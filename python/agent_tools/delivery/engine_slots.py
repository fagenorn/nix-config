"""The engine route's agent slots (#1522): how many live sessions the host admits for `engine deliver`.

The host declaration (`host_admission`) names the engine route and the agent slots it admits, one per live
engine session. `declared_slots()` reads the declaration once, when a deliver starts; a host whose declaration
is missing, invalid, or does not admit the engine route raises `host_admission.DeclarationError`, and the
caller refuses to start a run.

A session holds one slot while it runs. The slots of a run live in `<root run dir>/slots/` (mode 0700),
one file `slot-<i>.lock` for each `i` below the declared count; a slot is an exclusive non-blocking `flock`
on that file, held by the engine process on a descriptor the session never inherits, so the kernel frees it
when the engine dies. `hold` tries the files in order; with every slot taken it calls `on_wait` once, polls
every `POLL_SECONDS`, and calls `on_waited` once when it gets one. The caller records that wait as the
`wait_started` and `wait_ended` events of the `host-slot` wait. The bound is per root run: there is no count
across runs (ADR-delivery-018).
"""

from __future__ import annotations

import contextlib
import fcntl
import os
import time
from pathlib import Path
from typing import Callable, Iterator

from agent_tools.delivery import host_admission

SLOTS_DIR = "slots"
WAIT = "host-slot"
POLL_SECONDS = 0.2


def declared_slots() -> int:
    """The agent slots the host declaration admits for the engine route."""
    return host_admission.route_slots(host_admission.load_declaration(),
                                      host_admission.ENGINE_ROUTE)


def slot_dir(root: Path) -> Path:
    """The directory of the slot files of the run directory `root`."""
    return Path(root) / SLOTS_DIR


def _take(directory: Path, count: int) -> tuple[int, int] | None:
    """`(index, descriptor)` of the first slot of `count` that is free, else None."""
    for index in range(count):
        descriptor = os.open(directory / f"slot-{index}.lock", os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(descriptor)
        except BaseException:
            os.close(descriptor)
            raise
        else:
            return index, descriptor
    return None


@contextlib.contextmanager
def hold(root: Path, count: int, *, on_wait: Callable[[], None],
         on_waited: Callable[[], None]) -> Iterator[int]:
    """Hold one of the `count` slots of `root` for the block, waiting for a free one; yield its index."""
    directory = slot_dir(root)
    directory.mkdir(mode=0o700, exist_ok=True)
    waited = False
    while True:
        taken = _take(directory, count)
        if taken is not None:
            break
        if not waited:
            waited = True
            on_wait()
        time.sleep(POLL_SECONDS)
    index, descriptor = taken
    try:
        if waited:
            on_waited()
        yield index
    finally:
        os.close(descriptor)
