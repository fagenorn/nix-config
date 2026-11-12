"""The service brings back a manager that is gone while its sprint has work (#893).

Run: just agent-workflow-tests
"""
import io
import json
import sys
import threading
from datetime import datetime, timezone
from unittest import mock

from agent_tools.console import capacity, manager, nudge, revive, service, sessions, sprints

from . import console_test_support as support
from .test_console_messages import GOAL_TEXT, PARTS
from .test_console_reports import REPORT
from .test_console_writes import Case

T0 = 1_800_000_000.0
FAR = 1_900_000_000
GOAL = GOAL_TEXT


class ReviveCase(Case):
    """The set-up and helpers of the bring-back suites; it holds no test."""

    def setUp(self):
        super().setUp()
        support.write_registry(self.registry, support.entries(2))
        self.queued = support.Queued()
        self.launches = support.Launches()
        self.nudges = []
        self.outcomes = []
        self.during = None
        self.listed = {}
        self.now = [T0]
        stderr = mock.patch.object(sys, "stderr", io.StringIO())
        self.stderr = stderr.start()
        self.addCleanup(stderr.stop)

    def log_clock(self):
        return datetime.fromtimestamp(self.now[0], timezone.utc).isoformat(timespec="microseconds")

    def nudger(self, sent):
        self.nudges.append(sent)
        if self.during is not None:
            self.during()
        outcome = self.outcomes.pop(0) if self.outcomes else None
        if outcome is not None:
            raise nudge.NudgeFailed(outcome)

    def begin(self, **overrides):
        options = dict(
            launcher=self.launches, bound_profile_of=lambda root: "work",
            dispatch=self.queued, nudger=self.nudger, listing=lambda: dict(self.listed),
            clock=lambda: self.now[0], log_clock=self.log_clock, session_poll_seconds=3600)
        return self.start(**{**options, **overrides})

    def name(self, sid):
        return manager.session_name("owner/p01", sid)

    def secret(self, sid):
        return (self.store.parent / "sprint-secrets" / sid).read_text().removesuffix("\n")

    def append(self, svc, rows):
        with svc._ingest:
            svc._apply(svc.log.append(rows))

    def seen(self, svc, sid):
        self.append(svc, [("session.seen", "owner/p01", {
            "session_id": "s-1", "cwd": "/srv/p01", "repo": "/srv/p01", "state": "idle",
            "name": self.name(sid)})])

    def gone(self, svc):
        self.append(svc, [("session.gone", None, {"session_id": "s-1"})])

    def drain(self):
        while self.queued.jobs:
            self.queued.run_next()

    def on_track(self, svc, seen=True):
        sid = svc.state_goal("owner/p01", GOAL)
        self.queued.run_next()
        if seen:
            self.seen(svc, sid)
        svc.send_brief(sid, self.secret(sid), PARTS)
        svc.approve_brief("owner/p01", sid, 1)
        svc.send_report(sid, self.secret(sid), REPORT)
        self.drain()
        return sid

    def tick(self, svc, seconds):
        self.reserve(svc, seconds)
        self.drain()

    def reserve(self, svc, seconds):
        self.now[0] = T0 + seconds
        svc.revive()

    def revives(self):
        return [n for n in self.nudges if n.route == "revive"]

    def rows(self, kind):
        return [json.loads(row[4]) for row in support.log_rows(self.store) if row[2] == kind]

    def manager_rows(self):
        return [row for row in support.log_rows(self.store) if row[2].startswith("manager.")]

    def listed_now(self, sid):
        self.listed["s-1"] = sessions.Observation(
            "s-1", "/srv/p01", 1, "idle", None, self.name(sid), None)

    def profiles(self, **utilization):
        base = self.store.parent.parent / "accounts" / "profiles"
        dirs = {name: base / name for name in utilization}
        for directory in dirs.values():
            directory.mkdir(parents=True)
        return dirs

    @staticmethod
    def weekly(utilization, reset=FAR):
        return {"http_status": 200, "status": "allowed", "windows": {
            "7d": {"status": "allowed", "utilization": utilization, "reset": reset}}}

    @staticmethod
    def exhausted(reset):
        return {"http_status": 429, "status": "rejected", "windows": {
            "7d": {"status": "rejected", "utilization": 1.0, "reset": reset}}}

    def readings(self, svc, report_of):
        self.append(svc, [(capacity.READING, None, {"profile": profile, **report_of(profile)})
                          for profile in ("work", "home")])


