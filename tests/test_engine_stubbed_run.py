"""Scenario tests for the shipped `deliver` procedure on the fixture project.

Each case runs `engine deliver` as a child process against a built fixture project, a fake tracker
and a stubbed launcher (`tests/engine_stubbed_world.py`), and reads what the run left.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

from agent_tools.claims import forge_markers
from agent_tools.delivery import engine_session, holding
from agent_tools.project_contract import resolve_project
from agent_tools.verification import verify_block
from tests.engine_fixture import FixtureProject
from tests.engine_guards import payloads
from tests.engine_stubbed_world import (CLEAN_LITE, EVIDENCE_BODY, EVIDENCE_CHECK, GREEN, IMPLEMENTED, NOT_BEFORE,
                                        ROLES, StubbedRun, drafted)
from tests.guard_policy_world import REAL_GIT, install_platform_manifest_in_environ

TIER = "integration"  # every case builds a repository and runs the engine as a child process

setUpModule = install_platform_manifest_in_environ

PROCEDURES = Path(__file__).resolve().parents[1] / "python/agent_tools/delivery/procedures"
LOOK_BODY = ("Add a greet() function.\n\n## Acceptance criteria\n\n"
             "- [ ] [human] before merge: the greeting text — measured: the owner, on the pull request\n")
SETUP_WALK = [("contract", "ok"), ("review", "clear"), ("preflight", "clear"), ("existing", "absent"),
              ("applies", "applies"), ("acquire", "acquired"), ("worktree", "made"), ("look", "unmarked")]


FINDING = {"severity": "important", "file": "fixture/farewell.py:2", "failing_input": "farewell('')",
           "summary": "s"}
UNNAMED_LITE = dict(CLEAN_LITE, verdict="findings",
                    findings=[{"severity": "important", "file": "", "failing_input": "", "summary": "s"}])
CLEAN_FULL = {key: value for key, value in CLEAN_LITE.items() if key != "escalate"}
CLEAN_REREVIEW = {"verdict": "pass", "findings": []}
SHA = "a" * 40
CODEX_LIMIT = {"stdout": json.dumps({"status": 1, "error": "You've hit your usage limit."}), "exit": 1}


def lite_findings(**members) -> dict:
    return dict(CLEAN_LITE, verdict="findings", findings=[FINDING], **members)


def full_findings() -> dict:
    return dict(CLEAN_FULL, verdict="findings", findings=[FINDING])


def committing(path: str, text: str, **reply) -> dict:
    """A fix reply that commits `text` to `path`: the stub reports the commit it made."""
    return {"reply": {"status": "done", "notes": "n", "tests": [], **reply},
            "commit": {"path": path, "text": text}}


def implementing(path: str, text: str, **members) -> dict:
    return {"reply": {**IMPLEMENTED["reply"], **members}, "commit": {"path": path, "text": text}}


def stopping_after_verify(tmp: Path) -> Path:
    """A copy of the shipped procedures whose run is kept across a continue and stops once verified."""
    copy = tmp / "procedures"
    shutil.copytree(PROCEDURES, copy)
    path = copy / "deliver.json"
    document = json.loads(path.read_text("utf-8"))
    for step in document["steps"]:
        if step["id"] == "start":
            step["holds"] = "run"
        if step["id"] == "issue":
            step["on"]["refused"] = "done"  # the check wants one reachable step that still ends the run
        if step["id"] == "verification":
            step["on"]["done"] = "verified"
            step["on"]["verify"] = "landing"  # the check wants the landing step reachable too
    document["stops"]["verified"] = {"need": "owner-decision", "reenter": "verification"}
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return copy


def keeping_the_run(tmp: Path) -> Path:
    """A copy of the shipped procedures whose run is kept across a continue and otherwise unchanged."""
    copy = tmp / "kept-procedures"
    shutil.copytree(PROCEDURES, copy)
    path = copy / "deliver.json"
    document = json.loads(path.read_text("utf-8"))
    for step in document["steps"]:
        if step["id"] == "start":
            step["holds"] = "run"
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return copy


def model_of(launch: dict) -> str:
    return launch["argv"][launch["argv"].index("--model") + 1]


class Scenario(unittest.TestCase):
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
        run = StubbedRun(self)

        done = run.deliver()

        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(run.line(done)["end"], "done")
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
        run = StubbedRun(self, body=self.OVER_THE_RULE)

        done = run.deliver()

        self.stopped(run, done, "standard-not-on-engine", "nothing")
        self.assertIn(("lane", "standard"), run.transitions(run.runs()[0]))
        self.assertEqual(self.keys(run), ["applies"])
        self.assertEqual(len(run.claims()), 1)
        self.assertEqual(self.branch_here(run, run.worktree_path), run.branch)

    def test_a_body_naming_a_lane_path_stops_at_standard_not_on_engine(self):
        run = StubbedRun(self, body="Fix `secrets/x.yaml`.\n\n## Acceptance criteria\n\n- [ ] c\n")

        self.stopped(run, run.deliver(), "standard-not-on-engine", "nothing")

        self.assertEqual(self.keys(run), ["applies"])

    def test_a_continued_standard_stop_reads_the_issue_again(self):
        # The behaviour, not the stop's `reenter` value: the live `start` step is stale on every continue and is
        # re-entered first, so only test_engine_check's structural assertion on the three stops pins `reenter`.
        run = StubbedRun(self, body=self.OVER_THE_RULE)
        self.stopped(run, run.deliver(), "standard-not-on-engine", "nothing")

        self.stopped(run, run.deliver(), "standard-not-on-engine", "nothing")

        self.assertEqual(len(run.runs()), 1)
        events = run.events(run.runs()[0])
        self.assertEqual([e["event"] for e in events].count("run_continued"), 1)
        self.assertEqual(len([e for e in events if e["event"] == "step_entered" and e.get("step") == "issue"]), 2)

    def test_an_issue_with_a_look_marker_stops_at_look_not_on_engine_and_never_asks_the_lane(self):
        run = StubbedRun(self, body=LOOK_BODY)

        self.stopped(run, run.deliver(), "look-not-on-engine", "nothing")

        self.assertEqual(run.transitions(self.child(run, "setup"))[-1], ("look", "marked"))
        self.assertEqual(self.keys(run), ["applies"])

    def test_a_continued_run_reattaches_a_worktree_left_on_a_clean_detached_head_at_the_tip(self):
        run = StubbedRun(self, body=LOOK_BODY)
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

    def test_setup_refuses_a_closed_issue_and_makes_no_worktree(self):
        run = StubbedRun(self, state="closed")

        self.stopped(run, run.deliver(), "setup", "owner-decision")

        self.assertEqual(run.transitions(self.child(run, "setup"))[-1], ("preflight", "closed"))
        self.nothing_started(run)
        self.assertEqual(run.launches(), [])

    def test_setup_refuses_an_issue_with_an_open_pull_request_and_makes_no_worktree(self):
        pull = {"number": 12, "state": "OPEN", "headRefName": "someone-else", "closingIssuesReferences": []}
        run = StubbedRun(self, pulls=[pull])

        self.stopped(run, run.deliver(), "setup", "owner-decision")

        self.assertEqual(run.transitions(self.child(run, "setup"))[-1], ("preflight", "open-pr"))
        self.nothing_started(run)

    def test_setup_refuses_an_issue_that_no_longer_applies_comments_the_evidence_and_makes_no_worktree(self):
        evidence = "greet() already returns the greeting at origin/main."
        gone = {"verdict": "no-longer-applies", "details": "d", "evidence": evidence}
        run = StubbedRun(self, replies={"applies": gone})

        self.stopped(run, run.deliver(), "setup", "owner-decision")

        transitions = run.transitions(self.child(run, "setup"))
        self.assertIn(("applies", "no-longer-applies"), transitions)
        self.assertEqual(transitions[transitions.index(("applies", "no-longer-applies")) + 1],
                         ("note", "posted"))
        self.assertIn(evidence, [comment["body"] for comment in run.forge.stored()])
        self.nothing_started(run)

    def test_a_worktree_path_on_another_branch_stops_at_setup_and_takes_no_claim(self):
        run = StubbedRun(self)
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
        run = StubbedRun(self, comments=[held])

        self.stopped(run, run.deliver(), "claimed", "owner-decision")

        self.assertEqual(run.transitions(self.child(run, "setup"))[-1], ("acquire", "held_by"))
        self.assertEqual([claim.fields["holder"] for claim in run.claims()], [other])
        self.assertFalse(run.worktree_path.exists())

    def test_a_dirty_adopted_worktree_stops_at_dirty_and_keeps_the_change(self):
        run = StubbedRun(self)
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
        run = StubbedRun(self)
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

    def test_a_change_marked_sensitive_is_reviewed_under_the_full_reviewer(self):
        implemented = dict(IMPLEMENTED, reply=dict(IMPLEMENTED["reply"], sensitive=True))
        run = StubbedRun(self, replies={"implement": implemented, "full-review": CLEAN_FULL})

        self.finish(run, "done")

        transitions = run.transitions(self.child(run, "direct"))
        for edge in (("implemented", "full"), ("full-group", "pass"), ("full-tally", "clean")):
            self.assertIn(edge, transitions)
        self.assertIn("full-review", self.keys(run))
        self.assertNotIn("lite-review", self.keys(run))
        self.assertEqual(model_of(self.launch(run, "full-review")), self.reviewer_model(run))

    def test_an_escalate_reply_is_followed_by_the_full_reviewer(self):
        run = StubbedRun(self, replies={"lite-review": dict(CLEAN_LITE, escalate=True),
                                        "escalated": CLEAN_FULL})

        self.finish(run, "done")

        transitions = run.transitions(self.child(run, "direct"))
        for edge in (("lite-tally", "escalate"), ("escalated", "pass"), ("escalated-tally", "clean")):
            self.assertIn(edge, transitions)
        keys = self.keys(run)
        self.assertLess(keys.index("lite-review"), keys.index("escalated"))
        self.assertEqual(model_of(self.launch(run, "escalated")), self.reviewer_model(run))

    def test_findings_left_after_the_one_fix_round_stop_direct_review(self):
        run = StubbedRun(self, replies={
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
        run = StubbedRun(self, replies={"implement": refused})

        self.finish(run, "ineligible", "owner-decision")

        self.assertEqual(self.keys(run), ["applies", "implement"])
        steps = [step for step, _ in run.transitions(self.child(run, "direct"))]
        self.assertNotIn("lite-group", steps)
        self.assertNotIn("full-group", steps)
        self.assertEqual(self.branch_commits(run), [])

    def test_a_configured_independent_review_that_is_unavailable_stops_codex_unavailable(self):
        run = StubbedRun(self, review_code=[CODEX_LIMIT])

        self.finish(run, "codex-unavailable", "retry")

        self.assertEqual(len(run.companion_launches()), 2)
        self.assertIn("lite-review", self.keys(run))

    def test_a_project_that_configures_no_independent_review_runs_the_review_alone(self):
        run = StubbedRun(self)

        self.finish(run, "done")

        independent = self.stored(self.child(run, "direct"), "lite-independent")
        self.assertEqual((independent["verdict"], independent["findings"]), ("none", []))
        standin = shutil.which("codex-companion", path=run.env["PATH"])
        self.assertFalse(standin and Path(standin).is_relative_to(run.world.tmp), standin)
        self.assertEqual(run.companion_launches(), [])
        self.assertEqual(self.keys(run).count("lite-review"), 1)

    def test_an_unusable_review_is_asked_once_more_and_its_second_reply_is_used(self):
        run = StubbedRun(self, replies={"lite-review": UNNAMED_LITE, "lite-review.2": CLEAN_LITE})

        self.finish(run, "done")

        self.assertEqual(self.keys(run), ["applies", "implement", "lite-review", "lite-review"])
        tallies = [edge for edge in run.transitions(self.child(run, "direct")) if edge[0] == "lite-tally"]
        self.assertEqual(tallies, [("lite-tally", "unusable"), ("lite-tally", "clean")])

    def test_a_second_unusable_review_stops_direct_review(self):
        run = StubbedRun(self, replies={"lite-review": UNNAMED_LITE})

        self.finish(run, "direct-review", "owner-decision")

        self.assertEqual(self.keys(run).count("lite-review"), 2)
        self.assertNotIn("lite-fix", self.keys(run))

    def test_a_fix_that_reports_no_commit_stops_direct_fix(self):
        unfixed = {"status": "done", "start_head": SHA, "commit": "", "notes": "n", "tests": []}
        run = StubbedRun(self, replies={"lite-review": lite_findings(), "lite-fix": unfixed})

        self.finish(run, "direct-fix", "owner-decision")

        self.assertIn(("lite-fixed", "not-done"), run.transitions(self.child(run, "direct")))
        self.assertNotIn("lite-rereview", self.keys(run))


class VerifyTest(Scenario):
    def test_a_failing_verification_id_stops_verify(self):
        broken = implementing("fixture/greet.py", 'def greet(name: str) -> str:\n    return f"Hi, {name}."\n')
        run = StubbedRun(self, replies={"implement": broken})

        self.finish(run, "verify", "owner-decision")

        checks = self.stored(self.child(run, "verify"), "checks")
        self.assertEqual(checks["verdict"], "failed")
        self.assertEqual({r["id"]: r["status"] for r in checks["results"]}, {"lint": "pass", "test": "fail"})

    def test_an_id_whose_condition_matches_no_changed_path_is_recorded_skipped_with_its_reason(self):
        conditions = {"lint": {"when_changed": ["docs/**"], "skip_reason": "no documentation changed"}}
        run = StubbedRun(self, conditions=conditions)

        self.finish(run, "done")

        results = self.stored(self.child(run, "verify"), "checks")["results"]
        self.assertEqual([r["id"] for r in results], FixtureProject.VERIFICATION)
        lint, test = results
        self.assertEqual((lint["status"], lint["reason"]), ("skipped", "no documentation changed"))
        self.assertEqual(test["status"], "pass")

    def test_before_a_pull_request_verify_runs_lint_and_the_touched_checks_and_records_the_selection_and_slot_seconds(self):
        greet = 'def greet(name: str) -> str:\n    return "Hello, " + name + "."\n'
        run = StubbedRun(self, before_pull_request=True,
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
        run = StubbedRun(self, before_pull_request=True)
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
        run = StubbedRun(self, before_pull_request=True, rollup=RED)
        procedures = keeping_the_run(run.tmp)
        self.stopped(run, run.deliver(procedures), "checks", "owner-decision")
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
    def land_transitions(self, run: StubbedRun) -> list[tuple[str, str]]:
        return run.transitions(self.child(run, "land"))

    def prepared_head(self, run: StubbedRun) -> str:
        return self.stored(self.child(run, "land"), "prepare")["head"]

    def entered(self, run: StubbedRun) -> set[str]:
        return {e["step"] for e in run.events(self.child(run, "land")) if e["event"] == "step_entered"}


class LandGuardTest(Landing):
    def test_the_real_guard_allowed_the_push_the_pull_request_and_the_merge(self):
        run = StubbedRun(self)

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
        for step in ("push", "create", "merge"):
            self.assertEqual(outcomes[step], "ok", step)

    def test_without_declared_required_checks_the_merge_is_refused_and_nothing_merges(self):
        run = StubbedRun(self, required_checks=())
        before = run.origin_tip("main")

        self.finish(run, "merge", "owner-decision")

        land = self.child(run, "land")
        merge = self.stored(land, "merge")
        self.assertEqual(merge["verdict"], "refused")
        self.assertIn("protection lookup failed", merge["reason"])
        self.assertIn(("unlock-merge", "released"), run.transitions(land))
        self.assertEqual([p["state"] for p in run.pulls()], ["OPEN"])
        self.assertEqual(run.origin_tip("main"), before)
        self.assertEqual(run.forge.issue()["state"], "open")


class LandStopTest(Landing):
    def test_a_head_that_moves_after_the_lock_stops_head_moved_with_the_lock_released(self):
        run = StubbedRun(self, forge_events=("move-head",))

        self.finish(run, "head-moved", "owner-decision")

        transitions = self.land_transitions(run)
        for edge in (("lock", "held"), ("checks", "green"), ("head", "head-moved"),
                     ("unlock-moved", "released")):
            self.assertIn(edge, transitions)
        self.assertEqual(run.lock_refs(), {})
        self.assertEqual([p["state"] for p in run.pulls()], ["OPEN"])
        self.assertFalse({"recheck", "merge"} & self.entered(run))

    def test_a_red_required_check_stops_checks_with_the_lock_released(self):
        run = StubbedRun(self, rollup=RED)

        self.finish(run, "checks", "owner-decision")

        self.assertIn(("unlock-checks", "released"), self.land_transitions(run))
        self.assertEqual(run.lock_refs(), {})
        self.assertEqual([p["state"] for p in run.pulls()], ["OPEN"])

    def test_a_lock_taken_by_another_pull_request_stops_land_contended(self):
        run = StubbedRun(self, forge_events=("steal-lock",))

        self.finish(run, "land-contended", "retry")

        transitions = self.land_transitions(run)
        for edge in (("head", "pushed"), ("recheck", "contended"), ("unlock-contended", "released")):
            self.assertIn(edge, transitions)
        self.assertEqual(run.pulls()[0]["state"], "OPEN")
        self.assertNotIn("merge", self.entered(run))
        self.assertEqual(run.lock_refs(), {"refs/agent-locks/land/main": run.stolen_sha})

    def test_a_failed_release_stops_unreleased_lock(self):
        run = StubbedRun(self, lock_release_fails=True)

        self.finish(run, "unreleased-lock", "owner-decision")

        self.assertIn(("unlock", "unreleased"), self.land_transitions(run))
        self.assertEqual(run.pulls()[0]["state"], "MERGED")
        self.assertEqual(run.lock_refs(), {"refs/agent-locks/land/main": self.prepared_head(run)})

    def test_an_unreadable_rollup_stops_land_with_the_lock_released(self):
        run = StubbedRun(self, rollup=UNNAMED)

        self.finish(run, "land", "owner-decision")

        self.assertIn(("unlock-failed", "released"), self.land_transitions(run))
        self.assertEqual(run.lock_refs(), {})


class LandWaitTest(Landing):
    def test_the_land_run_records_a_started_and_ended_wait_for_the_lock_and_the_checks(self):
        run = StubbedRun(self)

        self.finish(run, "done")

        events = run.events(self.child(run, "land"))

        def at(kind: str, **match) -> list[int]:
            return [i for i, e in enumerate(events)
                    if e["event"] == kind and all(e.get(k) == v for k, v in match.items())]

        spans = {}
        for step in ("lock", "checks"):
            started, ended = at("wait_started", wait=step), at("wait_ended", wait=step)
            self.assertEqual((len(started), len(ended)), (1, 1), step)
            entered, stored = at("step_entered", step=step)[0], at("result_stored", step=step)[0]
            self.assertTrue(entered < started[0] < ended[0] < stored, step)
            spans[step] = (started[0], ended[0])
        self.assertLess(spans["lock"][1], spans["checks"][0])


class SettledTest(Landing):
    def earlier_merge(self, run: StubbedRun) -> tuple[str, str]:
        """A merge commit and its side head in the origin's object store, on no ref."""
        git, bare = run.world.git, run.bare
        tree = git(bare, "rev-parse", "main^{tree}").strip()
        main = git(bare, "rev-parse", "main").strip()
        side = git(bare, "commit-tree", tree, "-p", main, "-m", "earlier work").strip()
        return git(bare, "commit-tree", tree, "-p", main, "-p", side, "-m", "earlier merge").strip(), side

    def test_an_earlier_merged_pull_request_at_another_head_does_not_settle_the_landing(self):
        run = StubbedRun(self)
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
        self.assertIn(("merge", "ok"), walk)
        self.assertEqual([pull["number"] for pull in run.pulls()], [1, 2])
        landed = run.pulls()[1]
        self.assertEqual((landed["state"], landed["headRefOid"]), ("MERGED", self.prepared_head(run)))
        self.assertNotEqual(self.prepared_head(run), side)


