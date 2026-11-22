"""`verify-slot`: run one command while holding one of this host's verify slots (issue 1383).

    verify-slot run [--wait-limit SECONDS] -- ARGV...

A verify run is heavy, and several runs may start on one host at once. `run` admits at most
the host's declared count of them at a time: it takes one slot, runs `ARGV` with this
process's stdin, stdout, stderr, working directory and environment, and gives the slot back
when the command ends. Wrap each local verification command in it.

Slots. They are the files `slot-0.lock` .. `slot-<count-1>.lock` in
`$HOME/.agents/state/verify-slots/` (created with mode 0700). A slot is held by an exclusive
`flock` on its file, taken by this process and never passed to the command (the descriptor
is not inheritable and the child starts with `close_fds`). The kernel drops the lock when
this process ends, whatever the cause, so a holder killed by SIGKILL gives its slot back
even while its command survives (D3); nothing is recorded in the files and nothing goes
stale. A live holder is never preempted: a waiter takes a slot only once its holder has
ended. Waiters poll every `POLL_SECONDS` and no order among them is promised (no FIFO).

Count (D1). It is the `verify_slots` member of the host declaration
(`agent_tools.delivery.host_admission`), `DEFAULT_VERIFY_SLOTS` (1) when the declaration
file is absent. A declaration that exists and is invalid is a setup error: nothing runs.

`--wait-limit SECONDS` (a positive integer) bounds the wait for a slot; without it the wait
has no limit.

stderr lines of its own (stdout is the command's alone). A run that finds every slot taken
prints `WAITING_LINE` once when it starts to wait. A run that waited and then took a slot
prints `WAITED_LINE` once, before the command starts. A run that took a slot at once prints
nothing of its own. A run that reaches `--wait-limit` prints `NO_SLOT_LINE` and runs
nothing. A command that cannot start prints `verify-slot: cannot start <argv0>: <error>`.

Exit codes (D8). The command's own code when it ran; a command ended by signal `s` gives
`128 + s`. 2 for a usage or setup error (no `--`, no command after it, a bad `--wait-limit`,
an unset or empty `HOME`, an invalid declaration, a slot directory that cannot be made),
with nothing run. 75 (`NO_SLOT_EXIT`) when no slot came free within `--wait-limit`, with
nothing run. 127 when the command cannot start; the slot is freed.

Signals. SIGTERM, SIGHUP and SIGINT are handled. While the command runs, the signal is
forwarded to it and the exit code is `128 + signal` once it has ended (SIGTERM gives 143).
While waiting for a slot, the signal ends the wait with `128 + signal` and nothing runs.
The slot is released on every outcome. SIGKILL cannot be forwarded: the command goes on
running, and the slot is free as soon as this process is gone.
"""
from __future__ import annotations

import argparse
import fcntl
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from agent_tools.delivery import host_admission

NO_SLOT_LINE = "verify-slot: no verify slot came free within {limit}s; nothing ran"
WAITING_LINE = "verify-slot: all {count} verify slots of this host are taken; waiting"
WAITED_LINE = "verify-slot: waited {seconds:.1f}s for a verify slot"
NO_SLOT_EXIT = 75
POLL_SECONDS = 0.2
USAGE_EXIT = 2
CANNOT_START_EXIT = 127

_HANDLED_SIGNALS = (signal.SIGTERM, signal.SIGHUP, signal.SIGINT)


class SlotError(Exception):
    """A usage or setup error; the command exits 2 and runs nothing."""


def slot_count() -> int:
    """The declared verify slot count, `DEFAULT_VERIFY_SLOTS` when no declaration exists."""
    try:
        declaration = host_admission.load_declaration()
    except host_admission.DeclarationError as error:
        if error.reason_code == "declaration_missing":
            return host_admission.DEFAULT_VERIFY_SLOTS
        raise SlotError(f"the host declaration is invalid: {error}") from None
    return host_admission.verify_slots(declaration)


