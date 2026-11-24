"""Record a verification pass against the git tree it verified (#263).

`verified-tree check` resolves the worktree's project, computes the current
tree and the verification plan, and exits 0 printing one line of canonical
JSON, {"run": ["<id>", ...], "skipped": [{"id": "<id>", "reason": "<text>"},
...], "status": "verified" | "unverified", "tree": "<tree id>"}. It answers
`verified` only when a record exists, its `tree` equals the current tree and
its `verification` list equals `run`, element for element, which is how a planned run's final gate
lets the ship stage skip a rerun.

The plan reads `bindings.workflow.verification`,
`bindings.workflow.verification_conditions` and `bindings.vcs.integration_branch`
from `resolve_project.resolve(<worktree top level>, ["verification"])`. `run`
holds the declared ids, in declared order, that have no condition (an entry
holding only `pre_commit` is none) or whose `when_changed` globs match a changed path under
`resolve_project.any_path_matches`; `skipped` holds the rest, in declared order,
each with its authored `skip_reason`. The changed paths are the names
`git diff-tree -r --no-renames` prints between
`git merge-base HEAD refs/remotes/origin/<integration_branch>` and the current
tree, so a rename counts as both of its paths and a deletion counts. They are
computed only when some declared id has a condition, so a contract without
conditions needs no `origin` ref and runs every id.

`bindings.workflow.verification_conditions` (issue 437) is an optional `resolve-project` member;
absent or `null` means no id is conditional. It maps a `workflow.verification` id to
`{"when_changed": [<glob>, ...], "skip_reason": "<text>"}`, with those two members, which come
together; an entry may also carry an optional boolean `pre_commit` (issue 771) marking the id a
fast pre-commit check that deliver-standard names to every implementer, and an entry holding only
`pre_commit` leaves its id unconditional. `when_changed` is a non-empty list of globs under the
contract glob rules: repository-relative, canonically spelled, and matched with
`fnmatch.fnmatchcase`, so `*` crosses `/`. `skip_reason` is a non-empty string, reported
verbatim. At least one declared id must stay unconditional (the resolver validates all of this).

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
and takes no lock; a planned run's final review and conformance reviewer run it instead of
judging a measured surface by hand (issue 477).

`verified-tree run --worktree-path <path>` runs `workflow.verification_before_pull_request`
when the contract sets it, else every declared `workflow.verification` id, once each, in
that worktree, and prints one line of canonical JSON, {"clean": <bool>, "head": "<full
sha>", "results": [<result>, ...], "tree": "<tree id>", "verdict": "passed" | "failed" |
"dirty"}, exiting 0. The root is `git -C <path> rev-parse --show-toplevel`; the snapshot is
`resolve_project.resolve(<root>, ["verification"])`, so each command's argv and cwd are the
worktree's own contract (its cwd is absolute, rooted at the worktree). `results` holds exactly
one entry per run id, in declared order: `{"id", "status": "pass" | "fail" | "skipped",
"summary"}`, plus `"exit": <int>` when the command ran, `"reason": <skip_reason>` when skipped
(only an id the plan above skipped, with its `skip_reason`), and `"no_slot": true` only on a
`fail` where no slot came free, and, on every id that ran a command, `"waited_seconds"` and
`"held_seconds"` (each a number or null, from `verify-slot`'s report, the wait summed over the
attempts and the hold that of the last) and `"selection"` (the JSON object the command wrote to
the file `VERIFIED_TREE_SELECTION` names, left out when it wrote none or not an object). A tree
that is not clean before (`git status --porcelain` prints anything) runs nothing: verdict
`dirty`, `results` empty. Each run id runs as
`verify-slot run --wait-limit SLOT_WAIT_SECONDS --report <file> -- <argv>` in its cwd, stdin
closed and output captured: stdout carries only the one line, and each command's captured output goes to stderr
after it ends. Exit 75 retries, `SLOT_ATTEMPTS` runs in all, then `fail` with `no_slot` and
summary `no verify slot came free in <SLOT_ATTEMPTS> attempts`; a run past
`COMMAND_TIMEOUT_SECONDS` is terminated and is `fail` with summary `timed out after <N> s`
(`verify-slot` runs in its own session: the timeout sends SIGTERM to that whole process group,
then SIGKILL to it after `TERMINATE_GRACE_SECONDS`, so a command that ignores SIGTERM or leaves
descendants cannot outlive it; output is captured in a file, never a pipe, so a descendant
that outlives the command and keeps its stdout open delays nothing);
any other exit is the command's own (0 `pass`, else `fail` whose summary is the last
`SUMMARY_LINES` non-blank output lines). Every id runs even after an earlier one failed. The
verdict is `failed` when any result is `fail`, else `dirty` when the tree is not clean after
the runs, else `passed`; `clean` reports the after state and `tree` the tree that was run.
A `passed` run writes the record below for the tree it ran, its `verification` the ids whose
status is `pass` (a run that passed no id writes none, the record's list being non-empty), so
`check` then answers `verified` for that tree; a `failed` or `dirty` run, a usage error and an
error verdict write nothing and leave an earlier record as it was.
A usage error, a path that is not a git worktree, a resolver refusal or a missing
`origin/<integration_branch>` when some id is conditional prints `{"detail": "<text>",
"verdict": "error"}` and exits 1.

A `run` that passes, while `workflow.verification_before_pull_request` is set, atomically
replaces `<git rev-parse --absolute-git-dir>/verified-tree-run.json` with exactly
{"head": "<full sha>", "schema": "verified-tree-run/v1", "verification": ["<id>", ...]}, the HEAD
it ran at and the ids it ran; a failed or dirty run writes nothing and leaves an earlier record in
place, and a record that cannot be written prints `verified-tree: cannot record the pass:
<error>` on stderr while the verdict stands. After the dirty check and the plan, a `run` skips
every command, starting no `verify-slot`, when all of these hold for the record's head H0: the
record parses strictly (those keys, that schema, a tree-id `head`, a non-empty list of non-empty
strings); its `verification` equals the plan's `run`; H0 is an ancestor of HEAD; `git rev-list
--no-merges H0..HEAD ^refs/remotes/origin/<integration_branch>` prints nothing, so only merges
and commits already on the integration branch came since; and no path that differs between H0's
tree and the current tree is among the changed paths above. A skip prints {"clean": true, "head",
"results", "synced_since": "<H0>", "tree", "verdict": "passed"}, `synced_since` a string, each
result of the plan's `run` `skipped` with the summary and reason `passed at <H0>; the sync since
changed none of the pull request's files` and a condition-skipped id keeping its own reason. It
applies only while the binding is set, and an unreadable record or a git failure in that check
verifies instead of erroring; a run at H0 itself with nothing changed also skips.
A skip also records the current tree as verified, as a passing run does, with the plan's `run` ids.

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
carries no run, attempt or launch identity. `verified-tree-run.json`, written by `run` only,
sits beside it.

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
import math
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile

from agent_tools.project_contract import resolve_project
from agent_tools.canonical import reject_duplicate_keys, reject_nonfinite_literal
from agent_tools.system.siblings import sibling_argv

SCHEMA = "verified-tree/v1"
RECORD_NAME = "verified-tree.json"
PLAN_SCHEMA = "verified-tree-plan/v1"
PLAN_NAME = "verified-tree-plan.json"
PLAN_LOCK_NAME = "verified-tree-plan.lock"
RUN_RECORD_SCHEMA = "verified-tree-run/v1"
RUN_RECORD_NAME = "verified-tree-run.json"
SYNC_SKIP_REASON = "passed at {head}; the sync since changed none of the pull request's files"
TREE_PATTERN = r"[0-9a-f]{40}(?:[0-9a-f]{24})?"
ERROR_EXIT = 2
NOT_STARTED_EXIT = 127
REFUSED_EXIT = 3
SLOT_WAIT_SECONDS = 600
SLOT_ATTEMPTS = 12
COMMAND_TIMEOUT_SECONDS = 3600
SUMMARY_LINES = 20
NO_SLOT_EXIT = 75
SELECTION_ENV = "VERIFIED_TREE_SELECTION"  # the selector's name for it, which this package may not import
TERMINATE_GRACE_SECONDS = 30


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


def run_record_path(root: Path) -> Path:
    """The last passed `run`'s record, beside the record."""
    return record_path(root).with_name(RUN_RECORD_NAME)


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


