"""Scenario tests for the shipped `deliver` procedure on the fixture project.

Each case runs `engine deliver` as a child process against a built fixture project, a fake tracker
and a stubbed launcher (`tests/engine_stubbed_world.py`), and reads what the run left.
"""

from __future__ import annotations

import ast
import io
import json
import os
import shutil
import subprocess
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

from agent_tools.claims import forge_markers
from agent_tools.delivery import engine_session, holding
from agent_tools.delivery.review_findings import Round, dispositions
from agent_tools.project_contract import resolve_project
from agent_tools.verification import verify_block
from tests.engine_fixture import AdoptedFixtures, FixtureProject
from tests.engine_guards import payloads
from tests.engine_procedure_copies import (PROCEDURES, keeping_the_run, stopping_after_verify,
                                           unstructured_procedures)
from tests.engine_step_coverage import StepCoverage, test_ids
from tests.engine_stubbed_world import (CLEAN_LITE, EVIDENCE_BODY, EVIDENCE_CHECK, GREEN, IMPLEMENTED, NOT_BEFORE,
                                        ROLES, StubbedRun, drafted)
from tests.engine_verify_fixtures import (ATTESTED, FORMAT, FOUR, PASS_ATTESTED, RETESTED, TWO_SPACES, fixing,
                                          implementing)
from tests.guard_policy_world import REAL_GIT, install_platform_manifest_in_environ

TIER = "integration"  # every case builds a repository and runs the engine as a child process

FIXTURES = AdoptedFixtures()


def setUpModule() -> None:
    install_platform_manifest_in_environ()
    unittest.addModuleCleanup(FIXTURES.close)


def tearDownModule() -> None:
    STEPS.finish(sys.modules[__name__], Scenario)

STEPS = StepCoverage(PROCEDURES)
LOOK_BODY = ("Add a greet() function.\n\n## Acceptance criteria\n\n"
             "- [ ] [human] before merge: the greeting text — measured: the owner, on the pull request\n")
SETUP_WALK = [("contract", "ok"), ("review", "clear"), ("preflight", "clear"), ("existing", "absent"),
              ("applies", "applies"), ("acquire", "acquired"), ("worktree", "made"), ("look", "unmarked")]


FINDING = {"severity": "important", "file": "fixture/farewell.py:2", "failing_input": "farewell('')",
           "summary": "s", "kind": "other"}
UNNAMED_LITE = dict(CLEAN_LITE, verdict="findings",
                    findings=[{"severity": "important", "file": "", "failing_input": "", "summary": "s", "kind": "other"}])
CLEAN_FULL = {key: value for key, value in CLEAN_LITE.items() if key != "escalate"}
CLEAN_REREVIEW = {"verdict": "pass", "findings": []}
KEPT = ('import unittest\n\nfrom fixture.greet import greet\n\n\nclass KeptCheck(unittest.TestCase):\n'
        '    def test_greet_still_greets(self):\n        self.assertEqual(greet("Ada"), "Hello, Ada.")\n')
KEPT_ID = "checks.check_kept.KeptCheck.test_greet_still_greets"
SECOND = ('import unittest\n\n\nclass SecondCheck(unittest.TestCase):\n'
          '    def test_second_runs(self):\n        self.assertTrue(True)\n')
SECOND_ID = "checks.check_second.SecondCheck.test_second_runs"
SHA = "a" * 40
SYNCED = {"reply": {"status": "done", "notes": "n", "tests": ["checks/check_greet.py"]}, "merge": {}}
CONFLICTED = {"reply": {"status": "conflicted", "notes": "n", "tests": []}, "merge": {}}
RESOLVED_TEXT = IMPLEMENTED["commit"]["text"] + "OTHER = 1\n"
RESOLVED = {"reply": {"status": "done", "notes": "n", "tests": ["checks/check_greet.py"]},
            "merge": {"resolve": {"fixture/farewell.py": RESOLVED_TEXT}}}
UPSTREAM_IMPLEMENTED = {**IMPLEMENTED, "upstream": {"path": "fixture/farewell.py", "text": "OTHER = 1\n"}}
CONFLICTING_MAIN = {"path": "fixture/farewell.py", "text": "OTHER = 1\n"}
CODEX_LIMIT = {"stdout": json.dumps({"status": 1, "error": "You've hit your usage limit."}), "exit": 1}


def lite_findings(**members) -> dict:
    return dict(CLEAN_LITE, verdict="findings", findings=[FINDING], **members)


def full_findings() -> dict:
    return dict(CLEAN_FULL, verdict="findings", findings=[FINDING])


def committing(path: str, text: str, **reply) -> dict:
    """A fix reply that commits `text` to `path`: the stub reports the commit it made."""
    return {"reply": {"status": "done", "notes": "n", "tests": [], "declines": [], **reply},
            "commit": {"path": path, "text": text}}


def model_of(launch: dict) -> str:
    return launch["argv"][launch["argv"].index("--model") + 1]


class Scenario(unittest.TestCase):
    def run(self, result=None):
        # the runner runs only the tests it selected: select on the coverage of the test's own module
        sys.modules[type(self).__module__].STEPS.select(self.id())
        return super().run(result)

    def stubbed(self, **members) -> StubbedRun:
        module = sys.modules[type(self).__module__]
        run = StubbedRun(test_case=self, fixtures=module.FIXTURES, **members)
        self.addCleanup(lambda: module.STEPS.record(run.visited_steps()))
        return run

    def branch_here(self, run: StubbedRun, path: Path) -> str:
        return run.world.git(path, "branch", "--show-current").strip()

    def branches(self, run: StubbedRun) -> str:
        return run.world.git(run.fixture.root, "branch", "--list", run.branch).strip()

    def stopped(self, run: StubbedRun, done: subprocess.CompletedProcess, end: str, need: str) -> dict:
        self.assertEqual(done.returncode, 3, done.stdout + done.stderr)
        line = run.line(done)
        self.assertEqual((line["end"], line["need"]), (end, need), line)
        return line

    def child(self, run: StubbedRun, procedure: str, last: bool = False) -> Path:
        """The child run of the root that runs `procedure` (the latest one with `last`)."""
        named = [child for child in run.children(run.runs()[0])
                 if json.loads((child / "run.json").read_text("utf-8"))["procedure"] == procedure]
        return named[-1] if last else named[0]

    def stored(self, run_dir: Path, step: str, visit: int = 1) -> dict:
        """The result the step's visit stored, read from the file its `result_stored` event names."""
        event = next(e for e in StubbedRun.events(run_dir)
                     if e["event"] == "result_stored" and (e["step"], e["visit"]) == (step, visit))
        return json.loads((run_dir / event["result"]).read_text("utf-8"))

    def live_owner_actions(self, run: StubbedRun) -> list:
        markers = [m for m in (forge_markers.parse(c) for c in run.forge.stored()) if m is not None]
        return forge_markers.contest(markers, "owner-action", {})

    def released_claims(self, run: StubbedRun) -> list:
        markers = (forge_markers.parse(comment) for comment in run.forge.stored())
        return [m for m in markers if m is not None and m.kind == "claim" and "released" in m.fields]

    def keys(self, run: StubbedRun) -> list[str]:
        return [launch["key"] for launch in run.launches()]

    def launch(self, run: StubbedRun, step: str) -> dict:
        return next(launch for launch in run.launches() if launch["key"] == step)

    def branch_commits(self, run: StubbedRun) -> list[str]:
        return run.world.git(run.worktree_path, "log", "--format=%H", f"origin/main..{run.branch}").split()

    def finish(self, run: StubbedRun, end: str, need: str | None = None) -> dict:
        """Run the delivery and check its end; an end that is a stop is checked with its need."""
        done = run.deliver()
        if need is None:
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
            self.assertEqual(run.line(done)["end"], end)
            return run.line(done)
        return self.stopped(run, done, end, need)


class StubbedRunTest(Scenario):
    def test_a_stubbed_delivery_lands_a_merged_pull_request_and_closes_the_issue(self):
        run = self.stubbed()

        done = run.deliver()

        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(run.line(done)["end"], "done")
        self.assertLessEqual({"contract", "implement", "merge-pr", "close", "closing"}, run.visited())
        root = run.runs()[0]
        setup = run.children(root)[0]
        self.assertEqual(run.transitions(setup), SETUP_WALK)
        renewals = [e for e in run.events(setup) if e["event"] == "keep_alive_ran"]
        self.assertEqual([(e["step"], e["verdict"]) for e in renewals], [("worktree", "renewed")])
        self.assertEqual(run.transitions(root), [("start", "done"), ("issue", "read"), ("lane", "direct"),
                                                 ("direct-lane", "done"), ("verification", "done"),
                                                 ("landing", "done"), ("closing", "done")])
        direct = self.child(run, "direct")
        transitions = run.transitions(direct)
        for edge in (("implement", "done"), ("implemented", "lite"), ("lite-group", "pass"),
                     ("lite-tally", "clean")):
            self.assertIn(edge, transitions)
        renewed = [e for e in run.events(direct) if e["event"] == "keep_alive_ran" and e["step"] == "implement"]
        self.assertEqual([e["verdict"] for e in renewed], ["renewed"])
        commit = self.stored(direct, "implement")["commit"]
        checks = self.stored(self.child(run, "verify"), "checks")
        self.assertEqual((checks["verdict"], checks["clean"]), ("passed", True))
        self.assertEqual([r["id"] for r in checks["results"]], FixtureProject.VERIFICATION)
        self.assertEqual([r["status"] for r in checks["results"]], ["pass", "pass"])
        launches = run.launches()
        self.assertIn(run.title, launches[1]["prompt"])
        self.assertEqual(model_of(self.launch(run, "implement")), "sonnet")
        self.assertEqual(self.keys(run), ["applies", "implement", "lite-review"])
        pulls = run.pulls()
        self.assertEqual(len(pulls), 1)
        self.assertEqual(pulls[0]["state"], "MERGED")
        self.assertTrue(pulls[0]["body"].startswith("Closes #41."), pulls[0]["body"])
        merge = pulls[0]["mergeCommit"]["oid"]
        self.assertEqual(run.origin_tip("main"), merge)
        contains = subprocess.run([REAL_GIT, "-C", run.bare, "merge-base", "--is-ancestor", commit, merge],
                                  check=False)
        self.assertEqual(contains.returncode, 0)
        self.assertEqual(run.forge.issue()["state"], "closed")
        self.assertEqual(run.claims(), [])
        self.assertEqual(self.live_owner_actions(run), [])
        self.assertEqual(run.lock_refs(), {})
        self.assertFalse(run.worktree_path.exists())
        self.assertEqual(self.branches(run), "")
        self.assertIsNone(run.origin_tip(run.branch))
        self.assertEqual(run.world.git(run.fixture.root, "rev-parse", "main").strip(), run.origin_tip("main"))


