"""The owner's messages to a sprint and the manager's inbox and reply routes (#889).

Run: just agent-workflow-tests
"""
import contextlib
import io
import json
import dataclasses
import threading
import time
import unittest
from datetime import datetime, timezone

from agent_tools.console import manager, nudge, permission, sessions, sprints, write_guard
from agent_tools.console.event_log import EventLog

from . import console_test_support as support
from .test_console_answer import view_of
from .test_console_view import (
    MESSAGE_SID, message_at, message_row, message_rows, messaged_row, nudged_row, state)
from .test_console_writes import Case
from agent_tools.console import event_log
from agent_tools.console.sprints import (
    NUDGE_ACTION_TEXT, RETRY_ACTION_TEXT, TURN_ACTION_TEXT, sprint_states)
from agent_tools.console.view import derive_view
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)

BRIEF = "/api/brief"
APPROVE = "/api/approve"
REPLY = "/api/reply"
MESSAGE = "/api/message"
INBOX = "/api/inbox"
MESSAGE_REPLY = "/api/message-reply"
GOAL_TEXT = "make the importer resumable"
PARTS = {"title": "Importer resumes after a crash",
         "done": "the importer resumes after a crash", "excluded": ["no new formats"],
         "slices": ["checkpoint", "resume"], "risks": ["partial writes"],
         "asks": ["which store?"]}
JSON = {"Content-Type": "application/json"}
TEXT = "leave the importer's schema alone"
ANSWER = "kept the schema; moved the change to the reader"


class MessageRouteTest(Case):
    def open(self):
        support.write_registry(self.registry, support.entries(2))
        return self.start()

    def secret(self, sid):
        return (self.store.parent / "sprint-secrets" / sid).read_text().removesuffix("\n")

    def brief(self, svc, sid, secret, parts=PARTS, **headers):
        body = json.dumps({"sprint_id": sid, "secret": secret, "brief": parts}).encode()
        return support.post_page(svc.address, BRIEF, {**JSON, **headers}, body)

    def send(self, svc, sid, parts=PARTS):
        status, _, body = self.brief(svc, sid, self.secret(sid), parts)
        self.assertEqual(status, 200, body)
        return json.loads(body)["version"]

    def page(self, svc, path, body, **headers):
        return support.post_page(svc.address, path, self.own(svc, **{**JSON, **headers}),
                                 json.dumps(body).encode() if isinstance(body, dict) else body)

    def approve(self, svc, sid, version, project_id="owner/p01"):
        return self.page(svc, APPROVE, {"project_id": project_id, "sprint_id": sid,
                                        "version": version})

    def reply(self, svc, sid, version, reply, project_id="owner/p01"):
        return self.page(svc, REPLY, {"project_id": project_id, "sprint_id": sid,
                                      "version": version, "reply": reply})

    def message(self, svc, sid, text, project_id="owner/p01", **headers):
        body = json.dumps({"project_id": project_id, "sprint_id": sid, "text": text}).encode()
        return support.post_page(svc.address, MESSAGE, self.own(svc, **{**JSON, **headers}), body)

    def post(self, svc, path, body, headers=JSON):
        return support.post_page(svc.address, path, headers,
                                 json.dumps(body).encode() if isinstance(body, dict) else body)

    def inbox(self, svc, sid, secret, **headers):
        return self.post(svc, INBOX, {"sprint_id": sid, "secret": secret}, {**JSON, **headers})

    def answer(self, svc, sid, secret, message, reply, **headers):
        return self.post(svc, MESSAGE_REPLY, {"sprint_id": sid, "secret": secret,
                                              "message": message, "reply": reply},
                         {**JSON, **headers})

    def kinds(self):
        return [row[2] for row in support.log_rows(self.store)]

    def sprint_state(self, svc, sid):
        with svc._ingest:
            return svc._sprints[sid]

    def settled(self, svc):
        """A sprint with a change request, an approval and a text, in that order."""
        sid = svc.state_goal("owner/p01", GOAL_TEXT)
        self.send(svc, sid)
        self.assertEqual(self.reply(svc, sid, 1, "smaller slices")[0], 204)
        self.send(svc, sid)
        self.assertEqual(self.approve(svc, sid, 2)[0], 204)
        self.assertEqual(self.message(svc, sid, TEXT)[0], 204)
        return sid

    def test_an_approval_a_change_request_and_a_text_are_returned_once_in_order(self):
        svc = self.open()
        sid = self.settled(svc)
        status, headers, body = self.inbox(svc, sid, self.secret(sid))
        self.assertEqual((status, headers["Content-Type"]), (200, "application/json"))
        answer = json.loads(body)
        self.assertEqual(
            [(m["kind"], m["text"], m["version"]) for m in answer["messages"]],
            [("changes", "smaller slices", 1), ("approved", None, 2), ("text", TEXT, None)])
        ids = [m["id"] for m in answer["messages"]]
        self.assertEqual(ids, sorted(set(ids)))
        self.assertEqual(body, json.dumps(answer, sort_keys=True, separators=(",", ":")).encode())
        reads = [row for row in support.log_rows(self.store) if row[2] == "sprint.read"]
        self.assertEqual(len(reads), 1)
        self.assertEqual(json.loads(reads[0][4]), {"sprint_id": sid, "through": ids[-1]})
        again = self.assert_unchanged(svc, lambda: self.inbox(svc, sid, self.secret(sid)))
        self.assertEqual((again[0], json.loads(again[2])), (200, {"messages": []}))

    def test_a_message_without_the_token_or_from_another_origin_is_refused_and_appends_nothing(self):
        svc = self.open()
        sid = svc.state_goal("owner/p01", GOAL_TEXT)
        origin = f"http://127.0.0.1:{svc.address[1]}"
        cases = [({"Origin": origin}, b"token refused"),
                 ({"Origin": origin, write_guard.TOKEN_HEADER: "wrong"}, b"token refused"),
                 ({"Origin": "http://example.com", write_guard.TOKEN_HEADER: self.token()},
                  b"origin refused"),
                 ({write_guard.TOKEN_HEADER: self.token()}, b"origin refused")]
        body = json.dumps({"project_id": "owner/p01", "sprint_id": sid, "text": TEXT}).encode()
        for headers, text in cases:
            with self.subTest(headers=headers):
                got = self.assert_unchanged(svc, lambda: support.post_page(
                    svc.address, MESSAGE, {**JSON, **headers}, body))
                self.assertEqual((got[0], got[2]), (403, text + b"\n"))
        before = support.log_rows(self.store)
        got = self.message(svc, sid, TEXT)
        self.assertEqual((got[0], got[2]), (204, b""))
        rows = support.log_rows(self.store)
        self.assertEqual(rows[:len(before)], before)
        (row,) = rows[len(before):]
        self.assertEqual(row[2], "sprint.messaged")
        self.assertEqual(json.loads(row[4]), {"sprint_id": sid, "goal": GOAL_TEXT, "text": TEXT})

    def test_message_refusals_append_nothing(self):
        svc = self.open()
        sid = svc.state_goal("owner/p01", GOAL_TEXT)
        gone = svc.state_goal("owner/p01", GOAL_TEXT)
        svc.withdraw_goal("owner/p01", gone)
        valid = {"project_id": "owner/p01", "sprint_id": sid, "text": TEXT}
        table = [
            ("withdrawn", {**valid, "sprint_id": gone}, 409, b"this sprint is not open"),
            ("another project", {**valid, "project_id": "owner/p00"}, 409,
             b"this sprint is not open"),
            ("blank", {**valid, "text": "   "}, 409, b"write the message first"),
            ("too long", {**valid, "text": "x" * 2001}, 409,
             b"a message is at most 2000 characters"),
            ("missing text", {"project_id": "owner/p01"}, 400, b"bad message"),
            ("too large", b" " * 16385, 413, b"too large"),
        ]
        for name, body, status, text in table:
            with self.subTest(name):
                got = self.assert_unchanged(svc, lambda: self.page(svc, MESSAGE, body))
                self.assertEqual((got[0], got[2]), (status, text + b"\n"))

    def test_the_inbox_and_reply_routes_refuse_a_page_and_a_wrong_secret(self):
        svc = self.open()
        sid = self.settled(svc)
        gone = svc.state_goal("owner/p01", GOAL_TEXT)
        former = self.secret(gone)
        svc.withdraw_goal("owner/p01", gone)
        right = self.secret(sid)
        origin = {"Origin": f"http://127.0.0.1:{svc.address[1]}"}
        table = [
            ("inbox page", lambda: self.inbox(svc, sid, right, **origin), 403, b"origin refused"),
            ("reply page", lambda: self.answer(svc, sid, right, 1, "r", **origin), 403,
             b"origin refused"),
            ("inbox secret", lambda: self.inbox(svc, sid, "A" * 43), 403, b"secret refused"),
            ("reply secret", lambda: self.answer(svc, sid, "A" * 43, 1, "r"), 403,
             b"secret refused"),
            ("inbox withdrawn", lambda: self.inbox(svc, gone, former), 409,
             b"this sprint is not open"),
            ("reply withdrawn", lambda: self.answer(svc, gone, former, 1, "r"), 409,
             b"this sprint is not open"),
            ("inbox extra key", lambda: self.post(
                svc, INBOX, {"sprint_id": sid, "secret": right, "more": 1}), 400, b"bad inbox"),
            ("reply extra key", lambda: self.post(
                svc, MESSAGE_REPLY, {"sprint_id": sid, "secret": right, "message": 1,
                                     "reply": "r", "more": 1}), 400, b"bad message reply"),
        ]
        for name, action, status, text in table:
            with self.subTest(name):
                got = self.assert_unchanged(svc, action)
                self.assertEqual((got[0], got[2]), (status, text + b"\n"))

    def test_a_reply_with_the_secret_is_recorded_under_its_message_and_without_it_nothing_is(self):
        svc = self.open()
        sid = self.settled(svc)
        secret = self.secret(sid)
        (text,) = [m for m in self.sprint_state(svc, sid).messages if m.kind == "text"]
        got = self.assert_unchanged(svc, lambda: self.answer(svc, sid, "A" * 43,
                                                             text.message_id, ANSWER))
        self.assertEqual(got[0], 403)
        for message, reply, status, refusal in (
                (999, ANSWER, 409, b"this message is not known"),
                (text.message_id, "", 409, b"write the reply first")):
            got = self.assert_unchanged(
                svc, lambda: self.answer(svc, sid, secret, message, reply))
            self.assertEqual((got[0], got[2]), (status, refusal + b"\n"))
        status, headers, body = self.answer(svc, sid, secret, text.message_id, ANSWER)
        self.assertEqual((status, headers["Content-Type"]), (200, "application/json"))
        row = support.log_rows(self.store)[-1]
        self.assertEqual((row[2], json.loads(row[4])),
                         ("sprint.answered", {"sprint_id": sid, "message": text.message_id,
                                              "reply": ANSWER}))
        self.assertEqual(json.loads(body), {"at": row[1]})
        (folded,) = [m for m in self.sprint_state(svc, sid).messages
                     if m.message_id == text.message_id]
        self.assertEqual((folded.reply, folded.reply_at), (ANSWER, row[1]))

    def test_messages_and_reads_survive_a_restart(self):
        svc = self.open()
        sid = svc.state_goal("owner/p01", GOAL_TEXT)
        self.assertEqual(self.message(svc, sid, "one")[0], 204)
        self.assertEqual(self.message(svc, sid, "two")[0], 204)
        secret = self.secret(sid)
        first = json.loads(self.inbox(svc, sid, secret)[2])
        self.assertEqual([m["text"] for m in first["messages"]], ["one", "two"])
        self.assertEqual(self.message(svc, sid, "three")[0], 204)
        svc.close()
        second = self.start()
        got = json.loads(self.inbox(second, sid, secret)[2])
        self.assertEqual([m["text"] for m in got["messages"]], ["three"])
        self.assertEqual(json.loads(self.inbox(second, sid, secret)[2]), {"messages": []})

    def test_the_secret_and_the_owners_text_appear_in_no_stderr_line(self):
        svc = self.open()
        sid = svc.state_goal("owner/p01", GOAL_TEXT)
        secret = self.secret(sid)
        private = "my private words about the importer"
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            self.assertEqual(self.message(svc, sid, private, project_id="owner/p00")[0], 409)
            self.assertEqual(self.message(svc, sid, " " * 3)[0], 409)
            self.assertEqual(self.inbox(svc, sid, secret + "x")[0], 403)
            self.assertEqual(self.answer(svc, sid, secret, 999, private)[0], 409)
            self.assertEqual(self.answer(svc, sid, secret + "x", 1, private)[0], 403)
        lines = stderr.getvalue()
        self.assertIn("console: message_refused", lines)
        self.assertIn(f"console: inbox_refused {sid} secret refused", lines)
        self.assertIn("console: message_reply_refused", lines)
        self.assertNotIn(secret, lines)
        self.assertNotIn(private, lines)


