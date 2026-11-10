"""deliver-standard.js control flow against stub agents (#618, #572 S1).

The Workflow program runs under node with stub agent(), parallel() and phase();
each scenario fixes some agents' replies and asserts the stop or the call sequence.
Run: just agent-workflow-tests
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

REPO_ROOT = Path(__file__).parents[4]
PROGRAM = REPO_ROOT / "home/common/claude-code/skills/deliver-standard/deliver-standard.js"
HARNESS = Path(__file__).with_name("deliver_standard_harness.mjs")
SHA = "a" * 40
ISSUE_BRANCH_ARGV = re.compile(r"\bissue-branch --repo-root (\S+) --issue (\d+)\b")
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
NOTE = {"id": "AC4", "text": "the next session's first-turn prompt reads under 30k tokens", "kind": "note"}
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


PROGRAM_AGENT_TYPES = {"clerk", "planner", "implementer", "reviewer", "reviewer-lite"}


def untyped(calls):
    """Labels of agent calls that would run on the default tool set (#734)."""
    return [c["label"] for c in calls
            if c.get("kind", "agent") == "agent" and c["agentType"] not in PROGRAM_AGENT_TYPES]


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
    bad = untyped(out["calls"])
    if bad:
        raise AssertionError(f"agent calls without a program agentType: {bad}")
    return out["result"], out["calls"]


def labels(calls):
    return [c["label"] for c in calls]


def merged(pr, *commits):
    """A resume setup reply naming merged PR `pr` on the branch, with its commit oids."""
    return {"merged_pr": pr, "merged_heads": [{"number": pr, "commits": list(commits)}]}


def prompt(calls, label):
    found = [c["prompt"] for c in calls if c["label"] == label]
    if not found:
        raise AssertionError(f"no call labelled {label}: {labels(calls)}")
    return found[-1]


def schema_of(calls, label):
    found = [c["schema"] for c in calls if c["label"] == label]
    if not found:
        raise AssertionError(f"no call labelled {label}: {labels(calls)}")
    return found[-1]


def object_branch(schema):
    """A nested schema, read through the object branch of a nullable anyOf."""
    if "anyOf" in schema:
        found = [s for s in schema["anyOf"] if s.get("type") == "object"]
        if len(found) != 1:
            raise AssertionError(f"no single object branch: {schema}")
        return found[0]
    return schema


RENEW_READ = {"verdict", "by", "detail", "transient"}
# label: (top-level fields the program or a later prompt reads, {member: fields read inside it}); a member
# named "<name>[]" is an array whose items object is checked.
FOLDED_READ = {
    "verify": ({"head", "clean", "results"}, {"renew": RENEW_READ, "results[]": {"id", "status", "summary"}}),
    "pr": ({"pr", "head"}, {"renew": RENEW_READ, "lock": {"verdict"}}),
    "checks-1": ({"state", "head", "failing", "details", "pending"}, {"renew": RENEW_READ}),
    "merge": ({"merged", "behind", "merge_commit", "notes"}, {"renew": RENEW_READ, "lock": {"verdict"}}),
    "impl-1": ({"status", "start_head", "commit", "notes"}, {"renew": RENEW_READ}),
    "setup": ({"ok", "reason", "details", "host", "slug", "integration_branch", "default_branch", "branch",
               "worktree_path", "head", "merged_pr", "merged_refs", "merged_heads", "dirty", "duplicate_pr", "since_reviewed", "branch_heads",
               "existing", "unset_env", "merge_strategy", "delete_branch", "review", "review_state", "knowledge",
               "verification", "holder", "acquire", "claim", "answer", "renew"},
              {"existing": {"local_branch", "remote_branch", "worktree", "dirty", "status"},
               "merged_refs[]": {"number", "closes"}, "merged_heads[]": {"number", "commits"},
               "review": {"code", "plan"}, "review_state": {"code", "plan"},
               "knowledge": {"standards", "hints", "rejections"},
               "verification[]": {"id", "argv", "cwd", "when_changed", "skip_reason"},
               "acquire": {"verdict", "by", "detail", "transient"}, "claim": {"ok", "reason", "worktree", "base_sha", "plan_dir"},
               "answer": {"verdict", "comment_id", "questions", "decisions"}, "renew": RENEW_READ}),
}


def member(schema, name):
    """The object schema of a member: an array member's items, a nullable member's object branch."""
    if name.endswith("[]"):
        return schema["properties"][name[:-2]]["items"]
    return object_branch(schema["properties"][name])


class FoldTest(unittest.TestCase):
    """#716: folded bookkeeping steps return nested results that keep every field the program reads."""

    def test_folded_schemas_keep_every_read_field(self):
        _, calls = run()
        renew = member(schema_of(calls, "verify"), "renew")
        merge = "d" * 40
        _, moved_calls = run(replies={"checks-1": {"state": "behind", "head": SHA},
                                      "checks-2": {"state": "passed", "head": merge}},
                             patch={"sync-1": {"merge_commit": merge}})
        lock = schema_of(moved_calls, "land-lock-2")
        for label, (top, nested) in FOLDED_READ.items():
            with self.subTest(label=label):
                schema = schema_of(calls, label)
                self.assertLessEqual(top, set(schema["properties"]))
                for name, fields in nested.items():
                    branch = member(schema, name)
                    folded = label == "setup" and name in ("answer", "renew")
                    if name in ("acquire", "claim", "lock") or folded:
                        self.assertIn({"type": "null"}, schema["properties"][name]["anyOf"])
                    self.assertLessEqual(fields, set(branch["properties"]), name)
                    if name == "renew":
                        self.assertEqual(branch, renew)
                        if folded:
                            self.assertNotIn("renew", schema.get("required", []))
                        else:
                            self.assertEqual(schema["required"], ["renew"])
                    if folded:
                        self.assertNotIn(name, schema.get("required", []))
                    if name == "lock":
                        self.assertEqual(branch, lock)
        with self.subTest(label="owner-answer"):
            _, resumed = run(args=dict(ARGS, cont=RESUME_FOR_ANSWER))
            schema = schema_of(resumed, "owner-answer")
            self.assertLessEqual({"verdict", "decisions", "comment_id", "questions"}, set(schema["properties"]))
            self.assertEqual(schema["properties"]["renew"], renew)
            self.assertEqual(schema["required"], ["renew"])

    def test_gate_failure_after_a_folded_claim_keeps_a_claim_incomplete_cont(self):
        # gate: (setup patch, stage, the resume re-derives the location)
        cases = {
            "ok-false": ({"ok": False, "reason": "worktree add failed"}, "setup", False),
            "missing": ({"merge_strategy": None}, "setup", False),
            "missing-branch": ({"branch": None}, "setup", True),
            "missing-worktree-path": ({"worktree_path": None}, "setup", True),
            "holder": ({"holder": "h2/session-s1"}, "setup", False),
            "review-blocked": ({"review_state": {"code": "blocked", "plan": "available"}}, "review-blocked", False),
        }
        for gate, (patch, stage, rederive) in cases.items():
            with self.subTest(gate=gate):
                result, calls = run(patch={"setup": patch})
                self.assertEqual(result["stage"], stage)
                self.assertEqual(labels(calls), ["setup"])
                cont = result["cont"]
                self.assertTrue(cont["claim_incomplete"])
                self.assertEqual(cont["setup"]["holder"], HOLDER)
                for nested in ("acquire", "claim", "answer", "renew"):
                    self.assertNotIn(nested, cont["setup"])
                resumed, calls = run(args=dict(ARGS, cont=cont))
                self.assertEqual(resumed["stage"], "done")
                self.assertEqual(labels(calls)[:3], ["setup", "acquire", "worktree"])
                self.assertEqual(bool(ISSUE_BRANCH_ARGV.search(prompt(calls, "setup"))), rederive)
                self.assertIn("--branch issue-9-x", prompt(calls, "acquire"))
                self.assertIn("/r/.wt/w-issue-9-x", prompt(calls, "worktree"))
        # No claim taken: a refusal still stops with no cont.
        result, calls = run(patch={"setup": {"ok": False, "reason": "closed", "acquire": None, "claim": None}})
        self.assertEqual(result["stage"], "setup")
        self.assertNotIn("cont", result)

    def test_folded_pr_lock_is_released_on_head_moved(self):
        moved = "c" * 40
        result, calls = run(patch={"pr": {"head": moved}})
        self.assertEqual(result["stage"], "head-moved")
        names = labels(calls)
        self.assertEqual(names[names.index("pr"):], ["pr", "land-unlock"])
        self.assertIn(f"forge-claim land release --repo owner/repo --branch dev --sha {SHA}\n",
                      prompt(calls, "land-unlock"))
        self.assertNotIn("lock_unreleased", result)
        self.assertIn(f"forge-claim land acquire --repo owner/repo --branch dev --sha {SHA} --wait\n",
                      prompt(calls, "pr"))
        # A non-holding verdict leaves nothing to release, even on a head-moved stop.
        result, calls = run(patch={"pr": {"head": moved, "lock": {"verdict": "held_by", "by": "h2/b9"}}})
        self.assertEqual(result["stage"], "head-moved")
        self.assertNotIn("land-unlock", labels(calls))

    def test_a_lost_folded_lock_reply_still_releases_the_lock(self):
        release = f"forge-claim land release --repo owner/repo --branch dev --sha {SHA}\n"
        for reply in (None, "throw"):
            for label in ("pr", "merge"):
                with self.subTest(label=label, reply=reply):
                    result, calls = run(replies={label: reply})
                    names = labels(calls)
                    self.assertEqual(names[names.index(label):], [label, "land-unlock"])
                    self.assertIn(release, prompt(calls, "land-unlock"))
                    self.assertNotIn("When it prints not_held", prompt(calls, "land-unlock"))
                    if reply is None:
                        self.assertEqual(result["stage"], label)
                    else:
                        self.assertIsNone(result)
        # A move lock that never answered: the release tries the old sha, then the move target.
        merge = "d" * 40
        moved = {"replies": {"checks-1": {"state": "behind", "head": SHA}}, "patch": {"sync-1": {"merge_commit": merge}}}
        for reply in (None, "throw", {"verdict": "error", "detail": "gh failed"}):
            with self.subTest(move=reply):
                _, calls = run(replies=dict(moved["replies"], **{"land-lock-2": reply}), patch=moved["patch"])
                text = prompt(calls, "land-unlock")
                self.assertIn(release, text)
                self.assertIn(f"When it prints not_held with lock_sha {merge}, run alone and exactly: "
                              f"forge-claim land release --repo owner/repo --branch dev --sha {merge}", text)
                self.assertEqual(labels(calls).count("land-unlock"), 1)
        # A definitive answer: a move refused by another holder leaves only the old sha to release.
        _, calls = run(replies=dict(moved["replies"], **{"land-lock-2": {"verdict": "lost_to", "lock_sha": "c" * 40}}),
                       patch=moved["patch"])
        self.assertIn(release, prompt(calls, "land-unlock"))
        self.assertNotIn("When it prints not_held", prompt(calls, "land-unlock"))
        # A pr whose renew ended ran no lock command: nothing to release.
        _, calls = run(patch={"pr": {"renew": {"verdict": "not_held", "by": "h2/b1"}}})
        self.assertNotIn("land-unlock", labels(calls))

    def test_merge_skips_on_a_retaken_lock(self):
        retaken = {"merged": False, "notes": "the lock was retaken (acquired); not merged",
                   "lock": {"verdict": "acquired", "lock_sha": SHA}}
        merged = {"merged": True, "merge_commit": SHA, "notes": "merged",
                  "lock": {"verdict": "already_held", "lock_sha": SHA}}
        result, calls = run(replies={"merge": [retaken, merged]})
        self.assertEqual(result["stage"], "done")
        names = labels(calls)
        self.assertEqual(names[names.index("checks-1"):],
                         ["checks-1", "merge", "checks-2", "merge", "land-unlock", "hold", "close-out"])
        text = prompt(calls, "merge")
        self.assertIn("Only when lock's verdict is already_held or moved", text)
        self.assertLess(text.index(f"forge-claim land acquire --repo owner/repo --branch dev --sha {SHA}\n"),
                        text.index("gh pr merge 42"))
        self.assertNotIn(" --wait\n", text)
        result, calls = run(replies={"merge": [retaken, retaken]})
        self.assertEqual(result["stage"], "land-contended")
        self.assertEqual(labels(calls).count("land-unlock"), 1)

    def test_fresh_setup_claims_after_its_reads_and_before_the_worktree(self):
        _, calls = run()
        text = prompt(calls, "setup")
        acquire = "forge-claim acquire --repo <slug> --issue 9 --holder <host>/session-s1 --branch <branch>"
        self.assertIn(acquire, text)
        self.assertLess(text.index("no-longer-applies"), text.index(acquire))
        self.assertLess(text.index(acquire), text.index("worktree add --no-track -b <branch> <worktree_path> origin/<integration_branch>"))
        self.assertIn("keep ok true", text)
        for needle in ("worktree add <worktree_path> <branch>", "worktree add --no-track -b <branch> <worktree_path> origin/<branch>",
                       "rev-parse --absolute-git-dir", "skip a step already done"):
            self.assertIn(needle, text)
        _, calls = run(args={"repo_root": "/r", "issue": 9, "batch_id": "b7"})
        self.assertIn("--holder <host>/b7 ", prompt(calls, "setup"))

    def test_a_kept_unreviewed_plan_renews_alone(self):
        cont = {"setup": {"ok": True, "worktree": "/r/.wt/w-issue-9-x", "branch": "issue-9-x", "plan_dir": "/g",
                          "holder": HOLDER, "base_sha": SHA},
                "plan": PLAN, "plan_reviewed": False, "done": []}
        result, calls = run(args=dict(ARGS, cont=cont))
        self.assertEqual(result["stage"], "done")
        names = labels(calls)
        self.assertNotIn("owner-answer", names)
        self.assertLess(names.index("renew-plan"), names.index("plan-review"))


CHILD_HAPPY = ["setup", "plan", "plan-codex", "plan-review", "impl-1", "review-1",
               "renew-final-review", "final-codex", "final-1", "verify", "pr", "checks-1", "merge",
               "land-unlock", "hold", "close-out"]


class FoldedTaskRenewTest(unittest.TestCase):
    """#745: the first implementer call of a run renews the claim first; its renew is graded before any task field."""

    def test_only_the_first_implementer_of_a_run_renews(self):
        _, calls = run(replies={"plan": dict(PLAN, tasks=tasks(2))})
        self.assertNotIn("renew-tasks", labels(calls))
        first = prompt(calls, "impl-1")
        self.assertLess(first.index(RENEW), first.index("/g/task-1.md"))
        self.assertEqual(schema_of(calls, "impl-1")["required"], ["renew"])
        self.assertEqual(next(c for c in calls if c["label"] == "impl-1")["agentType"], "implementer")
        self.assertNotIn(RENEW, prompt(calls, "impl-2"))
        self.assertNotIn("renew", schema_of(calls, "impl-2")["properties"])

    def test_a_lost_renew_inside_impl_1_stops_before_any_task_result_is_used(self):
        done = {"status": "done", "start_head": "b0", "commit": "c0ffee", "tests": ["t"], "notes": "ok"}
        for renew in ({"verdict": "not_held", "by": "h2/b1"}, {"verdict": "error", "detail": "forge down"}, None):
            with self.subTest(renew=renew):
                result, calls = run(replies={"impl-1": dict(done, renew=renew)})
                self.assertEqual((result["stage"], result["at"]), ("claim-lost", "tasks"))
                self.assertNotIn("review-1", labels(calls))
                if renew and renew["verdict"] == "not_held":
                    self.assertNotIn("cont", result)
                else:
                    self.assertTrue(result["cont"]["claim_incomplete"])
                    self.assertEqual(result["cont"]["done"], [])
                    self.assertNotIn("partial", result["cont"])

    def test_direct_impl_renews_first_and_a_lost_renew_stops_before_its_result(self):
        _, calls = run(args=DIRECT)
        self.assertNotIn("renew-tasks", labels(calls))
        text = prompt(calls, "direct-impl")
        self.assertLess(text.index(RENEW), text.index("deliver-direct"))
        self.assertEqual(schema_of(calls, "direct-impl")["required"], ["renew"])
        result, calls = run(args=DIRECT, patch={"direct-impl": {"renew": {"verdict": "not_held", "by": "h2/b1"},
                                                                "ineligible": True}})
        self.assertEqual((result["stage"], result["at"]), ("claim-lost", "tasks"))
        self.assertNotIn("direct-review", labels(calls))


class FinalRenewStaysOutOfTheReviewersTest(unittest.TestCase):
    """#745: the renew is a mutating forge-claim command, so it never rides in a reviewer-profile call (read-only Bash)."""

    def test_the_final_review_renews_in_its_own_clerk_step_before_every_final_reviewer(self):
        _, calls = run(replies={"plan": dict(PLAN, tasks=tasks(4))})
        names = labels(calls)
        renew = next(c for c in calls if c["label"] == "renew-final-review")
        self.assertEqual(renew["agentType"], "clerk")
        self.assertLess(names.index("renew-final-review"), names.index("final-1"))
        self.assertLess(names.index("renew-final-review"), names.index("final-codex"))
        self.assertEqual(names.count("renew-final-review"), 1)

    def test_no_reviewer_call_is_asked_to_renew_the_claim(self):
        _, calls = run(replies={"plan": dict(PLAN, tasks=tasks(4))})
        reviewers = [c for c in calls if c["agentType"] in ("reviewer", "reviewer-lite")]
        self.assertTrue(any(c["label"] == "final-1" for c in reviewers))
        for c in reviewers:
            with self.subTest(label=c["label"]):
                self.assertNotIn("forge-claim renew", c["prompt"])
                self.assertNotIn("renew", c["schema"]["properties"])


# The bookkeeping agents of one fresh standard issue's happy path at e0c0656d (issue 745 baseline): setup,
# owner-answer, renew-tasks, renew-final-review, land-unlock and close-out.
BOOKKEEPING = re.compile(r"^(setup|acquire|worktree|renew|owner-answer|land-lock|land-unlock|close-out)(-|$)")
BOOKKEEPING_BASELINE = 6


class StandardBookkeepingCountTest(unittest.TestCase):
    def test_a_standard_issue_runs_at_least_two_fewer_bookkeeping_agents(self):
        # Standalone (acquired), and as a batch child whose folded acquire answers already_held (D1, D6).
        for kw in ({}, {"args": BATCH_CHILD, "patch": {"setup": {"acquire": HELD}}}):
            with self.subTest(kw=kw):
                result, calls = run(**kw)
                self.assertEqual(result["stage"], "done")
                book = [l for l in labels(calls) if BOOKKEEPING.match(l)]
                self.assertLessEqual(len(book), BOOKKEEPING_BASELINE - 2, book)


class IssueBranchStepTest(unittest.TestCase):
    """#748: the setup takes branch and worktree_path from issue-branch, fresh or re-deriving."""

    def test_the_fresh_setup_runs_issue_branch_once(self):
        _, calls = run()
        self.assertEqual(ISSUE_BRANCH_ARGV.findall(prompt(calls, "setup")), [("/r", "9")])

    def test_only_a_resume_that_lacks_its_location_runs_it(self):
        first, _ = run(patch={"setup": {"branch": None}})
        _, calls = run(args=dict(ARGS, cont=first["cont"]))
        self.assertEqual(ISSUE_BRANCH_ARGV.findall(prompt(calls, "setup")), [("/r", "9")])
        kept, _ = run(patch={"setup": {"merge_strategy": None}})
        _, calls = run(args=dict(ARGS, cont=kept["cont"]))
        self.assertEqual(ISSUE_BRANCH_ARGV.findall(prompt(calls, "setup")), [])


class HappyPathTest(unittest.TestCase):
    def test_one_task_runs_every_stage_in_order(self):
        result, calls = run()
        self.assertEqual(result["stage"], "done")
        self.assertTrue(result["merged"])
        self.assertEqual(labels(calls), CHILD_HAPPY)
        self.assertLessEqual(len(labels(calls)), 19)

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
        self.assertEqual(labels(calls)[-3:], ["land-unlock", "hold", "close-out"])
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
        for needle in ("duplicate", "re-adopt", "no-longer-applies", "--state all --search 9"):
            self.assertIn(needle, setup)
        self.assertNotIn("--add-label", setup)
        for needle in ("worktree add --no-track -b <branch> <worktree_path> origin/<integration_branch>",
                       "rev-parse --absolute-git-dir"):
            self.assertIn(needle, setup)

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
                result, calls = run(patch={"setup": {"claim": reply}})
                self.assertEqual(result["stage"], "claim")
                self.assertEqual(labels(calls), ["setup"])
                cont = result["cont"]
                self.assertTrue(cont["claim_incomplete"])
                result, calls = run(args=dict(ARGS, cont=cont))
                self.assertEqual(result["stage"], "done")
                self.assertEqual(labels(calls)[:5], ["setup", "acquire", "worktree", "owner-answer", "plan"])
                self.assertIn("skip a step already done", prompt(calls, "worktree"))
                self.assertIn("an earlier claim stopped part way", prompt(calls, "setup"))
                self.assertIn("worktree add --no-track -b issue-9-x /r/.wt/w-issue-9-x", prompt(calls, "worktree"))

    def test_a_lost_fresh_setup_reply_carries_no_cont(self):
        # A cont would resume past the fresh refusal checks (parked, duplicate, open-pr, no-longer-applies) that the lost
        # reply never showed passing: the stop carries none, and a rerun does the full fresh setup (the acquire is idempotent
        # for the same holder).
        result, calls = run(replies={"setup": None})
        self.assertEqual(result["stage"], "setup")
        self.assertIsNone(result["result"])
        self.assertEqual(result["dead_agents"], ["setup"])
        self.assertNotIn("cont", result)
        self.assertEqual(labels(calls), ["setup"])
        rerun, calls = run()
        self.assertEqual(rerun["stage"], "done")
        self.assertIn("Refuse (ok=false) with reason closed, parked", prompt(calls, "setup"))
        self.assertIn("--holder <host>/session-s1", prompt(calls, "setup"))

    def test_a_lost_resume_setup_reply_adds_no_cont(self):
        cont = {"setup": {}, "lane": "standard", "plan": None, "plan_reviewed": False, "done": [], "fix_waves": 0,
                "claim_incomplete": True}
        result, _ = run(args=dict(ARGS, cont=cont), replies={"setup": None})
        self.assertEqual(result["stage"], "setup")
        self.assertNotIn("cont", result)

    def test_blocked_capability_during_an_unfinished_claim_keeps_the_claim_cont(self):
        result, _ = run(patch={"setup": {"claim": {"ok": False, "reason": "x"}}})
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
        self.assertTrue(result["cont"]["claim_incomplete"])
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


ANSWER = {"verdict": "answered", "comment_id": 30, "decisions": "May the delivery push? Chosen: Approve: push it.",
          "questions": [{"question": "May the delivery push?", "options": ["Approve: push it."],
                         "chosen": "Approve: push it.", "comment_id": 30}]}
ASKED = {"status": "needs_user", "questions": [{"question": "Which host?", "options": ["Host one.", "Host two."]}]}


# A resume that has no plan yet: it reads the owner's answer through the owner-answer step.
RESUME_FOR_ANSWER = {"setup": {"ok": True, "worktree": "/r/.wt/w-issue-9-x", "branch": "issue-9-x", "plan_dir": "/g",
                               "holder": HOLDER, "base_sha": SHA}, "plan": None, "plan_reviewed": False, "done": []}
SETUP_ACQUIRE = "forge-claim acquire --repo <slug> --issue 9 --holder <host>/session-s1 --branch <branch>"
SETUP_RENEW = "forge-claim renew --repo <slug> --issue 9 --holder <host>/session-s1 --branch <branch>"
SETUP_STATUS = "forge-claim owner-action status --repo <slug> --issue 9 --reason decision"


class OwnerAnswerTest(unittest.TestCase):
    def test_a_fresh_setup_reads_the_answer_after_the_claim_and_runs_no_owner_answer_step(self):
        result, calls = run(args=dict(ARGS, mode="plan"), patch={"setup": {"answer": ANSWER}})
        self.assertEqual(result["stage"], "planned")
        names = labels(calls)
        self.assertNotIn("owner-answer", names)
        self.assertFalse([l for l in names if l.startswith("renew-")], names)
        setup = prompt(calls, "setup")
        self.assertLess(setup.index(SETUP_ACQUIRE), setup.index(SETUP_RENEW))
        self.assertLess(setup.index(SETUP_RENEW), setup.index(SETUP_STATUS))
        self.assertLess(setup.index(SETUP_STATUS), setup.index("worktree add <worktree_path> <branch>"))
        schema = schema_of(calls, "setup")
        self.assertNotIn("answer", schema.get("required", []))
        self.assertNotIn("renew", schema.get("required", []))
        self.assertIn(ANSWER["decisions"], prompt(calls, "plan"))
        self.assertNotIn("answer", result["cont"]["setup"])
        self.assertNotIn("renew", result["cont"]["setup"])
        self.assertEqual(result["cont"]["decisions"], [ANSWER["decisions"]])

    def test_an_unusable_folded_answer_stops_before_planning_and_the_resume_reads_it(self):
        for answer in (None, {"verdict": "error"}, {"verdict": "answered"}, dict(ANSWER, decisions=""),
                       dict(ANSWER, decisions="  ")):
            with self.subTest(answer=answer):
                result, calls = run(patch={"setup": {"answer": answer}})
                self.assertEqual(result["stage"], "owner-answer")
                self.assertEqual(labels(calls), ["setup"])
                cont = result["cont"]
                self.assertNotIn("claim_incomplete", cont)
                self.assertNotIn("answer", cont["setup"])
                resumed, calls = run(args=dict(ARGS, cont=cont), replies={"owner-answer": ANSWER})
                self.assertEqual(resumed["stage"], "done")
                names = labels(calls)
                self.assertLess(names.index("owner-answer"), names.index("plan"))

    def test_the_direct_lane_setup_reads_no_answer_and_renews_nothing(self):
        _, calls = run(args=dict(ARGS, lane="direct"))
        setup = prompt(calls, "setup")
        self.assertNotIn("owner-action status", setup)
        self.assertNotIn("forge-claim renew", setup)

    def test_a_resumed_answer_read_still_renews_first(self):
        result, calls = run(args=dict(ARGS, cont=RESUME_FOR_ANSWER), replies={"owner-answer": ANSWER})
        self.assertEqual(result["stage"], "done")
        answer = prompt(calls, "owner-answer")
        self.assertLess(answer.index(RENEW), answer.index("forge-claim owner-action status"))
        self.assertIn(ANSWER["decisions"], prompt(calls, "plan"))
        result, calls = run(args=dict(ARGS, cont=RESUME_FOR_ANSWER),
                            patch={"owner-answer": {"renew": {"verdict": "not_held", "by": "h2/b1"}}})
        self.assertEqual((result["stage"], result["at"]), ("claim-lost", "plan"))
        self.assertNotIn("plan", labels(calls))

    def test_decisions_ride_in_cont_and_merge_without_repeats(self):
        first, _ = run(args=dict(ARGS, decisions="Use the flag."), patch={"setup": {"answer": ANSWER}},
                       replies={"plan": ASKED})
        self.assertEqual(first["stage"], "plan")
        self.assertEqual(first["cont"]["decisions"], ["Use the flag.", ANSWER["decisions"]])
        second, calls = run(args=dict(ARGS, cont=first["cont"]), replies={"owner-answer": ANSWER, "plan": ASKED})
        self.assertEqual(second["cont"]["decisions"], ["Use the flag.", ANSWER["decisions"]])
        self.assertEqual(prompt(calls, "plan").count(ANSWER["decisions"]), 1)

    def test_an_open_or_absent_prompt_adds_nothing(self):
        for verdict in ("none", "open"):
            with self.subTest(verdict=verdict):
                result, calls = run(patch={"setup": {"answer": dict(ANSWER, verdict=verdict, decisions="")}})
                self.assertNotIn("The owner has answered", prompt(calls, "plan"))
                self.assertNotIn("decisions", result.get("cont") or {})

    def test_an_unreadable_answer_stops_before_planning(self):
        for reply in (None, {"verdict": "error"}, {"verdict": "answered"}, dict(ANSWER, decisions=""),
                      dict(ANSWER, decisions="  ")):
            with self.subTest(reply=reply):
                result, calls = run(args=dict(ARGS, cont=RESUME_FOR_ANSWER), replies={"owner-answer": reply})
                self.assertEqual(result["stage"], "owner-answer")
                self.assertIn("cont", result)
                self.assertNotIn("plan", labels(calls))

    def test_a_plan_in_hand_or_the_direct_lane_reads_no_answer(self):
        first, _ = run(args=dict(ARGS, mode="plan"))
        self.assertEqual(first["stage"], "planned")
        _, calls = run(args=dict(ARGS, cont=first["cont"]))
        self.assertNotIn("owner-answer", labels(calls))
        _, calls = run(args=dict(ARGS, lane="direct"))
        self.assertNotIn("owner-answer", labels(calls))

    def test_a_needs_user_stop_returns_questions_and_posts_nothing(self):
        result, calls = run(replies={"plan": ASKED})
        self.assertEqual((result["stage"], result["needs_user"]), ("plan", ASKED["questions"]))
        self.assertFalse([c["label"] for c in calls if "owner-action post" in c["prompt"]])

    def test_the_planner_asks_in_box_form_and_only_past_r8(self):
        _, calls = run()
        text = prompt(calls, "plan")
        self.assertIn("R8 of ~/.agents/standards/acceptance-planning.md", text)
        self.assertIn("{question, options}", text)
        plan_call = next(c for c in calls if c["label"] == "plan")
        self.assertEqual(plan_call["schema"]["properties"]["questions"]["items"]["required"], ["question", "options"])

    def test_plan_reviews_can_cite_every_rule(self):
        rules = REPO_ROOT / "home/common/agent-skills/standards/acceptance-planning.md"
        ids = re.findall(r"^- \*\*(R\d+)\.", rules.read_text(encoding="utf-8"), re.M)
        self.assertIn("R9", ids)
        _, calls = run()
        review = next(c for c in calls if c["label"] == "plan-review")
        self.assertEqual(review["schema"]["properties"]["findings"]["items"]["properties"]["rule"]["enum"], ids)
        self.assertIn(f"every rule {ids[0]}-{ids[-1]} of", prompt(calls, "plan"))
        text = PROGRAM.read_text(encoding="utf-8")
        self.assertRegex(text, r"label: 'plan-rules-review'[^}]*schema: PLAN_REVIEW")

    def test_close_out_ends_the_decision_prompt(self):
        _, calls = run()
        close = prompt(calls, "close-out")
        self.assertIn("forge-claim owner-action end --repo owner/repo --issue 9 --reason decision", close)
        self.assertLess(close.index("--reason decision"), close.index("forge-claim release"))
        result, _ = run(patch={"close-out": {"decision_ended": False}})
        self.assertEqual(result["stage"], "close-out")


HELD = {"verdict": "already_held", "comment_id": 5}
BATCH_CHILD = {"repo_root": "/r", "issue": 9, "batch_id": "b7"}


class FoldedSetupRenewTest(unittest.TestCase):
    """#745 D1: an already_held acquire refreshes nothing, so the fresh setup renews before planning."""

    def test_an_already_held_setup_renews_and_plans_without_an_owner_answer_step(self):
        for args in (ARGS, BATCH_CHILD):
            with self.subTest(args=args):
                result, calls = run(args=args, patch={"setup": {"acquire": HELD, "renew": {"verdict": "renewed"}}})
                self.assertEqual(result["stage"], "done")
                self.assertNotIn("owner-answer", labels(calls))

    def test_a_lost_setup_renew_after_already_held_stops_before_plan(self):
        for renew in ({"verdict": "not_held", "by": "h2/b1"}, {"verdict": "error", "detail": "forge down"}, None):
            with self.subTest(renew=renew):
                result, calls = run(args=BATCH_CHILD, patch={"setup": {"acquire": HELD, "renew": renew,
                                                                       "answer": ANSWER}})
                self.assertEqual((result["stage"], result["at"]), ("claim-lost", "plan"))
                self.assertEqual(labels(calls), ["setup"])
                if renew and renew["verdict"] == "not_held":
                    self.assertNotIn("cont", result)
                else:
                    self.assertTrue(result["cont"]["claim_incomplete"])
                    self.assertNotIn("renew", result["cont"]["setup"])
                    self.assertNotIn(ANSWER["decisions"], result["cont"].get("decisions") or [])

    def test_a_transient_setup_renew_renews_again_through_the_owner_answer_step(self):
        result, calls = run(args=BATCH_CHILD, patch={"setup": {"acquire": HELD, "renew": TRANSIENT}},
                            replies={"owner-answer": ANSWER})
        self.assertEqual(result["stage"], "done")
        names = labels(calls)
        self.assertEqual(names[:3], ["setup", "owner-answer", "plan"])
        self.assertIn(RENEW.replace(HOLDER, "h1/b7"), prompt(calls, "owner-answer"))

    def test_a_lost_setup_renew_is_graded_before_a_worktree_failure_or_a_dirty_worktree(self):
        masks = ({"claim": {"ok": False, "reason": "worktree add failed"}},
                 {"existing": {"worktree": True, "dirty": True, "status": " M a.js"}},
                 {"ok": False, "reason": "closed"})
        for mask in masks:
            for renew in ({"verdict": "not_held", "by": "h2/b1"}, {"verdict": "error", "detail": "forge down"}, None):
                with self.subTest(mask=mask, renew=renew):
                    result, calls = run(args=BATCH_CHILD, patch={"setup": dict(mask, acquire=HELD, renew=renew)})
                    self.assertEqual((result["stage"], result["at"]), ("claim-lost", "plan"))
                    self.assertEqual(labels(calls), ["setup"])
                    if renew and renew["verdict"] == "not_held":
                        self.assertNotIn("cont", result)
                    else:
                        self.assertTrue(result["cont"]["claim_incomplete"])

    def test_a_transient_setup_renew_is_retried_once_not_twice(self):
        for second in (TRANSIENT, {"verdict": "renewed"}):
            with self.subTest(second=second):
                answer = {"verdict": "none", "comment_id": None, "questions": [], "decisions": ""}
                result, calls = run(args=BATCH_CHILD, patch={"setup": {"acquire": HELD, "renew": TRANSIENT}},
                                    replies={"owner-answer": [dict(answer, renew=second), dict(answer, renew={"verdict": "renewed"})]})
                self.assertEqual(labels(calls).count("owner-answer"), 1)
                if second is TRANSIENT:
                    self.assertEqual((result["stage"], result["at"]), ("claim-lost", "plan"))
                    self.assertNotIn("plan", labels(calls))
                else:
                    self.assertEqual(result["stage"], "done")

    def test_an_acquired_setup_reads_no_renew(self):
        result, calls = run(patch={"setup": {"renew": None}})
        self.assertEqual(result["stage"], "done")
        self.assertNotIn("owner-answer", labels(calls))


RENEW = f"forge-claim renew --repo owner/repo --issue 9 --holder {HOLDER} --branch issue-9-x"
# (at, the call that renews, nested): a nested renew rides in that call's reply as renew.
BOUNDARIES = [("tasks", "impl-1", True),
              ("final-review", "renew-final-review", False), ("verify", "verify", True),
              ("ship", "pr", True), ("checks-1", "checks-1", True), ("merge", "merge", True)]
# The text each folded prompt runs after its renew.
STEP_MARK = {"impl-1": "task-1.md", "verify": "Run the project's declared verification",
             "pr": "open the pull request", "checks-1": "to be mergeable", "merge": "forge-claim land acquire"}


def boundary_reply(via, nested, renew):
    return {"patch": {via: {"renew": renew}}} if nested else {"replies": {via: renew}}


def next_guarded(happy, via):
    """The first happy-path label after via that a stop there must not reach (the lock release always runs)."""
    return next(l for l in happy[happy.index(via) + 1:] if l != "land-unlock")


class ClaimTest(unittest.TestCase):
    """#635: one claim primitive; held elsewhere stops before any worktree; renew at every boundary."""

    def test_claim_held_elsewhere_stops_before_any_worktree(self):
        for verdict in ("held_by", "lost_to"):
            with self.subTest(verdict=verdict):
                result, calls = run(patch={"setup": {"acquire": {"verdict": verdict, "by": "h2/b1", "comment_id": 5},
                                                     "claim": None}})
                self.assertEqual((result["stage"], result["verdict"], result["by"]), ("claimed", verdict, "h2/b1"))
                self.assertNotIn("cont", result)
                self.assertEqual(labels(calls), ["setup"])

    def test_acquire_names_the_holder_and_branch(self):
        stopped, calls = run(patch={"setup": {"claim": {"ok": False, "reason": "x"}}})
        self.assertIn("forge-claim acquire --repo <slug> --issue 9 --holder <host>/session-s1 --branch <branch>",
                      prompt(calls, "setup"))
        self.assertEqual(stopped["cont"]["setup"]["holder"], HOLDER)
        _, calls = run(args=dict(ARGS, cont=stopped["cont"]))
        self.assertIn(f"forge-claim acquire --repo owner/repo --issue 9 --holder {HOLDER} --branch issue-9-x",
                      prompt(calls, "acquire"))
        _, calls = run(args={"repo_root": "/r", "issue": 9, "batch_id": "b7"})
        self.assertIn("--holder <host>/b7 ", prompt(calls, "setup"))

    def test_already_held_continues(self):
        folded = {"setup": {"acquire": {"verdict": "already_held", "comment_id": 5}}}
        result, calls = run(patch=folded)
        self.assertEqual(result["stage"], "done")
        self.assertNotIn("acquire", labels(calls))
        # A batch acquires with its own holder before it starts the child, so its folded acquire is already_held.
        result, _ = run(args={"repo_root": "/r", "issue": 9, "batch_id": "b7"}, patch=folded)
        self.assertEqual(result["stage"], "done")

    def test_acquire_error_stops_with_a_cont_that_finishes_the_claim(self):
        for reply in ({"verdict": "error", "detail": "forge down"}, None):
            with self.subTest(reply=reply):
                result, calls = run(patch={"setup": {"acquire": reply}})
                self.assertEqual(result["stage"], "claim")
                self.assertTrue(result["cont"]["claim_incomplete"])
                self.assertEqual(labels(calls), ["setup"])

    def test_renew_runs_before_every_stage_boundary(self):
        _, calls = run()
        names = labels(calls)
        self.assertEqual([l for l in names if l.startswith("renew-")], [f"renew-{a}" for a, v, nested in BOUNDARIES if not nested])
        for at, via, nested in BOUNDARIES:
            with self.subTest(at=at):
                text = prompt(calls, via)
                self.assertIn(RENEW, text)
                if nested:
                    self.assertIn("When renew's verdict is not renewed, stop there", text)
                    self.assertLess(text.index(RENEW), text.index(STEP_MARK[via]))

    def test_ended_claim_stops_at_its_boundary_with_no_cont(self):
        happy = labels(run()[1])
        for at, via, nested in BOUNDARIES:
            with self.subTest(at=at):
                result, calls = run(**boundary_reply(via, nested, {"verdict": "not_held", "by": "h2/b1"}))
                self.assertEqual((result["stage"], result["at"]), ("claim-lost", at))
                self.assertNotIn(next_guarded(happy, via), labels(calls))
                self.assertNotIn("cont", result)

    def test_unanswered_renew_stops_with_a_cont_that_reacquires(self):
        happy = labels(run()[1])
        for at, via, nested in BOUNDARIES:
            for reply in ({"verdict": "error", "detail": "forge down"}, None):
                with self.subTest(at=at, reply=reply):
                    result, calls = run(**boundary_reply(via, nested, reply))
                    self.assertEqual((result["stage"], result["at"]), ("claim-lost", at))
                    self.assertNotIn(next_guarded(happy, via), labels(calls))
                    self.assertTrue(result["cont"]["claim_incomplete"])

    def test_resume_after_an_unanswered_renew_reacquires_and_finishes(self):
        stopped, _ = run(patch={"pr": {"renew": None}})
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
        self.assertNotIn("--add-label", setup)
        # Only the acquire step names the label, saying forge-claim adds it itself.
        self.assertEqual(setup.count("in-progress"), 1)
        self.assertIn("adds the in-progress label itself", setup)
        self.assertIn("parked", setup)

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
        self.assertIn("--holder h9/b1 ", prompt(calls, "owner-answer"))
        self.assertNotIn("acquire", labels(calls))


TRANSIENT = {"verdict": "error", "detail": "gh_failed: dial tcp: connect: network is unreachable", "transient": True}
# The full second reply of each folded step whose first renew ran out of transport retries; the harness fills renew and lock.
SECOND = {
    "impl-1": {"status": "done", "start_head": "b0", "commit": "c0ffee", "tests": ["t"], "notes": "ok"},
    "verify": {"head": SHA, "clean": True, "results": [{"id": "build", "status": "pass", "summary": "ok"}]},
    "pr": {"pr": 42, "head": SHA},
    "checks-1": {"state": "passed", "head": SHA, "required": ["ci"]},
    "merge": {"merged": True, "merge_commit": SHA, "notes": "merged"},
}


def transient_replies(via, nested, recovers=True):
    """Replies whose renew at `via` runs out of transport retries once, then recovers (or not)."""
    if nested:
        first = {"renew": TRANSIENT, "lock": None} if via in ("pr", "merge") else {"renew": TRANSIENT}
        then = SECOND[via]
    else:
        first, then = TRANSIENT, {"verdict": "renewed", "comment_id": 7}
    return {via: [first, then if recovers else first]}


class TransientTest(unittest.TestCase):
    """#740 D6: a renew or acquire that ran out of forge-claim's transport retries re-calls its step once."""

    def test_a_transient_renew_is_called_once_more_and_goes_on(self):
        happy = labels(run()[1])
        for at, via, nested in BOUNDARIES:
            with self.subTest(at=at):
                result, calls = run(replies=transient_replies(via, nested))
                self.assertEqual(result["stage"], "done")
                self.assertEqual(labels(calls).count(via), happy.count(via) + 1)

    def test_a_transient_renew_twice_stops_with_a_cont_that_reacquires(self):
        happy = labels(run()[1])
        for at, via, nested in BOUNDARIES:
            with self.subTest(at=at):
                result, calls = run(replies=transient_replies(via, nested, recovers=False))
                self.assertEqual((result["stage"], result["at"]), ("claim-lost", at))
                self.assertTrue(result["cont"]["claim_incomplete"])
                self.assertEqual(labels(calls).count(via), 2)
                self.assertNotIn(next_guarded(happy, via), labels(calls))

    def test_not_held_and_a_plain_error_are_never_called_again(self):
        for at, via, nested in BOUNDARIES:
            for renew in ({"verdict": "not_held", "by": "h2/b1"}, {"verdict": "not_held", "transient": True},
                          {"verdict": "error", "detail": "forge down"},
                          {"verdict": "error", "detail": "forge down", "transient": False}):
                with self.subTest(at=at, renew=renew):
                    _, calls = run(**boundary_reply(via, nested, renew))
                    self.assertEqual(labels(calls).count(via), 1)

    def test_a_transient_folded_acquire_runs_the_acquire_step_once_then_the_worktree(self):
        result, calls = run(patch={"setup": {"acquire": TRANSIENT, "claim": None}})
        self.assertEqual(result["stage"], "done")
        self.assertEqual(labels(calls)[:3], ["setup", "acquire", "worktree"])
        self.assertEqual(labels(calls).count("acquire"), 1)
        self.assertIn(f"forge-claim acquire --repo owner/repo --issue 9 --holder {HOLDER} --branch issue-9-x",
                      prompt(calls, "acquire"))

    def test_a_transient_folded_acquire_whose_acquire_step_is_transient_stops_with_a_cont(self):
        result, calls = run(patch={"setup": {"acquire": TRANSIENT, "claim": None}}, replies={"acquire": TRANSIENT})
        self.assertEqual(result["stage"], "claim")
        self.assertTrue(result["cont"]["claim_incomplete"])
        self.assertEqual(labels(calls), ["setup", "acquire"])

    def test_a_resumed_transient_acquire_is_called_once_more(self):
        stopped, _ = run(patch={"pr": {"renew": None}})
        for second, stage in (({"verdict": "already_held", "comment_id": 7}, "done"), (TRANSIENT, "claim")):
            with self.subTest(stage=stage):
                result, calls = run(args=dict(ARGS, cont=stopped["cont"]), replies={"acquire": [TRANSIENT, second]})
                self.assertEqual(result["stage"], stage)
                self.assertEqual(labels(calls).count("acquire"), 2)
                self.assertEqual("worktree" in labels(calls), stage == "done")

    def test_a_transient_folded_acquire_reads_the_answer_through_the_owner_answer_step(self):
        result, calls = run(patch={"setup": {"acquire": TRANSIENT, "claim": None, "answer": None}})
        self.assertEqual(result["stage"], "done")
        self.assertEqual(labels(calls)[:5], ["setup", "acquire", "worktree", "owner-answer", "plan"])

    def test_every_renew_and_acquire_asks_for_transient(self):
        _, calls = run()
        self.assertEqual(member(schema_of(calls, "verify"), "renew")["properties"]["transient"], {"type": "boolean"})
        for via in ("setup", "impl-1", "renew-final-review", "verify", "pr", "checks-1", "merge"):
            with self.subTest(via=via):
                self.assertIn("transient", prompt(calls, via))
        _, resumed = run(args=dict(ARGS, cont=RESUME_FOR_ANSWER))
        self.assertIn("transient", prompt(resumed, "owner-answer"))
        stopped, _ = run(patch={"pr": {"renew": None}})
        _, calls = run(args=dict(ARGS, cont=stopped["cont"]))
        self.assertEqual(schema_of(calls, "acquire")["properties"]["transient"], {"type": "boolean"})
        self.assertIn("transient", prompt(calls, "acquire"))

    def test_every_forge_claim_prompt_gives_the_long_bash_timeout(self):
        timeout = "a Bash timeout of 20 minutes (1200000 ms), and land acquire --wait 60 minutes (3600000 ms)"
        _, calls = run()
        for via in ("setup", "impl-1", "renew-final-review", "verify", "pr", "checks-1", "merge"):
            with self.subTest(via=via):
                self.assertIn(timeout, prompt(calls, via))
        _, resumed = run(args=dict(ARGS, cont=RESUME_FOR_ANSWER))
        self.assertIn(timeout, prompt(resumed, "owner-answer"))
        _, calls = run(patch={"pr": {"head": "c" * 40}})  # a head-moved stop releases the lock
        self.assertIn(timeout, prompt(calls, "land-unlock"))
        stopped, _ = run(patch={"pr": {"renew": None}})
        _, calls = run(args=dict(ARGS, cont=stopped["cont"]))
        self.assertIn(timeout, prompt(calls, "acquire"))
        merge = "d" * 40
        _, calls = run(replies={"checks-1": {"state": "behind", "head": SHA}, "checks-2": {"state": "passed", "head": merge}},
                       patch={"sync-1": {"merge_commit": merge}})
        self.assertIn(timeout, prompt(calls, "land-lock-2"))

    RETRIED = re.compile(r"forge-claim (?:acquire|renew|release|status|land acquire|land release|owner-action status)\b")

    def test_every_prompt_that_runs_a_retried_forge_claim_command_gives_the_long_bash_timeout(self):
        # Two 30 s timeouts plus the backoff use 120 s before the third try starts, so a command that
        # forge-claim retries needs the long Bash timeout wherever any prompt runs it.
        timeout = "a Bash timeout of 20 minutes (1200000 ms)"
        seen = set()
        _, calls = run()
        for call in calls:
            if self.RETRIED.search(call["prompt"]):
                seen.add(call["label"])
                with self.subTest(label=call["label"]):
                    self.assertIn(timeout, call["prompt"])
        self.assertIn("close-out", seen)


class SetupIdempotenceTest(unittest.TestCase):
    """#635: setup re-adopts an existing branch or worktree, never resets, stops on a merged duplicate."""

    EXISTING = {"local_branch": True, "remote_branch": True, "worktree": True, "dirty": True,
                "status": " M home/x.py", "head": "e" * 40}
    BANNED = ("reset --hard", "git clean", "checkout --", "git restore")

    def test_dirty_existing_worktree_is_readopted_without_reset(self):
        result, calls = run(patch={"setup": {"existing": self.EXISTING}})
        self.assertEqual(result["stage"], "dirty")
        self.assertEqual(labels(calls), ["setup"])
        self.assertIn(" M home/x.py", result["details"])
        self.assertEqual(result["cont"]["setup"]["worktree"], "/r/.wt/w-issue-9-x")
        self.assertNotIn("claim_incomplete", result["cont"])
        self.assertIn("adopt <worktree_path> as it is and run no worktree command", prompt(calls, "setup"))
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
        setup = prompt(calls, "setup")
        self.assertIn("merge-base origin/<integration_branch> HEAD", setup)
        self.assertIn("when existing.worktree is true, adopt <worktree_path> as it is and run no worktree command", setup)
        self.assertIn("Never reset, clean, restore or stash anything in it.", setup)

    def test_existing_local_branch_gets_a_worktree_without_a_new_branch(self):
        existing = dict(self.EXISTING, worktree=False, remote_branch=False, dirty=False, status="")
        result, calls = run(patch={"setup": {"existing": existing}})
        self.assertEqual(result["stage"], "done")
        self.assertIn("when existing.local_branch is true, git -C /r worktree add <worktree_path> <branch> (adopt the local branch)",
                      prompt(calls, "setup"))

    def test_remote_only_branch_is_checked_out_from_origin(self):
        existing = dict(self.EXISTING, worktree=False, local_branch=False, dirty=False, status="")
        _, calls = run(patch={"setup": {"existing": existing}})
        self.assertIn("when existing.remote_branch is true, git -C /r worktree add --no-track -b <branch> <worktree_path> origin/<branch>",
                      prompt(calls, "setup"))

    def test_merged_pr_referencing_the_issue_stops_as_a_duplicate(self):
        result, calls = run(replies={"setup": {"ok": False, "reason": "duplicate", "duplicate_pr": 41}})
        self.assertEqual(result["stage"], "setup")
        self.assertEqual(labels(calls), ["setup"])
        result, calls = run(patch={"setup": {"merged_refs": [{"number": 41, "closes": True}]}})
        self.assertEqual((result["stage"], result["duplicate"]), ("setup", 41))
        self.assertEqual(labels(calls), ["setup"])

    def test_failed_adoption_resumes_by_adopting_again(self):
        local = dict(self.EXISTING, worktree=False, remote_branch=False, dirty=False, status="")
        failed, _ = run(patch={"setup": {"existing": local, "claim": {"ok": False, "reason": "worktree add failed"}}})
        self.assertEqual(failed["stage"], "claim")
        self.assertTrue(failed["cont"]["claim_incomplete"])
        result, calls = run(args=dict(ARGS, cont=failed["cont"]), patch={"setup": {"existing": local}})
        self.assertEqual(result["stage"], "done")
        self.assertIn("existing", prompt(calls, "setup"))
        worktree = prompt(calls, "worktree")
        self.assertIn("git -C /r worktree add /r/.wt/w-issue-9-x issue-9-x", worktree)
        self.assertNotIn("-b issue-9-x", worktree)

    def test_resume_of_a_half_made_worktree_adopts_it(self):
        failed, _ = run(patch={"setup": {"claim": {"ok": False, "reason": "plan_dir failed"}}})
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


class SpecPrTest(unittest.TestCase):
    """#752: a spec merged in its own docs PR is no duplicate and never the delivery's own merged PR."""

    MINE, SPEC = "d" * 40, "5" * 40

    def cont(self, **extra):
        setup = {"ok": True, "worktree": "/r/.wt/w-issue-9-x", "branch": "issue-9-x", "plan_dir": "/g",
                 "holder": HOLDER, "base_sha": SHA}
        return dict({"setup": setup, "plan": dict(PLAN, tasks=tasks(2)), "plan_reviewed": True,
                     "done": [{"n": 1, "commit": self.MINE}]}, **extra)

    def test_a_closing_merged_pr_is_a_duplicate_even_when_setup_proceeds(self):
        result, calls = run(patch={"setup": {"merged_refs": [{"number": 41, "closes": True}]}})
        self.assertEqual((result["stage"], result["duplicate"]), ("setup", 41))
        self.assertEqual(labels(calls), ["setup"])

    def test_a_refs_only_merged_pr_lets_setup_proceed(self):
        result, _ = run(args=dict(ARGS, spec="/r/spec.md"),
                        patch={"setup": {"merged_refs": [{"number": 7, "closes": False}]}})
        self.assertEqual(result["stage"], "done")
        self.assertNotIn("duplicate", result)

    def test_a_refs_only_pr_is_no_duplicate_whatever_merged_pr_says(self):
        result, _ = run(args=dict(ARGS, spec="/r/spec.md"),
                        patch={"setup": {"merged_pr": 7, "merged_refs": [{"number": 7, "closes": False}]}})
        self.assertEqual(result["stage"], "done")
        self.assertNotIn("duplicate", result)

    def test_a_close_out_cont_keeps_its_pr_through_successive_stops(self):
        cont = {"setup": {"holder": HOLDER, "branch": "issue-9-x", "worktree": "/r/.wt/w-issue-9-x",
                          "worktree_path": "/r/.wt/w-issue-9-x"},
                "lane": "standard", "plan": {"acceptance": PLAN["acceptance"]}, "pr": 42}
        facts = {"merged_heads": [{"number": 42, "commits": []}]}
        failed = {"close-out": {"issue_state": "OPEN", "released": False}}
        first, calls = run(args=dict(ARGS, cont=cont), patch={"setup": facts, **failed})
        self.assertEqual((first["stage"], first["cont"]["pr"]), ("close-out", 42))
        second, calls = run(args=dict(ARGS, cont=first["cont"]), patch={"setup": facts, **failed})
        self.assertEqual((second["stage"], second["cont"]["pr"]), ("close-out", 42))
        self.assertIn("--state merged --head issue-9-x", prompt(calls, "setup"))
        third, _ = run(args=dict(ARGS, cont=second["cont"]), patch={"setup": facts})
        self.assertEqual((third["stage"], third["pr"]), ("done", 42))

    def test_resume_never_closes_out_a_same_named_spec_pr(self):
        # Squash strategy: the adopted spec branch put base_sha before the spec, so no ancestry rule can tell.
        cont = self.cont()
        result, calls = run(args=dict(ARGS, cont=cont), patch={"setup": merged(7, self.SPEC)})
        self.assertEqual((result["stage"], result["invalid"]), ("setup", "merged_pr"))
        self.assertEqual(result["cont"], cont)
        self.assertEqual(labels(calls), ["setup"])
        # Listed but not claimed as merged: the resume carries on with its tasks.
        result, calls = run(args=dict(ARGS, cont=cont),
                            patch={"setup": {"merged_heads": [{"number": 7, "commits": [self.SPEC]}]}})
        self.assertEqual(result["stage"], "done")
        self.assertIn("impl-2", labels(calls))
        # The hold of a normal ship comes last; a close-out straight after setup is what is refused.
        self.assertEqual(labels(calls)[:3], ["setup", "impl-2", "review-2"])

    def test_resume_closes_out_its_own_merged_pr_found_by_its_commits(self):
        heads = [{"number": 7, "commits": [self.SPEC]}, {"number": 42, "commits": [self.SPEC, self.MINE]}]
        result, calls = run(args=dict(ARGS, cont=self.cont()), patch={"setup": {"merged_heads": heads}})
        self.assertEqual((result["stage"], result["pr"]), ("done", 42))
        self.assertEqual(labels(calls), ["setup", "hold", "close-out"])

    def test_a_recorded_pr_outranks_a_commit_match_on_another_pr(self):
        """DR-001: a reused branch can list the same commit on two merged PRs; the recorded number decides."""
        heads = [{"number": 43, "commits": [self.MINE]}, {"number": 42, "commits": [self.MINE]}]
        cont = self.cont(pr=42)
        result, calls = run(args=dict(ARGS, cont=cont), patch={"setup": {"merged_pr": 42, "merged_heads": heads}})
        self.assertEqual((result["stage"], result["pr"]), ("done", 42))
        self.assertEqual(labels(calls), ["setup", "hold", "close-out"])
        result, calls = run(args=dict(ARGS, cont=cont), patch={"setup": {"merged_heads": heads}})
        self.assertEqual((result["stage"], result["pr"]), ("done", 42))
        # Only when no PR is recorded does a commit decide.
        result, _ = run(args=dict(ARGS, cont=self.cont()), patch={"setup": {"merged_heads": heads}})
        self.assertEqual((result["stage"], result["pr"]), ("done", 43))

    def test_a_cont_with_no_commit_and_no_pr_never_closes_out(self):
        failed, _ = run(patch={"setup": {"claim": {"ok": False, "reason": "worktree add failed"}}})
        self.assertTrue(failed["cont"]["claim_incomplete"])
        result, calls = run(args=dict(ARGS, cont=failed["cont"]), patch={"setup": merged(7, self.SPEC)})
        self.assertEqual((result["stage"], result["invalid"]), ("setup", "merged_pr"))
        self.assertTrue(result["cont"]["claim_incomplete"])
        self.assertNotIn("hold", labels(calls))
        self.assertNotIn("--state merged", prompt(calls, "setup"))

    def test_a_batch_close_out_cont_finds_its_pr_by_number(self):
        cont = {"setup": {"holder": HOLDER, "branch": "issue-9-x", "worktree": "/r/.wt/w-issue-9-x",
                          "worktree_path": "/r/.wt/w-issue-9-x"},
                "lane": "standard", "plan": {"acceptance": PLAN["acceptance"]}, "pr": 42}
        result, calls = run(args=dict(ARGS, cont=cont), patch={"setup": {"merged_heads": [{"number": 42, "commits": []}]}})
        self.assertEqual((result["stage"], result["pr"]), ("done", 42))
        self.assertEqual(labels(calls), ["setup", "hold", "close-out"])


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
    NOTE_ROWS = (
        ("R9", criterion(NOTE, verify={"ac": "AC4", "kind": "note", "host": "h1",
                                       "when": {"deployed_includes": SHA}, "run": {"script": "scripts/check-live"}},
                         lint=OK_LINT)),
        ("R9", criterion(NOTE, script="scripts/check-live")),
    )
    RULE_FINDING = {"verdict": "findings",
                    "findings": [{"severity": "important", "rule": "R2", "summary": "s"}]}

    REVISED = with_criteria(HUMAN, tasks=[{"n": 1, "title": "revised", "file": "/g/task-1.md", "risk": "standard"}])

    def test_planner_gets_the_reviewer_rubric_and_setup_facts(self):
        source = PROGRAM.read_text(encoding="utf-8")
        found = re.search(r"const PLAN_RUBRIC = `([^`]*)`", source)
        self.assertIsNotNone(found, "PLAN_RUBRIC is not a shared constant")
        rubric = found.group(1)
        self.assertEqual(source.count(rubric), 1)
        facts = "setup-facts-token-712"
        _, calls = run(patch={"setup": {"details": facts}}, replies={"plan-review": self.RULE_FINDING})
        self.assertIn(rubric, prompt(calls, "plan-review"))
        for label in ("plan", "plan-revise"):
            text = prompt(calls, label)
            self.assertIn(rubric, text, label)
            self.assertIn(facts, text, label)
        _, calls = run()
        self.assertNotIn(facts, prompt(calls, "plan"))
        self.assertNotIn("undefined", prompt(calls, "plan"))
        self.assertIn(rubric, prompt(calls, "plan"))

    def keep_stop(self):
        plan = with_criteria(HUMAN)
        return run(replies={"plan": plan, "plan-revise": plan, "plan-rules-revise": self.REVISED,
                            "plan-review": self.RULE_FINDING, "plan-rules-review": self.RULE_FINDING})

    def gate(self, plan):
        return run(replies={"plan": plan, "plan-revise": plan, "plan-rules-revise": plan})

    def test_each_rule_violation_stops_at_plan_review_naming_the_rule(self):
        for rule, bad in self.ROWS + self.NOTE_ROWS:
            with self.subTest(rule=rule, ac=bad["id"]):
                plan = with_criteria(bad)
                result, calls = self.gate(plan)
                self.assertEqual(result["stage"], "plan-review")
                self.assertIn((rule, bad["id"]), [(r["rule"], r["ac"]) for r in result["rules"]])
                self.assertEqual(result["cont"]["plan"], plan)
                self.assertFalse(result["cont"]["plan_reviewed"])
                self.assertEqual(result["cont"]["plan_findings"]["rounds"], 1)
                self.assertEqual(labels(calls).count("plan-revise"), 1)
                self.assertEqual(labels(calls).count("plan-rules-revise"), 1)
                self.assertIn(f'"rule":"{rule}"', prompt(calls, "plan-revise"))
                self.assertIn(f'"rule":"{rule}"', prompt(calls, "plan-rules-revise"))
                self.assertNotIn("impl-1", labels(calls))

    def test_a_note_without_verify_or_script_passes_plan_rules(self):
        """#736 AC1: a plan with a note criterion and no script passes planRules; the planner learns the kind."""
        result, calls = run(replies={"plan": with_criteria(NOTE)}, patch={"close-out": {"notes_posted": True}})
        kinds = schema_of(calls, "plan")["properties"]["acceptance"]["items"]["properties"]["kind"]["enum"]
        self.assertEqual(kinds, ["code", "evidence", "human", "note"])
        self.assertNotIn("plan-revise", labels(calls))
        self.assertNotIn("plan-rules-review", labels(calls))
        self.assertIn("impl-1", labels(calls))
        self.assertNotEqual(result["stage"], "plan-review")
        _, direct = run(args=dict(ARGS, lane="direct"))
        for text in (prompt(calls, "plan"), prompt(direct, "direct-impl")):
            for kind in kinds:
                self.assertIn(f"{kind} if ", text)

    def test_a_note_with_a_verify_block_or_script_is_refused_naming_r9(self):
        """#736 AC1: planRules refuses a note carrying a verify block or a script."""
        for _, bad in self.NOTE_ROWS:
            with self.subTest(bad=sorted(bad)):
                result, _ = self.gate(with_criteria(bad))
                self.assertEqual(result["stage"], "plan-review")
                self.assertEqual([(r["rule"], r["ac"]) for r in result["rules"]], [("R9", "AC4")])

    def test_a_metric_note_is_still_an_r5_refusal(self):
        result, _ = self.gate(with_criteria(criterion(NOTE, metric=True)))
        self.assertIn(("R5", "AC4"), [(r["rule"], r["ac"]) for r in result["rules"]])

    def test_the_planner_never_tags_a_note_as_a_metric(self):
        """#736 (D8): an owner-designated latency observation is a note, so the metric instruction exempts notes."""
        _, calls = run()
        text = prompt(calls, "plan")
        metric = text[text.index("set metric true"):]
        metric = metric[:metric.index(". ")]
        self.assertIn("never on a note", metric)

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

    def test_rules_stop_keeps_the_revised_plan(self):
        # A violation only a reviewer can see survives the full revise and one rules revise: the revised plan is kept.
        result, calls = self.keep_stop()
        names = labels(calls)
        self.assertEqual(result["stage"], "plan-review")
        self.assertEqual([r["rule"] for r in result["rules"]], ["R2"])
        self.assertEqual(result["cont"]["plan"], self.REVISED)
        self.assertFalse(result["cont"]["plan_reviewed"])
        kept = result["cont"]["plan_findings"]
        self.assertEqual(kept["rounds"], 1)
        self.assertEqual([r["rule"] for r in kept["rules"]], ["R2"])
        self.assertEqual([f["rule"] for f in kept["findings"]], ["R2"])
        self.assertEqual((names.count("plan-revise"), names.count("plan-rules-revise"), names.count("plan-rules-review")), (1, 1, 2))
        self.assertLess(names.index("plan-revise"), names.index("plan-rules-revise"))
        self.assertIn('"rule":"R2"', prompt(calls, "plan-rules-revise"))
        self.assertIn('"rule":"R2"', prompt(calls, "plan-rules-review"))
        self.assertNotIn("impl-1", names)
        # A clean rules re-review after the full revise proceeds with no rules revise.
        plan = with_criteria(HUMAN)
        _, calls = run(replies={"plan": plan, "plan-revise": plan, "plan-review": self.RULE_FINDING},
                       patch={"close-out": {"issue_state": "OPEN"}})
        self.assertNotIn("plan-rules-revise", labels(calls))
        self.assertIn("impl-1", labels(calls))
        # A silent rules re-reviewer keeps the revised plan, re-targeting the findings the revise was given (D6).
        result, calls = run(replies={"plan": plan, "plan-review": self.RULE_FINDING, "plan-rules-review": None})
        self.assertEqual(result["stage"], "plan-review")
        self.assertIsNotNone(result["cont"]["plan"])
        self.assertEqual(result["cont"]["plan_findings"]["rounds"], 0)
        self.assertEqual([r["rule"] for r in result["cont"]["plan_findings"]["rules"]], ["R2"])
        self.assertNotIn("plan-rules-revise", labels(calls))

    def test_resume_runs_one_rules_revise_with_decisions(self):
        first, _ = self.keep_stop()
        decision = "D: keep the act run and name the senses reason."
        result, calls = run(args=dict(ARGS, cont=first["cont"], decisions=decision))
        names = labels(calls)
        for label in ("plan", "plan-revise", "plan-review", "plan-codex"):
            self.assertNotIn(label, names)
        self.assertEqual(names.count("owner-answer"), 1)
        self.assertEqual(names.count("plan-rules-revise"), 1)
        answer = prompt(calls, "owner-answer")
        self.assertIn(RENEW, answer)
        self.assertLess(answer.index(RENEW), answer.index("forge-claim owner-action status"))
        self.assertLess(names.index("owner-answer"), names.index("plan-rules-revise"))
        self.assertLess(names.index("plan-rules-revise"), names.index("plan-rules-review"))
        revise = prompt(calls, "plan-rules-revise")
        self.assertIn(decision, revise)
        self.assertIn('"rule":"R2"', revise)
        self.assertIn("impl-1", names)
        self.assertNotIn("plan_findings", result.get("cont") or {})

    def test_resume_plans_again_when_a_non_rule_finding_was_kept(self):
        # A silent rules re-reviewer keeps every finding of the full review, including ones no rules revise may clear;
        # the kept plan has spent its one full revise, so the resume plans again with the owner's answer.
        plan = with_criteria(HUMAN)
        interface = {"verdict": "findings", "findings": [{"severity": "important", "summary": "interface mismatch"}]}
        codex = {"verdict": "findings", "findings": [{"severity": "important", "rule": "R2", "summary": "s", "source": "codex"}]}
        for kept in (interface, codex):
            with self.subTest(kept=kept["findings"][0]["summary"]):
                first, _ = run(replies={"plan": plan, "plan-revise": plan, "plan-review": kept, "plan-rules-review": None})
                self.assertEqual(first["stage"], "plan-review")
                self.assertIsNotNone(first["cont"]["plan_findings"])
                result, calls = run(args=dict(ARGS, cont=first["cont"]))
                names = labels(calls)
                self.assertNotIn("plan-rules-revise", names)
                self.assertEqual(names.count("plan"), 1)
                self.assertEqual(names.count("plan-revise"), 0)
                self.assertIn("plan-review", names)
                self.assertEqual(names.count("owner-answer"), 1)
                self.assertNotIn("plan_findings", result.get("cont") or {})

    def test_a_stuck_plan_with_a_ruleless_finding_stays_within_the_revise_bound(self):
        # Plan bound: at most one full revise and two rules revises per plan, however many resumes a ruleless finding takes.
        plan = with_criteria(HUMAN)
        bare = {"verdict": "findings", "findings": [{"severity": "important", "summary": "AC3 breaks a rule"}]}
        replies = {"plan": plan, "plan-revise": plan, "plan-rules-revise": plan, "plan-review": self.RULE_FINDING,
                   "plan-rules-review": [self.RULE_FINDING, bare]}
        result, calls = run(replies=replies)
        self.assertEqual(result["cont"]["plan_findings"]["rounds"], 1)
        for _ in range(4):
            result, calls = run(args=dict(ARGS, cont=result["cont"]), replies=replies)
            names = labels(calls)
            # Each resume plans a fresh plan: it is that plan's only full revise, and the kept plan is never revised again.
            self.assertEqual(names.count("plan"), 1)
            self.assertEqual(names.count("plan-revise"), 1)
            self.assertLessEqual(names.count("plan-rules-revise"), 2)
            self.assertLess(names.index("plan"), names.index("plan-revise"))
            self.assertEqual(result["stage"], "plan-review")
            self.assertNotIn("impl-1", names)

    def test_a_kept_finding_survives_an_unread_owner_answer(self):
        plan = with_criteria(HUMAN)
        interface = {"verdict": "findings", "findings": [{"severity": "important", "summary": "interface mismatch"}]}
        first, _ = run(replies={"plan": plan, "plan-revise": plan, "plan-review": interface, "plan-rules-review": None})
        kept = first["cont"]["plan_findings"]
        self.assertIsNotNone(kept)
        for answer in (None, {"verdict": "answered", "comment_id": 1, "questions": [], "decisions": " "}):
            with self.subTest(answer=answer):
                result, calls = run(args=dict(ARGS, cont=first["cont"]), replies={"owner-answer": answer})
                self.assertEqual(result["stage"], "owner-answer")
                self.assertEqual(result["cont"]["plan"], plan)
                self.assertEqual(result["cont"]["plan_findings"], kept)
                self.assertNotIn("plan-review", labels(calls))
                again, calls = run(args=dict(ARGS, cont=result["cont"]), replies={"owner-answer": {
                    "verdict": "answered", "comment_id": 1, "questions": [], "decisions": "D: pick one"}})
                self.assertEqual(labels(calls).count("owner-answer"), 1)
                self.assertIn("plan-review", labels(calls))
                self.assertIn("D: pick one", prompt(calls, "plan"))

    def test_a_codex_finding_re_reported_without_source_gets_no_rules_only_revise(self):
        # The rules re-review keeps neither source nor finding identity, so it may re-report a Codex finding under any rule id
        # or none; a Codex-triggered plan never gets a Claude-only second revise.
        plan = with_criteria(HUMAN)
        def report(**kw):
            return {"verdict": "findings", "findings": [dict({"severity": "important", "summary": "AC1 is not observable"}, **kw)]}
        for name, codex, rereview in (("ruled", report(rule="R2"), report(rule="R2")),
                                      ("ruleless", report(), report(rule="R2")),
                                      ("other-rule", report(rule="R2"), report(rule="R6"))):
            with self.subTest(codex=name):
                replies = {"plan": plan, "plan-revise": plan, "plan-codex": {"available": True, **codex},
                           "plan-rules-review": [rereview, {"verdict": "pass", "findings": []}]}
                result, calls = run(replies=replies)
                self.assertEqual(result["stage"], "plan-review")
                self.assertNotIn("plan-rules-revise", labels(calls))
                self.assertEqual(labels(calls).count("plan-rules-review"), 1)
                self.assertEqual(result["cont"]["plan_findings"]["rounds"], 0)
                self.assertNotIn("impl-1", labels(calls))
                # The resume does not run a rules-only revise either: the plan is planned again and reviewed in full.
                again, calls = run(args=dict(ARGS, cont=result["cont"]))
                self.assertNotIn("plan-rules-revise", labels(calls))
                self.assertEqual(labels(calls).count("plan"), 1)
                self.assertIn("plan-review", labels(calls))

    def test_second_rules_failure_on_resume_drops_the_plan(self):
        first, _ = self.keep_stop()
        result, calls = run(args=dict(ARGS, cont=first["cont"]), replies={"plan-rules-review": self.RULE_FINDING})
        self.assertEqual(result["stage"], "plan-review")
        self.assertEqual(labels(calls).count("plan-rules-revise"), 1)
        self.assertIsNone(result["cont"]["plan"])
        self.assertFalse(result["cont"]["plan_reviewed"])
        self.assertNotIn("plan_findings", result["cont"])
        self.assertNotIn("impl-1", labels(calls))
        _, calls = run(args=dict(ARGS, cont=result["cont"]))
        self.assertIn("plan", labels(calls))

    def test_codex_finding_left_gets_no_second_revise(self):
        plan = with_criteria(HUMAN)
        echoed = {"verdict": "findings", "findings": [{"severity": "important", "rule": "R2", "summary": "s", "source": "codex"}]}
        bare = {"verdict": "findings", "findings": [{"severity": "important", "summary": "AC3 breaks a rule"}]}
        for left in (echoed, bare):
            with self.subTest(left=left["findings"][0]["summary"]):
                result, calls = run(replies={"plan": plan, "plan-revise": plan, "plan-review": self.RULE_FINDING,
                                             "plan-rules-review": left})
                self.assertEqual(result["stage"], "plan-review")
                self.assertNotIn("plan-rules-revise", labels(calls))
                self.assertEqual(result["cont"]["plan"], plan)
                self.assertEqual(result["cont"]["plan_findings"]["rounds"], 0)
                self.assertNotIn("impl-1", labels(calls))

    def test_rules_rereview_finding_without_a_rule_still_blocks(self):
        plan = with_criteria(HUMAN)
        bare = {"verdict": "findings", "findings": [{"severity": "important", "summary": "AC3 breaks a rule"}]}
        result, calls = run(replies={"plan": plan, "plan-revise": plan, "plan-review": self.RULE_FINDING,
                                     "plan-rules-review": bare})
        self.assertEqual(result["stage"], "plan-review")
        self.assertEqual([r["summary"] for r in result["rules"]], ["AC3 breaks a rule"])
        self.assertNotIn("impl-1", labels(calls))
        self.assertNotIn("plan-rules-revise", labels(calls))
        minor = {"verdict": "findings", "findings": [{"severity": "minor", "summary": "style"}]}
        _, calls = run(replies={"plan": plan, "plan-revise": plan, "plan-review": self.RULE_FINDING,
                                "plan-rules-review": minor}, patch={"close-out": {"issue_state": "OPEN"}})
        self.assertIn("impl-1", labels(calls))

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
        self.assertEqual(names[:3], ["setup", "impl-2", "review-2"])
        self.assertIn(RENEW, prompt(calls, "impl-2"))
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
                            patch={"setup": dict(merged(42, "c1"), review_state={"code": "blocked", "plan": "blocked"})})
        self.assertEqual(result["stage"], "done")
        self.assertEqual(labels(calls), ["setup", "hold", "close-out"])

    def test_resume_after_merge_goes_to_close_out(self):
        result, calls = run(args=dict(ARGS, cont=self.cont()), patch={"setup": merged(42, "c1")})
        self.assertEqual(result["stage"], "done")
        self.assertEqual(labels(calls), ["setup", "hold", "close-out"])
        self.assertIn("gh issue close 9", prompt(calls, "close-out"))

    def test_cont_without_plan_plans_again(self):
        _, calls = run(args=dict(ARGS, cont={"setup": self.cont()["setup"], "plan": None, "done": []}))
        self.assertIn("plan", labels(calls))
        # The cont an old child wrote at a plan-review stop: plan dropped, no plan_findings.
        old = {"setup": self.cont()["setup"], "plan": None, "plan_reviewed": False, "done": [], "fix_waves": 0}
        _, calls = run(args=dict(ARGS, cont=old))
        names = labels(calls)
        for label in ("owner-answer", "plan", "plan-review", "impl-1"):
            self.assertIn(label, names)
        self.assertNotIn("plan-rules-revise", names)


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


