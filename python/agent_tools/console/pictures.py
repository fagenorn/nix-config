"""The console's store of the PNG pictures a manager sends (#1089).

Check. `checked_png(data)` raises `NotPng` unless `data` starts with the PNG signature
(`SIGNATURE_WRONG`: "not a PNG: the file does not start with the PNG signature"), holds at least
33 bytes (`HEADER_SHORT`: "not a PNG: the IHDR header is missing or cut short") and carries a
readable IHDR chunk straight after the signature (`HEADER_UNREADABLE`: "not a PNG: the IHDR header
is not readable"): chunk length 13, type `IHDR`, a CRC32 over type and data that matches, width and
height from 1 to 2**31-1, a (colour type, bit depth) pair the PNG specification allows, compression
0, filter 0 and interlace 0 or 1. The bytes after the IHDR chunk are not inspected. `str(error)` is
one of the three reasons.

Store. Pictures live in `pictures/` beside the event log (mode 0700, set even when the directory
existed with another mode); a picture is the file `pictures/<id>` (mode 0600) holding exactly the
bytes, `id` being their SHA-256 in lowercase hex. `store(directory, data)` returns `(id, written)`:
a picture is written once, to a temporary `.incoming-*` file (`O_CREAT|O_EXCL|O_NOFOLLOW`, 0600,
fsync) and moved into place by `os.replace`; a resend of the same bytes writes nothing, leaves the
file in place and sets its mtime to now, which renews its age for the sweep. An existing entry at
the path that is not a regular file raises `OSError`. `read(directory, id)` raises `ValueError` for
an id that is not 64 lowercase hex digits, and answers None for a missing file, a symlink or a
non-regular file.

Present. `present(directory, id)` is the ask route's check that a named picture is still stored: it
raises `ValueError` for an id that is not 64 lowercase hex digits and answers True only when
`os.lstat(directory / id)` succeeds on a regular file (a symlink, a directory, a FIFO and a missing
entry are False). It writes nothing, not even the file's age; the caller holds the ingest lock
that every sweep also holds, so the answer cannot go stale before the row is appended.

Reference. A picture is referenced by a row whose payload `pictures` is a list holding its id:
`referenced(events)` collects the members that are well-formed ids from every row but those of kind
`PICTURE_STORED`, whose own payload is `entry(project, sprint_id, id)`.

Sweep. `sweep(directory, keep, now)` removes each entry that is not a directory, whose name is not
in `keep` and whose age `now - st_mtime` is strictly more than `UNREFERENCED_SECONDS` (a day), and
returns how many it removed. A missing directory is 0; a listing failure raises `OSError`.

Decided in ADR-console-036.
"""

from __future__ import annotations

import hashlib
import os
import re
import secrets
import stat
import struct
import zlib
from collections.abc import Collection, Iterable
from pathlib import Path

from agent_tools.console.event_log import PICTURE_STORED, Event

DIRECTORY = "pictures"
MAX_BYTES = 2 * 1024 * 1024
UNREFERENCED_SECONDS = 86400.0
PICTURE_ID = re.compile(r"[0-9a-f]{64}")
SIGNATURE = b"\x89PNG\r\n\x1a\n"

SIGNATURE_WRONG = "not a PNG: the file does not start with the PNG signature"
HEADER_SHORT = "not a PNG: the IHDR header is missing or cut short"
HEADER_UNREADABLE = "not a PNG: the IHDR header is not readable"

_HEADER_END = 33
_LIMIT = 2 ** 31 - 1
_DEPTHS = {0: (1, 2, 4, 8, 16), 2: (8, 16), 3: (1, 2, 4, 8), 4: (8, 16), 6: (8, 16)}


class NotPng(ValueError):
    pass


def checked_png(data: bytes) -> None:
    if data[:8] != SIGNATURE:
        raise NotPng(SIGNATURE_WRONG)
    if len(data) < _HEADER_END:
        raise NotPng(HEADER_SHORT)
    length, kind = struct.unpack(">I4s", data[8:16])
    width, height, depth, colour, compression, filter_, interlace = struct.unpack(
        ">IIBBBBB", data[16:29])
    crc = struct.unpack(">I", data[29:33])[0]
    readable = (length == 13 and kind == b"IHDR" and crc == zlib.crc32(data[12:29])
                and 0 < width <= _LIMIT and 0 < height <= _LIMIT
                and depth in _DEPTHS.get(colour, ())
                and compression == 0 and filter_ == 0 and interlace in (0, 1))
    if not readable:
        raise NotPng(HEADER_UNREADABLE)


def store(directory: Path, data: bytes) -> tuple[str, bool]:
    picture_id = hashlib.sha256(data).hexdigest()
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(directory, 0o700)
    target = directory / picture_id
    try:
        present = os.lstat(target)
    except FileNotFoundError:
        present = None
    if present is not None:
        if not stat.S_ISREG(present.st_mode):
            raise OSError(f"{target} is not a file")
        os.utime(target)
        return picture_id, False
    temporary = directory / f".incoming-{secrets.token_hex(8)}"
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise
    return picture_id, True


def read(directory: Path, picture_id: str) -> bytes | None:
    if not PICTURE_ID.fullmatch(picture_id):
        raise ValueError("not a picture id")
    try:
        fd = os.open(directory / picture_id, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return None
    with os.fdopen(fd, "rb") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            return None
        return handle.read()


def present(directory: Path, picture_id: str) -> bool:
    if not PICTURE_ID.fullmatch(picture_id):
        raise ValueError("not a picture id")
    try:
        return stat.S_ISREG(os.lstat(directory / picture_id).st_mode)
    except FileNotFoundError:
        return False


def referenced(events: Iterable[Event]) -> frozenset[str]:
    found: set[str] = set()
    for event in events:
        listed = event.payload.get("pictures")
        if event.kind == PICTURE_STORED or not isinstance(listed, list):
            continue
        found.update(item for item in listed
                     if isinstance(item, str) and PICTURE_ID.fullmatch(item))
    return frozenset(found)


def sweep(directory: Path, keep: Collection[str], now: float) -> int:
    try:
        entries = list(os.scandir(directory))
    except FileNotFoundError:
        return 0
    removed = 0
    for item in entries:
        if item.is_dir(follow_symlinks=False) or item.name in keep:
            continue
        try:
            if now - item.stat(follow_symlinks=False).st_mtime <= UNREFERENCED_SECONDS:
                continue
            os.unlink(item.path)
        except FileNotFoundError:
            continue
        removed += 1
    return removed


def entry(project: str | None, sprint_id: str, picture_id: str) -> tuple[str, str | None, dict]:
    return (PICTURE_STORED, project, {"picture": picture_id, "sprint_id": sprint_id})
