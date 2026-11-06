"""deliver-standard.js control flow against stub agents (#618, #572 S1).

The Workflow program runs under node with stub agent(), parallel() and phase();
each scenario fixes some agents' replies and asserts the stop or the call sequence.
Run: just agent-workflow-tests
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess
import unittest

REPO_ROOT = Path(__file__).parents[4]
PROGRAM = REPO_ROOT / "home/common/claude-code/skills/deliver-standard/deliver-standard.js"
HARNESS = Path(__file__).with_name("deliver_standard_harness.mjs")
SHA = "a" * 40
ARGS = {"repo_root": "/r", "issue": 9, "session_id": "s1"}
HOLDER = "h1/session-s1"
PLAN = {
    "status": "planned", "plan_root": "/g/plan.md",
    "acceptance": [{"id": "AC1", "text": "works", "kind": "code"}],
    "tasks": [{"n": 1, "title": "one", "file": "/g/task-1.md", "risk": "standard"}],
}


def tasks(count, risk="standard"):
    return [{"n": n, "title": f"t{n}", "file": f"/g/task-{n}.md", "risk": risk}
            for n in range(1, count + 1)]


def run(args=None, replies=None, patch=None):
    node = shutil.which("node")
    if node is None:
        raise AssertionError("node is not on PATH; the deliver-standard scenarios need it")
    scenario = {"args": ARGS if args is None else args, "replies": replies or {}, "patch": patch or {}}
    done = subprocess.run([node, str(HARNESS), str(PROGRAM)], input=json.dumps(scenario),
                          capture_output=True, text=True, timeout=60, check=False)
    if done.returncode != 0:
        raise AssertionError(f"harness failed: {done.stderr}")
    out = json.loads(done.stdout)
    return out["result"], out["calls"]


def labels(calls):
    return [c["label"] for c in calls]


def prompt(calls, label):
    found = [c["prompt"] for c in calls if c["label"] == label]
    if not found:
        raise AssertionError(f"no call labelled {label}: {labels(calls)}")
    return found[-1]


class HappyPathTest(unittest.TestCase):
    def test_one_task_runs_every_stage_in_order(self):
        result, calls = run()
        self.assertEqual(result["stage"], "done")
        self.assertTrue(result["merged"])
        self.assertEqual(labels(calls), [
            "setup", "acquire", "worktree", "renew-plan", "plan", "plan-codex", "plan-review", "renew-tasks",
            "impl-1", "review-1", "renew-final-review", "final-codex", "final-1", "renew-verify", "verify",
            "renew-ship", "pr", "renew-checks-1", "checks-1", "renew-merge", "merge", "close-out"])

    def test_merge_carries_contract_strategy_and_the_checked_head(self):
        # The contract decides the form; a host guard that accepts fewer forms refuses
        # at the merge step, which then stops at stage merge (see the program header).
        head = "b" * 40
        _, calls = run(patch={"setup": {"merge_strategy": "squash", "delete_branch": False,
                                        "unset_env": ["GH_TOKEN"]},
                              "verify": {"head": head}, "pr": {"head": head}, "checks-1": {"head": head}})
        merge = prompt(calls, "merge")
        self.assertIn(f"unset GH_TOKEN && gh pr merge 42 --repo owner/repo --squash "
                      f"--match-head-commit {head}\n", merge)
        self.assertNotIn("--delete-branch", merge)
        self.assertNotIn("GITHUB_TOKEN", PROGRAM.read_text(encoding="utf-8"))

    def test_delete_branch_follows_the_contract(self):
        _, calls = run()
        self.assertIn(f"--merge --match-head-commit {SHA} --delete-branch", prompt(calls, "merge"))

    def test_non_default_integration_closes_the_issue_explicitly(self):
        _, calls = run()
        self.assertIn("Refs #9", prompt(calls, "pr"))
        close = prompt(calls, "close-out")
        self.assertIn("gh issue close 9 --repo owner/repo", close)
        self.assertIn("dev is not the default branch", close)

    def test_default_integration_uses_closes_and_still_confirms(self):
        _, calls = run(patch={"setup": {"integration_branch": "main"}})
        self.assertIn("Closes #9", prompt(calls, "pr"))
        self.assertIn("gh issue close 9", prompt(calls, "close-out"))

    def test_non_code_criterion_holds_the_issue_open(self):
        plan = dict(PLAN, acceptance=PLAN["acceptance"] + [{"id": "AC2", "text": "x", "kind": "evidence"}])
        _, calls = run(replies={"plan": plan}, patch={"setup": {"integration_branch": "main"}})
        self.assertIn("Refs #9", prompt(calls, "pr"))
        close = prompt(calls, "close-out")
        self.assertNotIn("gh issue close", close)
        self.assertIn("needs-verification", close)


class ContractTest(unittest.TestCase):
    def test_no_attribution_in_commits_or_pr_body(self):
        # #640: owner decision on #572, in every project and whatever the contract says.
        _, calls = run(patch={"setup": {"co_authored_by": True}})
        for label in ("impl-1", "pr"):
            self.assertIn("carry no Co-Authored-By trailer and PR bodies no generated-by line", prompt(calls, label))
        self.assertIn("with no attribution or generated-by line", prompt(calls, "pr"))
        text = PROGRAM.read_text(encoding="utf-8")
        self.assertNotIn("co_authored_by", text)
        self.assertNotIn("attribution lines your instructions give", text)
        self.assertNotRegex(text, r"Co-Authored-By: \w")

    def test_missing_contract_field_stops_without_a_default(self):
        result, calls = run(patch={"setup": {"merge_strategy": None}})
        self.assertEqual(result["stage"], "setup")
        self.assertEqual(result["missing"], ["merge_strategy"])
        self.assertEqual(labels(calls), ["setup"])

    def test_setup_refusal_stops_before_any_other_agent(self):
        result, calls = run(replies={"setup": {"ok": False, "reason": "already-merged"}})
        self.assertEqual(result["stage"], "setup")
        self.assertEqual(labels(calls), ["setup"])

    def test_setup_preflight_names_merged_pr_existing_branch_and_applicability(self):
        _, calls = run()
        setup = prompt(calls, "setup")
        for needle in ("duplicate", "re-adopt", "no-longer-applies",
                       "bindings.vcs.worktree.prefix", "bindings.vcs.worktree.root",
                       "--state all --search 9"):
            self.assertIn(needle, setup)
        self.assertNotIn("--add-label", setup)
        claim = prompt(calls, "worktree")
        for needle in ("worktree add --no-track -b issue-9-x /r/.wt/w-issue-9-x origin/dev",
                       "rev-parse --absolute-git-dir"):
            self.assertIn(needle, claim)

    def test_only_gh_commands_carry_the_credential_prefix(self):
        _, calls = run(patch={"setup": {"unset_env": ["GH_TOKEN"]}})
        text = prompt(calls, "impl-1")
        self.assertIn("unset GH_TOKEN && gh pr create", text)
        self.assertIn("; git -C /r branch -d issue-9-x.", text)
        self.assertIn("git -C /r/.wt/w-issue-9-x push origin issue-9-x;", text)
        self.assertNotIn("&& git", text)

    def test_claim_failure_stops_with_a_cont_that_finishes_the_claim(self):
        for reply in ({"ok": False, "reason": "worktree add failed"},
                      {"ok": True, "worktree": "/r/.wt/w-issue-9-x", "base_sha": SHA}):
            with self.subTest(reply=reply):
                result, calls = run(replies={"worktree": reply})
                self.assertEqual(result["stage"], "claim")
                self.assertEqual(labels(calls), ["setup", "acquire", "worktree"])
                cont = result["cont"]
                self.assertTrue(cont["claim_incomplete"])
                result, calls = run(args=dict(ARGS, cont=cont))
                self.assertEqual(result["stage"], "done")
                self.assertEqual(labels(calls)[:5], ["setup", "acquire", "worktree", "renew-plan", "plan"])
                self.assertIn("skip a step already done", prompt(calls, "worktree"))
                self.assertIn("an earlier claim stopped part way", prompt(calls, "setup"))
                self.assertIn("worktree add --no-track -b issue-9-x /r/.wt/w-issue-9-x", prompt(calls, "worktree"))

    def test_blocked_capability_during_an_unfinished_claim_keeps_the_claim_cont(self):
        result, _ = run(replies={"worktree": {"ok": False, "reason": "x"}})
        result, _ = run(args=dict(ARGS, cont=result["cont"]),
                        patch={"setup": {"review_state": {"code": "blocked", "plan": "available"}}})
        self.assertEqual(result["stage"], "review-blocked")
        self.assertTrue(result["cont"]["claim_incomplete"])

    def test_review_capability_without_state_or_command_stops(self):
        for patch, field in (({"review_state": {"plan": "available"}}, "review_state.code"),
                             ({"review": {"plan": "pr"}}, "review.code")):
            with self.subTest(field=field):
                result, calls = run(patch={"setup": patch})
                self.assertEqual(result["stage"], "setup")
                self.assertEqual(result["missing"], [field])
                self.assertEqual(labels(calls), ["setup"])

    def test_blocked_review_capability_stops(self):
        result, calls = run(patch={"setup": {"review_state": {"code": "blocked", "plan": "available"}}})
        self.assertEqual(result["stage"], "review-blocked")
        self.assertEqual(result["review"], "code")
        self.assertNotIn("cont", result)
        self.assertEqual(labels(calls), ["setup"])

    def test_unsupported_review_capability_skips_codex(self):
        result, calls = run(patch={"setup": {"review_state": {"code": "unsupported", "plan": "unsupported"}}})
        self.assertEqual(result["stage"], "done")
        self.assertNotIn("plan-codex", labels(calls))
        self.assertNotIn("final-codex", labels(calls))

    def test_reviewers_get_standards_hints_and_rejections(self):
        _, calls = run()
        for label in ("plan-review", "review-1", "final-1"):
            text = prompt(calls, label)
            for path in ("/r/docs/standards", "/r/.hints", "/r/.rej", "the-bar.md"):
                self.assertIn(path, text, label)


RENEW = f"forge-claim renew --repo owner/repo --issue 9 --holder {HOLDER} --branch issue-9-x"
BOUNDARIES = [("renew-plan", "plan"), ("renew-tasks", "impl-1"), ("renew-final-review", "final-codex"),
              ("renew-verify", "verify"), ("renew-ship", "pr"), ("renew-checks-1", "checks-1"),
              ("renew-merge", "merge")]


class ClaimTest(unittest.TestCase):
    """#635: one claim primitive; held elsewhere stops before any worktree; renew at every boundary."""

    def test_claim_held_elsewhere_stops_before_any_worktree(self):
        for verdict in ("held_by", "lost_to"):
            with self.subTest(verdict=verdict):
                result, calls = run(replies={"acquire": {"verdict": verdict, "by": "h2/b1", "comment_id": 5}})
                self.assertEqual((result["stage"], result["verdict"], result["by"]), ("claimed", verdict, "h2/b1"))
                self.assertNotIn("cont", result)
                self.assertEqual(labels(calls), ["setup", "acquire"])

    def test_acquire_names_the_holder_and_branch(self):
        _, calls = run()
        self.assertIn(f"forge-claim acquire --repo owner/repo --issue 9 --holder {HOLDER} --branch issue-9-x",
                      prompt(calls, "acquire"))
        _, calls = run(args={"repo_root": "/r", "issue": 9, "batch_id": "b7"})
        self.assertIn("--holder h1/b7 ", prompt(calls, "acquire"))

    def test_already_held_continues(self):
        result, _ = run(replies={"acquire": {"verdict": "already_held", "comment_id": 5}})
        self.assertEqual(result["stage"], "done")

    def test_acquire_error_stops_with_a_cont_that_finishes_the_claim(self):
        for reply in ({"verdict": "error", "detail": "forge down"}, None):
            with self.subTest(reply=reply):
                result, calls = run(replies={"acquire": reply})
                self.assertEqual(result["stage"], "claim")
                self.assertTrue(result["cont"]["claim_incomplete"])
                self.assertEqual(labels(calls), ["setup", "acquire"])

    def test_renew_runs_before_every_stage_boundary(self):
        _, calls = run()
        names = labels(calls)
        self.assertEqual([l for l in names if l.startswith("renew-")], [b for b, _ in BOUNDARIES])
        for boundary, first in BOUNDARIES:
            with self.subTest(boundary=boundary):
                self.assertIn(RENEW, prompt(calls, boundary))
                self.assertEqual(names[names.index(first) - 1], boundary)

    def test_ended_claim_stops_at_its_boundary_with_no_cont(self):
        for boundary, first in BOUNDARIES:
            with self.subTest(boundary=boundary):
                result, calls = run(replies={boundary: {"verdict": "not_held", "by": "h2/b1"}})
                self.assertEqual((result["stage"], result["at"]), ("claim-lost", boundary[len("renew-"):]))
                self.assertNotIn(first, labels(calls))
                self.assertNotIn("cont", result)

    def test_unanswered_renew_stops_with_a_cont_that_reacquires(self):
        for boundary, first in BOUNDARIES:
            for reply in ({"verdict": "error", "detail": "forge down"}, None):
                with self.subTest(boundary=boundary, reply=reply):
                    result, calls = run(replies={boundary: reply})
                    self.assertEqual((result["stage"], result["at"]), ("claim-lost", boundary[len("renew-"):]))
                    self.assertNotIn(first, labels(calls))
                    self.assertTrue(result["cont"]["claim_incomplete"])

    def test_resume_after_an_unanswered_renew_reacquires_and_finishes(self):
        stopped, _ = run(replies={"renew-ship": None})
        result, calls = run(args=dict(ARGS, cont=stopped["cont"]),
                            replies={"acquire": {"verdict": "already_held", "comment_id": 7}})
        self.assertEqual(result["stage"], "done")
        self.assertEqual(labels(calls)[:3], ["setup", "acquire", "worktree"])
        self.assertNotIn("plan", labels(calls))
        self.assertNotIn("impl-1", labels(calls))
        result, calls = run(args=dict(ARGS, cont=stopped["cont"]),
                            replies={"acquire": {"verdict": "lost_to", "by": "h2/b1"}})
        self.assertEqual(result["stage"], "claimed")
        self.assertEqual(labels(calls), ["setup", "acquire"])

    def test_holder_id_is_required_and_checked(self):
        for args in ({"repo_root": "/r", "issue": 9}, dict(ARGS, session_id="a b"),
                     {"repo_root": "/r", "issue": 9, "batch_id": "-x"}):
            with self.subTest(args=args):
                result, calls = run(args=args)
                self.assertEqual(result["stage"], "args")
                self.assertEqual(calls, [])

    def test_unusable_host_stops_before_the_claim(self):
        for host in (None, "bad host"):
            with self.subTest(host=host):
                result, calls = run(patch={"setup": {"host": host}})
                self.assertEqual(result["stage"], "setup")
                self.assertEqual(labels(calls), ["setup"])

    def test_setup_checks_no_claim_by_label_or_assignee(self):
        _, calls = run()
        setup = prompt(calls, "setup")
        self.assertNotIn("assignee", setup)
        self.assertNotIn("in-progress", setup)
        self.assertIn("parked", setup)
        self.assertNotIn("--add-label", prompt(calls, "worktree"))

    def test_close_out_releases_the_claim(self):
        _, calls = run()
        close = prompt(calls, "close-out")
        self.assertIn(f"forge-claim release --repo owner/repo --issue 9 --holder {HOLDER} --reason done", close)
        self.assertNotIn("Remove the in-progress label", close)
        result, _ = run(replies={"close-out": {"issue_state": "CLOSED", "released": False, "notes": "not_held"}})
        self.assertEqual(result["stage"], "close-out")

    def test_resume_keeps_the_holder_of_the_claim(self):
        cont = {"setup": {"ok": True, "worktree": "/r/.wt/w-issue-9-x", "branch": "issue-9-x", "plan_dir": "/g",
                          "holder": "h9/b1"}, "plan": None, "plan_reviewed": False, "done": []}
        _, calls = run(args={"repo_root": "/r", "issue": 9, "cont": cont})
        self.assertIn("--holder h9/b1 ", prompt(calls, "renew-plan"))
        self.assertNotIn("acquire", labels(calls))


