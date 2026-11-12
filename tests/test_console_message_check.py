"""The console message verify checks (#889): an approval on the page reaches the manager, and how fast.

Run: just agent-workflow-tests
"""
import contextlib
import io
import json
import socket
import subprocess
import tempfile
import threading
import unittest
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from types import SimpleNamespace

from agent_tools.console import manager, message_check, sprints
from agent_tools.console.message_check import GOAL, StopFailed
from agent_tools.console.sessions import Observation
from tests.test_console_manager_check import Registry, Time

ROOT = Path(__file__).resolve().parents[1]
WRAPPER = "home/common/verify-pending/checks/console-owner-message"
SID = "a" * 16
STATED = "2026-11-12T10:00:00+00:00"
APPROVED_AT = "2026-11-12T10:05:00+00:00"
T0 = datetime.fromisoformat(STATED).timestamp()
LISTED = {"s-1": Observation("s-1", "/srv/p01", 1, "idle", None,
                             manager.session_name("owner/p01", SID), None, "work")}


def later(seconds):
    return (datetime.fromisoformat(APPROVED_AT) + timedelta(seconds=seconds)).isoformat()


def approval(state="delivered", read=None, at=APPROVED_AT):
    return {"id": 2, "kind": "approved", "version": 1, "text": "approved", "at": at,
            "state": state, "state_text": state, "read_at": read, "reply": None,
            "reply_at": None}


def view(*, sprint=True, state="started", text=None, messages=(), reach=None, brief=None,
         managers=True, members=True):
    row = {"sprint_id": SID, "goal": GOAL, "stated_at": STATED, "manager_state": state,
           "manager_text": text}
    if members:
        row.update(messages=list(messages), reach_text=reach)
    items = [] if brief is None else [{"key": "brief/" + SID, "version": brief,
                                       "waiting_since": STATED}]
    return {"managers": managers,
            "entries": [{"type": "project", "project_id": "owner/p01",
                         "sprints": [row] if sprint else []}],
            "inbox": {"open": items, "answered": []}}


def serve(test, views, events, statuses=None):
    """A stub console: `views` are served in turn (the last repeats); every request is appended to
    `events`; `statuses` maps a path to the statuses its POSTs take in turn (default 204; "drop" closes the
    connection unanswered)."""
    remaining, scripted = list(views), {k: list(v) for k, v in (statuses or {}).items()}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = remaining.pop(0) if len(remaining) > 1 else remaining[0]
            events.append(("get", self.path))
            data = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            size = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(size))
            events.append(("post", self.path, body, dict(self.headers)))
            queue = scripted.get(self.path)
            status = queue.pop(0) if queue else 204
            if status == "drop":
                self.close_connection = True
                return
            self.send_response(status)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    test.addCleanup(thread.join, 5)
    test.addCleanup(server.server_close)
    test.addCleanup(server.shutdown)
    return f"http://127.0.0.1:{server.server_address[1]}"


class MessageCheckTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(subprocess.run, ["rm", "-rf", str(self.dir)])
        self.state_file = self.dir / "checks" / "state.json"
        self.result_file = self.dir / "checks" / "result.json"
        self.token_file = self.dir / "token"
        self.token_file.write_text("tok\n")
        self.failing_stops = 0

    def stop(self, session_id, profile):
        self.events.append(("stop", session_id, profile))
        if self.failing_stops:
            self.failing_stops -= 1
            raise StopFailed("the stop failed")

    def run_check(self, views, *, saved=None, url=None, statuses=None, budget="600",
                  registry=None, now=T0, command="start"):
        self.events = []
        if url is None:
            url = serve(self, views, self.events, statuses)
        if saved is not None:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            self.state_file.write_text(json.dumps(saved))
        self.time = Time(now)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = message_check.main(
                [command, "--project", "owner/p01", "--url", url, "--state-file",
                 str(self.state_file), "--result-file", str(self.result_file),
                 "--token-file", str(self.token_file), "--budget", budget],
                registry=registry or Registry(LISTED), stop=self.stop,
                clock=self.time.clock, sleep=self.time.sleep)
        return code, json.loads(out.getvalue())

    def timing(self, deadline=None):
        out = io.StringIO()
        argv = ["timing", "--result-file", str(self.result_file)]
        if deadline:
            argv += ["--deadline", str(deadline)]
        with contextlib.redirect_stdout(out):
            code = message_check.main(argv)
        return code, json.loads(out.getvalue())

    def posts(self, path):
        return [event[2] for event in self.events if event[0] == "post" and event[1] == path]

    def paths(self):
        return [event[1] for event in self.events if event[0] == "post"]

    def stated_views(self, *tail):
        """The views of a fresh run: nothing yet, then the new sprint, then `tail`."""
        return [view(sprint=False), view(), *tail]

    def test_an_approval_read_is_met_and_the_manager_is_stopped_before_the_withdrawal(self):
        code, out = self.run_check(self.stated_views(
            view(brief=1), view(messages=[approval()]),
            view(messages=[approval("read", later(40))])))
        self.assertEqual((code, out), (0, {"read_seconds": 40, "status": "met"}))
        self.assertEqual(self.posts("/api/goal"), [{"project_id": "owner/p01", "goal": GOAL}])
        self.assertEqual(self.posts("/api/approve"),
                         [{"project_id": "owner/p01", "sprint_id": SID, "version": 1}])
        self.assertEqual(self.posts("/api/withdraw"),
                         [{"project_id": "owner/p01", "sprint_id": SID}])
        stop = self.events.index(("stop", "s-1", "work"))
        withdrawn = next(i for i, e in enumerate(self.events) if e[:2] == ("post", "/api/withdraw"))
        self.assertEqual(self.events[stop - 1], ("get", "/api/state"))
        self.assertLess(stop, withdrawn)
        self.assertEqual(json.loads(self.result_file.read_text()),
                         {"read_seconds": 40, "status": "met"})
        self.assertFalse(self.state_file.exists())

    def test_a_replaced_version_answered_409_is_followed_by_approving_the_new_one(self):
        code, out = self.run_check(
            self.stated_views(view(brief=1), view(brief=2),
                              view(messages=[approval("read", later(30))])),
            statuses={"/api/approve": [409, 204]})
        self.assertEqual([post["version"] for post in self.posts("/api/approve")], [1, 2])
        self.assertEqual((code, out["read_seconds"]), (0, 30))

    def test_a_409_whose_approval_shows_in_the_view_is_not_approved_again(self):
        code, out = self.run_check(
            self.stated_views(view(brief=1), view(messages=[approval()]),
                              view(messages=[approval("read", later(25))])),
            statuses={"/api/approve": [409]})
        self.assertEqual(len(self.posts("/api/approve")), 1)
        self.assertEqual((code, out["read_seconds"]), (0, 25))

    def test_an_approval_the_console_never_answered_is_sent_again_not_called_refused(self):
        code, out = self.run_check(
            self.stated_views(view(brief=1), view(brief=1), view(messages=[approval()]),
                              view(messages=[approval("read", later(35))])),
            statuses={"/api/approve": ["drop"]})
        self.assertEqual([post["version"] for post in self.posts("/api/approve")], [1, 1])
        self.assertEqual((code, out["read_seconds"]), (0, 35))

    def test_an_approval_never_answered_is_not_recorded_so_a_resumed_run_sends_it_again(self):
        code, _ = self.run_check(self.stated_views(view(brief=1)), budget="5",
                                 statuses={"/api/approve": ["drop"]})
        self.assertEqual(code, 75)
        self.assertEqual(json.loads(self.state_file.read_text())["approved_versions"], [])
        code, out = self.run_check(
            [view(brief=1), view(messages=[approval("read", later(40))])])
        self.assertEqual((code, out["read_seconds"]), (0, 40))
        self.assertEqual([post["version"] for post in self.posts("/api/approve")], [1])

    def test_a_version_still_waiting_after_its_409_is_not_met(self):
        code, out = self.run_check(self.stated_views(view(brief=1)),
                                   statuses={"/api/approve": [409]})
        self.assertEqual((code, out["status"], out["reason"]),
                         (1, "not_met", "the console refused the approval of version 1"))
        self.assertEqual(len(self.posts("/api/approve")), 1)
        self.assertIn(("stop", "s-1", "work"), self.events)
        self.assertEqual(len(self.posts("/api/withdraw")), 1)

    def test_a_resumed_run_never_approves_a_version_twice(self):
        code, out = self.run_check(self.stated_views(view(brief=1)), budget="5")
        self.assertEqual(code, 75)
        self.assertEqual((out["phase"], out["status"], out["sprint_id"]), ("brief", "waiting", SID))
        self.assertEqual(json.loads(self.state_file.read_text())["approved_versions"], [1])
        code, out = self.run_check(
            [view(messages=[approval()]), view(messages=[approval("read", later(40))])])
        self.assertEqual((code, out["read_seconds"]), (0, 40))
        self.assertEqual(self.posts("/api/goal"), [])
        self.assertEqual(self.posts("/api/approve"), [])

    def test_a_read_after_five_minutes_is_met_here_and_slow_in_timing(self):
        code, out = self.run_check(self.stated_views(
            view(messages=[approval("read", later(400))])))
        self.assertEqual((code, out), (0, {"read_seconds": 400, "status": "met"}))
        self.assertEqual(self.timing(), (1, {"read_seconds": 400, "reason": "slow",
                                             "status": "not_met"}))
        self.result_file.write_text(json.dumps({"read_seconds": 40, "status": "met"}))
        before = self.result_file.read_text()
        self.assertEqual(self.timing(), (0, {"read_seconds": 40, "status": "met"}))
        self.assertEqual(self.result_file.read_text(), before)

    def test_an_unreachable_manager_is_not_met(self):
        code, out = self.run_check(self.stated_views(
            view(messages=[approval()], reach="manager not reachable")))
        self.assertEqual((code, out), (1, {"read_seconds": None, "reason": "manager not reachable",
                                           "status": "not_met"}))
        self.assertIn(("stop", "s-1", "work"), self.events)
        self.assertEqual(len(self.posts("/api/withdraw")), 1)
        self.assertEqual(self.timing()[0], 1)

    def test_an_approval_unread_past_900_seconds_is_still_waiting(self):
        saved = {"project": "owner/p01", "sprint_id": SID, "stated_at": STATED,
                 "approved_versions": [1]}
        old = (datetime.fromisoformat(STATED) - timedelta(seconds=1000)).isoformat()
        code, out = self.run_check([view(messages=[approval(at=old)])], saved=saved, budget="30")
        self.assertEqual((code, out), (75, {"phase": "read", "sprint_id": SID,
                                            "status": "waiting"}))
        self.assertEqual([e for e in self.events if e[0] == "stop"], [])
        self.assertEqual(self.paths(), [])
        self.assertTrue(self.state_file.exists())
        self.assertFalse(self.result_file.exists())

    def test_a_gone_sprint_and_a_failed_manager_are_not_met(self):
        cases = [("gone after the goal", [view(sprint=False), view(sprint=False)],
                  "the sprint is gone"),
                 ("gone while waiting", self.stated_views(view(sprint=False)),
                  "the sprint is gone"),
                 ("failed", self.stated_views(view(state="failed", text="the launch failed")),
                  "the launch failed")]
        for name, views, reason in cases:
            with self.subTest(name):
                code, out = self.run_check(views)
                self.assertEqual((code, out["status"], out["reason"]), (1, "not_met", reason))
                self.assertFalse(self.state_file.exists())

    def test_a_failed_stop_keeps_the_outcome_and_the_next_run_stops_then_withdraws(self):
        self.failing_stops = 1
        code, out = self.run_check(self.stated_views(
            view(messages=[approval("read", later(40))])))
        self.assertEqual((code, out), (75, {
            "reason": "the test manager is not stopped yet", "sprint_id": SID,
            "status": "waiting"}))
        self.assertEqual(self.posts("/api/withdraw"), [])
        self.assertTrue(self.state_file.exists())
        code, out = self.run_check([view(messages=[approval("read", later(40))])])
        self.assertEqual((code, out), (0, {"read_seconds": 40, "status": "met"}))
        self.assertIn(("stop", "s-1", "work"), self.events)
        self.assertEqual(len(self.posts("/api/withdraw")), 1)
        self.assertEqual(self.posts("/api/goal"), [])
        self.assertFalse(self.state_file.exists())

    def test_a_manager_not_listed_is_not_stopped(self):
        code, out = self.run_check(
            self.stated_views(view(messages=[approval("read", later(40))])),
            registry=Registry({}))
        self.assertEqual((code, out["read_seconds"]), (0, 40))
        self.assertEqual([e for e in self.events if e[0] == "stop"], [])
        self.assertEqual(len(self.posts("/api/withdraw")), 1)

    def test_timing_without_a_result_is_not_yet(self):
        self.assertEqual(self.timing(), (75, {"status": "no_result"}))

    def test_an_undeployed_or_unavailable_console_posts_nothing(self):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            closed = f"http://127.0.0.1:{probe.getsockname()[1]}"
        cases = [(closed, None, 75, "not_running"), (None, {}, 75, "not_deployed"),
                 (None, view(managers=False), 1, "managers_unavailable")]
        for url, body, code, status in cases:
            with self.subTest(status=status):
                got = self.run_check([body], url=url)
                self.assertEqual(got, (code, {"status": status}))
                self.assertFalse(self.state_file.exists())
                if url is None:
                    self.assertEqual(self.paths(), [])
                    self.assertEqual([e for e in self.events if e[0] == "stop"], [])

    def test_the_goal_tells_the_manager_to_cut_no_issues(self):
        self.assertTrue(GOAL.startswith("[verify #889]"))
        self.assertIn("cut no issues and deliver nothing", GOAL)
        self.assertIn("withdraw me", GOAL)
        self.assertEqual(sprints.checked_goal(GOAL), GOAL)

    def test_the_default_stop_runs_claude_stop_under_the_managers_profile(self):
        calls = []

        def run(argv, **kwargs):
            calls.append((argv, kwargs))
            return SimpleNamespace(returncode=0)

        environ = {"HOME": "/home/u", "PATH": "/bin", "CONSOLE_SPRINT_SECRET": "s"}
        message_check.default_stop("s-1", "work", run=run, environ=environ)
        argv, kwargs = calls[0]
        self.assertEqual(argv, ["claude-account", "run", "stop", "s-1"])
        self.assertEqual(kwargs["env"]["CLAUDE_ACCOUNT"], "work")
        self.assertNotIn("CONSOLE_SPRINT_SECRET", kwargs["env"])
        self.assertIs(kwargs["stdin"], subprocess.DEVNULL)
        self.assertEqual(kwargs["timeout"], 60)

        def failing(argv, **kwargs):
            kwargs["stderr"].write(b"x\n")
            return SimpleNamespace(returncode=1)

        def missing(argv, **kwargs):
            raise FileNotFoundError

        for stand_in, reason in ((failing, "x"),
                                 (missing, "claude-account is not installed")):
            with self.subTest(reason):
                with self.assertRaises(StopFailed) as raised:
                    message_check.default_stop("s-1", "work", run=stand_in, environ=environ)
                self.assertEqual(str(raised.exception), reason)

    def test_the_wrapper_is_executable_in_the_index(self):
        listed = subprocess.run(["git", "ls-files", "-s", WRAPPER], cwd=ROOT,
                                capture_output=True, text=True, check=True).stdout
        self.assertTrue(listed.startswith("100755"), listed)

    def test_an_off_loopback_url_is_refused(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            message_check.main(["start", "--project", "x", "--url", "http://example.com"])
        self.assertEqual(raised.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
