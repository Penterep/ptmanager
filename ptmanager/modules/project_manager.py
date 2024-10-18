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
from urllib.parse import urlparse

from config import Config
from process import Process
from utils import prompt_confirmation


class ProjectManager:
    def __init__(self, ptjsonlib: ptjsonlib.PtJsonLib, use_json: bool, proxies: dict, no_ssl_verify: bool, config: Config, debug: bool) -> None:
        self.ptjsonlib: object   = ptjsonlib
        self.use_json: bool      = use_json
        self.no_ssl_verify: bool = no_ssl_verify
        self.proxies: dict       = {"http": proxies, "https": proxies}
        self.config: object      = config
        self.debug: bool         = debug
        #TODO: Implementovat přepínač pro insecure SSL a upravit všechny requesty, aby s tímto přepínačem spolupracovaly

    def register_project(self, target_url: str, auth_token: str) -> None:
        """Registers new project."""
        if not target_url:
            self.ptjsonlib.end_error("Missing --target parameter", self.use_json)
        if not auth_token:
            self.ptjsonlib.end_error("Missing --auth parameter", self.use_json)
        if not self.config.get_satid():
            self.ptjsonlib.end_error("Please run 'ptmanager --init' first.", self.use_json)
        if not target_url.endswith("/"):
            target_url += "/"
        for project in self.config.get_projects():
            if project.get('auth') == auth_token:
                self.ptjsonlib.end_error("Provided authorization token has already been used.", self.use_json)

        try:
            ptprinthelper.ptprint(f"Registering new project ...", "TITLE", condition=True, colortext=False, clear_to_eol=True)
            try:
                response = requests.post(url=self._get_registration_url(target_url), proxies=self.proxies, allow_redirects=False, verify=self.no_ssl_verify, data=json.dumps({"token": auth_token, "satid": self.config.get_satid()}), headers={"Content-Type": "application/json"})
                if response.status_code != 200:
                    raise Exception(f"Expected status code 200, got {response.status_code}")
            except requests.RequestException:
                raise Exception("Error communicating with server, check your URL")

            response_data = response.json()
            if response_data.get("success"):
                ptprinthelper.ptprint(f"{response_data['message']}\n", "TITLE", condition=True, colortext=False, clear_to_eol=True)
                project_name = self._get_unique_project_name(base_name=response_data['data']['name'])
                self.config.add_project({"project_name": project_name, "target": target_url, "auth": auth_token, "pid": None, "port": None, "AS-ID": ''.join(random.choice(string.ascii_lowercase + string.digits) for _ in range(8))})
                self.list_projects()
            else:
                raise Exception("Invalid response data")
        except Exception as e:
            self.ptjsonlib.end_error(f"Registering new project: {e}.", self.use_json)


    def start_project(self, project_id: int, list_projects: bool = True) -> None:
        project: dict = self.config.get_project(project_id)

        if project.get("pid"):
            if not Process(project["pid"]).is_running():
                self.config.set_project_pid(project, None)
            else:
                self.list_projects()
                print(" ")
                self.ptjsonlib.end_error(f"Project {self.config.get_project(project_id).get('project_name', '')} is already running (PID: {project['pid']})", self.use_json)

        try:
            project_port = 10000 + project_id
            subprocess_args = [sys.executable, os.path.realpath(os.path.join(__file__.rsplit("/", 1)[0], "daemon.py")), "--target", project["target"], "--auth", project["auth"], "--project-id", project["AS-ID"], "--port", str(project_port)]
            if self.proxies.get("http"):
                subprocess_args += ["--proxy", self.proxies.get("http")]
            if not self.no_ssl_verify:
                subprocess_args += ["--no_ssl_verify"]

            # Start daemon.py via subprocess
            if self.debug:
                process = subprocess.Popen(subprocess_args, text=True)
            else:
                process = subprocess.Popen(subprocess_args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


        except Exception as e:
            self.ptjsonlib.end_error(e, self.use_json)

        self.config.set_project_pid(project_id, process.pid)
        self.config.set_project_port(project_id, project_port)
        ptprinthelper.ptprint(f"Started project {self.config.get_project(project_id).get('project_name', '')} (PID: {self.config.get_pid(project_id)})\n", "TITLE", condition=True, colortext=False, clear_to_eol=True)
        if list_projects:
            self.list_projects()

    def end_project(self, project_id: int, list_projects: bool = True) -> None:
        process_pid = self.config.get_pid(project_id)
        if process_pid:
            try:
                os.kill(process_pid, signal.SIGTERM)
                self.config.set_project_pid(project_id, None)
                self.config.set_project_port(project_id, None)
                ptprinthelper.ptprint(f"Killed project {self.config.get_project(project_id).get('project_name', '')} (PID: {process_pid})", "OK", condition=True, colortext=False, clear_to_eol=True)
                if list_projects:
                    print(" ")
                    self.list_projects()

            except ProcessLookupError:
                ptprinthelper.ptprint(f"Project {self.config.get_project(project_id).get('project_name', '')} is not running", "ERROR", condition=True, colortext=False, clear_to_eol=True)
                self.config.set_project_pid(project_id, None)
                self.config.set_project_port(project_id, None)
            except Exception as e:
                self.ptjsonlib.end_error(e, self.use_json)
        else:
            self.list_projects()
            print(" ")
            self.ptjsonlib.end_error(f"Project {self.config.get_project(project_id).get('project_name', '')} is not running", self.use_json)


    def reset_project(self, project_id: int) -> None:
        if self.config.get_pid(project_id):
            self.end_project(project_id, list_projects=False)
            self.start_project(project_id)
        else:
            self.list_projects()
            print(" ")
            self.ptjsonlib.end_error(f"Project {self.config.get_project(project_id).get('project_name')} is not running", self.use_json)

    def delete_project(self, project_id: int) -> None:
        """Removes project locally and attempts to unpair it from AS."""
        if self.config.get_pid(project_id):
            self.ptjsonlib.end_error(f"Project is running, end project first", self.use_json)

        project = self.config.get_project(project_id)
        url = project["target"] + "api/v1/sat/delete"

        try:
            ptprinthelper.ptprint(f"Deleting project {self.config.get_project(project_id).get('project_name')} ...", "TITLE", condition=True, colortext=False, clear_to_eol=True)

            # Send request to delete from AS
            response = requests.post(url=url, proxies=self.proxies, verify=self.no_ssl_verify, data=json.dumps({"satid": self.config.get_satid()}), headers={"Content-Type": "application/json"}, allow_redirects=False)
            self.config.remove_project(project_id)
            ptprinthelper.ptprint(f"Project {project.get('project_name')} deleted succesfully", "TITLE", condition=True, colortext=False, clear_to_eol=True)
        except (requests.RequestException) as e:
            ptprinthelper.ptprint(f"Server is not responding", "ERROR")
            if prompt_confirmation("Cannot delete project from AS. Delete TS from server manualy.\nProject will be deleted locally only. Unpair from AS manually."):
                self.config.remove_project(project_id)
                ptprinthelper.ptprint_(ptprinthelper.out_ifnot(f"local project deleted succesfully", "OK"))
        finally:
            print(" ")
            self.list_projects()


    def list_projects(self) -> None:
        print(f"{ptprinthelper.get_colored_text('ID', 'TITLE')}{' '*4}{ptprinthelper.get_colored_text('Project Name', 'TITLE')}{' '*20}{ptprinthelper.get_colored_text('PID', 'TITLE')}{' '*7}{ptprinthelper.get_colored_text('Status', 'TITLE')}{' '*9}{ptprinthelper.get_colored_text('Port', 'TITLE')}")
        print(f"{'-'*6}{'-'*32}{'-'*10}{'-'*15}{'-'*5}")
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

            port = project.get("port", "-") or "-"
            print(f"{index}{' '*(6-len(str(index)))}", end="")
            print(f"{project['project_name']}{' '*(32-len(project['project_name']))}", end="")
            print(f"{str(pid)}{' '*(10-len(str(pid)))}", end="")
            print(f"{status}{' '*(15-len(status))}", end="")
            print(f"{port}{' '*(15-len(str(port)))}", end="")
            print("")

    def register_uid(self) -> None:
        UID = str(uuid.uuid1())
        if self.config.get_satid():
            if prompt_confirmation(f"This will delete all your existing projects. This action cannot be undone.", bullet_type="TEXT"):
                self.config.delete_projects()
                self.config.delete()
                self.config.make()
                self.config.set_satid(UID)
            else:
                exit()
        else:
            self.config.set_satid(UID)

    def _get_unique_project_name(self, base_name):
        """Returns unique project name if project with <base_name> already exists."""
        project_name = base_name
        counter = 1

        while any(project.get("project_name") == project_name for project in self.config.get_projects()):
            project_name = f"{base_name} ({counter})"
            counter += 1

        return project_name

    def _get_registration_url(self, url: str):
        """Replaces <url> path with /api/v1/sat/register"""
        parsed_url = urlparse(url)
        # Check if the URL is valid
        if all([parsed_url.scheme, parsed_url.netloc]) and parsed_url.scheme in ["http", "https"]:
            # Ensure the path ends with a slash before adding the new path
            if not parsed_url.path.endswith('/'):
                parsed_url = parsed_url._replace(path=parsed_url.path + '/')
            # Replace the path and clear params, query, and fragment
            new_url = parsed_url._replace(path='/api/v1/sat/register', params='', query='', fragment='').geturl()
            return new_url
        else:
            return self.ptjsonlib.end_error("--target is not a valid URL.", self.use_json)
