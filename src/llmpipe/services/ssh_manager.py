from pathlib import Path
import paramiko
import re
from collections import defaultdict
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from queue import Queue, Empty
import threading
import stat

from llmpipe.config import SOCKET_PATH, SOCKET_DIR
from llmpipe.ui.displays import show_simple_message
from .exceptions import ConnectionError, LoginError, RemoteCommandError
from .json_manager import load_login_info

CONFIG_PATH = Path.home() / ".config" / "llmpipe"
KEY_PATH = CONFIG_PATH / "keys" / "id_ed25519"
LOGIN_INFO_PATH = CONFIG_PATH / "login-info.json"

class StreamReader:
    def __init__(self, stdout):
        self.LINE_SPLIT_PATTERN = re.compile(r'\r\n|\r|\n')
        self._stdout = stdout
        self._channel = stdout.channel
        self._queue = Queue()
        self.is_connected = True
        self._thread = threading.Thread(target=self._populate_queue, daemon=True)
        self._thread.start()

    def _populate_queue(self):
        """Background worker that continuously reads stdout."""
        buffer = ""

        while self.is_connected:
            try:
                # Check if SSH transport is still alive
                transport = self._channel.get_transport()
                if transport is None or not transport.is_active():
                    self.is_connected = False
                    break

                chunk = self._channel.recv(1024)

                # Append data and maintain line boundaries
                buffer += chunk.decode("utf-8", errors="replace")
                while True:
                    search_target = buffer[:-1] if buffer.endswith("\r") else buffer
                    match = self.LINE_SPLIT_PATTERN.search(search_target)

                    if not match:
                        break

                    line = buffer[: match.start()]
                    buffer = buffer[match.end() :]
                    self._queue.put(line)

            except (OSError, paramiko.SSHException):
                self.is_connected = False
                break

        if buffer:
            self._queue.put(buffer)

    

    def read_chunks(self) -> tuple[str, bool]:
        """Fetch all currently accumulated chunks from the queue."""
        chunks = []
        while True:
            try:
                item = self._queue.get_nowait()
                chunks.append(item)
            except Empty:
                break
        return "".join(chunks), self.is_connected   

    def close_channel(self):
        self._channel.close()

class SSHSession:
    def __init__(self):
        self.hostname = None
        self.username = None
        self.port = None
        self.client = None

    def __enter__(self):
        login_info = load_login_info()

        if login_info:
            self.client = self._get_authenticated_client()
            self.hostname = login_info["hostname"]
            self.username = login_info["username"]
            self.port = login_info["port"]
        else:
            raise LoginError()
        return self

    def __exit__(self, exc_type, exc, tb):
        if self.client:
            self.client.close()

    def is_ssh_alive(self) -> bool:
        """Checks if the SSH connection is actively alive and responding."""
        transport = self.client.get_transport()
        
        # Check if the local transport object still running
        if transport is None or not transport.is_active():
            return False
        
        # Send a tiny SSH_MSG_IGNORE packet
        try:
            transport.send_ignore()
            return True
        except (paramiko.SSHException, OSError):
            return False
            
    def check_session_in_progress(self, session_name: str) -> int:
        _, tmux_returncode = self.execute_command(f"tmux has-session -t ={session_name} 2>/dev/null", get_returncode=True, ignore_non_zero_exit=True)
        _, log_returncode = self.execute_command(f"[ -f ~/LLMPipe/{session_name}.log ]", get_returncode=True, ignore_non_zero_exit=True)
        
        if tmux_returncode != 0 and log_returncode != 0:
            return 1
        elif tmux_returncode == 0 and log_returncode == 0:
            return 0
        else:
            return 2
        
    def check_session_in_progress_bulk(self, session_names: str) -> list[int]:
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
        raw_output = self.execute_command(batch_cmd) or ""
        
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

    def upload_file(self, local_path: str, remote_path: str):
        """Uploads file to server."""
        with self.client.open_sftp() as sftp:
            sftp.put(local_path, remote_path)
        
    def download_file(self, remote_path: str, local_path: str):
        """Downloads file from server."""    
        with self.client.open_sftp() as sftp:
            sftp.get(remote_path, local_path)

    def download_dir(self,  remote_path: str, local_path: str):
        """Recursively download a remote directory."""
        Path(local_path).parent.mkdir(parents=True, exist_ok=True)
        
        with self.client.open_sftp() as sftp:
            self._recursive_sftp_get(sftp, remote_path, local_path)

    def _recursive_sftp_get(self, sftp, remote_dir: str, local_dir: str):    
        Path(local_dir).mkdir(parents=True, exist_ok=True)

        for attr in sftp.listdir_attr(remote_dir):
            remote_path = f"{remote_dir}/{attr.filename}"
            local_path = Path(local_dir) / attr.filename
            
            # Check if remote_path is a directory
            if stat.S_ISDIR(attr.st_mode):
                self._recursive_sftp_get(sftp, remote_path, local_path)
            else:
                sftp.get(remote_path, local_path)

    def execute_command(self, command: str, get_returncode: bool = False, ignore_non_zero_exit: bool = False) -> str | tuple[str, int]:
        _, stdout, stderr = self.client.exec_command(command)
        output = stdout.read().decode("utf-8")
        error = stderr.read().decode("utf-8")
        exit_status = stdout.channel.recv_exit_status()
        stdout.channel.close()

        if exit_status != 0 and not ignore_non_zero_exit:
            raise RemoteCommandError(f"Remote command error for command {command}:\n {error}")

        return (output, exit_status) if get_returncode else output

    def stream_command(self, command: str):
        """Executes a command and yields output line-by-line in real time."""
        _, stdout, _ = self.client.exec_command(command, bufsize=1)
        
        return stdout

    def _get_authenticated_client(self) -> paramiko.SSHClient:
        """Creates a Paramiko client authenticated with the app's dedicated key."""
        config = load_login_info()

        try:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            # Authenticates instantly using the dedicated key
            client.connect(
                hostname=config["hostname"],
                port=config.get("port", 22),
                username=config["username"],
                key_filename=str(KEY_PATH),
                timeout=5,
            )
        except Exception as e:
            raise ConnectionError(f"Connection Error: {e}")
        return client
        
    def logout(self):
        """Removes local and remote key."""
        client = None
        try:
            client = self._get_authenticated_client()
            key = paramiko.Ed25519Key(filename=str(KEY_PATH))
            public_key_str = f"ssh-ed25519 {key.get_base64()} llmpipe-auto-generated"

            # Remove key from authorized keys
            cmd = rf"sed -i '\|{public_key_str}|d' ~/.ssh/authorized_keys"
            client.exec_command(cmd)
        except Exception as e:
            raise RuntimeError(f"Error while removing remote public key: {e}")
        finally:
            if client:
                client.close()

        KEY_PATH.unlink()
        LOGIN_INFO_PATH.unlink()

    def get_finished_remote_sessions(self) -> list[dict]:
        """Get the finished remote sessions.""" 
        if not LOGIN_INFO_PATH.exists():
            raise LoginError()
        
        cmd = "find ~/LLMPipe/results -mindepth 2 -maxdepth 2 -type f | sort"
        raw_files = self.execute_command(cmd) or ""
        
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

    def get_running_remote_sessions(self) -> list[dict]:
        """Get the running remote sessions."""   
        if not LOGIN_INFO_PATH.exists():
            raise LoginError()
        
        # Get active tmux sessions
        try:
            tmux_sessions = self.execute_command('tmux ls -F "#{session_name}"').splitlines()
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
        raw_output = self.execute_command(batch_cmd) or ""
        
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

