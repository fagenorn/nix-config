"""The eleven-m5 memory floor's workload selection: which processes a workload holds and which are protected.

Calls `agent_tools.hosts.memory_floor` directly against stubbed process tables (no libproc, no
kernel call, so it runs on Linux): what protects a process, which declared owner a process belongs
to, how agent processes group by the declared root their cwd or ancestor is in, how CI jobs and
runner orphans are workloads of their runner user, and the order of a workload's pids.
Run: just agent-workflow-tests
"""

import contextlib
import dataclasses
import io as stdio
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock
from datetime import datetime, timezone
from pathlib import Path

from agent_tools.hosts.memory_floor import (
    GIB,
    _owners,
    build_parser,
    Io,
    Limits,
    Loop,
    restore_loop,
    Owners,
    Proc,
    enforce_once,
    kill_line,
    next_interval,
    parse_launchctl_list,
    parse_ps,
    protected_pids,
    read_omlx_pid,
    step,
    workloads,
)
from agent_tools.hosts.omlx_memory_watch import ReadingError

ROOT = Path(__file__).resolve().parents[1]

TIER = "fast"

W1 = "/Users/anis/Projects/jarbird/.worktrees/w1"
W2 = "/Users/anis/Projects/jarbird/.worktrees/w2"
OWNERS = Owners(
    501,
    "anis",
    ("/Users/anis/Projects/*/.worktrees/*", "/private/tmp/verify-pending-*"),
    ((534, "_github-runner-jarbird"),),
    agent_sessions=("claude", ".claude-unwrapped"),
)
MAIN = "/Users/anis/Projects/nix-config"
SCRATCH = "/private/tmp/claude-501/scratch"


def proc(pid, ppid, uid, cwd, gib, command="node"):
    return Proc(pid, ppid, uid, command, cwd, int(gib * GIB))


def table_of(*procs):
    return {p.pid: p for p in procs}


def session_tree(probe_gib, **overrides):
    """A Claude Code session: a daemon, its pty host, a spare, the Bash tool shell and a probe below it."""
    table = table_of(
        proc(198, 1, 501, "/", 0, ".claude-unwrapped daemon run"),
        proc(199, 198, 501, "/", 0, "claude bg-pty-host"),
        proc(200, 199, 501, MAIN, 1, "claude bg-spare"),
        proc(300, 200, 501, MAIN, 0, "/bin/zsh -c source snapshot.sh"),
        proc(301, 300, 501, SCRATCH, probe_gib, "python3 probe.py"),
    )
    for pid, changes in overrides.items():
        table[int(pid)] = dataclasses.replace(table[int(pid)], **changes)
    return table


LIMITS = Limits(16 * GIB, 3, 5, 16 * GIB, 2 * GIB, 2, 10, 24 * GIB, 190, GIB)
KILL_LINE = re.compile(
    r"^2026-11-24T12:33:05\+00:00 memory_kill reason=(floor|run_bound) owner=anis workload=agent:/Users/anis/Projects/jarbird/\.worktrees/w1 root_pid=300"
    r' root="node vitest run" processes=3 tree_gib=\d+\.\d available_before_gib=\d+\.\d'
    r" available_after_gib=\d+\.\d signals=(term|term\+kill)\n$"
)


def selected(table, omlx_pid=None, services=()):
    return workloads(table, OWNERS, protected_pids(table, omlx_pid, set(services)))


