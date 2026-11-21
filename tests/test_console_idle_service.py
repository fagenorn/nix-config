"""The service tells an idle manager to go on and waits out a quota (#929).

Run: just agent-workflow-tests
"""
import json
import os
import shutil
import threading
from dataclasses import replace
from datetime import datetime, timezone
from unittest import mock

from agent_tools.console import capacity, manager, nudge, permission, service, sessions, signin, sprints

from . import console_test_support as support
from .test_console_messages import PARTS
from .test_console_questions import ROUND
from .test_console_reports import REPORT
from .test_console_revive_service import GOAL, T0, ReviveCase
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)

RESET = int(T0) + 3600
RESUMED = PARTS["title"] + " resumed after the quota reset"
MOVED = PARTS["title"] + " moved to another account"
TOOK_OVER = "A new manager took over " + PARTS["title"]
JSON = {"Content-Type": "application/json"}


class IdleCase(ReviveCase):
    """The set-up and helpers of the idle suites; it holds no test."""

    def setUp(self):
        super().setUp()
        self.out_now = False
        self.svc = None
        self.arrival = 0
        self.stops = []
        self.held = []

    def arrive(self, svc):
        """`on_track`, then forget the nudge its brief approval caused: only later sends count."""
        sid = self.on_track(svc)
        self.nudges.clear()
        self.arrival = len(self.rows("sprint.nudged"))
        return sid

    def messaged(self):
        return self.rows("sprint.nudged")[self.arrival:]

    def poll(self, svc, seconds):
        self.now[0] = T0 + seconds
        svc.renudge()
        svc.finish_stops()
        svc.revive()
        svc.nudge_idle()
        self.drain()

    def continues(self):
        return [n for n in self.nudges if n.route == "continue"]

    def live(self, svc):
        return json.loads(svc.view_bytes)

    def entry(self, svc, sid):
        (shown,) = [sp for e in self.live(svc)["entries"] if e["project_id"] == "owner/p01"
                    for sp in e["sprints"] if sp["sprint_id"] == sid]
        return shown

    def said(self, svc):
        return [m["sentence"] for m in self.live(svc)["digest"]["recent"]]

    def start_out(self, listed=True, readings=True, **overrides):
        dirs = self.profiles(work=None, home=None)
        svc = self.begin(profile_dirs=list(dirs.values()), **overrides)
        sid = self.arrive(svc)
        self.assertEqual(self.launches.calls[0].profile, "work")
        if listed:
            self.listed_now(sid)
        if readings:
            self.out_readings(svc)
        svc.poll_sessions()
        return svc, sid

    def out_readings(self, svc):
        self.readings(svc, lambda p: self.exhausted(RESET) if p == "work" else self.weekly(0.1))

    def idle_service(self, **overrides):
        svc = self.begin(**overrides)
        sid = self.arrive(svc)
        self.listed_now(sid)
        return svc, sid


