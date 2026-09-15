from typing import Annotated
import typer
from pathlib import Path
from rich.text import Text
from rich.console import Group
from rich.live import Live

from .app import app
import llmpipe.services.ssh_manager as ssh
import llmpipe.services.session_manager as session_manager
from llmpipe.config import LanguageModel, ContextWindow
import llmpipe.services.json_manager as json_manager
import llmpipe.ui.displays as display

FASTA_EXTENSIONS = {".fasta", ".fa", ".fna"}
    


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
        
        # Static table for unsynced sessions and finished synced sessions
        static_table = display.SessionTableView()
        
        # Get unsynced sessions saved info
        for session_info in session_manager.get_unsynced_sessions(logged_in):
            static_table.add_row(
                session_info=session_info,
                synced=False
            )
            
        if not logged_in:
            return
        
        # Get synced sessions saved info
        login_info = json_manager.load_login_info()
        synced_sessions = session_manager.get_synced_sessions()
        
        running_sessions = []
        
        for session_info in synced_sessions:
            json_manager.save_session_info(login_info["hostname"], login_info["username"], session_info)
            if session_info["finished"] == False:
                running_sessions.append(session_info)   
            else:
                static_table.add_row(session_info=session_info, synced=True)
                
        # Print unsynced and finished synced sessions
        static_table.print_table()
        
        if not running_sessions:
            return
        
        # Keep updating the unfinished synced sessions
        _update_running_sessions(running_sessions=running_sessions, login_info=login_info)
                            
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
    login_info: dict[str]
):
    # Dynamic table for newly finished sessions
    dynamic_table = display.SessionTableView()
    # Live progress updater
    progress_view = display.SessionProgressView()
    
    render_group = Group(dynamic_table.get_table_object(), progress_view.get_progress_object())
    
    # Stream readers to read real-time remote logs
    readers = [
        session_manager.StreamReader(
            ssh.get_active_command(f"tail -n 1 -f ~/LLMPipe/{session_info["name"]}.log")
        )   
        for session_info in running_sessions
    ]
    
    for session_info in running_sessions:
            progress_view.add_session(session_info=session_info)
            
    with Live(render_group, refresh_per_second=4, vertical_overflow="ellipsis"):
        while running_sessions:
            to_remove = []
            
            for i, session_info in enumerate(running_sessions):
                chunk, connected = readers[i].read_chunks()
                if not connected:
                    display.show_error_message("Connection dropped.")
                    raise typer.Exit(2)
                
                if chunk == "\n" or chunk == "":
                    continue
                
                session_info = session_manager.get_session_progress(session_info=session_info, chunk=chunk)
                  
        
                progress_view.update_session(
                    session_info=session_info
                )   
                    
                if session_info["finished"]:
                    to_remove.append(i)
                    
            # Remove finished sessions in reversed order
            for i in reversed(to_remove):
                session_info = running_sessions.pop(i)
                progress_view.remove_session(session_info=session_info)
                dynamic_table.add_row(session_info=session_info, synced=True)
                
                json_manager.save_session_info(login_info["hostname"], login_info["username"], session_info)
                
                readers[i].stop_process()
                readers.pop(i)
    
            
    
            
    
            
            

            
            