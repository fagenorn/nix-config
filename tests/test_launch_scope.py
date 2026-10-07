"""launch-scope: run a launch's long commands in a scope and reap what they leave (#276).

Real processes throughout. Liveness is read from `ps`, and a zombie counts as
dead (spec Test seams). The injectable `terminate` callables cover the
branches a real process cannot reach (D12).
"""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from agent_tools import launch_processes, launch_scope
from agent_tools.launch_processes import (
    MARKER_ENV, Proc, ProcessTableError, UnsupportedPlatform, process_table,
    protected_pids, read_marker, require_supported_platform, terminate)
from agent_tools.launch_scope import check_launch_reply

# The suite itself may run under `launch-scope exec`; no fixture inherits that marker.
UNMARKED_ENV = {key: value for key, value in os.environ.items() if key != MARKER_ENV}
MARKER = "run-x/1:1:1/" + "a" * 32
# darwin hides an Apple platform binary's environment (D15): a marker proof needs this.
SLEEPER = [sys.executable, "-c", "import time; time.sleep(300)"]


def is_dead(pid):
    """Dead: `ps` no longer lists the pid, or lists it as a zombie.

    A live pid may print an empty `stat` (darwin procps, D15), so being listed
    is what counts.
    """
    completed = subprocess.run(["ps", "-o", "pid=,stat=", "-p", str(pid)],
                               capture_output=True, text=True, check=False)
    fields = completed.stdout.split()
    if completed.returncode != 0 or fields[:1] != [str(pid)]:
        return True
    return len(fields) > 1 and fields[1].startswith("Z")


