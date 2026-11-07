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
        return self.three_passes_after_first(reason, answer)

    def three_passes_after_first(self, reason, answer):
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

    def test_approve(self):
        self.hold(ok_check(effects="live"))
        prompt = self.three_passes("approve", lambda p: self.tick(p.comment_id, "Run it"))
        digest = vo.run_digest({"command": "check-ok"}, self.project.bindings["commands"]["check-ok"])
        self.assertEqual(prompt.fields, {"reason": "approve", "block": bkey(ok_check(effects="live")), "check": "0",
                                         "host": "mbp", "effects": "live", "round": "1", "run": digest})
        self.assertIn('Command: ["verify-ok"]', prompt.body)
        self.assertEqual((self.spawned("verify-ok"), self.results()), (1, ["pass"]))

    def test_act(self):
        act = check(kind="human", reason="hands", run={"act": "Plug the dock in", "then": {"command": "check-later"}})
        self.hold(act)
        self.assertEqual(self.run_pass(), [line(0, "AC1", "pending", "owner_asked")])
        self.assertEqual(self.spawned("verify-later"), 0)  # `then` waits for a later pass
        prompt = self.three_passes_after_first(
            "act", lambda p: self.world.respond("verify-later", [], exit=0, stdout="verify-later ran\n"))
        self.assertIn("Plug the dock in", prompt.body)
        self.assertIn('Then: ["verify-later"]', prompt.body)
        self.assertEqual(self.results(), ["pass"])


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


class ApproveConsumeTest(OwnerBase):
    """AC2: a ticked approve box is consumed exactly once and only by the named host."""

    def consumptions(self):
        return [m for m in self.markers("verify-run") if "consumed" in m.fields]

    def test_an_unticked_box_never_runs(self):
        self.hold(ok_check(effects="paid"))
        self.assertEqual(self.run_pass(), [line(0, "AC1", "pending", "owner_asked")])
        for _ in range(2):
            self.assertEqual(self.run_pass(), [line(0, "AC1", "pending", "owner_waiting")])
        self.assertEqual((self.spawned("verify-ok"), len(self.prompts("approve")), self.consumptions()), (0, 1, []))

    def test_only_the_named_host_consumes_a_ticked_box(self):
        self.hold(ok_check(effects="live"))
        self.run_pass("mbp")
        prompt, = self.prompts("approve")
        self.tick(prompt.comment_id, "Run it")
        self.assertEqual(self.run_pass("eleven-m5"), [line(0, "AC1", "pending", "not_this_host")])
        self.assertEqual((self.spawned("verify-ok"), self.consumptions()), (0, []))
        self.assertEqual(self.run_pass("mbp")[0], line(0, "AC1", "pass", "changed"))
        self.assertEqual(self.spawned("verify-ok"), 1)
        self.assertEqual([m.fields for m in self.consumptions()],
                         [{"consumed": str(prompt.comment_id), "host": "mbp", "run": prompt.fields["run"]}])
        self.assertEqual(self.world.issue()["state"], "closed")

    def test_two_runs_of_the_named_host_consume_one_tick_once_and_a_rerun_needs_a_new_tick(self):
        later = check(effects="live", run={"command": "check-later"})
        self.hold(later)
        self.run_pass()
        first, = self.prompts("approve")
        self.tick(first.comment_id, "Run it")
        node, = vr.list_held(SLUG)
        self.race(node, "mbp", "mbp")
        self.assertEqual((self.spawned("verify-later"), len(self.consumptions())), (1, 1))
        self.run_pass()
        self.assertEqual(self.spawned("verify-later"), 1)
        rounds = self.prompts("approve")
        self.assertEqual([p.fields["round"] for p in rounds], ["1", "2"])
        self.assertEqual([p.comment_id for p in self.live_prompts()], [rounds[1].comment_id])
        self.tick(rounds[1].comment_id, "Run it")
        self.run_pass()
        self.assertEqual((self.spawned("verify-later"), len(self.consumptions())), (2, 2))

    def test_a_command_changed_after_the_prompt_needs_a_new_prompt_and_a_new_tick(self):
        self.hold(ok_check(effects="live"))
        self.run_pass()
        first, = self.prompts("approve")
        self.tick(first.comment_id, "Run it")
        commands = {**self.project.bindings["commands"],
                    "check-ok": {**self.project.bindings["commands"]["check-ok"], "argv": ["verify-bad"]}}
        self.project = dataclasses.replace(self.project, bindings={**self.project.bindings, "commands": commands})
        self.assertEqual(self.run_pass(), [line(0, "AC1", "pending", "owner_asked")])
        self.assertEqual((self.spawned("verify-ok"), self.spawned("verify-bad"), self.consumptions()), (0, 0, []))
        rounds = self.prompts("approve")
        self.assertEqual([p.fields["round"] for p in rounds], ["1", "2"])
        self.assertNotEqual(rounds[0].fields["run"], rounds[1].fields["run"])
        self.assertIn('Command: ["verify-bad"]', rounds[1].body)
        self.assertIn(post_end(first.comment_id, "changed"), self.world.argvs("gh"))
        self.assertEqual([p.comment_id for p in self.live_prompts()], [rounds[1].comment_id])
        self.tick(rounds[1].comment_id, "Run it")
        self.run_pass()
        self.assertEqual((self.spawned("verify-ok"), self.spawned("verify-bad")), (0, 1))

    def test_an_approved_command_outside_verification_is_still_refused(self):
        self.hold(check(effects="live", run={"command": "nix-activate"}))
        self.assertEqual(self.run_pass(), [line(0, "AC1", "pending", "command_not_verification")])
        self.assertEqual(self.prompts(), [])

    def test_a_consumed_box_left_live_by_a_failed_run_is_never_run_again(self):
        live = ok_check(effects="live")
        self.hold(live)
        self.run_pass()
        prompt, = self.prompts("approve")
        self.tick(prompt.comment_id, "Run it")
        self.world.append_comment(stored_comment(300, marker(
            "verify-run", {"consumed": str(prompt.comment_id), "host": "mbp", "run": prompt.fields["run"]})))
        self.run_pass()
        self.assertEqual(self.spawned("verify-ok"), 0)
        self.assertNotIn(prompt.comment_id, [p.comment_id for p in self.live_prompts()])


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


