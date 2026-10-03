"""Review package operations and exclusive, custody-checked publication."""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
from typing import Callable, Mapping, Sequence

from agent_tools.review_actual import (GenerationError, InvocationError, SHA_RE,
    _run_git, _full_commit, actual_inputs, select_candidate)
from agent_tools.review_budget import BudgetAuthority, BudgetError, BudgetCheck
from agent_tools.review_pack import (ReviewRecord, canonical_manifest as _canonical,
    pack_whole_records, measure_candidate)

RUN_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")

class PublicationError(GenerationError):
    """Exclusive publication failed without replacing an existing entry."""


def _display_path(root: Path, repository: Path) -> str:
    try:
        return root.relative_to(repository).as_posix()
    except ValueError:
        return str(root)


def _write_stage(
    final_root: Path,
    manifest: Mapping[str, object],
    shards: Sequence[bytes],
    suffix: str,
) -> tuple[Path, Path]:
    staging: Path | None = None
    try:
        staging = Path(tempfile.mkdtemp(
            prefix=f".{final_root.name}.stage-", dir=final_root.parent
        ))
        stage_root = staging / final_root.name
        member_dir = stage_root.with_suffix(".shards")
        member_dir.mkdir()
        for number, raw in enumerate(shards, 1):
            (member_dir / f"shard-{number:03d}.{suffix}").write_bytes(raw)
        stage_root.write_bytes(_canonical(manifest))
        return staging, stage_root
    except Exception as exc:
        if staging is not None:
            _cleanup_stage(staging)
        if isinstance(exc, OSError):
            raise GenerationError("cannot write staging package") from exc
        raise


def _identity(path: Path) -> tuple[int, int]:
    info = path.lstat()
    return info.st_dev, info.st_ino


def _descriptor_identity(descriptor: int) -> tuple[int, int]:
    info = os.fstat(descriptor)
    return info.st_dev, info.st_ino


def _directory_identity(path: Path) -> tuple[int, int]:
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode):
        raise PublicationError("published member directory is not a directory")
    return info.st_dev, info.st_ino


def _verify_published_identities(
    member_dir: Path,
    member_fd: int,
    directory_identity: tuple[int, int],
    linked: Sequence[tuple[str, tuple[int, int]]],
) -> None:
    try:
        if _directory_identity(member_dir) != directory_identity:
            raise PublicationError("published member directory identity changed")
        if _descriptor_identity(member_fd) != directory_identity:
            raise PublicationError("published member directory identity changed")
        for leaf, expected in linked:
            info = os.stat(leaf, dir_fd=member_fd, follow_symlinks=False)
            if (not stat.S_ISREG(info.st_mode)
                    or (info.st_dev, info.st_ino) != expected):
                raise PublicationError("published member identity changed")
    except OSError as exc:
        raise PublicationError("published package identity changed") from exc


def _cleanup_published_members(
    member_dir: Path,
    member_fd: int,
    directory_identity: tuple[int, int],
    linked: Sequence[tuple[str, tuple[int, int]]],
) -> list[Exception]:
    """Remove only links still owned through the retained member descriptor."""
    failures: list[Exception] = []
    for leaf, expected in reversed(linked):
        try:
            info = os.stat(leaf, dir_fd=member_fd, follow_symlinks=False)
            if (stat.S_ISREG(info.st_mode)
                    and (info.st_dev, info.st_ino) == expected):
                os.unlink(leaf, dir_fd=member_fd)
        except FileNotFoundError:
            continue
        except OSError as exc:
            failures.append(exc)
    try:
        empty = not os.listdir(member_fd)
    except OSError as exc:
        failures.append(exc)
        empty = False
    if not empty:
        return failures
    try:
        info = member_dir.lstat()
        if (stat.S_ISDIR(info.st_mode)
                and (info.st_dev, info.st_ino) == directory_identity):
            member_dir.rmdir()
    except FileNotFoundError:
        pass
    except OSError as exc:
        failures.append(exc)
    return failures


def _failure_note(failure: Exception) -> str:
    return f"{type(failure).__name__}: {failure}"