TWO_IDS = [{"id": "lint", "argv": ["make", "lint"], "cwd": "."}, {"id": "test", "argv": ["make", "test"], "cwd": "."}]
FULL = json.dumps(TWO_IDS, separators=(",", ":"))
LINT_ONLY = json.dumps([TWO_IDS[0]], separators=(",", ":"))
FIXED = "c" * 40
LINT_RED = {"head": SHA, "clean": True, "results": [{"id": "lint", "status": "fail", "summary": "3 whitespace errors"},
                                                   {"id": "test", "status": "pass", "summary": "ok"}]}
LINT_GREEN = {"head": FIXED, "clean": True, "results": [{"id": "lint", "status": "pass", "summary": "ok"}]}
BOTH_GREEN = {"head": FIXED, "clean": True, "results": [{"id": "lint", "status": "pass", "summary": "ok"},
                                                       {"id": "test", "status": "pass", "summary": "ok"}]}
WS_ONLY = {"whitespace_exit": 0, "changed_paths": ["src/a.test.ts"]}
ATTESTED = {"verdict": "pass", "findings": [], "whitespace_insignificant": True,
            "whitespace_evidence": "src/a.test.ts: trailing spaces and blank lines between statements"}
WS_SCENARIO = {"args": dict(ARGS, mode="ready"),
               "replies": {"verify": LINT_RED, "ws-check-1": WS_ONLY, "verify-fix-review-1": ATTESTED,
                           "verify-2": LINT_GREEN},
               "patch": {"setup": {"verification": TWO_IDS}, "verify-fix-1": {"start_head": SHA, "commit": FIXED}}}


