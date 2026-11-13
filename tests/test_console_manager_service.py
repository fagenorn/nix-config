"""The service starts a sprint's manager when a goal is stated and retries it (#888).

Run: just agent-workflow-tests
"""
import contextlib
import inspect
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from agent_tools.console import (capacity, console, manager, nudge, probe, service, sessions,
                                 signin, sprints)
from agent_tools.console.event_log import GOAL_STATED, EventLog

from . import console_test_support as support
from .test_console_answer import view_of
from .test_console_briefs import PARTS
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
        if "profile_dirs" not in kwargs:
            support.sign_in(self.store, "work")
            kwargs["profile_dirs"] = [support.profile_dir(self.store, "work")]
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
            directory.mkdir(parents=True, exist_ok=True)
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
        support.sign_in(self.store, "work")
        svc = self.start(launcher=launches,
                         profile_dirs=[support.profile_dir(self.store, "work")])
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
            {"profile": "work", "session_name": name, "sprint_id": sid, "seen_after": 0}))
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

    def test_a_binding_to_another_profile_does_not_change_the_launch(self):
        dirs = self.profiles(work=0, home=0)
        accounts = self.store.parent.parent / "accounts"
        (accounts / "bindings.tsv").write_text("/srv/p01\thome\n")
        support.sign_in(self.store, "work")
        launches = support.Launches()
        with mock.patch.dict(os.environ, {"CLAUDE_ACCOUNTS_DIR": str(accounts)}):
            svc = self.start(launcher=launches, profile_dirs=list(dirs.values()),
                             clock=lambda: NOW)
            self.state(svc)
        self.assertEqual([c.profile for c in launches.calls], ["work"])

    def test_a_signed_out_profile_is_never_launched(self):
        dirs = self.profiles(work=0, home=0)
        self.seed_readings({"work": self.exhausted(FAR)})
        self.store.parent.mkdir(parents=True, exist_ok=True)
        log = EventLog(self.store)
        log.append([signin.entry("home", signin.Status("signed_out", None))])
        log.close()
        launches = support.Launches()
        svc = self.start(launcher=launches, profile_dirs=list(dirs.values()),
                         clock=lambda: NOW)
        sid = self.state(svc)
        self.assertEqual(launches.calls, [])
        until = datetime.fromtimestamp(FAR, timezone.utc).isoformat()
        _, _, kind, project, payload = support.log_rows(self.store)[-1]
        self.assertEqual((kind, project, json.loads(payload)),
                         ("manager.waiting", "owner/p01", {"sprint_id": sid, "until": until}))
        self.assertTrue(json.loads(svc.view_bytes)["capacity"]["all_out"])

    def test_a_signed_out_profile_with_the_most_room_is_skipped(self):
        dirs = self.profiles(work=0, home=0)
        self.seed_readings({"work": self.weekly(0.2), "home": self.weekly(0.6)})
        log = EventLog(self.store)
        log.append([signin.entry("work", signin.Status("signed_out", None))])
        log.close()
        launches = support.Launches()
        svc = self.start(launcher=launches, profile_dirs=list(dirs.values()),
                         clock=lambda: NOW)
        self.state(svc)
        self.assertEqual([c.profile for c in launches.calls], ["home"])

    def test_the_service_takes_no_binding(self):
        self.assertNotIn("bound_profile_of", inspect.signature(service.ConsoleService).parameters)

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

    def test_a_reserved_retry_does_not_launch_once_the_failed_manager_briefed(self):
        queue = support.Queued()
        launches = support.Launches(fail=["x", None])
        svc = self.start(launcher=launches, dispatch=queue)
        sid = self.state(svc)
        with contextlib.redirect_stderr(io.StringIO()):
            queue.run_next()
        self.assertEqual(self.sprint(svc, sid)["manager_state"], "failed")
        self.assertEqual(self.retry(svc, sid)[0], 204)
        svc.send_brief(sid, self.secret(sid), PARTS)
        sprint = self.sprint(svc, sid)
        self.assertEqual((sprint["manager_state"], sprint["retry"]), ("failed", False))
        rows = support.log_rows(self.store)
        queue.run_next()
        self.assertEqual(len(launches.calls), 1)
        self.assertEqual(support.log_rows(self.store), rows)
        self.assertEqual(self.retry(svc, sid)[0], 409)

    def test_a_goal_withdrawn_while_its_launch_is_in_flight_leaves_no_settings(self):
        holder = {}

        def launcher(launch):
            holder["svc"].withdraw_goal("owner/p01", launch.sprint_id)
            launch.settings.write_text("{}")

        svc = holder["svc"] = self.start(launcher=launcher)
        sid = self.state(svc)
        secrets = self.store.parent / "sprint-secrets"
        self.assertEqual(sorted(p.name for p in secrets.iterdir()), [])
        self.assertEqual([r[2] for r in self.manager_rows()], [])
        self.assertEqual(svc.sprint_status(sid)["decision"], "withdrawn")

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

    def test_main_passes_the_platform_nudger(self):
        recorded = {}

        class Stub:
            def __init__(self, *args, **kwargs):
                recorded.update(kwargs)
                raise OSError("x")

        with mock.patch("agent_tools.console.console.service.ConsoleService", Stub), \
                contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(console.main(["--port", "0"]), 1)
        self.assertIs(recorded["nudger"], nudge.nudger_for(sys.platform))

    def test_main_passes_the_platform_full_lister(self):
        recorded = {}

        class Stub:
            def __init__(self, *args, **kwargs):
                recorded.update(kwargs)
                raise OSError("x")

        with mock.patch("agent_tools.console.console.service.ConsoleService", Stub), \
                contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(console.main(["--port", "0"]), 1)
        self.assertIs(recorded["full_listing"], nudge.full_lister_for(sys.platform))

    def test_main_passes_the_platform_prober(self):
        recorded = {}

        class Stub:
            def __init__(self, *args, **kwargs):
                recorded.update(kwargs)
                raise OSError("x")

        with mock.patch("agent_tools.console.console.service.ConsoleService", Stub), \
                contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(console.main(["--port", "0"]), 1)
        self.assertIs(recorded["prober"], probe.prober_for(sys.platform))

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


