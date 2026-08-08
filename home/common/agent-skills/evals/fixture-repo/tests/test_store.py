import json
import os
import tempfile
import unittest

from tinytask.model import DONE, OPEN, Task
from tinytask.store import Store


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.store = Store(os.path.join(self.directory, "tasks.json"))

    def test_missing_file_loads_as_empty_backlog(self):
        self.assertEqual(self.store.load(), [])

    def test_add_assigns_sequential_ids(self):
        first = self.store.add("write the spec")
        second = self.store.add("write the plan")
        self.assertEqual((first.id, second.id), (1, 2))
        self.assertEqual(first.state, OPEN)

    def test_add_round_trips_through_the_file(self):
        self.store.add("write the spec")
        reloaded = Store(self.store.path).load()
        self.assertEqual([task.title for task in reloaded], ["write the spec"])

    def test_complete_marks_done_and_persists(self):
        task = self.store.add("write the spec")
        self.assertEqual(self.store.complete(task.id).state, DONE)
        self.assertEqual(self.store.load()[0].state, DONE)

    def test_complete_returns_none_for_unknown_id(self):
        self.assertIsNone(self.store.complete(99))

    def test_save_leaves_no_staging_files_behind(self):
        self.store.add("write the spec")
        self.assertEqual(os.listdir(self.directory), ["tasks.json"])

    def test_file_is_valid_json_with_the_documented_keys(self):
        self.store.add("write the spec")
        with open(self.store.path, encoding="utf-8") as handle:
            raw = json.load(handle)
        self.assertEqual(sorted(raw[0]), ["id", "state", "title"])


class TaskTest(unittest.TestCase):
    def test_unknown_state_is_rejected(self):
        with self.assertRaises(ValueError):
            Task(id=1, title="write the spec", state="wibble")


if __name__ == "__main__":
    unittest.main()
