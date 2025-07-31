import sys

from ptlibs import ptprinthelper, ptmisclib

def prompt_confirmation(message: str = None, confirm_message: str = "Are you sure?", bullet_type="TEXT") -> bool:
    try:
        if message:
            ptprinthelper.ptprint(message, bullet_type=bullet_type)
        action = input(f'{confirm_message.rstrip()} (y/n): ').upper().strip()
        if action == "Y":
            return True
        elif action == "N":# or action == "":
            return False
        else:
            return prompt_confirmation(message, confirm_message, bullet_type)
    except KeyboardInterrupt:
        print("\nInterrupted by user.")
        sys.exit(1)


def temp_manager():
    """Temp management function"""
    temp_path = ptmisclib.get_penterep_temp_dir()
    ptprinthelper.ptprint(f"Temp path: {temp_path}", "TITLE", condition=True, colortext=False)
    item_count, size_bytes = ptmisclib.read_temp_dir()
    ptprinthelper.ptprint(f"Item count: {item_count}, Size: {size_bytes}bytes", "TEXT", condition=True, colortext=False, indent=0, end="\n\n")
    if prompt_confirmation(confirm_message="Clear temp?"):
        if ptmisclib.clear_temp_dir():
            ptprinthelper.ptprint(f"Temp cleared.", "OK", condition=True, colortext=False)
    sys.exit(0)


import termios
import tty
import select
import threading

class InputBlocker:
    """
    Context manager that temporarily disables terminal input echo and discards all user keystrokes.

    This is useful for scenarios where user input should be ignored (e.g., during spinners or critical
    operations), without cluttering the terminal or requiring user interaction.

    Usage:
        with InputBlocker():
            do_something()  # User input is hidden and discarded during this block.

    Methods:
        __enter__(): Sets terminal to cbreak mode, disables echo, and starts input-draining thread.
        __exit__(): Restores terminal settings and stops background thread.
        flush_input(): Optionally flushes any remaining keystrokes from the input buffer.
    """
    def __enter__(self):
        self.fd = sys.stdin.fileno()
        self.old_settings = termios.tcgetattr(self.fd)
        tty.setcbreak(self.fd)
        new_settings = termios.tcgetattr(self.fd)
        new_settings[3] = new_settings[3] & ~termios.ECHO  # turn off echo
        termios.tcsetattr(self.fd, termios.TCSADRAIN, new_settings)

        # Start background thread to eat any keystrokes
        self._stop = False
        self._thread = threading.Thread(target=self._drain_input)
        self._thread.daemon = True
        self._thread.start()
        return self

    def _drain_input(self):
        """
        Background thread function that reads and discards keystrokes from stdin
        while the blocker is active.
        """
        while not self._stop:
            rlist, _, _ = select.select([sys.stdin], [], [], 0.05)
            if rlist:
                try:
                    sys.stdin.read(1)
                except (OSError, KeyboardInterrupt):
                    break

    def flush_input(self):
        """
        Manually flushes the input buffer by reading all available keystrokes.
        Useful if you want to discard any input after the blocking phase.
        """
        # Optional extra flush
        while True:
            rlist, _, _ = select.select([sys.stdin], [], [], 0)
            if not rlist:
                break
            sys.stdin.read(1)

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._stop = True
        self._thread.join()
        termios.tcsetattr(self.fd, termios.TCSADRAIN, self.old_settings)