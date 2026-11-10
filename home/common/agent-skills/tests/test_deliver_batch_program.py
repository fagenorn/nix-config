"""deliver-batch.js control flow against stub agents and a stub child workflow (#636).

The Workflow program runs under node with stub agent(), workflow(), parallel(), pipeline() and
phase(); each scenario fixes some replies and asserts the table or the call sequence.
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


def run_full(args=None, replies=None, patch=None, children=None, turns=None):
    node = shutil.which("node")
    if node is None:
        raise AssertionError("node is not on PATH; the deliver-batch scenarios need it")
    scenario = {"args": ARGS if args is None else args, "replies": replies or {},
                "patch": patch or {}, "children": children or {}, "turns": turns or {}}
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
                 "claim": {"verdict": "free", "by": None}, "merged_refs": [], "open_pr": None, "blockers": [],
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
                self.assertEqual(row(result, 1), {"issue": 1, "outcome": "stopped", "detail": NO_LANE})
                self.assertNotIn("acquire-1", labels(calls))
                self.assertNotIn("child-1", labels(calls))
                self.assertEqual(result["relaunch"]["issues"], [1])

    def test_a_missing_lane_after_an_unaccepted_readopt_stops_and_keeps_the_claim(self):
        result, calls, _ = run(patch={"facts-1": {"open_pr": OPEN_PR, "lane": None}},
                               replies={"readopt-1": UNACCEPTED})
        self.assertEqual(result["stage"], "done")
        self.assertEqual(row(result, 1), {"issue": 1, "outcome": "stopped", "detail": NO_LANE})
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
        self.assertEqual(row(result, 1), {"issue": 1, "outcome": "stopped", "detail": "claim status"})
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
                self.assertEqual(row(result, 1), {"issue": 1, "outcome": "stopped", "stage": "release", "detail": detail})
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
        self.assertEqual(row(result, 1), {"issue": 1, "outcome": "stopped", "stage": "release", "detail": "HTTP 502"})
        self.assertEqual(result["relaunch"]["issues"], [1])
        result, _, _ = run(patch={"facts-1": free}, replies={"release-1": {"verdict": "not_held"}})
        self.assertEqual(row(result, 1), {"issue": 1, "outcome": "closed", "released": False})
        self.assertIsNone(result["relaunch"])

    def test_a_closed_issue_with_a_failed_claim_lookup_stops_and_stays_in_relaunch(self):
        # A failed lookup proves nothing about ownership: the closed row must not be final, or a claim this batch holds is never released.
        err = {"state": "CLOSED", "claim": {"verdict": "error", "by": None}}
        result, calls, _ = run(patch={"facts-1": err})
        self.assertEqual(row(result, 1), {"issue": 1, "outcome": "stopped", "detail": "claim status"})
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
        self.assertEqual(result["relaunch"], dict(ARGS, issues=[1, 2, 3]))

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


class ContTest(unittest.TestCase):
    def test_an_interrupted_task_resumes_through_its_forwarded_cont(self):
        cont = {"setup": {"holder": HOLDER, "branch": "issue-1-x"}, "lane": "direct", "plan": None,
                "done": [], "partial": 1}
        dead = {"stage": "task-review", "task": {"n": 1}, "review": None, "dead_agents": ["review-1"], "cont": cont}
        first, _, _ = run(children={"1": dead})
        self.assertEqual(first["stage"], "breaker")
        self.assertEqual(first["relaunch"], dict(ARGS, conts={"1": cont}))
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
HAPPY = ["facts-1", "acquire-1", "child-1", "child-1", "land-pr-1", "land-sync-1-1", "land-checks-1-1",
         "land-merge-1", "land-unlock-1", "close-out-1"]


def ready(n, acceptance=None, head=SHA):
    return {"stage": "ready", "head": head, "branch": f"issue-{n}-x", "worktree": f"/r/.wt/w-issue-{n}-x",
            "verify": [{"id": "build", "status": "pass", "summary": "ok"}], "tasks": [{"n": 1}],
            "acceptance": acceptance or [{"id": "AC1", "text": "works", "kind": "code"}], "fix_waves": 0,
            "cont": {"setup": {"holder": HOLDER, "branch": f"issue-{n}-x", "worktree": f"/r/.wt/w-issue-{n}-x"}}}


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


def run_child(args):
    node = shutil.which("node")
    if node is None:
        raise AssertionError("node is not on PATH; the deliver-standard scenarios need it")
    scenario = {"args": args, "replies": {}, "patch": {}}
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


RENEW_READ = {"verdict", "by", "detail", "transient"}
FOLDED_READ = {
    "land-pr-1": ({"pr", "head"}, {"renew": RENEW_READ, "lock": {"verdict"}}),
    "land-merge-1": ({"merged", "notes"}, {"renew": RENEW_READ, "lock": {"verdict"}}),
    "land-record-1-1": ({"ok", "head", "detail"}, {"lock": {"verdict"}}),
}


class FoldTest(unittest.TestCase):
    """#716: the folded landing steps keep every field the program reads, and a folded lock is always released."""

    def test_folded_schemas_keep_every_read_field(self):
        _, calls, _ = run(replies={"land-sync-1-1": {"status": "done", "conflicted": False, "head": B, "notes": "ok"},
                                   "land-checks-1-1": {"state": "passed", "head": B, "required": ["ci"], "passed": ["ci"]}})
        for label, (top, nested) in FOLDED_READ.items():
            with self.subTest(label=label):
                schema = schema_of(calls, label)
                self.assertLessEqual(top, set(schema["properties"]))
                for name, fields in nested.items():
                    if name == "lock":
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
        result, calls, _ = run(replies={
            "land-sync-1-1": {"status": "done", "conflicted": False, "head": B, "notes": "ok"},
            "land-record-1-1": {"ok": True, "head": "d" * 40, "lock": {"verdict": "moved", "lock_sha": B}}})
        self.assertEqual((row(result, 1)["outcome"], row(result, 1)["stage"]), ("stopped", "land-record"))
        self.assertEqual(labels(calls).count("land-unlock-1"), 1)
        self.assertIn(f"forge-claim land release --repo owner/repo --branch dev --sha {B}\n", prompt(calls, "land-unlock-1"))

    def test_a_lost_folded_lock_reply_releases_every_sha_it_may_hold(self):
        release = f"forge-claim land release --repo owner/repo --branch dev --sha {SHA}\n"
        again = (f"When it prints not_held with lock_sha {B}, run alone and exactly: "
                 f"forge-claim land release --repo owner/repo --branch dev --sha {B}")
        synced = {"land-sync-1-1": {"status": "done", "conflicted": False, "head": B, "notes": "ok"},
                  "land-checks-1-1": {"state": "passed", "head": B, "required": ["ci"], "passed": ["ci"]}}
        # The initial --wait lock and the pre-merge re-check: the lock is held (or may be) at one sha only.
        for label, extra in (("land-pr-1", {}), ("land-merge-1", synced)):
            for reply in (None, "throw"):
                with self.subTest(label=label, reply=reply):
                    result, calls, _ = run(replies=dict(extra, **{label: reply}))
                    self.assertEqual(row(result, 1)["outcome"], "stopped")
                    ls = of(calls, 1)
                    self.assertEqual(ls[ls.index(label):], [label, "land-unlock-1"])
                    self.assertNotIn("When it prints not_held", prompt(calls, "land-unlock-1"))
        # The record step's move: unanswered, it may or may not have moved the lock to B, so both are released.
        for reply in (None, "throw", {"ok": True, "head": B, "lock": {"verdict": "error", "detail": "gh failed"}}):
            with self.subTest(record=reply):
                _, calls, _ = run(replies={"land-sync-1-1": synced["land-sync-1-1"], "land-record-1-1": reply})
                text = prompt(calls, "land-unlock-1")
                self.assertIn(release, text)
                self.assertIn(again, text)
                self.assertEqual(labels(calls).count("land-unlock-1"), 1)
        # Definitive answers: no move ran (ok false, lock null) or another holder refused it; only the old sha is ours.
        for reply in ({"ok": False, "head": "d" * 40, "detail": "head differs", "lock": None},
                      {"ok": True, "head": B, "lock": {"verdict": "held_by", "lock_sha": "c" * 40, "by": "h2/b9"}}):
            with self.subTest(record=reply):
                _, calls, _ = run(replies={"land-sync-1-1": synced["land-sync-1-1"], "land-record-1-1": reply})
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
        self.assertIn(f"forge-claim land release --repo owner/repo --branch dev --sha {SHA}", prompt(calls, "land-unlock-1"))
        self.assertIn("rules/branches/dev", prompt(calls, "land-checks-1-1"))
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
        result, calls, _ = run(replies={"land-pr-1": {"pr": 41, "head": SHA, "lock": {"verdict": "land-contended", "lock_sha": B}}})
        self.assertEqual(row(result, 1)["outcome"], "land-contended")
        for label in ("land-sync-1-1", "land-checks-1-1", "land-merge-1", "land-unlock-1", "release-1", "close-out-1"):
            self.assertNotIn(label, labels(calls))
        self.assertEqual(result["relaunch"]["issues"], [1])
        self.assertEqual(result["relaunch"]["conts"], {"1": ready(1)["cont"]})

    def test_ci_failing_twice_is_reported_and_never_merged(self):
        result, calls, _ = run(replies={
            "land-checks-1-1": {"state": "failed", "head": SHA, "failing": ["ci"]},
            "land-checks-1-2": {"state": "failed", "head": FIX, "failing": ["ci"]}})
        self.assertEqual(row(result, 1)["outcome"], "ci-failed")
        self.assertEqual(labels(calls).count("land-fix-1"), 1)
        self.assertIn("land-fix-review-1", labels(calls))
        self.assertIn("land-unlock-1", labels(calls))
        for label in ("land-merge-1", "release-1", "close-out-1"):
            self.assertNotIn(label, labels(calls))

    def test_ci_failing_once_is_fixed_and_lands_the_fix_head(self):
        result, calls, _ = run(replies={
            "land-checks-1-1": {"state": "failed", "head": SHA, "failing": ["ci"]},
            "land-record-1-1": {"ok": True, "head": FIX},
            "land-checks-1-2": {"state": "passed", "head": FIX, "passed": ["ci"]}})
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
        result, calls, _ = run(replies={
            "land-checks-1-1": {"state": "failed", "head": SHA, "failing": ["ci"]},
            "land-fix-review-1": {"verdict": "findings", "findings": [{"severity": "important", "summary": "skipped a test"}]}})
        self.assertEqual(row(result, 1)["outcome"], "ci-failed")
        self.assertNotIn("land-record-1-1", labels(calls))
        self.assertNotIn("land-merge-1", labels(calls))
        self.assertEqual(result["relaunch"]["conts"], {"1": ready(1)["cont"]})

    def test_a_declared_check_missing_from_a_passed_reply_is_never_merged(self):
        result, calls, _ = run(patch={"setup": {"required_checks": ["ci", "lint"]}})
        self.assertEqual((row(result, 1)["outcome"], row(result, 1)["stage"], row(result, 1)["missing"]),
                         ("stopped", "checks", ["lint"]))
        self.assertIn('["ci","lint"]', prompt(calls, "land-checks-1-1"))  # DECLARED as JSON.stringify writes it
        self.assertNotIn("land-merge-1", labels(calls))
        self.assertIn("land-unlock-1", labels(calls))

    def test_every_declared_check_passing_lands(self):
        result, _, _ = run(patch={"setup": {"required_checks": ["ci", "lint"]},
                                  "land-checks-1-1": {"passed": ["ci", "lint"]}})
        self.assertEqual(row(result, 1)["outcome"], "landed")

    def test_close_out_ends_the_landing_owner_actions(self):
        _, calls, _ = run()
        close = prompt(calls, "close-out-1")
        for reason in ("conflict", "needs-label", "decision"):
            self.assertIn(f"forge-claim owner-action end --repo owner/repo --issue 1 --reason {reason}", close)

    def test_a_conflicting_resync_is_resolved_and_reviewed(self):
        result, calls, _ = run(replies={
            "land-sync-1-1": {"status": "done", "conflicted": True, "head": B, "merge_commit": B,
                              "resolved_files": ["x.py"], "tests": ["t"], "notes": "ok"},
            "land-checks-1-1": {"state": "passed", "head": B}})
        self.assertEqual(row(result, 1)["outcome"], "landed")
        self.assertIn("land-sync-review-1-1", labels(calls))
        ls = labels(calls)
        self.assertLess(ls.index("land-sync-review-1-1"), ls.index("land-record-1-1"))
        self.assertLess(ls.index("land-record-1-1"), ls.index("land-merge-1"))
        self.assertIn(f"--sha {B}", prompt(calls, "land-record-1-1"))
        self.assertIn(f"--sha {B}", prompt(calls, "land-merge-1"))
        self.assertNotIn("land-ask-1", labels(calls))
        self.assertIn(f"--match-head-commit {B}", prompt(calls, "land-merge-1"))

    def test_a_rejected_resolution_is_conflict_without_an_owner_action(self):
        result, calls, _ = run(replies={
            "land-sync-1-1": {"status": "done", "conflicted": True, "head": B, "merge_commit": B, "notes": "ok"},
            "land-sync-review-1-1": {"verdict": "findings", "findings": [{"severity": "important", "summary": "dropped a change"}]}})
        self.assertEqual(row(result, 1)["outcome"], "conflict")
        for label in ("land-ask-1", "release-1"):
            self.assertNotIn(label, labels(calls))
        ls = labels(calls)
        self.assertLess(ls.index("land-pr-1"), ls.index("land-sync-1-1"))
        self.assertEqual(ls.count("land-unlock-1"), 1)

    def test_a_second_conflict_aborts_and_posts_an_owner_action(self):
        result, calls, _ = run(args=dict(ARGS, unattended=True), replies={
            "land-sync-1-1": {"status": "done", "conflicted": True, "head": B, "merge_commit": B, "notes": "ok"},
            "land-checks-1-1": {"state": "behind", "head": B},
            "land-sync-1-2": {"status": "blocked", "conflicted": True, "head": B, "notes": "aborted"}})
        self.assertEqual(row(result, 1)["outcome"], "conflict")
        self.assertIn("land-record-1-1", labels(calls))
        self.assertNotIn("land-record-1-2", labels(calls))
        self.assertIn("git merge --abort", prompt(calls, "land-sync-1-2"))
        self.assertNotIn("land-sync-review-1-2", labels(calls))
        self.assertIn(f"--holder {HOLDER} --reason conflict --items-file", prompt(calls, "land-ask-1"))
        self.assertIn({"issue": 1, "reason": "conflict", "comment_id": 99}, result["owner_actions"])
        self.assertIn("land-unlock-1", labels(calls))

    def test_needs_label_posts_an_owner_action(self):
        result, calls, _ = run(args=dict(ARGS, unattended=True), replies={"land-checks-1-1": {"state": "needs_label", "head": SHA, "label": "raise-me", "failing": ["gate"]}})
        self.assertEqual((row(result, 1)["outcome"], row(result, 1)["label"]), ("needs-label", "raise-me"))
        text = prompt(calls, "land-ask-1")
        self.assertIn("--reason needs-label --items-file", text)
        self.assertIn("raise-me", text)
        self.assertIn({"issue": 1, "reason": "needs-label", "comment_id": 99}, result["owner_actions"])
        self.assertIn("land-unlock-1", labels(calls))
        self.assertNotIn("land-merge-1", labels(calls))

    SECOND_CONFLICT = {
        "land-sync-1-1": {"status": "done", "conflicted": True, "head": B, "merge_commit": B, "notes": "ok"},
        "land-checks-1-1": {"state": "behind", "head": B},
        "land-sync-1-2": {"status": "blocked", "conflicted": True, "head": B, "notes": "aborted"}}

    def test_a_session_landing_returns_its_owner_asks_and_posts_nothing(self):
        for replies, reason in ((self.SECOND_CONFLICT, "conflict"),
                                ({"land-checks-1-1": {"state": "needs_label", "head": SHA, "label": "raise-me",
                                                      "failing": ["gate"]}}, "needs-label")):
            with self.subTest(reason=reason):
                result, calls, _ = run(replies=replies)
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
        result, calls, _ = run(args=dict(ARGS, unattended=True), replies=self.SECOND_CONFLICT)
        self.assertIn("then relaunch the batch", prompt(calls, "land-ask-1"))

    def test_behind_three_times_is_contention(self):
        behind = {"state": "behind", "head": SHA}
        result, calls, _ = run(replies={f"land-checks-1-{k}": behind for k in (1, 2, 3)})
        self.assertEqual(row(result, 1)["outcome"], "land-contended")
        self.assertIn("land-sync-1-3", labels(calls))
        self.assertNotIn("land-sync-1-4", labels(calls))
        self.assertIn("land-unlock-1", labels(calls))

    def test_a_lock_retaken_before_the_merge_resyncs_first(self):
        retaken = [{"merged": False, "notes": "retaken", "lock": {"verdict": "acquired", "lock_sha": SHA}},
                   {"merged": True, "merge_commit": SHA, "notes": "merged"}]
        result, calls, _ = run(replies={"land-merge-1": retaken})
        # the resync answers current (no head change), so nothing is recorded
        self.assertEqual(row(result, 1)["outcome"], "landed")
        ls = of(calls, 1)
        self.assertEqual(ls[ls.index("land-merge-1"):ls.index("land-unlock-1")],
                         ["land-merge-1", "land-sync-1-2", "land-checks-1-2", "land-merge-1"])
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
                self.assertEqual((row(result, 1)["outcome"], row(result, 1)["stage"], row(result, 1)["detail"]),
                                 ("stopped", "renew", detail))
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
        _, calls, _ = run()
        checks = prompt(calls, "land-checks-1-1")
        for argv in ("gh pr checks 41 --repo owner/repo --json name,bucket,link",
                     "gh api repos/owner/repo/rules/branches/dev"):
            self.assertIn(argv, checks)
        schema = schema_of(calls, "land-checks-1-1")
        self.assertIn("pending", schema["properties"])
        self.assertIn("pending", schema["properties"]["state"]["enum"])

    def test_a_pending_non_required_check_is_waited_for_before_the_merge(self):
        result, calls, _ = run(replies={
            "land-checks-1-1": {"state": "passed", "head": SHA, "required": ["ci"], "passed": ["ci"], "pending": ["e2e"]},
            "land-checks-1-2": {"state": "passed", "head": SHA, "required": ["ci"], "passed": ["ci", "e2e"]}})
        self.assertEqual(row(result, 1)["outcome"], "landed")
        names = labels(calls)
        self.assertLess(names.index("land-checks-1-2"), names.index("land-merge-1"))
        self.assertNotIn("land-fix-1", names)

    def test_checks_still_pending_after_three_waits_stop_unmerged(self):
        waiting = {"state": "pending", "head": SHA, "pending": ["e2e"]}
        result, calls, _ = run(replies={f"land-checks-1-{k}": waiting for k in (1, 2, 3)})
        r = row(result, 1)
        self.assertEqual((r["outcome"], r["stage"], r["pending"]), ("stopped", "checks-pending", ["e2e"]))
        names = labels(calls)
        self.assertNotIn("land-merge-1", names)
        self.assertNotIn("land-checks-1-4", names)
        self.assertIn("land-unlock-1", names)

    def test_a_failing_non_required_check_in_a_passed_reply_is_never_merged(self):
        red = {"state": "passed", "head": SHA, "required": ["ci"], "passed": ["ci"], "failing": ["e2e"]}
        result, calls, _ = run(replies={"land-checks-1-1": red, "land-checks-1-2": dict(red, head=FIX)})
        self.assertEqual((row(result, 1)["outcome"], row(result, 1)["failing"]), ("ci-failed", ["e2e"]))
        self.assertIn("e2e", prompt(calls, "land-fix-1"))
        self.assertNotIn("land-merge-1", labels(calls))

    def test_an_explicit_failed_state_outranks_a_pending_list(self):
        red = {"state": "failed", "head": SHA, "pending": ["slow"], "details": "e2e failed"}
        result, calls, _ = run(replies={"land-checks-1-1": red, "land-checks-1-2": dict(red, head=FIX)})
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
        timeout = "a Bash timeout of 20 minutes (1200000 ms), and land acquire --wait 60 minutes (3600000 ms)"
        _, calls, _ = run()
        for label in ("acquire-1", "land-pr-1", "land-merge-1", "land-unlock-1"):
            with self.subTest(label=label):
                self.assertIn(timeout, prompt(calls, label))

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
    """#677: the land lock is taken, waiting, before the first resync, held through the merge,
    and the last held sha is released after it and on a stop."""

    MERGED = {"status": "done", "conflicted": False, "head": B, "merge_commit": B, "notes": "ok"}

    def test_the_lock_is_taken_with_wait_before_the_first_resync(self):
        result, calls, _ = run()
        self.assertEqual(row(result, 1)["outcome"], "landed")
        ls = labels(calls)
        self.assertLess(ls.index("land-pr-1"), ls.index("land-sync-1-1"))
        self.assertIn(f"forge-claim land acquire --repo owner/repo --branch dev --sha {SHA} --wait",
                      prompt(calls, "land-pr-1"))
        self.assertLess(ls.index("land-merge-1"), ls.index("land-unlock-1"))

    def test_a_waited_acquire_goes_on_to_the_resync(self):
        waited = {"verdict": "acquired", "lock_sha": SHA, "waited_s": 1800, "took_over": "idle"}
        result, calls, _ = run(replies={"land-pr-1": {"pr": 41, "head": SHA, "lock": waited}})
        self.assertEqual(row(result, 1)["outcome"], "landed")
        ls = labels(calls)
        self.assertEqual(ls[ls.index("land-pr-1") + 1], "land-sync-1-1")
        self.assertIn("--wait", prompt(calls, "land-pr-1"))

    def test_a_non_holding_wait_answer_gives_up_before_any_sync(self):
        for verdict in ("land-contended", "held_by", "lost_to"):
            with self.subTest(verdict=verdict):
                result, calls, _ = run(replies={"land-pr-1": {"pr": 41, "head": SHA,
                                                              "lock": {"verdict": verdict, "lock_sha": B, "by": "h2/b9"}}})
                self.assertEqual(row(result, 1)["outcome"], "land-contended")
                for label in ("land-sync-1-1", "land-checks-1-1", "land-merge-1", "land-unlock-1"):
                    self.assertNotIn(label, labels(calls))
                self.assertEqual(result["relaunch"]["conts"], {"1": ready(1)["cont"]})

    def test_a_first_resync_that_merges_pushes_and_moves_the_lock(self):
        result, calls, _ = run(replies={
            "land-sync-1-1": self.MERGED,
            "land-checks-1-1": {"state": "passed", "head": B, "required": ["ci"], "passed": ["ci"]}})
        self.assertEqual(row(result, 1)["outcome"], "landed")
        self.assertIn("After a merge you completed, push the result", prompt(calls, "land-sync-1-1"))
        ls = labels(calls)
        self.assertLess(ls.index("land-sync-1-1"), ls.index("land-record-1-1"))
        self.assertLess(ls.index("land-record-1-1"), ls.index("land-checks-1-1"))
        self.assertIn(f"--sha {B}\n", prompt(calls, "land-record-1-1"))
        self.assertNotIn(" --wait\n", prompt(calls, "land-record-1-1"))
        self.assertIn(f"forge-claim land release --repo owner/repo --branch dev --sha {B}",
                      prompt(calls, "land-unlock-1"))

    def test_a_failed_move_releases_the_last_held_sha(self):
        result, calls, _ = run(replies={"land-sync-1-1": self.MERGED,
                                        "land-record-1-1": {"ok": True, "head": B, "lock": {
                                            "verdict": "lost_to", "lock_sha": "c" * 40, "by": "h2/b9"}}})
        self.assertEqual(row(result, 1)["outcome"], "land-contended")
        ls = labels(calls)
        self.assertNotIn("land-checks-1-1", ls)
        self.assertEqual(ls.count("land-unlock-1"), 1)
        self.assertIn(f"forge-claim land release --repo owner/repo --branch dev --sha {SHA}\n",
                      prompt(calls, "land-unlock-1"))

    def test_a_stop_in_the_first_resync_releases_the_lock(self):
        result, calls, _ = run(replies={"land-sync-1-1": {"status": "blocked", "conflicted": False, "notes": "dirty"}})
        self.assertEqual((row(result, 1)["outcome"], row(result, 1)["stage"]), ("stopped", "land-sync"))
        ls = labels(calls)
        self.assertEqual(ls.count("land-unlock-1"), 1)
        self.assertLess(ls.index("land-pr-1"), ls.index("land-unlock-1"))


