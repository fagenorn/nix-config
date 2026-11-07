"""verify-pending owner prompts (issue 631): ask, approve, act, decision and stale prompts, and the label."""
import contextlib
import dataclasses
import io
import json
import unittest
from datetime import datetime
from email.utils import format_datetime
from pathlib import Path
from unittest import mock

from agent_tools import forge_markers as fm
from agent_tools import verify_owner as vo
from agent_tools import verify_pending
from agent_tools import verify_run as vr

from .test_verify_pending import (ISSUE, SLUG, T0, PassBase, Refs, block, bkey, check, gnode, hold, line, marker,
                                  ok_check, result, stored_comment)

OA_ADD = ["api", "-X", "POST", f"repos/{SLUG}/issues/{ISSUE}/labels", "-f", "labels[]=owner-action"]
OA_REMOVE = ["api", "-X", "DELETE", f"repos/{SLUG}/issues/{ISSUE}/labels/owner-action"]
REPO_ROOT = Path(__file__).resolve().parents[1]


def ask_check(**over):
    return check(kind="human", reason="senses", run={"ask": "Is the dock icon bright?"}, **over)


def post_end(of, reason):
    return ["api", "-X", "POST", f"repos/{SLUG}/issues/{ISSUE}/comments", "-f", f"body={fm.end_body(of, reason)}"]


def prompt_marker(cid, fields, extra, at=T0):
    body = fm.render("owner-action", fields, "Recorded.", extra)
    return fm.parse({"id": cid, "body": body, "updated_at": at})


class OwnerBase(PassBase):
    def prompts(self, reason=None):
        return [m for m in self.markers("owner-action") if reason is None or m.fields.get("reason") == reason]

    def live_prompts(self):
        stored = [m for m in (fm.parse(c) for c in self.world.stored()) if m]
        return [m for m in stored if m.kind == "owner-action" and fm.is_live(m, stored)]

    def prompt_posts(self, since=0):
        return [a for a in self.world.argvs("gh")[since:]
                if len(a) == 6 and a[2] == "POST" and a[3].endswith("/comments")
                and "agent:owner-action" in a[5].split("\n", 1)[0]]

    def label_calls(self, since=0):
        return [a for a in self.world.argvs("gh")[since:] if a in (OA_ADD, OA_REMOVE)]

    def tick(self, comment_id, label):
        body = next(c["body"] for c in self.world.stored() if c["id"] == comment_id)
        self.assertIn(f"- [ ] {label}", body)
        fm.edit(SLUG, comment_id, body.replace(f"- [ ] {label}", f"- [x] {label}", 1))

    def results(self):
        return [m.fields["state"] for m in self.markers("verify-result")]

    def no_human_required(self):
        self.assertFalse(any("human-required" in part for a in self.world.argvs("gh") for part in a))


class PromptOnceTest(OwnerBase):
    """AC1: each prompt is posted once over three passes, carries owner-action, and the label goes when it resolves."""

    def three_passes(self, reason, answer):
        self.run_pass()
        prompt, = self.prompts(reason)
        self.assertIn("owner-action", self.world.issue()["labels"])
        mark = len(self.world.argvs("gh"))
        self.run_pass()
        self.assertEqual((self.prompt_posts(mark), self.label_calls(mark)), ([], []))
        answer(prompt)
        self.run_pass()
        self.assertEqual(len(self.prompts(reason)), 1)
        self.assertEqual(self.live_prompts(), [])
        self.assertNotIn("owner-action", self.world.issue()["labels"])
        self.assertEqual(self.label_calls(), [OA_ADD, OA_REMOVE])
        self.no_human_required()
        return prompt

    def test_ask(self):
        self.hold(ask_check())
        prompt = self.three_passes("ask", lambda p: self.tick(p.comment_id, "Accept"))
        self.assertEqual(prompt.fields, {"reason": "ask", "block": bkey(ask_check()), "check": "0", "host": "mbp"})
        self.assertIn("Is the dock icon bright?", prompt.body)
        self.assertEqual(self.results(), ["pass"])
        self.assertEqual(self.markers("verify-result")[0].fields["owner"], str(prompt.comment_id))
        self.assertEqual(self.world.issue()["state"], "closed")


