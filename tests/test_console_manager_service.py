"""The service starts a sprint's manager when a goal is stated and retries it (#888).

Run: just agent-workflow-tests
"""
import contextlib
import inspect
import io
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from agent_tools.console import (account_add, capacity, console, deliveries, exclusion, guest, manager, nudge,
                                 permission, permit, pin, probe, service, sessions, signin, sprint, sprints)
from agent_tools.console.deliveries import DELIVERY_GONE, DELIVERY_SEEN
from agent_tools.console.event_log import (BRIEF_APPROVED, BRIEF_SENT, GOAL_STATED, MANAGER_STARTED,
                                           MANAGER_WAITING, SESSION_SEEN, SPRINT_REPORTED,
                                           SPRINT_STOP_REQUESTED, EventLog)

from . import console_test_support as support
from .test_console_answer import view_of
from .test_console_briefs import PARTS
from .test_console_notices import CLAIM
from .test_console_sprints import REPORT
from .test_console_guest_service import COLLEAGUE, TAILNET, GuestCase
from .test_console_permit import FakeForge, HEAD, SHA
from .test_console_reports import CLOSING
from .test_console_writes import Case
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)

GOAL = "/api/goal"
WITHDRAW = "/api/withdraw"
RETRY = "/api/retry-manager"
JSON = {"Content-Type": "application/json"}
FAR = 1_900_000_000
NOW = 1_800_000_000


