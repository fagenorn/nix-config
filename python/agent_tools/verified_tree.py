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

`check` also persists the plan it printed, atomically replacing
`<git rev-parse --absolute-git-dir>/verified-tree-plan.json` with exactly
{"run": ["<id>", ...], "schema": "verified-tree-plan/v1", "tree": "<tree id>"},
after every read has succeeded. When the file already holds a plan for the
same tree that no `record` has consumed, `run` becomes the ids, in the
earlier plan's order, that both plans run, so a later `check` can narrow a
pending plan but never widen it: whichever caller records, every recorded id
is one it was told to run. An empty intersection removes the file, and a file
`check` cannot parse is replaced.

`verified-tree record --tree <id>` recomputes the tree. When it differs from
`--tree` it writes nothing, leaves any previous record byte-identical and exits
3 printing {"reason": "tree_changed", "recorded": false, "tree": "<current
tree>"}; this comparison comes before resolving. Otherwise it resolves,
recomputes the plan and reads the persisted plan. It exits 2 when no persisted
plan exists for that tree (no `check` of it) or when the recomputed `run`
differs from the persisted one (the plan changed since `check`, as when
`origin/<integration_branch>` moved). A persisted plan for that tree is
consumed, removed once read, whether or not `record` then records, so each
`check` backs at most one `record`. Otherwise it atomically replaces the
record with `verification` set to the persisted `run` and exits 0 printing
{"recorded": true, "tree": "<id>"}. So only ids that `check` told the caller to
run are ever recorded, and a skip never reads as a pass. `check` and `record`
read and write the plan under an exclusive lock on `verified-tree-plan.lock`
beside it.

`verified-tree fresh --since <commit> --record <path>` answers whether evidence
measured at a commit still describes the current tree. `--since` must resolve
under `git rev-parse --verify --end-of-options <since>^{commit}`. `--record`,
resolved against the current directory with symlinks followed, must lie
strictly inside the worktree's top level; it need not exist. `fresh` lists the
paths that differ between that commit's tree and the current tree, in the same
`git diff-tree -r --no-renames` form as the changed paths above, drops the
record's repository-relative path, and exits 0 printing {"changed": ["<path>",
...], "since": "<commit sha>", "status": "fresh" | "stale", "tree": "<tree
id>"}, `fresh` exactly when `changed` is empty. It reads no project contract
and takes no lock.

The tree is what a Git-backed build sees: the index's entries, staged new
files included, with tracked files' working-tree edits and deletions applied,
built by `git add -u` and `git write-tree` against a temporary copy of the
index, so on a clean worktree it equals `HEAD^{tree}`. An untracked file is not
in it, as such a build excludes it; committing one changes the tree, so the
next `check` answers `unverified`. No verb changes the real index, HEAD or
any working-tree file.

The record is one latest-pass file per worktree,
`<git rev-parse --absolute-git-dir>/verified-tree.json`, holding exactly
{"schema": "verified-tree/v1", "tree": "<id>", "verification": ["<id>", ...]}:
`tree` is 40 or 64 lowercase hex characters and `verification` is a non-empty
list of non-empty strings, the ids that ran and passed on that tree. It
carries no run, attempt or launch identity.

The persisted plan is parsed as strictly as the record: `tree` is a tree id
and `run` is a non-empty list of non-empty strings.

A resolver refusal (its line is `verified-tree: resolve-project refused:
<code> <repair_id>`), a git failure (a missing `origin/<integration_branch>`
ref or merge base included, when some id is conditional), a record that exists
but fails strict parsing or that closed schema, a persisted plan that `record`
reads and that fails them, a missing check of the tree, or a plan changed
since `check`, prints one `verified-tree: <message>` line on stderr and exits
2 with empty stdout, writing no record (a plan changed since `check` is still
consumed). `fresh` exits 2 the same way for a `--since` that names no commit,
a `--record` outside the worktree or a git failure. argparse's usage errors
also exit 2: no verb takes a verification id.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
import fcntl
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
PLAN_SCHEMA = "verified-tree-plan/v1"
PLAN_NAME = "verified-tree-plan.json"
PLAN_LOCK_NAME = "verified-tree-plan.lock"
TREE_PATTERN = r"[0-9a-f]{40}(?:[0-9a-f]{24})?"
ERROR_EXIT = 2
REFUSED_EXIT = 3


