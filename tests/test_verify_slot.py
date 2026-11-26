"""The verify-slot command (#1383): a host-wide verify slot held by flock while a command runs.

Run: just agent-workflow-tests
"""

import fcntl
import itertools
import json
import os
import re
import select
import signal
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from agent_tools.canonical import parse_rfc3339_utc
from agent_tools.delivery import comment_lint, never_rise, verify_history, verify_queue, verify_slot
from agent_tools.delivery.verify_slot import (
    NO_SLOT_EXIT, NO_SLOT_LINE, PLACE_LINE, QUEUED_LINE, REPORT_SKIPPED_LINE, SAME_REPOSITORY_LINE,
    SLOT_DIR_ENV, WAITING_LINE)
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


PLACE_PATTERN = re.compile(
    r"^verify-slot: this run is number (\d+) in line for a verify slot; now running: (.*)$")
COMMAND = " ".join(f"{sys.executable} -c {CHILD}".split()[:3])


def places(err):
    """The places of the place lines in `err`, in order."""
    return [int(match.group(1)) for line in err.splitlines() if (match := PLACE_PATTERN.match(line))]


def read_line(proc, end):
    """One stderr line of a running process, read byte by byte so nothing is buffered ahead."""
    descriptor = proc.stderr.fileno()
    data = b""
    while True:
        remaining = end - time.monotonic()
        if remaining <= 0 or not select.select([descriptor], [], [], remaining)[0]:
            raise AssertionError(f"no stderr line before the deadline; read so far: {data!r}")
        byte = os.read(descriptor, 1)
        if not byte:
            raise AssertionError(f"stderr closed; read so far: {data!r}")
        if byte == b"\n":
            return data.decode()
        data += byte


def read_until(proc, predicate, deadline=20):
    """Read stderr lines of a running process until one satisfies `predicate`; every line read."""
    end = time.monotonic() + deadline
    lines = []
    while True:
        lines.append(read_line(proc, end))
        if predicate(lines[-1]):
            return lines


def is_place(place=None, holders=None):
    def predicate(line):
        match = PLACE_PATTERN.match(line)
        return bool(match) and (place is None or int(match.group(1)) == place) and (
            holders is None or holders(match.group(2)))
    return predicate


def read_place(proc, deadline=20):
    """The place, the holders text and the lines read up to the first place line."""
    lines = read_until(proc, is_place(), deadline)
    match = PLACE_PATTERN.match(lines[-1])
    return int(match.group(1)), match.group(2), lines