class LaneTest(Scenario):
    OVER_THE_RULE = "Add greet().\n\n## Acceptance criteria\n\n" + "".join(f"- [ ] c{i}\n" for i in range(4))

    def test_a_body_over_the_rule_stops_at_standard_not_on_engine_with_no_lane_agent(self):
        run = self.stubbed(body=self.OVER_THE_RULE)

        done = run.deliver()

        self.stopped(run, done, "standard-not-on-engine", "nothing")
        self.assertIn(("lane", "standard"), run.transitions(run.runs()[0]))
        self.assertEqual(self.keys(run), ["applies"])
        self.assertEqual(len(run.claims()), 1)
        self.assertEqual(self.branch_here(run, run.worktree_path), run.branch)

    def test_a_body_naming_a_lane_path_stops_at_standard_not_on_engine(self):
        run = self.stubbed(body="Fix `secrets/x.yaml`.\n\n## Acceptance criteria\n\n- [ ] c\n")

        self.stopped(run, run.deliver(), "standard-not-on-engine", "nothing")

        self.assertEqual(self.keys(run), ["applies"])

    def test_a_continued_standard_stop_reads_the_issue_again(self):
        # The behaviour, not the stop's `reenter` value: the live `start` step is stale on every continue and is
        # re-entered first, so only test_engine_check's structural assertion on the three stops pins `reenter`.
        run = self.stubbed(body=self.OVER_THE_RULE)
        self.stopped(run, run.deliver(), "standard-not-on-engine", "nothing")

        self.stopped(run, run.deliver(), "standard-not-on-engine", "nothing")

        self.assertEqual(len(run.runs()), 1)
        events = run.events(run.runs()[0])
        self.assertEqual([e["event"] for e in events].count("run_continued"), 1)
        self.assertEqual(len([e for e in events if e["event"] == "step_entered" and e.get("step") == "issue"]), 2)

    def test_an_issue_with_a_look_marker_stops_at_look_not_on_engine_and_never_asks_the_lane(self):
        run = self.stubbed(body=LOOK_BODY)

        self.stopped(run, run.deliver(), "look-not-on-engine", "nothing")

        self.assertEqual(run.transitions(self.child(run, "setup"))[-1], ("look", "marked"))
        self.assertEqual(self.keys(run), ["applies"])

    def test_a_continued_run_reattaches_a_worktree_left_on_a_clean_detached_head_at_the_tip(self):
        run = self.stubbed(body=LOOK_BODY)
        self.stopped(run, run.deliver(), "look-not-on-engine", "nothing")
        run.world.git(run.worktree_path, "checkout", "--detach")
        self.assertEqual(self.branch_here(run, run.worktree_path), "")

        self.stopped(run, run.deliver(), "look-not-on-engine", "nothing")

        self.assertEqual(self.branch_here(run, run.worktree_path), run.branch)


class RefusalTest(Scenario):
    def nothing_started(self, run: StubbedRun) -> None:
        self.assertEqual(run.claims(), [])
        self.assertFalse(run.worktree_path.exists())
        self.assertEqual(self.branches(run), "")

    def test_a_procedure_that_fails_the_check_is_refused_before_its_first_step_with_the_validator_unimportable(self):
        run = self.stubbed()
        copy = run.tmp / "unchecked-procedures"
        shutil.copytree(PROCEDURES, copy)
        deliver = json.loads((copy / "deliver.json").read_text(encoding="utf-8"))
        next(item for item in deliver["steps"] if item["id"] == "issue")["stage"] = "testing"
        (copy / "deliver.json").write_text(json.dumps(deliver, indent=2) + "\n", encoding="utf-8")

        blocked = run.deliver(copy, validator_unimportable=True)

        self.assertEqual((blocked.returncode, blocked.stderr), (2, ""))
        self.assertEqual(json.loads(blocked.stdout), {"breaches": [], "refusals": [{
            "defect": "unknown_stage", "detail": "stage 'testing' is not one of the ten stages.",
            "procedure": "deliver", "step": "issue"}], "verdict": "refused"})
        self.assertEqual(run.runs(), [])
        self.assertEqual(run.launches(), [])
        self.assertEqual(run.claims(), [])

    def test_setup_refuses_a_closed_issue_and_makes_no_worktree(self):
        run = self.stubbed(state="closed")

        self.stopped(run, run.deliver(), "setup", "owner-decision")

        self.assertEqual(run.transitions(self.child(run, "setup"))[-1], ("preflight", "closed"))
        self.nothing_started(run)
        self.assertEqual(run.launches(), [])

    def test_setup_refuses_an_issue_with_an_open_pull_request_and_makes_no_worktree(self):
        pull = {"number": 12, "state": "OPEN", "headRefName": "someone-else", "closingIssuesReferences": []}
        run = self.stubbed(pulls=[pull])

        self.stopped(run, run.deliver(), "setup", "owner-decision")

        self.assertEqual(run.transitions(self.child(run, "setup"))[-1], ("preflight", "open-pr"))
        self.nothing_started(run)

    def test_setup_refuses_an_issue_that_no_longer_applies_comments_the_evidence_and_makes_no_worktree(self):
        evidence = "greet() already returns the greeting at origin/main."
        gone = {"verdict": "no-longer-applies", "details": "d", "evidence": evidence}
        run = self.stubbed(replies={"applies": gone})

        self.stopped(run, run.deliver(), "setup", "owner-decision")

        transitions = run.transitions(self.child(run, "setup"))
        self.assertIn(("applies", "no-longer-applies"), transitions)
        self.assertEqual(transitions[transitions.index(("applies", "no-longer-applies")) + 1],
                         ("note", "posted"))
        self.assertIn(evidence, [comment["body"] for comment in run.forge.stored()])
        self.nothing_started(run)

    def test_a_worktree_path_on_another_branch_stops_at_setup_and_takes_no_claim(self):
        run = self.stubbed()
        run.world.git(run.fixture.root, "worktree", "add", "--no-track", "-b", "other",
                      str(run.worktree_path), "origin/main")

        self.stopped(run, run.deliver(), "setup", "owner-decision")

        transitions = run.transitions(self.child(run, "setup"))
        self.assertEqual(transitions[-1], ("existing", "mismatch"))
        self.assertNotIn("acquire", [step for step, _ in transitions])
        self.assertEqual(run.claims(), [])
        self.assertEqual(run.forge.stored(), [])
        self.assertEqual(self.branch_here(run, run.worktree_path), "other")
        self.assertEqual(run.launches(), [])


class ClaimTest(Scenario):
    def test_a_claim_held_by_another_holder_stops_at_claimed(self):
        other = "other-host/41-20261101T000000Z-abcd"
        clock = "2026-11-06T10:00:00Z"
        held = {"id": 5, "created_at": clock, "updated_at": clock,
                "body": forge_markers.render("claim", {"issue": "41", "holder": other},
                                             f"Claimed by {other}.")}
        run = self.stubbed(comments=[held])

        self.stopped(run, run.deliver(), "claimed", "owner-decision")

        self.assertEqual(run.transitions(self.child(run, "setup"))[-1], ("acquire", "held_by"))
        self.assertEqual([claim.fields["holder"] for claim in run.claims()], [other])
        self.assertFalse(run.worktree_path.exists())

    def test_a_dirty_adopted_worktree_stops_at_dirty_and_keeps_the_change(self):
        run = self.stubbed()
        run.world.git(run.fixture.root, "worktree", "add", "--no-track", "-b", run.branch,
                      str(run.worktree_path), "origin/main")
        (run.worktree_path / "scratch.txt").write_text("keep\n", encoding="utf-8")

        self.stopped(run, run.deliver(), "dirty", "owner-decision")

        transitions = run.transitions(self.child(run, "setup"))
        self.assertEqual(transitions[transitions.index(("existing", "dirty")) + 1:][-1:],
                         [("worktree", "dirty")])
        self.assertTrue((run.worktree_path / "scratch.txt").exists())
        root = run.runs()[0]
        holder = f"{json.loads((root / 'run.json').read_text())['host']}/{root.name}"
        self.assertEqual([claim.fields["holder"] for claim in run.claims()], [holder])

    def test_an_incomplete_claim_stops_at_claim_and_a_continued_run_completes_it(self):
        run = self.stubbed()
        run.worktree_path.parent.mkdir(parents=True, exist_ok=True)
        run.worktree_path.write_text("in the way\n", encoding="utf-8")

        self.stopped(run, run.deliver(), "claim", "retry")

        transitions = run.transitions(self.child(run, "setup"))
        self.assertIn(("existing", "absent"), transitions)
        self.assertEqual(transitions[-1], ("worktree", "error"))
        first = run.claims()
        self.assertEqual(len(first), 1)
        run.worktree_path.unlink()

        done = run.deliver()

        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(run.line(done)["end"], "done")
        self.assertEqual(len(run.runs()), 1)
        root = run.runs()[0]
        self.assertEqual([e["event"] for e in run.events(root)].count("run_continued"), 1)
        second = run.transitions(self.child(run, "setup", last=True))
        self.assertIn(("acquire", "already_held"), second)
        self.assertTrue(("worktree", "made") in second or ("worktree", "adopted") in second, second)
        self.assertEqual(run.claims(), [])
        self.assertEqual([claim.comment_id for claim in self.released_claims(run)], [first[0].comment_id])