class SelectionTest(unittest.TestCase):
    def test_a_protected_or_undeclared_process_is_never_selected_even_when_largest(self):
        small = proc(300, 1, 501, W1, 2)
        rows = {
            "omlx": (proc(400, 1, 501, W1, 150), 400, ()),
            "omlx_child": (proc(401, 400, 501, W1, 150), 400, ()),
            "console": (proc(402, 1, 501, W1, 150), None, (402,)),
            "launchd_service": (proc(403, 1, 534, None, 150, "/x/Runner.Listener"), None, (403,)),
            "undeclared": (proc(404, 300, 503, W1, 150), None, ()),
            "launchd": (proc(1, 0, 501, W1, 150, "/sbin/launchd"), None, ()),
        }
        for name, (large, omlx_pid, services) in rows.items():
            with self.subTest(name):
                members = [small, large]
                if name == "omlx_child":
                    members.append(proc(400, 1, 501, W1, 1))
                found = selected(table_of(*members), omlx_pid, services)
                self.assertEqual(found[0].key, f"agent:{W1}")
                self.assertNotIn(large.pid, [pid for w in found for pid in w.pids])

    def test_agent_processes_group_by_the_declared_root_their_cwd_or_ancestor_is_in(self):
        rows = {
            "orphans": (
                [proc(310, 1, 501, W1, 3), proc(311, 1, 501, W1, 3), proc(312, 1, 501, W1, 3)],
                {f"agent:{W1}": ({310, 311, 312}, 9 * GIB)},
            ),
            "child_elsewhere": (
                [proc(320, 1, 501, W1, 2), proc(321, 320, 501, "/tmp", 1)],
                {f"agent:{W1}": ({320, 321}, 3 * GIB)},
            ),
            "outside": (
                [proc(330, 1, 501, "/Users/anis/Projects/nix-config", 5)],
                {},
            ),
            "own_cwd_wins": (
                [proc(340, 1, 501, W1, 2), proc(341, 340, 501, W2, 4)],
                {f"agent:{W1}": ({340}, 2 * GIB), f"agent:{W2}": ({341}, 4 * GIB)},
            ),
            "verify": (
                [proc(350, 1, 501, "/private/tmp/verify-pending-ab12cd34/src", 6)],
                {"agent:/private/tmp/verify-pending-ab12cd34": ({350}, 6 * GIB)},
            ),
        }
        for name, (members, expected) in rows.items():
            with self.subTest(name):
                found = selected(table_of(*members))
                self.assertEqual(
                    {w.key: (set(w.pids), w.size) for w in found}, expected
                )
                self.assertEqual({w.owner for w in found}, {"anis"} if expected else set())
                sizes = [w.size for w in found]
                self.assertEqual(sizes, sorted(sizes, reverse=True))

    def test_ci_jobs_and_runner_orphans_are_workloads_of_their_runner_user(self):
        table = table_of(
            proc(600, 1, 534, None, 1, "/x/Runner.Listener run"),
            proc(601, 600, 534, None, 2, "/private/var/lib/github-runners/x/bin/Runner.Worker spawnclient 1 2"),
            proc(602, 601, 534, None, 3, "node build"),
            proc(603, 1, 534, None, 4, "node stray"),
        )
        found = {w.key: w for w in selected(table, services=(600,))}
        self.assertEqual(
            set(found), {"ci:_github-runner-jarbird:601", "ci:_github-runner-jarbird:orphans"}
        )
        job = found["ci:_github-runner-jarbird:601"]
        self.assertEqual(job.pids, (602, 601))
        self.assertEqual(job.owner, "_github-runner-jarbird")
        self.assertEqual(job.root_pid, 601)
        self.assertEqual(found["ci:_github-runner-jarbird:orphans"].pids, (603,))
        self.assertNotIn(600, [pid for w in found.values() for pid in w.pids])

    def test_pids_are_ordered_leaves_first(self):
        table = table_of(
            proc(300, 1, 501, W1, 1),
            proc(301, 300, 501, W1, 1),
            proc(302, 301, 501, W1, 1),
            proc(303, 300, 501, W1, 1),
        )
        (only,) = selected(table)
        self.assertEqual(only.pids, (302, 303, 301, 300))
        self.assertEqual(only.root_pid, 300)


    def test_an_agent_tree_outside_every_root_is_a_workload_below_its_session(self):
        rows = {
            "scratch_cwd": (
                {**session_tree(30), 302: proc(302, 301, 501, SCRATCH, 2, "python3 -c worker")},
                {"agent:session:300": (300, {300, 301, 302}, 32 * GIB)},
            ),
            "main_checkout_parent": (
                {**session_tree(30), 301: proc(301, 300, 501, MAIN, 30, "python3 probe.py")},
                {"agent:session:300": (300, {300, 301}, 30 * GIB)},
            ),
            "two_shells": (
                {
                    **session_tree(5),
                    310: proc(310, 200, 501, MAIN, 0, "/bin/zsh -c source snapshot.sh"),
                    311: proc(311, 310, 501, SCRATCH, 3, "python3 other.py"),
                },
                {
                    "agent:session:300": (300, {300, 301}, 5 * GIB),
                    "agent:session:310": (310, {310, 311}, 3 * GIB),
                },
            ),
            "nested_session": (
                {
                    **session_tree(0),
                    302: proc(302, 301, 501, MAIN, 1, "claude -p review"),
                    303: proc(303, 302, 501, MAIN, 0, "/bin/zsh -c source snapshot.sh"),
                    304: proc(304, 303, 501, SCRATCH, 30, "python3 probe.py"),
                },
                {
                    "agent:session:300": (300, {300, 301}, 0),
                    "agent:session:303": (303, {303, 304}, 30 * GIB),
                },
            ),
            "rooted_shell_wins": (
                {**session_tree(30), 300: proc(300, 200, 501, W1, 0, "/bin/zsh -c source snapshot.sh")},
                {f"agent:{W1}": (300, {300, 301}, 30 * GIB)},
            ),
        }
        for name, (table, expected) in rows.items():
            with self.subTest(name):
                found = selected(table)
                self.assertEqual({w.key: (w.root_pid, set(w.pids), w.size) for w in found}, expected)
                self.assertEqual({w.owner for w in found}, {"anis"})
                if name == "two_shells":
                    self.assertEqual([w.key for w in found], ["agent:session:300", "agent:session:310"])
                members = {pid for w in found for pid in w.pids}
                self.assertFalse(members & {198, 199, 200})
                if name == "nested_session":
                    self.assertNotIn(302, members)

    def test_protection_and_other_users_hold_below_a_session(self):
        rows = {
            "omlx_shell": (session_tree(30), 300, (), {}),
            "omlx_below_probe": (
                {**session_tree(30), 302: proc(302, 301, 501, SCRATCH, 40)}, 301, (), {"agent:session:300": {300}},
            ),
            "service_shell": (session_tree(30), None, (300,), {}),
            "service_session": (session_tree(30), None, (200,), {"agent:session:300": {300, 301}}),
            "omlx_session_and_service_child": (session_tree(30), 198, (200,), {}),
            "other_user_probe": (session_tree(30, **{"301": {"uid": 503}}), None, (), {"agent:session:300": {300}}),
            "other_users_session": (session_tree(30, **{"200": {"uid": 503}}), None, (), {}),
            "no_session": (
                table_of(
                    proc(400, 1, 501, SCRATCH, 30, "python3 probe.py"),
                    proc(401, 1, 501, "/", 30, "/Applications/Safari.app/Contents/MacOS/Safari"),
                ),
                None, (), {},
            ),
            "session_alone": (table_of(proc(200, 1, 501, MAIN, 50, "claude bg-spare")), None, (), {}),
        }
        for name, (table, omlx_pid, services, expected) in rows.items():
            with self.subTest(name):
                found = selected(table, omlx_pid, services)
                self.assertEqual({w.key: set(w.pids) for w in found}, expected)

    def test_a_session_executable_under_a_path_with_spaces_is_found_by_its_executable(self):
        spaced = "/Users/anis/Agent Tools/claude"
        table = session_tree(30, **{"200": {"command": f"{spaced} bg-spare", "executable": spaced}})
        self.assertEqual({w.key: set(w.pids) for w in selected(table)}, {"agent:session:300": {300, 301}})
        # An unrooted child of that spaced session joins the run bound too.
        child = table_of(
            dataclasses.replace(proc(200, 1, 501, MAIN, 0), command=f"{spaced} bg-spare", executable=spaced),
            proc(300, 200, 501, SCRATCH, 30, "python3 probe.py"),
        )
        self.assertEqual({w.key: set(w.pids) for w in selected(child)}, {"agent:session:300": {300}})

    def test_every_omlx_descendant_is_protected_through_a_service_child(self):
        self.assertEqual(protected_pids(session_tree(30), 198, {200}), {0, 1, 198, 199, 200, 300, 301})