class SetupIdempotenceTest(unittest.TestCase):
    """#635: setup re-adopts an existing branch or worktree, never resets, stops on a merged duplicate."""

    EXISTING = {"local_branch": True, "remote_branch": True, "worktree": True, "dirty": True,
                "status": " M home/x.py", "head": "e" * 40}
    BANNED = ("reset --hard", "git clean", "checkout --", "git restore")

    def test_dirty_existing_worktree_is_readopted_without_reset(self):
        result, calls = run(patch={"setup": {"existing": self.EXISTING}})
        self.assertEqual(result["stage"], "dirty")
        self.assertEqual(labels(calls), ["setup", "acquire", "worktree"])
        self.assertIn(" M home/x.py", result["details"])
        self.assertEqual(result["cont"]["setup"]["worktree"], "/r/.wt/w-issue-9-x")
        self.assertNotIn("claim_incomplete", result["cont"])
        worktree = prompt(calls, "worktree")
        self.assertIn("adopt", worktree)
        self.assertNotIn("worktree add", worktree)
        for call in calls:
            for banned in self.BANNED:
                self.assertNotIn(banned, call["prompt"], call["label"])

    def test_resume_of_the_adopted_dirty_worktree_still_stops_dirty(self):
        first, _ = run(patch={"setup": {"existing": self.EXISTING}})
        result, calls = run(args=dict(ARGS, cont=first["cont"]), patch={"setup": {"dirty": True}})
        self.assertEqual(result["stage"], "dirty")
        self.assertEqual(labels(calls), ["setup"])

    def test_clean_existing_worktree_is_adopted_and_delivered(self):
        result, calls = run(patch={"setup": {"existing": dict(self.EXISTING, dirty=False, status="")}})
        self.assertEqual(result["stage"], "done")
        worktree = prompt(calls, "worktree")
        self.assertIn("merge-base origin/dev HEAD", worktree)
        self.assertNotIn("worktree add", worktree)
        self.assertIn("Never reset, clean, restore or stash anything in it.", worktree)

    def test_existing_local_branch_gets_a_worktree_without_a_new_branch(self):
        existing = dict(self.EXISTING, worktree=False, remote_branch=False, dirty=False, status="")
        result, calls = run(patch={"setup": {"existing": existing}})
        self.assertEqual(result["stage"], "done")
        worktree = prompt(calls, "worktree")
        self.assertIn("git -C /r worktree add /r/.wt/w-issue-9-x issue-9-x", worktree)
        self.assertNotIn("-b issue-9-x", worktree)

    def test_remote_only_branch_is_checked_out_from_origin(self):
        existing = dict(self.EXISTING, worktree=False, local_branch=False, dirty=False, status="")
        _, calls = run(patch={"setup": {"existing": existing}})
        self.assertIn("git -C /r worktree add --no-track -b issue-9-x /r/.wt/w-issue-9-x origin/issue-9-x",
                      prompt(calls, "worktree"))

    def test_merged_pr_referencing_the_issue_stops_as_a_duplicate(self):
        result, calls = run(replies={"setup": {"ok": False, "reason": "duplicate", "duplicate_pr": 41}})
        self.assertEqual(result["stage"], "setup")
        self.assertEqual(labels(calls), ["setup"])
        result, calls = run(patch={"setup": {"merged_pr": 41}})
        self.assertEqual((result["stage"], result["duplicate"]), ("setup", 41))
        self.assertEqual(labels(calls), ["setup"])

    def test_failed_adoption_resumes_by_adopting_again(self):
        local = dict(self.EXISTING, worktree=False, remote_branch=False, dirty=False, status="")
        failed, _ = run(patch={"setup": {"existing": local}},
                        replies={"worktree": {"ok": False, "notes": "worktree add failed"}})
        self.assertEqual(failed["stage"], "claim")
        self.assertTrue(failed["cont"]["claim_incomplete"])
        result, calls = run(args=dict(ARGS, cont=failed["cont"]), patch={"setup": {"existing": local}})
        self.assertEqual(result["stage"], "done")
        self.assertIn("existing", prompt(calls, "setup"))
        worktree = prompt(calls, "worktree")
        self.assertIn("git -C /r worktree add /r/.wt/w-issue-9-x issue-9-x", worktree)
        self.assertNotIn("-b issue-9-x", worktree)

    def test_resume_of_a_half_made_worktree_adopts_it(self):
        failed, _ = run(replies={"worktree": {"ok": False, "notes": "plan_dir failed"}})
        made = dict(self.EXISTING, dirty=False, status="")
        result, calls = run(args=dict(ARGS, cont=failed["cont"]), patch={"setup": {"existing": made}})
        self.assertEqual(result["stage"], "done")
        self.assertNotIn("worktree add", prompt(calls, "worktree"))

    def test_setup_prompt_readopts_and_names_the_duplicate_rule(self):
        _, calls = run()
        setup = prompt(calls, "setup")
        for needle in ("duplicate", "merged PR", "re-adopt", "--state all --search 9",
                       "never reset, clean, restore or stash", "worktree-mismatch"):
            self.assertIn(needle, setup)
        self.assertNotIn("existing-branch", setup)


