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


OK_LINT = {"ok": True, "errors": []}
EVIDENCE = {"id": "AC2", "text": "deployed", "kind": "evidence",
            "verify": {"ac": "AC2", "kind": "evidence", "host": "h1",
                       "when": {"deployed_includes": SHA}, "run": {"probe": "deployed_includes", "sha": SHA}},
            "lint": OK_LINT}
HUMAN = {"id": "AC3", "text": "looks right", "kind": "human",
         "verify": {"ac": "AC3", "kind": "human", "host": "h1", "when": {"days_after": {"event": "deployed", "days": 1}},
                    "run": {"ask": "Does the page render right on the phone"}, "reason": "senses"},
         "lint": OK_LINT}
RULES_FILE = REPO_ROOT / "home/common/agent-skills/standards/acceptance-planning.md"


def refused(*errors):
    return {"ok": False, "errors": [{"field": f, "code": c, "message": "m"} for f, c in errors]}


def criterion(base, **changes):
    out = json.loads(json.dumps(base))
    for key, value in changes.items():
        if key.startswith("verify_"):
            out["verify"][key[len("verify_"):]] = value
        elif value is None:
            out.pop(key, None)
        else:
            out[key] = value
    return out


def with_criteria(*extra, **top):
    return dict(PLAN, acceptance=PLAN["acceptance"] + list(extra), **top)


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
            "renew-ship", "pr", "renew-checks-1", "checks-1", "renew-merge", "merge", "hold", "close-out"])

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
        plan = dict(PLAN, acceptance=PLAN["acceptance"] + [EVIDENCE])
        result, calls = run(replies={"plan": plan}, patch={"setup": {"integration_branch": "main"},
                                                            "close-out": {"issue_state": "OPEN"}})
        self.assertEqual(result["stage"], "done")
        self.assertIn("Refs #9", prompt(calls, "pr"))
        self.assertEqual(labels(calls)[-3:], ["merge", "hold", "close-out"])
        close = prompt(calls, "close-out")
        self.assertNotIn("gh issue close", close)
        self.assertNotIn("needs-verification", close)
        self.assertIn("needs-verification", prompt(calls, "hold"))


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


