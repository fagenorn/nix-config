"""`agent_tools.verify_checks`: the committed verify checks of issue 638."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from agent_tools.verify_checks import after_switch, job_ancestor, scheduled_pass

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


if __name__ == "__main__":
    unittest.main()
