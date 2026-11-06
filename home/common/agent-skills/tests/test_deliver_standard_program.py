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
ARGS = {"repo_root": "/r", "issue": 9}
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
            "setup", "claim", "plan", "plan-codex", "plan-review", "impl-1", "review-1", "final-codex",
            "final-1", "verify", "pr", "checks-1", "merge", "close-out"])

    def test_merge_carries_contract_strategy_and_the_checked_head(self):
        # The contract decides the form; a host guard that accepts fewer forms refuses
        # at the merge step, which then stops at stage merge (see the program header).
        head = "b" * 40
        _, calls = run(patch={"setup": {"merge_strategy": "squash", "delete_branch": False,
                                        "unset_env": ["GH_TOKEN"]},
                              "checks-1": {"head": head}})
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
    def test_co_author_trailer_follows_the_contract(self):
        _, on = run()
        self.assertIn("end with the Co-Authored-By trailer", prompt(on, "impl-1"))
        _, off = run(patch={"setup": {"co_authored_by": False}})
        self.assertIn("carry no Co-Authored-By trailer", prompt(off, "impl-1"))
        text = PROGRAM.read_text(encoding="utf-8")
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
        for needle in ("already-merged", "existing-branch", "no-longer-applies",
                       "bindings.vcs.worktree.prefix", "bindings.vcs.worktree.root",
                       "--state all --search 9"):
            self.assertIn(needle, setup)
        self.assertNotIn("--add-label", setup)
        claim = prompt(calls, "claim")
        for needle in ("--add-label in-progress", "worktree add --no-track -b issue-9-x /r/.wt/w-issue-9-x origin/dev",
                       "rev-parse --absolute-git-dir"):
            self.assertIn(needle, claim)

    def test_only_gh_commands_carry_the_credential_prefix(self):
        _, calls = run(patch={"setup": {"unset_env": ["GH_TOKEN"]}})
        text = prompt(calls, "impl-1")
        self.assertIn("unset GH_TOKEN && gh pr create", text)
        self.assertIn("; git -C /r branch -d issue-9-x.", text)
        self.assertIn("git -C /r/.wt/w-issue-9-x push origin issue-9-x;", text)
        self.assertNotIn("&& git", text)

    def test_claim_failure_stops_with_its_result(self):
        result, calls = run(replies={"claim": {"ok": False, "reason": "worktree add failed"}})
        self.assertEqual(result["stage"], "claim")
        self.assertEqual(labels(calls), ["setup", "claim"])

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
        self.assertEqual(names[:3], ["setup", "impl-2", "review-2"])
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

    def test_dirty_resume_of_the_partial_task_continues(self):
        result, _ = run(args=dict(ARGS, cont=self.cont(partial=2)), patch={"setup": {"dirty": True}})
        self.assertEqual(result["stage"], "done")

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
        self.assertEqual([c["agentType"] for c in calls if c["label"] == "verify-fix-review-1"], ["reviewer-lite"])

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
        self.assertEqual(names[names.index("checks-1"):], ["checks-1", "sync-1", "checks-2", "merge", "close-out"])

    def test_conflicted_sync_is_rereviewed(self):
        _, calls = run(replies={"checks-1": {"state": "behind", "head": SHA}},
                       patch={"sync-1": {"conflicted": True, "resolved_files": ["a.py"]}})
        review = [c for c in calls if c["label"] == "sync-review-1"]
        self.assertEqual(review[0]["agentType"], "reviewer-lite")

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

    def test_unmerged_pr_stops_before_close_out(self):
        result, calls = run(replies={"merge": {"merged": False, "notes": "head moved"}})
        self.assertEqual(result["stage"], "merge")
        self.assertNotIn("close-out", labels(calls))


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
