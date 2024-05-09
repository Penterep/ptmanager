import argparse
import json; from json.decoder import JSONDecodeError
import os
import subprocess
import sys; sys.path.extend([__file__.rsplit("/", 1)[0], os.path.join(__file__.rsplit("/", 1)[0], "modules")])
import threading
import time
import pathlib

import requests

from process import Process
from config import Config

class ProcessManager:

    def __init__(self, args):
        self.config: Config          = Config(f"{str(pathlib.Path.home())}/.ptmanager/")
        self.satid: str              = self.config.get_satid()
        self.target: str             = args.target
        self.API_PATH: str           = "api/v1/sat/"

        self.AS_ID: str              = args.project_id
        self.project_dir: str        = os.path.join(self.config.get_path(), "projects", self.AS_ID)
        self.project_tasks_file: str = os.path.join(self.project_dir, "tasks.json")

        self.no_ssl_verify           = args.no_ssl_verify
        self.proxies: dict           = {"http": args.proxy, "https": args.proxy}
        self.free_threads            = [i for i in range(args.threads)]
        self.threads_list            = ["" for _ in range(args.threads)]
        self.lock                    = threading.Lock()

        if not args.target or not args.auth or not args.sid:
            self.ptjsonlib.end_error(f"Target, auth and sid are required", self.use_json)

        if not os.path.isdir(self.project_dir):
            os.makedirs(self.project_dir)


    def run(self, args):
        self.process_front(args.target, args.auth)


    def process_front(self, target, auth) -> None:
        while True:
            while not self.free_threads:
                time.sleep(8)

            self.send_results_to_server(target)

            task = self.get_task_from_as(target, auth)
            if not task:
                time.sleep(10)
                continue

            elif task["action"] == "new_task":
                thread_no = self.free_threads.pop()
                self.threads_list[thread_no] = threading.Thread(target=self.process_newtask, name=task["guid"], args=(task, thread_no), daemon=False)
                self.threads_list[thread_no].start()
            elif task["action"] == "status":
                self.status_task(task)
            elif task["action"] == "status-all":
                self.status_all_tasks()
            elif task["action"] == "kill-task":
                self.kill_task(task)
            elif task["action"] == "kill-all":
                self.kill_all_tasks()
            elif task["action"] == "null":
                pass


    def send_results_to_server(self, target) -> None:
        self.lock.acquire()
        with self.touchopen(self.project_tasks_file, "r+") as tasks_file:
            try:
                tasks_list: list = json.load(tasks_file)
            except JSONDecodeError:
                tasks_list = []


        for task_idx, task in enumerate(tasks_list):
            if task["status"] == "running":
                continue
            task_result_file = os.path.join(self.project_dir, task["guid"])
            if os.path.isfile(task_result_file):
                try:
                    with open(task_result_file, "r") as file:
                        task_result = json.load(file)
                except (JSONDecodeError, Exception) as e:
                        #TODO pokud existuje odkaz na task v tasks.json, ale neexistuje soubor GUID s taskem, nebo je tento soubor vadný, pak se tento záznam nikdy neodstraní z tasks.json
                        print("Chyba pri nacitani vysledku automatu ze souboru -", e)
                        task_result = {}
                        self.lock.release()
                        return
            else:
                task_result = None

            if task_result:
                task_result["guid"] = task["guid"]
                task_result["satid"] = self.satid
                task_result["results"] = json.dumps(task_result["results"])
                response = self.send_to_api(end_point="result", data=(task_result))
                if response.status_code == 200:
                    # Remove automat result as it's already been posted to AS.
                    try:
                        os.remove(task_result_file)
                    except OSError as e:
                        pass

                    # TODO: Popnuto z tasks_listu, ted je potreba upraveny (popnuty) tasks_list zaktualizovat v souboru
                    # TODO: Tak, že otevřu znovu <project_tasks_file> a nahradím jeho obsah popnutym tasks_listem.
                    tasks_list.pop(task_idx)

                    # Otevře soubor pro zápis - nahradí seznam aktualizovaným tasks_listem.
                    with self.touchopen(self.project_tasks_file, "w") as tasks_file:
                        json.dumps(tasks_list, indent=4)

        self.lock.release()


    def send_to_api(self, end_point, data) -> requests.Response:
        target = self.target + self.API_PATH + end_point
        response = requests.post(target, data=json.dumps(data), proxies=self.proxies, verify=self.no_ssl_verify, headers={"Content-Type": "application/json"})
        #if response.status_code != 200:
                #print(f"Response status code is not 200, but {response.status_code}")
        return response


    def status_task(self, task) -> None:
        """Retrieve status of <task>, repairs tasks.json if task is not running"""
        self.lock.acquire()
        with self.touchopen(self.project_tasks_file, "r+") as tasks_list_file:
            tasks_list = json.loads(tasks_list_file.read())
            for index, dictionary in enumerate(tasks_list):
                if dictionary["guid"] == task["guid"]:
                    if not Process(tasks_list[index]["pid"]).is_running():
                        tasks_list[index]["status"] = "error"
                        tasks_list[index]["pid"] = None
            tasks_list_file.seek(0)
            tasks_list_file.truncate(0)
            tasks_list_file.write(json.dumps(tasks_list, indent=4))
        self.lock.release()


    def status_all_tasks(self) -> None:
        """Repairs all tasks."""
        self.lock.acquire()
        with self.touchopen(self.project_tasks_file, "r+") as tasks_list_file:
            try:
                tasks_list = json.loads(tasks_list_file.read())
                for task in tasks_list:
                    if not Process(task["pid"]).is_running():
                        task["status"] = "error"
                        task["pid"] = None
                tasks_list_file.seek(0)
                tasks_list_file.truncate(0)
                tasks_list_file.write(json.dumps(tasks_list, indent=4))
            except JSONDecodeError:
                pass
            finally:
                self.lock.release()


    def kill_all_tasks(self) -> None:
        """Kills all tasks."""

        for t in self.threads_list:
            if isinstance(t, threading.Thread):
                t.join()

        for file in os.listdir(self.project_dir):
            if file != "tasks.json":
                os.remove(os.path.join(self.project_dir, file))

        # TODO - KillAllThreads - Pockat nez se thready dokonci, nebo chladnokrevne zavrazdit vsechno co je thread?
        self.lock.acquire()
        with self.touchopen(self.project_tasks_file, "r+") as tasks_list_file:
            try:
                tasks_list = json.loads(tasks_list_file.read())
                for task in tasks_list:
                    if task["pid"]:
                        Process(task["pid"]).kill()
                        task["status"] = "killed"
                        task["pid"] = None
                tasks_list_file.seek(0)
                tasks_list_file.truncate(0)
                tasks_list_file.write(json.dumps(tasks_list, indent=4))
            except JSONDecodeError:
                pass
            finally:
                self.lock.release()


    def kill_task(self, task) -> None:
        """Kills task with supplied guid."""
        for t in self.threads_list:
            if isinstance(t, threading.Thread) and t.name == task["guid"]:
                t.join()
        try:
            os.remove(os.path.join(self.project_dir, task["guid"]))
        except OSError:
            # File Not Found
            pass

        self.lock.acquire()
        with self.touchopen(self.project_tasks_file, "r+") as tasks_list_file:
            try:
                tasks_list = json.loads(tasks_list_file.read())
                for task_in_list in tasks_list:
                    if task_in_list["guid"] == task["guid"]:
                        if task_in_list["pid"]:
                            Process(task_in_list["pid"]).kill()
                            task_in_list["status"] = "killed"
                            task_in_list["pid"] = None
                tasks_list_file.seek(0)
                tasks_list_file.truncate(0)
                tasks_list_file.write(json.dumps(tasks_list, indent=4))
            except JSONDecodeError:
                pass
            finally:
                self.lock.release()


    def touchopen(self, filename, mode):
        open(filename, "a").close() # "touch" file
        return open(filename, mode)

    def process_newtask(self, task, thread_no) -> None:
        """Process newtask with available thread"""
        result_filename = self.config.get_temp_path() + task["guid"]
        with open(result_filename, "w+") as result_file:
            result_file.truncate(0) # Delete file content, if it exist
            tool_subprocess = subprocess.Popen(task["task"].split(), stdout=result_file, text=True)
            thread_variable = {"guid": task["guid"], "pid": tool_subprocess.pid, "timeStamp": time.time(), "status": "running"}

        self.lock.acquire()
        # Read tasks_list_file
        with self.touchopen(self.project_tasks_file, "r") as tasks_list_file:
            try:
                tasks_list = json.load(tasks_list_file)
            except JSONDecodeError:
                tasks_list = []

        # Update tasks_list in memory
        tasks_list.append(thread_variable)

        # Replace content with updated one
        with self.touchopen(self.project_tasks_file, "w") as tasks_list_file:
            tasks_list_file.write(json.dumps(tasks_list, indent=4))

        self.lock.release()

        tool_subprocess.wait()

        thread_variable.update({"status": "finished", "pid": None})
        
        with open(result_filename, "r") as result_file:
            tool_result = result_file.read()

        os.remove(result_filename)



        self.lock.acquire()
        # Read tasks_list_file
        with self.touchopen(self.project_tasks_file, "r") as tasks_list_file:
            tasks_list = json.load(tasks_list_file)
        self.lock.release()

        for task_idx, task_dict in enumerate(tasks_list):
            if task_dict["guid"] == thread_variable["guid"]:
                tasks_list[task_idx] = thread_variable

        self.lock.acquire()
        # Replace content with updated one
        with self.touchopen(self.project_tasks_file, "w") as tasks_list_file:
            tasks_list_file.write(json.dumps(tasks_list, indent=4))
        self.lock.release()


        self.lock.acquire()
        with open(os.path.join(self.project_dir, task["guid"]), "w") as task_result_file:
            task_result_file.write(tool_result)

        self.lock.release()
        self.free_threads.append(thread_no)


    def get_task_from_as(self, target=None, auth=None) -> dict:
        """Retrieve task from AS"""
        try:
            response = self.send_to_api(end_point="tasks", data={"satid": self.satid}).json()
        except requests.RequestException as e:
            print(f"Chyba pri ziskavani tasku z AS - {e}")
            return

        try:
            guid = response["data"]["guid"]
            action = response["data"]["action"]
            command = response["data"]["command"]
            return {"guid": guid, "action": action, "task": command}
        except Exception as e:
            return None



    def _delete_task_from_tasks(self, task) -> None:
        with open(os.path.join(os.path.dirname(os.path.realpath(__file__)), self.AS_ID, "tasks.json"), "r+") as f:
            original_json = json.loads(f.read())
            modified_json = [i for i in original_json if i["guid"] != task["guid"]]
            self.write_to_file_from_start(f, str(modified_json))


    def write_to_file_from_start(self, open_file, data: any) -> None:
        open_file.seek(0)
        open_file.truncate(0)
        open_file.write(data)


def parse_args():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("-T",    "--target",      type=str)
    parser.add_argument("-a",    "--auth",        type=str)
    parser.add_argument("-S",    "--sid",         type=str)
    parser.add_argument("-prj",  "--project_id",  type=str)
    parser.add_argument("-p",    "--proxy",       type=str)
    parser.add_argument("--no_ssl_verify",        action="store_false")

    parser.add_argument("-t",    "--threads",     type=int, default=20)

    args = parser.parse_args()
    return args


if __name__ == "__main__":
    args = parse_args()
    tool_subprocess = ProcessManager(args)
    tool_subprocess.run(args)