def blocked_by(*issues):
    return {"blockers": [{"issue": b, "state": "OPEN"} for b in issues]}


class DependencyTest(unittest.TestCase):
    def test_a_blocker_chain_releases_each_dependent_only_on_closed(self):
        result, calls, _ = run(args=dict(ARGS, issues=[1, 2, 3]),
                               patch={"facts-2": blocked_by(1), "facts-3": blocked_by(2)})
        ls = labels(calls)
        self.assertLess(ls.index("close-out-1"), ls.index("acquire-2"))
        self.assertLess(ls.index("close-out-2"), ls.index("acquire-3"))
        self.assertEqual([row(result, n)["outcome"] for n in (1, 2, 3)], ["landed"] * 3)

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
                               replies={"land-pr-1": {"pr": 41, "head": SHA, "lock": {"verdict": "land-contended"}}})
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
            self.assertEqual((row(result, n)["outcome"], row(result, n)["detail"]), ("blocked", "cycle"))
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
                           replies={"land-pr-3": {"pr": 43, "head": SHA, "lock": {"verdict": "land-contended"}}})
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
        first, _, _ = run(replies={
            "land-checks-1-1": {"state": "failed", "head": SHA, "failing": ["ci"]},
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
        first, _, _ = run(replies={"land-checks-1-1": {"state": "needs_label", "head": SHA, "label": "raise-me",
                                                       "failing": ["gate"]}})
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
                                          "detail": "issue-branch exited 1: forge_failed"})
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
        self.assertEqual(result["relaunch"], ARGS)

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
        self.assertEqual(first["relaunch"], ARGS)  # D9: the obsolete plan cont is not forwarded
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
        self.assertEqual(result["relaunch"], ARGS)

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
        for arg in ("repo_root", "batch_id", "child_script", "issues", "label", "decisions", "review_sizing"):
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
             "land-unlock-", "land-ask-", "land-record-", "land-pr-", "land-checks-", "land-merge-", "close-out-")),
    (IMPL, ("land-sync-", "land-fix-")),
    (REV, ("land-sync-review-", "land-fix-review-")),
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
     "replies": {"land-checks-1-1": {"state": "needs_label", "head": SHA, "label": "raise-me", "failing": ["gate"]}}},
    {"replies": {"land-checks-1-1": CI_RED, "land-record-1-1": {"ok": True, "head": FIX},
                 "land-checks-1-2": {"state": "passed", "head": FIX, "passed": ["ci"]}}},
    {"replies": {"land-sync-1-1": {"status": "done", "conflicted": True, "head": B, "merge_commit": B,
                                   "resolved_files": ["x.py"], "tests": ["t"], "notes": "ok"},
                 "land-checks-1-1": {"state": "passed", "head": B}}},
    {"patch": {"facts-1": dict(HELD, open_pr=OPEN_PR)}},
    {"args": dict(ARGS, conts={"1": {"setup": {}, "pr": 41}}),
     "patch": {"facts-1": dict(HELD, **landing(41))},
     "children": {"1": {"stage": "done", "pr": 41, "merged": True,
                        "acceptance": [{"id": "AC1", "text": "works", "kind": "code"}],
                        "close_out": {"issue_state": "CLOSED", "released": True}}}},
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
        _, calls, _ = run()
        self.assert_whole(prompt(calls, "land-sync-1-1"), "the files the merge changed against its first parent")

    def test_the_ci_fix_runs_whole_files_before_it_pushes(self):
        _, calls, _ = run(replies={
            "land-checks-1-1": {"state": "failed", "head": SHA, "failing": ["ci"]},
            "land-checks-1-2": {"state": "failed", "head": FIX, "failing": ["ci"]}})
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
                                                  "stage": "codex-unavailable", "detail": self.REASON})

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
                                          "dead_agents": ["final-codex"], "detail": nothing})

    def test_other_stops_keep_their_row(self):
        for c in ({"stage": "task", "details": "x", "cont": {"setup": {}}},
                  {"stage": "codex-unavailable", "step": "code", "cont": {"setup": {}}},
                  {"stage": "plan-review", "details": "the plan reviewer returned nothing",
                   "dead_agents": ["plan-review"], "cont": {"setup": {}}}):
            with self.subTest(stage=c["stage"]):
                result, _, _ = run(children={"1": c})
                self.assertNotIn("detail", row(result, 1))


if __name__ == "__main__":
    unittest.main()