class AskTest(OwnerBase):
    def test_reject_records_a_fail_with_the_failed_label(self):
        self.hold(ask_check())
        self.run_pass()
        prompt, = self.prompts("ask")
        self.tick(prompt.comment_id, "Reject")
        self.assertEqual(self.run_pass(), [line(0, "AC1", "fail", "owner_answered")])
        self.assertEqual(self.results(), ["fail"])
        self.assertIn("verification-failed", self.world.issue()["labels"])
        self.assertEqual(self.prompts("decision"), [])
        mark = len(self.world.argvs("gh"))
        self.run_pass()
        self.assertEqual(self.prompt_posts(mark), [])  # never asked twice for one block version

    def test_silence_and_both_boxes_record_nothing(self):
        self.hold(ask_check())
        self.assertEqual(self.run_pass(), [line(0, "AC1", "pending", "owner_asked")])
        self.assertEqual(self.run_pass(), [line(0, "AC1", "pending", "owner_waiting")])
        prompt, = self.prompts("ask")
        self.tick(prompt.comment_id, "Accept")
        self.tick(prompt.comment_id, "Reject")
        self.assertEqual(self.run_pass(), [line(0, "AC1", "pending", "owner_ambiguous")])
        self.assertEqual(self.results(), [])
        self.assertIn("owner-action", self.world.issue()["labels"])

    def test_another_host_reads_the_answer(self):
        self.hold(ask_check())
        self.run_pass("mbp")
        prompt, = self.prompts("ask")
        self.tick(prompt.comment_id, "Accept")
        self.assertEqual(self.run_pass("eleven-m5")[0], line(0, "AC1", "pass", "owner_answered"))

    def test_two_runners_post_one_prompt(self):
        self.hold(ask_check(host="any"))
        node, = vr.list_held(SLUG)
        self.race(node, "mbp", "eleven-m5")
        self.assertEqual(len(self.prompts("ask")), 1)

    def test_a_delayed_pass_never_reposts_an_answered_prompt(self):
        self.hold(ask_check())
        delayed, = vr.list_held(SLUG)  # a listing taken before any prompt exists
        self.run_pass()
        prompt, = self.prompts("ask")
        self.tick(prompt.comment_id, "Accept")
        self.run_pass()  # records the pass, ends the prompt, closes the issue
        mark = len(self.world.argvs("gh"))
        vr.pass_issue(self.project, "mbp", delayed, Refs())
        self.assertEqual([p.comment_id for p in self.prompts("ask")], [prompt.comment_id])
        self.assertEqual((self.live_prompts(), self.label_calls(mark)), ([], []))
        self.assertEqual(self.world.issue()["state"], "closed")

    def test_a_pass_on_a_replaced_block_never_ends_the_new_block_prompts(self):
        self.hold(ask_check())
        old, = vr.list_held(SLUG)
        fm.edit(SLUG, 10, hold(block(ask_check(ac="AC2"))))  # the owner edits the block: a new version
        self.run_pass()
        new, = self.prompts("ask")
        self.assertEqual(new.fields["block"], bkey(ask_check(ac="AC2")))
        vr.pass_issue(self.project, "mbp", old, Refs())  # a pass that still holds the old version
        self.assertEqual([p.fields["block"] for p in self.live_prompts()], [bkey(ask_check(ac="AC2"))])
        self.assertNotIn(post_end(new.comment_id, "superseded"), self.world.argvs("gh"))
        self.assertIn("owner-action", self.world.issue()["labels"])

    def test_report_posts_nothing(self):
        self.hold(ask_check())
        self.assertEqual(self.run_pass(report=True), [line(0, "AC1", "pending", "owner_check")])
        self.assertEqual(self.mutations(), [])

    def test_an_edited_block_supersedes_the_old_prompt_and_asks_again(self):
        earlier = bkey(ask_check())
        old = fm.render("owner-action", {"reason": "ask", "block": earlier, "check": "0", "host": "mbp"},
                        "AC1: the owner's answer is needed.", "Q?\n\n- [ ] Accept\n- [ ] Reject")
        self.hold(ask_check(ac="AC2"), extra=[stored_comment(11, old)])  # same comment 10, edited content
        self.assertEqual(self.run_pass(), [line(0, "AC2", "pending", "owner_asked")])
        self.assertEqual([p.fields["block"] for p in self.prompts("ask")], [earlier, bkey(ask_check(ac="AC2"))])
        self.assertEqual([p.comment_id for p in self.live_prompts()], [self.prompts("ask")[1].comment_id])
        self.assertIn(post_end(11, "superseded"), self.world.argvs("gh"))
        self.assertIn("owner-action", self.world.issue()["labels"])


