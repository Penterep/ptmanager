import argparse
import json; from json.decoder import JSONDecodeError
import os
import subprocess
import sys; sys.path.extend([__file__.rsplit("/", 1)[0], os.path.join(__file__.rsplit("/", 1)[0], "modules")])
import socket
import threading
import time
import pathlib

import requests

from process import Process
from config import Config


class Daemon:
    def __init__(self, args):
        self.config: Config          = Config(config_path=os.path.join(os.path.expanduser("~"), ".ptmanager/"))
        self.project_id: str         = args.project_id
        self.target: str             = args.target
        self.no_ssl_verify: bool     = args.no_ssl_verify
        self.socket_port: str        = args.port
        self.socket_address: str     = "127.0.0.1"
        self.proxies: dict           = {"http": args.proxy, "https": args.proxy}

        self.project_dir: str        = os.path.join(self.config.get_path(), "projects", self.project_id)
        self.project_tasks_file: str = os.path.join(self.project_dir, "tasks.json")

        self.free_threads            = [i for i in range(args.threads)]
        self.threads_list            = ["" for _ in range(args.threads)]
        self.lock                    = threading.Lock() # Tasks lock
        self.socket_lock             = threading.Lock() # Socket lock

        if not args.target or not args.auth :
            self.ptjsonlib.end_error(f"Target and auth are required", self.use_json)

        if not os.path.isdir(self.project_dir):
            os.makedirs(self.project_dir)

        # Start the socket server in a separate thread
        self.socket_server_thread = threading.Thread(target=self.start_socket_server, daemon=True)
        self.socket_server_thread.start()
        # Start loop
        self.start_loop(args.target, args.auth)

    def start_loop(self, target, auth) -> None:
        """Main loop"""
        while True:
            while not self.free_threads:
                time.sleep(8)

            # Send local results to application server
            self.send_results_to_server(target)

            # Retrieve tasks from application server
            task = self.get_task_from_server(target, auth)
            if not task:
                time.sleep(10)
                continue

            print("Received task:", task)

            if task["action"] == "new_task":
                thread_no = self.free_threads.pop()
                self.threads_list[thread_no] = threading.Thread(target=self.process_task, name=task["guid"], args=(task, thread_no), daemon=False)
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
        """Send local results to application server"""
        with self.lock:
            # Open tasks.json file
            with self.open_file(self.project_tasks_file, "r+") as tasks_file:
                try:
                    tasks_list: list = json.load(tasks_file)
                except JSONDecodeError:
                    tasks_list: list = []

        # Iterate in reverse order to safely modify the list
        for task_index in range(len(tasks_list) - 1, -1, -1):
            task_dict = tasks_list[task_index]

            # Skip tasks that are still running
            if task_dict["status"] == "running":
                continue

            # Prepare the task for sending
            task_dict["satid"] = self.config.get_satid()
            task_dict.pop("pid", None)  # Safely remove 'pid' if it exists
            task_dict.pop("timeStamp", None)  # Safely remove 'timeStamp' if it exists

            # Send the task to the API
            response = self.send_to_api(end_point="result", data=task_dict)
            if response.status_code == 200:
                # Remove the task from the list
                tasks_list.pop(task_index)

                # Write the updated tasks_list to tasks.json immediately after removal
                with self.open_file(self.project_tasks_file, "w") as tasks_file:
                    json.dump(tasks_list, tasks_file, indent=4)  # Save the updated list

    def send_to_api(self, end_point, data) -> requests.Response:
        target = self.target + "api/v1/sat/" + end_point
        response = requests.post(target, data=json.dumps(data), verify=self.no_ssl_verify, headers={"Content-Type": "application/json"}, proxies=self.proxies, allow_redirects=False)
        if response.status_code != 200:
            print(f"Error: Expected status code is 200, got {response.status_code}")
        return response

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
        """Process task received from application server"""

        # Save automat result to temp at /home/.ptmanager/temp/<guid>
        automat_output_path = os.path.join(self.config.get_temp_path(), task["guid"])

        # Call automat, save output to <automat_output_file>.
        with open(automat_output_path, "w+") as automat_output_file:
            automat_subprocess = subprocess.Popen(task["task"].split(), stdout=automat_output_file, stderr=automat_output_file, text=True)
            automat_result = {"guid": task["guid"], "pid": automat_subprocess.pid, "timeStamp": time.time(), "status": "running", "results": None}

        with self.lock:
            # Přečíst aktuální seznam úloh z tasks.json, pokud není vytvořen
            with self.open_file(self.project_tasks_file, "r") as tasks_file:
                try:
                    tasks_list: list = json.load(tasks_file)
                except JSONDecodeError:
                    tasks_list: list = []

            # Update <tasks_list> in memory
            tasks_list.append(automat_result)

            # Replace tasks.json content with the updated <tasks_list>
            with self.open_file(self.project_tasks_file, "w") as tasks_file:
                tasks_file.write(json.dumps(tasks_list, indent=4))

        # Wait for automat to finish
        automat_subprocess.wait()
        # Update automat_result status to 'finished' and remove the PID
        automat_result.update({"status": "finished", "pid": None})

        # Read automat result from <automat_output_file>
        with open(automat_output_path, "r") as automat_output_file:
            file_content = automat_output_file.read()
            try:
                tool_result = json.loads(file_content) # Output of arbitrary ptscript
            except:
                tool_result = {}
                automat_result["message"] = f"Error description: {file_content if file_content else 'File is empty.'}"

            automat_result["status"] = tool_result.get("status", "error")
            automat_result["results"] = json.dumps(tool_result.get("results", {}))

        # Remove the result file
        os.remove(automat_output_path)

        # Acquire the lock again for updating tasks_list
        with self.lock:

            # Load <tasks_list> from the tasks.json
            with self.open_file(self.project_tasks_file, "r") as tasks_file:
                tasks_list = json.load(tasks_file)
            # Update <tasks_list> with the finished automat result
            for task_index, task_dict in enumerate(tasks_list):
                if task_dict["guid"] == automat_result["guid"]:
                    tasks_list[task_index] = automat_result
            # Replace the content with the updated <tasks_list>
            with self.open_file(self.project_tasks_file, "w") as tasks_file:
                tasks_file.write(json.dumps(tasks_list, indent=4))

        # Release the lock and append the thread number to free_threads list
        self.free_threads.append(thread_no)


    def get_task_from_server(self, target=None, auth=None) -> dict:
        tasks_url = self.target + "api/v1/sat/tasks"
        try:
            response = requests.post(tasks_url, data=json.dumps({"satid": self.config.get_satid()}), verify=self.no_ssl_verify, proxies=self.proxies, headers={"Content-Type": "application/json"}, allow_redirects=False)
            if response.status_code == 200:
                response_data = response.json()
                return {"guid": response_data["data"]["guid"], "action": response_data["data"]["action"], "task": response_data["data"]["command"]}
            else:
                if response.status_code == 401:
                    print("Unauthorized")
                elif response.status_code == 400:
                    print("Queque empty")
                else:
                    print(f"Unexpected status code when retrieving tasks: {response.status_code}")
                return
        except:
            print("Error sending request to server to retrieve tasks")
            return

    def _delete_task_from_tasks(self, task) -> None:
        with open(os.path.join(os.path.dirname(os.path.realpath(__file__)), self.project_id, "tasks.json"), "r+") as f:
            original_json = json.loads(f.read())
            modified_json = [i for i in original_json if i["guid"] != task["guid"]]
            self.write_to_file_from_start(f, str(modified_json))


    def write_to_file_from_start(self, open_file, data: any) -> None:
        open_file.seek(0)
        open_file.truncate(0)
        open_file.write(data)


    def start_socket_server(self):
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.bind((self.socket_address, int(self.socket_port)))
        server.listen(100) # Backlog limit
        print(f"Socket Server listening on port {self.socket_port}")

        while True:
            client_socket, addr = server.accept()
            print(f"Accepted connection from {addr}")
            client_handler = threading.Thread(target=self.handle_socket_client, args=(client_socket,))
            client_handler.start()

    def handle_socket_client(self, client_socket):
        try:
            # Read until a newline character is found
            buffer = ""
            while True:
                data = client_socket.recv(1024).decode()
                print(json.loads(data), type(json.loads(data)))
                if not data:
                    break
                buffer += data
                if "\n" in buffer:
                    request, buffer = buffer.split("\n", 1)
                    # Acquire the lock before processing the request
                    with self.socket_lock:
                        # Process the request and save it
                        #self.process_request(request)
                        # Send an acknowledgment back to the client
                        print(request)
                        client_socket.send("Message received by server.\n".encode())
        finally:
            client_socket.close()

def parse_args():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--target",          type=str)
    parser.add_argument("--auth",            type=str)
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