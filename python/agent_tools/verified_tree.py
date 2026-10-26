"""Record a verification pass against the git tree it verified.

`verified-tree check` resolves the worktree's project, computes the current
tree and the verification plan, and exits 0 printing one line of canonical
JSON, {"run": ["<id>", ...], "skipped": [{"id": "<id>", "reason": "<text>"},
...], "status": "verified" | "unverified", "tree": "<tree id>"}. It answers
`verified` only when a record exists, its `tree` equals the current tree and
its `verification` list equals `run`, element for element.

The plan reads `bindings.workflow.verification`,
`bindings.workflow.verification_conditions` and `bindings.vcs.integration_branch`
from `resolve_project.resolve(<worktree top level>, ["verification"])`. `run`
holds the declared ids, in declared order, that have no condition or whose
`when_changed` globs match a changed path under
`resolve_project.any_path_matches`; `skipped` holds the rest, in declared order,
each with its authored `skip_reason`. The changed paths are the names
`git diff-tree -r --no-renames` prints between
`git merge-base HEAD refs/remotes/origin/<integration_branch>` and the current
tree, so a rename counts as both of its paths and a deletion counts. They are
computed only when some declared id has a condition, so a contract without
conditions needs no `origin` ref and runs every id.

`verified-tree record --tree <id>` recomputes the tree. When it differs from
`--tree` it writes nothing, leaves any previous record byte-identical and exits
3 printing {"reason": "tree_changed", "recorded": false, "tree": "<current
tree>"}. Otherwise it resolves, recomputes the plan, atomically replaces the
record with `verification` set to `run` and exits 0 printing
{"recorded": true, "tree": "<id>"}. A skipped id is never recorded, so a skip
never reads as a pass.

The tree is what a Git-backed build sees: the index's entries, staged new
files included, with tracked files' working-tree edits and deletions applied,
built by `git add -u` and `git write-tree` against a temporary copy of the
index, so on a clean worktree it equals `HEAD^{tree}`. An untracked file is not
in it, as such a build excludes it; committing one changes the tree, so the
next `check` answers `unverified`. Neither verb changes the real index, HEAD or
any working-tree file.

The record is one latest-pass file per worktree,
`<git rev-parse --absolute-git-dir>/verified-tree.json`, holding exactly
{"schema": "verified-tree/v1", "tree": "<id>", "verification": ["<id>", ...]}:
`tree` is 40 or 64 lowercase hex characters and `verification` is a non-empty
list of non-empty strings, the ids that ran and passed on that tree. It
carries no run, attempt or launch identity.

A resolver refusal (its line is `verified-tree: resolve-project refused:
<code> <repair_id>`), a git failure (a missing `origin/<integration_branch>`
ref or merge base included, when some id is conditional), or a record that
exists but fails strict parsing or that closed schema, prints one
`verified-tree: <message>` line on stderr and exits 2 with empty stdout,
writing nothing. argparse's usage errors also exit 2: neither verb takes a
verification id.
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

from agent_tools import resolve_project
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


def _git_bytes(args: Sequence[str], root: Path | None,
               env: Mapping[str, str] | None = None) -> bytes:
    """Run `git <args>` in `root`; its raw stdout, or VerifiedTreeError naming the subcommand."""
    try:
        completed = subprocess.run(["git", *args], cwd=root, env=env,
                                   capture_output=True, check=False)
    except OSError as error:
        raise VerifiedTreeError(f"git {args[0]}: {error}") from error
    if completed.returncode != 0:
        lines = os.fsdecode(completed.stderr).strip().splitlines()
        detail = lines[-1] if lines else f"exit {completed.returncode}"
        raise VerifiedTreeError(f"git {args[0]}: {detail}")
    return completed.stdout


def _git(args: Sequence[str], root: Path | None,
         env: Mapping[str, str] | None = None) -> str:
    """Run `git <args>` in `root`; its stripped stdout, or VerifiedTreeError naming the subcommand."""
    return os.fsdecode(_git_bytes(args, root, env)).strip()


def worktree_root() -> Path:
    """The top level of the worktree containing the current directory."""
    return Path(_git(["rev-parse", "--show-toplevel"], None))


def record_path(root: Path) -> Path:
    """The record file in the worktree's own git directory."""
    return Path(_git(["rev-parse", "--absolute-git-dir"], root)) / RECORD_NAME


