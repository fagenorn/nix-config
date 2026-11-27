"""One lock bump pass: open, settle and replace a bump, its record, and the glossary term.

Run: just agent-workflow-tests
"""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from agent_tools.console import lock_bump
from agent_tools.console.lock_bump import Step
from agent_tools.console.lock_bump_forge import Checks, OpenBump
from agent_tools.console.lock_bump_tree import BumpRefused, Built, branch_for, revision_of_branch
from tests.accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures

TIER = "fast"

REPO = Path(__file__).resolve().parent.parent
REV_A, REV_B, REV_C = "a" * 40, "b" * 40, "c" * 40
HEAD = "d" * 40
BUILT = "e" * 40
PROJECT = "octo/fixture"
ENTRIES = [{"project_id": PROJECT, "root": "/srv/fixture"}]


class FakeForge:
    def __init__(self):
        self.open = []
        self.states = {}
        self.status = "ahead"
        self.calls = []
        self.pulls = []
        self.numbers = iter(range(7, 100))

    def open_bumps(self, slug, base, cancel=None):
        self.calls.append(("open_bumps", slug, base))
        return list(self.open)

    def checks(self, slug, number, cancel=None):
        self.calls.append(("checks", slug, number))
        return self.states.get(number, Checks("pending", HEAD, ()))

    def open_pull(self, slug, branch, base, title, body, cancel=None):
        self.calls.append(("open_pull", slug, branch, base))
        self.pulls.append((title, body))
        number = next(self.numbers)
        self.open.append(OpenBump(number, revision_of_branch(branch)))
        return number

    def merge(self, slug, number, head, cancel=None):
        self.calls.append(("merge", slug, number, head))

    def close(self, slug, number, branch, cancel=None):
        self.calls.append(("close", slug, number, branch))
        self.open = [bump for bump in self.open if bump.number != number]

    def compare(self, repo, base, head, cancel=None):
        self.calls.append(("compare", repo, base, head))
        return self.status

    def named(self, kind):
        return [call for call in self.calls if call[0] == kind]


class FakeTracker:
    def __init__(self):
        self.issues = []
        self.known = {}
        self.finds = []
        self.stopped = False

    def find(self, project, revision):
        self.finds.append((project, revision))
        return self.known.get((project, revision))

    def create(self, title, body):
        if self.stopped:
            raise RuntimeError("console stopped")
        self.issues.append((title, body))
        return 500 + len(self.issues)


class FakeBuilder:
    def __init__(self, pin_answer=REV_A):
        self.pin_answer = pin_answer
        self.calls = []
        self.refusal = None

    def pin(self, root, slug, base, cancel=None):
        self.calls.append(("pin", root, slug, base))
        return self.pin_answer

    def build(self, root, slug, base, revision, cancel=None):
        self.calls.append(("build", root, slug, base, revision))
        return Built(branch_for(revision), BUILT)

    def verify(self, root, slug, revision, head, cancel=None):
        self.calls.append(("verify", root, slug, revision, head))
        if self.refusal:
            raise BumpRefused(self.refusal)


class PassCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.state_path = self.tmp / "state" / "lock-bumps.json"
        self.forge, self.tracker, self.builder = FakeForge(), FakeTracker(), FakeBuilder()

    def run_pass(self, latest=REV_B, entries=ENTRIES):
        return lock_bump.bump_pass(
            entries, project=PROJECT, base="main", platform_repo="octo/platform", latest=latest,
            forge=self.forge, tracker=self.tracker, builder=self.builder, state_path=self.state_path)

    def record(self):
        return lock_bump.read_state(self.state_path)["projects"].get(PROJECT)

    def remember(self, revision, outcome, pull=7, issue=None, origin=None, commit=None):
        lock_bump.write_state(self.state_path, {"format": 1, "projects": {PROJECT: {
            "revision": revision, "pull": pull, "outcome": outcome, "issue": issue, "from": origin,
            "commit": commit}}})

    def calls_of(self, name):
        return [call for call in self.builder.calls if call[0] == name]


