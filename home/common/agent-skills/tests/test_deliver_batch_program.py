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


def run(args=None, replies=None, patch=None, children=None):
    node = shutil.which("node")
    if node is None:
        raise AssertionError("node is not on PATH; the deliver-batch scenarios need it")
    scenario = {"args": ARGS if args is None else args, "replies": replies or {},
                "patch": patch or {}, "children": children or {}}
    done = subprocess.run([node, str(HARNESS), str(PROGRAM)], input=json.dumps(scenario),
                          capture_output=True, text=True, timeout=60, check=False)
    if done.returncode != 0:
        raise AssertionError(f"harness failed: {done.stderr}")
    out = json.loads(done.stdout)
    return out["result"], out["calls"], out["max_active"]


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
               dict(ARGS, decisions={"1": ""}), dict(ARGS, conts={"2": {"setup": {}}}),
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


class IntakeTest(unittest.TestCase):
    SKIPS = [({"state": "CLOSED"}, "closed"), ({"labels": ["needs-verification"]}, "needs-verification"),
             ({"labels": ["parked"]}, "parked"), ({"labels": ["agent:human-required"]}, "human-required"),
             ({"merged_pr": 5}, "duplicate"),
             ({"claim": {"verdict": "held_by", "by": "h2/b9"}}, "claimed-elsewhere"),
             ({"claim": {"verdict": "stale", "by": "h2/b9"}}, "stale-claim"),
             ({"blockers": [{"issue": 50, "state": "OPEN"}]}, "blocked")]

    def test_each_skip_is_decided_in_js_with_no_lane_agent_or_claim(self):
        for facts, outcome in self.SKIPS:
            with self.subTest(outcome=outcome):
                result, calls, _ = run(patch={"facts-1": facts})
                self.assertEqual(row(result, 1)["outcome"], outcome)
                self.assertEqual(labels(calls), ["setup", "facts-1"])

    def test_skip_rows_name_their_evidence(self):
        result, _, _ = run(patch={"facts-1": {"merged_pr": 5}})
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
                self.assertIn("lane-1", labels(calls))

    def test_a_blocker_inside_the_batch_does_not_skip_the_issue(self):
        _, calls, _ = run(args=dict(ARGS, issues=[1, 2]),
                          patch={"facts-1": {"blockers": [{"issue": 2, "state": "OPEN"}]}})
        self.assertIn("lane-1", labels(calls))

    def test_facts_agent_reads_claim_status_and_the_decision_marker(self):
        _, calls, _ = run()
        text = prompt(calls, "facts-1")
        self.assertIn(f"forge-claim status --repo owner/repo --issue 1 --holder {HOLDER}", text)
        self.assertIn("forge-claim owner-action status --repo owner/repo --issue 1 --reason decision", text)

    def test_every_facts_agent_runs_before_any_lane_agent(self):
        _, calls, _ = run(args=dict(ARGS, issues=[1, 2, 3]))
        ls = labels(calls)
        self.assertLess(max(ls.index(f"facts-{n}") for n in (1, 2, 3)),
                        min(ls.index(f"lane-{n}") for n in (1, 2, 3)))
        self.assertEqual([c["facts_pending"] for c in calls if c["label"].startswith("lane-")], [0, 0, 0])

    def test_needs_design_is_reported_and_not_claimed(self):
        result, calls, _ = run(replies={"lane-1": {"lane": "needs-design", "why": "no criteria"}})
        self.assertEqual(row(result, 1)["outcome"], "needs-design")
        self.assertNotIn("acquire-1", labels(calls))

    def test_lane_agent_reads_deliver_direct_eligibility(self):
        _, calls, _ = run()
        text = prompt(calls, "lane-1")
        self.assertIn("deliver-direct", text)
        self.assertIn("Eligibility", text)

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
        for arg in ("repo_root", "batch_id", "child_script", "issues", "label", "decisions"):
            self.assertIn(arg, meta)


if __name__ == "__main__":
    unittest.main()
