"""`agent_tools.verify_checks`: the committed verify checks of issue 638."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from agent_tools import forge_markers, verify_checks
from agent_tools.verify_checks import (after_switch, job_ancestor, required_checks,
                                       scheduled_pass)

ROOT = Path(__file__).resolve().parents[1]
CHECKS = "home/common/verify-pending/checks"
PASS = "/nix/store/" + "a" * 32 + "-verify-pending-pass"
BASH = ("/nix/store/" + "b" * 32 + "-bash/bin/bash",)
RUNNER = (1300, 1200, ("python3", "-m", "agent_tools.verify_pending", "run", "--host", "mbp"))
SWITCHED = datetime(2026, 11, 8, 10, 0, 0, 500000, tzinfo=timezone.utc)
NOW = datetime(2026, 11, 8, 12, 0, 0, tzinfo=timezone.utc)


def run_from_root(argv, env_extra=None):
    env = {**os.environ, "PYTHONPATH": str(ROOT / "python"), **(env_extra or {})}
    return subprocess.run(argv, cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)


def committed_mode(path):
    return subprocess.run(["git", "-C", str(ROOT), "ls-files", "-s", path],
                          capture_output=True, text=True, check=True).stdout.split(" ")[0]


class JobAncestorTest(unittest.TestCase):
    def test_pass_started_by_launchd_is_met(self):
        chain = [RUNNER, (1200, 1, (*BASH, PASS, "mbp")), (1, 0, ("/sbin/launchd",))]
        self.assertEqual(scheduled_pass(chain, "mbp"), (0, {"host": "mbp", "job_pid": 1200}))

    def test_pass_started_by_the_systemd_user_manager_is_met(self):
        chain = [RUNNER, (1200, 900, (*BASH, PASS, "anis-desktop")),
                 (900, 1, ("/run/current-system/systemd/lib/systemd/systemd", "--user"))]
        self.assertEqual(job_ancestor(chain, "anis-desktop"), 1200)

    def test_manual_run_while_a_scheduled_pass_runs_is_not_yet(self):
        # The scheduled pass is a sibling, not an ancestor: only this process's chain counts.
        chain = [RUNNER, (1200, 800, ("-zsh",)), (800, 1, ("/sbin/launchd",))]
        self.assertEqual(scheduled_pass(chain, "mbp"), (75, {"host": "mbp", "job_pid": None}))

    def test_pass_script_run_by_hand_from_a_shell_is_not_yet(self):
        chain = [RUNNER, (1200, 800, (*BASH, PASS, "mbp")), (800, 700, ("-zsh",)), (700, 1, ("login",))]
        self.assertIsNone(job_ancestor(chain, "mbp"))

    def test_pass_for_another_host_or_outside_the_store_is_not_yet(self):
        other = [RUNNER, (1200, 1, (*BASH, PASS, "eleven-m5"))]
        local = [RUNNER, (1200, 1, (*BASH, "/tmp/x-verify-pending-pass", "mbp"))]
        self.assertIsNone(job_ancestor(other, "mbp"))
        self.assertIsNone(job_ancestor(local, "mbp"))


class AfterSwitchTest(unittest.TestCase):
    def test_pass_within_60s_of_the_switch_is_met(self):
        lines = ["2026-11-08T09:45:00Z pass start host=mbp",
                 "2026-11-08T10:00:01Z switch host=mbp target=/nix/store/a current=yes",
                 "2026-11-08T10:00:01Z pass start host=mbp"]
        code, report = after_switch(lines, "mbp", SWITCHED, NOW)
        self.assertEqual((code, report["gap_s"]), (0, 1))

    def test_request_delayed_behind_a_running_round_is_not_met(self):
        # A round starts before the switch and runs 5 minutes; pass.sh then logs the
        # switch line and the next pass start back to back. The gap is from the link.
        lines = ["2026-11-08T09:59:50Z pass start host=mbp",
                 "2026-11-08T10:05:00Z pass end host=mbp verify=0 owner_actions=0",
                 "2026-11-08T10:05:00Z switch host=mbp target=/nix/store/a current=yes",
                 "2026-11-08T10:05:00Z pass start host=mbp"]
        code, report = after_switch(lines, "mbp", SWITCHED, NOW)
        self.assertEqual((code, report["gap_s"]), (1, 300))

    def test_no_pass_yet_is_not_yet_then_not_met(self):
        soon = datetime(2026, 11, 8, 10, 0, 30, tzinfo=timezone.utc)
        self.assertEqual(after_switch([], "mbp", SWITCHED, soon)[0], 75)
        self.assertEqual(after_switch([], "mbp", SWITCHED, NOW)[0], 1)

    def test_other_hosts_never_count(self):
        lines = ["2026-11-08T10:00:01Z pass start host=eleven-m5"]
        self.assertEqual(after_switch(lines, "mbp", SWITCHED, NOW)[0], 1)


class ScheduledPassCommandTest(unittest.TestCase):
    def test_wrapper_reads_the_rotated_log_and_the_link_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "runner.log"
            Path(f"{log}.1").write_text("2026-11-08T10:00:02Z pass start host=mbp\n")
            log.write_text("2026-11-08T10:15:00Z pass start host=mbp\n")
            link = Path(tmp) / "current-system"
            os.symlink("/nonexistent/system", link)
            os.utime(link, (SWITCHED.timestamp(), SWITCHED.timestamp()), follow_symlinks=False)
            done = run_from_root([str(ROOT / CHECKS / "scheduled-pass"), "--host", "mbp",
                                  "--after-switch", "--log", str(log), "--current-system", str(link),
                                  "--now", "2026-11-08T12:00:00Z"])
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(done.stdout)["gap_s"], 2)

    def test_wrapper_outside_the_job_is_not_yet(self):
        done = run_from_root([str(ROOT / CHECKS / "scheduled-pass"), "--host", "mbp"])
        self.assertEqual(done.returncode, 75, done.stderr)
        self.assertEqual(json.loads(done.stdout), {"host": "mbp", "job_pid": None})

    def test_missing_current_system_is_an_error(self):
        done = run_from_root([sys.executable, "-m", "agent_tools.verify_checks", "scheduled-pass",
                              "--host", "mbp", "--after-switch", "--current-system", "/nonexistent/cs"])
        self.assertEqual((done.returncode, done.stdout), (2, ""))

    def test_bad_host_is_a_usage_error(self):
        done = run_from_root([sys.executable, "-m", "agent_tools.verify_checks", "scheduled-pass",
                              "--host", "Bad Host"])
        self.assertEqual(done.returncode, 2)

    def test_wrapper_is_committed_executable(self):
        self.assertEqual(committed_mode(f"{CHECKS}/scheduled-pass"), "100755")


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
    return (mock.patch.object(forge_markers, "api_get", side_effect=api_get),
            mock.patch.object(forge_markers, "api_pages", side_effect=api_pages))


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


def run(name, conclusion="success", completed="2026-11-07T09:50:00Z", status="completed"):
    return {"name": name, "status": status, "conclusion": conclusion, "completed_at": completed}


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
        with self.assertRaises(forge_markers.ForgeError):
            self.check(gets, pages)

    def test_an_incomplete_search_is_refused(self):
        gets, pages = world([run("lint")])
        pages[SEARCH] = [search_page([2610], incomplete=True)]
        with self.assertRaises(forge_markers.ForgeError) as raised:
            self.check(gets, pages)
        self.assertEqual(raised.exception.code, "payload_invalid")

    def test_a_truncated_search_is_refused(self):
        gets, pages = world([run("lint")])
        pages[SEARCH] = [search_page([2610], total=1500)]
        with self.assertRaises(forge_markers.ForgeError):
            self.check(gets, pages)

    def test_check_runs_on_a_second_page_count_and_a_short_listing_is_refused(self):
        gets, pages = world([])
        pages[RUNS] = [{"total_count": 101, "check_runs": [run(f"other-{i}") for i in range(100)]},
                       {"total_count": 101, "check_runs": [run("lint")]}]
        self.assertEqual(self.check(gets, pages)[0], 0)
        pages[RUNS] = [{"total_count": 101, "check_runs": [run(f"other-{i}") for i in range(100)]}]
        with self.assertRaises(forge_markers.ForgeError):
            self.check(gets, pages)

    def test_forge_error_propagates(self):
        with mock.patch.object(forge_markers, "api_pages",
                               side_effect=forge_markers.ForgeError("gh_failed", "boom")):
            with self.assertRaises(forge_markers.ForgeError):
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
        done = run_from_root([sys.executable, "-m", "agent_tools.verify_checks", "required-checks",
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


if __name__ == "__main__":
    unittest.main()
