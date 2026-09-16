import threading
import re
from queue import Queue, Empty
from pathlib import Path

from llmpipe.config import LanguageModel, ContextWindow, SESSIONS_PATH
from . import ssh_manager as ssh
from . import json_manager as json_manager

class StreamReader:
    def __init__(self, process):
        self._process = process
        self._stream = process.stdout
        self._queue = Queue()
        self.is_connected = True
        self._thread = threading.Thread(target=self._populate_queue, daemon=True)
        self._thread.start()

    def _populate_queue(self):
        """Background worker that continuously reads stdout."""
        while True:
            line = self._stream.readline()
            
            if not line:  # Connection dropped
                self.is_connected = False
                self._queue.put(None)  # Sentinel value signaling stream closure
                break

            if line:
                self._queue.put(line)

    def read_chunks(self) -> tuple[str, bool]:
        """Fetch all currently accumulated chunks from the queue."""
        chunks = []
        while True:
            try:
                item = self._queue.get_nowait()
                if item is None:  # Disconnection sentinel consumed
                    self.is_connected = False
                    break
                chunks.append(item)
            except Empty:
                break
        return "".join(chunks), self.is_connected
    
    def stop_process(self):
        """Terminates the process."""
        self._process.terminate()
        self._process.wait()
        

def start_session(session_name: str, fasta_file: Path, language_model: LanguageModel, context_window: ContextWindow, align: bool):
    login_info = json_manager.load_login_info()
    if json_manager.session_exists(login_info["hostname"], login_info["username"], session_name):
        return 3
    
    try:
        ssh.upload_file(str(fasta_file), f"~/LLMPipe/{session_name}.fa")
    except ssh.RemoteCommandError:
        return 2
    
    try:
        ssh.execute_command(f"touch ~/LLMPipe/{session_name}.log")
    except ssh.RemoteCommandError:
        return 1
                
    command = (
        "cd ~/LLMPipe && "
        "source ../miniconda3/etc/profile.d/conda.sh && "
        "conda activate plantcad_env && "
        "python llm_pipe.py -f "
    )
    
    if align:
        command += "-m "
        
    match language_model:
        case LanguageModel.C:
            command += "-c "
        case LanguageModel.P1:
            command += "-p1 "   
        case LanguageModel.P2S:
            command += "-p2s "   
        case LanguageModel.P2M:
            command += "-p2m "    
        case LanguageModel.P2L:
            command += "-p2l "   
            
    match context_window:
        case ContextWindow.BP512:
            command += "-w 512 "    
        case ContextWindow.BP1024:
            command += "-w 1024 "  
        case ContextWindow.BP2048:
            command += "-w 2048 "   
        case ContextWindow.BP4096:
            command += "-w 4096 "  
        case ContextWindow.BP8192:
            command += "-w 8192 "   
        

    command += (
        f"{session_name}.fa > {session_name}.log 2>&1 && " 
        f"rm ~/LLMPipe/{session_name}.fa && "
        f"rm ~/LLMPipe/{session_name}.log && "
        f"tmux kill-session -t {session_name}"
    )
    
    try:
        ssh.execute_command(f"tmux new-session -d -s {session_name}")
    except ssh.RemoteCommandError:
        return 1

    try:
        ssh.execute_command(f'tmux send-keys -t {session_name} "{command}" C-m')  
    except ssh.RemoteCommandError:
        return 1
    
    sequence_count = _get_fasta_sequence_count(fasta_file)
    sequence_progress = 1
    progress = 0
    session_info = {
        "name": session_name, 
        "sequence_count": sequence_count, 
        "sequence_progress": sequence_progress,
        "progress": progress,
        "finished": False
    }
    
    login_info = json_manager.load_login_info()
    json_manager.save_session_info(login_info["hostname"], login_info["username"], session_info)
    
    return 0

