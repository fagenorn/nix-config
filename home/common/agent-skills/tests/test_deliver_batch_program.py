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

    def test_a_tracker_answer_survives_a_child_that_fails_after_the_marker_ended(self):
        answered = dict(OPEN, verdict="answered",
                        replies=[{"comment_id": 120, "author": "owner", "body": "Use the flag."}])
        held = {"claim": {"verdict": "held_by", "by": HOLDER}}
        args = dict(ARGS, conts={"1": {"setup": {}}})
        for child_result in ("throw", {"stage": "plan-review", "dead_agents": ["plan-review"], "cont": {"setup": {}}}):
            with self.subTest(child=child_result):
                first, calls, _ = run(args=args, patch={"facts-1": dict(held, decision=answered)},
                                      children={"1": child_result})
                self.assertIn("answered-1", labels(calls))
                self.assertEqual(first["relaunch"]["decisions"], {"1": "Use the flag."})
                # The marker is ended now: the tracker shows no replies, so only the relaunch holds the answer.
                _, calls, _ = run(args=first["relaunch"], patch={"facts-1": dict(held, decision={
                    "verdict": "none", "comment_id": None, "items": [], "replies": []})})
                self.assertEqual(child(calls, 1)["args"]["decisions"], "Use the flag.")

    def test_a_child_that_asks_again_does_not_carry_the_consumed_answer(self):
        answered = dict(OPEN, verdict="answered",
                        replies=[{"comment_id": 120, "author": "owner", "body": "Use the flag."}])
        result, _, _ = run(args=dict(ARGS, conts={"1": {"setup": {}}}), patch={"facts-1": {"decision": answered}},
                           children={"1": QUESTION})
        self.assertEqual(row(result, 1)["outcome"], "questions")
        self.assertNotIn("decisions", result["relaunch"])

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


B = "b" * 40
FIX = "c0ffee"
HAPPY = ["facts-1", "lane-1", "acquire-1", "child-1", "renew-1-land", "land-sync-1-1", "land-pr-1",
         "land-lock-1-1", "land-checks-1-1", "renew-1-merge", "land-lock-1-2", "land-merge-1",
         "land-unlock-1", "close-out-1"]


def ready(n, acceptance=None, head=SHA):
    return {"stage": "ready", "head": head, "branch": f"issue-{n}-x", "worktree": f"/r/.wt/w-issue-{n}-x",
            "verify": [{"id": "build", "status": "pass", "summary": "ok"}], "tasks": [{"n": 1}],
            "acceptance": acceptance or [{"id": "AC1", "text": "works", "kind": "code"}], "fix_waves": 0,
            "cont": {"setup": {"holder": HOLDER, "branch": f"issue-{n}-x", "worktree": f"/r/.wt/w-issue-{n}-x"}}}


