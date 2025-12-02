
"""
Hook for managing ptwordlists symlink creation/deletion.

Provides `install()` and `uninstall()` functions that can be
called automatically after the tool is installed or uninstalled.

- install(): Creates or updates a symlink at /usr/share/wordlists/penterep
             pointing to the installed package's wordlists directory.
- uninstall(): Removes the symlink if it exists.
"""

import os
import shutil
import sys
from pathlib import Path
from importlib import resources
from typing import Tuple

def install():
    """Create or update the ptwordlists symlink after installation."""
    try:
        status, msg = _register_wordlists_symlink()
    except Exception as e:
        pass

def uninstall():
    """Remove the ptwordlists symlink after uninstallation."""
    try:
        _remove_wordlists_symlink()
    except Exception as e:
        pass

def _register_wordlists_symlink(dst: str = "/usr/share/wordlists/penterep", force: bool = True) -> Tuple[bool, str]:
    """
    Create (or update) a symlink at `dst` pointing to the installed package's wordlists directory.

    Args:
        dst: Destination path for the symlink (default: '/usr/share/wordlists/penterep').
        force: If True, remove any existing file/dir/symlink at dst and replace it.
               If False, do not overwrite an existing non-symlink path.

    Returns:
        (success: bool, message: str)

    Raises:
        RuntimeError for unexpected failures (e.g. cannot locate package data).
    """
    dst_path = Path(dst)
    try:
        src = _locate_package_wordlists()
        src_path = Path(src)

        # ensure parent exists
        dst_parent = dst_path.parent
        dst_parent.mkdir(parents=True, exist_ok=True)

        # If target exists
        if dst_path.exists() or dst_path.is_symlink():
            # If it is already the correct symlink -> nothing to do
            if dst_path.is_symlink():
                try:
                    current_target = os.readlink(str(dst_path))
                except OSError:
                    current_target = None

                if current_target == str(src_path):
                    return True, f"Symlink already present: {dst} -> {current_target}"
                # If symlink points elsewhere and force is True -> remove it
                if force:
                    dst_path.unlink()
                else:
                    return False, f"Destination {dst} is a symlink to {current_target}; not overwriting (force=False)."

            else:
                # dst exists and is not a symlink (file or directory)
                if not force:
                    return False, f"Destination {dst} exists and is not a symlink; not overwritten (force=False)."
                # remove file or directory
                if dst_path.is_dir():
                    shutil.rmtree(dst_path)
                else:
                    dst_path.unlink()

        # create symlink
        os.symlink(str(src_path), str(dst_path))
        return True, f"Created symlink: {dst} -> {src}"

    except PermissionError:
        return False, "Permission denied: need root privileges to create symlink at " + dst
    except RuntimeError as e:
        # propagate expected package-location errors as failures
        return False, str(e)
    except Exception as e:
        # unexpected
        raise

def _locate_package_wordlists() -> str:
    """
    Locate the installed ptwordlists 'wordlists' directory using importlib.resources.
    Returns absolute path to the directory as a string.
    Raises RuntimeError if not found.
    """
    try:
        p = resources.files("ptwordlists").joinpath("wordlists")
        src = str(p)
        if not Path(src).exists():
            raise RuntimeError(f"wordlists directory not found inside ptwordlists package: {src}")
        return src
    except Exception as exc:
        raise RuntimeError(f"Failed to locate ptwordlists.wordlists: {exc}") from exc


def _remove_wordlists_symlink(dst: str = "/usr/share/wordlists/penterep") -> Tuple[bool, str]:
    """
    Remove the symlink at dst if it exists. If dst is a non-symlink path, do not remove it.

    Returns:
        (success: bool, message: str)
    """
    dst_path = Path(dst)
    if not dst_path.exists() and not dst_path.is_symlink():
        return True, f"No symlink found at {dst}."

    # Only remove if it's a symlink or if it's a directory that points to package? We will only remove symlink.
    if dst_path.is_symlink():
        try:
            dst_path.unlink()
            return True, f"Removed symlink {dst}."
        except PermissionError:
            return False, f"Permission denied removing {dst}; run as root."
        except Exception as e:
            return False, f"Failed to remove {dst}: {e}"
    else:
        return False, f"{dst} exists but is not a symlink; not removed."