def wait_for(path, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return True
        time.sleep(0.02)
    return False


class SlotHarness:
    """The scratch slot directory and the run helpers both test classes share."""

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
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass

    def declare(self, **extra):
        target = Path(self.home) / ".agents/share/host-declaration.json"
        target.parent.mkdir(parents=True)
        declaration = json.loads(COMMITTED_DECLARATION.read_text())
        declaration.update(extra)
        target.write_text(json.dumps(declaration))

    def env(self, home=None, owner=None):
        env = {key: value for key, value in os.environ.items() if key != "CLAUDE_CODE_SESSION_ID"}
        if owner is not None:
            env["CLAUDE_CODE_SESSION_ID"] = owner
        return {**env, "HOME": home or self.home, "PYTHONPATH": str(REPO_ROOT / "python"),
                SLOT_DIR_ENV: str(self.slots)}

    def start(self, name, *opts, code=None, argv=None, home=None, cwd=None, owner=None):
        tail = [str(code)] if code is not None else []
        command = argv if argv is not None else [
            sys.executable, "-c", CHILD, str(self.marks), name, *tail]
        proc = subprocess.Popen(
            [sys.executable, "-m", "agent_tools.delivery.verify_slot", "run", *opts, "--", *command],
            env=self.env(home, owner), cwd=cwd or self.home, stderr=subprocess.PIPE, text=True)
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

    def history(self):
        text = (self.slots / "history.jsonl").read_text()
        return [json.loads(line) for line in text.splitlines()]


class VerifySlotTest(SlotHarness, unittest.TestCase):
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
        plain = Path(self.home) / "not-a-repository"
        plain.mkdir()
        first = self.start("a", cwd=plain)
        second = self.start("b", cwd=plain)
        self.assertTrue(wait_for(self.mark("a", "start")))
        self.assertTrue(wait_for(self.mark("b", "start")))
        self.release("a")
        self.release("b")
        for proc in (first, second):
            code, err = self.finish(proc)
            self.assertEqual(code, 0)
            self.assertNotIn(verify_slot.SAME_REPOSITORY_LINE, err)

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

    def test_the_cleanup_tolerates_a_child_that_exits_between_its_check_and_its_kill(self):
        gone = subprocess.Popen([sys.executable, "-c", "pass"])
        gone.wait()
        self.mark("gone", "pid").write_text(str(gone.pid))
        with mock.patch(f"{__name__}.process_alive", return_value=True):
            self.reap()

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

    def test_a_trailing_slash_on_the_origin_url_does_not_change_the_repository(self):
        urls = ("https://github.com/Example/alpha.git/", "https://github.com/example/alpha/",
                "git@github.com:example/alpha.git/", "ssh://git@github.com/example/alpha.git//")
        for number, url in enumerate(urls):
            self.assertEqual(verify_slot.repository_group(self.repository(f"slash-{number}", url)),
                             "example/alpha")

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
            self.assertNotIn("verify-slot:", err)

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
        self.assertEqual(places(live.stderr.readline()), [1])
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


    def test_waiters_take_a_freed_slot_in_arrival_order(self):
        first = self.start("a")
        self.assertTrue(wait_for(self.mark("a", "start")))
        for name in ("b", "c", "d"):
            self.release(name)
        procs, first_places = [first], []
        for name in ("b", "c", "d"):
            proc = self.start(name)
            procs.append(proc)
            first_places.append(read_place(proc)[0])
        self.assertEqual(first_places, [1, 2, 3])
        self.release("a")
        self.assertEqual([self.finish(proc)[0] for proc in procs], [0, 0, 0, 0])
        for earlier, later in (("a", "b"), ("b", "c"), ("c", "d")):
            self.assertGreaterEqual(float(self.mark(later, "start").read_text()),
                                    float(self.mark(earlier, "end").read_text()))

    def test_three_runs_of_one_repository_and_one_of_another_share_two_slots_in_order(self):
        self.declare(verify_slots=2)
        one = self.repository("alpha-one", "git@github.com:example/alpha.git")
        two = self.repository("alpha-two", "https://github.com/Example/alpha")
        three = self.repository("alpha-three", "ssh://git@github.com/example/alpha.git")
        beta = self.repository("beta", "git@github.com:example/beta.git")
        first = self.start("a1", cwd=one)
        self.assertTrue(wait_for(self.mark("a1", "start")))
        second = self.start("a2", cwd=two)
        place, holders, lines = read_place(second)
        self.assertEqual((lines[0], place, holders), (SAME_REPOSITORY_LINE, 1, f"example/alpha ({COMMAND})"))
        self.assertEqual(lines[-1], PLACE_LINE.format(place=1, holders=f"example/alpha ({COMMAND})"))
        third = self.start("a3", cwd=three)
        self.assertEqual(read_place(third)[0], 2)
        other = self.start("b", cwd=beta)
        self.assertTrue(wait_for(self.mark("b", "start")))
        self.assertFalse(self.mark("a1", "end").exists())
        both = {f"example/alpha ({COMMAND})", f"example/beta ({COMMAND})"}
        read_until(second, is_place(1, lambda text: set(text.split(", ")) == both))
        self.release("b")
        self.release("a1")
        self.assertTrue(wait_for(self.mark("a2", "start")))
        self.assertGreaterEqual(float(self.mark("a2", "start").read_text()),
                                float(self.mark("a1", "end").read_text()))
        read_until(third, is_place(1))
        self.release("a2")
        self.assertTrue(wait_for(self.mark("a3", "start")))
        self.assertGreaterEqual(float(self.mark("a3", "start").read_text()),
                                float(self.mark("a2", "end").read_text()))
        self.release("a3")
        for proc in (first, second, third):
            self.assertEqual(self.finish(proc)[0], 0)
        other_code, other_err = self.finish(other)
        self.assertEqual(other_code, 0)
        self.assertNotIn("verify-slot:", other_err)

    def test_a_live_run_held_back_by_its_repository_leaves_a_free_slot_to_another_repository(self):
        self.declare(verify_slots=2)
        one = self.repository("alpha-one", "git@github.com:example/alpha.git")
        two = self.repository("alpha-two", "https://github.com/Example/alpha")
        beta = self.repository("beta", "git@github.com:example/beta.git")
        first = self.start("a", cwd=one)
        self.assertTrue(wait_for(self.mark("a", "start")))
        live = self.start("b", "--live", cwd=two)
        place, _, lines = read_place(live)
        self.assertEqual((lines[0], place), (SAME_REPOSITORY_LINE, 1))
        other = self.start("c", cwd=beta)
        self.assertTrue(wait_for(self.mark("c", "start")))
        self.assertFalse(self.mark("a", "end").exists())
        self.release("c")
        self.release("a")
        other_code, other_err = self.finish(other)
        self.assertEqual(other_code, 0)
        self.assertNotIn(verify_slot.DEFERRING_LINE, other_err)
        self.assertTrue(wait_for(self.mark("b", "start")))
        self.assertGreaterEqual(float(self.mark("b", "start").read_text()),
                                float(self.mark("a", "end").read_text()))
        self.release("b")
        self.assertEqual((self.finish(first)[0], self.finish(live)[0]), (0, 0))

    def test_two_free_slots_go_to_the_waiters_one_at_a_time_in_order(self):
        self.declare(verify_slots=2)
        holders = [self.start("x"), self.start("y")]
        self.assertTrue(wait_for(self.mark("x", "start")))
        self.assertTrue(wait_for(self.mark("y", "start")))
        second = self.start("b")
        self.assertEqual(read_place(second)[0], 1)
        os.kill(second.pid, signal.SIGSTOP)
        third = self.start("c")
        self.assertEqual(read_place(third)[0], 2)
        self.release("x")
        self.release("y")
        self.assertTrue(wait_for(self.mark("x", "end")))
        self.assertTrue(wait_for(self.mark("y", "end")))
        time.sleep(2)
        self.assertFalse(self.mark("c", "start").exists())
        os.kill(second.pid, signal.SIGCONT)
        self.assertTrue(wait_for(self.mark("b", "start")))
        self.assertTrue(wait_for(self.mark("c", "start")))
        self.release("b")
        self.release("c")
        for proc in (*holders, second, third):
            self.assertEqual(self.finish(proc)[0], 0)

    def test_a_holder_without_a_description_still_holds_back_its_repository(self):
        self.declare(verify_slots=2)
        one = self.repository("alpha-one", "git@github.com:example/alpha.git")
        beta = self.repository("beta", "git@github.com:example/beta.git")
        self.slots.mkdir()
        old = [verify_queue.open_shared(self.slots / "slot-0.lock"),
               verify_queue.open_shared(self.slots / verify_slot.group_lock_name("example/alpha"))]
        try:
            for descriptor in old:
                fcntl.flock(descriptor, fcntl.LOCK_EX)
            first = self.start("a", cwd=one)
            _, holders, lines = read_place(first)
            self.assertEqual((lines[0], holders), (SAME_REPOSITORY_LINE, "a verify run"))
            other = self.start("b", cwd=beta)
            self.assertTrue(wait_for(self.mark("b", "start")))
            self.assertFalse(self.mark("a", "start").exists())
        finally:
            for descriptor in old:
                os.close(descriptor)
        self.assertTrue(wait_for(self.mark("a", "start")))
        self.release("a")
        self.release("b")
        self.assertEqual((self.finish(first)[0], self.finish(other)[0]), (0, 0))

    def test_a_repository_limit_of_two_lets_two_runs_of_one_repository_hold_their_locks(self):
        self.slots.mkdir()
        group = "example/alpha"
        taken = []
        self.addCleanup(lambda: [os.close(fd) for fd in taken])

        def take(limit):
            held, reason = verify_slot._try_slots(self.slots, 3, True, group, limit)
            if held is not None:
                taken.extend(fd for fd in held if fd is not None)
            return held, reason

        first, second = take(2), take(2)
        for held, reason in (first, second):
            self.assertIsNone(reason)
            self.assertIsNotNone(held[0])
            self.assertIsNotNone(held[1])
        self.assertEqual(take(2), (None, "same_repository"))
        while taken:
            os.close(taken.pop())
        held, reason = take(1)
        self.assertIsNone(reason)
        self.assertIsNotNone(held[1])
        self.assertEqual(take(1), (None, "same_repository"))

    def test_a_repository_declared_two_runs_two_at_once_and_an_unnamed_one_runs_one(self):
        self.declare(verify_slots=5, verify_repository_slots={"example/alpha": 2, "example/beta": 1})
        urls = {"alpha-one": "git@github.com:example/alpha.git", "alpha-two": "https://github.com/Example/alpha",
                "alpha-three": "ssh://git@github.com/example/alpha.git", "beta-one": "git@github.com:example/beta.git",
                "beta-two": "git@github.com:example/beta.git", "gamma-one": "git@github.com:example/gamma.git",
                "gamma-two": "git@github.com:example/gamma.git"}
        where = {name: self.repository(name, url) for name, url in urls.items()}
        runs = {name: self.start(name, cwd=where[repo]) for name, repo in (
            ("a1", "alpha-one"), ("a2", "alpha-two"), ("b1", "beta-one"), ("g1", "gamma-one"))}
        for name in runs:
            self.assertTrue(wait_for(self.mark(name, "start")))
        for name, repo in (("a3", "alpha-three"), ("b2", "beta-two"), ("g2", "gamma-two")):
            runs[name] = self.start(name, cwd=where[repo])
            self.assertEqual(read_place(runs[name])[2][0], SAME_REPOSITORY_LINE)
            self.assertFalse(self.mark(name, "start").exists())
        runs["a1"].kill()
        runs["a1"].wait()
        self.assertTrue(wait_for(self.mark("a3", "start")))
        self.assertFalse(self.mark("a1", "end").exists())
        for name in ("b1", "g1"):
            self.release(name)
        for name in ("b2", "g2"):
            self.assertTrue(wait_for(self.mark(name, "start")))
        for name in runs:
            self.release(name)
        for name, proc in runs.items():
            if name != "a1":
                self.assertEqual(self.finish(proc)[0], 0)

    def test_a_declared_limit_far_above_the_slot_count_still_leaves_a_ticket_every_reader_parses(self):
        self.declare(verify_slots=2, verify_repository_slots={"example/alpha": 10**4096})
        where = {name: self.repository(name, f"git@github.com:example/{name}.git")
                 for name in ("alpha", "beta", "gamma")}
        holders = [self.start("b", cwd=where["beta"]), self.start("g", cwd=where["gamma"])]
        for name in ("b", "g"):
            self.assertTrue(wait_for(self.mark(name, "start")))
        waiter = self.start("a", cwd=where["alpha"])
        read_place(waiter)
        tickets = [verify_queue.open_shared(path) for path in self.slots.glob("ticket-*.lock")]
        try:
            limits = [verify_queue._parse(descriptor) for descriptor in tickets]
        finally:
            for descriptor in tickets:
                os.close(descriptor)
        self.assertEqual([record["repository_limit"] for record in limits], [2])
        for name in ("b", "g", "a"):
            self.release(name)
        for proc in (*holders, waiter):
            self.assertEqual(self.finish(proc)[0], 0)

    def test_a_live_run_under_its_repositorys_declared_limit_waits_ahead_without_being_held_back(self):
        self.declare(verify_slots=2, verify_repository_slots={"example/alpha": 2})
        where = {name: self.repository(name, f"git@github.com:example/{name.split('-')[0]}.git")
                 for name in ("alpha-one", "alpha-two", "beta", "gamma")}
        first, beta = self.start("a1", cwd=where["alpha-one"]), self.start("b", cwd=where["beta"])
        for name in ("a1", "b"):
            self.assertTrue(wait_for(self.mark(name, "start")))
        ordinary = self.start("c", cwd=where["gamma"])
        read_place(ordinary)
        live = self.start("a2", "--live", cwd=where["alpha-two"])
        place, _, lines = read_place(live)
        self.assertEqual((lines[0], place), (WAITING_LINE.format(count=2), 1))
        self.release("b")
        self.assertTrue(wait_for(self.mark("a2", "start")))
        self.assertFalse(self.mark("c", "start").exists())
        self.release("a1")
        self.assertTrue(wait_for(self.mark("c", "start")))
        self.release("a2")
        self.release("c")
        for proc in (first, beta, live, ordinary):
            self.assertEqual(self.finish(proc)[0], 0)

    def test_an_older_waiter_held_back_by_its_repository_leaves_the_free_slot_to_another_repository(self):
        self.declare(verify_slots=2, verify_repository_slots={"example/alpha": 2})
        alpha = self.repository("alpha", "git@github.com:example/alpha.git")
        beta = self.repository("beta", "git@github.com:example/beta.git")
        first = self.start("a1", cwd=alpha)
        self.assertTrue(wait_for(self.mark("a1", "start")))
        ticket = self.slots / "ticket-000000000100.lock"
        older = verify_queue.open_shared(ticket)
        try:
            fcntl.flock(older, fcntl.LOCK_EX | fcntl.LOCK_NB)
            os.write(older, json.dumps({"key": "older", "live": False, "repository": "example/alpha",
                                        "reserved_until": None}).encode())
            other = self.start("b", cwd=beta)
            self.assertTrue(wait_for(self.mark("b", "start")))
            self.assertTrue(ticket.exists())
        finally:
            os.close(older)
        self.release("a1")
        self.release("b")
        self.assertEqual((self.finish(first)[0], self.finish(other)[0]), (0, 0))

    def test_a_holder_of_a_higher_repository_lock_holds_back_a_repository_whose_limit_fell(self):
        self.declare(verify_slots=2, verify_repository_slots={"example/alpha": 1})
        alpha = self.repository("alpha", "git@github.com:example/alpha.git")
        beta = self.repository("beta", "git@github.com:example/beta.git")
        self.slots.mkdir()
        old = [verify_queue.open_shared(self.slots / "slot-1.lock"),
               verify_queue.open_shared(verify_queue.repository_lock_paths(self.slots, "example/alpha", 2, 2)[1])]
        try:
            for descriptor in old:
                fcntl.flock(descriptor, fcntl.LOCK_EX)
            first = self.start("a", cwd=alpha)
            _, holders, lines = read_place(first)
            self.assertEqual((lines[0], holders), (SAME_REPOSITORY_LINE, "a verify run"))
            other = self.start("b", cwd=beta)
            self.assertTrue(wait_for(self.mark("b", "start")))
            self.assertFalse(self.mark("a", "start").exists())
        finally:
            for descriptor in old:
                os.close(descriptor)
        self.assertTrue(wait_for(self.mark("a", "start")))
        self.release("a")
        self.release("b")
        self.assertEqual((self.finish(first)[0], self.finish(other)[0]), (0, 0))

    def test_a_declared_limit_above_the_slot_count_builds_no_lock_past_the_count(self):
        self.slots.mkdir()
        taken = []
        self.addCleanup(lambda: [os.close(fd) for fd in taken])
        with mock.patch.object(verify_queue, "repository_lock_paths",
                               wraps=verify_queue.repository_lock_paths) as paths:
            results = [verify_slot._try_slots(self.slots, 2, True, "example/alpha", 50)
                       for _ in range(3)]
        for held, _ in results:
            taken.extend(held or ())
        self.assertEqual([reason for _, reason in results], [None, None, "taken"])
        self.assertTrue(all(fd is not None for held, _ in results[:2] for fd in held))
        self.assertTrue(all(call.args[3] <= 2 for call in paths.call_args_list))
        self.assertEqual({path.name for path in self.slots.glob("repo-*.lock")},
                         {path.name for path in verify_queue.repository_lock_paths(
                             self.slots, "example/alpha", 2, 2)})

    def test_a_waiter_behind_a_paused_earlier_waiter_prints_the_holders_that_left(self):
        self.declare(verify_slots=2)
        holders = [self.start("x"), self.start("y")]
        self.assertTrue(wait_for(self.mark("x", "start")))
        self.assertTrue(wait_for(self.mark("y", "start")))
        second = self.start("b")
        self.assertEqual(read_place(second)[0], 1)
        os.kill(second.pid, signal.SIGSTOP)
        third = self.start("c")
        _, shown, _ = read_place(third)
        self.assertNotEqual(shown, "nothing")
        self.release("x")
        self.release("y")
        read_until(third, is_place(2, lambda text: text == "nothing"), deadline=10)
        os.kill(second.pid, signal.SIGCONT)
        self.release("b")
        self.release("c")
        for proc in (*holders, second, third):
            self.assertEqual(self.finish(proc)[0], 0)

    def test_an_ordinary_run_takes_the_slot_a_live_waiter_held_back_by_its_repository_leaves(self):
        self.declare(verify_slots=2)
        one = self.repository("alpha-one", "git@github.com:example/alpha.git")
        two = self.repository("alpha-two", "https://github.com/Example/alpha")
        beta = self.repository("beta", "git@github.com:example/beta.git")
        holders = [self.start("x"), self.start("y")]
        self.assertTrue(wait_for(self.mark("x", "start")))
        self.assertTrue(wait_for(self.mark("y", "start")))
        first = self.start("a", "--live", cwd=one)
        self.assertEqual(read_place(first)[0], 1)
        second = self.start("b", "--live", cwd=two)
        self.assertEqual(read_place(second)[0], 2)
        other = self.start("c", cwd=beta)
        self.assertEqual(read_place(other)[0], 3)
        os.kill(second.pid, signal.SIGSTOP)
        self.release("x")
        self.assertTrue(wait_for(self.mark("a", "start")))
        self.release("y")
        self.assertTrue(wait_for(self.mark("c", "start")))
        os.kill(second.pid, signal.SIGCONT)
        for name in ("a", "b", "c"):
            self.release(name)
        for proc in (*holders, first, second, other):
            self.assertEqual(self.finish(proc)[0], 0)

    def test_a_waiter_prints_its_place_again_when_it_changes(self):
        first = self.start("a")
        self.assertTrue(wait_for(self.mark("a", "start")))
        second = self.start("b")
        self.assertEqual(read_place(second)[0], 1)
        third = self.start("c")
        _, _, seen = read_place(third)
        self.release("a")
        self.assertTrue(wait_for(self.mark("b", "start")))
        seen += read_until(third, is_place(1))
        self.release("b")
        self.assertTrue(wait_for(self.mark("c", "start")))
        self.release("c")
        for proc in (first, second):
            self.assertEqual(self.finish(proc)[0], 0)
        code, err = self.finish(third)
        self.assertEqual(code, 0)
        lines = [line for line in seen + err.splitlines() if PLACE_PATTERN.match(line)]
        numbers = places("\n".join(lines))
        collapsed = [number for index, number in enumerate(numbers)
                     if index == 0 or number != numbers[index - 1]]
        self.assertEqual(collapsed, [2, 1])
        for earlier, later in itertools.pairwise(lines):
            self.assertNotEqual(earlier, later)
        self.assertGreaterEqual(float(self.mark("c", "start").read_text()),
                                float(self.mark("b", "end").read_text()))

    def test_a_killed_waiter_frees_its_place_at_once(self):
        first = self.start("a")
        self.assertTrue(wait_for(self.mark("a", "start")))
        second = self.start("b")
        self.assertEqual(read_place(second)[0], 1)
        third = self.start("c")
        self.assertEqual(read_place(third)[0], 2)
        os.kill(second.pid, signal.SIGKILL)
        second.wait()
        second.stderr.close()
        read_until(third, is_place(1), deadline=5)
        self.release("a")
        self.assertTrue(wait_for(self.mark("c", "start")))
        self.release("c")
        self.assertEqual((self.finish(first)[0], self.finish(third)[0]), (0, 0))
        self.assertGreaterEqual(float(self.mark("c", "start").read_text()),
                                float(self.mark("a", "end").read_text()))

    def test_a_run_that_waits_its_turn_behind_an_earlier_waiter_says_so(self):
        first = self.start("a")
        self.assertTrue(wait_for(self.mark("a", "start")))
        second = self.start("b")
        read_place(second)
        os.kill(second.pid, signal.SIGSTOP)
        third = self.start("c")
        self.assertEqual(read_place(third)[0], 2)
        self.release("a")
        self.assertTrue(wait_for(self.mark("a", "end")))
        read_until(third, lambda line: line == QUEUED_LINE, deadline=5)
        self.assertFalse(self.mark("c", "start").exists())
        os.kill(second.pid, signal.SIGCONT)
        self.release("b")
        self.release("c")
        for proc in (first, second, third):
            self.assertEqual(self.finish(proc)[0], 0)
        self.assertGreaterEqual(float(self.mark("c", "start").read_text()),
                                float(self.mark("b", "end").read_text()))

    def plain_directory(self, name):
        directory = Path(self.home) / name
        directory.mkdir()
        return str(directory)

    def queue_with_a_waiter_in_each_directory(self, *b_options):
        """`a` holds the one slot; `b` waits first in `db` and `c` second in `dc`; both are released."""
        holder = self.start("a")
        self.assertTrue(wait_for(self.mark("a", "start")))
        for name in ("b", "c"):
            self.release(name)
        first = self.start("b", *b_options, cwd=self.plain_directory("db"))
        self.assertEqual(read_place(first)[0], 1)
        second = self.start("c", cwd=self.plain_directory("dc"))
        self.assertEqual(read_place(second)[0], 2)
        return holder, first, second

    def test_a_timed_out_request_asked_again_resumes_its_earlier_place(self):
        holder, first, second = self.queue_with_a_waiter_in_each_directory("--wait-limit", "2")
        self.assertEqual(self.finish(first)[0], NO_SLOT_EXIT)
        again = self.start("b", cwd=str(Path(self.home) / "db"))
        self.assertEqual(read_place(again)[0], 1)
        self.release("a")
        for proc in (holder, again, second):
            self.assertEqual(self.finish(proc)[0], 0)
        self.assertGreaterEqual(float(self.mark("b", "start").read_text()),
                                float(self.mark("a", "end").read_text()))
        self.assertGreaterEqual(float(self.mark("c", "start").read_text()),
                                float(self.mark("b", "end").read_text()))

    def test_a_request_that_times_out_while_the_queue_lock_is_busy_keeps_its_place(self):
        holder, first, second = self.queue_with_a_waiter_in_each_directory("--wait-limit", "3")
        lock = None
        end = time.monotonic() + 20
        while lock is None and time.monotonic() < end:
            lock = verify_queue.lock_queue(self.slots)
        self.assertIsNotNone(lock)
        try:
            self.assertEqual(self.finish(first)[0], NO_SLOT_EXIT)
        finally:
            os.close(lock)
        again = self.start("b", cwd=str(Path(self.home) / "db"))
        self.assertEqual(read_place(again)[0], 1)
        self.release("a")
        for proc in (holder, again, second):
            self.assertEqual(self.finish(proc)[0], 0)
        self.assertGreaterEqual(float(self.mark("c", "start").read_text()),
                                float(self.mark("b", "end").read_text()))

    def test_another_command_in_the_same_directory_does_not_take_a_timed_out_place(self):
        holder, first, second = self.queue_with_a_waiter_in_each_directory("--wait-limit", "2")
        self.assertEqual(self.finish(first)[0], NO_SLOT_EXIT)
        self.release("e")
        other = self.start("e", cwd=str(Path(self.home) / "db"))
        self.assertEqual(read_place(other)[0], 2)
        self.release("a")
        for proc in (holder, second, other):
            self.assertEqual(self.finish(proc)[0], 0)
        self.assertLessEqual(float(self.mark("c", "start").read_text()),
                             float(self.mark("e", "start").read_text()))

    def test_a_signalled_waiter_does_not_keep_its_place(self):
        holder, first, second = self.queue_with_a_waiter_in_each_directory()
        first.send_signal(signal.SIGTERM)
        self.assertEqual(self.finish(first)[0], 143)
        again = self.start("b", cwd=str(Path(self.home) / "db"))
        self.assertEqual(read_place(again)[0], 2)
        self.release("a")
        for proc in (holder, second, again):
            self.assertEqual(self.finish(proc)[0], 0)
        self.assertLessEqual(float(self.mark("c", "start").read_text()),
                             float(self.mark("b", "start").read_text()))

    def test_a_slot_file_that_is_a_symlink_is_never_written_through(self):
        victim = Path(self.home) / "victim-original"
        victim.write_text("victim-original")
        self.slots.mkdir()
        (self.slots / "slot-0.lock").symlink_to(victim)
        self.release("a")
        code, _ = self.finish(self.start("a", "--wait-limit", "1"))
        self.assertEqual(code, NO_SLOT_EXIT)
        self.assertFalse(self.mark("a", "start").exists())
        self.assertEqual(victim.read_text(), "victim-original")

    def test_the_history_line_records_the_place_each_run_joined_at(self):
        first = self.start("a", code=0)
        self.assertTrue(wait_for(self.mark("a", "start")))
        second = self.start("b", code=3)
        read_place(second)
        third = self.start("c", code=4)
        self.assertEqual(read_place(third)[0], 2)
        fourth = self.start("d", "--wait-limit", "1")
        self.assertEqual(read_place(fourth)[0], 3)
        self.assertEqual(self.finish(fourth)[0], NO_SLOT_EXIT)
        for name in ("a", "b", "c"):
            self.release(name)
        for proc in (first, second, third):
            self.finish(proc)
        self.assertEqual({entry["exit"]: entry["place"] for entry in self.history()},
                         {0: 1, 3: 1, 4: 2, 75: 3})

    def test_a_run_that_waited_then_held_a_slot_records_both_durations(self):
        alpha = self.repository("alpha", "git@github.com:example/alpha.git")
        beta = self.repository("beta", "git@github.com:example/beta.git")
        first = self.start("a", cwd=alpha)
        self.assertTrue(wait_for(self.mark("a", "start")))
        second = self.start("b", code=4, cwd=beta)
        time.sleep(1.0)
        self.release("a")
        self.assertTrue(wait_for(self.mark("b", "start")))
        time.sleep(0.5)
        self.release("b")
        codes = (self.finish(first)[0], self.finish(second)[0])
        self.assertEqual(codes, (0, 4))
        entries = {entry["repository"]: entry for entry in self.history()}
        self.assertEqual(len(self.history()), 2)
        for entry in entries.values():
            self.assertEqual(set(entry), {"command", "exit", "held_seconds", "owner", "place", "repository",
                                          "started", "waited_seconds"})
            self.assertIsNone(entry["owner"])
        command = " ".join(" ".join([sys.executable, "-c", CHILD]).split()[:3])
        beta_entry, alpha_entry = entries["example/beta"], entries["example/alpha"]
        self.assertEqual(beta_entry["exit"], 4)
        self.assertGreaterEqual(beta_entry["waited_seconds"], 0.8)
        self.assertGreaterEqual(beta_entry["held_seconds"], 0.4)
        self.assertEqual(beta_entry["command"], command)
        self.assertEqual(alpha_entry["exit"], 0)
        self.assertLess(alpha_entry["waited_seconds"], 0.5)
        self.assertGreaterEqual(alpha_entry["held_seconds"], 1.0)
        now = datetime.now(timezone.utc)
        for entry in entries.values():
            self.assertTrue(entry["started"].endswith("Z"))
            started = parse_rfc3339_utc(entry["started"])
            self.assertLessEqual(now - timedelta(seconds=120), started)
            self.assertLessEqual(started, now)

    def test_the_history_line_records_the_session_that_asked_or_null(self):
        quick = [sys.executable, "-c", "pass"]
        for name, owner in (("a", "session-a"), ("b", ""), ("c", "s" * 300), ("d", None)):
            self.assertEqual(self.finish(self.start(name, argv=quick, owner=owner))[0], 0)
        self.assertEqual([entry["owner"] for entry in self.history()], ["session-a", None, "s" * 300, None])

    def test_a_run_whose_record_cannot_be_appended_still_returns_the_commands_exit(self):
        (self.slots / "history.jsonl").mkdir(parents=True)
        self.release("a")
        code, err = self.finish(self.start("a", code=3))
        self.assertEqual(code, 3)
        failed = [line for line in err.splitlines()
                  if line.startswith("verify-slot: cannot record this run in ")]
        self.assertEqual(len(failed), 1)
        self.release("b")
        self.assertEqual(self.finish(self.start("b", "--wait-limit", "1"))[0], 0)

    def test_a_history_path_that_is_a_symlink_is_never_written_through(self):
        victim = Path(self.home) / "victim.txt"
        victim.write_text("victim-original")
        self.slots.mkdir()
        (self.slots / "history.jsonl").symlink_to(victim)
        self.release("a")
        code, err = self.finish(self.start("a", code=3))
        self.assertEqual(code, 3)
        self.assertEqual(victim.read_text(), "victim-original")
        failed = [line for line in err.splitlines()
                  if line.startswith("verify-slot: cannot record this run in ")]
        self.assertEqual(len(failed), 1)

    def test_a_history_path_that_is_a_hard_link_is_never_written_through(self):
        victim = Path(self.home) / "victim.txt"
        victim.write_text("victim-original")
        self.slots.mkdir()
        os.link(victim, self.slots / "history.jsonl")
        self.release("a")
        code, err = self.finish(self.start("a", code=3))
        self.assertEqual(code, 3)
        self.assertEqual(victim.read_text(), "victim-original")
        failed = [line for line in err.splitlines()
                  if line.startswith("verify-slot: cannot record this run in ")]
        self.assertEqual(len(failed), 1)

    def test_a_history_path_that_is_a_fifo_does_not_hold_the_run_up(self):
        self.slots.mkdir()
        os.mkfifo(self.slots / "history.jsonl")
        self.release("a")
        code, err = self.finish(self.start("a", code=3), timeout=10)
        self.assertEqual(code, 3)
        failed = [line for line in err.splitlines()
                  if line.startswith("verify-slot: cannot record this run in ")]
        self.assertEqual(len(failed), 1)

    def test_a_run_that_gets_no_slot_records_its_wait_and_no_hold(self):
        first = self.start("a")
        self.assertTrue(wait_for(self.mark("a", "start")))
        self.release("b")
        code, _ = self.finish(self.start("b", "--wait-limit", "1"))
        self.release("a")
        self.finish(first)
        self.assertEqual(code, NO_SLOT_EXIT)
        entries = {entry["exit"]: entry for entry in self.history()}
        self.assertIsNone(entries[75]["held_seconds"])
        self.assertGreaterEqual(entries[75]["waited_seconds"], 1.0)
        self.assertIsInstance(entries[0]["held_seconds"], float)

    def test_a_setup_error_records_nothing(self):
        self.declare(verify_slots=0)
        self.assertEqual(self.finish(self.start("a"))[0], 2)
        self.assertFalse((self.slots / "history.jsonl").exists())

    def test_a_run_with_report_writes_its_history_entry_to_the_report_path(self):
        report = Path(self.home) / "report.json"
        self.release("a")
        code, _ = self.finish(self.start("a", "--report", str(report), code=3))
        self.assertEqual(code, 3)
        text = report.read_text()
        self.assertTrue(text.endswith("\n"))
        self.assertEqual(len(text.splitlines()), 1)
        self.assertEqual(json.loads(text), self.history()[0])
        self.assertEqual(len(self.history()), 1)

    def test_a_report_that_cannot_be_written_still_returns_the_commands_exit(self):
        report = Path(self.home) / "missing-dir" / "report.json"
        self.release("a")
        code, err = self.finish(self.start("a", "--report", str(report), code=4))
        self.assertEqual(code, 4)
        self.assertIn("verify-slot: cannot write the report", err)
        self.assertEqual(len(self.history()), 1)

    def test_a_run_that_gets_no_slot_reports_its_wait_and_no_hold(self):
        report = Path(self.home) / "report.json"
        first = self.start("a")
        self.assertTrue(wait_for(self.mark("a", "start")))
        self.release("b")
        code, _ = self.finish(self.start("b", "--wait-limit", "1", "--report", str(report)))
        self.release("a")
        self.finish(first)
        self.assertEqual(code, NO_SLOT_EXIT)
        reported = json.loads(report.read_text())
        self.assertIsNone(reported["held_seconds"])
        self.assertGreaterEqual(reported["waited_seconds"], 0.9)
        self.assertEqual(reported, {entry["exit"]: entry for entry in self.history()}[75])

    def test_a_setup_error_writes_no_report(self):
        report = Path(self.home) / "report.json"
        self.declare(verify_slots=0)
        self.assertEqual(self.finish(self.start("a", "--report", str(report)))[0], 2)
        self.assertFalse(report.exists())

    def test_a_report_path_that_is_a_symlink_is_not_followed(self):
        target = Path(self.home) / "target"
        target.write_text("keep\n")
        link = Path(self.home) / "link"
        link.symlink_to(target)
        self.release("a")
        code, err = self.finish(self.start("a", "--report", str(link)))
        self.assertEqual(code, 0)
        self.assertEqual(target.read_text(), "keep\n")
        self.assertIn("cannot write the report", err)

    def test_the_history_file_is_shared_by_every_account(self):
        other = Path(self.home) / "other-account"
        other.mkdir()
        self.release("a")
        self.release("b")
        self.finish(self.start("a"))
        self.finish(self.start("b", home=str(other)))
        self.assertEqual(stat.S_IMODE(os.stat(self.slots / "history.jsonl").st_mode), 0o666)
        self.assertEqual(len(self.history()), 2)


class VerifySlotReportTest(SlotHarness, unittest.TestCase):
    def write_history(self, *records, raw=()):
        self.slots.mkdir(exist_ok=True)
        lines = [json.dumps(record, separators=(",", ":")) for record in records] + list(raw)
        (self.slots / "history.jsonl").write_text("".join(line + "\n" for line in lines))

    def rec(self, repository, held, waited, hours_ago=1, code=0):
        started = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
        return {"command": "just test", "exit": code, "held_seconds": held, "repository": repository,
                "started": started.strftime("%Y-%m-%dT%H:%M:%SZ"), "waited_seconds": waited}

    def test_a_line_without_a_place_or_with_a_malformed_one(self):
        old = [self.rec("example/alpha", 30, 2), self.rec("example/alpha", 40, 3)]
        template = ('{"command":"just test","exit":0,"held_seconds":5,"place":%s,'
                    '"repository":"example/alpha","started":"2026-11-23T00:00:00Z","waited_seconds":1}')
        malformed = [template % bad for bad in ("0", '"1"', "true", "1.5")]
        self.write_history(*old, raw=malformed)
        code, lines, err = self.report("--hours", "100000")
        self.assertEqual(code, 0)
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith("example/alpha runs=2 "), lines)
        self.assertIn(REPORT_SKIPPED_LINE.format(count=4, path=self.slots / "history.jsonl"),
                      err.splitlines())

    def test_a_line_whose_owner_is_neither_a_string_nor_null_is_skipped(self):
        self.write_history({**self.rec("example/alpha", 30, 2), "owner": "session-a"},
                           {**self.rec("example/beta", 40, 3), "owner": None},
                           self.rec("example/gamma", 50, 4),
                           {**self.rec("example/delta", 60, 5), "owner": 5})
        code, lines, err = self.report()
        self.assertEqual(code, 0)
        self.assertEqual([line.split(" ", 1)[0] for line in lines],
                         ["example/alpha", "example/beta", "example/gamma"])
        self.assertIn(REPORT_SKIPPED_LINE.format(count=1, path=self.slots / "history.jsonl"),
                      err.splitlines())

    def report(self, *opts):
        result = subprocess.run(
            [sys.executable, "-m", "agent_tools.delivery.verify_slot", "report", *opts],
            env=self.env(), cwd=self.home, capture_output=True, text=True, timeout=20)
        return result.returncode, result.stdout.splitlines(), result.stderr

    def alpha_records(self):
        return [self.rec("example/alpha", 100 * n, 10 * n) for n in range(1, 11)] + [
            self.rec("example/alpha", 99999, 99999, hours_ago=30)]

    def test_the_report_gives_each_repositorys_medians_and_p90s_and_marks_the_one_over_budget(self):
        self.declare(verify_budget_seconds=600)
        beta = [self.rec("example/beta", held, waited)
                for held, waited in ((700, 5), (800, 15), (900, 25))]
        self.write_history(*self.alpha_records(), *beta,
                           self.rec("example/beta", None, 600, code=75), raw=["not json"])
        code, lines, err = self.report()
        self.assertEqual(code, 0)
        self.assertEqual(lines, [
            "example/alpha runs=10 held_median=550s held_p90=900s held_total=5500s"
            " waited_median=55s waited_p90=90s",
            "example/beta runs=4 held_median=800s held_p90=900s held_total=2400s"
            " waited_median=20s waited_p90=600s over budget 600s"])
        self.assertIn(REPORT_SKIPPED_LINE.format(count=1, path=self.slots / "history.jsonl"),
                      err.splitlines())

    def test_the_report_window_is_the_last_n_hours(self):
        self.write_history(*self.alpha_records())
        self.assertTrue(self.report("--hours", "48")[1][0].startswith("example/alpha runs=11 "))
        self.assertTrue(self.report()[1][0].startswith("example/alpha runs=10 "))
        self.assertEqual(self.report("--hours", "0")[0], 2)

    def test_a_line_with_an_integer_too_large_for_a_float_is_skipped(self):
        huge = '{"command":"x","exit":0,"held_seconds":5,"repository":null,' \
            '"started":"2026-11-23T00:00:00Z","waited_seconds":1' + "0" * 400 + "}"
        self.write_history(self.rec("example/beta", 30, 2), raw=[huge])
        code, lines, err = self.report()
        self.assertEqual(code, 0)
        self.assertEqual(len(lines), 1)
        self.assertIn(REPORT_SKIPPED_LINE.format(count=1, path=self.slots / "history.jsonl"),
                      err.splitlines())

    def test_a_window_reaching_before_the_calendar_reports_every_run(self):
        self.write_history(*self.alpha_records())
        code, lines, _ = self.report("--hours", "100000000")
        self.assertEqual(code, 0)
        self.assertTrue(lines[0].startswith("example/alpha runs=11 "))

    def test_a_median_hold_at_the_budget_is_not_marked(self):
        self.declare(verify_budget_seconds=600)
        self.write_history(*[self.rec("example/beta", held, 1) for held in (500, 600, 700)])
        self.assertEqual(self.report()[1], [
            "example/beta runs=3 held_median=600s held_p90=700s held_total=1800s"
            " waited_median=1s waited_p90=1s"])

    def test_with_no_budget_declared_nothing_is_marked(self):
        self.declare()
        self.write_history(*[self.rec("example/beta", 900, 1) for _ in range(3)])
        self.assertEqual(self.report()[1], [
            "example/beta runs=3 held_median=900s held_p90=900s held_total=2700s"
            " waited_median=1s waited_p90=1s"])

    def test_runs_outside_a_repository_and_runs_that_held_nothing_are_reported(self):
        self.write_history(self.rec(None, 30, 2), self.rec("example/gamma", None, 600, code=75))
        self.assertEqual(self.report()[1], [
            "(no repository) runs=1 held_median=30s held_p90=30s held_total=30s"
            " waited_median=2s waited_p90=2s",
            "example/gamma runs=1 held_median=- held_p90=- held_total=0s"
            " waited_median=600s waited_p90=600s"])

    def test_p90_is_the_nearest_rank(self):
        self.assertEqual(verify_history.nearest_rank_p90(list(range(1, 11))), 9)
        self.assertEqual(verify_history.nearest_rank_p90([5]), 5)
        self.assertEqual(verify_history.nearest_rank_p90([3, 1, 2]), 3)
        self.assertEqual(verify_history.nearest_rank_p90(list(range(1, 21))), 18)

    def test_an_invalid_declaration_fails_the_report(self):
        self.declare(verify_budget_seconds=0)
        self.write_history(self.rec("example/beta", 1, 1))
        code, lines, err = self.report()
        self.assertEqual(code, 2)
        self.assertEqual(lines, [])
        self.assertTrue(err.strip())

    def test_the_report_reads_what_a_run_recorded_and_creates_nothing(self):
        code, lines, _ = self.report()
        self.assertEqual((code, lines), (0, []))
        self.assertFalse(self.slots.exists())
        alpha = self.repository("alpha", "git@github.com:example/alpha.git")
        self.release("a")
        self.finish(self.start("a", cwd=alpha))
        lines = self.report()[1]
        self.assertEqual(len(lines), 1)
        self.assertRegex(lines[0], r"^example/alpha runs=1 held_median=\d+s held_p90=\d+s"
                         r" held_total=\d+s waited_median=\d+s waited_p90=\d+s$")

    def test_a_report_over_a_history_path_that_is_a_fifo_fails_instead_of_hanging(self):
        self.slots.mkdir()
        os.mkfifo(self.slots / "history.jsonl")
        code, lines, err = self.report()
        self.assertEqual((code, lines), (2, []))
        self.assertTrue(err.strip())

    def test_report_takes_no_command(self):
        result = subprocess.run(
            [sys.executable, "-m", "agent_tools.delivery.verify_slot", "report", "--", "true"],
            env=self.env(), cwd=self.home, capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)


class CommentCapTests(unittest.TestCase):
    """The queue docstrings this command added stay within the comment cap (rule B19)."""

    def test_the_decision_and_acquire_docstrings_are_within_the_cap(self):
        path = Path(verify_slot.__file__)
        data = path.read_bytes()
        snapshot = never_rise.Snapshot(revision="x", line_counts={}, contents={path.name: data})
        flagged = {v.line for v in comment_lint.enforcers(None)[1].find(snapshot)}
        lines = data.decode().split("\n")
        queue_docstrings = {n for n, text in enumerate(lines, 1)
                            if text.lstrip().startswith(('"""One decision under the queue lock',
                                                         '"""`(held, None, place)`'))}
        self.assertEqual(len(queue_docstrings), 2)
        self.assertEqual(flagged & queue_docstrings, set())


if __name__ == "__main__":
    unittest.main()