def wait_until(predicate, seconds=10.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return predicate()


def kill_quietly(pid):
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        pass


class ProcessSeamTest(unittest.TestCase):
    def spawn(self, argv, *, marker=None):
        env = dict(UNMARKED_ENV)
        if marker is not None:
            env[MARKER_ENV] = marker
        child = subprocess.Popen(argv, env=env, start_new_session=True)
        self.addCleanup(child.wait)
        self.addCleanup(kill_quietly, child.pid)
        return child

    def test_a_marked_child_is_read_and_an_unmarked_one_is_not(self):
        marked = self.spawn(SLEEPER, marker=MARKER)
        unmarked = self.spawn(SLEEPER)
        self.assertTrue(wait_until(lambda: read_marker(marked.pid) == MARKER))
        self.assertIsNone(read_marker(unmarked.pid))

    def test_pid_one_and_a_vanished_pid_carry_no_marker(self):
        self.assertIsNone(read_marker(1))
        gone = subprocess.Popen(["true"], env=UNMARKED_ENV)
        gone.wait()
        self.assertIsNone(read_marker(gone.pid))

    def test_the_table_lists_this_process_and_marks_a_zombie(self):
        child = subprocess.Popen(["true"], env=UNMARKED_ENV)
        self.addCleanup(child.wait)
        missing = Proc(0, 0, 0, False)
        self.assertTrue(wait_until(lambda: process_table().get(child.pid, missing).zombie))
        me = process_table()[os.getpid()]
        self.assertEqual((me.ppid, me.pgid, me.zombie), (os.getppid(), os.getpgrp(), False))

    def test_a_ps_that_cannot_run_is_a_table_error(self):
        empty = Path(self.enterContext(tempfile.TemporaryDirectory()))
        with mock.patch.dict(os.environ, {"PATH": str(empty)}):
            with self.assertRaises(ProcessTableError):
                process_table()

    def test_a_blank_stat_is_a_live_process_and_a_bad_line_is_an_error(self):  # D15
        bin_dir = Path(self.enterContext(tempfile.TemporaryDirectory()))
        fake_ps = bin_dir / "ps"

        def table_from(output):
            fake_ps.write_text(f"#!/bin/sh\nprintf '{output}'\n")
            fake_ps.chmod(0o755)
            with mock.patch.dict(os.environ, {"PATH": str(bin_dir)}):
                return process_table()
        self.assertEqual(table_from("  380     1   380     \\n   42   380    42 Z\\n\\n    7     1     7 Ss\\n"),
                         {380: Proc(380, 1, 380, False), 42: Proc(42, 380, 42, True),
                          7: Proc(7, 1, 7, False)})
        for bad in ("  380     1\\n", "  380     1   abc Ss\\n", "1 1 1 S extra\\n"):
            with self.subTest(bad=bad), self.assertRaises(ProcessTableError):
                table_from(bad)

    def test_this_process_and_its_ancestors_are_protected(self):
        protected = protected_pids(process_table())
        self.assertTrue({1, os.getpid(), os.getppid()} <= protected)

    def test_terminate_escalates_to_sigkill(self):
        ready = Path(self.enterContext(tempfile.TemporaryDirectory())) / "ready"
        stubborn = self.spawn([
            sys.executable, "-c",
            "import signal, sys, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
            "open(sys.argv[1], 'w').close(); time.sleep(300)", str(ready)])
        self.assertTrue(wait_until(ready.exists))
        self.assertEqual(terminate([stubborn.pid], [], term_seconds=0.5), (1, frozenset()))
        self.assertTrue(is_dead(stubborn.pid))

    def test_a_group_is_signalled_as_a_group(self):
        leader = self.spawn(["sh", "-c", "sleep 300 & wait"])

        def members():
            return sorted(pid for pid, proc in process_table().items()
                          if proc.pgid == leader.pid and not proc.zombie)
        self.assertTrue(wait_until(lambda: len(members()) == 2))
        before = members()
        self.assertEqual(terminate([], [leader.pid]), (2, frozenset()))
        for pid in before:
            self.assertTrue(wait_until(lambda: is_dead(pid), 2.0), pid)

    def test_this_process_its_ancestors_and_its_group_are_never_signalled(self):
        calls = []
        terminate([os.getpid(), os.getppid(), 1], [os.getpgrp()],
                  send=lambda pid, sig: calls.append(("pid", pid)),
                  send_group=lambda pgid, sig: calls.append(("group", pgid)),
                  term_seconds=0.1, kill_seconds=0.1)
        protected = protected_pids(process_table())
        self.assertNotIn(("group", os.getpgrp()), calls)
        self.assertEqual([call for call in calls if call[1] in protected], [])

    def test_a_pid_that_outlives_sigkill_is_a_survivor(self):  # D12
        table = {os.getpid(): Proc(os.getpid(), 1, os.getpgrp(), False),
                 4242424: Proc(4242424, 1, 4242424, False)}
        sent = []
        result = terminate([4242424], [], read_table=lambda: table,
                           send=lambda pid, sig: sent.append((pid, sig)),
                           send_group=lambda pgid, sig: sent.append(("group", pgid, sig)),
                           term_seconds=0.1, kill_seconds=0.1)
        self.assertEqual(result, (1, frozenset({4242424})))
        self.assertEqual(sent, [(4242424, signal.SIGTERM), (4242424, signal.SIGKILL)])

    def test_a_reused_pid_is_not_sent_sigkill(self):  # D11
        tables = iter([{4242424: Proc(4242424, 1, 4242424, False)}]
                      + [{4242424: Proc(4242424, 1, 77, False)}] * 1000)
        sent = []
        result = terminate([4242424], [], read_table=lambda: next(tables),
                           send=lambda pid, sig: sent.append((pid, sig)),
                           send_group=lambda pgid, sig: sent.append(("group", pgid, sig)),
                           term_seconds=0.1, kill_seconds=0.1)
        self.assertEqual((result, sent), ((1, frozenset()), [(4242424, signal.SIGTERM)]))

    def test_a_target_gone_before_sigterm_is_not_counted(self):  # D14
        tables = iter([{4242424: Proc(4242424, 1, 4242424, False),
                        4242425: Proc(4242425, 1, 4242425, False)}] + [{}] * 1000)
        sent = []

        def send(pid, sig):
            sent.append((pid, sig))
            if pid == 4242425:
                raise ProcessLookupError(pid)
        result = terminate([4242424, 4242425], [], read_table=lambda: next(tables),
                           send=send,
                           send_group=lambda pgid, sig: sent.append(("group", pgid, sig)),
                           term_seconds=0.1, kill_seconds=0.1)
        self.assertEqual(result, (1, frozenset()))
        self.assertEqual(sorted(sent), [(4242424, signal.SIGTERM), (4242425, signal.SIGTERM)])

    def test_an_unsupported_platform_fails_loud(self):
        with mock.patch.object(launch_processes.sys, "platform", "win32"):
            with self.assertRaises(UnsupportedPlatform):
                require_supported_platform()
            with self.assertRaises(UnsupportedPlatform):
                read_marker(os.getpid())


ROOT = Path(__file__).parents[1]
HARNESS_SOURCE = ROOT / "home/common/agent-skills/tests/test_workflow_state.py"
WORKFLOW = ROOT / "home/common/agent-skills/scripts/workflow-state.py"
HERMETIC_GIT = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}
LATER = "2026-08-13T20:06:00Z"