T0 = 1_800_000_000.0
BYPASS_MODE = permission.Permission(permission.BYPASS, permission.RULES_IN_PLACE)
AUTO_MODE = permission.Permission(permission.AUTO, permission.NOT_DECLARED)


class NudgeServiceTest(MessageRouteTest):
    """The service nudges a running manager, wakes a stopped one and counts failures (#889)."""

    def setUp(self):
        super().setUp()
        support.write_registry(self.registry, support.entries(2))
        self.queued = support.Queued()
        self.nudges = []
        self.outcomes = []
        self.listed = {}
        self.during = []
        self.stops = []
        self.now = [T0]

    def stop_session(self, session_id, profile):
        self.stops.append((session_id, len(self.nudges)))
        self.listed.pop(session_id, None)

    def log_clock(self):
        return datetime.fromtimestamp(self.now[0], timezone.utc).isoformat(timespec="microseconds")

    def nudger(self, sent):
        self.nudges.append(sent)
        if self.during:
            self.during.pop(0)()
        outcome = self.outcomes.pop(0) if self.outcomes else None
        if outcome is not None:
            raise nudge.NudgeFailed(outcome)

    def begin(self, **overrides):
        support.sign_in(self.store, "work")
        options = dict(
            launcher=support.Launches(), profile_dirs=[support.profile_dir(self.store, "work")],
            dispatch=self.queued, nudger=self.nudger, listing=lambda: dict(self.listed),
            clock=lambda: self.now[0], log_clock=self.log_clock, session_poll_seconds=3600)
        return self.start(**{**options, **overrides})

    def running(self, svc):
        """A sprint whose manager is started and listed as running."""
        sid = svc.state_goal("owner/p01", GOAL_TEXT)
        self.queued.run_next()
        self.listed["s-1"] = sessions.Observation(
            "s-1", "/srv/p01", 1, "idle", None, manager.session_name("owner/p01", sid), None)
        return sid

    def nudged(self):
        return [(row[0], json.loads(row[4])) for row in support.log_rows(self.store)
                if row[2] == "sprint.nudged"]

    def name(self, sid):
        return manager.session_name("owner/p01", sid)

    def started(self, svc, project, session_id, goal):
        """A sprint of `project` whose manager is started and listed as running under `session_id`."""
        sid = svc.state_goal(project, goal)
        self.queued.run_next()
        self.listed[session_id] = sessions.Observation(
            session_id, "/srv/" + project.split("/")[1], 1, "idle", None,
            manager.session_name(project, sid), None)
        return sid

    def drain(self):
        while self.queued.jobs:
            self.queued.run_next()

    def notice_nudged(self):
        return [json.loads(row[4]) for row in support.log_rows(self.store)
                if row[2] == "notice.nudged"]

    def kinds_after_start(self):
        return [row[2] for row in support.log_rows(self.store)
                if row[2] in ("sprint.nudged", "notice.nudged")]

    def test_an_owner_notice_nudges_each_running_manager_of_its_project_once(self):
        svc = self.begin()
        a = self.started(svc, "owner/p01", "s-1", "first goal")
        b = self.started(svc, "owner/p01", "s-2", "second goal")
        self.started(svc, "owner/p00", "s-3", "third goal")
        n = svc.post_owner_notice("owner/p01", "routes are frozen until Friday")
        self.drain()
        self.assertEqual(
            sorted((x.sprint_id, x.route, x.session_id) for x in self.nudges),
            sorted([(a, "relay", "s-1"), (b, "relay", "s-2")]))
        self.assertNotIn("frozen", repr(self.nudges))
        self.assertEqual(
            sorted(self.notice_nudged(), key=lambda row: row["sprint_id"]),
            sorted([{"sprint_id": a, "notice": n, "route": "relay", "ok": True},
                    {"sprint_id": b, "notice": n, "route": "relay", "ok": True}],
                   key=lambda row: row["sprint_id"]))
        self.assertEqual(self.nudged(), [])
        svc.withdraw_owner_notice("owner/p01", n)
        self.assertEqual(self.queued.jobs, [])
        self.assertEqual(len(self.nudges), 2)

    def test_a_queued_message_nudge_covers_the_notice_and_a_manager_not_started_gets_none(self):
        svc = self.begin()
        a = self.started(svc, "owner/p01", "s-1", "first goal")
        c = self.started(svc, "owner/p01", "s-3", "third goal")
        svc.send_message("owner/p01", c, TEXT)
        b = svc.state_goal("owner/p01", "second goal")
        before = len(self.queued.jobs)
        n = svc.post_owner_notice("owner/p01", "routes are frozen until Friday")
        self.assertEqual(len(self.queued.jobs), before + 1)
        self.drain()
        by_sprint = {}
        for sent in self.nudges:
            by_sprint.setdefault(sent.sprint_id, []).append(sent.route)
        self.assertEqual(by_sprint, {a: ["relay"], c: ["relay"]})
        self.assertEqual(self.notice_nudged(), [
            {"sprint_id": a, "notice": n, "route": "relay", "ok": True}])
        self.assertEqual([row["sprint_id"] for _, row in self.nudged()], [c])
        self.assertNotIn(b, by_sprint)

    def test_a_message_stored_during_a_notice_nudge_is_nudged_right_after(self):
        svc = self.begin()
        a = self.started(svc, "owner/p01", "s-1", "first goal")
        n = svc.post_owner_notice("owner/p01", "routes are frozen until Friday")
        message = svc.send_message("owner/p01", a, TEXT)
        self.drain()
        self.assertEqual([(x.sprint_id, x.route) for x in self.nudges],
                         [(a, "relay"), (a, "relay")])
        self.assertEqual(self.kinds_after_start(), ["notice.nudged", "sprint.nudged"])
        self.assertEqual(self.notice_nudged(), [
            {"sprint_id": a, "notice": n, "route": "relay", "ok": True}])
        self.assertEqual([row["through"] for _, row in self.nudged()], [message])

    def test_a_notice_posted_after_the_inbox_read_of_a_running_nudge_is_nudged_after_it(self):
        svc = self.begin()
        a = self.started(svc, "owner/p01", "s-1", "first goal")
        svc.send_message("owner/p01", a, TEXT)
        posted = []
        self.during = [lambda: posted.append(
            svc.post_owner_notice("owner/p01", "routes are frozen until Friday"))]
        self.drain()
        self.assertEqual(len(self.nudges), 2)
        self.assertEqual(self.kinds_after_start(), ["sprint.nudged", "notice.nudged"])
        self.assertTrue(self.nudged()[0][1]["ok"])
        self.assertEqual(self.notice_nudged(), [
            {"sprint_id": a, "notice": posted[0], "route": "relay", "ok": True}])

    def test_a_failed_message_nudge_leaves_the_notice_its_own_nudge(self):
        svc = self.begin()
        a = self.started(svc, "owner/p01", "s-1", "first goal")
        svc.send_message("owner/p01", a, TEXT)
        n = svc.post_owner_notice("owner/p01", "routes are frozen until Friday")
        self.outcomes = ["boom"]
        with contextlib.redirect_stderr(io.StringIO()):
            self.drain()
        self.assertEqual(len(self.nudges), 2)
        self.assertEqual(self.kinds_after_start(), ["sprint.nudged", "notice.nudged"])
        self.assertEqual(self.nudged()[0][1]["ok"], False)
        self.assertEqual(self.nudged()[0][1]["reason"], "boom")
        self.assertEqual(self.notice_nudged(), [
            {"sprint_id": a, "notice": n, "route": "relay", "ok": True}])

    def test_a_notice_due_while_another_reservation_holds_the_sprint_is_sent_by_renudge(self):
        svc = self.begin()
        a = self.started(svc, "owner/p01", "s-1", "first goal")
        svc._nudging.add(a)
        n = svc.post_owner_notice("owner/p01", "routes are frozen until Friday")
        self.assertEqual(self.queued.jobs, [])
        svc._nudging.discard(a)
        svc.renudge()
        self.drain()
        self.assertEqual([(x.sprint_id, x.route) for x in self.nudges], [(a, "relay")])
        self.assertEqual(self.notice_nudged(), [
            {"sprint_id": a, "notice": n, "route": "relay", "ok": True}])

    def test_a_failed_notice_nudge_is_recorded_and_counts_no_failure(self):
        svc = self.begin()
        a = self.started(svc, "owner/p01", "s-1", "first goal")
        n = svc.post_owner_notice("owner/p01", "routes are frozen until Friday")
        self.outcomes = ["boom"]
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            self.drain()
        self.assertEqual(self.notice_nudged(), [
            {"sprint_id": a, "notice": n, "route": "relay", "ok": False, "reason": "boom"}])
        self.assertEqual(self.sprint_state(svc, a).failed_nudges, 0)
        self.assertIn(f"console: notice_nudge_failed {a} boom", stderr.getvalue())
        self.now[0] += 120
        svc.renudge()
        self.drain()
        self.assertEqual(len(self.nudges), 1)

    def test_no_nudger_means_no_notice_nudge(self):
        svc = self.begin(nudger=None)
        self.started(svc, "owner/p01", "s-1", "first goal")
        svc.post_owner_notice("owner/p01", "routes are frozen until Friday")
        self.assertEqual(self.queued.jobs, [])
        self.assertEqual(self.notice_nudged(), [])
        self.assertEqual(svc._notice_due, {})

    def test_a_notice_due_for_a_sprint_whose_project_was_unregistered_is_dropped_not_looped(self):
        svc = self.begin()
        sid = self.started(svc, "owner/p01", "s-1", "first goal")
        svc.post_owner_notice("owner/p01", "routes are frozen until Friday")
        support.write_registry(self.registry, support.entries(2)[:1])
        svc.refresh()
        self.assertNotIn("owner/p01", svc._states)
        for _ in range(200):
            if not self.queued.jobs:
                break
            self.queued.run_next()
        self.assertEqual(self.queued.jobs, [])
        self.assertEqual(svc._notice_due, {})
        self.assertNotIn(sid, svc._nudging)
        self.assertEqual(self.nudges, [])
        svc.renudge()
        self.assertEqual(self.queued.jobs, [])

    def test_a_message_to_a_running_manager_is_relayed_with_the_fixed_sentence_only(self):
        svc = self.begin()
        sid = self.running(svc)
        svc.send_message("owner/p01", sid, TEXT)
        self.queued.run_next()
        self.assertEqual(self.nudges, [nudge.Nudge(
            sid, "relay", self.name(sid), "s-1", "work", "/srv/p01")])
        self.assertNotIn("importer", repr(self.nudges[0]))
        message = self.sprint_state(svc, sid).messages[-1]
        last = support.log_rows(self.store)[-1]
        self.assertEqual((last[2], json.loads(last[4])), (
            "sprint.nudged",
            {"sprint_id": sid, "through": message.message_id, "covers": [message.message_id],
             "route": "relay", "ok": True}))
        self.assertIsNotNone(message.delivered_at)
        self.assertEqual(self.queued.jobs, [])

    def test_a_listed_session_is_relayed_to_by_its_lowest_session_id(self):
        svc = self.begin()
        sid = self.running(svc)
        self.listed["s-0"] = sessions.Observation(
            "s-0", "/srv/p01", 2, "idle", None, self.name(sid), None)
        svc.send_message("owner/p01", sid, TEXT)
        self.queued.run_next()
        self.assertEqual([(n.route, n.session_id) for n in self.nudges], [("relay", "s-0")])

    def test_a_stopped_manager_is_woken_in_place(self):
        first = self.begin()
        sid = self.running(first)
        first.close()
        log = EventLog(self.store, clock=self.log_clock)
        log.append([("session.seen", "owner/p01", {
            "session_id": "s-1", "cwd": "/srv/p01", "repo": "/srv/p01", "state": "idle",
            "name": self.name(sid)})])
        log.close()
        self.listed.clear()
        svc = self.begin()
        svc.send_message("owner/p01", sid, TEXT)
        self.queued.run_next()
        self.assertEqual(self.nudges, [nudge.Nudge(
            sid, "wake", self.name(sid), "s-1", "work", "/srv/p01")])
        ((_, row),) = self.nudged()
        self.assertEqual((row["route"], row["ok"]), ("wake", True))

    def assert_message_wake_rewrites_settings(self, svc, sid):
        path = manager.settings_path(svc._sprint_secrets, sid)
        path.write_text(json.dumps({"env": {"CONSOLE_SPRINT_ID": sid}}))
        svc.send_message("owner/p01", sid, TEXT)
        self.queued.run_next()
        self.assertEqual([n.route for n in self.nudges], ["wake"])
        secret = (svc._sprint_secrets / sid).read_text().removesuffix("\n")
        launch = manager.new_launch(
            sid, "owner/p01", "g", "/srv/p01", "work", secret, svc._sprint_secrets)
        self.assertEqual(path.read_text(),
                         json.dumps(manager.settings_document(launch.env, AUTO_MODE)))

    def test_a_wake_of_a_session_the_full_listing_shows_writes_the_settings_file_again(self):
        svc, sid = self.stopped_with_full_listing(frozenset({"s-1"}))
        self.assert_message_wake_rewrites_settings(svc, sid)

    def test_a_wake_with_name_and_settings_writes_the_settings_file_again(self):
        svc, sid = self.stopped_with_full_listing(frozenset())
        self.assert_message_wake_rewrites_settings(svc, sid)

    def test_a_wake_of_a_sprint_whose_secret_is_missing_is_not_sent(self):
        svc, sid = self.stopped_with_full_listing(frozenset())
        path = manager.settings_path(svc._sprint_secrets, sid)
        path.write_text(json.dumps({"env": {"CONSOLE_SPRINT_ID": sid}}))
        (svc._sprint_secrets / sid).unlink()
        svc.send_message("owner/p01", sid, TEXT)
        self.queued.run_next()
        self.assertEqual(self.nudges, [])
        ((_, row),) = self.nudged()
        self.assertFalse(row["ok"])
        self.assertEqual(row["reason"], "the sprint's secret is missing")
        self.assertNotIn("permission", row)

    def test_a_sprint_withdrawn_during_the_wake_leaves_no_settings_file_and_sends_no_wake(self):
        svc, sid = self.stopped_with_full_listing(frozenset())
        path = manager.settings_path(svc._sprint_secrets, sid)
        path.write_text(json.dumps({"env": {"CONSOLE_SPRINT_ID": sid}}))

        def withdrawn(profile, cwd):
            svc.withdraw_goal("owner/p01", sid)
            return frozenset()

        svc._full_listing = withdrawn
        svc.send_message("owner/p01", sid, TEXT)
        self.queued.run_next()
        self.assertEqual(self.nudges, [])
        self.assertFalse(path.exists())
        self.assertFalse((svc._sprint_secrets / sid).exists())

    def stopped_with_full_listing(self, outcome, **overrides):
        """A restarted service whose manager is unlisted; `outcome` is what its full listing gives."""
        overrides.setdefault("permission_reader", lambda project_id, root: AUTO_MODE)
        first = self.begin(**overrides)
        sid = self.running(first)
        first.close()
        log = EventLog(self.store, clock=self.log_clock)
        log.append([("session.seen", "owner/p01", {
            "session_id": "s-1", "cwd": "/srv/p01", "repo": "/srv/p01", "state": "idle",
            "name": self.name(sid)})])
        log.close()
        self.listed.clear()
        self.full_calls = []

        def full(profile, cwd):
            self.full_calls.append((profile, cwd))
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        svc = self.begin(full_listing=full, **overrides)
        return svc, sid

    def lock_free_reader(self, modes, free):
        """A reader of `modes[-1]` that records into `free` whether the ingest lock was free."""
        def reader(project_id, root):
            def probe_lock():
                if self.svc._ingest.acquire(timeout=1):
                    self.svc._ingest.release()
                    free.append(True)
                else:
                    free.append(False)

            if self.svc is not None:  # the first service's launch runs before there is one to probe
                thread = threading.Thread(target=probe_lock)
                thread.start()
                thread.join()
            return modes[-1]

        return reader

    def test_a_message_wake_rereads_the_projects_mode(self):
        modes, free = [BYPASS_MODE], []
        self.svc = None
        svc, sid = self.stopped_with_full_listing(
            frozenset(), permission_reader=self.lock_free_reader(modes, free))
        self.svc = svc
        modes.append(AUTO_MODE)
        free.clear()
        svc.send_message("owner/p01", sid, TEXT)
        self.queued.run_next()
        self.assertEqual(free, [True])
        path = manager.settings_path(svc._sprint_secrets, sid)
        self.assertEqual(json.loads(path.read_text())["permissions"], {"defaultMode": "auto"})
        ((_, row),) = self.nudged()
        self.assertEqual(row["route"], "wake")
        self.assertEqual(row["permission"], {
            "mode": "auto", "reason": "no production rules declared"})
        self.assertEqual(self.sprint_state(svc, sid).permission, AUTO_MODE)

    def test_a_notice_wake_rereads_and_logs_the_projects_mode(self):
        modes = [BYPASS_MODE]
        svc, sid = self.stopped_with_full_listing(
            frozenset(), permission_reader=lambda project_id, root: modes[-1])
        modes.append(AUTO_MODE)
        svc.post_owner_notice("owner/p01", "routes are frozen until Friday")
        self.drain()
        self.assertEqual([n.route for n in self.nudges], ["wake"])
        path = manager.settings_path(svc._sprint_secrets, sid)
        self.assertEqual(json.loads(path.read_text())["permissions"], {"defaultMode": "auto"})
        self.assertEqual(self.notice_nudged()[-1]["route"], "wake")
        self.assertEqual(self.notice_nudged()[-1]["permission"], {
            "mode": "auto", "reason": "no production rules declared"})
        self.assertEqual(self.sprint_state(svc, sid).permission, AUTO_MODE)
        self.listed["s-1"] = sessions.Observation(
            "s-1", "/srv/p01", 1, "idle", None, self.name(sid), None)
        modes.append(BYPASS_MODE)
        svc.send_message("owner/p01", sid, TEXT)
        self.drain()
        last = self.nudged()[-1][1]
        self.assertEqual(last["route"], "relay")
        self.assertNotIn("permission", last)
        self.assertEqual(self.sprint_state(svc, sid).permission, AUTO_MODE)

    def test_a_relay_to_a_manager_last_logged_in_bypass_comes_from_a_bypass_sender(self):
        svc = self.begin(permission_reader=lambda project_id, root: BYPASS_MODE)
        sid = self.running(svc)
        self.assertEqual(self.sprint_state(svc, sid).permission, BYPASS_MODE)
        svc.send_message("owner/p01", sid, TEXT)
        self.queued.run_next()
        self.assertEqual(self.nudges, [nudge.Nudge(
            sid, "relay", self.name(sid), "s-1", "work", "/srv/p01", sender_bypass=True)])
        self.assertNotIn("permission", self.nudged()[-1][1])

    def test_a_relay_to_a_manager_last_logged_in_auto_comes_from_a_prompting_sender(self):
        svc = self.begin(permission_reader=lambda project_id, root: AUTO_MODE)
        sid = self.running(svc)
        self.assertEqual(self.sprint_state(svc, sid).permission, AUTO_MODE)
        svc.send_message("owner/p01", sid, TEXT)
        self.queued.run_next()
        self.assertEqual(self.nudges, [nudge.Nudge(
            sid, "relay", self.name(sid), "s-1", "work", "/srv/p01", sender_bypass=False)])

    def test_a_relay_to_a_manager_with_no_logged_mode_comes_from_a_prompting_sender(self):
        svc = self.begin(permission_reader=lambda project_id, root: BYPASS_MODE)
        sid = self.running(svc)
        with svc._ingest:
            svc._sprints[sid] = dataclasses.replace(svc._sprints[sid], permission=None)
        svc.send_message("owner/p01", sid, TEXT)
        self.queued.run_next()
        self.assertIs(self.nudges[-1].sender_bypass, False)

    def test_a_notice_relay_to_a_bypass_manager_comes_from_a_bypass_sender(self):
        svc = self.begin(permission_reader=lambda project_id, root: BYPASS_MODE)
        sid = self.running(svc)
        self.assertEqual(self.sprint_state(svc, sid).permission, BYPASS_MODE)
        svc.post_owner_notice("owner/p01", "routes are frozen until Friday")
        self.drain()
        (sent,) = self.nudges
        self.assertEqual(sent.route, "relay")
        self.assertIs(sent.sender_bypass, True)

    def test_a_relay_logs_no_mode(self):
        svc = self.begin()
        sid = self.running(svc)
        svc.send_message("owner/p01", sid, TEXT)
        self.queued.run_next()
        ((_, row),) = self.nudged()
        self.assertEqual(row["route"], "relay")
        self.assertNotIn("permission", row)

    def test_a_wake_whose_send_fails_logs_the_mode_it_wrote(self):
        svc, sid = self.stopped_with_full_listing(
            frozenset(), permission_reader=lambda project_id, root: permission.Permission(
                permission.AUTO, permission.NOT_ENFORCED))
        self.outcomes = ["boom"]
        svc.send_message("owner/p01", sid, TEXT)
        self.queued.run_next()
        ((_, row),) = self.nudged()
        self.assertFalse(row["ok"])
        self.assertEqual(row["permission"], {
            "mode": "auto",
            "reason": "production rules declared but not in the guard's policy"})

    def test_an_owners_message_wakes_a_session_absent_from_the_full_listing_with_its_name_and_settings(self):
        svc, sid = self.stopped_with_full_listing(frozenset())
        path = str(manager.settings_path(svc._sprint_secrets, sid))
        svc.send_message("owner/p01", sid, TEXT)
        self.queued.run_next()
        self.assertEqual(self.nudges, [nudge.Nudge(
            sid, "wake", self.name(sid), "s-1", "work", "/srv/p01", path)])
        self.assertEqual(
            nudge.nudge_command(self.nudges[0], "linux")[-6:],
            ["--bg", "--name", self.name(sid), "--settings", path, nudge.NUDGE_TEXT])
        ((_, row),) = self.nudged()
        self.assertEqual((row["route"], row["ok"], "listing_failed" in row), ("wake", True, False))
        self.assertEqual(self.full_calls, [("work", "/srv/p01")])

    def test_an_unreadable_full_listing_gives_the_bare_wake_and_records_why(self):
        svc, sid = self.stopped_with_full_listing(
            nudge.ListingUnreadable("the listing is not a JSON array"))
        svc.send_message("owner/p01", sid, TEXT)
        self.queued.run_next()
        self.assertEqual(self.nudges, [nudge.Nudge(
            sid, "wake", self.name(sid), "s-1", "work", "/srv/p01")])
        ((_, row),) = self.nudged()
        self.assertTrue(row["ok"])
        self.assertEqual(row["listing_failed"], "the listing is not a JSON array")

    def test_a_manager_that_starts_during_the_full_listing_read_is_relayed_to_not_woken(self):
        svc, sid = self.stopped_with_full_listing(frozenset())
        observed = sessions.Observation(
            "s-9", "/srv/p01", 3, "idle", None, self.name(sid), None)

        def slow(profile, cwd):
            self.full_calls.append((profile, cwd))
            self.listed["s-9"] = observed
            return frozenset()

        svc._full_listing = slow
        svc.send_message("owner/p01", sid, TEXT)
        self.queued.run_next()
        self.assertEqual(self.full_calls, [("work", "/srv/p01")])
        self.assertEqual(self.nudges, [nudge.Nudge(
            sid, "relay", self.name(sid), "s-9", "work", "/srv/p01")])
        ((_, row),) = self.nudged()
        self.assertEqual((row["route"], row["ok"], "listing_failed" in row), ("relay", True, False))

    def test_a_relay_never_reads_the_full_listing(self):
        calls = []
        svc = self.begin(full_listing=lambda profile, cwd: calls.append((profile, cwd)) or set())
        sid = self.running(svc)
        svc.send_message("owner/p01", sid, TEXT)
        self.queued.run_next()
        self.assertEqual([n.route for n in self.nudges], ["relay"])
        self.assertEqual(calls, [])

    def stopped_and_overdue(self):
        """A restarted service whose sprint's manager row is started, unlisted, briefless and overdue."""
        first = self.begin()
        sid = self.running(first)
        first.close()
        log = EventLog(self.store, clock=self.log_clock)
        log.append([("session.seen", "owner/p01", {
            "session_id": "s-1", "cwd": "/srv/p01", "repo": "/srv/p01", "state": sessions.ENDED,
            "name": self.name(sid)})])
        log.close()
        self.listed.clear()
        self.now[0] += 600
        return self.begin(), sid

    def test_a_retry_is_refused_while_a_wake_is_reserved(self):
        svc, sid = self.stopped_and_overdue()
        svc.send_message("owner/p01", sid, TEXT)
        self.assertEqual(len(self.queued.jobs), 1)
        with self.assertRaises(sprints.Refused) as refused:
            svc.retry_manager("owner/p01", sid)
        self.assertEqual(str(refused.exception), sprints.LAUNCHING)
        self.queued.run_next()
        self.assertEqual([n.route for n in self.nudges], ["wake"])
        self.assertEqual(self.queued.jobs, [])

    def test_a_message_is_not_nudged_while_a_retry_is_reserved(self):
        svc, sid = self.stopped_and_overdue()
        svc.retry_manager("owner/p01", sid)
        self.assertEqual(len(self.queued.jobs), 1)
        svc.send_message("owner/p01", sid, TEXT)
        self.assertEqual(len(self.queued.jobs), 1)
        self.queued.run_next()
        self.assertEqual(self.nudges, [])
        self.assertEqual(self.queued.jobs, [])

    def test_a_message_after_a_finished_retry_does_not_wake_the_replaced_manager(self):
        svc, sid = self.stopped_and_overdue()
        svc.retry_manager("owner/p01", sid)
        self.queued.run_next()
        self.assertEqual(self.sprint_state(svc, sid).manager.state, sprints.STARTED)
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            svc.send_message("owner/p01", sid, TEXT)
            self.queued.run_next()
            self.now[0] += 120
            svc.renudge()
            while self.queued.jobs:
                self.queued.run_next()
        self.assertEqual(self.nudges, [])
        self.assertTrue(all(row["route"] is None and not row["ok"]
                            for _, row in self.nudged()))

    def test_an_unknown_session_fails_the_nudge_without_calling_the_nudger(self):
        svc = self.begin()
        sid = svc.state_goal("owner/p01", GOAL_TEXT)
        self.queued.run_next()
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            message = svc.send_message("owner/p01", sid, TEXT)
            self.queued.run_next()
        self.assertEqual(self.nudges, [])
        ((_, row),) = self.nudged()
        self.assertEqual(row, {"sprint_id": sid, "through": message, "covers": [message],
                               "route": None, "ok": False, "reason": "the manager's session is not known"})
        self.assertIn(f"console: nudge_failed {sid} the manager's session is not known",
                      stderr.getvalue())

    def test_two_failed_nudges_in_a_row_mark_the_manager_not_reachable_and_keep_the_messages(self):
        svc = self.begin()
        sid = self.running(svc)
        self.outcomes[:] = ["relay refused", "relay refused"]
        svc.send_message("owner/p01", sid, TEXT)
        with contextlib.redirect_stderr(io.StringIO()):
            self.queued.run_next()
            self.now[0] += 61
            svc.renudge()
            self.queued.run_next()
        self.assertTrue(sprints.unreachable(self.sprint_state(svc, sid)))
        self.now[0] += 120
        svc.renudge()
        self.assertEqual(self.queued.jobs, [])
        self.assertEqual([m["text"] for m in svc.read_inbox(sid, self.secret(sid))], [TEXT])

    def test_a_first_failure_is_retried_once_after_a_minute_and_not_before(self):
        svc = self.begin()
        sid = self.running(svc)
        self.outcomes[:] = ["relay refused"]
        svc.send_message("owner/p01", sid, TEXT)
        with contextlib.redirect_stderr(io.StringIO()):
            self.queued.run_next()
        self.now[0] += 30
        svc.renudge()
        self.assertEqual(self.queued.jobs, [])
        self.now[0] += 31
        svc.renudge()
        self.assertEqual(len(self.queued.jobs), 1)

    def test_a_re_nudge_waits_a_minute_from_the_last_attempt(self):
        svc = self.begin()
        sid = self.running(svc)
        self.outcomes[:] = ["relay refused"]
        svc.send_message("owner/p01", sid, TEXT)
        self.now[0] += 100
        with contextlib.redirect_stderr(io.StringIO()):
            self.queued.run_next()
        self.now[0] += 30
        svc.renudge()
        self.assertEqual(self.queued.jobs, [])
        self.now[0] += 31
        svc.renudge()
        self.assertEqual(len(self.queued.jobs), 1)

    def test_a_stored_message_nobody_nudged_is_nudged_after_a_minute_not_before(self):
        first = self.begin()
        sid = self.running(first)
        first.close()
        log = EventLog(self.store, clock=self.log_clock)
        log.append([("sprint.messaged", "owner/p01", {
            "sprint_id": sid, "goal": GOAL_TEXT, "text": TEXT})])
        log.close()
        svc = self.begin()
        self.now[0] += 30
        svc.renudge()
        self.assertEqual(self.queued.jobs, [])
        self.now[0] += 31
        svc.renudge()
        self.assertEqual(len(self.queued.jobs), 1)

    def test_the_poll_loop_renudges(self):
        svc = self.begin(session_poll_seconds=0.05)
        sid = self.running(svc)
        self.outcomes[:] = ["relay refused"]
        svc.send_message("owner/p01", sid, TEXT)
        with contextlib.redirect_stderr(io.StringIO()):
            self.queued.run_next()
        self.now[0] += 61
        deadline = time.monotonic() + 10
        while not self.queued.jobs and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertEqual(len(self.queued.jobs), 1)

    def test_a_delivered_message_is_not_nudged_again_within_five_minutes(self):
        svc = self.begin()
        sid = self.running(svc)
        svc.send_message("owner/p01", sid, TEXT)
        self.queued.run_next()
        self.now[0] += 299
        svc.renudge()
        self.assertEqual(self.queued.jobs, [])

    def answered(self, **overrides):
        """An answered question relayed once to a listed manager whose session is known; `(svc, sid, answer, start)`."""
        from .test_console_questions import ROUND  # deferred: that module imports this one
        first = self.begin()
        sid = self.running(first)
        first.close()
        log = EventLog(self.store, clock=self.log_clock)
        log.append([("session.seen", "owner/p01", {
            "session_id": "s-1", "cwd": "/srv/p01", "repo": "/srv/p01", "state": "idle",
            "name": self.name(sid)})])
        log.close()
        svc = self.begin(**{
            "stopper": self.stop_session,
            "permission_reader": lambda project_id, root: permission.Permission(
                permission.AUTO, permission.NOT_DECLARED),
            **overrides})
        secret = self.secret(sid)
        svc.send_brief(sid, secret, PARTS)
        svc.approve_brief("owner/p01", sid, 1)
        self.queued.run_next()
        svc.read_inbox(sid, secret)
        round_id, _ = svc.ask_questions(sid, secret, ROUND)
        start = len(self.nudges)
        answer = svc.answer_question("owner/p01", sid, round_id, 0, 0, None)
        self.queued.run_next()
        return svc, sid, answer, start

    def relayed_twice(self, **overrides):
        svc, sid, answer, start = self.answered(**overrides)
        self.now[0] += 300
        svc.renudge()
        self.queued.run_next()
        return svc, sid, answer, start

    def routes(self, start):
        return [n.route for n in self.nudges[start:]]

    def test_an_unread_answer_is_relayed_once_more_five_minutes_after_its_relay(self):
        svc, sid, answer, start = self.answered()
        self.assertEqual(self.routes(start), ["relay"])
        self.now[0] += 299
        svc.renudge()
        self.assertEqual(self.queued.jobs, [])
        self.now[0] += 1
        svc.renudge()
        self.assertEqual(len(self.queued.jobs), 1)
        self.queued.run_next()
        self.assertEqual(self.routes(start), ["relay", "relay"])
        self.assertEqual(self.nudged()[-1][1], {
            "sprint_id": sid, "through": answer, "covers": [answer], "route": "relay", "ok": True})

    def test_an_answer_unread_after_the_second_relay_wakes_the_manager(self):
        svc, sid, answer, start = self.relayed_twice()
        self.now[0] += 299
        svc.renudge()
        self.assertEqual(self.queued.jobs, [])
        self.now[0] += 1
        svc.renudge()
        self.queued.run_next()
        self.assertEqual(self.stops, [("s-1", start + 2)])
        self.assertEqual(self.nudges[-1], nudge.Nudge(sid, "wake", self.name(sid), "s-1", "work", "/srv/p01"))
        self.assertEqual(self.routes(start), ["relay", "relay", "wake"])
        self.assertEqual(self.nudged()[-1][1], {
            "sprint_id": sid, "through": answer, "covers": [answer], "route": "wake", "ok": True,
            "permission": {"mode": "auto", "reason": "no production rules declared"}})
        self.now[0] += 1200
        svc.renudge()
        self.assertEqual(self.queued.jobs, [])

    def test_an_answer_the_manager_read_sends_nothing_further(self):
        svc, sid, answer, start = self.relayed_twice()
        svc.read_inbox(sid, self.secret(sid))
        self.now[0] += 1200
        svc.renudge()
        self.assertEqual(self.queued.jobs, [])
        self.assertEqual(self.routes(start), ["relay", "relay"])
        self.assertEqual(self.stops, [])

    def test_a_message_read_before_the_wake_runs_is_not_woken(self):
        svc, sid, answer, start = self.relayed_twice()
        self.now[0] += 300
        svc.renudge()
        self.assertEqual(len(self.queued.jobs), 1)
        svc.read_inbox(sid, self.secret(sid))
        rows = len(self.nudged())
        self.queued.run_next()
        self.assertEqual(self.stops, [])
        self.assertEqual(self.routes(start), ["relay", "relay"])
        self.assertEqual(len(self.nudged()), rows)
        self.assertEqual(svc._nudging, set())

    def test_the_wake_waits_while_the_manager_works_or_waits_at_a_prompt(self):
        for status, waiting_for in (("busy", None), ("waiting", "permission prompt"),
                                    ("waiting", "question")):
            with self.subTest(status=status, waiting_for=waiting_for), \
                    contextlib.redirect_stderr(io.StringIO()):
                self.setUp()
                svc, sid, answer, start = self.relayed_twice()
                self.listed["s-1"] = sessions.Observation(
                    "s-1", "/srv/p01", 1, status, waiting_for, self.name(sid), None)
                rows = len(self.nudged())
                self.now[0] += 300
                svc.renudge()
                self.queued.run_next()
                self.assertEqual(self.stops, [])
                self.assertEqual(self.routes(start), ["relay", "relay"])
                self.assertEqual(len(self.nudged()), rows)
                self.assertEqual(svc._nudging, set())
                self.listed["s-1"] = sessions.Observation(
                    "s-1", "/srv/p01", 1, "idle", None, self.name(sid), None)
                svc.renudge()
                self.queued.run_next()
                self.assertEqual(self.routes(start)[-1], "wake")
                svc.close()

    def test_the_wake_waits_while_the_hooks_show_the_manager_at_a_prompt(self):
        svc, sid, answer, start = self.relayed_twice()
        with svc._ingest:
            svc._sessions["s-1"] = dataclasses.replace(
                svc._sessions["s-1"], state=sessions.WAITING_PERMISSION)
        rows = len(self.nudged())
        self.now[0] += 300
        svc.renudge()
        self.queued.run_next()
        self.assertEqual(self.stops, [])
        self.assertEqual(self.routes(start), ["relay", "relay"])
        self.assertEqual(len(self.nudged()), rows)
        self.assertEqual(svc._nudging, set())

    def test_a_manager_whose_session_does_not_stop_is_not_woken(self):
        stays = lambda session_id, profile: self.stops.append((session_id, len(self.nudges)))
        for name, options in (("stays listed", {"stopper": stays}), ("no stopper", {"stopper": None})):
            stderr = io.StringIO()
            with self.subTest(name), contextlib.redirect_stderr(stderr):
                self.setUp()
                svc, sid, answer, start = self.relayed_twice(**options)
                self.now[0] += 300
                svc.renudge()
                self.queued.run_next()
                self.assertEqual(self.routes(start), ["relay", "relay"])
                self.assertEqual(self.nudged()[-1][1], {
                    "sprint_id": sid, "through": answer, "covers": [answer], "route": "wake",
                    "ok": False, "reason": sprints.STILL_RUNNING_TEXT})
                self.assertIn(f"console: nudge_failed {sid} {sprints.STILL_RUNNING_TEXT}",
                              stderr.getvalue())
                self.now[0] += 299
                svc.renudge()
                self.assertEqual(self.queued.jobs, [])
                svc.close()

    def test_a_stop_that_fails_is_a_failed_wake(self):
        def refuses(session_id, profile):
            raise manager.StopFailed("the stop exited 1")
        svc, sid, answer, start = self.relayed_twice(stopper=refuses)
        self.now[0] += 300
        with contextlib.redirect_stderr(io.StringIO()):
            svc.renudge()
            self.queued.run_next()
        payload = self.nudged()[-1][1]
        self.assertEqual((payload["route"], payload["ok"], payload["reason"]),
                         ("wake", False, "the stop exited 1"))
        self.assertEqual(self.routes(start), ["relay", "relay"])

    def test_a_manager_gone_before_the_wake_is_woken_without_a_stop(self):
        svc, sid, answer, start = self.relayed_twice()
        self.listed.clear()
        self.now[0] += 300
        svc.renudge()
        self.queued.run_next()
        self.assertEqual(self.stops, [])
        self.assertEqual((self.nudges[-1].route, self.nudges[-1].session_id), ("wake", "s-1"))

    def test_a_wake_that_cannot_be_dispatched_is_a_failed_wake(self):
        svc, sid, answer, start = self.relayed_twice()

        def no_thread(job):
            raise RuntimeError("no thread")
        svc._dispatch = no_thread
        self.now[0] += 300
        with contextlib.redirect_stderr(io.StringIO()):
            svc.renudge()
        self.assertEqual(self.nudged()[-1][1], {
            "sprint_id": sid, "through": answer, "covers": [answer], "route": "wake", "ok": False,
            "reason": "the wake could not start: RuntimeError: no thread"})
        self.assertEqual(svc._nudging, set())

    def test_no_nudge_without_a_started_manager_or_a_nudger(self):
        for name, options in (
                ("no launcher", {"launcher": None}),
                ("a failed launch", {"launcher": support.Launches(fail=["no claude"])}),
                ("no nudger", {"nudger": None})):
            with self.subTest(name), contextlib.redirect_stderr(io.StringIO()):
                self.setUp()
                svc = self.begin(**options)
                sid = svc.state_goal("owner/p01", GOAL_TEXT)
                if self.queued.jobs:
                    self.queued.run_next()
                svc.send_message("owner/p01", sid, TEXT)
                self.now[0] += 600
                svc.renudge()
                self.assertEqual(self.queued.jobs, [])
                self.assertEqual(self.nudged(), [])
                self.assertEqual(self.nudges, [])
                svc.close()

    def test_a_message_sent_while_a_nudge_runs_is_nudged_once_more_after_it(self):
        svc = self.begin()
        sid = self.running(svc)
        second = []

        def nudger(sent):
            self.nudger(sent)
            if len(self.nudges) == 1:
                second.append(svc.send_message("owner/p01", sid, "and keep the tests"))

        svc._nudger = nudger
        first = svc.send_message("owner/p01", sid, TEXT)
        self.queued.run_next()
        self.assertEqual(len(self.queued.jobs), 1)
        self.queued.run_next()
        self.assertEqual(len(self.nudges), 2)
        self.assertEqual([row["through"] for _, row in self.nudged()], [first, second[0]])
        self.assertEqual(self.queued.jobs, [])

    def test_approving_and_asking_for_changes_nudge_too(self):
        svc = self.begin()
        sid = self.running(svc)
        version = self.send(svc, sid)
        self.assertEqual(self.reply(svc, sid, version, "smaller slices")[0], 204)
        self.queued.run_next()
        version = self.send(svc, sid)
        self.assertEqual(self.approve(svc, sid, version)[0], 204)
        self.queued.run_next()
        rows = support.log_rows(self.store)
        kinds = [row[2] for row in rows]
        replied, approved = rows[kinds.index("brief.replied")], rows[kinds.index("brief.approved")]
        self.assertEqual([row["through"] for _, row in self.nudged()], [replied[0], approved[0]])

    def test_a_stored_message_whose_nudge_cannot_be_dispatched_is_sent_once_and_retried(self):
        calls = []

        def dispatch(job):
            calls.append(job)
            if len(calls) == 1:
                job()
            elif len(calls) == 2:
                raise RuntimeError("no thread")
            else:
                self.queued(job)

        svc = self.begin(dispatch=dispatch)
        sid = self.running_after(svc)
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            status = self.message(svc, sid, TEXT)[0]
        self.assertEqual(status, 204)
        rows = support.log_rows(self.store)
        self.assertEqual(self.kinds().count("sprint.messaged"), 1)
        message = self.sprint_state(svc, sid).messages[-1]
        reason = "the nudge could not start: RuntimeError: no thread"
        self.assertEqual((rows[-1][2], json.loads(rows[-1][4])), (
            "sprint.nudged", {"sprint_id": sid, "through": message.message_id,
                              "covers": [message.message_id], "route": None,
                              "ok": False, "reason": reason}))
        self.assertIn(f"console: nudge_failed {sid} {reason}", stderr.getvalue())
        self.assertNotIn(TEXT, stderr.getvalue())
        folded = self.sprint_state(svc, sid)
        self.assertEqual(folded.failed_nudges, 1)
        self.assertIsNone(folded.messages[-1].delivered_at)
        self.now[0] += 61
        svc.renudge()
        self.assertEqual(len(self.queued.jobs), 1)
        self.queued.run_next()
        self.assertEqual(len(self.nudges), 1)
        self.assertEqual(self.nudged()[-1][1]["ok"], True)

    def running_after(self, svc):
        sid = svc.state_goal("owner/p01", GOAL_TEXT)
        self.listed["s-1"] = sessions.Observation(
            "s-1", "/srv/p01", 1, "idle", None, self.name(sid), None)
        return sid

    def test_a_nudge_never_holds_the_ingest_lock(self):
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
        sid = self.running(svc)
        svc.send_message("owner/p01", sid, TEXT)
        self.queued.run_next()
        self.assertEqual(held, [True, True])



