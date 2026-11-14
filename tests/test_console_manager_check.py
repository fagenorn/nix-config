"""The console manager verify checks (#888): a stated goal starts a manager that briefs and survives a restart.

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
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from agent_tools.console import manager, manager_check
from agent_tools.console.manager import StopFailed
from agent_tools.console.manager_check import GOALS
from agent_tools.console.sessions import Observation
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)

ROOT = Path(__file__).resolve().parents[1]
WRAPPER = "home/common/verify-pending/checks/console-manager-start"
A, B = "a" * 16, "b" * 16
STATED = "2026-11-12T10:00:00+00:00"
T0 = datetime.fromisoformat(STATED).timestamp()
NAMES = {A: "owner/p01 sprint " + A, B: "owner/p01 sprint " + B}


def view(sprints, inbox=(), managers=True):
    return {"managers": managers,
            "entries": [{"type": "project", "project_id": "owner/p01", "sprints": sprints}],
            "inbox": {"open": list(inbox), "answered": []}}


def sprint(sid, goal, **over):
    return {"sprint_id": sid, "goal": goal, "stated_at": STATED, "manager_state": "started",
            "manager_text": None, "sessions": [], **over}


def brief(sid, at, version=1):
    return {"key": "brief/" + sid, "version": version, "waiting_since": "2026-11-12T" + at + "+00:00"}


def obs(sid):
    return Observation(session_id=sid, cwd="/srv/p01", pid=1, status="idle", waiting_for=None,
                       name=NAMES[sid], updated_ms=0, profile="default")


def both(**over):
    return [sprint(A, GOALS[0], **over), sprint(B, GOALS[1], **over)]


def serve(test, views, withdraws=()):
    """A stub console: `views` are served in turn (the last repeats, None is a 503); POSTs are
    recorded and each withdraw takes the next of `withdraws` as its status (else 204)."""
    posts, remaining, statuses = [], list(views), list(withdraws)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = remaining.pop(0) if len(remaining) > 1 else remaining[0]
            if body is None:
                self.send_response(503)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            data = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            size = int(self.headers.get("Content-Length", "0"))
            posts.append((self.path, dict(self.headers), json.loads(self.rfile.read(size))))
            status = statuses.pop(0) if posts[-1][0] == "/api/withdraw" and statuses else 204
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
    return f"http://127.0.0.1:{server.server_address[1]}", posts


class Time:
    def __init__(self, now):
        self.now = now

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class Registry:
    def __init__(self, *maps):
        self.maps, self.calls = list(maps), 0

    def __call__(self):
        self.calls += 1
        return self.maps[min(self.calls, len(self.maps)) - 1]


class ManagerCheckTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(subprocess.run, ["rm", "-rf", str(self.dir)])
        self.state_file = self.dir / "checks" / "state.json"
        self.result_file = self.dir / "checks" / "result.json"
        self.token_file = self.dir / "token"
        self.token_file.write_text("tok\n")
        self.restarts = []
        self.stops = []
        self.failing_stops = 0
        self.calls = []
        self.failing_removes = set()
        self.stop_seconds = 0

    def stop(self, session_id, profile):
        self.stops.append((session_id, profile, len(self.posted("/api/withdraw"))))
        self.calls.append(("stop", session_id, profile, len(self.posted("/api/withdraw"))))
        self.time.now += self.stop_seconds
        if self.failing_stops:
            self.failing_stops -= 1
            raise StopFailed(f"No job matching {session_id}")

    def remove(self, session_id, profile):
        self.calls.append(("remove", session_id, profile, len(self.posted("/api/withdraw"))))
        if session_id in self.failing_removes:
            self.failing_removes.discard(session_id)
            raise manager.RemoveFailed(f"cannot remove {session_id}")

    def start(self, views, *, resume=False, at=T0, registry=None, budget="30", url=None,
              withdraws=()):
        if url is None:
            url, self.posts = serve(self, views, withdraws)
        if resume:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            self.state_file.write_text(json.dumps({"project": "owner/p01", "sprints": [
                {"sprint_id": A, "stated_at": STATED}, {"sprint_id": B, "stated_at": STATED}]}))
        self.url, self.time = url, Time(at)
        self.registry = registry or Registry({})
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = manager_check.main(
                ["start", "--project", "owner/p01", "--url", url, "--state-file",
                 str(self.state_file), "--result-file", str(self.result_file),
                 "--token-file", str(self.token_file), "--budget", budget],
                restart=lambda: self.restarts.append(1), registry=self.registry, stop=self.stop,
                remove=self.remove,
                clock=self.time.clock, sleep=self.time.sleep)
        return code, json.loads(out.getvalue())

    def posted(self, path):
        return [post for post in self.posts if post[0] == path]

    def result(self):
        return json.loads(self.result_file.read_text())["brief_seconds"]

    def test_a_console_that_is_down_or_old_is_not_yet(self):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            closed = f"http://127.0.0.1:{probe.getsockname()[1]}"
        cases = [(closed, 75, "not_running", None), (None, 75, "not_deployed", {}),
                 (None, 1, "managers_unavailable", view([], managers=False))]
        for url, code, status, body in cases:
            with self.subTest(status=status):
                got = self.start([body], url=url)
                self.assertEqual(got, (code, {"status": status}))
                self.assertFalse(self.state_file.exists())
                if url is None:
                    self.assertEqual(self.posts, [])

    def test_the_first_run_states_two_marked_goals(self):
        code, out = self.start([view([]), view(both())])
        port = self.url.rsplit(":", 1)[1]
        goals = self.posted("/api/goal")
        self.assertEqual([post[2] for post in goals],
                         [{"project_id": "owner/p01", "goal": goal} for goal in GOALS])
        for _, headers, _ in goals:
            self.assertEqual(headers["Origin"], f"http://127.0.0.1:{port}")
            self.assertEqual(headers["X-Console-Token"], "tok")
        saved = json.loads(self.state_file.read_text())
        self.assertEqual(saved["sprints"], [{"sprint_id": A, "stated_at": STATED},
                                            {"sprint_id": B, "stated_at": STATED}])
        self.assertEqual((code, out["status"]), (75, "waiting"))

    def test_a_later_run_resumes_the_same_sprints(self):
        code, out = self.start([view(both())], resume=True)
        self.assertEqual(self.posted("/api/goal"), [])
        self.assertEqual((code, out["status"]), (75, "waiting"))

    def test_waiting_ends_at_the_budget_or_a_failure(self):
        waiting = self.start([view(both())], resume=True)
        self.assertEqual(waiting[0], 75)
        self.assertEqual(self.posted("/api/withdraw"), [])
        self.assertTrue(self.state_file.exists())
        self.assertFalse(self.result_file.exists())
        for state, text in (("missing", "the manager is not running"),
                            ("failed", "could not start a manager: x")):
            with self.subTest(state=state):
                failing = [sprint(A, GOALS[0], manager_state=state, manager_text=text),
                           sprint(B, GOALS[1])]
                code, out = self.start([view(failing)], resume=True)
                self.assertEqual((code, out["reason"]), (1, text))
                self.assertEqual(len(self.posted("/api/withdraw")), 2)

    def test_a_slow_or_parked_brief_is_not_yet_however_late(self):
        parked = [sprint(A, GOALS[0], manager_state="waiting",
                         manager_until="2026-11-12T12:00:00+00:00"), sprint(B, GOALS[1])]
        code, out = self.start([view(parked)], resume=True, at=T0 + 35 * 60)
        self.assertEqual(code, 75)
        shown = {row["sprint_id"]: row for row in out["sprints"]}
        self.assertEqual((shown[A]["manager_state"], shown[A]["manager_until"]),
                         ("waiting", "2026-11-12T12:00:00+00:00"))
        self.assertEqual(self.posted("/api/withdraw"), [])
        self.assertTrue(self.state_file.exists())
        self.assertFalse(self.result_file.exists())
        self.assertEqual(self.start([view(both())], resume=True, at=T0 + 7200)[0], 75)
        self.assertEqual(self.posted("/api/withdraw"), [])
        late = view(both(), [brief(A, "10:31:00"), brief(B, "10:02:00")])
        code, out = self.start([late], resume=True, at=T0 + 7200,
                               registry=Registry({1: obs(A), 2: obs(B)}))
        self.assertEqual((code, out["status"]), (0, "met"))
        self.assertEqual(self.result(), {A: 1860, B: 120})

    def test_two_briefs_then_a_restart_with_both_managers_running_is_met(self):
        briefs = view(both(), [brief(A, "10:02:00"), brief(B, "10:03:00")])
        code, out = self.start([briefs], resume=True, registry=Registry({1: obs(A), 2: obs(B)}))
        self.assertEqual(code, 0)
        self.assertEqual(out, {"brief_seconds": [120, 180],
                               "sessions": [NAMES[A], NAMES[B]], "status": "met"})
        self.assertEqual(len(self.restarts), 1)
        self.assertEqual(len(self.posted("/api/withdraw")), 2)
        self.assertFalse(self.state_file.exists())
        self.assertEqual(self.result(), {A: 120, B: 180})
        self.assertEqual(self.stops, [(A, "default", 0), (B, "default", 0)])

    def test_a_failed_stop_keeps_the_sprints_open_until_every_manager_is_stopped(self):
        briefs = view(both(), [brief(A, "10:02:00"), brief(B, "10:03:00")])
        registry = Registry({1: obs(A), 2: obs(B)})
        self.failing_stops = 1
        code, out = self.start([briefs], resume=True, registry=registry)
        self.assertEqual((code, out), (75, {
            "reason": "the test managers are not stopped yet: No job matching " + A,
            "sprints": [{"sprint_id": A}, {"sprint_id": B}], "status": "waiting"}))
        self.assertEqual([stop[:2] for stop in self.stops], [(A, "default"), (B, "default")])
        self.assertEqual(self.posted("/api/withdraw"), [])
        self.assertTrue(self.state_file.exists())
        self.assertFalse(self.result_file.exists())
        self.stops.clear()
        code, out = self.start([briefs], url=self.url, registry=registry)
        self.assertEqual((code, out["status"], out["sessions"]),
                         (0, "met", [NAMES[A], NAMES[B]]))
        self.assertEqual(self.stops, [(A, "default", 0), (B, "default", 0)])
        self.assertEqual(len(self.posted("/api/withdraw")), 2)
        self.assertEqual(len(self.restarts), 1)
        self.assertFalse(self.state_file.exists())
        self.assertEqual(self.result(), {A: 120, B: 180})

    def test_the_finish_stops_both_then_removes_both_before_it_withdraws(self):
        briefs = view(both(), [brief(A, "10:02:00"), brief(B, "10:03:00")])
        code, out = self.start([briefs], resume=True, registry=Registry({1: obs(A), 2: obs(B)}))
        self.assertEqual(code, 0)
        self.assertEqual(self.calls, [("stop", A, "default", 0), ("stop", B, "default", 0),
                                      ("remove", A, "default", 0), ("remove", B, "default", 0)])
        self.assertEqual(len(self.posted("/api/withdraw")), 2)
        self.assertEqual(json.loads(self.result_file.read_text())["cleared"], {
            "project": "owner/p01", "names": [NAMES[A], NAMES[B]], "profiles": ["default"]})

    def test_a_not_met_finish_removes_the_stopped_manager_before_it_withdraws(self):
        code, _ = self.start([view(both(manager_state="failed", manager_text="x"))],
                             resume=True, registry=Registry({1: obs(A)}))
        self.assertEqual(code, 1)
        self.assertEqual(self.calls, [("stop", A, "default", 0), ("remove", A, "default", 0)])
        self.assertEqual(len(self.posted("/api/withdraw")), 2)

    def test_a_failed_removal_keeps_the_outcome_and_the_next_run_removes_only_what_is_left(self):
        briefs = view(both(), [brief(A, "10:02:00"), brief(B, "10:03:00")])
        self.failing_removes = {A}
        code, out = self.start([briefs], resume=True, registry=Registry({1: obs(A), 2: obs(B)}))
        self.assertEqual((code, out), (75, {
            "reason": "the test managers' sessions are not removed yet: cannot remove " + A,
            "sprints": [{"sprint_id": A}, {"sprint_id": B}], "status": "waiting"}))
        self.assertEqual(self.posted("/api/withdraw"), [])
        self.assertFalse(self.result_file.exists())
        saved = json.loads(self.state_file.read_text())
        self.assertEqual(saved["stopped"], [
            {"session_id": A, "profile": "default"},
            {"session_id": B, "profile": "default", "removed": True}])
        self.assertEqual(saved["outcome"]["code"], 0)
        self.calls.clear()
        code, out = self.start([briefs], url=self.url, registry=Registry({}))
        self.assertEqual((code, out["status"]), (0, "met"))
        self.assertEqual(self.calls, [("remove", A, "default", 0)])
        self.assertEqual(len(self.posted("/api/withdraw")), 2)
        self.assertEqual(len(self.restarts), 1)
        self.assertFalse(self.state_file.exists())
        self.assertEqual(self.result(), {A: 120, B: 180})

    def test_a_finish_cut_short_after_one_stop_keeps_it_and_the_next_run_completes_the_cleanup(self):
        briefs = view(both(), [brief(A, "10:02:00"), brief(B, "10:03:00")])
        self.stop_seconds = 600
        code, out = self.start([briefs], resume=True, registry=Registry({1: obs(A), 2: obs(B)}))
        self.assertEqual((code, out), (75, {
            "reason": "the test managers are not stopped yet: " + manager.OUT_OF_TIME_TEXT,
            "sprints": [{"sprint_id": A}, {"sprint_id": B}], "status": "waiting"}))
        self.assertEqual(self.calls, [("stop", A, "default", 0)])
        self.assertEqual(self.posted("/api/withdraw"), [])
        self.assertFalse(self.result_file.exists())
        saved = json.loads(self.state_file.read_text())
        self.assertEqual(saved["stopped"], [{"session_id": A, "profile": "default"}])
        self.assertEqual(saved["outcome"]["code"], 0)
        self.calls.clear()
        self.stop_seconds = 0
        code, out = self.start([briefs], url=self.url, registry=Registry({1: obs(B)}))
        self.assertEqual((code, out["status"]), (0, "met"))
        self.assertEqual(self.calls, [("stop", B, "default", 0), ("remove", A, "default", 0),
                                      ("remove", B, "default", 0)])
        self.assertEqual(len(self.posted("/api/withdraw")), 2)
        self.assertEqual(len(self.restarts), 1)
        self.assertFalse(self.state_file.exists())

    def test_a_not_met_finish_stops_the_listed_managers_before_it_withdraws(self):
        code, out = self.start([view(both(manager_state="failed", manager_text="x"))],
                               resume=True, registry=Registry({1: obs(A)}))
        self.assertEqual((code, out["reason"]), (1, "x"))
        self.assertEqual(self.stops, [(A, "default", 0)])
        self.assertEqual(len(self.posted("/api/withdraw")), 2)

    def test_a_manager_shown_by_the_console_but_not_running_is_not_met(self):
        shown = [sprint(A, GOALS[0], sessions=[{}]), sprint(B, GOALS[1], sessions=[{}])]
        briefs = view(shown, [brief(A, "10:02:00"), brief(B, "10:03:00")])
        registry = Registry({1: obs(A)})
        code, out = self.start([briefs], resume=True, registry=registry)
        self.assertEqual((code, out["reason"]),
                         (1, "the manager is not running after the restart"))
        self.assertEqual(len(self.posted("/api/withdraw")), 2)
        self.assertEqual(registry.calls, 4)
        self.assertEqual(self.stops, [(A, "default", 0)])

    def test_a_second_brief_version_is_not_met(self):
        views = [view(both(), [brief(A, "10:02:00", version=2)]),
                 view(both(), [brief(A, "10:02:00", version=2), brief(B, "10:03:00")])]
        code, out = self.start(views, resume=True)
        self.assertEqual((code, out["reason"]), (1, "a brief reached another sprint's slot"))
        self.assertEqual(self.restarts, [])

    def test_a_second_brief_version_with_no_other_brief_is_not_met_at_once(self):
        views = [view(both(), [brief(A, "10:02:00", version=2)])]
        code, out = self.start(views, resume=True)
        self.assertEqual((code, out["reason"]), (1, "a brief reached another sprint's slot"))
        self.assertEqual(out["brief_seconds"], [120, None])
        self.assertEqual(self.restarts, [])
        self.assertEqual(len(self.posted("/api/withdraw")), 2)
        self.assertEqual(self.result(), {A: 120, B: None})

    def test_timing_reads_the_console_times_and_fails_a_late_brief(self):
        def timing(*args):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = manager_check.main(["timing", "--result-file", str(self.result_file), *args])
            return code, json.loads(out.getvalue())

        self.assertEqual(timing(), (75, {"status": "no_result"}))
        late = view(both(), [brief(A, "10:11:00"), brief(B, "10:02:00")])
        code, _ = self.start([late], resume=True, registry=Registry({1: obs(A), 2: obs(B)}))
        self.assertEqual((code, self.result()), (0, {A: 660, B: 120}))
        self.assertEqual(timing()[0], 1)
        self.assertEqual(timing()[1]["status"], "slow")
        self.result_file.write_text(json.dumps({"status": "met", "brief_seconds": {A: 120, B: 180}}))
        self.assertEqual(timing()[0], 0)
        self.assertEqual(timing()[1]["status"], "met")
        self.result_file.write_text(json.dumps({"status": "met", "brief_seconds": {A: 120, B: None}}))
        self.assertEqual(timing()[0], 1)

    def test_a_console_that_drops_its_view_after_the_goals_keeps_the_run_recoverable(self):
        code, out = self.start([view([]), None])
        self.assertEqual((code, out), (75, {"status": "not_running"}))
        self.assertEqual(len(self.posted("/api/goal")), 2)
        self.assertEqual(self.posted("/api/withdraw"), [])
        self.assertTrue(self.state_file.exists())
        code, out = self.start([view(both())])
        self.assertEqual((code, out["status"]), (75, "waiting"))
        self.assertEqual(self.posted("/api/goal"), [])
        saved = json.loads(self.state_file.read_text())
        self.assertEqual([row["sprint_id"] for row in saved["sprints"]], [A, B])

    def test_a_goal_missing_after_a_crash_is_stated_alone_on_the_next_run(self):
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps(
            {"project": "owner/p01", "sprints": [], "unresolved": True}))
        first = view([sprint(A, GOALS[0])])
        code, out = self.start([first, view(both())])
        self.assertEqual((code, out["status"]), (75, "waiting"))
        self.assertEqual([post[2]["goal"] for post in self.posted("/api/goal")], [GOALS[1]])

    def test_sprints_that_cannot_be_withdrawn_keep_the_run_until_they_are(self):
        failing = [sprint(A, GOALS[0], manager_state="failed", manager_text="x"),
                   sprint(B, GOALS[1])]
        code, out = self.start([view(failing)], resume=True, withdraws=[500, 500])
        self.assertEqual((code, out["status"]), (75, "waiting"))
        self.assertTrue(self.state_file.exists())
        self.assertFalse(self.result_file.exists())
        code, out = self.start([view(failing)], resume=False, url=self.url)
        self.assertEqual((code, out["status"], out["reason"]), (1, "not_met", "x"))
        self.assertFalse(self.state_file.exists())
        self.assertEqual(self.result(), {A: None, B: None})

    def test_a_new_run_discards_the_previous_result(self):
        self.result_file.parent.mkdir(parents=True, exist_ok=True)
        self.result_file.write_text(json.dumps({"status": "met", "brief_seconds": {A: 1, B: 2}}))
        code, out = self.start([view([]), view(both())])
        self.assertEqual((code, out["status"]), (75, "waiting"))
        self.assertFalse(self.result_file.exists())
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            timing = manager_check.main(["timing", "--result-file", str(self.result_file)])
        self.assertEqual((timing, json.loads(out.getvalue())), (75, {"status": "no_result"}))

    def test_the_wrapper_is_executable_in_the_index(self):
        listed = subprocess.run(["git", "ls-files", "-s", WRAPPER], cwd=ROOT,
                                capture_output=True, text=True, check=True).stdout
        self.assertTrue(listed.startswith("100755"), listed)

    def test_an_off_loopback_url_is_refused(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            manager_check.main(["start", "--project", "x", "--url", "http://example.com"])
        self.assertEqual(raised.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
