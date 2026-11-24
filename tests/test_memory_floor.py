"""The eleven-m5 memory floor's workload selection: which processes a workload holds and which are protected.

Calls `agent_tools.hosts.memory_floor` directly against stubbed process tables (no libproc, no
kernel call, so it runs on Linux): what protects a process, which declared owner a process belongs
to, how agent processes group by the declared root their cwd or ancestor is in, how CI jobs and
runner orphans are workloads of their runner user, and the order of a workload's pids.
Run: just agent-workflow-tests
"""

import unittest

from agent_tools.hosts.memory_floor import (
    GIB,
    Owners,
    Proc,
    parse_launchctl_list,
    parse_ps,
    protected_pids,
    workloads,
)

TIER = "fast"

W1 = "/Users/anis/Projects/jarbird/.worktrees/w1"
W2 = "/Users/anis/Projects/jarbird/.worktrees/w2"
OWNERS = Owners(
    501,
    "anis",
    ("/Users/anis/Projects/*/.worktrees/*", "/private/tmp/verify-pending-*"),
    ((534, "_github-runner-jarbird"),),
)


def proc(pid, ppid, uid, cwd, gib, command="node"):
    return Proc(pid, ppid, uid, command, cwd, int(gib * GIB))


def table_of(*procs):
    return {p.pid: p for p in procs}


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


if __name__ == "__main__":
    unittest.main()
