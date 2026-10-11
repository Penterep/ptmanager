from ptlibs import ptprinthelper, ptjsonlib, app_dirs
import json
import os
import shutil
import sys
import tempfile

import uuid

from utils import prompt_confirmation
from placeholders import PlaceholderError, placeholder_arguments

class Config:
    NAME = "config.json"
    PROJECTS_KEY = "projects"
    SATID_KEY = "satid"
    PLACEHOLDERS_KEY = "placeholders"
    TEMP = "temp"
    PID_KEY = "pid"
    PORT_KEY = "port"

    def __init__(self, config_path: str) -> None:
        self._config: dict[list] = None
        self.config_path: str = os.path.join(config_path, "")

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

        if os.path.realpath(self.config_path) != os.path.realpath(NEW_PATH):
            return

        old_file = os.path.join(OLD_PATH, self.NAME)
        new_file = os.path.join(self.config_path, self.NAME)

        if os.path.exists(old_file) and not os.path.exists(new_file):
            os.makedirs(self.config_path, exist_ok=True)
            shutil.move(old_file, new_file)
            print(f"Migrated old config from {old_file} to {new_file}")

            # Optional: remove old directory if empty
            try:
                os.rmdir(OLD_PATH)
            except OSError:
                pass  # Directory not empty, leave it

    def __repr__(self) -> None:
        return str(self.load())

    def load(self) -> dict[list]:
        with open(self.config_path + self.NAME) as f:
            self._config = json.load(f)


    def make(self) -> dict[list]:
        self._config = {self.SATID_KEY: None, self.PROJECTS_KEY: []}
        self.save(update_placeholders=True)

    def assure_config_path(self) -> None:
        os.makedirs(self.config_path, exist_ok=True)

    def delete(self) -> None:
        os.remove(self.config_path + self.NAME)

    def delete_projects(self) -> None:
        try:
            shutil.rmtree(os.path.join(self.config_path, self.PROJECTS_KEY))
        except FileNotFoundError as e:
            pass
        except Exception as e:
            print(e)

    def save(self, update_placeholders: bool = False) -> None:
        """Preserve current settings and atomically save an owner-only config."""
        self.assure_config_path()
        if not update_placeholders and os.path.exists(self.config_path + self.NAME):
            with open(self.config_path + self.NAME) as f:
                current = json.load(f)
            if self.PLACEHOLDERS_KEY in current:
                self._config[self.PLACEHOLDERS_KEY] = current[self.PLACEHOLDERS_KEY]
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", dir=self.config_path, delete=False) as f:
                temp_path = f.name
                json.dump(self._config, f, indent=4)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_path, self.config_path + self.NAME)
        finally:
            if temp_path and os.path.exists(temp_path):
                os.remove(temp_path)

    def get_placeholders(self) -> dict:
        """Read current settings without changing the daemon's cached project state."""
        with open(self.config_path + self.NAME) as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise PlaceholderError("Configuration must be an object.")
        return data.get(self.PLACEHOLDERS_KEY, {})

    def set_placeholders(self, values: dict) -> None:
        """Overwrite specified groups and preserve other settings and projects."""
        for name, value in values.items():
            placeholder_arguments(name, value)
        self.load()
        placeholders = self._config.setdefault(self.PLACEHOLDERS_KEY, {})
        if not isinstance(placeholders, dict):
            raise PlaceholderError("Placeholder configuration must be an object.")
        placeholders.update(values)
        self.save(update_placeholders=True)

    def get_path(self) -> str:
        return self.config_path

    def get_temp_path(self) -> str:
        #return app_dirs.AppDirs("ptmanager").get_data_dir()
        temp_path = self.config_path + self.TEMP + "/"
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

    def get_project_by_asid(self, asid: str):
        try:
            for project in self._config[self.PROJECTS_KEY]:
                if project.get("AS-ID") == asid:
                    return project
            return None
        except Exception as e:
            print(f"Error retrieving project by AS-ID - {e}")

    def get_satid(self) -> str:
        try:
            return self._config[self.SATID_KEY]
        except Exception as e:
            print(f"Error retrieving satid - {e}")

    def get_pid(self, project_id):
        return self._config[self.PROJECTS_KEY][project_id][self.PID_KEY]

    def set_satid(self, satid: str) -> None:
        self._config[self.SATID_KEY] = satid
        self.save()


    def add_project(self, project: dict[str]) -> None:
        self._config[self.PROJECTS_KEY].append(project)
        self.save()



    def set_project_pid(self, project_id: int, pid: int) -> None:
        """Sets <pid> for <project_id>"""
        self._config[self.PROJECTS_KEY][project_id][self.PID_KEY] = pid
        self.save()


    def set_project_port(self, project_id: int, port: int) -> None:
        """Sets <port> for <project_id>"""
        self._config[self.PROJECTS_KEY][project_id][self.PORT_KEY] = port
        self.save()


    def remove_project(self, project_id: int) -> None:
        try:
            shutil.rmtree(os.path.join(self.config_path, self.PROJECTS_KEY, self.get_project(project_id).get("AS-ID")))
        except FileNotFoundError:
            pass
        self._config[self.PROJECTS_KEY].pop(project_id)
        self.save()


    def register_uid(self) -> None:
        """Initialize a new SATID and remove projects, preserving user settings."""
        if self.get_satid():
            if prompt_confirmation(f"This will delete all your existing projects. This action cannot be undone.", bullet_type="TEXT"):
                self.delete_projects()
                self._config[self.PROJECTS_KEY] = []
                self.set_satid(satid=str(uuid.uuid1()))
        else:
            self.set_satid(satid=str(uuid.uuid1()))

        #print("Initialization complete. Your SATID is:", self.get_satid())