class PlanRulesTest(unittest.TestCase):
    """#634 AC1: plan review rejects each acceptance planning rule's violation and accepts a compliant plan."""

    ROWS = (
        ("R1", criterion(EVIDENCE, verify_when={"ci_run_includes": {"workflow": "ci", "branch": "issue-9-x", "sha": SHA}},
                         lint=refused(("checks[0].when", "pre_merge_only")))),
        ("R2", criterion(HUMAN, verify_run={"ask": "Approve the design"},
                         lint=refused(("checks[0].run.ask", "approval_ask")))),
        ("R3", criterion(HUMAN, verify_reason="taste ")),
        ("R3", criterion(HUMAN, lint=refused(("checks[0].reason", "reason_required")))),
        ("R4", criterion(EVIDENCE, verify=None)),
        ("R4", criterion(EVIDENCE, lint=None)),
        ("R4", criterion(EVIDENCE, verify_run={"command": "deploy-now"},
                         lint=refused(("checks[0].run.command", "not_declared")))),
        ("R4", criterion(EVIDENCE, verify_run={"command": "smoke"})),
        ("R4", criterion(EVIDENCE, verify_ac="AC9")),
        ("R5", criterion(EVIDENCE, metric=True)),
        ("R5", dict(PLAN["acceptance"][0], id="AC2", metric=True)),
    )
    RULE_FINDING = {"verdict": "findings",
                    "findings": [{"severity": "important", "rule": "R2", "summary": "s"}]}

    def gate(self, plan):
        return run(replies={"plan": plan, "plan-revise": plan})

    def test_each_rule_violation_stops_at_plan_review_naming_the_rule(self):
        for rule, bad in self.ROWS:
            with self.subTest(rule=rule, ac=bad["id"]):
                result, calls = self.gate(with_criteria(bad))
                self.assertEqual(result["stage"], "plan-review")
                self.assertIn((rule, bad["id"]), [(r["rule"], r["ac"]) for r in result["rules"]])
                self.assertIsNone(result["cont"]["plan"])
                self.assertFalse(result["cont"]["plan_reviewed"])
                self.assertEqual(labels(calls).count("plan-revise"), 1)
                self.assertIn(f'"rule":"{rule}"', prompt(calls, "plan-revise"))
                self.assertNotIn("impl-1", labels(calls))

    def test_pre_merge_only_evidence_stops_at_plan_review_naming_r1(self):
        # The issue's demo: a planner reply with a pre-merge-only evidence criterion.
        result, _ = self.gate(with_criteria(self.ROWS[0][1]))
        self.assertEqual((result["stage"], result["rules"][0]["rule"], result["rules"][0]["ac"]), ("plan-review", "R1", "AC2"))

    def test_compliant_plan_passes_without_a_revision(self):
        metric = criterion(EVIDENCE, id="AC4", metric=True, verify_ac="AC4", verify_mode="observe")
        build = criterion(EVIDENCE, id="AC5", verify_ac="AC5", verify_run={"command": "build"})
        result, calls = run(replies={"plan": with_criteria(EVIDENCE, HUMAN, metric, build)},
                            patch={"close-out": {"issue_state": "OPEN"}})
        self.assertNotIn("plan-revise", labels(calls))
        self.assertNotIn("plan-rules-review", labels(calls))
        self.assertIn("impl-1", labels(calls))
        self.assertNotEqual(result["stage"], "plan-review")

    def test_script_the_plan_commits_is_tolerated_only_when_listed(self):
        script = criterion(EVIDENCE, verify_run={"script": "scripts/check-live"},
                           lint=refused(("checks[0].run.script", "not_committed")))
        _, calls = run(replies={"plan": with_criteria(script, scripts=["scripts/check-live"])},
                       patch={"close-out": {"issue_state": "OPEN"}})
        self.assertNotIn("plan-revise", labels(calls))
        result, _ = self.gate(with_criteria(script))
        self.assertEqual(result["rules"][0]["rule"], "R4")

    def test_a_compliant_revision_proceeds(self):
        bad = with_criteria(self.ROWS[0][1])
        _, calls = run(replies={"plan": bad, "plan-revise": with_criteria(EVIDENCE)},
                       patch={"close-out": {"issue_state": "OPEN"}})
        self.assertEqual(labels(calls).count("plan-revise"), 1)
        self.assertEqual(labels(calls).count("plan-rules-review"), 1)
        self.assertIn("impl-1", labels(calls))

    def test_reviewer_rule_violation_surviving_an_unchanged_revision_stops(self):
        # A violation only a reviewer can see (an approval written as an act run) is re-checked after revision.
        plan = with_criteria(HUMAN)
        result, calls = run(replies={"plan": plan, "plan-revise": plan, "plan-review": self.RULE_FINDING,
                                     "plan-rules-review": self.RULE_FINDING})
        self.assertEqual(result["stage"], "plan-review")
        self.assertEqual([r["rule"] for r in result["rules"]], ["R2"])
        self.assertIsNone(result["cont"]["plan"])
        self.assertNotIn("impl-1", labels(calls))
        self.assertIn('"rule":"R2"', prompt(calls, "plan-rules-review"))
        _, calls = run(replies={"plan": plan, "plan-revise": plan, "plan-review": self.RULE_FINDING},
                       patch={"close-out": {"issue_state": "OPEN"}})
        self.assertIn("impl-1", labels(calls))
        result, _ = run(replies={"plan": plan, "plan-review": self.RULE_FINDING, "plan-rules-review": None})
        self.assertEqual(result["stage"], "plan-review")
        self.assertIsNone(result["cont"]["plan"])

    def test_planner_and_reviewer_prompts_point_to_the_rules(self):
        _, calls = run(replies={"plan-review": self.RULE_FINDING})
        plan = prompt(calls, "plan")
        for needle in ("~/.agents/standards/acceptance-planning.md", "verify-pending lint --input",
                       f"--repo-root /r/.wt/w-issue-9-x --pr-branch issue-9-x", "--pr-workflow",
                       f'"merge": "{SHA}"', "metric", "scripts"):
            self.assertIn(needle, plan)
        for label in ("plan-review", "plan-rules-review"):
            self.assertIn("~/.agents/standards/acceptance-planning.md", prompt(calls, label))

    def test_program_does_not_copy_the_rule_text(self):
        source = PROGRAM.read_text(encoding="utf-8")
        for line in RULES_FILE.read_text(encoding="utf-8").splitlines():
            if line.startswith("- **R"):
                self.assertNotIn(line.split("** ", 1)[1][:40], source)


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
        self.assertEqual(labels(calls), ["setup", "hold", "close-out"])

    def test_resume_after_merge_goes_to_close_out(self):
        result, calls = run(args=dict(ARGS, cont=self.cont()), patch={"setup": {"merged_pr": 42}})
        self.assertEqual(result["stage"], "done")
        self.assertEqual(labels(calls), ["setup", "hold", "close-out"])
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
        self.assertEqual(names[names.index("checks-1"):], ["checks-1", "sync-1", "renew-checks-2", "checks-2", "renew-merge", "merge", "hold", "close-out"])

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


