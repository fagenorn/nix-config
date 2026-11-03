"""Read a verification blocker's repository facts from `origin` (issue 543 D6-D15).

Two invocations, each reading JSON from standard input (`--input -`) and
resolving the project at the absolute `--repo-root`:

    verification-observe failure --repo-root <abs> --input -
    verification-observe observe --repo-root <abs> --input -

`failure` takes a declaration `{command_id, failure_class, worktree, facts}`
and prints the `verification-failure` it builds. `observe` takes a
`verification` requirement and prints the `verification-observation` of the
same sources. Success exits 0 and writes exactly the canonical bytes of the
result plus one newline to standard output and nothing to standard error. A
refusal exits 2 and writes one line, `verification-observe: <reason>`, to
standard error and nothing to standard output. An invalid invocation writes
`verification-observe: invalid invocation` and exits 2; `--help` exits 0.
The importable `observe_all` observes a list of requirements after one fetch
(issue 546 D2); no command mode runs it.

Both fetch `origin`'s integration branch into its remote-tracking ref, the
only write, and read each selected path's entry at the fetched commit with
`git ls-tree`: its mode and object id, or `null` for both when the path is
absent. No declared
command runs. `failure` also checks that the attempt's worktree belongs to the
`--repo-root` repository, is the top level of its checkout, holds the same
command entry, sits on the fetched commit's entries for every selected path and
has no change to them, a submodule's included.
"""

import argparse
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Sequence

from agent_tools.resolve_project import ContractError, resolve
from agent_tools.verification_blocker import (
    FAILURE_KIND,
    OBSERVATION_KIND,
    SCHEMA_VERSION,
    BlockerRefused,
    canonical_bytes,
    normalize_declaration,
    strict_load,
    validate_failure,
    validate_observation,
    validate_requirement,
)

PROG = "verification-observe"
GIT_TIMEOUT_SECONDS = 60
_INHERITED_GIT_STATE = ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE",
                        "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES")
_TREE_RECORD = re.compile(rb"([0-7]{6}) [a-z]+ ([0-9a-f]{40}|[0-9a-f]{64})\t")


class ObserveRefused(Exception):
    """A refusal; its message is the reason that follows `verification-observe: `."""


class _InvalidInvocation(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message: str):
        raise _InvalidInvocation(message)


def _git(directory: str | Path, *args: str) -> bytes:
    """Run `git -C <directory> <args>`; its stdout, or a refusal naming the subcommand."""
    environment = {name: value for name, value in os.environ.items()
                   if name not in _INHERITED_GIT_STATE}
    environment.update(GIT_TERMINAL_PROMPT="0", GIT_LITERAL_PATHSPECS="1",
                       GIT_OPTIONAL_LOCKS="0")
    try:
        done = subprocess.run(["git", "-C", str(directory), *args], capture_output=True,
                              timeout=GIT_TIMEOUT_SECONDS, check=False, env=environment)
    except subprocess.TimeoutExpired:
        raise ObserveRefused(f"git {args[0]}: timed out after {GIT_TIMEOUT_SECONDS} s") from None
    except OSError as error:
        raise ObserveRefused(f"git {args[0]}: {error.strerror or error}") from error
    if done.returncode != 0:
        lines = [line for line in done.stderr.decode("utf-8", "replace").splitlines()
                 if line.strip()]
        reason = lines[-1].strip() if lines else f"exit {done.returncode}"
        raise ObserveRefused(f"git {args[0]}: {reason}")
    return done.stdout


def _resolve(repo_root: str | Path, required: list[str] | None = None) -> dict:
    try:
        return resolve(str(repo_root), required)
    except ContractError as error:
        raise ObserveRefused(f"resolve-project refused: {error.code} {error.repair_id}") from error


def _command_copy(snapshot: dict, command_id: str) -> dict | None:
    """The command's entry with `cwd` relative to the project root (issue 543 D2)."""
    entry = snapshot["bindings"]["commands"].get(command_id)
    if entry is None:
        return None
    return {"id": command_id, "argv": entry["argv"], "env": entry["env"],
            "cwd": os.path.relpath(entry["cwd"], snapshot["project"]["root"])}


