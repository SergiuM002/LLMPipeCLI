from typing import Annotated
import typer

import llmpipe.services.ssh_manager as ssh
import llmpipe.services.json_manager as json_manager
import llmpipe.ui.displays as display
from llmpipe.services.json_manager import save_login_info, load_login_info, delete_login_info
from llmpipe.cli.app import app

@app.command()
def view_login():
    """Prints the username and hostname with which the user is logged in."""
    if not (login_info := load_login_info()):
        display.show_bold_colored_message("You are not logged in.", "red")
        raise typer.Exit(1)

    display.show_success_message(f"You are logged in to {login_info["hostname"]} as {login_info["username"]}.")
    raise typer.Exit(0)

@app.command()
def login(
    hostname: Annotated[str, typer.Argument(help="Hostname of the server")],
    username: Annotated[str, typer.Argument(help="Login username for the specified server")],
    port: Annotated[str, typer.Option("--port", "-p", help="The port to be used for the connection.")] = 22
):
    """Logs the user in with the specified idle timeout."""
    if json_manager.logged_in_to_as(hostname, username):
        display.show_bold_colored_message("Already logged in.", "yellow")
        raise typer.Exit(1)

    password = typer.prompt("Password", hide_input=True)

    try:
        ssh.login(hostname=hostname, username=username, password=password, port=port)
    except (RuntimeError, ssh.RemoteCommandError) as e:
        display.show_error_message(e)
        raise typer.Exit(2)

    json_manager.save_login_info(hostname, username, port)

    display.show_success_message("Successfully logged in!")
    raise typer.Exit(0)
            
@app.command()
def logout():
    """Logs the user out."""
    try:
        with ssh.SSHSession() as ssh_session:
            ssh_session.logout()
    except ssh.LoginError:
        display.show_bold_colored_message("Already logged out.", "yellow")
        raise typer.Exit(1)
    except RuntimeError as e:
        display.show_error_message(e)
        raise typer.Exit(2)

    display.show_success_message("Logged out successfully!")
    raise typer.Exit(0)

    
   

    
    