class OwnersCliTest(unittest.TestCase):
    def test_parsed_session_programs_select_a_tree_below_each_one(self):
        args = build_parser().parse_args([
            "enforce", "--floor-gib", "10", "--run-bound-gib", "24", "--min-tree-gib", "1",
            "--omlx-jetsam-priority", "190", "--agent-user", "anis",
            "--agent-root", "/Users/anis/Projects/*/.worktrees/*",
            "--agent-session", "claude", "--agent-session", ".claude-unwrapped",
            "--record", "/nonexistent/floor.json",
        ])
        with mock.patch(
            "agent_tools.hosts.memory_floor.pwd.getpwnam", return_value=types.SimpleNamespace(pw_uid=501)
        ):
            owners = _owners(args)
        self.assertEqual(owners.agent_sessions, ("claude", ".claude-unwrapped"))
        rows = {
            "claude": "claude bg-spare",
            ".claude-unwrapped": "/nix/store/abc-claude-code-2.1.322/bin/.claude-unwrapped daemon run",
        }
        for name, session_command in rows.items():
            with self.subTest(name):
                table = table_of(
                    proc(200, 1, 501, MAIN, 0, session_command),
                    proc(300, 200, 501, MAIN, 0, "/bin/zsh -c source snapshot.sh"),
                    proc(301, 300, 501, SCRATCH, 30, "python3 probe.py"),
                )
                found = workloads(table, owners, protected_pids(table, None, set()))
                self.assertEqual(
                    [(w.key, w.root_pid, set(w.pids)) for w in found], [("agent:session:300", 300, {300, 301})]
                )

    def test_only_the_parsed_session_programs_select_a_tree(self):
        args = build_parser().parse_args([
            "enforce", "--floor-gib", "10", "--run-bound-gib", "24", "--min-tree-gib", "1",
            "--omlx-jetsam-priority", "190", "--agent-user", "anis",
            "--agent-root", "/Users/anis/Projects/*/.worktrees/*",
            "--agent-session", ".claude-unwrapped",
            "--record", "/nonexistent/floor.json",
        ])
        with mock.patch(
            "agent_tools.hosts.memory_floor.pwd.getpwnam", return_value=types.SimpleNamespace(pw_uid=501)
        ):
            owners = _owners(args)
        table = table_of(
            proc(200, 1, 501, MAIN, 0, "/nix/store/abc-claude-code/bin/.claude-unwrapped daemon run"),
            proc(300, 200, 501, MAIN, 0, "/bin/zsh -c source snapshot.sh"),
            proc(301, 300, 501, SCRATCH, 30, "python3 probe.py"),
            proc(210, 1, 501, MAIN, 0, "claude bg-spare"),
            proc(310, 210, 501, MAIN, 0, "/bin/zsh -c source snapshot.sh"),
            proc(311, 310, 501, SCRATCH, 30, "python3 probe.py"),
        )
        found = workloads(table, owners, protected_pids(table, None, set()))
        self.assertEqual({w.key: set(w.pids) for w in found}, {"agent:session:300": {300, 301}})