class ReviewRouteTest(Scenario):
    def reviewer_model(self, run: StubbedRun, name: str = "reviewer") -> str:
        return engine_session.read_role(ROLES, name).model

    def seed_bar(self, run: StubbedRun) -> None:
        bar = run.world.home / ".agents/standards/the-bar.md"
        bar.parent.mkdir(parents=True, exist_ok=True)
        bar.write_text("# The bar\n\n### B1. Defense in depth\n\nBody.\n", encoding="utf-8")

    def test_a_finding_citing_a_made_up_rule_is_stored_blanked_and_graded_the_same(self):
        minor = {"severity": "minor", "file": "fixture/farewell.py:2", "failing_input": "farewell('')",
                 "summary": "s", "kind": "other"}
        run = self.stubbed(replies={"lite-review": dict(
            CLEAN_LITE, findings=[dict(minor, rule="ZZ999"), dict(minor, rule="B1"), minor])})
        self.seed_bar(run)

        self.finish(run, "done")

        direct = self.child(run, "direct")
        self.assertEqual([f.get("rule") for f in self.stored(direct, "lite-review")["findings"]], ["", "B1", None])
        self.assertIn(("lite-review", "pass"), [(e["step"], e["outcome"]) for e in StubbedRun.events(direct)
                                                 if e["event"] == "outcome_graded"])
        self.assertIn(("lite-tally", "clean"), run.transitions(direct))

    def test_a_schema_that_admits_only_one_rule_value_keeps_the_reply_unblanked(self):
        minor = {"severity": "minor", "file": "fixture/farewell.py:2", "failing_input": "farewell('')",
                 "summary": "s", "kind": "other", "rule": "local"}
        run = self.stubbed(replies={"lite-review": dict(CLEAN_LITE, findings=[minor])})
        copy = run.tmp / "local-rule-procedures"
        shutil.copytree(PROCEDURES, copy)
        path = copy / "direct-review-lite.reply.json"
        schema = json.loads(path.read_text("utf-8"))
        schema["properties"]["findings"]["items"]["properties"]["rule"] = {"enum": ["local"]}
        path.write_text(json.dumps(schema) + "\n", encoding="utf-8")

        done = run.deliver(copy)

        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        stored = self.stored(self.child(run, "direct"), "lite-review")["findings"]
        self.assertEqual([f.get("rule") for f in stored], ["local"])

    def test_a_declined_finding_takes_the_same_rounds_and_end_as_an_unstructured_one(self):
        reason = "farewell(None) is refused by the type checker at fixture/farewell.py:1"
        plain_finding = {k: v for k, v in FINDING.items() if k != "kind"}
        plain_second = dict(plain_finding, file="fixture/farewell.py:1", failing_input="farewell(None)")
        plain = self.stubbed(replies={
            "lite-review": dict(CLEAN_LITE, verdict="findings", findings=[plain_finding, plain_second]),
            "lite-fix": {"reply": {"status": "done", "notes": "the second finding is wrong: None never reaches it",
                                   "tests": []},
                         "commit": {"path": "fixture/second.py", "text": "SECOND = 2\n"}},
            "lite-rereview": CLEAN_REREVIEW})
        structured = self.stubbed(replies={
            "lite-review": dict(CLEAN_LITE, verdict="findings", findings=[
                dict(FINDING, kind="missing-test", rule="B1"),
                dict(FINDING, file="fixture/farewell.py:1", failing_input="farewell(None)", kind="weak-test")]),
            "lite-fix": committing("fixture/second.py", "SECOND = 2\n",
                                   declines=[{"finding": "lite-review:2", "reason": reason}]),
            "lite-rereview": CLEAN_REREVIEW})
        self.seed_bar(structured)

        done = plain.deliver(unstructured_procedures(plain.tmp))
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(plain.line(done)["end"], "done")
        self.finish(structured, "done")

        stored = self.stored(self.child(structured, "direct"), "lite-review")["findings"]
        self.assertEqual([f.get("rule") for f in stored], ["B1", None])
        self.assertEqual(self.keys(plain), self.keys(structured))
        self.assertEqual(plain.transitions(self.child(plain, "direct")),
                         structured.transitions(self.child(structured, "direct")))
        rendered = self.launch(structured, "lite-rereview")["prompt"]
        control = self.launch(plain, "lite-rereview")["prompt"]
        self.assertIn(reason, rendered)
        self.assertNotIn(reason, control)
        self.assertEqual(rendered.count("lite-review:2"), control.count("lite-review:2") + 1)
        direct = self.child(structured, "direct")
        round_ = Round(reviews=(("lite-review", self.stored(direct, "lite-review")),
                                ("lite-independent", self.stored(direct, "lite-independent"))),
                       fix=self.stored(direct, "lite-fix"),
                       rereview=("lite-rereview", self.stored(direct, "lite-rereview")))
        self.assertEqual([(d.name, d.disposition) for d in dispositions([round_])],
                         [("lite-review:1", "fixed"), ("lite-review:2", "declined")])

    def test_a_change_marked_sensitive_is_reviewed_under_the_full_reviewer(self):
        implemented = dict(IMPLEMENTED, reply=dict(IMPLEMENTED["reply"], sensitive=True))
        run = self.stubbed(replies={"implement": implemented, "full-review": CLEAN_FULL})

        self.finish(run, "done")

        transitions = run.transitions(self.child(run, "direct"))
        for edge in (("implemented", "full"), ("full-group", "pass"), ("full-tally", "clean")):
            self.assertIn(edge, transitions)
        self.assertIn("full-review", self.keys(run))
        self.assertNotIn("lite-review", self.keys(run))
        self.assertEqual(model_of(self.launch(run, "full-review")), self.reviewer_model(run))

    def test_an_escalate_reply_is_followed_by_the_full_reviewer(self):
        run = self.stubbed(replies={"lite-review": dict(CLEAN_LITE, escalate=True),
                                     "escalated": CLEAN_FULL})

        self.finish(run, "done")

        transitions = run.transitions(self.child(run, "direct"))
        for edge in (("lite-tally", "escalate"), ("escalated", "pass"), ("escalated-tally", "clean")):
            self.assertIn(edge, transitions)
        keys = self.keys(run)
        self.assertLess(keys.index("lite-review"), keys.index("escalated"))
        self.assertEqual(model_of(self.launch(run, "escalated")), self.reviewer_model(run))

    def test_findings_of_the_escalated_review_are_fixed_once_and_land_after_a_clean_rereview(self):
        fix = committing("fixture/second.py", "SECOND = 2\n")
        run = self.stubbed(replies={"lite-review": dict(CLEAN_LITE, escalate=True), "escalated": full_findings(),
                                     "escalated-fix": fix, "escalated-rereview": CLEAN_REREVIEW})

        self.finish(run, "done")

        transitions = run.transitions(self.child(run, "direct"))
        for edge in (("escalated-tally", "findings"), ("escalated-fixed", "done"), ("escalated-settled", "clean")):
            self.assertIn(edge, transitions)
        keys = self.keys(run)
        self.assertEqual(keys.count("escalated-fix"), 1)
        self.assertLess(keys.index("escalated"), keys.index("escalated-fix"))
        self.assertLess(keys.index("escalated-fix"), keys.index("escalated-rereview"))
        landed = run.world.git(run.fixture.root, "--git-dir", run.bare, "show", "main:fixture/second.py")
        self.assertEqual(landed, "SECOND = 2\n")

    def test_findings_of_the_full_review_of_a_sensitive_change_are_fixed_once_and_land_after_a_clean_rereview(self):
        fix = committing("fixture/second.py", "SECOND = 2\n")
        sensitive = dict(IMPLEMENTED, reply=dict(IMPLEMENTED["reply"], sensitive=True))
        run = self.stubbed(replies={"implement": sensitive, "full-review": full_findings(), "full-fix": fix,
                                     "full-rereview": CLEAN_REREVIEW})

        self.finish(run, "done")

        transitions = run.transitions(self.child(run, "direct"))
        for edge in (("implemented", "full"), ("full-tally", "findings"), ("full-fixed", "done"),
                     ("full-settled", "clean")):
            self.assertIn(edge, transitions)
        keys = self.keys(run)
        self.assertNotIn("lite-review", keys)
        self.assertEqual(keys.count("full-fix"), 1)
        self.assertLess(keys.index("full-fix"), keys.index("full-rereview"))
        self.assertEqual([pull["state"] for pull in run.pulls()], ["MERGED"])
        landed = run.world.git(run.fixture.root, "--git-dir", run.bare, "show", "main:fixture/second.py")
        self.assertEqual(landed, "SECOND = 2\n")

    def test_findings_left_after_the_one_fix_round_stop_direct_review(self):
        run = self.stubbed(replies={
            "lite-review": lite_findings(),
            "lite-fix": committing("fixture/second.py", "SECOND = 2\n"),
            "lite-rereview": {"verdict": "findings", "findings": [FINDING]}})

        self.finish(run, "direct-review", "owner-decision")

        self.assertEqual(self.keys(run).count("lite-fix"), 1)
        self.assertEqual(run.transitions(self.child(run, "direct"))[-1], ("lite-settled", "findings"))
        self.assertEqual(len(self.branch_commits(run)), 2)

    def test_an_ineligible_reply_stops_with_no_review_started(self):
        refused = {"status": "blocked", "start_head": SHA, "commit": SHA, "notes": "n", "acceptance": [],
                   "sensitive": False, "ineligible": True, "tests": []}
        run = self.stubbed(replies={"implement": refused})

        self.finish(run, "ineligible", "owner-decision")

        self.assertEqual(self.keys(run), ["applies", "implement"])
        steps = [step for step, _ in run.transitions(self.child(run, "direct"))]
        self.assertNotIn("lite-group", steps)
        self.assertNotIn("full-group", steps)
        self.assertEqual(self.branch_commits(run), [])

    def test_a_configured_independent_review_that_is_unavailable_stops_codex_unavailable(self):
        run = self.stubbed(review_code=[CODEX_LIMIT])

        self.finish(run, "codex-unavailable", "retry")

        self.assertEqual(len(run.companion_launches()), 2)
        self.assertIn("lite-review", self.keys(run))

    def test_a_project_that_configures_no_independent_review_runs_the_review_alone(self):
        run = self.stubbed()

        self.finish(run, "done")

        independent = self.stored(self.child(run, "direct"), "lite-independent")
        self.assertEqual((independent["verdict"], independent["findings"]), ("none", []))
        standin = shutil.which("codex-companion", path=run.env["PATH"])
        self.assertFalse(standin and Path(standin).is_relative_to(run.world.tmp), standin)
        self.assertEqual(run.companion_launches(), [])
        self.assertEqual(self.keys(run).count("lite-review"), 1)

    def test_an_unusable_review_is_asked_once_more_and_its_second_reply_is_used(self):
        run = self.stubbed(replies={"lite-review": UNNAMED_LITE, "lite-review.2": CLEAN_LITE})

        self.finish(run, "done")

        self.assertEqual(self.keys(run), ["applies", "implement", "lite-review", "lite-review"])
        tallies = [edge for edge in run.transitions(self.child(run, "direct")) if edge[0] == "lite-tally"]
        self.assertEqual(tallies, [("lite-tally", "unusable"), ("lite-tally", "clean")])

    def test_a_second_unusable_review_stops_direct_review(self):
        run = self.stubbed(replies={"lite-review": UNNAMED_LITE})

        self.finish(run, "direct-review", "owner-decision")

        self.assertEqual(self.keys(run).count("lite-review"), 2)
        self.assertNotIn("lite-fix", self.keys(run))

    def test_a_fix_that_reports_no_commit_stops_direct_fix(self):
        unfixed = {"status": "done", "start_head": SHA, "commit": "", "notes": "n", "tests": [], "declines": []}
        run = self.stubbed(replies={"lite-review": lite_findings(), "lite-fix": unfixed})

        self.finish(run, "direct-fix", "owner-decision")

        self.assertIn(("lite-fixed", "not-done"), run.transitions(self.child(run, "direct")))
        self.assertNotIn("lite-rereview", self.keys(run))


