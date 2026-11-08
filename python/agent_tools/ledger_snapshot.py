"""`ledger-snapshot`: a fenced, restorable cut of both runtime stores (#584 D7, D9).

A root's runtime state is two stores under `.superpowers`: `workflows` (one directory per
ledger, each with a `state.lock`) and `attempt-transactions` (the transaction core). `take`
writes one `.tar.gz` of both into `.superpowers/archive`. `restore` moves what is live aside
and extracts the snapshot; it never deletes anything.

The cut is consistent because of the fence. Every ledger write happens under that ledger's
`state.lock`, every core write takes `attempt-transactions/attempt-runs.lock` after any
ledger lock, and a new direct run is created under `workflows/.direct-<n>.lock`. The fence
takes all of them non-blocking, in that same order (ledgers, dot-locks, store locks), so it
never inverts a writer's own lock order. A lock already held means a writer is mid-write
and the command refuses `busy`; while the fence holds, no writer can make a write. After the
tarball is written the fence re-lists both stores, and a ledger, dot-lock or store that
appeared or vanished refuses `changed`.

A store that was absent at snapshot time is absent again after `restore --apply`, because
the live store is moved aside rather than extracted over. Python 3.12 or later is required
(`tarfile`'s `filter="data"`).
"""

from __future__ import annotations

import argparse
import contextlib
import errno
import fcntl
import fnmatch
import gzip
import hashlib
import json
import os
import stat
import sys
import tarfile
import zlib
from collections.abc import Callable, Iterator, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple

REPORT_SCHEMA = "ledger-snapshot-report/v1"
STORES = ("workflows", "attempt-transactions")
STORE_LOCKS = ("attempt-runs.lock", "creation.lock", "leases.lock")
ASIDE_NAMES = {"workflows": "workflows", "attempt-transactions": "attempt-transactions",
               "archive/workflows": "archive-workflows"}
CODES = ("busy", "changed", "exists", "invalid_path", "invalid_store", "invalid_snapshot")
_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


