"""Archive-before-remove for retained worktrees that no ledger maps (issue 585).

    worktree-reconcile plan --repo-root R --fleet-root F [--fleet-root F ...] --archive-root DIR
                            [--refused-pending] [--keep PATH ...] --out FILE
    worktree-reconcile apply --plan FILE --archive-root DIR --acknowledge-cleanup
    worktree-reconcile restore --manifest FILE --n N
    worktree-reconcile audit --run-dir DIR --archive-root DIR --repo-root R [--repo-root R ...]

`plan` is read-only: it classifies the linked worktrees of one root with
`agent_tools.worktree_mapping` and records, per worktree, the facts that decide whether it may be
removed. `apply` re-derives every `archive_remove` entry from fresh inputs immediately before
acting on it and acts only when the fresh entry equals the planned one. A removal is always
preceded by an archive (a copy of the worktree's git admin directory, a pin commit naming
everything that admin directory alone reaches, and a verified bundle of it) and a durable record.
Branches are never deleted, and `git worktree prune` and `git gc` are never run.

`audit` is the read-only pre-merge check: every red path of each root is `kept` with a reason the
plan recorded, `removed` on a durable record and a whole archive, `gone_elsewhere`, or
`new_since_plan`; anything else is `unresolved`.

Exit codes: 0 success; 1 when any result is `failed` (`audit`: when any path is unresolved); 2 a
refusal or tool error (`worktree-reconcile: <code>: <detail>` on stderr, nothing on stdout).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from collections.abc import Callable, Iterable, Iterator
from datetime import datetime, timezone
from pathlib import Path

from agent_tools import worktree_mapping
from agent_tools.github_remote import github_slug
from agent_tools.worktree_mapping import (MappingError, Worktree, classify, is_runner_workspace,
                                          ledger_matches, list_worktrees, verdicts_of)
from agent_tools.worktree_mapping import classify_root

PLAN_SCHEMA = "worktree-reconcile-plan/v2"
APPLY_SCHEMA = "worktree-reconcile-apply/v1"
ARCHIVE_SCHEMA = "worktree-reconcile-archive/v1"
KEEP_REASONS = ("live_process", "fleet_ledger", "locked", "open_pr", "git_operation",
                "refused_ledger_pending", "nested_worktree", "operator", "cross_device")

GIT_TIMEOUT = 300
PROBE_TIMEOUT = 120
ZERO_OID = "0" * 40
_OID = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
_OPERATION_FILES = ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "BISECT_LOG")
_OPERATION_DIRS = ("rebase-merge", "rebase-apply")
_IDENTITY = {"GIT_AUTHOR_NAME": "worktree-reconcile", "GIT_AUTHOR_EMAIL": "worktree-reconcile@localhost",
             "GIT_COMMITTER_NAME": "worktree-reconcile",
             "GIT_COMMITTER_EMAIL": "worktree-reconcile@localhost"}
_GIT_FAILURES = (OSError, subprocess.SubprocessError)


class ReconcileError(Exception):
    """A refusal or tool error; `code` is one of the codes the command prints."""

    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


# --- subprocess helpers -------------------------------------------------------------------

def _text(raw: bytes) -> str:
    return raw.decode("utf-8", "surrogateescape")


def _run(argv: list[str], *, env: dict[str, str] | None = None, cwd: str | None = None,
         timeout: int = GIT_TIMEOUT) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout,
                              check=False, env=env, cwd=cwd)
    except _GIT_FAILURES as error:
        raise ReconcileError("tool_error", f"{argv[0]} failed: {error}") from None


def _git(root: Path | str, *args: str, env: dict[str, str] | None = None, read: bool = False,
         check: bool = True) -> subprocess.CompletedProcess:
    argv = ["git"] + (["--no-optional-locks"] if read else []) + ["-C", str(root), *args]
    done = _run(argv, env=env)
    if check and done.returncode != 0:
        detail = _text(done.stderr).strip() or f"exit {done.returncode}"
        raise ReconcileError("tool_error", f"git {args[0]} failed in {root}: {detail}")
    return done


def _git_out(root: Path | str, *args: str, env: dict[str, str] | None = None,
             read: bool = False) -> str:
    return _text(_git(root, *args, env=env, read=read).stdout)


def _index_env(index: str, extra: dict[str, str] | None = None) -> dict[str, str]:
    return {**os.environ, "GIT_INDEX_FILE": index, **(extra or {})}


# --- durable writes -----------------------------------------------------------------------

def _fsync_dir(directory: Path) -> None:
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_atomic(directory: Path, name: str, data: bytes) -> None:
    """`directory/name` replaced by `data` atomically and durably, mode 0600."""
    tmp = directory / f".{name}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, directory / name)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    _fsync_dir(directory)


def _dump(obj: object) -> bytes:
    return (json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode(
        "utf-8", "surrogateescape")


def write_record(dir: Path, record: dict) -> None:
    """`<dir>/record.json`, atomically and durably; every record state change goes through here."""
    _write_atomic(Path(dir), "record.json", _dump(record))


def _write_manifest(directory: Path, manifest: dict) -> None:
    _write_atomic(directory, "manifest.json", _dump(manifest))


# --- fingerprint and admin directory -----------------------------------------------------

def _tree_lines(path: str) -> list[bytes]:
    lines: list[bytes] = []
    pending = [""]
    while pending:
        rel = pending.pop()
        here = os.path.join(path, rel) if rel else path
        try:
            names = sorted(os.listdir(here))
        except OSError as error:
            lines.append(f"{rel}\0unreadable\0{error.errno}".encode("utf-8", "surrogateescape"))
            continue
        for name in names:
            child = os.path.join(rel, name) if rel else name
            try:
                st = os.lstat(os.path.join(path, child))
            except OSError as error:
                lines.append(f"{child}\0vanished\0{error.errno}".encode("utf-8", "surrogateescape"))
                continue
            line = f"{child}\0{st.st_mode}\0{st.st_size}\0{st.st_mtime_ns}\0{st.st_ino}"
            if stat.S_ISLNK(st.st_mode):
                try:
                    line += "\0" + os.readlink(os.path.join(path, child))
                except OSError:
                    line += "\0?"
            lines.append(line.encode("utf-8", "surrogateescape"))
            if stat.S_ISDIR(st.st_mode):
                pending.append(child)
    return sorted(lines)


def _regular_files(base: str) -> Iterator[tuple[str, str]]:
    """`(relpath, absolute)` for every regular file under `base`, sorted by relpath."""
    found: list[tuple[str, str]] = []
    for here, dirs, names in os.walk(base, followlinks=False):
        for name in names:
            full = os.path.join(here, name)
            if not os.path.islink(full) and os.path.isfile(full):
                found.append((os.path.relpath(full, base), full))
    yield from sorted(found)


def fingerprint(path: str, admin: str | None) -> str:
    """sha256 over the worktree's entry metadata and every byte of its admin directory."""
    digest = hashlib.sha256()
    digest.update(b"tree\n")
    if os.path.lexists(path):
        for line in _tree_lines(path):
            digest.update(line + b"\n")
    digest.update(b"admin\n")
    if admin is not None and os.path.isdir(admin):
        for rel, full in _regular_files(admin):
            digest.update(rel.encode("utf-8", "surrogateescape") + b"\0")
            try:
                data = Path(full).read_bytes()
            except OSError as error:
                data = f"unreadable {error.errno}".encode()
            digest.update(str(len(data)).encode() + b"\0" + data)
    return digest.hexdigest()


