from typing import Annotated
import typer
from pathlib import Path
from rich.progress import Progress, BarColumn, TextColumn, Task, TaskProgressColumn, TimeRemainingColumn, ProgressColumn
from rich.live import Live
from rich.text import Text

from .app import app
import llmpipe.services.ssh_manager as ssh
import llmpipe.services.session_manager as session_manager
from llmpipe.config import LanguageModel, ContextWindow
import llmpipe.services.json_manager as json_manager
import llmpipe.ui.displays as display

FASTA_EXTENSIONS = {".fasta", ".fa", ".fna"}
    
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

def validate_fasta_file(path: Path) -> Path:
    if path.suffix.lower() not in FASTA_EXTENSIONS:
        valid_extensions = ", ".join(FASTA_EXTENSIONS)
        raise typer.BadParameter(f"File must be a FASTA ({valid_extensions}).")

@app.command()
def get_files(
    session_name: Annotated[str, typer.Argument(help="Name of the session")],
    download_path: Annotated[Path, typer.Argument(help="Download path", file_okay=True, dir_okay=True)] 
):
    """Download the result files of the specified session."""
    if (ssh_active := ssh.ssh_active()) == 1:
        display.show_not_logged_in_error()
        raise typer.Exit(1)
    elif ssh_active == 2:
        display.show_connection_timeout_error()
        raise typer.Exit(2)
    
    login_info = json_manager.load_login_info()
    if not json_manager.session_exists(login_info["hostname"], login_info["username"], session_name):
        display.show_error_message("The specified session does not exist.")
        raise typer.Exit(3)
      
    try:
        ssh.download_file(f"~/LLMPipe/results/{session_name}", download_path)
        display.show_success_message("Files transfered successfully.")
    except FileNotFoundError:
        display.show_error_message("Session directory is missing.")
    except ssh.RemoteCommandError:
        display.show_error_message("Something went wrong.")
        

@app.command()
def start_session(
    session_name: Annotated[str, typer.Argument(help="Name of the new session")],
    fasta_file: Annotated[
        Path, 
        typer.Argument(
            help="Path of the FASTA file to be scored", 
            exists=True, 
            file_okay=True, 
            dir_okay=True,
            readable=True,
            resolve_path=True
        )
    ],
    language_model: Annotated[LanguageModel, typer.Option(help="LLM used to score the FASTA")] = LanguageModel.P1,
    context_window: Annotated[ContextWindow, typer.Option(help="Context window given to the LLM")] = ContextWindow.BP512,
    align: Annotated[bool, typer.Option("--align", "-a", help="The sequences will be aligned before being scored")] = False
):
    """Start a session with the specified parameters."""
    if (ssh_active := ssh.ssh_active()) == 1:
        display.show_not_logged_in_error()
        raise typer.Exit(1)
    elif ssh_active == 2:
        display.show_connection_timeout_error()
        raise typer.Exit(2)
    
    return_code = session_manager.start_session(session_name, fasta_file, language_model, context_window, align)

    match return_code:
        case 1:
            display.show_error_message("One of the remote commands failed to run.")
        case 2:
            display.show_error_message("The remote script has not been set up.")
        case 3:
            display.show_error_message(f"A session with the name '{session_name}' already exists for this user.")
        case 0:
            display.show_success_message(f"Session '{session_name}' created successfully!")
            display.show_simple_message("Run 'llmpipe view-sessions' to see progress.")
            
            
            
@app.command()
def view_sessions():
    """View the active and completed sessions."""
    if ssh.ssh_active() == 0:
        logged_in = True
    else:
        logged_in = False
        
    try:
        running_sessions = []
        
        progress = Progress(
            TextColumn("{task.fields[desc_name]}"),
            TextColumn("{task.fields[desc_server]}"),
            TextColumn("{task.fields[desc_synced]}"),
            DynamicColumn(BarColumn, "show_live_progress"),
            DynamicColumn(TaskProgressColumn, "show_live_progress"),
            TextColumn("{task.fields[desc_status]}"),
            DynamicColumn(TextColumn, "show_eta", text_format="{task.fields[desc_eta]}"),
        )
        
        with Live(progress, vertical_overflow="visible") as live:
            view = display.SessionProgressView(progress)
            
            # Get unsynced sessions saved info
            for session_info in session_manager.get_unsynced_sessions(logged_in):
                view.add_session(
                    session_info=session_info,
                    synced=False
                )
                
            if not logged_in:
                return
            
            # Get synced sessions saved info
            login_info = json_manager.load_login_info()
            synced_sessions = session_manager.get_synced_sessions()
            
            for session_info in synced_sessions:
                view.add_session(
                    session_info=session_info,
                    synced=True
                )    
                json_manager.save_session_info(login_info["hostname"], login_info["username"], session_info)
            running_sessions = [d for d in synced_sessions if d.get("finished") == False]
            
            if not running_sessions:
                return
            
            _update_running_sessions(running_sessions=running_sessions, live=live, view=view, login_info=login_info)
                            
    except KeyboardInterrupt:
        for session_info in running_sessions:
            json_manager.save_session_info(login_info["hostname"], login_info["username"], session_info)
            
        display.show_simple_message("\nStopped viewing sessions.")
        raise typer.Exit(0)
    except FileNotFoundError:
        display.show_error_message("No sessions to view.")
        raise typer.Exit(1)
    
