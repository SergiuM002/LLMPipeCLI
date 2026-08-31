from typing import Annotated
import typer

import llmpipe.services.ssh_manager as ssh
import llmpipe.ui.displays as display
from llmpipe.services.json_manager import save_login_info, load_login_info, delete_login_info
from llmpipe.cli.app import app

@app.command()
def view_login():
    """Prints the username and hostname with which the user is logged in."""
    if (ssh_active := ssh.ssh_active()) == 1:
        display.show_not_logged_in_error()
        raise typer.Exit(1)
    elif ssh_active == 2:
        display.show_connection_timeout_error()
        raise typer.Exit(2)
    
    login_info = load_login_info()
    display.show_success_message(f"You are logged in to {login_info["hostname"]} as {login_info["username"]}.")

@app.command()
def login(
    hostname: Annotated[str, typer.Argument(help="Hostname of the server")],
    username: Annotated[str, typer.Argument(help="Login username for the specified server")],
    persist: Annotated[str, typer.Option("--persist", "-p", help="Idle timeout for login (e.g. 30m, 1h, yes)")] = "1h"
):
    """Logs the user in with the specified idle timeout."""
    return_code = ssh.login(hostname, username, persist)
    
    match return_code:
        case 0:
            display.show_success_message("Login successful!")
            save_login_info(hostname, username)
            raise typer.Exit(0)
        case 1:
            display.show_bold_colored_message("Already logged in, updated timeout timer.", "yellow")
            raise typer.Exit(1)
        case 2:
            display.show_connection_timeout_error()
            raise typer.Exit(2)
            
@app.command()
def logout():
    """Logs the user out."""
    return_code = ssh.logout()
    
    match return_code:
        case 0:
            display.show_success_message("Logged out successfully!")
            delete_login_info()
            raise typer.Exit(0)
        case 1:
            display.show_bold_colored_message("Already logged out.", "yellow")
            raise typer.Exit(1)
    
    