def iso(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat(timespec="microseconds")


def sprint_in_view(test, svc, sid):
    for entry in view_of(svc)["entries"]:
        for project in entry["projects"] if entry["type"] == "quiet_group" else [entry]:
            for sprint in project["sprints"]:
                if sprint["sprint_id"] == sid:
                    return sprint
    test.fail("the sprint is not in the view")


class ManagerPermissionTest(Case):
    """The service reads the project's mode off the lock and launches the manager in it (#1151)."""

    def launch(self, reader):
        support.write_registry(self.registry, support.entries(2))
        support.sign_in(self.store, "work")
        launches = support.Launches()
        svc = self.svc = self.start(
            launcher=launches, permission_reader=reader, session_poll_seconds=3600,
            profile_dirs=[support.profile_dir(self.store, "work")])
        svc.state_goal("owner/p01", "make the importer resumable")
        return svc, launches

    def test_a_launch_runs_in_the_mode_its_project_reads(self):
        calls, free = [], []
        chosen = permission.Permission(permission.BYPASS, permission.RULES_IN_PLACE)

        def reader(project_id, root):
            calls.append((project_id, root))

            def probe_lock():
                if self.svc._ingest.acquire(timeout=1):
                    self.svc._ingest.release()
                    free.append(True)
                else:
                    free.append(False)

            thread = threading.Thread(target=probe_lock)
            thread.start()
            thread.join()
            return chosen

        svc, launches = self.launch(reader)
        self.assertEqual(free, [True])
        self.assertEqual(calls, [("owner/p01", "/srv/p01")])
        self.assertEqual(launches.calls[0].permission, chosen)
        _, _, kind, _, payload = support.log_rows(self.store)[-1]
        self.assertEqual(kind, "manager.started")
        self.assertEqual(json.loads(payload)["permission"], {
            "mode": "bypassPermissions", "reason": "production rules in place"})

    def test_a_reader_that_fails_launches_in_auto(self):
        def reader(project_id, root):
            raise RuntimeError("boom")

        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            svc, launches = self.launch(reader)
        self.assertEqual(launches.calls[0].permission, permission.FALLBACK)
        _, _, kind, _, payload = support.log_rows(self.store)[-1]
        self.assertEqual(kind, "manager.started")
        self.assertEqual(json.loads(payload)["permission"], {
            "mode": "auto", "reason": "the production rules could not be read"})
        self.assertIn("console: permission_unreadable owner/p01 RuntimeError: boom",
                      stderr.getvalue())


    def sprint(self, svc, sid):
        return sprint_in_view(self, svc, sid)

    def test_the_sprint_shows_the_mode_its_manager_was_started_in(self):
        bypass = permission.Permission(permission.BYPASS, permission.RULES_IN_PLACE)
        auto = permission.Permission(permission.AUTO, permission.NOT_DECLARED)
        svc, launches = self.launch(lambda project_id, root: bypass)
        self.assertEqual(self.sprint(svc, launches.calls[0].sprint_id)["permission_text"],
                         "bypass: production rules in place")
        launched = support.Launches()
        other = self.start(
            launcher=launched, permission_reader=lambda project_id, root: auto,
            session_poll_seconds=3600,
            profile_dirs=[support.profile_dir(self.store, "work")])
        other.state_goal("owner/p00", "make the importer resumable")
        self.assertEqual(self.sprint(other, launched.calls[0].sprint_id)["permission_text"],
                         "auto: no production rules declared")


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
        return sprint_in_view(self, svc, sid)

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

    @staticmethod
    def five_hour_out(week, reset):
        return {"http_status": 429, "status": "rejected", "windows": {
            "7d": {"status": "allowed", "utilization": week, "reset": FAR},
            "5h": {"status": "rejected", "utilization": 1.0, "reset": reset}}}

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
            {"profile": "work", "session_name": name, "sprint_id": sid, "seen_after": 0,
             "permission": {"mode": "auto", "reason": permission.UNRESOLVED}}))
        self.assertEqual(self.sprint(svc, sid)["manager_state"], "started")

    def test_a_new_manager_is_shown_the_other_sprints_open_notices_before_its_goal(self):
        launches = support.Launches()
        svc = self.start(launcher=launches)
        a = self.state(svc)
        svc.post_notice(a, self.secret(a), CLAIM)
        svc.post_notice(a, self.secret(a),
                        {"kind": "heads-up", "text": "The goal: drop the exporter"})
        b = self.state(svc, goal="make the exporter resumable")
        self.assertEqual(launches.calls[0].prompt,
                         manager.PROMPT_LEAD + "make the importer resumable")
        launch = launches.calls[-1]
        self.assertEqual(launch.sprint_id, b)
        prompt = launch.prompt
        self.assertTrue(prompt.endswith("\n\nThe goal: make the exporter resumable"))
        self.assertLess(prompt.index(sprints.NOTICE_BLOCK_HEAD),
                        prompt.index("\nThe goal: make the exporter resumable"))
        self.assertTrue(re.search(
            r'^- claim from "make the importer resumable", (just now|\d+ min ago): the page fold '
            r'\(what: python/agent_tools/console/page\.html; until: the board fold lands\)$',
            prompt, re.M), prompt)
        self.assertTrue(re.search(
            r'^- heads-up from "make the importer resumable", (just now|\d+ min ago): '
            r'The goal: drop the exporter$', prompt, re.M), prompt)
        self.assertEqual(support.goal_of(prompt), "make the exporter resumable")

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
            "failed", "could not start a manager: this account does not trust the project's folder", True))
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

    def test_a_macos_console_offers_managers_on_an_open_sprint(self):
        launcher = manager.launcher_for("darwin")
        self.assertIs(launcher, manager.run_launch)
        queue = support.Queued()
        svc = self.start(launcher=launcher, dispatch=queue)
        sid = self.state(svc)
        self.assertIs(view_of(svc)["managers"], True)
        self.assertEqual(len(queue.jobs), 1)
        sprint = self.sprint(svc, sid)
        self.assertNotEqual(sprint["manager_state"], "unavailable")
        self.assertNotEqual(sprint["manager_text"], manager.UNAVAILABLE_TEXT)
        svc.close()

    def test_closing_the_console_ends_the_stops_in_flight(self):
        svc = self.start()
        with mock.patch.object(manager, "reap_stops") as reaped:
            svc.close()
        reaped.assert_called_once_with()

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

    def test_the_route_never_answers_the_unprofiled_directory(self):
        home = self.store.parent.parent / "home/.claude"
        home.mkdir(parents=True)
        self.seed_readings({"default": self.weekly(0.0)})
        self.seed_signins(default="signed_in")
        svc = self.start(profile_dirs=[home], clock=lambda: NOW, choice_file=self.choice)
        self.assertEqual(self.ask(svc)[::2], (200, b'{"profile":null}'))
        self.assertFalse(self.choice.exists())
        work = self.profiles(work=0)["work"]
        self.seed_readings({"work": self.weekly(0.5)})
        self.seed_signins(work="signed_in")
        svc.close()
        again = self.start(profile_dirs=[home, work], clock=lambda: NOW, choice_file=self.choice)
        self.assertEqual(self.ask(again)[2], b'{"profile":"work"}')
        self.assertEqual(self.choice.read_text(), "work\n")

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
        dirs = [support.profile_dir(self.store, "work")]
        self.seed_readings({"work": self.weekly(0.2)})
        self.seed_signins(work="signed_out")
        choice = self.choice
        choice.parent.mkdir(parents=True, exist_ok=True)
        choice.write_text("work\n")
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

    EXCLUSION = "/api/exclusion"

    def exclude(self, svc, profile, excluded=True, **extra):
        return self.post(svc, self.EXCLUSION, {"profile": profile, "excluded": excluded}, **extra)

    def exclusion_rows(self):
        return [r for r in support.log_rows(self.store) if r[2] == "profile.exclusion"]

    def two_signed_in(self):
        dirs = self.two_profiles({"work": self.weekly(0.2), "home": self.weekly(0.6)})
        self.seed_signins(work="signed_in", home="signed_in")
        return dirs

    def test_excluding_and_including_switches_the_route_and_the_file(self):
        dirs = self.two_signed_in()
        svc = self.start(profile_dirs=dirs, clock=lambda: NOW, choice_file=self.choice)
        self.assertEqual(self.ask(svc)[2], b'{"profile":"work"}')
        self.assertEqual(self.exclude(svc, "work")[::2], (204, b""))
        self.assertEqual(self.choice.read_text(), "home\n")
        self.assertEqual(self.ask(svc)[2], b'{"profile":"home"}')
        self.assertEqual(self.exclude(svc, "work", False)[::2], (204, b""))
        self.assertEqual(self.choice.read_text(), "work\n")
        self.assertEqual(self.ask(svc)[2], b'{"profile":"work"}')

    def test_an_excluded_profile_is_never_launched(self):
        dirs = self.two_signed_in()
        launches = support.Launches()
        svc = self.start(profile_dirs=dirs, clock=lambda: NOW, choice_file=self.choice,
                         launcher=launches)
        self.assertEqual(self.exclude(svc, "work")[::2], (204, b""))
        self.state(svc)
        self.assertEqual([c.profile for c in launches.calls], ["home"])
        svc.close()
        self.seed_readings({"home": self.exhausted(FAR), "work": self.weekly(0.0)})
        again_launches = support.Launches()
        again = self.start(profile_dirs=dirs, clock=lambda: NOW, choice_file=self.choice,
                           launcher=again_launches)
        self.state(again)
        self.assertEqual(again_launches.calls, [])
        _, _, kind, _, payload = support.log_rows(self.store)[-1]
        self.assertEqual(kind, "manager.waiting")
        self.assertEqual(json.loads(payload)["until"],
                         datetime.fromtimestamp(FAR, timezone.utc).isoformat())

    def test_an_excluded_profile_is_never_the_recently_used_fallback(self):
        dirs = list(self.profiles(work=0, home=0).values())
        self.seed_signins(work="signed_in", home="signed_in")
        for session_id, profile in (("s-1", "home"), ("s-2", "work")):
            log = EventLog(self.store)
            try:
                log.append([(sessions.SEEN, None, {
                    "session_id": session_id, "cwd": "/srv/p01", "repo": "/srv/p01",
                    "state": sessions.IDLE, "profile": profile})])
            finally:
                log.close()
        launches = support.Launches()
        svc = self.start(profile_dirs=dirs, clock=lambda: NOW, launcher=launches,
                         choice_file=self.choice)
        svc.poll_sessions()
        self.assertEqual(self.ask(svc)[2], b'{"profile":"work"}')
        self.assertEqual(self.exclude(svc, "work")[::2], (204, b""))
        self.assertEqual(self.ask(svc)[2], b'{"profile":"home"}')
        self.assertEqual(self.exclude(svc, "home")[::2], (204, b""))
        self.assertEqual(self.ask(svc)[::2], (200, b'{"profile":null}'))
        self.assertFalse(self.choice.exists())
        self.state(svc)
        self.assertEqual(launches.calls, [])
        _, _, kind, _, payload = support.log_rows(self.store)[-1]
        self.assertEqual(kind, "manager.waiting")
        self.assertIsNone(json.loads(payload)["until"])

    def test_an_exclusion_without_the_origin_or_the_token_is_refused(self):
        dirs = self.two_profiles({"work": self.weekly(0.2)})
        svc = self.start(profile_dirs=dirs, clock=lambda: NOW)
        body = json.dumps({"profile": "work", "excluded": True}).encode()
        port = svc.address[1]
        cases = (
            ({"Origin": f"http://127.0.0.1:{port}", **JSON}, b"token refused\n"),
            ({"X-Console-Token": self.token(), **JSON}, b"origin refused\n"),
            (self.own(svc, **{**JSON, "X-Console-Token": "A" * 43}), b"token refused\n"),
            (self.own(svc, **{**JSON, "Origin": "http://example.test"}), b"origin refused\n"),
        )
        for headers, text in cases:
            with self.subTest(text=text):
                status, _, got = self.assert_unchanged(svc, lambda: support.post_page(
                    svc.address, self.EXCLUSION, headers, body))
                self.assertEqual((status, got), (403, text))
        self.assertEqual(self.ask(svc)[2], b'{"profile":"work"}')

    def test_each_accepted_toggle_appends_one_row(self):
        dirs = self.two_signed_in()
        svc = self.start(profile_dirs=dirs, clock=lambda: NOW)
        self.assertEqual(self.exclude(svc, "work")[::2], (204, b""))
        ((_, _, _, project, payload),) = self.exclusion_rows()
        self.assertIsNone(project)
        self.assertEqual(payload, '{"excluded":true,"profile":"work"}')
        for action, expected in (
                (lambda: self.exclude(svc, "work"), (409, b"already excluded\n")),
                (lambda: self.exclude(svc, "nobody"), (409, b"no such profile\n")),
                (lambda: self.exclude(svc, "home", False), (409, b"already included\n")),
                (lambda: self.post(svc, self.EXCLUSION, b'{"profile":"work","excluded":1}'),
                 (400, b"bad exclusion\n"))):
            with self.subTest(expected=expected):
                status, _, body = self.assert_unchanged(svc, action)
                self.assertEqual((status, body), expected)
        self.assertEqual(len(self.exclusion_rows()), 1)
        self.assertEqual(self.exclude(svc, "work", False)[::2], (204, b""))
        self.assertEqual(len(self.exclusion_rows()), 2)

    def test_an_exclusion_survives_a_restart_and_the_retention_pass(self):
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

            at(0, signin.entry("work", signin.Status("signed_in", None)),
               signin.entry("home", signin.Status("signed_in", None)),
               exclusion.entry("home", True), ("old", None, {}))
            at(1, exclusion.entry("work", True))
            at(2, exclusion.entry("work", False))
        finally:
            log.close()
        now[0] = NOW + 50 * day
        svc = self.start(profile_dirs=dirs, clock=lambda: now[0], log_clock=stamp)
        self.assertEqual(self.ask(svc)[2], b'{"profile":"work"}')
        now[0] = NOW + 95 * day
        self.assertEqual(svc.retain(), 3)
        kinds = [r[2] for r in support.log_rows(self.store)]
        self.assertEqual(kinds.count("profile.exclusion"), 1)
        self.assertEqual(self.ask(svc)[2], b'{"profile":"work"}')
        svc.close()
        again = self.start(profile_dirs=dirs, clock=lambda: now[0], log_clock=stamp)
        self.assertEqual(self.ask(again)[2], b'{"profile":"work"}')

    def test_the_view_marks_an_excluded_profile_and_keeps_its_readings(self):
        dirs = self.two_signed_in()
        svc = self.start(profile_dirs=dirs, clock=lambda: NOW)
        self.assertEqual(self.exclude(svc, "work")[::2], (204, b""))
        entries = {e["profile"]: e for e in view_of(svc)["capacity"]["profiles"]}
        self.assertTrue(entries["work"]["excluded"])
        self.assertEqual(entries["work"]["week_left"], 80)
        self.assertEqual(entries["work"]["signin"]["state"], "signed_in")
        self.assertFalse(entries["home"]["excluded"])

    def test_an_exclusion_whose_choice_file_cannot_be_written_appends_nothing(self):
        dirs = self.two_signed_in()
        svc = self.start(profile_dirs=dirs, clock=lambda: NOW, choice_file=self.choice)
        self.ask(svc)
        self.assertEqual(self.choice.read_text(), "work\n")
        with mock.patch("agent_tools.console.manager.os.replace", side_effect=OSError("full")):
            result = self.assert_unchanged(svc, lambda: self.exclude(svc, "work"))
        self.assertEqual((result[0], result[2]), (500, b"exclusion failed\n"))
        self.assertEqual(self.choice.read_text(), "work\n")
        self.assertEqual(self.exclusion_rows(), [])
        self.assertEqual(self.exclude(svc, "work")[::2], (204, b""))
        self.assertEqual(self.choice.read_text(), "home\n")
        self.assertEqual(self.exclude(svc, "work", False)[::2], (204, b""))
        self.assertEqual(self.choice.read_text(), "work\n")
        with mock.patch.object(svc.log, "append",
                               side_effect=sqlite3.OperationalError("database is locked")):
            status, _, body = self.exclude(svc, "work")
        self.assertEqual((status, body), (500, b"exclusion failed\n"))
        self.assertEqual(self.choice.read_text(), "work\n")
        self.assertEqual(len(self.exclusion_rows()), 2)
        self.assertEqual(self.ask(svc)[2], b'{"profile":"work"}')

    PIN = "/api/pin"

    def pin(self, svc, profile, pinned=True, **extra):
        return self.post(svc, self.PIN, {"profile": profile, "pinned": pinned}, **extra)

    def pin_rows(self):
        return [r for r in support.log_rows(self.store) if r[2] == "profile.pin"]

    def test_a_pinned_profile_with_room_is_the_choice_until_unpinned(self):
        dirs = self.two_signed_in()
        svc = self.start(profile_dirs=dirs, clock=lambda: NOW, choice_file=self.choice)
        self.assertEqual(self.ask(svc)[2], b'{"profile":"work"}')
        self.assertEqual(self.pin(svc, "home")[::2], (204, b""))
        self.assertEqual(self.choice.read_text(), "home\n")
        self.assertEqual(self.ask(svc)[2], b'{"profile":"home"}')
        self.assertEqual(self.pin(svc, "home", False)[::2], (204, b""))
        self.assertEqual(self.choice.read_text(), "work\n")
        self.assertEqual(self.ask(svc)[2], b'{"profile":"work"}')

    def test_a_pinned_profile_is_the_manager_launch(self):
        dirs = self.two_signed_in()
        launches = support.Launches()
        svc = self.start(profile_dirs=dirs, clock=lambda: NOW, choice_file=self.choice,
                         launcher=launches)
        self.assertEqual(self.pin(svc, "home")[::2], (204, b""))
        self.state(svc)
        self.assertEqual([c.profile for c in launches.calls], ["home"])

    def test_a_pinned_profile_out_of_allowance_falls_back_and_returns(self):
        now = [NOW]
        dirs = self.two_profiles({"work": self.weekly(0.2),
                                  "home": self.five_hour_out(0.9, NOW + 100)})
        self.seed_signins(work="signed_in", home="signed_in")
        svc = self.start(profile_dirs=dirs, clock=lambda: now[0], choice_file=self.choice)
        self.assertEqual(self.pin(svc, "home")[::2], (204, b""))
        self.assertEqual(self.ask(svc)[2], b'{"profile":"work"}')
        self.assertEqual(self.choice.read_text(), "work\n")
        self.assertEqual(len(self.pin_rows()), 1)
        now[0] = NOW + 200
        svc.poll_sessions()
        entries = view_of(svc)["capacity"]["profiles"]
        self.assertEqual(manager.session_profile(
            {"profiles": [{**e, "pinned": False} for e in entries]}, {}), "work")
        home = {e["profile"]: e for e in entries}["home"]
        self.assertEqual((home["state"], home["week_left"]), ("ok", 10))
        self.assertEqual(self.ask(svc)[2], b'{"profile":"home"}')
        self.assertEqual(self.choice.read_text(), "home\n")
        self.assertEqual(len(self.pin_rows()), 1)

    def test_a_signed_out_pinned_profile_falls_back_and_returns_after_sign_in(self):
        now = [NOW]
        dirs = self.two_profiles({"work": self.weekly(0.2), "home": self.weekly(0.6)})
        self.seed_signins(work="signed_in", home="signed_out")

        def reader(one):
            if one.profile == "home" and now[0] == NOW:
                return signin.Status("signed_out", None)
            return signin.Status("signed_in", None)

        svc = self.start(profile_dirs=dirs, clock=lambda: now[0], choice_file=self.choice,
                         signin_reader=reader, probe_dispatch=lambda job: job())
        self.assertEqual(self.pin(svc, "home")[::2], (204, b""))
        self.assertEqual(self.ask(svc)[2], b'{"profile":"work"}')
        self.assertEqual(self.choice.read_text(), "work\n")
        ((_, _, _, _, payload),) = self.pin_rows()
        self.assertEqual(payload, '{"pinned":true,"profile":"home"}')
        now[0] = NOW + 31
        svc.probe_round()
        svc.poll_sessions()
        home = {e["profile"]: e for e in view_of(svc)["capacity"]["profiles"]}["home"]
        self.assertEqual(home["signin"]["state"], "signed_in")
        self.assertEqual(self.ask(svc)[2], b'{"profile":"home"}')
        self.assertEqual(self.choice.read_text(), "home\n")
        self.assertEqual(len(self.pin_rows()), 1)

    def test_pinning_another_profile_moves_the_pin(self):
        dirs = self.two_signed_in()
        svc = self.start(profile_dirs=dirs, clock=lambda: NOW)
        self.assertEqual(self.pin(svc, "work")[::2], (204, b""))
        self.assertEqual(self.pin(svc, "home")[::2], (204, b""))
        self.assertEqual(self.ask(svc)[2], b'{"profile":"home"}')
        self.assertEqual(len(self.pin_rows()), 2)
        for action, expected in (
                (lambda: self.pin(svc, "home"), (409, b"already pinned\n")),
                (lambda: self.pin(svc, "work", False), (409, b"not pinned\n")),
                (lambda: self.pin(svc, "nobody"), (409, b"no such profile\n")),
                (lambda: self.post(svc, self.PIN, b'{"profile":"home","pinned":1}'),
                 (400, b"bad pin\n"))):
            with self.subTest(expected=expected):
                status, _, body = self.assert_unchanged(svc, action)
                self.assertEqual((status, body), expected)
        self.assertEqual(len(self.pin_rows()), 2)

    def test_pinning_an_excluded_profile_is_refused(self):
        dirs = self.two_signed_in()
        svc = self.start(profile_dirs=dirs, clock=lambda: NOW)
        self.assertEqual(self.exclude(svc, "home")[::2], (204, b""))
        status, _, body = self.assert_unchanged(svc, lambda: self.pin(svc, "home"))
        self.assertEqual((status, body), (409, b"excluded; include it first\n"))
        self.assertEqual(self.pin_rows(), [])
        self.assertEqual(self.pin(svc, "work")[::2], (204, b""))
        status, _, body = self.assert_unchanged(svc, lambda: self.exclude(svc, "work"))
        self.assertEqual((status, body), (409, b"pinned; unpin it first\n"))
        self.assertEqual(self.ask(svc)[2], b'{"profile":"work"}')

    def test_a_pin_without_the_origin_or_the_token_is_refused(self):
        dirs = self.two_profiles({"work": self.weekly(0.2)})
        svc = self.start(profile_dirs=dirs, clock=lambda: NOW)
        body = json.dumps({"profile": "home", "pinned": True}).encode()
        port = svc.address[1]
        cases = (
            ({"Origin": f"http://127.0.0.1:{port}", **JSON}, b"token refused\n"),
            ({"X-Console-Token": self.token(), **JSON}, b"origin refused\n"),
            (self.own(svc, **{**JSON, "X-Console-Token": "A" * 43}), b"token refused\n"),
            (self.own(svc, **{**JSON, "Origin": "http://example.test"}), b"origin refused\n"),
        )
        for headers, text in cases:
            with self.subTest(text=text):
                status, _, got = self.assert_unchanged(svc, lambda: support.post_page(
                    svc.address, self.PIN, headers, body))
                self.assertEqual((status, got), (403, text))
        self.assertEqual(self.ask(svc)[2], b'{"profile":"work"}')

    def test_each_accepted_pin_appends_one_row(self):
        dirs = self.two_signed_in()
        svc = self.start(profile_dirs=dirs, clock=lambda: NOW)
        self.assertEqual(self.pin(svc, "home")[::2], (204, b""))
        ((_, _, _, project, payload),) = self.pin_rows()
        self.assertIsNone(project)
        self.assertEqual(payload, '{"pinned":true,"profile":"home"}')
        self.assertEqual(self.pin(svc, "home", False)[::2], (204, b""))
        rows = self.pin_rows()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1][4], '{"pinned":false,"profile":"home"}')

    def test_a_pin_survives_a_restart_and_the_retention_pass(self):
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

            def readings():
                return [(capacity.READING, None, {"profile": n, **self.weekly(u)})
                        for n, u in (("work", 0.2), ("home", 0.6))]

            at(0, signin.entry("work", signin.Status("signed_in", None)),
               signin.entry("home", signin.Status("signed_in", None)),
               *readings(), pin.entry("work", True), ("old", None, {}))
            at(1, pin.entry("home", True))
        finally:
            log.close()
        now[0] = NOW + 50 * day
        svc = self.start(profile_dirs=dirs, clock=lambda: now[0], log_clock=stamp)
        self.assertEqual(self.ask(svc)[2], b'{"profile":"home"}')
        now[0] = NOW + 95 * day
        self.assertGreater(svc.retain(), 0)
        ((_, _, _, _, payload),) = self.pin_rows()
        self.assertEqual(payload, '{"pinned":true,"profile":"home"}')
        svc.close()
        log = EventLog(self.store, clock=stamp)
        try:
            log.append(readings())
        finally:
            log.close()
        again = self.start(profile_dirs=dirs, clock=lambda: now[0], log_clock=stamp)
        self.assertEqual(self.ask(again)[2], b'{"profile":"home"}')

    def test_a_pin_whose_choice_file_cannot_be_written_appends_nothing(self):
        dirs = self.two_signed_in()
        svc = self.start(profile_dirs=dirs, clock=lambda: NOW, choice_file=self.choice)
        self.ask(svc)
        self.assertEqual(self.choice.read_text(), "work\n")
        with mock.patch("agent_tools.console.manager.os.replace", side_effect=OSError("full")):
            result = self.assert_unchanged(svc, lambda: self.pin(svc, "home"))
        self.assertEqual((result[0], result[2]), (500, b"pin failed\n"))
        self.assertEqual(self.choice.read_text(), "work\n")
        self.assertEqual(self.pin_rows(), [])
        self.assertEqual(self.pin(svc, "home")[::2], (204, b""))
        self.assertEqual(self.choice.read_text(), "home\n")
        self.assertEqual(self.pin(svc, "home", False)[::2], (204, b""))
        self.assertEqual(self.choice.read_text(), "work\n")
        with mock.patch.object(svc.log, "append",
                               side_effect=sqlite3.OperationalError("database is locked")):
            status, _, body = self.pin(svc, "home")
        self.assertEqual((status, body), (500, b"pin failed\n"))
        self.assertEqual(self.choice.read_text(), "work\n")
        self.assertEqual(len(self.pin_rows()), 2)
        self.assertEqual(self.ask(svc)[2], b'{"profile":"work"}')

    def test_the_view_says_when_the_pin_is_not_in_effect(self):
        dirs = self.two_profiles({"work": self.weekly(0.2), "home": self.exhausted(FAR)})
        self.seed_signins(work="signed_in", home="signed_in")
        svc = self.start(profile_dirs=dirs, clock=lambda: NOW, choice_file=self.choice)
        self.assertIsNone(view_of(svc)["pin"])
        self.assertEqual(self.pin(svc, "home")[::2], (204, b""))
        self.assertEqual(view_of(svc)["pin"], {
            "profile": "home", "in_effect": False, "reason": "out of allowance",
            "until": datetime.fromtimestamp(FAR, timezone.utc).isoformat(), "instead": "work"})
        self.assertEqual({e["profile"]: e["pinned"] for e in view_of(svc)["capacity"]["profiles"]},
                         {"home": True, "work": False})
        self.assertEqual(self.pin(svc, "work")[::2], (204, b""))
        self.assertEqual(view_of(svc)["pin"], {
            "profile": "work", "in_effect": True, "reason": None, "until": None, "instead": None})
        self.assertEqual(self.pin(svc, "work", False)[::2], (204, b""))
        self.assertIsNone(view_of(svc)["pin"])

    def test_a_launch_under_the_pin_is_kept_after_unpinning(self):
        dirs = self.two_signed_in()
        launches = support.Launches()
        svc = self.start(profile_dirs=dirs, clock=lambda: NOW, choice_file=self.choice,
                         launcher=launches)
        self.assertEqual(view_of(svc)["pin_launches"], [])
        self.assertEqual(self.pin(svc, "home")[::2], (204, b""))
        self.state(svc)
        self.assertEqual([c.profile for c in launches.calls], ["home"])
        self.assertEqual(self.manager_rows()[-1][2], "manager.started")
        self.assertEqual(json.loads(self.manager_rows()[-1][4])["profile"], "home")
        self.assertEqual(self.pin(svc, "home", False)[::2], (204, b""))
        self.assertIsNone(view_of(svc)["pin"])
        self.assertEqual(view_of(svc)["pin_launches"], ["home"])
        svc.close()
        again = self.start(profile_dirs=dirs, clock=lambda: NOW, choice_file=self.choice,
                           launcher=launches)
        self.assertEqual(view_of(again)["pin_launches"], ["home"])

    def prepare_then_exclude(self, svc, queue, *profiles):
        """Run the queued launch with each of `profiles` excluded just after the lock that prepared it is released."""
        def exclude_all():
            for profile in profiles:
                self.assertEqual(self.exclude(svc, profile)[::2], (204, b""))

        self.prepare_then(svc, queue, exclude_all)

    def prepare_then(self, svc, queue, act):
        """Run the queued launch with `act()` called just after the lock that prepared it is released."""
        prepared = svc._prepared_launch
        lock = svc._ingest
        state = {"prepared": False}

        class ReleaseHook:
            def __enter__(hook):
                lock.acquire()

            def __exit__(hook, *exc):
                lock.release()
                if state["prepared"]:
                    state["prepared"] = False
                    act()

        def prepared_then_flagged(*args):
            launch = prepared(*args)
            state["prepared"] = True
            return launch

        with mock.patch.object(svc, "_prepared_launch", side_effect=prepared_then_flagged), \
                mock.patch.object(svc, "_ingest", ReleaseHook()):
            queue.run_next()

    def test_a_launch_prepared_before_an_exclusion_is_not_started_under_the_excluded_profile(self):
        dirs = self.two_signed_in()
        launches = support.Launches()
        queue = support.Queued()
        svc = self.start(profile_dirs=dirs, clock=lambda: NOW, choice_file=self.choice,
                         launcher=launches, dispatch=queue)
        self.state(svc)
        self.prepare_then_exclude(svc, queue, "work")
        self.assertEqual([c.profile for c in launches.calls], ["home"])
        _, _, kind, _, payload = self.manager_rows()[-1]
        self.assertEqual((kind, json.loads(payload)["profile"]), ("manager.started", "home"))

    def work_dir(self):
        return self.store.parent.parent / "accounts" / "profiles" / "work"

    def test_a_launch_prepared_before_a_removal_is_not_started_under_the_removed_profile(self):
        dirs = self.two_signed_in()
        launches = support.Launches()
        queue = support.Queued()
        svc = self.start(profile_dirs=dirs, clock=lambda: NOW, choice_file=self.choice,
                         launcher=launches, dispatch=queue)
        self.state(svc)
        self.prepare_then(svc, queue, lambda: shutil.rmtree(self.work_dir()))
        self.assertEqual([c.profile for c in launches.calls], ["home"])
        _, _, kind, _, payload = self.manager_rows()[-1]
        self.assertEqual((kind, json.loads(payload)["profile"]), ("manager.started", "home"))

    def test_a_launch_prepared_before_a_removal_began_is_not_started_under_the_profile_being_removed(self):
        dirs = self.two_signed_in()
        launches = support.Launches()
        queue = support.Queued()
        entered = threading.Event()
        release = threading.Event()

        def signer_out(one):
            entered.set()
            release.wait(10)
        svc = self.start(profile_dirs=dirs, clock=lambda: NOW, choice_file=self.choice,
                         launcher=launches, dispatch=queue,
                         signin_reader=lambda one: signin.Status("signed_in", None),
                         account_remover=lambda name: shutil.rmtree(self.work_dir()),
                         signer_out=signer_out)
        self.state(svc)
        remover = threading.Thread(target=lambda: svc.remove_account("work", "work"))

        def begin_removal():
            remover.start()
            self.assertTrue(entered.wait(5))
        self.prepare_then(svc, queue, begin_removal)
        release.set()
        remover.join(10)
        self.assertEqual([c.profile for c in launches.calls], ["home"])
        _, _, kind, _, payload = self.manager_rows()[-1]
        self.assertEqual((kind, json.loads(payload)["profile"]), ("manager.started", "home"))

    def test_a_launch_prepared_before_a_pin_is_started_under_the_pin(self):
        dirs = self.two_signed_in()
        launches = support.Launches()
        queue = support.Queued()
        svc = self.start(profile_dirs=dirs, clock=lambda: NOW, choice_file=self.choice,
                         launcher=launches, dispatch=queue)
        self.state(svc)
        self.prepare_then(svc, queue, lambda: self.assertEqual(
            self.pin(svc, "home")[::2], (204, b"")))
        self.assertEqual(self.choice.read_text(), "home\n")
        self.assertEqual([c.profile for c in launches.calls], ["home"])
        _, _, kind, _, payload = self.manager_rows()[-1]
        self.assertEqual((kind, json.loads(payload)["profile"]), ("manager.started", "home"))

    def test_a_launch_prepared_under_a_pin_that_is_lifted_is_started_under_the_choice(self):
        dirs = self.two_signed_in()
        launches = support.Launches()
        queue = support.Queued()
        svc = self.start(profile_dirs=dirs, clock=lambda: NOW, choice_file=self.choice,
                         launcher=launches, dispatch=queue)
        self.assertEqual(self.pin(svc, "home")[::2], (204, b""))
        self.state(svc)
        self.prepare_then(svc, queue, lambda: self.assertEqual(
            self.pin(svc, "home", False)[::2], (204, b"")))
        self.assertEqual(self.choice.read_text(), "work\n")
        self.assertEqual([c.profile for c in launches.calls], ["work"])

    def test_a_launch_prepared_before_the_last_profile_was_excluded_waits(self):
        dirs = self.two_signed_in()
        launches = support.Launches()
        queue = support.Queued()
        svc = self.start(profile_dirs=dirs, clock=lambda: NOW, choice_file=self.choice,
                         launcher=launches, dispatch=queue)
        self.state(svc)
        self.prepare_then_exclude(svc, queue, "work", "home")
        self.assertEqual(launches.calls, [])
        _, _, kind, _, payload = support.log_rows(self.store)[-1]
        self.assertEqual(kind, "manager.waiting")
        self.assertIsNone(json.loads(payload)["until"])
        self.assertEqual(self.manager_rows()[-1][2], "manager.waiting")

    def test_the_excluded_route_answers_the_excluded_profiles_in_name_order(self):
        dirs = self.two_signed_in()
        svc = self.start(profile_dirs=dirs, clock=lambda: NOW, choice_file=self.choice)
        route = "/api/excluded"
        self.assertEqual(support.request(svc.address, "GET", route)[::2],
                         (200, b'{"excluded":[]}'))
        self.assertEqual(self.exclude(svc, "work")[::2], (204, b""))
        self.assertEqual(self.exclude(svc, "home")[::2], (204, b""))
        self.assertEqual(support.request(svc.address, "GET", route)[::2],
                         (200, b'{"excluded":["home","work"]}'))
        self.assertEqual(
            support.request(svc.address, "GET", route, host="example.com:80")[0], 403)