class PlanTest(unittest.TestCase):
    def test_plan_stays_outside_the_tree_and_out_of_the_pr(self):
        _, calls = run()
        plan = prompt(calls, "plan")
        self.assertIn("/r/.git/worktrees/w/deliver-standard/plan.md", plan)
        self.assertIn("never commit them", plan)
        self.assertIn("Never attach or link the plan", prompt(calls, "pr"))
        self.assertIn("Acceptance (a table", prompt(calls, "pr"))

    def test_spec_argument_reaches_planner_and_plan_reviewers(self):
        _, calls = run(args=dict(ARGS, spec="/s/spec.md"))
        for label in ("plan", "plan-review", "plan-codex"):
            self.assertIn("/s/spec.md", prompt(calls, label), label)

    def test_needs_user_returns_cont_with_setup_only(self):
        result, calls = run(replies={"plan": {"status": "needs_user", "questions": ["which?"]}})
        self.assertEqual(result["stage"], "plan")
        self.assertEqual(result["needs_user"], ["which?"])
        self.assertIsNone(result["cont"]["plan"])
        self.assertEqual(result["cont"]["setup"]["worktree"], "/r/.wt/w-issue-9-x")

    def test_codex_plan_review_unavailable_stops_and_resume_reviews_again(self):
        result, _ = run(replies={"plan-codex": {"available": False, "verdict": "pass", "findings": []}})
        self.assertEqual((result["stage"], result["step"]), ("codex-unavailable", "plan"))
        self.assertFalse(result["cont"]["plan_reviewed"])
        _, calls = run(args=dict(ARGS, cont=result["cont"]))
        names = labels(calls)
        self.assertNotIn("plan", names)
        self.assertIn("plan-review", names)
        self.assertIn("plan-codex", names)

    def test_plan_without_tasks_stops_instead_of_crashing(self):
        result, calls = run(replies={"plan": {"status": "planned", "plan_root": "/g/plan.md",
                                              "acceptance": PLAN["acceptance"]}})
        self.assertEqual((result["stage"], result["step"]), ("plan", "plan"))
        self.assertIsNone(result["cont"]["plan"])
        self.assertNotIn("plan-review", labels(calls))

    def test_failed_revision_stops_unreviewed(self):
        finding = {"verdict": "findings", "findings": [{"severity": "important", "summary": "gap"}]}
        result, calls = run(replies={"plan-review": finding, "plan-revise": None})
        self.assertEqual(result["stage"], "plan")
        self.assertEqual(result["findings"][0]["summary"], "gap")
        self.assertFalse(result["cont"]["plan_reviewed"])
        self.assertIsNone(result["cont"]["plan"])
        self.assertNotIn("impl-1", labels(calls))

    def test_revision_asking_questions_drops_the_plan(self):
        finding = {"verdict": "findings", "findings": [{"severity": "important", "summary": "gap"}]}
        result, _ = run(replies={"plan-review": finding,
                                 "plan-revise": {"status": "needs_user", "questions": ["q"]}})
        self.assertEqual(result["needs_user"], ["q"])
        self.assertIsNone(result["cont"]["plan"])

    def test_silent_plan_reviewer_stops(self):
        result, _ = run(replies={"plan-review": None})
        self.assertEqual(result["stage"], "plan-review")

    def test_plan_findings_trigger_one_revision(self):
        finding = {"verdict": "findings", "findings": [{"severity": "important", "summary": "gap"}]}
        _, calls = run(replies={"plan-review": finding})
        self.assertEqual(labels(calls).count("plan-revise"), 1)