AT = int(datetime.fromisoformat(message_at(3)).timestamp() * 1000)
FIVE_MIN = 300_000
MINUTE_TEXT = "the manager picks it up within a minute"
TURN_TEXT = "the manager picks it up at its next turn"


def approval(*more):
    return message_rows(
        message_row(3, event_log.BRIEF_SENT, {"version": 1, "goal": "g", "brief": PARTS}),
        message_row(4, event_log.BRIEF_APPROVED, {"version": 1, "goal": "g"}), *more)


def life(rows, now_ms, nudges=True):
    return derive_view([state("p00", 1)], sprints=sprint_states(rows), now_ms=now_ms,
                       nudges=nudges)["entries"][0]["sprints"][0]


class MessageLifeViewTest(unittest.TestCase):
    """A message reads sent, picked up, replied or not picked up (#1086)."""

    def test_a_message_reads_sent_with_its_pickup_then_picked_up_then_replied(self):
        rows = message_rows(messaged_row(3, TEXT))
        (sent,) = life(rows, AT + 60_000)["messages"]
        self.assertEqual((sent["state"], sent["state_text"], sent["action_text"]),
                         ("sent", "sent, " + MINUTE_TEXT, None))
        rows.append(message_row(4, event_log.SPRINT_READ, {"through": 3}))
        (read,) = life(rows, AT + 60_000)["messages"]
        self.assertEqual((read["state"], read["state_text"]), ("picked_up", "picked up"))
        rows.append(message_row(5, event_log.SPRINT_ANSWERED, {"message": 3, "reply": ANSWER}))
        (replied,) = life(rows, AT + 60_000)["messages"]
        self.assertEqual((replied["state"], replied["state_text"], replied["reply"]),
                         ("replied", "replied", ANSWER))

    def test_without_a_nudger_or_a_started_manager_the_pickup_is_the_next_turn(self):
        rows = message_rows(messaged_row(3, TEXT))
        turn = life(rows, AT + 60_000, nudges=False)
        self.assertEqual(turn["messages"][0]["state_text"], "sent, " + TURN_TEXT)
        self.assertEqual(turn["tell_text"], "The manager picks it up at its next turn.")
        bare = [message_row(1, event_log.GOAL_STATED, {"goal": "make the importer resumable"}),
                messaged_row(3, TEXT)]
        turn = life(bare, AT + 60_000)
        self.assertEqual(turn["messages"][0]["state_text"], "sent, " + TURN_TEXT)
        self.assertEqual(turn["tell_text"], "The manager picks it up at its next turn.")
        self.assertEqual(life(rows, AT + 60_000)["tell_text"],
                         "The manager picks it up within a minute.")

    def test_an_unread_message_reads_not_picked_up_at_five_minutes_with_an_action(self):
        # A briefed sprint: a started manager with no brief this old would be missing, and offer Retry.
        parts = {"done": "d", "excluded": ["x"], "slices": ["a"], "risks": ["r"], "asks": ["q"]}
        brief = message_row(2, event_log.BRIEF_SENT, {"version": 1, "goal": "g", "brief": parts})
        rows = message_rows(brief, messaged_row(3, TEXT))
        self.assertEqual(life(rows, AT + FIVE_MIN - 1)["messages"][0]["state"], "sent")
        late = life(rows, AT + FIVE_MIN)["messages"][0]
        self.assertEqual((late["state"], late["state_text"], late["action_text"]),
                         ("not_picked_up", "not picked up after 5 min",
                          "Tell the manager again, or drop the sprint."))
        turn = life(rows, AT + FIVE_MIN, nudges=False)["messages"][0]
        self.assertEqual(
            turn["action_text"],
            "It waits for the manager's next turn; drop the sprint if none comes.")
        for text in (NUDGE_ACTION_TEXT, TURN_ACTION_TEXT, RETRY_ACTION_TEXT):
            self.assertNotIn("More", text)
        for text in (NUDGE_ACTION_TEXT, TURN_ACTION_TEXT):
            self.assertNotIn("nudge", text)
            self.assertNotIn("withdraw", text)
        failed = [message_row(1, event_log.GOAL_STATED, {"goal": "make the importer resumable"}),
                  message_row(2, event_log.MANAGER_FAILED, {"reason": "boom"}),
                  messaged_row(3, TEXT)]
        retry = life(failed, AT + FIVE_MIN)
        self.assertTrue(retry["retry"])
        self.assertEqual(retry["messages"][0]["action_text"],
                         "Press Retry to start a new manager.")
        read = message_rows(messaged_row(3, TEXT),
                            message_row(4, event_log.SPRINT_READ, {"through": 3}))
        picked = life(read, AT + 2 * FIVE_MIN)["messages"][0]
        self.assertEqual((picked["state"], picked["action_text"]), ("picked_up", None))

    def test_a_picked_up_approval_is_not_shown_as_a_message(self):
        def shown(*more):
            return [(m["kind"], m["state"])
                    for m in life(approval(*more), AT + 60_000)["messages"]]
        self.assertEqual(shown(), [("approved", "sent")])
        read = message_row(5, event_log.SPRINT_READ, {"through": 4})
        self.assertEqual(shown(read), [])
        self.assertEqual(shown(messaged_row(6, TEXT),
                               message_row(7, event_log.SPRINT_READ, {"through": 6})),
                         [("text", "picked_up")])

    def test_the_approval_member_keeps_a_read_approval_that_messages_leaves_out(self):
        self.assertIsNone(life(message_rows(messaged_row(3, TEXT)), AT + 60_000)["approval"])
        self.assertEqual(life(approval(), AT + 60_000)["approval"]["state"], "sent")
        read = message_row(5, event_log.SPRINT_READ, {"through": 4})
        row = life(approval(read), AT + 60_000)
        self.assertEqual(row["messages"], [])
        self.assertEqual((row["approval"]["kind"], row["approval"]["state"],
                          row["approval"]["at"], row["approval"]["read_at"]),
                         ("approved", "picked_up", message_at(4), message_at(5)))
        later = [messaged_row(6, TEXT)] + [
            messaged_row(seq, TEXT) for seq in range(7, 20)]
        newest = life(approval(read, *later), AT + 60_000)
        self.assertEqual(newest["approval"]["id"], row["approval"]["id"])

    def test_a_picked_up_change_request_still_shows(self):
        rows = message_rows(
            message_row(3, event_log.BRIEF_SENT, {"version": 1, "goal": "g", "brief": PARTS}),
            message_row(4, event_log.BRIEF_REPLIED,
                        {"version": 1, "goal": "g", "reply": "smaller slices"}),
            message_row(5, event_log.SPRINT_READ, {"through": 4}))
        self.assertEqual([(m["kind"], m["state"]) for m in life(rows, AT + 60_000)["messages"]],
                         [("changes", "picked_up")])

    def test_a_replied_approval_keeps_its_reply(self):
        rows = approval(message_row(5, event_log.SPRINT_READ, {"through": 4}),
                        message_row(6, event_log.SPRINT_ANSWERED,
                                    {"message": 4, "reply": ANSWER}))
        self.assertEqual([(m["kind"], m["state"], m["reply"])
                          for m in life(rows, AT + 60_000)["messages"]],
                         [("approved", "replied", ANSWER)])

    def test_a_nudged_but_unread_message_never_reads_delivered(self):
        nudged = message_rows(messaged_row(3, TEXT), nudged_row(4, 3, True))
        self.assertEqual(life(nudged, AT + 60_000)["messages"][0]["state"], "sent")
        row_sets = [
            (message_rows(messaged_row(3, TEXT)), AT + 60_000),
            (message_rows(messaged_row(3, TEXT),
                          message_row(4, event_log.SPRINT_READ, {"through": 3})), AT + 60_000),
            (message_rows(messaged_row(3, TEXT),
                          message_row(4, event_log.SPRINT_READ, {"through": 3}),
                          message_row(5, event_log.SPRINT_ANSWERED,
                                      {"message": 3, "reply": ANSWER})), AT + 60_000),
            (message_rows(messaged_row(3, TEXT)), AT + FIVE_MIN),
            (nudged, AT + 60_000), (nudged, AT + FIVE_MIN)]
        for rows, now_ms in row_sets:
            for nudges in (True, False):
                for message in life(rows, now_ms, nudges)["messages"]:
                    self.assertNotIn(message["state"], ("delivered", "read"))
                    self.assertNotIn(message["state_text"], ("delivered", "read"))

    def test_an_ended_sprint_offers_no_tell_text(self):
        folded = sprint_states(message_rows(messaged_row(3, TEXT)))
        (sprint,) = folded.values()
        folded = {sprint.sprint_id: dataclasses.replace(sprint, stopped_at=message_at(6))}
        entry = derive_view([state("p00", 1)], sprints=folded,
                            now_ms=AT + 60_000)["entries"][0]["sprints"][0]
        self.assertIsNotNone(entry["ended_at"])
        self.assertIsNone(entry["tell_text"])

    def test_an_ended_sprint_points_at_no_control_and_promises_no_pickup(self):
        parts = {"done": "d", "excluded": ["x"], "slices": ["a"], "risks": ["r"], "asks": ["q"]}
        brief = message_row(2, event_log.BRIEF_SENT, {"version": 1, "goal": "g", "brief": parts})
        rows = message_rows(brief, messaged_row(3, TEXT))
        (sprint,) = sprint_states(rows).values()
        folded = {sprint.sprint_id: dataclasses.replace(sprint, stopped_at=message_at(6))}

        def ended(now_ms):
            return derive_view([state("p00", 1)], sprints=folded,
                               now_ms=now_ms)["entries"][0]["sprints"][0]
        (sent,) = ended(AT + 60_000)["messages"]
        self.assertEqual((sent["state"], sent["state_text"], sent["action_text"]),
                         ("sent", "sent", None))
        entry = ended(AT + FIVE_MIN)
        self.assertIsNotNone(entry["ended_at"])
        (late,) = entry["messages"]
        self.assertEqual((late["state"], late["state_text"], late["action_text"]),
                         ("not_picked_up", "not picked up after 5 min", None))


