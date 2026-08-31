from rich.progress import Progress, TaskID
from rich.text import Text

from .console import console

class InstallProgressView:
    def __init__(self, progress: Progress):
        self.progress = progress
        self.task = None

    def start(self):
        self.task = self.progress.add_task(description="Downloading miniconda...", total=100)
        
    def update(self, percentage: int, description: str):
        self.progress.update(self.task, completed=percentage, description=description)
    
class SessionProgressView:
    def __init__(self, progress: Progress):
        self.progress = progress
        self.tasks: dict[str, TaskID] = {}
        
    def add_session(self, session_info: dict, synced: bool):
        session_id = f"{session_info["name"]}:{session_info["username"]}@{session_info["hostname"]}"
        
        finished = session_info["finished"]
        desc_name = _get_session_desc_name(
            session_name=session_info["name"]
        )
        desc_server = _get_session_desc_server(
            hostname=session_info["hostname"],
            username=session_info["username"]
        )
        desc_synced = _get_session_desc_synced(
            synced=synced
        )
        desc_status = _get_session_desc_status(
            sequence_count=session_info["sequence_count"],
            sequence_progress=session_info["sequence_progress"],
            processing=False,
            finished=finished
        )
            
        self.tasks[session_id] = self.progress.add_task(
            "",
            desc_name=desc_name,
            desc_server=desc_server,
            desc_synced=desc_synced,
            desc_status=desc_status,
            total=100, 
            completed=session_info["progress"],
            show_live_progress=False if finished else True,
            show_eta=False if finished or not synced else True
        )
        
    def update_session(self, session_info: dict, synced: bool, reset: bool=False):
        session_id = f"{session_info["name"]}:{session_info["username"]}@{session_info["hostname"]}"    
        
        finished = session_info["finished"]
        desc_name = _get_session_desc_name(
            session_name=session_info["name"]
        )
        desc_server = _get_session_desc_server(
            hostname=session_info["hostname"],
            username=session_info["username"]
        )
        desc_synced = _get_session_desc_synced(
            synced=synced
        )
        desc_status = _get_session_desc_status(
            sequence_count=session_info["sequence_count"],
            sequence_progress=session_info["sequence_progress"],
            processing=session_info["processing"],
            finished=finished
        )
            
        if not reset:
            self.progress.update(
                self.tasks[session_id], 
                desc_name=desc_name,
                desc_server=desc_server,
                desc_synced=desc_synced,
                desc_status=desc_status,
                completed=session_info["progress"],
                show_live_progress=False if finished else True,
                show_eta=False if finished or not synced else True
            )
        else:
            self.progress.reset(
                self.tasks[session_id], 
                desc_name=desc_name,
                desc_server=desc_server,
                desc_synced=desc_synced,
                desc_status=desc_status,
                completed=0,
                start=True,
                show_live_progress=False if finished else True,
                show_eta=False if finished or not synced else True
            )
        

def show_simple_message(message: str):
    """Shows custom message."""
    console.print(message, highlight=False)

def show_error_message(error_message: str):
    """Shows custom errror."""
    console.print(f"[bold red]Error:[/bold red] [red]{error_message}[/red]")
    
def show_warning_message(warning_message: str):
    """Shows custom warning."""
    console.print(f"[bold yellow]Warning:[/bold yellow] [yellow]{warning_message}[/yellow]") 
    
def show_not_logged_in_error():
    """Shows not logged in error."""
    show_error_message("You are not logged in.")
    
def show_connection_timeout_error():
    """Shows connection timeout error"""
    show_error_message("Connection timeout.")
    
def show_success_message(success_message: str):
    """Shows custom success message."""
    console.print(f"[bold green]{success_message}[/bold green]") 
    
def show_bold_colored_message(message: str, color: str):
    """Shows custom bold message with the specified color."""
    console.print(f"[bold {color}]{message}[/bold {color}]") 
    
def _get_session_desc_name(
    session_name: str
):
    return (f"[bold]{session_name}[/bold]")
    
def _get_session_desc_server(
    hostname: str, 
    username: str, 
):    
    return f"{username}@{hostname}"  

def _get_session_desc_synced(
    synced: bool
):
    return (" [bold green](synced)[/bold green]:" if synced else " [bold yellow](unsynced)[/bold yellow]:") # Differentiate between synced and unsynced

def _get_session_desc_status(
    sequence_count: int, 
    sequence_progress: int, 
    processing: bool, 
    finished: bool
):
    return ((f"{sequence_progress}/{sequence_count} " if not finished else "(finished)") + # Diferentiate between finished and not
        ("processing..." if processing and not finished else "")) # Differentiate between processing and not
        

            
        
            