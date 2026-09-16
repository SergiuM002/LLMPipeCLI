import subprocess
from pathlib import Path
import re
from collections import defaultdict

from llmpipe.config import SOCKET_PATH, SOCKET_DIR
from llmpipe.ui.displays import show_simple_message
from .exceptions import ConnectionError, LoginError, RemoteCommandError
from .json_manager import load_login_info, logged_in_to_as

    
def get_base_ssh_cmd() -> list[str]:
    """Base SSH command targeting the multiplexed control socket."""
    return ["ssh", "-o", f"ControlPath={SOCKET_PATH}"]

def ssh_active() -> int:
    """Checks if the background SSH socket is active."""
    if not SOCKET_PATH.exists():
        return 1
    
    # Check if socket is active
    result = subprocess.run(
        get_base_ssh_cmd() + [
            "-o", "ServerAliveInterval=3",
            "-o", "ServerAliveCountMax=2",
            "-O", "check", 
            "placeholder_host"
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return 1

    check_connection_cmd = get_base_ssh_cmd() + [
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=3",
        "placeholder_host",
        "true",
    ]

    try:
        result = subprocess.run(check_connection_cmd, capture_output=True, timeout=3)
        return 0 
    except subprocess.TimeoutExpired:
        SOCKET_PATH.unlink(missing_ok=True)
        return 2
    
def get_active_command(command: str):
    cmd = get_base_ssh_cmd() + ["placeholder_host", command]
    
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        text=True,
        bufsize=1
    )
    
    try:
        return process
    except KeyboardInterrupt:
        process.terminate()
        process.wait()
            
def check_session_in_progress(session_name: str) -> int:
    tmux_return = subprocess.run(get_base_ssh_cmd() + ["placeholder_host", f"tmux has-session -t ={session_name} 2>/dev/null"])
    log_return = subprocess.run(get_base_ssh_cmd() + ["placeholder_host", f"[ -f ~/LLMPipe/{session_name}.log ]"])
    
    if tmux_return.returncode != 0 and log_return.returncode != 0:
        return 1
    elif tmux_return.returncode == 0 and log_return.returncode == 0:
        return 0
    else:
        return 2
    
def check_session_in_progress_bulk(session_names: str) -> list[int]:
    cmd_parts = []
    for s in session_names:
        cmd_parts.append(
            f'tmux has-session -t ={s} 2>/dev/null; '
            f'tx_rc=$?; '
            f'[ -f ~/LLMPipe/{s}.log ]; '
            f'lg_rc=$?; '
            f'echo "$tx_rc|$lg_rc|{s}"'
        )   
    
    batch_cmd = " ; ".join(cmd_parts)
    raw_output = execute_command(batch_cmd, capture_output=True) or ""
    
    status_list = []
    for line in raw_output.splitlines():
        parts = line.split("|", 2)
        
        if len(parts) > 3:
            raise RemoteCommandError
        
        tmux_return, log_return = parts[0], parts[1]
        
        if tmux_return != "0" and log_return != "0":
            status_list.append(1)
        elif tmux_return == "0" and log_return == "0":
            status_list.append(0)
        else:
            status_list.append(2)
            
    return status_list 

def upload_file(local_path: str, remote_path: str):
    """Uploads file using rsync."""
    login_info = load_login_info()
    remote_target = f"{login_info["username"]}@{login_info["hostname"]}:{remote_path}"
    
    ssh_cmd = f"ssh -o ControlPath={SOCKET_PATH}"
    
    cmd = [
        "rsync",
        "-avz",
        "--progress",  
        "-e", ssh_cmd,
        local_path,
        remote_target,
    ]
    
    # Run process and pass stdout/stderr through to terminal
    result = subprocess.run(cmd, capture_output=True)
    match result.returncode:
        case 0:
            return
        case 3 | 23 | 24:
            raise FileNotFoundError()
        case _:
            raise RemoteCommandError()
    
def download_file(remote_path: str, local_path: str, mkpath: bool=False):
    """Downloads file using rsync."""  
    if mkpath:
        Path(local_path).parent.mkdir(parents=True, exist_ok=True)
        
    login_info = load_login_info()
    remote_target = f"{login_info["username"]}@{login_info["hostname"]}:{remote_path}"
        
    ssh_cmd = f"ssh -o ControlPath={SOCKET_PATH}"
    
    cmd = [
        "rsync",
        "-avz",
        "--progress",  
        "-e", ssh_cmd,
        remote_target,
        local_path,
    ]
    
    # Run process and pass stdout/stderr through to terminal
    result = subprocess.run(cmd, capture_output=True, text=True)
    match result.returncode:
        case 0:
            return
        case 3 | 23 | 24:
            raise FileNotFoundError()
        case _:
            raise RemoteCommandError()
    
def execute_command(command: str, capture_output=False, capture_error: bool=False, timeout: int=10):
    if not SOCKET_PATH.exists():
        raise LoginError()
    
    cmd = get_base_ssh_cmd() + ["placeholder_host", command]
    
    try:
        result = subprocess.run(
            cmd, 
            timeout=timeout, 
            capture_output=capture_error or capture_output, 
            text=capture_error or capture_output
        )
        if result.returncode != 0:
            raise RemoteCommandError((result.stderr.strip() if capture_error or capture_output else ""))
    except subprocess.TimeoutExpired:
        raise ConnectionError()
        
    if capture_output:
        return result.stdout
        
def login(hostname: str, username: str, persist: str) -> int:
    """Authenticate and create the background SSH master socket."""
    SOCKET_DIR.mkdir(parents=True, exist_ok=True)

    # Check if a socket already exists and is active
    already_logged_in = False
    if SOCKET_PATH.exists():
        logout() 
        if logged_in_to_as(hostname, username):
            already_logged_in = True
        

    # Build the OpenSSH command to start the background socket
    # -f = background before command execution
    # -N = do not execute a remote command
    # Control options = create a master socket that can be reused for connection
    # ServerAlive options = delete the master socket after a time of disconnection
    ssh_cmd = [
        "ssh",
        "-fN",
        "-p", "22",
        "-o", "ConnectTimeout=5",
        "-o", "ControlMaster=yes",
        "-o", f"ControlPath={SOCKET_PATH}",
        "-o", f"ControlPersist={persist}",
        "-o", "ServerAliveInterval=3",
        "-o", "ServerAliveCountMax=2",
        f"{username}@{hostname}"
    ]

    show_simple_message(f"Connecting to [bold cyan]{username}@{hostname}:22[/bold cyan]...")
    
    # This inherits the user's interactive TTY for passwords/host key prompts
    result = subprocess.run(ssh_cmd, capture_output=True)

    if result.returncode == 0 and not already_logged_in:
        # Established connection successfully
        return 0
    elif result.returncode == 0 and already_logged_in:
        # Refreshed connection
        return 1
    else:
        # Could not establish connection
        return 2
    
def logout():
    """Close background SSH master socket."""
    if not SOCKET_PATH.exists():
        return 1
    
    # Tell OpenSSH master process to stop accepting connections and exit
    subprocess.run(
        get_base_ssh_cmd() + ["-O", "exit", "placeholder_host"],
        capture_output=True,
    )

    # Clean up socket file if left behind
    if SOCKET_PATH.exists():
        SOCKET_PATH.unlink(missing_ok=True)

    return 0

def get_finished_remote_sessions():
    """Get the finished remote sessions."""   
    if not SOCKET_PATH.exists():
        raise LoginError()
    
    cmd = "find ~/LLMPipe/results -mindepth 2 -maxdepth 2 -type f"
    raw_files = execute_command(cmd, capture_output=True) or ""
    
    # Group files by their parent directory (session name)
    dir_files = defaultdict(list)
    for filepath in raw_files.splitlines():
        p = Path(filepath)
        dir_files[p.parent.name].append(p.name)
        
    session_dicts = []
    for session_name, files in dir_files.items():
        # Validate expected file contents
        has_scores = f"{session_name}_scores_table0.csv" in files
        has_file_ids = "fileIDs.txt" in files
        
        if has_scores and has_file_ids:
            # There should be a csv file per sequence (minus 1 because of fileIDs.txt)
            sequence_count = len(files) - 1
            session_dicts.append(
                {
                    "name": session_name,
                    "sequence_count": sequence_count,
                    "sequence_progress": sequence_count,
                    "progress": 100,
                    "finished": True    
                }
            )
        
    return session_dicts

def get_running_remote_sessions():
    """Get the running remote sessions."""   
    if not SOCKET_PATH.exists():
        raise LoginError()
    
    # Get active tmux sessions
    try:
        tmux_sessions = execute_command('tmux ls -F "#{session_name}"', capture_output=True).splitlines()
    except RemoteCommandError:
        return []
        
    # Batch count and log inspections for ALL tmux sessions into 1 compound shell command
    cmd_parts = []
    for s in tmux_sessions:
        cmd_parts.append(
            f'if [ -f ~/LLMPipe/{s}.log ]; then '
            f'sc=$(grep -c "^>" ~/LLMPipe/{s}.fa 2>/dev/null || echo 0); '
            f'sp=$(grep -c -E "Processing windows: [0-9]+it " ~/LLMPipe/{s}.log 2>/dev/null || true); '
            f'last=$(tr "\r" "\n" < ~/LLMPipe/{s}.log | tail -n 1 ); '
            f'echo "{s}|$sc|$sp|$last"; '
            f'fi'
        )
        
    batch_cmd = " ; ".join(cmd_parts)
    raw_output = execute_command(batch_cmd, capture_output=True) or ""
    
    session_dicts = []
    for line in raw_output.splitlines():
        if not line.strip():
            continue
        
        # Parse the structured "|"-delimited result
        parts = line.split("|", 3)
        if len(parts) < 4:
            continue
        
        session_name, sequence_count, sequence_progress, last_log = parts[0], parts[1], parts[2], parts[3]
    
        match = re.search(r"Processing windows:\s*(\d+)%", last_log)
        progress = int(match.group(1)) if match else 0

        session_dicts.append(
            {
                "name": session_name,
                "sequence_count": int(sequence_count or 1),
                "sequence_progress": int(sequence_progress) + 1 or 1,
                "progress": progress,
                "finished": False    
            }
        )
        
    return session_dicts
            
