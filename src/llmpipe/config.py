from pathlib import Path
from enum import Enum

CONFIG_PATH =Path.home() / ".config" / "llmpipe"
SESSIONS_PATH = CONFIG_PATH / "sessions"
SOCKET_DIR = CONFIG_PATH / "sockets"
SOCKET_PATH = SOCKET_DIR / "master.sock"

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