class ColleagueAccountLaunchTest(GuestCase):
    """The manager launch follows the colleague-account rule (#1344, ADR-console-087 D1)."""

    ACTOR = guest.GuestActor(COLLEAGUE, TAILNET)

    def start_pool(self, work_used, colleague_used, waiting=False, done=False, **kwargs):
        """The owner's `work` and the colleague's `colleague-1`, both signed in, with the given weekly use."""
        self.seed()
        base = self.store.parent.parent / "accounts" / "profiles"
        dirs = []
        for name in ("work", "colleague-1"):
            (base / name).mkdir(parents=True, exist_ok=True)
            dirs.append(base / name)
        rows = [(capacity.READING, None, {"profile": name, **ManagerServiceTest.weekly(used)})
                for name, used in (("work", work_used), ("colleague-1", colleague_used))]
        rows += [signin.entry(name, signin.Status("signed_in", None))
                 for name in ("work", "colleague-1")]
        rows.append(account_add.added("colleague-1", COLLEAGUE))
        if waiting:
            rows += self.waiting_rows()
        if done:
            sid = "w" * 16
            rows += [(BRIEF_SENT, "owner/p01", {"sprint_id": sid, "version": 1, "goal": "wait",
                                                "brief": PARTS}),
                     (BRIEF_APPROVED, "owner/p01", {"sprint_id": sid, "version": 1, "goal": "wait"})]
            rows.append((SPRINT_REPORTED, "owner/p01", {
                "sprint_id": "w" * 16, "goal": "wait", "report": {**REPORT, "phase": "done"}}))
        self.append(rows)
        self.launches = support.Launches()
        return self.start(profile_dirs=dirs, clock=lambda: NOW, launcher=self.launches,
                          session_poll_seconds=3600, **kwargs)

    @staticmethod
    def waiting_rows():
        return [(GOAL_STATED, "owner/p01", {"sprint_id": "w" * 16, "goal": "wait", "by": COLLEAGUE}),
                (MANAGER_WAITING, "owner/p01", {"sprint_id": "w" * 16, "until": None})]

    def profile_of_next(self, svc, by=None):
        before = len(self.launches.calls)
        svc.state_goal("owner/p01", "make the importer resumable", by=by)
        (call,) = self.launches.calls[before:]
        return call.profile

    def test_his_sprint_runs_on_his_account_though_an_owner_account_has_more_room(self):
        svc = self.start_pool(0.1, 0.7)
        self.assertEqual(self.profile_of_next(svc, self.ACTOR), "colleague-1")
        self.assertEqual(self.profile_of_next(svc), "work")

    def test_the_owners_sprint_takes_his_account_when_it_has_most_room_and_none_of_his_waits(self):
        svc = self.start_pool(0.7, 0.1)
        self.assertEqual(self.profile_of_next(svc), "colleague-1")

    def test_the_owners_sprint_leaves_his_account_while_a_sprint_of_his_waits(self):
        svc = self.start_pool(0.7, 0.1, waiting=True)
        self.assertEqual(self.profile_of_next(svc), "work")
        self.assertEqual(self.profile_of_next(svc, self.ACTOR), "colleague-1")

    def test_a_sprint_that_ended_through_a_done_report_no_longer_keeps_his_account(self):
        svc = self.start_pool(0.7, 0.1, waiting=True, done=True)
        self.assertEqual(self.profile_of_next(svc), "colleague-1")

    def launch_after(self, act):
        """An owner's sprint prepared on the colleague's account, then `act(svc)` under the lock before it launches."""
        queue = support.Queued()
        svc = self.start_pool(0.9, 0.1, dispatch=queue)
        svc.state_goal("owner/p01", "make the importer resumable")
        def under_lock():
            with svc._ingest:
                act(svc)
        ProfileChoiceServiceTest.prepare_then(self, svc, queue, under_lock)
        return [call.profile for call in self.launches.calls]

    def test_a_launch_prepared_on_his_account_is_chosen_again_when_it_runs_out_meanwhile(self):
        def run_out(svc):
            svc._apply(svc.log.append([(capacity.READING, None, {
                "profile": "colleague-1", **ManagerServiceTest.exhausted(FAR)})]))
        self.assertEqual(self.launch_after(run_out), ["work"])

    def test_a_launch_prepared_on_his_account_is_chosen_again_when_a_sprint_of_his_waits_meanwhile(self):
        def reserve(svc):
            svc._apply(svc.log.append(self.waiting_rows()))
        self.assertEqual(self.launch_after(reserve), ["work"])

    def test_a_launch_prepared_on_his_account_stays_while_it_has_room(self):
        self.assertEqual(self.launch_after(lambda svc: None), ["colleague-1"])

