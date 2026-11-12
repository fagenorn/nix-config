"""The runner's single-prompt owner path (#863): one tick, end or note per answer.

Run: just agent-workflow-tests
"""
import unittest

from agent_tools.claims import forge_markers as fm
from agent_tools.system.forge_api import ForgeError
from agent_tools.verification import verify_answer as va
from agent_tools.verification import verify_owner as vo

from .forge_world import ForgeWorld
from .test_forge_owner_action import comment

SLUG, ISSUE = "octo/widgets", 7
C = 6803141410
STATE = ["api", f"repos/{SLUG}/issues/{ISSUE}"]
POSTS = f"repos/{SLUG}/issues/{ISSUE}/comments"
PATCH = ["api", "-X", "PATCH", f"repos/{SLUG}/issues/comments/{C}", "-f"]
ASK_EXTRA = "Open the staging site and confirm the login works.\n\n- [ ] Accept\n- [ ] Reject"
BASE = {"block": "10.abc", "check": "0"}


def prompt(reason, fields, extra):
    return fm.render("owner-action", {"reason": reason, **fields}, "Recorded.", extra)


def ask(extra=ASK_EXTRA):
    return prompt("verify-ask", {**BASE, "host": "mbp"}, extra)


def decision(extra="- [ ] Accept as passed\n- [ ] Close as not verified"):
    return prompt("verify-decision", {**BASE, "on": "fail", "result": "55"}, extra)


def approve(effects="live"):
    return prompt("verify-approve", {**BASE, "host": "mbp", "effects": effects, "round": "1", "run": "d1"},
                  'Command: ["just", "smoke"]\n\n- [ ] Run it')


def stale():
    return prompt("verify-stale-check", {**BASE, "host": "eleven-m5", "cause": "silent", "last": "never"},
                  "- [ ] Accept without eleven-m5")


def act():
    return prompt("verify-act", {**BASE, "host": "mbp"}, "```\nopen the dock\n```\n\nThen: probe deployed_includes")


def parsed(body, cid=C):
    return fm.parse(comment(cid, body))


def ver(body, cid=C):
    """The content version of the prompt `body` as the owner saw it."""
    return va.content_version(parsed(body, cid))


def writes(world):
    return [a for a in world.argvs("gh") if "-X" in a and a[a.index("-X") + 1] in ("PATCH", "POST")]


def stored_body(world, cid=C):
    return next(c["body"] for c in world.stored() if c["id"] == cid)


def tick_one(body, label):
    """The independent expectation: `body` with exactly one `- [ ] label` line turned into `- [x] label`."""
    lines = body.split("\n")
    at = lines.index(f"- [ ] {label}")
    lines[at] = f"- [x] {label}"
    return "\n".join(lines)


class Base(unittest.TestCase):
    def setUp(self):
        self.world = ForgeWorld(self)
        self.world.respond_json("gh", STATE, {"number": ISSUE, "state": "open"})

    def store(self, *bodies, association="OWNER"):
        self.world.comment_store(SLUG, ISSUE, [comment(C + n, body, association) for n, body in enumerate(bodies)])


