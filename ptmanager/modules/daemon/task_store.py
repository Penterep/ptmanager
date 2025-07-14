"""
task_store.py

This module provides a thread-safe abstraction for reading and writing task data
to a shared JSON file. It ensures consistency and guards against race conditions
when accessed concurrently by multiple threads.

Typical usage:
    task_store = TaskStore("/path/to/tasks.json")
    task_store.append_task({...})
    tasks = task_store.load_tasks()
"""

import json
import os
import threading

class TaskStore:
    """
    A thread-safe class for managing task data in a JSON file.

    It handles file creation, loading, saving, and updating tasks,
    ensuring no race conditions occur during concurrent access.
    """

    def __init__(self, file_path):
        """
        Initialize the TaskStore.

        Args:
            file_path (str): Path to the tasks JSON file.
        """
        self.file_path = file_path
        self.lock = threading.RLock()
        self.ensure_file_exists()

    def ensure_file_exists(self):
        """
        Ensure the directory and file exist. Create file with an empty list if needed.
        """
        dir_path = os.path.dirname(self.file_path)
        if dir_path:
            os.makedirs(dir_path, exist_ok=True)

        if not os.path.exists(self.file_path):
            with open(self.file_path, "w") as f:
                json.dump([], f)

    def load_tasks(self):
        """
        Load and return the list of tasks from the JSON file.

        Returns:
            list: A list of task dictionaries. Returns an empty list if the file is empty or invalid.
        """
        with self.lock, open(self.file_path, "r") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return []

    def save_tasks(self, tasks):
        """
        Save the list of tasks to the JSON file.

        Args:
            tasks (list): The list of task dictionaries to save.
        """
        with self.lock, open(self.file_path, "w") as f:
            json.dump(tasks, f, indent=4)

    def append_task(self, task):
        """
        Append a new task to the task list and save it.

        Args:
            task (dict): The task dictionary to append.
        """
        with self.lock:
            tasks = self.load_tasks()
            tasks.append(task)
            self.save_tasks(tasks)

    def update_task(self, guid, updates):
        """
        Update an existing task identified by its GUID.

        Args:
            guid (str): The GUID of the task to update.
            updates (dict): Dictionary of keys/values to update in the task.
        """
        with self.lock:
            tasks = self.load_tasks()
            for task in tasks:
                if task["guid"] == guid:
                    task.update(updates)
                    break
            self.save_tasks(tasks)

    def remove_task(self, guid):
        """
        Remove a task from the task list based on its GUID.

        Args:
            guid (str): The GUID of the task to remove.
        """
        with self.lock:
            tasks = self.load_tasks()
            tasks = [t for t in tasks if t["guid"] != guid]
            self.save_tasks(tasks)

    def pop_finished_tasks(self):
        """
        Atomically retrieve and remove all finished tasks (status != 'running').

        Returns:
            list: List of removed finished task dictionaries.
        """
        with self.lock:
            tasks = self.load_tasks()
            finished = [t for t in tasks if t.get("status") != "running"]
            remaining = [t for t in tasks if t.get("status") == "running"]
            self.save_tasks(remaining)
            return finished