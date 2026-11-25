"""The verify slot queue: tickets, holder descriptions and the rule that decides who is admitted next.

Everything lives in the host's verify slot directory, which every account may write to, so every file
is opened through `open_shared`: a symlink, a hard link, a FIFO or a directory at a name is refused
and nothing is read or written through it. No function here sleeps or blocks on a lock.

Files. `queue.lock` is the queue lock: one process at a time takes it (`lock_queue`) to join the
queue, list the waiters or admit one. `ticket-<12 digits>.lock` is one waiting run; its content is the
JSON object `key`, `live`, `repository` and `reserved_until`. `slot-<i>.lock` is a verify slot; its
holder writes a JSON object `command`, `pid` and `repository` into it (`record_holder`). `repo-<digest>.lock`
and `repo-<digest>-<k>.lock` are the per-repository locks of the older admission, kept so a run of
an older `verify-slot` and a newer one exclude each other.

Liveness. A ticket is a waiter only while some process holds its `flock`; nothing else marks it. A
SIGKILLed waiter loses its lock with its process, so its ticket is no waiter and is removed.

Reservation. A waiter that is about to run its command's retry gives its place back with `reserve`:
the ticket keeps its number and carries `reserved_until`, unlocked. A reserved ticket is never a
waiter. The same request (`request_key`: working directory and argv) takes it back with `join`
while `reserved_until` has not passed, or later while some other waiter with a higher number still
waits; any other request numbers a new ticket one past every ticket name present. `join` removes
every expired reservation that no locked ticket with a higher number guards before it numbers the new
ticket, so a request that joins after a reservation expired never keeps it alive, while a waiter that
joined before it expired does.

Admission. Waiters are served live first, then by ticket number (`service_order`). `admitted` walks
that order: a waiter whose repository already has `repository_limit` holders is skipped and takes no
slot, so it never blocks a later one; the others are admitted while slots are free. Holder counts
come from one `read_holders` observation; only an unknown holder makes `holder_counts` probe the
repository locks.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re

from agent_tools import canonical
from agent_tools.delivery import verify_history

QUEUE_LOCK = "queue.lock"
TICKET = "ticket-{seq:012d}.lock"
RESUME_SECONDS = 300
NO_HOLDER = "a verify run"
OUTSIDE = "a run outside a repository"
NOTHING = "nothing"
GROUP_LOCK = "repo-{digest}.lock"
EXTRA_GROUP_LOCK = "repo-{digest}-{index}.lock"

_TICKET_NAME = re.compile(r"^ticket-(\d{12})\.lock$")
_SLOT_NAME = re.compile(r"^slot-(\d+)\.lock$")
_OPEN_FLAGS = os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK
_READ_BYTES = 4096
_LOCK_NOW = fcntl.LOCK_EX | fcntl.LOCK_NB
_NO_DESCRIPTOR = (errno.EMFILE, errno.ENFILE)
MAX_COMMAND_CHARS = 200


@dataclass(frozen=True)
class Waiter:
    seq: int
    live: bool
    repository: str | None
    key: str


@dataclass(frozen=True)
class Holder:
    repository: str | None
    command: str
    known: bool = True


@dataclass
class Ticket:
    path: Path
    descriptor: int
    seq: int
    key: str
    live: bool
    repository: str | None


def open_shared(path: Path) -> int:
    """Open a shared file read-write, creating it with mode 0666 when it does not exist.

    An existing file is opened without `O_CREAT`: a sticky directory refuses an `O_CREAT` open of
    another account's file. Anything but a regular file with one link is closed and raises `OSError`.
    """
    try:
        return verify_history.regular_descriptor(os.open(path, _OPEN_FLAGS), path)
    except FileNotFoundError:
        pass
    old = os.umask(0)
    try:
        return verify_history.regular_descriptor(
            os.open(path, _OPEN_FLAGS | os.O_CREAT | os.O_EXCL, 0o666), path)
    except FileExistsError:
        return verify_history.regular_descriptor(os.open(path, _OPEN_FLAGS), path)
    finally:
        os.umask(old)


def held(path: Path) -> bool:
    """Whether a live process holds the lock file (a file that cannot be probed counts as held)."""
    try:
        descriptor = verify_history.regular_descriptor(os.open(path, _OPEN_FLAGS), path)
    except FileNotFoundError:
        return False
    except OSError:
        return True
    try:
        fcntl.flock(descriptor, _LOCK_NOW)
    except OSError:
        return True
    finally:
        os.close(descriptor)
    return False


def _group_digest(group: str) -> str:
    return hashlib.sha256(group.encode("utf-8")).hexdigest()[:16]


def group_lock_name(group: str) -> str:
    """The name of the lock file in the slot directory that one repository's holders share."""
    return GROUP_LOCK.format(digest=_group_digest(group))