class KillLineTest(unittest.TestCase):
    def test_an_unsafe_workload_name_stays_on_one_line(self):
        base = {
            "at": "2026-11-24T12:33:05+00:00", "reason": "run_bound", "owner": "anis", "root_pid": 300,
            "root_command": "node", "processes": 2, "tree_bytes": 30 * GIB,
            "available_before_bytes": 50 * GIB, "available_after_bytes": 60 * GIB, "signals": "term",
        }
        rows = {
            "unsafe": (
                "agent:/Users/anis/Projects/jar\nbird x/.worktrees/w1",
                " workload=agent:/Users/anis/Projects/jar%0Abird%20x/.worktrees/w1 root_pid=",
            ),
            "session": ("agent:session:300", " workload=agent:session:300 root_pid="),
        }
        for name, (key, fragment) in rows.items():
            with self.subTest(name):
                line = kill_line({**base, "workload": key})
                self.assertEqual(line.count("\n"), 1)
                self.assertTrue(line.endswith("\n"))
                self.assertIn(fragment, line)


class ParseTest(unittest.TestCase):
    def test_ps_and_launchctl_list_lines_parse_to_pids(self):
        text = "  1     0     0 /sbin/launchd\n 300 1 501 node vitest run --pool forks\n"
        self.assertEqual(
            parse_ps(text),
            {1: (0, 0, "/sbin/launchd"), 300: (1, 501, "node vitest run --pool forks")},
        )
        with self.assertRaises(ValueError):
            parse_ps("garbage")
        listing = "PID\tStatus\tLabel\n55731\t0\torg.nixos.omlx\n-\t0\torg.nixos.sops-nix\n"
        self.assertEqual(parse_launchctl_list(listing), {55731})