def _get_or_create_key() -> paramiko.Ed25519Key:
    """Generates an Ed25519 key pair and returns a Paramiko Ed25519Key object."""
    KEY_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Generate the raw Ed25519 private key
    raw_key = ed25519.Ed25519PrivateKey.generate()

    # Serialize to standard OpenSSH private key format
    private_pem = raw_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.OpenSSH,
        encryption_algorithm=serialization.NoEncryption()
    )

    # Save to disk
    KEY_PATH.write_bytes(private_pem)

    # Restrict permissions on Linux/macOS
    try:
        KEY_PATH.chmod(0o600)
    except OSError:
        pass

    # Load into Paramiko
    return paramiko.Ed25519Key(filename=str(KEY_PATH))

def login(hostname: str, username: str, password: str, port: int = 22) -> None:
    """Authenticate, create and store private key locally and store public key remotely."""
    CONFIG_PATH.mkdir(parents=True, exist_ok=True)

    try: 
        with SSHSession() as ssh_session:
            ssh_session.logout()
    except LoginError:
        pass

    # Generate a dedicated Ed25519 key pair if it doesn't exist
    if not KEY_PATH.exists():
        key = _get_or_create_key()
        public_key_str = f"ssh-ed25519 {key.get_base64()} llmpipe-auto-generated"
    else:
        key = paramiko.Ed25519Key(filename=str(KEY_PATH))
        public_key_str = f"ssh-ed25519 {key.get_base64()} llmpipe-auto-generated"

    # Connect using the password to deploy the public key
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        client.connect(hostname=hostname, port=port, username=username, password=password, timeout=5)
        
        # Append public key to remote authorized_keys
        cmd = (
            f"mkdir -p ~/.ssh && chmod 700 ~/.ssh && "
            f"grep -qF '{public_key_str}' ~/.ssh/authorized_keys 2>/dev/null || "
            f"echo '{public_key_str}' >> ~/.ssh/authorized_keys && "
            f"chmod 600 ~/.ssh/authorized_keys"
        )
        _, stdout, stderr = client.exec_command(cmd)
        exit_status = stdout.channel.recv_exit_status()
        
        if exit_status != 0:
            err_msg = stderr.read().decode().strip()

            raise RemoteCommandError(f"Remote command failed (exit code {exit_status}): {err_msg}")
        client.close()
    except Exception as e:
        raise RuntimeError(f"Login failed: {e}")