class TaskTest(unittest.TestCase):
    def test_blocked_task_stops_with_cont_marking_it_partial(self):
        result, _ = run(replies={"impl-1": {"status": "blocked", "notes": "no"}})
        self.assertEqual(result["stage"], "task")
        self.assertEqual(result["cont"]["partial"], 1)
        self.assertEqual(result["cont"]["done"], [])

    def test_unresolved_findings_after_two_fix_rounds_stop(self):
        bad = {"verdict": "findings", "findings": [{"severity": "critical", "summary": "bug"}]}
        result, calls = run(replies={"review-1": bad, "rereview-1-1": bad, "rereview-1-2": bad})
        self.assertEqual(result["stage"], "task-review")
        self.assertEqual([l for l in labels(calls) if l.startswith("fix-1-")], ["fix-1-1", "fix-1-2"])

    def test_low_risk_task_gets_reviewer_lite(self):
        _, calls = run(replies={"plan": dict(PLAN, tasks=tasks(1, "low"))})
        review = [c for c in calls if c["label"] == "review-1"][0]
        self.assertEqual(review["agentType"], "reviewer-lite")
        self.assertIn("lane: low.", review["prompt"])

    def test_first_pass_reviews_use_reviewer_lite_only_in_a_mode_it_accepts(self):
        # reviewer-lite accepts a first pass only for a declared mechanical or low lane;
        # every rereview names the prior findings.
        bad = {"verdict": "findings", "findings": [{"severity": "important", "summary": "bug"}]}
        _, calls = run(replies={"review-1": bad})
        for c in calls:
            if c["agentType"] == "reviewer-lite":
                self.assertTrue(c["label"].startswith("rereview-") or "lane: mechanical." in c["prompt"]
                                or "lane: low." in c["prompt"], c["label"])
        standard = [c for c in calls if c["label"] == "review-1"][0]
        self.assertEqual(standard["agentType"], "reviewer")
        self.assertNotIn("lane:", standard["prompt"])