class HoldTest(unittest.TestCase):
    """#634 AC2 and AC3: ship regrades, holds only on a lint-accepted block, runs verify-pending once, splits blocking human rows."""

    MERGE = "d" * 40
    HOLD = {"merge_commit_local": True, "code_unmet": [], "blocks": [], "split": [],
            "block": {"v": 1, "merge": "d" * 40, "checks": []}, "lint": {"ok": True, "errors": []},
            "verify_run": {"ran": True, "exit": 0}, "issue_state": "OPEN", "notes": "n"}
    CHILD = {"ac": "AC3", "issue": 50, "block": {"v": 1, "merge": "d" * 40, "checks": []},
             "lint": {"ok": True, "errors": []}, "verify_run": {"ran": True, "exit": 0}, "issue_state": "OPEN"}

    def ship(self, *criteria, hold=None, close="OPEN", **patch):
        replies = {"plan": with_criteria(*criteria)}
        if hold is not None:
            replies["hold"] = dict(self.HOLD, **hold)
        return run(replies=replies, patch=dict({"merge": {"merge_commit": self.MERGE},
                                                "close-out": {"issue_state": close}}, **patch))

    def test_hold_fetches_lints_posts_and_runs_verify_pending_once(self):
        result, calls = self.ship(EVIDENCE)
        self.assertEqual(result["stage"], "done")
        self.assertEqual(result["hold"]["issue_state"], "OPEN")
        hold = prompt(calls, "hold")
        for needle in ("verify-pending lint --input", "--repo-root /r", f"--pr-head {SHA}", "--pr-branch issue-9-x",
                       "--pr-workflow", "gh pr checks 42 --repo owner/repo --json workflow", "--blocks",
                       "needs-verification", "dependencies/blocking", "~/.agents/standards/acceptance-planning.md",
                       '["build"]', SHA, self.MERGE, '"deployed_includes"', "git -C /r cat-file -e"):
            self.assertIn(needle, hold)
        self.assertLess(hold.index("git -C /r fetch origin"), hold.index("verify-pending lint --input"))
        self.assertEqual(hold.count("verify-pending run --host h1 --repo owner/repo --issue 9"), 1)
        self.assertLess(labels(calls).index("hold"), labels(calls).index("close-out"))

    def test_passing_verify_run_closes_instead_of_holding(self):
        result, _ = self.ship(EVIDENCE, hold={"issue_state": "CLOSED"}, close="CLOSED")
        self.assertEqual(result["stage"], "done")
        self.assertEqual(result["close_out"]["issue_state"], "CLOSED")
        result, _ = self.ship(EVIDENCE, hold={"issue_state": "CLOSED"}, close="OPEN")
        self.assertEqual((result["stage"], result["expected_issue_state"]), ("close-out", "CLOSED"))

    def test_refused_lint_or_failed_run_stops_without_close_out(self):
        for hold in ({"lint": {"ok": False, "errors": [{"code": "unverified_reference"}]}},
                     {"verify_run": {"ran": False, "exit": 0}}, {"verify_run": {"ran": True, "exit": 2}},
                     {"verify_run": {"ran": True, "exit": 1}}, {"issue_state": "MAYBE"},
                     {"merge_commit_local": False}):
            with self.subTest(hold=hold):
                result, calls = self.ship(EVIDENCE, hold=hold)
                self.assertEqual(result["stage"], "hold")
                self.assertNotIn("close-out", labels(calls))
                self.assertIn("cont", result)

    def test_unmet_code_row_stops_without_a_hold(self):
        result, calls = self.ship(EVIDENCE, hold={"code_unmet": ["AC1"]})
        self.assertEqual((result["stage"], result["code_unmet"]), ("code-unmet", ["AC1"]))
        self.assertNotIn("close-out", labels(calls))
        self.assertIn("cont", result)

    def test_all_code_plan_regrades_before_close_out(self):
        result, calls = run()
        self.assertEqual(result["stage"], "done")
        self.assertEqual(labels(calls)[-3:], ["merge", "hold", "close-out"])
        hold = prompt(calls, "hold")
        self.assertIn("git -C /r fetch origin", hold)
        self.assertNotIn("verify-pending run", hold)
        self.assertIn("gh issue close 9", prompt(calls, "close-out"))
        result, calls = run(replies={"hold": dict(self.HOLD, code_unmet=["AC1"])})
        self.assertEqual((result["stage"], result["code_unmet"]), ("code-unmet", ["AC1"]))
        self.assertNotIn("close-out", labels(calls))

    def test_posted_unattended_command_outside_verification_stops(self):
        smoke = {"v": 1, "merge": self.MERGE, "checks": [{"ac": "AC2", "kind": "evidence", "run": {"command": "smoke"}}]}
        result, calls = self.ship(EVIDENCE, hold={"block": smoke})
        self.assertEqual((result["stage"], result["unattended"]), ("hold", ["AC2"]))
        self.assertNotIn("close-out", labels(calls))
        build = {"v": 1, "merge": self.MERGE, "checks": [{"ac": "AC2", "kind": "evidence", "run": {"command": "build"}}]}
        result, _ = self.ship(EVIDENCE, hold={"block": build})
        self.assertEqual(result["stage"], "done")

    def test_blocking_issue_moves_its_human_row_to_a_held_child_issue(self):
        result, _ = self.ship(HUMAN, hold={"blocks": [12], "split": [self.CHILD], "issue_state": "CLOSED",
                                           "lint": None, "verify_run": None, "block": None}, close="CLOSED")
        self.assertEqual(result["stage"], "done")
        self.assertEqual([(s["ac"], s["issue"]) for s in result["hold"]["split"]], [("AC3", 50)])
        result, _ = self.ship(HUMAN, EVIDENCE, hold={"blocks": [12], "split": [self.CHILD]})
        self.assertEqual(result["stage"], "done")

    def test_blocking_issue_without_split_stops(self):
        result, calls = self.ship(HUMAN, hold={"blocks": [12]})
        self.assertEqual((result["stage"], result["missing_split"]), ("hold", ["AC3"]))
        self.assertNotIn("close-out", labels(calls))
        result, _ = self.ship(HUMAN, hold={"blocks": [12], "split": [self.CHILD], "issue_state": "OPEN"})
        self.assertEqual(result["stage"], "hold")

    def test_split_child_without_an_accepted_hold_stops(self):
        for child in ({"lint": {"ok": False, "errors": [{"code": "reason_required"}]}},
                      {"verify_run": {"ran": False, "exit": 0}}, {"verify_run": {"ran": True, "exit": 2}},
                      {"issue_state": "MAYBE"}):
            with self.subTest(child=child):
                result, calls = self.ship(HUMAN, hold={"blocks": [12], "split": [dict(self.CHILD, **child)],
                                                       "issue_state": "CLOSED"}, close="CLOSED")
                self.assertEqual((result["stage"], result["bad_split"]), ("hold", ["AC3"]))
                self.assertNotIn("close-out", labels(calls))

    def test_resume_after_merge_holds_before_close_out(self):
        cont = {"setup": {"ok": True, "worktree": "/r/.wt/w-issue-9-x", "branch": "issue-9-x", "plan_dir": "/g",
                          "holder": HOLDER, "base_sha": SHA},
                "plan": with_criteria(EVIDENCE), "plan_reviewed": True, "done": [{"n": 1, "commit": "c0ffee"}]}
        result, calls = run(args=dict(ARGS, cont=cont), patch={"setup": {"merged_pr": 42},
                                                               "close-out": {"issue_state": "OPEN"}})
        self.assertEqual(result["stage"], "done")
        self.assertEqual(labels(calls), ["setup", "hold", "close-out"])
        hold = prompt(calls, "hold")
        self.assertIn("gh pr view 42 --repo owner/repo --json mergeCommit,headRefOid", hold)
        self.assertLess(hold.index("git -C /r fetch origin"), hold.index("verify-pending lint --input"))


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
                                         "renew-merge", "merge", "hold", "close-out"])

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

    def test_cached_verification_is_reused_only_for_the_same_contract(self):
        """COR-001: the cache is keyed by the freshly resolved verification contract, not the head alone."""
        build = {"id": "build", "argv": ["make", "build"], "cwd": "."}
        lint = {"id": "lint", "argv": ["make", "lint"], "cwd": "."}
        ready, _ = run(args=dict(ARGS, mode="ready"))
        reordered = {"cwd": ".", "argv": ["make", "build"], "id": "build"}
        same, calls = run(args=dict(ARGS, cont=ready["cont"]),
                          patch={"setup": {"head": SHA, "verification": [reordered]}})
        self.assertEqual(same["stage"], "done")
        self.assertNotIn("verify", labels(calls))
        added_results = [{"id": "build", "status": "pass", "summary": "ok"},
                         {"id": "lint", "status": "pass", "summary": "ok"}]
        changes = {
            "added command": ([build, lint], added_results),
            "changed argv": ([dict(build, argv=["make", "build", "-j"])], None),
            "changed cwd": ([dict(build, cwd="sub")], None),
        }
        for name, (verification, results) in changes.items():
            with self.subTest(change=name):
                reply = {"head": SHA, "clean": True,
                         "results": results or [{"id": "build", "status": "pass", "summary": "ok"}]}
                result, calls = run(args=dict(ARGS, cont=ready["cont"]),
                                    patch={"setup": {"head": SHA, "verification": verification}, "verify": reply})
                self.assertEqual(result["stage"], "done")
                self.assertIn("verify", labels(calls))
                self.assertNotIn("final-1", labels(calls))
                self.assertIn(json.dumps(verification, separators=(",", ":")), prompt(calls, "verify"))