class WhitespaceCarryForwardTest(unittest.TestCase):
    """#741: after a whitespace-only verify fix whose whitespace the reviewer attests insignificant, only the ids
    that did not pass re-run and the passes carry forward."""

    @staticmethod
    def scenario(ws, verify2=LINT_GREEN, fix=None, first=LINT_RED, review=ATTESTED, more=None):
        return run(args=dict(ARGS, mode="ready"),
                   replies={"verify": first, "ws-check-1": ws, "verify-fix-review-1": review, "verify-2": verify2,
                            **(more or {})},
                   patch={"setup": {"verification": TWO_IDS},
                          "verify-fix-1": fix or {"start_head": SHA, "commit": FIXED}})

    def assert_full_rerun(self, calls, result):
        self.assertIn(FULL, prompt(calls, "verify-2"))
        self.assertEqual(result["verify"], BOTH_GREEN["results"])

    def test_a_whitespace_only_fix_reruns_only_the_failed_id_and_carries_the_pass(self):
        result, calls = self.scenario(WS_ONLY)
        verify2 = prompt(calls, "verify-2")
        self.assertIn(LINT_ONLY, verify2)
        self.assertNotIn('"id":"test"', verify2)
        self.assertIn("verify-fix-review-1", labels(calls))
        self.assertEqual((result["stage"], result["head"]), ("ready", FIXED))
        self.assertEqual(len(result["verify"]), 2)
        by_id = {r["id"]: r for r in result["verify"]}
        self.assertEqual(by_id["lint"], {"id": "lint", "status": "pass", "summary": "ok"})
        self.assertEqual((by_id["test"]["status"], by_id["test"]["carried_from"]), ("pass", SHA))
        self.assertEqual(result["cont"]["verified"]["head"], FIXED)

    def test_the_ws_check_is_a_clerk_reading_the_fix_range(self):
        _, calls = self.scenario(WS_ONLY)
        check = [c for c in calls if c["label"] == "ws-check-1"]
        self.assertEqual([c["agentType"] for c in check], ["clerk"])
        text = check[0]["prompt"]
        self.assertIn(f"git -C /r/.wt/w-issue-9-x diff -b --ignore-blank-lines --quiet {SHA} {FIXED}\n", text)
        self.assertIn(f"git -C /r/.wt/w-issue-9-x diff --no-renames --name-only {SHA} {FIXED}\n", text)

    def test_only_a_prefiltered_fix_review_must_attest(self):
        _, calls = self.scenario(WS_ONLY)
        schema = schema_of(calls, "verify-fix-review-1")
        for key in ("whitespace_insignificant", "whitespace_evidence"):
            self.assertIn(key, schema["properties"])
            self.assertIn(key, schema["required"])
        self.assertIn("src/a.test.ts", prompt(calls, "verify-fix-review-1"))
        _, plain = self.scenario({"whitespace_exit": 1, "changed_paths": ["src/a.ts"]}, verify2=BOTH_GREEN)
        self.assertNotIn("whitespace_insignificant", schema_of(plain, "verify-fix-review-1")["properties"])
        self.assertEqual([c["agentType"] for c in calls + plain if c["label"] == "verify-fix-review-1"],
                         ["reviewer", "reviewer"])

    def test_a_fix_that_is_not_whitespace_only_reruns_every_id(self):
        cases = {
            "content change": {"whitespace_exit": 1, "changed_paths": ["src/a.ts"]},
            "whitespace-significant path": {"whitespace_exit": 0, "changed_paths": ["src/a.ts", "tools/b.py"]},
            "extensionless path": {"whitespace_exit": 0, "changed_paths": ["Makefile"]},
            "no changed path": {"whitespace_exit": 0, "changed_paths": []},
            "dead ws-check": None,
        }
        for name, ws in cases.items():
            with self.subTest(case=name):
                # The review attests anyway: an attestation the program did not ask for counts for nothing.
                result, calls = self.scenario(ws, verify2=BOTH_GREEN)
                self.assertIn("ws-check-1", labels(calls))
                self.assertIn("verify-fix-review-1", labels(calls))
                self.assert_full_rerun(calls, result)
        # A full re-run that omits test does not inherit its earlier pass.
        result, _ = self.scenario(cases["content change"], more={"verify-3": LINT_GREEN})
        self.assertEqual(result["stage"], "verify")
        self.assertIn("test", [p["id"] for p in result["problems"]])

    def test_whitespace_that_matters_reruns_every_id(self):
        # -b --ignore-blank-lines exits 0 for a doubled space inside a regex literal of an allowed file type.
        regex = {"whitespace_exit": 0, "changed_paths": ["src/match.mjs"]}
        reviews = {
            "regex whitespace": {"verdict": "pass", "findings": [], "whitespace_insignificant": False,
                                 "whitespace_evidence": "src/match.mjs: the hunk doubles a space inside a regex"},
            "blank evidence": dict(ATTESTED, whitespace_evidence="  "),
            "no attestation": {"verdict": "pass", "findings": []},
        }
        for name, review in reviews.items():
            with self.subTest(case=name):
                result, calls = self.scenario(regex, verify2=BOTH_GREEN, review=review)
                self.assertIn("whitespace_insignificant", schema_of(calls, "verify-fix-review-1")["properties"])
                self.assert_full_rerun(calls, result)
                self.assertFalse(any("carried_from" in r for r in result["verify"]))

    def test_no_carry_without_its_preconditions(self):
        cases = {
            "fix starts elsewhere": ({"start_head": "d" * 40, "commit": FIXED}, LINT_RED),
            "dirty first verify": (None, dict(LINT_RED, clean=False)),
            "nothing passed": (None, {"head": SHA, "clean": True,
                                      "results": [{"id": "lint", "status": "fail", "summary": "x"},
                                                  {"id": "test", "status": "fail", "summary": "y"}]}),
            "a missing result": (None, {"head": SHA, "clean": True,
                                        "results": [{"id": "lint", "status": "fail", "summary": "x"}]}),
        }
        for name, (fix, first) in cases.items():
            with self.subTest(case=name):
                result, calls = self.scenario(WS_ONLY, verify2=BOTH_GREEN, fix=fix, first=first)
                self.assertNotIn("ws-check-1", labels(calls))
                self.assertIn("verify-fix-review-1", labels(calls))
                self.assert_full_rerun(calls, result)

    def test_a_narrowed_verify_at_another_head_stops(self):
        moved = dict(LINT_GREEN, head="d" * 40)
        result, calls = self.scenario(WS_ONLY, verify2=moved)
        self.assertEqual(result["stage"], "verify")
        problems = json.dumps(result["problems"])
        self.assertIn("d" * 40, problems)
        self.assertIn(FIXED, problems)
        self.assertNotIn("verify-fix-2", labels(calls))

    def test_a_fresh_result_wins_over_a_carried_pass(self):
        fresh = {"head": FIXED, "clean": True, "results": [{"id": "lint", "status": "pass", "summary": "ok"},
                                                           {"id": "test", "status": "fail", "summary": "test broke"}]}
        result, _ = self.scenario(WS_ONLY, verify2=fresh, more={"verify-fix-2": {"status": "blocked", "notes": "x"}})
        self.assertEqual(result["stage"], "verify-fix")
        self.assertEqual([r for r in result["verify"]["results"] if r["id"] == "test"],
                         [{"id": "test", "status": "fail", "summary": "test broke"}])

    def test_a_second_whitespace_fix_keeps_the_original_carried_from(self):
        again = "e" * 40
        result, calls = run(args=dict(ARGS, mode="ready"),
                            replies={"verify": LINT_RED, "ws-check-1": WS_ONLY, "ws-check-2": WS_ONLY,
                                     "verify-fix-review-1": ATTESTED, "verify-fix-review-2": ATTESTED,
                                     "verify-2": dict(LINT_GREEN, results=[{"id": "lint", "status": "fail",
                                                                            "summary": "1 more"}]),
                                     "verify-3": dict(LINT_GREEN, head=again)},
                            patch={"setup": {"verification": TWO_IDS},
                                   "verify-fix-1": {"start_head": SHA, "commit": FIXED},
                                   "verify-fix-2": {"start_head": FIXED, "commit": again}})
        self.assertEqual((result["stage"], result["head"]), ("ready", again))
        self.assertNotIn('"id":"test"', prompt(calls, "verify-3"))
        by_id = {r["id"]: r for r in result["verify"]}
        self.assertEqual((by_id["test"]["status"], by_id["test"]["carried_from"]), ("pass", SHA))


