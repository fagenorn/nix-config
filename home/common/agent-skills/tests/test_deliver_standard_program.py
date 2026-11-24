"""deliver-standard.js control flow against stub agents (#618, #572 S1).

The Workflow program runs under node with stub agent(), parallel() and phase();
each scenario fixes some agents' replies and asserts the stop or the call sequence.
Run: just agent-workflow-tests
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from agent_tools.delivery import verify_slot

sys.path.insert(0, str(Path(__file__).resolve().parent))
from clerk_tools import outside_clerk_tools, granted_tools  # noqa: E402
from program_harness import server_for  # noqa: E402

REPO_ROOT = Path(__file__).parents[4]
PROGRAM = REPO_ROOT / "home/common/claude-code/skills/deliver-standard/deliver-standard.js"
HARNESS = Path(__file__).with_name("deliver_standard_harness.mjs")
SHA = "a" * 40
ISSUE_BRANCH_ARGV = re.compile(r"\bissue-branch --repo-root (\S+) --issue (\d+)\b")
ARGS = {"repo_root": "/r", "issue": 9, "session_id": "s1"}
HOLDER = "h1/session-s1"
# #1372: a security task keeps the Codex plan review in every default run; a small plan of no security task skips it.
PLAN = {
    "status": "planned", "plan_root": "/g/plan.md",
    "acceptance": [{"id": "AC1", "text": "works", "kind": "code"}],
    "tasks": [{"n": 1, "title": "one", "file": "/g/task-1.md", "risk": "security"}],
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
# #1019: the one sentence every review step gets, the same in both programs.
READ_ONLY = ("Never check out, switch, reset or stash in the worktree: read another commit with git show.")
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


# #1281: an evidence criterion whose verify member runs a committed script; the plan commits the script, so its lint is the one a plan-time check gives.
SCRIPTED = criterion(EVIDENCE, text="after the first switch that includes the merge, the host holds the generated files",
                     verify_run={"script": "scripts/count-generated"},
                     lint=refused(("checks[0].run.script", "not_committed")))
SCRIPTED_PLAN = with_criteria(SCRIPTED, scripts=["scripts/count-generated"])
MANIFEST = REPO_ROOT / "home/common/agent-skills/platform-manifest.json"
FIXTURE = REPO_ROOT / "home/common/agent-skills/evals/fixture-repo"
HERMETIC_GIT = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
                "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
                "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}
SCRUBBED = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
            "GIT_COMMON_DIR", "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_CEILING_DIRECTORIES")


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


class Raw(dict):
    """A fixture reply named() sends exactly as written: its findings get no default subject."""


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
        if isinstance(value, Raw):
            return dict(value)
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
    out = server_for(node).run(HARNESS, PROGRAM, scenario)
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


def checks_of(calls):
    """The checks the hold prompt tells the clerk to post: the JSON of its `Checks: ` line."""
    for line in prompt(calls, "hold").splitlines():
        if line.startswith("Checks: "):
            return json.loads(line[len("Checks: "):])
    raise AssertionError("no Checks payload")


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
    "pr": ({"pr", "head"}, {"renew": RENEW_READ,
                            "green": {"state", "head", "behind", "required", "passed", "failing", "pending", "details"}}),
    "land-take": ({"behind"}, {"renew": RENEW_READ, "lock": {"verdict"}}),
    "merge": ({"merged", "behind", "merge_commit", "notes"}, {"renew": RENEW_READ, "lock": {"verdict"}}),
    "impl-1": ({"status", "start_head", "commit", "notes"}, {"renew": RENEW_READ}),
    "hold": (set(), {"release": {"verdict", "detail"}}),
    "setup": ({"ok", "reason", "details", "host", "slug", "integration_branch", "default_branch", "branch",
               "worktree_path", "head", "merged_pr", "merged_refs", "merged_heads", "dirty", "duplicate_pr", "since_reviewed", "branch_heads",
               "existing", "unset_env", "merge_strategy", "delete_branch", "review", "review_state", "knowledge",
               "verification", "verification_before_pull_request", "holder", "acquire", "claim", "answer", "renew", "live_fault"},
              {"existing": {"local_branch", "remote_branch", "worktree", "dirty", "status"},
               "merged_refs[]": {"number", "closes"}, "merged_heads[]": {"number", "commits"},
               "review": {"code", "plan"}, "review_state": {"code", "plan"},
               "knowledge": {"standards", "hints", "rejections"},
               "verification[]": {"id", "argv", "cwd", "when_changed", "skip_reason", "pre_commit"}, "verification_before_pull_request[]": {"id", "argv", "cwd", "when_changed", "skip_reason"},
               "acquire": {"verdict", "by", "detail", "transient"}, "claim": {"ok", "reason", "worktree", "base_sha", "plan_dir"},
               "answer": {"verdict", "comment_id", "questions", "decisions"}, "renew": RENEW_READ}),
}


def member(schema, name):
    """The object schema of a member: an array member's items, a nullable member's object branch."""
    if name.endswith("[]"):
        return schema["properties"][name[:-2]]["items"]
    return object_branch(schema["properties"][name])


def green_read(head=SHA, **over):
    """The pr call's green read: every check passed at the head, which the base has not passed."""
    return dict({"state": "passed", "head": head, "behind": False, "required": ["ci"], "passed": ["ci"]}, **over)


def red_read(read):
    """A checks reply of the old shape as the pr call's read of a head whose base has not moved past it."""
    return dict({"behind": False}, **read)


# The lease is taken once the head is green; a take that answers behind sends the landing through its one sync.
TAKE_BEHIND = {"lock": {"verdict": "acquired", "lock_sha": SHA}, "behind": True}


class FoldTest(unittest.TestCase):
    """#716: folded bookkeeping steps return nested results that keep every field the program reads."""

    def test_folded_schemas_keep_every_read_field(self):
        _, calls = run()
        renew = member(schema_of(calls, "verify"), "renew")
        merge = "d" * 40
        _, moved_calls = run(replies={"checks-2": {"state": "passed", "passed": ["ci"], "head": merge}, "land-take": TAKE_BEHIND},
                             patch={"sync-1": {"merge_commit": merge}})
        lock = member(schema_of(moved_calls, "checks-2"), "lock")
        for label, (top, nested) in FOLDED_READ.items():
            with self.subTest(label=label):
                schema = schema_of(calls, label)
                self.assertLessEqual(top, set(schema["properties"]))
                for name, fields in nested.items():
                    branch = member(schema, name)
                    folded = label == "setup" and name in ("answer", "renew")
                    if name in ("acquire", "claim", "lock", "release", "green") or folded:
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

    def test_a_pr_head_that_moved_stops_before_any_lock_command_and_releases_nothing(self):
        moved = "c" * 40
        result, calls = run(patch={"pr": {"head": moved}})
        self.assertEqual(result["stage"], "head-moved")
        names = labels(calls)
        self.assertEqual(names[names.index("pr"):], ["pr"])
        self.assertNotIn("forge-claim land", prompt(calls, "pr"))
        self.assertNotIn("lock_unreleased", result)
        # A non-holding verdict leaves nothing to release.
        result, calls = run(replies={"land-take": {"lock": {"verdict": "held_by", "by": "h2/b9"}, "behind": False}})
        self.assertEqual(result["stage"], "land-contended")
        self.assertNotIn("land-unlock", labels(calls))

    def test_a_lost_folded_lock_reply_still_releases_the_lock(self):
        release = f"forge-claim land release --repo owner/repo --branch dev --sha {SHA}\n"
        for reply in (None, "throw"):
            # The pr call asks for no lock: a lost reply leaves nothing to release.
            lost, calls = run(replies={"pr": reply})
            self.assertEqual(labels(calls)[-1], "pr")
            for label, stage in (("land-take", "land-lock"), ("merge", "merge")):
                with self.subTest(label=label, reply=reply):
                    result, calls = run(replies={label: reply})
                    names = labels(calls)
                    self.assertEqual(names[names.index(label):], [label, "land-unlock"])
                    self.assertIn(release, prompt(calls, "land-unlock"))
                    self.assertNotIn("When it prints not_held", prompt(calls, "land-unlock"))
                    if reply is None:
                        self.assertEqual(result["stage"], stage)
                        self.assertEqual(result["cont"], ship_cont())
                    else:
                        self.assertIsNone(result)
        # A move lock that never answered: the release tries the old sha, then the move target.
        merge = "d" * 40
        moved = {"replies": {"land-take": TAKE_BEHIND}, "patch": {"sync-1": {"merge_commit": merge}}}
        for reply in (None, "throw", {"verdict": "error", "detail": "gh failed"}):
            with self.subTest(move=reply):
                lost = reply if reply in (None, "throw") else {"lock": reply}
                _, calls = run(replies=dict(moved["replies"], **{"checks-2": lost}), patch=moved["patch"])
                text = prompt(calls, "land-unlock")
                self.assertIn(release, text)
                self.assertIn(f"When it prints not_held with lock_sha {merge}, run alone and exactly: "
                              f"forge-claim land release --repo owner/repo --branch dev --sha {merge}", text)
                self.assertEqual(labels(calls).count("land-unlock"), 1)
        # A definitive answer: a move refused with another verdict leaves only the old sha to release.
        _, calls = run(replies=dict(moved["replies"], **{"checks-2": {"lock": {"verdict": "land-contended", "lock_sha": "c" * 40}}}),
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
                         ["pr", "land-take", "merge", "checks-2", "merge", "hold", "close-out"])
        text = prompt(calls, "merge")
        self.assertIn("Only when lock's verdict is already_held or moved", text)
        self.assertLess(text.index(f"forge-claim land acquire --repo owner/repo --branch dev --sha {SHA} --lease\n"),
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
               "renew-final-review", "final-codex", "final-1", "verify", "pr", "land-take",
               "merge", "hold", "close-out"]


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
                              "pr": {"head": head, "green": green_read(head)}})
        merge = prompt(calls, "merge")
        self.assertIn(f"unset GH_TOKEN && gh pr merge 42 --repo owner/repo --squash "
                      f"--match-head-commit {head}\n", merge)
        self.assertNotIn("--delete-branch", merge)
        self.assertNotIn("GITHUB_TOKEN", PROGRAM.read_text(encoding="utf-8"))

    def test_non_code_criterion_holds_the_issue_open(self):
        plan = dict(PLAN, acceptance=PLAN["acceptance"] + [EVIDENCE])
        result, calls = run(replies={"plan": plan}, patch={"setup": {"integration_branch": "main"},
                                                            "close-out": {"issue_state": "OPEN"}})
        self.assertEqual(result["stage"], "done")
        self.assertIn("Refs #9", prompt(calls, "pr"))
        self.assertEqual(labels(calls)[-4:], ["merge", "hold-draft", "hold", "close-out"])
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

    def test_on_without_a_plan_review_capability_keeps_the_full_rubric(self):
        _, calls = run(args=SIZED, patch={"setup": {"review_state": {"code": "available", "plan": "unsupported"}}})
        self.assertNotIn("plan-codex", labels(calls))
        text = prompt(calls, "plan-review")
        self.assertIn(FULL_RUBRIC, text)
        self.assertNotIn(CODEX_OWNS, text)


class SmallPlanCodexSkipTest(unittest.TestCase):
    """#1372: a small plan (at most three tasks, none of risk security) skips the Codex plan review."""

    SKIP = "codex plan review: skipped, a small plan ({} of at most 3 tasks, none of risk security)"
    MIXED = [tasks(2)[0], dict(tasks(2)[1], risk="security")]
    UNAVAILABLE = {"available": False, "verdict": "pass", "findings": []}

    def small(self, n=2):
        return dict(PLAN, tasks=tasks(n))

    def test_a_small_plan_runs_no_codex_plan_review_and_logs_why(self):
        mixed_risks = [dict(task, risk=risk) for task, risk in zip(tasks(3), ("mechanical", "low", "standard"))]
        for task_list in (tasks(1), tasks(2), tasks(3, "low"), mixed_risks):
            with self.subTest(tasks=[t["risk"] for t in task_list]):
                out = run_out(replies={"plan": dict(PLAN, tasks=task_list)})
                self.assertEqual(out["result"]["stage"], "done")
                self.assertNotIn("plan-codex", labels(out["calls"]))
                self.assertIn("plan-review", labels(out["calls"]))
                self.assertEqual([l for l in out["logs"] if l.startswith("codex plan review: ")],
                                 [self.SKIP.format(len(task_list))])

    def test_a_small_plan_never_stops_for_an_unavailable_codex(self):
        result, calls = run(replies={"plan": self.small(2), "plan-codex": self.UNAVAILABLE})
        self.assertEqual(result["stage"], "done")
        self.assertNotIn("plan-codex", labels(calls))

    def test_a_fourth_task_or_a_security_task_keeps_the_codex_plan_review(self):
        for task_list in (tasks(4), tasks(5, "low"), tasks(1, "security"), self.MIXED):
            with self.subTest(tasks=[t["risk"] for t in task_list]):
                out = run_out(replies={"plan": dict(PLAN, tasks=task_list)})
                self.assertEqual(out["result"]["stage"], "done")
                self.assertEqual(labels(out["calls"]).count("plan-codex"), 1)
                self.assertIn("codex plan review: 0 blocking findings", out["logs"])
                self.assertFalse([l for l in out["logs"] if "codex plan review: skipped" in l])

    def test_sizing_on_with_a_skipped_codex_plan_review_keeps_the_full_rubric(self):
        _, calls = run(args=SIZED, replies={"plan": self.small(2)})
        text = prompt(calls, "plan-review")
        self.assertNotIn("plan-codex", labels(calls))
        self.assertIn(FULL_RUBRIC, text)
        self.assertNotIn(CODEX_OWNS, text)

    def test_a_resumed_unreviewed_small_plan_skips_too(self):
        cont = {"setup": {"ok": True, "worktree": "/r/.wt/w-issue-9-x", "branch": "issue-9-x", "plan_dir": "/g",
                          "holder": HOLDER, "base_sha": SHA},
                "plan": self.small(2), "plan_reviewed": False, "done": []}
        result, calls = run(args=dict(ARGS, cont=cont))
        self.assertEqual(result["stage"], "done")
        self.assertIn("plan-review", labels(calls))
        self.assertNotIn("plan-codex", labels(calls))

    def test_no_skip_line_without_a_configured_codex_plan_review(self):
        out = run_out(replies={"plan": self.small(2)},
                      patch={"setup": {"review_state": {"code": "available", "plan": "unsupported"}}})
        self.assertNotIn("plan-codex", labels(out["calls"]))
        self.assertFalse([l for l in out["logs"] if l.startswith("codex plan review: ")])

    def test_a_small_plan_keeps_the_codex_diff_review(self):
        _, calls = run(replies={"plan": self.small(2)})
        stopped, _ = run(replies={"plan": self.small(2), "final-codex": self.UNAVAILABLE})
        self.assertEqual(labels(calls).count("final-codex"), 1)
        self.assertNotIn("plan-codex", labels(calls))
        call = next(c for c in calls if c["label"] == "final-codex")
        self.assertEqual((call["agentType"], call["effort"]), ("clerk", "high"))
        self.assertEqual(set(schema_of(calls, "final-codex")["properties"]), {"available", "verdict", "findings", "raw_summary"})
        self.assertEqual((stopped["stage"], stopped["step"]), ("codex-unavailable", "code"))

    FINDING = {"verdict": "findings", "findings": [{"severity": "important", "summary": "gap"}]}

    def grown(self, task_list):
        return dict(PLAN, tasks=task_list, criteria_edited=[])

    def test_an_amended_unreviewed_small_plan_keeps_the_codex_plan_review(self):
        cont = dict(AMEND_CONT, plan=self.small(2), plan_reviewed=False, done=[])
        out = run_out(args=dict(ARGS, cont=cont, amend=[AMEND_EDIT]))
        names = labels(out["calls"])
        self.assertEqual(out["result"]["stage"], "done")
        self.assertLess(names.index("amend"), names.index("plan-codex"))
        self.assertFalse([l for l in out["logs"] if "codex plan review: skipped" in l])

    OPEN = {"close-out": {"issue_state": "OPEN"}}

    def kept_small(self, revised_tasks):
        """A two-task plan skips Codex, the rules revise gives it revised_tasks, and the rules re-review stops the run on a rule finding."""
        rule = PlanRulesTest.RULE_FINDING
        plan = with_criteria(HUMAN, tasks=tasks(2))
        first, _ = run(replies={"plan": plan, "plan-revise": plan, "plan-rules-revise": with_criteria(HUMAN, tasks=revised_tasks),
                                "plan-review": rule, "plan-rules-review": rule})
        self.assertEqual(first["stage"], "plan-review")
        self.assertTrue(first["cont"]["codex_plan_skipped"])
        return first["cont"]

    def test_a_rules_only_resume_runs_the_codex_plan_review_a_revise_made_due(self):
        grown = with_criteria(HUMAN, tasks=tasks(2) + [dict(tasks(3)[2], risk="security")])
        for name, revised in (("fourth", tasks(4)), ("security", grown["tasks"])):
            with self.subTest(name):
                cont = self.kept_small(revised)
                result, calls = run(args=dict(ARGS, cont=cont), replies={"plan-rules-revise": with_criteria(HUMAN, tasks=revised)}, patch=self.OPEN)
                names = labels(calls)
                self.assertEqual(result["stage"], "done")
                self.assertEqual(names.count("plan-codex"), 1)
                self.assertLess(names.index("plan-rules-review"), names.index("plan-codex"))
                self.assertLess(names.index("plan-codex"), names.index("impl-1"))

    def test_a_rules_only_resume_of_a_plan_that_stays_small_runs_no_codex_plan_review(self):
        cont = self.kept_small(tasks(3))
        result, calls = run(args=dict(ARGS, cont=cont), replies={"plan-rules-revise": with_criteria(HUMAN, tasks=tasks(3))}, patch=self.OPEN)
        self.assertEqual(result["stage"], "done")
        self.assertNotIn("plan-codex", labels(calls))

    def test_a_rules_only_resume_with_an_amend_runs_the_codex_plan_review_it_skipped(self):
        cont = self.kept_small(tasks(2))
        cont = dict(cont, setup=dict(cont["setup"], plan_dir="/g"))
        replies = {"plan-rules-revise": with_criteria(HUMAN, tasks=tasks(2))}
        stopped, calls = run(args=dict(ARGS, cont=cont, amend=[AMEND_EDIT]),
                             replies=dict(replies, **{"plan-codex": self.UNAVAILABLE}))
        names = labels(calls)
        self.assertEqual((stopped["stage"], stopped["step"]), ("codex-unavailable", "plan"))
        self.assertLess(names.index("amend"), names.index("plan-codex"))
        self.assertNotIn("impl-1", names)
        self.assertFalse(stopped["cont"]["plan_reviewed"])
        # The stop keeps the review owed: a resume without the amend, on a plan that reads small again, still runs it.
        result, calls = run(args=dict(ARGS, cont=stopped["cont"]), patch=self.OPEN)
        names = labels(calls)
        self.assertEqual(result["stage"], "done")
        self.assertEqual(names.count("plan-codex"), 1)
        self.assertLess(names.index("plan-codex"), names.index("impl-1"))

    def test_an_amend_keeps_the_codex_plan_review_owed_through_a_stop_before_it_passes(self):
        # (a) A kept plan with no rules revise spent: the amend resume leaves a rule finding and stops at plan-review, with the plan kept and
        # before any Codex call; the next resume has no amend.
        cont = self.kept_small(tasks(2))
        cont = dict(cont, setup=dict(cont["setup"], plan_dir="/g"), plan_findings=dict(cont["plan_findings"], rounds=0))
        stopped, calls = run(args=dict(ARGS, cont=cont, amend=[AMEND_EDIT]),
                             replies={"plan-rules-revise": with_criteria(HUMAN, tasks=tasks(2)), "plan-rules-review": PlanRulesTest.RULE_FINDING})
        self.assertEqual(stopped["stage"], "plan-review")
        self.assertTrue(stopped["amended"])
        self.assertFalse(stopped["cont"]["plan_reviewed"])
        self.assertNotIn("plan-codex", labels(calls))
        self.assertTrue(stopped["cont"]["codex_plan_owed"])
        result, calls = run(args=dict(ARGS, cont=stopped["cont"]), replies={"plan-rules-revise": with_criteria(HUMAN, tasks=tasks(2))}, patch=self.OPEN)
        names = labels(calls)
        self.assertEqual(result["stage"], "done")
        self.assertEqual(names.count("plan-codex"), 1)
        self.assertLess(names.index("plan-codex"), names.index("impl-1"))

    def test_an_amend_on_an_unreviewed_plan_keeps_the_codex_plan_review_owed_through_each_stop(self):
        kept = self.kept_small(tasks(2))
        base = {k: v for k, v in kept.items() if k not in ("plan_findings", "codex_plan_skipped")}
        base = dict(base, setup=dict(base["setup"], plan_dir="/g"))
        silent_reviewer = {"plan-review": None}
        for name, replies, stage in (("codex unavailable", {"plan-codex": self.UNAVAILABLE}, "codex-unavailable"),
                                     ("silent claude reviewer", silent_reviewer, "plan-review")):
            with self.subTest(name):
                stopped, calls = run(args=dict(ARGS, cont=base, amend=[AMEND_EDIT]), replies=replies)
                self.assertEqual(stopped["stage"], stage)
                self.assertFalse(stopped["cont"]["plan_reviewed"])
                self.assertTrue(stopped["cont"]["codex_plan_owed"])
                result, calls = run(args=dict(ARGS, cont=stopped["cont"]), patch=self.OPEN)
                names = labels(calls)
                self.assertEqual(result["stage"], "done")
                self.assertEqual(names.count("plan-codex"), 1)
                self.assertLess(names.index("plan-codex"), names.index("impl-1"))
        # A passed review clears the mark: the cont of a run that reaches the tasks no longer carries it.
        out = run_out(args=dict(ARGS, cont=base, amend=[AMEND_EDIT]), patch=self.OPEN)
        self.assertEqual(out["result"]["stage"], "done")
        self.assertNotIn("codex_plan_owed", out["result"].get("cont", {}))

    def test_a_late_codex_finding_on_a_rules_only_resume_stops_at_plan_review(self):
        cont = self.kept_small(tasks(4))
        codex = {"available": True, "verdict": "findings", "findings": [{"severity": "important", "summary": "bad"}]}
        result, calls = run(args=dict(ARGS, cont=cont),
                            replies={"plan-rules-revise": with_criteria(HUMAN, tasks=tasks(4)), "plan-codex": codex})
        self.assertEqual(result["stage"], "plan-review")
        self.assertEqual([f["summary"] for f in result["findings"]], ["bad"])
        self.assertFalse(result["cont"]["plan_reviewed"])
        self.assertNotIn("impl-1", labels(calls))

    def test_a_revise_that_leaves_the_plan_small_runs_no_codex_plan_review(self):
        out = run_out(replies={"plan": self.small(2), "plan-review": self.FINDING, "plan-revise": self.grown(tasks(3))})
        self.assertEqual(out["result"]["stage"], "done")
        self.assertNotIn("plan-codex", labels(out["calls"]))

    def test_a_revise_that_leaves_the_plan_not_small_runs_the_codex_plan_review_on_it(self):
        added = tasks(2) + [dict(tasks(3)[2], risk="security")]
        for name, task_list in (("security", added), ("fourth", tasks(4))):
            with self.subTest(name):
                out = run_out(replies={"plan": self.small(2), "plan-review": self.FINDING, "plan-revise": self.grown(task_list)})
                names = labels(out["calls"])
                self.assertEqual(out["result"]["stage"], "done")
                self.assertEqual(names.count("plan-codex"), 1)
                self.assertGreater(names.index("plan-codex"), names.index("plan-revise"))
                self.assertIn("codex plan review: 0 blocking findings", out["logs"])
                self.assertEqual(names.count("impl-%d" % len(task_list)), 1)

    def test_the_codex_plan_review_of_a_grown_plan_stops_on_unavailable_and_on_findings(self):
        grown = self.grown(tasks(4))
        base = {"plan": self.small(2), "plan-review": self.FINDING, "plan-revise": grown}
        stopped, calls = run(replies=dict(base, **{"plan-codex": self.UNAVAILABLE}))
        self.assertEqual((stopped["stage"], stopped["step"]), ("codex-unavailable", "plan"))
        self.assertNotIn("impl-1", labels(calls))
        codex = {"available": True, "verdict": "findings", "findings": [{"severity": "important", "summary": "bad"}]}
        stopped, calls = run(replies=dict(base, **{"plan-codex": codex}))
        self.assertEqual(stopped["stage"], "plan-review")
        self.assertEqual([f["summary"] for f in stopped["findings"]], ["bad"])
        self.assertFalse(stopped["cont"]["plan_reviewed"])
        self.assertNotIn("impl-1", labels(calls))


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

    REMOVALS = ("For a removal run only the tests that pin it, through the runner's filter, as an incremental build: never the suite, "
                "never a clean rebuild; removals that are independent may be made and checked in one script, and a run of zero tests confirms "
                "nothing.")
    RESUMED = ("and make sure every test was seen failing first; of the removals, make only those not already made against the final "
               "result; start_head is")

    def test_the_implementer_prompt_still_demands_red_first_and_a_mutation_check(self):
        _, calls = run()
        impl = prompt(calls, "impl-1")
        self.assertIn("write the failing test first and see it fail", impl)
        # #1002: one removal per acceptance criterion, checked by the tests that pin it alone.
        self.assertIn("then once for each acceptance criterion the task covers (not for each test or branch; at least once when the task adds a test) temporarily "
                      "remove the code "
                      "that satisfies it and confirm the tests that pin it fail, restore, and commit only this task's files", impl)
        self.assertEqual(impl.count(self.REMOVALS), 1)
        # How to run a removal is the one sentence the prompt grew by.
        self.assertEqual((self.REMOVALS.count(". "), self.REMOVALS[-1]), (0, "."))
        for gone in ("for each new test", "mutation checks"):
            self.assertNotIn(gone, impl)

    def test_a_resumed_implementer_makes_only_the_removals_not_already_made(self):
        stopped, _ = run(replies={"impl-1": {"status": "blocked", "notes": "no"}})
        _, calls = run(args=dict(ARGS, cont=stopped["cont"], decisions="rerun"))
        impl = prompt(calls, "impl-1")
        self.assertIn(self.RESUMED, impl)
        self.assertNotIn("mutation checks still hold", impl)
        direct = PROGRAM.read_text(encoding="utf-8")
        # The direct lane and the live-fault lane (#1433) each build the paragraph, and the standard task prompt does.
        self.assertEqual(direct.count(self.RESUMED.replace(" start_head is", "")), 3)

    def test_no_implementer_schema_asks_for_mutation_checked(self):
        """#1002: nothing read the member, so no schema asks for it: not here, not in deliver-batch, not in the harness fixture."""
        _, calls = run()
        self.assertNotIn("mutation_checked", json.dumps([c.get("schema") for c in calls]))
        for path in (PROGRAM, PROGRAM.parent / "deliver-batch.js", HARNESS):
            self.assertNotIn("mutation_checked", path.read_text(encoding="utf-8"), path.name)

    def test_the_direct_lane_skill_carries_the_bound_and_the_filtered_run(self):
        skill = (REPO_ROOT / "home/common/agent-skills/skills/deliver-direct/SKILL.md").read_text(encoding="utf-8")
        self.assertIn("Once per criterion, remove its code: its filtered tests, no clean build, fail; zero run fails.", skill)
        self.assertNotIn("Remove each new code branch in turn", skill)
        _, calls = run(args=dict(ARGS, lane="direct"))
        self.assertIn("follow its step 3 exactly", prompt(calls, "direct-impl"))


class ProvingTestFirstTest(unittest.TestCase):
    """#1384: the planner names each task's one proving test first, and the plan review checks it."""

    PLANNERS = ("plan", "plan-revise", "plan-rules-revise", "plan-branch-revise", "plan-task-revise")

    @staticmethod
    def constant(name):
        found = re.search(rf"const {name} = `([^`]*)`", PROGRAM.read_text(encoding="utf-8"))
        if found is None:
            raise AssertionError(f"{name} is not a shared constant")
        return found.group(1)

    def test_every_planner_prompt_asks_for_the_proving_test_first_and_no_other_prompt_does(self):
        ask = self.constant("PROVING_TEST")
        seen = set()
        for call in all_calls():
            label = call["label"]
            if label in self.PLANNERS:
                self.assertIn(ask, call["prompt"], label)
                seen.add(label)
            else:
                self.assertNotIn(ask, call["prompt"], label)
        self.assertEqual(seen, set(self.PLANNERS))
        self.assertEqual(PROGRAM.read_text(encoding="utf-8").count(ask), 1)

    def test_the_plan_review_and_the_planner_self_check_carry_the_proving_finding_in_both_rubrics(self):
        finding = self.constant("PROVING_FINDING")
        full_rubric = self.constant("PLAN_RUBRIC")
        sized_rubric = self.constant("PLAN_RUBRIC_SIZED")
        owns = self.constant("PLAN_CODEX_OWNS")
        _, full = run()
        _, sized = run(args=SIZED)
        full_text = prompt(full, "plan-review")
        sized_text = prompt(sized, "plan-review")
        plan = prompt(full, "plan")
        self.assertLess(full_text.index(full_rubric), full_text.index(finding))
        self.assertLess(sized_text.index(sized_rubric), sized_text.index(finding))
        self.assertLess(sized_text.index(finding), sized_text.index(owns))
        self.assertLess(plan.index(full_rubric), plan.index(finding))
        for call in all_calls():
            if finding in call["prompt"]:
                self.assertIn(call["label"], self.PLANNERS + ("plan-review",))
        self.assertEqual(PROGRAM.read_text(encoding="utf-8").count(finding), 1)


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
                                 f"concrete failing input. No style notes. Do not edit anything.\n{READ_ONLY}\n{REPLY_ALONE}")
                self.assertEqual(prompt(calls, "rereview-1-1"), f"{head}\nRe-review only these previously reported findings for "
                                 f"task 1 against the fix: git -C {self.WT} diff c0ffee..f1c0de; the implementer's notes: ok. "
                                 'Findings: [{"severity":"important","summary":"bug on the candidate","failing_input":"x"}]. Report any finding still '
                                 f"unresolved and any new Important or Critical defect the fix introduced.\n{READ_ONLY}\n{REPLY_ALONE}")
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

    def test_codex_code_review_unavailable_stops(self):
        result, _ = run(replies={"final-codex": {"available": False, "verdict": "pass", "findings": []}})
        self.assertEqual((result["stage"], result["step"]), ("codex-unavailable", "code"))

    def test_codex_finding_drives_the_fix_wave(self):
        codex = {"available": True, "verdict": "findings",
                 "findings": [{"severity": "important", "summary": "edge", "failing_input": "x"}]}
        _, calls = run(replies={"plan": dict(PLAN, tasks=tasks(2)), "final-codex": codex})
        self.assertIn("edge", prompt(calls, "fix-wave"))
        self.assertIn("fix-wave-review", labels(calls))
        self.assertNotIn("plan-codex", labels(calls))

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


def slotted(entries, live=False):
    """The entries as a verification prompt holds them: each argv behind verify-slot (#1383), with --live in the live lane (#1434)."""
    lead = ["verify-slot", "run", "--wait-limit", "600", *(["--live"] if live else []), "--"]
    return json.dumps([dict(e, argv=[*lead, *e["argv"]]) for e in entries], separators=(",", ":"))
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
        self.assertIn(slotted(TWO_IDS), prompt(calls, "verify-2"))
        self.assertEqual(result["verify"], BOTH_GREEN["results"])

    def test_a_whitespace_only_fix_reruns_only_the_failed_id_and_carries_the_pass(self):
        result, calls = self.scenario(WS_ONLY)
        verify2 = prompt(calls, "verify-2")
        self.assertIn(slotted([TWO_IDS[0]]), verify2)
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
        self.assertIn("Rerun each failed command below once, whole and exactly as its argv below is written, and never "
                      "a second time once it has run, whatever its outcome;", rerun)
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
        self.assertIn(slotted([TWO_IDS[1]]), rerun)
        self.assertNotIn(slotted(TWO_IDS), rerun)
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


class VerifySlotTest(unittest.TestCase):
    """#1383: each verification command runs inside a host verify slot, and a no-slot attempt is not a run."""

    BUILD = {"id": "build", "argv": ["make", "build"], "cwd": "."}

    def test_the_verification_runs_each_declared_command_inside_a_verify_slot(self):
        _, calls = run()
        p = prompt(calls, "verify")
        self.assertIn(slotted([self.BUILD]), p)
        self.assertNotIn('"argv":["make","build"]', p)

    def test_a_live_lane_verification_waits_ahead_of_ordinary_runs(self):
        _, calls = run(args=ARGS, patch=LIVE_PATCH)
        p = prompt(calls, "verify")
        self.assertIn(slotted([self.BUILD], live=True), p)

    def test_an_ordinary_lane_verification_takes_no_priority(self):
        for args in (ARGS, dict(ARGS, lane="direct")):
            with self.subTest(lane=args.get("lane")):
                _, calls = run(args=args)
                p = prompt(calls, "verify")
                self.assertIn(slotted([self.BUILD]), p)
                self.assertNotIn('"--live"', p)

    def test_the_rerun_and_the_next_verification_run_inside_a_verify_slot(self):
        _, calls = run(replies={"verify": VerifyRerunTest.OUTSIDE, "verify-rerun-1": VerifyRerunTest.OUTSIDE})
        for label in ("verify-rerun-1", "verify-2"):
            with self.subTest(label=label):
                self.assertIn(slotted([self.BUILD]), prompt(calls, label))

    def test_every_verification_prompt_names_the_no_slot_line_and_the_attempts(self):
        _, calls = run(replies={"verify": VerifyRerunTest.OUTSIDE, "verify-rerun-1": VerifyRerunTest.GREEN})
        for label in ("verify", "verify-rerun-1"):
            with self.subTest(label=label):
                p = prompt(calls, label)
                self.assertIn(verify_slot.NO_SLOT_LINE.format(limit=600), p)
                self.assertIn(f"exits {verify_slot.NO_SLOT_EXIT}", p)
                self.assertIn("12 attempts", p)
                self.assertIn("does not count as a run", p)

    def test_the_cached_contract_stays_the_declared_commands(self):
        ready, _ = run(args=dict(ARGS, mode="ready"))
        self.assertEqual(ready["cont"]["verified"]["contract"], '[{"argv":["make","build"],"cwd":".","id":"build"}]')

    def test_the_rerun_does_not_count_a_no_slot_exit_as_its_one_rerun(self):
        _, calls = run(replies={"verify": VerifyRerunTest.OUTSIDE, "verify-rerun-1": VerifyRerunTest.GREEN})
        rerun = prompt(calls, "verify-rerun-1")
        self.assertIn("an attempt that exits 75 with the no-slot line ran nothing, so it is not that rerun and is "
                      "retried as below.", rerun)
        self.assertNotIn("exactly as declared, and never a second time, whatever the outcome.", rerun)

    NO_SLOT = {"id": "build", "status": "fail", "no_slot": True,
               "summary": "no verify slot came free in 12 attempts"}

    def test_a_rerun_that_never_started_for_want_of_a_slot_stops_with_no_fix_step(self):
        """VS-03: slot exhaustion on the rerun is no reproduced failure, so no implementer is asked to change code."""
        result, calls = run(replies={"verify": VerifyRerunTest.OUTSIDE,
                                     "verify-rerun-1": {"head": SHA, "clean": True, "results": [self.NO_SLOT]}})
        names = labels(calls)
        self.assertEqual(result["stage"], "verify")
        self.assertEqual([l for l in names if l.startswith("verify")], ["verify", "verify-rerun-1"])
        self.assertEqual([p["summary"] for p in result["problems"]], [self.NO_SLOT["summary"]])

    def test_a_first_verification_that_never_started_for_want_of_a_slot_stops_with_no_fix_step_or_rerun(self):
        result, calls = run(replies={"verify": {"head": SHA, "clean": True,
                                                "results": [dict(self.NO_SLOT, outside_diff=True)]}})
        self.assertEqual(result["stage"], "verify")
        self.assertEqual([l for l in labels(calls) if l.startswith("verify")], ["verify"])

    def test_the_prompt_asks_for_the_no_slot_mark_only_on_slot_exhaustion(self):
        _, calls = run()
        self.assertIn("no_slot: true", prompt(calls, "verify"))


class ShipTest(unittest.TestCase):
    def test_failed_checks_stop_unmerged(self):
        fix = "f" * 40
        result, calls = run(replies={"green-checks-1": red_read({"state": "failed", "head": fix})},
                            patch={"pr": {"green": red_read({"state": "failed", "head": SHA})},
                                   "fix-ci": {"start_head": SHA, "commit": fix}})
        self.assertEqual(result["stage"], "checks")
        self.assertNotIn("land-take", labels(calls))
        self.assertNotIn("merge", labels(calls))

    def test_clean_sync_rechecks_without_review(self):
        result, calls = run(patch={"land-take": {"behind": True}})
        self.assertEqual(result["stage"], "done")
        names = labels(calls)
        self.assertEqual(names[names.index("pr"):], ["pr", "land-take", "sync-1", "checks-2", "merge",
                                                   "hold", "close-out"])

    def test_conflicted_sync_is_rereviewed(self):
        _, calls = run(patch={"land-take": {"behind": True},
                              "sync-1": ABORTED, "sync-resolve-1": {"conflicted": True, "resolved_files": ["a.py"]}})
        review = [c for c in calls if c["label"] == "sync-review-1"]
        self.assertEqual(review[0]["agentType"], "reviewer")

    def test_conflicted_sync_with_findings_stops(self):
        bad = {"verdict": "findings", "findings": [{"severity": "important", "summary": "lost", "failing_input": "x"}]}
        result, calls = run(replies={"sync-review-1": bad, "fix-sync-review-1": bad},
                            patch={"land-take": {"behind": True},
                                   "sync-1": ABORTED, "sync-resolve-1": {"conflicted": True, "merge_commit": "d" * 40},
                                   "fix-sync-1": {"start_head": "d" * 40, "commit": "f" * 40}})
        self.assertEqual(result["stage"], "sync-review")
        self.assertNotIn("merge", labels(calls))

    def test_a_conflicted_sync_checks_for_markers_before_it_commits(self):
        """#907: the sync step runs the marker check itself, and a reply that says it ran leaves the review prompt as it was."""
        unchecked = "The merge was not checked for leftover conflict markers"
        behind = {"land-take": {"behind": True}}
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
                            patch={"land-take": {"behind": True},
                                   "sync-1": ABORTED, "sync-resolve-1": {"conflicted": True, "merge_commit": "d" * 40},
                                   "fix-sync-1": {"start_head": "d" * 40, "commit": "f" * 40}})
        self.assertEqual(result["stage"], "sync-review")
        self.assertIn("still lost", result["reason"])
        self.assertEqual(labels(calls).count("land-unlock"), 1)

    def test_third_behind_is_contention(self):
        behind = {"state": "behind", "head": SHA}
        result, calls = run(replies={"checks-2": behind, "checks-3": behind}, patch={"land-take": {"behind": True}})
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
        result, calls = run(patch={"pr": {"green": green_read("c" * 40)}})
        self.assertEqual(result["stage"], "head-moved")
        self.assertNotIn("land-take", labels(calls))
        self.assertNotIn("merge", labels(calls))

    def test_after_a_sync_the_merge_commit_is_the_expected_head(self):
        merge = "d" * 40
        result, calls = run(replies={"checks-2": {"state": "passed", "passed": ["ci"], "head": merge}},
                            patch={"land-take": {"behind": True}, "sync-1": {"merge_commit": merge}})
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
                                     "checks-3": {"state": "passed", "passed": ["ci"], "head": merge}},
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
                                     "checks-3": {"state": "passed", "passed": ["ci"], "head": m2},
                                     "checks-4": {"state": "behind", "head": m2},
                                     "checks-5": {"state": "passed", "passed": ["ci"], "head": m3}},
                            patch={"land-take": {"behind": True},
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

    # #1008: the forge's own words for a merge its branch protection refuses while the head is up to date.
    POLICY = {"merged": False, "behind": False,
              "notes": "X Pull request owner/repo#42 is not mergeable: the base branch policy prohibits the merge."}
    MERGED = {"merged": True, "merge_commit": "d" * 40, "notes": "merged"}

    def test_a_policy_refusal_polls_the_checks_once_more_and_merges_when_they_passed(self):
        result, calls = run(replies={"merge": [self.POLICY, self.MERGED]})
        self.assertEqual(result["stage"], "done")
        names = labels(calls)
        self.assertEqual(names[names.index("merge"):], ["merge", "checks-2", "merge", "hold", "close-out"])

    def test_a_policy_refusal_whose_poll_is_red_goes_to_the_fix_step(self):
        result, calls = run(replies={"merge": [self.POLICY, self.MERGED], "checks-2": {"state": "failed", "head": SHA, "failing": ["lint"]}})
        names = labels(calls)
        self.assertEqual(names[names.index("merge"):names.index("fix-ci") + 1], ["merge", "checks-2", "fix-ci"])
        self.assertNotIn("sync-1", names)

    def test_a_policy_refusal_whose_poll_stays_pending_stops_at_the_pending_waits(self):
        waiting = {"state": "pending", "head": SHA, "pending": ["lint"]}
        result, calls = run(replies=dict({"merge": self.POLICY}, **{f"checks-{k}": waiting for k in (2, 3, 4)}))
        self.assertEqual((result["stage"], result["pending"]), ("checks-pending", ["lint"]))
        self.assertEqual(labels(calls).count("merge"), 1)
        self.assertIn("cont", result)

    def test_a_refusal_marked_behind_is_handled_as_behind_whatever_its_message_says(self):
        # Behind and the policy text together: the three-refusal budget alone, with no extra poll and no fourth merge.
        behind = {"state": "behind", "head": SHA}
        result, calls = run(replies={"merge": dict(self.POLICY, behind=True), "checks-2": behind, "checks-4": behind})
        self.assertEqual(result["stage"], "merge")
        names = labels(calls)
        self.assertEqual(names.count("merge"), 3)
        self.assertEqual([l for l in names if l.startswith("sync-")], ["sync-1", "sync-2"])

    def test_a_second_policy_refusal_stops_at_the_merge(self):
        result, calls = run(replies={"merge": self.POLICY})
        self.assertEqual((result["stage"], result["merge"]["notes"]), ("merge", self.POLICY["notes"]))
        names = labels(calls)
        self.assertEqual(names.count("merge"), 2)
        self.assertEqual([l for l in names if l.startswith("checks-")], ["checks-2"])
        self.assertNotIn("sync-1", names)
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
               "review_rounds": 1, "reviewed": {"head": "c0ffee"},
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
        self.assertEqual(names[names.index("pr"):], ["pr", "land-take", "merge", "hold", "close-out"])

    def test_lock_commands_are_exact(self):
        _, calls = run()
        self.assertIn(f"forge-claim land acquire --repo owner/repo --branch dev --sha {SHA} --wait --lease\n",
                      prompt(calls, "land-take"))
        self.assertIn(f"forge-claim land acquire --repo owner/repo --branch dev --sha {SHA} --lease\n",
                      prompt(calls, "merge"))
        self.assertNotIn(" --wait\n", prompt(calls, "merge"))
        self.assertIn(f"forge-claim land release --repo owner/repo --branch dev --sha {SHA}\n",
                      prompt(calls, "hold"))

    def test_the_lock_is_taken_before_the_sync_merge_and_moved_after_the_push(self):
        merge = "d" * 40
        result, calls = run(replies={"checks-2": {"state": "passed", "passed": ["ci"], "head": merge}},
                            patch={"land-take": {"behind": True}, "sync-1": {"merge_commit": merge}})
        self.assertEqual(result["stage"], "done")
        names = labels(calls)
        self.assertEqual(names[names.index("pr"):], [
            "pr", "land-take", "sync-1", "land-push-2",
            "checks-2", "merge", "hold", "close-out"])
        self.assertIn("git -C /r/.wt/w-issue-9-x push origin issue-9-x", prompt(calls, "land-push-2"))
        self.assertIn(f"--sha {merge} --lease\n", prompt(calls, "checks-2"))
        self.assertNotIn(" --wait\n", prompt(calls, "checks-2"))
        self.assertIn(f"forge-claim land release --repo owner/repo --branch dev --sha {merge}",
                      prompt(calls, "hold"))

    def test_a_merge_refused_behind_resyncs_under_the_held_lock(self):
        merge = "d" * 40
        stale = {"merged": False, "behind": True, "notes": "Head branch is not up to date with the base branch"}
        result, calls = run(replies={"merge": [stale, {"merged": True, "merge_commit": merge, "notes": "merged"}],
                                     "checks-2": self.BEHIND, "checks-3": {"state": "passed", "passed": ["ci"], "head": merge}},
                            patch={"sync-1": {"merge_commit": merge}})
        self.assertEqual(result["stage"], "done")
        names = labels(calls)
        self.assertNotIn("land-unlock", names)
        later_locks = [c["prompt"] for c in calls if c["label"] in ("checks-3", "merge")]
        self.assertEqual(len(later_locks), 3)  # the first pre-merge check, the move after the push, the last pre-merge check
        for text in later_locks:
            self.assertNotIn(" --wait\n", text)
        self.assertIn("--wait --lease", prompt(calls, "land-take"))
        self.assertLess(names.index("land-take"), names.index("sync-1"))
        self.assertLess(names.index("sync-1"), names.index("land-push-3"))
        last_merge = len(names) - 1 - names[::-1].index("merge")
        self.assertLess(last_merge, names.index("hold"))

    def test_a_contended_lock_is_waited_for_by_the_cli(self):
        waited = {"verdict": "acquired", "lock_sha": SHA, "waited_s": 1800, "took_over": "idle"}
        result, calls = run(patch={"land-take": {"lock": waited}})
        self.assertEqual(result["stage"], "done")
        names = labels(calls)
        self.assertEqual(names[names.index("pr"):names.index("merge")], ["pr", "land-take"])
        self.assertIn(f"--sha {SHA} --wait --lease\n", prompt(calls, "land-take"))

    def test_a_fix_commit_in_short_form_moves_the_lock_by_its_full_sha(self):
        short = FIX[:9]
        result, calls = run(replies={"green-checks-1": green_read(FIX), "land-push-1": {"head": FIX}},
                            patch={"pr": {"green": red_read(RED)}, "fix-ci": {"start_head": SHA, "commit": short}})
        self.assertEqual(result["stage"], "done")
        self.assertIn(f"forge-claim land acquire --repo owner/repo --branch dev --sha {FIX} --wait --lease\n", prompt(calls, "land-take"))
        self.assertNotIn(f"--sha {short} ", prompt(calls, "land-take"))
        self.assertNotIn(f"--sha {short}\n", prompt(calls, "land-take"))
        self.assertIn(f"forge-claim land release --repo owner/repo --branch dev --sha {FIX}", prompt(calls, "hold"))

    def test_a_non_holding_wait_answer_stops_with_cont(self):
        for verdict in ("land-contended", "held_by", "lost_to"):
            with self.subTest(verdict=verdict):
                refusal = {"lock": {"verdict": verdict, "lock_sha": "b" * 40, "by": "h2/b9"}}
                result, calls = run(replies={f"land-lock-{k}": refusal for k in (1, 2, 3)},
                                    patch={"land-take": refusal})
                self.assertEqual((result["stage"], result["pr"], result["lock"]), ("land-contended", 42, verdict))
                self.assertIn("cont", result)
                for gone in ("checks-1", "checks-2", "sync-1", "merge", "land-unlock", "close-out"):
                    self.assertNotIn(gone, labels(calls))
                # #818: only a wait that ran out is waited for again; held_by and lost_to stop at once.
                self.assertEqual([l for l in labels(calls) if l.startswith("land-lock-")],
                                 ["land-lock-1", "land-lock-2", "land-lock-3"] if verdict == "land-contended" else [])

    def test_a_failed_move_releases_the_last_held_sha(self):
        merge = "d" * 40
        result, calls = run(replies={"checks-2": {"lock": {"verdict": "land-contended", "lock_sha": "c" * 40, "by": "h2/b9"}}},
                            patch={"land-take": {"behind": True}, "sync-1": {"merge_commit": merge}})
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
                            patch={"land-take": {"behind": True}, "sync-1": {"merge_commit": merge}})
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
        result, calls = run(replies={"land-take": {"lock": None}})
        self.assertEqual(result["stage"], "land-lock")
        self.assertIn("cont", result)
        self.assertEqual(labels(calls).count("land-unlock"), 1)
        self.assertIn(f"--sha {SHA}\n", prompt(calls, "land-unlock"))

    def test_every_stop_after_the_lock_releases_it(self):
        fix = "f" * 40
        cases = {
            # A red poll under the lease at an unsynced head: a policy refusal polls once more.
            "checks": {"replies": {"merge": [MergeRefusedBehindTest.POLICY], "checks-2": RED, "green-checks-1": red_read(dict(RED, head=fix))},
                       "patch": {"fix-ci": {"start_head": SHA, "commit": fix}}},
            "checks-pending": {"replies": {f"checks-{k}": {"state": "pending", "head": SHA, "pending": ["e2e"]}
                                           for k in (2, 3, 4)},
                               "patch": {"land-take": {"behind": True}}},
            "head-moved": {"replies": {"checks-2": {"state": "passed", "passed": ["ci"], "head": "c" * 40}},
                           "patch": {"land-take": {"behind": True}}},
            "merge": {"replies": {"merge": {"merged": False, "notes": "head moved"}}},
            "sync-contention": {"replies": {"checks-2": self.BEHIND, "checks-3": self.BEHIND},
                                "patch": {"land-take": {"behind": True}}},
            "land-contended": {"replies": {"checks-2": {"lock": {"verdict": "land-contended", "lock_sha": "b" * 40}}},
                               "patch": {"land-take": {"behind": True}, "sync-1": {"merge_commit": "d" * 40}}},
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
        result, calls = run(patch={"land-take": {"behind": True},
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
        result, calls = run(patch={"pr": {"head": "c" * 40}})
        self.assertEqual(result["stage"], "head-moved")
        self.assertNotIn("land-unlock", labels(calls))


class LandWaitRetryTest(unittest.TestCase):
    """#818: a land-contended answer of the folded acquire --wait is the wait running out behind other landings,
    so the claim is renewed and the same acquire waits again, three times at most."""

    CONTENDED = {"lock": {"verdict": "land-contended", "lock_sha": "b" * 40, "by": "h2/b9"}}
    WAIT_OUT = {"land-take": CONTENDED}

    @staticmethod
    def waits(calls):
        return [l for l in labels(calls) if l.startswith("land-lock-")]

    def test_a_contended_wait_then_an_acquired_lock_ships(self):
        result, calls = run(patch=self.WAIT_OUT)
        self.assertEqual(result["stage"], "done")
        names = labels(calls)
        self.assertEqual(names[names.index("pr"):], ["pr", "land-take", "land-lock-1", "merge", "hold", "close-out"])
        text = prompt(calls, "land-lock-1")
        self.assertIn(f"forge-claim renew --repo owner/repo --issue 9 --holder {HOLDER} --branch issue-9-x", text)
        self.assertIn(f"forge-claim land acquire --repo owner/repo --branch dev --sha {SHA} --wait --lease\n", text)
        self.assertLess(text.index("forge-claim renew"), text.index("forge-claim land acquire"))
        call = next(c for c in calls if c["label"] == "land-lock-1")
        self.assertEqual((call["agentType"], call["model"], call["effort"]), ("clerk", "sonnet", "low"))
        schema = schema_of(calls, "land-lock-1")
        self.assertEqual(schema["required"], ["renew"])
        self.assertIn("verdict", member(schema, "lock")["properties"])
        # The green read stands: the retried wait polls no checks and the head merges at once.
        self.assertNotIn("checks-1", names)
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
        self.assertEqual(names[names.index("pr"):], ["pr", "land-take", "land-lock-1", "land-lock-2", "land-lock-3"])

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
    """#913: a sync merge that conflicts is aborted under the land lease and resolved, tested, reviewed and fixed outside it; the
    accepted head is read green before it takes the lease again, and a clean merge never leaves it."""

    BEHIND = {"land-take": {"behind": True}}
    # The first take finds the base moved past the head; the next, after the resolution, finds it current.
    TAKES = [{"behind": True}, {}]
    RELEASE = "forge-claim land release --repo owner/repo --branch dev --sha "
    M2 = "e" * 40

    def ship(self, replies=None, **patch):
        return run_out(replies={"land-take": self.TAKES, **(replies or {})},
                       patch={"sync-1": ABORTED, "sync-resolve-1": {"merge_commit": MERGE}, **patch})

    @staticmethod
    def shipped(out):
        names = labels(out["calls"])
        return names[names.index("pr"):]

    def test_a_conflict_is_aborted_released_resolved_and_the_lease_taken_again_once_green(self):
        out = self.ship()
        result, calls = out["result"], out["calls"]
        self.assertEqual(result["stage"], "done")
        self.assertEqual(self.shipped(out), ["pr", "land-take", "sync-1", "land-unlock", "sync-resolve-1", "sync-review-1", "land-push-2",
                                             "green-checks-1", "land-take", "merge", "hold", "close-out"])
        sync = prompt(calls, "sync-1")
        self.assertIn("If it conflicts, do not resolve it: run git merge --abort inside /r/.wt/w-issue-9-x", sync)
        self.assertIn("confirm no merge is left in progress", sync)
        self.assertIn("conflicted", next(c for c in calls if c["label"] == "sync-1")["schema"]["properties"]["status"]["enum"])
        # The first hold ends at the head it was taken at, before the resolution starts.
        self.assertIn(f"{self.RELEASE}{SHA}\n", prompt(calls, "land-unlock"))
        resolve = prompt(calls, "sync-resolve-1")
        for text in ("the landing lock is not held while you work", "rev-parse -q --verify MERGE_HEAD", "merge origin/dev", "Do not push."):
            self.assertIn(text, resolve)
        # The accepted head is pushed and read green with no lock command; only then is the lease taken at it, waiting.
        self.assertIn(f"at the head {MERGE}", prompt(calls, "land-push-2"))
        self.assertNotIn("land acquire --repo", prompt(calls, "green-checks-1"))
        take = prompt(calls, "land-take")
        self.assertIn(f"forge-claim land acquire --repo owner/repo --branch dev --sha {MERGE} --wait --lease\n", take)
        self.assertIn("merge-base --is-ancestor origin/dev HEAD", take)
        merge = prompt(calls, "merge")
        self.assertIn(f"--sha {MERGE} --lease\n", merge)
        self.assertIn("Only when lock's verdict is already_held or moved", merge)
        self.assertIn(f"{self.RELEASE}{MERGE}", prompt(calls, "hold"))
        self.assertNotIn("lock_unreleased", result)

    # #986: the resolver committed the merge MERGE, its tests then caught a defect, and it fixed it in a commit on top: the head M2.
    FOLLOWED = {"merge_commit": MERGE, "head": M2, "resolved_files": ["a.py"], "markers_checked": True}
    DESCENDS = {"verdict": "pass", "findings": [], "descends": True}

    def followed(self, review, replies=None, **patch):
        return run_out(replies={"land-take": self.TAKES, "sync-review-1": review, **(replies or {})},
                       patch={"sync-1": ABORTED, "sync-resolve-1": self.FOLLOWED, **patch})

    def test_a_resolution_with_commits_on_top_of_its_merge_commit_is_reviewed_over_both_and_ships_at_its_head(self):
        out = self.followed(self.DESCENDS)
        result, calls = out["result"], out["calls"]
        self.assertEqual(result["stage"], "done")
        self.assertEqual(self.shipped(out), ["pr", "land-take", "sync-1", "land-unlock", "sync-resolve-1", "sync-review-1", "land-push-2",
                                             "green-checks-1", "land-take", "merge", "hold", "close-out"])
        review = prompt(calls, "sync-review-1")
        wt = "/r/.wt/w-issue-9-x"
        for needle in (f"git -C {wt} show --cc {MERGE}", f"git -C {wt} merge-base --is-ancestor {MERGE} {self.M2}",
                       f"git -C {wt} rev-list --count --min-parents=2 {MERGE}..{self.M2}", f"git -C {wt} diff {MERGE}..{self.M2}",
                       f"git -C {wt} diff --check {MERGE} {self.M2}", "above all for a test or check they weaken, skip or delete"):
            with self.subTest(needle=needle):
                self.assertIn(needle, review)
        self.assertIn("descends", schema_of(calls, "sync-review-1")["required"])
        # Everything downstream is at the head: the push, the green read, the lease, the merge and the release.
        self.assertIn(f"at the head {self.M2}", prompt(calls, "land-push-2"))
        self.assertIn(f"at the head {self.M2}", prompt(calls, "green-checks-1"))
        self.assertIn(f"forge-claim land acquire --repo owner/repo --branch dev --sha {self.M2} --wait --lease\n", prompt(calls, "land-take"))
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
        out = run_out(replies={"checks-2": {"state": "passed", "passed": ["ci"], "head": self.M2}, "sync-review-1": self.DESCENDS}, patch=clean)
        self.assertEqual(out["result"]["stage"], "done")
        self.assertEqual(self.shipped(out), ["pr", "land-take", "sync-1", "sync-review-1", "land-push-2", "checks-2", "merge", "hold", "close-out"])
        self.assertIn(f"diff {MERGE}..{self.M2}", prompt(out["calls"], "sync-review-1"))
        self.assertIn(f"--match-head-commit {self.M2}", prompt(out["calls"], "merge"))
        self.assertIn("head (the full sha of HEAD after the merge: the merge commit itself, unless you committed on top of it)",
                      prompt(out["calls"], "sync-1"))
        out = run_out(replies={"sync-review-1": {"verdict": "pass", "findings": [], "descends": False}}, patch=clean)
        self.assertEqual(out["result"]["stage"], "sync")
        self.assertNotIn("merge", self.shipped(out))
        # A clean merge whose head is the merge commit runs no review, as ever.
        out = run_out(replies={"checks-2": {"state": "passed", "passed": ["ci"], "head": MERGE}},
                      patch={**self.BEHIND, "sync-1": {"conflicted": False, "merge_commit": MERGE, "head": MERGE}})
        self.assertEqual(out["result"]["stage"], "done")
        self.assertNotIn("sync-review-1", self.shipped(out))

    def test_the_fix_wave_of_a_resolution_with_follow_up_commits_starts_at_its_head_and_names_the_range(self):
        fixed = "9" * 40
        out = self.followed(dict(FINDING, descends=True), **{"fix-sync-1": {"start_head": self.M2, "commit": fixed}})
        calls = out["calls"]
        self.assertEqual(out["result"]["stage"], "done")
        rng = f"merge commit {MERGE} (git -C /r/.wt/w-issue-9-x show --cc {MERGE}) and the commits made on top of it up to the head {self.M2}"
        self.assertIn(rng, prompt(calls, "fix-sync-1"))
        self.assertIn(f"diff {self.M2}..{fixed}", prompt(calls, "fix-sync-review-1"))
        self.assertIn(f"--match-head-commit {fixed}", prompt(calls, "merge"))
        self.assertIn(f"at the head {fixed}", prompt(calls, "green-checks-1"))
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
        result, calls = run(replies={"checks-2": {"state": "passed", "passed": ["ci"], "head": MERGE}},
                            patch=dict(self.BEHIND, **{"sync-1": {"merge_commit": MERGE}}))
        self.assertEqual(result["stage"], "done")
        names = labels(calls)
        self.assertEqual(names[names.index("pr"):], ["pr", "land-take", "sync-1", "land-push-2", "checks-2", "merge", "hold", "close-out"])
        self.assertIn(f"Move the cross-host landing lock of the branch dev for PR #42 to the head {MERGE}", prompt(calls, "checks-2"))
        self.assertNotIn(" --wait --lease\n", prompt(calls, "checks-2"))

    def test_behind_again_after_the_second_take_a_clean_merge_stays_under_the_lock(self):
        out = self.ship(replies={"land-take": [{"behind": True}, {"behind": True}, {}],
                                 "checks-4": {"state": "passed", "passed": ["ci"], "head": self.M2}}, **{"sync-2": {"merge_commit": self.M2}})
        self.assertEqual(out["result"]["stage"], "done")
        self.assertEqual(self.shipped(out), ["pr", "land-take", "sync-1", "land-unlock", "sync-resolve-1", "sync-review-1", "land-push-2",
                                             "green-checks-1", "land-take", "sync-2", "land-push-4", "checks-4", "merge", "hold", "close-out"])
        again = prompt(out["calls"], "checks-4")
        self.assertIn(f"--sha {self.M2} --lease\n", again)
        self.assertNotIn(" --wait --lease\n", again)
        self.assertIn(f"--match-head-commit {self.M2}", prompt(out["calls"], "merge"))

    def test_behind_again_with_a_second_conflict_is_resolved_outside_the_lock_again(self):
        second = {"sync-2": ABORTED, "sync-resolve-2": {"merge_commit": self.M2}}
        out = self.ship(replies={"land-take": [{"behind": True}, {"behind": True}, {}]}, **second)
        self.assertEqual(out["result"]["stage"], "done")
        self.assertEqual(self.shipped(out), [
            "pr", "land-take", "sync-1", "land-unlock", "sync-resolve-1", "sync-review-1", "land-push-2", "green-checks-1", "land-take",
            "sync-2", "land-unlock", "sync-resolve-2", "sync-review-2", "land-push-4", "green-checks-2", "land-take", "merge", "hold", "close-out"])
        # Each hold is released once, at the head it was held at.
        unlocks = [c["prompt"] for c in out["calls"] if c["label"] == "land-unlock"]
        self.assertEqual([self.RELEASE + sha + "\n" in text for sha, text in zip((SHA, MERGE), unlocks)], [True, True])
        self.assertIn(f"--sha {self.M2} --wait --lease\n", prompt(out["calls"], "land-take"))
        # Behind once more: the sync bound ends the delivery with its own reason, and the third hold is released.
        out = self.ship(replies={"land-take": [{"behind": True}, {"behind": True}, {"behind": True}]}, **second)
        self.assertEqual((out["result"]["stage"], out["result"]["syncs"]), ("sync-contention", 2))
        names = labels(out["calls"])
        self.assertNotIn("merge", names)
        self.assertEqual(names.count("land-unlock"), 3)
        self.assertIn(f"{self.RELEASE}{self.M2}\n", prompt(out["calls"], "land-unlock"))

    def test_a_refused_take_after_a_resolution_never_merges_and_holds_nothing(self):
        for verdict in ("land-contended", "held_by", "lost_to"):
            with self.subTest(verdict=verdict):
                out = self.ship(replies={"land-take": [{"behind": True}, {"lock": {"verdict": verdict, "lock_sha": self.M2}}],
                                         **{f"land-lock-{k}": {"lock": {"verdict": "land-contended"}} for k in (1, 2, 3)}})
                result, names = out["result"], labels(out["calls"])
                # Only a wait that ran out is waited for again, as often as a first wait is (LAND_WAIT_RETRIES).
                self.assertEqual([name for name in names if name.startswith("land-lock-")],
                                 [f"land-lock-{k}" for k in (1, 2, 3)] if verdict == "land-contended" else [])
                self.assertEqual((result["stage"], result["lock"]), ("land-contended", verdict))
                self.assertNotIn("merge", names)
                # The only release is the one before the resolution.
                self.assertEqual(names.count("land-unlock"), 1)
                self.assertLess(names.index("land-unlock"), names.index("sync-resolve-1"))
                self.assertNotIn("lock_unreleased", result)

    def test_a_take_after_a_resolution_that_answers_acquired_still_merges_only_on_the_pre_merge_check(self):
        retaken = {"lock": {"verdict": "acquired", "lock_sha": MERGE, "waited_s": 1740, "waited_on": [2257]}}
        out = self.ship(replies={"land-take": [{"behind": True}, retaken]})
        self.assertEqual(out["result"]["stage"], "done")
        self.assertIn("land-take: waited 29 min for the land lock of dev behind PR #2257", out["logs"])
        out = self.ship(replies={"land-take": [{"behind": True}, retaken], "merge": {"merged": False, "notes": "held_by", "lock": {"verdict": "held_by"}}})
        self.assertEqual(out["result"]["stage"], "land-contended")
        self.assertNotIn("hold", labels(out["calls"]))

    def test_a_lost_take_after_a_resolution_releases_what_it_may_hold(self):
        out = self.ship(replies={"land-take": [{"behind": True}, None]})
        self.assertEqual(out["result"]["stage"], "land-lock")
        names = labels(out["calls"])
        self.assertEqual(names.count("land-unlock"), 2)
        # The waiting acquire may have taken the lock at the accepted head: the stop releases it there.
        self.assertIn(f"{self.RELEASE}{MERGE}\n", prompt(out["calls"], "land-unlock"))
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
        out = run_out(replies={"land-take": self.TAKES}, patch={"sync-1": {"conflicted": True, "merge_commit": MERGE}})
        self.assertEqual(out["result"]["stage"], "done")
        self.assertEqual(self.shipped(out), ["pr", "land-take", "sync-1", "land-unlock", "sync-review-1", "land-push-2", "green-checks-1",
                                             "land-take", "merge", "hold", "close-out"])
        self.assertIn(f"--sha {MERGE} --wait --lease\n", prompt(out["calls"], "land-take"))

    def test_a_resolution_that_says_it_merged_cleanly_is_reviewed_all_the_same(self):
        clean = {"sync-resolve-1": {"conflicted": False, "merge_commit": MERGE}}
        out = self.ship(**clean)
        self.assertEqual(out["result"]["stage"], "done")
        self.assertEqual(self.shipped(out), ["pr", "land-take", "sync-1", "land-unlock", "sync-resolve-1", "sync-review-1", "land-push-2",
                                             "green-checks-1", "land-take", "merge", "hold", "close-out"])
        self.assertIn(f"merge commit {MERGE}", prompt(out["calls"], "sync-review-1"))
        self.assertIn(f"--sha {MERGE} --wait --lease\n", prompt(out["calls"], "land-take"))
        out = self.ship(replies={"sync-review-1": FINDING, "fix-sync-review-1": FINDING},
                        **clean, **{"fix-sync-1": {"start_head": MERGE, "commit": FIX}})
        self.assertEqual(out["result"]["stage"], "sync-review")
        self.assertNotIn("merge", labels(out["calls"]))

    def test_a_take_after_a_resolution_whose_wait_ran_out_waits_again_like_a_first_wait(self):
        out_of_time = {"lock": {"verdict": "land-contended", "lock_sha": self.M2, "waited_s": 3600, "waited_on": [7]}}
        takes = {"land-take": [{"behind": True}, out_of_time]}
        out = self.ship(replies={**takes, "land-lock-1": {"lock": {"verdict": "land-contended"}},
                                 "land-lock-2": {"lock": {"verdict": "acquired", "lock_sha": MERGE, "waited_s": 900, "waited_on": [7, 9]}}})
        result, calls = out["result"], out["calls"]
        self.assertEqual(result["stage"], "done")
        self.assertEqual(self.shipped(out), ["pr", "land-take", "sync-1", "land-unlock", "sync-resolve-1", "sync-review-1", "land-push-2",
                                             "green-checks-1", "land-take", "land-lock-1", "land-lock-2", "merge", "hold", "close-out"])
        again = next(c for c in calls if c["label"] == "land-lock-2")
        self.assertEqual((again["agentType"], again["model"]), ("clerk", "sonnet"))
        self.assertIn("forge-claim renew --repo owner/repo --issue 9", again["prompt"])
        self.assertIn(f"forge-claim land acquire --repo owner/repo --branch dev --sha {MERGE} --wait --lease\n", again["prompt"])
        self.assertIn(f"{self.RELEASE}{MERGE}", prompt(calls, "hold"))
        self.assertEqual([line for line in out["logs"] if "waited" in line],
                         ["land-take: waited 60 min for the land lock of dev behind PR #7",
                          "land-lock-2: waited 15 min for the land lock of dev behind PR #7, #9"])
        # A lost claim ends the wait; a lost reply may hold the lock at the accepted head, which the stop's release covers.
        out = self.ship(replies={**takes, "land-lock-1": {"renew": {"verdict": "not_held", "by": "h2/b1"}, "lock": None}})
        self.assertEqual((out["result"]["stage"], out["result"]["at"]), ("claim-lost", "land-lock-1"))
        self.assertEqual(labels(out["calls"]).count("land-unlock"), 1)
        out = self.ship(replies={**takes, "land-lock-1": None})
        self.assertEqual(out["result"]["stage"], "land-lock")
        self.assertEqual(labels(out["calls"]).count("land-unlock"), 2)
        self.assertIn(f"{self.RELEASE}{MERGE}\n", prompt(out["calls"], "land-unlock"))
        self.assertNotIn("merge", labels(out["calls"]))

    def test_a_long_first_wait_is_logged_with_its_holders(self):
        def waits(**lock):
            out = run_out(patch={"land-take": {"lock": dict({"verdict": "acquired", "lock_sha": SHA}, **lock)}})
            return [line for line in out["logs"] if "waited" in line]
        self.assertEqual(waits(waited_s=1740, waited_on=[2218]), ["land-take: waited 29 min for the land lock of dev behind PR #2218"])
        self.assertEqual(waits(waited_s=240, waited_on=[2218]), [])
        _, calls = run()
        self.assertIn("lock_sha, by, detail, waited_s and waited_on from its output", prompt(calls, "land-take"))


class ResolveBeforeLockTest(unittest.TestCase):
    """#941: before it asks for the land lock, the pr call probes whether the integration branch merges cleanly into the head. A clean
    probe changes nothing; a conflict is resolved, reviewed and fixed before any lock command, and the accepted head takes the lock."""

    PROBE_CMD = "git -C /r/.wt/w-issue-9-x merge-tree --write-tree --name-only --no-messages HEAD origin/dev"
    RELEASE = "forge-claim land release --repo owner/repo --branch dev --sha "
    # The probe found a conflict, so the pr call waited for no check and asked for no lock.
    EARLY = {"probe": {"conflicted": True, "tree": "e" * 40, "files": ["a.py"]}}
    RESOLVED = ["pr", "sync-resolve-1", "sync-review-1", "land-push-1", "green-checks-1", "land-take"]
    M2 = "e" * 40
    M3 = "9" * 40

    def ship(self, replies=None, **patch):
        return run_out(replies=dict({"green-checks-1": green_read(MERGE)}, **(replies or {})),
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
        self.assertNotIn("forge-claim land", text)
        self.assertLess(text.index(self.PROBE_CMD), text.index("for the checks of PR #<the PR number> at the head"))
        schema = schema_of(calls, "pr")
        self.assertIn({"type": "null"}, schema["properties"]["probe"]["anyOf"])
        self.assertIn({"type": "null"}, schema["properties"]["green"]["anyOf"])
        self.assertNotIn("lock", schema["properties"])
        self.assertEqual(member(schema, "probe")["required"], ["conflicted"])
        self.assertEqual(schema["required"], ["renew"])

    def test_a_clean_probe_is_the_old_flow_with_the_same_calls(self):
        for name, patch in (("current", {}), ("behind", {"land-take": {"behind": True}})):
            base = run(patch=patch)[1]
            for probe in (None, {"conflicted": False}, {"conflicted": False, "detail": "fatal: not a tree"}):
                with self.subTest(name=name, probe=probe):
                    result, calls = run(patch=dict(patch, pr={"probe": probe}))
                    self.assertEqual(self.steps(calls), self.steps(base))
                    self.assertEqual(result["stage"], "done")
        names = labels(run()[1])
        self.assertEqual(names[names.index("pr"):], ["pr", "land-take", "merge", "hold", "close-out"])

    def test_exit_one_without_a_tree_id_is_no_conflict(self):
        """git merge-tree also exits 1, with nothing on stdout, when a ref is missing: only a tree id proves a conflict."""
        base = self.steps(run()[1])
        for tree in (None, "", "merge-tree: origin/dev - not something we can merge", "e" * 39, "E" * 40):
            probe = {"conflicted": True, "files": []} if tree is None else {"conflicted": True, "tree": tree, "files": []}
            with self.subTest(tree=tree):
                result, calls = run(patch={"pr": {"probe": probe}})
                self.assertEqual(self.steps(calls), base)
                self.assertEqual(result["stage"], "done")
                # A call that waited for no check on such a reply resolves nothing: it stops at the checks.
                out = run_out(patch={"pr": {"probe": probe, "green": None}})
                self.assertEqual(out["result"]["stage"], "checks")
                self.assertEqual(self.shipped(out), ["pr"])

    def test_a_conflicted_probe_is_resolved_first_even_when_the_pr_call_named_a_green_read(self):
        out = run_out(replies={"green-checks-1": green_read(MERGE)},
                      patch={"pr": {"probe": {"conflicted": True, "tree": "e" * 40}, "green": green_read()},
                             "sync-resolve-1": {"merge_commit": MERGE}})
        self.assertEqual(out["result"]["stage"], "done")
        self.assertEqual(self.shipped(out), self.RESOLVED + ["merge", "hold", "close-out"])

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
        # The accepted head is pushed and read with no lock; only its green read takes the lock, waiting.
        self.assertIn(f"at the head {MERGE}", prompt(calls, "land-push-1"))
        self.assertNotIn("forge-claim land", prompt(calls, "green-checks-1"))
        take = prompt(calls, "land-take")
        self.assertIn(f"take the cross-host landing lock of the branch dev for PR #42 at the head {MERGE}; its head is green", take)
        self.assertIn(f"forge-claim land acquire --repo owner/repo --branch dev --sha {MERGE} --wait --lease\n", take)
        self.assertIn("merge-base --is-ancestor origin/dev HEAD", take)
        merge = prompt(calls, "merge")
        self.assertIn(f"--sha {MERGE} --lease\n", merge)
        self.assertIn(f"--match-head-commit {MERGE}", merge)
        # One hold, taken at the accepted head and released there once, in the hold call: no step ever held the verified head.
        releases = [sha for c in calls for sha in re.findall(re.escape(self.RELEASE) + r"([0-9a-f]+)", c["prompt"])]
        self.assertEqual(releases, [MERGE])
        self.assertNotIn("lock_unreleased", result)
        self.assertEqual(result["syncs"], 1)

    def test_a_finding_goes_through_the_fix_wave_and_the_fix_is_what_lands(self):
        out = self.ship(replies={"sync-review-1": FINDING, "green-checks-1": green_read(FIX)},
                        **{"fix-sync-1": {"start_head": MERGE, "commit": FIX}})
        self.assertEqual(out["result"]["stage"], "done")
        self.assertEqual(self.shipped(out), ["pr", "sync-resolve-1", "sync-review-1", "fix-sync-1", "fix-sync-review-1", "land-push-1",
                                             "green-checks-1", "land-take", "merge", "hold", "close-out"])
        self.assertIn(f"--sha {FIX} --wait --lease\n", prompt(out["calls"], "land-take"))
        self.assertIn(f"--match-head-commit {FIX}", prompt(out["calls"], "merge"))

    def test_every_stop_before_the_lock_runs_no_lock_command_and_accepts_nothing(self):
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
                for gone in ("sync-1", "green-checks-1", "land-take", "merge", "hold"):
                    self.assertNotIn(gone, names)
                # No step asked for the lock, so no stop releases it.
                self.assertNotIn("land-unlock", names)
                self.assertFalse([c for c in out["calls"] if "forge-claim land" in c["prompt"]])
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
        self.assertIn("final-scoped", names)
        self.assertLess(names.index("final-scoped"), names.index("merge"))

    def test_lost_and_refused_replies_on_the_new_step_order_keep_the_lock_accounting(self):
        refused = lambda v: {"lock": {"verdict": v, "lock_sha": self.M2}}
        waits = {f"land-lock-{k}": {"lock": {"verdict": "land-contended"}} for k in (1, 2, 3)}
        cases = {
            # The waiting acquire may have taken the lock at the accepted head before its reply was lost: the stop releases it there.
            "the take is lost": ({"land-take": None}, "land-lock", 1),
            "held by another": ({"land-take": refused("held_by")}, "land-contended", 0),
            "lost to another": ({"land-take": refused("lost_to")}, "land-contended", 0),
            "every wait ran out": ({"land-take": refused("land-contended"), **waits}, "land-contended", 0),
            "a retried wait is lost": ({"land-take": refused("land-contended"), "land-lock-1": None}, "land-lock", 1),
            # A lease lost at the merge's re-check holds nothing, however often it is waited for again.
            "the merge check lost the lock": ({"merge": {"merged": False, "notes": "held_by", "lock": {"verdict": "held_by"}}}, "land-contended", 0),
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
        # A wait that ran out at the CLI's bound is waited for again through the program, in a land-lock step.
        out = self.ship(replies={"land-take": refused("land-contended")})
        self.assertEqual(out["result"]["stage"], "done")
        self.assertEqual(self.shipped(out), self.RESOLVED + ["land-lock-1", "merge", "hold", "close-out"])
        self.assertIn(f"--sha {MERGE} --wait --lease\n", prompt(out["calls"], "land-lock-1"))
    def test_a_lost_or_ended_pr_call_is_handled_as_before_the_probe(self):
        out = run_out(replies={"pr": None})
        self.assertEqual(out["result"]["stage"], "pr")
        self.assertNotIn("land-unlock", labels(out["calls"]))
        out = run_out(patch={"pr": dict(self.EARLY, renew={"verdict": "not_held", "by": "h2/b9"})})
        self.assertEqual(out["result"]["stage"], "claim-lost")
        self.assertNotIn("sync-resolve-1", labels(out["calls"]))
        out = run_out(patch={"pr": dict(self.EARLY, head="c" * 40)})
        self.assertEqual(out["result"]["stage"], "head-moved")
        self.assertNotIn("land-unlock", labels(out["calls"]))

    def test_a_conflict_after_the_acquire_takes_the_913_path(self):
        out = self.ship(replies={"land-take": [{"behind": True}, {}]},
                        **{"sync-2": ABORTED, "sync-resolve-2": {"merge_commit": self.M2}})
        self.assertEqual(out["result"]["stage"], "done")
        self.assertEqual(self.shipped(out), self.RESOLVED + ["sync-2", "land-unlock", "sync-resolve-2", "sync-review-2", "land-push-3",
                                                             "green-checks-2", "land-take", "merge", "hold", "close-out"])
        # The hold taken at the accepted head is released before the second resolution; the lease is taken at the second accepted head once green.
        self.assertIn(f"{self.RELEASE}{MERGE}\n", prompt(out["calls"], "land-unlock"))
        self.assertIn(f"--sha {self.M2} --wait --lease\n", prompt(out["calls"], "land-take"))
    def test_the_round_before_the_lock_spends_no_sync_contention(self):
        clean = {"checks-3": {"state": "behind", "head": self.M2}, "checks-4": green_read(self.M3)}
        merges = {"land-take": {"behind": True}, "sync-2": {"merge_commit": self.M2}, "sync-3": {"merge_commit": self.M3}}
        out = self.ship(replies=clean, **merges)
        self.assertEqual((out["result"]["stage"], out["result"]["syncs"]), ("done", 3))
        self.assertEqual(self.shipped(out), self.RESOLVED + ["sync-2", "land-push-3", "checks-3", "sync-3", "land-push-4", "checks-4",
                                                             "merge", "hold", "close-out"])
        self.assertNotIn(" --wait\n", prompt(out["calls"], "checks-3"))
        out = self.ship(replies=dict(clean, **{"checks-4": {"state": "behind", "head": self.M3}}), **merges)
        self.assertEqual((out["result"]["stage"], out["result"]["syncs"]), ("sync-contention", 3))
        self.assertIn(f"{self.RELEASE}{self.M3}\n", prompt(out["calls"], "land-unlock"))


class ShipFixWaveTest(unittest.TestCase):
    """#649 defect 2 and the sync-review decision: one bounded fix wave, then a stop with cont."""

    def red_then(self, second, **patch):
        return run(replies={"green-checks-1": second},
                   patch=dict({"pr": {"green": red_read(RED)}, "fix-ci": {"start_head": SHA, "commit": FIX}}, **patch))

    def test_failed_check_runs_one_fix_wave_then_merges(self):
        result, calls = self.red_then(green_read(FIX))
        self.assertEqual(result["stage"], "done")
        names = labels(calls)
        self.assertEqual(names[names.index("pr"):], [
            "pr", "fix-ci", "fix-ci-review", "land-push-1", "green-checks-1", "land-take",
            "merge", "hold", "close-out"])
        fix = prompt(calls, "fix-ci")
        for needle in ("ci-tests", "FAIL test_cache: host-installed state", "regression test"):
            self.assertIn(needle, fix)
        self.assertEqual([c["agentType"] for c in calls if c["label"] == "fix-ci"], ["implementer"])
        self.assertEqual([c["agentType"] for c in calls if c["label"] == "fix-ci-review"], ["reviewer"])
        self.assertIn(f"diff {SHA}..{FIX}", prompt(calls, "fix-ci-review"))
        self.assertIn(f"--match-head-commit {FIX}", prompt(calls, "merge"))

    def test_a_second_failure_stops_with_cont(self):
        result, calls = self.red_then(red_read(dict(RED, head=FIX)))
        self.assertEqual(result["stage"], "checks")
        self.assertEqual(result["cont"]["checks_fixes"], 1)
        self.assertEqual(labels(calls).count("fix-ci"), 1)
        self.assertNotIn("merge", labels(calls))

    def test_a_resume_with_the_wave_spent_stops_at_the_first_failure(self):
        stopped, _ = self.red_then(red_read(dict(RED, head=FIX)))
        result, calls = run(args=dict(ARGS, cont=stopped["cont"]), patch={"pr": {"green": red_read(RED)}})
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
                                    patch=dict({"pr": {"green": red_read(RED)}, "fix-ci": {"start_head": SHA, "commit": FIX}}, **patch))
                self.assertEqual(result["stage"], stage.strip())
                self.assertIn("cont", result)
                self.assertNotIn("merge", labels(calls))

    RERAN = {"start_head": SHA, "commit": SHA, "notes": "cache restore failed in setup; failed jobs rerun"}

    def test_a_rerun_at_the_unchanged_head_polls_again_then_ships(self):
        # #818: done at the unchanged head is a rerun of jobs that failed for no cause in the code.
        result, calls = run(replies={"green-checks-1": green_read(SHA, required=["ci-tests"], passed=["ci-tests"])},
                            patch={"pr": {"green": red_read(RED)}, "fix-ci": self.RERAN})
        self.assertEqual(result["stage"], "done")
        names = labels(calls)
        self.assertEqual(names[names.index("pr"):], ["pr", "fix-ci", "green-checks-1", "land-take", "merge", "hold", "close-out"])
        self.assertNotIn("forge-claim land", prompt(calls, "green-checks-1"))
        self.assertIn(f"--match-head-commit {SHA}", prompt(calls, "merge"))
    def test_a_rerun_in_short_form_is_the_unchanged_head(self):
        result, calls = run(replies={"green-checks-1": green_read(SHA)},
                            patch={"pr": {"green": red_read(RED)}, "fix-ci": dict(self.RERAN, commit=SHA[:9])})
        self.assertEqual(result["stage"], "done")
        self.assertNotIn("fix-ci-review", labels(calls))
        self.assertNotIn("land-push-1", labels(calls))
    def test_a_rerun_that_is_still_red_stops_as_the_ci_failure(self):
        result, calls = run(replies={"green-checks-1": red_read(RED)}, patch={"pr": {"green": red_read(RED)}, "fix-ci": self.RERAN})
        self.assertEqual((result["stage"], result["failing"]), ("checks", ["ci-tests"]))
        self.assertEqual(result["cont"]["checks_fixes"], 1)
        names = labels(calls)
        self.assertEqual(names[names.index("pr"):], ["pr", "fix-ci", "green-checks-1"])
    STALE_GATE = {"state": "failed", "head": SHA, "failing": ["required-checks"], "stale": [43286872194]}
    STALE_LEAD = "This poll follows a rerun of failed jobs at this head."

    def test_a_gate_left_stale_by_a_rerun_is_rerun_by_the_poll_and_does_not_count_as_red(self):
        out = run_out(replies={"green-checks-1": red_read(self.STALE_GATE), "green-checks-2": green_read(SHA, required=["ci-tests"], passed=["ci-tests"])},
                      patch={"pr": {"green": red_read(RED)}, "fix-ci": self.RERAN})
        result, calls = out["result"], out["calls"]
        self.assertEqual(result["stage"], "done")
        names = labels(calls)
        self.assertEqual(names[names.index("pr"):], ["pr", "fix-ci", "green-checks-1", "green-checks-2", "land-take", "merge", "hold", "close-out"])
        self.assertIn("green-checks-1 reran a stale gate run (43286872194); polling once more", out["logs"])
        asked = prompt(calls, "green-checks-1")
        for needle in (self.STALE_LEAD, "a gate or aggregate job", "gh run view <run-id> --repo owner/repo --json updatedAt",
                       "Only when every failing check is stale",
                       "gh run rerun <run-id> --repo owner/repo --failed", "stale: the run ids you reran"):
            with self.subTest(needle=needle):
                self.assertIn(needle, asked)
        self.assertIn("stale", schema_of(calls, "green-checks-1")["properties"])
        self.assertNotIn(self.STALE_LEAD, prompt(calls, "green-checks-2"))
        self.assertNotIn("stale", schema_of(calls, "green-checks-2")["properties"])
        self.assertNotIn(self.STALE_LEAD, prompt(calls, "pr"))
    def test_a_check_still_red_after_the_stale_rerun_stops_as_the_ci_failure(self):
        for name, third in (("red", red_read(dict(RED, failing=["required-checks"]))), ("stale again", red_read(self.STALE_GATE))):
            with self.subTest(third=name):
                result, calls = run(replies={"green-checks-1": red_read(self.STALE_GATE), "green-checks-2": third},
                                    patch={"pr": {"green": red_read(RED)}, "fix-ci": self.RERAN})
                self.assertEqual((result["stage"], result["failing"]), ("checks", ["required-checks"]))
                names = labels(calls)
                self.assertEqual(names[names.index("pr"):], ["pr", "fix-ci", "green-checks-1", "green-checks-2"])
    def test_stale_is_read_only_from_the_poll_that_follows_a_rerun(self):
        # A first poll that names stale runs is a red poll like any other: it spends the one fix, and the next red poll stops.
        result, calls = run(replies={"green-checks-1": red_read(RED)}, patch={"pr": {"green": red_read(self.STALE_GATE)}, "fix-ci": self.RERAN})
        self.assertEqual(result["stage"], "checks")
        names = labels(calls)
        self.assertEqual(names[names.index("pr"):], ["pr", "fix-ci", "green-checks-1"])
        # The poll after a code fix moved the head is not asked either.
        result, calls = self.red_then(red_read(dict(self.STALE_GATE, head=FIX)))
        self.assertEqual(result["stage"], "checks")
        self.assertNotIn(self.STALE_LEAD, prompt(calls, "green-checks-1"))
        self.assertNotIn("green-checks-2", labels(calls))
    def test_the_ci_fix_prompt_reruns_every_failed_run_of_the_head_a_gate_included(self):
        _, calls = run(replies={"green-checks-1": green_read(SHA)},
                       patch={"setup": {"unset_env": ["GITHUB_TOKEN"]}, "pr": {"green": red_read(RED)}, "fix-ci": self.RERAN})
        text = prompt(calls, "fix-ci")
        for needle in (f"unset GITHUB_TOKEN && gh run list --repo owner/repo --commit {SHA} --json databaseId,workflowName,conclusion",
                       "keep the newest run of each workflowName (the highest databaseId; never an older run that one superseded)",
                       "rerun each of those whose conclusion is failure, cancelled or timed_out, not only the run of the check that broke first",
                       "a gate or aggregate check that failed only because another check failed is rerun too, with the same command"):
            with self.subTest(needle=needle):
                self.assertIn(needle, text)

    def test_the_ci_fix_prompt_tells_a_causeless_failure_to_rerun(self):
        _, calls = run(replies={"green-checks-1": green_read(SHA)},
                       patch={"setup": {"unset_env": ["GITHUB_TOKEN"]}, "pr": {"green": red_read(RED)}, "fix-ci": self.RERAN})
        text = prompt(calls, "fix-ci")
        for needle in ("no cause in the code", "change and commit nothing",
                       "unset GITHUB_TOKEN && gh run rerun <run-id> --repo owner/repo --failed",
                       "do not wait for them", f"head unchanged (commit equal to start_head, {SHA})",
                       "the program then polls the checks itself"):
            self.assertIn(needle, text)

    def test_a_sync_fix_at_the_unchanged_head_is_still_a_failure(self):
        # The rerun answer belongs to the CI fix alone: a sync fix with no commit and no rebuttal stops as before.
        result, calls = run(replies={"sync-review-1": FINDING},
                            patch={"land-take": {"behind": True},
                                   "sync-1": ABORTED, "sync-resolve-1": {"conflicted": True, "merge_commit": MERGE},
                                   "fix-sync-1": {"start_head": MERGE, "commit": MERGE, "notes": ""}})
        self.assertEqual(result["stage"], "sync-fix")
        for gone in ("fix-sync-review-1", "checks-2", "merge"):
            self.assertNotIn(gone, labels(calls))
        self.assertNotIn("gh run rerun", prompt(calls, "fix-sync-1"))

    def test_failed_check_on_another_head_is_head_moved_not_fixed(self):
        result, calls = run(patch={"pr": {"green": red_read(dict(RED, head="c" * 40))}})
        self.assertEqual(result["stage"], "head-moved")
        self.assertNotIn("fix-ci", labels(calls))

    def test_sync_review_finding_gets_one_fix_wave_then_merges(self):
        result, calls = run(replies={"sync-review-1": FINDING, "land-take": [{"behind": True}, {}]},
                            patch={"sync-1": ABORTED, "sync-resolve-1": {"conflicted": True, "merge_commit": MERGE, "resolved_files": ["a.py"]},
                                   "fix-sync-1": {"start_head": MERGE, "commit": FIX}})
        self.assertEqual(result["stage"], "done")
        names = labels(calls)
        self.assertEqual(names[names.index("sync-1"):names.index("merge")],
                         ["sync-1", "land-unlock", "sync-resolve-1", "sync-review-1", "fix-sync-1", "fix-sync-review-1", "land-push-2",
                          "green-checks-1", "land-take"])
        fix = prompt(calls, "fix-sync-1")
        self.assertIn(MERGE, fix)
        self.assertIn("dropped the new call site", fix)
        self.assertEqual([c["agentType"] for c in calls if c["label"] == "fix-sync-review-1"], ["reviewer"])
        self.assertIn(f"diff {MERGE}..{FIX}", prompt(calls, "fix-sync-review-1"))
        self.assertIn(f"--match-head-commit {FIX}", prompt(calls, "merge"))

    def test_failed_sync_fix_stops(self):
        result, calls = run(replies={"sync-review-1": FINDING},
                            patch={"land-take": {"behind": True},
                                   "sync-1": ABORTED, "sync-resolve-1": {"conflicted": True, "merge_commit": MERGE},
                                   "fix-sync-1": {"status": "blocked", "notes": "no"}})
        self.assertEqual(result["stage"], "sync-fix")
        self.assertNotIn("merge", labels(calls))

    def test_a_second_sync_review_finding_stops_without_a_second_wave(self):
        result, calls = run(replies={"sync-review-1": FINDING,
                                     "checks-2": {"state": "behind", "head": FIX}, "sync-review-2": FINDING},
                            patch={"land-take": {"behind": True},
                                   "sync-1": ABORTED, "sync-resolve-1": {"conflicted": True, "merge_commit": MERGE},
                                   "fix-sync-1": {"start_head": MERGE, "commit": FIX},
                                   "sync-2": ABORTED, "sync-resolve-2": {"conflicted": True, "merge_commit": "e" * 40}})
        self.assertEqual(result["stage"], "sync-review")
        self.assertEqual(result["cont"]["sync_fixes"], 1)
        self.assertNotIn("fix-sync-2", labels(calls))
        self.assertNotIn("merge", labels(calls))

    def test_a_fix_that_starts_from_another_head_stops_before_review(self):
        other = "c" * 40
        result, calls = run(patch={"pr": {"green": red_read(RED)}, "fix-ci": {"start_head": other, "commit": FIX}})
        self.assertEqual(result["stage"], "checks-fix")
        self.assertNotIn("fix-ci-review", labels(calls))
        self.assertNotIn("merge", labels(calls))
        result, calls = run(replies={"sync-review-1": FINDING},
                            patch={"land-take": {"behind": True},
                                   "sync-1": ABORTED, "sync-resolve-1": {"conflicted": True, "merge_commit": MERGE},
                                   "fix-sync-1": {"start_head": other, "commit": FIX}})
        self.assertEqual(result["stage"], "sync-fix")
        self.assertNotIn("fix-sync-review-1", labels(calls))
        self.assertNotIn("merge", labels(calls))

    def test_a_fix_start_head_in_short_form_is_the_same_head(self):
        result, calls = self.red_then(green_read(FIX), **{"fix-ci": {"start_head": SHA[:9], "commit": FIX}})
        self.assertEqual(result["stage"], "done")
        self.assertIn("fix-ci-review", labels(calls))

    def sync_rebuttal(self, review=None, **fix):
        replies = {"sync-review-1": FINDING, "land-take": [{"behind": True}, {}]}
        replies.update(review or {})
        return run(replies=replies,
                   patch={"sync-1": ABORTED, "sync-resolve-1": {"conflicted": True, "merge_commit": MERGE},
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
        result, _ = run(replies={"sync-1": None}, patch={"land-take": {"behind": True}})
        self.assertEqual(result["stage"], "sync")
        self.assertNotIn("checks_fixes", result["cont"])
        self.assertNotIn("sync_fixes", result["cont"])


class AllChecksTest(unittest.TestCase):
    """#756: the checks step waits for every check on head, required or not."""

    def test_checks_step_lists_every_check_and_can_answer_pending(self):
        _, calls = run(patch={"land-take": {"behind": True}})
        checks = prompt(calls, "checks-2")
        for argv in ("gh pr checks 42 --repo owner/repo --json name,bucket,link",
                     "gh api repos/owner/repo/rules/branches/dev"):
            self.assertIn(argv, checks)
        schema = schema_of(calls, "checks-2")
        self.assertIn("pending", schema["properties"])
        self.assertIn("pending", schema["properties"]["state"]["enum"])

    def test_a_pending_non_required_check_is_waited_for_before_the_merge(self):  # AC1
        waiting = green_read(required=["lint"], passed=["lint"], pending=["e2e"])
        green = green_read(required=["lint"], passed=["lint", "e2e"])
        result, calls = run(replies={"green-checks-1": green}, patch={"pr": {"green": waiting}})
        self.assertEqual(result["stage"], "done")
        names = labels(calls)
        self.assertEqual(names[names.index("pr"):],
                         ["pr", "green-checks-1", "land-take", "merge", "hold", "close-out"])

    def test_a_pending_state_is_waited_for_and_never_synced(self):
        result, calls = run(patch={"pr": {"green": green_read(state="pending", pending=["e2e"])}})
        self.assertEqual(result["stage"], "done")
        names = labels(calls)
        self.assertNotIn("sync-1", names)
        self.assertLess(names.index("green-checks-1"), names.index("land-take"))
        self.assertLess(names.index("land-take"), names.index("merge"))

    def test_checks_still_pending_after_three_waits_stop_unmerged(self):  # AC1
        waiting = green_read(state="pending", pending=["e2e"])
        result, calls = run(replies={f"green-checks-{k}": waiting for k in (1, 2)}, patch={"pr": {"green": waiting}})
        self.assertEqual((result["stage"], result["pending"]), ("checks-pending", ["e2e"]))
        self.assertIn("cont", result)
        names = labels(calls)
        self.assertNotIn("merge", names)
        self.assertNotIn("green-checks-3", names)
        # The lock was never asked for, so nothing is released.
        self.assertNotIn("land-take", names)
        self.assertEqual(names.count("land-unlock"), 0)

    def test_a_passed_reply_that_names_no_check_is_pending_and_never_merged(self):  # #1008
        empty = green_read(required=[], passed=[])
        result, calls = run(replies={f"green-checks-{k}": empty for k in (1, 2)}, patch={"pr": {"green": empty}})
        self.assertEqual((result["stage"], result["pending"]), ("checks-pending", []))
        self.assertIn("cont", result)
        names = labels(calls)
        self.assertNotIn("merge", names)
        self.assertNotIn("green-checks-3", names)

    def test_a_head_with_no_check_yet_is_polled_again_and_the_next_poll_decides(self):  # #1008
        empty = {"state": "passed", "head": SHA, "behind": False}
        result, calls = run(patch={"pr": {"green": empty}})
        self.assertEqual(result["stage"], "done")
        names = labels(calls)
        self.assertLess(names.index("green-checks-1"), names.index("merge"))
        result, calls = run(replies={"green-checks-1": {"state": "failed", "head": SHA, "behind": False, "failing": ["lint"]}},
                            patch={"pr": {"green": empty}})
        names = labels(calls)
        self.assertLess(names.index("green-checks-1"), names.index("fix-ci"))
        self.assertNotIn("land-take", names[:names.index("fix-ci")])

    def test_the_checks_prompt_calls_a_head_with_no_check_pending_and_reads_classic_protection(self):  # #1008
        _, calls = run(patch={"land-take": {"behind": True}})
        text = prompt(calls, "checks-2")
        self.assertIn("A head with no check reported at all is pending, never passed", text)
        self.assertIn("whenever that reply lists no required status checks, from classic branch protection", text)
        self.assertNotIn("none when neither answers", text)
        self.assertIn("passed (every name passing at head; a passed answer naming none is read as pending)", text)

    def test_a_poll_waits_for_the_first_check_before_it_answers_pending(self):  # #1008
        wait = ("While no check is reported on head, do not answer yet: read the list again about once a minute, running alone "
                "timeout 60 tail -f /dev/null between two reads (this step's own wait, which ends by itself with exit 124), and "
                "answer pending only when none is reported 5 minutes after your first read of the list.")
        beat = ("While no check is reported on head, do not answer yet: read the list again about once a minute, running alone "
                f"forge-claim land hold --repo owner/repo --branch dev --sha {SHA} --seconds 60 between two reads (it beats the lease and returns "
                "by itself), and answer pending only when none is reported 5 minutes after your first read of the list.")
        look = ("While no check is reported on the pull request at all, do not answer yet: read gh pr checks <the PR number> --repo owner/repo "
                "--json name,bucket,link about once a minute, running alone timeout 60 tail -f /dev/null between two reads (this step's own wait, "
                "which ends by itself with exit 124), and answer pending only when none is reported 5 minutes after your first read.")
        _, calls = run(patch={"land-take": {"behind": True}})
        self.assertEqual(prompt(calls, "pr").count(look), 1)
        self.assertEqual(prompt(calls, "checks-2").count(beat), 1)
        self.assertNotIn(wait, prompt(calls, "checks-2"))

    def test_a_failing_non_required_check_stops_the_merge_named(self):  # AC2
        red = {"state": "passed", "head": SHA, "required": ["lint"], "passed": ["lint"], "failing": ["e2e"],
               "details": "e2e: 2 failed"}
        result, calls = run(replies={"green-checks-1": red_read(dict(red, head=FIX))},
                            patch={"pr": {"green": red_read(red)}, "fix-ci": {"start_head": SHA, "commit": FIX}})
        self.assertEqual((result["stage"], result["failing"]), ("checks", ["e2e"]))
        self.assertNotIn("merge", labels(calls))
        self.assertIn("e2e", prompt(calls, "fix-ci"))

    def test_an_explicit_failed_state_outranks_a_pending_list(self):  # AC2
        red = {"state": "failed", "head": SHA, "pending": ["slow"], "details": "e2e failed"}
        result, calls = run(replies={"green-checks-1": red_read(dict(red, head=FIX))},
                            patch={"pr": {"green": red_read(red)}, "fix-ci": {"start_head": SHA, "commit": FIX}})
        self.assertEqual(result["stage"], "checks")
        self.assertEqual(result["checks"]["details"], "e2e failed")
        self.assertIn("e2e failed", prompt(calls, "fix-ci"))
        self.assertNotIn("green-checks-2", labels(calls))
        self.assertNotIn("merge", labels(calls))


class ShaNormalisationTest(unittest.TestCase):
    """#649 defect 1: a head reported in short form is the same head; a different head still stops."""

    def test_short_checks_head_is_accepted_and_the_merge_uses_the_full_sha(self):
        for short in (SHA[:7], SHA[:12], SHA.upper()[:10], f" {SHA[:9]}\n"):
            with self.subTest(short=short):
                result, calls = run(patch={"pr": {"green": green_read(short)}})
                self.assertEqual(result["stage"], "done")
                self.assertIn(f"--match-head-commit {SHA}", prompt(calls, "merge"))

    def test_short_pr_head_is_accepted(self):
        result, calls = run(patch={"pr": {"head": SHA[:8]}})
        self.assertEqual(result["stage"], "done")
        self.assertIn("merge", labels(calls))

    def test_a_different_or_too_short_head_still_stops(self):
        for head in ("c" * 40, "c" * 8, SHA[:6], "", "zzzzzzzzzz"):
            with self.subTest(head=head):
                result, calls = run(patch={"pr": {"green": green_read(head)}})
                self.assertEqual(result["stage"], "head-moved")
                self.assertNotIn("land-take", labels(calls))
                self.assertNotIn("merge", labels(calls))
                result, calls = run(patch={"pr": {"head": head}})
                self.assertEqual(result["stage"], "head-moved")
                self.assertFalse([n for n in labels(calls) if n.startswith("checks-")])

    def test_head_fields_require_a_full_sha_in_the_schema(self):
        _, calls = run(patch={"land-take": {"behind": True}})
        for label, field in (("pr", "head"), ("checks-2", "head"), ("verify", "head"), ("sync-1", "merge_commit")):
            with self.subTest(label=label):
                self.assertEqual(schema_of(calls, label)["properties"][field]["pattern"], "^[0-9a-f]{40}$")
        with self.subTest(label="pr green"):
            self.assertEqual(member(schema_of(calls, "pr"), "green")["properties"]["head"]["pattern"], "^[0-9a-f]{40}$")

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
                                                       "pr": {"green": green_read(SHA[:8])}})
        self.assertEqual(result["stage"], "done")
        self.assertNotIn("verify", labels(calls))
        self.assertIn(f"--match-head-commit {SHA} ", prompt(calls, "merge") + " ")
        other = SHA[:9] + "0" * 31
        result, calls = run(args=dict(ARGS, cont=cont), patch={"setup": {"head": SHA},
                                                       "pr": {"green": green_read(other)}})
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
        self.assertEqual(labels(calls), ["setup", "hold-draft", "hold", "close-out"])
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

    ASKED = dict(HUMAN["verify"], ac="AC2")

    def test_a_posted_human_check_for_an_evidence_criterion_is_refused_before_the_once_run(self):
        for issue in (9, 51):
            with self.subTest(issue=issue):
                posted = [{"issue": issue, "merge": self.MERGE, "checks": [self.ASKED]}]
                result, calls = self.ship(EVIDENCE, **{"hold-draft": {"posted": posted}})
                self.assertEqual((result["stage"], result["human_checks"], result["posted_holds"]),
                                 ("hold", ["AC2"], [issue]))
                self.assertIn(f"#{issue}", result["details"])
                self.assertNotIn("hold", labels(calls))
                self.assertNotIn("close-out", labels(calls))

    def test_a_check_that_asks_the_owner_for_an_evidence_criterion_is_never_drafted_for_the_hold(self):
        code = {"id": "AC1", "text": "works", "kind": "code"}
        cases = (
            (criterion(EVIDENCE, verify_kind="human", verify_run=HUMAN["verify"]["run"], verify_reason="hands"), {}),
            (criterion(EVIDENCE, verify_run=HUMAN["verify"]["run"]), {}),
            (criterion(EVIDENCE, verify=None), {"hold-draft": {"written": [self.ASKED]}}),
        )
        for n, (bad, extra) in enumerate(cases):
            with self.subTest(case=n):
                result, calls = run(args=DIRECT, patch=dict({"direct-impl": {"acceptance": [code, bad]}}, **extra))
                self.assertEqual((result["stage"], result["human_checks"], result["posted_holds"]),
                                 ("hold", ["AC2"], []))
                self.assertIn("hold-draft", labels(calls))
                self.assertNotIn("hold", labels(calls))
        bad = criterion(EVIDENCE, verify=None)
        result, calls = run(args=DIRECT, patch={"direct-impl": {"acceptance": [code, bad]}, "hold-draft": {"written": []}})
        self.assertEqual((result["stage"], result["missing_checks"]), ("hold", ["AC2"]))
        self.assertNotIn("hold", labels(calls))

    def test_a_hold_draft_that_cannot_be_read_holds_nothing(self):
        for patch in ({"complete": False}, {"posted": [{"issue": "9", "checks": []}]}, {"written": None}):
            with self.subTest(patch=patch):
                result, calls = self.ship(EVIDENCE, **{"hold-draft": patch})
                self.assertEqual(result["stage"], "hold")
                self.assertIn("draft", result)
                self.assertNotIn("hold", labels(calls))
        result, calls = self.ship(close="CLOSED")
        self.assertNotIn("hold-draft", labels(calls))
        self.assertEqual(result["stage"], "done")

    def test_a_hold_that_makes_an_evidence_or_code_criterion_a_human_check_is_refused(self):
        asked = self.ASKED
        cases = (
            ((EVIDENCE,), [asked], ["AC2"]),
            ((EVIDENCE,), [EVIDENCE["verify"], dict(HUMAN["verify"], ac="AC1")], ["AC1"]),
            ((EVIDENCE,), [dict(HUMAN["verify"], ac="ac2")], ["AC2"]),
            ((EVIDENCE, HUMAN), [dict(HUMAN["verify"], ac="ac2"), dict(HUMAN["verify"], ac="ac3")], ["AC2"]),
        )
        for criteria, checks, expected in cases:
            with self.subTest(checks=checks):
                result, calls = self.ship(*criteria, hold={"block": {"v": 1, "merge": self.MERGE, "checks": checks}})
                self.assertEqual((result["stage"], result["human_checks"], result["posted_holds"]),
                                 ("hold", expected, [9]))
                self.assertIn("#9", result["details"])
                self.assertNotIn("close-out", labels(calls))
        result, _ = self.ship(EVIDENCE, hold={"code_unmet": ["AC1"],
                                              "block": {"v": 1, "merge": self.MERGE, "checks": [asked]}})
        self.assertEqual(result["stage"], "code-unmet")

    def test_a_split_child_that_makes_an_evidence_criterion_a_human_check_is_refused(self):
        child = dict(self.CHILD, ac="AC2", issue=51, block={"v": 1, "merge": self.MERGE, "checks": [self.ASKED]})
        result, calls = self.ship(HUMAN, EVIDENCE, hold={"blocks": [12], "split": [self.CHILD, child],
                                                         "issue_state": "CLOSED", "block": None, "lint": None,
                                                         "verify_run": None}, close="CLOSED")
        self.assertEqual((result["stage"], result["human_checks"], result["posted_holds"]), ("hold", ["AC2"], [51]))
        self.assertIn("#51", result["details"])
        self.assertNotIn("close-out", labels(calls))

    def test_a_human_criterion_is_still_held_as_a_human_check(self):
        result, calls = self.ship(EVIDENCE, HUMAN)
        self.assertEqual(result["stage"], "done")
        self.assertNotIn("human_checks", result)
        checks = checks_of(calls)
        self.assertEqual([c for c in checks if c["ac"] == "AC3"], [HUMAN["verify"]])
        scripted = json.loads(json.dumps(criterion(EVIDENCE)["verify"]).replace(SHA, self.MERGE))
        self.assertIn(scripted, checks)
        self.assertEqual(prompt(calls, "hold").count("verify-pending run --host h1 --repo owner/repo --issue 9"), 1)

    PROBE = dict(EVIDENCE["verify"], when={"deployed_includes": MERGE}, run={"probe": "deployed_includes", "sha": MERGE})
    SCRIPT = dict(SCRIPTED["verify"], when={"deployed_includes": MERGE})
    CODE = {"id": "AC1", "text": "works", "kind": "code"}

    def direct(self, bad, hold=None, **patch):
        """The direct lane, whose one evidence or human criterion carries what `bad` says."""
        replies = {} if hold is None else {"hold": dict(self.HOLD, block={"v": 1, "merge": self.MERGE, "checks": hold})}
        return run(args=DIRECT, replies=replies,
                   patch=dict({"direct-impl": {"acceptance": [self.CODE, bad]}, "merge": {"merge_commit": self.MERGE},
                               "close-out": {"issue_state": "OPEN"}}, **patch))

    def test_the_hold_reports_a_criterion_it_would_not_make_a_human_check(self):
        """#1281 AC2: every refusal names the criterion, in human_checks and in the explanation for the owner."""
        posted = [{"issue": 51, "merge": self.MERGE, "checks": [self.ASKED]}]
        child = dict(self.CHILD, ac="AC2", issue=52, block={"v": 1, "merge": self.MERGE, "checks": [self.ASKED]})
        cases = (
            self.ship(EVIDENCE, **{"hold-draft": {"posted": posted}}),
            self.ship(EVIDENCE, hold={"block": {"v": 1, "merge": self.MERGE, "checks": [self.ASKED]}}),
            self.ship(HUMAN, EVIDENCE, hold={"blocks": [12], "split": [self.CHILD, child], "issue_state": "CLOSED",
                                             "block": None, "lint": None, "verify_run": None}, close="CLOSED"),
        )
        for n, (result, calls) in enumerate(cases):
            with self.subTest(case=n):
                self.assertEqual((result["stage"], result["human_checks"]), ("hold", ["AC2"]))
                self.assertIn("AC2", result["details"])
                self.assertNotIn("AC3", result["details"])
                self.assertNotIn("close-out", labels(calls))

    def test_a_verify_member_that_asks_the_owner_for_an_evidence_criterion_stops_before_the_hold(self):
        for verify in ({"verify_kind": "human", "verify_run": HUMAN["verify"]["run"], "verify_reason": "hands"},
                       {"verify_run": HUMAN["verify"]["run"]}):
            with self.subTest(verify=verify):
                result, calls = self.direct(criterion(EVIDENCE, **verify))
                self.assertEqual((result["stage"], result["human_checks"], result["posted_holds"]), ("hold", ["AC2"], []))
                self.assertIn("AC2", result["details"])
                self.assertIn("hold-draft", labels(calls))
                self.assertNotIn("hold", labels(calls))

    def test_a_retry_whose_parent_fence_omits_a_scripted_criterion_is_refused_before_the_once_run(self):
        plan = with_criteria(SCRIPTED, HUMAN, scripts=["scripts/count-generated"])
        for checks in ([HUMAN["verify"]], []):
            with self.subTest(checks=checks):
                posted = [{"issue": 9, "merge": self.MERGE, "checks": checks}]
                result, calls = run(replies={"plan": plan},
                                    patch={"merge": {"merge_commit": self.MERGE}, "close-out": {"issue_state": "OPEN"},
                                           "hold-draft": {"posted": posted}})
                self.assertEqual((result["stage"], result["script_checks"], result["posted_holds"]), ("hold", ["AC2"], [9]))
                self.assertNotIn("hold", labels(calls))
        posted = [{"issue": 9, "merge": self.MERGE, "checks": [HUMAN["verify"], self.SCRIPT]}]
        result, calls = run(replies={"plan": plan},
                            patch={"merge": {"merge_commit": self.MERGE}, "close-out": {"issue_state": "OPEN"},
                                   "hold-draft": {"posted": posted}})
        self.assertEqual(result["stage"], "done")
        self.assertIn("hold", labels(calls))

    def test_a_retry_whose_parent_fence_omits_an_open_criterion_is_refused_before_the_once_run(self):
        """#1281: the once-run closes the issue on the posted fence, so a criterion it lacks (human or evidence) stops the hold first."""
        held = json.loads(json.dumps(EVIDENCE["verify"]).replace(SHA, self.MERGE))
        for n, (criteria, checks, expected) in enumerate((
            ((EVIDENCE, HUMAN), [held], ["AC3"]),
            ((EVIDENCE, HUMAN), [HUMAN["verify"]], ["AC2"]),
            ((EVIDENCE, HUMAN), [held, dict(HUMAN["verify"], ac="ac3")], []),
        )):
            with self.subTest(case=n):
                posted = [{"issue": 9, "merge": self.MERGE, "checks": checks}]
                result, calls = self.ship(*criteria, **{"hold-draft": {"posted": posted}})
                if expected:
                    self.assertEqual((result["stage"], result["missing_checks"]), ("hold", expected))
                    self.assertNotIn("hold", labels(calls))
                    self.assertNotIn("close-out", labels(calls))
                else:
                    self.assertEqual(result["stage"], "done")
        child = {"issue": 51, "merge": self.MERGE, "checks": [HUMAN["verify"]]}
        for merge, stage in ((self.MERGE, "done"), ("e" * 40, "hold")):
            with self.subTest(child_merge=merge):
                posted = [{"issue": 9, "merge": self.MERGE, "checks": [held]}, dict(child, merge=merge)]
                result, calls = self.ship(EVIDENCE, HUMAN, **{"hold-draft": {"posted": posted}})
                self.assertEqual(result["stage"], stage)
                self.assertEqual("hold" in labels(calls), stage == "done")

    def test_a_script_the_draft_wrote_is_held_unchanged(self):
        bad = criterion(EVIDENCE, verify=None)
        written = {"hold-draft": {"written": [self.SCRIPT]}}
        for name, checks in (("probe", [self.PROBE]), ("args", [dict(self.SCRIPT, run={"script": "scripts/count-generated", "args": ["-x"]})])):
            with self.subTest(case=name):
                result, calls = self.direct(bad, hold=checks, **written)
                self.assertEqual((result["stage"], result["script_checks"]), ("hold", ["AC2"]))
                self.assertNotIn("close-out", labels(calls))
        result, calls = self.direct(bad, hold=[self.SCRIPT], **written)
        self.assertEqual(result["stage"], "done")
        result, calls = self.direct(bad, **written)
        self.assertEqual((result["stage"], checks_of(calls)), ("done", [self.SCRIPT]))
        posted = {"hold-draft": {"written": [self.SCRIPT], "posted": [{"issue": 9, "merge": self.MERGE, "checks": [self.PROBE]}]}}
        result, calls = self.direct(bad, **posted)
        self.assertEqual((result["stage"], result["script_checks"], result["posted_holds"]), ("hold", ["AC2"], [9]))
        self.assertNotIn("hold", labels(calls))

    def test_a_human_criterion_is_held_only_as_a_check_that_asks_the_owner(self):
        bad = criterion(HUMAN, verify=None)
        result, calls = self.direct(bad, **{"hold-draft": {"written": [dict(self.PROBE, ac="AC3")]}})
        self.assertEqual((result["stage"], result["missing_checks"]), ("hold", ["AC3"]))
        self.assertNotIn("hold", labels(calls))
        probe = dict(self.PROBE, ac="AC3")
        for n, (result, calls) in enumerate((
            self.ship(HUMAN, **{"hold-draft": {"posted": [{"issue": 9, "merge": self.MERGE, "checks": [probe]}]}}),
            self.ship(HUMAN, hold={"block": {"v": 1, "merge": self.MERGE, "checks": [probe]}}),
        )):
            with self.subTest(case=n):
                self.assertEqual((result["stage"], result["owner_checks"], result["posted_holds"]), ("hold", ["AC3"], [9]))
                self.assertIn("AC3", result["details"])
                self.assertNotIn("close-out", labels(calls))
        self.assertNotIn("hold", labels(self.ship(HUMAN, **{"hold-draft": {"posted": [{"issue": 9, "merge": self.MERGE, "checks": [probe]}]}})[1]))
        child = dict(self.CHILD, block={"v": 1, "merge": self.MERGE, "checks": [probe]})
        result, calls = self.ship(HUMAN, hold={"blocks": [12], "split": [child], "issue_state": "CLOSED",
                                               "block": None, "lint": None, "verify_run": None}, close="CLOSED")
        self.assertEqual((result["stage"], result["bad_split"]), ("hold", ["AC3"]))
        self.assertNotIn("close-out", labels(calls))

    def test_a_command_outside_the_verification_ids_is_refused_before_the_hold(self):
        outside = {"command": "not-a-verification-id"}
        for n, (bad, extra) in enumerate((
            (criterion(EVIDENCE, verify_run=outside), {}),
            (criterion(EVIDENCE, verify=None), {"hold-draft": {"written": [dict(EVIDENCE["verify"], run=outside)]}}),
        )):
            with self.subTest(case=n):
                result, calls = self.direct(bad, **extra)
                self.assertEqual((result["stage"], result["unattended"]), ("hold", ["AC2"]))
                self.assertIn("hold-draft", labels(calls))
                self.assertNotIn("hold", labels(calls))

    def scripted(self, checks, posted=None):
        patch = {"merge": {"merge_commit": self.MERGE}, "close-out": {"issue_state": "OPEN"}}
        if posted is not None:
            patch["hold-draft"] = {"posted": posted}
        return run(replies={"plan": SCRIPTED_PLAN,
                            "hold": dict(self.HOLD, block={"v": 1, "merge": self.MERGE, "checks": checks})}, patch=patch)

    def test_an_evidence_criterion_is_held_with_its_committed_script(self):
        with tempfile.TemporaryDirectory() as scratch:
            scratch = Path(scratch).resolve()
            home = scratch / "home"
            (home / ".agents" / "share").mkdir(parents=True)
            shutil.copy(MANIFEST, home / ".agents" / "share" / "platform-manifest.json")
            repo = scratch / "repo"
            shutil.copytree(FIXTURE, repo)
            (repo / "scripts").mkdir()
            script = repo / "scripts" / "count-generated"
            script.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            script.chmod(0o755)
            env = {**os.environ, "HOME": str(home), "PYTHONPATH": str(REPO_ROOT / "python"), **HERMETIC_GIT}
            for name in SCRUBBED:
                env.pop(name, None)

            def git(*args):
                return subprocess.run(["git", "-C", str(repo), *args], env=env, check=True,
                                      capture_output=True, text=True).stdout.strip()

            def lint(payload, head):
                path = scratch / "block.json"
                path.write_text(json.dumps({"v": 1, "merge": head, "checks": payload}), encoding="utf-8")
                done = subprocess.run([sys.executable, "-m", "agent_tools.verification.verify_pending", "lint",
                                       "--input", str(path), "--repo-root", str(repo)],
                                      env=env, capture_output=True, text=True, timeout=60)
                return done, json.loads(done.stdout)

            git("init", "-q", "-b", "main")
            git("config", "commit.gpgsign", "false")
            git("add", "-A")
            git("commit", "-q", "-m", "fixture")
            head = git("rev-parse", "HEAD")
            result, calls = run(replies={"plan": SCRIPTED_PLAN},
                                patch={"merge": {"merge_commit": head}, "close-out": {"issue_state": "OPEN"}})
            self.assertEqual(result["stage"], "done")
            payload = checks_of(calls)
            self.assertEqual([c["ac"] for c in payload], ["AC2"])
            self.assertEqual(payload[0]["kind"], "evidence")
            self.assertEqual(payload[0]["run"], {"script": "scripts/count-generated"})
            self.assertFalse([c for c in payload if c["kind"] == "human"])
            done, verdict = lint(payload, head)
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
            self.assertEqual(verdict["errors"], [])
            script.chmod(0o644)
            git("add", "-A")
            git("commit", "-q", "-m", "drop the executable bit")
            done, verdict = lint(payload, git("rev-parse", "HEAD"))
            self.assertIn(("checks[0].run.script", "not_committed"),
                          [(e["field"], e["code"]) for e in verdict["errors"]])

    def test_a_scripted_evidence_criterion_held_without_its_script_is_refused(self):
        script_check = dict(SCRIPTED["verify"], when={"deployed_includes": self.MERGE})
        probe = {"probe": "deployed_includes", "sha": self.MERGE}
        cases = {
            "a": [dict(EVIDENCE["verify"], when={"deployed_includes": self.MERGE}, run=probe)],
            "b": [dict(script_check, run={"script": "scripts/other"})],
            "c": [dict(script_check, run={"script": "scripts/count-generated", "at": "e" * 40})],
            "d": [dict(script_check, run={"script": "scripts/count-generated", "args": ["--all"]})],
            "e": [script_check, dict(script_check, run=probe)],
        }
        for name, checks in cases.items():
            with self.subTest(case=name):
                result, calls = self.scripted(checks)
                self.assertEqual((result["stage"], result["script_checks"], result["posted_holds"]),
                                 ("hold", ["AC2"], [9]))
                self.assertNotIn("close-out", labels(calls))
        with self.subTest(case="f"):
            posted = [{"issue": 9, "merge": self.MERGE,
                       "checks": [dict(script_check, run={"script": "scripts/other"})]}]
            result, calls = self.scripted([script_check], posted=posted)
            self.assertEqual((result["stage"], result["script_checks"], result["posted_holds"]),
                             ("hold", ["AC2"], [9]))
            self.assertNotIn("hold", labels(calls))

    def test_a_scripted_evidence_criterion_held_with_the_same_invocation_is_accepted(self):
        script_check = dict(SCRIPTED["verify"], when={"deployed_includes": self.MERGE})
        with self.subTest(case="a"):
            result, _ = self.scripted([dict(script_check, run={"script": "scripts/count-generated", "at": self.MERGE})])
            self.assertEqual(result["stage"], "done")
        with self.subTest(case="b"):
            pinned = criterion(SCRIPTED, verify_run={"script": "scripts/count-generated", "at": SHA})
            result, _ = run(replies={"plan": with_criteria(pinned, scripts=["scripts/count-generated"]),
                                     "hold": dict(self.HOLD, block={"v": 1, "merge": self.MERGE,
                                                                    "checks": [script_check]})},
                            patch={"merge": {"merge_commit": self.MERGE}, "close-out": {"issue_state": "OPEN"}})
            self.assertEqual(result["stage"], "done")

    def test_a_split_child_of_a_scripted_evidence_criterion_is_refused(self):
        probe = dict(EVIDENCE["verify"], when={"deployed_includes": self.MERGE},
                     run={"probe": "deployed_includes", "sha": self.MERGE})
        child = dict(self.CHILD, ac="AC2", issue=51, block={"v": 1, "merge": self.MERGE, "checks": [probe]})
        result, calls = run(replies={"plan": with_criteria(HUMAN, SCRIPTED, scripts=["scripts/count-generated"]),
                                     "hold": dict(self.HOLD, blocks=[12], split=[self.CHILD, child],
                                                  block={"v": 1, "merge": self.MERGE, "checks": []})},
                            patch={"merge": {"merge_commit": self.MERGE}, "close-out": {"issue_state": "OPEN"}})
        self.assertEqual((result["stage"], result["bad_split"]), ("hold", ["AC2"]))
        self.assertNotIn("close-out", labels(calls))


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
        blank = lambda text: re.sub(r"Findings: \[.*?\]\. ", "Findings: []. ", re.sub(r"\b[def]{40}\b", "SHA", text))
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

    def test_a_lost_rereview_keeps_its_findings_and_a_clean_delivery_carries_nothing(self):
        lost, _ = run(replies={"final-1": self.FIRST, "fix-wave-review": None})
        self.assertEqual(lost["stage"], "fix-wave-review")
        self.assertEqual([f["summary"] for f in lost["cont"]["fix_findings"]], ["race in acquire"])
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

    def test_findings_the_bound_cut_bring_a_full_review_on_resume(self):
        many = narrow(*[f"race {i} " + "x" * 900 for i in range(14)], failing_input="y" * 900)
        stopped, _ = run(replies={"final-1": self.FIRST, "fix-wave-review": self.AFTER_1, "fix-wave-review-2": many})
        self.assertEqual(stopped["cont"]["fix_findings_dropped"], 4)
        out = run_out(args=dict(ARGS, cont=stopped["cont"]), replies={"verify": None}, patch={"setup": {"head": "e" * 40}})
        self.assertIn("final-1", labels(out["calls"]))
        self.assertNotIn("final-scoped", labels(out["calls"]))
        wave = prompt(out["calls"], "fix-wave")
        for i in range(10):
            self.assertIn(f"race {i} ", wave)
        self.assertIn("4 open finding(s) were not kept in cont: this round reviews the whole delivery", json.dumps(out["logs"]))
        self.assertEqual(out["result"]["stage"], "verify")
        self.assertNotIn("fix_findings_dropped", out["result"]["cont"])

    def stopped(self):
        left = narrow("race in adopt", failing_input="two adopters")
        result, _ = run(replies=self.replies(**{"fix-wave-review-3": left}))
        return result["cont"]

    def test_a_resume_feeds_the_carried_findings_to_the_first_wave(self):
        fresh = {"verdict": "findings", "findings": [{"severity": "important", "file": "lock.py", "summary": "stale lock"}]}
        result, calls = run(args=dict(ARGS, cont=self.stopped()), replies={"final-scoped": fresh})
        self.assertEqual((result["stage"], result["fix_waves"]), ("done", 4))
        self.assertEqual(waves(calls), self.THREE[:2])
        self.assertIn("final-scoped", labels(calls))
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
        _, calls = run(args=dict(ARGS, cont=self.stopped()), replies={"final-scoped": fresh}, patch={"fix-wave": self.NOTHING})
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
        _, calls = run(args=dict(ARGS, cont=self.stopped()), replies={"final-scoped": fresh})
        wave = prompt(calls, "fix-wave")
        self.assertIn("Race  in ADOPT", wave)
        self.assertNotIn("race in adopt", wave)
        self.assertNotIn("left open by an earlier run", wave)

    def test_the_carried_findings_last_until_a_wave_takes_them(self):
        cont = self.stopped()
        for replies in ({"final-scoped": None}, {"fix-wave": None}):
            with self.subTest(replies=replies):
                result, _ = run(args=dict(ARGS, cont=cont), replies=replies)
                self.assertIn(result["stage"], ("final-review", "fix-wave"))
                self.assertEqual(result["cont"]["fix_findings"], cont["fix_findings"])
        # #1370: a wave that answered and failed, and a lost re-review, keep them too: the next round re-checks each against the head.
        for reply in ({"status": "blocked", "notes": "no"}, {"status": "done", "start_head": "d" * 40, "notes": "nothing to do"}):
            with self.subTest(reply=reply):
                out = run_out(args=dict(ARGS, cont=cont), replies={"fix-wave": reply})
                self.assertEqual(out["result"]["stage"], "fix-wave")
                self.assertEqual(out["result"]["cont"]["fix_findings"], cont["fix_findings"])
                self.assertIn("fix-wave: 1 open finding(s) kept in cont after a wave that failed", json.dumps(out))
        taken, _ = run(args=dict(ARGS, cont=cont), replies={"verify": None})
        self.assertEqual(taken["stage"], "verify")
        self.assertNotIn("fix_findings", taken["cont"])
        resolved, _ = run(args=dict(ARGS, cont=cont), replies={"fix-wave-review": None})
        self.assertEqual(resolved["cont"]["fix_findings"], cont["fix_findings"])

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
        result, _ = run(args=dict(ARGS, cont=cont), replies={"final-scoped": self.left(), "fix-wave-review": self.left()})
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


R = "d" * 40
H = "e" * 40
SCOPED_FIRST = {"verdict": "findings", "findings": [{"severity": "critical", "file": "lock.py", "summary": "leak"}]}
SCOPED_NEW = {"verdict": "findings", "findings": [{"severity": "important", "file": "claim.py", "summary": "race in steal", "relation": "new"}]}
AMENDED = (" The owner amended the plan since the last review (plan.md, Amendments): grade the head against the amended tasks "
           "and acceptance criteria, not only the commits above.")


def scoped_first_stop():
    """#1370: the cont of a first run stopped after its re-review, one finding left open in claim.py."""
    result, _ = run(replies={"final-1": SCOPED_FIRST, "fix-wave-review": SCOPED_NEW},
                    patch={"fix-wave": {"start_head": "c0ffee", "commit": R}})
    assert result["stage"] == "fix-wave-review", result["stage"]
    cont = result["cont"]
    assert [f["summary"] for f in cont["fix_findings"]] == ["race in steal"], cont["fix_findings"]
    assert cont["reviewed"] == {"head": R}, cont["reviewed"]
    return cont


def scoped_resume(cont, replies=None, patch=None, args=None):
    return run(args=dict(args or ARGS, cont=cont), replies=replies, patch=dict({"setup": {"head": H}}, **(patch or {})))


class ScopedReviewRoundTest(unittest.TestCase):
    """#1370: the rounds after the first full final review read only what changed since the head the last review read."""

    def test_a_first_full_review_counts_one_round_and_records_the_head_it_read(self):
        cont = scoped_first_stop()
        self.assertEqual((cont["review_rounds"], cont["reviewed"]), (1, {"head": R}))
        clean, _ = run(replies={"verify": None})
        self.assertEqual(clean["stage"], "verify")
        self.assertEqual((clean["cont"]["review_rounds"], clean["cont"]["reviewed"]), (1, {"head": "c0ffee"}))
        lost, _ = run(replies={"final-1": None})
        self.assertEqual(lost["stage"], "final-review")
        self.assertNotIn("review_rounds", lost["cont"])
        self.assertNotIn("reviewed", lost["cont"])

    def test_a_resume_reviews_only_the_new_commits_and_the_carried_findings(self):
        first = run_out(args=SIZED, replies=dict(sized(1501), **{"final-1": SCOPED_FIRST, "fix-wave-review": SCOPED_NEW}),
                        patch={"fix-wave": {"start_head": "c0ffee4", "commit": R}})
        for label in ("diff-size", "final-1", "final-2", "final-codex", "final-integration"):
            self.assertIn(label, labels(first["calls"]))
        self.assertEqual(first["result"]["stage"], "fix-wave-review")
        self.assertEqual(first["result"]["cont"]["reviewed"], {"head": R})
        result, calls = run(args=dict(SIZED, cont=first["result"]["cont"]), replies={"verify": None}, patch={"setup": {"head": H}})
        names = labels(calls)
        self.assertIn("final-scoped", names)
        for label in ("final-1", "final-2", "final-codex", "final-integration", "diff-size"):
            self.assertNotIn(label, names)
        scoped = prompt(calls, "final-scoped")
        wt = "git -C /r/.wt/w-issue-9-x"
        for needle in (f"{wt} merge-base --is-ancestor {R} {H}", f"{wt} log -p --no-merges {R}..{H} ^origin/dev",
                       f"{wt} rev-list --merges {R}..{H} ^origin/dev", "show --remerge-diff", f"{wt} diff {R} {H}",
                       "race in steal", "return closed"):
            self.assertIn(needle, scoped)
        self.assertNotIn("origin/dev...HEAD", scoped)
        self.assertIn("race in steal", prompt(calls, "fix-wave"))
        self.assertEqual((result["stage"], result["cont"]["review_rounds"]), ("verify", 2))
        self.assertEqual({c["label"]: c for c in calls}["final-scoped"]["agentType"], "reviewer")
        props = schema_of(calls, "final-scoped")["properties"]
        self.assertEqual(props["closed"], {"type": "array", "items": {"type": "integer"}})
        self.assertEqual(props["head"], {"type": "string"})

    def test_a_carried_finding_the_scoped_reviewer_closes_needs_no_fix_wave(self):
        cont = scoped_first_stop()
        closed, calls = scoped_resume(cont, replies={"final-scoped": {"verdict": "pass", "findings": [], "closed": [1]}, "verify": None})
        self.assertFalse([name for name in labels(calls) if name.startswith("fix-wave")])
        self.assertEqual(closed["stage"], "verify")
        self.assertNotIn("fix_findings", closed["cont"])
        self.assertEqual((closed["cont"]["review_rounds"], closed["cont"]["reviewed"]), (2, {"head": H}))
        for numbers in ([7], [], [0], [1.5], ["1"]):
            with self.subTest(closed=numbers):
                _, calls = scoped_resume(cont, replies={"final-scoped": {"verdict": "pass", "findings": [], "closed": numbers}, "verify": None})
                wave = prompt(calls, "fix-wave")
                self.assertIn("race in steal", wave)
                self.assertIn("The last 1 were left open by an earlier run's fix waves", wave)

    def test_a_resume_on_the_reviewed_head_still_runs_the_scoped_reviewer(self):
        result, calls = run(args=dict(ARGS, cont=scoped_first_stop()), replies={"verify": None}, patch={"setup": {"head": R}})
        self.assertIn("final-scoped", labels(calls))
        self.assertNotIn("final-1", labels(calls))
        self.assertEqual(result["cont"]["review_rounds"], 2)

    def test_a_resume_with_no_head_read_reviews_up_to_HEAD_and_records_the_head_the_reviewer_read(self):
        cont = scoped_first_stop()
        for said, expected in (("9" * 40, "9" * 40), ("HEAD", R)):
            with self.subTest(head=said):
                result, calls = run(args=dict(ARGS, cont=cont), replies={
                    "final-scoped": {"verdict": "pass", "findings": [], "closed": [1], "head": said}, "verify": None})
                scoped = prompt(calls, "final-scoped")
                self.assertIn(f"log -p --no-merges {R}..HEAD ^origin/dev", scoped)
                self.assertIn("rev-parse HEAD", scoped)
                self.assertEqual(result["cont"]["reviewed"], {"head": expected})

    def test_a_failed_wave_and_a_lost_re_review_keep_the_open_findings(self):
        failed, _ = run(replies={"final-1": SCOPED_FIRST, "fix-wave": {"status": "blocked", "notes": "no"}})
        lost, _ = run(replies={"final-1": SCOPED_FIRST, "fix-wave-review": None}, patch={"fix-wave": {"start_head": "c0ffee", "commit": R}})
        for stage, result in (("fix-wave", failed), ("fix-wave-review", lost)):
            with self.subTest(stage=stage):
                self.assertEqual(result["stage"], stage)
                self.assertEqual([f["summary"] for f in result["cont"]["fix_findings"]], ["leak"])
                self.assertEqual(result["cont"]["reviewed"], {"head": "c0ffee"})
                self.assertEqual(result["cont"]["review_rounds"], 1)

    def test_a_re_review_moves_the_reviewed_head(self):
        result, _ = run(replies={"final-1": SCOPED_FIRST, "fix-wave-review": FixWaveTest.narrowing(), "fix-wave-review-2": SCOPED_NEW},
                        patch={"fix-wave": {"start_head": "c0ffee", "commit": R}, "fix-wave-2": {"start_head": R, "commit": H}})
        self.assertEqual(result["stage"], "fix-wave-review")
        self.assertEqual(result["cont"]["reviewed"], {"head": H})
        self.assertEqual(result["cont"]["review_rounds"], 1)

    def test_a_lost_scoped_review_keeps_the_round_and_the_findings(self):
        cont = scoped_first_stop()
        result, _ = scoped_resume(cont, replies={"final-scoped": None})
        self.assertEqual(result["stage"], "final-review")
        self.assertIn("the scoped reviewer", result["reason"])
        self.assertEqual(result["cont"]["review_rounds"], 1)
        self.assertEqual(result["cont"]["reviewed"], {"head": R})
        self.assertEqual(result["cont"]["fix_findings"], cont["fix_findings"])

    def branch_stop(self):
        new = {"verdict": "findings", "findings": [{"severity": "important", "summary": "leak on cand", "relation": "new"}]}
        at_e = {"start_head": TIP, "commit": TIP, "branch_heads": [{"name": "cand", "head": "e" * 40}]}
        stopped, _ = run(replies={"plan": bplan(), "final-1": SCOPED_FIRST, "fix-wave-review": new},
                         patch={"impl-1": {"commit": TIP}, "impl-2": {"commit": "d" * 40}, "fix-wave": at_e})
        self.assertEqual(stopped["stage"], "fix-wave-review")
        self.assertEqual(stopped["cont"]["reviewed"], {"head": TIP, "branches": {"cand": "e" * 40}})
        return stopped["cont"]

    def branch_resume(self, cont, **replies):
        facts = [{"name": "cand", "head": "f" * 40, "current": "cand", "toplevel": "/r/.wt/cand", "common_dir": "/r/.git"}]
        wave = {"start_head": TIP, "commit": TIP, "branch_heads": [{"name": "cand", "head": "f" * 40}]}
        return run(args=dict(ARGS, cont=cont), replies=dict({"verify": None}, **replies),
                   patch={"setup": {"head": TIP, "branch_heads": facts}, "fix-wave": wave})

    def test_a_declared_branch_is_reviewed_from_its_recorded_head(self):
        _, calls = self.branch_resume(self.branch_stop())
        scoped = prompt(calls, "final-scoped")
        e, f = "e" * 40, "f" * 40
        for needle in (f"git -C /r/.wt/cand merge-base --is-ancestor {e} {f}", f"git -C /r/.wt/cand log -p --no-merges {e}..{f} ^{BR['base']}",
                       f"git -C /r/.wt/cand rev-list --merges {e}..{f} ^{BR['base']}", f"git -C /r/.wt/cand diff {e} {f}"):
            self.assertIn(needle, scoped)
        self.assertNotIn(f"diff {BR['base']}...cand", scoped)

    def test_a_completed_full_review_is_never_run_in_full_again(self):
        legacy = {k: v for k, v in FinalReviewedResumeTest.stopped_after_review()["cont"].items() if k not in ("review_rounds", "reviewed")}
        self.assertEqual(legacy["final_reviewed"], {"head": TIP})
        result, calls = run(args=dict(ARGS, cont=legacy), replies={"verify": None}, patch={"setup": {"head": H}})
        self.assertIn("final-scoped", labels(calls))
        self.assertNotIn("final-1", labels(calls))
        self.assertIn(f"{TIP}..{H}", prompt(calls, "final-scoped"))
        self.assertEqual(result["cont"]["review_rounds"], 2)
        bare = {k: v for k, v in scoped_first_stop().items() if k not in ("review_rounds", "reviewed")}
        _, calls = scoped_resume(bare, replies={"verify": None})
        self.assertIn("final-1", labels(calls))
        self.assertNotIn("final-scoped", labels(calls))
        only = dict(PLAN, branches=[dict(BR)], tasks=[dict(PLAN["tasks"][0], file="/g/task-1.md", branch="cand")])
        result, calls = run(replies={"plan": only, "final-1": {"verdict": "pass", "findings": [], "head": "9" * 40}, "verify": None})
        self.assertIn("rev-parse HEAD", prompt(calls, "final-1"))
        self.assertEqual(result["cont"]["reviewed"]["head"], "9" * 40)
        self.assertIn("cand", result["cont"]["reviewed"]["branches"])

    def test_a_malformed_reviewed_marker_is_not_used(self):
        cont = scoped_first_stop()
        for head in ("HEAD", "x" * 40):
            with self.subTest(head=head):
                _, calls = scoped_resume(dict(cont, reviewed={"head": head}))
                self.assertIn("final-1", labels(calls))
                self.assertNotIn("final-scoped", labels(calls))
        branch = self.branch_stop()
        bad = dict(branch, reviewed=dict(branch["reviewed"], branches={"cand": "HEAD", "../x": "e" * 40}))
        _, calls = self.branch_resume(bad)
        scoped = prompt(calls, "final-scoped")
        self.assertIn(f"git -C /r/.wt/cand diff {BR['base']}...cand", scoped)
        self.assertNotIn("HEAD..f", scoped)
        # What a stop hands back is the marker as read: the invalid entries are gone from it.
        lost, _ = self.branch_resume(bad, **{"final-scoped": None})
        self.assertEqual(lost["stage"], "final-review")
        self.assertEqual(lost["cont"]["reviewed"], {"head": TIP})

    def test_an_amended_plan_is_graded_by_the_scoped_round(self):
        cont = FinalReviewedResumeTest.stopped_after_review()["cont"]
        _, calls = run(args=dict(ARGS, cont=cont, amend=[AMEND_EDIT]), patch={"setup": {"head": TIP}})
        names = labels(calls)
        self.assertLess(names.index("amend"), names.index("final-scoped"))
        self.assertLess(names.index("final-scoped"), names.index("verify"))
        self.assertNotIn("final-1", names)
        self.assertIn(AMENDED, prompt(calls, "final-scoped"))
        stopped, _ = run(args=dict(ARGS, cont=cont, amend=[AMEND_EDIT]), replies={"amend": None}, patch={"setup": {"head": TIP}})
        self.assertEqual(stopped["stage"], "amend")
        self.assertEqual(stopped["cont"]["reviewed"], {"head": TIP, "amended": True})
        result, calls = run(args=dict(ARGS, cont=stopped["cont"]), replies={"verify": None}, patch={"setup": {"head": TIP}})
        self.assertIn(AMENDED, prompt(calls, "final-scoped"))
        self.assertEqual(result["cont"]["reviewed"], {"head": TIP})

    def test_an_applied_amend_is_kept_by_a_stop_before_the_next_verdict(self):
        cont = FinalReviewedResumeTest.stopped_after_review()["cont"]
        lost, _ = run(args=dict(ARGS, cont=cont, amend=[AMEND_EDIT]), replies={"final-scoped": None}, patch={"setup": {"head": TIP}})
        self.assertEqual(lost["stage"], "final-review")
        self.assertEqual(lost["cont"]["reviewed"], {"head": TIP, "amended": True})
        _, calls = run(args=dict(ARGS, cont=lost["cont"]), replies={"verify": None}, patch={"setup": {"head": TIP}})
        self.assertIn(AMENDED, prompt(calls, "final-scoped"))


def open_(summary, file="claim.py"):
    return {"verdict": "findings", "findings": [{"severity": "important", "file": file, "summary": summary, "relation": "new"}]}


class ReviewRoundCapTest(unittest.TestCase):
    """#1370: a round's verdict that leaves findings open after one full and two scoped rounds stops before any fix wave; only the owner reopens it."""

    DECISION = "Accept the renew race; fix only the leak."
    DECIDED = ' The owner decided how to settle the findings left open at the review round cap, and the decision is binding: "Accept the renew race; fix only the leak."'
    REASON = ("fix-wave-review: the review round cap is reached after 3 rounds (one full and two scoped); an owner decision is needed "
              "on the 1 finding(s) still open: race in renew")
    EIGHT = {"setup": {"head": "8" * 40}}

    def second(self):
        out = run_out(args=dict(ARGS, cont=scoped_first_stop()),
                      replies={"final-scoped": open_("race in steal"), "fix-wave-review": open_("race in renew")},
                      patch={"setup": {"head": "e" * 40}, "fix-wave": {"start_head": "e" * 40, "commit": "9" * 40}})
        self.assertEqual((out["result"]["stage"], out["result"]["cont"]["review_rounds"], out["result"]["fix_waves"]), ("fix-wave-review", 2, 2))
        return out

    def capped(self, replies=None):
        return run_out(args=dict(ARGS, cont=self.second()["result"]["cont"]),
                       replies=dict({"final-scoped": open_("race in renew")}, **(replies or {})), patch={"setup": {"head": "f" * 40}})

    def test_a_third_round_left_open_stops_at_the_cap(self):
        second = self.second()
        self.assertIn("fix-wave", labels(second["calls"]))
        self.assertNotIn("round_cap", second["result"])
        self.assertNotIn("round_cap", second["result"]["cont"])
        out = self.capped()
        result, cont = out["result"], out["result"]["cont"]
        self.assertEqual(result["stage"], "fix-wave-review")
        self.assertEqual(result["round_cap"], {"rounds": 3, "findings": ["race in renew"]})
        self.assertEqual(cont["round_cap"], result["round_cap"])
        self.assertTrue(result["reason"].startswith(self.REASON), result["reason"])
        self.assertLessEqual(len(result["reason"]), 300)
        self.assertEqual(waves(out["calls"]), [])
        self.assertEqual((result["fix_waves"], cont["fix_waves"]), (2, 2))
        self.assertEqual(cont["review_rounds"], 3)
        self.assertEqual([f["summary"] for f in cont["fix_findings"]], ["race in renew"])
        passed, _ = run(args=dict(ARGS, cont=second["result"]["cont"]), patch={"setup": {"head": "f" * 40}},
                        replies={"final-scoped": {"verdict": "pass", "findings": [], "closed": [1]}, "verify": None})
        self.assertEqual(passed["stage"], "verify")
        self.assertNotIn("round_cap", passed["cont"])

    def test_a_resume_of_a_capped_cont_starts_no_agent(self):
        cont = self.capped()["result"]["cont"]
        held = dict(cont, decisions=["An earlier answer."])
        for name, c, more in (("none", cont, {}), ("blank", cont, {"decisions": "  "}), ("rerun", cont, {"decisions": "rerun"}),
                              ("already held", held, {"decisions": "An earlier answer."})):
            with self.subTest(name):
                result, calls = run(args=dict(ARGS, cont=c, **more))
                self.assertEqual(calls, [])
                self.assertEqual(result["stage"], "fix-wave-review")
                self.assertEqual(result["cont"], c)
                self.assertEqual(result["round_cap"], cont["round_cap"])
                if name == "none":
                    self.assertEqual(result["reason"], f"{self.REASON}; not run again: this resume brings nothing new from the owner; "
                                     "resume with decisions (how to settle the open findings), or amend")
        _, calls = run(args=dict(ARGS, cont={k: v for k, v in cont.items() if k != "fix_findings"}))
        self.assertNotEqual(calls, [])

    def test_only_a_cap_stop_gates_the_resume(self):
        lost, _ = run(args=dict(ARGS, cont=scoped_first_stop()), replies={"final-scoped": open_("race in steal"), "fix-wave": None},
                      patch={"setup": {"head": "e" * 40}})
        self.assertEqual(lost["stage"], "fix-wave")
        self.assertNotIn("round_cap", lost)
        self.assertNotIn("round_cap", lost["cont"])
        self.assertEqual([f["summary"] for f in lost["cont"]["fix_findings"]], ["race in steal"])
        _, calls = run(args=dict(ARGS, cont=dict(lost["cont"], review_rounds=3)), patch={"setup": {"head": "e" * 40}})
        self.assertEqual(labels(calls)[0], "setup")
        self.assertIn("final-scoped", labels(calls))
        cont = self.capped()["result"]["cont"]
        out = run_out(args=dict(ARGS, cont=cont, decisions=self.DECISION),
                      replies={"final-scoped": open_("race in renew"), "fix-wave-review": None}, patch=self.EIGHT)
        self.assertEqual(out["result"]["stage"], "fix-wave-review")
        self.assertNotIn("round_cap", out["result"]["cont"])
        self.assertIn(self.DECISION, out["result"]["cont"]["decisions"])
        _, calls = run(args=dict(ARGS, cont=out["result"]["cont"]), patch=self.EIGHT)
        self.assertIn("final-scoped", labels(calls))
        out = run_out(args=dict(ARGS, cont=cont, decisions=self.DECISION),
                      replies={"final-scoped": open_("race in renew"), "fix-wave": None}, patch=self.EIGHT)
        self.assertEqual(out["result"]["stage"], "fix-wave")
        self.assertEqual(out["result"]["cont"]["round_cap"]["rounds"], 3)
        self.assertNotIn(self.DECISION, out["result"]["cont"].get("decisions", []))
        result, calls = run(args=dict(ARGS, cont=out["result"]["cont"]))
        self.assertEqual(calls, [])

    def test_an_owner_decision_admits_one_more_scoped_round(self):
        cont = self.capped()["result"]["cont"]
        out = run_out(args=dict(ARGS, cont=cont, decisions=self.DECISION), replies={"final-scoped": open_("race in renew"), "verify": None}, patch=self.EIGHT)
        result, calls = out["result"], out["calls"]
        for label in ("final-scoped", "fix-wave", "fix-wave-review"):
            self.assertIn(label, labels(calls))
            self.assertIn(self.DECIDED, prompt(calls, label))
        for label in ("final-scoped", "fix-wave-review"):
            self.assertIn(f"{self.DECIDED}. Report no finding that only disputes it.", prompt(calls, label))
        self.assertEqual((result["stage"], result["cont"]["review_rounds"]), ("verify", 4))
        self.assertIn(self.DECISION, result["cont"]["decisions"])
        self.assertNotIn("round_cap", result["cont"])
        again = run_out(args=dict(ARGS, cont=cont, decisions=self.DECISION),
                        replies={"final-scoped": open_("race in renew"), "fix-wave-review": open_("race in lease")}, patch=self.EIGHT)["result"]
        self.assertEqual(again["stage"], "fix-wave-review")
        self.assertEqual(again["round_cap"], {"rounds": 4, "findings": ["race in lease"]})
        self.assertEqual(again["cont"]["round_cap"], again["round_cap"])

    def test_an_amend_admits_one_more_scoped_round(self):
        cont = self.capped()["result"]["cont"]
        out = run_out(args=dict(ARGS, cont=cont, amend=[dict(AMEND_EDIT, file="task-1.md")]),
                      replies={"final-scoped": open_("race in renew"), "verify": None}, patch=self.EIGHT)
        for label in ("amend", "fix-wave"):
            self.assertIn(label, labels(out["calls"]))
        self.assertIn(" The owner amended the plan after the review round cap (plan.md, Amendments): it is binding.", prompt(out["calls"], "fix-wave"))
        self.assertEqual(out["result"]["stage"], "verify")

    def test_the_existing_bounds_still_apply_inside_the_cap(self):
        first = run(args=dict(ARGS, cont=FixWavesConvergeTest().stopped()), replies={"fix-wave-review": FixWavesConvergeTest.left()},
                    patch={"setup": {"head": "e" * 40}})[0]
        self.assertEqual(first["diverging"], {"file": "claim.py", "waves": 4})
        self.assertNotIn("round_cap", first)
        cont = dict(self.capped()["result"]["cont"], fix_waves=3)
        result, _ = run(args=dict(ARGS, cont=cont, decisions=self.DECISION),
                        replies={"final-scoped": open_("race in renew"), "fix-wave-review": FixWavesConvergeTest.left()}, patch=self.EIGHT)
        self.assertEqual(result["diverging"], {"file": "claim.py", "waves": 4})
        self.assertEqual(result["round_cap"]["rounds"], 4)
        self.assertTrue(result["reason"].startswith("fix-wave-review: the fix waves do not converge on claim.py after 4 waves"), result["reason"])
        self.assertIn("the review round cap is reached", result["reason"])
        decision = FixWaveHistoryTest.DECISION
        oscillating = dict(FixWaveHistoryTest().stopped()["cont"], review_rounds=3)
        _, calls = run(args=dict(ARGS, cont=oscillating, decisions=decision), patch={"setup": {"head": "e" * 40}})
        for label in ("final-scoped", "fix-wave"):
            self.assertIn(label, labels(calls))
        self.assertIn(json.dumps(decision), prompt(calls, "fix-wave"))


class ReviewRoundFindingsTest(unittest.TestCase):
    """#1370: the final review's findings on the scoped rounds, the round cap and the reviewed head."""

    NARROW = {"verdict": "findings", "changed_files": ["tools/grader.json"],
              "findings": [{"severity": "important", "file": "src/lock.py", "summary": "lock race on another path", "relation": "narrowing"}]}

    def test_a_wave_lost_after_the_first_leaves_no_oscillating_marker(self):
        history = FixWaveHistoryTest()
        cont = history.stopped()["cont"]
        self.assertIn("oscillating", cont)
        args = dict(ARGS, cont=cont, decisions=history.DECISION)
        late, _ = run(args=args, replies={"fix-wave-review": self.NARROW, "fix-wave-2": None}, patch={"fix-wave": history.ONLY})
        self.assertEqual(late["stage"], "fix-wave")
        self.assertNotIn("oscillating", late["cont"])
        self.assertEqual([f["summary"] for f in late["cont"]["fix_findings"]], ["lock race on another path"])
        self.assertEqual(late["cont"]["decisions"], [history.DECISION])
        _, calls = run(args=dict(ARGS, cont=late["cont"]))
        self.assertIn("final-scoped", labels(calls))
        first, _ = run(args=args, replies={"fix-wave": None})
        self.assertEqual(first["stage"], "fix-wave")
        self.assertIn("oscillating", first["cont"])

    def test_a_fix_wave_that_starts_elsewhere_does_not_move_the_reviewed_head(self):
        for start, moved in ((R, True), ("b" * 40, False)):
            with self.subTest(start_head=start):
                out = run_out(replies={"final-1": SCOPED_FIRST, "fix-wave-review": SCOPED_NEW},
                              patch={"fix-wave": {"start_head": start, "commit": H}, "impl-1": {"commit": R}})
                self.assertEqual(out["result"]["cont"]["reviewed"], {"head": H if moved else R})
        # The commits between the head the review read and the wave's reported start were never re-reviewed: the next round reads them.
        stopped, _ = run(replies={"final-1": SCOPED_FIRST, "fix-wave-review": SCOPED_NEW},
                         patch={"fix-wave": {"start_head": "b" * 40, "commit": H}, "impl-1": {"commit": R}})
        _, calls = run(args=dict(ARGS, cont=stopped["cont"]), patch={"setup": {"head": "f" * 40}})
        self.assertIn(f"{R}..{'f' * 40}", prompt(calls, "final-scoped"))

    def test_a_later_wave_never_moves_the_reviewed_head_past_a_gap_an_earlier_wave_left(self):
        # Wave 1 started at b..., not at the reviewed head: R..b... was never re-reviewed. Wave 2 starts at wave 1's commit, which is no reason to move the head.
        gap = {"fix-wave": {"start_head": "b" * 40, "commit": H}, "fix-wave-2": {"start_head": H, "commit": "a" * 40}, "impl-1": {"commit": R}}
        narrow = dict(self.NARROW, changed_files=["tools/grader.json"])
        stopped = run_out(replies={"final-1": SCOPED_FIRST, "fix-wave-review": narrow, "fix-wave-review-2": SCOPED_NEW}, patch=gap)["result"]
        self.assertEqual(stopped["stage"], "fix-wave-review")
        self.assertEqual(stopped["cont"]["reviewed"], {"head": R})
        passed = run_out(replies={"final-1": SCOPED_FIRST, "fix-wave-review": narrow, "fix-wave-review-2": {"verdict": "pass", "findings": []}, "verify": None}, patch=gap)["result"]
        self.assertEqual(passed["stage"], "verify")
        self.assertEqual(passed["cont"]["reviewed"], {"head": R})
        # The pass records no head as reviewed, so a resume at that head reads the gap in a scoped round instead of skipping the review.
        self.assertNotIn("final_reviewed", passed["cont"])
        _, calls = run(args=dict(ARGS, cont=passed["cont"]), patch={"setup": {"head": "a" * 40}})
        self.assertIn(f"{R}..{'a' * 40}", prompt(calls, "final-scoped"))
        # Without a gap the same two waves move the head and record the pass.
        clean = dict(gap, **{"fix-wave": {"start_head": R, "commit": H}})
        ok = run_out(replies={"final-1": SCOPED_FIRST, "fix-wave-review": narrow, "fix-wave-review-2": {"verdict": "pass", "findings": []}, "verify": None}, patch=clean)["result"]
        self.assertEqual(ok["cont"]["reviewed"], {"head": "a" * 40})
        self.assertEqual(ok["cont"]["final_reviewed"]["head"], "a" * 40)

    def test_a_round_without_a_known_tip_requires_the_head_its_reviewers_read(self):
        only = dict(PLAN, branches=[dict(BR)], tasks=[dict(PLAN["tasks"][0], file="/g/task-1.md", branch="cand")])
        _, calls = run(replies={"plan": only, "verify": None})
        self.assertIn("head", schema_of(calls, "final-1")["required"])
        _, calls = run(replies={"verify": None})
        self.assertNotIn("head", schema_of(calls, "final-1")["required"])

    def test_two_carried_findings_alike_but_for_the_failing_input_are_two_findings(self):
        cont = dict(scoped_first_stop(), fix_findings=[
            {"severity": "important", "file": "claim.py", "summary": "race in steal", "failing_input": "input-one"},
            {"severity": "important", "file": "claim.py", "summary": "race in steal", "failing_input": "input-two"}])
        again = {"verdict": "findings", "closed": [], "findings": [dict(cont["fix_findings"][0])]}
        _, calls = scoped_resume(cont, replies={"final-scoped": again, "verify": None})
        wave = prompt(calls, "fix-wave")
        self.assertIn('"failing_input":"input-one"', wave)
        self.assertIn('"failing_input":"input-two"', wave)
        self.assertIn("The last 1 were left open", wave)
        both = dict(again, findings=cont["fix_findings"])
        _, calls = scoped_resume(cont, replies={"final-scoped": both, "verify": None})
        self.assertIn("input-two", prompt(calls, "fix-wave"))
        self.assertNotIn("were left open by an earlier run's fix waves", prompt(calls, "fix-wave"))

    def test_an_amended_round_may_report_what_the_amended_plan_requires_and_the_head_lacks(self):
        cont = FinalReviewedResumeTest.stopped_after_review()["cont"]
        _, calls = run(args=dict(ARGS, cont=cont, amend=[AMEND_EDIT]), patch={"setup": {"head": TIP}})
        amended = prompt(calls, "final-scoped")
        self.assertIn("in those commits, among the findings above or in a requirement of the amended plan the head does not meet. Do not edit anything.", amended)
        _, calls = run(args=dict(ARGS, cont=cont), patch={"setup": {"head": H}})
        plain = prompt(calls, "final-scoped")
        self.assertIn("in those commits or among the findings above. Do not edit anything.", plain)
        self.assertNotIn("requirement of the amended plan", plain)

    def test_a_stored_head_that_is_no_commit_id_reaches_no_git_command_and_skips_no_review(self):
        legacy = {k: v for k, v in FinalReviewedResumeTest.stopped_after_review()["cont"].items() if k not in ("review_rounds", "reviewed")}
        for bad in ("HEAD~1", "x" * 40, "d" * 40 + "; rm"):
            with self.subTest(head=bad):
                cont = dict(legacy, final_reviewed={"head": bad, "accepted": ["HEAD~2", "$(id)"]})
                _, calls = run(args=dict(ARGS, cont=cont), patch={"setup": {"head": H, "since_reviewed": "merge_only"}})
                setup = prompt(calls, "setup")
                for needle in (bad, "HEAD~2", "$(id)", "since_reviewed"):
                    self.assertNotIn(needle, setup)
                self.assertIn("final-1", labels(calls))
                self.assertNotIn("final-scoped", labels(calls))
        good = dict(legacy, final_reviewed={"head": TIP, "accepted": ["a" * 40, "HEAD~2"]})
        _, calls = run(args=dict(ARGS, cont=good), patch={"setup": {"head": H, "since_reviewed": "merge_only"}})
        self.assertIn(f"passed at {TIP}", prompt(calls, "setup"))
        self.assertIn(f"is one of {'a' * 40} or", prompt(calls, "setup"))
        self.assertNotIn("HEAD~2", prompt(calls, "setup"))

    def test_an_oscillation_decision_binds_the_scoped_reviewer_of_a_capped_cont(self):
        history = FixWaveHistoryTest()
        cont = dict(history.stopped()["cont"], review_rounds=3, round_cap={"rounds": 3, "findings": ["pattern too wide again"]})
        _, calls = run(args=dict(ARGS, cont=cont, decisions=history.DECISION), patch={"setup": {"head": H}, "fix-wave": history.ONLY})
        scoped = prompt(calls, "final-scoped")
        self.assertIn(f"{json.dumps(history.DECISION)}", scoped)
        self.assertIn("the decision is binding", scoped)
        self.assertIn("Report no finding that only disputes it.", scoped)
        self.assertEqual(prompt(calls, "fix-wave").count(json.dumps(history.DECISION)), 1)


def program_const(name):
    found = re.search(rf"^const {name} = '([^'\\]*)'$", PROGRAM.read_text(encoding="utf-8"), re.M)
    if found is None:
        raise AssertionError(f"no const {name} in the program")
    return found.group(1)


def items(calls, label):
    return json.loads(prompt(calls, label).split("Follow-ups: ", 1)[1].split("\n", 1)[0])


def filings(calls):
    return [name for name in labels(calls) if re.fullmatch(r"follow-ups-\d+", name)]


class ScopedRoundFollowUpTest(unittest.TestCase):
    """#1386: after the first full review only a critical finding, or one naming an unmet criterion, blocks; the rest are filed as follow-up issues."""

    HARDENING = {"severity": "important", "file": "src/guard.py", "summary": "guard could also check the length", "relation": "new", "commit": H}
    DOC = {"severity": "important", "file": "src/doc.py", "summary": "doc example is stale", "relation": "new", "commit": H}
    SECURITY = {"severity": "critical", "file": "src/auth.py", "summary": "token written to the log", "relation": "new", "commit": H}
    RENEW = {"severity": "important", "file": "claim.py", "summary": "race in renew", "relation": "new", "commit": "9" * 40}
    FILED = [{"issue": 911, "file": "src/guard.py", "summary": "guard could also check the length", "commit": H}]

    @staticmethod
    def unmet(severity):
        return {"severity": severity, "file": "src/flow.py", "summary": "AC1 has no test", "ac": "AC1", "relation": "new", "commit": H}

    @staticmethod
    def scoped(*findings, **more):
        return dict({"verdict": "findings", "findings": list(findings), "closed": [1]}, **more)

    def test_a_non_critical_scoped_finding_is_filed_and_the_delivery_lands(self):
        cont = scoped_first_stop()
        result, calls = run(args=dict(ARGS, cont=cont), replies={"final-scoped": self.scoped(self.HARDENING, head=H)})
        self.assertEqual(result["stage"], "done")
        self.assertIn("merge", labels(calls))
        self.assertEqual(waves(calls), [])
        self.assertEqual(filings(calls), ["follow-ups-1"])
        self.assertEqual(result["follow_ups"], self.FILED)
        entries = items(calls, "follow-ups-1")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["n"], 1)
        for needle in ("#9", "src/guard.py", H, "guard could also check the length"):
            self.assertIn(needle, entries[0]["body"])
        self.assertLess(labels(calls).index("follow-ups-1"), labels(calls).index("verify"))
        self.assertEqual(schema_of(calls, "follow-ups-1")["required"], ["filed"])
        cmd = re.search(r"forge-issue create --repo owner/repo [^\n]*?--body-file", prompt(calls, "follow-ups-1"))
        self.assertIsNotNone(cmd)
        self.assertNotIn("--blocked-by", cmd.group(0))
        self.assertNotIn("--blocks", cmd.group(0))

    def test_a_critical_security_finding_in_a_scoped_round_never_reaches_the_merge(self):
        cont = scoped_first_stop()
        result, calls = scoped_resume(cont, replies={"final-scoped": self.scoped(self.SECURITY, self.HARDENING),
                                                     "fix-wave-review": {"verdict": "findings", "findings": [self.SECURITY]}})
        self.assertEqual(result["stage"], "fix-wave-review")
        self.assertNotIn("pr", labels(calls))
        self.assertNotIn("merge", labels(calls))
        self.assertIn("token written to the log", prompt(calls, "fix-wave"))
        self.assertNotIn("guard could also check the length", prompt(calls, "fix-wave"))
        self.assertEqual([f["summary"] for f in result["cont"]["fix_findings"]], ["token written to the log"])
        self.assertEqual(result["cont"]["follow_ups"], self.FILED)

    def test_a_finding_naming_an_unmet_criterion_blocks_in_every_round(self):
        ac_item = {"type": "string"}
        for sev in ("important", "minor"):
            with self.subTest(round="scoped", severity=sev):
                _, calls = scoped_resume(scoped_first_stop(), replies={"final-scoped": self.scoped(self.unmet(sev)), "verify": None})
                self.assertEqual(schema_of(calls, "final-scoped")["properties"]["findings"]["items"]["properties"]["ac"], ac_item)
                self.assertIn("AC1 has no test", prompt(calls, "fix-wave"))
                self.assertEqual(filings(calls), [])
            with self.subTest(round="re-review", severity=sev):
                result, calls = scoped_resume(scoped_first_stop(), replies={
                    "final-scoped": self.scoped(self.SECURITY), "fix-wave-review": {"verdict": "findings", "findings": [self.unmet(sev)]}})
                self.assertEqual(result["stage"], "fix-wave-review")
                self.assertIn("AC1 has no test", [f["summary"] for f in result["cont"]["fix_findings"]])
                self.assertEqual(filings(calls), [])
            with self.subTest(round="full", severity=sev):
                _, calls = run(replies={"final-1": {"verdict": "findings", "findings": [self.unmet(sev)]}, "verify": None})
                self.assertEqual(schema_of(calls, "final-1")["properties"]["findings"]["items"]["properties"]["ac"], ac_item)
                self.assertIn("AC1 has no test", prompt(calls, "fix-wave"))
                self.assertEqual(filings(calls), [])

    def test_a_scoped_fix_wave_review_files_its_non_critical_findings(self):
        result, calls = scoped_resume(scoped_first_stop(), replies={
            "final-scoped": self.scoped(self.SECURITY), "fix-wave-review": {"verdict": "findings", "findings": [self.RENEW]}, "verify": None})
        self.assertEqual(result["stage"], "verify")
        self.assertEqual(waves(calls), ["fix-wave", "fix-wave-review"])
        self.assertEqual(filings(calls), ["follow-ups-1"])
        self.assertEqual(result["cont"]["follow_ups"], [{"issue": 911, "file": "claim.py", "summary": "race in renew", "commit": "9" * 40}])
        self.assertNotIn("fix_findings", result["cont"])
        review = schema_of(calls, "fix-wave-review")
        self.assertIn("changed_files", review["properties"])
        self.assertEqual(review["properties"]["findings"]["items"]["required"], ["severity", "summary", "file", "commit"])

    def test_a_reworded_re_report_of_a_first_review_finding_still_blocks(self):
        """A still-open finding of the first full review, re-reported by the re-review with another summary, is the same defect: it blocks, never filed."""
        reworded = {"severity": "important", "file": "claim.py", "summary": "race in steal is still open after the fix", "relation": "narrowing", "commit": "e" * 40}
        again = {"verdict": "findings", "findings": [reworded]}
        result, calls = scoped_resume(scoped_first_stop(), replies={
            "final-scoped": {"verdict": "findings", "closed": [], "findings": []},
            "fix-wave-review": again, "fix-wave-review-2": again, "fix-wave-review-3": again, "verify": None})
        self.assertEqual(result["stage"], "fix-wave-review")
        self.assertEqual(filings(calls), [])
        self.assertNotIn("verify", labels(calls))
        self.assertEqual([f["summary"] for f in result["cont"]["fix_findings"]], ["race in steal is still open after the fix"])
        self.assertNotIn("follow_ups", result["cont"])
        elsewhere = dict(reworded, file="other.py")
        result, calls = scoped_resume(scoped_first_stop(), replies={
            "final-scoped": {"verdict": "findings", "closed": [], "findings": []},
            "fix-wave-review": {"verdict": "findings", "findings": [elsewhere]}, "verify": None})
        self.assertEqual(result["stage"], "verify")
        self.assertEqual(filings(calls), ["follow-ups-1"])

    def test_an_unconfirmed_filing_stops_before_verify_and_the_resume_files_it_once(self):
        both = ["guard could also check the length", "doc example is stale"]
        for name, reply, left in (("partial", {"filed": [{"n": 1, "issue": 901}]}, ["doc example is stale"]), ("lost", None, both), ("thrown", "throw", both)):
            with self.subTest(name):
                stopped, calls = run(args=dict(ARGS, cont=scoped_first_stop()), replies={
                    "final-scoped": self.scoped(self.HARDENING, self.DOC, head=H), "follow-ups-1": reply, "follow-ups-2": {"filed": []}})
                self.assertEqual(stopped["stage"], "final-review")
                self.assertNotIn("verify", labels(calls))
                self.assertNotIn("merge", labels(calls))
                self.assertEqual(waves(calls), [])
                self.assertEqual(filings(calls), ["follow-ups-1", "follow-ups-2"])
                self.assertEqual([f["summary"] for f in stopped["cont"]["follow_ups_pending"]], left)
                self.assertTrue(all(f["commit"] == H for f in stopped["cont"]["follow_ups_pending"]))
                if name == "partial":
                    self.assertEqual(stopped["cont"]["follow_ups"], [dict(self.FILED[0], issue=901)])
                else:
                    self.assertNotIn("follow_ups", stopped["cont"])
                if name == "thrown":
                    self.assertIn("follow-ups-1", stopped["dead_agents"])
                done, calls = run(args=dict(ARGS, cont=stopped["cont"]))
                self.assertEqual(done["stage"], "done")
                self.assertEqual(filings(calls), ["follow-ups-1"])
                entries = items(calls, "follow-ups-1")
                self.assertEqual(len(entries), len(left))
                for entry, summary in zip(entries, left):
                    self.assertIn(summary, entry["body"])
                self.assertLess(labels(calls).index("follow-ups-1"), labels(calls).index("verify"))
                self.assertLess(labels(calls).index("follow-ups-1"), labels(calls).index("merge"))
                self.assertEqual(sorted(f["summary"] for f in done["follow_ups"]), sorted(both))
                self.assertNotIn("follow_ups_pending", done)

    def test_findings_alike_in_title_are_two_issues_and_a_shared_number_confirms_neither(self):
        a = dict(self.HARDENING, file="src/a.py", summary="missing test for the error path")
        b = dict(a, file="src/b.py")
        result, calls = scoped_resume(scoped_first_stop(), replies={"final-scoped": self.scoped(a, b), "verify": None})
        first, second = items(calls, "follow-ups-1")
        self.assertNotEqual(first["title"], second["title"])
        self.assertNotEqual(first["body"], second["body"])
        self.assertIn("src/a.py", first["title"])
        self.assertIn("src/b.py", second["title"])
        self.assertEqual([(f["issue"], f["file"]) for f in result["cont"]["follow_ups"]], [(911, "src/a.py"), (912, "src/b.py")])
        shared = {"filed": [{"n": 1, "issue": 901}, {"n": 2, "issue": 901}]}
        stopped, calls = scoped_resume(scoped_first_stop(), replies={"final-scoped": self.scoped(a, b), "follow-ups-1": shared, "follow-ups-2": shared})
        self.assertEqual(stopped["stage"], "final-review")
        self.assertNotIn("follow_ups", stopped["cont"])
        self.assertEqual([f["file"] for f in stopped["cont"]["follow_ups_pending"]], ["src/a.py", "src/b.py"])
        _, again = scoped_resume(stopped["cont"], replies={"verify": None})
        self.assertEqual([i["body"] for i in items(again, "follow-ups-1")], [i["body"] for i in items(calls, "follow-ups-1")])
        self.assertIn("gh issue list --repo owner/repo --state all", prompt(again, "follow-ups-1"))

    def test_a_minor_scoped_finding_is_filed(self):
        result, calls = scoped_resume(scoped_first_stop(), replies={
            "final-scoped": self.scoped(dict(self.HARDENING, severity="minor")), "verify": None})
        self.assertEqual(waves(calls), [])
        self.assertEqual(filings(calls), ["follow-ups-1"])
        self.assertIn("minor", items(calls, "follow-ups-1")[0]["body"])
        self.assertEqual(result["cont"]["follow_ups"], self.FILED)

    def test_a_follow_up_names_the_commit_its_reviewer_read_it_at(self):
        branch = ScopedReviewRoundTest()
        found = dict(self.HARDENING, file="/r/.wt/cand/src/c.py", commit="c" * 40)
        result, calls = branch.branch_resume(branch.branch_stop(), **{"final-scoped": self.scoped(found, closed=[])})
        self.assertEqual([f["commit"] for f in result["cont"]["follow_ups"]], ["c" * 40])
        self.assertIn("c" * 40, items(calls, "follow-ups-1")[0]["body"])
        bare = {k: v for k, v in self.HARDENING.items() if k != "commit"}
        _, calls = scoped_resume(scoped_first_stop(), replies={"final-scoped": self.scoped(bare), "verify": None})
        self.assertIn("guard could also check the length", prompt(calls, "fix-wave"))
        self.assertEqual(filings(calls), [])

    def test_closures_are_reconciled_before_the_triage(self):
        cont = ReviewRoundCapTest().second()["result"]["cont"]
        result, calls = run(args=dict(ARGS, cont=cont), patch={"setup": {"head": "f" * 40}},
                            replies={"final-scoped": self.scoped(dict(self.RENEW, commit="f" * 40)), "verify": None})
        self.assertNotIn("round_cap", result)
        self.assertEqual(waves(calls), [])
        self.assertEqual(filings(calls), ["follow-ups-1"])
        self.assertEqual(result["stage"], "verify")
        two = [dict(SCOPED_NEW["findings"][0], commit=H, failing_input=x) for x in ("input-one", "input-two")]
        _, calls = scoped_resume(scoped_first_stop(), replies={"final-scoped": self.scoped(*two, closed=[]), "verify": None})
        self.assertIn("input-one", prompt(calls, "fix-wave"))
        self.assertNotIn("input-two", prompt(calls, "fix-wave"))
        self.assertIn("input-two", items(calls, "follow-ups-1")[0]["body"])

    def test_every_final_reviewer_is_told_what_critical_means(self):
        critical, blocks = program_const("CRITICAL_MEANS"), program_const("SCOPED_BLOCKS")
        _, calls = run(replies={"final-1": SCOPED_FIRST, "verify": None})
        for label in ("final-1", "final-codex", "fix-wave-review"):
            self.assertIn(critical, prompt(calls, label))
        for label in ("final-1", "fix-wave-review"):
            self.assertNotIn(blocks, prompt(calls, label))
        _, calls = run(args=SIZED, replies=dict(sized(1501), verify=None))
        self.assertIn(critical, prompt(calls, "final-integration"))
        _, calls = scoped_resume(scoped_first_stop(), replies={"final-scoped": self.scoped(self.SECURITY), "verify": None})
        for label in ("final-scoped", "fix-wave-review"):
            self.assertIn(critical, prompt(calls, label))
            self.assertIn(blocks, prompt(calls, label))

    def test_a_quoted_summary_reaches_the_title_without_shell_quotes(self):
        said = "don't log \"token\" via $HOME or `env` \\ here"
        _, calls = scoped_resume(scoped_first_stop(), replies={"final-scoped": self.scoped(dict(self.HARDENING, summary=said)), "verify": None})
        entry = items(calls, "follow-ups-1")[0]
        for char in "'\"`$\\":
            self.assertNotIn(char, entry["title"])
        self.assertIn("src/guard.py", entry["title"])
        self.assertIn(said, entry["body"])

    def test_filed_follow_ups_outlive_a_stop_and_are_not_filed_twice(self):
        stopped, _ = scoped_resume(scoped_first_stop(), replies={"final-scoped": self.scoped(self.SECURITY, self.HARDENING),
                                                                 "fix-wave-review": {"verdict": "findings", "findings": [self.SECURITY]}})
        self.assertEqual(stopped["cont"]["follow_ups"], self.FILED)
        result, calls = scoped_resume(stopped["cont"], replies={"final-scoped": self.scoped(self.HARDENING), "verify": None})
        self.assertEqual(filings(calls), [])
        self.assertEqual(waves(calls), [])
        self.assertEqual(result["cont"]["follow_ups"], self.FILED)

    def test_a_reworded_re_report_of_a_first_review_finding_blocks_whatever_its_relation(self):
        """The re-review may call a still-open finding new; the report in its file stands for it, never filed."""
        reworded = {"severity": "important", "file": "claim.py", "summary": "race in steal is still open on the retry path", "relation": "new", "commit": H}
        result, calls = scoped_resume(scoped_first_stop(), replies={
            "final-scoped": {"verdict": "findings", "findings": [], "closed": []},
            "fix-wave-review": {"verdict": "findings", "findings": [reworded]}, "verify": None})
        self.assertEqual(result["stage"], "fix-wave-review")
        self.assertEqual(filings(calls), [])
        self.assertNotIn("verify", labels(calls))
        self.assertEqual([f["summary"] for f in result["cont"]["fix_findings"]], [reworded["summary"]])
        self.assertNotIn("follow_ups", result["cont"])

    def test_one_wave_finding_absorbs_one_report_and_the_others_are_filed(self):
        repeat = {"severity": "important", "file": "claim.py", "summary": "race in steal", "relation": "new", "commit": H}
        other = {"severity": "important", "file": "claim.py", "summary": "race in renew", "relation": "narrowing", "commit": H}
        result, calls = scoped_resume(scoped_first_stop(), replies={
            "final-scoped": {"verdict": "findings", "findings": [], "closed": []},
            "fix-wave-review": {"verdict": "findings", "findings": [repeat, other]}, "verify": None})
        self.assertEqual(result["stage"], "fix-wave-review")
        self.assertEqual([f["summary"] for f in result["cont"]["fix_findings"]], ["race in steal"])
        self.assertEqual(filings(calls), ["follow-ups-1"])
        self.assertEqual([f["summary"] for f in result["cont"]["follow_ups"]], ["race in renew"])

    def test_a_minor_repeat_of_a_critical_or_unmet_criterion_finding_still_blocks(self):
        for name, wave, repeat in (("critical", self.SECURITY, dict(self.SECURITY, severity="minor")),
                                   ("unmet criterion", self.unmet("important"), dict(self.unmet("important"), severity="minor", ac=None))):
            with self.subTest(name):
                repeat = {k: v for k, v in repeat.items() if v is not None}
                result, calls = scoped_resume(scoped_first_stop(), replies={
                    "final-scoped": self.scoped(wave), "fix-wave-review": {"verdict": "findings", "findings": [repeat]}, "verify": None})
                self.assertEqual(result["stage"], "fix-wave-review")
                self.assertNotIn("verify", labels(calls))
                self.assertEqual(filings(calls), [])
                kept = [f for f in result["cont"]["fix_findings"] if f["summary"] == wave["summary"]]
                self.assertEqual([(f["severity"], f.get("ac")) for f in kept], [(wave["severity"], wave.get("ac"))])

    def test_a_minor_repeat_of_an_ordinary_finding_is_still_dropped(self):
        repeat = {"severity": "minor", "file": "claim.py", "summary": "race in steal", "relation": "new", "commit": H}
        result, calls = scoped_resume(scoped_first_stop(), replies={
            "final-scoped": {"verdict": "findings", "findings": [], "closed": []},
            "fix-wave-review": {"verdict": "findings", "findings": [repeat]}, "verify": None})
        self.assertEqual(result["stage"], "verify")
        self.assertEqual(filings(calls), [])

    def test_an_unrelated_minor_report_in_a_critical_findings_file_is_filed_not_upgraded(self):
        """A fix wave resolves a critical finding; the re-review adds a minor note of its own in the same file: it is filed, never carried as the critical one."""
        for name, wave in (("critical", self.SECURITY), ("unmet criterion", self.unmet("important"))):
            with self.subTest(name):
                note = {"severity": "minor", "file": wave["file"], "summary": "a docstring typo in an unrelated helper", "relation": "new", "commit": H}
                result, calls = scoped_resume(scoped_first_stop(), replies={
                    "final-scoped": self.scoped(wave), "fix-wave-review": {"verdict": "findings", "findings": [note]}, "verify": None})
                self.assertEqual(result["stage"], "verify")
                self.assertEqual(filings(calls), ["follow-ups-1"])
                self.assertEqual([e["title"].endswith(note["summary"]) for e in items(calls, "follow-ups-1")], [True])

    def test_the_independent_codex_review_reports_an_unmet_criterion_at_any_severity(self):
        item = schema_of(run(args=SIZED, replies=dict(sized(1501), verify=None))[1], "final-codex")["properties"]["findings"]["items"]
        self.assertEqual(item["properties"]["ac"], {"type": "string"})
        codex = {"available": True, "verdict": "findings", "findings": [self.unmet("minor")], "raw_summary": ""}
        _, calls = run(args=SIZED, replies=dict(sized(1501), **{"final-codex": codex, "verify": None}))
        self.assertIn("AC1 has no test", prompt(calls, "fix-wave"))
        style = {"severity": "minor", "file": "src/flow.py", "summary": "style", "relation": "new"}
        _, calls = run(args=SIZED, replies=dict(sized(1501), **{"final-codex": dict(codex, findings=[style]), "verify": None}))
        self.assertEqual(waves(calls), [])

    def test_the_filing_clerk_is_told_only_to_use_tools_it_has(self):
        clerk = (REPO_ROOT / "home/common/claude-code/agents/clerk.md").read_text(encoding="utf-8")
        tools = {t.strip() for t in re.search(r"^tools:\s*(.+)$", clerk, re.M).group(1).split(",")}
        _, calls = scoped_resume(scoped_first_stop(), replies={"final-scoped": self.scoped(self.HARDENING), "verify": None})
        text = prompt(calls, "follow-ups-1")
        named = set(re.findall(r"\b([A-Z][A-Za-z]+) tool\b", text))
        self.assertLessEqual(named, tools)

    def test_the_recovery_lookup_is_complete_before_an_issue_is_created_again(self):
        _, calls = scoped_resume(scoped_first_stop(), replies={"final-scoped": self.scoped(self.HARDENING), "verify": None})
        text = prompt(calls, "follow-ups-1")
        lookups = re.findall(r"gh issue list [^\n]*?--limit (\d+)", text)
        self.assertEqual(lookups, ["1000", "1000"])
        self.assertLess(text.index("--limit 1000"), text.index("forge-issue create"))

    def test_two_findings_that_differ_only_past_the_clip_are_two_follow_ups(self):
        head = "x" * 300
        a = dict(self.HARDENING, failing_input=head + "-first")
        b = dict(self.HARDENING, failing_input=head + "-second")
        result, calls = scoped_resume(scoped_first_stop(), replies={"final-scoped": self.scoped(a, b), "verify": None})
        entries = items(calls, "follow-ups-1")
        self.assertEqual(len(entries), 2)
        self.assertNotEqual(entries[0]["body"], entries[1]["body"])
        self.assertEqual(len(result["cont"]["follow_ups"]), 2)
        self.assertEqual(len({f["key"] for f in result["cont"]["follow_ups"]}), 2)
        _, calls = scoped_resume(result["cont"], replies={"final-scoped": self.scoped(a, closed=[]), "verify": None})
        self.assertEqual(filings(calls), [])
        again = dict(self.HARDENING, failing_input=head + "-first")
        _, calls = scoped_resume(scoped_first_stop(), replies={"final-scoped": self.scoped(a, again), "verify": None})
        self.assertEqual(len(items(calls, "follow-ups-1")), 1)


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


class FixWaveHistoryTest(unittest.TestCase):
    """#1000: a file whose fix drew a new finding gets its history; a second time stops for the owner; settled findings leave the prompt."""

    FILE = "tools/grader.json"
    FIRST = {"verdict": "findings", "findings": [
        {"severity": "important", "file": "tools/grader.json:16", "summary": "pattern too wide"},
        {"severity": "important", "file": "src/lock.py", "summary": "settled lock race"},
        {"severity": "critical", "file": "src/renew.py:3", "summary": "settled renew leak"}]}
    CHANGED = {"changed_files": ["tools/grader.json", "src/lock.py"]}
    HISTORY = "tools/grader.json has now been judged more than once in the same place"
    SCOPE = (" If a finding is wrong, explain with evidence in notes. Change only what fixing these findings needs, their regression "
             "tests included. ")
    ONLY = {"changed_files": ["tools/grader.json"]}

    @staticmethod
    def found(*rows, changed=CHANGED["changed_files"]):
        return {"verdict": "findings", "changed_files": changed,
                "findings": [{"severity": "important", "file": f, "summary": s, "relation": r} for f, s, r in rows]}

    def two(self, after_1, after_2=None, **patch):
        replies = {"final-1": self.FIRST, "fix-wave-review": after_1}
        if after_2 is not None:
            replies["fix-wave-review-2"] = after_2
        waves_ = {"fix-wave": dict(self.CHANGED, notes="narrowed the pattern"),
                  "fix-wave-2": dict(self.CHANGED, notes="widened it again", start_head="d" * 40, commit="e" * 40)}
        return run_out(replies=replies, patch=dict(waves_, **patch))

    def test_the_first_firing_gets_its_wave_with_the_history_of_the_file(self):
        out = self.two(self.found(("./tools/grader.json:16", "pattern too narrow", "new")))
        result, calls = out["result"], out["calls"]
        self.assertEqual((result["stage"], result["fix_waves"]), ("done", 2))
        self.assertEqual(waves(calls), ThirdFixWaveTest.THREE[:4])
        self.assertNotIn("oscillating", result)
        second = prompt(calls, "fix-wave-2")
        history = [{"round": 0, "findings": ["pattern too wide"]}, {"wave": 1, "range": "b0..c0ffee"}]
        tail = ("Read each range (git -C /r/.wt/w-issue-9-x diff <range> -- tools/grader.json), then change the approach or rebut the "
                "finding with evidence in notes; do not move the same lines back.")
        self.assertIn(f" {self.HISTORY}: the fix of one finding drew the next. Its history, oldest first: "
                      f"{json.dumps(history, separators=(',', ':'))}. {tail}", second)
        # The wave changed another file too, so its notes say nothing about this one; a wave that changed it alone keeps them.
        self.assertNotIn("narrowed the pattern", second.split("Its history")[1].split("Read each range")[0])
        alone = self.two(self.found(("tools/grader.json", "pattern too narrow", "new"), changed=self.ONLY["changed_files"]),
                         **{"fix-wave": dict(self.ONLY, notes="narrowed the pattern")})
        history[1] = {"wave": 1, "notes": "narrowed the pattern", "range": "b0..c0ffee"}
        self.assertIn(f"Its history, oldest first: {json.dumps(history, separators=(',', ':'))}. {tail}", prompt(alone["calls"], "fix-wave-2"))
        self.assertIn("pattern too narrow", second)
        self.assertNotIn(self.HISTORY, prompt(calls, "fix-wave"))

    def test_later_waves_do_not_carry_settled_first_round_findings(self):
        out = self.two(self.found(("src/lock.py", "lock race on another path", "narrowing"), ("src/renew.py", "same leak", "narrowing")),
                       self.found(("src/zzz.py", "elsewhere", "new"), changed=["src/zzz.py"]),
                       **{"fix-wave-2": {"changed_files": ["src/zzz.py"]}})
        calls = out["calls"]
        self.assertEqual(waves(calls), ThirdFixWaveTest.THREE)
        second, third = prompt(calls, "fix-wave-2"), prompt(calls, "fix-wave-3")
        self.assertIn(f"They narrow these first-round findings: {json.dumps(self.FIRST['findings'][1:], separators=(',', ':'))}. "
                      "The other 1 is settled.", second)
        self.assertNotIn("pattern too wide", second)
        self.assertIn(" They follow the fix of the first-round findings (any not marked narrowing is a defect in a file the previous fix "
                      "wave changed); none of those is still open.", third)
        for gone in ("pattern too wide", "settled renew leak", "settled lock race"):
            self.assertNotIn(gone, third)
        self.assertIn("pattern too wide", prompt(calls, "fix-wave"))
        # A turning file's first-round findings are in its history, once.
        turned = prompt(self.two(self.found(("tools/grader.json", "pattern too narrow", "new")))["calls"], "fix-wave-2")
        self.assertEqual(turned.count("pattern too wide"), 1)
        self.assertIn(" They follow the fix of the first-round findings (any not marked narrowing is a defect in a file the previous "
                      "fix wave changed); none of those is still open.", turned)
        self.assertNotIn("all settled", PROGRAM.read_text(encoding="utf-8"))
        self.assertNotIn("settled lock race", turned)

    def test_a_finding_that_names_no_file_keeps_what_cannot_be_told_settled(self):
        first = {"verdict": "findings", "findings": self.FIRST["findings"] + [{"severity": "important", "summary": "no file here"}]}
        after = self.found(("src/lock.py", "lock race on another path", "narrowing"))
        _, calls = run(replies={"final-1": first, "fix-wave-review": after})
        second = prompt(calls, "fix-wave-2")
        self.assertIn("no file here", second)
        self.assertIn("settled lock race", second)
        self.assertNotIn("settled renew leak", second)
        self.assertIn("The other 2 are settled.", second)
        nowhere = {"verdict": "findings", "findings": [{"severity": "important", "summary": "somewhere", "relation": "narrowing"}]}
        _, calls = run(replies={"final-1": self.FIRST, "fix-wave-review": nowhere})
        second = prompt(calls, "fix-wave-2")
        self.assertIn(f"They narrow these first-round findings: {json.dumps(self.FIRST['findings'], separators=(',', ':'))}. If", second)
        self.assertNotIn("settled.", second)

    def test_every_wave_is_told_to_change_nothing_no_finding_names(self):
        _, calls = run(replies={"final-1": ThirdFixWaveTest.FIRST, "fix-wave-review": ThirdFixWaveTest.AFTER_1,
                                "fix-wave-review-2": ThirdFixWaveTest.AFTER_2})
        for label in ("fix-wave", "fix-wave-2"):
            self.assertIn(self.SCOPE, prompt(calls, label))
        self.assertIn("not only the reported instance. If a finding is wrong, explain with evidence in notes. Change only what closing "
                      "that class needs, its regression tests included. ", prompt(calls, "fix-wave-3"))
        self.assertNotIn("Change nothing no finding names", PROGRAM.read_text(encoding="utf-8"))

    def test_a_narrowing_finding_whose_parent_cannot_be_told_keeps_every_first_round_finding(self):
        """Review S2: a narrowing finding in a file no first-round finding named narrows one of them, so none is called settled."""
        out = self.two(self.found(("src/new.py", "same race", "narrowing")), self.found(("src/new.py", "same race again", "narrowing")))
        for label in ("fix-wave-2", "fix-wave-3"):
            wave = prompt(out["calls"], label)
            self.assertIn(f"They narrow these first-round findings: {json.dumps(self.FIRST['findings'], separators=(',', ':'))}. ", wave)
            self.assertNotIn("settled.", wave)
            self.assertNotIn("still open", wave)
        # When every first-round finding is in the turning file's history, nothing is said about the rest.
        first = {"verdict": "findings", "findings": self.FIRST["findings"][:1]}
        after = self.found((self.FILE, "pattern too narrow", "new"), ("src/new.py", "same race", "narrowing"))
        _, calls = run(replies={"final-1": first, "fix-wave-review": after}, patch={"fix-wave": self.CHANGED})
        second = prompt(calls, "fix-wave-2")
        self.assertIn(self.HISTORY, second)
        self.assertNotIn("first-round findings", second)

    def test_a_round_of_the_history_is_bounded(self):
        """Review N1: ten findings a round, each text capped."""
        many = [{"severity": "important", "file": self.FILE, "summary": f"{i} " + "w" * 900} for i in range(14)]
        new = self.found((self.FILE, "n" * 900, "new"), changed=self.ONLY["changed_files"])
        out = run_out(replies={"final-1": {"verdict": "findings", "findings": many}, "fix-wave-review": new, "fix-wave-review-2": new},
                      patch={"fix-wave": dict(self.ONLY, notes="z" * 900), "fix-wave-2": self.ONLY})
        rounds = out["result"]["oscillating"]["rounds"]
        self.assertEqual([len(r["findings"]) for r in rounds if "findings" in r], [10, 1, 1])
        for entry in rounds:
            for text in entry.get("findings", []) + [entry.get("notes", "")]:
                self.assertLessEqual(len(text), 300)
        self.assertEqual(len(rounds[1]["notes"]), 300)
        self.assertEqual(out["result"]["cont"]["oscillating"], out["result"]["oscillating"])

    def test_a_second_new_finding_the_second_wave_did_not_change_is_a_plain_stop(self):
        """Review S5: the signal needs the file in the diff of the wave just re-reviewed, at the second firing as at the first."""
        after_2 = self.found((self.FILE, "pattern too wide again", "new"), changed=["src/lock.py"])
        out = self.two(self.found((self.FILE, "pattern too narrow", "new")), after_2, **{"fix-wave-2": {"changed_files": ["src/lock.py"]}})
        result = out["result"]
        self.assertEqual((result["stage"], result["fix_waves"]), ("fix-wave-review", 2))
        self.assertNotIn("oscillating", result)
        self.assertNotIn("oscillating", result["cont"])
        self.assertEqual([f["summary"] for f in result["cont"]["fix_findings"]], ["pattern too wide again"])

    def test_on_a_plan_with_declared_branches_the_history_range_names_the_issue_worktree(self):
        """Review N4: only the issue worktree's diff feeds the signal, and the wave's range is that worktree's."""
        wave = {"start_head": TIP, "commit": "e" * 40, "changed_files": ["tools/grader.json"],
                "branch_heads": [{"name": "cand", "head": "d" * 40}]}
        _, calls = run(replies={"plan": bplan(), "final-1": self.FIRST,
                                "fix-wave-review": self.found((self.FILE, "pattern too narrow", "new"), changed=["tools/grader.json"])},
                       patch={"impl-1": {"commit": TIP}, "impl-2": {"commit": "d" * 40}, "fix-wave": wave,
                              "fix-wave-2": {"start_head": "e" * 40, "commit": "f" * 40, "branch_heads": [{"name": "cand", "head": "d" * 40}]}})
        second = prompt(calls, "fix-wave-2")
        self.assertIn(f'"range":"{TIP}..{"e" * 40}"', second)
        self.assertIn("Read each range (git -C /r/.wt/w-issue-9-x diff <range> -- tools/grader.json)", second)

    def stopped(self):
        out = self.two(self.found((self.FILE, "pattern too narrow", "new")),
                       self.found((self.FILE, "pattern too wide again", "new"), changed=["tools/grader.json"]),
                       **{"fix-wave-2": dict(self.ONLY, notes="widened it again", start_head="d" * 40, commit="e" * 40)})
        self.assertEqual(out["result"]["stage"], "fix-wave-review")
        return out["result"]

    DECISION = "Match the literal token only; drop the alternation."
    KEPT = [{"round": 0, "findings": ["pattern too wide"]}, {"wave": 1, "range": "b0..c0ffee"},
            {"round": 1, "findings": ["pattern too narrow"]}, {"wave": 2, "notes": "widened it again", "range": f"{'d' * 40}..{'e' * 40}"}]

    def test_the_stop_keeps_the_marker_in_cont(self):
        stopped = self.stopped()
        self.assertEqual(stopped["cont"]["oscillating"], stopped["oscillating"])
        self.assertEqual(stopped["oscillating"]["rounds"], self.KEPT + [{"round": 2, "findings": ["pattern too wide again"]}])

    def test_a_resume_with_no_new_decision_stops_before_any_agent(self):
        """Review B1: nothing new from the owner would only turn the file once more."""
        cont = self.stopped()["cont"]
        held = dict(cont, decisions=["An earlier answer."])
        for name, c, more in (("none", cont, {}), ("blank", cont, {"decisions": "  "}), ("rerun", cont, {"decisions": "rerun"}),
                              ("already held", held, {"decisions": "An earlier answer."})):
            with self.subTest(name):
                result, calls = run(args=dict(ARGS, cont=c, **more))
                self.assertEqual(calls, [])
                self.assertEqual((result["stage"], result["fix_waves"]), ("fix-wave-review", 2))
                self.assertEqual(result["cont"], c)
                self.assertEqual(result["oscillating"], cont["oscillating"])
                self.assertEqual(result["reason"], "fix-wave-review: the fix waves go back and forth on tools/grader.json: two fixes of it "
                                 "in a row each drew a new finding there; an owner decision on the approach is needed; not run again: this "
                                 "resume brings nothing new from the owner; resume with decisions (the approach), or amend")
                self.assertLessEqual(len(result["reason"]), 300)
        # A cont whose open findings are gone has nothing to hold back.
        result, calls = run(args=dict(ARGS, cont={k: v for k, v in cont.items() if k != "fix_findings"}))
        self.assertNotEqual(calls, [])
        self.assertNotIn("oscillating", result.get("cont", {}))

    def resume(self, replies=None, patch=None, decisions=DECISION, cont=None):
        return run_out(args=dict(ARGS, cont=cont or self.stopped()["cont"], decisions=decisions), replies=replies, patch=patch)

    def test_a_resume_with_a_decision_gives_it_and_the_history_to_the_first_wave_and_its_re_review(self):
        out = self.resume(patch={"fix-wave": self.ONLY})
        result, calls = out["result"], out["calls"]
        self.assertEqual((result["stage"], result["fix_waves"]), ("done", 3))
        self.assertEqual(waves(calls), ThirdFixWaveTest.THREE[:2])
        decided = f" The owner decided the approach for tools/grader.json, and the decision is binding: {json.dumps(self.DECISION)}."
        history = json.dumps(self.KEPT, separators=(",", ":"))
        wave = prompt(calls, "fix-wave")
        self.assertIn(f" {self.HISTORY}: the fix of one finding drew the next.{decided} Its history, oldest first: {history}. Read each range "
                      "(git -C /r/.wt/w-issue-9-x diff <range> -- tools/grader.json), then follow that decision; do not move the same "
                      "lines back.", wave)
        self.assertIn("pattern too wide again", wave)
        self.assertIn(f"{decided} Report no finding that only disputes it. tools/grader.json was judged more than once in the same place "
                      f"before this fix; its history, oldest first: {history}. {program_const('CRITICAL_MEANS')} {program_const('SCOPED_BLOCKS')} ", prompt(calls, "fix-wave-review"))
        self.assertIn(" Report any still unresolved", prompt(calls, "fix-wave-review"))

    AMENDED = " The owner amended the plan for tools/grader.json (plan.md, Amendments): it is binding."

    def test_an_amend_only_resume_tells_the_wave_and_its_re_review_of_the_amendment(self):
        """Re-review X1: the amendment is what the owner brought, so the fixer and the re-reviewer are pointed at it."""
        cont = self.stopped()["cont"]
        out = run_out(args=dict(ARGS, cont=cont, amend=[dict(AMEND_EDIT, file="task-1.md")]), patch={"fix-wave": self.ONLY})
        result, calls = out["result"], out["calls"]
        self.assertEqual((result["stage"], result["fix_waves"]), ("done", 3))
        self.assertIn("amend", labels(calls))
        self.assertEqual(waves(calls), ThirdFixWaveTest.THREE[:2])
        history = json.dumps(self.KEPT, separators=(",", ":"))
        self.assertIn(f"the fix of one finding drew the next.{self.AMENDED} Its history, oldest first: {history}. Read each range "
                      "(git -C /r/.wt/w-issue-9-x diff <range> -- tools/grader.json), then follow that amendment; do not move the same "
                      "lines back.", prompt(calls, "fix-wave"))
        self.assertIn(f"{self.AMENDED} Report no finding that only disputes it. tools/grader.json was judged more than once",
                      prompt(calls, "fix-wave-review"))
        # A decision with the amend is the decision's clause.
        both = run_out(args=dict(ARGS, cont=cont, amend=[dict(AMEND_EDIT, file="task-1.md")], decisions=self.DECISION),
                       patch={"fix-wave": self.ONLY})
        self.assertIn(json.dumps(self.DECISION), prompt(both["calls"], "fix-wave"))
        self.assertNotIn(self.AMENDED, prompt(both["calls"], "fix-wave"))
        # A run that did not resume an oscillating cont says nothing of either.
        plain = self.two(self.found((self.FILE, "pattern too narrow", "new")))
        for label in ThirdFixWaveTest.THREE[:4]:
            self.assertNotIn("The owner ", prompt(plain["calls"], label))

    def test_every_wave_of_the_resumed_run_that_names_the_file_gets_the_decision_and_the_history(self):
        """Re-review Y1: a narrowing finding on the file admits a second wave, which is not left blind."""
        narrowing = self.found((self.FILE, "same on another token", "narrowing"), ("src/lock.py", "lock path", "narrowing"))
        elsewhere = self.found(("src/lock.py", "lock path 2", "narrowing"))
        out = self.resume(replies={"fix-wave-review": narrowing, "fix-wave-review-2": elsewhere},
                          patch={"fix-wave": dict(self.ONLY, notes="literal token", start_head="e" * 40, commit="f" * 40),
                                 "fix-wave-2": dict(self.ONLY, start_head="f" * 40, commit="a" * 40)})
        result, calls = out["result"], out["calls"]
        self.assertEqual((result["stage"], result["fix_waves"]), ("done", 5))
        self.assertEqual(waves(calls), ThirdFixWaveTest.THREE)
        decided = f" The owner decided the approach for tools/grader.json, and the decision is binding: {json.dumps(self.DECISION)}."
        history = json.dumps(self.KEPT + [{"round": 2, "findings": ["pattern too wide again"]},
                                          {"wave": 3, "notes": "literal token", "range": f"{'e' * 40}..{'f' * 40}"}], separators=(",", ":"))
        self.assertIn(f"the fix of one finding drew the next.{decided} Its history, oldest first: {history}. Read each range "
                      "(git -C /r/.wt/w-issue-9-x diff <range> -- tools/grader.json), then follow that decision;", prompt(calls, "fix-wave-2"))
        self.assertIn(f"{decided} Report no finding that only disputes it. tools/grader.json was judged more than once in the same place "
                      f"before this fix; its history, oldest first: {history}.", prompt(calls, "fix-wave-review-2"))
        # The third wave's findings no longer name the file: neither the decision nor the history.
        for label in ("fix-wave-3", "fix-wave-review-3"):
            self.assertNotIn("The owner decided", prompt(calls, label))
            self.assertNotIn("judged more than once", prompt(calls, label))

    def test_the_decision_is_kept_once_a_wave_has_had_it_and_stays_new_until_then(self):
        lost = self.resume(replies={"fix-wave": None})["result"]
        self.assertEqual(lost["stage"], "fix-wave")
        self.assertNotIn("decisions", lost["cont"])
        self.assertEqual(lost["cont"]["oscillating"]["file"], self.FILE)
        again = self.resume(cont=lost["cont"], patch={"fix-wave": self.ONLY})
        self.assertIn(json.dumps(self.DECISION), prompt(again["calls"], "fix-wave"))
        had = self.resume(replies={"fix-wave-review": None})["result"]
        self.assertEqual(had["cont"]["decisions"], [self.DECISION])

    def test_a_third_turn_on_the_file_stops_again_with_the_whole_history(self):
        turn = self.found((self.FILE, "pattern too narrow again", "new"), changed=["tools/grader.json"])
        out = self.resume(replies={"fix-wave-review": turn},
                          patch={"fix-wave": dict(self.ONLY, notes="literal token", start_head="e" * 40, commit="f" * 40)})
        result, calls = out["result"], out["calls"]
        self.assertEqual((result["stage"], result["fix_waves"]), ("fix-wave-review", 3))
        self.assertEqual(waves(calls), ThirdFixWaveTest.THREE[:2])
        rounds = self.KEPT + [{"round": 2, "findings": ["pattern too wide again"]},
                              {"wave": 3, "notes": "literal token", "range": f"{'e' * 40}..{'f' * 40}"},
                              {"round": 3, "findings": ["pattern too narrow again"]}]
        self.assertEqual(result["oscillating"], {"file": self.FILE, "rounds": rounds})
        self.assertEqual(result["cont"]["oscillating"], result["oscillating"])
        self.assertEqual(result["cont"]["decisions"], [self.DECISION])
        # The decision it carried is held now, so the same resume again stops before any agent.
        same, calls = run(args=dict(ARGS, cont=result["cont"], decisions=self.DECISION))
        self.assertEqual(calls, [])
        self.assertEqual(same["stage"], "fix-wave-review")

    def test_a_resumed_wave_that_clears_the_file_drops_the_marker(self):
        other = self.found(("src/lock.py", "another file", "new"), changed=["tools/grader.json"])
        result = self.resume(replies={"fix-wave-review": other}, patch={"fix-wave": self.ONLY})["result"]
        self.assertEqual(result["stage"], "fix-wave-review")
        self.assertNotIn("oscillating", result)
        self.assertNotIn("oscillating", result["cont"])

    def test_the_kept_history_is_bounded_on_the_way_in(self):
        cont = self.stopped()["cont"]
        junk = [{"round": i, "findings": ["x" * 900] * 30 + [7], "extra": 1} for i in range(40)] + ["junk"]
        out = self.resume(cont=dict(cont, oscillating={"file": self.FILE, "rounds": junk}), patch={"fix-wave": self.ONLY})
        kept = json.loads(prompt(out["calls"], "fix-wave").split("Its history, oldest first: ")[1].split(". Read each range")[0])
        self.assertLessEqual(len(kept), 12)
        self.assertEqual((sorted(kept[0]), len(kept[0]["findings"]), len(kept[0]["findings"][0])), (["findings", "round"], 10, 300))

    def test_the_signal_needs_a_new_finding_the_fix_diff_and_a_finding_the_round_before(self):
        rows = (("a narrowing finding", self.found((self.FILE, "another path", "narrowing")), self.CHANGED),
                ("a file the round before did not name", self.found(("src/lock.py", "x", "narrowing"), ("src/fresh.py", "y", "new"),
                                                                    changed=["src/fresh.py"]), {"changed_files": ["src/fresh.py"]}))
        for name, after_1, wave in rows:
            with self.subTest(name):
                out = self.two(after_1, **{"fix-wave": wave})
                self.assertEqual((out["result"]["stage"], out["result"]["fix_waves"]), ("done", 2))
                self.assertNotIn("judged more than once", prompt(out["calls"], "fix-wave-2"))
        # Outside the fix diff a new finding stops as it did (#950), unmarked.
        out = self.two(self.found((self.FILE, "pattern too narrow", "new")), **{"fix-wave": {"changed_files": ["src/lock.py"]}})
        self.assertEqual((out["result"]["stage"], out["result"]["fix_waves"]), ("fix-wave-review", 1))
        self.assertNotIn("oscillating", out["result"])

    def test_the_second_firing_on_the_file_stops_for_the_owner_with_its_history(self):
        after_2 = self.found((self.FILE, "pattern too wide again", "new"), changed=["tools/grader.json"])
        out = self.two(self.found(("tools/grader.json:16", "pattern too narrow", "new")), after_2)
        result, calls = out["result"], out["calls"]
        self.assertEqual((result["stage"], result["fix_waves"]), ("fix-wave-review", 2))
        self.assertEqual(waves(calls), ThirdFixWaveTest.THREE[:4])
        self.assertEqual(result["oscillating"], {"file": self.FILE, "rounds": [
            {"round": 0, "findings": ["pattern too wide"]}, {"wave": 1, "range": "b0..c0ffee"},
            {"round": 1, "findings": ["pattern too narrow"]}, {"wave": 2, "range": f"{'d' * 40}..{'e' * 40}"},
            {"round": 2, "findings": ["pattern too wide again"]}]})
        self.assertTrue(result["reason"].startswith("fix-wave-review: the fix waves go back and forth on tools/grader.json: two fixes of "
                                                    "it in a row each drew a new finding there; an owner decision on the approach is needed"),
                        result["reason"])
        self.assertLessEqual(len(result["reason"]), 300)
        self.assertEqual([f["summary"] for f in result["cont"]["fix_findings"]], ["pattern too wide again"])
        self.assertNotIn("diverging", result)
        self.assertEqual(len([line for line in out["logs"] if "fix waves 1 and 2 each drew a new finding in tools/grader.json" in line]), 1)

    def test_a_second_firing_on_another_file_is_a_first_firing(self):
        after_2 = self.found(("src/lock.py", "lock regressed", "new"), changed=["src/lock.py"])
        out = self.two(self.found((self.FILE, "pattern too narrow", "new"), ("src/lock.py", "lock path", "narrowing")), after_2,
                       **{"fix-wave-2": {"changed_files": ["src/lock.py"], "notes": "locked"}})
        result, calls = out["result"], out["calls"]
        self.assertEqual((result["stage"], result["fix_waves"]), ("done", 3))
        third = prompt(calls, "fix-wave-3")
        self.assertIn("src/lock.py has now been judged more than once in the same place", third)
        self.assertNotIn(self.HISTORY, third)
        # Every finding of the third wave is in the turning file: no class sentence at all.
        self.assertNotIn(ThirdFixWaveTest.CLASS, third)
        self.assertIn(self.SCOPE, third)

    def test_the_class_sentence_leaves_the_turning_file_out(self):
        after_1 = self.found((self.FILE, "pattern too narrow", "narrowing"), ("src/lock.py", "lock path", "narrowing"))
        after_2 = self.found((self.FILE, "pattern too wide again", "new"), ("src/lock.py", "lock path 2", "narrowing"),
                             changed=["tools/grader.json"])
        out = self.two(after_1, after_2)
        self.assertEqual((out["result"]["stage"], out["result"]["fix_waves"]), ("done", 3))
        third = prompt(out["calls"], "fix-wave-3")
        self.assertIn(self.HISTORY, third)
        self.assertIn("close them all, not only the reported instance. Not in tools/grader.json: fix only what is reported there. If", third)
        history = third.split("Its history, oldest first: ")[1].split(". Read each range")[0]
        self.assertEqual([e.get("findings", e.get("range")) for e in json.loads(history)],
                         [["pattern too wide"], "b0..c0ffee", ["pattern too narrow"], f"{'d' * 40}..{'e' * 40}"])

    def test_a_second_firing_at_the_last_wave_is_marked_too(self):
        after_1 = self.found((self.FILE, "pattern too narrow", "narrowing"))

        def new(summary):
            return self.found((self.FILE, summary, "new"), changed=["tools/grader.json"])
        replies = {"final-1": self.FIRST, "fix-wave-review": after_1, "fix-wave-review-2": new("too wide again"),
                   "fix-wave-review-3": new("too narrow again")}
        patch = {k: self.CHANGED for k in ("fix-wave", "fix-wave-2", "fix-wave-3")}
        result, calls = run(replies=replies, patch=patch)
        self.assertEqual((result["stage"], result["fix_waves"]), ("fix-wave-review", 3))
        self.assertEqual(waves(calls), ThirdFixWaveTest.THREE)
        self.assertEqual(result["oscillating"]["file"], self.FILE)
        self.assertEqual(len(result["oscillating"]["rounds"]), 7)
        # A first firing at the last wave is the plain stop at the wave bound.
        once, _ = run(replies=dict(replies, **{"fix-wave-review-2": self.found((self.FILE, "still", "narrowing"))}), patch=patch)
        self.assertEqual((once["stage"], once["fix_waves"]), ("fix-wave-review", 3))
        self.assertNotIn("oscillating", once)


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
        self.assertEqual(labels(calls), ["setup", "pr", "land-take", "merge", "hold", "close-out"])

    def test_ship_after_ready_reviews_again_when_the_head_moved_or_is_dirty(self):
        ready, _ = run(args=dict(ARGS, mode="ready"))
        for patch in ({"head": "e" * 40}, {"head": SHA, "dirty": True}):
            with self.subTest(patch=patch):
                result, calls = run(args=dict(ARGS, cont=ready["cont"]), patch={"setup": patch})
                if patch.get("dirty"):
                    self.assertEqual(result["stage"], "dirty")
                    continue
                for label in ("final-scoped", "verify"):
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
                self.assertIn(slotted(verification), prompt(calls, "verify"))


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
                self.assertEqual(labels(calls), ["setup", "verify", "pr", "land-take", "merge", "hold", "close-out"])

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
                self.assertIn("final-scoped", labels(calls))
        stopped, _ = run(args=dict(ARGS, cont=cont), replies={"verify": None}, patch={"setup": {"head": "e" * 40}})
        self.assertEqual(stopped["cont"]["final_reviewed"], {"head": "e" * 40})

    def test_resume_with_an_unfinished_task_reviews_again(self):
        cont = dict(self.stopped_after_review()["cont"], done=[])
        result, calls = run(args=dict(ARGS, cont=cont), patch={"setup": {"head": TIP}})
        self.assertEqual(result["stage"], "done")
        names = labels(calls)
        self.assertLess(names.index("impl-1"), names.index("final-scoped"))

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
                         patch=dict({"land-take": {"behind": True}, "impl-1": {"commit": TIP},
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
                self.assertIn("final-scoped", names)
                self.assertLess(names.index("final-scoped"), names.index("merge"))
                self.assertNotIn("since_reviewed", prompt(calls, "setup"))

    def test_an_accepted_conflicted_merge_keeps_the_skip(self):
        stopped = self.sync_stop({"green-checks-1": None}, {})
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
        self.assertIn("final-scoped", labels(calls))

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
        stopped, _ = run(args=dict(ARGS, cont=cont), replies={"final-scoped": None}, patch={"setup": {"head": "e" * 40}})
        self.assertEqual(stopped["stage"], "final-review")
        self.assertNotIn("final_reviewed", stopped["cont"])

    def test_a_dirty_tree_on_the_reviewed_head_reviews_again(self):
        cont = dict(self.stopped_after_review()["cont"], partial=1)
        result, calls = run(args=dict(ARGS, cont=cont), patch={"setup": {"head": TIP, "dirty": True}})
        self.assertEqual(result["stage"], "done")
        self.assertIn("final-scoped", labels(calls))

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
        for member in ("final_reviewed", "review_rounds", "reviewed"):
            del cont[member]
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
        self.assertEqual(labels(calls), ["setup", "pr", "land-take", "merge", "hold", "close-out"])

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


LIVE_START = "b" * 40
DECLARED = {"verdict": "declared", "sprint_id": "0123456789abcdef",
            "fault": {"id": 5, "issue": 9, "observed": "saving the settings form drops the billing address",
                      "when": "12:10 UTC", "proven": "a saved form read back from the database",
                      "at": "2026-11-21T12:10:00.123456+00:00"}}
LIVE_PATCH = {"setup": {"live_fault": DECLARED}}
FT = {"name": "test_harm", "file": "tests/test_harm.py",
      "red": {"command": "pytest tests/test_harm.py::test_harm", "exit": 1, "head": LIVE_START, "failed": ["test_harm"],
              "output": "AssertionError: the billing address was dropped"},
      "green": {"command": "pytest tests/test_harm.py::test_harm", "exit": 0, "head": SHA, "passed": ["test_harm"]}}
LIVE_IMPL_REPLY = {"status": "done", "start_head": LIVE_START, "commit": SHA, "tests": ["t"], "notes": "ok",
                   "acceptance": [{"id": "AC1", "text": "works", "kind": "code"}], "fault_test": FT, "beyond": []}


def with_ft(**changes):
    """The default fault_test with the named parts replaced: red=/green= merge into their run, the rest replace."""
    ft = copy.deepcopy(FT)
    for key, value in changes.items():
        if key in ("red", "green"):
            ft[key].update(value)
        else:
            ft[key] = value
    return ft


class LiveLaneTest(unittest.TestCase):
    """#1433: a declared live fault runs one implementer with failing-then-passing evidence and one review, no plan."""

    def test_a_declared_issue_runs_one_implementer_and_one_reviewer_and_no_plan(self):
        result, calls = run(args=ARGS, patch=LIVE_PATCH)
        self.assertEqual(result["stage"], "done")
        names = labels(calls)
        self.assertFalse([l for l in names if l.startswith("plan") or l == "owner-answer"], names)
        self.assertFalse([l for l in names if l.endswith("-codex")], names)
        self.assertEqual([c["label"] for c in calls if c["agentType"] == "implementer"], ["live-impl"])
        reviewers = [(c["label"], c["agentType"]) for c in calls if c["agentType"] in ("reviewer", "reviewer-lite")]
        self.assertEqual(reviewers, [("live-review", "reviewer")])
        self.assertLess(names.index("renew-tasks"), names.index("live-impl"))
        self.assertLess(names.index("live-impl"), names.index("live-review"))
        self.assertLess(names.index("live-review"), names.index("verify"))
        self.assertLess(names.index("verify"), names.index("pr"))

    def test_the_setup_reads_the_declaration_unless_a_lane_is_chosen(self):
        for args, patch in ((ARGS, None), (dict(ARGS, lane="live"), LIVE_PATCH)):
            _, calls = run(args=args, patch=patch)
            text = prompt(calls, "setup")
            self.assertIn("sprint recap", text)
            self.assertIn("sprint: no sprint id", text)
        for lane in ("standard", "direct"):
            _, calls = run(args=dict(ARGS, lane=lane))
            self.assertNotIn("sprint recap", prompt(calls, "setup"))

    def test_an_explicit_standard_lane_reads_no_declaration(self):
        _, calls = run(args=dict(ARGS, lane="standard"), patch=LIVE_PATCH)
        self.assertIn("plan", labels(calls))
        self.assertNotIn("live-impl", labels(calls))

    def test_an_explicit_live_lane_without_a_standing_declaration_stops(self):
        wrong_issue = copy.deepcopy(DECLARED)
        wrong_issue["fault"]["issue"] = 10
        for reply in ({"verdict": "none"}, {"verdict": "no-sprint"}, wrong_issue, dict(DECLARED, sprint_id="x")):
            with self.subTest(reply=reply):
                result, calls = run(args=dict(ARGS, lane="live"), patch={"setup": {"live_fault": reply}})
                self.assertEqual(result["stage"], "live-fault")
                self.assertIn("rerun with lane standard and no cont", result["reason"])
                self.assertNotIn("live-impl", labels(calls))
                self.assertEqual(result["cont"]["lane"], "live")

    def test_an_unread_declaration_stops_a_lane_less_run_before_any_planner(self):
        for live_fault in ({"verdict": "error", "detail": "console down"}, None, {"verdict": "declared"}):
            with self.subTest(live_fault=live_fault):
                result, calls = run(args=ARGS, patch={"setup": {"live_fault": live_fault}})
                self.assertEqual(result["stage"], "live-fault")
                self.assertIn("could not be read", result["reason"])
                self.assertFalse([l for l in labels(calls) if l.startswith("plan")], labels(calls))
                self.assertNotIn("live-impl", labels(calls))
                self.assertEqual(result["cont"]["lane"], "live")
                resumed, calls = run(args=dict(ARGS, cont=result["cont"]), patch={"setup": {"head": SHA, "live_fault": DECLARED}})
                self.assertIn("live-impl", labels(calls))
        _, calls = run(args=ARGS, patch={"setup": {"live_fault": {"verdict": "no-sprint"}}})
        self.assertIn("plan", labels(calls))

    def test_an_early_stop_on_a_declared_issue_keeps_the_live_lane(self):
        result, _ = run(args=ARGS, patch={"setup": {"ok": False, "reason": "not-resumable", "live_fault": DECLARED}})
        self.assertEqual(result["stage"], "setup")
        self.assertEqual(result["cont"]["lane"], "live")
        stopped, _ = run(args=ARGS, patch={"setup": {"live_fault": DECLARED, "claim": {"ok": False, "reason": "worktree"}}})
        self.assertEqual(stopped["stage"], "claim")
        self.assertEqual(stopped["cont"]["lane"], "live")
        _, calls = run(args=dict(ARGS, cont=stopped["cont"]), patch={"setup": {"live_fault": DECLARED}})
        self.assertNotIn("plan", labels(calls))
        self.assertIn("live-impl", labels(calls))

    def test_a_declared_issue_in_plan_mode_stops(self):
        result, calls = run(args=dict(ARGS, mode="plan"), patch=LIVE_PATCH)
        self.assertEqual(result["stage"], "live-fault")
        self.assertIn("no plan mode", result["reason"])
        self.assertNotIn("live-impl", labels(calls))
        self.assertNotIn("plan", labels(calls))
        result, calls = run(args=dict(ARGS, lane="live", mode="plan"))
        self.assertEqual(result, {"stage": "args", "error": "the live-fault lane has no plan mode"})
        self.assertEqual(calls, [])

    def test_a_change_without_failing_then_passing_evidence_stops(self):
        reply = dict(LIVE_IMPL_REPLY)
        without = {k: v for k, v in reply.items() if k != "fault_test"}
        cases = {
            "absent": {"live-impl": without},
            "red passed": {"live-impl": dict(reply, fault_test=with_ft(red={"exit": 0}))},
            "red never ran": {"live-impl": dict(reply, fault_test=with_ft(red={"exit": 127, "failed": []}))},
            "another test failed": {"live-impl": dict(reply, fault_test=with_ft(red={"failed": ["test_other"]}))},
            "no failure line": {"live-impl": dict(reply, fault_test=with_ft(red={"output": ""}))},
            "green failed": {"live-impl": dict(reply, fault_test=with_ft(green={"exit": 1}))},
            "green passed nothing": {"live-impl": dict(reply, fault_test=with_ft(green={"passed": []}))},
            "another selector": {"live-impl": dict(reply, fault_test=with_ft(green={"command": "pytest tests/test_other.py::test_other"}))},
            "red at another head": {"live-impl": dict(reply, fault_test=with_ft(red={"head": "e" * 40}))},
            "green at another head": {"live-impl": dict(reply, fault_test=with_ft(green={"head": "e" * 40}))},
            "no name": {"live-impl": dict(reply, fault_test=with_ft(name=""))},
            "nothing committed": {"live-impl": dict(reply, commit=LIVE_START, fault_test=with_ft(green={"head": LIVE_START}))},
        }
        for name, replies in cases.items():
            with self.subTest(case=name):
                result, calls = run(args=ARGS, patch=LIVE_PATCH, replies=replies)
                self.assertEqual(result["stage"], "live-evidence")
                self.assertTrue(result["reason"].startswith("live-evidence: the change carries no test shown failing before it and passing after it"), result["reason"])
                self.assertIn("rerun with lane standard and no cont", result["reason"])
                self.assertNotIn("live-review", labels(calls))
                self.assertNotIn("verify", labels(calls))
                self.assertNotIn("partial", result["cont"])
                self.assertEqual(result["cont"]["live_fault"]["final"], "live-evidence")
        result, _ = run(args=ARGS, patch=LIVE_PATCH)
        self.assertEqual(result["stage"], "done")

    def test_a_committed_reply_without_criteria_is_final_and_asks_no_second_implementer(self):
        without = {k: v for k, v in LIVE_IMPL_REPLY.items() if k != "acceptance"}
        for name, reply in (("empty", dict(LIVE_IMPL_REPLY, acceptance=[])), ("absent", without)):
            with self.subTest(reply=name):
                stopped, calls = run(args=ARGS, patch=LIVE_PATCH, replies={"live-impl": reply})
                self.assertEqual(stopped["stage"], "live-bound")
                self.assertIn("no acceptance criteria", stopped["reason"])
                self.assertIn("rerun with lane standard and no cont", stopped["reason"])
                self.assertNotIn("partial", stopped["cont"])
                self.assertEqual(stopped["cont"]["live_fault"]["final"], "live-bound")
                result, calls = run(args=dict(ARGS, cont=stopped["cont"]), patch={"setup": {"head": SHA, "live_fault": DECLARED}})
                self.assertEqual(result["stage"], "live-bound")
                self.assertIn("already stopped at live-bound", result["reason"])
                self.assertEqual([c["label"] for c in calls if c["agentType"] == "implementer"], [])

    def test_a_final_live_stop_does_not_resume(self):
        stopped, _ = run(args=ARGS, patch=LIVE_PATCH, replies={"live-impl": dict(LIVE_IMPL_REPLY, fault_test=with_ft(red={"exit": 0}))})
        result, calls = run(args=dict(ARGS, cont=stopped["cont"]), patch={"setup": {"head": SHA, "live_fault": DECLARED}})
        self.assertEqual(result["stage"], "live-evidence")
        self.assertIn("already stopped at live-evidence", result["reason"])
        self.assertNotIn("live-impl", labels(calls))

    def test_the_implementer_is_called_once_after_its_own_renew(self):
        _, calls = run(args=ARGS, patch=LIVE_PATCH)
        schema = schema_of(calls, "live-impl")
        self.assertNotIn("renew", schema["properties"])
        self.assertLessEqual({"fault_test", "beyond"}, set(schema["properties"]))
        self.assertEqual(schema["required"], ["status", "notes"])
        result, calls = run(args=ARGS, patch=LIVE_PATCH, replies={"live-impl": None})
        self.assertEqual(result["stage"], "task")
        self.assertEqual([c["label"] for c in calls if c["agentType"] == "implementer"], ["live-impl"])
        self.assertEqual(result["cont"]["partial"], 1)
        result, calls = run(args=ARGS, patch=dict(LIVE_PATCH, **{"live-impl": {"status": "blocked", "notes": "needs a schema change"}}))
        self.assertEqual(result["stage"], "live-bound")
        self.assertEqual(result["cont"]["live_fault"]["final"], "live-bound")
        self.assertEqual([c["label"] for c in calls if c["agentType"] == "implementer"], ["live-impl"])

    def test_the_live_implementer_is_told_the_fault_and_the_test_first_order(self):
        _, calls = run(args=ARGS, patch=LIVE_PATCH)
        text = prompt(calls, "live-impl")
        for piece in (DECLARED["fault"]["observed"], "smallest change that stops the harm", "it must fail",
                      "run the same command again", "it must pass", "beyond"):
            self.assertIn(piece, text)

    def test_an_unusable_review_is_not_asked_again(self):
        result, calls = run(args=ARGS, patch=LIVE_PATCH, replies={"live-review": INCOMPLETE})
        self.assertEqual(result["stage"], "live-review")
        self.assertNotIn("live-review-again", labels(calls))
        self.assertEqual(result["lost_reviews"], ["live-review"])
        self.assertIn("rerun with lane standard and no cont", result["reason"])
        self.assertEqual(result["cont"]["live_fault"]["final"], "live-review")
        resumed, calls = run(args=dict(ARGS, cont=result["cont"]), patch={"setup": {"head": SHA, "live_fault": DECLARED}})
        self.assertEqual(resumed["stage"], "live-review")
        self.assertIn("already stopped at live-review", resumed["reason"])
        self.assertFalse([c["label"] for c in calls if c["agentType"] in ("reviewer", "reviewer-lite")])
        result, _ = run(args=ARGS, patch=dict(LIVE_PATCH, **{"live-review": {"head": "e" * 40}}))
        self.assertEqual(result["stage"], "live-bound")

    def test_a_reviewer_that_answered_nothing_is_the_one_step_a_resume_runs_again(self):
        stopped, _ = run(args=ARGS, patch=LIVE_PATCH, replies={"live-review": None})
        self.assertEqual(stopped["stage"], "live-review")
        self.assertEqual(stopped["dead_agents"], ["live-review"])
        self.assertNotIn("final", stopped["cont"]["live_fault"])
        result, calls = run(args=dict(ARGS, cont=stopped["cont"]), patch={"setup": {"head": SHA, "live_fault": DECLARED}})
        self.assertEqual(result["stage"], "done")
        self.assertEqual([c["label"] for c in calls if c["agentType"] in ("reviewer", "reviewer-lite")], ["live-review"])
        self.assertNotIn("live-impl", labels(calls))

    def test_a_live_stop_resumes_in_the_live_lane(self):
        stopped, _ = run(args=ARGS, patch=LIVE_PATCH, replies={"verify": None})
        self.assertEqual(stopped["cont"]["lane"], "live")
        self.assertEqual(stopped["cont"]["live_fault"],
                         {"id": 5, "sprint_id": "0123456789abcdef", "issue": 9, "at": DECLARED["fault"]["at"]})
        self.assertEqual(stopped["cont"]["done"][0]["fault_test"]["red"]["exit"], 1)
        result, calls = run(args=dict(ARGS, cont=stopped["cont"]), patch={"setup": {"head": SHA, "live_fault": DECLARED}})
        self.assertEqual(result["stage"], "done")
        self.assertNotIn("live-impl", labels(calls))
        self.assertNotIn("live-review", labels(calls))
        self.assertIn("sprint recap", prompt(calls, "setup"))
        result, _ = run(args=dict(ARGS, cont=stopped["cont"]), patch={"setup": {"head": SHA, "live_fault": {"verdict": "none"}}})
        self.assertEqual(result["stage"], "live-fault")

    def test_a_replaced_declaration_stops_the_resume(self):
        stopped, _ = run(args=ARGS, patch=LIVE_PATCH, replies={"verify": None})
        replaced = copy.deepcopy(DECLARED)
        replaced["fault"].update({"id": 6, "at": "2026-11-21T13:00:00.000000+00:00"})
        result, calls = run(args=dict(ARGS, cont=stopped["cont"]), patch={"setup": {"head": SHA, "live_fault": replaced}})
        self.assertEqual(result["stage"], "live-fault")
        self.assertIn("withdrawn or replaced", result["reason"])
        self.assertNotIn("live-review", labels(calls))

    def test_a_blocked_codex_capability_does_not_stop_the_live_lane(self):
        blocked = {"review_state": {"code": "blocked", "plan": "blocked"}}
        result, calls = run(args=ARGS, patch={"setup": dict(blocked, live_fault=DECLARED)})
        self.assertEqual(result["stage"], "done")
        self.assertFalse([l for l in labels(calls) if l.endswith("-codex")], labels(calls))
        result, _ = run(args=ARGS, patch={"setup": blocked})
        self.assertEqual(result["stage"], "review-blocked")

    def test_the_lane_arg_takes_live_only(self):
        result, calls = run(args=dict(ARGS, lane="fast"))
        self.assertEqual(result, {"stage": "args", "error": "lane must be standard, direct or live"})
        self.assertEqual(calls, [])


def live_sized(*rows, sensitive=()):
    """A live-size patch from (path, added, deleted) rows."""
    return {"live-size": {"measured": True, "head": SHA, "sensitive": [dict(s) for s in sensitive],
                          "files": [{"path": p, "added": a, "deleted": d} for p, a, d in rows]}}


def refused_with(what):
    return f"live-refused: {what}; deliver the fault in an ordinary delivery: rerun with lane standard and no cont"


class LiveSizeTest(unittest.TestCase):
    """#1433: the size and sensitivity of the diff are read before the one review, and a refusal calls no reviewer."""

    def refusal(self, patch, reason):
        result, calls = run(args=ARGS, patch=dict(LIVE_PATCH, **patch))
        self.assertEqual(result["stage"], "live-refused")
        self.assertEqual(result["reason"], reason)
        self.assertNotIn("\n", result["reason"])
        self.assertEqual(result["cont"]["live_fault"]["final"], "live-refused")
        self.assertNotIn("live-review", labels(calls))
        self.assertNotIn("verify", labels(calls))

    def test_a_diff_over_80_lines_outside_tests_is_refused_in_one_line(self):
        self.refusal(live_sized(("src/a.py", 60, 30), ("tests/test_a.py", 40, 0)),
                     refused_with("the diff changes 90 lines outside tests, over the live lane's 80"))

    def test_a_fourth_file_is_refused(self):
        self.refusal(live_sized(("src/a.py", 1, 0), ("src/b.py", 1, 0), ("src/c.py", 1, 0), ("tests/test_a.py", 1, 0)),
                     refused_with("the diff changes 4 files, over the live lane's 3"))

    def test_a_sensitive_change_is_refused(self):
        patch = live_sized(("src/fix.py", 5, 2), ("tests/test_harm.py", 20, 0),
                      sensitive=[{"path": "src/auth.py", "why": "authentication"}])
        self.refusal(patch, refused_with("the diff touches authentication in src/auth.py"))

    def test_80_lines_outside_tests_in_3_files_pass(self):
        result, _ = run(args=ARGS, patch=dict(LIVE_PATCH, **live_sized(("src/a.py", 50, 30), ("tests/test_harm.py", 300, 0), ("src/b.py", 0, 0))))
        self.assertEqual(result["stage"], "done")

    def test_test_lines_do_not_count(self):
        for path in ("tests/x.py", "pkg/__tests__/x.js", "spec/x_spec.rb", "test_x.py", "x_test.go", "src/x.test.ts", "src/x.spec.js"):
            with self.subTest(path=path):
                impl = dict(LIVE_IMPL_REPLY, fault_test=with_ft(file=path))
                result, _ = run(args=ARGS, patch=dict(LIVE_PATCH, **live_sized((path, 500, 0), ("src/fix.py", 10, 0))), replies={"live-impl": impl})
                self.assertEqual(result["stage"], "done")
        self.refusal(live_sized(("src/testing.py", 500, 0), ("src/fix.py", 10, 0)),
                     refused_with("the diff changes 510 lines outside tests, over the live lane's 80"))

    def test_an_unmeasured_diff_stops_before_the_review(self):
        for reply in ({"measured": False}, None):
            with self.subTest(reply=reply):
                result, calls = run(args=ARGS, patch=LIVE_PATCH, replies={"live-size": reply})
                self.assertEqual(result["stage"], "live-size")
                self.assertIn("the live-fault diff could not be measured", result["reason"])
                self.assertNotIn("live-review", labels(calls))
                self.assertNotIn("final", result["cont"]["live_fault"])
        resumed, calls = run(args=dict(ARGS, cont=result["cont"]), patch={"setup": {"head": SHA, "live_fault": DECLARED}})
        self.assertEqual(resumed["stage"], "done")
        self.assertIn("live-size", labels(calls))
        self.assertNotIn("live-impl", labels(calls))

    def test_a_malformed_measurement_is_unmeasured(self):
        good = {"measured": True, "head": SHA, "files": [{"path": "src/a.py", "added": 1, "deleted": 0}], "sensitive": []}
        for bad in (dict(good, files="src/a.py"), dict(good, files=[{"path": "src/a.py", "added": "1", "deleted": 0}]),
                    dict(good, files=[{"added": 1, "deleted": 0}]), dict(good, sensitive=None), {"measured": True, "head": SHA}):
            with self.subTest(bad=bad):
                result, calls = run(args=ARGS, patch=LIVE_PATCH, replies={"live-size": bad})
                self.assertEqual(result["stage"], "live-size")
                self.assertNotIn("live-review", labels(calls))

    def test_the_size_step_runs_before_the_review(self):
        _, calls = run(args=ARGS, patch=LIVE_PATCH)
        names = labels(calls)
        self.assertLess(names.index("renew-final-review"), names.index("live-size"))
        self.assertLess(names.index("live-size"), names.index("live-review"))
        props = schema_of(calls, "live-size")["properties"]
        for key in ("files", "sensitive", "head"):
            self.assertIn(key, props)
        text = prompt(calls, "live-size")
        self.assertIn("git -C /r/.wt/w-issue-9-x diff --numstat --no-renames origin/dev...HEAD", text)
        self.assertIn("git -C /r/.wt/w-issue-9-x diff --no-renames origin/dev...HEAD", text)
        for piece in ("authentication", "secrets", "permission or command guard"):
            self.assertIn(piece, text)

    def test_a_rename_counts_both_paths(self):
        self.refusal(live_sized(("tests/test_a.py", 0, 40), ("src/a.py", 40, 0), ("src/b.py", 1, 0), ("src/c.py", 1, 0)),
                     refused_with("the diff changes 4 files, over the live lane's 3"))
        self.refusal(live_sized(("tests/helper.py", 0, 50), ("src/helper.py", 50, 0), ("src/fix.py", 31, 0)),
                     refused_with("the diff changes 81 lines outside tests, over the live lane's 80"))

    def test_paths_spelled_differently_are_distinct_files(self):
        self.refusal(live_sized(("a", 1, 0), (" a", 1, 0), ("b", 1, 0), ("tests/test_harm.py", 1, 0)),
                     refused_with("the diff changes 4 files, over the live lane's 3"))

    def test_a_test_the_diff_does_not_change_is_no_evidence(self):
        result, calls = run(args=ARGS, patch=dict(LIVE_PATCH, **live_sized(("src/fix.py", 5, 2))))
        self.assertEqual(result["stage"], "live-evidence")
        self.assertEqual(result["reason"], "live-evidence: the change carries no test shown failing before it and passing after it: "
                         "the test file tests/test_harm.py is not a path the diff changes; "
                         "deliver the fault in an ordinary delivery: rerun with lane standard and no cont")
        self.assertEqual(result["cont"]["live_fault"]["final"], "live-evidence")
        self.assertNotIn("live-review", labels(calls))
        self.assertNotIn("verify", labels(calls))
        impl = dict(LIVE_IMPL_REPLY, fault_test=with_ft(file="./tests/test_harm.py"))
        result, _ = run(args=ARGS, patch=LIVE_PATCH, replies={"live-impl": impl})
        self.assertEqual(result["stage"], "done")

    def test_a_path_listed_twice_counts_once(self):
        result, _ = run(args=ARGS, patch=dict(LIVE_PATCH, **live_sized(("src/a.py", 30, 0), ("src/a.py", 30, 0), ("tests/test_harm.py", 5, 0), ("src/b.py", 1, 0))))
        self.assertEqual(result["stage"], "done")
        self.refusal(live_sized(("src/a.py", 41, 0), ("src/a.py", 40, 0)),
                     refused_with("the diff changes 81 lines outside tests, over the live lane's 80"))

    def test_a_measurement_at_another_head_stops(self):
        result, calls = run(args=ARGS, patch=dict(LIVE_PATCH, **{"live-size": {"head": "e" * 40}}))
        self.assertEqual(result["stage"], "live-bound")
        self.assertIn(f"the diff was measured at {'e' * 40}, not the delivered commit {SHA}", result["reason"])
        self.assertIn("deliver the fault in an ordinary delivery: rerun with lane standard and no cont", result["reason"])
        self.assertNotIn("live-review", labels(calls))


CRIT = {"severity": "critical", "file": "src/fix.py", "summary": "the token is written to the log", "commit": SHA}
HARD = {"severity": "important", "file": "src/fix.py", "summary": "could also check the length", "commit": SHA}
MINOR = {"severity": "minor", "file": "src/fix.py", "summary": "rename the helper", "commit": SHA}
BEYOND = [{"file": "db/schema.sql", "summary": "add an index on the address table"}]
BEYOND_PATCH = dict(LIVE_PATCH, **{"live-impl": dict(LIVE_IMPL_REPLY, beyond=BEYOND)})
LIVE_RESUME = {"setup": {"head": SHA, "live_fault": DECLARED}}


def live_reply(*findings, met=True):
    return {"verdict": "findings" if findings else "pass", "findings": list(findings), "head": SHA,
            "acceptance": [{"id": "AC1", "met": met, "evidence": "tests/test_harm.py:3" if met else ""}]}


class LiveReviewTest(unittest.TestCase):
    """#1433: only a critical finding, or one naming an unmet criterion, blocks the live-fault lane; the rest are filed as follow-up issues."""

    def live(self, *findings, met=True, patch=LIVE_PATCH, replies=None):
        return run(args=ARGS, patch=patch, replies=dict({"live-review": live_reply(*findings, met=met)}, **(replies or {})))

    def test_a_critical_finding_blocks_the_merge(self):
        result, calls = self.live(CRIT)
        self.assertEqual(result["stage"], "live-review")
        self.assertIn("a critical finding blocks the live-fault lane", result["reason"])
        for label in ("pr", "merge", "verify", "follow-ups-1"):
            self.assertNotIn(label, labels(calls))
        self.assertEqual([c["label"] for c in calls if c["agentType"] == "implementer"], ["live-impl"])
        self.assertEqual(result["cont"]["live_fault"]["final"], "live-review")

    def test_other_findings_are_filed_as_follow_ups_and_the_delivery_lands(self):
        result, calls = self.live(HARD)
        self.assertEqual(result["stage"], "done")
        self.assertEqual(filings(calls), ["follow-ups-1"])
        self.assertLess(labels(calls).index("follow-ups-1"), labels(calls).index("verify"))
        self.assertEqual({k: result["follow_ups"][0][k] for k in ("issue", "file", "summary", "commit")},
                         {"issue": 911, "file": "src/fix.py", "summary": "could also check the length", "commit": SHA})
        self.assertTrue(items(calls, "follow-ups-1")[0]["body"].startswith(
            "Follow-up of #9: the live-fault lane's diff review raised this important finding, which does not block that delivery."))
        self.assertIn("The live-fault lane of this issue left the items below out of the fix", prompt(calls, "follow-ups-1"))

    def test_a_minor_finding_is_filed_too(self):
        result, calls = self.live(MINOR)
        self.assertEqual(result["stage"], "done")
        self.assertEqual(filings(calls), ["follow-ups-1"])

    def test_a_finding_naming_a_met_criterion_is_filed(self):
        result, calls = self.live(dict(HARD, ac="AC1"))
        self.assertEqual(result["stage"], "done")
        self.assertEqual(filings(calls), ["follow-ups-1"])

    def test_a_finding_naming_an_unmet_criterion_blocks(self):
        result, _ = self.live(dict(HARD, ac="AC1"), met=False)
        self.assertEqual(result["stage"], "live-review")

    def test_a_finding_naming_a_criterion_the_review_never_graded_blocks(self):
        reply = dict(live_reply(dict(HARD, ac="AC1")), acceptance=[])
        result, calls = run(args=ARGS, patch=LIVE_PATCH, replies={"live-review": reply})
        self.assertEqual(result["stage"], "live-review")
        self.assertEqual(filings(calls), [])

    def test_a_finding_naming_no_criterion_of_the_issue_is_filed(self):
        result, calls = self.live(dict(HARD, ac="AC9"))
        self.assertEqual(result["stage"], "done")
        self.assertEqual(filings(calls), ["follow-ups-1"])

    def test_an_ungraded_code_criterion_blocks(self):
        result, _ = self.live(met=False)
        self.assertEqual(result["stage"], "live-review")

    def test_a_mixed_review_files_the_rest_and_blocks(self):
        result, calls = self.live(CRIT, MINOR)
        self.assertEqual(result["stage"], "live-review")
        self.assertEqual(filings(calls), ["follow-ups-1"])
        self.assertEqual(len(items(calls, "follow-ups-1")), 1)
        self.assertIn("rename the helper", items(calls, "follow-ups-1")[0]["body"])
        self.assertEqual([{k: f[k] for k in ("issue", "file", "summary", "commit")} for f in result["cont"]["follow_ups"]],
                         [{"issue": 911, "file": "src/fix.py", "summary": "rename the helper", "commit": SHA}])
        self.assertEqual([f["severity"] for f in result["findings"]], ["critical"])

    def test_a_follow_up_left_unfiled_beside_a_critical_finding_is_filed_by_the_resume(self):
        stopped, calls = self.live(CRIT, MINOR, replies={"follow-ups-1": {"filed": []}})
        self.assertEqual(stopped["stage"], "live-review")
        self.assertEqual(stopped["cont"]["live_fault"]["final"], "live-review")
        self.assertEqual([f["summary"] for f in stopped["cont"]["follow_ups_pending"]], ["rename the helper"])
        result, calls = run(args=dict(ARGS, cont=stopped["cont"]), patch=LIVE_RESUME)
        self.assertEqual(result["stage"], "live-review")
        self.assertIn("already stopped at live-review", result["reason"])
        self.assertEqual(filings(calls), ["follow-ups-1"])
        self.assertEqual([f["summary"] for f in result["cont"]["follow_ups"]], ["rename the helper"])
        self.assertNotIn("follow_ups_pending", result["cont"])
        for label in ("live-impl", "live-size", "live-review", "verify"):
            self.assertNotIn(label, labels(calls))
        again, calls = run(args=dict(ARGS, cont=result["cont"]), patch=LIVE_RESUME)
        self.assertEqual(again["stage"], "live-review")
        self.assertEqual(filings(calls), [])

    def test_beyond_items_are_filed_as_follow_ups(self):
        result, calls = run(args=ARGS, patch=BEYOND_PATCH)
        self.assertEqual(result["stage"], "done")
        self.assertEqual(len(result["follow_ups"]), 1)
        body = items(calls, "follow-ups-1")[0]["body"]
        self.assertTrue(body.startswith("Follow-up of #9: the live-fault lane left this out of the fix, which stops the harm and nothing more."), body)
        self.assertIn("db/schema.sql", body)
        self.assertIn(SHA, body)

    def test_a_beyond_item_survives_a_stop_and_is_filed_once(self):
        stopped, calls = run(args=ARGS, patch=BEYOND_PATCH, replies={"live-size": None})
        self.assertEqual(stopped["stage"], "live-size")
        self.assertEqual(stopped["cont"]["done"][0]["beyond"], BEYOND)
        self.assertEqual(filings(calls), [])
        result, calls = run(args=dict(ARGS, cont=stopped["cont"]), patch=LIVE_RESUME)
        self.assertEqual(result["stage"], "done")
        self.assertEqual(filings(calls), ["follow-ups-1"])
        self.assertEqual(len(result["follow_ups"]), 1)
        cut, calls = run(args=dict(ARGS, cont=stopped["cont"]), patch=LIVE_RESUME, replies={"verify": None})
        self.assertEqual(cut["stage"], "verify")
        self.assertEqual(filings(calls), ["follow-ups-1"])
        self.assertNotIn("beyond", cut["cont"]["done"][0])
        self.assertEqual(len(cut["cont"]["follow_ups"]), 1)
        result, calls = run(args=dict(ARGS, cont=cut["cont"]), patch=LIVE_RESUME)
        self.assertEqual(filings(calls), [])

    def test_a_beyond_item_is_filed_when_no_review_runs(self):
        stopped, _ = run(args=ARGS, patch=BEYOND_PATCH, replies={"live-size": None})
        cont = dict(stopped["cont"], done=[dict(stopped["cont"]["done"][0], reviewed_head=SHA, reviewer="reviewer")])
        result, calls = run(args=dict(ARGS, cont=cont), patch=LIVE_RESUME)
        self.assertEqual(result["stage"], "done")
        self.assertNotIn("live-review", labels(calls))
        self.assertEqual(filings(calls), ["follow-ups-1"])

    def test_an_unconfirmed_follow_up_stops_before_verify(self):
        result, calls = self.live(HARD, replies={"follow-ups-1": {"filed": []}, "follow-ups-2": {"filed": []}})
        self.assertEqual(result["stage"], "final-review")
        self.assertNotIn("verify", labels(calls))
        self.assertTrue(result["cont"]["follow_ups_pending"][0]["lead"].startswith("Follow-up of #9: the live-fault lane's diff review"))
        self.assertEqual(items(calls, "follow-ups-2")[0]["body"], items(calls, "follow-ups-1")[0]["body"])


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
            (("fix-ci",), {"replies": {"checks-2": {"state": "passed", "passed": ["ci"], "head": SHA, "required": ["ci-tests"]}},
                           "patch": {"pr": {"green": red_read(RED)}, "fix-ci": ShipFixWaveTest.RERAN}}),
            (("fix-sync-1",), {"replies": {"sync-review-1": FINDING},
                               "patch": {"land-take": {"behind": True},
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

        for name in ("LAND_ACQUIRE", "LEASE_HOLD", "LOCK_RETURN", "RELEASE_AGAIN"):
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
        self.assertIn("final-scoped", labels(calls))
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
        self.assertIn("final-scoped", labels(calls))
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
        self.assertIn("final-scoped", labels(calls))
        self.assertEqual(again["cont"]["final_reviewed"], {"head": TIP, "branches": {"constructor": "e" * 40}})


# #1139: a marked issue stops at awaiting look; MARKED is the setup's look read, D a head a sync or a push moves the branch to.
MARKED = {"verdict": "marked", "covers": ["the settings page"], "acs": []}
D = "d" * 40
AWAIT_REASON = "issue 9 needs the owner's look before merge"
F, B = "f" * 40, "b" * 40
RESUME = {"setup": {"look": MARKED, "head": SHA}}
# #1246: the pull request head D is an integration merge on top of the verified head (verify is cached at SHA under RESUME).
LOOK_MERGED = dict(RESUME, **{"look-head": {"head": D}, "pr": {"head": D, "green": green_read(D)}})
# A passing look-verify reply at D whose summary differs from the cached verify's.
LOOK_OK = {"head": D, "clean": True, "merge_only": True, "ahead": False,
           "results": [{"id": "build", "status": "pass", "summary": "verified at the approved head"}]}
# The cont of the awaiting-look stop of a marked delivery (LookResumeTest pins it against the program), so SCENARIOS can resume it.
LOOK_CONT = {
    "setup": {"ok": True, "host": "h1", "slug": "owner/repo", "integration_branch": "dev", "default_branch": "main", "branch": "issue-9-x",
              "worktree_path": "/r/.wt/w-issue-9-x", "dirty": False, "unset_env": [], "merge_strategy": "merge", "delete_branch": True,
              "review": {"code": "cr", "plan": "pr"}, "review_state": {"code": "available", "plan": "available"},
              "knowledge": {"standards": ["/r/docs/standards"], "hints": ["/r/.hints"], "rejections": ["/r/.rej"]},
              "verification": [{"id": "build", "argv": ["make", "build"], "cwd": "."}],
              "look": {"verdict": "marked", "covers": ["the settings page"], "acs": []}, "holder": "h1/session-s1",
              "worktree": "/r/.wt/w-issue-9-x", "base_sha": SHA, "plan_dir": "/r/.git/worktrees/w/deliver-standard"},
    "lane": "standard",
    "plan": {"status": "planned", "plan_root": "/r/.git/worktrees/w/deliver-standard/plan.md",
             "acceptance": [{"id": "AC1", "text": "works", "kind": "code"}],
             "tasks": [{"n": 1, "title": "one", "file": "task-1.md", "risk": "security"}]},
    "plan_reviewed": True,
    "done": [{"n": 1, "commit": "c0ffee", "review_rounds": 0, "reviewer": "reviewer"}],
    "fix_waves": 0,
    "review_rounds": 1,
    "reviewed": {"head": "c0ffee"},
    "verified": {"head": SHA, "results": [{"id": "build", "status": "pass", "summary": "ok"}],
                 "contract": '[{"argv":["make","build"],"cwd":".","id":"build"}]'},
    "look": {"pr": 42, "head": SHA},
    "final_reviewed": {"head": "c0ffee"},
}
LIVE_RED = {"head": SHA, "clean": True, "results": [{"id": "build", "status": "fail", "summary": "boom"}]}
LIVE_RECORD = {"id": 5, "sprint_id": "0123456789abcdef", "issue": 9, "at": DECLARED["fault"]["at"]}
LIVE_CONT = dict(LOOK_CONT, lane="live", live_fault=LIVE_RECORD,
                 plan={"status": "planned", "plan_root": None, "acceptance": [{"id": "AC1", "text": "works", "kind": "code"}],
                       "tasks": [{"n": 1, "title": "live", "file": None, "risk": "standard"}]},
                 done=[{"n": 1, "commit": SHA, "review_rounds": 0, "reviewer": "reviewer", "reviewed_head": SHA, "fault_test": FT}])


def live(patch):
    """LIVE_PATCH with `patch` merged over it, one level deep."""
    merged_patch = copy.deepcopy(LIVE_PATCH)
    for key, value in patch.items():
        merged_patch[key] = dict(merged_patch.get(key, {}), **value) if isinstance(value, dict) else value
    return merged_patch


class LiveBindingTest(unittest.TestCase):
    """#1433: the live-fault lane verifies, opens and merges its one reviewed commit, or stops: no later step dispatches a second implementer or reviewer."""

    SCENARIOS = {
        "failed verification": {"args": ARGS, "patch": LIVE_PATCH, "replies": {"verify": LIVE_RED, "verify-rerun-1": LIVE_RED}},
        "another verify head": {"args": ARGS, "patch": live({"verify": {"head": "e" * 40}})},
        "behind": {"args": ARGS, "patch": live({"land-take": {"behind": True}})},
        "red check": {"args": ARGS, "patch": live({"pr": {"green": red_read(RED)}})},
        "early conflict": {"args": ARGS, "patch": live({"pr": {"probe": {"conflicted": True, "tree": "e" * 40, "files": ["a.py"]}}})},
        "owner changes": {"args": dict(ARGS, cont=LIVE_CONT, look={"answer": "changes", "words": "make the label bold"}),
                          "patch": {"setup": {"look": MARKED, "head": SHA, "live_fault": DECLARED}}},
        "approve a moved head": {"args": dict(ARGS, cont=LIVE_CONT, look={"answer": "approve", "head": D}),
                                 "patch": {"setup": {"look": MARKED, "head": SHA, "live_fault": DECLARED}, "look-head": {"head": D},
                                           "look-verify": LOOK_OK, "look-read": {"verdict": "approved"}}},
        "clean": {"args": ARGS, "patch": LIVE_PATCH},
    }

    def go(self, name):
        return run(**self.SCENARIOS[name])

    def test_a_failed_verification_stops_without_a_fix(self):
        result, calls = self.go("failed verification")
        self.assertEqual(result["stage"], "live-bound")
        self.assertIn("a fix would be a second implementer", result["reason"])
        self.assertFalse([l for l in labels(calls) if l.startswith(("verify-fix", "ws-check"))], labels(calls))
        self.assertEqual([c["label"] for c in calls if c["agentType"] == "implementer"], ["live-impl"])
        self.assertEqual(result["cont"]["live_fault"]["final"], "live-bound")

    def test_a_verification_at_another_head_stops(self):
        result, calls = self.go("another verify head")
        self.assertEqual(result["stage"], "live-bound")
        self.assertIn("not the delivered commit", result["reason"])
        self.assertNotIn("pr", result)
        self.assertNotIn("pr", labels(calls))

    def test_a_behind_pull_request_stops_without_a_sync(self):
        result, calls = self.go("behind")
        self.assertEqual(result["stage"], "live-bound")
        self.assertIn("behind", result["reason"])
        self.assertFalse([l for l in labels(calls) if l.startswith("sync-")], labels(calls))
        self.assertNotIn("merge", labels(calls))
        self.assertNotIn("lock_unreleased", result)

    def test_a_red_check_stops_without_a_ci_fix(self):
        result, calls = self.go("red check")
        self.assertEqual(result["stage"], "live-bound")
        self.assertNotIn("fix-ci", labels(calls))
        self.assertNotIn("fix-ci-review", labels(calls))
        self.assertNotIn("merge", labels(calls))
        self.assertNotIn("lock_unreleased", result)

    def test_a_conflict_found_before_the_lock_stops_without_a_resolution(self):
        result, calls = self.go("early conflict")
        self.assertEqual(result["stage"], "live-bound")
        self.assertFalse([l for l in labels(calls) if l.startswith("sync-")], labels(calls))
        self.assertNotIn("lock_unreleased", result)

    def test_an_owner_changes_answer_stops_without_a_look_fix(self):
        result, calls = self.go("owner changes")
        self.assertEqual(result["stage"], "live-bound")
        self.assertNotIn("look-fix", labels(calls))
        self.assertNotIn("renew-look-fix", labels(calls))

    def test_an_approve_of_a_head_that_is_not_the_delivered_commit_stops_before_any_verification(self):
        result, calls = self.go("approve a moved head")
        got = labels(calls)
        self.assertEqual(result["stage"], "live-bound")
        self.assertIn("not the delivered commit", result["reason"])
        for label in ("look-verify", "look-read", "look-pr", "pr", "merge"):
            self.assertNotIn(label, got)

    def test_the_pr_evidence_names_the_live_review(self):
        _, calls = self.go("clean")
        self.assertIn("live-fault lane review: one reviewer, no plan", prompt(calls, "pr"))
        self.assertNotIn("configured independent review", prompt(calls, "pr"))
        _, calls = run(args=ARGS)
        self.assertIn("configured independent review", prompt(calls, "pr"))

    def test_no_live_scenario_dispatches_a_second_implementer_or_reviewer(self):
        for name in self.SCENARIOS:
            with self.subTest(scenario=name):
                _, calls = self.go(name)
                implementers = [c["label"] for c in calls if c["agentType"] == "implementer"]
                reviewers = [c["label"] for c in calls if c["agentType"] in ("reviewer", "reviewer-lite")]
                self.assertIn(implementers, ([], ["live-impl"]))
                self.assertIn(reviewers, ([], ["live-review"]))


CLERK, PLANNER, IMPL, REV, LITE = "clerk", "planner", "implementer", "reviewer", "reviewer-lite"
EITHER = frozenset({REV, LITE})
EXPECTED = {stem: frozenset({kind}) if isinstance(kind, str) else kind for kind, stems in (
    (CLERK, ("setup", "acquire", "worktree", "renew-", "live-size", "live-green", "owner-answer", "plan-codex", "direct-codex", "final-codex", "diff-size", "amend", "follow-ups-",
             "verify", "verify-", "verify-rerun-", "ws-check-", "land-unlock", "land-push-", "land-take", "land-lock-", "land-relock-", "pr", "green-checks-", "checks-", "merge",
             "hold-draft", "hold", "close-out", "look-pr", "look-push", "look-head", "look-post", "look-read", "look-stale", "look-status", "look-verify",
             "look-checks-", "look-reverify", "look-carry", "look-carry-own", "look-carry-verify")),
    (PLANNER, ("plan", "plan-revise", "plan-rules-revise", "plan-branch-revise", "plan-task-revise")),
    (IMPL, ("direct-impl", "direct-fix", "live-impl", "impl-", "fix-", "fix-wave", "fix-wave-", "verify-fix-", "fix-ci", "sync-", "sync-resolve-",
            "fix-sync-", "look-fix", "fix-retest")),
    (REV, ("plan-review", "plan-rules-review", "direct-review-full", "final-", "final-integration", "final-scoped", "fix-wave-review",
           "fix-wave-review-", "verify-fix-review-", "fix-ci-review", "sync-review-", "fix-sync-review-", "look-fix-review", "live-review")),
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
    # #1433: the live-fault lane's one implementer and one reviewer.
    {"patch": LIVE_PATCH},
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
    # #1281: a plan with an evidence criterion drafts the hold before it posts.
    {"replies": {"plan": with_criteria(EVIDENCE)}, "patch": {"close-out": {"issue_state": "OPEN"}}},
    {"patch": {"hold": {"release": None}}},
    {"replies": {"checks-2": {"state": "passed", "passed": ["ci"], "head": FIX, "required": ["ci-tests"]}},
     "patch": {"pr": {"green": red_read(RED)}, "fix-ci": {"start_head": SHA, "commit": FIX}}},
    {"replies": {"sync-review-1": FINDING, "checks-2": {"state": "passed", "passed": ["ci"], "head": FIX, "required": ["ci-tests"]}},
     "patch": dict(CONFLICT, **{"land-take": {"behind": True}})},
    {"patch": {"land-take": {"lock": {"verdict": "land-contended", "lock_sha": "b" * 40}}}},
    # A head whose checks are still running is polled with no lock before the lease is asked for.
    {"patch": {"pr": {"green": green_read(state="pending", pending=["e2e"])}}},
    # A lease lost during the checks wait is waited for again in a land-relock step.
    {"replies": {"checks-2": {"state": "lost", "lock_sha": "e" * 40}, "checks-3": green_read(MERGE)},
     "patch": {"land-take": {"behind": True}, "sync-1": {"merge_commit": MERGE}}},
    {"args": DIRECT, "replies": {"direct-review": BAD}},
    {"args": DIRECT, "replies": {"direct-review": {"verdict": "pass", "findings": [], "escalate": True}}},
    # #1139: a marked issue stops at awaiting look; a head behind its base is synced and pushed first.
    {"patch": {"setup": {"look": MARKED}, "look-pr": {"behind": True}, "sync-1": {"merge_commit": D, "head": D}}},
    # #1373: a red check before the look stop gets the one fix and a push, the stop waits for green and re-verifies the fixed head.
    {"replies": {"look-checks-1": {"state": "failed", "head": SHA, "behind": False, "required": ["ci"], "failing": ["ci"], "details": "x"}},
     "patch": {"setup": {"look": MARKED}, "fix-ci": {"start_head": SHA, "commit": F}}},
    # #1139: the owner's approve and changes answers resume an awaiting-look cont.
    {"args": dict(ARGS, cont=LOOK_CONT, look={"answer": "approve", "head": SHA}), "patch": RESUME},
    {"args": dict(ARGS, cont=LOOK_CONT, look={"answer": "changes", "words": "make the label bold"}),
     "patch": dict(RESUME, **{"look-fix": {"start_head": SHA, "commit": F}, "verify": {"head": F}, "look-pr": {"head": F}})},
    # #1211: a head that moved after the approval asks look-approval status whether the approval is kept.
    {"args": dict(ARGS, cont=LOOK_CONT, look={"answer": "approve", "head": SHA}),
     "patch": dict(RESUME, **{"land-take": {"behind": True}, "sync-1": {"merge_commit": D, "head": D},
                              "checks-2": {"state": "passed", "head": D, "required": ["ci"], "passed": ["ci"]},
                              "look-status": {"verdict": "approved", "kept_from": SHA}})},
    # #1566: a landing resync that needs a new look verifies the new head and asks look-approval carry whether the approval carries.
    {"args": dict(ARGS, cont=LOOK_CONT, look={"answer": "approve", "head": SHA}),
     "patch": dict(RESUME, **{"land-take": {"behind": True}, "sync-1": {"merge_commit": D, "head": D},
                              "checks-2": {"state": "passed", "head": D, "required": ["ci"], "passed": ["ci"]},
                              "look-status": {"verdict": "needed", "kept_from": None},
                              "look-checks-1": {"state": "passed", "head": D, "behind": False, "required": ["ci"], "passed": ["ci"]}})},
    # #1211: a fix answer records the approval with the owner's words (the only look-post of a resume), fixes once and lands the fixed head.
    {"args": dict(ARGS, cont=LOOK_CONT, look={"answer": "fix", "head": SHA, "words": "make the label bold"}),
     "patch": dict(RESUME, **{"look-fix": {"start_head": SHA, "commit": F}, "verify": {"head": F},
                              "pr": {"head": F, "green": green_read(F)},
                              "look-status": {"verdict": "approved", "kept_from": SHA}})},
    # #1246: an approve answer for a PR head that merged the integration branch on the verified head verifies it first.
    {"args": dict(ARGS, cont=LOOK_CONT, look={"answer": "approve", "head": D}), "patch": LOOK_MERGED},
    # #1356: an approval that answers a plan criterion reads the earlier hold before the hold.
    {"args": dict(ARGS, cont=LOOK_CONT, look={"answer": "approve", "head": SHA}),
     "patch": dict(RESUME, setup={"look": dict(MARKED, acs=["AC1"]), "head": SHA})},
    # #1371: a resume carrying an untested commit records its tests before any push.
    {"args": dict(ARGS, cont=dict(LOOK_CONT, untested={"stage": "look-fix", "start_head": SHA, "head": F})),
     "patch": dict(RESUME, setup={"look": MARKED, "head": F}, verify={"head": F})},
    WS_SCENARIO,
    # #1370: a resume of a cont that holds the commit the last review read runs a scoped round.
    {"args": dict(ARGS, cont=dict({k: v for k, v in AMEND_CONT.items() if k != "partial"}, plan=PLAN, done=[{"n": 1, "commit": "c1"}],
                                  review_rounds=1, reviewed={"head": "abcd"})),
     "replies": {"final-scoped": {"verdict": "findings", "closed": [], "findings": [
         {"severity": "important", "file": "a.py", "summary": "could cache", "relation": "new", "commit": "a" * 40}]}}},
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

    ON_DEFAULT = {"setup", "worktree", "land-unlock", "land-push-", "land-take", "land-lock-", "land-relock-", "pr", "merge", "hold", "close-out",
                  "look-pr", "look-push"}

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

    def test_the_look_steps_stay_on_the_default_model(self):
        _, calls = run(args=dict(ARGS, clerk_model="haiku"),
                       patch={"setup": {"look": MARKED}, "look-pr": {"behind": True}, "sync-1": {"merge_commit": D, "head": D}})
        for label in ("look-pr", "look-push"):
            self.assertEqual([c["model"] for c in calls if c["label"] == label], ["sonnet"], label)

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
    PASSED = {"state": "passed", "passed": ["ci"], "head": FIX, "required": ["ci-tests"]}
    # One scenario per implementer prompt family that interpolates FOCUSED, with the labels it must reach.
    SCENARIOS = (
        ({"replies": {"review-1": TASK_FINDING}}, {"impl-1", "fix-1-1"}),
        ({"replies": {"final-1": FINDING}}, {"fix-wave"}),
        ({"replies": {"verify": VERIFY_RED}}, {"verify-fix-1"}),
        ({"replies": {"checks-2": PASSED},
          "patch": {"pr": {"green": red_read(RED)}, "fix-ci": {"start_head": SHA, "commit": FIX}}}, {"fix-ci"}),
        ({"replies": {"sync-review-1": FINDING, "checks-2": PASSED},
          "patch": dict(CONFLICT, **{"land-take": {"behind": True}})}, {"sync-1", "sync-resolve-1", "fix-sync-1"}),
        ({"args": DIRECT, "replies": {"direct-review": BAD}}, {"direct-impl", "direct-fix"}),
        # #1433: the live-fault lane's one implementer.
        ({"patch": LIVE_PATCH}, {"live-impl"}),
        # #1139: the owner's changes answer runs one fix round.
        ({"args": dict(ARGS, cont=LOOK_CONT, look={"answer": "changes", "words": "make the label bold"})}, {"look-fix"}),
    )
    FAMILIES = frozenset().union(*(want for _, want in SCENARIOS))

    def implementer_prompts(self, verification):
        """Every FOCUSED-carrying implementer prompt, by label, over SCENARIOS with this verification contract."""
        found = {}
        for scenario, expected in self.SCENARIOS:
            patched = dict(scenario, patch={**scenario.get("patch", {}), "setup": {**scenario.get("patch", {}).get("setup", {}), "verification": verification}})
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


def push_tests(text):
    """The push_tests payload a prompt carries, or None; #1371: a test reads the payload, never the sentence around it."""
    start = text.find('{"push_tests":')
    if start < 0:
        return None
    return json.JSONDecoder().raw_decode(text, start)[0]["push_tests"]


def program_const(name):
    """The single-quoted string literal of the program's one `const NAME = '...'` line."""
    found = [line for line in PROGRAM.read_text(encoding="utf-8").splitlines() if line.startswith(f"const {name} = '")]
    if len(found) != 1:
        raise AssertionError(f"not exactly one const {name} line: {found}")
    return found[0][len(f"const {name} = '"):found[0].rindex("'")]


PUSH_PAYLOAD = {"when": "committed", "scopes": ["touched", "callers", "guards"], "guards": [],
                "on_failure": "fix-and-rerun", "report": "tests"}
PASSED_AT_FIX = {"state": "passed", "passed": ["ci"], "head": FIX, "required": ["ci-tests"]}


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
        _, calls = run(patch={"pr": {"green": red_read({"state": "failed", "head": SHA})},
                              "fix-ci": {"start_head": SHA, "commit": "f" * 40}})
        self.assert_whole(prompt(calls, "fix-ci"), "the files you changed")

    def test_conflicted_sync_and_its_fix_run_whole_files(self):
        _, calls = run(replies={"sync-review-1": BAD},
                       patch={"land-take": {"behind": True},
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


class PushBoundFixTestsTest(unittest.TestCase):
    """#1371: a fix that leads to a push to an open pull request tests what it touched, its callers and the declared cheap guards; one that records no test command stops before the push, and a resume at its commit records the tests before any push."""

    PUSH_BOUND = (
        ("fix-ci", {"replies": {"green-checks-1": green_read(FIX)},
                    "patch": {"pr": {"green": red_read(RED)}, "fix-ci": {"start_head": SHA, "commit": FIX}}}),
        ("fix-sync-1", {"replies": {"sync-review-1": FINDING, "checks-2": PASSED_AT_FIX},
                        "patch": dict(CONFLICT, **{"land-take": {"behind": True}})}),
        ("look-fix", {"args": dict(ARGS, cont=LOOK_CONT, look={"answer": "changes", "words": "make the label bold"}),
                      "patch": dict(RESUME, **{"look-fix": {"start_head": SHA, "commit": F}, "verify": {"head": F},
                                               "look-pr": {"head": F}})}),
    )
    TESTED = ["python3 -m unittest tests/test_a.py: 4 passed"]

    @staticmethod
    def flagged(kwargs):
        patch = kwargs.get("patch", {})
        return dict(kwargs, patch={**patch, "setup": {**patch.get("setup", {}), "verification": PreCommitFocusTest.FLAGGED}})

    def test_every_push_bound_fix_prompt_carries_the_push_tests_payload(self):
        for label, kwargs in self.PUSH_BOUND:
            with self.subTest(label=label):
                _, calls = run(**kwargs)
                self.assertEqual(push_tests(prompt(calls, label)), PUSH_PAYLOAD)

    def test_the_flagged_ids_are_the_declared_cheap_guards(self):
        for label, kwargs in self.PUSH_BOUND:
            with self.subTest(label=label):
                _, calls = run(**self.flagged(kwargs))
                self.assertEqual(push_tests(prompt(calls, label)), dict(PUSH_PAYLOAD, guards=PreCommitFocusTest.UNFLAGGED))

    def test_only_the_push_bound_fixes_carry_it(self):
        scenarios = (
            ({"replies": {"review-1": BAD}}, ("impl-1", "fix-1-1")),
            ({"replies": {"final-1": FINDING}}, ("fix-wave",)),
            ({"replies": {"verify": VERIFY_RED}}, ("verify-fix-1",)),
            (self.PUSH_BOUND[1][1], ("sync-1", "sync-resolve-1")),
            ({"args": DIRECT, "replies": {"direct-review": BAD}}, ("direct-impl", "direct-fix")),
        )
        for kwargs, names in scenarios:
            _, calls = run(**kwargs)
            for label in names:
                with self.subTest(label=label):
                    self.assertIsNone(push_tests(prompt(calls, label)))

    def refused(self, stage, start, commit, forbidden, kwargs, label, fix, record):
        """Run kwargs with the fix reply made with this test record (None: no tests key) and assert the refusal."""
        reply = {"status": "done", "notes": "fixed", **fix, **({} if record is None else {"tests": record})}
        result, calls = run(**dict(kwargs, replies={**kwargs.get("replies", {}), label: reply}))
        self.assertEqual(result["stage"], stage)
        self.assertEqual(result["details"], program_const("UNTESTED"))
        self.assertIn(result["details"], result["reason"])
        self.assertEqual(result["cont"]["untested"], {"stage": stage, "start_head": start, "head": commit})
        for name in forbidden:
            self.assertNotIn(name, labels(calls))

    def test_a_committed_fix_with_no_test_recorded_stops_before_its_review_and_the_push(self):
        fixed = OwnRedOutsideLockTest.FIXED
        sites = (
            ("checks-fix", SHA, FIX, ("fix-ci-review", "land-push-1", "merge"), self.PUSH_BOUND[0][1], "fix-ci",
             {"start_head": SHA, "commit": FIX}),
            ("checks-fix", fixed["start_head"], fixed["commit"], ("fix-ci-review", "land-push-1", "merge"),
             {"replies": {"checks-2": PASSED_AT_FIX}, "patch": {"pr": OwnRedOutsideLockTest.PRE_RED}}, "fix-ci", dict(fixed)),
            ("sync-fix", MERGE, FIX, ("fix-sync-review-1", "land-push-2", "merge"), self.PUSH_BOUND[1][1], "fix-sync-1",
             {"start_head": MERGE, "commit": FIX}),
            ("look-fix", SHA, F, ("look-fix-review", "verify", "look-pr", "look-push", "merge"), self.PUSH_BOUND[2][1], "look-fix",
             {"start_head": SHA, "commit": F}),
        )
        for stage, start, commit, forbidden, kwargs, label, fix in sites:
            for record in ([], ["", "  "], None):
                with self.subTest(stage=stage, label=label, record=record):
                    self.refused(stage, start, commit, forbidden, kwargs, label, fix, record)

    def test_a_blocked_fix_that_committed_with_no_test_recorded_carries_untested_too(self):
        fixed = OwnRedOutsideLockTest.FIXED
        sites = (
            ("checks-fix", SHA, FIX, ("fix-ci-review", "land-push-1", "merge"), self.PUSH_BOUND[0][1], "fix-ci",
             {"start_head": SHA, "commit": FIX}),
            ("checks-fix", fixed["start_head"], fixed["commit"], ("fix-ci-review", "land-push-1", "merge"),
             {"replies": {"checks-2": PASSED_AT_FIX}, "patch": {"pr": OwnRedOutsideLockTest.PRE_RED}}, "fix-ci", dict(fixed)),
            ("sync-fix", MERGE, FIX, ("fix-sync-review-1", "land-push-2", "merge"), self.PUSH_BOUND[1][1], "fix-sync-1",
             {"start_head": MERGE, "commit": FIX}),
            ("look-fix", SHA, F, ("look-fix-review", "verify", "look-pr", "look-push", "merge"), self.PUSH_BOUND[2][1], "look-fix",
             {"start_head": SHA, "commit": F}),
        )
        for stage, start, commit, forbidden, kwargs, label, fix in sites:
            for record in ([], None):
                with self.subTest(stage=stage, label=label, record=record):
                    self.refused(stage, start, commit, forbidden, kwargs, label, dict(fix, status="blocked", notes="tests still red"), record)

    AT_FIX = {"setup": {"head": FIX}, "verify": {"head": FIX},
              "pr": {"head": FIX, "green": green_read(FIX)}}

    def test_a_resume_at_the_untested_commit_records_its_tests_before_any_push(self):
        stopped, _ = run(replies={"green-checks-1": green_read(FIX), "fix-ci-review": FINDING},
                         patch={"pr": {"green": red_read(RED)}, "fix-ci": {"start_head": SHA, "commit": FIX}})
        self.assertIn("cont", stopped)
        cont = dict(stopped["cont"], untested={"stage": "checks-fix", "start_head": SHA, "head": FIX})

        def resume(reply):
            return run(args=dict(ARGS, cont=cont), patch=dict(self.AT_FIX, **{"fix-retest": reply}))

        with self.subTest(case="records no test"):
            result, calls = resume({"start_head": FIX, "commit": FIX, "tests": []})
            self.assertEqual(result["stage"], "checks-fix")
            self.assertEqual(result["details"], program_const("UNTESTED"))
            self.assertEqual(result["cont"]["untested"], {"stage": "checks-fix", "start_head": SHA, "head": FIX})
            got = labels(calls)
            self.assertIn("fix-retest", got)
            self.assertFalse([l for l in got if l in ("pr", "merge") or l.startswith("land-push-")], got)
        with self.subTest(case="records its tests"):
            result, calls = resume({"start_head": FIX, "commit": FIX, "tests": self.TESTED})
            got = labels(calls)
            self.assertEqual(result["stage"], "done")
            self.assertLess(got.index("fix-retest"), got.index("pr"))
            self.assertEqual([c["agentType"] for c in calls if c["label"] == "fix-retest"], ["implementer"])
            text = prompt(calls, "fix-retest")
            self.assertEqual(push_tests(text), dict(PUSH_PAYLOAD, on_failure="report"))
            self.assertIn(f"git -C /r/.wt/w-issue-9-x diff {SHA}..{FIX}", text)
        with self.subTest(case="the retest committed"):
            result, calls = resume({"start_head": FIX, "commit": "e" * 40, "tests": self.TESTED})
            self.assertEqual(result["stage"], "checks-fix")
            self.assertNotIn("pr", labels(calls))

    READY_AT_F = dict(RESUME, setup={"look": MARKED, "head": F}, verify={"head": F})

    def test_a_ready_mode_resume_retests_before_it_returns_ready(self):
        cont = dict(LOOK_CONT, untested={"stage": "look-fix", "start_head": SHA, "head": F})

        def resume(reply):
            return run(args=dict(ARGS, mode="ready", cont=cont), patch=dict(self.READY_AT_F, **{"fix-retest": reply}))

        with self.subTest(case="records its tests"):
            result, calls = resume({"start_head": F, "commit": F, "tests": self.TESTED})
            self.assertEqual(result["stage"], "ready")
            self.assertIn("fix-retest", labels(calls))
            self.assertNotIn("untested", result["cont"])
        for case, reply in (("records no test", {"start_head": F, "commit": F, "tests": []}),
                            ("the retest committed", {"start_head": F, "commit": "e" * 40, "tests": self.TESTED})):
            with self.subTest(case=case):
                result, calls = resume(reply)
                self.assertEqual(result["stage"], "look-fix")
                self.assertEqual(result["cont"]["untested"], {"stage": "look-fix", "start_head": SHA, "head": F})

    def test_a_fix_report_with_no_start_head_keeps_the_head_the_program_asked_it_at(self):
        sites = (
            ("checks-fix", SHA, FIX, self.PUSH_BOUND[0][1], "fix-ci"),
            ("sync-fix", MERGE, FIX, self.PUSH_BOUND[1][1], "fix-sync-1"),
            ("look-fix", SHA, F, self.PUSH_BOUND[2][1], "look-fix"),
        )
        for stage, start, commit, kwargs, label in sites:
            for status in ("done", "blocked"):
                with self.subTest(stage=stage, status=status):
                    reply = {"status": status, "notes": "fixed", "commit": commit, "tests": []}
                    result, calls = run(**dict(kwargs, replies={**kwargs.get("replies", {}), label: reply}))
                    self.assertEqual(result["stage"], stage)
                    self.assertEqual(result["cont"]["untested"], {"stage": stage, "start_head": start, "head": commit})

    def test_a_fix_report_naming_another_start_head_is_compared_with_the_head_the_program_knew(self):
        """The reply's own start_head never decides whether the head moved: the known head stays the retest base."""
        sites = (
            ("checks-fix", SHA, FIX, self.PUSH_BOUND[0][1], "fix-ci"),
            ("sync-fix", MERGE, FIX, self.PUSH_BOUND[1][1], "fix-sync-1"),
            ("look-fix", SHA, F, self.PUSH_BOUND[2][1], "look-fix"),
        )
        for stage, start, commit, kwargs, label in sites:
            with self.subTest(stage=stage):
                reply = {"status": "done", "notes": "fixed", "start_head": commit, "commit": commit, "tests": []}
                result, calls = run(**dict(kwargs, replies={**kwargs.get("replies", {}), label: reply}))
                self.assertEqual(result["stage"], stage)
                self.assertEqual(result["cont"]["untested"], {"stage": stage, "start_head": start, "head": commit})
                self.assertFalse([l for l in labels(calls) if l in ("merge", "look-pr", "look-push") or l.startswith("land-push-")])

    def test_a_retest_that_leaves_the_worktree_changed_does_not_mark_the_head_shipped(self):
        cont = dict(LOOK_CONT, untested={"stage": "look-fix", "start_head": SHA, "head": F})
        done = {"status": "done", "notes": "ok", "start_head": F, "commit": F, "tests": self.TESTED}
        for case, kwargs in (("changed", {"patch": dict(self.READY_AT_F, **{"fix-retest": dict(done, clean=False)})}),
                             ("unsaid", {"patch": self.READY_AT_F, "replies": {"fix-retest": done}})):
            with self.subTest(case=case):
                result, calls = run(args=dict(ARGS, mode="ready", cont=cont), **kwargs)
                self.assertEqual(result["stage"], "look-fix")
                self.assertEqual(result["details"], program_const("RETEST_DIRTY"))
                self.assertEqual(result["cont"]["untested"], {"stage": "look-fix", "start_head": SHA, "head": F})
                self.assertFalse([l for l in labels(calls) if l in ("pr", "look-pr", "look-push", "merge")])

    def test_a_second_untested_look_fix_keeps_the_earliest_pending_start(self):
        cont = dict(LOOK_CONT, untested={"stage": "look-fix", "start_head": SHA, "head": F})
        result, calls = run(args=dict(ARGS, cont=cont, look={"answer": "changes", "words": "make the label bolder"}),
                            patch=dict(RESUME, setup={"look": MARKED, "head": F},
                                       **{"look-fix": {"start_head": F, "commit": D, "tests": []}}))
        self.assertEqual(result["stage"], "look-fix")
        self.assertEqual(result["cont"]["untested"], {"stage": "look-fix", "start_head": SHA, "head": D})

    def test_a_fix_that_commits_nothing_needs_no_test_record(self):
        result, calls = run(replies={"green-checks-1": green_read(SHA)},
                            patch={"pr": {"green": red_read(RED)}, "fix-ci": dict(ShipFixWaveTest.RERAN, tests=[])})
        names = labels(calls)
        self.assertEqual(result["stage"], "done")
        self.assertEqual(names[names.index("pr"):], ["pr", "fix-ci", "green-checks-1", "land-take", "merge", "hold", "close-out"])
        rebuttal = dict(self.PUSH_BOUND[1][1])
        rebuttal["patch"] = dict(rebuttal["patch"], **{"fix-sync-1": {"start_head": MERGE, "commit": MERGE,
                                                                       "notes": "the finding is wrong: a.py keeps both calls", "tests": []}})
        result, calls = run(**rebuttal)
        self.assertIn("fix-sync-review-1", labels(calls))
        self.assertNotEqual(result["stage"], "sync-fix")

    def test_a_red_check_fix_report_listing_its_tests_lands(self):
        tests = ["python3 -m unittest tests/test_a.py: 4 passed", "python3 -m unittest tests/test_uses_a.py: 2 passed",
                 "treefmt --fail-on-change (tools): passed"]
        kwargs = self.flagged(self.PUSH_BOUND[0][1])
        kwargs["patch"] = dict(kwargs["patch"], **{"fix-ci": {"start_head": SHA, "commit": FIX, "tests": tests}})
        result, calls = run(**kwargs)
        names = labels(calls)
        self.assertEqual(result["stage"], "done")
        self.assertEqual(names[names.index("pr"):],
                         ["pr", "fix-ci", "fix-ci-review", "land-push-1", "green-checks-1", "land-take", "merge", "hold", "close-out"])
        self.assertNotIn("fix-retest", names)


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
        self.assertEqual(names[names.index("pr"):], ["pr", "land-take", "merge", "hold", "close-out"])
        pr = prompt(calls, "pr")
        self.assertIn(self.CHECKS_CMD, pr)
        self.assertIn("gh api repos/owner/repo/rules/branches/dev", pr)
        self.assertNotIn("forge-claim land", pr)
        self.assertLess(pr.index(RENEW), pr.index(self.PUSH_CMD))
        schema = schema_of(calls, "pr")
        self.assertEqual(set(member(schema, "green")["properties"]),
                         {"state", "head", "behind", "required", "passed", "failing", "pending", "details"})
        self.assertIn({"type": "null"}, schema["properties"]["green"]["anyOf"])
        self.assertEqual(schema["required"], ["renew"])

    def test_each_folded_first_checks_failure_stops_as_before(self):
        rows = [
            ("lost", {"patch": {"pr": {"green": None}}}, "checks", ship_cont()),
            ("head", {"patch": {"pr": {"green": green_read("c" * 40)}}}, "head-moved", ship_cont()),
            ("pending", {"patch": {"pr": {"green": green_read(state="pending", pending=["e2e"])}},
                         "replies": {"green-checks-1": green_read(state="pending", pending=["e2e"]),
                                     "green-checks-2": green_read(state="pending", pending=["e2e"])}},
             "checks-pending", ship_cont()),
            ("red", {"patch": {"pr": {"green": red_read(RED)}, "fix-ci": {"start_head": SHA, "commit": FIX}},
                     "replies": {"green-checks-1": red_read(dict(RED, head=FIX))}},
             "checks", ship_cont(checks_fixes=1)),
            ("behind", {"patch": {"land-take": {"behind": True}}}, "done", None),
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
                    self.assertEqual(names.count("land-unlock"), 0)
                    self.assertNotIn("merge", names)
                    self.assertFalse([n for n in names if n.startswith("checks-") or n == "land-take"])
                elif name == "head":
                    self.assertNotIn("merge", names)
                    self.assertNotIn("land-take", names)
                elif name == "pending":
                    self.assertIn("green-checks-1", names)
                    self.assertIn("green-checks-2", names)
                    self.assertNotIn("green-checks-3", names)
                    self.assertNotIn("land-take", names)
                elif name == "red":
                    self.assertIn("fix-ci", names)
                    self.assertNotIn("merge", names)
                else:
                    self.assertEqual(names[names.index("pr"):],
                                     ["pr", "land-take", "sync-1", "checks-2", "merge", "hold", "close-out"])

    def test_a_green_read_is_ignored_when_the_take_refuses_and_when_the_pr_step_stops(self):
        result, calls = run(patch={"land-take": {"lock": {"verdict": "held_by", "by": "h2/b9"}}})
        self.assertEqual(result["stage"], "land-contended")
        self.assertEqual(result["cont"], ship_cont())
        self.assertFalse([n for n in labels(calls) if n.startswith("checks-")])
        result, _ = run(patch={"pr": {"head": "c" * 40}})
        self.assertEqual(result["stage"], "head-moved")
        self.assertEqual(result["cont"], ship_cont())

    def test_a_standalone_unmoved_round_still_renews(self):
        pending = {"land-take": {"behind": True}}
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

    MOVED_PATCH = {"land-take": {"behind": True}, "sync-1": {"merge_commit": MERGE}}
    MOVED_OK = {"checks-2": {"state": "passed", "passed": ["ci"], "head": MERGE}}
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
        acquire = f"forge-claim land acquire --repo owner/repo --branch dev --sha {MERGE} --lease\n"
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
            "lock-refused": ({"checks-2": {"lock": {"verdict": "land-contended", "lock_sha": other}}}, "land-contended",
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
                    self.assertEqual(result["lock"], "land-contended")
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
        result, calls = run(patch={"pr": {"green": red_read(RED)}, "fix-ci": {"start_head": SHA, "commit": FIX[:9]}},
                            replies={"land-push-1": {"head": FIX}, "green-checks-1": green_read(FIX)})
        self.assertEqual(result["stage"], "done")
        self.assertNotIn("cont", result)
        # The lock was not asked for while the fix was made, so its green read takes it, waiting.
        self.assertIn(f"--sha {FIX} --wait --lease\n", prompt(calls, "land-take"))
        self.assertNotIn(f"--sha {FIX[:9]} ", prompt(calls, "land-take"))
        self.assertNotIn(f"--sha {FIX[:9]}\n", prompt(calls, "land-take"))
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
        for name, cont, head, skipped in (("verified", ready["cont"], SHA, ("final-1", "final-scoped", "verify")),
                                          ("final reviewed", stopped["cont"], TIP, ("final-1", "final-scoped"))):
            plain, calls = run(args=dict(ARGS, cont=cont), patch={"setup": {"head": head}})
            with self.subTest(name, amend=False):
                self.assertEqual(plain["stage"], "done")
                for label in skipped:
                    self.assertNotIn(label, labels(calls))
            result, calls = run(args=dict(ARGS, cont=cont, amend=[AMEND_EDIT]), patch={"setup": {"head": head}})
            with self.subTest(name, amend=True):
                self.assertEqual(result["stage"], "done")
                # #1370: the amended plan is graded by the scoped round, never skipped and never run in full again.
                self.assertLess(labels(calls).index("amend"), labels(calls).index("final-scoped"))
                self.assertLess(labels(calls).index("final-scoped"), labels(calls).index("verify"))
                self.assertNotIn("final-1", labels(calls))

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
        self.assertIn("final-scoped", labels(calls))
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
                    self.assertIn("final-scoped", labels(calls))
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
# The exact #992 shape: no file key and no failing_input key at all. Raw, so named() gives it no subject.
KEYLESS = Raw({"verdict": "findings", "findings": [{"severity": "important", "summary": "Placeholder emitted to satisfy the schema"}]})
NO_REVIEW = ": the reply is no review ("
LOST_REVIEW = ": the second reply is no review either; the review is lost"


class StructuredReplyTest(unittest.TestCase):
    """#992: the structured reply goes alone and last; an unusable review reply reruns the step once and is never a finding."""

    FOUR = {"plan": dict(PLAN, tasks=tasks(4))}
    SYNC = {"land-take": {"behind": True}, "sync-1": ABORTED,
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

    def test_a_finding_with_no_file_key_and_no_failing_input_key_is_no_review(self):
        self.assertEqual(named({"review-1": KEYLESS})["review-1"]["findings"], [{"severity": "important", "summary": "Placeholder emitted to satisfy the schema"}])
        out = run_out(replies={"review-1": KEYLESS})
        names = labels(out["calls"])
        self.assertEqual(names[names.index("review-1"):names.index("review-1") + 3], ["review-1", "review-1-again", "renew-final-review"])
        self.assertNotIn("fix-1-1", names)
        self.assertEqual(out["result"]["stage"], "done")
        out = run_out(replies={"review-1": KEYLESS, "review-1-again": KEYLESS})
        result, names = out["result"], labels(out["calls"])
        self.assertEqual(names[-2:], ["review-1", "review-1-again"])
        self.assertEqual((result["stage"], result["lost_reviews"]), ("task-review", ["review-1"]))
        self.assertIsNone(result["review"])
        self.assertNotIn("dead_agents", result)
        self.assertIn("review-1" + LOST_REVIEW, out["logs"])

    def test_a_criterion_the_program_found_ungraded_names_its_subject(self):
        # The direct re-review restates the program's own finding: with its subject it is a usable review, with it stripped it is not.
        ungraded = {"verdict": "pass", "findings": [], "acceptance": [{"id": "AC1", "met": False, "evidence": ""}]}
        _, calls = run(args=DIRECT, replies={"direct-review": ungraded})
        sent = prompt(calls, "direct-rereview")
        made = json.loads(sent[sent.index("Findings: [") + len("Findings: "):sent.index("]", sent.index("Findings: [")) + 1])
        self.assertEqual((len(made), made[0]["failing_input"]), (1, "criterion AC1"))
        out = run_out(args=DIRECT, replies={"direct-review": ungraded, "direct-rereview": Raw({"verdict": "findings", "findings": made})})
        self.assertFalse([n for n in labels(out["calls"]) if n.endswith("-again")])
        bare = [{k: v for k, v in made[0].items() if k != "failing_input"}]
        out = run_out(args=DIRECT, replies={"direct-review": ungraded, "direct-rereview": Raw({"verdict": "findings", "findings": bare})})
        self.assertIn("direct-rereview-again", labels(out["calls"]))

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
            ("fix-ci-review", {"patch": {"pr": {"green": red_read(RED)}, "fix-ci": {"start_head": SHA, "commit": FIX}}}),
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
        schemas = (r"schema: (?:asked \? WS_REVIEW : FINDINGS|withChanged\(SCOPED \? withItems\(FINDINGS, SCOPED_ITEM\) : FINAL_FINDINGS\)|SYNC_REVIEW_SCHEMA\(followup\)|FINDINGS|PLAN_REVIEW"
                   r"|GRADED_FINDINGS|DIRECT_FINDINGS|FINAL_SCHEMA|SCOPED_FINDINGS|LIVE_FINDINGS) \}")
        sites = [m.end() for m in re.finditer(schemas, source)]
        self.assertEqual(len(sites), 18)
        # The options object of a review call closes the readReview() call, or one of its three named options does.
        tails = [source[end:source.index(")", end) + 1] for end in sites]
        self.assertEqual(sorted(set(tails)), sorted([")", ", { fileless })", ", { ruled: true })", ", { optional: true })", ", { once: true })"]))
        self.assertEqual((tails.count(", { fileless })"), tails.count(", { ruled: true })"), tails.count(", { optional: true })"), tails.count(", { once: true })")), (4, 2, 1, 1))
        self.assertEqual(len(re.findall(r"\breadReview\((?!\))", source)), 18)
        # No schema that carries findings is built anywhere else: each is one of the named ones above, FINDINGS spread into it.
        self.assertEqual(len(re.findall(r"\.\.\.(?:GRADED_)?FINDINGS,", source)), 7)
        self.assertEqual(source.count(", { fileless })"), 4)
        self.assertEqual(source.count("const fileless = !diffReviewed\n"), 1)
        self.assertEqual(source.count("{ ruled: true }"), 2)

    def test_an_implementer_reply_names_full_shas_or_none(self):
        red = {"head": SHA, "clean": True, "results": [{"id": "build", "status": "fail", "summary": "boom"}]}
        scenarios = (
            (("impl-1", "fix-1-1", "fix-wave"), {"replies": {"review-1": REAL, "final-1": REAL}}),
            (("direct-impl", "direct-fix"), {"args": DIRECT, "replies": {"direct-review": BAD}}),
            (("verify-fix-1",), {"replies": {"verify": red}}),
            (("fix-ci",), {"patch": {"pr": {"green": red_read(RED)}, "fix-ci": {"start_head": SHA, "commit": FIX}}}),
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


class OwnRedOutsideLockTest(unittest.TestCase):
    """#1001: a red check the branch itself caused is fixed outside the land lock. Under the lock, the fix step of a red poll at a
    head no sync has changed releases the lock before it edits, and the reviewed fix is read green before it takes it again; a pull request that
    already existed is read once before the lock is asked for, and a check that had already failed there is fixed with no lock."""

    RELEASE = f"forge-claim land release --repo owner/repo --branch dev --sha {SHA}\n"
    RERAN = {"start_head": SHA, "commit": SHA, "notes": "cache restore failed in setup; failed jobs rerun"}
    FIXED = {"start_head": SHA, "commit": FIX}
    GREEN = {"state": "passed", "passed": ["ci"], "head": FIX, "required": ["ci-tests"]}
    GREEN_READ = green_read(FIX)
    PRE_RED = {"own_red": {"head": SHA, "failing": ["shard-3"], "details": "https://ci/run/7"}}

    @staticmethod
    def shipped(out):
        names = labels(out["calls"])
        return names[names.index("pr"):]

    def under_lease(self, red, replies=None, **patch):
        """A red poll (checks-2) under the lease at an unsynced head: a policy refusal polls once more."""
        return run_out(replies={"merge": [MergeRefusedBehindTest.POLICY, MergeRefusedBehindTest.MERGED], "checks-2": red, **(replies or {})},
                       patch=patch)

    def test_a_red_first_poll_releases_the_lock_for_the_fix_and_ships_the_reviewed_head(self):
        out = self.under_lease(RED, **{"fix-ci": dict(self.FIXED, lock_released=True)})
        result, calls = out["result"], out["calls"]
        self.assertEqual(result["stage"], "done")
        # No step is added: the fix step releases the lock itself, and the fix head is read green before the lease is asked for.
        self.assertEqual(self.shipped(out), ["pr", "land-take", "merge", "checks-2", "fix-ci", "fix-ci-review", "land-push-3", "green-checks-1",
                                             "land-take", "merge", "hold", "close-out"])
        fix = prompt(calls, "fix-ci")
        self.assertIn(f"The landing lock of the branch dev is held for this pull request at {SHA}", fix)
        self.assertIn(f"release the lock before you edit any file: run alone and exactly: {self.RELEASE}", fix)
        self.assertIn("keep the lock: run no forge-claim command and return lock_released false", fix)
        self.assertLess(fix.index(self.RELEASE), fix.index("Find the cause in this branch's changes"))
        self.assertEqual(schema_of(calls, "fix-ci")["properties"]["lock_released"], {"type": "boolean"})
        self.assertNotIn("land acquire --repo", prompt(calls, "green-checks-1"))
        self.assertIn(f"forge-claim land acquire --repo owner/repo --branch dev --sha {FIX} --wait --lease\n", prompt(calls, "land-take"))
        merge = prompt(calls, "merge")
        self.assertIn(f"--sha {FIX} --lease\n", merge)
        self.assertIn(f"--match-head-commit {FIX}", merge)
        self.assertNotIn("land-unlock", labels(calls))
        self.assertIn(f"forge-claim land release --repo owner/repo --branch dev --sha {FIX}", prompt(calls, "hold"))
        self.assertIn("ci-tests failed at the head the lock was taken at; its fix is reviewed outside the land lock", out["logs"])

    def test_a_release_the_fix_step_did_not_report_is_made_before_the_review(self):
        out = self.under_lease(RED, **{"fix-ci": dict(self.FIXED, lock_released=False)})
        self.assertEqual(out["result"]["stage"], "done")
        self.assertEqual(self.shipped(out), ["pr", "land-take", "merge", "checks-2", "fix-ci", "land-unlock", "fix-ci-review", "land-push-3",
                                             "green-checks-1", "land-take", "merge", "hold", "close-out"])
        self.assertIn(self.RELEASE, prompt(out["calls"], "land-unlock"))

    def test_a_flaky_red_is_rerun_under_the_lock_as_before(self):
        out = self.under_lease(RED, {"checks-3": {"state": "passed", "passed": ["ci"], "head": SHA, "required": ["ci-tests"]}},
                               **{"fix-ci": self.RERAN})
        self.assertEqual(out["result"]["stage"], "done")
        self.assertEqual(self.shipped(out), ["pr", "land-take", "merge", "checks-2", "fix-ci", "checks-3", "merge", "hold", "close-out"])
        self.assertNotIn("forge-claim land acquire", prompt(out["calls"], "checks-3"))
        self.assertEqual([line for line in out["logs"] if "outside the land lock" in line], [])

    def test_a_rerun_that_released_the_lock_against_its_prompt_is_read_green_before_it_takes_it_again(self):
        out = self.under_lease(RED, **{"fix-ci": dict(self.RERAN, lock_released=True)})
        self.assertEqual(out["result"]["stage"], "done")
        self.assertEqual(self.shipped(out), ["pr", "land-take", "merge", "checks-2", "fix-ci", "green-checks-1", "land-take", "merge", "hold",
                                             "close-out"])
        self.assertIn(f"--sha {SHA} --wait --lease\n", prompt(out["calls"], "land-take"))

    def test_the_fix_outside_the_lock_happens_once_per_delivery(self):
        out = self.under_lease(RED, {"green-checks-1": red_read(dict(RED, head=FIX))}, **{"fix-ci": self.FIXED})
        self.assertEqual(out["result"]["stage"], "checks")
        self.assertEqual(self.shipped(out), ["pr", "land-take", "merge", "checks-2", "fix-ci", "fix-ci-review", "land-push-3", "green-checks-1",
                                             "land-unlock"])
        self.assertIn(f"--sha {SHA}\n", prompt(out["calls"], "land-unlock"))

    def test_a_fix_the_review_rejects_releases_the_verified_head_once_more_and_never_ships(self):
        out = self.under_lease(RED, {"fix-ci-review": FINDING}, **{"fix-ci": self.FIXED})
        self.assertEqual(out["result"]["stage"], "checks-fix-review")
        self.assertEqual(self.shipped(out), ["pr", "land-take", "merge", "checks-2", "fix-ci", "fix-ci-review", "land-unlock"])
        self.assertIn(self.RELEASE, prompt(out["calls"], "land-unlock"))

    def test_a_red_check_after_a_sync_under_the_lock_leaves_the_queue_before_its_fix(self):
        out = run_out(replies={"checks-2": RED, "land-take": [{"behind": True}, {}]}, patch={"fix-ci": self.FIXED})
        calls = out["calls"]
        self.assertEqual(out["result"]["stage"], "done")
        self.assertEqual(self.shipped(out), ["pr", "land-take", "sync-1", "checks-2", "land-unlock", "fix-ci", "fix-ci-review", "land-push-3",
                                             "green-checks-1", "land-take", "merge", "hold", "close-out"])
        self.assertIn("The land lock was released before this fix; run no forge-claim command.", prompt(calls, "fix-ci"))
        self.assertNotIn("forge-claim land", prompt(calls, "fix-ci"))
        self.assertNotIn("lock_released", schema_of(calls, "fix-ci")["properties"])
        self.assertNotIn("forge-claim land", prompt(calls, "green-checks-1"))
        self.assertIn(f"--sha {FIX} --wait --lease\n", prompt(calls, "land-take"))

    def test_the_pr_call_reads_a_reused_pull_request_once_before_the_lock(self):
        _, calls = run()
        text = prompt(calls, "pr")
        read = "gh pr view <the PR number> --repo owner/repo --json headRefOid,statusCheckRollup, one read, never a watch and never a wait"
        self.assertIn(read, text)
        for needle in ("only when an open PR already existed and was reused (a PR this step opened has no finished check, so skip this read)",
                       f"so the read counts only when its headRefOid is {SHA}",
                       "merge-base --is-ancestor origin/dev HEAD succeeds). When it is not, the head is behind its base and gets new checks "
                       "once it is synced; the failure counts all the same, because no lock is held yet",
                       "a cancelled check does not count), see whether origin/dev is an ancestor of HEAD",
                       "When the failure counts, wait for no check",
                       "and behind (true when the head is behind its base, else false), and green null",
                       "count only the newest run of each check name, the one with the latest startedAt, so a failed attempt whose re-run passed does not count",
                       "In every other case (another head, no failed check, "
                       "checks still running, none reported, or a read failed) return own_red null and go on."):
            self.assertIn(needle, text)
        self.assertNotIn("forge-claim land", text)
        self.assertLess(text.index("merge-tree --write-tree"), text.index(read))
        self.assertLess(text.index(read), text.index("for the checks of PR #<the PR number> at the head"))
        self.assertIn({"type": "null"}, schema_of(calls, "pr")["properties"]["own_red"]["anyOf"])
        self.assertEqual(member(schema_of(calls, "pr"), "own_red")["required"], ["head", "failing"])

    def test_a_check_already_red_before_the_lock_is_fixed_with_no_lock_and_the_fix_head_takes_it(self):
        out = run_out(replies={"green-checks-1": self.GREEN_READ}, patch={"pr": self.PRE_RED, "fix-ci": self.FIXED})
        result, calls = out["result"], out["calls"]
        self.assertEqual(result["stage"], "done")
        self.assertEqual(self.shipped(out), ["pr", "fix-ci", "fix-ci-review", "land-push-1", "green-checks-1", "land-take", "merge", "hold", "close-out"])
        fix = prompt(calls, "fix-ci")
        self.assertIn('failed at ' + SHA + ': ["shard-3"]. Log tail: https://ci/run/7.', fix)
        self.assertIn("The landing lock of the branch dev is not held and was not asked for yet: run no forge-claim command.", fix)
        self.assertNotIn("forge-claim land", fix)
        self.assertNotIn("forge-claim land", prompt(calls, "green-checks-1"))
        take = prompt(calls, "land-take")
        self.assertIn(f"take the cross-host landing lock of the branch dev for PR #42 at the head {FIX}; its head is green", take)
        self.assertIn(f"--sha {FIX} --wait --lease\n", take)
        # One hold, taken at the fix head and released there once, in the hold call: no step ever held the verified head.
        releases = [sha for c in calls for sha in re.findall(r"forge-claim land release --repo owner/repo --branch dev --sha ([0-9a-f]+)", c["prompt"])]
        self.assertEqual(releases, [FIX])
        self.assertIn("shard-3 had already failed at the head; fixing before the land lock is asked for", out["logs"])
    def test_a_rerun_before_the_lock_takes_the_lock_at_the_unchanged_head(self):
        out = run_out(replies={"green-checks-1": green_read(SHA)}, patch={"pr": self.PRE_RED, "fix-ci": self.RERAN})
        self.assertEqual(out["result"]["stage"], "done")
        self.assertEqual(self.shipped(out), ["pr", "fix-ci", "green-checks-1", "land-take", "merge", "hold", "close-out"])
        self.assertIn(f"--sha {SHA} --wait --lease\n", prompt(out["calls"], "land-take"))
    def test_a_red_rollup_at_another_head_diverts_nothing(self):
        """A head that was just pushed can still show the checks of the head before it: only a read at the pushed head counts."""
        base = [(c["label"], c["prompt"]) for c in run()[1]]
        for head in (MERGE, "", None):
            own = {"failing": ["shard-3"]} if head is None else {"head": head, "failing": ["shard-3"]}
            with self.subTest(head=head):
                result, calls = run(patch={"pr": {"own_red": own}})
                self.assertEqual([(c["label"], c["prompt"]) for c in calls], base)
                out = run_out(patch={"pr": {"own_red": own, "green": None}})
                self.assertEqual(out["result"]["stage"], "checks")
                self.assertEqual(self.shipped(out), ["pr"])

    STALE = {"state": "failed", "head": SHA, "failing": ["gate"], "stale": [77]}
    STALE_ASK = "This poll follows a rerun of failed jobs at this head."

    def test_a_stale_gate_after_a_rerun_before_the_lock_is_asked_in_the_poll_that_follows_it(self):
        """The poll after a rerun before the lock still asks the stale question, and no lock is asked for."""
        passed = green_read(SHA)
        stale = red_read(self.STALE)
        out = run_out(replies={"green-checks-1": stale, "green-checks-2": passed}, patch={"pr": self.PRE_RED, "fix-ci": self.RERAN})
        calls = out["calls"]
        self.assertEqual(out["result"]["stage"], "done")
        self.assertEqual(self.shipped(out), ["pr", "fix-ci", "green-checks-1", "green-checks-2", "land-take", "merge", "hold", "close-out"])
        first = prompt(calls, "green-checks-1")
        self.assertNotIn("forge-claim land", first)
        self.assertIn(self.STALE_ASK, first)
        self.assertIn("stale", schema_of(calls, "green-checks-1")["properties"])
        self.assertEqual(schema_of(calls, "green-checks-1")["required"], ["renew"])
        # Once: the poll after it carries no such instruction, and a check that is red there stops the delivery.
        self.assertNotIn(self.STALE_ASK, prompt(calls, "green-checks-2"))
        again = run_out(replies={"green-checks-1": stale, "green-checks-2": red_read(dict(RED, head=SHA))}, patch={"pr": self.PRE_RED, "fix-ci": self.RERAN})
        self.assertEqual(again["result"]["stage"], "checks")
        # A red answer that names no stale run is a second red poll, as ever.
        red = run_out(replies={"green-checks-1": red_read(dict(RED, head=SHA))}, patch={"pr": self.PRE_RED, "fix-ci": self.RERAN})
        self.assertEqual(red["result"]["stage"], "checks")
    def test_a_stale_gate_after_a_rerun_that_released_the_lock_is_asked_in_the_green_read(self):
        out = self.under_lease(RED, {"green-checks-1": red_read(self.STALE), "green-checks-2": green_read(SHA)},
                               **{"fix-ci": dict(self.RERAN, lock_released=True)})
        calls = out["calls"]
        self.assertEqual(out["result"]["stage"], "done")
        self.assertEqual(self.shipped(out), ["pr", "land-take", "merge", "checks-2", "fix-ci", "green-checks-1", "green-checks-2", "land-take",
                                             "merge", "hold", "close-out"])
        self.assertNotIn("forge-claim land", prompt(calls, "green-checks-1"))
        self.assertIn(self.STALE_ASK, prompt(calls, "green-checks-1"))
        self.assertIn("stale", schema_of(calls, "green-checks-1")["properties"])
        self.assertNotIn(self.STALE_ASK, prompt(calls, "green-checks-2"))

    def test_the_green_read_of_a_fix_commit_asks_no_stale_question(self):
        out = self.under_lease(RED, **{"fix-ci": self.FIXED})
        self.assertNotIn(self.STALE_ASK, prompt(out["calls"], "green-checks-1"))
        self.assertNotIn("stale", schema_of(out["calls"], "green-checks-1")["properties"])

    def test_a_red_read_after_a_conflict_resolved_before_the_lock_is_fixed_with_no_lock(self):
        """The accepted head is read and its red check fixed with no lock; only the fixed head takes it."""
        out = run_out(replies={"green-checks-1": red_read(dict(RED, head=MERGE)), "green-checks-2": green_read(FIX)},
                      patch={"pr": ResolveBeforeLockTest.EARLY, "sync-resolve-1": {"merge_commit": MERGE},
                             "fix-ci": {"start_head": MERGE, "commit": FIX}})
        calls = out["calls"]
        self.assertEqual(out["result"]["stage"], "done")
        self.assertEqual(self.shipped(out), ["pr", "sync-resolve-1", "sync-review-1", "land-push-1", "green-checks-1", "fix-ci", "fix-ci-review",
                                             "land-push-2", "green-checks-2", "land-take", "merge", "hold", "close-out"])
        self.assertIn("The landing lock of the branch dev is not held and was not asked for yet: run no forge-claim command.", prompt(calls, "fix-ci"))
        self.assertIn(f"--sha {FIX} --wait --lease\n", prompt(calls, "land-take"))
        releases = [sha for c in calls for sha in re.findall(r"forge-claim land release --repo owner/repo --branch dev --sha ([0-9a-f]+)", c["prompt"])]
        self.assertEqual(releases, [FIX])
    def test_a_reported_release_that_left_the_lock_held_is_taken_again_at_the_fix_head(self):
        for verdict in ("moved", "already_held", "acquired"):
            with self.subTest(verdict=verdict):
                taken = {"lock": {"verdict": verdict, "lock_sha": FIX}}
                out = self.under_lease(RED, {"land-take": [{}, taken]}, **{"fix-ci": dict(self.FIXED, lock_released=True)})
                self.assertEqual(out["result"]["stage"], "done")
                self.assertNotIn("land-unlock", labels(out["calls"]))
                self.assertIn(f"forge-claim land release --repo owner/repo --branch dev --sha {FIX}", prompt(out["calls"], "hold"))

    def test_a_rerun_whose_lock_was_lost_unreported_polls_again_before_it_merges(self):
        """The step kept quiet about a release and reran: the pre-merge acquire answers acquired, so the checks are read again first."""
        passed = {"state": "passed", "passed": ["ci"], "head": SHA, "required": ["ci-tests"]}
        retaken = {"merged": False, "lock": {"verdict": "acquired", "lock_sha": SHA}}
        out = self.under_lease(RED, {"checks-3": passed, "checks-4": passed,
                                     "merge": [MergeRefusedBehindTest.POLICY, retaken, {"merged": True, "merge_commit": SHA, "notes": "merged"}]},
                               **{"fix-ci": dict(self.RERAN, lock_released=False)})
        self.assertEqual(out["result"]["stage"], "done")
        self.assertEqual(self.shipped(out), ["pr", "land-take", "merge", "checks-2", "fix-ci", "checks-3", "merge", "checks-4", "merge",
                                             "hold", "close-out"])
        self.assertIn("merge-base --is-ancestor origin/dev HEAD", prompt(out["calls"], "checks-4"))

    def test_a_stop_before_the_first_take_runs_no_lock_command(self):
        for stage, replies, patch in (("checks-fix-review", {"fix-ci-review": FINDING}, {"fix-ci": self.FIXED}),
                                      ("checks-fix", {}, {"fix-ci": {"status": "blocked", "notes": "no"}})):
            with self.subTest(stage=stage):
                out = run_out(replies=replies, patch=dict({"pr": self.PRE_RED}, **patch))
                self.assertEqual(out["result"]["stage"], stage)
                self.assertEqual(out["result"]["cont"]["checks_fixes"], 1)
                names = self.shipped(out)
                self.assertNotIn("land-unlock", names)
                self.assertNotIn("merge", names)
                self.assertFalse([c for c in out["calls"] if "forge-claim land" in c["prompt"]])

    def test_an_own_red_reply_that_names_no_failed_check_is_the_old_flow(self):
        base = [(c["label"], c["prompt"]) for c in run()[1]]
        for own in ({"head": SHA, "failing": []}, None):
            with self.subTest(own=own):
                result, calls = run(patch={"pr": {"own_red": own}})
                self.assertEqual([(c["label"], c["prompt"]) for c in calls], base)
                self.assertEqual(result["stage"], "done")



class WaitByPlaceTest(unittest.TestCase):
    """#1018: the retries of a lock wait are spent only by a wait that made no progress. A wait that ended first in line, or at a
    better place than the wait before it, is made again for nothing, and a ceiling of six hours bounds the waits in all."""

    @staticmethod
    def ran_out(position, **lock):
        return {"lock": dict({"verdict": "land-contended", "lock_sha": "b" * 40, "waited_s": 3000, "waited_on": [7],
                              "position": position, "ahead": [] if position == 1 else [7]}, **lock)}

    def waits(self, first, *later):
        """The run whose land-take and land-lock steps answer these places; the step after the last takes the lock."""
        result, calls = run(replies={f"land-lock-{k}": self.ran_out(place) for k, place in enumerate(later, 1)},
                            patch={"land-take": self.ran_out(first)})
        return result["stage"], [label for label in labels(calls) if label.startswith("land-lock-")]

    def test_a_wait_that_ends_first_in_line_never_stops_land_contended(self):
        self.assertEqual(self.waits(2, 1, 1, 1, 1), ("done", [f"land-lock-{k}" for k in range(1, 6)]))

    def test_a_wait_whose_place_improved_spends_no_retry(self):
        self.assertEqual(self.waits(5, 4, 3, 2, 2), ("done", [f"land-lock-{k}" for k in range(1, 6)]))

    def test_a_wait_with_no_progress_still_stops_land_contended(self):
        for name, places in (("the same place", (2, 2, 2, 2)), ("a worse place", (2, 3, 4, 5)), ("no place read", (None,) * 4),
                             ("one better place, then none", (3, 2, 2, 2, 2))):
            with self.subTest(name):
                self.assertEqual(self.waits(*places), ("land-contended", [f"land-lock-{k}" for k in range(1, len(places))]))

    def test_the_waits_in_all_stop_at_the_ceiling(self):
        self.assertIn("const LAND_WAIT_MAX_S = 6 * 3600\nconst LAND_WAIT_CALL_S = 3000\n", PROGRAM.read_text(encoding="utf-8"))
        self.assertEqual(self.waits(*[1] * 12), ("land-contended", [f"land-lock-{k}" for k in range(1, 7)]))  # 7 waits of 50 minutes

    def test_a_reply_that_under_reports_its_wait_does_not_lift_the_ceiling(self):
        for waited in (0, 1, -5, None):
            with self.subTest(waited_s=waited):
                lock = {"lock": {"verdict": "land-contended", "position": 1, "waited_s": waited}}
                result, calls = run(replies={f"land-lock-{k}": lock for k in range(1, 12)}, patch={"land-take": lock})
                self.assertEqual(result["stage"], "land-contended")
                self.assertEqual(len([label for label in labels(calls) if label.startswith("land-lock-")]), 6)

    def test_a_take_after_a_resolution_judges_each_wait_by_its_own_reply_and_shares_the_ceiling(self):
        ship = ConflictedSyncOutsideLockTest().ship
        relocks = lambda out: [label for label in labels(out["calls"]) if label.startswith("land-lock-")]  # noqa: E731
        # The take's wait ended first in line; the waits after it end at place 3 and spend the retries.
        out = ship(replies={"land-take": [{"behind": True}, self.ran_out(1)], **{f"land-lock-{k}": self.ran_out(3) for k in range(1, 10)}})
        self.assertEqual((out["result"]["stage"], relocks(out)), ("land-contended", [f"land-lock-{k}" for k in range(1, 5)]))
        # First in line for ever: seven waits of 50 minutes in all, the take's included.
        out = ship(replies={"land-take": [{"behind": True}, self.ran_out(1)], **{f"land-lock-{k}": self.ran_out(1) for k in range(1, 10)}})
        self.assertEqual((out["result"]["stage"], relocks(out)), ("land-contended", [f"land-lock-{k}" for k in range(1, 7)]))

    def test_the_lock_replies_carry_the_place(self):
        _, calls = run(patch={"land-take": self.ran_out(1)})
        for label in ("land-take", "land-lock-1"):
            with self.subTest(label=label):
                self.assertIn("waited_s and waited_on from its output, and position and ahead when it prints them.", prompt(calls, label))
                lock = member(schema_of(calls, label), "lock")["properties"]
                self.assertEqual((lock["position"], lock["ahead"]),
                                 ({"anyOf": [{"type": "integer"}, {"type": "null"}]}, {"type": "array", "items": {"type": "integer"}}))


class BehindRedBeforeLockTest(unittest.TestCase):
    """#1018: a check that had failed at a head behind its base, read while another landing holds the lock, is not left for the
    sync under the lock: the branch is brought up to date before the lock is asked for, the checks of the new head are waited for
    with no lock, and a failure that survives goes to the fix wave before the lock, as any check that had failed at the head."""

    PRE = {"own_red": {"head": SHA, "failing": ["shard-3"], "details": "https://ci/run/7", "behind": True}}
    GREEN = green_read(MERGE)
    SYNCED = {"merge_commit": MERGE}
    UP_TO_DATE = "the branch was brought up to date with dev before the lock was asked for"

    @staticmethod
    def shipped(out):
        names = labels(out["calls"])
        return names[names.index("pr"):]

    @staticmethod
    def releases(calls):
        return [sha for c in calls for sha in re.findall(r"forge-claim land release --repo owner/repo --branch dev --sha ([0-9a-f]+)", c["prompt"])]

    def test_the_branch_is_synced_and_polled_before_the_lock_and_a_green_head_takes_it(self):
        out = run_out(replies={"green-checks-1": self.GREEN}, patch={"pr": self.PRE, "sync-1": self.SYNCED})
        result, calls = out["result"], out["calls"]
        self.assertEqual(result["stage"], "done")
        self.assertEqual(self.shipped(out), ["pr", "sync-1", "land-push-1", "green-checks-1", "land-take", "merge", "hold", "close-out"])
        # The usual sync step, a push behind its own renew and a poll behind its own renew; none runs a lock command.
        self.assertIn("git -C /r/.wt/w-issue-9-x merge origin/dev", prompt(calls, "sync-1"))
        self.assertIn("forge-claim renew", prompt(calls, "green-checks-1"))
        self.assertIn("git -C /r/.wt/w-issue-9-x push origin issue-9-x", prompt(calls, "land-push-1"))
        for label in ("sync-1", "land-push-1", "green-checks-1"):
            self.assertNotIn("forge-claim land", prompt(calls, label))
        take = prompt(calls, "land-take")
        self.assertIn(f"take the cross-host landing lock of the branch dev for PR #42 at the head {MERGE}; its head is green", take)
        self.assertIn(f"--sha {MERGE} --wait --lease\n", take)
        self.assertEqual(self.releases(calls), [MERGE])
        self.assertIn(f"--match-head-commit {MERGE}", prompt(calls, "merge"))
        self.assertIn("shard-3 failed at a head behind dev; bringing the branch up to date before the lock is asked for", out["logs"])
    def test_a_failure_that_survives_the_sync_is_fixed_before_the_lock(self):
        red = red_read({"state": "failed", "head": MERGE, "failing": ["shard-3"], "details": "shard-3 log"})
        out = run_out(replies={"green-checks-1": red, "green-checks-2": green_read(FIX)},
                      patch={"pr": self.PRE, "sync-1": self.SYNCED, "fix-ci": {"start_head": MERGE, "commit": FIX}})
        calls = out["calls"]
        self.assertEqual(out["result"]["stage"], "done")
        self.assertEqual(self.shipped(out), ["pr", "sync-1", "land-push-1", "green-checks-1", "fix-ci", "fix-ci-review", "land-push-2",
                                             "green-checks-2", "land-take", "merge", "hold", "close-out"])
        fix = prompt(calls, "fix-ci")
        self.assertIn('failed at ' + MERGE + ': ["shard-3"]. Log tail: shard-3 log.', fix)
        self.assertIn("The landing lock of the branch dev is not held and was not asked for yet: run no forge-claim command.", fix)
        self.assertIn(f"at the head {FIX}; its head is green", prompt(calls, "land-take"))
        self.assertEqual(self.releases(calls), [FIX])
        # One fix wave per delivery, as ever: a check still red at the fixed head stops it before any lock.
        again = run_out(replies={"green-checks-1": red, "green-checks-2": red_read(dict(RED, head=FIX))},
                        patch={"pr": self.PRE, "sync-1": self.SYNCED, "fix-ci": {"start_head": MERGE, "commit": FIX}})
        self.assertEqual(again["result"]["stage"], "checks")
        self.assertNotIn("land-take", labels(again["calls"]))
    def test_that_sync_spends_no_sync_of_the_landing(self):
        """Behind twice more under the lock: both syncs of the contention budget are still there."""
        m2, m3 = "e" * 40, "9" * 40
        out = run_out(replies={"green-checks-1": self.GREEN, "checks-3": {"state": "behind", "head": m2}, "checks-4": green_read(m3)},
                      patch={"pr": self.PRE, "land-take": {"behind": True}, "sync-1": self.SYNCED, "sync-2": {"merge_commit": m2},
                             "sync-3": {"merge_commit": m3}})
        self.assertEqual(out["result"]["stage"], "done")
        self.assertEqual([name for name in self.shipped(out) if name.startswith("sync-")], ["sync-1", "sync-2", "sync-3"])
    def test_a_red_check_under_the_lock_after_a_green_sync_before_it_is_still_the_branchs_own(self):
        """No sync has changed the head under the lock, so the fix step releases the lock before it edits (#1001)."""
        out = run_out(replies={"green-checks-1": self.GREEN, "merge": [MergeRefusedBehindTest.POLICY, MergeRefusedBehindTest.MERGED],
                               "checks-3": dict(RED, head=MERGE), "green-checks-2": green_read(FIX)},
                      patch={"pr": self.PRE, "sync-1": self.SYNCED, "fix-ci": {"start_head": MERGE, "commit": FIX, "lock_released": True}})
        self.assertEqual(out["result"]["stage"], "done")
        fix = prompt(out["calls"], "fix-ci")
        self.assertIn(f"The landing lock of the branch dev is held for this pull request at {MERGE}", fix)
        self.assertIn("lock_released", schema_of(out["calls"], "fix-ci")["properties"])
        self.assertNotIn("forge-claim land", prompt(out["calls"], "green-checks-2"))
        self.assertIn(f"--sha {FIX} --wait --lease\n", prompt(out["calls"], "land-take"))
    def test_a_red_read_that_is_still_behind_syncs_again_before_any_fix(self):
        behind = red_read({"state": "failed", "head": MERGE, "failing": ["shard-3"], "behind": True})
        out = run_out(replies={"green-checks-1": behind, "green-checks-2": self.GREEN},
                      patch={"pr": self.PRE, "sync-1": self.SYNCED, "sync-2": self.SYNCED})
        self.assertEqual(out["result"]["stage"], "done")
        self.assertEqual(self.shipped(out), ["pr", "sync-1", "land-push-1", "green-checks-1", "sync-2", "green-checks-2", "land-take",
                                             "merge", "hold", "close-out"])
        self.assertNotIn("fix-ci", self.shipped(out))
    def test_a_conflict_met_by_that_sync_is_resolved_outside_the_lock_and_said_so(self):
        out = run_out(replies={"green-checks-1": self.GREEN},
                      patch={"pr": self.PRE, "sync-1": ABORTED, "sync-resolve-1": {"merge_commit": MERGE}})
        self.assertEqual(out["result"]["stage"], "done")
        self.assertEqual(self.shipped(out), ["pr", "sync-1", "sync-resolve-1", "sync-review-1", "land-push-1", "green-checks-1", "land-take",
                                             "merge", "hold", "close-out"])
        self.assertIn(f"at the head {MERGE}; its head is green", prompt(out["calls"], "land-take"))
        self.assertEqual(self.releases(out["calls"]), [MERGE])
        # A stop inside that resolution holds nothing and releases nothing: no lock was asked for.
        stopped = run_out(patch={"pr": self.PRE, "sync-1": ABORTED, "sync-resolve-1": {"status": "blocked", "notes": "cannot resolve"}})
        self.assertEqual(stopped["result"]["stage"], "sync")
        self.assertEqual(self.shipped(stopped), ["pr", "sync-1", "sync-resolve-1"])
        self.assertEqual(self.releases(stopped["calls"]), [])
    def test_a_stop_before_the_lock_asks_for_no_lock_and_releases_nothing(self):
        stops = {"the sync is blocked": ({}, {"sync-1": {"status": "blocked", "notes": "dirty tree"}}, "sync"),
                 "the poll is lost": ({"green-checks-1": None}, {"sync-1": self.SYNCED}, "checks"),
                 "the poll names another head": ({"green-checks-1": green_read(FIX)}, {"sync-1": self.SYNCED}, "head-moved")}
        for name, (replies, patch, stage) in stops.items():
            with self.subTest(name):
                out = run_out(replies=replies, patch=dict({"pr": self.PRE}, **patch))
                self.assertEqual(out["result"]["stage"], stage)
                self.assertNotIn("land-unlock", self.shipped(out))
                self.assertEqual(self.releases(out["calls"]), [])
                self.assertNotIn("--wait --lease\n", "".join(c["prompt"] for c in out["calls"]))
    def test_a_head_that_is_not_behind_is_not_synced_early(self):
        own = dict(self.PRE["own_red"], behind=False)
        out = run_out(replies={"green-checks-1": green_read(FIX)},
                      patch={"pr": dict(self.PRE, own_red=own), "fix-ci": {"start_head": SHA, "commit": FIX}})
        self.assertEqual(self.shipped(out), ["pr", "fix-ci", "fix-ci-review", "land-push-1", "green-checks-1", "land-take", "merge", "hold", "close-out"])
        self.assertEqual(member(schema_of(out["calls"], "pr"), "own_red")["properties"]["behind"], {"type": "boolean"})


REVIEWERS = ("reviewer", "reviewer-lite")


class ReadOnlyReviewTest(unittest.TestCase):
    """#1019: every review step is told, in one shared sentence, never to move the worktree's HEAD."""

    def test_every_review_step_carries_the_sentence_once_and_no_other_step_does(self):
        seen = all_calls()
        kinds = {c["agentType"] for c in seen if READ_ONLY in c["prompt"]}
        self.assertEqual(kinds, set(REVIEWERS))
        for call in seen:
            with self.subTest(label=call["label"]):
                review = call["agentType"] in REVIEWERS
                self.assertEqual(call["prompt"].count(READ_ONLY), 1 if review else 0)
                if review and not call["label"].endswith("-again"):
                    self.assertTrue(call["prompt"].endswith(f"\n{READ_ONLY}\n{REPLY_ALONE}"))

    def test_a_rerun_review_carries_it_once(self):
        _, calls = run(replies={"review-1": INCOMPLETE})
        again = prompt(calls, "review-1-again")
        self.assertEqual(again.count(READ_ONLY), 1)
        self.assertLess(again.index(READ_ONLY), again.index("An earlier reply to this step was discarded"))

    def test_the_sentence_is_one_constant_shared_with_deliver_batch(self):
        mine = PROGRAM.read_text(encoding="utf-8")
        batch = PROGRAM.with_name("deliver-batch.js").read_text(encoding="utf-8")
        line = f"const READ_ONLY = '{READ_ONLY}'\n"
        self.assertEqual((mine.count(line), batch.count(line)), (1, 1))
        # One sentence: its only full stop ends it. It is added where every review passes, and nowhere else.
        self.assertEqual(READ_ONLY.index("."), len(READ_ONLY) - 1)
        for text in (mine, batch):
            self.assertEqual(text.count("${READ_ONLY}"), 1)
            self.assertEqual(text.count("Never check out, switch, reset or stash"), 1)
            self.assertIn(f"{'    ' if text is batch else '  '}const prompt = `${{asked}}${{BEFORE_PR ? `\\n${{REVIEW_TESTS}}` : ''}}\\n${{READ_ONLY}}`\n", text)
        for word in ("check out", "switch", "reset", "stash", "git show"):
            self.assertIn(word, READ_ONLY)
        # No second worktree is offered: every step works only in the worktree it is given.
        self.assertNotIn("temporary", READ_ONLY)
        self.assertNotIn("worktree add", READ_ONLY)


class ReattachTest(unittest.TestCase):
    """#1019: a worktree detached at its branch tip with a clean tree is put back on the branch; any other detached HEAD stops as before."""

    WT, BRANCH = "/r/.wt/w-issue-9-x", "issue-9-x"

    @staticmethod
    def reattach(branch, path):
        return (f"When HEAD in {path} is detached (git -C {path} symbolic-ref -q HEAD fails), put it back on {branch} first, only when "
                f"git -C {path} rev-parse HEAD and git -C {path} rev-parse refs/heads/{branch} print the same sha and "
                f"git -C {path} status --porcelain prints nothing: run git -C {path} switch {branch}, alone, and return reattached true. "
                "It is the one change this read may make; never reset, and leave any other detached HEAD as it is.")

    def cont(self):
        return ResumeTest().cont()

    def test_the_resumed_setup_reattaches_before_it_judges_the_branch(self):
        _, calls = run(args=dict(ARGS, cont=self.cont()))
        text = prompt(calls, "setup")
        sentence = self.reattach(self.BRANCH, self.WT)
        self.assertEqual(text.count(sentence), 1)
        self.assertLess(text.index(f"exists and is on branch {self.BRANCH}"), text.index(sentence))
        self.assertLess(text.index(sentence), text.index("If any fails, return ok=false with reason not-resumable and the evidence."))
        self.assertIn("Change nothing but that re-attach.", text)
        self.assertNotIn("checkout", sentence)

    def test_a_resume_reattached_at_the_branch_tip_goes_on(self):
        out = run_out(args=dict(ARGS, cont=self.cont()), patch={"setup": {"reattached": True}})
        self.assertEqual(out["result"]["stage"], "done")
        self.assertIn("impl-2", labels(out["calls"]))
        self.assertEqual(len([line for line in out["logs"] if line.startswith("setup: the worktree was on a detached HEAD at its branch tip")]), 1)
        # The fact belongs to this run alone: no cont carries it to the next.
        stopped = run_out(args=dict(ARGS, cont=self.cont()), patch={"setup": {"reattached": True}}, replies={"impl-2": None})["result"]
        self.assertNotIn("reattached", stopped["cont"]["setup"])

    def test_a_resume_with_no_reattach_logs_nothing(self):
        out = run_out(args=dict(ARGS, cont=self.cont()))
        self.assertFalse([line for line in out["logs"] if "detached" in line])

    def test_any_other_detached_head_stops_with_the_existing_reason(self):
        for evidence in ("HEAD is detached at c0ffee, not the tip of issue-9-x", "HEAD is detached at the tip and the tree is dirty: M a.py"):
            with self.subTest(evidence=evidence):
                result, calls = run(args=dict(ARGS, cont=self.cont()),
                                    replies={"setup": {"ok": False, "reason": "not-resumable", "details": evidence}})
                self.assertEqual((result["stage"], result["result"]["reason"]), ("setup", "not-resumable"))
                self.assertEqual(labels(calls), ["setup"])

    def test_the_fresh_setup_and_the_incomplete_claim_resume_reattach_through_the_existing_read(self):
        _, calls = run()
        fresh = prompt(calls, "setup")
        self.assertEqual(fresh.count(self.reattach("<branch>", "<worktree_path>")), 1)
        self.assertLess(fresh.index(self.reattach("<branch>", "<worktree_path>")), fresh.index("Return existing with local_branch"))
        cont = {"setup": {"ok": True, "branch": self.BRANCH, "worktree_path": self.WT, "holder": HOLDER}, "lane": "standard", "plan": None,
                "plan_reviewed": False, "done": [], "fix_waves": 0, "claim_incomplete": True}
        _, calls = run(args=dict(ARGS, cont=cont))
        self.assertEqual(prompt(calls, "setup").count(self.reattach(self.BRANCH, self.WT)), 1)

    def test_the_setup_schema_names_the_reattach(self):
        _, calls = run()
        self.assertEqual(schema_of(calls, "setup")["properties"]["reattached"], {"type": "boolean"})

    def test_the_sentence_is_the_same_in_deliver_batch(self):
        mine = PROGRAM.read_text(encoding="utf-8")
        batch = PROGRAM.with_name("deliver-batch.js").read_text(encoding="utf-8")
        (line,) = [l for l in mine.splitlines() if l.startswith("const REATTACH = ")]
        self.assertEqual(batch.count(line + "\n"), 1)
        self.assertIn("switch ${branch}", line)
        self.assertNotIn("checkout", line)


class RulesReviseSecondRoundTest(unittest.TestCase):
    """#1019: a rules re-review that leaves only findings on criteria the revise changed gets one more revise; never a third."""

    PINNED = dict(HUMAN, text="looks right on 2026-11-13")
    LOOSE = dict(HUMAN, text="looks right on the day of the check")
    ON_AC3 = PlanRuleMessagesTest.review(PlanRuleMessagesTest.finding("important", "AC3", "a pinned date", "R2"))
    OPEN = {"close-out": {"issue_state": "OPEN"}}
    # What the first rules revise is asked to fix: a finding on AC3.
    ASKED = PlanRuleMessagesTest.review(PlanRuleMessagesTest.finding("important", "AC3", "not checkable", "R2"))

    def go(self, revises, rereviews, asked=None, **more):
        plan = with_criteria(HUMAN)
        replies = {"plan": plan, "plan-revise": plan, "plan-review": PlanRulesTest.RULE_FINDING,
                   "plan-rules-revise": revises, "plan-rules-review": [asked or self.ASKED] + rereviews}
        return run_out(replies=replies, patch=self.OPEN, **more)

    @staticmethod
    def counts(calls):
        names = labels(calls)
        return names.count("plan-rules-revise"), names.count("plan-rules-review")

    def test_a_finding_on_a_criterion_the_revise_changed_gets_a_second_round(self):
        out = self.go([with_criteria(self.PINNED), with_criteria(self.LOOSE)], [self.ON_AC3, PASS_REPLY])
        result, calls = out["result"], out["calls"]
        self.assertEqual(self.counts(calls), (2, 3))
        self.assertNotEqual(result["stage"], "plan-review")
        self.assertIn("impl-1", labels(calls))
        second = [c["prompt"] for c in calls if c["label"] == "plan-rules-revise"][1]
        self.assertIn('"summary":"a pinned date"', second)
        self.assertNotIn('"summary":"not checkable"', second[second.index("Fix only these rule findings"):])
        self.assertEqual(len([line for line in out["logs"] if line.endswith("one more rules revise")]), 1)

    def test_a_third_revise_is_never_run(self):
        out = self.go([with_criteria(self.PINNED), with_criteria(self.LOOSE), with_criteria(self.PINNED)],
                      [self.ON_AC3, self.ON_AC3, PASS_REPLY])
        result, calls = out["result"], out["calls"]
        self.assertEqual(self.counts(calls), (2, 3))
        self.assertEqual(result["stage"], "plan-review")
        self.assertEqual([(r["rule"], r["ac"]) for r in result["rules"]], [("R2", "AC3")])
        # Both revises are spent: the plan is dropped, as after the second revise of a relaunch.
        self.assertIsNone(result["cont"]["plan"])
        self.assertNotIn("plan_findings", result["cont"])
        self.assertNotIn("impl-1", labels(calls))

    def test_any_other_finding_stops_after_one_revise_as_before(self):
        f = PlanRuleMessagesTest.finding
        cases = (
            ("a criterion the revise left alone", with_criteria(self.PINNED), [f("important", "AC1", "s", "R2")]),
            ("one of two on another criterion", with_criteria(self.PINNED), [f("important", "AC3", "s", "R2"), f("important", "AC1", "s", "R2")]),
            ("no criterion named", with_criteria(self.PINNED), [f("important", None, "s", "R2")]),
            ("the revise changed no criterion", with_criteria(HUMAN), [f("important", "AC3", "s", "R2")]),
            ("only the tasks changed", PlanRulesTest.REVISED, [f("important", "AC3", "s", "R2")]),
        )
        for name, revised, left in cases:
            with self.subTest(case=name):
                out = self.go([revised, with_criteria(self.LOOSE)], [PlanRuleMessagesTest.review(*left), PASS_REPLY])
                result, calls = out["result"], out["calls"]
                self.assertEqual(self.counts(calls), (1, 2))
                self.assertEqual(result["stage"], "plan-review")
                self.assertEqual(result["cont"]["plan_findings"]["rounds"], 1)
                self.assertEqual(result["cont"]["plan"], revised)
                self.assertFalse([line for line in out["logs"] if line.endswith("one more rules revise")])

    def test_a_reworded_criterion_the_revise_was_not_asked_about_is_not_changed(self):
        """A planner retypes criteria: AC1 reworded while AC3 is fixed, then a finding on AC1, stops after one revise."""
        reworded = dict(PLAN, acceptance=[dict(PLAN["acceptance"][0], text="it works"), self.PINNED])
        on_ac1 = PlanRuleMessagesTest.review(PlanRuleMessagesTest.finding("important", "AC1", "vague", "R2"))
        out = self.go([reworded, with_criteria(self.LOOSE)], [on_ac1, PASS_REPLY])
        result, calls = out["result"], out["calls"]
        self.assertEqual(self.counts(calls), (1, 2))
        self.assertEqual(result["stage"], "plan-review")
        self.assertEqual(result["cont"]["plan_findings"]["rounds"], 1)
        self.assertEqual([(r["rule"], r["ac"]) for r in result["rules"]], [("R2", "AC1")])
        # The same reply with the finding on AC3, which the revise was asked to fix and changed, gets the second round.
        out = self.go([reworded, with_criteria(self.LOOSE)], [self.ON_AC3, PASS_REPLY])
        self.assertEqual(self.counts(out["calls"]), (2, 3))

    def test_a_revise_asked_about_no_named_criterion_gets_no_second_round(self):
        out = self.go([with_criteria(self.PINNED), with_criteria(self.LOOSE)], [self.ON_AC3, PASS_REPLY], asked=PlanRulesTest.RULE_FINDING)
        self.assertEqual(self.counts(out["calls"]), (1, 2))
        self.assertEqual(out["result"]["stage"], "plan-review")

    def test_the_criterion_id_is_matched_without_case_or_spaces(self):
        left = PlanRuleMessagesTest.review(PlanRuleMessagesTest.finding("important", " ac3 ", "a pinned date", "R2"))
        out = self.go([with_criteria(self.PINNED), with_criteria(self.LOOSE)], [left, PASS_REPLY])
        self.assertEqual(self.counts(out["calls"]), (2, 3))

    def test_a_swap_between_classification_rules_keeps_its_owner_action_and_its_bound(self):
        f = PlanRuleMessagesTest.finding
        plan = with_criteria(HUMAN)
        r3 = PlanRuleMessagesTest.review(f("important", "AC3", "not a human check", "R3"))
        swap = PlanRuleMessagesTest.review(f("important", "AC3", "s", "R1"))
        result, calls = run(replies={"plan": plan, "plan-revise": plan, "plan-review": PlanRulesTest.RULE_FINDING,
                                     "plan-rules-revise": [with_criteria(self.PINNED), with_criteria(self.LOOSE)],
                                     "plan-rules-review": [r3, swap, PASS_REPLY]})
        self.assertEqual(self.counts(calls), (1, 2))
        self.assertEqual(result["stage"], "plan-review")
        self.assertEqual(result["conflict"], {"ac": "AC3", "rules": ["R3", "R1"], "revises_left": 1})
        self.assertEqual(result["cont"]["plan_findings"]["rounds"], 1)

    def test_a_silent_second_re_review_stops_with_the_findings_the_second_revise_was_given(self):
        out = self.go([with_criteria(self.PINNED), with_criteria(self.LOOSE)], [self.ON_AC3, None])
        result, calls = out["result"], out["calls"]
        self.assertEqual(self.counts(calls), (2, 3))
        self.assertEqual(result["stage"], "plan-review")
        self.assertEqual([r["summary"] for r in result["rules"]], ["a pinned date"])
        self.assertIsNone(result["cont"]["plan"])

    def test_a_relaunch_that_already_spent_one_revise_runs_only_the_one_left(self):
        first = self.go([with_criteria(HUMAN)], [PlanRuleMessagesTest.review(PlanRuleMessagesTest.finding("important", "AC3", "s", "R2"))])["result"]
        self.assertEqual(first["cont"]["plan_findings"]["rounds"], 1)
        result, calls = run(args=dict(ARGS, cont=first["cont"]),
                            replies={"plan-rules-revise": [with_criteria(self.PINNED), with_criteria(self.LOOSE)],
                                     "plan-rules-review": [self.ON_AC3, PASS_REPLY]})
        self.assertEqual(self.counts(calls), (1, 1))
        self.assertEqual(result["stage"], "plan-review")
        self.assertIsNone(result["cont"]["plan"])


class LookStopTest(unittest.TestCase):
    """#1139: a delivery of an issue marked for the owner's look stops at awaiting look, after verify, push and the pull request."""

    PICS = [{"kind": "before", "path": "/tmp/b.png"}, {"kind": "after", "path": "/tmp/a.png"}]

    def test_a_marked_issue_stops_at_awaiting_look_after_verify_push_and_pr(self):
        result, calls = run(patch={"setup": {"look": MARKED}})
        got = labels(calls)
        self.assertEqual(result["stage"], "awaiting-look")
        self.assertEqual((result["issue"], result["pr"], result["head"], result["reason"], result["covers"]),
                         (9, 42, SHA, AWAIT_REASON, ["the settings page"]))
        self.assertEqual(result["cont"]["look"], {"pr": 42, "head": SHA})
        self.assertEqual(result["cont"]["verified"]["head"], SHA)
        self.assertEqual(got[-1], "look-checks-1")
        self.assertLess(got.index("verify"), got.index("look-pr"))
        self.assertLess(got.index("look-pr"), got.index("look-checks-1"))
        for label in ("pr", "merge", "hold", "close-out", "land-unlock"):
            self.assertNotIn(label, got)
        self.assertEqual([l for l in got if l.startswith(("land-", "checks-"))], [])
        text = prompt(calls, "look-pr")
        self.assertIn("git -C /r/.wt/w-issue-9-x push origin issue-9-x", text)
        self.assertIn("If an open PR with head issue-9-x already exists", text)
        for call in calls:
            self.assertNotIn("forge-claim land", call["prompt"], call["label"])

    def test_the_direct_lane_stops_at_awaiting_look_too(self):
        result, calls = run(args=DIRECT, patch={"setup": {"look": MARKED}})
        got = labels(calls)
        self.assertEqual(result["stage"], "awaiting-look")
        self.assertLess(got.index("direct-review"), got.index("look-pr"))
        self.assertNotIn("merge", got)
        self.assertEqual([l for l in got if l.startswith("land-")], [])

    def test_a_marked_branch_behind_its_base_is_synced_and_pushed_before_the_stop(self):
        result, calls = run(patch={"setup": {"look": MARKED}, "look-pr": {"behind": True}, "sync-1": {"merge_commit": D, "head": D}})
        got = labels(calls)
        self.assertEqual(got[got.index("look-pr") + 1:], ["sync-1", "look-push", "look-checks-1", "look-reverify", "look-checks-2"])
        self.assertIn("at the head " + D, prompt(calls, "look-push"))
        self.assertEqual(result["stage"], "awaiting-look")
        self.assertEqual(result["head"], D)
        self.assertEqual(result["cont"]["look"]["head"], D)

    def test_a_probe_conflict_is_resolved_and_reviewed_before_the_stop(self):
        result, calls = run(patch={"setup": {"look": MARKED},
                                   "look-pr": {"probe": {"conflicted": True, "tree": "e" * 40, "files": ["a.py"]}},
                                   "sync-resolve-1": {"merge_commit": D, "head": D}})
        got = labels(calls)
        self.assertEqual([l for l in got if l in ("sync-resolve-1", "sync-review-1", "look-push")],
                         ["sync-resolve-1", "sync-review-1", "look-push"])
        self.assertNotIn("sync-1", got)
        self.assertEqual([l for l in got if l.startswith("land-")], [])
        self.assertEqual(result["stage"], "awaiting-look")
        self.assertEqual(result["head"], D)

    def test_a_look_marker_that_was_not_read_stops_after_verify(self):
        for args in (ARGS, dict(ARGS, mode="ready")):
            with self.subTest(mode=args.get("mode", "ship")):
                result, calls = run(args=args, patch={"setup": {"look": {"verdict": "error", "detail": "x"}}})
                got = labels(calls)
                self.assertEqual(result["stage"], "look")
                self.assertIn("cont", result)
                self.assertNotIn("look-pr", got)
                self.assertNotIn("pr", got)
                self.assertIn("verify", got)

    def test_ready_mode_reports_the_look_verdict(self):
        ready, _ = run(args=dict(ARGS, mode="ready"), patch={"setup": {"look": MARKED}})
        self.assertEqual(ready["look"], {"verdict": "marked", "covers": ["the settings page"]})
        plain, _ = run(args=dict(ARGS, mode="ready"))
        self.assertEqual(plain["look"], {"verdict": "unmarked", "covers": []})

    def test_the_pictures_verify_wrote_ride_on_the_stop(self):
        result, _ = run(patch={"setup": {"look": MARKED}, "verify": {"pictures": self.PICS}})
        self.assertEqual(result["pictures"], self.PICS)
        self.assertEqual(result["cont"]["verified"]["pictures"], self.PICS)
        bare, _ = run(patch={"setup": {"look": MARKED}})
        self.assertNotIn("pictures", bare)
        self.assertNotIn("pictures", bare["cont"]["verified"])

    def test_an_unmarked_issue_ships_with_no_look_step(self):
        result, calls = run()
        got = labels(calls)
        self.assertEqual(result["stage"], "done")
        self.assertEqual([l for l in got if l.startswith("look-")], [])
        self.assertEqual(got[got.index("pr"):], ["pr", "land-take", "merge", "hold", "close-out"])
        direct, direct_calls = run(args=DIRECT)
        self.assertEqual(direct["stage"], "done")
        self.assertEqual([l for l in labels(direct_calls) if l.startswith("look-")], [])


class LookChecksTest(unittest.TestCase):
    """#1373: a marked delivery stops at awaiting look only once the checks of the head the owner will see are green."""

    PENDING = {"state": "pending", "head": SHA, "behind": False, "pending": ["ci"]}
    GREEN = {"state": "passed", "head": SHA, "behind": False, "required": ["ci"], "passed": ["ci"]}
    RED = {"state": "failed", "head": SHA, "behind": False, "required": ["ci"], "failing": ["ci"],
           "details": "FAIL test_cache: host-installed state"}
    FIXED = {"fix-ci": {"start_head": SHA, "commit": F}}
    MARK = {"setup": {"look": MARKED}}

    def go(self, replies=None, patch=None, **kw):
        return run(replies=replies, patch=dict(self.MARK, **(patch or {})), **kw)

    @staticmethod
    def after_pr(calls):
        got = labels(calls)
        return got[got.index("look-pr") + 1:]

    def test_a_marked_delivery_stops_only_after_its_pending_checks_turn_green(self):
        result, calls = self.go(replies={"look-checks-1": self.PENDING, "look-checks-2": self.GREEN})
        got = labels(calls)
        self.assertEqual(result["stage"], "awaiting-look")
        self.assertEqual(result["head"], SHA)
        self.assertEqual(result["cont"]["look"], {"pr": 42, "head": SHA})
        self.assertEqual(self.after_pr(calls), ["look-checks-1", "look-checks-2"])
        self.assertEqual([l for l in got if l.startswith(("land-", "checks-"))], [])
        self.assertNotIn("merge", got)
        for call in calls:
            self.assertNotIn("forge-claim land", call["prompt"], call["label"])
        text = prompt(calls, "look-checks-1")
        self.assertIn("forge-claim renew", text)
        self.assertIn("look at the head " + SHA, text)
        w = text.index("gh pr checks 42 --repo owner/repo --watch")
        r = text.index("gh pr view 42 --repo owner/repo --json headRefOid,statusCheckRollup", w)
        text.index("git -C /r/.wt/w-issue-9-x merge-base --is-ancestor origin/dev", r)
        self.assertNotIn("ahead of origin/issue-9-x", text)

    def test_a_passed_reply_without_a_required_list_is_never_green(self):
        # #1373 C1: an omitted list hides a required check that has not reported yet, so it is read as pending, never as proof.
        unlisted = {"state": "passed", "head": SHA, "behind": False, "passed": ["lint"]}
        result, calls = self.go(replies={"look-checks-1": unlisted, "look-checks-2": self.GREEN})
        self.assertEqual(result["stage"], "awaiting-look")
        self.assertEqual(self.after_pr(calls), ["look-checks-1", "look-checks-2"])
        with self.subTest(reply="never listed"):
            result, calls = self.go(replies={f"look-checks-{k}": unlisted for k in (1, 2, 3)})
            self.assertEqual(result["stage"], "checks-pending")
            self.assertNotIn("look-checks-4", labels(calls))
        with self.subTest(reply="an explicit empty list"):
            result, calls = self.go(replies={"look-checks-1": dict(unlisted, required=[])})
            self.assertEqual(self.after_pr(calls), ["look-checks-1"])
            self.assertEqual(result["stage"], "awaiting-look")

    def test_the_poll_reads_the_required_checks_of_both_sources_and_matches_their_app(self):
        # #1373 C2, C3: the rulesets and classic protection are both read, and a required check is judged by the app its entry names.
        text = prompt(self.go()[1], "look-checks-1")
        self.assertIn("gh api repos/owner/repo/rules/branches/dev", text)
        self.assertIn("gh api repos/owner/repo/branches/dev/protection", text)
        self.assertIn("integration_id", text)
        self.assertIn("app_id", text)
        self.assertNotIn("whenever that reply lists no required status checks", text)

    def test_the_poll_reads_the_app_of_each_run_from_a_source_that_carries_it(self):
        # #1373 C2: the pull request rollup has no app field, so the app of a run is read from the check runs of the head the rollup names.
        text = prompt(self.go()[1], "look-checks-1")
        view = text.index("gh pr view 42 --repo owner/repo --json headRefOid,statusCheckRollup")
        runs = text.index("gh api repos/owner/repo/commits/<its headRefOid>/check-runs --paginate", view)
        self.assertIn("app.id", text[runs:])
        self.assertLess(runs, text.index("Classify", runs))
        self.assertNotIn("that one read alone", text)

    def test_the_poll_has_one_watch_and_one_deadline(self):
        # #1373 I1: a stuck check must end a poll so the three-wait counter advances.
        text = prompt(self.go()[1], "look-checks-1")
        self.assertEqual(text.count("--watch"), 1)
        self.assertNotIn("run it again", text)

    def test_a_forge_that_moved_during_the_verification_is_read_again_before_the_stop(self):
        # #1373 I2: after the look-reverify call the stop waits on the forge once more: its checks and its head.
        moved = {"sync-1": {"merge_commit": D, "head": D}}
        base = {"look-checks-1": dict(self.GREEN, behind=True)}
        result, calls = self.go(replies=dict(base, **{"look-checks-3": dict(self.PENDING, head=D)}), patch=moved)
        self.assertEqual(self.after_pr(calls), ["look-checks-1", "sync-1", "look-push", "look-checks-2", "look-reverify", "look-checks-3", "look-checks-4"])
        self.assertEqual((result["stage"], result["head"]), ("awaiting-look", D))
        with self.subTest(read="head moved"):
            result, calls = self.go(replies=dict(base, **{"look-checks-3": dict(self.GREEN, head=B)}), patch=moved)
            self.assertEqual((result["stage"], result["head"]), ("head-moved", B))
            self.assertNotIn("look", result["cont"])
        with self.subTest(read="red"):
            red = dict(self.RED, head=D)
            result, calls = self.go(replies=dict(base, **{"look-checks-3": red, "look-checks-4": dict(self.GREEN, head=F)}),
                                    patch=dict(moved, **{"fix-ci": {"start_head": D, "commit": F}}))
            self.assertEqual(self.after_pr(calls)[-7:], ["look-checks-3", "fix-ci", "fix-ci-review", "look-push", "look-checks-4", "look-reverify", "look-checks-5"])
    def test_a_head_with_no_check_reported_yet_is_polled_again(self):
        result, calls = self.go(replies={"look-checks-1": {"state": "passed", "head": SHA, "behind": False, "passed": []},
                                         "look-checks-2": self.GREEN})
        self.assertEqual(result["stage"], "awaiting-look")
        self.assertEqual(self.after_pr(calls), ["look-checks-1", "look-checks-2"])

    def test_a_passed_reply_missing_a_required_check_is_polled_again(self):
        partial = {"state": "passed", "head": SHA, "behind": False, "required": ["lint", "build"], "passed": ["lint"]}
        result, calls = self.go(replies={"look-checks-1": partial, "look-checks-2": dict(partial, passed=["lint", "build"])})
        self.assertEqual(result["stage"], "awaiting-look")
        self.assertEqual(self.after_pr(calls), ["look-checks-1", "look-checks-2"])
        with self.subTest(reply="still partial"):
            result, calls = self.go(replies={f"look-checks-{k}": partial for k in (1, 2, 3)})
            self.assertEqual(result["stage"], "checks-pending")
            self.assertEqual(result["pending"], ["build"])
            self.assertNotIn("look-checks-4", labels(calls))

    def test_checks_still_pending_after_three_waits_stop_before_the_look(self):
        result, calls = self.go(replies={f"look-checks-{k}": self.PENDING for k in (1, 2, 3)})
        self.assertEqual(result["stage"], "checks-pending")
        self.assertEqual(result["pending"], ["ci"])
        self.assertNotIn("look", result["cont"])
        self.assertNotIn("look-checks-4", labels(calls))
        self.assertNotIn("merge", labels(calls))

    def test_a_red_check_gets_the_one_fix_and_the_stop_names_the_fixed_head(self):
        result, calls = self.go(replies={"look-checks-1": self.RED, "look-checks-2": dict(self.GREEN, head=F)}, patch=self.FIXED)
        got = labels(calls)
        self.assertEqual(self.after_pr(calls), ["look-checks-1", "fix-ci", "fix-ci-review", "look-push", "look-checks-2", "look-reverify", "look-checks-3"])
        self.assertEqual(result["stage"], "awaiting-look")
        self.assertEqual(result["head"], F)
        self.assertEqual(result["cont"]["look"], {"pr": 42, "head": F})
        self.assertEqual(result["cont"]["checks_fixes"], 1)
        self.assertEqual(result["cont"]["verified"]["head"], F)
        self.assertIn("at the head " + F, prompt(calls, "look-push"))
        self.assertIn("look at the head " + F, prompt(calls, "look-checks-2"))
        self.assertIn("moved to the head " + F, prompt(calls, "look-reverify"))
        self.assertIn("FAIL test_cache: host-installed state", prompt(calls, "fix-ci"))
        self.assertIn("run no forge-claim command", prompt(calls, "fix-ci"))
        self.assertEqual([c["agentType"] for c in calls if c["label"] == "fix-ci"], ["implementer"])
        self.assertEqual([c["agentType"] for c in calls if c["label"] == "fix-ci-review"], ["reviewer"])
        self.assertEqual([l for l in got if l.startswith("land-")], [])
        for call in calls:
            self.assertNotIn("forge-claim land", call["prompt"], call["label"])

    def test_a_second_red_check_stops_at_checks_not_at_the_look(self):
        result, calls = self.go(replies={"look-checks-1": self.RED, "look-checks-2": dict(self.RED, head=F)}, patch=self.FIXED)
        got = labels(calls)
        self.assertEqual(result["stage"], "checks")
        self.assertEqual(result["failing"], ["ci"])
        self.assertEqual(result["cont"]["checks_fixes"], 1)
        self.assertEqual(got.count("fix-ci"), 1)
        self.assertNotIn("look", result["cont"])
        self.assertNotIn("look-reverify", got)

    def test_a_rerun_at_the_unchanged_head_polls_again_with_the_stale_question(self):
        rerun = {"fix-ci": {"start_head": SHA, "commit": SHA, "notes": "cache restore failed; failed jobs rerun"}}
        result, calls = self.go(replies={"look-checks-1": self.RED, "look-checks-2": self.GREEN}, patch=rerun)
        self.assertEqual(self.after_pr(calls), ["look-checks-1", "fix-ci", "look-checks-2"])
        self.assertEqual((result["stage"], result["head"]), ("awaiting-look", SHA))
        self.assertIn("This poll follows a rerun of failed jobs at this head", prompt(calls, "look-checks-2"))
        self.assertNotIn("This poll follows a rerun of failed jobs at this head", prompt(calls, "look-checks-1"))

    def test_a_base_that_moved_during_the_wait_is_synced_pushed_and_verified_before_the_stop(self):
        result, calls = self.go(replies={"look-checks-1": dict(self.GREEN, behind=True)},
                                patch={"sync-1": {"merge_commit": D, "head": D}, "look-reverify": {"pictures": LookStopTest.PICS}})
        self.assertEqual(self.after_pr(calls), ["look-checks-1", "sync-1", "look-push", "look-checks-2", "look-reverify", "look-checks-3"])
        self.assertEqual(result["stage"], "awaiting-look")
        self.assertEqual(result["head"], D)
        self.assertEqual(result["cont"]["look"]["head"], D)
        self.assertEqual(result["cont"]["verified"]["head"], D)
        self.assertEqual(result["pictures"], LookStopTest.PICS)
        self.assertEqual([l for l in labels(calls) if l.startswith("land-")], [])

    def test_a_sync_after_the_fix_is_verified_at_the_head_the_stop_names(self):
        result, calls = self.go(replies={"look-checks-1": self.RED, "look-checks-2": dict(self.GREEN, head=F, behind=True)},
                                patch=dict(self.FIXED, **{"sync-1": {"merge_commit": D, "head": D}, "look-reverify": {"pictures": LookStopTest.PICS}}))
        self.assertEqual(self.after_pr(calls), ["look-checks-1", "fix-ci", "fix-ci-review", "look-push", "look-checks-2", "sync-1",
                                                "look-push", "look-checks-3", "look-reverify", "look-checks-4"])
        self.assertEqual(result["head"], D)
        self.assertEqual(result["cont"]["look"], {"pr": 42, "head": D})
        self.assertEqual(result["cont"]["verified"]["head"], D)
        self.assertEqual(result["cont"]["verified"]["pictures"], LookStopTest.PICS)
        self.assertEqual(result["pictures"], LookStopTest.PICS)
        self.assertIn("moved to the head " + D, prompt(calls, "look-reverify"))
        self.assertEqual(labels(calls).count("look-reverify"), 1)

    def test_a_base_that_keeps_moving_stops_at_sync_contention(self):
        result, calls = self.go(replies={f"look-checks-{k}": dict(self.GREEN, behind=True) for k in (1, 2, 3)})
        self.assertEqual(result["stage"], "sync-contention")
        self.assertEqual(self.after_pr(calls), ["look-checks-1", "sync-1", "look-checks-2", "sync-2", "look-checks-3"])

    def test_a_poll_that_reads_another_pull_request_head_stops_as_head_moved(self):
        result, _ = self.go(replies={"look-checks-1": dict(self.GREEN, head=B)})
        self.assertEqual(result["stage"], "head-moved")
        self.assertEqual(result["head"], B)
        self.assertNotIn("look", result["cont"])

    def test_an_approve_of_the_head_the_stop_named_lands_it_with_no_new_push(self):
        def landing(first, head, patch):
            result, calls = run(args=dict(ARGS, cont=first["cont"], look={"answer": "approve", "head": head}), patch=patch)
            got = labels(calls)
            self.assertEqual(result["stage"], "done")
            self.assertEqual([l for l in got if l in ("look-head", "look-read", "look-post", "pr", "merge")], ["look-head", "look-read", "pr", "merge"])
            for label in got:
                self.assertFalse(label in ("verify", "look-verify", "look-push", "look-reverify") or label.startswith(("final-", "land-push-", "sync-", "fix-ci", "look-checks-")), label)
            self.assertNotIn("Push the branch (", prompt(calls, "pr"))
            self.assertIn("reuse the open pull request #42", prompt(calls, "pr"))
            for call in calls:
                self.assertNotIn("Then push the branch", call["prompt"], call["label"])
            self.assertIn("--match-head-commit " + head, prompt(calls, "merge"))

        first, _ = self.go(replies={"look-checks-1": self.RED}, patch=self.FIXED)
        self.assertEqual(first["head"], F)
        self.assertEqual(first["cont"]["verified"]["head"], F)
        landing(first, F, {"setup": {"look": MARKED, "head": F}, "look-head": {"head": F},
                           "pr": {"head": F, "green": green_read(F)}})
        with self.subTest(run="unfixed"):
            unfixed, _ = self.go(replies={"look-checks-1": self.PENDING, "look-checks-2": self.GREEN})
            landing(unfixed, SHA, RESUME)


class LookResumeTest(unittest.TestCase):
    """#1139: the owner's approve or changes answer resumes the awaiting-look cont of a marked delivery."""

    def look_cont(self):
        result, _ = run(patch={"setup": {"look": MARKED}})
        self.assertEqual(result["stage"], "awaiting-look")
        return result["cont"]

    def approve(self, head=SHA, patch=None, replies=None, cont=None, **extra):
        look = dict({"answer": "approve", "head": head}, **extra)
        return run(args=dict(ARGS, cont=cont or self.look_cont(), look=look), patch=RESUME if patch is None else patch, replies=replies)

    def test_approve_for_the_current_head_records_the_approval_and_merges(self):
        result, calls = self.approve()
        got = labels(calls)
        self.assertEqual(result["stage"], "done")
        self.assertEqual([l for l in got if l in ("look-head", "look-read", "look-post", "pr", "merge")], ["look-head", "look-read", "pr", "merge"])
        self.assertNotIn("look-verify", got)
        self.assertIn("gh pr view 42 --repo owner/repo --json state,headRefOid", prompt(calls, "look-head"))
        self.assertIn("Run alone and exactly: look-approval status --repo owner/repo --issue 9 --pr 42 --head " + SHA, prompt(calls, "look-read"))
        self.assertNotIn("--message", prompt(calls, "look-read"))
        with self.subTest(message="msg-7"):
            _, named = self.approve(message="msg-7")
            self.assertNotIn("--message", prompt(named, "look-read"))
            self.assertNotIn("look-post", labels(named))

    def test_the_awaiting_look_stop_tells_the_owner_an_approve_lands_on_a_recorded_approval(self):
        result, _ = run(patch={"setup": {"look": MARKED}})
        ways = result["ways"]
        approve = ways[:ways.index("or look {answer: fix")]
        self.assertIn("to land on the approval recorded for that head", approve)
        self.assertIn("this program never posts one", approve)
        self.assertNotIn("to approve that head,", approve)

    def test_a_resume_after_a_console_recorded_approval_reads_it_and_posts_nothing(self):
        result, calls = self.approve(replies={"look-read": {"verdict": "approved", "kept_from": None}})
        self.assertEqual(result["stage"], "done")
        self.assertEqual([l for l in labels(calls) if l in ("look-head", "look-read", "look-post", "pr", "merge")], ["look-head", "look-read", "pr", "merge"])
        self.assertIn("look-approval status --repo owner/repo --issue 9 --pr 42 --head " + SHA, prompt(calls, "look-read"))
        for call in calls:
            self.assertNotIn("look-approval post", call["prompt"])
        self.assertIn("--match-head-commit " + SHA, prompt(calls, "merge"))

    def test_an_approve_with_no_recorded_approval_stops_and_merges_nothing(self):
        cases = (({"verdict": "needed", "kept_from": None}, "needed"), ({"verdict": "unmarked", "kept_from": None}, "unmarked"))
        for reply, tail in cases:
            with self.subTest(tail=tail):
                result, calls = self.approve(replies={"look-read": reply})
                self.stops_at_approve(result, calls, "the approval of " + SHA + " was not recorded: the verified head was " + SHA
                                      + " and look-approval status answered " + tail, absent=("look-post", "look-pr", "pr", "merge"))

    def test_an_approve_whose_status_read_has_no_verdict_says_it_could_not_check(self):
        result, calls = self.approve(replies={"look-read": {"detail": "x"}})
        self.stops_at_approve(result, calls, "the approval of " + SHA + " could not be checked: the verified head was " + SHA
                              + " and look-approval status answered no verdict: x", absent=("look-post", "look-pr", "pr", "merge"))
        self.assertNotIn("not recorded", result["details"])

    def test_an_approve_carrying_the_number_the_inbox_prints_reads_the_approval_and_lands(self):
        for message in (7, "msg-7"):
            with self.subTest(message=message):
                result, calls = self.approve(message=message)
                self.assertEqual(result["stage"], "done")
                self.assertIn("look-read", labels(calls))
                self.assertNotIn("look-post", labels(calls))
        for message in (0, -1, 1.5, True, None, "bad message", [7]):
            with self.subTest(message=message):
                result, _ = self.approve(message=message)
                self.assertEqual(result["stage"], "args")

    def test_approve_for_an_older_head_whose_carry_is_refused_stops_at_the_current_head(self):
        result, calls = self.approve(head=B)
        got = labels(calls)
        self.assertEqual(result["stage"], "awaiting-look")
        self.assertEqual(result["head"], SHA)
        self.assertEqual(result["cont"]["look"], {"pr": 42, "head": SHA})
        self.assertTrue(result["reason"].startswith("the approval of " + B + " does not carry to " + SHA + ": pictures-differ"), result["reason"])
        self.assertIn("look-read", got)
        self.assertIn("--head " + B, prompt(calls, "look-read"))
        for label in ("look-post", "look-pr", "pr", "merge"):
            self.assertNotIn(label, got)

    def test_approve_when_the_local_head_moved_records_nothing(self):
        result, calls = self.approve(patch={"setup": {"look": MARKED, "head": F}, "verify": {"head": F}, "look-pr": {"head": F}},
                                     replies={"look-verify": {"head": F, "clean": True, "merge_only": False, "ahead": True, "results": []}})
        got = labels(calls)
        self.assertIn("look-verify", got)
        self.assertNotIn("look-post", got)
        self.assertNotIn("look-read", got)
        self.assertIn("look-pr", got)
        self.assertLess(got.index("look-verify"), got.index("look-pr"))
        self.assertEqual(result["stage"], "awaiting-look")
        self.assertEqual(result["head"], F)
        self.assertEqual(result["reason"], "the approval of " + SHA + " was not recorded: the worktree head " + F + " is ahead of it; " + AWAIT_REASON)
        self.assertEqual(result["cont"]["look"], {"pr": 42, "head": F})

    MOVED = dict(RESUME, **{
        "land-take": {"behind": True}, "sync-1": {"merge_commit": D, "head": D},
        "checks-2": {"state": "passed", "head": D, "required": ["ci"], "passed": ["ci"]}})

    def test_a_head_that_moves_under_the_lock_after_the_approval_stops_at_awaiting_look(self):
        result, calls = self.approve(patch=self.MOVED)
        got = labels(calls)
        self.assertIn("look-status", got)
        self.assertEqual(result["stage"], "awaiting-look")
        self.assertEqual(result["head"], D)
        self.assertNotIn("merge", got)
        self.assertIn("land-unlock", got)
        self.assertEqual(result["cont"]["look"], {"pr": 42, "head": D})

    def test_a_moved_head_whose_approval_is_kept_lands(self):
        result, calls = self.approve(patch=dict(self.MOVED, **{"look-status": {"verdict": "approved", "kept_from": SHA}}))
        got = labels(calls)
        self.assertEqual(result["stage"], "done")
        self.assertLess(got.index("look-status"), got.index("merge"))
        self.assertIn("look-approval status --repo owner/repo --issue 9 --pr 42 --head " + D, prompt(calls, "look-status"))
        self.assertIn("--match-head-commit " + D, prompt(calls, "merge"))
        self.assertIn("look-approval tick --repo owner/repo --issue 9 --pr 42 --head " + D, prompt(calls, "close-out"))

    def test_a_moved_head_whose_status_is_needed_stops_at_awaiting_look(self):
        result, calls = self.approve(patch=dict(self.MOVED, **{"look-status": {"verdict": "needed", "kept_from": None},
                                                               "look-checks-1": {"state": "passed", "head": D, "behind": False, "required": ["ci"], "passed": ["ci"]}}))
        got = labels(calls)
        self.assertEqual(result["stage"], "awaiting-look")
        self.assertEqual(result["head"], D)
        self.assertEqual(result["reason"], "the approval of " + SHA + " does not carry to " + D + ": pictures-differ; " + AWAIT_REASON)
        self.assertLess(got.index("look-carry"), got.index("look-checks-1"))
        self.assertNotIn("merge", got)
        self.assertIn("land-unlock", got)
        self.assertEqual(result["cont"]["look"], {"pr": 42, "head": D})

    def test_a_moved_head_whose_status_failed_stops_without_asking(self):
        for name, kwargs in (("error", {"patch": dict(self.MOVED, **{"look-status": {"verdict": "error", "detail": "x"}})}),
                             ("none", {"patch": self.MOVED, "replies": {"look-status": None}})):
            with self.subTest(reply=name):
                result, calls = self.approve(**kwargs)
                got = labels(calls)
                self.assertEqual(result["stage"], "look-status")
                self.assertIn("cont", result)
                self.assertNotIn("merge", got)
                self.assertIn("land-unlock", got)

    def test_a_marked_landing_reads_an_omitted_required_list_as_pending(self):
        # #1373 C1: a passed reply with no required list proves no required check passed.
        short = {"state": "passed", "head": D, "passed": ["ci"]}
        patch = dict(self.MOVED, **{"look-status": {"verdict": "needed", "kept_from": None}}, **{"land-take": {"behind": True}})
        result, calls = self.approve(patch=patch, replies={f"checks-{k}": short for k in range(2, 7)})
        got = labels(calls)
        self.assertEqual(result["stage"], "checks-pending")
        self.assertNotIn("look-status", got)
        self.assertNotIn("merge", got)

    def test_every_landing_checks_prompt_asks_for_a_required_list_even_when_empty(self):
        # #1373: a marked landing reads an omitted required list as pending, so the clerk is told to always return one.
        patch = dict(self.MOVED, **{"look-status": {"verdict": "needed", "kept_from": None}}, **{"land-take": {"behind": True}})
        _, calls = self.approve(patch=patch)
        text = prompt(calls, "checks-2")
        self.assertIn("Return required always, even as an empty list", text)
        self.assertNotIn("none only when neither lists any", text)

    def test_a_marked_landing_reads_a_missing_required_check_as_pending(self):
        # #1373, D8: a passed reply that leaves a required name out of passed is pending for a marked landing too.
        short = {"state": "passed", "head": D, "required": ["ci", "build"], "passed": ["ci"]}
        patch = dict(self.MOVED, **{"look-status": {"verdict": "needed", "kept_from": None}},
                     **{"land-take": {"behind": True}}, **{f"checks-{k}": short for k in range(2, 7)})
        result, calls = self.approve(patch=patch)
        got = labels(calls)
        self.assertEqual(result["stage"], "checks-pending")
        self.assertNotIn("look-status", got)
        self.assertNotIn("merge", got)

    def test_an_approve_for_a_moved_head_waits_for_its_checks_before_asking_again(self):
        # #1373, D5: the re-ask waits for the checks of the head it shows, and fixes, syncs and pushes nothing.
        moved = {"look-head": {"head": B, "state": "OPEN", "renew": {"verdict": "renewed"}}, "look-read": {"verdict": "needed", "kept_from": None}}
        pending = {"state": "pending", "head": B, "behind": False, "pending": ["ci"]}
        result, calls = self.approve(head=SHA, replies=dict(moved, **{f"look-checks-{k}": pending for k in (1, 2, 3)}))
        got = labels(calls)
        self.assertEqual(result["stage"], "checks-pending")
        self.assertTrue(result["reason"].startswith("the approval of " + SHA + " was not recorded: PR #42's head is now " + B), result["reason"])
        for label in ("look-post", "look-verify", "look-push", "look-pr", "pr", "merge", "fix-ci"):
            self.assertNotIn(label, got)
        self.assertIn("look at the head " + B, prompt(calls, "look-checks-1"))
        with self.subTest(reply="green"):
            green = {"state": "passed", "head": B, "behind": True, "required": ["ci"], "passed": ["ci"]}
            result, calls = self.approve(head=SHA, replies=dict(moved, **{"look-checks-1": green}))
            got = labels(calls)
            self.assertEqual((result["stage"], result["head"]), ("awaiting-look", B))
            self.assertEqual(got[got.index("look-head") + 1:], ["look-read", "look-checks-1"])

    def test_a_fix_for_a_moved_head_with_a_red_check_stops_at_checks(self):
        red = {"state": "failed", "head": B, "behind": False, "required": ["ci"], "failing": ["ci"], "details": "x"}
        result, calls = self.fix(head=SHA, replies={"look-head": {"head": B, "state": "OPEN", "renew": {"verdict": "renewed"}}, "look-checks-1": red})
        got = labels(calls)
        self.assertEqual(result["stage"], "checks")
        self.assertEqual(result["failing"], ["ci"])
        for label in ("look-post", "look-fix", "fix-ci", "merge"):
            self.assertNotIn(label, got)

    def approved_cont(self):
        result, _ = self.approve(replies={"merge": None})
        self.assertEqual(result["stage"], "merge")
        self.assertEqual(result["cont"]["look"], {"pr": 42, "head": SHA, "approved": SHA})
        return result["cont"]

    def test_an_approved_cont_lands_without_a_second_approval(self):
        result, calls = run(args=dict(ARGS, cont=self.approved_cont()), patch=RESUME)
        self.assertEqual(result["stage"], "done")
        self.assertNotIn("look-head", labels(calls))
        self.assertNotIn("look-post", labels(calls))
        self.assertNotIn("look-read", labels(calls))
        self.assertNotIn("look-status", labels(calls))

    def test_changes_run_one_fix_round_verify_again_and_stop_at_the_new_head(self):
        patch = dict(RESUME, **{"look-fix": {"start_head": SHA, "commit": F}, "verify": {"head": F}, "look-pr": {"head": F}})
        result, calls = run(args=dict(ARGS, cont=self.look_cont(), look={"answer": "changes", "words": "make the label bold"}), patch=patch)
        got = labels(calls)
        self.assertEqual(result["stage"], "awaiting-look")
        self.assertEqual(result["head"], F)
        self.assertEqual([l for l in got if l in ("look-fix", "look-fix-review", "verify", "look-pr")],
                         ["look-fix", "look-fix-review", "verify", "look-pr"])
        self.assertEqual(got.count("look-fix"), 1)
        fix = [c for c in calls if c["label"] == "look-fix"][0]
        self.assertEqual(fix["agentType"], "implementer")
        self.assertIn(json.dumps("make the label bold"), fix["prompt"])
        self.assertEqual([c["agentType"] for c in calls if c["label"] == "look-fix-review"], ["reviewer"])
        self.assertNotIn("merge", got)

    FIXED = dict(RESUME, **{"look-fix": {"start_head": SHA, "commit": F}, "verify": {"head": F},
                            "pr": {"head": F, "green": green_read(F)},
                            "look-status": {"verdict": "approved", "kept_from": SHA}})

    def fix(self, patch=None, head=SHA, cont=None, replies=None):
        look = {"answer": "fix", "head": head, "words": "make the label bold"}
        return run(args=dict(ARGS, cont=cont or self.look_cont(), look=look), patch=self.FIXED if patch is None else patch, replies=replies)

    def test_fix_records_the_approval_fixes_once_and_lands(self):
        result, calls = self.fix()
        got = labels(calls)
        self.assertEqual(result["stage"], "done")
        steps = ("look-head", "look-post", "look-fix", "look-fix-review", "verify", "look-status", "merge")
        self.assertEqual([l for l in got if l in steps], list(steps))
        self.assertEqual(got.count("look-fix"), 1)
        self.assertIn("--answer fix --message session-s1 --words-file /r/.git/worktrees/w/deliver-standard/look-fix-words.txt",
                      prompt(calls, "look-post"))
        self.assertIn("/r/.git/worktrees/w/deliver-standard/look-fix-words.txt", prompt(calls, "look-post"))
        self.assertIn("look-approval status --repo owner/repo --issue 9 --pr 42 --head " + F, prompt(calls, "look-status"))
        self.assertIn("--match-head-commit " + F, prompt(calls, "merge"))

    # #1425: the clerk has no Write tool, so the look-post prompt may name only the tools its agent definition grants.
    def test_the_look_post_prompt_names_only_tools_the_clerk_has(self):
        _, calls = self.fix()
        self.assertEqual(granted_tools(), {"Bash", "Read", "Skill"})
        text = prompt(calls, "look-post")
        self.assertEqual(outside_clerk_tools(text), set())
        self.assertEqual([c["agentType"] for c in calls if c["label"] == "look-post"], ["clerk"])
        # The check itself: an added sentence asking for a tool the clerk lacks, with or without the word "tool", is found.
        self.assertEqual(outside_clerk_tools(text + "\nUse Edit to update the file"), {"Edit"})
        self.assertEqual(outside_clerk_tools(text + "\nUse the Write tool"), {"Write"})
        self.assertEqual(outside_clerk_tools("Run it with Bash, then Read the file"), set())

    def look_post_commands(self, plan_dir, words):
        """The look-post prompt for a plan directory: its words-file write and its post command, as the clerk is told to run them."""
        cont = self.look_cont()
        cont["setup"]["plan_dir"] = str(plan_dir)
        look = {"answer": "fix", "head": SHA, "words": words}
        _, calls = run(args=dict(ARGS, cont=cont, look=look), patch=self.FIXED)
        text = prompt(calls, "look-post")
        return (text, re.search(r"run alone and exactly: (printf [^\n]*)", text).group(1),
                re.search(r"run alone and exactly: (look-approval post[^\n]*)", text).group(1))

    # #1425 (DR-01): the plan directory is a checkout path; one with a space, an apostrophe and a dollar sign is written and posted whole.
    def test_the_owners_words_reach_the_words_file_unchanged(self):
        words = "make the \"label\" bold:\nit costs $5 and `x` and 'y' \\ n \u00e9 \U0001f600\n\n"
        with tempfile.TemporaryDirectory() as tmp:
            plan_dir = Path(tmp) / "Team Checkout" / "it's $HOME" / "deliver-standard"
            plan_dir.mkdir(parents=True)
            _, write, post = self.look_post_commands(plan_dir, words)
            subprocess.run(["sh", "-c", write], check=True, cwd=tmp, timeout=60)
            self.assertEqual((plan_dir / "look-fix-words.txt").read_bytes(), words.encode("utf-8"))
            self.assertEqual(os.listdir(tmp), ["Team Checkout"], "the write created a file beside the plan directory")
            self.assertEqual(shlex.split(post)[-1], str(plan_dir / "look-fix-words.txt"))

    # #1425 (DR-03): a write that fails partway leaves a prefix the post would accept, so the clerk is told to stop and the program stops.
    def test_a_failed_words_write_posts_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            text, write, _ = self.look_post_commands(Path(tmp), "make the label bold")
            self.assertIn("If that command exits non-zero, run nothing else and return verdict write-failed", text)
            bin_dir = Path(tmp) / "bin"
            bin_dir.mkdir()
            decoder = bin_dir / "base64"
            decoder.write_text("#!/bin/sh\nprintf prefix\nexit 1\n", encoding="utf-8")
            decoder.chmod(0o755)
            done = subprocess.run([shutil.which("sh"), "-c", write], cwd=tmp, env={"PATH": str(bin_dir)}, capture_output=True, timeout=60)
            self.assertEqual((done.returncode != 0, (Path(tmp) / "look-fix-words.txt").read_bytes()), (True, b"prefix"))
        failed = dict(self.FIXED, **{"look-post": {"verdict": "write-failed", "detail": "base64: invalid input"}})
        result, calls = self.fix(patch=failed)
        self.assertEqual(result["stage"], "look-approve")
        for label in ("look-fix", "look-status", "merge"):
            self.assertNotIn(label, labels(calls))

    def test_fix_for_a_moved_head_posts_nothing(self):
        result, calls = self.fix(head=B)
        got = labels(calls)
        self.assertEqual(result["stage"], "awaiting-look")
        self.assertEqual(result["head"], SHA)
        self.assertEqual(result["cont"]["look"], {"pr": 42, "head": SHA})
        for label in ("look-post", "look-fix", "merge"):
            self.assertNotIn(label, got)
        result, calls = self.fix(replies={"look-head": {"head": B, "state": "OPEN", "renew": {"verdict": "renewed"}}})
        self.assertEqual((result["stage"], result["head"]), ("awaiting-look", B))
        self.assertNotIn("look-post", labels(calls))

    def test_a_fix_for_a_head_other_than_the_awaiting_look_head_posts_nothing(self):
        # The pull request head is the head the owner named, but not the one the stop left for the owner.
        result, calls = self.fix(head=B, replies={"look-head": {"head": B, "state": "OPEN", "renew": {"verdict": "renewed"}}})
        self.assertEqual((result["stage"], result["head"]), ("awaiting-look", B))
        for label in ("look-post", "look-fix"):
            self.assertNotIn(label, labels(calls))

    def test_a_fix_answer_whose_fix_makes_no_commit_leaves_no_approval_in_the_cont(self):
        noop = dict(self.FIXED, **{"look-fix": {"start_head": SHA, "commit": SHA}})
        stopped, _ = self.fix(patch=noop, cont=self.approved_cont())
        self.assertEqual(stopped["stage"], "look-fix")
        self.assertEqual(stopped["cont"]["look"], {"pr": 42, "head": SHA})

    def test_a_fix_answer_stops_at_look_when_the_setup_could_not_read_the_marker(self):
        cont = self.look_cont()
        unread = dict(self.FIXED, setup={"look": {"verdict": "error", "detail": "x"}, "head": SHA})
        result, calls = self.fix(patch=unread, cont=cont)
        got = labels(calls)
        self.assertEqual(result["stage"], "look")
        self.assertEqual(result["cont"]["look"], {"pr": 42, "head": SHA})
        for label in ("look-head", "look-post", "look-fix", "look-fix-review", "verify", "merge"):
            self.assertNotIn(label, got)

    def test_a_fix_for_a_closed_pull_request_posts_nothing(self):
        result, calls = self.fix(replies={"look-head": {"head": SHA, "state": "CLOSED", "renew": {"verdict": "renewed"}}})
        self.assertEqual(result["stage"], "look-approve")
        for label in ("look-post", "look-fix"):
            self.assertNotIn(label, labels(calls))

    def test_a_fix_whose_post_is_not_posted_stops_before_the_fix(self):
        result, calls = self.fix(replies={"look-post": {"verdict": "untrusted", "comment_id": 5}})
        self.assertEqual(result["stage"], "look-approve")
        self.assertNotIn("look-fix", labels(calls))

    def test_a_fix_whose_status_is_not_kept_stops_at_awaiting_look(self):
        result, calls = self.fix(patch=dict(self.FIXED, **{"look-status": {"verdict": "needed", "kept_from": None}}))
        got = labels(calls)
        self.assertEqual(result["stage"], "awaiting-look")
        self.assertEqual(result["head"], F)
        self.assertEqual(result["cont"]["look"], {"pr": 42, "head": F})
        self.assertNotIn("merge", got)

    def test_changes_on_an_approved_cont_takes_no_lock_and_stops_at_the_new_head(self):
        patch = dict(RESUME, **{"look-fix": {"start_head": SHA, "commit": F}, "verify": {"head": F}, "look-pr": {"head": F}})
        result, calls = run(args=dict(ARGS, cont=self.approved_cont(), look={"answer": "changes", "words": "make the label bold"}), patch=patch)
        got = labels(calls)
        self.assertEqual(result["stage"], "awaiting-look")
        self.assertEqual(result["head"], F)
        self.assertEqual(result["cont"]["look"], {"pr": 42, "head": F})
        self.assertIn("look-pr", got)
        for lock_step in ("pr", "land-unlock", "merge"):
            self.assertNotIn(lock_step, got)

    def test_a_changes_answer_whose_fix_makes_no_commit_revokes_the_approval_for_the_next_resume(self):
        noop = dict(RESUME, **{"look-fix": {"start_head": SHA, "commit": SHA}})
        stopped, _ = run(args=dict(ARGS, cont=self.approved_cont(), look={"answer": "changes", "words": "make the label bold"}), patch=noop)
        self.assertEqual(stopped["stage"], "look-fix")
        self.assertEqual(stopped["cont"]["look"], {"pr": 42, "head": SHA})
        result, calls = run(args=dict(ARGS, cont=stopped["cont"]), patch=RESUME)
        got = labels(calls)
        self.assertEqual(result["stage"], "awaiting-look")
        for lock_step in ("pr", "land-unlock", "merge"):
            self.assertNotIn(lock_step, got)

    def test_a_changes_answer_that_stops_before_the_fix_revokes_the_approval_for_the_next_resume(self):
        # The resume stops at dirty, before the changes round runs: the cont it returns must already carry no approval.
        dirty = dict(RESUME, setup={"look": MARKED, "head": SHA, "dirty": True})
        stopped, _ = run(args=dict(ARGS, cont=self.approved_cont(), look={"answer": "changes", "words": "make the label bold"}), patch=dirty)
        self.assertEqual(stopped["stage"], "dirty")
        self.assertEqual(stopped["cont"]["look"], {"pr": 42, "head": SHA})
        result, calls = run(args=dict(ARGS, cont=stopped["cont"]), patch=RESUME)
        got = labels(calls)
        self.assertEqual(result["stage"], "awaiting-look")
        for lock_step in ("pr", "land-unlock", "merge"):
            self.assertNotIn(lock_step, got)

    def test_a_changes_answer_that_stops_in_setup_or_on_a_bad_amend_returns_a_cont_with_no_approval(self):
        # These stops return the caller's cont as it came, before the changes round: it must carry no approval, or a resume with no look lands the rejected head.
        changes = {"answer": "changes", "words": "make the label bold"}
        stops = {
            "setup": (dict(ARGS, cont=self.approved_cont(), look=changes), dict(RESUME, setup={"look": MARKED, "head": SHA, "merge_strategy": None})),
            "amend": (dict(ARGS, cont=self.approved_cont(), look=changes, amend=[]), RESUME),
        }
        for stage, (args, patch) in stops.items():
            with self.subTest(stage=stage):
                stopped, _ = run(args=args, patch=patch)
                self.assertEqual(stopped["stage"], stage)
                self.assertEqual(stopped["cont"]["look"], {"pr": 42, "head": SHA})
                result, calls = run(args=dict(ARGS, cont=stopped["cont"]), patch=RESUME)
                got = labels(calls)
                self.assertEqual(result["stage"], "awaiting-look")
                for lock_step in ("pr", "land-unlock", "merge"):
                    self.assertNotIn(lock_step, got)

    def test_a_changes_answer_renews_the_claim_before_the_fix_and_edits_nothing_when_it_is_lost(self):
        patch = dict(RESUME, **{"look-fix": {"start_head": SHA, "commit": F}, "verify": {"head": F}, "look-pr": {"head": F}})
        _, calls = run(args=dict(ARGS, cont=self.look_cont(), look={"answer": "changes", "words": "make the label bold"}), patch=patch)
        names = labels(calls)
        self.assertLess(names.index("renew-look-fix"), names.index("look-fix"))
        lost = dict(patch, **{"renew-look-fix": {"verdict": "not_held"}})
        result, calls = run(args=dict(ARGS, cont=self.look_cont(), look={"answer": "changes", "words": "make the label bold"}), patch=lost)
        self.assertEqual(result["stage"], "claim-lost")
        self.assertNotIn("look-fix", labels(calls))

    def test_a_changes_round_whose_review_finds_a_defect_stops_without_a_second_round(self):
        patch = dict(RESUME, **{"look-fix": {"start_head": SHA, "commit": F}, "verify": {"head": F}, "look-pr": {"head": F}})
        finding = {"verdict": "findings", "findings": [{"severity": "important", "summary": "still plain", "failing_input": "x"}]}
        result, calls = run(args=dict(ARGS, cont=self.look_cont(), look={"answer": "changes", "words": "make the label bold"}),
                            patch=patch, replies={"look-fix-review": finding})
        got = labels(calls)
        self.assertEqual(result["stage"], "look-fix-review")
        self.assertEqual(got.count("look-fix"), 1)
        self.assertNotIn("verify", got)
        self.assertNotIn("look-pr", got)

    def test_look_args_are_checked_before_any_agent(self):
        cont = self.look_cont()
        approve = {"answer": "approve", "head": SHA}
        shape = "look must be {answer: approve, head, message?}, {answer: fix, head, words, message?} or {answer: changes, words}"
        rows = (
            (dict(ARGS, look=approve), "look needs a cont: it answers an awaiting-look stop"),
            (dict(ARGS, cont=cont, mode="ready", look=approve), "look needs mode ship"),
            (dict(ARGS, cont=ship_cont(), look=approve), "look approve needs a cont that stopped at awaiting-look"),
            (dict(ARGS, cont=cont, look={"answer": "approve", "head": "abc"}), shape),
            (dict(ARGS, cont=cont, look={"answer": "changes", "words": "  "}), shape),
            (dict(ARGS, cont=cont, look={"answer": "changes", "words": "x" * 2001}), shape),
            (dict(ARGS, cont=cont, look={"answer": "approve", "head": SHA, "message": "a b"}), shape),
            (dict(ARGS, cont=cont, look={"answer": "later"}), shape),
            (dict(ARGS, cont=cont, look={"answer": "fix", "head": SHA}), shape),
            (dict(ARGS, cont=cont, look={"answer": "fix", "head": SHA, "words": "x" * 2001}), shape),
            (dict(ARGS, cont=ship_cont(), look={"answer": "fix", "head": SHA, "words": "w"}),
             "look fix needs a cont that stopped at awaiting-look"),
        )
        for n, (args, error) in enumerate(rows):
            with self.subTest(row=n, error=error):
                out = run_out(args=args)
                self.assertEqual(out["result"], {"stage": "args", "error": error})
                self.assertEqual(out["calls"], [])

    def test_approve_on_an_unmarked_issue_ships_as_today(self):
        result, calls = run(args=dict(ARGS, cont=self.look_cont(), look={"answer": "approve", "head": SHA}), patch={"setup": {"head": SHA}})
        self.assertEqual(result["stage"], "done")
        self.assertNotIn("look-head", labels(calls))

    def test_a_new_approve_on_an_approved_cont_is_validated_again(self):
        result, calls = self.approve(head=B, cont=self.approved_cont())
        got = labels(calls)
        self.assertEqual(result["stage"], "awaiting-look")
        self.assertEqual(result["head"], SHA)
        self.assertEqual(result["cont"]["look"], {"pr": 42, "head": SHA})
        self.assertTrue(result["reason"].startswith("the approval of " + B + " does not carry to " + SHA + ": pictures-differ"), result["reason"])
        self.assertIn("look-head", got)
        self.assertIn("look-read", got)
        self.assertIn("--head " + B, prompt(calls, "look-read"))
        for label in ("look-post", "merge"):
            self.assertNotIn(label, got)

    def test_an_incomplete_look_head_reply_stops_at_look_approve(self):
        replies = ({"state": "OPEN", "renew": {"verdict": "renewed"}}, {"state": "OPEN", "head": "abc", "renew": {"verdict": "renewed"}})
        for reply, approved in [(r, approved) for r in replies for approved in (False, True)]:
            with self.subTest(reply=reply, approved_cont=approved):
                result, calls = self.approve(replies={"look-head": reply}, cont=self.approved_cont() if approved else None)
                got = labels(calls)
                self.assertEqual(result["stage"], "look-approve")
                self.assertEqual(result["details"], self.UNREAD)
                self.assertEqual(result["cont"]["look"], {"pr": 42, "head": SHA})
                for label in ("look-read", "look-post", "look-pr", "pr", "merge"):
                    self.assertNotIn(label, got)
        with self.subTest(reply=None):
            result, calls = self.approve(replies={"look-head": None})
            got = labels(calls)
            self.assertEqual(result["stage"], "look-approve")
            self.assertEqual(result["details"], self.UNREAD)
            self.assertNotIn("not recorded", result["details"])
            for label in ("look-read", "look-post", "look-pr", "pr", "merge"):
                self.assertNotIn(label, got)

    UNREAD = "the approval of " + SHA + " could not be checked: PR #42's head could not be read; the verified head is " + SHA

    # #1246: an approve answer is verified and recorded for the pull request head, else the stop names both heads.
    NOT_RECORDED = " was not recorded: "

    def stops_at_approve(self, result, calls, details, absent=("look-read", "look-post", "look-pr", "pr", "merge")):
        self.assertEqual(result["stage"], "look-approve")
        self.assertEqual(result["details"], details)
        self.assertEqual(result["cont"]["look"], {"pr": 42, "head": SHA})
        got = labels(calls)
        for label in absent:
            self.assertNotIn(label, got)

    def test_approve_for_the_pr_head_after_a_merge_on_the_verified_head_verifies_records_and_lands(self):
        result, calls = self.approve(head=D, patch=LOOK_MERGED, replies={"look-verify": LOOK_OK})
        got = labels(calls)
        w = "git -C /r/.wt/w-issue-9-x "
        self.assertEqual(result["stage"], "done")
        self.assertEqual([l for l in got if l in ("look-head", "look-verify", "look-read", "look-post", "pr", "merge")],
                         ["look-head", "look-verify", "look-read", "pr", "merge"])
        for part in (w + "merge --ff-only " + D, w + "merge-base --is-ancestor HEAD " + D, w + "merge-base --is-ancestor " + D + " HEAD",
                     "rev-list --no-merges " + SHA + ".." + D + " ^origin/dev",
                     slotted([{"id": "build", "argv": ["make", "build"], "cwd": "."}])):
            self.assertIn(part, prompt(calls, "look-verify"))
        self.assertIn("look-approval status --repo owner/repo --issue 9 --pr 42 --head " + D, prompt(calls, "look-read"))
        self.assertIn("--sha " + D + " --wait --lease", prompt(calls, "land-take"))
        # #1373: the approved head is already pushed, so the pr call reuses its pull request and carries no body text.
        self.assertIn("reuse the open pull request #42", prompt(calls, "pr"))
        self.assertNotIn("Push the branch (", prompt(calls, "pr"))
        self.assertIn("--match-head-commit " + D, prompt(calls, "merge"))
        self.assertIn("look-approval tick --repo owner/repo --issue 9 --pr 42 --head " + D, prompt(calls, "close-out"))

    def test_the_merge_check_of_an_approved_head_leaves_out_merges_the_integration_branch_holds(self):
        # A hand-resolved merge reachable from origin/dev is not the head's own: only the merges past it are checked.
        _, calls = self.approve(head=D, patch=LOOK_MERGED, replies={"look-verify": LOOK_OK})
        self.assertIn("rev-list --merges " + SHA + ".." + D + " ^origin/dev (", prompt(calls, "look-verify"))

    def test_an_approve_whose_head_fails_verification_stops_with_both_heads(self):
        for reply in (dict(LOOK_OK, results=[{"id": "build", "status": "fail", "summary": "boom"}]), dict(LOOK_OK, clean=False)):
            with self.subTest(reply=reply):
                result, calls = self.approve(head=D, patch=LOOK_MERGED, replies={"look-verify": reply})
                self.stops_at_approve(result, calls, "the approval of " + D + " was not recorded: its verification failed, so the verified head stays " + SHA)
                self.assertIn(D, result["reason"])
                self.assertIn(SHA, result["reason"])

    def test_an_approve_whose_head_adds_its_own_commits_stops_with_both_heads(self):
        result, calls = self.approve(head=D, patch=LOOK_MERGED, replies={"look-verify": dict(LOOK_OK, merge_only=False, results=[])})
        self.stops_at_approve(result, calls, "the approval of " + D + " was not recorded: it adds commits after the verified head " + SHA
                              + " that are not clean merges of dev, so it needs a review first")

    def test_an_unusable_look_verify_reply_stops_with_both_heads(self):
        replies = (None, {"head": D, "clean": True, "ahead": False, "results": []}, {"head": D, "clean": True, "merge_only": True, "results": []},
                   dict(LOOK_OK, head="abc"))
        for reply in replies:
            with self.subTest(reply=reply):
                result, calls = self.approve(head=D, patch=LOOK_MERGED, replies={"look-verify": reply})
                self.stops_at_approve(result, calls, "the approval of " + D + " was not recorded: its verification returned no usable reply; the verified head is " + SHA)

    def test_an_approve_whose_worktree_head_diverged_stops_before_any_push(self):
        result, calls = self.approve(patch={"setup": {"look": MARKED, "head": F}, "verify": {"head": F}},
                                     replies={"look-verify": {"head": F, "clean": True, "merge_only": False, "ahead": False, "results": []}})
        self.stops_at_approve(result, calls, "the approval of " + SHA + " was not recorded: the worktree head " + F
                              + " neither fast-forwards to it nor contains it, so it cannot be pushed over it",
                              absent=("look-read", "look-post", "look-pr", "look-push", "pr", "merge"))

    def test_an_approve_whose_read_fails_stops_with_both_heads(self):
        cases = (
            ({}, {"look-read": {"verdict": "error", "detail": "x"}}, SHA, "could not be checked", "answered error: x"),
            ({}, {"look-read": None}, SHA, "could not be checked", "answered nothing"),
            (dict(head=D, patch=LOOK_MERGED), {"look-verify": LOOK_OK, "look-read": {"verdict": "refused"}}, D, "was not recorded", "answered refused"),
        )
        for kwargs, replies, answered, what, tail in cases:
            with self.subTest(tail=tail):
                result, calls = self.approve(replies=replies, **kwargs)
                self.stops_at_approve(result, calls, "the approval of " + answered + " " + what + ": the verified head was " + SHA
                                      + " and look-approval status " + tail, absent=("look-post", "look-pr", "pr", "merge"))

    def test_an_approve_on_a_pr_that_is_not_open_stops_with_both_heads(self):
        result, calls = self.approve(replies={"look-head": {"state": "CLOSED", "head": D, "renew": {"verdict": "renewed"}}})
        self.stops_at_approve(result, calls, "the approval of " + SHA + " was not recorded: PR #42 is CLOSED, not open, at head " + D,
                              absent=("look-read", "look-post", "look-verify", "pr", "merge"))

    def test_a_landing_stop_after_an_unrecorded_approval_names_both_heads(self):
        result, _ = self.approve(patch={"setup": {"look": MARKED, "head": F}, "verify": {"head": F}},
                                 replies={"look-verify": {"head": F, "clean": True, "merge_only": False, "ahead": True, "results": []}, "look-pr": None})
        self.assertEqual(result["stage"], "pr")
        self.assertTrue(result["reason"].startswith("the approval of " + SHA + " was not recorded: the worktree head " + F + " is ahead of it; "),
                        result["reason"])

    def test_the_scenario_look_cont_is_a_real_stop_cont(self):
        self.assertEqual(LOOK_CONT, self.look_cont())


class LookMovedHeadTest(unittest.TestCase):
    """#1597: an approve resume that finds the PR head moved outside the delivery carries the approval under the landing's rules."""

    OK = [{"id": "build", "status": "pass", "summary": "ok"}]
    BARE = {"head": D, "clean": True, "merge_only": True, "results": OK}
    FILES_CARRIED = {"verdict": "carried", "from": SHA, "reason": None, "rule": "look-files", "comment_id": 501}

    def approve(self, head=SHA, replies=None, patch=None):
        first, _ = run(patch={"setup": {"look": MARKED}})
        return run(args=dict(ARGS, cont=first["cont"], look={"answer": "approve", "head": head}),
                   patch=LOOK_MERGED if patch is None else patch, replies=replies)

    def carries(self, source=SHA):
        return {"look-carry-verify": self.BARE, "look-carry": dict(self.FILES_CARRIED, **{"from": source})}

    def test_a_manual_update_branch_merge_with_no_pictures_carries_and_lands(self):
        result, calls = self.approve(replies={"look-carry-verify": self.BARE, "look-carry": self.FILES_CARRIED})
        got = labels(calls)
        self.assertEqual(result["stage"], "done")
        order = ["look-head", "look-read", "look-carry-verify", "look-carry", "pr", "merge"]
        self.assertEqual([l for l in got if l in order], order)
        self.assertNotIn("look-verify", got)
        self.assertIn("look-approval status --repo owner/repo --issue 9 --pr 42 --head " + SHA, prompt(calls, "look-read"))
        verify = prompt(calls, "look-carry-verify")
        self.assertIn("merge --ff-only " + D, verify)
        self.assertIn("rev-list --no-merges " + SHA + ".." + D + " ^origin/dev", verify)
        self.assertNotIn("--is-ancestor " + SHA + " " + SHA, verify)
        self.assertIn(" --from " + SHA + " --head " + D + "\n", prompt(calls, "look-carry"))
        self.assertIn("--match-head-commit " + D, prompt(calls, "merge"))
        self.assertIn("look-approval tick --repo owner/repo --issue 9 --pr 42 --head " + D, prompt(calls, "close-out"))
        for call in calls:
            self.assertNotIn("look-approval post", call["prompt"])

    def test_an_owners_head_past_the_verified_head_carries_from_the_owners_head(self):
        result, calls = self.approve(head=B, replies=self.carries(B))
        self.assertEqual(result["stage"], "done")
        verify = prompt(calls, "look-carry-verify")
        for text in ("merge-base --is-ancestor " + B + " " + D, "merge-base --is-ancestor " + SHA + " " + B,
                     "rev-list --no-merges " + SHA + ".." + D, "merge-base --is-ancestor " + B + " " + SHA,
                     "rev-list --no-merges " + B + ".." + D):
            self.assertIn(text, verify)
        self.assertIn(" --from " + B + " --head " + D, prompt(calls, "look-carry"))

    def test_a_worktree_that_already_holds_the_manual_merge_carries(self):
        patch = dict(LOOK_MERGED, setup={"look": MARKED, "head": D}, verify={"head": D})
        result, calls = self.approve(patch=patch, replies=self.carries())
        self.assertEqual(result["stage"], "done")
        verify = prompt(calls, "look-carry-verify")
        for text in ("merge-base --is-ancestor " + D + " " + SHA, "merge-base --is-ancestor " + SHA + " " + D,
                     "rev-list --no-merges " + SHA + ".." + D):
            self.assertIn(text, verify)
        self.assertIn(" --from " + SHA + " --head " + D, prompt(calls, "look-carry"))

    def test_an_approval_kept_from_an_earlier_head_carries_from_that_head(self):
        replies = dict(self.carries(F), **{"look-read": {"verdict": "approved", "kept_from": F}})
        result, calls = self.approve(replies=replies)
        self.assertEqual(result["stage"], "done")
        verify = prompt(calls, "look-carry-verify")
        for text in ("merge-base --is-ancestor " + SHA + " " + F, "merge-base --is-ancestor " + F + " " + SHA,
                     "rev-list --no-merges " + F + ".." + D):
            self.assertIn(text, verify)
        self.assertIn(" --from " + F + " --head " + D, prompt(calls, "look-carry"))

    def test_a_manual_update_branch_that_changed_a_look_file_stops_for_the_owners_look(self):
        needed = {"verdict": "needed", "from": SHA, "reason": "look-files-differ", "rule": "look-files", "comment_id": None}
        result, calls = self.approve(replies={"look-carry-verify": self.BARE, "look-carry": needed})
        got = labels(calls)
        self.assertEqual(result["stage"], "awaiting-look")
        self.assertEqual(result["head"], D)
        self.assertEqual(result["cont"]["look"], {"pr": 42, "head": D})
        self.assertEqual(result["reason"], "the approval of " + SHA + " does not carry to " + D + ": look-files-differ; " + AWAIT_REASON)
        self.assertNotIn("pr", got)
        self.assertNotIn("merge", got)

    def test_a_manual_update_branch_with_a_non_merge_commit_stops_for_the_owners_look(self):
        result, calls = self.approve(replies={"look-carry-verify": dict(self.BARE, merge_only=False)})
        got = labels(calls)
        self.assertEqual(result["stage"], "awaiting-look")
        self.assertTrue(result["reason"].endswith("it adds commits that are not clean merges of dev; " + AWAIT_REASON), result["reason"])
        self.assertNotIn("look-carry", got)
        self.assertNotIn("merge", got)

    def test_a_stop_after_the_approval_was_read_never_says_it_was_not_recorded(self):
        stopped = {
            "a merge stop after a carry": (dict(self.carries(), merge=None), "merge"),
            "an unusable verification": ({"look-carry-verify": None}, "look-carry"),
            "an unexpected carry reply": ({"look-carry-verify": self.BARE, "look-carry": {"verdict": "moved"}}, "look-carry"),
        }
        for name, (replies, stage) in stopped.items():
            with self.subTest(name=name):
                result, _ = self.approve(replies=replies)
                self.assertEqual(result["stage"], stage)
                self.assertNotIn("was not recorded", result["reason"])

    def test_an_approval_read_that_failed_on_a_moved_head_never_says_it_was_not_recorded(self):
        for reply in ({"verdict": "error", "detail": "x"}, None):
            with self.subTest(reply=reply):
                result, _ = self.approve(replies={"look-read": reply})
                self.assertEqual(result["stage"], "look-approve")
                self.assertNotIn("was not recorded", result["reason"])
                self.assertIn("could not be checked", result["reason"])

    def test_a_commit_made_outside_the_delivery_is_not_recorded_as_verified(self):
        first, _ = run(patch={"setup": {"look": MARKED}})
        result, calls = self.approve(replies={"look-carry-verify": dict(self.BARE, merge_only=False)})
        self.assertEqual(result["stage"], "awaiting-look")
        self.assertEqual(result["head"], D)
        self.assertEqual(result["cont"]["verified"]["head"], first["cont"]["verified"]["head"])
        self.assertNotEqual(result["cont"]["verified"]["head"], D)
        self.assertEqual(result["cont"]["look"], {"pr": 42, "head": D})

    def test_a_worktree_that_cannot_reach_the_moved_head_asks_for_the_owners_look(self):
        stale = {"head": F, "clean": True, "merge_only": False, "results": []}
        result, calls = self.approve(replies={"look-carry-verify": stale})
        got = labels(calls)
        self.assertEqual(result["stage"], "awaiting-look")
        self.assertEqual(result["head"], D)
        self.assertTrue(result["reason"].startswith("the approval of " + SHA + " does not carry to " + D), result["reason"])
        for label in ("look-carry", "merge"):
            self.assertNotIn(label, got)
        self.assertIn("look-checks-1", got)

    def test_a_moved_head_whose_approval_is_not_recorded_stops_as_before(self):
        result, calls = self.approve(replies={"look-read": {"verdict": "needed", "kept_from": None}})
        self.assertEqual(result["stage"], "awaiting-look")
        self.assertEqual(result["reason"], "the approval of " + SHA + " was not recorded: PR #42's head is now " + D + "; " + AWAIT_REASON)
        self.assertNotIn("look-carry-verify", labels(calls))

    def test_an_unreadable_approval_read_on_a_moved_head_stops_without_asking(self):
        for reply in ({"verdict": "error", "detail": "x"}, None):
            with self.subTest(reply=reply):
                result, calls = self.approve(replies={"look-read": reply})
                got = labels(calls)
                self.assertEqual(result["stage"], "look-approve")
                self.assertTrue(result["details"].startswith("the approval of " + SHA + " could not be checked: PR #42's head is now " + D), result["details"])
                self.assertNotIn("look-carry-verify", got)
                self.assertNotIn("look-checks-1", got)

    def test_an_unmarked_or_unknown_approval_read_on_a_moved_head_stops_without_asking(self):
        for reply in ({"verdict": "unmarked", "kept_from": None}, {"verdict": "whatever", "kept_from": None}):
            with self.subTest(reply=reply):
                result, calls = self.approve(replies={"look-read": reply})
                got = labels(calls)
                self.assertEqual(result["stage"], "look-approve")
                self.assertFalse([l for l in got if l.startswith("look-checks-")], got)
                for label in ("look-carry-verify", "look-carry", "pr", "merge"):
                    self.assertNotIn(label, got)

    def test_a_live_lane_moved_head_carries_nothing(self):
        result, calls = run(args=dict(ARGS, cont=LIVE_CONT, look={"answer": "approve", "head": SHA}),
                            patch={"setup": {"look": MARKED, "head": SHA, "live_fault": DECLARED}, "look-head": {"head": D}})
        got = labels(calls)
        for label in ("look-read", "look-carry-verify", "look-carry", "merge"):
            self.assertNotIn(label, got)
        self.assertTrue(result["reason"].startswith("the approval of " + SHA + " was not recorded: PR #42's head is now " + D), result)

    def test_a_stop_after_a_moved_head_carry_keeps_the_owners_head(self):
        result, _ = self.approve(replies=dict(self.carries(), merge=None))
        self.assertEqual(result["stage"], "merge")
        self.assertEqual(result["cont"]["look"], {"pr": 42, "head": D, "approved": D, "owner": SHA})


class LookTickTest(unittest.TestCase):
    """#1186: the close-out of an approved look ticks its look marker, as step 0 of the close-out call."""

    TICK = "Run alone and exactly: look-approval tick --repo owner/repo --issue 9 --pr 42 --head " + SHA
    CLOSE_OUT = {"issue_state": "CLOSED", "branch_deleted": True, "released": True, "decision_ended": True, "notes": "ok"}

    def look_cont(self):
        result, _ = run(patch={"setup": {"look": MARKED}})
        self.assertEqual(result["stage"], "awaiting-look")
        return result["cont"]

    def approve_args(self):
        return dict(ARGS, cont=self.look_cont(), look={"answer": "approve", "head": SHA})

    def approve(self, **kw):
        return run(args=self.approve_args(), patch=RESUME, **kw)

    def test_an_approved_landing_ticks_the_look_marker_after_the_hold(self):
        result, calls = self.approve()
        got = labels(calls)
        self.assertEqual(result["stage"], "done")
        self.assertLess(got.index("hold"), got.index("close-out"))
        self.assertNotIn("look-tick", got)
        text = prompt(calls, "close-out")
        self.assertIn(self.TICK, text)
        self.assertLess(text.index(self.TICK), text.index("forge-claim release"))
        self.assertEqual(result["look_tick"], {"verdict": "ticked", "ticked": 1})

    def test_no_look_tick_without_an_approved_marked_landing(self):
        deliveries = {
            "unmarked": run(),
            "awaiting": run(patch={"setup": {"look": MARKED}}),
            "approve on unmarked": run(args=dict(ARGS, cont=LOOK_CONT, look={"answer": "approve", "head": SHA})),
        }
        for name, (result, calls) in deliveries.items():
            with self.subTest(delivery=name):
                self.assertFalse([c for c in calls if "look-approval tick" in c["prompt"]])
                self.assertNotIn("look_tick", result)

    def test_a_merged_pr_resume_of_an_approved_cont_ticks_the_look(self):
        stopped, _ = self.approve(replies={"merge": None})
        self.assertEqual(stopped["stage"], "merge")
        cont = stopped["cont"]
        self.assertEqual(cont["look"], {"pr": 42, "head": SHA, "approved": SHA})
        result, calls = run(args=dict(ARGS, cont=cont), patch={"setup": {"look": MARKED, "head": SHA, **merged(42, "c0ffee")}})
        self.assertEqual(result["stage"], "done")
        self.assertEqual(labels(calls).count("close-out"), 1)
        self.assertIn(self.TICK, prompt(calls, "close-out"))

    def test_a_look_tick_that_did_not_tick_is_logged_and_the_close_out_still_runs(self):
        out = run_out(args=self.approve_args(), replies={"close-out": dict(self.CLOSE_OUT, look_tick={"verdict": "needed"})}, patch=RESUME)
        self.assertEqual(out["result"]["stage"], "done")
        self.assertEqual(out["result"]["look_tick"]["verdict"], "needed")
        self.assertEqual(len([l for l in out["logs"] if "close-out: the look marker of issue 9 was not ticked: needed" in l]), 1)
        silent = run_out(args=self.approve_args(), replies={"close-out": self.CLOSE_OUT}, patch=RESUME)
        self.assertEqual(silent["result"]["stage"], "done")
        self.assertIsNone(silent["result"]["look_tick"])
        self.assertTrue([l for l in silent["logs"] if "was not ticked: no reply" in l])


def stale(*entries):
    """The reply of a complete look-stale read naming `entries`."""
    return {"complete": True, "stale": list(entries)}


class LookHoldTest(unittest.TestCase):
    """#1356: the hold leaves out the criterion the issue's own look-marker line names, whatever the plan reworded it to."""

    REWORDED = {"id": "AC2", "text": "Before merge, the owner judges the settings page", "kind": "human",
                "verify": {"ac": "AC2", "kind": "human", "host": "h1", "when": {"days_after": {"event": "deployed", "days": 1}},
                           "run": {"ask": "Does the settings page look right"}, "reason": "senses"},
                "lint": OK_LINT}
    LOOKED = {"verdict": "marked", "covers": ["the settings page"], "acs": ["AC2"]}
    MERGE = "c0ffee" + "0" * 34

    def deliver(self, *criteria, hold=None, look=None, close="OPEN", replies=None):
        look = look or self.LOOKED
        planned = {"plan": with_criteria(*criteria)}
        args = dict(ARGS, cont=run(patch={"setup": {"look": look}}, replies=planned)[0]["cont"],
                    look={"answer": "approve", "head": SHA})
        held = [c for c in with_criteria(*criteria)["acceptance"] if c["id"] not in look.get("acs", []) and c["kind"] != "code"]
        covering = {"v": 1, "merge": self.MERGE, "checks": [{"ac": c["id"], "kind": c["kind"]} for c in held]}
        replies = dict(planned, hold=dict(HoldTest.HOLD, **dict({"block": covering}, **(hold or {}))), **(replies or {}))
        return run(args=args, replies=replies, patch={"setup": {"look": look, "head": SHA},
                                                      "merge": {"merge_commit": self.MERGE},
                                                      "close-out": {"issue_state": close}})

    def test_an_approved_reworded_look_criterion_is_not_held(self):
        result, calls = self.deliver(self.REWORDED, close="CLOSED")
        hold = prompt(calls, "hold")
        self.assertNotIn("Before merge, the owner judges", hold)
        self.assertEqual(result["stage"], "done")
        self.assertNotIn("verify-pending run", hold)
        self.assertIn("look-approval tick", prompt(calls, "close-out"))
        self.assertEqual(result["acceptance"][-1]["id"], "AC2")

    def test_an_ordinary_human_criterion_is_still_held(self):
        ordinary = dict(HUMAN, id="AC3")
        result, calls = self.deliver(self.REWORDED, ordinary)
        self.assertEqual(result["stage"], "done")
        hold = prompt(calls, "hold")
        self.assertIn("looks right", hold)
        self.assertNotIn("Before merge, the owner judges", hold)
        self.assertEqual(hold.count("verify-pending run --host h1 --repo owner/repo --issue 9"), 1)

    def test_a_look_read_that_names_no_criterion_holds_every_human_criterion(self):
        result, calls = self.deliver(self.REWORDED, look={"verdict": "marked", "covers": ["the settings page"], "acs": []})
        self.assertEqual(result["stage"], "done")
        self.assertIn("Before merge, the owner judges", prompt(calls, "hold"))

    def awaiting(self, *criteria, look=None):
        """The cont of the awaiting-look stop of a plan made while the issue's look read was `look`."""
        result, _ = run(patch={"setup": {"look": look or self.LOOKED}}, replies={"plan": with_criteria(*criteria)})
        self.assertEqual(result["stage"], "awaiting-look")
        return result["cont"]

    def replay(self, cont, *criteria, left_out=("AC2",), read=None, replies=None, close="CLOSED"):
        """A resume of `cont` whose approved PR has already merged: a cont of an awaiting-look stop carries no approval."""
        read = read or self.LOOKED
        held = [c for c in with_criteria(*criteria)["acceptance"] if c["id"] not in left_out and c["kind"] != "code"]
        covering = {"v": 1, "merge": self.MERGE, "checks": [{"ac": c["id"], "kind": c["kind"]} for c in held]}
        replies = dict({"hold": dict(HoldTest.HOLD, block=covering)}, **(replies or {}))
        return run(args=dict(ARGS, cont=cont), replies=replies,
                   patch={"setup": {"look": read, "head": SHA, **merged(42, "c0ffee")}, "close-out": {"issue_state": close}})

    def test_a_replay_after_the_approved_pr_merged_reads_the_approval_before_the_hold(self):
        """#1356 C1: the replayed awaiting-look cont has no approved head, so the recorded approval is read against the merged head."""
        result, calls = self.replay(self.awaiting(self.REWORDED), self.REWORDED)
        self.assertEqual(result["stage"], "done")
        got = labels(calls)
        self.assertLess(got.index("look-head"), got.index("look-read"))
        self.assertLess(got.index("look-read"), got.index("hold"))
        self.assertIn("gh pr view 42 --repo owner/repo --json state,headRefOid", prompt(calls, "look-head"))
        self.assertIn(f"look-approval status --repo owner/repo --issue 9 --pr 42 --head {SHA} --merge-commit {self.MERGE}", prompt(calls, "look-read"))
        self.assertNotIn("Before merge, the owner judges", prompt(calls, "hold"))
        self.assertIn(f"look-approval tick --repo owner/repo --issue 9 --pr 42 --head {SHA} --merge-commit {self.MERGE}", prompt(calls, "close-out"))

    def test_a_replay_with_no_recorded_approval_holds_the_look_criterion_and_ticks_nothing(self):
        result, calls = self.replay(self.awaiting(self.REWORDED), self.REWORDED, close="OPEN", left_out=(),
                                    replies={"look-read": {"verdict": "needed", "kept_from": None}})
        self.assertEqual(result["stage"], "done")
        self.assertIn("Before merge, the owner judges", prompt(calls, "hold"))
        self.assertNotIn("look-approval tick", prompt(calls, "close-out"))

    def test_a_replay_whose_approval_cannot_be_read_stops_before_the_hold(self):
        for name, replies in (("error", {"look-read": {"verdict": "error", "kept_from": None}}), ("no head", {"look-head": None}),
                              ("no landing commit", {"look-head": {"head": SHA, "state": "MERGED", "merge": None}})):
            with self.subTest(case=name):
                result, calls = self.replay(self.awaiting(self.REWORDED), self.REWORDED, replies=replies)
                self.assertEqual(result["stage"], "look-approve")
                self.assertNotIn("hold", labels(calls))

    def test_a_replay_fetches_before_it_resolves_the_landing_commit(self):
        """#1356 I3: the landing commit is read against origin, so a checkout that predates the other pull request's merge is refreshed first."""
        result, calls = self.replay(self.awaiting(self.REWORDED), self.REWORDED)
        self.assertEqual(result["stage"], "done")
        head = prompt(calls, "look-head")
        self.assertIn("git -C /r fetch origin", head)
        self.assertLess(head.index("git -C /r fetch origin"), head.index("gh pr view 42"))
        self.assertLess(head.index("git -C /r fetch origin"), head.index("merge-base --is-ancestor"))

    def test_a_replay_of_an_indirect_merge_names_the_landing_commit_to_the_look_stale_read_and_the_hold(self):
        """#1356 I3: the merged PR has a null mergeCommit, so the split-child fence match and the hold name the landing commit the replay resolved."""
        result, calls = self.replay(self.awaiting(self.REWORDED), self.REWORDED)
        self.assertEqual(result["stage"], "done")
        stale_read, hold = prompt(calls, "look-stale"), prompt(calls, "hold")
        self.assertIn(f"the merge commit of PR 42 ({self.MERGE})", stale_read)
        self.assertIn(f"Merge commit: {self.MERGE}", hold)
        self.assertNotIn("read from gh pr view", stale_read + hold)
        self.assertNotIn("merge-base --is-ancestor", prompt(calls, "hold"))

    def test_a_swapped_checkbox_order_keeps_the_marker_to_plan_mapping_of_the_planning(self):
        """#1356 C2: the look checkbox and an ordinary human checkbox swapped while delivery waited; the plan's ids still name the look criterion."""
        ordinary = dict(HUMAN, id="AC3")
        cont = self.awaiting(self.REWORDED, ordinary)
        self.assertEqual(cont["look_acs"], ["AC2"])
        swapped = dict(self.LOOKED, acs=["AC3"])
        result, calls = self.replay(cont, self.REWORDED, ordinary, read=swapped, close="OPEN")
        self.assertEqual(result["stage"], "done")
        hold = prompt(calls, "hold")
        self.assertNotIn("Before merge, the owner judges", hold)
        self.assertIn("looks right", hold)

    def test_an_existing_verify_block_naming_the_look_check_is_reconciled_before_it_runs(self):
        """#1356 I1: the hold names the answered criterion and edits a posted block that still checks it; a block that still checks it stops."""
        ordinary = dict(HUMAN, id="AC3")
        result, calls = self.deliver(self.REWORDED, ordinary)
        self.assertIn("gh api --method PATCH repos/owner/repo/issues/comments/<comment id>", prompt(calls, "hold"))
        both = {"v": 1, "merge": self.MERGE, "checks": [{"ac": "AC2", "kind": "human"}, {"ac": "AC3", "kind": "human"}]}
        result, _ = self.deliver(self.REWORDED, ordinary, hold={"block": both})
        self.assertEqual((result["stage"], result["look_checks"]), ("hold", ["AC2"]))

    def test_a_marked_look_read_without_acs_is_asked_again_and_a_second_one_is_a_failed_read(self):
        """#1356 I2: a marked reply that omits acs is incomplete, never an empty list."""
        bare = dict(SETUP_OK, look={"verdict": "marked", "covers": ["the settings page"]})
        whole = dict(SETUP_OK, look=self.LOOKED)
        result, calls = run(replies={"setup": [bare, whole]})
        self.assertEqual((result["stage"], labels(calls).count("setup")), ("awaiting-look", 2))
        result, calls = run(replies={"setup": [bare, bare]})
        self.assertEqual(result["stage"], "look")
        self.assertEqual(labels(calls).count("setup"), 2)

    def test_a_landing_whose_open_issue_still_holds_an_answered_check_stops_before_the_hold(self):
        """#1356: a hold posted before the approval was read still checks the answered criterion, so the landing stops before the hold call."""
        result, calls = self.deliver(self.REWORDED, close="CLOSED", replies={"look-stale": stale({"issue": 9, "acs": ["AC2"], "results": False})})
        self.assertEqual((result["stage"], result["look_checks"]), ("hold", ["AC2"]))
        got = labels(calls)
        self.assertNotIn("hold", got)
        self.assertNotIn("close-out", got)
        self.assertLess(got.index("merge"), got.index("look-stale"))

    def test_a_stale_split_child_always_stops_and_a_stale_parent_with_an_open_criterion_is_reconciled_by_the_hold(self):
        ordinary = dict(HUMAN, id="AC3")
        child = {"look-stale": stale({"issue": 50, "acs": ["AC2"], "results": False})}
        for name, criteria in (("child, nothing held", (self.REWORDED,)), ("child, one held", (self.REWORDED, ordinary))):
            with self.subTest(case=name):
                kw = {"close": "CLOSED"} if len(criteria) == 1 else {}
                result, calls = self.deliver(*criteria, replies=child, **kw)
                self.assertEqual((result["stage"], result["look_checks"]), ("hold", ["AC2"]))
                self.assertNotIn("hold", labels(calls))
        with self.subTest(case="parent, one held"):
            result, calls = self.deliver(self.REWORDED, ordinary, replies={"look-stale": stale({"issue": 9, "acs": ["AC2"], "results": False})})
            self.assertEqual(result["stage"], "done")
            self.assertIn("hold", labels(calls))

    def test_a_stale_read_that_names_no_array_stops_before_the_hold(self):
        for name, reply in (("key omitted", {}), ("lost reply", None), ("entry without an integer issue", stale({"issue": "9", "acs": ["AC2"], "results": False})),
                            ("entry without results", stale({"issue": 9, "acs": ["AC2"]})),
                            ("a read that failed", {"complete": False, "stale": [], "detail": "timeline read failed"}),
                            ("a read that did not say", {"stale": []})):
            with self.subTest(case=name):
                result, calls = self.deliver(self.REWORDED, close="CLOSED", replies={"look-stale": reply})
                self.assertEqual(result["stage"], "hold")
                self.assertNotIn("hold", labels(calls))
                self.assertNotIn("close-out", labels(calls))

    def test_a_landing_whose_approval_answers_no_criterion_reads_no_earlier_hold(self):
        result, calls = self.deliver(self.REWORDED, look={"verdict": "marked", "covers": ["the settings page"], "acs": []})
        self.assertEqual(result["stage"], "done")
        self.assertNotIn("look-stale", labels(calls))

    def test_a_landing_with_nothing_held_reads_the_earlier_hold_and_names_no_fence_run(self):
        result, calls = self.deliver(self.REWORDED, close="CLOSED")
        self.assertEqual(result["stage"], "done")
        self.assertNotIn("verify-pending", prompt(calls, "hold"))
        stale = prompt(calls, "look-stale")
        self.assertIn("gh api repos/owner/repo/issues/9/comments --paginate", stale)
        self.assertIn("gh api repos/owner/repo/issues/9/timeline --paginate", stale)
        # #1356: AC ids are local to an issue, so a cross-referencing issue counts as a split of this one only by the merge commit its fence names.
        self.assertIn(self.MERGE, stale)

    def test_a_replay_of_a_merge_stop_whose_pr_merged_at_another_head_reads_the_approval_at_that_head(self):
        other = "e" * 40
        stopped, _ = self.deliver(self.REWORDED, close="CLOSED", replies={"merge": None})
        self.assertEqual(stopped["stage"], "merge")
        self.assertEqual(stopped["cont"]["look"]["approved"], SHA)
        with self.subTest(case="approved at another head"):
            result, calls = self.replay(stopped["cont"], self.REWORDED, replies={"look-head": {"head": other, "state": "MERGED", "merge": self.MERGE}})
            self.assertIn("look-read", labels(calls))
            self.assertIn("--head " + other, prompt(calls, "look-read"))
            self.assertEqual(result["stage"], "done")
            self.assertIn(f"look-approval tick --repo owner/repo --issue 9 --pr 42 --head {other} --merge-commit {self.MERGE}", prompt(calls, "close-out"))
        with self.subTest(case="not approved at another head"):
            result, calls = self.replay(stopped["cont"], self.REWORDED, left_out=(), close="OPEN",
                                        replies={"look-head": {"head": other, "state": "MERGED", "merge": self.MERGE},
                                                 "look-read": {"verdict": "needed", "kept_from": None}})
            self.assertEqual(result["stage"], "done")
            self.assertNotIn("look-approval tick", prompt(calls, "close-out"))
            self.assertNotIn("look-stale", labels(calls))
        with self.subTest(case="same head, recorded under the merged pull request"):
            result, calls = self.replay(stopped["cont"], self.REWORDED)
            self.assertIn("look-read", labels(calls))
            self.assertIn("--head " + SHA, prompt(calls, "close-out"))
        with self.subTest(case="same head, the carried approval is not recorded for the merged pull request"):
            # #1356 C1: the cont's approval is of this head, but the head merged under another pull request that holds none.
            result, calls = self.replay(stopped["cont"], self.REWORDED, left_out=(), close="OPEN",
                                        replies={"look-read": {"verdict": "needed", "kept_from": None}})
            self.assertEqual(result["stage"], "done")
            self.assertIn("look-read", labels(calls))
            self.assertNotIn("look-approval tick", prompt(calls, "close-out"))
            self.assertIn("Before merge, the owner judges", prompt(calls, "hold"))
            self.assertNotIn("look-stale", labels(calls))

    def test_a_hold_of_this_issue_with_recorded_results_is_not_rewritten(self):
        """#1356 I1: removing the look check changes the block's version and discards the results of the checks that stay."""
        ordinary = dict(HUMAN, id="AC3")
        for results, want in ((False, "done"), (True, "hold")):
            with self.subTest(results=results):
                result, calls = self.deliver(self.REWORDED, ordinary,
                                             replies={"look-stale": stale({"issue": 9, "acs": ["AC2"], "results": results})})
                self.assertEqual(result["stage"], want)
                self.assertEqual("hold" in labels(calls), want == "done")
                if want == "hold":
                    self.assertEqual(result["look_checks"], ["AC2"])

    def test_a_split_child_whose_fence_checks_the_answered_criterion_stops_the_landing(self):
        """#1356 I4: the child's returned fence is validated, whatever the clerk was told."""
        ordinary = dict(HUMAN, id="AC3")
        own = {"v": 1, "merge": self.MERGE, "checks": [{"ac": "AC3", "kind": "human"}]}
        both = dict(own, checks=[{"ac": "AC3", "kind": "human"}, {"ac": "AC2", "kind": "human"}])
        for name, block, want in (("only its own check", own, "done"), ("with the approved one", both, "hold")):
            with self.subTest(case=name):
                hold = {"blocks": [12], "split": [dict(HoldTest.CHILD, block=block)], "issue_state": "CLOSED",
                        "lint": None, "verify_run": None, "block": None}
                result, calls = self.deliver(self.REWORDED, ordinary, hold=hold, close="CLOSED")
                self.assertEqual(result["stage"], want)
                if want == "hold":
                    self.assertEqual(result["look_checks"], ["AC2"])
                    self.assertNotIn("close-out", labels(calls))

    def test_a_replay_whose_setup_look_read_failed_stops_before_the_hold(self):
        for name, read in (("marked without acs twice", {"verdict": "marked", "covers": ["the settings page"]}),
                           ("error", {"verdict": "error", "detail": "x"})):
            with self.subTest(case=name):
                result, calls = self.replay(self.awaiting(self.REWORDED), self.REWORDED, read=read)
                self.assertEqual(result["stage"], "look")
                self.assertNotIn("hold", labels(calls))
                self.assertNotIn("close-out", labels(calls))

    def test_a_replay_resolves_the_landing_commit_of_a_pr_whose_merge_commit_is_its_own_head(self):
        """#1356 C1: the forge records an indirectly merged PR with its head as merge commit, so a landing that is not the head is resolved for that shape too."""
        result, calls = self.replay(self.awaiting(self.REWORDED), self.REWORDED)
        self.assertEqual(result["stage"], "done")
        head = prompt(calls, "look-head")
        self.assertIn("or when its oid equals headRefOid", head)
        self.assertIn("rev-list --first-parent <headRefOid>..origin/", head)
        self.assertIn("has <headRefOid> as its first parent", head)
        # the hold is given the landing commit the replay resolved, so it resolves nothing itself
        self.assertNotIn("oid equals headRefOid", prompt(calls, "hold"))

    def test_a_head_that_landed_as_itself_is_never_named_as_its_own_landing_commit(self):
        """#1356 C1: a fast-forward landing has the head as its own landing commit, whose first parent lies inside the PR, so no base before the landing exists to judge a kept approval against: the read returns merge null and the replay stops."""
        result, calls = self.replay(self.awaiting(self.REWORDED), self.REWORDED)
        head = prompt(calls, "look-head")
        self.assertNotIn("merge commit is <headRefOid>", head)
        self.assertIn("so it landed as itself (a fast-forward): no commit before the head names the tip of dev before the landing, and the first commit that contains the head is the head's own child, never a landing commit, so return merge null and stop here", head)
        # #1356: the first-parent check does not wait for the forge's oid to equal the head: a null mergeCommit reaches the same child of the head
        self.assertIn("when the last commit of the first list has <headRefOid> as its first parent", head)
        self.assertIn("whatever mergeCommit is (null or the head's own oid)", head)
        self.assertNotIn("when the oid equals headRefOid and the last commit", head)
        self.assertIn("is the head itself and it landed as itself: return merge null and stop here", head)
        self.assertNotIn("merge commit is <headRefOid>", prompt(calls, "hold"))
        stopped, calls = self.replay(self.awaiting(self.REWORDED), self.REWORDED,
                                     replies={"look-head": {"head": SHA, "state": "MERGED", "merge": None}})
        self.assertEqual(stopped["stage"], "look-approve")
        self.assertNotIn("look-read", labels(calls))
        self.assertNotIn("hold", labels(calls))

    def test_a_fence_that_spells_the_answered_check_in_lower_case_still_stops_the_landing(self):
        """#1356 C2: the runner compares check ids upper-cased, so ac2 is the criterion AC2 for the stale read and the returned block."""
        ordinary = dict(HUMAN, id="AC3")
        result, calls = self.deliver(self.REWORDED, ordinary)
        self.assertIn("compared ignoring case", prompt(calls, "look-stale"))
        self.assertIn("an id compared ignoring case", prompt(calls, "hold"))
        child = {"look-stale": stale({"issue": 50, "acs": ["ac2"], "results": False})}
        result, calls = self.deliver(self.REWORDED, ordinary, replies=child)
        self.assertEqual((result["stage"], result["look_checks"]), ("hold", ["AC2"]))
        self.assertNotIn("hold", labels(calls))
        both = {"v": 1, "merge": self.MERGE, "checks": [{"ac": "ac2", "kind": "human"}, {"ac": "AC3", "kind": "human"}]}
        result, calls = self.deliver(self.REWORDED, ordinary, hold={"block": both})
        self.assertEqual((result["stage"], result["look_checks"]), ("hold", ["AC2"]))
        self.assertNotIn("close-out", labels(calls))
        split = {"blocks": [12], "split": [dict(HoldTest.CHILD, block=dict(both, checks=[{"ac": "AC3", "kind": "human"}, {"ac": "Ac2", "kind": "human"}]))],
                 "issue_state": "CLOSED", "lint": None, "verify_run": None, "block": None}
        result, calls = self.deliver(self.REWORDED, ordinary, hold=split, close="CLOSED")
        self.assertEqual((result["stage"], result["look_checks"]), ("hold", ["AC2"]))
        self.assertNotIn("close-out", labels(calls))

    def test_the_stale_read_counts_what_the_runner_recorded_or_asked_for_the_selected_block_by_its_trusted_markers(self):
        """#1356 I1 and I2: an owner answer to a prompt of a retained check is lost by a rewrite as a result is, and only a trusted marker of that block counts."""
        ordinary = dict(HUMAN, id="AC3")
        result, calls = self.deliver(self.REWORDED, ordinary)
        read = prompt(calls, "look-stale")
        self.assertNotIn("<!-- agent: verify-result", read)
        self.assertNotIn("<!-- agent: marker", read)
        self.assertIn("<!-- agent:KIND v1", read)
        self.assertIn("author_association OWNER or MEMBER", read)
        self.assertIn("block=<selected comment id>.<digest>", read)
        self.assertIn("a prompt to the owner for one of its checks", read)
        self.assertIn("names another block (or none) counts for nothing", read)
        self.assertIn("discard those results and the owner's pending answers", read)


LONG_BASH_TIMEOUT = ("a Bash timeout of 20 minutes (1200000 ms). Only a land acquire command that ends in --wait gets more: "
                     "the flag takes no value, so write nothing after it, and the command itself waits for up to 50 minutes and then "
                     "answers land-contended by itself, so give it a Bash timeout of 60 minutes (3600000 ms) and never run it in the background.")


def _own_red_scenario():
    return OwnRedOutsideLockTest().under_lease(RED, {"checks-3": OwnRedOutsideLockTest.GREEN}, **{"fix-ci": OwnRedOutsideLockTest.FIXED})["calls"]


def _graded_hold_scenario():
    acceptance = [{"id": "AC1", "text": "x", "kind": "code"}, {"id": "AC2", "text": "y", "kind": "evidence"}]
    return run(args=DIRECT, patch={"direct-impl": {"acceptance": acceptance},
                                   "close-out": {"issue_state": "OPEN"}})[1]


def _rules_only_revise_scenario():
    plan = with_criteria(HUMAN)
    return run(replies={"plan": plan, "plan-revise": plan, "plan-rules-revise": PlanRulesTest.REVISED,
                        "plan-review": PlanRulesTest.RULE_FINDING,
                        "plan-rules-review": PlanRulesTest.RULE_FINDING})[1]


def _sync_rebuttal_scenario():
    fix = {"start_head": "d" * 40, "commit": "d" * 40, "notes": "the finding is wrong because x"}
    return run(replies={"sync-review-1": BAD},
               patch={"land-take": {"behind": True},
                      "sync-1": ABORTED, "sync-resolve-1": {"conflicted": True, "merge_commit": "d" * 40}, "fix-sync-1": fix})[1]


def _renew_lost_resume_scenario():
    stopped, _ = run(patch={"pr": {"renew": None}})
    return run(args=dict(ARGS, cont=stopped["cont"]))[1]


def _checks_behind_scenario():
    merge = "d" * 40
    return run(replies={"checks-2": {"state": "passed", "passed": ["ci"], "head": merge}},
               patch={"land-take": {"behind": True}, "sync-1": {"merge_commit": merge}})[1]


PROMPT_SCENARIOS = {
    "happy": lambda: run()[1],
    "main-integration": lambda: run(patch={"setup": {"integration_branch": "main"}})[1],
    "resume-for-answer": lambda: run(args=dict(ARGS, cont=RESUME_FOR_ANSWER))[1],
    "head-moved": lambda: run(replies={"checks-2": {"state": "passed", "passed": ["ci"], "head": "c" * 40}}, patch={"land-take": {"behind": True}})[1],
    "renew-lost-resume": _renew_lost_resume_scenario,
    "checks-behind": _checks_behind_scenario,
    "remote-only-branch": lambda: run(patch={"setup": {"existing": dict(
        SetupIdempotenceTest.EXISTING, worktree=False, local_branch=False, dirty=False, status="")}})[1],
    "sized-plan-finding": lambda: run(args=SIZED, replies={"plan-review": {
        "verdict": "findings", "findings": [{"severity": "important", "summary": "gap"}]}})[1],
    "rule-finding": lambda: run(replies={"plan-review": PlanRulesTest.RULE_FINDING})[1],
    "final-finding": lambda: run(replies={"final-1": {
        "verdict": "findings", "findings": [{"severity": "important", "summary": "bug", "failing_input": "x"}]}})[1],
    "evidence-hold": lambda: HoldTest().ship(EVIDENCE)[1],
    "direct": lambda: run(args=DIRECT)[1],
    "fix-wave": lambda: run(replies={"final-1": FixWaveTest.FIRST})[1],
    "direct-graded-hold": _graded_hold_scenario,
    "map-findings": lambda: run(replies={"plan-review": MAP_TASK_FINDING, "review-1": MAP_TASK_FINDING})[1],
    "rules-only-revise": _rules_only_revise_scenario,
    "whitespace-only": lambda: WhitespaceCarryForwardTest.scenario(WS_ONLY)[1],
    "verify-red": lambda: run(replies={"verify": VERIFY_RED})[1],
    "sync-rebuttal": _sync_rebuttal_scenario,
    "own-red": _own_red_scenario,
    "ship-resume": lambda: run(args=dict(ARGS, cont=ship_cont()))[1],
}
_SCENARIO_CALLS = {}


def scenario_calls(name):
    """The calls of one scenario, run once per process, a failure included; callers never mutate the list."""
    if name not in _SCENARIO_CALLS:
        try:
            _SCENARIO_CALLS[name] = (PROMPT_SCENARIOS[name](), None)
        except Exception as failure:
            _SCENARIO_CALLS[name] = (None, failure)
    calls, failure = _SCENARIO_CALLS[name]
    if failure is not None:
        raise failure
    return calls


def _rows(scenario, label, origin, *phrases):
    return tuple((scenario, label, phrase, origin) for phrase in phrases)


PROMPT_PHRASES = {
    "planner": (
        *_rows("happy", "plan", "PlanTest.test_plan_stays_outside_the_tree_and_out_of_the_pr",
               "/r/.git/worktrees/w/deliver-standard/plan.md", "never commit them"),
        *_rows("sized-plan-finding", "plan", "ReviewSizingPlanTest.test_on_keeps_the_full_rubric_for_the_planner", FULL_RUBRIC),
        *_rows("sized-plan-finding", "plan-revise", "ReviewSizingPlanTest.test_on_keeps_the_full_rubric_for_the_planner", FULL_RUBRIC),
        *_rows("rule-finding", "plan", "PlanRulesTest.test_planner_and_reviewer_prompts_point_to_the_rules",
               "~/.agents/standards/acceptance-planning.md", "verify-pending lint --input",
               "--repo-root /r/.wt/w-issue-9-x --pr-branch issue-9-x", "--pr-workflow",
               f'"merge": "{SHA}"', "metric", "scripts"),
        *_rows("evidence-hold", "plan", "HoldTest.test_every_ruled_step_files_issues_through_forge_issue",
               "forge-issue create", "--blocked-by <n>", "--blocks <n>", "forge-issue link"),
        *_rows("happy", "plan", "CodeMapTest.test_the_planner_writes_the_map_in_the_plan_directory", MAP_PATH),
        *_rows("map-findings", "plan-revise", "CodeMapTest.test_plan_reviewers_reviser_and_implementers_name_the_map", MAP_PATH),
        *_rows("rules-only-revise", "plan-rules-revise", "CodeMapTest.test_the_rules_only_reviser_names_the_map", MAP_PATH),
    ),
    "implementer": (
        *_rows("happy", "impl-1", "TransientTest.test_every_forge_claim_prompt_gives_the_long_bash_timeout", LONG_BASH_TIMEOUT),
        *_rows("evidence-hold", "impl-1", "HoldTest.test_every_ruled_step_files_issues_through_forge_issue",
               "forge-issue create", "--blocked-by <n>", "--blocks <n>", "forge-issue link"),
        *_rows("direct", "direct-impl", "HoldTest.test_every_ruled_step_files_issues_through_forge_issue",
               "forge-issue create", "--blocked-by <n>", "--blocks <n>", "forge-issue link"),
        *_rows("direct", "direct-impl", "DirectLaneTest.test_direct_implementer_follows_deliver_direct_steps",
               "deliver-direct skill", "Skill tool", "Eligibility", "step 3", "steps 4 to 7",
               "/r/.wt/w-issue-9-x", "h1/session-s1"),
        *_rows("direct", "direct-impl",
               "DirectLaneTest.test_the_implementer_keeps_the_declared_verification_out_of_the_criteria",
               "Do not write the declared verification commands as an acceptance criterion: the verify step gates on them."),
        *_rows("map-findings", "impl-1", "CodeMapTest.test_plan_reviewers_reviser_and_implementers_name_the_map", MAP_PATH),
        *_rows("map-findings", "fix-1-1", "CodeMapTest.test_plan_reviewers_reviser_and_implementers_name_the_map", MAP_PATH),
        *_rows("fix-wave", "fix-wave", "KeptObligationTest.test_a_rejected_finding_needs_evidence_in_notes",
               "If a finding is wrong, explain with evidence in notes."),
        *_rows("sync-rebuttal", "fix-sync-1",
               "KeptObligationTest.test_the_sync_fix_may_not_rewrite_the_merge_and_its_rebuttal_is_checked_yourself",
               "never redo or rewrite the merge"),
        *_rows("own-red", "fix-ci", "OwnRedOutsideLockTest.test_the_diagnosis_under_the_lock_is_bounded",
               "read only the failed job log, the check details and the branch's diff, and run no build and no test before the release",
               "When the cause is in this branch's changes, or you cannot tell, release the lock before you edit any file",
               "Only when the failure clearly has no cause in the code (no commit is needed), keep the lock"),
    ),
    "reviewer": (
        *(row for label in ("plan-review", "review-1", "final-1")
          for row in _rows("happy", label, "ContractTest.test_reviewers_get_standards_hints_and_rejections",
                           "/r/docs/standards", "/r/.hints", "/r/.rej", "the-bar.md")),
        *_rows("rule-finding", "plan-review", "PlanRulesTest.test_planner_and_reviewer_prompts_point_to_the_rules",
               "~/.agents/standards/acceptance-planning.md"),
        *_rows("rule-finding", "plan-rules-review", "PlanRulesTest.test_planner_and_reviewer_prompts_point_to_the_rules",
               "~/.agents/standards/acceptance-planning.md"),
        *_rows("final-finding", "fix-wave-review", "ReviewAndVerifyTest.test_fix_reviews_cover_the_whole_fix_range",
               "diff b0..c0ffee"),
        *_rows("fix-wave", "fix-wave-review", "FixWaveTest.test_rereview_is_asked_to_classify_each_finding",
               "relation", "narrowing", "Unsure is new"),
        *_rows("map-findings", "plan-review", "CodeMapTest.test_plan_reviewers_reviser_and_implementers_name_the_map", MAP_PATH),
        *_rows("whitespace-only", "verify-fix-review-1", "KeptObligationTest.test_the_whitespace_attestation_stays_a_question",
               "Also judge whether each of its whitespace changes is insignificant:"),
        *_rows("sync-rebuttal", "fix-sync-review-1",
               "KeptObligationTest.test_the_sync_fix_may_not_rewrite_the_merge_and_its_rebuttal_is_checked_yourself",
               "Check each rebuttal against the code yourself"),
    ),
    "clerk": (
        *_rows("happy", "merge", "HappyPathTest.test_delete_branch_follows_the_contract",
               f"--merge --match-head-commit {SHA} --delete-branch"),
        *_rows("happy", "pr", "HappyPathTest.test_non_default_integration_closes_the_issue_explicitly", "Refs #9"),
        *_rows("happy", "close-out", "HappyPathTest.test_non_default_integration_closes_the_issue_explicitly",
               "gh issue close 9 --repo owner/repo", "dev is not the default branch"),
        *_rows("main-integration", "pr", "HappyPathTest.test_default_integration_uses_closes_and_still_confirms", "Closes #9"),
        *_rows("main-integration", "close-out", "HappyPathTest.test_default_integration_uses_closes_and_still_confirms",
               "gh issue close 9"),
        *(row for label in ("setup", "renew-final-review", "verify", "land-take", "merge")
          for row in _rows("happy", label, "TransientTest.test_every_forge_claim_prompt_gives_the_long_bash_timeout",
                           LONG_BASH_TIMEOUT)),
        *_rows("resume-for-answer", "owner-answer", "TransientTest.test_every_forge_claim_prompt_gives_the_long_bash_timeout",
               LONG_BASH_TIMEOUT),
        *_rows("head-moved", "land-unlock", "TransientTest.test_every_forge_claim_prompt_gives_the_long_bash_timeout",
               LONG_BASH_TIMEOUT),
        *_rows("renew-lost-resume", "acquire", "TransientTest.test_every_forge_claim_prompt_gives_the_long_bash_timeout",
               LONG_BASH_TIMEOUT),
        *_rows("checks-behind", "checks-2", "TransientTest.test_every_forge_claim_prompt_gives_the_long_bash_timeout",
               LONG_BASH_TIMEOUT),
        *_rows("remote-only-branch", "setup", "SetupIdempotenceTest.test_remote_only_branch_is_checked_out_from_origin",
               "when existing.remote_branch is true, git -C /r worktree add --no-track -b <branch> <worktree_path> origin/<branch>"),
        *_rows("happy", "pr", "PlanTest.test_plan_stays_outside_the_tree_and_out_of_the_pr",
               "Never attach or link the plan", "Acceptance (a table"),
        *_rows("happy", "verify", "ReviewAndVerifyTest.test_skip_eligibility_lists_both_sides_of_a_rename",
               "diff --no-renames --name-only"),
        *_rows("happy", "pr", "ShipTest.test_checks_wait_uses_the_required_names_rule",
               "gh api repos/owner/repo/rules/branches/dev"),
        *_rows("checks-behind", "checks-2", "ShipTest.test_checks_wait_uses_the_required_names_rule",
               "gh api repos/owner/repo/rules/branches/dev", "never treat a partial list as green"),
        *_rows("happy", "pr", "ShipFixWaveTest.test_checks_prompt_asks_for_failing_names_and_the_log_tail",
               "failing", "--log-failed"),
        *_rows("evidence-hold", "hold", "HoldTest.test_every_ruled_step_files_issues_through_forge_issue",
               "forge-issue create", "--blocked-by <n>", "--blocks <n>", "forge-issue link"),
        *_rows("direct-graded-hold", "hold", "DirectLaneTest.test_close_out_grades_the_implementer_criteria",
               "needs-verification"),
        *_rows("map-findings", "plan-codex", "CodeMapTest.test_plan_reviewers_reviser_and_implementers_name_the_map", MAP_PATH),
        *_rows("verify-red", "verify", "KeptObligationTest.test_the_verify_body_asks_for_precise_failure_summaries",
               "summarize the failing tests or errors precisely."),
        *_rows("happy", "setup", "LookStopTest.test_both_setup_prompts_read_the_look_marker",
               "look-approval marked --repo <slug> --issue 9"),
        *_rows("ship-resume", "setup", "LookStopTest.test_both_setup_prompts_read_the_look_marker",
               "look-approval marked --repo <slug> --issue 9"),
    ),
}


def row_failure(role, row, calls):
    """Why the row's call does not carry its phrase as the role's call, or None; only the last call of the label counts."""
    _, label, phrase, _ = row
    found = [c for c in calls if c["label"] == label]
    if not found:
        return f"no call labelled {label}"
    last = found[-1]
    if last["agentType"] != role:
        return f"{label} is a {last['agentType']} call, not {role}"
    if phrase not in last["prompt"]:
        return f"{label} lacks {phrase}"
    return None


class PromptPhraseTableTest(unittest.TestCase):
    """#1312: the phrases a delivery prompt must carry, one table per agent role, replacing the tests that only searched a prompt.

    A row is a phrase that one labelled call of one scenario must contain; the role is the agentType the program gives the call.
    """

    @staticmethod
    def rows_of(role):
        return PROMPT_PHRASES[role]

    def check_role(self, role):
        for row in self.rows_of(role):
            scenario, label, phrase, _ = row
            with self.subTest(scenario=scenario, label=label, phrase=phrase):
                self.assertIsNone(row_failure(role, row, scenario_calls(scenario)))

    def test_the_planner_prompts_carry_their_phrases(self):
        self.check_role("planner")

    def test_the_implementer_prompts_carry_their_phrases(self):
        self.check_role("implementer")

    def test_the_reviewer_prompts_carry_their_phrases(self):
        self.check_role("reviewer")

    def test_the_clerk_prompts_carry_their_phrases(self):
        self.check_role("clerk")

    def test_row_failure_names_each_cause(self):
        calls = [{"label": "x", "prompt": "alpha beta", "agentType": "clerk"},
                 {"label": "x", "prompt": "gamma", "agentType": "clerk"},
                 {"label": "y", "prompt": "alpha", "agentType": "reviewer"}]
        self.assertIsNone(row_failure("clerk", ("s", "x", "gamma", "o"), calls))
        self.assertEqual(row_failure("clerk", ("s", "x", "alpha", "o"), calls), "x lacks alpha")
        self.assertEqual(row_failure("clerk", ("s", "y", "alpha", "o"), calls), "y is a reviewer call, not clerk")
        self.assertEqual(row_failure("clerk", ("s", "z", "alpha", "o"), calls), "no call labelled z")
        self.assertIs(scenario_calls("happy"), scenario_calls("happy"))

    def test_a_failing_scenario_runs_once_and_every_later_row_reports_its_failure(self):
        runs = []

        def broken():
            runs.append(1)
            raise RuntimeError("harness timed out")

        with mock.patch.dict(PROMPT_SCENARIOS, {"broken": broken}), mock.patch.dict(_SCENARIO_CALLS):
            for _ in range(3):
                with self.assertRaisesRegex(RuntimeError, "harness timed out"):
                    scenario_calls("broken")
        self.assertEqual(len(runs), 1)

    def test_removing_any_phrase_fails_exactly_its_row(self):
        for role, table in PROMPT_PHRASES.items():
            for row in table:
                scenario, label, phrase, _ = row
                with self.subTest(role=role, scenario=scenario, label=label, phrase=phrase):
                    same = [r for r in table if r[0] == scenario]
                    original = scenario_calls(scenario)
                    baseline = {r for r in same if row_failure(role, r, original) is not None}
                    mutated = copy.deepcopy(original)
                    last = [c for c in mutated if c["label"] == label][-1]
                    last["prompt"] = last["prompt"].replace(phrase, "")
                    vanished = {r for r in same if r[1] == label and r[2] not in last["prompt"]}
                    failing = {r for r in same if row_failure(role, r, mutated) is not None}
                    self.assertEqual(failing, {row} | vanished | baseline)

    def test_the_table_lists_each_row_once_under_a_known_scenario(self):
        self.assertEqual(set(PROMPT_PHRASES), {"planner", "implementer", "reviewer", "clerk"})
        triples = [(r[0], r[1], r[2]) for table in PROMPT_PHRASES.values() for r in table]
        for table in PROMPT_PHRASES.values():
            self.assertEqual(len(set(table)), len(table))
        self.assertEqual(len(set(triples)), len(triples))
        used = {r[0] for table in PROMPT_PHRASES.values() for r in table}
        self.assertTrue(used <= set(PROMPT_SCENARIOS), used - set(PROMPT_SCENARIOS))
        self.assertEqual(used, set(PROMPT_SCENARIOS))


class LiveTimingTest(unittest.TestCase):
    """#1433: the pull request names the declaration, and the close-out records the time from declaration to a green head."""

    AT = "2026-11-21T12:10:00.000000+00:00"

    def whole_hour(self, green_at, state="green", head=SHA):
        fault = dict(DECLARED["fault"], at=self.AT)
        patch = {"setup": {"live_fault": dict(DECLARED, fault=fault)}}
        replies = {"live-green": {"state": state, "head": head, "green_at": green_at}}
        result, _ = run(args=ARGS, replies=replies, patch=patch)
        self.assertEqual(result["stage"], "done", result)
        return result["live_fault"]

    def test_the_done_result_records_the_time_from_declaration_to_green(self):
        out = run_out(args=ARGS, patch=LIVE_PATCH)
        self.assertEqual(out["result"]["stage"], "done")
        member = out["result"]["live_fault"]
        for key, value in (("id", 5), ("sprint_id", "0123456789abcdef"), ("issue", 9), ("pr", 42),
                           ("declared_at", "2026-11-21T12:10:00.123456+00:00"),
                           ("green_at", "2026-11-21T12:52:30Z"), ("within_hour", True)):
            self.assertEqual(member[key], value, key)
        self.assertAlmostEqual(member["seconds"], 2549.877, places=3)
        self.assertTrue([l for l in out["logs"] if l.startswith(
            "live fault 5: declared 2026-11-21T12:10:00.123456+00:00, green 2026-11-21T12:52:30Z:")], out["logs"])
        names = labels(out["calls"])
        self.assertLess(names.index("close-out"), names.index("live-green"))
        self.assertIn("pr-green --repo owner/repo --pr 42", prompt(out["calls"], "live-green"))

    def test_exactly_one_hour_is_within_and_one_second_more_is_not(self):
        exact = self.whole_hour("2026-11-21T13:10:00Z")
        self.assertEqual(exact["seconds"], 3600)
        self.assertIs(exact["within_hour"], True)
        over = self.whole_hour("2026-11-21T13:10:01Z")
        self.assertEqual(over["seconds"], 3601)
        self.assertIs(over["within_hour"], False)

    def test_a_microsecond_decides_the_hour(self):
        for green_at, seconds, within in (("2026-11-21T13:10:00.000001Z", 3600.000001, False),
                                          ("2026-11-21T13:09:59.999999Z", 3599.999999, True),
                                          ("2026-11-21T13:10:00.000000Z", 3600, True)):
            with self.subTest(green_at=green_at):
                member = self.whole_hour(green_at)
                self.assertAlmostEqual(member["seconds"], seconds, places=6)
                self.assertIs(member["within_hour"], within)

    def test_a_green_time_before_the_declaration_is_null(self):
        member = self.whole_hour("2026-11-21T11:00:00Z")
        self.assertIsNone(member["seconds"])
        self.assertIs(member["within_hour"], False)

    def test_a_failed_or_pending_head_records_no_green_time(self):
        for state, head in (("failed", SHA), ("pending", SHA), ("green", "e" * 40)):
            with self.subTest(state=state, head=head):
                member = self.whole_hour(None if state != "green" else "2026-11-21T12:52:30Z", state, head)
                self.assertIsNone(member["green_at"])
                self.assertIsNone(member["seconds"])

    def test_an_unread_green_time_records_null_and_lands(self):
        for reply in (None, "throw"):
            with self.subTest(reply=reply):
                result, _ = run(args=ARGS, replies={"live-green": reply}, patch=LIVE_PATCH)
                self.assertEqual(result["stage"], "done")
                self.assertIsNone(result["live_fault"]["seconds"])
                self.assertNotIn("live-green", result.get("dead_agents", []))

    def test_the_pr_body_names_the_declaration(self):
        result, calls = run(args=ARGS, patch=LIVE_PATCH)
        self.assertIn("Live-fault lane: declaration 5 of sprint 0123456789abcdef for issue #9, declared "
                      "2026-11-21T12:10:00.123456+00:00", prompt(calls, "pr"))
        for args in (dict(ARGS, lane="direct"), ARGS):
            with self.subTest(lane=args.get("lane")):
                result, calls = run(args=args)
                self.assertEqual(result["stage"], "done")
                self.assertNotIn("Live-fault lane", prompt(calls, "pr"))
                self.assertNotIn("live-green", labels(calls))
                self.assertNotIn("live_fault", result)

    def test_a_merged_replay_after_withdrawal_records_the_time(self):
        stopped, _ = run(args=ARGS, replies={"close-out": None}, patch=LIVE_PATCH)
        self.assertEqual(stopped["stage"], "close-out")
        for verdict in ("none", "no-sprint"):
            with self.subTest(verdict=verdict):
                result, calls = run(args=dict(ARGS, cont=stopped["cont"]),
                                    patch={"setup": dict(merged(42, SHA), live_fault={"verdict": verdict})})
                self.assertEqual(result["stage"], "done", result)
                self.assertIn("close-out", labels(calls))
                self.assertIn("live-green", labels(calls))
                self.assertEqual(result["live_fault"]["id"], 5)


if __name__ == "__main__":
    unittest.main()
