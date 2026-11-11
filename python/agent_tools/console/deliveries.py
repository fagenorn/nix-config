"""The console's run journals (#858): what a workflow run has done so far, read without re-reading.

A run journal is the append-only JSON-lines file a workflow run writes as it goes, at
`<config>/projects/<slug>/<session_id>/subagents/workflows/<run_id>/journal.jsonl` (`JOURNAL_NAME`
is the file's name). Each line is one JSON object; the journal carries no timestamp, so a run's
last movement is the journal's modification time.

`JournalReader.read(path)` returns what was appended since its last read of that path, never the
whole file again. It keeps, per path, the inode, the byte offset and the bytes of a trailing line
that has no newline yet:

- `None` only when the journal is confirmed absent (`FileNotFoundError` or `NotADirectoryError` from
  `os.stat`); the reader then forgets the path.
- `Unreadable(reason)`, `"<Type>: <message>"` of the `OSError` that stopped the read, for any other
  failure to stat, open or read. It is not absence: the journal may still be there, and the kept
  state is left unchanged, so the next successful read continues where the last one ended.
- `Chunk(records, moved_ms, from_start)` otherwise. `records` are the complete new lines parsed in
  file order (an empty line, invalid UTF-8 or JSON, or a value that is not a JSON object is
  skipped); `moved_ms` is the journal's `st_mtime_ns // 1_000_000` at this read; `from_start` is
  true when this read began at byte 0 (nothing known, a forgotten path, a different inode, or a
  size below the kept offset), and a caller holding a fold of earlier records must then start a
  new fold.

A journal whose size equals the kept offset is not opened. An opened journal is read once, for
exactly the bytes between the offset and the size `os.stat` reported; growth after the stat is
picked up by the next call. Pending bytes are never read from the file again. Nothing here reads a
clock.
"""

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Callable

JOURNAL_NAME = "journal.jsonl"


@dataclass(frozen=True)
class Chunk:
    """The complete new lines of a journal, the journal's mtime in ms, and whether this read began at byte 0."""

    records: tuple[dict, ...]
    moved_ms: int
    from_start: bool


@dataclass(frozen=True)
class Unreadable:
    """`"<Type>: <message>"` of the `OSError` that stopped a read; not absence."""

    reason: str


def _open_binary(path: Path) -> BinaryIO:
    return open(path, "rb")


def _reason(error: OSError) -> str:
    return f"{type(error).__name__}: {error}"


def _parse(line: bytes) -> dict | None:
    try:
        value = json.loads(line.decode("utf-8"))
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


class JournalReader:
    def __init__(self, opener: Callable[[Path], BinaryIO] = _open_binary):
        self._opener = opener
        self._known: dict[Path, tuple[int, int, bytes]] = {}

    def forget(self, path: Path) -> None:
        self._known.pop(path, None)

    def read(self, path: Path) -> Chunk | Unreadable | None:
        try:
            stat = os.stat(path)
        except (FileNotFoundError, NotADirectoryError):
            self.forget(path)
            return None
        except OSError as error:
            return Unreadable(_reason(error))
        moved_ms = stat.st_mtime_ns // 1_000_000
        known = self._known.get(path)
        from_start = known is None or known[0] != stat.st_ino or stat.st_size < known[1]
        _, offset, pending = (stat.st_ino, 0, b"") if from_start else known
        if stat.st_size == offset:
            self._known[path] = (stat.st_ino, offset, pending)
            return Chunk((), moved_ms, from_start)
        try:
            with self._opener(path) as handle:
                handle.seek(offset)
                data = handle.read(stat.st_size - offset)
        except OSError as error:
            return Unreadable(_reason(error))
        *lines, pending = (pending + data).split(b"\n")
        self._known[path] = (stat.st_ino, offset + len(data), pending)
        records = tuple(record for record in map(_parse, lines) if record is not None)
        return Chunk(records, moved_ms, from_start)
