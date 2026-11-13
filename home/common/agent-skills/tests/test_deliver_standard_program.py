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
import sys
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


# A whole fresh setup reply, as the harness defaults it; the harness adds the folded claim to an explicit ok reply.
SETUP_OK = {
    "ok": True, "host": "h1", "slug": "owner/repo", "integration_branch": "dev", "default_branch": "main",
    "branch": "issue-9-x", "worktree_path": "/r/.wt/w-issue-9-x", "dirty": False, "unset_env": [], "merge_strategy": "merge",
    "delete_branch": True, "review": {"code": "cr", "plan": "pr"}, "review_state": {"code": "available", "plan": "available"},
    "knowledge": {"standards": ["/r/docs/standards"], "hints": ["/r/.hints"], "rejections": ["/r/.rej"]},
    "verification": [{"id": "build", "argv": ["make", "build"], "cwd": "."}],
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
SIZED = dict(ARGS, review_sizing=True)
FULL_RUBRIC = "a task whose test cannot fail, wrong or missing interfaces"
# #996: how a blocked task stop ends its reason, after the cap.
WAYS = "; resume with decisions (a planner revises the task file), amend {file, find, replace}, or decisions rerun if the cause was outside the task file"
DIRECT_WAYS = "; resume with decisions (the implementer gets it with these notes), or decisions rerun if the cause was outside the task"
CODEX_OWNS = "The Codex plan review running beside you owns code correctness"
RULE_ID = "put the broken rule's id in the finding's rule)."
PASS_REPLY = {"verdict": "pass", "findings": []}
# #987: the one-sentence turn procedure call() puts first in every reviewer and implementer prompt.
REVIEWER_ROUNDS = ("Look things up in rounds: load the files under review in one message, then put every open question's "
                   "Bash, Grep or Read call in the same message as the others, never one small lookup per turn.")
IMPLEMENTER_ROUNDS = ("Work in rounds: put a round's lookups in one message, send its independent edits as several Edit calls "
                      "in one message, and run the tests once per round of edits, never one small call per turn.")

# #992: the one sentence about the structured reply, the same in both programs.
REPLY_ALONE = ("Call StructuredOutput alone in its own message, never beside another tool call, only after every other tool "
               "result has come back: the first accepted call is final and ends the step.")


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


AMEND_EDIT = {"file": "task-2.md", "find": "old rule", "replace": "new rule"}
AMEND_CONT = {"setup": {"ok": True, "worktree": "/r/.wt/w-issue-9-x", "branch": "issue-9-x", "plan_dir": "/g"},
              "lane": "standard", "plan": dict(PLAN, tasks=tasks(2)), "plan_reviewed": True,
              "done": [{"n": 1, "commit": "c1"}], "partial": 2}
PLAN_AMEND = (sys.executable, "-m", "agent_tools.delivery.plan_amend")


def amend_input(calls):
    found = re.search(r"^Input: (\{.*\})$", prompt(calls, "amend"), re.M)
    return json.loads(found.group(1))


def plan_dir_cont(directory: Path, **extra):
    cont = dict(AMEND_CONT, setup=dict(AMEND_CONT["setup"], plan_dir=str(directory)),
                plan=dict(PLAN, plan_root=str(directory / "plan.md"),
                          tasks=[dict(t, file=str(directory / f"task-{t['n']}.md")) for t in tasks(2)]))
    cont.update(extra)
    return cont


PROGRAM_AGENT_TYPES = {"clerk", "planner", "implementer", "reviewer", "reviewer-lite"}


def untyped(calls):
    """Labels of agent calls that would run on the default tool set (#734)."""
    return [c["label"] for c in calls
            if c.get("kind", "agent") == "agent" and c["agentType"] not in PROGRAM_AGENT_TYPES]


def named(fixtures):
    """A copy of scenario replies or patches whose blocking fixture findings name a subject (#992).

    A review finding the program accepts names a file or a failing input. A fixture finding that says neither
    gets a failing input here; one that spells either key itself, an empty file included, is left as written.
    """
    def fix(value):
        if isinstance(value, list):
            return [fix(v) for v in value]
        if not isinstance(value, dict):
            return value
        out = {k: fix(v) for k, v in value.items()}
        if isinstance(out.get("findings"), list):
            out["findings"] = [dict(f, failing_input="x") if isinstance(f, dict) and f.get("severity") != "minor"
                               and "file" not in f and "failing_input" not in f else f for f in out["findings"]]
        return out
    return fix(fixtures or {})


def run_out(args=None, replies=None, patch=None, after=None):
    """The harness's whole output: result, calls, the program's log lines and the call and reply events."""
    node = shutil.which("node")
    if node is None:
        raise AssertionError("node is not on PATH; the deliver-standard scenarios need it")
    scenario = {"args": ARGS if args is None else args, "replies": named(replies), "patch": named(patch), "after": after or {}}
    done = subprocess.run([node, str(HARNESS), str(PROGRAM)], input=json.dumps(scenario),
                          capture_output=True, text=True, timeout=60, check=False)
    if done.returncode != 0:
        raise AssertionError(f"harness failed: {done.stderr}")
    out = json.loads(done.stdout)
    bad = untyped(out["calls"])
    if bad:
        raise AssertionError(f"agent calls without a program agentType: {bad}")
    return out


def run(args=None, replies=None, patch=None):
    out = run_out(args, replies, patch)
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
    "pr": ({"pr", "head"}, {"renew": RENEW_READ, "lock": {"verdict"},
                            "checks": {"state", "head", "failing", "details", "pending"}}),
    "merge": ({"merged", "behind", "merge_commit", "notes"}, {"renew": RENEW_READ, "lock": {"verdict"}}),
    "impl-1": ({"status", "start_head", "commit", "notes"}, {"renew": RENEW_READ}),
    "hold": (set(), {"release": {"verdict", "detail"}}),
    "setup": ({"ok", "reason", "details", "host", "slug", "integration_branch", "default_branch", "branch",
               "worktree_path", "head", "merged_pr", "merged_refs", "merged_heads", "dirty", "duplicate_pr", "since_reviewed", "branch_heads",
               "existing", "unset_env", "merge_strategy", "delete_branch", "review", "review_state", "knowledge",
               "verification", "holder", "acquire", "claim", "answer", "renew"},
              {"existing": {"local_branch", "remote_branch", "worktree", "dirty", "status"},
               "merged_refs[]": {"number", "closes"}, "merged_heads[]": {"number", "commits"},
               "review": {"code", "plan"}, "review_state": {"code", "plan"},
               "knowledge": {"standards", "hints", "rejections"},
               "verification[]": {"id", "argv", "cwd", "when_changed", "skip_reason", "pre_commit"},
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
        _, moved_calls = run(replies={"checks-2": {"state": "passed", "head": merge}},
                             patch={"pr": {"checks": {"state": "behind", "head": SHA}}, "sync-1": {"merge_commit": merge}})
        lock = member(schema_of(moved_calls, "checks-2"), "lock")
        for label, (top, nested) in FOLDED_READ.items():
            with self.subTest(label=label):
                schema = schema_of(calls, label)
                self.assertLessEqual(top, set(schema["properties"]))
                for name, fields in nested.items():
                    branch = member(schema, name)
                    folded = label == "setup" and name in ("answer", "renew")
                    if name in ("acquire", "claim", "lock", "release", "checks") or folded:
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
            # 870: the claim's worktree stands in for a missing worktree_path, so the gate needs both absent.
            "missing-worktree-path": ({"worktree_path": None, "claim": {"ok": True, "worktree": None, "base_sha": SHA, "plan_dir": "/g"}}, "setup", True),
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
                        self.assertEqual(result["cont"], ship_cont())
                    else:
                        self.assertIsNone(result)
        # A move lock that never answered: the release tries the old sha, then the move target.
        merge = "d" * 40
        moved = {"replies": {}, "patch": {"pr": {"checks": {"state": "behind", "head": SHA}}, "sync-1": {"merge_commit": merge}}}
        for reply in (None, "throw", {"verdict": "error", "detail": "gh failed"}):
            with self.subTest(move=reply):
                lost = reply if reply in (None, "throw") else {"lock": reply}
                _, calls = run(replies=dict(moved["replies"], **{"checks-2": lost}), patch=moved["patch"])
                text = prompt(calls, "land-unlock")
                self.assertIn(release, text)
                self.assertIn(f"When it prints not_held with lock_sha {merge}, run alone and exactly: "
                              f"forge-claim land release --repo owner/repo --branch dev --sha {merge}", text)
                self.assertEqual(labels(calls).count("land-unlock"), 1)
        # A definitive answer: a move refused by another holder leaves only the old sha to release.
        _, calls = run(replies=dict(moved["replies"], **{"checks-2": {"lock": {"verdict": "lost_to", "lock_sha": "c" * 40}}}),
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
        self.assertEqual(names[names.index("pr"):],
                         ["pr", "merge", "checks-2", "merge", "hold", "close-out"])
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
               "renew-final-review", "final-codex", "final-1", "verify", "pr", "merge",
               "hold", "close-out"]


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
BOOKKEEPING = re.compile(r"^(setup|acquire|worktree|renew|owner-answer|land-unlock|close-out)(-|$)")
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
                              "verify": {"head": head},
                              "pr": {"head": head, "checks": {"state": "passed", "head": head}}})
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

    def test_a_transient_setup_refusal_before_the_claim_is_retried_once(self):
        # 870: a forge or network failure in a reply that took no claim is asked once more; a second one, or any other refusal, stops.
        transient = {"ok": False, "reason": "branch", "details": "network is unreachable", "transient": True}
        cases = {
            "recovers": ([transient, SETUP_OK], 2, "done"),
            "transient-twice": ([transient, transient, SETUP_OK], 2, "setup"),
            "not-transient": ([dict(transient, transient=False), SETUP_OK], 1, "setup"),
            "unmarked": ([{"ok": False, "reason": "closed"}, SETUP_OK], 1, "setup"),
            "claimed": ([dict(transient, acquire={"verdict": "acquired", "comment_id": 7}), SETUP_OK], 1, "setup"),
        }
        for name, (replies, setups, stage) in cases.items():
            with self.subTest(case=name):
                result, calls = run(replies={"setup": replies})
                self.assertEqual(result["stage"], stage)
                self.assertEqual(labels(calls).count("setup"), setups)
                if stage == "setup":
                    self.assertEqual(labels(calls), ["setup"] * setups)
        _, calls = run()
        self.assertIn("transient", schema_of(calls, "setup")["properties"])
        self.assertIn("On any refusal set transient true only when the failed command's stderr JSON has transient true anywhere in it.",
                      prompt(calls, "setup"))

    def test_a_setup_reply_without_its_claim_fields_is_asked_again_once(self):
        # 870: the clerk claimed and set up the worktree but left holder, acquire, renew and claim out of its reply.
        # An explicit reply that is ok gets the fold from the harness, so the bare reply is the default with each field patched to null.
        bare = {"holder": None, "acquire": None, "claim": None, "renew": None}
        result, calls = run(replies={"setup": [dict(SETUP_OK, **bare), SETUP_OK]})
        self.assertEqual(result["stage"], "done")
        self.assertEqual(labels(calls).count("setup"), 2)
        result, calls = run(patch={"setup": bare})
        self.assertEqual((result["stage"], result["invalid"]), ("setup", "holder"))
        self.assertEqual(labels(calls), ["setup", "setup"])
        schema = schema_of(calls, "setup")
        self.assertEqual(schema["required"], ["ok", "holder", "acquire", "claim"])
        self.assertIn({"type": "null"}, schema["properties"]["holder"]["anyOf"])
        self.assertIn("A refusal before step 5 returns holder, acquire and claim null. Once the claim step ran", prompt(calls, "setup"))
        # A resumed setup carries no fold: its schema requires only ok, and it is never asked again for one.
        cont = run(patch={"setup": {"merge_strategy": None}})[0]["cont"]
        _, resumed = run(args=dict(ARGS, cont=cont))
        self.assertEqual(schema_of(resumed, "setup")["required"], ["ok"])
        self.assertEqual(labels(resumed).count("setup"), 1)

    def test_a_setup_reply_naming_the_worktree_only_in_its_claim_proceeds(self):
        # 870: the reply carried the path as claim.worktree alone and was reported missing.
        result, calls = run(patch={"setup": {"worktree_path": None}})
        self.assertEqual(result["stage"], "done")
        self.assertNotIn("worktree", labels(calls))
        self.assertIn("/r/.wt/w-issue-9-x", prompt(calls, "plan"))
        self.assertIn("Return ok=true with branch, worktree_path and every other field above, holder,", prompt(calls, "setup"))
        # A failed claim, or a claim never taken, names no location: the stop's cont carries no worktree_path.
        path = "/r/.wt/w-issue-9-x"
        for name, patch in (("failed", {"claim": {"ok": False, "worktree": path, "reason": "worktree add failed"}}),
                            ("untaken", {"acquire": {"verdict": "error", "detail": "x"}})):
            with self.subTest(claim=name):
                result, calls = run(patch={"setup": dict(patch, worktree_path=None)})
                self.assertEqual((result["stage"], result["missing"]), ("setup", ["worktree_path"]))
                self.assertFalse(result.get("cont", {}).get("setup", {}).get("worktree_path"))
        merge = prompt(run()[1], "merge")
        self.assertIn("is not up to date with the base branch, or the guard says the PR is behind its base (the integration", merge)

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

    def test_the_direct_lane_setup_reads_no_answer_but_renews_after_the_claim(self):
        _, calls = run(args=dict(ARGS, lane="direct"))
        setup = prompt(calls, "setup")
        self.assertNotIn("owner-action status", setup)
        self.assertLess(setup.index(SETUP_ACQUIRE), setup.index(SETUP_RENEW))
        self.assertLess(setup.index(SETUP_RENEW), setup.index("worktree add <worktree_path> <branch>"))

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
        with self.subTest("a recommended option passes through unchanged"):
            recommended = {"status": "needs_user", "questions": [
                {"question": "Which host?", "options": ["Host one.", "Host two."], "recommended": "Host two."}]}
            result, _ = run(replies={"plan": recommended})
            self.assertEqual(result["needs_user"], recommended["questions"])

    def test_the_planner_may_name_its_recommended_option(self):
        _, calls = run()
        plan_call = next(c for c in calls if c["label"] == "plan")
        text = prompt(calls, "plan")
        item = plan_call["schema"]["properties"]["questions"]["items"]
        self.assertEqual(item["properties"]["recommended"], {"type": "string"})
        self.assertEqual(item["required"], ["question", "options"])
        self.assertIn("when you would choose one option, recommended: its exact text", text)

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

    def test_a_batched_direct_lane_child_renews_in_setup_and_proceeds(self):
        result, calls = run(args=dict(BATCH_CHILD, lane="direct"),
                            patch={"setup": {"acquire": HELD, "renew": {"verdict": "renewed"}}})
        self.assertEqual(result["stage"], "done")
        self.assertEqual(labels(calls)[:2], ["setup", "direct-impl"])

    def test_a_lost_direct_lane_setup_renew_stops_claim_lost(self):
        for renew in ({"verdict": "not_held", "by": "h2/b1"}, {"verdict": "error", "detail": "forge down"}, None):
            with self.subTest(renew=renew):
                result, calls = run(args=dict(BATCH_CHILD, lane="direct"),
                                    patch={"setup": {"acquire": HELD, "renew": renew}})
                self.assertEqual((result["stage"], result["at"]), ("claim-lost", "plan"))
                self.assertEqual(labels(calls), ["setup"])
                if renew and renew["verdict"] == "not_held":
                    self.assertNotIn("cont", result)
                else:
                    self.assertTrue(result["cont"]["claim_incomplete"])

    def test_the_direct_lane_setup_schema_lists_renew_as_the_standard_lane_does(self):
        _, direct = run(args=dict(ARGS, lane="direct"))
        _, standard = run()
        schema = schema_of(direct, "setup")
        self.assertEqual(schema["properties"]["renew"], schema_of(standard, "setup")["properties"]["renew"])
        self.assertNotIn("renew", schema.get("required", []))
        self.assertIn("holder, acquire, renew", prompt(direct, "setup"))

    def test_an_acquired_setup_reads_no_renew(self):
        result, calls = run(patch={"setup": {"renew": None}})
        self.assertEqual(result["stage"], "done")
        self.assertNotIn("owner-answer", labels(calls))


RENEW = f"forge-claim renew --repo owner/repo --issue 9 --holder {HOLDER} --branch issue-9-x"
# (at, the call that renews, nested): a nested renew rides in that call's reply as renew.
BOUNDARIES = [("tasks", "impl-1", True),
              ("final-review", "renew-final-review", False), ("verify", "verify", True),
              ("ship", "pr", True), ("merge", "merge", True)]
# The text each folded prompt runs after its renew.
STEP_MARK = {"impl-1": "task-1.md", "verify": "Run the project's declared verification",
             "pr": "open the pull request", "merge": "forge-claim land acquire"}


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
        for via in ("setup", "impl-1", "renew-final-review", "verify", "pr", "merge"):
            with self.subTest(via=via):
                self.assertIn("transient", prompt(calls, via))
        _, resumed = run(args=dict(ARGS, cont=RESUME_FOR_ANSWER))
        self.assertIn("transient", prompt(resumed, "owner-answer"))
        stopped, _ = run(patch={"pr": {"renew": None}})
        _, calls = run(args=dict(ARGS, cont=stopped["cont"]))
        self.assertEqual(schema_of(calls, "acquire")["properties"]["transient"], {"type": "boolean"})
        self.assertIn("transient", prompt(calls, "acquire"))

    def test_every_forge_claim_prompt_gives_the_long_bash_timeout(self):
        timeout = ("a Bash timeout of 20 minutes (1200000 ms). Only a land acquire command that ends in --wait gets more: "
                   "the flag takes no value, so write nothing after it, and the command itself waits for up to 50 minutes and then "
                   "answers land-contended by itself, so give it a Bash timeout of 60 minutes (3600000 ms) and never run it in the background.")
        _, calls = run()
        for via in ("setup", "impl-1", "renew-final-review", "verify", "pr", "merge"):
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
        _, calls = run(replies={"checks-2": {"state": "passed", "head": merge}},
                       patch={"pr": {"checks": {"state": "behind", "head": SHA}}, "sync-1": {"merge_commit": merge}})
        self.assertIn(timeout, prompt(calls, "checks-2"))

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
        self.assertTrue({"hold", "close-out"} <= seen, seen)


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


class ReviewSizingArgTest(unittest.TestCase):
    """#747: review_sizing is an opt-in boolean, checked before any agent."""

    def test_review_sizing_must_be_a_boolean(self):
        for bad in ("yes", 1, None):
            with self.subTest(bad=bad):
                result, calls = run(args=dict(ARGS, review_sizing=bad))
                self.assertEqual(result, {"stage": "args", "error": "review_sizing must be a boolean"})
                self.assertEqual(calls, [])

    def test_false_runs_like_absent(self):
        absent, absent_calls = run()
        off, off_calls = run(args=dict(ARGS, review_sizing=False))
        self.assertEqual(off["stage"], "done")
        self.assertEqual([(c["label"], c["prompt"]) for c in off_calls],
                         [(c["label"], c["prompt"]) for c in absent_calls])


class ReviewSizingPlanTest(unittest.TestCase):
    """#747: with sizing on and the Codex plan review configured, the Claude plan review narrows to rules, conventions and consistency."""

    def test_off_keeps_the_full_rubric(self):
        _, calls = run()
        text = prompt(calls, "plan-review")
        self.assertIn(FULL_RUBRIC, text)
        self.assertNotIn(CODEX_OWNS, text)

    def test_on_with_the_codex_plan_review_narrows_the_claude_rubric(self):
        result, calls = run(args=SIZED)
        self.assertEqual(result["stage"], "done")
        self.assertIn("plan-codex", labels(calls))
        text = prompt(calls, "plan-review")
        self.assertIn(CODEX_OWNS, text)
        self.assertNotIn(FULL_RUBRIC, text)
        self.assertNotIn("wrong or missing interfaces", text)
        for needle in ("an acceptance criterion with no task", "acceptance-planning.md", "documented conventions",
                       "internal inconsistency", "project-specific literal written into global skills or agents",
                       "/r/docs/standards", "context.md", "--json title,body,comments"):
            with self.subTest(needle=needle):
                self.assertIn(needle, text)
        # The rule-id instruction stays whole and comes before the Codex sentence, never inside its "do not sweep" clause.
        self.assertLess(text.index(RULE_ID), text.index(CODEX_OWNS))
        self.assertNotIn("do not sweep for it, or", text)
        off = prompt(run()[1], "plan-review")
        self.assertEqual(text.count("acceptance-planning.md"), off.count("acceptance-planning.md"))
        self.assertEqual(text.count(RULE_ID), 1)
        review = next(c for c in calls if c["label"] == "plan-review")
        self.assertEqual((review["agentType"], review["schema"]["properties"]["findings"]["items"]["properties"]["rule"]["enum"][0]),
                         ("reviewer", "R1"))

    def test_on_keeps_the_full_rubric_for_the_planner(self):
        _, calls = run(args=SIZED, replies={"plan-review": {"verdict": "findings",
                                                             "findings": [{"severity": "important", "summary": "gap"}]}})
        for label in ("plan", "plan-revise"):
            with self.subTest(label=label):
                self.assertIn(FULL_RUBRIC, prompt(calls, label))

    def test_on_without_a_plan_review_capability_keeps_the_full_rubric(self):
        _, calls = run(args=SIZED, patch={"setup": {"review_state": {"code": "available", "plan": "unsupported"}}})
        self.assertNotIn("plan-codex", labels(calls))
        text = prompt(calls, "plan-review")
        self.assertIn(FULL_RUBRIC, text)
        self.assertNotIn(CODEX_OWNS, text)


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
                # The revise changes the acceptance, so the ruleless trigger still gets its rules re-review (#819).
                first, _ = run(replies={"plan": plan, "plan-revise": with_criteria(HUMAN, EVIDENCE), "plan-review": kept,
                                        "plan-rules-review": None})
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
        # The revise changes the acceptance, so the ruleless trigger still gets its rules re-review (#819).
        plan = with_criteria(HUMAN, EVIDENCE)
        first, _ = run(replies={"plan": with_criteria(HUMAN), "plan-revise": plan, "plan-review": interface,
                                "plan-rules-review": None})
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

    CODEX_CASES = (("ruled", {"rule": "R2"}, {"rule": "R2"}), ("ruleless", {}, {"rule": "R2"}), ("other-rule", {"rule": "R2"}, {"rule": "R6"}))

    @staticmethod
    def report(**kw):
        return {"verdict": "findings", "findings": [dict({"severity": "important", "summary": "AC1 is not observable"}, **kw)]}

    def codex_replies(self, codex, rereviews):
        # The revise changes the acceptance, so a ruleless trigger still gets its rules re-review (#819).
        return {"plan": with_criteria(HUMAN), "plan-revise": with_criteria(HUMAN, EVIDENCE), "plan-rules-revise": self.REVISED,
                "plan-codex": {"available": True, **self.report(**codex)}, "plan-rules-review": rereviews}

    def test_a_codex_triggered_revise_gets_the_rules_only_revise_and_proceeds_when_clean(self):
        # #823: the rules re-review keeps neither source nor finding identity, so its rule findings on a Codex-triggered plan
        # are taken as its own: they get the one rules-only revise, and a clean re-review of that proceeds.
        for name, codex, rereview in self.CODEX_CASES:
            with self.subTest(codex=name):
                replies = self.codex_replies(codex, [self.report(**rereview), {"verdict": "pass", "findings": []}])
                result, calls = run(replies=replies, patch={"close-out": {"issue_state": "OPEN"}})
                names = labels(calls)
                self.assertNotEqual(result["stage"], "plan-review")
                self.assertEqual((names.count("plan-revise"), names.count("plan-rules-revise"), names.count("plan-rules-review")), (1, 1, 2))
                self.assertIn(f'"rule":"{rereview["rule"]}"', prompt(calls, "plan-rules-revise"))
                self.assertIn("impl-1", names)

    def test_a_kept_plan_whose_triggers_included_codex_resumes_with_one_rules_revise(self):
        # #823: the kept findings record the Codex trigger, and the resume still runs the rules-only revise, not a replan.
        for name, codex, rereview in self.CODEX_CASES:
            with self.subTest(codex=name):
                left = self.report(**rereview)
                first, calls = run(replies=self.codex_replies(codex, left))
                self.assertEqual(first["stage"], "plan-review")
                self.assertEqual(labels(calls).count("plan-rules-revise"), 1)
                kept = first["cont"]["plan_findings"]
                self.assertEqual(kept["rounds"], 1)
                self.assertEqual([f.get("source") for f in kept["findings"]], ["codex"])
                self.assertEqual(first["cont"]["plan"], self.REVISED)
                result, calls = run(args=dict(ARGS, cont=first["cont"]), patch={"close-out": {"issue_state": "OPEN"}})
                names = labels(calls)
                for label in ("plan", "plan-revise", "plan-review", "plan-codex"):
                    self.assertNotIn(label, names)
                self.assertEqual((names.count("plan-rules-revise"), names.count("plan-rules-review")), (1, 1))
                self.assertIn("impl-1", names)
                self.assertNotIn("plan_findings", result.get("cont") or {})
                # The rounds cap holds: a second failed rules revise drops the plan, and the next resume plans again.
                result, calls = run(args=dict(ARGS, cont=first["cont"]), replies={"plan-rules-review": left})
                self.assertEqual(result["stage"], "plan-review")
                self.assertEqual(labels(calls).count("plan-rules-revise"), 1)
                self.assertIsNone(result["cont"]["plan"])
                self.assertNotIn("plan_findings", result["cont"])
                self.assertNotIn("impl-1", labels(calls))

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

    def test_a_remaining_codex_or_ruleless_finding_stops_with_no_rules_revise(self):
        # #823 keeps this stop: whatever triggered the revise, a finding left with source codex or with no rule id is not
        # one the rules-only revise may settle.
        plan = with_criteria(HUMAN)
        echoed = {"verdict": "findings", "findings": [{"severity": "important", "rule": "R2", "summary": "s", "source": "codex"}]}
        bare = {"verdict": "findings", "findings": [{"severity": "important", "summary": "AC3 breaks a rule"}]}
        for trigger in ("claude", "codex"):
            for left in (echoed, bare):
                with self.subTest(trigger=trigger, left=left["findings"][0]["summary"]):
                    replies = {"plan": plan, "plan-revise": plan, "plan-review": self.RULE_FINDING, "plan-rules-review": left}
                    if trigger == "codex":
                        replies["plan-codex"] = {"available": True, **self.RULE_FINDING}
                    result, calls = run(replies=replies)
                    self.assertEqual(result["stage"], "plan-review")
                    self.assertNotIn("plan-rules-revise", labels(calls))
                    self.assertEqual(result["cont"]["plan"], plan)
                    self.assertEqual(result["cont"]["plan_findings"]["rounds"], 0)
                    self.assertNotIn("impl-1", labels(calls))
                    # The resume runs no rules-only revise either: the plan is planned again and reviewed in full.
                    again, calls = run(args=dict(ARGS, cont=result["cont"]))
                    self.assertNotIn("plan-rules-revise", labels(calls))
                    self.assertEqual(labels(calls).count("plan"), 1)
                    self.assertIn("plan-review", labels(calls))

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


class PlanRuleMessagesTest(unittest.TestCase):
    """#988: a program rule message names every way out, and a minor finding on a blocked criterion reaches the rules revise."""

    CAPPED = dict(PLAN["acceptance"][0], id="AC5", text="the evaluation costs at most $5", metric=True)
    HELD = criterion(EVIDENCE, id="AC5", text="the evaluation costs at most $5", metric=True, verify_ac="AC5", verify_mode="observe")
    BETTER = "label AC5 plain code and describe the bound as the cap AC2 enforces"
    HUMAN_WAYS = ("name the one of senses, hands, credentials, money, taste that applies", "make the criterion code or evidence")
    CODE_WAY = "make it a code criterion when a test, CI or a local evaluation shows it before merge (R1)"
    # Each program message: the row of PlanRulesTest.ROWS it answers, then every way out it must name.
    WAYS = (
        (0, ("make it a code criterion, graded at ship", "trigger the check on that")),
        (1, ("drop the post-merge ask", "keep a human check only for")),
        (2, HUMAN_WAYS),
        (3, HUMAN_WAYS),
        (4, ("add one", CODE_WAY)),
        (7, ("a committed script or a probe", CODE_WAY)),
        (8, ("set its ac and kind to this criterion's",)),
    )

    @staticmethod
    def program_findings(bad):
        plan = with_criteria(bad)
        result, _ = run(replies={"plan": plan, "plan-revise": plan, "plan-rules-revise": plan})
        return [r["summary"] for r in result["rules"] if r.get("ac") == bad["id"]]

    @staticmethod
    def review(*findings):
        return {"verdict": "findings" if findings else "pass", "findings": list(findings)}

    @staticmethod
    def finding(severity, ac=None, summary="s", rule="R5"):
        return dict({"severity": severity, "rule": rule, "summary": summary}, **({} if ac is None else {"ac": ac}))

    def test_the_r5_message_names_both_ways_out(self):
        for bad in (self.CAPPED, criterion(EVIDENCE, metric=True), criterion(HUMAN, metric=True)):
            with self.subTest(kind=bad["kind"]):
                (summary,) = [s for s in self.program_findings(bad) if s.startswith("R5 ")]
                self.assertIn("an evidence check with mode observe", summary)
                self.assertIn(f"or drop metric and {self.CODE_WAY}", summary)
        (summary,) = [s for s in self.program_findings(criterion(NOTE, metric=True)) if s.startswith("R5 ")]
        self.assertIn("drop metric (R9)", summary)
        self.assertIn("make it an evidence check with mode observe", summary)

    def test_every_other_program_rule_message_names_its_ways_out(self):
        for index, ways in self.WAYS:
            rule, bad = PlanRulesTest.ROWS[index]
            with self.subTest(row=index, rule=rule):
                summaries = [s for s in self.program_findings(bad) if s.startswith(f"{rule} ")]
                self.assertTrue(summaries)
                for way in ways:
                    self.assertTrue(any(way in s for s in summaries), (way, summaries))
        for _, bad in PlanRulesTest.NOTE_ROWS:
            with self.subTest(note=sorted(bad)):
                (summary,) = self.program_findings(bad)
                self.assertIn("drop them", summary)
                self.assertIn("make the criterion evidence (R4)", summary)

    def test_the_rules_review_is_asked_for_the_criterion_id(self):
        plan = with_criteria(self.CAPPED)
        _, calls = run(replies={"plan": plan, "plan-revise": plan, "plan-rules-revise": plan})
        self.assertIn("the criterion's id in its ac", prompt(calls, "plan-rules-review"))
        item = schema_of(calls, "plan-rules-review")["properties"]["findings"]["items"]
        self.assertEqual(item["properties"]["ac"], {"type": "string"})
        self.assertNotIn("ac", item["required"])

    def test_a_minor_finding_on_a_criterion_the_program_blocks_reaches_the_rules_revise(self):
        plan = with_criteria(self.CAPPED)
        for ac in ("AC5", "ac5", " Ac 5 "):
            with self.subTest(ac=ac):
                _, calls = run(replies={"plan": plan, "plan-revise": plan, "plan-rules-revise": plan,
                                        "plan-rules-review": self.review(self.finding("minor", ac, self.BETTER))})
                revise = prompt(calls, "plan-rules-revise")
                self.assertIn("also noted", revise)
                self.assertIn(self.BETTER, revise)
                self.assertLess(revise.index('"summary":"R5 (AC5)'), revise.index(self.BETTER))

    def test_a_minor_finding_on_a_criterion_the_reviewer_blocks_reaches_the_rules_revise(self):
        plan = with_criteria(HUMAN)
        rereview = self.review(self.finding("important", "AC3", "not a human check", "R3"), self.finding("minor", "ac3", self.BETTER, "R3"))
        _, calls = run(replies={"plan": plan, "plan-revise": plan, "plan-rules-revise": plan,
                                "plan-review": PlanRulesTest.RULE_FINDING, "plan-rules-review": rereview})
        self.assertIn(self.BETTER, prompt(calls, "plan-rules-revise"))

    def test_a_minor_finding_on_another_criterion_neither_travels_nor_blocks(self):
        plan = with_criteria(self.CAPPED)
        for name, minor in (("other", self.finding("minor", "AC1", self.BETTER)), ("no-id", self.finding("minor", None, self.BETTER)),
                            ("in-prose", self.finding("minor", None, f"AC5: {self.BETTER}"))):
            with self.subTest(minor=name):
                result, calls = run(replies={"plan": plan, "plan-revise": plan, "plan-rules-revise": plan,
                                             "plan-rules-review": self.review(minor)})
                revise = prompt(calls, "plan-rules-revise")
                self.assertNotIn("also noted", revise)
                self.assertNotIn(self.BETTER, revise)
                self.assertEqual([r["severity"] for r in result["rules"]], ["important"])
                self.assertNotIn("noted", result["cont"]["plan_findings"])
        # With nothing blocking, a minor finding that names a criterion starts no rules revise and stops nothing.
        clean = with_criteria(HUMAN)
        result, calls = run(replies={"plan": clean, "plan-revise": clean, "plan-review": PlanRulesTest.RULE_FINDING,
                                     "plan-rules-review": self.review(self.finding("minor", "AC3", self.BETTER))},
                            patch={"close-out": {"issue_state": "OPEN"}})
        self.assertNotIn("plan-rules-revise", labels(calls))
        self.assertIn("impl-1", labels(calls))
        self.assertNotEqual(result["stage"], "plan-review")

    def chain(self):
        # nodocom issue 2215: the revise labels AC5 code with a metric, the program reports R5, the rules review gives the right
        # fix as a minor finding, the rules revise makes AC5 an observed hold, and the second rules review reports R1.
        plan = with_criteria(self.CAPPED)
        first = self.review(self.finding("minor", "AC5", self.BETTER))
        second = self.review(self.finding("important", "AC5", "a local evaluation is a code criterion", "R1"),
                             self.finding("minor", "AC5", self.BETTER, "R1"))
        return run(replies={"plan": plan, "plan-revise": plan, "plan-rules-revise": with_criteria(self.HELD),
                            "plan-rules-review": [first, second]})

    def test_the_2215_chain_hands_the_revise_the_minor_finding(self):
        result, calls = self.chain()
        names = labels(calls)
        self.assertEqual((names.count("plan-revise"), names.count("plan-rules-revise"), names.count("plan-rules-review")), (1, 1, 2))
        revise = prompt(calls, "plan-rules-revise")
        self.assertIn('"summary":"R5 (AC5): metric is set', revise)
        self.assertIn("drop metric and make it a code criterion", revise)
        self.assertIn(self.BETTER, revise)
        # The noted finding is context only: the stop lists the one blocking finding and still allows one more rules revise.
        self.assertEqual(result["stage"], "plan-review")
        self.assertEqual([(r["rule"], r["severity"]) for r in result["rules"]], [("R1", "important")])
        self.assertIn("1 finding(s)", result["reason"])
        kept = result["cont"]["plan_findings"]
        self.assertEqual(kept["rounds"], 1)
        self.assertEqual([(n["severity"], n["ac"]) for n in kept["noted"]], [("minor", "AC5")])

    def test_a_resumed_rules_revise_gets_the_kept_minor_finding(self):
        first, _ = self.chain()
        fixed = with_criteria(dict(self.CAPPED, metric=False))
        _, calls = run(args=dict(ARGS, cont=first["cont"]), replies={"plan-rules-revise": fixed},
                       patch={"close-out": {"issue_state": "OPEN"}})
        revise = prompt(calls, "plan-rules-revise")
        self.assertIn('"rule":"R1"', revise)
        self.assertIn(self.BETTER, revise)
        self.assertIn("impl-1", labels(calls))
        # A kept note that matches no blocking criterion, or is not minor, is not passed on.
        cont = json.loads(json.dumps(first["cont"]))
        cont["plan_findings"]["noted"] = [self.finding("minor", "AC1", "stray-note"), self.finding("important", "AC5", "loud-note")]
        _, calls = run(args=dict(ARGS, cont=cont), replies={"plan-rules-revise": fixed}, patch={"close-out": {"issue_state": "OPEN"}})
        revise = prompt(calls, "plan-rules-revise")
        self.assertNotIn("stray-note", revise)
        self.assertNotIn("loud-note", revise)

    def test_a_bound_a_pre_merge_run_enforces_is_a_code_criterion_with_no_metric(self):
        """#988 (a): the planner sets metric only on an observed evidence criterion, so R1 and R5 cannot both fire on the correct form."""
        bound = dict(self.CAPPED, metric=False)
        _, calls = run(replies={"plan": with_criteria(bound)})
        text = prompt(calls, "plan")
        metric = text[text.index("set metric true"):]
        metric = metric[:metric.index(". ")]
        self.assertIn("set metric true only on an evidence criterion, never on a note (R9: ", metric)
        self.assertIn("mode observe (R5)", metric)
        self.assertIn("a code criterion with metric false (R1)", metric)
        self.assertNotIn("of a code, evidence or human criterion", text)
        self.assertNotIn("plan-revise", labels(calls))
        self.assertIn("impl-1", labels(calls))
        (r5,) = [line for line in RULES_FILE.read_text(encoding="utf-8").splitlines() if line.startswith("- **R5.")]
        self.assertIn("that only a deploy or observation over time shows is a check with `mode: observe`", r5)
        self.assertIn("is not a metric: it is part of its `code` criterion (R1)", r5)

    def test_a_criterion_two_rules_pull_apart_stops_as_an_owner_decision(self):
        """#988 (b): the stop names both rules and the criterion, before anything the cap could cut."""
        result, _ = self.chain()
        self.assertEqual(result["conflict"], {"ac": "AC5", "rules": ["R5", "R1"], "revises_left": 1})
        self.assertTrue(result["reason"].startswith("plan-review: the acceptance rules R5 and R1 conflict for AC5: "), result["reason"])
        self.assertIn("an owner decision on how AC5 is classified is the expected way out: "
                      "a relaunch without one gets the one rules revise left", result["reason"])
        # With no revise left the plan is dropped, and the reason says that instead.
        dropped, _ = self.relaunched()
        self.assertEqual(dropped["conflict"], {"ac": "AC5", "rules": ["R1", "R5"], "revises_left": 0})
        self.assertIn("the plan was dropped, and a relaunch without one plans again", dropped["reason"])
        self.assertNotIn("rules revise left", dropped["reason"])

    def test_a_mechanical_survivor_is_not_a_conflict(self):
        """#988 (b): only a swap between classification rules is a conflict; the rest stays a plain plan-review stop."""
        plan = with_criteria(HUMAN)
        r3 = self.review(self.finding("important", "AC3", "not a human check", "R3"))
        cases = (
            ("same rule survives", r3, self.finding("important", "AC3", "not a human check", "R3")),
            ("R3 then R4", r3, self.finding("important", "AC3", "the verify block is wrong", "R4")),
            ("R4 then R1", self.review(self.finding("important", "AC3", "no block", "R4")), self.finding("important", "AC3", "s", "R1")),
            ("no id", r3, self.finding("important", None, "s", "R1")),
            ("another criterion", r3, self.finding("important", "AC1", "s", "R1")),
        )
        for name, before, after in cases:
            with self.subTest(case=name):
                result, calls = run(replies={"plan": plan, "plan-revise": plan, "plan-rules-revise": plan, "plan-review": PlanRulesTest.RULE_FINDING,
                                             "plan-rules-review": [before, self.review(after)]})
                self.assertEqual(result["stage"], "plan-review")
                self.assertEqual(labels(calls).count("plan-rules-revise"), 1)
                self.assertNotIn("conflict", result)
                self.assertNotIn("conflict", result["reason"])
                self.assertEqual(result["cont"]["plan_findings"]["rounds"], 1)
        # The earlier rule still blocking beside the new one is no swap either.
        both = self.review(self.finding("important", "AC3", "not a human check", "R3"), self.finding("important", "AC3", "s", "R1"))
        result, _ = run(replies={"plan": plan, "plan-revise": plan, "plan-rules-revise": plan, "plan-review": PlanRulesTest.RULE_FINDING,
                                 "plan-rules-review": [r3, both]})
        self.assertNotIn("conflict", result)
        # R3 gone and R1 new on the same criterion is one.
        swap = self.review(self.finding("important", "ac3", "s", "R1"))
        result, _ = run(replies={"plan": plan, "plan-revise": plan, "plan-rules-revise": plan, "plan-review": PlanRulesTest.RULE_FINDING,
                                 "plan-rules-review": [r3, swap]})
        self.assertEqual(result["conflict"], {"ac": "ac3", "rules": ["R3", "R1"], "revises_left": 1})

    def test_no_existing_rule_stop_is_a_conflict(self):
        """#988 review: the rule rows that stop at plan review with their rule left are relaunchable stops, as before."""
        for rule, bad in PlanRulesTest.ROWS + PlanRulesTest.NOTE_ROWS:
            with self.subTest(rule=rule, ac=bad["id"]):
                plan = with_criteria(bad)
                result, _ = run(replies={"plan": plan, "plan-revise": plan, "plan-rules-revise": plan})
                self.assertEqual(result["stage"], "plan-review")
                self.assertNotIn("conflict", result)

    def test_the_notes_and_the_prior_findings_are_bounded(self):
        plan = with_criteria(self.CAPPED)
        notes = self.review(*[self.finding("minor", "AC5", f"note-{i}-end") for i in range(10)])
        _, calls = run(replies={"plan": plan, "plan-revise": plan, "plan-rules-revise": plan, "plan-rules-review": notes})
        revise = prompt(calls, "plan-rules-revise")
        self.assertEqual([i for i in range(10) if f"note-{i}-end" in revise], list(range(8)))
        dropped, _ = self.relaunched()
        cont = json.loads(json.dumps(dropped["cont"]))
        cont["prior_findings"] = [self.finding("important", "AC5", f"prior-{i}-end") for i in range(25)]
        result, calls = run(args=dict(ARGS, cont=cont), replies={"plan-review": None})
        self.assertEqual([f["summary"] for f in result["cont"]["prior_findings"]], [f"prior-{i}-end" for i in range(20)])
        self.assertNotIn("prior-20-end", prompt(calls, "plan"))

    def test_only_the_fresh_plan_prompt_shows_the_prior_findings(self):
        dropped, _ = self.relaunched()
        earlier = "An earlier plan of this issue was dropped"
        plan = with_criteria(HUMAN)
        _, calls = run(args=dict(ARGS, cont=dropped["cont"]),
                       replies={"plan": plan, "plan-revise": plan, "plan-rules-revise": plan, "plan-review": PlanRulesTest.RULE_FINDING,
                                "plan-rules-review": PlanRulesTest.RULE_FINDING})
        self.assertIn(earlier, prompt(calls, "plan"))
        for label in ("plan-revise", "plan-rules-revise"):
            self.assertNotIn(earlier, prompt(calls, label), label)
        wrong = bplan([dict(BR, name="dev")])
        _, calls = run(args=dict(ARGS, cont=dropped["cont"]), replies={"plan": wrong, "plan-branch-revise": wrong})
        self.assertIn(earlier, prompt(calls, "plan"))
        self.assertNotIn(earlier, prompt(calls, "plan-branch-revise"))

    def test_the_rules_review_reads_the_owner_decisions(self):
        first, _ = self.chain()
        decision = "D: AC5 is a code criterion and the 5 USD bound is the cap AC2 enforces."
        _, calls = run(args=dict(ARGS, cont=first["cont"], decisions=decision), replies={"plan-rules-revise": with_criteria(self.CAPPED)})
        self.assertIn(decision, prompt(calls, "plan-rules-review"))
        _, calls = run(replies={"plan": with_criteria(self.CAPPED)})
        self.assertNotIn("owner's decisions", prompt(calls, "plan-rules-review"))

    def test_the_command_message_lists_no_empty_id_list(self):
        outside = criterion(EVIDENCE, verify_run={"command": "smoke"})
        plan = with_criteria(outside)
        result, _ = run(replies={"plan": plan, "plan-revise": plan, "plan-rules-revise": plan}, patch={"setup": {"verification": []}})
        (summary,) = [r["summary"] for r in result["rules"] if "unattended command" in r["summary"]]
        self.assertIn("use a committed script or a probe", summary)
        self.assertNotIn("[]", summary)
        (summary,) = [s for s in self.program_findings(outside) if "unattended command" in s]
        self.assertIn('use one of ["build"], a committed script or a probe', summary)

    def test_a_criterion_that_only_restates_the_declared_verification_is_refused(self):
        """#993: the verify step proves it, so the program asks for it to be dropped; anything naming a test of its own passes."""
        setup = {"setup": {"verification": [{"id": "lint", "argv": ["devenv", "tasks", "run", "nodo:lint"], "cwd": "."},
                                            {"id": "test", "argv": ["devenv", "tasks", "run", "nodo:test:fast"], "cwd": "."}]}}
        for text in ("`nodo:lint` and `nodo:test:fast` pass at the branch head", "Lint and test pass.", "devenv tasks run nodo:lint exits 0"):
            with self.subTest(text=text):
                plan = with_criteria({"id": "AC6", "text": text, "kind": "code"})
                result, calls = run(replies={"plan": plan, "plan-revise": plan, "plan-rules-revise": plan}, patch=setup)
                self.assertEqual(result["stage"], "plan-review")
                (found,) = result["rules"]
                self.assertEqual((found["rule"], found["ac"], found["severity"]), ("verify", "AC6", "important"))
                self.assertIn("only restates the declared verification", found["summary"])
                self.assertIn("drop the criterion", found["summary"])
                self.assertEqual(labels(calls).count("plan-rules-revise"), 1)
                self.assertIn("drop the criterion", prompt(calls, "plan-rules-revise"))
        for text in ("the lint rule for unused imports passes on the new module", "test_parser_rejects_empty_input passes",
                     "the suite passes at the branch head", "works"):
            with self.subTest(kept=text):
                plan = with_criteria({"id": "AC6", "text": text, "kind": "code"})
                _, calls = run(replies={"plan": plan}, patch=dict(setup, **{"close-out": {"issue_state": "OPEN"}}))
                self.assertNotIn("plan-revise", labels(calls))
        _, calls = run()
        self.assertIn("Return no criterion that only restates a declared verification command passing", prompt(calls, "plan"))
        # A plan whose every criterion restates the verification keeps them: dropping them would leave no criterion and no plan.
        restated = [{"id": "AC1", "text": "nodo:lint passes", "kind": "code"}, {"id": "AC2", "text": "test passes at the branch head", "kind": "code"}]
        for name, acceptance in (("sole", restated[:1]), ("all", restated)):
            with self.subTest(only=name):
                result, calls = run(replies={"plan": dict(PLAN, acceptance=acceptance)}, patch=setup)
                self.assertNotIn("plan-revise", labels(calls))
                self.assertNotIn("plan-rules-revise", labels(calls))
                self.assertIn("impl-1", labels(calls))
                self.assertNotIn(result["stage"], ("plan", "plan-review"))

    def test_no_final_review_is_asked_to_run_the_declared_suite(self):
        """#993: the chunk reviews and the integration review leave the declared verification to the verify step."""
        owned = "The verify step runs the declared verification: run only the targeted tests a finding needs, never the whole suite."
        _, calls = run(replies={"plan": dict(PLAN, tasks=tasks(4))})
        for label in ("final-1", "final-2", "final-integration"):
            self.assertEqual(prompt(calls, label).count(owned), 1, label)
        _, calls = run()
        self.assertEqual(prompt(calls, "final-1").count(owned), 1)
        self.assertEqual(PROGRAM.read_text(encoding="utf-8").count(owned), 1)

    def relaunched(self):
        # The relaunch of 2215: the kept plan's rules revise makes AC5 code but leaves metric set, so the program reports R5 again.
        first, _ = self.chain()
        return run(args=dict(ARGS, cont=first["cont"]), replies={"plan-rules-revise": with_criteria(self.CAPPED)})

    def test_the_findings_of_a_dropped_plan_survive_until_a_plan_is_accepted(self):
        """#988 (c): the second failed rules revise drops the plan; what was found on it reaches the next planner."""
        dropped, _ = self.relaunched()
        self.assertEqual(dropped["stage"], "plan-review")
        self.assertIsNone(dropped["cont"]["plan"])
        self.assertNotIn("plan_findings", dropped["cont"])
        prior = dropped["cont"]["prior_findings"]
        self.assertEqual([(f["rule"], f["ac"]) for f in prior], [("R5", "AC5"), ("R1", "AC5")])
        self.assertTrue(all(f["severity"] == "important" for f in prior))
        # A stop of the run that plans again, before any plan is accepted, still carries them.
        asked, calls = run(args=dict(ARGS, cont=dropped["cont"]),
                           replies={"plan": {"status": "needs_user", "questions": [{"question": "q", "options": ["a b c."]}]}})
        text = prompt(calls, "plan")
        self.assertIn("An earlier plan of this issue was dropped at plan review", text)
        self.assertIn("a local evaluation is a code criterion", text)
        self.assertIn('"summary":"R5 (AC5): metric is set', text)
        self.assertEqual(asked["stage"], "plan")
        self.assertEqual(asked["cont"]["prior_findings"], prior)
        again, _ = run(args=dict(ARGS, cont=asked["cont"]), replies={"plan-review": None})
        self.assertEqual(again["stage"], "plan-review")
        self.assertEqual(again["cont"]["prior_findings"], prior)
        # A plan that passes review ends the carry, and a first run's prompt never mentions an earlier plan.
        done, calls = run(args=dict(ARGS, cont=again["cont"]), patch={"close-out": {"issue_state": "OPEN"}})
        self.assertIn("impl-1", labels(calls))
        self.assertNotIn("prior_findings", done.get("cont") or {})
        _, calls = run()
        self.assertNotIn("An earlier plan", prompt(calls, "plan"))

    def test_a_revise_that_drops_the_plan_keeps_what_its_review_found(self):
        """#988 (c): a revise that comes back as questions drops the plan; the findings it was fixing are not lost."""
        ask = {"status": "needs_user", "questions": [{"question": "q", "options": ["a b c."]}]}
        plan = with_criteria(HUMAN)
        for label in ("plan-revise", "plan-rules-revise"):
            with self.subTest(label=label):
                replies = {"plan": plan, "plan-revise": plan, "plan-review": PlanRulesTest.RULE_FINDING,
                           "plan-rules-review": PlanRulesTest.RULE_FINDING}
                result, _ = run(replies=dict(replies, **{label: ask}))
                self.assertEqual(result["stage"], "plan")
                self.assertIsNone(result["cont"]["plan"])
                self.assertEqual([f["rule"] for f in result["cont"]["prior_findings"]], ["R2"])
        first, _ = PlanRulesTest().keep_stop()
        result, _ = run(args=dict(ARGS, cont=first["cont"]), replies={"plan-rules-revise": ask})
        self.assertIsNone(result["cont"]["plan"])
        self.assertEqual([f["rule"] for f in result["cont"]["prior_findings"]], ["R2"])
        # A kept plan no rules revise may settle is planned again with its findings in the prompt.
        bare = {"verdict": "findings", "findings": [{"severity": "important", "summary": "interface-mismatch-988"}]}
        first, _ = run(replies={"plan": plan, "plan-revise": with_criteria(HUMAN, EVIDENCE), "plan-review": bare, "plan-rules-review": None})
        _, calls = run(args=dict(ARGS, cont=first["cont"]))
        self.assertIn("interface-mismatch-988", prompt(calls, "plan"))


class PlanTurnStructureTest(unittest.TestCase):
    """#819: the planner writes its files in one message, revises with Edit, and self-checks three finding classes."""

    PLANNERS = ("plan", "plan-revise", "plan-rules-revise", "plan-branch-revise", "plan-task-revise")
    WRITE_ONCE = ("write the code map, plan.md and every task file as parallel Write calls in one message",
                  "a second message only if the output limit forces it", "then run any checks in one message")
    REVISE = ("first list /r/.git/worktrees/w/deliver-standard/*.md and load them all as parallel Read calls in one message, then fix",
              "fix the findings with Edit in place", "rewrite a whole file only when most of it changes",
              "leave each acceptance criterion's text unchanged unless fixing a finding requires changing it")
    SELF_CHECK = ("run every grep or deny gate a task prescribes against the text this plan requires and confirm it does not reject that text",
                  "for each invariant, threshold and decision a task states, name the test case that fails when that one rule is removed; one with no such case needs a test",
                  "list for each new test or doc the CI workflow test list, the generated index and the project gate that must also change")

    def calls(self):
        # The scenario of PlanRulesTest.keep_stop: plan, plan-revise and plan-rules-revise all run.
        plan = with_criteria(HUMAN)
        _, calls = run(replies={"plan": plan, "plan-revise": plan, "plan-rules-revise": PlanRulesTest.REVISED,
                                "plan-review": PlanRulesTest.RULE_FINDING, "plan-rules-review": PlanRulesTest.RULE_FINDING})
        return calls

    def test_the_first_plan_writes_every_file_in_one_message(self):
        text = prompt(self.calls(), "plan")
        for needle in self.WRITE_ONCE:
            self.assertIn(needle, text)
            self.assertLess(text.index(needle), text.index("Plan this issue."))
        for needle in self.REVISE:
            self.assertNotIn(needle, text)

    def test_both_revises_load_once_and_edit_in_place(self):
        calls = self.calls()
        for label in ("plan-revise", "plan-rules-revise"):
            text = prompt(calls, label)
            for needle in self.REVISE:
                self.assertIn(needle, text, label)
                self.assertLess(text.index(needle), text.index("Plan this issue."), label)
            self.assertNotIn("parallel Write calls", text, label)
            # #967: one cat of the directory overflows the Bash output cap.
            for gone in ("cat ", "with one command"):
                self.assertNotIn(gone, text[:text.index("Plan this issue.")], label)

    def test_the_load_sentence_is_no_longer_than_the_one_command_it_replaced(self):
        source = PROGRAM.read_text(encoding="utf-8")
        edits = re.search(r"const PLAN_EDITS = `([^`]*)`", source).group(1)
        self.assertNotIn("cat ", edits)
        self.assertLessEqual(len(edits), 399)

    def test_only_the_planner_gets_the_self_check_and_the_reviewer_rubric_is_untouched(self):
        calls = self.calls()
        for label in self.PLANNERS[:3]:
            text = prompt(calls, label)
            for needle in self.SELF_CHECK:
                self.assertIn(needle, text, label)
                self.assertGreater(text.index(needle), text.index("check the plan against the review it will get"), label)
        for call in all_calls() + calls:
            if call["label"] not in self.PLANNERS:
                for needle in self.SELF_CHECK + self.WRITE_ONCE + self.REVISE:
                    self.assertNotIn(needle, call["prompt"], call["label"])
        source = PROGRAM.read_text(encoding="utf-8")
        rubric = re.search(r"const PLAN_RUBRIC = `([^`]*)`", source).group(1)
        self.assertEqual(rubric, "an acceptance criterion with no task, a task whose test cannot fail, wrong or missing interfaces, "
                                 "a design choice that breaks the project's documented conventions, or a project-specific literal "
                                 "written into global skills or agents")


class RulesRereviewSkipTest(unittest.TestCase):
    """#819 AC2: a revise no rule triggered, clean by planRules and with unchanged acceptance, gets no rules re-review."""

    BARE = {"verdict": "findings", "findings": [{"severity": "important", "summary": "interface mismatch"}]}
    LEFT = {"verdict": "findings", "findings": [{"severity": "important", "summary": "AC2 breaks a rule"}]}
    SKIPPED = "plan rules re-review skipped"
    OPEN = {"close-out": {"issue_state": "OPEN"}}

    def go(self, plan, revised, review=None, **more):
        # A rules re-review that would block, were it run (ruleless, so no rules-only revise follows it).
        replies = {"plan": plan, "plan-revise": revised, "plan-review": review or self.BARE,
                   "plan-rules-review": self.LEFT, **more}
        out = run_out(replies=replies, patch=self.OPEN)
        return out["result"], labels(out["calls"]), [line for line in out["logs"] if self.SKIPPED in line]

    def test_a_ruleless_trigger_with_unchanged_acceptance_skips_the_rules_rereview_and_proceeds(self):
        plan = with_criteria(EVIDENCE, HUMAN)
        # The tasks may change, and verify's key order is not a change.
        reordered = criterion(EVIDENCE)
        reordered["verify"] = dict(reversed(list(reordered["verify"].items())))
        revised = with_criteria(reordered, HUMAN, tasks=tasks(2))
        result, names, skipped = self.go(plan, revised)
        self.assertEqual(names.count("plan-revise"), 1)
        self.assertNotIn("plan-rules-review", names)
        self.assertNotIn("plan-rules-revise", names)
        self.assertIn("impl-2", names)
        self.assertNotEqual(result["stage"], "plan-review")
        self.assertEqual(len(skipped), 1)

    def test_a_codex_ruleless_trigger_skips_too(self):
        plan = with_criteria(HUMAN)
        _, names, skipped = self.go(plan, plan, review={"verdict": "pass", "findings": []},
                                    **{"plan-codex": {"available": True, **self.BARE}})
        self.assertNotIn("plan-rules-review", names)
        self.assertIn("impl-1", names)
        self.assertEqual(len(skipped), 1)

    def test_a_trigger_carrying_a_rule_still_runs_the_rules_rereview(self):
        plan = with_criteria(HUMAN)
        mixed = {"verdict": "findings", "findings": self.BARE["findings"] + PlanRulesTest.RULE_FINDING["findings"]}
        codex = {"plan-codex": {"available": True, **PlanRulesTest.RULE_FINDING}}
        for name, review, more in (("claude", mixed, {}), ("codex", self.BARE, codex)):
            with self.subTest(source=name):
                result, names, skipped = self.go(plan, plan, review=review, **more)
                self.assertEqual(names.count("plan-rules-review"), 1)
                self.assertEqual(result["stage"], "plan-review")
                self.assertNotIn("impl-1", names)
                self.assertEqual(skipped, [])

    def test_a_changed_criterion_still_runs_the_rules_rereview(self):
        plan = with_criteria(EVIDENCE)
        code = PLAN["acceptance"][0]
        changes = (
            # The rules judge the wording: a code criterion reworded into a post-deploy threshold keeps every other member.
            ("text", [dict(code, text="p95 latency stays under 200 ms for a week after the deploy"), EVIDENCE]),
            ("kind", [code, criterion(HUMAN, id="AC2", verify_ac="AC2")]),
            ("verify", [code, criterion(EVIDENCE, verify_host="h2")]),
            ("metric", [code, criterion(EVIDENCE, metric=True, verify_mode="observe")]),
            ("id", [code, criterion(EVIDENCE, id="AC7", verify_ac="AC7")]),
            ("order", [EVIDENCE, code]),
            ("added", [code, EVIDENCE, HUMAN]),
            ("removed", [code]),
        )
        for name, acceptance in changes:
            with self.subTest(changed=name):
                result, names, skipped = self.go(plan, dict(PLAN, acceptance=acceptance))
                self.assertEqual(names.count("plan-rules-review"), 1)
                self.assertEqual(result["stage"], "plan-review")
                self.assertNotIn("impl-1", names)
                self.assertEqual(skipped, [])

    REWORDED = "p95 latency stays under 200 ms for a week after the deploy"

    def naming(self, summary, **more):
        return {"verdict": "findings", "findings": [{"severity": "important", "summary": summary, **more}]}

    @staticmethod
    def retyped(plan, **top):
        """The planner's reply after a revise: every criterion's text typed again, differently."""
        return dict(plan, acceptance=[dict(a, text=a["text"] + ", retyped") for a in plan["acceptance"]], **top)

    def kept_whole(self, plan, reply, **more):
        """The rules re-review runs and the plan kept is the reply exactly, less criteria_edited."""
        result, names, skipped = self.go(plan, reply, **more)
        self.assertEqual(names.count("plan-rules-review"), 1)
        self.assertEqual(skipped, [])
        self.assertEqual(result["stage"], "plan-review")
        final = more.get("plan-branch-revise", reply)
        self.assertEqual(result["cont"]["plan"], {k: v for k, v in final.items() if k != "criteria_edited"})
        return result

    def test_a_retyped_text_no_finding_names_keeps_the_earlier_text_and_skips(self):
        """The planner retypes every criterion in its reply though it reworded none: the earlier text stands."""
        plan = with_criteria(EVIDENCE, HUMAN)
        # AC10 and BAC2 are other words, not AC1 or AC2.
        for name, review in (("bare", self.BARE), ("other ids", self.naming("AC10 and BAC2 have no task", file="/g/task-1.md"))):
            with self.subTest(findings=name):
                out = run_out(replies={"plan": plan, "plan-revise": self.retyped(plan, criteria_edited=[]), "plan-review": review,
                                       "plan-rules-review": self.LEFT}, patch=self.OPEN)
                names = labels(out["calls"])
                self.assertNotIn("plan-rules-review", names)
                self.assertEqual(len([line for line in out["logs"] if self.SKIPPED in line]), 1)
                self.assertEqual(len([line for line in out["logs"] if "kept the earlier text of 3 criteria the revise does not list as edited" in line]), 1)
                self.assertIn("impl-1", names)
                self.assertEqual(out["result"]["acceptance"], plan["acceptance"])
                later = prompt(out["calls"], "final-1") + prompt(out["calls"], "close-out")
                self.assertNotIn("retyped", later)

    NAMING = (("summary", {"summary": "the wording of AC2: names no deploy"}),
              ("lower case", {"summary": "criterion ac2 has no task"}),
              ("failing_input", {"summary": "a criterion has no task", "failing_input": "(AC2)"}),
              ("ac", {"summary": "no task", "ac": "AC2"}))

    def test_a_criterion_a_finding_names_is_restored_like_any_other_and_skips(self):
        """#951: a finding that names a criterion says nothing about its row; only the revise's list keeps a retyped text."""
        plan = with_criteria(EVIDENCE)
        for name, finding in self.NAMING:
            with self.subTest(named_in=name):
                result, names, skipped = self.go(plan, self.retyped(plan, criteria_edited=[]), review=self.naming(**finding))
                self.assertNotIn("plan-rules-review", names)
                self.assertEqual(len(skipped), 1)
                self.assertIn("impl-1", names)
                self.assertEqual(result["acceptance"], plan["acceptance"])

    def test_a_named_criterion_the_revise_lists_keeps_the_reply_whole_and_the_rules_rereview_runs(self):
        plan = with_criteria(EVIDENCE)
        for name, finding in self.NAMING:
            with self.subTest(named_in=name):
                # AC2, listed, takes the reply's text, so the skip cannot fire and nothing is restored: no half-restored plan.
                self.kept_whole(plan, self.retyped(plan, criteria_edited=["AC2"]), review=self.naming(**finding))

    def test_a_criterion_the_reply_lists_as_edited_keeps_the_reply_whole_and_the_rules_rereview_runs(self):
        # The finding names no id (the second criterion), but the planner lists AC2 as a text it changed; ids compare without case.
        plan = with_criteria(EVIDENCE)
        for listed in ("AC2", "ac2"):
            with self.subTest(listed=listed):
                result = self.kept_whole(plan, self.retyped(plan, criteria_edited=[listed]),
                                         review=self.naming("the second criterion names no deploy"))
                self.assertNotIn("criteria_edited", result["cont"]["plan"])

    def test_a_text_rewritten_to_fix_a_finding_and_listed_reaches_the_final_review(self):
        """#951: the question is about the text, the member restored, so a text-only fix is listed and kept."""
        plan = with_criteria(EVIDENCE)
        fixed = dict(plan, acceptance=[plan["acceptance"][0], dict(EVIDENCE, text=self.REWORDED)])
        replies = {"plan": plan, "plan-review": self.naming("the second criterion names no deploy window")}
        out = run_out(replies=dict(replies, **{"plan-revise": dict(fixed, criteria_edited=["AC2"])}), patch=self.OPEN)
        self.assertEqual(labels(out["calls"]).count("plan-rules-review"), 1)
        self.assertEqual(out["result"]["acceptance"], fixed["acceptance"])
        self.assertIn(self.REWORDED, prompt(out["calls"], "final-1"))
        stopped = self.kept_whole(plan, dict(fixed, criteria_edited=["AC2"]), review=replies["plan-review"])
        self.assertEqual(stopped["cont"]["plan"]["acceptance"][1]["text"], self.REWORDED)

    def test_a_text_typed_again_with_an_empty_list_is_restored_and_the_rules_rereview_is_skipped(self):
        plan = with_criteria(EVIDENCE)
        retyped = dict(plan, acceptance=[plan["acceptance"][0], dict(EVIDENCE, text="deployed to the host")], criteria_edited=[])
        out = run_out(replies={"plan": plan, "plan-revise": retyped, "plan-review": self.naming("the second criterion names no deploy window"),
                               "plan-rules-review": self.LEFT}, patch=self.OPEN)
        self.assertNotIn("plan-rules-review", labels(out["calls"]))
        self.assertEqual(len([line for line in out["logs"] if self.SKIPPED in line]), 1)
        self.assertEqual(out["result"]["acceptance"], plan["acceptance"])
        self.assertNotIn("deployed to the host", prompt(out["calls"], "final-1"))

    def test_a_rule_finding_keeps_the_revised_text_whatever_the_list_says(self):
        """A finding that names a rule restores nothing: the rules re-review judges the text the revise returned."""
        plan = with_criteria(EVIDENCE)
        for name, review, more in (("claude", PlanRulesTest.RULE_FINDING, {}),
                                   ("codex", self.BARE, {"plan-codex": {"available": True, **PlanRulesTest.RULE_FINDING}})):
            with self.subTest(source=name):
                self.kept_whole(plan, self.retyped(plan, criteria_edited=[]), review=review, **more)

    def test_the_edited_list_survives_a_branch_revise_after_the_revise(self):
        # The plan-revise reply names its branch wrongly, so the branch revise's reply (not asked for the list) replaces it.
        plan = bplan(acceptance=with_criteria(EVIDENCE)["acceptance"])
        fixed = self.retyped(plan)
        for name, more in (("absent", {}), ("empty", {"criteria_edited": []})):
            with self.subTest(branch_revise_list=name):
                revised = self.retyped(bplan(task_branch="other", acceptance=plan["acceptance"]), criteria_edited=["AC2"])
                self.kept_whole(plan, revised, **{"plan-branch-revise": dict(fixed, **more)})
        with self.subTest(branch_revise_list="another id"):
            revised = self.retyped(bplan(task_branch="other", acceptance=plan["acceptance"]), criteria_edited=[])
            self.kept_whole(plan, revised, **{"plan-branch-revise": dict(fixed, criteria_edited=["AC1"])})
        with self.subTest(branch_revise_list="none edited"):
            revised = self.retyped(bplan(task_branch="other", acceptance=plan["acceptance"]), criteria_edited=[])
            result, names, skipped = self.go(plan, revised, **{"plan-branch-revise": fixed})
            self.assertLess(names.index("plan-revise"), names.index("plan-branch-revise"))
            self.assertNotIn("plan-rules-review", names)
            self.assertEqual(len(skipped), 1)
            self.assertEqual(result["acceptance"], plan["acceptance"])

    def test_an_empty_edited_list_restores_and_an_absent_one_is_unknown(self):
        plan = with_criteria(EVIDENCE)
        result, names, skipped = self.go(plan, self.retyped(plan, criteria_edited=[]))
        self.assertNotIn("plan-rules-review", names)
        self.assertEqual(len(skipped), 1)
        self.assertEqual(result["acceptance"], plan["acceptance"])
        self.kept_whole(plan, self.retyped(plan))

    def test_the_revise_asks_which_criteria_it_edited(self):
        out = run_out(replies={"plan": PLAN, "plan-revise": PLAN, "plan-review": self.BARE}, patch=self.OPEN)
        self.assertIn("criteria_edited: the ids of the criteria whose text you changed to fix a finding (typing the same criterion "
                      "again in other words is not a change; an empty list when you changed none): ", prompt(out["calls"], "plan-revise"))
        self.assertNotIn("plan.md's acceptance section", prompt(out["calls"], "plan-revise"))
        self.assertNotIn("wording you changed", prompt(out["calls"], "plan-revise"))
        self.assertNotIn("criteria_edited", prompt(out["calls"], "plan"))
        self.assertEqual(schema_of(out["calls"], "plan-revise")["properties"]["criteria_edited"]["items"]["type"], "string")

    def test_a_restore_that_would_not_reach_the_skip_leaves_the_reply_untouched(self):
        """Restoring by id is wrong once an id means another criterion, so any other change keeps the reply as returned."""
        plan = with_criteria(EVIDENCE)
        code = PLAN["acceptance"][0]
        moved = criterion(EVIDENCE, id="AC3", verify_ac="AC3", text="deployed, retyped")
        rows = (
            ("changed verify", [dict(code, text="works, retyped"), criterion(EVIDENCE, text=self.REWORDED, verify_host="h2")]),
            # AC1 split into AC1 and AC2; the old AC2 is now AC3.
            ("renumbered", [dict(code, text="parses"), {"id": "AC2", "text": "prints", "kind": "code"}, moved]),
            ("reused id, changed kind", [dict(code, text="works, retyped"), {"id": "AC2", "text": "prints", "kind": "code"}]),
            ("duplicate ids", [dict(code, text="parses"), dict(code, text="prints"), criterion(EVIDENCE, text="deployed, retyped")]),
            ("added", [dict(code, text="works, retyped"), criterion(EVIDENCE, text="deployed, retyped"), HUMAN]),
        )
        for name, acceptance in rows:
            with self.subTest(change=name):
                self.kept_whole(plan, dict(PLAN, acceptance=acceptance, criteria_edited=[]))

    def test_criteria_edited_never_reaches_the_kept_plan(self):
        # Any planner reply may carry the member; none keeps it in the plan a stop or a cont holds.
        plan = with_criteria(HUMAN)
        listed = dict(plan, criteria_edited=["AC1"])
        result, _ = run(replies={"plan": listed, "plan-revise": listed, "plan-rules-revise": listed,
                                 "plan-review": PlanRulesTest.RULE_FINDING, "plan-rules-review": PlanRulesTest.RULE_FINDING})
        self.assertEqual((result["stage"], result["cont"]["plan"]), ("plan-review", plan))

    def test_a_revision_that_planrules_refuses_still_runs_the_rules_rereview(self):
        # No trigger has a rule and the revise changes no id, kind, metric or verify, but it drops a lint: planRules hits R4.
        result, names, skipped = self.go(with_criteria(EVIDENCE), with_criteria(criterion(EVIDENCE, lint=None)))
        self.assertEqual(names.count("plan-rules-review"), 1)
        self.assertEqual(skipped, [])
        self.assertEqual(result["stage"], "plan-review")

    def test_a_rules_only_revise_always_runs_its_rules_rereview(self):
        # A rules revise is triggered by rule findings, so its re-review is never skipped.
        result, calls = PlanRulesTest().keep_stop()
        self.assertEqual(labels(calls).count("plan-rules-review"), 2)
        self.assertEqual(result["stage"], "plan-review")


class PlanTestCaseFormTest(unittest.TestCase):
    """#746 trial: only the plan step's task files state each failing test as a case, not as code."""

    PLANNERS = ("plan", "plan-revise", "plan-rules-revise", "plan-branch-revise", "plan-task-revise")
    MARK = "state each failing test as a case"

    @staticmethod
    def rule():
        found = re.search(r"const TEST_CASES = `([^`]*)`", PROGRAM.read_text(encoding="utf-8"))
        if found is None:
            raise AssertionError("TEST_CASES is not a shared constant")
        return found.group(1)

    def test_the_rule_names_every_part_of_a_case_and_keeps_the_carve_out(self):
        text = self.rule()
        for needle in (self.MARK, "its name", "the arrange", "the act", "the exact assertion",
                       "the expected failure", "carve-out", "an exact wire format",
                       "Write failing tests out in full.", "The implementer writes the test code from the case."):
            self.assertIn(needle, text)
        self.assertEqual(PROGRAM.read_text(encoding="utf-8").count(text), 1)

    def test_every_planner_prompt_prohibits_full_test_code_outside_the_carve_out(self):
        # Literals are pinned here, not read back from the constant under test.
        restrictions = ("not as code", "full test code stays only under its carve-out")
        seen = set()
        for call in all_calls():
            if call["label"] in self.PLANNERS:
                for needle in restrictions:
                    self.assertIn(needle, call["prompt"], call["label"])
                seen.add(call["label"])
        self.assertEqual(seen, set(self.PLANNERS))

    def test_only_planner_prompts_carry_the_rule(self):
        text = self.rule()
        seen = set()
        for call in all_calls():
            label = call["label"]
            if label in self.PLANNERS:
                self.assertIn(text, call["prompt"], label)
                seen.add(label)
            else:
                self.assertNotIn(self.MARK, call["prompt"], label)
        self.assertEqual(seen, set(self.PLANNERS))

    def test_writing_plans_and_deliver_batch_keep_full_test_code(self):
        skill = (REPO_ROOT / "home/common/agent-skills/skills/writing-plans/SKILL.md").read_text(encoding="utf-8")
        self.assertIn("Write failing tests out in full.", skill)
        self.assertNotIn(self.MARK, skill)
        batch = (PROGRAM.parent / "deliver-batch.js").read_text(encoding="utf-8")
        self.assertNotIn(self.MARK, batch)

    def test_the_implementer_prompt_still_demands_red_first_and_a_mutation_check(self):
        _, calls = run()
        impl = prompt(calls, "impl-1")
        self.assertIn("write the failing test first and see it fail", impl)
        self.assertIn("temporarily remove the code it pins and confirm it fails", impl)


class TaskTest(unittest.TestCase):
    def test_blocked_task_stops_with_cont_marking_it_partial(self):
        result, _ = run(replies={"impl-1": {"status": "blocked", "notes": "no"}})
        self.assertEqual(result["stage"], "task")
        self.assertEqual(result["cont"]["partial"], 1)
        self.assertEqual(result["cont"]["done"], [])

    def test_a_blocked_task_says_why_in_one_bounded_line(self):
        """#869: the implementer's own words reach the stop."""
        notes = "Task 1 cannot be finished as written\nbecause it depends on Task 2"
        result, _ = run(replies={"impl-1": {"status": "blocked", "notes": notes}})
        self.assertEqual(result["reason"], f"task: task 1 blocked: Task 1 cannot be finished as written because it depends on Task 2{WAYS}")
        result, _ = run(replies={"impl-1": {"status": "blocked", "notes": "x" * 900}})
        self.assertEqual(len(result["reason"]), 300)
        result, _ = run(replies={"impl-1": None})
        self.assertEqual(result["reason"], "task: task 1 the implementer returned nothing")
        result, _ = run(replies={"impl-1": {"status": "blocked"}})
        self.assertEqual(result["reason"], f"task: task 1 blocked{WAYS}")
        for replies in ({"impl-1": {}}, {"review-1": {"verdict": "findings", "findings": [{"severity": "critical", "failing_input": "x"}]},
                                         "rereview-1-1": {"verdict": "findings", "findings": [{"severity": "critical", "failing_input": "x"}]},
                                         "rereview-1-2": {"verdict": "findings", "findings": [{"severity": "critical", "failing_input": "x"}]}},
                        {"renew-final-review": {}}, {"merge": {"lock": None}}):
            with self.subTest(replies=replies):
                result, _ = run(replies=replies)
                self.assertNotIn("undefined", result["reason"])
                self.assertNotIn("null", result["reason"])

    def test_a_blocked_review_names_the_review_before_and_after_the_claim(self):
        blocked = {"setup": {"review_state": {"code": "blocked", "plan": "available"}}}
        fresh, _ = run(patch=blocked)
        self.assertEqual((fresh["stage"], fresh["reason"]), ("review-blocked", "review-blocked: the code review is blocked"))
        cont = {"setup": {"ok": True, "worktree": "/r/.wt/w-issue-9-x", "branch": "issue-9-x", "plan_dir": "/g"},
                "plan": PLAN, "plan_reviewed": True, "done": []}
        resumed, _ = run(args=dict(ARGS, cont=cont), patch=blocked)
        self.assertEqual((resumed["stage"], resumed["reason"]), ("review-blocked", "review-blocked: the code review is blocked"))

    def test_every_stop_carries_a_reason_and_a_pause_none(self):
        """#869: plan-review, task-review, verify, land and claim stops each name their stage and detail; planned and ready are not stops."""
        rule = {"verdict": "findings", "findings": [{"severity": "important", "rule": "R2", "summary": "AC1 asks for approval"}]}
        stops = {
            "plan-review": ({"plan-review": None}, "plan-review: the plan reviewer returned nothing"),
            "plan-rules": ({"plan-review": rule, "plan-rules-review": rule}, "plan-review: 1 finding(s): AC1 asks for approval"),
            "task-review": ({"review-1": TASK_FINDING, "rereview-1-1": TASK_FINDING, "rereview-1-2": TASK_FINDING},
                            "task-review: task 1 1 finding(s): bug on the candidate"),
            "verify": ({"verify": None}, "verify: ?: verification returned nothing"),
            "renew": ({"renew-final-review": {"verdict": "error", "detail": "forge down"}}, "claim-lost: renew at final-review: forge down"),
            "merge": ({"merge": None}, "merge: the merge step returned nothing"),
        }
        for name, (replies, start) in stops.items():
            with self.subTest(name=name):
                result, _ = run(replies=replies)
                self.assertTrue(result["reason"].startswith(start), result.get("reason"))
                self.assertLessEqual(len(result["reason"]), 300)
        for mode in ("plan", "ready"):
            paused, _ = run(args=dict(ARGS, mode=mode))
            self.assertNotIn("reason", paused)
        done, _ = run()
        self.assertNotIn("reason", done)

    def test_unresolved_findings_after_two_fix_rounds_stop(self):
        bad = {"verdict": "findings", "findings": [{"severity": "critical", "summary": "bug", "failing_input": "x"}]}
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
        bad = {"verdict": "findings", "findings": [{"severity": "important", "summary": "bug", "failing_input": "x"}]}
        _, calls = run(replies={"review-1": bad})
        for c in calls:
            if c["agentType"] == "reviewer-lite":
                self.assertTrue(c["label"].startswith("rereview-") or "lane: mechanical." in c["prompt"]
                                or "lane: low." in c["prompt"], c["label"])
        standard = [c for c in calls if c["label"] == "review-1"][0]
        self.assertEqual(standard["agentType"], "reviewer")
        self.assertNotIn("lane:", standard["prompt"])


def blocked(notes="no", **more):
    return dict({"status": "blocked", "notes": notes}, **more)


def task_steps(calls):
    return [label for label in labels(calls) if label.startswith(("impl-", "review-"))]


class BlockedOnLaterTaskTest(unittest.TestCase):
    """#896: a task blocked on a later task of its plan runs just after that task, once."""

    SIX = {"plan": dict(PLAN, tasks=tasks(6))}
    NEEDS_6 = blocked("Task 5 cannot be finished as written because it depends on Task 6", blocked_on=6)
    DONE_5 = {"status": "done", "start_head": "b5", "commit": "c5", "notes": "ok"}

    def go(self, args=None, **replies):
        out = run_out(args, dict(self.SIX, **replies))
        return out["result"], out["calls"], out["logs"]

    def test_the_named_later_task_runs_first_and_the_delivery_continues(self):
        result, calls, logs = self.go(**{"impl-5": [self.NEEDS_6, self.DONE_5]})
        self.assertEqual(result["stage"], "done")
        self.assertEqual(task_steps(calls), ["impl-1", "review-1", "impl-2", "review-2", "impl-3", "review-3", "impl-4", "review-4",
                                             "impl-5", "impl-6", "review-6", "impl-5", "review-5"])
        self.assertIn("task 5 is blocked on task 6: moved to run just after it, once (order 1, 2, 3, 4, 6, 5)", logs)
        self.assertEqual([c["label"] for c in calls if c["agentType"] == "planner"], ["plan"])
        ahead, retry = prompt(calls, "impl-6"), prompt(calls, "impl-5")
        self.assertIn("Task 5 waits for task 6 and may have left uncommitted edits: leave them as they are.", ahead)
        self.assertIn("Task 6, which this task was blocked on, is done now.", retry)
        self.assertIn("uncommitted edits or commits in the worktree", retry)
        # A blocked attempt that committed sits before task 6's commits: the retry's span starts at its own start.
        self.assertIn("start_head is HEAD as this attempt starts.", retry)
        self.assertNotIn("the head before this task's first commit", retry)
        # #923: the range starts at the head the task before it (task 6) left, not at the start the reply names.
        self.assertIn("git -C /r/.wt/w-issue-9-x diff c0ffee6..c5", prompt(calls, "review-5"))
        self.assertEqual(result["reordered"], [{"task": 5, "after": 6, "notes": self.NEEDS_6["notes"]}])
        ready, _, _ = self.go(dict(ARGS, mode="ready"), **{"impl-5": [self.NEEDS_6, self.DONE_5]})
        self.assertEqual((ready["stage"], ready["reordered"]), ("ready", result["reordered"]))
        plain, _, _ = self.go()
        self.assertNotIn("reordered", plain)

    def test_the_stop_reason_survives_long_notes(self):
        long = blocked("x" * 900, blocked_on=6)
        result, _, _ = self.go(**{"impl-5": [self.NEEDS_6, long]})
        self.assertTrue(result["reason"].startswith("task: task 5 blocked again after it was moved behind task 6; task 5 blocked: xxx"),
                        result["reason"])
        self.assertEqual(len(result["reason"]), 300)
        result, _, _ = self.go(**{"impl-5": blocked("x" * 900, blocked_on=2)})
        self.assertTrue(result["reason"].startswith("task: task 5 not moved: task 2 is not a later unfinished task of the plan; task 5 blocked: xxx"),
                        result["reason"])

    def test_a_new_plan_drops_the_record_of_the_old_one(self):
        setup = {"ok": True, "worktree": "/r/.wt/w-issue-9-x", "branch": "issue-9-x", "plan_dir": "/g"}
        cont = {"setup": setup, "plan": None, "plan_reviewed": False, "done": [], "reordered": [{"task": 1, "after": 2, "notes": "old"}]}
        replies = {"plan": dict(PLAN, tasks=tasks(2)), "impl-1": [blocked("needs 2", blocked_on=2), self.DONE_5]}
        result, calls = run(args=dict(ARGS, cont=cont), replies=replies)
        self.assertEqual(result["stage"], "done")
        self.assertEqual(task_steps(calls), ["impl-1", "impl-2", "review-2", "impl-1", "review-1"])
        first = [c["prompt"] for c in calls if c["label"] == "impl-1"][0]
        self.assertNotIn("was blocked on", first)
        self.assertEqual(result["reordered"], [{"task": 1, "after": 2, "notes": "needs 2"}])

    def test_the_implementer_is_asked_for_the_task_number_not_for_prose(self):
        _, calls, _ = self.go()
        for label in ("impl-1", "impl-6"):
            self.assertEqual(schema_of(calls, label)["properties"]["blocked_on"], {"type": "integer"})
            self.assertIn("blocked_on: the number of the later task of this plan it needs first, if that is why; when you name it, "
                          "first undo every uncommitted edit you made, leaving the worktree as you found it.", prompt(calls, label))
            self.assertNotIn("waits for task", prompt(calls, label))
            self.assertNotIn("was blocked on", prompt(calls, label))
            self.assertNotIn("uncommitted edits", prompt(calls, label))

    def test_a_second_block_of_the_moved_task_stops_with_the_reason(self):
        for again in (self.NEEDS_6, blocked("still impossible")):
            with self.subTest(again=again):
                result, calls, _ = self.go(**{"impl-5": [self.NEEDS_6, again]})
                self.assertEqual((result["stage"], result["task"]["n"], result["cont"]["partial"]), ("task", 5, 5))
                self.assertIn("blocked again after it was moved behind task 6", result["reason"])
                self.assertEqual(labels(calls).count("impl-5"), 2)
                self.assertEqual(labels(calls).count("impl-6"), 1)
                self.assertEqual([d["n"] for d in result["cont"]["done"]], [1, 2, 3, 4, 6])

    def test_a_block_that_names_no_later_task_stops_as_before(self):
        result, calls, _ = self.go(**{"impl-5": blocked("the task file is wrong")})
        self.assertEqual(result["reason"], f"task: task 5 blocked: the task file is wrong{WAYS}")
        self.assertEqual((result["cont"]["partial"], result["cont"]["plan"]["tasks"]), (5, tasks(6)))
        self.assertNotIn("reordered", result["cont"])
        self.assertNotIn("impl-6", labels(calls))

    def test_a_block_on_an_earlier_done_or_unknown_task_stops(self):
        for named in (4, 5, 9, 0):
            with self.subTest(named=named):
                result, calls, _ = self.go(**{"impl-5": blocked("needs it", blocked_on=named)})
                self.assertEqual((result["stage"], result["cont"]["partial"]), ("task", 5))
                self.assertIn(f"not moved: task {named} is not a later unfinished task of the plan", result["reason"])
                self.assertNotIn("reordered", result["cont"])
                self.assertNotIn("impl-6", labels(calls))
        for wrong in ("6", 6.5, None):
            with self.subTest(wrong=wrong):
                result, calls, _ = self.go(**{"impl-5": blocked("needs it", blocked_on=wrong)})
                self.assertEqual(result["reason"], f"task: task 5 blocked: needs it{WAYS}")
                self.assertNotIn("impl-6", labels(calls))

    def test_a_named_task_in_another_worktree_stops(self):
        def plan(on_branch):
            return dict(bplan(), tasks=[dict(t, **({"branch": "cand"} if t["n"] in on_branch else {})) for t in tasks(6)])
        result, calls = run(replies={"plan": plan({6}), "impl-5": self.NEEDS_6})
        self.assertEqual((result["stage"], result["cont"]["partial"]), ("task", 5))
        self.assertIn("not moved: task 6 commits in another worktree", result["reason"])
        self.assertNotIn("impl-6", labels(calls))
        result, calls = run(replies={"plan": plan({5, 6}), "impl-5": [self.NEEDS_6, self.DONE_5]})
        self.assertEqual(result["stage"], "done")
        self.assertEqual(task_steps(calls)[-4:], ["impl-6", "review-6", "impl-5", "review-5"])

    def test_the_tasks_between_keep_their_order(self):
        result, calls, _ = self.go(**{"impl-3": [blocked("needs 5", blocked_on=5), self.DONE_5]})
        self.assertEqual(result["stage"], "done")
        self.assertEqual([step for step in labels(calls) if step.startswith("impl-")],
                         ["impl-1", "impl-2", "impl-3", "impl-4", "impl-5", "impl-3", "impl-6"])

    def test_a_block_while_a_moved_task_waits_stops(self):
        result, calls, _ = self.go(**{"impl-4": blocked("needs 6", blocked_on=6), "impl-5": blocked("needs 4", blocked_on=4)})
        self.assertEqual((result["stage"], result["task"]["n"], result["cont"]["partial"]), ("task", 5, 5))
        self.assertIn("not moved behind task 4: task 4 still waits for task 6", result["reason"])
        self.assertNotIn("impl-6", labels(calls))
        self.assertEqual([t["n"] for t in result["cont"]["plan"]["tasks"]], [1, 2, 3, 5, 6, 4])

    def test_a_stop_after_the_move_keeps_the_order_and_reruns_no_done_task(self):
        stopped, _, _ = self.go(**{"impl-5": self.NEEDS_6, "impl-6": None})
        cont = stopped["cont"]
        self.assertEqual((stopped["stage"], cont["partial"]), ("task", 6))
        self.assertEqual([t["n"] for t in cont["plan"]["tasks"]], [1, 2, 3, 4, 6, 5])
        self.assertEqual(cont["reordered"], [{"task": 5, "after": 6, "notes": self.NEEDS_6["notes"]}])
        self.assertEqual([d["n"] for d in cont["done"]], [1, 2, 3, 4])
        result, calls = run(args=dict(ARGS, cont=cont), patch={"setup": {"dirty": True}})
        self.assertEqual(result["stage"], "done")
        self.assertEqual(task_steps(calls), ["impl-6", "review-6", "impl-5", "review-5"])
        self.assertIn("Task 5 waits for task 6", prompt(calls, "impl-6"))
        self.assertIn("start_head is the head before this task's first commit.", prompt(calls, "impl-6"))
        self.assertIn("start_head is HEAD as this attempt starts.", prompt(calls, "impl-5"))
        # The moved task's one repair is spent across the relaunch too.
        again, calls = run(args=dict(ARGS, cont=cont), replies={"impl-5": self.NEEDS_6})
        self.assertEqual((again["stage"], again["cont"]["partial"]), ("task", 5))
        self.assertIn("blocked again after it was moved behind task 6", again["reason"])
        self.assertEqual(labels(calls).count("impl-6"), 1)
        self.assertEqual(again["cont"]["reordered"], cont["reordered"])

    def test_a_later_stop_carries_the_record_and_no_partial(self):
        result, _, _ = self.go(**{"impl-5": [self.NEEDS_6, self.DONE_5], "verify": None})
        self.assertEqual(result["stage"], "verify")
        self.assertNotIn("partial", result["cont"])
        self.assertEqual([(r["task"], r["after"]) for r in result["cont"]["reordered"]], [(5, 6)])
        self.assertEqual([d["n"] for d in result["cont"]["done"]], [1, 2, 3, 4, 6, 5])


EMPTY_RANGE = re.compile(r"diff (\S+)\.\.\1(?!\w)")
KNOW_TEXT = ("Ground the review in: ~/.agents/standards/the-bar.md and its stacks/ shards matching the changed file types (when present); "
             "the project's standards (/r/docs/standards), only shards whose globs intersect the change; review hints (/r/.hints); "
             "recorded rejections (/r/.rej): never raise a finding a rejection already settles.")


class NoCommitTaskTest(unittest.TestCase):
    """#923: a task that ends with no new commit gets a no-change check, never a diff review of an empty range.

    Whether a reply added a commit is read against a head the program holds, never from the reply's own start_head.
    """

    HEAD = "c0ffee"
    WT = "/r/.wt/w-issue-9-x"
    NO_COMMIT = {"start_head": HEAD, "commit": HEAD, "notes": "posted the comment on the issue", "tests": ["gh issue view -> 1"]}
    NEEDS_CHANGE = {"verdict": "findings",
                    "findings": [{"severity": "critical", "summary": "the task file requires src/a.py to change", "failing_input": "x"}]}
    NEEDS_JSON = '[{"severity":"critical","summary":"the task file requires src/a.py to change","failing_input":"x"}]'
    TRACKED_ONLY = f"git -C {WT} status --porcelain --untracked-files=no prints nothing"

    def go(self, risk="low", replies=None, patch=None, **more):
        replies = dict({"plan": dict(PLAN, tasks=tasks(2, risk))}, **(replies or {}))
        return run(replies=replies, patch=dict({"impl-2": self.NO_COMMIT}, **(patch or {})), **more)

    def assert_no_empty_range(self, calls):
        for c in calls:
            self.assertIsNone(EMPTY_RANGE.search(c["prompt"]), c["label"])

    @staticmethod
    def call_of(calls, label):
        return [c for c in calls if c["label"] == label][-1]

    def test_a_no_commit_task_is_accepted_on_evidence_a_reviewer_checks(self):
        for risk in ("low", "mechanical", "standard", "security"):
            with self.subTest(risk=risk):
                result, calls = self.go(risk)
                self.assertEqual(result["stage"], "done")
                self.assert_no_empty_range(calls)
                review = [c for c in calls if c["label"] == "review-2"]
                self.assertEqual([c["agentType"] for c in review], ["reviewer"])
                text = review[0]["prompt"]
                for want in (f"Task 2 ended with no new commit: the head of {self.WT} is still c0ffee.",
                             "There is no diff to review and none is missing",
                             "its task file /g/task-2.md (the contract)",
                             "notes: posted the comment on the issue; checks run: [\"gh issue view -> 1\"].",
                             f"{self.TRACKED_ONLY}: another head or an uncommitted change to a tracked file is a finding. Then",
                             "Does the task file require a tracked file to be created, changed or deleted?",
                             "Confirm each yourself, with read-only commands that change nothing, the task file's own verification commands or a lookup (",
                             "the implementer's word alone is not evidence"):
                    self.assertIn(want, text)
                self.assertNotIn("lane:", text)
                self.assertNotIn("Review the diff of task", text)
                self.assertNotIn("fix-2-1", labels(calls))
                self.assertEqual([d for d in result["tasks"] if d["n"] == 2],
                                 [{"n": 2, "commit": self.HEAD, "review_rounds": 0, "reviewer": "reviewer", "no_change": True}])

    def test_a_no_change_check_names_the_head_the_program_holds_not_the_reply_spelling(self):
        """#932: an abbreviated or uppercase reply sha is not what the reviewer compares rev-parse HEAD with."""
        full = "c0ffee1" + "0" * 33
        for said in ("C0FFEE1", full[:12], full.upper()):
            with self.subTest(said=said):
                short = {"start_head": said, "commit": said, "notes": "see the comment", "tests": []}
                result, calls = self.go(replies={"review-2": self.NEEDS_CHANGE},
                                        patch={"impl-1": {"commit": full}, "impl-2": short, "fix-2-1": short})
                self.assertEqual(result["stage"], "done")
                first, again = prompt(calls, "review-2"), self.call_of(calls, "rereview-2-1")["prompt"]
                self.assertIn(f"Task 2 ended with no new commit: the head of {self.WT} is still {full}.", first)
                self.assertIn(f"The fix made no new commit (the head of {self.WT} is still {full})", again)
                for text in (first, again):
                    self.assertIn(f"First confirm that git -C {self.WT} rev-parse HEAD prints {full} and", text)
                    self.assertNotIn(f"prints {said} and" if said != full else full.upper(), text)
        # The program's own head may be the shorter one: the fuller of the two is printed, lowercased.
        long = {"start_head": "C0FFEE" + "1" * 34, "commit": "C0FFEE" + "1" * 34, "notes": "n", "tests": []}
        _, calls = self.go(patch={"impl-1": {"commit": "c0ffee1"}, "impl-2": long})
        self.assertIn(f"rev-parse HEAD prints {'c0ffee' + '1' * 34} and", prompt(calls, "review-2"))

    def test_a_no_commit_task_whose_brief_required_a_change_goes_back_and_its_diff_gets_a_first_pass(self):
        for risk, kind in (("low", "reviewer-lite"), ("standard", "reviewer")):
            with self.subTest(risk=risk):
                # The fix names another start head: the first pass still starts at the head the task was accepted at.
                result, calls = self.go(risk, replies={"review-2": self.NEEDS_CHANGE},
                                        patch={"fix-2-1": {"start_head": "e9", "commit": "d1"}})
                self.assertEqual(result["stage"], "done")
                self.assert_no_empty_range(calls)
                self.assertIn("the task file requires src/a.py to change", prompt(calls, "fix-2-1"))
                again = self.call_of(calls, "rereview-2-1")
                self.assertEqual(again["agentType"], kind)
                self.assertIn(f"{'lane: low. ' if risk == 'low' else ''}Review the diff of task 2 only: "
                              f"git -C {self.WT} diff c0ffee..d1 (and the task file /g/task-2.md as its contract).", again["prompt"])
                self.assertIn(f"this diff answers these findings: {self.NEEDS_JSON}", again["prompt"])
                self.assertEqual([d for d in result["tasks"] if d["n"] == 2],
                                 [{"n": 2, "commit": "d1", "review_rounds": 1, "reviewer": kind}])

    def test_after_the_first_pass_of_its_diff_a_second_fix_is_a_scoped_rereview_or_a_rebuttal(self):
        first = {"review-2": self.NEEDS_CHANGE, "rereview-2-1": TASK_FINDING}
        for risk in ("low", "standard"):
            with self.subTest(risk=risk, second="commits"):
                result, calls = self.go(risk, replies=first, patch={"fix-2-1": {"start_head": self.HEAD, "commit": "d1"},
                                                                   "fix-2-2": {"start_head": "d1", "commit": "d2"}})
                self.assertEqual(result["stage"], "done")
                again = self.call_of(calls, "rereview-2-2")
                self.assertEqual(again["agentType"], "reviewer-lite")
                self.assertIn(f"Re-review only these previously reported findings for task 2 against the fix: git -C {self.WT} diff d1..d2;",
                              again["prompt"])
                self.assertNotIn("Review the diff of task", again["prompt"])
                self.assertNotIn("lane:", again["prompt"])
                self.assert_no_empty_range(calls)
            with self.subTest(risk=risk, second="no commit"):
                result, calls = self.go(risk, replies=first, patch={"fix-2-1": {"start_head": self.HEAD, "commit": "d1"},
                                                                   "fix-2-2": {"start_head": "d1", "commit": "d1"}})
                self.assertEqual(result["stage"], "done")
                again = self.call_of(calls, "rereview-2-2")
                self.assertEqual(again["agentType"], "reviewer")
                self.assertIn(f"The fix made no new commit (the head of {self.WT} is still d1)", again["prompt"])
                self.assertIn(f"the task's diff (git -C {self.WT} diff c0ffee..d1)", again["prompt"])
                self.assert_no_empty_range(calls)

    def test_a_no_commit_task_that_never_changes_what_its_brief_required_stops(self):
        result, calls = self.go(replies={"review-2": self.NEEDS_CHANGE, "rereview-2-1": self.NEEDS_CHANGE,
                                         "rereview-2-2": self.NEEDS_CHANGE},
                                patch={"fix-2-1": self.NO_COMMIT, "fix-2-2": self.NO_COMMIT})
        self.assertEqual((result["stage"], result["cont"]["partial"]), ("task-review", 2))
        self.assertTrue(result["reason"].startswith("task-review: task 2 1 finding(s): the task file requires src/a.py"))
        self.assertEqual([d["n"] for d in result["cont"]["done"]], [1])
        self.assert_no_empty_range(calls)
        for label in ("rereview-2-1", "rereview-2-2"):
            again = self.call_of(calls, label)
            self.assertEqual(again["agentType"], "reviewer")
            self.assertIn(f"The fix made no new commit (the head of {self.WT} is still c0ffee)", again["prompt"])
            self.assertIn(self.TRACKED_ONLY, again["prompt"])
            self.assertIn("a finding the evidence does not refute is still unresolved", again["prompt"])
            self.assertNotIn("the task's diff", again["prompt"])

    def test_a_fix_that_answers_a_normal_task_with_no_commit_is_reviewed_as_a_rebuttal(self):
        # The head just reviewed decides, whatever start_head the fix reports.
        for start in ("c0ffee", SHA):
            with self.subTest(start=start):
                result, calls = run(replies={"review-1": TASK_FINDING},
                                    patch={"fix-1-1": {"start_head": start, "commit": "c0ffee", "notes": "the finding is wrong: see a.py:3"}})
                self.assertEqual(result["stage"], "done")
                self.assert_no_empty_range(calls)
                again = self.call_of(calls, "rereview-1-1")
                self.assertEqual(again["agentType"], "reviewer")
                self.assertIn(f"the task's diff (git -C {self.WT} diff {SHA}..c0ffee)", again["prompt"])
                self.assertIn("The implementer's notes: the finding is wrong: see a.py:3.", again["prompt"])

    def test_a_fix_that_commits_is_a_scoped_rereview_whatever_start_head_it_reports(self):
        result, calls = run(replies={"review-1": TASK_FINDING}, patch={"fix-1-1": {"start_head": "d1", "commit": "d1"}})
        self.assertEqual(result["stage"], "done")
        self.assert_no_empty_range(calls)
        again = self.call_of(calls, "rereview-1-1")
        self.assertEqual(again["agentType"], "reviewer-lite")
        self.assertIn(f"against the fix: git -C {self.WT} diff c0ffee..d1; the implementer's notes", again["prompt"])
        self.assertNotIn("made no new commit", again["prompt"])

    def test_a_resume_at_a_partial_no_commit_task_passes_the_same_way(self):
        stopped, _ = self.go(replies={"review-2": None})
        self.assertEqual((stopped["stage"], stopped["cont"]["partial"]), ("task-review", 2))
        result, calls = run(args=dict(ARGS, cont=stopped["cont"]), patch={"impl-2": self.NO_COMMIT})
        self.assertEqual(result["stage"], "done")
        self.assertEqual(labels(calls)[:3], ["setup", "impl-2", "review-2"])
        self.assertIn("start_head is the head before this task's first commit", prompt(calls, "impl-2"))
        self.assert_no_empty_range(calls)
        review = self.call_of(calls, "review-2")
        self.assertEqual(review["agentType"], "reviewer")
        self.assertIn("Task 2 ended with no new commit", review["prompt"])

    def test_a_resume_whose_cut_off_attempt_committed_gets_a_diff_review_from_the_accepted_head(self):
        """The resumed implementer names the cut-off attempt's commit as both ends: the commit is still unreviewed."""
        stopped, _ = self.go(replies={"review-2": None})
        moved = {"start_head": "d1", "commit": "d1"}
        # The setup's head already holds the cut-off commit, so it is not the accepted head of a partial task.
        for setup in ({}, {"head": "d1"}):
            with self.subTest(setup=setup):
                result, calls = run(args=dict(ARGS, cont=stopped["cont"]), patch={"impl-2": moved, "setup": setup})
                self.assertEqual(result["stage"], "done")
                self.assert_no_empty_range(calls)
                review = self.call_of(calls, "review-2")
                self.assertEqual(review["agentType"], "reviewer-lite")
                self.assertIn(f"lane: low. Review the diff of task 2 only: git -C {self.WT} diff c0ffee..d1 (and the task file", review["prompt"])
                self.assertNotIn("ended with no new commit", review["prompt"])
                self.assertEqual([d for d in result["tasks"] if d["n"] == 2],
                                 [{"n": 2, "commit": "d1", "review_rounds": 0, "reviewer": "reviewer-lite"}])
        # A partial first task has no done task before it: the accepted head is the branch's base.
        first, _ = run(replies={"review-1": None})
        self.assertEqual(first["cont"]["partial"], 1)
        _, calls = run(args=dict(ARGS, cont=first["cont"]), patch={"impl-1": moved})
        self.assertIn(f"Review the diff of task 1 only: git -C {self.WT} diff {SHA}..d1 (and", prompt(calls, "review-1"))

    def test_a_reply_that_starts_above_the_accepted_head_is_reviewed_from_the_accepted_head(self):
        """The implementer commits A then B and reports A..B: the review covers the accepted head..B, so A is not hidden."""
        result, calls = run(replies={"plan": dict(PLAN, tasks=tasks(2))}, patch={"impl-2": {"start_head": "a1", "commit": "b2"}})
        self.assertEqual(result["stage"], "done")
        self.assertIn(f"Review the diff of task 2 only: git -C {self.WT} diff c0ffee..b2 (and", prompt(calls, "review-2"))
        self.assertNotIn("a1", prompt(calls, "review-2"))
        # An honest reply keeps its own spelling of the accepted head.
        _, calls = run(replies={"plan": dict(PLAN, tasks=tasks(2))}, patch={"impl-2": {"start_head": "C0FFEE", "commit": "b2"}})
        self.assertIn(f"git -C {self.WT} diff C0FFEE..b2 (and", prompt(calls, "review-2"))

    def test_a_rebuttal_after_a_cut_off_commit_names_the_task_diff_from_the_accepted_head(self):
        stopped, _ = self.go(replies={"review-2": None})
        result, calls = run(args=dict(ARGS, cont=stopped["cont"]), replies={"review-2": TASK_FINDING},
                            patch={"impl-2": {"start_head": "d1", "commit": "d1"}, "fix-2-1": {"start_head": "d1", "commit": "d1"}})
        self.assertEqual(result["stage"], "done")
        self.assert_no_empty_range(calls)
        self.assertIn(f"git -C {self.WT} diff c0ffee..d1 (and", prompt(calls, "review-2"))
        again = self.call_of(calls, "rereview-2-1")
        self.assertEqual(again["agentType"], "reviewer")
        self.assertIn(f"the task's diff (git -C {self.WT} diff c0ffee..d1)", again["prompt"])

    def test_a_resume_at_a_task_no_stop_left_partial_reads_the_head_the_setup_found(self):
        cont = {"setup": {"ok": True, "worktree": self.WT, "branch": "issue-9-x", "plan_dir": "/g"},
                "plan": dict(PLAN, tasks=tasks(2)), "plan_reviewed": True, "done": [{"n": 1, "commit": "c1"}]}
        result, calls = run(args=dict(ARGS, cont=cont), patch={"setup": {"head": "e1"}, "impl-2": {"start_head": "e1", "commit": "e1"}})
        self.assertEqual(result["stage"], "done")
        self.assertIn(f"Task 2 ended with no new commit: the head of {self.WT} is still e1.", prompt(calls, "review-2"))

    def test_a_waiting_tasks_kept_edits_are_neither_flagged_nor_reverted(self):
        """#897: while a blocked task waits behind a later one, its uncommitted edits stay in the worktree."""
        notice = "Task 1 waits for task 2 and may have left uncommitted edits: "
        replies = {"plan": dict(PLAN, tasks=tasks(2)),
                   "impl-1": [blocked("needs 2", blocked_on=2), {"status": "done", "start_head": "b0", "commit": "c0ffee", "notes": "ok"}],
                   "review-2": self.NEEDS_CHANGE, "rereview-2-1": self.NEEDS_CHANGE, "rereview-2-2": {"verdict": "pass", "findings": []}}
        none = {"start_head": SHA, "commit": SHA}
        result, calls = run(replies=replies, patch={"impl-2": none, "fix-2-1": none, "fix-2-2": none})
        self.assertEqual(result["stage"], "done")
        self.assertEqual(task_steps(calls), ["impl-1", "impl-2", "review-2", "impl-1", "review-1"])
        for label in ("review-2", "rereview-2-1", "rereview-2-2"):
            with self.subTest(label=label):
                self.assertIn(f"an uncommitted change to a tracked file is a finding.{' ' + notice}those are not a finding. Then",
                              prompt(calls, label))
        for label in ("impl-2", "fix-2-1", "fix-2-2"):
            with self.subTest(label=label):
                self.assertIn(f"{notice}leave them as they are.", prompt(calls, label))
        # No task waits in a plain run: no notice anywhere.
        _, calls = self.go(replies={"review-2": self.NEEDS_CHANGE}, patch={"fix-2-1": self.NO_COMMIT})
        for c in calls:
            self.assertNotIn("waits for task", c["prompt"], c["label"])

    def test_a_declared_branch_no_commit_task_is_checked_in_its_worktree(self):
        result, calls = run(replies={"plan": bplan()}, patch={"impl-2": {"start_head": BR["head"], "commit": BR["head"]}})
        self.assertEqual(result["stage"], "done")
        self.assert_no_empty_range(calls)
        self.assertIn(f"the head of /r/.wt/cand is still {BR['head']}", prompt(calls, "review-2"))
        # Another head than the branch's known one is a commit to review, whatever start_head says.
        one = "1" * 40
        _, calls = run(replies={"plan": bplan()}, patch={"impl-2": {"start_head": one, "commit": one}})
        self.assertIn(f"Review the diff of task 2 only: git -C /r/.wt/cand diff {BR['head']}..{one} (and", prompt(calls, "review-2"))

    def test_a_plan_whose_every_task_commits_nothing_stops_before_the_final_review(self):
        none = {"start_head": SHA, "commit": SHA}
        result, calls = run(replies={"plan": dict(PLAN, tasks=tasks(2))}, patch={"impl-1": none, "impl-2": none})
        self.assertEqual(result["stage"], "no-changes")
        self.assertTrue(result["reason"].startswith("no-changes: every task ended with no commit: the branch issue-9-x holds nothing"),
                        result["reason"])
        self.assertEqual([c["agentType"] for c in calls if c["label"] in ("review-1", "review-2")], ["reviewer", "reviewer"])
        for label in labels(calls):
            self.assertFalse(label.startswith(("final-", "renew-final", "verify", "pr")), label)
        self.assertNotIn("partial", result["cont"])
        self.assertEqual([d.get("no_change") for d in result["cont"]["done"]], [True, True])
        again, calls = run(args=dict(ARGS, cont=result["cont"]))
        self.assertEqual(again["stage"], "no-changes")
        self.assertEqual(labels(calls), ["setup"])

    def test_a_task_that_commits_is_reviewed_with_the_same_bytes_as_before(self):
        for risk, lane in (("standard", ""), ("low", "lane: low. ")):
            with self.subTest(risk=risk):
                _, calls = run(replies={"plan": dict(PLAN, tasks=tasks(1, risk)), "review-1": TASK_FINDING})
                impl = prompt(calls, "impl-1")
                # #987: the implementer's opening line is its own; a reviewer opens with the reviewer's, reviewer-lite with none.
                self.assertTrue(impl.startswith(IMPLEMENTER_ROUNDS + "\n"))
                head = impl[len(IMPLEMENTER_ROUNDS) + 1:impl.index("\nFirst renew the claim")]
                opener = "" if lane else REVIEWER_ROUNDS + "\n"
                self.assertEqual(prompt(calls, "review-1"), f"{opener}{head}\n{lane}Review the diff of task 1 only: "
                                 f"git -C {self.WT} diff {SHA}..c0ffee (and the task file /g/task-1.md as its contract). {KNOW_TEXT} "
                                 "Report Important or Critical correctness defects and unmet task requirements only, each with a "
                                 f"concrete failing input. No style notes. Do not edit anything.\n{REPLY_ALONE}")
                self.assertEqual(prompt(calls, "rereview-1-1"), f"{head}\nRe-review only these previously reported findings for "
                                 f"task 1 against the fix: git -C {self.WT} diff c0ffee..f1c0de; the implementer's notes: ok. "
                                 'Findings: [{"severity":"important","summary":"bug on the candidate","failing_input":"x"}]. Report any finding still '
                                 f"unresolved and any new Important or Critical defect the fix introduced.\n{REPLY_ALONE}")
                kinds = {c["label"]: c["agentType"] for c in calls}
                self.assertEqual((kinds["review-1"], kinds["rereview-1-1"]),
                                 ("reviewer-lite" if lane else "reviewer", "reviewer-lite"))


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
        self.assertNotIn("forge-claim land release", prompt(calls, "hold"))
        self.assertNotIn("release", schema_of(calls, "hold")["properties"])

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
        bad = {"verdict": "findings", "findings": [{"severity": "important", "summary": "bug", "failing_input": "x"}]}
        _, calls = run(replies={"final-1": bad})
        self.assertIn("diff b0..c0ffee", prompt(calls, "fix-wave-review"))

    def test_codex_code_review_unavailable_stops(self):
        result, _ = run(replies={"final-codex": {"available": False, "verdict": "pass", "findings": []}})
        self.assertEqual((result["stage"], result["step"]), ("codex-unavailable", "code"))

    def test_codex_finding_drives_the_fix_wave(self):
        codex = {"available": True, "verdict": "findings",
                 "findings": [{"severity": "important", "summary": "edge", "failing_input": "x"}]}
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
        bad = {"verdict": "findings", "findings": [{"severity": "important", "summary": "weakened test", "failing_input": "x"}]}
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


class IntegrationBesideCodexTest(unittest.TestCase):
    """#967: the integration review starts when the chunk reviewers return and is awaited with Codex; every outcome is as before."""

    FOUR = {"plan": dict(PLAN, tasks=tasks(4))}
    # The Codex reply is held until the integration review has been called: a run that waits for Codex first never ends.
    HELD = {"final-codex": "final-integration"}
    CHUNK = {"severity": "important", "summary": "chunk defect", "failing_input": "x"}
    CODEX = {"severity": "important", "summary": "codex defect", "failing_input": "x"}
    INTEG = {"severity": "critical", "summary": "seam defect", "failing_input": "x"}

    @staticmethod
    def found(*findings, **extra):
        return dict({"verdict": "findings", "findings": list(findings)}, **extra)

    def both(self, replies=None, args=None):
        """The same scenario with Codex held and not held: the two runs must not differ."""
        scenario = dict(self.FOUR, **(replies or {}))
        held, free = run_out(args, scenario, after=self.HELD), run_out(args, scenario)
        self.assertEqual(held["result"], free["result"])
        self.assertEqual(held["calls"], free["calls"])
        self.assertEqual(held["logs"], free["logs"])
        return held

    def final_labels(self, out):
        return [l for l in labels(out["calls"]) if l.startswith("final-")]

    def test_the_integration_review_is_called_before_the_codex_reply_resolves(self):
        out = self.both()
        events = out["events"]
        self.assertLess(events.index("reply final-2"), events.index("call final-integration"))
        self.assertLess(events.index("call final-integration"), events.index("reply final-codex"))
        self.assertEqual(self.final_labels(out), ["final-codex", "final-1", "final-2", "final-integration"])
        self.assertIn(json.dumps([PASS_REPLY, PASS_REPLY], separators=(",", ":")), prompt(out["calls"], "final-integration"))

    def test_both_passing_ships_with_no_fix_wave(self):
        out = self.both()
        self.assertEqual(out["result"]["stage"], "done")
        self.assertNotIn("fix-wave", labels(out["calls"]))
        self.assertIn("codex review: 0 blocking findings", out["logs"])

    def test_codex_findings_alone_drive_the_fix_wave(self):
        out = self.both({"final-codex": self.found(self.CODEX, available=True)})
        self.assertIn(f"these final-review findings, each real defect with a regression test, then commit: "
                      f"{json.dumps([dict(self.CODEX, source='codex')], separators=(',', ':'))}.", prompt(out["calls"], "fix-wave"))
        self.assertIn("codex review: 1 blocking findings", out["logs"])
        self.assertIn("final review: 1 blocking findings, fix wave 1", out["logs"])

    def test_integration_findings_alone_drive_the_fix_wave(self):
        out = self.both({"final-integration": self.found(self.INTEG)})
        self.assertIn(f"then commit: {json.dumps([self.INTEG], separators=(',', ':'))}.", prompt(out["calls"], "fix-wave"))
        self.assertIn("codex review: 0 blocking findings", out["logs"])

    def test_the_fix_wave_gets_chunk_then_codex_then_integration_findings(self):
        out = self.both({"final-2": self.found(self.CHUNK), "final-codex": self.found(self.CODEX, available=True),
                         "final-integration": self.found(self.INTEG)})
        order = [self.CHUNK, dict(self.CODEX, source="codex"), self.INTEG]
        self.assertIn(f"then commit: {json.dumps(order, separators=(',', ':'))}.", prompt(out["calls"], "fix-wave"))
        logs = out["logs"]
        self.assertLess(logs.index("codex review: 1 blocking findings"), logs.index("final review: 3 blocking findings, fix wave 1"))

    def test_an_unavailable_or_silent_codex_stops_and_the_integration_reply_is_unused(self):
        for codex, why in (({"available": False, "verdict": "pass", "findings": []}, "unavailable"), (None, "silent")):
            for integ in (PASS_REPLY, self.found(self.INTEG), None, "throw"):
                with self.subTest(codex=why, integ=integ):
                    out = self.both({"final-codex": codex, "final-integration": integ})
                    result = out["result"]
                    self.assertEqual((result["stage"], result["step"], result["codex"]), ("codex-unavailable", "code", codex))
                    # Only a reply the program reads can be a dead agent.
                    self.assertEqual(result.get("dead_agents"), None if codex else ["final-codex"])
                    self.assertNotIn("fix-wave", labels(out["calls"]))
                    self.assertFalse([l for l in out["logs"] if l.startswith("codex review:")])

    def test_a_silent_integration_reviewer_still_stops_after_codex(self):
        out = self.both({"final-integration": None, "final-codex": self.found(self.CODEX, available=True)})
        result = out["result"]
        self.assertEqual((result["stage"], result["details"]), ("final-review", "the integration reviewer returned nothing"))
        self.assertEqual(result["dead_agents"], ["final-integration"])
        self.assertIn("codex review: 1 blocking findings", out["logs"])

    def test_a_throwing_integration_reviewer_fails_the_run(self):
        scenario = dict(self.FOUR, **{"final-integration": "throw"})
        for after in (self.HELD, None):
            with self.subTest(after=after):
                out = run_out(replies=scenario, after=after)
                self.assertIsNone(out["result"])
                self.assertIn("stub agent final-integration threw", out["error"])

    def test_a_silent_chunk_reviewer_stops_before_the_integration_review(self):
        out = run_out(replies=dict(self.FOUR, **{"final-2": None}))
        result = out["result"]
        self.assertEqual((result["stage"], result["details"]), ("final-review", "a final reviewer returned nothing"))
        self.assertEqual(self.final_labels(out), ["final-codex", "final-1", "final-2"])
        # Codex is still waited for, as before.
        self.assertIn("reply final-codex", out["events"])

    def test_a_silent_chunk_reviewer_still_awaits_a_throwing_codex(self):
        # The stop waits for Codex: its throw fails the run instead of being dropped behind the stop.
        out = run_out(replies=dict(self.FOUR, **{"final-2": None, "final-codex": "throw"}))
        self.assertIsNone(out["result"])
        self.assertIn("stub agent final-codex threw", out["error"])
        self.assertEqual(self.final_labels(out), ["final-codex", "final-1", "final-2"])

    def test_one_chunk_has_no_integration_review(self):
        out = run_out(replies={"final-codex": self.found(self.CODEX, available=True)})
        self.assertEqual(self.final_labels(out), ["final-codex", "final-1"])
        self.assertIn("codex defect", prompt(out["calls"], "fix-wave"))

    def test_no_configured_codex_still_runs_the_integration_review(self):
        out = run_out(replies=dict(self.FOUR, **{"final-integration": self.found(self.INTEG)}),
                      patch={"setup": {"review_state": {"code": "unsupported", "plan": "unsupported"}}})
        self.assertEqual(self.final_labels(out), ["final-1", "final-2", "final-integration"])
        self.assertIn(f"then commit: {json.dumps([self.INTEG], separators=(',', ':'))}.", prompt(out["calls"], "fix-wave"))
        self.assertFalse([l for l in out["logs"] if l.startswith("codex review:")])


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


FOUR = {"plan": dict(PLAN, tasks=tasks(4))}


def sized(lines):
    return dict(FOUR, **{"diff-size": {"measured": True, "changed_lines": lines}})


class ReviewSizingFinalTest(unittest.TestCase):
    """#747: with sizing on, the final review is chunked, and the integration review runs, only above 1500 changed lines."""

    def test_off_chunks_four_tasks_by_three_without_measuring(self):
        result, calls = run(replies=FOUR)
        names = labels(calls)
        self.assertTrue(result["chunked"])
        for label in ("final-1", "final-2", "final-integration"):
            self.assertIn(label, names)
        self.assertNotIn("diff-size", names)

    def test_on_at_the_threshold_reviews_the_whole_delivery_once(self):
        result, calls = run(args=SIZED, replies=sized(1500))
        self.assertEqual(result["stage"], "done")
        self.assertFalse(result["chunked"])
        names = labels(calls)
        self.assertEqual([l for l in names if l.startswith("final-")], ["final-codex", "final-1"])
        self.assertIn("of the whole delivery", prompt(calls, "final-1"))
        self.assertLess(names.index("renew-final-review"), names.index("diff-size"))
        self.assertLess(names.index("diff-size"), names.index("final-codex"))
        self.assertLess(names.index("diff-size"), names.index("final-1"))
        self.assertIn("final review whole", prompt(calls, "pr"))

    def test_on_above_the_threshold_chunks_with_an_integration_review(self):
        result, calls = run(args=SIZED, replies=sized(1501))
        self.assertTrue(result["chunked"])
        names = labels(calls)
        for label in ("final-1", "final-2", "final-integration"):
            self.assertIn(label, names)
        self.assertIn("chunk 1/2", prompt(calls, "final-1"))
        self.assertEqual(names.count("diff-size"), 1)
        self.assertIn("final review chunked", prompt(calls, "pr"))

    def test_on_with_three_tasks_never_measures(self):
        result, calls = run(args=SIZED, replies={"plan": dict(PLAN, tasks=tasks(3))})
        self.assertFalse(result["chunked"])
        names = labels(calls)
        self.assertNotIn("diff-size", names)
        self.assertNotIn("final-integration", names)

    def test_on_with_an_unread_size_falls_back_to_task_chunks(self):
        for reply in ("throw", None, {"measured": False}, {"measured": False, "changed_lines": 10},
                      {"changed_lines": 10}, {"measured": True}, {"measured": True, "changed_lines": "many"},
                      {"measured": True, "changed_lines": -1}, {"measured": True, "changed_lines": 12.5}):
            with self.subTest(reply=reply):
                result, calls = run(args=SIZED, replies=dict(FOUR, **{"diff-size": reply}))
                self.assertEqual(result["stage"], "done")
                self.assertTrue(result["chunked"])
                for label in ("final-1", "final-2", "final-integration"):
                    self.assertIn(label, labels(calls))

    def test_a_recovered_size_failure_is_not_a_dead_agent_on_a_later_stop(self):
        # deliver-batch's breaker reads dead_agents; an optional measurement that fell back must not trip it.
        for reply in ("throw", None):
            with self.subTest(reply=reply):
                result, _ = run(args=SIZED, replies=dict(FOUR, **{"diff-size": reply, "final-1": FINDING,
                                                                  "fix-wave": {"status": "blocked", "notes": "no"}}))
                self.assertEqual(result["stage"], "fix-wave")
                self.assertNotIn("dead_agents", result)

    def test_the_size_step_is_a_low_clerk_reading_shortstat_of_every_range(self):
        _, calls = run(args=SIZED, replies=FOUR)
        size = next(c for c in calls if c["label"] == "diff-size")
        self.assertEqual((size["agentType"], size["model"], size["effort"]), ("clerk", "sonnet", "low"))
        self.assertEqual(size["schema"]["required"], ["measured"])
        self.assertEqual(size["schema"]["properties"]["measured"], {"type": "boolean"})
        self.assertEqual(size["schema"]["properties"]["changed_lines"], {"type": "integer", "minimum": 0})
        for needle in ("git -C /r/.wt/w-issue-9-x fetch origin",
                       "git -C /r/.wt/w-issue-9-x diff --shortstat origin/dev...HEAD",
                       "measured false", "Hard rules for this step"):
            with self.subTest(needle=needle):
                self.assertIn(needle, size["prompt"])
        self.assertNotIn("--numstat", size["prompt"])
        branched = bplan()
        branched["tasks"] = tasks(3) + [dict(branched["tasks"][1], n=4, file="/g/task-4.md")]
        _, calls = run(args=SIZED, replies={"plan": branched})
        self.assertIn("git -C /r/.wt/cand diff --shortstat origin/dev...cand", prompt(calls, "diff-size"))

    def test_cont_records_a_whole_review_only_when_sizing_collapsed_it(self):
        for args, replies, expected in ((ARGS, FOUR, None), (SIZED, sized(1501), None),
                                        (SIZED, {"plan": dict(PLAN, tasks=tasks(3))}, None), (SIZED, sized(1500), True)):
            with self.subTest(args=args, replies=replies):
                stopped, _ = run(args=args, replies=dict(replies, verify=None), patch={"impl-4": {"commit": TIP}, "impl-3": {"commit": TIP}})
                self.assertEqual(stopped["stage"], "verify")
                if expected is None:
                    self.assertNotIn("whole", stopped["cont"]["final_reviewed"])
                else:
                    self.assertIs(stopped["cont"]["final_reviewed"]["whole"], expected)

    def test_a_resume_that_skips_the_final_review_keeps_its_shape(self):
        for lines, chunked, word in ((1500, False, "whole"), (1501, True, "chunked")):
            with self.subTest(lines=lines):
                # A stop after the final review (verify): the resume skips the review on the reviewed head (SKIP_FINAL).
                stopped, _ = run(args=SIZED, replies=dict(sized(lines), verify=None), patch={"impl-4": {"commit": TIP}})
                self.assertEqual(stopped["stage"], "verify")
                result, calls = run(args=dict(SIZED, cont=stopped["cont"]), patch={"setup": {"head": TIP}})
                self.assertEqual(result["stage"], "done")
                names = labels(calls)
                self.assertNotIn("diff-size", names)
                self.assertNotIn("final-1", names)
                self.assertIs(result["chunked"], chunked)
                self.assertIn(f"final review {word}", prompt(calls, "pr"))
                # A ready stop: the resume skips review and verify on the verified head (SKIP_REVIEW).
                ready, _ = run(args=dict(SIZED, mode="ready"), replies=sized(lines))
                self.assertEqual(ready["stage"], "ready")
                result, calls = run(args=dict(SIZED, cont=ready["cont"]), patch={"setup": {"head": SHA}})
                self.assertEqual(result["stage"], "done")
                self.assertNotIn("final-1", labels(calls))
                self.assertIs(result["chunked"], chunked)
                self.assertIn(f"final review {word}", prompt(calls, "pr"))


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


class VerifyRerunTest(unittest.TestCase):
    """#972: a failure outside the branch's changed files is rerun once before any fix step, and a fix step stays inside the diff."""

    FLAKE = "tests/http_client.test.ts > retries: timed out"
    OUTSIDE = {"head": SHA, "clean": True,
               "results": [{"id": "build", "status": "fail", "summary": FLAKE, "outside_diff": True}]}
    GREEN = {"head": SHA, "clean": True, "results": [{"id": "build", "status": "pass", "summary": "ok on the rerun"}]}
    UNRELATED = {"status": "blocked", "start_head": SHA, "commit": SHA, "notes": "not this branch",
                 "unrelated": {"test": "tests/http_client.test.ts > retries",
                               "evidence": "the branch changes only admin/knip.json; the test fails the same way at origin/dev"}}

    def test_a_failure_that_passes_the_one_rerun_proceeds_with_no_fix_step_and_names_the_flaky_test(self):
        out = run_out(replies={"verify": self.OUTSIDE, "verify-rerun-1": self.GREEN})
        result, names = out["result"], labels(out["calls"])
        self.assertEqual(result["stage"], "done")
        self.assertEqual([l for l in names if l.startswith("verify")], ["verify", "verify-rerun-1"])
        self.assertEqual(result["flaky"], [{"id": "build", "summary": self.FLAKE}])
        self.assertEqual(result["verify"],
                         [{"id": "build", "status": "pass", "summary": "ok on the rerun", "flaky": self.FLAKE}])
        self.assertIn(f"verify: flaky, build failed and passed on the one rerun: {self.FLAKE}", out["logs"])

    def test_a_ready_stop_and_the_ship_resumed_from_it_keep_the_flaky_test(self):
        ready, _ = run(args=dict(ARGS, mode="ready"), replies={"verify": self.OUTSIDE, "verify-rerun-1": self.GREEN})
        self.assertEqual((ready["stage"], ready["flaky"]), ("ready", [{"id": "build", "summary": self.FLAKE}]))
        shipped, calls = run(args=dict(ARGS, cont=ready["cont"]), patch={"setup": {"head": SHA}})
        self.assertEqual((shipped["stage"], shipped["flaky"]), ("done", [{"id": "build", "summary": self.FLAKE}]))
        self.assertNotIn("verify", labels(calls))

    def test_a_clean_verification_carries_no_flaky_member(self):
        result, calls = run()
        self.assertNotIn("flaky", result)
        self.assertNotIn("verify-rerun-1", labels(calls))

    def test_a_failure_that_fails_the_rerun_too_still_goes_to_the_fix_step_and_is_verified_again(self):
        result, calls = run(replies={"verify": self.OUTSIDE, "verify-rerun-1": self.OUTSIDE})
        self.assertEqual([l for l in labels(calls) if l.startswith("verify")],
                         ["verify", "verify-rerun-1", "verify-fix-1", "verify-fix-review-1", "verify-2"])
        self.assertIn(self.FLAKE, prompt(calls, "verify-fix-1"))
        self.assertEqual(result["stage"], "done")
        self.assertNotIn("flaky", result)

    def test_each_verification_is_rerun_at_most_once(self):
        fail = {"verify": self.OUTSIDE, "verify-2": self.OUTSIDE, "verify-3": self.OUTSIDE}
        reruns = {f"verify-rerun-{n}": self.OUTSIDE for n in (1, 2, 3)}
        result, calls = run(replies=dict(fail, **reruns))
        self.assertEqual(result["stage"], "verify")
        self.assertEqual([l for l in labels(calls) if l.startswith("verify") and "review" not in l],
                         ["verify", "verify-rerun-1", "verify-fix-1", "verify-2", "verify-rerun-2", "verify-fix-2",
                          "verify-3", "verify-rerun-3"])

    def test_the_rerun_asks_for_each_whole_command_and_never_a_selection_of_tests(self):
        _, calls = run(replies={"verify": self.OUTSIDE, "verify-rerun-1": self.GREEN})
        rerun = prompt(calls, "verify-rerun-1")
        self.assertIn("Rerun each failed command below once, whole and exactly as declared, and never a second time, "
                      "whatever the outcome.", rerun)
        self.assertIn("Run the project's declared verification once on the worktree head", rerun)
        for wording in ("select", "only its failing tests", "failing tests named", "else the whole command"):
            self.assertNotIn(wording, rerun)

    def test_a_fix_after_a_failed_rerun_is_told_it_is_not_flaky_and_gets_no_placement(self):
        _, calls = run(replies={"verify": self.OUTSIDE, "verify-rerun-1": self.OUTSIDE})
        fix = prompt(calls, "verify-fix-1")
        self.assertIn('The project\'s verification failed: [{"id":"build","status":"fail","summary":"%s"}]. It failed again on '
                      "the one rerun at the same head, so it is not flaky. Find the cause" % self.FLAKE, fix)
        self.assertNotIn("outside_diff\":", fix)
        self.assertNotIn("or it is flaky", fix)
        self.assertIn("With no cause established (it fails without this branch), change and commit nothing", fix)

    def test_a_fix_with_no_rerun_or_a_rerun_that_did_not_count_is_not_told_so(self):
        for replies in ({"verify": VERIFY_RED}, {"verify": self.OUTSIDE, "verify-rerun-1": dict(self.GREEN, head=FIXED)},
                        {"verify": self.OUTSIDE, "verify-rerun-1": None}):
            with self.subTest(replies=replies):
                _, calls = run(replies=replies)
                fix = prompt(calls, "verify-fix-1")
                self.assertNotIn("so it is not flaky", fix)
                self.assertNotIn("outside_diff\":", fix)
                self.assertIn("(it fails without this branch, or it is flaky)", fix)

    def test_the_second_fix_is_told_only_of_its_own_verifications_rerun(self):
        _, calls = run(replies={"verify": self.OUTSIDE, "verify-rerun-1": self.OUTSIDE, "verify-2": VERIFY_RED})
        self.assertIn("so it is not flaky", prompt(calls, "verify-fix-1"))
        self.assertNotIn("so it is not flaky", prompt(calls, "verify-fix-2"))

    def test_a_failure_inside_the_diff_or_not_placed_is_not_rerun(self):
        inside = {"id": "test", "status": "fail", "summary": "src/a.test.ts", "outside_diff": False}
        outside = {"id": "lint", "status": "fail", "summary": "x", "outside_diff": True}
        for results in ([dict(inside, id="build")], [{"id": "build", "status": "fail", "summary": "boom"}], [outside, inside]):
            with self.subTest(results=results):
                result, calls = run(replies={"verify": {"head": SHA, "clean": True, "results": results}},
                                    patch={"setup": {"verification": TWO_IDS}} if len(results) == 2 else None)
                self.assertNotIn("verify-rerun-1", labels(calls))
                self.assertIn("verify-fix-1", labels(calls))

    def test_the_rerun_names_only_the_failed_ids_and_keeps_the_passes(self):
        first = {"head": SHA, "clean": True,
                 "results": [{"id": "lint", "status": "pass", "summary": "ok"},
                             {"id": "test", "status": "fail", "summary": self.FLAKE, "outside_diff": True}]}
        again = {"head": SHA, "clean": True, "results": [{"id": "test", "status": "pass", "summary": "ok"}]}
        result, calls = run(replies={"verify": first, "verify-rerun-1": again}, patch={"setup": {"verification": TWO_IDS}})
        rerun = prompt(calls, "verify-rerun-1")
        self.assertIn(json.dumps([TWO_IDS[1]], separators=(",", ":")), rerun)
        self.assertNotIn(FULL, rerun)
        self.assertIn(self.FLAKE, rerun)
        self.assertEqual([c["agentType"] for c in calls if c["label"] == "verify-rerun-1"], ["clerk"])
        self.assertEqual(result["stage"], "done")
        self.assertEqual({r["id"]: r["status"] for r in result["verify"]}, {"lint": "pass", "test": "pass"})
        self.assertEqual(result["flaky"], [{"id": "test", "summary": self.FLAKE}])

    def test_a_rerun_at_another_head_on_a_dirty_tree_or_silent_is_not_a_pass(self):
        once = self.GREEN["results"][0]
        for again in (dict(self.GREEN, head=FIXED), dict(self.GREEN, clean=False), None,
                      {"head": SHA, "clean": True, "results": []},
                      dict(self.GREEN, results=[dict(once, status="skipped")]), dict(self.GREEN, results=[once, once])):
            with self.subTest(again=again):
                result, calls = run(replies={"verify": self.OUTSIDE, "verify-rerun-1": again})
                self.assertIn("verify-fix-1", labels(calls))
                self.assertNotIn("flaky", result)

    def test_the_verify_clerk_places_each_failure_against_the_changed_files(self):
        _, calls = run()
        self.assertIn("On each failure also return outside_diff: true only when no failing test file and no erroring file is "
                      "in that git diff --name-only list, else false.", prompt(calls, "verify"))
        self.assertIn("outside_diff", schema_of(calls, "verify")["properties"]["results"]["items"]["properties"])

    def test_a_fix_step_reporting_an_unrelated_failure_stops_naming_the_test_with_no_commit(self):
        result, calls = run(replies={"verify": VERIFY_RED, "verify-fix-1": self.UNRELATED})
        self.assertEqual(result["stage"], "verify-unrelated")
        self.assertIn("tests/http_client.test.ts > retries fails outside this branch's diff, so no fix was made",
                      result["reason"])
        self.assertEqual(result["unrelated"], self.UNRELATED["unrelated"])
        self.assertNotIn("commit", result)
        self.assertIn("cont", result)
        self.assertEqual(labels(calls)[-1], "verify-fix-1")

    def test_an_unrelated_report_that_committed_anyway_stops_too_and_names_the_commit(self):
        result, calls = run(replies={"verify": VERIFY_RED, "verify-fix-1": dict(self.UNRELATED, status="done", commit=FIXED)})
        self.assertEqual((result["stage"], result["commit"]), ("verify-unrelated", FIXED))
        self.assertIn(f"the fix step still committed {FIXED}, unreviewed", result["details"])
        self.assertEqual(labels(calls)[-1], "verify-fix-1")

    def test_an_unrelated_report_without_a_test_or_evidence_is_a_plain_blocked_fix(self):
        for unrelated in ({"test": "", "evidence": "x"}, {"test": "t", "evidence": ""}, "t"):
            with self.subTest(unrelated=unrelated):
                result, _ = run(replies={"verify": VERIFY_RED, "verify-fix-1": dict(self.UNRELATED, unrelated=unrelated)})
                self.assertEqual(result["stage"], "verify-fix")

    def test_the_fix_step_needs_a_cause_before_it_edits_outside_the_diff(self):
        _, calls = run(replies={"verify": VERIFY_RED})
        fix = prompt(calls, "verify-fix-1")
        self.assertIn("When what fails lies outside that diff, first establish with evidence why it fails here: this branch's "
                      "change, or this delivery's environment (the worktree path, the branch name). Only with that cause shown "
                      "may you edit a file outside the diff, and then return outside_diff: [{file, why}]", fix)
        self.assertIn("With no cause established (it fails without this branch, or it is flaky), change and commit nothing and "
                      "return status blocked with unrelated {test, evidence}, evidence being what you ran or read: establish it by "
                      "reading, or by running the test, never by checking out another commit in the worktree.", fix)
        self.assertIn("Never weaken, skip or delete a test to make it pass.", fix)
        properties = schema_of(calls, "verify-fix-1")["properties"]
        self.assertEqual(properties["unrelated"]["required"], ["test", "evidence"])
        self.assertEqual(properties["outside_diff"]["items"]["required"], ["file", "why"])

    OUT = [{"file": "tests/http_client.test.ts", "why": "the sentinel s-1 occurs in the worktree path, so the sweep matches it"}]

    def test_an_out_of_diff_fix_with_a_stated_cause_proceeds_and_is_flagged(self):
        fixed = {"start_head": SHA, "commit": FIXED, "outside_diff": self.OUT}
        out = run_out(replies={"verify": VERIFY_RED}, patch={"verify-fix-1": fixed})
        result, calls = out["result"], out["calls"]
        self.assertEqual((result["stage"], result["outside_fixes"]), ("done", self.OUT))
        self.assertIn(f"verify-fix-1: edited tests/http_client.test.ts, outside the branch's diff: {self.OUT[0]['why']}",
                      out["logs"])
        review = prompt(calls, "verify-fix-review-1")
        self.assertIn(self.OUT[0]["why"], review)
        self.assertIn("a cause the code or the failure does not bear out is an Important defect", review)
        self.assertIn("verification fixes outside the branch's diff, each with its cause", prompt(calls, "pr"))
        self.assertIn(self.OUT[0]["why"], prompt(calls, "pr"))

    def test_a_malformed_out_of_diff_entry_is_not_flagged(self):
        bad = [{"file": "a.ts"}, {"why": "w"}, {"file": "", "why": "w"}, {"file": "a.ts", "why": ""}, "a.ts", None]
        for reported, kept in ((bad + self.OUT, self.OUT), (bad, None), ("a.ts", None), ({"file": "a.ts", "why": "w"}, None)):
            with self.subTest(reported=reported):
                out = run_out(replies={"verify": VERIFY_RED},
                              patch={"verify-fix-1": {"start_head": SHA, "commit": FIXED, "outside_diff": reported}})
                self.assertEqual((out["result"]["stage"], out["result"].get("outside_fixes")), ("done", kept))
                self.assertEqual(len([l for l in out["logs"] if "outside the branch's diff" in l]), len(kept or []))

    def test_a_resume_that_finds_the_head_moved_keeps_the_out_of_diff_fix(self):
        fixed = {"start_head": SHA, "commit": FIXED, "outside_diff": self.OUT}
        ready, _ = run(args=dict(ARGS, mode="ready"), replies={"verify": VERIFY_RED, "verify-2": self.GREEN},
                       patch={"verify-fix-1": fixed})
        self.assertEqual(ready["cont"]["outside_fixes"], self.OUT)
        self.assertNotIn("outside_fixes", ready["cont"]["verified"])
        shipped, calls = run(args=dict(ARGS, cont=ready["cont"]), patch={"setup": {"head": FIXED}})
        self.assertIn("verify", labels(calls))
        self.assertNotIn("verify-fix-1", labels(calls))
        self.assertEqual((shipped["stage"], shipped["outside_fixes"]), ("done", self.OUT))
        self.assertIn(self.OUT[0]["why"], prompt(calls, "pr"))
        stopped, _ = run(args=dict(ARGS, cont=ready["cont"]), replies={"verify": None}, patch={"setup": {"head": FIXED}})
        self.assertEqual((stopped["stage"], stopped["cont"]["outside_fixes"]), ("verify", self.OUT))

    def test_a_fix_inside_the_diff_is_not_flagged(self):
        out = run_out(replies={"verify": VERIFY_RED})
        self.assertNotIn("outside_fixes", out["result"])
        self.assertNotIn("outside the branch's diff", prompt(out["calls"], "verify-fix-review-1"))
        self.assertNotIn("outside the branch's diff", prompt(out["calls"], "pr"))

    def test_a_ready_stop_and_the_ship_resumed_from_it_keep_the_out_of_diff_fix(self):
        fixed = {"start_head": SHA, "commit": FIXED, "outside_diff": self.OUT}
        ready, _ = run(args=dict(ARGS, mode="ready"), replies={"verify": VERIFY_RED, "verify-2": self.GREEN},
                       patch={"verify-fix-1": fixed})
        self.assertEqual((ready["stage"], ready["outside_fixes"]), ("ready", self.OUT))
        shipped, calls = run(args=dict(ARGS, cont=ready["cont"]), patch={"setup": {"head": SHA}})
        self.assertNotIn("verify", labels(calls))
        self.assertEqual((shipped["stage"], shipped["outside_fixes"]), ("done", self.OUT))
        self.assertIn(self.OUT[0]["why"], prompt(calls, "pr"))


class ShipTest(unittest.TestCase):
    def test_checks_wait_uses_the_required_names_rule(self):
        _, calls = run()
        checks = prompt(calls, "pr")
        self.assertIn("gh api repos/owner/repo/rules/branches/dev", checks)
        self.assertIn("never treat a partial list as green", checks)

    def test_failed_checks_stop_unmerged(self):
        fix = "f" * 40
        result, calls = run(replies={"checks-2": {"state": "failed", "head": fix}},
                            patch={"pr": {"checks": {"state": "failed", "head": SHA}},
                                   "fix-ci": {"start_head": SHA, "commit": fix}})
        self.assertEqual(result["stage"], "checks")
        self.assertNotIn("merge", labels(calls))

    def test_clean_sync_rechecks_without_review(self):
        result, calls = run(patch={"pr": {"checks": {"state": "behind", "head": SHA}}})
        self.assertEqual(result["stage"], "done")
        names = labels(calls)
        self.assertEqual(names[names.index("pr"):], ["pr", "sync-1", "checks-2", "merge",
                                                   "hold", "close-out"])

    def test_conflicted_sync_is_rereviewed(self):
        _, calls = run(patch={"pr": {"checks": {"state": "behind", "head": SHA}},
                              "sync-1": ABORTED, "sync-resolve-1": {"conflicted": True, "resolved_files": ["a.py"]}})
        review = [c for c in calls if c["label"] == "sync-review-1"]
        self.assertEqual(review[0]["agentType"], "reviewer")

    def test_conflicted_sync_with_findings_stops(self):
        bad = {"verdict": "findings", "findings": [{"severity": "important", "summary": "lost", "failing_input": "x"}]}
        result, calls = run(replies={"sync-review-1": bad, "fix-sync-review-1": bad},
                            patch={"pr": {"checks": {"state": "behind", "head": SHA}},
                                   "sync-1": ABORTED, "sync-resolve-1": {"conflicted": True, "merge_commit": "d" * 40},
                                   "fix-sync-1": {"start_head": "d" * 40, "commit": "f" * 40}})
        self.assertEqual(result["stage"], "sync-review")
        self.assertNotIn("merge", labels(calls))

    def test_a_conflicted_sync_checks_for_markers_before_it_commits(self):
        """#907: the sync step runs the marker check itself, and a reply that says it ran leaves the review prompt as it was."""
        unchecked = "The merge was not checked for leftover conflict markers"
        behind = {"pr": {"checks": {"state": "behind", "head": SHA}}}
        conflicted = {"conflicted": True, "resolved_files": ["a.py"]}
        result, calls = run(patch=dict(behind, **{"sync-1": ABORTED, "sync-resolve-1": dict(conflicted, markers_checked=True)}))
        self.assertEqual(result["stage"], "done")
        self.assertNotIn("diff --check", prompt(calls, "sync-1"))
        sync = prompt(calls, "sync-resolve-1")
        self.assertRegex(sync, r"run git -C (\S+) diff --check HEAD and git -C \1 diff --check origin/\S+ before committing and remove each "
                               r"leftover conflict marker both report \(same file and line\) in a file you resolved by hand; "
                               r"every other line they report is content and stays")
        self.assertIn("markers_checked (true when both checks ran)", sync)
        self.assertLess(sync.index("diff --check HEAD"), sync.index("commit the merge"))
        self.assertIn("markers_checked", sync)
        self.assertNotIn(unchecked, prompt(calls, "sync-review-1"))
        names = labels(calls)
        for said in ({"markers_checked": False}, {}):
            with self.subTest(said=said):
                result, calls = run(patch=dict(behind, **{"sync-1": ABORTED, "sync-resolve-1": dict(conflicted, **said)}))
                self.assertEqual(result["stage"], "done")
                self.assertIn(unchecked, prompt(calls, "sync-review-1"))
                self.assertEqual(labels(calls), names)

    def test_a_surviving_sync_finding_stops_with_its_reason(self):
        left = {"verdict": "findings", "findings": [{"severity": "important", "summary": "still lost", "failing_input": "x"}]}
        result, calls = run(replies={"sync-review-1": FINDING, "fix-sync-review-1": left},
                            patch={"pr": {"checks": {"state": "behind", "head": SHA}},
                                   "sync-1": ABORTED, "sync-resolve-1": {"conflicted": True, "merge_commit": "d" * 40},
                                   "fix-sync-1": {"start_head": "d" * 40, "commit": "f" * 40}})
        self.assertEqual(result["stage"], "sync-review")
        self.assertIn("still lost", result["reason"])
        self.assertEqual(labels(calls).count("land-unlock"), 1)

    def test_third_behind_is_contention(self):
        behind = {"state": "behind", "head": SHA}
        result, calls = run(replies={"checks-2": behind, "checks-3": behind}, patch={"pr": {"checks": behind}})
        self.assertEqual(result["stage"], "sync-contention")
        self.assertEqual([l for l in labels(calls) if l.startswith("sync-")], ["sync-1", "sync-2"])

    def test_close_out_that_leaves_the_issue_open_is_not_done(self):
        result, _ = run(replies={"close-out": {"issue_state": "OPEN", "notes": "close failed"}})
        self.assertEqual((result["stage"], result["expected_issue_state"]), ("close-out", "CLOSED"))
        self.assertEqual(result["pr"], 42)

    def test_pushed_head_must_be_the_verified_head(self):
        result, calls = run(patch={"pr": {"head": "c" * 40}})
        self.assertEqual((result["stage"], result["expected"]), ("head-moved", SHA))
        self.assertFalse([n for n in labels(calls) if n.startswith("checks-")])
        result, calls = run(patch={"pr": {"checks": {"state": "passed", "head": "c" * 40}}})
        self.assertEqual(result["stage"], "head-moved")
        self.assertNotIn("merge", labels(calls))

    def test_after_a_sync_the_merge_commit_is_the_expected_head(self):
        merge = "d" * 40
        result, calls = run(replies={"checks-2": {"state": "passed", "head": merge}},
                            patch={"pr": {"checks": {"state": "behind", "head": SHA}}, "sync-1": {"merge_commit": merge}})
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
            "merge", "checks-2", "sync-1", "land-push-3",
            "checks-3", "merge", "hold", "close-out"])
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
                                     "checks-2": {"state": "behind", "head": m1},
                                     "checks-3": {"state": "passed", "head": m2},
                                     "checks-4": {"state": "behind", "head": m2},
                                     "checks-5": {"state": "passed", "head": m3}},
                            patch={"pr": {"checks": {"state": "behind", "head": SHA}},
                                   "sync-1": {"merge_commit": m1}, "sync-2": {"merge_commit": m2},
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
# #913: a sync step whose merge conflicts aborts it and answers conflicted; the resolution is its own step, sync-resolve, outside the land lock.
ABORTED = {"status": "conflicted", "conflicted": True, "notes": "a.py conflicts"}
RED = {"state": "failed", "head": SHA, "failing": ["ci-tests"], "details": "FAIL test_cache: host-installed state"}
FINDING = {"verdict": "findings", "findings": [{"severity": "important", "summary": "dropped the new call site", "failing_input": "x"}]}
# The cont every ship stop of the default fresh run carries (observed at the base commit of #801).
SHIP_PINNED = {"lane": "standard", "plan_reviewed": True, "fix_waves": 0, "final_reviewed": {"head": "c0ffee"},
               "done": [{"n": 1, "commit": "c0ffee", "review_rounds": 0, "reviewer": "reviewer"}]}


def ship_cont(**extra):
    """The cont of a ship stop the delivery's land and close-out changes do not touch, checked against the pin."""
    result, _ = run(replies={"merge": None})
    cont = result["cont"]
    if set(cont) != {"setup", "plan"} | set(SHIP_PINNED) or any(cont[k] != v for k, v in SHIP_PINNED.items()):
        raise AssertionError(f"the ship cont moved: {cont}")
    return dict(cont, **extra)


class LandLockTest(unittest.TestCase):
    """#677: ship takes the land lock, waiting, before any sync, holds it through the merge,
    and releases it after the merge and on every stop."""

    BEHIND = {"state": "behind", "head": SHA}

    def test_ship_order_is_lock_then_checks_then_merge_then_release(self):
        result, calls = run()
        self.assertEqual(result["stage"], "done")
        names = labels(calls)
        self.assertEqual(names[names.index("pr"):], ["pr", "merge", "hold", "close-out"])

    def test_lock_commands_are_exact(self):
        _, calls = run()
        self.assertIn(f"forge-claim land acquire --repo owner/repo --branch dev --sha {SHA} --wait\n",
                      prompt(calls, "pr"))
        self.assertIn(f"forge-claim land acquire --repo owner/repo --branch dev --sha {SHA}\n",
                      prompt(calls, "merge"))
        self.assertNotIn(" --wait\n", prompt(calls, "merge"))
        self.assertIn(f"forge-claim land release --repo owner/repo --branch dev --sha {SHA}\n",
                      prompt(calls, "hold"))

    def test_the_lock_is_taken_before_the_sync_merge_and_moved_after_the_push(self):
        merge = "d" * 40
        result, calls = run(replies={"checks-2": {"state": "passed", "head": merge}},
                            patch={"pr": {"checks": self.BEHIND}, "sync-1": {"merge_commit": merge}})
        self.assertEqual(result["stage"], "done")
        names = labels(calls)
        self.assertEqual(names[names.index("pr"):], [
            "pr", "sync-1", "land-push-2",
            "checks-2", "merge", "hold", "close-out"])
        self.assertIn("git -C /r/.wt/w-issue-9-x push origin issue-9-x", prompt(calls, "land-push-2"))
        self.assertIn(f"--sha {merge}\n", prompt(calls, "checks-2"))
        self.assertNotIn(" --wait\n", prompt(calls, "checks-2"))
        self.assertIn(f"forge-claim land release --repo owner/repo --branch dev --sha {merge}",
                      prompt(calls, "hold"))

    def test_a_merge_refused_behind_resyncs_under_the_held_lock(self):
        merge = "d" * 40
        stale = {"merged": False, "behind": True, "notes": "Head branch is not up to date with the base branch"}
        result, calls = run(replies={"merge": [stale, {"merged": True, "merge_commit": merge, "notes": "merged"}],
                                     "checks-2": self.BEHIND, "checks-3": {"state": "passed", "head": merge}},
                            patch={"sync-1": {"merge_commit": merge}})
        self.assertEqual(result["stage"], "done")
        names = labels(calls)
        self.assertNotIn("land-unlock", names)
        later_locks = [c["prompt"] for c in calls if c["label"] in ("checks-3", "merge")]
        self.assertEqual(len(later_locks), 3)  # the first pre-merge check, the move after the push, the last pre-merge check
        for text in later_locks:
            self.assertNotIn(" --wait\n", text)
        self.assertIn("--wait", prompt(calls, "pr"))
        self.assertLess(names.index("pr"), names.index("sync-1"))
        self.assertLess(names.index("sync-1"), names.index("land-push-3"))
        last_merge = len(names) - 1 - names[::-1].index("merge")
        self.assertLess(last_merge, names.index("hold"))

    def test_a_contended_lock_is_waited_for_by_the_cli(self):
        waited = {"verdict": "acquired", "lock_sha": SHA, "waited_s": 1800, "took_over": "idle"}
        result, calls = run(patch={"pr": {"lock": waited}})
        self.assertEqual(result["stage"], "done")
        names = labels(calls)
        self.assertEqual(names[names.index("pr"):names.index("merge")], ["pr"])
        self.assertIn(f"--sha {SHA} --wait\n", prompt(calls, "pr"))

    def test_a_fix_commit_in_short_form_moves_the_lock_by_its_full_sha(self):
        short = FIX[:9]
        result, calls = run(replies={"checks-2": {"state": "passed", "head": FIX, "required": ["ci-tests"]},
                                     "land-push-2": {"head": FIX}},
                            patch={"pr": {"checks": RED}, "fix-ci": {"start_head": SHA, "commit": short}})
        self.assertEqual(result["stage"], "done")
        self.assertIn(f"forge-claim land acquire --repo owner/repo --branch dev --sha {FIX}\n", prompt(calls, "checks-2"))
        self.assertNotIn(f"--sha {short}\n", prompt(calls, "checks-2"))
        self.assertIn(f"forge-claim land release --repo owner/repo --branch dev --sha {FIX}", prompt(calls, "hold"))

    def test_a_non_holding_wait_answer_stops_with_cont(self):
        for verdict in ("land-contended", "held_by", "lost_to"):
            with self.subTest(verdict=verdict):
                refusal = {"lock": {"verdict": verdict, "lock_sha": "b" * 40, "by": "h2/b9"}}
                result, calls = run(replies={f"land-lock-{k}": refusal for k in (1, 2, 3)},
                                    patch={"pr": dict(refusal, checks=None)})
                self.assertEqual((result["stage"], result["pr"], result["lock"]), ("land-contended", 42, verdict))
                self.assertIn("cont", result)
                for gone in ("checks-1", "checks-2", "sync-1", "merge", "land-unlock", "close-out"):
                    self.assertNotIn(gone, labels(calls))
                # #818: only a wait that ran out is waited for again; held_by and lost_to stop at once.
                self.assertEqual([l for l in labels(calls) if l.startswith("land-lock-")],
                                 ["land-lock-1", "land-lock-2", "land-lock-3"] if verdict == "land-contended" else [])

    def test_a_failed_move_releases_the_last_held_sha(self):
        merge = "d" * 40
        result, calls = run(replies={"checks-2": {"lock": {"verdict": "lost_to", "lock_sha": "c" * 40, "by": "h2/b9"}}},
                            patch={"pr": {"checks": self.BEHIND}, "sync-1": {"merge_commit": merge}})
        self.assertEqual(result["stage"], "land-contended")
        self.assertIn("cont", result)
        names = labels(calls)
        self.assertNotIn("merge", names)
        self.assertEqual(names.count("land-unlock"), 1)
        self.assertIn(f"forge-claim land release --repo owner/repo --branch dev --sha {SHA}\n",
                      prompt(calls, "land-unlock"))

    def test_a_push_that_lands_another_head_stops_before_the_lock_moves(self):
        merge = "d" * 40
        result, calls = run(replies={"land-push-2": {"head": "c" * 40}},
                            patch={"pr": {"checks": self.BEHIND}, "sync-1": {"merge_commit": merge}})
        self.assertEqual((result["stage"], result["pr"], result["expected"]), ("head-moved", 42, merge))
        names = labels(calls)
        self.assertNotIn("checks-2", names)
        self.assertEqual(names.count("land-unlock"), 1)
        self.assertIn(f"--sha {SHA}\n", prompt(calls, "land-unlock"))

    def test_a_failed_release_is_reported_and_keeps_the_result(self):
        result, calls = run(replies={"merge": {"merged": False, "notes": "head moved"}, "land-unlock": None})
        self.assertEqual(result["stage"], "merge")
        self.assertIn("cont", result)
        self.assertEqual(result["lock_unreleased"]["sha"], SHA)
        self.assertIn("land-unlock", result["dead_agents"])
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
            "checks": {"replies": {"checks-2": {"state": "failed", "head": fix}},
                       "patch": {"pr": {"checks": {"state": "failed", "head": SHA}},
                                 "fix-ci": {"start_head": SHA, "commit": fix}}},
            "checks-pending": {"replies": {f"checks-{k}": {"state": "pending", "head": SHA, "pending": ["e2e"]}
                                           for k in (2, 3)},
                               "patch": {"pr": {"checks": {"state": "pending", "head": SHA, "pending": ["e2e"]}}}},
            "head-moved": {"patch": {"pr": {"checks": {"state": "passed", "head": "c" * 40}}}},
            "merge": {"replies": {"merge": {"merged": False, "notes": "head moved"}}},
            "sync-contention": {"replies": {"checks-2": self.BEHIND, "checks-3": self.BEHIND},
                                "patch": {"pr": {"checks": self.BEHIND}}},
            "land-contended": {"replies": {"checks-2": {"lock": {"verdict": "lost_to", "lock_sha": "b" * 40}}},
                               "patch": {"pr": {"checks": self.BEHIND}, "sync-1": {"merge_commit": "d" * 40}}},
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
        result, calls = run(patch={"pr": {"checks": {"state": "pending", "head": SHA, "pending": ["e2e"]}},
                                   "checks-2": {"renew": {"verdict": "not_held", "by": "h2/b9"}}})
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


class LandWaitRetryTest(unittest.TestCase):
    """#818: a land-contended answer of the folded acquire --wait is the wait running out behind other landings,
    so the claim is renewed and the same acquire waits again, three times at most."""

    CONTENDED = {"lock": {"verdict": "land-contended", "lock_sha": "b" * 40, "by": "h2/b9"}}
    WAIT_OUT = {"pr": dict(CONTENDED, checks=None)}

    @staticmethod
    def waits(calls):
        return [l for l in labels(calls) if l.startswith("land-lock-")]

    def test_a_contended_wait_then_an_acquired_lock_ships(self):
        result, calls = run(patch=self.WAIT_OUT)
        self.assertEqual(result["stage"], "done")
        names = labels(calls)
        self.assertEqual(names[names.index("pr"):], ["pr", "land-lock-1", "checks-1", "merge", "hold", "close-out"])
        text = prompt(calls, "land-lock-1")
        self.assertIn(f"forge-claim renew --repo owner/repo --issue 9 --holder {HOLDER} --branch issue-9-x", text)
        self.assertIn(f"forge-claim land acquire --repo owner/repo --branch dev --sha {SHA} --wait\n", text)
        self.assertLess(text.index("forge-claim renew"), text.index("forge-claim land acquire"))
        call = next(c for c in calls if c["label"] == "land-lock-1")
        self.assertEqual((call["agentType"], call["model"], call["effort"]), ("clerk", "sonnet", "low"))
        schema = schema_of(calls, "land-lock-1")
        self.assertEqual(schema["required"], ["renew"])
        self.assertIn("verdict", member(schema, "lock")["properties"])
        # The retried wait polled no checks: the first round polls them itself, behind its own renew, and moves no lock.
        self.assertIn("forge-claim renew", prompt(calls, "checks-1"))
        self.assertNotIn("Move the cross-host landing lock", prompt(calls, "checks-1"))
        self.assertIn(f"forge-claim land release --repo owner/repo --branch dev --sha {SHA}\n", prompt(calls, "hold"))

    def test_a_lock_acquired_on_a_later_wait_ships(self):
        result, calls = run(replies={"land-lock-1": self.CONTENDED, "land-lock-2": self.CONTENDED}, patch=self.WAIT_OUT)
        self.assertEqual(result["stage"], "done")
        self.assertEqual(self.waits(calls), ["land-lock-1", "land-lock-2", "land-lock-3"])

    def test_a_wait_contended_on_every_retry_stops_land_contended(self):
        result, calls = run(replies={f"land-lock-{k}": self.CONTENDED for k in (1, 2, 3, 4)}, patch=self.WAIT_OUT)
        self.assertEqual((result["stage"], result["pr"], result["lock"]), ("land-contended", 42, "land-contended"))
        self.assertIn("cont", result)
        names = labels(calls)
        self.assertEqual(names[names.index("pr"):], ["pr", "land-lock-1", "land-lock-2", "land-lock-3"])

    def test_a_not_held_renew_during_a_retry_is_claim_lost(self):
        result, calls = run(replies={"land-lock-1": self.CONTENDED,
                                     "land-lock-2": {"renew": {"verdict": "not_held", "by": "h2/b1"}, "lock": None}},
                            patch=self.WAIT_OUT)
        self.assertEqual((result["stage"], result["at"]), ("claim-lost", "land-lock-2"))
        self.assertNotIn("cont", result)
        self.assertEqual(self.waits(calls), ["land-lock-1", "land-lock-2"])
        # The renew ended, so the prompt ran no lock command: nothing is held and nothing is released.
        for gone in ("checks-1", "merge", "land-unlock", "close-out"):
            self.assertNotIn(gone, labels(calls))

    def test_a_transient_renew_during_a_retry_is_recalled_once(self):
        result, calls = run(replies={"land-lock-1": [{"renew": TRANSIENT, "lock": None},
                                                     {"lock": {"verdict": "acquired", "lock_sha": SHA}}]},
                            patch=self.WAIT_OUT)
        self.assertEqual(result["stage"], "done")
        self.assertEqual(self.waits(calls), ["land-lock-1", "land-lock-1"])

    def test_another_refusal_during_a_retry_stops_without_another_wait(self):
        for verdict in ("held_by", "lost_to"):
            with self.subTest(verdict=verdict):
                result, calls = run(replies={"land-lock-1": {"lock": {"verdict": verdict, "by": "h2/b9"}}},
                                    patch=self.WAIT_OUT)
                self.assertEqual((result["stage"], result["lock"]), ("land-contended", verdict))
                self.assertEqual(self.waits(calls), ["land-lock-1"])
                self.assertNotIn("land-unlock", labels(calls))

    def test_an_unanswered_retry_stops_with_a_release_at_the_pr_head(self):
        # The retried acquire may have taken the lock before its answer was lost or failed, so the stop releases it once.
        for reply in (None, {"lock": None}, {"lock": {"verdict": "error", "detail": "gh failed"}}):
            with self.subTest(reply=reply):
                result, calls = run(replies={"land-lock-1": reply}, patch=self.WAIT_OUT)
                self.assertEqual((result["stage"], result["pr"]), ("land-lock", 42))
                self.assertIn("cont", result)
                self.assertEqual(self.waits(calls), ["land-lock-1"])
                self.assertEqual(labels(calls).count("land-unlock"), 1)
                self.assertIn(f"--sha {SHA}\n", prompt(calls, "land-unlock"))
                self.assertNotIn("merge", labels(calls))

    def test_a_lock_held_at_once_runs_no_retry(self):
        _, calls = run()
        self.assertEqual(self.waits(calls), [])


class ConflictedSyncOutsideLockTest(unittest.TestCase):
    """#913: a sync merge that conflicts is aborted under the land lock and resolved, tested, reviewed and fixed outside it; the
    accepted head takes the lock again, waiting, and a clean merge never leaves it."""

    BEHIND = {"pr": {"checks": {"state": "behind", "head": SHA}}}
    RELEASE = "forge-claim land release --repo owner/repo --branch dev --sha "
    M2 = "e" * 40

    def ship(self, replies=None, **patch):
        return run_out(replies=dict({"checks-2": {"state": "passed", "head": MERGE}}, **(replies or {})),
                       patch={**self.BEHIND, "sync-1": ABORTED, "sync-resolve-1": {"merge_commit": MERGE}, **patch})

    @staticmethod
    def shipped(out):
        names = labels(out["calls"])
        return names[names.index("pr"):]

    def test_a_conflict_is_aborted_released_resolved_and_the_lock_taken_again(self):
        out = self.ship()
        result, calls = out["result"], out["calls"]
        self.assertEqual(result["stage"], "done")
        self.assertEqual(self.shipped(out), ["pr", "sync-1", "land-unlock", "sync-resolve-1", "sync-review-1", "land-push-2",
                                             "checks-2", "merge", "hold", "close-out"])
        sync = prompt(calls, "sync-1")
        self.assertIn("If it conflicts, do not resolve it: run git merge --abort inside /r/.wt/w-issue-9-x", sync)
        self.assertIn("confirm no merge is left in progress", sync)
        self.assertIn("conflicted", next(c for c in calls if c["label"] == "sync-1")["schema"]["properties"]["status"]["enum"])
        # The first hold ends at the head it was taken at, before the resolution starts.
        self.assertIn(f"{self.RELEASE}{SHA}\n", prompt(calls, "land-unlock"))
        resolve = prompt(calls, "sync-resolve-1")
        for text in ("the landing lock is not held while you work", "rev-parse -q --verify MERGE_HEAD", "merge origin/dev", "Do not push."):
            self.assertIn(text, resolve)
        # The accepted head is pushed, then the lock is taken at it with --wait and its checks are polled in the same call.
        self.assertIn(f"at the head {MERGE}", prompt(calls, "land-push-2"))
        checks = prompt(calls, "checks-2")
        self.assertIn(f"forge-claim land acquire --repo owner/repo --branch dev --sha {MERGE} --wait\n", checks)
        self.assertIn("merge-base --is-ancestor origin/dev HEAD", checks)
        merge = prompt(calls, "merge")
        self.assertIn(f"--sha {MERGE}\n", merge)
        self.assertIn("Only when lock's verdict is already_held or moved", merge)
        self.assertIn(f"{self.RELEASE}{MERGE}", prompt(calls, "hold"))
        self.assertNotIn("lock_unreleased", result)

    # #986: the resolver committed the merge MERGE, its tests then caught a defect, and it fixed it in a commit on top: the head M2.
    FOLLOWED = {"merge_commit": MERGE, "head": M2, "resolved_files": ["a.py"], "markers_checked": True}
    DESCENDS = {"verdict": "pass", "findings": [], "descends": True}

    def followed(self, review, replies=None, **patch):
        return run_out(replies=dict({"checks-2": {"state": "passed", "head": self.M2}, "sync-review-1": review}, **(replies or {})),
                       patch={**self.BEHIND, "sync-1": ABORTED, "sync-resolve-1": self.FOLLOWED, **patch})

    def test_a_resolution_with_commits_on_top_of_its_merge_commit_is_reviewed_over_both_and_ships_at_its_head(self):
        out = self.followed(self.DESCENDS)
        result, calls = out["result"], out["calls"]
        self.assertEqual(result["stage"], "done")
        self.assertEqual(self.shipped(out), ["pr", "sync-1", "land-unlock", "sync-resolve-1", "sync-review-1", "land-push-2",
                                             "checks-2", "merge", "hold", "close-out"])
        review = prompt(calls, "sync-review-1")
        wt = "/r/.wt/w-issue-9-x"
        for needle in (f"git -C {wt} show --cc {MERGE}", f"git -C {wt} merge-base --is-ancestor {MERGE} {self.M2}",
                       f"git -C {wt} rev-list --count --min-parents=2 {MERGE}..{self.M2}", f"git -C {wt} diff {MERGE}..{self.M2}",
                       f"git -C {wt} diff --check {MERGE} {self.M2}", "above all for a test or check they weaken, skip or delete"):
            with self.subTest(needle=needle):
                self.assertIn(needle, review)
        self.assertIn("descends", schema_of(calls, "sync-review-1")["required"])
        # Everything downstream is at the head: the push, the lock, the merge and the release.
        self.assertIn(f"at the head {self.M2}", prompt(calls, "land-push-2"))
        self.assertIn(f"forge-claim land acquire --repo owner/repo --branch dev --sha {self.M2} --wait\n", prompt(calls, "checks-2"))
        self.assertIn(f"--match-head-commit {self.M2}", prompt(calls, "merge"))
        self.assertIn(f"{self.RELEASE}{self.M2}", prompt(calls, "hold"))

    def test_a_resolution_whose_head_does_not_descend_from_its_merge_commit_stops(self):
        for name, review in (("unrelated", {"verdict": "pass", "findings": [], "descends": False}),
                             ("unproven", {"verdict": "pass", "findings": []}),
                             ("unrelated with findings", dict(FINDING, descends=False))):
            with self.subTest(review=name):
                out = self.followed(review)
                result = out["result"]
                self.assertEqual(result["stage"], "sync")
                self.assertEqual(result["reason"], f"sync: the resolution names the head {self.M2} and the merge commit {MERGE}, and the head "
                                                   "does not descend from it: only a reviewed merge commit lands")
                names = self.shipped(out)
                for gone in ("fix-sync-1", "land-push-2", "checks-2", "merge"):
                    self.assertNotIn(gone, names)
        # A head that is the merge commit asks for no proof.
        out = self.ship(**{"sync-resolve-1": {"merge_commit": MERGE, "head": MERGE}})
        self.assertEqual(out["result"]["stage"], "done")
        self.assertNotIn("descends", prompt(out["calls"], "sync-review-1"))

    def test_a_clean_sync_whose_head_is_not_its_merge_commit_is_reviewed_too(self):
        """A sync step that committed on top of its clean merge is asked for its head, and those commits are reviewed or refused."""
        clean = {**self.BEHIND, "sync-1": {"conflicted": False, "merge_commit": MERGE, "head": self.M2}}
        out = run_out(replies={"checks-2": {"state": "passed", "head": self.M2}, "sync-review-1": self.DESCENDS}, patch=clean)
        self.assertEqual(out["result"]["stage"], "done")
        self.assertEqual(self.shipped(out), ["pr", "sync-1", "sync-review-1", "land-push-2", "checks-2", "merge", "hold", "close-out"])
        self.assertIn(f"diff {MERGE}..{self.M2}", prompt(out["calls"], "sync-review-1"))
        self.assertIn(f"--match-head-commit {self.M2}", prompt(out["calls"], "merge"))
        self.assertIn("head (the full sha of HEAD after the merge: the merge commit itself, unless you committed on top of it)",
                      prompt(out["calls"], "sync-1"))
        out = run_out(replies={"sync-review-1": {"verdict": "pass", "findings": [], "descends": False}}, patch=clean)
        self.assertEqual(out["result"]["stage"], "sync")
        self.assertNotIn("merge", self.shipped(out))
        # A clean merge whose head is the merge commit runs no review, as ever.
        out = run_out(replies={"checks-2": {"state": "passed", "head": MERGE}},
                      patch={**self.BEHIND, "sync-1": {"conflicted": False, "merge_commit": MERGE, "head": MERGE}})
        self.assertEqual(out["result"]["stage"], "done")
        self.assertNotIn("sync-review-1", self.shipped(out))

    def test_the_fix_wave_of_a_resolution_with_follow_up_commits_starts_at_its_head_and_names_the_range(self):
        fixed = "9" * 40
        out = self.followed(dict(FINDING, descends=True), replies={"checks-2": {"state": "passed", "head": fixed}},
                            **{"fix-sync-1": {"start_head": self.M2, "commit": fixed}})
        calls = out["calls"]
        self.assertEqual(out["result"]["stage"], "done")
        rng = f"merge commit {MERGE} (git -C /r/.wt/w-issue-9-x show --cc {MERGE}) and the commits made on top of it up to the head {self.M2}"
        self.assertIn(rng, prompt(calls, "fix-sync-1"))
        self.assertIn(f"diff {self.M2}..{fixed}", prompt(calls, "fix-sync-review-1"))
        self.assertIn(f"--match-head-commit {fixed}", prompt(calls, "merge"))
        # A fix that started at the merge commit, beneath the follow-up commits, is not a fix of the reviewed head.
        out = self.followed(dict(FINDING, descends=True), **{"fix-sync-1": {"start_head": MERGE, "commit": fixed}})
        self.assertEqual(out["result"]["stage"], "sync-fix")

    def test_the_resolver_runs_its_tests_before_it_commits_the_merge_and_never_amends_it(self):
        calls = self.ship()["calls"]
        resolve = prompt(calls, "sync-resolve-1")
        before = "still before committing, run in full every test file among or covering the files you resolved by hand"
        self.assertLess(resolve.index("diff --check HEAD"), resolve.index(before))
        self.assertLess(resolve.index(before), resolve.index("commit the merge only once they pass"))
        self.assertNotIn(", commit the merge, and run in full", resolve)
        for needle in ("never amend or redo the merge: fix it in a commit on top of it",
                       "head (the full sha of HEAD: the merge commit, or the last commit you made on top of it)"):
            with self.subTest(needle=needle):
                self.assertIn(needle, resolve)
        self.assertIn("head", schema_of(calls, "sync-resolve-1")["properties"])

    def test_a_clean_merge_keeps_the_lock(self):
        result, calls = run(replies={"checks-2": {"state": "passed", "head": MERGE}},
                            patch=dict(self.BEHIND, **{"sync-1": {"merge_commit": MERGE}}))
        self.assertEqual(result["stage"], "done")
        names = labels(calls)
        self.assertEqual(names[names.index("pr"):], ["pr", "sync-1", "land-push-2", "checks-2", "merge", "hold", "close-out"])
        self.assertIn(f"Move the cross-host landing lock of the branch dev for PR #42 to the head {MERGE}", prompt(calls, "checks-2"))
        self.assertNotIn(" --wait\n", prompt(calls, "checks-2"))

    def test_behind_again_after_the_retake_a_clean_merge_stays_under_the_lock(self):
        out = self.ship(replies={"checks-2": {"state": "behind", "head": MERGE, "lock": {"verdict": "acquired", "lock_sha": MERGE}},
                                 "checks-3": {"state": "passed", "head": self.M2}},
                        **{"sync-2": {"merge_commit": self.M2}})
        self.assertEqual(out["result"]["stage"], "done")
        self.assertEqual(self.shipped(out), ["pr", "sync-1", "land-unlock", "sync-resolve-1", "sync-review-1", "land-push-2", "checks-2",
                                             "sync-2", "land-push-3", "checks-3", "merge", "hold", "close-out"])
        again = prompt(out["calls"], "checks-3")
        self.assertIn(f"--sha {self.M2}\n", again)
        self.assertNotIn(" --wait\n", again)
        self.assertIn(f"--match-head-commit {self.M2}", prompt(out["calls"], "merge"))

    def test_behind_again_with_a_second_conflict_is_resolved_outside_the_lock_again(self):
        second = {"sync-2": ABORTED, "sync-resolve-2": {"merge_commit": self.M2}}
        out = self.ship(replies={"checks-2": {"state": "behind", "head": MERGE}, "checks-3": {"state": "passed", "head": self.M2}}, **second)
        self.assertEqual(out["result"]["stage"], "done")
        self.assertEqual(self.shipped(out), [
            "pr", "sync-1", "land-unlock", "sync-resolve-1", "sync-review-1", "land-push-2", "checks-2",
            "sync-2", "land-unlock", "sync-resolve-2", "sync-review-2", "land-push-3", "checks-3", "merge", "hold", "close-out"])
        # Each hold is released once, at the head it was held at.
        unlocks = [c["prompt"] for c in out["calls"] if c["label"] == "land-unlock"]
        self.assertEqual([self.RELEASE + sha + "\n" in text for sha, text in zip((SHA, MERGE), unlocks)], [True, True])
        self.assertIn(f"--sha {self.M2} --wait\n", prompt(out["calls"], "checks-3"))
        # Behind once more: the sync bound ends the delivery with its own reason, and the third hold is released.
        out = self.ship(replies={"checks-2": {"state": "behind", "head": MERGE}, "checks-3": {"state": "behind", "head": self.M2}}, **second)
        self.assertEqual((out["result"]["stage"], out["result"]["syncs"]), ("sync-contention", 2))
        names = labels(out["calls"])
        self.assertNotIn("merge", names)
        self.assertEqual(names.count("land-unlock"), 3)
        self.assertIn(f"{self.RELEASE}{self.M2}\n", prompt(out["calls"], "land-unlock"))

    def test_a_refused_retake_never_merges_and_holds_nothing(self):
        for verdict in ("land-contended", "held_by", "lost_to"):
            with self.subTest(verdict=verdict):
                out = self.ship(replies={"checks-2": {"lock": {"verdict": verdict, "lock_sha": self.M2}},
                                         **{f"land-relock-{k}": {"lock": {"verdict": "land-contended"}} for k in (1, 2, 3)}})
                result, names = out["result"], labels(out["calls"])
                # Only a wait that ran out is waited for again, as often as a first wait is (LAND_WAIT_RETRIES).
                self.assertEqual([name for name in names if name.startswith("land-relock-")],
                                 [f"land-relock-{k}" for k in (1, 2, 3)] if verdict == "land-contended" else [])
                self.assertEqual((result["stage"], result["lock"]), ("land-contended", verdict))
                self.assertNotIn("merge", names)
                # The only release is the one before the resolution.
                self.assertEqual(names.count("land-unlock"), 1)
                self.assertLess(names.index("land-unlock"), names.index("sync-resolve-1"))
                self.assertNotIn("lock_unreleased", result)

    def test_a_retake_that_answers_acquired_still_merges_only_on_the_pre_merge_check(self):
        retaken = {"state": "passed", "head": MERGE, "lock": {"verdict": "acquired", "lock_sha": MERGE, "waited_s": 1740, "waited_on": [2257]}}
        out = self.ship(replies={"checks-2": retaken})
        self.assertEqual(out["result"]["stage"], "done")
        self.assertIn("checks-2: waited 29 min for the land lock of dev behind PR #2257", out["logs"])
        out = self.ship(replies={"checks-2": retaken, "merge": {"merged": False, "notes": "held_by", "lock": {"verdict": "held_by"}}})
        self.assertEqual(out["result"]["stage"], "land-contended")
        self.assertNotIn("hold", labels(out["calls"]))

    def test_a_lost_retake_releases_what_it_may_hold(self):
        out = self.ship(replies={"checks-2": None})
        self.assertEqual(out["result"]["stage"], "land-contended")
        names = labels(out["calls"])
        self.assertEqual(names.count("land-unlock"), 2)
        # The waiting acquire may have taken the lock at the accepted head: the release names it as the second sha.
        last = prompt(out["calls"], "land-unlock")
        self.assertIn(f"When it prints not_held with lock_sha {MERGE}, run alone and exactly: {self.RELEASE}{MERGE}", last)
        self.assertNotIn("merge", names)

    def test_every_stop_outside_the_lock_releases_once_and_accepts_nothing(self):
        stops = {
            "the resolution is lost": ({"sync-resolve-1": None}, {}, "sync"),
            "the resolution is blocked": ({}, {"sync-resolve-1": {"status": "blocked", "notes": "too tangled"}}, "sync"),
            "the review is lost": ({"sync-review-1": None}, {}, "sync-review"),
            "the fix is blocked": ({"sync-review-1": FINDING}, {"fix-sync-1": {"status": "blocked", "notes": "no"}}, "sync-fix"),
            "the finding survives": ({"sync-review-1": FINDING, "fix-sync-review-1": FINDING},
                                     {"fix-sync-1": {"start_head": MERGE, "commit": FIX}}, "sync-review"),
            "the push is lost": ({"land-push-2": None}, {}, "push"),
        }
        for name, (replies, patch, stage) in stops.items():
            with self.subTest(stop=name):
                out = self.ship(replies=replies, **patch)
                result, names = out["result"], labels(out["calls"])
                self.assertEqual(result["stage"], stage)
                self.assertEqual(names.count("land-unlock"), 1)
                self.assertEqual(names[names.index("sync-1") + 1], "land-unlock")
                for gone in ("checks-2", "merge", "hold"):
                    self.assertNotIn(gone, names)
                self.assertNotIn("lock_unreleased", result)

    def test_a_release_that_failed_before_the_resolution_is_tried_again_at_the_stop(self):
        out = self.ship(replies={"land-unlock": [{"verdict": "error", "detail": "boom"}, {"verdict": "released"}], "sync-review-1": None})
        self.assertEqual(out["result"]["stage"], "sync-review")
        unlocks = [c["prompt"] for c in out["calls"] if c["label"] == "land-unlock"]
        self.assertEqual([f"{self.RELEASE}{SHA}\n" in text for text in unlocks], [True, True])
        self.assertNotIn("lock_unreleased", out["result"])
        # When that second release fails too, the result says so.
        out = self.ship(replies={"land-unlock": {"verdict": "error", "detail": "boom"}, "sync-review-1": None})
        self.assertEqual(out["result"]["lock_unreleased"]["sha"], SHA)

    def test_a_sync_step_that_resolved_the_conflict_itself_is_released_and_reviewed(self):
        out = run_out(replies={"checks-2": {"state": "passed", "head": MERGE}},
                      patch=dict(self.BEHIND, **{"sync-1": {"conflicted": True, "merge_commit": MERGE}}))
        self.assertEqual(out["result"]["stage"], "done")
        self.assertEqual(self.shipped(out), ["pr", "sync-1", "land-unlock", "sync-review-1", "land-push-2", "checks-2",
                                             "merge", "hold", "close-out"])
        self.assertIn(f"--sha {MERGE} --wait\n", prompt(out["calls"], "checks-2"))

    def test_a_resolution_that_says_it_merged_cleanly_is_reviewed_all_the_same(self):
        clean = {"sync-resolve-1": {"conflicted": False, "merge_commit": MERGE}}
        out = self.ship(**clean)
        self.assertEqual(out["result"]["stage"], "done")
        self.assertEqual(self.shipped(out), ["pr", "sync-1", "land-unlock", "sync-resolve-1", "sync-review-1", "land-push-2", "checks-2",
                                             "merge", "hold", "close-out"])
        self.assertIn(f"merge commit {MERGE}", prompt(out["calls"], "sync-review-1"))
        self.assertIn(f"--sha {MERGE} --wait\n", prompt(out["calls"], "checks-2"))
        out = self.ship(replies={"sync-review-1": FINDING, "fix-sync-review-1": FINDING},
                        **clean, **{"fix-sync-1": {"start_head": MERGE, "commit": FIX}})
        self.assertEqual(out["result"]["stage"], "sync-review")
        self.assertNotIn("merge", labels(out["calls"]))

    def test_a_retake_whose_wait_ran_out_waits_again_like_a_first_wait(self):
        out_of_time = {"lock": {"verdict": "land-contended", "lock_sha": self.M2, "waited_s": 3600, "waited_on": [7]}}
        out = self.ship(replies={"checks-2": out_of_time, "checks-3": {"state": "passed", "head": MERGE},
                                 "land-relock-1": {"lock": {"verdict": "land-contended"}},
                                 "land-relock-2": {"lock": {"verdict": "acquired", "lock_sha": MERGE, "waited_s": 900, "waited_on": [7, 9]}}})
        result, calls = out["result"], out["calls"]
        self.assertEqual(result["stage"], "done")
        # A retried wait polled no checks: the next round polls them, under the lock, before the merge.
        self.assertEqual(self.shipped(out), ["pr", "sync-1", "land-unlock", "sync-resolve-1", "sync-review-1", "land-push-2", "checks-2",
                                             "land-relock-1", "land-relock-2", "checks-3", "merge", "hold", "close-out"])
        again = next(c for c in calls if c["label"] == "land-relock-2")
        self.assertEqual((again["agentType"], again["model"]), ("clerk", "sonnet"))
        self.assertIn("forge-claim renew --repo owner/repo --issue 9", again["prompt"])
        self.assertIn(f"forge-claim land acquire --repo owner/repo --branch dev --sha {MERGE} --wait\n", again["prompt"])
        self.assertNotIn("land acquire --repo", prompt(calls, "checks-3"))
        self.assertIn(f"{self.RELEASE}{MERGE}", prompt(calls, "hold"))
        self.assertEqual([line for line in out["logs"] if "waited" in line],
                         ["checks-2: waited 60 min for the land lock of dev behind PR #7",
                          "land-relock-2: waited 15 min for the land lock of dev behind PR #7, #9"])
        # A lost claim ends the wait; a lost reply may hold the lock at the accepted head, which the stop's release covers.
        out = self.ship(replies={"checks-2": out_of_time, "land-relock-1": {"renew": {"verdict": "not_held", "by": "h2/b1"}, "lock": None}})
        self.assertEqual((out["result"]["stage"], out["result"]["at"]), ("claim-lost", "land-relock-1"))
        self.assertEqual(labels(out["calls"]).count("land-unlock"), 1)
        out = self.ship(replies={"checks-2": out_of_time, "land-relock-1": None})
        self.assertEqual(out["result"]["stage"], "land-lock")
        self.assertEqual(labels(out["calls"]).count("land-unlock"), 2)
        self.assertIn(f"When it prints not_held with lock_sha {MERGE}, run alone and exactly: {self.RELEASE}{MERGE}",
                      prompt(out["calls"], "land-unlock"))
        self.assertNotIn("merge", labels(out["calls"]))

    def test_a_long_first_wait_is_logged_with_its_holders(self):
        def waits(**lock):
            out = run_out(patch={"pr": {"lock": dict({"verdict": "acquired", "lock_sha": SHA}, **lock)}})
            return [line for line in out["logs"] if "waited" in line]
        self.assertEqual(waits(waited_s=1740, waited_on=[2218]), ["pr: waited 29 min for the land lock of dev behind PR #2218"])
        self.assertEqual(waits(waited_s=240, waited_on=[2218]), [])
        _, calls = run()
        self.assertIn("lock_sha, by, detail, waited_s and waited_on from its output", prompt(calls, "pr"))


class ResolveBeforeLockTest(unittest.TestCase):
    """#941: before it asks for the land lock, the pr call probes whether the integration branch merges cleanly into the head. A clean
    probe changes nothing; a conflict is resolved, reviewed and fixed before any lock command, and the accepted head takes the lock."""

    PROBE_CMD = "git -C /r/.wt/w-issue-9-x merge-tree --write-tree --name-only --no-messages HEAD origin/dev"
    RELEASE = "forge-claim land release --repo owner/repo --branch dev --sha "
    # The probe found a conflict, so the pr call ran no lock command and waited for no check.
    EARLY = {"probe": {"conflicted": True, "tree": "e" * 40, "files": ["a.py"]}, "lock": None, "checks": None}
    RESOLVED = ["pr", "sync-resolve-1", "sync-review-1", "land-push-1", "checks-1"]
    M2 = "e" * 40
    M3 = "9" * 40

    def ship(self, replies=None, **patch):
        return run_out(replies=dict({"checks-1": {"state": "passed", "head": MERGE}}, **(replies or {})),
                       patch={"pr": self.EARLY, "sync-resolve-1": {"merge_commit": MERGE}, **patch})

    @staticmethod
    def shipped(out):
        names = labels(out["calls"])
        return names[names.index("pr"):]

    @staticmethod
    def steps(calls):
        return [(c["label"], c["prompt"]) for c in calls]

    def test_the_probe_runs_in_the_pr_call_before_the_lock_and_changes_nothing(self):
        _, calls = run()
        text = prompt(calls, "pr")
        self.assertIn(f"run git -C /r/.wt/w-issue-9-x fetch origin, then alone and exactly: {self.PROBE_CMD}\n", text)
        for needle in ("exit 1 is a conflict only when the first line of its output is a tree id (40 hexadecimal characters)",
                       "(a missing ref prints nothing there)", "never run git merge in this step",
                       "When probe's conflicted is true, run no lock command and wait for no check: return lock null and checks null"):
            self.assertIn(needle, text)
        self.assertEqual(member(schema_of(calls, "pr"), "probe")["properties"]["tree"], {"type": "string"})
        self.assertLess(text.index("push origin issue-9-x"), text.index(self.PROBE_CMD))
        self.assertLess(text.index(self.PROBE_CMD), text.index(f"--sha {SHA} --wait\n"))
        schema = schema_of(calls, "pr")
        self.assertIn({"type": "null"}, schema["properties"]["probe"]["anyOf"])
        self.assertEqual(member(schema, "probe")["required"], ["conflicted"])
        self.assertEqual(schema["required"], ["renew"])

    def test_a_clean_probe_is_the_old_flow_with_the_same_calls(self):
        for name, checks in (("current", {"state": "passed", "head": SHA, "required": ["ci"]}), ("behind", {"state": "behind", "head": SHA})):
            base = run(patch={"pr": {"checks": checks}})[1]
            for probe in (None, {"conflicted": False}, {"conflicted": False, "detail": "fatal: not a tree"}):
                with self.subTest(name=name, probe=probe):
                    result, calls = run(patch={"pr": {"checks": checks, "probe": probe}})
                    self.assertEqual(self.steps(calls), self.steps(base))
                    self.assertEqual(result["stage"], "done")
        names = labels(run()[1])
        self.assertEqual(names[names.index("pr"):], ["pr", "merge", "hold", "close-out"])

    def test_exit_one_without_a_tree_id_is_no_conflict(self):
        """git merge-tree also exits 1, with nothing on stdout, when a ref is missing: only a tree id proves a conflict."""
        base = self.steps(run()[1])
        for tree in (None, "", "merge-tree: origin/dev - not something we can merge", "e" * 39, "E" * 40):
            probe = {"conflicted": True, "files": []} if tree is None else {"conflicted": True, "tree": tree, "files": []}
            with self.subTest(tree=tree):
                result, calls = run(patch={"pr": {"probe": probe}})
                self.assertEqual(self.steps(calls), base)
                self.assertEqual(result["stage"], "done")
                # A call that ran no lock command on such a reply resolves nothing: it stops at the lock and releases the verified head.
                out = run_out(patch={"pr": {"probe": probe, "lock": None, "checks": None}})
                self.assertEqual(out["result"]["stage"], "land-lock")
                self.assertEqual(self.shipped(out), ["pr", "land-unlock"])
                self.assertIn(f"{self.RELEASE}{SHA}\n", prompt(out["calls"], "land-unlock"))

    def test_a_conflicted_probe_that_still_names_a_lock_verdict_is_the_old_flow(self):
        out = run_out(replies={"checks-2": {"state": "passed", "head": MERGE}},
                      patch={"pr": {"probe": {"conflicted": True, "tree": "e" * 40}, "checks": {"state": "behind", "head": SHA}},
                             "sync-1": ABORTED, "sync-resolve-1": {"merge_commit": MERGE}})
        self.assertEqual(out["result"]["stage"], "done")
        self.assertEqual(self.shipped(out), ["pr", "sync-1", "land-unlock", "sync-resolve-1", "sync-review-1", "land-push-2", "checks-2",
                                             "merge", "hold", "close-out"])

    def test_a_conflict_is_resolved_and_reviewed_before_any_acquire_and_the_accepted_head_lands(self):
        out = self.ship()
        result, calls = out["result"], out["calls"]
        self.assertEqual(result["stage"], "done")
        self.assertEqual(self.shipped(out), self.RESOLVED + ["merge", "hold", "close-out"])
        self.assertIn("dev conflicts with the head; resolving before the land lock is asked for", out["logs"])
        # The resolution and its review are the #913 steps, word for word.
        under = ConflictedSyncOutsideLockTest().ship()["calls"]
        for label in ("sync-resolve-1", "sync-review-1"):
            with self.subTest(label=label):
                self.assertEqual(prompt(calls, label), prompt(under, label))
        self.assertIn("diff --check HEAD", prompt(calls, "sync-resolve-1"))
        # The accepted head is pushed, then takes the lock for the first time, waiting, and its checks are polled in the same call.
        self.assertIn(f"at the head {MERGE}", prompt(calls, "land-push-1"))
        checks = prompt(calls, "checks-1")
        self.assertIn(f"Take the cross-host landing lock of the branch dev for PR #42 at the head {MERGE}; "
                      "a conflict with dev was resolved before the lock was asked for", checks)
        self.assertIn(f"forge-claim land acquire --repo owner/repo --branch dev --sha {MERGE} --wait\n", checks)
        self.assertIn("merge-base --is-ancestor origin/dev HEAD", checks)
        merge = prompt(calls, "merge")
        self.assertIn(f"--sha {MERGE}\n", merge)
        self.assertIn(f"--match-head-commit {MERGE}", merge)
        # One hold, taken at the accepted head and released there once, in the hold call: no step ever held the verified head.
        releases = [sha for c in calls for sha in re.findall(re.escape(self.RELEASE) + r"([0-9a-f]+)", c["prompt"])]
        self.assertEqual(releases, [MERGE])
        self.assertNotIn("lock_unreleased", result)
        self.assertEqual(result["syncs"], 1)

    def test_a_finding_goes_through_the_fix_wave_and_the_fix_is_what_lands(self):
        out = self.ship(replies={"sync-review-1": FINDING, "checks-1": {"state": "passed", "head": FIX}},
                        **{"fix-sync-1": {"start_head": MERGE, "commit": FIX}})
        self.assertEqual(out["result"]["stage"], "done")
        self.assertEqual(self.shipped(out), ["pr", "sync-resolve-1", "sync-review-1", "fix-sync-1", "fix-sync-review-1", "land-push-1",
                                             "checks-1", "merge", "hold", "close-out"])
        self.assertIn(f"--sha {FIX} --wait\n", prompt(out["calls"], "checks-1"))
        self.assertIn(f"--match-head-commit {FIX}", prompt(out["calls"], "merge"))

    def test_every_stop_before_the_lock_releases_the_verified_head_once_and_accepts_nothing(self):
        stops = {
            "the resolution is lost": ({"sync-resolve-1": None}, {}, "sync"),
            "the resolution is blocked": ({}, {"sync-resolve-1": {"status": "blocked", "notes": "too tangled"}}, "sync"),
            "the review is lost": ({"sync-review-1": None}, {}, "sync-review"),
            "the fix is blocked": ({"sync-review-1": FINDING}, {"fix-sync-1": {"status": "blocked", "notes": "no"}}, "sync-fix"),
            "the finding survives": ({"sync-review-1": FINDING, "fix-sync-review-1": FINDING},
                                     {"fix-sync-1": {"start_head": MERGE, "commit": FIX}}, "sync-review"),
            "the push is lost": ({"land-push-1": None}, {}, "push"),
        }
        for name, (replies, patch, stage) in stops.items():
            with self.subTest(stop=name):
                out = self.ship(replies=replies, **patch)
                result, names = out["result"], labels(out["calls"])
                self.assertEqual(result["stage"], stage)
                for gone in ("sync-1", "checks-1", "merge", "hold"):
                    self.assertNotIn(gone, names)
                # A pr call that answered conflicted may have taken the lock all the same: the stop releases the verified head, once, last.
                self.assertEqual((names.count("land-unlock"), names[-1]), (1, "land-unlock"))
                self.assertIn(f"{self.RELEASE}{SHA}\n", prompt(out["calls"], "land-unlock"))
                self.assertNotIn(f"lock_sha {MERGE}", prompt(out["calls"], "land-unlock"))
                self.assertNotIn("lock_unreleased", result)
                if stage != "push":
                    self.assertNotIn("final_reviewed", result["cont"])

    def test_a_resume_after_a_stop_before_the_lock_reviews_again(self):
        stopped, _ = run(replies={"sync-review-1": None},
                         patch={"pr": self.EARLY, "impl-1": {"commit": TIP}, "sync-resolve-1": {"conflicted": True, "merge_commit": MERGE}})
        self.assertEqual(stopped["stage"], "sync-review")
        self.assertNotIn("final_reviewed", stopped["cont"])
        result, calls = run(args=dict(ARGS, cont=stopped["cont"]), patch={"setup": {"head": MERGE, "since_reviewed": "merge_only"}})
        self.assertEqual(result["stage"], "done")
        names = labels(calls)
        self.assertIn("final-1", names)
        self.assertLess(names.index("final-1"), names.index("merge"))

    def test_lost_and_refused_replies_on_the_new_step_order_keep_the_lock_accounting(self):
        refused = lambda v: {"lock": {"verdict": v, "lock_sha": self.M2}}
        waits = {f"land-relock-{k}": {"lock": {"verdict": "land-contended"}} for k in (1, 2, 3)}
        cases = {
            # The waiting acquire may have taken the lock at the accepted head before its reply was lost: the stop releases it there.
            "the first take is lost": ({"checks-1": None}, "land-contended", 1),
            "held by another": ({"checks-1": refused("held_by")}, "land-contended", 0),
            "lost to another": ({"checks-1": refused("lost_to")}, "land-contended", 0),
            "every wait ran out": ({"checks-1": refused("land-contended"), **waits}, "land-contended", 0),
            "a relock is lost": ({"checks-1": refused("land-contended"), "land-relock-1": None}, "land-lock", 1),
            "the merge check lost the lock": ({"merge": {"merged": False, "notes": "held_by", "lock": {"verdict": "held_by"}}}, "land-contended", 1),
        }
        for name, (replies, stage, unlocks) in cases.items():
            with self.subTest(case=name):
                out = self.ship(replies=replies)
                result, names = out["result"], labels(out["calls"])
                self.assertEqual(result["stage"], stage)
                self.assertEqual(names.count("land-unlock"), unlocks)
                if unlocks:
                    self.assertIn(f"{self.RELEASE}{MERGE}\n", prompt(out["calls"], "land-unlock"))
                self.assertNotIn("hold", names)
                self.assertNotIn("lock_unreleased", result)
        # A wait that ran out at the CLI's bound is waited for again through the program, in a land-relock step.
        out = self.ship(replies={"checks-1": refused("land-contended"), "checks-2": {"state": "passed", "head": MERGE}})
        self.assertEqual(out["result"]["stage"], "done")
        self.assertEqual(self.shipped(out), self.RESOLVED + ["land-relock-1", "checks-2", "merge", "hold", "close-out"])
        self.assertIn(f"--sha {MERGE} --wait\n", prompt(out["calls"], "land-relock-1"))

    def test_a_lost_or_ended_pr_call_is_handled_as_before_the_probe(self):
        out = run_out(replies={"pr": None})
        self.assertEqual(out["result"]["stage"], "pr")
        self.assertIn(f"{self.RELEASE}{SHA}\n", prompt(out["calls"], "land-unlock"))
        out = run_out(patch={"pr": dict(self.EARLY, renew={"verdict": "not_held", "by": "h2/b9"})})
        self.assertEqual(out["result"]["stage"], "claim-lost")
        self.assertNotIn("sync-resolve-1", labels(out["calls"]))
        out = run_out(patch={"pr": dict(self.EARLY, head="c" * 40)})
        self.assertEqual(out["result"]["stage"], "head-moved")
        self.assertNotIn("land-unlock", labels(out["calls"]))

    def test_a_conflict_after_the_acquire_takes_the_913_path(self):
        out = self.ship(replies={"checks-1": {"state": "behind", "head": MERGE}, "checks-2": {"state": "passed", "head": self.M2}},
                        **{"sync-2": ABORTED, "sync-resolve-2": {"merge_commit": self.M2}})
        self.assertEqual(out["result"]["stage"], "done")
        self.assertEqual(self.shipped(out), self.RESOLVED + ["sync-2", "land-unlock", "sync-resolve-2", "sync-review-2", "land-push-2",
                                                             "checks-2", "merge", "hold", "close-out"])
        # The hold taken at the accepted head is released before the second resolution; the retake waits at the second accepted head.
        self.assertIn(f"{self.RELEASE}{MERGE}\n", prompt(out["calls"], "land-unlock"))
        retake = prompt(out["calls"], "checks-2")
        self.assertIn(f"Take the cross-host landing lock of the branch dev for PR #42 again, at the head {self.M2}; "
                      "it was released while a conflict was resolved", retake)
        self.assertIn(f"--sha {self.M2} --wait\n", retake)

    def test_the_round_before_the_lock_spends_no_sync_contention(self):
        clean = {"checks-1": {"state": "behind", "head": MERGE}, "checks-2": {"state": "behind", "head": self.M2},
                 "checks-3": {"state": "passed", "head": self.M3}}
        merges = {"sync-2": {"merge_commit": self.M2}, "sync-3": {"merge_commit": self.M3}}
        out = self.ship(replies=clean, **merges)
        self.assertEqual((out["result"]["stage"], out["result"]["syncs"]), ("done", 3))
        self.assertEqual(self.shipped(out), self.RESOLVED + ["sync-2", "land-push-2", "checks-2", "sync-3", "land-push-3", "checks-3",
                                                             "merge", "hold", "close-out"])
        self.assertNotIn(" --wait\n", prompt(out["calls"], "checks-2"))
        out = self.ship(replies=dict(clean, **{"checks-3": {"state": "behind", "head": self.M3}}), **merges)
        self.assertEqual((out["result"]["stage"], out["result"]["syncs"]), ("sync-contention", 3))
        self.assertIn(f"{self.RELEASE}{self.M3}\n", prompt(out["calls"], "land-unlock"))


class ShipFixWaveTest(unittest.TestCase):
    """#649 defect 2 and the sync-review decision: one bounded fix wave, then a stop with cont."""

    def red_then(self, second, **patch):
        return run(replies={"checks-2": second},
                   patch=dict({"pr": {"checks": RED}, "fix-ci": {"start_head": SHA, "commit": FIX}}, **patch))

    def test_failed_check_runs_one_fix_wave_then_merges(self):
        result, calls = self.red_then({"state": "passed", "head": FIX, "required": ["ci-tests"]})
        self.assertEqual(result["stage"], "done")
        names = labels(calls)
        self.assertEqual(names[names.index("pr"):], [
            "pr", "fix-ci", "fix-ci-review", "land-push-2", "checks-2",
            "merge", "hold", "close-out"])
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
        result, calls = run(args=dict(ARGS, cont=stopped["cont"]), patch={"pr": {"checks": RED}})
        self.assertEqual(result["stage"], "checks")
        self.assertNotIn("fix-ci", labels(calls))

    def test_failed_or_unreviewed_fix_stops(self):
        cases = {
            "checks-fix": ({}, {"fix-ci": {"status": "blocked", "notes": "no"}}),
            "checks-fix ": ({}, {"fix-ci": {"start_head": SHA, "commit": None}}),
            "checks-fix-review": ({"fix-ci-review": FINDING}, {}),
            "checks-fix-review ": ({"fix-ci-review": None}, {}),
        }
        for stage, (replies, patch) in cases.items():
            with self.subTest(case=stage):
                result, calls = run(replies=replies,
                                    patch=dict({"pr": {"checks": RED}, "fix-ci": {"start_head": SHA, "commit": FIX}}, **patch))
                self.assertEqual(result["stage"], stage.strip())
                self.assertIn("cont", result)
                self.assertNotIn("merge", labels(calls))

    RERAN = {"start_head": SHA, "commit": SHA, "notes": "cache restore failed in setup; failed jobs rerun"}

    def test_a_rerun_at_the_unchanged_head_polls_again_then_ships(self):
        # #818: done at the unchanged head is a rerun of jobs that failed for no cause in the code.
        result, calls = run(replies={"checks-2": {"state": "passed", "head": SHA, "required": ["ci-tests"]}},
                            patch={"pr": {"checks": RED}, "fix-ci": self.RERAN})
        self.assertEqual(result["stage"], "done")
        names = labels(calls)
        self.assertEqual(names[names.index("pr"):], ["pr", "fix-ci", "checks-2", "merge", "hold", "close-out"])
        self.assertIn("forge-claim renew", prompt(calls, "checks-2"))
        self.assertNotIn("Move the cross-host landing lock", prompt(calls, "checks-2"))
        self.assertIn(f"--match-head-commit {SHA}", prompt(calls, "merge"))

    def test_a_rerun_in_short_form_is_the_unchanged_head(self):
        result, calls = run(replies={"checks-2": {"state": "passed", "head": SHA}},
                            patch={"pr": {"checks": RED}, "fix-ci": dict(self.RERAN, commit=SHA[:9])})
        self.assertEqual(result["stage"], "done")
        self.assertNotIn("fix-ci-review", labels(calls))
        self.assertNotIn("land-push-2", labels(calls))

    def test_a_rerun_that_is_still_red_stops_as_the_ci_failure(self):
        result, calls = run(replies={"checks-2": RED}, patch={"pr": {"checks": RED}, "fix-ci": self.RERAN})
        self.assertEqual((result["stage"], result["failing"]), ("checks", ["ci-tests"]))
        self.assertEqual(result["cont"]["checks_fixes"], 1)
        names = labels(calls)
        self.assertEqual(names[names.index("pr"):], ["pr", "fix-ci", "checks-2", "land-unlock"])

    # #986: the gate failed only because another check flaked; that check's rerun passed and the gate, in its own run, shows its old failure.
    STALE_GATE = {"state": "failed", "head": SHA, "failing": ["required-checks"], "stale": [43286872194]}
    STALE_LEAD = "This poll follows a rerun of failed jobs at this head."

    def test_a_gate_left_stale_by_a_rerun_is_rerun_by_the_poll_and_does_not_count_as_red(self):
        out = run_out(replies={"checks-2": self.STALE_GATE, "checks-3": {"state": "passed", "head": SHA, "required": ["ci-tests"]}},
                      patch={"pr": {"checks": RED}, "fix-ci": self.RERAN})
        result, calls = out["result"], out["calls"]
        self.assertEqual(result["stage"], "done")
        names = labels(calls)
        self.assertEqual(names[names.index("pr"):], ["pr", "fix-ci", "checks-2", "checks-3", "merge", "hold", "close-out"])
        self.assertIn("checks-2 reran a stale gate run (43286872194); polling once more", out["logs"])
        asked = prompt(calls, "checks-2")
        for needle in (self.STALE_LEAD, "a gate or aggregate job", "gh run view <run-id> --repo owner/repo --json updatedAt",
                       "Only when every failing check is stale",
                       "gh run rerun <run-id> --repo owner/repo --failed", "stale: the run ids you reran"):
            with self.subTest(needle=needle):
                self.assertIn(needle, asked)
        self.assertIn("stale", schema_of(calls, "checks-2")["properties"])
        self.assertNotIn(self.STALE_LEAD, prompt(calls, "checks-3"))
        self.assertNotIn("stale", schema_of(calls, "checks-3")["properties"])
        self.assertNotIn(self.STALE_LEAD, prompt(calls, "pr"))

    def test_a_check_still_red_after_the_stale_rerun_stops_as_the_ci_failure(self):
        for name, third in (("red", dict(RED, failing=["required-checks"])), ("stale again", self.STALE_GATE)):
            with self.subTest(third=name):
                result, calls = run(replies={"checks-2": self.STALE_GATE, "checks-3": third},
                                    patch={"pr": {"checks": RED}, "fix-ci": self.RERAN})
                self.assertEqual((result["stage"], result["failing"]), ("checks", ["required-checks"]))
                names = labels(calls)
                self.assertEqual(names[names.index("pr"):], ["pr", "fix-ci", "checks-2", "checks-3", "land-unlock"])

    def test_stale_is_read_only_from_the_poll_that_follows_a_rerun(self):
        # A first poll that names stale runs is a red poll like any other: it spends the one fix, and the next red poll stops.
        result, calls = run(replies={"checks-2": RED}, patch={"pr": {"checks": self.STALE_GATE}, "fix-ci": self.RERAN})
        self.assertEqual(result["stage"], "checks")
        names = labels(calls)
        self.assertEqual(names[names.index("pr"):], ["pr", "fix-ci", "checks-2", "land-unlock"])
        # The poll after a code fix moved the head is not asked either.
        result, calls = self.red_then(dict(self.STALE_GATE, head=FIX))
        self.assertEqual(result["stage"], "checks")
        self.assertNotIn(self.STALE_LEAD, prompt(calls, "checks-2"))
        self.assertNotIn("checks-3", labels(calls))

    def test_the_ci_fix_prompt_reruns_every_failed_run_of_the_head_a_gate_included(self):
        _, calls = run(replies={"checks-2": {"state": "passed", "head": SHA}},
                       patch={"setup": {"unset_env": ["GITHUB_TOKEN"]}, "pr": {"checks": RED}, "fix-ci": self.RERAN})
        text = prompt(calls, "fix-ci")
        for needle in (f"unset GITHUB_TOKEN && gh run list --repo owner/repo --commit {SHA} --json databaseId,workflowName,conclusion",
                       "keep the newest run of each workflowName (the highest databaseId; never an older run that one superseded)",
                       "rerun each of those whose conclusion is failure, cancelled or timed_out, not only the run of the check that broke first",
                       "a gate or aggregate check that failed only because another check failed is rerun too, with the same command"):
            with self.subTest(needle=needle):
                self.assertIn(needle, text)

    def test_the_ci_fix_prompt_tells_a_causeless_failure_to_rerun(self):
        _, calls = run(replies={"checks-2": {"state": "passed", "head": SHA}},
                       patch={"setup": {"unset_env": ["GITHUB_TOKEN"]}, "pr": {"checks": RED}, "fix-ci": self.RERAN})
        text = prompt(calls, "fix-ci")
        for needle in ("no cause in the code", "change and commit nothing",
                       "unset GITHUB_TOKEN && gh run rerun <run-id> --repo owner/repo --failed",
                       "do not wait for them", f"head unchanged (commit equal to start_head, {SHA})",
                       "the program then polls the checks itself"):
            self.assertIn(needle, text)

    def test_a_sync_fix_at_the_unchanged_head_is_still_a_failure(self):
        # The rerun answer belongs to the CI fix alone: a sync fix with no commit and no rebuttal stops as before.
        result, calls = run(replies={"sync-review-1": FINDING},
                            patch={"pr": {"checks": {"state": "behind", "head": SHA}},
                                   "sync-1": ABORTED, "sync-resolve-1": {"conflicted": True, "merge_commit": MERGE},
                                   "fix-sync-1": {"start_head": MERGE, "commit": MERGE, "notes": ""}})
        self.assertEqual(result["stage"], "sync-fix")
        for gone in ("fix-sync-review-1", "checks-2", "merge"):
            self.assertNotIn(gone, labels(calls))
        self.assertNotIn("gh run rerun", prompt(calls, "fix-sync-1"))

    def test_failed_check_on_another_head_is_head_moved_not_fixed(self):
        result, calls = run(patch={"pr": {"checks": dict(RED, head="c" * 40)}})
        self.assertEqual(result["stage"], "head-moved")
        self.assertNotIn("fix-ci", labels(calls))

    def test_checks_prompt_asks_for_failing_names_and_the_log_tail(self):
        _, calls = run()
        checks = prompt(calls, "pr")
        self.assertIn("failing", checks)
        self.assertIn("--log-failed", checks)

    def test_sync_review_finding_gets_one_fix_wave_then_merges(self):
        result, calls = run(replies={"sync-review-1": FINDING,
                                     "checks-2": {"state": "passed", "head": FIX, "required": ["ci-tests"]}},
                            patch={"pr": {"checks": {"state": "behind", "head": SHA}},
                                   "sync-1": ABORTED, "sync-resolve-1": {"conflicted": True, "merge_commit": MERGE, "resolved_files": ["a.py"]},
                                   "fix-sync-1": {"start_head": MERGE, "commit": FIX}})
        self.assertEqual(result["stage"], "done")
        names = labels(calls)
        self.assertEqual(names[names.index("sync-1"):names.index("checks-2")],
                         ["sync-1", "land-unlock", "sync-resolve-1", "sync-review-1", "fix-sync-1", "fix-sync-review-1", "land-push-2"])
        fix = prompt(calls, "fix-sync-1")
        self.assertIn(MERGE, fix)
        self.assertIn("dropped the new call site", fix)
        self.assertEqual([c["agentType"] for c in calls if c["label"] == "fix-sync-review-1"], ["reviewer"])
        self.assertIn(f"diff {MERGE}..{FIX}", prompt(calls, "fix-sync-review-1"))
        self.assertIn(f"--match-head-commit {FIX}", prompt(calls, "merge"))

    def test_failed_sync_fix_stops(self):
        result, calls = run(replies={"sync-review-1": FINDING},
                            patch={"pr": {"checks": {"state": "behind", "head": SHA}},
                                   "sync-1": ABORTED, "sync-resolve-1": {"conflicted": True, "merge_commit": MERGE},
                                   "fix-sync-1": {"status": "blocked", "notes": "no"}})
        self.assertEqual(result["stage"], "sync-fix")
        self.assertNotIn("merge", labels(calls))

    def test_a_second_sync_review_finding_stops_without_a_second_wave(self):
        result, calls = run(replies={"sync-review-1": FINDING,
                                     "checks-2": {"state": "behind", "head": FIX}, "sync-review-2": FINDING},
                            patch={"pr": {"checks": {"state": "behind", "head": SHA}},
                                   "sync-1": ABORTED, "sync-resolve-1": {"conflicted": True, "merge_commit": MERGE},
                                   "fix-sync-1": {"start_head": MERGE, "commit": FIX},
                                   "sync-2": ABORTED, "sync-resolve-2": {"conflicted": True, "merge_commit": "e" * 40}})
        self.assertEqual(result["stage"], "sync-review")
        self.assertEqual(result["cont"]["sync_fixes"], 1)
        self.assertNotIn("fix-sync-2", labels(calls))
        self.assertNotIn("merge", labels(calls))

    def test_a_fix_that_starts_from_another_head_stops_before_review(self):
        other = "c" * 40
        result, calls = run(patch={"pr": {"checks": RED}, "fix-ci": {"start_head": other, "commit": FIX}})
        self.assertEqual(result["stage"], "checks-fix")
        self.assertNotIn("fix-ci-review", labels(calls))
        self.assertNotIn("merge", labels(calls))
        result, calls = run(replies={"sync-review-1": FINDING},
                            patch={"pr": {"checks": {"state": "behind", "head": SHA}},
                                   "sync-1": ABORTED, "sync-resolve-1": {"conflicted": True, "merge_commit": MERGE},
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
        replies = {"sync-review-1": FINDING,
                   "checks-2": {"state": "passed", "head": MERGE, "required": ["ci-tests"]}}
        replies.update(review or {})
        return run(replies=replies,
                   patch={"pr": {"checks": {"state": "behind", "head": SHA}},
                          "sync-1": ABORTED, "sync-resolve-1": {"conflicted": True, "merge_commit": MERGE},
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
        result, _ = run(replies={"sync-1": None}, patch={"pr": {"checks": {"state": "behind", "head": SHA}}})
        self.assertEqual(result["stage"], "sync")
        self.assertNotIn("checks_fixes", result["cont"])
        self.assertNotIn("sync_fixes", result["cont"])


class AllChecksTest(unittest.TestCase):
    """#756: the checks step waits for every check on head, required or not."""

    def test_checks_step_lists_every_check_and_can_answer_pending(self):
        _, calls = run(patch={"pr": {"checks": {"state": "pending", "head": SHA, "pending": ["e2e"]}}})
        checks = prompt(calls, "checks-2")
        for argv in ("gh pr checks 42 --repo owner/repo --json name,bucket,link",
                     "gh api repos/owner/repo/rules/branches/dev"):
            self.assertIn(argv, checks)
        schema = schema_of(calls, "checks-2")
        self.assertIn("pending", schema["properties"])
        self.assertIn("pending", schema["properties"]["state"]["enum"])

    def test_a_pending_non_required_check_is_waited_for_before_the_merge(self):  # AC1
        waiting = {"state": "passed", "head": SHA, "required": ["lint"], "passed": ["lint"], "pending": ["e2e"]}
        green = {"state": "passed", "head": SHA, "required": ["lint"], "passed": ["lint", "e2e"]}
        result, calls = run(replies={"checks-2": green}, patch={"pr": {"checks": waiting}})
        self.assertEqual(result["stage"], "done")
        names = labels(calls)
        self.assertEqual(names[names.index("pr"):],
                         ["pr", "checks-2", "merge", "hold", "close-out"])

    def test_a_pending_state_is_waited_for_and_never_synced(self):
        result, calls = run(patch={"pr": {"checks": {"state": "pending", "head": SHA, "pending": ["e2e"]}}})
        self.assertEqual(result["stage"], "done")
        names = labels(calls)
        self.assertNotIn("sync-1", names)
        self.assertLess(names.index("checks-2"), names.index("merge"))

    def test_checks_still_pending_after_three_waits_stop_unmerged(self):  # AC1
        waiting = {"state": "pending", "head": SHA, "pending": ["e2e"]}
        result, calls = run(replies={f"checks-{k}": waiting for k in (2, 3)}, patch={"pr": {"checks": waiting}})
        self.assertEqual((result["stage"], result["pending"]), ("checks-pending", ["e2e"]))
        self.assertIn("cont", result)
        names = labels(calls)
        self.assertNotIn("merge", names)
        self.assertNotIn("checks-4", names)
        self.assertEqual(names.count("land-unlock"), 1)

    def test_a_failing_non_required_check_stops_the_merge_named(self):  # AC2
        red = {"state": "passed", "head": SHA, "required": ["lint"], "passed": ["lint"], "failing": ["e2e"],
               "details": "e2e: 2 failed"}
        result, calls = run(replies={"checks-2": dict(red, head=FIX)},
                            patch={"pr": {"checks": red}, "fix-ci": {"start_head": SHA, "commit": FIX}})
        self.assertEqual((result["stage"], result["failing"]), ("checks", ["e2e"]))
        self.assertNotIn("merge", labels(calls))
        self.assertIn("e2e", prompt(calls, "fix-ci"))

    def test_an_explicit_failed_state_outranks_a_pending_list(self):  # AC2
        red = {"state": "failed", "head": SHA, "pending": ["slow"], "details": "e2e failed"}
        result, calls = run(replies={"checks-2": dict(red, head=FIX)},
                            patch={"pr": {"checks": red}, "fix-ci": {"start_head": SHA, "commit": FIX}})
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
                result, calls = run(patch={"pr": {"checks": {"state": "passed", "head": short, "required": ["ci"]}}})
                self.assertEqual(result["stage"], "done")
                self.assertIn(f"--match-head-commit {SHA}", prompt(calls, "merge"))

    def test_short_pr_head_is_accepted(self):
        result, calls = run(patch={"pr": {"head": SHA[:8]}})
        self.assertEqual(result["stage"], "done")
        self.assertIn("merge", labels(calls))

    def test_a_different_or_too_short_head_still_stops(self):
        for head in ("c" * 40, "c" * 8, SHA[:6], "", "zzzzzzzzzz"):
            with self.subTest(head=head):
                result, calls = run(patch={"pr": {"checks": {"state": "passed", "head": head, "required": ["ci"]}}})
                self.assertEqual(result["stage"], "head-moved")
                self.assertNotIn("merge", labels(calls))
                result, calls = run(patch={"pr": {"head": head}})
                self.assertEqual(result["stage"], "head-moved")
                self.assertFalse([n for n in labels(calls) if n.startswith("checks-")])

    def test_head_fields_require_a_full_sha_in_the_schema(self):
        _, calls = run(patch={"pr": {"checks": {"state": "behind", "head": SHA}}})
        for label, field in (("pr", "head"), ("checks-2", "head"), ("verify", "head"), ("sync-1", "merge_commit")):
            with self.subTest(label=label):
                self.assertEqual(schema_of(calls, label)["properties"][field]["pattern"], "^[0-9a-f]{40}$")
        with self.subTest(label="pr checks"):
            self.assertEqual(member(schema_of(calls, "pr"), "checks")["properties"]["head"]["pattern"], "^[0-9a-f]{40}$")

    def test_ready_cont_resumed_on_the_short_form_of_its_head_skips_review_and_verify(self):
        ready, _ = run(args=dict(ARGS, mode="ready"))
        result, calls = run(args=dict(ARGS, cont=ready["cont"]), patch={"setup": {"head": SHA[:9]}})
        self.assertEqual(result["stage"], "done")
        self.assertNotIn("final-1", labels(calls))
        self.assertNotIn("verify", labels(calls))

    def test_a_legacy_abbreviated_verify_cache_keeps_the_full_pr_sha(self):
        ready, _ = run(args=dict(ARGS, mode="ready"))
        cont = dict(ready["cont"], verified=dict(ready["cont"]["verified"], head=SHA[:9]))
        result, calls = run(args=dict(ARGS, cont=cont), patch={"setup": {"head": SHA},
                                                       "pr": {"checks": {"state": "passed", "head": SHA[:8]}}})
        self.assertEqual(result["stage"], "done")
        self.assertNotIn("verify", labels(calls))
        self.assertIn(f"--match-head-commit {SHA} ", prompt(calls, "merge") + " ")
        other = SHA[:9] + "0" * 31
        result, calls = run(args=dict(ARGS, cont=cont), patch={"setup": {"head": SHA},
                                                       "pr": {"checks": {"state": "passed", "head": other}}})
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


def waves(calls):
    return [name for name in labels(calls) if name.startswith("fix-wave")]


def narrow(*summaries, severity="important", **more):
    return {"verdict": "findings",
            "findings": [dict({"severity": severity, "file": "claim.py", "summary": s, "relation": "narrowing"}, **more)
                         for s in summaries]}


class ThirdFixWaveTest(unittest.TestCase):
    """#924: a third wave for narrowing, non-critical, non-growing findings; a fix-wave-review stop carries what it left open."""

    FIRST = FixWaveTest.FIRST
    AFTER_1 = narrow("race in release", "race in renew")
    AFTER_2 = narrow("race in expire", "race in adopt")
    CLASS = "Fix the class of defect: enumerate every path of the same kind"
    THREE = ["fix-wave", "fix-wave-review", "fix-wave-2", "fix-wave-review-2", "fix-wave-3", "fix-wave-review-3"]

    def replies(self, **more):
        return dict({"final-1": self.FIRST, "fix-wave-review": self.AFTER_1, "fix-wave-review-2": self.AFTER_2}, **more)

    def test_deliveries_that_clear_in_up_to_two_waves_keep_their_steps(self):
        for replies, expected in (({}, []),
                                  ({"final-1": self.FIRST}, self.THREE[:2]),
                                  ({"final-1": self.FIRST, "fix-wave-review": self.AFTER_1}, self.THREE[:4])):
            with self.subTest(expected=expected):
                result, calls = run(replies=replies)
                self.assertEqual((result["stage"], result["fix_waves"]), ("done", len(expected) // 2))
                self.assertEqual(waves(calls), expected)
                self.assertFalse([c for c in calls if c["label"].startswith("fix-wave") and self.CLASS in c["prompt"]])

    def test_a_third_wave_that_clears_lets_the_delivery_continue(self):
        result, calls = run(replies=self.replies())
        self.assertEqual((result["stage"], result["fix_waves"]), ("done", 3))
        self.assertEqual(waves(calls), self.THREE)
        self.assertEqual(labels(calls)[labels(calls).index("fix-wave-review-3") + 1], "verify")
        third = prompt(calls, "fix-wave-3")
        for needle in (self.CLASS, "close them all, not only the reported instance", "race in expire", "race in acquire",
                       "If a finding is wrong, explain with evidence in notes."):
            self.assertIn(needle, third)
        self.assertNotIn("race in release", third)
        for label in ("fix-wave", "fix-wave-2"):
            self.assertNotIn(self.CLASS, prompt(calls, label))
        by_label = {c["label"]: c for c in calls}
        self.assertEqual((by_label["fix-wave-3"]["agentType"], by_label["fix-wave-review-3"]["agentType"]),
                         ("implementer", "reviewer"))

    def test_the_third_rereview_is_scoped_like_the_second(self):
        _, calls = run(replies=self.replies(), patch={"fix-wave-2": {"start_head": "d" * 40, "commit": "e" * 40},
                                                      "fix-wave-3": {"start_head": "e" * 40, "commit": "f" * 40}})
        second, third = prompt(calls, "fix-wave-review-2"), prompt(calls, "fix-wave-review-3")
        self.assertIn("f" * 40, third)
        self.assertIn("race in expire", third)
        self.assertNotIn("race in release", third)
        # The same prompt, wave for wave: only the fix's range and the findings under re-review differ.
        blank = lambda text: re.sub(r"Findings: \[.*?\]\. Report", "Findings: []. Report", re.sub(r"\b[def]{40}\b", "SHA", text))
        self.assertEqual(blank(second), blank(third))

    def test_each_clause_of_the_admission_refuses_the_third_wave(self):
        mixed = narrow("race in expire")
        mixed["findings"].append({"severity": "important", "summary": "leak", "relation": "new"})
        unmarked = {"verdict": "findings", "findings": [{"severity": "important", "summary": "race in expire"}]}
        for name, after_2 in (("a finding that is not narrowing", mixed), ("a finding with no relation", unmarked),
                              ("a critical finding", narrow("race in expire", severity="critical")),
                              ("a finding with no severity", {"verdict": "findings", "findings": [
                                  {"file": "claim.py", "summary": "race in expire", "relation": "narrowing"}]}),
                              ("more findings than after wave 1", narrow("race a", "race b", "race c"))):
            with self.subTest(name):
                result, calls = run(replies=self.replies(**{"fix-wave-review-2": after_2}))
                self.assertEqual((result["stage"], result["fix_waves"]), ("fix-wave-review", 2))
                self.assertEqual(waves(calls), self.THREE[:4])
                self.assertEqual([f["summary"] for f in result["cont"]["fix_findings"]], [f["summary"] for f in after_2["findings"]])

    def test_a_minor_finding_after_wave_one_does_not_raise_the_allowed_count(self):
        after_1 = narrow("race in release")
        after_1["findings"].append({"severity": "minor", "summary": "naming", "relation": "narrowing"})
        result, calls = run(replies=self.replies(**{"fix-wave-review": after_1}))
        self.assertEqual((result["stage"], result["fix_waves"]), ("fix-wave-review", 2))
        self.assertNotIn("fix-wave-3", labels(calls))
        _, calls = run(replies=self.replies(**{"fix-wave-review": after_1, "fix-wave-review-2": narrow("race in expire")}))
        self.assertIn("fix-wave-3", labels(calls))

    def test_as_many_findings_as_after_wave_one_are_admitted(self):
        for after_2 in (narrow("race in expire"), self.AFTER_2):
            with self.subTest(count=len(after_2["findings"])):
                _, calls = run(replies=self.replies(**{"fix-wave-review-2": after_2}))
                self.assertIn("fix-wave-3", labels(calls))

    def test_minor_findings_do_not_count_against_the_third_wave(self):
        after_2 = narrow("race in expire", "race in adopt")
        after_2["findings"].append({"severity": "minor", "summary": "naming", "relation": "new"})
        _, calls = run(replies=self.replies(**{"fix-wave-review-2": after_2}))
        self.assertIn("fix-wave-3", labels(calls))

    def test_a_third_wave_that_leaves_findings_stops_and_carries_them(self):
        left = narrow("race in adopt", failing_input="two adopters")
        result, calls = run(replies=self.replies(**{"fix-wave-review-3": left}))
        self.assertEqual((result["stage"], result["fix_waves"]), ("fix-wave-review", 3))
        self.assertEqual(waves(calls), self.THREE)
        self.assertEqual(result["cont"]["fix_findings"],
                         [{"severity": "important", "file": "claim.py", "summary": "race in adopt", "failing_input": "two adopters"}])
        self.assertEqual(result["cont"]["fix_waves"], 3)
        self.assertIn("race in adopt", result["reason"])

    def test_no_fourth_wave(self):
        again = narrow("race in adopt")
        _, calls = run(replies=self.replies(**{"fix-wave-review-3": again, "fix-wave-review-4": again}))
        self.assertEqual(waves(calls), self.THREE)

    def test_a_failed_third_wave_stops(self):
        result, _ = run(replies=self.replies(**{"fix-wave-3": {"status": "blocked", "notes": "no"}}))
        self.assertEqual((result["stage"], result["fix_waves"]), ("fix-wave", 3))

    def test_a_stop_after_the_first_wave_carries_its_findings(self):
        new = {"verdict": "findings", "findings": [{"severity": "critical", "summary": "leak", "relation": "new"}]}
        result, _ = run(replies={"final-1": self.FIRST, "fix-wave-review": new})
        self.assertEqual(result["cont"]["fix_findings"], [{"severity": "critical", "summary": "leak", "failing_input": "x"}])

    def test_a_lost_rereview_and_a_clean_delivery_carry_nothing(self):
        lost, _ = run(replies={"final-1": self.FIRST, "fix-wave-review": None})
        self.assertEqual(lost["stage"], "fix-wave-review")
        self.assertNotIn("fix_findings", lost["cont"])
        later, _ = run(replies=self.replies(verify=None))
        self.assertEqual(later["stage"], "verify")
        self.assertNotIn("fix_findings", later["cont"])

    def test_the_carried_findings_are_bounded(self):
        many = narrow(*[f"race {i} " + "x" * 900 for i in range(14)], failing_input="y" * 900, source="codex")
        many["findings"][0]["file"] = "f" * 900
        out = run_out(replies={"final-1": self.FIRST, "fix-wave-review": self.AFTER_1, "fix-wave-review-2": many})
        result = out["result"]
        kept = result["cont"]["fix_findings"]
        self.assertEqual(len(kept), 10)
        for finding in kept:
            self.assertLessEqual(set(finding), {"severity", "file", "summary", "failing_input"})
            self.assertTrue(all(len(v) <= 300 for v in finding.values()), finding)
        self.assertLess(len(json.dumps(kept)), 10 * 1000)
        self.assertIn("4 of 14 open finding(s) not carried in cont", json.dumps(out))
        # A cont that came back larger (edited by hand, or from before the bound) is cut again on the way in.
        cont = dict(result["cont"], fix_findings=many["findings"] + [{"severity": "minor", "summary": "naming"}, "text", {"file": "a"}])
        again, _ = run(args=dict(ARGS, cont=cont), replies={"final-1": None})
        self.assertEqual(again["stage"], "final-review")
        self.assertEqual(again["cont"]["fix_findings"], kept)

    def stopped(self):
        left = narrow("race in adopt", failing_input="two adopters")
        result, _ = run(replies=self.replies(**{"fix-wave-review-3": left}))
        return result["cont"]

    def test_a_resume_feeds_the_carried_findings_to_the_first_wave(self):
        fresh = {"verdict": "findings", "findings": [{"severity": "important", "file": "lock.py", "summary": "stale lock"}]}
        result, calls = run(args=dict(ARGS, cont=self.stopped()), replies={"final-1": fresh})
        self.assertEqual((result["stage"], result["fix_waves"]), ("done", 4))
        self.assertEqual(waves(calls), self.THREE[:2])
        self.assertIn("final-1", labels(calls))
        wave = prompt(calls, "fix-wave")
        for needle in ("stale lock", "race in adopt", "two adopters",
                       "The last 1 were left open by an earlier run's fix waves and may repeat the ones before them: "
                       "check each against the current head, and explain one that no longer holds in notes; "
                       "when you commit nothing, return commit equal to start_head."):
            self.assertIn(needle, wave)
        self.assertLess(wave.index("stale lock"), wave.index("race in adopt"))
        rereview = prompt(calls, "fix-wave-review")
        for needle in ("race in adopt", "stale lock", "against the fix (git -C",
                       "The last 1 were left open by an earlier run and may repeat the ones before them: "
                       "check each against the head, not only the diff."):
            self.assertIn(needle, rereview)

    def test_a_first_run_names_no_carried_findings(self):
        _, calls = run(replies={"final-1": self.FIRST})
        for label in ("fix-wave", "fix-wave-review"):
            self.assertNotIn("earlier run", prompt(calls, label))

    def test_a_minor_carried_finding_is_dropped_when_the_cont_is_read(self):
        cont = dict(self.stopped(), fix_findings=[{"severity": "minor", "summary": "naming nit"},
                                                  {"severity": "important", "summary": "race in adopt"}])
        _, calls = run(args=dict(ARGS, cont=cont))
        wave = prompt(calls, "fix-wave")
        self.assertNotIn("naming nit", wave)
        self.assertIn("The last 1 were left open", wave)
        only_minor = dict(cont, fix_findings=[{"severity": "minor", "summary": "naming nit"}])
        _, calls = run(args=dict(ARGS, cont=only_minor))
        self.assertEqual(waves(calls), [])

    NOTHING = {"start_head": "d" * 40, "commit": "d" * 40, "notes": "already closed by 1234"}

    def test_carried_findings_already_closed_are_checked_against_the_head_and_the_delivery_continues(self):
        result, calls = run(args=dict(ARGS, cont=self.stopped()), patch={"fix-wave": self.NOTHING})
        self.assertEqual(result["stage"], "done")
        self.assertEqual(waves(calls), self.THREE[:2])
        rereview = prompt(calls, "fix-wave-review")
        for needle in ("against the current head of /r/.wt/w-issue-9-x (the fix wave committed nothing, so there is no diff to read). "
                       "Nothing changed since these were raised, so each finding stands unless the code at the head shows it does "
                       "not hold. The notes are the implementer's claims: check each against the code and never clear a finding on "
                       "the notes alone; notes: already closed by 1234. Findings: ",
                       "race in adopt"):
            self.assertIn(needle, rereview)
        self.assertNotIn("declared branch", rereview)
        # The head check covers every wave-1 finding, the fresh ones too: nothing was committed for any of them.
        fresh = {"verdict": "findings", "findings": [{"severity": "important", "file": "lock.py", "summary": "stale lock"}]}
        _, calls = run(args=dict(ARGS, cont=self.stopped()), replies={"final-1": fresh}, patch={"fix-wave": self.NOTHING})
        rereview = prompt(calls, "fix-wave-review")
        for needle in ("the fix wave committed nothing", "stale lock", "race in adopt"):
            self.assertIn(needle, rereview)

    def branch_resume(self, head):
        """A resume of a declared-branch delivery with a carried finding, whose first wave commits nothing on the issue branch."""
        new = {"verdict": "findings", "findings": [{"severity": "important", "summary": "leak on cand", "relation": "new"}]}
        at_e = {"start_head": TIP, "commit": TIP, "branch_heads": [{"name": "cand", "head": "e" * 40}]}
        stopped, _ = run(replies={"plan": bplan(), "final-1": self.FIRST, "fix-wave-review": new},
                         patch={"impl-1": {"commit": TIP}, "impl-2": {"commit": "d" * 40}, "fix-wave": at_e})
        self.assertEqual([f["summary"] for f in stopped["cont"]["fix_findings"]], ["leak on cand"])
        facts = [{"name": "cand", "head": "e" * 40, "current": "cand", "toplevel": "/r/.wt/cand", "common_dir": "/r/.git"}]
        wave = {"start_head": TIP, "commit": TIP, "branch_heads": [{"name": "cand", "head": head}]}
        result, calls = run(args=dict(ARGS, cont=stopped["cont"]),
                            patch={"setup": {"head": TIP, "branch_heads": facts}, "fix-wave": wave})
        self.assertEqual(result["stage"], "done")
        self.assertIn("leak on cand", prompt(calls, "fix-wave"))
        return prompt(calls, "fix-wave-review")

    def test_a_wave_that_commits_only_on_a_declared_branch_is_reviewed_over_that_range(self):
        rereview = self.branch_resume("f" * 40)
        self.assertIn(f"git -C /r/.wt/cand diff {'e' * 40}..{'f' * 40}", rereview)
        self.assertIn("check each against the head, not only the diff", rereview)
        self.assertNotIn("committed nothing", rereview)

    def test_the_head_check_names_the_declared_branch_worktrees(self):
        rereview = self.branch_resume("e" * 40)
        self.assertIn("against the current head of /r/.wt/w-issue-9-x and of each declared branch's worktree (cand in /r/.wt/cand) "
                      "(the fix wave committed nothing, so there is no diff to read).", rereview)
        self.assertNotIn("git -C /r/.wt/cand diff", rereview)
        self.assertNotIn("d" * 40, rereview)
        self.assertNotIn("not only the diff", rereview)

    def test_a_carried_finding_the_head_check_still_holds_stops_and_is_carried(self):
        cont = self.stopped()
        for held in (narrow("race in adopt"), narrow("race in adopt", relation="new")):
            with self.subTest(held=held):
                result, calls = run(args=dict(ARGS, cont=cont), replies={"fix-wave-review": held}, patch={"fix-wave": self.NOTHING})
                self.assertEqual(result["stage"], "fix-wave-review")
                self.assertEqual(waves(calls), self.THREE[:2])
                self.assertEqual([f["summary"] for f in result["cont"]["fix_findings"]], ["race in adopt"])
        lost, _ = run(args=dict(ARGS, cont=cont), replies={"fix-wave-review": None}, patch={"fix-wave": self.NOTHING})
        self.assertEqual(lost["cont"]["fix_findings"], cont["fix_findings"])

    def test_a_first_run_wave_that_commits_nothing_is_reviewed_as_before(self):
        _, calls = run(replies={"final-1": self.FIRST}, patch={"fix-wave": self.NOTHING})
        self.assertIn(f"against the fix (git -C /r/.wt/w-issue-9-x diff {'d' * 40}..{'d' * 40})", prompt(calls, "fix-wave-review"))

    def test_a_resume_runs_the_wave_when_the_fresh_review_raises_nothing(self):
        result, calls = run(args=dict(ARGS, cont=self.stopped()))
        self.assertEqual(result["stage"], "done")
        self.assertEqual(waves(calls), self.THREE[:2])
        self.assertIn("race in adopt", prompt(calls, "fix-wave"))

    def test_a_finding_the_fresh_review_raises_again_is_passed_once(self):
        fresh = {"verdict": "findings", "findings": [{"severity": "critical", "file": "claim.py", "summary": "Race  in ADOPT"}]}
        _, calls = run(args=dict(ARGS, cont=self.stopped()), replies={"final-1": fresh})
        wave = prompt(calls, "fix-wave")
        self.assertIn("Race  in ADOPT", wave)
        self.assertNotIn("race in adopt", wave)
        self.assertNotIn("left open by an earlier run", wave)

    def test_the_carried_findings_last_until_a_wave_takes_them(self):
        cont = self.stopped()
        for replies in ({"final-1": None}, {"fix-wave": None}):
            with self.subTest(replies=replies):
                result, _ = run(args=dict(ARGS, cont=cont), replies=replies)
                self.assertIn(result["stage"], ("final-review", "fix-wave"))
                self.assertEqual(result["cont"]["fix_findings"], cont["fix_findings"])
        # A wave that answered and failed has had them: the resume's fresh review decides.
        for reply in ({"status": "blocked", "notes": "no"}, {"status": "done", "start_head": "d" * 40, "notes": "nothing to do"}):
            with self.subTest(reply=reply):
                out = run_out(args=dict(ARGS, cont=cont), replies={"fix-wave": reply})
                self.assertEqual(out["result"]["stage"], "fix-wave")
                self.assertNotIn("fix_findings", out["result"]["cont"])
                self.assertIn("1 carried finding(s) dropped after a wave that answered and failed", json.dumps(out))
        taken, _ = run(args=dict(ARGS, cont=cont), replies={"verify": None})
        self.assertEqual(taken["stage"], "verify")
        self.assertNotIn("fix_findings", taken["cont"])
        resolved, _ = run(args=dict(ARGS, cont=cont), replies={"fix-wave-review": None})
        self.assertNotIn("fix_findings", resolved["cont"])

    def test_a_resumed_run_gets_its_own_three_waves(self):
        result, calls = run(args=dict(ARGS, cont=self.stopped()), replies=self.replies())
        self.assertEqual((result["stage"], result["fix_waves"]), ("done", 6))
        self.assertEqual(waves(calls), self.THREE)


class FixWavesConvergeTest(unittest.TestCase):
    """#940: a fix-wave-review stop at the wave bound, with a finding left in a file the carried findings named, is marked diverging."""

    VERDICT = "the fix waves do not converge on claim.py after 4 waves; an owner decision on the design is needed"

    @staticmethod
    def left(file="claim.py", summary="race in steal", **more):
        finding = dict({"severity": "important", "summary": summary, "relation": "new"}, **more)
        if file is not None:
            finding["file"] = file
        return {"verdict": "findings", "findings": [finding]}

    def stopped(self, **changes):
        """The cont of a first run stopped after three waves, one finding left open in claim.py."""
        result, _ = run(replies=ThirdFixWaveTest().replies(**{"fix-wave-review-3": narrow("race in adopt")}))
        self.assertEqual((result["stage"], result["cont"]["fix_waves"]), ("fix-wave-review", 3))
        self.assertNotIn("diverging", result)
        return dict(result["cont"], **changes)

    def test_a_resume_that_leaves_the_same_file_open_at_the_bound_is_marked(self):
        result, calls = run(args=dict(ARGS, cont=self.stopped()), replies={"fix-wave-review": self.left()})
        self.assertEqual((result["stage"], result["fix_waves"]), ("fix-wave-review", 4))
        self.assertEqual(result["diverging"], {"file": "claim.py", "waves": 4})
        self.assertEqual(result["reason"], f"fix-wave-review: {self.VERDICT}; 1 finding(s): race in steal")
        self.assertEqual(result["cont"]["fix_waves"], 4)
        self.assertEqual(result["cont"]["fix_findings"], [{"severity": "important", "file": "claim.py", "summary": "race in steal"}])
        self.assertNotIn("diverging", result["cont"])
        self.assertEqual(waves(calls), ThirdFixWaveTest.THREE[:2])

    def test_the_waves_counted_are_those_of_every_run(self):
        replies = {"fix-wave-review": narrow("race in steal"), "fix-wave-review-2": narrow("race in steal", severity="critical")}
        result, _ = run(args=dict(ARGS, cont=self.stopped()), replies=replies)
        self.assertEqual(result["diverging"], {"file": "claim.py", "waves": 5})
        self.assertIn("after 5 waves", result["reason"])

    def test_below_the_bound_the_stop_is_an_ordinary_one(self):
        for spent, marked in ((1, False), (2, False), (3, True), (7, True)):
            with self.subTest(spent=spent):
                result, _ = run(args=dict(ARGS, cont=self.stopped(fix_waves=spent)), replies={"fix-wave-review": self.left()})
                self.assertEqual((result["stage"], result["fix_waves"]), ("fix-wave-review", spent + 1))
                self.assertEqual("diverging" in result, marked)
                self.assertEqual("do not converge" in result["reason"], marked)
                self.assertEqual([f["summary"] for f in result["cont"]["fix_findings"]], ["race in steal"])

    def test_findings_left_in_other_files_stop_as_before(self):
        mixed = self.left("lock.py")
        mixed["findings"].append({"severity": "minor", "file": "claim.py", "summary": "naming", "relation": "new"})
        for name, rv in (("another file", self.left("lock.py")), ("no file", self.left(None)), ("only a minor one in the file", mixed)):
            with self.subTest(name):
                result, _ = run(args=dict(ARGS, cont=self.stopped()), replies={"fix-wave-review": rv})
                self.assertEqual((result["stage"], result["fix_waves"]), ("fix-wave-review", 4))
                self.assertNotIn("diverging", result)
                self.assertEqual(result["reason"], "fix-wave-review: 1 finding(s): race in steal")
                self.assertEqual([f["summary"] for f in result["cont"]["fix_findings"]], ["race in steal"])

    def test_a_position_or_a_leading_dot_slash_names_the_same_file(self):
        path = "src/claim.py"
        root = "/r/.wt/w-issue-9-x"
        forms = (path, f"{path}:328", f"{path}:328-337", f"{path}:328:12", f"./{path}", f" ./{path}:9 ",
                 f"{root}/{path}", f"{root}/{path}:328-337", f"{path}#L328", f"{path}#L328-L337", f"{root}/./{path}#L3-9")
        for carried_as in forms:
            for left_as in forms:
                with self.subTest(carried=carried_as, left=left_as):
                    cont = self.stopped(fix_findings=[{"severity": "important", "file": carried_as, "summary": "race in adopt"}])
                    result, _ = run(args=dict(ARGS, cont=cont), replies={"fix-wave-review": self.left(left_as)})
                    self.assertEqual(result["diverging"], {"file": path, "waves": 4})
                    self.assertIn(f"do not converge on {path} after 4 waves;", result["reason"])
                    # The cont keeps the finding as the reviewer wrote it.
                    self.assertEqual(result["cont"]["fix_findings"][0]["file"], left_as)

    def test_other_differences_between_paths_are_different_files(self):
        cont = self.stopped(fix_findings=[{"severity": "important", "file": "src/claim.py:328-337", "summary": "race in adopt"}])
        for other in ("src/Claim.py", "claim.py", "src/claim.py.bak", "src/claim.pyc:3", "src/claim.py:fn", "../src/claim.py",
                      "/elsewhere/src/claim.py", "/r/.wt/w-issue-9-xy/src/claim.py", "src/claim.py#fn"):
            with self.subTest(other=other):
                result, _ = run(args=dict(ARGS, cont=cont), replies={"fix-wave-review": self.left(other)})
                self.assertEqual(result["stage"], "fix-wave-review")
                self.assertNotIn("diverging", result)

    def test_one_shared_file_among_several_is_named(self):
        rv = self.left("lock.py", "stale lock")
        rv["findings"].append({"severity": "critical", "file": "claim.py", "summary": "race in steal", "relation": "new"})
        result, _ = run(args=dict(ARGS, cont=self.stopped()), replies={"fix-wave-review": rv})
        self.assertEqual(result["diverging"], {"file": "claim.py", "waves": 4})

    def test_a_run_that_carried_no_findings_in_is_never_marked(self):
        first, calls = run(replies=ThirdFixWaveTest().replies(**{"fix-wave-review-3": narrow("race in adopt")}))
        self.assertEqual((first["stage"], first["fix_waves"]), ("fix-wave-review", 3))
        self.assertNotIn("diverging", first)
        # Waves at the bound, but nothing carried in (the earlier run stopped elsewhere): no earlier finding named the file.
        cont = {k: v for k, v in self.stopped(fix_waves=6).items() if k != "fix_findings"}
        result, _ = run(args=dict(ARGS, cont=cont), replies={"final-1": self.left(), "fix-wave-review": self.left()})
        self.assertEqual((result["stage"], result["fix_waves"]), ("fix-wave-review", 7))
        self.assertNotIn("diverging", result)

    def test_a_delivery_that_converges_and_a_lost_rereview_are_unchanged(self):
        done, _ = run(args=dict(ARGS, cont=self.stopped()))
        self.assertEqual((done["stage"], done["fix_waves"]), ("done", 4))
        self.assertNotIn("diverging", done)
        lost, _ = run(args=dict(ARGS, cont=self.stopped()), replies={"fix-wave-review": None})
        self.assertEqual(lost["stage"], "fix-wave-review")
        self.assertNotIn("diverging", lost)
        failed, _ = run(args=dict(ARGS, cont=self.stopped()), replies={"fix-wave": {"status": "blocked", "notes": "no"}})
        self.assertEqual(failed["stage"], "fix-wave")
        self.assertNotIn("diverging", failed)

    def test_the_reason_is_capped_and_keeps_the_verdict(self):
        long = "dir/" * 200 + "claim.py"
        cont = self.stopped(fix_findings=[{"severity": "important", "file": long, "summary": "race in adopt"}])
        result, _ = run(args=dict(ARGS, cont=cont), replies={"fix-wave-review": self.left(long, "s" * 900)})
        self.assertEqual(result["diverging"]["waves"], 4)
        self.assertLessEqual(len(result["diverging"]["file"]), 300)
        self.assertLessEqual(len(result["reason"]), 300)
        self.assertNotIn("\n", result["reason"])
        self.assertIn("after 4 waves; an owner decision on the design is needed", result["reason"])


class FixDiffFindingTest(unittest.TestCase):
    """#950: a finding not marked narrowing, in a file the fix wave's commits changed, is admitted to the next wave like a narrowing one."""

    FIRST = FixWaveTest.FIRST
    CHANGED = {"changed_files": ["src/claim.py", "tests/test_claim.py"]}
    NAME_ONLY = "git -C /r/.wt/w-issue-9-x diff --no-renames --name-only "

    @staticmethod
    def found(*findings, changed=CHANGED["changed_files"]):
        """A re-review reply: its findings, each (file, relation) or a whole finding, and the files it read as changed."""
        rows = []
        for i, f in enumerate(findings):
            if isinstance(f, tuple):
                f = {k: v for k, v in (("file", f[0]), ("relation", f[1])) if v is not None}
            rows.append(dict({"severity": "important", "summary": f"leak {i}"}, **f))
        return dict({"verdict": "findings", "findings": rows}, **({} if changed is None else {"changed_files": changed}))

    def first_wave(self, rv, wave=CHANGED):
        return run(replies={"final-1": self.FIRST, "fix-wave-review": rv}, patch={"fix-wave": wave or {}})

    def test_a_new_finding_in_a_file_the_fix_changed_gets_the_second_wave(self):
        narrowing = {"file": "lock.py", "relation": "narrowing"}
        for name, rv in (("new", self.found(("src/claim.py", "new"))),
                         ("no relation", self.found(("src/claim.py", None))),
                         ("a position and an absolute path", self.found(("/r/.wt/w-issue-9-x/./src/claim.py:12-14", "new"))),
                         ("the test file", self.found(("tests/test_claim.py#L3", "new"))),
                         ("beside a narrowing one elsewhere", self.found(narrowing, ("src/claim.py", "new"))),
                         ("listed with a dot slash", self.found(("src/claim.py", "new"), changed=[" ./src/claim.py "]))):
            with self.subTest(name):
                out = run_out(replies={"final-1": self.FIRST, "fix-wave-review": rv}, patch={"fix-wave": self.CHANGED})
                result, calls = out["result"], out["calls"]
                self.assertEqual((result["stage"], result["fix_waves"]), ("done", 2))
                self.assertEqual(waves(calls), ThirdFixWaveTest.THREE[:4])
                second = prompt(calls, "fix-wave-2")
                self.assertIn("leak ", second)
                self.assertIn("They follow the fix of these first-round findings (any not marked narrowing is a defect in a file "
                              "the previous fix wave changed): ", second)
                self.assertNotIn("They narrow", second)
                self.assertEqual(len([line for line in out["logs"] if "are in files fix wave 1 changed; they get the next wave" in line]), 1)

    def test_a_new_finding_outside_the_fix_diff_or_with_no_file_stops(self):
        rows = (("another file", self.found(("src/lock.py", "new")), self.CHANGED),
                ("no file", self.found((None, "new")), self.CHANGED),
                ("no file and no relation", self.found((None, None)), self.CHANGED),
                ("an empty file", self.found(("  ", "new")), self.CHANGED),
                ("one of two outside", self.found(("src/claim.py", "new"), ("src/lock.py", "new")), self.CHANGED),
                ("another case", self.found(("src/Claim.py", "new")), self.CHANGED),
                ("a file only the reviewer lists", self.found(("src/claim.py", "new")), {"changed_files": ["src/lock.py"]}),
                ("a file only the implementer lists", self.found(("src/claim.py", "new"), changed=["src/lock.py"]), self.CHANGED),
                ("no list from the implementer", self.found(("src/claim.py", "new")), None),
                ("no list from the reviewer", self.found(("src/claim.py", "new"), changed=None), self.CHANGED),
                ("lists that are not lists", self.found(("src/claim.py", "new"), changed="src/claim.py"), {"changed_files": "src/claim.py"}),
                ("empty lists", self.found(("src/claim.py", "new"), changed=[]), {"changed_files": []}))
        for name, rv, wave in rows:
            with self.subTest(name):
                result, calls = self.first_wave(rv, wave)
                self.assertEqual((result["stage"], result["fix_waves"]), ("fix-wave-review", 1))
                self.assertEqual(waves(calls), ThirdFixWaveTest.THREE[:2])
                self.assertEqual([f["summary"] for f in result["cont"]["fix_findings"]], [f["summary"] for f in rv["findings"]])
                self.assertNotIn("diverging", result)

    def third(self, after_2, wave_2=CHANGED, **more):
        replies = dict({"final-1": self.FIRST, "fix-wave-review": ThirdFixWaveTest.AFTER_1, "fix-wave-review-2": after_2}, **more)
        return run(replies=replies, patch={"fix-wave": {"changed_files": ["src/first.py"]}, "fix-wave-2": wave_2,
                                           "fix-wave-3": {"changed_files": ["src/claim.py"]}})

    def test_a_new_finding_in_the_second_fix_diff_gets_the_third_wave_under_the_other_clauses(self):
        for name, after_2 in (("one", self.found(("src/claim.py", "new"))),
                              ("as many as after wave 1", self.found(("src/claim.py", "new"), {"file": "x.py", "relation": "narrowing"}))):
            with self.subTest(name):
                result, calls = self.third(after_2)
                self.assertEqual((result["stage"], result["fix_waves"]), ("done", 3))
                self.assertEqual(waves(calls), ThirdFixWaveTest.THREE)
                self.assertIn(ThirdFixWaveTest.CLASS, prompt(calls, "fix-wave-3"))
                self.assertIn("They follow the fix of these first-round findings", prompt(calls, "fix-wave-3"))
                # Wave 2 took narrowing findings only, so its prompt is the one it always had.
                self.assertIn("They narrow these first-round findings: ", prompt(calls, "fix-wave-2"))

    def test_each_other_clause_still_refuses_the_third_wave(self):
        in_diff = ("src/claim.py", "new")
        rows = (("a critical finding", self.found({"file": "src/claim.py", "relation": "new", "severity": "critical"}), self.CHANGED),
                ("no severity", {"verdict": "findings", "changed_files": ["src/claim.py"],
                                 "findings": [{"file": "src/claim.py", "summary": "leak", "relation": "new"}]}, self.CHANGED),
                ("more findings than after wave 1", self.found(in_diff, in_diff, in_diff), self.CHANGED),
                ("a file only the first wave changed", self.found(("src/first.py", "new"), changed=["src/first.py"]), self.CHANGED),
                ("a file outside the diff", self.found(("src/lock.py", "new")), self.CHANGED),
                ("no file", self.found((None, "new")), self.CHANGED))
        for name, after_2, wave_2 in rows:
            with self.subTest(name):
                result, calls = self.third(after_2, wave_2)
                self.assertEqual((result["stage"], result["fix_waves"]), ("fix-wave-review", 2))
                self.assertEqual(waves(calls), ThirdFixWaveTest.THREE[:4])

    def test_no_fourth_wave_for_a_finding_in_the_third_fix_diff(self):
        again = self.found(("src/claim.py", "new"), changed=["src/claim.py"])
        for after_2 in (self.found(("src/claim.py", "new")), ThirdFixWaveTest.AFTER_2):
            with self.subTest(after_2=after_2):
                result, calls = self.third(after_2, **{"fix-wave-review-3": again, "fix-wave-review-4": again})
                self.assertEqual((result["stage"], result["fix_waves"]), ("fix-wave-review", 3))
                self.assertEqual(waves(calls), ThirdFixWaveTest.THREE)
                self.assertEqual([f["summary"] for f in result["cont"]["fix_findings"]], ["leak 0"])

    def test_an_idle_wave_admits_nothing(self):
        cont = ThirdFixWaveTest().stopped()
        idle = dict(ThirdFixWaveTest.NOTHING, **self.CHANGED)
        result, calls = run(args=dict(ARGS, cont=cont), replies={"fix-wave-review": self.found(("src/claim.py", "new"))},
                            patch={"fix-wave": idle})
        self.assertEqual(result["stage"], "fix-wave-review")
        self.assertEqual(waves(calls), ThirdFixWaveTest.THREE[:2])
        self.assertNotIn("--name-only", prompt(calls, "fix-wave-review"))

    def test_the_not_converging_marker_is_decided_at_the_stop_as_before(self):
        cont = FixWavesConvergeTest().stopped()
        # Without the lists the resume stops marked, as #940 has it.
        left = FixWavesConvergeTest.left()
        result, _ = run(args=dict(ARGS, cont=cont), replies={"fix-wave-review": left}, patch={"fix-wave": {"changed_files": ["claim.py"]}})
        self.assertEqual(result["diverging"], {"file": "claim.py", "waves": 4})
        # In the fix diff, the finding gets the next wave; the stop that follows it is marked with the waves then spent.
        in_diff = dict(left, changed_files=["claim.py"])
        still = FixWavesConvergeTest.left(severity="critical")
        result, calls = run(args=dict(ARGS, cont=cont), replies={"fix-wave-review": in_diff, "fix-wave-review-2": still},
                            patch={"fix-wave": {"changed_files": ["claim.py"]}})
        self.assertEqual(waves(calls), ThirdFixWaveTest.THREE[:4])
        self.assertEqual((result["stage"], result["fix_waves"]), ("fix-wave-review", 5))
        self.assertEqual(result["diverging"], {"file": "claim.py", "waves": 5})
        cleared, _ = run(args=dict(ARGS, cont=cont), replies={"fix-wave-review": in_diff}, patch={"fix-wave": {"changed_files": ["claim.py"]}})
        self.assertEqual((cleared["stage"], cleared["fix_waves"]), ("done", 5))
        self.assertNotIn("diverging", cleared)

    def test_deliveries_without_such_a_finding_do_not_read_the_lists(self):
        """Narrowing-only and clean deliveries run the same calls to the same result, whatever the lists say."""
        third = ThirdFixWaveTest().replies()
        scenarios = ({}, {"final-1": self.FIRST}, {"final-1": self.FIRST, "fix-wave-review": ThirdFixWaveTest.AFTER_1}, third,
                     dict(third, **{"fix-wave-review-3": narrow("race in adopt")}),
                     dict(third, **{"fix-wave-review-2": narrow("race in expire", severity="critical")}))
        lists = {label: self.CHANGED for label in ("fix-wave", "fix-wave-2", "fix-wave-3")}
        for replies in scenarios:
            with self.subTest(replies=sorted(replies)):
                plain = run_out(replies=replies)
                listed = run_out(replies={k: dict(v, **self.CHANGED) if "review" in k else v for k, v in replies.items()}, patch=lists)
                # A stop shows the re-review's reply as it came, its list included; nothing else differs.
                (listed["result"].get("rv") or {}).pop("changed_files", None)
                self.assertEqual(listed, plain)
                self.assertFalse([line for line in plain["logs"] if "they get the next wave" in line])
                for call in plain["calls"]:
                    if call["label"].startswith("fix-wave"):
                        self.assertNotIn("follow the fix of", call["prompt"])

    def test_both_steps_are_asked_for_the_changed_files_of_the_range_the_program_holds(self):
        _, calls = run(replies=ThirdFixWaveTest().replies(), patch={"fix-wave-2": {"start_head": "d" * 40, "commit": "e" * 40}})
        for label in ("fix-wave", "fix-wave-2", "fix-wave-3"):
            self.assertIn(f" Also return changed_files: the output lines of {self.NAME_ONLY}<start_head>..<commit>, run alone after "
                          "your last commit.", prompt(calls, label))
            self.assertEqual(schema_of(calls, label)["properties"]["changed_files"], {"type": "array", "items": {"type": "string"}})
            self.assertNotIn("changed_files", schema_of(calls, label)["required"])
        for label, span in (("fix-wave-review", "b0..c0ffee"), ("fix-wave-review-2", f"{'d' * 40}..{'e' * 40}")):
            self.assertIn(f" Unsure is new. Also return changed_files: the output lines of {self.NAME_ONLY}{span}, run alone.",
                          prompt(calls, label))
            self.assertEqual(schema_of(calls, label)["properties"]["changed_files"], {"type": "array", "items": {"type": "string"}})
            self.assertNotIn("changed_files", schema_of(calls, label)["required"])
        # No other implementer or reviewer step is asked.
        asked = {c["label"] for c in calls if "changed_files" in c["prompt"] or "changed_files" in json.dumps(c["schema"])}
        self.assertEqual(asked, set(ThirdFixWaveTest.THREE))


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
        for label in ("pr", "merge", "close-out"):
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
        self.assertEqual(labels(calls), ["setup", "pr", "merge", "hold", "close-out"])

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
                self.assertEqual(labels(calls), ["setup", "verify", "pr", "merge", "hold", "close-out"])

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
        stopped, _ = run(replies=replies,
                         patch=dict({"pr": {"checks": {"state": "behind", "head": SHA}}, "impl-1": {"commit": TIP},
                                     "sync-1": ABORTED, "sync-resolve-1": {"conflicted": True, "merge_commit": MERGE}}, **patch))
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
        stopped = self.sync_stop({"checks-2": {"lock": {"verdict": "already_held", "lock_sha": MERGE}}}, {})
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
BAD = {"verdict": "findings", "findings": [{"severity": "important", "summary": "bug", "failing_input": "x"}]}


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

    # #935: a criterion restating the declared verification had no evidence before verify and stopped the delivery.
    UNGRADED = {"verdict": "pass", "findings": [], "acceptance": [{"id": "AC1", "met": False, "evidence": ""}]}
    OLD_FIX = ("Fix these review findings in the worktree, with a regression test for each real defect, then commit: %s. "
               "If a finding is wrong, say so in notes with evidence instead of changing code. Run only the tests covering the files you changed")
    FIX_FINDINGS = re.compile(r"then commit: (\[.*?\])\. If a finding is wrong")

    def test_the_implementer_keeps_the_declared_verification_out_of_the_criteria(self):
        _, calls = run(args=DIRECT)
        self.assertIn("Do not write the declared verification commands as an acceptance criterion: the verify step gates on them.",
                      prompt(calls, "direct-impl"))

    def test_only_ungraded_criteria_ask_the_fix_round_for_their_evidence(self):
        result, calls = run(args=DIRECT, replies={"direct-review": self.UNGRADED})
        self.assertEqual(result["stage"], "done")
        fix = prompt(calls, "direct-fix")
        for needle in ("Acceptance criterion AC1", "run the command it names", "its exit status and its last lines",
                       "The focused-tests-only rule does not apply to a command a criterion names"):
            self.assertIn(needle, fix)
        self.assertNotIn("Run only the tests covering the files you changed", fix)
        self.assertNotIn("Fix these review findings", fix)
        rereview = prompt(calls, "direct-rereview")
        self.assertIn("the implementer's notes: ", rereview)
        self.assertIn("the notes carry the evidence produced for each", rereview)
        names = labels(calls)
        self.assertLess(names.index("direct-rereview"), names.index("verify"))

    def test_a_real_finding_beside_an_ungraded_criterion_keeps_the_fix_prompt(self):
        codex = {"available": True, "verdict": "findings", "findings": [{"severity": "important", "summary": "edge"}]}
        _, real = run(args=DIRECT, replies={"direct-review": BAD})
        plain = prompt(real, "direct-fix")
        for replies in ({"direct-review": dict(BAD, acceptance=self.UNGRADED["acceptance"])},
                        {"direct-review": self.UNGRADED, "direct-codex": codex}):
            with self.subTest(replies=sorted(replies)):
                _, calls = run(args=DIRECT, replies=replies)
                fix = prompt(calls, "direct-fix")
                found = self.FIX_FINDINGS.search(fix).group(1)
                self.assertIn("Acceptance criterion AC1", found)
                self.assertEqual(len(json.loads(found)), 2)
                self.assertIn(self.OLD_FIX % found, fix)
                self.assertEqual(fix, plain.replace(self.FIX_FINDINGS.search(plain).group(1), found))
                self.assertNotIn("the notes carry the evidence", prompt(calls, "direct-rereview"))

    def test_a_criterion_still_unmet_after_the_evidence_round_stops_before_verify(self):
        result, calls = run(args=DIRECT, replies={"direct-review": self.UNGRADED, "direct-rereview": BAD})
        self.assertEqual(result["stage"], "direct-review")
        self.assertEqual(labels(calls).count("direct-fix"), 1)
        self.assertNotIn("verify", labels(calls))

    def test_a_clean_direct_delivery_keeps_its_step_sequence(self):
        _, calls = run(args=DIRECT)
        names = labels(calls)
        self.assertNotIn("direct-fix", names)
        self.assertNotIn("direct-rereview", names)
        start = names.index("direct-impl")
        self.assertEqual(names[start:start + 2], ["direct-impl", "renew-final-review"])
        self.assertEqual(set(names[start + 2:start + 4]), {"direct-codex", "direct-review"})
        self.assertEqual(names[start + 4], "verify")

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
        self.assertEqual(labels(calls), ["setup", "pr", "merge", "hold", "close-out"])

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


class FixCommitScopeTest(unittest.TestCase):
    """A fix agent stages by path only what its fix changed: one committed a lock file a tool had generated."""

    SCOPE = ("Before committing, read git status in the worktree you commit in and stage by path only the files the fix "
             "itself changed or created; never run git add -A, git commit -a or git add on a directory (the dot included); a lock file, "
             "a generated file or an untracked file the fix did not need is left unstaged and named in notes.")
    CRITICAL = {"verdict": "findings", "findings": [{"severity": "critical", "summary": "bug", "failing_input": "x"}]}
    FAIL = {"head": SHA, "clean": True, "results": [{"id": "build", "status": "fail", "summary": "boom"}]}

    def test_every_fix_prompt_carries_the_commit_scope(self):
        scenarios = (
            (("fix-1-1",), {"replies": {"review-1": self.CRITICAL}}),
            (("fix-wave", "fix-wave-2"), {"replies": {"final-1": FixWaveTest.FIRST, "fix-wave-review": FixWaveTest.narrowing()}}),
            (("direct-fix",), {"args": DIRECT, "replies": {"direct-review": BAD}}),
            (("verify-fix-1",), {"replies": {"verify": self.FAIL}}),
            (("fix-ci",), {"replies": {"checks-2": {"state": "passed", "head": SHA, "required": ["ci-tests"]}},
                           "patch": {"pr": {"checks": RED}, "fix-ci": ShipFixWaveTest.RERAN}}),
            (("fix-sync-1",), {"replies": {"sync-review-1": FINDING},
                               "patch": {"pr": {"checks": {"state": "behind", "head": SHA}},
                                         "sync-1": ABORTED, "sync-resolve-1": {"conflicted": True, "merge_commit": MERGE, "resolved_files": ["a.py"]},
                                         "fix-sync-1": {"start_head": MERGE, "commit": FIX}}}),
        )
        for wanted, scenario in scenarios:
            _, calls = run(**scenario)
            for label in wanted:
                with self.subTest(label=label):
                    self.assertEqual(prompt(calls, label).count(self.SCOPE), 1)

    def test_no_other_prompt_carries_it(self):
        _, calls = run()
        self.assertEqual([c["label"] for c in calls if self.SCOPE in c["prompt"]], [])


class IndirectMergeHoldTest(unittest.TestCase):
    """A PR merged through another PR's merge is MERGED with a null mergeCommit: the hold derives the commit."""

    INDIRECT = (" When that mergeCommit is null, read gh pr view 42 --repo owner/repo --json state: only when it is MERGED "
                "(the PR was merged indirectly: its head reached dev through another PR's merge), confirm "
                "git -C /r merge-base --is-ancestor <headRefOid> origin/dev succeeds, then run "
                "git -C /r rev-list --first-parent <headRefOid>..origin/dev (the first-parent line of origin/dev, newest "
                "first) and git -C /r rev-list --ancestry-path <headRefOid>..origin/dev (the commits that contain the head): "
                "the merge commit is the last commit of the first list that is also in the second (the first commit on the "
                "first-parent line that contains the head); when the first list is empty, the tip of origin/dev is "
                "the head itself and the merge commit is <headRefOid>. When the state is not MERGED or the head is not an "
                "ancestor, return merge_commit_local false and stop here.")

    def test_a_hold_without_a_merge_commit_derives_it_from_the_head(self):
        cont = {"setup": {"holder": HOLDER, "branch": "issue-9-x", "worktree": "/r/.wt/w-issue-9-x",
                          "worktree_path": "/r/.wt/w-issue-9-x"},
                "lane": "standard", "plan": {"acceptance": PLAN["acceptance"]}, "pr": 42}
        result, calls = run(args=dict(ARGS, cont=cont), patch={"setup": {"merged_heads": [{"number": 42, "commits": []}]}})
        self.assertEqual(result["stage"], "done")
        hold = prompt(calls, "hold")
        self.assertIn("Merge commit: read from gh pr view 42 --repo owner/repo --json mergeCommit,headRefOid (and read "
                      f"headRefOid, the PR head).{self.INDIRECT} Confirm git -C /r cat-file -e <merge commit>^{{commit}} "
                      "succeeds and return the result as merge_commit_local; if it fails, stop here.", hold)

    def test_a_hold_given_the_merge_commit_is_unchanged(self):
        result, calls = run()
        self.assertEqual(result["stage"], "done")
        hold = prompt(calls, "hold")
        merge_commit = result["merge_commit"]
        self.assertIn(f"1. Run git -C /r fetch origin. Merge commit: {merge_commit}. Confirm git -C /r cat-file -e "
                      "<merge commit>^{commit} succeeds and return the result as merge_commit_local; if it fails, stop here.",
                      hold)
        for absent in ("mergeCommit is null", "merge-base --is-ancestor", "--ancestry-path", "--first-parent", "--json state"):
            self.assertNotIn(absent, hold)


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
        # #941: the resolve scope and the probe before the land lock are one text in both programs.
        self.assertEqual(line(mine, "RESOLVE_SCOPE"), line(batch, "RESOLVE_SCOPE"))

        def upto(text, name, end):
            start = text.index(f"const {name} = ")
            return text[start:text.index(end, start)]

        self.assertEqual(upto(mine, "PROBE", "\nlet PR = null"), upto(batch, "PROBE", "\n// A folded reply"))
        # The fix-commit scope is one sentence in both programs: deliver-batch's land-fix step commits too.
        self.assertEqual(line(mine, "COMMIT_SCOPE"), line(batch, "COMMIT_SCOPE"))
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
        for arg in ("session_id", "batch_id", "mode?", "lane?", "review_sizing?", "clerk_model?", "amend?"):
            self.assertIn(arg, meta)


BR = {"name": "cand", "worktree": "/r/.wt/cand", "base": "origin/dev", "head": "b" * 40,
      "current": "cand", "toplevel": "/r/.wt/cand", "common_dir": "/r/.git", "clean": True}
BR_PUSH = "git -C /r/.wt/cand push origin cand"
NO_FORCE = "Never push with --force, --force-with-lease or a +refspec, and never push dev or main."
TASK_FINDING = {"verdict": "findings", "findings": [{"severity": "important", "summary": "bug on the candidate", "failing_input": "x"}]}
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
                              "verify", "pr", "merge", "hold",
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
        one, two, three = BR["head"], "2" * 40, "3" * 40
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
        self.assertIn(f"git -C /r/.wt/w-issue-9-x diff {SHA}..c0ffee", prompt(calls, "review-1"))
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
                result, calls = run(replies={"plan": reply, "plan-branch-revise": reply})
                self.assertEqual((result["stage"], result["step"]), ("plan", "plan-branch-revise"))
                self.assertTrue(result["branch_problems"])
                self.assertIsNone(result["cont"]["plan"])
                self.assertEqual(labels(calls).count("plan-branch-revise"), 1)
                self.assertNotIn("plan-review", labels(calls))
                self.assertNotIn("impl-1", labels(calls))
        ok, _ = run(replies={"plan": bplan([dict(BR), at("/r/.wt/cand2", name="cand2", current="cand2")])})
        self.assertEqual(ok["stage"], "done")
        dev = bplan([dict(BR, name="dev", current="dev")], task_branch="dev")
        result, calls = run(replies={"plan-review": TASK_FINDING, "plan-revise": dev, "plan-branch-revise": dev})
        self.assertEqual((result["stage"], result["step"]), ("plan", "plan-branch-revise"))
        self.assertTrue(result["branch_problems"])
        cont = {"setup": {"ok": True, "worktree": "/r/.wt/w-issue-9-x", "branch": "issue-9-x", "plan_dir": "/g"},
                "plan": bplan([dict(BR, name="dev", current="dev")], task_branch="dev"), "plan_reviewed": True, "done": []}
        facts = [{"name": "dev", "head": "b" * 40, "current": "dev", "toplevel": "/r/.wt/cand", "common_dir": "/r/.git"}]
        result, calls = run(args=dict(ARGS, cont=cont), patch={"setup": {"branch_heads": facts}})
        self.assertEqual((result["stage"], result["step"]), ("plan", "resume"))
        self.assertTrue(result["branch_problems"])
        self.assertNotIn("impl-1", labels(calls))

    def test_a_plan_refused_for_its_branches_is_revised_once_in_place(self):
        """#869: a branch fault costs one planner revise of the kept plan, not the plan."""
        bad = bplan(task_branch="other")
        fixed, calls = run(replies={"plan": bad, "plan-branch-revise": bplan()})
        self.assertEqual(fixed["stage"], "done")
        self.assertEqual((labels(calls).count("plan"), labels(calls).count("plan-branch-revise")), (1, 1))
        self.assertLess(labels(calls).index("plan-branch-revise"), labels(calls).index("plan-review"))
        revise = prompt(calls, "plan-branch-revise")
        self.assertIn("fix only these problems in place", revise)
        self.assertIn('branch \\"other\\" is not declared', revise)
        self.assertIn("This is a revision", revise)
        _, calls = run(replies={"plan": bplan()})
        self.assertNotIn("plan-branch-revise", labels(calls))
        asked, calls = run(replies={"plan": bad, "plan-branch-revise": {"status": "needs_user", "questions": ["Which branch?"]}})
        self.assertEqual((asked["stage"], asked["needs_user"]), ("plan", ["Which branch?"]))

    def test_a_refused_plan_names_its_branch_problems_in_one_bounded_line(self):
        """#869: the plan-refused stop says why."""
        bad = bplan(task_branch="other")
        result, _ = run(replies={"plan": bad, "plan-branch-revise": bad})
        self.assertEqual(result["reason"], 'plan: branch problems: task 2: branch "other" is not declared')
        many = bplan([dict(BR, name=f"cand{i}", current=f"cand{i}", clean=False) for i in range(40)])
        result, _ = run(replies={"plan": many, "plan-branch-revise": many})
        self.assertEqual(len(result["reason"]), 300)
        self.assertTrue(result["reason"].endswith("..."))
        self.assertNotIn("\n", result["reason"])
        result, _ = run(replies={"plan": {"status": "planned"}})
        self.assertEqual(result["reason"], "plan: the plan reply is not a well-formed plan")
        result, _ = run(replies={"plan": bad, "plan-branch-revise": {"status": "planned"}})
        self.assertEqual((result["step"], result["reason"]), ("plan-branch-revise", "plan: the plan-branch-revise reply is not a well-formed plan"))

    def test_a_task_naming_the_delivery_branch_is_a_plain_task(self):
        """#864: a planner that tags a task with the delivery's own branch declared no extra branch."""
        own = dict(PLAN, branches=[], tasks=[dict(PLAN["tasks"][0], branch="issue-9-x")])
        result, calls = run(replies={"plan": own})
        self.assertEqual(result["stage"], "done")
        self.assertIn("plan-review", labels(calls))
        self.assertNotIn("commits to the declared branch", prompt(calls, "impl-1"))
        self.assertIn("git -C /r/.wt/w-issue-9-x diff", prompt(calls, "review-1"))
        self.assertNotIn("branch", result["tasks"][0])
        revised, calls = run(replies={"plan-review": TASK_FINDING, "plan-revise": own})
        self.assertEqual(revised["stage"], "done")
        self.assertEqual(labels(calls).count("plan-revise"), 1)
        cont = {"setup": {"ok": True, "worktree": "/r/.wt/w-issue-9-x", "branch": "issue-9-x", "plan_dir": "/g"},
                "plan": own, "plan_reviewed": True, "done": []}
        resumed, calls = run(args=dict(ARGS, cont=cont))
        self.assertEqual(resumed["stage"], "done")
        self.assertIn("impl-1", labels(calls))
        # Any other undeclared name is still refused, and so is declaring the delivery branch itself.
        for name, reply in {"other": dict(own, tasks=[dict(PLAN["tasks"][0], branch="other")]),
                            "case alias": dict(own, tasks=[dict(PLAN["tasks"][0], branch="ISSUE-9-X")]),
                            "declared": bplan([dict(BR, name="issue-9-x", current="issue-9-x")], task_branch="issue-9-x")}.items():
            with self.subTest(name=name):
                refused, calls = run(replies={"plan": reply, "plan-branch-revise": reply})
                self.assertEqual((refused["stage"], refused["step"]), ("plan", "plan-branch-revise"))
                self.assertTrue(refused["branch_problems"])
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
    (CLERK, ("setup", "acquire", "worktree", "renew-", "owner-answer", "plan-codex", "direct-codex", "final-codex", "diff-size", "amend",
             "verify", "verify-", "verify-rerun-", "ws-check-", "land-unlock", "land-push-", "land-lock-", "land-relock-", "pr", "checks-", "merge",
             "hold", "close-out")),
    (PLANNER, ("plan", "plan-revise", "plan-rules-revise", "plan-branch-revise", "plan-task-revise")),
    (IMPL, ("direct-impl", "direct-fix", "impl-", "fix-", "fix-wave", "fix-wave-", "verify-fix-", "fix-ci", "sync-", "sync-resolve-",
            "fix-sync-")),
    (REV, ("plan-review", "plan-rules-review", "direct-review-full", "final-", "final-integration", "fix-wave-review",
           "fix-wave-review-", "verify-fix-review-", "fix-ci-review", "sync-review-", "fix-sync-review-")),
    # #923: a review with no diff range (a no-commit task, a fix answered with no commit) runs on reviewer.
    (EITHER, ("review-", "direct-review", "rereview-")),
    (LITE, ("direct-rereview",)),
) for stem in stems}
STEM_PATTERNS = (
    r"\b(?:label|reviewLabel): (['`])([a-z][a-z0-9-]*)",
    r"\b\w*[lL]abel = (['`])([a-z][a-z0-9-]*)",
    r"`, (`)([a-z][a-z0-9-]*)(?=\$\{|`)",
)
CONFLICT = {"sync-1": ABORTED, "sync-resolve-1": {"conflicted": True, "merge_commit": MERGE, "resolved_files": ["a.py"]},
            "fix-sync-1": {"start_head": MERGE, "commit": FIX}}
VERIFY_RED = {"head": SHA, "clean": True, "results": [{"id": "build", "status": "fail", "summary": "boom"}]}
NARROWING = {"verdict": "findings",
             "findings": [{"severity": "critical", "summary": "race in release", "relation": "narrowing"}]}
SCENARIOS = (
    {},
    {"args": dict(ARGS, cont=RESUME_FOR_ANSWER), "replies": {"owner-answer": ANSWER}},
    {"args": dict(ARGS, cont=AMEND_CONT, amend=[AMEND_EDIT])},
    {"args": dict(ARGS, cont=dict(AMEND_CONT, blocked={"task": 2, "notes": "the fixture is missing"}), decisions="Use the other fixture.")},
    {"replies": {"plan": with_criteria(PlanRulesTest.ROWS[0][1]), "plan-revise": with_criteria(PlanRulesTest.ROWS[0][1]),
                 "plan-rules-revise": with_criteria(PlanRulesTest.ROWS[0][1])}},
    {"replies": {"plan-review": FINDING}},
    {"replies": {"plan": dict(PLAN, branches="none")}},
    {"args": dict(ARGS, cont={"claim_incomplete": True, "setup": {"holder": HOLDER}})},
    {"replies": {"plan": dict(PLAN, tasks=tasks(1, "low"))}},
    {"replies": {"review-1": BAD, "rereview-1-1": BAD, "rereview-1-2": BAD}},
    {"replies": {"plan": dict(PLAN, tasks=tasks(4)), "final-1": FINDING, "fix-wave-review": NARROWING}},
    {"args": dict(ARGS, review_sizing=True), "replies": {"plan": dict(PLAN, tasks=tasks(4))}},
    {"replies": {"verify": VERIFY_RED}},
    {"replies": {"verify": VerifyRerunTest.OUTSIDE}},
    {"patch": {"hold": {"release": None}}},
    {"replies": {"checks-2": {"state": "passed", "head": FIX, "required": ["ci-tests"]}},
     "patch": {"pr": {"checks": RED}, "fix-ci": {"start_head": SHA, "commit": FIX}}},
    {"replies": {"sync-review-1": FINDING, "checks-2": {"state": "passed", "head": FIX, "required": ["ci-tests"]}},
     "patch": dict(CONFLICT, pr={"checks": {"state": "behind", "head": SHA}})},
    {"patch": {"pr": {"lock": {"verdict": "land-contended", "lock_sha": "b" * 40}, "checks": None}}},
    # #913: a retake whose wait ran out is waited for again in a land-relock step.
    {"replies": {"checks-2": {"lock": {"verdict": "land-contended"}}, "checks-3": {"state": "passed", "head": MERGE}},
     "patch": {"pr": {"checks": {"state": "behind", "head": SHA}}, "sync-1": ABORTED, "sync-resolve-1": {"merge_commit": MERGE},
               "land-relock-1": {"lock": {"verdict": "acquired", "lock_sha": MERGE}}}},
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
        found = [c for c in all_calls() if c["label"] in ("plan", "plan-revise", "plan-rules-revise", "plan-branch-revise", "plan-task-revise")]
        self.assertEqual({c["label"] for c in found}, {"plan", "plan-revise", "plan-rules-revise", "plan-branch-revise", "plan-task-revise"})
        for call in found:
            self.assertEqual((call["agentType"], call["model"], call["effort"]), ("planner", None, None), call["label"])


class ClerkModelTest(unittest.TestCase):
    """#803, #813: clerk_model (sonnet, the default, or haiku) is checked before any agent and sets the model of every clerk call except the lifecycle and setup steps, which stay on the default."""

    ON_DEFAULT = {"setup", "worktree", "land-unlock", "land-push-", "land-lock-", "land-relock-", "pr", "merge", "hold", "close-out"}

    def test_clerk_model_must_be_sonnet_or_haiku(self):
        for bad in ("opus", "Haiku", "", 1, None, True):
            with self.subTest(bad=bad):
                result, calls = run(args=dict(ARGS, clerk_model=bad))
                self.assertEqual(result, {"stage": "args", "error": "clerk_model must be sonnet or haiku"})
                self.assertEqual(calls, [])

    def test_explicit_sonnet_runs_like_absent(self):
        absent, absent_calls = run()
        explicit, explicit_calls = run(args=dict(ARGS, clerk_model="sonnet"))
        self.assertEqual(explicit["stage"], "done")
        self.assertEqual([(c["label"], c["prompt"], c["model"]) for c in explicit_calls],
                         [(c["label"], c["prompt"], c["model"]) for c in absent_calls])

    def test_every_clerk_call_takes_the_clerk_model(self):
        clerk_stems = {stem for stem, kinds in EXPECTED.items() if kinds == frozenset({CLERK})}
        seen = set()
        pinned = set()
        for index, scenario in enumerate(SCENARIOS):
            with self.subTest(i=index):
                base = run(**scenario)[1]
                trial = run(**dict(scenario, args=dict(scenario.get("args", ARGS), clerk_model="haiku")))[1]
                self.assertEqual(labels(trial), labels(base))
                for b, t in zip(base, trial):
                    self.assertEqual(t["agentType"], b["agentType"], b["label"])
                    self.assertEqual(t["effort"], b["effort"], b["label"])
                    if b["agentType"] == CLERK:
                        stem = AgentTypeTest.stem_of(t["label"])
                        self.assertEqual(b["model"], "sonnet", b["label"])
                        if stem in self.ON_DEFAULT:
                            self.assertEqual(t["model"], "sonnet", b["label"])
                            pinned.add(stem)
                        else:
                            self.assertEqual(t["model"], "haiku", b["label"])
                            seen.add(stem)
                    else:
                        self.assertEqual(t["model"], b["model"], b["label"])
        self.assertEqual(pinned, self.ON_DEFAULT)
        self.assertEqual(seen, clerk_stems - self.ON_DEFAULT)

    def test_clerk_model_is_never_kept_in_cont(self):
        result, calls = run(args=dict(ARGS, mode="plan", clerk_model="haiku"))
        self.assertEqual(result["stage"], "planned")
        self.assertNotIn("clerk_model", json.dumps(result["cont"]))
        models = [c["model"] for c in calls if c["agentType"] == CLERK and c["label"] not in self.ON_DEFAULT]
        self.assertTrue(models)
        self.assertEqual(set(models), {"haiku"})

    def test_every_clerk_site_names_the_clerk_model(self):
        text = PROGRAM.read_text(encoding="utf-8")
        sites = re.findall(r"agentType: 'clerk', model: ([^,]+),", text)
        self.assertEqual(len(sites), text.count("agentType: 'clerk'"))
        self.assertGreater(len(sites), 0)
        self.assertEqual(set(sites), {"CLERK_MODEL", "DEFAULT_CLERK_MODEL"})


class PromptCommandFormTest(unittest.TestCase):
    """#738: a command ends at a line break, and a prompt that reads the issue body asks for it."""

    BODY_READERS = ("plan", "plan-revise", "plan-rules-revise", "plan-branch-revise", "plan-task-revise", "plan-review")

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


MAP_PATH = "/r/.git/worktrees/w/deliver-standard/context.md"
MAP_TASK_FINDING = {"verdict": "findings", "findings": [{"severity": "important", "summary": "gap", "failing_input": "x"}]}
MAP_READERS = re.compile(r"plan|plan-review|plan-codex|plan-revise|plan-rules-revise|plan-branch-revise|impl-\d+|fix-\d+-\d+")


def map_carriers(calls):
    return [c["label"] for c in calls if "context.md" in c["prompt"]]


class CodeMapTest(unittest.TestCase):
    """#743: the planner writes a code map beside the plan; plan reviewers, revisers and task implementers are pointed at it, nobody else."""

    def assert_no_map(self, calls, expected):
        # prompt() raises when a label is missing, so each expected call is shown to have run.
        for label in expected:
            with self.subTest(label=label):
                self.assertNotIn("context.md", prompt(calls, label))
        self.assertEqual([l for l in map_carriers(calls) if not MAP_READERS.fullmatch(l)], [])

    def test_the_planner_writes_the_map_in_the_plan_directory(self):
        _, calls = run()
        self.assertIn(MAP_PATH, prompt(calls, "plan"))

    def test_plan_reviewers_reviser_and_implementers_name_the_map(self):
        _, calls = run(replies={"plan-review": MAP_TASK_FINDING, "review-1": MAP_TASK_FINDING})
        for label in ("plan-review", "plan-codex", "plan-revise", "impl-1", "fix-1-1"):
            with self.subTest(label=label):
                self.assertIn(MAP_PATH, prompt(calls, label))

    def test_the_rules_only_reviser_names_the_map(self):
        # The scenario of PlanRulesTest.keep_stop: both reviews return an R2 rule finding, so plan-rules-revise runs.
        plan = with_criteria(HUMAN)
        _, calls = run(replies={"plan": plan, "plan-revise": plan, "plan-rules-revise": PlanRulesTest.REVISED,
                                "plan-review": PlanRulesTest.RULE_FINDING,
                                "plan-rules-review": PlanRulesTest.RULE_FINDING})
        self.assertIn(MAP_PATH, prompt(calls, "plan-rules-revise"))

    def test_task_reviewers_get_no_map(self):
        _, calls = run(replies={"review-1": MAP_TASK_FINDING})
        self.assert_no_map(calls, ("review-1", "rereview-1-1", "final-1", "final-codex"))

    def test_chunked_final_review_and_integration_get_no_map(self):
        _, calls = run(replies={"plan": dict(PLAN, tasks=tasks(4))})
        self.assert_no_map(calls, ("review-1", "review-4", "final-1", "final-2", "final-integration", "final-codex"))

    def test_the_final_fix_wave_and_its_review_get_no_map(self):
        _, calls = run(replies={"final-1": BAD})
        self.assert_no_map(calls, ("fix-wave", "fix-wave-review"))

    def test_the_direct_lane_and_its_repair_get_no_map(self):
        _, calls = run(args=DIRECT, replies={"direct-review": BAD})
        self.assert_no_map(calls, ("direct-impl", "direct-review", "direct-fix", "direct-rereview"))
        self.assertEqual(map_carriers(calls), [])


class PlannerReadsTest(unittest.TestCase):
    """#737, #819: the plan step batches its lookups itself; no step is granted a subagent, the Agent tool not existing here."""

    PLANNERS = ("plan", "plan-revise", "plan-rules-revise", "plan-branch-revise", "plan-task-revise")
    NO_SUBAGENTS = "- Do not dispatch subagents unless this step says so."
    HARD_RULES = "Hard rules for this step"
    BATCH = "put every open question's Bash or Read call in the same message as the others"
    PACE = "send at least four lookups in each exploration message and start writing by your twelfth message"
    # #967: the review-findings revise checks every finding in one message instead.
    REVISE_PACE = ("check every finding's claim in the first lookup message after the load below, one call per finding, "
                   "and send at most two follow-up lookup messages before editing")
    PROCEDURE = (BATCH, "several tool calls per message, never one small lookup per turn",
                 "No subagent can be dispatched: the Agent tool does not exist in this step.")

    def test_no_prompt_grants_explore_and_every_ruled_prompt_keeps_the_rule(self):
        planners, ruled = set(), set()
        for call in all_calls():
            text, label = call["prompt"], call["label"]
            for gone in ("Explore", "subagent_type", "you may dispatch"):
                self.assertNotIn(gone, text, label)
            if self.HARD_RULES in text:
                self.assertIn(self.NO_SUBAGENTS, text, label)
                ruled.add(label)
            if label in self.PLANNERS:
                for needle in ("Do not build, prototype or run the change", self.NO_SUBAGENTS):
                    self.assertIn(needle, text, label)
                planners.add(label)
        self.assertEqual(planners, set(self.PLANNERS))
        self.assertLessEqual({"setup", "impl-1", "pr", "merge"}, ruled)
        self.assertNotIn("Explore", PROGRAM.read_text(encoding="utf-8"))

    def test_every_planner_prompt_opens_with_the_lookup_procedure(self):
        seen = set()
        for call in all_calls():
            text, label = call["prompt"], call["label"]
            if label not in self.PLANNERS:
                self.assertNotIn("exploration message", text, label)
                self.assertNotIn(self.BATCH, text, label)
                continue
            self.assertTrue(text.startswith("Procedure for this step."), label)
            pace, other = (self.REVISE_PACE, self.PACE) if label in ("plan-revise", "plan-task-revise") else (self.PACE, self.REVISE_PACE)
            self.assertNotIn(other, text, label)
            self.assertNotIn("twelfth" if pace == self.REVISE_PACE else "follow-up lookup", text, label)
            # The pace sits inside the one procedure sentence, between the batching rule and the subagent line.
            self.assertIn(f"never one small lookup per turn), {pace}. No subagent can be dispatched", text, label)
            self.assertLess(text.index(pace), text.index("This is a revision:" if label != "plan" else "Then write the code map"), label)
            for needle in self.PROCEDURE + (pace,):
                self.assertIn(needle, text, label)
                # Before the task description, not after it.
                self.assertLess(text.index(needle), text.index("Plan this issue."), label)
                self.assertLess(text.index(needle), text.index("Issue #9 of "), label)
            seen.add(label)
        self.assertEqual(seen, set(self.PLANNERS))

    # #987: the reviewer's and the implementer's own one-sentence procedures, different sentences from the planner's BATCH.
    ROUNDS = {"reviewer": REVIEWER_ROUNDS, "implementer": IMPLEMENTER_ROUNDS}
    OPENERS = ("Look things up in rounds: load", "Work in rounds:")

    def test_every_reviewer_and_implementer_prompt_opens_with_its_one_sentence(self):
        seen = set()
        for call in all_calls():
            text, label, kind = call["prompt"], call["label"], call["agentType"]
            if kind not in self.ROUNDS:
                # reviewer-lite included: its steps are a few turns at a small context.
                for opener in self.OPENERS:
                    self.assertNotIn(opener, text, label)
                continue
            # One sentence, once, on a line of its own before the step's prompt, and never the other kind's.
            self.assertTrue(text.startswith(self.ROUNDS[kind] + "\n"), label)
            self.assertEqual(sum(text.count(opener) for opener in self.OPENERS), 1, label)
            seen.add(AgentTypeTest.stem_of(label))
        # Every site that can run one of the two kinds is seen running it, but for the two the scenarios reach on reviewer-lite only.
        self.assertEqual(seen | {"direct-review", "rereview-"}, {stem for stem, kinds in EXPECTED.items() if kinds & set(self.ROUNDS)})

    def test_each_rounds_sentence_is_one_constant_added_where_every_call_passes(self):
        source = PROGRAM.read_text(encoding="utf-8")
        for kind, sentence in self.ROUNDS.items():
            self.assertEqual(source.count(f"  {kind}: `{sentence}`,\n"), 1, kind)
            # One sentence: its only full stop ends it.
            self.assertEqual(sentence.index("."), len(sentence) - 1, kind)
        self.assertIn("reply = await agent(withRounds(withReply(prompt, opts), opts), opts)", source)
        # Every agent call of the program goes through that one wrapper.
        self.assertEqual(len(re.findall(r"\bawait agent\(", source)), 1)

    def test_the_shared_rules_keep_the_no_subagent_line_and_name_no_grant(self):
        source = PROGRAM.read_text(encoding="utf-8")
        start = source.index("const BASE_RULES = `")
        base_rules = source[start:source.index("`", start + len("const BASE_RULES = `"))]
        self.assertIn(self.NO_SUBAGENTS, base_rules)
        self.assertNotIn("Explore", base_rules)


class PreCommitFocusTest(unittest.TestCase):
    """#771: FOCUSED and FIX_TESTS name the contract's fast pre-commit ids, with argv and cwd, to every implementer."""

    # The flagged entry keeps the stub's id build, so every scenario's verify replies still answer the contract.
    UNFLAGGED = [{"id": "build", "argv": ["treefmt", "--fail-on-change"], "cwd": "tools"}]
    FLAGGED = [dict(UNFLAGGED[0], pre_commit=True)]
    NAMED = json.dumps(UNFLAGGED, separators=(",", ":"))
    GENERIC = "run any formatter or lint fix the project's standards (/r/docs/standards) name on the files you changed"
    PASSED = {"state": "passed", "head": FIX, "required": ["ci-tests"]}
    # One scenario per implementer prompt family that interpolates FOCUSED, with the labels it must reach.
    SCENARIOS = (
        ({"replies": {"review-1": TASK_FINDING}}, {"impl-1", "fix-1-1"}),
        ({"replies": {"final-1": FINDING}}, {"fix-wave"}),
        ({"replies": {"verify": VERIFY_RED}}, {"verify-fix-1"}),
        ({"replies": {"checks-2": PASSED},
          "patch": {"pr": {"checks": RED}, "fix-ci": {"start_head": SHA, "commit": FIX}}}, {"fix-ci"}),
        ({"replies": {"sync-review-1": FINDING, "checks-2": PASSED},
          "patch": dict(CONFLICT, pr={"checks": {"state": "behind", "head": SHA}})}, {"sync-1", "sync-resolve-1", "fix-sync-1"}),
        ({"args": DIRECT, "replies": {"direct-review": BAD}}, {"direct-impl", "direct-fix"}),
    )
    FAMILIES = frozenset().union(*(want for _, want in SCENARIOS))

    def implementer_prompts(self, verification):
        """Every FOCUSED-carrying implementer prompt, by label, over SCENARIOS with this verification contract."""
        found = {}
        for scenario, expected in self.SCENARIOS:
            patched = dict(scenario, patch={**scenario.get("patch", {}), "setup": {"verification": verification}})
            _, calls = run(**patched)
            prompts = {c["label"]: c["prompt"] for c in calls
                       if c["agentType"] == "implementer" and c["label"] in expected}
            self.assertLessEqual(expected, set(prompts), scenario)
            found.update(prompts)
        self.assertLessEqual(self.FAMILIES, set(found))
        return found

    def test_every_focused_site_has_a_scenario(self):
        # A prompt family that gains or loses FOCUSED must be reflected in SCENARIOS.
        source = PROGRAM.read_text(encoding="utf-8")
        # The merge sync names FMT directly (it runs WHOLE, not FOCUSED); four of the FMT uses are the FOCUSED, FIX_TESTS, OWN_TESTS
        # and EVIDENCE_FIX definitions (#935: EVIDENCE_FIX is direct-fix's other wording, the same family).
        sites = (source.count("${FOCUSED}") + source.count("${FIX_TESTS}") + source.count("${OWN_TESTS}")
                 + source.count("${FMT}") - 4)
        self.assertEqual(sites, len(self.FAMILIES))

    def test_the_evidence_fix_round_names_the_flagged_argv_too(self):
        ungraded = {"verdict": "pass", "findings": [], "acceptance": [{"id": "AC1", "met": False, "evidence": ""}]}
        _, calls = run(args=DIRECT, replies={"direct-review": ungraded}, patch={"setup": {"verification": self.FLAGGED}})
        self.assertIn("Produce the evidence each criterion asks for", prompt(calls, "direct-fix"))
        self.assertIn(self.NAMED, prompt(calls, "direct-fix"))

    def test_every_implementer_prompt_names_the_flagged_argv(self):
        for label, text in self.implementer_prompts(self.FLAGGED).items():
            with self.subTest(label=label):
                self.assertIn(self.NAMED, text)
                self.assertIn("fast pre-commit", text)
                self.assertNotIn(self.GENERIC, text)

    def test_with_none_flagged_the_generic_sentence_stays(self):
        for label, text in self.implementer_prompts(self.UNFLAGGED).items():
            with self.subTest(label=label):
                self.assertIn(self.GENERIC, text)
                self.assertNotIn("fast pre-commit", text)

    def test_only_the_flagged_ids_are_named(self):
        lint = {"id": "lint", "argv": ["make", "lint"], "cwd": "."}
        _, calls = run(replies={"verify": None}, patch={"setup": {"verification": [lint] + self.FLAGGED}})
        text = prompt(calls, "impl-1")
        self.assertIn(self.NAMED, text)
        self.assertNotIn('"make","lint"', text)

    def test_the_contract_read_asks_for_the_flag(self):
        _, calls = run()
        self.assertIn("pre_commit: true", prompt(calls, "setup"))
        item = schema_of(calls, "setup")["properties"]["verification"]["items"]
        self.assertEqual(item["properties"]["pre_commit"], {"type": "boolean"})


WHOLE_RUN = ("run in full every test file among or covering", "never a single test class",
             "any fast suite the project declares", "each command and its result")
FOCUSED_RUN = "Run only the tests covering the files you changed"
# #963: a step the verify step follows runs whole test files of what it changed and no suite.
OWN_RUN = ("Before returning, run in full every test file among or covering the files you changed (never a single test class) "
           "and no suite: the verify step runs it next; return tests: each command and its result.")


class WholeTestFileTest(unittest.TestCase):
    """#787: every implementer step after the task loop runs whole test files and reports each command and its result; #963: only a step the verify step does not follow also runs a fast suite."""

    def assert_own(self, text):
        self.assertIn(OWN_RUN, text)
        self.assertNotIn("fast suite", text)
        self.assertNotIn("Run only the tests", text)

    def assert_whole(self, text, files):
        for needle in WHOLE_RUN + (f"covering {files}",):
            self.assertIn(needle, text)
        self.assertNotIn("Run only the tests", text)
        self.assertNotIn("run only the tests", text)

    def test_both_fix_waves_run_whole_files_and_leave_the_suite_to_verify(self):
        _, calls = run(replies={"final-1": FixWaveTest.FIRST, "fix-wave-review": FixWaveTest.narrowing()})
        for label in ("fix-wave", "fix-wave-2"):
            with self.subTest(label=label):
                self.assert_own(prompt(calls, label))
                self.assertIn("each real defect with a regression test", prompt(calls, label))
        # The verify step runs after the last wave, before anything reads a suite result.
        seen = labels(calls)
        self.assertLess(seen.index("fix-wave-2"), seen.index("verify"))

    def test_verify_fix_runs_whole_files(self):
        _, calls = run(replies={"verify": VERIFY_RED})
        self.assert_own(prompt(calls, "verify-fix-1"))
        seen = labels(calls)
        self.assertLess(seen.index("verify-fix-1"), seen.index("verify-2"))

    def test_checks_fix_runs_whole_files(self):
        _, calls = run(patch={"pr": {"checks": {"state": "failed", "head": SHA}},
                              "fix-ci": {"start_head": SHA, "commit": "f" * 40}})
        self.assert_whole(prompt(calls, "fix-ci"), "the files you changed")

    def test_conflicted_sync_and_its_fix_run_whole_files(self):
        _, calls = run(replies={"sync-review-1": BAD},
                       patch={"pr": {"checks": {"state": "behind", "head": SHA}},
                              "sync-1": ABORTED, "sync-resolve-1": {"conflicted": True, "merge_commit": "d" * 40},
                              "fix-sync-1": {"start_head": "d" * 40, "commit": "f" * 40}})
        resolve = prompt(calls, "sync-resolve-1")
        self.assert_whole(resolve, "the files you resolved by hand")
        # #941: the resolution tests what it resolved; the pull request's checks cover what the merge brought in.
        self.assertIn("the checks of the pull request cover everything else the merge brought in, so run no test for a file that merged cleanly", resolve)
        self.assertNotIn("against its first parent", resolve)
        self.assert_whole(prompt(calls, "fix-sync-1"), "the files you changed")

    def test_task_loop_and_direct_lane_keep_the_focused_run(self):
        _, calls = run(replies={"review-1": BAD})
        _, direct = run(args=DIRECT, replies={"direct-review": BAD})
        for label, text in (("impl-1", prompt(calls, "impl-1")), ("fix-1-1", prompt(calls, "fix-1-1")),
                            ("direct-fix", prompt(direct, "direct-fix"))):
            with self.subTest(label=label):
                self.assertIn(FOCUSED_RUN, text)
                self.assertNotIn(WHOLE_RUN[0], text)


class KeptObligationTest(unittest.TestCase):
    """#787: the byte-budget trims left these obligations of the post-loop prompts in place."""

    def test_the_whitespace_attestation_stays_a_question(self):
        _, calls = WhitespaceCarryForwardTest.scenario(WS_ONLY)
        self.assertIn("Also judge whether each of its whitespace changes is insignificant:",
                      prompt(calls, "verify-fix-review-1"))

    def test_a_rejected_finding_needs_evidence_in_notes(self):
        _, calls = run(replies={"final-1": FixWaveTest.FIRST})
        self.assertIn("If a finding is wrong, explain with evidence in notes.", prompt(calls, "fix-wave"))

    def test_the_verify_body_asks_for_precise_failure_summaries(self):
        _, calls = run(replies={"verify": VERIFY_RED})
        self.assertIn("summarize the failing tests or errors precisely.", prompt(calls, "verify"))

    def test_the_sync_fix_may_not_rewrite_the_merge_and_its_rebuttal_is_checked_yourself(self):
        fix = {"start_head": "d" * 40, "commit": "d" * 40, "notes": "the finding is wrong because x"}
        _, calls = run(replies={"sync-review-1": BAD},
                       patch={"pr": {"checks": {"state": "behind", "head": SHA}},
                              "sync-1": ABORTED, "sync-resolve-1": {"conflicted": True, "merge_commit": "d" * 40}, "fix-sync-1": fix})
        self.assertIn("never redo or rewrite the merge", prompt(calls, "fix-sync-1"))
        self.assertIn("Check each rebuttal against the code yourself", prompt(calls, "fix-sync-review-1"))


class CodexUnavailableReasonTest(unittest.TestCase):
    """#790: a codex-unavailable stop carries the Codex reviewer's reported reason."""

    REASON = ("runtime failure: You've hit your usage limit. Visit https://chatgpt.com/codex/settings/usage "
              "to purchase more credits or try again at Nov 12th, 2026 5:34 AM.")
    SITES = ((ARGS, "plan-codex", "plan"), (ARGS, "final-codex", "code"), (DIRECT, "direct-codex", "code"))

    def test_each_codex_unavailable_stop_carries_the_reviewers_reason(self):
        for args, label, step in self.SITES:
            with self.subTest(label=label):
                reply = {"available": False, "verdict": "pass", "findings": [], "raw_summary": self.REASON}
                result, _ = run(args=args, replies={label: reply})
                self.assertEqual((result["stage"], result["step"]), ("codex-unavailable", step))
                self.assertEqual(result["details"], self.REASON)
                self.assertEqual(result["codex"], reply)

    def test_a_reply_without_a_reason_still_names_one(self):
        for raw in ({}, {"raw_summary": "  "}):
            with self.subTest(raw=raw):
                reply = {"available": False, "verdict": "pass", "findings": [], **raw}
                result, _ = run(replies={"final-codex": reply})
                self.assertEqual(result["details"], "the Codex review step gave no reason")

    def test_no_reply_is_named_and_stays_a_dead_agent(self):
        for args, label, step in self.SITES:
            with self.subTest(label=label):
                result, _ = run(args=args, replies={label: None})
                self.assertEqual((result["stage"], result["step"]), ("codex-unavailable", step))
                self.assertEqual(result["details"], "the Codex review step returned nothing")
                self.assertEqual(result["dead_agents"], [label])


class FoldedReleaseTest(unittest.TestCase):
    """#801: the lock release rides first in the hold call."""
    REL = f"forge-claim land release --repo owner/repo --branch dev --sha {SHA}\n"

    def test_the_hold_call_releases_the_land_lock_first(self):
        result, calls = run()
        self.assertEqual(result["stage"], "done")
        self.assertNotIn("cont", result)
        names = labels(calls)
        self.assertEqual(names[names.index("merge"):], ["merge", "hold", "close-out"])
        self.assertNotIn("land-unlock", names)
        text = prompt(calls, "hold")
        self.assertIn(self.REL, text)
        self.assertLess(text.index(self.REL), text.index("git -C /r fetch origin"))
        hold = schema_of(calls, "hold")
        self.assertEqual(set(member(hold, "release")["properties"]), {"verdict", "detail"})
        self.assertIn({"type": "null"}, hold["properties"]["release"]["anyOf"])
        self.assertNotIn("release", hold["required"])
        self.assertNotIn("lock_unreleased", result)

    def test_an_unconfirmed_folded_release_falls_back_to_one_standalone_release(self):
        for release in (None, {"verdict": "error", "detail": "gh failed"}):
            with self.subTest(release=release):
                result, calls = run(patch={"hold": {"release": release}})
                self.assertEqual(result["stage"], "done")
                self.assertNotIn("cont", result)
                names = labels(calls)
                self.assertEqual(names[-3:], ["hold", "close-out", "land-unlock"])
                self.assertEqual(names.count("land-unlock"), 1)
                self.assertIn(f"--sha {SHA}\n", prompt(calls, "land-unlock"))
                self.assertNotIn("lock_unreleased", result)
        result, calls = run(patch={"hold": {"release": {"verdict": "not_held"}}})
        self.assertEqual(result["stage"], "done")
        self.assertNotIn("land-unlock", labels(calls))

    def test_a_lost_hold_reply_still_releases_once_and_stops_at_hold(self):
        result, calls = run(replies={"hold": None})
        self.assertEqual(result["stage"], "hold")
        self.assertEqual(result["cont"], ship_cont())
        self.assertEqual(labels(calls)[-2:], ["hold", "land-unlock"])
        self.assertEqual(labels(calls).count("land-unlock"), 1)
        result, calls = run(replies={"hold": "throw"})
        self.assertIsNone(result)
        self.assertEqual(labels(calls)[-2:], ["hold", "land-unlock"])

    def test_a_failed_fallback_release_is_reported(self):
        result, calls = run(patch={"hold": {"release": {"verdict": "error"}}}, replies={"land-unlock": None})
        self.assertEqual(labels(calls)[-3:], ["hold", "close-out", "land-unlock"])
        self.assertEqual(result["stage"], "done")
        self.assertNotIn("cont", result)
        self.assertEqual(result["lock_unreleased"]["sha"], SHA)
        self.assertIn("land-unlock", result["dead_agents"])

    def test_a_hold_gate_stop_keeps_its_stage_and_cont_and_needs_no_fallback(self):
        result, calls = run(patch={"hold": {"code_unmet": ["AC1"]}})
        self.assertEqual(result["stage"], "code-unmet")
        self.assertEqual(result["cont"], ship_cont())
        self.assertNotIn("land-unlock", labels(calls))
        self.assertIn(self.REL, prompt(calls, "hold"))


class FoldedFirstChecksTest(unittest.TestCase):
    """#801: the first checks poll rides in the pr call."""

    CHECKS_CMD = "gh pr checks <the PR number> --repo owner/repo --json name,bucket,link"
    PUSH_CMD = "git -C /r/.wt/w-issue-9-x push origin issue-9-x"
    PENDING = {"state": "pending", "head": SHA, "pending": ["e2e"]}

    def test_the_pr_call_carries_the_first_checks_poll(self):
        result, calls = run()
        names = labels(calls)
        self.assertEqual(result["stage"], "done")
        self.assertNotIn("cont", result)
        self.assertEqual(names[names.index("pr"):], ["pr", "merge", "hold", "close-out"])
        pr = prompt(calls, "pr")
        self.assertIn(self.CHECKS_CMD, pr)
        self.assertIn("gh api repos/owner/repo/rules/branches/dev", pr)
        self.assertLess(pr.index(f"--sha {SHA} --wait\n"), pr.index(self.CHECKS_CMD))
        self.assertLess(pr.index(RENEW), pr.index(self.PUSH_CMD))
        schema = schema_of(calls, "pr")
        self.assertEqual(set(member(schema, "checks")["properties"]),
                         {"state", "head", "required", "passed", "failing", "pending", "details"})
        self.assertIn({"type": "null"}, schema["properties"]["checks"]["anyOf"])
        self.assertEqual(schema["required"], ["renew"])

    def test_each_folded_first_checks_failure_stops_as_before(self):
        rows = [
            ("lost", {"patch": {"pr": {"checks": None}}}, "checks", ship_cont()),
            ("head", {"patch": {"pr": {"checks": {"state": "passed", "head": "c" * 40}}}}, "head-moved", ship_cont()),
            ("pending", {"patch": {"pr": {"checks": self.PENDING}},
                         "replies": {"checks-2": self.PENDING, "checks-3": self.PENDING}},
             "checks-pending", ship_cont()),
            ("red", {"patch": {"pr": {"checks": RED}, "fix-ci": {"start_head": SHA, "commit": FIX}},
                     "replies": {"checks-2": dict(RED, head=FIX)}},
             "checks", ship_cont(checks_fixes=1)),
            ("behind", {"patch": {"pr": {"checks": {"state": "behind", "head": SHA}}}}, "done", None),
        ]
        for name, scenario, stage, cont in rows:
            with self.subTest(name):
                result, calls = run(**scenario)
                names = labels(calls)
                self.assertEqual(result["stage"], stage)
                if cont is None:
                    self.assertNotIn("cont", result)
                else:
                    self.assertEqual(result["cont"], cont)
                if name == "lost":
                    self.assertIsNone(result["checks"])
                    self.assertEqual(names.count("land-unlock"), 1)
                    self.assertNotIn("merge", names)
                    self.assertFalse([n for n in names if n.startswith("checks-")])
                elif name == "head":
                    self.assertNotIn("merge", names)
                elif name == "pending":
                    self.assertIn("checks-2", names)
                    self.assertIn("checks-3", names)
                    self.assertNotIn("checks-4", names)
                elif name == "red":
                    self.assertIn("fix-ci", names)
                    self.assertNotIn("merge", names)
                else:
                    self.assertEqual(names[names.index("pr"):],
                                     ["pr", "sync-1", "checks-2", "merge", "hold", "close-out"])

    def test_a_folded_poll_is_ignored_when_the_pr_step_stops(self):
        result, calls = run(patch={"pr": {"lock": {"verdict": "held_by", "by": "h2/b9"}}})
        self.assertEqual(result["stage"], "land-contended")
        self.assertEqual(result["cont"], ship_cont())
        self.assertFalse([n for n in labels(calls) if n.startswith("checks-")])
        result, _ = run(patch={"pr": {"head": "c" * 40}})
        self.assertEqual(result["stage"], "head-moved")
        self.assertEqual(result["cont"], ship_cont())

    def test_a_standalone_unmoved_round_still_renews(self):
        pending = {"pr": {"checks": self.PENDING}}
        result, calls = run(patch=pending)
        self.assertEqual(result["stage"], "done")
        second = prompt(calls, "checks-2")
        self.assertLess(second.index(RENEW), second.index("gh pr checks 42 --repo owner/repo --json name,bucket,link"))
        self.assertEqual(schema_of(calls, "checks-2")["required"], ["renew"])
        result, _ = run(patch=dict(pending, **{"checks-2": {"renew": {"verdict": "not_held", "by": "h2/b9"}}}))
        self.assertEqual(result["stage"], "claim-lost")
        self.assertEqual(result["at"], "checks-2")
        self.assertNotIn("cont", result)
        result, _ = run(patch=dict(pending, **{"checks-2": {"renew": {"verdict": "error", "detail": "x"}}}))
        self.assertEqual(result["stage"], "claim-lost")
        self.assertEqual(result["cont"], ship_cont(claim_incomplete=True))


class FoldedMovedRoundTest(unittest.TestCase):
    """#801: a moved round is one push call and one checks call."""

    MOVED_PATCH = {"pr": {"checks": {"state": "behind", "head": SHA}}, "sync-1": {"merge_commit": MERGE}}
    MOVED_OK = {"checks-2": {"state": "passed", "head": MERGE}}
    PUSH_CMD = "git -C /r/.wt/w-issue-9-x push origin issue-9-x"
    CHECKS_CMD = "gh pr checks 42 --repo owner/repo --json name,bucket,link"

    @staticmethod
    def REL(sha):
        return f"forge-claim land release --repo owner/repo --branch dev --sha {sha}"

    def moved(self, **replies):
        return run(patch=self.MOVED_PATCH, replies=dict(self.MOVED_OK, **replies))

    def test_a_moved_round_is_one_push_and_one_checks_call(self):
        result, calls = self.moved()
        self.assertEqual(result["stage"], "done")
        self.assertNotIn("cont", result)
        names = labels(calls)
        self.assertEqual(names[names.index("sync-1"):],
                         ["sync-1", "land-push-2", "checks-2", "merge", "hold", "close-out"])
        self.assertFalse([n for n in names if n.startswith("renew-checks") or n.startswith("land-lock")])
        push = prompt(calls, "land-push-2")
        self.assertLess(push.index(RENEW), push.index(self.PUSH_CMD))
        self.assertEqual(schema_of(calls, "land-push-2")["required"], ["renew"])
        checks = prompt(calls, "checks-2")
        acquire = f"forge-claim land acquire --repo owner/repo --branch dev --sha {MERGE}\n"
        self.assertLess(checks.index(acquire), checks.index(self.CHECKS_CMD))
        self.assertNotIn(" --wait\n", checks)
        self.assertNotIn(RENEW, checks)
        schema = schema_of(calls, "checks-2")
        self.assertIn("verdict", member(schema, "lock")["properties"])
        self.assertIn({"type": "null"}, schema["properties"]["lock"]["anyOf"])
        self.assertEqual(schema["required"], ["lock"])
        self.assertIn(self.REL(MERGE) + "\n", prompt(calls, "hold"))

    def test_each_moved_round_step_fails_at_its_old_stage(self):
        other = "c" * 40
        # (replies, stage, cont or None for none, extra check)
        cases = {
            "renew-ended": ({"land-push-2": {"renew": {"verdict": "not_held", "by": "h2/b9"}}}, "claim-lost", None),
            "renew-error": ({"land-push-2": {"renew": {"verdict": "error", "detail": "x"}}}, "claim-lost",
                            ship_cont(claim_incomplete=True)),
            "transient-recovers": ({"land-push-2": [{"renew": TRANSIENT}, {"head": MERGE}]}, "done", None),
            "transient-twice": ({"land-push-2": [{"renew": TRANSIENT}, {"renew": TRANSIENT}]}, "claim-lost",
                                ship_cont(claim_incomplete=True)),
            "push-lost": ({"land-push-2": None}, "push", ship_cont()),
            "push-other-head": ({"land-push-2": {"head": other}}, "head-moved", ship_cont()),
            "lock-refused": ({"checks-2": {"lock": {"verdict": "lost_to", "lock_sha": other}}}, "land-contended",
                             ship_cont()),
            "lock-lost": ({"checks-2": None}, "land-contended", ship_cont()),
            "lock-null": ({"checks-2": {"lock": None}}, "land-contended", ship_cont()),
            "lock-error": ({"checks-2": {"lock": {"verdict": "error", "detail": "gh failed"}}}, "land-contended",
                           ship_cont()),
            "lock-confirmed-no-fields": ({"checks-2": {"lock": {"verdict": "already_held", "lock_sha": MERGE}}},
                                         "checks", ship_cont()),
        }
        for name, (replies, stage, cont) in cases.items():
            with self.subTest(case=name):
                result, calls = run(patch=self.MOVED_PATCH, replies=dict(self.MOVED_OK, **replies))
                names = labels(calls)
                self.assertEqual(result["stage"], stage)
                if cont is None:
                    self.assertNotIn("cont", result)
                else:
                    self.assertEqual(result["cont"], cont)
                if name == "renew-ended":
                    self.assertEqual(result["at"], "checks-2")
                    self.assertNotIn("checks-2", names)
                if name == "renew-error":
                    self.assertEqual(result["at"], "checks-2")
                if name in ("transient-recovers", "transient-twice"):
                    self.assertEqual(names.count("land-push-2"), 2)
                if name == "transient-twice":
                    self.assertNotIn("checks-2", names)
                if name == "push-lost":
                    self.assertEqual(names.count("land-unlock"), 1)
                    self.assertIn(self.REL(SHA) + "\n", prompt(calls, "land-unlock"))
                    self.assertNotIn(self.REL(MERGE), prompt(calls, "land-unlock"))
                if name == "push-other-head":
                    self.assertEqual(result["expected"], MERGE)
                    self.assertNotIn("checks-2", names)
                    self.assertIn(self.REL(SHA), prompt(calls, "land-unlock"))
                    self.assertNotIn(self.REL(MERGE), prompt(calls, "land-unlock"))
                if name == "lock-refused":
                    self.assertEqual(result["lock"], "lost_to")
                    self.assertIn(self.REL(SHA), prompt(calls, "land-unlock"))
                    self.assertNotIn(self.REL(MERGE), prompt(calls, "land-unlock"))
                if name in ("lock-lost", "lock-null", "lock-error"):
                    self.assertIn(result["lock"], (None, "error"))
                    self.assertEqual(names.count("land-unlock"), 1)
                    self.assertIn(self.REL(SHA) + "\n", prompt(calls, "land-unlock"))
                    self.assertIn(self.REL(MERGE), prompt(calls, "land-unlock"))
                if name == "lock-confirmed-no-fields":
                    self.assertIsNone(result["checks"])
                    self.assertIn(self.REL(MERGE), prompt(calls, "land-unlock"))

    def test_a_short_fix_sha_moves_the_lock_by_the_pushed_full_sha(self):
        result, calls = run(patch={"pr": {"checks": RED}, "fix-ci": {"start_head": SHA, "commit": FIX[:9]}},
                            replies={"land-push-2": {"head": FIX},
                                     "checks-2": {"state": "passed", "head": FIX, "required": ["ci-tests"]}})
        self.assertEqual(result["stage"], "done")
        self.assertNotIn("cont", result)
        self.assertIn(f"--sha {FIX}\n", prompt(calls, "checks-2"))
        self.assertNotIn(f"--sha {FIX[:9]}\n", prompt(calls, "checks-2"))
        self.assertIn(self.REL(FIX) + "\n", prompt(calls, "hold"))


class AmendTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.d = self.tmp / "deliver-standard"
        self.d.mkdir()
        (self.d / "plan.md").write_text("# Plan\n\nD5 says old.\n", encoding="utf-8")
        (self.d / "task-2.md").write_text("Step 3: old rule here.\n", encoding="utf-8")

    def run_plan_amend(self, request):
        source = self.tmp / "input.json"
        source.write_text(json.dumps(request), encoding="utf-8")
        done = subprocess.run([*PLAN_AMEND, "apply", "--input", str(source)],
                              capture_output=True, text=True, check=False)
        return done.returncode, done.stdout

    def snapshot(self):
        return {f.name: f.read_bytes() for f in sorted(self.d.iterdir())}

    def test_a_valid_amend_edits_the_plan_file_and_adds_an_amendments_line_before_the_task(self):
        cont = plan_dir_cont(self.d)
        args = dict(ARGS, cont=cont, amend=[AMEND_EDIT])
        _, calls = run(args=args)
        code, out = self.run_plan_amend(amend_input(calls))
        result, calls2 = run(args=args, replies={"amend": json.loads(out)})
        self.assertEqual(code, 0)
        self.assertEqual((self.d / "task-2.md").read_bytes(), b"Step 3: new rule here.\n")
        self.assertEqual((self.d / "plan.md").read_bytes(),
                         b'# Plan\n\nD5 says old.\n\n## Amendments\n\n- Amendment answering the stop at task 2: '
                         b'in task-2.md, replaced "old rule" with "new rule".\n')
        self.assertEqual(result["stage"], "done")
        self.assertLess(labels(calls2).index("amend"), labels(calls2).index("impl-2"))

    def test_a_valid_amend_renews_then_runs_one_clerk_before_the_next_task(self):
        result, calls = run(args=dict(ARGS, cont=AMEND_CONT, amend=[AMEND_EDIT]))
        self.assertEqual(result["stage"], "done")
        self.assertEqual(labels(calls)[:4], ["setup", "renew-amend", "amend", "impl-2"])
        call = next(c for c in calls if c["label"] == "amend")
        self.assertEqual((call["agentType"], call["model"], call["effort"]), ("clerk", "sonnet", "low"))
        self.assertIn("plan-amend apply --input", call["prompt"])
        self.assertEqual(amend_input(calls), {
            "plan_dir": "/g", "plan_root": "/g/plan.md", "stop": "the stop at task 2",
            "edits": [{"file": "/g/task-2.md", "find": "old rule", "replace": "new rule"}]})

    def test_a_file_under_plan_dir_resolves_to_its_absolute_path(self):
        slash = dict(AMEND_CONT, setup=dict(AMEND_CONT["setup"], plan_dir="/g/"))
        for name, cont, file, want in (("absolute", AMEND_CONT, "/g/task-2.md", "/g/task-2.md"),
                                       ("nested", AMEND_CONT, "sub/x.md", "/g/sub/x.md"),
                                       ("trailing slash", slash, "task-2.md", "/g/task-2.md")):
            with self.subTest(name):
                _, calls = run(args=dict(ARGS, cont=cont, amend=[dict(AMEND_EDIT, file=file)]))
                got = amend_input(calls)
                self.assertEqual(got["plan_dir"], "/g")
                self.assertEqual(got["edits"][0]["file"], want)

    def test_a_file_outside_plan_dir_stops_at_amend_before_any_agent(self):
        cases = [(AMEND_CONT, dict(AMEND_EDIT, file=f), f) for f in (
            "/etc/passwd", "../plan.md", "sub/../task-2.md", "./task-2.md", "/g/../task-2.md",
            "/gx/task-2.md", "/g", "/G/task-2.md", "task 2.md")]
        elsewhere = dict(AMEND_CONT, plan=dict(PLAN, plan_root="/elsewhere/plan.md", tasks=tasks(2)))
        cases.append((elsewhere, AMEND_EDIT, "/elsewhere/plan.md"))
        for cont, edit, outside in cases:
            with self.subTest(outside):
                result, calls = run(args=dict(ARGS, cont=cont, amend=[edit]))
                self.assertEqual(result["stage"], "amend")
                self.assertEqual(result["cont"], cont)
                self.assertEqual(calls, [])
                self.assertIn({"file": outside, "reason": "outside plan_dir"}, result["refused"])

    def test_a_missing_or_repeated_find_stops_at_amend_with_files_and_cont_unchanged(self):
        for name, text, edit in (("repeated", "old rule, old rule\n", AMEND_EDIT),
                                 ("absent", None, dict(AMEND_EDIT, find="absent")),
                                 ("missing file", None, dict(AMEND_EDIT, file="task-9.md"))):
            with self.subTest(name):
                if text is not None:
                    (self.d / "task-2.md").write_text(text, encoding="utf-8")
                before = self.snapshot()
                cont = plan_dir_cont(self.d)
                args = dict(ARGS, cont=cont, amend=[edit])
                _, calls = run(args=args)
                code, out = self.run_plan_amend(amend_input(calls))
                result, calls2 = run(args=args, replies={"amend": json.loads(out)})
                self.assertEqual(code, 1)
                self.assertEqual(self.snapshot(), before)
                self.assertEqual(result["stage"], "amend")
                self.assertEqual(result["cont"], cont)
                self.assertNotIn("impl-2", labels(calls2))

    def test_a_reply_that_does_not_apply_every_edit_in_order_stops(self):
        second = {"file": "plan.md", "find": "D5", "replace": "D5 (amended)"}

        def G(f, **kw):
            return dict({"file": f, "exists": True, "occurrences": 1, "already": False}, **kw)
        both = [G("/g/task-2.md"), G("/g/plan.md")]
        for name, reply in (
                ("refused", {"status": "refused", "edits": both, "refused": []}),
                ("short", {"status": "applied", "edits": both[:1], "refused": []}),
                ("reversed", {"status": "applied", "edits": both[::-1], "refused": []}),
                ("repeated find", {"status": "applied", "edits": [both[0], G("/g/plan.md", occurrences=2)], "refused": []}),
                ("error", {"status": "error", "edits": [], "refused": [], "detail": "x"}),
                ("lost", None)):
            with self.subTest(name):
                result, calls = run(args=dict(ARGS, cont=AMEND_CONT, amend=[AMEND_EDIT, second]),
                                    replies={"amend": reply})
                self.assertEqual(result["stage"], "amend")
                self.assertEqual(result["cont"], AMEND_CONT)
                self.assertNotIn("impl-2", labels(calls))
                if reply is None:
                    self.assertEqual(result["dead_agents"], ["amend"])
        with self.subTest("already recorded"):
            reply = {"status": "applied", "refused": [],
                     "edits": [G("/g/task-2.md", already=True, occurrences=0), G("/g/plan.md")]}
            result, _ = run(args=dict(ARGS, cont=AMEND_CONT, amend=[AMEND_EDIT, second]), replies={"amend": reply})
            self.assertEqual(result["stage"], "done")

    def test_the_stop_text_names_the_stop(self):
        no_partial = {k: v for k, v in AMEND_CONT.items() if k != "partial"}
        for want, cont in (("the stop before task 2", no_partial),
                           ("the stop after the last task",
                            dict(no_partial, done=[{"n": 1, "commit": "c1"}, {"n": 2, "commit": "c2"}]))):
            with self.subTest(want):
                _, calls = run(args=dict(ARGS, cont=cont, amend=[AMEND_EDIT]))
                self.assertEqual(amend_input(calls)["stop"], want)

    def test_a_malformed_amend_stops_at_amend_with_the_cont_before_any_agent(self):
        cases = [(AMEND_CONT, a) for a in (
            [], "x", [["task-2.md"]], [{"file": "task-2.md", "find": "", "replace": "y"}],
            [{"file": "task-2.md", "find": "x"}], [{"file": "", "find": "x", "replace": "y"}],
            [{"file": "task-2.md", "find": "x", "replace": 1}], [None])]
        no_dir = dict(AMEND_CONT, setup={k: v for k, v in AMEND_CONT["setup"].items() if k != "plan_dir"})
        for cont in (dict(AMEND_CONT, plan=None),
                     dict(AMEND_CONT, lane="direct", plan=dict(PLAN, plan_root=None, tasks=tasks(2))),
                     dict(AMEND_CONT, lane="direct"),
                     dict(AMEND_CONT, plan=dict(PLAN, plan_root=5, tasks=tasks(2))),
                     dict(AMEND_CONT, setup=None), no_dir):
            cases.append((cont, [AMEND_EDIT]))
        for i, (cont, amend) in enumerate(cases):
            with self.subTest(i):
                result, calls = run(args=dict(ARGS, cont=cont, amend=amend))
                self.assertEqual(result["stage"], "amend")
                self.assertIn("error", result)
                self.assertEqual(result["cont"], cont)
                self.assertEqual(calls, [])

    def test_a_falsy_malformed_amend_is_refused_not_ignored(self):
        for amend in ("", 0, False):
            with self.subTest(amend=amend, cont=True):
                result, calls = run(args=dict(ARGS, cont=AMEND_CONT, amend=amend))
                self.assertEqual(result["stage"], "amend")
                self.assertEqual(result["cont"], AMEND_CONT)
                self.assertEqual(calls, [])
            with self.subTest(amend=amend, cont=False):
                result, calls = run(args=dict(ARGS, amend=amend))
                self.assertEqual(result["stage"], "args")
                self.assertEqual(calls, [])

    def test_amend_without_a_cont_stops_at_args(self):
        result, calls = run(args=dict(ARGS, amend=[AMEND_EDIT]))
        self.assertEqual(result["stage"], "args")
        self.assertNotIn("cont", result)
        self.assertEqual(calls, [])

    def test_a_kept_plan_planned_again_refuses_amend(self):
        F = {"severity": "important", "summary": "interface mismatch"}
        cont = {k: v for k, v in AMEND_CONT.items() if k != "partial"}
        cont.update(plan_reviewed=False, done=[], plan_findings={"rules": [F], "findings": [F], "rounds": 0})
        result, calls = run(args=dict(ARGS, cont=cont, amend=[AMEND_EDIT]))
        self.assertEqual(result["stage"], "amend")
        self.assertEqual(result["cont"], cont)
        self.assertEqual(labels(calls), ["setup", "owner-answer"])

    def test_a_lost_claim_stops_before_the_clerk(self):
        for name, reply in (("not_held", {"verdict": "not_held"}),
                            ("error", {"verdict": "error", "detail": "x"}), ("lost", None)):
            with self.subTest(name):
                result, calls = run(args=dict(ARGS, cont=AMEND_CONT, amend=[AMEND_EDIT]),
                                    replies={"renew-amend": reply})
                self.assertEqual(result["stage"], "claim-lost")
                self.assertEqual(result["at"], "amend")
                self.assertEqual(labels(calls), ["setup", "renew-amend"])
                if name == "not_held":
                    self.assertNotIn("cont", result)

    def test_an_unreviewed_plan_renews_once_then_amends_before_its_review(self):
        cont = dict({k: v for k, v in AMEND_CONT.items() if k != "partial"}, plan_reviewed=False, done=[])
        _, calls = run(args=dict(ARGS, cont=cont, amend=[AMEND_EDIT]))
        names = labels(calls)
        self.assertEqual(names[:3], ["setup", "renew-plan", "amend"])
        self.assertNotIn("renew-amend", names)
        self.assertLess(names.index("amend"), names.index("plan-review"))

    def test_an_applied_amend_invalidates_the_cached_review_and_verify(self):
        ready, _ = run(args=dict(ARGS, mode="ready"))
        self.assertEqual(ready["stage"], "ready")
        stopped, _ = run(replies={"verify": None}, patch={"impl-1": {"commit": TIP}})
        self.assertEqual(stopped["stage"], "verify")
        for name, cont, head, skipped in (("verified", ready["cont"], SHA, ("final-1", "verify")),
                                          ("final reviewed", stopped["cont"], TIP, ("final-1",))):
            plain, calls = run(args=dict(ARGS, cont=cont), patch={"setup": {"head": head}})
            with self.subTest(name, amend=False):
                self.assertEqual(plain["stage"], "done")
                for label in skipped:
                    self.assertNotIn(label, labels(calls))
            result, calls = run(args=dict(ARGS, cont=cont, amend=[AMEND_EDIT]), patch={"setup": {"head": head}})
            with self.subTest(name, amend=True):
                self.assertEqual(result["stage"], "done")
                self.assertLess(labels(calls).index("amend"), labels(calls).index("final-1"))
                self.assertIn("verify", labels(calls))
                self.assertIn("final-1", labels(calls))

    def test_an_edit_already_recorded_still_invalidates_the_cached_review(self):
        # A relaunch after a run that died between the clerk and any stop finds every edit recorded already, and its only
        # cont is the one from before the amend: the amended plan must still be reviewed and verified.
        ready, _ = run(args=dict(ARGS, mode="ready"))
        done = {"status": "applied", "refused": [],
                "edits": [{"file": ready["cont"]["setup"]["plan_dir"] + "/task-2.md", "exists": True,
                           "occurrences": 0, "already": True}]}
        result, calls = run(args=dict(ARGS, cont=ready["cont"], amend=[AMEND_EDIT]),
                            replies={"amend": done}, patch={"setup": {"head": SHA}})
        self.assertEqual(result["stage"], "done")
        self.assertIn("final-1", labels(calls))
        self.assertIn("verify", labels(calls))

    def test_an_amend_that_stops_after_the_clerk_ran_drops_the_cached_review_and_verify(self):
        ready, _ = run(args=dict(ARGS, mode="ready"))
        stopped, _ = run(replies={"verify": None}, patch={"impl-1": {"commit": TIP}})
        for name, cont, head in (("verified", ready["cont"], SHA), ("final reviewed", stopped["cont"], TIP)):
            self.assertTrue("verified" in cont or "final_reviewed" in cont)
            recorded = {"status": "applied", "refused": [],
                        "edits": [{"file": cont["setup"]["plan_dir"] + "/task-2.md", "exists": True,
                                   "occurrences": 0, "already": True}]}
            for lost, reply in (("lost reply", None), ("error reply", {"status": "error", "edits": [], "refused": [], "detail": "x"})):
                with self.subTest(name, lost=lost):
                    first, _ = run(args=dict(ARGS, cont=cont, amend=[AMEND_EDIT]), replies={"amend": reply},
                                   patch={"setup": {"head": head}})
                    self.assertEqual(first["stage"], "amend")
                    self.assertNotIn("verified", first["cont"])
                    self.assertNotIn("final_reviewed", first["cont"])
                    result, calls = run(args=dict(ARGS, cont=first["cont"], amend=[AMEND_EDIT]),
                                        replies={"amend": recorded}, patch={"setup": {"head": head}})
                    self.assertEqual(result["stage"], "done")
                    self.assertIn("final-1", labels(calls))
                    self.assertIn("verify", labels(calls))

    def test_a_confirmed_refusal_returns_the_cont_unchanged(self):
        ready, _ = run(args=dict(ARGS, mode="ready"))
        stopped, _ = run(replies={"verify": None}, patch={"impl-1": {"commit": TIP}})
        for name, cont, head in (("verified", ready["cont"], SHA), ("final reviewed", stopped["cont"], TIP)):
            self.assertTrue("verified" in cont or "final_reviewed" in cont)
            refused = {"status": "refused", "edits": [],
                       "refused": [{"file": cont["setup"]["plan_dir"] + "/task-2.md", "reason": "find occurs 2 times"}]}
            with self.subTest(name):
                result, _ = run(args=dict(ARGS, cont=cont, amend=[AMEND_EDIT]), replies={"amend": refused},
                                patch={"setup": {"head": head}})
                self.assertEqual(result["stage"], "amend")
                self.assertEqual(result["cont"], cont)

    def test_a_resume_without_amend_is_unchanged(self):
        result, calls = run(args=dict(ARGS, cont=AMEND_CONT))
        self.assertEqual(result["stage"], "done")
        self.assertEqual(labels(calls)[:3], ["setup", "impl-2", "review-2"])
        self.assertNotIn("amend", labels(calls))
        self.assertNotIn("renew-amend", labels(calls))
        self.assertFalse(any("plan-amend" in c["prompt"] for c in calls))

    def test_amend_is_never_kept_in_cont(self):
        result, calls = run(args=dict(ARGS, cont=AMEND_CONT, amend=[AMEND_EDIT]), replies={"verify": None})
        self.assertEqual(result["stage"], "verify")
        self.assertIn("amend", labels(calls))
        self.assertNotIn("amend", result["cont"])
        self.assertNotIn("Amendment", json.dumps(result["cont"]))

    def test_a_stop_after_the_amend_applied_says_so_and_a_refusal_does_not(self):
        result, calls = run(args=dict(ARGS, cont=AMEND_CONT, amend=[AMEND_EDIT]), replies={"verify": None})
        self.assertEqual(result["stage"], "verify")
        self.assertIs(result["amended"], True)
        F = {"severity": "important", "summary": "interface mismatch"}
        kept = {k: v for k, v in AMEND_CONT.items() if k != "partial"}
        kept.update(plan_reviewed=False, done=[], plan_findings={"rules": [F], "findings": [F], "rounds": 0})
        for name, args, replies in (
                ("plan planned again", dict(ARGS, cont=kept, amend=[AMEND_EDIT]), {}),
                ("not applied", dict(ARGS, cont=AMEND_CONT, amend=[AMEND_EDIT]), {"amend": {"status": "refused", "edits": [], "refused": []}}),
                ("lost claim", dict(ARGS, cont=AMEND_CONT, amend=[AMEND_EDIT]), {"renew-amend": {"verdict": "error", "detail": "x"}})):
            with self.subTest(name):
                result, _ = run(args=args, replies=replies)
                self.assertNotIn("amended", result)



INCOMPLETE = {"verdict": "incomplete", "findings": []}
# What a reply sent beside a pending lookup held (#992): a blocking finding that names neither a file nor a failing input.
PLACEHOLDER = {"verdict": "findings", "findings": [{"severity": "important", "file": "", "summary": "Placeholder emitted to satisfy the schema"}]}
REAL = {"verdict": "findings", "findings": [{"severity": "important", "file": "src/a.py", "summary": "off by one"}]}
NO_REVIEW = ": the reply is no review ("
LOST_REVIEW = ": the second reply is no review either; the review is lost"


class StructuredReplyTest(unittest.TestCase):
    """#992: the structured reply goes alone and last; an unusable review reply reruns the step once and is never a finding."""

    FOUR = {"plan": dict(PLAN, tasks=tasks(4))}
    SYNC = {"pr": {"checks": {"state": "behind", "head": SHA}}, "sync-1": ABORTED,
            "sync-resolve-1": {"conflicted": True, "merge_commit": MERGE, "resolved_files": ["a.py"]}}

    def test_every_step_ends_with_the_one_sentence(self):
        seen = all_calls()
        self.assertTrue(seen)
        for call in seen:
            with self.subTest(label=call["label"]):
                self.assertIsNotNone(call["schema"])
                self.assertTrue(call["prompt"].endswith("\n" + REPLY_ALONE))
                self.assertEqual(call["prompt"].count("StructuredOutput"), 1)

    def test_the_sentence_is_one_constant_shared_with_deliver_batch(self):
        mine = PROGRAM.read_text(encoding="utf-8")
        batch = PROGRAM.with_name("deliver-batch.js").read_text(encoding="utf-8")
        line = f"const REPLY_ALONE = '{REPLY_ALONE}'\n"
        self.assertEqual((mine.count(line), batch.count(line)), (1, 1))
        # One sentence: its only full stop ends it. It is added where every call passes, and nowhere else.
        self.assertEqual(REPLY_ALONE.index("."), len(REPLY_ALONE) - 1)
        self.assertEqual(mine.count("StructuredOutput"), 2)
        self.assertIn("const withReply = (prompt, opts) => (opts && opts.schema ? `${prompt}\\n${REPLY_ALONE}` : prompt)\n", mine)

    def test_the_sentence_stands_with_the_rounds_sentences(self):
        # The rounds sentences batch lookups and edits; the reply sentence is about the one tool they never name.
        for rounds in (REVIEWER_ROUNDS, IMPLEMENTER_ROUNDS):
            self.assertNotIn("StructuredOutput", rounds)
            self.assertNotIn("every tool call", rounds)
        self.assertIn("never beside another tool call", REPLY_ALONE)
        _, calls = run()
        text = prompt(calls, "review-1")
        self.assertTrue(text.startswith(REVIEWER_ROUNDS + "\n"))
        self.assertTrue(text.endswith("\n" + REPLY_ALONE))

    def test_an_unusable_task_review_reruns_once_and_spends_no_fix_round(self):
        for name, reply in (("placeholder", PLACEHOLDER), ("incomplete", INCOMPLETE)):
            with self.subTest(reply=name):
                out = run_out(replies={"review-1": reply})
                result, calls = out["result"], out["calls"]
                self.assertEqual(result["stage"], "done")
                names = labels(calls)
                self.assertEqual(names[names.index("impl-1"):names.index("impl-1") + 4], ["impl-1", "review-1", "review-1-again", "renew-final-review"])
                self.assertFalse([n for n in names if n.startswith(("fix-1-", "rereview-1-"))])
                self.assertEqual(result["tasks"][0]["review_rounds"], 0)
                first, again = (next(c for c in calls if c["label"] == label) for label in ("review-1", "review-1-again"))
                self.assertEqual((again["agentType"], again["schema"]), (first["agentType"], first["schema"]))
                body = first["prompt"][:-len("\n" + REPLY_ALONE)]
                self.assertTrue(again["prompt"].startswith(body + "\nAn earlier reply to this step was discarded: "))
                self.assertTrue(again["prompt"].endswith("Finish the review before you reply.\n" + REPLY_ALONE))
                self.assertEqual(len([l for l in out["logs"] if l.startswith("review-1" + NO_REVIEW)]), 1)
                self.assertNotIn("dead_agents", result)

    def test_the_rerun_s_real_finding_gets_the_fix_round(self):
        result, calls = run(replies={"review-1": PLACEHOLDER, "review-1-again": REAL})
        self.assertEqual(result["stage"], "done")
        self.assertIn("off by one", prompt(calls, "fix-1-1"))
        self.assertNotIn("Placeholder", prompt(calls, "fix-1-1"))
        self.assertEqual(result["tasks"][0]["review_rounds"], 1)

    def test_two_unusable_replies_in_a_row_are_a_lost_review(self):
        for first, second in ((PLACEHOLDER, PLACEHOLDER), (INCOMPLETE, PLACEHOLDER), (PLACEHOLDER, INCOMPLETE)):
            with self.subTest(first=first["verdict"], second=second["verdict"]):
                out = run_out(replies={"review-1": first, "review-1-again": second})
                result, names = out["result"], labels(out["calls"])
                # The stop a reviewer that returned nothing takes, with no fix round spent and no dead agent named.
                lost, _ = run(replies={"review-1": None})
                self.assertEqual(result["stage"], lost["stage"])
                self.assertIsNone(result["review"])
                self.assertEqual(names[-2:], ["review-1", "review-1-again"])
                # A lost review and a dead reviewer are told apart: by the list that names the step, and by the reason.
                self.assertEqual(result["reason"], "task-review: task 1 the reviewer answered twice with no usable review")
                self.assertEqual(result["lost_reviews"], ["review-1"])
                self.assertNotIn("dead_agents", result)
                self.assertEqual(lost["reason"], "task-review: task 1 the reviewer returned nothing")
                self.assertEqual(lost["dead_agents"], ["review-1"])
                self.assertNotIn("lost_reviews", lost)
                self.assertIn("review-1" + LOST_REVIEW, out["logs"])

    def test_an_unusable_rereview_reruns_too_and_the_fix_round_it_follows_is_the_only_one(self):
        result, calls = run(replies={"review-1": REAL, "rereview-1-1": PLACEHOLDER})
        self.assertEqual(result["stage"], "done")
        names = labels(calls)
        self.assertEqual([n for n in names if "1-" in n and n.startswith(("fix-", "rereview-"))], ["fix-1-1", "rereview-1-1", "rereview-1-1-again"])
        result, calls = run(replies={"review-1": REAL, "rereview-1-1": INCOMPLETE, "rereview-1-1-again": INCOMPLETE})
        self.assertEqual(result["stage"], "task-review")
        self.assertNotIn("fix-1-2", labels(calls))

    def test_a_usable_reply_is_never_rerun(self):
        minor = {"verdict": "findings", "findings": [{"severity": "minor", "summary": "style"}]}
        by_input = {"verdict": "findings", "findings": [{"severity": "critical", "summary": "crash", "failing_input": "an empty list"}]}
        for name, reply in (("pass", PASS_REPLY), ("minor", minor), ("file", REAL), ("failing input", by_input)):
            with self.subTest(reply=name):
                out = run_out(replies={"review-1": reply})
                self.assertFalse([n for n in labels(out["calls"]) if n.endswith("-again")])
                self.assertFalse([l for l in out["logs"] if NO_REVIEW in l])

    def test_every_strict_review_site_reruns_a_placeholder(self):
        red = {"head": SHA, "clean": True, "results": [{"id": "build", "status": "fail", "summary": "boom"}]}
        cases = (
            ("sync-review-1", {"patch": self.SYNC}),
            ("fix-sync-review-1", {"patch": dict(self.SYNC, **{"fix-sync-1": {"start_head": MERGE, "commit": FIX}}), "replies": {"sync-review-1": REAL}}),
            ("fix-ci-review", {"patch": {"pr": {"checks": RED}, "fix-ci": {"start_head": SHA, "commit": FIX}}}),
            ("verify-fix-review-1", {"replies": {"verify": red}}),
        )
        for label, scenario in cases:
            for name, reply in (("placeholder", PLACEHOLDER), ("incomplete", INCOMPLETE)):
                with self.subTest(label=label, reply=name):
                    replies = dict(scenario.get("replies", {}), **{label: reply})
                    _, calls = run(patch=scenario.get("patch"), replies=replies)
                    names = labels(calls)
                    self.assertEqual(names[names.index(label):names.index(label) + 2], [label, label + "-again"])
                    self.assertEqual(names.count(label + "-again"), 1)

    def test_a_lost_sync_review_stops_at_the_sync_review_and_spends_no_fix(self):
        result, calls = run(patch=self.SYNC, replies={"sync-review-1": PLACEHOLDER, "sync-review-1-again": PLACEHOLDER})
        lost, _ = run(patch=self.SYNC, replies={"sync-review-1": None})
        self.assertEqual((result["stage"], lost["stage"]), ("sync-review", "sync-review"))
        self.assertEqual((result["reason"], lost["reason"]), ("sync-review: the reviewer answered twice with no usable review", "sync-review: the reviewer returned nothing"))
        self.assertNotIn("fix-sync-1", labels(calls))
        self.assertNotIn("sync_fixes", result["cont"])
        self.assertEqual((result["lost_reviews"], result.get("dead_agents")), (["sync-review-1"], None))
        self.assertEqual((lost.get("lost_reviews"), lost["dead_agents"]), (None, ["sync-review-1"]))

    def test_every_review_holds_a_blocking_finding_to_its_subject(self):
        # A finding that names neither a file nor a failing input (an empty file: named() leaves it as written).
        bare = {"verdict": "findings", "findings": [{"severity": "important", "file": "", "summary": "AC1 is not shown met"}]}
        ruled = dict(bare, findings=[dict(bare["findings"][0], rule="R2")])
        # label: (scenario, the step a finding of it would reach)
        sites = {
            "plan-review": ({}, "plan-revise"),
            "plan-rules-review": ({"replies": {"plan-review": ruled}}, None),
            "final-1": ({}, "fix-wave"),
            "final-integration": ({"replies": dict(self.FOUR)}, "fix-wave"),
            "fix-wave-review": ({"replies": {"final-1": REAL}}, None),
            "direct-review": ({"args": DIRECT}, "direct-fix"),
            "direct-rereview": ({"args": DIRECT, "replies": {"direct-review": REAL}}, None),
        }
        for label, (scenario, reached) in sites.items():
            for name, reply in (("placeholder", bare), ("incomplete", INCOMPLETE)):
                with self.subTest(label=label, reply=name):
                    out = run_out(scenario.get("args"), dict(scenario.get("replies", {}), **{label: reply}), scenario.get("patch"))
                    names = labels(out["calls"])
                    self.assertEqual(names.count(label + "-again"), 1)
                    self.assertEqual(len([l for l in out["logs"] if l.startswith(label + NO_REVIEW)]), 1)
                    if reached:
                        self.assertNotIn(reached, names)

    def test_a_plan_review_finding_that_names_its_rule_or_criterion_names_its_subject(self):
        # The two plan reviews only: a rule finding is about a criterion, and the plan's own rule check reports ac and rule alone.
        for key, value in (("rule", "R2"), ("ac", "AC1")):
            ruled = {"verdict": "findings", "findings": [{"severity": "important", "file": "", "summary": "AC1 breaks a rule", "rule": "R2", key: value}]}
            for label, replies in (("plan-review", {}), ("plan-rules-review", {"plan-review": ruled})):
                with self.subTest(label=label, key=key):
                    out = run_out(replies=dict(replies, **{label: ruled}))
                    self.assertFalse([n for n in labels(out["calls"]) if n.endswith("-again")])
                    self.assertFalse([l for l in out["logs"] if NO_REVIEW in l])
        # Anywhere else a rule names nothing the fix wave can act on.
        ruled = {"verdict": "findings", "findings": [{"severity": "important", "file": "", "summary": "AC1 breaks a rule", "rule": "R2"}]}
        _, calls = run(replies={"final-1": ruled})
        self.assertIn("final-1-again", labels(calls))

    def test_only_a_task_that_ended_with_no_commit_may_raise_a_finding_with_no_subject(self):
        # Its outputs may be no file (a posted comment); the same finding on a diff review is a placeholder.
        bare = {"verdict": "findings", "findings": [{"severity": "important", "file": "", "summary": "the comment was not posted"}]}
        no_commit = {"impl-1": {"start_head": SHA, "commit": SHA}}
        _, calls = run(replies={"review-1": bare})
        self.assertIn("review-1-again", labels(calls))
        out = run_out(replies={"review-1": bare}, patch=no_commit)
        self.assertFalse([n for n in labels(out["calls"]) if n.endswith("-again")])
        self.assertFalse([l for l in out["logs"] if NO_REVIEW in l])
        self.assertIn("fix-1-1", labels(out["calls"]))
        # Its verdict is still read: an unfinished review of it runs once more.
        _, calls = run(replies={"review-1": INCOMPLETE}, patch=no_commit)
        self.assertEqual(labels(calls).count("review-1-again"), 1)
        self.assertNotIn("fix-1-1", labels(calls))

    def test_the_fixture_helper_names_a_failing_input_only_where_a_fixture_names_no_subject(self):
        given = {"review-1": {"verdict": "findings", "findings": [
            {"severity": "important", "summary": "a"}, {"severity": "minor", "summary": "b"}, {"severity": "critical", "file": "", "summary": "c"},
            {"severity": "critical", "file": "x.py", "summary": "d"}, {"severity": "critical", "failing_input": "y", "summary": "e"}]}, "plan": None, "verify": [PASS_REPLY, "throw"]}
        got = named(given)
        self.assertEqual(got["review-1"]["findings"][0], {"severity": "important", "summary": "a", "failing_input": "x"})
        self.assertEqual(got["review-1"]["findings"][1:], given["review-1"]["findings"][1:])
        self.assertEqual((got["plan"], got["verify"]), (None, [PASS_REPLY, "throw"]))
        self.assertNotIn("failing_input", given["review-1"]["findings"][0])

    def test_a_lost_integration_review_stops_the_final_review_and_is_no_dead_agent(self):
        result, calls = run(replies=dict(self.FOUR, **{"final-integration": INCOMPLETE, "final-integration-again": INCOMPLETE}))
        self.assertEqual((result["stage"], result["details"]), ("final-review", "the integration reviewer answered twice with no usable review"))
        self.assertEqual(result["reason"], "final-review: the integration reviewer answered twice with no usable review")
        self.assertEqual(result["lost_reviews"], ["final-integration"])
        self.assertNotIn("dead_agents", result)
        self.assertNotIn("fix-wave", labels(calls))
        dead, _ = run(replies=dict(self.FOUR, **{"final-integration": None}))
        self.assertEqual((dead["details"], dead["dead_agents"]), ("the integration reviewer returned nothing", ["final-integration"]))
        self.assertNotIn("lost_reviews", dead)

    def test_a_lost_final_review_spends_no_fix_wave(self):
        result, calls = run(replies={"final-1": INCOMPLETE, "final-1-again": INCOMPLETE})
        self.assertEqual((result["stage"], result["details"]), ("final-review", "a final reviewer answered twice with no usable review"))
        self.assertEqual(result["cont"]["fix_waves"], 0)
        self.assertNotIn("fix-wave", labels(calls))
        self.assertEqual(result["lost_reviews"], ["final-1"])
        self.assertNotIn("dead_agents", result)
        dead, _ = run(replies={"final-1": None})
        self.assertEqual(dead["details"], "a final reviewer returned nothing")

    def test_a_lost_plan_review_says_so_and_a_later_stop_still_names_it(self):
        result, _ = run(replies={"plan-review": INCOMPLETE, "plan-review-again": INCOMPLETE})
        self.assertEqual((result["stage"], result["reason"]), ("plan-review", "plan-review: the plan reviewer answered twice with no usable review"))
        self.assertEqual(result["lost_reviews"], ["plan-review"])
        dead, _ = run(replies={"plan-review": None})
        self.assertEqual(dead["reason"], "plan-review: the plan reviewer returned nothing")
        ruled = {"verdict": "findings", "findings": [{"severity": "important", "summary": "AC1 breaks a rule", "rule": "R2"}]}
        result, _ = run(replies={"plan-review": ruled, "plan-rules-review": INCOMPLETE, "plan-rules-review-again": INCOMPLETE})
        self.assertEqual((result["stage"], result["details"]), ("plan-review", "the rules re-reviewer answered twice with no usable review"))
        self.assertEqual(result["lost_reviews"], ["plan-rules-review"])
        dead, _ = run(replies={"plan-review": ruled, "plan-rules-review": None})
        self.assertEqual(dead["details"], "the rules re-reviewer returned nothing")

    def test_the_findings_schema_names_the_incomplete_verdict_and_what_a_blocking_finding_carries(self):
        _, calls = run(replies=dict(self.FOUR, **{"review-1": REAL, "final-1": REAL}))
        for label in ("plan-review", "review-1", "rereview-1-1", "final-1", "final-integration", "fix-wave-review"):
            with self.subTest(label=label):
                schema = schema_of(calls, label)
                self.assertEqual(schema["properties"]["verdict"]["enum"], ["pass", "findings", "incomplete"])
                self.assertIn("incomplete", schema["properties"]["verdict"]["description"])
                items = schema["properties"]["findings"]["items"]
                self.assertEqual(items["description"], "a critical or important finding names its file or its failing_input")
                self.assertEqual(items["required"], ["severity", "summary"])

    def test_every_review_reply_is_read_through_the_one_wrapper(self):
        source = PROGRAM.read_text(encoding="utf-8")
        schemas = (r"schema: (?:asked \? WS_REVIEW : FINDINGS|withChanged\(FINDINGS\)|SYNC_REVIEW_SCHEMA\(followup\)|FINDINGS|PLAN_REVIEW"
                   r"|GRADED_FINDINGS|DIRECT_FINDINGS) \}")
        sites = [m.end() for m in re.finditer(schemas, source)]
        self.assertEqual(len(sites), 15)
        # The options object of a review call closes the readReview() call, or one of its three named options does.
        tails = [source[end:source.index(")", end) + 1] for end in sites]
        self.assertEqual(sorted(set(tails)), sorted([")", ", { fileless })", ", { ruled: true })", ", { optional: true })"]))
        self.assertEqual((tails.count(", { fileless })"), tails.count(", { ruled: true })"), tails.count(", { optional: true })")), (4, 2, 1))
        self.assertEqual(len(re.findall(r"\breadReview\((?!\))", source)), 15)
        # No schema that carries findings is built anywhere else: each is one of the named ones above, FINDINGS spread into it.
        self.assertEqual(len(re.findall(r"\.\.\.(?:GRADED_)?FINDINGS,", source)), 5)
        self.assertEqual(source.count(", { fileless })"), 4)
        self.assertEqual(source.count("const fileless = !diffReviewed\n"), 1)
        self.assertEqual(source.count("{ ruled: true }"), 2)

    def test_an_implementer_reply_names_full_shas_or_none(self):
        red = {"head": SHA, "clean": True, "results": [{"id": "build", "status": "fail", "summary": "boom"}]}
        scenarios = (
            (("impl-1", "fix-1-1", "fix-wave"), {"replies": {"review-1": REAL, "final-1": REAL}}),
            (("direct-impl", "direct-fix"), {"args": DIRECT, "replies": {"direct-review": BAD}}),
            (("verify-fix-1",), {"replies": {"verify": red}}),
            (("fix-ci",), {"patch": {"pr": {"checks": RED}, "fix-ci": {"start_head": SHA, "commit": FIX}}}),
            (("fix-sync-1",), {"patch": dict(self.SYNC, **{"fix-sync-1": {"start_head": MERGE, "commit": FIX}}), "replies": {"sync-review-1": REAL}}),
        )
        for wanted, scenario in scenarios:
            _, calls = run(**scenario)
            for label in wanted:
                with self.subTest(label=label):
                    schema = schema_of(calls, label)
                    for field in ("commit", "start_head"):
                        spec = schema["properties"][field]
                        self.assertEqual(spec, {"type": "string", "pattern": "^[0-9a-f]{40}$"})
                        for bad in ("PLACEHOLDER", "", "c0ffee", SHA.upper(), SHA + "0", "none"):
                            self.assertIsNone(re.search(spec["pattern"], bad), bad)
                        self.assertIsNotNone(re.search(spec["pattern"], SHA))
                        # A blocked reply names no commit: the two stay optional.
                        self.assertNotIn(field, schema["required"])
                    self.assertLessEqual({"status", "notes"}, set(schema["properties"]))


class BlockedTaskDecisionTest(unittest.TestCase):
    """#996: a blocked task's notes ride in the cont, and its resume needs a new decision (a planner revises the task file) or an amend."""

    NOTES = "the task file names a fixture that does not exist"
    DECISION = "Use the fixture tests/data/a.json instead."
    PLAN2 = dict(PLAN, tasks=tasks(2))
    REVISED = dict(PLAN2, criteria_edited=[])

    def stopped(self, notes=None, **args):
        result, _ = run(args=dict(ARGS, **args), replies={"plan": self.PLAN2, "impl-2": blocked(self.NOTES if notes is None else notes)})
        self.assertEqual(result["stage"], "task")
        return result

    def resume(self, cont, replies=None, **args):
        return run(args=dict(ARGS, cont=cont, **args), replies=dict({"plan-task-revise": self.REVISED}, **(replies or {})))

    def test_the_task_stop_keeps_the_notes_and_names_both_ways_out(self):
        result = self.stopped()
        self.assertEqual(result["cont"]["blocked"], {"task": 2, "notes": self.NOTES})
        self.assertEqual(result["cont"]["partial"], 2)
        self.assertEqual(result["reason"], f"task: task 2 blocked: {self.NOTES}{WAYS}")
        for way in ("decisions", "amend {file, find, replace}"):
            self.assertIn(way, result["reason"])
        long = self.stopped(notes="x" * 5000)
        self.assertEqual(len(long["cont"]["blocked"]["notes"]), 2000)
        self.assertEqual(len(long["reason"]), 300)
        self.assertTrue(long["reason"].endswith(f"...{WAYS}"), long["reason"])

    def test_a_stop_that_is_not_a_blocked_implementer_keeps_no_notes(self):
        for replies in ({"impl-2": None}, {"impl-2": {"status": "done", "notes": "no commit"}}, {"verify": None}):
            with self.subTest(replies=replies):
                result, _ = run(replies=dict({"plan": self.PLAN2}, **replies))
                self.assertNotIn("blocked", result["cont"])
                self.assertNotIn("decisions (", result["reason"])

    def test_a_new_decision_runs_a_planner_step_before_the_implementer(self):
        cont = self.stopped()["cont"]
        result, calls = self.resume(cont, decisions=self.DECISION)
        self.assertEqual(result["stage"], "done")
        self.assertEqual(labels(calls)[:4], ["setup", "renew-plan", "plan-task-revise", "impl-2"])
        step = next(c for c in calls if c["label"] == "plan-task-revise")
        self.assertEqual(step["agentType"], "planner")
        for needle in (self.DECISION, self.NOTES, "/g/task-2.md", "Task 2 (t2)", "fix only that task file in place", "criteria_edited",
                       "check every finding's claim in the first lookup message"):
            self.assertIn(needle, step["prompt"])
        # The implementer gets the task as it always does: the decision reached the task file, not its prompt.
        self.assertNotIn(self.DECISION, prompt(calls, "impl-2"))
        self.assertIn("exactly as its task file /g/task-2.md specifies", prompt(calls, "impl-2"))
        # No criterion changed, so the rules are not reviewed again (#819).
        self.assertNotIn("plan-rules-review", labels(calls))
        self.assertNotIn("plan-review", labels(calls))

    def test_a_used_decision_is_kept_and_the_blocked_member_is_gone(self):
        cont = self.stopped()["cont"]
        result, _ = self.resume(cont, replies={"verify": None}, decisions=self.DECISION)
        self.assertEqual(result["stage"], "verify")
        self.assertEqual(result["cont"]["decisions"], [self.DECISION])
        self.assertNotIn("blocked", result["cont"])
        # Blocked again after the revise: the new notes, and the same decision is no longer new.
        again, calls = self.resume(cont, replies={"impl-2": blocked("still wrong")}, decisions=self.DECISION)
        self.assertEqual((again["stage"], again["cont"]["blocked"]), ("task", {"task": 2, "notes": "still wrong"}))
        self.assertEqual(again["cont"]["decisions"], [self.DECISION])
        last, calls = self.resume(again["cont"], decisions=self.DECISION)
        self.assertEqual((last["stage"], calls), ("task", []))

    def test_a_revise_that_changes_a_criterion_gets_the_rules_review(self):
        cont = self.stopped()["cont"]
        changed = dict(self.PLAN2, acceptance=[{"id": "AC1", "text": "works with the fixture", "kind": "code"}], criteria_edited=["AC1"])
        result, calls = self.resume(cont, replies={"plan-task-revise": changed, "verify": None}, decisions=self.DECISION)
        names = labels(calls)
        self.assertLess(names.index("plan-task-revise"), names.index("plan-rules-review"))
        self.assertLess(names.index("plan-rules-review"), names.index("impl-2"))
        self.assertEqual(result["cont"]["plan"]["acceptance"][0]["text"], "works with the fixture")

    def test_no_new_decision_stops_before_any_agent_and_names_both_ways_out(self):
        held = self.stopped(decisions="An earlier answer.")["cont"]
        self.assertEqual(held["decisions"], ["An earlier answer."])
        for name, cont, args in (("none", self.stopped()["cont"], {}), ("blank", self.stopped()["cont"], {"decisions": "  "}),
                                 ("already held", held, {"decisions": "An earlier answer."})):
            with self.subTest(name):
                result, calls = self.resume(cont, **args)
                self.assertEqual(calls, [])
                self.assertEqual((result["stage"], result["task"], result["blocked"]), ("task", {"n": 2}, {"task": 2, "notes": self.NOTES}))
                self.assertEqual(result["cont"], cont)
                self.assertEqual(result["reason"], "task: not run again: this resume brings nothing new from the owner; "
                                                   f"task 2 blocked: {self.NOTES}{WAYS}")

    def test_an_amend_answers_a_blocked_task_without_a_planner(self):
        cont = dict(AMEND_CONT, blocked={"task": 2, "notes": self.NOTES})
        result, calls = run(args=dict(ARGS, cont=cont, amend=[AMEND_EDIT]), replies={"verify": None})
        self.assertEqual(labels(calls)[:4], ["setup", "renew-amend", "amend", "impl-2"])
        self.assertNotIn("plan-task-revise", labels(calls))
        self.assertNotIn("blocked", result["cont"])
        # With a decision as well, the amend is applied first and the planner works the decision in; one renew covers both.
        _, calls = run(args=dict(ARGS, cont=cont, amend=[AMEND_EDIT], decisions=self.DECISION), replies={"plan-task-revise": self.REVISED})
        self.assertEqual(labels(calls)[:5], ["setup", "renew-amend", "amend", "plan-task-revise", "impl-2"])

    def test_a_cont_from_before_the_blocked_member_runs_the_implementer_again(self):
        cont = {k: v for k, v in self.stopped()["cont"].items() if k != "blocked"}
        for args in ({}, {"decisions": self.DECISION}):
            with self.subTest(args=args):
                _, calls = self.resume(cont, **args)
                self.assertEqual(labels(calls)[:2], ["setup", "impl-2"])
                self.assertNotIn("plan-task-revise", labels(calls))

    def test_a_blocked_member_that_does_not_match_the_cont_is_ignored(self):
        base = self.stopped()["cont"]
        for name, cont in (("another task", dict(base, blocked={"task": 1, "notes": "x"})), ("not an object", dict(base, blocked="x")),
                           ("the task is done", dict(base, done=base["done"] + [{"n": 2, "commit": "c2"}])),
                           ("no partial", {k: v for k, v in base.items() if k != "partial"})):
            with self.subTest(name):
                _, calls = self.resume(cont)
                self.assertIn("setup", labels(calls))
                self.assertNotIn("plan-task-revise", labels(calls))

    def test_a_revise_that_fails_keeps_the_plan_the_notes_and_the_decision_unused(self):
        cont = self.stopped()["cont"]
        questions = [{"question": "Which fixture?", "options": ["The first one.", "The second one."]}]
        cases = (
            ("questions", {"status": "needs_user", "questions": questions}, "plan", True),
            ("malformed", {"status": "planned"}, "plan", False),
            ("a done task dropped", dict(self.REVISED, tasks=tasks(2)[1:]), "plan", False),
            ("rule findings left", dict(self.PLAN2, acceptance=self.PLAN2["acceptance"] + [criterion(EVIDENCE, lint=None)],
                                        criteria_edited=[]), "plan-review", False),
        )
        for name, reply, stage, asked in cases:
            with self.subTest(name):
                result, calls = self.resume(cont, replies={"plan-task-revise": reply, "plan-rules-revise": reply}, decisions=self.DECISION)
                self.assertEqual((result["stage"], result["step"]), (stage, "plan-task-revise"))
                self.assertNotIn("impl-2", labels(calls))
                self.assertEqual(result["cont"]["plan"], cont["plan"])
                self.assertIs(result["cont"]["plan_reviewed"], True)
                self.assertNotIn("plan_findings", result["cont"])
                self.assertEqual(result["cont"]["blocked"], dict(cont["blocked"], **({"asked": True} if asked else {})))
                self.assertEqual(result["cont"]["done"], cont["done"])
                if asked:
                    # The planner read the decision and asked on: it is kept, and the resume with the answer shows the planner both.
                    self.assertEqual(result["needs_user"], questions)
                    self.assertEqual(result["cont"]["decisions"], [self.DECISION])
                    for more in ({"decisions": "The first one."}, {}):
                        answer = {"verdict": "answered", "comment_id": 3, "questions": [], "decisions": "The first one."}
                        _, again = self.resume(result["cont"], replies={"owner-answer": answer}, **more)
                        for text in (self.DECISION, "The first one."):
                            self.assertIn(text, prompt(again, "plan-task-revise"))
                        self.assertIn("impl-2", labels(again))
                    continue
                self.assertNotIn("decisions", result["cont"])
                # The same resume tries the revise again.
                _, again = self.resume(result["cont"], decisions=self.DECISION)
                self.assertIn("plan-task-revise", labels(again))
                self.assertIn("impl-2", labels(again))

    def test_the_decision_rerun_runs_the_implementer_on_the_unchanged_task_file_with_no_planner(self):
        cont = self.stopped(decisions="An earlier answer.")["cont"]
        for word in ("rerun", " rerun\n"):
            with self.subTest(word=word):
                result, calls = self.resume(cont, replies={"verify": None}, decisions=word)
                self.assertEqual(labels(calls)[:2], ["setup", "impl-2"])
                self.assertNotIn("plan-task-revise", labels(calls))
                self.assertEqual(result["cont"]["decisions"], ["An earlier answer."])
                self.assertNotIn("blocked", result["cont"])
                self.assertNotIn("rerun", prompt(calls, "impl-2").split("exactly as its task file")[0].lower())
        # A stop of the rerun that is not a blocked implementer carries no blocked member: the old notes are answered.
        cut, _ = self.resume(cont, replies={"impl-2": {"status": "done", "notes": "no commit"}}, decisions="rerun")
        self.assertEqual((cut["stage"], cut["cont"]["partial"]), ("task", 2))
        self.assertNotIn("blocked", cut["cont"])
        # Blocked again: the new notes, and rerun works again (it is never a held decision).
        again, _ = self.resume(cont, replies={"impl-2": blocked("the token is still rejected")}, decisions="rerun")
        self.assertEqual(again["cont"]["blocked"], {"task": 2, "notes": "the token is still rejected"})
        self.assertIn("decisions rerun if the cause was outside the task file", again["reason"])
        _, calls = self.resume(again["cont"], decisions="rerun")
        self.assertEqual(labels(calls)[:2], ["setup", "impl-2"])
        # A longer text that only starts with the word is a decision like any other.
        _, calls = self.resume(cont, decisions="rerun it with the other fixture")
        self.assertIn("plan-task-revise", labels(calls))
        # Outside a blocked resume the word is still no decision: no planner ever reads it.
        fresh, calls = run(args=dict(ARGS, decisions="rerun"), replies={"verify": None})
        self.assertNotIn("decisions", fresh["cont"])
        self.assertNotIn("they are binding", prompt(calls, "plan"))

    def test_the_direct_lane_reruns_without_the_decision_sentence(self):
        first, _ = run(args=DIRECT, replies={"direct-impl": {"status": "blocked", "notes": self.NOTES}})
        result, calls = run(args=dict(ARGS, cont=first["cont"], decisions="rerun"), replies={"verify": None})
        self.assertEqual(labels(calls)[:2], ["setup", "direct-impl"])
        self.assertNotIn("That attempt returned blocked", prompt(calls, "direct-impl"))
        self.assertNotIn("decisions", result["cont"])
        self.assertNotIn("blocked", result["cont"])

    def test_a_revise_that_touches_a_done_task_or_removes_a_criterion_fails(self):
        two = dict(self.PLAN2, acceptance=self.PLAN2["acceptance"] + [{"id": "AC2", "text": "is fast", "kind": "code"}])
        first, _ = run(replies={"plan": two, "impl-2": blocked(self.NOTES)})
        cont = first["cont"]
        moved = [dict(tasks(2)[0], file="/g/task-1b.md"), tasks(2)[1]]
        cases = (("a done task's file", dict(two, tasks=moved), "done task(s) 1"),
                 ("a done task dropped", dict(two, tasks=tasks(2)[1:]), "done task(s) 1"),
                 ("a criterion removed", dict(two, acceptance=two["acceptance"][:1]), "removed the criteria AC2"))
        for name, reply, said in cases:
            with self.subTest(name):
                result, calls = self.resume(cont, replies={"plan-task-revise": dict(reply, criteria_edited=[])}, decisions=self.DECISION)
                self.assertEqual((result["stage"], result["step"]), ("plan", "plan-task-revise"))
                self.assertIn(said, result["reason"])
                self.assertNotIn("impl-2", labels(calls))
                self.assertEqual((result["cont"]["plan"], result["cont"]["blocked"]), (cont["plan"], cont["blocked"]))
                self.assertNotIn("decisions", result["cont"])
        # The blocked task itself may change, a task may be added, and a criterion's text may be restated.
        free = dict(two, tasks=[tasks(2)[0], dict(tasks(2)[1], file="/g/task-2b.md", title="t2 again"), tasks(3)[2]],
                    acceptance=[two["acceptance"][0], dict(two["acceptance"][1], text="answers within a second")], criteria_edited=["AC2"])
        result, calls = self.resume(cont, replies={"plan-task-revise": free, "verify": None}, decisions=self.DECISION)
        self.assertEqual(result["stage"], "verify")
        self.assertIn("/g/task-2b.md", prompt(calls, "impl-2"))
        self.assertIn("impl-3", labels(calls))

    def test_a_revise_that_moves_a_done_task_to_another_declared_branch_fails(self):
        cont = self.stopped()["cont"]
        moved = dict(self.PLAN2, branches=[dict(BR)], tasks=[dict(tasks(2)[0], branch="cand"), tasks(2)[1]], criteria_edited=[])
        result, calls = self.resume(cont, replies={"plan-task-revise": moved}, decisions=self.DECISION)
        self.assertEqual((result["stage"], result["step"]), ("plan", "plan-task-revise"))
        self.assertNotIn("branch_problems", result)
        self.assertIn("done task(s) 1", result["reason"])
        self.assertNotIn("impl-2", labels(calls))
        self.assertEqual(result["cont"]["plan"], cont["plan"])
        # The blocked task itself may move to a declared branch.
        free = dict(self.PLAN2, branches=[dict(BR)], tasks=[tasks(2)[0], dict(tasks(2)[1], branch="cand")], criteria_edited=[])
        _, calls = self.resume(cont, replies={"plan-task-revise": free}, decisions=self.DECISION)
        self.assertIn("impl-2", labels(calls))

    def test_a_failed_revise_leaves_no_prior_findings_in_the_cont(self):
        cont = self.stopped()["cont"]
        self.assertNotIn("prior_findings", cont)
        unlinted = dict(self.PLAN2, acceptance=self.PLAN2["acceptance"] + [criterion(EVIDENCE, lint=None)], criteria_edited=[])
        for reply in ({"status": "planned"}, {"status": "needs_user", "questions": [{"question": "q", "options": ["a."]}]}, unlinted):
            with self.subTest(reply=reply.get("status"), criteria=len(reply.get("acceptance", []))):
                result, _ = self.resume(cont, replies={"plan-task-revise": reply, "plan-rules-revise": reply}, decisions=self.DECISION)
                self.assertNotIn("prior_findings", result["cont"])
                self.assertIs(result["cont"]["plan_reviewed"], True)

    def test_a_revise_that_ends_in_a_rules_conflict_carries_it_and_keeps_the_decision(self):
        cont = self.stopped()["cont"]
        capped = dict(PLAN["acceptance"][0], id="AC5", text="the evaluation costs at most $5", metric=True)
        held = criterion(EVIDENCE, id="AC5", text="the evaluation costs at most $5", metric=True, verify_ac="AC5", verify_mode="observe")
        r1 = {"verdict": "findings", "findings": [{"severity": "important", "rule": "R1", "ac": "AC5", "summary": "a local evaluation is a code criterion"}]}
        replies = {"plan-task-revise": dict(self.PLAN2, acceptance=self.PLAN2["acceptance"] + [capped], criteria_edited=[]),
                   "plan-rules-revise": dict(self.PLAN2, acceptance=self.PLAN2["acceptance"] + [held]),
                   "plan-rules-review": [PASS_REPLY, r1]}
        result, calls = self.resume(cont, replies=replies, decisions=self.DECISION)
        self.assertEqual((result["stage"], result["step"]), ("plan-review", "plan-task-revise"))
        self.assertEqual((result["conflict"]["ac"], result["conflict"]["rules"]), ("AC5", ["R5", "R1"]))
        self.assertIn("the acceptance rules R5 and R1 conflict for AC5", result["reason"])
        self.assertNotIn("impl-2", labels(calls))
        self.assertEqual((result["cont"]["plan"], result["cont"]["blocked"]), (cont["plan"], cont["blocked"]))
        self.assertEqual(result["cont"]["decisions"], [self.DECISION])
        # The owner's classification is the new decision: the revise runs again and its planner reads both.
        _, again = self.resume(result["cont"], decisions="AC5 is a code criterion.")
        for text in (self.DECISION, "AC5 is a code criterion."):
            self.assertIn(text, prompt(again, "plan-task-revise"))
        self.assertIn("impl-2", labels(again))

    def test_a_failed_revise_restores_the_reorder_record(self):
        moved = [{"task": 2, "after": 1, "notes": "needed task 1"}]
        cont = dict(self.stopped()["cont"], reordered=moved)
        result, _ = self.resume(cont, replies={"plan-task-revise": {"status": "planned"}}, decisions=self.DECISION)
        self.assertEqual((result["stage"], result["cont"]["reordered"]), ("plan", moved))
        # An accepted revise is a new plan: it drops the record, as every new plan does.
        done, _ = self.resume(cont, replies={"verify": None}, decisions=self.DECISION)
        self.assertNotIn("reordered", done["cont"])

    def test_a_revise_that_asked_reads_the_owners_answer_on_its_resume(self):
        cont = dict(self.stopped()["cont"])
        cont["blocked"] = dict(cont["blocked"], asked=True)
        answer = {"verdict": "answered", "comment_id": 3, "questions": [], "decisions": "Which fixture? Chosen: The first one."}
        result, calls = self.resume(cont, replies={"owner-answer": answer, "verify": None})
        self.assertEqual(labels(calls)[:4], ["setup", "owner-answer", "plan-task-revise", "impl-2"])
        self.assertIn(answer["decisions"], prompt(calls, "plan-task-revise"))
        self.assertEqual(result["cont"]["decisions"], [answer["decisions"]])
        unanswered, calls = self.resume(cont)
        self.assertEqual(labels(calls), ["setup", "owner-answer"])
        self.assertEqual((unanswered["stage"], unanswered["cont"]["blocked"]), ("task", cont["blocked"]))
        self.assertIn("amend {file, find, replace}", unanswered["reason"])

    def test_a_lost_renew_before_the_revise_leaves_the_decision_new(self):
        cont = self.stopped()["cont"]
        result, calls = self.resume(cont, replies={"renew-plan": {"verdict": "error", "detail": "x"}}, decisions=self.DECISION)
        self.assertEqual(labels(calls), ["setup", "renew-plan", "renew-plan"][:len(calls)])
        self.assertNotIn("plan-task-revise", labels(calls))
        self.assertNotIn("decisions", result["cont"])
        self.assertEqual(result["cont"]["blocked"], cont["blocked"])

    def test_no_other_prompt_grows(self):
        _, calls = run(replies={"plan": self.PLAN2})
        for call in calls:
            for needle in ("returned blocked", "the owner then decided", "resume with decisions", self.DECISION):
                self.assertNotIn(needle, call["prompt"], call["label"])
        self.assertNotIn("plan-task-revise", labels(calls))

    def test_the_direct_lane_gives_the_decision_and_the_notes_to_its_implementer(self):
        reply = {"status": "blocked", "notes": self.NOTES}
        first, calls = run(args=DIRECT, replies={"direct-impl": reply})
        self.assertEqual((first["stage"], first["cont"]["blocked"], first["cont"]["partial"]), ("task", {"task": 1, "notes": self.NOTES}, 1))
        self.assertEqual(first["reason"], f"task: task 1 blocked: {self.NOTES}{DIRECT_WAYS}")
        self.assertNotIn("That attempt returned blocked", prompt(calls, "direct-impl"))
        unsettled, calls = run(args=dict(ARGS, cont=first["cont"]))
        self.assertEqual((unsettled["stage"], calls, unsettled["cont"]), ("task", [], first["cont"]))
        self.assertTrue(unsettled["reason"].endswith(DIRECT_WAYS), unsettled["reason"])
        self.assertNotIn("amend", unsettled["reason"])
        result, calls = run(args=dict(ARGS, cont=first["cont"], decisions=self.DECISION), replies={"verify": None})
        self.assertEqual(labels(calls)[:2], ["setup", "direct-impl"])
        self.assertNotIn("plan-task-revise", labels(calls))
        for needle in (self.DECISION, self.NOTES, "That attempt returned blocked"):
            self.assertIn(needle, prompt(calls, "direct-impl"))
        self.assertEqual(result["cont"]["decisions"], [self.DECISION])
        self.assertNotIn("blocked", result["cont"])


class CodexQuotaStopTest(unittest.TestCase):
    """#996: a codex-unavailable stop whose message names a usage or quota limit carries retry_after; any other is unchanged."""

    SITES = CodexUnavailableReasonTest.SITES

    def stop(self, args, label, raw):
        reply = {"available": False, "verdict": "pass", "findings": [], **({} if raw is None else {"raw_summary": raw})}
        result, _ = run(args=args, replies={label: reply})
        self.assertEqual(result["stage"], "codex-unavailable")
        return result

    def test_a_usage_limit_carries_its_reset_time_at_every_site(self):
        for args, label, _ in self.SITES:
            with self.subTest(label=label):
                result = self.stop(args, label, CodexUnavailableReasonTest.REASON)
                self.assertEqual(result["retry_after"], "Nov 12th, 2026 5:34 AM")
                self.assertEqual(result["details"], CodexUnavailableReasonTest.REASON)
                self.assertIn("cont", result)

    def test_the_reset_time_is_read_from_the_message_or_left_null(self):
        real = "You've hit your usage limit. Visit https://chatgpt.com/settings/usage to purchase more credits or try again at "
        for raw, want in (("runtime failure: usage limit reached, resets at 09:00 UTC on Friday. Buy credits.", "09:00 UTC on Friday"),
                          (real + "Nov 17th, 2026 7:09 AM.", "Nov 17th, 2026 7:09 AM"),
                          (real + "Nov 12th, 2026 5:34 p.m. Buy credits to go on.", "Nov 12th, 2026 5:34 p.m."),
                          (real + "5:34 A.M.", "5:34 A.M."),
                          ("You exceeded your current quota, please check your plan and billing details.", None),
                          ("You have exceeded your quota. Try again in 2 hours.", "2 hours"),
                          ("Quota exceeded for this workspace; try again in 3 days 4 hours", "3 days 4 hours"),
                          ("runtime failure: quota exceeded", None), ("You've hit your usage limit.", None)):
            with self.subTest(raw=raw):
                result = self.stop(ARGS, "final-codex", raw)
                self.assertIn("retry_after", result)
                self.assertEqual(result["retry_after"], want)

    def test_any_other_codex_failure_carries_no_retry_after(self):
        for raw in ("daemon rejected the slot; try again at 5 PM", "the run failed, and this is not a usage or quota limit",
                    "write failed: Disk quota exceeded; try again at 5 PM", "the quota of reviewers is one per packet", "runtime failure: the payload was malformed", "  ", None):
            with self.subTest(raw=raw):
                self.assertNotIn("retry_after", self.stop(ARGS, "plan-codex", raw))
        dead, _ = run(replies={"final-codex": None})
        self.assertNotIn("retry_after", dead)

    def test_the_codex_schema_and_prompts_are_unchanged(self):
        _, calls = run()
        for label in ("plan-codex", "final-codex"):
            self.assertEqual(set(schema_of(calls, label)["properties"]), {"available", "verdict", "findings", "raw_summary"})
            self.assertNotIn("quota", prompt(calls, label))
            self.assertNotIn("retry_after", prompt(calls, label))


if __name__ == "__main__":
    unittest.main()