class RevertCheckTest(Scenario):
    def test_the_review_after_the_revert_check_names_a_new_test_that_passes_without_its_source(self):
        run = self.stubbed(replies={"implement": implementing("checks/check_kept.py", KEPT)})

        self.finish(run, "done")

        direct = self.child(run, "direct")
        checked = self.stored(direct, "revert-check")
        self.assertEqual((checked["still_passing"], checked["new_tests"], checked["reason"]),
                         ([KEPT_ID], [KEPT_ID], ""))
        self.assertIn(KEPT_ID, self.launch(run, "lite-review")["prompt"])
        transitions = run.transitions(direct)
        self.assertIn(("revert-check", "ok"), transitions)
        self.assertLess(transitions.index(("revert-check", "ok")), transitions.index(("implemented", "lite")))

    def test_a_fix_that_moves_the_head_runs_the_check_again_before_the_re_review_and_adds_no_review_round(self):
        run = self.stubbed(replies={
            "implement": implementing("checks/check_kept.py", KEPT),
            "lite-review": lite_findings(),
            "lite-fix": committing("checks/check_second.py", SECOND),
            "lite-rereview": CLEAN_REREVIEW})

        self.finish(run, "done")

        self.assertEqual(self.keys(run), ["applies", "implement", "lite-review", "lite-fix", "lite-rereview"])
        direct = self.child(run, "direct")
        wanted = {"implement", "revert-check", "lite-review", "lite-fix", "lite-revert-check", "lite-rereview"}
        entered = [e["step"] for e in StubbedRun.events(direct) if e["event"] == "step_entered" and e["step"] in wanted]
        self.assertEqual(entered, ["implement", "revert-check", "lite-review", "lite-fix", "lite-revert-check",
                                   "lite-rereview"])
        first, second = self.stored(direct, "revert-check"), self.stored(direct, "lite-revert-check")
        self.assertEqual(first["head"], self.stored(direct, "implement")["commit"])
        self.assertEqual(second["head"], self.stored(direct, "lite-fix")["commit"])
        self.assertNotEqual(second["head"], first["head"])
        self.assertEqual(first["still_passing"], [KEPT_ID])
        self.assertEqual(second["new_tests"], [KEPT_ID, SECOND_ID])
        self.assertEqual(second["still_passing"], [KEPT_ID, SECOND_ID])
        prompt = self.launch(run, "lite-rereview")["prompt"]
        self.assertIn(KEPT_ID, prompt)
        self.assertIn(SECOND_ID, prompt)


class VerifyTest(Scenario):
    def test_a_failing_verification_id_with_no_fix_reply_stops_verify_fix(self):
        broken = implementing("fixture/greet.py", 'def greet(name: str) -> str:\n    return f"Hi, {name}."\n')
        run = self.stubbed(replies={"implement": broken})

        self.finish(run, "verify-fix", "owner-decision")

        checks = self.stored(self.child(run, "verify"), "checks")
        self.assertEqual(checks["verdict"], "failed")
        self.assertEqual({r["id"]: r["status"] for r in checks["results"]}, {"lint": "pass", "test": "fail"})
        self.assertIs(next(r for r in checks["results"] if r["id"] == "test")["reran"], True)

    def test_an_untested_fix_is_reviewed_narrowed_and_retested(self):
        run = self.stubbed(extra_files=FORMAT, replies={
            "implement": FOUR, "fix": fixing("fixture/greeting.json", TWO_SPACES), "fix-review": PASS_ATTESTED,
            "retest": RETESTED})

        self.finish(run, "done")

        walk = run.transitions(self.child(run, "verify"))
        for edge in (("round", "fix"), ("fixed", "done"), ("ws-check", "read"), ("fix-review", "pass"),
                     ("narrowing", "rerun-failed-only"), ("round", "retest"), ("retested", "done")):
            self.assertIn(edge, walk)

    def test_an_unusable_fix_review_is_asked_once_more_and_the_second_reply_is_narrowed(self):
        unusable = {"verdict": "findings", **ATTESTED,
                    "findings": [{"severity": "important", "file": "", "failing_input": "",
                                  "summary": "s", "kind": "other"}]}
        run = self.stubbed(extra_files=FORMAT, replies={
            "implement": FOUR, "fix": fixing("fixture/greeting.json", TWO_SPACES),
            "fix-review": unusable, "fix-review-again": PASS_ATTESTED, "retest": RETESTED})

        self.finish(run, "done")

        walk = run.transitions(self.child(run, "verify"))
        for edge in (("narrowing", "unusable"), ("fix-review-again", "pass"),
                     ("narrowing-again", "rerun-failed-only")):
            self.assertIn(edge, walk)

    def test_an_id_whose_condition_matches_no_changed_path_is_recorded_skipped_with_its_reason(self):
        conditions = {"lint": {"when_changed": ["docs/**"], "skip_reason": "no documentation changed"}}
        run = self.stubbed(conditions=conditions)

        self.finish(run, "done")

        results = self.stored(self.child(run, "verify"), "checks")["results"]
        self.assertEqual([r["id"] for r in results], FixtureProject.VERIFICATION)
        lint, test = results
        self.assertEqual((lint["status"], lint["reason"]), ("skipped", "no documentation changed"))
        self.assertEqual(test["status"], "pass")

    def test_before_a_pull_request_verify_runs_lint_and_the_touched_checks_and_records_the_selection_and_slot_seconds(self):
        greet = 'def greet(name: str) -> str:\n    return "Hello, " + name + "."\n'
        run = self.stubbed(before_pull_request=True,
                           replies={"implement": implementing("fixture/greet.py", greet)})

        self.finish(run, "done")

        verify = self.child(run, "verify")
        event = next(e for e in run.events(verify) if e["event"] == "result_stored" and e["step"] == "checks")
        checks = json.loads((verify / event["result"]).read_text("utf-8"))
        self.assertEqual(checks["verdict"], "passed")
        self.assertEqual([(r["id"], r["status"]) for r in checks["results"]],
                         [("lint", "pass"), ("test-touched", "pass")])
        self.assertEqual(checks["results"][1]["selection"],
                         {"base": "origin/main", "changed": ["fixture/greet.py"], "full": False,
                          "full_because": [], "selected": ["checks/check_greet.py"]})
        for result in checks["results"]:
            for member in ("waited_seconds", "held_seconds"):
                self.assertNotIsInstance(result[member], bool)
                self.assertIsInstance(result[member], (int, float))
                self.assertGreaterEqual(result[member], 0)
        self.assertEqual(len(run.slot_history()), 2)

    def test_a_continued_run_after_a_clean_sync_that_changes_none_of_the_pull_requests_files_runs_no_verification(self):
        run = self.stubbed(before_pull_request=True)
        procedures = stopping_after_verify(run.tmp)
        self.stopped(run, run.deliver(procedures), "verified", "owner-decision")
        first = self.stored(self.child(run, "verify"), "checks")
        self.assertEqual(first["verdict"], "passed")
        held = len(run.slot_history())
        root = run.fixture.root
        (root / "README.md").write_text((root / "README.md").read_text("utf-8") + "more\n", "utf-8")
        run.world.git(root, "commit", "-qam", "unrelated")
        run.world.git(root, "push", "-q", "origin", "main")
        run.world.git(run.worktree_path, "fetch", "-q", "origin")
        run.world.git(run.worktree_path, "merge", "-q", "--no-edit", "origin/main")

        done = run.deliver(procedures)

        self.stopped(run, done, "verified", "owner-decision")
        self.assertEqual(len(run.runs()), 1)
        self.assertEqual([e["event"] for e in run.events(run.runs()[0])].count("run_continued"), 1)
        second = self.stored(self.child(run, "verify", last=True), "checks")
        self.assertEqual(second["verdict"], "passed")
        self.assertEqual(second["synced_since"], first["head"])
        self.assertEqual([r["status"] for r in second["results"]], ["skipped", "skipped"])
        self.assertEqual(len(run.slot_history()), held)


    def test_a_continued_run_that_skips_verification_after_a_clean_sync_still_lands(self):
        run = self.stubbed(before_pull_request=True, rollup=RED)
        procedures = keeping_the_run(run.tmp)
        self.stopped(run, run.deliver(procedures), "checks-fix", "owner-decision")
        held = len(run.slot_history())
        state = json.loads(run.pulls_state.read_text("utf-8"))
        state["rollup"] = GREEN
        run.pulls_state.write_text(json.dumps(state), encoding="utf-8")
        root = run.fixture.root
        (root / "README.md").write_text((root / "README.md").read_text("utf-8") + "more\n", "utf-8")
        run.world.git(root, "commit", "-qam", "unrelated")
        run.world.git(root, "push", "-q", "origin", "main")
        run.world.git(run.worktree_path, "fetch", "-q", "origin")
        run.world.git(run.worktree_path, "merge", "-q", "--no-edit", "origin/main")

        done = run.deliver(procedures)

        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(run.line(done)["end"], "done")
        skipped = self.stored(self.child(run, "verify", last=True), "checks")
        self.assertEqual([r["status"] for r in skipped["results"]], ["skipped", "skipped"])
        self.assertEqual(len(run.slot_history()), held)
        self.assertEqual([p["state"] for p in run.pulls()], ["MERGED"])


