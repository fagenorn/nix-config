"""The verify checks for the bypass proof record and the next manager's mode (#1152).

Run: just agent-workflow-tests
"""
import copy
import json
import os
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agent_tools.console.bypass_proof import (
    ATTEMPT_NAMES, CHANGE_ID, FORBIDDEN_NAMES, GUARD_PREFIX, REQUIRED_CHECK, TEARDOWN_STEPS,
    expected_fragments)
from agent_tools.console.event_log import EventLog
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)
from .wake_proof_world import WakeProofWorld

ROOT = Path(__file__).resolve().parents[1]
RECORD_SCRIPT = "home/common/verify-pending/checks/bypass-proof-record"
MANAGERS_SCRIPT = "home/common/verify-pending/checks/bypass-proof-managers"
WAKES_SCRIPT = "home/common/verify-pending/checks/bypass-proof-wakes"
PROJECT = "fagenorn/nix-config"
BYPASS, AUTO = "bypassPermissions", "auto"
T = datetime(2026, 11, 16, 12, 0, 0, tzinfo=timezone.utc)


def passing_record(slug="fagenorn/bypass-proof-x", finished_at=T):
    attempts = []
    for name in ATTEMPT_NAMES:
        attempt = {"attempt": name, "permission_mode": BYPASS}
        if name in FORBIDDEN_NAMES:
            fragment = expected_fragments(slug, CHANGE_ID, REQUIRED_CHECK)[name]
            sentence = (fragment + "reason" if fragment.startswith(GUARD_PREFIX)
                        else GUARD_PREFIX + "unsafe: " + fragment)
            attempt.update(verdict="refused", sentence=sentence)
        else:
            attempt.update(verdict="allowed", sentence="")
        attempts.append(attempt)
    return {"schema_version": 1, "mode": "github", "repository": slug,
            "project_id": "bypass-proof/x", "started_at": (finished_at - timedelta(minutes=5)).isoformat(),
            "finished_at": finished_at.isoformat(), "outcome": "passed", "reason": None,
            "attempts": attempts,
            "teardown": [{"step": step, "ok": True, "detail": ""} for step in TEARDOWN_STEPS]}


def started(sprint, mode, project=PROJECT, permission=True):
    payload = {"sprint_id": sprint, "profile": "work", "session_name": "n", "seen_after": 0}
    if permission:
        payload["permission"] = {"mode": mode, "reason": "production rules in place"}
    return ("manager.started", project, payload)


class BypassProofChecksTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.dir = Path(temporary.name)
        self.record = self.dir / "bypass-proof.json"
        self.log = self.dir / "events.sqlite3"

    def write(self, record):
        self.record.write_text(json.dumps(record), encoding="utf-8")

    def append_at(self, at, *rows):
        log = EventLog(self.log, clock=lambda: at.isoformat(timespec="microseconds"))
        try:
            log.append(list(rows))
        finally:
            log.close()

    def run_script(self, script, *args):
        env = {**os.environ, "PYTHONPATH": str(ROOT / "python")}
        done = subprocess.run([str(ROOT / script), *args], cwd=ROOT, env=env,
                              capture_output=True, text=True, timeout=60)
        return done.returncode, json.loads(done.stdout)

    def check_record(self, record=None):
        if record is not None:
            self.write(record)
        return self.run_script(RECORD_SCRIPT, "--record", str(self.record))

    def check_managers(self):
        return self.run_script(MANAGERS_SCRIPT, "--project", PROJECT, "--record", str(self.record),
                               "--log", str(self.log))

    def test_a_complete_passing_github_record_is_met(self):
        code, output = self.check_record(passing_record())
        self.assertEqual((code, output["status"]), (0, "met"))
        self.assertEqual(output["repository"], "fagenorn/bypass-proof-x")
        self.assertEqual(output["finished_at"], T.isoformat())

    def test_no_record_is_not_yet(self):
        code, output = self.run_script(RECORD_SCRIPT, "--record", str(self.dir / "missing.json"))
        self.assertEqual((code, output["reason"]), (75, "no_record"))

    def test_a_record_missing_evidence_is_not_met(self):
        def drop_attempts(record):
            del record["attempts"]

        def drop_merge(record):
            record["attempts"] = [a for a in record["attempts"] if a["attempt"] != "merge"]

        def duplicate_push(record):
            record["attempts"].append(copy.deepcopy(record["attempts"][0]))

        def only_unregister(record):
            record["teardown"] = record["teardown"][:1]

        def recompile_twice(record):
            record["teardown"].append(copy.deepcopy(record["teardown"][1]))

        cases = [
            (drop_attempts, ["attempts unreadable"]),
            (drop_merge, ["attempt merge missing"]),
            (duplicate_push, ["attempt push duplicated"]),
            (only_unregister, ["teardown recompile missing", "teardown delete_repository missing",
                               "teardown remove_checkout missing"]),
            (recompile_twice, ["teardown recompile duplicated"]),
        ]
        for change, problems in cases:
            with self.subTest(change.__name__):
                record = passing_record()
                change(record)
                code, output = self.check_record(record)
                self.assertEqual(code, 1)
                self.assertEqual(output["status"], "not_met")
                for problem in problems:
                    self.assertIn(problem, output["problems"])

    def test_a_record_contradicting_its_outcome_is_not_met(self):
        def attempt(record, name):
            return next(a for a in record["attempts"] if a["attempt"] == name)

        def push_effect(record):
            attempt(record, "push")["verdict"] = "took_effect"

        def route_blocked(record):
            attempt(record, "read_only_route")["verdict"] = "not_allowed"

        def merge_lookup(record):
            attempt(record, "merge")["sentence"] = "lifecycle guard: PR lookup failed"

        def auto_mode(record):
            attempt(record, "release")["permission_mode"] = AUTO

        def delete_failed(record):
            next(e for e in record["teardown"] if e["step"] == "delete_repository")["ok"] = False

        cases = [
            (push_effect, "attempt push took_effect"),
            (route_blocked, "attempt read_only_route not_allowed"),
            (merge_lookup, "attempt merge sentence"),
            (auto_mode, "attempt release not in bypass"),
            (delete_failed, "teardown delete_repository failed"),
        ]
        for change, problem in cases:
            with self.subTest(change.__name__):
                record = passing_record()
                change(record)
                code, output = self.check_record(record)
                self.assertEqual(code, 1)
                self.assertIn(problem, output["problems"])

    def test_a_failed_outcome_is_not_met(self):
        record = passing_record()
        record["outcome"] = "failed"
        record["attempts"][0]["verdict"] = "took_effect"
        code, output = self.check_record(record)
        self.assertEqual(code, 1)
        self.assertIn("outcome failed", output["problems"])
        self.assertIn("attempt push took_effect", output["problems"])

    def test_an_unhashable_entry_name_is_unexpected_not_a_crash(self):
        def list_attempt(record):
            record["attempts"].append({"attempt": ["x"]})

        def dict_step(record):
            record["teardown"].append({"step": {"a": 1}, "ok": True})

        for change, problem in ((list_attempt, "attempt ['x'] unexpected"),
                                (dict_step, "teardown {'a': 1} unexpected")):
            with self.subTest(change.__name__):
                record = passing_record()
                change(record)
                code, output = self.check_record(record)
                self.assertEqual((code, output["status"]), (1, "not_met"))
                self.assertIn(problem, output["problems"])
                self.write(record)
                self.append_at(T + timedelta(hours=1), started("after", BYPASS))
                code, output = self.check_managers()
                self.assertEqual((code, output["reason"]), (75, "no_proof"))

    def test_a_run_mode_record_does_not_count(self):
        record = passing_record()
        record["mode"] = "run"
        self.assertEqual(self.check_record(record)[0], 75)

    def test_the_first_manager_after_the_proof_in_bypass_is_met(self):
        self.write(passing_record())
        self.append_at(T - timedelta(hours=1), started("before", AUTO))
        self.append_at(T + timedelta(hours=1), started("after", BYPASS))
        code, output = self.check_managers()
        self.assertEqual((code, output["status"], output["sprint_id"]), (0, "met", "after"))

    def test_a_manager_after_the_proof_in_auto_is_not_met(self):
        self.write(passing_record())
        self.append_at(T + timedelta(hours=1), started("after", AUTO))
        code, output = self.check_managers()
        self.assertEqual((code, output["status"], output["sprint_id"]), (1, "not_met", "after"))

    def test_a_later_manager_never_stands_in_for_a_first_one_without_evidence(self):
        for label, first in (("no permission", started("first", AUTO, permission=False)),
                             ("no sprint", ("manager.started", PROJECT, {
                                 "permission": {"mode": BYPASS, "reason": "r"}})),
                             ("bad permission", ("manager.started", PROJECT, {
                                 "sprint_id": "first", "permission": {"mode": 3}}))):
            with self.subTest(label):
                self.write(passing_record())
                self.log.unlink(missing_ok=True)
                self.append_at(T + timedelta(hours=1), first)
                self.append_at(T + timedelta(hours=2), started("second", BYPASS))
                code, output = self.check_managers()
                self.assertEqual((code, output["status"], output["reason"]),
                                 (1, "not_met", "no_permission"))

    def test_an_unrelated_push_refusal_in_a_record_is_not_met(self):
        record = passing_record()
        push = next(a for a in record["attempts"] if a["attempt"] == "push")
        push["sentence"] = GUARD_PREFIX + "unsafe push: push URL lookup timed out"
        code, output = self.check_record(record)
        self.assertEqual((code, output["problems"]), (1, ["attempt push sentence"]))

    def test_no_manager_after_the_proof_is_not_yet(self):
        self.write(passing_record())
        self.append_at(T - timedelta(hours=1), started("before", BYPASS))
        code, output = self.check_managers()
        self.assertEqual((code, output["reason"]), (75, "no_manager"))

    def test_managers_check_waits_for_a_complete_passing_proof(self):
        incomplete = passing_record()
        incomplete["attempts"] = [a for a in incomplete["attempts"] if a["attempt"] != "merge"]
        self.append_at(T + timedelta(hours=1), started("after", BYPASS))
        for label, record in (("no record", None), ("merge missing", incomplete)):
            with self.subTest(label):
                self.record.unlink(missing_ok=True)
                if record is not None:
                    self.write(record)
                code, output = self.check_managers()
                self.assertEqual((code, output["reason"]), (75, "no_proof"))

    def test_scripts_are_committed_executable(self):
        for script in (RECORD_SCRIPT, MANAGERS_SCRIPT):
            with self.subTest(script):
                self.assertTrue(os.access(ROOT / script, os.X_OK))


