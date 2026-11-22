"""The stop request of `engine stop` and the polled wait that obeys it (#1524).

A stop request is the file `stop-request` in a run directory, a strict JSON object holding the
`pid` and `started` of the lock holder it names (`engine_shell.lock_holder`) and the time it was
written. `requested` answers true only for that holder, so a request left by an earlier engine
never ends a later one. `write_request` publishes it atomically with mode 0600; `clear` removes it.

`communicate` is `Popen.communicate` that, given a `stop` predicate, waits in `POLL_SECONDS` slices
and raises `Stopped` once `stop()` is true. It kills nothing: the caller's handler ends the process
group. A retry passes no input, because CPython keeps the unsent offset of the first call.

The module imports no other engine module, so `engine_commands` and `engine_session` can use it.
"""

from __future__ import annotations

import json
import os
import random
import string
import subprocess
import time
from pathlib import Path
from typing import Callable, Mapping

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
    except OSError:
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


def communicate(process: subprocess.Popen, data: bytes | None, *,
                stop: Callable[[], bool] | None,
                timeout: float | None = None) -> tuple[bytes, bytes | None]:
    """`process.communicate(data, timeout=timeout)`, raising `Stopped` once `stop()` is true."""
    if stop is None:
        return process.communicate(data, timeout=timeout)
    deadline = None if timeout is None else time.monotonic() + timeout
    first = True
    while True:
        wait = POLL_SECONDS if deadline is None else max(
            0, min(POLL_SECONDS, deadline - time.monotonic()))
        try:
            return process.communicate(data if first else None, timeout=wait)
        except subprocess.TimeoutExpired:
            first = False
            if stop():
                raise Stopped from None
            if deadline is not None and time.monotonic() >= deadline:
                raise
