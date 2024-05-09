import subprocess
import re
import os
import sys; sys.path.extend([__file__.rsplit("/", 1)[0], os.path.join(__file__.rsplit("/", 1)[0], "modules")])
import requests

from ptlibs import ptjsonlib, ptprinthelper


class ToolsManager:
    def __init__(self, ptjsonlib: ptjsonlib.PtJsonLib, use_json: bool) -> None:
        self.ptjsonlib = ptjsonlib
        self.use_json = use_json

    def print_available_tools(self) -> None:
        self._print_tools_table(self._get_script_list_from_api())

    def _print_tools_table(self, tool_list_from_api, tools2update: list = None, tools2install: list = None, tools2delete: list = None) -> None:
        print(f"{ptprinthelper.get_colored_text('Tool name', 'TITLE')}{' '*9}{ptprinthelper.get_colored_text('Installed', 'TITLE')}{' '*10}{ptprinthelper.get_colored_text('Latest', 'TITLE')}")
        print(f"{'-'*20}{'-'*19}{'-'*19}{'-'*6}")

        for ptscript in tool_list_from_api:
            is_installed, local_version = self.check_if_tool_is_installed(ptscript['name'])
            remote_version = ptscript["version"]

            print(f"{ptscript['name']}{' '*(20-len(ptscript['name']))}{local_version}{' '*(19-len(local_version))}{remote_version}{' '*5}", end="" if tools2update or tools2install or tools2delete else "\n", flush=True)

            if tools2install:
                if ptscript["name"] in tools2install:
                    if not is_installed:
                        print(self._install_update_delete_tools(tool_name=ptscript["name"], do_install=True))
                    else:
                        print("Already installed")
                else:
                    print("")

            if tools2delete:
                if ptscript["name"] in tools2delete:
                    if is_installed:
                        print(self._install_update_delete_tools(tool_name=ptscript["name"], do_delete=True))
                    else:
                        print("Already uninstalled")
                else:
                    print("")

            if tools2update:
                if ptscript["name"] in tools2update:
                    if is_installed:
                        if local_version.replace(".", "") < remote_version.replace(".", ""):
                            print(self._install_update_delete_tools(tool_name=ptscript["name"], local_version=local_version, do_update=True))
                        elif local_version.replace(".", "") == remote_version.replace(".", ""):
                            print("Already latest version")
                        else:
                            print("Current version is > than the available version.")
                    else:
                        print("Install first before updating")
                else:
                    print("")


        #print(f"{'-'*20}{'-'*19}{'-'*19}{'-'*6}")


    def _get_script_list_from_api(self) -> list:
        """Retrieve available tools from API"""
        print("Fetching tools...", end="\r")
        try:
            available_tools = requests.get("https://raw.githubusercontent.com/Penterep/ptmanager/main/ptmanager/available_tools.txt").text.split("\n")
            available_tools = sorted(list(set([tool.strip() for tool in available_tools if tool.strip() and not tool.startswith("#")])))
            script_list = []
            for tool in available_tools:
                response = requests.get(f'https://pypi.python.org/pypi/{tool}/json')
                if response.status_code != 200:
                    continue
                response = response.json()
                script_list.append({"name": tool, "version": list(response['releases'].keys())[-1]})
        except Exception as e:
            self.ptjsonlib.end_error(f"Error retrieving tools from api - {e}", self.use_json)

        return sorted(script_list, key=lambda x: x['name'])

    def check_if_tool_is_installed(self, tool_name) -> tuple[bool, str]:
        try:
            p = subprocess.run([tool_name, "-v"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            local_version = p.stdout.split()[-1] # gets version
            is_installed = True
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
            if tool_name in ["ptlibs"]:
                return "Cannot be deleted from ptmanager"
            process_args = ["pip", "uninstall", tool_name, "-y"]


        process = subprocess.run(process_args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) # install/update/delete
        if do_delete:
            try:
                process = subprocess.run([tool_name, "-v"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) # check new version
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
        tools2prepare = set([tool.lower() for unparsed_tool in tools2prepare for tool in unparsed_tool.split(",") if tool])
        script_list = self._get_script_list_from_api()

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
            print("")
            self.ptjsonlib.end_error(f"Unrecognized Tool(s): [{', '.join(invalid_tool_names)}]", self.use_json)


    def _check_if_tool_exists(self, tool_name: str, script_list) -> bool:
        """Checks if tool_name is present in script_list"""
        if tool_name in [script["name"] for script in script_list]:
            return True