class MessageWindowViewTest(unittest.TestCase):
    """A reply to a message older than the shown ten is never cut from the view (#1086)."""

    def rows(self):
        sent = [messaged_row(seq, "note %d" % seq) for seq in range(3, 15)]
        return message_rows(*sent, message_row(15, event_log.SPRINT_ANSWERED,
                                               {"message": 3, "reply": ANSWER}))

    def view(self, looked):
        return derive_view([state("p00", 1)], sprints=sprint_states(self.rows()),
                           now_ms=AT + 20 * 60_000, looked=looked)

    def test_a_new_reply_to_the_oldest_of_twelve_messages_stays_shown_and_announced(self):
        view = self.view(message_at(14))
        shown = view["entries"][0]["sprints"][0]["messages"]
        self.assertEqual([m["id"] for m in shown], [3, *range(5, 15)])
        self.assertEqual([m["id"] for m in shown if m["new"]], [3])
        self.assertEqual([r["message_id"] for r in view["new_replies"]], [3])
        self.assertEqual(view["new_replies_text"],
                         "New reply from the manager of make the importer resumable")

    def test_an_old_reply_already_looked_at_is_cut_with_the_other_old_messages(self):
        view = self.view(message_at(15))
        shown = view["entries"][0]["sprints"][0]["messages"]
        self.assertEqual([m["id"] for m in shown], list(range(5, 15)))
        self.assertEqual(view["new_replies"], [])


    def test_a_picked_up_approval_takes_no_window_slot(self):
        brief = {"version": 1, "goal": "g", "brief": PARTS}
        rows = message_rows(
            messaged_row(3, "note 3"), message_row(4, event_log.BRIEF_SENT, brief),
            message_row(5, event_log.BRIEF_APPROVED, {"version": 1, "goal": "g"}),
            message_row(6, event_log.SPRINT_READ, {"through": 5}),
            *[messaged_row(seq, "note %d" % seq) for seq in range(7, 16)])
        view = derive_view([state("p00", 1)], sprints=sprint_states(rows),
                           now_ms=AT + 20 * 60_000, looked=None)
        shown = view["entries"][0]["sprints"][0]["messages"]
        self.assertEqual([m["id"] for m in shown], [3, *range(7, 16)])


