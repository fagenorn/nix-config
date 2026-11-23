"""`agent_tools.verification.cleanup_fix_check`: the first fix change reports its required checks."""
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from agent_tools.delivery import cleanup_issue
from agent_tools.system import forge_api
from agent_tools.verification import cleanup_fix_check
from agent_tools.verification.cleanup_fix_check import cleanup_fix_checks

TIER = "fast"

ROOT = Path(__file__).resolve().parents[1]
WRAPPER = "home/common/verify-pending/checks/cleanup-fix-checks"
HEAD = "h" * 40
APP = 15368
PULLS = "repos/o/w/pulls?state=all&base=main&per_page=100"
PROTECTION = "repos/o/w/branches/main/protection/required_status_checks"
RULES = "repos/o/w/rules/branches/main?per_page=100"
CHECK_RUNS = f"repos/o/w/commits/{HEAD}/check-runs?per_page=100"
OPEN = "repos/o/w/issues?state=open&per_page=100"
CLOSED = "repos/o/w/issues?state=closed&since="
RUNS = "repos/o/w/actions/workflows/cleanup-issue.yaml/runs?branch=main&created=%3E%3D"


def at(text):
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def fix_pull(number, login="octo", association="OWNER", body="<!-- agent:cleanup-fix v1 rule=PY7 -->"):
    return {"number": number, "body": body, "user": {"login": login},
            "author_association": association, "head": {"sha": HEAD},
            "created_at": "2026-12-01T00:00:00Z"}


def cleanup_item(number, closed_at=None, login="github-actions[bot]", association="NONE",
                 body="<!-- agent:cleanup v1 rule=PY11 -->", pull_request=False):
    item = {"number": number, "body": body, "user": {"login": login},
            "author_association": association}
    if closed_at is not None:
        item["closed_at"] = closed_at
    if pull_request:
        item["pull_request"] = {}
    return item


def check_run(name, app=APP, status="completed", conclusion="success"):
    return {"name": name, "app": {"id": app}, "status": status, "conclusion": conclusion}