class ShipTest(unittest.TestCase):
    def test_checks_wait_uses_the_required_names_rule(self):
        _, calls = run()
        checks = prompt(calls, "checks-1")
        self.assertIn("gh api repos/owner/repo/rules/branches/dev", checks)
        self.assertIn("never treat a partial list as green", checks)

    def test_failed_checks_stop_unmerged(self):
        fix = "f" * 40
        result, calls = run(replies={"checks-1": {"state": "failed", "head": SHA},
                                     "checks-2": {"state": "failed", "head": fix}},
                            patch={"fix-ci": {"start_head": SHA, "commit": fix}})
        self.assertEqual(result["stage"], "checks")
        self.assertNotIn("merge", labels(calls))

    def test_clean_sync_rechecks_without_review(self):
        result, calls = run(replies={"checks-1": {"state": "behind", "head": SHA}})
        self.assertEqual(result["stage"], "done")
        names = labels(calls)
        self.assertEqual(names[names.index("checks-1"):], ["checks-1", "sync-1", "checks-2", "merge",
                                                         "land-unlock", "hold", "close-out"])

    def test_conflicted_sync_is_rereviewed(self):
        _, calls = run(replies={"checks-1": {"state": "behind", "head": SHA}},
                       patch={"sync-1": {"conflicted": True, "resolved_files": ["a.py"]}})
        review = [c for c in calls if c["label"] == "sync-review-1"]
        self.assertEqual(review[0]["agentType"], "reviewer")

    def test_conflicted_sync_with_findings_stops(self):
        bad = {"verdict": "findings", "findings": [{"severity": "important", "summary": "lost"}]}
        result, calls = run(replies={"checks-1": {"state": "behind", "head": SHA}, "sync-review-1": bad,
                                     "fix-sync-review-1": bad},
                            patch={"sync-1": {"conflicted": True, "merge_commit": "d" * 40},
                                   "fix-sync-1": {"start_head": "d" * 40, "commit": "f" * 40}})
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

    def test_a_merged_reply_without_notes_still_closes_out(self):
        # The folded merge schema requires only the renew, so a merged PR's reply may carry no notes.
        result, calls = run(replies={"merge": {"merged": True, "merge_commit": "c" * 40}})
        self.assertEqual(result["stage"], "done")
        self.assertIn("close-out", labels(calls))

    def test_a_reply_without_merged_stops_at_merge(self):
        result, calls = run(replies={"merge": {"notes": "unsure"}})
        self.assertEqual(result["stage"], "merge")
        self.assertNotIn("close-out", labels(calls))


class MergeRefusedBehindTest(unittest.TestCase):
    """#662: a merge refused because the integration branch moved syncs and retries, bounded at three refusals."""

    STALE = {"merged": False, "behind": True, "notes": "GraphQL: Head branch is not up to date with the base branch"}

    def test_one_refusal_syncs_then_merges(self):
        merge = "d" * 40
        result, calls = run(replies={"merge": [self.STALE, {"merged": True, "merge_commit": merge, "notes": "merged"}],
                                     "checks-2": {"state": "behind", "head": SHA},
                                     "checks-3": {"state": "passed", "head": merge}},
                            patch={"sync-1": {"merge_commit": merge}})
        self.assertEqual(result["stage"], "done")
        names = labels(calls)
        self.assertEqual(names[names.index("merge"):], [
            "merge", "checks-2", "sync-1", "renew-checks-3", "land-push-3", "land-lock-3",
            "checks-3", "merge", "land-unlock", "hold", "close-out"])
        self.assertIn(f"--match-head-commit {merge}", prompt(calls, "merge"))
        self.assertEqual(result["syncs"], 1)

    def test_three_refusals_stop_at_merge_with_cont(self):
        behind = {"state": "behind", "head": SHA}
        result, calls = run(replies={"merge": self.STALE, "checks-2": behind, "checks-4": behind})
        self.assertEqual(result["stage"], "merge")
        self.assertEqual(labels(calls).count("merge"), 3)
        self.assertEqual([l for l in labels(calls) if l.startswith("sync-")], ["sync-1", "sync-2"])
        self.assertIn("cont", result)
        self.assertNotIn("close-out", labels(calls))

    def test_earlier_syncs_do_not_consume_the_merge_recovery(self):
        m1, m2, m3 = "1" * 40, "2" * 40, "3" * 40
        result, calls = run(replies={"merge": [self.STALE, {"merged": True, "merge_commit": MERGE, "notes": "merged"}],
                                     "checks-1": {"state": "behind", "head": SHA},
                                     "checks-2": {"state": "behind", "head": m1},
                                     "checks-3": {"state": "passed", "head": m2},
                                     "checks-4": {"state": "behind", "head": m2},
                                     "checks-5": {"state": "passed", "head": m3}},
                            patch={"sync-1": {"merge_commit": m1}, "sync-2": {"merge_commit": m2},
                                   "sync-3": {"merge_commit": m3}})
        self.assertEqual(result["stage"], "done")
        self.assertEqual([l for l in labels(calls) if l.startswith("sync-")], ["sync-1", "sync-2", "sync-3"])
        self.assertIn(f"--match-head-commit {m3}", prompt(calls, "merge"))
        self.assertEqual(result["syncs"], 3)

    def test_a_third_pre_merge_behind_is_still_contention_after_a_recovery(self):
        behind = {"state": "behind", "head": SHA}
        result, calls = run(replies={"merge": self.STALE, "checks-2": behind, "checks-3": behind, "checks-4": behind,
                                     "checks-5": behind})
        self.assertEqual(result["stage"], "sync-contention")

    def test_any_other_refusal_stops_at_once(self):
        result, calls = run(replies={"merge": {"merged": False, "behind": False, "notes": "required check pending"}})
        self.assertEqual(result["stage"], "merge")
        self.assertEqual(labels(calls).count("merge"), 1)
        self.assertNotIn("sync-1", labels(calls))
        self.assertIn("cont", result)

    def test_a_refusal_with_no_verdict_stops_at_once(self):
        result, calls = run(replies={"merge": {"merged": False, "notes": "head moved"}})
        self.assertEqual(result["stage"], "merge")
        self.assertEqual(labels(calls).count("merge"), 1)

    def test_merge_prompt_names_the_not_up_to_date_verdict(self):
        _, calls = run()
        self.assertIn("behind", schema_of(calls, "merge")["properties"])
        self.assertIn("not up to date", prompt(calls, "merge"))


