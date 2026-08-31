class ConnectionError(RuntimeError):
    """Custom exception raised when the connection is broken."""
    pass
class LoginError(RuntimeError):
    """Custom exception raised when the user is not logged in."""
    pass
class RemoteCommandError(RuntimeError):
    """Custom exception raised when the remote command returns a non-zero code."""
    pass