"""The verify check that a declared live fault's first delivery reaches a green pull request within the hour (#1433, AC5).

Run: just agent-workflow-tests
"""
import contextlib
import io
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from agent_tools.console import event_log, live_fault_check
from agent_tools.system.forge_api import ForgeError
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)
from tests.test_verify_checks import committed_mode

ROOT = Path(__file__).resolve().parents[1]
WRAPPER = "home/common/verify-pending/checks/live-fault-first-use"
REPO = "octo/widgets"
SPRINT = "aaaaaaaaaaaaaaaa"
AT_A = "2026-11-21T12:10:00.000000+00:00"
AT_B = "2026-11-21T12:20:00.000000+00:00"
DECLARED_A = datetime(2026, 11, 21, 12, 10, tzinfo=timezone.utc)


def declare(log, at, issue):
    log._clock = lambda: at
    (event,) = log.append([(event_log.FAULT_DECLARED, None, {
        "sprint_id": SPRINT, "goal": "g",
        "fault": {"issue": issue, "observed": "o", "when": "w", "proven": "p"}})])
    return event.seq


def marker(seq, issue, at, sprint=SPRINT):
    return f"Live-fault lane: declaration {seq} of sprint {sprint} for issue #{issue}, declared {at}"


def pull(number, *lines):
    return {"number": number, "body": "## Summary\n\n" + "\n".join(lines) + "\n"}


def green(at):
    return lambda repo, number: ("green", {"pr": number, "green_at": at})


class LiveFaultCheckTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.store = Path(self.dir.name) / "events.sqlite3"
        log = event_log.EventLog(self.store)
        self.a = declare(log, AT_A, 12)
        self.b = declare(log, AT_B, 13)
        log.close()
        self.marker_a = marker(self.a, 12, AT_A)
        self.marker_b = marker(self.b, 13, AT_B)

    def check(self, pulls, state=None, now=DECLARED_A + timedelta(hours=5), argv=None, store=None):
        state = state or green("2026-11-21T12:52:30Z")
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(live_fault_check, "_pulls", return_value=pulls) as listed, \
                mock.patch.object(live_fault_check, "pr_green_state", side_effect=state) as read, \
                mock.patch.object(live_fault_check, "_now", return_value=now), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = live_fault_check.main(
                argv if argv is not None else ["--repo", REPO, "--store", str(store or self.store)])
        self.listed, self.read, self.err = listed, read, err.getvalue()
        text = out.getvalue().strip()
        return code, (json.loads(text) if text else None)

    def test_no_live_lane_pull_request_yet_is_not_yet(self):
        code, out = self.check([pull(40, "nothing")])
        self.assertEqual((code, out), (75, {"verdict": "not_yet"}))

    def test_a_first_use_within_the_hour_is_met(self):
        code, out = self.check([pull(40, self.marker_a)])
        self.assertEqual(code, 0)
        self.assertEqual(out["seconds"], 2550)
        self.assertEqual((out["pr"], out["declaration"], out["issue"], out["sprint_id"], out["state"]),
                         (40, self.a, 12, SPRINT, "green"))
        self.assertEqual((out["declared_at"], out["green_at"]), (AT_A, "2026-11-21T12:52:30Z"))
        self.assertEqual(set(out), {"declaration", "sprint_id", "issue", "pr", "state",
                                    "declared_at", "green_at", "seconds"})

    def test_exactly_one_hour_is_met_and_one_second_more_is_not(self):
        self.assertEqual(self.check([pull(40, self.marker_a)], green("2026-11-21T13:10:00Z"))[0], 0)
        self.assertEqual(self.check([pull(40, self.marker_a)], green("2026-11-21T13:10:01Z"))[0], 1)

    def test_a_green_time_before_the_declaration_is_not_met(self):
        self.assertEqual(self.check([pull(40, self.marker_a)], green("2026-11-21T12:00:00Z"))[0], 1)

    def test_a_first_use_not_green_yet_is_pending_within_the_hour(self):
        soon = DECLARED_A + timedelta(minutes=30)
        for state in ("pending", "failed"):
            with self.subTest(state=state):
                code, out = self.check([pull(40, self.marker_a)],
                                       lambda r, n, s=state: (s, {"pr": n, "green_at": None}), now=soon)
                self.assertEqual((code, out["pr"], out["state"]), (75, 40, state))
        late = DECLARED_A + timedelta(minutes=61)
        code, out = self.check([pull(40, self.marker_a)],
                               lambda r, n: ("pending", {"pr": n, "green_at": None}), now=late)
        self.assertEqual((code, out["pr"]), (1, 40))

    def test_the_first_declaration_with_a_pull_request_decides(self):
        code, out = self.check([pull(41, self.marker_b)])
        self.assertEqual((code, out["declaration"], out["pr"]), (0, self.b, 41))
        code, out = self.check([pull(40, self.marker_a), pull(41, self.marker_b)],
                               lambda r, n: ("green", {"green_at": "2026-11-21T14:00:00Z" if n == 40
                                                       else "2026-11-21T12:25:00Z"}))
        self.assertEqual((code, out["declaration"], out["pr"]), (1, self.a, 40))

    def test_the_lowest_numbered_pull_request_of_the_declaration_decides(self):
        code, out = self.check([pull(45, self.marker_a), pull(40, "x", f"  {self.marker_a}  ")])
        self.assertEqual((code, out["pr"]), (0, 40))

    def test_an_earlier_open_pull_request_beside_a_later_merged_one(self):
        states = {40: ("pending", {"green_at": None}), 41: ("green", {"green_at": "2026-11-21T12:25:00Z"})}
        code, out = self.check([pull(40, self.marker_a), pull(41, self.marker_b)],
                               lambda r, n: states[n], now=DECLARED_A + timedelta(minutes=30))
        self.assertEqual((code, out["pr"], out["state"]), (75, 40, "pending"))

    def test_a_marker_of_another_store_or_issue_does_not_count(self):
        bodies = [marker(self.a, 12, AT_A, sprint="bbbbbbbbbbbbbbbb"),
                  marker(self.a, 99, AT_A),
                  marker(self.a, 12, "2026-11-21T12:10:00.000001+00:00"),
                  f"Live-fault lane: declaration {self.a}",
                  self.marker_a + " and more",
                  "see " + self.marker_a]
        code, out = self.check([pull(40 + n, body) for n, body in enumerate(bodies)])
        self.assertEqual((code, out), (75, {"verdict": "not_yet"}))
        self.read.assert_not_called()

    def test_a_pull_request_without_a_body_is_skipped(self):
        code, out = self.check([{"number": 3, "body": None}, pull(40, self.marker_a)])
        self.assertEqual((code, out["pr"]), (0, 40))

    def test_a_bad_repo_is_a_usage_error(self):
        code, out = self.check([pull(40, self.marker_a)], argv=["--repo", "nope", "--store", str(self.store)])
        self.assertEqual(code, 2)
        self.assertTrue(self.err.strip())
        self.listed.assert_not_called()
        self.read.assert_not_called()

    def test_an_unknown_argument_is_a_usage_error(self):
        self.assertEqual(self.check([], argv=["--repo", REPO, "--bogus"])[0], 2)

    def test_an_absent_store_is_not_yet(self):
        code, out = self.check([pull(40, self.marker_a)], store=Path(self.dir.name) / "missing.sqlite3")
        self.assertEqual((code, out), (75, {"verdict": "not_yet"}))
        self.assertFalse((Path(self.dir.name) / "missing.sqlite3").exists())

    def test_the_store_is_never_written(self):
        before = self.store.read_bytes()
        self.check([pull(40, self.marker_a)])
        self.assertEqual(self.store.read_bytes(), before)
        self.assertEqual(sorted(os.listdir(self.dir.name)), ["events.sqlite3"])

    def test_a_forge_error_is_a_usage_class_error(self):
        def broken(repo, number):
            raise ForgeError("gh_failed", "boom")
        code, _ = self.check([pull(40, self.marker_a)], broken)
        self.assertEqual(code, 2)
        self.assertEqual(len(self.err.strip().splitlines()), 1)
        with mock.patch.object(live_fault_check, "_pulls", side_effect=ForgeError("gh_failed", "boom")), \
                contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(live_fault_check.main(["--repo", REPO, "--store", str(self.store)]), 2)

    def test_the_wrapper_is_committed_executable(self):
        path = ROOT / WRAPPER
        self.assertTrue(os.access(path, os.X_OK))
        self.assertEqual(committed_mode(WRAPPER), "100755")
        last = path.read_text().rstrip("\n").splitlines()[-1]
        self.assertEqual(last, 'PYTHONPATH=python exec python3 -m agent_tools.console.live_fault_check "$@"')


if __name__ == "__main__":
    unittest.main()
