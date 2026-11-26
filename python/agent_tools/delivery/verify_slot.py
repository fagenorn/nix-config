"""`verify-slot`: run one command while holding one of this host's verify slots (issue 1383).

    verify-slot run [--wait-limit SECONDS] [--live] [--report PATH] -- ARGV...
    verify-slot report [--hours N]

A verify run is heavy, and several runs may start on one host at once. `run` admits at most
the host's declared count of them at a time: it takes one slot, runs `ARGV` with this
process's stdin, stdout, stderr, working directory and environment, and gives the slot back
when the command ends. Wrap each local verification command in it.

Slots. They are the files `slot-0.lock` .. `slot-<count-1>.lock` in one directory that
belongs to the host, never to an account: `DEFAULT_SLOT_DIR` (`/tmp/agent-verify-slots`), or
the directory named by the environment variable `VERIFY_SLOT_DIR` when it is set (a seam for
tests and for a host that keeps its slots elsewhere). The directory is made with mode 1777
and each lock file with mode 0666, so every local account takes its slots from the same
files. A slot is held by an exclusive `flock` on its file, taken by this process and never
passed to the command (the descriptor is not inheritable and the child starts with
`close_fds`). The kernel drops the lock when this process ends, whatever the cause, so a
holder killed by SIGKILL gives its slot back even while its command survives (D3); nothing is
recorded in the slot file beyond the holder's description and nothing goes stale. A live holder
is never preempted: a waiter takes a slot only once its holder has ended. Waiters poll every
`POLL_SECONDS` and are served in arrival order, every live waiter before every ordinary one (see
`--live` and Queue).

`--live` (issue 1434) marks a live-fault run, which waits ahead of every ordinary run and
never stops one in progress. While it waits it holds a shared `flock` on the marker file
`LIVE_MARKER` (`live-waiting.lock`) in the slot directory, created with mode 0666 like a slot
file so every account can lock it; it is not a slot and no slot count includes it. The live
run registers with a non-blocking lock retried every `REGISTER_RETRY_SECONDS` inside its
timed, signal-aware wait, so a process that stalls while probing the marker delays neither
`--wait-limit` nor a signal. The run drops the marker once it holds a slot or ends for any
other reason, and the kernel drops it when the waiter dies, so a SIGKILLed live waiter frees
the ordinary runs at once. An ordinary run that took a slot checks the marker last and, while
any live waiter holds it, gives the slot back and waits: it prints `DEFERRING_LINE` once
instead of `WAITING_LINE`. A slot that a live run did not yet hold is thereby left to the live
waiter, and a run in progress is never preempted.

The check is an exclusive non-blocking probe of the marker, which another ordinary run's
probe would also fail, so ordinary probes take turns: each holds an exclusive `flock` on the
guard file `LIVE_PROBE` (`live-probe.lock`, also mode 0666) around its probe, and a live run
never takes it. A probe that finds the guard taken retries for up to `PROBE_SECONDS`; a probe
that still cannot take it gives its slot back and waits one poll without deferring. A marker
or guard that cannot be opened, for example a directory in its place, is a setup error (exit
2) and the slot just taken is closed.

Admission counts every live holder, in whichever slot file. A run that took a slot checks
that the holders of all `slot-*.lock` files, itself included, number at most the declared
count, and gives its slot back and waits otherwise. A count lowered while a higher-numbered
slot is still held therefore never admits a run beside that holder.

Repositories. `verify-slot run` never admits two holders of one repository at once, since
two suites of one project share resources such as a single test database. The
repository is the `origin` remote of the working directory, normalized to `owner/repo` and
lowercased; a run outside a repository, or in one without `origin`, is its own group and is
excluded by no other run. A holder takes an exclusive non-blocking `flock` on `repo-<digest>.lock`
(`GROUP_LOCK`) in the slot directory only after it took its slot and passed the count recheck,
and gives the slot back and waits while another holder has it. The lock is taken after the slot
so a waiter holds neither and a live waiter still goes first (ADR-delivery-016 D6): ordinary
runs of other repositories defer to a live run only while its repository is under the limit:
a live waiter that its repository holds back holds no marker and gets no priority. Live runs
take the repository lock like ordinary ones. The lock file is not a slot file and no count
includes it, and it is held like a slot (a descriptor the command does not inherit), so a
SIGKILLed holder frees its repository at once.

Queue (ADR-delivery-022). A waiter joins by creating a numbered ticket file in the slot
directory under `queue.lock` (see `agent_tools.delivery.verify_queue`) and holds an exclusive
`flock` on it while it waits, so a SIGKILLed waiter leaves the queue at once. A holder writes
its repository and command into its slot file, which is how a waiter counts the holders of each
repository. Free slots go one at a time, in service order (live waiters, then ticket number),
to the waiters whose repository holds fewer slots than `REPOSITORY_LIMIT`; only the first
admitted waiter takes a slot, so no later waiter takes one before it. A waiter that its
repository holds back keeps its place and blocks no one. An ordinary run still probes the live
marker when it takes a slot, so it defers to a waiting live run of an older `verify-slot`; while
a live ticket is queued the marker is not probed, since the queue already serves live waiters first
and a queued live waiter that its repository holds back may hold the marker until its next poll.
A run that reaches `--wait-limit` keeps its ticket reserved, unlocked and holding back no
waiter; the same argv in the same working directory takes the place back while the reservation is
under `RESUME_SECONDS` old or while a waiter that joined after it still waits. A run ended by a
signal or an error gives its ticket up.

Short lane. The `verify_short_lane` member of the host declaration lists, per repository, the
exact argv vectors of short commands and the count of short slots. A run whose repository and
whole argv match one runs in the short lane: it queues on `short-ticket-*.lock` tickets and
takes one of `short-slot-<i>.lock` (`verify_queue.slot_name`), so it never takes a long slot or
a long ticket and a long run never takes a short one. It takes no repository lock, so any number
of short runs of one repository may hold slots at once, and no marker: it neither registers one
nor defers to one. Within the lane free slots go to the first waiters in service order, live
waiters first, then ticket number. Any other run, including the same argv in another repository,
takes the long lane as before.

History. Every run that got past setup appends one line to `history.jsonl` in the slot directory
(see `agent_tools.delivery.verify_history`), after it gave its slot and repository lock back:
a run that took a slot, one that reached `--wait-limit` and one signalled while it waited. A run
that held no slot records `held_seconds: null`. The line's `place` is the place the run joined the
queue at, the place it took back for a resumed request, or null when it never joined. Its `lane` is
`long` or `short`, the lane the run queued in. A setup or
usage error records nothing. A failed append prints `HISTORY_FAILED_LINE` once and leaves the exit
code alone. `--report PATH` writes the run's history entry, the same JSON object as its
`history.jsonl` line, to PATH. A caller reads it to learn the run's wait and hold, and a path that
cannot be written is reported and changes nothing.

Report. `verify-slot report [--hours N]` reads `history.jsonl` and prints one stdout line per
repository whose runs started in the last N hours (`DEFAULT_REPORT_HOURS`, 24; a positive
integer): the runs, the median, 90th percentile and total of the hold, and the median and 90th
percentile of the wait, in whole seconds (`agent_tools.delivery.verify_history` has the exact
line). A repository whose hold median is strictly above the `verify_budget_seconds` member of the
host declaration is marked ` over budget <budget>s`; with no declaration file or no such member
nothing is marked. A line of the history that cannot be read is skipped, and `REPORT_SKIPPED_LINE`
goes once to stderr when any was. The report creates no file and no directory, and an absent
history prints nothing. It exits 0, or 2 for a usage error (`--`, a bad `--hours`), an invalid
declaration or a history that cannot be read.

Count (D1). It is the `verify_slots` member of the host declaration
(`agent_tools.delivery.host_admission`), `DEFAULT_VERIFY_SLOTS` (1) when the declaration
file is absent. A declaration entry that exists and is invalid, or is not a file, is a setup
error: nothing runs. `HOME` locates the declaration, so an unset or empty `HOME` is a setup
error too.

`--wait-limit SECONDS` (a positive integer) bounds the wait for a slot; without it the wait
has no limit. The limit is checked before each further try, so a slot freed after it is not
taken.

stderr lines of its own (stdout is the command's alone). A run that finds every slot taken
prints `WAITING_LINE` once when it starts to wait; an ordinary run that gave a slot back to a
live waiter prints `DEFERRING_LINE` once; a run that gave a slot back because another holder
has its repository prints `SAME_REPOSITORY_LINE` once; one that waits behind earlier waiters
prints `QUEUED_LINE` once. A waiter follows its reason line with `PLACE_LINE`, its place in line
and the slots' holders, and prints it again whenever either changes. A run that waited and then
took a slot prints `WAITED_LINE` once, before the command starts. A run that took a slot at once
prints nothing of its own. A run that reaches `--wait-limit` prints `NO_SLOT_LINE` and runs
nothing. A short command still running at its bound prints `SHORT_BOUND_LINE` once. A command
that cannot start prints `verify-slot: cannot start <argv0>: <error>`. A run
whose history line cannot be appended prints `HISTORY_FAILED_LINE` once.

Exit codes (D8). The command's own code when it ran; a command ended by signal `s` gives
`128 + s`. 2 for a usage or setup error (no `--`, no command after it, a bad `--wait-limit`,
an unset or empty `HOME`, an invalid declaration, a slot directory that cannot be made),
with nothing run. 75 (`NO_SLOT_EXIT`) when no slot came free within `--wait-limit`, with
nothing run and its place in line reserved. 124 (`BOUND_EXIT`) when a short command was still
running at its lane's bound and was ended (see Signals). 127 when the command cannot start; the
slot is freed.

Signals. SIGTERM, SIGHUP and SIGINT are handled. While the command runs, the signal is
forwarded to it and the exit code is `128 + signal` once it has ended (SIGTERM gives 143); a
short command runs in its own process group and the signal goes to the whole group. A short
command still running `bound_seconds` after it started has its group sent SIGTERM and, once
`SHORT_GRACE_SECONDS` have passed with a member left, SIGKILL; the slot is given back only
after the group is gone, and a signal received meanwhile still gives `128 + signal`. The group
is told before the bound line is written, and a stderr that cannot be written changes neither.
A forwarded signal gets the same wait and KILL for a member that ignores it. When stdin is a
terminal this run holds in the foreground, the short command's group takes the foreground and
this run takes it back when the command ends. A `bound_seconds` above `threading.TIMEOUT_MAX`
is an invalid declaration.
While waiting for a slot, the signal ends the wait with `128 + signal` and nothing runs.
The slot is released on every outcome. SIGKILL cannot be forwarded: the command goes on
running, and the slot is free as soon as this process is gone.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import signal
import stat
import subprocess
import sys
import time

from agent_tools.delivery import host_admission, verify_history, verify_queue
from agent_tools.project_contract.derived_values import normalize_remote_url

NO_SLOT_LINE = "verify-slot: no verify slot came free within {limit}s; nothing ran"
WAITING_LINE = "verify-slot: all {count} verify slots of this host are taken; waiting"
WAITED_LINE = "verify-slot: waited {seconds:.1f}s for a verify slot"
DEFERRING_LINE = "verify-slot: a live-fault verify run is waiting for a slot; this run waits behind it"
SAME_REPOSITORY_LINE = "verify-slot: a verify run of this repository holds a verify slot; waiting"
PLACE_LINE = "verify-slot: this run is number {place} in line for a verify slot; now running: {holders}"
QUEUED_LINE = "verify-slot: earlier verify runs are waiting for a slot; this run waits its turn"
HISTORY_FAILED_LINE = "verify-slot: cannot record this run in {path}: {error}"
REPORT_FAILED_LINE = "verify-slot: cannot write the report {path}: {error}"
REPORT_SKIPPED_LINE = "verify-slot: skipped {count} unreadable lines of {path}"
GIT_TIMEOUT_SECONDS = 10
LIVE_MARKER = "live-waiting.lock"
LIVE_PROBE = "live-probe.lock"
NO_SLOT_EXIT = 75
DEFAULT_REPORT_HOURS = 24
POLL_SECONDS = 0.2
REGISTER_RETRY_SECONDS = 0.005
PROBE_RETRY_SECONDS = 0.005
PROBE_SECONDS = 1.0
DEFAULT_SLOT_DIR = "/tmp/agent-verify-slots"
SLOT_DIR_ENV = "VERIFY_SLOT_DIR"
USAGE_EXIT = 2
REPOSITORY_LIMIT = 1
CANNOT_START_EXIT = 127
SHORT_BOUND_LINE = "verify-slot: this short command ran past its {bound}s bound and was ended"
BOUND_EXIT = 124
SHORT_GRACE_SECONDS = 5.0

_open_slot = verify_queue.open_shared
_held = verify_queue.held
GROUP_LOCK = verify_queue.GROUP_LOCK
group_lock_name = verify_queue.group_lock_name

_WAIT_LINES = {"taken": WAITING_LINE, "deferred": DEFERRING_LINE,
               "same_repository": SAME_REPOSITORY_LINE, "queued": QUEUED_LINE}
_HANDLED_SIGNALS = (signal.SIGTERM, signal.SIGHUP, signal.SIGINT)


class SlotError(Exception):
    """A usage or setup error; the command exits 2 and runs nothing."""


def _declaration() -> dict | None:
    """The validated host declaration, None when the file is absent; an invalid one is a `SlotError`."""
    try:
        return host_admission.load_declaration()
    except host_admission.DeclarationError as error:
        if error.reason_code == "declaration_missing":
            return None
        raise SlotError(f"the host declaration is invalid: {error}") from None


def slot_count() -> int:
    """The declared verify slot count, `DEFAULT_VERIFY_SLOTS` when no declaration exists."""
    declaration = _declaration()
    if declaration is None:
        return host_admission.DEFAULT_VERIFY_SLOTS
    return host_admission.verify_slots(declaration)


def slot_dir() -> Path:
    """The host's slot directory: `$VERIFY_SLOT_DIR` when set, else `DEFAULT_SLOT_DIR`."""
    return Path(os.environ.get(SLOT_DIR_ENV) or DEFAULT_SLOT_DIR)


