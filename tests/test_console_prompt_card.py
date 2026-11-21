"""The permission card's rows, fold, open rule, entries and wire shapes (#1424).

Run: just agent-workflow-tests
"""
import json
import os
import subprocess
import sys
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agent_tools.console import event_log, manager, prompt_card, sessions, sprints
from agent_tools.console.event_log import Event

from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)

ROOT = Path(__file__).resolve().parent.parent
PROJECT = "owner/p00"
SPRINT = "a" * 16
BASE = datetime(2026, 11, 21, 12, 0, 0, tzinfo=timezone.utc)
AT = BASE.isoformat(timespec="microseconds")
AT_MS = sessions.at_ms(AT)


def asked(seq, session="s-1", command="git worktree add ../w", description=None, **extra):
    payload = {"sprint_id": SPRINT, "session_id": session, "command": command}
    if description is not None:
        payload["description"] = description
    payload.update(extra)
    return Event(seq, AT, "prompt.asked", PROJECT, payload)


def answered(seq, prompt, answer, **extra):
    return Event(seq, AT, "prompt.answered", PROJECT, {"prompt": prompt, "answer": answer, **extra})


def closed(seq, prompt, reason):
    return Event(seq, AT, "prompt.closed", PROJECT, {"prompt": prompt, "reason": reason})


def sprint(**fields):
    base = sprints.SprintState(SPRINT, PROJECT, "Do the thing. More.", 1, AT,
                               brief=sprints.Brief(1, {"title": "Fix it"}, AT,
                                                   sprints.APPROVED, None, AT),
                               manager_session="s-1")
    return replace(base, **fields)


def session(state=sessions.WORKING, sid="s-1"):
    return sessions.SessionState(sid, "/srv/p00", "/srv/p00", state, "n", 1, AT, None)


def states(folded):
    return {number: prompt.state for number, prompt in folded.items()}