class FakeIo:
    """Readings in GiB (the last repeats); a pid dies on SIGKILL, or on SIGTERM unless stubborn."""

    def __init__(self, readings, table, stubborn=(), broken=()):
        self.readings = list(readings)
        self.base = dict(table)
        self.stubborn = set(stubborn)
        self.broken = set(broken)
        self.dead = set()
        self.signals = []
        self.stamps = []
        self.time = 1000.0

    def _read(self, name):
        if name in self.broken:
            raise ReadingError(f"{name} could not run")

    def available(self):
        self._read("available")
        value = self.readings.pop(0) if len(self.readings) > 1 else self.readings[0]
        return int(value * GIB)

    def table(self):
        self._read("table")
        return {pid: p for pid, p in self.base.items() if pid not in self.dead}

    def services(self):
        self._read("services")
        return set()

    def omlx_pid(self):
        self._read("omlx_pid")
        return None

    def signal(self, pid, sig):
        self.signals.append((sig, pid))
        self.stamps.append(self.time)
        if sig == signal.SIGKILL or pid not in self.stubborn:
            self.dead.add(pid)

    def alive(self, pid):
        return pid not in self.dead

    def sleep(self, seconds):
        self.time += seconds

    def clock(self):
        return self.time

    def now(self):
        return datetime(2026, 11, 24, 12, 33, 5, tzinfo=timezone.utc)

    def priority_get(self, pid):
        return LIMITS.jetsam_priority

    def priority_set(self, pid, priority):
        pass

    def io(self):
        return Io(
            self.available, self.table, self.services, self.omlx_pid, self.signal, self.alive,
            self.sleep, self.clock, self.now, self.priority_get, self.priority_set,
        )


def w1_and_w2(w1_gib=(8, 6, 6)):
    first, second, third = w1_gib
    return table_of(
        proc(300, 1, 501, W1, first, "node vitest run"),
        proc(301, 300, 501, W1, second),
        proc(302, 301, 501, W1, third),
        proc(310, 1, 501, W2, 4),
    )


class Daemon:
    def __init__(self, readings, table, stubborn=(), broken=()):
        self.fake = FakeIo(readings, table, stubborn, broken)
        self.io = self.fake.io()
        self.loop = Loop()
        self.record = {}
        self.lines = []
        self.stderr = stdio.StringIO()

    def sample(self, times=1):
        interval = None
        with contextlib.redirect_stderr(self.stderr):
            for _ in range(times):
                interval = enforce_once(LIMITS, OWNERS, self.io, self.loop, self.record, self.lines.append)
        return interval


