"""The console's permission card routes (#1424): a manager's held prompt and the owner's answer.

Run: just agent-workflow-tests
"""
import contextlib
import io
import json
import os
import sys
import unittest
from unittest import mock

from agent_tools.console import event_log, guest, manager, prompt_card, service, sprint
from agent_tools.console.event_log import SPRINT_STOP_REQUESTED

from . import console_test_support as support
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)
from .test_console_manager_service import NOW, PermitCase, iso

JSON = {"Content-Type": "application/json"}
COMMAND = "git worktree add ../w"
WORDS = "Create the delivery's worktree"


class PromptCase(PermitCase):
    def boot(self, **kwargs):
        self.now = [NOW]
        self.kwargs = {"clock": lambda: self.now[0], "log_clock": lambda: iso(self.now[0]),
                       **kwargs}
        svc, sid = super().boot(**self.kwargs)
        self.token_file = self.store.parent / "page-token"
        svc.ingest_hook(support.hook_body("session start", session_id="s-1"))
        return svc, sid

    def post(self, svc, path, body, headers=JSON):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        return support.post_page(svc.address, path, headers, data)

    def signed(self, sid, fields, secret=None, nonce=None):
        """The hook's body for `fields`: a fresh nonce and the `auth` of the others, never the secret."""
        fields = {"sprint_id": sid, **fields, "nonce": nonce or os.urandom(16).hex()}
        key = self.secret(sid) if secret is None else secret
        return {**fields, "auth": prompt_card.request_auth(key, prompt_card.signed_bytes(fields))}

    def hook(self, svc, sid, phase, session="s-1", secret=None, **fields):
        body = self.signed(sid, {"phase": phase, "session_id": session, **fields}, secret)
        self.nonce = body["nonce"]
        return self.post(svc, prompt_card.ASK_PATH, body)

    def reply(self, sid, text):
        """The decoded 200 answer to the last `hook`, once its `mac` is checked and removed."""
        decoded = json.loads(text)
        mac = decoded.pop("mac")
        self.assertEqual(mac, prompt_card.reply_mac(
            self.secret(sid), sid, self.nonce, decoded["prompt"], decoded["state"]))
        return decoded

    def ask(self, svc, sid, session="s-1", command=COMMAND, description=WORDS):
        status, _, text = self.hook(svc, sid, "ask", session, command=command,
                                    description=description)
        self.assertEqual(status, 200)
        return self.reply(sid, text)

    def phase(self, svc, sid, phase, prompt, session="s-1"):
        """The status and the decoded answer (the raw text of a refusal) of a wait or a close."""
        status, _, text = self.hook(svc, sid, phase, session, prompt=prompt)
        return status, (self.reply(sid, text) if status == 200 else text)

    def answer(self, svc, prompt, answer, headers=None):
        return self.post(svc, prompt_card.ANSWER_PATH, {"prompt": prompt, "answer": answer},
                         {**self.own(svc), **JSON} if headers is None else headers)

    def state(self, svc):
        status, _, text = support.request(svc.address, "GET", "/api/state")
        self.assertEqual(status, 200)
        return json.loads(text)

    def items(self, svc):
        return [item for item in self.state(svc)["inbox"]["open"]
                if item["reason"] == "permission"]

    def count(self, svc):
        return self.state(svc)["statement"]["inbox_items"]

    def rows(self, kind):
        return [json.loads(row[4]) for row in support.log_rows(self.store) if row[2] == kind]

    def restart(self, svc):
        svc.close()
        return self.start(launcher=support.Launches(), session_poll_seconds=3600,
                          slug_of=lambda root: "p01",
                          branch_pattern_of=lambda root: "issue-<num>-<slug>", **self.kwargs)


