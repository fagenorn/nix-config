"""The service tells an idle manager to go on and waits out a quota (#929).

Run: just agent-workflow-tests
"""
import json
import threading
from datetime import datetime, timezone
from unittest import mock

from agent_tools.console import nudge, service, sprints

from . import console_test_support as support
from .test_console_questions import ROUND
from .test_console_reports import REPORT
from .test_console_revive_service import GOAL, T0, ReviveCase

RESET = int(T0) + 3600
RESUMED = GOAL + " resumed after the quota reset"
JSON = {"Content-Type": "application/json"}


class IdleCase(ReviveCase):
    """The set-up and helpers of the idle suites; it holds no test."""

    def setUp(self):
        super().setUp()
        self.out_now = False
        self.svc = None
        self.arrival = 0

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

    def test_a_working_manager_or_a_moving_delivery_gets_no_nudge(self):
        seen = {"session_id": "s-1", "run_id": "wf_1", "moved_ms": int((T0 + 200) * 1000),
                "issues": [{"issue": 12, "stage": "building", "task": None, "tasks": None}]}
        for name in ("working", "moving", "finished"):
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
                self.append(svc, [("delivery.seen", "owner/p01", seen)])
                if name == "finished":
                    self.now[0] = T0 + 250
                    self.append(svc, [("delivery.gone", "owner/p01",
                                       {"session_id": "s-1", "run_id": "wf_1"})])
                self.poll(svc, 300)
                self.assertEqual(self.continues(), [])
                self.poll(svc, 499.999)
                self.assertEqual(self.continues(), [])
                self.poll(svc, 500)
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
        self.assertEqual(item["headline"], "the manager has stopped making progress on " + GOAL)
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

    def test_no_wake_while_the_account_is_out_and_the_wake_after_the_reset_resumes(self):
        svc, sid = self.start_out(listed=False)
        self.gone(svc)
        for seconds in (120, 600, 3599):
            self.poll(svc, seconds)
        self.assertEqual(self.revives(), [])
        self.assertEqual(self.rows("manager.woken"), [])
        self.poll(svc, 3600)
        self.assertEqual(self.revives(), [
            nudge.Nudge(sid, "revive", self.name(sid), "s-1", "work", "/srv/p01")])
        self.assertEqual(self.rows("manager.woken"), [
            {"sprint_id": sid, "goal": GOAL, "session_id": "s-1", "ok": True, "resumed": True}])
        said = self.said(svc)
        self.assertEqual(said.count(RESUMED), 1)
        self.assertEqual(said.count("The manager of " + GOAL + " was restarted"), 0)