class FloorTest(unittest.TestCase):
    def test_under_the_floor_for_the_declared_samples_the_largest_workload_ends_leaves_first(self):
        daemon = Daemon([10, 10, 10, 40], w1_and_w2(), stubborn=(302,))
        daemon.sample(2)
        self.assertEqual(daemon.fake.signals, [])
        daemon.sample()
        self.assertEqual(
            daemon.fake.signals,
            [(signal.SIGTERM, 302), (signal.SIGTERM, 301), (signal.SIGTERM, 300), (signal.SIGKILL, 302)],
        )
        self.assertGreaterEqual(daemon.fake.stamps[-1] - daemon.fake.stamps[0], LIMITS.grace_seconds)
        self.assertNotIn(310, [pid for _, pid in daemon.fake.signals])

    def test_the_next_workload_ends_only_while_the_floor_is_still_breached(self):
        rows = {
            "recovered": ([10, 10, 10, 40], [300], 1),
            "still_low": ([10, 10, 10, 12, 30], [300, 310], 2),
        }
        for name, (readings, roots, kills) in rows.items():
            with self.subTest(name):
                daemon = Daemon(readings, w1_and_w2())
                daemon.sample(3)
                termed = {pid for sig, pid in daemon.fake.signals if sig == signal.SIGTERM}
                self.assertEqual({300, 310} & termed, set(roots))
                self.assertEqual([e["root_pid"] for e in daemon.record["recent"]], roots)
                self.assertEqual(len(daemon.record["recent"]), kills)

    def test_a_workload_that_exits_on_sigterm_gets_no_sigkill(self):
        daemon = Daemon([10, 10, 10, 40], w1_and_w2())
        daemon.sample(3)
        self.assertEqual({sig for sig, _ in daemon.fake.signals}, {signal.SIGTERM})
        self.assertEqual(daemon.record["recent"][0]["signals"], "term")

    def test_each_kill_prints_one_line_and_records_it(self):
        daemon = Daemon([10, 10, 10, 40], w1_and_w2())
        daemon.sample(3)
        (line,) = daemon.lines
        entry = daemon.record["recent"][0]
        self.assertEqual(line, kill_line(entry))
        self.assertRegex(line, KILL_LINE)
        self.assertEqual(entry["workload"], f"agent:{W1}")
        self.assertIn("reason=floor", line)
        self.assertEqual(daemon.record["kills"], 1)
        self.assertEqual(entry["seq"], 1)
        self.assertEqual(entry["available_before_bytes"], 10 * GIB)
        self.assertEqual(entry["available_after_bytes"], 40 * GIB)
        carried = Daemon([10, 10, 10, 40], w1_and_w2())
        carried.record = {"kills": 50, "recent": [{"seq": seq} for seq in range(1, 51)]}
        carried.sample(3)
        self.assertEqual(carried.record["kills"], 51)
        self.assertEqual([e["seq"] for e in carried.record["recent"]], list(range(2, 52)))

    def test_the_daemon_writes_only_its_record_and_never_follows_a_symlink(self):
        with tempfile.TemporaryDirectory() as scratch:
            directory = Path(scratch)
            target = directory / "target"
            target.write_text("keep\n")
            record_path = directory / "floor.json"
            log_path = directory / "memory-watch.log"
            record_path.symlink_to(target)
            log_path.symlink_to(target)
            daemon = Daemon([10, 10, 10, 40], w1_and_w2())
            lines = []
            with contextlib.redirect_stderr(daemon.stderr):
                for _ in range(3):
                    step(LIMITS, OWNERS, daemon.io, daemon.loop, daemon.record, record_path, lines.append)
            self.assertEqual(target.read_text(), "keep\n")
            self.assertFalse(record_path.is_symlink())
            self.assertEqual(json.loads(record_path.read_text())["kills"], 1)
            self.assertTrue(log_path.is_symlink())
            self.assertEqual(os.readlink(log_path), str(target))
            self.assertEqual(
                sorted(p.name for p in directory.iterdir()), ["floor.json", "memory-watch.log", "target"]
            )
            self.assertEqual(len(lines), 1)

    def test_an_unreadable_protection_input_ends_nothing(self):
        for name in ("table", "services", "omlx_pid", "available"):
            with self.subTest(name):
                daemon = Daemon([10], w1_and_w2(), broken=(name,))
                interval = daemon.sample(3)
                self.assertEqual(daemon.fake.signals, [])
                self.assertIn(f"{name} could not run", daemon.stderr.getvalue())
                if name == "available":
                    self.assertEqual(interval, LIMITS.fast_seconds)

    def test_a_breach_with_no_workload_logs_once_per_episode(self):
        only_protected = table_of(proc(400, 1, 501, "/Users/anis/Projects/nix-config", 50))
        daemon = Daemon([10, 10, 10, 10, 50, 10, 10, 10, 10], only_protected)
        daemon.sample(9)
        self.assertEqual(daemon.fake.signals, [])
        self.assertEqual(len(daemon.lines), 2)
        for line in daemon.lines:
            self.assertRegex(line, UNMET_LINE.format(available="10.0", largest="0.0"))


