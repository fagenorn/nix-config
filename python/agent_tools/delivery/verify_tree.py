"""The peak footprint of a verify run's process tree, read with macOS `footprint(1)` while the run goes.

`verify-slot run` starts a `TreePeak` for its command's child. It reads the tree at `start()` and then
every `interval` seconds (`TREE_SECONDS`) until `stop()`, and reads nothing once `stop()` has returned.
One read is exactly

    footprint -p <pid> -t -f bytes --noCategories -j <path>

with `<path>` in a fresh temporary directory, no stdin and no output, and a limit of
`TREE_TIMEOUT_SECONDS`. `<pid>` is the command's child, never `verify-slot`'s own pid, so footprint is
not in the tree it reads. `-t` adds the child's descendants, and footprint de-duplicates memory the
processes share, so the report's `total footprint` is the tree's figure; the processes' own figures
are never added up.

A report is a reading only when its JSON is an object whose `unit` is `"byte"`, whose `bytes per unit`
is the integer 1, whose `total footprint` is an integer of at least 0 (a bool is refused) and whose
`errors` is an empty list. Anything else, a non-zero exit, a timeout, an `OSError` or a missing file
is no reading and the run goes on. A `footprint` that is not an executable file is never run, so a
host without one (Linux) records nothing. footprint needs root only for another account's
processes; a run measures its own child, so every account can measure its own runs.

The peak is the largest reading and `at` is the UTC time of the read that first reached it
(`%Y-%m-%dT%H:%M:%SZ`); a later equal reading keeps the earlier time. With no reading both are None.
`VERIFY_SLOT_FOOTPRINT` names another footprint program, a test seam.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
import json
import os
import subprocess
import tempfile
import threading

TREE_SECONDS = 2.0
TREE_TIMEOUT_SECONDS = 10
JOIN_SECONDS = 1.0
FOOTPRINT_ENV = "VERIFY_SLOT_FOOTPRINT"
DEFAULT_FOOTPRINT = "/usr/bin/footprint"
TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def footprint_path() -> str:
    """The footprint program: `VERIFY_SLOT_FOOTPRINT` when set and non-empty, else `DEFAULT_FOOTPRINT`."""
    return os.environ.get(FOOTPRINT_ENV) or DEFAULT_FOOTPRINT


def parse_tree(document: object) -> int | None:
    """The tree's `total footprint` in bytes when `document` is a complete byte report, else None."""
    if not isinstance(document, dict):
        return None
    total = document.get("total footprint")
    scale = document.get("bytes per unit")
    if (document.get("unit") != "byte" or type(scale) is not int or scale != 1
            or type(total) is not int or total < 0 or document.get("errors") != []):
        return None
    return total


def read_tree(footprint: str, pid: int) -> int | None:
    """One reading of `pid`'s tree in bytes, or None when footprint gave no complete report."""
    try:
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "tree.json")
            result = subprocess.run(
                [footprint, "-p", str(pid), "-t", "-f", "bytes", "--noCategories", "-j", path],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=TREE_TIMEOUT_SECONDS)
            if result.returncode != 0:
                return None
            with open(path, encoding="utf-8") as handle:
                document = json.load(handle)
    except (OSError, subprocess.SubprocessError, ValueError, RecursionError):
        return None
    return parse_tree(document)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TreePeak:
    """Reads one process's tree on a background thread and keeps the largest reading and its time."""

    def __init__(self, pid: int, footprint: str, interval: float = TREE_SECONDS,
                 clock: Callable[[], datetime] | None = None) -> None:
        self._pid = pid
        self._footprint = footprint
        self._interval = interval
        self._clock = clock or _utc_now
        self._stopped = threading.Event()
        self._lock = threading.Lock()
        self._peak: int | None = None
        self._at: str | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if not os.access(self._footprint, os.X_OK):
            return
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> tuple[int | None, str | None]:
        """End the reads and answer the peak and its time; a read in flight is bounded by its own timeout."""
        self._stopped.set()
        if self._thread is not None:
            self._thread.join(JOIN_SECONDS)
        with self._lock:
            return self._peak, self._at

    def _loop(self) -> None:
        while True:
            reading = read_tree(self._footprint, self._pid)
            if reading is not None:
                self._keep(reading)
            if self._stopped.wait(self._interval):
                return

    def _keep(self, reading: int) -> None:
        at = self._clock().strftime(TIME_FORMAT)
        with self._lock:
            if self._peak is None or reading > self._peak:
                self._peak, self._at = reading, at