def _prepare_dir(directory: Path) -> None:
    """Make the shared slot directory (sticky, world-writable) and refuse a non-directory."""
    directory.parent.mkdir(parents=True, exist_ok=True)
    old = os.umask(0)
    try:
        os.mkdir(directory, 0o1777)
    except FileExistsError:
        pass
    finally:
        os.umask(old)
    status = os.lstat(directory)
    if not stat.S_ISDIR(status.st_mode):
        raise SlotError(f"{directory} is not a directory")
    if status.st_uid == os.getuid() and stat.S_IMODE(status.st_mode) != 0o1777:
        os.chmod(directory, 0o1777)


def repository_group(cwd: Path) -> str | None:
    """The repository `cwd` belongs to: its normalized, lowercased `origin` remote, else None."""
    try:
        result = subprocess.run(
            ["git", "-C", str(cwd), "remote", "get-url", "origin"], stdin=subprocess.DEVNULL,
            capture_output=True, text=True, timeout=GIT_TIMEOUT_SECONDS)
    except (OSError, subprocess.TimeoutExpired):
        return None
    url = result.stdout.strip()
    if result.returncode != 0 or not url:
        return None
    return (normalize_remote_url(url) or url).lower()


def _say(line: str) -> None:
    sys.stderr.write(line + "\n")
    sys.stderr.flush()


