"""`agent_tools.verification.verify_checks`: the committed verify checks of issue 638."""
import contextlib
import dataclasses
import http.server
import inspect
import io
import json
import os
import pwd
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import tracemalloc
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from agent_tools.console import event_log, inbox
from agent_tools.console import manager as console_manager
from agent_tools.console import sprints as console_sprints
from agent_tools.console import view as console_view
from agent_tools.console.sprints import Manager, SprintState
from agent_tools.console.view import ProjectState
from agent_tools.delivery import agent_gate_bundle
from agent_tools.claims import forge_markers
from agent_tools.system import siblings
from agent_tools.verification import verify_checks, verify_exec, verify_issues
from agent_tools.system import forge_api
from agent_tools.verification.verify_checks import required_checks, self_hosted_runner

from . import console_test_support as support
from . import railway_world
from .guard_policy_world import GuardPolicyWorld
from .pre_push_world import PrePushWorld
from .railway_world import MERGE, deployment
from .test_railway_deploy_adapter import request as railway_request
from .test_agent_gate_bundle import IDENTITY, context, flat, stratum  # the emitted-bundle builders

ROOT = Path(__file__).resolve().parents[1]
CHECKS = "home/common/verify-pending/checks"


def run_from_root(argv, env_extra=None):
    env = {**os.environ, "PYTHONPATH": str(ROOT / "python"), **(env_extra or {})}
    return subprocess.run(argv, cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)


def committed_mode(path):
    return subprocess.run(["git", "-C", str(ROOT), "ls-files", "-s", path],
                          capture_output=True, text=True, check=True).stdout.split(" ")[0]


SINCE = datetime(2026, 11, 6, 17, 37, 11, tzinfo=timezone.utc)
SEARCH = ("search/issues?q=repo%3Aelevenyellow%2Fnodocom%20is%3Apr%20is%3Amerged%20base%3Adev"
          "%20merged%3A%3E2026-11-06T17%3A37%3A11Z&sort=created&order=asc&per_page=100")
SHA = "a" * 40
RUNS = f"repos/elevenyellow/nodocom/commits/{SHA}/check-runs?per_page=100"
STATUSES = f"repos/elevenyellow/nodocom/commits/{SHA}/statuses?per_page=100"
PROTECTION = "repos/elevenyellow/nodocom/branches/dev/protection/required_status_checks"


def forge(gets, pages):
    """Patch both forge reads; any read not listed fails the test."""
    def api_get(path, allow=()):
        if path not in gets:
            raise AssertionError(f"unexpected read {path}")
        return gets[path]

    def api_pages(path):
        if path not in pages:
            raise AssertionError(f"unexpected paginated read {path}")
        return pages[path]
    return (mock.patch.object(forge_api, "api_get", side_effect=api_get),
            mock.patch.object(forge_api, "api_pages", side_effect=api_pages))


def search_page(numbers, total=None, incomplete=False):
    return {"total_count": len(numbers) if total is None else total,
            "incomplete_results": incomplete, "items": [{"number": n} for n in numbers]}


def pull(merged, sha=SHA):
    return {"merged_at": merged, "head": {"sha": sha}}


def world(check_runs, statuses=(), required=("lint",), merged="2026-11-07T10:00:00Z"):
    gets = {
        "repos/elevenyellow/nodocom/pulls/2610": pull(merged),
        PROTECTION: {"checks": [{"context": c} for c in required], "contexts": list(required)},
    }
    pages = {
        SEARCH: [search_page([2610])],
        RUNS: [{"total_count": len(check_runs), "check_runs": list(check_runs)}],
        STATUSES: [list(statuses)],
    }
    return gets, pages


def run(name, conclusion="success", completed="2026-11-07T09:50:00Z", status="completed",
        app_id=None):
    found = {"name": name, "status": status, "conclusion": conclusion, "completed_at": completed}
    if app_id is not None:
        found["app"] = {"id": app_id}
    return found


class RequiredChecksTest(unittest.TestCase):
    def check(self, gets, pages):
        get_patch, pages_patch = forge(gets, pages)
        with get_patch, pages_patch:
            return required_checks("elevenyellow/nodocom", "dev", SINCE)

    def test_required_check_passed_before_merge_is_met(self):
        code, report = self.check(*world([run("lint")]))
        self.assertEqual((code, report["pr"], report["missing"]), (0, 2610, []))

    def test_check_completed_after_merge_is_not_met(self):
        code, report = self.check(*world([run("lint", completed="2026-11-07T10:05:00Z")]))
        self.assertEqual((code, report["missing"]), (1, ["lint"]))

    def test_failed_check_is_not_met(self):
        self.assertEqual(self.check(*world([run("lint", conclusion="failure")]))[0], 1)

    def test_commit_status_counts(self):
        statuses = [{"context": "lint", "state": "success", "updated_at": "2026-11-07T09:00:00Z"}]
        self.assertEqual(self.check(*world([], statuses))[0], 0)

    def test_a_success_status_replaced_by_a_later_failure_is_not_met(self):
        statuses = [{"context": "lint", "state": "failure", "updated_at": "2026-11-07T09:30:00Z"},
                    {"context": "lint", "state": "success", "updated_at": "2026-11-07T09:00:00Z"}]
        self.assertEqual(self.check(*world([], statuses))[0], 1)

    def test_a_check_from_another_app_than_the_required_one_is_not_met(self):
        gets, pages = world([run("lint", app_id=999)])
        gets[PROTECTION] = {"checks": [{"context": "lint", "app_id": 15368}], "contexts": ["lint"]}
        code, report = self.check(gets, pages)
        self.assertEqual((code, report["missing"]), (1, ["lint"]))

    def test_a_check_from_the_required_app_is_met(self):
        gets, pages = world([run("lint", app_id=999), run("lint", app_id=15368)])
        gets[PROTECTION] = {"checks": [{"context": "lint", "app_id": 15368}], "contexts": ["lint"]}
        self.assertEqual(self.check(gets, pages)[0], 0)

    def test_a_check_run_without_an_app_does_not_meet_a_bound_requirement(self):
        gets, pages = world([run("lint")])
        gets[PROTECTION] = {"checks": [{"context": "lint", "app_id": 15368}]}
        self.assertEqual(self.check(gets, pages)[0], 1)

    def test_a_commit_status_does_not_meet_a_bound_requirement(self):
        statuses = [{"context": "lint", "state": "success", "updated_at": "2026-11-07T09:00:00Z"}]
        gets, pages = world([], statuses)
        gets[PROTECTION] = {"checks": [{"context": "lint", "app_id": 15368}]}
        self.assertEqual(self.check(gets, pages)[0], 1)

    def test_an_unbound_requirement_accepts_any_app(self):
        for entry in ({"context": "lint", "app_id": None}, {"context": "lint", "app_id": -1}):
            gets, pages = world([run("lint", app_id=999)])
            gets[PROTECTION] = {"checks": [entry], "contexts": ["lint"]}
            self.assertEqual(self.check(gets, pages)[0], 0, entry)

    def test_the_legacy_contexts_list_does_not_loosen_a_bound_requirement(self):
        gets, pages = world([run("lint", app_id=999)])
        gets[PROTECTION] = {"checks": [{"context": "lint", "app_id": 15368}],
                            "contexts": ["lint"]}
        self.assertEqual(self.check(gets, pages)[0], 1)

    def test_each_app_bound_to_the_same_context_must_have_passed(self):
        gets, pages = world([run("lint", app_id=1)])
        gets[PROTECTION] = {"checks": [{"context": "lint", "app_id": 1},
                                       {"context": "lint", "app_id": 2}]}
        self.assertEqual(self.check(gets, pages)[0], 1)
        gets, pages = world([run("lint", app_id=1), run("lint", app_id=2)])
        gets[PROTECTION] = {"checks": [{"context": "lint", "app_id": 1},
                                       {"context": "lint", "app_id": 2}]}
        self.assertEqual(self.check(gets, pages)[0], 0)

    def test_a_malformed_app_id_is_refused(self):
        gets, pages = world([run("lint")])
        gets[PROTECTION] = {"checks": [{"context": "lint", "app_id": "15368"}]}
        with self.assertRaises(forge_api.ForgeError):
            self.check(gets, pages)

    def test_no_required_checks_is_not_met(self):
        self.assertEqual(self.check(*world([run("lint")], required=()))[0], 1)

    def test_no_merged_pull_request_is_not_yet(self):
        code, report = self.check({}, {SEARCH: [search_page([])]})
        self.assertEqual((code, report["pr"]), (75, None))

    def test_the_earliest_merge_on_a_later_page_is_the_one_judged(self):
        gets, pages = world([run("lint")])
        later = "b" * 40
        gets["repos/elevenyellow/nodocom/pulls/2600"] = pull("2026-11-08T10:00:00Z", later)
        gets["repos/elevenyellow/nodocom/pulls/2610"] = pull("2026-11-07T10:00:00Z")
        pages[SEARCH] = [search_page([2600], total=2), search_page([2610], total=2)]
        code, report = self.check(gets, pages)
        self.assertEqual((code, report["pr"], report["merged_at"]), (0, 2610, "2026-11-07T10:00:00Z"))

    def test_a_merge_at_or_before_the_since_instant_is_not_judged(self):
        gets, pages = world([run("lint")], merged="2026-11-06T17:37:11Z")
        code, report = self.check(gets, pages)
        self.assertEqual((code, report["pr"]), (75, None))

    def test_a_success_status_after_the_merge_is_not_met(self):
        statuses = [{"context": "lint", "state": "success", "updated_at": "2026-11-07T10:30:00Z"}]
        self.assertEqual(self.check(*world([], statuses))[0], 1)

    def test_a_status_page_that_is_not_a_list_is_refused(self):
        gets, pages = world([run("lint")])
        pages[STATUSES] = [{"message": "nope"}]
        with self.assertRaises(forge_api.ForgeError):
            self.check(gets, pages)

    def test_an_incomplete_search_is_refused(self):
        gets, pages = world([run("lint")])
        pages[SEARCH] = [search_page([2610], incomplete=True)]
        with self.assertRaises(forge_api.ForgeError) as raised:
            self.check(gets, pages)
        self.assertEqual(raised.exception.code, "payload_invalid")

    def test_a_truncated_search_is_refused(self):
        gets, pages = world([run("lint")])
        pages[SEARCH] = [search_page([2610], total=1500)]
        with self.assertRaises(forge_api.ForgeError):
            self.check(gets, pages)

    def test_check_runs_on_a_second_page_count_and_a_short_listing_is_refused(self):
        gets, pages = world([])
        pages[RUNS] = [{"total_count": 101, "check_runs": [run(f"other-{i}") for i in range(100)]},
                       {"total_count": 101, "check_runs": [run("lint")]}]
        self.assertEqual(self.check(gets, pages)[0], 0)
        pages[RUNS] = [{"total_count": 101, "check_runs": [run(f"other-{i}") for i in range(100)]}]
        with self.assertRaises(forge_api.ForgeError):
            self.check(gets, pages)

    def test_forge_error_propagates(self):
        with mock.patch.object(forge_api, "api_pages",
                               side_effect=forge_api.ForgeError("gh_failed", "boom")):
            with self.assertRaises(forge_api.ForgeError):
                required_checks("elevenyellow/nodocom", "dev", SINCE)


class RequiredChecksCommandTest(unittest.TestCase):
    def test_wrapper_maps_a_forge_error_to_exit_2(self):
        # PATH holds only python3, so the wrapper finds its interpreter and gh is missing.
        with tempfile.TemporaryDirectory() as tmp:
            os.symlink(sys.executable, Path(tmp) / "python3")
            done = run_from_root(["/bin/sh", str(ROOT / CHECKS / "required-checks"),
                                  "--repo", "elevenyellow/nodocom", "--base", "dev",
                                  "--since", "2026-11-06T17:37:11Z"], {"PATH": tmp})
        self.assertEqual((done.returncode, done.stdout), (2, ""), done.stderr)
        self.assertIn("forge_error", done.stderr)

    def test_bad_repo_is_a_usage_error(self):
        done = run_from_root([sys.executable, "-m", "agent_tools.verification.verify_checks", "required-checks",
                              "--repo", "nodocom", "--base", "dev", "--since", "2026-11-06T17:37:11Z"])
        self.assertEqual(done.returncode, 2)

    def test_bad_repo_never_reaches_the_forge(self):
        with mock.patch.object(verify_checks, "required_checks",
                               side_effect=AssertionError("reached the forge")):
            with self.assertRaises(SystemExit) as raised:
                verify_checks.main(["required-checks", "--repo", "nodocom", "--base", "dev",
                                    "--since", "2026-11-06T17:37:11Z"])
        self.assertEqual(raised.exception.code, 2)

    def test_wrapper_is_committed_executable(self):
        self.assertEqual(committed_mode(f"{CHECKS}/required-checks"), "100755")


class SuiteWorld:
    """A forge for the suite-regressions check: before runs 1..N, the merge run 100 and after runs 100..119."""
    REPO, WORKFLOW, JOB, BRANCH = "fagenorn/nix-config", "ci.yaml", "Agent Workflow Tests", "main"
    MERGE = "c" * 40
    STAMP = "2026-11-18T00:00:00Z"
    LISTING = "repos/fagenorn/nix-config/actions/workflows/ci.yaml/runs?branch=main&event=push"
    PAGE = 100

    def __init__(self, before=20, after=21, after_base=100):
        self.after_base = after_base
        self.before_ids = list(range(1, before + 1))
        self.after_ids = list(range(after_base, after_base + after))
        self.attempts = {}
        self.jobs = {}
        self.logs = {}

    @staticmethod
    def log(rows=(("tests/a.py", True), ("tests/b.py", True)), summary=None, prefix="\ufeff"):
        stamp = "2026-11-18T00:00:01.1234567Z "
        lines = []
        for member, passed in rows:
            state = "passed" if passed else "failed"
            lines += [f"suite-runner: begin {member}", f"{member} output", f"end noise",
                      f"suite-runner: end {member} {state} exit={0 if passed else 1} 1.0s"]
        for member, passed in rows:
            lines.append(f"suite-runner:     1.0s wall     1.0s cpu {'passed' if passed else 'failed'} {member}")
        if summary is None:
            ok = sum(1 for _, passed in rows if passed)
            summary = (len(rows), ok, len(rows) - ok)
        lines.append("suite-runner: summary members=%d passed=%d failed=%d jobs=4 wall=2.0s cpu=2.0s" % summary)
        return prefix + "\n".join(stamp + line for line in lines) + "\n"

    def run(self, run_id, created):
        return {"id": run_id, "created_at": created, "run_attempt": self.attempts.get(run_id, 1)}

    def before_created(self, run_id):
        return (datetime(2026, 11, 1, tzinfo=timezone.utc) + timedelta(minutes=run_id)).strftime("%Y-%m-%dT%H:%M:%SZ")

    def after_created(self, run_id):
        return (datetime(2026, 11, 18, tzinfo=timezone.utc)
                + timedelta(minutes=run_id - self.after_base)).strftime("%Y-%m-%dT%H:%M:%SZ")

    def set_job(self, run_id, status="completed", conclusion="success", attempt=1):
        self.jobs[(run_id, attempt)] = (status, conclusion)

    def fail(self, run_id, rows=(("tests/a.py", True), ("tests/b.py", False)), attempt=1, log=None):
        self.set_job(run_id, conclusion="failure", attempt=attempt)
        self.logs[1000 * attempt + run_id] = self.log(rows) if log is None else log

    def gets(self):
        gets = {f"{self.LISTING}&head_sha={self.MERGE}&per_page=100":
                {"workflow_runs": [self.run(100, self.STAMP)]},
                }
        for run_id in self.before_ids + self.after_ids:
            for attempt in range(1, self.attempts.get(run_id, 1) + 1):
                status, conclusion = self.jobs.get((run_id, attempt), ("completed", "success"))
                gets[f"repos/{self.REPO}/actions/runs/{run_id}/attempts/{attempt}/jobs?per_page=100"] = {
                    "jobs": [{"id": 5, "name": "Nix Eval", "status": "completed", "conclusion": "failure"},
                             {"id": 1000 * attempt + run_id, "name": self.JOB,
                              "status": status, "conclusion": conclusion}]}
        return gets

    def pages(self):
        runs = [self.run(i, self.after_created(i)) for i in reversed(self.after_ids)]
        earlier = [self.run(i, self.before_created(i)) for i in reversed(self.before_ids)]
        return {f"{self.LISTING}&created=>={self.STAMP}&per_page=100":
                [{"total_count": len(runs), "workflow_runs": runs}],
                f"{self.LISTING}&created=<{self.STAMP}&per_page=100":
                [{"total_count": len(earlier), "workflow_runs": earlier[at:at + self.PAGE]}
                 for at in range(0, len(earlier), self.PAGE)]}

    def check(self, n=20):
        def run_gh(argv, allow=()):
            prefix = f"repos/{self.REPO}/actions/jobs/"
            if argv[0] != "api" or not argv[1].startswith(prefix) or not argv[1].endswith("/logs"):
                raise AssertionError(f"unexpected gh {argv}")
            job_id = int(argv[1][len(prefix):-len("/logs")])
            return 0, self.logs.get(job_id, self.log())
        get, pages = forge(self.gets(), self.pages())
        with get, pages, mock.patch.object(forge_api, "run_gh", side_effect=run_gh):
            return verify_checks.suite_regressions(
                self.REPO, self.WORKFLOW, self.JOB, self.BRANCH, self.MERGE, n)


class SuiteRegressionsTest(unittest.TestCase):
    def test_all_after_runs_passing_is_met(self):
        code, report = SuiteWorld().check()
        self.assertEqual((code, report["regressions"], report["unattributed"]), (0, {}, []))
        self.assertEqual(len(report["after"]), 20)
        self.assertEqual(report["before"], list(range(20, 0, -1)))

    def test_a_member_failing_after_that_passed_before_is_not_met(self):
        world = SuiteWorld()
        world.fail(105)
        code, report = world.check()
        self.assertEqual((code, report["regressions"]), (1, {"tests/b.py": [105]}))

    def test_a_member_that_failed_before_too_is_not_a_regression(self):
        world = SuiteWorld()
        world.fail(3)
        world.fail(105)
        self.assertEqual(world.check()[0], 0)

    def test_a_member_absent_before_is_not_a_regression(self):
        world = SuiteWorld()
        world.fail(105, rows=(("tests/a.py", True), ("tests/new.py", False)))
        self.assertEqual(world.check()[0], 0)

    def test_fewer_than_n_completed_after_runs_is_not_yet(self):
        world = SuiteWorld()
        world.set_job(110, status="in_progress", conclusion=None)
        self.assertEqual(world.check()[0], 75)

    def test_no_run_at_the_merge_is_not_yet(self):
        world = SuiteWorld()
        gets = world.gets()
        gets[f"{world.LISTING}&head_sha={world.MERGE}&per_page=100"] = {"workflow_runs": []}
        get, pages = forge(gets, world.pages())
        with get, pages:
            code, report = verify_checks.suite_regressions(
                world.REPO, world.WORKFLOW, world.JOB, world.BRANCH, world.MERGE, 20)
        self.assertEqual((code, report["merge_run"]), (75, None))

    def test_an_after_failure_without_a_summary_is_not_met(self):
        world = SuiteWorld()
        world.fail(105, log="2026-11-18T00:00:01Z the job died\n")
        code, report = world.check()
        self.assertEqual((code, report["unattributed"]), (1, [105]))

    def test_timing_rows_inside_a_member_block_are_not_read(self):
        world = SuiteWorld()
        stamp = "2026-11-18T00:00:01.1234567Z "
        inside = (stamp + "suite-runner:     1.0s wall     1.0s cpu failed tests/b.py\n")
        text = world.log()
        text = text.replace(stamp + "tests/a.py output\n", stamp + "tests/a.py output\n" + inside, 1)
        world.logs[1000 + 3] = text
        world.fail(106)
        code, report = world.check()
        self.assertEqual((code, report["regressions"]), (1, {"tests/b.py": [106]}))

    def test_cancelled_after_runs_are_passed_over(self):
        world = SuiteWorld()
        world.set_job(101, conclusion="cancelled")
        code, report = world.check()
        self.assertEqual(code, 0)
        self.assertNotIn(101, report["after"])
        self.assertEqual(len(report["after"]), 20)

    def test_fewer_than_n_before_runs_is_a_forge_error(self):
        with self.assertRaises(forge_api.ForgeError) as raised:
            SuiteWorld(before=19).check()
        self.assertEqual(raised.exception.code, "payload_invalid")

    def test_a_failure_hidden_by_a_passing_rerun_is_not_met(self):
        world = SuiteWorld()
        world.attempts[105] = 2
        world.fail(105, attempt=1)
        world.set_job(105, attempt=2)
        code, report = world.check()
        self.assertEqual((code, report["regressions"]), (1, {"tests/b.py": [105]}))
        self.assertEqual(report["after"].count(105), 1)
        self.assertEqual(len(report["after"]), 20)

    def test_an_after_summary_that_disagrees_with_its_rows_is_not_met(self):
        world = SuiteWorld()
        world.fail(105, log=world.log(rows=(("tests/a.py", True),), summary=(2, 1, 1)))
        code, report = world.check()
        self.assertEqual((code, report["unattributed"], report["regressions"]), (1, [105], {}))

    def test_a_before_run_without_a_complete_summary_is_passed_over(self):
        world = SuiteWorld(before=22)
        world.fail(22, log="no summary here\n")
        world.fail(21, rows=(("tests/a.py", True), ("tests/b.py", True)),
                   log=world.log(summary=(3, 2, 0)))
        code, report = world.check()
        self.assertEqual(code, 0)
        self.assertEqual(report["before"], list(range(20, 0, -1)))
        self.assertEqual(report["before_skipped"], [22, 21])

    def test_a_baseline_short_of_complete_logs_is_a_forge_error(self):
        world = SuiteWorld(before=21)
        world.fail(21, log="no summary here\n")
        world.fail(20, log=world.log(summary=(3, 1, 1)))
        with self.assertRaises(forge_api.ForgeError) as raised:
            world.check()
        self.assertEqual(raised.exception.code, "payload_invalid")

    def test_a_baseline_larger_than_a_page_is_read_across_pages(self):
        world = SuiteWorld(before=101, after=101, after_base=1000)
        code, report = world.check(n=101)
        self.assertEqual((code, report["regressions"]), (0, {}))
        self.assertEqual(report["before"], list(range(101, 0, -1)))
        self.assertEqual(len(report["after"]), 101)

    def test_a_baseline_that_skips_past_the_first_page_still_reaches_n(self):
        world = SuiteWorld(before=120, after_base=1000)
        for run_id in range(21, 121):
            world.fail(run_id, log="no summary here\n")
        code, report = world.check()
        self.assertEqual(code, 0)
        self.assertEqual(report["before"], list(range(20, 0, -1)))
        self.assertEqual(report["before_skipped"], list(range(120, 20, -1)))

    def test_a_truncated_before_listing_is_a_forge_error(self):
        world = SuiteWorld()
        pages = world.pages()
        key = f"{world.LISTING}&created=<{world.STAMP}&per_page=100"
        pages[key][0]["total_count"] += 1
        get, patched = forge(world.gets(), pages)
        with get, patched, self.assertRaises(forge_api.ForgeError) as raised:
            verify_checks.suite_regressions(
                world.REPO, world.WORKFLOW, world.JOB, world.BRANCH, world.MERGE, 20)
        self.assertEqual(raised.exception.code, "payload_invalid")

    def test_a_member_that_failed_in_a_before_attempt_is_not_a_regression(self):
        world = SuiteWorld()
        world.attempts[3] = 2
        world.fail(3, attempt=1)
        world.set_job(3, attempt=2)
        world.fail(105)
        self.assertEqual(world.check()[0], 0)


class SuiteRegressionsCommandTest(unittest.TestCase):
    ARGS = ["--repo", "fagenorn/nix-config", "--workflow", "ci.yaml", "--job", "Agent Workflow Tests",
            "--branch", "main", "--merge", "c" * 40, "--n", "20"]

    def test_wrapper_maps_a_forge_error_to_exit_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.symlink(sys.executable, Path(tmp) / "python3")
            done = run_from_root(["/bin/sh", str(ROOT / CHECKS / "suite-regressions"), *self.ARGS],
                                 {"PATH": tmp})
        self.assertEqual((done.returncode, done.stdout), (2, ""), done.stderr)
        self.assertIn("forge_error", done.stderr)

    def test_a_short_merge_sha_is_a_usage_error(self):
        args = [*self.ARGS[:-4], "--merge", "abc", "--n", "20"]
        with mock.patch.object(verify_checks, "suite_regressions",
                               side_effect=AssertionError("reached the forge")):
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    verify_checks.main(["suite-regressions", *args])
        self.assertEqual(raised.exception.code, 2)

    def test_wrapper_is_committed_executable(self):
        self.assertEqual(committed_mode(f"{CHECKS}/suite-regressions"), "100755")


def _fake_program(tmp, name, body):
    path = Path(tmp) / name
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(0o755)
    return str(path)