def current_tree(root: Path) -> str:
    """The index's entries with tracked working-tree edits applied, built in a temporary index."""
    index = root / _git(["rev-parse", "--git-path", "index"], root)
    with tempfile.TemporaryDirectory() as scratch:
        temporary = Path(scratch) / "index"
        if index.is_file():
            shutil.copy2(index, temporary)
        env = {**os.environ, "GIT_INDEX_FILE": str(temporary)}
        _git(["add", "-u"], root, env=env)
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


def verification_policy(root: Path) -> dict:
    """The declared ids, their conditions (`{}` when none) and the integration branch."""
    try:
        snapshot = resolve_project.resolve(str(root), ["verification"])
    except resolve_project.ContractError as error:
        raise VerifiedTreeError(
            f"resolve-project refused: {error.code} {error.repair_id}") from error
    bindings = snapshot["bindings"]
    workflow = bindings["workflow"]
    return {"verification": workflow["verification"],
            "conditions": workflow.get("verification_conditions") or {},
            "integration_branch": bindings["vcs"]["integration_branch"]}


def changed_paths(root: Path, integration_branch: str, tree: str) -> list[str]:
    """Every path `tree` changes against its merge base with `origin/<integration_branch>`."""
    base = _git(["merge-base", "HEAD", f"refs/remotes/origin/{integration_branch}"], root)
    names = _git_bytes(["diff-tree", "-r", "--no-renames", "--name-only", "-z", base, tree], root)
    return [os.fsdecode(name) for name in names.split(b"\0") if name]


def plan(verification: Sequence[str], conditions: Mapping[str, Mapping],
         changed: Sequence[str]) -> dict:
    """{"run", "skipped"}: a conditional id runs only when a changed path matches its globs."""
    run: list[str] = []
    skipped: list[dict] = []
    for verification_id in verification:
        condition = conditions.get(verification_id)
        if condition is None or resolve_project.any_path_matches(
                list(changed), condition["when_changed"]):
            run.append(verification_id)
        else:
            skipped.append({"id": verification_id, "reason": condition["skip_reason"]})
    return {"run": run, "skipped": skipped}


def current_plan(root: Path, tree: str) -> dict:
    """The plan for `tree`; the change is read only when some declared id is conditional."""
    policy = verification_policy(root)
    conditions = policy["conditions"]
    conditional = any(verification_id in conditions for verification_id in policy["verification"])
    changed = (changed_paths(root, policy["integration_branch"], tree) if conditional else [])
    return plan(policy["verification"], conditions, changed)


def check() -> dict:
    """{"run", "skipped", "status", "tree"}: verified only for the recorded tree and `run` ids."""
    root = worktree_root()
    tree = current_tree(root)
    planned = current_plan(root, tree)
    stored = read_record(record_path(root))
    verified = (stored is not None and stored["tree"] == tree
                and stored["verification"] == planned["run"])
    return {**planned, "status": "verified" if verified else "unverified", "tree": tree}


def record(tree: str) -> tuple[int, dict]:
    """Record the plan's `run` ids when the current tree equals `tree`; (3, refusal) otherwise."""
    root = worktree_root()
    current = current_tree(root)
    if current != tree:
        return REFUSED_EXIT, {"recorded": False, "reason": "tree_changed", "tree": current}
    verification = current_plan(root, tree)["run"]
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
    verbs.add_parser("check", help="print the plan; is the current tree verified?")
    record_verb = verbs.add_parser("record", help="record a pass against a tree")
    record_verb.add_argument("--tree", required=True, help="the tree the pass verified")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.verb == "check":
            status, result = 0, check()
        else:
            status, result = record(args.tree)
    except VerifiedTreeError as error:
        print(f"verified-tree: {error}", file=sys.stderr)
        return ERROR_EXIT
    print(_canonical(result))
    return status


if __name__ == "__main__":
    raise SystemExit(main())