class SnapshotRefused(ValueError):
    """One refusal: a closed code and its detail."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


class _UsageError(ValueError):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message: str):  # type: ignore[override]
        raise _UsageError(message)


class Fence(NamedTuple):
    ledgers: tuple[str, ...]
    dot_locks: tuple[str, ...]
    transactions: bool


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _open(path: str, flags: int, what: str, *, mode: int = 0o777, dir_fd: int | None = None) -> int:
    """`os.open`, with a symlink or a wrong file type at `path` a refusal."""
    try:
        return os.open(path, flags, mode, dir_fd=dir_fd)
    except OSError as exc:
        if exc.errno in (errno.ELOOP, errno.ENOTDIR):
            raise SnapshotRefused("invalid_store", f"{what} is a symlink or not the expected "
                                                   f"file type") from exc
        raise


def _stat(name: str, dir_fd: int) -> os.stat_result | None:
    try:
        return os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None


def _is_dot_lock(name: str) -> bool:
    return fnmatch.fnmatchcase(name, ".*.lock")


def _scan(wfd: int) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """The ledgers and the dot-locks directly under the `workflows` directory `wfd`."""
    ledgers: list[str] = []
    dots: list[str] = []
    for name in sorted(os.listdir(wfd)):
        found = _stat(name, wfd)
        if found is None:
            continue
        if stat.S_ISDIR(found.st_mode) and not name.startswith("."):
            try:
                lfd = os.open(name, _DIR_FLAGS, dir_fd=wfd)
            except OSError as exc:
                if exc.errno in (errno.ELOOP, errno.ENOTDIR, errno.ENOENT):
                    continue
                raise
            try:
                if any(_stat(member, lfd) for member in ("state.json", "state.lock")):
                    ledgers.append(name)
            finally:
                os.close(lfd)
        elif stat.S_ISREG(found.st_mode) and _is_dot_lock(name):
            dots.append(name)
    return tuple(ledgers), tuple(dots)


def _open_superpowers(superpowers: Path) -> int:
    try:
        return _open(str(superpowers), _DIR_FLAGS, str(superpowers))
    except FileNotFoundError as exc:
        raise SnapshotRefused("invalid_store", f"{superpowers} does not exist") from exc


def _open_store(sfd: int, name: str) -> int | None:
    try:
        return _open(name, _DIR_FLAGS, name, dir_fd=sfd)
    except FileNotFoundError:
        return None


@contextlib.contextmanager
def fence(superpowers: Path, *, require_workflows: bool) -> Iterator[Fence]:
    """Hold every ledger, dot-lock and transaction-store lock, non-blocking, in writer order."""
    fds: list[int] = []
    locks: list[tuple[int, str]] = []  # (fd, path relative to .superpowers), in lock order

    def opened(fd: int) -> int:
        fds.append(fd)
        return fd

    try:
        sfd = opened(_open_superpowers(superpowers))
        wfd_raw = _open_store(sfd, "workflows")
        ledgers: tuple[str, ...] = ()
        dots: tuple[str, ...] = ()
        if wfd_raw is None:
            if require_workflows:
                raise SnapshotRefused("invalid_store", f"{superpowers / 'workflows'} is absent")
        else:
            wfd = opened(wfd_raw)
            ledgers, dots = _scan(wfd)
            try:
                for name in ledgers:
                    lfd = _open(name, _DIR_FLAGS, f"workflows/{name}", dir_fd=wfd)
                    try:
                        lock = _open("state.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW,
                                     f"workflows/{name}/state.lock", mode=0o600, dir_fd=lfd)
                    finally:
                        os.close(lfd)
                    locks.append((opened(lock), f"workflows/{name}/state.lock"))
                for name in dots:
                    lock = _open(name, os.O_RDWR | os.O_NOFOLLOW, f"workflows/{name}",
                                 dir_fd=wfd)
                    locks.append((opened(lock), f"workflows/{name}"))
            except FileNotFoundError as exc:
                raise SnapshotRefused("changed", f"{exc.filename} vanished while the fence "
                                                 f"was being taken") from exc
        tfd_raw = _open_store(sfd, "attempt-transactions")
        if tfd_raw is not None:
            tfd = opened(tfd_raw)
            for name in STORE_LOCKS:
                flags = os.O_RDWR | os.O_NOFOLLOW
                if name == "attempt-runs.lock":
                    flags |= os.O_CREAT
                try:
                    lock = _open(name, flags, f"attempt-transactions/{name}", mode=0o600,
                                 dir_fd=tfd)
                except FileNotFoundError:
                    continue
                locks.append((opened(lock), f"attempt-transactions/{name}"))
        for fd, relative in locks:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise SnapshotRefused("busy", f"{relative} is held by a writer") from exc
        yield Fence(ledgers, dots, tfd_raw is not None)
    finally:
        for fd in reversed(fds):
            with contextlib.suppress(OSError):
                os.close(fd)


def _relist(superpowers: Path) -> Fence:
    """The stores as they are now, read without taking or creating any lock."""
    sfd = _open_superpowers(superpowers)
    try:
        wfd = _open_store(sfd, "workflows")
        if wfd is None:
            raise SnapshotRefused("changed", "workflows vanished while the fence was held")
        try:
            ledgers, dots = _scan(wfd)
        finally:
            os.close(wfd)
        tfd = _open_store(sfd, "attempt-transactions")
        if tfd is not None:
            os.close(tfd)
        return Fence(ledgers, dots, tfd is not None)
    finally:
        os.close(sfd)


def _resolve_root(root: Path) -> Path:
    try:
        resolved = Path(root).resolve(strict=True)
    except OSError as exc:
        raise SnapshotRefused("invalid_path", f"{root}: {exc.strerror}") from exc
    if not resolved.is_dir():
        raise SnapshotRefused("invalid_path", f"{resolved} is not a directory")
    return resolved


def _check_archive_home(archive: Path) -> bool:
    """Whether `archive` exists; a symlink or a non-directory there is `invalid_store`."""
    try:
        found = os.lstat(archive)
    except FileNotFoundError:
        return False
    if not stat.S_ISDIR(found.st_mode):
        raise SnapshotRefused("invalid_store", f"{archive} is a symlink or not a directory")
    return True


def _fsync_dir(fd: int) -> None:
    os.fsync(fd)


def _add_store(tar: tarfile.TarFile, superpowers: Path, store: str) -> int:
    """Add the store directory and everything under it; a non-regular, non-directory is refused."""
    count = 0
    top = superpowers / store
    tar.add(top, arcname=store, recursive=False)
    count += 1
    for dirpath, dirnames, filenames in os.walk(top, followlinks=False):
        dirnames.sort()
        filenames.sort()
        for name in [*dirnames, *filenames]:
            full = Path(dirpath) / name
            relative = full.relative_to(superpowers).as_posix()
            mode = os.lstat(full).st_mode
            if stat.S_ISDIR(mode):
                tar.add(full, arcname=relative, recursive=False)
            elif stat.S_ISREG(mode):
                info = tar.gettarinfo(str(full), arcname=relative)
                fd = _open(str(full), os.O_RDONLY | os.O_NOFOLLOW, relative)
                with os.fdopen(fd, "rb") as handle:
                    tar.addfile(info, handle)
            else:
                raise SnapshotRefused("invalid_store", f"{relative} is a symlink or another "
                                                       f"file type a snapshot cannot hold")
            count += 1
    return count


def take(root: Path, out: Path, *, now: Callable[[], str],
         on_written: Callable[[], None] = lambda: None) -> dict:
    """Write one tarball of both stores under the fence; publish it only if nothing changed."""
    root = _resolve_root(root)
    superpowers = root / ".superpowers"
    archive = superpowers / "archive"
    _check_archive_home(archive)
    out = Path(out)
    parent = out.parent.resolve(strict=False)
    if parent != archive.resolve(strict=False) or not out.name.endswith(".tar.gz"):
        raise SnapshotRefused("invalid_path", f"{out} must be a .tar.gz directly in {archive}")
    final = parent / out.name
    if os.path.lexists(final):
        raise SnapshotRefused("exists", str(final))
    partial_name = f"{final.name}.partial"
    with fence(superpowers, require_workflows=True) as held:
        archive.mkdir(mode=0o700, exist_ok=True)
        afd = _open(str(archive), _DIR_FLAGS, str(archive))
        created = linked = False
        try:
            fd = _open(partial_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                       partial_name, mode=0o600, dir_fd=afd)
            created = True
            members = 0
            with os.fdopen(fd, "wb") as handle:
                with tarfile.open(fileobj=handle, mode="w:gz") as tar:
                    for store in STORES:
                        if os.path.lexists(superpowers / store):
                            members += _add_store(tar, superpowers, store)
                handle.flush()
                os.fsync(handle.fileno())
            on_written()
            if _relist(superpowers) != held:
                raise SnapshotRefused("changed", "a ledger, dot-lock or store appeared or "
                                                 "vanished while the snapshot was written")
            digest = hashlib.sha256()
            with open(archive / partial_name, "rb") as written:
                for block in iter(lambda: written.read(1 << 20), b""):
                    digest.update(block)
            try:
                os.link(partial_name, final.name, src_dir_fd=afd, dst_dir_fd=afd)
            except FileExistsError as exc:
                raise SnapshotRefused("exists", str(final)) from exc
            linked = True
            os.unlink(partial_name, dir_fd=afd)
            created = False
            _fsync_dir(afd)
        except BaseException:
            with contextlib.suppress(OSError):
                if created:
                    os.unlink(partial_name, dir_fd=afd)
                if linked:
                    os.unlink(final.name, dir_fd=afd)
            raise
        finally:
            os.close(afd)
    return {"schema": REPORT_SCHEMA, "mode": "take", "snapshot": str(final),
            "sha256": f"sha256:{digest.hexdigest()}", "members": members,
            "ledgers": len(held.ledgers), "transactions": held.transactions, "taken_at": now()}


def _invalid(detail: str) -> SnapshotRefused:
    return SnapshotRefused("invalid_snapshot", detail)


def _validated_members(tar: tarfile.TarFile, snapshot: Path) -> list[tarfile.TarInfo]:
    try:
        members = tar.getmembers()
    except (tarfile.TarError, EOFError, zlib.error, gzip.BadGzipFile) as exc:
        raise _invalid(f"{snapshot}: {exc}") from exc
    for member in members:
        parts = member.name.split("/")
        if any(part in ("", ".", "..") for part in parts) or "\\" in member.name:
            raise _invalid(f"member {member.name!r} is not a relative path")
        if parts[0] not in STORES:
            raise _invalid(f"member {member.name!r} is outside {', '.join(STORES)}")
        if not (member.isdir() or member.isreg()):
            raise _invalid(f"member {member.name!r} is not a directory or regular file")
        if len(parts) == 1 and not member.isdir():
            raise _invalid(f"store {member.name!r} is not a directory")
    if not any(member.name == "workflows" and member.isdir() for member in members):
        raise _invalid("the snapshot holds no workflows directory")
    return members


def _open_snapshot(superpowers: Path, snapshot: Path) -> tuple[Path, tarfile.TarFile]:
    archive = superpowers / "archive"
    snapshot = Path(snapshot)
    try:
        found = os.lstat(snapshot)
    except OSError as exc:
        raise SnapshotRefused("invalid_path", f"{snapshot}: {exc.strerror}") from exc
    if not stat.S_ISREG(found.st_mode):
        raise SnapshotRefused("invalid_path", f"{snapshot} is not a regular, non-symlink file")
    _check_archive_home(archive)
    parent = snapshot.parent.resolve(strict=True)
    if parent != archive.resolve(strict=True):
        raise SnapshotRefused("invalid_path", f"{snapshot} must be directly in {archive}")
    resolved = parent / snapshot.name
    try:
        return resolved, tarfile.open(resolved, "r:gz")
    except (tarfile.TarError, EOFError, zlib.error, gzip.BadGzipFile) as exc:
        raise _invalid(f"{resolved}: {exc}") from exc


def _moved(superpowers: Path) -> list[str]:
    """The live paths a restore moves aside, in `ASIDE_NAMES` order."""
    moved = []
    for relative in ASIDE_NAMES:
        try:
            found = os.lstat(superpowers / relative)
        except FileNotFoundError:
            continue
        if not stat.S_ISDIR(found.st_mode):
            raise SnapshotRefused("invalid_store", f"{relative} is a symlink or not a directory")
        moved.append(relative)
    return moved


def _newer(superpowers: Path, moved: list[str], than_ns: int) -> list[str]:
    newer = []
    for relative in moved:
        for dirpath, _, filenames in os.walk(superpowers / relative, followlinks=False):
            for name in filenames:
                full = Path(dirpath) / name
                found = os.lstat(full)
                if stat.S_ISREG(found.st_mode) and found.st_mtime_ns > than_ns:
                    newer.append(full.relative_to(superpowers).as_posix())
    return sorted(newer)


def restore(root: Path, snapshot: Path, *, apply: bool, now: Callable[[], str]) -> dict:
    """Return both stores to a snapshot, moving every live file aside and deleting none."""
    root = _resolve_root(root)
    superpowers = root / ".superpowers"
    snapshot, tar = _open_snapshot(superpowers, snapshot)
    with tar:
        members = _validated_members(tar, snapshot)
        restored = [store for store in STORES
                    if any(m.name.split("/")[0] == store for m in members)]
        digest = hashlib.sha256(snapshot.read_bytes()).hexdigest()
        moved = _moved(superpowers)
        report = {"schema": REPORT_SCHEMA, "mode": "restore_dry_run", "snapshot": str(snapshot),
                  "sha256": f"sha256:{digest}", "aside": None, "moved": moved,
                  "restored": restored, "transactions": "attempt-transactions" in restored,
                  "newer": _newer(superpowers, moved, snapshot.stat().st_mtime_ns)}
        if not apply:
            return report
        with fence(superpowers, require_workflows=False):
            moved = _moved(superpowers)
            stem = snapshot.name.removesuffix(".tar.gz")
            stamp = now().replace("-", "").replace(":", "")
            aside = superpowers / "archive" / f"{stem}.restore-{stamp}"
            try:
                aside.mkdir(mode=0o700)
            except FileExistsError as exc:
                raise SnapshotRefused("exists", str(aside)) from exc
            report.update(mode="restore", aside=str(aside), moved=moved,
                          newer=_newer(superpowers, moved, snapshot.stat().st_mtime_ns))
            try:
                for relative in moved:
                    os.rename(superpowers / relative, aside / ASIDE_NAMES[relative])
                tar.extractall(path=superpowers, members=members, filter="data")
                for directory in (superpowers, superpowers / "archive"):
                    fd = os.open(directory, _DIR_FLAGS)
                    try:
                        _fsync_dir(fd)
                    finally:
                        os.close(fd)
            except OSError as exc:
                if moved:
                    exc.filename = (f"{exc.filename} (moved-aside files are kept in {aside})")
                raise
        return report


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="ledger-snapshot", description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    take_parser = commands.add_parser("take", help="write a fenced snapshot of both stores")
    take_parser.add_argument("--repo-root", required=True, type=Path)
    take_parser.add_argument("--out", required=True, type=Path)
    restore_parser = commands.add_parser("restore", help="restore a snapshot, moving live aside")
    restore_parser.add_argument("--repo-root", required=True, type=Path)
    restore_parser.add_argument("--snapshot", required=True, type=Path)
    restore_parser.add_argument("--apply", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
        if args.command == "take":
            report = take(args.repo_root, args.out, now=_now)
        else:
            report = restore(args.repo_root, args.snapshot, apply=args.apply, now=_now)
    except _UsageError as exc:
        print(f"ledger-snapshot: usage: {exc}".replace("\n", " "), file=sys.stderr)
        return 2
    except SnapshotRefused as exc:
        print(f"ledger-snapshot: {exc.code}: {exc.detail}".replace("\n", " "), file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"ledger-snapshot: {exc.strerror or type(exc).__name__}: "
              f"{exc.filename or exc}".replace("\n", " "), file=sys.stderr)
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