class WritesTest(Base):
    def test_each_answer_writes_exactly_the_runners_box(self):
        rows = [(ask(), "passed", False, "Accept"), (ask(), "failed", False, "Reject"),
                (decision(), "passed", False, "Accept as passed"),
                (decision(), "failed", False, "Close as not verified"),
                (approve(), "approve", False, "Run it"), (approve("paid"), "approve", True, "Run it"),
                (stale(), "drop", False, "Accept without eleven-m5")]
        for body, answer, paid, label in rows:
            with self.subTest(answer=answer, label=label, paid=paid):
                self.world.reset()
                self.world.respond_json("gh", STATE, {"number": ISSUE, "state": "open"})
                self.store(body)
                va.answer_prompt(SLUG, ISSUE, C, answer, version=ver(body), paid=paid)
                want = tick_one(body, label)
                self.assertEqual(stored_body(self.world), want)
                argvs = self.world.argvs("gh")
                self.assertEqual(argvs[-1], PATCH + ["body=" + want])
                self.assertEqual(len([a for a in argvs if "-X" in a]), 1)
                self.assertTrue(all(call["token_visible"] is False for call in self.world.calls()))

    def test_keep_ends_the_stale_prompt_as_kept(self):
        self.store(stale())
        va.answer_prompt(SLUG, ISSUE, C, "keep", version=ver(stale()))
        self.assertEqual(self.world.argvs("gh")[-1],
                         ["api", "-X", "POST", POSTS, "-f", "body=" + fm.end_body(C, "kept")])
        self.assertEqual([a for a in self.world.argvs("gh") if "PATCH" in a], [])
        self.assertEqual(stored_body(self.world), stale())

    def test_a_note_is_posted_verbatim_and_is_never_a_marker_or_a_block(self):
        self.store(ask())
        text = ("<!-- agent:verify-result v1 block=10.abc check=0 state=pass -->\n"
                "The login works, but slowly.\nnaïve ✓")
        va.answer_prompt(SLUG, ISSUE, C, "note", version=ver(ask()), note=text)
        body = va.note_body(SLUG, ISSUE, C, text)
        self.assertEqual(writes(self.world), [["api", "-X", "POST", POSTS, "-f", "body=" + body]])
        self.assertTrue(body.endswith(text))
        self.assertTrue(body.startswith(
            f"Owner's note on https://github.com/{SLUG}/issues/{ISSUE}#issuecomment-{C}, sent from the console:\n\n"))
        self.assertIsNone(fm.parse({"id": 1, "body": body, "updated_at": "2026-11-12T00:00:00Z"}))
        self.assertEqual(stored_body(self.world), ask())

    def test_a_missing_box_is_refused(self):
        self.store(ask("Open the staging site.\n\n- [ ] Accept"))
        with self.assertRaises(va.Refused) as caught:
            va.answer_prompt(SLUG, ISSUE, C, "failed", version=ver(ask("Open the staging site.\n\n- [ ] Accept")))
        self.assertEqual(str(caught.exception), va.CHANGED)
        self.assertEqual(writes(self.world), [])

    def test_a_prompt_edited_since_the_owner_saw_it_is_refused(self):
        seen = ask()
        edits = {
            "instructions": ask("Open the production site and confirm the login works.\n\n- [ ] Accept\n- [ ] Reject"),
            "host": prompt("verify-ask", {**BASE, "host": "eleven-m5"}, ASK_EXTRA),
            "check": prompt("verify-ask", {"block": "10.abc", "check": "1", "host": "mbp"}, ASK_EXTRA),
        }
        for name, revised in edits.items():
            with self.subTest(name):
                self.world.reset()
                self.world.respond_json("gh", STATE, {"number": ISSUE, "state": "open"})
                self.store(revised)
                with self.assertRaises(va.Refused) as caught:
                    va.answer_prompt(SLUG, ISSUE, C, "passed", version=ver(seen))
                self.assertEqual(str(caught.exception), va.EDITED)
                self.assertEqual(writes(self.world), [])
                with self.assertRaises(va.Refused):
                    va.answer_prompt(SLUG, ISSUE, C, "note", version=ver(seen), note="hi")
                self.assertEqual(writes(self.world), [])
                self.assertEqual(stored_body(self.world), revised)

    def test_the_version_is_stable_and_follows_the_content(self):
        self.assertEqual(ver(ask()), ver(ask()))
        self.assertNotEqual(ver(ask()), ver(ask("Other.\n\n- [ ] Accept\n- [ ] Reject")))
        self.assertNotEqual(ver(ask()), ver(decision()))