def _resolved(root: Path) -> dict:
    """The `["verification"]` snapshot of `root`'s project contract."""
    try:
        return resolve_project.resolve(str(root), ["verification"])
    except resolve_project.ContractError as error:
        raise VerifiedTreeError(
            f"resolve-project refused: {error.code} {error.repair_id}") from error


def _policy(snapshot: Mapping) -> dict:
    """The declared ids, their conditions (`{}` when none) and the integration branch."""
    bindings = snapshot["bindings"]
    workflow = bindings["workflow"]
    return {"verification": workflow["verification"],
            "before_pull_request": workflow.get("verification_before_pull_request"),
            "conditions": workflow.get("verification_conditions") or {},
            "integration_branch": bindings["vcs"]["integration_branch"]}


def _run_ids(policy: Mapping) -> list[str]:
    """The ids `run` runs: the pre-pull-request list when the contract sets one, else all."""
    before = policy["before_pull_request"]
    return list(before) if isinstance(before, list) else list(policy["verification"])


def verification_policy(root: Path) -> dict:
    """The declared ids, their conditions (`{}` when none) and the integration branch."""
    return _policy(_resolved(root))


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
        if (condition is None or not resolve_project.is_conditional(condition)
                or resolve_project.any_path_matches(list(changed), condition["when_changed"])):
            run.append(verification_id)
        else:
            skipped.append({"id": verification_id, "reason": condition["skip_reason"]})
    return {"run": run, "skipped": skipped}


