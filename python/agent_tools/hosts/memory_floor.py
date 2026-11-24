"""The eleven-m5 memory floor: which processes are workloads and which are protected.

A workload is a group of processes the floor may end together to give memory back. Every workload
belongs to a declared owner: the agent user, or a CI runner user.

- An agent-user process is a direct member of the workload `agent:<dir>` when its cwd is inside a
  declared root glob (`<dir>` is the part of the cwd the glob matched); otherwise it joins the
  workload of its nearest ancestor, and has none when the walk meets a protected or undeclared
  ancestor, or pid 1.
- A runner-user `Runner.Worker` starts the workload `ci:<user>:<pid>` and its descendants join it;
  a runner-user process whose parent is pid 1 and that is not protected joins `ci:<user>:orphans`.
- A process of any other user is never in a workload, wherever its cwd or ancestors are.

Protected processes are never in a workload: pids 0 and 1, the oMLX server and every descendant of
it, and each service process the host runs for the system (the process only, not its children).

The functions here are pure over a process table, so the selection runs against stubbed tables.
"""

import fnmatch
from dataclasses import dataclass

GIB = 1024**3
PROG = "memory-floor"
WORKER = "Runner.Worker"


@dataclass(frozen=True)
class Proc:
    pid: int
    ppid: int
    uid: int
    command: str
    cwd: str | None
    footprint: int


@dataclass(frozen=True)
class Owners:
    agent_uid: int
    agent_user: str
    agent_roots: tuple[str, ...]
    runners: tuple[tuple[int, str], ...]


@dataclass(frozen=True)
class Workload:
    key: str
    owner: str
    root_pid: int
    root_command: str
    pids: tuple[int, ...]
    size: int


def parse_ps(text: str) -> dict[int, tuple[int, int, str]]:
    table = {}
    for line in text.splitlines():
        fields = line.split(None, 3)
        if len(fields) < 3:
            continue
        try:
            pid, ppid, uid = int(fields[0]), int(fields[1]), int(fields[2])
        except ValueError:
            continue
        table[pid] = (ppid, uid, fields[3] if len(fields) > 3 else "")
    if not table:
        raise ValueError("no process line parsed from ps output")
    return table


def parse_launchctl_list(text: str) -> set[int]:
    pids = set()
    for line in text.splitlines()[1:]:
        first = line.split("\t", 1)[0].strip()
        if first.isdigit():
            pids.add(int(first))
    return pids


def root_of(cwd: str | None, roots: tuple[str, ...]) -> str | None:
    if not cwd:
        return None
    parts = cwd.split("/")
    for root in roots:
        globs = root.split("/")
        count = len(globs)
        if len(parts) >= count and all(
            fnmatch.fnmatchcase(part, pattern) for part, pattern in zip(parts, globs)
        ):
            return "/".join(parts[:count])
    return None


def protected_pids(table: dict[int, Proc], omlx_pid: int | None, service_pids: set[int]) -> set[int]:
    protected = {0, 1} | set(service_pids)
    if omlx_pid is not None:
        protected.add(omlx_pid)
        children: dict[int, list[int]] = {}
        for proc in table.values():
            children.setdefault(proc.ppid, []).append(proc.pid)
        pending = [omlx_pid]
        while pending:
            for child in children.get(pending.pop(), ()):
                if child not in protected:
                    protected.add(child)
                    pending.append(child)
    return protected


def _program(command: str) -> str:
    first = command.split(None, 1)
    return first[0].rsplit("/", 1)[-1] if first else ""


def _depth(table: dict[int, Proc], pid: int) -> int:
    seen = {pid}
    depth = 0
    parent = table[pid].ppid
    while parent in table and parent not in seen:
        seen.add(parent)
        depth += 1
        parent = table[parent].ppid
    return depth


def workloads(table: dict[int, Proc], owners: Owners, protected: set[int]) -> list[Workload]:
    runner_names = dict(owners.runners)
    assigned: dict[int, tuple[str, str] | None] = {}

    def assign(pid: int, visiting: frozenset[int] = frozenset()) -> tuple[str, str] | None:
        if pid in assigned:
            return assigned[pid]
        proc = table.get(pid)
        if proc is None or pid <= 1 or pid in protected or pid in visiting:
            return None
        found = None
        if proc.uid == owners.agent_uid:
            matched = root_of(proc.cwd, owners.agent_roots)
            if matched is not None:
                found = (f"agent:{matched}", owners.agent_user)
            else:
                found = assign(proc.ppid, visiting | {pid})
                if found is not None and found[1] != owners.agent_user:
                    found = None
        elif proc.uid in runner_names:
            name = runner_names[proc.uid]
            if _program(proc.command) == WORKER:
                found = (f"ci:{name}:{pid}", name)
            elif proc.ppid == 1:
                found = (f"ci:{name}:orphans", name)
            else:
                found = assign(proc.ppid, visiting | {pid})
                if found is not None and found[1] != name:
                    found = None
        assigned[pid] = found
        return found

    members: dict[str, tuple[str, list[int]]] = {}
    for pid in table:
        found = assign(pid)
        if found is not None:
            members.setdefault(found[0], (found[1], []))[1].append(pid)

    result = []
    for key, (owner, pids) in members.items():
        depths = {pid: _depth(table, pid) for pid in pids}
        root = min(pids, key=lambda pid: (depths[pid], pid))
        ordered = tuple(sorted(pids, key=lambda pid: (-depths[pid], -pid)))
        result.append(
            Workload(
                key=key,
                owner=owner,
                root_pid=root,
                root_command=table[root].command,
                pids=ordered,
                size=sum(table[pid].footprint for pid in pids),
            )
        )
    return sorted(result, key=lambda w: (-w.size, w.key))
