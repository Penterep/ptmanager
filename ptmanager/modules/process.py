import os
import signal


class Process:
    def __init__(self, PID: int) -> None:
        self.PID = PID

    def is_running(self) -> bool:
        """Check if process is running"""
        if self.PID is None:
            return False
        try:
            os.kill(self.PID, 0) # Does not terminate, just checks if running
            return True
        except ProcessLookupError:
            return False

    def kill(self) -> bool:
        """Tries to kill process with PID"""
        try:
            os.kill(self.PID, signal.SIGTERM) # Tries to kill process
            return True
        except ProcessLookupError:
            return False