RED = [{"__typename": "CheckRun", "name": "Fixture Checks", "status": "COMPLETED",
        "conclusion": "FAILURE", "startedAt": "2026-11-06T10:00:00Z", "workflowName": "Fixture"}]
UNNAMED = [{"__typename": "CheckRun", "status": "COMPLETED", "conclusion": "SUCCESS"}]


class Landing(Scenario):
    def attempt(self, run: StubbedRun) -> Path:
        """The last child of the land run that runs `land-attempt`."""
        found = [child for child in run.children(self.child(run, "land"))
                 if json.loads((child / "run.json").read_text("utf-8"))["procedure"] == "land-attempt"]
        return found[-1]

    def land_transitions(self, run: StubbedRun) -> list[tuple[str, str]]:
        return run.transitions(self.attempt(run))

    def release_transitions(self, run: StubbedRun) -> list[tuple[str, str]]:
        return run.transitions(self.child(run, "land"))

    def prepared_head(self, run: StubbedRun) -> str:
        return self.stored(self.attempt(run), "prepare")["head"]

    def entered(self, run: StubbedRun) -> set[str]:
        return {e["step"] for e in run.events(self.attempt(run)) if e["event"] == "step_entered"}


class LandGuardTest(Landing):
    def test_the_real_guard_allowed_the_push_the_pull_request_and_the_merge(self):
        run = self.stubbed()

        self.finish(run, "done")

        head = self.prepared_head(run)
        commands = [line["payload"]["tool_input"]["command"] for line in payloads(run.guard_log)]
        root = run.fixture.root
        for text in (
                f"git -C {root} push origin {run.branch}",
                (f"gh pr create --repo example/fixture --base main --head {run.branch} "
                 '--title "Add a greeting" --body "Closes #41. Delivered by the engine."'),
                f"gh pr merge 1 --repo example/fixture --merge --match-head-commit {head} --delete-branch"):
            with self.subTest(text):
                self.assertEqual(commands.count(text), 1, commands)
        outcomes = dict(self.land_transitions(run))
        for step in ("push", "create", "merge-pr"):
            self.assertEqual(outcomes[step], "ok", step)

    def test_without_declared_required_checks_the_merge_is_refused_and_nothing_merges(self):
        run = self.stubbed(required_checks=())
        before = run.origin_tip("main")

        self.finish(run, "merge", "owner-decision")

        merge = self.stored(self.attempt(run), "merge-pr")
        self.assertEqual(merge["verdict"], "refused")
        self.assertIn("protection lookup failed", merge["reason"])
        self.assertEqual(self.land_transitions(run)[-2:], [("merge-pr", "refused"), ("merge-state", "other")])
        self.assertEqual(self.release_transitions(run)[-2:], [("attempt", "merge"), ("release", "merge")])
        self.assertEqual([p["state"] for p in run.pulls()], ["OPEN"])
        self.assertEqual(run.origin_tip("main"), before)
        self.assertEqual(run.forge.issue()["state"], "open")


class LandStopTest(Landing):
    def test_a_head_that_moves_after_the_check_poll_stops_head_moved_and_merges_nothing(self):
        run = self.stubbed( forge_events=("move-head",))

        self.finish(run, "head-moved", "owner-decision")

        transitions = self.land_transitions(run)
        for edge in (("gate", "green"), ("lock", "no-pull"), ("head", "head-moved")):
            self.assertIn(edge, transitions)
        self.assertIn(("release", "head-moved"), self.release_transitions(run))
        self.assertEqual(run.lock_refs(), {})
        self.assertEqual([p["state"] for p in run.pulls()], ["OPEN"])
        self.assertFalse({"recheck", "merge-pr"} & self.entered(run))

    def test_a_red_required_check_with_no_fix_answer_stops_checks_fix_with_the_lock_free(self):
        run = self.stubbed( rollup=RED)

        self.finish(run, "checks-fix", "owner-decision")

        self.assertIn(("gate", "red"), self.land_transitions(run))
        self.assertIn(("red", "fix"), self.land_transitions(run))
        self.assertIn(("release", "checks-fix"), self.release_transitions(run))
        self.assertEqual(run.lock_refs(), {})
        self.assertEqual([p["state"] for p in run.pulls()], ["OPEN"])

    def test_a_lock_taken_by_another_pull_request_stops_land_contended(self):
        run = self.stubbed(forge_events=("steal-lock",))

        self.finish(run, "land-contended", "retry")

        transitions = self.land_transitions(run)
        self.assertIn(("lock", "contended"), transitions)
        self.assertIn(("lock-wait", "again"), transitions)
        self.assertEqual([o for s, o in transitions if s == "lock-wait"][-1], "spent")
        self.assertIn(("release", "land-contended"), self.release_transitions(run))
        self.assertEqual(run.pulls()[0]["state"], "OPEN")
        self.assertNotIn("merge-pr", self.entered(run))
        self.assertEqual(run.lock_refs(), {"refs/agent-locks/land/main": run.stolen_sha})

    def test_a_failed_release_stops_unreleased_lock(self):
        run = self.stubbed(lock_release_fails=True)

        self.finish(run, "unreleased-lock", "owner-decision")

        self.assertIn(("release", "unreleased"), self.release_transitions(run))
        self.assertEqual(run.pulls()[0]["state"], "MERGED")
        self.assertEqual(run.lock_refs(), {"refs/agent-locks/land/main": self.prepared_head(run)})

    def test_an_unreadable_rollup_stops_land_with_the_lock_released(self):
        run = self.stubbed(rollup=UNNAMED)

        self.finish(run, "land", "owner-decision")

        self.assertIn(("gate", "error"), self.land_transitions(run))
        self.assertIn(("release", "land"), self.release_transitions(run))
        self.assertEqual(run.lock_refs(), {})


class LandWaitTest(Landing):
    def test_the_land_run_records_a_started_and_ended_wait_for_the_lock_and_the_checks(self):
        run = self.stubbed()

        self.finish(run, "done")

        events = run.events(self.attempt(run))

        def at(kind: str, **match) -> list[int]:
            return [i for i, e in enumerate(events)
                    if e["event"] == kind and all(e.get(k) == v for k, v in match.items())]

        spans = {}
        for step, wait in (("gate", "checks"), ("lock", "lock")):
            started, ended = at("wait_started", wait=wait), at("wait_ended", wait=wait)
            self.assertEqual((len(started), len(ended)), (1, 1), step)
            entered, stored = at("step_entered", step=step)[0], at("result_stored", step=step)[0]
            self.assertTrue(entered < started[0] < ended[0] < stored, step)
            spans[step] = (started[0], ended[0])
        self.assertLess(spans["gate"][1], spans["lock"][0])