DIRECT = dict(ARGS, lane="direct")
BAD = {"verdict": "findings", "findings": [{"severity": "important", "summary": "bug"}]}


class DirectLaneTest(unittest.TestCase):
    """#635: setup, one implementer on deliver-direct's steps, one fresh reviewer, at most one fix round."""

    def test_direct_lane_runs_one_implementer_one_fresh_reviewer_and_no_planner(self):
        result, calls = run(args=DIRECT)
        self.assertEqual(result["stage"], "done")
        names = labels(calls)
        self.assertFalse([l for l in names if l.startswith("plan") or l == "renew-plan"], names)
        self.assertEqual([c["label"] for c in calls if c["agentType"] == "implementer"], ["direct-impl"])
        reviewers = [c for c in calls if c["agentType"] in ("reviewer", "reviewer-lite")]
        self.assertEqual([(c["label"], c["agentType"]) for c in reviewers], [("direct-review", "reviewer-lite")])
        self.assertIn("lane: direct.", reviewers[0]["prompt"])
        self.assertIn("direct-codex", names)
        self.assertNotIn("final-1", names)
        self.assertEqual(names[names.index("direct-impl") - 1], "renew-tasks")
        self.assertIn("renew-final-review", names[:names.index("direct-review")])
        self.assertIn("direct-lane review", prompt(calls, "pr"))

    def test_direct_lane_in_ready_mode_returns_a_reviewed_head(self):
        result, calls = run(args=dict(DIRECT, mode="ready"))
        self.assertEqual((result["stage"], result["head"]), ("ready", SHA))
        self.assertEqual(result["cont"]["lane"], "direct")
        self.assertNotIn("pr", labels(calls))

    def test_direct_implementer_follows_deliver_direct_steps(self):
        _, calls = run(args=DIRECT)
        impl = prompt(calls, "direct-impl")
        for needle in ("deliver-direct skill", "Skill tool", "Eligibility", "step 3", "steps 4 to 7",
                       "/r/.wt/w-issue-9-x", "h1/session-s1"):
            self.assertIn(needle, impl)

    def test_sensitive_diff_gets_the_full_reviewer(self):
        _, calls = run(args=DIRECT, patch={"direct-impl": {"sensitive": True}})
        review = [c for c in calls if c["label"] == "direct-review"][0]
        self.assertEqual(review["agentType"], "reviewer")
        self.assertNotIn("lane: direct", review["prompt"])

    def test_reviewer_lite_escalation_hands_the_review_to_the_full_reviewer(self):
        result, calls = run(args=DIRECT, replies={"direct-review": {"verdict": "pass", "findings": [], "escalate": True}})
        self.assertEqual(result["stage"], "done")
        self.assertEqual([c["agentType"] for c in calls if c["label"] == "direct-review-full"], ["reviewer"])

    def test_at_most_one_fix_round(self):
        result, calls = run(args=DIRECT, replies={"direct-review": BAD, "direct-rereview": BAD})
        self.assertEqual(result["stage"], "direct-review")
        self.assertEqual(labels(calls).count("direct-fix"), 1)
        self.assertNotIn("verify", labels(calls))
        rereview = [c for c in calls if c["label"] == "direct-rereview"][0]
        self.assertEqual(rereview["agentType"], "reviewer-lite")
        self.assertIn("bug", rereview["prompt"])

    def test_one_fix_round_that_resolves_continues(self):
        result, _ = run(args=DIRECT, replies={"direct-review": BAD})
        self.assertEqual(result["stage"], "done")

    def test_failed_fix_stops(self):
        result, _ = run(args=DIRECT, replies={"direct-review": BAD, "direct-fix": {"status": "blocked", "notes": "no"}})
        self.assertEqual(result["stage"], "direct-fix")

    def test_codex_finding_enters_the_fix_round(self):
        codex = {"available": True, "verdict": "findings", "findings": [{"severity": "important", "summary": "edge"}]}
        _, calls = run(args=DIRECT, replies={"direct-codex": codex})
        self.assertIn("edge", prompt(calls, "direct-fix"))

    def test_codex_unavailable_stops(self):
        result, _ = run(args=DIRECT, replies={"direct-codex": {"available": False, "verdict": "pass", "findings": []}})
        self.assertEqual((result["stage"], result["step"]), ("codex-unavailable", "code"))

    def test_lane_and_mode_are_checked_before_any_agent(self):
        for args in (dict(DIRECT, mode="plan"), dict(ARGS, lane="fast")):
            with self.subTest(args=args):
                result, calls = run(args=args)
                self.assertEqual(result["stage"], "args")
                self.assertEqual(calls, [])

    def test_ineligible_issue_stops_before_review(self):
        result, calls = run(args=DIRECT, replies={"direct-impl": {"status": "blocked", "ineligible": True, "notes": "needs design"}})
        self.assertEqual(result["stage"], "ineligible")
        self.assertNotIn("direct-review", labels(calls))

    def test_missing_acceptance_stops(self):
        result, calls = run(args=DIRECT, patch={"direct-impl": {"acceptance": []}})
        self.assertEqual(result["stage"], "task")
        self.assertNotIn("direct-review", labels(calls))

    def test_close_out_grades_the_implementer_criteria(self):
        acceptance = [{"id": "AC1", "text": "x", "kind": "code"}, {"id": "AC2", "text": "y", "kind": "evidence"}]
        _, calls = run(args=DIRECT, patch={"direct-impl": {"acceptance": acceptance},
                                           "close-out": {"issue_state": "OPEN"}})
        self.assertIn("needs-verification", prompt(calls, "hold"))

    def test_resume_after_the_review_skips_to_verify(self):
        stopped, _ = run(args=DIRECT, replies={"verify": None})
        self.assertEqual((stopped["stage"], stopped["cont"]["lane"]), ("verify", "direct"))
        self.assertEqual(stopped["cont"]["done"][0]["reviewed_head"], "c0ffee")
        result, calls = run(args=dict(ARGS, cont=stopped["cont"]), patch={"setup": {"head": "c0ffee"}})
        names = labels(calls)
        self.assertEqual(result["stage"], "done")
        self.assertNotIn("direct-impl", names)
        self.assertNotIn("direct-review", names)
        self.assertNotIn("plan", names)
        self.assertIn("verify", names)

    def test_resume_on_a_moved_head_reviews_again(self):
        stopped, _ = run(args=DIRECT, replies={"verify": None})
        ready, _ = run(args=dict(DIRECT, mode="ready"))
        for cont in (stopped["cont"], ready["cont"]):
            with self.subTest(stage=cont.get("verified") and "ready" or "verify"):
                result, calls = run(args=dict(ARGS, cont=cont), patch={"setup": {"head": "e" * 40}})
                names = labels(calls)
                self.assertEqual(result["stage"], "done")
                self.assertNotIn("direct-impl", names)
                for label in ("renew-final-review", "direct-codex", "direct-review", "verify", "pr", "merge"):
                    self.assertIn(label, names)
                self.assertLess(names.index("direct-review"), names.index("verify"))

    def test_ship_after_a_direct_ready_on_the_same_head_skips_review_and_verify(self):
        ready, _ = run(args=dict(DIRECT, mode="ready"))
        result, calls = run(args=dict(ARGS, cont=ready["cont"]), patch={"setup": {"head": SHA}})
        self.assertEqual(result["stage"], "done")
        self.assertEqual(labels(calls), ["setup", "renew-ship", "pr", "renew-checks-1", "checks-1",
                                         "renew-merge", "merge", "hold", "close-out"])

    def test_a_review_stop_resumes_into_the_review_not_the_implementer(self):
        stopped, _ = run(args=DIRECT, replies={"direct-review": None})
        self.assertEqual(stopped["stage"], "direct-review")
        self.assertIsNone(stopped["cont"]["done"][0]["reviewed_head"])
        result, calls = run(args=dict(ARGS, cont=stopped["cont"]), patch={"setup": {"head": "c0ffee"}})
        self.assertEqual(result["stage"], "done")
        self.assertNotIn("direct-impl", labels(calls))
        self.assertIn("direct-review", labels(calls))

    def test_claim_failures_keep_the_lane(self):
        failures = {"acquire": {"verdict": "error", "detail": "forge down"},
                    "worktree": {"ok": False, "notes": "worktree add failed"}}
        for lane in ("standard", "direct"):
            for label, reply in failures.items():
                with self.subTest(lane=lane, label=label):
                    stopped, _ = run(args=dict(ARGS, lane=lane), replies={label: reply})
                    self.assertEqual(stopped["stage"], "claim")
                    self.assertEqual(stopped["cont"]["lane"], lane)
                    for args in (dict(ARGS, cont=stopped["cont"]), dict(ARGS, lane=lane, cont=stopped["cont"])):
                        result, calls = run(args=args)
                        self.assertEqual(result["stage"], "done")
                        self.assertEqual("direct-impl" in labels(calls), lane == "direct")
                        self.assertEqual("plan" in labels(calls), lane == "standard")

    def test_resume_cannot_switch_lane(self):
        stopped, _ = run(args=DIRECT, replies={"verify": None})
        result, calls = run(args=dict(ARGS, lane="standard", cont=stopped["cont"]))
        self.assertEqual(result["stage"], "args")
        self.assertEqual(calls, [])


