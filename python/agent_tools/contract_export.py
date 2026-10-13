"""The sparse export the guard-policy proof resolves on (issue 385).

`export_contract` writes the contract file and the regular-blob projection
files a resolution reads (`resolve_project.projection_paths`) of one commit
into a new directory. Every other path is left absent, and so is any symlink,
tree or submodule at a listed path, so the resolver refuses it as missing and
no link is ever created in the destination. It reads through git plumbing only
(one `ls-tree` and at most one `cat-file --batch` child per phase), each run
`local_only` so that a partial clone's promised blob refuses instead of being
fetched. It writes nothing to the repository, it refuses
`adopt.git.export_failed` on any git or OS failure, and it is imported, never
run.

A module of the `agent_tools` package, imported by the guard-policy proof.
"""

from __future__ import annotations

from pathlib import Path
import posixpath

from agent_tools import resolve_project
from agent_tools.adopt_inspection import AdoptError, refuse, run_git

REGULAR_MODES = ("100644", "100755")


def _export_failed() -> AdoptError:
    return refuse("adopt_failure", "adopt.git.export_failed", "",
                  "the remote commit could not be exported")


def export_contract(root: Path, commit: str, destination: Path) -> None:
    """Contract: see the module docstring; refuses `adopt.git.export_failed`.

    `destination` must not exist. The contract is written first and parsed, and
    only a contract that parses is followed by its projection files: a contract
    the resolver refuses is judged by the resolver on the contract alone (D10).
    """
    try:
        destination.mkdir()
    except OSError:
        raise _export_failed() from None
    contract_path = resolve_project.CONTRACT_FILENAME
    found = _regular_blobs(root, commit, [contract_path])
    if contract_path not in found:
        return
    _write(destination, [contract_path], _read_blobs(root, [found[contract_path]]))
    try:
        paths = resolve_project.projection_paths(
            resolve_project.load_contract(destination))
    except (resolve_project.ContractError, ValueError, RecursionError):
        return
    found = _regular_blobs(root, commit, paths)
    ordered = [path for path in paths if path in found]
    _write(destination, ordered, _read_blobs(root, [found[path] for path in ordered]))


def _write(destination: Path, paths: list[str], contents: list[bytes]) -> None:
    try:
        for path, content in zip(paths, contents, strict=True):
            target = destination / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
    except OSError:
        raise _export_failed() from None


def _regular_blobs(root: Path, commit: str, paths: list[str]) -> dict[str, str]:
    """Requested path -> blob id, for each requested path that is a regular blob at `commit`."""
    if not paths:
        return {}
    code, out = run_git(root, "--literal-pathspecs", "ls-tree", "-z", "--full-tree",
                        commit, "--", *paths, local_only=True)
    if code != 0:
        raise _export_failed()
    blobs: dict[str, str] = {}
    for record in out.split(b"\0"):
        if not record:
            continue
        fields, tab, name = record.partition(b"\t")
        parts = fields.split(b" ")
        if not tab or len(parts) != 3:
            raise _export_failed()
        mode, kind, oid = (part.decode("ascii", "replace") for part in parts)
        if mode in REGULAR_MODES and kind == "blob":
            blobs[name.decode("utf-8", "surrogateescape")] = oid
    return {path: blobs[posixpath.normpath(path)] for path in paths
            if posixpath.normpath(path) in blobs}


def _read_blobs(root: Path, object_ids: list[str]) -> list[bytes]:
    """The bytes of each blob, in order, from one `git cat-file --batch` child."""
    if not object_ids:
        return []
    code, out = run_git(root, "cat-file", "--batch", local_only=True,
                        input="".join(f"{oid}\n" for oid in object_ids).encode())
    if code != 0:
        raise _export_failed()
    contents: list[bytes] = []
    position = 0
    for oid in object_ids:
        end = out.find(b"\n", position)
        header = out[position:end].split(b" ") if end >= 0 else []
        if len(header) != 3 or header[0].decode("ascii", "replace") != oid \
                or header[1] != b"blob" or not header[2].isdigit():
            raise _export_failed()
        start, size = end + 1, int(header[2])
        if out[start + size:start + size + 1] != b"\n":
            raise _export_failed()
        contents.append(out[start:start + size])
        position = start + size + 1
    return contents
