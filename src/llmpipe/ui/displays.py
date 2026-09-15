from rich.progress import Progress, TaskID
from rich.text import Text
from rich.table import Table
from rich.live import Live
from rich.progress import Progress, BarColumn, TextColumn, Task, TaskProgressColumn, TimeRemainingColumn, ProgressColumn

from .console import console

class DynamicColumn(ProgressColumn):
    def __init__(self, column_type, attribute_name: str, **kwargs):
        super().__init__()
        self.column = column_type(**kwargs)
        self.attribute_name = attribute_name
        
    def get_table_column(self):
        return self.column.get_table_column()
        
    def render(self, task: Task) -> Text:
        enabled = task.fields.get(self.attribute_name)
        if not enabled:
            return Text("")  # Hide progress
        return self.column.render(task) # Show progress

class InstallProgressView:
    def __init__(self, progress: Progress):
        self.progress = progress
        self.task = None

    def start(self):
        self.task = self.progress.add_task(description="Downloading miniconda...", total=100)
        
    def update(self, percentage: int, description: str):
        self.progress.update(self.task, completed=percentage, description=description)
        
class SessionTableView:
    def __init__(self):
        self.table = Table(box=None, show_header=False)
        
        self.table.add_column("name")
        self.table.add_column("server")
        self.table.add_column("synced")
        self.table.add_column("progress")
        
    def get_table_object(self) -> Table:
        return self.table
        
    def add_row(self, session_info: dict, synced: bool):
        name = _get_session_desc_name(session_name=session_info["name"])
        server = _get_session_desc_server(hostname=session_info["hostname"], username=session_info["username"])
        synced_desc = _get_session_desc_synced(synced=synced)
        status = _get_session_desc_status(
            sequence_count=session_info["sequence_count"],
            sequence_progress=session_info["sequence_progress"],
            processing=False,
            finished=session_info["finished"],
        )
        
        self.table.add_row(name, server, synced_desc, status)   
    
    def print_table(self):
        console.print(self.table, highlight=False)
        
    def stop_live(self):
        if self.live_view:
            self.live.stop()
    
class SessionProgressView:
    def __init__(self):
        
        progress = Progress(
            TextColumn("{task.fields[desc_name]}"),
            TextColumn("{task.fields[desc_server]}"),
            TextColumn("{task.fields[desc_synced]}"),
            DynamicColumn(BarColumn, "show_live_progress"),
            DynamicColumn(TaskProgressColumn, "show_live_progress"),
            TextColumn("{task.fields[desc_status]}"),
            DynamicColumn(TextColumn, "show_eta", text_format="{task.fields[desc_eta]}"),
            auto_refresh=False
        )
        
        self.progress = progress
        self.tasks: dict[str, TaskID] = {}
        
    def get_progress_object(self) -> Progress:
        return self.progress
        
    def add_session(self, session_info: dict):
        session_id = f'{session_info["name"]}:{session_info["username"]}@{session_info["hostname"]}'
        
        finished = session_info["finished"]
        desc_name = _get_session_desc_name(
            session_name=session_info["name"]
        )
        desc_server = _get_session_desc_server(
            hostname=session_info["hostname"],
            username=session_info["username"]
        )
        desc_synced = _get_session_desc_synced(
            synced=True
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
            show_eta=False
        )
        
    def update_session(self, session_info: dict):
        session_id = f'{session_info["name"]}:{session_info["username"]}@{session_info["hostname"]}'    
        
        finished = session_info["finished"]
        desc_name = _get_session_desc_name(
            session_name=session_info["name"]
        )
        desc_server = _get_session_desc_server(
            hostname=session_info["hostname"],
            username=session_info["username"]
        )
        desc_synced = _get_session_desc_synced(
            synced=True
        )
        desc_status = _get_session_desc_status(
            sequence_count=session_info["sequence_count"],
            sequence_progress=session_info["sequence_progress"],
            processing=session_info["processing"],
            finished=finished
        )
        if not finished and session_info["eta"]:
            desc_eta = _get_session_desc_eta(
                eta=session_info["eta"]
            )
        else:
            desc_eta = ""
        
        self.progress.update(
            self.tasks[session_id], 
            desc_name=desc_name,
            desc_server=desc_server,
            desc_synced=desc_synced,
            desc_status=desc_status,
            desc_eta=desc_eta,
            completed=session_info["progress"],
            show_live_progress=not finished,
            show_eta=not finished
        )
        
    def remove_session(self, session_info: dict):
        session_id = f'{session_info["name"]}:{session_info["username"]}@{session_info["hostname"]}' 
        
        self.progress.remove_task(self.tasks[session_id])   

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
def _get_session_desc_eta(
    eta: str
):
    return f"Sequence ETA: {eta}"

            
        
            