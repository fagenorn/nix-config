"""`ledger-archive`: move labelled, refused workflow ledgers out of `migrate`'s inventory (#584).

A ledger that `workflow-state migrate` refuses (an unknown dialect, an ambiguous lineage and
so on) stays in `.superpowers/workflows` forever and keeps every later inventory red. This
command is the acknowledged cleanup of #72: the owner labels each refused ledger, and only a
labelled ledger is moved, whole, to `.superpowers/archive/workflows/<ledger>` with a sidecar
`<ledger>.archived.json`. A dry run (the default) writes nothing. With `--apply`, every
candidate's directory is opened through a validated `O_NOFOLLOW` directory fd, its lock is
taken without blocking and all locks are held together while the inventory is read again,
so a ledger a live run is using, or one that changed since the inventory, is skipped and
left in place.
"""

from __future__ import annotations

import argparse
import contextlib
import errno
import fcntl
import hashlib
import json
import os
import stat
import subprocess
import sys
import tempfile
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path

from agent_tools import attempt_identity
from agent_tools.canonical import reject_duplicate_keys, reject_nonfinite_literal

REPORT_SCHEMA = "ledger-archive-report/v1"
RECORD_SCHEMA = "ledger-archive-record/v1"
SKIP_REASONS = ("destination_exists", "locked", "ledger_missing", "changed", "unlabelled")
DISPOSITIONS = ("archived", "abandoned", "unresolved")
IDENTITY_FIELDS = ("verdict", "reason", "run_id", "schema_version", "dialect", "issues")
LABEL_MEMBERS = ("disposition", "redeliver")
_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


