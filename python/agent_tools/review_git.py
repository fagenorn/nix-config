"""Original Git object/parent authority; traversal is compared, never trusted."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import subprocess
from typing import Sequence


class HistoryError(Exception):
    """History cannot be authenticated independently of effective traversal."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class OriginalCommit:
    oid: str
    tree: str
    parents: tuple[str, ...]
    raw: bytes


def _git(repo: Path, *args: str) -> bytes:
    try:
        return subprocess.run(["git", "-C", str(repo), *args], check=True,
                              capture_output=True).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise HistoryError("original_history_unavailable") from exc


def _guard_stepwise(repo: Path) -> str:
    # Repository-routing overrides would also redirect disposable reconstruction
    # commands. Refuse them before any source or scratch operation can write.
    if any(key in os.environ for key in ("GIT_DIR", "GIT_COMMON_DIR", "GIT_WORK_TREE",
            "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES")):
        raise HistoryError("original_repository_routing_unavailable")
    locations = _git(repo, "rev-parse", "--path-format=absolute", "--git-dir", "--git-common-dir").decode().splitlines()
    paths = [Path(root) / name for root in locations for name in ("info/grafts", "shallow")]
    for key in ("GIT_GRAFT_FILE", "GIT_SHALLOW_FILE"):
        if key in os.environ:
            path = Path(os.environ[key])
            paths.append(path if path.is_absolute() else repo / path)
    try:
        for path in paths:
            if path.is_symlink() or (path.exists() and path.stat().st_size):
                raise HistoryError("original_history_virtualized")
        if _git(repo, "rev-parse", "--is-shallow-repository").strip() != b"false":
            raise HistoryError("original_history_virtualized")
    except OSError as exc:
        raise HistoryError("original_history_unavailable") from exc
    namespaces = {"refs/replace/", os.environ.get("GIT_REPLACE_REF_BASE", "refs/replace/")}
    if any(_git(repo, "for-each-ref", "--format=%(refname)", prefix) for prefix in namespaces):
        raise HistoryError("original_history_virtualized")
    # A missing promisor object must not trigger a fetch into the source store.
    settings = _git(repo, "config", "--null", "--list").lower().split(b"\0")
    if any(row.startswith(b"extensions.partialclone\n") or
           (row.split(b"\n", 1)[0].endswith(b".promisor") and row.rsplit(b"\n", 1)[-1] != b"false")
           for row in settings):
        raise HistoryError("original_history_unavailable")
    algorithm = _git(repo, "rev-parse", "--show-object-format").strip().decode("ascii")
    if algorithm not in {"sha1", "sha256"}:
        raise HistoryError("original_object_format_unavailable")
    return algorithm


def _guard(repo: Path) -> str:
    # Repository-routing overrides would also redirect disposable reconstruction
    # commands. Refuse them before any source or scratch operation can write.
    if any(key in os.environ for key in ("GIT_DIR", "GIT_COMMON_DIR", "GIT_WORK_TREE",
            "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES")):
        raise HistoryError("original_repository_routing_unavailable")
    # One rev-parse answers locations, shallowness and object format (#262 D2).
    # Any failure re-runs BASE's stepwise guard so failure codes keep their precedence.
    try:
        facts = _git(repo, "rev-parse", "--path-format=absolute", "--git-dir", "--git-common-dir",
                     "--is-shallow-repository", "--show-object-format").decode().splitlines()
    except HistoryError:
        return _guard_stepwise(repo)
    if len(facts) != 4:
        return _guard_stepwise(repo)
    *locations, shallow, algorithm = facts
    paths = [Path(root) / name for root in locations for name in ("info/grafts", "shallow")]
    for key in ("GIT_GRAFT_FILE", "GIT_SHALLOW_FILE"):
        if key in os.environ:
            path = Path(os.environ[key])
            paths.append(path if path.is_absolute() else repo / path)
    try:
        for path in paths:
            if path.is_symlink() or (path.exists() and path.stat().st_size):
                raise HistoryError("original_history_virtualized")
    except OSError as exc:
        raise HistoryError("original_history_unavailable") from exc
    if shallow.strip() != "false":
        raise HistoryError("original_history_virtualized")
    namespaces = sorted({"refs/replace/", os.environ.get("GIT_REPLACE_REF_BASE", "refs/replace/")})
    if _git(repo, "for-each-ref", "--format=%(refname)", *namespaces):
        raise HistoryError("original_history_virtualized")
    # A missing promisor object must not trigger a fetch into the source store.
    settings = _git(repo, "config", "--null", "--list").lower().split(b"\0")
    if any(row.startswith(b"extensions.partialclone\n") or
           (row.split(b"\n", 1)[0].endswith(b".promisor") and row.rsplit(b"\n", 1)[-1] != b"false")
           for row in settings):
        raise HistoryError("original_history_unavailable")
    algorithm = algorithm.strip()
    if algorithm not in {"sha1", "sha256"}:
        raise HistoryError("original_object_format_unavailable")
    return algorithm


def _identity(value: str, algorithm: str) -> None:
    length = 40 if algorithm == "sha1" else 64
    if not isinstance(value, str) or re.fullmatch("[0-9a-f]{" + str(length) + "}", value) is None:
        raise HistoryError("original_object_identity_mismatch")


def _reachable(commits: dict[str, OriginalCommit], tips: Sequence[str]) -> set[str]:
    seen: set[str] = set()
    pending = list(tips)
    while pending:
        oid = pending.pop()
        if oid not in seen:
            seen.add(oid)
            pending.extend(commits[oid].parents)
    return seen


