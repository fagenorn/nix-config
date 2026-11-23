"""The verify-slot command (#1383): a host-wide verify slot held by flock while a command runs.

Run: just agent-workflow-tests
"""

import fcntl
import json
import os
import re
import signal
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from agent_tools.delivery import verify_slot
from agent_tools.delivery.verify_slot import NO_SLOT_EXIT, NO_SLOT_LINE, SLOT_DIR_ENV, WAITING_LINE
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
        self.slots = Path(self.home) / "slots"
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

    def env(self, home=None):
        return {**os.environ, "HOME": home or self.home, "PYTHONPATH": str(REPO_ROOT / "python"),
                SLOT_DIR_ENV: str(self.slots)}

    def start(self, name, *opts, code=None, argv=None, home=None, cwd=None):
        tail = [str(code)] if code is not None else []
        command = argv if argv is not None else [
            sys.executable, "-c", CHILD, str(self.marks), name, *tail]
        proc = subprocess.Popen(
            [sys.executable, "-m", "agent_tools.delivery.verify_slot", "run", *opts, "--", *command],
            env=self.env(home), cwd=cwd or self.home, stderr=subprocess.PIPE, text=True)
        self.procs.append(proc)
        return proc

    def repository(self, name, url=None):
        directory = Path(self.home) / "repos" / name
        directory.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", "-q", str(directory)], check=True, capture_output=True)
        if url is not None:
            subprocess.run(["git", "-C", str(directory), "remote", "add", "origin", url],
                           check=True, capture_output=True)
        return directory

    def mark(self, name, suffix):
        return self.marks / f"{name}.{suffix}"

    def release(self, name):
        self.mark(name, "release").write_text("")

    def finish(self, proc, timeout=30):
        _, err = proc.communicate(timeout=timeout)
        return proc.returncode, err

    def test_a_second_run_from_the_same_repository_waits_until_the_first_ends(self):
        self.declare(verify_slots=2)
        one = self.repository("alpha-one", "git@github.com:example/alpha.git")
        two = self.repository("alpha-two", "https://github.com/Example/alpha")
        first = self.start("a", cwd=one)
        self.assertTrue(wait_for(self.mark("a", "start")))
        second = self.start("b", cwd=two)
        time.sleep(1.5)
        self.assertFalse(self.mark("b", "start").exists())
        self.release("a")
        first_code, _ = self.finish(first)
        self.assertTrue(wait_for(self.mark("b", "start")))
        self.release("b")
        second_code, second_err = self.finish(second)
        self.assertEqual((first_code, second_code), (0, 0))
        self.assertGreaterEqual(float(self.mark("b", "start").read_text()),
                                float(self.mark("a", "end").read_text()))
        self.assertEqual(second_err.splitlines().count(verify_slot.SAME_REPOSITORY_LINE), 1)
        self.assertEqual(len(WAITED_PATTERN.findall(second_err)), 1)
        self.assertNotIn(WAITING_LINE.format(count=2), second_err.splitlines())

    def test_runs_from_different_repositories_hold_slots_together(self):
        self.declare(verify_slots=2)
        alpha = self.repository("alpha", "git@github.com:example/alpha.git")
        beta = self.repository("beta", "git@github.com:example/beta.git")
        first = self.start("a", cwd=alpha)
        second = self.start("b", cwd=beta)
        self.assertTrue(wait_for(self.mark("a", "start")))
        self.assertTrue(wait_for(self.mark("b", "start")))
        self.release("a")
        self.release("b")
        for proc in (first, second):
            code, err = self.finish(proc)
            self.assertEqual(code, 0)
            self.assertIsNone(WAITED_PATTERN.search(err))
            self.assertNotIn(verify_slot.SAME_REPOSITORY_LINE, err)

    def test_runs_outside_a_repository_are_each_their_own_group(self):
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

    def test_a_same_repository_waiter_leaves_the_free_slot_to_another_repository(self):
        self.declare(verify_slots=2)
        one = self.repository("alpha-one", "git@github.com:example/alpha.git")
        two = self.repository("alpha-two", "https://github.com/Example/alpha")
        beta = self.repository("beta", "git@github.com:example/beta.git")
        first = self.start("a", cwd=one)
        self.assertTrue(wait_for(self.mark("a", "start")))
        second = self.start("b", cwd=two)
        time.sleep(1.0)
        third = self.start("c", cwd=beta)
        self.assertTrue(wait_for(self.mark("c", "start")))
        self.assertFalse(self.mark("b", "start").exists())
        for name in ("a", "b", "c"):
            self.release(name)
        for proc in (first, second, third):
            self.assertEqual(self.finish(proc)[0], 0)

    def test_a_killed_holder_gives_back_its_repository(self):
        self.declare(verify_slots=2)
        one = self.repository("alpha-one", "git@github.com:example/alpha.git")
        two = self.repository("alpha-two", "https://github.com/Example/alpha")
        first = self.start("a", cwd=one)
        self.assertTrue(wait_for(self.mark("a", "start")))
        first.kill()
        first.wait()
        second = self.start("b", cwd=two)
        self.assertTrue(wait_for(self.mark("b", "start")))
        self.assertTrue(process_alive(int(self.mark("a", "pid").read_text())))
        self.release("a")
        self.release("b")
        self.assertEqual(self.finish(second)[0], 0)

    def test_a_live_run_waits_for_a_running_holder_of_its_repository(self):
        self.declare(verify_slots=2)
        one = self.repository("alpha-one", "git@github.com:example/alpha.git")
        two = self.repository("alpha-two", "https://github.com/Example/alpha")
        first = self.start("a", cwd=one)
        self.assertTrue(wait_for(self.mark("a", "start")))
        second = self.start("b", "--live", cwd=two)
        time.sleep(1.5)
        self.assertFalse(self.mark("b", "start").exists())
        self.release("a")
        self.assertTrue(wait_for(self.mark("b", "start")))
        self.release("b")
        self.assertEqual((self.finish(first)[0], self.finish(second)[0]), (0, 0))
        self.assertGreaterEqual(float(self.mark("b", "start").read_text()),
                                float(self.mark("a", "end").read_text()))

    def test_the_repository_group_is_the_normalized_origin_remote(self):
        scp = self.repository("scp", "git@github.com:Example/Alpha.git")
        https = self.repository("https", "https://github.com/example/alpha")
        ssh = self.repository("ssh", "ssh://git@github.com/example/alpha.git")
        beta = self.repository("beta", "git@github.com:example/beta.git")
        local = self.repository("local", "/srv/git/Alpha.git")
        bare = self.repository("bare")
        (scp / "sub").mkdir()
        plain = Path(self.home) / "plain"
        plain.mkdir()
        group = verify_slot.repository_group
        for path in (scp, https, ssh, scp / "sub"):
            self.assertEqual(group(path), "example/alpha")
        self.assertEqual(group(beta), "example/beta")
        self.assertEqual(group(local), "/srv/git/alpha.git")
        self.assertIsNone(group(bare))
        self.assertIsNone(group(plain))
        self.assertNotEqual(verify_slot.group_lock_name("example/alpha"),
                            verify_slot.group_lock_name("example/beta"))
        self.assertFalse(Path(verify_slot.group_lock_name("example/alpha")).match("slot-*.lock"))

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

    def test_a_live_run_started_last_takes_the_freed_slot_before_the_ordinary_waiters(self):
        first = self.start("a")
        self.assertTrue(wait_for(self.mark("a", "start")))
        for name in ("b", "c", "d"):
            self.release(name)
        waiting = WAITING_LINE.format(count=1)
        second = self.start("b")
        self.assertEqual(second.stderr.readline().rstrip("\n"), waiting)
        third = self.start("c")
        self.assertEqual(third.stderr.readline().rstrip("\n"), waiting)
        live = self.start("d", "--live")
        self.assertEqual(live.stderr.readline().rstrip("\n"), waiting)
        self.release("a")
        codes = [self.finish(proc) for proc in (first, second, third, live)]
        self.assertEqual([code for code, _ in codes], [0, 0, 0, 0])
        self.assertGreaterEqual(float(self.mark("d", "start").read_text()),
                                float(self.mark("a", "end").read_text()))
        live_end = float(self.mark("d", "end").read_text())
        self.assertLessEqual(live_end, float(self.mark("b", "start").read_text()))
        self.assertLessEqual(live_end, float(self.mark("c", "start").read_text()))
        self.assertEqual(len(WAITED_PATTERN.findall(codes[3][1])), 1)
        marker = self.slots / verify_slot.LIVE_MARKER
        self.assertEqual(stat.S_IMODE(os.stat(marker).st_mode), 0o666)

    def test_a_live_run_never_stops_a_run_in_progress(self):
        first = self.start("a")
        self.assertTrue(wait_for(self.mark("a", "start")))
        code, err = self.finish(self.start("d", "--live", "--wait-limit", "1"))
        self.assertEqual(code, NO_SLOT_EXIT)
        self.assertIn(NO_SLOT_LINE.format(limit=1), err.splitlines())
        self.assertFalse(self.mark("d", "start").exists())
        self.assertTrue(process_alive(int(self.mark("a", "pid").read_text())))
        self.release("a")
        self.assertEqual(self.finish(first)[0], 0)
        self.assertTrue(self.mark("a", "end").exists())

    def test_an_ordinary_run_defers_to_a_waiting_live_run_even_with_a_free_slot(self):
        self.slots.mkdir(parents=True)
        marker = os.open(self.slots / verify_slot.LIVE_MARKER, os.O_RDWR | os.O_CREAT, 0o666)
        fcntl.flock(marker, fcntl.LOCK_SH)
        self.release("b")
        self.release("c")
        try:
            code, err = self.finish(self.start("b", "--wait-limit", "1"))
        finally:
            os.close(marker)
        later_code, later_err = self.finish(self.start("c", "--wait-limit", "5"))
        self.assertEqual(code, NO_SLOT_EXIT)
        self.assertFalse(self.mark("b", "start").exists())
        self.assertEqual(err.splitlines().count(verify_slot.DEFERRING_LINE), 1)
        self.assertNotIn(WAITING_LINE.format(count=1), err)
        self.assertEqual(later_code, 0)
        self.assertNotIn(verify_slot.DEFERRING_LINE, later_err)

    def test_a_live_run_stays_within_its_wait_limit_while_an_ordinary_probe_is_stalled(self):
        self.slots.mkdir(parents=True)
        probe = os.open(self.slots / verify_slot.LIVE_MARKER, os.O_RDWR | os.O_CREAT, 0o666)
        fcntl.flock(probe, fcntl.LOCK_EX)
        self.release("d")
        try:
            started = time.monotonic()
            code, err = self.finish(self.start("d", "--live", "--wait-limit", "1"), timeout=6)
            elapsed = time.monotonic() - started
        finally:
            os.close(probe)
        self.assertEqual(code, NO_SLOT_EXIT)
        self.assertIn(NO_SLOT_LINE.format(limit=1), err.splitlines())
        self.assertLess(elapsed, 5)
        self.assertFalse(self.mark("d", "start").exists())

    def test_an_unusable_marker_is_a_setup_error_and_frees_the_slot(self):
        self.slots.mkdir(parents=True)
        (self.slots / verify_slot.LIVE_MARKER).mkdir()
        code, err = self.finish(self.start("b", "--wait-limit", "1"))
        self.assertEqual(code, 2)
        self.assertIn("verify-slot: cannot take a slot", err)
        self.assertFalse(self.mark("b", "start").exists())
        slot = os.open(self.slots / "slot-0.lock", os.O_RDWR)
        self.addCleanup(os.close, slot)
        fcntl.flock(slot, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def test_concurrent_ordinary_probes_do_not_defer_to_each_other(self):
        self.slots.mkdir(parents=True)
        marker = os.open(self.slots / verify_slot.LIVE_MARKER, os.O_RDWR | os.O_CREAT, 0o666)
        guard = os.open(self.slots / verify_slot.LIVE_PROBE, os.O_RDWR | os.O_CREAT, 0o666)
        fcntl.flock(guard, fcntl.LOCK_EX)
        fcntl.flock(marker, fcntl.LOCK_EX)
        self.release("b")
        proc = self.start("b", "--wait-limit", "10")
        try:
            time.sleep(0.7)
        finally:
            os.close(marker)
            os.close(guard)
        code, err = self.finish(proc)
        self.assertEqual(code, 0)
        self.assertTrue(self.mark("b", "start").exists())
        self.assertNotIn(verify_slot.DEFERRING_LINE, err)

    def test_an_ordinary_run_goes_on_once_the_live_waiter_is_gone(self):
        first = self.start("a")
        self.assertTrue(wait_for(self.mark("a", "start")))
        live = self.start("d", "--live")
        self.assertEqual(live.stderr.readline().rstrip("\n"), WAITING_LINE.format(count=1))
        os.kill(live.pid, signal.SIGKILL)
        live.wait()
        live.stderr.close()
        self.release("b")
        second = self.start("b", "--wait-limit", "10")
        self.release("a")
        self.finish(first)
        code, err = self.finish(second)
        self.assertEqual(code, 0)
        self.assertTrue(self.mark("b", "start").exists())
        self.assertNotIn(verify_slot.DEFERRING_LINE, err)
        self.assertFalse(self.mark("d", "start").exists())

    def test_a_live_run_holding_a_slot_holds_back_no_ordinary_run(self):
        self.declare(verify_slots=2)
        live = self.start("d", "--live")
        self.assertTrue(wait_for(self.mark("d", "start")))
        self.release("b")
        code, err = self.finish(self.start("b", "--wait-limit", "5"))
        self.assertEqual(code, 0)
        self.assertTrue(self.mark("b", "start").exists())
        self.assertNotIn(verify_slot.DEFERRING_LINE, err)
        self.release("d")
        self.assertEqual(self.finish(live)[0], 0)

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
            env=self.env(), cwd=self.home, capture_output=True, text=True, check=False)
        self.release("b")
        code, err = self.finish(self.start("b", "--wait-limit", "1"))
        self.assertEqual(missing_code, 127)
        self.assertEqual(empty.returncode, 2)
        self.assertEqual(code, 0)
        self.assertIsNone(WAITED_PATTERN.search(err))

    def test_runs_of_different_accounts_on_one_host_share_the_slots(self):
        """VS-01: the slots are the host's, so two accounts with different homes cannot both hold one."""
        other = Path(self.home) / "other-account"
        other.mkdir()
        first = self.start("a")
        self.assertTrue(wait_for(self.mark("a", "start")))
        second = self.start("b", "--wait-limit", "1", home=str(other))
        code, err = self.finish(second)
        self.assertEqual(code, NO_SLOT_EXIT)
        self.assertIn(NO_SLOT_LINE.format(limit=1), err.splitlines())
        self.assertFalse(self.mark("b", "start").exists())
        self.release("a")
        self.assertEqual(self.finish(first)[0], 0)

    def test_the_default_slot_directory_does_not_depend_on_home(self):
        homes = [Path(self.home) / "one", Path(self.home) / "two"]
        env = {key: value for key, value in self.env().items() if key != SLOT_DIR_ENV}
        found = []
        for home in homes:
            home.mkdir()
            done = subprocess.run(
                [sys.executable, "-c",
                 "from agent_tools.delivery import verify_slot; print(verify_slot.slot_dir())"],
                env={**env, "HOME": str(home)}, capture_output=True, text=True, check=True)
            found.append(Path(done.stdout.strip()))
        self.assertEqual(found[0], found[1])
        self.assertTrue(found[0].is_absolute())
        for home in homes:
            self.assertNotIn(home, found[0].parents)

    def test_a_lowered_count_still_counts_the_holders_of_the_higher_slots(self):
        """VS-02: with count 2 -> 1 and slot-1 still held, a new run waits though slot-0 is free."""
        self.declare(verify_slots=2)
        first = self.start("a")
        second = self.start("b")
        self.assertTrue(wait_for(self.mark("a", "start")))
        self.assertTrue(wait_for(self.mark("b", "start")))
        self.release("a")
        self.assertEqual(self.finish(first)[0], 0)
        declaration = Path(self.home) / ".agents/share/host-declaration.json"
        declaration.write_text(json.dumps({**json.loads(declaration.read_text()), "verify_slots": 1}))
        self.release("c")
        third = self.start("c", "--wait-limit", "1")
        code, err = self.finish(third)
        self.assertFalse(self.mark("c", "start").exists())
        self.assertEqual(code, NO_SLOT_EXIT)
        self.assertIn(NO_SLOT_LINE.format(limit=1), err.splitlines())
        self.release("b")
        self.assertEqual(self.finish(second)[0], 0)

    def test_a_waiter_that_wakes_after_its_limit_does_not_take_a_slot_freed_after_it(self):
        """VS-04: the deadline is checked before another try, so a late wake-up times out."""
        first = self.start("a")
        self.assertTrue(wait_for(self.mark("a", "start")))
        self.release("b")
        second = self.start("b", "--wait-limit", "1")
        self.assertEqual(second.stderr.readline().rstrip("\n"), WAITING_LINE.format(count=1))
        os.kill(second.pid, signal.SIGSTOP)
        time.sleep(1.3)
        self.release("a")
        self.assertEqual(self.finish(first)[0], 0)
        os.kill(second.pid, signal.SIGCONT)
        code, err = self.finish(second)
        self.assertFalse(self.mark("b", "start").exists())
        self.assertEqual(code, NO_SLOT_EXIT)
        self.assertIn(NO_SLOT_LINE.format(limit=1), err.splitlines())

    def test_a_declaration_that_is_not_a_file_is_a_setup_error_not_a_missing_one(self):
        target = Path(self.home) / ".agents/share/host-declaration.json"
        target.parent.mkdir(parents=True)
        for label, make in (("directory", lambda: target.mkdir()),
                            ("dangling symlink", lambda: target.symlink_to(Path(self.home) / "nowhere"))):
            with self.subTest(label):
                make()
                code, err = self.finish(self.start("x"))
                self.assertEqual(code, 2)
                self.assertFalse(self.mark("x", "start").exists())
                self.assertTrue(err.strip())
                if target.is_dir():
                    target.rmdir()
                else:
                    target.unlink()


if __name__ == "__main__":
    unittest.main()
