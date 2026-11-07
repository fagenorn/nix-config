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
from agent_tools import forge_owner_action as foa
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

    def advance(self, at):
        """Move the forge's clock after the store exists: the Date header and new comments' time."""
        stamp = datetime.fromisoformat(at.replace("Z", "+00:00"))
        self.world.respond("gh", ["api", "--include", "rate_limit"],
                           stdout=f"HTTP/2.0 200 OK\r\nDate: {format_datetime(stamp, usegmt=True)}\r\n\r\n{{}}")
        path = self.world.state / "store.json"
        store = json.loads(path.read_text("utf-8"))
        store["clock"] = at
        path.write_text(json.dumps(store), encoding="utf-8")

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
        prompt = self.three_passes("verify-ask", lambda p: self.tick(p.comment_id, "Accept"))
        self.assertEqual(prompt.fields,
                         {"reason": "verify-ask", "block": bkey(ask_check()), "check": "0", "host": "mbp"})
        self.assertIn("Is the dock icon bright?", prompt.body)
        self.assertEqual(self.results(), ["pass"])
        self.assertEqual(self.markers("verify-result")[0].fields["owner"], str(prompt.comment_id))
        self.assertEqual(self.world.issue()["state"], "closed")

    def test_approve(self):
        self.hold(ok_check(effects="live"))
        prompt = self.three_passes("verify-approve", lambda p: self.tick(p.comment_id, "Run it"))
        digest = vo.run_digest({"command": "check-ok"}, {"argv": ["verify-ok"], "cwd": ".", "env": []})
        self.assertEqual(prompt.fields, {"reason": "verify-approve", "block": bkey(ok_check(effects="live")),
                                         "check": "0", "host": "mbp", "effects": "live", "round": "1", "run": digest})
        self.assertIn('Command: ["verify-ok"]', prompt.body)
        self.assertEqual((self.spawned("verify-ok"), self.results()), (1, ["pass"]))

    def test_act(self):
        act = check(kind="human", reason="hands", run={"act": "Plug the dock in", "then": {"command": "check-later"}})
        self.hold(act)
        self.assertEqual(self.run_pass(), [line(0, "AC1", "pending", "owner_asked")])
        self.assertEqual(self.spawned("verify-later"), 0)  # `then` waits for a later pass
        prompt = self.three_passes_after_first(
            "verify-act", lambda p: self.world.respond("verify-later", [], exit=0, stdout="verify-later ran\n"))
        self.assertIn("Plug the dock in", prompt.body)
        self.assertIn('Then: ["verify-later"]', prompt.body)
        self.assertEqual(self.results(), ["pass"])

    def test_stale(self):
        offline = ok_check(host="eleven-m5")
        self.world.comment_store(SLUG, ISSUE, [stored_comment(10, hold(block(offline)), at="2026-10-20T10:00:00Z")],
                                 labels=["needs-verification"])
        prompt = self.three_passes("verify-stale-check", lambda p: self.tick(p.comment_id, "Accept without eleven-m5"))
        self.assertEqual(prompt.fields, {"reason": "verify-stale-check", "block": bkey(offline), "check": "0",
                                         "host": "eleven-m5", "cause": "silent", "last": "never"})
        waived, = self.markers("verify-result")
        self.assertEqual((waived.fields["state"], waived.fields["waived"]), ("pass", "eleven-m5"))
        self.assertEqual(self.world.issue()["state"], "closed")
        self.assertEqual(self.spawned("verify-ok"), 0)