def repository_lock_paths(directory: Path, group: str, limit: int) -> list[Path]:
    """The `limit` lock files of one repository; the first is the name older runs already use."""
    digest = _group_digest(group)
    paths = [directory / group_lock_name(group)]
    paths.extend(directory / EXTRA_GROUP_LOCK.format(digest=digest, index=index)
                 for index in range(1, limit))
    return paths


def request_key(cwd: Path, argv: Sequence[str]) -> str:
    """The identity of one request: its resolved working directory and its command."""
    return canonical.telemetry_digest([str(cwd.resolve()), list(argv)])


def service_order(waiters: Iterable[Waiter]) -> list[Waiter]:
    """Live waiters first, then by ticket number."""
    return sorted(waiters, key=lambda waiter: (not waiter.live, waiter.seq))


def holder_counts(directory: Path, holders: Sequence[Holder], repositories: Iterable[str],
                  repository_limit: int) -> dict[str, int]:
    """Holders per repository; an unknown holder makes each repository's locks count as well."""
    counts = Counter(holder.repository for holder in holders
                     if holder.known and holder.repository is not None)
    result = dict(counts)
    if any(not holder.known for holder in holders):
        for repository in repositories:
            probed = sum(1 for path in repository_lock_paths(directory, repository, repository_limit)
                         if held(path))
            result[repository] = max(result.get(repository, 0), probed)
    return result


def admitted(waiters: Iterable[Waiter], counts: Mapping[str, int], free: int,
             repository_limit: int) -> list[Waiter]:
    """The waiters that may take the free slots now, in service order."""
    counts = dict(counts)
    chosen: list[Waiter] = []
    for waiter in service_order(waiters):
        if free <= 0:
            break
        repository = waiter.repository
        if repository is not None and counts.get(repository, 0) >= repository_limit:
            continue
        chosen.append(waiter)
        free -= 1
        if repository is not None:
            counts[repository] = counts.get(repository, 0) + 1
    return chosen


def place(waiters: Iterable[Waiter], seq: int) -> int:
    """The 1-based place of the waiter with ticket number `seq` in service order."""
    return 1 + [waiter.seq for waiter in service_order(waiters)].index(seq)


def holders_text(holders: Sequence[Holder]) -> str:
    """The holders in plain words."""
    if not holders:
        return NOTHING
    return ", ".join(
        NO_HOLDER if not holder.known else f"{holder.repository or OUTSIDE} ({holder.command})"
        for holder in holders)


def lock_queue(directory: Path) -> int | None:
    """Take the queue lock without blocking: its descriptor, or None while another holds it."""
    descriptor = open_shared(directory / QUEUE_LOCK)
    try:
        fcntl.flock(descriptor, _LOCK_NOW)
    except BlockingIOError:
        os.close(descriptor)
        return None
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def _content(key: str, live: bool, repository: str | None, reserved_until: float | None) -> bytes:
    return json.dumps({"key": key, "live": live, "repository": repository,
                       "reserved_until": reserved_until}, sort_keys=True).encode("utf-8")


def _write(descriptor: int, data: bytes) -> None:
    os.pwrite(descriptor, data, 0)
    os.ftruncate(descriptor, len(data))


def _parse(descriptor: int) -> dict | None:
    """The ticket's content when it is a well-formed record, else None."""
    try:
        record = json.loads(os.pread(descriptor, _READ_BYTES, 0))
    except (OSError, ValueError):
        return None
    if not isinstance(record, dict):
        return None
    key, live, repository = record.get("key"), record.get("live"), record.get("repository")
    if "reserved_until" not in record:
        return None
    until = record["reserved_until"]
    if not isinstance(key, str) or not isinstance(live, bool):
        return None
    if repository is not None and not isinstance(repository, str):
        return None
    if until is not None and (isinstance(until, bool) or not isinstance(until, (int, float))):
        return None
    return record


def _tickets(directory: Path) -> list[tuple[int, Path]]:
    found = []
    for path in directory.glob("ticket-*.lock"):
        match = _TICKET_NAME.match(path.name)
        if match:
            found.append((int(match.group(1)), path))
    return sorted(found)


