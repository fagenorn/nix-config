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
from agent_tools.delivery import engine_session
from agent_tools.project_contract import resolve_project
from tests.engine_fixture import FixtureProject
from tests.engine_guards import payloads
from tests.engine_stubbed_world import APPLIES, CLEAN_LITE, IMPLEMENTED, ROLES, StubbedRun
from tests.guard_policy_world import install_platform_manifest_in_environ

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


def lane(name: str) -> dict:
    return {"applies": APPLIES, "lane": {"lane": name, "why": "w"}}


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
    def test_a_stubbed_delivery_reaches_the_end_of_verify_with_the_stubs_commit_on_a_clean_branch(self):
        run = StubbedRun(self)

        done = run.deliver()

        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(run.line(done)["end"], "done")
        root = run.runs()[0]
        holder = f"{json.loads((root / 'run.json').read_text())['host']}/{root.name}"
        claims = run.claims()
        self.assertEqual(len(claims), 1)
        self.assertEqual((claims[0].fields["holder"], claims[0].fields["branch"]), (holder, run.branch))
        self.assertEqual(self.branch_here(run, run.worktree_path), run.branch)
        setup = run.children(root)[0]
        self.assertEqual(run.transitions(setup), SETUP_WALK)
        renewals = [e for e in run.events(setup) if e["event"] == "keep_alive_ran"]
        self.assertEqual([(e["step"], e["verdict"]) for e in renewals], [("worktree", "renewed")])
        self.assertEqual(run.transitions(root), [("start", "done"), ("issue", "read"), ("lane", "direct"),
                                                 ("direct-lane", "done"), ("verification", "done")])
        direct = self.child(run, "direct")
        transitions = run.transitions(direct)
        for edge in (("implement", "done"), ("implemented", "lite"), ("lite-group", "pass"),
                     ("lite-tally", "clean")):
            self.assertIn(edge, transitions)
        renewed = [e for e in run.events(direct) if e["event"] == "keep_alive_ran" and e["step"] == "implement"]
        self.assertEqual([e["verdict"] for e in renewed], ["renewed"])
        commit = self.stored(direct, "implement")["commit"]
        self.assertEqual(self.branch_commits(run), [commit])
        self.assertEqual(run.world.git(run.worktree_path, "log", "-1", "--format=%s").strip(), "stub change")
        self.assertEqual(run.world.git(run.worktree_path, "status", "--porcelain"), "")
        checks = self.stored(self.child(run, "verify"), "checks")
        self.assertEqual((checks["verdict"], checks["clean"]), ("passed", True))
        self.assertEqual([r["id"] for r in checks["results"]], FixtureProject.VERIFICATION)
        self.assertEqual([r["status"] for r in checks["results"]], ["pass", "pass"])
        launches = run.launches()
        self.assertIn(run.title, launches[1]["prompt"])
        self.assertEqual(model_of(self.launch(run, "implement")), "sonnet")
        self.assertEqual(self.keys(run), ["applies", "lane", "implement", "lite-review"])


class LaneTest(Scenario):
    def test_the_lane_answer_standard_stops_at_standard_not_on_engine(self):
        run = StubbedRun(self, replies=lane("standard"))

        self.stopped(run, run.deliver(), "standard-not-on-engine", "nothing")

        self.assertEqual(len(run.claims()), 1)
        self.assertEqual(self.branch_here(run, run.worktree_path), run.branch)

    def test_the_lane_answer_needs_design_stops_for_the_owners_decision(self):
        run = StubbedRun(self, replies=lane("needs-design"))

        self.stopped(run, run.deliver(), "needs-design", "owner-decision")

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
        claims = run.claims()
        self.assertEqual([claim.comment_id for claim in claims], [first[0].comment_id])
        self.assertEqual(self.branch_here(run, run.worktree_path), run.branch)


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

        self.assertEqual(self.keys(run), ["applies", "lane", "implement"])
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

        self.assertEqual(self.keys(run), ["applies", "lane", "implement", "lite-review", "lite-review"])
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


class CoverageTest(Scenario):
    def scenarios(self):
        gone = {"verdict": "no-longer-applies", "details": "d", "evidence": "already done at origin/main."}
        sensitive = dict(IMPLEMENTED, reply=dict(IMPLEMENTED["reply"], sensitive=True))
        fix = committing("fixture/second.py", "SECOND = 2\n")
        return (
            None,
            {"applies": gone},
            {"lite-review": lite_findings(), "lite-fix": fix, "lite-rereview": CLEAN_REREVIEW},
            {"lite-review": dict(CLEAN_LITE, escalate=True), "escalated": full_findings(),
             "escalated-fix": fix, "escalated-rereview": CLEAN_REREVIEW},
            {"implement": sensitive, "full-review": full_findings(), "full-fix": fix,
             "full-rereview": CLEAN_REREVIEW})

    def test_every_step_of_the_shipped_procedures_is_visited_by_a_stubbed_run(self):
        visited: set[str] = set()
        for replies in self.scenarios():
            run = StubbedRun(self, replies=replies)
            run.deliver()
            for directory in run.runs() + [c for r in run.runs() for c in run.children(r)]:
                visited |= {e["step"] for e in run.events(directory)
                            if e["event"] in ("step_entered", "transition_taken")}

        declared = {step["id"] for name in ("setup", "deliver", "direct", "verify")
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