class IdleServiceTest(IdleCase):
    def test_an_idle_continue_to_a_bypass_manager_comes_from_a_bypass_sender(self):
        svc, sid = self.idle_service(permission_reader=lambda project_id, root: permission.Permission(
            permission.BYPASS, permission.RULES_IN_PLACE))
        self.poll(svc, 300)
        self.assertEqual(self.continues(), [
            nudge.Nudge(sid, "continue", self.name(sid), "s-1", "work", "/srv/p01",
                        sender_bypass=True)])

    def test_an_idle_manager_of_a_sprint_with_work_gets_one_nudge_after_five_minutes(self):
        svc, sid = self.idle_service()
        self.poll(svc, 299.999)
        self.assertEqual(self.continues(), [])
        self.poll(svc, 300)
        self.assertEqual(self.continues(), [
            nudge.Nudge(sid, "continue", self.name(sid), "s-1", "work", "/srv/p01")])
        self.assertEqual(self.rows("manager.nudged"), [
            {"sprint_id": sid, "goal": GOAL, "session_id": "s-1", "ok": True}])
        self.poll(svc, 301)
        self.assertEqual(len(self.continues()), 1)

    RUN_SEEN = {"session_id": "s-1", "run_id": "wf_1", "moved_ms": int((T0 + 200) * 1000),
                "issues": [{"issue": 12, "stage": "building", "task": None, "tasks": None}]}

    def test_a_working_manager_or_a_finished_delivery_gets_no_early_nudge(self):
        for name in ("working", "finished"):
            with self.subTest(name):
                self.setUp()
                svc, sid = self.idle_service()
                if name == "working":
                    self.append(svc, [("session.seen", "owner/p01", {
                        "session_id": "s-1", "cwd": "/srv/p01", "repo": "/srv/p01",
                        "state": "working", "name": self.name(sid)})])
                    self.poll(svc, 600)
                    self.assertEqual(self.continues(), [])
                    continue
                self.now[0] = T0 + 200
                self.append(svc, [("delivery.seen", "owner/p01", self.RUN_SEEN)])
                self.now[0] = T0 + 250
                self.append(svc, [("delivery.gone", "owner/p01",
                                   {"session_id": "s-1", "run_id": "wf_1"})])
                self.poll(svc, 300)
                self.assertEqual(self.continues(), [])
                self.poll(svc, 499.999)
                self.assertEqual(self.continues(), [])
                self.poll(svc, 500)
                self.assertEqual(len(self.continues()), 1)

    def test_a_run_in_progress_that_moved_within_thirty_minutes_holds_the_nudge(self):
        svc, sid = self.idle_service()
        self.now[0] = T0 + 200
        self.append(svc, [("delivery.seen", "owner/p01", self.RUN_SEEN)])
        for seconds in (300, 500, 1200, 1999.999):
            self.poll(svc, seconds)
            self.assertEqual(self.continues(), [], seconds)

    def test_a_run_in_progress_that_has_not_moved_for_thirty_minutes_no_longer_holds_it(self):
        svc, sid = self.idle_service()
        self.now[0] = T0 + 200
        self.append(svc, [("delivery.seen", "owner/p01", self.RUN_SEEN)])
        self.poll(svc, 1999.999)
        self.assertEqual(self.continues(), [])
        self.poll(svc, 2000)
        self.assertEqual(len(self.continues()), 1)
        self.poll(svc, 2001)
        self.assertEqual(len(self.continues()), 1)

    def write_setup_journal(self, moved_at):
        """A run of s-1 that has started its setup and named no issue, last moved at `moved_at`."""
        journal = (self.store.parent.parent.parent / "projects/-srv-p01/s-1"
                   / "subagents/workflows/wf_1/journal.jsonl")
        journal.parent.mkdir(parents=True)
        journal.write_text(json.dumps(
            {"agentId": "a1", "type": "started", "label": "setup", "phase": "setup"}) + "\n")
        os.utime(journal, ns=(int(moved_at * 1e9),) * 2)

    def test_a_run_awaiting_its_setup_result_holds_the_nudge_like_one_with_an_issue(self):
        svc, sid = self.idle_service(session_dirs=[self.store.parent.parent.parent / "sessions"])
        self.write_setup_journal(T0 + 200)
        svc.poll_deliveries()
        self.assertEqual(self.rows("delivery.seen"), [])
        for seconds in (300, 500, 1200, 1999.999):
            self.poll(svc, seconds)
            self.assertEqual(self.continues(), [], seconds)
        self.poll(svc, 2000)
        self.assertEqual(len(self.continues()), 1)

    def reach_no_progress(self, svc, sid):
        for seconds in (300, 900, 1500, 2100):
            self.poll(svc, seconds)

    def test_no_second_nudge_within_ten_minutes_and_no_fourth_without_a_report(self):
        svc, sid = self.idle_service()
        counts = []
        for seconds in (300, 899.999, 900, 1500, 2100, 2700):
            self.poll(svc, seconds)
            counts.append(len(self.continues()))
        self.assertEqual(counts, [1, 1, 2, 3, 3, 3])
        self.assertEqual(self.rows("manager.no_progress"), [
            {"sprint_id": sid, "goal": GOAL, "status": REPORT["status"]}])

    def test_a_report_resets_the_count(self):
        svc, sid = self.idle_service()
        for seconds in (300, 900, 1500):
            self.poll(svc, seconds)
        self.assertEqual(len(self.continues()), 3)
        self.now[0] = T0 + 1600
        svc.send_report(sid, self.secret(sid), REPORT)
        self.poll(svc, 2100)
        self.assertEqual(len(self.continues()), 4)
        self.assertEqual(self.rows("manager.no_progress"), [])

    def test_the_no_progress_item_offers_continue_and_withdraw(self):
        svc, sid = self.idle_service()
        self.reach_no_progress(svc, sid)
        live = self.live(svc)
        (item,) = [i for i in live["inbox"]["open"] if i["reason"] == "progress"]
        self.assertEqual(item["headline"],
                         "the manager has stopped making progress on " + PARTS["title"])
        self.assertEqual(item["last_status"], REPORT["status"])
        self.assertEqual(live["statement"]["inbox_items"], 1)
        self.now[0] = T0 + 2190
        self.append(svc, [("delivery.seen", "owner/p01", {
            "session_id": "s-1", "run_id": "wf_1", "moved_ms": int((T0 + 2190) * 1000),
            "issues": [{"issue": 12, "stage": "building", "task": None, "tasks": None}]})])
        self.now[0] = T0 + 2200
        body = json.dumps({"project_id": "owner/p01", "sprint_id": sid}).encode()
        status, _, _ = support.post_page(
            svc.address, "/api/continue", self.own(svc, **JSON), body=body)
        self.assertEqual(status, 204)
        self.drain()
        self.assertEqual(len(self.rows("sprint.continued")), 1)
        self.assertEqual(len(self.continues()), 4)
        self.assertEqual([i for i in self.live(svc)["inbox"]["open"]
                          if i["reason"] == "progress"], [])
        svc.withdraw_goal("owner/p01", sid)
        self.assertEqual([i for i in self.live(svc)["inbox"]["open"]
                          if i.get("sprint_id") == sid], [])

    def test_continue_is_refused_unless_the_item_is_open(self):
        svc, sid = self.idle_service()
        with self.assertRaises(sprints.Refused) as caught:
            self.assert_unchanged(svc, lambda: svc.continue_sprint("owner/p01", sid))
        self.assertEqual(str(caught.exception), sprints.NOT_STUCK)
        with self.assertRaises(sprints.Refused) as caught:
            self.assert_unchanged(svc, lambda: svc.continue_sprint("owner/p01", "0" * 32))
        self.assertEqual(str(caught.exception), sprints.NOT_OPEN)
        body = json.dumps({"project_id": "owner/p01", "sprint_id": sid}).encode()
        got = self.assert_unchanged(svc, lambda: support.post_page(
            svc.address, "/api/continue", self.own(svc, **JSON), body=body))
        self.assertEqual((got[0], got[2]), (409, sprints.NOT_STUCK.encode() + b"\n"))

    def test_a_sprint_that_waits_on_the_owner_is_closing_done_stopping_or_withdrawn_is_never_nudged(self):
        def waiting(svc, sid):
            svc.ask_questions(sid, self.secret(sid), ROUND)

        def phase(name):
            return lambda svc, sid: svc.send_report(
                sid, self.secret(sid), {**REPORT, "phase": name})

        table = {"waiting": waiting, "closing": phase("closing"), "done": phase("done"),
                 "stopping": lambda svc, sid: svc.stop_sprint("owner/p01", sid),
                 "withdrawn": lambda svc, sid: svc.withdraw_goal("owner/p01", sid)}
        for name, act in table.items():
            with self.subTest(name):
                self.setUp()
                svc, sid = self.idle_service()
                act(svc, sid)
                self.drain()
                for seconds in (300, 1200, 3000):
                    self.poll(svc, seconds)
                self.assertEqual(self.continues(), [])
                self.assertEqual(self.rows("manager.nudged"), [])

    def test_an_idle_nudge_that_fails_counts_and_says_why(self):
        svc, sid = self.idle_service()
        self.outcomes = ["the relay did not confirm the message"]
        self.poll(svc, 300)
        self.assertEqual(self.rows("manager.nudged"), [
            {"sprint_id": sid, "goal": GOAL, "session_id": "s-1", "ok": False,
             "reason": "the relay did not confirm the message"}])
        self.assertIn(
            f"console: idle_nudge_failed {sid} the relay did not confirm the message",
            self.stderr.getvalue())

    def test_a_fresh_listing_without_the_manager_sends_nothing(self):
        svc, sid = self.idle_service()
        self.listed = {}
        self.poll(svc, 300)
        self.assertEqual(self.continues(), [])
        self.assertEqual(self.rows("manager.nudged"), [])

    def test_a_manager_that_turns_busy_during_the_listing_gets_no_nudge(self):
        def listing():
            if self.turn_busy:
                self.listed["s-1"] = replace(self.listed["s-1"], status="busy")
            return dict(self.listed)

        self.turn_busy = False
        svc, sid = self.idle_service(listing=listing)
        self.turn_busy = True
        self.poll(svc, 300)
        self.assertEqual(self.continues(), [])
        self.assertEqual(self.rows("manager.nudged"), [])
        self.assertEqual(svc._nudging, set())
        self.turn_busy = False
        self.listed["s-1"] = replace(self.listed["s-1"], status="idle")
        self.poll(svc, 301)
        self.assertEqual(len(self.continues()), 1)

    def test_a_busy_reading_older_than_the_sessions_newest_hook_does_not_hold_the_nudge(self):
        svc, sid = self.idle_service()
        self.listed["s-1"] = replace(self.listed["s-1"], status="busy", updated_ms=1)
        self.append(svc, [("session.hook", "owner/p01", {
            "event": "Stop", "session_id": "s-1", "cwd": "/srv/p01", "repo": "/srv/p01",
            "received_ms": int((T0 + 10) * 1000)})])
        self.poll(svc, 300)
        self.assertEqual(len(self.continues()), 1)

    def test_a_manager_gone_while_the_no_progress_item_is_open_is_not_brought_back(self):
        svc, sid = self.idle_service()
        self.reach_no_progress(svc, sid)
        self.assertEqual(len(self.rows("manager.no_progress")), 1)
        self.listed = {}
        self.gone(svc)
        for seconds in (2220, 2400, 3600, 7200):
            self.poll(svc, seconds)
        self.assertEqual(self.revives(), [])
        self.assertEqual(self.rows("manager.woken"), [])
        self.assertEqual(self.rows("manager.stalled"), [])
        self.assertEqual(len(self.launches.calls), 1)

    def test_the_idle_nudge_never_holds_the_ingest_lock(self):
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

        svc = self.begin(nudger=nudger, listing=listing)
        sid = self.arrive(svc)
        self.listed_now(sid)
        held.clear()
        self.poll(svc, 300)
        self.assertEqual(len(self.continues()), 1)
        self.assertGreaterEqual(len(held), 2)
        self.assertTrue(all(held))

    def test_the_poll_loop_nudges_idle_managers(self):
        called = threading.Event()
        with mock.patch.object(service.ConsoleService, "nudge_idle", lambda self: called.set()):
            self.begin(session_poll_seconds=0.05)
            self.assertTrue(called.wait(10))


