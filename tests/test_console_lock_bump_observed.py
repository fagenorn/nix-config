"""The evidence check that a lock bump merged with green required checks.

Run: just agent-workflow-tests
"""
import contextlib
import io
import json
import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from agent_tools.console import lock_bump
from agent_tools.console import lock_bump_forge
from agent_tools.console.lock_bump_forge import Checks
from agent_tools.system import forge_api
from agent_tools.system.forge_api import ForgeError
from tests.test_verify_checks import committed_mode

TIER = "fast"

SCRIPT = "home/common/verify-pending/checks/lock-bump-merged"
REPO = "octo/fixture"
PATH = f"repos/{REPO}/pulls?state=closed&per_page=100"
REV_A, REV_B, REV_C, HEAD = "a" * 40, "b" * 40, "c" * 40, "d" * 40


SINCE = "2026-12-01T00:00:00Z"
NOW = datetime(2026, 12, 3, tzinfo=timezone.utc)


def closed(number, ref, merged_at, base="main"):
    return {"number": number, "merged_at": merged_at, "base": {"ref": base},
            "head": {"ref": ref, "sha": HEAD, "repo": {"full_name": REPO}}}


def proven_line(revision, stamp):
    return json.dumps({"format": 1, "issue": 1, "project": REPO, "proven": stamp, "revision": revision, "run": 1})


class StandIn:
    def __init__(self, answer):
        self.answer = answer
        self.calls = []

    def __call__(self, *args):
        self.calls.append(args)
        return self.answer


class ObservedTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.proven = self.tmp / "proven.jsonl"
        self.lines = [proven_line(REV_A, "2026-11-30T06:00:00Z"), proven_line(REV_B, "2026-12-01T06:00:00Z"),
                      proven_line(REV_C, "2026-12-02T06:00:00Z")]
        self.proven.write_text("\n".join(self.lines) + "\n")

    def observe(self, pulls, answer=Checks("green", HEAD, ()), now=NOW):
        pages, verdict = StandIn([pulls]), StandIn(answer)
        result = lock_bump.observe(REPO, base="main", since=SINCE, proven=self.proven, pages=pages, verdict=verdict,
                                   now=lambda: now)
        return result, pages, verdict

    def test_the_first_proven_revision_after_activation_merged_green_is_met(self):
        pulls = [closed(9, f"lock-bump-{REV_B}", "2026-12-01T07:00:00Z"), closed(8, f"lock-bump-{REV_A}", None)]
        result, pages, verdict = self.observe(pulls)
        self.assertEqual(result, (0, {"pull": 9, "state": "met"}))
        self.assertEqual((pages.calls, verdict.calls), ([(PATH,)], [(REPO, 9)]))

    def test_a_bump_merged_before_activation_does_not_count(self):
        pulls = [closed(7, f"lock-bump-{REV_A}", "2026-11-30T07:00:00Z")]
        result, _, verdict = self.observe(pulls)
        self.assertEqual(result, (75, {"pull": None, "state": "not_yet"}))
        self.assertEqual(verdict.calls, [])

    def test_a_later_revisions_merge_does_not_stand_for_the_first(self):
        pulls = [closed(10, f"lock-bump-{REV_C}", "2026-12-02T07:00:00Z")]
        result, _, verdict = self.observe(pulls)
        self.assertEqual(result, (75, {"pull": None, "state": "not_yet"}))
        self.assertEqual(verdict.calls, [])

    def test_a_merge_into_another_base_does_not_count(self):
        pulls = [closed(9, f"lock-bump-{REV_B}", "2026-12-01T07:00:00Z", base="release")]
        result, _, _ = self.observe(pulls)
        self.assertEqual(result, (75, {"pull": None, "state": "not_yet"}))

    def test_a_merge_after_the_seven_days_is_not_met(self):
        pulls = [closed(9, f"lock-bump-{REV_B}", "2026-12-08T00:00:01Z")]
        result, _, verdict = self.observe(pulls, now=datetime(2026, 12, 9, tzinfo=timezone.utc))
        self.assertEqual(result, (1, {"pull": 9, "state": "not_met"}))
        self.assertEqual(verdict.calls, [])

    def test_a_merge_on_the_last_day_is_met(self):
        pulls = [closed(9, f"lock-bump-{REV_B}", "2026-12-08T00:00:00Z")]
        result, _, _ = self.observe(pulls, now=datetime(2026, 12, 9, tzinfo=timezone.utc))
        self.assertEqual(result, (0, {"pull": 9, "state": "met"}))

    def test_no_merged_bump_is_not_yet_inside_the_window_and_not_met_after_it(self):
        pulls = [closed(8, f"lock-bump-{REV_B}", None), closed(7, "adopt-0123456789ab", "2026-12-01T07:00:00Z")]
        self.assertEqual(self.observe(pulls)[0], (75, {"pull": None, "state": "not_yet"}))
        late = datetime(2026, 12, 9, tzinfo=timezone.utc)
        self.assertEqual(self.observe(pulls, now=late)[0], (1, {"pull": None, "state": "not_met"}))

    def test_no_proven_revision_after_activation_is_not_yet(self):
        self.proven.write_text(self.lines[0] + "\n")
        result, pages, _ = self.observe([closed(9, f"lock-bump-{REV_A}", "2026-12-01T07:00:00Z")])
        self.assertEqual(result, (75, {"pull": None, "state": "not_yet"}))
        self.assertEqual(pages.calls, [])

    def test_a_red_required_context_is_not_met(self):
        pulls = [closed(9, f"lock-bump-{REV_B}", "2026-12-01T07:00:00Z")]
        result, _, _ = self.observe(pulls, Checks("red", HEAD, ("Tests",)))
        self.assertEqual(result, (1, {"pull": 9, "state": "not_met"}))

    def test_main_prints_one_line_and_maps_a_forge_error_to_two(self):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(forge_api, "api_pages", side_effect=ForgeError("gh_failed", "down")) as pages, \
                mock.patch.object(forge_api, "run_gh", side_effect=AssertionError("no real gh")), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = lock_bump.main(["observed", "--repo", REPO, "--base", "main", "--since", SINCE,
                                   "--proven", str(self.proven)])
        self.assertEqual((code, out.getvalue()), (2, ""))
        self.assertTrue(err.getvalue().startswith("lock-bump: "))
        self.assertEqual(len(err.getvalue().splitlines()), 1)
        pages.assert_called_once_with(PATH)

    def test_the_check_script_runs_observed(self):
        text = (Path(__file__).resolve().parent.parent / SCRIPT).read_text()
        self.assertTrue(text.startswith("#!/bin/sh\n"))
        self.assertTrue(text.endswith(
            'PYTHONPATH=python exec python3 -m agent_tools.console.lock_bump observed "$@"\n'))
        self.assertEqual(committed_mode(SCRIPT), "100755")


