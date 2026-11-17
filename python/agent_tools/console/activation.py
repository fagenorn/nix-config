"""The console's activation reading (#1114, #1258): what this host runs behind origin's integration branch.

The console runs from a build of the `python/` tree (`SOURCE_DIR`). This module compares the files
that build holds with the files on the remote-tracking integration branch of a registered checkout,
and the files the host's configuration is built from with that branch, so the page can say, in one
line, that a `just switch` would change what the host runs. It writes nothing: no ref, no file, no
log row.

Console-built files. Every regular file under `<package_root>/agent_tools/console/` except
`__pycache__` directories and `.pyc` files, plus every `agent_tools` module those `.py` files
import, transitively, plus the `__init__.py` of every package on each imported dotted path. A module
outside that closure is never a key. Keys are `SOURCE_DIR + "/" + <path relative to package_root>`
with `/` separators; values are git blob ids (`blob_id`).

`changed_paths(running, origin)` names a path when it is a key of `running` and
`origin.get(path) != running[path]`, or when it is an `origin` key under `python/agent_tools/console/`
(not under `__pycache__`, not `.pyc`) that `running` does not hold. The result is sorted, without
duplicates.

Host-built changes. `Activation.other` holds the paths a merged change touched that the host's
configuration is built from but that are not console files: the paths `git diff-tree` reports between
the host's configuration revision (the `base`, with a trailing `-dirty` removed) and the reading's
commit, kept when `host_built(path)` holds, minus every path of `running` and every path under
`python/agent_tools/console/` (console status is decided by blobs only). `host_built` is False
exactly for a path under a `NOT_BUILT_DIRS` directory (`docs/`, `tests/`, `.github/`, `.agents/`) or
equal to a `NOT_BUILT_FILES` file (the root documents and `justfile`, `.gitignore`, `.sops.yaml`, and
the Nix-module READMEs no `.nix` file reads); every other path is counted. The host's revision is
read on every reading, through the `revision` seam, so a later activation clears `other` by itself;
a revision that cannot be read, or a commit the checkout lacks, is a failed read. `Activation.pending`
is true when `changed` or `other` is not empty.

`Activation.commit` is the 40-hex object id of `refs/remotes/origin/<branch>` that the compared tree
was read from: the id is read once and the tree is listed at that id, never re-resolved from the ref
name. An activation builds that commit, not the checkout's own `HEAD` or working tree, so the
checkout needs no update first and the reading carries no "checkout behind" flag.

`reading(roots, running, revision=...)` reads only `refs/remotes/origin/<branch>` of each checkout, where
`<branch>` is the integration branch of the checkout's project contract, never the local branch or
the working tree. It returns `Activation(root, changed, commit, other)` for the first root in sorted order
whose branch is a string and whose origin tree holds `ENTRY` (the file that marks a checkout as the
console's source), even when an earlier root's read failed. Its `tree` seam is
`origin_tree(root, branch)`, giving `(commit, files)`; its `changes` seam is
`host_changes(root, base, commit)`. `revision()` is called once, only after a candidate root is
found, and a failure of `revision` or `changes` for that root propagates at once.

`origin_tip(root)` is the commit of `refs/remotes/origin/<integration_branch(root)>`: None when the
root has no contract or no such ref, `ReadFailed` when git or the resolver fails.

A failed read is never a successful "no line". A root with no project contract, no remote-tracking
ref, or an origin tree without `ENTRY` is not a candidate. A root whose read failed (git exited
non-zero, could not run or timed out; the resolver failed; a malformed record) raises `ReadFailed`
when no root qualifies, naming the failed roots; `reading` returns None only when every root was read
and none is a candidate.

`reader_for(package_root, revision=...)` computes `console_files(package_root)` once, when called
(the running build is immutable), and reuses it for every later call; `revision` is read on every call.
"""

from __future__ import annotations

import ast
import hashlib
import subprocess
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from agent_tools.project_contract import resolve_project

