"""The console's activation reading (#1114): which console files this host runs behind origin's integration branch.

The console runs from a build of the `python/` tree (`SOURCE_DIR`). This module compares the files
that build holds with the files on the remote-tracking integration branch of a registered checkout,
so the page can say, in one line, that a `just switch` would change what the console runs. It writes
nothing: no ref, no file, no log row.

Console-built files. Every regular file under `<package_root>/agent_tools/console/` except
`__pycache__` directories and `.pyc` files, plus every `agent_tools` module those `.py` files
import, transitively, plus the `__init__.py` of every package on each imported dotted path. A module
outside that closure is never a key. Keys are `SOURCE_DIR + "/" + <path relative to package_root>`
with `/` separators; values are git blob ids (`blob_id`).

`changed_paths(running, origin)` names a path when it is a key of `running` and
`origin.get(path) != running[path]`, or when it is an `origin` key under `python/agent_tools/console/`
(not under `__pycache__`, not `.pyc`) that `running` does not hold. The result is sorted, without
duplicates.

`reading(roots, running)` reads only `refs/remotes/origin/<branch>` of each checkout, where
`<branch>` is the integration branch of the checkout's project contract, never the local branch or
the working tree. It returns `Activation(root, changed)` for the first root in sorted order whose
branch is a string and whose origin tree holds `ENTRY` (the file that marks a checkout as the
console's source), even when an earlier root's read failed.

A failed read is never a successful "no line". A root with no project contract, no remote-tracking
ref, or an origin tree without `ENTRY` is not a candidate. A root whose read failed (git exited
non-zero, could not run or timed out; the resolver failed; a malformed record) raises `ReadFailed`
when no root qualifies, naming the failed roots; `reading` returns None only when every root was read
and none is a candidate.

`reader_for(package_root)` computes `console_files(package_root)` once, when called (the running
build is immutable), and reuses it for every later call.
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


class ReadFailed(Exception):
    """A read that could not be made; never the same as a read that found nothing."""


@dataclass(frozen=True)
class Activation:
    root: str
    changed: tuple[str, ...]


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


def origin_files(root: str, branch: str) -> dict[str, str] | None:
    """Repository path -> blob id of every blob under `python/agent_tools` on `refs/remotes/origin/<branch>`.

    None only when that remote-tracking ref does not exist; `ReadFailed` when git fails.
    """
    ref = f"refs/remotes/origin/{branch}"
    listing = _git(root, "for-each-ref", "--format=%(objectname) %(refname)", ref)
    commit = None
    for line in listing.decode("utf-8", "replace").splitlines():
        object_id, _, name = line.partition(" ")
        if name == ref:
            commit = object_id
    if commit is None:
        return None
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


def reading(
    roots: Iterable[str],
    running: Mapping[str, str],
    *,
    branch_of: Callable[[str], str | None] = integration_branch,
    tree: Callable[[str, str], Mapping[str, str] | None] = origin_files,
) -> Activation | None:
    """The activation reading of the first root whose origin carries the console; see the module docstring."""
    failures: list[str] = []
    for root in sorted(roots):
        try:
            branch = branch_of(root)
            origin = None if branch is None else tree(root, branch)
        except ReadFailed as error:
            failures.append(str(error))
            continue
        if origin is not None and ENTRY in origin:
            return Activation(root, changed_paths(running, origin))
    if failures:
        raise ReadFailed("; ".join(failures))
    return None


def reader_for(package_root: Path) -> Callable[[Iterable[str]], Activation | None]:
    """A reader over the checkouts, comparing against the files of the running build taken now."""
    running = console_files(package_root)
    return lambda roots: reading(roots, running, branch_of=integration_branch)
