"""Scenario tests for the shipped `deliver` procedure on the fixture project (#1526).

Each case runs `engine deliver` as a child process against a built fixture project, a fake tracker
and a stubbed launcher (`tests/engine_stubbed_world.py`), and reads what the run left.
"""

from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path

from agent_tools.claims import forge_markers
from tests.engine_stubbed_world import APPLIES, DIRECT, StubbedRun
from tests.guard_policy_world import install_platform_manifest_in_environ

TIER = "integration"  # every case builds a repository and runs the engine as a child process

setUpModule = install_platform_manifest_in_environ

PROCEDURES = Path(__file__).resolve().parents[1] / "python/agent_tools/delivery/procedures"
LOOK_BODY = ("Add a greet() function.\n\n## Acceptance criteria\n\n"
             "- [ ] [human] before merge: the greeting text — measured: the owner, on the pull request\n")
SETUP_WALK = [("contract", "ok"), ("review", "clear"), ("preflight", "clear"), ("existing", "absent"),
              ("applies", "applies"), ("acquire", "acquired"), ("worktree", "made"), ("look", "unmarked")]


def lane(name: str) -> dict:
    return {"verdict": APPLIES, "lane": {"lane": name, "why": "w"}}


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

    def child(self, run: StubbedRun) -> Path:
        return run.children(run.runs()[0])[0]


class StubbedRunTest(Scenario):
    def test_a_stubbed_delivery_ends_with_the_claim_held_by_the_run_the_worktree_on_the_branch_and_lane_direct(self):
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
        self.assertEqual(run.transitions(root), [("start", "done"), ("issue", "read"), ("lane", "direct")])
        launches = run.launches()
        self.assertIn(run.title, launches[1]["prompt"])
        self.assertEqual([launch["key"] for launch in launches], ["verdict", "lane"])


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

        self.assertEqual(run.transitions(self.child(run))[-1], ("look", "marked"))
        self.assertEqual([launch["key"] for launch in run.launches()], ["verdict"])


class RefusalTest(Scenario):
    def nothing_started(self, run: StubbedRun) -> None:
        self.assertEqual(run.claims(), [])
        self.assertFalse(run.worktree_path.exists())
        self.assertEqual(self.branches(run), "")

    def test_setup_refuses_a_closed_issue_and_makes_no_worktree(self):
        run = StubbedRun(self, state="closed")

        self.stopped(run, run.deliver(), "setup", "owner-decision")

        self.assertEqual(run.transitions(self.child(run))[-1], ("preflight", "closed"))
        self.nothing_started(run)
        self.assertEqual(run.launches(), [])

    def test_setup_refuses_an_issue_with_an_open_pull_request_and_makes_no_worktree(self):
        pull = {"number": 12, "state": "OPEN", "headRefName": "someone-else", "closingIssuesReferences": []}
        run = StubbedRun(self, pulls=[pull])

        self.stopped(run, run.deliver(), "setup", "owner-decision")

        self.assertEqual(run.transitions(self.child(run))[-1], ("preflight", "open-pr"))
        self.nothing_started(run)

    def test_setup_refuses_an_issue_that_no_longer_applies_comments_the_evidence_and_makes_no_worktree(self):
        evidence = "greet() already returns the greeting at origin/main."
        gone = {"verdict": "no-longer-applies", "details": "d", "evidence": evidence}
        run = StubbedRun(self, replies={"verdict": gone, "lane": DIRECT})

        self.stopped(run, run.deliver(), "setup", "owner-decision")

        transitions = run.transitions(self.child(run))
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

        transitions = run.transitions(self.child(run))
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

        self.assertEqual(run.transitions(self.child(run))[-1], ("acquire", "held_by"))
        self.assertEqual([claim.fields["holder"] for claim in run.claims()], [other])
        self.assertFalse(run.worktree_path.exists())

    def test_a_dirty_adopted_worktree_stops_at_dirty_and_keeps_the_change(self):
        run = StubbedRun(self)
        run.world.git(run.fixture.root, "worktree", "add", "--no-track", "-b", run.branch,
                      str(run.worktree_path), "origin/main")
        (run.worktree_path / "scratch.txt").write_text("keep\n", encoding="utf-8")

        self.stopped(run, run.deliver(), "dirty", "owner-decision")

        transitions = run.transitions(self.child(run))
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

        transitions = run.transitions(self.child(run))
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
        second = run.transitions(run.children(root)[-1])
        self.assertIn(("acquire", "already_held"), second)
        self.assertTrue(("worktree", "made") in second or ("worktree", "adopted") in second, second)
        claims = run.claims()
        self.assertEqual([claim.comment_id for claim in claims], [first[0].comment_id])
        self.assertEqual(self.branch_here(run, run.worktree_path), run.branch)


class CoverageTest(Scenario):
    def test_every_step_of_setup_and_deliver_is_visited_by_a_stubbed_run(self):
        gone = {"verdict": "no-longer-applies", "details": "d", "evidence": "already done at origin/main."}
        visited: set[str] = set()
        for replies in (None, {"verdict": gone, "lane": DIRECT}):
            run = StubbedRun(self, replies=replies)
            run.deliver()
            for directory in run.runs() + [c for r in run.runs() for c in run.children(r)]:
                visited |= {step for step, _ in run.transitions(directory)}

        declared = {step["id"] for name in ("setup", "deliver")
                    for step in json.loads((PROCEDURES / f"{name}.json").read_text("utf-8"))["steps"]}
        self.assertEqual(visited, declared)


if __name__ == "__main__":
    unittest.main()