def _fetch(snapshot: dict) -> str:
    """Fetch `origin`'s integration branch; the commit id every read of the call uses."""
    root = snapshot["project"]["root"]
    branch = snapshot["bindings"]["vcs"]["integration_branch"]
    try:  # a refspec takes `*` and other pattern syntax; only one literal branch may be fetched
        _git(root, "check-ref-format", f"refs/heads/{branch}")
    except ObserveRefused:
        raise ObserveRefused(f"integration branch {branch!r} is not a valid branch name") from None
    tracking = f"refs/remotes/origin/{branch}"
    _git(root, "fetch", "--quiet", "--no-tags", "--no-write-fetch-head",
         "--no-auto-maintenance", "--no-recurse-submodules", "--refmap=",
         "origin", f"+refs/heads/{branch}:{tracking}")
    return _git(root, "rev-parse", "--verify", "--end-of-options",
                f"{tracking}^{{commit}}").decode("ascii", "replace").strip()


def _read_entry(directory: str | Path, commit: str, path: str) -> dict:
    """The `{path, mode, object}` entry `commit` holds at `path`; `mode` and `object` are
    `None` when it holds nothing there. The mode is kept so that a change of the executable
    bit alone, which keeps the object id, is still a change."""
    out = _git(directory, "ls-tree", "-z", "--full-tree", commit, "--", path)
    if not out:
        return {"path": path, "mode": None, "object": None}
    record = _TREE_RECORD.match(out)
    if (record is None or not out.endswith(b"\0")
            or out[record.end():-1] != path.encode("utf-8")):
        raise ObserveRefused(f"git ls-tree: unexpected output for {path}")
    return {"path": path, "mode": record.group(1).decode("ascii"),
            "object": record.group(2).decode("ascii")}


def _read_facts(root: str, commit: str, selection: list[dict]) -> list[dict]:
    return [{"name": item["name"], "source": {"paths": item["paths"]},
             "value": {"objects": [_read_entry(root, commit, path) for path in item["paths"]]}}
            for item in selection]


def _repository(snapshot: dict) -> dict:
    return {"project_id": snapshot["project"]["id"],
            "integration_branch": snapshot["bindings"]["vcs"]["integration_branch"]}


def _reason(error: Exception) -> str:
    """The line `main` prints after `verification-observe: `."""
    return " ".join(str(error).split())


def _observations(repo_root: str, requirements: list[dict]
                  ) -> tuple[list[dict], list[tuple[str, str]]]:
    """Observe valid requirements at one fetched commit (issue 546 D2): a resolution or
    fetch refusal refuses every requirement, a read or build refusal only its own."""
    if not requirements:
        return [], []
    try:
        snapshot = _resolve(repo_root)
        commit = _fetch(snapshot)
    except ObserveRefused as error:
        return [], [(requirement["blocker_id"], _reason(error)) for requirement in requirements]
    observations, refused = [], []
    for requirement in requirements:
        try:
            facts = _read_facts(snapshot["project"]["root"], commit, requirement["sources"])
            observations.append(validate_observation({
                "kind": OBSERVATION_KIND, "schema_version": SCHEMA_VERSION,
                "blocker_id": requirement["blocker_id"], "repository": _repository(snapshot),
                "facts": facts}))
        except (ObserveRefused, BlockerRefused) as error:
            refused.append((requirement["blocker_id"], _reason(error)))
    return observations, refused


def observe_all(repo_root: str, requirements: object) -> tuple[list[dict], list[tuple[str, str]]]:
    """The observations of every requirement, after one resolution and at most one fetch
    (issue 546 D2): `(observations, refused)`, each in input order, every requirement in
    exactly one of them; a refusal is `(blocker_id, reason)`, never an observation.

    A non-list, or an element that is not a valid requirement, raises `BlockerRefused`
    naming `requirements[<i>]` before any process starts; an empty list does no I/O.
    """
    if not isinstance(requirements, list):
        raise BlockerRefused("requirements: must be a list")
    for index, requirement in enumerate(requirements):
        try:
            validate_requirement(requirement)
        except BlockerRefused as refusal:
            raise BlockerRefused(f"requirements[{index}]: {refusal}") from None
    return _observations(repo_root, requirements)


def observe(repo_root: str, requirement: object) -> dict:
    """The `verification-observation` of a requirement's sources at `origin`."""
    try:
        validate_requirement(requirement)
    except BlockerRefused as error:
        raise ObserveRefused(str(error)) from error
    observations, refused = _observations(repo_root, [requirement])
    if refused:
        raise ObserveRefused(refused[0][1])
    return observations[0]


