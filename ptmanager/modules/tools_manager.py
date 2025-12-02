import subprocess
import re
import os
import sys; sys.path.extend([__file__.rsplit("/", 1)[0], os.path.join(__file__.rsplit("/", 1)[0], "modules")])
import requests
import time
import threading
import importlib
import itertools
import json

from ptlibs import ptjsonlib, ptprinthelper, ptmisclib
from ptlibs.ptprinthelper import get_colored_text

from concurrent.futures import ThreadPoolExecutor

class ToolsManager:
    def __init__(self, ptjsonlib: ptjsonlib.PtJsonLib, use_json: bool) -> None:
        self.ptjsonlib = ptjsonlib
        self.use_json = use_json
        self._stop_spinner = False
        self._is_sudo = os.geteuid() == 0
        self._is_penterep_venv = self.is_penterep_venv("/opt/penterep-tools/penterep-tools")
        self.script_list = self._get_script_list_from_api()
        self._installed_versions_cache = {}

    def _print_tools_table(self, tools: list[str] = None, action: str = None, status_map: dict[str, str] = None) -> None:
        """
        Prints a table of available tools, showing installed and latest versions,
        and optionally prints status messages per tool from status_map.

        Args:
            tools (list[str] | None): List of tool names to print. If None, prints all.
            action (str | None): Action name for context (install/update/delete) - used for default status messages.
            status_map (dict[str, str] | None): Optional dict mapping tool names to status messages to display instead of blank.
        """
        if tools is None:
            tools = [tool["name"] for tool in self.script_list]

        # Remove duplicates and normalize case (lowercase)
        tools = list(dict.fromkeys([t.lower() for t in tools]))

        installed_versions = self._get_installed_versions_map(tools)

        print(f"{get_colored_text('Tool name', 'TITLE')}{' '*9}{get_colored_text('Installed', 'TITLE')}{' '*10}{get_colored_text('Latest', 'TITLE')}{' '*8}{get_colored_text('Status', 'TITLE') if status_map else ''}")

        print(f"{'-'*20}{'-'*19}{'-'*19}{'-'*6}{'-'*(15 if status_map else 0)}")

        name_col_width = 20
        local_ver_col_width = 10
        remote_ver_col_width = 10
        status_col_width = 15

        for tool_name in tools:
            # Find version from script_list
            remote_version = "-"
            for tool in self.script_list:
                if tool["name"] == tool_name:
                    remote_version = tool["version"]
                    break

            is_installed, local_version = self.check_if_tool_is_installed(tool_name, installed_versions)

            status = ""
            if status_map and tool_name in status_map:
                status = status_map[tool_name].strip()
            elif action:
                status = ""

            print(f"{tool_name:<{name_col_width}} {local_version:<{local_ver_col_width}}      {remote_version:<{remote_ver_col_width}}    {status:<{status_col_width}}")

    def _check_if_tool_exists(self, tool_name: str, script_list: list[dict]) -> bool:
        return any(tool_name == script["name"].lower() for script in script_list)


    def check_if_tool_is_installed(self, tool_name: str, installed_versions: dict[str, str]) -> tuple[bool, str]:
        """
        Check if a tool is installed by looking it up in the installed_versions dictionary.

        Args:
            tool_name (str): The tool name to check.
            installed_versions (dict[str, str]): Mapping of installed tool names (lowercase) to their versions.

        Returns:
            tuple[bool, str]: Tuple where first element is True if installed, False otherwise,
                            and second element is the installed version or "-" if not installed.
        """
        tool_key = tool_name
        if tool_key in installed_versions:
            return True, installed_versions[tool_key]
        else:
            return False, "-"

    def _get_installed_versions_map(self, tool_names: list[str]) -> dict[str, str]:
        """
        Returns a mapping of installed tool names to their version strings using `pip show`.

        This method performs a single `pip show` call with multiple tool names to efficiently
        determine which tools are currently installed in the environment and retrieve their versions.

        Args:
            tool_names (list[str]): List of tool names to check (as registered in PyPI / pip).

        Returns:
            dict[str, str]: Dictionary where keys are lowercase tool names and values are
                            their installed version strings. Tools not found will be omitted.
        """
        if not tool_names:
            return {}

        try:
            result = subprocess.run(
                ["pip", "show", *tool_names],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                check=False
            )
        except Exception:
            return {}

        installed_versions = {}
        current_name = None

        for line in result.stdout.splitlines():
            if line.startswith("Name:"):
                current_name = line.split(":", 1)[1].strip().lower()
            elif line.startswith("Version:") and current_name:
                version = line.split(":", 1)[1].strip()
                installed_versions[current_name] = version
                current_name = None  # reset for next block

        return installed_versions

    def _get_script_list_from_api(self) -> list:
        """
        Retrieve available tools from remote API and fetch their current versions from PyPI.

        Displays a spinner while fetching data.

        Returns:
            list of dict: List of tools with their names and versions, sorted alphabetically.

        Raises:
            Calls self.ptjsonlib.end_error() internally on errors during retrieval.
        """
        stop_event = threading.Event()

        def spinner_func():
            """Display animated spinner in terminal while data is being fetched."""
            spinner = itertools.cycle(["|", "/", "-", "\\"])
            spinner_dots = itertools.cycle(["."] * 2 + [".."] * 4 + ["..."] * 6)
            sys.stdout.write("\033[?25l")  # Hide cursor
            sys.stdout.flush()
            try:
                while not stop_event.is_set():
                    symbol = next(spinner)
                    dots = next(spinner_dots)
                    text = f"[{get_colored_text(symbol, 'TITLE')}] Retrieving tools {dots}"
                    sys.stdout.write("\r" + text + " " * 10)  # clear to eol approx
                    sys.stdout.flush()
                    time.sleep(0.1)
            finally:
                sys.stdout.write("\r" + " " * 40 + "\r")  # Clear line
                sys.stdout.write("\033[?25h")  # Show cursor
                sys.stdout.flush()

        def fetch_tool_info(tool):
            """
            Fetch version info for a given PyPI package.

            Args:
                tool (str): Name of the tool/package.

            Returns:
                dict | None: Dictionary with name and version, or None if fetch fails.
            """
            try:
                response = requests.get(f'https://pypi.org/pypi/{tool}/json')
                if response.status_code == 200:
                    data = response.json()
                    return {"name": tool, "version": data["info"]["version"]}
            except:
                return None

        spinner_thread = threading.Thread(target=spinner_func, daemon=True)
        spinner_thread.start()

        try:
            url = "https://raw.githubusercontent.com/Penterep/ptmanager/main/ptmanager/available_tools.txt"
            available_tools = requests.get(url).text.split("\n")
            tools = sorted(set(tool.strip().lower() for tool in available_tools if tool.strip() and not tool.startswith("#")))

            with ThreadPoolExecutor(max_workers=10) as executor:
                script_list = [res for res in executor.map(fetch_tool_info, tools) if res]

        except Exception as e:
            stop_event.set()
            spinner_thread.join()
            sys.stdout.flush()
            self.ptjsonlib.end_error(f"Error retrieving tools from API:", details="Cannot retrieve response from target server.", condition=False)

        stop_event.set()
        spinner_thread.join()

        return sorted(script_list, key=lambda x: (x['name'] in ('ptlibs', 'ptmanager'), x['name']))


    def prepare_install_update_delete_tools(self, tools2prepare: list[str], action: str | None = None) -> None:
        """
        Prepares and executes install, update, or delete actions on specified tools.

        Args:
            tools2prepare (list[str]): List of tool names or ['all'].
            action (str | None): One of 'install', 'update', 'delete'. Determines the pip action to perform.

        Behavior:
            - Verifies existence of specified tools.
            - Prints current status and intended action.
            - Executes pip commands.
            - Updates the displayed tool table with results (success/failure/status).
            - Handles special cases like protected tools (ptlibs, ptmanager).
            - Skips redundant actions (e.g. already installed/deleted/up-to-date).
        """
        if not tools2prepare:
            print("No tools specified.")
            self._print_tools_table()
            return

        if self._is_penterep_venv and not self._is_sudo:
            self.ptjsonlib.end_error(f"Please run script as sudo for those operations.", self.use_json)

        tools_set = list(dict.fromkeys([tool.lower() for tool in tools2prepare]))
        if "all" in tools_set:
            tools_set = [tool["name"] for tool in self.script_list]

        valid_tools = [t for t in tools_set if self._check_if_tool_exists(t, self.script_list)]
        invalid_tools = [t for t in tools_set if not self._check_if_tool_exists(t, self.script_list)]

        if invalid_tools:
            print()
            self.ptjsonlib.end_error(f"Unrecognized Tool(s): [{', '.join(invalid_tools)}]", self.use_json)

        if action == "install":
            self._install_tools(valid_tools)
        elif action == "update":
            self._update_tools(valid_tools)
        elif action == "delete":
            self._delete_tools(valid_tools)
        else:
            self.ptjsonlib.end_error(f"Unknown action '{action}' specified.", self.use_json)

    def _install_tools(self, valid_tools: list[str]) -> None:
        """
        Installs the specified tools using pip, updates and prints the status table.

        Args:
            valid_tools (list[str]): List of tool names to install.

        Behavior:
            - Checks which tools are already installed.
            - Prints status showing which tools are already installed and which are being installed.
            - Runs pip install on tools not yet installed.
            - Updates the status map with results (success/failure).
            - Registers successfully installed tools.
            - Refreshes and prints the updated tools status table.
        """
        rows_count = len(self.script_list) + 2
        installed_versions = self._get_installed_versions_map(valid_tools)

        tools_installed = [t for t in valid_tools if t in installed_versions]
        tools_not_installed = [t for t in valid_tools if t not in installed_versions]

        status_map = {}
        for tool in valid_tools:
            if tool in tools_installed:
                status_map[tool] = "Already installed"
            else:
                status_map[tool] = "Installing..."

        self._print_tools_table(tools=[tool["name"] for tool in self.script_list], status_map=status_map)

        if not tools_not_installed:
            return

        pip_args = [sys.executable, "-m", "pip", "install"] + tools_not_installed
        result = subprocess.run(pip_args, capture_output=True, text=True)

        final_installed_versions = self._get_installed_versions_map(valid_tools)

        for tool in valid_tools:
            if tool in installed_versions and tool in final_installed_versions:
                status_map[tool] = "Already installed"
            elif tool in final_installed_versions:
                status_map[tool] = "Installed: OK"
                self.run_hook(tool, "register")
                self.run_hook(tool, "install")
            else:
                status_map[tool] = "Install failed"

        print(f"\033[{rows_count}A", end="")
        self._print_tools_table(tools=[tool["name"] for tool in self.script_list], status_map=status_map)
        print()


    def _update_tools(self, valid_tools: list[str]) -> None:
        """
        Updates the specified installed tools using pip, and prints status updates.

        Args:
            valid_tools (list[str]): List of tool names to update.

        Behavior:
            - Checks installed and not installed tools.
            - Compares installed versions to latest versions.
            - Only runs upgrade on tools that are out-of-date.
            - Updates and displays status accordingly.
        """
        rows_count = len(self.script_list) + 2
        installed_versions = self._get_installed_versions_map(valid_tools)
        latest_versions = {tool["name"]: tool.get("version", "") for tool in self.script_list}

        status_map = {}
        tools_to_update = []
        tools_not_installed = []

        # Classify tools by installed/not installed and version status
        for tool in valid_tools:
            latest_version = latest_versions.get(tool, "")
            installed_version = installed_versions.get(tool)

            if installed_version is None:
                status_map[tool] = "Not installed — please install first"
                tools_not_installed.append(tool)
            elif installed_version == latest_version:
                status_map[tool] = "Already up-to-date"
            else:
                status_map[tool] = "Updating..."
                tools_to_update.append(tool)

        self._print_tools_table(tools=[tool["name"] for tool in self.script_list], status_map=status_map)

        if not tools_to_update:
            return  # No tools need updating

        # Run pip upgrade only on tools that need it
        pip_args = [sys.executable, "-m", "pip", "install", "--upgrade"] + tools_to_update
        subprocess.run(pip_args, capture_output=True, text=True)

        # Refresh installed versions after upgrade
        final_installed_versions = self._get_installed_versions_map(valid_tools)

        # Update status based on whether upgrade succeeded
        for tool in tools_to_update:
            final_version = final_installed_versions.get(tool, "")
            latest_version = latest_versions.get(tool, "")
            if final_version == latest_version:
                status_map[tool] = "Updated successfully"
            else:
                status_map[tool] = "Update failed or partial"

        print(f"\033[{rows_count}A", end="")
        self._print_tools_table(tools=[tool["name"] for tool in self.script_list], status_map=status_map)
        print()

    def _delete_tools(self, valid_tools: list[str]) -> None:
        """
        Uninstalls specified tools (except protected ones) using pip, updating status accordingly.

        Args:
            valid_tools (list[str]): List of tool names to uninstall.

        Behavior:
            - Filters out protected tools (ptlibs, ptmanager) and tools not installed.
            - Prints initial status showing which tools are removable or protected.
            - Runs pip uninstall -y on filtered tools.
            - Updates the status map with results (success/failure).
            - Refreshes and prints the updated tools status table.
        """
        rows_count = len(self.script_list) + 2
        installed_versions = self._get_installed_versions_map(valid_tools)

        filtered_tools = [
            t for t in valid_tools
            if t not in ("ptlibs", "ptmanager") and t in installed_versions
        ]

        status_map = {}
        for tool in valid_tools:
            if tool in ("ptlibs", "ptmanager"):
                status_map[tool] = "Cannot be deleted from ptmanager"
            elif tool not in installed_versions:
                status_map[tool] = "Already uninstalled"
            elif tool in filtered_tools:
                status_map[tool] = "Removing..."
            else:
                status_map[tool] = "Cannot be deleted or already uninstalled"

        self._print_tools_table(tools=[tool["name"] for tool in self.script_list], status_map=status_map)

        if not filtered_tools:
            return

        pip_args = [sys.executable, "-m", "pip", "uninstall", "-y"] + filtered_tools
        result = subprocess.run(pip_args, capture_output=True, text=True)

        final_installed_versions = self._get_installed_versions_map(valid_tools)

        for tool in valid_tools:
            if tool in ("ptlibs", "ptmanager"):
                status_map[tool] = "Cannot be deleted from ptmanager"
            elif tool in installed_versions and tool not in final_installed_versions:
                status_map[tool] = "Uninstall: OK"
                self.run_hook(tool, "uninstall")
                
            elif tool not in installed_versions:
                status_map[tool] = "Already uninstalled"
            else:
                status_map[tool] = "Uninstall failed"

        print(f"\033[{rows_count}A", end="")
        self._print_tools_table(tools=[tool["name"] for tool in self.script_list], status_map=status_map)
        print()

    def run_hook(self, tool_name: str, action: str):
        """
        action: "install" or "uninstall", "register
        """
        if action == "register":
            if self._is_penterep_venv:
                try:
                    # Register tool launcher
                    subprocess.run(["/usr/local/bin/register-tools", tool_name], check=True)
                except Exception:
                    pass
        else:
            try:
                module = importlib.import_module(f"modules.hooks.{tool_name}")
                getattr(module, action)()
            except Exception:
                sys.stdout.write("\033[?25h")  # Show cursor
                pass

    def is_penterep_venv(self, expected_path: str) -> bool:
        """
        Returns True if the current Python interpreter is running inside the expected (penterep) virtual environment.

        Args:
            expected_path (str): Absolute path to the venv directory to check against.

        Returns:
            bool: True if current venv matches the expected path.
        """
        current_venv = os.path.realpath(sys.prefix)
        expected_venv = os.path.realpath(expected_path)
        return current_venv == expected_venv