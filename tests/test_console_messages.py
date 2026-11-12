"""The owner's messages to a sprint and the manager's inbox and reply routes (#889).

Run: just agent-workflow-tests
"""
import contextlib
import io
import json

from agent_tools.console import write_guard

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
