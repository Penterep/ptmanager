import argparse
import json; from json.decoder import JSONDecodeError
import os
import subprocess
import sys; sys.path.extend([__file__.rsplit("/", 1)[0], os.path.join(__file__.rsplit("/", 3)[0], "modules")])
import socket
import threading
import time
import pathlib
import urllib
import requests

from process import Process
from config import Config
from burp_listener import BurpSocketListener

import queue
from queue import Queue # Thread safe

from task_store import TaskStore

class Daemon:
    def __init__(self, args):
        self.config: Config          = Config(config_path=os.path.join(os.path.expanduser("~"), ".ptmanager/"))
        self.project_id: str         = args.project_id
        self.target: str             = args.target
        self.no_ssl_verify: bool     = args.no_ssl_verify
        self.socket_port: str        = args.port
        self.burpsuite_port          = args.port
        self.socket_address: str     = "127.0.0.1"
        self.proxies: dict           = {"http": args.proxy, "https": args.proxy}
        self.project_dir: str        = os.path.join(self.config.get_path(), "projects", self.project_id)

        self.project_tasks_file: str = os.path.join(self.project_dir, "tasks.json")
        self.task_store              = TaskStore(self.project_tasks_file)

        self.free_threads            = [i for i in range(args.threads)]
        self.threads_list            = ["" for _ in range(args.threads)]
        self.lock                    = threading.Lock() # Tasks lock

        # Create project_dir if not exists
        if not os.path.isdir(self.project_dir):
            os.makedirs(self.project_dir)

        # Start burp socket listener
        self.burpsuite_listener_thread = threading.Thread(target=self.start_burp_listener, args=(Queue(), ), daemon=True)
        self.burpsuite_listener_thread.start()

        # Start AS loop
        self.start_loop(args.target, args.auth)

    def start_burp_listener(self, queue):
        """Start BurpSuite listener for incoming data."""
        self.burp_listener = BurpSocketListener(daemon=self, config=self.config, port=int(self.socket_port), data_callback=lambda d: queue.put(d))

    def start_loop(self, target, auth) -> None:
        """Main loop for task processing."""
        while True:

            # Ensure there are free threads available
            while not self.free_threads:
                time.sleep(8)

            # Send local results to application server
            self.send_results_to_server(target)

            # Retrieve and process tasks from the server
            task = self.get_task_from_server(target, auth)

            if task:
                self.process_task_based_on_action(task)
            else:
                time.sleep(5)
                continue

    def process_task_based_on_action(self, task):
        """Process the task depending on its action type."""
        print(f"New task: {task}")
        if task["action"] == "new_task":
            self.handle_new_task(task)
        elif task["action"] == "status":
            self.status_task(task)
        elif task["action"] == "status-all":
            self.status_all_tasks()
        elif task["action"] == "kill-task":
            self.kill_task(task)
        elif task["action"] == "kill-all":
            self.kill_all_tasks()

    def handle_new_task(self, task):
        """Handle a new task."""
        if task["command"].lower().startswith("burpsuiteplugin"):
            self.handle_burpsuite_plugin_task(task)
        else:
            self.run_external_automat(task)

    def handle_burpsuite_plugin_task(self, task):
        """Handle tasks related to BurpSuite plugin."""
        parts = task["command"].strip().split()
        if len(parts) == 2:
            url = parts[1]
            parsed_domain = urllib.parse.urlparse(url).netloc
            self.burp_listener.domain_guid_map[parsed_domain] = task["guid"]
            self.burp_listener.send_domain_to_burp_scope(url)

    def run_external_automat(self, task):
        """Run an external automation task."""
        thread_no = self.free_threads.pop()
        self.threads_list[thread_no] = threading.Thread(target=self.process_task, name=task["guid"], args=(task, thread_no), daemon=False)
        self.threads_list[thread_no].start()

    def send_results_to_server(self, target) -> None:
        """Send local results to application server."""
        finished_tasks = self.task_store.pop_finished_tasks()

        for task_dict in finished_tasks:
            # Prepare task
            task_dict["satid"] = self.config.get_satid()
            task_dict.pop("pid", None)
            task_dict.pop("timeStamp", None)

            # Send to API
            response = self.send_to_api(end_point="result", data=task_dict)

            # If send fails, re-append the task to store (optional but useful)
            if response.status_code != 200:
                self.task_store.append_task(task_dict)

    def send_to_api(self, end_point, data) -> requests.Response:
        """Send data to the API."""
        target = self.target + "api/v1/sat/" + end_point
        response = requests.post(target, data=json.dumps(data), verify=self.no_ssl_verify, headers={"Content-Type": "application/json"}, proxies=self.proxies, allow_redirects=False)

        if response.status_code != 200:
            print(f"Error sending to {'api/v1/sat/' + end_point}: Expected status code is 200, got {response.status_code}")
        return response

    def status_all_tasks(self) -> None:
        """
        Repairs all tasks.

        Retrieves the status of all tasks in the project. If a task is not running,
        it updates its status to 'error' and sets the process ID (pid) to None in the
        tasks JSON file.

        """
        with self.lock:
            try:
                with self.open_file(self.project_tasks_file, "r+") as tasks_file:
                    tasks_list = json.loads(tasks_file.read())
                    for task in tasks_list:
                        if not Process(task.get("pid")).is_running():
                            task["status"] = "error"
                            task["pid"] = None
                with self.open_file(self.project_tasks_file, "w") as tasks_file:
                    json.dump(tasks_list, tasks_file, indent=4)
            except JSONDecodeError as e:
                print("Error decoding JSON:", e)

    def status_task(self, task) -> None:
        """Retrieve status of <task>, repairs tasks.json if task is not running"""
        with self.lock:
            with self.open_file(self.project_tasks_file, "r+") as tasks_file:
                tasks_list = json.load(tasks_file)
                for task_item in tasks_list:
                    if task_item["guid"] == task["guid"]:
                        if not Process(task_item["pid"]).is_running():
                            task_item["status"] = "error"
                            task_item["pid"] = None
                tasks_file.seek(0)
                tasks_file.truncate(0)
                json.dump(tasks_list, tasks_file, indent=4)
                #tasks_file.write(json.dumps(tasks_list, indent=4))

    def kill_all_tasks(self) -> None:
        """Kills all tasks."""

        for t in self.threads_list:
            if isinstance(t, threading.Thread):
                t.join()

        for file in os.listdir(self.project_dir):
            if file != "tasks.json":
                os.remove(os.path.join(self.project_dir, file))

        # TODO: Kill all task threads
        self.lock.acquire()
        with self.open_file(self.project_tasks_file, "r+") as tasks_file:
            try:
                tasks_list = json.loads(tasks_file.read())
                for task in tasks_list:
                    if task["pid"]:
                        Process(task["pid"]).kill()
                        task["status"] = "killed"
                        task["pid"] = None
                tasks_file.seek(0)
                tasks_file.truncate(0)
                tasks_file.write(json.dumps(tasks_list, indent=4))
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
        with self.open_file(self.project_tasks_file, "r+") as tasks_file:
            try:
                tasks_list = json.loads(tasks_file.read())
                for task_in_list in tasks_list:
                    if task_in_list["guid"] == task["guid"]:
                        if task_in_list["pid"]:
                            Process(task_in_list["pid"]).kill()
                            task_in_list["status"] = "killed"
                            task_in_list["pid"] = None
                tasks_file.seek(0)
                tasks_file.truncate(0)
                tasks_file.write(json.dumps(tasks_list, indent=4))
            except JSONDecodeError:
                pass
            finally:
                self.lock.release()

    def open_file(self, filename, mode):
        """
        Open a file in the specified mode, creating it if it doesn't exist.

        Args:
            filename (str): The name of the file to open.
            mode (str): The mode in which to open the file ('r', 'w', 'a', etc.).

        Returns:
            file: An open file object.
        """
        # Check if the file exists
        if not os.path.exists(filename):
            # If the file doesn't exist, create it
            with open(filename, "x"):
                pass  # File created
        # Open the file in the specified mode
        return open(filename, mode)

    def process_task(self, task: dict, thread_no: int) -> None:
        """
        Process a task received from the application server:
        - Launches the external command defined in the task.
        - Logs the execution status (running → finished).
        - Parses and stores the tool output.
        - Updates the task store with results.
        - Frees the thread upon completion.

        Args:
            task (dict): Task dictionary containing at least "guid" and "command".
            thread_no (int): Identifier of the worker thread handling this task.
        """

        guid = task["guid"]
        command = task["command"]
        temp_path = os.path.join(self.config.get_temp_path(), guid) # /home/.ptmanager/temp/<guid>

        # Run external command (automat) and save result to temp_path
        with open(temp_path, "w+") as output_file:
            process = subprocess.Popen(
                command.split(),
                stdout=output_file,
                stderr=output_file,
                text=True
            )

        # Create running task record
        running_task = {
            "guid": guid,
            "pid": process.pid,
            "timeStamp": time.time(),
            "status": "running",
            "results": None
        }

        self.task_store.append_task(running_task)

        # Wait for completion
        process.wait()

        # Load and parse result
        try:
            with open(temp_path, "r") as output_file:
                output_content = output_file.read()
                parsed_result = json.loads(output_content)
        except Exception:
            parsed_result = {}
            output_content = output_content if output_content else "File is empty."
            running_task["message"] = f"Error description: {output_content}"

        # Update task with result
        running_task.update({
            "pid": None,
            "status": parsed_result.get("status", "error"),
            "results": json.dumps(parsed_result.get("results", {})),
            "message": running_task.get("message")  # Optional
        })

        self.task_store.update_task(guid, running_task)

        os.remove(temp_path)

        # Mark thread as free
        self.free_threads.append(thread_no)


    def get_task_from_server(self, target=None, auth=None) -> dict | None:
        """Retrieve a new task from the application server."""
        tasks_url = self.target + "api/v1/sat/tasks"
        try:
            headers = {"Content-Type": "application/json"}
            payload = {"satid": self.config.get_satid()}
            response = requests.post(
                tasks_url,
                data=json.dumps(payload),
                headers=headers,
                proxies=self.proxies,
                verify=self.no_ssl_verify,
                allow_redirects=False
            )

            # Return if status != 200
            if response.status_code != 200:
                if response.status_code == 401:
                    print("[401 Unauthorized] Received unauthorized response when retrieving task.")
                else:
                    print(f"[{response.status_code}] Unexpected response code while retrieving task.")
                return

            response_data = response.json()
            if response_data.get("message", "").lower() == "test queue is empty": # If empty queue, return
                return

            task_data = response_data.get("data", {})

            return {
                "guid": task_data.get("guid"),
                "action": task_data.get("action"),
                "command": task_data.get("command")
            }

        except Exception as e:
            print("Error sending request to server to retrieve tasks: {e}", e)
            return


def parse_args():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--target",          type=str, required=True)
    parser.add_argument("--auth",            type=str, required=True)
    parser.add_argument("--project-id",     type=str)
    parser.add_argument("--proxy",           type=str)
    parser.add_argument("--port",            type=str)
    parser.add_argument("--no_ssl_verify",   action="store_false")
    parser.add_argument("--threads",         type=int, default=20)

    args = parser.parse_args()
    return args


if __name__ == "__main__":
    args = parse_args()
    requests.packages.urllib3.disable_warnings()
    daemon = Daemon(args)