class SuiteWallTimeTest(unittest.TestCase):
    def test_the_verdict_table(self):
        rows = [
            ((0, 412.0, 600), (0, "met", 0)),
            ((0, 600.0, 600), (1, "slow", 0)),
            ((0, 599.9, 600), (0, "met", 0)),
            ((3, 100.0, 600), (1, "failed", 3)),
            ((None, 600.0, 600), (1, "deadline", None)),
        ]
        for given, expected in rows:
            with self.subTest(given=given):
                code, report = verify_checks.suite_wall_verdict(*given)
                self.assertEqual((code, report["verdict"], report["suite_exit"]), expected)
                self.assertEqual(set(report), {"check", "verdict", "wall_seconds", "limit",
                                               "suite_exit", "summary"})
                self.assertEqual(report["check"], "suite-wall-time")

    def test_a_suite_passing_below_the_limit_is_met(self):
        line = "suite-runner: summary members=1 passed=1 failed=0 jobs=1 wall=2.0s cpu=0.1s"
        with tempfile.TemporaryDirectory() as tmp:
            fake = _fake_program(tmp, "suite", f"sleep \"$1\"\necho '{line}'\nexit 0\n")
            code, report = verify_checks.suite_wall_time(4.0, root=Path(tmp), argv=[fake, "2"])
        self.assertEqual((code, report["verdict"], report["suite_exit"]), (0, "met", 0))
        self.assertEqual(report["summary"], line)
        self.assertTrue(2.0 <= report["wall_seconds"] < 4.0, report)

    def test_a_suite_reaching_the_limit_is_killed_and_not_met(self):
        with tempfile.TemporaryDirectory() as tmp:
            pidfile = str(Path(tmp) / "pid")
            fake = _fake_program(tmp, "suite", "sleep 30 &\necho $! > \"$1\"\nwait\n")
            started = time.monotonic()
            code, report = verify_checks.suite_wall_time(2.0, root=Path(tmp), argv=[fake, pidfile])
            elapsed = time.monotonic() - started
            pid = Path(pidfile).read_text().strip()
            self.assertEqual((code, report["verdict"], report["suite_exit"]), (1, "deadline", None))
            self.assertGreaterEqual(report["wall_seconds"], 2.0)
            self.assertLess(elapsed, 10)
            deadline = time.monotonic() + 5
            while True:
                stat = subprocess.run(["ps", "-o", "stat=", "-p", pid],
                                      capture_output=True, text=True).stdout.strip()
                if stat == "" or stat.startswith("Z"):
                    break
                if time.monotonic() > deadline:
                    self.fail("the suite's grandchild survived the kill")

    def test_a_slow_pass_reports_the_wall_time_it_was_judged_on(self):
        code, report = verify_checks.suite_wall_verdict(0, 599.96, 600)
        self.assertEqual((code, report["verdict"]), (0, "met"))
        self.assertLess(report["wall_seconds"], report["limit"])
        code, report = verify_checks.suite_wall_verdict(0, 600.04, 600)
        self.assertEqual((code, report["verdict"]), (1, "slow"))
        self.assertGreaterEqual(report["wall_seconds"], report["limit"])

    def test_an_orphaned_daemon_in_its_own_session_is_killed_at_the_deadline(self):
        # The fixture's shape: the client that starts the daemon exits at once, so the daemon is
        # re-parented to init (ppid 1) and sits in its own session, out of reach of both the
        # process group and a walk down from the suite.
        launcher = (
            "import subprocess, sys\n"
            "daemon = subprocess.Popen([sys.executable, '-c', 'import signal; signal.pause()'],\n"
            "                          start_new_session=True)\n"
            "open(sys.argv[1], 'w').write(str(daemon.pid))\n")
        suite = (
            "import subprocess, sys, time\n"
            f"subprocess.run([sys.executable, '-c', {launcher!r}, sys.argv[1]], check=True)\n"
            "time.sleep(60)\n")
        with tempfile.TemporaryDirectory() as tmp:
            pidfile = Path(tmp) / "pid"
            script = Path(tmp) / "suite.py"
            script.write_text(suite)
            code, report = verify_checks.suite_wall_time(
                2.0, root=Path(tmp), argv=[sys.executable, str(script), str(pidfile)])
            pid = pidfile.read_text().strip()
            try:
                self.assertEqual((code, report["verdict"]), (1, "deadline"))
                deadline = time.monotonic() + 5
                while True:
                    stat = subprocess.run(["ps", "-o", "stat=", "-p", pid],
                                          capture_output=True, text=True).stdout.strip()
                    if stat == "" or stat.startswith("Z"):
                        break
                    if time.monotonic() > deadline:
                        self.fail("the daemon started in its own session survived the deadline")
            finally:
                with contextlib.suppress(ProcessLookupError):
                    os.kill(int(pid), 9)

    def test_the_summary_is_found_in_a_huge_log_without_holding_it(self):
        line = "suite-runner: summary members=2 passed=1 failed=1 jobs=1 wall=1.0s cpu=0.1s"
        body = (f"head -c 33554432 /dev/zero | tr '\\0' x\necho\necho 'suite-runner: summary old'\n"
                f"echo '{line}'\necho tail\n")
        with tempfile.TemporaryDirectory() as tmp:
            fake = _fake_program(tmp, "suite", body)
            tracemalloc.start()
            try:
                _, report = verify_checks.suite_wall_time(60.0, root=Path(tmp), argv=[fake])
                peak = tracemalloc.get_traced_memory()[1]
            finally:
                tracemalloc.stop()
        self.assertEqual(report["summary"], line)
        self.assertLess(peak, 4 * 1024 * 1024)

    def test_the_last_summary_scan_across_chunk_boundaries(self):
        prefix = b"suite-runner: summary"
        cases = [
            (b"a\n" + prefix + b" one\nnoise\n" + prefix + b" two\nzzz", prefix.decode() + " two"),
            (b"x" * 50 + b"\n" + prefix + b" only", prefix.decode() + " only"),
            (b"no summary here\n" * 5, None),
            (prefix + b" a\n" + b"y" * 10000 + b"\n", prefix.decode() + " a"),
            (b"", None),
        ]
        for data, expected in cases:
            for chunk in (1, 3, 7, 64):
                with self.subTest(data=data[:30], chunk=chunk):
                    self.assertEqual(verify_checks._last_summary(io.BytesIO(data), chunk), expected)

    def test_a_failing_suite_is_not_met(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = _fake_program(tmp, "suite", "exit 3\n")
            code, report = verify_checks.suite_wall_time(60.0, root=Path(tmp), argv=[fake])
        self.assertEqual((code, report["verdict"], report["suite_exit"]), (1, "failed", 3))

    def test_the_suite_runs_without_forge_tokens(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "env"
            fake = _fake_program(tmp, "suite", "env > \"$1\"\n")
            with mock.patch.dict(os.environ, {"GITHUB_TOKEN": "t1", "GH_TOKEN": "t2"}):
                code, _ = verify_checks.suite_wall_time(60.0, root=Path(tmp), argv=[fake, str(out)])
            lines = out.read_text().splitlines()
        self.assertEqual(code, 0)
        self.assertFalse([line for line in lines
                          if line.startswith(("GITHUB_TOKEN=", "GH_TOKEN="))])


class SuiteWallTimeCommandTest(unittest.TestCase):
    FAKE_JUST = (
        "printf '%s\\n' \"$@\" > \"$FAKE_JUST_LOG\"\n"
        "pwd -P >> \"$FAKE_JUST_LOG\"\n"
        "i=0; while [ $i -lt 500 ]; do echo noise; i=$((i+1)); done\n"
        "echo 'suite-runner: summary members=1 passed=1 failed=0 jobs=1 wall=0.1s cpu=0.1s'\n")

    def test_a_bad_limit_is_a_usage_error(self):
        cap = str(verify_exec.TIMEOUT - verify_checks.SUITE_REPORT_MARGIN + 1)
        for value in (["0"], ["-5"], ["ten"], [cap], []):
            with self.subTest(value=value):
                argv = ["suite-wall-time", *(["--limit", *value] if value else [])]
                with mock.patch.object(verify_checks, "suite_wall_time",
                                       side_effect=AssertionError("ran the suite")):
                    with contextlib.redirect_stderr(io.StringIO()):
                        with self.assertRaises(SystemExit) as raised:
                            verify_checks.main(argv)
                self.assertEqual(raised.exception.code, 2)

    def test_the_full_window_fits_the_runner_timeout(self):
        met = verify_checks.suite_wall_verdict(0, 1.0, 600.0)
        with mock.patch.object(verify_checks, "suite_wall_time", return_value=met) as ran:
            with contextlib.redirect_stdout(io.StringIO()):
                code = verify_checks.main(["suite-wall-time", "--limit", "600"])
        self.assertEqual(code, 0)
        ran.assert_called_once()
        self.assertEqual(ran.call_args.args[0], 600.0)
        self.assertLessEqual(600 + verify_checks.SUITE_REPORT_MARGIN, verify_exec.TIMEOUT)

    def test_the_wrapper_runs_the_suite_recipe_at_the_repo_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "bin").mkdir()
            _fake_program(Path(tmp) / "bin", "just", self.FAKE_JUST)
            log = str(Path(tmp) / "log")
            result = run_from_root(
                [str(ROOT / CHECKS / "suite-wall-time"), "--limit", "600"],
                {"PATH": f"{tmp}/bin:{os.environ['PATH']}", "FAKE_JUST_LOG": log})
            logged = Path(log).read_text().splitlines()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(logged, ["agent-workflow-tests", str(ROOT)])
        self.assertEqual(result.stdout.count("\n"), 1)
        report = json.loads(result.stdout)
        self.assertEqual(report["verdict"], "met")
        self.assertEqual(report["summary"],
                         "suite-runner: summary members=1 passed=1 failed=0 jobs=1 wall=0.1s cpu=0.1s")
        self.assertNotIn("noise", result.stdout)

    def test_the_wrapper_refuses_a_zero_limit_without_running_the_suite(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "bin").mkdir()
            _fake_program(Path(tmp) / "bin", "just", self.FAKE_JUST)
            log = Path(tmp) / "log"
            result = run_from_root(
                [str(ROOT / CHECKS / "suite-wall-time"), "--limit", "0"],
                {"PATH": f"{tmp}/bin:{os.environ['PATH']}", "FAKE_JUST_LOG": str(log)})
            ran = log.exists()
        self.assertEqual((result.returncode, result.stdout), (2, ""), result.stderr)
        self.assertFalse(ran)

    def test_wrapper_is_committed_executable(self):
        self.assertEqual(committed_mode(f"{CHECKS}/suite-wall-time"), "100755")


class IssueClosedTest(unittest.TestCase):
    PATH = "repos/o/r/issues/1009"
    COMMENTS = PATH + "/comments?per_page=100"
    BLOCK = {"v": 1, "merge": "a" * 40, "checks": [{"ac": "AC1", "kind": "evidence", "host": "mbp"}]}
    KEY = verify_issues.block_key(10, BLOCK)

    @staticmethod
    def comment(cid, body, association="OWNER"):
        return {"id": cid, "author_association": association, "body": body,
                "created_at": "2026-11-06T10:00:00Z"}

    def held(self):
        return self.comment(10, "Held.\n\n```verify\n" + json.dumps(self.BLOCK) + "\n```\n")

    def closed(self, cid=11, outcome="verified", association="OWNER", key=None):
        body = forge_markers.render(verify_issues.CLOSED, {"block": key or self.KEY, "outcome": outcome},
                                    "Recorded.")
        return self.comment(cid, body, association)

    def read(self, payload, comments=()):
        def api_get(path, allow=()):
            self.assertEqual(path, self.PATH)
            return payload

        def api_pages(path):
            self.assertEqual(path, self.COMMENTS)
            return [list(comments)]
        stack = contextlib.ExitStack()
        stack.enter_context(mock.patch.object(forge_api, "api_get", side_effect=api_get))
        stack.enter_context(mock.patch.object(forge_api, "api_pages", side_effect=api_pages))
        return stack

    def completed(self, *comments):
        with self.read({"state": "closed", "state_reason": "completed"}, comments):
            return verify_checks.issue_closed("o/r", 1009)

    def test_an_issue_closed_as_completed_after_its_block_was_verified_is_met(self):
        self.assertEqual(self.completed(self.held(), self.closed()),
                         (0, {"issue": 1009, "state": "closed", "state_reason": "completed",
                              "verified": True}))

    def test_an_issue_closed_as_completed_by_hand_is_not_met(self):
        for comments in ((), (self.held(),), (self.held(), self.closed(outcome="expired")),
                         (self.held(), self.closed(association="NONE")),
                         (self.held(), self.closed(key="10.0123456789abcdef")),
                         (self.closed(),)):
            with self.subTest(comments=comments):
                code, report = self.completed(*comments)
                self.assertEqual((code, report["verified"]), (1, False))

    def test_a_verified_marker_of_an_older_block_does_not_count_for_a_replacement(self):
        newer = self.comment(12, "Held.\n\n```verify\n" + json.dumps({**self.BLOCK, "merge": "b" * 40})
                             + "\n```\n")
        self.assertEqual(self.completed(self.held(), self.closed(), newer)[0], 1)

    def test_an_open_issue_is_not_yet(self):
        with self.read({"state": "open", "state_reason": None}):
            self.assertEqual(verify_checks.issue_closed("o/r", 1009),
                             (75, {"issue": 1009, "state": "open", "state_reason": None}))

    def test_an_issue_closed_another_way_is_not_met_without_reading_its_comments(self):
        with self.read({"state": "closed", "state_reason": "not_planned"}, ()) as _, \
                mock.patch.object(forge_api, "api_pages", side_effect=AssertionError("read")):
            code, report = verify_checks.issue_closed("o/r", 1009)
        self.assertEqual((code, report["state_reason"]), (1, "not_planned"))

    def test_an_unreadable_issue_is_a_forge_error(self):
        for payload in ([], {"state": "gone"}):
            with self.subTest(payload=payload), self.read(payload):
                with self.assertRaises(forge_api.ForgeError) as raised:
                    verify_checks.issue_closed("o/r", 1009)
                self.assertEqual(raised.exception.code, "payload_invalid")
        with self.read({"state": "closed", "state_reason": "completed"}, [{"id": "x"}]):
            with self.assertRaises(forge_api.ForgeError) as raised:
                verify_checks.issue_closed("o/r", 1009)
            self.assertEqual(raised.exception.code, "payload_invalid")
        err = io.StringIO()
        with mock.patch.object(forge_api, "api_get",
                               side_effect=forge_api.ForgeError("transport", "x")):
            with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
                code = verify_checks.main(["issue-closed", "--repo", "o/r", "--issue", "1009"])
        self.assertEqual(code, 2)
        self.assertIn("verify-checks: forge_error: transport", err.getvalue())

    def test_the_issue_closed_wrapper_is_committed_executable(self):
        self.assertEqual(committed_mode(f"{CHECKS}/issue-closed"), "100755")
        self.assertEqual(run_from_root([str(ROOT / CHECKS / "issue-closed")]).returncode, 2)


class HostMentionsTest(unittest.TestCase):
    PATH = "repos/o/r/issues?state=open&per_page=100"

    def read(self, pages, phrases=("anis-desktop", "Linux host"), gone="anis-desktop is gone", exempt=()):
        def api_pages(path):
            self.assertEqual(path, self.PATH)
            return pages
        with mock.patch.object(forge_api, "api_pages", side_effect=api_pages):
            return verify_checks.host_mentions("o/r", list(phrases), gone, list(exempt))

    def test_an_issue_that_names_the_host_without_the_gone_line_is_an_offender(self):
        pages = [[{"number": 6, "title": "On the Linux host", "body": "anis-desktop is gone: moved to eleven-m5"},
                  {"number": 7, "title": "y", "body": "nothing"}],
                 [{"number": 5, "title": "x", "body": "run it on anis-desktop"},
                  {"number": 8, "title": "pr", "body": "anis-desktop", "pull_request": {}}]]
        self.assertEqual(self.read(pages), (1, {"mentioning": [5, 6], "offenders": [5]}))

    def test_matching_ignores_case_and_honours_the_exemption(self):
        pages = [[{"number": 9, "title": "t", "body": "the LINUX HOST"},
                  {"number": 1291, "title": "t", "body": "anis-desktop"},
                  {"number": 10, "title": "t", "body": "Anis-Desktop Is Gone. anis-desktop"},
                  {"number": 11, "title": "anis-desktop", "body": None}]]
        self.assertEqual(self.read(pages, exempt=[1291]),
                         (1, {"mentioning": [9, 10, 11, 1291], "offenders": [9, 11]}))
        self.assertEqual(self.read([[]]), (0, {"mentioning": [], "offenders": []}))

    def test_an_open_criterion_that_still_names_the_host_is_not_answered_by_a_gone_paragraph(self):
        gone = "anis-desktop is gone: nothing runs there now."
        pages = [[{"number": 5, "title": "t", "body": f"- [ ] [evidence] run it on anis-desktop\n\n{gone}"},
                  {"number": 6, "title": "t", "body": f"- [ ] [evidence] run it on eleven-m5\n- [x] was on the Linux host\n\n{gone}"},
                  {"number": 7, "title": "t", "body": f"Run on the Linux host.\n\n{gone}"},
                  {"number": 8, "title": "t", "body": f"1. [ ] run on the LINUX HOST\n\n{gone}"},
                  {"number": 9, "title": "t", "body": f"- [ ] {gone}"}]]
        self.assertEqual(self.read(pages), (1, {"mentioning": [5, 6, 7, 8, 9], "offenders": [5, 8]}))

    def test_a_malformed_listing_is_a_forge_error(self):
        for pages in (["x"], [["x"]], [[{"number": "5", "body": ""}]], [[{"number": True, "body": ""}]]):
            with self.subTest(pages=pages):
                with self.assertRaises(forge_api.ForgeError) as raised:
                    self.read(pages)
                self.assertEqual(raised.exception.code, "payload_invalid")
        err = io.StringIO()
        with mock.patch.object(forge_api, "api_pages",
                               side_effect=forge_api.ForgeError("transport", "x")):
            with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
                code = verify_checks.main(["host-mentions", "--repo", "o/r", "--phrase", "a", "--gone", "b"])
        self.assertEqual(code, 2)
        self.assertIn("verify-checks: forge_error: transport", err.getvalue())


class HostPromptsTest(unittest.TestCase):
    HOST = "anis-desktop"
    STALE = {"reason": "verify-stale-check", "block": "1.0000000000000000", "check": "0",
             "host": "anis-desktop", "cause": "silent", "last": "never"}

    @staticmethod
    def comment(cid, body, association="OWNER"):
        return {"id": cid, "author_association": association, "body": body,
                "updated_at": "2026-11-06T10:00:00Z"}

    def prompt(self, cid, fields, association="OWNER"):
        return self.comment(cid, forge_markers.render("owner-action", fields, "Asking."), association)

    def end(self, cid, of, association="OWNER"):
        return self.comment(cid, forge_markers.end_body(of, "decision"), association)

    def run_check(self, listings, comments, repos=("o/r",)):
        """`listings` maps a repo to its pages; `comments` maps (repo, issue) to REST comments."""
        self.reads = []

        def api_pages(path):
            for repo, pages in listings.items():
                if path == f"repos/{repo}/issues?state=open&per_page=100":
                    return pages
            raise AssertionError(path)

        def list_comments(slug, issue):
            self.reads.append((slug, issue))
            return comments.get((slug, issue), [])
        with mock.patch.object(forge_api, "api_pages", side_effect=api_pages), \
                mock.patch.object(forge_markers, "list_comments", side_effect=list_comments):
            return verify_checks.host_prompts(list(repos), self.HOST)

    def test_a_live_prompt_naming_the_host_is_reported_whatever_the_labels(self):
        listings = {"o/r": [[{"number": 3, "title": "t", "body": "", "labels": []},
                             {"number": 4, "title": "t", "body": "", "labels": []}]]}
        comments = {("o/r", 3): [self.prompt(30, self.STALE)],
                    ("o/r", 4): [self.prompt(40, {**self.STALE, "host": "eleven-m5"})]}
        self.assertEqual(self.run_check(listings, comments),
                         (1, {"host": self.HOST, "live": [
                             {"repo": "o/r", "issue": 3, "comment": 30, "reason": "verify-stale-check"}]}))

    def test_trust_and_liveness_follow_the_marker_type(self):
        listings = {"o/r": [[{"number": 5}, {"number": 4}, {"number": 3}]]}
        approve = {**self.STALE, "reason": "verify-approve", "host": "mbp+anis-desktop"}
        forge = {"issue": "5", "reason": "decision", "holder": "h", "host": self.HOST}
        comments = {
            ("o/r", 3): [self.prompt(30, self.STALE), self.end(31, 30)],
            ("o/r", 4): [self.prompt(41, approve), self.end(42, 41, "COLLABORATOR"),
                         self.prompt(43, self.STALE, "COLLABORATOR")],
            ("o/r", 5): [self.prompt(50, forge, "COLLABORATOR"), self.prompt(51, forge, "NONE")]}
        code, report = self.run_check(listings, comments)
        self.assertEqual(code, 1)
        self.assertEqual(report["live"], [
            {"repo": "o/r", "issue": 4, "comment": 41, "reason": "verify-approve"},
            {"repo": "o/r", "issue": 5, "comment": 50, "reason": "decision"}])

    def test_every_open_issue_is_read_once_and_none_is_met(self):
        listings = {"o/r": [[{"number": 3}, {"number": 4}], [{"number": 5}]],
                    "o/s": [[]]}
        self.assertEqual(self.run_check(listings, {}, repos=("o/r", "o/s")),
                         (0, {"host": self.HOST, "live": []}))
        self.assertEqual(sorted(self.reads), [("o/r", 3), ("o/r", 4), ("o/r", 5)])

    def test_a_live_prompt_on_an_open_pull_request_is_reported(self):
        listings = {"o/r": [[{"number": 3, "title": "t", "body": "", "pull_request": {}},
                             {"number": 4, "title": "t", "body": ""}]]}
        comments = {("o/r", 3): [self.prompt(30, self.STALE)]}
        self.assertEqual(self.run_check(listings, comments),
                         (1, {"host": self.HOST, "live": [
                             {"repo": "o/r", "issue": 3, "comment": 30, "reason": "verify-stale-check"}]}))
        self.assertEqual(sorted(self.reads), [("o/r", 3), ("o/r", 4)])


class HostCheckWrappersTest(unittest.TestCase):
    def test_the_wrappers_are_committed_executable(self):
        for name in ("host-mentions", "host-prompts"):
            with self.subTest(name=name):
                self.assertEqual(committed_mode(f"{CHECKS}/{name}"), "100755")
                self.assertEqual(run_from_root([str(ROOT / CHECKS / name)]).returncode, 2)


class PlatformStatusWrapperTest(unittest.TestCase):
    def test_runs_the_installed_platform_status_and_passes_it_through(self):
        with tempfile.TemporaryDirectory() as home:
            bin_dir = Path(home) / ".agents" / "bin"
            bin_dir.mkdir(parents=True)
            fake = bin_dir / "resolve-project"
            fake.write_text('#!/bin/sh\nprintf \'{"argv": "%s", "platform": {"deprecations": [1]}}\\n\' "$*"\n'
                            "exit 3\n")
            fake.chmod(0o755)
            done = run_from_root([str(ROOT / CHECKS / "platform-status")], {"HOME": home})
        self.assertEqual(done.returncode, 3, done.stderr)
        self.assertEqual(json.loads(done.stdout)["argv"], "platform-status")

    def test_wrapper_is_committed_executable(self):
        self.assertEqual(committed_mode(f"{CHECKS}/platform-status"), "100755")


class ManagedPrePushHookTest(unittest.TestCase):
    SLUG = "fagenorn/pre-push-hook-fixture"

    def setUp(self):
        self.world = PrePushWorld(self)
        managed = self.world.tmp / "abc-agent-git-hooks"
        self.world.hooks.rename(managed)
        self.world.hooks = managed
        self.set_user_config(managed)

    def set_user_config(self, hooks, extra=""):
        Path(self.world.env["GIT_CONFIG_GLOBAL"]).write_text(
            ("" if hooks is None else f"[core]\n\thooksPath = {hooks}\n") + extra,
            encoding="utf-8")

    def check(self):
        return run_from_root(["python3", "-m", "agent_tools.verification.verify_checks",
                              "managed-pre-push-hook", "--slug", self.SLUG],
                             env_extra=self.world.env)

    def test_the_managed_hook_refusing_a_default_branch_push_is_met(self):
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout),
                         {"hooks_path": str(self.world.hooks), "managed": True,
                          "refused": True, "remote_unchanged": True,
                          "control_admitted": True, "met": True})

    def test_a_url_rewrite_in_the_user_config_does_not_move_the_fixture_pushes(self):
        self.set_user_config(self.world.hooks,
                             '[url "https://example.invalid/"]\n'
                             "\tinsteadOf = git@github.com:\n"
                             "\tpushInsteadOf = git@github.com:\n")
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["met"])

    def test_an_unset_hooks_path_is_not_met(self):
        self.set_user_config(None)
        result = self.check()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(json.loads(result.stdout)["hooks_path"], None)

    def test_an_unmanaged_hooks_directory_is_not_met(self):
        plain = self.world.tmp / "plain-hooks"
        self.world.hooks.rename(plain)
        self.set_user_config(plain)
        result = self.check()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertFalse(json.loads(result.stdout)["managed"])

    def test_a_managed_hook_that_admits_everything_is_not_met(self):
        (self.world.hooks / "pre-push").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        result = self.check()
        self.assertEqual(result.returncode, 1, result.stderr)
        report = json.loads(result.stdout)
        self.assertFalse(report["refused"])
        self.assertFalse(report["remote_unchanged"])

    def test_a_managed_hook_that_refuses_a_feature_push_too_is_not_met(self):
        (self.world.hooks / "pre-push").write_text(
            "#!/bin/sh\necho lifecycle guard pre-push: unsafe push: refusing to push the "
            "default branch main >&2\nexit 1\n", encoding="utf-8")
        result = self.check()
        self.assertEqual(result.returncode, 1, result.stderr)
        report = json.loads(result.stdout)
        self.assertTrue(report["refused"])
        self.assertFalse(report["control_admitted"])

    def test_the_check_script_is_committed_executable(self):
        self.assertEqual(committed_mode("home/common/verify-pending/checks/managed-pre-push-hook"),
                         "100755")


FAKE_RESOLVE = """#!/bin/sh
# fake resolve-project: answers from $FAKE_RESOLVE_DIR/<subcommand>.json and .exit
dir="$FAKE_RESOLVE_DIR"
cat "$dir/$1.json"
exit "$(cat "$dir/$1.exit" 2>/dev/null || echo 0)"
"""


class DeprecationsRetiredTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        self.root, self.answers, bin_dir = base / "root", base / "answers", base / "bin"
        for path in (self.root, self.answers, bin_dir):
            path.mkdir()
        fake = bin_dir / "resolve-project"
        fake.write_text(FAKE_RESOLVE)
        fake.chmod(0o755)
        self.env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}",
                    "FAKE_RESOLVE_DIR": str(self.answers)}
        git = ["git", "-C", str(self.root)]
        subprocess.run([*git, "init", "-q"], check=True)
        (self.root / "README.md").write_text("nodo\n")
        subprocess.run([*git, "add", "README.md"], check=True)
        subprocess.run([*git, "-c", "user.name=t", "-c", "user.email=t@t", "-c",
                        "commit.gpgsign=false", "commit", "-qm", "init"], check=True)
        self.answer(deprecated=[], adapter="none")

    def answer(self, *, deprecated, adapter, targets=(), state="unsupported", resolve_exit=0,
               project_id="elevenyellow/nodocom", schema_version=None):
        (self.answers / "platform-status.json").write_text(
            json.dumps({"project": {"deprecated_uses": deprecated}}))
        versioned = {} if schema_version is None else {"schema_version": schema_version}
        (self.answers / "resolve.json").write_text(json.dumps({
            **versioned,
            "project": {"id": project_id, "root": str(self.root)},
            "bindings": {} if adapter is None else {"deploy": {"adapter": adapter}},
            "capabilities": {"release": {"state": state, "reason_code": None, "repair_id": None}},
            "release": {"targets": [{"adapter": a} for a in targets]}}))
        (self.answers / "resolve.exit").write_text(str(resolve_exit))

    def check(self, **kwargs):
        options = {"watch_adapter": None, "red_pending": False, **kwargs}
        return verify_checks.deprecations_retired_check([self.root], self.env, **options)

    def commit(self, path, text):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
        subprocess.run(["git", "-C", str(self.root), "add", path], check=True)

    def test_a_clean_root_is_green(self):
        code, report = self.check()
        self.assertEqual((code, report["met"], report["roots"][0]["verdict"]), (0, True, "green"))

    def test_each_reading_turns_the_root_red(self):
        cases = (
            lambda: self.answer(deprecated=["legacy-skills-config"], adapter="none"),
            lambda: self.commit(".claude/skills.config.json", "{}"),
            lambda: self.answer(deprecated=[], adapter="railway"),
            lambda: self.answer(deprecated=[], adapter="none", resolve_exit=2),
            lambda: self.commit("docs/deploy.md", "run release deploy inspect --commit x\n"),
        )
        for index, make_red in enumerate(cases):
            with self.subTest(case=index):
                self.setUp()
                make_red()
                code, report = self.check()
                self.assertEqual((code, report["roots"][0]["verdict"]), (1, "red"))
                self.assertEqual(self.check(red_pending=True)[0], 75)

    def test_a_schema_2_snapshot_without_a_deploy_binding_reads_c_green(self):
        self.answer(deprecated=[], adapter=None, schema_version=2)
        code, report = self.check()
        self.assertEqual((code, report["roots"][0]["readings"]["c"]["status"]), (0, "green"))
        self.answer(deprecated=[], adapter=None, schema_version=2, resolve_exit=2)
        self.assertEqual(self.check()[0], 1)

    def test_a_schema_1_snapshot_without_a_deploy_binding_reads_c_red(self):
        for version in (1, None, True, "2"):
            with self.subTest(schema_version=version):
                self.answer(deprecated=[], adapter=None, schema_version=version)
                code, report = self.check()
                self.assertEqual((code, report["roots"][0]["readings"]["c"]["status"]), (1, "red"))

    def test_a_schema_1_snapshot_with_the_none_adapter_reads_c_green(self):
        self.answer(deprecated=[], adapter="none", schema_version=1)
        self.assertEqual(self.check()[1]["roots"][0]["readings"]["c"]["status"], "green")

    def test_a_real_deploy_adapter_keeps_c_red_and_none_keeps_it_green(self):
        self.answer(deprecated=[], adapter="railway")
        code, report = self.check()
        self.assertEqual((code, report["roots"][0]["readings"]["c"]["status"]), (1, "red"))
        self.answer(deprecated=[], adapter="none")
        self.assertEqual(self.check()[1]["roots"][0]["readings"]["c"]["status"], "green")

    def test_a_hit_under_the_artifact_directory_is_not_a_user(self):
        self.commit(".agents/artifacts/evidence/old.md", "release deploy inspect\n")
        self.assertEqual(self.check()[0], 0)

    def test_the_nix_config_root_is_scoped_to_its_skills(self):
        self.answer(deprecated=[], adapter="none", project_id="fagenorn/nix-config")
        self.commit("python/agent_tools/verification/verify_checks.py", 'RETIRED_COMMAND = "release deploy inspect"\n')
        self.commit("tests/test_verify_checks.py", "release deploy inspect\n")
        code, report = self.check()
        self.assertEqual((code, report["roots"][0]["verdict"]), (0, "green"))
        self.assertEqual(report["roots"][0]["readings"]["d"]["scope"],
                         ["home/common/agent-skills/skills"])
        self.commit("home/common/agent-skills/skills/ship-release/SKILL.md",
                    "run release deploy inspect\n")
        self.assertEqual(self.check()[0], 1)

    def test_another_root_greps_the_whole_tree(self):
        self.commit("python/tool.py", "release deploy inspect\n")
        code, report = self.check()
        self.assertEqual((code, report["roots"][0]["readings"]["d"]["scope"]),
                         (1, [".", ":!.agents/artifacts"]))

    def test_the_watch_adapter_is_pending_until_adopted_and_available(self):
        self.assertEqual(self.check(watch_adapter="railway-deploy")[0], 75)
        self.answer(deprecated=[], adapter="none", targets=("github-forge", "railway-deploy"),
                    state="blocked")
        code, report = self.check(watch_adapter="railway-deploy")
        self.assertEqual((code, report["roots"][0]["verdict"]), (1, "red"))
        self.answer(deprecated=[], adapter="none", targets=("github-forge", "railway-deploy"),
                    state="available")
        self.assertEqual(self.check(watch_adapter="railway-deploy")[0], 0)

    def test_an_unreadable_platform_status_is_a_tool_error(self):
        (self.answers / "platform-status.json").write_text("not json")
        with self.assertRaises(verify_checks.ToolError):
            self.check()


class DeprecationsRetiredWrapperTest(unittest.TestCase):
    def test_wrapper_is_committed_executable(self):
        self.assertEqual(committed_mode(f"{CHECKS}/deprecations-retired"), "100755")

    def test_the_command_line_exits_two_on_a_tool_error(self):
        with tempfile.TemporaryDirectory() as home:
            done = run_from_root([str(ROOT / CHECKS / "deprecations-retired"),
                                  "--repo-root", home], {"HOME": home, "PATH": f"{Path(sys.executable).parent}:/usr/bin:/bin"})
        self.assertEqual(done.returncode, 2, done.stderr)
        self.assertIn("verify-checks: tool_error:", done.stderr)


def fleet(version, rows):
    return {"platform": {"platform_version": version}, "fleet": rows}


def row(pid, compatible=True, removed=None):
    return {"project_id": pid, "root": f"/r/{pid}", "compatible": compatible,
            "removed_uses": removed if removed is not None else []}


def entry(i):
    return {"id": f"d{i}", "kind": "platform_behavior", "subject": f"s{i}",
            "since": "1.2.0", "successor": "x", "migration": "m"}


def manifests(main_ids=(1, 2), removal_ids=(1, 2), main="1.2.0", cand="2.0.0"):
    shape = {"schema_version": 1, "project_schema_versions": [1, 2],
             "resolved_schema_version": 1, "migrations": []}
    return ({**shape, "platform_version": main,
             "deprecations": [entry(i) for i in main_ids], "removals": []},
            {**shape, "platform_version": cand,
             "deprecations": [], "removals": [entry(i) for i in removal_ids]})


GREEN_MANIFEST = {"verdict": "green"}


class ManifestVerdictTest(unittest.TestCase):
    def test_every_removal_declared_is_green(self):
        code, report = verify_checks.manifest_verdict(*manifests())
        self.assertEqual((code, report["verdict"], report["undeclared"]), (0, "green", []))
        self.assertEqual(report, {"verdict": "green", "main_version": "1.2.0",
                                  "candidate_version": "2.0.0", "removal_ids": ["d1", "d2"],
                                  "undeclared": []})

    def test_one_missing_deprecation_is_not_green(self):
        code, report = verify_checks.manifest_verdict(*manifests(main_ids=(1,)))
        self.assertEqual((code, report["verdict"], report["undeclared"]), (75, "red", ["d2"]))

    def test_a_changed_entry_is_not_declared(self):
        main, cand = manifests()
        cand["removals"][0]["successor"] = "other"
        self.assertEqual(verify_checks.manifest_verdict(main, cand)[1]["undeclared"], ["d1"])

    def test_every_one_of_the_six_members_must_be_equal(self):
        valid_change = {"id": "changed", "kind": "project_file", "subject": "changed",
                        "since": "1.9.0", "successor": "changed", "migration": "changed"}
        for member, changed in valid_change.items():
            with self.subTest(member=member):
                main, cand = manifests(main_ids=(1,), removal_ids=(1,))
                cand["removals"][0][member] = changed
                code, report = verify_checks.manifest_verdict(main, cand)
                self.assertEqual(code, 75)
                self.assertEqual(len(report["undeclared"]), 1)

    def test_majors_and_emptiness(self):
        for args in (dict(main="2.0.0"), dict(cand="1.3.0"), dict(removal_ids=())):
            with self.subTest(**args):
                self.assertEqual(verify_checks.manifest_verdict(*manifests(**args))[0], 75)

    def test_an_unreadable_manifest_is_usage(self):
        for main, cand in (([], manifests()[1]), (manifests()[0], "x"), (None, None)):
            with self.subTest(main=main):
                code, report = verify_checks.manifest_verdict(main, cand)
                self.assertEqual((code, report["verdict"]), (2, "unreadable"))

    def test_a_manifest_lacking_a_member_is_usage(self):
        for member in ("platform_version", "deprecations", "removals"):
            for side in (0, 1):
                with self.subTest(member=member, side=side):
                    pair = list(manifests())
                    del pair[side][member]
                    self.assertEqual(verify_checks.manifest_verdict(*pair)[0], 2)


    def test_a_manifest_the_validator_rejects_is_usage_even_when_the_records_match(self):
        for member in ("project_schema_versions", "resolved_schema_version",
                       "schema_version", "migrations"):
            for side in (0, 1):
                with self.subTest(member=member, side=side):
                    pair = list(manifests())
                    del pair[side][member]
                    code, report = verify_checks.manifest_verdict(*pair)
                    self.assertEqual((code, report["verdict"]), (2, "unreadable"))
        pair = list(manifests())
        pair[1]["removals"][0]["kind"] = "not-a-kind"
        self.assertEqual(verify_checks.manifest_verdict(*pair)[0], 2)


class PreflightVerdictTest(unittest.TestCase):
    def test_green_needs_every_row_compatible_on_both_sides(self):
        code, report = verify_checks.preflight_verdict(
            fleet("1.2.0", [row("b"), row("a")]), fleet("2.0.0", [row("a"), row("b")]), SHA,
            GREEN_MANIFEST)
        self.assertEqual((code, report["verdict"]), (0, "green"))
        self.assertEqual({key: report[key] for key in
                          ("candidate", "bridge_version", "candidate_version", "manifest")},
                         {"candidate": SHA, "bridge_version": "1.2.0",
                          "candidate_version": "2.0.0", "manifest": GREEN_MANIFEST})
        self.assertEqual(report["rows"], [
            {"project_id": pid, "root": f"/r/{pid}", "bridge_compatible": True,
             "candidate_compatible": True, "removed_uses": [], "reason": None}
            for pid in ("a", "b")])

    def test_each_rule_alone_keeps_it_not_yet(self):
        ok = (fleet("1.2.0", [row("a")]), fleet("2.0.0", [row("a")]))
        cases = {
            "manifest_red": (*ok, {"verdict": "red", "undeclared": ["d2"]}),
            "bridge_too_old": (fleet("1.1.0", [row("a")]), ok[1], GREEN_MANIFEST),
            "bridge_not_major_1": (fleet("2.0.0", [row("a")]), ok[1], GREEN_MANIFEST),
            "candidate_not_major_2": (ok[0], fleet("1.3.0", [row("a")]), GREEN_MANIFEST),
            "empty": (fleet("1.2.0", []), fleet("2.0.0", []), GREEN_MANIFEST),
            "roster_differs": (ok[0], fleet("2.0.0", [row("b")]), GREEN_MANIFEST),
            "bridge_incompatible": (fleet("1.2.0", [row("a", False)]), ok[1], GREEN_MANIFEST),
            "candidate_incompatible": (ok[0], fleet("2.0.0", [row("a", False)]), GREEN_MANIFEST),
            "removed_use": (ok[0], fleet("2.0.0", [row("a", removed=["legacy-skills-config"])]),
                            GREEN_MANIFEST),
            "removed_use_unknown": (ok[0], fleet("2.0.0", [row("a", removed=None) | {
                "removed_uses": None}]), GREEN_MANIFEST),
        }
        for name, (bridge, candidate, manifest) in cases.items():
            with self.subTest(name=name):
                code, report = verify_checks.preflight_verdict(bridge, candidate, SHA, manifest)
                self.assertEqual(code, 75)
                self.assertNotEqual(report["verdict"], "green")

    def test_a_row_reason_is_the_first_rule_it_fails(self):
        code, report = verify_checks.preflight_verdict(
            fleet("1.2.0", [row("a", False), row("b"), row("c"), row("d")]),
            fleet("2.0.0", [row("a", False), row("b", False), row("c", removed=["x"]),
                            row("e")]),
            SHA, GREEN_MANIFEST)
        self.assertEqual(code, 75)
        reasons = {r["project_id"]: r["reason"] for r in report["rows"]}
        self.assertEqual([r["project_id"] for r in report["rows"]], ["a", "b", "c", "d", "e"])
        self.assertEqual(reasons["a"], "bridge_incompatible")
        self.assertEqual(reasons["b"], "candidate_incompatible")
        self.assertEqual(reasons["c"], "removed_use")
        self.assertEqual(reasons["d"], "candidate_missing")
        self.assertEqual(reasons["e"], "bridge_missing")

    def test_a_malformed_report_is_not_green_and_does_not_raise(self):
        for bridge, candidate in (({}, {}), ({"platform": [], "fleet": 1}, fleet("2.0.0", [])),
                                  (fleet("1.2.0", [1]), fleet("2.0.0", [{"project_id": 1}]))):
            with self.subTest(bridge=bridge):
                self.assertEqual(
                    verify_checks.preflight_verdict(bridge, candidate, SHA, GREEN_MANIFEST)[0], 75)

    def test_the_wrapper_is_committed_executable(self):
        self.assertEqual(committed_mode(f"{CHECKS}/cutover-preflight"), "100755")


MANIFEST = "home/common/agent-skills/platform-manifest.json"
CANDIDATE_BRANCH = "cutover-130-candidate"

CANDIDATE_RESOLVER = """import json, os, sys
if os.path.realpath(__file__).split(os.sep)[:len(os.path.realpath(os.getcwd()).split(os.sep))] \
        != os.path.realpath(os.getcwd()).split(os.sep):
    sys.exit(9)
args = sys.argv[1:]
if args[:2] != ["platform-status", "--fleet"] or args[2] != "--manifest" or len(args) != 4:
    sys.exit(8)
if not os.path.isfile(args[3]):
    sys.exit(7)
print(json.dumps({"platform": {"platform_version": "2.0.0"},
                  "fleet": [{"project_id": "a", "root": "/r/a", "compatible": True,
                             "removed_uses": []}]}))
"""
BRIDGE = """#!/bin/sh
[ -z "${PYTHONPATH+x}" ] || exit 9
[ "$*" = "platform-status --fleet" ] || exit 8
%s
"""
BRIDGE_JSON = json.dumps(fleet("1.2.0", [row("a")]))


class CutoverWorld:
    """A bare `origin`, a pusher that writes it, and a clone that has only `main`."""

    def __init__(self, test_case, main_ids=(1, 2)):
        tmp = tempfile.TemporaryDirectory()
        test_case.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name).resolve()
        patch = mock.patch.dict(os.environ, {
            "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"})
        patch.start()
        test_case.addCleanup(patch.stop)
        self.bare = self.tmp / "origin.git"
        self.git(self.tmp, "init", "-q", "--bare", "-b", "main", str(self.bare))
        self.pusher = self.tmp / "pusher"
        self.git(self.tmp, "init", "-q", "-b", "main", str(self.pusher))
        self.git(self.pusher, "remote", "add", "origin", str(self.bare))
        self.commit(self.pusher, manifests(main_ids=main_ids)[0])
        self.git(self.pusher, "push", "-q", "origin", "main")
        self.clone = self.tmp / "clone"
        self.git(self.tmp, "clone", "-q", str(self.bare), str(self.clone))

    @staticmethod
    def git(cwd, *args):
        return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True,
                              check=True, timeout=60).stdout.strip()

    def commit(self, repo, manifest, files=None):
        path = repo / MANIFEST
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(manifest), encoding="utf-8")
        for name, text in (files or {}).items():
            (repo / name).parent.mkdir(parents=True, exist_ok=True)
            (repo / name).write_text(text, encoding="utf-8")
        self.git(repo, "add", "-A")
        self.git(repo, "commit", "-q", "-m", "manifest")
        return self.git(repo, "rev-parse", "HEAD")

    def publish_candidate(self, removal_ids=(1, 2), files=None):
        self.git(self.pusher, "checkout", "-q", "-b", CANDIDATE_BRANCH)
        sha = self.commit(self.pusher, manifests(removal_ids=removal_ids)[1], files)
        self.git(self.pusher, "push", "-q", "origin", f"HEAD:refs/heads/{CANDIDATE_BRANCH}")
        self.git(self.pusher, "checkout", "-q", "main")
        return sha

    def refs(self):
        return self.git(self.clone, "for-each-ref")


class CutoverManifestTest(unittest.TestCase):
    def test_an_absent_candidate_branch_is_not_yet(self):
        world = CutoverWorld(self)
        code, report = verify_checks.cutover_manifest(world.clone, CANDIDATE_BRANCH)
        self.assertEqual((code, report["verdict"]), (75, "absent"))
        code, report = verify_checks.cutover_preflight(
            world.clone, CANDIDATE_BRANCH, environ=os.environ)
        self.assertEqual((code, report["verdict"]), (75, "absent"))

    def test_the_main_ref_names_the_main_side_and_is_not_fetched(self):
        world = CutoverWorld(self)
        world.publish_candidate()
        code, report = verify_checks.cutover_manifest(world.clone, main_ref="HEAD")
        self.assertEqual((code, report["verdict"], report["undeclared"]), (0, "green", []))
        self.assertEqual(report["removal_ids"], ["d1", "d2"])
        world.commit(world.clone, manifests(main_ids=(1,))[0])
        code, report = verify_checks.cutover_manifest(world.clone, main_ref="HEAD")
        self.assertEqual((code, report["verdict"], report["undeclared"]), (75, "red", ["d2"]))

    def test_without_a_main_ref_origin_main_is_the_main_side(self):
        world = CutoverWorld(self, main_ids=(1,))
        world.publish_candidate()
        code, report = verify_checks.cutover_manifest(world.clone, CANDIDATE_BRANCH)
        self.assertEqual((code, report["undeclared"]), (75, ["d2"]))
        world.git(world.pusher, "checkout", "-q", "main")
        world.commit(world.pusher, manifests()[0])
        world.git(world.pusher, "push", "-q", "origin", "main")
        code, report = verify_checks.cutover_manifest(world.clone, CANDIDATE_BRANCH)
        self.assertEqual((code, report["verdict"]), (0, "green"))

    def test_no_ref_is_written_in_the_clone(self):
        world = CutoverWorld(self, main_ids=(1,))
        world.publish_candidate()
        world.git(world.pusher, "checkout", "-q", "main")
        world.commit(world.pusher, manifests()[0])
        world.git(world.pusher, "push", "-q", "origin", "main")
        before = world.refs()
        self.assertIn("refs/remotes/origin/main", before)
        verify_checks.cutover_manifest(world.clone, CANDIDATE_BRANCH)
        self.assertEqual(world.refs(), before)

    def test_a_candidate_without_a_readable_manifest_is_usage(self):
        world = CutoverWorld(self)
        world.git(world.pusher, "checkout", "-q", "-b", CANDIDATE_BRANCH)
        world.git(world.pusher, "rm", "-q", MANIFEST)
        world.git(world.pusher, "commit", "-q", "-m", "drop")
        world.git(world.pusher, "push", "-q", "origin", f"HEAD:refs/heads/{CANDIDATE_BRANCH}")
        code, report = verify_checks.cutover_manifest(world.clone, CANDIDATE_BRANCH)
        self.assertEqual((code, report["verdict"]), (2, "unreadable"))

    def test_the_command_prints_the_report_and_exits_with_its_code(self):
        world = CutoverWorld(self)
        done = run_from_root([sys.executable, "-m", "agent_tools.verification.verify_checks", "cutover-manifest",
                              "--repo-root", str(world.clone)])
        self.assertEqual(done.returncode, 75, done.stderr)
        self.assertEqual(json.loads(done.stdout)["verdict"], "absent")
        world.publish_candidate()
        done = run_from_root([sys.executable, "-m", "agent_tools.verification.verify_checks", "cutover-manifest",
                              "--repo-root", str(world.clone), "--main-ref", "HEAD"])
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(done.stdout)["verdict"], "green")


class CutoverPreflightTest(unittest.TestCase):
    def setUp(self):
        self.world = CutoverWorld(self)
        self.sha = self.world.publish_candidate(files={
            "python/agent_tools/__init__.py": "",
            "python/agent_tools/project_contract/__init__.py": "",
            "python/agent_tools/project_contract/resolve_project.py": CANDIDATE_RESOLVER})
        self.bin = self.world.tmp / "bin"
        self.bin.mkdir()
        self.scratch = self.world.tmp / "scratch"
        self.scratch.mkdir()
        patch = mock.patch.object(tempfile, "tempdir", str(self.scratch))
        patch.start()
        self.addCleanup(patch.stop)

    def bridge(self, body):
        script = self.bin / "resolve-project"
        script.write_text(BRIDGE % body, encoding="utf-8")
        script.chmod(0o755)

    def environ(self):
        return {**os.environ, "PATH": f"{self.bin}:{os.environ['PATH']}", "PYTHONPATH": "python"}

    def preflight(self):
        return verify_checks.cutover_preflight(
            self.world.clone, CANDIDATE_BRANCH, environ=self.environ())

    def test_both_sides_judging_the_fleet_compatible_is_green(self):
        self.bridge(f"echo '{BRIDGE_JSON}'")
        code, report = self.preflight()
        self.assertEqual((code, report["verdict"]), (0, "green"), report)
        self.assertEqual(report["candidate"], self.sha)
        self.assertEqual(report["manifest"]["verdict"], "green")
        self.assertEqual([r["project_id"] for r in report["rows"]], ["a"])
        self.assertEqual(list(self.scratch.iterdir()), [])

    def test_the_bridge_failing_names_the_bridge(self):
        for body in ("exit 3", "echo not-json"):
            with self.subTest(body=body):
                self.bridge(body)
                code, report = self.preflight()
                self.assertEqual((code, report["verdict"], report["side"]),
                                 (75, "unreadable", "bridge"))
                self.assertEqual(list(self.scratch.iterdir()), [])

    def test_a_missing_bridge_names_the_bridge(self):
        environ = {**self.environ(), "PATH": f"{self.bin}:{Path(shutil.which('git')).parent}"}
        code, report = verify_checks.cutover_preflight(
            self.world.clone, CANDIDATE_BRANCH, environ=environ)
        self.assertEqual((code, report["verdict"], report["side"]), (75, "unreadable", "bridge"))

    def test_a_hung_side_times_out_and_is_named(self):
        self.bridge("exec sleep 10")
        started = time.monotonic()
        with mock.patch.object(verify_checks, "SIDE_TIMEOUT", 1):
            code, report = self.preflight()
        self.assertLess(time.monotonic() - started, 8)
        self.assertEqual((code, report["verdict"], report["side"]), (75, "unreadable", "bridge"))

    def test_the_candidate_side_failing_names_the_candidate(self):
        self.bridge(f"echo '{BRIDGE_JSON}'")
        self.world.git(self.world.pusher, "checkout", "-q", CANDIDATE_BRANCH)
        (self.world.pusher / "python/agent_tools/project_contract/resolve_project.py").write_text(
            "import sys\nsys.exit(4)\n", encoding="utf-8")
        self.world.git(self.world.pusher, "commit", "-q", "-am", "break")
        self.world.git(self.world.pusher, "push", "-q", "origin", f"HEAD:refs/heads/{CANDIDATE_BRANCH}")
        code, report = self.preflight()
        self.assertEqual((code, report["verdict"], report["side"]), (75, "unreadable", "candidate"))

    def test_a_pre_move_candidate_with_the_flat_resolver_is_judged_by_its_own_layout(self):
        # The recorded cutover candidate predates the domain layout: `agent_tools/resolve_project.py`.
        self.bridge(f"echo '{BRIDGE_JSON}'")
        self.world.git(self.world.pusher, "checkout", "-q", CANDIDATE_BRANCH)
        self.world.git(self.world.pusher, "rm", "-q",
                       "python/agent_tools/project_contract/resolve_project.py")
        (self.world.pusher / "python/agent_tools/resolve_project.py").write_text(
            CANDIDATE_RESOLVER, encoding="utf-8")
        self.world.git(self.world.pusher, "add", "-A")
        self.world.git(self.world.pusher, "commit", "-q", "-m", "flat layout")
        self.world.git(self.world.pusher, "push", "-q", "origin", f"HEAD:refs/heads/{CANDIDATE_BRANCH}")
        code, report = self.preflight()
        self.assertEqual((code, report["verdict"]), (0, "green"), report)

    def test_an_incompatible_candidate_row_is_not_yet(self):
        self.bridge(f"echo '{BRIDGE_JSON}'")
        self.world.git(self.world.pusher, "checkout", "-q", CANDIDATE_BRANCH)
        (self.world.pusher / "python/agent_tools/project_contract/resolve_project.py").write_text(
            CANDIDATE_RESOLVER.replace('"compatible": True', '"compatible": False'),
            encoding="utf-8")
        self.world.git(self.world.pusher, "commit", "-q", "-am", "incompatible")
        self.world.git(self.world.pusher, "push", "-q", "origin", f"HEAD:refs/heads/{CANDIDATE_BRANCH}")
        code, report = self.preflight()
        self.assertEqual((code, report["verdict"]), (75, "not_yet"))
        self.assertEqual(report["rows"][0]["reason"], "candidate_incompatible")

    def test_no_ref_is_written_in_the_clone(self):
        self.bridge(f"echo '{BRIDGE_JSON}'")
        before = self.world.refs()
        self.preflight()
        self.assertEqual(self.world.refs(), before)

    def test_the_command_runs_the_wrapper(self):
        self.bridge(f"echo '{BRIDGE_JSON}'")
        done = run_from_root(
            [str(ROOT / CHECKS / "cutover-preflight"), "--repo-root", str(self.world.clone)],
            {"HOME": str(self.world.tmp), "PATH": self.environ()["PATH"]})
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(done.stdout)["verdict"], "green")