class SettledTest(Landing):
    def earlier_merge(self, run: StubbedRun) -> tuple[str, str]:
        """A merge commit and its side head in the origin's object store, on no ref."""
        git, bare = run.world.git, run.bare
        tree = git(bare, "rev-parse", "main^{tree}").strip()
        main = git(bare, "rev-parse", "main").strip()
        side = git(bare, "commit-tree", tree, "-p", main, "-m", "earlier work").strip()
        return git(bare, "commit-tree", tree, "-p", main, "-p", side, "-m", "earlier merge").strip(), side

    def test_an_earlier_merged_pull_request_at_another_head_does_not_settle_the_landing(self):
        run = self.stubbed()
        merge, side = self.earlier_merge(run)
        state = json.loads(run.pulls_state.read_text(encoding="utf-8"))
        state["pulls"].append({"number": 1, "state": "MERGED", "baseRefName": "main",
                               "headRefName": run.branch, "headRefOid": side,
                               "mergeCommit": {"oid": merge}, "title": "earlier",
                               "body": "Refs #41.", "url": "https://github.com/example/fixture/pull/1"})
        state["next"] = 2
        run.pulls_state.write_text(json.dumps(state), encoding="utf-8")

        self.finish(run, "done")

        walk = self.land_transitions(run)
        self.assertIn(("settled", "unmerged"), walk)
        self.assertIn(("merge-pr", "ok"), walk)
        self.assertEqual([pull["number"] for pull in run.pulls()], [1, 2])
        landed = run.pulls()[1]
        self.assertEqual((landed["state"], landed["headRefOid"]), ("MERGED", self.prepared_head(run)))
        self.assertNotEqual(self.prepared_head(run), side)


HOLD_STEPS = {"hold-facts", "hold-look", "hold-draft", "hold-gate", "regrade", "graded", "hold-lint",
              "split", "hold-post", "hold-label", "once-run", "close"}


HUMAN_CHECK = {"ac": "AC3", "kind": "human", "host": "any", "when": NOT_BEFORE,
               "run": {"ask": "Does the greeting read well?"}, "reason": "taste"}
SPLIT_BODY = EVIDENCE_BODY + "- [ ] [human] the greeting reads well\n"


def hold_comments(run: StubbedRun) -> list[dict]:
    """The stored comments of the issue that carry a verify fence."""
    return [comment for comment in run.forge.stored() if "```verify" in comment["body"]]


def held_label(run: StubbedRun) -> bool:
    return "needs-verification" in run.forge.issue()["labels"]


class CloseOutTest(Landing):
    def posted_nothing(self, run: StubbedRun) -> None:
        """A refused hold or an unmet code criterion posts nothing and keeps the claim and worktree."""
        stored = run.forge.stored()
        self.assertEqual(len(stored), 1, [comment["body"] for comment in stored])
        self.assertTrue(stored[0]["body"].startswith("<!-- agent:claim v1 issue=41 "), stored[0]["body"])
        issue = run.forge.issue()
        self.assertEqual((issue["state"], issue["labels"], issue["created"]), ("open", ["in-progress"], []))
        self.assertEqual(len(run.claims()), 1)
        self.assertTrue(run.worktree_path.exists())

    def test_an_issue_with_one_evidence_criterion_ends_done_open_labelled_with_one_hold_comment(self):
        run = self.stubbed(body=EVIDENCE_BODY)

        self.finish(run, "done")

        pulls = run.pulls()
        self.assertEqual(pulls[0]["state"], "MERGED")
        self.assertTrue(pulls[0]["body"].startswith("Refs #41."), pulls[0]["body"])
        merge = pulls[0]["mergeCommit"]["oid"]
        self.assertEqual(run.forge.issue()["state"], "open")
        self.assertTrue(held_label(run))
        comments = hold_comments(run)
        self.assertEqual(len(comments), 1)
        block = {"v": 1, "merge": merge, "checks": [EVIDENCE_CHECK]}
        self.assertEqual(verify_block.parse_block(comments[0]["body"]), (block, []))
        self.assertEqual(run.forge.issue()["created"], [])
        child = self.child(run, "close-out")
        self.assertEqual([t for t in run.transitions(child) if t[0] in HOLD_STEPS],
                         [("hold-facts", "open"), ("hold-look", "clear"), ("hold-draft", "drafted"),
                          ("hold-gate", "ready"), ("regrade", "met"), ("graded", "met"), ("hold-lint", "valid"),
                          ("split", "none"), ("hold-post", "posted"), ("hold-label", "labelled"),
                          ("once-run", "ran"), ("close", "open-criteria")])
        self.assertEqual(self.stored(child, "hold-post")["block"], block)
        self.assertEqual(self.stored(child, "once-run")["runs"], [{"issue": 41, "exit": 0}])
        self.assertEqual(run.transitions(run.runs()[0])[-1], ("closing", "done"))
        self.assertEqual(run.claims(), [])
        self.assertFalse(run.worktree_path.exists())

    def test_an_unmet_code_criterion_stops_code_unmet_and_posts_nothing(self):
        unmet = {"verdict": "unmet", "code_unmet": ["AC1"],
                 "acceptance": [{"id": "AC1", "met": False, "evidence": "no test shows it"}]}
        run = self.stubbed(body=EVIDENCE_BODY, replies={"regrade": unmet})

        self.finish(run, "code-unmet", "owner-decision")

        self.posted_nothing(run)
        child = self.child(run, "close-out")
        walk = run.transitions(child)
        self.assertLess(walk.index(("hold-gate", "ready")), walk.index(("regrade", "unmet")))
        self.assertFalse([t for t in walk if t[0] in ("hold-lint", "split", "hold-post")])
        self.assertEqual(run.transitions(run.runs()[0])[-1], ("closing", "code-unmet"))

    def test_a_met_verdict_naming_an_unmet_code_criterion_stops_code_unmet_and_posts_nothing(self):
        contradictory = {"verdict": "met", "code_unmet": ["AC1"],
                         "acceptance": [{"id": "AC1", "met": False, "evidence": "no test shows it"}]}
        run = self.stubbed(body=EVIDENCE_BODY, replies={"regrade": contradictory})

        self.finish(run, "code-unmet", "owner-decision")

        self.posted_nothing(run)
        walk = run.transitions(self.child(run, "close-out"))
        self.assertIn(("regrade", "met"), walk)
        self.assertIn(("graded", "unmet"), walk)
        self.assertFalse([t for t in walk if t[0] in ("hold-lint", "split", "hold-post")])
        self.assertEqual(run.transitions(run.runs()[0])[-1], ("closing", "code-unmet"))

    def refused(self, replies: dict, verdict: str) -> tuple:
        run = self.stubbed(body=EVIDENCE_BODY, replies=replies)

        self.finish(run, "hold", "owner-decision")

        self.posted_nothing(run)
        child = self.child(run, "close-out")
        gate = self.stored(child, "hold-gate")
        self.assertEqual((gate["verdict"], gate["acs"]), (verdict, ["AC2"]))
        return run, child

    def test_a_drafted_owner_check_for_an_evidence_criterion_stops_hold_posting_nothing(self):
        ask = {"ac": "AC2", "kind": "human", "host": "any", "when": NOT_BEFORE,
               "run": {"ask": "Have you seen the greeting?"}, "reason": "senses"}

        run, child = self.refused({"hold-draft": drafted(ask)}, "human-checks")

        self.assertNotIn("regrade", [step for step, _ in run.transitions(child)])

    def test_a_drafted_command_outside_the_verification_ids_stops_hold_posting_nothing(self):
        self.refused({"hold-draft": drafted(dict(EVIDENCE_CHECK, run={"command": "deploy"}))},
                     "unattended")

    def test_a_criterion_left_without_a_drafted_check_stops_hold_posting_nothing(self):
        self.refused({"hold-draft": drafted()}, "missing-checks")

    def test_a_verify_block_failing_the_lint_stops_hold_posting_nothing(self):
        bad = dict(EVIDENCE_CHECK, when={"not_before": "not-a-time"})
        run = self.stubbed(body=EVIDENCE_BODY, replies={"hold-draft": drafted(bad)})

        self.finish(run, "hold", "owner-decision")

        self.posted_nothing(run)
        child = self.child(run, "close-out")
        walk = run.transitions(child)
        order = [walk.index(t) for t in (("hold-gate", "ready"), ("regrade", "met"), ("graded", "met"),
                                         ("hold-lint", "invalid"))]
        self.assertEqual(order, sorted(order))
        lint = self.stored(child, "hold-lint")
        self.assertEqual(lint["verdict"], "invalid")
        self.assertTrue([e for entry in lint["lints"] for e in entry["errors"]
                         if "checks[0].when.not_before" in json.dumps(e)], lint)
        self.assertFalse([t for t in walk if t[0] in ("split", "hold-post")])

    def test_a_run_cut_after_the_hold_comment_and_continued_leaves_one_hold_comment_and_one_split_issue(self):
        run = self.stubbed(body=SPLIT_BODY, blocks=(50,), fail_once=("add_label:needs-verification",),
                           replies={"hold-draft": drafted(EVIDENCE_CHECK, HUMAN_CHECK)})

        self.finish(run, "hold", "owner-decision")

        merge = run.pulls()[0]["mergeCommit"]["oid"]
        evidence = {"v": 1, "merge": merge, "checks": [EVIDENCE_CHECK]}
        self.assertEqual(len(hold_comments(run)), 1)
        self.assertEqual(verify_block.parse_block(hold_comments(run)[0]["body"]), (evidence, []))
        self.assertFalse(held_label(run))
        created = run.forge.issue()["created"]
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0]["body"].split("\n", 1)[0], holding.split_line(41, "AC3", merge))
        self.assertEqual(created[0]["labels"], ["needs-verification"])
        self.assertEqual(len(created[0]["comments"]), 1)
        self.assertEqual(verify_block.parse_block(created[0]["comments"][0]["body"]),
                         ({"v": 1, "merge": merge, "checks": [HUMAN_CHECK]}, []))
        first = self.child(run, "close-out")
        walk = run.transitions(first)
        for transition in (("split", "split"), ("hold-post", "posted"), ("hold-label", "error")):
            self.assertIn(transition, walk)
        self.assertEqual(len(run.claims()), 1)

        self.finish(run, "done")

        self.assertEqual(len(run.runs()), 1)
        root = run.runs()[0]
        continued = [e for e in run.events(root) if e["event"] == "run_continued"]
        self.assertEqual([e["step"] for e in continued], ["closing"])
        self.assertEqual(run.transitions(root)[-2:], [("closing", "hold"), ("closing", "done")])
        self.assertEqual(len(hold_comments(run)), 1)
        self.assertEqual(verify_block.parse_block(hold_comments(run)[0]["body"]), (evidence, []))
        self.assertEqual(len(run.forge.issue()["created"]), 1)
        self.assertEqual(len(run.forge.issue()["created"][0]["comments"]), 1)
        self.assertTrue(held_label(run))
        second = self.child(run, "close-out", last=True)
        self.assertNotEqual(second, first)
        children = [{"ac": "AC3", "issue": created[0]["number"]}]
        self.assertEqual(self.stored(second, "split")["children"], children)
        self.assertEqual(self.stored(first, "split")["children"], children)
        self.assertEqual(self.stored(second, "hold-post")["comment_id"], self.stored(first, "hold-post")["comment_id"])
        second_walk = run.transitions(second)
        for transition in (("hold-label", "labelled"), ("once-run", "ran"), ("close", "open-criteria")):
            self.assertIn(transition, second_walk)
        self.assertEqual([r["issue"] for r in self.stored(second, "once-run")["runs"]], [created[0]["number"], 41])
        self.assertEqual(len(run.pulls()), 1)
        self.assertEqual(run.forge.issue()["state"], "open")
        self.assertEqual(run.claims(), [])
        self.assertFalse(run.worktree_path.exists())

    def test_a_continue_after_a_failed_release_resumes_landing_and_closes_out(self):
        run = self.stubbed(lock_release_fails=True)
        self.finish(run, "unreleased-lock", "owner-decision")
        root = run.runs()[0]
        run.forge.ref_store(run.fixture.slug, run.forge.refs())

        self.finish(run, "done")

        self.assertEqual(len(run.runs()), 1)
        continued = [e for e in run.events(root) if e["event"] == "run_continued"]
        self.assertEqual([e["step"] for e in continued], ["landing"])
        self.assertEqual(run.transitions(root)[-2:], [("landing", "done"), ("closing", "done")])
        self.assertEqual(len(run.pulls()), 1)
        self.assertEqual(run.pulls()[0]["state"], "MERGED")
        self.assertEqual(run.forge.issue()["state"], "closed")
        self.assertEqual(run.lock_refs(), {})
        self.assertEqual(run.claims(), [])
        self.assertFalse(run.worktree_path.exists())
        self.assertEqual(self.branches(run), "")