def _guard_checkout(snapshot: dict, declaration: dict) -> None:
    """Refuse a worktree of another repository, one below its checkout's top level, or one
    holding a different command entry (issue 543 D7)."""
    worktree, command_id = declaration["worktree"], declaration["command_id"]
    common = [Path(_git(directory, "rev-parse", "--path-format=absolute",
                        "--git-common-dir").decode("utf-8").strip()).resolve()
              for directory in (worktree, snapshot["project"]["root"])]
    if common[0] != common[1]:
        raise ObserveRefused("guard: the worktree is not a checkout of --repo-root's repository")
    top = Path(_git(worktree, "rev-parse", "--show-toplevel").decode("utf-8").strip())
    if top.resolve() != Path(worktree).resolve():
        raise ObserveRefused("guard: the worktree is not the top level of its checkout")
    if _command_copy(_resolve(worktree), command_id) != _command_copy(snapshot, command_id):
        raise ObserveRefused(f"guard: the worktree's {command_id} entry differs from "
                             "--repo-root's")


def _guard_attempt(snapshot: dict, declaration: dict, facts: list[dict]) -> None:
    """Refuse an attempt behind or changing a selected path (issue 543 D15)."""
    worktree = declaration["worktree"]
    branch = snapshot["bindings"]["vcs"]["integration_branch"]
    head = _git(worktree, "rev-parse", "--verify", "--end-of-options",
                "HEAD^{commit}").decode("ascii", "replace").strip()
    selected = [entry for fact in facts for entry in fact["value"]["objects"]]
    for entry in selected:
        if _read_entry(worktree, head, entry["path"]) != entry:
            raise ObserveRefused(f"guard: {entry['path']} at HEAD differs from origin/{branch}")
    changed = _git(worktree, "status", "--porcelain=v1", "-z", "--untracked-files=all",
                   "--ignore-submodules=none", "--",
                   *[entry["path"] for entry in selected])
    if changed:
        raise ObserveRefused("guard: a selected path has a staged, unstaged or untracked change")


def build_failure(repo_root: str, declaration: object) -> dict:
    """The `verification-failure` of a declaration, read at `origin` and guarded (issue 543 D7)."""
    try:
        declared = normalize_declaration(declaration)
        snapshot = _resolve(repo_root, ["verification"])
        command_id = declared["command_id"]
        if command_id not in snapshot["bindings"]["workflow"]["verification"]:
            raise ObserveRefused(f"{command_id} is not a verification command")
        _guard_checkout(snapshot, declared)
        commit = _fetch(snapshot)
        facts = _read_facts(snapshot["project"]["root"], commit, declared["facts"])
        _guard_attempt(snapshot, declared, facts)
        return validate_failure({
            "kind": FAILURE_KIND, "schema_version": SCHEMA_VERSION,
            "repository": _repository(snapshot), "command": _command_copy(snapshot, command_id),
            "failure_class": declared["failure_class"], "facts": facts})
    except BlockerRefused as error:
        raise ObserveRefused(str(error)) from error


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(prog=PROG, allow_abbrev=False,
                     description="Read a verification blocker's repository facts from origin.")
    modes = parser.add_subparsers(dest="mode", required=True)
    for mode, help_text in (("failure", "build a verification-failure from a declaration"),
                            ("observe", "observe a verification requirement's sources")):
        sub = modes.add_parser(mode, help=help_text, allow_abbrev=False)
        sub.add_argument("--repo-root", required=True, help="absolute repository root")
        sub.add_argument("--input", required=True, help="must be - (standard input)")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
        if not os.path.isabs(args.repo_root) or args.input != "-":
            raise _InvalidInvocation(args.mode)
    except _InvalidInvocation:
        sys.stderr.write(f"{PROG}: invalid invocation\n")
        return 2
    build = build_failure if args.mode == "failure" else observe
    try:
        result = build(args.repo_root, strict_load(sys.stdin.buffer.read()))
    except (ObserveRefused, BlockerRefused) as error:
        sys.stderr.write(f"{PROG}: {_reason(error)}\n")
        return 2
    sys.stdout.buffer.write(canonical_bytes(result) + b"\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
