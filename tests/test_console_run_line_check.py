"""The verify script that a run line under a sprint waiting its turn to merge never reads quiet (#1212).

Run: just agent-workflow-tests
"""
import contextlib
import io
import json
import unittest

from agent_tools.console import run_line_check
from agent_tools.console.movement import PullRequest
from agent_tools.system.forge_api import ForgeError
from tests.test_verify_checks import committed_mode
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)

WRAPPER = "home/common/verify-pending/checks/console-run-line"
NOW = 1_794_866_817
PROJECT = "owner/p00"
PATTERN = "issue-<num>-<slug>"
P40 = PullRequest(40, frozenset({4}), False, None, True)
P41 = PullRequest(41, frozenset({5}), False, None, False)
WAITER_41 = {"refs/agent-locks/land-wait/main/1794865617-41-1794866800": "41" * 20}
LOCK_TEXT = "waiting its turn to merge"


def sprint(sprint_id="a" * 16, issue=5, now_text=LOCK_TEXT, ended_at=None, inbox=None,
           runs=()):
    """A running sprint; with `inbox` its issue is only an inbox issue; `runs` are the deliveries
    of its own session."""
    shown = [] if inbox is not None else [
        {"issue": issue, "stage": "landing", "stage_text": "landing"}]
    return {"sprint_id": sprint_id, "ended_at": ended_at, "state": "on_track", "ball": "manager",
            "now_text": now_text, "issues": shown,
            "movement": {"issues": [issue] if inbox is None else [inbox]},
            "sessions": [{"session_id": "s1", "deliveries": list(runs)}] if runs else []}


def run_entry(run_id="wf_l1", issue=5, quiet=False, moved_text=LOCK_TEXT):
    return {"run_id": run_id, "issues": [{"issue": issue, "stage": "landing"}],
            "quiet": quiet, "moved_text": moved_text}


def state_of(sprints, outside_runs, grouped=False):
    entry = {"type": "project", "project_id": PROJECT, "sprints": list(sprints),
             "outside_sprints": {"sessions": [{"session_id": "d1",
                                               "deliveries": list(outside_runs)}]}}
    return {"entries": [{"type": "quiet_group", "projects": [entry]} if grouped else entry]}


class RunLineCheckTest(unittest.TestCase):
    def run_check(self, *, pulls=(P40, P41), waiters=WAITER_41, state=None, read_pulls=None,
                  read_state=None):
        state = state_of([sprint()], [run_entry()]) if state is None else state
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = run_line_check.main(
                ["--project", PROJECT, "--repo", PROJECT, "--pattern", PATTERN],
                read_pulls=read_pulls or (lambda slug, pattern: tuple(pulls)),
                read_waiters=lambda slug: waiters, forge_now=lambda: NOW,
                read_state=read_state or (lambda port: state))
        return code, json.loads(out.getvalue())

    def test_a_queue_whose_waiting_run_line_names_its_wait_is_met(self):
        code, printed = self.run_check()
        self.assertEqual(0, code)
        self.assertEqual("met", printed["status"])
        self.assertEqual([40, 41], printed["queued"])
        self.assertEqual([{"run_id": "wf_l1", "moved_text": LOCK_TEXT}], printed["runs"])

    def test_a_quiet_run_line_under_a_waiting_sprint_is_not_met(self):
        quiet = run_entry(quiet=True, moved_text="quiet for 45 min")
        code, printed = self.run_check(state=state_of([sprint()], [quiet]))
        self.assertEqual(1, code)
        self.assertEqual("not_met", printed["status"])
        self.assertEqual(["wf_l1"], printed["quiet"])
        own = run_entry(run_id="wf_l2", quiet=True, moved_text="quiet for 45 min")
        code, printed = self.run_check(state=state_of([sprint(runs=[own])], []))
        self.assertEqual(1, code)
        self.assertEqual(["wf_l2"], printed["quiet"])

    def test_a_quiet_run_of_an_issue_not_in_the_queue_is_not_judged(self):
        waiting = sprint(inbox=5)
        waiting["movement"]["issues"] = [5, 6]
        quiet = run_entry(issue=6, quiet=True, moved_text="quiet for 45 min")
        code, printed = self.run_check(state=state_of([waiting], [quiet]))
        self.assertEqual(75, code)
        self.assertEqual("no_run", printed["status"])
        holder_run = run_entry(issue=4, quiet=True, moved_text="quiet for 45 min")
        code, printed = self.run_check(state=state_of([sprint()], [holder_run]))
        self.assertEqual(75, code)
        self.assertEqual("no_run", printed["status"])

    def test_a_run_needs_one_issue_shared_by_the_queue_its_sprint_and_itself(self):
        waiting = sprint(inbox=5)
        waiting["movement"]["issues"] = [5, 6]
        straddling = run_entry(issue=4, quiet=True, moved_text="quiet for 45 min")
        straddling["issues"].append({"issue": 6, "stage": "landing"})
        code, printed = self.run_check(state=state_of([waiting], [straddling]))
        self.assertEqual((75, "no_run"), (code, printed["status"]))

    def test_a_quiet_field_that_is_not_an_explicit_false_is_not_yet(self):
        for label, change in (("absent", None), ("null", None), ("string", "no"), ("zero", 0)):
            with self.subTest(label):
                run = run_entry()
                if label == "absent":
                    del run["quiet"]
                else:
                    run["quiet"] = change
                code, printed = self.run_check(state=state_of([sprint()], [run]))
                self.assertEqual((75, "unreadable_run"), (code, printed["status"]))
                self.assertEqual(["wf_l1"], printed["runs"])

    def test_no_queue_no_console_no_wait_shown_and_no_run_are_not_yet(self):
        def refuse(slug, pattern):
            raise ForgeError("rate limited")

        def down(port):
            raise OSError("connection refused")

        building = sprint(now_text="building 1 of 2: x")
        cases = {
            "no_queue": dict(pulls=(P41,)),
            "no_long_waiter": dict(waiters={
                "refs/agent-locks/land-wait/main/1794866757-41-1794866800": "41" * 20}),
            "no_console": dict(read_state=down),
            "no_wait_shown": dict(state=state_of([building], [run_entry()])),
            "no_run": dict(state=state_of([sprint()], [])),
            "forge_unreadable": dict(read_pulls=refuse),
        }
        for status, kwargs in cases.items():
            with self.subTest(status):
                code, printed = self.run_check(**kwargs)
                self.assertEqual(75, code)
                self.assertEqual("no_queue" if status == "no_long_waiter" else status,
                                 printed["status"])

    def test_a_grouped_project_is_read(self):
        code, printed = self.run_check(state=state_of([sprint()], [run_entry()], grouped=True))
        self.assertEqual(0, code)
        self.assertEqual("met", printed["status"])

    def test_the_wrapper_is_committed_executable(self):
        self.assertEqual("100755", committed_mode(WRAPPER))


if __name__ == "__main__":
    unittest.main()