def _unlink(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


def _probe(path: Path) -> tuple[int, bool] | None:
    """Open a ticket and try its lock: `(descriptor, locked_by_another)`, or None when it is refused.

    A process that has run out of descriptors learns nothing about the ticket, so that error is
    raised rather than read as a refusal: a refused ticket is removed.
    """
    try:
        descriptor = open_shared(path)
    except OSError as error:
        if error.errno in _NO_DESCRIPTOR:
            raise
        return None
    try:
        fcntl.flock(descriptor, _LOCK_NOW)
    except BlockingIOError:
        return descriptor, True
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor, False


def _close_probed(probed: Sequence[tuple[int, Path, int, bool]]) -> None:
    for _seq, _path, descriptor, _other in probed:
        os.close(descriptor)


def join(directory: Path, key: str, live: bool, repository: str | None, now: float) -> Ticket:
    """Take back this request's reserved ticket or number a new one; the caller holds the queue lock."""
    probed: list[tuple[int, Path, int, bool]] = []
    highest = 0
    try:
        for seq, path in _tickets(directory):
            highest = max(highest, seq)
            result = _probe(path)
            if result is not None:
                probed.append((seq, path, result[0], result[1]))
    except BaseException:
        _close_probed(probed)
        raise
    locked = [seq for seq, _path, _descriptor, other in probed if other]
    taken: tuple[int, Path, int] | None = None
    try:
        for seq, path, descriptor, other in probed:
            if other:
                continue
            record = _parse(descriptor)
            until = None if record is None else record["reserved_until"]
            if record is None or until is None:
                continue
            if until <= now and not any(number > seq for number in locked):
                _unlink(path)  # expired, and no waiter stands behind it: this newcomer joined after it
                continue
            if taken is None and record["key"] == key:
                taken = (seq, path, descriptor)
        if taken is None:
            seq = highest + 1
            path = directory / TICKET.format(seq=seq)
            descriptor = open_shared(path)
            try:
                fcntl.flock(descriptor, _LOCK_NOW)
            except BaseException:
                os.close(descriptor)
                raise
            taken = (seq, path, descriptor)
        _write(taken[2], _content(key, live, repository, None))
    except BaseException:
        if taken is not None:
            os.close(taken[2])
        raise
    finally:
        for _seq, _path, descriptor, _other in probed:
            if taken is None or descriptor != taken[2]:
                os.close(descriptor)
    return Ticket(taken[1], taken[2], taken[0], key, live, repository)


def waiters(directory: Path, own: Ticket, now: float) -> list[Waiter]:
    """The waiters now, `own` included; the caller holds the queue lock. Dead tickets are removed."""
    probed: list[tuple[int, Path, int, bool]] = []
    try:
        for seq, path in _tickets(directory):
            if path == own.path:
                continue
            result = _probe(path)
            if result is None:
                _unlink(path)
                continue
            probed.append((seq, path, result[0], result[1]))
    except BaseException:
        _close_probed(probed)
        raise
    listed = [Waiter(own.seq, own.live, own.repository, own.key)]
    locked = [own.seq] + [seq for seq, _path, _descriptor, other in probed if other]
    try:
        for seq, path, descriptor, other in probed:
            record = _parse(descriptor)
            if other:
                if record is not None and record["reserved_until"] is None:
                    listed.append(Waiter(seq, record["live"], record["repository"], record["key"]))
                continue
            until = None if record is None else record["reserved_until"]
            if until is None or (until <= now and not any(number > seq for number in locked)):
                _unlink(path)
    finally:
        for _seq, _path, descriptor, _other in probed:
            os.close(descriptor)
    return sorted(listed, key=lambda waiter: waiter.seq)


def reserve(ticket: Ticket, now: float) -> None:
    """Give the ticket's place back for `RESUME_SECONDS`: record the reservation, then release the lock."""
    try:
        _write(ticket.descriptor, _content(ticket.key, ticket.live, ticket.repository,
                                           now + RESUME_SECONDS))
    finally:
        os.close(ticket.descriptor)


def leave(ticket: Ticket) -> None:
    """Remove the ticket and release its lock."""
    try:
        ticket.path.unlink()
    except (FileNotFoundError, PermissionError):
        pass
    finally:
        os.close(ticket.descriptor)


def record_holder(descriptor: int, repository: str | None, command: str) -> None:
    """Describe this process as the holder of the slot file `descriptor` locks.

    The command is cut to `MAX_COMMAND_CHARS` so the record always fits the reader's `_READ_BYTES`.
    """
    data = json.dumps({"command": command[:MAX_COMMAND_CHARS], "pid": os.getpid(), "repository": repository},
                      sort_keys=True).encode("utf-8")
    _write(descriptor, data)


def clear_holder(descriptor: int) -> None:
    """Erase the holder's description from the slot file."""
    os.ftruncate(descriptor, 0)


def _described(descriptor: int) -> Holder | None:
    try:
        record = json.loads(os.pread(descriptor, _READ_BYTES, 0))
    except (OSError, ValueError):
        return None
    if not isinstance(record, dict):
        return None
    command, pid, repository = record.get("command"), record.get("pid"), record.get("repository")
    if not isinstance(command, str) or isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        return None
    if repository is not None and not isinstance(repository, str):
        return None
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return None
    except OSError:
        pass
    return Holder(repository, command)


def read_holders(directory: Path) -> list[Holder]:
    """One entry per held slot file, in slot order; a held file nobody described is unknown."""
    names = []
    for path in directory.glob("slot-*.lock"):
        match = _SLOT_NAME.match(path.name)
        if match:
            names.append((int(match.group(1)), path))
    holders = []
    for _index, path in sorted(names):
        try:
            descriptor = open_shared(path)
        except OSError:
            holders.append(Holder(None, "", known=False))
            continue
        try:
            fcntl.flock(descriptor, _LOCK_NOW)
        except BlockingIOError:
            holders.append(_described(descriptor) or Holder(None, "", known=False))
        finally:
            os.close(descriptor)
    return holders