class _Run:
    """One run's signal state: the signal received so far and the child to forward it to."""

    def __init__(self) -> None:
        self.received: int | None = None
        self.child: subprocess.Popen | None = None
        self.grouped = False

    def handle(self, signum: int, _frame: object) -> None:
        self.received = signum
        if self.child is not None:
            try:
                if self.grouped:
                    os.killpg(self.child.pid, signum)
                else:
                    self.child.send_signal(signum)
            except (OSError, ProcessLookupError):
                pass


def _live_waiting(directory: Path) -> bool | None:
    """Whether a live waiter holds the marker; `None` when another ordinary probe kept the guard.

    Ordinary probes take turns on the guard, so a probe never mistakes another probe's
    exclusive lock for a live waiter. An unopenable marker or guard raises `OSError`.
    """
    guard = _open_slot(directory / LIVE_PROBE)
    try:
        give_up = time.monotonic() + PROBE_SECONDS
        while True:
            try:
                fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= give_up:
                    return None
                time.sleep(PROBE_RETRY_SECONDS)
        try:
            marker = os.open(directory / LIVE_MARKER, os.O_RDWR)
        except FileNotFoundError:
            return False
        try:
            fcntl.flock(marker, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        finally:
            os.close(marker)
        return False
    finally:
        os.close(guard)


def _register_live(directory: Path) -> int | None:
    """The marker descriptor holding a shared lock, `None` while a probe holds it exclusively."""
    marker = _open_slot(directory / LIVE_MARKER)
    try:
        fcntl.flock(marker, fcntl.LOCK_SH | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(marker)
        return None
    except BaseException:
        os.close(marker)
        raise
    return marker


def _holders_beside(directory: Path, own: Path, lane: str = verify_queue.LONG_LANE) -> int:
    """The live holders of every slot file of `lane` but `own`, whatever their index."""
    return sum(1 for path in verify_queue.slot_files(directory, lane) if path != own and _held(path))


def _take_repository(directory: Path, group: str, repository_limit: int) -> int | None:
    """The first repository lock of `group` this process gets without blocking, else None."""
    for path in verify_queue.repository_lock_paths(directory, group, repository_limit):
        descriptor = _open_slot(path)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(descriptor)
            continue
        except BaseException:
            os.close(descriptor)
            raise
        return descriptor
    return None


def _try_slots(directory: Path, count: int, live: bool, group: str | None, repository_limit: int,
               probe_marker: bool = True,
               lane: str = verify_queue.LONG_LANE) -> tuple[tuple[int, int | None] | None, str | None]:
    """`((slot, group lock or None), None)` on a slot kept, else `(None, reason)` with nothing taken.

    A slot file that cannot be opened counts as taken, as it does for every holder count. A taken
    slot is kept only while the holders of all slot files, this one included, number at most
    `count`: a count lowered beneath a still-held higher slot is honoured (`taken`). Then, when
    `group` is set, it also takes one of the repository's `repository_limit` locks, and gives the
    slot back while every one is held (`same_repository`). An ordinary run lastly gives both back
    while a live waiter holds the marker (`deferred`); a live run skips that check, and so does a
    caller that passes `probe_marker=False`. The slot files are `lane`'s.
    """
    for index in range(count):
        path = directory / verify_queue.slot_name(lane, index)
        try:
            descriptor = _open_slot(path)
        except OSError:
            continue
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(descriptor)
            continue
        except BaseException:
            os.close(descriptor)
            raise
        if 1 + _holders_beside(directory, path, lane) > count:
            os.close(descriptor)
            return None, "taken"
        held_group = None
        if group is not None:
            try:
                held_group = _take_repository(directory, group, repository_limit)
            except BaseException:
                os.close(descriptor)
                raise
            if held_group is None:
                os.close(descriptor)
                return None, "same_repository"
        if not live and probe_marker:
            try:
                waiting = _live_waiting(directory)
            except BaseException:
                _close_all(descriptor, held_group)
                raise
            if waiting is not False:
                _close_all(descriptor, held_group)
                return None, "deferred" if waiting is True else "taken"
        return (descriptor, held_group), None
    return None, "taken"


def _close_all(*descriptors: int | None) -> None:
    for descriptor in descriptors:
        if descriptor is not None:
            os.close(descriptor)


def _bounded(pause: float, start: float, wait_limit: int | None) -> float:
    if wait_limit is None:
        return pause
    return max(0.0, min(pause, start + wait_limit - time.monotonic()))


def _decide(directory: Path, count: int, live: bool, group: str | None, key: str, command: str,
            ticket: verify_queue.Ticket | None, lane: str = verify_queue.LONG_LANE) -> tuple:
    """One decision under the queue lock: `(ticket, held, reason, eligible, place, holders)`.

    `held` is the slot taken, `reason` why the run waits (None while it waits for an earlier
    admitted waiter) and `eligible` whether its repository is under the limit (always, short lane).
    """
    short = lane == verify_queue.SHORT_LANE
    if ticket is None:
        ticket = verify_queue.join(directory, key, live, group, time.time(), lane=lane)
    queue = verify_queue.waiters(directory, ticket, time.time())
    holders = verify_queue.read_holders(directory, lane)
    free = max(0, count - len(holders))
    if short:
        admitted, eligible = verify_queue.short_admitted(queue, free), True
    else:
        counts = verify_queue.holder_counts(
            directory, holders, {waiter.repository for waiter in queue if waiter.repository},
            REPOSITORY_LIMIT)
        admitted = verify_queue.admitted(queue, counts, free, REPOSITORY_LIMIT)
        eligible = group is None or counts.get(group, 0) < REPOSITORY_LIMIT
    place = verify_queue.place(queue, ticket.seq)
    reason = None
    if admitted and admitted[0].seq == ticket.seq:
        # A live waiter in the queue is ordered ahead by `admitted`, and one held back by its
        # repository may still hold a marker it drops only at its next poll, so the marker speaks
        # only for a live waiter of an older `verify-slot`, which no ticket shows.
        if short:
            held, reason = _try_slots(directory, count, live, None, REPOSITORY_LIMIT,
                                      probe_marker=False, lane=lane)
        else:
            held, reason = _try_slots(directory, count, live, group, REPOSITORY_LIMIT,
                                      probe_marker=not any(waiter.live for waiter in queue))
        if held is not None:
            try:
                verify_queue.record_holder(held[0], group, command)
            except BaseException:
                _close_all(*held)
                raise
            verify_queue.leave(ticket)
            return None, held, None, eligible, place, holders
    elif not any(waiter.seq == ticket.seq for waiter in admitted):
        reason = "same_repository" if not eligible else "taken" if free == 0 else "queued"
    return ticket, None, reason, eligible, place, holders


def _acquire(directory: Path, count: int, wait_limit: int | None, run: _Run, live: bool,
             group: str | None, key: str,
             command: str,
             lane: str = verify_queue.LONG_LANE) -> tuple[tuple[int, int | None] | None, int | None, int | None]:
    """`(held, None, place)` on a taken slot, else `(None, exit code, place)` with nothing to run.

    `place` is where the run joined the queue, None if it never did. A live long-lane run holds the
    marker while it waits under the limit; a run leaving without a slot gives its ticket up.
    """
    marker = None
    ticket = None
    joined_place = None
    try:
        start = time.monotonic()
        waiting = contended = False
        eligible = True
        said: set[str] = set()
        last_place = None
        while True:
            if run.received is not None:
                return None, 128 + run.received, joined_place
            registering = live and lane == verify_queue.LONG_LANE and marker is None and eligible
            if ((waiting or contended or registering) and wait_limit is not None
                    and time.monotonic() - start >= wait_limit):
                _say(NO_SLOT_LINE.format(limit=wait_limit))
                if ticket is not None:
                    reserved, ticket = ticket, None
                    verify_queue.reserve(reserved, time.time())
                return None, NO_SLOT_EXIT, joined_place
            if registering:
                marker = _register_live(directory)
                if marker is None:
                    contended = True
                    time.sleep(_bounded(REGISTER_RETRY_SECONDS, start, wait_limit))
                    continue
            lock = verify_queue.lock_queue(directory)
            if lock is None:
                contended = True
                time.sleep(_bounded(REGISTER_RETRY_SECONDS, start, wait_limit))
                continue
            try:
                ticket, held, reason, eligible, place, holders = _decide(
                    directory, count, live, group, key, command, ticket, lane)
                if joined_place is None:
                    joined_place = place
                if marker is not None and not eligible and held is None:
                    os.close(marker)
                    marker = None
            finally:
                os.close(lock)
            if held is not None:
                if waiting:
                    _say(WAITED_LINE.format(seconds=time.monotonic() - start))
                return held, None, joined_place
            if reason is None:
                contended = True
            else:
                waiting = True
                if reason not in said:
                    said.add(reason)
                    _say(_WAIT_LINES[reason].format(count=count))
            if waiting:
                text = (place, verify_queue.holders_text(holders))
                if text != last_place:
                    last_place = text
                    _say(PLACE_LINE.format(place=place, holders=text[1]))
            time.sleep(_bounded(POLL_SECONDS, start, wait_limit))
    finally:
        if marker is not None:
            os.close(marker)
        if ticket is not None:
            verify_queue.leave(ticket)


def _group_alive(pid: int) -> bool:
    try:
        os.killpg(pid, 0)
    except (ProcessLookupError, PermissionError):  # macOS refuses a group of only zombies
        return False
    return True


def _kill_group(pid: int, signum: int) -> None:
    try:
        os.killpg(pid, signum)
    except (ProcessLookupError, OSError):
        pass


def _foreground(pgrp: int) -> None:
    """Make `pgrp` the foreground group of the terminal on stdin, whatever the signals say."""
    blocked = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGTTOU})
    try:
        os.tcsetpgrp(0, pgrp)
    except OSError:
        pass
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, blocked)