SOURCE_DIR = "python"
ENTRY = "python/agent_tools/console/console.py"
_PACKAGE = "agent_tools"
_CONSOLE_DIR = f"{SOURCE_DIR}/{_PACKAGE}/console/"
_GIT_SECONDS = 30
NOT_BUILT_DIRS = ("docs/", "tests/", ".github/", ".agents/")
NOT_BUILT_FILES = (
    "README.md", "CLAUDE.md", "AGENTS.md", "justfile", ".gitignore", ".sops.yaml",
    "home/common/claude-code/README.md", "home/common/agent-skills/README.md",
    "home/linux/claude-local/README.md", "hosts/darwin/eleven-m5/README.md",
)


class ReadFailed(Exception):
    """A read that could not be made; never the same as a read that found nothing."""


@dataclass(frozen=True)
class Activation:
    root: str
    changed: tuple[str, ...]
    commit: str
    other: tuple[str, ...] = ()

    @property
    def pending(self) -> bool:
        return bool(self.changed or self.other)


def host_built(path: str) -> bool:
    """False exactly for a path the host's configuration is not built from; see the module docstring."""
    return not (path.startswith(NOT_BUILT_DIRS) or path in NOT_BUILT_FILES)


def blob_id(data: bytes) -> str:
    """The id git gives a blob holding `data`."""
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def _kept(path: Path) -> bool:
    return "__pycache__" not in path.parts and path.suffix != ".pyc" and path.is_file()


def _imports(source_path: Path, package_root: Path) -> set[str]:
    """The dotted names the module at `source_path` imports; empty when it does not parse."""
    try:
        tree = ast.parse(source_path.read_bytes())
    except (SyntaxError, UnicodeDecodeError, ValueError):
        return set()
    package = source_path.relative_to(package_root).with_suffix("").parts[:-1]
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                base = node.module or ""
            else:
                kept = package[: max(len(package) - (node.level - 1), 0)]
                base = ".".join((*kept, *([node.module] if node.module else [])))
            if base:
                names.add(base)
                names.update(f"{base}.{alias.name}" for alias in node.names)
    return names


def console_files(package_root: Path) -> dict[str, str]:
    """Repository path -> blob id of each console-built file found under `package_root`."""
    package_root = Path(package_root)
    found: dict[Path, None] = {}
    queue: list[Path] = []

    def add(path: Path) -> None:
        if path not in found and _kept(path):
            found[path] = None
            if path.suffix == ".py":
                queue.append(path)

    console = package_root / _PACKAGE / "console"
    if console.is_dir():
        for path in sorted(console.rglob("*")):
            add(path)
    while queue:
        source = queue.pop()
        for dotted in _imports(source, package_root):
            segments = dotted.split(".")
            if segments[0] != _PACKAGE:
                continue
            for end in range(1, len(segments) + 1):
                prefix = package_root.joinpath(*segments[:end])
                add(prefix / "__init__.py")
                add(prefix.with_suffix(".py"))
    return {
        f"{SOURCE_DIR}/{path.relative_to(package_root).as_posix()}": blob_id(path.read_bytes())
        for path in sorted(found)
    }