class OpenTest(PassCase):
    def test_an_older_lock_opens_exactly_one_bump(self):
        first = self.run_pass()
        second = self.run_pass()
        self.assertEqual(self.forge.named("open_pull"), [("open_pull", PROJECT, branch_for(REV_B), "main")])
        self.assertEqual(self.calls_of("build"), [("build", Path("/srv/fixture"), PROJECT, "main", REV_B)])
        self.assertEqual(first, [Step(PROJECT, "opened", REV_B, 7, None, None)])
        self.assertEqual(second, [Step(PROJECT, "pending", REV_B, 7, None, None)])
        self.assertEqual(self.record(), {"revision": REV_B, "pull": 7, "outcome": "open", "issue": None,
                                         "from": REV_A, "commit": BUILT})

    def test_the_bump_pull_request_names_the_revision_and_carries_the_marker(self):
        self.run_pass()
        title, body = self.forge.pulls[0]
        self.assertEqual(title, f"Bump the agent platform to {REV_B[:12]}")
        self.assertIn(f"octo/platform@{REV_B}", body)
        self.assertIn(REV_A, body)
        self.assertEqual(body.splitlines()[-1], lock_bump.MARKER)

    def test_a_current_lock_opens_none(self):
        self.builder.pin_answer = REV_B
        self.assertEqual(self.run_pass(), [Step(PROJECT, "current", REV_B, None, None, None)])
        self.assertEqual((self.forge.named("compare"), self.calls_of("build"), self.forge.named("open_pull")),
                         ([], [], []))

    def test_a_lock_not_behind_the_proven_revision_opens_none(self):
        self.forge.status = "behind"
        self.assertEqual(self.run_pass(), [Step(PROJECT, "not_behind", REV_B, None, None, "behind")])
        self.assertEqual(self.calls_of("build"), [])

    def test_no_proven_revision_calls_nothing(self):
        self.assertEqual(self.run_pass(latest=None), [Step(PROJECT, "no_proven", None, None, None, None)])
        self.assertEqual((self.forge.calls, self.builder.calls, self.tracker.issues), ([], [], []))

    def test_an_open_bump_unknown_to_a_lost_record_is_adopted_not_doubled(self):
        self.forge.open.append(OpenBump(9, REV_B))
        self.run_pass()
        self.assertEqual(self.forge.named("open_pull"), [])
        self.assertEqual(self.record()["pull"], 9)


class SettleTest(PassCase):
    def test_green_required_checks_merge_the_bump_at_its_head(self):
        self.forge.open.append(OpenBump(9, REV_B))
        self.forge.states[9] = Checks("green", HEAD, ())
        self.assertEqual(self.run_pass(), [Step(PROJECT, "merged", REV_B, 9, None, None)])
        self.assertEqual(self.forge.named("merge"), [("merge", PROJECT, 9, HEAD)])
        self.assertEqual(self.record()["outcome"], "merged")
        self.assertEqual(self.tracker.issues, [])

    def test_a_head_that_is_not_the_recorded_built_commit_merges_nothing(self):
        self.forge.open.append(OpenBump(9, REV_B))
        self.forge.states[9] = Checks("green", HEAD, ())
        self.remember(REV_B, "open", pull=9, commit=BUILT)
        steps = self.run_pass()
        self.assertEqual(steps, [Step(PROJECT, "unverified", REV_B, 9, None, "head moved")])
        self.assertEqual((self.forge.named("merge"), self.record()["outcome"]), ([], "open"))

    def test_a_head_that_does_not_hold_the_bump_merges_nothing(self):
        self.forge.open.append(OpenBump(9, REV_B))
        self.forge.states[9] = Checks("green", HEAD, ())
        self.builder.refusal = "the bump branch does not lock bbbbbbbbbbbb"
        steps = self.run_pass()
        self.assertEqual([step.action for step in steps], ["unverified"])
        self.assertEqual(self.forge.named("merge"), [])
        self.assertEqual(self.calls_of("verify"), [("verify", Path("/srv/fixture"), PROJECT, REV_B, HEAD)])

    def test_the_recorded_built_commit_is_merged_after_it_verifies(self):
        self.forge.open.append(OpenBump(9, REV_B))
        self.forge.states[9] = Checks("green", BUILT, ())
        self.remember(REV_B, "open", pull=9, commit=BUILT)
        self.assertEqual(self.run_pass()[0].action, "merged")
        self.assertEqual(self.forge.named("merge"), [("merge", PROJECT, 9, BUILT)])

    def test_pending_checks_merge_nothing(self):
        self.forge.open.append(OpenBump(9, REV_B))
        self.run_pass()
        self.assertEqual([self.forge.named(kind) for kind in ("merge", "close", "open_pull")], [[], [], []])

    def test_a_newer_proven_revision_closes_the_open_bump_and_opens_its_own(self):
        self.forge.open.append(OpenBump(9, REV_A))
        self.remember(REV_A, "open", pull=9)
        steps = self.run_pass(latest=REV_C)
        kinds = [call[0] for call in self.forge.calls if call[0] in ("close", "open_pull")]
        self.assertEqual(kinds, ["close", "open_pull"])
        self.assertEqual(self.forge.named("close"), [("close", PROJECT, 9, branch_for(REV_A))])
        self.assertEqual(self.forge.named("open_pull"), [("open_pull", PROJECT, branch_for(REV_C), "main")])
        self.assertEqual([step.action for step in steps], ["replaced", "opened"])

    def test_a_merged_revision_is_never_opened_again(self):
        self.remember(REV_B, "merged")
        self.assertEqual(self.run_pass(), [Step(PROJECT, "done", REV_B, 7, None, None)])
        self.assertEqual((self.calls_of("pin"), self.forge.named("open_pull")), ([], []))