def _owns_terminal() -> bool:
    """Whether this process's group is the foreground group of the terminal on stdin."""
    try:
        return os.isatty(0) and os.tcgetpgrp(0) == os.getpgrp()
    except OSError:
        return False


def _reap_group(child: subprocess.Popen) -> None:
    """Wait the grace for a short child's group to go, KILL what is left, then wait for it to go."""
    pid = child.pid
    grace_end = time.monotonic() + SHORT_GRACE_SECONDS
    while (child.poll() is None or _group_alive(pid)) and time.monotonic() < grace_end:
        time.sleep(0.05)
    _kill_group(pid, signal.SIGKILL)  # a member that outlived the leader and the grace
    child.wait()
    settled = time.monotonic() + 1.0
    while _group_alive(pid) and time.monotonic() < settled:
        time.sleep(0.05)


def _end_group(child: subprocess.Popen, bound: int) -> int:
    """End a short child's whole group past its bound; the group is told first, the report is best effort."""
    _kill_group(child.pid, signal.SIGTERM)
    try:
        _say(SHORT_BOUND_LINE.format(bound=bound))
    except OSError:  # a caller that closed its stderr still gets the group ended and its slot held
        os.dup2(os.open(os.devnull, os.O_WRONLY), 2)  # the unwritten text must not fail the exit flush
    _reap_group(child)
    return BOUND_EXIT


