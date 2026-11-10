from pathlib import Path
from enum import Enum
import llmpipe
from importlib.resources import files

CONFIG_PATH =Path.home() / ".config" / "llmpipe"
SESSIONS_PATH = CONFIG_PATH / "sessions"
REMOTE_SCRIPT_PATH = files(llmpipe).joinpath("remote_script/llm_pipe.py")

class LanguageModel(str, Enum):
    C = "caduceus"
    P1 = "plantcaduceus1"
    P2S = "plantcaduceus2s"
    P2M = "plantcaduceus2m"
    P2L = "plantcaduceus2l"
    
class ContextWindow(int, Enum):
    BP512 = 512
    BP1024 = 1024
    BP2048 = 2048
    BP4096 = 4096
    BP8192 = 8192