def emitted(state, candidate):
    """A real emitted bundle (assemble_bundle, valid id) whose identity binds `candidate`."""
    identity = json.loads(json.dumps(IDENTITY))
    identity["bound"]["commit"]["candidate"] = candidate
    value = {"approved": flat(stratum(context(1000, 800))),
             "rejected": flat(stratum(context(1000, 999))), "unmeasured": None}[state]
    return agent_gate_bundle.assemble_bundle(
        {"identity": identity, "expansion": {"expanded": False, "checkpoint_ref": None}},
        value, [], None, state)


def emitted_claude_only(state, candidate, kind="cutover", version=2):
    """A real version-2 or version-3 bundle: claude-only evidence, bound to `candidate`, of reader kind `kind`."""
    identity = json.loads(json.dumps(IDENTITY))
    identity["bound"]["commit"]["candidate"] = candidate
    identity["pinned"]["builds"].pop("codex", None)
    profile = agent_gate_bundle.gate_profile(version, kind)
    value = {"approved": {"cases": [
                 dict(case, strata={"claude": case["strata"]["claude"]})
                 for case in flat(stratum(context(1000, 1000)))["cases"]]},
             "unmeasured": None}[state]
    return agent_gate_bundle.assemble_bundle(
        {"identity": identity, "expansion": {"expanded": False, "checkpoint_ref": None}},
        value, [], None, state, profile)


class BundleVerdictTest(unittest.TestCase):
    def test_an_approved_claude_only_cutover_bundle_is_green(self):
        code, report = verify_checks.bundle_verdict(
            {"cutover-130-bundle.json": emitted_claude_only("approved", SHA),
             "release-128-bundle.json": emitted("unmeasured", "b" * 40)}, SHA)
        self.assertEqual((code, report["verdict"], report["approved"]),
                         (0, "green", ["cutover-130-bundle.json"]))

    def test_an_approved_distributional_cutover_bundle_is_green(self):
        code, report = verify_checks.bundle_verdict(
            {"cutover-757-bundle.json": emitted_claude_only("approved", SHA, version=3)}, SHA)
        self.assertEqual((code, report["verdict"], report["approved"]),
                         (0, "green", ["cutover-757-bundle.json"]))

    def test_a_version_two_bundle_of_another_kind_is_unreadable(self):
        for kind in ("promotion", "release"):
            with self.subTest(kind=kind):
                code, report = verify_checks.bundle_verdict(
                    {"x-bundle.json": emitted_claude_only("unmeasured", SHA, kind)}, SHA)
                self.assertEqual((code, report["approved"]), (75, []))
                self.assertEqual([u["path"] for u in report["unreadable"]], ["x-bundle.json"])

    def test_a_relabelled_claude_only_bundle_is_unreadable(self):
        tampered = emitted_claude_only("approved", SHA)
        tampered["bundle_kind"] = "promotion"
        code, report = verify_checks.bundle_verdict({"x-bundle.json": tampered}, SHA)
        self.assertEqual((code, report["approved"]), (75, []))

    def test_an_approved_bundle_binding_the_candidate_is_green(self):
        code, report = verify_checks.bundle_verdict(
            {"a-bundle.json": emitted("approved", SHA),
             "release-128-bundle.json": emitted("unmeasured", "b" * 40)}, SHA)
        self.assertEqual((code, report["verdict"]), (0, "green"))
        self.assertEqual(report["approved"], ["a-bundle.json"])

    def test_unmeasured_rejected_or_another_candidate_is_not_yet(self):
        for bundles in ({}, {"x-bundle.json": emitted("unmeasured", SHA)},
                        {"x-bundle.json": emitted("rejected", SHA)},
                        {"x-bundle.json": emitted("approved", "b" * 40)}):
            with self.subTest(bundles=list(bundles)):
                self.assertEqual(verify_checks.bundle_verdict(bundles, SHA)[0], 75)

    def test_a_two_field_approval_is_unreadable(self):
        fake = {"state": "approved", "identity": {"bound": {"commit": {"candidate": SHA}}}}
        code, report = verify_checks.bundle_verdict({"x-bundle.json": fake}, SHA)
        self.assertEqual((code, [u["path"] for u in report["unreadable"]]), (75, ["x-bundle.json"]))

    def test_a_relabelled_bundle_is_unreadable(self):
        tampered = emitted("rejected", SHA)
        tampered["state"] = "approved"
        code, report = verify_checks.bundle_verdict({"x-bundle.json": tampered}, SHA)
        self.assertEqual((code, report["approved"]), (75, []))
        self.assertEqual([u["path"] for u in report["unreadable"]], ["x-bundle.json"])

    def test_a_rebound_candidate_breaks_the_digest(self):
        moved = emitted("approved", "b" * 40)
        moved["identity"]["bound"]["commit"]["candidate"] = SHA
        self.assertEqual(verify_checks.bundle_verdict({"x-bundle.json": moved}, SHA)[0], 75)

    def test_a_candidate_that_is_not_a_commit_id_is_unreadable(self):
        for bound in ("unpinned", "A" * 40, "a" * 39, None):
            with self.subTest(bound=bound):
                code, report = verify_checks.bundle_verdict(
                    {"x-bundle.json": emitted("approved", bound)}, bound)
                self.assertEqual((code, report["approved"]), (75, []))
                self.assertEqual([u["path"] for u in report["unreadable"]], ["x-bundle.json"])

    def test_the_committed_cutover_bundle_verifies_unmeasured(self):
        doc = json.loads((ROOT / ".agents/artifacts/evidence/cutover-579-bundle.json").read_text())
        self.assertEqual(agent_gate_bundle.verify_bundle(doc), "unmeasured")
        self.assertRegex(doc["identity"]["bound"]["commit"]["candidate"], r"^[0-9a-f]{40}$")

    def test_the_wrapper_is_committed_executable(self):
        self.assertEqual(committed_mode(f"{CHECKS}/cutover-bundle"), "100755")


EVIDENCE = ".agents/artifacts/evidence"


class CutoverBundleTest(unittest.TestCase):
    def test_the_check_reads_the_bundles_at_origin_main(self):
        world = CutoverWorld(self)
        candidate = world.publish_candidate()
        code, report = verify_checks.cutover_bundle(world.clone, CANDIDATE_BRANCH)
        self.assertEqual((code, report["approved"], report["candidate"]), (75, [], candidate))
        files = {f"{EVIDENCE}/a-bundle.json": json.dumps(emitted("approved", candidate)),
                 f"{EVIDENCE}/b-bundle.json": "not json",
                 f"{EVIDENCE}/c-trials.json": "{}"}
        world.commit(world.pusher, manifests()[0], files)
        world.git(world.pusher, "push", "-q", "origin", "main")
        code, report = verify_checks.cutover_bundle(world.clone, CANDIDATE_BRANCH)
        self.assertEqual((code, report["verdict"]), (0, "green"))
        self.assertEqual(report["approved"], [f"{EVIDENCE}/a-bundle.json"])
        self.assertEqual([u["path"] for u in report["unreadable"]], [f"{EVIDENCE}/b-bundle.json"])

    def test_an_absent_candidate_branch_is_not_yet(self):
        world = CutoverWorld(self)
        code, report = verify_checks.cutover_bundle(world.clone, CANDIDATE_BRANCH)
        self.assertEqual((code, report["verdict"]), (75, "absent"))


if __name__ == "__main__":
    unittest.main()


RUNNERS = "repos/elevenyellow/jarbird/actions/runners?per_page=100"
WANTED = ("nix", "eleven-m5", "jarbird")


def runner_entry(name="eleven-m5-jarbird", status="online",
                 labels=("self-hosted", "macOS", "ARM64", "nix", "eleven-m5", "jarbird")):
    return {"id": 1, "name": name, "status": status, "busy": False,
            "labels": [{"id": i, "name": label, "type": "custom"} for i, label in enumerate(labels)]}


def judge_runner(entries, total=None):
    get, pages = forge({}, {RUNNERS: [{"total_count": len(entries) if total is None else total,
                                       "runners": list(entries)}]})
    with get, pages:
        return self_hosted_runner("elevenyellow/jarbird", "eleven-m5-jarbird", WANTED)


class SelfHostedRunnerTest(unittest.TestCase):
    def test_an_online_runner_with_every_label_is_met(self):
        code, report = judge_runner([runner_entry(name="other"), runner_entry()])
        self.assertEqual(code, 0)
        self.assertEqual((report["found"], report["status"], report["missing"]), (True, "online", []))
        self.assertEqual(report["required"], ["eleven-m5", "jarbird", "nix", "self-hosted"])

    def test_a_missing_label_is_not_met(self):
        code, report = judge_runner([runner_entry(labels=("self-hosted", "nix", "eleven-m5"))])
        self.assertEqual((code, report["missing"]), (1, ["jarbird"]))

    def test_an_offline_runner_is_not_yet(self):
        self.assertEqual(judge_runner([runner_entry(status="offline")])[0], 75)

    def test_an_unlisted_runner_is_not_yet(self):
        code, report = judge_runner([runner_entry(name="eleven-m5-arcwave")])
        self.assertEqual((code, report["found"], report["status"]), (75, False, None))

    def test_a_truncated_listing_is_refused(self):
        with self.assertRaises(forge_api.ForgeError):
            judge_runner([runner_entry()], total=2)

    def test_malformed_entries_are_refused(self):
        bad_labels = runner_entry()
        bad_labels["labels"] = ["jarbird"]
        no_status = runner_entry()
        del no_status["status"]
        for entries in (["eleven-m5-jarbird"], [{"status": "online"}], [bad_labels], [no_status]):
            with self.subTest(entries=entries):
                with self.assertRaises(forge_api.ForgeError):
                    judge_runner(entries)


class SelfHostedRunnerCommandTest(unittest.TestCase):
    ARGS = ["--repo", "elevenyellow/jarbird", "--runner", "eleven-m5-jarbird",
            "--label", "nix", "--label", "eleven-m5", "--label", "jarbird"]

    def test_wrapper_maps_a_forge_error_to_exit_2(self):
        # PATH holds only python3, so the wrapper finds its interpreter and gh is missing.
        with tempfile.TemporaryDirectory() as tmp:
            os.symlink(sys.executable, Path(tmp) / "python3")
            done = run_from_root(["/bin/sh", str(ROOT / CHECKS / "self-hosted-runner"), *self.ARGS],
                                 {"PATH": tmp})
        self.assertEqual((done.returncode, done.stdout), (2, ""), done.stderr)
        self.assertIn("forge_error", done.stderr)

    def test_a_malformed_listing_exits_2_through_main(self):
        get, pages = forge({}, {RUNNERS: [{"total_count": 1, "runners": [{"status": "online"}]}]})
        with get, pages, mock.patch("sys.stdout") as out, mock.patch("sys.stderr") as err:
            code = verify_checks.main(["self-hosted-runner", *self.ARGS])
        self.assertEqual(code, 2)
        out.write.assert_not_called()
        self.assertIn("forge_error: payload_invalid", "".join(c.args[0] for c in err.write.call_args_list))

    def test_bad_arguments_never_reach_the_forge(self):
        cases = (["--repo", "jarbird", *self.ARGS[2:]],
                 [*self.ARGS[:2], "--runner", "", *self.ARGS[4:]],
                 [*self.ARGS[:4], "--label", ""],
                 self.ARGS[:4])
        for argv in cases:
            with self.subTest(argv=argv):
                with mock.patch.object(verify_checks, "self_hosted_runner",
                                       side_effect=AssertionError("reached the forge")):
                    with self.assertRaises(SystemExit) as raised:
                        verify_checks.main(["self-hosted-runner", *argv])
                self.assertEqual(raised.exception.code, 2)

    def test_main_prints_the_report_and_returns_the_code(self):
        with mock.patch.object(verify_checks, "self_hosted_runner", return_value=(75, {"found": False})) as called:
            with mock.patch("sys.stdout") as out:
                code = verify_checks.main(["self-hosted-runner", *self.ARGS])
        self.assertEqual(code, 75)
        called.assert_called_once_with("elevenyellow/jarbird", "eleven-m5-jarbird", ["nix", "eleven-m5", "jarbird"])
        out.write.assert_any_call('{"found": false}')

    def test_wrapper_is_committed_executable(self):
        self.assertEqual(committed_mode(f"{CHECKS}/self-hosted-runner"), "100755")


class GuardFleetWorld(GuardPolicyWorld):
    """A hermetic fleet plus a clone whose origin carries the cutover candidate: the real
    `python/` tree and platform manifest, committed on `cutover-130-candidate`."""

    def __init__(self, test_case):
        super().__init__(test_case)
        bare = self.tmp / "candidate-origin.git"
        pusher = self.tmp / "candidate-pusher"
        self.clone = self.tmp / "candidate-clone"
        self.git(self.tmp, "init", "--quiet", "--bare", "-b", "main", str(bare))
        self.git(self.tmp, "init", "--quiet", "-b", "main", str(pusher))
        self.git(pusher, "config", "commit.gpgsign", "false")
        self.git(pusher, "remote", "add", "origin", str(bare))
        (pusher / "README").write_text("main\n", encoding="utf-8")
        self.git(pusher, "add", "-A")
        self.git(pusher, "commit", "--quiet", "-m", "main")
        self.git(pusher, "push", "--quiet", "origin", "main")
        self.git(pusher, "checkout", "--quiet", "-b", CANDIDATE_BRANCH)
        shutil.copytree(ROOT / "python", pusher / "python",
                        ignore=shutil.ignore_patterns("__pycache__"))
        (pusher / verify_checks.MANIFEST_PATH).parent.mkdir(parents=True)
        shutil.copy(ROOT / verify_checks.MANIFEST_PATH, pusher / verify_checks.MANIFEST_PATH)
        self.git(pusher, "add", "-A")
        self.git(pusher, "commit", "--quiet", "-m", "candidate")
        self.git(pusher, "push", "--quiet", "origin", f"HEAD:refs/heads/{CANDIDATE_BRANCH}")
        self.git(self.tmp, "clone", "--quiet", str(bare), str(self.clone))

    def fleet(self, registry=None):
        # The host's own PYTHONPATH must not decide whose code derives: the check does.
        environ = {key: value for key, value in self.env.items() if key != "PYTHONPATH"}
        return verify_checks.guard_policy_fleet(
            self.clone, CANDIDATE_BRANCH, environ=environ, registry=registry)

    def lagging_default(self, project_id, slug, *, override):
        """The anis-desktop nodocom entry: `main` is a schema-1 contract, `dev` a schema-2 one,
        and the registry entry carries the `branch_override` only when `override` is true."""
        root = self.project(project_id, slug, integration_branch="dev", register=False)
        self.git(root, "checkout", "--quiet", "main")
        old = self.contract(project_id, slug)
        old["schema_version"] = 1
        self.commit_contract(root, old, "the project's schema-1 default branch", render=False)
        self.publish(root, ["main", "dev"])
        entry = {"project_id": project_id, "root": str(root)}
        if override:
            entry["branch_override"] = {"branch": "dev", "default_branch": "main",
                                        "reason": "default_contract_unresolved"}
        self.register(entry)


class GuardPolicyFleetTest(unittest.TestCase):
    def setUp(self):
        self.world = GuardFleetWorld(self)

    def test_every_registered_slug_deriving_is_green(self):
        self.world.project("fixture/one", "fagenorn/one")
        self.world.project("fixture/two", "fagenorn/two")
        code, report = self.world.fleet()
        self.assertEqual((code, report["verdict"]), (0, "green"), report)
        self.assertEqual([(r["repository"], r["exit"], r["outcome"]) for r in report["rows"]],
                         [("fagenorn/one", 0, "derived"), ("fagenorn/two", 0, "derived")])

    def test_the_anis_desktop_nodocom_entry_reads_red(self):
        self.world.project("fixture/one", "fagenorn/one")
        self.world.lagging_default("elevenyellow/nodocom", "elevenyellow/nodocom",
                                   override=False)
        code, report = self.world.fleet()
        self.assertEqual((code, report["verdict"]), (1, "red"), report)
        [bad] = [r for r in report["rows"] if r["verdict"] == "red"]
        self.assertEqual((bad["repository"], bad["exit"], bad["outcome"], bad["reason_codes"]),
                         ("elevenyellow/nodocom", 1, "refused", ["contract_unresolved"]))
        [good] = [r for r in report["rows"] if r["verdict"] == "green"]
        self.assertEqual(good["repository"], "fagenorn/one")

    def test_the_same_entry_with_the_override_is_green(self):
        self.world.lagging_default("elevenyellow/nodocom", "elevenyellow/nodocom",
                                   override=True)
        code, report = self.world.fleet()
        self.assertEqual((code, report["verdict"]), (0, "green"), report)

    def test_an_entry_whose_origin_names_no_slug_is_red(self):
        root = self.world.project("fixture/one", "fagenorn/one")
        self.world.identity(root, "git@gitlab.com:fagenorn/one.git")
        code, report = self.world.fleet()
        self.assertEqual((code, report["verdict"]), (1, "red"), report)
        self.assertEqual([(r["repository"], r["outcome"]) for r in report["rows"]],
                         [(None, "origin_unproven")])

    def test_an_unreadable_registry_is_red_not_empty(self):
        self.world.project("fixture/one", "fagenorn/one")
        self.world.write_registry("{not json")
        code, report = self.world.fleet()
        self.assertEqual((code, report["verdict"]), (75, "unreadable"), report)

    def test_a_named_registry_file_that_is_missing_is_unreadable(self):
        self.world.project("fixture/one", "fagenorn/one")
        code, report = self.world.fleet(registry=self.world.tmp / "no-such-registry.json")
        self.assertEqual((code, report["verdict"], report["side"], report["rows"]),
                         (75, "unreadable", "registry", []))

    def test_an_absent_default_registry_is_the_empty_fleet(self):
        (self.world.home / ".agents/state/fleet/registry.json").unlink(missing_ok=True)
        code, report = self.world.fleet()
        self.assertEqual((code, report["verdict"], report["rows"]), (0, "green", []))

    def test_a_registry_the_guard_would_refuse_is_unreadable(self):
        root = self.world.project("fixture/one", "fagenorn/one")
        entries = [{"project_id": "fixture/one", "root": str(root)}]
        for name, document in (
                ("no-schema", {"projects": entries}),
                ("wrong-schema", {"schema_version": "1", "projects": entries}),
                ("extra-member", {"schema_version": 1, "projects": entries, "note": "x"})):
            with self.subTest(name=name):
                path = self.world.tmp / f"{name}.json"
                path.write_text(json.dumps(document), encoding="utf-8")
                code, report = self.world.fleet(registry=path)
                self.assertEqual((code, report["verdict"], report["side"]),
                                 (75, "unreadable", "registry"), report)

    def test_a_registry_file_replaces_the_hosts_own(self):
        self.world.project("fixture/one", "fagenorn/one")
        empty = self.world.tmp / "empty-registry.json"
        empty.write_text(json.dumps({"schema_version": 1, "projects": []}), encoding="utf-8")
        code, report = self.world.fleet(registry=empty)
        self.assertEqual((code, report["verdict"], report["rows"]), (0, "green", []))

    def test_an_absent_candidate_branch_is_not_yet(self):
        self.world.project("fixture/one", "fagenorn/one")
        code, report = verify_checks.guard_policy_fleet(
            self.world.clone, "no-such-branch", environ=self.world.env)
        self.assertEqual((code, report["verdict"]), (75, "absent"))

    def test_a_candidate_without_its_python_tree_is_unreadable(self):
        self.world.project("fixture/one", "fagenorn/one")
        pusher = self.world.tmp / "candidate-pusher"
        self.world.git(pusher, "rm", "-rq", "python")
        self.world.git(pusher, "commit", "--quiet", "-m", "no python")
        self.world.git(pusher, "push", "--quiet", "origin", f"HEAD:refs/heads/{CANDIDATE_BRANCH}")
        code, report = self.world.fleet()
        self.assertEqual((code, report["verdict"], report["side"]), (75, "unreadable", "candidate"))

    def test_the_candidate_home_keeps_the_hosts_forge_and_git_configuration(self):
        home = self.world.tmp / "real-home"
        home.mkdir()
        (home / ".gitconfig").write_text("[user]\n\tname = t\n", encoding="utf-8")
        env = verify_checks._candidate_env({"HOME": str(home), "PYTHONPATH": "host"},
                                           Path("/c/home"), Path("/c/python"))
        self.assertEqual((env["HOME"], env["PYTHONPATH"]), ("/c/home", "/c/python"))
        self.assertEqual(env["GH_CONFIG_DIR"], str(home / ".config/gh"))
        self.assertEqual(env["GIT_CONFIG_GLOBAL"], str(home / ".gitconfig"))
        kept = verify_checks._candidate_env(
            {"HOME": str(home), "GH_CONFIG_DIR": "/gh", "GIT_CONFIG_GLOBAL": "/dev/null"},
            Path("/c/home"), Path("/c/python"))
        self.assertEqual((kept["GH_CONFIG_DIR"], kept["GIT_CONFIG_GLOBAL"]), ("/gh", "/dev/null"))

    def test_a_pre_move_candidate_with_the_flat_guard_policy_is_derived_by_its_own_layout(self):
        # The recorded cutover candidate predates the domain layout: `agent_tools/guard_policy.py`.
        self.world.project("fixture/one", "fagenorn/one")
        pusher = self.world.tmp / "candidate-pusher"
        self.world.git(pusher, "rm", "-q", "python/agent_tools/guard/guard_policy.py")
        (pusher / "python/agent_tools/guard_policy.py").write_text(
            "import json\nprint(json.dumps({'outcome': 'derived', 'refused': [], 'row': {}}))\n",
            encoding="utf-8")
        self.world.git(pusher, "add", "-A")
        self.world.git(pusher, "commit", "--quiet", "-m", "flat layout")
        self.world.git(pusher, "push", "--quiet", "origin", f"HEAD:refs/heads/{CANDIDATE_BRANCH}")
        code, report = self.world.fleet()
        self.assertEqual((code, report["verdict"]), (0, "green"), report)
        self.assertEqual([(r["repository"], r["outcome"]) for r in report["rows"]],
                         [("fagenorn/one", "derived")])

    def test_the_candidates_code_derives_not_the_hosts(self):
        # A candidate whose guard-policy is broken reads unreadable even though the host's
        # own PYTHONPATH (the world's) holds a working one.
        self.world.project("fixture/one", "fagenorn/one")
        pusher = self.world.tmp / "candidate-pusher"
        (pusher / "python/agent_tools/guard/guard_policy.py").write_text(
            "import sys\nsys.exit(4)\n", encoding="utf-8")
        self.world.git(pusher, "commit", "--quiet", "-am", "break")
        self.world.git(pusher, "push", "--quiet", "origin", f"HEAD:refs/heads/{CANDIDATE_BRANCH}")
        code, report = self.world.fleet()
        self.assertEqual((code, report["verdict"]), (1, "red"), report)
        self.assertEqual(report["rows"][0]["outcome"], "unreadable")


