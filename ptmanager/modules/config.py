from ptlibs import ptprinthelper, ptjsonlib, app_dirs
import json
import os
import shutil
import sys

from utils import prompt_confirmation

class Config:
    NAME = "config.json"
    PROJECTS_KEY = "projects"
    SATID_KEY = "satid"
    TEMP = "temp"
    PID_KEY = "pid"
    PORT_KEY = "port"

    def __init__(self, config_path: str = os.path.join(os.path.expanduser("~"), ".penterep", "ptmanager/")) -> None:
        self._config: dict[list] = None
        self._config_path = config_path

        self._migrate_old_config_if_needed() # TODO: Temporary function to migrate old path...

        try:
            self.load()
        except FileNotFoundError:
            self.make()
        except json.JSONDecodeError:
            if prompt_confirmation(f"Error parsing {self.NAME}. Fix it manually or create a new one.", "Create new one?", bullet_type="ERROR"):
                self.make()
            else:
                sys.exit(1)

    def _migrate_old_config_if_needed(self) -> None:
        OLD_PATH = os.path.expanduser("~/.ptmanager/")
        NEW_PATH = os.path.expanduser("~/.penterep/ptmanager/")

        old_file = os.path.join(OLD_PATH, self.NAME)
        new_file = os.path.join(self._config_path, self.NAME)

        if os.path.exists(old_file) and not os.path.exists(new_file):
            os.makedirs(self._config_path, exist_ok=True)
            shutil.move(old_file, new_file)
            print(f"Migrated old config from {old_file} to {new_file}")

            # Optional: remove old directory if empty
            try:
                os.rmdir(OLD_PATH)
            except OSError:
                pass  # Directory not empty, leave it

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
        #return app_dirs.AppDirs("ptmanager").get_data_dir()
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
    
    def get_project(self, project_id: int):
        try:
            return self._config[self.PROJECTS_KEY][project_id]
        except Exception as e:
            print(f"Error retrieving project - {e}")

    def get_satid(self, project_id: int) -> str:
        try:
            self._config[self.PROJECTS_KEY][project_id].get("satid")
        except Exception as e:
            print(f"Error retrieving satid - {e}")


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