def flattened(suite):
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            yield from flattened(test)
        else:
            yield test


class StepCoverageTest(Scenario):
    ID = "m.T.test_a"

    def test_the_module_teardown_fails_naming_a_declared_step_no_run_visited(self):
        module = sys.modules[type(self).__module__]
        scope = {procedure for procedure, _ in module.STEPS.declared()}
        self.assertEqual(scope, {"setup", "deliver", "direct", "verify", "land", "close-out"})
        coverage = StepCoverage(PROCEDURES, tuple(sorted(scope)))
        for test_id in test_ids(module):
            coverage.select(test_id)
        coverage.record(coverage.declared() - {("direct", "escalated-settled")})

        with mock.patch.object(module, "STEPS", coverage), self.assertRaises(AssertionError) as raised:
            module.tearDownModule()

        self.assertIn("escalated-settled", str(raised.exception))

    def test_each_test_the_runner_selects_is_selected_on_the_module_coverage(self):
        self.assertIn(self.id(), STEPS.selected_ids())

    def test_every_test_class_of_the_module_is_a_scenario(self):
        module = sys.modules[type(self).__module__]

        loaded = list(flattened(unittest.TestLoader().loadTestsFromModule(module)))

        self.assertTrue(loaded)
        for test in loaded:
            self.assertIsInstance(test, Scenario, test.id())

    def test_every_run_of_the_module_is_built_through_the_shared_helper(self):
        module = sys.modules[type(self).__module__]
        tree = ast.parse(Path(module.__file__).read_text("utf-8"))
        allowed = {id(call) for function in ast.walk(tree)
                   if isinstance(function, ast.FunctionDef) and function.name == "stubbed"
                   for call in ast.walk(function)}

        direct = [call.lineno for call in ast.walk(tree)
                  if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
                  and call.func.id == "StubbedRun" and id(call) not in allowed]

        self.assertEqual(direct, [], "build a run with self.stubbed so it adopts the shared fixture and records its steps")

    def test_a_stubbed_run_records_the_steps_it_visited_on_the_module_coverage(self):
        module = sys.modules[type(self).__module__]
        coverage = StepCoverage(PROCEDURES)

        with mock.patch.object(module, "STEPS", coverage), \
                mock.patch.object(StubbedRun, "visited_steps", return_value={("setup", "contract")}):
            self.stubbed()
            self.doCleanups()

        self.assertEqual(coverage.recorded(), {("setup", "contract")})

    def test_a_declared_step_no_run_visited_fails_the_coverage_check(self):
        coverage = StepCoverage(PROCEDURES)
        coverage.select(self.ID)
        coverage.record(coverage.declared() - {("direct", "escalated-settled")})

        with self.assertRaises(AssertionError) as raised:
            coverage.check([self.ID])

        self.assertIn("escalated-settled", str(raised.exception))

    def test_a_visited_step_no_procedure_declares_fails_the_coverage_check(self):
        coverage = StepCoverage(PROCEDURES)
        coverage.select(self.ID)
        coverage.record(coverage.declared() | {("direct", "retired-step")})

        with self.assertRaises(AssertionError) as raised:
            coverage.check([self.ID])

        self.assertIn("retired-step", str(raised.exception))

    def test_a_visited_step_of_a_procedure_the_coverage_does_not_name_is_ignored(self):
        coverage = StepCoverage(PROCEDURES, ("direct",))
        coverage.select(self.ID)
        coverage.record(coverage.declared() | {("land-attempt", "renew")})

        result = coverage.check([self.ID])

        self.assertIsNone(result)

    def test_the_module_test_ids_leave_out_a_test_not_of_the_given_base(self):
        fake = types.ModuleType("fake")
        base = type("Base", (unittest.TestCase,), {"__module__": "fake"})
        fake.T = type("T", (base,), {"__module__": "fake", "test_a": lambda self: None})
        fake.U = type("U", (unittest.TestCase,), {"__module__": "fake", "test_b": lambda self: None})

        kept = test_ids(fake, base)
        every = test_ids(fake)

        self.assertEqual(kept, {"fake.T.test_a"})
        self.assertEqual(every, {"fake.T.test_a", "fake.U.test_b"})

    def test_a_step_id_visited_in_one_procedure_does_not_cover_the_same_id_in_another(self):
        coverage = StepCoverage(PROCEDURES)
        coverage.select(self.ID)
        coverage.record(coverage.declared() - {("land", "release")})

        self.assertIn(("close-out", "release"), coverage.recorded())
        with self.assertRaises(AssertionError) as raised:
            coverage.check([self.ID])

        self.assertIn("land.release", str(raised.exception))
        self.assertNotIn("close-out.release", str(raised.exception))

    def test_a_selected_test_whose_class_setup_skipped_does_not_silence_the_coverage_check(self):
        coverage = StepCoverage(PROCEDURES)

        cannot_start = unittest.SkipTest("the class cannot start")

        def skipping(cls) -> None:
            raise cannot_start

        fake = types.ModuleType("fake")
        fake.STEPS = coverage
        fake.T = type("T", (Scenario,), {"__module__": "fake", "setUpClass": classmethod(skipping),
                                         "test_a": lambda self: None})
        home, directory = os.environ["HOME"], FIXTURES.directory
        result = self.run_fake(fake)
        with self.assertRaises(AssertionError) as raised:
            coverage.finish(fake, Scenario)

        self.assertEqual((result.testsRun, len(result.skipped)), (0, 1))
        self.assertIn("direct.escalated-settled", str(raised.exception))
        self.assertEqual((os.environ["HOME"], FIXTURES.directory), (home, directory))

    def test_a_test_the_runner_built_and_did_not_run_is_not_selected(self):
        coverage = StepCoverage(PROCEDURES)
        fake = types.ModuleType("fake")
        fake.STEPS = coverage
        fake.T = type("T", (Scenario,), {"__module__": "fake", "test_a": lambda self: None})
        with mock.patch.dict(sys.modules, {"fake": fake}):
            unittest.TestLoader().loadTestsFromModule(fake)
            test_ids(fake)

        self.assertEqual(coverage.selected_ids(), frozenset())

    def fake_module(self, coverage: StepCoverage, visits: list) -> types.ModuleType:
        fake = types.ModuleType("fake")
        fake.STEPS = coverage
        fake.A = type("A", (Scenario,), {"__module__": "fake", "test_a": lambda self: coverage.record(visits)})
        fake.B = type("B", (Scenario,), {"__module__": "fake", "test_b": lambda self: None})
        return fake

    def run_fake(self, fake: types.ModuleType, only: type | None = None) -> unittest.TestResult:
        """Load the fake module whole, then run the tests of `only` (all of them without it)."""
        with mock.patch.dict(sys.modules, {"fake": fake}):
            loaded = flattened(unittest.TestLoader().loadTestsFromModule(fake))
            suite = unittest.TestSuite(test for test in loaded if only is None or isinstance(test, only))
            return unittest.TextTestRunner(stream=io.StringIO()).run(suite)

    def test_a_class_run_from_a_module_loaded_whole_checks_no_coverage(self):
        coverage = StepCoverage(PROCEDURES)
        fake = self.fake_module(coverage, [])

        result = self.run_fake(fake, fake.B)

        self.assertEqual(result.testsRun, 1)
        self.assertIsNone(coverage.finish(fake, Scenario))

    def test_a_second_suite_of_the_module_checks_its_coverage_after_a_first_suite_did(self):
        coverage = StepCoverage(PROCEDURES)
        visits = list(coverage.declared())
        fake = self.fake_module(coverage, visits)
        self.run_fake(fake)
        self.assertIsNone(coverage.finish(fake, Scenario))
        visits.clear()

        self.run_fake(fake)
        with self.assertRaises(AssertionError) as raised:
            coverage.finish(fake, Scenario)

        self.assertIn("direct.escalated-settled", str(raised.exception))

    def test_a_full_suite_checks_its_coverage_after_a_suite_of_part_of_the_module(self):
        coverage = StepCoverage(PROCEDURES)
        fake = self.fake_module(coverage, [])
        self.run_fake(fake, fake.B)
        self.assertIsNone(coverage.finish(fake, Scenario))

        self.run_fake(fake)
        with self.assertRaises(AssertionError) as raised:
            coverage.finish(fake, Scenario)

        self.assertIn("direct.escalated-settled", str(raised.exception))

    def test_a_full_run_whose_runs_together_visit_every_declared_step_passes(self):
        coverage = StepCoverage(PROCEDURES)
        steps = sorted(coverage.declared())
        coverage.select(self.ID)
        coverage.record(steps[::2])
        coverage.record(steps[1::2])

        result = coverage.check([self.ID])

        self.assertIsNone(result)

    def test_a_run_of_part_of_the_module_checks_no_coverage(self):
        coverage = StepCoverage(PROCEDURES)
        coverage.select(self.ID)

        result = coverage.check([self.ID, "m.T.test_b"])

        self.assertIsNone(result)

    def test_a_test_skipped_by_a_decorator_does_not_silence_the_coverage_check(self):
        coverage = StepCoverage(PROCEDURES)
        fake = types.ModuleType("fake")
        fake.T = type("T", (unittest.TestCase,), {"__module__": "fake", "test_a": lambda self: None,
                                                  "test_b": unittest.skip("off")(lambda self: None)})
        fake.U = type("U", (unittest.TestCase,), {"__module__": "fake", "__unittest_skip__": True,
                                                  "test_c": lambda self: None})
        coverage.select("fake.T.test_a")

        self.assertEqual(test_ids(fake), {"fake.T.test_a"})
        with self.assertRaises(AssertionError) as raised:
            coverage.check(test_ids(fake))

        self.assertIn("escalated-settled", str(raised.exception))

    def test_a_name_filter_on_the_command_line_does_not_narrow_the_module_test_ids(self):
        fake = types.ModuleType("fake")
        fake.T = type("T", (unittest.TestCase,), {"__module__": "fake", "test_a": lambda self: None,
                                                  "test_b": lambda self: None})

        with mock.patch.object(unittest.defaultTestLoader, "testNamePatterns", ["*.test_a"]):
            ids = test_ids(fake)

        self.assertEqual(ids, {"fake.T.test_a", "fake.T.test_b"})

    def test_the_module_test_ids_name_the_tests_of_the_module(self):
        module = sys.modules[type(self).__module__]
        landing = (f"{StubbedRunTest.__module__}.StubbedRunTest."
                   "test_a_stubbed_delivery_lands_a_merged_pull_request_and_closes_the_issue")

        ids = test_ids(module)

        self.assertIn(self.id(), ids)
        self.assertIn(landing, ids)
        for test_id in ids:
            self.assertTrue(test_id.rsplit(".", 1)[-1].startswith("test_"), test_id)