def admin_digests(admin: Path) -> dict[str, str]:
    """relpath (POSIX) to sha256 of each regular file under `admin`; a symlink is its target."""
    out: dict[str, str] = {}
    base = str(admin)
    for here, dirs, names in os.walk(base, followlinks=False):
        for name in dirs + names:
            full = os.path.join(here, name)
            rel = Path(os.path.relpath(full, base)).as_posix()
            if os.path.islink(full):
                out[rel] = "symlink:" + os.readlink(full)
            elif name in names and os.path.isfile(full):
                out[rel] = hashlib.sha256(Path(full).read_bytes()).hexdigest()
    return dict(sorted(out.items()))


def _common_dir(root: Path) -> str:
    return _git_out(root, "rev-parse", "--path-format=absolute", "--git-common-dir",
                    read=True).strip()


def admin_dir(root: Path, path: str) -> str | None:
    """The `<common>/worktrees/<id>` directory whose `gitdir` file names `path`'s `.git`."""
    base = Path(_common_dir(root)) / "worktrees"
    if not base.is_dir():
        return None
    wanted = {path.rstrip("/") + "/.git"}
    if os.path.isdir(path):
        wanted.add(os.path.realpath(path) + "/.git")
    wanted |= {os.path.realpath(w) for w in wanted}
    for candidate in sorted(base.iterdir()):
        try:
            text = (candidate / "gitdir").read_text(encoding="utf-8", errors="surrogateescape").strip()
        except OSError:
            continue
        if text in wanted or os.path.realpath(text) in wanted:
            return str(candidate)
    return None


# --- pins ----------------------------------------------------------------------------------

def _oid_of(file: str) -> str | None:
    try:
        content = Path(file).read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None
    return content if _OID.fullmatch(content) else None


def pin_sources(root: Path, admin: str, head: str | None) -> dict:
    """Every object id the admin directory's own files name, read from those files only."""
    found: list[tuple[str, str]] = []
    if head:
        found.append(("head", head))
    refs = os.path.join(admin, "refs")
    if os.path.isdir(refs):
        for rel, full in _regular_files(refs):
            oid = _oid_of(full)
            if oid:
                found.append((f"ref/{Path(rel).as_posix()}", oid))
    for name in ("ORIG_HEAD", "AUTO_MERGE"):
        oid = _oid_of(os.path.join(admin, name))
        if oid:
            found.append((name, oid))
    logs = os.path.join(admin, "logs")
    if os.path.isdir(logs):
        for rel, full in _regular_files(logs):
            try:
                content = Path(full).read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for number, line in enumerate(content.split("\n"), 1):
                fields = line.partition("\t")[0].split(" ")
                for side, oid in zip(("old", "new"), fields[:2]):
                    if _OID.fullmatch(oid) and set(oid) != {"0"}:
                        found.append((f"log/{Path(rel).as_posix()}:{number}:{side}", oid))
    kinds: dict[str, str | None] = {}
    for _, oid in found:
        if oid not in kinds:
            done = _git(root, "cat-file", "-t", oid, read=True, check=False)
            kinds[oid] = _text(done.stdout).strip() if done.returncode == 0 else None
    sources: dict[str, list[str]] = {}
    missing: list[dict] = []
    non_commit: list[dict] = []
    for source, oid in found:
        kind = kinds[oid]
        if kind is None:
            missing.append({"source": source, "sha": oid})
        elif kind != "commit":
            non_commit.append({"source": source, "sha": oid})
        else:
            sources.setdefault(oid, []).append(source)
    commits = [head] if head in sources else []
    commits += sorted(oid for oid in sources if oid not in commits)
    return {"commits": commits, "sources": sources, "missing": missing, "non_commit": non_commit}


# --- the entry ------------------------------------------------------------------------------

def default_device_of(path: str) -> int:
    return os.stat(path).st_dev


def _is_live(path: str, real: str | None, live: set[str]) -> bool:
    names = {path} | ({real} if real else set())
    return any(cwd == name or cwd.startswith(name.rstrip("/") + "/") for cwd in live for name in names)


def _holds_another(path: str, real: str | None, others: Iterable[str]) -> bool:
    """True when a path of `others` lies below this worktree: removing it would carry that one off."""
    names = {path} | ({real} if real else set())
    for other in others:
        spellings = {other, os.path.realpath(other)}
        if any(o != name and o.startswith(name.rstrip("/") + "/") for o in spellings for name in names):
            return True
    return False