class RegistryAgreementTest(unittest.TestCase):
    OVERRIDE = {"branch": "dev", "default_branch": "main",
                "reason": "default_contract_unresolved"}

    def entries(self, override=None):
        entry = {"project_id": "elevenyellow/nodocom", "root": "/x"}
        if override is not None:
            entry["branch_override"] = override
        return [entry]

    def test_hosts_that_agree_are_green(self):
        for override in (None, self.OVERRIDE):
            with self.subTest(override=override):
                code, report = verify_checks.registry_agreement(
                    {"mbp": self.entries(override), "anis-desktop": self.entries(override)})
                self.assertEqual((code, report["verdict"]), (0, "green"), report)

    def test_the_anis_desktop_entry_without_the_override_is_red(self):
        code, report = verify_checks.registry_agreement(
            {"mbp": self.entries(self.OVERRIDE), "anis-desktop": self.entries()})
        self.assertEqual((code, report["verdict"]), (1, "red"), report)
        [row] = report["rows"]
        self.assertEqual((row["project_id"], row["verdict"]), ("elevenyellow/nodocom", "red"))
        self.assertEqual(row["branch_override"], {"mbp": self.OVERRIDE, "anis-desktop": None})

    def test_a_recorded_intentional_difference_is_green(self):
        code, report = verify_checks.registry_agreement(
            {"mbp": self.entries(self.OVERRIDE), "anis-desktop": self.entries()},
            intentional={"elevenyellow/nodocom"})
        self.assertEqual((code, report["verdict"]), (0, "green"), report)
        self.assertEqual(report["rows"][0]["verdict"], "intentional")

    def test_a_project_on_one_host_is_not_compared(self):
        code, report = verify_checks.registry_agreement(
            {"mbp": self.entries(self.OVERRIDE), "anis-desktop": []})
        self.assertEqual((code, report["verdict"], report["rows"]), (0, "green", []))

    def test_main_reads_registry_files_and_exits_with_the_verdict(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        files = []
        for host, override in (("mbp", self.OVERRIDE), ("anis-desktop", None)):
            path = Path(tmp.name) / f"{host}.json"
            path.write_text(json.dumps({"schema_version": 1, "projects": self.entries(override)}),
                            encoding="utf-8")
            files.append(f"{host}={path}")
        with mock.patch("sys.stdout"):
            red = verify_checks.main(["registry-agreement", "--registry", *files])
            green = verify_checks.main(["registry-agreement", "--registry", *files,
                                        "--intentional", "elevenyellow/nodocom"])
        self.assertEqual((red, green), (1, 0))

    def test_main_refuses_a_missing_registry_file(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        good = Path(tmp.name) / "good.json"
        good.write_text(json.dumps({"schema_version": 1, "projects": self.entries()}),
                        encoding="utf-8")
        with mock.patch("sys.stderr"), mock.patch("sys.stdout"):
            self.assertEqual(verify_checks.main(
                ["registry-agreement", "--registry", f"mbp={good}",
                 f"anis-desktop={Path(tmp.name) / 'absent.json'}"]), 2)

    def test_main_refuses_a_registry_file_the_guard_would_refuse(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        bad = Path(tmp.name) / "no-schema.json"
        bad.write_text(json.dumps({"projects": self.entries()}), encoding="utf-8")
        with mock.patch("sys.stderr"), mock.patch("sys.stdout"):
            self.assertEqual(verify_checks.main(
                ["registry-agreement", "--registry", f"mbp={bad}", f"x={bad}"]), 2)

    def test_main_refuses_an_unreadable_registry_file(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        bad = Path(tmp.name) / "bad.json"
        bad.write_text("{not json", encoding="utf-8")
        with mock.patch("sys.stderr"):
            self.assertEqual(verify_checks.main(
                ["registry-agreement", "--registry", f"mbp={bad}", f"x={bad}"]), 2)


GOOD = "/etc/profiles/per-user/tester/bin:/run/current-system/sw/bin:/usr/bin:/bin"
BAD = "/usr/local/bin:/usr/bin:/bin:/etc/profiles/per-user/tester/bin"
PY313 = "Python 3.13.12"
PY39 = "Python 3.9.6"
UNREADABLE = {"readable": False, "path": None, "profile_before_usr_bin": False,
              "python": None, "python_ok": False, "met": False}


def lines(path, py):
    return ["__VERIFY_PATH__=" + path, "__VERIFY_PYTHON__=" + py]


def fake_zsh(directory, clean_lines, inherited_lines):
    """An executable stand-in for zsh that records each run and prints baked sentinel lines."""
    directory = Path(directory)
    calls = directory / "calls"
    script = directory / "zsh"

    def printing(baked):
        return "printf '%s\\n' " + " ".join(f"'{line}'" for line in baked)

    script.write_text(
        "#!/bin/sh\n"
        f'echo "$*|$PATH|${{__NIX_DARWIN_SET_ENVIRONMENT_DONE-unset}}|$HOME|$USER|$TERM" >> {calls}\n'
        'if [ -n "${__NIX_DARWIN_SET_ENVIRONMENT_DONE+x}" ]; then\n'
        f"{printing(inherited_lines)}\nelse\n{printing(clean_lines)}\nfi\n", encoding="utf-8")
    script.chmod(0o755)
    return script, calls


class ShellPathVerdictTest(unittest.TestCase):
    def test_profile_first_and_python_313_is_met(self):
        self.assertEqual(verify_checks.shell_path_verdict(GOOD, PY313, "tester"),
                         {"readable": True, "path": GOOD, "profile_before_usr_bin": True,
                          "python": "3.13.12", "python_ok": True, "met": True})

    def test_usr_bin_first_is_not_met(self):
        verdict = verify_checks.shell_path_verdict(BAD, PY313, "tester")
        self.assertFalse(verdict["profile_before_usr_bin"])
        self.assertFalse(verdict["met"])

    def test_python_39_is_not_met(self):
        verdict = verify_checks.shell_path_verdict(GOOD, PY39, "tester")
        self.assertEqual(verdict["python"], "3.9.6")
        self.assertFalse(verdict["python_ok"])
        self.assertFalse(verdict["met"])

    def test_python_314_is_met(self):
        self.assertTrue(verify_checks.shell_path_verdict(GOOD, "Python 3.14.0", "tester")["met"])

    def test_missing_python_is_not_met(self):
        verdict = verify_checks.shell_path_verdict(
            GOOD, "zsh:1: command not found: python3", "tester")
        self.assertIsNone(verdict["python"])
        self.assertFalse(verdict["python_ok"])

    def test_another_users_profile_does_not_count(self):
        self.assertFalse(
            verify_checks.shell_path_verdict(GOOD, PY313, "someone")["profile_before_usr_bin"])

    def test_missing_usr_bin_is_not_met(self):
        verdict = verify_checks.shell_path_verdict(
            "/etc/profiles/per-user/tester/bin:/bin", PY313, "tester")
        self.assertFalse(verdict["profile_before_usr_bin"])


class DarwinShellPathTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)

    def run_check(self, clean, inherited):
        script, calls = fake_zsh(self.tmp, clean, inherited)
        code, report = verify_checks.darwin_shell_path(
            user="tester", home=str(self.tmp), zsh_bin=str(script))
        return code, report, calls

    def test_both_probes_met_exits_0_and_runs_fresh_login_interactive_shells(self):
        code, report, calls = self.run_check(lines(GOOD, PY313), lines(GOOD, PY313))
        self.assertEqual(code, 0)
        self.assertTrue(report["met"])
        self.assertTrue(report["probes"]["clean"]["met"])
        self.assertTrue(report["probes"]["inherited"]["met"])
        recorded = calls.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(recorded), 2)
        rows = [line.rsplit("|", 5) for line in recorded]
        for argv, *_ in rows:
            self.assertTrue(argv.startswith('-l -i -c print -r -- "__VERIFY_PATH__=$PATH"'), argv)
        _, path, flag, home, user, term = rows[0]
        self.assertEqual((path, flag, term), ("/usr/bin:/bin:/usr/sbin:/sbin", "unset", "dumb"))
        _, path, flag, home2, user2, _ = rows[1]
        self.assertEqual((path, flag), (verify_checks.INHERITED_PATH.format(user="tester"), "1"))
        self.assertEqual((home, user, home2, user2), (str(self.tmp), "tester") * 2)

    def test_inherited_usr_bin_first_exits_1(self):
        code, report, _ = self.run_check(lines(GOOD, PY313), lines(BAD, PY39))
        self.assertEqual(code, 1)
        self.assertTrue(report["probes"]["clean"]["met"])
        self.assertFalse(report["probes"]["inherited"]["met"])
        self.assertEqual(report["probes"]["inherited"]["path"], BAD)

    def test_banner_noise_around_the_sentinels_is_ignored(self):
        clean = ["Que?", "__VERIFY_PATH__=/usr/bin", *lines(GOOD, PY313), "bye"]
        code, _, _ = self.run_check(clean, lines(GOOD, PY313))
        self.assertEqual(code, 0)

    def test_a_shell_without_sentinels_is_unreadable_and_exits_2(self):
        code, report, _ = self.run_check(lines(GOOD, PY313), ["nothing here"])
        self.assertEqual(code, 2)
        self.assertEqual(report["probes"]["inherited"], UNREADABLE)

    def test_a_missing_shell_is_unreadable_and_exits_2(self):
        code, report = verify_checks.darwin_shell_path(
            user="tester", home=str(self.tmp), zsh_bin=str(self.tmp / "absent"))
        self.assertEqual(code, 2)
        self.assertFalse(report["probes"]["clean"]["readable"])
        self.assertFalse(report["probes"]["inherited"]["readable"])


class DarwinShellPathCommandTest(unittest.TestCase):
    def test_the_command_prints_one_json_line_and_exits_with_the_verdict(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        me = pwd.getpwuid(os.getuid()).pw_name
        good = lines(f"/etc/profiles/per-user/{me}/bin:/usr/bin", PY313)
        script, _ = fake_zsh(tmp.name, good, good)
        result = run_from_root([sys.executable, "-m", "agent_tools.verification.verify_checks",
                                "darwin-shell-path", "--zsh", str(script)])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["met"])

    def test_the_check_script_is_committed_executable(self):
        self.assertEqual(committed_mode(f"{CHECKS}/darwin-shell-path"), "100755")


class DarwinShellPathWrapperTest(unittest.TestCase):
    """The committed check script, run as verify-pending or a user runs it, under the PATH it diagnoses."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.me = pwd.getpwuid(os.getuid()).pw_name
        self.home = self.tmp / "home"
        (self.home / ".agents" / "bin").mkdir(parents=True)
        self.stubs = self.tmp / "stubs"
        self.stubs.mkdir()
        good = lines(f"/etc/profiles/per-user/{self.me}/bin:/usr/bin", PY313)
        self.zsh, _ = fake_zsh(self.tmp, good, good)

    def launcher(self, interpreter):
        """A managed launcher in the shape lib/agent-tools.nix writes, naming `interpreter`."""
        path = self.home / ".agents" / "bin" / "verify-pending"
        path.write_text("#!/bin/sh\nunset NIX_PYTHONPATH NIX_PYTHONPREFIX NIX_PYTHONEXECUTABLE\n"
                        f'exec {interpreter} -I -m agent_tools.verification.verify_pending "$@"\n',
                        encoding="utf-8")

    def old_python3(self):
        """A python3 first on PATH that cannot run the package, as Xcode's 3.9 cannot."""
        stub = self.stubs / "python3"
        stub.write_text("#!/bin/sh\necho 'old python3 cannot import agent_tools' >&2\nexit 1\n",
                        encoding="utf-8")
        stub.chmod(0o755)

    def run_script(self):
        env = {"HOME": str(self.home), "PATH": f"{self.stubs}:/usr/bin:/bin"}
        return subprocess.run(["/bin/sh", str(ROOT / CHECKS / "darwin-shell-path"),
                               "--zsh", str(self.zsh)], cwd=ROOT, env=env,
                              capture_output=True, text=True, timeout=60)

    def test_it_starts_with_the_managed_interpreter_when_python3_on_path_cannot_run_the_package(self):
        self.old_python3()
        self.launcher(sys.executable)
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["met"])

    def test_it_exits_2_when_there_is_no_managed_launcher(self):
        result = self.run_script()
        self.assertEqual(result.returncode, 2)
        self.assertIn("verify-pending", result.stderr)

    def test_it_exits_2_when_the_launcher_names_no_runnable_interpreter(self):
        self.launcher(self.tmp / "absent" / "python3")
        result = self.run_script()
        self.assertEqual(result.returncode, 2)
        self.assertIn("verify-pending", result.stderr)


class ConsoleStateTest(unittest.TestCase):
    """`console-state` (issue 856): the console's state endpoint answers 200 on loopback."""

    def setUp(self):
        handle = tempfile.TemporaryDirectory()
        self.addCleanup(handle.cleanup)
        self.tmp = Path(handle.name)

    def console(self):
        support.write_registry(self.tmp / "registry.json", [])
        svc = support.service(self, self.tmp / "events.sqlite3", self.tmp / "registry.json")
        return svc.address[1]

    def stub(self, routes):
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(routes.get(self.path.split("?", 1)[0], 404))
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *args):
                pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server.server_address[1]

    def closed_port(self):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            return sock.getsockname()[1]

    def test_a_running_console_is_met(self):
        port = self.console()
        self.assertEqual(verify_checks.console_state(port), (0, {"port": port, "status": 200}))

    def test_another_status_on_the_state_endpoint_is_not_met(self):
        port = self.stub({"/": 200, "/api/state": 503})
        self.assertEqual(verify_checks.console_state(port), (1, {"port": port, "status": 503}))

    def test_no_answer_is_not_met_with_the_error(self):
        port = self.closed_port()
        code, report = verify_checks.console_state(port)
        self.assertEqual(code, 1)
        self.assertIsNone(report["status"])
        self.assertTrue(report["error"].startswith("ConnectionRefusedError: "), report["error"])
        self.assertEqual(report["port"], port)

    def test_the_command_prints_one_json_line(self):
        port = self.console()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = verify_checks.main(["console-state", "--port", str(port)])
        self.assertEqual(code, 0)
        self.assertEqual(out.getvalue(), json.dumps({"port": port, "status": 200}, sort_keys=True) + "\n")

    def test_a_missing_or_bad_port_is_a_usage_error(self):
        for argv in (["console-state"], ["console-state", "--port", "0"]):
            with self.subTest(argv=argv):
                with contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as raised:
                        verify_checks.main(argv)
                self.assertEqual(raised.exception.code, 2)

    def test_the_wrapper_runs_the_check(self):
        port = self.console()
        result = run_from_root([str(ROOT / CHECKS / "console-state"), "--port", str(port)])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"port": port, "status": 200})

    def test_wrapper_is_committed_executable(self):
        self.assertEqual(committed_mode(f"{CHECKS}/console-state"), "100755")


class ConsoleFailedStartTest(unittest.TestCase):
    """`console-failed-start` (issue 1182): an open failed-start card's sprint line reads the failed start."""

    SID = "a" * 16
    T0 = "2026-11-12T10:00:00.000000+00:00"
    REASON = ("Workspace not trusted. Run `claude` in /home/x/p once and accept the trust prompt, "
              "then retry.")

    def real_view(self):
        t0_ms = int(datetime.fromisoformat(self.T0).timestamp() * 1000)
        sprint = dataclasses.replace(
            SprintState(self.SID, "p00", "make the importer resumable", 5, self.T0),
            manager=Manager("failed", self.T0, reason=self.REASON))
        view = console_view.derive_view([ProjectState("p00", "/srv/p00", 1, "t1")],
                                        sprints={self.SID: sprint}, now_ms=t0_ms + 60_000)
        return json.loads(console_view.encode_view(view))

    def stub(self, routes):
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                status, body = routes.get(self.path.split("?", 1)[0], (404, b""))
                self.send_response(status)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server.server_address[1]

    def closed_port(self):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            return sock.getsockname()[1]

    def test_no_open_card_is_not_yet(self):
        self.assertEqual(verify_checks.failed_start_state({"inbox": {"open": []}, "entries": []}),
                         (75, {"verdict": "not_yet", "cards": 0}))

    def test_a_card_whose_line_reads_the_failed_start_is_met(self):
        self.assertEqual(verify_checks.failed_start_state(self.real_view()),
                         (0, {"verdict": "met", "cards": 1}))

    def test_a_wrong_line_ball_retry_or_reason_is_not_met(self):
        def sprint_of(view):
            return verify_checks._sprint_entries(view)[0]

        def card_of(view):
            return view["inbox"]["open"][0]

        def drop(view):
            for project in view["entries"]:
                project["sprints"] = []

        cases = (
            ("line", lambda v: sprint_of(v).update(now_text="drafting the brief")),
            ("ball", lambda v: sprint_of(v).update(ball="nobody")),
            ("retry", lambda v: sprint_of(v).update(retry=False)),
            ("reason", lambda v: card_of(v).update(last_reason="Run claude in /home/x/p")),
            ("reason", lambda v: card_of(v).update(last_reason="Workspace not trusted")),
            ("reason", lambda v: card_of(v).update(last_reason="   ")),
            ("reason", lambda v: card_of(v).update(last_reason="")),
            ("reason", lambda v: card_of(v).update(last_reason=None)),
            ("line", drop))
        for index, (problem, mutate) in enumerate(cases):
            with self.subTest(index=index, problem=problem):
                view = self.real_view()
                mutate(view)
                self.assertEqual(verify_checks.failed_start_state(view),
                                 (1, {"verdict": "not_met", "cards": 1, "problems": [problem]}))

    def test_a_card_and_sprint_without_a_string_sprint_id_are_not_met(self):
        def strip(view):
            del view["inbox"]["open"][0]["sprint_id"]
            del verify_checks._sprint_entries(view)[0]["sprint_id"]

        def as_list(view):
            view["inbox"]["open"][0]["sprint_id"] = ["a"]
            verify_checks._sprint_entries(view)[0]["sprint_id"] = ["a"]

        def card_only(view):
            view["inbox"]["open"][0]["sprint_id"] = 7

        for name, mutate in (("both absent", strip), ("list valued", as_list), ("card not a string", card_only)):
            with self.subTest(name):
                view = self.real_view()
                mutate(view)
                self.assertEqual(verify_checks.failed_start_state(view),
                                 (1, {"verdict": "not_met", "cards": 1, "problems": ["line"]}))

    def test_the_wire_names_match_the_console(self):
        self.assertEqual(verify_checks.FAILED_START_REASON, "failed_start")
        self.assertEqual(verify_checks.FAILED_START_NOW, console_sprints.NOW_FAILED_START_TEXT)
        self.assertEqual(verify_checks.FAILED_START_REASONS, console_manager.PLAIN_TEXTS)

    def test_an_unreachable_console_is_not_yet(self):
        unreachable = (75, {"verdict": "unreachable", "cards": 0})
        self.assertEqual(verify_checks.console_failed_start(self.closed_port()), unreachable)
        self.assertEqual(verify_checks.console_failed_start(
            self.stub({"/api/state": (503, b"{}")})), unreachable)
        self.assertEqual(verify_checks.console_failed_start(
            self.stub({"/api/state": (200, b"[]")})), unreachable)

    def test_the_command_and_its_wrapper_print_one_json_line(self):
        port = self.stub({"/api/state": (200, console_view.encode_view(self.real_view()))})
        expected = json.dumps({"verdict": "met", "cards": 1}, sort_keys=True) + "\n"
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = verify_checks.main(["console-failed-start", "--port", str(port)])
        self.assertEqual(code, 0)
        self.assertEqual(out.getvalue(), expected)
        result = run_from_root([str(ROOT / CHECKS / "console-failed-start"), "--port", str(port)])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, expected)
        for argv in (["console-failed-start"], ["console-failed-start", "--port", "0"]):
            with self.subTest(argv=argv):
                with contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as raised:
                        verify_checks.main(argv)
                self.assertEqual(raised.exception.code, 2)

    def test_wrapper_is_committed_executable(self):
        self.assertEqual(committed_mode(f"{CHECKS}/console-failed-start"), "100755")


class ConsoleManagerMergeTest(unittest.TestCase):
    """`console-manager-merge` (issue 1377): a manager merged its own pull request after activation."""

    SPRINT = "a" * 16
    OTHER_SPRINT = "b" * 16
    SESSION = "manager-session"
    REPO = "octo/widgets"
    HEAD = "b" * 40
    T0 = datetime(2026, 11, 1, 0, 0, 0, tzinfo=timezone.utc)

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.root = self.dir / "repo"
        self.root.mkdir()
        self.shas = {}
        self.git("init", "-q")
        for name in ("P", "S", "C"):
            self.git("-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false",
                     "commit", "-q", "--allow-empty", "-m", name)
            self.shas[name] = self.git("rev-parse", "HEAD").strip()
        self.at = self.T0
        self.log_path = self.dir / "events.sqlite3"
        self.log = event_log.EventLog(self.log_path, clock=lambda: self.at.isoformat(timespec="microseconds"))
        self.addCleanup(self.log._connection.close)
        self.pulls = {}
        self.calls = []
        self.reported(self.SPRINT, 1377)

    def reported(self, sprint, *issues):
        self.append("sprint.reported", {"sprint_id": sprint, "goal": "g", "report": {
            "issues": [{"issue": number, "stage": "building"} for number in issues]}}, timedelta(0))

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.root), *args], capture_output=True, text=True,
                              check=True).stdout

    def append(self, kind, payload, when):
        self.at = self.T0 + when
        self.log.append([(kind, None, payload)])

    def activated(self, commit="C", ok=True, when=timedelta(0)):
        self.append("activation.finished", {"root": "/r", "commit": self.shas[commit], "ok": ok,
                                            "reason": None, "next_step": None}, when)

    def seen(self, session=None, sprint=None, when=timedelta(0)):
        self.append("session.seen", {"session_id": session or self.SESSION, "cwd": "/r", "repo": None,
                                     "state": "idle", "name": f"p00 sprint {sprint or self.SPRINT}"}, when)

    def permit(self, kind, when, repo=None, session=None, pr=7, head=None, sprint=None, call="call-1"):
        payload = {"sprint_id": sprint or self.SPRINT, "session_id": session or self.SESSION,
                   "tool_use_id": call, "repo": repo or self.REPO, "verb": "merge",
                   "target": {"pr": pr, "head": head or self.HEAD}}
        if kind == "permit.judged":
            payload.update(decision="allow", reason="allowed")
        self.append(kind, payload, when)

    def pull(self, merged_at, head=None, pr=7, merged=True):
        self.pulls[pr] = {"merged": merged, "head": {"sha": head or self.HEAD},
                          "merged_at": None if merged_at is None else
                          (self.T0 + merged_at).strftime("%Y-%m-%dT%H:%M:%SZ")}

    def landed_merge(self, day=1, **extra):
        """A judged allow at 10:00, its landing at 10:01 and the pull merged at 10:00:30 of the day."""
        start = timedelta(days=day, hours=10)
        self.permit("permit.judged", start, **extra)
        self.permit("permit.landed", start + timedelta(minutes=1), **extra)
        self.pull(start + timedelta(seconds=30), head=extra.get("head"))

    def run_check(self, now, *argv):
        def api_get(path, allow=()):
            self.calls.append(path)
            prefix = f"repos/{self.REPO}/pulls/"
            self.assertTrue(path.startswith(prefix), path)
            return self.pulls[int(path[len(prefix):])]

        out = io.StringIO()
        args = ["console-manager-merge", "--repo", self.REPO, "--since", self.shas["S"],
                "--log", str(self.log_path), "--repo-root", str(self.root), *argv]
        with mock.patch.object(verify_checks.forge_api, "api_get", api_get), \
                mock.patch.object(verify_checks, "_utcnow", lambda: self.T0 + now), \
                contextlib.redirect_stdout(out):
            code = verify_checks.main(args)
        return code, json.loads(out.getvalue())

    def qualifying(self, day=1):
        self.activated()
        self.seen()
        self.landed_merge(day)

    def test_a_landed_manager_merge_after_activation_is_met(self):
        self.qualifying()
        code, report = self.run_check(timedelta(days=2))
        self.assertEqual(code, 0)
        self.assertEqual(report["pr"], 7)
        self.assertEqual((report["met"], report["verdict"], report["head"]), (True, "met", self.HEAD))
        self.assertEqual(report["activated_at"], self.T0.isoformat())
        self.assertEqual(report["judged_at"], (self.T0 + timedelta(days=1, hours=10)).isoformat())
        self.assertEqual(report["merged_at"], (self.T0 + timedelta(days=1, hours=10, seconds=30)).isoformat())
        self.assertEqual(set(report), {"met", "verdict", "pr", "head", "judged_at", "landed_at",
                                       "merged_at", "activated_at"})

    def test_a_delayed_verifier_still_counts_a_merge_inside_the_window(self):
        self.qualifying()
        self.assertEqual(self.run_check(timedelta(days=10))[0], 0)

    def test_a_merge_after_the_window_is_not_met(self):
        self.qualifying(day=8)
        code, report = self.run_check(timedelta(days=10))
        self.assertEqual((code, report["verdict"], report["pr"]), (1, "not_met", None))
        self.assertEqual(self.run_check(timedelta(days=8))[0], 1)

    def test_a_merge_before_activation_is_not_counted(self):
        self.activated()
        self.seen()
        self.landed_merge(day=-1)
        self.assertEqual(self.run_check(timedelta(days=2))[0], 75)

    def test_no_qualifying_activation_is_not_yet(self):
        self.seen()
        self.landed_merge()
        self.activated(ok=False)
        self.activated(commit="P", when=timedelta(hours=1))
        self.assertEqual(self.run_check(timedelta(days=2))[0], 75)

    def test_a_refused_manager_call_then_a_lead_merge_stays_pending(self):
        self.activated()
        self.seen()
        self.permit("permit.judged", timedelta(days=1, hours=10))
        self.pull(timedelta(days=1, hours=12))
        self.assertEqual(self.run_check(timedelta(days=2))[0], 75)

    def test_a_merge_outside_the_calls_span_is_not_counted(self):
        for merged_at in (timedelta(days=1, hours=9), timedelta(days=1, hours=11)):
            with self.subTest(merged_at=merged_at):
                self.setUp()
                self.activated()
                self.seen()
                self.permit("permit.judged", timedelta(days=1, hours=10))
                self.permit("permit.landed", timedelta(days=1, hours=10, minutes=1))
                self.pull(merged_at)
                self.assertEqual(self.run_check(timedelta(days=2))[0], 75)

    def test_a_sprint_that_reported_no_issue_before_the_judgement_is_not_counted(self):
        self.activated()
        self.seen(sprint=self.OTHER_SPRINT)
        self.landed_merge(sprint=self.OTHER_SPRINT)
        self.append("sprint.reported", {"sprint_id": self.OTHER_SPRINT, "goal": "g", "report": {
            "issues": []}}, timedelta(days=0))
        self.append("sprint.reported", {"sprint_id": self.OTHER_SPRINT, "goal": "g", "report": {
            "issues": [{"issue": 5, "stage": "building"}]}}, timedelta(days=3))
        self.assertEqual(self.run_check(timedelta(days=2))[0], 75)
        self.assertEqual(self.run_check(timedelta(days=10))[0], 1)

    def test_any_sprints_manager_merge_counts_whichever_issue_it_delivered(self):
        """Issue 1377 itself may have been delivered outside a sprint or as a sprint's last issue."""
        self.activated()
        self.seen(sprint=self.OTHER_SPRINT)
        self.reported(self.OTHER_SPRINT, 999)
        self.landed_merge(sprint=self.OTHER_SPRINT)
        code, report = self.run_check(timedelta(days=2))
        self.assertEqual((code, report["verdict"], report["pr"]), (0, "met", 7))

    def test_a_landing_of_another_tool_call_does_not_complete_the_allowed_one(self):
        self.activated()
        self.seen()
        start = timedelta(days=1, hours=10)
        self.permit("permit.judged", start, call="call-1")
        self.permit("permit.landed", start + timedelta(minutes=1), call="call-2")
        self.pull(start + timedelta(seconds=30))
        self.assertEqual(self.run_check(timedelta(days=2))[0], 75)

    def test_rows_that_name_no_tool_call_are_not_counted(self):
        self.activated()
        self.seen()
        start = timedelta(days=1, hours=10)
        for call in ("", None):
            self.permit("permit.judged", start, call=call)
            self.permit("permit.landed", start + timedelta(minutes=1), call=call)
        self.pull(start + timedelta(seconds=30))
        self.assertEqual(self.run_check(timedelta(days=2))[0], 75)

    def test_a_git_that_cannot_answer_the_ancestry_is_an_error_not_pending(self):
        self.append("activation.finished", {"root": "/r", "commit": "d" * 40, "ok": True,
                                            "reason": None, "next_step": None}, timedelta(0))
        self.activated(when=timedelta(hours=1))
        stderr = io.StringIO()
        with mock.patch.object(verify_checks.forge_api, "api_get") as api_get, \
                contextlib.redirect_stderr(stderr), contextlib.redirect_stdout(io.StringIO()):
            code = verify_checks.main(["console-manager-merge", "--repo", self.REPO, "--since",
                                       self.shas["S"], "--log", str(self.log_path),
                                       "--repo-root", str(self.root)])
        self.assertEqual(code, 2)
        self.assertIn("git", stderr.getvalue())
        api_get.assert_not_called()

    def test_a_permit_of_another_repository_or_session_is_not_counted(self):
        self.activated()
        self.seen()
        self.landed_merge(repo="x/y")
        self.landed_merge(session="other-session")
        self.assertEqual(self.run_check(timedelta(days=2))[0], 75)

    def test_a_merge_at_another_head_or_unmerged_is_skipped(self):
        self.qualifying()
        self.pull(timedelta(days=1, hours=10, seconds=30), head="c" * 40)
        self.assertEqual(self.run_check(timedelta(days=2))[0], 75)
        self.pull(None, merged=False)
        self.assertEqual(self.run_check(timedelta(days=2))[0], 75)

    def test_bad_arguments_are_a_usage_error(self):
        for argv in (["--repo", "bad", "--since", self.shas["S"]],
                     ["--repo", self.REPO, "--since", "abc"],
                     ["--repo", self.REPO]):
            with self.subTest(argv=argv):
                with mock.patch.object(verify_checks.forge_api, "api_get") as api_get, \
                        contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as raised:
                        verify_checks.main(["console-manager-merge", *argv, "--log", str(self.log_path)])
                self.assertEqual(raised.exception.code, 2)
                api_get.assert_not_called()

    def test_the_script_is_committed_executable_and_runs_the_check(self):
        script = f"{CHECKS}/console-manager-merge"
        self.assertEqual(committed_mode(script), "100755")
        result = run_from_root([str(ROOT / script), "--repo", "bad", "--since", "x"])
        self.assertEqual(result.returncode, 2, result.stderr)