class GuardWorldTest(Scenario):
    """The stubbed world's pull-request forge and the real guard on the fixture's confirmed row."""

    BRANCH = "issue-41-add-a-greeting"

    def pushed(self, run: StubbedRun, branch: str | None = None) -> str:
        """Commit one file on a new branch of the fixture, push it to the bare origin, return its tip."""
        branch = branch or self.BRANCH
        root = run.fixture.root
        git = run.world.git
        git(root, "switch", "--quiet", "-c", branch)
        (root / f"{branch}.txt").write_text("a greeting\n", encoding="utf-8")
        git(root, "add", "-A")
        git(root, "commit", "--quiet", "-m", f"Work on {branch}")
        git(root, "switch", "--quiet", "main")
        git(root, "push", "--quiet", "origin", branch)
        return run.origin_tip(branch)

    def gh(self, run: StubbedRun, *argv: str) -> subprocess.CompletedProcess:
        return subprocess.run(["gh", *argv], cwd=run.fixture.root, env=run.env, capture_output=True,
                              text=True, timeout=120)

    def create(self, run: StubbedRun, branch: str | None = None) -> subprocess.CompletedProcess:
        return self.gh(run, "pr", "create", "--repo", "example/fixture", "--base", "main", "--head",
                       branch or self.BRANCH, "--title", "Add a greeting", "--body", "Closes #41.")

    def merge_text(self, head: str, number: int = 1) -> str:
        return (f"gh pr merge {number} --repo example/fixture --merge --match-head-commit {head} "
                f"--delete-branch")

    def view(self, run: StubbedRun) -> dict:
        done = self.gh(run, "pr", "view", "1", "--repo", "example/fixture", "--json",
                       "headRefOid,statusCheckRollup")
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout)

    def test_the_real_guard_of_the_stubbed_world_allows_the_fixtures_push_creation_and_pinned_merge(self):
        run = self.stubbed()
        head = self.pushed(run)
        self.pushed(run, "issue-41-second")
        created = self.create(run)
        self.assertEqual(created.returncode, 0, created.stderr)
        root = run.fixture.root
        texts = [
            f"git -C {root} push origin {self.BRANCH}",
            "gh pr create --repo example/fixture --base main --head issue-41-second "
            '--title "Add a greeting" --body "Closes #41. Delivered by the engine."',
            self.merge_text(head),
        ]

        for text in texts:
            with self.subTest(text):
                done = run.guard(text, root)
                self.assertEqual(done.returncode, 0, done.stderr)

        self.assertEqual([line["payload"]["tool_input"]["command"] for line in payloads(run.guard_log)],
                         texts)

    def test_a_run_without_required_checks_resolves_with_the_member_absent(self):
        run = self.stubbed(required_checks=())

        snapshot = resolve_project.resolve(run.fixture.root)

        self.assertNotIn("required_checks", snapshot["bindings"]["vcs"]["merge"])

    def test_without_declared_required_checks_the_real_guard_refuses_the_merge(self):
        run = self.stubbed(required_checks=())
        head = self.pushed(run)
        self.assertEqual(self.create(run).returncode, 0)

        done = run.guard(self.merge_text(head), run.fixture.root)

        self.assertEqual(done.returncode, 2, done.stderr)
        self.assertIn("protection lookup failed", done.stderr)

    def test_the_fake_merge_lands_only_the_pinned_head_and_deletes_the_branch(self):
        run = self.stubbed()
        head = self.pushed(run)
        self.assertEqual(self.create(run).returncode, 0)
        args = ("pr", "merge", "1", "--repo", "example/fixture", "--merge", "--delete-branch",
                "--match-head-commit")

        wrong = self.gh(run, *args, "0" * 40)
        self.assertEqual(wrong.returncode, 1, wrong.stderr)
        self.assertEqual(run.pulls()[0]["state"], "OPEN")
        right = self.gh(run, *args, head)

        self.assertEqual(right.returncode, 0, right.stderr)
        self.assertEqual(run.pulls()[0]["state"], "MERGED")
        merge = run.origin_tip("main")
        parents = run.world.git(run.fixture.root, "--git-dir", run.bare, "log", "-1",
                                "--format=%P", merge).split()
        self.assertEqual(parents[1], head)
        self.assertEqual(len(parents), 2)
        self.assertIsNone(run.origin_tip(self.BRANCH))

    def test_a_move_head_event_moves_the_branch_on_the_first_rollup_read(self):
        run = self.stubbed(forge_events=("move-head",))
        head = self.pushed(run)
        self.assertEqual(self.create(run).returncode, 0)

        first = self.view(run)
        moved = run.origin_tip(self.BRANCH)
        second = self.view(run)

        self.assertEqual(first["headRefOid"], head)
        self.assertEqual(first["statusCheckRollup"][0]["name"], "Fixture Checks")
        self.assertNotEqual(moved, head)
        self.assertEqual(second["headRefOid"], moved)
        self.assertEqual(run.origin_tip(self.BRANCH), moved)

    def test_a_steal_lock_event_hands_the_lock_to_a_second_open_pull_request(self):
        run = self.stubbed(forge_events=("steal-lock",))
        self.pushed(run)
        self.assertEqual(self.create(run).returncode, 0)

        self.view(run)

        self.assertEqual(run.lock_refs(), {"refs/agent-locks/land/main": run.stolen_sha})
        done = self.gh(run, "api", f"repos/example/fixture/commits/{run.stolen_sha}/pulls?per_page=100")
        self.assertEqual(done.returncode, 0, done.stderr)
        listed = json.loads(done.stdout)
        self.assertEqual([(p["state"], p["number"] != 1) for p in listed], [("open", True)])


if __name__ == "__main__":
    unittest.main()