class ReviveServiceTest(ReviveCase):
    def test_a_sprint_with_work_gone_two_minutes_gets_one_wake_with_the_fixed_sentence(self):
        svc = self.begin()
        sid = self.on_track(svc)
        self.tick(svc, 0)
        self.gone(svc)
        self.tick(svc, 119.999)
        self.assertEqual(self.revives(), [])
        self.tick(svc, 120)
        self.assertEqual(self.revives(), [nudge.Nudge(
            sid, "revive", self.name(sid), "s-1", "work", "/srv/p01")])
        self.assertEqual(nudge.nudge_command(self.revives()[0], "linux")[-1], nudge.RESTART_TEXT)
        self.assertEqual(self.rows("manager.woken"), [
            {"sprint_id": sid, "goal": GOAL, "session_id": "s-1", "ok": True}])
        self.tick(svc, 121)
        self.tick(svc, 239)
        self.assertEqual(len(self.revives()), 1)
        self.assertEqual(len(self.rows("manager.woken")), 1)

    def test_a_listed_manager_is_never_woken(self):
        svc = self.begin()
        self.on_track(svc)
        self.tick(svc, 10_000)
        self.assertEqual(self.revives(), [])
        self.assertEqual(self.rows("manager.woken"), [])
        self.assertEqual(len(self.launches.calls), 1)
        self.gone(svc)
        self.tick(svc, 10_119)
        self.assertEqual(self.revives(), [])
        self.tick(svc, 10_120)
        self.assertEqual(len(self.revives()), 1)

    def test_a_closing_done_or_withdrawn_sprint_is_never_brought_back(self):
        for name in ("closing", "done", "withdrawn"):
            with self.subTest(name):
                self.setUp()
                svc = self.begin()
                sid = self.on_track(svc)
                if name == "withdrawn":
                    svc.withdraw_goal("owner/p01", sid)
                else:
                    svc.send_report(sid, self.secret(sid), {**REPORT, "phase": name})
                    self.drain()
                self.gone(svc)
                self.tick(svc, 86_400)
                self.assertEqual(self.revives(), [])
                self.assertEqual(len(self.launches.calls), 1)
                self.assertEqual(self.rows("manager.woken"), [])
                self.assertEqual(self.rows("manager.stalled"), [])

    def test_a_wake_is_not_sent_when_the_fresh_listing_shows_the_manager(self):
        for name in ("listing", "closed"):
            with self.subTest(name):
                self.setUp()
                svc = self.begin()
                sid = self.on_track(svc)
                self.gone(svc)
                self.reserve(svc, 120)
                if name == "listing":
                    self.listed_now(sid)
                else:
                    svc.send_report(sid, self.secret(sid), {**REPORT, "phase": "closing"})
                self.drain()
                self.assertEqual(self.revives(), [])
                self.assertEqual(self.rows("manager.woken"), [])
                self.assertEqual(svc._nudging, set())
                with self.assertRaises(sprints.Refused) as refused:
                    svc.retry_manager("owner/p01", sid)
                self.assertEqual(str(refused.exception), sprints.HAS_MANAGER)

    def test_a_wake_is_not_sent_when_the_sprint_stops_having_work_during_the_listing(self):
        for name in ("closing", "done", "withdrawn"):
            with self.subTest(name):
                self.setUp()
                changes = []
                svc = self.begin(listing=lambda: (changes and changes[0](), dict(self.listed))[1])
                sid = self.on_track(svc)
                self.gone(svc)
                self.reserve(svc, 120)
                if name == "withdrawn":
                    changes.append(lambda: svc.withdraw_goal("owner/p01", sid))
                else:
                    changes.append(lambda: svc.send_report(
                        sid, self.secret(sid), {**REPORT, "phase": name}))
                self.drain()
                self.assertEqual(self.revives(), [])
                self.assertEqual(self.rows("manager.woken"), [])
                self.assertEqual(svc._nudging, set())

    def test_a_wake_that_cannot_start_is_a_failed_wake_and_frees_the_reservation(self):
        broken = []

        def dispatch(job):
            if broken:
                raise RuntimeError("no thread")
            self.queued(job)

        svc = self.begin(dispatch=dispatch)
        sid = self.on_track(svc)
        self.gone(svc)
        broken.append(True)
        self.tick(svc, 120)
        self.assertEqual(self.revives(), [])
        self.assertEqual(self.rows("manager.woken"), [{
            "sprint_id": sid, "goal": GOAL, "session_id": "s-1", "ok": False,
            "reason": "the wake could not start: RuntimeError: no thread"}])
        self.assertEqual(svc._nudging, set())

    def test_a_manager_seen_before_the_wake_command_returns_counts_as_back(self):
        svc = self.begin()
        sid = self.on_track(svc)
        self.during = lambda: self.seen(svc, sid)
        self.gone(svc)
        self.tick(svc, 120)
        self.assertEqual(self.rows("manager.woken"), [
            {"sprint_id": sid, "goal": GOAL, "session_id": "s-1", "ok": True, "back": True}])
        self.assertTrue(svc._sprints[sid].revivals[-1].back)
        for seconds in (240, 360):
            self.gone(svc)
            self.tick(svc, seconds)
        self.assertEqual(len(self.revives()), 3)
        self.gone(svc)
        self.tick(svc, 480)
        self.assertEqual(len(self.revives()), 3)
        self.assertEqual(len(self.rows("manager.stalled")), 1)

    def test_an_unknown_session_is_taken_over_by_one_new_manager(self):
        svc = self.begin()
        sid = self.on_track(svc, seen=False)
        self.tick(svc, 120)
        self.assertEqual(len(self.launches.calls), 2)
        self.assertEqual(self.launches.calls[-1].prompt, manager.TAKEOVER_LEAD + GOAL)
        started = self.rows("manager.started")[-1]
        self.assertEqual((started["sprint_id"], started["takeover"], started["goal"]),
                         (sid, True, GOAL))
        self.tick(svc, 121)
        self.assertEqual(len(self.launches.calls), 2)

    def test_two_failed_wakes_in_a_row_are_followed_by_one_takeover(self):
        svc = self.begin()
        self.on_track(svc)
        self.gone(svc)
        self.outcomes[:] = ["No conversation found", "No conversation found"]
        self.tick(svc, 120)
        self.tick(svc, 240)
        self.assertEqual(len(self.revives()), 2)
        self.assertEqual([row["ok"] for row in self.rows("manager.woken")], [False, False])
        self.assertEqual(len(self.launches.calls), 1)
        self.tick(svc, 360)
        self.assertEqual(len(self.launches.calls), 2)
        self.assertEqual(self.launches.calls[-1].prompt, manager.TAKEOVER_LEAD + GOAL)
        self.tick(svc, 361)
        self.assertEqual(len(self.launches.calls), 2)
        self.assertEqual(len(self.revives()), 2)

    def test_a_manager_polled_while_its_launcher_returns_keeps_its_session(self):
        svc = self.begin(launcher=self.launched_and_seen)
        self.svc_under_test = svc
        sid = self.on_track(svc)
        self.gone(svc)
        self.outcomes[:] = ["No conversation found", "No conversation found"]
        for seconds in (120, 240, 360):
            self.tick(svc, seconds)
        self.assertEqual(len(self.launches.calls), 2)
        self.assertGreater(self.rows("manager.started")[-1]["seen_after"], 0)
        self.assertEqual(svc._sprints[sid].manager_session, "s-2")

    def launched_and_seen(self, launch):
        self.launches(launch)
        if launch.takeover:
            self.append(self.svc_under_test, [("session.seen", "owner/p01", {
                "session_id": "s-2", "cwd": "/srv/p01", "repo": "/srv/p01", "state": "idle",
                "name": launch.session_name})])

    def test_a_wake_that_never_comes_back_counts_as_failed(self):
        svc = self.begin()
        self.on_track(svc)
        self.gone(svc)
        for seconds in (120, 240, 360):
            self.tick(svc, seconds)
        self.assertEqual(len(self.revives()), 2)
        self.assertEqual(len(self.launches.calls), 2)

    def test_a_queued_takeover_is_dropped_when_the_sprint_stops_having_work(self):
        for name in ("closing", "withdrawn"):
            with self.subTest(name):
                self.setUp()
                svc = self.begin()
                sid = self.on_track(svc, seen=False)
                before = self.manager_rows()
                self.reserve(svc, 120)
                self.assertEqual(len(self.queued.jobs), 1)
                if name == "withdrawn":
                    svc.withdraw_goal("owner/p01", sid)
                else:
                    svc.send_report(sid, self.secret(sid), {**REPORT, "phase": "closing"})
                self.queued.run_next()
                self.assertEqual(len(self.launches.calls), 1)
                self.assertEqual(self.manager_rows(), before)
                self.assertEqual(svc._launching, {})

    def test_a_queued_takeover_is_dropped_when_the_manager_is_listed_again(self):
        for name in ("folded", "folded without a nudger", "listing"):
            with self.subTest(name):
                self.setUp()
                svc = self.begin(nudger=None) if "nudger" in name else self.begin()
                sid = self.on_track(svc, seen=False)
                before = self.manager_rows()
                self.reserve(svc, 120)
                if name.startswith("folded"):
                    self.seen(svc, sid)
                else:
                    self.listed_now(sid)
                self.queued.run_next()
                self.assertEqual(len(self.launches.calls), 1)
                self.assertEqual(self.manager_rows(), before)
                self.assertEqual(svc._launching, {})
                if name == "listing":
                    self.reserve(svc, 239)
                    self.assertEqual(self.queued.jobs, [])
                    self.assertEqual(len(self.launches.calls), 1)

    def waiting_takeover(self):
        """A sprint with an unknown session whose takeover waited for quota until `until`."""
        until = int(T0) + 1000
        dirs = self.profiles(work=0, home=0)
        svc = self.begin(profile_dirs=list(dirs.values()))
        sid = self.on_track(svc, seen=False)
        self.readings(svc, lambda profile: self.exhausted(until + (profile == "home") * 1000))
        self.tick(svc, 120)
        return svc, sid, until

    def test_a_takeover_that_meets_exhausted_profiles_waits_then_starts_exactly_one_once_capacity_returns(self):
        for name in ("poll", "retry"):
            with self.subTest(name):
                self.setUp()
                svc, sid, until = self.waiting_takeover()
                self.assertEqual(len(self.launches.calls), 1)
                self.assertEqual(self.rows("manager.waiting"), [{
                    "sprint_id": sid, "takeover": True, "goal": GOAL,
                    "until": datetime.fromtimestamp(until, timezone.utc).isoformat()}])
                status = sprints.manager_status(
                    svc._sprints[sid], False, int((T0 + 120) * 1000), True)
                self.assertEqual((status[0], status[2]), ("waiting", True))
                self.tick(svc, 1000 - 1)
                self.assertEqual(len(self.launches.calls), 1)
                self.readings(svc, lambda profile: self.weekly(0.1))
                if name == "poll":
                    self.tick(svc, 1000)
                else:
                    svc.retry_manager("owner/p01", sid)
                    self.drain()
                    self.tick(svc, 1000)
                self.assertEqual(len(self.launches.calls), 2)
                self.assertEqual(self.launches.calls[-1].prompt, manager.TAKEOVER_LEAD + GOAL)
                self.assertTrue(self.rows("manager.started")[-1]["takeover"])
                self.assertEqual(len(self.rows("manager.started")), 2)

    def test_a_takeover_without_the_secret_is_a_takeover_failure_and_counts(self):
        svc = self.begin()
        sid = self.on_track(svc, seen=False)
        (self.store.parent / "sprint-secrets" / sid).unlink()
        missing = {"sprint_id": sid, "reason": "the sprint's secret is missing",
                   "takeover": True, "goal": GOAL}
        self.tick(svc, 120)
        self.assertEqual(self.rows("manager.failed"), [missing])
        self.tick(svc, 240)
        self.tick(svc, 360)
        self.assertEqual(self.rows("manager.failed"), [missing] * 3)
        self.tick(svc, 480)
        self.assertEqual(self.rows("manager.failed"), [missing] * 3)
        self.assertEqual(self.rows("manager.stalled"), [{
            "sprint_id": sid, "goal": GOAL, "reason": "the sprint's secret is missing"}])
        self.assertEqual(len(self.launches.calls), 1)

    def test_a_takeover_whose_launch_fails_is_marked_as_a_takeover(self):
        self.launches.fail[:] = [None, "no claude"]
        svc = self.begin()
        sid = self.on_track(svc, seen=False)
        self.tick(svc, 120)
        self.assertEqual(self.rows("manager.failed"), [{
            "sprint_id": sid, "reason": "no claude", "takeover": True, "goal": GOAL}])

    def test_a_third_bring_back_within_an_hour_is_followed_by_no_fourth_and_try_again_starts_one_more(self):
        svc = self.begin()
        sid = self.on_track(svc)
        self.gone(svc)
        for seconds in (120, 240, 360):
            self.tick(svc, seconds)
            self.seen(svc, sid)
            self.gone(svc)
        self.assertEqual(len(self.revives()), 3)
        self.tick(svc, 480)
        self.assertEqual(len(self.revives()), 3)
        self.assertEqual(self.rows("manager.stalled"), [{
            "sprint_id": sid, "goal": GOAL, "reason": revive.GONE_AGAIN_TEXT}])
        self.tick(svc, 480 + 3600)
        self.assertEqual(len(self.rows("manager.stalled")), 1)
        self.assertEqual(len(self.revives()), 3)
        self.assertEqual(len(self.launches.calls), 1)
        self.assertEqual(svc._sprints[sid].stalled, revive.GONE_AGAIN_TEXT)
        self.assertEqual(svc._manager_state(svc._sprints[sid]), (
            "stalled", "managers keep failing: " + revive.GONE_AGAIN_TEXT, True))
        svc.retry_manager("owner/p01", sid)
        self.drain()
        self.assertEqual(len(self.launches.calls), 2)
        self.assertEqual(self.launches.calls[-1].prompt, manager.TAKEOVER_LEAD + GOAL)
        self.assertTrue(self.rows("manager.started")[-1]["takeover"])
        self.assertIsNone(svc._sprints[sid].stalled)

    def test_revive_never_holds_the_ingest_lock(self):
        held = []

        def free():
            got = svc._ingest.acquire(blocking=False)
            held.append(got)
            if got:
                svc._ingest.release()

        def listing():
            free()
            return dict(self.listed)

        def nudger(sent):
            free()
            self.nudger(sent)

        def launcher(launch):
            free()
            self.launches(launch)

        for name, seen in (("wake", True), ("takeover", False)):
            with self.subTest(name):
                self.setUp()
                held.clear()
                svc = self.begin(nudger=nudger, launcher=launcher, listing=listing)
                self.on_track(svc, seen=seen)
                held.clear()
                if seen:
                    self.gone(svc)
                self.tick(svc, 120)
                self.assertEqual(len(self.revives()) if seen else len(self.launches.calls) - 1, 1)
                self.assertGreaterEqual(len(held), 2)
                self.assertTrue(all(held))

    def test_the_poll_loop_brings_managers_back(self):
        called = threading.Event()
        with mock.patch.object(service.ConsoleService, "revive", lambda self: called.set()):
            self.begin(session_poll_seconds=0.05)
            self.assertTrue(called.wait(10))