def publish_package(
    stage_root: Path,
    final_root: Path,
    before_mutation: Callable[[str, Path], None] | None = None,
    *,
    final_parent_fd: int | None = None,
    verify_final_parent: Callable[[], None] | None = None,
) -> None:
    """Publish with exclusive hard links and inode-matched cleanup (D16)."""
    previous_fd = -1
    member_fd = -1
    primary_failure: Exception | None = None
    release_failures: list[Exception] = []
    stage_members = stage_root.with_suffix(".shards")
    final_members = final_root.with_suffix(".shards")
    linked: list[tuple[str, tuple[int, int]]] = []
    directory_identity: tuple[int, int] | None = None
    try:
        if final_parent_fd is not None:
            previous_fd = _open_directory(Path.cwd())
            os.fchdir(final_parent_fd)
            final_root = Path(final_root.name)
            final_members = final_root.with_suffix(".shards")
        if before_mutation is not None:
            before_mutation("member_dir", final_members)
        if verify_final_parent is not None:
            verify_final_parent()
        final_members.mkdir()
        named_identity = _directory_identity(final_members)
        member_fd = _open_directory(final_members)
        descriptor_identity = _descriptor_identity(member_fd)
        if descriptor_identity != named_identity:
            raise PublicationError("published member directory identity changed")
        if _directory_identity(final_members) != descriptor_identity:
            raise PublicationError("published member directory identity changed")
        directory_identity = descriptor_identity
        for source in sorted(stage_members.iterdir()):
            if before_mutation is not None:
                before_mutation(f"member:{source.name}", final_members / source.name)
            if verify_final_parent is not None:
                verify_final_parent()
            _verify_published_identities(
                final_members, member_fd, directory_identity, linked
            )
            expected = _identity(source)
            os.link(
                source, source.name, dst_dir_fd=member_fd, follow_symlinks=False
            )
            linked.append((source.name, expected))
            _verify_published_identities(
                final_members, member_fd, directory_identity, linked
            )
        if before_mutation is not None:
            before_mutation("manifest", final_root)
        if verify_final_parent is not None:
            verify_final_parent()
        _verify_published_identities(
            final_members, member_fd, directory_identity, linked
        )
        os.link(stage_root, final_root, follow_symlinks=False)
    except (OSError, RuntimeError, PublicationError) as exc:
        primary_failure = exc
        if directory_identity is not None:
            release_failures.extend(_cleanup_published_members(
                final_members, member_fd, directory_identity, linked
            ))
    finally:
        if member_fd >= 0:
            try:
                os.close(member_fd)
            except OSError as exc:
                release_failures.append(exc)
        if previous_fd >= 0:
            try:
                os.fchdir(previous_fd)
            except OSError as exc:
                release_failures.append(exc)
            try:
                os.close(previous_fd)
            except OSError as exc:
                release_failures.append(exc)
    if primary_failure is not None:
        failure = PublicationError("exclusive package publication failed")
        for secondary in release_failures:
            failure.add_note(_failure_note(secondary))
        raise failure from primary_failure
    if release_failures:
        failure = PublicationError("exclusive package publication release failed")
        for secondary in release_failures[1:]:
            failure.add_note(_failure_note(secondary))
        raise failure from release_failures[0]


def _cleanup_stage(staging: Path) -> None:
    try:
        shutil.rmtree(staging)
    except OSError:
        pass


def _artifact_report(
    state: str,
    path: str,
    check: BudgetCheck,
) -> dict[str, object]:
    artifact: dict[str, object] = {
        "kind": "review-package",
        "path": path,
        "metrics": dict(check.metrics),
        "budget_status": check.status,
    }
    if check.status == "over_budget":
        artifact["violations"] = list(check.violations)
    return {"state": state, "artifact": artifact, "notes": "validated review package"}


def _real_directory(path: Path) -> None:
    try:
        info = path.lstat()
    except OSError as exc:
        raise InvocationError("invalid repository identity") from exc
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise InvocationError("invalid repository identity")


