import sys
from ptlibs import ptprinthelper

from ptlibs import ptmisclib

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