class QuietFailureTest(OwnerBase):
    """AC4: without `ask`, a failure and an expiry stay off the owner's list; with it they become decisions."""

    def due_long_ago(self, c):
        due = marker("verify-due", {"block": bkey(c), "check": "0", "host": "mbp"})
        return [stored_comment(11, due, at="2026-10-15T10:00:00Z")]

    def test_a_failing_assert_check_without_on_fail_ask_adds_no_owner_action(self):
        self.hold(check(run={"command": "check-bad"}))
        for _ in range(3):
            self.run_pass()
        self.assertEqual((self.prompts(), self.label_calls()), ([], []))
        self.assertEqual(self.world.issue()["labels"], ["needs-verification", "verification-failed"])

    def test_an_expired_check_without_on_expire_ask_adds_no_owner_action(self):
        later = check(run={"command": "check-later"})
        self.hold(later, extra=self.due_long_ago(later))
        self.run_pass()
        self.assertEqual(self.results(), ["expired"])
        self.assertEqual((self.prompts(), self.label_calls()), ([], []))

    def test_on_fail_ask_posts_one_decision_and_accept_passes(self):
        bad = check(run={"command": "check-bad"}, on_fail="ask")
        self.hold(bad)
        self.assertEqual(self.run_pass(), [line(0, "AC1", "fail", "fail_ask")])
        fail, = self.markers("verify-result")
        decision, = self.prompts("decision")
        self.assertEqual(decision.fields, {"reason": "decision", "block": bkey(bad), "check": "0", "on": "fail",
                                           "result": str(fail.comment_id)})
        self.assertEqual(self.label_calls(), [OA_ADD])
        mark = len(self.world.argvs("gh"))
        self.run_pass()
        self.assertEqual(self.prompt_posts(mark), [])
        self.tick(decision.comment_id, "Accept as passed")
        self.assertEqual(self.run_pass()[0], line(0, "AC1", "pass", "owner_answered"))
        self.assertEqual(self.results(), ["fail", "pass"])
        self.assertEqual(self.label_calls(), [OA_ADD, OA_REMOVE])
        self.assertEqual(self.world.issue()["state"], "closed")

    def test_a_fail_decision_lost_after_the_fail_was_recorded_is_posted_by_the_next_pass(self):
        bad = check(run={"command": "check-bad"}, on_fail="ask")
        self.hold(bad)
        with mock.patch.object(vr._Pass, "prompt", side_effect=fm.ForgeError("gh_failed", "HTTP 502")):
            self.assertEqual(self.run_pass(), [line(None, None, "skipped", "forge_error")])
        fail, = self.markers("verify-result")
        self.assertEqual((self.prompts(), self.label_calls()), ([], []))
        self.assertEqual(self.run_pass(), [line(0, "AC1", "fail", "unchanged")])
        decision, = self.prompts("decision")
        self.assertEqual((decision.fields["on"], decision.fields["result"]), ("fail", str(fail.comment_id)))
        self.assertIn("owner-action", self.world.issue()["labels"])
        mark = len(self.world.argvs("gh"))
        self.run_pass()
        self.assertEqual(self.prompt_posts(mark), [])

    def test_on_expire_ask_posts_one_decision_and_close_rejects(self):
        later = check(run={"command": "check-later"}, on_expire="ask")
        self.hold(later, extra=self.due_long_ago(later))
        self.assertEqual(self.run_pass(), [line(0, "AC1", "pending", "not_yet")])
        decision, = self.prompts("decision")
        self.assertEqual(decision.fields["on"], "expire")
        self.run_pass()
        self.assertEqual((len(self.prompts("decision")), self.spawned("verify-later")), (1, 2))
        self.tick(decision.comment_id, "Close as not verified")
        self.assertEqual(self.run_pass()[0], line(0, "AC1", "rejected", "owner_answered"))
        self.assertEqual(self.markers("verify-closed")[0].body.split("\n")[1], "Not verified: AC1 rejected.")
        self.assertEqual(self.world.issue()["state_reason"], "not_planned")
        self.assertNotIn("owner-action", self.world.issue()["labels"])

    def test_an_expiry_decision_stays_open_through_a_later_failure(self):
        later = check(run={"command": "check-later"}, on_expire="ask")
        self.hold(later, extra=self.due_long_ago(later))
        self.run_pass()
        decision, = self.prompts("decision")
        self.world.respond("verify-later", [], exit=1, stdout="verify-later failed\n")
        self.assertEqual(self.run_pass()[0], line(0, "AC1", "fail", "changed"))
        self.assertEqual([p.comment_id for p in self.live_prompts()], [decision.comment_id])
        self.assertNotIn(post_end(decision.comment_id, "answered"), self.world.argvs("gh"))
        self.assertIn("owner-action", self.world.issue()["labels"])
        self.tick(decision.comment_id, "Close as not verified")
        self.assertEqual(self.run_pass()[0], line(0, "AC1", "rejected", "owner_answered"))
        self.assertEqual(self.world.issue()["state"], "closed")

    def test_an_act_then_outside_verification_is_never_run(self):
        act = check(kind="human", reason="hands", run={"act": "Plug it in", "then": {"command": "nix-activate"}})
        self.hold(act)
        self.run_pass()
        self.assertEqual(self.run_pass(), [line(0, "AC1", "pending", "command_not_verification")])
        self.assertEqual(self.spawned("verify-ok"), 0)


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

    def test_decision_and_act_settlement(self):
        key = "10.x"
        decision = prompt_marker(30, {"reason": "decision", "block": key, "check": "0", "on": "expire"}, "- [ ] Passed")
        act = prompt_marker(31, {"reason": "act", "block": key, "check": "0", "host": "mbp"}, "Plug it in")
        plain = fm.parse({"id": 32, "body": result(key, 0, "fail"), "updated_at": T0})
        owned = fm.parse({"id": 33, "body": result(key, 0, "rejected", owner="30"), "updated_at": T0})
        later = fm.parse({"id": 34, "body": result(key, 0, "pass"), "updated_at": T0})
        for prompt in (decision, act):
            self.assertIsNone(vo.settle_reason(prompt, [decision, act], key, vr.FINAL))
            self.assertIsNone(vo.settle_reason(prompt, [decision, act, plain], key, vr.FINAL))  # a fail is not final
        self.assertEqual(vo.settle_reason(decision, [decision, owned], key, vr.FINAL), "answered")
        self.assertEqual(vo.settle_reason(decision, [decision, later], key, vr.FINAL), "resolved")
        self.assertEqual(vo.settle_reason(act, [act, later], key, vr.FINAL), "resolved")
        rejected = fm.parse({"id": 35, "body": result(key, 0, "rejected"), "updated_at": T0})
        self.assertEqual(vo.settle_reason(act, [act, rejected], key, vr.FINAL), "resolved")


class RecipeTest(unittest.TestCase):
    def test_the_suite_runs_this_file(self):
        lines = (REPO_ROOT / "justfile").read_text(encoding="utf-8").splitlines()
        self.assertIn("    tests/test_verify_pending_owner.py \\", lines)
