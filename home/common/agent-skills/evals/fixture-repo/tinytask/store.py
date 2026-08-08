"""Single-file JSON backing store for the backlog.

See ADR-backlog-001 (docs/areas/backlog/adr/001-json-file-store.md) for why this is a
file and not a database.
"""

import json
import os
import tempfile

from .model import DONE, Task


class Store:
    def __init__(self, path):
        self.path = path

    def load(self):
        if not os.path.exists(self.path):
            return []
        with open(self.path, encoding="utf-8") as handle:
            raw = json.load(handle)
        return [Task.from_dict(item) for item in raw]

    def save(self, tasks):
        """Write the whole backlog atomically — a crash never leaves a half file."""
        payload = json.dumps([task.to_dict() for task in tasks], indent=2) + "\n"
        directory = os.path.dirname(os.path.abspath(self.path))
        os.makedirs(directory, exist_ok=True)
        handle_fd, staging = tempfile.mkstemp(dir=directory)
        try:
            with os.fdopen(handle_fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
            os.replace(staging, self.path)
        except BaseException:
            if os.path.exists(staging):
                os.unlink(staging)
            raise

    def add(self, title):
        tasks = self.load()
        task = Task(id=max([task.id for task in tasks], default=0) + 1, title=title)
        tasks.append(task)
        self.save(tasks)
        return task

    def complete(self, task_id):
        """Mark a task done. Returns the task, or None when the id is unknown."""
        tasks = self.load()
        for task in tasks:
            if task.id == task_id:
                task.state = DONE
                self.save(tasks)
                return task
        return None