def _plan_of(root: Path, tree: str, policy: Mapping) -> dict:
    """The plan for `tree` under `policy`; the change is read only when some id is conditional."""
    conditions = policy["conditions"]
    conditional = any(
        verification_id in conditions
        and resolve_project.is_conditional(conditions[verification_id])
        for verification_id in policy["verification"])
    changed = (changed_paths(root, policy["integration_branch"], tree) if conditional else [])
    return plan(policy["verification"], conditions, changed)


def current_plan(root: Path, tree: str) -> dict:
    """The plan for `tree`; the change is read only when some declared id is conditional."""
    return _plan_of(root, tree, verification_policy(root))


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


def _clean(root: Path) -> bool:
    """True when `git status --porcelain` prints nothing."""
    return not _git(["status", "--porcelain"], root)


def _output_summary(output: str) -> str:
    """The last `SUMMARY_LINES` non-blank lines of `output`."""
    lines = [line for line in output.splitlines() if line.strip()]
    return "\n".join(lines[-SUMMARY_LINES:])


def _signal_group(child: subprocess.Popen, number: int) -> None:
    """Send `number` to the whole process group `child` leads (it was started in its own session)."""
    try:
        os.killpg(child.pid, number)
    except ProcessLookupError:
        pass


def _number(value: object) -> bool:
    """A finite non-negative number, not a bool."""
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and value >= 0)


def _read_json_object(path: Path) -> dict | None:
    """The JSON object in `path`, or None for a missing or empty file, bad JSON or a non-object."""
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _read_report(path: Path) -> dict | None:
    """`verify-slot`'s report when readable: a wait and a hold that is a number or null."""
    report = _read_json_object(path)
    if (report is None or not _number(report.get("waited_seconds"))
            or not (report.get("held_seconds") is None or _number(report.get("held_seconds")))):
        return None
    return report


def _slot_seconds(reports: Sequence[Mapping | None]) -> tuple[float | None, float | None]:
    """(summed wait, last hold) over the attempts' readable reports; None when none was readable."""
    readable = [report for report in reports if report is not None]
    if not readable:
        return None, None
    return round(sum(report["waited_seconds"] for report in readable), 1), readable[-1]["held_seconds"]