class ArchiveRefused(ValueError):
    """One refusal: a closed code and its detail."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


class _Parser(argparse.ArgumentParser):
    def error(self, message: str):  # type: ignore[override]
        raise ArchiveRefused("usage", message)


def archive_root(superpowers: Path) -> Path:
    return superpowers / "archive" / "workflows"


def _record_path(superpowers: Path, ledger: str) -> Path:
    return archive_root(superpowers) / f"{ledger}.archived.json"


def _name_violation(name: object) -> str | None:
    """Why `name` is not one safe path component, or None."""
    if not isinstance(name, str) or not name:
        return "a ledger name must be a non-empty string"
    if name.startswith("."):
        return f"ledger name {name!r} must not start with a dot"
    if "/" in name or "\0" in name:
        return f"ledger name {name!r} must be one path component"
    return None


def _strict_json(text: str) -> object:
    return json.loads(text, object_pairs_hook=reject_duplicate_keys,
                      parse_constant=reject_nonfinite_literal)


def _label_violation(label: object) -> str | None:
    if not isinstance(label, dict) or set(label) != set(LABEL_MEMBERS):
        return f"a label must be an object with exactly {', '.join(LABEL_MEMBERS)}"
    disposition, redeliver = label["disposition"], label["redeliver"]
    if disposition not in DISPOSITIONS:
        return f"disposition must be one of {', '.join(DISPOSITIONS)}"
    if not isinstance(redeliver, list) or any(
            not isinstance(n, int) or isinstance(n, bool) or n < 1 for n in redeliver):
        return "redeliver must be a list of integers >= 1"
    if any(a >= b for a, b in zip(redeliver, redeliver[1:])):
        return "redeliver must be strictly ascending"
    if disposition == "archived" and redeliver:
        return "an archived label must have an empty redeliver"
    if disposition == "abandoned" and not redeliver:
        return "an abandoned label must name at least one issue in redeliver"
    return None


def load_labels(path: Path) -> dict[str, dict]:
    """The labels file: `{ledger: {"disposition": ..., "redeliver": [...]}}`, strictly."""
    try:
        labels = _strict_json(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ArchiveRefused("invalid_labels", f"{path}: {exc}") from exc
    if not isinstance(labels, dict):
        raise ArchiveRefused("invalid_labels", "the labels file must be one JSON object")
    for name, label in labels.items():
        problem = _name_violation(name) or _label_violation(label)
        if problem:
            raise ArchiveRefused("invalid_labels", f"{name!r}: {problem}")
    return labels


def _check_report(document: object) -> dict:
    if (not isinstance(document, dict)
            or document.get("schema") != attempt_identity.REPORT_SCHEMA
            or document.get("mode") != "dry_run"
            or not isinstance(document.get("ledgers"), list)
            or not all(isinstance(row, dict) for row in document["ledgers"])):
        raise ArchiveRefused("invalid_report", "not a dry-run attempt-migration-report/v1")
    return document


def plan_rows(superpowers: Path, migration: dict, labels: dict[str, dict] | None) -> list[dict]:
    """One report row per refused ledger of the dry-run document, in its order."""
    rows = []
    for source in _check_report(migration)["ledgers"]:
        if source.get("verdict") != "refused":
            continue
        ledger = source.get("ledger")
        problem = _name_violation(ledger)
        if problem:
            raise ArchiveRefused("invalid_ledger_name", problem)
        label = None if labels is None else labels.get(ledger)
        destination = archive_root(superpowers) / ledger
        row = {"ledger": ledger, "run_id": source.get("run_id"),
               "schema_version": source.get("schema_version"),
               "dialect": source.get("dialect"), "issues": source.get("issues"),
               "reason": source.get("reason"),
               "disposition": None if label is None else label["disposition"],
               "redeliver": None if label is None else list(label["redeliver"]),
               "destination": str(destination), "verdict": "would_archive",
               "skip_reason": None}
        if labels is not None and label is None:
            row["verdict"], row["skip_reason"] = "skipped", "unlabelled"
        elif (os.path.lexists(destination)
              or os.path.lexists(_record_path(superpowers, ledger))):
            row["verdict"], row["skip_reason"] = "skipped", "destination_exists"
        rows.append(row)
    return rows


def _dry_run(root: Path) -> dict:
    """`workflow-state migrate --repo-root <root>` (the dry run), parsed and checked."""
    completed = subprocess.run(["workflow-state", "migrate", "--repo-root", str(root)],
                               capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        lines = completed.stderr.strip().splitlines()
        raise ArchiveRefused("workflow_state_failed",
                             lines[-1] if lines else f"exit {completed.returncode}")
    try:
        document = _strict_json(completed.stdout)
    except ValueError as exc:
        raise ArchiveRefused("invalid_report", str(exc)) from exc
    return _check_report(document)


def _check_archive_root(superpowers: Path) -> None:
    for path in (superpowers / "archive", archive_root(superpowers)):
        try:
            mode = os.lstat(path).st_mode
        except FileNotFoundError:
            return
        if not stat.S_ISDIR(mode):
            raise ArchiveRefused("archive_home", f"{path} is not a plain directory")


def _ensure_archive_root(superpowers: Path) -> None:
    _check_archive_root(superpowers)
    for path in (superpowers / "archive", archive_root(superpowers)):
        path.mkdir(mode=0o700, exist_ok=True)


def _same_directory(lfd: int, workflows: Path, ledger: str) -> bool:
    """Whether `workflows/<ledger>` is still the directory `lfd` holds."""
    try:
        path_stat = os.lstat(workflows / ledger)
    except FileNotFoundError:
        return False
    if not stat.S_ISDIR(path_stat.st_mode):
        return False
    held = os.fstat(lfd)
    return (held.st_dev, held.st_ino) == (path_stat.st_dev, path_stat.st_ino)


def _state_hash(lfd: int) -> str | None:
    """`sha256:` of `state.json` read through `lfd`, or None when it cannot be read."""
    try:
        fd = os.open("state.json", os.O_RDONLY | os.O_NOFOLLOW, dir_fd=lfd)
    except OSError as exc:
        if exc.errno in (errno.ENOENT, errno.ELOOP, errno.ENOTDIR):
            return None
        raise
    with os.fdopen(fd, "rb") as handle:
        return "sha256:" + hashlib.sha256(handle.read()).hexdigest()


def _fsync_dir(path: Path | int) -> None:
    fd = path if isinstance(path, int) else os.open(path, _DIR_FLAGS)
    try:
        os.fsync(fd)
    finally:
        if not isinstance(path, int):
            os.close(fd)


def _prepare_record(destination_dir: Path, record: dict) -> Path:
    """Write `record` durably to a temporary file beside its final name; return the temporary.

    Every byte that can fail for lack of space is written here, before the ledger moves, so
    publishing the record afterwards is one rename and needs no new space.
    """
    fd, temporary = tempfile.mkstemp(dir=destination_dir, prefix=".record-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary)
        raise
    return Path(temporary)


def _skip(row: dict, reason: str) -> None:
    row["verdict"], row["skip_reason"] = "skipped", reason


def _open_candidates(wfd: int, rows: list[dict], opened: list[int]) -> list[dict]:
    """Open each candidate through `wfd` and take its lock; the held ones, in row order."""
    held = []
    for row in rows:
        if row["verdict"] != "would_archive":
            continue
        try:
            lfd = os.open(row["ledger"], _DIR_FLAGS, dir_fd=wfd)
        except OSError as exc:
            if exc.errno in (errno.ENOENT, errno.ENOTDIR, errno.ELOOP):
                _skip(row, "ledger_missing")
                continue
            raise
        opened.append(lfd)
        try:
            lock = os.open("state.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600,
                           dir_fd=lfd)
        except OSError as exc:
            if exc.errno == errno.ELOOP:
                raise ArchiveRefused("symlinked_lock",
                                     f"{row['ledger']}/state.lock is a symlink") from exc
            raise
        opened.append(lock)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            _skip(row, "locked")
            continue
        held.append({"row": row, "lfd": lfd})
    return held


def apply_rows(root: Path, superpowers: Path, rows: list[dict], *,
               now: Callable[[], str]) -> list[dict]:
    """Archive every `would_archive` row that stays eligible under its lock; the final rows."""
    rows = [dict(row) for row in rows]
    for row in rows:
        if row["verdict"] == "would_archive" and row["disposition"] is None:
            _skip(row, "unlabelled")
    if not any(row["verdict"] == "would_archive" for row in rows):
        return rows
    workflows = superpowers / "workflows"
    archive = archive_root(superpowers)
    opened: list[int] = []
    try:
        wfd = os.open(workflows, _DIR_FLAGS)
        opened.append(wfd)
        held = _open_candidates(wfd, rows, opened)
        if not held:
            return rows
        first: dict[str, str | None] = {}
        for entry in held:
            row = entry["row"]
            if not _same_directory(entry["lfd"], workflows, row["ledger"]):
                _skip(row, "ledger_missing")
            else:
                first[row["ledger"]] = _state_hash(entry["lfd"])
                if first[row["ledger"]] is None:
                    _skip(row, "changed")
        reread = {source.get("ledger"): source for source in _dry_run(root)["ledgers"]}
        for entry in held:
            row = entry["row"]
            if row["verdict"] != "would_archive":
                continue
            current = reread.get(row["ledger"])
            expected = {**row, "verdict": "refused"}
            if current is None or any(current.get(name) != expected.get(name)
                                      for name in IDENTITY_FIELDS):
                _skip(row, "changed")
            else:
                entry["current"] = current
        _ensure_archive_root(superpowers)
        for entry in held:
            row = entry["row"]
            if row["verdict"] != "would_archive":
                continue
            ledger, lfd = row["ledger"], entry["lfd"]
            destination = archive / ledger
            if (os.path.lexists(destination)
                    or os.path.lexists(_record_path(superpowers, ledger))):
                _skip(row, "destination_exists")
            elif not _same_directory(lfd, workflows, ledger):
                _skip(row, "ledger_missing")
            elif _state_hash(lfd) != first[ledger]:
                _skip(row, "changed")
            else:
                current = entry["current"]
                temporary = _prepare_record(archive, {
                    "schema": RECORD_SCHEMA, "ledger": ledger,
                    "run_id": current.get("run_id"),
                    "schema_version": current.get("schema_version"),
                    "dialect": current.get("dialect"), "issues": current.get("issues"),
                    "reason": current.get("reason"), "source": str(workflows / ledger),
                    "destination": str(destination), "disposition": row["disposition"],
                    "redeliver": row["redeliver"], "archived_at": now(),
                    "state_sha256": first[ledger]})
                moved = False
                try:
                    os.rename(workflows / ledger, destination)
                    moved = True
                    os.replace(temporary, _record_path(superpowers, ledger))
                except BaseException:
                    # A ledger is archived only together with its record: put it back, so
                    # a rerun still finds it in the inventory.
                    with contextlib.suppress(OSError):
                        if moved:
                            os.rename(destination, workflows / ledger)
                    with contextlib.suppress(OSError):
                        os.unlink(temporary)
                    raise
                _fsync_dir(wfd)
                _fsync_dir(archive)
                row["verdict"] = "archived"
        return rows
    finally:
        for fd in reversed(opened):
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
            os.close(fd)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _counts(rows: list[dict]) -> dict[str, int]:
    return {name: sum(row["verdict"] == name for row in rows)
            for name in ("would_archive", "archived", "skipped")}


def _build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="ledger-archive", description=__doc__.splitlines()[0])
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--labels")
    return parser


def _run(argv: Sequence[str] | None) -> tuple[dict, int]:
    args = _build_parser().parse_args(argv)
    if args.apply and args.labels is None:
        raise ArchiveRefused("labels_required", "--apply needs --labels FILE")
    labels = None if args.labels is None else load_labels(Path(args.labels))
    try:
        root = Path(args.repo_root).resolve(strict=True)
    except OSError as exc:
        raise ArchiveRefused("repo_root", f"{args.repo_root}: {exc.strerror}") from exc
    superpowers = root / ".superpowers"
    try:
        workflows_mode = os.lstat(superpowers / "workflows").st_mode
    except OSError as exc:
        raise ArchiveRefused("workflows_missing", f"{superpowers / 'workflows'}: "
                             f"{exc.strerror}") from exc
    if not stat.S_ISDIR(workflows_mode):
        raise ArchiveRefused("workflows_missing",
                             f"{superpowers / 'workflows'} is not a plain directory")
    rows = plan_rows(superpowers, _dry_run(root), labels)
    post_check = None
    if args.apply:
        _check_archive_root(superpowers)
        rows = apply_rows(root, superpowers, rows, now=_now)
        after = _dry_run(root)["ledgers"]
        archived = {row["ledger"] for row in rows if row["verdict"] == "archived"}
        skipped = {row["ledger"] for row in rows if row["verdict"] == "skipped"}
        refused = [source.get("ledger") for source in after
                   if source.get("verdict") == "refused"]
        unexpected = sorted(
            {source.get("ledger") for source in after} & archived
            | {name for name in refused if name not in skipped})
        post_check = {"passed": not unexpected, "refused_after": len(refused),
                      "unexpected": unexpected}
    report = {"schema": REPORT_SCHEMA, "mode": "apply" if args.apply else "dry_run",
              "archive_dir": str(archive_root(superpowers)), "ledgers": rows,
              "counts": _counts(rows), "post_check": post_check}
    return report, 0 if post_check is None or post_check["passed"] else 1


def main(argv: Sequence[str] | None = None) -> int:
    try:
        report, code = _run(argv)
    except ArchiveRefused as exc:
        print(f"ledger-archive: {exc.code}: {exc.detail}".replace("\n", " "), file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"ledger-archive: {exc.strerror or type(exc).__name__}: "
              f"{exc.filename or exc}".replace("\n", " "), file=sys.stderr)
        return 2
    print(json.dumps(report, sort_keys=True))
    return code


if __name__ == "__main__":
    sys.exit(main())