class ConsoleNoCardTest(unittest.TestCase):
    """`console-no-card` (issue 1327): the console lists no inbox card with any of the given keys."""

    K = "octo/widgets#1326/ac1"
    UNREADABLE = (75, {"verdict": "unreachable", "listed": 0})

    def stub(self, routes):
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                status, body = routes.get(self.path.split("?", 1)[0], (404, b""))
                self.send_response(status)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server.server_address[1]

    def closed_port(self):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            return sock.getsockname()[1]

    def test_no_listed_key_is_met(self):
        view = {"inbox": {"open": [{"key": "octo/widgets#7/ac1"}], "answered": []}}
        self.assertEqual(verify_checks.no_card_state(view, [self.K]), (0, {"verdict": "absent", "listed": 0}))

    def test_a_listed_key_is_not_yet(self):
        other = "octo/widgets#9/ac2"
        listed = (75, {"verdict": "listed", "listed": 1})
        self.assertEqual(verify_checks.no_card_state(
            {"inbox": {"open": [{"key": self.K}], "answered": []}}, [self.K]), listed)
        self.assertEqual(verify_checks.no_card_state(
            {"inbox": {"open": [], "answered": [{"key": self.K}]}}, [self.K]), listed)
        self.assertEqual(verify_checks.no_card_state(
            {"inbox": {"open": [{"key": self.K}], "answered": [{"key": other}]}}, [self.K, other]),
            (75, {"verdict": "listed", "listed": 2}))
        self.assertEqual(verify_checks.no_card_state(
            {"inbox": {"open": [{"key": self.K}], "answered": [{"key": self.K}]}}, [self.K]), listed)

    def test_an_unreadable_inbox_is_never_met(self):
        for view in ([], {}, {"inbox": []}, {"inbox": {"open": {}, "answered": []}},
                     {"inbox": {"open": [], "answered": None}}):
            with self.subTest(view=view):
                self.assertEqual(verify_checks.no_card_state(view, [self.K]), self.UNREADABLE)
        for entry in ("x", {}, {"key": []}):
            for where in ("open", "answered"):
                with self.subTest(entry=entry, where=where):
                    lists = {"open": [], "answered": [], where: [entry]}
                    self.assertEqual(verify_checks.no_card_state({"inbox": lists}, [self.K]), self.UNREADABLE)

    def test_a_real_view_lists_the_review_card(self):
        node = {"__typename": "Issue", "number": 1326, "issueDependenciesSummary": {"blocking": 0},
                "blocking": {"totalCount": 0, "nodes": []}, "comments": {"totalCount": 0, "nodes": []},
                "authorAssociation": "OWNER",
                "body": "## Acceptance criteria\n\n- [ ] [human] It reads plainly\n",
                "labels": {"nodes": [{"name": "needs-verification"}]}}
        item = inbox.items_from_node("p00", "octo/widgets", node)[0]
        records = {("p00", item["key"]): console_view.InboxRecord(item, "t1", "t1")}
        view = json.loads(console_view.encode_view(console_view.derive_view(
            [ProjectState("p00", "/srv/p00", 1, "t1")], records)))
        self.assertEqual(verify_checks.no_card_state(view, [item["key"]]),
                         (75, {"verdict": "listed", "listed": 1}))
        self.assertEqual(verify_checks.no_card_state(view, ["octo/widgets#1/ac9"]),
                         (0, {"verdict": "absent", "listed": 0}))

    def test_an_unreachable_console_is_not_yet(self):
        self.assertEqual(verify_checks.console_no_card(self.closed_port(), [self.K]), self.UNREADABLE)
        self.assertEqual(verify_checks.console_no_card(
            self.stub({"/api/state": (503, b'{"inbox": {"open": [], "answered": []}}')}), [self.K]),
            self.UNREADABLE)
        self.assertEqual(verify_checks.console_no_card(
            self.stub({"/api/state": (200, b"not json")}), [self.K]), self.UNREADABLE)

    def test_a_malformed_state_is_never_absent(self):
        listed = '{"key": "%s"}' % self.K
        bodies = {
            "duplicate open": '{"inbox": {"open": [%s], "open": [], "answered": []}}' % listed,
            "duplicate inbox": '{"inbox": {"open": [%s], "answered": []}, "inbox": {"open": [], "answered": []}}' % listed,
            "nan": '{"inbox": {"open": [], "answered": []}, "x": NaN}',
            "deep": "[" * 100000 + "]" * 100000,
        }
        for name, body in bodies.items():
            with self.subTest(name=name):
                self.assertEqual(verify_checks.console_no_card(
                    self.stub({"/api/state": (200, body.encode())}), [self.K]), self.UNREADABLE)

    def test_the_command_and_its_wrapper_print_one_json_line(self):
        port = self.stub({"/api/state": (200, b'{"inbox": {"open": [], "answered": []}}')})
        expected = json.dumps({"listed": 0, "verdict": "absent"}, sort_keys=True) + "\n"
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = verify_checks.main(["console-no-card", "--port", str(port), "--key", self.K])
        self.assertEqual(code, 0)
        self.assertEqual(out.getvalue(), expected)
        result = run_from_root([str(ROOT / CHECKS / "console-no-card"), "--port", str(port), "--key", self.K])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, expected)
        answered = self.stub({"/api/state": (
            200, json.dumps({"inbox": {"open": [], "answered": [{"key": self.K}]}}).encode())})
        listed = json.dumps({"listed": 1, "verdict": "listed"}, sort_keys=True) + "\n"
        result = run_from_root([str(ROOT / CHECKS / "console-no-card"), "--port", str(answered), "--key", self.K])
        self.assertEqual(result.returncode, 75, result.stderr)
        self.assertEqual(result.stdout, listed)
        for argv in (["console-no-card", "--port", str(port)], ["console-no-card", "--key", self.K],
                     ["console-no-card", "--port", "0", "--key", self.K]):
            with self.subTest(argv=argv):
                with contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as raised:
                        verify_checks.main(argv)
                self.assertEqual(raised.exception.code, 2)

    def test_wrapper_is_committed_executable(self):
        self.assertEqual(committed_mode(f"{CHECKS}/console-no-card"), "100755")


class ConsoleNoticeListsTest(unittest.TestCase):
    """`console-notice-lists` (issue 1291): the owner's notices name every issue of a project."""

    def serve(self, status, body):
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(status)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        server = loopback_server(Handler)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server.server_address[1]

    def serve_view(self, entries):
        return self.serve(200, json.dumps({"entries": entries}).encode())

    @staticmethod
    def project(project_id, *notices):
        return {"type": "project", "project_id": project_id, "notices": list(notices)}

    @staticmethod
    def notice(number, text, owner=True):
        return {"id": number, "owner": owner, "kind": "heads-up", "text": text}

    def test_one_owner_notice_naming_every_issue_covers_a_project(self):
        port = self.serve_view([
            self.project("jarbird", self.notice(4, "anis-desktop is gone: #611 #711 #712")),
            {"type": "quiet_group", "label": "1 quiet projects", "count": 1,
             "projects": [self.project("nodocom", self.notice(9, "anis-desktop is gone: #2600 #2990"))]}])
        self.assertEqual(
            verify_checks.console_notice_lists(port, {"jarbird": [611, 711, 712], "nodocom": [2600, 2990]}),
            (0, {"verdict": "covered", "projects": {"jarbird": {"notice": 4}, "nodocom": {"notice": 9}}}))

    def test_a_split_list_a_manager_notice_or_a_prefix_does_not_cover(self):
        cases = {
            "split": [self.notice(1, "gone: #611"), self.notice(2, "gone: #711 #712")],
            "manager": [self.notice(3, "gone: #611 #711 #712", owner=False)],
            "prefix": [self.notice(5, "gone: #6110 #711 #712")],
        }
        for name, notices in cases.items():
            with self.subTest(name=name):
                port = self.serve_view([self.project("jarbird", *notices)])
                code, report = verify_checks.console_notice_lists(port, {"jarbird": [611, 711, 712]})
                self.assertEqual(code, 75)
                self.assertEqual(report["verdict"], "missing")
                self.assertIsNone(report["projects"]["jarbird"]["notice"])

    def test_an_entry_of_another_type_is_skipped_and_an_absent_project_is_missing(self):
        port = self.serve_view([
            {"type": "other", "project_id": "jarbird", "notices": [self.notice(1, "#611")]}])
        self.assertEqual(verify_checks.console_notice_lists(port, {"jarbird": [611]}),
                         (75, {"verdict": "missing", "projects": {"jarbird": {"notice": None}}}))

    def test_an_unreachable_console_is_not_yet(self):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            closed = sock.getsockname()[1]
        unreachable = (75, {"verdict": "unreachable"})
        wanted = {"jarbird": [611]}
        self.assertEqual(verify_checks.console_notice_lists(closed, wanted), unreachable)
        self.assertEqual(verify_checks.console_notice_lists(self.serve(500, b"{}"), wanted), unreachable)
        self.assertEqual(verify_checks.console_notice_lists(self.serve(200, b"[]"), wanted), unreachable)

    def test_the_command_prints_one_json_line(self):
        port = self.serve_view([self.project("jarbird", self.notice(4, "#611 #711"))])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = verify_checks.main(["console-notice-lists", "--port", str(port),
                                       "--notice", "jarbird=611,711"])
        self.assertEqual(code, 0)
        self.assertEqual(out.getvalue(), json.dumps(
            {"projects": {"jarbird": {"notice": 4}}, "verdict": "covered"}, sort_keys=True) + "\n")

    def test_a_bad_notice_argument_is_a_usage_error(self):
        bad = (["jarbird"], ["jarbird=a"], ["jarbird=611,"], ["jarbird=0"],
               ["jarbird=1", "jarbird=1"])
        for values in bad:
            with self.subTest(values=values):
                argv = ["console-notice-lists", "--port", "1"]
                for value in values:
                    argv += ["--notice", value]
                with contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as raised:
                        verify_checks.main(argv)
                self.assertEqual(raised.exception.code, 2)

    def test_the_wrapper_is_committed_executable_and_exits_2_without_arguments(self):
        self.assertEqual(committed_mode(f"{CHECKS}/console-notice-lists"), "100755")
        self.assertEqual(run_from_root([str(ROOT / CHECKS / "console-notice-lists")]).returncode, 2)


class FirstScreenStateTest(unittest.TestCase):
    """`first_screen_state` (issue 1031): a long-goal question is named by title with a short ask."""

    GOAL = "Make the importer resumable after a crash. " + "g" * 1357
    SID = "a" * 16
    TITLE = "Importer resumes after a crash"

    def view(self):
        return {
            "entries": [{"type": "project", "project_id": "owner/importer",
                         "sprints": [{"sprint_id": self.SID, "title": self.TITLE, "goal": self.GOAL}],
                         "finished_sprints": {"sprints": []}}],
            "inbox": {"open": [{"reason": "question", "sprint_id": self.SID, "title": self.TITLE,
                                "headline": "Which store keeps the checkpoints?", "context": None,
                                "questions": [{"question": "Which store keeps the checkpoints?",
                                               "options": ["sqlite", "files"]}]}]},
            "digest": {"moments": []},
        }

    def item(self, v):
        return v["inbox"]["open"][0]

    def members(self, report):
        return [problem["member"] for problem in report["problems"]]

    def test_a_long_goal_question_named_by_title_is_met(self):
        self.assertEqual(verify_checks.first_screen_state(self.view()), (0, {"verdict": "met", "questions": 1}))

    def test_no_open_question_of_a_long_goal_is_not_yet(self):
        none_open = self.view()
        none_open["inbox"]["open"] = []
        short = self.view()
        short["entries"][0]["sprints"][0]["goal"] = self.GOAL[:900]
        for name, v in (("none open", none_open), ("short goal", short), ("not a dict", [])):
            with self.subTest(name):
                code, report = verify_checks.first_screen_state(v)
                self.assertEqual(code, 75)
                self.assertEqual(report["verdict"], "not_yet")

    def test_a_question_carrying_the_goal_is_not_met(self):
        v = self.view()
        self.item(v)["goal"] = self.GOAL
        code, report = verify_checks.first_screen_state(v)
        self.assertEqual(code, 1)
        self.assertIn({"sprint_id": self.SID, "member": "goal"}, report["problems"])

    def test_an_empty_or_missing_ask_or_options_is_not_met(self):
        def headline(value):
            return lambda v: self.item(v).__setitem__("headline", value)

        def question(key, value):
            return lambda v: self.item(v)["questions"][0].__setitem__(key, value)

        cases = (
            ("empty headline", headline(""), "headline"),
            ("blank headline", headline("   "), "headline"),
            ("no questions", lambda v: self.item(v).pop("questions"), "questions"),
            ("empty questions", lambda v: self.item(v).__setitem__("questions", []), "questions"),
            ("empty question", question("question", ""), "questions"),
            ("no options", question("options", []), "options"),
            ("one option", question("options", ["sqlite"]), "options"),
            ("empty option", question("options", ["sqlite", ""]), "options"),
        )
        for name, change, member in cases:
            with self.subTest(name):
                v = self.view()
                change(v)
                code, report = verify_checks.first_screen_state(v)
                self.assertEqual(code, 1)
                self.assertIn({"sprint_id": self.SID, "member": member}, report["problems"])

    def test_an_ask_or_option_over_its_limit_is_not_met(self):
        def headline(v):
            self.item(v)["headline"] = "h" * 141

        def option(v):
            self.item(v)["questions"][0]["options"] = ["sqlite", "o" * 81]

        def title(v):
            self.item(v)["title"] = "t" * 61

        def context(v):
            self.item(v)["context"] = "c" * 401

        for change, member in ((headline, "headline"), (option, "options"), (title, "title"),
                               (context, "context")):
            with self.subTest(member):
                v = self.view()
                change(v)
                code, report = verify_checks.first_screen_state(v)
                self.assertEqual(code, 1)
                self.assertIn({"sprint_id": self.SID, "member": member}, report["problems"])

    def test_goal_text_outside_the_sprint_entrys_goal_is_not_met(self):
        def moment(v):
            v["digest"]["moments"].append({"text": "A brief arrived: " + self.GOAL})

        def status(v):
            v["entries"][0]["sprints"][0]["status"] = self.GOAL[150:400]

        def unstopped(v):
            v["entries"][0]["unstopped"] = [{"title": self.TITLE, "note": self.GOAL[190:310]}]

        def unstopped_goal(v):
            v["entries"][0]["unstopped"] = [{"title": self.TITLE, "goal": self.GOAL}]

        for change, path in ((moment, "digest.moments[0].text"),
                             (status, "entries[0].sprints[0].status"),
                             (unstopped, "entries[0].unstopped[0].note"),
                             (unstopped_goal, "entries[0].unstopped[0].goal")):
            with self.subTest(path):
                v = self.view()
                change(v)
                code, report = verify_checks.first_screen_state(v)
                self.assertEqual(code, 1)
                self.assertIn({"sprint_id": self.SID, "member": "goal_text", "path": path},
                              report["problems"])

    def test_goal_text_with_escaped_characters_is_still_found(self):
        g2 = "Make the importer resumable after a crash. " + ("é \"quoted\"\nline " * 100)[:1357]
        v = self.view()
        v["entries"][0]["sprints"][0]["goal"] = g2
        v["digest"]["moments"].append({"text": "Seen: " + g2})
        code, report = verify_checks.first_screen_state(v)
        self.assertEqual(code, 1)
        self.assertIn("goal_text", self.members(report))

    def test_the_sprint_entrys_own_goal_is_exempt_wherever_the_entry_sits(self):
        finished = self.view()
        project = finished["entries"][0]
        project["finished_sprints"]["sprints"] = project["sprints"]
        project["sprints"] = []
        quiet = self.view()
        quiet["entries"] = [{"type": "quiet_group", "projects": quiet["entries"]}]
        for name, v in (("finished", finished), ("quiet group", quiet)):
            with self.subTest(name):
                self.assertEqual(verify_checks.first_screen_state(v), (0, {"verdict": "met", "questions": 1}))


FAKE_BROWSER = r'''#!%(python)s
import base64, json, os, sys
from pathlib import Path

here = Path(__file__).resolve().parent
with open(here / "argv.jsonl", "a") as log:
    log.write(json.dumps(sys.argv) + "\n")
if %(die)r:
    sys.exit(1)
import time
measures = json.loads(%(measures)r)
buffer = b""
evaluations = 0
while True:
    while b"\0" not in buffer:
        chunk = os.read(3, 65536)
        if not chunk:
            sys.exit(0)
        buffer += chunk
    raw, buffer = buffer.split(b"\0", 1)
    message = json.loads(raw)
    if %(silent)r:
        time.sleep(600)
    method, session = message["method"], message.get("sessionId")
    with open(here / "calls.jsonl", "a") as log:
        log.write(json.dumps([method, session]) + "\n")
    result = {}
    if method == "Target.createTarget":
        result = {"targetId": "T"}
    elif method == "Target.attachToTarget":
        result = {"sessionId": "S"}
    elif method == "Runtime.evaluate":
        result = {"result": {"type": "object", "value": measures[min(evaluations, len(measures) - 1)]}}
        evaluations += 1
    elif method == "Page.captureScreenshot":
        result = {"data": base64.b64encode(b"\x89PNG fake").decode()}
    reply = {"id": message["id"], "result": result}
    if session:
        reply["sessionId"] = session
    out = [reply]
    if method == "Page.navigate":
        out.append({"method": "Page.loadEventFired", "params": {}, "sessionId": "S"})
    for member in out:
        os.write(4, json.dumps(member).encode() + b"\0")
    if method == "Browser.close":
        sys.exit(0)
'''

M_OK = {"viewport": {"width": 1440, "height": 900},
        "lead": {"title": "Importer resumes after a crash",
                 "ask": {"text": "Which store keeps the checkpoints?", "top": 120, "bottom": 168, "clipped": False},
                 "options": [{"text": "sqlite", "top": 300, "bottom": 340},
                             {"text": "files", "top": 350, "bottom": 390}]},
        "text": "Importer resumes after a crash\nWhich store keeps the checkpoints?"}
M_EMPTY = {**M_OK, "lead": None}


def fake_browser(tmp, measures, *, die=False, silent=False):
    path = Path(tmp) / "browser"
    path.write_text(FAKE_BROWSER % {"python": sys.executable, "die": die, "measures": json.dumps(measures), "silent": silent})
    path.chmod(0o755)
    return path


def with_lead(measure, **changes):
    lead = json.loads(json.dumps(measure["lead"]))
    ask = {**lead["ask"], **changes.get("ask", {})}
    options = changes.get("options", lead["options"])
    return {**measure, "lead": {"title": changes.get("title", lead["title"]), "ask": ask, "options": options},
            **({"text": changes["text"]} if "text" in changes else {})}


class ChromiumDriverTest(unittest.TestCase):
    """`chromium_first_screen` (issue 1031): DevTools over the browser's pipe, no input sent."""

    def setUp(self):
        handle = tempfile.TemporaryDirectory()
        self.addCleanup(handle.cleanup)
        self.tmp = Path(handle.name)

    def jsonl(self, name):
        return [json.loads(line) for line in (self.tmp / name).read_text().splitlines()]

    def test_the_driver_speaks_the_pipe_and_waits_for_the_lead(self):
        fake = fake_browser(self.tmp, [M_EMPTY, M_OK])
        measure = verify_checks.chromium_first_screen(
            "http://127.0.0.1:1/", width=1440, height=900, screenshot=self.tmp / "s.png",
            browser=[str(fake)], timeout=10)
        self.assertEqual(measure, M_OK)
        self.assertEqual((self.tmp / "s.png").read_bytes(), b"\x89PNG fake")
        argv = self.jsonl("argv.jsonl")[0]
        for flag in ("--headless=new", "--remote-debugging-pipe", "--window-size=1440,900"):
            self.assertIn(flag, argv)
        profile = [a for a in argv if a.startswith("--user-data-dir=")]
        self.assertEqual(len(profile), 1)
        self.assertFalse(Path(profile[0].split("=", 1)[1]).exists())
        calls = self.jsonl("calls.jsonl")
        methods = [method for method, _ in calls]
        self.assertEqual(methods[:2], ["Target.createTarget", "Target.attachToTarget"])
        self.assertEqual(calls[2:4], [["Emulation.setDeviceMetricsOverride", "S"], ["Page.navigate", "S"]])
        self.assertEqual(methods[-1], "Browser.close")
        self.assertEqual(methods.count("Runtime.evaluate"), 2)
        self.assertFalse([m for m in methods if m.startswith("Input.")])

    def test_the_browser_is_launched_without_a_shell_that_only_takes_single_digit_descriptors(self):
        # dash (the CI runner's /bin/sh) refuses `3<&10`: "Bad fd number". The pipes must reach
        # descriptors 3 and 4 without a shell redirection naming a descriptor of 10 or more.
        fake = fake_browser(self.tmp, [M_OK])
        launched = []
        real = subprocess.Popen

        def spy(argv, *args, **kwargs):
            launched.append(argv)
            return real(argv, *args, **kwargs)

        with mock.patch.object(verify_checks.subprocess, "Popen", spy):
            verify_checks.chromium_first_screen(
                "http://127.0.0.1:1/", width=1440, height=900, screenshot=self.tmp / "s.png",
                browser=[str(fake)], timeout=10)
        self.assertEqual(len(launched), 1)
        self.assertNotIn(launched[0][0], ("/bin/sh", "sh"))
        self.assertFalse([part for part in launched[0] if "<&" in part or ">&" in part])
        self.assertEqual(self.jsonl("calls.jsonl")[0][0], "Target.createTarget")

    def test_a_browser_that_dies_raises(self):
        fake = fake_browser(self.tmp, [M_OK], die=True)
        started = time.monotonic()
        with self.assertRaises(verify_checks.BrowserError):
            verify_checks.chromium_first_screen(
                "http://127.0.0.1:1/", width=1440, height=900, screenshot=self.tmp / "s.png",
                browser=[str(fake)], timeout=10)
        self.assertLess(time.monotonic() - started, 10)

    def test_a_silent_browser_is_bounded_by_the_timeout_not_a_fixed_call_limit(self):
        fake = fake_browser(self.tmp, [M_OK], silent=True)
        started = time.monotonic()
        with self.assertRaises(verify_checks.BrowserError):
            verify_checks.chromium_first_screen(
                "http://127.0.0.1:1/", width=1440, height=900, screenshot=self.tmp / "s.png",
                browser=[str(fake)], timeout=2)
        self.assertLess(time.monotonic() - started, 8)

    def test_the_browser_comes_from_path_else_nix_shell(self):
        with mock.patch("shutil.which", return_value=None):
            self.assertEqual(verify_checks.browser_command(), ["nix", "shell", "n#chromium", "--command", "chromium"])
        with mock.patch("shutil.which", return_value="/run/current-system/sw/bin/chromium"):
            self.assertEqual(verify_checks.browser_command(), ["/run/current-system/sw/bin/chromium"])


class ConsoleFirstScreenTest(unittest.TestCase):
    """`console-first-screen` (issue 1031): the live first screen at 1440x900 against the fold."""

    GOAL = FirstScreenStateTest.GOAL
    view = FirstScreenStateTest.view
    SID = FirstScreenStateTest.SID
    TITLE = FirstScreenStateTest.TITLE

    def setUp(self):
        handle = tempfile.TemporaryDirectory()
        self.addCleanup(handle.cleanup)
        self.tmp = Path(handle.name)

    def serve(self, view):
        body = json.dumps(view).encode()

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200 if self.path == "/api/state" else 404)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server.server_address[1]

    def check(self, measures, view=None, *, timeout=10, die=False):
        port = self.serve(view if view is not None else self.view())
        fake = fake_browser(self.tmp, measures, die=die)
        return verify_checks.console_first_screen(port, browser=[str(fake)], timeout=timeout, out_dir=self.tmp)

    def test_a_whole_ask_and_options_above_the_fold_is_met(self):
        code, report = self.check([M_OK])
        self.assertEqual(code, 0, report)
        self.assertEqual(report["verdict"], "met")
        self.assertEqual(report["screenshot"], str(self.tmp / "first-screen-1440.png"))
        self.assertTrue((self.tmp / "first-screen-1440.png").exists())
        self.assertEqual(report["viewport"], {"width": 1440, "height": 900})

    def test_an_ask_or_option_below_the_fold_is_not_met(self):
        second_low = [{"text": "sqlite", "top": 300, "bottom": 340}, {"text": "files", "top": 350, "bottom": 920}]
        one_option = [{"text": "sqlite", "top": 300, "bottom": 340}]
        cases = (("ask below", with_lead(M_OK, ask={"bottom": 950}), "fold_ask"),
                 ("ask clipped", with_lead(M_OK, ask={"clipped": True}), "fold_ask"),
                 ("option below", with_lead(M_OK, options=second_low), "fold_options"),
                 ("one option", with_lead(M_OK, options=one_option), "fold_options"))
        for name, measure, member in cases:
            with self.subTest(name):
                code, report = self.check([measure])
                self.assertEqual(code, 1, report)
                self.assertEqual(report["verdict"], "not_met")
                self.assertIn({"member": member}, report["problems"])

    def test_goal_text_on_the_rendered_page_is_not_met(self):
        code, report = self.check([{**M_OK, "text": "Seen: " + self.GOAL}])
        self.assertEqual(code, 1)
        self.assertIn({"member": "visible_goal"}, report["problems"])

    def test_a_lead_without_or_with_another_sprint_title_is_not_met(self):
        for name, title in (("no title", None), ("another title", "Exporter streams rows")):
            with self.subTest(name):
                code, report = self.check([with_lead(M_OK, title=title)])
                self.assertEqual(code, 1, report)
                self.assertIn({"member": "lead_title"}, report["problems"])

    def test_the_lead_is_matched_to_the_candidate_with_its_own_title(self):
        v = self.view()
        twin = json.loads(json.dumps(v["inbox"]["open"][0]))
        twin.update(sprint_id="b" * 16, title="Exporter streams rows")
        v["entries"][0]["sprints"].append({"sprint_id": "b" * 16, "title": "Exporter streams rows", "goal": self.GOAL})
        v["inbox"]["open"].insert(0, twin)
        code, report = self.check([M_OK], v)
        self.assertEqual(code, 0, report)

    def test_a_rendered_goal_with_collapsed_whitespace_is_not_met(self):
        goal = self.GOAL[:210] + "\n\n  " + "word  \n  and\tmore " * 6 + self.GOAL[260:]
        v = self.view()
        v["entries"][0]["sprints"][0]["goal"] = goal
        rendered = " ".join(goal.split())
        self.assertNotIn(goal[200:300], rendered)
        code, report = self.check([{**M_OK, "text": "Seen: " + rendered}], v)
        self.assertEqual(code, 1, report)
        self.assertIn({"member": "visible_goal"}, report["problems"])

    def test_a_page_led_by_another_item_is_not_yet(self):
        other = with_lead(M_OK, ask={"text": "Approve the brief?"})
        for name, measure, timeout in (("no lead", M_EMPTY, 2), ("another ask", other, 10)):
            with self.subTest(name):
                code, report = self.check([measure], timeout=timeout)
                self.assertEqual(code, 75, report)
                self.assertEqual(report["lead"], "other")

    def test_no_long_goal_question_never_starts_the_browser(self):
        v = self.view()
        v["inbox"]["open"] = []
        code, report = self.check([M_OK], v)
        self.assertEqual(code, 75, report)
        self.assertFalse((self.tmp / "argv.jsonl").exists())

    def test_a_failing_state_never_starts_the_browser(self):
        v = self.view()
        v["inbox"]["open"][0]["goal"] = self.GOAL
        code, report = self.check([M_OK], v)
        self.assertEqual(code, 1)
        self.assertEqual(report["verdict"], "not_met")
        self.assertFalse((self.tmp / "argv.jsonl").exists())

    def test_no_browser_is_reported(self):
        code, report = self.check([M_OK], die=True)
        self.assertEqual(code, 1)
        self.assertEqual(report["verdict"], "no_browser")

    def test_no_console_is_unreachable(self):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        code, report = verify_checks.console_first_screen(port, browser=["/nonexistent"], out_dir=self.tmp)
        self.assertEqual(code, 1)
        self.assertEqual(report["verdict"], "unreachable")

    def test_the_wrapper_is_committed_executable_and_reports_met(self):
        port = self.serve(self.view())
        fake = fake_browser(self.tmp, [M_OK])
        result = run_from_root([str(ROOT / CHECKS / "console-first-screen"), "--port", str(port),
                                "--browser", str(fake)])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["verdict"], "met")
        self.assertEqual(committed_mode(f"{CHECKS}/console-first-screen"), "100755")