FIX = "f" * 40
MERGE = "d" * 40
RED = {"state": "failed", "head": SHA, "failing": ["ci-tests"], "details": "FAIL test_cache: host-installed state"}
FINDING = {"verdict": "findings", "findings": [{"severity": "important", "summary": "dropped the new call site"}]}


class LandLockTest(unittest.TestCase):
    """#677: ship takes the land lock, waiting, before any sync, holds it through the merge,
    and releases it after the merge and on every stop."""

    BEHIND = {"state": "behind", "head": SHA}

    def test_ship_order_is_lock_then_checks_then_merge_then_release(self):
        result, calls = run()
        self.assertEqual(result["stage"], "done")
        names = labels(calls)
        self.assertEqual(names[names.index("pr"):], ["pr", "checks-1", "merge", "land-unlock", "hold", "close-out"])

    def test_lock_commands_are_exact(self):
        _, calls = run()
        self.assertIn(f"forge-claim land acquire --repo owner/repo --branch dev --sha {SHA} --wait\n",
                      prompt(calls, "pr"))
        self.assertIn(f"forge-claim land acquire --repo owner/repo --branch dev --sha {SHA}\n",
                      prompt(calls, "merge"))
        self.assertNotIn(" --wait\n", prompt(calls, "merge"))
        self.assertIn(f"forge-claim land release --repo owner/repo --branch dev --sha {SHA}\n",
                      prompt(calls, "land-unlock"))

    def test_the_lock_is_taken_before_the_sync_merge_and_moved_after_the_push(self):
        merge = "d" * 40
        result, calls = run(replies={"checks-1": self.BEHIND, "checks-2": {"state": "passed", "head": merge}},
                            patch={"sync-1": {"merge_commit": merge}})
        self.assertEqual(result["stage"], "done")
        names = labels(calls)
        self.assertEqual(names[names.index("pr"):], [
            "pr", "checks-1", "sync-1", "renew-checks-2", "land-push-2",
            "land-lock-2", "checks-2", "merge", "land-unlock", "hold", "close-out"])
        self.assertIn("git -C /r/.wt/w-issue-9-x push origin issue-9-x", prompt(calls, "land-push-2"))
        self.assertIn(f"--sha {merge}\n", prompt(calls, "land-lock-2"))
        self.assertNotIn(" --wait\n", prompt(calls, "land-lock-2"))
        self.assertIn(f"forge-claim land release --repo owner/repo --branch dev --sha {merge}",
                      prompt(calls, "land-unlock"))

    def test_a_merge_refused_behind_resyncs_under_the_held_lock(self):
        merge = "d" * 40
        stale = {"merged": False, "behind": True, "notes": "Head branch is not up to date with the base branch"}
        result, calls = run(replies={"merge": [stale, {"merged": True, "merge_commit": merge, "notes": "merged"}],
                                     "checks-2": self.BEHIND, "checks-3": {"state": "passed", "head": merge}},
                            patch={"sync-1": {"merge_commit": merge}})
        self.assertEqual(result["stage"], "done")
        names = labels(calls)
        self.assertEqual(names.count("land-unlock"), 1)
        later_locks = [c["prompt"] for c in calls if c["label"] in ("land-lock-3", "merge")]
        self.assertEqual(len(later_locks), 3)  # the first pre-merge check, the move after the push, the last pre-merge check
        for text in later_locks:
            self.assertNotIn(" --wait\n", text)
        self.assertIn("--wait", prompt(calls, "pr"))
        self.assertLess(names.index("pr"), names.index("sync-1"))
        self.assertLess(names.index("sync-1"), names.index("land-push-3"))
        last_merge = len(names) - 1 - names[::-1].index("merge")
        self.assertLess(last_merge, names.index("land-unlock"))

    def test_a_contended_lock_is_waited_for_by_the_cli(self):
        waited = {"verdict": "acquired", "lock_sha": SHA, "waited_s": 1800, "took_over": "idle"}
        result, calls = run(patch={"pr": {"lock": waited}})
        self.assertEqual(result["stage"], "done")
        names = labels(calls)
        self.assertEqual(names[names.index("pr"):names.index("checks-1")], ["pr"])
        self.assertIn(f"--sha {SHA} --wait\n", prompt(calls, "pr"))

    def test_a_fix_commit_in_short_form_moves_the_lock_by_its_full_sha(self):
        short = FIX[:9]
        result, calls = run(replies={"checks-1": RED, "checks-2": {"state": "passed", "head": FIX, "required": ["ci-tests"]},
                                     "land-push-2": {"head": FIX}},
                            patch={"fix-ci": {"start_head": SHA, "commit": short}})
        self.assertEqual(result["stage"], "done")
        self.assertIn(f"forge-claim land acquire --repo owner/repo --branch dev --sha {FIX}\n", prompt(calls, "land-lock-2"))
        self.assertNotIn(f"--sha {short}\n", prompt(calls, "land-lock-2"))
        self.assertIn(f"forge-claim land release --repo owner/repo --branch dev --sha {FIX}", prompt(calls, "land-unlock"))

    def test_a_non_holding_wait_answer_stops_with_cont(self):
        for verdict in ("land-contended", "held_by", "lost_to"):
            with self.subTest(verdict=verdict):
                result, calls = run(patch={"pr": {"lock": {"verdict": verdict, "lock_sha": "b" * 40, "by": "h2/b9"}}})
                self.assertEqual((result["stage"], result["pr"], result["lock"]), ("land-contended", 42, verdict))
                self.assertIn("cont", result)
                for gone in ("land-lock-2", "checks-1", "sync-1", "merge", "land-unlock", "close-out"):
                    self.assertNotIn(gone, labels(calls))

    def test_a_failed_move_releases_the_last_held_sha(self):
        merge = "d" * 40
        result, calls = run(replies={"checks-1": self.BEHIND,
                                     "land-lock-2": {"verdict": "lost_to", "lock_sha": "c" * 40, "by": "h2/b9"}},
                            patch={"sync-1": {"merge_commit": merge}})
        self.assertEqual(result["stage"], "land-contended")
        self.assertIn("cont", result)
        names = labels(calls)
        self.assertNotIn("checks-2", names)
        self.assertEqual(names.count("land-unlock"), 1)
        self.assertIn(f"forge-claim land release --repo owner/repo --branch dev --sha {SHA}\n",
                      prompt(calls, "land-unlock"))

    def test_a_push_that_lands_another_head_stops_before_the_lock_moves(self):
        merge = "d" * 40
        result, calls = run(replies={"checks-1": self.BEHIND, "land-push-2": {"head": "c" * 40}},
                            patch={"sync-1": {"merge_commit": merge}})
        self.assertEqual((result["stage"], result["pr"], result["expected"]), ("head-moved", 42, merge))
        names = labels(calls)
        self.assertNotIn("land-lock-2", names)
        self.assertEqual(names.count("land-unlock"), 1)
        self.assertIn(f"--sha {SHA}\n", prompt(calls, "land-unlock"))

    def test_a_failed_release_is_reported_and_keeps_the_result(self):
        result, calls = run(replies={"merge": {"merged": False, "notes": "head moved"}, "land-unlock": None})
        self.assertEqual(result["stage"], "merge")
        self.assertIn("cont", result)
        self.assertEqual(result["lock_unreleased"]["sha"], SHA)
        self.assertIn("land-unlock", result["dead_agents"])
        result, calls = run(replies={"land-unlock": None})
        self.assertEqual(result["stage"], "done")
        self.assertEqual(result["lock_unreleased"]["sha"], SHA)
        self.assertIn("close-out", labels(calls))
        result, _ = run()
        self.assertNotIn("lock_unreleased", result)

    def test_an_unanswered_folded_lock_stops_with_a_release_at_the_pr_head(self):
        # The folded lock may have been taken before its reply was lost, so the stop releases the verified head once.
        result, calls = run(patch={"pr": {"lock": None}})
        self.assertEqual(result["stage"], "land-lock")
        self.assertIn("cont", result)
        self.assertEqual(labels(calls).count("land-unlock"), 1)
        self.assertIn(f"--sha {SHA}\n", prompt(calls, "land-unlock"))

    def test_every_stop_after_the_lock_releases_it(self):
        fix = "f" * 40
        cases = {
            "checks": {"replies": {"checks-1": {"state": "failed", "head": SHA},
                                   "checks-2": {"state": "failed", "head": fix}},
                       "patch": {"fix-ci": {"start_head": SHA, "commit": fix}}},
            "checks-pending": {"replies": {f"checks-{k}": {"state": "pending", "head": SHA, "pending": ["e2e"]}
                                           for k in (1, 2, 3)}},
            "head-moved": {"patch": {"checks-1": {"head": "c" * 40}}},
            "merge": {"replies": {"merge": {"merged": False, "notes": "head moved"}}},
            "sync-contention": {"replies": {"checks-1": self.BEHIND, "checks-2": self.BEHIND,
                                            "checks-3": self.BEHIND}},
            "land-contended": {"replies": {"checks-1": self.BEHIND, "land-lock-2": {"verdict": "lost_to", "lock_sha": "b" * 40}},
                               "patch": {"sync-1": {"merge_commit": "d" * 40}}},
        }
        for stage, scenario in cases.items():
            with self.subTest(stage=stage):
                result, calls = run(**scenario)
                self.assertEqual(result["stage"], stage)
                self.assertIn("cont", result)
                names = labels(calls)
                self.assertEqual(names.count("land-unlock"), 1)
                self.assertLess(names.index("pr"), names.index("land-unlock"))
                self.assertNotIn("close-out", names)

    def test_a_lost_claim_after_the_lock_releases_it(self):
        result, calls = run(patch={"checks-1": {"renew": {"verdict": "not_held", "by": "h2/b9"}}})
        self.assertEqual(result["stage"], "claim-lost")
        self.assertEqual(labels(calls).count("land-unlock"), 1)
        self.assertNotIn("merge", labels(calls))

    def test_a_lock_retaken_before_the_merge_rechecks_first(self):
        retaken = {"merged": False, "notes": "retaken", "lock": {"verdict": "acquired", "lock_sha": SHA}}
        result, calls = run(replies={"merge": [retaken, {"merged": True, "merge_commit": SHA, "notes": "merged"}]})
        self.assertEqual(result["stage"], "done")
        names = labels(calls)
        self.assertLess(names.index("merge"), names.index("checks-2"))
        self.assertLess(names.index("checks-2"), len(names) - 1 - names[::-1].index("merge"))
        result, calls = run(replies={"merge": [retaken, retaken]})
        self.assertEqual(result["stage"], "land-contended")
        self.assertEqual(labels(calls).count("merge"), 2)
        self.assertEqual(labels(calls).count("land-unlock"), 1)

    def test_a_stop_before_any_lock_command_takes_none(self):
        # The nested renew ended, so the prompt ran nothing after it; a refused lock holds nothing either.
        _, calls = run(patch={"pr": {"renew": {"verdict": "not_held", "by": "h2/b1"}}})
        self.assertNotIn("land-unlock", labels(calls))
        result, calls = run(patch={"pr": {"head": "c" * 40, "lock": {"verdict": "held_by", "by": "h2/b9"}}})
        self.assertEqual(result["stage"], "head-moved")
        self.assertNotIn("land-unlock", labels(calls))


class ShipFixWaveTest(unittest.TestCase):
    """#649 defect 2 and the sync-review decision: one bounded fix wave, then a stop with cont."""

    def red_then(self, second, **patch):
        return run(replies={"checks-1": RED, "checks-2": second},
                   patch=dict({"fix-ci": {"start_head": SHA, "commit": FIX}}, **patch))

    def test_failed_check_runs_one_fix_wave_then_merges(self):
        result, calls = self.red_then({"state": "passed", "head": FIX, "required": ["ci-tests"]})
        self.assertEqual(result["stage"], "done")
        names = labels(calls)
        self.assertEqual(names[names.index("checks-1"):], [
            "checks-1", "fix-ci", "fix-ci-review", "renew-checks-2", "land-push-2", "land-lock-2", "checks-2",
            "merge", "land-unlock", "hold", "close-out"])
        fix = prompt(calls, "fix-ci")
        for needle in ("ci-tests", "FAIL test_cache: host-installed state", "regression test"):
            self.assertIn(needle, fix)
        self.assertEqual([c["agentType"] for c in calls if c["label"] == "fix-ci"], ["implementer"])
        self.assertEqual([c["agentType"] for c in calls if c["label"] == "fix-ci-review"], ["reviewer"])
        self.assertIn(f"diff {SHA}..{FIX}", prompt(calls, "fix-ci-review"))
        self.assertIn(f"--match-head-commit {FIX}", prompt(calls, "merge"))

    def test_a_second_failure_stops_with_cont(self):
        result, calls = self.red_then(dict(RED, head=FIX))
        self.assertEqual(result["stage"], "checks")
        self.assertEqual(result["cont"]["checks_fixes"], 1)
        self.assertEqual(labels(calls).count("fix-ci"), 1)
        self.assertNotIn("merge", labels(calls))

    def test_a_resume_with_the_wave_spent_stops_at_the_first_failure(self):
        stopped, _ = self.red_then(dict(RED, head=FIX))
        result, calls = run(args=dict(ARGS, cont=stopped["cont"]), replies={"checks-1": RED})
        self.assertEqual(result["stage"], "checks")
        self.assertNotIn("fix-ci", labels(calls))

    def test_failed_or_unreviewed_fix_stops(self):
        cases = {
            "checks-fix": ({}, {"fix-ci": {"status": "blocked", "notes": "no"}}),
            "checks-fix ": ({}, {"fix-ci": {"start_head": SHA, "commit": SHA}}),
            "checks-fix-review": ({"fix-ci-review": FINDING}, {}),
            "checks-fix-review ": ({"fix-ci-review": None}, {}),
        }
        for stage, (replies, patch) in cases.items():
            with self.subTest(case=stage):
                result, calls = run(replies=dict({"checks-1": RED}, **replies),
                                    patch=dict({"fix-ci": {"start_head": SHA, "commit": FIX}}, **patch))
                self.assertEqual(result["stage"], stage.strip())
                self.assertIn("cont", result)
                self.assertNotIn("merge", labels(calls))

    def test_failed_check_on_another_head_is_head_moved_not_fixed(self):
        result, calls = run(replies={"checks-1": dict(RED, head="c" * 40)})
        self.assertEqual(result["stage"], "head-moved")
        self.assertNotIn("fix-ci", labels(calls))

    def test_checks_prompt_asks_for_failing_names_and_the_log_tail(self):
        _, calls = run()
        checks = prompt(calls, "checks-1")
        self.assertIn("failing", checks)
        self.assertIn("--log-failed", checks)

    def test_sync_review_finding_gets_one_fix_wave_then_merges(self):
        result, calls = run(replies={"checks-1": {"state": "behind", "head": SHA}, "sync-review-1": FINDING,
                                     "checks-2": {"state": "passed", "head": FIX, "required": ["ci-tests"]}},
                            patch={"sync-1": {"conflicted": True, "merge_commit": MERGE, "resolved_files": ["a.py"]},
                                   "fix-sync-1": {"start_head": MERGE, "commit": FIX}})
        self.assertEqual(result["stage"], "done")
        names = labels(calls)
        self.assertEqual(names[names.index("sync-1"):names.index("checks-2")],
                         ["sync-1", "sync-review-1", "fix-sync-1", "fix-sync-review-1", "renew-checks-2",
                          "land-push-2", "land-lock-2"])
        fix = prompt(calls, "fix-sync-1")
        self.assertIn(MERGE, fix)
        self.assertIn("dropped the new call site", fix)
        self.assertEqual([c["agentType"] for c in calls if c["label"] == "fix-sync-review-1"], ["reviewer"])
        self.assertIn(f"diff {MERGE}..{FIX}", prompt(calls, "fix-sync-review-1"))
        self.assertIn(f"--match-head-commit {FIX}", prompt(calls, "merge"))

    def test_failed_sync_fix_stops(self):
        result, calls = run(replies={"checks-1": {"state": "behind", "head": SHA}, "sync-review-1": FINDING},
                            patch={"sync-1": {"conflicted": True, "merge_commit": MERGE},
                                   "fix-sync-1": {"status": "blocked", "notes": "no"}})
        self.assertEqual(result["stage"], "sync-fix")
        self.assertNotIn("merge", labels(calls))

    def test_a_second_sync_review_finding_stops_without_a_second_wave(self):
        result, calls = run(replies={"checks-1": {"state": "behind", "head": SHA}, "sync-review-1": FINDING,
                                     "checks-2": {"state": "behind", "head": FIX}, "sync-review-2": FINDING},
                            patch={"sync-1": {"conflicted": True, "merge_commit": MERGE},
                                   "fix-sync-1": {"start_head": MERGE, "commit": FIX},
                                   "sync-2": {"conflicted": True, "merge_commit": "e" * 40}})
        self.assertEqual(result["stage"], "sync-review")
        self.assertEqual(result["cont"]["sync_fixes"], 1)
        self.assertNotIn("fix-sync-2", labels(calls))
        self.assertNotIn("merge", labels(calls))

    def test_a_fix_that_starts_from_another_head_stops_before_review(self):
        other = "c" * 40
        result, calls = run(replies={"checks-1": RED}, patch={"fix-ci": {"start_head": other, "commit": FIX}})
        self.assertEqual(result["stage"], "checks-fix")
        self.assertNotIn("fix-ci-review", labels(calls))
        self.assertNotIn("merge", labels(calls))
        result, calls = run(replies={"checks-1": {"state": "behind", "head": SHA}, "sync-review-1": FINDING},
                            patch={"sync-1": {"conflicted": True, "merge_commit": MERGE},
                                   "fix-sync-1": {"start_head": other, "commit": FIX}})
        self.assertEqual(result["stage"], "sync-fix")
        self.assertNotIn("fix-sync-review-1", labels(calls))
        self.assertNotIn("merge", labels(calls))

    def test_a_fix_start_head_in_short_form_is_the_same_head(self):
        result, calls = self.red_then({"state": "passed", "head": FIX, "required": ["ci-tests"]},
                                      **{"fix-ci": {"start_head": SHA[:9], "commit": FIX}})
        self.assertEqual(result["stage"], "done")
        self.assertIn("fix-ci-review", labels(calls))

    def sync_rebuttal(self, review=None, **fix):
        replies = {"checks-1": {"state": "behind", "head": SHA}, "sync-review-1": FINDING,
                   "checks-2": {"state": "passed", "head": MERGE, "required": ["ci-tests"]}}
        replies.update(review or {})
        return run(replies=replies,
                   patch={"sync-1": {"conflicted": True, "merge_commit": MERGE},
                          "fix-sync-1": dict({"start_head": MERGE, "commit": MERGE, "notes": "the call site is on line 12"}, **fix)})

    def test_a_sync_rebuttal_with_evidence_and_no_commit_is_adjudicated_by_the_reviewer(self):
        result, calls = self.sync_rebuttal()
        self.assertEqual(result["stage"], "done")
        self.assertIn("fix-sync-review-1", labels(calls))
        review = prompt(calls, "fix-sync-review-1")
        self.assertIn("the call site is on line 12", review)
        self.assertIn("rebuttal", review)
        self.assertNotIn(f"diff {MERGE}..{MERGE}", review)
        self.assertIn(f"--match-head-commit {MERGE}", prompt(calls, "merge"))

    def test_a_sync_rebuttal_the_reviewer_rejects_stops_at_sync_review(self):
        result, calls = self.sync_rebuttal(review={"fix-sync-review-1": FINDING})
        self.assertEqual(result["stage"], "sync-review")
        self.assertNotIn("merge", labels(calls))

    def test_a_sync_rebuttal_without_notes_stops_at_sync_fix(self):
        result, calls = self.sync_rebuttal(notes="")
        self.assertEqual(result["stage"], "sync-fix")
        self.assertNotIn("fix-sync-review-1", labels(calls))

    def test_no_fix_wave_keeps_the_cont_shape(self):
        result, _ = run(replies={"checks-1": {"state": "behind", "head": SHA}, "sync-1": None})
        self.assertEqual(result["stage"], "sync")
        self.assertNotIn("checks_fixes", result["cont"])
        self.assertNotIn("sync_fixes", result["cont"])


class AllChecksTest(unittest.TestCase):
    """#756: the checks step waits for every check on head, required or not."""

    def test_checks_step_lists_every_check_and_can_answer_pending(self):
        _, calls = run()
        checks = prompt(calls, "checks-1")
        for argv in ("gh pr checks 42 --repo owner/repo --json name,bucket,link",
                     "gh api repos/owner/repo/rules/branches/dev"):
            self.assertIn(argv, checks)
        schema = schema_of(calls, "checks-1")
        self.assertIn("pending", schema["properties"])
        self.assertIn("pending", schema["properties"]["state"]["enum"])

    def test_a_pending_non_required_check_is_waited_for_before_the_merge(self):  # AC1
        waiting = {"state": "passed", "head": SHA, "required": ["lint"], "passed": ["lint"], "pending": ["e2e"]}
        green = {"state": "passed", "head": SHA, "required": ["lint"], "passed": ["lint", "e2e"]}
        result, calls = run(replies={"checks-1": waiting, "checks-2": green})
        self.assertEqual(result["stage"], "done")
        names = labels(calls)
        self.assertEqual(names[names.index("checks-1"):],
                         ["checks-1", "checks-2", "merge", "land-unlock", "hold", "close-out"])

    def test_a_pending_state_is_waited_for_and_never_synced(self):
        result, calls = run(replies={"checks-1": {"state": "pending", "head": SHA, "pending": ["e2e"]}})
        self.assertEqual(result["stage"], "done")
        names = labels(calls)
        self.assertNotIn("sync-1", names)
        self.assertLess(names.index("checks-2"), names.index("merge"))

    def test_checks_still_pending_after_three_waits_stop_unmerged(self):  # AC1
        waiting = {"state": "pending", "head": SHA, "pending": ["e2e"]}
        result, calls = run(replies={f"checks-{k}": waiting for k in (1, 2, 3)})
        self.assertEqual((result["stage"], result["pending"]), ("checks-pending", ["e2e"]))
        self.assertIn("cont", result)
        names = labels(calls)
        self.assertNotIn("merge", names)
        self.assertNotIn("checks-4", names)
        self.assertEqual(names.count("land-unlock"), 1)

    def test_a_failing_non_required_check_stops_the_merge_named(self):  # AC2
        red = {"state": "passed", "head": SHA, "required": ["lint"], "passed": ["lint"], "failing": ["e2e"],
               "details": "e2e: 2 failed"}
        result, calls = run(replies={"checks-1": red, "checks-2": dict(red, head=FIX)},
                            patch={"fix-ci": {"start_head": SHA, "commit": FIX}})
        self.assertEqual((result["stage"], result["failing"]), ("checks", ["e2e"]))
        self.assertNotIn("merge", labels(calls))
        self.assertIn("e2e", prompt(calls, "fix-ci"))

    def test_an_explicit_failed_state_outranks_a_pending_list(self):  # AC2
        red = {"state": "failed", "head": SHA, "pending": ["slow"], "details": "e2e failed"}
        result, calls = run(replies={"checks-1": red, "checks-2": dict(red, head=FIX)},
                            patch={"fix-ci": {"start_head": SHA, "commit": FIX}})
        self.assertEqual(result["stage"], "checks")
        self.assertEqual(result["checks"]["details"], "e2e failed")
        self.assertIn("e2e failed", prompt(calls, "fix-ci"))
        self.assertNotIn("checks-3", labels(calls))
        self.assertNotIn("merge", labels(calls))