class IdleQuotaTest(IdleCase):
    def record_stop(self, session_id, profile):
        """Note one stop: its profile, the launches so far, and whether the ingest lock was free."""
        self.stops.append((session_id, profile, len(self.launches.calls)))
        if self.svc is not None:
            got = self.svc._ingest.acquire(blocking=False)
            self.held.append(got)
            if got:
                self.svc._ingest.release()

    def stopper(self, session_id, profile):
        self.record_stop(session_id, profile)
        self.listed.pop(session_id, None)

    def listed_out(self, stopper=None, **overrides):
        """`start_out` with a stopper and `s-1` listed on the profile the manager was launched on."""
        svc, sid = self.start_out(stopper=stopper or self.stopper, **overrides)
        self.svc = svc
        if "s-1" in self.listed:
            self.listed["s-1"] = sessions.Observation(
                "s-1", "/srv/p01", 1, "idle", None, self.name(sid), None, "work")
        return svc, sid

    def seen_row(self, svc, sid, session_id="s-1", state="idle"):
        self.append(svc, [("session.seen", "owner/p01", {
            "session_id": session_id, "cwd": "/srv/p01", "repo": "/srv/p01", "state": state,
            "name": self.name(sid)})])

    def test_a_listed_manager_waiting_on_quota_is_stopped_and_taken_over_on_an_account_with_room(self):
        svc, sid = self.listed_out()
        self.poll(svc, 300)
        self.assertEqual(self.stops, [("s-1", "work", 1)])
        self.assertTrue(self.held)
        self.assertTrue(all(self.held))
        self.assertEqual([c.profile for c in self.launches.calls], ["work", "home"])
        self.assertIs(self.launches.calls[-1].takeover, True)
        started = self.rows("manager.started")[-1]
        self.assertEqual((started["profile"], started["takeover"], started["moved"], started["goal"]),
                         ("home", True, True, GOAL))
        self.assertEqual(self.said(svc).count(MOVED), 1)
        self.assertEqual(self.said(svc).count(TOOK_OVER), 0)
        self.assertNotIn(sid, svc._launching)
        self.assertNotIn(sid, svc._quota_held)
        self.gone(svc)
        self.seen_row(svc, sid, "s-2")
        self.listed = {"s-2": sessions.Observation(
            "s-2", "/srv/p01", 1, "idle", None, self.name(sid), None, "home")}
        self.poll(svc, 1800)
        self.assertEqual(len(self.stops), 1)
        self.assertEqual([c.profile for c in self.launches.calls], ["work", "home"])
        self.assertEqual([n.session_id for n in self.continues()], ["s-2"])
        self.assertFalse(any(row.get("resumed") for row in self.rows("manager.nudged")))
        self.assertEqual(self.said(svc).count(RESUMED), 0)
        self.assertEqual(self.said(svc).count(MOVED), 1)

    def test_a_listed_manager_waits_on_quota_when_no_account_has_room(self):
        def other_out(svc):
            self.readings(svc, lambda p: self.exhausted(RESET))

        def home_room(svc):
            self.append(svc, [(capacity.READING, None, {"profile": "home", **self.weekly(0.1)})])

        def work_only(svc):
            self.append(svc, [(capacity.READING, None, {"profile": "work", **self.exhausted(RESET)})])

        cases = [
            ("the other account is out too", {"readings": False}, other_out, home_room),
            ("the other account is excluded", {}, lambda svc: svc.set_exclusion("home", True),
             lambda svc: svc.set_exclusion("home", False)),
            ("the other account has no reading", {"readings": False}, work_only, home_room),
        ]
        for name, overrides, arrange, give_room in cases:
            with self.subTest(name):
                self.setUp()
                svc, sid = self.listed_out(**overrides)
                arrange(svc)
                self.poll(svc, 300)
                self.poll(svc, 600)
                self.assertEqual(self.stops, [])
                self.assertEqual([c.profile for c in self.launches.calls], ["work"])
                self.assertNotIn(sid, svc._launching)
                shown = self.entry(svc, sid)
                self.assertEqual((shown["state"], shown["state_text"]),
                                 ("quota", "waiting on quota until"))
                self.assertEqual(self.nudges, [])
                give_room(svc)
                self.poll(svc, 900)
                self.assertEqual(self.stops, [("s-1", "work", 1)])
                self.assertEqual([c.profile for c in self.launches.calls], ["work", "home"])

    def test_a_move_never_starts_a_second_manager_while_the_first_is_listed(self):
        def failing(session_id, profile):
            self.record_stop(session_id, profile)
            raise manager.StopFailed("the stop timed out")

        def listed_on(session_id, profile):
            self.record_stop(session_id, profile)

        def renamed(session_id, profile):
            self.stopper(session_id, profile)
            self.seen_row(self.svc, self.sid, "s-2")

        def loses_room(session_id, profile):
            self.stopper(session_id, profile)
            self.svc.set_exclusion("home", True)

        cases = [("the stop fails", failing), ("the session stays listed", listed_on),
                 ("another session carries the manager's name", renamed),
                 ("the target loses room during the stop", loses_room)]
        for name, stop in cases:
            with self.subTest(name):
                self.setUp()
                svc, sid = self.listed_out(stopper=stop)
                self.sid = sid
                self.poll(svc, 300)
                self.poll(svc, 600)
                self.assertEqual(len(self.stops), 1)
                self.assertEqual([c.profile for c in self.launches.calls], ["work"])
                self.assertEqual(len(self.rows("manager.started")), 1)
                self.assertIn(sid, svc._move_cancelled)
                self.assertNotIn(sid, svc._launching)
                self.assertNotIn(MOVED, self.said(svc))
                if name == "the stop fails":
                    self.assertIn("console: quota_move_failed " + sid, self.stderr.getvalue())
                if name == "the target loses room during the stop":
                    self.gone(svc)
                    self.assert_waits_to_wake(svc, sid)

    def test_a_listed_manager_is_not_moved_while_it_works_without_a_stopper_while_handed_to_the_owner_or_after_three_bring_backs(self):
        with self.subTest("working"):
            svc, sid = self.listed_out()
            self.seen_row(svc, sid, state="working")
            self.poll(svc, 300)
            self.assertEqual(self.stops, [])
            self.seen_row(svc, sid, state="idle")
            self.poll(svc, 600)
            self.assertEqual(len(self.stops), 1)
            self.assertEqual([c.profile for c in self.launches.calls], ["work", "home"])
        with self.subTest("without a stopper"):
            self.setUp()
            svc, sid = self.start_out()
            self.poll(svc, 300)
            self.poll(svc, 600)
            self.assertEqual([c.profile for c in self.launches.calls], ["work"])
            self.assertNotIn("quota_move_failed", self.stderr.getvalue())
            self.assertEqual(self.entry(svc, sid)["state"], "quota")
        with self.subTest("the no-progress item is open"):
            self.setUp()
            svc, sid = self.listed_out()
            self.append(svc, [("manager.no_progress", "owner/p01", {
                "sprint_id": sid, "goal": GOAL, "status": None})])
            self.poll(svc, 300)
            self.assertEqual(self.stops, [])
            self.assertEqual([c.profile for c in self.launches.calls], ["work"])
        with self.subTest("three bring-backs within the hour"):
            self.setUp()
            svc, sid = self.listed_out()
            self.append(svc, [("manager.started", "owner/p01", {
                "sprint_id": sid, "profile": "work", "session_name": self.name(sid),
                "takeover": True, "goal": GOAL})] * 3)
            self.poll(svc, 300)
            self.assertEqual(self.stops, [])
            self.assertEqual([c.profile for c in self.launches.calls], ["work"])

    def test_a_listed_move_whose_manager_left_the_listing_before_the_stop_is_left_to_the_bring_back(self):
        svc, sid = self.listed_out()
        self.now[0] = T0 + 300
        svc.revive()
        self.assertIsInstance(svc._launching[sid], service._ListedMoveReservation)
        self.assertEqual(svc._launching[sid].target, "home")
        self.listed.clear()
        self.drain()
        self.assertEqual(self.stops, [])
        self.assertEqual([c.profile for c in self.launches.calls], ["work"])
        self.assertNotIn(sid, svc._move_cancelled)
        self.assertNotIn(sid, svc._launching)
        self.gone(svc)
        self.poll(svc, 600)
        self.assertEqual([c.profile for c in self.launches.calls], ["work", "home"])
        self.assertEqual(self.said(svc).count(TOOK_OVER), 1)
        self.assertEqual(self.said(svc).count(MOVED), 0)

    def test_nothing_is_sent_while_the_account_is_out_and_one_resume_follows_the_reset(self):
        svc, sid = self.start_out()
        for seconds in (300, 1800):
            self.now[0] = T0 + seconds
            svc.nudge_idle()
            self.assertEqual((svc._nudging, self.queued.jobs), (set(), []))
            self.poll(svc, seconds)
        self.assertEqual(self.nudges, [])
        self.assertEqual(self.rows("manager.nudged"), [])
        live = self.live(svc)
        shown = self.entry(svc, sid)
        (work,) = [p for p in live["capacity"]["profiles"] if p["profile"] == "work"]
        self.assertEqual((shown["state"], shown["state_text"]), ("quota", "waiting on quota until"))
        self.assertEqual(shown["state_until"], work["out_until"])
        self.assertEqual(shown["state_until"],
                         datetime.fromtimestamp(RESET, timezone.utc).isoformat())
        self.poll(svc, 3600)
        self.assertEqual(len(self.nudges), 1)
        self.assertEqual(self.nudges[0].route, "continue")
        self.assertEqual(self.rows("manager.nudged"), [
            {"sprint_id": sid, "goal": GOAL, "session_id": "s-1", "ok": True, "resumed": True}])
        shown = self.entry(svc, sid)
        self.assertNotEqual(shown["state"], "quota")
        self.assertIsNone(shown["state_until"])
        self.assertEqual(self.said(svc).count(RESUMED), 1)
        self.poll(svc, 3601)
        self.assertEqual(len(self.nudges), 1)

    def test_a_gone_manager_on_an_account_that_is_out_moves_to_an_account_with_room(self):
        svc, sid = self.start_out(listed=False)
        self.gone(svc)
        self.poll(svc, 600)
        self.assertEqual(self.revives(), [])
        self.assertEqual([call.profile for call in self.launches.calls], ["work", "home"])
        self.assertIs(self.launches.calls[-1].takeover, True)

    def test_a_gone_manager_waits_when_the_other_account_gives_no_reason_to_move(self):
        cases = {
            "no reading yet": lambda svc: self.append(svc, [
                (capacity.READING, None, {"profile": "work", **self.exhausted(RESET)})]),
            "excluded by the owner": lambda svc: (self.out_readings(svc),
                                                  svc.set_exclusion("home", True)),
        }
        for name, arrange in cases.items():
            with self.subTest(name):
                self.setUp()
                svc, sid = self.start_out(listed=False, readings=False)
                arrange(svc)
                svc.poll_sessions()
                self.gone(svc)
                self.poll(svc, 600)
                self.assertEqual([call.profile for call in self.launches.calls], ["work"])
                self.assertEqual(self.revives(), [])
                self.assertEqual(self.rows("manager.waiting"), [])

    def test_two_profiles_whose_readings_carry_one_account_id_are_one_account_to_the_move(self):
        def reading(account):
            return (capacity.READING, None,
                    {"profile": "home", "account": account, **self.weekly(0.1)})

        def left(account):
            return (signin.READING, None, {
                "profile": "home", "state": "signed_in", "ends_at": None,
                "account": "b@example.invalid", "account_seq": 0,
                "left_account": "a@example.invalid", "left_reading": account})

        cases = {
            "same id": ([reading("acct-1")], False),
            "other id": ([reading("acct-2")], True),
            "late reply of the account it left, now on another": (
                [reading("acct-2"), left("acct-1"), reading("acct-1")], True),
            "late reply of the account it left, now on work's": (
                [reading("acct-1"), left("acct-2"), reading("acct-2")], False),
        }
        for name, (home, moves) in cases.items():
            with self.subTest(name):
                self.setUp()
                svc, sid = self.start_out(listed=False, readings=False)
                self.append(svc, [(capacity.READING, None, {
                    "profile": "work", "account": "acct-1", **self.exhausted(RESET)}), *home])
                svc.poll_sessions()
                self.gone(svc)
                self.now[0] = T0 + 600
                svc.revive()
                self.assertEqual(len(self.queued.jobs), 1 if moves else 0)
                if not moves:
                    self.assertNotIn(sid, svc._launching)
                self.drain()
                if moves:
                    self.assertEqual([c.profile for c in self.launches.calls], ["work", "home"])
                    self.assertIs(self.launches.calls[-1].takeover, True)
                else:
                    self.assertEqual([c.profile for c in self.launches.calls], ["work"])
                    self.assertEqual(self.revives(), [])
                    self.assertEqual(self.rows("manager.waiting"), [])

    def reserved_move(self, spare=True, setup=None, **names):
        """A quota move reserved on `home` (with `spare` also having room) and not yet launched."""
        names = names or ({"work": None, "home": None, "spare": None} if spare
                          else {"work": None, "home": None})
        dirs = self.profiles(**names)
        svc = self.begin(profile_dirs=list(dirs.values()))
        sid = self.arrive(svc)
        self.assertEqual(self.launches.calls[0].profile, "work")
        self.out_readings(svc)
        if spare:
            self.append(svc, [(capacity.READING, None, {"profile": "spare", **self.weekly(0.5)})])
        if setup is not None:
            setup(svc)
        svc.poll_sessions()
        self.gone(svc)
        self.now[0] = T0 + 600
        svc.revive()
        self.assertEqual(len(self.queued.jobs), 1)
        self.assertIsInstance(svc._launching[sid], service._TakeoverReservation)
        self.assertEqual(svc._launching[sid].target, "home")
        return svc, sid, dirs

    def during_permission_read(self, svc, change):
        reader, acted = svc._permission_reader, []

        def acting(project_id, root):
            if not acted:
                acted.append(True)
                change()
            return reader(project_id, root)

        svc._permission_reader = acting

    def assert_move_cancelled(self, svc, sid):
        self.assertEqual([c.profile for c in self.launches.calls], ["work"])
        self.assertEqual(self.revives(), [])
        self.assertEqual(self.rows("manager.waiting"), [])
        self.assertEqual(len(self.rows("manager.started")), 1)
        self.assertNotIn(sid, svc._launching)

    def assert_waits_to_wake(self, svc, sid):
        self.poll(svc, 700)
        self.assert_move_cancelled(svc, sid)
        self.poll(svc, 3600)
        self.assertEqual(self.revives(), [
            nudge.Nudge(sid, "revive", self.name(sid), "s-1", "work", "/srv/p01")])
        self.assertEqual([c.profile for c in self.launches.calls], ["work"])

    @staticmethod
    def signed(profile, account):
        return (signin.READING, None, {"profile": profile, "state": "signed_in",
                                       "ends_at": None, "account": account, "account_seq": 0})

    def test_a_quota_move_whose_account_stops_having_room_before_the_launch_starts_nothing_and_waits_to_wake(self):
        def remove(svc, dirs):
            shutil.rmtree(dirs["home"])

        def exclude(svc, dirs):
            svc.set_exclusion("home", True)

        def out(svc, dirs):
            self.append(svc, [(capacity.READING, None,
                               {"profile": "home", **self.exhausted(RESET)})])

        def signed_out(svc, dirs):
            self.append(svc, [signin.entry("home", signin.Status("signed_out", None))])

        cases = [
            ("removed before the launch", True, remove, "drain"),
            ("excluded during the permission read", True, exclude, "read"),
            ("out during the permission read", True, out, "read"),
            ("signed out during the permission read", True, signed_out, "read"),
            ("removed before the launch, nothing else has room", False, remove, "drain"),
            ("excluded during the permission read, nothing else has room", False, exclude,
             "read"),
        ]
        for name, spare, change, when in cases:
            with self.subTest(name):
                self.setUp()
                svc, sid, dirs = self.reserved_move(spare)
                if when == "drain":
                    change(svc, dirs)
                else:
                    self.during_permission_read(svc, lambda: change(svc, dirs))
                self.drain()
                self.assert_move_cancelled(svc, sid)
                self.assert_waits_to_wake(svc, sid)

    def test_a_quota_move_cancelled_with_no_other_room_is_not_decided_again_when_an_account_gains_room(self):
        def setup(svc):
            self.append(svc, [(capacity.READING, None, {"profile": "extra", **self.weekly(0.5)})])
            svc.set_exclusion("extra", True)

        svc, sid, dirs = self.reserved_move(
            spare=False, setup=setup, work=None, home=None, extra=None)
        svc.set_exclusion("home", True)
        self.drain()
        self.assert_move_cancelled(svc, sid)
        svc.set_exclusion("extra", False)
        self.poll(svc, 700)
        self.assert_move_cancelled(svc, sid)
        self.assertIn(sid, svc._move_cancelled)
        self.poll(svc, 3600)
        self.assertEqual([c.profile for c in self.launches.calls], ["work"])
        self.assertEqual(len(self.revives()), 1)

    def test_a_quota_move_on_another_account_than_the_one_it_chose_starts_nothing(self):
        def reading(profile, account):
            return (capacity.READING, None,
                    {"profile": profile, "account": account, **self.weekly(0.1)})

        cases = {
            "the reading account id changes": (
                lambda svc: self.append(svc, [reading("home", "acct-2")]),
                lambda svc: self.append(svc, [reading("home", "acct-3")])),
            "the sign-in account changes": (
                lambda svc: self.append(svc, [self.signed("home", "a@example.invalid")]),
                lambda svc: self.append(svc, [self.signed("home", "b@example.invalid")])),
        }
        for name, (setup, change) in cases.items():
            with self.subTest(name):
                self.setUp()
                svc, sid, _ = self.reserved_move(setup=setup)
                self.during_permission_read(svc, lambda: change(svc))
                self.drain()
                self.assert_move_cancelled(svc, sid)
                self.assert_waits_to_wake(svc, sid)

    def test_a_quota_move_whose_target_gained_an_alias_reading_of_the_managers_account_is_not_a_move(self):
        cases = {"same id": ("acct-1", False), "other id": ("acct-2", True)}
        for name, (alias_id, moves) in cases.items():
            with self.subTest(name):
                self.setUp()
                dirs = self.profiles(work=None, home=None, spare=None)
                svc = self.begin(profile_dirs=list(dirs.values()))
                sid = self.arrive(svc)
                self.append(svc, [
                    (capacity.READING, None, {
                        "profile": "work", "account": "acct-1", **self.exhausted(RESET)}),
                    self.signed("home", "a@example.invalid"),
                    self.signed("spare", "a@example.invalid"),
                    (capacity.READING, None, {
                        "profile": "spare", "account": alias_id, **self.weekly(0.1)})])
                svc.poll_sessions()
                self.gone(svc)
                self.now[0] = T0 + 600
                svc.revive()
                self.assertEqual(len(self.queued.jobs), 1 if moves else 0)
                self.drain()
                self.assertEqual([c.profile for c in self.launches.calls],
                                 ["work", "home"] if moves else ["work"])

    def test_a_quota_move_to_a_colleagues_account_for_the_colleagues_own_sprint_starts(self):
        svc, sid = self.start_out(listed=False)
        with svc._ingest:
            svc._account_owners = {"home": "colleague"}
            svc._sprints[sid] = replace(svc._sprints[sid], started_by="colleague")
        self.gone(svc)
        self.poll(svc, 600)
        self.assertEqual([c.profile for c in self.launches.calls], ["work", "home"])
        self.assertIs(self.launches.calls[-1].takeover, True)

    def test_a_quota_move_is_cancelled_when_the_owner_pins_another_profile_while_it_is_queued(self):
        svc, sid, _ = self.reserved_move()
        svc.set_pin("spare", True)
        self.drain()
        self.assert_move_cancelled(svc, sid)
        self.assert_waits_to_wake(svc, sid)

    def test_a_quota_move_is_cancelled_when_the_managers_quota_resets_during_the_permission_read(self):
        svc, sid, _ = self.reserved_move()
        self.during_permission_read(svc, lambda: self.append(svc, [(
            capacity.READING, None, {"profile": "work", **self.weekly(0.1)})]))
        self.drain()
        self.assert_move_cancelled(svc, sid)
        self.poll(svc, 700)
        self.assertEqual(len(self.revives()), 1)
        self.assertEqual([c.profile for c in self.launches.calls], ["work"])

    def test_a_late_refusal_from_an_account_the_manager_left_is_no_reason_to_move(self):
        svc, sid = self.start_out(listed=False, readings=False)
        self.append(svc, [
            (capacity.READING, None, {
                "profile": "work", "account": "acct-2", **self.weekly(0.1)}),
            (signin.READING, None, {
                "profile": "work", "state": "signed_in", "ends_at": None,
                "account": "b@example.invalid", "account_seq": 0,
                "left_account": "a@example.invalid", "left_reading": "acct-1"}),
            (capacity.READING, None, {
                "profile": "work", "account": "acct-1", **self.exhausted(RESET)}),
            (capacity.READING, None, {"profile": "home", "account": "acct-3", **self.weekly(0.1)})])
        svc.poll_sessions()
        self.gone(svc)
        self.poll(svc, 600)
        self.assertEqual([c.profile for c in self.launches.calls], ["work"])
        self.assertEqual(len(self.revives()), 1)

    def test_a_quota_move_is_cancelled_when_its_target_becomes_a_duplicate_of_a_third_profile(self):
        def setup(svc):
            self.append(svc, [
                (capacity.READING, None, {"profile": "abba", **self.weekly(0.5)}),
                self.signed("abba", "a@example.invalid"),
                self.signed("home", "b@example.invalid")])

        svc, sid, _ = self.reserved_move(
            spare=False, setup=setup, work=None, home=None, abba=None)
        self.append(svc, [self.signed("abba", "b@example.invalid")])
        self.drain()
        self.assert_move_cancelled(svc, sid)
        self.assert_waits_to_wake(svc, sid)

    def test_a_withdrawn_sprint_leaves_the_quota_mark(self):
        svc, sid = self.start_out()
        self.poll(svc, 300)
        self.assertEqual(svc._quota_held, {sid})
        svc.withdraw_goal("owner/p01", sid)
        self.poll(svc, 600)
        self.assertEqual(svc._quota_held, set())

    def test_a_message_left_during_the_wait_is_the_one_send_after_the_reset(self):
        for name in ("queued", "relay finished first"):
            with self.subTest(name):
                self.setUp()
                svc, sid = self.start_out()
                self.now[0] = T0 + 600
                svc.send_message("owner/p01", sid, "hello")
                self.assertEqual((svc._nudging, self.queued.jobs), (set(), []))
                self.drain()
                self.assertEqual(self.nudges, [])
                self.assertEqual(self.messaged(), [])
                self.poll(svc, 1800)
                self.assertEqual(self.nudges, [])
                if name == "queued":
                    self.poll(svc, 3600)
                else:
                    self.now[0] = T0 + 3600
                    svc.renudge()
                    self.drain()
                    svc.finish_stops()
                    svc.revive()
                    svc.nudge_idle()
                    self.drain()
                self.assertEqual([n.route for n in self.nudges], ["relay"])
                (row,) = self.messaged()
                self.assertIs(row["ok"], True)
                self.assertIs(row["resumed"], True)
                self.assertEqual(self.rows("manager.nudged"), [])
                self.assertEqual(self.said(svc).count(RESUMED), 1)

    def test_a_reading_that_arrives_during_the_listing_holds_the_send(self):
        for name in ("relay", "wake"):
            with self.subTest(name):
                self.setUp()

                def listing():
                    if self.out_now:
                        self.out_now = False
                        self.out_readings(self.svc)
                    return dict(self.listed)

                self.svc, sid = self.start_out(listed=name == "relay", readings=False,
                                               listing=listing)
                svc = self.svc
                self.now[0] = T0 + 60
                self.out_now = True
                svc.send_message("owner/p01", sid, "hello")
                self.drain()
                self.assertEqual(self.nudges, [])
                self.assertEqual(self.messaged(), [])
                self.assertEqual(svc._nudging, set())
                self.poll(svc, 3600)
                (sent,) = self.nudges
                self.assertEqual(sent.route, name)
                (row,) = self.messaged()
                self.assertIs(row["ok"], True)
                self.assertIs(row["resumed"], True)

    def test_no_wake_while_every_account_is_out_and_the_wake_after_the_reset_resumes(self):
        svc, sid = self.start_out(listed=False, readings=False)
        self.readings(svc, lambda p: self.exhausted(RESET))
        svc.poll_sessions()
        self.gone(svc)
        for seconds in (120, 600, 3599):
            self.poll(svc, seconds)
        self.assertEqual(self.revives(), [])
        self.assertEqual(self.rows("manager.woken"), [])
        self.poll(svc, 3600)
        self.assertEqual(self.revives(), [
            nudge.Nudge(sid, "revive", self.name(sid), "s-1", "work", "/srv/p01")])
        self.assertEqual(self.rows("manager.woken"), [
            {"sprint_id": sid, "goal": GOAL, "session_id": "s-1", "ok": True, "resumed": True,
             "permission": {"mode": "auto", "reason": permission.UNRESOLVED}}])
        said = self.said(svc)
        self.assertEqual(said.count(RESUMED), 1)
        self.assertEqual(said.count("The manager of " + PARTS["title"] + " was restarted"), 0)
