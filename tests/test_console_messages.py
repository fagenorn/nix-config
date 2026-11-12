"""The owner's messages to a sprint and the manager's inbox and reply routes (#889).

Run: just agent-workflow-tests
"""
import contextlib
import io
import json
import time
from datetime import datetime, timezone

from agent_tools.console import manager, nudge, sessions, sprints, write_guard
from agent_tools.console.event_log import EventLog

from . import console_test_support as support
from .test_console_answer import view_of
from .test_console_writes import Case

BRIEF = "/api/brief"
APPROVE = "/api/approve"
REPLY = "/api/reply"
MESSAGE = "/api/message"
INBOX = "/api/inbox"
MESSAGE_REPLY = "/api/message-reply"
GOAL_TEXT = "make the importer resumable"
PARTS = {"done": "the importer resumes after a crash", "excluded": ["no new formats"],
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


class NudgeServiceTest(MessageRouteTest):
    """The service nudges a running manager, wakes a stopped one and counts failures (#889)."""

    def setUp(self):
        super().setUp()
        support.write_registry(self.registry, support.entries(2))
        self.queued = support.Queued()
        self.nudges = []
        self.outcomes = []
        self.listed = {}
        self.now = [T0]

    def log_clock(self):
        return datetime.fromtimestamp(self.now[0], timezone.utc).isoformat(timespec="microseconds")

    def nudger(self, sent):
        self.nudges.append(sent)
        outcome = self.outcomes.pop(0) if self.outcomes else None
        if outcome is not None:
            raise nudge.NudgeFailed(outcome)

    def begin(self, **overrides):
        options = dict(
            launcher=support.Launches(), bound_profile_of=lambda root: "work",
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
            {"sprint_id": sid, "through": message.message_id, "route": "relay", "ok": True}))
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

    def stopped_with_full_listing(self, outcome):
        """A restarted service whose manager is unlisted; `outcome` is what its full listing gives."""
        first = self.begin()
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

        svc = self.begin(full_listing=full)
        return svc, sid

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
        self.assertEqual(row, {"sprint_id": sid, "through": message, "route": None, "ok": False,
                               "reason": "the manager's session is not known"})
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

    def test_a_delivered_message_is_not_nudged_again(self):
        svc = self.begin()
        sid = self.running(svc)
        svc.send_message("owner/p01", sid, TEXT)
        self.queued.run_next()
        self.now[0] += 600
        svc.renudge()
        self.assertEqual(self.queued.jobs, [])

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
            "sprint.nudged", {"sprint_id": sid, "through": message.message_id, "route": None,
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