class WakeCheckTest(unittest.TestCase):
    """The wake check's exit is the wake step's exit, unchanged (#1230)."""

    def run_check(self, *args, **extra):
        world = WakeProofWorld(self)
        done = subprocess.run([str(ROOT / WAKES_SCRIPT), *args], cwd=ROOT,
                              env={**world.env, **extra}, capture_output=True, text=True,
                              timeout=120)
        return done.returncode, done.stdout

    def test_the_wake_check_is_met_when_both_wakes_reach_the_manager(self):
        code, out = self.run_check()
        self.assertEqual(0, code)
        self.assertEqual("passed", json.loads(out)["outcome"])

    def test_the_wake_check_is_not_met_when_a_wake_is_held(self):
        code, out = self.run_check("--wake-wait", "2", FAKE_CLIENT_HOLD_AFTER="1")
        self.assertEqual(1, code)
        self.assertEqual("failed", json.loads(out)["outcome"])

    def test_the_wake_check_is_not_yet_when_the_step_cannot_start(self):
        code, out = self.run_check(CLAUDECODE="1")
        self.assertEqual(75, code)
        self.assertEqual("refused", json.loads(out)["outcome"])

    def test_the_wake_check_refuses_a_bad_argument(self):
        code, _ = self.run_check("--wake-wait", "nope")
        self.assertEqual(2, code)

    def test_the_wake_check_is_committed_executable(self):
        done = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-s", WAKES_SCRIPT],
                              capture_output=True, text=True, timeout=60)
        self.assertTrue(done.stdout.startswith("100755 "), done.stdout)


if __name__ == "__main__":
    unittest.main()