def _traversal(repo: Path, commits: dict[str, OriginalCommit], tips: Sequence[str],
               excluded: Sequence[str] = (), *, topological: bool = False) -> tuple[str, ...]:
    expected = _reachable(commits, tips) - _reachable(commits, excluded)
    ordering = ["--topo-order"] if topological else []
    rows = _git(repo, "rev-list", "--parents", "--reverse", *ordering,
                *tips, "--not", *excluded).decode("ascii").splitlines()
    ordered = []
    for row in rows:
        fields = row.split()
        if (not fields or fields[0] not in expected or fields[0] in ordered
                or tuple(fields[1:]) != commits[fields[0]].parents):
            raise HistoryError("original_parent_mismatch")
        ordered.append(fields[0])
    if set(ordered) != expected:
        raise HistoryError("original_range_mismatch")
    if topological:
        positions = {oid: n for n, oid in enumerate(ordered)}
        if any(positions[parent] >= positions[oid] for oid in ordered
               for parent in commits[oid].parents if parent in positions):
            raise HistoryError("original_parent_mismatch")
    return tuple(ordered)


def _closure(repo: Path, tips: Sequence[str]) -> dict[str, OriginalCommit]:
    algorithm = _guard(repo)
    for oid in tips:
        _identity(oid, algorithm)
    commits: dict[str, OriginalCommit] = {}
    trees: set[str] = set()
    env = dict(os.environ, GIT_NO_REPLACE_OBJECTS="1", GIT_NO_LAZY_FETCH="1")
    try:
        with subprocess.Popen(["git", "--no-replace-objects", "-C", str(repo), "cat-file", "--batch"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env) as batch:
            def read(oid: str, kind: bytes) -> bytes:
                _identity(oid, algorithm)
                batch.stdin.write(oid.encode("ascii") + b"\n")
                batch.stdin.flush()
                header = batch.stdout.readline().split()
                if len(header) != 3 or header[:2] != [oid.encode("ascii"), kind] or not header[2].isdigit():
                    raise HistoryError("original_object_unavailable")
                raw = batch.stdout.read(int(header[2]))
                if len(raw) != int(header[2]) or batch.stdout.read(1) != b"\n":
                    raise HistoryError("original_object_unavailable")
                digest = hashlib.new(algorithm, kind + b" " + str(len(raw)).encode("ascii") + b"\0" + raw)
                if digest.hexdigest() != oid:
                    raise HistoryError("original_object_identity_mismatch")
                return raw
            try:
                pending = list(tips)
                while pending:
                    oid = pending.pop()
                    if oid in commits:
                        continue
                    raw = read(oid, b"commit")
                    header, separator, _ = raw.partition(b"\n\n")
                    lines = header.split(b"\n")
                    tree_rows = [line[5:] for line in lines if line.startswith(b"tree ")]
                    if not separator or len(tree_rows) != 1 or lines[0] != b"tree " + tree_rows[0]:
                        raise HistoryError("original_commit_header_mismatch")
                    tree = tree_rows[0].decode("ascii")
                    parents = tuple(line[7:].decode("ascii") for line in lines if line.startswith(b"parent "))
                    for parent in parents:
                        _identity(parent, algorithm)
                    if tree not in trees:
                        read(tree, b"tree")
                        trees.add(tree)
                    commits[oid] = OriginalCommit(oid, tree, parents, raw)
                    pending.extend(parents)
            finally:
                batch.stdin.close()
            if batch.wait() != 0:
                raise HistoryError("original_object_unavailable")
    except (OSError, UnicodeError, ValueError) as exc:
        raise HistoryError("original_history_unavailable") from exc
    # No retained cache: every API boundary observes current metadata and objects.
    _guard(repo)
    _traversal(repo, commits, tips)
    return commits


def original_commit(repo: Path, oid: str) -> OriginalCommit:
    return _closure(repo, (oid,))[oid]


def original_commits(repo: Path, oids: Sequence[str]) -> tuple[OriginalCommit, ...]:
    """Several authenticated commits, in the order asked, from one closure (#262 D3)."""
    oids = tuple(oids)
    if not oids:
        return ()
    commits = _closure(repo, oids)
    return tuple(commits[oid] for oid in oids)


def _original_walk(repo: Path, base: str, heads: Sequence[str], *, topological: bool) -> tuple[str, ...]:
    commits = _closure(repo, (base, *heads))
    return _traversal(repo, commits, heads, (base,), topological=topological) if heads else ()


def original_range(repo: Path, base: str, head: str, *, topological: bool = True) -> tuple[str, ...]:
    return _original_walk(repo, base, (head,), topological=topological)


def original_ancestor(repo: Path, base: str, head: str) -> bool:
    commits = _closure(repo, (base, head))
    expected = base in _reachable(commits, (head,))
    try:
        result = subprocess.run(["git", "-C", str(repo), "merge-base", "--is-ancestor", base, head],
                                capture_output=True)
    except OSError as exc:
        raise HistoryError("original_history_unavailable") from exc
    if result.returncode not in {0, 1} or (result.returncode == 0) != expected:
        raise HistoryError("original_ancestry_mismatch")
    return expected


def original_edge(repo: Path, parent: str, commit: str, ordinal: int) -> tuple[OriginalCommit, OriginalCommit]:
    commits = _closure(repo, (parent, commit))
    parents = commits[commit].parents
    if type(ordinal) is not int or not 1 <= ordinal <= len(parents) or parents[ordinal - 1] != parent:
        raise HistoryError("original_parent_mismatch")
    return commits[parent], commits[commit]