W3 = "/Users/anis/Projects/jarbird/.worktrees/w3"
W4 = "/Users/anis/Projects/jarbird/.worktrees/w4"
UNMET_LINE = r"^2026-11-24T12:33:05\+00:00 floor_unmet available_gib={available} largest_gib={largest}\n$"


def trees(*sizes):
    roots = (W1, W2, W3, W4)
    return table_of(*(proc(300 + 10 * i, 1, 501, roots[i], gib) for i, gib in enumerate(sizes)))


class UsefulKillTest(unittest.TestCase):
    def test_no_tree_under_the_declared_minimum_is_ended_even_when_it_would_reach_the_floor(self):
        rows = {
            "small_trees_at_13": ([13], (0.1, 0.5, 0.9)),
            "small_tree_that_would_reach_the_floor": ([15.5], (0.6,)),
        }
        for name, (readings, sizes) in rows.items():
            with self.subTest(name):
                daemon = Daemon(readings, trees(*sizes))
                daemon.sample(3)
                self.assertEqual(daemon.fake.signals, [])
                self.assertEqual(daemon.record.get("kills", 0), 0)

    def test_a_tree_whose_end_still_leaves_memory_under_the_floor_is_not_ended(self):
        rows = {
            "just_short": ([13, 13, 13, 40], (0.1, 0.5, 2.9), []),
            "exactly_over": ([13, 13, 13, 40], (0.1, 0.5, 3.0), [320]),
            "largest_of_two_that_help_ends_not_the_smaller": ([13, 13, 13, 40], (4.0, 5.0, 1.5), [310]),
            "a_four_gib_tree_among_small_ones": ([13, 13, 13, 40], (0.1, 0.5, 2.0, 4.0), [330]),
        }
        for name, (readings, sizes, expected) in rows.items():
            with self.subTest(name):
                daemon = Daemon(readings, trees(*sizes))
                daemon.sample(3)
                termed = [pid for sig, pid in daemon.fake.signals if sig == signal.SIGTERM]
                self.assertEqual(termed, expected)
                self.assertEqual([e["root_pid"] for e in daemon.record.get("recent", [])], expected)

    def test_an_episode_with_no_candidate_that_helps_logs_and_records_once(self):
        daemon = Daemon([13] * 8 + [50] + [13] * 4, trees(0.1, 0.5, 2.0))
        daemon.sample(8)
        self.assertEqual(daemon.fake.signals, [])
        (line,) = daemon.lines
        self.assertRegex(line, UNMET_LINE.format(available="13.0", largest="2.0"))
        self.assertEqual(daemon.record["floor_unmets"], 1)
        (entry,) = daemon.record["floor_unmet_recent"]
        self.assertEqual((entry["seq"], entry["available_bytes"], entry["largest_bytes"]), (1, 13 * GIB, 2 * GIB))
        daemon.sample(5)
        self.assertEqual(len(daemon.lines), 2)
        self.assertEqual(daemon.record["floor_unmets"], 2)
        self.assertEqual([e["seq"] for e in daemon.record["floor_unmet_recent"]], [1, 2])

    def test_a_healthy_sample_records_no_episodes_so_the_first_one_is_countable(self):
        daemon = Daemon([20], trees(2.0))
        daemon.sample()
        self.assertEqual((daemon.record["floor_unmets"], daemon.record["floor_unmet_recent"]), (0, []))

    def test_a_breach_after_a_kill_and_a_recovery_is_a_new_episode(self):
        daemon = Daemon([13, 13, 13, 13, 40, 13, 13, 13], trees(2.0))
        daemon.sample(3)
        self.assertEqual(daemon.record["floor_unmets"], 1)
        # A tree that helps arrives and is ended, memory recovers, then falls again.
        daemon.fake.base = trees(2.0, 4.0)
        daemon.sample(1)
        self.assertEqual(daemon.record["kills"], 1)
        daemon.sample(3)
        self.assertEqual(daemon.record["floor_unmets"], 2)
        self.assertEqual(len(daemon.lines), 3)

    def test_a_restart_in_an_open_episode_does_not_open_another(self):
        daemon = Daemon([13], trees(2.0))
        daemon.sample(3)
        self.assertEqual(daemon.record["floor_unmets"], 1)
        again = Daemon([13], trees(2.0))
        again.record = json.loads(json.dumps(daemon.record))
        again.loop = restore_loop(again.record)
        again.sample(3)
        self.assertEqual((again.lines, again.record["floor_unmets"]), ([], 1))
        again.fake.readings = [40]
        again.sample(1)
        again.fake.readings = [13]
        again.sample(3)
        self.assertEqual(again.record["floor_unmets"], 2)