class ClosingEndsPromptsTest(OwnerBase):
    """An issue that closes keeps no live prompt and no owner-action label, whichever way it closes."""

    def test_closing_as_not_verified_ends_a_waiting_ask_and_drops_the_label(self):
        later = check(ac="AC2", run={"command": "check-later"})
        self.hold(ask_check(), later)
        self.run_pass()  # the ask is posted and the later check opens its window
        prompt, = self.live_prompts()
        self.assertIn("owner-action", self.world.issue()["labels"])
        self.world.respond("gh", ["api", "--include", "rate_limit"],
                           stdout="HTTP/2.0 200 OK\r\nDate: Fri, 04 Dec 2026 10:00:00 GMT\r\n\r\n{}")
        self.run_pass()  # the later check outlives its window; the ask is still unanswered
        self.assertEqual(self.markers("verify-closed")[0].fields["outcome"], "expired")
        self.assertEqual(self.world.issue()["state_reason"], "not_planned")
        self.assertEqual(self.live_prompts(), [])
        self.assertIn(post_end(prompt.comment_id, "closed"), self.world.argvs("gh"))
        self.assertNotIn("owner-action", self.world.issue()["labels"])
        self.no_human_required()

    def test_a_delayed_pass_on_a_closed_issue_leaves_no_prompt_and_no_label(self):
        self.hold(ask_check())
        delayed, = vr.list_held(SLUG)  # taken while block A was held
        fm.edit(SLUG, 10, hold(block(ok_check())))  # the owner replaces A with B
        self.run_pass()  # another pass verifies B and closes the issue
        self.assertEqual(self.world.issue()["state"], "closed")
        vr.pass_issue(self.project, "mbp", delayed, Refs())
        self.assertEqual(self.live_prompts(), [])
        self.assertNotIn("owner-action", self.world.issue()["labels"])
        self.assertEqual(self.label_calls(), [])
        self.no_human_required()


class VerifyOwnerTest(unittest.TestCase):
    def test_answer_reads_boxes(self):
        fields = {"reason": "ask", "block": "10.x", "check": "0", "host": "mbp"}
        self.assertIsNone(vo.answer(prompt_marker(1, fields, "Q?\n\n- [ ] Accept\n- [ ] Reject"), "Accept", "Reject"))
        self.assertEqual(vo.answer(prompt_marker(1, fields, "Q?\n\n- [X] Accept\n- [ ] Reject"), "Accept", "Reject"), "yes")
        self.assertEqual(vo.answer(prompt_marker(1, fields, "Q?\n\n* [ ] Accept\n* [x] Reject"), "Accept", "Reject"), "no")
        self.assertEqual(vo.answer(prompt_marker(1, fields, "- [x] Accept\n- [x] Reject"), "Accept", "Reject"), "ambiguous")
        self.assertIsNone(vo.answer(prompt_marker(1, fields, "- [x] Accepted\n- [ ] Reject"), "Accept", "Reject"))

    def test_prompts_and_settlement(self):
        key = "10.x"
        ask = prompt_marker(20, {"reason": "ask", "block": key, "check": "0", "host": "mbp"}, "- [ ] Accept")
        other = prompt_marker(21, {"reason": "ask", "block": "9.y", "check": "0", "host": "mbp"}, "- [ ] Accept")
        plain = fm.parse({"id": 22, "body": result(key, 0, "fail"), "updated_at": T0})
        owned = fm.parse({"id": 23, "body": result(key, 0, "fail", owner="20"), "updated_at": T0})
        self.assertEqual(vo.prompts([ask, other, plain], "ask", key, 0), [ask])
        self.assertEqual(vo.settle_reason(other, [ask, other], key, ("pass",)), "superseded")
        self.assertIsNone(vo.settle_reason(other, [ask, other], None, ("pass",)))  # no fresh key: never superseded
        self.assertIsNone(vo.settle_reason(ask, [ask], key, ("pass",)))
        self.assertIsNone(vo.settle_reason(ask, [ask, plain], key, ("pass",)))  # a newer result is not an answer
        self.assertEqual(vo.settle_reason(ask, [ask, plain, owned], key, ("pass",)), "answered")
        passed = fm.parse({"id": 25, "body": result(key, 0, "pass"), "updated_at": T0})
        self.assertEqual(vo.settle_reason(ask, [ask, passed], key, ("pass",)), "resolved")  # settled by the check's own result
        self.assertIsNone(vo.settle_reason(ask, [ask, passed], key, ("hit",)))
        ended = fm.parse({"id": 24, "body": fm.end_body(20, "answered"), "updated_at": T0})
        self.assertEqual(vo.live_prompts([ask, ended], ("ask",), key, 0), [])
        self.assertEqual(vo.prompts([ask, ended], "ask", key, 0), [ask])  # an ended prompt still counts as posted


class RecipeTest(unittest.TestCase):
    def test_the_suite_runs_this_file(self):
        lines = (REPO_ROOT / "justfile").read_text(encoding="utf-8").splitlines()
        self.assertIn("    tests/test_verify_pending_owner.py \\", lines)