class RedTest(PassCase):
    def red_bump(self):
        self.forge.open.append(OpenBump(9, REV_B))
        self.forge.states[9] = Checks("red", HEAD, ("Tests",))

    def test_a_red_bump_files_one_issue_naming_the_check_and_the_project(self):
        self.red_bump()
        steps = self.run_pass()
        self.assertEqual(self.forge.named("merge"), [])
        (title, body), = self.tracker.issues
        self.assertIn("Tests", title)
        self.assertIn(PROJECT, title)
        self.assertIn(f"https://github.com/{PROJECT}/pull/9", body)
        self.assertIn(REV_B, body)
        self.assertEqual((self.record()["outcome"], self.record()["issue"]), ("red", 501))
        self.assertEqual(steps, [Step(PROJECT, "filed", REV_B, 9, 501, None)])

    def test_a_second_pass_over_the_same_red_bump_files_none(self):
        self.red_bump()
        self.run_pass()
        second = self.run_pass()
        self.assertEqual(len(self.tracker.issues), 1)
        self.assertEqual(second[0].action, "red_known")

    def test_a_green_reading_after_a_red_one_never_merges_the_bump(self):
        self.red_bump()
        self.run_pass()
        self.forge.states[9] = Checks("green", HEAD, ())
        steps = self.run_pass()
        self.assertEqual(steps, [Step(PROJECT, "red_known", REV_B, 9, 501, None)])
        self.assertEqual(self.forge.named("merge"), [])
        self.assertEqual(self.record()["outcome"], "red")

    def test_a_red_bump_whose_issue_exists_on_the_tracker_files_no_second_issue(self):
        self.red_bump()
        self.tracker.known[(PROJECT, REV_B)] = 77
        steps = self.run_pass()
        self.assertEqual(self.tracker.issues, [])
        self.assertEqual(steps, [Step(PROJECT, "red_known", REV_B, 9, 77, None)])
        self.assertEqual((self.record()["outcome"], self.record()["issue"]), ("red", 77))

    def test_a_stop_before_the_issue_is_filed_keeps_the_red_decision_and_a_green_rerun_never_merges(self):
        self.red_bump()
        self.tracker.stopped = True
        with self.assertRaises(RuntimeError):
            self.run_pass()
        self.assertEqual((self.record()["outcome"], self.record()["issue"]), ("red", None))
        self.tracker.stopped = False
        self.forge.states[9] = Checks("green", HEAD, ())
        steps = self.run_pass()
        self.assertEqual(steps, [Step(PROJECT, "filed", REV_B, 9, 501, None)])
        self.assertEqual((self.forge.named("merge"), self.record()["issue"]), ([], 501))

    def test_a_stop_after_the_issue_is_filed_before_it_is_saved_finds_that_issue_and_never_merges(self):
        self.red_bump()
        self.remember(REV_B, "red", pull=9)
        self.tracker.known[(PROJECT, REV_B)] = 77
        self.forge.states[9] = Checks("green", HEAD, ())
        steps = self.run_pass()
        self.assertEqual(steps, [Step(PROJECT, "red_known", REV_B, 9, 77, None)])
        self.assertEqual((self.forge.named("merge"), self.tracker.issues, self.record()["issue"]), ([], [], 77))

    def test_a_red_bump_closed_by_hand_is_retried_only_by_a_newer_revision(self):
        self.remember(REV_B, "red", issue=501)
        self.assertEqual(self.run_pass()[0].action, "done")
        self.assertEqual(self.calls_of("build"), [])
        self.assertEqual(self.run_pass(latest=REV_C)[0].action, "opened")
        self.assertEqual(self.calls_of("build")[0][-1], REV_C)