def _normalize_keep(keeps: Iterable[str]) -> frozenset[str]:
    """Each operator `--keep` as the one absolute, symlink-free spelling a worktree compares by."""
    return frozenset(os.path.realpath(os.path.expanduser(str(k))) for k in keeps)


def _short(branch: str | None) -> str | None:
    if branch is None:
        return None
    return branch[len("refs/heads/"):] if branch.startswith("refs/heads/") else branch


def _index_facts(root: Path, admin: str | None, head: str | None) -> tuple[bool, bool]:
    """`(index_differs, unmerged)` of the admin directory's own index; never refreshes it."""
    index = os.path.join(admin, "index") if admin else None
    if index is None or not os.path.isfile(index):
        return False, False
    env = _index_env(index)
    differs = False
    if head:
        done = _git(root, "diff-index", "--cached", "--quiet", head, "--", env=env, read=True,
                    check=False)
        differs = done.returncode != 0
    unmerged = bool(_git_out(root, "ls-files", "-u", env=env, read=True).strip())
    return differs, unmerged


def entry_of(root: Path, wt: Worktree, n: int, *, verdicts, fleet_roots, archive_root, live, prs,
             refused_pending, operator_keep, other_paths=(), device_of=default_device_of) -> dict:
    """The one derivation of an entry; `build_plan` and `apply_plan` both call it."""
    path = wt.path
    exists = os.path.isdir(path)
    real = os.path.realpath(path) if exists else None
    admin = admin_dir(root, path)
    names = ledger_matches(root, path)
    kind = classify(names, verdicts)
    differs, unmerged = _index_facts(root, admin, wt.head)
    pushed = bool(wt.head) and bool(_git_out(
        root, "for-each-ref", "--contains", wt.head, "refs/remotes", read=True).strip())
    pins = pin_sources(root, admin, wt.head) if admin else None
    open_pr = prs.get(_short(wt.branch)) if wt.branch else None
    reasons: set[str] = set()
    if _is_live(path, real, live):
        reasons.add("live_process")
    own = os.path.realpath(root)
    for fleet in fleet_roots:
        if os.path.realpath(fleet) != own and ledger_matches(Path(fleet), path):
            reasons.add("fleet_ledger")
            break
    if wt.locked:
        reasons.add("locked")
    if open_pr is not None:
        reasons.add("open_pr")
    operation = (admin is None or wt.head is None or unmerged
                 or (pins is not None and bool(pins["non_commit"]))
                 or any(os.path.exists(os.path.join(admin, f)) for f in _OPERATION_FILES)
                 or any(os.path.isdir(os.path.join(admin, d)) for d in _OPERATION_DIRS))
    if operation:
        reasons.add("git_operation")
    if kind == "refused-only" and refused_pending:
        reasons.add("refused_ledger_pending")
    if _holds_another(path, real, other_paths):
        reasons.add("nested_worktree")
    if path in operator_keep or os.path.realpath(path) in operator_keep:
        reasons.add("operator")
    if exists and device_of(path) != device_of(str(archive_root)):
        reasons.add("cross_device")
    keep = [reason for reason in KEEP_REASONS if reason in reasons]
    action = "none" if kind in ("current", "migrate") else "keep" if keep else "archive_remove"
    return {"n": n, "path": path, "realpath": real, "admin": admin, "class": kind, "ledgers": names,
            "head": wt.head, "branch": wt.branch, "locked": wt.locked, "prunable": wt.prunable,
            "fingerprint": fingerprint(path, admin), "index_differs": differs, "pushed": pushed,
            "pins": pins, "open_pr": open_pr, "keep": keep, "action": action}


def _other_paths(root: Path, listing: list[Worktree], wt: Worktree) -> list[str]:
    """Every registered path but `wt`'s own, the main checkout included."""
    return [str(root)] + [other.path for other in listing if other.path != wt.path]


def build_plan(root: Path, migrate_report: dict, *, fleet_roots: list[Path], archive_root: Path,
               live_cwds: Callable[[], set[str]],
               open_prs: Callable[[Path], dict[str, dict]], now: datetime, refused_pending: bool,
               operator_keep: frozenset[str] = frozenset(),
               device_of: Callable[[str], int] = default_device_of) -> dict:
    """The read-only plan for one root."""
    done = _git(root, "rev-parse", "--show-ref-format", read=True, check=False)
    storage = _text(done.stdout).strip()
    if done.returncode != 0 or storage != "files":
        raise ReconcileError("unsupported_ref_storage",
                             f"{root}: ref storage is {storage or 'unknown'}, not files")
    if not Path(archive_root).is_dir():
        raise ReconcileError("bad_plan", f"archive root {archive_root} is not a directory")
    verdicts = verdicts_of(migrate_report)
    live = live_cwds()
    prs = open_prs(root)
    operator_keep = _normalize_keep(operator_keep)
    excluded: list[str] = []
    entries: list[dict] = []
    listing = list_worktrees(root)
    known = {os.path.realpath(wt.path) for wt in listing}
    for unknown in sorted(operator_keep - known):
        raise ReconcileError("unknown_keep", f"--keep {unknown} is not a linked worktree of {root}")
    for wt in listing:
        if is_runner_workspace(wt):
            excluded.append(wt.path)
            continue
        entries.append(entry_of(
            root, wt, len(entries) + 1, verdicts=verdicts, fleet_roots=fleet_roots,
            archive_root=archive_root, live=live, prs=prs, refused_pending=refused_pending,
            operator_keep=operator_keep, other_paths=_other_paths(root, listing, wt),
            device_of=device_of))
    return {"schema": PLAN_SCHEMA, "root": str(root), "run_id": now.strftime("%Y%m%dT%H%M%SZ"),
            "fleet_roots": [str(r) for r in fleet_roots], "archive_root": str(archive_root),
            "refused_pending": refused_pending, "operator_keep": sorted(operator_keep),
            "verdicts": verdicts, "excluded": excluded, "entries": entries}