class MessagePickupServiceTest(MessageRouteTest):
    def test_the_service_words_the_pickup_by_whether_it_has_a_nudger(self):
        svc = self.open()
        sid = self.settled(svc)
        (sprint,) = view_of(svc)["entries"][0]["sprints"]
        self.assertEqual(sprint["tell_text"], "The manager picks it up at its next turn.")
        svc.close()
        log = EventLog(self.store)
        log.append([("manager.started", "owner/p01", {
            "sprint_id": sid, "profile": "work", "session_name": "m"})])
        log.close()
        svc = self.start()
        (sprint,) = view_of(svc)["entries"][0]["sprints"]
        self.assertEqual(sprint["tell_text"], "The manager picks it up at its next turn.")
        svc.close()
        svc = self.start(nudger=lambda n: None)
        (sprint,) = view_of(svc)["entries"][0]["sprints"]
        self.assertEqual(sprint["tell_text"], "The manager picks it up within a minute.")


def view_with(folded, looked, now_ms):
    return derive_view([state("p00", 1)], sprints=folded, now_ms=now_ms, looked=looked)


def replied_rows():
    return message_rows(messaged_row(3, TEXT),
                        message_row(4, event_log.SPRINT_ANSWERED,
                                    {"message": 3, "reply": ANSWER}))


