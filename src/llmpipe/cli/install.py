from typing import Annotated
import typer
from rich.progress import Progress, BarColumn, TextColumn
from pathlib import Path

from .app import app
import llmpipe.ui.displays as display
import llmpipe.services.ssh_manager as ssh

@app.command()
def remote_install(
    remote_script_path: Annotated[
        Path, 
        typer.Argument(
            help="Path of the llm_pipe remote script", 
            exists=True, 
            file_okay=True, 
            dir_okay=True,
            readable=True,
            resolve_path=True
        )]
):
    """Install the remote script and environment on the specified server."""
    if (ssh_active := ssh.ssh_active()) == 1:
        display.show_not_logged_in_error()
        raise typer.Exit(1)
    elif ssh_active == 2:
        display.show_connection_timeout_error()
        raise typer.Exit(2)
    
    CONDA_BIN = "$HOME/miniconda3/bin/conda"
    CONDA_INIT = "source $HOME/miniconda3/etc/profile.d/conda.sh && "
    
    
    with Progress(
        TextColumn("{task.description}"),
        BarColumn()
    ) as progress:
        view = display.InstallProgressView(progress)
        view.start()
        
        try:
            ssh.execute_command('test -d "~/miniconda3"')
        except ssh.RemoteCommandError:
            try:
                ssh.execute_command(
                    "curl -L -O https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh && "
                    "bash Miniconda3-latest-*.sh -b -p $HOME/miniconda3 -u && "
                    "rm Miniconda3-latest-*.sh",
                    capture_error=True,
                    timeout=None
                )
            except ssh.RemoteCommandError as e:
                progress.stop()
                display.show_error_message("Miniconda failed to install:\n" + str(e))
                raise typer.Exit(3)
        
        view.update(10, "Setting up miniconda...")
        
        try:
            ssh.execute_command(
                f"{CONDA_INIT}"
                f"{CONDA_BIN} tos accept --override-channels --channel https://repo.anaconda.com/pkgs/main && "
                f"{CONDA_BIN} tos accept --override-channels --channel https://repo.anaconda.com/pkgs/r",
                capture_error=True,
                timeout=None
            )
        except ssh.RemoteCommandError:
            progress.stop()
            display.show_error_message("Failed to accept miniconda TOS:\n" + str(e))
            raise typer.Exit(4)
        
        view.update(20, "Setting up environment...")
        
        remove_command = ""
        try:
            ssh.execute_command(f'test -d "~/miniconda3/envs/plantcad_env"')
        except ssh.RemoteCommandError:
            remove_command = f"{CONDA_BIN} env remove -n plantcad_env -y && "
            
        try:
            ssh.execute_command(
                f"{CONDA_INIT}"
                f"{remove_command}"
                f"{CONDA_BIN} create -y --name plantcad_env python=3.10.19 && "
                f"{CONDA_BIN} install -n plantcad_env -c nvidia -c bioconda -y cuda-nvcc cuda-toolkit mafft",
                capture_error=True  ,
                timeout=None
            )
        except ssh.RemoteCommandError:
            progress.stop()
            display.show_error_message("Failed to set up environment:\n" + str(e))
            raise typer.Exit(5)
            
        view.update(40, "Installing extensions...")
        
        ENV_DIR = "$HOME/miniconda3/envs/plantcad_env"
        ENV_BIN = f"{ENV_DIR}/bin"
        ENV_PIP = f"{ENV_BIN}/pip"
        
        try:
            ssh.execute_command(
                f"{ENV_PIP} install torch==2.3.1 torchvision==0.18.1 torchaudio==2.3.1 --index-url https://download.pytorch.org/whl/cu121",
                capture_error=True,
                timeout=None
            )
        except ssh.RemoteCommandError:
            progress.stop()
            display.show_error_message("Failed to install extensions:\n" + str(e))
            raise typer.Exit(5)
        
        view.update(65, "Installing extensions...")
        
        try:
            ssh.execute_command(
                f"export CUDA_HOME={ENV_DIR} && "
                f"export PATH={ENV_BIN}:$PATH && "
                f"export LD_LIBRARY_PATH={ENV_DIR}/lib:$LD_LIBRARY_PATH && "
                f"{ENV_PIP} install https://github.com/Dao-AILab/causal-conv1d/releases/download/v1.5.0.post8/causal_conv1d-1.5.0.post8+cu12torch2.3cxx11abiFALSE-cp310-cp310-linux_x86_64.whl",
                capture_error=True,
                timeout=None
            )
        except ssh.RemoteCommandError:
            progress.stop()
            display.show_error_message("Failed to install extensions:\n" + str(e))
            raise typer.Exit(5)
        
        view.update(70, "Installing extensions...")
        
        try:
            ssh.execute_command(
                f"{CONDA_INIT}"
                f"export PATH={ENV_BIN}:$PATH && "
                f"{ENV_PIP} install mamba-ssm==2.2.2 transformers==4.40.0 git+https://github.com/dridk/PyVCF3.git@master scipy==1.12.0 biopython xgboost==2.0.3 scikit-learn==1.4.0 matplotlib --no-build-isolation",
                capture_error=True,
                timeout=None
            )
        except ssh.RemoteCommandError:
            progress.stop()
            display.show_error_message("Failed to install extensions:\n" + str(e))
            raise typer.Exit(5)
        
        view.update(90, "Installing extensions...")
        
        try:
            ssh.execute_command(
                f"{ENV_PIP} install --quiet git+https://github.com/SilvanCodes/gpn.git",
                capture_error=True,
                timeout=None
            )
        except ssh.RemoteCommandError:
            progress.stop()
            display.show_error_message("Failed to install extensions:\n" + str(e))
            raise typer.Exit(5)
        
        view.update(95, "Uploading remote script...")
        
        ssh.execute_command("mkdir -p ~/LLMPipe")
        ssh.execute_command("mkdir -p ~/LLMPipe/results")
    
        ssh.upload_file(remote_script_path, "~/LLMPipe/llm_pipe.py")
        
        view.update(100, "Installed.")