"""The stop request of `engine stop` and the polled wait that obeys it (#1524).

A stop request is the file `stop-request` in a run directory, a strict JSON object holding the
`pid` and `started` of the lock holder it names (`engine_shell.lock_holder`) and the time it was
written. `requested` answers true only for that holder, so a request left by an earlier engine
never ends a later one. `write_request` publishes it atomically with mode 0600; `clear` removes it.

`communicate` is `Popen.communicate` that, given a `stop` predicate, waits in `POLL_SECONDS` slices
and raises `Stopped` once `stop()` is true, also when the process ended inside the first slice: a
request made before the process ended is never graded past. It kills nothing: the caller's handler
calls `end_group`. The input goes to the child's stdin from a daemon thread that closes it
after the last byte, never through a retried `communicate`: before Python 3.13 a retry that
carries input is refused and one that carries none stops writing, so a prompt larger than the
pipe would never be delivered. `pause` is `time.sleep` that polls `stop` the same way, in slices
of at most `POLL_SECONDS`.
`requested` treats only a missing file as no request; any other read error propagates.

`publication` is the exclusive flock on the run directory that orders a request's publication
against the engine's recording of the stop and removal of the file (`engine_shell.request_stop`).
`sigterm_exits` makes a SIGTERM to the engine raise `SystemExit` while a process group runs.

The module imports no other engine module, so `engine_commands` and `engine_session` can use it.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import random
import signal
import string
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable, Iterator, Mapping

from agent_tools.canonical import reject_duplicate_keys, reject_nonfinite_literal

REQUEST_NAME = "stop-request"
STOPPED_BY_REQUEST = "stopped-by-request"
STOP_NEED = "retry"
POLL_SECONDS = 0.5


class Stopped(Exception):
    """A stop request ended the step's process group."""


def request_path(run_dir: Path) -> Path:
    return Path(run_dir) / REQUEST_NAME


def write_request(run_dir: Path, holder: Mapping[str, object]) -> Path:
    document = {"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "pid": holder["pid"], "started": holder["started"]}
    text = json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n"
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
    temporary = Path(run_dir) / f".{REQUEST_NAME}.{os.getpid()}.{suffix}.tmp"
    published = False
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(text.encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, request_path(run_dir))
        published = True
        directory = os.open(run_dir, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if not published:
            temporary.unlink(missing_ok=True)
    return request_path(run_dir)


def requested(run_dir: Path, holder: Mapping[str, object]) -> bool:
    try:
        raw = request_path(run_dir).read_bytes()
    except FileNotFoundError:
        return False
    try:
        document = json.loads(raw.decode("utf-8"), object_pairs_hook=reject_duplicate_keys,
                              parse_constant=reject_nonfinite_literal)
    except (ValueError, RecursionError):  # UnicodeDecodeError is a ValueError
        return False
    return (isinstance(document, dict) and type(document.get("pid")) is int
            and document["pid"] == holder["pid"] and document.get("started") == holder["started"])


def clear(run_dir: Path) -> None:
    request_path(run_dir).unlink(missing_ok=True)


@contextlib.contextmanager
def publication(run_dir: Path) -> Iterator[None]:
    """Hold the run directory's exclusive flock: a request is published or removed one at a time."""
    descriptor = os.open(run_dir, os.O_RDONLY)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        os.close(descriptor)


def _terminate(signum: int, frame: object) -> None:
    raise SystemExit(128 + signum)


@contextlib.contextmanager
def sigterm_exits() -> Iterator[None]:
    """A SIGTERM raises `SystemExit(143)` inside the block; the previous handler returns after."""
    try:
        previous = signal.signal(signal.SIGTERM, _terminate)
    except ValueError:  # not the main thread: no handler can be installed
        previous = None
    try:
        yield
    finally:
        if previous is not None:
            signal.signal(signal.SIGTERM, previous)


def end_group(process: subprocess.Popen) -> None:
    """Kill `process`'s whole group, reap its leader and close its pipes, waiting for no EOF.

    A descendant that left the group may still hold a pipe's far end; closing ours frees the caller.
    """
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):  # gone, or a leader left unreaped as a zombie (macOS)
        pass
    process.wait()
    for pipe in (process.stdin, process.stdout, process.stderr):
        if pipe is not None:
            with contextlib.suppress(OSError):
                pipe.close()


def communicate(process: subprocess.Popen, data: bytes | None, *,
                stop: Callable[[], bool] | None,
                timeout: float | None = None) -> tuple[bytes, bytes | None]:
    """`process.communicate(data, timeout=timeout)`, raising `Stopped` once `stop()` is true."""
    if stop is None:
        return process.communicate(data, timeout=timeout)
    if data and process.stdin is not None:
        feeder = threading.Thread(target=_feed, args=(process.stdin, data), daemon=True)
        process.stdin = None  # `communicate` leaves stdin to the feeder
        feeder.start()
    deadline = None if timeout is None else time.monotonic() + timeout
    while True:
        wait = POLL_SECONDS if deadline is None else max(
            0, min(POLL_SECONDS, deadline - time.monotonic()))
        try:
            output = process.communicate(None, timeout=wait)
        except subprocess.TimeoutExpired:
            if stop():
                raise Stopped from None
            if deadline is not None and time.monotonic() >= deadline:
                raise
        else:
            if stop():
                raise Stopped
            return output


def _feed(stdin, data: bytes) -> None:
    """Write `data` to `stdin` and close it; a child that left or closed its end ends the write."""
    try:
        stdin.write(data)
        stdin.flush()
    except (OSError, ValueError):
        pass
    finally:
        with contextlib.suppress(OSError, ValueError):
            stdin.close()


def pause(seconds: float, stop: Callable[[], bool] | None) -> None:
    """`time.sleep(seconds)`, raising `Stopped` as soon as `stop()` is true, before each slice and after the last."""
    if stop is None:
        time.sleep(seconds)
        return
    left = seconds
    while True:
        if stop():
            raise Stopped
        if left <= 0:
            return
        piece = min(POLL_SECONDS, left)
        time.sleep(piece)
        left -= piece