class ResumeTest(unittest.TestCase):
    def cont(self, **extra):
        setup = {"ok": True, "worktree": "/r/.wt/w-issue-9-x", "branch": "issue-9-x",
                 "plan_dir": "/g"}
        return dict({"setup": setup, "plan": dict(PLAN, tasks=tasks(2)), "plan_reviewed": True,
                     "done": [{"n": 1, "commit": "c1"}]}, **extra)

    def test_cont_readopts_skips_plan_and_finished_tasks(self):
        result, calls = run(args=dict(ARGS, cont=self.cont(partial=2)))
        self.assertEqual(result["stage"], "done")
        names = labels(calls)
        self.assertEqual(names[:4], ["setup", "renew-tasks", "impl-2", "review-2"])
        self.assertNotIn("plan", names)
        self.assertNotIn("impl-1", names)
        self.assertIn("re-adopt", prompt(calls, "setup"))
        self.assertIn("uncommitted edits", prompt(calls, "impl-2"))

    def test_resume_refusal_is_a_setup_stop(self):
        result, calls = run(args=dict(ARGS, cont=self.cont()),
                            replies={"setup": {"ok": False, "reason": "not-resumable"}})
        self.assertEqual(result["stage"], "setup")
        self.assertEqual(labels(calls), ["setup"])

    def test_dirty_resume_without_a_partial_task_stops(self):
        result, calls = run(args=dict(ARGS, cont=self.cont()), patch={"setup": {"dirty": True}})
        self.assertEqual(result["stage"], "dirty")
        self.assertEqual(labels(calls), ["setup"])

    def test_a_stop_before_the_partial_task_keeps_it_partial(self):
        result, _ = run(args=dict(ARGS, cont=self.cont(partial=2)),
                        patch={"setup": {"review_state": {"code": "blocked", "plan": "available"}}})
        self.assertEqual((result["stage"], result["cont"]["partial"]), ("review-blocked", 2))
        result, calls = run(args=dict(ARGS, cont=result["cont"]), patch={"setup": {"dirty": True}})
        self.assertEqual(result["stage"], "done")
        self.assertIn("uncommitted edits", prompt(calls, "impl-2"))

    def test_partial_is_dropped_once_its_task_is_done(self):
        result, _ = run(args=dict(ARGS, cont=self.cont(partial=2)), replies={"verify": None})
        self.assertEqual(result["stage"], "verify")
        self.assertNotIn("partial", result["cont"])

    def test_dirty_resume_of_the_partial_task_continues(self):
        result, _ = run(args=dict(ARGS, cont=self.cont(partial=2)), patch={"setup": {"dirty": True}})
        self.assertEqual(result["stage"], "done")

    def test_resume_after_merge_closes_out_even_with_a_blocked_review(self):
        result, calls = run(args=dict(ARGS, cont=self.cont()),
                            patch={"setup": {"merged_pr": 42, "review_state": {"code": "blocked", "plan": "blocked"}}})
        self.assertEqual(result["stage"], "done")
        self.assertEqual(labels(calls), ["setup", "close-out"])

    def test_resume_after_merge_goes_to_close_out(self):
        result, calls = run(args=dict(ARGS, cont=self.cont()), patch={"setup": {"merged_pr": 42}})
        self.assertEqual(result["stage"], "done")
        self.assertEqual(labels(calls), ["setup", "close-out"])
        self.assertIn("gh issue close 9", prompt(calls, "close-out"))

    def test_cont_without_plan_plans_again(self):
        _, calls = run(args=dict(ARGS, cont={"setup": self.cont()["setup"], "plan": None, "done": []}))
        self.assertIn("plan", labels(calls))