class ShaNormalisationTest(unittest.TestCase):
    """#649 defect 1: a head reported in short form is the same head; a different head still stops."""

    def test_short_checks_head_is_accepted_and_the_merge_uses_the_full_sha(self):
        for short in (SHA[:7], SHA[:12], SHA.upper()[:10], f" {SHA[:9]}\n"):
            with self.subTest(short=short):
                result, calls = run(patch={"checks-1": {"head": short}})
                self.assertEqual(result["stage"], "done")
                self.assertIn(f"--match-head-commit {SHA}", prompt(calls, "merge"))

    def test_short_pr_head_is_accepted(self):
        result, calls = run(patch={"pr": {"head": SHA[:8]}})
        self.assertEqual(result["stage"], "done")
        self.assertIn("checks-1", labels(calls))

    def test_a_different_or_too_short_head_still_stops(self):
        for head in ("c" * 40, "c" * 8, SHA[:6], "", "zzzzzzzzzz"):
            with self.subTest(head=head):
                result, calls = run(patch={"checks-1": {"head": head}})
                self.assertEqual(result["stage"], "head-moved")
                self.assertNotIn("merge", labels(calls))
                result, calls = run(patch={"pr": {"head": head}})
                self.assertEqual(result["stage"], "head-moved")
                self.assertNotIn("checks-1", labels(calls))

    def test_head_fields_require_a_full_sha_in_the_schema(self):
        _, calls = run(replies={"checks-1": {"state": "behind", "head": SHA}})
        for label, field in (("pr", "head"), ("checks-1", "head"), ("verify", "head"), ("sync-1", "merge_commit")):
            with self.subTest(label=label):
                self.assertEqual(schema_of(calls, label)["properties"][field]["pattern"], "^[0-9a-f]{40}$")

    def test_ready_cont_resumed_on_the_short_form_of_its_head_skips_review_and_verify(self):
        ready, _ = run(args=dict(ARGS, mode="ready"))
        result, calls = run(args=dict(ARGS, cont=ready["cont"]), patch={"setup": {"head": SHA[:9]}})
        self.assertEqual(result["stage"], "done")
        self.assertNotIn("final-1", labels(calls))
        self.assertNotIn("verify", labels(calls))

    def test_a_legacy_abbreviated_verify_cache_keeps_the_full_pr_sha(self):
        ready, _ = run(args=dict(ARGS, mode="ready"))
        cont = dict(ready["cont"], verified=dict(ready["cont"]["verified"], head=SHA[:9]))
        result, calls = run(args=dict(ARGS, cont=cont), patch={"setup": {"head": SHA}, "checks-1": {"head": SHA[:8]}})
        self.assertEqual(result["stage"], "done")
        self.assertNotIn("verify", labels(calls))
        self.assertIn(f"--match-head-commit {SHA} ", prompt(calls, "merge") + " ")
        other = SHA[:9] + "0" * 31
        result, calls = run(args=dict(ARGS, cont=cont), patch={"setup": {"head": SHA}, "checks-1": {"head": other}})
        self.assertEqual(result["stage"], "head-moved")
        self.assertEqual(result["expected"], SHA)
        self.assertNotIn("merge", labels(calls))

    def test_a_full_checks_head_replaces_an_abbreviated_expected_head(self):
        ready, _ = run(args=dict(ARGS, mode="ready"))
        cont = dict(ready["cont"], verified=dict(ready["cont"]["verified"], head=SHA[:9]))
        result, calls = run(args=dict(ARGS, cont=cont),
                            patch={"setup": {"head": SHA}, "pr": {"head": SHA[:8]}})
        self.assertEqual(result["stage"], "done")
        self.assertIn(f"--match-head-commit {SHA} ", prompt(calls, "merge") + " ")

    def test_direct_resume_on_the_short_form_of_the_reviewed_head_skips_the_review(self):
        stopped, _ = run(args=dict(ARGS, lane="direct"), replies={"verify": None},
                         patch={"direct-impl": {"commit": SHA}})
        self.assertEqual(stopped["cont"]["done"][0]["reviewed_head"], SHA)
        result, calls = run(args=dict(ARGS, cont=stopped["cont"]), patch={"setup": {"head": SHA[:10]}})
        self.assertEqual(result["stage"], "done")
        self.assertNotIn("direct-review", labels(calls))


class HoldTest(unittest.TestCase):
    """#634 AC2 and AC3: ship regrades, holds only on a lint-accepted block, runs verify-pending once, splits blocking human rows."""

    MERGE = "d" * 40
    HOLD = {"merge_commit_local": True, "code_unmet": [], "blocks": [], "split": [],
            "block": {"v": 1, "merge": "d" * 40, "checks": []}, "lint": {"ok": True, "errors": []},
            "verify_run": {"ran": True, "exit": 0}, "issue_state": "OPEN", "notes": "n"}
    CHILD = {"ac": "AC3", "issue": 50, "block": {"v": 1, "merge": "d" * 40, "checks": [{"ac": "AC3", "kind": "human"}]},
             "lint": {"ok": True, "errors": []}, "verify_run": {"ran": True, "exit": 0}, "issue_state": "OPEN"}

    def ship(self, *criteria, hold=None, close="OPEN", **patch):
        replies = {"plan": with_criteria(*criteria)}
        if hold is not None:
            moved = [x["ac"] for x in hold.get("split", [])]
            covering = {"v": 1, "merge": self.MERGE, "checks": [{"ac": c["id"], "kind": c["kind"]} for c in criteria
                                                                if c["id"] not in moved]}
            replies["hold"] = dict(self.HOLD, **dict({"block": covering}, **hold))
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
        self.assertNotIn("gh issue create", hold)
        split = hold[hold.index("(forge-issue create --repo owner/repo"):]
        self.assertNotIn("--block", split[:split.index(")")])  # the split issue carries no edge (R7)

    def test_every_ruled_step_files_issues_through_forge_issue(self):
        """#697 D11: an issue a plan's task declares is filed by forge-issue with native edges."""
        _, calls = self.ship(EVIDENCE)
        _, direct = run(args=dict(ARGS, lane="direct"))
        for found, label in ((calls, "plan"), (calls, "impl-1"), (calls, "hold"), (direct, "direct-impl")):
            with self.subTest(label=label):
                text = prompt(found, label)
                for argv in ("forge-issue create", "--blocked-by <n>", "--blocks <n>", "forge-issue link"):
                    self.assertIn(argv, text)

    def test_passing_verify_run_closes_instead_of_holding(self):
        result, _ = self.ship(EVIDENCE, hold={"issue_state": "CLOSED"}, close="CLOSED")
        self.assertEqual(result["stage"], "done")
        self.assertEqual(result["close_out"]["issue_state"], "CLOSED")
        result, _ = self.ship(EVIDENCE, hold={"issue_state": "CLOSED"}, close="OPEN")
        self.assertEqual((result["stage"], result["expected_issue_state"]), ("close-out", "CLOSED"))

    def test_close_out_runs_when_the_once_run_closes_the_issue(self):
        """#760 AC1: the hold posts a block, the single verify run closes the issue, and close-out still runs."""
        result, calls = self.ship(EVIDENCE, hold={"issue_state": "CLOSED"}, close="CLOSED")
        self.assertEqual(result["stage"], "done")
        self.assertEqual(labels(calls)[-2:], ["hold", "close-out"])
        close_out = prompt(calls, "close-out")
        self.assertIn("git -C /r worktree remove /r/.wt/w-issue-9-x", close_out)
        self.assertIn("forge-claim release --repo owner/repo --issue 9 --holder", close_out)
        self.assertEqual(prompt(calls, "hold").count("verify-pending run --host h1 --repo owner/repo --issue 9"), 1)

    def test_close_out_runs_when_the_issue_is_already_closed_at_hold_time(self):
        """#760 AC2: an issue closed before the hold posts nothing and runs nothing, and close-out still runs."""
        already = {"issue_state": "CLOSED", "already_closed": True, "block": None, "lint": None, "verify_run": None}
        result, calls = self.ship(EVIDENCE, hold=already, close="CLOSED")
        self.assertEqual(result["stage"], "done")
        self.assertEqual(labels(calls)[-2:], ["hold", "close-out"])
        close_out = prompt(calls, "close-out")
        self.assertIn("git -C /r worktree remove /r/.wt/w-issue-9-x", close_out)
        self.assertIn("forge-claim release --repo owner/repo --issue 9 --holder", close_out)
        self.assertIn("return already_closed true and issue_state CLOSED", prompt(calls, "hold"))
        result, calls = self.ship(HUMAN, hold=already, close="CLOSED")
        self.assertEqual(result["stage"], "done")

    def test_closed_at_hold_time_still_checks_a_split_child(self):
        child = dict(self.CHILD, verify_run={"ran": False, "exit": 0})
        hold = {"issue_state": "CLOSED", "already_closed": True, "blocks": [12], "split": [child]}
        result, calls = self.ship(HUMAN, hold=hold, close="CLOSED")
        self.assertEqual((result["stage"], result["bad_split"]), ("hold", ["AC3"]))
        self.assertNotIn("close-out", labels(calls))
        result, calls = self.ship(HUMAN, hold=dict(hold, split=[]), close="CLOSED")
        self.assertEqual((result["stage"], result["missing_split"]), ("hold", ["AC3"]))
        self.assertNotIn("close-out", labels(calls))
        result, _ = self.ship(HUMAN, hold=dict(hold, split=[self.CHILD]), close="CLOSED")
        self.assertEqual(result["stage"], "done")

    def test_the_hold_prompt_recovers_split_children_when_the_issue_is_already_closed(self):
        """#760 R2: a resume that finds the parent closed still reads the blocked issues and the split children."""
        _, calls = self.ship(HUMAN, hold={"issue_state": "CLOSED", "already_closed": True, "blocks": [], "split": []})
        hold = prompt(calls, "hold")
        self.assertIn("steps 4 and 5 still apply", hold)
        self.assertLess(hold.index("steps 4 and 5 still apply"), hold.index("4. Read the issues this one blocks"))

    def test_a_once_run_close_still_validates_the_hold_evidence(self):
        """#760 R1: CLOSED after this attempt's own run is not already_closed: an uncovered criterion still stops."""
        partial = {"v": 1, "merge": self.MERGE, "checks": [{"ac": "AC2", "kind": "evidence"}]}
        for flag in ({}, {"already_closed": False}):
            with self.subTest(flag=flag):
                result, calls = self.ship(EVIDENCE, HUMAN, hold=dict({"issue_state": "CLOSED", "block": partial}, **flag),
                                          close="CLOSED")
                self.assertEqual((result["stage"], result["missing_checks"]), ("hold", ["AC3"]))
                self.assertNotIn("close-out", labels(calls))
        result, calls = self.ship(EVIDENCE, hold={"issue_state": "CLOSED", "lint": None, "verify_run": None},
                                  close="CLOSED")
        self.assertEqual(result["stage"], "hold")
        self.assertNotIn("close-out", labels(calls))

    def test_closed_at_hold_time_still_needs_the_merge_and_the_code_rows(self):
        already = {"issue_state": "CLOSED", "already_closed": True, "block": None, "lint": None, "verify_run": None}
        for bad, stage in (({"merge_commit_local": False}, "hold"), ({"code_unmet": ["AC1"]}, "code-unmet")):
            with self.subTest(bad=bad):
                result, calls = self.ship(EVIDENCE, hold=dict(already, **bad), close="CLOSED")
                self.assertEqual(result["stage"], stage)
                self.assertNotIn("close-out", labels(calls))

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
        self.assertEqual(labels(calls)[-3:], ["land-unlock", "hold", "close-out"])
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

    def test_hold_block_that_leaves_a_remaining_criterion_unchecked_stops(self):
        block = {"v": 1, "merge": self.MERGE, "checks": [{"ac": "AC2", "kind": "evidence"}]}
        result, calls = self.ship(EVIDENCE, HUMAN, hold={"block": block}, close="CLOSED")
        self.assertEqual((result["stage"], result["missing_checks"]), ("hold", ["AC3"]))
        self.assertNotIn("close-out", labels(calls))
        covering = {"v": 1, "merge": self.MERGE, "checks": [{"ac": "AC2", "kind": "evidence"}, {"ac": "AC3", "kind": "human"}]}
        result, _ = self.ship(EVIDENCE, HUMAN, hold={"block": covering})
        self.assertEqual(result["stage"], "done")

    def test_split_child_block_that_does_not_check_its_criterion_stops(self):
        child = dict(self.CHILD, block={"v": 1, "merge": self.MERGE, "checks": [{"ac": "AC2", "kind": "evidence"}]})
        result, calls = self.ship(HUMAN, hold={"blocks": [12], "split": [child], "issue_state": "CLOSED"}, close="CLOSED")
        self.assertEqual((result["stage"], result["bad_split"]), ("hold", ["AC3"]))
        self.assertNotIn("close-out", labels(calls))

    def test_resume_after_merge_holds_before_close_out(self):
        cont = {"setup": {"ok": True, "worktree": "/r/.wt/w-issue-9-x", "branch": "issue-9-x", "plan_dir": "/g",
                          "holder": HOLDER, "base_sha": SHA},
                "plan": with_criteria(EVIDENCE), "plan_reviewed": True, "done": [{"n": 1, "commit": "c0ffee"}]}
        result, calls = run(args=dict(ARGS, cont=cont), patch={"setup": merged(42, "c0ffee"),
                                                               "close-out": {"issue_state": "OPEN"}})
        self.assertEqual(result["stage"], "done")
        self.assertEqual(labels(calls), ["setup", "hold", "close-out"])
        hold = prompt(calls, "hold")
        self.assertIn("gh pr view 42 --repo owner/repo --json mergeCommit,headRefOid", hold)
        self.assertLess(hold.index("git -C /r fetch origin"), hold.index("verify-pending lint --input"))


    def test_resume_hold_prompt_asks_for_lint_and_the_once_run(self):
        # A retry must still return fresh lint and verify_run, so the prompt names both commands and the result is graded on them.
        cont = {"setup": {"ok": True, "worktree": "/r/.wt/w-issue-9-x", "branch": "issue-9-x", "plan_dir": "/g",
                          "holder": HOLDER, "base_sha": SHA},
                "plan": with_criteria(EVIDENCE), "plan_reviewed": True, "done": [{"n": 1, "commit": "c0ffee"}]}
        result, calls = run(args=dict(ARGS, cont=cont), patch={"setup": merged(42, "c0ffee"), "close-out": {"issue_state": "OPEN"}})
        hold = prompt(calls, "hold")
        self.assertIn("verify-pending lint --input", hold)
        self.assertEqual(hold.count("verify-pending run --host h1 --repo owner/repo --issue 9"), 1)
        self.assertEqual(result["stage"], "done")
        stale = {"lint": {"ok": False, "errors": [{"code": "unverified_reference"}]}}
        result, _ = run(args=dict(ARGS, cont=cont), replies={"hold": dict(self.HOLD, **stale)},
                        patch={"setup": merged(42, "c0ffee")})
        self.assertEqual(result["stage"], "hold")


class NoteCloseOutTest(unittest.TestCase):
    """#736 AC2: a note is never held, and the close-out comment lists the note texts."""

    MERGE = "d" * 40

    def ship(self, *criteria, hold=None, **patch):
        replies = {"plan": with_criteria(*criteria)}
        if hold is not None:
            replies["hold"] = hold
        return run(replies=replies, patch=dict({"merge": {"merge_commit": self.MERGE},
                                                "close-out": {"notes_posted": True}}, **patch))

    def test_the_close_out_comment_lists_the_note_texts(self):
        result, calls = self.ship(NOTE)
        self.assertEqual(result["stage"], "done")
        close = prompt(calls, "close-out")
        self.assertIn(NOTE["text"], close)
        self.assertIn("Orchestrator notes for PR 42", close)
        self.assertIn("gh issue comment 9 --repo owner/repo --body-file", close)
        self.assertLess(close.index("Orchestrator notes for PR 42"), close.index("gh issue close 9 --repo owner/repo"))
        self.assertIn("Every criterion is of kind code or note: post nothing, add no label", prompt(calls, "hold"))
        self.assertIn("never regraded, held or checked", prompt(calls, "hold"))

    def test_a_code_and_note_plan_closes_like_an_all_code_plan(self):
        result, calls = self.ship(NOTE, setup={"integration_branch": "main"})
        self.assertEqual(result["stage"], "done")
        self.assertIn("Closes #9", prompt(calls, "pr"))
        self.assertNotIn("needs-verification", prompt(calls, "close-out"))

    def test_unposted_notes_stop_the_close_out(self):
        result, _ = self.ship(NOTE, **{"close-out": {"notes_posted": False}})
        self.assertEqual((result["stage"], result["expected_issue_state"]), ("close-out", "CLOSED"))

    def test_a_plan_without_notes_has_no_notes_step(self):
        _, calls = run()
        self.assertNotIn("Orchestrator notes", prompt(calls, "close-out"))

    def test_a_note_beside_evidence_is_neither_checked_nor_missing(self):
        hold = {"merge_commit_local": True, "code_unmet": [], "blocks": [], "split": [],
                "block": {"v": 1, "merge": self.MERGE, "checks": [{"ac": "AC2", "kind": "evidence"}]},
                "lint": {"ok": True, "errors": []}, "verify_run": {"ran": True, "exit": 0},
                "issue_state": "OPEN", "notes": "n"}
        result, calls = self.ship(EVIDENCE, NOTE, hold=hold,
                                  **{"close-out": {"issue_state": "OPEN", "notes_posted": True}})
        self.assertEqual(result["stage"], "done")
        self.assertIn("(evidence or human, not split)", prompt(calls, "hold"))
        close = prompt(calls, "close-out")
        self.assertIn(NOTE["text"], close)
        self.assertNotIn("gh issue close", close)

    def test_a_hold_that_checks_a_note_stops(self):
        """#736 DR-001: a note is never held, so a hold block or split child that checks one is refused."""
        both = {"v": 1, "merge": self.MERGE, "checks": [{"ac": "AC2", "kind": "evidence"}, {"ac": "AC4", "kind": "note"}]}
        result, calls = self.ship(EVIDENCE, NOTE, hold=dict(HoldTest.HOLD, block=both),
                                  **{"close-out": {"issue_state": "OPEN", "notes_posted": True}})
        self.assertEqual((result["stage"], result["note_checks"]), ("hold", ["AC4"]))
        self.assertNotIn("close-out", labels(calls))
        note_child = dict(HoldTest.CHILD, ac="AC4", block={"v": 1, "merge": self.MERGE, "checks": [{"ac": "AC4", "kind": "note"}]})
        result, calls = self.ship(HUMAN, NOTE, hold=dict(HoldTest.HOLD, blocks=[12], split=[HoldTest.CHILD, note_child]),
                                  **{"close-out": {"issue_state": "OPEN", "notes_posted": True}})
        self.assertEqual((result["stage"], result["bad_split"]), ("hold", ["AC4"]))
        self.assertNotIn("close-out", labels(calls))
        extra = dict(HoldTest.CHILD, block={"v": 1, "merge": self.MERGE, "checks": [
            {"ac": "AC3", "kind": "human"}, {"ac": "AC4", "kind": "evidence", "run": {"script": "scripts/check-live"}}]})
        result, calls = self.ship(HUMAN, NOTE, hold=dict(HoldTest.HOLD, blocks=[12], split=[extra]),
                                  **{"close-out": {"issue_state": "OPEN", "notes_posted": True}})
        self.assertEqual((result["stage"], result["bad_split"]), ("hold", ["AC3"]))
        self.assertNotIn("close-out", labels(calls))

    def test_an_unrecognised_kind_never_closes_ungraded(self):
        """#736 DR-002: a typo kind is neither open nor a note, so no path may close the issue on it."""
        typo = dict(NOTE, kind="evdience")
        cont = {"setup": {"ok": True, "worktree": "/r/.wt/w-issue-9-x", "branch": "issue-9-x", "plan_dir": "/g",
                          "holder": HOLDER, "base_sha": SHA},
                "plan": with_criteria(typo), "plan_reviewed": True, "done": [{"n": 1, "commit": "c0ffee"}]}
        result, calls = run(args=dict(ARGS, cont=cont), patch={"setup": merged(42, "c0ffee")})
        self.assertEqual((result["stage"], result["bad_kinds"]), ("close-out", ["AC4"]))
        self.assertNotIn("close-out", labels(calls))
        self.assertNotIn("hold", labels(calls))
        result, calls = run(replies={"plan": with_criteria(typo)})
        self.assertNotEqual(result["stage"], "done")
        self.assertNotIn("pr", labels(calls))
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
        for label in ("pr", "checks-1", "merge", "close-out"):
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
        self.assertEqual(labels(calls), ["setup", "pr", "checks-1", "merge", "land-unlock", "hold", "close-out"])

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


TIP = "b" * 40


