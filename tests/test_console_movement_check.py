"""The verify script that a sprint whose sessions write output reads moving (#1185).

Run: just agent-workflow-tests
"""
import contextlib
import io
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from agent_tools.console import movement_check
from tests.test_verify_checks import committed_mode
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)

ROOT = Path(__file__).resolve().parents[1]
WRAPPER = "home/common/verify-pending/checks/console-sprint-output"
NOW = 1_800_000_000
MIN = 60


def iso(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat()


def sprint(sid, *, state="on_track", ball="manager", status_age=40 * MIN, base_age=40 * MIN,
           now_text="building 1 of 7: Importer resumes", sessions=(), issues=(4,), assoc=(),
           nudged_at=None, ended_at=None):
    return {
        "type": "sprint", "sprint_id": sid, "state": state, "ball": ball, "now_text": now_text,
        "status_at": iso(NOW - status_age), "ended_at": ended_at,
        "issues": [{"issue": n, "stage": "building", "stage_text": "building"} for n in issues],
        "sessions": list(sessions),
        "movement": {
            "sessions": [{"session_id": s, "manager": m,
                          "read_at": None if r is None else iso(r)} for s, m, r in assoc],
            "nudged_at": None if nudged_at is None else iso(nudged_at),
            "base_at": iso(NOW - base_age)},
    }


def project(*sprints, outside=()):
    return {"type": "project", "project_id": "owner/p00", "sprints": list(sprints),
            "outside_sprints": {"sessions": list(outside)}}


def view(*projects):
    return {"entries": list(projects)}


def session(sid, state="idle", deliveries=()):
    return {"session_id": sid, "state": state, "deliveries": list(deliveries)}


def delivery(issue, moved_age):
    return {"run_id": "r", "moved_at": iso(NOW - moved_age),
            "issues": [{"issue": issue, "stage": "building", "stage_text": "building"}]}


class MovementCheckTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.projects = Path(tmp.name)

    def write(self, relative, age):
        path = self.projects / "slug" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n")
        os.utime(path, (NOW - age, NOW - age))

    def check(self, document, argv=()):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = movement_check.main(
                list(argv), state=lambda: document, clock=lambda: NOW,
                projects=lambda: [self.projects])
        return code, json.loads(out.getvalue())

    def moving(self, **kw):
        """Test 1's arrangement: one sprint that reads moving on old signals, fresh output."""
        self.write("s1.jsonl", 5 * MIN)
        kw.setdefault("sessions", [session("s1")])
        kw.setdefault("assoc", [("s1", True, NOW - MIN)])
        return sprint("a", **kw)

    def test_a_fresh_sprint_that_reads_moving_with_old_base_signals_is_met(self):
        code, out = self.check(view(project(self.moving())))
        self.assertEqual((0, "met"), (code, out["status"]))
        self.assertEqual([{"project_id": "owner/p00", "sprint_id": "a", "session_id": "s1",
                           "output_age_s": 300}], out["moving"])

    def test_a_fresh_seen_sprint_that_reads_may_be_stuck_is_not_met(self):
        code, out = self.check(view(project(self.moving(state="quiet", ball="nobody"))))
        self.assertEqual((1, "not_met"), (code, out["status"]))
        self.assertEqual(("a", "s1"), (out["stuck"][0]["sprint_id"], out["stuck"][0]["session_id"]))

    def test_output_the_console_has_not_read_yet_is_not_judged(self):
        read_at = NOW - 2 * MIN
        self.write("s1.jsonl", NOW - (read_at + 1))
        late = sprint("a", state="quiet", ball="nobody", assoc=[("s1", True, read_at)])
        self.assertEqual(75, self.check(view(project(late)))[0])
        self.write("s1.jsonl", NOW - (read_at - 1))
        self.assertEqual(1, self.check(view(project(late)))[0])
        unread = sprint("a", state="quiet", ball="nobody", assoc=[("s1", True, None)])
        self.assertEqual(75, self.check(view(project(unread)))[0])

    def test_output_older_than_twelve_minutes_is_not_fresh(self):
        quiet = sprint("a", state="quiet", ball="nobody", assoc=[("s1", True, NOW)])
        self.write("s1.jsonl", 13 * MIN)
        self.assertEqual(75, self.check(view(project(quiet)))[0])
        self.write("s1.jsonl", 11 * MIN)
        self.assertEqual(1, self.check(view(project(quiet)))[0])

    def test_a_managers_reply_to_a_nudge_is_not_counted(self):
        self.write("s1.jsonl", 5 * MIN)

        def quiet(manager):
            return sprint("a", state="quiet", ball="nobody", nudged_at=NOW - 6 * MIN,
                          assoc=[("s1", manager, NOW - MIN)])
        self.assertEqual(75, self.check(view(project(quiet(True))))[0])
        self.assertEqual(1, self.check(view(project(quiet(False))))[0])

    def test_met_needs_every_older_signal_to_be_old(self):
        cases = {
            "base": dict(base_age=5 * MIN),
            "status": dict(status_age=5 * MIN),
            "wait": dict(now_text="waiting for CI on its pull request"),
            "working": dict(sessions=[session("s1", "working")]),
            "inbox delivery": dict(sessions=[session("s1")]),
            "own delivery": dict(sessions=[session("s1", deliveries=[delivery(4, 5 * MIN)])]),
        }
        for name, kw in cases.items():
            with self.subTest(name):
                outside = [session("d1", deliveries=[delivery(4, 5 * MIN)])] \
                    if name == "inbox delivery" else []
                code, out = self.check(view(project(self.moving(**kw), outside=outside)))
                self.assertEqual((75, "waiting"), (code, out["status"]))

    def test_a_stuck_sprint_known_only_through_its_associations_is_found(self):
        for session_id, manager, relative in (
                ("m2", True, "m2.jsonl"), ("d2", False, "d2/subagents/workflows/wf/agent-a.jsonl")):
            with self.subTest(session_id):
                self.write(relative, 2 * MIN if manager is False else 5 * MIN)
                other = sprint("b", state="quiet", ball="nobody", issues=(9,),
                               assoc=[(session_id, manager, NOW - MIN)])
                code, out = self.check(view(project(self.moving(), other)))
                self.assertEqual(1, code)
                self.assertEqual(["b"], [s["sprint_id"] for s in out["stuck"]])

    def test_finished_and_quiet_group_sprints(self):
        self.write("s1.jsonl", 5 * MIN)
        done = sprint("a", state="quiet", ball="nobody", assoc=[("s1", True, NOW - MIN)],
                      ended_at=iso(NOW - MIN))
        self.assertEqual(75, self.check(view(project(done)))[0])
        stuck = sprint("a", state="quiet", ball="nobody", assoc=[("s1", True, NOW - MIN)])
        group = {"type": "quiet_group", "label": "9 quiet projects", "count": 9,
                 "projects": [project(stuck)]}
        self.assertEqual(1, self.check(view(group))[0])

    def test_no_console_answer_is_not_yet(self):
        code, out = self.check(None)
        self.assertEqual((75, {"status": "no_console"}), (code, out))

    def test_a_url_that_is_not_loopback_http_is_a_usage_error(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            movement_check.main(["--url", "http://example.com:1"], state=lambda: None)
        self.assertEqual(2, raised.exception.code)

    def test_the_wrapper_is_committed_executable_and_runs_the_module(self):
        text = (ROOT / WRAPPER).read_text()
        self.assertTrue(text.startswith("#!/bin/sh"))
        self.assertIn("-m agent_tools.console.movement_check", text)
        self.assertEqual("100755", committed_mode(WRAPPER))


if __name__ == "__main__":
    unittest.main()