class ReviewAndVerifyTest(unittest.TestCase):
    def test_four_tasks_review_in_two_chunks_plus_integration(self):
        result, calls = run(replies={"plan": dict(PLAN, tasks=tasks(4))})
        self.assertTrue(result["chunked"])
        names = labels(calls)
        for label in ("final-1", "final-2", "final-integration"):
            self.assertIn(label, names)

    def test_silent_final_reviewer_stops(self):
        result, calls = run(replies={"final-1": None})
        self.assertEqual(result["stage"], "final-review")
        self.assertNotIn("fix-wave", labels(calls))

    def test_silent_task_reviewer_stops(self):
        result, _ = run(replies={"review-1": None})
        self.assertEqual(result["stage"], "task-review")
        self.assertEqual(result["cont"]["partial"], 1)

    def test_done_without_both_range_ends_is_not_done(self):
        for reply in ({"status": "done", "start_head": "b0", "notes": "ok"},
                      {"status": "done", "commit": "c1", "notes": "ok"}):
            with self.subTest(reply=reply):
                result, _ = run(replies={"impl-1": reply})
                self.assertEqual(result["stage"], "task")

    def test_skip_eligibility_lists_both_sides_of_a_rename(self):
        _, calls = run()
        self.assertIn("diff --no-renames --name-only", prompt(calls, "verify"))

    def test_fix_reviews_cover_the_whole_fix_range(self):
        bad = {"verdict": "findings", "findings": [{"severity": "important", "summary": "bug"}]}
        _, calls = run(replies={"final-1": bad})
        self.assertIn("diff b0..c0ffee", prompt(calls, "fix-wave-review"))

    def test_codex_code_review_unavailable_stops(self):
        result, _ = run(replies={"final-codex": {"available": False, "verdict": "pass", "findings": []}})
        self.assertEqual((result["stage"], result["step"]), ("codex-unavailable", "code"))

    def test_codex_finding_drives_the_fix_wave(self):
        codex = {"available": True, "verdict": "findings",
                 "findings": [{"severity": "important", "summary": "edge"}]}
        _, calls = run(replies={"final-codex": codex})
        self.assertIn("edge", prompt(calls, "fix-wave"))
        self.assertIn("fix-wave-review", labels(calls))

    def test_missing_or_unearned_results_and_dirty_tree_fail_verification(self):
        for reply in ({"head": SHA, "clean": True, "results": []},
                      {"head": SHA, "clean": True, "results": [{"id": "build", "status": "skipped", "summary": "s"}]},
                      {"head": SHA, "clean": False, "results": [{"id": "build", "status": "pass", "summary": "ok"}]}):
            with self.subTest(reply=reply):
                result, calls = run(replies={"verify": reply, "verify-2": reply, "verify-3": reply})
                self.assertEqual(result["stage"], "verify")
                self.assertNotIn("pr", labels(calls))

    def test_verify_fix_is_reviewed(self):
        fail = {"head": SHA, "clean": True, "results": [{"id": "build", "status": "fail", "summary": "boom"}]}
        bad = {"verdict": "findings", "findings": [{"severity": "important", "summary": "weakened test"}]}
        result, calls = run(replies={"verify": fail, "verify-fix-review-1": bad})
        self.assertEqual(result["stage"], "verify-fix-review")
        self.assertEqual([c["agentType"] for c in calls if c["label"] == "verify-fix-review-1"], ["reviewer"])

    def test_verification_runs_in_each_command_cwd(self):
        _, calls = run(patch={"setup": {"verification": [{"id": "build", "argv": ["npm", "test"], "cwd": "web"}]}})
        verify = prompt(calls, "verify")
        self.assertIn('"cwd":"web"', verify)
        self.assertIn("<worktree>/<its cwd>", verify)

    def test_verify_failing_after_two_fixes_stops(self):
        fail = {"head": SHA, "clean": True, "results": [{"id": "build", "status": "fail", "summary": "boom"}]}
        result, calls = run(replies={"verify": fail, "verify-2": fail, "verify-3": fail})
        self.assertEqual(result["stage"], "verify")
        self.assertEqual([l for l in labels(calls) if l.startswith("verify-fix")],
                         ["verify-fix-1", "verify-fix-review-1", "verify-fix-2", "verify-fix-review-2"])