# --- the archive -------------------------------------------------------------------------------

def _run_dir(archive_root: Path, run_id: str, root: Path) -> Path:
    tag = hashlib.sha256(str(root).encode("utf-8", "surrogateescape")).hexdigest()[:8]
    return Path(archive_root) / run_id / f"{Path(root).name}-{tag}"


def archive_dir(archive_root: Path, run_id: str, root: Path, n: int, path: str) -> Path:
    """The one place the archive layout is computed."""
    return _run_dir(archive_root, run_id, root) / f"{n}-{os.path.basename(path)}"


def _mkdir_private(archive_root: Path, target: Path) -> None:
    """Create `target` and every missing directory between it and `archive_root`, mode 0700."""
    missing: list[Path] = []
    here = target
    while not here.exists() and here != Path(archive_root):
        missing.append(here)
        here = here.parent
    for directory in reversed(missing):
        directory.mkdir(mode=0o700)
        os.chmod(directory, 0o700)


def _pin_message(path: str, pins: dict) -> str:
    lines = [f"worktree-reconcile: {path}", ""]
    for sha in pins["commits"]:
        lines.append(f"{sha} {', '.join(pins['sources'].get(sha, []))}")
    return "\n".join(lines) + "\n"


def _make_pin(root: Path, d: Path, entry: dict, ref: str) -> tuple[str, str]:
    scratch = d / ".index-scratch"
    index = d / "admin" / "index"
    if index.is_file():
        shutil.copyfile(index, scratch)
    tree = _git_out(root, "write-tree", env=_index_env(str(scratch))).strip()
    commits = entry["pins"]["commits"]
    message = d / ".pin-message"
    message.write_text(_pin_message(entry["path"], entry["pins"]), encoding="utf-8",
                       errors="surrogateescape")
    args = ["-c", "commit.gpgsign=false", "commit-tree", tree]
    for parent in commits:
        args += ["-p", parent]
    args += ["-F", str(message)]
    pin = _git_out(root, *args, env={**os.environ, **_IDENTITY}).strip()
    _git(root, "update-ref", ref, pin, ZERO_OID)
    for leftover in (scratch, message):
        try:
            leftover.unlink()
        except FileNotFoundError:
            pass
    return pin, tree


def _make_bundle(root: Path, d: Path, ref: str, pin: str) -> Path:
    bundle = d / "history.bundle"
    _git(root, "bundle", "create", str(bundle), ref, "--not", "--remotes")
    _git(root, "bundle", "verify", str(bundle))
    heads = [line for line in _git_out(root, "bundle", "list-heads", str(bundle)).splitlines()
             if line.strip()]
    if heads != [f"{pin} {ref}"]:
        raise ReconcileError("tool_error", f"bundle heads are {heads}, not [{pin} {ref}]")
    scratch = d / ".bundle-check"
    try:
        _git(d, "init", "--bare", "-q", str(scratch))
        info = scratch / "objects" / "info"
        info.mkdir(parents=True, exist_ok=True)
        (info / "alternates").write_text(str(Path(_common_dir(root)) / "objects") + "\n")
        _git(scratch, "bundle", "unbundle", str(bundle))
        _git(scratch, "cat-file", "-e", pin)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return bundle


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _archive(root: Path, d: Path, run_id: str, entry: dict) -> dict:
    """Steps 1 to 4 of the archive; returns the `archived` record."""
    admin = Path(entry["admin"])
    shutil.copytree(admin, d / "admin", symlinks=True)
    if admin_digests(d / "admin") != admin_digests(admin):
        raise ReconcileError("tool_error", "the admin directory changed while it was copied")
    ref = f"refs/archive/worktree-reconcile/{run_id}/{entry['n']}"
    pin, tree = _make_pin(root, d, entry, ref)
    bundle = _make_bundle(root, d, ref, pin)
    return {"schema": ARCHIVE_SCHEMA, "state": "archived", "run_id": run_id, "root": str(root),
            "n": entry["n"], "path": entry["path"], "entry": entry, "archive_ref": ref, "pin": pin,
            "tree": tree, "parents": list(entry["pins"]["commits"]),
            "admin_files": admin_digests(d / "admin"), "bundle": str(bundle),
            "bundle_sha256": _sha256_file(bundle), "bundle_heads": [[pin, ref]],
            "directory": None, "detail": "archived"}


def _remove(root: Path, d: Path, record: dict, live_cwds: Callable[[], set[str]]) -> tuple[str, str]:
    """Removal after a durable archive; returns `(outcome, detail)`."""
    path = record["path"]
    real = os.path.realpath(path) if os.path.isdir(path) else None
    if _is_live(path, real, live_cwds()):
        return "changed", "live_process_at_removal"
    tree = d / "tree"
    renamed = False
    try:
        if os.path.isdir(path):
            os.rename(path, tree)
            renamed = True
        record.update(state="renamed", directory=str(tree) if renamed else None, detail="renamed")
        write_record(d, record)
        _git(root, "worktree", "remove", "--force", path)
    except (*_GIT_FAILURES, ReconcileError) as error:
        if renamed and os.path.isdir(tree) and not os.path.lexists(path):
            os.rename(tree, path)
        record.update(state="archived", directory=None, detail=f"removal failed: {error}")
        try:
            write_record(d, record)
        except OSError:
            pass
        return "failed", f"removal failed: {error}"
    record.update(state="removed", detail="removed")
    try:
        write_record(d, record)
    except OSError as error:
        return "failed", f"removed, but the record write failed: {error}"
    return "removed", "removed"


def _differing(fresh: dict, planned: dict) -> str:
    keys = sorted(k for k in set(fresh) | set(planned) if fresh.get(k) != planned.get(k))
    return "differs: " + ", ".join(keys)