class FinalReviewedResumeTest(unittest.TestCase):
    """#649 defect 3: cont records the head the final review passed at; a resume on it skips the review."""

    FIRST = {"verdict": "findings", "findings": [{"severity": "critical", "summary": "race in acquire"}]}

    @staticmethod
    def stopped_after_review(**patch):
        stopped, _ = run(replies={"verify": None}, patch=dict({"impl-1": {"commit": TIP}}, **patch))
        assert stopped["stage"] == "verify", stopped["stage"]
        return stopped

    def test_cont_records_the_head_the_final_review_passed_at(self):
        self.assertEqual(self.stopped_after_review()["cont"]["final_reviewed"], {"head": TIP})
        stopped, _ = run(replies={"final-1": self.FIRST, "verify": None},
                         patch={"impl-1": {"commit": TIP}, "fix-wave": {"start_head": TIP, "commit": "d" * 40}})
        self.assertEqual(stopped["cont"]["final_reviewed"], {"head": "d" * 40})

    def test_no_marker_before_the_final_review_passes(self):
        new = {"verdict": "findings", "findings": [{"severity": "critical", "summary": "leak", "relation": "new"}]}
        for replies in ({"final-1": None}, {"final-1": self.FIRST, "fix-wave-review": new}):
            with self.subTest(replies=replies):
                stopped, _ = run(replies=replies)
                self.assertIn(stopped["stage"], ("final-review", "fix-wave-review"))
                self.assertNotIn("final_reviewed", stopped["cont"])
        stopped, _ = run(args=dict(ARGS, lane="direct"), replies={"verify": None})
        self.assertNotIn("final_reviewed", stopped["cont"])

    def test_resume_on_the_reviewed_head_skips_the_final_review(self):
        cont = self.stopped_after_review()["cont"]
        for head in (TIP, TIP[:10]):
            with self.subTest(head=head):
                result, calls = run(args=dict(ARGS, cont=cont), patch={"setup": {"head": head}})
                self.assertEqual(result["stage"], "done")
                self.assertEqual(labels(calls), ["setup", "verify", "pr", "checks-1", "merge", "land-unlock",
                                                 "hold", "close-out"])

    def test_resume_after_only_an_integration_merge_skips_the_final_review(self):
        cont = self.stopped_after_review()["cont"]
        result, calls = run(args=dict(ARGS, cont=cont),
                            patch={"setup": {"head": "e" * 40, "since_reviewed": "merge_only"}})
        self.assertEqual(result["stage"], "done")
        self.assertNotIn("final-1", labels(calls))
        self.assertIn("verify", labels(calls))
        setup = prompt(calls, "setup")
        self.assertIn(f"rev-list --no-merges {TIP}..HEAD", setup)
        self.assertIn(f"merge-base --is-ancestor {TIP} HEAD", setup)

    def test_resume_on_a_moved_head_reviews_again_and_records_the_new_head(self):
        cont = self.stopped_after_review()["cont"]
        for patch in ({"head": "e" * 40, "since_reviewed": "moved"}, {"head": "e" * 40}, {}):
            with self.subTest(patch=patch):
                result, calls = run(args=dict(ARGS, cont=cont), patch={"setup": patch})
                self.assertEqual(result["stage"], "done")
                self.assertIn("final-1", labels(calls))
        stopped, _ = run(args=dict(ARGS, cont=cont), replies={"verify": None}, patch={"setup": {"head": "e" * 40}})
        self.assertEqual(stopped["cont"]["final_reviewed"], {"head": "e" * 40})

    def test_resume_with_an_unfinished_task_reviews_again(self):
        cont = dict(self.stopped_after_review()["cont"], done=[])
        result, calls = run(args=dict(ARGS, cont=cont), patch={"setup": {"head": TIP}})
        self.assertEqual(result["stage"], "done")
        names = labels(calls)
        self.assertLess(names.index("impl-1"), names.index("final-1"))

    def test_ready_cont_on_a_merge_only_head_skips_review_but_verifies_again(self):
        ready, _ = run(args=dict(ARGS, mode="ready"))
        self.assertIn("final_reviewed", ready["cont"])
        result, calls = run(args=dict(ARGS, cont=ready["cont"]),
                            patch={"setup": {"head": "e" * 40, "since_reviewed": "merge_only"}})
        self.assertEqual(result["stage"], "done")
        self.assertNotIn("final-1", labels(calls))
        self.assertIn("verify", labels(calls))

    def sync_stop(self, replies, patch):
        stopped, _ = run(replies=dict({"checks-1": {"state": "behind", "head": SHA}}, **replies),
                         patch=dict({"impl-1": {"commit": TIP},
                                     "sync-1": {"conflicted": True, "merge_commit": MERGE}}, **patch))
        return stopped

    def test_a_stop_inside_the_sync_window_drops_the_marker_and_the_resume_reviews_again(self):
        cases = {
            "sync": ({"sync-1": None}, {}),
            "sync-review": ({"sync-review-1": None}, {}),
            "sync-review ": ({"sync-review-1": FINDING, "fix-sync-review-1": FINDING},
                             {"fix-sync-1": {"start_head": MERGE, "commit": FIX}}),
            "sync-fix": ({"sync-review-1": FINDING}, {"fix-sync-1": {"status": "blocked", "notes": "no"}}),
        }
        for stage, (replies, patch) in cases.items():
            with self.subTest(stage=stage):
                stopped = self.sync_stop(replies, patch)
                self.assertEqual(stopped["stage"], stage.strip())
                self.assertNotIn("final_reviewed", stopped["cont"])
                result, calls = run(args=dict(ARGS, cont=stopped["cont"]),
                                    patch={"setup": {"head": MERGE, "since_reviewed": "merge_only"}})
                self.assertEqual(result["stage"], "done")
                names = labels(calls)
                self.assertIn("final-1", names)
                self.assertLess(names.index("final-1"), names.index("merge"))
                self.assertNotIn("since_reviewed", prompt(calls, "setup"))

    def test_an_accepted_conflicted_merge_keeps_the_skip(self):
        stopped = self.sync_stop({"checks-2": None}, {})
        self.assertEqual(stopped["stage"], "checks")
        self.assertEqual(stopped["cont"]["final_reviewed"], {"head": TIP, "accepted": [MERGE]})
        result, calls = run(args=dict(ARGS, cont=stopped["cont"]),
                            patch={"setup": {"head": MERGE, "since_reviewed": "merge_only"}})
        self.assertEqual(result["stage"], "done")
        self.assertNotIn("final-1", labels(calls))
        setup = prompt(calls, "setup")
        self.assertIn(MERGE, setup)
        self.assertIn(f"rev-list --merges {TIP}..HEAD", setup)

    def test_the_setup_requires_merges_without_a_hand_made_resolution(self):
        ready, _ = run(args=dict(ARGS, mode="ready"), patch={"impl-1": {"commit": TIP}})
        self.assertNotIn("accepted", ready["cont"]["final_reviewed"])
        _, calls = run(args=dict(ARGS, mode="ready", cont=ready["cont"]), patch={"setup": {"head": MERGE, "since_reviewed": "moved"}})
        setup = prompt(calls, "setup")
        self.assertIn(f"rev-list --merges {TIP}..HEAD", setup)
        self.assertIn("merge-tree --write-tree <merge>^1 <merge>^2", setup)
        self.assertIn("rev-parse <merge>^{tree}", setup)
        self.assertNotIn("prints nothing); else", setup)
        self.assertIn("final-1", labels(calls))

    def test_the_merge_tree_check_flags_a_one_sided_resolution_that_show_cc_misses(self):
        """The setup's clean-merge test, run on real git: a conflict resolved by taking one side whole."""
        def git(*args, ok=(0,)):
            r = subprocess.run(["git", "-C", repo, "-c", "user.email=a@b", "-c", "user.name=a",
                                "-c", "commit.gpgsign=false", *args], capture_output=True, text=True)
            self.assertIn(r.returncode, ok, r.stderr)
            return r

        def write(text):
            with open(os.path.join(repo, "foo.js"), "w") as f:
                f.write(text)

        def clean(merge):
            r = git("merge-tree", "--write-tree", merge + "^1", merge + "^2", ok=(0, 1))
            return r.returncode == 0 and r.stdout.strip() == git("rev-parse", merge + "^{tree}").stdout.strip()

        with tempfile.TemporaryDirectory() as repo:
            git("init", "-q", "-b", "main")
            write("a\nb\nc\n")
            git("add", "."), git("commit", "-qm", "base")
            git("checkout", "-qb", "work")
            write("a\nB\nc\n")
            git("commit", "-qam", "delivery change")
            git("checkout", "-q", "main")
            write("a\nX\nc\n")
            git("commit", "-qam", "integration change")
            git("checkout", "-q", "work")
            git("merge", "-q", "main", "-m", "sync", ok=(1,))
            write("a\nX\nc\n")  # takes the integration side verbatim, dropping the delivery change
            git("add", "."), git("commit", "-qm", "sync")
            self.assertEqual(git("show", "--cc", "--format=", "HEAD").stdout, "")  # the blind spot
            self.assertFalse(clean("HEAD"))
            # a merge git resolves without help passes the same test
            git("checkout", "-qb", "work2", "main~1")
            write("a\nb\nc\ne\n")
            git("commit", "-qam", "tail")
            git("merge", "-q", "main", "-m", "clean sync")
            self.assertTrue(clean("HEAD"))

    def test_a_review_that_must_run_again_drops_the_stale_marker(self):
        cont = self.stopped_after_review()["cont"]
        stopped, _ = run(args=dict(ARGS, cont=cont), replies={"final-1": None}, patch={"setup": {"head": "e" * 40}})
        self.assertEqual(stopped["stage"], "final-review")
        self.assertNotIn("final_reviewed", stopped["cont"])

    def test_a_dirty_tree_on_the_reviewed_head_reviews_again(self):
        cont = dict(self.stopped_after_review()["cont"], partial=1)
        result, calls = run(args=dict(ARGS, cont=cont), patch={"setup": {"head": TIP, "dirty": True}})
        self.assertEqual(result["stage"], "done")
        self.assertIn("final-1", labels(calls))

    def test_the_direct_lane_never_keeps_a_marker(self):
        direct = dict(ARGS, lane="direct")
        stopped, _ = run(args=direct, replies={"verify": None}, patch={"direct-impl": {"commit": TIP}})
        self.assertEqual(stopped["stage"], "verify")
        cont = dict(stopped["cont"], final_reviewed={"head": TIP})
        stopped, _ = run(args=dict(direct, cont=cont), replies={"verify": None}, patch={"setup": {"head": TIP}})
        self.assertEqual(stopped["stage"], "verify")
        self.assertNotIn("final_reviewed", stopped["cont"])

    def test_cont_without_the_marker_still_resumes(self):
        cont = self.stopped_after_review()["cont"]
        del cont["final_reviewed"]
        result, calls = run(args=dict(ARGS, cont=cont), patch={"setup": {"head": TIP}})
        self.assertEqual(result["stage"], "done")
        self.assertIn("final-1", labels(calls))
        self.assertNotIn("since_reviewed", prompt(calls, "setup"))
        _, calls = run()
        self.assertNotIn("since_reviewed", prompt(calls, "setup"))


DIRECT = dict(ARGS, lane="direct")
BAD = {"verdict": "findings", "findings": [{"severity": "important", "summary": "bug"}]}


class DirectLaneTest(unittest.TestCase):
    """#635: setup, one implementer on deliver-direct's steps, one fresh reviewer, at most one fix round."""

    def test_direct_lane_runs_one_implementer_one_fresh_reviewer_and_no_planner(self):
        result, calls = run(args=DIRECT)
        self.assertEqual(result["stage"], "done")
        names = labels(calls)
        self.assertFalse([l for l in names if l.startswith("plan") or l == "owner-answer"], names)
        self.assertEqual([c["label"] for c in calls if c["agentType"] == "implementer"], ["direct-impl"])
        reviewers = [c for c in calls if c["agentType"] in ("reviewer", "reviewer-lite")]
        self.assertEqual([(c["label"], c["agentType"]) for c in reviewers], [("direct-review", "reviewer-lite")])
        self.assertIn("lane: direct.", reviewers[0]["prompt"])
        self.assertIn("direct-codex", names)
        self.assertNotIn("final-1", names)
        self.assertEqual(names[names.index("direct-impl") - 1], "setup")
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

    def test_a_criterion_without_evidence_is_a_blocking_finding_and_the_fix_round(self):
        graded = {"verdict": "pass", "findings": [], "acceptance": [{"id": "AC1", "met": True, "evidence": ""}]}
        result, calls = run(args=DIRECT, replies={"direct-review": graded})
        self.assertEqual(result["stage"], "done")
        fix = prompt(calls, "direct-fix")
        self.assertIn("AC1", fix)
        self.assertIn('"severity":"important"', fix)
        self.assertEqual(labels(calls).count("direct-rereview"), 1)

    def test_an_unmet_or_ungraded_criterion_is_a_blocking_finding(self):
        unmet = {"verdict": "pass", "findings": [], "acceptance": [{"id": "AC1", "met": False, "evidence": "t.py:1"}]}
        for reply in (unmet, {"verdict": "pass", "findings": []}):
            _, calls = run(args=DIRECT, replies={"direct-review": reply})
            self.assertIn("AC1", prompt(calls, "direct-fix"))

    def test_a_criterion_met_with_evidence_needs_no_fix_round(self):
        _, calls = run(args=DIRECT)
        self.assertNotIn("direct-fix", labels(calls))

    def test_a_criterion_no_test_can_show_is_not_held_to_evidence(self):
        acceptance = [{"id": "AC1", "text": "works", "kind": "code"}, {"id": "AC2", "text": "feels right", "kind": "human"}]
        _, calls = run(args=DIRECT, patch={"direct-impl": {"acceptance": acceptance}})
        self.assertNotIn("direct-fix", labels(calls))

    def test_the_review_prompt_holds_only_code_criteria_to_the_blocking_evidence_rule(self):
        for patch in ({}, {"direct-impl": {"sensitive": True}}):
            _, calls = run(args=DIRECT, patch=patch)
            text = prompt(calls, "direct-review")
            self.assertIn("a code criterion that is not met, or has no evidence, is an Important finding", text)
            self.assertIn("other kinds are not findings", text)
            self.assertNotIn("unmet criteria only", text)

    def test_the_escalated_full_review_is_graded_too(self):
        replies = {"direct-review": {"verdict": "pass", "findings": [], "escalate": True},
                   "direct-review-full": {"verdict": "pass", "findings": []}}
        _, calls = run(args=DIRECT, replies=replies)
        self.assertIn("AC1", prompt(calls, "direct-fix"))

    def test_every_direct_review_prompt_and_schema_asks_for_graded_criteria(self):
        for label, patch in (("direct-review", {}), ("direct-review", {"direct-impl": {"sensitive": True}})):
            _, calls = run(args=DIRECT, patch=patch)
            self.assertIn("acceptance with one entry per criterion id", prompt(calls, label))
            item = schema_of(calls, label)["properties"]["acceptance"]["items"]
            self.assertEqual(set(item["required"]), {"id", "met", "evidence"})
        replies = {"direct-review": {"verdict": "pass", "findings": [], "escalate": True}}
        _, calls = run(args=DIRECT, replies=replies)
        self.assertIn("acceptance with one entry per criterion id", prompt(calls, "direct-review-full"))
        self.assertIn("acceptance", schema_of(calls, "direct-review-full")["properties"])

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
        self.assertEqual(labels(calls), ["setup", "pr", "checks-1", "merge", "land-unlock", "hold", "close-out"])

    def test_a_review_stop_resumes_into_the_review_not_the_implementer(self):
        stopped, _ = run(args=DIRECT, replies={"direct-review": None})
        self.assertEqual(stopped["stage"], "direct-review")
        self.assertIsNone(stopped["cont"]["done"][0]["reviewed_head"])
        result, calls = run(args=dict(ARGS, cont=stopped["cont"]), patch={"setup": {"head": "c0ffee"}})
        self.assertEqual(result["stage"], "done")
        self.assertNotIn("direct-impl", labels(calls))
        self.assertIn("direct-review", labels(calls))

    def test_claim_failures_keep_the_lane(self):
        failures = {"acquire": {"acquire": {"verdict": "error", "detail": "forge down"}},
                    "worktree": {"claim": {"ok": False, "reason": "worktree add failed"}}}
        for lane in ("standard", "direct"):
            for label, reply in failures.items():
                with self.subTest(lane=lane, label=label):
                    stopped, _ = run(args=dict(ARGS, lane=lane), patch={"setup": reply})
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
    def test_land_lock_calls_are_the_batch_calls(self):
        """#677 P1: deliver-standard reuses deliver-batch's land-lock calls verbatim."""
        mine = PROGRAM.read_text(encoding="utf-8")
        batch = PROGRAM.with_name("deliver-batch.js").read_text(encoding="utf-8")

        def literal(text, name):
            start = text.index(f"const {name} = ")
            first = text[start:text.index("\n", start)]
            return first if first.rstrip().endswith("}") else text[start:text.index("\n}\n", start) + 2]

        for name in ("LOCK_SCHEMA", "RELEASE_SCHEMA"):
            with self.subTest(name=name):
                self.assertEqual(literal(mine, name), literal(batch, name))

        def line(text, name):
            start = text.index(f"const {name} = ")
            return text[start:text.index("\n", start)]

        def bare(text):
            """The text without the #740 FORGE_TIMEOUT sentence (and its template-literal quoting), which each program adds in its own task."""
            return text.replace(" ${FORGE_TIMEOUT}", "").replace("`", "'")

        for name in ("LAND_ACQUIRE", "LOCK_RETURN", "RELEASE_AGAIN"):
            with self.subTest(name=name):
                self.assertEqual(bare(line(mine, name)), bare(line(batch, name)))
        for needle in (
            "Run alone and exactly: forge-claim land release --repo ${SLUG} --branch ${INT} --sha ${lockSha}",
            "released and not_held are both fine. ${FORGE_TIMEOUT} Return its verdict and any detail. Run nothing else.",
        ):
            with self.subTest(line=needle):
                self.assertIn(bare(needle), bare(batch))
                self.assertIn(needle, mine)

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


BR = {"name": "cand", "worktree": "/r/.wt/cand", "base": "origin/dev", "head": "b" * 40,
      "current": "cand", "toplevel": "/r/.wt/cand", "common_dir": "/r/.git", "clean": True}
BR_PUSH = "git -C /r/.wt/cand push origin cand"
NO_FORCE = "Never push with --force, --force-with-lease or a +refspec, and never push dev or main."
TASK_FINDING = {"verdict": "findings", "findings": [{"severity": "important", "summary": "bug on the candidate"}]}
REVIEWERS = ("reviewer", "reviewer-lite")


def bplan(branches=..., task_branch="cand", **top):
    """A two-task plan whose second task commits to the declared branch cand (#713)."""
    second = {"n": 2, "title": "two", "file": "/g/task-2.md", "risk": "standard"}
    if task_branch is not None:
        second["branch"] = task_branch
    return dict(PLAN, branches=[dict(BR)] if branches is ... else branches,
                tasks=[dict(PLAN["tasks"][0]), second], **top)


def at(path, **more):
    """BR moved to another worktree path whose facts agree with it."""
    return dict(BR, worktree=path, toplevel=path, **more)


