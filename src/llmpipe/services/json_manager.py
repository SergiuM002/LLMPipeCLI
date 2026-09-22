import json
from pathlib import Path

from llmpipe.config import SESSIONS_PATH, CONFIG_PATH


def save_session_info(hostname: str, username: str, session_info: dict):
    SAVE_PATH = SESSIONS_PATH / hostname / username / "sessions.json"
    
    # Only keep relevant keys
    wanted_info = ["name", "sequence_count", "sequence_progress", "progress", "finished"]
    clean_info = {k: v for k, v in session_info.items() if k in wanted_info} 
    
    try:
        with open(SAVE_PATH, "r") as f:
            saved_sessions = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        saved_sessions = []
        
    replaced = False
    for i, session in enumerate(saved_sessions):
        if session.get("name") == clean_info.get("name"):
            saved_sessions[i] = clean_info
            replaced = True
            break
        
    if not replaced:
        saved_sessions.append(clean_info)
        
    Path(SAVE_PATH).parent.mkdir(parents=True, exist_ok=True)
        
    with open(SAVE_PATH, "w") as f:
        json.dump(saved_sessions, f, indent=4)
        
def load_sessions_info(hostname: str, username: str):
    SAVE_PATH = SESSIONS_PATH / hostname / username / "sessions.json"
    
    try:
        with open(SAVE_PATH, "r") as f:
            saved_sessions = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        Path(SAVE_PATH).parent.mkdir(parents=True, exist_ok=True)
        with open(SAVE_PATH, "w") as f:
            json.dump([], f)
            saved_sessions = []
        
    return saved_sessions

def delete_session(hostname: str, username: str, session_name: str):
    SAVE_PATH = SESSIONS_PATH / hostname / username / "sessions.json"
    
    if not Path(SAVE_PATH).exists():
        raise FileNotFoundError
    
    sessions = load_sessions_info(hostname, username)
    
    deleted = False
    for session in sessions:
        if session["name"] == session_name:
            sessions.remove(session)
            deleted = True
            
    if not deleted:
        raise RuntimeError
            
    with open(SAVE_PATH, "w") as f:
        json.dump(sessions, f, indent=4)
        
def session_exists(hostname: str, username: str, session_name: str) -> bool:
    SAVE_PATH = SESSIONS_PATH / hostname / username / "sessions.json"
    
    if not Path(SAVE_PATH).exists():
        return False
    
    sessions = load_sessions_info(hostname, username)
        
    for session in sessions:
        if session["name"] == session_name:
            return True
        
    return False

def any_session_exists(hostname: str, username: str) -> bool:
    SAVE_PATH = SESSIONS_PATH / hostname / username / "sessions.json"
        
    if not Path(SAVE_PATH).exists():
        return False
        
    sessions_info = load_sessions_info(hostname, username)
    
    return sessions_info and any(sessions_info)


def save_login_info(hostname: str, username: str, port: int):
    LOGIN_INFO_PATH = CONFIG_PATH / "login-info.json"

    Path(LOGIN_INFO_PATH).parent.mkdir(parents=True, exist_ok=True)
    
    login_info = {
        "hostname": hostname,
        "username": username,
        "port": port
    }
    
    with open(LOGIN_INFO_PATH, "w") as f:
        json.dump(login_info, f, indent=4)    
        
def load_login_info():
    LOGIN_INFO_PATH = CONFIG_PATH / "login-info.json"

    try:
        with open(LOGIN_INFO_PATH, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        with open(LOGIN_INFO_PATH, "w") as f:
            json.dump([], f)
    
def delete_login_info():
    LOGIN_INFO_PATH = CONFIG_PATH / "login-info.json"
    
    Path(LOGIN_INFO_PATH).parent.mkdir(parents=True, exist_ok=True)
    
    with open(LOGIN_INFO_PATH, "w") as f:
        json.dump({}, f, indent=4)    
        
def logged_in_to_as(hostname: str, username: str) -> bool:
    login_info = load_login_info()

    if not login_info:
        return False
    
    return hostname == login_info["hostname"] and username == login_info["username"]