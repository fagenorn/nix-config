"""Unattended-run gate, project read at origin, detached worktree and execution (issue 630).

What `verify-pending` may run without a person (P1: only a `kind: evidence` check with no `ask` or
`act` run and `effects` of `none`, never `live` or `paid`; P2, the lead decision: a contract
`command` only when it is a declared `workflow.verification` command, no other runs unattended),
how a project is read (P17: the contract at the integration branch commit the registered `origin` lists, through the
guard-policy reader, never the checkout's working tree, index or local branches), where a check
runs (a detached worktree at the one commit the caller chose, removed afterwards: a `command` run
executes at the contract commit, a `script` or `at` run at the commit the lint checked, the block's
`merge` unless `at` names another) and how its exit is read (P5: 0 met, 1 not met, 75 not yet,
anything else, or the 10-minute timeout, leaves the check pending; P2: output is trimmed, never
trusted). Every git child, the source reader's included, runs without `GITHUB_TOKEN` and
`GH_TOKEN` (P16). No shell is ever involved: a run becomes an argv or
nothing.
"""
from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Mapping, Sequence

from agent_tools import canonical
from agent_tools.guard import guard_policy
from agent_tools.project_contract import adopt_inspection, adopt_verify

TIMEOUT = 600
OUTPUT_LIMIT = 2000
GIT_TIMEOUT = 120

_INDEX = re.compile(r"0|[1-9][0-9]*")


TOKENS = ("GITHUB_TOKEN", "GH_TOKEN")


def child_env(**extra: str) -> dict[str, str]:
    """`os.environ` without the forge tokens: the one environment every child gets."""
    env = {key: value for key, value in os.environ.items() if key not in TOKENS}
    env.update(extra)
    return env


@contextlib.contextmanager
def _tokenless() -> Iterator[None]:
    """Remove the forge tokens from `os.environ` for the block, for readers that start git children
    from the inherited environment, and restore them after it."""
    previous = {name: os.environ.pop(name) for name in TOKENS if name in os.environ}
    try:
        yield
    finally:
        os.environ.update(previous)


# --- gate -------------------------------------------------------------------


@dataclass(frozen=True)
class Gate:
    runnable: bool
    reason: str


def gate(check: Mapping, verification: Sequence[str]) -> Gate:
    """The first refusal of an unattended run, or `Gate(True, "due")`."""
    run = check.get("run") or {}
    if check.get("kind") != "evidence" or "ask" in run or "act" in run:
        return Gate(False, "owner_check")
    effects = check.get("effects", "none")
    if effects == "live":
        return Gate(False, "effects_live")
    if effects == "paid":
        return Gate(False, "effects_paid")
    if "command" in run and run["command"] not in verification:
        return Gate(False, "command_not_verification")
    return Gate(True, "due")


# --- the project, read at origin ---------------------------------------------


class SourceError(Exception):
    """The project could not be read at origin; the message is the repair id or reason."""


@dataclass(frozen=True)
class Source:
    snapshot: dict
    contract_root: Path
    commit: str
    branch: str


@contextlib.contextmanager
def project_source(entry: Mapping) -> Iterator[Source]:
    """The resolved contract at the entry's registered `origin` branch, in a scratch export."""
    with contextlib.ExitStack() as stack:
        # The shared source reader starts its git children from the inherited environment, so the
        # tokens are out of `os.environ` for the whole read (P16); the caller's block runs outside it.
        with _tokenless():
            try:
                source = stack.enter_context(adopt_verify.remote_source(
                    Path(entry["root"]), guard_policy.resolver,
                    (entry.get("branch_override") or {}).get("branch"),
                    network_timeout=GIT_TIMEOUT, reader=guard_policy.CONTRACT_READER))
            except adopt_inspection.AdoptError as error:
                raise SourceError(error.repair_id) from None
            status, payload = guard_policy.resolver(source.resolver_root, "resolve")
            if status != 0:
                raise SourceError(adopt_inspection.resolver_repair_id(payload))
            if payload["bindings"]["vcs"]["integration_branch"] != source.branch:
                raise SourceError("branch_mismatch")
        # The snapshot's command cwds are real paths; the export root must be one too, or
        # `run_argv` cannot relativise them (a symlinked temp dir, as on macOS).
        yield Source(payload, source.resolver_root.resolve(), source.commit, source.branch)


# --- the detached worktree ---------------------------------------------------


class WorkspaceError(Exception):
    """The commit could not be had or checked out."""


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(root), *args], stdin=subprocess.DEVNULL, capture_output=True, text=True,
        timeout=GIT_TIMEOUT, env=child_env(GIT_TERMINAL_PROMPT="0"))


def ensure_commit(root: Path, sha: str) -> bool:
    """Whether `root` holds commit `sha`, fetching it from `origin` once if it does not."""
    try:
        if _git(root, "cat-file", "-e", f"{sha}^{{commit}}").returncode == 0:
            return True
        _git(root, "fetch", "--no-tags", "origin", sha)
        return _git(root, "cat-file", "-e", f"{sha}^{{commit}}").returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