def get_unsynced_sessions(logged_in: bool):
    if logged_in:
        login_info = json_manager.load_login_info()
        logged_in_hostname = login_info["hostname"]
        logged_in_username = login_info["username"]
    else:
        logged_in_hostname = ""
        logged_in_username = ""
    
    hostnames = [d.name for d in SESSIONS_PATH.iterdir() if d.is_dir()]
    usernames = {}
    
    for hname in hostnames:
        usernames[hname] = [d.name for d in Path(SESSIONS_PATH / hname).iterdir() if d.is_dir() and (d.name != logged_in_username or hname != logged_in_hostname)]
    
    # Load in unsynced sessions
    for hname in hostnames:
        for uname in usernames[hname]:
            yield from (d | {"hostname": hname, "username": uname} for d in json_manager.load_sessions_info(hname, uname)) 
         
def get_synced_sessions():   
    login_info = json_manager.load_login_info()
    
    # Filter for unfinished sessions and show finished sessions
    synced_sessions_info = json_manager.load_sessions_info(login_info["hostname"], login_info["username"])
    
    if not synced_sessions_info:
        return []
    
    synced_sessions_status = _get_sessions_status(synced_sessions_info)
    
    synced_sessions_with_status = [d | {"hostname": login_info["hostname"], "username": login_info["username"]} for d in 
        _get_sessions_with_finished_state(sessions=synced_sessions_info, sessions_status=synced_sessions_status)] 
    
    return synced_sessions_with_status    
    
def get_session_progress(session_info: dict, chunk: str):     
    session_info["eta"] = None
    
    if "Script finished." in chunk:
        session_info["finished"] = True  
        session_info["processing"] = False
        return session_info
    
    if re.search(r"Processing windows: \d+it ", chunk):
        session_info["sequence_progress"] += 1
        session_info["progress"] = 0
        session_info["processing"] = False
    
    
    lines = [line.strip() for line in chunk.splitlines() if line.strip()]
    if not lines:
        return session_info
    
    line = lines[-1]
    
    
    if match := re.search(r"Processing windows:\s*(\d+)%", line):
        if eta_match := re.search(r"<((\d+:)*\d+),", line):
            session_info["eta"] = str(eta_match.group(1))   
        else:
            session_info["eta"] = None

        session_info["progress"] = int(match.group(1))
        session_info["processing"] = False
    else:
        session_info["progress"] = 100
        session_info["processing"] = True

    return session_info
    
        
def delete_session(session_name: str, session_status: int, hostname: str, username: str):
 
    json_manager.delete_session(hostname, username, session_name)
            
    if session_status == 0:
        try:
            ssh.execute_command(
                f"tmux kill-session -t {session_name}; "
                f"rm ~/LLMPipe/{session_name}.log; "
                f"rm ~/LLMPipe/{session_name}.fa"
            )
        except ssh.RemoteCommandError:
            pass
    elif session_status == 1:
        try:
            ssh.execute_command(f"rm -r ~/LLMPipe/results/{session_name}")
        except ssh.RemoteCommandError:
            pass        
        
def save_sessions_info(unfinished_sessions: list[dict], finished_sessions: list[dict], login_info: dict):
    for unfinished_session in unfinished_sessions:
        json_manager.save_session_info(login_info["hostname"], login_info["username"], unfinished_session)
    for finished_session in finished_sessions:
        json_manager.save_session_info(login_info["hostname"], login_info["username"], finished_session)
        
def _get_fasta_sequence_count(path: Path) -> int:
    with open(path, "r") as f:
        return sum(1 for line in f if line.startswith(">"))
        
def _get_sessions_status(sessions_info: list[dict[str]]) -> list[str]:
    session_names = [session_info["name"] for session_info in sessions_info]
    sessions_status_codes = ssh.check_session_in_progress_bulk(session_names)
    
    sessions_status = []
    
    for status_code in sessions_status_codes:
        if status_code == 0:
            sessions_status.append("in_progress")
        elif status_code == 1:
            sessions_status.append ("finished")  
            
    return sessions_status
    
def _get_sessions_with_finished_state(sessions: list[dict[str]], sessions_status: list[str]):
    for session_info, session_status in zip(sessions, sessions_status):
        if session_status == "finished":
            session_info["finished"] = True
        if session_status == "in_progress":
            session_info["finished"] = False
            
    return sessions




        