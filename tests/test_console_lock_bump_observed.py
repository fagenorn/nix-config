"""The evidence check that a lock bump merged with green required checks.

Run: just agent-workflow-tests
"""
import contextlib
import io
import unittest
from pathlib import Path
from unittest import mock

from agent_tools.console import lock_bump
from agent_tools.console.lock_bump_forge import Checks
from agent_tools.system import forge_api
from agent_tools.system.forge_api import ForgeError
from tests.test_verify_checks import committed_mode

SCRIPT = "home/common/verify-pending/checks/lock-bump-merged"
REPO = "octo/fixture"
PATH = f"repos/{REPO}/pulls?state=closed&per_page=100"
REV_A, REV_B, HEAD = "a" * 40, "b" * 40, "d" * 40


def closed(number, ref, merged_at):
    return {"number": number, "merged_at": merged_at, "head": {"ref": ref, "sha": HEAD, "repo": {"full_name": REPO}}}


class StandIn:
    def __init__(self, answer):
        self.answer = answer
        self.calls = []

    def __call__(self, *args):
        self.calls.append(args)
        return self.answer


class ObservedTest(unittest.TestCase):
    def observe(self, pulls, answer=Checks("green", HEAD, ())):
        pages, verdict = StandIn([pulls]), StandIn(answer)
        return lock_bump.observe(REPO, pages=pages, verdict=verdict), pages, verdict

    def test_a_merged_bump_with_green_required_contexts_is_met(self):
        pulls = [closed(9, f"lock-bump-{REV_B}", "2026-12-01T07:00:00Z"), closed(8, f"lock-bump-{REV_A}", None)]
        result, pages, verdict = self.observe(pulls)
        self.assertEqual(result, (0, {"pull": 9, "state": "met"}))
        self.assertEqual((pages.calls, verdict.calls), ([(PATH,)], [(REPO, 9)]))

    def test_no_merged_bump_is_not_yet(self):
        pulls = [closed(8, f"lock-bump-{REV_A}", None), closed(7, "adopt-0123456789ab", "2026-12-01T07:00:00Z")]
        result, _, verdict = self.observe(pulls)
        self.assertEqual(result, (75, {"pull": None, "state": "not_yet"}))
        self.assertEqual(verdict.calls, [])

    def test_a_red_required_context_is_not_met(self):
        pulls = [closed(9, f"lock-bump-{REV_B}", "2026-12-01T07:00:00Z")]
        result, _, _ = self.observe(pulls, Checks("red", HEAD, ("Tests",)))
        self.assertEqual(result, (1, {"pull": 9, "state": "not_met"}))

    def test_main_prints_one_line_and_maps_a_forge_error_to_two(self):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(forge_api, "api_pages", side_effect=ForgeError("gh_failed", "down")) as pages, \
                mock.patch.object(forge_api, "run_gh", side_effect=AssertionError("no real gh")), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = lock_bump.main(["observed", "--repo", REPO])
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


if __name__ == "__main__":
    unittest.main()