def _primary_checkout(repo: Path) -> Path:
    """The working tree that owns the common Git directory.

    Identity first, primary second — the same order `sdd-workspace` applies
    (issue 102, D19), and for the same reason. A checkout whose git dir *is*
    its common dir is the primary whatever that dir is named: a submodule
    working tree reports `<super>/.git/modules/<name>` and a
    `git init --separate-git-dir=` checkout reports the bare git-dir path.
    Demanding the `.git` name before deciding which checkout this is refuses
    both, and `delivery-detail` publication is the last step of a run — so the
    refusal would land only at completion, after the work it was meant to
    publish. The `.git` name and the `dirname` derivation stay on the
    linked-worktree branch, the one place they are the validation that the
    primary really is the common dir's parent.
    """
    raw_git = _run_git(repo, "rev-parse", "--path-format=absolute", "--git-dir")
    assert isinstance(raw_git, str)
    gitdir = Path(os.path.abspath(raw_git.strip()))
    raw = _run_git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir")
    assert isinstance(raw, str)
    common = Path(os.path.abspath(raw.strip()))
    if gitdir == common:
        shown = _run_git(repo, "rev-parse", "--show-toplevel")
        assert isinstance(shown, str)
        primary = Path(os.path.abspath(shown.strip()))
    else:
        if common.name != ".git":
            raise InvocationError("invalid common Git directory")
        _real_directory(common)
        primary = common.parent
        shown = _run_git(primary, "rev-parse", "--show-toplevel")
        assert isinstance(shown, str)
        if Path(os.path.abspath(shown.strip())) != primary:
            raise InvocationError("invalid primary checkout")
    _real_directory(primary)
    return primary


def _open_directory(path: Path) -> int:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    return os.open(path, flags)


class _DirectoryChain:
    """Retain and revalidate every no-follow directory used for publication."""

    def __init__(self, descriptors: list[int], names: list[str]):
        self._descriptors = descriptors
        self._names = names
        self._identities = [_descriptor_identity(fd) for fd in descriptors]

    @property
    def leaf(self) -> int:
        return self._descriptors[-1]

    def verify(self) -> None:
        try:
            for index, descriptor in enumerate(self._descriptors):
                if _descriptor_identity(descriptor) != self._identities[index]:
                    raise PublicationError("destination parent identity changed")
                if index:
                    info = os.stat(
                        self._names[index - 1],
                        dir_fd=self._descriptors[index - 1],
                        follow_symlinks=False,
                    )
                    if (not stat.S_ISDIR(info.st_mode)
                            or (info.st_dev, info.st_ino) != self._identities[index]):
                        raise PublicationError("destination parent identity changed")
        except OSError as exc:
            raise PublicationError("destination parent identity changed") from exc

    def close(self) -> None:
        for descriptor in reversed(self._descriptors):
            os.close(descriptor)
        self._descriptors.clear()


def _ensure_directories(
    base: Path, parts: Sequence[str], *, retain: bool = False
) -> _DirectoryChain | None:
    try:
        descriptor = _open_directory(base)
    except OSError as exc:
        raise InvocationError("unsafe destination parent") from exc
    descriptors = [descriptor]
    try:
        for part in parts:
            try:
                os.mkdir(part, 0o700, dir_fd=descriptor)
            except FileExistsError:
                pass
            try:
                child = os.open(
                    part,
                    os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
                    | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=descriptor,
                )
            except OSError as exc:
                raise InvocationError("unsafe destination parent") from exc
            descriptor = child
            descriptors.append(descriptor)
        chain = _DirectoryChain(descriptors, list(parts))
        chain.verify()
        if retain:
            return chain
        chain.close()
        return None
    except Exception:
        for opened in reversed(descriptors):
            os.close(opened)
        raise


def _ensure_ignore(primary: Path) -> None:
    delivery = primary / ".superpowers/issue-delivery"
    try:
        directory = _open_directory(delivery)
    except OSError as exc:
        raise InvocationError("unsafe delivery home") from exc
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    created = False
    created_identity: tuple[int, int] | None = None
    descriptor = -1
    try:
        try:
            descriptor = os.open(".gitignore", flags, 0o600, dir_fd=directory)
            created = True
            raw = b"*\n"
            written = 0
            while written < len(raw):
                written += os.write(descriptor, raw[written:])
            os.fsync(descriptor)
            info = os.fstat(descriptor)
            created_identity = (info.st_dev, info.st_ino)
            os.close(descriptor)
            descriptor = -1
            descriptor = os.open(
                ".gitignore",
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=directory,
            )
        except FileExistsError:
            descriptor = os.open(
                ".gitignore",
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=directory,
            )
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise InvocationError("unsafe delivery ignore")
        os.lseek(descriptor, 0, os.SEEK_SET)
        if os.read(descriptor, 3) != b"*\n":
            raise InvocationError("invalid delivery ignore")
    except (OSError, InvocationError) as exc:
        if created and created_identity is not None:
            try:
                current = os.stat(".gitignore", dir_fd=directory, follow_symlinks=False)
                if created_identity == (current.st_dev, current.st_ino):
                    os.unlink(".gitignore", dir_fd=directory)
            except OSError:
                pass
        if isinstance(exc, InvocationError):
            raise
        raise InvocationError("unsafe delivery ignore") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        os.close(directory)