WORKSPACE_PREFIX = "verify-pending-"
WORKSPACE_LEAF = "wt"
_WORKSPACE_PARENT = re.compile(re.escape(WORKSPACE_PREFIX) + r"[a-z0-9_]{8}")


def is_workspace(path: str) -> bool:
    """Whether `path` has the shape `workspace` gives its worktrees: `<tmp>/verify-pending-<8>/wt`.

    The `<8>` is `tempfile.mkdtemp`'s suffix alphabet and length. It judges the last two path
    components only, reads no file and does not consult TMPDIR, so a `/var` or `/private/var`
    spelling of the same directory both match."""
    p = Path(path)
    return p.name == WORKSPACE_LEAF and _WORKSPACE_PARENT.fullmatch(p.parent.name) is not None


@contextlib.contextmanager
def workspace(root: Path, commit: str) -> Iterator[Path]:
    """A detached worktree of `root` at `commit`, removed on exit however the block ends."""
    if not ensure_commit(root, commit):
        raise WorkspaceError(f"commit {commit} is not available from {root}")
    tmp = Path(tempfile.mkdtemp(prefix=WORKSPACE_PREFIX))
    wt = tmp / WORKSPACE_LEAF
    try:
        try:
            added = _git(root, "worktree", "add", "--detach", str(wt), commit)
        except (OSError, subprocess.SubprocessError) as error:
            raise WorkspaceError(f"git worktree add failed: {error}") from None
        if added.returncode != 0:
            raise WorkspaceError(f"git worktree add failed: {added.stderr.strip()}")
        try:
            yield wt
        finally:
            with contextlib.suppress(OSError, subprocess.SubprocessError):
                _git(root, "worktree", "remove", "--force", str(wt))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# --- execution ---------------------------------------------------------------


@dataclass(frozen=True)
class Result:
    exit: int | None
    stdout: str
    stderr: str
    timed_out: bool


def execute(argv: Sequence[str], cwd: Path, timeout: float = TIMEOUT) -> Result:
    """Run `argv` in `cwd` with no stdin and no tokens; kill the whole process group on timeout."""
    try:
        proc = subprocess.Popen(
            list(argv), cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, errors="replace", start_new_session=True, env=child_env())
    except OSError as error:
        return Result(None, "", str(error), False)
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        with contextlib.suppress(OSError):
            os.killpg(proc.pid, signal.SIGKILL)
        out, err = proc.communicate()
        return Result(None, out or "", err or "", True)
    return Result(proc.returncode, out or "", err or "", False)


def run_argv(run: Mapping, bindings: Mapping, contract_root: Path, wt: Path) -> tuple[list[str], Path]:
    """The argv and working directory of a `command` or `script` run; nothing else is ever run."""
    if "command" in run:
        command = bindings["commands"][run["command"]]
        return list(command["argv"]), wt / Path(command["cwd"]).relative_to(contract_root)
    if "script" in run:
        return [str(wt / run["script"]), *run.get("args", [])], wt
    raise ValueError("a run that is neither a command nor a script has no argv")


# --- reading the result ------------------------------------------------------

_MISSING = object()


def _resolve(document: object, pointer: str) -> object:
    """RFC 6901 `pointer` over `document`, or `_MISSING`."""
    if pointer == "":
        return document
    if not pointer.startswith("/"):
        return _MISSING
    node = document
    for part in pointer[1:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if isinstance(node, dict):
            if part not in node:
                return _MISSING
            node = node[part]
        elif isinstance(node, list):
            if not _INDEX.fullmatch(part) or int(part) >= len(node):
                return _MISSING
            node = node[int(part)]
        else:
            return _MISSING
    return node


def _same(a: object, b: object) -> bool:
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def expect_met(expect: Mapping | None, stdout: str) -> bool:
    """Whether every JSON test of `expect` holds over `stdout` (no expectation is always met)."""
    if expect is None:
        return True
    try:
        document = json.loads(stdout, object_pairs_hook=canonical.reject_duplicate_keys,
                              parse_constant=canonical.reject_nonfinite_literal)
    except ValueError:
        return False
    for test in expect.get("json", []):
        value = _resolve(document, test["pointer"])
        if value is _MISSING:
            return False
        if "equals" in test and not _same(value, test["equals"]):
            return False
        if "min_len" in test:
            if not isinstance(value, (str, list, dict)) or len(value) < test["min_len"]:
                return False
    return True


def classify(result: Result, expect: Mapping | None) -> str:
    """`met`, `not_met`, `not_yet`, `timeout` or `exit_unexpected` (P5)."""
    if result.timed_out:
        return "timeout"
    if result.exit == 0:
        return "met" if expect_met(expect, result.stdout) else "not_met"
    if result.exit == 1:
        return "not_met"
    if result.exit == 75:
        return "not_yet"
    return "exit_unexpected"


def trim(text: str, limit: int = OUTPUT_LIMIT) -> str:
    """The last `limit` characters of `text`."""
    return text[-limit:] if limit > 0 else ""