# --- railway-project-read (issue 1124) ----------------------------------------------------

DEVENV = """#!{python}
import json, os, subprocess, sys, time
from pathlib import Path

state = Path(os.environ["RAILWAY_READ_FIXTURE"])
with open(state / "devenv.jsonl", "a", encoding="utf-8") as log:
    log.write(json.dumps({{"argv": sys.argv[1:], "cwd": os.getcwd()}}) + "\\n")
if sys.argv[1:3] != ["shell", "--"]:
    sys.exit(64)
if (state / "sleep").exists():
    time.sleep(30)
if (state / "fail").exists():
    sys.exit(3)
print("entering shell", flush=True)
env = dict(os.environ)
env["PATH"] = {bin!r} + ":" + env["PATH"]
done = subprocess.run(sys.argv[3:], env=env, stdout=subprocess.PIPE, text=True)
sys.stdout.write(done.stdout)
sys.exit(done.returncode)
"""
SITE = {"kind": "github_repository", "repository": railway_request()["parameters"]["target"]["repository"],
        "branch": "main"}


def railway_params(services=None):
    """The adapter parameters of a satisfied read, as the adapter's own suite builds them."""
    return railway_request(**({} if services is None else {"services": services}))["parameters"]


class RailwayReadWorld:
    """Registered projects whose dev shell supplies the only railway, read through fake seams."""

    def __init__(self, test_case):
        self.case = test_case
        tmp = tempfile.TemporaryDirectory()
        test_case.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name).resolve()
        self.me = pwd.getpwuid(os.getuid()).pw_name
        self.sys = self.tmp / "sys"
        self.sys.mkdir()
        # The host's own bin directories can hold a railway (the one this issue removes), so
        # the tools the dev shell needs are linked into `sys/` and only `sys/` is the system path.
        for program in ("git", "env"):
            found = shutil.which(program)
            if found is None:
                test_case.skipTest(f"no {program}")
            (self.sys / program).symlink_to(found)
        self.git = shutil.which("git")
        self.system_path = str(self.sys)
        self.world = railway_world.RailwayWorld(test_case)
        self.state = self.tmp / "devenv-state"
        self.state.mkdir()
        patch = mock.patch.dict(os.environ, {"RAILWAY_READ_FIXTURE": str(self.state)})
        patch.start()
        test_case.addCleanup(patch.stop)
        devenv = self.sys / "devenv"
        devenv.write_text(DEVENV.format(python=sys.executable, bin=str(self.world.bin)),
                          encoding="utf-8")
        devenv.chmod(0o755)
        self.world.status()
        self.world.deployments("api", deployment("d1", MERGE))
        self.home = self.tmp / "home"
        (self.home / ".agents/state/fleet").mkdir(parents=True)
        self.roots, self.contracts, self.configs, self.unreadable = [], {}, {}, set()
        self.source_calls, self.inspect_calls = [], []
        self.targets = [{"adapter": "railway-deploy", "operations": ["deploy"],
                         "profile": "fixture-main", "target": {**SITE, "handle": "fixture-site"}}]
        self.inspection = None

    def project(self, config, *, devenv=True):
        index = len(self.roots)
        root = self.tmp / f"checkout-{index}"
        root.mkdir()
        subprocess.run([self.git, "init", "-q", str(root)], check=True)
        (root / ".agents").mkdir()
        (root / ".agents/project.json").write_text("{}", encoding="utf-8")
        if devenv:
            (root / "devenv.nix").write_text("{}", encoding="utf-8")
        contract = self.tmp / f"contract-{index}"
        contract.mkdir()
        self.roots.append(root)
        self.contracts[str(root)] = contract
        self.configs[str(contract)] = config
        self.write_registry()
        return root

    def write_registry(self):
        projects = [{"project_id": f"fixture-project-{i}", "root": str(root)}
                    for i, root in enumerate(self.roots)]
        (self.home / ".agents/state/fleet/registry.json").write_text(
            json.dumps({"schema_version": 1, "projects": projects}), encoding="utf-8")

    @contextlib.contextmanager
    def source(self, entry):
        self.source_calls.append(entry["root"])
        if entry["root"] in self.unreadable:
            raise verify_exec.SourceError("contract_unreadable")
        yield verify_exec.Source({"release": {"targets": self.targets}},
                                 self.contracts[entry["root"]],
                                 railway_params()["candidate"]["commit"], "main")

    def inspect(self, contract_root, profile_id, env, deadline):
        self.inspect_calls.append((contract_root, profile_id))
        if self.inspection is not None:
            return self.inspection(contract_root)
        return {"bindings": {"adapters": {"rw": {
                    "adapter": "railway-deploy",
                    "config": {"deploy": self.configs[str(contract_root)]}}}},
                "graphs": {"activation": [{"id": "deploy", "adapter": "rw", "operation": "deploy",
                                           "target": "fixture-site"}]}}

    def read(self, **extra):
        environ = {**os.environ, "PYTHONPATH": os.path.relpath(ROOT / "python")}
        options = {"user": self.me, "home": str(self.home), "system_path": self.system_path,
                   "environ": environ, "source": self.source, "inspect_profile": self.inspect}
        return verify_checks.railway_project_read(**{**options, **extra})

    def devenv_calls(self):
        path = self.state / "devenv.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text("utf-8").splitlines()]


class RailwayProjectReadTest(unittest.TestCase):
    def setUp(self):
        self.w = RailwayReadWorld(self)

    def met(self, reasons, units=1, read=1):
        return {"met": True, "system_railway": None, "units": units, "read": read,
                "reasons": reasons}

    def test_every_registered_railway_unit_read_from_its_dev_shell_is_met(self):
        root = self.w.project(railway_params(["api"])["config"])
        self.assertEqual(self.w.read(), (0, self.met(["deployed"])))
        (call,) = self.w.devenv_calls()
        self.assertEqual(call["cwd"], str(root))
        argv = call["argv"]
        self.assertEqual(json.loads(argv[argv.index("--parameters") + 1]), railway_params(["api"]))
        self.assertTrue(self.w.world.calls("railway"))

    def test_without_the_project_railway_the_unit_is_not_read(self):
        self.w.project(railway_params(["api"])["config"])
        (self.w.world.bin / "railway").unlink()
        self.assertEqual(self.w.read(), (1, {"met": False, "system_railway": None, "units": 1,
                                             "read": 0, "reasons": ["executable_missing"]}))

    def test_every_unit_must_read_not_one(self):
        self.w.project(railway_params(["api"])["config"])
        self.w.project(railway_params()["config"])
        self.w.world.respond("railway", ["deployment", "list", "--service", "admin",
                                         "--environment", "production", "--json"], None, exit=1,
                             stderr="Unauthorized. Please run `railway login` again.")
        self.assertEqual(self.w.read(), (1, {"met": False, "system_railway": None, "units": 2,
                                             "read": 1,
                                             "reasons": ["deployed", "railway_unauthorized"]}))

    def test_a_checkout_that_differs_from_origin_cannot_suppress_a_watch(self):
        root = self.w.project(railway_params(["api"])["config"])
        subprocess.run([self.w.git, "-C", str(root), "checkout", "-q", "-b", "local-only"], check=True)
        code, report = self.w.read()
        self.assertEqual(report["units"], 1)
        (call,) = self.w.inspect_calls
        self.assertEqual(call[0], self.w.contracts[str(root)])
        self.assertNotEqual(call[0], root)
        default = inspect.signature(verify_checks.railway_project_read).parameters["source"].default
        self.assertIs(default, verify_exec.project_source)

    def test_a_system_railway_is_not_met_and_reads_nothing(self):
        self.w.project(railway_params(["api"])["config"])
        found = self.w.sys / "railway"
        found.write_text("#!/bin/sh\n", encoding="utf-8")
        found.chmod(0o755)
        code, report = self.w.read()
        self.assertEqual((code, report["system_railway"], report["met"]), (1, str(found), False))
        self.assertEqual(self.w.devenv_calls(), [])
        self.assertEqual(self.w.source_calls, [])
        self.assertEqual(self.w.world.calls("railway"), [])

    def test_a_railway_in_the_global_nix_profile_is_found(self):
        prefix = self.w.tmp / "prefix"
        me, home = self.w.me, str(self.w.home)
        absolute = ("/nix/var/nix/profiles/default/bin", "/run/current-system/sw/bin",
                    f"/etc/profiles/per-user/{me}/bin", "/opt/homebrew/bin", "/usr/local/bin")
        for directory in absolute:
            with self.subTest(directory=directory):
                found = Path(f"{prefix}{directory}/railway")
                found.parent.mkdir(parents=True, exist_ok=True)
                found.write_text("#!/bin/sh\n", encoding="utf-8")
                found.chmod(0o755)
                path = verify_checks.railway_system_path(me, home, prefix=str(prefix))
                code, report = self.w.read(system_path=path)
                self.assertEqual((code, report["system_railway"]), (1, str(found)))
                found.unlink()
        with self.subTest(directory="{home}/.nix-profile/bin"):
            found = self.w.home / ".nix-profile/bin/railway"
            found.parent.mkdir(parents=True)
            found.write_text("#!/bin/sh\n", encoding="utf-8")
            found.chmod(0o755)
            path = verify_checks.railway_system_path(me, home, prefix=str(prefix))
            code, report = self.w.read(system_path=path)
            self.assertEqual((code, report["system_railway"]), (1, str(found)))

    def test_the_system_dirs_cover_the_runner_path(self):
        me, home = self.w.me, str(self.w.home)
        entries = verify_checks.railway_system_path(me, home).split(":")
        for entry in ("/run/current-system/sw/bin", "/nix/var/nix/profiles/default/bin",
                      "/usr/bin", "/bin", "/usr/sbin", "/sbin", f"/etc/profiles/per-user/{me}/bin",
                      f"{home}/.nix-profile/bin"):
            self.assertIn(entry, entries)

    def test_an_unread_unit_is_not_met(self):
        w = self.w
        w.project(railway_params(["api"])["config"])
        # The missing command goes last: it removes the world's railway for the rest of the test.
        for reason in ("railway_unauthorized", "lookup_failed", "executable_missing"):
            with self.subTest(reason=reason):
                if reason == "executable_missing":
                    (w.world.bin / "railway").unlink()
                else:
                    stderr = ("Unauthorized. Please run `railway login` again."
                              if reason == "railway_unauthorized" else "boom")
                    w.world.respond("railway", ["status", "--json"], None, exit=1, stderr=stderr)
                self.assertEqual(w.read(), (1, {"met": False, "system_railway": None, "units": 1,
                                                "read": 0, "reasons": [reason]}))

    def test_a_railway_project_without_a_dev_shell_is_not_met(self):
        root = self.w.project(railway_params(["api"])["config"])
        (root / "devenv.nix").unlink()
        self.assertEqual(self.w.read(), (1, {"met": False, "system_railway": None, "units": 1,
                                             "read": 0, "reasons": ["no_dev_shell"]}))
        self.assertEqual(self.w.devenv_calls(), [])

    def test_no_registered_railway_unit_is_not_yet(self):
        with self.subTest("another adapter"):
            self.w.project(railway_params(["api"])["config"])
            self.w.targets = [{"adapter": "github-forge", "operations": ["merge"],
                               "profile": "fixture-main", "target": {**SITE, "handle": "forge"}}]
            code, report = self.w.read()
            self.assertEqual((code, report["units"], report["met"]), (75, 0, False))
            self.assertEqual(self.w.inspect_calls, [])
        with self.subTest("no registry"):
            (self.w.home / ".agents/state/fleet/registry.json").unlink()
            self.assertEqual(self.w.read()[0], 75)

    def test_the_read_ends_before_the_runner_kills_it(self):
        self.assertLess(verify_checks.RAILWAY_READ_BUDGET + 3 * verify_exec.GIT_TIMEOUT,
                        verify_exec.TIMEOUT)
        self.w.project(railway_params(["api"])["config"])
        (self.w.state / "sleep").write_text("", encoding="utf-8")
        started = time.monotonic()
        self.assertEqual(self.w.read(budget=1), (2, {"met": False, "error": "read_timeout"}))
        self.assertLess(time.monotonic() - started, 10)
        with self.subTest("no time left"):
            self.w.source_calls.clear()
            self.assertEqual(self.w.read(budget=0), (2, {"met": False, "error": "read_timeout"}))
            self.assertEqual(self.w.source_calls, [])

    def test_an_unreadable_step_exits_2_with_its_code_only(self):
        def failing(code):
            return 2, {"met": False, "error": code}
        root = self.w.project(railway_params(["api"])["config"])
        with self.subTest("contract_unreadable"):
            self.w.unreadable.add(str(root))
            self.assertEqual(self.w.read(), failing("contract_unreadable"))
            self.w.unreadable.clear()
        with self.subTest("inspection_unreadable"):
            self.w.inspection = lambda contract_root: None
            self.assertEqual(self.w.read(), failing("inspection_unreadable"))
            self.w.inspection = None
        with self.subTest("read_failed"):
            (self.w.state / "fail").write_text("", encoding="utf-8")
            self.assertEqual(self.w.read(), failing("read_failed"))
            (self.w.state / "fail").unlink()
        with self.subTest("devenv_missing"):
            (self.w.sys / "devenv").unlink()
            self.assertEqual(self.w.read(), failing("devenv_missing"))
        with self.subTest("registry_unreadable"):
            (self.w.home / ".agents/state/fleet/registry.json").write_text("not json",
                                                                         encoding="utf-8")
            self.assertEqual(self.w.read(), failing("registry_unreadable"))

    def test_the_report_names_no_project(self):
        w = self.w
        w.project(railway_params(["api"])["config"])
        w.project(railway_params()["config"])
        w.world.respond("railway", ["deployment", "list", "--service", "admin", "--environment",
                                    "production", "--json"], None, exit=1, stderr="Unauthorized")
        reports = [w.read()[1]]
        w.unreadable.add(str(w.roots[0]))
        reports.append(w.read()[1])
        w.unreadable.clear()
        (w.world.bin / "railway").unlink()
        reports.append(w.read()[1])
        names = ["fixture-project-0", "fixture-project-1", "fixture-main", "fixture-site",
                 railway_world.SLUG, railway_world.CONFIG["project"],
                 railway_world.CONFIG["environment"], *railway_world.CONFIG["services"],
                 *map(str, w.roots), *map(str, w.contracts.values())]
        for report in reports:
            text = json.dumps(report)
            for name in names:
                self.assertNotIn(name, text)


class RailwayProjectReadCommandTest(unittest.TestCase):
    def test_the_profile_is_inspected_by_the_packaged_sibling_at_the_contract_root(self):
        seen = {}

        def bounded(argv, *, cwd, env, deadline):
            seen.update(argv=argv, cwd=cwd, env=env)
            return subprocess.CompletedProcess(argv, 0, "{}", "")
        with mock.patch.object(verify_checks, "_run_bounded", side_effect=bounded):
            result = verify_checks._railway_profile_inspection(
                Path("/c"), "p", {"PATH": "x"}, time.monotonic() + 5)
        self.assertEqual(result, {})
        self.assertEqual(seen["argv"], [*siblings.sibling_argv("release.release"), "profile",
                                        "inspect", "p", "--repo-root", "/c"])
        self.assertFalse(any(".agents/bin" in part for part in seen["argv"]))
        self.assertEqual(seen["env"], {"PATH": "x"})

    def test_the_command_prints_one_json_line_and_exits_with_the_verdict(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        empty, home = Path(tmp.name) / "empty", Path(tmp.name) / "home"
        empty.mkdir()
        home.mkdir()
        result = run_from_root([sys.executable, "-m", "agent_tools.verification.verify_checks",
                                "railway-project-read", "--system-path", str(empty)],
                               env_extra={"HOME": str(home)})
        self.assertEqual(result.returncode, 75, result.stderr)
        lines_out = result.stdout.splitlines()
        self.assertEqual(len(lines_out), 1)
        self.assertFalse(json.loads(lines_out[0])["met"])

    def test_the_check_script_is_committed_executable(self):
        self.assertEqual(committed_mode(f"{CHECKS}/railway-project-read"), "100755")


CONSOLE_LABEL = "org.nixos.agent-console"
PROXY_LABEL = "org.nixos.claude-cache-proxy"
SOPS_LABEL = "org.nixos.sops-nix"
VERIFY_LABEL = "org.nixos.verify-pending"
NO_SESSION = "ownerServices: the owner has no login session"
SESSION = "ownerServices: the owner has a login session"
DOMAIN = "Domain does not support specified action"


def loopback_server(handler):
    """A loopback `ThreadingHTTPServer` on port 0 serving `handler`, in a daemon thread."""
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


class ConsoleHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200 if self.path == "/api/state" else 404)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, *args):
        pass


class ProxyHandler(http.server.BaseHTTPRequestHandler):
    body = b'{"service":"cache-proxy"}'

    def do_GET(self):
        ok = self.path == "/_proxy/health"
        body = self.body if ok else b""
        self.send_response(200 if ok else 404)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class OwnerServicesWorld(unittest.TestCase):
    """A temp HOME with the forge key and the activation record, and the two loopback servers."""
    commit = "b" * 40

    def setUp(self):
        handle = tempfile.TemporaryDirectory()
        self.addCleanup(handle.cleanup)
        self.tmp = Path(handle.name)
        self.home = self.tmp / "home"
        (self.home / ".ssh").mkdir(parents=True)
        (self.home / "secret").write_text("key\n", encoding="utf-8")
        self.key = self.home / ".ssh" / "id_ed25519"
        self.key.symlink_to(self.home / "secret")
        self.state = self.home / ".agents" / "state" / "console"
        self.state.mkdir(parents=True)
        self.result = self.state / "activation.result"
        self.log = self.state / "activation.log"
        self.write_activation({"commit": self.commit, "exit": 0},
                              f"building\n{NO_SESSION}\ndone\n")
        self.store = self.state / "events.sqlite3"
        self.finish(self.commit, ok=True)
        self.proxy_handler = type("Proxy", (ProxyHandler,), {})
        self.console_server = loopback_server(ConsoleHandler)
        self.proxy_server = loopback_server(self.proxy_handler)
        self.addCleanup(self.stop, self.console_server)
        self.addCleanup(self.stop, self.proxy_server)
        self.console_port = self.console_server.server_address[1]
        self.proxy_port = self.proxy_server.server_address[1]

    @staticmethod
    def stop(server):
        server.shutdown()
        server.server_close()

    def finish(self, commit, *, ok):
        """Append one `activation.finished` row, as the console does when it settles a run."""
        connection = sqlite3.connect(self.store)
        try:
            connection.execute("CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY AUTOINCREMENT,"
                               " at TEXT NOT NULL, kind TEXT NOT NULL, project TEXT, payload TEXT NOT NULL)")
            connection.execute("INSERT INTO events (at, kind, project, payload) VALUES (?, ?, NULL, ?)",
                               ("2026-11-18T00:00:00Z", "activation.finished",
                                json.dumps({"root": "r", "commit": commit, "ok": ok})))
            connection.commit()
        finally:
            connection.close()

    def write_activation(self, result, log):
        if result is not None:
            self.result.write_text(json.dumps(result), encoding="utf-8")
        self.log.write_text(log, encoding="utf-8")
        self.age_log(10)

    def age_log(self, seconds):
        """Set the log's mtime `seconds` before the result's (negative: after)."""
        stamp = self.result.stat().st_mtime_ns if self.result.exists() else time.time_ns()
        shifted = stamp - seconds * 1_000_000_000
        os.utime(self.log, ns=(shifted, shifted))