def _harness():
    spec = importlib.util.spec_from_file_location("launch_scope_harness", HARNESS_SOURCE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.LifecycleHarness


LifecycleHarness = _harness()


class ScopeHarness(LifecycleHarness):
    """A ledger with launch 14:1:1 current, a git root for the registry, a PATH shim."""

    def setUp(self):
        super().setUp()
        self.cli_env = {k: v for k, v in self.cli_env.items() if k != MARKER_ENV}
        self.shims = self.root / "shims"
        self.shims.mkdir()
        self.write_shim(f"exec {shlex.quote(sys.executable)} {shlex.quote(str(WORKFLOW))} \"$@\"")
        self.env = {**self.cli_env, **HERMETIC_GIT,
                    "PATH": f"{self.shims}{os.pathsep}{os.environ['PATH']}"}
        subprocess.run(["git", "init", "-q", str(self.root)], env=self.env, check=True)
        common = subprocess.run(
            ["git", "-C", str(self.root), "rev-parse", "--path-format=absolute",
             "--git-common-dir"], env=self.env, check=True, capture_output=True, text=True)
        self.registry = Path(common.stdout.strip()) / "agent-launch" / self.run_id
        self.init_run()
        self.assertEqual(self.spawn(issue=14, worktree=str(self.root / "wt-14"))["id"], "14:1:1")

    def write_shim(self, body):
        shim = self.shims / "workflow-state"
        shim.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
        shim.chmod(0o755)

    def argv(self, *args):
        return [sys.executable, "-m", "agent_tools.launch_scope", *args]

    def scope(self, *args, env=None):
        return subprocess.run(self.argv(*args), cwd=self.root, capture_output=True, text=True,
                              check=False, env=self.env if env is None else env, timeout=120)

    def exec_args(self, *command, action_id="14:1:1", worker_id=None):
        identity = ["--worker-id", worker_id] if worker_id else ["--action-id", action_id]
        return ["exec", "--repo-root", str(self.root), "--run-id", self.run_id, *identity,
                "--", *command]

    def exec_(self, *command, **identity):
        return self.scope(*self.exec_args(*command, **identity))

    def background_exec(self, *command, **identity):
        supervisor = subprocess.Popen(self.argv(*self.exec_args(*command, **identity)),
                                      cwd=self.root, env=self.env,
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(supervisor.wait)
        self.addCleanup(kill_quietly, supervisor.pid)
        return supervisor

    def pid_from(self, path):
        self.assertTrue(wait_until(path.exists), path)
        pids = [int(word) for word in path.read_text().split()]
        for pid in pids:
            self.addCleanup(kill_quietly, pid)
        return pids

    def rows(self, action_id):
        directory = self.registry / action_id
        return sorted(p.name for p in directory.glob("*.json")) if directory.is_dir() else []

    def assert_refused(self, completed, action_id, reason):
        self.assertEqual(completed.returncode, 3, completed.stderr)
        self.assertEqual(completed.stdout.count("\n"), 1)
        self.assertEqual(json.loads(completed.stdout),
                         {"action_id": action_id, "started": False, "reason": reason})


# The backgrounded sleeper is a sys.executable process, so its marker is readable on darwin (D15).
SLEEP_300 = f"{shlex.quote(sys.executable)} -c 'import time; time.sleep(300)'"
BACKGROUND_SLEEP = f'{SLEEP_300} & echo $! > "$1.tmp" && mv "$1.tmp" "$1"; wait'


class ExecTest(ScopeHarness, unittest.TestCase):
    def test_a_superseded_launch_starts_nothing_and_leaves_no_row(self):
        resumed = self.resume(issue=14, worktree=str(self.root / "wt-14"), now=LATER,
                              owner_unavailable=True)
        self.assertEqual(resumed["id"], "14:1:2")
        witness = self.root / "started"
        done = self.exec_(sys.executable, "-c",
                          "import sys; open(sys.argv[1], 'w').close()", str(witness))
        self.assert_refused(done, "14:1:1", "superseded_launch")
        self.assertFalse(witness.exists())
        self.assertEqual(self.rows("14:1:1"), [])

    def test_a_backgrounded_sleep_does_not_outlive_exec(self):
        pidfile = self.root / "sleep.pid"
        done = self.exec_("sh", "-c", f'{SLEEP_300} & echo $! > "$1"', "sh", str(pidfile))
        self.assertEqual(done.returncode, 0, done.stderr)
        (pid,) = self.pid_from(pidfile)
        self.assertTrue(wait_until(lambda: is_dead(pid), 2.0))
        self.assertEqual(self.rows("14:1:1"), [])

    def test_the_child_carries_the_marker_and_its_status_passes_through(self):
        seen = self.root / "marker"
        done = self.exec_("sh", "-c", 'printf %s "$AGENT_LAUNCH_SCOPE" > "$1"; exit 7',
                          "sh", str(seen))
        self.assertEqual(done.returncode, 7, done.stderr)
        self.assertRegex(seen.read_text(),
                         rf"\A{re.escape(self.run_id)}/14:1:1/[0-9a-f]{{32}}\Z")
        self.assertEqual(self.exec_("sh", "-c", "kill -TERM $$").returncode,
                         128 + signal.SIGTERM)

    def test_a_term_to_exec_reaches_the_command_group(self):
        pidfile = self.root / "sleep.pid"
        supervisor = self.background_exec("sh", "-c", BACKGROUND_SLEEP, "sh", str(pidfile))
        (pid,) = self.pid_from(pidfile)
        supervisor.send_signal(signal.SIGTERM)
        self.assertEqual(supervisor.wait(timeout=30), 128 + signal.SIGTERM)
        self.assertTrue(is_dead(pid))
        self.assertEqual(self.rows("14:1:1"), [])

    def test_a_concurrent_exec_of_the_same_launch_is_untouched(self):
        pidfile = self.root / "sleep.pid"
        first = self.background_exec("sh", "-c", BACKGROUND_SLEEP, "sh", str(pidfile))
        (pid,) = self.pid_from(pidfile)
        second = self.exec_("true")
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertFalse(is_dead(pid))
        self.assertEqual(len(self.rows("14:1:1")), 1)
        first.send_signal(signal.SIGTERM)
        first.wait(timeout=30)
        self.assertEqual(self.rows("14:1:1"), [])

    def test_a_worker_runs_while_live_and_is_refused_once_released(self):
        worker = self.register_worker(action_id="14:1:1",
                                      now="2026-08-13T20:01:00Z")["worker_id"]
        self.assertEqual(self.exec_("true", worker_id=worker).returncode, 0)
        self.release_worker(worker_id=worker, event="returned", now="2026-08-13T20:02:00Z")
        self.assert_refused(self.exec_("true", worker_id=worker), "14:1:1", "released")

    def test_a_failed_or_malformed_check_starts_nothing(self):
        worker = self.register_worker(action_id="14:1:1",
                                      now="2026-08-13T20:01:00Z")["worker_id"]
        self.write_shim("exit 2")
        self.assert_refused(self.exec_("true"), "14:1:1", "check_launch_failed")
        self.assert_refused(self.exec_("true", worker_id=worker), "14:1:1",
                            "check_worker_failed")
        good = {"action_id": "14:1:1", "current": True, "current_action_id": "14:1:1",
                "reason": "current"}
        for reply in ("not json", json.dumps({**good, "current": "yes"}),
                      json.dumps({**good, "action_id": "14:1:2"})):
            with self.subTest(reply=reply):
                self.write_shim(f"echo {shlex.quote(reply)}")
                self.assert_refused(self.exec_("true"), "14:1:1", "malformed_reply")
        self.assertEqual(self.rows("14:1:1"), [])

    def test_a_program_that_cannot_run_exits_as_a_shell_does(self):
        self.assertEqual(self.exec_("no-such-program-276").returncode, 127)
        plain = self.root / "plain"
        plain.write_text("x\n")
        plain.chmod(0o644)
        self.assertEqual(self.exec_(str(plain)).returncode, 126)
        self.assertEqual(self.rows("14:1:1"), [])

    def test_usage_and_helper_errors_exit_two_with_empty_stdout(self):
        not_git = Path(self.enterContext(tempfile.TemporaryDirectory()))
        git_only = self.root / "git-only"
        git_only.mkdir()
        (git_only / "git").symlink_to(shutil.which("git", path=self.env["PATH"]))
        base = ["exec", "--repo-root", str(self.root), "--run-id", self.run_id]
        cases = {
            "no separator": ([*base, "--action-id", "14:1:1", "true"], None),
            "no identity": ([*base, "--", "true"], None),
            "two identities": ([*base, "--action-id", "14:1:1", "--worker-id", "14:1:1:w1",
                                "--", "true"], None),
            "empty argv": ([*base, "--action-id", "14:1:1", "--"], None),
            "unsafe action": ([*base, "--action-id", "..", "--", "true"], None),
            "unsafe worker": ([*base, "--worker-id", "w1", "--", "true"], None),
            "unsafe run": (["exec", "--repo-root", str(self.root), "--run-id", "../x",
                            "--action-id", "14:1:1", "--", "true"], None),
            "not a repository": (["exec", "--repo-root", str(not_git), "--run-id",
                                  self.run_id, "--action-id", "14:1:1", "--", "true"], None),
            "no workflow-state": ([*base, "--action-id", "14:1:1", "--", "true"],
                                  {**self.env, "PATH": str(git_only)}),
        }
        for label, (args, env) in cases.items():
            with self.subTest(case=label):
                done = self.scope(*args, env=env)
                self.assertEqual((done.returncode, done.stdout), (2, ""), done.stderr)
        self.assertEqual(self.rows("14:1:1"), [])

    def test_a_failure_after_the_spawn_still_kills_the_group(self):  # D14
        real_write = launch_scope.write_atomically

        def failing_rewrite(pidfile):
            def write(target, data):
                if json.loads(data)["pgid"] is None:
                    return real_write(target, data)
                self.assertTrue(wait_until(pidfile.exists), pidfile)
                raise OSError("injected rewrite failure")
            return mock.patch.object(launch_scope, "write_atomically", write)

        def failing_table(pidfile):
            return mock.patch.object(launch_scope, "process_table",
                                     side_effect=ProcessTableError("injected table failure"))
        exiting = f'{SLEEP_300} & echo $! > "$1.tmp" && mv "$1.tmp" "$1"'
        cases = {
            # Proven clean: the row goes. Unprovable (no table): the row stays for reap.
            "row rewrite": (failing_rewrite, BACKGROUND_SLEEP, "injected rewrite failure", 0),
            "process table": (failing_table, exiting, "injected table failure", 1),
        }
        forwarded = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
        for label, (inject, script, message, rows) in cases.items():
            with self.subTest(case=label):
                pidfile = self.root / f"{label.replace(' ', '-')}.pid"
                before = {signum: signal.getsignal(signum) for signum in forwarded}
                stdout, stderr = io.StringIO(), io.StringIO()
                with mock.patch.dict(os.environ, self.env, clear=True), inject(pidfile), \
                        contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    status = launch_scope.main(
                        self.exec_args("sh", "-c", script, "sh", str(pidfile)))
                self.assertEqual((status, stdout.getvalue()), (2, ""), stderr.getvalue())
                self.assertIn(f"launch-scope: ", stderr.getvalue())
                self.assertIn(message, stderr.getvalue())
                (pid,) = self.pid_from(pidfile)
                self.assertTrue(wait_until(lambda: is_dead(pid), 2.0), pid)
                self.assertEqual({signum: signal.getsignal(signum) for signum in forwarded},
                                 before)
                self.assertEqual(len(self.rows("14:1:1")), rows)


class CheckLaunchReplyTest(unittest.TestCase):
    def test_only_an_exact_reply_is_believed(self):
        good = {"action_id": "1:1:1", "current": True, "current_action_id": "1:1:1",
                "reason": "current"}
        stale = {**good, "current": False, "current_action_id": "1:1:2",
                 "reason": "superseded_launch"}
        cases = {
            b"not json": "malformed_reply",
            json.dumps([good]).encode(): "malformed_reply",
            json.dumps({**good, "extra": 1}).encode(): "malformed_reply",
            json.dumps({**good, "current": 1}).encode(): "malformed_reply",
            json.dumps({**good, "action_id": "1:1:2"}).encode(): "malformed_reply",
            json.dumps({**good, "reason": "superseded_launch"}).encode(): "malformed_reply",
            json.dumps({**good, "current_action_id": "1:1:2"}).encode(): "malformed_reply",
            json.dumps({**good, "current_action_id": None}).encode(): "malformed_reply",
            json.dumps({**stale, "current_action_id": 7}).encode(): "malformed_reply",
            json.dumps({**stale, "reason": 3}).encode(): "malformed_reply",
            b'{"action_id":"1:1:1","action_id":"1:1:1","current":true,'
            b'"current_action_id":"1:1:1","reason":"current"}': "malformed_reply",
            b'{"action_id":"1:1:1","current":true,"current_action_id":NaN,'
            b'"reason":"current"}': "malformed_reply",
            json.dumps(good).encode(): "current",
            json.dumps(stale).encode(): "superseded_launch",
            json.dumps({**stale, "current_action_id": None,
                        "reason": "unknown_run"}).encode(): "unknown_run",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(check_launch_reply(raw, "1:1:1"), expected)


if __name__ == "__main__":
    unittest.main()
