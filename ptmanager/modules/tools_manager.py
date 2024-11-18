import subprocess
import re
import os
import sys; sys.path.extend([__file__.rsplit("/", 1)[0], os.path.join(__file__.rsplit("/", 1)[0], "modules")])
import requests
import time
import threading
import json

from ptlibs import ptjsonlib, ptprinthelper

class ToolsManager:
    def __init__(self, ptjsonlib: ptjsonlib.PtJsonLib, use_json: bool) -> None:
        self.ptjsonlib = ptjsonlib
        self.use_json = use_json
        self._stop_spinner = False
        self._is_sudo = os.geteuid() == 0
        self._is_venv = True if hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix else False

    def _print_tools_table(self, tool_list_from_api, tools2update: list = None, tools2install: list = None, tools2delete: list = None) -> None:
        print(f"{ptprinthelper.get_colored_text('Tool name', 'TITLE')}{' '*9}{ptprinthelper.get_colored_text('Installed', 'TITLE')}{' '*10}{ptprinthelper.get_colored_text('Latest', 'TITLE')}")
        print(f"{'-'*20}{'-'*19}{'-'*19}{'-'*6}{'-'*7}")

        for ptscript in tool_list_from_api:
            is_installed, local_version = self.check_if_tool_is_installed(ptscript['name'])
            remote_version = ptscript["version"]
            print(f"{ptscript['name']}{' '*(20-len(ptscript['name']))}{local_version}{' '*(19-len(local_version))}{remote_version}{' '*5}", end="" if tools2update or tools2install or tools2delete else "\n", flush=True)

            if tools2install:
                if ptscript["name"] in tools2install:
                    if not is_installed:
                        print(self._install_update_delete_tools(tool_name=ptscript["name"], do_install=True))
                        if self._is_venv:
                            try:
                                subprocess.run(["/usr/local/bin/register-tools", ptscript["name"]], check=True)
                            except:
                                pass
                    else:
                        print(" ")
                else:
                    # Uninstalled / Not installed
                    print("")

            if tools2delete:
                if ptscript["name"] in tools2delete:
                    if is_installed:
                        print(self._install_update_delete_tools(tool_name=ptscript["name"], do_delete=True))
                    else:
                        print("")
                else:
                    print("")

            if tools2update:
                if ptscript["name"] in tools2update:
                    if is_installed:
                        if local_version.replace(".", "") < remote_version.replace(".", ""):
                            print(self._install_update_delete_tools(tool_name=ptscript["name"], local_version=local_version, do_update=True))
                        elif local_version.replace(".", "") == remote_version.replace(".", ""):
                            print(" ")
                            # print("Already latest version")
                        else:
                            print("Current version is > than the available version.")
                    else:
                        # print("Install first before updating")
                        print(" ")
                else:
                    print(" ")

    def print_available_tools(self) -> None:
        try:
            self._print_tools_table(self._get_script_list_from_api())
        except KeyboardInterrupt:
            self._stop_spinner = True
            sys.stdout.write("\033[?25h")  # Ensure cursor is shown
            sys.stdout.flush()
            print("\nProcess interrupted by user.")
            sys.exit(1)

    def _get_script_list_from_api(self) -> list:
        """Retrieve available tools from API"""
        spinner_thread = threading.Thread(target=self._spinner, daemon=True)
        spinner_thread.start()  # Retrieving tools spinner...

        try:
            available_tools = requests.get("https://raw.githubusercontent.com/Penterep/ptmanager/main/ptmanager/available_tools.txt").text.split("\n")
            available_tools = sorted(list(set([tool.strip() for tool in available_tools if tool.strip() and not tool.startswith("#")])))
            script_list = []
            for tool in available_tools:
                response = requests.get(f'https://pypi.python.org/pypi/{tool}/json')
                if response.status_code != 200:
                    continue
                response = response.json()
                #script_list.append({"name": tool, "version": list(response['releases'].keys())[-1]})
                script_list.append({"name": tool, "version": response["info"]["version"]})

        except Exception as e:
            self._stop_spinner = True
            spinner_thread.join()
            sys.stdout.write("\r" + " " * 40 + "\r")  # Clear the line in case of error
            sys.stdout.flush()
            self.ptjsonlib.end_error(f"Error retrieving tools from API ({e})", self.use_json)

        finally:
            # Ensure cursor is shown even if an error occurs or if interrupted
            sys.stdout.write("\033[?25h")  # Show cursor
            sys.stdout.flush()

        self._stop_spinner = True
        spinner_thread.join()
        sys.stdout.write("\r" + " " * 40 + "\r")  # Clear line using spaces and carriage return
        return sorted(script_list, key=lambda x: x['name'])


    def check_if_tool_is_installed(self, tool_name) -> tuple[bool, str]:
        try:
            p = subprocess.run([tool_name, "-v"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

            if re.compile(r'^\w*\s\d{1,3}\.\d{1,3}\.\d{1,3}$').match(p.stdout.strip()):
                script_name, version = p.stdout.strip().split()
                is_installed = True
                local_version = version
            else:
                is_installed = False
                local_version = "-"
        except FileNotFoundError:
            local_version = "-"
            is_installed = False
        except IndexError:
            local_version = "-"
            is_installed = False
        return is_installed, local_version


    def _install_update_delete_tools(self, tool_name:str, do_install=False, do_update=False, do_delete=False, local_version=None) -> str:
        assert do_update or do_install or do_delete

        if do_install:
            process_args = ["pip", "install", tool_name]

        if do_update:
            process_args = ["pip", "install", tool_name, "--upgrade"]

        if do_delete:
            if tool_name in ["ptlibs", "ptmanager"]:
                return "Cannot be deleted from ptmanager"
            process_args = ["pip", "uninstall", tool_name, "-y"]

        try:
            process = subprocess.run(process_args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True) # install/update/delete
        except Exception as e:
            return f"error: {e}"

        if do_delete:
            try:
                process = subprocess.run([tool_name, "-v"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) # check new version
                if "not installed" in process.stdout.lower():
                    return "Uninstall: OK"
            except FileNotFoundError as e:
                return f"Uninstall: OK"
            except:
                return f"Uninstall: {e}"
        else:
            try:
                process = subprocess.run([tool_name, "-v"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) # check new version
                new_version = process.stdout.split()[1]
            except Exception as e:
                return f"- -> Updated: Error - {e}"
            if do_update:
                return f"{local_version} -> {new_version} Updated: OK"
            else:
                return f"Installed: OK"


    def prepare_install_update_delete_tools(self, tools2prepare: list, do_update: bool=None, do_install: bool=None, do_delete: bool = None) -> None:
        """Prepare provided tools for installation or update or deletion"""

        if self._is_venv and not self._is_sudo:
            ptprinthelper.ptprint(f"Please run script as sudo for those operations.", )
            sys.exit(1)


        tools2prepare = set([tool.lower() for unparsed_tool in tools2prepare for tool in unparsed_tool.split(",") if tool])

        try:
            #self._print_tools_table(self._get_script_list_from_api())
            script_list = self._get_script_list_from_api()
        except KeyboardInterrupt:
            self._stop_spinner = True
            sys.stdout.write("\033[?25h")
            sys.stdout.flush()
            print("\nProcess interrupted by user.")
            sys.exit(1)

        if "all" in tools2prepare:
            tools2prepare = [tool["name"] for tool in script_list]

        valid_tool_names = [tool for tool in tools2prepare if self._check_if_tool_exists(tool, script_list)]
        invalid_tool_names = [tool for tool in tools2prepare if not self._check_if_tool_exists(tool, script_list)] if len(valid_tool_names) < len(tools2prepare) else []

        if valid_tool_names:
            if do_install:
                self._print_tools_table(script_list, tools2install=valid_tool_names)
            if do_update:
                self._print_tools_table(script_list, tools2update=valid_tool_names)
            if do_delete:
                self._print_tools_table(script_list, tools2delete=valid_tool_names)

        if invalid_tool_names:
            if not valid_tool_names:
                self._print_tools_table(script_list)
            print(" ")
            self.ptjsonlib.end_error(f"Unrecognized Tool(s): [{', '.join(invalid_tool_names)}]", self.use_json)


    def _check_if_tool_exists(self, tool_name: str, script_list) -> bool:
        """Checks if tool_name is present in script_list"""
        if tool_name in [script["name"] for script in script_list]:
            return True


    def _spinner(self):
        sys.stdout.write("\033[?25l")  # Hide cursor
        sys.stdout.flush()
        while not self._stop_spinner:
            for symbol in '|/-\\':
                sys.stdout.write(f'\r[{ptprinthelper.get_colored_text(string=symbol, color="TITLE")}] Retrieving tools ...')  # \r přepíše řádek
                sys.stdout.flush()
                time.sleep(0.1)
        # Show cursor again when spinner stops
        sys.stdout.write("\033[?25h")
        sys.stdout.flush()