HOLD_STEPS = {"hold-facts", "hold-look", "hold-draft", "hold-gate", "regrade", "hold-lint", "split",
              "hold-post", "hold-label", "once-run", "close"}


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
        self.assertEqual(hold_comments(run), [])
        bodies = [comment["body"] for comment in run.forge.stored()]
        self.assertFalse([b for b in bodies if b.startswith(("Held after the merge", "Delivered by PR"))],
                         bodies)
        self.assertFalse(held_label(run))
        self.assertEqual(run.forge.issue()["created"], [])
        self.assertEqual(len(run.claims()), 1)
        self.assertTrue(run.worktree_path.exists())

    def test_an_issue_with_one_evidence_criterion_ends_done_open_labelled_with_one_hold_comment(self):
        run = StubbedRun(self, body=EVIDENCE_BODY)

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
                          ("hold-gate", "ready"), ("regrade", "met"), ("hold-lint", "valid"),
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
        run = StubbedRun(self, body=EVIDENCE_BODY, replies={"regrade": unmet})

        self.finish(run, "code-unmet", "owner-decision")

        self.posted_nothing(run)
        child = self.child(run, "close-out")
        walk = run.transitions(child)
        self.assertLess(walk.index(("hold-gate", "ready")), walk.index(("regrade", "unmet")))
        self.assertFalse([t for t in walk if t[0] in ("hold-lint", "split", "hold-post")])
        self.assertEqual(run.transitions(run.runs()[0])[-1], ("closing", "code-unmet"))

    def refused(self, replies: dict, verdict: str) -> tuple:
        run = StubbedRun(self, body=EVIDENCE_BODY, replies=replies)

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
        run = StubbedRun(self, body=EVIDENCE_BODY, replies={"hold-draft": drafted(bad)})

        self.finish(run, "hold", "owner-decision")

        self.posted_nothing(run)
        child = self.child(run, "close-out")
        walk = run.transitions(child)
        order = [walk.index(t) for t in (("hold-gate", "ready"), ("regrade", "met"), ("hold-lint", "invalid"))]
        self.assertEqual(order, sorted(order))
        lint = self.stored(child, "hold-lint")
        self.assertEqual(lint["verdict"], "invalid")
        self.assertTrue([e for entry in lint["lints"] for e in entry["errors"]
                         if "checks[0].when.not_before" in json.dumps(e)], lint)
        self.assertFalse([t for t in walk if t[0] in ("split", "hold-post")])

    def test_a_run_cut_after_the_hold_comment_and_continued_leaves_one_hold_comment_and_one_split_issue(self):
        run = StubbedRun(self, body=SPLIT_BODY, blocks=(50,), fail_once=("add_label:needs-verification",),
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
        run = StubbedRun(self, lock_release_fails=True)
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


class CoverageTest(Landing):
    def scenarios(self):
        gone = {"verdict": "no-longer-applies", "details": "d", "evidence": "already done at origin/main."}
        sensitive = dict(IMPLEMENTED, reply=dict(IMPLEMENTED["reply"], sensitive=True))
        fix = committing("fixture/second.py", "SECOND = 2\n")
        return (
            {},
            {"replies": {"applies": gone}},
            {"replies": {"lite-review": lite_findings(), "lite-fix": fix, "lite-rereview": CLEAN_REREVIEW}},
            {"replies": {"lite-review": dict(CLEAN_LITE, escalate=True), "escalated": full_findings(),
                         "escalated-fix": fix, "escalated-rereview": CLEAN_REREVIEW}},
            {"replies": {"implement": sensitive, "full-review": full_findings(), "full-fix": fix,
                         "full-rereview": CLEAN_REREVIEW}},
            {"rollup": RED},
            {"rollup": UNNAMED},
            {"forge_events": ("move-head",)},
            {"forge_events": ("steal-lock",)},
            {"required_checks": ()},
            {"lock_release_fails": True},
            {"body": EVIDENCE_BODY})

    def test_every_step_of_the_shipped_procedures_is_visited_by_a_stubbed_run(self):
        visited: set[str] = set()
        for scenario in self.scenarios():
            run = StubbedRun(self, **scenario)
            run.deliver()
            if scenario.get("lock_release_fails"):
                run.forge.ref_store(run.fixture.slug, run.forge.refs())
                run.deliver()
            for directory in run.runs() + [c for r in run.runs() for c in run.children(r)]:
                visited |= {e["step"] for e in run.events(directory)
                            if e["event"] in ("step_entered", "transition_taken")}

        declared = {step["id"] for name in ("setup", "deliver", "direct", "verify", "land", "close-out")
                    for step in json.loads((PROCEDURES / f"{name}.json").read_text("utf-8"))["steps"]}
        self.assertEqual(visited, declared)


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
        run = StubbedRun(self)
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
        run = StubbedRun(self, required_checks=())

        snapshot = resolve_project.resolve(run.fixture.root)

        self.assertNotIn("required_checks", snapshot["bindings"]["vcs"]["merge"])

    def test_without_declared_required_checks_the_real_guard_refuses_the_merge(self):
        run = StubbedRun(self, required_checks=())
        head = self.pushed(run)
        self.assertEqual(self.create(run).returncode, 0)

        done = run.guard(self.merge_text(head), run.fixture.root)

        self.assertEqual(done.returncode, 2, done.stderr)
        self.assertIn("protection lookup failed", done.stderr)

    def test_the_fake_merge_lands_only_the_pinned_head_and_deletes_the_branch(self):
        run = StubbedRun(self)
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
        run = StubbedRun(self, forge_events=("move-head",))
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
        run = StubbedRun(self, forge_events=("steal-lock",))
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