class PromptCardTest(unittest.TestCase):
    def test_rows_have_exact_shapes(self):
        self.assertEqual(
            prompt_card.asked_row(PROJECT, SPRINT, "s-1", "git worktree add x", None),
            ("prompt.asked", PROJECT, {"sprint_id": SPRINT, "session_id": "s-1",
                                       "command": "git worktree add x"}))
        self.assertEqual(
            prompt_card.asked_row(PROJECT, SPRINT, "s-1", "git worktree add x",
                                  "Create the worktree")[2],
            {"sprint_id": SPRINT, "session_id": "s-1", "command": "git worktree add x",
             "description": "Create the worktree"})
        self.assertEqual(prompt_card.answered_row(PROJECT, 7, "allow"),
                         ("prompt.answered", PROJECT, {"prompt": 7, "answer": "allow"}))
        self.assertEqual(prompt_card.closed_row(PROJECT, 7, "expired"),
                         ("prompt.closed", PROJECT, {"prompt": 7, "reason": "expired"}))

    def test_the_wire_constants_are_fixed(self):
        self.assertEqual((manager.PROMPT_HOLD_SECONDS, manager.PROMPT_POLL_SECONDS,
                          manager.PROMPT_TIMEOUT), (600, 2, 660))
        self.assertEqual((event_log.PROMPT_ASKED, event_log.PROMPT_ANSWERED,
                          event_log.PROMPT_CLOSED),
                         ("prompt.asked", "prompt.answered", "prompt.closed"))
        for kind in (event_log.PROMPT_ASKED, event_log.PROMPT_ANSWERED, event_log.PROMPT_CLOSED):
            self.assertNotIn(kind, event_log.KEPT_KINDS)
        self.assertEqual(event_log.SCHEMA_VERSION, 12)
        self.assertEqual((prompt_card.ASK_PATH, prompt_card.ANSWER_PATH),
                         ("/api/permission-prompt", "/api/permission-answer"))
        self.assertEqual((prompt_card.HOLD_SECONDS, prompt_card.POLL_SECONDS,
                          prompt_card.CONTACT_SECONDS, prompt_card.MAX_COMMAND_CHARS,
                          prompt_card.MAX_WORDS_CHARS), (600, 2, 6, 16384, 200))

    def test_the_fold_opens_answers_and_closes_once(self):
        events = [asked(1), answered(2, 1, "allow"), answered(3, 1, "refuse"),
                  asked(4), closed(5, 4, "expired"), answered(6, 4, "allow")]
        folded = prompt_card.prompts(events)
        self.assertEqual(states(folded), {1: prompt_card.ALLOWED, 4: prompt_card.CLOSED})
        self.assertEqual(folded[1], prompt_card.Prompt(
            1, PROJECT, SPRINT, "s-1", "git worktree add ../w", None, AT, prompt_card.ALLOWED))
        with_by = prompt_card.prompts([asked(1), answered(2, 1, "allow", by="guest@x.org")])
        self.assertEqual(states(with_by), {1: prompt_card.OPEN})
        superseded = prompt_card.prompts([asked(1), closed(2, 1, "superseded")])
        self.assertEqual(states(superseded), {1: prompt_card.OPEN})
        bad = prompt_card.prompts([
            Event(1, AT, "prompt.asked", PROJECT,
                  {"sprint_id": SPRINT, "session_id": "s-1"}),
            asked(2, command=""),
            asked(3, command="x" * (prompt_card.MAX_COMMAND_CHARS + 1)),
            asked(4, extra="member"),
            Event(5, AT, "prompt.asked", None,
                  {"sprint_id": SPRINT, "session_id": "s-1", "command": "ls"})])
        self.assertEqual(bad, {})
        ok = prompt_card.prompts([asked(1, command="x" * prompt_card.MAX_COMMAND_CHARS)])
        self.assertEqual(states(ok), {1: prompt_card.OPEN})
        half = prompt_card.prompts(events[:3])
        before = dict(half)
        self.assertEqual(prompt_card.prompts(events[3:], half), folded)
        self.assertEqual(half, before)

    def test_two_prompts_of_one_session_are_held_side_by_side(self):
        folded = prompt_card.prompts([asked(1), asked(2)])
        self.assertEqual(states(folded), {1: prompt_card.OPEN, 2: prompt_card.OPEN})
        contact = {1: AT_MS, 2: AT_MS}
        table = {SPRINT: sprint()}
        held = {"s-1": session()}
        self.assertEqual([p.prompt_id for p in prompt_card.open_prompts(
            folded, AT_MS, table, held, contact)], [1, 2])
        after = prompt_card.prompts([answered(3, 1, "allow")], folded)
        self.assertEqual(states(after), {1: prompt_card.ALLOWED, 2: prompt_card.OPEN})

    def test_a_card_is_open_only_while_its_hook_sprint_and_session_hold(self):
        base = prompt_card.prompts([asked(1)])
        answered_state = prompt_card.prompts([answered(2, 1, "allow")], base)
        edge = prompt_card.CONTACT_SECONDS * 1000
        hold = prompt_card.HOLD_SECONDS * 1000
        now = AT_MS + 1000
        live = {SPRINT: sprint()}
        rows = [
            ("fresh", base, now, live, {"s-1": session()}, {1: now}, True),
            ("hold ran out", base, AT_MS + hold, live, {"s-1": session()}, {1: AT_MS + hold},
             False),
            ("just inside the hold", base, AT_MS + hold - 1, live, {"s-1": session()},
             {1: AT_MS + hold - 1}, True),
            ("no contact", base, now, live, {"s-1": session()}, {}, False),
            ("contact at the edge", base, now, live, {"s-1": session()}, {1: now - edge}, False),
            ("contact one ms later", base, now, live, {"s-1": session()}, {1: now - edge + 1},
             True),
            ("contact for another prompt", base, now, live, {"s-1": session()}, {2: now}, False),
            ("stop requested", base, now, {SPRINT: sprint(stop_at=AT)}, {"s-1": session()},
             {1: now}, False),
            ("closing", base, now,
             {SPRINT: sprint(closing=sprints.Closing(AT, "s", "f", (), ""))},
             {"s-1": session()}, {1: now}, False),
            ("another manager", base, now, {SPRINT: sprint(manager_session="s-2")},
             {"s-1": session()}, {1: now}, False),
            ("session ended", base, now, live, {"s-1": session(sessions.ENDED)}, {1: now},
             False),
            ("session unknown", base, now, live, {}, {1: now}, False),
            ("sprint unknown", base, now, {}, {"s-1": session()}, {1: now}, False),
            ("sprint still drafting", base, now, {SPRINT: sprint(brief=None)},
             {"s-1": session()}, {1: now}, False),
            ("answered", answered_state, now, live, {"s-1": session()}, {1: now}, False),
        ]
        for label, folded, at, table, held, contact, expected in rows:
            with self.subTest(label):
                found = prompt_card.open_prompts(folded, at, table, held, contact)
                self.assertEqual([p.prompt_id for p in found], [1] if expected else [])

    def test_active_is_the_notice_predicate(self):
        self.assertEqual(prompt_card.active(sprint()),
                         sprint().state == sprints.STARTING and sprints.takes_notices(sprint()))
        self.assertTrue(prompt_card.active(sprint()))
        self.assertFalse(prompt_card.active(sprint(stop_at=AT)))
        self.assertFalse(prompt_card.active(sprint(brief=None)))

    def test_each_module_imports_first_in_a_fresh_interpreter(self):
        for name in ("manager", "prompt_card", "sprints", "sprint", "service"):
            with self.subTest(name):
                done = subprocess.run(
                    [sys.executable, "-c", f"import agent_tools.console.{name}"],
                    env={**os.environ, "PYTHONPATH": str(ROOT / "python")},
                    capture_output=True)
                self.assertEqual(done.returncode, 0, done.stderr.decode())

    def test_the_entry_names_the_command_in_plain_words(self):
        state = sprint()
        title = sprints.sprint_title(state)
        found = prompt_card.prompts([asked(
            3, description="Create the delivery's worktree\nmore")])
        entry = prompt_card.inbox_entries(list(found.values()), {SPRINT: state})
        self.assertEqual(entry, [{
            "type": "inbox_item", "reason": "permission", "key": "permission/3",
            "project_id": PROJECT, "sprint_id": SPRINT, "prompt": 3, "title": title,
            "headline": f"The manager of {title} asks to run a command",
            "words": "Create the delivery's worktree", "command": "git worktree add ../w",
            "answered": False, "waiting_since": AT}])
        plain = prompt_card.prompts([asked(1)])
        self.assertEqual(prompt_card.inbox_entries(list(plain.values()), {SPRINT: state})[0]["words"],
                         prompt_card.NO_WORDS)
        self.assertEqual(prompt_card.inbox_entries(list(plain.values()), {}), [])
        long = prompt_card.words("y" * 300)
        self.assertEqual((len(long), long[-1]), (200, "…"))
        self.assertEqual(prompt_card.words("   \n"), prompt_card.NO_WORDS)
        self.assertEqual(prompt_card.words(None), prompt_card.NO_WORDS)

    def test_parsers_refuse_anything_but_the_exact_shapes(self):
        def body(**fields):
            return json.dumps(fields).encode()
        ask = dict(sprint_id=SPRINT, secret="k", phase="ask", session_id="s-1", command="ls")
        wait = dict(sprint_id=SPRINT, secret="k", phase="wait", session_id="s-1", prompt=4)
        self.assertEqual(prompt_card.parse_ask(body(**ask)),
                         prompt_card.AskRequest(SPRINT, "k", "ask", "s-1", "ls", None, None))
        self.assertEqual(prompt_card.parse_ask(body(**ask, description="why")).description, "why")
        self.assertEqual(prompt_card.parse_ask(body(**wait)),
                         prompt_card.AskRequest(SPRINT, "k", "wait", "s-1", None, None, 4))
        self.assertEqual(prompt_card.parse_ask(body(**{**wait, "phase": "close"})).phase, "close")
        self.assertEqual(prompt_card.parse_answer(body(prompt=7, answer="refuse")), (7, "refuse"))
        refused = [
            json.dumps(ask).replace('"command": "ls"', '"command": "ls", "command": "rm"').encode(),
            body(**ask, extra=1),
            body(**{**ask, "command": ""}),
            body(**{**ask, "command": "x" * (prompt_card.MAX_COMMAND_CHARS + 1)}),
            body(**{**ask, "description": 3}),
            body(**{k: v for k, v in ask.items() if k != "command"}),
            body(**{**ask, "phase": "judge"}),
            body(**{**wait, "prompt": True}),
            body(**{**wait, "prompt": 0}),
            body(**{**wait, "command": "ls"}),
            b'{"sprint_id": NaN}',
            b"[]",
        ]
        for text in refused:
            with self.subTest(text[:60]), self.assertRaises(ValueError):
                prompt_card.parse_ask(text)
        for text in (body(prompt=True, answer="allow"), body(prompt=0, answer="allow"),
                     body(prompt=1, answer="yes"), body(prompt=1), body(prompt=1, answer="allow",
                                                                         by="x")):
            with self.subTest(text), self.assertRaises(ValueError):
                prompt_card.parse_answer(text)

    def test_the_hook_output_is_the_clients_permission_decision(self):
        self.assertEqual(json.loads(prompt_card.hook_output("allow")),
                         {"hookSpecificOutput": {"hookEventName": "PermissionRequest",
                                                 "decision": {"behavior": "allow"}}})
        self.assertEqual(
            json.loads(prompt_card.hook_output("deny", "no"))["hookSpecificOutput"]["decision"],
            {"behavior": "deny", "message": "no"})
        self.assertNotIn("\n", prompt_card.hook_output("allow"))

    def test_no_owner_text_names_a_terminal(self):
        texts = {name: value for name, value in vars(prompt_card).items()
                 if not name.startswith("_") and isinstance(value, str)}
        self.assertIn("HEADLINE", texts)
        for name, value in texts.items():
            with self.subTest(name):
                self.assertNotIn("terminal", value.lower())


if __name__ == "__main__":
    unittest.main()