class NewReplyViewTest(unittest.TestCase):
    """A reply after the owner's last look is new, announced apart from the count (#1086)."""

    NOW = AT + 7 * 60_000

    def view(self, rows, looked):
        return view_with(sprint_states(rows), looked, self.NOW)

    def messages(self, view):
        return view["entries"][0]["sprints"][0]["messages"]

    def test_a_reply_after_the_last_look_is_new_and_announced_outside_the_count(self):
        view = self.view(replied_rows(), message_at(3))
        (message,) = self.messages(view)
        self.assertIs(message["new"], True)
        self.assertEqual(view["new_replies"], [{
            "project_id": "p00", "sprint_id": MESSAGE_SID, "title": "make the importer resumable",
            "message_id": 3, "reply_at": message_at(4)}])
        self.assertEqual(view["new_replies_text"],
                         "New reply from the manager of make the importer resumable")
        self.assertEqual(view["statement"]["inbox_items"], 0)
        self.assertEqual(view["statement"]["headline"], "Nothing needs you")

    def test_a_reply_to_an_approval_is_new_until_a_later_look(self):
        rows = approval(message_row(5, event_log.SPRINT_READ, {"through": 4}),
                        message_row(6, event_log.SPRINT_ANSWERED,
                                    {"message": 4, "reply": ANSWER}))
        view = self.view(rows, message_at(5))
        (message,) = self.messages(view)
        self.assertEqual((message["kind"], message["state"]), ("approved", "replied"))
        self.assertIs(message["new"], True)
        self.assertEqual([r["message_id"] for r in view["new_replies"]], [4])
        self.assertIsInstance(view["new_replies_text"], str)
        view = self.view(rows, message_at(7))
        (message,) = self.messages(view)
        self.assertEqual((message["kind"], message["state"]), ("approved", "replied"))
        self.assertIs(message["new"], False)
        self.assertEqual(view["new_replies"], [])

    def test_a_reply_at_or_before_the_last_look_is_not_new(self):
        for looked in (message_at(4), message_at(5)):
            with self.subTest(looked=looked):
                view = self.view(replied_rows(), looked)
                self.assertIs(self.messages(view)[0]["new"], False)
                self.assertEqual(view["new_replies"], [])
                self.assertIsNone(view["new_replies_text"])

    def test_with_no_look_stored_a_reply_is_new(self):
        self.assertIs(self.messages(self.view(replied_rows(), None))[0]["new"], True)

    def test_replies_on_two_sprints_read_as_a_count(self):
        other = "b" * 16

        def row(seq, kind, payload):
            return dataclasses.replace(
                message_row(seq, kind, payload),
                payload={"sprint_id": other, **payload})
        rows = replied_rows() + [
            row(5, event_log.GOAL_STATED, {"goal": "tidy the exporter"}),
            row(6, event_log.MANAGER_STARTED, {"profile": "work", "session_name": "n"}),
            row(7, event_log.SPRINT_MESSAGED, {"goal": "g", "text": TEXT}),
            row(8, event_log.SPRINT_ANSWERED, {"message": 7, "reply": ANSWER})]
        view = self.view(rows, message_at(3))
        self.assertEqual(view["new_replies_text"], "2 new replies from managers")
        self.assertEqual([r["reply_at"] for r in view["new_replies"]],
                         [message_at(4), message_at(8)])
        self.assertEqual([r["sprint_id"] for r in view["new_replies"]], [MESSAGE_SID, other])

    def test_a_message_without_a_reply_is_never_new(self):
        view = self.view(message_rows(messaged_row(3, TEXT)), None)
        self.assertIs(self.messages(view)[0]["new"], False)
        self.assertEqual(view["new_replies"], [])

    def test_a_reply_then_finish_is_announced_and_kept_on_the_ended_sprint(self):
        (sprint,) = sprint_states(replied_rows()).values()
        folded = {sprint.sprint_id: dataclasses.replace(sprint, stopped_at=message_at(6))}
        project = lambda view: view["entries"][0]
        for now_ms, where in ((AT + 7 * 60_000, lambda p: p["sprints"]),
                              (AT + 7 * 60_000 + 2 * 86_400_000,
                               lambda p: p["finished_sprints"]["sprints"])):
            with self.subTest(now_ms=now_ms):
                view = view_with(folded, message_at(3), now_ms)
                (entry,) = where(project(view))
                self.assertIsNotNone(entry["ended_at"])
                self.assertIs(entry["messages"][0]["new"], True)
                self.assertEqual([r["message_id"] for r in view["new_replies"]], [3])
                self.assertEqual(view["new_replies_text"],
                                 "New reply from the manager of make the importer resumable")
                looked = view_with(folded, message_at(7), now_ms)
                (entry,) = where(project(looked))
                self.assertIs(entry["messages"][0]["new"], False)
                self.assertEqual(looked["new_replies"], [])
                self.assertIsNone(looked["new_replies_text"])


class NewReplyServiceTest(MessageRouteTest):
    def test_a_look_after_the_reply_clears_new(self):
        svc = self.open()
        sid = self.settled(svc)
        self.inbox(svc, sid, self.secret(sid))
        (text,) = [m for m in self.sprint_state(svc, sid).messages if m.kind == "text"]
        self.assertEqual(self.answer(svc, sid, self.secret(sid), text.message_id, ANSWER)[0], 200)

        def shown():
            view = view_of(svc)
            (message,) = [m for m in view["entries"][0]["sprints"][0]["messages"]
                          if m["id"] == text.message_id]
            return view, message
        view, message = shown()
        self.assertIs(message["new"], True)
        self.assertIsInstance(view["new_replies_text"], str)
        self.assertEqual(support.post_page(svc.address, "/api/looked", self.own(svc))[0], 204)
        view, message = shown()
        self.assertIs(message["new"], False)
        self.assertEqual(view["new_replies"], [])
        self.assertIsNone(view["new_replies_text"])
