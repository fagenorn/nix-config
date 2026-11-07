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


QUESTION = {"stage": "plan", "needs_user": ["Which flag?"], "cont": {"setup": {}}}
OPEN = {"verdict": "open", "comment_id": 99, "items": ["Which flag?"], "replies": []}


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
        _, calls, _ = run(replies={"lane-1": {"lane": "direct", "why": "small"}})
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

    def test_a_child_that_lost_its_claim_is_claim_lost(self):
        result, _, _ = run(children={"1": {"stage": "claimed", "verdict": "held_by", "by": "h2/b9"}})
        self.assertEqual((row(result, 1)["outcome"], row(result, 1)["by"]), ("claim-lost", "h2/b9"))


class QuestionTest(unittest.TestCase):
    def test_questions_keep_the_claim_post_a_marker_and_return_grouped(self):
        result, calls, _ = run(args=dict(ARGS, issues=[1, 2, 3]),
                               children={"1": QUESTION, "3": dict(QUESTION, needs_user=["Which host?", "Why?"])})
        self.assertEqual(result["questions"], [{"issue": 1, "questions": ["Which flag?"], "marker": 99},
                                               {"issue": 3, "questions": ["Which host?", "Why?"], "marker": 99}])
        self.assertEqual([row(result, n)["outcome"] for n in (1, 3)], ["questions", "questions"])
        self.assertIn("child-2", labels(calls))
        self.assertNotIn("release-1", labels(calls))
        text = prompt(calls, "ask-1")
        self.assertIn(f"forge-claim owner-action post --repo owner/repo --issue 1 --holder {HOLDER} "
                      "--reason decision --items-file", text)
        self.assertIn("Which flag?", text)
        self.assertEqual(result["owner_actions"], [{"issue": 1, "reason": "decision", "comment_id": 99},
                                                   {"issue": 3, "reason": "decision", "comment_id": 99}])
        self.assertIn(1, result["relaunch"]["issues"])
        self.assertIn(3, result["relaunch"]["issues"])

    def test_open_questions_without_answers_wait_without_lane_claim_or_child(self):
        result, calls, _ = run(patch={"facts-1": {"claim": {"verdict": "held_by", "by": HOLDER}, "decision": OPEN}})
        self.assertEqual(row(result, 1)["outcome"], "questions")
        self.assertEqual(result["questions"], [{"issue": 1, "questions": ["Which flag?"], "marker": 99}])
        self.assertEqual(labels(calls), ["setup", "facts-1"])

    def test_relaunch_decisions_end_the_marker_and_reach_the_child(self):
        _, calls, _ = run(args=dict(ARGS, decisions={"1": "Use the flag."}), patch={"facts-1": {"decision": OPEN}})
        self.assertEqual(child(calls, 1)["args"]["decisions"], "Use the flag.")
        self.assertIn("forge-claim owner-action end --repo owner/repo --issue 1 --reason decision",
                      prompt(calls, "answered-1"))
        ls = labels(calls)
        self.assertLess(ls.index("acquire-1"), ls.index("answered-1"))
        self.assertLess(ls.index("answered-1"), ls.index("child-1"))

    def test_an_owner_reply_on_the_issue_answers_the_questions(self):
        answered = dict(OPEN, verdict="answered",
                        replies=[{"comment_id": 120, "author": "owner", "body": "Use the flag."}])
        _, calls, _ = run(patch={"facts-1": {"decision": answered}})
        self.assertIn("Use the flag.", child(calls, 1)["args"]["decisions"])
        self.assertIn("answered-1", labels(calls))

    def test_no_decisions_key_without_an_answer(self):
        _, calls, _ = run()
        self.assertNotIn("decisions", child(calls, 1)["args"])
        self.assertNotIn("answered-1", labels(calls))


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
        result, _, _ = run(args=dict(ARGS, issues=[1, 2], decisions={"2": "x"}), replies={"lane-1": None})
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
        self.assertNotIn("lane-1", labels(calls))
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