def _assert_output(raw: str, expected: Path, primary: Path) -> None:
    supplied = Path(raw)
    if any(part == ".." for part in supplied.parts):
        raise InvocationError("invalid asserted output")
    absolute = Path(os.path.abspath(supplied))
    if ".git" in absolute.parts:
        raise InvocationError("invalid asserted output")
    try:
        relative = expected.relative_to(primary)
    except ValueError as exc:
        raise InvocationError("invalid asserted output") from exc
    count = len(relative.parts)
    if count == 0 or tuple(absolute.parts[-count:]) != relative.parts:
        raise InvocationError("invalid asserted output")
    primary_alias = Path(*absolute.parts[:-count])
    if Path(os.path.realpath(primary_alias)) != primary:
        raise InvocationError("invalid asserted output")
    try:
        alias_info = primary_alias.lstat()
        if (not stat.S_ISDIR(alias_info.st_mode)
                or stat.S_ISLNK(alias_info.st_mode)
                or _identity(primary_alias) != _identity(primary)):
            raise InvocationError("invalid asserted output")
    except OSError as exc:
        raise InvocationError("invalid asserted output") from exc
    current = primary_alias
    for part in relative.parts:
        current /= part
        try:
            info = current.lstat()
        except FileNotFoundError:
            break
        except OSError as exc:
            raise InvocationError("invalid asserted output") from exc
        if stat.S_ISLNK(info.st_mode):
            raise InvocationError("invalid asserted output")