def apply_plan(plan: dict, *, migrate_dry_run: Callable[[], dict],
               live_cwds: Callable[[], set[str]], open_prs: Callable[[Path], dict[str, dict]],
               archive_root: Path, acknowledge_cleanup: bool,
               device_of: Callable[[str], int] = default_device_of) -> dict:
    """Archive then remove each candidate whose fresh derivation equals its planned entry."""
    if not acknowledge_cleanup:
        raise ReconcileError("not_acknowledged", "apply needs --acknowledge-cleanup")
    if not isinstance(plan, dict) or plan.get("schema") != PLAN_SCHEMA:
        raise ReconcileError("bad_plan", f"the plan's schema is not {PLAN_SCHEMA}")
    if str(archive_root) != plan.get("archive_root"):
        raise ReconcileError("bad_plan", "the archive root is not the plan's archive root")
    try:
        root = Path(plan["root"])
        run_id = plan["run_id"]
        entries = sorted(plan["entries"], key=lambda e: e["n"])
        fleet_roots = [Path(r) for r in plan["fleet_roots"]]
        refused_pending = bool(plan["refused_pending"])
        operator_keep = frozenset(plan["operator_keep"])
        if not isinstance(run_id, str) or not run_id:
            raise ValueError("run_id")
    except (KeyError, TypeError, ValueError) as error:
        raise ReconcileError("bad_plan", f"the plan is malformed: {error!r}") from None
    run_dir = _run_dir(archive_root, run_id, root)
    manifest_path = run_dir / "manifest.json"
    results: list[dict] = []
    details: list[dict] = []

    def flush() -> None:
        _mkdir_private(Path(archive_root), run_dir)
        _write_manifest(run_dir, {
            "schema": APPLY_SCHEMA, "root": str(root), "run_id": run_id,
            "archive_root": str(archive_root),
            "results": [{**r, "entry": e, "restore": (
                f"worktree-reconcile restore --manifest {manifest_path} --n {r['n']}")
                if r["outcome"] == "removed" else None} for r, e in zip(results, details)]})

    for entry in entries:
        result = {"n": entry["n"], "path": entry["path"], "head": entry.get("head"),
                  "outcome": "kept", "archive_ref": None, "bundle": None, "admin": None,
                  "directory": None, "detail": ""}
        results.append(result)
        details.append(entry)
        if entry["action"] != "archive_remove":
            result["detail"] = f"{entry['action']}: {','.join(entry['keep'])}".rstrip(": ,")
            flush()
            continue
        _reconcile_one(root, entry, result, run_dir=run_dir, run_id=run_id, fleet_roots=fleet_roots,
                       archive_root=archive_root, refused_pending=refused_pending,
                       operator_keep=operator_keep, migrate_dry_run=migrate_dry_run,
                       live_cwds=live_cwds, open_prs=open_prs, device_of=device_of, flush=flush)
        flush()
    flush()
    return {"schema": APPLY_SCHEMA, "run_id": run_id, "root": str(root),
            "manifest": str(manifest_path), "results": results}


def _reconcile_one(root: Path, entry: dict, result: dict, *, run_dir: Path, run_id: str,
                   fleet_roots, archive_root, refused_pending, operator_keep, migrate_dry_run,
                   live_cwds, open_prs, device_of, flush) -> None:
    try:
        listing = list_worktrees(root)
        wt = next((w for w in listing if w.path == entry["path"]), None)
    except MappingError as error:
        result.update(outcome="failed", detail=str(error))
        return
    if wt is None:
        result.update(outcome="changed", detail="missing_from_listing")
        return
    report = migrate_dry_run()
    live = live_cwds()
    prs = open_prs(root)
    try:
        fresh = entry_of(root, wt, entry["n"], verdicts=verdicts_of(report), fleet_roots=fleet_roots,
                         archive_root=archive_root, live=live, prs=prs,
                         refused_pending=refused_pending, operator_keep=operator_keep,
                         other_paths=_other_paths(root, listing, wt), device_of=device_of)
    except (MappingError, ReconcileError, OSError) as error:
        result.update(outcome="failed", detail=f"re-check failed: {error}")
        return
    if fresh != entry:
        result.update(outcome="changed", detail=_differing(fresh, entry))
        return
    d = archive_dir(archive_root, run_id, root, entry["n"], entry["path"])
    try:
        _mkdir_private(Path(archive_root), d)
        record = _archive(root, d, run_id, entry)
        write_record(d, record)
    except (*_GIT_FAILURES, ReconcileError, shutil.Error) as error:
        result.update(outcome="failed", detail=f"archive failed: {error}")
        return
    result.update(archive_ref=record["archive_ref"], bundle=record["bundle"],
                  admin=str(d / "admin"))
    outcome, detail = _remove(root, d, record, live_cwds)
    result.update(outcome=outcome, detail=detail, directory=record["directory"])


# --- restore -----------------------------------------------------------------------------------

def _checked_out_elsewhere(root: Path, branch: str) -> bool:
    listing = _git_out(root, "worktree", "list", "--porcelain", read=True)
    return any(line == f"branch {branch}" for line in listing.splitlines())