@app.command()
def delete_session(
    session_name: Annotated[str, typer.Argument(help="Name of the session to be deleted")] 
):
    """Delete hostname for specified user or logged in user."""
    if (ssh_active := ssh.ssh_active()) == 1:
        display.show_not_logged_in_error()
        raise typer.Exit(1)
    elif ssh_active == 2:
        display.show_connection_timeout_error()
        raise typer.Exit(2)
    
    login_info = json_manager.load_login_info()

    if not json_manager.session_exists(login_info["hostname"], login_info["username"], session_name):
        display.show_error_message("The specified session was not found for this user.")
        raise typer.Exit(3)   
    
    session_status = ssh.check_session_in_progress(session_name)
    
    if session_status == 0:
        delete = typer.confirm(f"Are you sure you want to delete running session '{session_name}'?")
    elif session_status == 2:
        display.show_warning_message(f"Tmux session or log file has been manually deleted. Session '{session_name}' broken.")   
        delete = typer.confirm(f"Are you sure you want to delete session '{session_name}'? ")
    else:
        delete = typer.confirm(f"Are you sure you want to delete session '{session_name}'? ")
        
    if not delete:
        raise typer.Exit(0)
    
    try:
        session_manager.delete_session(session_name, session_status, login_info["hostname"], login_info["username"])
        display.show_success_message(f"Session '{session_name}' deleted successfully.")
    except (FileNotFoundError, RuntimeError):
        display.show_error_message("The specified session was not found for this user.")
        raise typer.Exit(3)

@app.command()
def delete_all_sessions(
    
):
    """Deletes all synced sessions."""
    if (ssh_active := ssh.ssh_active()) == 1:
        display.show_not_logged_in_error()
        raise typer.Exit(1)
    elif ssh_active == 2:
        display.show_connection_timeout_error()
        raise typer.Exit(2)
    
    login_info = json_manager.load_login_info()

    if not json_manager.any_session_exists(login_info["hostname"], login_info["username"]):
        display.show_error_message("No session was found for this user.")
        raise typer.Exit(3)   
    
    delete = typer.confirm("Are you sure you want to delete all sessions? This may include still running sessions.")
    
    if not delete:
        display.show_simple_message("Delete aborted.")
        raise typer.Exit(0)
        
    sessions = json_manager.load_sessions_info(login_info["hostname"], login_info["username"])  
    
    errors = 0
    
    for session in sessions:
        try:
            session_status = ssh.check_session_in_progress(session["name"])
            session_manager.delete_session(session["name"], session_status, login_info["hostname"], login_info["username"])
        except (FileNotFoundError, RuntimeError):
            display.show_warning_message(f"Could not delete session '{session["name"]}'.")
            errors += 1
            
    if errors == 0:
        display.show_success_message("All sessions deleted successfully!")
    else:
        display.show_warning_message(f"All sessions deleted except {errors}.")
            
def _update_running_sessions(
    running_sessions: list[dict], 
    live: Live,
    view: display.SessionProgressView,
    login_info: dict[str]
):
    # Stream readers to read real-time remote logs
    readers = []
    for session_info in running_sessions:
        readers.append(session_manager.StreamReader(ssh.get_active_command(f"tail -n 1 -f ~/LLMPipe/{session_info["name"]}.log")))

    while True:
        for i, session_info in enumerate(running_sessions):
            chunk, connected = readers[i].read_chunks()
            if not connected:
                live.stop()
                display.show_error_message("Connection dropped.")
                raise typer.Exit(2)
            
            if chunk == "\n" or chunk == "":
                continue
            
            session_info = session_manager.get_session_progress(session_info=session_info, chunk=chunk)
                
            view.update_session(
                session_info=session_info,
                synced=True,
            )   
            if session_info["finished"] == False:
                running_sessions[i] = session_info
            else:
                json_manager.save_session_info(login_info["hostname"], login_info["username"], session_info)
                running_sessions.pop(i)
                readers[i].stop_process()
                readers.pop(i)
        if not running_sessions:
            break
            
    
            
    
            
            

            
            