from typing import Annotated
import typer
from rich.progress import Progress, BarColumn, TextColumn
from pathlib import Path

from .app import app
import llmpipe.ui.displays as display
import llmpipe.services.ssh_manager as ssh
import llmpipe.services.json_manager as json_manager

CONDA_BIN = "$HOME/miniconda3/bin/conda"
CONDA_INIT = "source $HOME/miniconda3/etc/profile.d/conda.sh && "
ENV_DIR = "$HOME/miniconda3/envs/plantcad_env"
ENV_BIN = f"{ENV_DIR}/bin"
ENV_PIP = f"{ENV_BIN}/pip"

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
    if not json_manager.load_login_info():
        display.show_not_logged_in_error()
        raise typer.Exit(1)
    
    with Progress(
        TextColumn("{task.description}"),
        BarColumn()
    ) as progress:
        view = display.InstallProgressView(progress)
        view.start()

        with ssh.SSHSession() as ssh_session:
            def run_step(command: str, percentage: int, message: str, fail_message: str, exit_code: int):
                view.update_message(message)
                
                try:
                    ssh_session.execute_command(command)
                except ssh.RemoteCommandError:
                    progress.stop()
                    display.show_error_message(f"{fail_message}:\n" + str(e))
                    raise typer.Exit(exit_code)    
                
                view.update_percentage(percentage)
                
            try:
                ssh_session.execute_command('test -d "~/miniconda3"')
            except ssh.RemoteCommandError:
                run_step(
                    "curl -L -O https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh && "
                    "bash Miniconda3-latest-*.sh -b -p $HOME/miniconda3 -u && "
                    "rm Miniconda3-latest-*.sh",
                    10,
                    "Downloading miniconda...",
                    "Miniconda failed to install",
                    3
                )
            
            run_step(
                f"{CONDA_INIT}"
                f"{CONDA_BIN} tos accept --override-channels --channel https://repo.anaconda.com/pkgs/main && "
                f"{CONDA_BIN} tos accept --override-channels --channel https://repo.anaconda.com/pkgs/r",
                20,
                "Accepting Anaconda channel terms...",
                "Failed to accept miniconda TOS",
                4
            )
            
            package_check = (
                f'{ENV_BIN}/python -c "import importlib.metadata as m, sys; '
                "versions = {d.metadata.get('Name', '').lower().replace('_', '-'): d.version "
                "for d in m.distributions()}; "
                "expected = {'torch': '2.3.1+cu121', 'torchvision': '0.18.1+cu121', 'torchaudio': '2.3.1+cu121', "
                "'causal-conv1d': '1.5.0.post8', 'mamba-ssm': '2.2.2', 'transformers': '4.40.0', "
                "'pyvcf3': None, 'scipy': '1.12.0', 'biopython': None, 'xgboost': '2.0.3', "
                "'scikit-learn': '1.4.0', 'matplotlib': None, 'gpn': None}; "
                "missing = [n for n, v in expected.items() if not versions.get(n) or "
                "(v is not None and versions[n] != v)]; "
                "sys.exit(1 if missing else 0)\""
            )
     
            _, exit_status = ssh_session.execute_command(package_check, ignore_non_zero_exit=True, get_returncode=True)
            packages_installed = (exit_status == 0)
                
            if packages_installed:
                view.update_message("Uploading the remote script...")
                view.update_percentage(95)
            else:
                run_step(
                    f"{CONDA_INIT}"
                    f"if [ -d \"$HOME/miniconda3/envs/plantcad_env\" ]; then {CONDA_BIN} env remove -n plantcad_env -y; fi && "
                    f"{CONDA_BIN} create -y --name plantcad_env python=3.10.19 && "
                    f"{CONDA_BIN} install -n plantcad_env -c nvidia -c bioconda -y cuda-nvcc cuda-toolkit mafft",
                    40,
                    "Creating the plantcad environment...",
                    "Failed to set up environment",
                    5
                )
                
                run_step(
                    f"{ENV_PIP} install torch==2.3.1 torchvision==0.18.1 torchaudio==2.3.1 "
                    "--index-url https://download.pytorch.org/whl/cu121",  
                    65,
                    "Installing PyTorch...",
                    "Failed to install PyTorch",
                    5
                )
                
                run_step(
                    f"export CUDA_HOME={ENV_DIR} && "
                    f"export PATH={ENV_BIN}:$PATH && "
                    f"export LD_LIBRARY_PATH={ENV_DIR}/lib:$LD_LIBRARY_PATH && "
                    f"{ENV_PIP} install https://github.com/Dao-AILab/causal-conv1d/releases/download/v1.5.0.post8/causal_conv1d-1.5.0.post8+cu12torch2.3cxx11abiFALSE-cp310-cp310-linux_x86_64.whl",
                    70,
                    "Installing causal-conv1d...",
                    "Failed to install causal-conv1d",
                    5
                )
                
                run_step(
                    f"{CONDA_INIT}"
                    f"export PATH={ENV_BIN}:$PATH && "
                    f"{ENV_PIP} install mamba-ssm==2.2.2 transformers==4.40.0 git+https://github.com/dridk/PyVCF3.git@master scipy==1.12.0 biopython xgboost==2.0.3 scikit-learn==1.4.0 matplotlib --no-build-isolation",
                    80,
                    "Installing additional Python packages...",
                    "Failed to install Python package",
                    5
                )
                
                run_step(
                    "echo -e 'torch==2.3.1\ntorchvision==0.18.1\ntorchaudio==2.3.1\ntransformers==4.40.0' > constraints.txt && "
                    f"{ENV_PIP} install git+https://github.com/SilvanCodes/gpn.git -c constraints.txt && "
                    "rm constraints.txt",
                    90,
                    "Installing GPN...",
                    "Failed to install GPN",
                    5
                ) 
            
            view.update_percentage(95)
            view.update_message("Uploading the remote script...")
            
            ssh_session.execute_command("mkdir -p ~/LLMPipe")
            ssh_session.execute_command("mkdir -p ~/LLMPipe/results")
        
            try:
                ssh_session.upload_file(remote_script_path, "LLMPipe/llm_pipe.py")
            except ssh.RemoteCommandError as e:
                progress.stop()
                display.show_error_message("Failed to upload remote script:\n" + str(e))
                raise typer.Exit(6)  
            
            view.update_percentage(100)
            view.update_message("Installed.")
            raise typer.Exit(0)