class VerifiedTreeError(Exception):
    """A resolver refusal, a git failure, an unreadable or malformed record or persisted plan,
    a missing check of the tree or a plan changed since check; main prints one stderr
    line and exits 2."""


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


def plan_path(root: Path) -> Path:
    """The plan `check` last printed, beside the record."""
    return record_path(root).with_name(PLAN_NAME)


@contextmanager
def plan_lock(root: Path) -> Iterator[None]:
    """Hold the exclusive lock under which `check` and `record` read and write the plan."""
    path = record_path(root).with_name(PLAN_LOCK_NAME)
    try:
        descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
    except OSError as error:
        raise VerifiedTreeError(f"cannot open {path}: {error}") from error
    with os.fdopen(descriptor, "r+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        yield


def _remove(path: Path) -> None:
    """Remove `path` if it exists."""
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError as error:
        raise VerifiedTreeError(f"cannot remove {path}: {error}") from error


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


def _read_ids_file(path: Path, kind: str, schema: str, ids_key: str) -> dict | None:
    """The strictly parsed {"schema", "tree", <ids_key>} file, or None only when it does not exist."""
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
        raise VerifiedTreeError(f"malformed {kind} {path}: {error}") from error
    keys = {"schema", "tree", ids_key}
    if not isinstance(document, dict) or set(document) != keys:
        raise VerifiedTreeError(f"malformed {kind} {path}: keys must be {sorted(keys)}")
    if document["schema"] != schema:
        raise VerifiedTreeError(f"malformed {kind} {path}: schema must be {schema}")
    tree = document["tree"]
    if not isinstance(tree, str) or not re.fullmatch(TREE_PATTERN, tree):
        raise VerifiedTreeError(f"malformed {kind} {path}: tree is not a tree id")
    ids = document[ids_key]
    if (not isinstance(ids, list) or not ids
            or not all(isinstance(item, str) and item for item in ids)):
        raise VerifiedTreeError(
            f"malformed {kind} {path}: {ids_key} must be a non-empty list of ids")
    return document


def read_record(path: Path) -> dict | None:
    """The validated record, or None only when the file does not exist."""
    return _read_ids_file(path, "record", SCHEMA, "verification")


def read_plan(path: Path) -> dict | None:
    """The validated persisted plan, or None only when the file does not exist."""
    return _read_ids_file(path, "plan", PLAN_SCHEMA, "run")


def _write_atomically(path: Path, document: Mapping[str, object]) -> None:
    """Replace `path` with `document`'s canonical JSON line, or leave it untouched."""
    body = _canonical(document) + "\n"
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


def _tree_diff(root: Path, left: str, right: str) -> list[str]:
    """Every path whose entry differs between tree-ish `left` and `right`, in git's order.

    `--no-renames` lists both sides of a rename, and a deletion is listed."""
    names = _git_bytes(["diff-tree", "-r", "--no-renames", "--name-only", "-z", left, right], root)
    return [os.fsdecode(name) for name in names.split(b"\0") if name]


def changed_paths(root: Path, integration_branch: str, tree: str) -> list[str]:
    """Every path `tree` changes against its merge base with `origin/<integration_branch>`."""
    base = _git(["merge-base", "HEAD", f"refs/remotes/origin/{integration_branch}"], root)
    return _tree_diff(root, base, tree)


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
    """{"run", "skipped", "status", "tree"}: verified only for the recorded tree and `run` ids.

    Persists the printed plan's `tree` and `run` for `record`, narrowed to the ids a
    pending plan for the same tree also runs."""
    root = worktree_root()
    tree = current_tree(root)
    planned = current_plan(root, tree)
    stored = read_record(record_path(root))
    verified = (stored is not None and stored["tree"] == tree
                and stored["verification"] == planned["run"])
    with plan_lock(root):
        try:
            pending = read_plan(plan_path(root))
        except VerifiedTreeError:
            pending = None
        run = planned["run"]
        if pending is not None and pending["tree"] == tree:
            run = [item for item in pending["run"] if item in run]
        if run:
            _write_atomically(plan_path(root), {"run": run, "schema": PLAN_SCHEMA,
                                                "tree": tree})
        else:
            _remove(plan_path(root))
    return {**planned, "status": "verified" if verified else "unverified", "tree": tree}


def record(tree: str) -> tuple[int, dict]:
    """Record the `run` ids `check` printed for `tree`; (3, refusal) when the tree moved.

    The tree is compared before resolving. The plan recomputed now must equal
    the one `check` persisted for `tree`, so an id `check` skipped is never
    recorded. The persisted plan is consumed once read."""
    root = worktree_root()
    current = current_tree(root)
    if current != tree:
        return REFUSED_EXIT, {"recorded": False, "reason": "tree_changed", "tree": current}
    run = current_plan(root, tree)["run"]
    with plan_lock(root):
        checked = read_plan(plan_path(root))
        if checked is None or checked["tree"] != tree:
            raise VerifiedTreeError(f"no check of tree {tree} to record")
        _remove(plan_path(root))
        if checked["run"] != run:
            raise VerifiedTreeError(
                f"plan changed since check: run {checked['run']} is now {run}")
        _write_atomically(record_path(root), {"schema": SCHEMA, "tree": tree,
                                              "verification": checked["run"]})
    return 0, {"recorded": True, "tree": tree}


def _record_relative(root: Path, record: str) -> str:
    """`record`, resolved against the current directory, as a repository-relative POSIX path."""
    top = root.resolve()
    resolved = (Path.cwd() / record).resolve()
    try:
        relative = resolved.relative_to(top)
    except ValueError:
        relative = None
    if relative is None or not relative.parts:
        raise VerifiedTreeError(f"--record {record} is not a path inside the worktree {top}")
    return relative.as_posix()


def fresh(since: str, record: str) -> dict:
    """{"changed", "since", "status", "tree"}: fresh when only `record` differs from `since`."""
    root = worktree_root()
    try:
        commit = _git(["rev-parse", "--verify", "--end-of-options", f"{since}^{{commit}}"], root)
    except VerifiedTreeError as error:
        raise VerifiedTreeError(f"--since {since} names no commit") from error
    excluded = _record_relative(root, record)
    tree = current_tree(root)
    changed = [path for path in _tree_diff(root, commit, tree) if path != excluded]
    return {"changed": changed, "since": commit,
            "status": "stale" if changed else "fresh", "tree": tree}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="verified-tree", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    verbs = parser.add_subparsers(dest="verb", required=True)
    verbs.add_parser("check", help="print the plan; is the current tree verified?")
    record_verb = verbs.add_parser("record", help="record a pass against a tree")
    record_verb.add_argument("--tree", required=True, help="the tree the pass verified")
    fresh_verb = verbs.add_parser("fresh", help="has the tree changed since a commit?")
    fresh_verb.add_argument("--since", required=True, help="the commit the evidence measured")
    fresh_verb.add_argument("--record", required=True, help="the acceptance record's path")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.verb == "check":
            status, result = 0, check()
        elif args.verb == "fresh":
            status, result = 0, fresh(args.since, args.record)
        else:
            status, result = record(args.tree)
    except VerifiedTreeError as error:
        print(f"verified-tree: {error}", file=sys.stderr)
        return ERROR_EXIT
    print(_canonical(result))
    return status


if __name__ == "__main__":
    raise SystemExit(main())