class OmlxPidReadingTest(unittest.TestCase):

    def launchctl(self, directory, code, out=""):
        path = Path(directory) / "launchctl"
        path.write_text(f"#!/bin/sh\ncat <<'EOF'\n{out}\nEOF\nexit {code}\n")
        path.chmod(0o755)
        return str(path)

    def test_a_job_that_is_not_loaded_has_no_pid_so_kills_stay_on(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertIsNone(read_omlx_pid(self.launchctl(directory, 113), "org.nixos.omlx"))

    def test_any_other_launchctl_failure_is_unreadable(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ReadingError, "launchctl exited 1$"):
                read_omlx_pid(self.launchctl(directory, 1), "org.nixos.omlx")


class RunBoundTest(unittest.TestCase):
    def test_a_workload_over_the_run_bound_ends_while_memory_is_over_the_floor(self):
        table = table_of(
            proc(300, 1, 501, W1, 30, "node vitest run"),
            proc(310, 1, 501, W2, 20),
        )
        daemon = Daemon([100], table)
        daemon.sample()
        self.assertEqual([pid for _, pid in daemon.fake.signals], [300])
        (line,) = daemon.lines
        self.assertIn("reason=run_bound", line)
        (entry,) = daemon.record["recent"]
        self.assertEqual(entry["reason"], "run_bound")
        self.assertEqual(daemon.record["kills"], 1)

    def test_an_agent_tree_outside_every_root_over_the_run_bound_is_ended(self):
        daemon = Daemon([100], session_tree(30))
        daemon.sample()
        self.assertEqual(daemon.fake.signals, [(signal.SIGTERM, 301), (signal.SIGTERM, 300)])
        (line,) = daemon.lines
        self.assertIn(" owner=anis workload=agent:session:300 root_pid=300 ", line)
        self.assertIn("reason=run_bound", line)
        self.assertEqual(daemon.record["recent"][0]["workload"], "agent:session:300")


class CadenceTest(unittest.TestCase):
    def test_the_interval_is_fast_while_memory_falls_or_sits_near_the_floor(self):
        rows = [
            (31 * GIB, None, 0, 2),
            (33 * GIB, None, 0, 10),
            (50 * GIB, 53 * GIB, 0, 2),
            (50 * GIB, 51 * GIB, 0, 10),
            (60 * GIB, 60 * GIB, 1, 2),
        ]
        for available, previous, streak, expected in rows:
            with self.subTest(available=available / GIB, previous=previous, streak=streak):
                self.assertEqual(next_interval(LIMITS, available, previous, streak), expected)


class CommandTest(unittest.TestCase):
    def test_the_floor_daemon_is_a_row_of_the_command_table(self):
        lines = (ROOT / "lib" / "agent-tools.nix").read_text().splitlines()
        self.assertEqual(lines.count('    "memory-floor" = "hosts.memory_floor";'), 1)
        verdicts = json.loads((ROOT / "python/agent_tools/delivery/command_verdicts.json").read_text())
        self.assertIsNone(verdicts["memory-floor"])
        env = {**os.environ, "PYTHONPATH": str(ROOT / "python")}
        base = [sys.executable, "-m", "agent_tools.hosts.memory_floor"]
        top = subprocess.run(base + ["--help"], capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(top.returncode, 0)
        self.assertIn("enforce", top.stdout)
        enforce = subprocess.run(base + ["enforce", "--help"], capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(enforce.returncode, 0)
        self.assertNotIn("--watch-log", enforce.stdout)
        self.assertIn("--agent-session", enforce.stdout)


if __name__ == "__main__":
    unittest.main()
