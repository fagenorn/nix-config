"""deliver-batch.js control flow against stub agents and a stub child workflow (#636).

The Workflow program runs under node with stub agent(), workflow(), parallel(), pipeline() and
phase(); each scenario fixes some replies and asserts the table or the call sequence.
Run: just agent-workflow-tests
"""

from __future__ import annotations

import itertools
import json
from pathlib import Path
import re
import shutil
import subprocess
import unittest

REPO_ROOT = Path(__file__).parents[4]
PROGRAM = REPO_ROOT / "home/common/claude-code/skills/deliver-standard/deliver-batch.js"
HARNESS = Path(__file__).with_name("deliver_batch_harness.mjs")
SHA = "a" * 40
ARGS = {"repo_root": "/r", "batch_id": "b1", "child_script": "/s/deliver-standard.js", "issues": [1]}
HOLDER = "h1/b1"
ISSUE_BRANCH_ARGV = re.compile(r"\bissue-branch --repo-root (\S+) --issue (\d+)\b")


HELD = {"claim": {"verdict": "held_by", "by": HOLDER}}


PROGRAM_AGENT_TYPES = {"clerk", "planner", "implementer", "reviewer", "reviewer-lite"}


def untyped(calls):
    """Labels of agent calls that would run on the default tool set (#734)."""
    return [c["label"] for c in calls
            if c.get("kind", "agent") == "agent" and c["agentType"] not in PROGRAM_AGENT_TYPES]


def run_full(args=None, replies=None, patch=None, children=None, turns=None, delays=None):
    node = shutil.which("node")
    if node is None:
        raise AssertionError("node is not on PATH; the deliver-batch scenarios need it")
    scenario = {"args": ARGS if args is None else args, "replies": replies or {},
                "patch": patch or {}, "children": children or {}, "turns": turns or {}, "delays": delays or {}}
    done = subprocess.run([node, str(HARNESS), str(PROGRAM)], input=json.dumps(scenario),
                          capture_output=True, text=True, timeout=60, check=False)
    if done.returncode != 0:
        raise AssertionError(f"harness failed: {done.stderr}")
    out = json.loads(done.stdout)
    bad = untyped(out["calls"])
    if bad:
        raise AssertionError(f"agent calls without a program agentType: {bad}")
    return out


def run(args=None, replies=None, patch=None, children=None, turns=None):
    out = run_full(args=args, replies=replies, patch=patch, children=children, turns=turns)
    return out["result"], out["calls"], out["max_active"]


AMEND_EDIT = {"file": "task-2.md", "find": "old rule", "replace": "new rule"}


def reviewed(n):
    """A valid deliver-standard continuation whose plan is reviewed and whose first task is done."""
    return {"setup": {"ok": True, "holder": "h1/b1", "branch": f"issue-{n}-x", "worktree": f"/r/.wt/w-issue-{n}-x",
                      "worktree_path": f"/r/.wt/w-issue-{n}-x", "plan_dir": "/g"},
            "lane": "standard",
            "plan": {"status": "planned", "plan_root": "/g/plan.md",
                     "acceptance": [{"id": "AC1", "text": "works", "kind": "code"}],
                     "tasks": [{"n": 1, "title": "t1", "file": "/g/task-1.md", "risk": "standard"},
                               {"n": 2, "title": "t2", "file": "/g/task-2.md", "risk": "standard"}]},
            "plan_reviewed": True, "done": [{"n": 1, "commit": "c1"}], "fix_waves": 0}


def verified_cont(n):
    """A reviewed continuation that records a passed verification: no review or verify is owed on it."""
    return dict(reviewed(n), verified={"head": "a" * 40, "results": [], "contract": "{}"})


def kept(n):
    """A continuation that still plans ahead: its plan is unreviewed and nothing is done."""
    return dict(reviewed(n), plan_reviewed=False, done=[])


# The members of a cont's setup the relaunch keeps: what a resumed child reads from cont.setup, and the fresh setup's facts.
SETUP_KEPT = ("holder", "branch", "worktree", "worktree_path", "base_sha", "plan_dir", "details")


def slim(cont):
    """The cont as a relaunch forwards it: its setup holds only the kept members, every other member is as it came."""
    return dict(cont, setup={k: v for k, v in cont["setup"].items() if k in SETUP_KEPT})


def closing(pr):
    """Facts naming a merged PR that closes the issue."""
    return {"merged_refs": [{"number": pr, "closes": True}]}


def landing(pr):
    """Facts naming merged PR `pr` that closes the issue, and listing it as landed on the cont branch."""
    return {**closing(pr), "landed": [{"number": pr, "commits": []}]}


def labels(calls):
    return [c["label"] for c in calls]


def of(calls, n):
    """The labels of issue n's calls, in order: the first number in a label is its issue."""
    found = []
    for c in calls:
        match = re.search(r"-(\d+)(?:-|$)", c["label"])
        if match and int(match.group(1)) == n:
            found.append(c["label"])
    return found


def prompt(calls, label):
    found = [c["prompt"] for c in calls if c["label"] == label and c["kind"] == "agent"]
    if not found:
        raise AssertionError(f"no agent call labelled {label}: {labels(calls)}")
    return found[-1]


def child(calls, n):
    found = [c for c in calls if c["label"] == f"child-{n}"]
    if not found:
        raise AssertionError(f"no child for issue {n}: {labels(calls)}")
    return found[-1]


def row(result, issue):
    return next(r for r in result["table"] if r["issue"] == issue)


def without(mapping, key):
    return {k: v for k, v in mapping.items() if k != key}


class ArgsTest(unittest.TestCase):
    def test_args_are_checked_before_any_agent(self):
        bad = [without(ARGS, "batch_id"), dict(ARGS, batch_id="b 1"), without(ARGS, "child_script"),
               without(ARGS, "repo_root"), without(ARGS, "issues"), dict(ARGS, label="ready"),
               dict(ARGS, issues=[]), dict(ARGS, issues=[1, 1]), dict(ARGS, issues=[0]),
               dict(ARGS, decisions={"1": ""}), dict(ARGS, unattended="yes"), dict(ARGS, conts={"2": {"setup": {}}}),
               dict(ARGS, conts={"1": "x"}),
               dict(without(ARGS, "issues"), label="ready", conts={"1": {"setup": {}}})]
        for args in bad:
            with self.subTest(args=args):
                result, calls, _ = run(args=args)
                self.assertEqual(result["stage"], "args")
                self.assertEqual(calls, [])

    def test_missing_contract_field_stops_without_a_default(self):
        for field in ("max_parallel", "slug", "integration_branch", "merge_strategy", "host"):
            with self.subTest(field=field):
                result, calls, _ = run(patch={"setup": {field: None}})
                self.assertEqual((result["stage"], result["missing"]), ("setup", [field]))
                self.assertEqual(labels(calls), ["setup"])

    def test_setup_reads_the_contract_and_max_parallel(self):
        _, calls, _ = run()
        text = prompt(calls, "setup")
        self.assertIn("resolve-project resolve --repo-root /r", text)
        self.assertIn("bindings.workflow.orchestration.max_parallel", text)
        self.assertIn("bindings.vcs.merge.required_checks", text)

    def test_declared_required_checks_are_optional_but_checked(self):
        result, _, _ = run(patch={"setup": {"required_checks": None}, "facts-1": {"state": "CLOSED"}})
        self.assertEqual(result["stage"], "done")
        for bad in ([], ["ci", "ci"], [""], "ci"):
            with self.subTest(bad=bad):
                result, calls, _ = run(patch={"setup": {"required_checks": bad}})
                self.assertEqual((result["stage"], result["invalid"]), ("setup", "required_checks"))
                self.assertEqual(labels(calls), ["setup"])

    def test_setup_reply_without_required_checks_stops_the_run(self):
        reply = {"ok": True, "host": "h1", "slug": "owner/repo", "integration_branch": "dev", "default_branch": "main",
                 "merge_strategy": "merge", "delete_branch": True, "unset_env": [], "max_parallel": 2}
        result, calls, _ = run(replies={"setup": reply})
        self.assertEqual((result["stage"], result["invalid"]), ("setup", "required_checks"))
        self.assertEqual(labels(calls), ["setup"])

    def test_label_mode_issue_list_runs_after_the_credential_unset(self):
        args = dict(without(ARGS, "issues"), label="agent:ready")
        _, calls, _ = run(args=args, patch={"setup": {"issues": []}})
        text = prompt(calls, "setup")
        step = next(line for line in text.splitlines() if line.startswith("3."))
        self.assertIn("gh issue list --repo <slug> --label agent:ready", step)
        self.assertIn("bindings.tracker.credential_env.unset_before_invocation", step)
        self.assertRegex(step, r"after unsetting exactly the names in")

    def test_label_selects_the_issues_setup_lists(self):
        args = dict(without(ARGS, "issues"), label="agent:ready")
        result, calls, _ = run(args=args, patch={"setup": {"issues": [4, 2, 4]},
                                                 "facts-2": {"state": "CLOSED"}, "facts-4": {"state": "CLOSED"}})
        self.assertIn("--label agent:ready", prompt(calls, "setup"))
        self.assertEqual([r["issue"] for r in result["table"]], [2, 4])


class ReviewSizingTest(unittest.TestCase):
    """#747: review_sizing is checked, then passed to every child and the relaunch only when on."""

    STOP = {"stage": "task", "task": {"n": 2}, "cont": {"setup": {}}}

    def test_review_sizing_must_be_a_boolean(self):
        for bad in ("yes", 1, None):
            with self.subTest(bad=bad):
                result, calls, _ = run(args=dict(ARGS, review_sizing=bad))
                self.assertEqual(result, {"stage": "args", "error": "review_sizing must be a boolean"})
                self.assertEqual(calls, [])

    def test_off_passes_nothing(self):
        for args in (ARGS, dict(ARGS, review_sizing=False)):
            with self.subTest(args=args):
                result, calls, _ = run(args=args, children={"1": self.STOP})
                self.assertEqual(child(calls, 1)["args"],
                                 {"repo_root": "/r", "issue": 1, "batch_id": "b1", "mode": "plan", "lane": "standard"})
                self.assertNotIn("review_sizing", result["relaunch"])

    def test_on_reaches_the_child_the_relaunch_and_the_resumed_child(self):
        result, calls, _ = run(args=dict(ARGS, review_sizing=True), children={"1": self.STOP})
        self.assertEqual(child(calls, 1)["args"], {"repo_root": "/r", "issue": 1, "batch_id": "b1", "mode": "plan",
                                                   "lane": "standard", "review_sizing": True})
        self.assertIs(result["relaunch"]["review_sizing"], True)
        _, calls, _ = run(args=result["relaunch"], patch={"facts-1": {"claim": {"verdict": "held_by", "by": HOLDER}}})
        self.assertEqual(child(calls, 1)["args"], {"repo_root": "/r", "issue": 1, "batch_id": "b1", "mode": "ready",
                                                   "cont": {"setup": {}}, "review_sizing": True})

    def test_on_reaches_the_standard_rerun_of_an_ineligible_direct_child(self):
        ineligible = {"stage": "ineligible", "cont": {"setup": {}, "lane": "direct"}}
        _, calls, _ = run(args=dict(ARGS, review_sizing=True), patch={"facts-1": {"lane": "direct", "why": "small"}},
                          children={"1": [ineligible, self.STOP]})
        runs = [c for c in calls if c["label"] == "child-1"]
        self.assertEqual(len(runs), 2)
        for c in runs:
            self.assertIs(c["args"]["review_sizing"], True)


class IntakeTest(unittest.TestCase):
    SKIPS = [({"state": "CLOSED"}, "closed"), ({"labels": ["needs-verification"]}, "needs-verification"),
             ({"labels": ["parked"]}, "parked"), ({"labels": ["agent:human-required"]}, "human-required"),
             (closing(5), "duplicate"),
             ({"claim": {"verdict": "held_by", "by": "h2/b9"}}, "claimed-elsewhere"),
             ({"claim": {"verdict": "stale", "by": "h2/b9"}}, "stale-claim"),
             ({"blockers": [{"issue": 50, "state": "OPEN"}]}, "blocked")]

    def test_each_skip_is_decided_in_js_with_no_lane_agent_or_claim(self):
        for facts, outcome in self.SKIPS:
            with self.subTest(outcome=outcome):
                result, calls, _ = run(patch={"facts-1": facts})
                self.assertEqual(row(result, 1)["outcome"], outcome)
                # A closed issue still runs the release that finishes any cleanup a failed one left (#714): no lane, no claim.
                self.assertEqual(labels(calls), ["setup", "facts-1"] + (["release-1"] if outcome == "closed" else []))

    def test_skip_rows_name_their_evidence(self):
        result, _, _ = run(patch={"facts-1": closing(5)})
        self.assertEqual(row(result, 1)["pr"], 5)
        result, _, _ = run(patch={"facts-1": {"claim": {"verdict": "stale", "by": "h2/b9"}}})
        self.assertEqual(row(result, 1)["by"], "h2/b9")
        result, _, _ = run(patch={"facts-1": {"blockers": [{"issue": 51, "state": "OPEN"},
                                                           {"issue": 50, "state": "OPEN"}]}})
        self.assertEqual(row(result, 1)["blocker"], 50)

    def test_own_claim_and_a_closed_outside_blocker_stay_eligible(self):
        for facts in ({"claim": {"verdict": "held_by", "by": HOLDER}},
                      {"claim": {"verdict": "stale", "by": HOLDER}},
                      {"blockers": [{"issue": 50, "state": "CLOSED"}]}):
            with self.subTest(facts=facts):
                _, calls, _ = run(patch={"facts-1": facts})
                self.assertIn("acquire-1", labels(calls))

    def test_a_blocker_inside_the_batch_does_not_skip_the_issue(self):
        _, calls, _ = run(args=dict(ARGS, issues=[1, 2]),
                          patch={"facts-1": {"blockers": [{"issue": 2, "state": "OPEN"}]}})
        self.assertIn("acquire-1", labels(calls))

    def test_facts_agent_reads_claim_status_and_the_decision_marker(self):
        _, calls, _ = run()
        text = prompt(calls, "facts-1")
        self.assertIn(f"forge-claim status --repo owner/repo --issue 1 --holder {HOLDER}", text)
        self.assertIn("forge-claim owner-action status --repo owner/repo --issue 1 --reason decision", text)

    def test_every_facts_agent_answers_before_any_acquire(self):
        _, calls, _ = run(args=dict(ARGS, issues=[1, 2, 3]))
        ls = labels(calls)
        self.assertLess(max(ls.index(f"facts-{n}") for n in (1, 2, 3)),
                        min(ls.index(f"acquire-{n}") for n in (1, 2, 3)))
        self.assertEqual([c["facts_pending"] for c in calls if c["label"].startswith("acquire-")], [0, 0, 0])

    def test_needs_design_is_reported_and_not_claimed(self):
        result, calls, _ = run(patch={"facts-1": {"lane": "needs-design", "why": "no criteria"}})
        self.assertEqual(row(result, 1)["outcome"], "needs-design")
        self.assertNotIn("acquire-1", labels(calls))

    def test_an_intake_routing_keeps_its_reason_in_the_row_and_the_log(self):
        """#932: the needs-design row carries intake's why as one capped line, and the log line prints it."""
        out = run_full(patch={"facts-1": {"lane": "needs-design", "why": "no criteria:\n  the issue names no check"}})
        self.assertEqual(row(out["result"], 1),
                         {"issue": 1, "outcome": "needs-design", "lane": "needs-design",
                          "reason": "no criteria: the issue names no check"})
        self.assertIn("#1: needs-design (no criteria: the issue names no check)", out["logs"])
        out = run_full(patch={"facts-1": {"lane": "needs-design", "why": "w" * 400}})
        self.assertEqual(row(out["result"], 1)["reason"], "w" * 297 + "...")
        out = run_full(patch={"facts-1": {"lane": "needs-design", "why": " "}})
        self.assertNotIn("reason", row(out["result"], 1))
        self.assertIn("#1: needs-design", out["logs"])
        # A readopted issue routed at its unaccepted PR keeps the reason the same way.
        out = run_full(patch={"facts-1": {"open_pr": OPEN_PR, "lane": "needs-design", "why": "an open design decision"}},
                       replies={"readopt-1": {"ok": False, "reason": "unaccepted"}})
        self.assertEqual(row(out["result"], 1)["reason"], "an open design decision")

    def test_table_keeps_the_given_issue_order(self):
        result, _, _ = run(args=dict(ARGS, issues=[3, 1, 2]), patch={"facts-3": {"state": "CLOSED"}})
        self.assertEqual([r["issue"] for r in result["table"]], [3, 1, 2])

    def test_relaunch_names_the_same_batch_and_only_unfinished_issues(self):
        result, _, _ = run(args=dict(ARGS, issues=[1, 2], decisions={"2": "Use the flag."}),
                           patch={"facts-1": {"state": "CLOSED"},
                                  "facts-2": {"blockers": [{"issue": 50, "state": "OPEN"}]}})
        self.assertEqual(result["stage"], "done")
        self.assertEqual(result["relaunch"], {"repo_root": "/r", "batch_id": "b1", "child_script": "/s/deliver-standard.js",
                                              "issues": [2], "decisions": {"2": "Use the flag."}})

    def test_relaunch_forwards_given_conts_of_unfinished_issues_only(self):
        cont = {"setup": {"branch": "issue-2-x"}, "lane": "standard", "partial": 2}
        result, _, _ = run(args=dict(ARGS, issues=[1, 2], conts={"1": {"setup": {}}, "2": cont}),
                           patch={"facts-1": {"state": "CLOSED"},
                                  "facts-2": {"blockers": [{"issue": 50, "state": "OPEN"}]}})
        self.assertEqual(result["relaunch"]["conts"], {"2": cont})

    def test_no_relaunch_when_every_issue_is_final(self):
        result, _, _ = run(patch={"facts-1": {"state": "CLOSED"}})
        self.assertIsNone(result["relaunch"])


QS = [{"question": "Which flag?", "options": ["Use the flag.", "Drop the flag."]}]
QUESTION = {"stage": "plan", "needs_user": QS, "cont": {"setup": {}}}
OPEN = {"verdict": "open", "comment_id": 99, "decisions": "",
        "questions": [dict(QS[0], chosen=None, comment_id=99)]}
ANSWERED = dict(OPEN, verdict="answered", decisions="Which flag? Chosen: Use the flag.",
                questions=[dict(QS[0], chosen="Use the flag.", comment_id=99)])


FIXED = {"commit": "f" * 40, "evidence": "git grep -F 'boom' finds nothing at origin/dev; ffff removed it"}


FACTS_NO_LANE = {"state": "OPEN", "labels": [], "title": "t", "branch": "issue-1-x",
                 "claim": {"verdict": "free", "by": None}, "merged_refs": [], "open_pr": None,
                 "native": {"verdict": "read", "blocked_by": []}, "blockers": [],
                 "decision": {"verdict": "none", "comment_id": None, "questions": []}}
UNACCEPTED = {"ok": False, "reason": "unaccepted"}
NO_LANE = "facts-1 returned no lane"


class IntakeLaneTest(unittest.TestCase):
    """#745: facts-n answers the lane; no separate lane agent runs."""

    def test_facts_answers_the_lane_and_no_lane_agent_runs(self):
        _, calls, _ = run(patch={"facts-1": {"lane": "direct", "why": "small"}})
        self.assertFalse([l for l in labels(calls) if l.startswith("lane-")])
        self.assertEqual(child(calls, 1)["args"]["lane"], "direct")
        text = prompt(calls, "facts-1")
        self.assertIn("gh issue view 1 --repo owner/repo --json state,labels,title,body,createdAt,comments", text)
        self.assertIn("deliver-direct", text)
        facts = next(c for c in calls if c["label"] == "facts-1")
        self.assertEqual((facts["agentType"], facts["model"], facts["effort"]), ("clerk", "sonnet", "medium"))
        self.assertEqual(facts["schema"]["properties"]["lane"]["enum"], ["direct", "standard", "needs-design"])
        self.assertIn("lane", facts["schema"]["required"])

    def test_a_facts_reply_without_lane_is_a_stopped_row(self):
        cases = ({"patch": {"facts-1": {"lane": None}}}, {"patch": {"facts-1": {"lane": "fast"}}},
                 {"replies": {"facts-1": FACTS_NO_LANE}})
        for case in cases:
            with self.subTest(case=case):
                result, calls, _ = run(**case)
                self.assertEqual(result["stage"], "done")
                self.assertEqual(row(result, 1), {"issue": 1, "outcome": "stopped", "reason": NO_LANE})
                self.assertNotIn("acquire-1", labels(calls))
                self.assertNotIn("child-1", labels(calls))
                self.assertEqual(result["relaunch"]["issues"], [1])

    def test_a_missing_lane_after_an_unaccepted_readopt_stops_and_keeps_the_claim(self):
        result, calls, _ = run(patch={"facts-1": {"open_pr": OPEN_PR, "lane": None}},
                               replies={"readopt-1": UNACCEPTED})
        self.assertEqual(result["stage"], "done")
        self.assertEqual(row(result, 1), {"issue": 1, "outcome": "stopped", "reason": NO_LANE})
        ls = labels(calls)
        self.assertLess(ls.index("acquire-1"), ls.index("readopt-1"))
        self.assertNotIn("child-1", ls)
        self.assertNotIn("release-1", ls)
        self.assertEqual(result["relaunch"]["issues"], [1])

    def test_a_continuation_and_an_accepted_readopt_never_read_the_lane(self):
        cont = {"setup": {"holder": HOLDER, "branch": "issue-1-x"}, "lane": "direct", "plan": None,
                "done": [], "partial": 1}
        own = {"claim": {"verdict": "held_by", "by": HOLDER}, "lane": None}
        result, calls, _ = run(args=dict(ARGS, conts={"1": cont}), patch={"facts-1": own})
        self.assertIn("acquire-1", labels(calls))
        self.assertEqual(child(calls, 1)["args"]["cont"], cont)
        self.assertNotEqual(row(result, 1).get("detail"), NO_LANE)
        result, calls, _ = run(patch={"facts-1": dict(own, open_pr=OPEN_PR)})
        self.assertIn("acquire-1", labels(calls))
        self.assertEqual(row(result, 1)["outcome"], "landed")

    def test_a_closed_issue_without_lane_keeps_its_final_row(self):
        result, _, _ = run(patch={"facts-1": {"state": "CLOSED", "lane": None}})
        self.assertEqual(row(result, 1)["outcome"], "closed")


class AlreadyFixedTest(unittest.TestCase):
    def test_already_fixed_symptom_skips_lane_claim_and_child(self):
        result, calls, _ = run(patch={"facts-1": {"already_fixed": FIXED}})
        self.assertEqual(row(result, 1), {"issue": 1, "outcome": "already-fixed",
                                          "commit": FIXED["commit"], "evidence": FIXED["evidence"]})
        self.assertEqual(labels(calls), ["setup", "facts-1"])
        self.assertEqual(result["owner_actions"], [{"issue": 1, "reason": "already-fixed", "commit": FIXED["commit"]}])
        self.assertIsNone(result["relaunch"])
        self.assertFalse([c["label"] for c in calls if "gh issue close" in c.get("prompt", "")])

    def test_facts_agent_checks_the_symptom_at_origin_of_the_integration_branch(self):
        _, calls, _ = run()
        text = prompt(calls, "facts-1")
        self.assertIn("createdAt", text)
        self.assertIn("git -C /r grep -n -F", text)
        self.assertIn("origin/dev", text)
        self.assertIn("git -C /r log origin/dev -S", text)
        self.assertIn("--since=", text)
        self.assertIn("already_fixed", text)

    def test_a_continued_or_own_claimed_issue_is_never_already_fixed(self):
        for args, facts in ((dict(ARGS, conts={"1": {"setup": {}}}), {"already_fixed": FIXED}),
                            (ARGS, {"already_fixed": FIXED, "claim": {"verdict": "held_by", "by": HOLDER}})):
            with self.subTest(facts=facts, args=args):
                result, calls, _ = run(args=args, patch={"facts-1": facts})
                self.assertNotEqual(row(result, 1)["outcome"], "already-fixed")
                self.assertIn("child-1", labels(calls))

    def test_a_null_or_commitless_already_fixed_stays_eligible(self):
        for fixed in (None, {"commit": "", "evidence": "x"}):
            with self.subTest(fixed=fixed):
                _, calls, _ = run(patch={"facts-1": {"already_fixed": fixed}})
                self.assertIn("acquire-1", labels(calls))

    def test_a_failed_claim_lookup_is_never_already_fixed(self):
        result, calls, _ = run(patch={"facts-1": {"already_fixed": FIXED, "claim": {"verdict": "error", "by": None}}})
        self.assertEqual(row(result, 1), {"issue": 1, "outcome": "stopped", "reason": "claim status"})
        self.assertEqual(result["relaunch"]["issues"], [1])
        self.assertEqual(result["owner_actions"], [])
        self.assertNotIn("acquire-1", labels(calls))

    def test_a_merged_pr_wins_over_already_fixed(self):
        result, _, _ = run(patch={"facts-1": dict(closing(5), already_fixed=FIXED)})
        self.assertEqual(row(result, 1)["outcome"], "duplicate")


class ClaimTest(unittest.TestCase):
    def test_a_waiting_issue_is_not_claimed_until_admitted(self):
        _, calls, active = run(args=dict(ARGS, issues=[1, 2]), patch={"setup": {"max_parallel": 1}})
        ls = labels(calls)
        self.assertLess(ls.index("child-1"), ls.index("acquire-2"))
        self.assertLess(ls.index("acquire-1"), ls.index("child-1"))
        self.assertEqual(active, 1)

    def test_children_run_up_to_max_parallel(self):
        _, _, active = run(args=dict(ARGS, issues=[1, 2, 3]))
        self.assertEqual(active, 2)

    def test_acquire_names_the_batch_holder_and_branch(self):
        _, calls, _ = run()
        self.assertIn(f"forge-claim acquire --repo owner/repo --issue 1 --holder {HOLDER} --branch issue-1-x",
                      prompt(calls, "acquire-1"))

    def test_claim_lost_to_another_host_skips_the_child(self):
        for verdict in ("held_by", "lost_to"):
            with self.subTest(verdict=verdict):
                result, calls, _ = run(replies={"acquire-1": {"verdict": verdict, "by": "h2/b9"}})
                self.assertEqual((row(result, 1)["outcome"], row(result, 1)["by"]), ("claim-lost", "h2/b9"))
                self.assertNotIn("child-1", labels(calls))

    def test_child_runs_ready_with_lane_batch_and_script(self):
        _, calls, _ = run(patch={"facts-1": {"lane": "direct", "why": "small"}})
        c = child(calls, 1)
        self.assertEqual(c["script"], "/s/deliver-standard.js")
        self.assertEqual(c["args"], {"repo_root": "/r", "issue": 1, "batch_id": "b1", "mode": "ready", "lane": "direct"})

    def test_child_stop_without_cont_releases_the_claim(self):
        result, calls, _ = run(children={"1": {"stage": "setup", "result": {"ok": False, "reason": "no-longer-applies"}}})
        self.assertEqual((row(result, 1)["outcome"], row(result, 1)["stage"]), ("stopped", "setup"))
        self.assertIn(f"forge-claim release --repo owner/repo --issue 1 --holder {HOLDER} --reason skipped",
                      prompt(calls, "release-1"))

    def test_child_stop_with_cont_keeps_the_claim_for_a_relaunch(self):
        result, calls, _ = run(children={"1": {"stage": "task", "task": {"n": 2}, "cont": {"setup": {}}}})
        self.assertEqual((row(result, 1)["outcome"], row(result, 1)["stage"]), ("stopped", "task"))
        self.assertNotIn("release-1", labels(calls))
        self.assertEqual(result["relaunch"]["issues"], [1])
        self.assertEqual(result["relaunch"]["conts"], {"1": {"setup": {}}})

    def test_a_direct_lane_child_that_finds_the_issue_ineligible_is_rerun_in_the_standard_lane(self):
        ineligible = {"stage": "ineligible", "impl": {"status": "blocked", "ineligible": True},
                      "cont": {"setup": {}, "lane": "direct"}}
        ready = {"stage": "ready", "head": SHA, "branch": "issue-1-x", "worktree": "/r/.wt/w-issue-1-x", "verify": [],
                 "tasks": [{"n": 1}], "acceptance": [{"id": "AC1", "text": "works", "kind": "code"}],
                 "cont": {"setup": {"holder": HOLDER}, "lane": "standard"}}
        result, calls, _ = run(patch={"facts-1": {"lane": "direct", "why": "small"}}, children={"1": [ineligible, ready]})
        runs = [c for c in calls if c["label"] == "child-1"]
        self.assertEqual(len(runs), 2)
        self.assertEqual(runs[0]["args"]["lane"], "direct")
        self.assertEqual(runs[1]["args"], {"repo_root": "/r", "issue": 1, "batch_id": "b1", "mode": "ready", "lane": "standard"})
        self.assertEqual(row(result, 1)["outcome"], "landed")
        self.assertNotIn("conts", result["relaunch"] or {})

    def test_a_standard_rerun_that_stops_again_forwards_only_its_own_cont(self):
        ineligible = {"stage": "ineligible", "cont": {"setup": {}, "lane": "direct"}}
        again = {"stage": "task", "task": {"n": 1}, "cont": {"setup": {}, "lane": "standard"}}
        result, _, _ = run(patch={"facts-1": {"lane": "direct", "why": "small"}},
                           children={"1": [ineligible, again]})
        self.assertEqual(result["relaunch"]["conts"], {"1": {"setup": {}, "lane": "standard"}})

    def test_a_child_that_lost_its_claim_is_claim_lost(self):
        result, _, _ = run(children={"1": {"stage": "claimed", "verdict": "held_by", "by": "h2/b9"}})
        self.assertEqual((row(result, 1)["outcome"], row(result, 1)["by"]), ("claim-lost", "h2/b9"))


TASK_STOP = {"stage": "task", "task": {"n": 2}, "cont": {"setup": {}}}
CLOSED_RELEASE = f"forge-claim release --repo owner/repo --issue 1 --holder {HOLDER} --reason closed"


class ClosedClaimTest(unittest.TestCase):
    def test_a_closed_issue_held_by_this_batch_is_released_at_intake(self):
        for verdict in ("held_by", "stale"):
            with self.subTest(verdict=verdict):
                result, calls, _ = run(patch={"facts-1": {"state": "CLOSED", "claim": {"verdict": verdict, "by": HOLDER}}})
                self.assertEqual(row(result, 1), {"issue": 1, "outcome": "closed", "released": True})
                self.assertEqual(labels(calls), ["setup", "facts-1", "release-1"])
                self.assertIn(CLOSED_RELEASE, prompt(calls, "release-1"))
                self.assertIsNone(result["relaunch"])

    def test_a_failed_intake_release_stays_open_for_a_relaunch(self):
        held = {"state": "CLOSED", "claim": {"verdict": "held_by", "by": HOLDER}}
        for reply, detail in (({"verdict": "error", "detail": "HTTP 502"}, "HTTP 502"),
                              (None, "release-1 returned nothing")):
            with self.subTest(reply=reply):
                result, _, _ = run(patch={"facts-1": held}, replies={"release-1": reply})
                self.assertEqual(row(result, 1), {"issue": 1, "outcome": "stopped", "stage": "release", "reason": f"release: {detail}"})
                self.assertEqual(result["relaunch"]["issues"], [1])
        result, _, _ = run(patch={"facts-1": held}, replies={"release-1": {"verdict": "not_held"}})
        self.assertEqual(row(result, 1), {"issue": 1, "outcome": "closed", "released": False})
        self.assertIsNone(result["relaunch"])

    def test_a_closed_issue_with_a_free_claim_retries_a_release_that_ended_the_claim_first(self):
        # forge-claim ends the claim before the marker edit and label removal, which can fail afterwards:
        # the next intake reads the claim free, and only the release itself finishes that cleanup.
        free = {"state": "CLOSED", "claim": {"verdict": "free", "by": None}}
        result, calls, _ = run(patch={"facts-1": free})
        self.assertEqual(row(result, 1), {"issue": 1, "outcome": "closed", "released": True})
        self.assertEqual(labels(calls), ["setup", "facts-1", "release-1"])
        self.assertIn(CLOSED_RELEASE, prompt(calls, "release-1"))
        result, _, _ = run(patch={"facts-1": free}, replies={"release-1": {"verdict": "error", "detail": "HTTP 502"}})
        self.assertEqual(row(result, 1), {"issue": 1, "outcome": "stopped", "stage": "release", "reason": "release: HTTP 502"})
        self.assertEqual(result["relaunch"]["issues"], [1])
        result, _, _ = run(patch={"facts-1": free}, replies={"release-1": {"verdict": "not_held"}})
        self.assertEqual(row(result, 1), {"issue": 1, "outcome": "closed", "released": False})
        self.assertIsNone(result["relaunch"])

    def test_a_closed_issue_with_a_failed_claim_lookup_stops_and_stays_in_relaunch(self):
        # A failed lookup proves nothing about ownership: the closed row must not be final, or a claim this batch holds is never released.
        err = {"state": "CLOSED", "claim": {"verdict": "error", "by": None}}
        result, calls, _ = run(patch={"facts-1": err})
        self.assertEqual(row(result, 1), {"issue": 1, "outcome": "stopped", "reason": "claim status"})
        self.assertEqual(result["relaunch"]["issues"], [1])
        self.assertNotIn("release-1", labels(calls))
        self.assertNotIn("acquire-1", labels(calls))

    def test_a_closed_issue_claimed_by_another_holder_is_not_released(self):
        for verdict in ("held_by", "stale"):
            with self.subTest(verdict=verdict):
                _, calls, _ = run(patch={"facts-1": {"state": "CLOSED", "claim": {"verdict": verdict, "by": "h2/b9"}}})
                self.assertNotIn("release-1", labels(calls))

    def test_the_intake_release_waits_for_every_facts_agent_and_precedes_every_acquire(self):
        _, calls, _ = run(args=dict(ARGS, issues=[1, 2]),
                          patch={"facts-1": {"state": "CLOSED", "claim": {"verdict": "held_by", "by": HOLDER}}})
        ls = labels(calls)
        self.assertLess(ls.index("facts-2"), ls.index("release-1"))
        self.assertLess(ls.index("release-1"), ls.index("acquire-2"))
        self.assertEqual(next(c for c in calls if c["label"] == "release-1")["facts_pending"], 0)

    def test_a_child_stop_on_a_closed_issue_releases_and_is_final(self):
        for release in ("released", "not_held"):
            with self.subTest(release=release):
                result, calls, _ = run(children={"1": TASK_STOP},
                                       replies={"settle-1": {"state": "CLOSED", "release": release}})
                self.assertEqual(row(result, 1), {"issue": 1, "outcome": "closed", "stage": "task",
                                                  "released": release == "released"})
                self.assertEqual(of(calls, 1)[-2:], ["child-1", "settle-1"])
                text = prompt(calls, "settle-1")
                self.assertIn("gh issue view 1 --repo owner/repo --json state", text)
                self.assertIn(CLOSED_RELEASE, text)
                self.assertIn("not_held (exit 3)", text)
                self.assertIsNone(result["relaunch"])

    def test_a_closed_settle_whose_release_failed_keeps_the_cont(self):
        for reply in ({"state": "CLOSED", "release": "error"}, None):
            with self.subTest(reply=reply):
                result, _, _ = run(children={"1": TASK_STOP}, replies={"settle-1": reply})
                self.assertEqual((row(result, 1)["outcome"], row(result, 1)["stage"]), ("stopped", "task"))
                self.assertEqual(result["relaunch"]["conts"], {"1": {"setup": {}}})

    def test_settle_runs_only_after_a_stop_with_a_cont(self):
        for c in ({"stage": "setup", "result": {"ok": False, "reason": "no-longer-applies"}},
                  {"stage": "plan", "needs_user": [{"question": "q?", "options": ["Do it."]}], "cont": {"setup": {}}},
                  {"stage": "claimed", "verdict": "held_by", "by": "h2/b9"},
                  {"stage": "planned", "cont": {"setup": {}}}):
            with self.subTest(child=c):
                _, calls, _ = run(children={"1": c})
                self.assertNotIn("settle-1", labels(calls))
        # A post-merge stop of a re-adopted merged landing: the issue reads CLOSED, but its close-out is unfinished.
        merged = {**landing(41), "state": "CLOSED", "claim": {"verdict": "held_by", "by": HOLDER}}
        for c in ({"stage": "close-out", "cont": {"setup": {}}},
                  {"stage": "setup", "missing": ["host"], "cont": {"setup": {}, "pr": 41}},
                  {"stage": "task", "pr": 41, "cont": {"setup": {}}},
                  {"stage": "close-out", "pr": 41, "cont": {"setup": {}}},
                  {"stage": "hold", "pr": 41, "cont": {"setup": {}}},
                  {"stage": "code-unmet", "pr": 41, "code_unmet": ["AC1"], "cont": {"setup": {}}}):
            with self.subTest(child=c):
                result, calls, _ = run(args=dict(ARGS, conts={"1": {"setup": {}, "pr": 41}}), patch={"facts-1": merged},
                                       children={"1": c}, replies={"settle-1": {"state": "CLOSED", "release": "released"}})
                self.assertNotIn("settle-1", labels(calls))
                self.assertEqual((row(result, 1)["outcome"], row(result, 1)["stage"]), ("stopped", c["stage"]))
                self.assertEqual(result["relaunch"]["conts"], {"1": c["cont"]})
        _, calls, _ = run()
        self.assertNotIn("settle-1", labels(calls))


class QuestionTest(unittest.TestCase):
    def test_an_unattended_batch_posts_box_prompts_and_returns_them_grouped(self):
        result, calls, _ = run(args=dict(ARGS, issues=[1, 2, 3], unattended=True),
                               children={"1": QUESTION, "3": QUESTION})
        self.assertEqual(result["questions"], [{"issue": 1, "questions": QS, "marker": 99},
                                               {"issue": 3, "questions": QS, "marker": 99}])
        self.assertIn("child-2", labels(calls))
        self.assertNotIn("release-1", labels(calls))
        text = prompt(calls, "ask-1")
        self.assertIn(f"forge-claim owner-action post --repo owner/repo --issue 1 --holder {HOLDER} "
                      "--reason decision --questions-file", text)
        self.assertIn(json.dumps(QS, separators=(",", ":")), text)
        self.assertEqual(result["owner_actions"], [{"issue": 1, "reason": "decision", "comment_id": 99},
                                                   {"issue": 3, "reason": "decision", "comment_id": 99}])
        self.assertTrue(result["relaunch"]["unattended"])

    def test_a_session_launched_batch_posts_no_prompt(self):
        result, calls, _ = run(children={"1": QUESTION})
        self.assertEqual(row(result, 1)["outcome"], "questions")
        self.assertEqual(result["questions"], [{"issue": 1, "questions": QS, "marker": None}])
        self.assertEqual(result["owner_actions"], [])
        self.assertNotIn("ask-1", labels(calls))
        self.assertFalse([c["label"] for c in calls if "owner-action post" in c.get("prompt", "")])
        self.assertNotIn("unattended", result["relaunch"])

    def test_open_questions_without_answers_wait_without_lane_claim_or_child(self):
        result, calls, _ = run(patch={"facts-1": {"claim": {"verdict": "held_by", "by": HOLDER}, "decision": OPEN}})
        self.assertEqual(row(result, 1)["outcome"], "questions")
        self.assertEqual(result["questions"], [{"issue": 1, "questions": OPEN["questions"], "marker": 99}])
        self.assertEqual(labels(calls), ["setup", "facts-1"])

    def test_an_answered_prompt_is_eligible_and_the_child_reads_it(self):
        _, calls, _ = run(patch={"facts-1": {"decision": ANSWERED}})
        self.assertNotIn("decisions", child(calls, 1)["args"])
        before_close = calls[:labels(calls).index("close-out-1")]
        self.assertFalse([c["label"] for c in before_close if "owner-action end" in c.get("prompt", "")])
        self.assertIn("--reason decision", prompt(calls, "close-out-1"))

    def test_relaunch_decisions_reach_the_child_and_end_nothing_early(self):
        _, calls, _ = run(args=dict(ARGS, decisions={"1": "Use the flag."}), patch={"facts-1": {"decision": OPEN}})
        self.assertEqual(child(calls, 1)["args"]["decisions"], "Use the flag.")
        self.assertNotIn("answered-1", labels(calls))

    def test_a_child_that_asks_again_drops_an_args_decision_from_the_relaunch(self):
        held = {"claim": {"verdict": "held_by", "by": HOLDER}}
        first, _, _ = run(args=dict(ARGS, decisions={"1": "Use the flag."}), patch={"facts-1": {"decision": OPEN}},
                          children={"1": QUESTION})
        self.assertEqual(row(first, 1)["outcome"], "questions")
        self.assertEqual(first["relaunch"]["decisions"], {})
        self.assertEqual(first["relaunch"]["conts"], {"1": QUESTION["cont"]})
        _, calls, _ = run(args=first["relaunch"], patch={"facts-1": dict(held, decision=ANSWERED)})
        self.assertEqual(child(calls, 1)["args"]["cont"], QUESTION["cont"])
        self.assertNotIn("decisions", child(calls, 1)["args"])

    def test_no_decisions_key_without_an_answer(self):
        _, calls, _ = run()
        self.assertNotIn("decisions", child(calls, 1)["args"])

    def test_no_prompt_text_reads_owner_replies(self):
        text = PROGRAM.read_text(encoding="utf-8")
        for gone in ("replies", "TAKEN", "answered-"):
            self.assertNotIn(gone, text)


class BreakerTest(unittest.TestCase):
    def test_a_terminal_agent_failure_stops_admission_and_returns_relaunch_args(self):
        result, calls, _ = run(args=dict(ARGS, issues=[1, 2, 3]), patch={"setup": {"max_parallel": 1}},
                               replies={"acquire-1": None})
        self.assertEqual(result["stage"], "breaker")
        self.assertNotIn("acquire-2", labels(calls))
        self.assertNotIn("acquire-3", labels(calls))
        self.assertEqual(row(result, 1)["outcome"], "stopped")
        self.assertEqual([row(result, n)["outcome"] for n in (2, 3)], ["not-admitted", "not-admitted"])
        self.assertEqual(without(result["relaunch"], "reasons"), dict(ARGS, issues=[1, 2, 3]))

    def test_every_dead_child_shape_trips_the_breaker(self):
        cont = {"setup": {}, "lane": "standard", "partial": 1}
        dead = [
            "throw",
            {"stage": "task-review", "task": {"n": 1}, "review": None, "dead_agents": ["review-1"], "cont": cont},
            {"stage": "plan-review", "details": "the plan reviewer returned nothing", "dead_agents": ["plan-review"],
             "cont": {"setup": {}}},
            {"stage": "final-review", "details": "a final reviewer returned nothing",
             "finals": [None, {"verdict": "pass", "findings": []}], "dead_agents": ["final-1"], "cont": {"setup": {}}},
            {"stage": "setup", "result": None, "dead_agents": ["setup"]},
        ]
        for c in dead:
            with self.subTest(child=c):
                result, calls, _ = run(args=dict(ARGS, issues=[1, 2]), patch={"setup": {"max_parallel": 1}},
                                       children={"1": c})
                self.assertEqual(result["stage"], "breaker")
                self.assertNotIn("child-2", labels(calls))
                self.assertNotIn("acquire-2", labels(calls))
                self.assertNotIn("release-1", labels(calls))
                self.assertEqual(result["relaunch"]["issues"], [1, 2])

    def test_a_stop_with_a_null_field_but_no_dead_agents_is_not_terminal(self):
        result, calls, _ = run(args=dict(ARGS, issues=[1, 2]), patch={"setup": {"max_parallel": 1}},
                               children={"1": {"stage": "checks", "checks": None, "cont": {"setup": {}}}})
        self.assertEqual(result["stage"], "done")
        self.assertIn("child-2", labels(calls))

    def test_relaunch_carries_the_decisions_verbatim(self):
        result, _, _ = run(args=dict(ARGS, issues=[1, 2], decisions={"2": "x"}), replies={"facts-1": None})
        self.assertEqual(result["relaunch"]["decisions"], {"2": "x"})

    def test_a_null_cont_free_stop_is_not_terminal_when_no_field_is_null(self):
        result, _, _ = run(children={"1": {"stage": "task", "task": {"n": 2}, "cont": {"setup": {}}}})
        self.assertEqual(result["stage"], "done")


class NoChangesTest(unittest.TestCase):
    """#923: a child whose every task ended with no commit has nothing to land: the row is final, the claim is given back."""

    CONT = {"setup": {"holder": HOLDER, "branch": "issue-1-x"}, "lane": "standard",
            "done": [{"n": 1, "commit": SHA, "no_change": True}]}
    STOP = {"stage": "no-changes", "reason": "no-changes: every task ended with no commit", "cont": CONT}

    def test_a_no_changes_child_is_final_released_and_an_owner_action(self):
        result, calls, _ = run(children={"1": self.STOP})
        self.assertEqual(row(result, 1), {"issue": 1, "outcome": "no-changes", "released": True,
                                          "reason": "no-changes: every task ended with no commit"})
        self.assertEqual(result["owner_actions"], [{"issue": 1, "reason": "no-changes"}])
        self.assertIsNone(result["relaunch"])
        self.assertIn(f"forge-claim release --repo owner/repo --issue 1 --holder {HOLDER} --reason skipped", prompt(calls, "release-1"))
        for label in labels(calls):
            self.assertFalse(label.startswith(("settle-", "land-")), label)

    def test_a_failed_release_keeps_the_row_open_with_its_cont(self):
        for reply in (None, {"verdict": "error", "detail": "forge down"}):
            with self.subTest(reply=reply):
                result, _, _ = run(children={"1": self.STOP}, replies={"release-1": reply})
                self.assertEqual((row(result, 1)["outcome"], row(result, 1)["stage"]), ("stopped", "release"))
                self.assertEqual(result["owner_actions"], [])
                self.assertEqual(result["relaunch"]["conts"], {"1": self.CONT})


class NotConvergingTest(unittest.TestCase):
    """#940: a child whose fix waves do not converge goes to the owner: final, not relaunched, the work and the claim left as they are."""

    FINDINGS = [{"severity": "important", "file": "claim.py", "summary": "race in steal", "failing_input": "two stealers"}]
    CONT = {"setup": {"holder": HOLDER, "branch": "issue-1-x", "worktree_path": "/r/.wt/w-issue-1-x"}, "lane": "standard",
            "plan": {"tasks": []}, "plan_reviewed": True, "done": [], "fix_waves": 4, "fix_findings": FINDINGS}
    REASON = ("fix-wave-review: the fix waves do not converge on claim.py after 4 waves; an owner decision on the design is needed; "
              "1 finding(s): race in steal")
    STOP = {"stage": "fix-wave-review", "fix_waves": 4, "diverging": {"file": "claim.py", "waves": 4}, "reason": REASON, "cont": CONT}
    TAKEN = {"file": "claim.py", "waves": 4, "worktree": "/r/.wt/w-issue-1-x", "branch": "issue-1-x"}

    def test_a_diverging_child_is_final_an_owner_action_and_keeps_its_claim(self):
        result, calls, _ = run(children={"1": self.STOP})
        self.assertEqual(row(result, 1), dict({"issue": 1, "outcome": "not-converging", "stage": "fix-wave-review",
                                               "reason": self.REASON}, **self.TAKEN))
        self.assertEqual(result["owner_actions"],
                         [dict({"issue": 1, "reason": "not-converging", "claim": "held", "holder": HOLDER,
                                "findings": self.FINDINGS, "cont": self.CONT}, **self.TAKEN)])
        self.assertIsNone(result["relaunch"])
        self.assertEqual(labels(calls).count("child-1"), 1)
        self.assertEqual(of(calls, 1)[-2:], ["child-1", "settle-1"])
        for call in calls:
            self.assertFalse(call["label"].startswith(("release-", "land-")), call["label"])
            if call["kind"] == "agent" and call["label"] != "settle-1":
                self.assertNotIn("forge-claim release", call["prompt"])

    def test_the_relaunch_of_the_other_issues_does_not_carry_it(self):
        other = {"setup": {}, "lane": "standard"}
        result, _, _ = run(args=dict(ARGS, issues=[1, 2]),
                           children={"1": self.STOP, "2": {"stage": "verify", "verify": {}, "cont": other}})
        self.assertEqual(row(result, 1)["outcome"], "not-converging")
        relaunch = result["relaunch"]
        self.assertEqual((relaunch["issues"], relaunch["conts"]), ([2], {"2": other}))
        self.assertNotIn("1", relaunch.get("reasons", {}))

    def test_the_owner_actions_cont_is_slimmed_and_resumes_the_child(self):
        setup = dict(self.CONT["setup"], base_sha=SHA, verification=[{"id": "v1"}], knowledge="k" * 5000, unset_env=["X"])
        result, _, _ = run(children={"1": dict(self.STOP, cont=dict(self.CONT, setup=setup))})
        cont = result["owner_actions"][0]["cont"]
        self.assertEqual(cont, dict(self.CONT, setup=dict(self.CONT["setup"], base_sha=SHA)))
        # The owner relaunches with it: the same batch id re-adopts the held claim and the child resumes the cont.
        again, calls, _ = run(args=dict(ARGS, conts={"1": cont}), patch={"facts-1": HELD})
        self.assertEqual(child(calls, 1)["args"]["cont"], cont)
        self.assertEqual(again["stage"], "done")

    def test_an_issue_closed_meanwhile_settles_as_closed(self):
        result, calls, _ = run(children={"1": self.STOP}, replies={"settle-1": {"state": "CLOSED", "release": "released"}})
        self.assertEqual(row(result, 1), {"issue": 1, "outcome": "closed", "stage": "fix-wave-review", "released": True})
        self.assertEqual(result["owner_actions"], [])
        self.assertIsNone(result["relaunch"])
        # A closed issue whose release failed stays stopped, so a relaunch releases it.
        failed, _, _ = run(children={"1": self.STOP}, replies={"settle-1": {"state": "CLOSED", "release": "error"}})
        self.assertEqual(row(failed, 1)["outcome"], "stopped")
        self.assertEqual(failed["owner_actions"], [])
        # A settle that gave no answer leaves the state unread: the stop still goes to the owner.
        lost, _, _ = run(children={"1": self.STOP}, replies={"settle-1": None})
        self.assertEqual(row(lost, 1)["outcome"], "not-converging")

    def test_the_pr_and_bounded_findings_reach_the_owner_action(self):
        many = [{"severity": "important", "file": "claim.py", "summary": f"race {i} " + "x" * 900, "extra": "dropped"} for i in range(14)]
        stop = dict(self.STOP, cont=dict(self.CONT, pr=77, fix_findings=many + ["text"]))
        result, _, _ = run(children={"1": stop})
        action = result["owner_actions"][0]
        self.assertEqual((action["pr"], row(result, 1)["pr"]), (77, 77))
        self.assertEqual(len(action["findings"]), 10)
        for finding in action["findings"]:
            self.assertEqual(set(finding), {"severity", "file", "summary"})
            self.assertLessEqual(len(finding["summary"]), 300)
        self.assertNotIn("findings", row(result, 1))
        self.assertEqual(action["cont"]["fix_findings"], action["findings"])
        self.assertEqual(action["cont"]["pr"], 77)

    def test_the_file_the_worktree_and_the_branch_are_one_capped_line_each(self):
        setup = dict(self.CONT["setup"], worktree_path="/r/.wt/w\n" + "w" * 900, branch="issue-1-x\n" + "b" * 900)
        stop = dict(self.STOP, diverging={"file": "src/claim.py\n" + "f" * 900, "waves": 4}, cont=dict(self.CONT, setup=setup))
        result, _, _ = run(children={"1": stop})
        for holder in (row(result, 1), result["owner_actions"][0]):
            for key, start in (("file", "src/claim.py f"), ("worktree", "/r/.wt/w w"), ("branch", "issue-1-x b")):
                with self.subTest(key=key):
                    self.assertTrue(holder[key].startswith(start), holder[key])
                    self.assertNotIn("\n", holder[key])
                    self.assertLessEqual(len(holder[key]), 300)

    def test_an_ordinary_fix_wave_review_stop_is_relaunched_with_its_cont(self):
        stop = without(dict(self.STOP, reason="fix-wave-review: 1 finding(s): race in steal"), "diverging")
        result, calls, _ = run(children={"1": stop})
        self.assertEqual((row(result, 1)["outcome"], row(result, 1)["stage"]), ("stopped", "fix-wave-review"))
        self.assertEqual(result["owner_actions"], [])
        self.assertEqual(result["relaunch"]["conts"], {"1": self.CONT})


class ContTest(unittest.TestCase):
    def test_an_interrupted_task_resumes_through_its_forwarded_cont(self):
        cont = {"setup": {"holder": HOLDER, "branch": "issue-1-x"}, "lane": "direct", "plan": None,
                "done": [], "partial": 1}
        dead = {"stage": "task-review", "task": {"n": 1}, "review": None, "dead_agents": ["review-1"], "cont": cont}
        first, _, _ = run(children={"1": dead})
        self.assertEqual(first["stage"], "breaker")
        self.assertEqual(without(first["relaunch"], "reasons"), dict(ARGS, conts={"1": cont}))
        # The relaunch: a new run on the returned args; the tracker still shows the batch's own claim.
        result, calls, _ = run(args=first["relaunch"],
                               patch={"facts-1": {"claim": {"verdict": "held_by", "by": HOLDER}}})
        self.assertEqual(child(calls, 1)["args"], {"repo_root": "/r", "issue": 1, "batch_id": "b1",
                                                   "mode": "ready", "cont": cont})
        self.assertIn("acquire-1", labels(calls))
        self.assertEqual(labels(calls).count("child-1"), 1)
        self.assertEqual(result["stage"], "done")  # Task 4 turns this ready child into a landing

    def test_a_stop_with_cont_is_forwarded_and_a_stop_without_is_not(self):
        cont = {"setup": {}, "lane": "standard"}
        result, _, _ = run(args=dict(ARGS, issues=[1, 2]),
                           children={"1": {"stage": "verify", "verify": {}, "cont": cont},
                                     "2": {"stage": "setup", "result": {"ok": False, "reason": "closed"}}})
        self.assertEqual(result["relaunch"]["conts"], {"1": cont})

    def test_a_questioned_child_forwards_its_cont_with_the_decisions(self):
        result, _, _ = run(children={"1": QUESTION})
        self.assertEqual(result["relaunch"]["conts"], {"1": QUESTION["cont"]})
        _, calls, _ = run(args=dict(result["relaunch"], decisions={"1": "Use the flag."}),
                          patch={"facts-1": {"decision": OPEN, "claim": {"verdict": "held_by", "by": HOLDER}}})
        args = child(calls, 1)["args"]
        self.assertEqual((args["cont"], args["decisions"]), (QUESTION["cont"], "Use the flag."))
        self.assertNotIn("lane", args)


B = "b" * 40
FIX = "c0ffee"
# #913: a sync step whose merge conflicts aborts it and answers conflicted; the resolution is its own step, land-sync-resolve, outside the land lock.
ABORTED = {"status": "conflicted", "conflicted": True, "head": SHA, "notes": "x.py conflicts"}
C = "c" * 40
HAPPY = ["facts-1", "acquire-1", "child-1", "child-1", "land-pr-1", "land-merge-1", "close-out-1"]
# The folded first checks poll of land-pr answering behind, so the landing resyncs before its next poll, land-checks-1-2 (#801).
BEHIND = {"land-pr-1": {"checks": {"state": "behind", "head": SHA}}}


def contended(n=1):
    """Replies that answer every retry of issue n's waited land acquire with land-contended (#818)."""
    return {f"land-lock-{n}-{k}": {"lock": {"verdict": "land-contended", "lock_sha": B}} for k in (1, 2, 3)}


def folded(checks):
    """A land-pr patch whose carried first checks poll is `checks`."""
    return {"land-pr-1": {"checks": checks}}


def ready(n, acceptance=None, head=SHA):
    return {"stage": "ready", "head": head, "branch": f"issue-{n}-x", "worktree": f"/r/.wt/w-issue-{n}-x",
            "verify": [{"id": "build", "status": "pass", "summary": "ok"}], "tasks": [{"n": 1}],
            "acceptance": acceptance or [{"id": "AC1", "text": "works", "kind": "code"}], "fix_waves": 0,
            "cont": {"setup": {"holder": HOLDER, "branch": f"issue-{n}-x", "worktree": f"/r/.wt/w-issue-{n}-x"}}}

# The relaunch conts of a landing of issue 1: one that stops before its merge keeps the child's ready cont, one that
# stops after it adds the merged PR (the harness's default land-pr PR is 41).
PRE_MERGE_CONTS = {"1": ready(1)["cont"]}
POST_MERGE_CONTS = {"1": dict(ready(1)["cont"], pr=41)}


CHILD_PROGRAM = PROGRAM.with_name("deliver-standard.js")
CHILD_HARNESS = Path(__file__).with_name("deliver_standard_harness.mjs")
BOOKKEEPING = re.compile(r"^(facts|acquire|setup|worktree|renew|owner-answer|land-lock|land-unlock|close-out)(-|$)")
# One batch-delivered issue's bookkeeping agents on the happy path at 6e2f9dde: the ready child's setup, acquire,
# worktree, renew-plan, owner-answer, renew-tasks, renew-final-review and renew-verify, and the batch's facts-1,
# acquire-1, renew-1-land, land-lock-1-1, renew-1-merge, land-lock-1-2, land-unlock-1 and close-out-1.
BOOKKEEPING_BASELINE = 16


def schema_of(calls, label):
    found = [c["schema"] for c in calls if c["label"] == label and c["kind"] == "agent"]
    if not found:
        raise AssertionError(f"no agent call labelled {label}: {labels(calls)}")
    return found[-1]


def object_branch(schema):
    if "anyOf" in schema:
        found = [s for s in schema["anyOf"] if s.get("type") == "object"]
        if len(found) != 1:
            raise AssertionError(f"no single object branch: {schema}")
        return found[0]
    return schema


class FlakyVerificationRowTest(unittest.TestCase):
    """#972: a check the child saw fail and pass on its one rerun is named on the issue's row and in the log."""

    FLAKY = [{"id": "build", "summary": "tests/http_client.test.ts > retries: timed out"}]

    def test_a_landed_row_names_the_flaky_test(self):
        out = run_full(children={"1": dict(ready(1), flaky=self.FLAKY)})
        row = out["result"]["table"][0]
        self.assertEqual((row["outcome"], row["flaky"]), ("landed", self.FLAKY))
        self.assertIn("#1: flaky verification, passed on the one rerun: build: tests/http_client.test.ts > retries: timed out",
                      out["logs"])

    def test_a_row_without_a_flaky_check_carries_no_member(self):
        out = run_full(children={"1": dict(ready(1), flaky=[{"id": "build"}, "x"])})
        self.assertNotIn("flaky", out["result"]["table"][0])
        self.assertNotIn("flaky", run_full()["result"]["table"][0])

    OUT = [{"file": "tests/http_client.test.ts", "why": "the sentinel s-1 occurs in the worktree path"}]

    def test_a_landed_row_and_its_pr_name_the_out_of_diff_fix_and_its_cause(self):
        out = run_full(children={"1": dict(ready(1), outside_fixes=self.OUT)})
        row = out["result"]["table"][0]
        self.assertEqual((row["outcome"], row["outside_fixes"]), ("landed", self.OUT))
        self.assertIn("#1: the verification fix edited outside the branch's diff: tests/http_client.test.ts: "
                      "the sentinel s-1 occurs in the worktree path", out["logs"])
        pr = [c["prompt"] for c in out["calls"] if c["label"] == "land-pr-1"][-1]
        self.assertIn("verification fixes outside the branch's diff, each with its cause", pr)
        self.assertIn("the sentinel s-1 occurs in the worktree path", pr)
        plain = run_full()
        self.assertNotIn("outside_fixes", plain["result"]["table"][0])
        self.assertNotIn("outside the branch's diff", [c["prompt"] for c in plain["calls"] if c["label"] == "land-pr-1"][-1])

    def test_an_unrelated_verification_failure_is_a_stopped_row_with_its_reason_and_is_relaunched(self):
        reason = "verify-unrelated: tests/http_client.test.ts > retries fails outside this branch's diff, so no fix was made: fails at origin/dev"
        stop = {"stage": "verify-unrelated", "reason": reason, "cont": reviewed(1)}
        result, _, _ = run(children={"1": stop})
        row = result["table"][0]
        self.assertEqual((row["outcome"], row["stage"], row["reason"]), ("stopped", "verify-unrelated", reason))
        self.assertIn("1", result["relaunch"]["conts"])


def run_child(args, replies=None, patch=None):
    node = shutil.which("node")
    if node is None:
        raise AssertionError("node is not on PATH; the deliver-standard scenarios need it")
    scenario = {"args": args, "replies": replies or {}, "patch": patch or {}}
    done = subprocess.run([node, str(CHILD_HARNESS), str(CHILD_PROGRAM)], input=json.dumps(scenario),
                          capture_output=True, text=True, timeout=60, check=False)
    if done.returncode != 0:
        raise AssertionError(f"child harness failed: {done.stderr}")
    out = json.loads(done.stdout)
    return out["result"], out["calls"]


class BookkeepingCountTest(unittest.TestCase):
    def test_per_issue_bookkeeping_agents_drop_by_at_least_40_percent(self):
        child_result, child_calls = run_child({"repo_root": "/r", "issue": 1, "batch_id": "b1",
                                               "mode": "ready", "lane": "standard"})
        self.assertEqual(child_result["stage"], "ready")
        result, calls, _ = run()
        self.assertEqual(row(result, 1)["outcome"], "landed")
        child_book = [l for l in labels(child_calls) if BOOKKEEPING.match(l)]
        batch_book = [l for l in of(calls, 1) if BOOKKEEPING.match(l)]
        self.assertLessEqual(len(child_book) + len(batch_book), BOOKKEEPING_BASELINE * 0.6, (child_book, batch_book))


def size(value):
    return len(json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode())


class RelaunchContSizeTest(unittest.TestCase):
    """The lead copies the relaunch into the next run's args: a forwarded cont keeps of its setup only what a resume reads."""

    CHILD_ARGS = {"repo_root": "/r", "issue": 1, "batch_id": "b1"}
    DETAILS = "Still applies: the handler in src/a.py drops the second call; nothing of it exists yet."
    RULE = {"verdict": "findings", "findings": [{"severity": "important", "rule": "R2", "summary": "AC1 asks for approval"}]}
    # Every kind of stop a batch forwards: (the child's mode, its replies, the stage it stops at, the first call only that resume makes).
    STOPS = (
        ("ready", {}, "ready", "renew-final-review"),
        ("plan", {}, "planned", "impl-1"),
        ("ready", {"plan": {"status": "needs_user", "questions": [{"question": "Which host?", "options": ["One.", "Two."]}]}},
         "plan", "plan"),
        ("ready", {"plan-review": RULE, "plan-rules-review": RULE}, "plan-review", "plan-rules-revise"),
        ("ready", {"impl-1": {"status": "blocked", "notes": "the fixture is missing"}}, "task", "impl-1"),
        ("ready", {"verify": None}, "verify", "verify"),
    )
    # A resume's setup reply reads the contract afresh; a dirty tree, a moved head and a merged PR take the other resume paths.
    RESUME_SETUPS = ({}, {"dirty": True}, {"head": "b" * 40})

    def stop(self, mode, replies, stage):
        result, _ = run_child(dict(self.CHILD_ARGS, mode=mode, lane="standard"), replies=replies,
                              patch={"setup": {"details": self.DETAILS}})
        self.assertEqual(result["stage"], stage, result)
        return result

    def forwarded(self, stop):
        """The cont a batch's relaunch carries for a child that stopped with `stop`; a ready or planned child's when its issue then waits."""
        if stop["stage"] in ("ready", "planned"):
            result, _, _ = run(args=dict(ARGS, conts={"1": stop["cont"]}), patch={"facts-1": {"blockers": [{"issue": 50, "state": "OPEN"}]}})
        else:
            result, _, _ = run(children={"1": stop})
        return result["relaunch"]["conts"]["1"]

    def test_the_relaunch_keeps_only_the_setup_members_a_resume_reads(self):
        full = self.stop("ready", {"verify": None}, "verify")["cont"]
        dropped = set(full["setup"]) - set(SETUP_KEPT)
        for name in ("verification", "knowledge", "review", "review_state", "unset_env", "slug", "integration_branch",
                     "merge_strategy", "host"):
            self.assertIn(name, dropped)
        sent = self.forwarded({"stage": "verify", "cont": full})
        self.assertEqual(sent, slim(full))
        self.assertEqual(set(sent["setup"]), set(full["setup"]) & set(SETUP_KEPT))
        for name in ("holder", "branch", "worktree", "worktree_path", "base_sha", "plan_dir", "details"):
            self.assertEqual(sent["setup"][name], full["setup"][name])
        self.assertEqual({k: v for k, v in sent.items() if k != "setup"}, {k: v for k, v in full.items() if k != "setup"})

    def test_a_given_cont_is_slimmed_the_same_way_and_slimming_twice_changes_nothing(self):
        full = self.stop("ready", {"verify": None}, "verify")["cont"]
        blocked = {"facts-1": {"blockers": [{"issue": 50, "state": "OPEN"}]}}
        first, _, _ = run(args=dict(ARGS, conts={"1": full}), patch=blocked)
        self.assertEqual(first["relaunch"]["conts"], {"1": slim(full)})
        second, _, _ = run(args=first["relaunch"], patch=blocked)
        self.assertEqual(second["relaunch"]["conts"], first["relaunch"]["conts"])

    def test_a_cont_with_no_setup_object_is_forwarded_as_it_came(self):
        for cont in ({"lane": "standard"}, {"setup": None, "lane": "standard"}, {"setup": "x"}):
            with self.subTest(cont=cont):
                result, _, _ = run(children={"1": {"stage": "task", "cont": cont}})
                self.assertEqual(result["relaunch"]["conts"], {"1": cont})

    def test_a_resume_of_the_slimmed_cont_runs_the_steps_of_the_full_cont(self):
        """stop -> relaunch args -> resume: every prompt but the setup's, every step and the result are those of the full cont."""
        # A planned child is resumed in mode ready, as the batch resumes it once a delivery slot is free.
        stops = [("ready", self.stop(mode, replies, stage), step) for mode, replies, stage, step in self.STOPS]
        # A kept plan whose findings no rules-only revise may settle: its resume drops the plan and plans again.
        kept = next(s for _, s, _ in stops if s["stage"] == "plan-review")
        findings = dict(kept["cont"]["plan_findings"], rules=[dict(kept["cont"]["plan_findings"]["rules"][0], source="codex")])
        stops.append(("ready", dict(kept, cont=dict(kept["cont"], plan_findings=findings)), "plan"))
        for mode, stop, step in stops:
            full = stop["cont"]
            sent = self.forwarded(stop)
            self.assertEqual(sent, slim(full))
            self.assertLess(size(sent), size(full))
            for setup in self.RESUME_SETUPS:
                with self.subTest(stage=stop["stage"], step=step, setup=setup):
                    runs = [run_child(dict(self.CHILD_ARGS, mode=mode, cont=cont), patch={"setup": setup}) for cont in (full, sent)]
                    (want, want_calls), (got, got_calls) = runs
                    self.assertEqual(labels(got_calls), labels(want_calls))
                    if not setup.get("dirty"):
                        self.assertIn(step, labels(want_calls))
                    self.assertEqual(got, want)
                    for a, b in zip(got_calls, want_calls):
                        if a["label"] == "setup":
                            earlier = "Earlier setup: "
                            self.assertEqual(a["prompt"].replace(earlier + json.dumps(sent["setup"], separators=(",", ":")), earlier),
                                             b["prompt"].replace(earlier + json.dumps(full["setup"], separators=(",", ":")), earlier))
                            self.assertNotEqual(a["prompt"], b["prompt"])
                        else:
                            self.assertEqual(a, b)

    def test_a_merged_landing_closes_out_from_the_slimmed_cont_as_from_the_full_one(self):
        stop = self.stop("ready", {}, "ready")
        full = dict(stop["cont"], pr=41)
        sent = self.forwarded({"stage": "hold", "pr": 41, "cont": full})
        self.assertEqual(sent, slim(full))
        merged = {"setup": {"merged_pr": 41, "merged_heads": [{"number": 41, "commits": []}]}}
        (want, want_calls), (got, got_calls) = [run_child(dict(self.CHILD_ARGS, cont=cont), patch=merged) for cont in (full, sent)]
        self.assertEqual(labels(got_calls), labels(want_calls))
        self.assertIn("hold", labels(want_calls))
        self.assertEqual(got, want)
        self.assertEqual([c for c in got_calls if c["label"] != "setup"], [c for c in want_calls if c["label"] != "setup"])

    def test_every_setup_member_the_child_reads_from_a_cont_is_kept(self):
        """A new read of cont.setup in the child must be added to the batch's kept list, or a relaunch would drop it."""
        batch = PROGRAM.read_text(encoding="utf-8")
        kept = json.loads(re.search(r"^const CONT_SETUP_KEPT = (\[.*\])$", batch, re.M).group(1).replace("'", '"'))
        self.assertEqual(tuple(kept), SETUP_KEPT)
        child_text = CHILD_PROGRAM.read_text(encoding="utf-8")
        read = set(re.findall(r"\bCONT\.setup\.([A-Za-z_]+)", child_text))
        self.assertEqual(read, {"holder", "branch", "worktree", "worktree_path", "base_sha", "plan_dir"})
        self.assertLessEqual(read, set(kept))
        # The only other use of cont.setup is the resume prompt's "Earlier setup", and the child never spreads or iterates it.
        whole = re.findall(r"CONT\.setup(?![.\w])(?! &&)(?!\))", child_text)
        self.assertEqual(len(whole), 0, whole)
        self.assertEqual(child_text.count("JSON.stringify(CONT.setup)"), 1)
        self.assertEqual(len(re.findall(r"\.\.\.\s*CONT\.setup|Object\.(keys|entries|values|assign)\(CONT\.setup", child_text)), 0)

    def test_a_representative_relaunch_shrinks_by_the_setup_it_no_longer_carries(self):
        """A cont shaped like a recorded one (a reviewed plan of five tasks, verified): the setup falls to a third, the cont by a tenth."""
        setup = {
            "ok": True, "host": "host-1", "slug": "owner/repo", "unset_env": [], "integration_branch": "dev", "default_branch": "main",
            "merge_strategy": "merge", "delete_branch": True, "review": {"code": "review-code", "plan": "review-plan"},
            "review_state": {"code": "available", "plan": "available"},
            "knowledge": {"standards": ["/home/u/Projects/repo/docs/standards/README.md"], "hints": ["/home/u/Projects/repo/.claude/hints"],
                          "rejections": ["/home/u/Projects/repo/.agents/knowledge/rejections"]},
            "verification": [{"id": "lint", "argv": ["devenv", "tasks", "run", "ci:lint"], "cwd": "."},
                             {"id": "test", "argv": ["devenv", "tasks", "run", "ci:test"], "cwd": "."}],
            "branch": "issue-1-a-browser-run-loses-its-own", "head": SHA, "dirty": False, "since_reviewed": "same",
            "worktree_path": "/home/u/Projects/repo/.worktrees/worktree-issue-1-a-browser-run-loses-its-own",
            "holder": "host-1/host-1-20261111-1415",
            "worktree": "/home/u/Projects/repo/.worktrees/worktree-issue-1-a-browser-run-loses-its-own",
            "base_sha": "3" * 40,
            "plan_dir": "/home/u/Projects/repo/.git/worktrees/worktree-issue-1-a-browser-run-loses-its-own/deliver-standard",
        }
        plan_dir = setup["plan_dir"]
        cont = {
            "setup": setup, "lane": "standard",
            "plan": {"status": "planned", "plan_root": f"{plan_dir}/plan.md",
                     "acceptance": [{"id": f"AC{i}", "kind": "code", "text": "A test with a fake tool that never answers: " + "x" * 330}
                                    for i in range(1, 5)],
                     "tasks": [{"n": i, "title": "Bound each heartbeat call so a hang is a failed beat " + "y" * 40,
                                "file": f"{plan_dir}/task-{i}.md", "risk": "standard"} for i in range(1, 6)]},
            "plan_reviewed": True, "decisions": ["Approved as filed. " + "z" * 300],
            "done": [{"n": i, "commit": "c" * 40, "review_rounds": 0, "reviewer": "reviewer"} for i in range(1, 6)],
            "fix_waves": 0, "final_reviewed": {"head": SHA},
            "verified": {"head": SHA, "results": [{"id": "lint", "status": "pass", "summary": "ok"}, {"id": "test", "status": "pass", "summary": "ok"}],
                         "contract": json.dumps(setup["verification"], separators=(",", ":"))},
        }
        result, _, _ = run(args=dict(ARGS, conts={"1": cont}), patch={"facts-1": {"blockers": [{"issue": 50, "state": "OPEN"}]}})
        sent = result["relaunch"]["conts"]["1"]
        self.assertLessEqual(size(sent["setup"]), size(setup) * 0.5)
        self.assertLessEqual(size(sent), size(cont) * 0.9)
        # The plan, the decisions, the task log and the verification are read by the resume from the cont, so they stay whole.
        self.assertGreaterEqual(size(sent), size(cont) * 0.8)


RENEW_READ = {"verdict", "by", "detail", "transient"}
FOLDED_READ = {
    "land-pr-1": ({"pr", "head"}, {"renew": RENEW_READ, "lock": {"verdict"},
                                   "checks": {"state", "head", "passed", "failing", "pending", "label", "details"}}),
    "land-merge-1": ({"merged", "notes"}, {"renew": RENEW_READ, "lock": {"verdict"}}),
    "land-record-1-1": ({"ok", "head", "detail"}, {"lock": {"verdict"},
                                                   "checks": {"state", "head", "passed", "failing", "pending"}}),
    "close-out-1": ({"issue_state", "released", "decision_ended", "notes_posted"}, {"release": {"verdict", "detail"}}),
}


class FoldTest(unittest.TestCase):
    """#716: the folded landing steps keep every field the program reads, and a folded lock is always released."""

    def test_folded_schemas_keep_every_read_field(self):
        _, calls, _ = run(patch=BEHIND,
                          replies={"land-sync-1-1": {"status": "done", "conflicted": False, "head": B, "notes": "ok"}})
        for label, (top, nested) in FOLDED_READ.items():
            with self.subTest(label=label):
                schema = schema_of(calls, label)
                self.assertLessEqual(top, set(schema["properties"]))
                for name, fields in nested.items():
                    if name in ("lock", "release", "checks"):
                        self.assertIn({"type": "null"}, schema["properties"][name]["anyOf"])
                    branch = object_branch(schema["properties"][name])
                    self.assertLessEqual(fields, set(branch["properties"]))
                if "renew" in nested:
                    self.assertEqual(schema["required"], ["renew"])

    def test_folded_pr_lock_is_released_on_head_moved(self):
        result, calls, _ = run(replies={"land-pr-1": {"pr": 41, "head": B}})
        self.assertEqual((row(result, 1)["outcome"], row(result, 1)["stage"]), ("stopped", "head-moved"))
        ls = of(calls, 1)
        self.assertEqual(ls[ls.index("land-pr-1"):], ["land-pr-1", "land-unlock-1"])
        self.assertIn(f"forge-claim land release --repo owner/repo --branch dev --sha {SHA}\n", prompt(calls, "land-unlock-1"))
        self.assertIn(f"forge-claim land acquire --repo owner/repo --branch dev --sha {SHA} --wait\n", prompt(calls, "land-pr-1"))

    def test_folded_record_lock_is_released_at_the_moved_sha(self):
        result, calls, _ = run(patch=BEHIND, replies={
            "land-sync-1-1": {"status": "done", "conflicted": False, "head": B, "notes": "ok"},
            "land-record-1-1": {"ok": True, "head": "d" * 40, "lock": {"verdict": "moved", "lock_sha": B}}})
        self.assertEqual((row(result, 1)["outcome"], row(result, 1)["stage"]), ("stopped", "land-record"))
        self.assertEqual(labels(calls).count("land-unlock-1"), 1)
        self.assertIn(f"forge-claim land release --repo owner/repo --branch dev --sha {B}\n", prompt(calls, "land-unlock-1"))

    def test_a_lost_folded_lock_reply_releases_every_sha_it_may_hold(self):
        release = f"forge-claim land release --repo owner/repo --branch dev --sha {SHA}\n"
        again = (f"When it prints not_held with lock_sha {B}, run alone and exactly: "
                 f"forge-claim land release --repo owner/repo --branch dev --sha {B}")
        synced = {"land-sync-1-1": {"status": "done", "conflicted": False, "head": B, "notes": "ok"}}
        # The initial --wait lock and the pre-merge re-check: the lock is held (or may be) at one sha only.
        # A lost reply stops at its step's own stage; a thrown agent stops at "land". Neither reached the merge
        # as far as the program knows, so the relaunch keeps the child's ready cont.
        for label, extra in (("land-pr-1", {}), ("land-merge-1", {})):
            for reply in (None, "throw"):
                with self.subTest(label=label, reply=reply):
                    result, calls, _ = run(replies=dict(extra, **{label: reply}))
                    self.assertEqual(row(result, 1)["outcome"], "stopped")
                    self.assertEqual(row(result, 1)["stage"], {"land-pr-1": "pr", "land-merge-1": "merge"}[label] if reply is None else "land")
                    self.assertEqual(result["relaunch"]["issues"], [1])
                    self.assertEqual(result["relaunch"]["conts"], PRE_MERGE_CONTS)
                    ls = of(calls, 1)
                    self.assertEqual(ls[ls.index(label):], [label, "land-unlock-1"])
                    self.assertNotIn("When it prints not_held", prompt(calls, "land-unlock-1"))
        # The record step's move: unanswered, it may or may not have moved the lock to B, so both are released.
        for reply in (None, "throw", {"ok": True, "head": B, "lock": {"verdict": "error", "detail": "gh failed"}}):
            with self.subTest(record=reply):
                result, calls, _ = run(patch=BEHIND, replies={"land-sync-1-1": synced["land-sync-1-1"], "land-record-1-1": reply})
                graded = row(result, 1)
                if isinstance(reply, dict):
                    self.assertEqual(graded["outcome"], "land-contended")
                else:
                    self.assertEqual((graded["outcome"], graded["stage"]), ("stopped", "land-record" if reply is None else "land"))
                self.assertEqual(result["relaunch"]["conts"], PRE_MERGE_CONTS)
                text = prompt(calls, "land-unlock-1")
                self.assertIn(release, text)
                self.assertIn(again, text)
                self.assertEqual(labels(calls).count("land-unlock-1"), 1)
        # Definitive answers: no move ran (ok false, lock null) or another holder refused it; only the old sha is ours.
        for reply in ({"ok": False, "head": "d" * 40, "detail": "head differs", "lock": None},
                      {"ok": True, "head": B, "lock": {"verdict": "held_by", "lock_sha": "c" * 40, "by": "h2/b9"}}):
            with self.subTest(record=reply):
                result, calls, _ = run(patch=BEHIND, replies={"land-sync-1-1": synced["land-sync-1-1"], "land-record-1-1": reply})
                graded = row(result, 1)
                if reply["ok"]:
                    self.assertEqual(graded["outcome"], "land-contended")
                else:
                    self.assertEqual((graded["outcome"], graded["stage"]), ("stopped", "land-record"))
                self.assertEqual(result["relaunch"]["conts"], PRE_MERGE_CONTS)
                self.assertIn(release, prompt(calls, "land-unlock-1"))
                self.assertNotIn("When it prints not_held", prompt(calls, "land-unlock-1"))
        # A land-pr whose renew ended ran no lock command: nothing to release.
        _, calls, _ = run(patch={"land-pr-1": {"renew": {"verdict": "not_held", "by": "h2/b9"}}})
        self.assertNotIn("land-unlock-1", labels(calls))


class LandTest(unittest.TestCase):
    NOTE = {"id": "AC2", "text": "the next session's first-turn prompt reads under 30k tokens", "kind": "note"}
    CODE = {"id": "AC1", "text": "works", "kind": "code"}

    def test_a_note_is_listed_and_the_issue_closes(self):
        """#736 AC2: a note is never held; the batch close-out comment lists the note texts."""
        result, calls, _ = run(children={"1": ready(1, [self.CODE, self.NOTE])},
                               replies={"close-out-1": {"issue_state": "CLOSED", "released": True, "decision_ended": True,
                                                        "notes_posted": True, "notes": "ok"}})
        self.assertEqual(row(result, 1)["outcome"], "landed")
        close = prompt(calls, "close-out-1")
        self.assertIn(self.NOTE["text"], close)
        self.assertIn("gh issue comment 1 --repo owner/repo --body-file", close)
        self.assertLess(close.index("Orchestrator notes for PR 41"), close.index("gh issue close 1 --repo owner/repo"))
        self.assertNotIn("needs-verification", close)
        _, calls, _ = run(children={"1": ready(1, [self.CODE, self.NOTE])}, patch={"setup": {"integration_branch": "main"}},
                          replies={"close-out-1": {"issue_state": "CLOSED", "released": True, "decision_ended": True,
                                                   "notes_posted": True, "notes": "ok"}})
        self.assertIn("Closes #1", prompt(calls, "land-pr-1"))

    def test_an_unrecognised_kind_stops_the_landing_before_any_close(self):
        """#736 DR-002: a typo kind is neither open nor a note, so the landing stops before the PR and never closes."""
        typo = dict(self.NOTE, kind="evdience")
        result, calls, _ = run(children={"1": ready(1, [self.CODE, typo])})
        self.assertEqual((row(result, 1)["outcome"], row(result, 1)["stage"]), ("stopped", "plan"))
        self.assertNotIn("close-out-1", [c["label"] for c in calls])
        self.assertNotIn("land-pr-1", [c["label"] for c in calls])

    def test_unposted_notes_stop_the_landing_close_out(self):
        result, _, _ = run(children={"1": ready(1, [self.CODE, self.NOTE])},
                           replies={"close-out-1": {"issue_state": "CLOSED", "released": True, "decision_ended": True,
                                                    "notes_posted": False, "notes": "x"}})
        self.assertEqual((row(result, 1)["outcome"], row(result, 1)["stage"]), ("stopped", "close-out"))

    def test_a_note_beside_evidence_holds_only_the_evidence(self):
        evidence = {"id": "AC3", "text": "live", "kind": "evidence"}
        result, calls, _ = run(children={"1": ready(1, [self.CODE, self.NOTE, evidence])},
                               replies={"close-out-1": {"issue_state": "OPEN", "released": True, "decision_ended": True,
                                                        "notes_posted": True, "notes": "held"}})
        self.assertEqual(row(result, 1)["outcome"], "landed-held")
        close = prompt(calls, "close-out-1")
        self.assertIn('how to check each: [{"id":"AC3","text":"live","kind":"evidence"}]', close)
        self.assertIn(self.NOTE["text"], close)

    def test_happy_landing_runs_every_step_in_order(self):
        result, calls, _ = run()
        self.assertEqual((row(result, 1)["outcome"], row(result, 1)["pr"]), ("landed", 41))
        self.assertEqual(of(calls, 1), HAPPY)
        # 10 agent calls as before #744, plus the plan child (a workflow call): see the plan-ahead budget test.
        self.assertLessEqual(len(of(calls, 1)), 11)
        self.assertIsNone(result["relaunch"])

    def test_landing_commands_are_exact(self):
        _, calls, _ = run()
        self.assertIn(f"forge-claim renew --repo owner/repo --issue 1 --holder {HOLDER} --branch issue-1-x",
                      prompt(calls, "land-pr-1"))
        self.assertIn(f"forge-claim renew --repo owner/repo --issue 1 --holder {HOLDER} --branch issue-1-x",
                      prompt(calls, "land-merge-1"))
        self.assertIn(f"forge-claim land acquire --repo owner/repo --branch dev --sha {SHA} --wait\n",
                      prompt(calls, "land-pr-1"))
        self.assertIn(f"forge-claim land acquire --repo owner/repo --branch dev --sha {SHA}\n", prompt(calls, "land-merge-1"))
        self.assertNotIn(" --wait\n", prompt(calls, "land-merge-1"))
        self.assertIn(f"gh pr merge 41 --repo owner/repo --merge --match-head-commit {SHA} --delete-branch",
                      prompt(calls, "land-merge-1"))
        self.assertIn(f"forge-claim land release --repo owner/repo --branch dev --sha {SHA}", prompt(calls, "close-out-1"))
        self.assertIn("rules/branches/dev", prompt(calls, "land-pr-1"))
        close = prompt(calls, "close-out-1")
        for needle in ("deliver-direct", "step 7", f"forge-claim release --repo owner/repo --issue 1 --holder {HOLDER} --reason done",
                       "gh issue close 1 --repo owner/repo"):
            self.assertIn(needle, close)

    def test_pr_body_refs_unless_the_integration_branch_is_the_default(self):
        _, calls, _ = run()
        self.assertIn("Refs #1", prompt(calls, "land-pr-1"))
        _, calls, _ = run(patch={"setup": {"integration_branch": "main"}})
        self.assertIn("Closes #1", prompt(calls, "land-pr-1"))

    def test_landings_never_interleave(self):
        _, calls, _ = run(args=dict(ARGS, issues=[1, 2]))
        land = [c["label"] for c in calls if c["label"].startswith(("renew-", "land-", "close-out-"))]
        owners = [int(re.search(r"-(\d+)(?:-|$)", label).group(1)) for label in land]
        self.assertEqual(sum(1 for a, b in zip(owners, owners[1:]) if a != b), 1)

    def test_land_lock_contention_is_reported(self):
        result, calls, _ = run(replies=dict(contended(), **{
            "land-pr-1": {"pr": 41, "head": SHA, "lock": {"verdict": "land-contended", "lock_sha": B}}}))
        self.assertEqual(row(result, 1)["outcome"], "land-contended")
        for label in ("land-sync-1-1", "land-checks-1-1", "land-merge-1", "land-unlock-1", "release-1", "close-out-1"):
            self.assertNotIn(label, labels(calls))
        self.assertEqual(result["relaunch"]["issues"], [1])
        self.assertEqual(result["relaunch"]["conts"], {"1": ready(1)["cont"]})

    def test_ci_failing_twice_is_reported_and_never_merged(self):
        result, calls, _ = run(patch=folded(CI_RED), replies={
            "land-record-1-1": {"ok": True, "head": FIX, "checks": dict(CI_RED, head=FIX)}})
        self.assertEqual(row(result, 1)["outcome"], "ci-failed")
        self.assertEqual(labels(calls).count("land-fix-1"), 1)
        self.assertIn("land-fix-review-1", labels(calls))
        self.assertIn("land-unlock-1", labels(calls))
        for label in ("land-merge-1", "release-1", "close-out-1"):
            self.assertNotIn(label, labels(calls))

    def test_ci_failing_once_is_fixed_and_lands_the_fix_head(self):
        result, calls, _ = run(patch=folded(CI_RED), replies={
            "land-record-1-1": {"ok": True, "head": FIX}})
        self.assertEqual(row(result, 1)["outcome"], "landed")
        self.assertIn(f"--sha {FIX}\n", prompt(calls, "land-record-1-1"))
        self.assertNotIn(" --wait\n", prompt(calls, "land-record-1-1"))
        self.assertIn(f"--sha {FIX}\n", prompt(calls, "land-merge-1"))
        self.assertIn(f"--match-head-commit {FIX}", prompt(calls, "land-merge-1"))
        ls = labels(calls)
        self.assertLess(ls.index("land-fix-review-1"), ls.index("land-record-1-1"))
        self.assertLess(ls.index("land-record-1-1"), ls.index("land-merge-1"))
        self.assertIn(f"Accepted head: {FIX}", prompt(calls, "land-record-1-1"))

    def test_the_pr_body_records_the_accepted_head(self):
        _, calls, _ = run()
        self.assertIn(f"Accepted head: {SHA}", prompt(calls, "land-pr-1"))
        self.assertNotIn("land-record-1-1", labels(calls))  # no head change after the PR opened

    def test_a_rejected_fix_is_never_recorded_as_accepted(self):
        result, calls, _ = run(patch=folded(CI_RED), replies={
            "land-fix-review-1": {"verdict": "findings", "findings": [{"severity": "important", "summary": "skipped a test"}]}})
        self.assertEqual(row(result, 1)["outcome"], "ci-failed")
        self.assertNotIn("land-record-1-1", labels(calls))
        self.assertNotIn("land-merge-1", labels(calls))
        self.assertEqual(result["relaunch"]["conts"], {"1": ready(1)["cont"]})

    def test_a_declared_check_missing_from_a_passed_reply_is_never_merged(self):
        result, calls, _ = run(patch={"setup": {"required_checks": ["ci", "lint"]}})
        self.assertEqual((row(result, 1)["outcome"], row(result, 1)["stage"], row(result, 1)["missing"]),
                         ("stopped", "checks", ["lint"]))
        self.assertIn('["ci","lint"]', prompt(calls, "land-pr-1"))  # DECLARED as JSON.stringify writes it
        self.assertNotIn("land-merge-1", labels(calls))
        self.assertIn("land-unlock-1", labels(calls))

    def test_every_declared_check_passing_lands(self):
        result, _, _ = run(patch=dict({"setup": {"required_checks": ["ci", "lint"]}},
                                      **folded({"state": "passed", "head": SHA, "required": ["ci", "lint"],
                                                "passed": ["ci", "lint"]})))
        self.assertEqual(row(result, 1)["outcome"], "landed")

    def test_close_out_ends_the_landing_owner_actions(self):
        _, calls, _ = run()
        close = prompt(calls, "close-out-1")
        for reason in ("conflict", "needs-label", "decision"):
            self.assertIn(f"forge-claim owner-action end --repo owner/repo --issue 1 --reason {reason}", close)

    def test_a_conflicting_resync_is_resolved_and_reviewed(self):
        result, calls, _ = run(patch=BEHIND, replies={
            "land-sync-1-1": ABORTED, "land-sync-resolve-1-1": {"status": "done", "conflicted": True, "head": B, "merge_commit": B,
                              "resolved_files": ["x.py"], "tests": ["t"], "notes": "ok"}})
        self.assertEqual(row(result, 1)["outcome"], "landed")
        self.assertIn("land-sync-review-1-1", labels(calls))
        ls = labels(calls)
        self.assertLess(ls.index("land-sync-review-1-1"), ls.index("land-record-1-1"))
        self.assertLess(ls.index("land-record-1-1"), ls.index("land-merge-1"))
        self.assertIn(f"--sha {B}", prompt(calls, "land-record-1-1"))
        self.assertIn(f"--sha {B}", prompt(calls, "land-merge-1"))
        self.assertNotIn("land-ask-1", labels(calls))
        self.assertIn(f"--match-head-commit {B}", prompt(calls, "land-merge-1"))

    def test_a_rejected_resolution_is_sync_review_without_an_owner_action(self):
        result, calls, _ = run(patch=BEHIND, replies={
            "land-sync-1-1": ABORTED, "land-sync-resolve-1-1": {"status": "done", "conflicted": True, "head": B, "merge_commit": B, "notes": "ok"},
            "land-sync-review-1-1": {"verdict": "findings", "findings": [{"severity": "important", "summary": "dropped a change"}]},
            "land-sync-rereview-1-1": {"verdict": "findings", "findings": [{"severity": "important", "summary": "dropped a change"}]}})
        self.assertEqual(row(result, 1)["outcome"], "sync-review")
        for label in ("land-ask-1", "release-1"):
            self.assertNotIn(label, labels(calls))
        ls = labels(calls)
        self.assertLess(ls.index("land-pr-1"), ls.index("land-sync-1-1"))
        self.assertEqual(ls.count("land-unlock-1"), 1)

    def test_a_third_conflict_aborts_and_posts_an_owner_action(self):
        """#913: two conflicted syncs are resolved outside the lock; the third is aborted under it and goes to the owner."""
        result, calls, _ = run(args=dict(ARGS, unattended=True), patch=BEHIND, replies=self.THIRD_CONFLICT)
        self.assertEqual(row(result, 1)["outcome"], "conflict")
        ls = labels(calls)
        self.assertIn("land-record-1-2", ls)
        self.assertNotIn("land-record-1-3", ls)
        self.assertIn("git merge --abort", prompt(calls, "land-sync-1-3"))
        for gone in ("land-sync-resolve-1-3", "land-sync-review-1-3"):
            self.assertNotIn(gone, ls)
        ask = prompt(calls, "land-ask-1")
        self.assertIn(f"--holder {HOLDER} --reason conflict --items-file", ask)
        self.assertIn("conflicts with dev again, after 2 earlier conflicts in one landing, so the landing stopped and accepted no merge", ask)
        self.assertIn({"issue": 1, "reason": "conflict", "comment_id": 99}, result["owner_actions"])
        # Two releases before a resolution, and the wrapper's: the third hold, taken at the second resolution, ends at that head.
        self.assertEqual(ls.count("land-unlock-1"), 3)
        self.assertEqual(ls[-2:], ["land-ask-1", "land-unlock-1"])
        self.assertIn(f"forge-claim land release --repo owner/repo --branch dev --sha {C}\n", prompt(calls, "land-unlock-1"))

    def test_needs_label_posts_an_owner_action(self):
        result, calls, _ = run(args=dict(ARGS, unattended=True), patch=folded(self.NEEDS_LABEL))
        self.assertEqual((row(result, 1)["outcome"], row(result, 1)["label"]), ("needs-label", "raise-me"))
        text = prompt(calls, "land-ask-1")
        self.assertIn("--reason needs-label --items-file", text)
        self.assertIn("raise-me", text)
        self.assertIn({"issue": 1, "reason": "needs-label", "comment_id": 99}, result["owner_actions"])
        self.assertIn("land-unlock-1", labels(calls))
        self.assertNotIn("land-merge-1", labels(calls))

    NEEDS_LABEL = {"state": "needs_label", "head": SHA, "label": "raise-me", "failing": ["gate"]}
    # Run with patch=BEHIND: the folded poll resyncs once and conflicts, the retake's poll is behind again and the second resync conflicts
    # too; its merge is then refused as behind, and the third resync's conflict is past MAX_CONFLICT_ROUNDS (#913).
    THIRD_CONFLICT = {
        "land-sync-1-1": ABORTED, "land-sync-resolve-1-1": {"status": "done", "conflicted": True, "head": B, "merge_commit": B, "notes": "ok"},
        "land-record-1-1": {"ok": True, "head": B, "checks": {"state": "behind", "head": B}},
        "land-sync-1-2": dict(ABORTED, head=B), "land-sync-resolve-1-2": {"status": "done", "conflicted": True, "head": C, "merge_commit": C, "notes": "ok"},
        "land-merge-1": {"merged": False, "behind": True, "notes": "the head branch is not up to date with the base branch"},
        "land-sync-1-3": {"status": "blocked", "conflicted": True, "head": C, "notes": "aborted"}}

    def test_a_session_landing_returns_its_owner_asks_and_posts_nothing(self):
        for patch, replies, reason in ((BEHIND, self.THIRD_CONFLICT, "conflict"),
                                       (folded(self.NEEDS_LABEL), {}, "needs-label")):
            with self.subTest(reason=reason):
                result, calls, _ = run(patch=patch, replies=replies)
                r = row(result, 1)
                self.assertEqual((r["outcome"], r["owner_ask"]["reason"]), (reason, reason))
                self.assertTrue(r["owner_ask"]["items"])
                self.assertNotIn("land-ask-1", labels(calls))
                self.assertEqual(result["owner_actions"], [])
                self.assertIn("land-unlock-1", labels(calls))
                self.assertNotIn("release-1", labels(calls))

    def test_a_close_out_without_the_decision_ended_stays_resumable(self):
        for reply in ({"issue_state": "CLOSED", "released": True},
                      {"issue_state": "CLOSED", "released": True, "decision_ended": False}):
            with self.subTest(reply=reply):
                result, _, _ = run(replies={"close-out-1": reply})
                self.assertEqual((row(result, 1)["outcome"], row(result, 1)["stage"]), ("stopped", "close-out"))
                self.assertIn("1", result["relaunch"]["conts"])

    def test_no_owner_item_asks_to_say_how(self):
        self.assertNotIn("say how", PROGRAM.read_text(encoding="utf-8"))
        result, calls, _ = run(args=dict(ARGS, unattended=True), patch=BEHIND, replies=self.THIRD_CONFLICT)
        self.assertIn("then relaunch the batch", prompt(calls, "land-ask-1"))

    def test_behind_three_times_is_contention(self):
        behind = {"state": "behind", "head": SHA}
        result, calls, _ = run(patch=folded(behind), replies={f"land-checks-1-{k}": behind for k in (2, 3)})
        self.assertEqual(row(result, 1)["outcome"], "land-contended")
        self.assertIn("land-sync-1-2", labels(calls))
        self.assertNotIn("land-sync-1-3", labels(calls))
        self.assertIn("land-unlock-1", labels(calls))

    def test_a_lock_retaken_before_the_merge_resyncs_first(self):
        retaken = [{"merged": False, "notes": "retaken", "lock": {"verdict": "acquired", "lock_sha": SHA}},
                   {"merged": True, "merge_commit": SHA, "notes": "merged"}]
        result, calls, _ = run(replies={"land-merge-1": retaken})
        # the resync answers current (no head change), so nothing is recorded
        self.assertEqual(row(result, 1)["outcome"], "landed")
        ls = of(calls, 1)
        self.assertEqual(ls[ls.index("land-merge-1"):ls.index("close-out-1")],
                         ["land-merge-1", "land-sync-1-1", "land-checks-1-2", "land-merge-1"])
        self.assertNotIn("land-record-1-1", ls)

    def test_a_lost_claim_stops_the_landing_before_the_pr(self):
        result, calls, _ = run(patch={"land-pr-1": {"renew": {"verdict": "not_held", "by": "h2/b9"}}})
        self.assertEqual((row(result, 1)["outcome"], row(result, 1)["by"]), ("claim-lost", "h2/b9"))
        self.assertNotIn("land-sync-1-1", labels(calls))
        self.assertNotIn("land-unlock-1", labels(calls))

    def test_an_errored_or_missing_nested_renew_stops_the_landing(self):
        for renew, detail in (({"verdict": "error", "detail": "forge down"}, "forge down"),
                              (None, "land-pr-1 returned no renew")):
            with self.subTest(renew=renew):
                result, calls, _ = run(patch={"land-pr-1": {"renew": renew}})
                self.assertEqual((row(result, 1)["outcome"], row(result, 1)["stage"], row(result, 1)["reason"]),
                                 ("stopped", "renew", f"renew: {detail}"))
                self.assertNotIn("land-sync-1-1", labels(calls))
                # An error verdict means the prompt ran nothing after it; a missing renew proves nothing, so the lock is released.
                self.assertEqual("land-unlock-1" in labels(calls), renew is None)

    def test_a_lost_claim_at_the_merge_releases_the_lock_and_never_merges(self):
        result, calls, _ = run(patch={"land-merge-1": {"renew": {"verdict": "not_held", "by": "h2/b9"}}})
        self.assertEqual(row(result, 1)["outcome"], "claim-lost")
        self.assertIn("land-unlock-1", labels(calls))
        self.assertNotIn("close-out-1", labels(calls))

    def test_a_pushed_head_other_than_the_ready_head_stops(self):
        result, calls, _ = run(replies={"land-pr-1": {"pr": 41, "head": B}})
        self.assertEqual((row(result, 1)["outcome"], row(result, 1)["stage"]), ("stopped", "head-moved"))
        self.assertNotIn("land-sync-1-1", labels(calls))
        self.assertIn("land-unlock-1", labels(calls))

    def test_an_unmerged_pr_unlocks_and_stops(self):
        result, calls, _ = run(replies={"land-merge-1": {"merged": False, "notes": "head mismatch"}})
        self.assertEqual((row(result, 1)["outcome"], row(result, 1)["stage"]), ("stopped", "merge"))
        self.assertIn("land-unlock-1", labels(calls))
        self.assertNotIn("close-out-1", labels(calls))

    # 870: a merge refused because the integration branch moved outside the land lock.
    REFUSED = {"merged": False, "behind": True, "notes": "the head branch is not up to date with the base branch"}
    MERGED = {"merged": True, "merge_commit": SHA, "notes": "merged"}

    def test_a_merge_refused_as_not_up_to_date_resyncs_and_merges_again(self):
        c = "c" * 40
        result, calls, _ = run(patch=BEHIND, replies={
            "land-sync-1-1": {"status": "done", "conflicted": False, "head": B, "notes": "ok"},
            "land-sync-1-2": {"status": "done", "conflicted": False, "head": c, "notes": "ok"},
            "land-merge-1": [self.REFUSED, self.MERGED]})
        self.assertEqual(row(result, 1)["outcome"], "landed")
        ls = of(calls, 1)
        self.assertEqual(ls[ls.index("land-merge-1"):], ["land-merge-1", "land-sync-1-2", "land-record-1-2", "land-merge-1", "close-out-1"])
        # The lock moved to the new head, and its checks were waited for, before the second merge names it.
        self.assertIn(f"forge-claim land acquire --repo owner/repo --branch dev --sha {c}\n", prompt(calls, "land-record-1-2"))
        merges = [call["prompt"] for call in calls if call["label"] == "land-merge-1"]
        self.assertIn(f"--match-head-commit {B}", merges[0])
        self.assertIn(f"--match-head-commit {c}", merges[1])
        self.assertIn("behind true only when the refusal says the head branch is not up to date with the base branch, "
                      "or the guard says the PR is behind its base, else false.", merges[0])
        self.assertIn("behind", schema_of(calls, "land-merge-1")["properties"])

    def test_the_refusal_budget_is_independent_of_the_resyncs_already_run(self):
        c, d = "c" * 40, "d" * 40
        spent = {
            "land-sync-1-1": {"status": "done", "conflicted": False, "head": B, "notes": "ok"},
            "land-record-1-1": {"ok": True, "head": B, "checks": {"state": "behind", "head": B}},
            "land-sync-1-2": {"status": "done", "conflicted": False, "head": c, "notes": "ok"},
            "land-sync-1-3": {"status": "done", "conflicted": False, "head": d, "notes": "ok"},
            "land-merge-1": [self.REFUSED, self.MERGED]}
        result, calls, _ = run(patch=BEHIND, replies=spent)
        self.assertEqual(row(result, 1)["outcome"], "landed")
        ls = of(calls, 1)
        self.assertEqual(ls[ls.index("land-merge-1"):], ["land-merge-1", "land-sync-1-3", "land-record-1-3", "land-merge-1", "close-out-1"])
        # A behind answer after the refusal's resync is still counted against MAX_SYNCS alone, which is spent here.
        behind_again = dict(spent, **{"land-record-1-3": {"ok": True, "head": d, "checks": {"state": "behind", "head": d}}})
        result, calls, _ = run(patch=BEHIND, replies=behind_again)
        self.assertEqual(row(result, 1)["outcome"], "land-contended")
        self.assertEqual(labels(calls).count("land-merge-1"), 1)
        self.assertNotIn("land-sync-1-4", labels(calls))

    def test_a_refusal_resync_leaves_the_behind_budget_whole(self):
        # The first poll passes, so no resync ran before the refusal: its resync must not count against MAX_SYNCS.
        c, d = "c" * 40, "d" * 40
        result, calls, _ = run(replies={
            "land-merge-1": [self.REFUSED, self.MERGED],
            "land-sync-1-1": {"status": "done", "conflicted": False, "head": B, "notes": "ok"},
            "land-record-1-1": {"ok": True, "head": B, "checks": {"state": "behind", "head": B}},
            "land-sync-1-2": {"status": "done", "conflicted": False, "head": c, "notes": "ok"},
            "land-record-1-2": {"ok": True, "head": c, "checks": {"state": "behind", "head": c}},
            "land-sync-1-3": {"status": "done", "conflicted": False, "head": d, "notes": "ok"}})
        self.assertEqual(row(result, 1)["outcome"], "landed")
        ls = of(calls, 1)
        self.assertEqual(ls[ls.index("land-merge-1"):],
                         ["land-merge-1", "land-sync-1-1", "land-record-1-1", "land-sync-1-2", "land-record-1-2",
                          "land-sync-1-3", "land-record-1-3", "land-merge-1", "close-out-1"])

    def test_a_merge_refused_as_not_up_to_date_past_its_budget_stops(self):
        result, calls, _ = run(replies={"land-merge-1": self.REFUSED})
        self.assertEqual((row(result, 1)["outcome"], row(result, 1)["stage"]), ("stopped", "merge"))
        ls = of(calls, 1)
        self.assertEqual(ls.count("land-merge-1"), 3)
        self.assertEqual([label for label in ls if label.startswith("land-sync-")], ["land-sync-1-1", "land-sync-1-2"])
        self.assertIn("land-unlock-1", ls)
        self.assertNotIn("close-out-1", ls)

    def test_a_refusal_that_is_not_behind_stops_at_the_merge_without_a_resync(self):
        for refusal in (dict(self.REFUSED, behind=False), {"merged": False, "notes": "head mismatch"}):
            with self.subTest(refusal=refusal):
                result, calls, _ = run(replies={"land-merge-1": [refusal, self.MERGED]})
                self.assertEqual((row(result, 1)["outcome"], row(result, 1)["stage"]), ("stopped", "merge"))
                self.assertEqual(labels(calls).count("land-merge-1"), 1)
                self.assertNotIn("land-sync-1-1", labels(calls))

    def test_non_code_criteria_hold_the_issue_open(self):
        acceptance = [{"id": "AC1", "text": "works", "kind": "code"}, {"id": "AC2", "text": "live", "kind": "evidence"}]
        result, calls, _ = run(children={"1": ready(1, acceptance)},
                               replies={"close-out-1": {"issue_state": "OPEN", "released": True, "decision_ended": True, "notes": "held"}})
        self.assertEqual(row(result, 1)["outcome"], "landed-held")
        close = prompt(calls, "close-out-1")
        self.assertNotIn("gh issue close", close)
        self.assertIn("needs-verification", close)

    def test_the_pr_step_reuses_only_a_pr_whose_head_is_the_batch_branch(self):
        text = prompt(run()[1], "land-pr-1")
        self.assertIn("If an open PR with head issue-1-x exists", text)
        self.assertIn("Never reuse or edit a PR whose head is another branch", text)
        self.assertNotIn("or one against dev for this issue", text)

    def test_a_landing_stopped_after_the_merge_is_closed_out_by_the_relaunch(self):
        first, _, _ = run(replies={"close-out-1": {"issue_state": "OPEN", "released": False, "notes": "release errored"}})
        self.assertEqual((row(first, 1)["outcome"], row(first, 1)["stage"]), ("stopped", "close-out"))
        relaunch = first["relaunch"]
        self.assertEqual(relaunch["issues"], [1])
        done = {"stage": "done", "pr": 41, "merged": True, "acceptance": [{"id": "AC1", "text": "works", "kind": "code"}],
                "close_out": {"issue_state": "CLOSED", "released": True}}
        second, calls, _ = run(args=relaunch,
                               patch={"facts-1": {**landing(41), "claim": {"verdict": "held_by", "by": HOLDER}}},
                               children={"1": done})
        self.assertEqual((row(second, 1)["outcome"], row(second, 1)["pr"]), ("landed", 41))
        self.assertIsNone(second["relaunch"])
        self.assertEqual(child(calls, 1)["args"]["cont"], relaunch["conts"]["1"])
        end = prompt(calls, "recover-end-1")
        for reason in ("conflict", "needs-label"):
            self.assertIn(f"forge-claim owner-action end --repo owner/repo --issue 1 --reason {reason}", end)
        self.assertNotIn("land-pr-1", labels(calls))

    def test_an_adopted_pr_merged_then_stopped_at_close_out_is_closed_out_by_the_relaunch(self):
        first, _, _ = run(patch={"facts-1": {"open_pr": OPEN_PR, "claim": {"verdict": "held_by", "by": HOLDER}}},
                          replies={"close-out-1": {"issue_state": "OPEN", "released": False, "notes": "release errored"}})
        self.assertEqual((row(first, 1)["outcome"], row(first, 1)["stage"]), ("stopped", "close-out"))
        cont = first["relaunch"]["conts"]["1"]
        self.assertEqual(cont["setup"]["holder"], HOLDER)
        self.assertEqual(cont["setup"]["branch"], "issue-1-x")
        self.assertEqual(cont["setup"]["worktree"], "/r/.wt/w-issue-1-x")
        self.assertEqual(cont["plan"]["acceptance"], [{"id": "AC1", "text": "works", "kind": "code"}])
        self.assertEqual(cont["pr"], OPEN_PR["number"])
        done = {"stage": "done", "pr": 41, "merged": True, "acceptance": [{"id": "AC1", "text": "works", "kind": "code"}],
                "close_out": {"issue_state": "CLOSED", "released": True}}
        second, calls, _ = run(args=first["relaunch"],
                               patch={"facts-1": {**landing(41), "claim": {"verdict": "held_by", "by": HOLDER}}},
                               children={"1": done})
        self.assertEqual((row(second, 1)["outcome"], row(second, 1)["pr"]), ("landed", 41))
        self.assertEqual(child(calls, 1)["args"]["cont"], cont)
        self.assertNotIn("land-pr-1", labels(calls))

    def test_a_relaunched_merged_landing_with_open_criteria_is_held(self):
        cont = {"setup": {"holder": HOLDER, "branch": "issue-1-x", "worktree": "/r/.wt/w-issue-1-x"}, "pr": 41}
        done = {"stage": "done", "pr": 41, "merged": True, "acceptance": [{"id": "AC2", "text": "live", "kind": "evidence"}],
                "close_out": {"issue_state": "OPEN", "released": True}}
        result, _, _ = run(args=dict(ARGS, conts={"1": cont}),
                           patch={"facts-1": {**landing(41), "claim": {"verdict": "held_by", "by": HOLDER}}},
                           children={"1": done})
        self.assertEqual(row(result, 1)["outcome"], "landed-held")

    def test_a_relaunched_merged_landing_whose_hold_closed_the_issue_is_landed_and_releases_dependents(self):
        cont = {"setup": {"holder": HOLDER, "branch": "issue-1-x", "worktree": "/r/.wt/w-issue-1-x"}, "pr": 41}
        done = {"stage": "done", "pr": 41, "merged": True, "acceptance": [{"id": "AC2", "text": "live", "kind": "evidence"}],
                "close_out": {"issue_state": "CLOSED", "released": True}}
        result, calls, _ = run(args=dict(ARGS, issues=[1, 2], conts={"1": cont}),
                               patch={"facts-1": {**landing(41), "claim": {"verdict": "held_by", "by": HOLDER}},
                                      "facts-2": blocked_by(1)},
                               children={"1": done})
        self.assertEqual(row(result, 1)["outcome"], "landed")
        self.assertNotEqual(row(result, 2)["outcome"], "waits-verification")
        self.assertIn("acquire-2", labels(calls))

    def test_a_merged_pr_without_a_forwarded_cont_stays_a_duplicate(self):
        result, calls, _ = run(patch={"facts-1": {**closing(41), "claim": {"verdict": "held_by", "by": HOLDER}}})
        self.assertEqual(row(result, 1)["outcome"], "duplicate")
        self.assertEqual(labels(calls), ["setup", "facts-1"])

    def test_a_close_out_that_leaves_the_wrong_state_is_stopped(self):
        result, _, _ = run(replies={"close-out-1": {"issue_state": "OPEN", "released": True, "notes": "x"}})
        self.assertEqual((row(result, 1)["outcome"], row(result, 1)["stage"]), ("stopped", "close-out"))


class RerunAndContendedRetryTest(unittest.TestCase):
    """#818: a rerun with no new commit goes back to the checks poll, and a land-contended wait is retried within a bound."""

    RERAN = {"status": "done", "start_head": SHA, "commit": SHA, "notes": "cache HTTP 416 in setup; reran the failed jobs"}
    WAIT_OUT = {"land-pr-1": {"pr": 41, "head": SHA, "lock": {"verdict": "land-contended", "lock_sha": B}}}

    def test_a_rerun_with_an_unchanged_head_polls_again_and_lands(self):
        result, calls, _ = run(patch=folded(CI_RED), replies={"land-fix-1": self.RERAN})
        self.assertEqual(row(result, 1)["outcome"], "landed")
        ls = of(calls, 1)
        self.assertEqual(ls[ls.index("land-pr-1"):],
                         ["land-pr-1", "land-fix-1", "land-checks-1-2", "land-merge-1", "close-out-1"])
        self.assertIn(f"--match-head-commit {SHA}", prompt(calls, "land-merge-1"))

    def test_a_rerun_that_is_still_red_is_ci_failed_and_never_merged(self):
        result, calls, _ = run(patch=folded(CI_RED), replies={"land-fix-1": self.RERAN, "land-checks-1-2": CI_RED})
        self.assertEqual((row(result, 1)["outcome"], row(result, 1)["failing"]), ("ci-failed", ["ci"]))
        ls = labels(calls)
        self.assertEqual(ls.count("land-fix-1"), 1)
        self.assertEqual(ls.count("land-unlock-1"), 1)
        for label in ("land-fix-review-1", "land-record-1-1", "land-checks-1-3", "land-merge-1", "close-out-1"):
            self.assertNotIn(label, ls)

    def test_a_fix_round_that_did_not_finish_is_still_ci_failed(self):
        for fix in (None, {"status": "blocked", "commit": SHA, "notes": "stuck"}, {"status": "done", "notes": "no sha"}):
            with self.subTest(fix=fix):
                result, calls, _ = run(patch=folded(CI_RED), replies={"land-fix-1": fix})
                self.assertEqual((row(result, 1)["outcome"], row(result, 1)["reason"]),
                                 ("ci-failed", "the fix round did not finish; failing checks ci"))
                self.assertNotIn("land-checks-1-2", labels(calls))
                self.assertNotIn("land-merge-1", labels(calls))

    def test_the_fix_prompt_carries_the_commit_scope_once_before_its_push(self):
        """A fix agent stages by path only what its fix changed: one committed a lock file a tool had generated."""
        scope = ("Before committing, read git status in the worktree you commit in and stage by path only the files the fix "
                 "itself changed or created; never run git add -A, git commit -a or git add on a directory (the dot included); "
                 "a lock file, a generated file or an untracked file the fix did not need is left unstaged and named in notes.")
        _, calls, _ = run(patch=folded(CI_RED), replies={"land-fix-1": self.RERAN})
        text = prompt(calls, "land-fix-1")
        self.assertEqual(text.count(scope), 1)
        self.assertLess(text.index(scope), text.index("When the failure has no cause in the code"))

    def test_the_fix_prompt_names_the_rerun_of_a_failure_with_no_code_cause(self):
        _, calls, _ = run(patch=dict({"setup": {"unset_env": ["GITHUB_TOKEN"]}}, **folded(CI_RED)),
                          replies={"land-fix-1": self.RERAN})
        text = prompt(calls, "land-fix-1")
        for needle in ("no cause in the code", "infrastructure, cache or network error in a setup step",
                       "unset GITHUB_TOKEN && gh run rerun <run-id> --repo owner/repo --failed", "once",
                       "do not wait for them", "status done", "the head unchanged", "the program then polls",
                       "a regression test", "Never weaken, skip or delete a test or check"):
            with self.subTest(needle=needle):
                self.assertIn(needle, text)

    def test_a_contended_wait_is_retried_and_lands(self):
        result, calls, _ = run(replies=self.WAIT_OUT)
        self.assertEqual((row(result, 1)["outcome"], row(result, 1)["pr"]), ("landed", 41))
        ls = of(calls, 1)
        self.assertEqual(ls[ls.index("land-pr-1"):],
                         ["land-pr-1", "land-lock-1-1", "land-checks-1-1", "land-merge-1", "close-out-1"])
        text = prompt(calls, "land-lock-1-1")
        self.assertIn(f"forge-claim renew --repo owner/repo --issue 1 --holder {HOLDER} --branch issue-1-x", text)
        self.assertIn(f"forge-claim land acquire --repo owner/repo --branch dev --sha {SHA} --wait\n", text)
        self.assertIn("ends in --wait gets more: the flag takes no value", text)
        self.assertNotIn("--wait 60", text)
        schema = schema_of(calls, "land-lock-1-1")
        self.assertEqual(schema["required"], ["renew"])
        self.assertLessEqual(RENEW_READ, set(schema["properties"]["renew"]["properties"]))
        self.assertIn("land-contended", object_branch(schema["properties"]["lock"])["properties"]["verdict"]["enum"])
        self.assertIn(f"forge-claim land release --repo owner/repo --branch dev --sha {SHA}", prompt(calls, "close-out-1"))
        self.assertIsNone(result["relaunch"])

    def test_a_wait_contended_on_every_retry_ends_land_contended_after_the_bound(self):
        result, calls, _ = run(replies=dict(contended(), **self.WAIT_OUT))
        self.assertEqual(row(result, 1)["outcome"], "land-contended")
        ls = of(calls, 1)
        self.assertEqual(ls[ls.index("land-pr-1"):], ["land-pr-1", "land-lock-1-1", "land-lock-1-2", "land-lock-1-3"])
        self.assertEqual(result["relaunch"]["issues"], [1])
        self.assertEqual(result["relaunch"]["conts"], PRE_MERGE_CONTS)

    def test_a_later_retry_that_acquires_lands(self):
        held = {"lock": {"verdict": "land-contended"}}
        result, calls, _ = run(replies=dict(self.WAIT_OUT, **{"land-lock-1-1": held, "land-lock-1-2": held}))
        self.assertEqual(row(result, 1)["outcome"], "landed")
        self.assertEqual([l for l in labels(calls) if l.startswith("land-lock-")],
                         ["land-lock-1-1", "land-lock-1-2", "land-lock-1-3"])

    def test_a_claim_lost_during_a_contended_retry_is_claim_lost(self):
        result, calls, _ = run(replies=dict(self.WAIT_OUT, **{
            "land-lock-1-1": {"lock": {"verdict": "land-contended"}},
            "land-lock-1-2": {"renew": {"verdict": "not_held", "by": "h2/b9"}, "lock": None}}))
        self.assertEqual((row(result, 1)["outcome"], row(result, 1)["by"]), ("claim-lost", "h2/b9"))
        ls = labels(calls)
        self.assertEqual(ls.count("land-lock-1-2"), 1)
        for label in ("land-lock-1-3", "land-checks-1-1", "land-merge-1", "land-unlock-1", "close-out-1"):
            self.assertNotIn(label, ls)

    def test_a_retry_refused_by_another_holder_ends_without_another_wait(self):
        for verdict in ("held_by", "lost_to"):
            with self.subTest(verdict=verdict):
                result, calls, _ = run(replies=dict(self.WAIT_OUT, **{
                    "land-lock-1-1": {"lock": {"verdict": verdict, "lock_sha": B, "by": "h2/b9"}}}))
                self.assertEqual(row(result, 1)["outcome"], "land-contended")
                for label in ("land-lock-1-2", "land-checks-1-1", "land-merge-1", "land-unlock-1"):
                    self.assertNotIn(label, labels(calls))

    def test_a_lost_or_errored_retry_stops_and_releases_the_lock_it_may_hold(self):
        cases = ((None, "land-lock", 1), ("throw", "land", 1),
                 ({"lock": {"verdict": "error", "detail": "gh failed"}}, "land-lock", 1),
                 ({"renew": {"verdict": "error", "detail": "forge down"}, "lock": None}, "renew", 0))
        for reply, stage, unlocks in cases:
            with self.subTest(reply=reply):
                result, calls, _ = run(replies=dict(self.WAIT_OUT, **{"land-lock-1-1": reply}))
                self.assertEqual((row(result, 1)["outcome"], row(result, 1)["stage"]), ("stopped", stage))
                ls = labels(calls)
                self.assertEqual(ls.count("land-unlock-1"), unlocks)
                self.assertNotIn("land-lock-1-2", ls)
                self.assertNotIn("land-merge-1", ls)
                self.assertEqual(result["relaunch"]["conts"], PRE_MERGE_CONTS)
                if unlocks:
                    self.assertIn(f"forge-claim land release --repo owner/repo --branch dev --sha {SHA}\n",
                                  prompt(calls, "land-unlock-1"))

    def test_a_transient_renew_recalls_the_retry_once(self):
        result, calls, _ = run(replies=dict(self.WAIT_OUT, **{
            "land-lock-1-1": [{"renew": TRANSIENT, "lock": None}, {"lock": {"verdict": "acquired", "lock_sha": SHA}}]}))
        self.assertEqual(row(result, 1)["outcome"], "landed")
        self.assertEqual(labels(calls).count("land-lock-1-1"), 2)


class SpecPrTest(unittest.TestCase):
    """#752: only a PR that closes the issue is a duplicate; a forwarded cont re-adopts only its own landing."""

    MINE, SPEC = "d" * 40, "5" * 40
    CONT = {"setup": {"holder": HOLDER, "branch": "issue-1-x", "worktree": "/r/.wt/w-issue-1-x"},
            "done": [{"n": 1, "commit": "d" * 40}]}
    HELD_DONE = {"stage": "done", "pr": 41, "merged": True, "acceptance": [{"id": "AC2", "text": "live", "kind": "evidence"}],
                 "close_out": {"issue_state": "OPEN", "released": True}}

    def test_a_refs_only_merged_pr_is_no_duplicate(self):
        result, _, _ = run(patch={"facts-1": {"merged_refs": [{"number": 7, "closes": False}]}})
        self.assertEqual(row(result, 1)["outcome"], "landed")

    def test_a_closing_merged_pr_is_a_duplicate(self):
        result, calls, _ = run(patch={"facts-1": closing(5)})
        self.assertEqual((row(result, 1)["outcome"], row(result, 1)["pr"]), ("duplicate", 5))
        self.assertEqual(labels(calls), ["setup", "facts-1"])

    def test_a_refs_landing_of_a_forwarded_cont_is_closed_out_not_skipped(self):
        facts = dict(HELD, labels=["needs-verification"], merged_refs=[{"number": 41, "closes": False}],
                     landed=[{"number": 7, "commits": [self.SPEC]}, {"number": 41, "commits": [self.SPEC, self.MINE]}])
        result, calls, _ = run(args=dict(ARGS, conts={"1": self.CONT}), patch={"facts-1": facts},
                               children={"1": self.HELD_DONE})
        self.assertEqual(row(result, 1)["outcome"], "landed-held")
        self.assertEqual(child(calls, 1)["args"]["cont"], self.CONT)

    def test_a_spec_pr_on_the_cont_branch_is_not_its_landing(self):
        facts = dict(HELD, labels=["needs-verification"], landed=[{"number": 7, "commits": [self.SPEC]}])
        for cont in (self.CONT, {"setup": self.CONT["setup"], "claim_incomplete": True}):
            with self.subTest(cont=cont):
                result, calls, _ = run(args=dict(ARGS, conts={"1": cont}), patch={"facts-1": facts})
                self.assertEqual(row(result, 1)["outcome"], "needs-verification")
                self.assertEqual(labels(calls), ["setup", "facts-1"])

    def test_the_landing_is_read_on_the_cont_branch(self):
        renamed = {"setup": dict(self.CONT["setup"], branch="issue-1-old-title"), "done": self.CONT["done"]}
        _, calls, _ = run(args=dict(ARGS, conts={"1": renamed}))
        self.assertIn("--state merged --head issue-1-old-title", prompt(calls, "facts-1"))
        _, calls, _ = run(args=dict(ARGS, conts={"1": {"setup": {"holder": HOLDER}, "pr": 41}}))
        self.assertIn("--state merged --head <branch>", prompt(calls, "facts-1"))
        _, calls, _ = run(args=dict(ARGS, conts={"1": {"setup": {"holder": HOLDER, "branch": "issue-1-x"}}}))
        self.assertNotIn("--state merged --head", prompt(calls, "facts-1"))

    def test_an_unrelated_closing_pr_does_not_re_adopt_a_forwarded_cont(self):
        facts = dict(HELD, **closing(5), landed=[])
        for cont in (self.CONT, {"setup": self.CONT["setup"], "pr": 41}):
            with self.subTest(cont=cont):
                result, calls, _ = run(args=dict(ARGS, conts={"1": cont}), patch={"facts-1": facts})
                self.assertEqual((row(result, 1)["outcome"], row(result, 1)["pr"]), ("duplicate", 5))
                self.assertEqual(labels(calls), ["setup", "facts-1"])

    def test_a_close_out_cont_with_its_pr_re_adopts_a_refs_landing(self):
        cont = {"setup": {"holder": HOLDER, "branch": "issue-1-x", "worktree": "/r/.wt/w-issue-1-x"}, "pr": 41}
        facts = dict(HELD, labels=["needs-verification"], landed=[{"number": 41, "commits": []}])
        result, _, _ = run(args=dict(ARGS, conts={"1": cont}), patch={"facts-1": facts}, children={"1": self.HELD_DONE})
        self.assertEqual(row(result, 1)["outcome"], "landed-held")


class AllChecksLandTest(unittest.TestCase):
    """#756: the landing waits for every check on head, required or not."""

    def test_land_checks_step_lists_every_check_and_can_answer_pending(self):
        _, calls, _ = run(patch=folded({"state": "pending", "head": SHA, "pending": ["e2e"]}))
        # The carried poll names the PR by a placeholder; the standalone poll names it.
        for label, pr in (("land-pr-1", "<the PR number>"), ("land-checks-1-2", "41")):
            for argv in (f"gh pr checks {pr} --repo owner/repo --json name,bucket,link",
                         "gh api repos/owner/repo/rules/branches/dev"):
                self.assertIn(argv, prompt(calls, label))
        schema = object_branch(schema_of(calls, "land-pr-1")["properties"]["checks"])
        self.assertIn("pending", schema["properties"])
        self.assertIn("pending", schema["properties"]["state"]["enum"])

    def test_a_pending_non_required_check_is_waited_for_before_the_merge(self):
        result, calls, _ = run(patch=folded({"state": "passed", "head": SHA, "required": ["ci"], "passed": ["ci"],
                                             "pending": ["e2e"]}), replies={
            "land-checks-1-2": {"state": "passed", "head": SHA, "required": ["ci"], "passed": ["ci", "e2e"]}})
        self.assertEqual(row(result, 1)["outcome"], "landed")
        names = labels(calls)
        self.assertLess(names.index("land-checks-1-2"), names.index("land-merge-1"))
        self.assertNotIn("land-fix-1", names)

    def test_checks_still_pending_after_three_waits_stop_unmerged(self):
        waiting = {"state": "pending", "head": SHA, "pending": ["e2e"]}
        result, calls, _ = run(patch=folded(waiting), replies={f"land-checks-1-{k}": waiting for k in (2, 3)})
        r = row(result, 1)
        self.assertEqual((r["outcome"], r["stage"], r["pending"]), ("stopped", "checks-pending", ["e2e"]))
        names = labels(calls)
        self.assertNotIn("land-merge-1", names)
        self.assertNotIn("land-checks-1-4", names)
        self.assertIn("land-unlock-1", names)

    def test_a_failing_non_required_check_in_a_passed_reply_is_never_merged(self):
        red = {"state": "passed", "head": SHA, "required": ["ci"], "passed": ["ci"], "failing": ["e2e"]}
        result, calls, _ = run(patch=folded(red), replies={"land-record-1-1": {"ok": True, "head": FIX, "checks": dict(red, head=FIX)}})
        self.assertEqual((row(result, 1)["outcome"], row(result, 1)["failing"]), ("ci-failed", ["e2e"]))
        self.assertIn("e2e", prompt(calls, "land-fix-1"))
        self.assertNotIn("land-merge-1", labels(calls))

    def test_an_explicit_failed_state_outranks_a_pending_list(self):
        red = {"state": "failed", "head": SHA, "pending": ["slow"], "details": "e2e failed"}
        result, calls, _ = run(patch=folded(red), replies={"land-record-1-1": {"ok": True, "head": FIX, "checks": dict(red, head=FIX)}})
        r = row(result, 1)
        self.assertEqual((r["outcome"], r["details"]), ("ci-failed", "e2e failed"))
        self.assertIn("e2e failed", prompt(calls, "land-fix-1"))
        self.assertNotIn("land-merge-1", labels(calls))


TRANSIENT = {"verdict": "error", "detail": "gh_failed: dial tcp: connect: network is unreachable", "transient": True}


class TransientTest(unittest.TestCase):
    """#740 D6, D7: a transient acquire or renew is re-called once; a still-transient acquire row is re-queued once."""

    def test_a_transient_acquire_is_called_once_more(self):
        result, calls, _ = run(replies={"acquire-1": [TRANSIENT, {"verdict": "acquired", "comment_id": 7}]})
        self.assertEqual(row(result, 1)["outcome"], "landed")
        self.assertEqual(labels(calls).count("acquire-1"), 2)

    def test_a_row_still_transient_is_requeued_behind_the_waiting_issues(self):
        result, calls, _ = run(args=dict(ARGS, issues=[1, 2, 3]), patch={"setup": {"max_parallel": 1}},
                               replies={"acquire-1": [TRANSIENT, TRANSIENT, {"verdict": "acquired", "comment_id": 7}]})
        self.assertEqual([row(result, n)["outcome"] for n in (1, 2, 3)], ["landed"] * 3)
        ls = labels(calls)
        third = [i for i, label in enumerate(ls) if label == "acquire-1"][2]
        self.assertLess(ls.index("acquire-2"), third)
        self.assertLess(ls.index("acquire-3"), third)

    def test_a_requeued_row_still_transient_stops_at_acquire(self):
        result, calls, _ = run(replies={"acquire-1": TRANSIENT})
        self.assertEqual((row(result, 1)["outcome"], row(result, 1)["stage"], row(result, 1)["transient"]),
                         ("stopped", "acquire", True))
        self.assertEqual(labels(calls).count("acquire-1"), 4)
        self.assertNotIn("child-1", labels(calls))
        self.assertNotIn("release-1", labels(calls))
        self.assertEqual(result["relaunch"]["issues"], [1])

    def test_contention_and_a_plain_error_are_never_called_again(self):
        for reply in ({"verdict": "held_by", "by": "h2/b9"}, {"verdict": "error", "detail": "forge down"},
                      {"verdict": "error", "detail": "forge down", "transient": False}):
            with self.subTest(reply=reply):
                result, calls, _ = run(replies={"acquire-1": reply})
                self.assertEqual(labels(calls).count("acquire-1"), 1)
                self.assertNotIn("transient", row(result, 1))

    def test_a_transient_folded_renew_recalls_its_landing_step_once(self):
        cases = {"land-pr-1": {"pr": 41, "head": SHA},
                 "land-merge-1": {"merged": True, "merge_commit": SHA, "notes": "merged"}}
        for label, second in cases.items():
            with self.subTest(label=label, recovers=True):
                result, calls, _ = run(replies={label: [{"renew": TRANSIENT, "lock": None}, second]})
                self.assertEqual(row(result, 1)["outcome"], "landed")
                self.assertEqual(labels(calls).count(label), 2)
            with self.subTest(label=label, recovers=False):
                result, calls, _ = run(replies={label: {"renew": TRANSIENT, "lock": None}})
                self.assertEqual((row(result, 1)["outcome"], row(result, 1)["stage"]), ("stopped", "renew"))
                self.assertEqual(labels(calls).count(label), 2)

    def test_a_not_held_folded_renew_is_never_called_again(self):
        result, calls, _ = run(patch={"land-pr-1": {"renew": {"verdict": "not_held", "by": "h2/b9"}}})
        self.assertEqual(row(result, 1)["outcome"], "claim-lost")
        self.assertEqual(labels(calls).count("land-pr-1"), 1)

    def test_acquire_and_renew_ask_for_transient(self):
        _, calls, _ = run()
        self.assertEqual(schema_of(calls, "acquire-1")["properties"]["transient"], {"type": "boolean"})
        for label in ("acquire-1", "land-pr-1", "land-merge-1"):
            with self.subTest(label=label):
                self.assertIn("transient", prompt(calls, label))

    def test_every_forge_claim_prompt_gives_the_long_bash_timeout(self):
        timeout = ("a Bash timeout of 20 minutes (1200000 ms). Only a land acquire command that ends in --wait gets more: "
                   "the flag takes no value, so write nothing after it, and the command itself waits for up to 50 minutes and then "
                   "answers land-contended by itself, so give it a Bash timeout of 60 minutes (3600000 ms) and never run it in the background.")
        _, calls, _ = run()
        for label in ("acquire-1", "land-pr-1", "land-merge-1", "close-out-1"):
            with self.subTest(label=label):
                self.assertIn(timeout, prompt(calls, label))
        _, calls, _ = run(replies={"close-out-1": None})
        self.assertIn(timeout, prompt(calls, "land-unlock-1"))

    RETRIED = re.compile(r"forge-claim (?:acquire|renew|release|status|land acquire|land release|owner-action status)\b")

    def test_every_prompt_that_runs_a_retried_forge_claim_command_gives_the_long_bash_timeout(self):
        # Two 30 s timeouts plus the backoff use 120 s before the third try starts, so a command that
        # forge-claim retries needs the long Bash timeout wherever any prompt runs it.
        timeout = "a Bash timeout of 20 minutes (1200000 ms)"
        closed = {"facts-1": {"state": "CLOSED", "claim": {"verdict": "held_by", "by": HOLDER}}}
        seen = set()
        for patch in ({}, closed):
            _, calls, _ = run(patch=patch)
            for call in calls:
                if call["kind"] == "agent" and self.RETRIED.search(call["prompt"]):
                    seen.add(call["label"])
                    with self.subTest(label=call["label"]):
                        self.assertIn(timeout, call["prompt"])
        self.assertTrue({"facts-1", "release-1"} <= seen, seen)


class LandOrderTest(unittest.TestCase):
    """#677, #801: the land lock is taken, waiting, in land-pr before any check, held through the merge,
    a resync runs only on a behind answer, and the last held sha is released after it and on a stop."""

    MERGED = {"status": "done", "conflicted": False, "head": B, "merge_commit": B, "notes": "ok"}

    def test_the_lock_is_taken_with_wait_before_any_check_or_resync(self):
        result, calls, _ = run()
        self.assertEqual(row(result, 1)["outcome"], "landed")
        ls = labels(calls)
        self.assertNotIn("land-sync-1-1", ls)
        text = prompt(calls, "land-pr-1")
        wait = f"forge-claim land acquire --repo owner/repo --branch dev --sha {SHA} --wait"
        self.assertIn(wait, text)
        self.assertLess(text.index(wait), text.index("gh pr checks"))
        self.assertLess(ls.index("land-merge-1"), ls.index("close-out-1"))
        self.assertIn(f"forge-claim land release --repo owner/repo --branch dev --sha {SHA}\n", prompt(calls, "close-out-1"))

    def test_a_waited_acquire_goes_on_to_the_merge(self):
        waited = {"verdict": "acquired", "lock_sha": SHA, "waited_s": 1800, "took_over": "idle"}
        result, calls, _ = run(replies={"land-pr-1": {"pr": 41, "head": SHA, "lock": waited}})
        self.assertEqual(row(result, 1)["outcome"], "landed")
        ls = labels(calls)
        self.assertEqual(ls[ls.index("land-pr-1") + 1], "land-merge-1")
        self.assertIn("--wait", prompt(calls, "land-pr-1"))

    def test_a_non_holding_wait_answer_gives_up_before_any_sync(self):
        for verdict in ("land-contended", "held_by", "lost_to"):
            with self.subTest(verdict=verdict):
                result, calls, _ = run(replies=dict(contended(), **{
                    "land-pr-1": {"pr": 41, "head": SHA, "lock": {"verdict": verdict, "lock_sha": B, "by": "h2/b9"}}}))
                self.assertEqual(row(result, 1)["outcome"], "land-contended")
                for label in ("land-sync-1-1", "land-checks-1-1", "land-merge-1", "land-unlock-1"):
                    self.assertNotIn(label, labels(calls))
                self.assertEqual(result["relaunch"]["conts"], {"1": ready(1)["cont"]})

    def test_a_behind_resync_that_merges_pushes_and_moves_the_lock(self):
        result, calls, _ = run(patch=BEHIND, replies={
            "land-sync-1-1": self.MERGED})
        self.assertEqual(row(result, 1)["outcome"], "landed")
        self.assertIn("After a clean merge, push the result", prompt(calls, "land-sync-1-1"))
        ls = labels(calls)
        self.assertLess(ls.index("land-sync-1-1"), ls.index("land-record-1-1"))
        self.assertLess(ls.index("land-record-1-1"), ls.index("land-merge-1"))
        self.assertIn(f"--sha {B}\n", prompt(calls, "land-record-1-1"))
        self.assertNotIn(" --wait\n", prompt(calls, "land-record-1-1"))
        self.assertIn(f"forge-claim land release --repo owner/repo --branch dev --sha {B}",
                      prompt(calls, "close-out-1"))

    def test_a_failed_move_releases_the_last_held_sha(self):
        result, calls, _ = run(patch=BEHIND, replies={"land-sync-1-1": self.MERGED,
                                        "land-record-1-1": {"ok": True, "head": B, "lock": {
                                            "verdict": "lost_to", "lock_sha": "c" * 40, "by": "h2/b9"}}})
        self.assertEqual(row(result, 1)["outcome"], "land-contended")
        ls = labels(calls)
        self.assertNotIn("land-checks-1-2", ls)
        self.assertEqual(ls.count("land-unlock-1"), 1)
        self.assertIn(f"forge-claim land release --repo owner/repo --branch dev --sha {SHA}\n",
                      prompt(calls, "land-unlock-1"))

    def test_a_move_answering_lost_to_by_this_batch_at_the_old_lock_reads_the_status_and_goes_on(self):
        """#816: a move whose read-back lagged answers lost_to naming this batch and the lock it already held."""
        stale = {"ok": True, "head": B, "lock": {"verdict": "lost_to", "lock_sha": SHA, "by": HOLDER}}
        result, calls, _ = run(patch=BEHIND, replies={
            "land-sync-1-1": self.MERGED, "land-record-1-1": stale,
            "land-status-1-1": {"verdict": "held_by", "lock_sha": B, "by": HOLDER},
            "land-checks-1-2": {"state": "passed", "head": B, "required": ["ci"], "passed": ["ci"]}})
        self.assertEqual(row(result, 1)["outcome"], "landed")
        ls = labels(calls)
        self.assertLess(ls.index("land-record-1-1"), ls.index("land-status-1-1"))
        self.assertLess(ls.index("land-status-1-1"), ls.index("land-checks-1-2"))
        self.assertIn("forge-claim land status --repo owner/repo --branch dev", prompt(calls, "land-status-1-1"))
        self.assertIn(f"forge-claim land release --repo owner/repo --branch dev --sha {B}",
                      prompt(calls, "close-out-1"))

    def test_a_lost_to_that_is_not_this_batchs_own_lock_is_contention_without_a_status_read(self):
        for lock in ({"verdict": "lost_to", "lock_sha": SHA, "by": "h2/b9"},
                     {"verdict": "lost_to", "lock_sha": "c" * 40, "by": HOLDER}):
            with self.subTest(lock=lock):
                result, calls, _ = run(patch=BEHIND, replies={
                    "land-sync-1-1": self.MERGED, "land-record-1-1": {"ok": True, "head": B, "lock": lock}})
                self.assertEqual(row(result, 1)["outcome"], "land-contended")
                self.assertNotIn("land-status-1-1", labels(calls))

    def test_a_status_read_that_does_not_show_the_expected_head_is_contention(self):
        stale = {"ok": True, "head": B, "lock": {"verdict": "held_by", "lock_sha": SHA, "by": HOLDER}}
        for status in ({"verdict": "held_by", "lock_sha": SHA, "by": HOLDER},
                       {"verdict": "held_by", "lock_sha": "c" * 40, "by": "h2/b9"}, {"verdict": "free"}):
            with self.subTest(status=status):
                result, calls, _ = run(patch=BEHIND, replies={
                    "land-sync-1-1": self.MERGED, "land-record-1-1": stale, "land-status-1-1": status})
                self.assertEqual(row(result, 1)["outcome"], "land-contended")
                self.assertNotIn("land-checks-1-2", labels(calls))
                self.assertIn(f"forge-claim land release --repo owner/repo --branch dev --sha {SHA}\n",
                              prompt(calls, "land-unlock-1"))

    def test_a_failed_or_lost_status_read_keeps_the_moved_lock_a_release_target(self):
        """The read-back proves nothing when it fails: the move may have landed, so cleanup releases both shas."""
        stale = {"ok": True, "head": B, "lock": {"verdict": "lost_to", "lock_sha": SHA, "by": HOLDER}}
        again = (f"When it prints not_held with lock_sha {B}, run alone and exactly: "
                 f"forge-claim land release --repo owner/repo --branch dev --sha {B}")
        for status in (None, {"verdict": "error", "detail": "gh failed"}):
            with self.subTest(status=status):
                result, calls, _ = run(patch=BEHIND, replies={
                    "land-sync-1-1": self.MERGED, "land-record-1-1": stale, "land-status-1-1": status})
                self.assertEqual(row(result, 1)["outcome"], "land-contended")
                text = prompt(calls, "land-unlock-1")
                self.assertIn(f"forge-claim land release --repo owner/repo --branch dev --sha {SHA}\n", text)
                self.assertIn(again, text)

    def test_a_stop_in_a_behind_resync_releases_the_lock(self):
        result, calls, _ = run(patch=BEHIND, replies={"land-sync-1-1": {"status": "blocked", "conflicted": False, "notes": "dirty"}})
        self.assertEqual((row(result, 1)["outcome"], row(result, 1)["stage"]), ("stopped", "land-sync"))
        ls = labels(calls)
        self.assertEqual(ls.count("land-unlock-1"), 1)
        self.assertLess(ls.index("land-pr-1"), ls.index("land-unlock-1"))


def native(*issues):
    """forge-issue read's answer naming these issues of the repository as native blockers."""
    return {"verdict": "read", "blocked_by": [f"owner/repo#{n}" for n in issues]}


def stated(states):
    """forge-issue read's answer (#964): every reference of `states` as a native blocker, with its state."""
    return {"verdict": "read", "blocked_by": sorted(states), "blocked_by_states": states}


def blocked_by(*issues):
    return {"blockers": [{"issue": b, "state": "OPEN"} for b in issues]}


class SyncFixRoundTest(unittest.TestCase):
    """#907: a conflicted sync merge checks for conflict markers itself, and a sync-review finding gets one fix round and one
    re-review before the landing ends as sync-review (#955: the merge is resolved, so the row is not a conflict one)."""

    FIXED = "f" * 40
    CONFLICTED = {"status": "done", "conflicted": True, "head": B, "merge_commit": B, "resolved_files": ["x.py"],
                  "markers_checked": True, "tests": ["t"], "notes": "removed one marker"}
    FOUND = {"verdict": "findings", "findings": [{"severity": "important", "summary": "dropped a sentence dev added"},
                                                 {"severity": "minor", "summary": "style"}]}
    LEFT = {"verdict": "findings", "findings": [{"severity": "important", "summary": "the sentence is still missing"}]}
    UNCHECKED = "The merge was not checked for leftover conflict markers"

    def land(self, **replies):
        return run(patch=BEHIND, replies=dict({"land-sync-1-1": ABORTED, "land-sync-resolve-1-1": self.CONFLICTED}, **replies))

    def test_the_sync_checks_the_merged_tree_for_markers_before_it_commits(self):
        result, calls, _ = self.land()
        self.assertEqual(row(result, 1)["outcome"], "landed")
        sync = prompt(calls, "land-sync-resolve-1-1")
        self.assertIn("run git -C /r/.wt/w-issue-1-x diff --check HEAD and git -C /r/.wt/w-issue-1-x diff --check origin/dev before committing "
                      "and remove each leftover conflict marker both report (same file and line) in a file you resolved by hand; "
                      "every other line they report is content and stays", sync)
        self.assertIn("markers_checked (true when both checks ran)", sync)
        self.assertIn("markers_checked", sync)
        self.assertLess(sync.index("diff --check HEAD"), sync.index("commit the merge"))
        self.assertIn("markers_checked", next(c for c in calls if c["label"] == "land-sync-resolve-1-1")["schema"]["properties"])
        self.assertNotIn("diff --check", prompt(calls, "land-sync-1-1"))
        self.assertNotIn(self.UNCHECKED, prompt(calls, "land-sync-review-1-1"))
        self.assertEqual(land_labels(calls), ["land-pr-1", "land-sync-1-1", "land-unlock-1", "land-sync-resolve-1-1", "land-sync-review-1-1",
                                              "land-record-1-1", "land-merge-1", "close-out-1"])

    def test_a_resolution_whose_marker_check_did_not_run_is_reviewed_for_markers_in_the_same_call(self):
        for said in ({"markers_checked": False}, {}):
            with self.subTest(said=said):
                reply = dict({k: v for k, v in self.CONFLICTED.items() if k != "markers_checked"}, **said)
                result, calls, _ = self.land(**{"land-sync-resolve-1-1": reply})
                self.assertEqual(row(result, 1)["outcome"], "landed")
                self.assertIn(self.UNCHECKED, prompt(calls, "land-sync-review-1-1"))
                self.assertEqual(labels(calls), labels(self.land()[1]))

    def test_a_finding_is_fixed_rereviewed_and_landed_at_the_fix(self):
        result, calls, _ = self.land(**{"land-sync-review-1-1": self.FOUND})
        self.assertEqual(row(result, 1)["outcome"], "landed")
        self.assertEqual(land_labels(calls), [
            "land-pr-1", "land-sync-1-1", "land-unlock-1", "land-sync-resolve-1-1", "land-sync-review-1-1", "land-sync-fix-1-1",
            "land-sync-rereview-1-1", "land-record-1-1", "land-merge-1", "close-out-1"])
        fix = next(c for c in calls if c["label"] == "land-sync-fix-1-1")
        self.assertEqual((fix["agentType"], fix["model"]), ("implementer", "sonnet"))
        for text in ("dropped a sentence dev added", f"merge commit {B}", "never redo or rewrite the merge",
                     "stage by path only the files the fix itself changed or created",
                     "git -C /r/.wt/w-issue-1-x push origin issue-1-x"):
            self.assertIn(text, fix["prompt"])
        self.assertNotIn("style", fix["prompt"])
        again = next(c for c in calls if c["label"] == "land-sync-rereview-1-1")
        self.assertEqual(again["agentType"], "reviewer")
        self.assertIn(f"diff {B}..{self.FIXED}", again["prompt"])
        self.assertIn("dropped a sentence dev added", again["prompt"])
        # The lock is taken again at the fix in the record step, its checks are waited for there, and the merge names it.
        record = prompt(calls, "land-record-1-1")
        self.assertIn(f"changed to {self.FIXED}", record)
        self.assertIn(f"--sha {self.FIXED} --wait\n", record)
        self.assertIn("wait for every check", record)
        self.assertIn(f"--match-head-commit {self.FIXED}", prompt(calls, "land-merge-1"))
        self.assertIn(f"--sha {self.FIXED}", prompt(calls, "close-out-1"))
        self.assertEqual(labels(calls).count("land-unlock-1"), 1)

    def test_a_finding_that_survives_the_fix_round_ends_sync_review_with_its_reason(self):
        left = {"verdict": "findings", "findings": [dict(self.LEFT["findings"][0], file="docs/x.md"), {"severity": "minor", "summary": "style"}]}
        out = run_full(patch=BEHIND, replies={"land-sync-1-1": ABORTED, "land-sync-resolve-1-1": self.CONFLICTED,
                                              "land-sync-review-1-1": self.FOUND, "land-sync-rereview-1-1": left})
        result, calls, logs = out["result"], out["calls"], out["logs"]
        got = row(result, 1)
        reason = (f"sync-review of merge {B}: a finding survived the fix round; unaccepted fix commit {self.FIXED}; "
                  "finding docs/x.md: the sentence is still missing")
        self.assertEqual((got["outcome"], got["reason"]), ("sync-review", reason))
        self.assertNotIn("detail", got)
        # The table, the log and the relaunch show the same line; no owner action is posted, as for any other open row.
        self.assertIn(f"#1: sync-review ({reason})", logs)
        self.assertEqual(result["relaunch"]["reasons"], {"1": reason})
        self.assertEqual(result["owner_actions"], [])
        self.assertNotIn("owner_ask", got)
        # The pushed, unaccepted fix is named on the row.
        self.assertEqual(got["fix"], {"commit": self.FIXED, "notes": "ok"})
        ls = labels(calls)
        for gone in ("land-record-1-1", "land-merge-1", "land-ask-1", "release-1", "land-sync-fix-1-2"):
            self.assertNotIn(gone, ls)
        self.assertEqual((ls.count("land-sync-fix-1-1"), ls.count("land-sync-rereview-1-1"), ls.count("land-unlock-1")), (1, 1, 1))
        # The lock was released before the resolution, at the head it was held at, and nothing took it again.
        self.assertIn(f"forge-claim land release --repo owner/repo --branch dev --sha {SHA}\n", prompt(calls, "land-unlock-1"))

    def test_a_surviving_finding_with_a_long_summary_keeps_the_fix_commit_within_the_cap(self):
        long = {"verdict": "findings", "findings": [{"severity": "critical", "file": "x.py", "summary": "the merge dropped a guard " * 40}]}
        got = row(self.land(**{"land-sync-review-1-1": self.FOUND, "land-sync-rereview-1-1": long})[0], 1)
        self.assertEqual((got["outcome"], len(got["reason"])), ("sync-review", 300))
        self.assertTrue(got["reason"].startswith(f"sync-review of merge {B}: a finding survived the fix round; unaccepted fix commit "
                                                 f"{self.FIXED}; finding x.py: the merge dropped a guard"))
        self.assertTrue(got["reason"].endswith("..."))
        self.assertNotIn("\n", got["reason"])

    def test_a_rebuttal_the_rereview_rejects_ends_sync_review_without_a_fix_commit(self):
        rebuttal = {"status": "done", "start_head": B, "commit": B, "notes": "the sentence is on line 12"}
        result, _, _ = self.land(**{"land-sync-review-1-1": self.FOUND, "land-sync-fix-1-1": rebuttal, "land-sync-rereview-1-1": self.LEFT})
        got = row(result, 1)
        self.assertEqual((got["outcome"], got["reason"]), ("sync-review", f"sync-review of merge {B}: a finding survived the fix round "
                                                           "(a rebuttal, no fix commit); finding the sentence is still missing"))

    def test_a_lost_sync_review_ends_sync_review(self):
        got = row(self.land(**{"land-sync-review-1-1": None})[0], 1)
        self.assertEqual((got["outcome"], got["reason"]), ("sync-review", f"sync-review of merge {B}: the sync review returned nothing"))

    def test_an_unresolved_merge_stays_conflict_with_its_own_reason(self):
        """#955: only a merge that was not resolved is a conflict row: a blocked resolution here, the conflict-round bound in
        test_a_third_conflict_aborts_and_posts_an_owner_action."""
        got = row(self.land(**{"land-sync-resolve-1-1": {"status": "blocked", "conflicted": True, "notes": "too tangled"}})[0], 1)
        self.assertEqual((got["outcome"], got["reason"]), ("conflict", "too tangled"))

    def test_a_sync_review_row_is_relaunched_and_readopted_as_a_conflict_row_is(self):
        """#955: the relaunch of a sync-review row differs from that of a conflict row only in its reason, and the new run takes both the same way."""
        survived = self.land(**{"land-sync-review-1-1": self.FOUND, "land-sync-rereview-1-1": self.LEFT})[0]
        blocked = self.land(**{"land-sync-resolve-1-1": {"status": "blocked", "conflicted": True, "notes": "too tangled"}})[0]
        self.assertEqual([row(r, 1)["outcome"] for r in (survived, blocked)], ["sync-review", "conflict"])
        self.assertEqual(without(survived["relaunch"], "reasons"), without(blocked["relaunch"], "reasons"))
        self.assertEqual(survived["relaunch"]["issues"], [1])
        self.assertEqual(survived["relaunch"]["conts"], PRE_MERGE_CONTS)
        runs = [run(args=first["relaunch"], patch={"facts-1": dict(HELD, open_pr=OPEN_PR)},
                    replies={"readopt-1": {"ok": False, "reason": "unaccepted", "detail": self.FIXED}}) for first in (survived, blocked)]
        self.assertEqual(labels(runs[0][1]), labels(runs[1][1]))
        ls = labels(runs[0][1])
        self.assertLess(ls.index("readopt-1"), ls.index("child-1"))
        self.assertLess(ls.index("child-1"), ls.index("land-pr-1"))
        self.assertEqual(row(runs[0][0], 1)["outcome"], "landed")

    def test_a_fix_round_that_does_not_finish_ends_sync_review_without_a_rereview(self):
        fixes = {"nothing": None, "blocked": {"status": "blocked", "notes": "no"},
                 "started elsewhere": {"status": "done", "start_head": "e" * 40, "commit": self.FIXED, "notes": "ok"},
                 "no commit and no evidence": {"status": "done", "start_head": B, "commit": B, "notes": ""}}
        for name, fix in fixes.items():
            with self.subTest(fix=name):
                result, calls, _ = self.land(**{"land-sync-review-1-1": self.FOUND, "land-sync-fix-1-1": fix})
                got = row(result, 1)
                pushed = isinstance(fix, dict) and fix.get("commit") == self.FIXED
                self.assertEqual((got["outcome"], got["reason"]),
                                 ("sync-review", f"sync-review of merge {B}: the sync fix round did not finish; "
                                  + (f"unaccepted fix commit {self.FIXED}; " if pushed else "") + "finding dropped a sentence dev added"))
                self.assertEqual(got.get("fix"), None if fix is None else {k: fix[k] for k in ("commit", "notes") if k in fix})
                ls = labels(calls)
                for gone in ("land-sync-rereview-1-1", "land-record-1-1", "land-merge-1"):
                    self.assertNotIn(gone, ls)
                self.assertEqual(ls.count("land-unlock-1"), 1)

    def test_a_lost_rereview_ends_sync_review(self):
        result, calls, _ = self.land(**{"land-sync-review-1-1": self.FOUND, "land-sync-rereview-1-1": None})
        got = row(result, 1)
        self.assertEqual((got["outcome"], got["reason"]),
                         ("sync-review", f"sync-review of merge {B}: the sync re-review returned nothing; unaccepted fix commit {self.FIXED}; "
                          "finding dropped a sentence dev added"))
        self.assertEqual(got["fix"], {"commit": self.FIXED, "notes": "ok"})
        self.assertEqual(labels(calls).count("land-unlock-1"), 1)

    def test_a_rebuttal_with_evidence_is_adjudicated_and_lands_at_the_merge(self):
        rebuttal = {"status": "done", "start_head": B, "commit": B, "notes": "the sentence is on line 12"}
        result, calls, _ = self.land(**{"land-sync-review-1-1": self.FOUND, "land-sync-fix-1-1": rebuttal})
        self.assertEqual(row(result, 1)["outcome"], "landed")
        # A rebuttal is adjudicated by the full reviewer, never reviewer-lite.
        self.assertEqual([c["agentType"] for c in calls if c["label"] == "land-sync-rereview-1-1"], ["reviewer"])
        again = prompt(calls, "land-sync-rereview-1-1")
        self.assertIn("the rebuttal (no new commit) of", again)
        self.assertIn("Check each rebuttal against the code yourself", again)
        self.assertIn(f"--match-head-commit {B}", prompt(calls, "land-merge-1"))

    def test_the_fix_round_spends_no_resync(self):
        # MAX_SYNCS is two: were the round a resync, the behind answer after it would end land-contended.
        c = "c" * 40
        result, calls, _ = self.land(**{
            "land-sync-review-1-1": self.FOUND,
            "land-record-1-1": {"ok": True, "head": self.FIXED, "checks": {"state": "behind", "head": self.FIXED}},
            "land-sync-1-2": {"status": "done", "conflicted": False, "head": c, "notes": "ok"}})
        self.assertEqual(row(result, 1)["outcome"], "landed")
        self.assertIn(f"--match-head-commit {c}", prompt(calls, "land-merge-1"))

    def test_a_merge_without_conflicts_runs_no_extra_step(self):
        clean = {"status": "done", "conflicted": False, "head": B, "notes": "ok"}
        result, calls, _ = self.land(**{"land-sync-1-1": clean})
        self.assertEqual(row(result, 1)["outcome"], "landed")
        self.assertEqual(land_labels(calls), ["land-pr-1", "land-sync-1-1", "land-record-1-1", "land-merge-1", "close-out-1"])

    def test_both_programs_carry_the_same_wording(self):
        names = ("MARKER_CHECK", "MARKERS_UNCHECKED", "SYNC_FIX", "SYNC_REREVIEW", "COMMIT_SCOPE")
        lines = lambda path: {line.split(" ", 2)[1]: line for line in path.read_text(encoding="utf-8").splitlines()
                              if line.startswith(tuple(f"const {name} = " for name in names))}
        batch, standard = lines(PROGRAM), lines(PROGRAM.with_name("deliver-standard.js"))
        self.assertEqual(sorted(batch), sorted(names))
        self.assertEqual(batch, standard)


class ConflictedSyncOutsideLockTest(unittest.TestCase):
    """#913: a sync merge that conflicts is aborted under the land lock and resolved, tested, reviewed and fixed outside it; the
    reviewed head takes the lock again, waiting, and a clean merge never leaves it."""

    RELEASE = "forge-claim land release --repo owner/repo --branch dev --sha "
    FOUND = {"verdict": "findings", "findings": [{"severity": "important", "summary": "dropped a change"}]}

    def land(self, **replies):
        return run_full(patch=BEHIND, replies=dict({"land-sync-1-1": ABORTED}, **replies))

    def test_a_conflict_is_aborted_released_resolved_and_the_lock_taken_again(self):
        out = self.land()
        result, calls = out["result"], out["calls"]
        self.assertEqual(row(result, 1)["outcome"], "landed")
        self.assertEqual(land_labels(calls), ["land-pr-1", "land-sync-1-1", "land-unlock-1", "land-sync-resolve-1-1", "land-sync-review-1-1",
                                              "land-record-1-1", "land-merge-1", "close-out-1"])
        sync = prompt(calls, "land-sync-1-1")
        self.assertIn("If the merge conflicts, do not resolve it: run git merge --abort inside /r/.wt/w-issue-1-x", sync)
        self.assertIn("confirm no merge is left in progress", sync)
        self.assertIn("conflicted", next(c for c in calls if c["label"] == "land-sync-1-1")["schema"]["properties"]["status"]["enum"])
        # The first hold ends at the head it was taken at, before the resolution starts.
        self.assertIn(f"{self.RELEASE}{SHA}\n", prompt(calls, "land-unlock-1"))
        resolve = prompt(calls, "land-sync-resolve-1-1")
        for text in ("The landing lock is not held while you work", "rev-parse -q --verify MERGE_HEAD", "merge origin/dev",
                     "git -C /r/.wt/w-issue-1-x push origin issue-1-x"):
            self.assertIn(text, resolve)
        # The reviewed head is recorded, then the lock is taken at it with --wait and its checks are polled, in one step.
        record = prompt(calls, "land-record-1-1")
        self.assertIn(f"Accepted head: {B}\n", record)
        self.assertIn(f"forge-claim land acquire --repo owner/repo --branch dev --sha {B} --wait\n", record)
        self.assertLess(record.index("Accepted head:"), record.index("land acquire"))
        self.assertIn("merge-base --is-ancestor origin/dev HEAD", record)
        # The merge keeps its one-shot check, and the second hold is released once, in the close-out call.
        merge = prompt(calls, "land-merge-1")
        self.assertIn(f"--sha {B}\n", merge)
        self.assertIn("Only when lock's verdict is already_held or moved", merge)
        self.assertIn(f"{self.RELEASE}{B}\n", prompt(calls, "close-out-1"))
        self.assertEqual(out["logs"][-1], "#1: landed")

    def test_a_clean_merge_keeps_the_lock(self):
        result, calls, _ = run(patch=BEHIND, replies={"land-sync-1-1": {"status": "done", "conflicted": False, "head": B, "notes": "ok"}})
        self.assertEqual(row(result, 1)["outcome"], "landed")
        self.assertEqual(land_labels(calls), ["land-pr-1", "land-sync-1-1", "land-record-1-1", "land-merge-1", "close-out-1"])
        record = prompt(calls, "land-record-1-1")
        self.assertIn(f"move the cross-host landing lock of the branch dev to the head {B}", record)
        self.assertNotIn("--wait\n", record)

    def test_behind_again_after_the_retake_a_clean_merge_stays_under_the_lock(self):
        out = self.land(**{"land-record-1-1": {"ok": True, "head": B, "lock": {"verdict": "acquired", "lock_sha": B},
                                               "checks": {"state": "behind", "head": B}},
                           "land-sync-1-2": {"status": "done", "conflicted": False, "head": C, "notes": "ok"}})
        result, calls = out["result"], out["calls"]
        self.assertEqual(row(result, 1)["outcome"], "landed")
        self.assertEqual(land_labels(calls), ["land-pr-1", "land-sync-1-1", "land-unlock-1", "land-sync-resolve-1-1", "land-sync-review-1-1",
                                              "land-record-1-1", "land-sync-1-2", "land-record-1-2", "land-merge-1", "close-out-1"])
        again = prompt(calls, "land-record-1-2")
        self.assertIn(f"--sha {C}\n", again)
        self.assertNotIn("--wait\n", again)
        self.assertIn(f"--match-head-commit {C}", prompt(calls, "land-merge-1"))

    def test_behind_again_with_a_second_conflict_is_resolved_outside_the_lock_again(self):
        replies = {"land-sync-1-1": ABORTED,
                   "land-record-1-1": {"ok": True, "head": B, "checks": {"state": "behind", "head": B}},
                   "land-sync-1-2": dict(ABORTED, head=B),
                   "land-sync-resolve-1-2": {"status": "done", "conflicted": True, "head": C, "merge_commit": C, "notes": "ok"}}
        result, calls, _ = run(patch=BEHIND, replies=replies)
        self.assertEqual(row(result, 1)["outcome"], "landed")
        self.assertEqual(land_labels(calls), [
            "land-pr-1", "land-sync-1-1", "land-unlock-1", "land-sync-resolve-1-1", "land-sync-review-1-1", "land-record-1-1",
            "land-sync-1-2", "land-unlock-1", "land-sync-resolve-1-2", "land-sync-review-1-2", "land-record-1-2",
            "land-merge-1", "close-out-1"])
        # Each hold is released once, at the head it was held at.
        unlocks = [c["prompt"] for c in calls if c["label"] == "land-unlock-1"]
        self.assertEqual([self.RELEASE + sha + "\n" in text for sha, text in zip((SHA, B), unlocks)], [True, True])
        self.assertIn(f"--sha {C} --wait\n", prompt(calls, "land-record-1-2"))
        self.assertIn(f"--match-head-commit {C}", prompt(calls, "land-merge-1"))
        # Behind once more after the second round: the sync budget is spent, and the third hold is released by the wrapper.
        result, calls, _ = run(patch=BEHIND, replies=dict(replies, **{"land-record-1-2": {
            "ok": True, "head": C, "checks": {"state": "behind", "head": C}}}))
        got = row(result, 1)
        self.assertEqual((got["outcome"], got["reason"]), ("land-contended", "behind dev after 2 resyncs in all"))
        self.assertNotIn("land-merge-1", labels(calls))
        self.assertEqual(labels(calls).count("land-unlock-1"), 3)
        self.assertIn(f"{self.RELEASE}{C}\n", prompt(calls, "land-unlock-1"))

    def test_a_refused_retake_waits_no_further_and_never_merges(self):
        for verdict in ("land-contended", "held_by", "lost_to"):
            with self.subTest(verdict=verdict):
                result, calls, _ = run(patch=BEHIND, replies={"land-sync-1-1": ABORTED, "land-record-1-1": {
                    "ok": True, "head": B, "lock": {"verdict": verdict, "lock_sha": C, "by": "h2/b9"}, "checks": None},
                    **{f"land-relock-1-{k}": {"lock": {"verdict": "land-contended", "lock_sha": C}} for k in (1, 2, 3)}})
                # Only a wait that ran out is waited for again, as often as a first wait is (LAND_WAIT_RETRIES).
                self.assertEqual([label for label in labels(calls) if label.startswith("land-relock-")],
                                 [f"land-relock-1-{k}" for k in (1, 2, 3)] if verdict == "land-contended" else [])
                got = row(result, 1)
                self.assertEqual((got["outcome"], got["reason"]),
                                 ("land-contended", f"the land lock was not taken again at the reviewed head {B} ({verdict})"))
                ls = labels(calls)
                for gone in ("land-merge-1", "land-checks-1-2", "land-status-1-1", "close-out-1"):
                    self.assertNotIn(gone, ls)
                # Nothing is held after the refusal: the only release is the one before the resolution.
                self.assertEqual(ls.count("land-unlock-1"), 1)
                self.assertLess(ls.index("land-unlock-1"), ls.index("land-sync-resolve-1-1"))
                self.assertEqual(result["relaunch"]["conts"], PRE_MERGE_CONTS)

    def test_a_retake_that_answers_acquired_still_merges_only_on_the_pre_merge_check(self):
        retaken = {"ok": True, "head": B, "lock": {"verdict": "acquired", "lock_sha": B, "waited_s": 1740, "waited_on": [2257]}}
        out = self.land(**{"land-record-1-1": retaken})
        self.assertEqual(row(out["result"], 1)["outcome"], "landed")
        self.assertIn("land-record-1-1: waited 29 min for the land lock of dev behind PR #2257", out["logs"])
        out = self.land(**{"land-record-1-1": retaken,
                           "land-merge-1": {"merged": False, "notes": "held_by", "lock": {"verdict": "held_by", "lock_sha": C}}})
        got = row(out["result"], 1)
        self.assertEqual((got["outcome"], got["reason"]), ("land-contended", "the land lock was not held before the merge (held_by)"))
        self.assertNotIn("close-out-1", labels(out["calls"]))

    def test_a_lost_or_failed_retake_releases_what_it_may_hold(self):
        # No reply: the waiting acquire may have taken the lock at the reviewed head, so the wrapper releases there.
        result, calls, _ = run(patch=BEHIND, replies={"land-sync-1-1": ABORTED, "land-record-1-1": None})
        self.assertEqual((row(result, 1)["outcome"], row(result, 1)["stage"]), ("stopped", "land-record"))
        self.assertEqual(labels(calls).count("land-unlock-1"), 2)
        self.assertIn(f"{self.RELEASE}{B}\n", prompt(calls, "land-unlock-1"))
        self.assertNotIn("land-merge-1", labels(calls))
        # The record step refused before any lock command: nothing is held and nothing more is released.
        result, calls, _ = run(patch=BEHIND, replies={"land-sync-1-1": ABORTED, "land-record-1-1": {
            "ok": False, "head": C, "detail": "the head moved", "lock": None, "checks": None}})
        self.assertEqual((row(result, 1)["outcome"], row(result, 1)["stage"]), ("stopped", "land-record"))
        self.assertEqual(labels(calls).count("land-unlock-1"), 1)

    def test_every_stop_outside_the_lock_releases_once_and_accepts_nothing(self):
        stops = {
            "the resolution is lost": ({"land-sync-resolve-1-1": None}, "stopped"),
            "the resolution is blocked": ({"land-sync-resolve-1-1": {"status": "blocked", "conflicted": True, "notes": "too tangled"}}, "conflict"),
            "the resolution names no head": ({"land-sync-resolve-1-1": {"status": "done", "conflicted": True, "notes": "ok"}}, "stopped"),
            "the review is lost": ({"land-sync-review-1-1": None}, "sync-review"),
            "the fix is lost": ({"land-sync-review-1-1": self.FOUND, "land-sync-fix-1-1": None}, "sync-review"),
            "the finding survives": ({"land-sync-review-1-1": self.FOUND, "land-sync-rereview-1-1": self.FOUND}, "sync-review"),
        }
        for name, (replies, outcome) in stops.items():
            with self.subTest(stop=name):
                out = self.land(**replies)
                result, ls = out["result"], labels(out["calls"])
                self.assertEqual(row(result, 1)["outcome"], outcome)
                self.assertEqual(ls.count("land-unlock-1"), 1)
                self.assertEqual(ls[ls.index("land-sync-1-1") + 1], "land-unlock-1")
                # The accepted head is never rewritten, so a relaunch finds the pushed merge unaccepted and reviews it through the child.
                for gone in ("land-record-1-1", "land-merge-1", "close-out-1"):
                    self.assertNotIn(gone, ls)
                self.assertEqual(result["relaunch"]["conts"], PRE_MERGE_CONTS)

    def test_a_relaunch_after_a_stop_outside_the_lock_goes_through_the_child(self):
        first, _, _ = run(patch=BEHIND, replies={"land-sync-1-1": ABORTED, "land-sync-review-1-1": None})
        result, calls, _ = run(args=first["relaunch"], patch={"facts-1": dict(HELD, open_pr=OPEN_PR)},
                               replies={"readopt-1": {"ok": False, "reason": "unaccepted", "detail": B}})
        ls = labels(calls)
        self.assertLess(ls.index("readopt-1"), ls.index("child-1"))
        self.assertLess(ls.index("child-1"), ls.index("land-pr-1"))
        self.assertEqual(row(result, 1)["outcome"], "landed")

    def test_a_sync_step_that_resolved_the_conflict_itself_is_released_and_reviewed(self):
        resolved = {"status": "done", "conflicted": True, "head": B, "merge_commit": B, "notes": "ok"}
        result, calls, _ = run(patch=BEHIND, replies={"land-sync-1-1": resolved})
        self.assertEqual(row(result, 1)["outcome"], "landed")
        self.assertEqual(land_labels(calls), ["land-pr-1", "land-sync-1-1", "land-unlock-1", "land-sync-review-1-1", "land-record-1-1",
                                              "land-merge-1", "close-out-1"])
        self.assertIn(f"--sha {B} --wait\n", prompt(calls, "land-record-1-1"))
        result, calls, _ = run(patch=BEHIND, replies={"land-sync-1-1": resolved, "land-sync-review-1-1": self.FOUND,
                                                      "land-sync-rereview-1-1": self.FOUND})
        self.assertEqual(row(result, 1)["outcome"], "sync-review")
        self.assertNotIn("land-merge-1", labels(calls))

    def test_a_resolution_that_says_it_merged_cleanly_is_reviewed_all_the_same(self):
        clean = {"land-sync-resolve-1-1": {"status": "done", "conflicted": False, "head": B, "notes": "dev moved"}}
        out = self.land(**clean)
        self.assertEqual(row(out["result"], 1)["outcome"], "landed")
        self.assertEqual(land_labels(out["calls"]), ["land-pr-1", "land-sync-1-1", "land-unlock-1", "land-sync-resolve-1-1",
                                                     "land-sync-review-1-1", "land-record-1-1", "land-merge-1", "close-out-1"])
        self.assertIn(f"merge commit {B}", prompt(out["calls"], "land-sync-review-1-1"))
        self.assertIn(f"--sha {B} --wait\n", prompt(out["calls"], "land-record-1-1"))
        out = self.land(**clean, **{"land-sync-review-1-1": self.FOUND, "land-sync-rereview-1-1": self.FOUND})
        self.assertEqual(row(out["result"], 1)["outcome"], "sync-review")
        self.assertNotIn("land-merge-1", labels(out["calls"]))

    def test_a_resolution_whose_head_is_not_its_reviewed_merge_commit_never_lands(self):
        for name, replies in {
            "resolved outside the lock": {"land-sync-1-1": ABORTED, "land-sync-resolve-1-1": {
                "status": "done", "conflicted": True, "head": C, "merge_commit": B, "notes": "ok"}},
            "resolved by the sync step": {"land-sync-1-1": {"status": "done", "conflicted": True, "head": C, "merge_commit": B, "notes": "ok"}},
        }.items():
            with self.subTest(case=name):
                result, calls, _ = run(patch=BEHIND, replies=replies)
                got = row(result, 1)
                self.assertEqual((got["outcome"], got["stage"]), ("stopped", "land-sync"))
                self.assertEqual(got["reason"], f"land-sync: the resolution names the head {C} and the merge commit {B}: only a reviewed merge commit lands")
                ls = labels(calls)
                for gone in ("land-sync-review-1-1", "land-record-1-1", "land-merge-1"):
                    self.assertNotIn(gone, ls)
                self.assertEqual(ls.count("land-unlock-1"), 1)
        # An abbreviated merge commit of the same head is the same commit.
        out = self.land(**{"land-sync-resolve-1-1": {"status": "done", "conflicted": True, "head": B, "merge_commit": B[:12], "notes": "ok"}})
        self.assertEqual(row(out["result"], 1)["outcome"], "landed")

    def test_a_retake_whose_wait_ran_out_waits_again_like_a_first_wait(self):
        out_of_time = {"ok": True, "head": B, "lock": {"verdict": "land-contended", "lock_sha": C, "waited_s": 3600, "waited_on": [7]}, "checks": None}
        out = self.land(**{"land-record-1-1": out_of_time,
                           "land-relock-1-1": {"lock": {"verdict": "land-contended", "lock_sha": C}},
                           "land-relock-1-2": {"lock": {"verdict": "acquired", "lock_sha": B, "waited_s": 900, "waited_on": [7, 9]}},
                           "land-checks-1-2": {"state": "passed", "head": B, "required": ["ci"], "passed": ["ci"]}})
        result, calls = out["result"], out["calls"]
        self.assertEqual(row(result, 1)["outcome"], "landed")
        # A retried wait polled no checks: the loop polls them itself, under the lock, before the merge.
        self.assertEqual(land_labels(calls), ["land-pr-1", "land-sync-1-1", "land-unlock-1", "land-sync-resolve-1-1", "land-sync-review-1-1",
                                              "land-record-1-1", "land-relock-1-1", "land-relock-1-2", "land-checks-1-2", "land-merge-1",
                                              "close-out-1"])
        again = next(c for c in calls if c["label"] == "land-relock-1-2")
        self.assertEqual((again["agentType"], again["model"]), ("clerk", "sonnet"))
        self.assertIn("forge-claim renew --repo owner/repo --issue 1", again["prompt"])
        self.assertIn(f"forge-claim land acquire --repo owner/repo --branch dev --sha {B} --wait\n", again["prompt"])
        self.assertIn(f"{self.RELEASE}{B}\n", prompt(calls, "close-out-1"))
        self.assertEqual([line for line in out["logs"] if "waited" in line],
                         ["land-record-1-1: waited 60 min for the land lock of dev behind PR #7",
                          "land-relock-1-2: waited 15 min for the land lock of dev behind PR #7, #9"])
        # A lost claim ends the wait; a lost reply may hold the lock at the reviewed head, which the wrapper releases.
        out = self.land(**{"land-record-1-1": out_of_time, "land-relock-1-1": {"renew": {"verdict": "not_held", "by": "h2/b9"}, "lock": None}})
        self.assertEqual(row(out["result"], 1)["outcome"], "claim-lost")
        self.assertEqual(labels(out["calls"]).count("land-unlock-1"), 1)
        out = self.land(**{"land-record-1-1": out_of_time, "land-relock-1-1": None})
        self.assertEqual((row(out["result"], 1)["outcome"], row(out["result"], 1)["stage"]), ("stopped", "land-lock"))
        self.assertEqual(labels(out["calls"]).count("land-unlock-1"), 2)
        self.assertIn(f"{self.RELEASE}{B}\n", prompt(out["calls"], "land-unlock-1"))
        self.assertNotIn("land-merge-1", labels(out["calls"]))

    FAILED = {"verdict": "error", "detail": "boom"}

    def unlocks(self, out):
        return [c["prompt"] for c in out["calls"] if c["label"] == "land-unlock-1"]

    def test_a_release_that_failed_before_the_resolution_is_tried_again_at_the_stop(self):
        for name, first in {"an error": self.FAILED, "a lost reply": None, "a dead agent": "throw"}.items():
            with self.subTest(release=name):
                out = self.land(**{"land-unlock-1": [first, {"verdict": "released"}], "land-sync-review-1-1": None})
                dead = name == "a dead agent"  # the landing ends where the agent died; the resolution never starts
                self.assertEqual(row(out["result"], 1)["outcome"], "stopped" if dead else "sync-review")
                self.assertEqual("land-sync-resolve-1-1" in labels(out["calls"]), not dead)
                # Both releases name the sha the lock is held at: the head it was taken at.
                self.assertEqual([f"{self.RELEASE}{SHA}\n" in text for text in self.unlocks(out)], [True, True])
                self.assertNotIn("land-merge-1", labels(out["calls"]))

    def test_after_a_failed_release_a_lost_retake_releases_the_earlier_sha_then_the_reviewed_head(self):
        out = self.land(**{"land-unlock-1": [self.FAILED, {"verdict": "released"}], "land-record-1-1": None})
        self.assertEqual((row(out["result"], 1)["outcome"], row(out["result"], 1)["stage"]), ("stopped", "land-record"))
        first, last = self.unlocks(out)
        self.assertIn(f"{self.RELEASE}{SHA}\n", last)
        self.assertIn(f"When it prints not_held with lock_sha {B}, run alone and exactly: {self.RELEASE}{B}", last)
        self.assertNotIn("When it prints not_held", first)

    def test_after_a_failed_release_the_retake_outcomes_keep_the_right_sha(self):
        failed = {"land-unlock-1": [self.FAILED, {"verdict": "released"}]}
        # The retake moves the lock that was never released: the landing goes on and the close-out releases the reviewed head.
        out = self.land(**failed, **{"land-record-1-1": {"ok": True, "head": B, "lock": {"verdict": "moved", "lock_sha": B}}})
        self.assertEqual(row(out["result"], 1)["outcome"], "landed")
        self.assertEqual(len(self.unlocks(out)), 1)
        self.assertIn(f"{self.RELEASE}{B}\n", prompt(out["calls"], "close-out-1"))
        # The record step refused before any lock command: the earlier sha is still marked held and is released again.
        out = self.land(**failed, **{"land-record-1-1": {"ok": False, "head": C, "detail": "the head moved", "lock": None, "checks": None}})
        self.assertEqual((row(out["result"], 1)["outcome"], row(out["result"], 1)["stage"]), ("stopped", "land-record"))
        self.assertEqual([f"{self.RELEASE}{SHA}\n" in text for text in self.unlocks(out)], [True, True])
        # Another landing holds the lock: nothing of this landing's is left to release.
        out = self.land(**failed, **{"land-record-1-1": {"ok": True, "head": B, "lock": {"verdict": "held_by", "lock_sha": C}, "checks": None}})
        self.assertEqual(row(out["result"], 1)["outcome"], "land-contended")
        self.assertEqual(len(self.unlocks(out)), 1)


class LockWaitLogTest(unittest.TestCase):
    """#913: forge-claim's waited_on reaches the lock replies, and a long wait is logged with the pull requests it waited on."""

    @staticmethod
    def waits(out):
        return [line for line in out["logs"] if "waited" in line]

    def test_the_lock_replies_carry_the_wait(self):
        _, calls, _ = run()
        self.assertIn("lock_sha, by, detail, waited_s and waited_on from its output", prompt(calls, "land-pr-1"))
        lock = object_branch(schema_of(calls, "land-pr-1")["properties"]["lock"])["properties"]
        self.assertEqual((lock["waited_s"], lock["waited_on"]), ({"type": "integer"}, {"type": "array", "items": {"type": "integer"}}))

    def test_a_long_wait_is_logged_with_its_holders_and_a_short_one_is_not(self):
        def waited(**lock):
            return {"land-pr-1": {"lock": dict({"verdict": "acquired", "lock_sha": SHA}, **lock)}}
        self.assertEqual(self.waits(run_full(patch=waited(waited_s=1740, waited_on=[2218, 2230]))),
                         ["land-pr-1: waited 29 min for the land lock of dev behind PR #2218, #2230"])
        self.assertEqual(self.waits(run_full(patch=waited(waited_s=600))), ["land-pr-1: waited 10 min for the land lock of dev"])
        for lock in ({"waited_s": 240, "waited_on": [2218]}, {}):
            with self.subTest(lock=lock):
                self.assertEqual(self.waits(run_full(patch=waited(**lock))), [])

    def test_a_retried_wait_is_logged_under_its_own_step(self):
        out = run_full(replies={"land-pr-1": {"pr": 41, "head": SHA, "lock": {"verdict": "land-contended", "waited_s": 3600, "waited_on": [7]}},
                                "land-lock-1-1": {"lock": {"verdict": "acquired", "lock_sha": SHA, "waited_s": 480, "waited_on": [7, 9]}}})
        self.assertEqual(row(out["result"], 1)["outcome"], "landed")
        self.assertEqual(self.waits(out), ["land-pr-1: waited 60 min for the land lock of dev behind PR #7",
                                           "land-lock-1-1: waited 8 min for the land lock of dev behind PR #7, #9"])

    def test_both_programs_carry_the_same_lock_return_and_wait_log(self):
        def copies(path):
            text = path.read_text(encoding="utf-8")
            lines = {name: next(line for line in text.splitlines() if line.startswith(f"const {name} = "))
                     for name in ("LOCK_RETURN", "LOCK_WAIT_LOG_S")}
            start = text.index("const logWait = ")
            return dict(lines, logWait=text[start:text.index("\n}\n", start) + 3])
        batch = copies(PROGRAM)
        self.assertEqual(batch["logWait"].count("\n"), 5)
        self.assertIn("behind PR", batch["logWait"])
        self.assertEqual(batch, copies(PROGRAM.with_name("deliver-standard.js")))


class DependencyTest(unittest.TestCase):
    def test_a_blocker_chain_releases_each_dependent_only_on_closed(self):
        result, calls, _ = run(args=dict(ARGS, issues=[1, 2, 3]),
                               patch={"facts-2": blocked_by(1), "facts-3": blocked_by(2)})
        ls = labels(calls)
        self.assertLess(ls.index("close-out-1"), ls.index("acquire-2"))
        self.assertLess(ls.index("close-out-2"), ls.index("acquire-3"))
        self.assertEqual([row(result, n)["outcome"] for n in (1, 2, 3)], ["landed"] * 3)

    def test_a_blocker_only_the_tracker_names_makes_the_dependent_wait(self):
        """An edge added with forge-issue link is absent from the body's list (#944 ahead of #891)."""
        result, calls, _ = run(args=dict(ARGS, issues=[2, 1]),
                               patch={"facts-1": {"native": stated({"owner/repo#50": "closed", "Owner/REPO#2": "open"})}})
        ls = labels(calls)
        self.assertLess(ls.index("close-out-2"), ls.index("acquire-1"))
        self.assertEqual([row(result, n)["outcome"] for n in (1, 2)], ["landed"] * 2)

    def test_an_outside_native_blocker_the_reply_gives_no_state_blocks(self):
        result, calls, _ = run(patch={"facts-1": {"native": native(50)}})
        self.assertEqual((row(result, 1)["outcome"], row(result, 1)["blocker"]), ("blocked", 50))
        self.assertNotIn("acquire-1", labels(calls))

    def test_a_closed_native_blocker_of_either_repository_does_not_block(self):
        """The native states release with no clerk lookup, and another repository's #2 is never the batch's #2."""
        facts = {"native": stated({"Owner/Repo#50": "closed", "other/repo#2": "CLOSED"})}
        result, calls, _ = run(args=dict(ARGS, issues=[1, 2]), patch={"facts-1": facts})
        self.assertEqual(row(result, 1)["outcome"], "landed")
        ls = labels(calls)
        self.assertLess(ls.index("acquire-1"), ls.index("close-out-2"))

    def test_an_open_blocker_in_another_repository_blocks_and_is_named_whole(self):
        facts = {"native": stated({"other/repo#2": "open", "another/repo#7": "open", "owner/repo#50": "closed"})}
        result, calls, _ = run(args=dict(ARGS, issues=[1, 2]), patch={"facts-1": facts})
        self.assertEqual(row(result, 1), {"issue": 1, "outcome": "blocked", "blocker_ref": "another/repo#7",
                                          "blockers": ["another/repo#7", "other/repo#2"],
                                          "reason": "waits for another/repo#7, other/repo#2"})
        self.assertNotIn("acquire-1", labels(calls))
        self.assertEqual(row(result, 2)["outcome"], "landed")
        self.assertEqual(result["relaunch"]["issues"], [1])

    def test_an_open_blocker_of_the_repository_is_named_before_another_repository_s(self):
        facts = {"native": stated({"other/repo#2": "open", "owner/repo#50": "open"})}
        result, _, _ = run(patch={"facts-1": facts})
        self.assertEqual(row(result, 1), {"issue": 1, "outcome": "blocked", "blocker": 50, "blockers": ["#50", "other/repo#2"],
                                          "reason": "waits for #50, other/repo#2"})

    def test_a_blocked_row_names_every_open_outside_blocker(self):
        """An owner closes them all in one round (a row naming one of two cost a relaunch)."""
        body = [{"issue": 2213, "state": "OPEN"}, {"issue": 9, "state": "CLOSED"}, {"issue": 2, "state": "OPEN"}]
        for facts, named in (
                ({"native": stated({"owner/repo#2212": "open"})}, ["#2212"]),
                ({"native": stated({"owner/repo#2212": "open", "owner/repo#77": "closed"}), "blockers": body}, ["#2212", "#2213"]),
                ({"native": stated({"other/repo#5": "open", "owner/repo#2212": "open", "a/b#1": "open"}), "blockers": body},
                 ["#2212", "#2213", "a/b#1", "other/repo#5"])):
            with self.subTest(named=named):
                # Issue 2 is in the batch: an in-batch blocker is waited for, never named as an outside one.
                result, _, _ = run(args=dict(ARGS, issues=[1, 2]), patch={"facts-1": facts})
                self.assertEqual(row(result, 1), {"issue": 1, "outcome": "blocked", "blocker": 2212, "blockers": named,
                                                  "reason": f"waits for {', '.join(named)}"})

    def test_the_log_line_names_every_open_outside_blocker(self):
        out = run_full(patch={"facts-1": {"native": stated({"owner/repo#2212": "open", "other/repo#5": "open"})}})
        self.assertIn("#1: blocked (waits for #2212, other/repo#5)", out["logs"])

    def test_a_state_is_found_whatever_the_case_of_its_reference(self):
        for listed, key in (("Owner/Repo#50", "owner/repo#50"), ("owner/repo#50", "OWNER/REPO#50"), ("Other/Repo#2", "other/repo#2")):
            with self.subTest(listed=listed, key=key):
                facts = {"native": {"verdict": "read", "blocked_by": [listed], "blocked_by_states": {key: "closed"}}}
                result, _, _ = run(patch={"facts-1": facts})
                self.assertEqual(row(result, 1)["outcome"], "landed")

    def test_the_schema_takes_the_nulls_a_failed_read_prints(self):
        _, calls, _ = run()
        members = next(c for c in calls if c["label"] == "facts-1")["schema"]["properties"]["native"]["properties"]
        for name, kind in (("blocked_by", "array"), ("blocked_by_states", "object")):
            self.assertEqual(members[name]["type"], [kind, "null"])
        result, _, _ = run(patch={"facts-1": {"native": {"verdict": "error", "blocked_by": None, "blocked_by_states": None,
                                                         "error": "payload_invalid"}}})
        self.assertEqual(row(result, 1)["reason"], "facts-1 did not read the native blockers: payload_invalid")

    def test_a_native_entry_the_reply_gives_no_state_counts_as_open(self):
        for ref, named in (("other/repo#2", {"blocker_ref": "other/repo#2"}), ("owner/repo#50", {"blocker": 50})):
            for states in (None, {}, [], "closed", {ref: None}, {ref: "unknown"}, {ref + "0": "closed"}):
                with self.subTest(ref=ref, states=states):
                    answer = {"verdict": "read", "blocked_by": [ref]}
                    if states is not None:
                        answer["blocked_by_states"] = states
                    # A state the clerk looked up itself never closes a blocker the native read left open.
                    facts = {"native": answer, "blockers": [{"issue": 50, "state": "CLOSED"}, {"issue": 2, "state": "CLOSED"}]}
                    result, calls, _ = run(patch={"facts-1": facts})
                    self.assertEqual({k: v for k, v in row(result, 1).items() if k not in ("reason", "blockers")},
                                     dict({"issue": 1, "outcome": "blocked"}, **named))
                    self.assertNotIn("acquire-1", labels(calls))

    def test_the_facts_step_relays_the_states_and_looks_up_only_body_blockers_the_native_list_lacks(self):
        _, calls, _ = run()
        call = next(c for c in calls if c["label"] == "facts-1")
        self.assertIn("blocked_by_states", call["schema"]["properties"]["native"]["properties"])
        self.assertIn("return the verdict, blocked_by, blocked_by_states and error of the one JSON line it prints, unchanged. "
                      "blockers: one {issue, state} per issue #<n> of the body's \"Blocked by\" list whose owner/repo#<n> is not in "
                      "blocked_by, with the state from gh issue view, [] when none.", call["prompt"])

    def test_only_a_state_that_says_closed_releases_a_blocker(self):
        for state, outcome in (("unknown", "blocked"), ("", "blocked"), ("error", "blocked"), ("open", "blocked"),
                               ("closed", "landed"), ("CLOSED", "landed")):
            with self.subTest(state=state):
                result, _, _ = run(patch={"facts-1": {"blockers": [{"issue": 50, "state": state}]}})
                self.assertEqual(row(result, 1)["outcome"], outcome)

    def test_a_blocker_stated_open_once_stays_open(self):
        for states in (("OPEN", "CLOSED"), ("CLOSED", "OPEN")):
            for listed in ((), (50,)):
                with self.subTest(states=states, native=listed):
                    facts = {"native": native(*listed), "blockers": [{"issue": 50, "state": s} for s in states]}
                    result, _, _ = run(patch={"facts-1": facts})
                    self.assertEqual((row(result, 1)["outcome"], row(result, 1).get("blocker")), ("blocked", 50))

    def test_a_native_entry_that_is_no_qualified_reference_stops_the_issue(self):
        for bad in ("#50", "50", "owner/repo#0", 50):
            with self.subTest(entry=bad):
                result, calls, _ = run(patch={"facts-1": {"native": {"verdict": "read", "blocked_by": ["owner/repo#2", bad]}}})
                self.assertEqual(row(result, 1), {"issue": 1, "outcome": "stopped", "reason":
                                                  f"facts-1 returned a native blocker that is no <owner>/<name>#<n>: {json.dumps(bad)}"})
                self.assertNotIn("acquire-1", labels(calls))

    def test_a_failed_native_read_names_its_error(self):
        result, _, _ = run(patch={"facts-1": {"native": {"verdict": "error", "blocked_by": None, "error": "usage"}}})
        self.assertEqual(row(result, 1)["reason"], "facts-1 did not read the native blockers: usage")
        _, calls, _ = run()
        call = next(c for c in calls if c["label"] == "facts-1")
        self.assertIn("error", call["schema"]["properties"]["native"]["properties"])
        self.assertIn("blocked_by_states and error of the one JSON line", call["prompt"])

    def test_a_closed_issue_whose_native_read_failed_is_closed_and_released(self):
        result, calls, _ = run(patch={"facts-1": {"state": "CLOSED", "native": {"verdict": "error"}}})
        self.assertEqual(row(result, 1), {"issue": 1, "outcome": "closed", "released": True})
        self.assertEqual(labels(calls), ["setup", "facts-1", "release-1"])

    def test_a_reply_without_the_native_read_stops_the_issue_unclaimed(self):
        for bad in (None, {"verdict": "error"}, {"verdict": "read"}, {"verdict": "linked", "blocked_by": []}):
            with self.subTest(native=bad):
                facts = dict(FACTS_NO_LANE, lane="standard", native=bad, blockers=[{"issue": 50, "state": "CLOSED"}])
                if bad is None:
                    del facts["native"]
                result, calls, _ = run(replies={"facts-1": facts})
                self.assertEqual(row(result, 1),
                                 {"issue": 1, "outcome": "stopped", "reason": "facts-1 did not read the native blockers"})
                self.assertNotIn("acquire-1", labels(calls))

    def test_the_facts_step_names_the_native_read_and_requires_its_answer(self):
        _, calls, _ = run()
        call = next(c for c in calls if c["label"] == "facts-1")
        self.assertIn("run alone and exactly forge-issue read --repo owner/repo --issue 1 and return", call["prompt"])
        self.assertLessEqual({"native", "blockers"}, set(call["schema"]["required"]))

    def test_a_merged_but_open_blocker_does_not_release(self):
        acceptance = [{"id": "AC1", "text": "works", "kind": "code"}, {"id": "AC2", "text": "live", "kind": "evidence"}]
        result, calls, _ = run(args=dict(ARGS, issues=[1, 2]), patch={"facts-2": blocked_by(1)},
                               children={"1": ready(1, acceptance)},
                               replies={"close-out-1": {"issue_state": "OPEN", "released": True, "decision_ended": True, "notes": "held"}})
        self.assertEqual(row(result, 1)["outcome"], "landed-held")
        self.assertEqual((row(result, 2)["outcome"], row(result, 2)["blocker"]), ("waits-verification", 1))
        self.assertNotIn("acquire-2", labels(calls))

    def test_a_blocker_held_for_verification_reports_waits_verification(self):
        result, calls, _ = run(args=dict(ARGS, issues=[1, 2]),
                               patch={"facts-1": {"labels": ["needs-verification"]}, "facts-2": blocked_by(1)})
        self.assertEqual((row(result, 2)["outcome"], row(result, 2)["blocker"]), ("waits-verification", 1))
        self.assertNotIn("acquire-2", labels(calls))
        self.assertNotIn("child-2", labels(calls))

    def test_a_failed_blocker_blocks_its_dependent(self):
        result, calls, _ = run(args=dict(ARGS, issues=[1, 2]), patch={"facts-2": blocked_by(1)},
                               replies=dict(contended(), **{
                                   "land-pr-1": {"pr": 41, "head": SHA, "lock": {"verdict": "land-contended"}}}))
        self.assertEqual((row(result, 2)["outcome"], row(result, 2)["blocker"]), ("blocked", 1))
        self.assertNotIn("acquire-2", labels(calls))
        self.assertEqual(result["relaunch"]["issues"], [1, 2])

    def test_an_already_closed_in_batch_blocker_releases_at_once(self):
        result, calls, _ = run(args=dict(ARGS, issues=[1, 2]),
                               patch={"facts-1": {"state": "CLOSED"}, "facts-2": blocked_by(1)})
        self.assertEqual(row(result, 2)["outcome"], "landed")

    def test_a_cycle_blocks_every_issue_on_it(self):
        result, calls, _ = run(args=dict(ARGS, issues=[1, 2, 3]),
                               patch={"facts-1": blocked_by(2), "facts-2": blocked_by(1)})
        for n in (1, 2):
            self.assertEqual((row(result, n)["outcome"], row(result, n)["reason"]), ("blocked", "cycle"))
        self.assertEqual(row(result, 3)["outcome"], "landed")

    def test_a_cycle_is_an_owner_action_and_never_a_relaunch(self):
        # A cycle only the owner can break: relaunching it returns the same blocked rows forever.
        result, _, _ = run(args=dict(ARGS, issues=[1, 2, 3]),
                           patch={"facts-1": blocked_by(2), "facts-2": blocked_by(1)})
        self.assertIsNone(result["relaunch"])
        self.assertEqual([(a["issue"], a["reason"]) for a in result["owner_actions"]], [(1, "cycle"), (2, "cycle")])

    def test_a_cycle_leaves_the_other_open_issues_in_the_relaunch(self):
        result, _, _ = run(args=dict(ARGS, issues=[1, 2, 3]),
                           patch={"facts-1": blocked_by(2), "facts-2": blocked_by(1)},
                           replies=dict(contended(3), **{
                               "land-pr-3": {"pr": 43, "head": SHA, "lock": {"verdict": "land-contended"}}}))
        self.assertEqual(result["relaunch"]["issues"], [3])

    def test_a_waiting_dependent_holds_no_slot(self):
        result, _, active = run(args=dict(ARGS, issues=[1, 2, 3]), patch={"setup": {"max_parallel": 1},
                                                                       "facts-1": blocked_by(3)})
        self.assertEqual([row(result, n)["outcome"] for n in (1, 2, 3)], ["landed"] * 3)
        self.assertEqual(active, 1)


OPEN_PR = {"number": 41, "head_branch": "issue-1-x"}


class ReadoptTest(unittest.TestCase):
    def test_the_readopt_schema_accepts_a_note_row(self):
        """#736: a PR body Acceptance row of kind note readopts."""
        _, calls, _ = run(patch={"facts-1": {"open_pr": OPEN_PR}})
        kinds = schema_of(calls, "readopt-1")["properties"]["acceptance"]["items"]["properties"]["kind"]["enum"]
        self.assertEqual(kinds, ["code", "evidence", "human", "note"])

    def test_a_readopted_note_reaches_the_close_out_and_the_issue_closes(self):
        """#736: the clerk is told it may return a note, and a readopted note is listed, never held."""
        note = {"id": "AC2", "text": "the next session's first-turn prompt reads under 30k tokens", "kind": "note"}
        acceptance = [{"id": "AC1", "text": "works", "kind": "code"}, note]
        result, calls, _ = run(patch={"facts-1": {"open_pr": OPEN_PR}, "readopt-1": {"acceptance": acceptance}},
                               replies={"close-out-1": {"issue_state": "CLOSED", "released": True, "decision_ended": True,
                                                        "notes_posted": True, "notes": "ok"}})
        kinds = schema_of(calls, "readopt-1")["properties"]["acceptance"]["items"]["properties"]["kind"]["enum"]
        text = prompt(calls, "readopt-1")
        clause = text[text.index("kind ("):]
        clause = clause[:clause.index(")")]
        for kind in kinds:
            self.assertIn(kind, clause)
        self.assertEqual(row(result, 1)["outcome"], "landed")
        close = prompt(calls, "close-out-1")
        self.assertIn(note["text"], close)
        self.assertIn("gh issue close 1 --repo owner/repo", close)
        self.assertNotIn("needs-verification", close)

    def test_an_open_pr_of_the_branch_lands_without_lane_or_child(self):
        result, calls, _ = run(patch={"facts-1": {"open_pr": OPEN_PR, "claim": {"verdict": "held_by", "by": HOLDER}}})
        self.assertEqual(row(result, 1)["outcome"], "landed")
        self.assertEqual(of(calls, 1)[:4], ["facts-1", "acquire-1", "readopt-1", "land-pr-1"])
        self.assertNotIn("child-1", labels(calls))
        text = prompt(calls, "readopt-1")
        for needle in ("41", "issue-1-x", "worktree list --porcelain", "headRefOid", "Acceptance"):
            self.assertIn(needle, text)

    def test_an_open_pr_of_another_branch_goes_to_the_child(self):
        _, calls, _ = run(patch={"facts-1": {"open_pr": {"number": 41, "head_branch": "someone-else"}}})
        self.assertIn("child-1", labels(calls))
        self.assertNotIn("readopt-1", labels(calls))

    def test_a_failed_readopt_keeps_the_claim(self):
        result, calls, _ = run(patch={"facts-1": {"open_pr": OPEN_PR}},
                               replies={"readopt-1": {"ok": False, "reason": "dirty", "detail": "M a.py"}})
        self.assertEqual((row(result, 1)["outcome"], row(result, 1)["stage"]), ("stopped", "readopt"))
        self.assertNotIn("child-1", labels(calls))
        self.assertNotIn("release-1", labels(calls))
        self.assertNotIn("land-pr-1", labels(calls))
        self.assertEqual(result["relaunch"]["issues"], [1])

    def test_readopt_claims_before_it_reads(self):
        _, calls, _ = run(patch={"facts-1": {"open_pr": OPEN_PR}})
        ls = labels(calls)
        self.assertLess(ls.index("acquire-1"), ls.index("readopt-1"))

    def test_the_readopted_acceptance_reaches_the_close_out(self):
        acceptance = [{"id": "AC1", "text": "works", "kind": "code"}, {"id": "AC2", "text": "live", "kind": "evidence"}]
        result, calls, _ = run(patch={"facts-1": {"open_pr": OPEN_PR}, "readopt-1": {"acceptance": acceptance}},
                               replies={"close-out-1": {"issue_state": "OPEN", "released": True, "decision_ended": True, "notes": "held"}})
        self.assertEqual(row(result, 1)["outcome"], "landed-held")
        self.assertNotIn("gh issue close", prompt(calls, "close-out-1"))

    def test_readopt_reads_the_accepted_head(self):
        _, calls, _ = run(patch={"facts-1": {"open_pr": OPEN_PR}})
        self.assertIn("Accepted head:", prompt(calls, "readopt-1"))

    def test_a_relaunch_after_a_rejected_fix_review_reruns_the_gates_before_landing(self):
        # Run 1: CI fails, the fix is pushed, its review rejects it: ci-failed, PR head = the fix.
        first, _, _ = run(patch=folded(CI_RED), replies={
            "land-fix-review-1": {"verdict": "findings", "findings": [{"severity": "important", "summary": "weakened a test"}]}})
        self.assertEqual(row(first, 1)["outcome"], "ci-failed")
        # Run 2: the PR is open at the unaccepted fix head; readopt refuses to land it as it stands.
        result, calls, _ = run(args=first["relaunch"],
                               patch={"facts-1": {"open_pr": OPEN_PR, "claim": {"verdict": "held_by", "by": HOLDER},
                                                  "lane": None}},
                               replies={"readopt-1": {"ok": False, "reason": "unaccepted", "detail": "head c0ffee"}})
        ls = labels(calls)
        self.assertLess(ls.index("readopt-1"), ls.index("child-1"))
        self.assertEqual(child(calls, 1)["args"]["cont"], first["relaunch"]["conts"]["1"])
        self.assertLess(ls.index("child-1"), ls.index("land-merge-1"))
        self.assertEqual(row(result, 1)["outcome"], "landed")

    def test_an_unaccepted_pr_without_a_cont_gets_a_lane_and_a_fresh_child(self):
        _, calls, _ = run(patch={"facts-1": {"open_pr": OPEN_PR}},
                          replies={"readopt-1": {"ok": False, "reason": "unaccepted"}})
        ls = labels(calls)
        self.assertLess(ls.index("acquire-1"), ls.index("readopt-1"))
        self.assertLess(ls.index("readopt-1"), ls.index("child-1"))
        self.assertEqual(child(calls, 1)["args"]["lane"], "standard")
        self.assertNotIn("cont", child(calls, 1)["args"])
        result, calls, _ = run(patch={"facts-1": {"open_pr": OPEN_PR, "lane": "needs-design"}},
                               replies={"readopt-1": {"ok": False, "reason": "unaccepted"}})
        self.assertEqual(row(result, 1)["outcome"], "needs-design")
        self.assertIn("release-1", labels(calls))
        self.assertNotIn("child-1", labels(calls))

    def test_a_relaunch_after_needs_label_lands_and_ends_the_marker(self):
        first, _, _ = run(patch=folded({"state": "needs_label", "head": SHA, "label": "raise-me", "failing": ["gate"]}))
        self.assertEqual(row(first, 1)["outcome"], "needs-label")
        result, calls, _ = run(args=first["relaunch"],
                               patch={"facts-1": {"open_pr": OPEN_PR, "claim": {"verdict": "held_by", "by": HOLDER}}})
        self.assertEqual(row(result, 1)["outcome"], "landed")
        self.assertIn("forge-claim owner-action end --repo owner/repo --issue 1 --reason needs-label",
                      prompt(calls, "close-out-1"))
        self.assertNotIn("land-ask-1", labels(calls))


class IssueBranchFactsTest(unittest.TestCase):
    """#748: the facts step takes the branch from issue-branch, the command deliver-standard runs."""

    def test_the_facts_step_runs_issue_branch_for_its_issue(self):
        _, calls, _ = run()
        self.assertEqual(ISSUE_BRANCH_ARGV.findall(prompt(calls, "facts-1")), [("/r", "1")])

    def test_a_failed_derivation_never_claims_and_keeps_the_failure_detail(self):
        reply = {"branch": None, "branch_error": "issue-branch exited 1: forge_failed"}
        result, calls, _ = run(patch={"facts-1": reply})
        self.assertEqual(row(result, 1), {"issue": 1, "outcome": "stopped", "stage": "branch",
                                          "reason": "branch: issue-branch exited 1: forge_failed"})
        self.assertEqual(result["relaunch"]["issues"], [1])
        self.assertNotIn("acquire-1", labels(calls))
        self.assertNotIn("child-1", labels(calls))
        self.assertFalse([c for c in calls if "undefined" in c["prompt"]])

    def test_a_failed_derivation_without_a_detail_still_stops_before_the_claim(self):
        result, calls, _ = run(patch={"facts-1": {"branch": None}})
        self.assertEqual((row(result, 1)["outcome"], row(result, 1)["stage"]), ("stopped", "branch"))
        self.assertNotIn("acquire-1", labels(calls))


class DemoTest(unittest.TestCase):
    def test_three_issue_batch_with_a_dependency_and_a_questioned_issue_returns_one_table(self):
        result, calls, _ = run(args=dict(ARGS, issues=[1, 2, 3]),
                               patch={"facts-3": {"blockers": [{"issue": 1, "state": "OPEN"}]}},
                               children={"2": {"stage": "plan", "needs_user": QS, "cont": {"setup": {}}}})
        self.assertEqual(result["stage"], "done")
        self.assertEqual([(r["issue"], r["outcome"]) for r in result["table"]],
                         [(1, "landed"), (2, "questions"), (3, "landed")])
        self.assertEqual(result["questions"], [{"issue": 2, "questions": QS, "marker": None}])
        self.assertEqual(result["relaunch"], dict(ARGS, issues=[2], conts={"2": {"setup": {}}}))
        ls = labels(calls)
        self.assertLess(ls.index("close-out-1"), ls.index("acquire-3"))


def planned(n):
    """A plan child's planned stop for issue n, with a cont that names its plan."""
    cont = {"setup": {"holder": HOLDER, "branch": f"issue-{n}-x", "worktree": f"/r/.wt/w-issue-{n}-x"},
            "lane": "standard", "plan_reviewed": True, "plan": {"id": f"plan-{n}"}}
    return {"stage": "planned", "plan": {"id": f"plan-{n}"}, "cont": cont}


DIRECT = {"lane": "direct", "why": "small"}
# A resume whose worktree or plan dir is gone: deliver-standard's setup refuses with no cont.
NOT_RESUMABLE = {"stage": "setup", "result": {"ok": False, "reason": "not-resumable", "details": "the worktree is gone"}}
CLAIMED = {"stage": "claimed", "verdict": "held_by", "by": "h2/b9"}


def direct_lane(*issues):
    """Scenario keys that make each issue direct-lane, whether the program reads its lane from lane-<n> or from facts-<n>."""
    return {"replies": {f"lane-{n}": DIRECT for n in issues}, "patch": {f"facts-{n}": DIRECT for n in issues}}


def children_of(calls, n, mode):
    return [c for c in calls if c["kind"] == "workflow" and c["args"]["issue"] == n and c["args"]["mode"] == mode]


def event_index(events, event, issue, mode):
    wanted = {"event": event, "issue": issue, "mode": mode}
    for i, e in enumerate(events):
        if e == wanted:
            return i
    raise AssertionError(f"no child event {wanted}: {events}")


class PlanAheadTest(unittest.TestCase):
    """#744: a standard-lane issue plans under a second semaphore ahead of a free delivery slot."""

    ONE_SLOT = {"args": dict(ARGS, issues=[1, 2, 3]), "patch": {"setup": {"max_parallel": 1}}}

    def test_with_one_slot_the_next_plan_starts_before_the_first_ready_child_returns(self):
        out = run_full(**self.ONE_SLOT)
        events = out["child_events"]
        self.assertLess(event_index(events, "start", 2, "plan"), event_index(events, "return", 1, "ready"))
        self.assertLess(event_index(events, "start", 3, "plan"), event_index(events, "return", 2, "ready"))
        self.assertEqual([row(out["result"], n)["outcome"] for n in (1, 2, 3)], ["landed"] * 3)
        self.assertEqual((out["max_active"], out["max_planning"]), (1, 1))

    def test_a_finished_plan_keeps_its_plan_slot_until_it_holds_a_delivery_slot(self):
        # D4: issue 1's ready child is held for 200 turns. Issue 2 finishes planning long before that and waits for
        # the one delivery slot with its plan slot kept, so issue 3 is neither claimed nor planned until issue 2 holds it.
        # A program that gives the plan slot back before it waits for the delivery slot starts issue 3's plan at once.
        out = run_full(turns={"1:ready": 200}, **self.ONE_SLOT)
        events, ls = out["child_events"], labels(out["calls"])
        ready1_done = event_index(events, "return", 1, "ready")
        self.assertLess(event_index(events, "return", 2, "plan"), ready1_done,
                        "premise: issue 2 finished planning while issue 1 delivered")
        plan3 = event_index(events, "start", 3, "plan")
        self.assertLess(ready1_done, plan3)
        self.assertLess(event_index(events, "start", 2, "ready"), plan3)
        child2 = [i for i, label in enumerate(ls) if label == "child-2"]
        self.assertEqual(len(child2), 2)
        self.assertLess(child2[1], ls.index("acquire-3"))
        self.assertEqual([row(out["result"], n)["outcome"] for n in (1, 2, 3)], ["landed"] * 3)

    def test_every_ready_child_of_a_planned_issue_receives_that_plans_cont(self):
        kids = {str(n): [planned(n), ready(n)] for n in (1, 2, 3)}
        result, calls, _ = run(children=kids, **self.ONE_SLOT)
        for n in (1, 2, 3):
            with self.subTest(issue=n):
                self.assertEqual([c["args"] for c in children_of(calls, n, "plan")],
                                 [{"repo_root": "/r", "issue": n, "batch_id": "b1", "mode": "plan", "lane": "standard"}])
                self.assertEqual([c["args"] for c in children_of(calls, n, "ready")],
                                 [{"repo_root": "/r", "issue": n, "batch_id": "b1", "mode": "ready", "cont": planned(n)["cont"]}])
                self.assertEqual(row(result, n)["outcome"], "landed")

    def test_a_direct_issue_never_runs_a_plan_child(self):
        ineligible = {"stage": "ineligible", "cont": {"setup": {}, "lane": "direct"}}
        lane = direct_lane(2)
        for kids in ({}, {"2": [ineligible, ready(2)]}):
            with self.subTest(children=kids):
                result, calls, _ = run(args=self.ONE_SLOT["args"], replies=lane["replies"],
                                       patch={**self.ONE_SLOT["patch"], **lane["patch"]}, children=kids)
                self.assertEqual(children_of(calls, 2, "plan"), [])
                self.assertTrue(children_of(calls, 2, "ready"))
                self.assertEqual(len(children_of(calls, 1, "plan")), 1)
                self.assertEqual(row(result, 2)["outcome"], "landed")

    def test_a_finished_plan_takes_the_next_delivery_slot_before_queued_direct_issues(self):
        # With one slot, direct issue 1 running and direct issues 2 and 3 queued, the plan of
        # standard issue 4 must not wait behind both of them (D4).
        lane = direct_lane(1, 2, 3)
        out = run_full(args=dict(ARGS, issues=[1, 2, 3, 4]), replies=lane["replies"],
                       patch={"setup": {"max_parallel": 1}, **lane["patch"]})
        events = out["child_events"]
        after_plan = [e["issue"] for e in events[event_index(events, "return", 4, "plan"):]
                      if e["event"] == "start" and e["mode"] == "ready"]
        self.assertEqual(after_plan[0], 4, events)
        self.assertIn(3, after_plan[1:], "premise: a direct issue was still queued when the plan finished")
        self.assertEqual([e["issue"] for e in events if e["mode"] == "plan" and e["event"] == "start"], [4])
        self.assertEqual([row(out["result"], n)["outcome"] for n in (1, 2, 3, 4)], ["landed"] * 4)
        self.assertEqual((out["max_active"], out["max_planning"]), (1, 1))

    def test_only_one_child_at_a_time_touches_an_issue(self):
        out = run_full(args=dict(ARGS, issues=[1, 2, 3]))
        for n in (1, 2, 3):
            with self.subTest(issue=n):
                self.assertEqual([(e["event"], e["mode"]) for e in out["child_events"] if e["issue"] == n],
                                 [("start", "plan"), ("return", "plan"), ("start", "ready"), ("return", "ready")])

    def test_a_plan_ahead_issue_is_claimed_once_before_its_plan_child(self):
        out = run_full()
        calls = out["calls"]
        ls = labels(calls)
        self.assertEqual(ls.count("acquire-1"), 1)
        first_child = next(i for i, c in enumerate(calls) if c["kind"] == "workflow")
        self.assertLess(ls.index("acquire-1"), first_child)
        self.assertEqual(calls[first_child]["args"]["mode"], "plan")
        self.assertNotIn("release-1", ls)
        self.assertEqual(row(out["result"], 1)["outcome"], "landed")

    def test_plan_ahead_adds_a_workflow_child_but_no_agent_call_to_the_landing_budget(self):
        # The landing test bounds one issue's calls at 10 before #744; the plan child is the one added call, a
        # workflow() child, so the agent calls stay within that original bound.
        _, calls, _ = run()
        mine = [c for c in calls if c["label"] in set(of(calls, 1))]
        self.assertEqual(len([c for c in mine if c["kind"] == "workflow"]), 2)
        self.assertLessEqual(len([c for c in mine if c["kind"] == "agent"]), 10)
        self.assertEqual(len(mine), len(HAPPY))

    def test_a_plan_child_that_stops_takes_no_delivery_slot(self):
        no_cont = {"stage": "setup", "result": {"ok": False, "reason": "no-longer-applies"}}
        for stop, outcome in ((QUESTION, "questions"), (no_cont, "stopped")):
            with self.subTest(stop=stop):
                out = run_full(children={"1": [stop, ready(1)]})
                self.assertEqual(row(out["result"], 1)["outcome"], outcome)
                self.assertEqual([c["args"]["mode"] for c in out["calls"] if c["kind"] == "workflow"], ["plan"])
                self.assertEqual(out["max_active"], 0)
        _, calls, _ = run(children={"1": [no_cont, ready(1)]})
        self.assertIn("release-1", labels(calls))

    def test_a_forwarded_cont_without_a_reviewed_plan_plans_ahead_with_it(self):
        result, calls, _ = run(args=dict(ARGS, conts={"1": QUESTION["cont"]}, decisions={"1": "Use the flag."}),
                               patch={"facts-1": dict(HELD, decision=OPEN)},
                               children={"1": [planned(1), ready(1)]})
        self.assertEqual([c["args"] for c in calls if c["kind"] == "workflow"], [
            {"repo_root": "/r", "issue": 1, "batch_id": "b1", "mode": "plan", "cont": QUESTION["cont"],
             "decisions": "Use the flag."},
            {"repo_root": "/r", "issue": 1, "batch_id": "b1", "mode": "ready", "cont": planned(1)["cont"],
             "decisions": "Use the flag."}])
        self.assertEqual(row(result, 1)["outcome"], "landed")

    def test_a_plan_child_that_cannot_resume_a_forwarded_cont_drops_it(self):
        # D9: the forwarded cont names a worktree that is gone; the claim is released and the relaunch starts afresh.
        result, calls, _ = run(args=dict(ARGS, conts={"1": QUESTION["cont"]}), patch={"facts-1": HELD},
                               children={"1": NOT_RESUMABLE})
        self.assertEqual([c["args"]["mode"] for c in calls if c["kind"] == "workflow"], ["plan"])
        self.assertIn("release-1", labels(calls))
        self.assertEqual(without(result["relaunch"], "reasons"), ARGS)

    def test_a_reviewed_plan_or_a_merged_pr_goes_straight_to_a_delivery_slot(self):
        # Regression guard for D3: it passes before and after the change.
        cont = planned(1)["cont"]
        _, calls, _ = run(args=dict(ARGS, conts={"1": cont}), patch={"facts-1": HELD})
        self.assertEqual([c["args"] for c in calls if c["kind"] == "workflow"],
                         [{"repo_root": "/r", "issue": 1, "batch_id": "b1", "mode": "ready", "cont": cont}])
        merged = {**landing(41), "state": "CLOSED", "claim": {"verdict": "held_by", "by": HOLDER}}
        _, calls, _ = run(args=dict(ARGS, conts={"1": {"setup": {}, "pr": 41}}), patch={"facts-1": merged},
                          children={"1": {"stage": "close-out", "pr": 41, "cont": {"setup": {}}}})
        self.assertEqual([c["args"]["mode"] for c in calls if c["kind"] == "workflow"], ["ready"])
        # A forwarded cont whose own landing merged (a done commit, no pr) is closed out, never planned.
        own = {"setup": {"holder": HOLDER, "branch": "issue-1-x", "worktree": "/r/.wt/w-issue-1-x"},
               "done": [{"n": 1, "commit": "d" * 40}]}
        landed_own = dict(HELD, labels=["needs-verification"], merged_refs=[{"number": 41, "closes": False}],
                          landed=[{"number": 41, "commits": ["d" * 40]}])
        result, calls, _ = run(args=dict(ARGS, conts={"1": own}), patch={"facts-1": landed_own},
                               children={"1": {"stage": "done", "pr": 41, "merged": True, "acceptance": [],
                                               "close_out": {"issue_state": "CLOSED", "released": True}}})
        self.assertEqual([c["args"]["mode"] for c in calls if c["kind"] == "workflow"], ["ready"])
        self.assertEqual(row(result, 1)["outcome"], "landed")

    def test_a_cont_with_a_pr_or_a_readoptable_open_pr_never_runs_a_plan_child(self):
        # D3: an integer pr in the cont, or an open PR on the derived branch, sends the issue straight to a delivery slot.
        _, calls, _ = run(args=dict(ARGS, conts={"1": {"setup": {}, "lane": "standard", "pr": 41}}),
                          patch={"facts-1": HELD})
        self.assertEqual([c["args"]["mode"] for c in calls if c["kind"] == "workflow"], ["ready"])
        _, calls, _ = run(args=dict(ARGS, conts={"1": QUESTION["cont"]}),
                          patch={"facts-1": {"open_pr": OPEN_PR, "claim": {"verdict": "held_by", "by": HOLDER}},
                                 "readopt-1": {"ok": False, "reason": "unaccepted"}})
        self.assertEqual(children_of(calls, 1, "plan"), [])
        self.assertTrue(children_of(calls, 1, "ready"))


class ReadyPathTest(unittest.TestCase):
    """#744 D7, D9: each failure family the existing tests pin on the first child, on the ready child of a planned issue."""

    def ready_args(self, calls, n):
        return [c["args"] for c in children_of(calls, n, "ready")]

    def test_a_ready_child_that_cannot_resume_releases_the_claim_and_the_relaunch_plans_afresh(self):
        first, calls, _ = run(children={"1": [planned(1), NOT_RESUMABLE]})
        self.assertEqual(self.ready_args(calls, 1)[0]["cont"], planned(1)["cont"])
        self.assertEqual((row(first, 1)["outcome"], row(first, 1)["stage"]), ("stopped", "setup"))
        self.assertIn(f"forge-claim release --repo owner/repo --issue 1 --holder {HOLDER} --reason skipped",
                      prompt(calls, "release-1"))
        self.assertEqual(without(first["relaunch"], "reasons"), ARGS)  # D9: the obsolete plan cont is not forwarded
        _, calls, _ = run(args=first["relaunch"])
        self.assertEqual([c["args"] for c in calls if c["kind"] == "workflow"][0],
                         {"repo_root": "/r", "issue": 1, "batch_id": "b1", "mode": "plan", "lane": "standard"})

    def test_a_ready_child_stop_with_cont_keeps_the_claim_and_forwards_its_own_cont(self):
        result, calls, _ = run(children={"1": [planned(1), TASK_STOP]})
        self.assertEqual(self.ready_args(calls, 1)[0]["cont"], planned(1)["cont"])
        self.assertEqual((row(result, 1)["outcome"], row(result, 1)["stage"]), ("stopped", "task"))
        self.assertNotIn("release-1", labels(calls))
        self.assertEqual(result["relaunch"]["issues"], [1])
        self.assertEqual(result["relaunch"]["conts"], {"1": TASK_STOP["cont"]})

    def test_a_ready_child_that_lost_its_claim_is_claim_lost_without_a_cont(self):
        result, calls, _ = run(children={"1": [planned(1), CLAIMED]})
        self.assertEqual((row(result, 1)["outcome"], row(result, 1)["by"]), ("claim-lost", "h2/b9"))
        self.assertEqual(len(self.ready_args(calls, 1)), 1)
        self.assertEqual(result["relaunch"], dict(ARGS, reasons={"1": "claimed by h2/b9"}))

    def test_a_ready_child_stop_on_a_closed_issue_settles(self):
        for release in ("released", "not_held"):
            with self.subTest(release=release):
                result, calls, _ = run(children={"1": [planned(1), TASK_STOP]},
                                       replies={"settle-1": {"state": "CLOSED", "release": release}})
                self.assertEqual(row(result, 1), {"issue": 1, "outcome": "closed", "stage": "task",
                                                  "released": release == "released"})
                self.assertEqual(of(calls, 1)[-2:], ["child-1", "settle-1"])
                self.assertIn(CLOSED_RELEASE, prompt(calls, "settle-1"))
                self.assertIsNone(result["relaunch"])
        result, _, _ = run(children={"1": [planned(1), TASK_STOP]},
                           replies={"settle-1": {"state": "CLOSED", "release": "error"}})
        self.assertEqual((row(result, 1)["outcome"], row(result, 1)["stage"]), ("stopped", "task"))
        self.assertEqual(result["relaunch"]["conts"], {"1": TASK_STOP["cont"]})

    def test_every_dead_ready_child_shape_trips_the_breaker_and_a_planned_neighbour_keeps_its_cont(self):
        # Issue 1's ready child is held for 50 turns, so issue 2 is planned and waiting for the one delivery slot
        # when the breaker trips: it is refused that slot, keeps its claim and forwards its plan cont (D5).
        cont = {"setup": {}, "lane": "standard", "partial": 1}
        shapes = [
            ("throw", planned(1)["cont"]),
            ({"stage": "task-review", "task": {"n": 1}, "review": None, "dead_agents": ["review-1"], "cont": cont}, cont),
            ({"stage": "final-review", "details": "a final reviewer returned nothing",
              "finals": [None, {"verdict": "pass", "findings": []}], "dead_agents": ["final-1"], "cont": {"setup": {}}},
             {"setup": {}}),
            ({"stage": "setup", "result": None, "dead_agents": ["setup"]}, planned(1)["cont"]),
        ]
        for dead, kept in shapes:
            with self.subTest(child=dead):
                result, calls, _ = run(args=dict(ARGS, issues=[1, 2]), patch={"setup": {"max_parallel": 1}},
                                       children={"1": [planned(1), dead], "2": [planned(2), ready(2)]},
                                       turns={"1:ready": 50})
                self.assertEqual(result["stage"], "breaker")
                self.assertEqual(len(self.ready_args(calls, 1)), 1)
                self.assertEqual(self.ready_args(calls, 2), [])
                self.assertEqual(row(result, 2), {"issue": 2, "outcome": "not-admitted", "stage": "planned"})
                self.assertNotIn("release-1", labels(calls))
                self.assertNotIn("release-2", labels(calls))
                self.assertEqual(result["relaunch"]["issues"], [1, 2])
                self.assertEqual(result["relaunch"]["conts"], {"1": kept, "2": planned(2)["cont"]})


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

    def test_meta_names_the_args(self):
        text = PROGRAM.read_text(encoding="utf-8")
        meta = text[:text.index("\n}\n")]
        for arg in ("repo_root", "batch_id", "child_script", "issues", "label", "decisions", "review_sizing",
                    "clerk_model", "amend"):
            self.assertIn(arg, meta)

    def test_deliver_batch_skill_is_small_and_names_the_program_and_its_args(self):
        # #637 AC1: the skill that replaces orchestrate-issues stays at most 1.5 KB.
        path = PROGRAM.parent.parent / "deliver-batch" / "SKILL.md"
        raw = path.read_bytes()
        self.assertLessEqual(len(raw), 1536)
        text = raw.decode("utf-8")
        self.assertTrue(text.startswith("---\nname: deliver-batch\ndescription: "))
        description = text.split("\n", 3)[2].removeprefix("description: ")
        self.assertLessEqual(len(description.encode("utf-8")), 147)
        self.assertIn("Use for", description)
        self.assertIn("deliver issues", description)
        self.assertNotIn("resolve-project resolve", text)
        for key in ("`deliver-batch.js`", "`deliver-standard.js`", "scriptPath", "repo_root", "issues",
                    "label", "batch_id", "<host>-<yyyymmdd-hhmm>", "child_script", "decisions",
                    "table", "questions", "owner_actions", "relaunch", "resumeFromRunId",
                    "`error`", "`result`", "`missing`", "`invalid`", "`holder`", "`breaker`"):
            with self.subTest(key=key):
                self.assertIn(key, text)

    def test_deliver_standard_skill_hands_batches_to_deliver_batch(self):
        text = PROGRAM.with_name("SKILL.md").read_text(encoding="utf-8")
        self.assertLessEqual(len(text.encode("utf-8")), 1056)
        self.assertIn("`deliver-batch`", text)
        self.assertNotIn("deliver-batch.js", text)


CLERK, IMPL, REV = "clerk", "implementer", "reviewer"
EXPECTED = {stem: frozenset({kind}) for kind, stems in (
    (CLERK, ("setup", "facts-", "release-", "acquire-", "readopt-", "recover-end-", "ask-", "settle-",
             "land-unlock-", "land-ask-", "land-lock-", "land-relock-", "land-record-", "land-status-", "land-pr-", "land-checks-", "land-merge-", "close-out-",
             "train-sweep-", "train-pr-", "train-checks-", "train-ready-", "train-merge-", "train-flip-")),
    (IMPL, ("land-sync-", "land-sync-resolve-", "land-sync-fix-", "land-fix-", "train-build-")),
    (REV, ("land-sync-review-", "land-sync-rereview-", "land-fix-review-")),
) for stem in stems}
STEM_PATTERNS = (
    r"\b(?:label|reviewLabel): (['`])([a-z][a-z0-9-]*)",
    r"\b\w*[lL]abel = (['`])([a-z][a-z0-9-]*)",
    r"`, (`)([a-z][a-z0-9-]*)(?=\$\{|`)",
)
CI_RED = {"state": "failed", "head": SHA, "failing": ["ci"]}
SCENARIOS = (
    {},
    {"patch": {"facts-1": dict(HELD, state="CLOSED")}},
    {"children": {"1": TASK_STOP}, "replies": {"settle-1": {"state": "CLOSED", "release": "released"}}},
    {"args": dict(ARGS, unattended=True), "children": {"1": QUESTION}},
    {"args": dict(ARGS, unattended=True),
     "patch": folded({"state": "needs_label", "head": SHA, "label": "raise-me", "failing": ["gate"]})},
    {"patch": folded(CI_RED),
     "replies": {"land-record-1-1": {"ok": True, "head": FIX}}},
    {"patch": BEHIND,
     "replies": {"land-sync-1-1": ABORTED, "land-sync-resolve-1-1": {"status": "done", "conflicted": True, "head": B, "merge_commit": B,
                                   "resolved_files": ["x.py"], "tests": ["t"], "notes": "ok"}}},
    # #913: a retake whose wait ran out is waited for again in a land-relock step.
    {"patch": BEHIND,
     "replies": {"land-sync-1-1": ABORTED,
                 "land-record-1-1": {"ok": True, "head": B, "lock": {"verdict": "land-contended"}, "checks": None},
                 "land-checks-1-2": {"state": "passed", "head": B, "required": ["ci"], "passed": ["ci"]}}},
    # #907: a sync-review finding reaches the fix round and its re-review.
    {"patch": BEHIND,
     "replies": {"land-sync-1-1": ABORTED, "land-sync-resolve-1-1": {"status": "done", "conflicted": True, "head": B, "merge_commit": B, "notes": "ok"},
                 "land-sync-review-1-1": {"verdict": "findings", "findings": [{"severity": "important", "summary": "dropped"}]}}},
    {"patch": BEHIND,
     "replies": {"land-sync-1-1": {"status": "done", "conflicted": False, "head": B, "merge_commit": B, "notes": "ok"},
                 "land-record-1-1": {"ok": True, "head": B, "lock": {"verdict": "lost_to", "lock_sha": SHA, "by": HOLDER}},
                 "land-status-1-1": {"verdict": "held_by", "lock_sha": B, "by": HOLDER},
                 "land-checks-1-2": {"state": "passed", "head": B, "required": ["ci"], "passed": ["ci"]}}},
    {"patch": folded({"state": "pending", "head": SHA, "pending": ["e2e"]})},
    {"replies": {"land-pr-1": {"pr": 41, "head": SHA, "lock": {"verdict": "land-contended"}}}},
    {"patch": {"facts-1": dict(HELD, open_pr=OPEN_PR)}},
    {"args": dict(ARGS, conts={"1": {"setup": {}, "pr": 41}}),
     "patch": {"facts-1": dict(HELD, **landing(41))},
     "children": {"1": {"stage": "done", "pr": 41, "merged": True,
                        "acceptance": [{"id": "AC1", "text": "works", "kind": "code"}],
                        "close_out": {"issue_state": "CLOSED", "released": True}}}},
    # #822: a train of two ready issues reaches every train step.
    {"args": dict(ARGS, issues=[1, 2], train=True), "patch": BEHIND},
    # A member PR the merge step still read OPEN is read again by a train-flip step.
    {"args": dict(ARGS, issues=[1, 2], train=True), "patch": BEHIND,
     "replies": {"train-merge-1": {"merged": True, "prs": [{"pr": 41, "state": "MERGED"}, {"pr": 42, "state": "OPEN"}]}}},
)


def all_calls():
    return [c for scenario in SCENARIOS for c in run(**scenario)[1]
            if c.get("kind", "agent") == "agent"]


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
        found = [c for c in all_calls() if c["label"].startswith("land-pr-")]
        self.assertTrue(found)
        for call in found:
            self.assertEqual((call["agentType"], call["effort"]), ("clerk", "high"), call["label"])


class ClerkModelTest(unittest.TestCase):
    """#803, #813: clerk_model is checked, sets the model of every clerk call except the setup and lifecycle steps, which stay on the default, and is passed to every child and the relaunch only when haiku."""

    ON_DEFAULT = {"setup", "land-unlock-", "land-lock-", "land-relock-", "land-pr-", "land-merge-", "land-record-", "land-checks-", "close-out-",
                  "train-sweep-", "train-pr-", "train-checks-", "train-merge-"}

    def test_clerk_model_must_be_sonnet_or_haiku(self):
        for bad in ("opus", "Haiku", "", 1, None, True):
            with self.subTest(bad=bad):
                result, calls, _ = run(args=dict(ARGS, clerk_model=bad))
                self.assertEqual(result, {"stage": "args", "error": "clerk_model must be sonnet or haiku"})
                self.assertEqual(calls, [])

    def test_sonnet_passes_nothing(self):
        for args in (ARGS, dict(ARGS, clerk_model="sonnet")):
            with self.subTest(args=args):
                result, calls, _ = run(args=args, children={"1": ReviewSizingTest.STOP})
                self.assertEqual(child(calls, 1)["args"],
                                 {"repo_root": "/r", "issue": 1, "batch_id": "b1", "mode": "plan", "lane": "standard"})
                self.assertNotIn("clerk_model", result["relaunch"])

    def test_haiku_reaches_the_child_the_relaunch_and_the_resumed_child(self):
        result, calls, _ = run(args=dict(ARGS, clerk_model="haiku"), children={"1": ReviewSizingTest.STOP})
        self.assertEqual(child(calls, 1)["args"], {"repo_root": "/r", "issue": 1, "batch_id": "b1", "mode": "plan",
                                                   "lane": "standard", "clerk_model": "haiku"})
        self.assertEqual(result["relaunch"]["clerk_model"], "haiku")
        _, calls, _ = run(args=result["relaunch"], patch={"facts-1": {"claim": {"verdict": "held_by", "by": HOLDER}}})
        self.assertEqual(child(calls, 1)["args"], {"repo_root": "/r", "issue": 1, "batch_id": "b1", "mode": "ready",
                                                   "cont": {"setup": {}}, "clerk_model": "haiku"})

    def test_haiku_reaches_the_standard_rerun_of_an_ineligible_direct_child(self):
        ineligible = {"stage": "ineligible", "cont": {"setup": {}, "lane": "direct"}}
        _, calls, _ = run(args=dict(ARGS, clerk_model="haiku"), patch={"facts-1": {"lane": "direct", "why": "small"}},
                          children={"1": [ineligible, ReviewSizingTest.STOP]})
        runs = [c for c in calls if c["label"] == "child-1"]
        self.assertEqual(len(runs), 2)
        for c in runs:
            self.assertEqual(c["args"]["clerk_model"], "haiku")

    def test_every_clerk_call_takes_the_clerk_model(self):
        clerk_stems = {stem for stem, kinds in EXPECTED.items() if kinds == frozenset({CLERK})}
        reached = set()
        pinned = set()
        for index, scenario in enumerate(SCENARIOS):
            with self.subTest(i=index):
                base = [c for c in run(**scenario)[1] if c.get("kind", "agent") == "agent"]
                trial_args = dict(scenario.get("args", ARGS), clerk_model="haiku")
                trial = [c for c in run(**dict(scenario, args=trial_args))[1] if c.get("kind", "agent") == "agent"]
                self.assertEqual(labels(trial), labels(base))
                for b, t in zip(base, trial):
                    self.assertEqual(t["agentType"], b["agentType"], t["label"])
                    self.assertEqual(t["effort"], b["effort"], t["label"])
                    if b["agentType"] == CLERK:
                        stem = AgentTypeTest.stem_of(t["label"])
                        self.assertEqual(b["model"], "sonnet", b["label"])
                        if stem in self.ON_DEFAULT:
                            self.assertEqual(t["model"], "sonnet", t["label"])
                            pinned.add(stem)
                        else:
                            self.assertEqual(t["model"], "haiku", t["label"])
                            reached.add(stem)
                    else:
                        self.assertEqual(t["model"], b["model"], t["label"])
        self.assertEqual(pinned, self.ON_DEFAULT)
        self.assertEqual(reached, clerk_stems - self.ON_DEFAULT)

    def test_every_clerk_site_names_the_clerk_model(self):
        text = PROGRAM.read_text(encoding="utf-8")
        sites = re.findall(r"agentType: 'clerk', model: ([^,]+),", text)
        self.assertEqual(len(sites), text.count("agentType: 'clerk'"))
        self.assertGreater(len(sites), 0)
        self.assertLessEqual(set(sites), {"CLERK_MODEL", "DEFAULT_CLERK_MODEL"})

    def test_meta_names_the_steps_clerk_model_covers(self):
        meta = PROGRAM.read_text(encoding="utf-8")
        meta = meta[:meta.index("\n}\n")]
        covers = meta[meta.index("clerk_model?"):meta.index("; returns one table")]
        for needle in ("the status clerk steps", "setup", "lifecycle verb", "stay on sonnet"):
            with self.subTest(needle=needle):
                self.assertIn(needle, covers)


RESOLVE_SCOPE = "the checks of the pull request cover everything else the merge brought in, so run no test for a file that merged cleanly"
WHOLE_RUN = ("run in full every test file among or covering", "never a single test class",
             "any fast suite the project declares", "each command and its result")


class WholeTestFileLandTest(unittest.TestCase):
    """#787: the batch's post-loop implementer steps (the first resync's conflict resolution and the CI fix) run whole test files and any fast suite, and report each command and its result."""

    def assert_whole(self, text, files):
        for needle in WHOLE_RUN + (f"covering {files}",):
            self.assertIn(needle, text)
        self.assertNotIn("Run only the tests", text)
        self.assertNotIn("run only the tests", text)

    def test_the_conflict_resolution_runs_whole_files_and_reports_them(self):
        _, calls, _ = run(patch=BEHIND, replies={"land-sync-1-1": ABORTED})
        resolve = prompt(calls, "land-sync-resolve-1-1")
        self.assert_whole(resolve, "the files you resolved by hand")
        # #941: the resolution tests what it resolved; the pull request's checks cover what the merge brought in.
        self.assertIn(RESOLVE_SCOPE, resolve)
        self.assertNotIn("against its first parent", resolve)

    def test_the_ci_fix_runs_whole_files_before_it_pushes(self):
        _, calls, _ = run(patch=folded(CI_RED))
        self.assertIn("land-fix-1", labels(calls))
        text = prompt(calls, "land-fix-1")
        self.assert_whole(text, "the files you changed")
        self.assertIn("push origin", text)
        self.assertIn("before pushing, run in full every test file", text)


class KeptObligationLandTest(unittest.TestCase):
    """#787: the byte-budget trims left these obligations of the land prompts in place."""

    def test_another_branchs_pr_is_left_untouched(self):
        _, calls, _ = run()
        self.assertIn("even when it references this issue; leave it untouched.", prompt(calls, "land-pr-1"))

    def test_a_rerun_must_not_merge_twice(self):
        _, calls, _ = run()
        self.assertIn("a re-run must not merge twice.", prompt(calls, "land-merge-1"))


class CodexUnavailableDetailTest(unittest.TestCase):
    """#790: a codex-unavailable child stop shows the reviewer's reason in the table."""

    REASON = "runtime failure: You've hit your usage limit. Try again at Nov 12th, 2026 5:34 AM."

    def test_a_codex_unavailable_stop_shows_its_reason(self):
        for c in ({"stage": "codex-unavailable", "step": "code", "details": self.REASON, "cont": {"setup": {}}},
                  {"stage": "codex-unavailable", "step": "plan", "details": self.REASON}):
            with self.subTest(cont="cont" in c):
                result, _, _ = run(children={"1": c})
                self.assertEqual(row(result, 1), {"issue": 1, "outcome": "stopped",
                                                  "stage": "codex-unavailable", "reason": f"codex-unavailable: {self.REASON}"})

    def test_a_codex_unavailable_dead_agent_stop_shows_its_reason_and_trips_the_breaker(self):
        nothing = "the Codex review step returned nothing"
        c = {"stage": "codex-unavailable", "step": "code", "details": nothing, "dead_agents": ["final-codex"],
             "cont": {"setup": {}}}
        result, calls, _ = run(args=dict(ARGS, issues=[1, 2]), patch={"setup": {"max_parallel": 1}},
                               children={"1": c})
        self.assertEqual(result["stage"], "breaker")
        self.assertNotIn("child-2", labels(calls))
        self.assertEqual(result["relaunch"]["issues"], [1, 2])
        self.assertEqual(row(result, 1), {"issue": 1, "outcome": "stopped", "stage": "codex-unavailable",
                                          "dead_agents": ["final-codex"], "reason": f"codex-unavailable: {nothing}"})

    def test_other_stops_keep_their_row(self):
        for c in ({"stage": "task", "details": "x", "cont": {"setup": {}}},
                  {"stage": "codex-unavailable", "step": "code", "cont": {"setup": {}}},
                  {"stage": "plan-review", "details": "the plan reviewer returned nothing",
                   "dead_agents": ["plan-review"], "cont": {"setup": {}}}):
            with self.subTest(stage=c["stage"]):
                result, _, _ = run(children={"1": c})
                self.assertNotIn("detail", row(result, 1))


class StopReasonTest(unittest.TestCase):
    """#869: a stopped row says why, the table text shows it and a relaunch keeps it until the issue moves on."""

    CHILD_ARGS = {"repo_root": "/r", "issue": 1, "batch_id": "b1", "lane": "standard"}
    BLOCKED = "Task 1 cannot be finished as written because it depends on Task 2"
    WAITS = {"facts-1": {"blockers": [{"issue": 50, "state": "OPEN"}]}}

    def child_stop(self, mode, replies, stage):
        result, _ = run_child(dict(self.CHILD_ARGS, mode=mode), replies=replies)
        self.assertEqual(result["stage"], stage, result)
        return result

    def refused_plan(self):
        bad = {"status": "planned", "plan_root": "/g/plan.md", "acceptance": [{"id": "AC1", "text": "works", "kind": "code"}],
               "tasks": [{"n": 1, "title": "one", "file": "/g/task-1.md", "risk": "standard", "branch": "other"}]}
        return self.child_stop("plan", {"plan": bad, "plan-branch-revise": bad}, "plan")

    def blocked_task(self):
        return self.child_stop("ready", {"impl-1": {"status": "blocked", "notes": self.BLOCKED}}, "task")

    def test_a_refused_plan_and_a_blocked_task_reach_the_row_and_the_table_text(self):
        cases = ((self.refused_plan(), "plan", 'plan: branch problems: task 1: branch "other" is not declared'),
                 (self.blocked_task(), "task", f"task: task 1 blocked: {self.BLOCKED}"))
        for stop, stage, reason in cases:
            with self.subTest(stage=stage):
                out = run_full(children={"1": stop})
                result = out["result"]
                self.assertEqual(row(result, 1), {"issue": 1, "outcome": "stopped", "stage": stage, "reason": reason})
                self.assertIn(f"#1: stopped ({reason})", out["logs"])
                self.assertEqual(result["relaunch"]["reasons"], {"1": reason})

    def test_a_child_that_throws_names_the_error_and_the_script(self):
        MSG = "Cannot load the script\n    at load (workflow.js:1)"
        WHY = "child program could not be loaded or threw: Cannot load the script (/s/deliver-standard.js)"
        DIRECT = {"facts-1": {"lane": "direct", "why": "small"}}
        INELIGIBLE = {"stage": "ineligible", "cont": {"setup": {}, "lane": "direct"}}
        cases = (
            ("plan call", {"children": {"1": {"throw": MSG}}}),
            ("ready call after a plan", {"children": {"1": [planned(1), {"throw": MSG}]}}),
            ("direct ready call", {"patch": DIRECT, "children": {"1": {"throw": MSG}}}),
            ("standard rerun of an ineligible direct child", {"patch": DIRECT, "children": {"1": [INELIGIBLE, {"throw": MSG}]}}),
        )
        for name, scenario in cases:
            with self.subTest(name):
                out = run_full(**scenario)
                result = out["result"]
                self.assertEqual(row(result, 1), {"issue": 1, "outcome": "stopped", "reason": WHY})
                self.assertEqual(result["relaunch"]["reasons"], {"1": WHY})
                self.assertIn(f"#1: stopped ({WHY})", out["logs"])
                self.assertNotIn("at load", row(result, 1)["reason"])
                self.assertEqual(result["stage"], "breaker")
                self.assertTrue(any(line.startswith("#1: child-1 threw: ") and "at load (workflow.js:1)" in line for line in out["logs"]), out["logs"])
        with self.subTest("another script path"):
            out = run_full(args=dict(ARGS, child_script="/c/other.js"), children={"1": {"throw": MSG}})
            self.assertEqual(row(out["result"], 1)["reason"], "child program could not be loaded or threw: Cannot load the script (/c/other.js)")
        with self.subTest("empty message"):
            out = run_full(children={"1": {"throw": ""}})
            self.assertEqual(row(out["result"], 1)["reason"], "child program could not be loaded or threw: no message (/s/deliver-standard.js)")

    def test_a_long_thrown_message_keeps_the_script_path(self):
        LONG = "E" * 400
        CUT = "child program could not be loaded or threw: " + "E" * 228 + "... (/s/deliver-standard.js)"
        self.assertEqual(len(CUT), 300)
        out = run_full(children={"1": {"throw": LONG}})
        result = out["result"]
        self.assertEqual(row(result, 1), {"issue": 1, "outcome": "stopped", "reason": CUT})
        self.assertEqual(result["relaunch"]["reasons"], {"1": CUT})
        self.assertIn(f"#1: stopped ({CUT})", out["logs"])
        self.assertTrue(any(line.startswith("#1: child-1 threw: ") and LONG in line for line in out["logs"]), out["logs"])

    def test_a_long_child_script_path_keeps_its_file_name(self):
        FILE = "deliver-standard.js"
        PATH = "/" + "d" * (300 - len(FILE) - 2) + "/" + FILE
        self.assertEqual(len(PATH), 300)
        THREW = "child program could not be loaded or threw: "
        for label, message in (("short message", "Cannot load the script"), ("long message", "E" * 400)):
            with self.subTest(label):
                out = run_full(args=dict(ARGS, child_script=PATH), children={"1": {"throw": message}})
                reason = row(out["result"], 1)["reason"]
                self.assertLessEqual(len(reason), 300)
                self.assertTrue(reason.startswith(THREW + message[:20]), reason)
                self.assertIn(" (...d", reason)
                self.assertTrue(reason.endswith(PATH[-100:] + ")"), reason)
                self.assertTrue(reason.endswith(FILE + ")"), reason)
                self.assertEqual(out["result"]["relaunch"]["reasons"], {"1": reason})
                self.assertTrue(any(line.startswith("#1: child-1 threw: ") and message in line for line in out["logs"]), out["logs"])

    def test_every_stopped_row_has_a_bounded_one_line_reason(self):
        long = {"stage": "task", "reason": "task: " + "x\n" * 400, "cont": {"setup": {}}}
        rows = (
            ({"children": {"1": long}}, None),
            ({"children": {"1": {"stage": "verify", "cont": {"setup": {}}}}}, "verify"),
            ({"children": {"1": {"stage": "args", "error": "mode must be plan, ready or ship"}}}, "args: mode must be plan, ready or ship"),
            ({"children": {"1": None}}, "child-1 returned nothing"),
            ({"children": {"1": {"stage": "setup", "result": {"ok": True}, "missing": ["worktree_path", "branch"],
                                 "cont": {"claim_incomplete": True}}}}, "setup: setup reply lacks worktree_path, branch"),
            ({"children": {"1": {"stage": "setup", "result": {"ok": False, "reason": "not-resumable", "details": "the worktree\nis gone"}}}},
             "setup: not-resumable; the worktree is gone"),
            ({"children": {"1": {"stage": "setup", "result": None}}}, "setup: the step returned nothing"),
            ({"children": {"1": {"stage": "setup", "result": {"ok": True}, "invalid": "holder", "holder": "x"}}}, "setup: invalid holder"),
            ({"patch": {"facts-1": {"claim": {"verdict": "error", "by": None}}}}, "claim status"),
            ({"replies": {"land-merge-1": None}}, "merge: land-merge-1 returned nothing"),
        )
        for scenario, reason in rows:
            with self.subTest(reason=reason):
                result, _, _ = run(**scenario)
                got = row(result, 1)
                self.assertEqual(got["outcome"], "stopped")
                self.assertLessEqual(len(got["reason"]), 300)
                self.assertNotIn("\n", got["reason"])
                if reason is not None:
                    self.assertEqual(got["reason"], reason)
        landed, _, _ = run()
        self.assertNotIn("reason", row(landed, 1))

    def test_the_reason_survives_a_relaunch_until_the_issue_moves_on(self):
        stop = self.blocked_task()
        reason = f"task: task 1 blocked: {self.BLOCKED}"
        first, _, _ = run(children={"1": stop})
        # The relaunch does not get to the issue: its row still says why it stopped, and the next relaunch keeps saying so.
        waiting = run_full(args=first["relaunch"], patch=self.WAITS)
        second = waiting["result"]
        self.assertEqual(row(second, 1), {"issue": 1, "outcome": "blocked", "blocker": 50, "blockers": ["#50"], "reason": f"waits for #50; previous run: {reason}"})
        self.assertIn(f"#1: blocked (waits for #50; previous run: {reason})", waiting["logs"])
        self.assertEqual(second["relaunch"]["reasons"], {"1": reason})
        third, _, _ = run(args=second["relaunch"], patch=self.WAITS)
        self.assertEqual(third["relaunch"], second["relaunch"])
        # A new stop replaces it, and an issue that lands drops it.
        again, _, _ = run(args=first["relaunch"], children={"1": {"stage": "verify", "reason": "verify: build: 2 tests failed", "cont": stop["cont"]}})
        self.assertEqual(row(again, 1)["reason"], "verify: build: 2 tests failed")
        self.assertEqual(again["relaunch"]["reasons"], {"1": "verify: build: 2 tests failed"})
        landed, _, _ = run(args=first["relaunch"])
        self.assertEqual(row(landed, 1), {"issue": 1, "outcome": "landed", "pr": 41})
        self.assertIsNone(landed["relaunch"])

    def test_the_relaunch_grows_by_at_most_the_bounded_reason(self):
        stop = dict(self.blocked_task(), reason="task: " + "y" * 900)
        result, _, _ = run(children={"1": stop})
        relaunch = result["relaunch"]
        self.assertEqual(len(relaunch["reasons"]["1"]), 300)
        self.assertLessEqual(size(relaunch) - size(without(relaunch, "reasons")), 300 + len(',"reasons":{"1":""}'))
        capped, _, _ = run(args=dict(ARGS, reasons={"1": "z" * 900}), patch=self.WAITS)
        self.assertEqual(len(capped["relaunch"]["reasons"]["1"]), 300)

    def test_a_flapping_stop_with_an_unchanged_cont_repeats_the_relaunch_reasons_aside(self):
        """The lead stops relaunching once a relaunch, reasons aside, equals the args it ran with; the relaunch carries the latest reason."""
        stop = self.blocked_task()
        relaunch, _, _ = run(children={"1": stop})
        relaunch = relaunch["relaunch"]
        for flap in ("verify: build: 2 tests failed", "task: task 1 blocked: Task 2 has to come first", "verify: build: 1 test failed"):
            with self.subTest(flap=flap):
                result, _, _ = run(args=relaunch, children={"1": dict(stop, stage=flap.split(":")[0], reason=flap)})
                self.assertEqual(row(result, 1)["reason"], flap)
                self.assertEqual(result["relaunch"]["reasons"], {"1": flap})
                self.assertEqual(without(result["relaunch"], "reasons"), without(relaunch, "reasons"))
                relaunch = result["relaunch"]

    def test_every_open_row_fills_the_reason_column(self):
        """A row that is not final says why in reason, whatever member held it; a final row has none."""
        red = {"state": "failed", "head": SHA, "failing": ["ci"], "details": "FAIL test_cache"}
        rejected = {"land-sync-1-1": ABORTED, "land-sync-resolve-1-1": {"status": "done", "conflicted": True, "head": "b" * 40, "merge_commit": "b" * 40, "notes": "ok"},
                    "land-sync-review-1-1": {"verdict": "findings", "findings": [{"severity": "important", "summary": "dropped a change"}]},
                    "land-sync-rereview-1-1": {"verdict": "findings", "findings": [{"severity": "important", "summary": "dropped a change"}]}}
        rows = (
            ("ci-failed", {"patch": {"land-pr-1": {"checks": red}}, "replies": {"land-fix-1": None}},
             "the fix round did not finish; failing checks ci"),
            ("land-contended", {"patch": {"land-pr-1": {"lock": {"verdict": "held_by", "by": "h2/b9"}}}},
             "the land lock is held by another landing (held_by)"),
            ("blocked", {"patch": self.WAITS}, "waits for #50"),
            ("claim-lost", {"children": {"1": {"stage": "claimed", "verdict": "held_by", "by": "h2/b9"}}}, "claimed by h2/b9"),
        )
        for outcome, scenario, reason in rows:
            with self.subTest(outcome=outcome):
                result, _, _ = run(**scenario)
                got = row(result, 1)
                self.assertEqual((got["outcome"], got["reason"]), (outcome, reason))
                self.assertNotIn("detail", got)
        cycle = {"facts-1": {"blockers": [{"issue": 2, "state": "OPEN"}]}, "facts-2": {"blockers": [{"issue": 1, "state": "OPEN"}]}}
        result, _, _ = run(args=dict(ARGS, issues=[1, 2]), patch=cycle)
        self.assertEqual([(row(result, n)["outcome"], row(result, n)["reason"]) for n in (1, 2)],
                         [("blocked", "cycle"), ("blocked", "cycle")])
        result, _, _ = run(patch=BEHIND, replies=rejected)
        self.assertEqual((row(result, 1)["outcome"], row(result, 1)["reason"]),
                         ("sync-review", f"sync-review of merge {'b' * 40}: a finding survived the fix round; unaccepted fix commit {'f' * 40}; "
                          "finding dropped a change"))
        waiting, _, _ = run(patch={"facts-1": {"decision": {"verdict": "open", "comment_id": 5, "questions": ["Which?"]}}})
        self.assertEqual(row(waiting, 1)["outcome"], "questions")
        self.assertNotIn("reason", row(waiting, 1))

    def test_a_real_setup_stop_of_the_child_reaches_the_row(self):
        refused, _ = run_child(dict(self.CHILD_ARGS, mode="ready"),
                               replies={"setup": {"ok": False, "reason": "closed", "details": "the issue is closed"}})
        self.assertEqual((refused["stage"], "reason" in refused), ("setup", False))
        result, _, _ = run(children={"1": refused})
        self.assertEqual(row(result, 1)["reason"], "setup: closed; the issue is closed")
        lacking, _ = run_child(dict(self.CHILD_ARGS, mode="ready"), patch={"setup": {"merge_strategy": None}})
        self.assertEqual(lacking["stage"], "setup")
        result, _, _ = run(children={"1": lacking})
        self.assertEqual(row(result, 1)["reason"], "setup: setup reply lacks merge_strategy")

    def test_reasons_must_be_strings(self):
        for bad in ([], "x", {"1": 5}, {"1": None}):
            with self.subTest(bad=bad):
                result, calls, _ = run(args=dict(ARGS, reasons=bad))
                self.assertEqual((result["stage"], calls), ("args", []))


class FoldedCloseOutReleaseTest(unittest.TestCase):
    """#801: the lock release rides first in the close-out call."""

    REL = f"forge-claim land release --repo owner/repo --branch dev --sha {SHA}\n"
    CLAIM_RELEASE = f"forge-claim release --repo owner/repo --issue 1 --holder {HOLDER} --reason done"

    def test_the_close_out_releases_the_land_lock_first(self):
        result, calls, _ = run()
        self.assertEqual(row(result, 1)["outcome"], "landed")
        self.assertIsNone(result["relaunch"])
        ls = of(calls, 1)
        self.assertEqual(ls[-2:], ["land-merge-1", "close-out-1"])
        self.assertNotIn("land-unlock-1", ls)
        text = prompt(calls, "close-out-1")
        self.assertIn(self.REL, text)
        self.assertLess(text.index(self.REL), text.index(self.CLAIM_RELEASE))
        member = schema_of(calls, "close-out-1")["properties"]["release"]
        self.assertLessEqual({"verdict", "detail"}, set(object_branch(member)["properties"]))
        self.assertIn({"type": "null"}, member["anyOf"])

    def test_an_unconfirmed_folded_release_falls_back_to_one_standalone_release(self):
        for release in (None, {"verdict": "error", "detail": "gh failed"}):
            with self.subTest(release=release):
                result, calls, _ = run(patch={"close-out-1": {"release": release}})
                self.assertEqual(row(result, 1)["outcome"], "landed")
                self.assertIsNone(result["relaunch"])
                ls = of(calls, 1)
                self.assertEqual(ls[-2:], ["close-out-1", "land-unlock-1"])
                self.assertEqual(ls.count("land-unlock-1"), 1)
                self.assertIn(f"--sha {SHA}\n", prompt(calls, "land-unlock-1"))
        result, calls, _ = run(patch={"close-out-1": {"release": {"verdict": "not_held"}}})
        self.assertEqual(row(result, 1)["outcome"], "landed")
        self.assertNotIn("land-unlock-1", labels(calls))

    def test_a_lost_close_out_reply_releases_once_and_keeps_the_cont(self):
        result, calls, _ = run(replies={"close-out-1": None})
        self.assertEqual((row(result, 1)["outcome"], row(result, 1)["stage"]), ("stopped", "close-out"))
        self.assertEqual(result["relaunch"]["issues"], [1])
        self.assertEqual(result["relaunch"]["conts"], POST_MERGE_CONTS)
        ls = of(calls, 1)
        self.assertEqual(ls[-2:], ["close-out-1", "land-unlock-1"])
        self.assertEqual(ls.count("land-unlock-1"), 1)
        result, calls, _ = run(replies={"close-out-1": "throw"})
        self.assertEqual((row(result, 1)["outcome"], row(result, 1)["stage"]), ("stopped", "land"))
        self.assertEqual(result["relaunch"]["conts"], POST_MERGE_CONTS)
        ls = of(calls, 1)
        self.assertEqual(ls.count("land-unlock-1"), 1)
        self.assertLess(ls.index("close-out-1"), ls.index("land-unlock-1"))

    def test_a_close_out_that_stops_keeps_its_stage_and_cont_and_needs_no_fallback(self):
        result, calls, _ = run(replies={"close-out-1": {"issue_state": "OPEN", "released": True, "decision_ended": True}})
        self.assertEqual((row(result, 1)["outcome"], row(result, 1)["stage"]), ("stopped", "close-out"))
        self.assertEqual(row(result, 1)["expected_issue_state"], "CLOSED")
        self.assertNotIn("land-unlock-1", labels(calls))
        self.assertEqual(result["relaunch"]["conts"], POST_MERGE_CONTS)


class FoldedFirstLandChecksTest(unittest.TestCase):
    """#801: land-pr carries the first checks poll; a resync runs only on behind."""

    CHECKS_CMD = "gh pr checks <the PR number> --repo owner/repo --json name,bucket,link"

    def test_land_pr_carries_the_first_checks_poll_and_runs_no_first_resync(self):
        result, calls, _ = run()
        self.assertEqual(row(result, 1)["outcome"], "landed")
        self.assertIsNone(result["relaunch"])
        self.assertEqual(of(calls, 1), ["facts-1", "acquire-1", "child-1", "child-1", "land-pr-1", "land-merge-1",
                                        "close-out-1"])
        text = prompt(calls, "land-pr-1")
        self.assertIn(self.CHECKS_CMD, text)
        self.assertIn("gh api repos/owner/repo/rules/branches/dev", text)
        self.assertLess(text.index(f"--sha {SHA} --wait\n"), text.index(self.CHECKS_CMD))
        member = schema_of(calls, "land-pr-1")["properties"]["checks"]
        self.assertEqual(set(object_branch(member)["properties"]),
                         {"state", "head", "required", "passed", "failing", "pending", "label", "details"})
        self.assertIn({"type": "null"}, member["anyOf"])

    def test_each_folded_first_checks_answer_is_graded_as_before(self):
        behind = {"state": "behind", "head": SHA}
        pending = {"state": "pending", "head": SHA, "pending": ["e2e"]}
        fix_review = {"verdict": "findings", "findings": [{"severity": "important", "summary": "skipped a test"}]}
        table = (
            (None, {}, ("stopped", "checks"), PRE_MERGE_CONTS,
             lambda ls: (self.assertEqual(ls.count("land-unlock-1"), 1), self.assertNotIn("land-merge-1", ls))),
            ({"state": "passed", "head": B}, {}, ("stopped", "head-moved"), PRE_MERGE_CONTS,
             lambda ls: self.assertNotIn("land-merge-1", ls)),
            (pending, {"land-checks-1-2": pending, "land-checks-1-3": pending}, ("stopped", "checks-pending"),
             PRE_MERGE_CONTS,
             lambda ls: (self.assertIn("land-checks-1-3", ls), self.assertNotIn("land-checks-1-4", ls))),
            (behind, {}, ("landed", None), None,
             lambda ls: self.assertEqual(ls[ls.index("land-pr-1"):],
                                         ["land-pr-1", "land-sync-1-1", "land-checks-1-2", "land-merge-1",
                                          "close-out-1"])),
            (behind, {"land-checks-1-2": behind, "land-checks-1-3": behind}, ("land-contended", None), PRE_MERGE_CONTS,
             lambda ls: (self.assertIn("land-sync-1-1", ls), self.assertIn("land-sync-1-2", ls),
                         self.assertNotIn("land-sync-1-3", ls), self.assertIn("land-unlock-1", ls))),
            (CI_RED, {"land-fix-review-1": fix_review}, ("ci-failed", None), PRE_MERGE_CONTS,
             lambda ls: (self.assertNotIn("land-record-1-1", ls), self.assertNotIn("land-merge-1", ls))),
        )
        for folded, extra, (outcome, stage), conts, check in table:
            with self.subTest(folded=folded, outcome=outcome):
                result, calls, _ = run(patch={"land-pr-1": {"checks": folded}}, replies=extra)
                self.assertEqual(row(result, 1)["outcome"], outcome)
                if stage:
                    self.assertEqual(row(result, 1)["stage"], stage)
                if folded is None:
                    self.assertEqual(row(result, 1)["reason"], "checks: land-pr-1 returned no checks")
                if conts is None:
                    self.assertIsNone(result["relaunch"])
                else:
                    self.assertEqual(result["relaunch"]["conts"], conts)
                check(of(calls, 1))

    def test_a_behind_resync_that_merges_still_pushes_records_and_moves_the_lock(self):
        result, calls, _ = run(
            patch={"land-pr-1": {"checks": {"state": "behind", "head": SHA}}},
            replies={"land-sync-1-1": {"status": "done", "conflicted": False, "head": B, "merge_commit": B, "notes": "ok"}})
        self.assertEqual(row(result, 1)["outcome"], "landed")
        self.assertIsNone(result["relaunch"])
        ls = labels(calls)
        self.assertLess(ls.index("land-sync-1-1"), ls.index("land-record-1-1"))
        self.assertLess(ls.index("land-record-1-1"), ls.index("land-merge-1"))
        self.assertIn("git -C /r/.wt/w-issue-1-x push origin issue-1-x", prompt(calls, "land-sync-1-1"))
        self.assertIn(f"--sha {B}\n", prompt(calls, "land-record-1-1"))
        self.assertIn(f"forge-claim land release --repo owner/repo --branch dev --sha {B}\n", prompt(calls, "close-out-1"))


class FoldedRecordChecksTest(unittest.TestCase):
    """#801: the record step carries the next checks poll."""

    def test_a_fix_lands_through_the_record_step_carrying_its_checks(self):
        result, calls, _ = run(patch=folded(CI_RED), replies={"land-record-1-1": {"ok": True, "head": FIX}})
        self.assertEqual(row(result, 1)["outcome"], "landed")
        self.assertIsNone(result["relaunch"])
        ls = of(calls, 1)
        self.assertEqual(ls[ls.index("land-fix-1"):],
                         ["land-fix-1", "land-fix-review-1", "land-record-1-1", "land-merge-1", "close-out-1"])
        self.assertNotIn("land-checks-1-2", ls)
        text = prompt(calls, "land-record-1-1")
        self.assertLess(text.index(f"--sha {FIX}\n"), text.index("gh pr checks 41 --repo owner/repo --json name,bucket,link"))
        self.assertIn(f"--match-head-commit {FIX}", prompt(calls, "land-merge-1"))
        member = schema_of(calls, "land-record-1-1")["properties"]["checks"]
        self.assertEqual(set(object_branch(member)["properties"]), {"state", "head", "passed", "failing", "pending"} | {"required", "label", "details"})
        self.assertIn({"type": "null"}, member["anyOf"])

    def test_each_record_step_answer_is_graded_as_before(self):
        table = (
            ({"ok": True, "head": FIX, "checks": None}, ("stopped", "checks"),
             lambda ls: (self.assertEqual(ls.count("land-unlock-1"), 1), self.assertNotIn("land-checks-1-2", ls),
                         self.assertNotIn("land-merge-1", ls))),
            ({"ok": True, "head": FIX, "checks": {"state": "passed", "head": "d" * 40}}, ("stopped", "head-moved"),
             lambda ls: self.assertNotIn("land-merge-1", ls)),
            ({"ok": True, "head": FIX, "checks": dict(CI_RED, head=FIX)}, ("ci-failed", None),
             lambda ls: (self.assertEqual(ls.count("land-fix-1"), 1), self.assertNotIn("land-checks-1-2", ls))),
            ({"ok": False, "head": "d" * 40, "detail": "head differs", "lock": None}, ("stopped", "land-record"),
             lambda ls: self.assertNotIn("land-checks-1-2", ls)),
            ({"ok": True, "head": FIX, "lock": {"verdict": "lost_to", "lock_sha": "c" * 40, "by": "h2/b9"}},
             ("land-contended", None), lambda ls: self.assertNotIn("land-checks-1-2", ls)),
        )
        for reply, (outcome, stage), check in table:
            with self.subTest(reply=reply):
                result, calls, _ = run(patch=folded(CI_RED), replies={"land-record-1-1": reply})
                self.assertEqual(row(result, 1)["outcome"], outcome)
                if stage:
                    self.assertEqual(row(result, 1)["stage"], stage)
                if outcome == "stopped" and stage == "checks":
                    self.assertEqual(row(result, 1)["reason"], "checks: land-record-1-1 returned no checks")
                if stage == "head-moved":
                    self.assertEqual(row(result, 1)["head"], "d" * 40)
                self.assertEqual(result["relaunch"]["issues"], [1])
                self.assertEqual(result["relaunch"]["conts"], PRE_MERGE_CONTS)
                check(of(calls, 1))

    def test_a_behind_resync_that_merges_lands_through_the_record_checks(self):
        result, calls, _ = run(patch=BEHIND, replies={
            "land-sync-1-1": {"status": "done", "conflicted": False, "head": B, "merge_commit": B, "notes": "ok"}})
        self.assertEqual(row(result, 1)["outcome"], "landed")
        self.assertIsNone(result["relaunch"])
        ls = of(calls, 1)
        self.assertEqual(ls[ls.index("land-sync-1-1"):], ["land-sync-1-1", "land-record-1-1", "land-merge-1", "close-out-1"])

    def test_a_round_without_a_head_change_still_polls_alone(self):
        result, calls, _ = run(patch=folded({"state": "pending", "head": SHA, "pending": ["e2e"]}))
        self.assertEqual(row(result, 1)["outcome"], "landed")
        self.assertIsNone(result["relaunch"])
        self.assertIn("land-checks-1-2", of(calls, 1))
        self.assertNotIn("land-record-1-1", of(calls, 1))


class AmendTest(unittest.TestCase):
    def test_amend_args_are_checked_before_any_agent(self):
        r = reviewed(1)
        bad = [dict(ARGS, amend="x"), dict(ARGS, conts={"1": r}, amend=[]), dict(ARGS, amend={"1": [AMEND_EDIT]}),
               dict(ARGS, conts={"1": r}, amend={"2": [AMEND_EDIT]})]
        for value in ([], ["x"], AMEND_EDIT, [{}], [{"file": "task-2.md", "find": "x"}],
                      [{"file": "", "find": "x", "replace": "y"}], [{"file": "task-2.md", "find": "", "replace": "y"}],
                      [{"file": "task-2.md", "find": "x", "replace": 1}]):
            bad.append(dict(ARGS, conts={"1": r}, amend={"1": value}))
        for args in bad:
            with self.subTest(args=args):
                result, calls, _ = run(args=args)
                self.assertEqual(result["stage"], "args")
                self.assertEqual(calls, [])

    def test_a_reviewed_cont_forwards_its_amend_to_its_one_child(self):
        result, calls, _ = run(args=dict(ARGS, conts={"1": reviewed(1)}, amend={"1": [AMEND_EDIT]}))
        self.assertEqual(len([c for c in calls if c["label"] == "child-1"]), 1)
        self.assertEqual(child(calls, 1)["args"]["amend"], [AMEND_EDIT])
        self.assertEqual(child(calls, 1)["args"]["cont"], reviewed(1))

    def test_the_forwarded_amend_reaches_the_child_program(self):
        _, calls, _ = run(args=dict(ARGS, conts={"1": reviewed(1)}, amend={"1": [AMEND_EDIT]}))
        child_result, child_calls = run_child(child(calls, 1)["args"])
        self.assertEqual(labels(child_calls)[:3], ["setup", "renew-amend", "amend"])
        self.assertEqual(child_result["stage"], "ready")

    def test_a_planning_ahead_cont_forwards_amend_to_the_plan_child_only(self):
        _, calls, _ = run(args=dict(ARGS, conts={"1": kept(1)}, amend={"1": [AMEND_EDIT]}))
        children = [c for c in calls if c["label"] == "child-1"]
        self.assertEqual([c["args"]["mode"] for c in children], ["plan", "ready"])
        self.assertEqual(children[0]["args"]["amend"], [AMEND_EDIT])
        self.assertNotIn("amend", children[1]["args"])

    def test_a_refused_amend_keeps_the_cont_and_the_amend_for_the_relaunch(self):
        result, calls, _ = run(
            args=dict(ARGS, conts={"1": kept(1)}, amend={"1": [AMEND_EDIT]}),
            children={"1": {"stage": "amend", "error": "amend must be a non-empty list", "cont": kept(1)}})
        self.assertEqual(len([c for c in calls if c["label"] == "child-1"]), 1)
        self.assertEqual(result["relaunch"]["conts"], {"1": slim(kept(1))})
        self.assertEqual(result["relaunch"]["amend"], {"1": [AMEND_EDIT]})

    def test_the_relaunch_carries_the_amend_of_every_issue_whose_cont_it_carries(self):
        result, _, _ = run(
            args=dict(ARGS, issues=[1, 2], conts={"1": reviewed(1), "2": reviewed(2)},
                      amend={"1": [AMEND_EDIT], "2": [AMEND_EDIT]}),
            patch={"facts-2": {"blockers": [{"issue": 50, "state": "OPEN"}]}},
            children={"1": {"stage": "task", "task": {"n": 2}, "cont": reviewed(1)}})
        self.assertEqual(result["relaunch"]["amend"], {"1": [AMEND_EDIT], "2": [AMEND_EDIT]})
        self.assertEqual(set(result["relaunch"]["conts"]), {"1", "2"})
        with self.subTest("a dropped cont drops its amend"):
            result, _, _ = run(args=dict(ARGS, conts={"1": kept(1)}, amend={"1": [AMEND_EDIT]}),
                               children={"1": {"stage": "plan", "details": "x"}})
            self.assertNotIn("conts", result["relaunch"])
            self.assertNotIn("amend", result["relaunch"])

    def test_an_accepted_open_pr_with_a_pending_amend_goes_through_the_child_before_landing(self):
        facts = {"facts-1": {"open_pr": OPEN_PR, "claim": {"verdict": "held_by", "by": HOLDER}}}
        result, calls, _ = run(args=dict(ARGS, conts={"1": reviewed(1)}, amend={"1": [AMEND_EDIT]}), patch=facts)
        ls = labels(calls)
        self.assertEqual(child(calls, 1)["args"]["amend"], [AMEND_EDIT])
        self.assertLess(ls.index("readopt-1"), ls.index("child-1"))
        self.assertEqual(row(result, 1)["outcome"], "landed")
        with self.subTest("an amend already applied is not sent again, so the PR lands as it stands"):
            _, calls, _ = run(args=dict(ARGS, conts={"1": reviewed(1)}), patch=facts)
            self.assertNotIn("child-1", labels(calls))

    def test_an_amend_applied_before_the_review_finished_is_kept_for_the_relaunch(self):
        # The child applied the amend, then stopped before the final review and verify of the amended plan.
        facts = {"facts-1": {"open_pr": OPEN_PR, "claim": {"verdict": "held_by", "by": HOLDER}}}
        stopped = reviewed(1)
        first, _, _ = run(args=dict(ARGS, conts={"1": reviewed(1)}, amend={"1": [AMEND_EDIT]}),
                          children={"1": {"stage": "codex-unavailable", "amended": True, "details": "limit", "cont": stopped}})
        self.assertEqual(first["relaunch"]["conts"], {"1": slim(stopped)})
        self.assertEqual(first["relaunch"]["amend"], {"1": [AMEND_EDIT]})
        # The accepted PR head is unchanged, yet the relaunch must go through the child, never land as it stands.
        second, calls, _ = run(args=dict(ARGS, conts=first["relaunch"]["conts"], amend=first["relaunch"]["amend"]), patch=facts)
        self.assertEqual(child(calls, 1)["args"]["amend"], [AMEND_EDIT])
        self.assertLess(labels(calls).index("readopt-1"), labels(calls).index("child-1"))

    def test_a_run_without_amend_sends_none(self):
        result, calls, _ = run(args=dict(ARGS, conts={"1": reviewed(1)}),
                               children={"1": {"stage": "task", "task": {"n": 2}, "cont": reviewed(1)}})
        self.assertNotIn("amend", child(calls, 1)["args"])
        self.assertNotIn("amend", result["relaunch"])

    def test_an_applied_amend_is_not_kept_in_the_relaunch(self):
        F = {"severity": "important", "summary": "design gap"}
        stopped = dict(kept(1), plan_findings={"rules": [F], "findings": [F], "rounds": 0})
        result, calls, _ = run(args=dict(ARGS, conts={"1": kept(1)}, amend={"1": [AMEND_EDIT]}),
                               children={"1": {"stage": "plan-review", "amended": True, "cont": stopped}})
        self.assertEqual(result["relaunch"]["conts"], {"1": slim(stopped)})
        self.assertNotIn("amend", result["relaunch"])
        # The relaunched child plans the kept plan again instead of refusing: it carries no amend.
        retry = dict(child(calls, 1)["args"], cont=result["relaunch"]["conts"]["1"])
        retry.pop("amend", None)
        child_result, _ = run_child(retry)
        self.assertNotEqual(child_result["stage"], "amend")

    def test_an_amend_applied_by_the_plan_child_is_not_kept_when_the_ready_child_stops(self):
        plan_stop = {"stage": "planned", "plan": {"tasks": [{"n": 1}]}, "amended": True, "cont": reviewed(1)}
        result, calls, _ = run(args=dict(ARGS, conts={"1": kept(1)}, amend={"1": [AMEND_EDIT]}),
                               children={"1": [plan_stop, {"stage": "task", "task": {"n": 2}, "cont": verified_cont(1)}]})
        self.assertEqual(result["relaunch"]["conts"], {"1": slim(verified_cont(1))})
        self.assertNotIn("amend", result["relaunch"])

    def test_one_issues_applied_amend_leaves_anothers_unapplied_amend_in_the_relaunch(self):
        result, _, _ = run(args=dict(ARGS, issues=[1, 2], conts={"1": reviewed(1), "2": reviewed(2)},
                                     amend={"1": [AMEND_EDIT], "2": [AMEND_EDIT]}),
                           children={"1": {"stage": "task", "task": {"n": 2}, "amended": True, "cont": verified_cont(1)},
                                     "2": {"stage": "setup", "cont": reviewed(2)}})
        self.assertEqual(result["relaunch"]["amend"], {"2": [AMEND_EDIT]})
        self.assertEqual(set(result["relaunch"]["conts"]), {"1", "2"})


if __name__ == "__main__":
    unittest.main()


X1, X2, X3 = "1" * 40, "2" * 40, "3" * 40
TRAIN_STEMS = ("train-pr-", "train-build-", "train-checks-", "train-ready-", "train-merge-", "train-flip-")
FLIP_CALLS = 8
LAND_RELEASE = "forge-claim land release --repo owner/repo --branch dev --sha "
FORBIDDEN = ("'", '"', "$", "`", "\\")


def train_run(issues=(1, 2), replies=None, patch=None, args=None, children=None):
    """A train-enabled batch whose issues all become ready together and whose first landing is behind."""
    issues = list(issues)
    merged = {"setup": {"max_parallel": len(issues)}, **BEHIND, **(patch or {})}
    return run(args=dict(ARGS, issues=issues, train=True, **(args or {})), replies=replies, patch=merged, children=children)


def land_labels(calls):
    return [c["label"] for c in calls if c["label"].startswith(("land-", "train-", "close-out-"))]


def train_labels(calls):
    return [label for label in labels(calls) if label.startswith(TRAIN_STEMS)]


def lock_releases(calls, n=1):
    """The calls of issue n's landing that release the land lock: its close-out (folded) or its standalone unlock."""
    return [c["label"] for c in calls if c["label"] in (f"close-out-{n}", f"land-unlock-{n}") and LAND_RELEASE in c["prompt"]]


def members_of(calls, label):
    text = prompt(calls, label)
    lead = "The members, in order, as JSON: "
    return json.loads(text[text.index(lead) + len(lead):].split("\n")[0])


def merge_reply(states, lock="already_held", merged=True):
    return {"lock": {"verdict": lock, "lock_sha": SHA}, "merged": merged, "notes": "n",
            "prs": [{"pr": pr, "state": state} for pr, state in states.items()]}


def flips(state, prs, car="MERGED"):
    """Replies that answer every train-flip read of train 1 with `state` for each of `prs`."""
    return {f"train-flip-1-{k}": {"car": car, "prs": [{"pr": pr, "state": state} for pr in prs]} for k in range(1, FLIP_CALLS + 1)}


# The forge read that answers a still open car.
OPEN_CAR = {"train-flip-1-1": {"car": "OPEN", "prs": []}}


def flip_labels(calls):
    return [label for label in labels(calls) if label.startswith("train-flip-")]


def step_text(calls, label):
    """A step's own text, without the shared rules that follow it."""
    return prompt(calls, label).split("\nHard rules for this step")[0]


class TrainArgsTest(unittest.TestCase):
    """#822: train is opt-in, checked like the other boolean args, and kept in the relaunch only when true."""

    def test_train_must_be_a_boolean(self):
        for bad in ("yes", 1, None, []):
            with self.subTest(bad=bad):
                result, calls, _ = run(args=dict(ARGS, train=bad))
                self.assertEqual(result, {"stage": "args", "error": "train must be a boolean"})
                self.assertEqual(calls, [])

    def test_meta_and_the_args_comment_name_train(self):
        text = PROGRAM.read_text(encoding="utf-8")
        meta = text[:text.index("\n}\n")]
        self.assertIn("train?", meta)
        header = text[text.index("\n// Args:"):text.index("\nconst ID_RE")]
        self.assertIn("train (boolean, default false", header)

    def test_the_relaunch_keeps_train_only_when_true(self):
        result, _, _ = run(args=dict(ARGS, train=True), children={"1": ReviewSizingTest.STOP})
        self.assertIs(result["relaunch"]["train"], True)
        for args in (ARGS, dict(ARGS, train=False)):
            with self.subTest(args=args):
                result, _, _ = run(args=args, children={"1": ReviewSizingTest.STOP})
                self.assertNotIn("train", result["relaunch"])

    def test_train_never_reaches_a_child(self):
        _, calls, _ = train_run()
        for c in calls:
            if c["kind"] == "workflow":
                self.assertNotIn("train", c["args"])

    def test_without_train_two_ready_issues_emit_no_train_label_and_the_same_calls(self):
        base = run(args=dict(ARGS, issues=[1, 2]), patch=BEHIND)[1]
        _, calls, _ = run(args=dict(ARGS, issues=[1, 2], train=False), patch=BEHIND)
        for found in (base, calls):
            self.assertEqual([l for l in labels(found) if l.startswith("train-")], [])
        self.assertEqual([(c["label"], c.get("prompt")) for c in calls], [(c["label"], c.get("prompt")) for c in base])
        self.assertIn("land-pr-2", labels(base))


class TrainTest(unittest.TestCase):
    """#822: up to three ready issues land through one car merge under one land lock; any surprise falls back to land()."""

    def test_two_ready_issues_land_through_one_car_merge(self):
        result, calls, _ = train_run()
        self.assertEqual(land_labels(calls), [
            "train-sweep-1", "land-pr-1", "train-pr-2", "train-build-1", "train-checks-1-1", "train-checks-1-2",
            "train-ready-1", "train-merge-1", "close-out-1", "train-sweep-2", "close-out-2"])
        merge = prompt(calls, "train-merge-1")
        self.assertIn(f"gh pr merge 92 --repo owner/repo --merge --match-head-commit {X2} --delete-branch", merge)
        self.assertEqual(len(re.findall(r"gh pr merge \d+ ", merge)), 1)
        self.assertIn(f"forge-claim land acquire --repo owner/repo --branch dev --sha {SHA}\n", merge)
        self.assertEqual(lock_releases(calls), ["close-out-1"])
        self.assertIn(LAND_RELEASE + SHA, prompt(calls, "close-out-1"))
        self.assertNotIn("forge-claim land release", prompt(calls, "close-out-2"))
        self.assertEqual(len([c for c in calls if "forge-claim land release" in c.get("prompt", "")]), 1)
        self.assertEqual(row(result, 1), {"issue": 1, "outcome": "landed", "pr": 41, "train": 1, "car_pr": 92})
        self.assertEqual(row(result, 2), {"issue": 2, "outcome": "landed", "pr": 42, "train": 1, "car_pr": 92})
        self.assertIsNone(result["relaunch"])

    def test_the_train_steps_carry_the_guard_forms(self):
        _, calls, _ = train_run()
        build = prompt(calls, "train-build-1")
        self.assertEqual(members_of(calls, "train-build-1"), [
            {"issue": 1, "head": SHA, "car": "land-train/b1-1-1"}, {"issue": 2, "head": SHA, "car": "land-train/b1-1-2"}])
        for needle in ("push -u origin <car>", "one branch per call",
                       "gh pr create --repo owner/repo --base dev --head <car>",
                       "from the repository checkout /r", "never from another directory", "never chained after cd",
                       "merge --no-ff", "merge --abort", "Never write to a member's own branch"):
            with self.subTest(needle=needle):
                self.assertIn(needle, build)
        merge = prompt(calls, "train-merge-1")
        for needle in ("from the repository checkout /r", "never from another directory", "never chained after cd",
                       "do not wait for it", "never read or return its merge commit"):
            with self.subTest(needle=needle):
                self.assertIn(needle, merge)
        for step in ("train-merge-1", "train-checks-1-1", "train-ready-1", "train-build-1", "train-sweep-2", "train-pr-2"):
            with self.subTest(step=step):
                own = step_text(calls, step)
                self.assertNotIn("sleep", own)
                self.assertNotIn("exception", own)
        self.assertNotIn("mergeCommit", merge)
        self.assertNotIn("merge_commit", json.dumps(schema_of(calls, "train-merge-1")))
        sweep = prompt(calls, "train-sweep-2")
        self.assertIn("git -C /r push origin --delete refs/heads/<branch>", sweep)
        self.assertIn("land-train/b1-", sweep)
        for branch in ("issue-1-x", "issue-2-x"):
            self.assertIn(branch, sweep)
        self.assertNotIn("issue-1-x", prompt(calls, "train-sweep-1"))
        checks = prompt(calls, "train-checks-1-2")
        self.assertIn(f"at the car head {X2}", checks)
        self.assertIn("25 minutes", checks)
        self.assertNotIn("60 minutes", checks)
        for label in ("train-checks-1-1", "train-checks-1-2"):
            own = step_text(calls, label)
            # Read-only and side by side: gh alone, no fetch and no git in the shared checkout; a failed read is pending, never failed.
            self.assertNotIn("fetch origin", own)
            self.assertNotIn("git -C", own)
            self.assertNotIn("merge-base", own)
            self.assertIn("Run no git command in this step", own)
            self.assertIn("when it fails again answer state pending", own)
        self.assertEqual(sum("fetch origin" in step_text(calls, l) for l in labels(calls) if l.startswith("train-") and "sweep" not in l), 1)

    def test_the_build_step_builds_each_car_on_the_one_before_it(self):
        _, calls, _ = train_run(children={"1": ready(1), "2": ready(2, head=B)})
        self.assertEqual([(m["issue"], m["head"]) for m in members_of(calls, "train-build-1")], [(1, SHA), (2, B)])
        build = step_text(calls, "train-build-1")
        steps = ["git -C /r fetch origin, once",
                 "git -C /r worktree add -B <the first car> <that path> origin/dev",
                 "never at origin/dev again: git -C <the scratch worktree> checkout -B <car>.",
                 "git -C <the scratch worktree> merge --no-ff -m 'Land train car <i>' <head>.",
                 "git -C <the scratch worktree> merge --abort and stop there",
                 "git -C <the scratch worktree> push -u origin <car>.",
                 "gh pr create --repo owner/repo --base dev --head <car>",
                 "git -C <the scratch worktree> checkout --detach"]
        found = [build.find(step) for step in steps]
        self.assertNotIn(-1, found)
        self.assertEqual(found, sorted(found))
        # Only the first car starts at the integration tip, and no merge can fast-forward.
        self.assertEqual((build.count("worktree add -B"), build.count("checkout -B"), build.count(" -B ")), (1, 1, 2))
        self.assertIsNone(re.search(r"checkout -B <car>\s+\S*origin", build))
        self.assertEqual(build.count(" merge --no-ff "), 1)
        self.assertNotIn("merge --ff", build)
        # The scratch worktree leaves the last car before the merge step deletes that car's branch.
        order = labels(calls)
        self.assertLess(order.index("train-build-1"), order.index("train-merge-1"))
        self.assertIn("--delete-branch", step_text(calls, "train-merge-1"))
        self.assertNotIn("worktree", step_text(calls, "train-merge-1"))

    def test_the_sweep_deletes_the_local_car_branch_before_the_remote_one(self):
        _, calls, _ = train_run()
        for label in ("train-sweep-1", "train-sweep-2"):
            with self.subTest(label=label):
                sweep = step_text(calls, label)
                steps = ["gh pr close <number> --repo owner/repo", "git -C /r worktree remove --force <path>",
                         "git -C /r branch -d <branch>", "git -C /r push origin --delete refs/heads/<branch>"]
                found = [sweep.find(step) for step in steps]
                self.assertNotIn(-1, found)
                self.assertEqual(found, sorted(found))
                self.assertNotIn("branch -D <", sweep)

    def test_the_train_renews_every_member_claim_before_the_merge(self):
        _, calls, _ = train_run()
        self.assertIn(f"forge-claim renew --repo owner/repo --issue 2 --holder {HOLDER} --branch issue-2-x", prompt(calls, "train-pr-2"))
        ready_step = prompt(calls, "train-ready-1")
        self.assertIn(f"forge-claim renew --repo owner/repo --issue <issue> --holder {HOLDER} --branch <branch>", ready_step)
        self.assertEqual(members_of(calls, "train-ready-1"), [
            {"issue": 1, "branch": "issue-1-x", "pr": 41, "head": SHA}, {"issue": 2, "branch": "issue-2-x", "pr": 42, "head": SHA}])

    def test_the_train_pr_step_opens_the_pr_as_land_pr_does_without_lock_or_checks(self):
        _, calls, _ = train_run()
        land_pr, train_pr = prompt(calls, "land-pr-1"), prompt(calls, "train-pr-2")
        start, end = "Then open the pull request of issue", "Return pr (number) and head (the full sha of the pushed head)."
        section = land_pr[land_pr.index(start):land_pr.index(end) + len(end)]
        self.assertIn(section.replace("#1", "#2").replace("issue-1-x", "issue-2-x"), train_pr)
        self.assertNotIn("forge-claim land", train_pr)
        self.assertNotIn("gh pr checks", train_pr)

    def test_the_car_title_and_body_carry_no_issue_reference(self):
        _, calls, _ = train_run()
        build = prompt(calls, "train-build-1")
        title = re.search(r"--title '([^']*)'", build).group(1)
        body = re.search(r"--body '([^']*)'", build).group(1)
        for text in (title, body):
            with self.subTest(text=text):
                self.assertNotIn("#", text)
                self.assertNotIn("issue", text.lower())
                self.assertIsNone(re.search(r"\b(Closes|Fixes|Resolves|Refs)\b", text))
                for char in FORBIDDEN:
                    self.assertNotIn(char, text)
        self.assertIn("no issue number", build)

    def test_a_single_ready_issue_runs_no_train_step(self):
        result, calls, _ = run(args=dict(ARGS, train=True), patch=BEHIND)
        self.assertEqual(train_labels(calls), [])
        # The one train label is the drain-start sweep of cars a dead earlier run may have left open.
        self.assertEqual([l for l in labels(calls) if l.startswith("train-")], ["train-sweep-1"])
        self.assertEqual(land_labels(calls)[1:], ["land-pr-1", "land-sync-1-1", "land-checks-1-2", "land-merge-1", "close-out-1"])
        self.assertEqual(row(result, 1), {"issue": 1, "outcome": "landed", "pr": 41})

    def test_a_first_landing_that_is_not_behind_lands_the_whole_drain_serially(self):
        result, calls, _ = train_run(patch={"land-pr-1": {}})
        self.assertEqual(train_labels(calls), [])
        self.assertEqual(land_labels(calls), ["train-sweep-1", "land-pr-1", "land-merge-1", "close-out-1",
                                              "land-pr-2", "land-merge-2", "close-out-2"])
        self.assertEqual([row(result, n)["outcome"] for n in (1, 2)], ["landed", "landed"])

    def test_a_merge_strategy_other_than_merge_never_trains(self):
        result, calls, _ = train_run(patch={"setup": {"max_parallel": 2, "merge_strategy": "squash"}})
        self.assertEqual(train_labels(calls), [])
        self.assertEqual([row(result, n)["outcome"] for n in (1, 2)], ["landed", "landed"])

    def test_a_red_car_two_among_three_merges_car_one_and_lands_the_rest_serially(self):
        result, calls, _ = train_run(issues=(1, 2, 3), replies={"train-checks-1-2": {"state": "failed", "head": X2, "failing": ["ci"]}},
                                     patch={"land-pr-2": {"checks": {"state": "behind", "head": SHA}}})
        order = land_labels(calls)
        self.assertEqual(order[:order.index("train-merge-1")], [
            "train-sweep-1", "land-pr-1", "train-pr-2", "train-pr-3", "train-build-1",
            "train-checks-1-1", "train-checks-1-2", "train-checks-1-3", "train-ready-1"])
        self.assertIn(f"gh pr merge 91 --repo owner/repo --merge --match-head-commit {X1} --delete-branch", prompt(calls, "train-merge-1"))
        self.assertEqual(order[order.index("train-merge-1") + 1:], [
            "close-out-1", "train-sweep-2", "land-pr-2", "land-sync-2-1", "land-checks-2-2", "land-merge-2", "close-out-2",
            "land-pr-3", "land-merge-3", "close-out-3"])
        self.assertEqual([m["issue"] for m in members_of(calls, "train-ready-1")], [1])
        self.assertEqual(row(result, 1), {"issue": 1, "outcome": "landed", "pr": 41, "train": 1, "car_pr": 91})
        self.assertEqual(row(result, 2), {"issue": 2, "outcome": "landed", "pr": 42})
        self.assertEqual(row(result, 3), {"issue": 3, "outcome": "landed", "pr": 43})
        self.assertEqual(lock_releases(calls), ["close-out-1"])

    def test_a_pending_or_wrong_head_or_undeclared_car_is_not_green(self):
        declared = {"setup": {"max_parallel": 2, "required_checks": ["gate"]}}
        for name, reply, patch in (
                ("pending", {"state": "pending", "head": X2, "pending": ["e2e"]}, None),
                ("head", {"state": "passed", "head": X1, "required": ["ci"], "passed": ["ci"]}, None),
                ("failing list", {"state": "passed", "head": X2, "passed": ["ci"], "failing": ["lint"]}, None),
                ("dead", None, None),
                ("declared", {"state": "passed", "head": X2, "required": ["ci"], "passed": ["ci"]}, declared)):
            with self.subTest(name=name):
                replies = {"train-checks-1-2": reply}
                if name == "pending":
                    replies["train-checks-1-2-more"] = reply
                if patch:
                    replies["train-checks-1-1"] = {"state": "passed", "head": X1, "required": ["gate"], "passed": ["gate"]}
                result, calls, _ = train_run(replies=replies, patch=patch)
                self.assertIn("gh pr merge 91 ", prompt(calls, "train-merge-1"))
                self.assertNotIn("train", row(result, 2))

    def test_a_build_conflict_at_car_two_trains_only_car_one(self):
        result, calls, _ = train_run(replies={"train-build-1": {"status": "blocked", "conflicted": True, "notes": "conflict",
                                                                 "cars": [{"issue": 1, "head": X1, "pr": 91}]}})
        self.assertNotIn("train-checks-1-2", labels(calls))
        self.assertIn(f"--match-head-commit {X1}", prompt(calls, "train-merge-1"))
        order = land_labels(calls)
        self.assertEqual(order[order.index("train-merge-1") + 1:], ["close-out-1", "train-sweep-2", "land-pr-2", "land-merge-2", "close-out-2"])
        self.assertEqual(row(result, 1)["car_pr"], 91)
        self.assertEqual(row(result, 2), {"issue": 2, "outcome": "landed", "pr": 42})
        self.assertEqual(lock_releases(calls), ["close-out-1"])

    def test_no_green_car_sweeps_and_the_first_issue_goes_on_inside_its_landing_with_the_lock_held_once(self):
        for name, replies in (
                ("conflict at car one", {"train-build-1": {"status": "blocked", "conflicted": True, "cars": []}}),
                ("car one red", {"train-checks-1-1": {"state": "failed", "head": X1, "failing": ["ci"]}}),
                ("build died", {"train-build-1": None}),
                ("build threw", {"train-build-1": "throw"}),
                ("cars misnamed", {"train-build-1": {"status": "done", "cars": [{"issue": 2, "head": X1, "pr": 91}]}}),
                ("short car sha", {"train-build-1": {"status": "done", "cars": [{"issue": 1, "head": "abc1234", "pr": 91}]}}),
                ("ready died", {"train-ready-1": None})):
            with self.subTest(name=name):
                result, calls, _ = train_run(replies=replies)
                order = land_labels(calls)
                self.assertNotIn("train-merge-1", order)
                self.assertEqual("train-checks-1-1" in order, name in ("car one red", "ready died"))
                self.assertEqual(order.count("land-pr-1"), 1)
                tail = ["train-sweep-2", "land-sync-1-1", "land-checks-1-2", "land-merge-1", "close-out-1",
                        "land-pr-2", "land-merge-2", "close-out-2"]
                self.assertEqual(order[-len(tail):], tail)
                self.assertEqual(lock_releases(calls), ["close-out-1"])
                self.assertEqual(row(result, 1), {"issue": 1, "outcome": "landed", "pr": 41})
                self.assertEqual(row(result, 2), {"issue": 2, "outcome": "landed", "pr": 42})

    def test_a_train_pr_that_fails_shrinks_the_train_before_any_car(self):
        lost = {"renew": {"verdict": "not_held", "by": "h2/b9"}}
        for name, reply, expected in (
                ("claim lost", lost, {"issue": 2, "outcome": "claim-lost", "by": "h2/b9", "reason": "claimed by h2/b9"}),
                ("head moved", {"pr": 42, "head": B}, {"issue": 2, "outcome": "stopped", "pr": 42, "stage": "head-moved", "expected": SHA, "head": B, "reason": f"head-moved: expected {SHA}, head {B}"}),
                ("dead", None, {"issue": 2, "outcome": "stopped", "stage": "pr", "reason": "pr: train-pr-2 returned nothing"})):
            with self.subTest(name=name):
                result, calls, _ = train_run(replies={"train-pr-2": reply})
                self.assertNotIn("train-build-1", labels(calls))
                self.assertNotIn("land-pr-2", labels(calls))
                self.assertEqual(row(result, 2), expected)
                self.assertEqual(row(result, 1), {"issue": 1, "outcome": "landed", "pr": 41})
                self.assertEqual(lock_releases(calls), ["close-out-1"])

    def test_a_failed_train_pr_among_three_keeps_the_issues_before_it_and_lands_those_after_it_serially(self):
        result, calls, _ = train_run(issues=(1, 2, 3), replies={"train-pr-3": {"renew": {"verdict": "not_held", "by": "h2/b9"}}})
        self.assertEqual([m["issue"] for m in members_of(calls, "train-build-1")], [1, 2])
        self.assertEqual(row(result, 3)["outcome"], "claim-lost")
        result, calls, _ = train_run(issues=(1, 2, 3), replies={"train-pr-2": {"renew": {"verdict": "not_held", "by": "h2/b9"}}})
        self.assertNotIn("train-build-1", labels(calls))
        self.assertEqual(row(result, 2)["outcome"], "claim-lost")
        self.assertEqual(row(result, 3), {"issue": 3, "outcome": "landed", "pr": 43})
        self.assertIn("land-pr-3", labels(calls))

    def test_a_claim_lost_at_the_merge_shrinks_the_train_to_the_issues_before_it(self):
        ready_reply = {"members": [{"issue": 1, "renew": {"verdict": "renewed"}, "head": SHA, "state": "OPEN"},
                                   {"issue": 2, "renew": {"verdict": "not_held", "by": "h2/b9"}, "head": SHA, "state": "OPEN"}]}
        result, calls, _ = train_run(replies={"train-ready-1": ready_reply})
        self.assertIn(f"gh pr merge 91 --repo owner/repo --merge --match-head-commit {X1}", prompt(calls, "train-merge-1"))
        self.assertEqual(row(result, 2), {"issue": 2, "outcome": "claim-lost", "pr": 42, "by": "h2/b9", "reason": "claimed by h2/b9"})
        self.assertEqual(row(result, 1), {"issue": 1, "outcome": "landed", "pr": 41, "train": 1, "car_pr": 91})
        for label in ("close-out-2", "land-pr-2"):
            self.assertNotIn(label, labels(calls))
        self.assertEqual(lock_releases(calls), ["close-out-1"])
        self.assertEqual(result["relaunch"]["issues"], [2])

    def test_a_head_that_moved_before_the_merge_shrinks_the_train(self):
        ready_reply = {"members": [{"issue": 1, "renew": {"verdict": "renewed"}, "head": SHA, "state": "OPEN"},
                                   {"issue": 2, "renew": {"verdict": "renewed"}, "head": B, "state": "OPEN"}]}
        result, calls, _ = train_run(replies={"train-ready-1": ready_reply})
        self.assertIn("gh pr merge 91 ", prompt(calls, "train-merge-1"))
        self.assertEqual(without(row(result, 2), "reason"), {"issue": 2, "outcome": "stopped", "pr": 42, "stage": "head-moved", "expected": SHA, "head": B})
        self.assertNotIn("close-out-2", labels(calls))
        self.assertEqual(lock_releases(calls), ["close-out-1"])

    def test_the_first_issue_failing_the_ready_step_ends_the_train_without_a_merge(self):
        for name, member, expected in (
                ("claim lost", {"issue": 1, "renew": {"verdict": "not_held", "by": "h2/b9"}, "head": SHA, "state": "OPEN"},
                 {"issue": 1, "outcome": "claim-lost", "pr": 41, "by": "h2/b9", "reason": "claimed by h2/b9"}),
                ("head moved", {"issue": 1, "renew": {"verdict": "renewed"}, "head": B, "state": "OPEN"},
                 {"issue": 1, "outcome": "stopped", "pr": 41, "stage": "head-moved", "expected": SHA, "head": B, "reason": f"head-moved: expected {SHA}, head {B}"}),
                ("renew error", {"issue": 1, "renew": {"verdict": "error", "detail": "boom"}, "head": SHA, "state": "OPEN"},
                 {"issue": 1, "outcome": "stopped", "pr": 41, "stage": "renew", "reason": "renew: boom"}),
                ("closed", {"issue": 1, "renew": {"verdict": "renewed"}, "head": SHA, "state": "CLOSED"},
                 {"issue": 1, "outcome": "stopped", "pr": 41, "stage": "train-ready", "reason": "train-ready: PR #41 reads CLOSED"})):
            with self.subTest(name=name):
                second = {"issue": 2, "renew": {"verdict": "renewed"}, "head": SHA, "state": "OPEN"}
                result, calls, _ = train_run(replies={"train-ready-1": {"members": [member, second]}})
                order = land_labels(calls)
                self.assertNotIn("train-merge-1", order)
                self.assertEqual(row(result, 1), expected)
                self.assertEqual(lock_releases(calls), ["land-unlock-1"])
                self.assertEqual(order[order.index("land-unlock-1"):], ["land-unlock-1", "train-sweep-2", "land-pr-2", "land-merge-2", "close-out-2"])
                self.assertEqual(row(result, 2), {"issue": 2, "outcome": "landed", "pr": 42})

    def test_a_transient_renew_recalls_the_ready_step_once(self):
        transient = {"members": [{"issue": 1, "renew": TRANSIENT, "head": SHA, "state": "OPEN"},
                                 {"issue": 2, "renew": {"verdict": "renewed"}, "head": SHA, "state": "OPEN"}]}
        fine = {"members": [{"issue": n, "renew": {"verdict": "renewed"}, "head": SHA, "state": "OPEN"} for n in (1, 2)]}
        result, calls, _ = train_run(replies={"train-ready-1": [transient, fine]})
        self.assertEqual(labels(calls).count("train-ready-1"), 2)
        self.assertEqual([row(result, n)["outcome"] for n in (1, 2)], ["landed", "landed"])

    def test_a_car_pending_with_no_failed_check_at_the_cap_gets_one_further_wait(self):
        late = {"state": "pending", "head": X1, "passed": ["ci"], "pending": ["e2e"]}
        result, calls, _ = train_run(replies={"train-checks-1-1": late})
        order = land_labels(calls)
        # Only the late car is waited for again; the green car keeps its answer.
        self.assertEqual(order[order.index("train-build-1") + 1:order.index("train-merge-1")],
                         ["train-checks-1-1", "train-checks-1-2", "train-checks-1-1-more", "train-ready-1"])
        first, more = step_text(calls, "train-checks-1-1"), step_text(calls, "train-checks-1-1-more")
        self.assertIn("6 minutes at most and stop waiting 6 minutes after this step began", more)
        self.assertEqual(more, first.replace("25 minutes", "6 minutes"))
        self.assertIn("gh pr merge 92 ", prompt(calls, "train-merge-1"))
        for n, pr in ((1, 41), (2, 42)):
            self.assertEqual(row(result, n), {"issue": n, "outcome": "landed", "pr": pr, "train": 1, "car_pr": 92})

    def test_every_late_car_shares_the_one_further_wait(self):
        late = {f"train-checks-1-{i}": {"state": "pending", "head": head, "pending": ["e2e"]} for i, head in ((1, X1), (2, X2))}
        result, calls, _ = train_run(replies=late)
        self.assertEqual([l for l in labels(calls) if l.startswith("train-checks-")],
                         ["train-checks-1-1", "train-checks-1-2", "train-checks-1-1-more", "train-checks-1-2-more"])
        self.assertEqual([row(result, n).get("car_pr") for n in (1, 2)], [92, 92])

    def test_a_car_still_pending_after_the_further_wait_falls_back_as_a_late_car_did(self):
        late = {"state": "pending", "head": X1, "pending": ["e2e"]}
        result, calls, _ = train_run(replies={"train-checks-1-1": late, "train-checks-1-1-more": late})
        order = land_labels(calls)
        self.assertEqual([l for l in order if l.startswith("train-checks-")], ["train-checks-1-1", "train-checks-1-2", "train-checks-1-1-more"])
        self.assertNotIn("train-merge-1", order)
        tail = ["train-checks-1-1-more", "train-sweep-2", "land-sync-1-1", "land-checks-1-2", "land-merge-1", "close-out-1",
                "land-pr-2", "land-merge-2", "close-out-2"]
        self.assertEqual(order[-len(tail):], tail)
        self.assertEqual(lock_releases(calls), ["close-out-1"])
        self.assertEqual(row(result, 1), {"issue": 1, "outcome": "landed", "pr": 41})
        self.assertEqual(row(result, 2), {"issue": 2, "outcome": "landed", "pr": 42})

    def test_a_failed_check_at_the_cap_gets_no_further_wait(self):
        for name, reply in (
                ("failed", {"state": "failed", "head": X1, "failing": ["ci"], "pending": ["e2e"]}),
                ("pending with a failed check", {"state": "pending", "head": X1, "failing": ["ci"], "pending": ["e2e"]}),
                ("pending at another head", {"state": "pending", "head": X2, "pending": ["e2e"]}),
                ("dead", None)):
            with self.subTest(name=name):
                result, calls, _ = train_run(replies={"train-checks-1-1": reply})
                order = land_labels(calls)
                self.assertEqual([l for l in order if l.startswith("train-checks-")], ["train-checks-1-1", "train-checks-1-2"])
                self.assertNotIn("train-merge-1", order)
                self.assertEqual([row(result, n) for n in (1, 2)], [{"issue": n, "outcome": "landed", "pr": 40 + n} for n in (1, 2)])
        # A late car behind a red one is not waited for: it could not join the green prefix.
        _, calls, _ = train_run(issues=(1, 2, 3), replies={"train-checks-1-2": {"state": "failed", "head": X2, "failing": ["ci"]},
                                                           "train-checks-1-3": {"state": "pending", "head": X3, "pending": ["e2e"]}})
        self.assertEqual([l for l in labels(calls) if l.endswith("-more")], [])

    def test_a_train_merge_refused_as_behind_sweeps_and_lands_its_members_serially(self):
        c = "c" * 40
        refused = dict(merge_reply({}, merged=False), behind=True, notes="the head branch is not up to date with the base branch")
        result, calls, _ = train_run(replies={"train-merge-1": refused, **OPEN_CAR,
                                              "land-sync-1-1": {"status": "done", "conflicted": False, "head": c, "notes": "ok"}})
        order = land_labels(calls)
        # One read of the forge confirms the car is still open before anything lands serially.
        self.assertIn("gh pr view 92 --repo owner/repo --json state and return its state as car", step_text(calls, "train-flip-1-1"))
        self.assertEqual(order[order.index("train-merge-1") + 1:], [
            "train-flip-1-1", "train-sweep-2", "land-sync-1-1", "land-record-1-1", "land-merge-1", "close-out-1", "land-pr-2", "land-merge-2", "close-out-2"])
        # The first landing kept the lock at its ready head through the train, moves it to the resynced head and releases it there, once.
        self.assertIn(f"forge-claim land acquire --repo owner/repo --branch dev --sha {c}\n", prompt(calls, "land-record-1-1"))
        self.assertIn(f"--match-head-commit {c}", prompt(calls, "land-merge-1"))
        self.assertEqual(lock_releases(calls), ["close-out-1"])
        self.assertIn(LAND_RELEASE + c, prompt(calls, "close-out-1"))
        self.assertNotIn("land-unlock-1", order)
        self.assertEqual(row(result, 1), {"issue": 1, "outcome": "landed", "pr": 41})
        self.assertEqual(row(result, 2), {"issue": 2, "outcome": "landed", "pr": 42})
        self.assertIsNone(result["relaunch"])

    def test_the_train_merge_asks_for_behind_in_the_serial_merge_words(self):
        _, calls, _ = train_run(issues=(1, 2, 3), replies={"train-checks-1-2": {"state": "failed", "head": X2, "failing": ["ci"]}})
        sentence = ("Never retry with another form; on a guard refusal or a head mismatch return merged false with the exact message in notes, "
                    "and behind true only when the refusal says the head branch is not up to date with the base branch, "
                    "or the guard says the PR is behind its base, else false.")
        for label in ("train-merge-1", "land-merge-2"):
            self.assertEqual(step_text(calls, label).count(sentence), 1)
            self.assertEqual(schema_of(calls, label)["properties"]["behind"], {"type": "boolean"})
        self.assertEqual(PROGRAM.read_text().count(sentence), 1)

    def test_a_behind_refusal_whose_car_reads_merged_is_closed_out(self):
        refused = dict(merge_reply({}, merged=False), behind=True)
        result, calls, _ = train_run(replies={"train-merge-1": refused})
        order = land_labels(calls)
        self.assertEqual(order[order.index("train-merge-1") + 1:], ["train-flip-1-1", "close-out-1", "train-sweep-2", "close-out-2"])
        for n, pr in ((1, 41), (2, 42)):
            self.assertEqual(row(result, n), {"issue": n, "outcome": "landed", "pr": pr, "train": 1, "car_pr": 92})
        self.assertEqual(lock_releases(calls), ["close-out-1"])

    def test_a_behind_refusal_whose_car_is_not_read_open_stops_every_member(self):
        refused = dict(merge_reply({}, merged=False), behind=True)
        for name, read in (("closed", {"car": "CLOSED", "prs": []}), ("dead", None), ("threw", "throw")):
            with self.subTest(name=name):
                result, calls, _ = train_run(replies={"train-merge-1": refused, "train-flip-1-1": read})
                order = land_labels(calls)
                self.assertEqual(order[order.index("train-merge-1") + 1:], ["train-flip-1-1", "land-unlock-1", "train-sweep-2"])
                for n, pr in ((1, 41), (2, 42)):
                    self.assertEqual(row(result, n), {"issue": n, "outcome": "stopped", "pr": pr, "stage": "train-merge", "reason": "train-merge: n"})

    def test_a_refused_train_merge_that_stays_behind_ends_in_the_serial_landings_own_rows(self):
        refused = dict(merge_reply({}, merged=False), behind=True)
        behind = {"state": "behind", "head": SHA}
        result, calls, _ = train_run(replies={"train-merge-1": refused, **OPEN_CAR, "land-checks-1-2": behind, "land-checks-1-3": behind})
        self.assertEqual(row(result, 1)["outcome"], "land-contended")
        self.assertEqual(lock_releases(calls), ["land-unlock-1"])
        self.assertEqual(row(result, 2), {"issue": 2, "outcome": "landed", "pr": 42})

    def test_a_lock_not_already_held_before_the_merge_sweeps_and_every_row_is_land_contended(self):
        # A behind answer changes nothing without the lock: it is read only under already_held (the car, read, would be open).
        for verdict, behind in itertools.product(("lost_to", "held_by", "acquired", "moved", "land-contended", "error"), (False, True)):
            with self.subTest(verdict=verdict, behind=behind):
                reply = dict(merge_reply({}, lock=verdict, merged=False), behind=behind)
                result, calls, _ = train_run(replies={"train-merge-1": reply, **OPEN_CAR})
                order = land_labels(calls)
                self.assertEqual(order[order.index("train-merge-1") + 1:], ["land-unlock-1", "train-sweep-2"])
                for n, pr in ((1, 41), (2, 42)):
                    self.assertEqual(row(result, n), {"issue": n, "outcome": "land-contended", "pr": pr,
                                                      "reason": f"the land lock was not held before the train merge ({verdict})"})
                self.assertEqual(lock_releases(calls), ["land-unlock-1"])
                self.assertEqual(result["relaunch"]["issues"], [1, 2])
                self.assertNotIn("pr", result["relaunch"]["conts"]["1"])

    def test_a_car_that_did_not_merge_stops_every_member_and_sweeps(self):
        open_car = {"train-flip-1-1": {"car": "OPEN", "prs": []}}
        for name, replies, detail, flipped in (
                ("unmerged", {"train-merge-1": merge_reply({}, merged=False)}, "n", []),
                ("refused, not behind", {"train-merge-1": dict(merge_reply({}, merged=False), behind=False)}, "n", []),
                ("dead", {"train-merge-1": None, **open_car}, "train-merge-1 returned nothing", ["train-flip-1-1"]),
                ("threw", {"train-merge-1": "throw", **open_car}, "stub agent train-merge-1 threw", ["train-flip-1-1"]),
                ("no verdict", {"train-merge-1": {"lock": None, "merged": False}, **open_car}, "train-merge-1 returned no lock verdict", ["train-flip-1-1"]),
                ("no verdict, behind", {"train-merge-1": {"lock": None, "merged": False, "behind": True}, **open_car},
                 "train-merge-1 returned no lock verdict", ["train-flip-1-1"]),
                ("dead and unread", {"train-merge-1": None, "train-flip-1-1": None}, "train-merge-1 returned nothing", ["train-flip-1-1"]),
                ("dead and the read threw", {"train-merge-1": None, "train-flip-1-1": "throw"}, "train-merge-1 returned nothing", ["train-flip-1-1"])):
            with self.subTest(name=name):
                result, calls, _ = train_run(replies=replies)
                order = land_labels(calls)
                self.assertEqual(order[order.index("train-merge-1") + 1:], flipped + ["land-unlock-1", "train-sweep-2"])
                for n, pr in ((1, 41), (2, 42)):
                    self.assertEqual(row(result, n), {"issue": n, "outcome": "stopped", "pr": pr, "stage": "train-merge", "reason": f"train-merge: {detail}"})
                self.assertEqual(lock_releases(calls), ["land-unlock-1"])
                self.assertNotIn("pr", result["relaunch"]["conts"]["1"])

    def test_a_lost_merge_reply_reads_the_forge_once_and_closes_out_a_merged_car(self):
        for name, reply in (("dead", None), ("threw", "throw"), ("no verdict", {"lock": None, "merged": False})):
            with self.subTest(name=name):
                result, calls, _ = train_run(replies={"train-merge-1": reply})
                self.assertEqual(flip_labels(calls), ["train-flip-1-1"])
                flip = step_text(calls, "train-flip-1-1")
                self.assertIn("gh pr view 92 --repo owner/repo --json state and return its state as car", flip)
                self.assertIn("The pull requests to read, as JSON: [41,42]", flip)
                order = land_labels(calls)
                self.assertEqual(order[order.index("train-flip-1-1") + 1:], ["close-out-1", "train-sweep-2", "close-out-2"])
                for n, pr in ((1, 41), (2, 42)):
                    self.assertEqual(row(result, n), {"issue": n, "outcome": "landed", "pr": pr, "train": 1, "car_pr": 92})
                self.assertEqual(lock_releases(calls), ["close-out-1"])

    def test_a_flip_step_reads_states_and_changes_nothing(self):
        _, calls, _ = train_run(replies={"train-merge-1": merge_reply({41: "MERGED", 42: "OPEN"})})
        flip = step_text(calls, "train-flip-1-1")
        self.assertIn("The pull requests to read, as JSON: [42]", flip)
        for needle in ("change nothing", "do not wait and do not read twice", "Never merge, close or edit any pull request",
                       "never read or return its merge commit"):
            with self.subTest(needle=needle):
                self.assertIn(needle, flip)
        for banned in ("gh pr merge", "forge-claim", "git -C", "mergeCommit"):
            with self.subTest(banned=banned):
                self.assertNotIn(banned, flip)

    def test_a_member_the_merge_step_read_open_is_read_again_until_it_flips(self):
        late = {"train-merge-1": merge_reply({41: "MERGED", 42: "OPEN"}),
                "train-flip-1-1": {"car": "MERGED", "prs": [{"pr": 42, "state": "OPEN"}]},
                "train-flip-1-2": None,
                # A read that names a PR it was not asked for never unmerges that PR.
                "train-flip-1-3": {"car": "MERGED", "prs": [{"pr": 42, "state": "MERGED"}, {"pr": 41, "state": "OPEN"}]}}
        result, calls, _ = train_run(replies=late)
        self.assertEqual(flip_labels(calls), ["train-flip-1-1", "train-flip-1-2", "train-flip-1-3"])
        for n, pr in ((1, 41), (2, 42)):
            self.assertEqual(row(result, n), {"issue": n, "outcome": "landed", "pr": pr, "train": 1, "car_pr": 92})
        result, calls, _ = train_run()
        self.assertEqual(flip_labels(calls), [])

    def test_a_member_pr_still_open_after_the_car_merge_is_stopped_without_a_close_out(self):
        result, calls, _ = train_run(replies={"train-merge-1": merge_reply({41: "MERGED", 42: "OPEN"}), **flips("OPEN", [42])})
        self.assertEqual(without(row(result, 2), "reason"), {"issue": 2, "outcome": "stopped", "pr": 42, "stage": "train-merged-open", "train": 1, "car_pr": 92})
        # The program, not a sleeping step, waits: one read-only flip step per round, up to the bound, each for the open PR alone.
        self.assertEqual(flip_labels(calls), [f"train-flip-1-{k}" for k in range(1, FLIP_CALLS + 1)])
        for label in flip_labels(calls):
            self.assertIn("The pull requests to read, as JSON: [42]", prompt(calls, label))
        self.assertNotIn("close-out-2", labels(calls))
        self.assertEqual(row(result, 1), {"issue": 1, "outcome": "landed", "pr": 41, "train": 1, "car_pr": 92})
        self.assertEqual(lock_releases(calls), ["close-out-1"])
        # The car is merged, so the relaunch keeps the member's PR in its cont; its remote branch is not deleted under an open PR.
        self.assertEqual(result["relaunch"]["conts"]["2"]["pr"], 42)
        sweep = prompt(calls, "train-sweep-2")
        self.assertIn("issue-1-x", sweep)
        self.assertNotIn("issue-2-x", sweep)

    def test_a_first_pr_still_open_after_the_car_merge_releases_the_lock_once_without_its_close_out(self):
        for name, states in (("open", {41: "OPEN", 42: "MERGED"}), ("unread", {42: "MERGED"})):
            with self.subTest(name=name):
                result, calls, _ = train_run(replies={"train-merge-1": merge_reply(states), **flips("OPEN", [41])})
                self.assertEqual(len(flip_labels(calls)), FLIP_CALLS)
                self.assertEqual(without(row(result, 1), "reason"), {"issue": 1, "outcome": "stopped", "pr": 41, "stage": "train-merged-open", "train": 1, "car_pr": 92})
                self.assertNotIn("close-out-1", labels(calls))
                self.assertEqual(lock_releases(calls), ["land-unlock-1"])
                self.assertEqual(row(result, 2), {"issue": 2, "outcome": "landed", "pr": 42, "train": 1, "car_pr": 92})
                self.assertNotIn("forge-claim land release", prompt(calls, "close-out-2"))
                self.assertEqual(result["relaunch"]["conts"]["1"]["pr"], 41)

    def test_the_sweep_runs_at_the_drain_start_and_after_a_thrown_step(self):
        _, calls, _ = train_run(replies={"train-build-1": "throw"})
        order = land_labels(calls)
        self.assertEqual(order[:3], ["train-sweep-1", "land-pr-1", "train-pr-2"])
        self.assertEqual(order[order.index("train-build-1") + 1], "train-sweep-2")
        self.assertLess(order.index("train-sweep-2"), order.index("land-sync-1-1"))

    def test_a_dead_or_thrown_sweep_never_stops_a_landing(self):
        for reply in (None, "throw"):
            with self.subTest(reply=reply):
                result, calls, _ = train_run(replies={"train-sweep-1": reply, "train-sweep-2": reply})
                self.assertEqual([row(result, n)["outcome"] for n in (1, 2)], ["landed", "landed"])
                self.assertEqual(lock_releases(calls), ["close-out-1"])
                self.assertEqual([l for l in labels(calls) if l.startswith("train-sweep-")], ["train-sweep-1", "train-sweep-2"])

    def test_a_clean_drain_start_sweep_is_not_repeated_and_a_failed_one_is(self):
        _, calls, _ = train_run(issues=(1, 2, 3, 4))
        self.assertEqual([l for l in labels(calls) if l.startswith("train-sweep-")], ["train-sweep-1", "train-sweep-2"])
        _, calls, _ = train_run(issues=(1, 2, 3, 4), replies={"train-sweep-2": {"ok": False, "detail": "a car is still open"}})
        self.assertEqual([l for l in labels(calls) if l.startswith("train-sweep-")], ["train-sweep-1", "train-sweep-2", "train-sweep-3"])

    def test_a_fourth_waiting_issue_lands_in_the_next_drain(self):
        result, calls, _ = train_run(issues=(1, 2, 3, 4))
        self.assertEqual([m["issue"] for m in members_of(calls, "train-build-1")], [1, 2, 3])
        self.assertEqual(labels(calls).count("train-build-1"), 1)
        self.assertNotIn("train-pr-4", labels(calls))
        order = land_labels(calls)
        self.assertLess(order.index("close-out-3"), order.index("land-pr-4"))
        self.assertIn(f"gh pr merge 93 --repo owner/repo --merge --match-head-commit {X3}", prompt(calls, "train-merge-1"))
        self.assertEqual([row(result, n)["outcome"] for n in (1, 2, 3, 4)], ["landed"] * 4)
        self.assertEqual(row(result, 4), {"issue": 4, "outcome": "landed", "pr": 44})

    def test_an_issue_with_an_unknown_criterion_kind_never_joins_a_train(self):
        odd = ready(2, acceptance=[{"id": "AC1", "text": "works", "kind": "vibes"}])
        result, calls, _ = train_run(children={"1": ready(1), "2": odd})
        self.assertEqual(train_labels(calls), [])
        self.assertEqual((row(result, 2)["outcome"], row(result, 2)["stage"]), ("stopped", "plan"))
        self.assertEqual(row(result, 1)["outcome"], "landed")

    def test_a_trained_issue_with_open_criteria_is_held_by_its_close_out(self):
        held = ready(2, acceptance=[{"id": "AC1", "text": "live", "kind": "evidence"}])
        result, calls, _ = train_run(children={"1": ready(1), "2": held}, replies={"close-out-2": {"issue_state": "OPEN", "released": True, "decision_ended": True}})
        self.assertEqual(row(result, 2), {"issue": 2, "outcome": "landed-held", "pr": 42, "train": 1, "car_pr": 92})
        self.assertIn("needs-verification", prompt(calls, "close-out-2"))

    def test_a_trained_close_out_that_stops_keeps_its_cont_with_the_pr(self):
        result, calls, _ = train_run(replies={"close-out-2": {"issue_state": "OPEN", "released": False, "decision_ended": True}})
        self.assertEqual((row(result, 2)["outcome"], row(result, 2)["stage"]), ("stopped", "close-out"))
        self.assertEqual(result["relaunch"]["conts"]["2"]["pr"], 42)
        self.assertIs(result["relaunch"]["train"], True)

    def test_the_remote_issue_branches_are_swept_only_when_the_contract_deletes_branches(self):
        _, calls, _ = train_run(patch={"setup": {"max_parallel": 2, "delete_branch": False}})
        self.assertNotIn("issue-1-x", prompt(calls, "train-sweep-2"))
        self.assertNotIn("--delete-branch", prompt(calls, "train-merge-1"))


class TrainRelaunchTest(unittest.TestCase):
    """#822, the failure table's last row: a run that stopped or died after the car merge is relaunched, and its issue PRs read MERGED."""

    DONE = [{"n": 1, "commit": "c1"}]

    @staticmethod
    def done_child(pr):
        return {"stage": "done", "pr": pr, "merged": True, "acceptance": [{"id": "AC1", "text": "works", "kind": "code"}],
                "close_out": {"issue_state": "CLOSED", "released": True}}

    def merged_facts(self, pr):
        # dev is not the default branch, so the merged PR only says Refs; it is the cont's own landing by its commit.
        return dict(HELD, merged_refs=[{"number": pr, "closes": False}], landed=[{"number": pr, "commits": ["c1"]}])

    def test_a_relaunch_after_the_car_merge_closes_the_issues_out_and_lands_nothing_again(self):
        children = {str(n): dict(ready(n), cont=dict(ready(n)["cont"], done=self.DONE)) for n in (1, 2)}
        # The merge reply and the one read after it are both lost: the run cannot know the car is merged.
        first, _, _ = train_run(children=children, replies={"train-merge-1": None, "train-flip-1-1": None})
        relaunch = first["relaunch"]
        self.assertEqual((relaunch["issues"], relaunch["train"]), ([1, 2], True))
        for n in ("1", "2"):
            self.assertNotIn("pr", relaunch["conts"][n])
        second, calls, _ = run(args=relaunch, patch={"facts-1": self.merged_facts(41), "facts-2": self.merged_facts(42)},
                               children={"1": self.done_child(41), "2": self.done_child(42)})
        self.assertEqual([l for l in labels(calls) if l.startswith(("land-", "train-", "close-out-"))], [])
        for c in calls:
            if c["kind"] == "agent":
                self.assertNotIn("gh pr merge 4", c["prompt"])
                self.assertNotIn("gh pr merge 9", c["prompt"])
        for n, pr in ((1, 41), (2, 42)):
            self.assertEqual(row(second, n), {"issue": n, "outcome": "landed", "pr": pr})
            self.assertEqual(child(calls, n)["args"]["mode"], "ready")
            self.assertEqual(child(calls, n)["args"]["cont"], relaunch["conts"][str(n)])
            self.assertEqual(len([c for c in calls if c["label"] == f"child-{n}"]), 1)
            self.assertIn(f"recover-end-{n}", labels(calls))
        self.assertIsNone(second["relaunch"])

    def test_a_relaunch_of_a_member_stopped_open_closes_it_out_once_the_forge_marks_it_merged(self):
        first, _, _ = train_run(replies={"train-merge-1": merge_reply({41: "MERGED", 42: "OPEN"}), **flips("OPEN", [42])})
        relaunch = first["relaunch"]
        self.assertEqual(relaunch["issues"], [2])
        self.assertEqual(relaunch["conts"]["2"]["pr"], 42)
        facts = dict(HELD, merged_refs=[{"number": 42, "closes": False}], landed=[{"number": 42, "commits": []}])
        second, calls, _ = run(args=relaunch, patch={"facts-2": facts}, children={"2": self.done_child(42)})
        self.assertEqual([l for l in labels(calls) if l.startswith(("land-", "train-", "close-out-"))], [])
        self.assertEqual(row(second, 2), {"issue": 2, "outcome": "landed", "pr": 42})
        self.assertIsNone(second["relaunch"])


# #936: land-pr-1 is held this many turns (its wait for the land lock), and a joining issue's child returns this many turns into it.
LOCK_WAIT = 60
DURING_WAIT = 40
AFTER_WAIT = 90
JOIN_LOG = "#1: #2 became ready while it waited for the land lock; they land with it as a train"
JOIN_LOG_23 = "#1: #2, #3 became ready while it waited for the land lock; they land with it as a train"


def join_run(issues=(1, 2), replies=None, patch=None, children=None, args=None, late=DURING_WAIT, delays=None):
    """A train-enabled batch whose issue 1 is ready first and lands alone, behind; the others become ready `late` turns later.

    An issue with a `children` entry answers ready from its plan-mode call, so that call is the one held."""
    issues = list(issues)
    merged = {"setup": {"max_parallel": len(issues)}, **BEHIND, **(patch or {})}
    return run_full(args={**ARGS, "issues": issues, "train": True, **(args or {})}, replies=replies, patch=merged, children=children,
                    turns={f"{n}:{'plan' if str(n) in (children or {}) else 'ready'}": late for n in issues[1:]},
                    delays={"land-pr-1": LOCK_WAIT, **(delays or {})})


def ready_during(out, n):
    """The landing step that was running when issue n's child returned ready: the last call started before that return."""
    at = [r["calls"] for r in out["child_returns"] if r["issue"] == n][-1]
    return out["calls"][at - 1]["label"]


def land_release_shas(calls):
    """Every land lock release any step of the run was told to run, by sha."""
    return [sha for c in calls if c["kind"] == "agent" for sha in re.findall(re.escape(LAND_RELEASE) + r"([0-9a-f]+)", c["prompt"])]


def join_logs(out):
    """The join lines the run logged: one per landing that took joiners, naming them."""
    return [line for line in out["logs"] if "became ready while it waited" in line]


def waited_acquires(calls):
    return [c["label"] for c in calls if c["kind"] == "agent" and re.search(r"forge-claim land acquire [^\n]* --wait\n", c["prompt"])]


def landing_of(calls, n):
    """Issue n's landing steps, label and prompt, in order."""
    return [(c["label"], c["prompt"]) for c in calls if c["label"].startswith(("land-", "close-out-")) and c["label"] in of(calls, n)]


class TrainJoinTest(unittest.TestCase):
    """#936: an issue that becomes ready while the batch's one landing still waits for the land lock lands with it as a train, under that hold."""

    def test_an_issue_ready_by_the_end_of_the_lock_wait_joins_the_landing_as_a_train(self):
        out = join_run()
        result, calls = out["result"], out["calls"]
        # The drain took issue 1 alone: issue 2 was not waiting when it started, and never gets a land-pr of its own.
        self.assertEqual(land_labels(calls), [
            "train-sweep-1", "land-pr-1", "train-pr-2", "train-build-1", "train-checks-1-1", "train-checks-1-2",
            "train-ready-1", "train-merge-1", "close-out-1", "train-sweep-2", "close-out-2"])
        self.assertEqual(ready_during(out, 2), "land-pr-1")
        self.assertEqual(join_logs(out), [JOIN_LOG])
        # One lock hold: taken once, waiting, by land-pr-1 at issue 1's ready head; re-checked there by the train merge; released there once.
        self.assertEqual(waited_acquires(calls), ["land-pr-1"])
        merge = prompt(calls, "train-merge-1")
        self.assertIn(f"forge-claim land acquire --repo owner/repo --branch dev --sha {SHA}\n", merge)
        self.assertIn(f"gh pr merge 92 --repo owner/repo --merge --match-head-commit {X2} --delete-branch", merge)
        self.assertNotIn("forge-claim land", prompt(calls, "train-pr-2"))
        self.assertEqual(lock_releases(calls), ["close-out-1"])
        self.assertEqual(land_release_shas(calls), [SHA])
        self.assertEqual(lock_releases(calls, 2), [])
        self.assertEqual(row(result, 1), {"issue": 1, "outcome": "landed", "pr": 41, "train": 1, "car_pr": 92})
        self.assertEqual(row(result, 2), {"issue": 2, "outcome": "landed", "pr": 42, "train": 1, "car_pr": 92})
        self.assertIsNone(result["relaunch"])

    def test_the_joined_train_is_the_train_of_two_issues_that_waited_together(self):
        together = train_run()[1]
        out = join_run()
        self.assertEqual(join_logs(out), [JOIN_LOG])
        joined = out["calls"]
        steps = lambda found: [(c["label"], c["prompt"]) for c in found if c["label"].startswith(("land-", "train-", "close-out-"))]
        self.assertEqual(steps(joined), steps(together))

    def test_a_lone_landing_with_nothing_ready_at_the_end_of_its_wait_adds_no_step(self):
        serial = run(args=dict(ARGS, train=False), patch=BEHIND)[1]
        lone = run_full(args=dict(ARGS, train=True), patch=BEHIND, delays={"land-pr-1": LOCK_WAIT})
        self.assertEqual([(c["label"], c.get("prompt")) for c in lone["calls"] if c["label"] != "train-sweep-1"],
                         [(c["label"], c.get("prompt")) for c in serial])
        self.assertEqual([line for line in lone["logs"] if "train" in line], [])
        # A second issue that is ready only after the wait ended changes nothing in the first landing either.
        out = join_run(late=AFTER_WAIT)
        self.assertEqual(landing_of(out["calls"], 1), landing_of(serial, 1))
        self.assertEqual(train_labels(out["calls"]), [])
        self.assertEqual(join_logs(out), [])
        self.assertNotEqual(ready_during(out, 2), "land-pr-1")

    def test_nothing_joins_once_the_sync_or_the_checks_started(self):
        lone = run(args=dict(ARGS, train=True), patch=BEHIND)[1]
        for step in ("land-sync-1-1", "land-checks-1-2", "land-merge-1"):
            with self.subTest(step=step):
                # Issue 2 becomes ready while `step` runs, after land-pr-1 returned.
                out = join_run(late=AFTER_WAIT, delays={step: LOCK_WAIT})
                result, calls = out["result"], out["calls"]
                self.assertEqual(ready_during(out, 2), step)
                self.assertEqual(train_labels(calls), [])
                self.assertEqual(landing_of(calls, 1), landing_of(lone, 1))
                self.assertEqual(of(land_labels_calls(calls), 2), ["land-pr-2", "land-merge-2", "close-out-2"])
                self.assertEqual(land_release_shas(calls), [SHA, SHA])
                self.assertEqual([row(result, n) for n in (1, 2)], [{"issue": n, "outcome": "landed", "pr": 40 + n} for n in (1, 2)])
                self.assertEqual(join_logs(out), [])

    def test_a_first_poll_that_is_not_behind_or_a_retried_wait_takes_no_joiner(self):
        # A current head waited for its own checks inside land-pr; a retried wait is polled by the loop: neither is the handover point.
        for name, replies, patch in (
                ("current", None, {"land-pr-1": {}}),
                ("pending", None, {"land-pr-1": {"checks": {"state": "pending", "head": SHA, "pending": ["e2e"]}}}),
                ("retried wait", {"land-pr-1": {"pr": 41, "head": SHA, "lock": {"verdict": "land-contended", "lock_sha": B}, "checks": None}}, None)):
            with self.subTest(name=name):
                out = join_run(replies=replies, patch=patch)
                result, calls = out["result"], out["calls"]
                self.assertEqual(ready_during(out, 2), "land-pr-1")
                self.assertEqual(train_labels(calls), [])
                self.assertIn("land-pr-2", labels(calls))
                self.assertEqual([row(result, n)["outcome"] for n in (1, 2)], ["landed", "landed"])
                self.assertEqual(join_logs(out), [])

    def test_a_batch_without_train_or_with_another_merge_strategy_never_joins(self):
        for name, args, patch in (("no train", {"train": False}, None), ("squash", None, {"setup": {"max_parallel": 2, "merge_strategy": "squash"}})):
            with self.subTest(name=name):
                out = join_run(args=args, patch=patch)
                calls = out["calls"]
                self.assertEqual(ready_during(out, 2), "land-pr-1")
                self.assertEqual(join_logs(out), [])
                self.assertEqual(train_labels(calls), [])
                self.assertEqual(of(land_labels_calls(calls), 2), ["land-pr-2", "land-merge-2", "close-out-2"])
                self.assertEqual([row(out["result"], n)["outcome"] for n in (1, 2)], ["landed", "landed"])
        base = run_full(args=dict(ARGS, issues=[1, 2]), patch=BEHIND, turns={"2:ready": DURING_WAIT}, delays={"land-pr-1": LOCK_WAIT})["calls"]
        off = join_run(args={"train": False}, patch={"setup": {}})["calls"]
        self.assertEqual([(c["label"], c.get("prompt")) for c in off], [(c["label"], c.get("prompt")) for c in base])

    def test_up_to_two_issues_join_and_a_third_lands_in_its_own_drain(self):
        out = join_run(issues=(1, 2, 3))
        self.assertEqual([ready_during(out, n) for n in (2, 3)], ["land-pr-1"] * 2)
        self.assertEqual(join_logs(out), [JOIN_LOG_23])
        self.assertEqual([m["issue"] for m in members_of(out["calls"], "train-build-1")], [1, 2, 3])
        self.assertEqual(land_release_shas(out["calls"]), [SHA])
        out = join_run(issues=(1, 2, 3, 4))
        result, calls = out["result"], out["calls"]
        self.assertEqual([ready_during(out, n) for n in (2, 3, 4)], ["land-pr-1"] * 3)
        self.assertEqual(join_logs(out), [JOIN_LOG_23])
        self.assertEqual([m["issue"] for m in members_of(calls, "train-build-1")], [1, 2, 3])
        self.assertNotIn("train-pr-4", labels(calls))
        order = land_labels(calls)
        self.assertLess(order.index("close-out-3"), order.index("land-pr-4"))
        self.assertEqual(labels(calls).count("train-build-1"), 1)
        self.assertEqual([row(result, n)["outcome"] for n in (1, 2, 3, 4)], ["landed"] * 4)
        self.assertEqual(row(result, 4), {"issue": 4, "outcome": "landed", "pr": 44})
        self.assertEqual(land_release_shas(calls), [SHA, SHA])

    def test_an_issue_with_an_unknown_criterion_kind_never_joins(self):
        odd = ready(2, acceptance=[{"id": "AC1", "text": "works", "kind": "vibes"}])
        out = join_run(issues=(1, 2, 3), children={"1": ready(1), "2": odd, "3": ready(3)})
        result, calls = out["result"], out["calls"]
        # Both became ready inside the lock wait, so the landing itself chose its joiners: only the valid one.
        self.assertEqual([ready_during(out, n) for n in (2, 3)], ["land-pr-1"] * 2)
        self.assertEqual(join_logs(out), ["#1: #3 became ready while it waited for the land lock; they land with it as a train"])
        self.assertEqual([m["issue"] for m in members_of(calls, "train-build-1")], [1, 3])
        self.assertEqual(train_labels(calls).count("train-pr-3"), 1)
        self.assertNotIn("train-pr-2", labels(calls))
        self.assertNotIn("land-pr-2", labels(calls))
        self.assertEqual((row(result, 2)["outcome"], row(result, 2)["stage"]), ("stopped", "plan"))
        self.assertEqual([row(result, n)["outcome"] for n in (1, 3)], ["landed", "landed"])
        self.assertEqual(land_release_shas(calls), [SHA])

    def test_a_joined_train_that_fails_before_its_merge_falls_back_to_serial_landing_under_the_same_hold(self):
        for name, replies in (
                ("conflict at car one", {"train-build-1": {"status": "blocked", "conflicted": True, "cars": []}}),
                ("car one red", {"train-checks-1-1": {"state": "failed", "head": X1, "failing": ["ci"]}}),
                ("build died", {"train-build-1": None}),
                ("build threw", {"train-build-1": "throw"}),
                ("ready died", {"train-ready-1": None})):
            with self.subTest(name=name):
                out = join_run(replies=replies)
                result, calls = out["result"], out["calls"]
                order = land_labels(calls)
                self.assertNotIn("train-merge-1", order)
                self.assertEqual((ready_during(out, 2), join_logs(out)), ("land-pr-1", [JOIN_LOG]))
                self.assertEqual(order.count("land-pr-1"), 1)
                tail = ["train-sweep-2", "land-sync-1-1", "land-checks-1-2", "land-merge-1", "close-out-1",
                        "land-pr-2", "land-merge-2", "close-out-2"]
                self.assertEqual(order[-len(tail):], tail)
                # Issue 1 kept its one hold through the failed train; issue 2 then takes and releases its own.
                self.assertEqual(waited_acquires(calls), ["land-pr-1", "land-pr-2"])
                self.assertEqual(lock_releases(calls), ["close-out-1"])
                self.assertEqual(lock_releases(calls, 2), ["close-out-2"])
                self.assertEqual(land_release_shas(calls), [SHA, SHA])
                self.assertEqual(row(result, 1), {"issue": 1, "outcome": "landed", "pr": 41})
                self.assertEqual(row(result, 2), {"issue": 2, "outcome": "landed", "pr": 42})

    def test_a_joined_train_merge_refused_as_behind_resyncs_the_first_landing_and_releases_at_the_moved_sha(self):
        refused = dict(merge_reply({}, merged=False), behind=True, notes="the head branch is not up to date with the base branch")
        out = join_run(replies={"train-merge-1": refused, **OPEN_CAR,
                                "land-sync-1-1": {"status": "done", "conflicted": False, "head": C, "notes": "ok"}})
        result, calls = out["result"], out["calls"]
        self.assertEqual((ready_during(out, 2), join_logs(out)), ("land-pr-1", [JOIN_LOG]))
        order = land_labels(calls)
        self.assertEqual(order[order.index("train-merge-1") + 1:], [
            "train-flip-1-1", "train-sweep-2", "land-sync-1-1", "land-record-1-1", "land-merge-1", "close-out-1", "land-pr-2", "land-merge-2", "close-out-2"])
        self.assertIn(f"forge-claim land acquire --repo owner/repo --branch dev --sha {C}\n", prompt(calls, "land-record-1-1"))
        self.assertEqual(land_release_shas(calls), [C, SHA])
        self.assertNotIn("land-unlock-1", order)
        self.assertEqual([row(result, n) for n in (1, 2)], [{"issue": n, "outcome": "landed", "pr": 40 + n} for n in (1, 2)])

    def test_a_joiner_whose_pr_step_fails_leaves_the_first_landing_alone(self):
        for name, reply, outcome in (("claim lost", {"renew": {"verdict": "not_held", "by": "h2/b9"}}, "claim-lost"), ("dead", None, "stopped")):
            with self.subTest(name=name):
                out = join_run(replies={"train-pr-2": reply})
                result, calls = out["result"], out["calls"]
                self.assertEqual((ready_during(out, 2), join_logs(out)), ("land-pr-1", [JOIN_LOG]))
                self.assertNotIn("train-build-1", labels(calls))
                self.assertNotIn("land-pr-2", labels(calls))
                self.assertEqual(row(result, 2)["outcome"], outcome)
                self.assertEqual(row(result, 1), {"issue": 1, "outcome": "landed", "pr": 41})
                self.assertEqual(land_release_shas(calls), [SHA])
                self.assertEqual(result["relaunch"]["issues"], [2])

    def test_a_lost_reply_on_the_joined_path_releases_the_lock_once(self):
        stopped = lambda n, detail: {"issue": n, "outcome": "stopped", "pr": 40 + n, "stage": "train-merge", "reason": f"train-merge: {detail}"}
        for name, replies, tail, release in (
                # The merge reply and the read after it are lost: the car may be merged, so both members stop and nothing lands serially.
                ("merge and read lost", {"train-merge-1": None, "train-flip-1-1": None}, ["train-flip-1-1", "land-unlock-1", "train-sweep-2"], "land-unlock-1"),
                ("merge threw, car open", {"train-merge-1": "throw", **OPEN_CAR}, ["train-flip-1-1", "land-unlock-1", "train-sweep-2"], "land-unlock-1"),
                # The merge reply is lost and the car reads merged: both are closed out.
                ("merge lost, car merged", {"train-merge-1": None}, ["train-flip-1-1", "close-out-1", "train-sweep-2", "close-out-2"], "close-out-1"),
                # The folded release in the close-out is lost: the wrapper releases the same sha.
                ("close-out lost", {"close-out-1": None}, ["close-out-1", "land-unlock-1", "train-sweep-2", "close-out-2"], None)):
            with self.subTest(name=name):
                out = join_run(replies=replies)
                result, calls = out["result"], out["calls"]
                order = land_labels(calls)
                self.assertEqual(order[order.index("train-merge-1") + 1:], tail)
                self.assertEqual((ready_during(out, 2), join_logs(out)), ("land-pr-1", [JOIN_LOG]))
                self.assertEqual(waited_acquires(calls), ["land-pr-1"])
                if release:
                    self.assertEqual(lock_releases(calls), [release])
                    self.assertEqual(land_release_shas(calls), [SHA])
                else:
                    self.assertEqual(lock_releases(calls), ["close-out-1", "land-unlock-1"])
                    self.assertEqual(land_release_shas(calls), [SHA, SHA])
                self.assertEqual(lock_releases(calls, 2), [])
                if tail[-1] == "train-sweep-2":
                    detail = "stub agent train-merge-1 threw" if name == "merge threw, car open" else "train-merge-1 returned nothing"
                    self.assertEqual([row(result, n) for n in (1, 2)], [stopped(1, detail), stopped(2, detail)])
                    self.assertEqual(result["relaunch"]["issues"], [1, 2])
                elif release:
                    self.assertEqual([row(result, n)["outcome"] for n in (1, 2)], ["landed", "landed"])

    def test_a_lost_lock_before_the_joined_merge_ends_every_member_land_contended(self):
        out = join_run(replies={"train-merge-1": merge_reply({}, lock="acquired", merged=False)})
        result, calls = out["result"], out["calls"]
        self.assertEqual((ready_during(out, 2), join_logs(out)), ("land-pr-1", [JOIN_LOG]))
        order = land_labels(calls)
        self.assertEqual(order[order.index("train-merge-1") + 1:], ["land-unlock-1", "train-sweep-2"])
        self.assertEqual([row(result, n)["outcome"] for n in (1, 2)], ["land-contended", "land-contended"])
        self.assertEqual(land_release_shas(calls), [SHA])

    def test_a_dead_first_landing_step_before_the_handover_leaves_the_joiner_to_its_own_drain(self):
        out = join_run(replies={"land-pr-1": None})
        result, calls = out["result"], out["calls"]
        self.assertEqual((ready_during(out, 2), join_logs(out)), ("land-pr-1", []))
        self.assertEqual(train_labels(calls), [])
        self.assertEqual((row(result, 1)["outcome"], row(result, 1)["stage"]), ("stopped", "pr"))
        # The lost land-pr may have taken the lock: its landing releases the ready head, and issue 2 lands by itself.
        self.assertEqual(lock_releases(calls), ["land-unlock-1"])
        self.assertEqual(of(land_labels_calls(calls), 2), ["land-pr-2", "land-merge-2", "close-out-2"])
        self.assertEqual(row(result, 2), {"issue": 2, "outcome": "landed", "pr": 42})


class ResolveBeforeLockTest(unittest.TestCase):
    """#941: before it asks for the land lock, land-pr probes whether the integration branch merges cleanly into the head. A clean
    probe changes nothing; a conflict is resolved, reviewed and fixed before any lock command, and the reviewed head takes the lock."""

    PROBE_CMD = "git -C /r/.wt/w-issue-1-x merge-tree --write-tree --name-only --no-messages HEAD origin/dev"
    # The probe found a conflict, so land-pr ran no lock command and waited for no check.
    EARLY = {"land-pr-1": {"probe": {"conflicted": True, "tree": "e" * 40, "files": ["x.py"]}, "lock": None, "checks": None}}
    RESOLVED = ["land-pr-1", "land-sync-resolve-1-1", "land-sync-review-1-1", "land-record-1-1"]
    FIXED = "f" * 40
    FOUND = {"verdict": "findings", "findings": [{"severity": "important", "summary": "dropped a sentence dev added"}]}
    LEFT = {"verdict": "findings", "findings": [{"severity": "important", "summary": "the sentence is still missing"}]}
    BEHIND_AT_B = {"ok": True, "head": B, "lock": {"verdict": "acquired", "lock_sha": B}, "checks": {"state": "behind", "head": B}}

    def land(self, **replies):
        return run_full(patch=self.EARLY, replies=replies)

    @staticmethod
    def steps(calls):
        return [(c["label"], c["prompt"]) for c in calls if c["kind"] == "agent"]

    def test_the_probe_runs_in_land_pr_before_the_lock_and_changes_nothing(self):
        _, calls, _ = run()
        text = prompt(calls, "land-pr-1")
        self.assertIn(f"run git -C /r/.wt/w-issue-1-x fetch origin, then alone and exactly: {self.PROBE_CMD}\n", text)
        for needle in ("exit 1 is a conflict only when the first line of its output is a tree id (40 hexadecimal characters)",
                       "(a missing ref prints nothing there)", "never run git merge in this step",
                       "When probe's conflicted is true, run no lock command and wait for no check: return lock null and checks null"):
            self.assertIn(needle, text)
        self.assertLess(text.index("push origin issue-1-x"), text.index(self.PROBE_CMD))
        self.assertEqual(object_branch(schema_of(calls, "land-pr-1")["properties"]["probe"])["properties"]["tree"], {"type": "string"})
        self.assertLess(text.index(self.PROBE_CMD), text.index(f"--sha {SHA} --wait\n"))
        schema = schema_of(calls, "land-pr-1")
        self.assertIn({"type": "null"}, schema["properties"]["probe"]["anyOf"])
        self.assertEqual(object_branch(schema["properties"]["probe"])["required"], ["conflicted"])
        self.assertEqual(schema["required"], ["renew"])

    def test_a_clean_probe_is_the_old_flow_with_the_same_calls(self):
        for name, patch in (("current", {}), ("behind", BEHIND)):
            base = run(patch=patch)[1]
            probes = (None, {"conflicted": False}, {"conflicted": False, "files": []}, {"conflicted": False, "detail": "fatal: not a tree"})
            for probe in probes:
                with self.subTest(name=name, probe=probe):
                    result, calls, _ = run(patch={"land-pr-1": dict(patch.get("land-pr-1", {}), probe=probe)})
                    self.assertEqual(self.steps(calls), self.steps(base))
                    self.assertEqual(row(result, 1)["outcome"], "landed")
        # The clean path keeps its call count: the probe rides in land-pr.
        self.assertEqual([label for label in labels(run()[1]) if label != "setup"], HAPPY)

    def test_exit_one_without_a_tree_id_is_no_conflict(self):
        """git merge-tree also exits 1, with nothing on stdout, when a ref is missing: only a tree id proves a conflict."""
        base = self.steps(run()[1])
        for tree in (None, "", "merge-tree: origin/dev - not something we can merge", "e" * 39, "E" * 40):
            probe = {"conflicted": True, "files": []} if tree is None else {"conflicted": True, "tree": tree, "files": []}
            with self.subTest(tree=tree):
                # The step took the lock as it always did: the landing is the old flow.
                result, calls, _ = run(patch={"land-pr-1": {"probe": probe}})
                self.assertEqual(self.steps(calls), base)
                self.assertEqual(row(result, 1)["outcome"], "landed")
                # A step that ran no lock command on such a reply resolves nothing: it stops at the lock and releases the ready head.
                out = run_full(patch={"land-pr-1": {"probe": probe, "lock": None, "checks": None}})
                got = row(out["result"], 1)
                self.assertEqual((got["outcome"], got["stage"]), ("stopped", "land-lock"))
                self.assertEqual(land_labels(out["calls"]), ["land-pr-1", "land-unlock-1"])
                self.assertEqual(land_release_shas(out["calls"]), [SHA])
        # A tree id with surrounding whitespace is still one.
        out = run_full(patch={"land-pr-1": dict(self.EARLY["land-pr-1"], probe={"conflicted": True, "tree": "e" * 40 + "\n"})})
        self.assertEqual(land_labels(out["calls"]), self.RESOLVED + ["land-merge-1", "close-out-1"])

    def test_a_conflicted_probe_that_still_names_a_lock_verdict_is_the_old_flow(self):
        # The step took the lock against its prompt: the landing holds it, and a conflict is found by the sync under it (#913).
        result, calls, _ = run(patch={"land-pr-1": {"probe": {"conflicted": True, "tree": "e" * 40}, "checks": {"state": "behind", "head": SHA}}},
                               replies={"land-sync-1-1": ABORTED})
        self.assertEqual(land_labels(calls), ["land-pr-1", "land-sync-1-1", "land-unlock-1", "land-sync-resolve-1-1", "land-sync-review-1-1",
                                              "land-record-1-1", "land-merge-1", "close-out-1"])
        self.assertEqual(row(result, 1)["outcome"], "landed")

    def test_a_conflict_is_resolved_and_reviewed_before_any_acquire_and_the_reviewed_head_lands(self):
        out = self.land()
        result, calls = out["result"], out["calls"]
        self.assertEqual(row(result, 1), {"issue": 1, "outcome": "landed", "pr": 41})
        self.assertEqual(land_labels(calls), self.RESOLVED + ["land-merge-1", "close-out-1"])
        self.assertIn("#1: dev conflicts with the head; resolving before the land lock is asked for", out["logs"])
        # The resolution and its review are the #913 steps, word for word, and MARKER_CHECK is in them.
        under = run(patch=BEHIND, replies={"land-sync-1-1": ABORTED})[1]
        for label in ("land-sync-resolve-1-1", "land-sync-review-1-1"):
            with self.subTest(label=label):
                self.assertEqual(prompt(calls, label), prompt(under, label))
        self.assertIn("diff --check HEAD", prompt(calls, "land-sync-resolve-1-1"))
        # The reviewed head is recorded, then takes the lock for the first time, waiting, and its checks are polled: one step.
        record = prompt(calls, "land-record-1-1")
        self.assertIn(f"Accepted head: {B}\n", record)
        self.assertIn(f"take the cross-host landing lock of the branch dev at the head {B}; a conflict with dev was resolved before the lock was asked for", record)
        self.assertIn(f"forge-claim land acquire --repo owner/repo --branch dev --sha {B} --wait\n", record)
        self.assertLess(record.index("Accepted head:"), record.index("land acquire"))
        self.assertIn("merge-base --is-ancestor origin/dev HEAD", record)
        # The record step equals the #913 retake's but for the sentence that says why the lock is taken.
        again = "take the cross-host landing lock of the branch dev again, at the head " + B + "; it was released while a conflict was resolved"
        first = "take the cross-host landing lock of the branch dev at the head " + B + "; a conflict with dev was resolved before the lock was asked for"
        self.assertEqual(record, prompt(under, "land-record-1-1").replace(again, first))
        merge = prompt(calls, "land-merge-1")
        self.assertIn(f"--sha {B}\n", merge)
        self.assertIn(f"--match-head-commit {B}", merge)
        # One hold, taken at the reviewed head and released there once, in the close-out: no step ever held the ready head.
        self.assertEqual(lock_releases(calls), ["close-out-1"])
        self.assertEqual(land_release_shas(calls), [B])
        self.assertIsNone(result["relaunch"])

    def test_a_finding_goes_through_the_fix_round_and_the_fix_is_what_lands(self):
        out = self.land(**{"land-sync-review-1-1": self.FOUND})
        result, calls = out["result"], out["calls"]
        self.assertEqual(row(result, 1)["outcome"], "landed")
        self.assertEqual(land_labels(calls), ["land-pr-1", "land-sync-resolve-1-1", "land-sync-review-1-1", "land-sync-fix-1-1",
                                              "land-sync-rereview-1-1", "land-record-1-1", "land-merge-1", "close-out-1"])
        self.assertIn(f"merge commit {B}", prompt(calls, "land-sync-fix-1-1"))
        record = prompt(calls, "land-record-1-1")
        self.assertIn(f"Accepted head: {self.FIXED}\n", record)
        self.assertIn(f"--sha {self.FIXED} --wait\n", record)
        self.assertIn(f"--match-head-commit {self.FIXED}", prompt(calls, "land-merge-1"))
        self.assertEqual(land_release_shas(calls), [self.FIXED])

    def test_a_finding_that_survives_the_fix_round_ends_sync_review_without_ever_taking_the_lock(self):
        out = self.land(**{"land-sync-review-1-1": self.FOUND, "land-sync-rereview-1-1": self.LEFT})
        result, calls = out["result"], out["calls"]
        got = row(result, 1)
        self.assertEqual((got["outcome"], got["reason"]),
                         ("sync-review", f"sync-review of merge {B}: a finding survived the fix round; unaccepted fix commit {self.FIXED}; "
                          "finding the sentence is still missing"))
        self.assertEqual(got["fix"], {"commit": self.FIXED, "notes": "ok"})
        self.assertEqual(land_labels(calls), ["land-pr-1", "land-sync-resolve-1-1", "land-sync-review-1-1", "land-sync-fix-1-1",
                                              "land-sync-rereview-1-1", "land-unlock-1"])
        # No step was told to take the lock. The one release, at the ready head, covers a land-pr that took it against its prompt.
        self.assertNotIn("land acquire", "".join(c["prompt"] for c in calls if c["label"].startswith("land-sync-")))
        self.assertEqual(land_release_shas(calls), [SHA])
        self.assertEqual(result["relaunch"]["conts"], PRE_MERGE_CONTS)

    def test_every_stop_before_the_lock_releases_the_ready_head_once_and_accepts_nothing(self):
        stops = {
            "the resolution is lost": ({"land-sync-resolve-1-1": None}, "stopped"),
            "the resolution is blocked": ({"land-sync-resolve-1-1": {"status": "blocked", "conflicted": True, "notes": "too tangled"}}, "conflict"),
            "the resolution names two commits": ({"land-sync-resolve-1-1": {"status": "done", "conflicted": True, "head": B, "merge_commit": C}}, "stopped"),
            "the review is lost": ({"land-sync-review-1-1": None}, "sync-review"),
            "the fix is blocked": ({"land-sync-review-1-1": self.FOUND, "land-sync-fix-1-1": {"status": "blocked", "notes": "no"}}, "sync-review"),
            "the re-review is lost": ({"land-sync-review-1-1": self.FOUND, "land-sync-rereview-1-1": None}, "sync-review"),
        }
        for name, (replies, outcome) in stops.items():
            with self.subTest(stop=name):
                out = self.land(**replies)
                result, calls = out["result"], out["calls"]
                self.assertEqual(row(result, 1)["outcome"], outcome)
                ls = labels(calls)
                for gone in ("land-sync-1-1", "land-record-1-1", "land-merge-1", "close-out-1", "land-ask-1"):
                    self.assertNotIn(gone, ls)
                # A land-pr that answered conflicted may have taken the lock all the same: the wrapper releases the ready head, once, last.
                self.assertEqual((ls.count("land-unlock-1"), ls[-1]), (1, "land-unlock-1"))
                self.assertEqual(land_release_shas(calls), [SHA])
                # The accepted head of the pull request is still the ready head: only land-pr wrote it.
                heads = {sha for c in calls if c["kind"] == "agent" for sha in re.findall(r"Accepted head: ([0-9a-f]+)", c["prompt"])}
                self.assertEqual(heads, {SHA})
                self.assertEqual(result["relaunch"]["conts"], PRE_MERGE_CONTS)

    def test_a_relaunch_after_a_stop_before_the_lock_reviews_again_before_it_lands(self):
        first = self.land(**{"land-sync-review-1-1": None})["result"]
        self.assertEqual(row(first, 1)["outcome"], "sync-review")
        # Run 2: the PR is open at the pushed, unaccepted merge; readopt refuses to land it as it stands, as after a #913 stop.
        result, calls, _ = run(args=first["relaunch"],
                               patch={"facts-1": {"open_pr": OPEN_PR, "claim": {"verdict": "held_by", "by": HOLDER}, "lane": None}},
                               replies={"readopt-1": {"ok": False, "reason": "unaccepted", "detail": f"head {B}"}})
        ls = labels(calls)
        self.assertLess(ls.index("readopt-1"), ls.index("child-1"))
        self.assertEqual(child(calls, 1)["args"]["cont"], first["relaunch"]["conts"]["1"])
        self.assertLess(ls.index("child-1"), ls.index("land-merge-1"))
        self.assertEqual(row(result, 1)["outcome"], "landed")

    def test_lost_and_refused_replies_on_the_new_step_order_keep_the_lock_accounting(self):
        refused = lambda v: {"ok": True, "head": B, "lock": {"verdict": v, "lock_sha": C, "by": "h2/b9"}, "checks": None}
        waits = {f"land-relock-1-{k}": {"lock": {"verdict": "land-contended", "lock_sha": C}} for k in (1, 2, 3)}
        cases = {
            # The record step may have taken the lock at the reviewed head before its reply was lost: the wrapper releases it there.
            "record lost": ({"land-record-1-1": None}, "stopped", ["land-unlock-1"], [B]),
            "record threw": ({"land-record-1-1": "throw"}, "stopped", ["land-unlock-1"], [B]),
            # A record that changed nothing ran no lock command.
            "record refused the head": ({"land-record-1-1": {"ok": False, "head": C, "lock": None, "checks": None}}, "stopped", [], []),
            "held by another": ({"land-record-1-1": refused("held_by")}, "land-contended", [], []),
            "lost to another": ({"land-record-1-1": refused("lost_to")}, "land-contended", [], []),
            "every wait ran out": ({"land-record-1-1": refused("land-contended"), **waits}, "land-contended", [], []),
            "a relock is lost": ({"land-record-1-1": refused("land-contended"), "land-relock-1-1": None}, "stopped", ["land-unlock-1"], [B]),
            "the merge check lost the lock": ({"land-merge-1": {"merged": False, "notes": "held_by", "lock": {"verdict": "held_by", "lock_sha": C}}},
                                              "land-contended", ["land-unlock-1"], [B]),
            "the close-out is lost": ({"close-out-1": None}, "stopped", ["close-out-1", "land-unlock-1"], [B, B]),
        }
        for name, (replies, outcome, releases, shas) in cases.items():
            with self.subTest(case=name):
                out = self.land(**replies)
                result, calls = out["result"], out["calls"]
                self.assertEqual(row(result, 1)["outcome"], outcome)
                self.assertEqual(lock_releases(calls), releases)
                self.assertEqual(land_release_shas(calls), shas)
                if name != "the close-out is lost":
                    self.assertNotIn("close-out-1", labels(calls))
        got = row(self.land(**{"land-record-1-1": refused("held_by")})["result"], 1)
        self.assertEqual(got["reason"], f"the land lock was not taken at the reviewed head {B} (held_by)")
        # A wait that ran out at the CLI's bound is waited for again through the program, in a land-relock step.
        out = self.land(**{"land-record-1-1": refused("land-contended"), "land-relock-1-1": {"lock": {"verdict": "acquired", "lock_sha": B}},
                           "land-checks-1-1": {"state": "passed", "head": B, "required": ["ci"], "passed": ["ci"]}})
        self.assertEqual(land_labels(out["calls"]), self.RESOLVED + ["land-relock-1-1", "land-checks-1-1", "land-merge-1", "close-out-1"])
        self.assertIn(f"--sha {B} --wait\n", prompt(out["calls"], "land-relock-1-1"))
        self.assertEqual(land_release_shas(out["calls"]), [B])
        self.assertEqual(row(out["result"], 1)["outcome"], "landed")

    def test_a_lost_or_ended_land_pr_is_handled_as_before_the_probe(self):
        out = run_full(replies={"land-pr-1": None})
        self.assertEqual((row(out["result"], 1)["outcome"], row(out["result"], 1)["stage"]), ("stopped", "pr"))
        self.assertEqual(land_release_shas(out["calls"]), [SHA])
        lost = dict(self.EARLY["land-pr-1"], pr=41, head=SHA, renew={"verdict": "not_held", "by": "h2/b9"})
        out = run_full(replies={"land-pr-1": lost})
        self.assertEqual(row(out["result"], 1)["outcome"], "claim-lost")
        self.assertEqual(land_labels(out["calls"]), ["land-pr-1"])
        moved = dict(self.EARLY["land-pr-1"], pr=41, head=C, renew={"verdict": "renewed"})
        out = run_full(replies={"land-pr-1": moved})
        self.assertEqual((row(out["result"], 1)["outcome"], row(out["result"], 1)["stage"]), ("stopped", "head-moved"))
        self.assertEqual(land_release_shas(out["calls"]), [])

    def test_behind_after_the_first_acquire_a_clean_merge_stays_under_the_lock(self):
        out = self.land(**{"land-record-1-1": self.BEHIND_AT_B,
                           "land-sync-1-2": {"status": "done", "conflicted": False, "head": C, "notes": "ok"}})
        result, calls = out["result"], out["calls"]
        self.assertEqual(row(result, 1)["outcome"], "landed")
        self.assertEqual(land_labels(calls), self.RESOLVED + ["land-sync-1-2", "land-record-1-2", "land-merge-1", "close-out-1"])
        again = prompt(calls, "land-record-1-2")
        self.assertIn(f"move the cross-host landing lock of the branch dev to the head {C}", again)
        self.assertNotIn("--wait\n", again)
        self.assertEqual(land_release_shas(calls), [C])

    def test_a_conflict_after_the_acquire_takes_the_913_path_and_the_round_bound_counts_both(self):
        D = "d" * 40
        second = {"land-record-1-1": self.BEHIND_AT_B, "land-sync-1-2": dict(ABORTED, head=B),
                  "land-sync-resolve-1-2": {"status": "done", "conflicted": True, "head": C, "merge_commit": C, "notes": "ok"}}
        out = self.land(**second)
        result, calls = out["result"], out["calls"]
        self.assertEqual(row(result, 1)["outcome"], "landed")
        self.assertEqual(land_labels(calls), self.RESOLVED + [
            "land-sync-1-2", "land-unlock-1", "land-sync-resolve-1-2", "land-sync-review-1-2", "land-record-1-2", "land-merge-1", "close-out-1"])
        # The hold taken at the reviewed head is released before the second resolution; the retake waits at the second reviewed head.
        self.assertIn(f"{LAND_RELEASE}{B}\n", prompt(calls, "land-unlock-1"))
        retake = prompt(calls, "land-record-1-2")
        self.assertIn(f"take the cross-host landing lock of the branch dev again, at the head {C}; it was released while a conflict was resolved", retake)
        self.assertIn(f"--sha {C} --wait\n", retake)
        self.assertEqual(land_release_shas(calls), [B, C])
        # A third conflict in one landing goes to the owner: the round before the lock counts as the first.
        third = dict(second, **{"land-record-1-2": {"ok": True, "head": C, "checks": {"state": "behind", "head": C}},
                                "land-sync-1-3": dict(ABORTED, head=C)})
        out = self.land(**third)
        got = row(out["result"], 1)
        self.assertEqual(got["outcome"], "conflict")
        self.assertIn("after 2 earlier conflicts in one landing", got["owner_ask"]["items"][0])
        ls = labels(out["calls"])
        self.assertNotIn("land-sync-resolve-1-3", ls)
        self.assertNotIn("land-merge-1", ls)
        self.assertEqual(land_release_shas(out["calls"]), [B, C])
        # The round before the lock answered no behind poll, so it spends none of the resyncs a landing has under the lock.
        clean = {"land-record-1-1": self.BEHIND_AT_B, "land-sync-1-2": {"status": "done", "conflicted": False, "head": C, "notes": "ok"},
                 "land-record-1-2": {"ok": True, "head": C, "checks": {"state": "behind", "head": C}},
                 "land-sync-1-3": {"status": "done", "conflicted": False, "head": D, "notes": "ok"}}
        out = self.land(**clean)
        self.assertEqual(row(out["result"], 1)["outcome"], "landed")
        self.assertIn(f"--match-head-commit {D}", prompt(out["calls"], "land-merge-1"))
        out = self.land(**dict(clean, **{"land-record-1-3": {"ok": True, "head": D, "checks": {"state": "behind", "head": D}}}))
        got = row(out["result"], 1)
        self.assertEqual((got["outcome"], got["reason"]), ("land-contended", "behind dev after 3 resyncs in all"))
        self.assertEqual(land_release_shas(out["calls"]), [D])


class ResolveBeforeLockTrainTest(unittest.TestCase):
    """#941 with #936 and #822: a landing that resolved a conflict before the lock hands over to a train from the step that took the
    lock at the reviewed head, and the train rides that head."""

    EARLY = ResolveBeforeLockTest.EARLY
    BEHIND_AT_B = ResolveBeforeLockTest.BEHIND_AT_B
    RESOLVED = ResolveBeforeLockTest.RESOLVED
    TRAIN = ["train-pr-2", "train-build-1", "train-checks-1-1", "train-checks-1-2", "train-ready-1", "train-merge-1"]

    def join(self, replies=None, **more):
        return join_run(patch=self.EARLY, replies={"land-record-1-1": self.BEHIND_AT_B, **(replies or {})}, **more)

    def test_a_lander_that_resolved_before_the_lock_takes_a_joiner(self):
        out = self.join()
        result, calls = out["result"], out["calls"]
        self.assertEqual(land_labels(calls), ["train-sweep-1"] + self.RESOLVED + self.TRAIN + ["close-out-1", "train-sweep-2", "close-out-2"])
        self.assertEqual(join_logs(out), [JOIN_LOG])
        # The train's first member is the reviewed head: car 1 is built on it, the ready read expects it, and the merge re-checks the lock there.
        self.assertEqual([(m["issue"], m["head"]) for m in members_of(calls, "train-build-1")], [(1, B), (2, SHA)])
        self.assertEqual([(m["issue"], m["head"]) for m in members_of(calls, "train-ready-1")], [(1, B), (2, SHA)])
        merge = prompt(calls, "train-merge-1")
        self.assertIn(f"forge-claim land acquire --repo owner/repo --branch dev --sha {B}\n", merge)
        self.assertIn(f"gh pr merge 92 --repo owner/repo --merge --match-head-commit {X2} --delete-branch", merge)
        self.assertNotIn("forge-claim land", prompt(calls, "train-pr-2"))
        # One hold: taken at the reviewed head by the record step, never moved, released there once by the first landing's close-out.
        self.assertEqual(lock_releases(calls), ["close-out-1"])
        self.assertEqual(land_release_shas(calls), [B])
        self.assertEqual(lock_releases(calls, 2), [])
        self.assertEqual(row(result, 1), {"issue": 1, "outcome": "landed", "pr": 41, "train": 1, "car_pr": 92})
        self.assertEqual(row(result, 2), {"issue": 2, "outcome": "landed", "pr": 42, "train": 1, "car_pr": 92})
        self.assertIsNone(result["relaunch"])

    def test_an_issue_that_becomes_ready_during_the_resolution_or_the_wait_joins(self):
        for step in ("land-sync-resolve-1-1", "land-record-1-1"):
            with self.subTest(step=step):
                out = self.join(late=AFTER_WAIT, delays={step: LOCK_WAIT})
                self.assertEqual(ready_during(out, 2), step)
                self.assertEqual(join_logs(out), [JOIN_LOG])
                self.assertEqual([row(out["result"], n)["outcome"] for n in (1, 2)], ["landed", "landed"])
                self.assertEqual(land_release_shas(out["calls"]), [B])

    def test_a_first_poll_at_the_reviewed_head_that_is_not_behind_takes_no_joiner(self):
        out = join_run(patch=self.EARLY)
        result, calls = out["result"], out["calls"]
        self.assertEqual(train_labels(calls), [])
        self.assertEqual(join_logs(out), [])
        self.assertEqual(landing_of(calls, 1), landing_of(run_full(patch=self.EARLY)["calls"], 1))
        self.assertEqual(of(land_labels_calls(calls), 2), ["land-pr-2", "land-merge-2", "close-out-2"])
        self.assertEqual([row(result, n) for n in (1, 2)], [{"issue": n, "outcome": "landed", "pr": 40 + n} for n in (1, 2)])
        self.assertEqual(land_release_shas(calls), [B, SHA])

    def test_two_issues_that_waited_together_train_on_the_reviewed_head(self):
        result, calls, _ = train_run(patch=self.EARLY, replies={"land-record-1-1": self.BEHIND_AT_B})
        self.assertEqual(land_labels(calls), ["train-sweep-1"] + self.RESOLVED + self.TRAIN + ["close-out-1", "train-sweep-2", "close-out-2"])
        self.assertEqual([(m["issue"], m["head"]) for m in members_of(calls, "train-build-1")], [(1, B), (2, SHA)])
        self.assertEqual([row(result, n)["outcome"] for n in (1, 2)], ["landed", "landed"])
        self.assertEqual(land_release_shas(calls), [B])

    def test_a_first_member_whose_pr_left_the_reviewed_head_ends_before_the_merge(self):
        ready = {"members": [{"issue": 1, "renew": {"verdict": "renewed"}, "head": SHA, "state": "OPEN"},
                             {"issue": 2, "renew": {"verdict": "renewed"}, "head": SHA, "state": "OPEN"}]}
        out = self.join(replies={"train-ready-1": ready})
        got = row(out["result"], 1)
        self.assertEqual((got["outcome"], got["stage"], got["expected"], got["head"]), ("stopped", "head-moved", B, SHA))
        self.assertNotIn("train-merge-1", labels(out["calls"]))
        self.assertEqual(lock_releases(out["calls"]), ["land-unlock-1"])
        self.assertEqual(land_release_shas(out["calls"])[0], B)

    def test_a_joined_train_that_falls_back_lands_serially_under_the_same_hold(self):
        out = self.join(replies={"train-build-1": {"status": "blocked", "conflicted": True, "cars": [], "notes": "car 2 conflicts"},
                                 "land-sync-1-2": {"status": "done", "conflicted": False, "head": C, "notes": "ok"}})
        result, calls = out["result"], out["calls"]
        self.assertEqual(join_logs(out), [JOIN_LOG])
        self.assertNotIn("train-merge-1", labels(calls))
        self.assertEqual(of(land_labels_calls(calls), 1), self.RESOLVED + ["land-sync-1-2", "land-record-1-2", "land-merge-1", "close-out-1"])
        self.assertEqual(of(land_labels_calls(calls), 2), ["land-pr-2", "land-merge-2", "close-out-2"])
        self.assertEqual([row(result, n) for n in (1, 2)], [{"issue": n, "outcome": "landed", "pr": 40 + n} for n in (1, 2)])
        # The hold taken at the reviewed head moved to the clean resync's head and was released there once.
        self.assertEqual(land_release_shas(calls), [C, SHA])


def land_labels_calls(calls):
    return [c for c in calls if c["label"].startswith(("land-", "close-out-"))]