class ProfileChoiceServiceTest(ManagerServiceTest):
    """The console answers the profile a new session should use and keeps it in a file (#1011)."""

    PROFILE = "/api/profile"

    def ask(self, svc):
        return support.request(svc.address, "GET", self.PROFILE)

    @staticmethod
    def both(week, five):
        return {"http_status": 200, "status": "allowed", "windows": {
            "7d": {"status": "allowed", "utilization": week, "reset": FAR},
            "5h": {"status": "allowed", "utilization": five, "reset": FAR}}}

    def seed_signins(self, **states):
        self.store.parent.mkdir(parents=True, exist_ok=True)
        log = EventLog(self.store)
        try:
            log.append([signin.entry(name, signin.Status(state, None))
                        for name, state in states.items()])
        finally:
            log.close()

    @staticmethod
    def identity(path):
        stat = path.stat()
        return (stat.st_ino, stat.st_mtime_ns)

    @property
    def choice(self):
        return self.store.parent.parent / "accounts" / "chosen-profile"

    def two_profiles(self, readings):
        dirs = self.profiles(work=0, home=0)
        self.seed_readings(readings)
        return list(dirs.values())

    def test_the_route_answers_the_profile_with_most_weekly_allowance(self):
        dirs = self.two_profiles({"work": self.weekly(0.2), "home": self.weekly(0.6)})
        svc = self.start(profile_dirs=dirs, clock=lambda: NOW)
        status, headers, body = self.ask(svc)
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "application/json")
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(body, b'{"profile":"work"}')

    def test_the_route_breaks_a_weekly_tie_on_five_hour_allowance(self):
        dirs = self.two_profiles({"work": self.both(0.5, 0.7), "home": self.both(0.5, 0.1)})
        svc = self.start(profile_dirs=dirs, clock=lambda: NOW)
        self.assertEqual(self.ask(svc)[2], b'{"profile":"home"}')

    def test_the_route_never_answers_a_signed_out_profile(self):
        dirs = self.two_profiles({"work": self.weekly(0.2), "home": self.weekly(0.6)})
        self.seed_signins(work="signed_out")
        svc = self.start(profile_dirs=dirs, clock=lambda: NOW)
        self.assertEqual(self.ask(svc)[2], b'{"profile":"home"}')

    def test_with_no_room_the_route_answers_the_most_recently_used_signed_in_profile(self):
        dirs = list(self.profiles(work=0, home=0).values())
        self.seed_signins(work="signed_in", home="signed_in")
        for session_id, profile in (("s-1", "home"), ("s-2", "work"), ("s-3", "gone")):
            log = EventLog(self.store)
            try:
                log.append([(sessions.SEEN, None, {
                    "session_id": session_id, "cwd": "/srv/p01", "repo": "/srv/p01",
                    "state": sessions.IDLE, "profile": profile})])
            finally:
                log.close()
        launches = support.Launches()
        svc = self.start(profile_dirs=dirs, clock=lambda: NOW, launcher=launches)
        svc.poll_sessions()
        gone = [json.loads(row[4])["session_id"]
                for row in support.log_rows(self.store) if row[2] == sessions.GONE]
        self.assertIn("s-1", gone)
        self.assertIn("s-2", gone)
        self.assertEqual(self.ask(svc)[2], b'{"profile":"work"}')
        self.state(svc)
        (launch,) = launches.calls
        self.assertEqual(launch.profile, "work")
        svc.close()
        again = self.start(profile_dirs=dirs, clock=lambda: NOW, launcher=support.Launches())
        self.assertEqual(self.ask(again)[2], b'{"profile":"work"}')

    def test_retention_keeps_the_use_of_a_session_whose_assignment_it_removes(self):
        dirs = list(self.profiles(work=0, home=0).values())
        day = 86400
        now = [NOW]
        stamp = lambda: iso(now[0])
        self.store.parent.mkdir(parents=True, exist_ok=True)
        log = EventLog(self.store, clock=stamp)
        try:
            def at(days, *entries):
                now[0] = NOW + days * day
                log.append(list(entries))

            seen = lambda sid, profile: (sessions.SEEN, None, {
                "session_id": sid, "cwd": "/srv/p01", "repo": "/srv/p01",
                "state": sessions.IDLE, "profile": profile})
            at(0, signin.entry("work", signin.Status("signed_in", None)),
               signin.entry("home", signin.Status("signed_in", None)), seen("s-b", "home"),
               ("old", None, {}))
            at(10, seen("s-a", "work"))
            at(20, (sessions.HOOK, None, {"session_id": "s-b", "event": "Stop"}))
            at(30, (sessions.GONE, None, {"session_id": "s-a"}),
               (sessions.GONE, None, {"session_id": "s-b"}))
        finally:
            log.close()
        now[0] = NOW + 50 * day
        svc = self.start(profile_dirs=dirs, clock=lambda: now[0], log_clock=stamp)
        self.assertEqual(self.ask(svc)[2], b'{"profile":"home"}')
        now[0] = NOW + 95 * day
        self.assertEqual(svc.retain(), 1)
        kinds = [r[2] for r in support.log_rows(self.store)]
        self.assertEqual(kinds.count(sessions.SEEN), 2)
        self.assertEqual(self.ask(svc)[2], b'{"profile":"home"}')
        svc.close()
        again = self.start(profile_dirs=dirs, clock=lambda: now[0], log_clock=stamp)
        self.assertEqual(self.ask(again)[2], b'{"profile":"home"}')

    def test_with_no_sign_in_known_the_route_answers_null(self):
        dirs = list(self.profiles(work=0, home=0).values())
        svc = self.start(profile_dirs=dirs, clock=lambda: NOW, choice_file=self.choice)
        self.assertEqual(self.ask(svc)[::2], (200, b'{"profile":null}'))
        self.assertFalse(self.choice.exists())

    def test_other_methods_on_the_profile_route_are_refused(self):
        svc = self.start()
        status, headers, _ = support.request(svc.address, "POST", self.PROFILE)
        self.assertEqual((status, headers["Allow"]), (405, "GET"))
        self.assertEqual(
            support.request(svc.address, "GET", self.PROFILE, host="example.com:80")[0], 403)

    def test_the_choice_file_is_written_when_and_only_when_the_choice_changes(self):
        dirs = self.two_profiles({"work": self.weekly(0.2), "home": self.weekly(0.6)})
        now = [NOW]

        def reader(one):
            if one.profile == "work" and now[0] > NOW:
                return signin.Status("signed_out", None)
            return signin.Status("signed_in", None)

        choice = self.choice
        svc = self.start(profile_dirs=dirs, clock=lambda: now[0], choice_file=choice,
                         signin_reader=reader, probe_dispatch=lambda job: job())
        self.assertEqual(choice.read_text(), "work\n")
        before = self.identity(choice)
        svc.poll_sessions()
        svc.poll_sessions()
        self.ask(svc)
        self.ask(svc)
        self.assertEqual(self.identity(choice), before)
        self.assertEqual(sorted(p.name for p in choice.parent.iterdir()),
                         ["chosen-profile", "profiles"])
        now[0] = NOW + 31
        svc.probe_round()
        svc.poll_sessions()
        self.assertEqual(choice.read_text(), "home\n")
        self.assertNotEqual(choice.stat().st_ino, before[0])
        self.assertEqual(self.ask(svc)[2], b'{"profile":"home"}')
        after = self.identity(choice)
        svc.poll_sessions()
        self.assertEqual(self.identity(choice), after)

    def test_a_restart_that_finds_its_choice_in_the_file_writes_nothing(self):
        dirs = self.two_profiles({"work": self.weekly(0.2), "home": self.weekly(0.6)})
        choice = self.choice
        choice.parent.mkdir(parents=True, exist_ok=True)
        choice.write_text("work\n")
        before = self.identity(choice)
        svc = self.start(profile_dirs=dirs, clock=lambda: NOW, choice_file=choice)
        svc.poll_sessions()
        self.ask(svc)
        self.assertEqual(self.identity(choice), before)
        self.assertEqual(choice.read_text(), "work\n")

    def test_a_route_answer_that_changed_is_written_at_once(self):
        self.seed_readings({"work": self.weekly(0.6), "home": self.weekly(0.1)})
        dirs = [support.profile_dir(self.store, "work")]
        choice = self.choice
        svc = self.start(profile_dirs=dirs, clock=lambda: NOW, choice_file=choice)
        self.assertEqual(choice.read_text(), "work\n")
        dirs.append(support.profile_dir(self.store, "home"))
        self.assertEqual(self.ask(svc)[2], b'{"profile":"home"}')
        self.assertEqual(choice.read_text(), "home\n")

    def test_without_a_choice_file_nothing_is_written(self):
        root = self.store.parent.parent.parent
        dirs = self.two_profiles({"work": self.weekly(0.2), "home": self.weekly(0.6)})
        env = {"CLAUDE_ACCOUNTS_DIR": str(self.store.parent.parent / "accounts"),
               "HOME": str(root / "home")}
        with mock.patch.dict(os.environ, env):
            svc = self.start(profile_dirs=dirs, clock=lambda: NOW)
            svc.poll_sessions()
            status, _, body = self.ask(svc)
        self.assertEqual((status, body), (200, b'{"profile":"work"}'))
        self.assertEqual(list(root.rglob("chosen-profile")), [])

    def test_a_choice_file_that_cannot_be_written_warns_once_until_a_write_succeeds(self):
        self.seed_readings({"work": self.weekly(0.2), "home": self.weekly(0.1)})
        dirs = [support.profile_dir(self.store, "work")]
        blocked = self.store.parent.parent / "blocked"
        blocked.write_text("x")
        chosen = blocked / "chosen-profile"
        stderr = io.StringIO()

        def warnings():
            return [line for line in stderr.getvalue().splitlines()
                    if line.startswith("console: choice_unwritten ")]

        with contextlib.redirect_stderr(stderr):
            svc = self.start(clock=lambda: NOW, profile_dirs=dirs, choice_file=chosen)
            svc.poll_sessions()
            svc.poll_sessions()
            self.assertEqual(len(warnings()), 1)
            self.assertEqual(self.ask(svc)[::2], (200, b'{"profile":"work"}'))
            blocked.unlink()
            blocked.mkdir()
            svc.poll_sessions()
            self.assertEqual(chosen.read_text(), "work\n")
            shutil.rmtree(blocked)
            blocked.write_text("x")
            dirs.append(support.profile_dir(self.store, "home"))
            svc.poll_sessions()
        self.assertEqual(len(warnings()), 2)

    def test_main_passes_the_default_choice_file(self):
        recorded = {}

        class Stub:
            def __init__(self, *args, **kwargs):
                recorded.update(kwargs)
                raise OSError("x")

        with mock.patch("agent_tools.console.console.service.ConsoleService", Stub), \
                contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(console.main(["--port", "0"]), 1)
        self.assertEqual(recorded["choice_file"], service.default_choice_file())

    def test_the_default_choice_file_is_in_the_accounts_dir(self):
        with mock.patch.dict(os.environ, {"CLAUDE_ACCOUNTS_DIR": "/x"}):
            self.assertEqual(service.default_choice_file(), Path("/x/chosen-profile"))
        with tempfile.TemporaryDirectory() as home:
            env = {key: value for key, value in os.environ.items()
                   if key != "CLAUDE_ACCOUNTS_DIR"}
            env["HOME"] = home
            with mock.patch.dict(os.environ, env, clear=True):
                self.assertEqual(service.default_choice_file(),
                                 Path(home) / ".claude-accounts" / "chosen-profile")

    def test_when_nothing_can_be_chosen_the_route_answers_null_and_the_file_goes(self):
        dirs = [support.profile_dir(self.store, "default")]
        self.seed_readings({"default": self.weekly(0.2)})
        self.seed_signins(default="signed_out")
        choice = self.choice
        choice.parent.mkdir(parents=True, exist_ok=True)
        choice.write_text("default\n")
        launches = support.Launches()
        svc = self.start(profile_dirs=dirs, clock=lambda: NOW, choice_file=choice,
                         launcher=launches)
        self.assertEqual(self.ask(svc)[::2], (200, b'{"profile":null}'))
        self.assertFalse(choice.exists())
        self.state(svc)
        self.assertEqual(launches.calls, [])
        _, _, kind, _, payload = support.log_rows(self.store)[-1]
        self.assertEqual(kind, "manager.waiting")
        self.assertIsNone(json.loads(payload)["until"])


if __name__ == "__main__":
    unittest.main()