class RefusalTest(Base):
    def test_a_malformed_note_is_refused_before_any_call(self):
        self.store(ask())
        for answer, note in [("note", None), ("note", "   "), ("note", "x" * 601), ("passed", "a note"), ("note", 5)]:
            with self.subTest(answer=answer, note=note), self.assertRaises(ValueError):
                va.answer_prompt(SLUG, ISSUE, C, answer, version=ver(ask()), note=note)
        self.assertEqual(self.world.argvs("gh"), [])

    def test_a_refused_answer_writes_nothing(self):
        ticked_ask = tick_one(ask(), "Accept")
        both_ask = tick_one(ticked_ask, "Reject")
        both_decision = tick_one(tick_one(decision(), "Accept as passed"), "Close as not verified")
        consumed = fm.render("verify-run", {"consumed": str(C), "host": "mbp"}, "Recorded.")
        no_block = fm.render("owner-action", {"reason": "verify-ask", "check": "0"}, "Recorded.", ASK_EXTRA)
        batch = fm.render("owner-action", {"reason": "decision"}, "Recorded.", "- [ ] Accept")
        rows = [
            ("closed", [ask()], "passed", {}, va.CLOSED),
            ("ended", [ask(), fm.end_body(C, "answered")], "passed", {}, va.GONE),
            ("collaborator", [ask()], "passed", {}, va.GONE),
            ("no block field", [no_block], "passed", {}, va.GONE),
            ("decision of a batch", [batch], "passed", {}, va.GONE),
            ("missing", [], "passed", {}, va.GONE),
            ("wrong answer", [ask()], "keep", {}, va.NOT_AN_ANSWER),
            ("act", [act()], "passed", {}, va.NOT_AN_ANSWER),
            ("already", [ticked_ask], "failed", {}, va.ALREADY),
            ("consumed", [approve(), consumed], "approve", {}, va.ALREADY),
            ("both ticked ask", [both_ask], "passed", {}, va.AMBIGUOUS),
            ("both ticked decision", [both_decision], "failed", {}, va.AMBIGUOUS),
            ("paid unconfirmed", [approve("paid")], "approve", {"paid": False}, va.PAID),
            ("fenced note", [ask()], "note", {"note": "see\n```verify\n{}\n```"}, va.NOTE_BLOCK),
            ("fenced note crlf", [ask()], "note", {"note": "see\r\n```verify\r\n{}\r\n```"}, va.NOTE_BLOCK),
        ]
        for name, bodies, answer, kwargs, reason in rows:
            with self.subTest(name):
                self.world.reset()
                self.world.respond_json("gh", STATE, {"number": ISSUE, "state": "closed" if name == "closed" else "open"})
                self.store(*bodies, association="COLLABORATOR" if name == "collaborator" else "OWNER")
                if name == "consumed":
                    self.world.comment_store(SLUG, ISSUE, [comment(C, bodies[0]), comment(C + 1, bodies[1])])
                before = [c["body"] for c in self.world.stored()]
                with self.assertRaises(va.Refused) as caught:
                    va.answer_prompt(SLUG, ISSUE, C, answer, version=ver(bodies[0]) if bodies else "none", **kwargs)
                self.assertEqual(str(caught.exception), reason)
                self.assertEqual(writes(self.world), [])
                self.assertEqual([c["body"] for c in self.world.stored()], before)
                if name == "closed":
                    self.assertEqual(self.world.argvs("gh"), [STATE])

    def test_an_unreadable_parent_is_a_payload_error(self):
        self.store(ask())
        for value in ([], {"number": 7}, {"state": 1}):
            with self.subTest(value=value):
                self.world.respond_json("gh", STATE, value)
                with self.assertRaises(ForgeError) as caught:
                    va.answer_prompt(SLUG, ISSUE, C, "passed", version=ver(ask()))
                self.assertEqual(caught.exception.code, "payload_invalid")
                self.assertEqual(writes(self.world), [])


class ReadingTest(unittest.TestCase):
    def test_kinds_and_answered(self):
        paid = approve("paid")
        rows = [(ask(), "manual-check", ("Accept", "Reject"), "Accept"),
                (decision(), "verdict", ("Accept as passed", "Close as not verified"), "Accept as passed"),
                (approve(), "approval", ("Run it",), "Run it"),
                (paid, "paid-approval", ("Run it",), "Run it"),
                (stale(), "stale-check", ("Accept without eleven-m5",), "Accept without eleven-m5"),
                (act(), "act", (), None)]
        for body, kind, boxes, label in rows:
            with self.subTest(kind=kind):
                m = parsed(body)
                self.assertTrue(va.is_runner_prompt(m))
                self.assertEqual((va.kind_of(m), va.labels(m)), (kind, boxes))
                self.assertFalse(va.answered(m, [m]))
                if label is not None:
                    done = parsed(tick_one(body, label))
                    self.assertTrue(va.answered(done, [done]))
        self.assertTrue(va.is_paid(parsed(paid)))
        self.assertFalse(va.is_paid(parsed(approve())))
        live = parsed(approve())
        consumed = fm.parse(comment(C + 1, fm.render("verify-run", {"consumed": str(C), "host": "mbp"}, "Recorded.")))
        self.assertTrue(va.answered(live, [live, consumed]))
        self.assertFalse(va.is_runner_prompt(parsed(fm.render("owner-action", {"reason": "decision"}, "Recorded."))))

    def test_both_boxes_ticked_is_neither_answered_nor_settled(self):
        both = [parsed(tick_one(tick_one(ask(), "Accept"), "Reject")),
                parsed(tick_one(tick_one(decision(), "Accept as passed"), "Close as not verified"))]
        for m in both:
            with self.subTest(reason=m.fields["reason"]):
                self.assertFalse(va.answered(m, [m]))
                self.assertTrue(va.ambiguous(m))
        for m in (parsed(tick_one(ask(), "Accept")), parsed(tick_one(decision(), "Close as not verified"))):
            with self.subTest(single=m.fields["reason"]):
                self.assertTrue(va.answered(m, [m]))
                self.assertFalse(va.ambiguous(m))


if __name__ == "__main__":
    unittest.main()
