"""The service starts a sprint's manager when a goal is stated and retries it (#888).

Run: just agent-workflow-tests
"""
import contextlib
import io
import json
import sys
import threading
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from agent_tools.console import capacity, console, manager, sprints
from agent_tools.console.event_log import GOAL_STATED, EventLog

from . import console_test_support as support
from .test_console_answer import view_of
from .test_console_writes import Case

GOAL = "/api/goal"
WITHDRAW = "/api/withdraw"
RETRY = "/api/retry-manager"
JSON = {"Content-Type": "application/json"}
FAR = 1_900_000_000
NOW = 1_800_000_000


def iso(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat(timespec="microseconds")


class ManagerServiceTest(Case):
    def start(self, **kwargs):
        support.write_registry(self.registry, support.entries(2))
        kwargs.setdefault("session_poll_seconds", 3600)
        return super().start(**kwargs)

    def post(self, svc, path, body, **extra):
        data = json.dumps(body).encode() if isinstance(body, dict) else body
        return support.post_page(svc.address, path, self.own(svc, **{**JSON, **extra}), data)

    def state(self, svc, goal="make the importer resumable", project_id="owner/p01"):
        status, _, body = self.post(svc, GOAL, {"project_id": project_id, "goal": goal})
        self.assertEqual((status, body), (204, b""))
        (row,) = [r for r in support.log_rows(self.store) if r[2] == GOAL_STATED][-1:]
        return json.loads(row[4])["sprint_id"]

    def retry(self, svc, sid, project_id="owner/p01"):
        return self.post(svc, RETRY, {"project_id": project_id, "sprint_id": sid})

    def secret(self, sid):
        return (self.store.parent / "sprint-secrets" / sid).read_text().removesuffix("\n")

    def sprint(self, svc, sid):
        for entry in view_of(svc)["entries"]:
            for project in entry["projects"] if entry["type"] == "quiet_group" else [entry]:
                for sprint in project["sprints"]:
                    if sprint["sprint_id"] == sid:
                        return sprint
        self.fail("the sprint is not in the view")

    def manager_rows(self):
        return [r for r in support.log_rows(self.store) if r[2].startswith("manager.")]

    def profiles(self, **utilization):
        base = self.store.parent.parent / "accounts" / "profiles"
        dirs = {name: base / name for name in utilization}
        for directory in dirs.values():
            directory.mkdir(parents=True)
        return dirs

    def seed_readings(self, readings):
        self.store.parent.mkdir(parents=True, exist_ok=True)
        log = EventLog(self.store)
        log.append([(capacity.READING, None, {"profile": profile, **report})
                    for profile, report in readings.items()])
        log.close()

    @staticmethod
    def weekly(utilization, reset=FAR):
        return {"http_status": 200, "status": "allowed", "windows": {
            "7d": {"status": "allowed", "utilization": utilization, "reset": reset}}}

    @staticmethod
    def exhausted(reset):
        return {"http_status": 429, "status": "rejected", "windows": {
            "7d": {"status": "rejected", "utilization": 1.0, "reset": reset}}}

    def test_a_stated_goal_launches_one_manager_with_its_identity(self):
        launches = support.Launches()
        svc = self.start(launcher=launches, bound_profile_of=lambda root: "work")
        sid = self.state(svc)
        (launch,) = launches.calls
        self.assertEqual(launch.cwd, "/srv/p01")
        self.assertEqual(launch.profile, "work")
        name = manager.session_name("owner/p01", sid)
        self.assertEqual(launch.session_name, name)
        self.assertEqual(launch.prompt, (
            "You are the manager of one sprint, started by the console. "
            'Run "sprint contract" first and follow what it prints. '
            "The goal: make the importer resumable"))
        self.assertEqual(launch.settings,
                         self.store.parent / "sprint-secrets" / (sid + ".settings.json"))
        self.assertEqual(dict(launch.env), {"CONSOLE_SPRINT_ID": sid,
                                            "CONSOLE_SPRINT_SECRET": self.secret(sid)})
        _, _, kind, project, payload = support.log_rows(self.store)[-1]
        self.assertEqual((kind, project, json.loads(payload)), (
            "manager.started", "owner/p01",
            {"profile": "work", "session_name": name, "sprint_id": sid}))
        self.assertEqual(self.sprint(svc, sid)["manager_state"], "started")

    def test_the_launch_uses_the_profile_with_most_weekly_allowance(self):
        dirs = self.profiles(work=0, home=0)
        self.seed_readings({"work": self.weekly(0.2), "home": self.weekly(0.6)})
        launches = support.Launches()
        svc = self.start(launcher=launches, profile_dirs=list(dirs.values()),
                         clock=lambda: NOW)
        self.state(svc)
        self.assertEqual([c.profile for c in launches.calls], ["work"])

    def test_the_choice_reads_the_profile_dirs_at_launch(self):
        base = self.store.parent.parent / "accounts" / "profiles"
        self.seed_readings({"work": self.weekly(0.6), "home": self.weekly(0.1)})
        (base / "work").mkdir(parents=True)
        dirs = [base / "work"]
        launches = support.Launches()
        svc = self.start(launcher=launches, profile_dirs=dirs, clock=lambda: NOW)
        (base / "home").mkdir()
        dirs.append(base / "home")
        self.state(svc)
        self.assertEqual([c.profile for c in launches.calls], ["home"])

    def test_every_profile_out_launches_nothing_and_waits_for_the_earliest_reset(self):
        first, second = FAR, FAR + 3600
        dirs = self.profiles(work=0, home=0)
        self.seed_readings({"work": self.exhausted(first), "home": self.exhausted(second)})
        launches = support.Launches()
        svc = self.start(launcher=launches, profile_dirs=list(dirs.values()),
                         clock=lambda: NOW)
        sid = self.state(svc)
        self.assertEqual(launches.calls, [])
        until = datetime.fromtimestamp(first, timezone.utc).isoformat()
        _, _, kind, project, payload = support.log_rows(self.store)[-1]
        self.assertEqual((kind, project, json.loads(payload)),
                         ("manager.waiting", "owner/p01", {"sprint_id": sid, "until": until}))
        sprint = self.sprint(svc, sid)
        self.assertEqual((sprint["manager_state"], sprint["manager_text"],
                          sprint["manager_until"], sprint["retry"]),
                         ("waiting", "waiting on quota until", until, True))

    def test_a_failed_start_shows_its_reason_and_retry_launches_again(self):
        launches = support.Launches(fail=["the directory is not trusted", None])
        svc = self.start(launcher=launches)
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            sid = self.state(svc)
        sprint = self.sprint(svc, sid)
        self.assertEqual((sprint["manager_state"], sprint["manager_text"], sprint["retry"]), (
            "failed", "could not start a manager: the directory is not trusted", True))
        self.assertIn(f"console: manager_failed {sid} the directory is not trusted",
                      stderr.getvalue())
        status, _, body = self.retry(svc, sid)
        self.assertEqual((status, body), (204, b""))
        self.assertEqual(len(launches.calls), 2)
        self.assertEqual(self.sprint(svc, sid)["manager_state"], "started")

    def test_a_missing_manager_can_be_retried(self):
        now = [NOW]
        launches = support.Launches()
        svc = self.start(launcher=launches, clock=lambda: now[0],
                         log_clock=lambda: iso(now[0]))
        sid = self.state(svc)
        now[0] = NOW + 60
        status, _, body = self.retry(svc, sid)
        self.assertEqual((status, body), (409, b"this sprint has a manager\n"))
        now[0] = NOW + 180
        svc.poll_sessions()
        sprint = self.sprint(svc, sid)
        self.assertEqual((sprint["manager_state"], sprint["retry"]), ("missing", True))
        status, _, body = self.retry(svc, sid)
        self.assertEqual((status, body), (204, b""))
        self.assertEqual(len(launches.calls), 2)

    def test_two_retries_launch_once(self):
        queue = support.Queued()
        launches = support.Launches(fail=["x", None, None])
        svc = self.start(launcher=launches, dispatch=queue)
        sid = self.state(svc)
        with contextlib.redirect_stderr(io.StringIO()):
            queue.run_next()
        self.assertEqual(self.sprint(svc, sid)["manager_state"], "failed")
        self.assertEqual(self.retry(svc, sid)[0], 204)
        self.assertEqual(len(queue.jobs), 1)
        status, _, body = self.retry(svc, sid)
        self.assertEqual((status, body), (409, b"a manager is starting for this sprint\n"))
        self.assertEqual(len(queue.jobs), 1)
        queue.run_next()
        self.assertEqual(len(launches.calls), 2)
        self.assertEqual(self.sprint(svc, sid)["manager_state"], "started")
        status, _, body = self.retry(svc, sid)
        self.assertEqual((status, body), (409, b"this sprint has a manager\n"))

    def test_a_finished_attempt_never_frees_a_later_retrys_reservation(self):
        queue = support.Queued()
        launches = support.Launches(fail=["x", None, None])
        svc = self.start(launcher=launches, dispatch=queue)
        sid = self.state(svc)
        record = svc._record_launch

        def record_then_retry_in_the_gap(launch, reason, token):
            record(launch, reason, token)
            svc.retry_manager("owner/p01", sid)

        with mock.patch.object(svc, "_record_launch", record_then_retry_in_the_gap):
            with contextlib.redirect_stderr(io.StringIO()):
                queue.run_next()
        self.assertEqual(len(queue.jobs), 1)
        status, _, body = self.retry(svc, sid)
        self.assertEqual((status, body), (409, b"a manager is starting for this sprint\n"))
        self.assertEqual(len(queue.jobs), 1)
        queue.run_next()
        self.assertEqual(len(launches.calls), 2)

    def test_a_launch_that_raised_past_the_recording_still_frees_the_reservation(self):
        launches = support.Launches()
        queue = support.Queued()
        svc = self.start(launcher=launches, dispatch=queue)
        sid = self.state(svc)
        with mock.patch.object(svc, "_prepared_launch", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                queue.run_next()
        svc.start_manager(sid)
        self.assertEqual(len(launches.calls), 1)

    def test_a_launch_is_rechecked_when_it_runs(self):
        launches = support.Launches()
        svc = self.start(launcher=launches)
        sid = self.state(svc)
        rows = support.log_rows(self.store)
        svc.start_manager(sid)
        self.assertEqual(len(launches.calls), 1)
        self.assertEqual(support.log_rows(self.store), rows)

    def test_retry_refusals_append_nothing(self):
        now = [NOW + 60]
        self.store.parent.mkdir(parents=True, exist_ok=True)
        old = sprints.new_sprint_id()
        sprints.create_secret(self.store.parent / "sprint-secrets", old)
        log = EventLog(self.store, clock=lambda: iso(NOW))
        log.append([(GOAL_STATED, "owner/p01", {"sprint_id": old, "goal": "an older goal"})])
        log.close()
        launches = support.Launches()
        svc = self.start(launcher=launches, clock=lambda: now[0],
                         log_clock=lambda: iso(now[0]))
        sid = self.state(svc)
        table = [
            ("a started sprint", lambda: self.retry(svc, sid), 409,
             b"this sprint has a manager\n"),
            ("a sprint no manager row speaks for", lambda: self.retry(svc, old), 409,
             b"retry is offered two minutes after the goal\n"),
            ("another project", lambda: self.retry(svc, sid, "owner/p00"), 409,
             b"this sprint is not open\n"),
            ("no token", lambda: support.post_page(
                svc.address, RETRY, {"Origin": f"http://127.0.0.1:{svc.address[1]}", **JSON},
                json.dumps({"project_id": "owner/p01", "sprint_id": sid}).encode()),
             403, b"token refused\n"),
            ("no sprint", lambda: self.post(svc, RETRY, {"project_id": "owner/p01"}), 400,
             b"bad retry\n"),
        ]
        for name, action, status, text in table:
            with self.subTest(name):
                got = self.assert_unchanged(svc, action)
                self.assertEqual((got[0], got[2]), (status, text))
        self.assertEqual(len(launches.calls), 1)
        svc.close()
        bare = self.start()
        got = self.assert_unchanged(bare, lambda: self.retry(bare, old))
        self.assertEqual((got[0], got[2]),
                         (409, b"managers are not available on this host yet\n"))

    def test_without_a_launcher_no_launch_is_made_and_the_sprint_says_so(self):
        svc = self.start()
        sid = self.state(svc)
        self.assertEqual(self.manager_rows(), [])
        self.assertIs(view_of(svc)["managers"], False)
        sprint = self.sprint(svc, sid)
        self.assertEqual((sprint["manager_text"], sprint["retry"]),
                         ("managers are not available on this host yet", False))

    def test_main_passes_the_platform_launcher(self):
        recorded = {}

        class Stub:
            def __init__(self, *args, **kwargs):
                recorded.update(kwargs)
                raise OSError("x")

        with mock.patch("agent_tools.console.console.service.ConsoleService", Stub), \
                contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(console.main(["--port", "0"]), 1)
        self.assertIs(recorded["launcher"], manager.launcher_for(sys.platform))

    def test_a_launch_never_holds_the_ingest_lock(self):
        alive = []
        holder = {}

        def launcher(launch):
            thread = threading.Thread(
                target=lambda: holder["svc"].sprint_status(launch.sprint_id), daemon=True)
            thread.start()
            thread.join(timeout=2)
            alive.append(thread.is_alive())

        svc = holder["svc"] = self.start(launcher=launcher)
        self.state(svc)
        self.assertEqual(alive, [False])

    def test_launches_run_on_their_own_thread_by_default(self):
        release, names = threading.Event(), []
        self.addCleanup(release.set)

        def blocking(launch):
            names.append(threading.current_thread().name)
            release.wait(10)

        svc = self.start(launcher=blocking, dispatch=None)
        self.state(svc)
        self.assertEqual(self.manager_rows(), [])
        release.set()
        deadline = time.monotonic() + 5
        while not self.manager_rows() and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertEqual([r[2] for r in self.manager_rows()], ["manager.started"])
        self.assertEqual(names, ["console-manager-launch"])

    def test_the_secret_appears_in_no_row_view_or_stderr(self):
        seen = []

        def launcher(launch):
            seen.append(launch.env["CONSOLE_SPRINT_SECRET"])
            raise manager.LaunchFailed("token " + seen[0])

        svc = self.start(launcher=launcher)
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            sid = self.state(svc)
        secret = seen[0]
        self.assertEqual(secret, self.secret(sid))
        for _, _, _, _, payload in support.log_rows(self.store):
            self.assertNotIn(secret, payload)
        self.assertNotIn(secret.encode(), svc.view_bytes)
        self.assertNotIn(secret, stderr.getvalue())
        (row,) = self.manager_rows()
        self.assertEqual(json.loads(row[4])["reason"], "token <secret>")

    def test_withdrawing_removes_the_managers_settings(self):
        launches = support.Launches()
        svc = self.start(launcher=launches)
        sid = self.state(svc)
        (launch,) = launches.calls
        launch.settings.write_text("{}")
        status, _, body = self.post(svc, WITHDRAW, {"project_id": "owner/p01", "sprint_id": sid})
        self.assertEqual((status, body), (204, b""))
        self.assertFalse(launch.settings.exists())


if __name__ == "__main__":
    unittest.main()