def _slotted(argv: Sequence[str], cwd: str, report: Path, selection: Path) -> tuple[int | None, str]:
    """One `verify-slot run` of `argv` in `cwd`: (exit code, output), or (None, output) on timeout.
    verify-slot leads its own session so a timeout reaches the command and its descendants, which
    verify-slot's SIGKILL cannot forward. Output goes to a file, never a pipe, so a descendant
    that outlives the command and holds its stdout cannot delay the exit code or hang a read.
    """
    command = [*sibling_argv("delivery.verify_slot"), "run", "--wait-limit",
               str(SLOT_WAIT_SECONDS), "--report", str(report), "--", *argv]
    with tempfile.TemporaryFile() as captured:
        try:
            child = subprocess.Popen(command, cwd=cwd, stdin=subprocess.DEVNULL,
                                     stdout=captured, stderr=subprocess.STDOUT,
                                     env={**os.environ, SELECTION_ENV: str(selection)},
                                     start_new_session=True)
        except OSError as error:
            return NOT_STARTED_EXIT, f"cannot start {argv[0]}: {error}"
        code: int | None
        try:
            code = child.wait(timeout=COMMAND_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            _signal_group(child, signal.SIGTERM)  # verify-slot also forwards it and gives the slot back
            try:
                child.wait(timeout=TERMINATE_GRACE_SECONDS)
            except subprocess.TimeoutExpired:
                pass
            _signal_group(child, signal.SIGKILL)  # whatever still holds the group, verify-slot included
            child.wait()
            code = None
        captured.seek(0)
        return code, os.fsdecode(captured.read())


def _run_command(verification_id: str, command: Mapping) -> dict:
    """The result of one declared id, retried while no verify slot comes free."""
    code: int | None = None
    reports: list[dict | None] = []
    selection: dict | None = None
    for _ in range(SLOT_ATTEMPTS):
        with tempfile.TemporaryDirectory() as scratch:
            report_path, selection_path = Path(scratch) / "report.json", Path(scratch) / "selection.json"
            code, output = _slotted(command["argv"], command["cwd"], report_path, selection_path)
            reports.append(_read_report(report_path))
            selection = _read_json_object(selection_path)
        if output:
            sys.stderr.write(f"verified-tree: output of {verification_id}\n{output}")
            if not output.endswith("\n"):
                sys.stderr.write("\n")
        if code != NO_SLOT_EXIT:
            break
    waited, held = _slot_seconds(reports)
    if code is None:
        result = {"id": verification_id, "status": "fail",
                  "summary": f"timed out after {COMMAND_TIMEOUT_SECONDS} s"}
    elif code == NO_SLOT_EXIT:
        result = {"id": verification_id, "status": "fail", "exit": code, "no_slot": True,
                  "summary": f"no verify slot came free in {SLOT_ATTEMPTS} attempts"}
    else:
        status = "pass" if code == 0 else "fail"
        summary = "passed" if code == 0 else _output_summary(output) or f"exit {code}"
        result = {"id": verification_id, "status": status, "exit": code, "summary": summary}
    result["waited_seconds"], result["held_seconds"] = waited, held
    if selection is not None:
        result["selection"] = selection
    return result


def _read_run_record(path: Path) -> dict | None:
    """The strictly parsed run record, or None when it is absent or malformed; never raises."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"),
                              object_pairs_hook=reject_duplicate_keys,
                              parse_constant=reject_nonfinite_literal)
    except (OSError, ValueError):
        return None
    if not isinstance(document, dict) or set(document) != {"head", "schema", "verification"}:
        return None
    head, ids = document["head"], document["verification"]
    if (document["schema"] != RUN_RECORD_SCHEMA or not isinstance(head, str)
            or not re.fullmatch(TREE_PATTERN, head) or not isinstance(ids, list) or not ids
            or not all(isinstance(item, str) and item for item in ids)):
        return None
    return document


def _synced_since(root: Path, tree: str, planned: Mapping, policy: Mapping) -> str | None:
    """The head a pass was recorded at when only a clean sync has changed the branch since, else None.

    Any git failure or unreadable record answers None: the run verifies instead."""
    try:
        recorded = _read_run_record(run_record_path(root))
        if recorded is None or recorded["verification"] != planned["run"]:
            return None
        origin = f"refs/remotes/origin/{policy['integration_branch']}"
        earlier = recorded["head"]
        if subprocess.run(["git", "merge-base", "--is-ancestor", earlier, "HEAD"], cwd=root,
                          capture_output=True, check=False).returncode != 0:
            return None
        if _git(["rev-list", "--no-merges", f"{earlier}..HEAD", f"^{origin}"], root):
            return None
        if not set(_tree_diff(root, earlier, tree)).isdisjoint(
                changed_paths(root, policy["integration_branch"], tree)):
            return None
    except (VerifiedTreeError, OSError):
        return None
    return earlier


def _record_pass(root: Path, head: str, run_ids: Sequence[str]) -> None:
    """Record that `run_ids` passed at `head`; a failure is reported on stderr, never raised."""
    try:
        _write_atomically(run_record_path(root), {"head": head, "schema": RUN_RECORD_SCHEMA,
                                                  "verification": list(run_ids)})
    except VerifiedTreeError as error:
        print(f"verified-tree: cannot record the pass: {error}", file=sys.stderr)


def run(worktree: Path) -> tuple[int, dict]:
    """Run every declared id once in `worktree`: (0, verdict document) or (1, error document)."""
    try:
        root = Path(_git(["rev-parse", "--show-toplevel"], worktree))
        snapshot = _resolved(root)
        policy = _policy(snapshot)
        tree = current_tree(root)
        head = _git(["rev-parse", "HEAD"], root)
        if not _clean(root):
            return 0, {"clean": False, "head": head, "results": [], "tree": tree,
                       "verdict": "dirty"}
        ids = _run_ids(policy)
        planned = _plan_of(root, tree, {**policy, "verification": ids})
        reasons = {entry["id"]: entry["reason"] for entry in planned["skipped"]}
        bound = isinstance(policy["before_pull_request"], list)
        earlier = _synced_since(root, tree, planned, policy) if bound else None
        if earlier is not None:
            if planned["run"]:  # the synced tree is the verified one, so landing can ready it
                _write_atomically(record_path(root), {"schema": SCHEMA, "tree": tree,
                                                      "verification": list(planned["run"])})
            reasons.update({item: SYNC_SKIP_REASON.format(head=earlier) for item in planned["run"]})
            return 0, {"clean": True, "head": head, "synced_since": earlier, "tree": tree,
                       "verdict": "passed",
                       "results": [{"id": item, "status": "skipped",
                                    "summary": reasons[item], "reason": reasons[item]}
                                   for item in ids]}
        commands = snapshot["bindings"]["commands"]
        results = []
        for verification_id in ids:
            if verification_id in reasons:
                reason = reasons[verification_id]
                results.append({"id": verification_id, "status": "skipped",
                                "summary": reason, "reason": reason})
            else:
                results.append(_run_command(verification_id, commands[verification_id]))
        clean = _clean(root)
        verdict = ("failed" if any(entry["status"] == "fail" for entry in results)
                   else "passed" if clean else "dirty")
        passed = [entry["id"] for entry in results if entry["status"] == "pass"]
        if verdict == "passed" and passed:
            _write_atomically(record_path(root), {"schema": SCHEMA, "tree": tree,
                                                  "verification": passed})
    except (VerifiedTreeError, OSError) as error:
        return 1, {"detail": str(error), "verdict": "error"}
    if bound and verdict == "passed":
        _record_pass(root, head, planned["run"])
    return 0, {"clean": clean, "head": head, "results": results, "tree": tree,
               "verdict": verdict}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="verified-tree", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    verbs = parser.add_subparsers(dest="verb", required=True)
    verbs.add_parser("check", help="print the plan; is the current tree verified?")
    record_verb = verbs.add_parser("record", help="record a pass against a tree")
    record_verb.add_argument("--tree", required=True, help="the tree the pass verified")
    run_verb = verbs.add_parser("run", help="run every declared id once in a worktree")
    run_verb.add_argument("--worktree-path", required=True, help="the worktree to verify")
    fresh_verb = verbs.add_parser("fresh", help="has the tree changed since a commit?")
    fresh_verb.add_argument("--since", required=True, help="the commit the evidence measured")
    fresh_verb.add_argument("--record", required=True, help="the acceptance record's path")
    return parser


class _UsageError(Exception):
    """A usage error of `run`, which answers as an error verdict instead of exiting 2."""


class _RunParser(argparse.ArgumentParser):
    def error(self, message: str):
        raise _UsageError(message)


def _run_main(argv: Sequence[str]) -> int:
    parser = _RunParser(prog="verified-tree run")
    parser.add_argument("--worktree-path", required=True)
    try:
        args = parser.parse_args(argv)
    except _UsageError as error:
        status, result = 1, {"detail": f"usage: {error}", "verdict": "error"}
    else:
        status, result = run(Path(args.worktree_path))
    print(_canonical(result))
    return status


def main(argv: Sequence[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv[:1] == ["run"] and not {"-h", "--help"} & set(argv):
        return _run_main(argv[1:])
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