def _wait_bounded(child: subprocess.Popen, bound: int) -> int:
    """The child's code, or `BOUND_EXIT` once it ran `bound` seconds and its group was ended."""
    end = time.monotonic() + bound
    while (remaining := end - time.monotonic()) > 0:
        try:
            return child.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            pass
    return _end_group(child, bound)


def _run_child(argv: list[str], run: _Run, bound: int | None = None) -> int:
    if run.received is not None:
        return 128 + run.received
    interactive = bound is not None and _owns_terminal()
    try:
        if bound is None:
            child = subprocess.Popen(argv)
        elif interactive:
            # Its own group, made the terminal's foreground before it runs, so a read of stdin does not stop it.
            child = subprocess.Popen(
                argv, process_group=0, preexec_fn=lambda: _foreground(os.getpgrp()))
        else:
            child = subprocess.Popen(argv, process_group=0)
    except OSError as error:
        _say(f"verify-slot: cannot start {argv[0]}: {error}")
        return CANNOT_START_EXIT
    run.grouped = bound is not None
    run.child = child
    # A signal that arrived while the child was being created found no child to forward to.
    if run.received is not None:
        run.handle(run.received, None)
    try:
        code = child.wait() if bound is None else _wait_bounded(child, bound)
        if bound is not None and (interactive or run.received is not None):
            # A forwarded signal ends the leader, not a member that ignores it; and the terminal's own
            # interrupt goes to the child's foreground group alone, so the wrapper never learns of it.
            _reap_group(child)
    finally:
        if interactive:
            _foreground(os.getpgrp())
    if run.received is not None:
        return 128 + run.received
    return 128 - code if code < 0 else code