def restore_entry(manifest: Path, n: int) -> dict:
    """Put a `removed` entry back from its archive; the archive and the pin ref stay."""
    try:
        data = json.loads(Path(manifest).read_text(encoding="utf-8"))
        root = Path(data["root"])
        item = next((r for r in data["results"] if r.get("n") == n), None)
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise ReconcileError("bad_plan", f"cannot read manifest {manifest}: {error}") from None
    if item is None or item.get("outcome") != "removed":
        raise ReconcileError("not_removed", f"entry {n} was not removed")
    path = item["path"]
    if os.path.lexists(path):
        raise ReconcileError("path_exists", f"{path} exists")
    entry = item["entry"]
    head, branch = entry.get("head"), entry.get("branch")
    archived_admin = Path(item["admin"])
    tree = Path(item["directory"]) if item.get("directory") else None
    _git(root, "worktree", "add", "--no-checkout", "--detach", path, item["archive_ref"] + "^1")
    admin = Path(_git_out(path, "rev-parse", "--absolute-git-dir").strip())
    try:
        for name in ("index", "ORIG_HEAD", "AUTO_MERGE"):
            if (archived_admin / name).is_file():
                shutil.copy2(archived_admin / name, admin / name)
        for name in ("logs", "refs"):
            if (archived_admin / name).is_dir():
                shutil.copytree(archived_admin / name, admin / name, symlinks=True,
                                dirs_exist_ok=True)
    except (OSError, shutil.Error) as error:
        raise ReconcileError("tool_error", f"cannot restore the admin files: {error}") from None
    detail = "restored"
    if branch is None:
        detail = "restored detached: the worktree had no branch"
    else:
        resolved = _git(root, "rev-parse", "--verify", "-q", branch, read=True, check=False)
        if _text(resolved.stdout).strip() != head:
            detail = f"restored detached: {branch} no longer names {head}"
        elif _checked_out_elsewhere(root, branch):
            detail = f"restored detached: {branch} is checked out in another worktree"
        else:
            _git(path, "symbolic-ref", "HEAD", branch)
    if tree is not None:
        try:
            shutil.copytree(tree, path, symlinks=True, dirs_exist_ok=True,
                            ignore=lambda src, names: [".git"] if src == str(tree) else [])
        except (OSError, shutil.Error) as error:
            raise ReconcileError("tool_error", f"cannot restore the working files: {error}") from None
    return {"path": path, "head": head, "branch": branch, "detail": detail}


# --- real probes -------------------------------------------------------------------------------

def migrate_dry_run(root: Path) -> dict:
    """The dry-run report of `workflow-state migrate --repo-root root`."""
    done = _run(["workflow-state", "migrate", "--repo-root", str(root)], timeout=PROBE_TIMEOUT)
    if done.returncode != 0:
        raise ReconcileError("tool_error", f"workflow-state exit {done.returncode}: "
                                           f"{_text(done.stderr).strip()}")
    try:
        report = json.loads(_text(done.stdout))
    except ValueError:
        raise ReconcileError("tool_error", f"workflow-state printed non-JSON for {root}") from None
    if not isinstance(report, dict):
        raise ReconcileError("tool_error", f"workflow-state report for {root} is not an object")
    return report


def lsof_cwds() -> set[str]:
    """Every process's current directory; an lsof that fails without output is a tool error."""
    done = _run(["lsof", "-a", "-d", "cwd", "-Fn"], timeout=PROBE_TIMEOUT)
    out = _text(done.stdout)
    if done.returncode != 0 and not out.strip():
        raise ReconcileError("tool_error", f"lsof exit {done.returncode}: {_text(done.stderr).strip()}")
    return {line[1:] for line in out.splitlines() if line.startswith("n") and len(line) > 1}


def gh_open_prs(root: Path) -> dict[str, dict]:
    """Open pull requests of the root's GitHub repository, by head branch name."""
    remote = _git(root, "remote", "get-url", "origin", read=True, check=False)
    slug = github_slug(_text(remote.stdout)) if remote.returncode == 0 else None
    if slug is None:
        return {}
    done = _run(["gh", "pr", "list", "--repo", slug, "--state", "open", "--json",
                 "number,headRefName,updatedAt", "--limit", "500"], timeout=PROBE_TIMEOUT)
    if done.returncode != 0:
        raise ReconcileError("tool_error", f"gh pr list exit {done.returncode}: "
                                           f"{_text(done.stderr).strip()}")
    try:
        rows = json.loads(_text(done.stdout))
        return {row["headRefName"]: {"number": row["number"], "updated_at": row["updatedAt"]}
                for row in rows}
    except (ValueError, KeyError, TypeError):
        raise ReconcileError("tool_error", "gh pr list printed an unusable listing") from None


# --- audit -------------------------------------------------------------------------------------

_RECORD_FIELDS = {"schema": str, "state": str, "run_id": str, "root": str, "n": int, "path": str,
                  "entry": dict, "archive_ref": str, "pin": str, "tree": str, "parents": list,
                  "admin_files": dict, "bundle": str, "bundle_sha256": str, "bundle_heads": list}
_GONE_STATES = ("renamed", "removed")


def load_run_dir(run_dir: Path) -> tuple[dict[str, list[dict]], dict[str, list[dict]]]:
    """Plans and apply results found directly in `run_dir`, each grouped by its `root` string."""
    base = Path(run_dir)
    if not base.is_dir():
        raise ReconcileError("bad_run_dir", f"{run_dir} is not a directory")
    plans: dict[str, list[dict]] = {}
    applies: dict[str, list[dict]] = {}
    for file in sorted(base.glob("*.json")):
        if not file.is_file():
            continue
        try:
            text = file.read_text(encoding="utf-8", errors="replace")
        except OSError as error:
            raise ReconcileError("bad_run_dir", f"cannot read {file}: {error}") from None
        try:
            doc = json.loads(text)
        except ValueError:
            if PLAN_SCHEMA in text:
                raise ReconcileError("bad_run_dir", f"{file} does not parse") from None
            continue
        schema = doc.get("schema") if isinstance(doc, dict) else None
        if schema == PLAN_SCHEMA:
            if (not isinstance(doc.get("root"), str) or not isinstance(doc.get("run_id"), str)
                    or not isinstance(doc.get("entries"), list)
                    or not all(isinstance(e, dict) and isinstance(e.get("path"), str)
                               for e in doc["entries"])):
                raise ReconcileError("bad_run_dir", f"{file} is a malformed plan")
            if any(p["run_id"] == doc["run_id"] for p in plans.get(doc["root"], [])):
                raise ReconcileError("bad_run_dir",
                                     f"two plans of {doc['root']} have run id {doc['run_id']}")
            plans.setdefault(doc["root"], []).append(doc)
        elif schema == APPLY_SCHEMA:
            if (isinstance(doc.get("root"), str) and isinstance(doc.get("run_id"), str)
                    and isinstance(doc.get("results"), list)):
                applies.setdefault(doc["root"], []).append(doc)
    return plans, applies


