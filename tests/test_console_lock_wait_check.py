"""The verify script that a sprint queued for the land lock shows its wait (#1184).

Run: just agent-workflow-tests
"""
import contextlib
import io
import json
import unittest
from unittest import mock

from agent_tools.console import deliveries, lock_wait_check, service
from agent_tools.console.movement import PullRequest
from agent_tools.system.forge_api import ForgeError
from tests.test_verify_checks import committed_mode
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)

WRAPPER = "home/common/verify-pending/checks/console-lock-wait"
NOW = 1_794_866_817
PROJECT = "owner/p00"
PATTERN = "issue-<num>-<slug>"
P40 = PullRequest(40, frozenset({4}), False, None, True)
P41 = PullRequest(41, frozenset({5}), False, None, False)
WAITER_41 = {"refs/agent-locks/land-wait/main/1794865617-41-1794866800": "41" * 20}


def sprint(sprint_id="a" * 16, issue=5, state="on_track", ball="manager",
           now_text="waiting its turn to merge", ended_at=None):
    return {"sprint_id": sprint_id, "ended_at": ended_at, "state": state, "ball": ball,
            "now_text": now_text,
            "issues": [{"issue": issue, "stage": "landing", "stage_text": "landing"}]}


def state_of(*sprints, grouped=False):
    entry = {"type": "project", "project_id": PROJECT, "sprints": list(sprints)}
    return {"entries": [{"type": "quiet_group", "projects": [entry]} if grouped else entry]}


class LockWaitCheckTest(unittest.TestCase):
    def run_check(self, *, pulls=(P40, P41), waiters=WAITER_41, state=None, argv=None,
                  read_pulls=None, read_state=None):
        state = state_of(sprint()) if state is None else state
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = lock_wait_check.main(
                argv or ["--project", PROJECT, "--repo", PROJECT, "--pattern", PATTERN],
                read_pulls=read_pulls or (lambda slug, pattern: tuple(pulls)),
                read_waiters=lambda slug: waiters, forge_now=lambda: NOW,
                read_state=read_state or (lambda port: state))
        return code, json.loads(out.getvalue())

    def test_a_queue_of_two_whose_sprint_reads_moving_is_met(self):
        code, printed = self.run_check()
        self.assertEqual(0, code)
        self.assertEqual("met", printed["status"])
        self.assertEqual([40, 41], printed["queued"])
        self.assertEqual([{"sprint_id": "a" * 16, "state": "on_track",
                           "now_text": "waiting its turn to merge"}], printed["sprints"])

    def test_a_queued_sprint_that_reads_quiet_is_not_met(self):
        code, printed = self.run_check(state=state_of(sprint(state="quiet", ball="nobody")))
        self.assertEqual(1, code)
        self.assertEqual("not_met", printed["status"])
        self.assertEqual(["a" * 16], printed["stuck"])

    def test_a_queue_that_proves_no_wait_is_not_yet(self):
        closed = {"refs/agent-locks/land-wait/main/1794865617-43-1794866800": "43" * 20}
        fresh_closed = {"refs/agent-locks/land-wait/main/1794866757-43-1794866800": "43" * 20}
        quiet = state_of(sprint(state="quiet", ball="nobody"))
        cases = {
            "no waiter": dict(waiters={}),
            "a dead waiter": dict(waiters={
                "refs/agent-locks/land-wait/main/1794865617-41-%d" % (NOW - 391): "41" * 20}),
            "a waiter from the future": dict(waiters={
                "refs/agent-locks/land-wait/main/1794865617-41-%d" % (NOW + 61): "41" * 20}),
            "a fresh waiter": dict(waiters={
                "refs/agent-locks/land-wait/main/%d-41-%d" % (NOW - 840, NOW - 17): "41" * 20},
                state=quiet),
            "a registration of a closed pull request": dict(pulls=(P40,), waiters=closed),
            "a fresh registration of a closed pull request": dict(pulls=(P40,),
                                                                  waiters=fresh_closed),
        }
        for name, kwargs in cases.items():
            with self.subTest(name):
                code, printed = self.run_check(**kwargs)
                self.assertEqual((75, "no_queue"), (code, printed["status"]))

    def test_no_sprint_of_the_queue_is_not_yet(self):
        for name, state in {
                "another issue": state_of(sprint(issue=99)),
                "an ended sprint": state_of(sprint(ended_at="2026-11-16T00:00:00Z"))}.items():
            with self.subTest(name):
                code, printed = self.run_check(state=state)
                self.assertEqual((75, "no_sprint"), (code, printed["status"]))

    def test_a_moving_holder_with_no_waiter_sprint_here_is_not_yet(self):
        holder = sprint(issue=4, now_text="waiting for CI on its pull request")
        code, printed = self.run_check(state=state_of(holder))
        self.assertEqual((75, "no_sprint", [40, 41]), (code, printed["status"], printed["queued"]))
        with self.subTest("a quiet holder beside a waiter's sprint that shows the wait"):
            quiet_holder = sprint("b" * 16, issue=4, state="quiet", ball="nobody")
            code, printed = self.run_check(state=state_of(quiet_holder, sprint()))
            self.assertEqual((1, ["b" * 16]), (code, printed.get("stuck")))

    def test_a_waiter_sprint_moving_for_another_reason_is_not_yet(self):
        code, printed = self.run_check(
            state=state_of(sprint(now_text="building 1 of 2: Importer resumes")))
        self.assertEqual((75, "no_wait_shown"), (code, printed["status"]))

    def test_a_sprint_inside_a_quiet_group_is_found(self):
        code, printed = self.run_check(state=state_of(sprint(), grouped=True))
        self.assertEqual((0, "met"), (code, printed["status"]))

    def test_an_unreadable_forge_or_console_is_not_yet(self):
        def refuse(slug, pattern):
            raise ForgeError("gh_failed", "x")

        def silent(port):
            raise OSError("refused")

        code, printed = self.run_check(read_pulls=refuse)
        self.assertEqual((75, "forge_unreadable"), (code, printed["status"]))
        code, printed = self.run_check(read_state=silent)
        self.assertEqual((75, "no_console"), (code, printed["status"]))

    def test_the_defaults_are_this_checkouts_pattern_and_the_console_port(self):
        parsed = lock_wait_check.build_parser().parse_args(["--project", "p", "--repo", "o/r"])
        self.assertEqual(service.DEFAULT_PORT, parsed.port)
        asked = []

        def read_pulls(slug, pattern):
            asked.append((slug, pattern))
            return (P40, P41)

        with mock.patch.object(deliveries, "configured_branch_pattern", return_value=PATTERN):
            self.run_check(argv=["--project", "p", "--repo", "o/r"], read_pulls=read_pulls)
        self.assertEqual([("o/r", PATTERN)], asked)

    def test_the_wrapper_is_committed_executable(self):
        self.assertEqual("100755", committed_mode(WRAPPER))


if __name__ == "__main__":
    unittest.main()