class DeadAgentTest(unittest.TestCase):
    """deliver-batch (#636 D12) reads dead_agents to tell an agent that returned nothing from a stop."""

    def test_each_dead_agent_shape_names_its_label(self):
        for label, stage in (("setup", "setup"), ("plan-review", "plan-review"), ("review-1", "task-review"),
                             ("final-1", "final-review"), ("verify", "verify")):
            with self.subTest(label=label):
                result, _ = run(replies={label: None})
                self.assertEqual(result["stage"], stage)
                self.assertEqual(result["dead_agents"], [label])

    def test_a_live_run_and_an_ordinary_stop_carry_no_dead_agents(self):
        result, _ = run()
        self.assertEqual(result["stage"], "done")
        self.assertNotIn("dead_agents", result)
        result, _ = run(replies={"plan": {"status": "needs_user", "questions": ["q"]}})
        self.assertEqual(result["stage"], "plan")
        self.assertNotIn("dead_agents", result)


class SourceTest(unittest.TestCase):
    def test_program_avoids_replay_breaking_builtins(self):
        text = PROGRAM.read_text(encoding="utf-8")
        for banned in ("Date.now(", "Math.random(", "new Date()"):
            self.assertNotIn(banned, text)

    def test_every_agent_call_goes_through_the_dead_agent_wrapper(self):
        text = PROGRAM.read_text(encoding="utf-8")
        self.assertEqual(len(re.findall(r"\bagent\(", text)), 1)

    def test_meta_is_a_pure_literal_first(self):
        text = PROGRAM.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("export const meta = {"))
        meta = text[:text.index("\n}\n")]
        self.assertIsNone(re.search(r"\$\{|\.\.\.", meta))

    def test_skill_frontmatter_args_and_size(self):
        raw = PROGRAM.with_name("SKILL.md").read_bytes()
        self.assertLessEqual(len(raw), 1056)
        text = raw.decode("utf-8")
        self.assertTrue(text.startswith(
            "---\nname: deliver-standard\n"
            "description: Runs the standard-lane Workflow program for one issue. Use for deliver-standard.\n---\n"))
        start = text.index("`args` `{")
        workflow_args = text[start:text.index("}`", start)]
        for key in ("repo_root", "issue", "session_id: ${CLAUDE_SESSION_ID}", "batch_id?", "mode?", "lane?",
                    "decisions?", "spec?"):
            with self.subTest(key=key):
                self.assertIn(key, workflow_args)

    def test_meta_names_the_new_args(self):
        text = PROGRAM.read_text(encoding="utf-8")
        meta = text[:text.index("\n}\n")]
        for arg in ("session_id", "batch_id", "mode?", "lane?"):
            self.assertIn(arg, meta)


if __name__ == "__main__":
    unittest.main()
