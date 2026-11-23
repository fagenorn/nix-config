"""`agent_tools.verification.suite_test_failures`: the suite-test-failures verify check."""
import contextlib
import io
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent_tools.system import forge_api
from agent_tools.verification import suite_test_failures

from tests.test_verify_checks import CHECKS, ROOT, SuiteWorld, committed_mode, forge, run_from_root

TIER = "fast"


def failure_log(*lines, summary=True):
    """A BOM-led, stamped job log of `lines`, closed by a one-failed-member summary unless `summary` is false."""
    stamp = "2026-11-18T00:00:01.1234567Z "
    kept = list(lines)
    if summary:
        kept += ["suite-runner:     1.0s wall     1.0s cpu failed tests/b.py",
                 "suite-runner: summary members=1 passed=0 failed=1 jobs=4 wall=2.0s cpu=2.0s"]
    return "﻿" + "".join(stamp + line + "\n" for line in kept)


def failures(world, test, n=20):
    """`suite_test_failures` over `world`'s forge, whose job logs are the world's."""
    def run_gh(argv, allow=()):
        prefix = f"repos/{world.REPO}/actions/jobs/"
        if argv[0] != "api" or not argv[1].startswith(prefix) or not argv[1].endswith("/logs"):
            raise AssertionError(f"unexpected gh {argv}")
        job_id = int(argv[1][len(prefix):-len("/logs")])
        return 0, world.logs.get(job_id, world.log())
    get, pages = forge(world.gets(), world.pages())
    with get, pages, mock.patch.object(forge_api, "run_gh", side_effect=run_gh):
        return suite_test_failures.suite_test_failures(
            world.REPO, world.WORKFLOW, world.JOB, world.BRANCH, world.MERGE, n, test)


class SuiteTestFailuresTest(unittest.TestCase):
    def test_a_failed_attempt_naming_the_test_inside_its_member_block_is_not_met(self):
        world = SuiteWorld()
        world.fail(105, log=failure_log("suite-runner: begin tests/b.py", "ERROR: test_x (tests.b.T.test_x)",
                                        "suite-runner: end tests/b.py failed exit=1 1.0s"))
        code, report = failures(world, "test_x")
        self.assertEqual((code, report["failures"], report["test"]), (1, [105], "test_x"))

    def test_after_runs_with_no_failure_are_met(self):
        code, report = failures(SuiteWorld(), "test_x")
        self.assertEqual((code, report["failures"], len(report["after"]), report["merge_run"]),
                         (0, [], 20, 100))

    def test_a_failed_attempt_for_another_test_is_met(self):
        world = SuiteWorld()
        world.fail(105, log=failure_log("FAIL: test_other (tests.b.T.test_other)"))
        code, report = failures(world, "test_x")
        self.assertEqual((code, report["failures"]), (0, []))

    def test_a_name_that_only_starts_with_the_test_is_not_its_failure(self):
        world = SuiteWorld()
        world.fail(105, log=failure_log("ERROR: test_x_slow (tests.b.T.test_x_slow)"))
        self.assertEqual(failures(world, "test_x")[0], 0)

    def test_a_failed_attempt_without_a_summary_is_not_met(self):
        world = SuiteWorld()
        world.fail(105, log=failure_log("the job died", summary=False))
        code, report = failures(world, "test_x")
        self.assertEqual((code, report["failures"], report["unattributed"]), (1, [], [105]))

    def test_a_failed_attempt_without_a_summary_naming_the_test_is_a_failure(self):
        world = SuiteWorld()
        world.fail(105, log=failure_log("ERROR: test_x (tests.b.T.test_x)", summary=False))
        code, report = failures(world, "test_x")
        self.assertEqual((code, report["failures"], report["unattributed"]), (1, [105], []))

    def test_a_subtest_failure_names_the_test(self):
        world = SuiteWorld()
        world.fail(107, log=failure_log("FAIL: test_x (tests.b.T.test_x) (tool='node')"))
        code, report = failures(world, "test_x")
        self.assertEqual((code, report["failures"]), (1, [107]))

    def test_a_run_naming_the_test_in_two_attempts_is_listed_once(self):
        world = SuiteWorld()
        world.attempts[106] = 2
        world.fail(106, attempt=1, log=failure_log("ERROR: test_x (m.T.test_x)"))
        world.fail(106, attempt=2, log=failure_log("ERROR: test_x (m.T.test_x)"))
        self.assertEqual(failures(world, "test_x")[1]["failures"], [106])

    def test_fewer_than_n_counted_after_runs_is_not_yet(self):
        world = SuiteWorld()
        world.set_job(110, status="in_progress", conclusion=None)
        self.assertEqual(failures(world, "test_x")[0], 75)

    def test_no_run_at_the_merge_is_not_yet_and_reads_no_log(self):
        world = SuiteWorld()
        gets = world.gets()
        gets[f"{world.LISTING}&head_sha={world.MERGE}&per_page=100"] = {"workflow_runs": []}
        get, pages = forge(gets, world.pages())
        with get, pages, mock.patch.object(forge_api, "run_gh", side_effect=AssertionError("read a log")):
            code, report = suite_test_failures.suite_test_failures(
                world.REPO, world.WORKFLOW, world.JOB, world.BRANCH, world.MERGE, 20, "test_x")
        self.assertEqual((code, report["merge_run"], report["failures"]), (75, None, []))

    def test_a_passing_attempt_log_is_never_read(self):
        world = SuiteWorld()
        get, pages = forge(world.gets(), world.pages())
        with get, pages, mock.patch.object(forge_api, "run_gh", side_effect=AssertionError("read a log")):
            code, _ = suite_test_failures.suite_test_failures(
                world.REPO, world.WORKFLOW, world.JOB, world.BRANCH, world.MERGE, 20, "test_x")
        self.assertEqual(code, 0)


class SuiteTestFailuresCommandTest(unittest.TestCase):
    ARGS = ["--repo", "fagenorn/nix-config", "--workflow", "ci.yaml", "--job", "Agent Workflow Tests",
            "--branch", "main", "--merge", "c" * 40, "--n", "6", "--test", "test_x"]

    def test_wrapper_maps_a_forge_error_to_exit_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.symlink(sys.executable, Path(tmp) / "python3")
            done = run_from_root(["/bin/sh", str(ROOT / CHECKS / "suite-test-failures"), *self.ARGS],
                                 {"PATH": tmp})
        self.assertEqual((done.returncode, done.stdout), (2, ""), done.stderr)
        self.assertIn("forge_error", done.stderr)

    def test_an_empty_test_name_is_a_usage_error(self):
        with mock.patch.object(suite_test_failures, "suite_test_failures",
                               side_effect=AssertionError("reached the forge")):
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    suite_test_failures.main([*self.ARGS[:-1], ""])
        self.assertEqual(raised.exception.code, 2)

    def test_the_wrapper_is_committed_executable_and_names_no_issue(self):
        self.assertEqual(committed_mode(f"{CHECKS}/suite-test-failures"), "100755")
        reference = re.compile(r"#\d|[Ii]ssues? \d")
        comments = [line for line in (ROOT / CHECKS / "suite-test-failures").read_text().splitlines()[1:]
                    if line.startswith("#")]
        self.assertEqual([line for line in comments if reference.search(line)], [])


if __name__ == "__main__":
    unittest.main()