PERMIT = "/api/permit"
SLUG = "o/r"
MERGE = f"gh pr merge 7 --repo {SLUG} --merge --match-head-commit {SHA} --delete-branch"
ROOT = "/srv/p01"
RELEASE_RUN = (f"release transaction run --repo-root {ROOT} --commit {'a' * 40} --version v1.2.0 "
               "--title 'v1.2.0 notes' --notes-file /tmp/n --confirm publish:0123456789ab")


def issues_report(*numbers):
    return {**REPORT, "issues": [{"issue": n, "stage": "building"} for n in numbers], "inbox": []}


class PermitCase(Case):
    """A started, approved sprint of a registered project, its manager session and a fake forge (#1377)."""

    def boot(self, **kwargs):
        """A fresh console (a new store) with one approved sprint reporting issue 12, run by `s-1`."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.store = root / "state/console/events.sqlite3"
        self.registry = root / "state/fleet/registry.json"
        support.write_registry(self.registry, support.entries(2))
        self.fake = FakeForge()
        kwargs.setdefault("permit_forge", self.fake.forge())
        svc = self.svc = self.start(
            launcher=support.Launches(), session_poll_seconds=3600, slug_of=lambda root: SLUG,
            merge_binding_of=lambda root: ("merge", True),
            branch_pattern_of=lambda root: "issue-<num>-<slug>", **kwargs)
        sid = self.sprint(svc, "make the importer resumable")
        self.seen(svc, sid, "s-1")
        svc.send_report(sid, self.secret(sid), issues_report(12))
        self.deliver(svc, "s-1", 12)
        return svc, sid

    def secret(self, sid):
        return (self.store.parent / "sprint-secrets" / sid).read_text().removesuffix("\n")

    def sprint(self, svc, goal):
        sid = svc.state_goal("owner/p01", goal)
        svc.send_brief(sid, self.secret(sid), PARTS)
        svc.approve_brief("owner/p01", sid, 1)
        return sid

    def seen(self, svc, sid, session_id):
        with svc._ingest:
            svc._apply(svc.log.append([(SESSION_SEEN, "owner/p01", {
                "name": manager.session_name("owner/p01", sid), "session_id": session_id})]))

    def deliver(self, svc, session_id, *numbers, run="r-1"):
        state = deliveries.DeliveryState(
            session_id, run, 1, tuple(deliveries.IssueStage(n, "building") for n in numbers))
        self.append(svc, DELIVERY_SEEN, deliveries.seen_payload(state))

    def clean_up(self, svc, session_id, run="r-1"):
        self.append(svc, DELIVERY_GONE, {"session_id": session_id, "run_id": run})

    def append(self, svc, kind, payload):
        with svc._ingest:
            svc._apply(svc.log.append([(kind, "owner/p01", payload)]))

    def rows(self, kind):
        return [json.loads(row[4]) for row in support.log_rows(self.store) if row[2] == kind]

    def judge(self, svc, sid, command, session="s-1", call="t-1"):
        return svc.permit(sid, self.secret(sid), session, call, command)


class PermitServiceTest(PermitCase):
    def test_the_sprints_manager_is_allowed_the_plain_release_run_and_refused_abandon(self):
        svc, sid = self.boot()
        verdict = self.judge(svc, sid, RELEASE_RUN)
        self.assertEqual((verdict.decision, verdict.verb), ("allow", "release"))
        (row,) = self.rows("permit.judged")
        self.assertEqual((row["verb"], row["decision"], row["reason"], row["target"]),
                         ("release", "allow", "", {"commit": "a" * 40, "version": "v1.2.0"}))
        other = self.judge(svc, sid, RELEASE_RUN, session="s-2", call="t-2")
        self.assertEqual((other.decision, other.reason), ("deny", permit.NOT_MANAGER))
        abandon = self.judge(svc, sid, "release transaction abandon --repo-root r", call="t-3")
        self.assertEqual((abandon.decision, abandon.verb, abandon.reason),
                         ("deny", "release-abandon", permit.NO_ABANDON))
        self.assertEqual(3, len(self.rows("permit.judged")))
        self.assertEqual({"verb": "release-abandon", "decision": "deny", "reason": permit.NO_ABANDON,
                          "target": {}},
                         {key: self.rows("permit.judged")[2][key]
                          for key in ("verb", "decision", "reason", "target")})
        before = len(self.rows("permit.judged"))
        piped = "git log -1 --format=release%x20transaction%x20run%x20--candidate%x20X | sh"
        verdict = self.judge(svc, sid, piped, call="t-4")
        self.assertEqual((verdict.decision, verdict.reason, verdict.verb), (None, "", None))
        self.assertEqual(before, len(self.rows("permit.judged")))

    def test_the_sprints_delivered_reported_pull_request_merges(self):
        svc, sid = self.boot()
        verdict = self.judge(svc, sid, MERGE)
        self.assertEqual((verdict.decision, verdict.verb, dict(verdict.target)),
                         ("allow", "merge", {"pr": 7, "head": SHA}))
        (row,) = self.rows("permit.judged")
        self.assertEqual(row, {"sprint_id": sid, "session_id": "s-1", "tool_use_id": "t-1", "repo": SLUG,
                               "verb": "merge", "decision": "allow", "reason": "",
                               "target": {"pr": 7, "head": SHA}})

    def test_a_merge_behind_the_documented_prefix_is_allowed_and_lands(self):
        svc, sid = self.boot()
        command = "env -u GITHUB_TOKEN -u GH_TOKEN " + MERGE
        verdict = self.judge(svc, sid, command)
        self.assertEqual(verdict.decision, permit.ALLOW)
        self.assertIs(svc.permit_landed(sid, self.secret(sid), "s-1", "t-1", command), True)
        (landed,) = self.rows("permit.landed")
        self.assertEqual(landed["target"], {"pr": 7, "head": SHA})

    def test_a_reported_issue_no_manager_delivery_carries_is_refused(self):
        svc, sid = self.boot()
        svc.send_report(sid, self.secret(sid), issues_report(12, 40))
        self.fake.pr = {**self.fake.pr, "branch": "issue-40-x"}
        self.deliver(svc, "s-other", 40, run="r-2")
        verdict = self.judge(svc, sid, MERGE)
        self.assertEqual((verdict.decision, verdict.reason),
                         ("deny", permit.NOT_OWN_PR.format(pr=7)))

    def test_an_issue_another_open_sprint_reports_is_refused(self):
        svc, sid = self.boot()
        other = self.sprint(svc, "make the exporter resumable")
        svc.send_report(other, self.secret(other), issues_report(12))
        verdict = self.judge(svc, sid, MERGE)
        self.assertEqual((verdict.decision, verdict.reason),
                         ("deny", permit.SHARED_ISSUE.format(issue=12)))

    def test_another_session_is_refused(self):
        svc, sid = self.boot()
        for session in ("s-2", ""):
            with self.subTest(session=session):
                verdict = self.judge(svc, sid, MERGE, session)
                self.assertEqual((verdict.decision, verdict.reason), ("deny", permit.NOT_MANAGER))
        self.assertEqual(self.fake.calls, [])

    def test_a_manager_not_yet_seen_is_refused(self):
        svc, sid = self.boot()
        other = self.sprint(svc, "make the exporter resumable")
        verdict = self.judge(svc, other, MERGE)
        self.assertEqual((verdict.decision, verdict.reason), ("deny", permit.NOT_MANAGER))

    def test_a_sprint_that_is_not_running_is_refused(self):
        def stop(svc, sid):
            svc.stop_sprint("owner/p01", sid)

        def close(svc, sid):
            svc.send_closing(sid, self.secret(sid), CLOSING)

        def redraft(svc, sid):
            svc.send_brief(sid, self.secret(sid), {**PARTS, "title": "Importer resumes, again"})

        for name, act in (("stop requested", stop), ("closed", close), ("second brief", redraft)):
            with self.subTest(name):
                svc, sid = self.boot()
                act(svc, sid)
                verdict = self.judge(svc, sid, MERGE)
                self.assertEqual((verdict.decision, verdict.reason), ("deny", permit.NOT_ACTIVE))
                self.assertEqual(self.rows("permit.judged")[-1]["decision"], "deny")
                self.assertEqual(self.fake.calls, [])

    def test_a_sprint_that_changes_during_the_forge_read_is_refused(self):
        def stop(svc, sid):
            self.append(svc, SPRINT_STOP_REQUESTED, {"sprint_id": sid, "goal": "g"})

        def restart(svc, sid):
            self.append(svc, MANAGER_STARTED, {
                "profile": "work", "session_name": manager.session_name("owner/p01", sid),
                "sprint_id": sid})

        def share(svc, sid):
            other = self.sprint(svc, "make the exporter resumable")
            svc.send_report(other, self.secret(other), issues_report(12))

        for name, act in (("stop", stop), ("restart", restart), ("shared issue", share)):
            with self.subTest(name):
                svc, sid = self.boot()
                read = self.fake.read_pr

                def moving(slug, number, read=read, act=act, svc=svc, sid=sid):
                    found = read(slug, number)
                    act(svc, sid)
                    return found

                svc._permit_forge = permit.Forge(moving, self.fake.read_run, self.fake.read_required)
                verdict = self.judge(svc, sid, MERGE)
                self.assertEqual((verdict.decision, verdict.reason), ("deny", permit.MOVED))
                last = self.rows("permit.judged")[-1]
                self.assertEqual((last["decision"], last["reason"]), ("deny", permit.MOVED))

    def test_the_forge_is_read_once_for_both_judgements(self):
        svc, sid = self.boot()
        self.assertEqual(self.judge(svc, sid, MERGE).decision, "allow")
        self.assertEqual(self.fake.calls, [("pr", SLUG, 7)])

    def test_an_unrelated_command_is_not_judged_or_logged(self):
        svc, sid = self.boot()
        before = support.log_rows(self.store)
        verdict = self.judge(svc, sid, "git status")
        self.assertIsNone(verdict.decision)
        self.assertEqual(support.log_rows(self.store), before)
        self.assertEqual(self.rows("permit.judged"), [])

    def test_a_wrong_secret_is_refused(self):
        svc, sid = self.boot()
        with self.assertRaises(sprints.SecretRefused):
            svc.permit(sid, "A" * 43, "s-1", "t-1", MERGE)

    def test_a_landed_merge_is_recorded_only_after_its_allow(self):
        svc, sid = self.boot()
        secret = self.secret(sid)
        self.assertFalse(svc.permit_landed(sid, secret, "s-1", "t-1", MERGE))
        self.assertEqual(self.rows("permit.landed"), [])
        self.assertEqual(self.judge(svc, sid, MERGE).decision, "allow")
        for session, call, command in (("s-2", "t-1", MERGE), ("s-1", "t-1", MERGE + " --admin"),
                                       ("s-1", "t-1", MERGE.replace(" 7 ", " 8 ")),
                                       ("s-1", "t-2", MERGE)):
            with self.subTest(session=session, call=call, command=command[-20:]):
                self.assertFalse(svc.permit_landed(sid, secret, session, call, command))
        self.assertEqual(self.rows("permit.landed"), [])
        self.assertTrue(svc.permit_landed(sid, secret, "s-1", "t-1", MERGE))
        self.assertEqual(self.rows("permit.landed"), [{
            "sprint_id": sid, "session_id": "s-1", "tool_use_id": "t-1", "repo": SLUG, "verb": "merge",
            "target": {"pr": 7, "head": SHA}}])

    def test_a_landing_after_thirty_minutes_is_not_recorded(self):
        now = [NOW]
        svc, sid = self.boot(clock=lambda: now[0])
        self.assertEqual(self.judge(svc, sid, MERGE).decision, "allow")
        now[0] += 30 * 60
        self.assertTrue(svc.permit_landed(sid, self.secret(sid), "s-1", "t-1", MERGE))
        now[0] += 1
        self.assertFalse(svc.permit_landed(sid, self.secret(sid), "s-1", "t-1", MERGE))
        self.assertEqual(len(self.rows("permit.landed")), 1)

    def test_a_denied_merge_is_never_recorded_as_landed(self):
        svc, sid = self.boot()
        self.fake.pr = {**self.fake.pr, "branch": "issue-99-x"}
        self.assertEqual(self.judge(svc, sid, MERGE).decision, "deny")
        self.assertFalse(svc.permit_landed(sid, self.secret(sid), "s-1", "t-1", MERGE))

    def test_a_sprint_a_done_report_ended_refuses_a_merge(self):
        svc, sid = self.boot()
        self.assertEqual(self.judge(svc, sid, MERGE).decision, "allow")
        svc.send_report(sid, self.secret(sid), {**issues_report(12), "phase": "done"})
        self.assertIsNotNone(sprints.ended_at(svc._sprints[sid]))
        verdict = self.judge(svc, sid, MERGE)
        self.assertEqual((verdict.decision, verdict.reason), ("deny", permit.NOT_ACTIVE))

    def test_a_merge_after_the_delivery_run_was_cleaned_up_is_still_allowed(self):
        svc, sid = self.boot()
        self.clean_up(svc, "s-1")
        self.assertEqual(svc._deliveries, {})
        self.assertEqual(self.judge(svc, sid, MERGE).decision, "allow")

    def post(self, svc, body, **headers):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        return support.post_page(svc.address, PERMIT, {**JSON, **headers}, data)

    def request(self, sid, **change):
        return {"sprint_id": sid, "secret": self.secret(sid), "phase": "judge",
                "session_id": "s-1", "tool_use_id": "t-1", "command": MERGE, **change}

    def test_the_permit_route_answers_a_manager_only(self):
        svc, sid = self.boot()
        status, _, body = self.post(svc, self.request(sid))
        self.assertEqual((status, json.loads(body)), (200, {"decision": "allow", "reason": ""}))
        status, _, body = self.post(svc, self.request(sid, command="git status"))
        self.assertEqual((status, json.loads(body)), (200, {"decision": None, "reason": ""}))
        status, _, body = self.post(svc, self.request(sid, phase="landed"))
        self.assertEqual((status, json.loads(body)), (200, {"recorded": True}))
        status, _, body = self.post(svc, self.request(sid, secret="A" * 43))
        self.assertEqual((status, body), (403, sprints.SECRET_REFUSED.encode() + b"\n"))
        status, _, body = self.post(svc, self.request(sid, sprint_id="e" * 16))
        self.assertEqual((status, body), (409, sprints.NOT_OPEN.encode() + b"\n"))
        duplicated = json.dumps(self.request(sid)).replace(
            '"phase": "judge"', '"phase": "judge", "phase": "judge"').encode()
        bad = [duplicated, self.request(sid, phase="other"), {**self.request(sid), "extra": 1},
               self.request(sid, session_id=""), self.request(sid, session_id="x" * 129),
               self.request(sid, tool_use_id=""), self.request(sid, tool_use_id="x" * 129),
               {k: v for k, v in self.request(sid).items() if k != "tool_use_id"},
               self.request(sid, command="x" * 8193), self.request(sid, command=3), b"not json"]
        for body in bad:
            with self.subTest(body=str(body)[:60]):
                status, _, text = self.post(svc, body)
                self.assertEqual((status, text), (400, b"bad permit\n"))
        status, _, text = self.post(svc, b" " * 16385)
        self.assertEqual((status, text), (413, b"too large\n"))
        with mock.patch.object(svc, "permit", side_effect=RuntimeError("boom")), \
                contextlib.redirect_stderr(io.StringIO()):
            status, _, text = self.post(svc, self.request(sid))
        self.assertEqual((status, text), (500, b"permit failed\n"))

    def test_the_permit_route_is_manager_only(self):
        self.assertIn(service.PERMIT_PATH, service.MANAGER_WRITES)
        self.assertIn(service.PERMIT_PATH, service.OWNER_ONLY)
        self.assertIn(service.PERMIT_PATH, service.ROUTES)


class PermitHookTest(PermitCase):
    """The hook commands the settings carry, run as the client runs them: `sh -c <command>` with the hook input on stdin."""

    def hook(self, svc, sid, command, hook_input):
        bin_dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, bin_dir)
        shim = bin_dir / "sprint"
        shim.write_text("#!/bin/sh\nexec python3 -m agent_tools.console.sprint \"$@\" "
                        f"--port {svc.address[1]}\n")
        shim.chmod(0o755)
        env = {"PATH": f"{bin_dir}:{os.environ['PATH']}",
               "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "python"),
               manager.ID_ENV: sid, manager.SECRET_ENV: self.secret(sid)}
        done = subprocess.run(["sh", "-c", command], input=json.dumps(hook_input).encode(),
                              env=env, capture_output=True, timeout=30)
        self.assertEqual((done.returncode, done.stderr), (0, b""))
        return done.stdout.decode()

    def test_the_generated_hook_allows_only_the_granted_commands(self):
        svc, sid = self.boot()
        hooks = manager.settings_document({}, permission.FALLBACK)["hooks"]
        [pre] = hooks["PreToolUse"][0]["hooks"]
        [post] = hooks["PostToolUse"][0]["hooks"]

        def call(command):
            return {"session_id": "s-1", "tool_use_id": "t-1", "tool_name": "Bash",
                    "tool_input": {"command": command}}

        out = self.hook(svc, sid, pre["command"], call(MERGE))
        self.assertEqual(json.loads(out), {"hookSpecificOutput": {
            "hookEventName": "PreToolUse", "permissionDecision": "allow",
            "permissionDecisionReason": ""}})
        self.assertEqual([row["decision"] for row in self.rows("permit.judged")], ["allow"])
        self.fake.pr = {**self.fake.pr, "branch": "issue-99-x"}
        out = self.hook(svc, sid, pre["command"], call(MERGE.replace(" 7 ", " 8 ")))
        deny = json.loads(out)["hookSpecificOutput"]
        self.assertEqual((deny["hookEventName"], deny["permissionDecision"]), ("PreToolUse", "deny"))
        self.assertEqual([row["decision"] for row in self.rows("permit.judged")], ["allow", "deny"])
        self.assertEqual(self.hook(svc, sid, pre["command"], call("git status")), "")
        self.assertEqual(len(self.rows("permit.judged")), 2)
        self.assertEqual(self.rows("permit.landed"), [])
        self.assertEqual(self.hook(svc, sid, post["command"], call(MERGE)), "")
        self.assertEqual(len(self.rows("permit.landed")), 1)


class PermitWireTest(PermitCase):
    def test_the_command_and_the_route_agree(self):
        svc, sid = self.boot()
        hook = {"session_id": "s-1", "tool_use_id": "t-1", "tool_name": "Bash",
                "tool_input": {"command": MERGE}}
        out = io.StringIO()
        with mock.patch.dict(os.environ, {manager.ID_ENV: sid, manager.SECRET_ENV: self.secret(sid)}), \
                mock.patch.object(sys, "stdin", io.StringIO(json.dumps(hook))), \
                contextlib.redirect_stdout(out):
            code = sprint.main(["permit", "--port", str(svc.address[1])])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out.getvalue()), {"hookSpecificOutput": {
            "hookEventName": "PreToolUse", "permissionDecision": "allow",
            "permissionDecisionReason": ""}})
        self.assertEqual(len(out.getvalue().splitlines()), 1)
        out = io.StringIO()
        with mock.patch.dict(os.environ, {manager.ID_ENV: sid, manager.SECRET_ENV: self.secret(sid)}), \
                mock.patch.object(sys, "stdin", io.StringIO(json.dumps(hook))), \
                contextlib.redirect_stdout(out):
            code = sprint.main(["permit", "--landed", "--port", str(svc.address[1])])
        self.assertEqual((code, out.getvalue()), (0, ""))
        self.assertEqual(len(self.rows("permit.landed")), 1)


if __name__ == "__main__":
    unittest.main()