def _record(directory: Path, entry: dict) -> None:
    """Append this run's history line; a failure is reported and never changes the exit code."""
    path = verify_history.history_path(directory)
    try:
        verify_history.append(path, entry)
    except (OSError, ValueError) as error:
        _say(HISTORY_FAILED_LINE.format(path=path, error=error))


def _report(path: Path, entry: dict) -> None:
    """Write this run's entry to `path`, replacing a file and never following a symlink."""
    line = json.dumps(entry, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(line)
    except (OSError, ValueError) as error:
        _say(REPORT_FAILED_LINE.format(path=path, error=error))


def run_command(argv: list[str], wait_limit: int | None, live: bool = False,
                report: str | None = None) -> int:
    home = os.environ.get("HOME")
    if not home:
        raise SlotError("HOME is unset or empty")
    try:
        group = repository_group(Path.cwd())
    except OSError:
        group = None
    declaration = _declaration()
    count = (host_admission.DEFAULT_VERIFY_SLOTS if declaration is None
             else host_admission.verify_slots(declaration))
    lane = verify_queue.LONG_LANE
    bound = None
    short = None if declaration is None else host_admission.short_command(declaration, group, argv)
    if short is not None:
        count, lane, bound = short[0], verify_queue.SHORT_LANE, short[1]
    directory = slot_dir()
    try:
        _prepare_dir(directory)
    except OSError as error:
        raise SlotError(f"cannot create {directory}: {error}") from None
    key = verify_queue.request_key(Path.cwd(), argv)
    command = " ".join(" ".join(argv).split()[:verify_history.COMMAND_WORDS])
    run = _Run()
    previous = {number: signal.signal(number, run.handle) for number in _HANDLED_SIGNALS}
    held = None
    joined = None
    acquired = False
    code = USAGE_EXIT
    started = datetime.now(timezone.utc)
    begin = taken = time.monotonic()
    waited, held_seconds = 0.0, None
    try:
        try:
            held, code, joined = _acquire(
                directory, count, wait_limit, run, live, group, key, command, lane)
        except OSError as error:
            raise SlotError(f"cannot take a slot in {directory}: {error}") from None
        acquired = True
        taken = time.monotonic()
        waited = taken - begin
        if held is None:
            return code
        code = _run_child(argv, run, bound)
        return code
    finally:
        if held is not None:
            try:
                verify_queue.clear_holder(held[0])
            except OSError:
                pass
            _close_all(held[1], held[0])
            held_seconds = time.monotonic() - taken
        for number, handler in previous.items():
            signal.signal(number, handler)
        if acquired:
            entry = verify_history.entry(group, argv, started, waited, held_seconds, code, joined, lane)
            _record(directory, entry)
            if report is not None:
                _report(Path(report), entry)


def report_command(hours: int) -> int:
    """Print each repository's hold and wait figures for the last `hours` hours."""
    try:
        budget = host_admission.verify_budget_seconds(host_admission.load_declaration())
    except host_admission.DeclarationError as error:
        if error.reason_code != "declaration_missing":
            raise SlotError(f"the host declaration is invalid: {error}") from None
        budget = None
    path = verify_history.history_path(slot_dir())
    try:
        records, skipped = verify_history.read(path)
    except OSError as error:
        raise SlotError(f"cannot read {path}: {error}") from None
    try:
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
    except OverflowError:
        since = datetime.min.replace(tzinfo=timezone.utc)
    for summary in verify_history.summarize(records, since):
        print(verify_history.report_line(summary, budget))
    if skipped:
        _say(REPORT_SKIPPED_LINE.format(count=skipped, path=path))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="verify-slot", description="Run a command while holding one of this host's verify slots.")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="run ARGV in a verify slot (use `--` before ARGV)",
                              usage="verify-slot run [--wait-limit SECONDS] [--live] [--report PATH] -- ARGV...")
    run.add_argument("--wait-limit", type=int, default=None, metavar="SECONDS",
                     help="give up with exit 75 when no slot comes free within this many seconds")
    run.add_argument("--live", action="store_true",
                     help="wait ahead of every ordinary run, never stopping a run in progress")
    run.add_argument("--report", default=None, metavar="PATH",
                     help="write this run's history entry to PATH")
    report = commands.add_parser("report", help="print each repository's hold and wait figures",
                                 usage="verify-slot report [--hours N]")
    report.add_argument("--hours", type=int, default=DEFAULT_REPORT_HOURS, metavar="N",
                        help="report the runs that started in the last N hours (default 24)")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    command: list[str] = []
    if "--" in arguments:
        split = arguments.index("--")
        arguments, command = arguments[:split], arguments[split + 1:]
        found_separator = True
    else:
        found_separator = False
    parser = build_parser()
    args = parser.parse_args(arguments)
    if args.command == "report":
        if found_separator:
            parser.error("report takes no command")
        if args.hours < 1:
            parser.error("--hours must be a positive integer")
    else:
        if args.wait_limit is not None and args.wait_limit < 1:
            parser.error("--wait-limit must be a positive integer")
        if not found_separator or not command:
            parser.error("run needs `--` followed by the command to run")
    try:
        if args.command == "report":
            return report_command(args.hours)
        return run_command(command, args.wait_limit, args.live, args.report)
    except SlotError as error:
        _say(f"verify-slot: {error}")
        return USAGE_EXIT


if __name__ == "__main__":
    sys.exit(main())
