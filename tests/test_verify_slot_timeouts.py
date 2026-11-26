"""The verify-slot timeout share check: the share of one repository's requests that timed out in a window.

Runs `agent_tools.delivery.verify_slot_timeouts` and its committed wrapper as children against a scratch
verify-slot history: which requests count, what makes the share met, not met or not yet, and an unreadable history.
Run: just agent-workflow-tests
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

TIER = "fast"

ROOT = Path(__file__).resolve().parent.parent
WRAPPER = "home/common/verify-pending/checks/verify-slot-timeouts"
REPOSITORY = "fagenorn/nix-config"
DEPLOYED = ["--repository", REPOSITORY, "--hours", "24"]


def stamp(moment):
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def request(repository=REPOSITORY, timed_out=False, age=timedelta(hours=1)):
    """One history record started `age` before now; a timeout is exit 75 with no hold."""
    return {"command": "just test", "exit": 75 if timed_out else 0, "held_seconds": None if timed_out else 12.0,
            "repository": repository, "started": stamp(datetime.now(timezone.utc) - age), "waited_seconds": 600.0,
            "place": None}


def requests(count, timed_out=0, **extra):
    return [request(timed_out=index < timed_out, **extra) for index in range(count)]


class VerifySlotTimeoutsTest(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.scratch = Path(scratch.name)
        self.history = self.scratch / "history.jsonl"

    def write(self, records, path=None):
        (path or self.history).write_text("".join(json.dumps(record) + "\n" for record in records))

    def env(self):
        return {**os.environ, "PYTHONPATH": str(ROOT / "python"), "VERIFY_SLOT_DIR": str(self.scratch)}

    def run_check(self, *argv):
        return subprocess.run([sys.executable, "-m", "agent_tools.delivery.verify_slot_timeouts", *argv],
                              capture_output=True, text=True, env=self.env(), cwd=self.scratch)

    def test_a_day_whose_timed_out_share_is_below_the_baseline_is_met(self):
        self.write(requests(30, timed_out=10))
        result = self.run_check(*DEPLOYED)
        self.assertEqual(result.returncode, 0, result.stderr)
        answer = json.loads(result.stdout)
        self.assertEqual(answer["verdict"], "met")
        self.assertEqual(answer["requests"], 30)
        self.assertEqual(answer["timed_out"], 10)
        self.assertEqual(answer["baseline_timed_out"], 85)
        self.assertEqual(answer["baseline_requests"], 149)

    def test_the_baseline_share_itself_is_not_met(self):
        self.write(requests(149, timed_out=85))
        result = self.run_check(*DEPLOYED, "--history", str(self.history))
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(json.loads(result.stdout)["verdict"], "not_met")

    def test_fewer_than_twenty_requests_is_not_yet(self):
        self.write(requests(19))
        result = self.run_check(*DEPLOYED, "--history", str(self.history))
        self.assertEqual(result.returncode, 75, result.stderr)
        self.assertEqual(json.loads(result.stdout)["verdict"], "not_yet")

    def test_other_repositories_older_and_future_requests_do_not_count(self):
        self.write(requests(20)
                   + requests(50, timed_out=50, repository="other/repo")
                   + requests(50, timed_out=50, age=timedelta(hours=30))
                   + requests(50, timed_out=50, age=timedelta(hours=-1)))
        result = self.run_check(*DEPLOYED, "--history", str(self.history))
        self.assertEqual(result.returncode, 0, result.stderr)
        answer = json.loads(result.stdout)
        self.assertEqual(answer["requests"], 20)
        self.assertEqual(answer["timed_out"], 0)

    def test_a_run_that_waited_and_then_failed_is_not_a_timeout(self):
        self.write([{**request(), "exit": 75, "held_seconds": 3.0} for _ in range(20)])
        result = self.run_check(*DEPLOYED, "--history", str(self.history))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["timed_out"], 0)

    def test_an_absent_history_is_not_yet(self):
        result = self.run_check(*DEPLOYED, "--history", str(self.scratch / "missing.jsonl"))
        self.assertEqual(result.returncode, 75, result.stderr)
        self.assertEqual(json.loads(result.stdout)["requests"], 0)

    def test_an_unreadable_history_fails(self):
        result = self.run_check(*DEPLOYED, "--history", str(self.scratch))
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertTrue(result.stderr.startswith("verify-slot-timeouts: "), result.stderr)

    def test_the_wrapper_is_committed_executable_and_runs_the_check(self):
        listing = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-s", WRAPPER],
                                 capture_output=True, text=True, check=True).stdout
        self.assertTrue(listing.startswith("100755"), listing)
        self.write(requests(30, timed_out=10))
        result = subprocess.run([str(ROOT / WRAPPER), *DEPLOYED], capture_output=True, text=True, cwd=ROOT,
                                env=self.env())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["verdict"], "met")


if __name__ == "__main__":
    unittest.main()
