"""An owner-only card's approved command runs once, within an hour, over a signed request (issue 1687)."""
import http.client
import json
from datetime import datetime, timezone

from agent_tools.console import permit, service, sprints

from .test_console_manager_service import PermitCase
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)

ACTION_COMMAND = "curl -sS -X POST http://127.0.0.1:27999/api/plan-approve --data @/tmp/approve.json"
T0 = 1_795_000_000.0


class ActionCase(PermitCase):
    def ask_action(self, svc, sid, command=ACTION_COMMAND):
        round_id, _ = svc.ask_questions(sid, self.secret(sid), {"questions": [{
            "question": "May the manager run this one Apply on the throwaway console?",
            "blocks": "the registration check", "options": ["Run it once", "Do not run it"],
            "recommended": "Run it once", "owner_only": True,
            "action": {"command": command, "approve": "Run it once"}}]})
        return round_id

    def judge_action(self, svc, sid, command, session="s-1", call="t-1"):
        return svc.permit_action(sid, self.secret(sid), session, call, permit.command_digest(command))

    def clocked(self):
        self.now = T0
        return {"clock": lambda: self.now,
                "log_clock": lambda: datetime.fromtimestamp(self.now, timezone.utc).isoformat(
                    timespec="microseconds")}

    def start(self, **kwargs):
        self.started = kwargs
        return super().start(**kwargs)

    def restart(self, **kwargs):
        self.svc.close()
        self.svc = self.start(**{**self.started, **kwargs})
        return self.svc


