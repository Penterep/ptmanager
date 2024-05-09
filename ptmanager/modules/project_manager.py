import os
import random
import signal
import string
import subprocess
import sys; sys.path.extend([__file__.rsplit("/", 1)[0], os.path.join(__file__.rsplit("/", 1)[0], "modules")])
import urllib
import uuid
import json

import requests

from ptlibs import ptjsonlib, ptprinthelper

from config import Config
from process import Process


class ProjectManager:
    def __init__(self, ptjsonlib: ptjsonlib.PtJsonLib, use_json: bool, proxies: dict, no_ssl_verify: bool, config: Config) -> None:
        self.ptjsonlib     = ptjsonlib
        self.use_json      = use_json
        self.no_ssl_verify = no_ssl_verify
        self.proxies       = {"http": proxies, "https": proxies}
        self.config        = config

    def register_project(self, target: str, auth_token: str) -> None:
        """Registers new project"""
        if not target:
            self.ptjsonlib.end_error("Missing --target parameter", self.use_json)
        if not auth_token:
            self.ptjsonlib.end_error("Missing --auth parameter", self.use_json)

        target = self.is_url(target)
        if not target:
            self.ptjsonlib.end_error("Target is not a valid URL", self.use_json)

        registration_url = target + "api/v1/sat/register"
        try:
            response = requests.post(registration_url, proxies=self.proxies, verify=self.no_ssl_verify, data={"token": auth_token, "satid": self.config.get_satid()})
        except requests.RequestException as e:
            self.ptjsonlib.end_error("Server is not responding", self.use_json)

        if response.status_code == 200:
            try:
                response_json = response.json()
            except json.JSONDecodeError:
                self.ptjsonlib.end_error(f"Could not parse target response as json - {response.text}", self.use_json)

            if response_json.get("success"):
                print(response_json["data"]['name'])
                print(response_json['message'])
                project_name = response_json['data']['name']
            else:
                self.ptjsonlib.end_error(response_json, self.use_json)
        else:
            self.ptjsonlib.end_error(f"[{response.status_code}] {response.text}", self.use_json)

        AS_ID = ''.join(random.choice(string.ascii_lowercase) for _ in range(8))
        self.config.add_project({"project_name": project_name, "target": target, "auth": auth_token, "pid": None, "AS-ID": AS_ID})

    def is_url(self, url: int):
        try:
            result = urllib.parse.urlparse(url)
            if result.path:
                while result.path.endswith("/"):
                    result = result._replace(path=result.path[:-1])
            result = result._replace(path=result.path + "/")
            return result.geturl()
        except ValueError:
            return False

    def start_project(self, project_id: int) -> None:
        """Starts specified project."""
        print("Starting ....")
        project = self.config.get_project(project_id)
        if project["pid"]:
            if not Process(project["pid"]).is_running():
                self.config.set_project_pid(project_id, None)
            else:
                self.ptjsonlib.end_error(f"Project is already running with PID {project['pid']}", self.use_json)

        response = {"sessionid": "sessionid"}
        try:
            subprocess_args = [sys.executable, os.path.realpath(os.path.join(__file__.rsplit("/", 1)[0], "process_manager.py")), "--target", project["target"], "--auth", project["auth"], "--sid", response["sessionid"], "--project_id", project["AS-ID"]]

            if self.proxies.get("http"):
                subprocess_args += ["--proxy", self.proxies.get("http")]
            if not self.no_ssl_verify:
                subprocess_args += ["--no_ssl_verify"]

            process = subprocess.Popen(subprocess_args)

        except Exception as e:
            self.ptjsonlib.end_error(e, self.use_json)
        self.config.set_project_pid(project_id, process.pid)
        ptprinthelper.ptprint_(ptprinthelper.out_ifnot(f"Started Project {project_id+1} with PID {process.pid}", "INFO"))


    def end_project(self, project_id: int) -> None:
        process_pid = self.config.get_pid(project_id)
        if process_pid:
            try:
                os.kill(process_pid, signal.SIGTERM)
                self.config.set_project_pid(project_id, None)
                ptprinthelper.ptprint_(ptprinthelper.out_ifnot(f"Killed process with PID {process_pid}", "OK"))
            except ProcessLookupError:
                ptprinthelper.ptprint_(ptprinthelper.out_ifnot(f"Proccess [{process_pid}] is not running ", "ERROR"))
                self.config.set_project_pid(project_id, None)
            except Exception as e:
                self.ptjsonlib.end_error(e, self.use_json)
        else:
            self.ptjsonlib.end_error(f"Project is not running", self.use_json)

    def reset_project(self, project_id: int) -> None:
        if self.config.get_pid(project_id):
            self.end_project(project_id)
            self.start_project(project_id)
        else:
            self.start_project(project_id)

        ptprinthelper.ptprint_(ptprinthelper.out_ifnot(f"Succesfully registered project", "OK"))


    def delete_project(self, project_id: int) -> None:
        # TODO: Send request to delete project from AS
        if self.config.get_pid(project_id):
            self.ptjsonlib.end_error(f"Project is running, end project first", self.use_json)

        project = self.config.get_project(project_id)
        request_path = project["target"] + "api/v1/sat/delete"

        try:
            response = requests.post(request_path, proxies=self.proxies, verify=self.no_ssl_verify, data={"satid": self.config.get_satid()}) #project["auth"]
            self.config.remove_project(project_id)
            ptprinthelper.ptprint_(ptprinthelper.out_ifnot(f"Project deleted succesfully", "OK"))
        except requests.RequestException as e:
            ptprinthelper.ptprint(f"Server is not responding", "ERROR")
            if self._yes_no_prompt("Cannot delete project from AS. Delete TS from server manualy.\nProject will be deleted locally only. Are you sure?", bullet_type=None):
                self.config.remove_project(project_id)
                ptprinthelper.ptprint_(ptprinthelper.out_ifnot(f"Local project deleted succesfully", "OK"))


    def list_projects(self) -> None:
        print(f"{ptprinthelper.get_colored_text('ID', 'TITLE')}{' '*4}{ptprinthelper.get_colored_text('Project Name', 'TITLE')}{' '*20}{ptprinthelper.get_colored_text('PID', 'TITLE')}{' '*7}{ptprinthelper.get_colored_text('Status', 'TITLE')}{' '*9}")
        print(f"{'-'*6}{'-'*32}{'-'*10}{'-'*15}")
        if not self.config.get_projects():
            print(" ")
            self.ptjsonlib.end_error("No projects found, register a project first", self.use_json)

        for index, project in enumerate(self.config.get_projects(), 1):
            if project["pid"]:
                if not Process(project["pid"]).is_running():
                    self.config.set_project_pid(index - 1, None)
                    project["pid"] = None
            pid = project["pid"]
            if pid:
                status = "running"
            if not pid:
                status = "-"
                pid = "-"

            print(f"{index}{' '*(6-len(str(index)))}", end="")
            print(f"{project['project_name']}{' '*(32-len(project['project_name']))}", end="")
            print(f"{str(pid)}{' '*(10-len(str(pid)))}", end="")
            print(f"{status}{' '*(15-len(status))}", end="")
            print("")

    def register_uid(self) -> None:
        UID = str(uuid.uuid1())
        if self.config.get_satid():
            if self._yes_no_prompt("UID already exists, are you sure you want to create new? All your projects will be deleted!"):
                self.config.delete_projects()
                self.config.delete()
                self.config.make()
                self.config.set_satid(UID)
            else:
                exit()
        else:
            self.config.set_satid(UID)
            print("[*] New UID generated")
            self.config.print()


    def _yes_no_prompt(self, msg, bullet_type="OK") -> bool:
        ptprinthelper.ptprint_(ptprinthelper.out_ifnot(f"{msg}", bullet_type), end=" ")
        reply = input(f"y/N: ").upper().strip()
        if reply == "Y":
            return True
        elif reply == "N" or reply == "":
            return False
        else:
            return self._yes_no_prompt(msg)

#TODO: Implementovat přepínač pro insecure SSL a upravit všechny requesty, aby s tímto přepínačem spolupracovaly