class ShipTest(unittest.TestCase):
    def test_checks_wait_uses_the_required_names_rule(self):
        _, calls = run()
        checks = prompt(calls, "checks-1")
        self.assertIn("gh api repos/owner/repo/rules/branches/dev", checks)
        self.assertIn("never treat a partial list as green", checks)

    def test_failed_checks_stop_unmerged(self):
        result, calls = run(replies={"checks-1": {"state": "failed", "head": SHA}})
        self.assertEqual(result["stage"], "checks")
        self.assertNotIn("merge", labels(calls))

    def test_clean_sync_rechecks_without_review(self):
        result, calls = run(replies={"checks-1": {"state": "behind", "head": SHA}})
        self.assertEqual(result["stage"], "done")
        names = labels(calls)
        self.assertEqual(names[names.index("checks-1"):], ["checks-1", "sync-1", "renew-checks-2", "checks-2", "renew-merge", "merge", "close-out"])

    def test_conflicted_sync_is_rereviewed(self):
        _, calls = run(replies={"checks-1": {"state": "behind", "head": SHA}},
                       patch={"sync-1": {"conflicted": True, "resolved_files": ["a.py"]}})
        review = [c for c in calls if c["label"] == "sync-review-1"]
        self.assertEqual(review[0]["agentType"], "reviewer")

    def test_conflicted_sync_with_findings_stops(self):
        bad = {"verdict": "findings", "findings": [{"severity": "important", "summary": "lost"}]}
        result, calls = run(replies={"checks-1": {"state": "behind", "head": SHA}, "sync-review-1": bad},
                            patch={"sync-1": {"conflicted": True}})
        self.assertEqual(result["stage"], "sync-review")
        self.assertNotIn("merge", labels(calls))

    def test_third_behind_is_contention(self):
        behind = {"state": "behind", "head": SHA}
        result, calls = run(replies={"checks-1": behind, "checks-2": behind, "checks-3": behind})
        self.assertEqual(result["stage"], "sync-contention")
        self.assertEqual([l for l in labels(calls) if l.startswith("sync-")], ["sync-1", "sync-2"])

    def test_close_out_that_leaves_the_issue_open_is_not_done(self):
        result, _ = run(replies={"close-out": {"issue_state": "OPEN", "notes": "close failed"}})
        self.assertEqual((result["stage"], result["expected_issue_state"]), ("close-out", "CLOSED"))
        self.assertEqual(result["pr"], 42)

    def test_pushed_head_must_be_the_verified_head(self):
        result, calls = run(patch={"pr": {"head": "c" * 40}})
        self.assertEqual((result["stage"], result["expected"]), ("head-moved", SHA))
        self.assertNotIn("checks-1", labels(calls))
        result, calls = run(patch={"checks-1": {"head": "c" * 40}})
        self.assertEqual(result["stage"], "head-moved")
        self.assertNotIn("merge", labels(calls))

    def test_after_a_sync_the_merge_commit_is_the_expected_head(self):
        merge = "d" * 40
        result, calls = run(replies={"checks-1": {"state": "behind", "head": SHA},
                                     "checks-2": {"state": "passed", "head": merge}},
                            patch={"sync-1": {"merge_commit": merge}})
        self.assertEqual(result["stage"], "done")
        self.assertIn(f"--match-head-commit {merge}", prompt(calls, "merge"))

    def test_unmerged_pr_stops_before_close_out(self):
        result, calls = run(replies={"merge": {"merged": False, "notes": "head moved"}})
        self.assertEqual(result["stage"], "merge")
        self.assertNotIn("close-out", labels(calls))


