import sys
from ptlibs import ptprinthelper


def prompt_confirmation(message: str, confirm_message: str = "Are you sure?", bullet_type="TEXT") -> bool:
    try:
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