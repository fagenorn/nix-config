"""Record a full verification pass against the git tree it verified.

`verified-tree check --verification <id> [--verification <id> ...]` computes the
current tree and exits 0 printing one line of canonical JSON,
{"status": "verified" | "unverified", "tree": "<tree id>"}. It answers
`verified` only when a record exists, its `tree` equals the current tree and
its `verification` list equals the given ids in order.

`verified-tree record --tree <id> --verification <id> [...]` recomputes the
tree. When it equals `--tree` it atomically replaces the record and exits 0
printing {"recorded": true, "tree": "<id>"}; otherwise it writes nothing,
leaves any previous record byte-identical and exits 3 printing
{"reason": "tree_changed", "recorded": false, "tree": "<current tree>"}.

The tree is the git tree of the working tree as verification saw it: tracked
files with uncommitted edits plus untracked files that are not ignored, built
by `git add -A` and `git write-tree` against a temporary copy of the index, so
on a clean worktree it equals `HEAD^{tree}`. Neither verb changes the real
index, HEAD or any working-tree file.

The record is one latest-pass file per worktree,
`<git rev-parse --absolute-git-dir>/verified-tree.json`, holding exactly
{"schema": "verified-tree/v1", "tree": "<id>", "verification": ["<id>", ...]}:
`tree` is 40 or 64 lowercase hex characters and `verification` is a non-empty
list of non-empty strings. It carries no run, attempt or launch identity.

An empty `--verification` id, a git failure, or a record that exists but fails
strict parsing or that closed schema, prints one `verified-tree: <message>` line
on stderr and exits 2 with empty stdout, writing nothing; argparse's usage
errors also exit 2.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

from agent_tools.canonical import reject_duplicate_keys, reject_nonfinite_literal

SCHEMA = "verified-tree/v1"
RECORD_NAME = "verified-tree.json"
RECORD_KEYS = frozenset({"schema", "tree", "verification"})
TREE_PATTERN = r"[0-9a-f]{40}(?:[0-9a-f]{24})?"
ERROR_EXIT = 2
REFUSED_EXIT = 3


class VerifiedTreeError(Exception):
    """A git failure or an unreadable or malformed record; main prints one stderr line and exits 2."""


def _canonical(document: Mapping[str, object]) -> str:
    return json.dumps(document, sort_keys=True, separators=(",", ":"))


def _git(args: Sequence[str], root: Path | None,
         env: Mapping[str, str] | None = None) -> str:
    """Run `git <args>` in `root`; its stripped stdout, or VerifiedTreeError naming the subcommand."""
    try:
        completed = subprocess.run(["git", *args], cwd=root, env=env,
                                   capture_output=True, text=True, check=False)
    except OSError as error:
        raise VerifiedTreeError(f"git {args[0]}: {error}") from error
    if completed.returncode != 0:
        lines = completed.stderr.strip().splitlines()
        detail = lines[-1] if lines else f"exit {completed.returncode}"
        raise VerifiedTreeError(f"git {args[0]}: {detail}")
    return completed.stdout.strip()


def worktree_root() -> Path:
    """The top level of the worktree containing the current directory."""
    return Path(_git(["rev-parse", "--show-toplevel"], None))


def record_path(root: Path) -> Path:
    """The record file in the worktree's own git directory."""
    return Path(_git(["rev-parse", "--absolute-git-dir"], root)) / RECORD_NAME


def current_tree(root: Path) -> str:
    """The tree of tracked edits plus untracked non-ignored files, built in a temporary index."""
    index = root / _git(["rev-parse", "--git-path", "index"], root)
    with tempfile.TemporaryDirectory() as scratch:
        temporary = Path(scratch) / "index"
        if index.is_file():
            shutil.copy2(index, temporary)
        env = {**os.environ, "GIT_INDEX_FILE": str(temporary)}
        _git(["add", "-A"], root, env=env)
        return _git(["write-tree"], root, env=env)


def read_record(path: Path) -> dict | None:
    """The validated record, or None only when the file does not exist."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError) as error:
        raise VerifiedTreeError(f"cannot read {path}: {error}") from error
    try:
        document = json.loads(text, object_pairs_hook=reject_duplicate_keys,
                              parse_constant=reject_nonfinite_literal)
    except ValueError as error:
        raise VerifiedTreeError(f"malformed record {path}: {error}") from error
    if not isinstance(document, dict) or set(document) != RECORD_KEYS:
        raise VerifiedTreeError(f"malformed record {path}: keys must be {sorted(RECORD_KEYS)}")
    if document["schema"] != SCHEMA:
        raise VerifiedTreeError(f"malformed record {path}: schema must be {SCHEMA}")
    tree = document["tree"]
    if not isinstance(tree, str) or not re.fullmatch(TREE_PATTERN, tree):
        raise VerifiedTreeError(f"malformed record {path}: tree is not a tree id")
    verification = document["verification"]
    if (not isinstance(verification, list) or not verification
            or not all(isinstance(item, str) and item for item in verification)):
        raise VerifiedTreeError(
            f"malformed record {path}: verification must be a non-empty list of ids")
    return document


def _require_ids(verification: list[str]) -> None:
    """Refuse an empty verification id, which the record's closed schema forbids."""
    if not verification or not all(verification):
        raise VerifiedTreeError("every --verification id must be non-empty")


def check(verification: list[str]) -> dict:
    """{"status", "tree"}: verified only for the recorded tree under the same ids in order."""
    _require_ids(verification)
    root = worktree_root()
    tree = current_tree(root)
    stored = read_record(record_path(root))
    verified = (stored is not None and stored["tree"] == tree
                and stored["verification"] == verification)
    return {"status": "verified" if verified else "unverified", "tree": tree}


def record(tree: str, verification: list[str]) -> tuple[int, dict]:
    """Replace the record when the current tree equals `tree`; (3, refusal) otherwise."""
    _require_ids(verification)
    root = worktree_root()
    current = current_tree(root)
    if current != tree:
        return REFUSED_EXIT, {"recorded": False, "reason": "tree_changed", "tree": current}
    path = record_path(root)
    body = _canonical({"schema": SCHEMA, "tree": tree, "verification": verification}) + "\n"
    try:
        descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".verified-tree-")
    except OSError as error:
        raise VerifiedTreeError(f"cannot write {path}: {error}") from error
    replaced = False
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        replaced = True
    except OSError as error:
        raise VerifiedTreeError(f"cannot write {path}: {error}") from error
    finally:
        if not replaced:
            try:
                os.unlink(temporary)
            except OSError:
                pass
    return 0, {"recorded": True, "tree": tree}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="verified-tree", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    verbs = parser.add_subparsers(dest="verb", required=True)
    check_verb = verbs.add_parser("check", help="is the current tree verified?")
    record_verb = verbs.add_parser("record", help="record a pass against a tree")
    record_verb.add_argument("--tree", required=True, help="the tree the pass verified")
    for verb in (check_verb, record_verb):
        verb.add_argument("--verification", action="append", required=True,
                          help="a declared verification id, in order")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.verb == "check":
            status, result = 0, check(args.verification)
        else:
            status, result = record(args.tree, args.verification)
    except VerifiedTreeError as error:
        print(f"verified-tree: {error}", file=sys.stderr)
        return ERROR_EXIT
    print(_canonical(result))
    return status


if __name__ == "__main__":
    raise SystemExit(main())