def _record_valid(dir: Path, record: object) -> bool:
    if not isinstance(record, dict) or record.get("schema") != ARCHIVE_SCHEMA:
        return False
    for key, kind in _RECORD_FIELDS.items():
        value = record.get(key)
        if not isinstance(value, kind) or (kind is int and isinstance(value, bool)):
            return False
    pins = record["entry"].get("pins")
    if not isinstance(pins, dict) or not isinstance(pins.get("commits"), list):
        return False
    if record.get("directory") is not None and not isinstance(record["directory"], str):
        return False
    if "directory" not in record:
        return False
    parent = Path(dir).parent.parent.parent
    return Path(dir) == archive_dir(parent, record["run_id"], Path(record["root"]), record["n"],
                                    record["path"])


def verify_archive(root: Path, dir: Path, record: dict) -> str | None:
    """None when the record's archive is whole, else the first failing reason (P10)."""
    dir = Path(dir)
    if not _record_valid(dir, record):
        return "record_invalid"
    done = _git(root, "rev-parse", "--verify", "-q", record["archive_ref"] + "^{commit}", read=True,
                check=False)
    if done.returncode != 0:
        return "archive_ref_missing"
    pin = record["pin"]
    parents_done = _git(root, "rev-list", "--parents", "-n", "1", pin, read=True, check=False)
    tree_done = _git(root, "rev-parse", "--verify", "-q", pin + "^{tree}", read=True, check=False)
    fields = _text(parents_done.stdout).split()
    parents = fields[1:]
    if (_text(done.stdout).strip() != pin or tree_done.returncode != 0
            or _text(tree_done.stdout).strip() != record["tree"] or parents_done.returncode != 0
            or parents != record["parents"]):
        return "pin_mismatch"
    if not parents or parents[0] != record["entry"].get("head"):
        return "archive_head_mismatch"
    if any(sha not in parents for sha in record["entry"]["pins"]["commits"]):
        return "pins_unreachable"
    try:
        if admin_digests(dir / "admin") != record["admin_files"]:
            return "admin_mismatch"
    except OSError:
        return "admin_mismatch"
    bundle = dir / "history.bundle"
    try:
        whole = (bundle.is_file() and record["bundle"] == str(bundle)
                 and _sha256_file(bundle) == record["bundle_sha256"])
    except OSError:
        whole = False
    if not whole:
        return "bundle_damaged"
    heads = _git(root, "bundle", "list-heads", str(bundle), read=True, check=False)
    listed = [line.split(" ", 1) for line in _text(heads.stdout).splitlines() if line.strip()]
    if heads.returncode != 0 or listed != record["bundle_heads"]:
        return "bundle_heads_mismatch"
    if _git(root, "bundle", "verify", str(bundle), read=True, check=False).returncode != 0:
        return "bundle_unverified"
    directory = record.get("directory")
    if directory is not None and (directory != str(dir / "tree") or not os.path.isdir(directory)):
        return "directory_missing"
    return None


def _identity(path: str) -> frozenset[str]:
    return frozenset({path, os.path.realpath(path)})


def _same(a: str, b: str) -> bool:
    return bool(_identity(a) & _identity(b))


