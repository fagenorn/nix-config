"""The verify script that this host runs the commit the console's Activate activated (#1193).

Run: just agent-workflow-tests
"""
import contextlib
import io
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from agent_tools.console import activation_check, event_log
from tests.test_verify_checks import committed_mode
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)

ROOT = Path(__file__).resolve().parents[1]
WRAPPER = "home/common/verify-pending/checks/console-activation"
MERGE = "m" * 40
C0, C1, C2 = "0" * 40, "1" * 40, "2" * 40


def finished(ok, commit):
    return {"root": "/r", "commit": commit, "ok": ok, "reason": None, "next_step": None}


def contains_in(*commits):
    return lambda merge, commit: commit in commits


def run_module(*arguments):
    env = {**os.environ, "PYTHONPATH": str(ROOT / "python")}
    return subprocess.run(
        [sys.executable, "-m", "agent_tools.console.activation_check", *arguments],
        cwd=ROOT, env=env, capture_output=True, text=True, check=False)


class VerdictTest(unittest.TestCase):
    def test_a_page_activation_the_host_runs_is_met(self):
        code, document = activation_check.verdict(
            MERGE, [finished(True, C1)], C1, contains_in(C1))
        self.assertEqual((code, document), (0, {"status": "met", "commit": C1, "revision": C1}))

    def test_no_page_activation_yet_is_waiting(self):
        for rows, contains in (([], contains_in(C1)),
                               ([finished(False, C1)], contains_in(C1)),
                               ([finished(True, C1)], contains_in())):
            with self.subTest(rows=rows):
                code, document = activation_check.verdict(MERGE, rows, C1, contains)
                self.assertEqual((code, document["status"]), (75, "waiting"))

    def test_a_host_not_running_the_activated_commit_is_not_met(self):
        for revision in ("d" * 40, None):
            with self.subTest(revision=revision):
                code, document = activation_check.verdict(
                    MERGE, [finished(True, C1)], revision, contains_in(C1))
                self.assertEqual((code, document["status"]), (1, "not_met"))

    def test_the_newest_containing_activation_counts(self):
        code, document = activation_check.verdict(
            MERGE, [finished(True, C1), finished(True, C2)], C2, contains_in(C1, C2))
        self.assertEqual((code, document), (0, {"status": "met", "commit": C2, "revision": C2}))

    def test_an_older_containing_success_does_not_count_after_a_newer_one(self):
        code, document = activation_check.verdict(
            MERGE, [finished(True, C1), finished(True, C0)], C1, contains_in(C1))
        self.assertEqual((code, document), (75, {"status": "waiting"}))


class StoreTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def test_an_absent_store_is_unreadable_and_not_created(self):
        store = self.dir / "absent.sqlite3"
        done = run_module("--merge", MERGE, "--store", str(store))
        self.assertEqual(done.returncode, 2, done.stderr)
        self.assertEqual(list(self.dir.iterdir()), [])

    def test_an_older_schema_store_is_left_unchanged(self):
        store = self.dir / "old.sqlite3"
        connection = sqlite3.connect(store)
        connection.execute("PRAGMA user_version = 1")
        connection.execute(
            "CREATE TABLE events(seq INTEGER PRIMARY KEY, at INTEGER, kind TEXT, project TEXT, "
            "payload TEXT)")
        connection.execute("INSERT INTO events(at, kind, project, payload) "
                           "VALUES (1, 'activation.finished', NULL, '{}')")
        connection.commit()
        connection.close()
        before = store.read_bytes()
        done = run_module("--merge", MERGE, "--store", str(store))
        self.assertIn(done.returncode, (2, 75), done.stderr)
        self.assertEqual(store.read_bytes(), before)
        connection = sqlite3.connect(store)
        self.addCleanup(connection.close)
        self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 1)

    def test_a_newer_schema_store_is_read_normally(self):
        # A later merge bumped the console's schema and the running console migrated the store
        # forward; the check, run at an earlier merge's tree, must still read its rows.
        store = self.dir / "new.sqlite3"
        connection = sqlite3.connect(store)
        connection.execute(f"PRAGMA user_version = {event_log.SCHEMA_VERSION + 1}")
        connection.execute(
            "CREATE TABLE events(seq INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT, kind TEXT, "
            "project TEXT, payload TEXT)")
        connection.execute(
            "INSERT INTO events(at, kind, project, payload) VALUES (?, 'activation.finished', NULL, ?)",
            ("2026-11-17T00:00:00+00:00", json.dumps(finished(True, C1))))
        connection.commit()
        connection.close()
        self.assertEqual(activation_check.read_rows(store), [finished(True, C1)])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = activation_check.main(
                ["--merge", C1, "--store", str(store)], revision=lambda: C1)
        self.assertEqual(
            (code, json.loads(out.getvalue())),
            (0, {"status": "met", "commit": C1, "revision": C1}))

    def test_the_wrapper_is_committed_executable(self):
        self.assertEqual("100755", committed_mode(ROOT / WRAPPER))


if __name__ == "__main__":
    unittest.main()