class DeclaredBranchTest(unittest.TestCase):
    """#713 (#685 item 3): a plan may declare extra branches its fix agents edit and push, never forced."""

    def test_declared_branch_grants_non_force_push_to_its_fix_agent(self):
        result, calls = run(replies={"plan": bplan(), "review-2": TASK_FINDING})
        self.assertEqual(result["stage"], "done")
        planner = prompt(calls, "plan")
        self.assertIn("--git-common-dir", planner)
        self.assertIn("status --porcelain", planner)
        cut = labels(calls).index("plan-review") + 1
        post = calls[cut:]
        granted = {c["label"] for c in post if c["agentType"] not in REVIEWERS}
        self.assertLessEqual({"impl-1", "impl-2", "fix-2-1", "final-codex",
                              "verify", "pr", "checks-1", "merge", "land-unlock", "hold",
                              "close-out"}, granted)
        for c in post:
            with self.subTest(label=c["label"]):
                if c["agentType"] in REVIEWERS:
                    self.assertNotIn("push origin", c["prompt"])
                else:
                    self.assertIn(BR_PUSH, c["prompt"])
                    self.assertIn(NO_FORCE, c["prompt"])
        for c in calls[:cut]:
            with self.subTest(label=c["label"]):
                self.assertNotIn(BR_PUSH, c["prompt"])
        _, plain = run()
        for call in plain:
            self.assertNotIn("--force-with-lease", call["prompt"], call["label"])
        # D7: the merged-PR re-adopt closes out before the resumed plan is validated, and pushes nothing.
        cont = {"setup": {"ok": True, "worktree": "/r/.wt/w-issue-9-x", "branch": "issue-9-x", "plan_dir": "/g",
                          "holder": HOLDER, "base_sha": SHA},
                "plan": bplan(), "plan_reviewed": True, "done": [{"n": 1, "commit": "c0ffee"}, {"n": 2, "commit": "d" * 40}]}
        closed, calls = run(args=dict(ARGS, cont=cont), patch={"setup": merged(42, "c0ffee")})
        self.assertEqual(closed["stage"], "done")
        for label in ("hold", "close-out"):
            self.assertNotIn(BR_PUSH, prompt(calls, label))

    def test_a_declared_branch_task_runs_in_its_worktree(self):
        one, two, three = "1" * 40, "2" * 40, "3" * 40
        result, calls = run(replies={"plan": bplan(), "review-2": TASK_FINDING},
                            patch={"impl-2": {"start_head": one, "commit": two},
                                   "fix-2-1": {"start_head": two, "commit": three}})
        self.assertEqual(result["stage"], "done")
        here = "Task 2 commits to the declared branch cand in the worktree /r/.wt/cand"
        push = "After each commit, push it alone with git -C /r/.wt/cand push origin cand."
        for label in ("impl-2", "review-2", "fix-2-1", "rereview-2-1"):
            with self.subTest(label=label):
                self.assertIn(here, prompt(calls, label))
        for label in ("impl-2", "fix-2-1"):
            self.assertIn(push, prompt(calls, label))
        for label in ("review-2", "rereview-2-1"):
            self.assertNotIn("push origin", prompt(calls, label))
        self.assertIn(f"git -C /r/.wt/cand diff {one}..{two}", prompt(calls, "review-2"))
        self.assertIn(f"git -C /r/.wt/cand diff {two}..{three}", prompt(calls, "rereview-2-1"))
        self.assertNotIn("commits to the declared branch", prompt(calls, "impl-1"))
        self.assertIn("git -C /r/.wt/w-issue-9-x diff b0..c0ffee", prompt(calls, "review-1"))
        self.assertEqual(result["tasks"][1], {"n": 2, "commit": three, "review_rounds": 1,
                                              "reviewer": "reviewer", "branch": "cand"})
        self.assertNotIn("branch", result["tasks"][0])

    def test_declaring_the_integration_branch_is_invalid(self):
        bad = {
            "integration": bplan([dict(BR, name="dev", current="dev")], task_branch="dev"),
            "default": bplan([dict(BR, name="main", current="main")], task_branch="main"),
            "issue branch": bplan([dict(BR, name="issue-9-x", current="issue-9-x")], task_branch="issue-9-x"),
            "case alias": bplan([dict(BR, name="DEV", current="DEV")], task_branch="DEV"),
            "namespaced": bplan([dict(BR, name="refs/heads/main", current="refs/heads/main")], task_branch="refs/heads/main"),
            "heads alias": bplan([dict(BR, name="heads/cand", current="heads/cand")], task_branch="heads/cand"),
            "lock": bplan([dict(BR, name="cand.lock", current="cand.lock")], task_branch="cand.lock"),
            "dot component": bplan([dict(BR, name="a/.b", current="a/.b")], task_branch="a/.b"),
            "trailing dot": bplan([dict(BR, name="cand.", current="cand.")], task_branch="cand."),
            "HEAD": bplan([dict(BR, name="HEAD", current="HEAD")], task_branch="HEAD"),
            "refspec": bplan([dict(BR, name="+cand", current="+cand")], task_branch="+cand"),
            "shell": bplan([dict(BR, name="cand;x", current="cand;x")], task_branch="cand;x"),
            "delivery worktree": bplan([at("/r/.wt/w-issue-9-x")]),
            "delivery worktree, slash": bplan([at("/r/.wt/w-issue-9-x/")]),
            "shared checkout": bplan([at("/r")]),
            "shared checkout, slash": bplan([at("/r/")]),
            "shared checkout, dot": bplan([at("/r/.")]),
            "shared checkout, case": bplan([at("/R")]),
            "dot-dot worktree": bplan([at("/r/.wt/../cand")]),
            "relative worktree": bplan([at("wt/cand")]),
            "on another branch": bplan([dict(BR, current="issue-9-x")]),
            "not its own checkout": bplan([dict(BR, worktree="/r/sub", toplevel="/r")]),
            "dirty": bplan([dict(BR, clean=False)]),
            "no clean": bplan([{k: v for k, v in BR.items() if k != "clean"}]),
            "other repository": bplan([dict(BR, common_dir="/other/.git")]),
            "no common dir": bplan([{k: v for k, v in BR.items() if k != "common_dir"}]),
            "no toplevel": bplan([{k: v for k, v in BR.items() if k != "toplevel"}]),
            "no head": bplan([{k: v for k, v in BR.items() if k != "head"}]),
            "short head": bplan([dict(BR, head="b" * 7)]),
            "bad base": bplan([dict(BR, base="x..y")]),
            "shell base": bplan([dict(BR, base="origin/dev;x")]),
            "twice": bplan([dict(BR), at("/r/.wt/cand2")]),
            "shared worktree": bplan([dict(BR), dict(BR, name="cand2", current="cand2")]),
            "undeclared task branch": bplan(task_branch="other"),
            "task branch not a string": bplan(task_branch=5),
            "not a list": bplan("cand"),
            "entry not an object": bplan(["cand"]),
            "null entry": bplan([None]),
            "list entry": bplan([[dict(BR)]]),
        }
        for name, reply in bad.items():
            with self.subTest(name=name):
                result, calls = run(replies={"plan": reply})
                self.assertEqual((result["stage"], result["step"]), ("plan", "plan"))
                self.assertTrue(result["branch_problems"])
                self.assertIsNone(result["cont"]["plan"])
                self.assertNotIn("plan-review", labels(calls))
                self.assertNotIn("impl-1", labels(calls))
        ok, _ = run(replies={"plan": bplan([dict(BR), at("/r/.wt/cand2", name="cand2", current="cand2")])})
        self.assertEqual(ok["stage"], "done")
        result, calls = run(replies={"plan-review": TASK_FINDING,
                                     "plan-revise": bplan([dict(BR, name="dev", current="dev")], task_branch="dev")})
        self.assertEqual((result["stage"], result["step"]), ("plan", "plan-revise"))
        self.assertTrue(result["branch_problems"])
        cont = {"setup": {"ok": True, "worktree": "/r/.wt/w-issue-9-x", "branch": "issue-9-x", "plan_dir": "/g"},
                "plan": bplan([dict(BR, name="dev", current="dev")], task_branch="dev"), "plan_reviewed": True, "done": []}
        facts = [{"name": "dev", "head": "b" * 40, "current": "dev", "toplevel": "/r/.wt/cand", "common_dir": "/r/.git"}]
        result, calls = run(args=dict(ARGS, cont=cont), patch={"setup": {"branch_heads": facts}})
        self.assertEqual((result["stage"], result["step"]), ("plan", "resume"))
        self.assertTrue(result["branch_problems"])
        self.assertNotIn("impl-1", labels(calls))

    def test_a_kept_plan_with_an_invalid_declaration_is_dropped_on_resume_whatever_the_facts_read(self):
        """The plan check comes before the branch-fact check: honest facts of an invalid declaration must not stop setup."""
        cont_of = lambda plan: {"setup": {"ok": True, "worktree": "/r/.wt/w-issue-9-x", "branch": "issue-9-x", "plan_dir": "/g"},
                                "plan": plan, "plan_reviewed": True, "done": []}
        honest = {
            "delivery worktree": (at("/r/.wt/w-issue-9-x"), {"current": "issue-9-x", "toplevel": "/r/.wt/w-issue-9-x"}),
            "shared checkout": (at("/r"), {"current": "main", "toplevel": "/r"}),
            "relative worktree": (at("wt/cand"), {"toplevel": "/r/wt/cand"}),
            "dot-dot worktree": (at("/r/.wt/../cand"), {"toplevel": "/r/.wt/cand"}),
            "on another branch": (dict(BR, current="issue-9-x"), {"current": "issue-9-x"}),
            "not its own checkout": (dict(BR, worktree="/r/sub", toplevel="/r"), {"toplevel": "/r"}),
            "integration branch": (dict(BR, name="dev", current="dev"), {"name": "dev", "current": "dev"}),
            "dirty": (dict(BR, clean=False), {}),
            "unread": (dict(BR, common_dir="/other/.git"), None),
        }
        for name, (entry, read) in honest.items():
            with self.subTest(name=name):
                tb = entry["name"]
                cont = cont_of(bplan([entry], task_branch=tb))
                fact = None if read is None else dict(self.facts("b" * 40, name=tb)[0], **read)
                patch = {"head": TIP} if fact is None else {"head": TIP, "branch_heads": [fact]}
                result, calls = run(args=dict(ARGS, cont=cont), patch={"setup": patch})
                self.assertEqual((result["stage"], result["step"]), ("plan", "resume"))
                self.assertTrue(result["branch_problems"])
                self.assertIsNone(result["cont"]["plan"])
                self.assertNotIn("impl-1", labels(calls))

    def test_a_kept_plan_the_resume_drops_demands_no_branch_facts(self):
        """A plan-review stop keeps an unreviewed plan; when the resume will drop and replan it, a vanished worktree must not stop setup."""
        setup = {"ok": True, "worktree": "/r/.wt/w-issue-9-x", "branch": "issue-9-x", "plan_dir": "/g"}
        interface = {"severity": "important", "summary": "interface mismatch"}
        codex = {"severity": "important", "rule": "R2", "summary": "s", "source": "codex"}
        rule = {"severity": "important", "rule": "R2", "summary": "s"}
        for name, kept in (("non-rule finding", interface), ("codex finding", codex)):
            with self.subTest(name=name):
                cont = {"setup": setup, "plan": bplan(), "plan_reviewed": False,
                        "plan_findings": {"rules": [kept], "findings": [kept], "rounds": 0}, "done": []}
                result, calls = run(args=dict(ARGS, cont=cont), patch={"setup": {"head": TIP}})
                self.assertNotEqual(result["stage"], "setup")
                self.assertEqual(labels(calls).count("plan"), 1)
                self.assertNotIn("plan-rules-revise", labels(calls))
        # A rules-only kept plan is revised in place and still reads its facts first.
        cont = {"setup": setup, "plan": bplan(), "plan_reviewed": False,
                "plan_findings": {"rules": [rule], "findings": [rule], "rounds": 0}, "done": []}
        result, _ = run(args=dict(ARGS, cont=cont), patch={"setup": {"head": TIP}})
        self.assertEqual(result["stage"], "setup")
        self.assertEqual(result["missing"], ["branch_heads.cand"])

    RANGE = "git -C /r/.wt/cand diff origin/dev...cand"
    FINAL_FINDING = {"verdict": "findings", "findings": [{"severity": "critical", "summary": "candidate drops a key"}]}

    def test_final_review_covers_the_declared_branch_range(self):
        stopped, calls = run(replies={"plan": bplan(), "verify": None},
                             patch={"impl-1": {"commit": TIP}, "impl-2": {"start_head": "1" * 40, "commit": "d" * 40}})
        self.assertEqual(stopped["stage"], "verify")
        for label in ("final-codex", "final-1"):
            with self.subTest(label=label):
                self.assertIn(self.RANGE, prompt(calls, label))
        self.assertEqual(stopped["cont"]["final_reviewed"], {"head": TIP, "branches": {"cand": "d" * 40}})
        chunked = bplan()
        chunked["tasks"] = tasks(3) + [dict(chunked["tasks"][1], n=4, file="/g/task-4.md")]
        _, calls = run(replies={"plan": chunked})
        for label in ("final-1", "final-2", "final-integration"):
            with self.subTest(label=label):
                self.assertIn(self.RANGE, prompt(calls, label))
        _, plain = run()
        self.assertNotIn("declared branches", prompt(plain, "final-1"))
        self.assertNotIn(self.RANGE, prompt(plain, "final-codex"))

    def test_fix_wave_records_and_rereviews_the_declared_branch_heads(self):
        moved = {"start_head": TIP, "commit": TIP, "branch_heads": [{"name": "cand", "head": "e" * 40}]}
        stopped, calls = run(replies={"plan": bplan(), "final-1": self.FINAL_FINDING, "verify": None},
                             patch={"impl-1": {"commit": TIP}, "impl-2": {"commit": "d" * 40}, "fix-wave": moved})
        self.assertEqual(stopped["stage"], "verify")
        self.assertIn("branch_heads", prompt(calls, "fix-wave"))
        wave = prompt(calls, "fix-wave")
        self.assertIn("git -C /r/.wt/w-issue-9-x rev-parse HEAD", wave)
        self.assertIn("never a declared branch's commit", wave)
        self.assertNotIn("(git rev-parse HEAD before", wave)
        self.assertIn(f"git -C /r/.wt/cand diff {'d' * 40}..{'e' * 40}", prompt(calls, "fix-wave-review"))
        self.assertNotIn("push origin", prompt(calls, "fix-wave-review"))
        self.assertEqual(stopped["cont"]["final_reviewed"], {"head": TIP, "branches": {"cand": "e" * 40}})
        for heads in (None, [], [{"name": "cand", "head": "e" * 7}], [None, "cand"]):
            with self.subTest(heads=heads):
                wave = {"start_head": TIP, "commit": TIP} if heads is None else {"start_head": TIP, "commit": TIP, "branch_heads": heads}
                stopped, _ = run(replies={"plan": bplan(), "final-1": self.FINAL_FINDING},
                                 patch={"impl-2": {"commit": "d" * 40}, "fix-wave": wave})
                self.assertEqual(stopped["stage"], "fix-wave")
                self.assertNotIn("final_reviewed", stopped["cont"])


    @staticmethod
    def facts(head, name="cand", **more):
        return [dict({"name": name, "head": head, "current": name, "toplevel": "/r/.wt/cand", "common_dir": "/r/.git"}, **more)]

    def test_resume_where_only_the_declared_branch_changed_reviews_again(self):
        stopped, _ = run(replies={"plan": bplan(), "verify": None},
                         patch={"impl-1": {"commit": TIP}, "impl-2": {"commit": "d" * 40}})
        cont = stopped["cont"]
        same, calls = run(args=dict(ARGS, cont=cont), patch={"setup": {"head": TIP, "branch_heads": self.facts("d" * 40)}})
        self.assertEqual(same["stage"], "done")
        self.assertNotIn("final-1", labels(calls))
        self.assertIn("verify", labels(calls))
        self.assertIn("cand in /r/.wt/cand", prompt(calls, "setup"))
        self.assertIn("branch_heads", prompt(calls, "setup"))
        self.assertIn("branch --show-current", prompt(calls, "setup"))
        self.assertIn("--git-common-dir", prompt(calls, "setup"))
        moved, calls = run(args=dict(ARGS, cont=cont), patch={"setup": {"head": TIP, "branch_heads": self.facts("e" * 40)}})
        self.assertEqual(moved["stage"], "done")
        self.assertIn("final-1", labels(calls))
        again, _ = run(args=dict(ARGS, cont=cont), replies={"verify": None},
                       patch={"setup": {"head": TIP, "branch_heads": self.facts("e" * 40)}})
        self.assertEqual(again["cont"]["final_reviewed"], {"head": TIP, "branches": {"cand": "e" * 40}})
        wrong = {"unread": None, "short head": self.facts("d" * 7),
                 "on another branch": self.facts("d" * 40, current="issue-9-x"),
                 "not its own checkout": self.facts("d" * 40, toplevel="/r"),
                 "another repository": self.facts("d" * 40, common_dir="/other/.git"),
                 "no common dir": self.facts("d" * 40, common_dir=None),
                 "another name": self.facts("d" * 40, name="other")}
        for name, heads in wrong.items():
            with self.subTest(name=name):
                patch = {"head": TIP} if heads is None else {"head": TIP, "branch_heads": heads}
                bad, calls = run(args=dict(ARGS, cont=cont), patch={"setup": patch})
                self.assertEqual(bad["stage"], "setup")
                self.assertIn("branch_heads.cand", bad["missing"])
                self.assertEqual(bad["cont"], cont)
                self.assertEqual(labels(calls), ["setup"])
        ready, _ = run(args=dict(ARGS, mode="ready"), replies={"plan": bplan()}, patch={"impl-2": {"commit": "d" * 40}})
        self.assertEqual(ready["cont"]["verified"]["branches"], {"cand": "d" * 40})
        _, calls = run(args=dict(ARGS, cont=ready["cont"]), patch={"setup": {"head": SHA, "branch_heads": self.facts("d" * 40)}})
        self.assertNotIn("final-1", labels(calls))
        self.assertNotIn("verify", labels(calls))
        _, calls = run(args=dict(ARGS, cont=ready["cont"]), patch={"setup": {"head": SHA, "branch_heads": self.facts("e" * 40)}})
        self.assertIn("final-1", labels(calls))
        self.assertIn("verify", labels(calls))

    def test_claim_lost_resume_rereads_the_declared_heads(self):
        stopped, _ = run(replies={"plan": bplan(), "renew-final-review": {"verdict": "error", "detail": "forge down"}},
                         patch={"impl-2": {"commit": "d" * 40}})
        self.assertEqual((stopped["stage"], stopped["at"]), ("claim-lost", "final-review"))
        cont = stopped["cont"]
        self.assertTrue(cont["claim_incomplete"])
        self.assertEqual(cont["plan"]["branches"], [BR])
        result, calls = run(args=dict(ARGS, cont=cont), replies={"acquire": {"verdict": "already_held", "comment_id": 7}},
                            patch={"setup": {"branch_heads": self.facts("d" * 40)}})
        self.assertEqual(result["stage"], "done")
        self.assertEqual(labels(calls)[:3], ["setup", "acquire", "worktree"])
        self.assertIn("branch_heads", prompt(calls, "setup"))
        self.assertIn(self.RANGE, prompt(calls, "final-1"))
        unread, calls = run(args=dict(ARGS, cont=cont))
        self.assertEqual(unread["stage"], "setup")
        self.assertIn("branch_heads.cand", unread["missing"])
        self.assertEqual(unread["cont"], cont)

    def test_a_branch_named_like_an_object_key_is_tracked_on_resume(self):
        odd = dict(BR, name="constructor", current="constructor")
        stopped, _ = run(replies={"plan": bplan([odd], task_branch="constructor"), "verify": None},
                         patch={"impl-1": {"commit": TIP}, "impl-2": {"commit": "d" * 40}})
        self.assertEqual(stopped["cont"]["final_reviewed"], {"head": TIP, "branches": {"constructor": "d" * 40}})
        again, calls = run(args=dict(ARGS, cont=stopped["cont"]), replies={"verify": None},
                           patch={"setup": {"head": TIP, "branch_heads": self.facts("e" * 40, name="constructor")}})
        self.assertIn("final-1", labels(calls))
        self.assertEqual(again["cont"]["final_reviewed"], {"head": TIP, "branches": {"constructor": "e" * 40}})


CLERK, PLANNER, IMPL, REV, LITE = "clerk", "planner", "implementer", "reviewer", "reviewer-lite"
EITHER = frozenset({REV, LITE})
EXPECTED = {stem: frozenset({kind}) if isinstance(kind, str) else kind for kind, stems in (
    (CLERK, ("setup", "acquire", "worktree", "renew-", "owner-answer", "plan-codex", "direct-codex", "final-codex",
             "verify", "verify-", "ws-check-", "land-lock-", "land-unlock", "land-push-", "pr", "checks-", "merge",
             "hold", "close-out")),
    (PLANNER, ("plan", "plan-revise", "plan-rules-revise")),
    (IMPL, ("direct-impl", "direct-fix", "impl-", "fix-", "fix-wave", "fix-wave-", "verify-fix-", "fix-ci", "sync-",
            "fix-sync-")),
    (REV, ("plan-review", "plan-rules-review", "direct-review-full", "final-", "final-integration", "fix-wave-review",
           "fix-wave-review-", "verify-fix-review-", "fix-ci-review", "sync-review-", "fix-sync-review-")),
    (EITHER, ("review-", "direct-review")),
    (LITE, ("direct-rereview", "rereview-")),
) for stem in stems}
STEM_PATTERNS = (
    r"\b(?:label|reviewLabel): (['`])([a-z][a-z0-9-]*)",
    r"\b\w*[lL]abel = (['`])([a-z][a-z0-9-]*)",
    r"`, (`)([a-z][a-z0-9-]*)(?=\$\{|`)",
)
CONFLICT = {"sync-1": {"conflicted": True, "merge_commit": MERGE, "resolved_files": ["a.py"]},
            "fix-sync-1": {"start_head": MERGE, "commit": FIX}}
VERIFY_RED = {"head": SHA, "clean": True, "results": [{"id": "build", "status": "fail", "summary": "boom"}]}
NARROWING = {"verdict": "findings",
             "findings": [{"severity": "critical", "summary": "race in release", "relation": "narrowing"}]}
SCENARIOS = (
    {},
    {"args": dict(ARGS, cont=RESUME_FOR_ANSWER), "replies": {"owner-answer": ANSWER}},
    {"replies": {"plan": with_criteria(PlanRulesTest.ROWS[0][1]), "plan-revise": with_criteria(PlanRulesTest.ROWS[0][1]),
                 "plan-rules-revise": with_criteria(PlanRulesTest.ROWS[0][1])}},
    {"replies": {"plan-review": FINDING}},
    {"args": dict(ARGS, cont={"claim_incomplete": True, "setup": {"holder": HOLDER}})},
    {"replies": {"plan": dict(PLAN, tasks=tasks(1, "low"))}},
    {"replies": {"review-1": BAD, "rereview-1-1": BAD, "rereview-1-2": BAD}},
    {"replies": {"plan": dict(PLAN, tasks=tasks(4)), "final-1": FINDING, "fix-wave-review": NARROWING}},
    {"replies": {"verify": VERIFY_RED}},
    {"replies": {"checks-1": RED, "checks-2": {"state": "passed", "head": FIX, "required": ["ci-tests"]}},
     "patch": {"fix-ci": {"start_head": SHA, "commit": FIX}}},
    {"replies": {"checks-1": {"state": "behind", "head": SHA}, "sync-review-1": FINDING,
                 "checks-2": {"state": "passed", "head": FIX, "required": ["ci-tests"]}},
     "patch": CONFLICT},
    {"args": DIRECT, "replies": {"direct-review": BAD}},
    {"args": DIRECT, "replies": {"direct-review": {"verdict": "pass", "findings": [], "escalate": True}}},
    WS_SCENARIO,
)


def all_calls():
    return [c for scenario in SCENARIOS for c in run(**scenario)[1]]


class AgentTypeTest(unittest.TestCase):
    """#734: every agent call names a program agent type, so none runs on the default tool set."""

    @staticmethod
    def stems(text):
        return {m.group(2) for pattern in STEM_PATTERNS for m in re.finditer(pattern, text)}

    @staticmethod
    def stem_of(label):
        found = [k for k in EXPECTED if label == k or (k.endswith("-") and label.startswith(k))]
        return max(found, key=len) if found else None

    def test_every_named_site_has_an_expected_type(self):
        self.assertLessEqual(self.stems(PROGRAM.read_text(encoding="utf-8")), set(EXPECTED))

    def test_every_site_is_reached_with_its_type(self):
        reached = set()
        for call in all_calls():
            stem = self.stem_of(call["label"])
            self.assertIsNotNone(stem, call["label"])
            self.assertIn(call["agentType"], EXPECTED[stem], call["label"])
            reached.add(stem)
        self.assertEqual(reached, set(EXPECTED))

    def test_d3_sites_keep_a_high_effort(self):
        found = [c for c in all_calls() if c["label"] in ("hold", "pr", "plan-codex", "direct-codex", "final-codex")]
        self.assertEqual({c["label"] for c in found}, {"hold", "pr", "plan-codex", "direct-codex", "final-codex"})
        for call in found:
            self.assertEqual((call["agentType"], call["effort"]), ("clerk", "high"), call["label"])

    def test_planner_sites_take_the_definition_tier(self):
        found = [c for c in all_calls() if c["label"] in ("plan", "plan-revise", "plan-rules-revise")]
        self.assertEqual({c["label"] for c in found}, {"plan", "plan-revise", "plan-rules-revise"})
        for call in found:
            self.assertEqual((call["agentType"], call["model"], call["effort"]), ("planner", None, None), call["label"])


class PromptCommandFormTest(unittest.TestCase):
    """#738: a command ends at a line break, and a prompt that reads the issue body asks for it."""

    BODY_READERS = ("plan", "plan-revise", "plan-rules-revise", "plan-review")

    def test_no_command_is_followed_by_a_lone_dot_argument(self):
        for call in all_calls():
            self.assertIsNone(re.search(r"(?<=\S) \.(?=\s|$)", call["prompt"]), call["label"])

    def test_body_readers_view_the_issue_as_json_with_body_and_comments(self):
        seen = set()
        for call in all_calls():
            if call["label"] not in self.BODY_READERS:
                continue
            views = re.findall(r"gh issue view[^)\n]*", call["prompt"])
            self.assertTrue(views, call["label"])
            for view in views:
                self.assertRegex(view, r"--json \S*\bbody\b", call["label"])
                self.assertRegex(view, r"--json \S*\bcomments\b", call["label"])
                self.assertNotIn("--comments", view, call["label"])
            seen.add(call["label"])
        self.assertEqual(seen, set(self.BODY_READERS))


if __name__ == "__main__":
    unittest.main()