class FixWaveTest(unittest.TestCase):
    """#635 owner comment: a narrowing re-review earns a second wave; a new kind stops; waves are counted."""

    FIRST = {"verdict": "findings", "findings": [{"severity": "critical", "summary": "race in acquire"}]}

    @staticmethod
    def narrowing(summary="race in release"):
        return {"verdict": "findings",
                "findings": [{"severity": "critical", "summary": summary, "relation": "narrowing"}]}

    def test_narrowing_findings_earn_a_second_wave(self):
        result, calls = run(replies={"final-1": self.FIRST, "fix-wave-review": self.narrowing()})
        self.assertEqual((result["stage"], result["fix_waves"]), ("done", 2))
        self.assertEqual([l for l in labels(calls) if l.startswith("fix-wave")],
                         ["fix-wave", "fix-wave-review", "fix-wave-2", "fix-wave-review-2"])
        self.assertIn("race in release", prompt(calls, "fix-wave-2"))
        self.assertIn("race in release", prompt(calls, "fix-wave-review-2"))
        self.assertEqual([c["agentType"] for c in calls if c["label"] == "fix-wave-review-2"], ["reviewer"])

    def test_a_new_kind_of_finding_stops_after_one_wave(self):
        new = {"severity": "critical", "summary": "leak", "relation": "new"}
        bare = {"severity": "critical", "summary": "leak"}
        narrow = {"severity": "critical", "summary": "race in release", "relation": "narrowing"}
        for findings in ([new], [bare], [narrow, new]):
            with self.subTest(findings=findings):
                rv = {"verdict": "findings", "findings": findings}
                result, calls = run(replies={"final-1": self.FIRST, "fix-wave-review": rv})
                self.assertEqual((result["stage"], result["fix_waves"]), ("fix-wave-review", 1))
                self.assertNotIn("fix-wave-2", labels(calls))

    def test_findings_after_the_second_wave_stop(self):
        result, calls = run(replies={"final-1": self.FIRST, "fix-wave-review": self.narrowing(),
                                     "fix-wave-review-2": self.narrowing("race in renew")})
        self.assertEqual((result["stage"], result["fix_waves"]), ("fix-wave-review", 2))
        self.assertNotIn("fix-wave-3", labels(calls))

    def test_failed_second_wave_stops(self):
        result, _ = run(replies={"final-1": self.FIRST, "fix-wave-review": self.narrowing(),
                                 "fix-wave-2": {"status": "blocked", "notes": "no"}})
        self.assertEqual((result["stage"], result["fix_waves"]), ("fix-wave", 2))

    def test_rereview_is_asked_to_classify_each_finding(self):
        _, calls = run(replies={"final-1": self.FIRST})
        rereview = prompt(calls, "fix-wave-review")
        for needle in ("relation", "narrowing", "Unsure is new"):
            self.assertIn(needle, rereview)

    def test_waves_are_counted(self):
        result, _ = run()
        self.assertEqual(result["fix_waves"], 0)
        result, _ = run(replies={"final-1": self.FIRST})
        self.assertEqual((result["stage"], result["fix_waves"]), ("done", 1))


class ModeTest(unittest.TestCase):
    """#635: each mode stops at its stage and returns its stage object."""

    def test_plan_mode_stops_after_plan_review_with_the_plan(self):
        result, calls = run(args=dict(ARGS, mode="plan"))
        self.assertEqual(result["stage"], "planned")
        self.assertEqual(result["plan"]["plan_root"], "/r/.git/worktrees/w/deliver-standard/plan.md")
        self.assertTrue(result["cont"]["plan_reviewed"])
        self.assertEqual(labels(calls)[-1], "plan-review")
        self.assertFalse([c for c in calls if c["agentType"] == "implementer"])

    def test_plan_mode_with_questions_returns_them(self):
        result, _ = run(args=dict(ARGS, mode="plan"),
                        replies={"plan": {"status": "needs_user", "questions": ["q"]}})
        self.assertEqual((result["stage"], result["needs_user"]), ("plan", ["q"]))

    def test_ready_mode_stops_after_verify_with_no_pr(self):
        result, calls = run(args=dict(ARGS, mode="ready"))
        self.assertEqual((result["stage"], result["head"], result["branch"]), ("ready", SHA, "issue-9-x"))
        self.assertEqual(result["verify"], [{"id": "build", "status": "pass", "summary": "ok"}])
        self.assertEqual(result["fix_waves"], 0)
        self.assertEqual(result["acceptance"], PLAN["acceptance"])
        self.assertEqual(result["cont"]["verified"]["head"], SHA)
        self.assertEqual(labels(calls)[-1], "verify")
        for label in ("renew-ship", "pr", "checks-1", "merge", "close-out"):
            self.assertNotIn(label, labels(calls))

    def test_ship_mode_is_the_default(self):
        _, default = run()
        _, ship = run(args=dict(ARGS, mode="ship"))
        self.assertEqual(labels(default), labels(ship))
        self.assertEqual(labels(ship)[-1], "close-out")

    def test_unknown_mode_is_an_args_error(self):
        result, calls = run(args=dict(ARGS, mode="deploy"))
        self.assertEqual(result["stage"], "args")
        self.assertEqual(calls, [])

    def test_plan_then_ready_then_ship_resume_each_stage(self):
        planned, _ = run(args=dict(ARGS, mode="plan"))
        ready, calls = run(args=dict(ARGS, mode="ready", cont=planned["cont"]))
        self.assertEqual(ready["stage"], "ready")
        self.assertNotIn("plan", labels(calls))
        self.assertNotIn("plan-review", labels(calls))
        self.assertIn("rev-parse HEAD", prompt(calls, "setup"))
        done, calls = run(args=dict(ARGS, mode="ship", cont=ready["cont"]), patch={"setup": {"head": SHA}})
        self.assertEqual(done["stage"], "done")
        self.assertEqual(labels(calls), ["setup", "renew-ship", "pr", "renew-checks-1", "checks-1",
                                         "renew-merge", "merge", "close-out"])

    def test_ship_after_ready_reviews_again_when_the_head_moved_or_is_dirty(self):
        ready, _ = run(args=dict(ARGS, mode="ready"))
        for patch in ({"head": "e" * 40}, {"head": SHA, "dirty": True}):
            with self.subTest(patch=patch):
                result, calls = run(args=dict(ARGS, cont=ready["cont"]), patch={"setup": patch})
                if patch.get("dirty"):
                    self.assertEqual(result["stage"], "dirty")
                    continue
                for label in ("final-1", "verify"):
                    self.assertIn(label, labels(calls))


class SourceTest(unittest.TestCase):
    def test_program_avoids_replay_breaking_builtins(self):
        text = PROGRAM.read_text(encoding="utf-8")
        for banned in ("Date.now(", "Math.random(", "new Date()"):
            self.assertNotIn(banned, text)

    def test_meta_is_a_pure_literal_first(self):
        text = PROGRAM.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("export const meta = {"))
        meta = text[:text.index("\n}\n")]
        self.assertIsNone(re.search(r"\$\{|\.\.\.", meta))


if __name__ == "__main__":
    unittest.main()
