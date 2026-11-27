"""`lock_bump_tree`: the file side of a lock bump, pure edits first.

`pinned_revision` and `bumped_lock` read the lock through `adopt_conformance.lock_with_platform(lock, None)`,
so only a kept `agent-platform` entry is ever edited and a missing or foreign one is `BumpRefused`, never a
new entry. `bumped_lock` replaces that node's `locked` member with the proven revision's record and nothing
else, serialised as the adoption does (sorted, indented, a trailing newline only when the input had one).
`required_migrations` names the migration a proven revision needs a contract to take: one step, which must
land on a schema the revision reads, because each real migration resolves its own output at once; a step
that lands on a retired schema is `BumpRefused` before any file is touched.

`GitBuilder` builds the bump commit. Every child runs in its own group with no stdin, no `GITHUB_TOKEN`,
`GH_TOKEN` or repository selector, and a set `cancel` ends the build with `approve.Cancelled`. `pin` checks
that `origin` of the checkout is the project, fetches the base and reads the lock's pinned revision there.
`build` returns `Built(branch, commit)`. It reuses a bump branch already on the remote only after `verify`
shows its head locks the proven revision (anything else is `BumpRefused`, never reused); else it takes the proven revision's package (whose record
must be that revision of the platform repository), makes a scratch worktree at the base, writes the bumped
lock, runs the migrations the revision requires and its projections with the package's own tools, commits
signed as the contract's `bindings.vcs.commit.signed` says (never as the host's default does) and pushes
that commit to the bump branch without force. `verify` fetches the bump branch and refuses unless its tip
is the named head and the lock at that head pins the proven revision. The worktree and its directory are
removed on every outcome.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import NamedTuple

from agent_tools.canonical import reject_duplicate_keys
from agent_tools.console import approve, manager
from agent_tools.delivery import proof_run
from agent_tools.project_contract import adopt_conformance
from agent_tools.project_contract.adopt_apply import signing_requested
from agent_tools.project_contract.adopt_inspection import AdoptError
from agent_tools.project_contract.adopt_planning import select_forward_step
from agent_tools.project_contract.agent_platform import valid_revision

BRANCH_PREFIX = "lock-bump-"
BRANCH = re.compile(r"lock-bump-([0-9a-f]{40})")
REVISION = re.compile(r"[0-9a-f]{40}")


class BumpRefused(Exception):
    """A bump that cannot be made, in plain words."""


class Built(NamedTuple):
    branch: str
    commit: str


def branch_for(revision: str) -> str:
    if not isinstance(revision, str) or REVISION.fullmatch(revision) is None:
        raise ValueError("a bump branch names a revision in full")
    return BRANCH_PREFIX + revision


def revision_of_branch(ref: str) -> str | None:
    found = BRANCH.fullmatch(ref) if isinstance(ref, str) else None
    return found[1] if found else None


def _entry(lock: bytes) -> adopt_conformance.LockEntry:
    try:
        return adopt_conformance.lock_with_platform(lock, None)
    except adopt_conformance.Undeclarable as error:
        raise BumpRefused(f"the lock cannot be bumped: {error.repair_id}") from None


def pinned_revision(lock: bytes) -> str:
    return _entry(lock).locked["rev"]


def bumped_lock(lock: bytes, record: Mapping[str, object]) -> bytes:
    entry = _entry(lock)
    if not valid_revision(record):
        raise BumpRefused("the proven revision's record is malformed")
    if (record["owner"], record["repo"]) != (entry.locked["owner"], entry.locked["repo"]):
        raise BumpRefused("the proven revision's record names another repository than the lock")
    document = json.loads(lock.decode("utf-8"), object_pairs_hook=reject_duplicate_keys)
    document["nodes"][entry.node]["locked"] = dict(record)
    text = json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False)
    if lock.endswith(b"\n"):
        text += "\n"
    return text.encode("utf-8")


def required_migrations(manifest: Mapping, schema_version: int) -> list[str]:
    supported = manifest["project_schema_versions"]
    if schema_version in supported:
        return []
    try:
        step = select_forward_step(dict(manifest), schema_version)
    except AdoptError as error:
        raise BumpRefused(f"no single migration steps forward from schema {schema_version}: "
                          f"{error.repair_id}") from None
    if step is None:
        raise BumpRefused(f"no migration steps forward from schema {schema_version}")
    target = step.get("to_schema")
    if target not in supported:
        raise BumpRefused(f"the migration {step['id']} from schema {schema_version} lands on schema {target}, "
                          "which the proven revision does not read, and a migration resolves its own output")
    return [step["id"]]


CHILD_TIMEOUT = 1800.0
_DROPPED = ("GITHUB_TOKEN", "GH_TOKEN", *proof_run.SELECTORS)


def _run(argv: Sequence[str], step: str, cancel: threading.Event | None, timeout: float,
         ok: Sequence[int] = (0,)) -> subprocess.CompletedProcess:
    """One child in its own group; its result when its exit is in `ok`, else `BumpRefused` naming `step`."""
    if cancel is not None and cancel.is_set():
        raise approve.Cancelled()
    env = {key: value for key, value in os.environ.items() if key not in _DROPPED}
    env["GIT_TERMINAL_PROMPT"] = "0"
    try:
        done = manager.run_in_own_group(
            list(argv), timeout=timeout, cancel=cancel, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, start_new_session=True, env=env)
    except subprocess.TimeoutExpired:
        raise BumpRefused(f"{step} timed out") from None
    except OSError as error:
        raise BumpRefused(f"{step} could not start: {error}") from None
    if cancel is not None and cancel.is_set():
        raise approve.Cancelled()
    if done.returncode not in ok:
        lines = (done.stderr or b"").decode("utf-8", "replace").strip().splitlines()
        raise BumpRefused(f"{step} failed: {lines[0] if lines else 'exit ' + str(done.returncode)}")
    return done


def checked_origin(root: Path, slug: str) -> None:
    answers: list[str | None] = []
    for arguments in (("get-url", "origin"), ("get-url", "--push", "--all", "origin")):
        try:
            done = _run(["git", "-C", str(root), "remote", *arguments], "the origin read", None, 60.0)
            answers.extend(done.stdout.decode("utf-8", "replace").split())
        except BumpRefused:
            answers.append(None)
    if not adopt_conformance.names_origin(answers, slug):
        raise BumpRefused(f"the remote origin of {root} is not {slug}")


def nix_package(platform_repo: str, revision: str, cancel: threading.Event | None, *,
                timeout: float = CHILD_TIMEOUT) -> Path:
    done = _run(["nix", "build", "--no-link", "--print-out-paths",
                 f"github:{platform_repo}/{revision}#agent-platform"], "the platform build", cancel, timeout)
    lines = done.stdout.decode("utf-8", "replace").strip().splitlines()
    out = Path(lines[-1]) if lines else None
    if out is None or not out.is_absolute() or not out.is_dir():
        raise BumpRefused("the platform build named no package directory")
    return out


def _json_file(path: Path, what: str) -> object:
    try:
        return json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, ValueError, RecursionError):
        raise BumpRefused(f"{what} cannot be read") from None


class GitBuilder:
    def __init__(self, platform_repo: str, *,
                 package: Callable[[str, threading.Event | None], Path] | None = None,
                 origin_check: Callable[[Path, str], None] | None = None,
                 timeout: float = CHILD_TIMEOUT):
        self._platform_repo = platform_repo
        self._timeout = timeout
        self._package = package or (
            lambda revision, cancel: nix_package(platform_repo, revision, cancel, timeout=timeout))
        self._origin_check = origin_check or checked_origin

    def _git(self, root: Path, step: str, cancel, *args: str, ok: Sequence[int] = (0,)):
        return _run(["git", "-C", str(root), *args], step, cancel, self._timeout, ok)

    def pin(self, root: Path, slug: str, base: str, cancel: threading.Event | None = None) -> str:
        self._origin_check(root, slug)
        self._git(root, "the base fetch", cancel, "fetch", "--quiet", "--no-tags", "origin",
                  f"+refs/heads/{base}:refs/remotes/origin/{base}")
        shown = self._git(root, "the lock read", cancel, "show", f"origin/{base}:{adopt_conformance.LOCK_FILE}")
        return pinned_revision(shown.stdout)

    def _record(self, out: Path, revision: str) -> dict:
        found = _json_file(out / "share" / "agent-platform" / "platform-revision.json", "the package's revision")
        if not isinstance(found, dict) or found.get("schema_version") != 1:
            raise BumpRefused("the package's revision record is of a schema this build does not read")
        record = {key: value for key, value in found.items() if key != "schema_version"}
        if (not valid_revision(record) or record["rev"] != revision
                or f"{record['owner']}/{record['repo']}" != self._platform_repo):
            raise BumpRefused(f"the package was not built from {self._platform_repo}@{revision}")
        return record

    def verify(self, root: Path, slug: str, revision: str, head: str,
               cancel: threading.Event | None = None) -> None:
        """Refuse unless the bump branch's tip is `head` and the lock there pins `revision`."""
        branch = branch_for(revision)
        self._git(root, "the bump branch fetch", cancel, "fetch", "--quiet", "--no-tags", "origin",
                  f"+refs/heads/{branch}:refs/remotes/origin/{branch}")
        tip = self._git(root, "the bump branch read", cancel, "rev-parse", "--verify",
                        f"refs/remotes/origin/{branch}").stdout.decode().strip()
        if tip != head:
            raise BumpRefused(f"the bump branch is at {tip[:12]}, not at {head[:12]}")
        shown = self._git(root, "the bump lock read", cancel, "show", f"{head}:{adopt_conformance.LOCK_FILE}")
        if pinned_revision(shown.stdout) != revision:
            raise BumpRefused(f"the bump branch does not lock {revision[:12]}")

    def build(self, root: Path, slug: str, base: str, revision: str,
              cancel: threading.Event | None = None) -> Built:
        branch = branch_for(revision)
        found = self._git(root, "the bump branch read", cancel, "ls-remote", "--exit-code", "origin",
                          f"refs/heads/{branch}", ok=(0, 2))
        if found.returncode == 0:
            words = found.stdout.decode("utf-8", "replace").split()
            head = words[0] if words else ""
            if approve.COMMIT.fullmatch(head) is None:
                raise BumpRefused("the bump branch has no readable head")
            self.verify(root, slug, revision, head, cancel)
            return Built(branch, head)
        out = self._package(revision, cancel)
        record = self._record(out, revision)
        manifest = _json_file(out / "share" / "agent-platform" / "platform-manifest.json", "the package's manifest")
        scratch = Path(tempfile.mkdtemp(prefix="lock-bump-"))
        tree = scratch / "tree"
        try:
            self._git(root, "the worktree", cancel, "worktree", "add", "--quiet", "--detach", str(tree),
                      f"origin/{base}")
            signing = self._edit(tree, out, manifest, record, cancel)
            self._git(tree, "the staging", cancel, "add", "--all")
            self._git(tree, "the commit", cancel, "commit", "--quiet", "--no-verify", signing, "-m",
                      f"Bump the agent platform to {revision[:12]}")
            commit = self._git(tree, "the commit read", cancel, "rev-parse", "HEAD").stdout.decode().strip()
            self._git(root, "the push", cancel, "push", "--quiet", "--no-follow-tags", "origin",
                      f"{commit}:refs/heads/{branch}")
        finally:
            self._clean(root, tree, scratch)
        return Built(branch, commit)

    def _edit(self, tree: Path, out: Path, manifest: object, record: dict, cancel) -> str:
        lock_file = tree / adopt_conformance.LOCK_FILE
        try:
            lock_file.write_bytes(bumped_lock(lock_file.read_bytes(), record))
        except OSError as error:
            raise BumpRefused(f"the lock cannot be written: {error}") from None
        contract = _json_file(tree / ".agents" / "project.json", "the project contract")
        schema = contract.get("schema_version") if isinstance(contract, dict) else None
        if isinstance(schema, bool) or not isinstance(schema, int):
            raise BumpRefused("the project contract declares no schema version")
        if (not isinstance(manifest, dict) or not isinstance(manifest.get("migrations"), list)
                or not isinstance(manifest.get("project_schema_versions"), list)):
            raise BumpRefused("the package's manifest is malformed")
        for migration in required_migrations(manifest, schema):
            _run([str(out / "bin" / "adopt-project"), "migrate", "--migration", migration,
                  "--repo-root", str(tree)], "the migration", cancel, self._timeout)
        _run([str(out / "bin" / "resolve-project"), "write-projections", "--repo-root", str(tree)],
             "the projections", cancel, self._timeout)
        resolved = _run([str(out / "bin" / "resolve-project"), "resolve", "--repo-root", str(tree)],
                        "the contract resolution", cancel, self._timeout)
        try:
            payload = json.loads(resolved.stdout.decode("utf-8"))
        except (ValueError, RecursionError):
            raise BumpRefused("the contract resolution is not JSON") from None
        signed = signing_requested(payload)
        if signed is None:
            raise BumpRefused("the contract's commit signing policy could not be resolved")
        return "-S" if signed else "--no-gpg-sign"

    def _clean(self, root: Path, tree: Path, scratch: Path) -> None:
        try:
            self._git(root, "the worktree removal", None, "worktree", "remove", "--force", str(tree))
        except BumpRefused:
            pass
        shutil.rmtree(scratch, ignore_errors=True)
        try:
            self._git(root, "the worktree prune", None, "worktree", "prune")
        except BumpRefused:
            pass