class AskTest(OwnerBase):
    def test_reject_records_a_fail_with_the_failed_label(self):
        self.hold(ask_check())
        self.run_pass()
        prompt, = self.prompts("verify-ask")
        self.tick(prompt.comment_id, "Reject")
        self.assertEqual(self.run_pass(), [line(0, "AC1", "fail", "owner_answered")])
        self.assertEqual(self.results(), ["fail"])
        self.assertIn("verification-failed", self.world.issue()["labels"])
        self.assertEqual(self.prompts("verify-decision"), [])
        mark = len(self.world.argvs("gh"))
        self.run_pass()
        self.assertEqual(self.prompt_posts(mark), [])  # never asked twice for one block version

    def test_silence_and_both_boxes_record_nothing(self):
        self.hold(ask_check())
        self.assertEqual(self.run_pass(), [line(0, "AC1", "pending", "owner_asked")])
        self.assertEqual(self.run_pass(), [line(0, "AC1", "pending", "owner_waiting")])
        prompt, = self.prompts("verify-ask")
        self.tick(prompt.comment_id, "Accept")
        self.tick(prompt.comment_id, "Reject")
        self.assertEqual(self.run_pass(), [line(0, "AC1", "pending", "owner_ambiguous")])
        self.assertEqual(self.results(), [])
        self.assertIn("owner-action", self.world.issue()["labels"])

    def test_another_host_reads_the_answer(self):
        self.hold(ask_check())
        self.run_pass("mbp")
        prompt, = self.prompts("verify-ask")
        self.tick(prompt.comment_id, "Accept")
        self.assertEqual(self.run_pass("eleven-m5")[0], line(0, "AC1", "pass", "owner_answered"))

    def test_two_runners_post_one_prompt(self):
        self.hold(ask_check(host="any"))
        node, = vr.list_held(SLUG)
        self.race(node, "mbp", "eleven-m5")
        self.assertEqual(len(self.prompts("verify-ask")), 1)

    def test_a_delayed_pass_never_reposts_an_answered_prompt(self):
        self.hold(ask_check())
        delayed, = vr.list_held(SLUG)  # a listing taken before any prompt exists
        self.run_pass()
        prompt, = self.prompts("verify-ask")
        self.tick(prompt.comment_id, "Accept")
        self.run_pass()  # records the pass, ends the prompt, closes the issue
        mark = len(self.world.argvs("gh"))
        vr.pass_issue(self.project, "mbp", delayed, Refs())
        self.assertEqual([p.comment_id for p in self.prompts("verify-ask")], [prompt.comment_id])
        self.assertEqual((self.live_prompts(), self.label_calls(mark)), ([], []))
        self.assertEqual(self.world.issue()["state"], "closed")

    def test_a_pass_on_a_replaced_block_never_ends_the_new_block_prompts(self):
        self.hold(ask_check())
        old, = vr.list_held(SLUG)
        fm.edit(SLUG, 10, hold(block(ask_check(ac="AC2"))))  # the owner edits the block: a new version
        self.run_pass()
        new, = self.prompts("verify-ask")
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
        old = fm.render("owner-action", {"reason": "verify-ask", "block": earlier, "check": "0", "host": "mbp"},
                        "AC1: the owner's answer is needed.", "Q?\n\n- [ ] Accept\n- [ ] Reject")
        self.hold(ask_check(ac="AC2"), extra=[stored_comment(11, old)])  # same comment 10, edited content
        self.assertEqual(self.run_pass(), [line(0, "AC2", "pending", "owner_asked")])
        self.assertEqual([p.fields["block"] for p in self.prompts("verify-ask")], [earlier, bkey(ask_check(ac="AC2"))])
        self.assertEqual([p.comment_id for p in self.live_prompts()], [self.prompts("verify-ask")[1].comment_id])
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
        self.assertEqual((self.spawned("verify-ok"), len(self.prompts("verify-approve")), self.consumptions()),
                         (0, 1, []))

    def test_only_the_named_host_consumes_a_ticked_box(self):
        self.hold(ok_check(effects="live"))
        self.run_pass("mbp")
        prompt, = self.prompts("verify-approve")
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
        first, = self.prompts("verify-approve")
        self.tick(first.comment_id, "Run it")
        node, = vr.list_held(SLUG)
        self.race(node, "mbp", "mbp")
        self.assertEqual((self.spawned("verify-later"), len(self.consumptions())), (1, 1))
        self.run_pass()
        self.assertEqual(self.spawned("verify-later"), 1)
        rounds = self.prompts("verify-approve")
        self.assertEqual([p.fields["round"] for p in rounds], ["1", "2"])
        self.assertEqual([p.comment_id for p in self.live_prompts()], [rounds[1].comment_id])
        self.tick(rounds[1].comment_id, "Run it")
        self.run_pass()
        self.assertEqual((self.spawned("verify-later"), len(self.consumptions())), (2, 2))

    def test_a_command_changed_after_the_prompt_needs_a_new_prompt_and_a_new_tick(self):
        self.hold(ok_check(effects="live"))
        self.run_pass()
        first, = self.prompts("verify-approve")
        self.tick(first.comment_id, "Run it")
        commands = {**self.project.bindings["commands"],
                    "check-ok": {**self.project.bindings["commands"]["check-ok"], "argv": ["verify-bad"]}}
        self.project = dataclasses.replace(self.project, bindings={**self.project.bindings, "commands": commands})
        self.assertEqual(self.run_pass(), [line(0, "AC1", "pending", "owner_asked")])
        self.assertEqual((self.spawned("verify-ok"), self.spawned("verify-bad"), self.consumptions()), (0, 0, []))
        rounds = self.prompts("verify-approve")
        self.assertEqual([p.fields["round"] for p in rounds], ["1", "2"])
        self.assertNotEqual(rounds[0].fields["run"], rounds[1].fields["run"])
        self.assertIn('Command: ["verify-bad"]', rounds[1].body)
        self.assertIn(post_end(first.comment_id, "changed"), self.world.argvs("gh"))
        self.assertEqual([p.comment_id for p in self.live_prompts()], [rounds[1].comment_id])
        self.tick(rounds[1].comment_id, "Run it")
        self.run_pass()
        self.assertEqual((self.spawned("verify-ok"), self.spawned("verify-bad")), (0, 1))

    def test_a_tick_survives_a_pass_that_resolves_the_contract_under_a_new_scratch_root(self):
        self.hold(ok_check(effects="live"))
        self.run_pass()
        first, = self.prompts("verify-approve")
        self.tick(first.comment_id, "Run it")
        scratch = Path("/tmp/scratch-export-two/default")  # every real pass resolves under a fresh export
        moved = {name: {**entry, "cwd": str(scratch)} for name, entry in self.project.bindings["commands"].items()}
        self.project = dataclasses.replace(self.project, root=scratch, contract_root=scratch,
                                           bindings={**self.project.bindings, "commands": moved})
        self.assertEqual(self.run_pass()[0], line(0, "AC1", "pass", "changed"))
        self.assertEqual((self.spawned("verify-ok"), len(self.prompts("verify-approve"))), (1, 1))
        self.assertEqual([m.fields["consumed"] for m in self.consumptions()], [str(first.comment_id)])

    def test_a_ticked_approval_for_a_block_replaced_since_the_listing_never_runs(self):
        self.hold(ok_check(effects="live"))
        self.run_pass()
        first, = self.prompts("verify-approve")
        self.tick(first.comment_id, "Run it")
        old, = vr.list_held(SLUG)
        fm.edit(SLUG, 10, hold(block(ok_check(effects="live", ac="AC2"))))  # the owner replaces the held block
        vr.pass_issue(self.project, "mbp", old, Refs())
        self.assertEqual((self.spawned("verify-ok"), self.consumptions()), (0, []))

    def test_an_approved_command_outside_verification_is_still_refused(self):
        self.hold(check(effects="live", run={"command": "nix-activate"}))
        self.assertEqual(self.run_pass(), [line(0, "AC1", "pending", "command_not_verification")])
        self.assertEqual(self.prompts(), [])

    def test_a_consumed_box_left_live_by_a_failed_run_is_never_run_again(self):
        live = ok_check(effects="live")
        self.hold(live)
        self.run_pass()
        prompt, = self.prompts("verify-approve")
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
        decision, = self.prompts("verify-decision")
        self.assertEqual(decision.fields, {"reason": "verify-decision", "block": bkey(bad), "check": "0", "on": "fail",
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
        decision, = self.prompts("verify-decision")
        self.assertEqual((decision.fields["on"], decision.fields["result"]), ("fail", str(fail.comment_id)))
        self.assertIn("owner-action", self.world.issue()["labels"])
        mark = len(self.world.argvs("gh"))
        self.run_pass()
        self.assertEqual(self.prompt_posts(mark), [])

    def test_on_expire_ask_posts_one_decision_and_close_rejects(self):
        later = check(run={"command": "check-later"}, on_expire="ask")
        self.hold(later, extra=self.due_long_ago(later))
        self.assertEqual(self.run_pass(), [line(0, "AC1", "pending", "not_yet")])
        decision, = self.prompts("verify-decision")
        self.assertEqual(decision.fields["on"], "expire")
        self.run_pass()
        self.assertEqual((len(self.prompts("verify-decision")), self.spawned("verify-later")), (1, 2))
        self.tick(decision.comment_id, "Close as not verified")
        self.assertEqual(self.run_pass()[0], line(0, "AC1", "rejected", "owner_answered"))
        self.assertEqual(self.markers("verify-closed")[0].body.split("\n")[1], "Not verified: AC1 rejected.")
        self.assertEqual(self.world.issue()["state_reason"], "not_planned")
        self.assertNotIn("owner-action", self.world.issue()["labels"])

    def test_an_expiry_decision_stays_open_through_a_later_failure(self):
        later = check(run={"command": "check-later"}, on_expire="ask")
        self.hold(later, extra=self.due_long_ago(later))
        self.run_pass()
        decision, = self.prompts("verify-decision")
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
        fields = {"reason": "verify-ask", "block": "10.x", "check": "0", "host": "mbp"}
        self.assertIsNone(vo.answer(prompt_marker(1, fields, "Q?\n\n- [ ] Accept\n- [ ] Reject"), "Accept", "Reject"))
        self.assertEqual(vo.answer(prompt_marker(1, fields, "Q?\n\n- [X] Accept\n- [ ] Reject"), "Accept", "Reject"), "yes")
        self.assertEqual(vo.answer(prompt_marker(1, fields, "Q?\n\n* [ ] Accept\n* [x] Reject"), "Accept", "Reject"), "no")
        self.assertEqual(vo.answer(prompt_marker(1, fields, "- [x] Accept\n- [x] Reject"), "Accept", "Reject"), "ambiguous")
        self.assertIsNone(vo.answer(prompt_marker(1, fields, "- [x] Accepted\n- [ ] Reject"), "Accept", "Reject"))

    def test_prompts_and_settlement(self):
        key = "10.x"
        ask = prompt_marker(20, {"reason": "verify-ask", "block": key, "check": "0", "host": "mbp"}, "- [ ] Accept")
        other = prompt_marker(21, {"reason": "verify-ask", "block": "9.y", "check": "0", "host": "mbp"}, "- [ ] Accept")
        plain = fm.parse({"id": 22, "body": result(key, 0, "fail"), "updated_at": T0})
        owned = fm.parse({"id": 23, "body": result(key, 0, "fail", owner="20"), "updated_at": T0})
        self.assertEqual(vo.prompts([ask, other, plain], "verify-ask", key, 0), [ask])
        self.assertEqual(vo.settle_reason(other, [ask, other], key, ("pass",)), "superseded")
        self.assertIsNone(vo.settle_reason(other, [ask, other], None, ("pass",)))  # no fresh key: never superseded
        self.assertIsNone(vo.settle_reason(ask, [ask], key, ("pass",)))
        self.assertIsNone(vo.settle_reason(ask, [ask, plain], key, ("pass",)))  # a newer result is not an answer
        self.assertEqual(vo.settle_reason(ask, [ask, plain, owned], key, ("pass",)), "answered")
        passed = fm.parse({"id": 25, "body": result(key, 0, "pass"), "updated_at": T0})
        self.assertEqual(vo.settle_reason(ask, [ask, passed], key, ("pass",)), "resolved")  # settled by the check's own result
        self.assertIsNone(vo.settle_reason(ask, [ask, passed], key, ("hit",)))
        ended = fm.parse({"id": 24, "body": fm.end_body(20, "answered"), "updated_at": T0})
        self.assertEqual(vo.live_prompts([ask, ended], ("verify-ask",), key, 0), [])
        # an ended prompt still counts as posted
        self.assertEqual(vo.prompts([ask, ended], "verify-ask", key, 0), [ask])

    def test_decision_and_act_settlement(self):
        key = "10.x"
        decision = prompt_marker(30, {"reason": "verify-decision", "block": key, "check": "0", "on": "expire"},
                                 "- [ ] Passed")
        act = prompt_marker(31, {"reason": "verify-act", "block": key, "check": "0", "host": "mbp"}, "Plug it in")
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


class StaleTest(OwnerBase):
    OLD = "2026-10-20T10:00:00Z"  # server now is 2026-11-06T10:00:00Z unless advanced

    def held_since(self, at, *checks, extra=()):
        self.world.comment_store(SLUG, ISSUE, [stored_comment(10, hold(block(*checks)), at=at), *extra],
                                 labels=["needs-verification"])

    def test_a_young_block_is_not_stale(self):
        self.held_since("2026-11-01T10:00:00Z", ok_check(host="eleven-m5"))
        self.run_pass()
        self.assertEqual(self.prompts(), [])

    def test_any_and_a_host_list_never_go_stale(self):
        self.held_since(self.OLD, ok_check(host="any", when={"not_before": "2030-01-01T00:00:00+00:00"}),
                        ok_check(ac="AC2", host=["eleven-m5", "anis-desktop"]))
        self.run_pass()
        self.assertEqual(self.prompts(), [])

    def test_last_names_the_date_the_host_last_reported(self):
        offline = ok_check(host="eleven-m5")
        due = marker("verify-due", {"block": "9.0000000000000000", "check": "0", "host": "eleven-m5"})
        self.held_since(self.OLD, offline, extra=[stored_comment(11, due, at="2026-10-21T08:00:00Z")])
        self.run_pass()
        stale, = self.prompts("verify-stale-check")
        self.assertEqual((stale.fields["cause"], stale.fields["last"]), ("silent", "2026-10-21"))

    def test_a_reporting_host_whose_check_is_not_due_is_never_stale(self):
        waits = ok_check(when={"not_before": "2030-01-01T00:00:00+00:00"})  # e.g. a release not cut yet
        self.held_since(self.OLD, waits)
        self.assertEqual(self.run_pass("mbp"), [line(0, "AC1", "pending", "not_before")])
        seen, = self.markers("verify-seen")
        self.assertEqual(seen.fields, {"block": bkey(waits), "host": "mbp", "on": "2026-11-06"})
        self.assertEqual(self.run_pass("eleven-m5"), [line(0, "AC1", "pending", "not_this_host")])
        self.assertEqual((self.prompts(), self.label_calls()), ([], []))

    def test_the_report_marker_is_posted_once_and_edited_once_a_day(self):
        self.held_since(self.OLD, ok_check(when={"not_before": "2030-01-01T00:00:00+00:00"}))
        self.run_pass()
        mark = len(self.world.argvs("gh"))
        self.run_pass()
        self.assertEqual(self.mutations(mark), [])
        self.advance("2026-11-07T10:00:00Z")
        self.run_pass()
        seen, = self.markers("verify-seen")
        self.assertEqual(seen.fields["on"], "2026-11-07")
        self.assertEqual(len([a for a in self.world.argvs("gh") if a[1:3] == ["-X", "PATCH"]]), 1)

    def test_a_due_check_unresolved_past_the_stale_age_is_reported_by_its_own_host(self):
        later = check(run={"command": "check-later"})
        due = marker("verify-due", {"block": bkey(later), "check": "0", "host": "mbp"})
        self.held_since(self.OLD, later, extra=[stored_comment(11, due, at="2026-10-28T10:00:00Z")])
        self.assertEqual(self.run_pass(), [line(0, "AC1", "pending", "not_yet")])
        stale, = self.prompts("verify-stale-check")
        self.assertEqual((stale.fields["host"], stale.fields["cause"], stale.fields["last"]),
                         ("mbp", "unresolved", "2026-11-06"))
        self.assertIn("since 2026-10-28", stale.body)

    def test_repeated_unresolved_runs_go_stale_once_seven_days_after_the_check_fell_due(self):
        self.held_since(self.OLD, check(run={"command": "check-later"}))
        for day in ("2026-10-21", "2026-10-24", "2026-10-27"):
            self.advance(f"{day}T10:00:00Z")
            self.assertEqual(self.run_pass(), [line(0, "AC1", "pending", "not_yet")])
        self.assertEqual(self.prompts(), [])  # every pass took and deleted a lease: none moved the clock
        self.advance("2026-10-29T10:00:00Z")
        self.run_pass()
        stale, = self.prompts("verify-stale-check")
        self.assertEqual((stale.fields["cause"], stale.fields["last"]), ("unresolved", "2026-10-29"))
        self.assertIn("since 2026-10-21", stale.body)
        self.advance("2026-11-02T10:00:00Z")
        self.run_pass()
        self.assertEqual((len(self.prompts("verify-stale-check")), self.spawned("verify-later")), (1, 5))

    def test_a_failed_or_prompted_check_is_not_reported_stale(self):
        bad = check(run={"command": "check-bad"})
        self.held_since(self.OLD, bad, check(ac="AC2", kind="human", reason="senses", run={"ask": "Is it bright?"}))
        self.run_pass()
        self.assertEqual([p.fields["reason"] for p in self.prompts()], ["verify-ask"])

    def test_report_posts_nothing(self):
        self.held_since(self.OLD, ok_check(host="eleven-m5"), ok_check(ac="AC2"))
        self.run_pass(report=True)
        self.assertEqual([a for a in self.world.argvs("gh") if "-X" in a], [])

    def test_a_host_with_nothing_unresolved_posts_no_report_marker(self):
        done, away = ok_check(), ok_check(ac="AC2", host="eleven-m5", when={"not_before": "2030-01-01T00:00:00+00:00"})
        self.held_since(self.OLD, done, away)
        self.assertEqual(self.run_pass()[0], line(0, "AC1", "pass", "changed"))
        self.assertEqual(self.markers("verify-seen"), [])

    def test_a_final_or_failed_check_is_not_reported_stale(self):
        checks = [ok_check(host="eleven-m5"), ok_check(ac="AC2", host="eleven-m5"),
                  ok_check(ac="AC3", host="eleven-m5")]
        results = [stored_comment(11, result(bkey(*checks), 0, "pass", host="eleven-m5"), at=self.OLD),
                   stored_comment(12, result(bkey(*checks), 1, "fail", ac="AC2", host="eleven-m5"), at=self.OLD)]
        self.held_since(self.OLD, *checks, extra=results)
        self.run_pass()
        stale, = self.prompts("verify-stale-check")
        self.assertEqual(stale.fields["check"], "2")

    def test_a_check_asked_this_pass_or_holding_a_live_prompt_is_not_also_reported_stale(self):
        asking = ask_check()
        due = marker("verify-due", {"block": bkey(asking), "check": "0", "host": "mbp"})
        self.held_since(self.OLD, asking, extra=[stored_comment(11, due, at="2026-10-28T10:00:00Z")])
        self.run_pass()  # asks this pass
        self.run_pass()  # the ask is live
        self.assertEqual([p.fields["reason"] for p in self.prompts()], ["verify-ask"])

    def test_an_ended_stale_prompt_is_never_posted_again(self):
        offline = ok_check(host="eleven-m5")
        fields = {"reason": "verify-stale-check", "block": bkey(offline), "check": "0", "host": "eleven-m5",
                  "cause": "silent", "last": "never"}
        old = fm.render("owner-action", fields, "AC1 waits on eleven-m5, which last reported never.",
                        "- [ ] Accept without eleven-m5")
        ended = fm.end_body(11, "closed")
        self.held_since(self.OLD, offline, extra=[stored_comment(11, old), stored_comment(12, ended)])
        self.run_pass()
        self.assertEqual([p.comment_id for p in self.prompts("verify-stale-check")], [11])

    def test_the_waive_box_records_a_pass_whichever_runner_reads_it(self):
        offline = ok_check(host="eleven-m5")
        self.held_since(self.OLD, offline, ok_check(ac="AC2", host="eleven-m5"))
        self.run_pass()
        prompt = self.prompts("verify-stale-check")[0]
        self.assertIn("AC1 waits on eleven-m5, which last reported never.", prompt.body)
        self.tick(prompt.comment_id, "Accept without eleven-m5")
        self.assertEqual(self.run_pass("anis-desktop")[0], line(0, "AC1", "pass", "owner_waived"))
        waived = self.markers("verify-result")[0]
        self.assertEqual(waived.fields["owner"], str(prompt.comment_id))
        self.assertEqual(list(waived.fields)[-2:], ["waived", "owner"])


class ForeignOwnerActionTest(OwnerBase):
    """An `owner-action` marker a batch posts (issue 636) is not a verify-pending prompt: no pass ends it.

    It carries `issue`, `reason` and `holder` but no `block` or `check`, so the sweep must leave it live
    whether a block is held or the issue has left the listing, and whatever its reason is named."""

    BATCH_ID = 11

    def batch_marker(self, reason):
        return fm.render("owner-action", {"issue": str(ISSUE), "reason": reason, "holder": "mbp/session-a"},
                         "Delivery waits for the owner's answers below.", "- Which flag?")

    def assert_untouched(self):
        stored = [m for m in (fm.parse(c) for c in self.world.stored()) if m]
        batch, = [m for m in stored if m.comment_id == self.BATCH_ID]
        self.assertTrue(fm.is_live(batch, stored))
        self.assertFalse(any(f"agent:end v1 of={self.BATCH_ID} " in part
                             for a in self.world.argvs("gh") for part in a))

    def held_block_pass(self, reason):
        self.hold(ask_check(), extra=[stored_comment(self.BATCH_ID, self.batch_marker(reason))])
        self.assertEqual(self.run_pass(), [line(0, "AC1", "pending", "owner_asked")])
        self.assert_untouched()
        self.assertIn("owner-action", self.world.issue()["labels"])

    def closing_pass(self, reason):
        self.hold(ask_check(), extra=[stored_comment(self.BATCH_ID, self.batch_marker(reason))])
        delayed, = vr.list_held(SLUG)
        fm.remove_label(SLUG, ISSUE, "needs-verification")  # the issue leaves the listing: no held block
        vr.pass_issue(self.project, "mbp", delayed, Refs())  # must not raise
        self.assert_untouched()
        self.assertIn("owner-action", self.world.issue()["labels"])  # the batch marker still stands

    def test_a_batch_decision_survives_a_pass_on_a_held_block(self):
        self.held_block_pass(foa.REASONS[0])

    def test_a_batch_decision_survives_a_pass_with_no_held_block(self):
        self.closing_pass(foa.REASONS[0])

    def test_a_marker_without_block_and_check_is_ignored_even_under_a_verify_reason(self):
        self.held_block_pass(vo.DECISION)

    def test_a_marker_without_block_and_check_is_ignored_on_the_closing_path(self):
        self.closing_pass(vo.DECISION)

    def test_the_two_reason_sets_are_disjoint(self):
        self.assertEqual(set(vo.REASONS) & set(foa.REASONS), set())


class StaleVocabularyTest(unittest.TestCase):
    """`last_seen` counts report markers of the host only; a prompt of `stale-check` settles like an ask."""

    def mark(self, cid, kind, fields, at):
        return fm.parse({"id": cid, "body": fm.render(kind, fields, "Recorded."), "updated_at": at})

    def test_only_report_markers_of_the_host_move_its_clock(self):
        host = {"host": "eleven-m5"}
        quiet = [self.mark(1, "verify-run", host, "2026-11-01T00:00:00Z"),
                 self.mark(2, "verify-run", {"consumed": "5", **host}, "2026-11-02T00:00:00Z"),
                 self.mark(3, "owner-action", {"reason": "verify-approve", **host}, "2026-11-03T00:00:00Z"),
                 self.mark(4, "verify-result", {"host": "mbp"}, "2026-11-04T00:00:00Z")]
        self.assertEqual((vo.last_seen(quiet, "eleven-m5"), vo.last_report(quiet, "eleven-m5")), (None, "never"))
        kinds = [self.mark(5, "verify-result", host, "2026-10-01T00:00:00Z"),
                 self.mark(6, "verify-due", host, "2026-10-02T00:00:00Z"),
                 self.mark(7, "window-open", host, "2026-10-03T00:00:00Z")]
        self.assertEqual(vo.last_report([*quiet, *kinds], "eleven-m5"), "2026-10-03")

    def test_a_seen_marker_counts_the_day_it_names(self):
        seen = self.mark(1, "verify-seen", {"block": "9.x", "host": "eleven-m5", "on": "2026-11-05"},
                         "2026-10-01T00:00:00Z")
        self.assertEqual(vo.last_report([seen], "eleven-m5"), "2026-11-05")
        self.assertEqual(vo.last_seen([seen], "eleven-m5").isoformat(), "2026-11-05T00:00:00+00:00")

    def test_a_stale_prompt_settles_when_answered_or_final(self):
        key = "9.x"
        prompt = prompt_marker(20, {"reason": "verify-stale-check", "block": key, "check": "0", "host": "eleven-m5",
                                    "cause": "silent", "last": "never"}, "- [ ] Accept without eleven-m5")
        waived = self.mark(21, "verify-result", {"block": key, "check": "0", "state": "pass", "owner": "20"},
                           T0)
        final = self.mark(22, "verify-result", {"block": key, "check": "0", "state": "pass"}, T0)
        self.assertIsNone(vo.settle_reason(prompt, [prompt], key, vr.FINAL))
        self.assertEqual(vo.settle_reason(prompt, [prompt, waived], key, vr.FINAL), "answered")
        self.assertEqual(vo.settle_reason(prompt, [prompt, final], key, vr.FINAL), "resolved")


class ApproveAllLiveTest(OwnerBase):
    """AC3: `approve --all-live` ticks only live prompts of the given repo."""

    def setUp(self):
        super().setUp()
        self.world.respond_json("gh", ["api", "user"], {"login": "octo"})
        self.world.respond_json("gh", ["api", f"repos/{SLUG}"], {"owner": {"login": "octo", "type": "User"}})

    def cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = verify_pending.main(list(argv))
            except SystemExit as exit:
                code = exit.code
        return code, [json.loads(entry) for entry in out.getvalue().splitlines()], err.getvalue()

    def edited(self, since):
        return [int(a[3].rsplit("/", 1)[1]) for a in self.world.argvs("gh")[since:] if a[1:3] == ["-X", "PATCH"]]

    def other_repo(self, name, pages):
        """Serve `octo/<name>`: its owner, and each GraphQL page of its held issues, cursor by cursor."""
        self.world.respond_json("gh", ["api", f"repos/octo/{name}"], {"owner": {"login": "octo", "type": "User"}})
        base = ["api", "graphql", "-f", f"query={vr.APPROVE_QUERY}", "-f", "owner=octo", "-f", f"name={name}"]
        for after, page in pages:
            argv = base if after is None else [*base, "-f", f"after={after}"]
            self.world.respond_json("gh", argv, {"data": {"repository": {"issues": page}}})

    def test_ticks_only_live_prompts_and_never_paid(self):
        live = check(effects="live", run={"command": "check-ok"})
        paid = check(ac="AC2", effects="paid", run={"command": "check-ok"})
        self.hold(live, paid)
        self.run_pass()
        prompts = {p.fields["effects"]: p for p in self.prompts("verify-approve")}
        mark = len(self.world.argvs("gh"))
        code, lines, _ = self.cli("approve", "--repo", SLUG, "--all-live")
        self.assertEqual(code, 0)
        self.assertEqual(self.edited(mark), [prompts["live"].comment_id])
        self.assertEqual(lines, [{"repo": SLUG, "issue": ISSUE, "check": 0, "ac": "AC1",
                                  "comment": prompts["live"].comment_id, "state": "approved", "reason": "all_live"}])
        bodies = {c["id"]: c["body"] for c in self.world.stored()}
        self.assertIn("- [x] Run it", bodies[prompts["live"].comment_id])
        self.assertIn("- [ ] Run it", bodies[prompts["paid"].comment_id])
        mark = len(self.world.argvs("gh"))
        self.assertEqual(self.cli("approve", "--repo", SLUG, "--all-live")[:2], (0, []))
        self.assertEqual(self.edited(mark), [])
        self.run_pass()
        self.assertEqual(self.spawned("verify-ok"), 1)  # the live check ran once; the paid one waits

    def test_every_comment_of_an_issue_beyond_the_last_100_is_read(self):
        self.hold(check(effects="live", run={"command": "check-ok"}))
        self.run_pass()
        prompt, = self.prompts("verify-approve")
        for n in range(101):  # the block and the prompt fall out of the GraphQL `last: 100` window
            self.world.append_comment(stored_comment(1000 + n, f"note {n}"))
        mark = len(self.world.argvs("gh"))
        code, lines, _ = self.cli("approve", "--repo", SLUG, "--all-live")
        self.assertEqual((code, [entry["comment"] for entry in lines]), (0, [prompt.comment_id]))
        self.assertEqual(self.edited(mark), [prompt.comment_id])

    def test_every_page_of_held_issues_is_read(self):
        live = check(effects="live", run={"command": "check-ok"})
        prompt = fm.render("owner-action", {"reason": "verify-approve", "block": bkey(live), "check": "0",
                                            "host": "mbp", "effects": "live", "round": "1", "run": "0123456789abcdef"},
                           "AC1 has live effects.", 'Command: ["verify-ok"]\n\n- [ ] Run it')

        def issue(number, comments):
            return {"number": number, "comments": {"totalCount": len(comments), "nodes": comments}}
        self.other_repo("many", [
            (None, {"pageInfo": {"hasNextPage": True, "endCursor": "c1"},
                    "nodes": [issue(n, []) for n in range(1, 101)]}),
            ("c1", {"pageInfo": {"hasNextPage": False, "endCursor": None},
                    "nodes": [issue(101, [gnode(10, hold(block(live))), gnode(20, prompt)])]})])
        ticked = prompt.replace("- [ ] Run it", "- [x] Run it")
        self.world.respond_json("gh", ["api", "-X", "PATCH", "repos/octo/many/issues/comments/20",
                                       "-f", f"body={ticked}"], {})
        code, lines, _ = self.cli("approve", "--repo", "octo/many", "--all-live")
        self.assertEqual((code, [(entry["issue"], entry["comment"]) for entry in lines]), (0, [(101, 20)]))

    def test_a_listing_that_cannot_be_completed_ticks_nothing_and_exits_1(self):
        self.other_repo("broken", [(None, {"pageInfo": {"hasNextPage": True}, "nodes": []})])
        code, lines, _ = self.cli("approve", "--repo", "octo/broken", "--all-live")
        self.assertEqual((code, [entry["reason"] for entry in lines]), (1, ["forge_error"]))
        self.assertEqual(self.edited(0), [])

    def test_another_repo_is_untouched(self):
        self.hold(check(effects="live", run={"command": "check-ok"}))
        self.run_pass()
        self.other_repo("other", [(None, {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": []})])
        mark = len(self.world.argvs("gh"))
        self.assertEqual(self.cli("approve", "--repo", "octo/other", "--all-live")[:2], (0, []))
        calls = self.world.argvs("gh")[mark:]
        self.assertEqual([a for a in calls if "-X" in a], [])
        self.assertFalse(any(SLUG in part for a in calls for part in a))

    def test_an_untrusted_account_ticks_nothing(self):
        self.hold(check(effects="live", run={"command": "check-ok"}))
        self.run_pass()
        self.world.respond_json("gh", ["api", "user"], {"login": "helper"})
        mark = len(self.world.argvs("gh"))
        code, lines, _ = self.cli("approve", "--repo", SLUG, "--all-live")
        self.assertEqual((code, [entry["reason"] for entry in lines]), (1, ["runner_untrusted"]))
        self.assertEqual(self.edited(mark), [])

    def test_usage_errors_exit_2(self):
        self.assertEqual(self.cli("approve", "--repo", "not a slug", "--all-live")[0], 2)
        self.assertEqual(self.cli("approve", "--repo", SLUG)[0], 2)

    def test_tick_rewrites_one_box(self):
        body = fm.render("owner-action", {"reason": "verify-approve"}, "Run?", "Command: x\n\n- [ ] Run it")
        self.assertEqual(vo.tick(body, "Run it"), body.replace("- [ ] Run it", "- [x] Run it"))
        self.assertIsNone(vo.tick(body.replace("[ ]", "[x]"), "Run it"))