def slot_dir(home: str) -> Path:
    return Path(home) / ".agents/state/verify-slots"


def _say(line: str) -> None:
    sys.stderr.write(line + "\n")
    sys.stderr.flush()


class _Run:
    """One run's signal state: the signal received so far and the child to forward it to."""

    def __init__(self) -> None:
        self.received: int | None = None
        self.child: subprocess.Popen | None = None

    def handle(self, signum: int, _frame: object) -> None:
        self.received = signum
        if self.child is not None:
            try:
                self.child.send_signal(signum)
            except (OSError, ProcessLookupError):
                pass


def _try_slots(directory: Path, count: int) -> int | None:
    """The descriptor of the first slot lock taken, or `None` when every slot is held."""
    for index in range(count):
        descriptor = os.open(directory / f"slot-{index}.lock", os.O_RDWR | os.O_CREAT, 0o600)
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


def _acquire(directory: Path, count: int, wait_limit: int | None, run: _Run) -> tuple[int | None, int | None]:
    """`(descriptor, None)` on a taken slot, else `(None, exit code)` with nothing to run."""
    start = time.monotonic()
    waiting = False
    while True:
        if run.received is not None:
            return None, 128 + run.received
        descriptor = _try_slots(directory, count)
        if descriptor is not None:
            if waiting:
                _say(WAITED_LINE.format(seconds=time.monotonic() - start))
            return descriptor, None
        if not waiting:
            waiting = True
            _say(WAITING_LINE.format(count=count))
        if wait_limit is not None and time.monotonic() - start >= wait_limit:
            _say(NO_SLOT_LINE.format(limit=wait_limit))
            return None, NO_SLOT_EXIT
        time.sleep(POLL_SECONDS)


def _run_child(argv: list[str], run: _Run) -> int:
    if run.received is not None:
        return 128 + run.received
    try:
        child = subprocess.Popen(argv)
    except OSError as error:
        _say(f"verify-slot: cannot start {argv[0]}: {error}")
        return CANNOT_START_EXIT
    run.child = child
    # A signal that arrived while the child was being created found no child to forward to.
    if run.received is not None:
        run.handle(run.received, None)
    code = child.wait()
    if run.received is not None:
        return 128 + run.received
    return 128 - code if code < 0 else code


def run_command(argv: list[str], wait_limit: int | None) -> int:
    home = os.environ.get("HOME")
    if not home:
        raise SlotError("HOME is unset or empty")
    count = slot_count()
    directory = slot_dir(home)
    try:
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    except OSError as error:
        raise SlotError(f"cannot create {directory}: {error}") from None
    run = _Run()
    previous = {number: signal.signal(number, run.handle) for number in _HANDLED_SIGNALS}
    descriptor = None
    try:
        try:
            descriptor, code = _acquire(directory, count, wait_limit, run)
        except OSError as error:
            raise SlotError(f"cannot take a slot in {directory}: {error}") from None
        if descriptor is None:
            return code
        return _run_child(argv, run)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        for number, handler in previous.items():
            signal.signal(number, handler)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="verify-slot", description="Run a command while holding one of this host's verify slots.")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="run ARGV in a verify slot (use `--` before ARGV)",
                              usage="verify-slot run [--wait-limit SECONDS] -- ARGV...")
    run.add_argument("--wait-limit", type=int, default=None, metavar="SECONDS",
                     help="give up with exit 75 when no slot comes free within this many seconds")
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
    if args.wait_limit is not None and args.wait_limit < 1:
        parser.error("--wait-limit must be a positive integer")
    if not found_separator or not command:
        parser.error("run needs `--` followed by the command to run")
    try:
        return run_command(command, args.wait_limit)
    except SlotError as error:
        _say(f"verify-slot: {error}")
        return USAGE_EXIT


if __name__ == "__main__":
    sys.exit(main())