def _read_record(file: Path) -> dict | None:
    try:
        doc = json.loads(file.read_text(encoding="utf-8", errors="surrogateescape"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def _latest_outcome(applies: list[dict], path: str) -> str | None:
    best: tuple[str, str | None] | None = None
    for apply in applies:
        for result in apply["results"]:
            if (isinstance(result, dict) and isinstance(result.get("path"), str)
                    and _same(result["path"], path)):
                if best is None or apply["run_id"] > best[0]:
                    best = (apply["run_id"], result.get("outcome"))
    return best[1] if best else None


def audit_root(root: Path, migrate_report: dict, plans: list[dict], applies: list[dict], *,
               archive_root: Path) -> dict:
    """Every red path of `root` resolved or listed `unresolved`; read-only, judged on fresh state."""
    fresh = classify_root(root, migrate_report)
    listing = [wt.path for wt in list_worktrees(root)]
    red = [row["path"] for row in fresh["paths"] if row["class"] in ("unmapped", "refused-only")]
    plans = sorted(plans, key=lambda p: p["run_id"])
    latest = plans[-1] if plans else None
    out = {"root": str(root), "red": len(red), "excluded": list(fresh["excluded"]), "removed": [],
           "gone_elsewhere": [], "kept": {}, "new_since_plan": [], "unresolved": []}
    unresolved = out["unresolved"]
    settled: list[str] = []

    def row(path: str, why: str, outcome: str | None, action: str | None = "archive_remove") -> None:
        unresolved.append({"path": path, "why": why, "action": action, "outcome": outcome})
        settled.append(path)

    candidates: dict[str, list[tuple[dict, dict]]] = {}
    for plan in plans:
        for entry in plan["entries"]:
            if entry.get("action") == "archive_remove" and isinstance(entry.get("n"), int):
                candidates.setdefault(os.path.realpath(entry["path"]), []).append((plan, entry))
    for hits in candidates.values():
        path = hits[-1][1]["path"]
        records: list[tuple[str, Path, dict | None]] = []
        for plan, entry in hits:
            d = archive_dir(archive_root, plan["run_id"], root, entry["n"], entry["path"])
            if (d / "record.json").is_file():
                records.append((plan["run_id"], d, _read_record(d / "record.json")))
        gone = [r for r in records if r[2] is not None and r[2].get("state") in _GONE_STATES]
        present = any(_same(path, listed) for listed in listing)
        if present:
            if gone:
                row(path, "reappeared", "removed")
            continue
        applied = _latest_outcome(applies, path)
        if gone:
            run_id, d, record = gone[-1]
            reason = verify_archive(root, d, record)
            if reason is None:
                out["removed"].append({"path": path, "run_id": run_id, "n": record["n"],
                                       "state": record["state"]})
            else:
                row(path, reason, "removed")
        elif records:
            row(path, "record_invalid" if any(r[2] is None for r in records)
                else "removal_unconfirmed", applied)
        else:
            pinned = any(
                _git(root, "rev-parse", "--verify", "-q",
                     f"refs/archive/worktree-reconcile/{plan['run_id']}/{entry['n']}", read=True,
                     check=False).returncode == 0 for plan, entry in hits)
            if pinned or applied == "removed":
                row(path, "record_missing", applied)
            else:
                out["gone_elsewhere"].append({"path": path,
                                              "run_ids": sorted({p["run_id"] for p, _ in hits})})
    for path in red:
        if any(_same(path, s) for s in settled):
            continue
        entry = next((e for e in latest["entries"] if _same(e["path"], path)), None) if latest else None
        if latest is None:
            row(path, "no_plan", None, None)
        elif entry is None:
            out["new_since_plan"].append(path)
        elif entry.get("action") == "keep" and entry.get("keep"):
            out["kept"][path] = list(entry["keep"])
        elif entry.get("action") == "archive_remove":
            row(path, "planned_archive_remove", _latest_outcome(applies, path), "archive_remove")
        else:
            row(path, "planned_none_now_red", _latest_outcome(applies, path), entry.get("action"))
    unresolved.sort(key=lambda u: (u["path"], u["why"]))
    out["new_since_plan"].sort()
    out["removed"].sort(key=lambda r: (r["path"], r["run_id"]))
    out["gone_elsewhere"].sort(key=lambda g: g["path"])
    return out


# --- command ----------------------------------------------------------------------------------

def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="worktree-reconcile", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("plan", help="write a read-only plan")
    plan.add_argument("--repo-root", required=True, type=Path)
    plan.add_argument("--fleet-root", required=True, action="append", type=Path)
    plan.add_argument("--archive-root", required=True, type=Path)
    plan.add_argument("--refused-pending", action="store_true")
    plan.add_argument("--keep", action="append", default=[])
    plan.add_argument("--out", required=True, type=Path)
    apply = sub.add_parser("apply", help="archive then remove each still-valid candidate")
    apply.add_argument("--plan", required=True, type=Path)
    apply.add_argument("--archive-root", required=True, type=Path)
    apply.add_argument("--acknowledge-cleanup", action="store_true")
    restore = sub.add_parser("restore", help="put a removed worktree back")
    restore.add_argument("--manifest", required=True, type=Path)
    restore.add_argument("--n", required=True, type=int)
    audit = sub.add_parser("audit", help="check that every red path is resolved (read-only)")
    audit.add_argument("--run-dir", required=True, type=Path)
    audit.add_argument("--archive-root", required=True, type=Path)
    audit.add_argument("--repo-root", required=True, action="append", type=Path)
    return parser


def _command_plan(args: argparse.Namespace) -> int:
    plan = build_plan(args.repo_root, migrate_dry_run(args.repo_root), fleet_roots=args.fleet_root,
                      archive_root=args.archive_root, live_cwds=lsof_cwds, open_prs=gh_open_prs,
                      now=datetime.now(timezone.utc),
                      refused_pending=args.refused_pending, operator_keep=frozenset(args.keep))
    try:
        _write_atomic(args.out.parent, args.out.name, _dump(plan))
    except OSError as error:
        raise ReconcileError("tool_error", f"cannot write {args.out}: {error}") from None
    actions = [e["action"] for e in plan["entries"]]
    print(json.dumps({"entries": len(actions), "archive_remove": actions.count("archive_remove"),
                      "keep": actions.count("keep"), "none": actions.count("none"),
                      "excluded": len(plan["excluded"])}))
    return 0


def _command_apply(args: argparse.Namespace) -> int:
    if not args.acknowledge_cleanup:
        raise ReconcileError("not_acknowledged", "apply needs --acknowledge-cleanup")
    try:
        plan = json.loads(args.plan.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ReconcileError("bad_plan", f"cannot read plan {args.plan}: {error}") from None
    root = Path(plan["root"]) if isinstance(plan, dict) and isinstance(plan.get("root"), str) else None
    result = apply_plan(plan, migrate_dry_run=lambda: migrate_dry_run(root), live_cwds=lsof_cwds,
                        open_prs=gh_open_prs, archive_root=args.archive_root,
                        acknowledge_cleanup=True)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 1 if any(r["outcome"] == "failed" for r in result["results"]) else 0


def _command_audit(args: argparse.Namespace) -> int:
    plans, applies = load_run_dir(args.run_dir)
    if shutil.which("workflow-state") is None:
        raise ReconcileError("tool_error", "workflow-state not found")
    roots = []
    for root in args.repo_root:
        own = os.path.realpath(root)
        pick = lambda found: [doc for key, docs in found.items()
                              if os.path.realpath(key) == own for doc in docs]
        roots.append(audit_root(root, migrate_dry_run(root), pick(plans), pick(applies),
                                archive_root=args.archive_root))
    unmet = any(r["unresolved"] for r in roots)
    print(json.dumps({"met": not unmet, "roots": roots}, indent=2, ensure_ascii=False))
    return 1 if unmet else 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "plan":
            return _command_plan(args)
        if args.command == "apply":
            return _command_apply(args)
        if args.command == "audit":
            return _command_audit(args)
        print(json.dumps(restore_entry(args.manifest, args.n)))
        return 0
    except ReconcileError as error:
        print(f"worktree-reconcile: {error.code}: {error.detail}", file=sys.stderr)
    except MappingError as error:
        print(f"worktree-reconcile: tool_error: {error}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
