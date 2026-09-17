# LLMPipeCLI
A command-line interface for using DNA language models using typer. This project means to make using DNA language models easier for people not used to running LLMs but used to running terminal commands.

## Prerequisites

Make sure you have [uv](https://docs.astral.sh/uv/) installed on your system:

Using the orginal script:
```bash
curl -LsSf https://astral.sh/uv/install.sh| sh
```
Alteratively, you can use a package manager, such as pip.

## Quickstart

### Cloning the repository
Clone the repository to your system using `git clone <repository-link>`.

### Setting up the environment
Run `uv sync`, you will see the `.venv` directory appearing in the project folder. Activate the newly created virtual environment.

### Running the entry point
You can now run the program with `python src/llmpipe/main.py` or simply by running `uv run llmpipe`.
The latter also works outside the virtual environment. 

## Installing as a global CLI tool

### Option 1: Install from GitHub directly
```bash
uv tool install git+<repository-link>
```

### Option 2: Install from local directory
```bash
git clone <repository-link>
uv tool install .
```

## Using the CLI
**Note: you can replace "uv run llmpipe" with just "llmpipe" in all commands below if you have installed the CLI globally.**

### Running commands
Run `uv run llmpipe --help` to see what commands you can run and run them with `uv run llmpipe [options] {command} [arguments]`

### Setting up the remote part
The remote script is provided in `LLMPipeCLI/remote script/llm_pipe.py`

Install the remote script using the following commands:
```bash
uv run llmpipe login [hostname] [username]
uv run llmpipe remote-install [path_to_script]
```