def _git(root: str, *arguments: str) -> bytes:
    try:
        done = subprocess.run(
            ["git", "-C", root, *arguments], stdin=subprocess.DEVNULL, capture_output=True,
            timeout=_GIT_SECONDS, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ReadFailed(f"{root}: git {arguments[0]} could not run ({type(error).__name__})") from None
    if done.returncode != 0:
        raise ReadFailed(f"{root}: git {arguments[0]} exited {done.returncode}")
    return done.stdout


def _tree_files(root: str, commit: str) -> dict[str, str]:
    """Repository path -> blob id of every blob under `python/agent_tools` at `commit`."""
    tree = _git(root, "ls-tree", "-r", "-z", "--full-tree", commit, "--", f"{SOURCE_DIR}/{_PACKAGE}")
    files: dict[str, str] = {}
    for record in tree.split(b"\0"):
        if not record:
            continue
        head, tab, path = record.partition(b"\t")
        fields = head.split(b" ")
        if not tab or len(fields) != 3:
            raise ReadFailed(f"{root}: git ls-tree gave a malformed record")
        if fields[1] == b"blob":
            files[path.decode("utf-8", "replace")] = fields[2].decode("ascii", "replace")
    return files


def _origin_commit(root: str, branch: str) -> str | None:
    """The object id of `refs/remotes/origin/<branch>`; None only when that ref does not exist."""
    ref = f"refs/remotes/origin/{branch}"
    listing = _git(root, "for-each-ref", "--format=%(objectname) %(refname)", ref)
    commit = None
    for line in listing.decode("utf-8", "replace").splitlines():
        object_id, _, name = line.partition(" ")
        if name == ref:
            commit = object_id
    return commit


def origin_tree(root: str, branch: str) -> tuple[str, dict[str, str]] | None:
    """`(commit, files)` of `refs/remotes/origin/<branch>`: its commit id and the blobs under `python/agent_tools`.

    None only when that remote-tracking ref does not exist; `ReadFailed` when git fails.
    """
    commit = _origin_commit(root, branch)
    if commit is None:
        return None
    return commit, _tree_files(root, commit)


def origin_files(root: str, branch: str) -> dict[str, str] | None:
    """Repository path -> blob id of every blob under `python/agent_tools` on `refs/remotes/origin/<branch>`.

    None only when that remote-tracking ref does not exist; `ReadFailed` when git fails.
    """
    read = origin_tree(root, branch)
    return None if read is None else read[1]


def changed_paths(running: Mapping[str, str], origin: Mapping[str, str]) -> tuple[str, ...]:
    """The console files `running` holds that differ on `origin`, and the console files only `origin` holds."""
    changed = {path for path, blob in running.items() if origin.get(path) != blob}
    for path in origin:
        if path in running or not path.startswith(_CONSOLE_DIR):
            continue
        parts = path.split("/")
        if "__pycache__" not in parts and not path.endswith(".pyc"):
            changed.add(path)
    return tuple(sorted(changed))


def host_changes(root: str, base: str, commit: str) -> tuple[str, ...]:
    """The host-built paths that differ between the commits `base` and `commit`, sorted."""
    out = _git(root, "diff-tree", "-r", "--name-only", "-z", "--no-renames", base, commit, "--")
    paths = {record.decode("utf-8", "surrogateescape") for record in out.split(b"\0") if record}
    return tuple(sorted(path for path in paths if host_built(path)))


def integration_branch(root: str) -> str | None:
    """The integration branch of the project contract at `root`; None only when the root holds no contract."""
    try:
        branch = resolve_project.resolve(root)["bindings"]["vcs"]["integration_branch"]
    except resolve_project.ContractError as error:
        if error.code == "not_onboarded":
            return None
        raise ReadFailed(f"{root}: the project contract did not resolve ({error.code})") from None
    except Exception as error:
        raise ReadFailed(f"{root}: the project contract did not resolve ({type(error).__name__})") from None
    if not isinstance(branch, str):
        raise ReadFailed(f"{root}: the project contract names no integration branch")
    return branch


def origin_tip(root: str) -> str | None:
    """The commit of the root's remote-tracking integration branch; None when it has no contract or no such ref."""
    branch = integration_branch(root)
    return None if branch is None else _origin_commit(root, branch)


def reading(
    roots: Iterable[str],
    running: Mapping[str, str],
    *,
    revision: Callable[[], str | None],
    branch_of: Callable[[str], str | None] = integration_branch,
    tree: Callable[[str, str], tuple[str, Mapping[str, str]] | None] = origin_tree,
    changes: Callable[[str, str, str], tuple[str, ...]] = host_changes,
) -> Activation | None:
    """The activation reading of the first root whose origin carries the console; see the module docstring."""
    failures: list[str] = []
    for root in sorted(roots):
        try:
            branch = branch_of(root)
            read = None if branch is None else tree(root, branch)
        except ReadFailed as error:
            failures.append(str(error))
            continue
        if read is not None and ENTRY in read[1]:
            commit, origin = read
            base = revision()
            if base is None:
                raise ReadFailed(f"{root}: the host's configuration revision could not be read")
            other = tuple(
                path for path in changes(root, base.removesuffix("-dirty"), commit)
                if path not in running and not path.startswith(_CONSOLE_DIR))
            return Activation(root, changed_paths(running, origin), commit, other)
    if failures:
        raise ReadFailed("; ".join(failures))
    return None


def reader_for(
    package_root: Path, *, revision: Callable[[], str | None]
) -> Callable[[Iterable[str]], Activation | None]:
    """A reader over the checkouts, comparing against the files of the running build taken now."""
    running = console_files(package_root)
    return lambda roots: reading(roots, running, revision=revision, branch_of=integration_branch)