class CleanupFixCheckTest(unittest.TestCase):
    def run_check(self, pulls=(), runs=(), open_issues=(), closed=(), workflow_runs=(),
                  now="2026-12-24T00:00:00Z", window=14):
        self.paths = []
        checks = [{"context": "Nix Eval", "app_id": APP},
                  {"context": "Agent Workflow Tests", "app_id": APP}]

        def api_get(path, allow=()):
            self.assertEqual(path, PROTECTION)
            return {"checks": checks, "contexts": []}

        def api_pages(path):
            self.paths.append(path)
            if path == PULLS:
                return [list(pulls)]
            if path == RULES:
                return [[]]
            if path == CHECK_RUNS:
                return [{"total_count": len(runs), "check_runs": list(runs)}]
            if path == OPEN:
                return [list(open_issues)]
            if path.startswith(CLOSED):
                return [list(closed)]
            if path.startswith(RUNS):
                return [{"total_count": len(workflow_runs), "workflow_runs": list(workflow_runs)}]
            raise AssertionError(f"unexpected paginated read {path}")

        with (mock.patch.object(forge_api, "api_get", side_effect=api_get),
              mock.patch.object(forge_api, "api_pages", side_effect=api_pages),
              mock.patch.object(forge_api, "server_now", return_value=at(now))):
            return cleanup_fix_checks("o/w", "main", "cleanup-issue.yaml", window)

    def test_a_fix_change_whose_head_reports_every_required_check_is_met(self):
        runs = [check_run("Nix Eval", status="in_progress", conclusion=None),
                check_run("Agent Workflow Tests", conclusion="failure")]
        self.assertEqual(self.run_check(pulls=[fix_pull(40)], runs=runs), (0, {
            "pr": 40, "head": HEAD, "required": ["Agent Workflow Tests", "Nix Eval"],
            "missing": [], "held": None, "freed": None, "picked": None, "status": "met"}))

    def test_the_restated_values_equal_the_cleanup_commands(self):
        self.assertEqual(
            (cleanup_fix_check.FIX_KIND, cleanup_fix_check.CLEANUP_KIND, cleanup_fix_check.FILER,
             cleanup_fix_check.TRUSTED),
            (cleanup_issue.FIX_KIND, cleanup_issue.CLEANUP_KIND, cleanup_issue.FILER,
             cleanup_issue.TRUSTED))

    def test_an_open_cleanup_issue_holds_the_clock(self):
        other = fix_pull(7, body="<!-- agent:cleanup v1 rule=PY11 -->")
        open_issues = [cleanup_item(1700), cleanup_item(1639),
                       cleanup_item(1, pull_request=True)]
        code, report = self.run_check(pulls=[other], open_issues=open_issues)
        self.assertEqual((code, report["status"], report["held"], report["pr"]),
                         (75, "queue_held", 1639, None))
        self.assertFalse([path for path in self.paths if "state=closed" in path])

    def test_a_free_slot_waits_14_days_from_the_first_run_after_the_freeing_close(self):
        closed = [cleanup_item(1, "2026-12-01T00:00:00Z"), cleanup_item(2, "2026-12-10T00:00:00Z")]
        workflow_runs = [{"created_at": "2026-12-10T06:00:00Z"},
                         {"created_at": "2026-12-10T00:05:00Z"}]
        code, report = self.run_check(closed=closed, workflow_runs=workflow_runs)
        self.assertEqual((code, report["status"], report["freed"], report["picked"]),
                         (75, "deferred", "2026-12-10T00:00:00Z", "2026-12-10T00:05:00Z"))
        self.assertIn(f"{RUNS}2026-12-10T00:00:00Z&per_page=100", self.paths)
        code, report = self.run_check(closed=closed, workflow_runs=workflow_runs,
                                      now="2026-12-24T00:06:00Z")
        self.assertEqual((code, report["status"]), (1, "not_opened"))

    def test_a_free_slot_with_no_run_yet_is_not_yet(self):
        code, report = self.run_check(closed=[cleanup_item(2, "2026-12-10T00:00:00Z")])
        self.assertEqual((code, report["status"], report["picked"]), (75, "no_run", None))

    def test_a_closed_issue_without_the_marker_or_by_an_untrusted_author_starts_no_clock(self):
        closed = [cleanup_item(1, "2026-12-01T00:00:00Z", body="no marker"),
                  cleanup_item(2, "2026-12-02T00:00:00Z", login="mallory"),
                  cleanup_item(3, "2026-12-03T00:00:00Z", pull_request=True)]
        code, report = self.run_check(closed=closed)
        self.assertEqual((code, report["status"], report["freed"]), (1, "not_opened", None))

    def test_a_fix_marker_by_an_untrusted_author_is_not_judged(self):
        code, report = self.run_check(pulls=[fix_pull(40, login="mallory", association="NONE")],
                                      open_issues=[cleanup_item(1639)])
        self.assertEqual((code, report["pr"], report["status"]), (75, None, "queue_held"))

    def test_the_lowest_numbered_fix_change_is_judged(self):
        code, report = self.run_check(pulls=[fix_pull(50), fix_pull(40)], runs=[
            check_run("Nix Eval"), check_run("Agent Workflow Tests")])
        self.assertEqual((code, report["pr"]), (0, 40))

    def test_a_missing_check_waits_an_hour_then_is_not_met(self):
        runs = [check_run("Nix Eval")]
        code, report = self.run_check(pulls=[fix_pull(40)], runs=runs, now="2026-12-01T00:30:00Z")
        self.assertEqual((code, report["status"], report["missing"]),
                         (75, "waiting", ["Agent Workflow Tests"]))
        code, report = self.run_check(pulls=[fix_pull(40)], runs=runs, now="2026-12-01T01:01:00Z")
        self.assertEqual((code, report["status"]), (1, "not_met"))

    def test_a_run_from_another_app_does_not_report_a_bound_check(self):
        runs = [check_run("Nix Eval", app=999), check_run("Agent Workflow Tests", app=999)]
        code, report = self.run_check(pulls=[fix_pull(40)], runs=runs)
        self.assertEqual((code, report["missing"]), (1, ["Agent Workflow Tests", "Nix Eval"]))


class CleanupFixCheckCommandTest(unittest.TestCase):
    def test_wrapper_maps_a_forge_error_to_exit_2(self):
        # PATH holds only python3, so the wrapper finds its interpreter and gh is missing.
        with tempfile.TemporaryDirectory() as tmp:
            os.symlink(sys.executable, Path(tmp) / "python3")
            done = subprocess.run(
                ["/bin/sh", str(ROOT / WRAPPER), "--repo", "o/w", "--base", "main",
                 "--workflow", "cleanup-issue.yaml", "--window-days", "14"],
                cwd=ROOT, env={**os.environ, "PYTHONPATH": str(ROOT / "python"), "PATH": tmp},
                capture_output=True, text=True, timeout=60)
        self.assertEqual((done.returncode, done.stdout), (2, ""), done.stderr)
        self.assertIn("cleanup-fix-checks: forge_error", done.stderr)

    def test_wrapper_is_committed_executable(self):
        mode = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-s", WRAPPER],
                              capture_output=True, text=True, check=True).stdout.split(" ")[0]
        self.assertEqual(mode, "100755")


if __name__ == "__main__":
    unittest.main()