MERGE = "e" * 40
PLATFORM = "octo/platform"


class Compare(StandIn):
    def __init__(self, answers):
        super().__init__(None)
        self.answers = answers

    def __call__(self, repo, base, head):
        self.calls.append((repo, base, head))
        return self.answers[head]


class MergedTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.proven = self.tmp / "proven.jsonl"
        self.proven.write_text("\n".join([
            proven_line(REV_A, "2026-11-30T06:00:00Z"), proven_line(REV_B, "2026-12-01T06:00:00Z"),
            proven_line(REV_C, "2026-12-02T06:00:00Z")]) + "\n")

    def observe(self, pulls, answers, checks=Checks("green", HEAD, ())):
        pages, verdict = StandIn([pulls]), StandIn(checks)
        compare = Compare(answers)
        result = lock_bump.observe_merged(REPO, base="main", merge=MERGE, platform_repo=PLATFORM,
                                          proven=self.proven, pages=pages, verdict=verdict, compare=compare)
        return result, pages, verdict, compare

    def test_the_first_merged_bump_of_a_proven_revision_holding_the_merge_is_met(self):
        pulls = [closed(10, f"lock-bump-{REV_C}", "2026-12-03T07:00:00Z"),
                 closed(9, f"lock-bump-{REV_B}", "2026-12-02T07:00:00Z"),
                 closed(8, f"lock-bump-{REV_A}", "2026-12-01T07:00:00Z")]
        result, pages, verdict, compare = self.observe(
            pulls, {REV_A: "behind", REV_B: "ahead", REV_C: "ahead"})
        self.assertEqual(result, (0, {"pull": 9, "state": "met"}))
        self.assertEqual(pages.calls, [(PATH,)])
        self.assertEqual(compare.calls, [(PLATFORM, MERGE, REV_A), (PLATFORM, MERGE, REV_B)])
        self.assertEqual(verdict.calls, [(REPO, 9)])

    def test_the_merge_commit_itself_proven_counts(self):
        pulls = [closed(9, f"lock-bump-{REV_B}", "2026-12-02T07:00:00Z")]
        result, _, _, _ = self.observe(pulls, {REV_B: "identical"})
        self.assertEqual(result, (0, {"pull": 9, "state": "met"}))

    def test_no_merged_bump_holding_the_merge_is_not_yet(self):
        pulls = [closed(9, f"lock-bump-{REV_B}", "2026-12-02T07:00:00Z"),
                 closed(8, f"lock-bump-{REV_A}", "2026-12-01T07:00:00Z")]
        result, _, verdict, _ = self.observe(pulls, {REV_A: "behind", REV_B: "diverged"})
        self.assertEqual(result, (75, {"pull": None, "state": "not_yet"}))
        self.assertEqual(verdict.calls, [])

    def test_a_merged_bump_of_an_unproven_revision_does_not_count(self):
        pulls = [closed(11, f"lock-bump-{'f' * 40}", "2026-12-02T07:00:00Z")]
        result, _, _, compare = self.observe(pulls, {"f" * 40: "ahead"})
        self.assertEqual(result, (75, {"pull": None, "state": "not_yet"}))
        self.assertEqual(compare.calls, [])

    def test_the_merge_form_ignores_a_bump_merged_into_another_base(self):
        pulls = [closed(9, f"lock-bump-{REV_B}", "2026-12-02T07:00:00Z", base="release")]
        result, _, _, _ = self.observe(pulls, {REV_B: "ahead"})
        self.assertEqual(result, (75, {"pull": None, "state": "not_yet"}))

    def test_a_merged_bump_holding_the_merge_with_a_red_required_context_is_not_met(self):
        pulls = [closed(9, f"lock-bump-{REV_B}", "2026-12-02T07:00:00Z")]
        result, _, _, _ = self.observe(pulls, {REV_B: "ahead"}, Checks("red", HEAD, ("Tests",)))
        self.assertEqual(result, (1, {"pull": 9, "state": "not_met"}))

    def test_no_proven_record_reads_no_pull(self):
        self.proven.unlink()
        pulls = [closed(9, f"lock-bump-{REV_B}", "2026-12-02T07:00:00Z")]
        result, pages, _, _ = self.observe(pulls, {REV_B: "ahead"})
        self.assertEqual(result, (75, {"pull": None, "state": "not_yet"}))
        self.assertEqual(pages.calls, [])

    def test_main_merge_form_refuses_a_missing_platform_repo_a_short_sha_and_both_forms(self):
        head = ["observed", "--repo", REPO, "--base", "main"]
        for tail in (["--merge", MERGE], ["--merge", "abc1234", "--platform-repo", PLATFORM],
                     ["--since", SINCE, "--merge", MERGE, "--platform-repo", PLATFORM],
                     ["--merge", MERGE, "--platform-repo", PLATFORM, "--within-days", "3"]):
            with self.subTest(tail=tail), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    lock_bump.main(head + tail)
                self.assertEqual(raised.exception.code, 2)

    def test_main_merge_form_prints_the_met_record(self):
        out = io.StringIO()
        pulls = [[closed(9, f"lock-bump-{REV_B}", "2026-12-02T07:00:00Z")]]
        with mock.patch.object(forge_api, "api_pages", return_value=pulls), \
                mock.patch.object(forge_api, "run_gh", side_effect=AssertionError("no real gh")), \
                mock.patch.object(lock_bump_forge.GitHubBumpForge, "compare", return_value="ahead") as compare, \
                mock.patch.object(lock_bump_forge.GitHubBumpForge, "verdict",
                                  return_value=Checks("green", HEAD, ())), \
                contextlib.redirect_stdout(out):
            code = lock_bump.main(["observed", "--repo", REPO, "--base", "main", "--merge", MERGE,
                                   "--platform-repo", PLATFORM, "--proven", str(self.proven)])
        self.assertEqual((code, out.getvalue()), (0, '{"pull":9,"state":"met"}\n'))
        compare.assert_called_once_with(PLATFORM, MERGE, REV_B)


if __name__ == "__main__":
    unittest.main()