class ReviveViewServiceTest(ReviveCase):
    def live(self, svc):
        return json.loads(svc.view_bytes)

    def test_a_stalled_sprint_shows_one_inbox_item_in_the_live_view(self):
        svc = self.begin()
        sid = self.on_track(svc)
        self.gone(svc)
        for seconds in (120, 240, 360):
            self.tick(svc, seconds)
            self.seen(svc, sid)
            self.gone(svc)
        self.tick(svc, 480)
        live = self.live(svc)
        (stall,) = [i for i in live["inbox"]["open"] if i["reason"] == "manager"]
        self.assertEqual(stall["headline"], "managers keep failing on " + GOAL)
        self.assertEqual(stall["last_reason"], revive.GONE_AGAIN_TEXT)
        self.assertEqual(live["statement"]["inbox_items"], 1)
        (shown,) = [sp for e in live["entries"] if e["project_id"] == "owner/p01"
                    for sp in e["sprints"]]
        self.assertEqual((shown["manager_state"], shown["retry"]), ("stalled", True))
        svc.retry_manager("owner/p01", sid)
        self.drain()
        live = self.live(svc)
        self.assertEqual([i for i in live["inbox"]["open"] if i["reason"] == "manager"], [])
        self.assertEqual(live["statement"]["inbox_items"], 0)

    def test_a_restart_adds_one_digest_sentence_and_no_inbox_item_in_the_live_view(self):
        svc = self.begin()
        self.on_track(svc)
        self.gone(svc)
        self.tick(svc, 120)
        live = self.live(svc)
        said = [m["sentence"] for m in live["digest"]["recent"]]
        self.assertEqual(said.count("The manager of " + GOAL + " was restarted"), 1)
        self.assertEqual([i for i in live["inbox"]["open"] if i["reason"] == "manager"], [])