class ScopeTest(PassCase):
    def test_only_the_named_project_of_several_registered_gets_a_bump(self):
        entries = [{"project_id": "octo/p00", "root": "/srv/p00"}, *ENTRIES,
                   {"project_id": "octo/p01", "root": "/srv/p01"}]
        self.run_pass(entries=entries)
        self.assertEqual({call[1:4] for call in self.calls_of("build")},
                         {(Path("/srv/fixture"), PROJECT, "main")})
        self.assertEqual({call[1] for call in self.forge.calls}, {PROJECT, "octo/platform"})
        self.assertEqual(len(self.forge.named("open_pull")), 1)

    def test_an_unregistered_project_calls_nothing(self):
        steps = self.run_pass(entries=[{"project_id": "octo/p00", "root": "/srv/p00"}])
        self.assertEqual(steps, [Step(PROJECT, "unregistered", None, None, None, None)])
        self.assertEqual((self.forge.calls, self.builder.calls), ([], []))


class StateTest(PassCase):
    def test_a_malformed_record_is_refused_not_reset(self):
        self.state_path.parent.mkdir(parents=True)
        self.state_path.write_text(json.dumps({"format": 2}))
        with self.assertRaises(BumpRefused):
            self.run_pass()
        self.assertEqual(json.loads(self.state_path.read_text()), {"format": 2})


    def test_a_null_record_is_refused_not_an_attribute_error(self):
        self.state_path.parent.mkdir(parents=True)
        self.state_path.write_text("null")
        with self.assertRaises(BumpRefused):
            self.run_pass()
        self.assertEqual(self.state_path.read_text(), "null")


class PlatformTrackerTest(unittest.TestCase):
    def tracker(self, pages):
        seen = []

        def read(path):
            seen.append(path)
            return pages

        return lock_bump.PlatformTracker("octo/platform", pages=read, create=lambda *a: 1,
                                         author=lambda: "console-bot"), seen

    def test_the_issue_with_this_projects_and_revisions_marker_is_found(self):
        marker = lock_bump.red_marker(PROJECT, REV_B)
        other = lock_bump.red_marker(PROJECT, REV_A)
        mine = {"login": "Console-Bot"}
        pages = [[{"number": 3, "body": f"x\n\n{other}", "user": mine}, {"number": 4, "body": "none", "user": mine}],
                 [{"number": 5, "body": f"x\n\n{marker}", "user": mine, "pull_request": {}},
                  {"number": 6, "body": f"x\n\n{marker}", "user": mine}]]
        tracker, seen = self.tracker(pages)
        self.assertEqual(tracker.find(PROJECT, REV_B), 6)
        self.assertEqual(seen, ["repos/octo/platform/issues?state=all&per_page=100"])

    def test_no_marker_finds_none(self):
        mine = {"login": "console-bot"}
        tracker, _ = self.tracker([[{"number": 3, "body": None, "user": mine},
                                    {"number": 4, "body": "no marker", "user": mine}]])
        self.assertIsNone(tracker.find(PROJECT, REV_B))

    def test_a_marker_in_an_issue_of_another_author_is_not_this_bumps_report(self):
        marker = lock_bump.red_marker(PROJECT, REV_B)
        pages = [[{"number": 3, "body": f"x\n\n{marker}", "user": {"login": "someone-else"}},
                  {"number": 4, "body": f"x\n\n{marker}"}, {"number": 5, "body": f"x\n\n{marker}", "user": None}]]
        tracker, _ = self.tracker(pages)
        self.assertIsNone(tracker.find(PROJECT, REV_B))


class GlossaryTest(unittest.TestCase):
    def test_the_project_contract_glossary_defines_lock_bump(self):
        lines = (REPO / "docs/areas/project-contract/CONTEXT.md").read_text().splitlines()
        definition = lines[lines.index("**Lock bump**:") + 1]
        for word in ("**Proven revision**", "lock", "migration", "projections"):
            self.assertIn(word, definition)
        self.assertIn("| Lock bump | Project contract |", (REPO / "docs/CONTEXT-MAP.md").read_text())


if __name__ == "__main__":
    unittest.main()
