"""Issue 4 acceptance soak: priorities and due dates through the CLI (slow; opt in)."""
import contextlib
import io
import os
import tempfile
import time
import unittest

from tinytask.cli import main

SOAK_SECONDS = 330


def run(*argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = main(list(argv))
    return code, out.getvalue().splitlines()


@unittest.skipUnless(os.environ.get("TINYTASK_ACCEPTANCE") == "1", "set TINYTASK_ACCEPTANCE=1")
class PriorityAcceptance(unittest.TestCase):
    def test_priorities_and_due_dates_hold_for_the_whole_soak(self):
        deadline, rounds = time.monotonic() + SOAK_SECONDS, 0
        while time.monotonic() < deadline:
            with tempfile.TemporaryDirectory() as tmp:
                path = os.path.join(tmp, "tasks.json")
                self.assertEqual(run("--file", path, "add", "low one", "--priority", "low")[0], 0)
                self.assertEqual(run("--file", path, "add", "urgent", "--priority", "high",
                                     "--due", "2026-11-01")[0], 0)
                self.assertEqual(run("--file", path, "add", "plain")[0], 0)
                code, lines = run("--file", path, "list", "--sort", "priority", "--long")
                self.assertEqual(code, 0)
                self.assertEqual([line.split("\t")[2] for line in lines], ["high", "normal", "low"])
                self.assertEqual(lines[0].split("\t")[3], "2026-11-01")
                self.assertEqual(run("--file", path, "edit", "1", "--priority", "high")[0], 0)
                code, lines = run("--file", path, "list", "--sort", "due", "--long")
                self.assertEqual(lines[0].split("\t")[4], "urgent")
                self.assertEqual(run("--file", path, "list")[1][0], "1\topen\tlow one")
            rounds += 1
            time.sleep(0.5)
        self.assertGreater(rounds, 100)