class LandTest(unittest.TestCase):
    def test_happy_landing_runs_every_step_in_order(self):
        result, calls, _ = run()
        self.assertEqual((row(result, 1)["outcome"], row(result, 1)["pr"]), ("landed", 41))
        self.assertEqual(of(calls, 1), HAPPY)
        self.assertIsNone(result["relaunch"])

    def test_landing_commands_are_exact(self):
        _, calls, _ = run()
        self.assertIn(f"forge-claim renew --repo owner/repo --issue 1 --holder {HOLDER} --branch issue-1-x",
                      prompt(calls, "renew-1-land"))
        self.assertIn(f"forge-claim land acquire --repo owner/repo --branch dev --sha {SHA} --wait",
                      prompt(calls, "land-lock-1-1"))
        self.assertIn(f"forge-claim land acquire --repo owner/repo --branch dev --sha {SHA}", prompt(calls, "land-lock-1-2"))
        self.assertNotIn("--wait", prompt(calls, "land-lock-1-2"))
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
        result, calls, _ = run(replies={"land-lock-1-1": {"verdict": "land-contended", "lock_sha": B}})
        self.assertEqual(row(result, 1)["outcome"], "land-contended")
        for label in ("land-checks-1-1", "land-merge-1", "land-unlock-1", "release-1", "close-out-1"):
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
        self.assertIn(f"--sha {FIX}", prompt(calls, "land-lock-1-2"))
        self.assertIn(f"--match-head-commit {FIX}", prompt(calls, "land-merge-1"))
        ls = labels(calls)
        self.assertLess(ls.index("land-fix-review-1"), ls.index("land-record-1-1"))
        self.assertLess(ls.index("land-record-1-1"), ls.index("land-lock-1-2"))
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
        for reason in ("conflict", "needs-label"):
            self.assertIn(f"forge-claim owner-action end --repo owner/repo --issue 1 --reason {reason}", close)

    def test_a_conflicting_resync_is_resolved_and_reviewed(self):
        result, calls, _ = run(replies={
            "land-sync-1-1": {"status": "done", "conflicted": True, "head": B, "merge_commit": B,
                              "resolved_files": ["x.py"], "tests": ["t"], "notes": "ok"},
            "land-pr-1": {"pr": 41, "head": B}, "land-checks-1-1": {"state": "passed", "head": B}})
        self.assertEqual(row(result, 1)["outcome"], "landed")
        self.assertIn("land-sync-review-1-1", labels(calls))
        self.assertNotIn("land-ask-1", labels(calls))
        self.assertIn(f"--match-head-commit {B}", prompt(calls, "land-merge-1"))

    def test_a_rejected_resolution_is_conflict_without_an_owner_action(self):
        result, calls, _ = run(replies={
            "land-sync-1-1": {"status": "done", "conflicted": True, "head": B, "merge_commit": B, "notes": "ok"},
            "land-sync-review-1-1": {"verdict": "findings", "findings": [{"severity": "important", "summary": "dropped a change"}]}})
        self.assertEqual(row(result, 1)["outcome"], "conflict")
        for label in ("land-ask-1", "land-pr-1", "release-1"):
            self.assertNotIn(label, labels(calls))

    def test_a_second_conflict_aborts_and_posts_an_owner_action(self):
        result, calls, _ = run(replies={
            "land-sync-1-1": {"status": "done", "conflicted": True, "head": B, "merge_commit": B, "notes": "ok"},
            "land-pr-1": {"pr": 41, "head": B},
            "land-checks-1-1": {"state": "behind", "head": B},
            "land-sync-1-2": {"status": "blocked", "conflicted": True, "head": B, "notes": "aborted"}})
        self.assertEqual(row(result, 1)["outcome"], "conflict")
        self.assertNotIn("land-record-1-1", labels(calls))
        self.assertIn("git merge --abort", prompt(calls, "land-sync-1-2"))
        self.assertNotIn("land-sync-review-1-2", labels(calls))
        self.assertIn(f"--holder {HOLDER} --reason conflict --items-file", prompt(calls, "land-ask-1"))
        self.assertIn({"issue": 1, "reason": "conflict", "comment_id": 99}, result["owner_actions"])
        self.assertIn("land-unlock-1", labels(calls))

    def test_needs_label_posts_an_owner_action(self):
        result, calls, _ = run(replies={"land-checks-1-1": {"state": "needs_label", "head": SHA, "label": "raise-me", "failing": ["gate"]}})
        self.assertEqual((row(result, 1)["outcome"], row(result, 1)["label"]), ("needs-label", "raise-me"))
        text = prompt(calls, "land-ask-1")
        self.assertIn("--reason needs-label --items-file", text)
        self.assertIn("raise-me", text)
        self.assertIn({"issue": 1, "reason": "needs-label", "comment_id": 99}, result["owner_actions"])
        self.assertIn("land-unlock-1", labels(calls))
        self.assertNotIn("land-merge-1", labels(calls))

    def test_behind_three_times_is_contention(self):
        behind = {"state": "behind", "head": SHA}
        result, calls, _ = run(replies={f"land-checks-1-{k}": behind for k in (1, 2, 3)})
        self.assertEqual(row(result, 1)["outcome"], "land-contended")
        self.assertIn("land-sync-1-3", labels(calls))
        self.assertNotIn("land-sync-1-4", labels(calls))
        self.assertIn("land-unlock-1", labels(calls))

    def test_a_lock_retaken_before_the_merge_resyncs_first(self):
        result, calls, _ = run(replies={"land-lock-1-2": {"verdict": "acquired", "lock_sha": SHA}})
        # the resync answers current (no head change), so nothing is recorded
        self.assertEqual(row(result, 1)["outcome"], "landed")
        ls = labels(calls)
        self.assertLess(ls.index("land-lock-1-2"), ls.index("land-sync-1-2"))
        self.assertLess(ls.index("land-sync-1-2"), ls.index("land-merge-1"))

    def test_a_lost_claim_stops_the_landing_before_the_pr(self):
        result, calls, _ = run(replies={"renew-1-land": {"verdict": "not_held", "by": "h2/b9"}})
        self.assertEqual(row(result, 1)["outcome"], "claim-lost")
        self.assertNotIn("land-pr-1", labels(calls))

    def test_a_pushed_head_other_than_the_ready_head_stops(self):
        result, calls, _ = run(replies={"land-pr-1": {"pr": 41, "head": B}})
        self.assertEqual((row(result, 1)["outcome"], row(result, 1)["stage"]), ("stopped", "head-moved"))
        self.assertNotIn("land-lock-1-1", labels(calls))

    def test_an_unmerged_pr_unlocks_and_stops(self):
        result, calls, _ = run(replies={"land-merge-1": {"merged": False, "notes": "head mismatch"}})
        self.assertEqual((row(result, 1)["outcome"], row(result, 1)["stage"]), ("stopped", "merge"))
        self.assertIn("land-unlock-1", labels(calls))
        self.assertNotIn("close-out-1", labels(calls))

    def test_non_code_criteria_hold_the_issue_open(self):
        acceptance = [{"id": "AC1", "text": "works", "kind": "code"}, {"id": "AC2", "text": "live", "kind": "evidence"}]
        result, calls, _ = run(children={"1": ready(1, acceptance)},
                               replies={"close-out-1": {"issue_state": "OPEN", "released": True, "notes": "held"}})
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
                               patch={"facts-1": {"merged_pr": 41, "claim": {"verdict": "held_by", "by": HOLDER}}},
                               children={"1": done})
        self.assertEqual((row(second, 1)["outcome"], row(second, 1)["pr"]), ("landed", 41))
        self.assertIsNone(second["relaunch"])
        self.assertEqual(child(calls, 1)["args"]["cont"], relaunch["conts"]["1"])
        end = prompt(calls, "recover-end-1")
        for reason in ("conflict", "needs-label"):
            self.assertIn(f"forge-claim owner-action end --repo owner/repo --issue 1 --reason {reason}", end)
        self.assertNotIn("land-pr-1", labels(calls))

    def test_a_relaunched_merged_landing_with_open_criteria_is_held(self):
        cont = {"setup": {"holder": HOLDER, "branch": "issue-1-x", "worktree": "/r/.wt/w-issue-1-x"}}
        done = {"stage": "done", "pr": 41, "merged": True, "acceptance": [{"id": "AC2", "text": "live", "kind": "evidence"}]}
        result, _, _ = run(args=dict(ARGS, conts={"1": cont}),
                           patch={"facts-1": {"merged_pr": 41, "claim": {"verdict": "held_by", "by": HOLDER}}},
                           children={"1": done})
        self.assertEqual(row(result, 1)["outcome"], "landed-held")

    def test_a_merged_pr_without_a_forwarded_cont_stays_a_duplicate(self):
        result, calls, _ = run(patch={"facts-1": {"merged_pr": 41, "claim": {"verdict": "held_by", "by": HOLDER}}})
        self.assertEqual(row(result, 1)["outcome"], "duplicate")
        self.assertEqual(labels(calls), ["setup", "facts-1"])

    def test_a_close_out_that_leaves_the_wrong_state_is_stopped(self):
        result, _, _ = run(replies={"close-out-1": {"issue_state": "OPEN", "released": True, "notes": "x"}})
        self.assertEqual((row(result, 1)["outcome"], row(result, 1)["stage"]), ("stopped", "close-out"))


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
                               replies={"close-out-1": {"issue_state": "OPEN", "released": True, "notes": "held"}})
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
                               replies={"land-lock-1-1": {"verdict": "land-contended"}})
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
            self.assertNotIn(f"lane-{n}", labels(calls))
        self.assertEqual(row(result, 3)["outcome"], "landed")

    def test_a_waiting_dependent_holds_no_slot(self):
        result, _, active = run(args=dict(ARGS, issues=[1, 2, 3]), patch={"setup": {"max_parallel": 1},
                                                                       "facts-1": blocked_by(3)})
        self.assertEqual([row(result, n)["outcome"] for n in (1, 2, 3)], ["landed"] * 3)
        self.assertEqual(active, 1)


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