class PromptRouteTest(PromptCase):
    def test_a_manager_prompt_is_a_card_the_owner_allows_once_on_the_page(self):
        svc, sid = self.boot()
        asked = self.ask(svc, sid)
        n = asked["prompt"]
        self.assertEqual(asked, {"prompt": n, "state": "open"})
        (item,) = self.items(svc)
        self.assertEqual((item["command"], item["prompt"]), (COMMAND, n))
        self.assertEqual(self.count(svc), 1)
        self.assertEqual(self.answer(svc, n, "allow")[0], 204)
        self.assertEqual(self.phase(svc, sid, "wait", n), (200, {"prompt": n, "state": "allowed"}))
        self.assertEqual(self.items(svc), [])
        self.assertEqual(self.count(svc), 0)
        self.assertEqual(self.rows(event_log.PROMPT_ANSWERED), [{"prompt": n, "answer": "allow"}])

    def test_the_owner_refuses_and_a_second_answer_is_refused(self):
        svc, sid = self.boot()
        n = self.ask(svc, sid)["prompt"]
        self.assertEqual(self.answer(svc, n, "refuse")[0], 204)
        self.assertEqual(self.phase(svc, sid, "wait", n), (200, {"prompt": n, "state": "refused"}))
        status, _, text = self.answer(svc, n, "allow")
        self.assertEqual((status, text), (409, prompt_card.NOT_OPEN.encode() + b"\n"))
        self.assertEqual(self.rows(event_log.PROMPT_ANSWERED), [{"prompt": n, "answer": "refuse"}])

    def test_a_prompt_from_another_session_or_an_inactive_sprint_is_refused_at_once(self):
        svc, sid = self.boot()
        status, _, text = self.hook(svc, sid, "ask", "s-2", command=COMMAND)
        self.assertEqual((status, self.reply(sid, text)), (200, {"prompt": None, "state": "refused"}))
        self.assertEqual(self.rows(event_log.PROMPT_ASKED), [])
        n = self.ask(svc, sid)["prompt"]
        self.assertEqual(self.phase(svc, sid, "wait", n, "s-2")[0], 409)
        self.assertEqual(self.phase(svc, sid, "close", n, "s-2")[0], 409)
        self.assertEqual(len(self.items(svc)), 1)
        self.append(svc, SPRINT_STOP_REQUESTED, {"sprint_id": sid, "goal": "g"})
        status, _, text = self.hook(svc, sid, "ask", command=COMMAND)
        self.assertEqual((status, self.reply(sid, text)), (200, {"prompt": None, "state": "refused"}))
        self.assertEqual(len(self.rows(event_log.PROMPT_ASKED)), 1)

    def test_a_prompt_with_no_reason_is_refused_for_its_reason_and_records_no_card(self):
        svc, sid = self.boot()
        cases = (("absent", {}), ("empty", {"description": ""}),
                 ("blank", {"description": "  \n\t"}))
        for label, fields in cases:
            with self.subTest(label):
                status, _, text = self.hook(svc, sid, "ask", command=COMMAND, **fields)
                self.assertEqual(status, 200)
                self.assertEqual(self.reply(sid, text), {"prompt": None, "state": "unexplained"})
        self.assertEqual(self.rows(event_log.PROMPT_ASKED), [])
        self.assertEqual(self.items(svc), [])
        self.assertEqual(self.count(svc), 0)
        asked = self.ask(svc, sid)
        self.assertEqual(asked, {"prompt": asked["prompt"], "state": "open"})
        self.assertEqual(self.rows(event_log.PROMPT_ASKED), [
            {"sprint_id": sid, "session_id": "s-1", "command": COMMAND, "description": WORDS}])
        (item,) = self.items(svc)
        self.assertEqual(item["words"], WORDS)

    def test_the_answer_route_is_owner_only(self):
        svc, sid = self.boot()
        n = self.ask(svc, sid)["prompt"]
        status, _, text = self.answer(svc, n, "allow", headers=JSON)
        self.assertEqual((status, text), (403, b"origin refused\n"))
        wrong = {"Origin": f"http://127.0.0.1:{svc.address[1]}", "X-Console-Token": "x", **JSON}
        self.assertEqual(self.answer(svc, n, "allow", headers=wrong)[0], 403)
        self.assertEqual(self.rows(event_log.PROMPT_ANSWERED), [])
        self.assertEqual(service.PROMPT_ANSWER_PATH, prompt_card.ANSWER_PATH)
        self.assertEqual(service.PROMPT_PATH, prompt_card.ASK_PATH)
        self.assertIn(service.PROMPT_ANSWER_PATH, service.OWNER_ONLY)
        self.assertIn(service.PROMPT_ANSWER_PATH, service.PAGE_WRITES)
        for held in (service.GUEST_WRITES, service.GUEST_ACCOUNT_WRITES, service.MANAGER_WRITES):
            self.assertNotIn(service.PROMPT_ANSWER_PATH, held)
        self.assertIn(service.PROMPT_PATH, service.MANAGER_WRITES)
        self.assertNotIn(service.PROMPT_PATH, service.PAGE_WRITES)
        self.assertEqual(guest.OWNER_ONLY_INPUTS["prompt_items"], ())

    def test_two_prompts_of_one_session_are_held_side_by_side(self):
        svc, sid = self.boot()
        first = self.ask(svc, sid, command="git status")["prompt"]
        self.now[0] += 1
        second = self.ask(svc, sid, command="git log")["prompt"]
        self.assertNotEqual(first, second)
        for n in (first, second):
            self.assertEqual(self.phase(svc, sid, "wait", n), (200, {"prompt": n, "state": "open"}))
        self.assertEqual(self.count(svc), 2)
        self.assertEqual(self.rows(event_log.PROMPT_CLOSED), [])
        self.assertEqual(self.answer(svc, first, "allow")[0], 204)
        self.assertEqual(self.phase(svc, sid, "wait", first),
                         (200, {"prompt": first, "state": "allowed"}))
        self.assertEqual(self.phase(svc, sid, "wait", second),
                         (200, {"prompt": second, "state": "open"}))
        self.assertEqual([item["prompt"] for item in self.items(svc)], [second])

    def test_a_card_whose_hook_stopped_waiting_leaves_and_takes_no_answer(self):
        svc, sid = self.boot()
        n = self.ask(svc, sid)["prompt"]
        self.now[0] += prompt_card.CONTACT_SECONDS + 1
        svc.poll_sessions()
        self.assertEqual(self.items(svc), [])
        self.assertEqual(self.count(svc), 0)
        status, _, text = self.answer(svc, n, "allow")
        self.assertEqual((status, text), (409, prompt_card.NOT_OPEN.encode() + b"\n"))
        self.assertEqual(self.rows(event_log.PROMPT_ANSWERED), [])
        svc = self.restart(svc)
        self.assertEqual(self.items(svc), [])
        self.assertEqual(self.answer(svc, n, "allow")[0], 409)

    def test_a_card_of_a_session_that_ended_and_was_removed_never_reappears(self):
        svc, sid = self.boot()
        n = self.ask(svc, sid)["prompt"]
        self.assertEqual(len(self.items(svc)), 1)
        svc.ingest_hook(support.hook_body("session end", session_id="s-1"))
        self.assertEqual(self.phase(svc, sid, "wait", n)[0], 200)
        self.assertEqual(self.items(svc), [])
        self.assertEqual(self.answer(svc, n, "allow")[0], 409)
        self.append(svc, "session.gone", {"session_id": "s-1"})
        self.assertEqual(self.phase(svc, sid, "wait", n)[0], 200)
        self.assertEqual(self.items(svc), [])

    def test_a_card_ends_when_its_hold_runs_out_or_its_hook_closes_it(self):
        svc, sid = self.boot()
        n = self.ask(svc, sid)["prompt"]
        for _ in range(prompt_card.HOLD_SECONDS // 2 + 2):
            self.now[0] += 2
            self.assertEqual(self.phase(svc, sid, "wait", n)[0], 200)
            if self.rows(event_log.PROMPT_CLOSED):
                break
        self.assertEqual(self.phase(svc, sid, "wait", n), (200, {"prompt": n, "state": "ended"}))
        self.assertEqual(self.phase(svc, sid, "close", n), (200, {"prompt": n, "state": "ended"}))
        self.assertEqual(self.rows(event_log.PROMPT_CLOSED), [{"prompt": n, "reason": "ended"}])
        self.assertEqual(self.items(svc), [])
        self.assertEqual(self.answer(svc, n, "allow")[0], 409)
        m = self.ask(svc, sid)["prompt"]
        self.assertEqual(self.phase(svc, sid, "close", m), (200, {"prompt": m, "state": "closed"}))
        self.assertEqual(self.rows(event_log.PROMPT_CLOSED)[-1], {"prompt": m, "reason": "expired"})
        self.assertEqual(len(self.rows(event_log.PROMPT_CLOSED)), 2)

    def test_a_stopped_sprint_closes_its_prompt_as_ended_not_as_unanswered(self):
        # R7: the hook is told the console closed it, not that ten minutes passed.
        svc, sid = self.boot()
        n = self.ask(svc, sid)["prompt"]
        self.append(svc, SPRINT_STOP_REQUESTED, {"sprint_id": sid, "goal": "g"})
        self.assertEqual(self.phase(svc, sid, "wait", n), (200, {"prompt": n, "state": "ended"}))
        self.assertEqual(self.rows(event_log.PROMPT_CLOSED), [{"prompt": n, "reason": "ended"}])

    def test_a_close_the_hook_asked_for_stays_closed_not_ended(self):
        svc, sid = self.boot()
        n = self.ask(svc, sid)["prompt"]
        self.assertEqual(self.phase(svc, sid, "close", n), (200, {"prompt": n, "state": "closed"}))
        self.assertEqual(self.phase(svc, sid, "wait", n), (200, {"prompt": n, "state": "closed"}))

    def test_a_request_is_signed_with_the_secret_and_a_reply_is_too_and_the_secret_is_never_sent(self):
        # R1: whatever listens on the port gets no secret and cannot sign a decision the hook honours.
        svc, sid = self.boot()
        secret = self.secret(sid)
        body = self.signed(sid, {"phase": "ask", "session_id": "s-1", "command": COMMAND,
                                  "description": WORDS})
        self.assertNotIn(secret, json.dumps(body))
        status, _, text = self.post(svc, prompt_card.ASK_PATH, body)
        self.assertEqual(status, 200)
        sent = json.loads(text)
        self.assertEqual(set(sent), {"prompt", "state", "mac"})
        self.assertEqual(sent["mac"], prompt_card.reply_mac(
            secret, sid, body["nonce"], sent["prompt"], sent["state"]))
        self.assertNotEqual(sent["mac"], prompt_card.reply_mac(
            secret, sid, "cd" * 16, sent["prompt"], sent["state"]))
        self.assertNotIn(secret, text.decode())
        self.assertEqual(len(self.rows(event_log.PROMPT_ASKED)), 1)

    def test_a_request_that_is_not_signed_by_the_secret_is_refused_and_writes_nothing(self):
        svc, sid = self.boot()
        n = self.ask(svc, sid)["prompt"]
        for name, body in (
                ("a wrong secret", self.signed(sid, {"phase": "ask", "session_id": "s-1",
                                                     "command": COMMAND}, secret="A" * 43)),
                ("a body changed after signing", {
                    **self.signed(sid, {"phase": "ask", "session_id": "s-1", "command": "ls"}),
                    "command": "rm -rf /"}),
                ("a wait for another prompt", {
                    **self.signed(sid, {"phase": "wait", "session_id": "s-1", "prompt": n}),
                    "prompt": n + 1}),
                ("a close made a wait", {
                    **self.signed(sid, {"phase": "close", "session_id": "s-1", "prompt": n}),
                    "phase": "wait"})):
            with self.subTest(name):
                self.assertEqual(self.post(svc, prompt_card.ASK_PATH, body)[0], 403)
        self.assertEqual(len(self.rows(event_log.PROMPT_ASKED)), 1)
        self.assertEqual(self.rows(event_log.PROMPT_CLOSED), [])
        status, _, _ = self.post(svc, prompt_card.ASK_PATH, self.signed(
            "0" * 16, {"phase": "ask", "session_id": "s-1", "command": COMMAND}, secret="x"))
        self.assertEqual(status, 409)

    def test_a_body_that_carries_the_secret_or_has_no_signature_is_a_bad_prompt(self):
        svc, sid = self.boot()
        signed = self.signed(sid, {"phase": "ask", "session_id": "s-1", "command": COMMAND})
        for body in ({**signed, "secret": self.secret(sid)},
                     {k: v for k, v in signed.items() if k != "auth"},
                     {k: v for k, v in signed.items() if k != "nonce"},
                     {**signed, "phase": "prove"}):
            self.assertEqual(self.post(svc, prompt_card.ASK_PATH, body)[0], 400)
        self.assertEqual(self.rows(event_log.PROMPT_ASKED), [])

    def test_a_command_of_the_longest_length_in_any_script_is_held(self):
        # R4: json escapes each astral character to twelve bytes, so the limit is on the escaped body.
        svc, sid = self.boot()
        command = "\U0001F600" * prompt_card.MAX_COMMAND_CHARS
        body = json.dumps(self.signed(sid, {
            "phase": "ask", "session_id": "s-1", "command": command, "description": "d" * 4000}))
        self.assertGreater(len(body), 65536)
        self.assertLessEqual(len(body), service.MAX_PROMPT_BYTES)
        status, _, text = self.post(svc, prompt_card.ASK_PATH, body.encode())
        self.assertEqual(status, 200)
        n = json.loads(text)["prompt"]
        self.assertEqual([item["command"] for item in self.items(svc)], [command])
        self.assertEqual(n, self.items(svc)[0]["prompt"])

    def test_an_answer_accepted_before_the_close_is_what_the_close_returns(self):
        svc, sid = self.boot()
        for answer, word in (("allow", "allowed"), ("refuse", "refused")):
            n = self.ask(svc, sid)["prompt"]
            self.assertEqual(self.answer(svc, n, answer)[0], 204)
            self.assertEqual(self.phase(svc, sid, "close", n), (200, {"prompt": n, "state": word}))
        self.assertEqual(self.rows(event_log.PROMPT_CLOSED), [])

    def test_a_restarted_console_shows_the_card_again_once_its_hook_waits(self):
        svc, sid = self.boot()
        n = self.ask(svc, sid)["prompt"]
        svc = self.restart(svc)
        self.assertEqual(self.items(svc), [])
        self.assertEqual(self.phase(svc, sid, "wait", n), (200, {"prompt": n, "state": "open"}))
        self.assertEqual([item["prompt"] for item in self.items(svc)], [n])


class PromptHookWireTest(PromptCase):
    def test_an_allow_between_the_last_wait_and_the_close_is_honored(self):
        svc, sid = self.boot()
        hook = {"session_id": "s-1", "tool_name": "Bash",
                "tool_input": {"command": COMMAND, "description": WORDS}}
        clock = [0]

        def on_sleep(seconds):
            (item,) = self.items(svc)
            status, _, _ = self.answer(svc, item["prompt"], "allow")
            self.assertEqual(status, 204)
            clock[0] = prompt_card.HOLD_SECONDS + 1

        out = io.StringIO()
        args = sprint.build_parser().parse_args(
            ["permit", "--prompt", "--port", str(svc.address[1])])
        with mock.patch.dict(os.environ, {manager.ID_ENV: sid, manager.SECRET_ENV: self.secret(sid)}), \
                mock.patch.object(sys, "stdin", io.StringIO(json.dumps(hook))), \
                contextlib.redirect_stdout(out):
            code = sprint.run_prompt(args, clock=lambda: clock[0], sleep=on_sleep)
        self.assertEqual(code, 0)
        self.assertEqual(out.getvalue(), prompt_card.hook_output("allow") + "\n")
        self.assertEqual(len(self.rows(event_log.PROMPT_ANSWERED)), 1)
        self.assertEqual(self.rows(event_log.PROMPT_CLOSED), [])


if __name__ == "__main__":
    unittest.main()