class OwnerServicesTest(OwnerServicesWorld):
    """`owner-services` (issue 1290): the owner's services run at boot with nobody logged in."""

    def setUp(self):
        super().setUp()
        merge_base = ("-C", ".", "merge-base", "--is-ancestor", "a" * 40, self.commit)
        self.table = {
            ("print", "gui/502"): (113, ""),
            ("print", f"system/{CONSOLE_LABEL}"): (0, "\tstate = running\n\tpid = 4001\n"),
            ("print", f"system/{PROXY_LABEL}"): (0, "\tstate = running\n\tpid = 4002\n"),
            ("print", f"system/{SOPS_LABEL}"): (0, ""),
            ("print", f"system/{VERIFY_LABEL}"): (0, ""),
            ("-nP", "-a", f"-iTCP:{self.console_port}", "-sTCP:LISTEN", "-Fp"): (0, "p4001\nf3\n"),
            ("-nP", "-a", f"-iTCP:{self.proxy_port}", "-sTCP:LISTEN", "-Fp"): (0, "p4002\nf5\n"),
            merge_base: (0, ""),
        }
        self.merge_base = merge_base

    def fake(self, argv, **kw):
        answer = self.table[tuple(argv[1:])]
        if callable(answer):
            answer = answer()
        if isinstance(answer, BaseException):
            raise answer
        code, stdout = answer
        return subprocess.CompletedProcess(argv, code, stdout, "")

    def check(self):
        return verify_checks.owner_services(
            console_port=self.console_port, proxy_port=self.proxy_port, merge="a" * 40,
            home=self.home, uid=502, repo_root=Path("."), launchctl="/bin/launchctl",
            lsof="/usr/sbin/lsof", run=self.fake)

    def test_every_service_up_and_a_clean_page_activation_is_met(self):
        code, report = self.check()
        self.assertEqual((code, report["verdict"]), (0, "met"))
        self.assertEqual(report["activation"], "clean")
        self.assertTrue(report["met"])
        self.assertTrue(all(report["daemons"].values()))
        self.assertEqual(set(report["daemons"]), set(verify_checks.OWNER_SERVICE_LABELS))
        self.assertEqual(report["console"], {"answers": True, "owned": True})
        self.assertEqual(report["proxy"], {"answers": True, "owned": True})
        self.assertTrue(report["ssh_key"])

    def test_an_owner_gui_session_is_not_yet(self):
        self.table[("print", "gui/502")] = (0, "")
        self.assertEqual(self.check()[0], 75)
        self.assertEqual(self.check()[1]["verdict"], "logged_in")

    def test_a_gui_session_wins_over_a_failed_reading(self):
        self.table[("print", "gui/502")] = (0, "")
        self.table[("print", f"system/{SOPS_LABEL}")] = (113, "")
        code, report = self.check()
        self.assertEqual((code, report["verdict"]), (75, "logged_in"))

    def test_a_daemon_not_loaded_is_not_met(self):
        self.table[("print", f"system/{SOPS_LABEL}")] = (113, "")
        code, report = self.check()
        self.assertEqual((code, report["verdict"]), (1, "not_met"))
        self.assertIs(report["daemons"][SOPS_LABEL], False)

    def test_a_dangling_forge_key_is_not_met(self):
        (self.home / "secret").unlink()
        code, report = self.check()
        self.assertEqual((code, report["verdict"]), (1, "not_met"))
        self.assertIs(report["ssh_key"], False)

    def test_a_proxy_that_is_not_the_cache_proxy_is_not_met(self):
        self.proxy_handler.body = b'{"service":"other"}'
        code, report = self.check()
        self.assertEqual((code, report["verdict"]), (1, "not_met"))
        self.assertIs(report["proxy"]["answers"], False)

    def test_no_console_is_not_met(self):
        self.console_server.shutdown()
        self.console_server.server_close()
        code, report = self.check()
        self.assertEqual((code, report["verdict"]), (1, "not_met"))
        self.assertIs(report["console"]["answers"], False)

    def test_a_console_served_by_another_process_is_not_met(self):
        lsof = ("-nP", "-a", f"-iTCP:{self.console_port}", "-sTCP:LISTEN", "-Fp")
        self.table[("print", f"system/{CONSOLE_LABEL}")] = (0, "\tstate = spawn scheduled\n")
        self.table[lsof] = (0, "p5000\n")
        code, report = self.check()
        self.assertEqual((code, report["verdict"]), (1, "not_met"))
        self.assertEqual(report["console"], {"answers": True, "owned": False})
        self.assertIs(report["daemons"][CONSOLE_LABEL], True)
        with self.subTest("the job has a pid, another process listens"):
            self.table[("print", f"system/{CONSOLE_LABEL}")] = (0, "\tpid = 4001\n")
            self.assertIs(self.check()[1]["console"]["owned"], False)

    def test_a_domain_line_in_the_page_activation_is_not_met(self):
        self.write_activation({"commit": self.commit, "exit": 0},
                              f"building\n{NO_SESSION}\nBoot-out failed: 125: {DOMAIN}\n")
        code, report = self.check()
        self.assertEqual((code, report["verdict"], report["activation"]), (1, "not_met", "domain_lines"))

    def test_an_activation_without_the_session_line_is_not_met(self):
        self.write_activation({"commit": self.commit, "exit": 0}, "building\ndone\n")
        code, report = self.check()
        self.assertEqual((code, report["verdict"], report["activation"]), (1, "not_met", "unmarked"))

    def test_an_activation_in_an_owner_session_is_not_yet(self):
        self.write_activation({"commit": self.commit, "exit": 0}, f"building\n{SESSION}\n")
        code, report = self.check()
        self.assertEqual((code, report["verdict"], report["activation"]), (75, "not_yet", "logged_in"))

    def test_an_activation_of_an_older_commit_is_not_yet(self):
        self.table[self.merge_base] = (1, "")
        code, report = self.check()
        self.assertEqual((code, report["verdict"], report["activation"]), (75, "not_yet", "unread"))

    def test_an_unread_activation_is_not_yet(self):
        self.result.unlink()
        code, report = self.check()
        self.assertEqual((code, report["verdict"], report["activation"]), (75, "not_yet", "unread"))

    def test_a_failed_activation_is_not_yet(self):
        records = [({"commit": self.commit, "exit": 1}, "building\n"),
                   ({"commit": self.commit, "exit": True}, "building\n"),
                   ({"commit": self.commit, "exit": False}, "building\n"),
                   ({"commit": self.commit, "error": "FileNotFoundError: x"}, "")]
        for record, log in records:
            with self.subTest(record=record):
                self.write_activation(record, log)
                code, report = self.check()
                self.assertEqual((code, report["verdict"], report["activation"]),
                                 (75, "not_yet", "unread"))

    def test_an_activation_the_console_did_not_record_as_succeeded_is_not_yet(self):
        """The result's exit 0 is the command's; the console may then find the host on another revision."""
        for name, rows in (("no row", []), ("failed", [("b" * 40, False)]),
                           ("another commit", [("c" * 40, True)]),
                           ("a failure after a success", [("b" * 40, True), ("b" * 40, False)])):
            with self.subTest(name):
                self.store.unlink()
                if not rows:
                    sqlite3.connect(self.store).close()
                for commit, ok in rows:
                    self.finish(commit, ok=ok)
                code, report = self.check()
                self.assertEqual((code, report["verdict"], report["activation"]), (75, "not_yet", "unread"))
        with self.subTest("no store"):
            self.store.unlink()
            code, report = self.check()
            self.assertEqual((code, report["verdict"], report["activation"]), (75, "not_yet", "unread"))

    def test_a_success_after_a_failure_of_the_same_commit_is_met(self):
        self.finish(self.commit, ok=False)
        self.finish(self.commit, ok=True)
        self.assertEqual(self.check()[0], 0)

    def test_a_gui_domain_that_cannot_be_read_is_not_a_logout(self):
        for name, answer in (("exit 1", (1, "")), ("exit 64", (64, "")),
                             ("timeout", subprocess.TimeoutExpired(["launchctl"], 5)),
                             ("no tool", FileNotFoundError("launchctl"))):
            with self.subTest(name):
                self.table[("print", "gui/502")] = answer
                code, report = self.check()
                self.assertEqual((code, report["verdict"]), (1, "gui_unread"))
                self.assertFalse(report["met"])

    def test_every_missing_domain_answer_reads_as_no_session(self):
        for status in (112, 113, 125):
            with self.subTest(status=status):
                self.table[("print", "gui/502")] = (status, "")
                self.assertEqual(self.check()[1]["verdict"], "met")

    def test_a_log_newer_than_its_result_is_not_yet(self):
        self.age_log(-10)
        code, report = self.check()
        self.assertEqual((code, report["verdict"], report["activation"]), (75, "not_yet", "unread"))

    def test_a_result_replaced_while_reading_is_not_yet(self):
        def replaced():
            self.result.unlink()
            return 0, ""
        self.table[self.merge_base] = replaced
        code, report = self.check()
        self.assertEqual((code, report["verdict"], report["activation"]), (75, "not_yet", "unread"))

    def test_an_unread_activation_is_not_yet_even_with_a_service_down(self):
        self.result.unlink()
        self.proxy_server.shutdown()
        self.proxy_server.server_close()
        self.assertEqual(self.check()[0], 75)

    def test_a_missing_tool_is_a_failed_reading(self):
        for key in list(self.table):
            if key[0] == "-nP":
                self.table[key] = FileNotFoundError("lsof")
        code, report = self.check()
        self.assertEqual((code, report["verdict"]), (1, "not_met"))
        self.assertIs(report["console"]["owned"], False)


class OwnerServicesCommandTest(OwnerServicesWorld):
    def setUp(self):
        self.commit = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                                     capture_output=True, text=True, check=True).stdout.strip()
        super().setUp()
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        pid = os.getpid()
        self.launchctl = self.script("launchctl", f"""#!/bin/sh
echo "noise {self.home}" >&2
case "$*" in
  "print gui/"*) exit 113 ;;
  "print system/{CONSOLE_LABEL}"|"print system/{PROXY_LABEL}") echo "pid = {pid}"; exit 0 ;;
  *) exit 0 ;;
esac
""")
        self.lsof = self.script("lsof", f"""#!/bin/sh
echo "noise {self.home}" >&2
echo "p{pid}"
exit 0
""")
        self.arguments = ["owner-services", "--console-port", str(self.console_port),
                          "--proxy-port", str(self.proxy_port), "--merge", self.commit,
                          "--launchctl", str(self.launchctl), "--lsof", str(self.lsof)]

    def script(self, name, text):
        path = self.bin / name
        path.write_text(text, encoding="utf-8")
        path.chmod(0o755)
        return path

    def command(self, arguments=None):
        return run_from_root([sys.executable, "-m", "agent_tools.verification.verify_checks",
                              *(arguments or self.arguments)], env_extra={"HOME": str(self.home)})

    def test_the_command_prints_one_json_line_and_exits_with_the_verdict(self):
        result = self.command()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(result.stdout.splitlines()), 1)
        self.assertEqual(json.loads(result.stdout)["verdict"], "met")
        self.assertEqual(result.stderr, "")
        self.assertNotIn(str(self.home), result.stdout + result.stderr)
        self.assertNotIn("noise", result.stdout + result.stderr)

    def test_the_committed_script_runs_the_owner_services_check(self):
        (self.home / ".agents" / "bin").mkdir(parents=True)
        (self.home / ".agents" / "bin" / "verify-pending").write_text(
            "#!/bin/sh\nunset NIX_PYTHONPATH NIX_PYTHONPREFIX NIX_PYTHONEXECUTABLE\n"
            f'exec {sys.executable} -I -m agent_tools.verification.verify_pending "$@"\n',
            encoding="utf-8")
        result = subprocess.run(["/bin/sh", str(ROOT / CHECKS / "owner-services"), *self.arguments[1:]],
                                cwd=ROOT, env={"HOME": str(self.home), "PATH": "/usr/bin:/bin"},
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(result.stdout.splitlines()), 1)
        self.assertEqual(json.loads(result.stdout)["verdict"], "met")

    def test_a_bad_merge_sha_is_a_usage_error(self):
        arguments = list(self.arguments)
        arguments[arguments.index("--merge") + 1] = "xyz"
        result = self.command(arguments)
        self.assertEqual(result.returncode, 2)
        self.assertIn("--merge", result.stderr)
        self.assertNotIn("invalid choice", result.stderr)

    def test_the_session_lines_match_the_activation_cleanup(self):
        text = (ROOT / "hosts/common/darwin-owner-services.nix").read_text(encoding="utf-8")
        self.assertIn(verify_checks.NO_SESSION_LINE, text)
        self.assertIn(verify_checks.SESSION_LINE, text)

    def test_the_check_script_is_committed_executable(self):
        self.assertEqual(committed_mode(f"{CHECKS}/owner-services"), "100755")


FAKE_DEVENV = f"""#!{sys.executable}
import json, os, subprocess, sys, time
from pathlib import Path

state = Path(os.environ["DEVENV_SHELL_FIXTURE"])
with open(state / "devenv.jsonl", "a", encoding="utf-8") as log:
    log.write(json.dumps({{
        "argv": sys.argv[1:], "cwd": os.getcwd(), "pid": os.getpid(),
        "home": os.environ.get("HOME"),
        "git_config_global": os.environ.get("GIT_CONFIG_GLOBAL"),
        "git_dir": os.environ.get("GIT_DIR"),
        "git_index_file": os.environ.get("GIT_INDEX_FILE")}}) + "\\n")
if sys.argv[1:3] != ["shell", "--"]:
    sys.exit(64)
(Path.cwd() / ".devenv").mkdir(exist_ok=True)
(Path.cwd() / ".devenv" / "state").write_text("x", encoding="utf-8")
if (state / "stray").exists():
    (Path.cwd() / "stray.txt").write_text("x", encoding="utf-8")
if (state / "fail").exists():
    print("shell broke")
    sys.exit(3)
if (state / "nocommit").exists():
    sys.exit(0)
if (state / "sleep").exists():
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    (state / "grandchild.pid").write_text(str(child.pid), encoding="utf-8")
    time.sleep(60)
env = dict(os.environ)
command = sys.argv[3:]
if (state / "locked").exists():
    locked = Path.cwd() / ".devenv" / "locked"
    locked.mkdir(exist_ok=True)
    (locked / "f").write_text("x", encoding="utf-8")
    locked.chmod(0o500)
if (state / "localconfig").exists():
    subprocess.run(["git", "config", "core.hooksPath", "/dev/null"], check=True)
if (state / "message").exists():
    command = ["other" if word == "probe" else word for word in command]
if (state / "rewind").exists():
    env.update(GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="commit.gpgsign",
               GIT_CONFIG_VALUE_0="false")
    subprocess.run(command, env=env, check=True)
    subprocess.run(["git", "reset", "-q", "--hard", (state / "rewind").read_text()], check=True)
    sys.exit(0)
if (state / "hooks").exists():
    env.update(GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="core.hooksPath",
               GIT_CONFIG_VALUE_0="/dev/null")
sys.exit(subprocess.run(command, env=env).returncode)
"""
FAKE_KEYGEN = f"""#!{sys.executable}
import sys

if "-Y" in sys.argv and "sign" in sys.argv:
    with open(sys.argv[-1] + ".sig", "w", encoding="utf-8") as sig:
        sig.write("-----BEGIN SSH SIGNATURE-----\\nZmFrZQ==\\n-----END SSH SIGNATURE-----\\n")
"""


class DevenvShellWorld:
    """A repository, a fake `devenv` and a fake ssh signer under one private environment."""

    def __init__(self, test_case):
        scratch = tempfile.TemporaryDirectory()
        test_case.addCleanup(scratch.cleanup)
        self.tmp = Path(scratch.name).resolve()
        for name in ("bin", "state", "home"):
            (self.tmp / name).mkdir()
        self.state = self.tmp / "state"
        for name, text in (("devenv", FAKE_DEVENV), ("fake-ssh-keygen", FAKE_KEYGEN)):
            script = self.tmp / "bin" / name
            script.write_text(text, encoding="utf-8")
            script.chmod(0o755)
        (self.tmp / "key").write_text("dummy", encoding="utf-8")
        self.gitconfig = self.tmp / "gitconfig"
        self.set_signing(True)
        self.env = {
            **{k: v for k, v in os.environ.items() if not k.startswith("GIT_")},
            "HOME": str(self.tmp / "home"), "GIT_CONFIG_GLOBAL": str(self.gitconfig),
            "GIT_CONFIG_NOSYSTEM": "1", "DEVENV_SHELL_FIXTURE": str(self.state),
            "PATH": f"{self.tmp / 'bin'}:{os.environ['PATH']}",
            "PYTHONPATH": str(ROOT / "python")}
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", str(self.repo)], env=self.env, check=True)
        (self.repo / ".gitignore").write_text(".devenv/\n", encoding="utf-8")
        self.git("add", ".gitignore")
        self.git("commit", "-q", "-m", "base")
        self.base = self.git("rev-parse", "HEAD").strip()

    def set_signing(self, enabled):
        self.gitconfig.write_text(
            f"[user]\n\tname = Probe\n\temail = probe@example.invalid\n"
            f"\tsigningkey = {self.tmp / 'key'}\n[gpg]\n\tformat = ssh\n"
            f"[gpg \"ssh\"]\n\tprogram = {self.tmp / 'bin' / 'fake-ssh-keygen'}\n"
            f"[commit]\n\tgpgsign = {'true' if enabled else 'false'}\n", encoding="utf-8")

    def run(self, argv, env=None):
        return subprocess.run(argv, cwd=ROOT, env=env or self.env, capture_output=True,
                              text=True, timeout=60)

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), *args], env=self.env,
                              capture_output=True, text=True, check=True).stdout

    def check(self, probe, *extra, env=None):
        return self.run([str(ROOT / CHECKS / "devenv-shell"), "--probe", probe,
                         "--repo-root", str(self.repo), *extra], env)

    @staticmethod
    def report(result):
        return json.loads(result.stdout)

    def calls(self):
        log = self.state / "devenv.jsonl"
        if not log.exists():
            return []
        return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]

    def flag(self, name):
        (self.state / name).write_text("", encoding="utf-8")

    def worktrees(self):
        return [line for line in self.git("worktree", "list", "--porcelain").splitlines()
                if line.startswith("worktree ")]


def process_is_gone(pid, seconds=5):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.1)
    return False


class DevenvShellCheckTest(unittest.TestCase):
    def setUp(self):
        self.world = DevenvShellWorld(self)

    def test_a_signed_commit_through_the_shell_is_met(self):
        world = self.world
        result = world.check("commit")
        self.assertEqual(result.returncode, 0, result.stderr)
        report = world.report(result)
        self.assertEqual(sorted(report), [
            "elapsed_seconds", "exit", "hooks_path", "met", "new_commit", "output_tail",
            "probe", "reason", "signed", "status"])
        self.assertEqual(report["probe"], "commit")
        self.assertEqual(report["exit"], 0)
        self.assertIs(report["new_commit"], True)
        self.assertIs(report["signed"], True)
        self.assertEqual(report["status"], [])
        self.assertEqual(report["hooks_path"], {"outside": None, "inside": None})
        self.assertIsNone(report["reason"])
        self.assertIs(report["met"], True)
        self.assertIsInstance(report["elapsed_seconds"], float)
        self.assertIsInstance(report["output_tail"], list)
        calls = world.calls()
        self.assertEqual([call["argv"] for call in calls], [
            ["shell", "--", "git", "commit", "--allow-empty", "-m", "probe"],
            ["shell", "--", "git", "config", "--get", "core.hooksPath"]])
        self.assertEqual(calls[0]["cwd"], calls[1]["cwd"])
        self.assertNotEqual(calls[0]["cwd"], str(world.repo))
        for call in calls:
            self.assertEqual(call["home"], world.env["HOME"])
            self.assertEqual(call["git_config_global"], world.env["GIT_CONFIG_GLOBAL"])
        self.assertEqual(len(world.worktrees()), 1)
        self.assertEqual(world.git("rev-parse", "HEAD").strip(), world.base)
        self.assertEqual(world.git("status", "--porcelain"), "")
        self.assertFalse(Path(calls[0]["cwd"]).exists())

    def test_an_unsigned_commit_through_the_shell_is_not_met(self):
        self.world.set_signing(False)
        result = self.world.check("commit")
        self.assertEqual(result.returncode, 1, result.stderr)
        report = self.world.report(result)
        self.assertIs(report["new_commit"], True)
        self.assertIs(report["signed"], False)
        self.assertEqual(report["reason"], "unsigned")
        self.assertIs(report["met"], False)

    def test_a_shell_that_makes_no_commit_is_not_met(self):
        self.world.flag("nocommit")
        result = self.world.check("commit")
        self.assertEqual(result.returncode, 1, result.stderr)
        report = self.world.report(result)
        self.assertEqual(report["exit"], 0)
        self.assertIs(report["new_commit"], False)
        self.assertIs(report["signed"], False)
        self.assertEqual(report["reason"], "no_commit")

    def test_a_head_moved_to_an_older_signed_commit_is_not_a_probe_commit(self):
        world = self.world
        world.set_signing(False)
        world.git("commit", "--allow-empty", "-m", "tip")
        (world.state / "rewind").write_text(world.base, encoding="utf-8")
        result = world.check("commit")
        self.assertEqual(result.returncode, 1, result.stderr)
        report = world.report(result)
        self.assertEqual(report["exit"], 0)
        self.assertIs(report["new_commit"], False)
        self.assertEqual(report["reason"], "no_commit")
        self.assertIs(report["met"], False)

    def test_a_commit_with_another_message_is_not_the_probe_commit(self):
        world = self.world
        world.flag("message")
        result = world.check("commit")
        self.assertEqual(result.returncode, 1, result.stderr)
        report = world.report(result)
        self.assertIs(report["new_commit"], False)
        self.assertEqual(report["reason"], "no_commit")

    def test_a_shell_that_writes_the_repository_config_leaves_the_callers_untouched(self):
        world = self.world
        world.flag("localconfig")
        before = (world.repo / ".git" / "config").read_text(encoding="utf-8")
        result = world.check("commit")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(world.report(result)["reason"], "hooks_changed")
        self.assertEqual((world.repo / ".git" / "config").read_text(encoding="utf-8"), before)
        configured = subprocess.run(
            ["git", "-C", str(world.repo), "config", "--get", "core.hooksPath"],
            env=world.env, capture_output=True, text=True)
        self.assertEqual(configured.returncode, 1)
        self.assertEqual(len(world.worktrees()), 1)

    @unittest.skipIf(os.geteuid() == 0, "root can remove a read-only directory")
    def test_a_scratch_clone_that_cannot_be_removed_is_a_fixture_error(self):
        world = self.world
        world.flag("locked")
        result = world.check("clean")
        scratch = Path(world.calls()[0]["cwd"]).parent
        try:
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn("fixture_error", result.stderr)
            self.assertIn("not removed", result.stderr)
            self.assertEqual(result.stdout, "")
        finally:
            for locked in scratch.rglob("locked"):
                locked.chmod(0o700)
            shutil.rmtree(scratch, ignore_errors=True)

    def test_a_failing_shell_is_not_met(self):
        self.world.flag("fail")
        result = self.world.check("commit")
        self.assertEqual(result.returncode, 1, result.stderr)
        report = self.world.report(result)
        self.assertEqual(report["exit"], 3)
        self.assertEqual(report["reason"], "shell_failed")
        self.assertIn("shell broke", report["output_tail"])
        self.assertEqual(len(self.world.calls()), 1)

    def test_a_signed_commit_that_leaves_a_file_behind_is_not_met(self):
        world = self.world
        world.flag("stray")
        result = world.check("commit")
        self.assertEqual(result.returncode, 1, result.stderr)
        report = world.report(result)
        self.assertIs(report["new_commit"], True)
        self.assertIs(report["signed"], True)
        self.assertEqual(report["status"], ["?? stray.txt"])
        self.assertEqual(report["reason"], "dirty")
        self.assertIs(report["met"], False)
        self.assertEqual(len(world.worktrees()), 1)
        self.assertEqual(world.git("status", "--porcelain"), "")

    def test_a_shell_that_overrides_the_hooks_path_is_not_met(self):
        self.world.flag("hooks")
        result = self.world.check("commit")
        self.assertEqual(result.returncode, 1, result.stderr)
        report = self.world.report(result)
        self.assertIs(report["signed"], True)
        self.assertEqual(report["status"], [])
        self.assertEqual(report["hooks_path"], {"outside": None, "inside": "/dev/null"})
        self.assertEqual(report["reason"], "hooks_changed")

    def test_an_inherited_repository_redirect_cannot_reach_the_callers_branch(self):
        world = self.world
        staged = world.git("ls-files", "-s")
        redirect = {**world.env, "GIT_DIR": str(world.repo / ".git"),
                    "GIT_WORK_TREE": str(world.repo),
                    "GIT_INDEX_FILE": str(world.repo / ".git" / "index")}
        result = world.check("commit", env=redirect)
        self.assertEqual(result.returncode, 0, result.stderr)
        for call in world.calls():
            self.assertIsNone(call["git_dir"])
            self.assertIsNone(call["git_index_file"])
        self.assertEqual(world.git("rev-parse", "HEAD").strip(), world.base)
        self.assertEqual(world.git("rev-list", "--count", "HEAD").strip(), "1")
        self.assertEqual(world.git("ls-files", "-s"), staged)
        self.assertEqual(world.git("status", "--porcelain"), "")
        self.assertEqual(len(world.worktrees()), 1)

    def test_a_shell_past_the_bound_is_not_met_and_its_processes_end(self):
        world = self.world
        world.flag("sleep")
        started = time.monotonic()
        result = world.check("commit", "--timeout-seconds", "1")
        self.assertLess(time.monotonic() - started, 20)
        self.assertEqual(result.returncode, 1, result.stderr)
        report = world.report(result)
        self.assertIsNone(report["exit"])
        self.assertEqual(report["reason"], "timeout")
        grandchild = int((world.state / "grandchild.pid").read_text(encoding="utf-8"))
        self.assertTrue(process_is_gone(grandchild))
        self.assertTrue(process_is_gone(world.calls()[0]["pid"]))
        self.assertEqual(len(world.worktrees()), 1)

    def test_a_terminated_check_ends_its_shell_and_removes_its_worktree(self):
        world = self.world
        world.flag("sleep")
        proc = subprocess.Popen(
            [str(ROOT / CHECKS / "devenv-shell"), "--probe", "commit",
             "--repo-root", str(world.repo)],
            cwd=ROOT, env=world.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            pid_file = world.state / "grandchild.pid"
            deadline = time.monotonic() + 20
            while not pid_file.exists() and time.monotonic() < deadline:
                time.sleep(0.1)
            self.assertTrue(pid_file.exists())
            proc.send_signal(signal.SIGTERM)
            proc.wait(timeout=20)
            self.assertEqual(proc.returncode, 128 + signal.SIGTERM)
            self.assertTrue(process_is_gone(int(pid_file.read_text(encoding="utf-8"))))
            self.assertTrue(process_is_gone(world.calls()[0]["pid"]))
            self.assertEqual(len(world.worktrees()), 1)
            self.assertFalse(Path(world.calls()[0]["cwd"]).exists())
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
            proc.stdout.close()
            proc.stderr.close()

    def test_a_killed_check_still_ends_its_shell(self):
        world = self.world
        world.flag("sleep")
        proc = subprocess.Popen(
            [str(ROOT / CHECKS / "devenv-shell"), "--probe", "commit",
             "--repo-root", str(world.repo)],
            cwd=ROOT, env=world.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            pid_file = world.state / "grandchild.pid"
            deadline = time.monotonic() + 20
            while not pid_file.exists() and time.monotonic() < deadline:
                time.sleep(0.1)
            self.assertTrue(pid_file.exists())
            scratch = Path(world.calls()[0]["cwd"]).parent
            self.addCleanup(shutil.rmtree, scratch, ignore_errors=True)
            proc.kill()
            proc.wait(timeout=20)
            self.assertEqual(proc.returncode, -signal.SIGKILL)
            self.assertTrue(process_is_gone(int(pid_file.read_text(encoding="utf-8"))))
            self.assertTrue(process_is_gone(world.calls()[0]["pid"]))
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
            proc.stdout.close()
            proc.stderr.close()

    def test_a_timeout_past_the_bound_is_refused(self):
        for value in ("301", "0"):
            with self.subTest(value=value):
                result = self.world.check("commit", "--timeout-seconds", value)
                self.assertEqual(result.returncode, 2)
                self.assertIn("--timeout-seconds", result.stderr)
                self.assertEqual(self.world.calls(), [])
                self.assertEqual(len(self.world.worktrees()), 1)

    def test_no_devenv_on_path_is_not_met(self):
        world = self.world
        git = shutil.which("git")
        if git is None:
            self.skipTest("git is not installed")
        system = world.tmp / "sys"
        system.mkdir()
        (system / "git").symlink_to(git)
        (system / "python3").symlink_to(sys.executable)
        result = world.check("commit", env={**world.env, "PATH": str(system)})
        self.assertEqual(result.returncode, 1, result.stderr)
        report = world.report(result)
        self.assertEqual(report["reason"], "devenv_missing")
        self.assertIsNone(report["exit"])
        self.assertIs(report["met"], False)
        self.assertEqual(world.calls(), [])
        self.assertEqual(len(world.worktrees()), 1)

    def test_a_shell_that_leaves_the_checkout_clean_is_met(self):
        world = self.world
        result = world.check("clean")
        self.assertEqual(result.returncode, 0, result.stderr)
        report = world.report(result)
        self.assertEqual(report["probe"], "clean")
        self.assertEqual(report["exit"], 0)
        self.assertEqual(report["status"], [])
        self.assertIsNone(report["reason"])
        self.assertIs(report["met"], True)
        self.assertEqual(sorted(report), [
            "elapsed_seconds", "exit", "met", "output_tail", "probe", "reason", "status"])
        self.assertEqual([call["argv"] for call in world.calls()], [["shell", "--", "true"]])

    def test_a_shell_that_dirties_the_checkout_is_not_met(self):
        world = self.world
        world.flag("stray")
        result = world.check("clean")
        self.assertEqual(result.returncode, 1, result.stderr)
        report = world.report(result)
        self.assertEqual(report["status"], ["?? stray.txt"])
        self.assertEqual(report["reason"], "dirty")
        self.assertEqual(len(world.worktrees()), 1)
        self.assertEqual(world.git("status", "--porcelain"), "")

    def test_an_unrelated_worktree_registration_survives(self):
        world = self.world
        other = world.tmp / "other"
        world.git("worktree", "add", "--detach", str(other))
        shutil.rmtree(other)
        result = world.check("clean")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"worktree {other}", world.worktrees())

    def test_the_wrapper_is_committed_executable(self):
        self.assertEqual(committed_mode(f"{CHECKS}/devenv-shell"), "100755")
        result = self.world.run([str(ROOT / CHECKS / "devenv-shell")])
        self.assertEqual(result.returncode, 2)
