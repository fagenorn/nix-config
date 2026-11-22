"""The verify-slot command (#1383): a host-wide verify slot held by flock while a command runs.

Run: just agent-workflow-tests
"""

import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from agent_tools.delivery.verify_slot import NO_SLOT_EXIT, NO_SLOT_LINE, WAITING_LINE
from .process_liveness import process_alive

REPO_ROOT = Path(__file__).resolve().parents[1]
COMMITTED_DECLARATION = REPO_ROOT / "home/common/agent-skills/host-declaration.json"
WAITED_PATTERN = re.compile(r"^verify-slot: waited \d+\.\ds for a verify slot$", re.MULTILINE)

CHILD = """
import os, sys, time
directory, name = sys.argv[1], sys.argv[2]
code = int(sys.argv[3]) if len(sys.argv) > 3 else 0
def put(suffix, text):
    with open(os.path.join(directory, name + "." + suffix), "w") as handle:
        handle.write(text)
put("pid", str(os.getpid()))
put("start", repr(time.time()))
release = os.path.join(directory, name + ".release")
deadline = time.monotonic() + 60
while not os.path.exists(release) and time.monotonic() < deadline:
    time.sleep(0.05)
put("end", repr(time.time()))
sys.exit(code)
"""


def wait_for(path, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return True
        time.sleep(0.02)
    return False


class VerifySlotTest(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.home = scratch.name
        self.marks = Path(self.home) / "marks"
        self.marks.mkdir()
        self.procs = []
        self.addCleanup(self.reap)

    def reap(self):
        for proc in self.procs:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
        for pid_file in self.marks.glob("*.pid"):
            try:
                pid = int(pid_file.read_text())
            except ValueError:
                continue
            if process_alive(pid):
                os.kill(pid, signal.SIGKILL)

    def declare(self, **extra):
        target = Path(self.home) / ".agents/share/host-declaration.json"
        target.parent.mkdir(parents=True)
        declaration = json.loads(COMMITTED_DECLARATION.read_text())
        declaration.update(extra)
        target.write_text(json.dumps(declaration))

    def start(self, name, *opts, code=None, argv=None):
        tail = [str(code)] if code is not None else []
        command = argv if argv is not None else [
            sys.executable, "-c", CHILD, str(self.marks), name, *tail]
        proc = subprocess.Popen(
            [sys.executable, "-m", "agent_tools.delivery.verify_slot", "run", *opts, "--", *command],
            env={**os.environ, "HOME": self.home, "PYTHONPATH": str(REPO_ROOT / "python")},
            cwd=self.home, stderr=subprocess.PIPE, text=True)
        self.procs.append(proc)
        return proc

    def mark(self, name, suffix):
        return self.marks / f"{name}.{suffix}"

    def release(self, name):
        self.mark(name, "release").write_text("")

    def finish(self, proc, timeout=30):
        _, err = proc.communicate(timeout=timeout)
        return proc.returncode, err

    def test_with_one_slot_a_second_run_waits_until_the_first_ends(self):
        first = self.start("a")
        self.assertTrue(wait_for(self.mark("a", "start")))
        second = self.start("b")
        time.sleep(1.5)
        self.assertFalse(self.mark("b", "start").exists())
        self.release("a")
        first_code, first_err = self.finish(first)
        self.assertTrue(wait_for(self.mark("b", "start")))
        self.release("b")
        second_code, second_err = self.finish(second)
        self.assertEqual((first_code, second_code), (0, 0))
        self.assertGreaterEqual(float(self.mark("b", "start").read_text()),
                                float(self.mark("a", "end").read_text()))
        self.assertEqual(len(WAITED_PATTERN.findall(second_err)), 1)
        self.assertEqual(second_err.splitlines().count(WAITING_LINE.format(count=1)), 1)
        self.assertNotIn("verify-slot:", first_err)

    def test_the_declared_count_admits_that_many_runs_at_once(self):
        self.declare(verify_slots=2)
        first = self.start("a")
        second = self.start("b")
        self.assertTrue(wait_for(self.mark("a", "start")))
        self.assertTrue(wait_for(self.mark("b", "start")))
        self.release("a")
        self.release("b")
        for proc in (first, second):
            code, err = self.finish(proc)
            self.assertEqual(code, 0)
            self.assertIsNone(WAITED_PATTERN.search(err))

    def test_a_slot_held_by_a_killed_process_is_given_back(self):
        first = self.start("a")
        self.assertTrue(wait_for(self.mark("a", "start")))
        os.kill(first.pid, signal.SIGKILL)
        first.wait()
        second = self.start("b", "--wait-limit", "10")
        self.assertTrue(wait_for(self.mark("b", "start"), timeout=10))
        self.assertTrue(process_alive(int(self.mark("a", "pid").read_text())))
        self.release("b")
        code, _ = self.finish(second)
        self.assertEqual(code, 0)

    def test_a_live_holder_is_never_preempted(self):
        first = self.start("a")
        self.assertTrue(wait_for(self.mark("a", "start")))
        second = self.start("b", "--wait-limit", "1")
        code, err = self.finish(second)
        self.assertEqual(code, NO_SLOT_EXIT)
        self.assertIn(NO_SLOT_LINE.format(limit=1), err.splitlines())
        self.assertFalse(self.mark("b", "start").exists())
        self.assertTrue(process_alive(int(self.mark("a", "pid").read_text())))
        self.release("a")
        first_code, _ = self.finish(first)
        self.assertEqual(first_code, 0)
        self.assertTrue(self.mark("a", "end").exists())

    def test_the_childs_exit_is_returned_and_the_slot_freed(self):
        self.release("a")
        self.release("b")
        first_code, _ = self.finish(self.start("a", code=3))
        second_code, err = self.finish(self.start("b", "--wait-limit", "1"))
        self.assertEqual((first_code, second_code), (3, 0))
        self.assertIsNone(WAITED_PATTERN.search(err))
        self.assertNotIn(WAITING_LINE.format(count=1), err)

    def test_a_terminated_holder_ends_its_child_and_frees_the_slot(self):
        first = self.start("a")
        self.assertTrue(wait_for(self.mark("a", "start")))
        child_pid = int(self.mark("a", "pid").read_text())
        os.kill(first.pid, signal.SIGTERM)
        first.communicate(timeout=20)
        self.assertEqual(first.returncode, 143)
        deadline = time.monotonic() + 5
        while process_alive(child_pid) and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertFalse(process_alive(child_pid))
        self.release("b")
        code, _ = self.finish(self.start("b", "--wait-limit", "5"))
        self.assertEqual(code, 0)

    def test_an_invalid_declaration_runs_nothing(self):
        self.declare(verify_slots=0)
        code, err = self.finish(self.start("a"))
        self.assertEqual(code, 2)
        self.assertFalse(self.mark("a", "start").exists())
        self.assertTrue(err.strip())

    def test_a_child_that_cannot_start_or_no_child_is_refused(self):
        missing_code, _ = self.finish(self.start("x", argv=["/nonexistent/program"]))
        empty = subprocess.run(
            [sys.executable, "-m", "agent_tools.delivery.verify_slot", "run", "--"],
            env={**os.environ, "HOME": self.home, "PYTHONPATH": str(REPO_ROOT / "python")},
            cwd=self.home, capture_output=True, text=True, check=False)
        self.release("b")
        code, err = self.finish(self.start("b", "--wait-limit", "1"))
        self.assertEqual(missing_code, 127)
        self.assertEqual(empty.returncode, 2)
        self.assertEqual(code, 0)
        self.assertIsNone(WAITED_PATTERN.search(err))


if __name__ == "__main__":
    unittest.main()