def build_diff(args: argparse.Namespace, authority: BudgetAuthority) -> tuple[dict[str, object], int]:
    repo_raw = _run_git(Path.cwd(), "rev-parse", "--show-toplevel")
    assert isinstance(repo_raw, str)
    repo = Path(os.path.abspath(repo_raw.strip()))
    plan = Path(args.items[0])
    if not plan.is_absolute():
        plan = Path.cwd() / plan
    try:
        plan_check = authority.check("implementation-plan", plan)
        if plan_check.status != "within_budget":
            raise InvocationError("invalid plan package")
    except BudgetError as exc:
        raise InvocationError("invalid plan package") from exc
    base = _full_commit(repo, args.items[1], "base")
    head = _full_commit(repo, args.items[2], "head")
    if len(args.items) == 4:
        final_root = Path(args.items[3])
        if not final_root.is_absolute():
            final_root = Path.cwd() / final_root
        final_root = Path(os.path.abspath(final_root))
    else:
        try:
            output = subprocess.run(
                ["sdd-workspace", str(plan)],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        except (OSError, subprocess.CalledProcessError) as exc:
            raise GenerationError("cannot derive review workspace") from exc
        final_root = Path(output) / f"review-{base[:7]}..{head[:7]}.json"
    if final_root.suffix != ".json" or not final_root.parent.is_dir():
        raise InvocationError("invalid output path")
    candidate = select_candidate(
        actual_inputs(repo, base, head, final_root.name, authority.limits), authority.limits
    )
    return _publish_candidate(repo, final_root, candidate.manifest, candidate.shards,
                              "diff", authority=authority)


def build_detail(args: argparse.Namespace, authority: BudgetAuthority) -> tuple[dict[str, object], int]:
    repo_raw = _run_git(Path.cwd(), "rev-parse", "--show-toplevel")
    assert isinstance(repo_raw, str)
    repo = Path(os.path.abspath(repo_raw.strip()))
    primary = _primary_checkout(repo)
    if args.issue is None or not args.issue.isascii() or not args.issue.isdecimal():
        raise InvocationError("invalid issue")
    issue = int(args.issue)
    if issue < 1:
        raise InvocationError("invalid issue")
    if args.producer not in {"sdd", "ship-review"}:
        raise InvocationError("invalid producer")
    if args.head is None or SHA_RE.fullmatch(args.head) is None:
        raise InvocationError("invalid head")
    try:
        subprocess.run(
            ["git", "-C", str(repo), "cat-file", "-e", f"{args.head}^{{object}}"],
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise InvocationError("invalid head") from exc
    if args.branch is None:
        raise InvocationError("invalid branch")
    try:
        subprocess.run(
            ["git", "check-ref-format", "--branch", args.branch],
            check=True,
            capture_output=True,
        )
        current = _run_git(repo, "symbolic-ref", "--short", "HEAD")
    except (OSError, subprocess.CalledProcessError, GenerationError) as exc:
        raise InvocationError("invalid branch") from exc
    assert isinstance(current, str)
    if current.strip() != args.branch:
        raise InvocationError("invalid branch")
    if args.run_id == "-":
        identity = "branch-" + hashlib.sha256(args.branch.encode("utf-8")).hexdigest()
    elif args.run_id is not None and RUN_ID_RE.fullmatch(args.run_id):
        identity = args.run_id
    else:
        raise InvocationError("invalid run id")
    final_root = (
        primary / ".superpowers/issue-delivery" / str(issue) / identity
        / f"{args.producer}-{args.head}.json"
    )
    if args.output is not None:
        _assert_output(args.output, final_root, primary)
    source = Path(args.detail_input)
    if not source.is_absolute():
        source = Path.cwd() / source
    try:
        detail = authority.validate_detail(source)
    except BudgetError as exc:
        raise InvocationError("invalid detail input") from exc
    findings = detail["findings"]
    assert isinstance(findings, list)
    records = tuple(ReviewRecord(str(number), _canonical(finding), len(_canonical(finding)), None)
                    for number, finding in enumerate(findings))
    shard_bytes = pack_whole_records(records, authority.limits.member_max_bytes,
                                    strategy="sequential")
    shard_dir_name = final_root.with_suffix(".shards").name
    shards = [
        {"path": f"{shard_dir_name}/shard-{number:03d}.jsonl", "bytes": len(raw)}
        for number, raw in enumerate(shard_bytes, 1)
    ]
    manifest = {
        "interface_version": 1,
        "kind": "review-package",
        "purpose": "delivery-detail",
        "context": {"issue": issue, "branch": args.branch, "producer": args.producer},
        "shards": shards,
        "total_detail_bytes": sum(len(record.payload) for record in records),
        "coverage": {"complete": True, "finding_count": len(findings)},
    }
    _ensure_directories(primary, [".superpowers", "issue-delivery"])
    _ensure_ignore(primary)
    trusted_parent = _ensure_directories(
        primary, [".superpowers", "issue-delivery", str(issue), identity],
        retain=True,
    )
    assert trusted_parent is not None
    try:
        return _publish_candidate(
            primary, final_root, manifest, shard_bytes, "jsonl",
            trusted_parent=trusted_parent, authority=authority,
        )
    finally:
        trusted_parent.close()


def _publish_candidate(
    repository: Path,
    final_root: Path,
    manifest: Mapping[str, object],
    shards: Sequence[bytes],
    suffix: str,
    *,
    authority: BudgetAuthority,
    trusted_parent: _DirectoryChain | None = None,
    before_mutation: Callable[[str, Path], None] | None = None,
) -> tuple[dict[str, object], int]:
    staging: Path | None = None
    published_root = final_root
    previous_fd = -1
    try:
        if trusted_parent is not None:
            trusted_parent.verify()
            previous_fd = _open_directory(Path.cwd())
            os.fchdir(trusted_parent.leaf)
            final_root = Path(final_root.name)
        staging, stage_root = _write_stage(final_root, manifest, shards, suffix)
        check = authority.check("review-package", stage_root)
        expected = measure_candidate(manifest, shards, authority.limits)
        if (dict(check.metrics), check.status, check.violations) != expected:
            raise GenerationError("review package metric disagreement")
        publish_package(
            stage_root, final_root, before_mutation,
            verify_final_parent=(
                trusted_parent.verify if trusted_parent is not None else None
            ),
        )
    except BudgetError as exc:
        raise GenerationError("review package measurement failed") from exc
    finally:
        if staging is not None:
            _cleanup_stage(staging)
        if previous_fd >= 0:
            os.fchdir(previous_fd)
            os.close(previous_fd)
    state = "complete" if check.status == "within_budget" else "decompose_required"
    report = _artifact_report(state, _display_path(published_root, repository), check)
    return report, 0 if state == "complete" else 3