class ApprovedActionTest(ActionCase):
    """An owner-only card's approved command runs once, within an hour, over a signed request."""

    def outcome(self, verdict):
        return verdict.decision, verdict.reason, verdict.verb

    def test_an_owner_approved_action_runs_once_and_never_again(self):
        svc, sid = self.boot(**self.clocked())
        r = self.ask_action(svc, sid)
        svc.answer_question("owner/p01", sid, r, 0, 0, None)
        first = self.judge_action(svc, sid, ACTION_COMMAND, call="t-1")
        second = self.judge_action(svc, sid, ACTION_COMMAND, call="t-2")
        self.assertEqual((first.decision, first.verb, dict(first.target)),
                         ("allow", "action", {"round": r, "index": 0}))
        self.assertEqual((second.decision, second.verb, second.reason),
                         ("deny", "action", permit.ACTION_USED))
        judged = self.rows("permit.judged")
        self.assertEqual(len(judged), 2)
        self.assertEqual(judged[0], {
            "sprint_id": sid, "session_id": "s-1", "tool_use_id": "t-1", "repo": None,
            "verb": "action", "decision": "allow", "reason": "", "target": {"round": r, "index": 0}})

    def test_a_used_approval_stays_used_after_the_console_restarts(self):
        svc, sid = self.boot(**self.clocked())
        r = self.ask_action(svc, sid)
        svc.answer_question("owner/p01", sid, r, 0, 0, None)
        self.assertEqual(self.judge_action(svc, sid, ACTION_COMMAND).decision, "allow")
        svc = self.restart(**self.clocked())
        again = self.judge_action(svc, sid, ACTION_COMMAND, call="t-2")
        self.assertEqual((again.decision, again.reason), ("deny", permit.ACTION_USED))

    def test_a_command_no_card_names_gets_no_decision(self):
        svc, sid = self.boot(**self.clocked())
        self.assertEqual(self.outcome(self.judge_action(svc, sid, ACTION_COMMAND)), (None, "", None))
        self.assertEqual(self.rows("permit.judged"), [])
        r = self.ask_action(svc, sid)
        svc.answer_question("owner/p01", sid, r, 0, 0, None)
        for command in (ACTION_COMMAND + " --verbose", "curl -sS http://127.0.0.1:27999/",
                        " " + ACTION_COMMAND):
            with self.subTest(command=command):
                self.assertEqual(self.outcome(self.judge_action(svc, sid, command)), (None, "", None))
        self.assertEqual(self.outcome(self.judge(svc, sid, ACTION_COMMAND)), (None, "", None))
        self.assertEqual(self.rows("permit.judged"), [])
        self.assertEqual(self.judge_action(svc, sid, ACTION_COMMAND).decision, "allow")

    def test_an_approval_expires_sixty_minutes_after_the_answer(self):
        svc, sid = self.boot(**self.clocked())
        svc.answer_question("owner/p01", sid, self.ask_action(svc, sid), 0, 0, None)
        self.now = T0 + 3599
        self.assertEqual(self.judge_action(svc, sid, ACTION_COMMAND).decision, "allow")
        svc, sid = self.boot(**self.clocked())
        svc.answer_question("owner/p01", sid, self.ask_action(svc, sid), 0, 0, None)
        self.now = T0 + 3600
        verdict = self.judge_action(svc, sid, ACTION_COMMAND)
        self.assertEqual((verdict.decision, verdict.reason), ("deny", permit.ACTION_EXPIRED))

    def test_an_unanswered_or_declined_card_refuses_its_command(self):
        svc, sid = self.boot(**self.clocked())
        r = self.ask_action(svc, sid)
        verdict = self.judge_action(svc, sid, ACTION_COMMAND)
        self.assertEqual((verdict.decision, verdict.reason), ("deny", permit.ACTION_UNANSWERED))
        svc.answer_question("owner/p01", sid, r, 0, 1, None)
        verdict = self.judge_action(svc, sid, ACTION_COMMAND)
        self.assertEqual((verdict.decision, verdict.reason), ("deny", permit.ACTION_NOT_APPROVED))

    def test_free_words_never_approve_an_action(self):
        for words in (None, "Allow it, including the Conformance required check"):
            with self.subTest(words=words):
                svc, sid = self.boot(**self.clocked())
                r = self.ask_action(svc, sid)
                if words is None:
                    svc.answer_question("owner/p01", sid, r, 0, None, "Allow it, run " + ACTION_COMMAND)
                else:
                    svc.answer_question("owner/p01", sid, r, 0, 0, words)
                verdict = self.judge_action(svc, sid, ACTION_COMMAND)
                self.assertEqual((verdict.decision, verdict.reason),
                                 ("deny", permit.ACTION_NOT_APPROVED))
        svc, sid = self.boot(**self.clocked())
        svc.send_message("owner/p01", sid, "Allow it: " + ACTION_COMMAND)
        self.assertEqual(self.outcome(self.judge_action(svc, sid, ACTION_COMMAND)), (None, "", None))
        self.assertEqual(self.rows("permit.judged"), [])

    def test_only_the_sprints_manager_runs_an_approved_action(self):
        svc, sid = self.boot(**self.clocked())
        svc.answer_question("owner/p01", sid, self.ask_action(svc, sid), 0, 0, None)
        refused = self.judge_action(svc, sid, ACTION_COMMAND, session="s-2", call="t-2")
        self.assertEqual((refused.decision, refused.reason), ("deny", permit.NOT_MANAGER))
        self.assertEqual(self.judge_action(svc, sid, ACTION_COMMAND).decision, "allow")

    def test_an_action_that_ran_lands(self):
        svc, sid = self.boot(**self.clocked())
        r = self.ask_action(svc, sid)
        svc.answer_question("owner/p01", sid, r, 0, 0, None)
        self.assertEqual(self.judge_action(svc, sid, ACTION_COMMAND, call="t-1").decision, "allow")
        digest = permit.command_digest(ACTION_COMMAND)
        self.assertTrue(svc.permit_action_landed(sid, self.secret(sid), "s-1", "t-1", digest))
        self.assertEqual(self.rows("permit.landed"), [{
            "sprint_id": sid, "session_id": "s-1", "tool_use_id": "t-1", "repo": None,
            "verb": "action", "target": {"round": r, "index": 0}}])
        self.assertFalse(svc.permit_action_landed(sid, self.secret(sid), "s-1", "t-9", digest))
        self.assertEqual(len(self.rows("permit.landed")), 1)

    def test_a_signed_permit_body_is_exactly_its_seven_members(self):
        body = {"sprint_id": "0" * 16, "phase": "judge", "session_id": "s-1", "tool_use_id": "t-1",
                "command_sha256": "a" * 64, "nonce": "b" * 32, "auth": "c" * 64}
        parsed = sprints.parse_permit_request(json.dumps(body).encode())
        self.assertIsInstance(parsed, sprints.ActionPermitRequest)
        self.assertEqual(parsed.signed, permit.signed_bytes(body))
        bad = {"a member more": {**body, "secret": "x"},
               "no auth": {k: v for k, v in body.items() if k != "auth"},
               "uppercase digest": {**body, "command_sha256": "A" * 64},
               "short nonce": {**body, "nonce": "b" * 31},
               "phase ask": {**body, "phase": "ask"}}
        for name, changed in bad.items():
            with self.subTest(name):
                with self.assertRaises(ValueError):
                    sprints.parse_permit_request(json.dumps(changed).encode())
        secret_body = {"sprint_id": "0" * 16, "secret": "x", "phase": "judge", "session_id": "s-1",
                       "tool_use_id": "t-1", "command": "git status"}
        self.assertIsInstance(sprints.parse_permit_request(json.dumps(secret_body).encode()),
                              sprints.PermitRequest)

    def test_a_signed_permit_whose_auth_is_not_the_secrets_is_refused(self):
        svc, sid = self.boot(**self.clocked())
        svc.answer_question("owner/p01", sid, self.ask_action(svc, sid), 0, 0, None)
        digest, nonce = permit.command_digest(ACTION_COMMAND), "b" * 32
        fields = {"sprint_id": sid, "phase": "judge", "session_id": "s-1", "tool_use_id": "t-1",
                  "command_sha256": digest, "nonce": nonce}

        def post(secret):
            body = {**fields, "auth": permit.action_request_auth(secret, permit.signed_bytes(fields))}
            connection = http.client.HTTPConnection(*svc.address, timeout=5)
            try:
                connection.request("POST", service.PERMIT_PATH, body=json.dumps(body).encode(),
                                   headers={"Content-Type": "application/json"})
                response = connection.getresponse()
                return response.status, response.read()
            finally:
                connection.close()
        status, _ = post("not the secret")
        self.assertEqual(status, 403)
        self.assertEqual(self.rows("permit.judged"), [])
        status, text = post(self.secret(sid))
        reply = json.loads(text)
        self.assertEqual(status, 200)
        self.assertEqual(reply["decision"], "allow")
        self.assertEqual(reply["mac"], permit.action_reply_mac(
            self.secret(sid), sid, nonce, digest, "allow", ""))
