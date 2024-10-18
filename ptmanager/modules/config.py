from ptlibs import ptprinthelper, ptjsonlib
import json
import os
import shutil
import sys

from utils import prompt_confirmation

class Config:
    NAME = "config.json"
    PROJECTS_KEY = "projects"
    TEMP = "temp"
    SATID_KEY = "satid"
    PID_KEY = "pid"
    PORT_KEY = "port"


    def __init__(self, config_path: str) -> None:
        self._config_path = config_path
        self._config: dict[list] = None
        try:
            self.load()
        except FileNotFoundError:
            self.make()
        except json.JSONDecodeError:
            if prompt_confirmation(f"Error parsing {self.NAME}. Fix it manually or create a new one.", "Create new one?", bullet_type="ERROR"):
                self.make()
            else:
                sys.exit(1)

    def __repr__(self) -> None:
        print(self._config)

    def load(self) -> dict[list]:
        with open(self._config_path + self.NAME) as f:
            self._config = json.load(f)

    def make(self) -> dict[list]:
        self.assure_config_path()
        with open(self._config_path + self.NAME, "w+") as f:
            data = {self.SATID_KEY: None, self.PROJECTS_KEY: []}
            f.write(json.dumps(data, indent=4, sort_keys=True))
        self._config = json.loads(json.dumps(data))

    def assure_config_path(self) -> None:
        os.makedirs(self._config_path, exist_ok=True)

    def delete(self) -> None:
        os.remove(self._config_path + self.NAME)

    def delete_projects(self) -> None:
        try:
            shutil.rmtree(os.path.join(self._config_path, self.PROJECTS_KEY))
        except FileNotFoundError as e:
            pass
        except Exception as e:
            print(e)

    def save(self) -> None:
        with open(self._config_path + self.NAME, "w") as f:
            json.dump(self._config, f, indent=4)


    def get_path(self) -> str:
        return self._config_path

    def get_temp_path(self) -> str:
        temp_path = self._config_path + self.TEMP + "/"
        os.makedirs(temp_path, exist_ok=True)
        return temp_path

    def get_projects(self) -> list:
        try:
            return self._config[self.PROJECTS_KEY]
        except KeyError:
            self._config[self.PROJECTS_KEY] = []
            self.save()
            return self.get_projects()


    def get_satid(self) -> str:
        return self._config[self.SATID_KEY]


    def set_satid(self, UID) -> None:
        self._config[self.SATID_KEY] = UID


    def add_project(self, project: dict[str]) -> None:
        self._config[self.PROJECTS_KEY].append(project)


    def get_pid(self, project_id):
        return self._config[self.PROJECTS_KEY][project_id][self.PID_KEY]


    def set_project_pid(self, project_id: int, pid: int) -> None:
        """Sets <pid> for <project_id>"""
        self._config[self.PROJECTS_KEY][project_id][self.PID_KEY] = pid


    def set_project_port(self, project_id: int, port: int) -> None:
        """Sets <port> for <project_id>"""
        self._config[self.PROJECTS_KEY][project_id][self.PORT_KEY] = port


    def remove_project(self, project_id: int) -> None:
        try:
            shutil.rmtree(os.path.join(self._config_path, self.PROJECTS_KEY, self.get_project(project_id).get("AS-ID")))
        except FileNotFoundError:
            pass
        self._config[self.PROJECTS_KEY].pop(project_id)
        self.save()


    def get_project(self, project_id: int):
        try:
            return self._config[self.PROJECTS_KEY][project_id]
        except Exception as e:
            print(f"Error retrieving project - {e}")
            sys.exit(1)
