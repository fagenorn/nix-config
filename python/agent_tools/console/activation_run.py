"""The activation runner (#1193): the contract's console activation, run for one commit, judged by what happened.

The console's Activate button runs the project's own activation command (the `bindings.commands`
entry that `production.console_activation` names, `activation_command`) for one commit: the tip of
the integration branch the activation reading compared. This module launches that run and settles
its outcome. It never decides whether a run may start; the service does.

Own clone. The run builds from a clone of its own, `state_dir / TREE_DIR`, never from the checkout
and never with a worktree registration or a prune: nothing is written to the checkout
(ADR-console-043 D2). A tree that is not a git repository is removed and cloned again with
`git clone --no-checkout <root>`; then every run fetches the checkout's `refs/remotes/origin/*` into
`refs/remotes/source/*`, checks out the commit detached and forced, and cleans the tree. The tree's
git output goes to the log, so a failure there is read from the same file as the command's output.

Own scope. On Linux the run is started inside its own systemd user scope (`systemd-run --user
--scope`, the form the manager uses), because the activation restarts the console, and a process
left in the console unit's cgroup would be killed with it. Elsewhere the run is a process group of
its own. `Run.tree` names the run's process tree (`scope:<unit>.scope` or `group:<pgid>`), so a
console that restarts mid-run can keep waiting for it.

Recorded exit. The command is not started directly but through this module's `record` command,
`python -m agent_tools.console.activation_run record --commit SHA --cwd DIR --log PATH --result
PATH -- ARGV...`. It truncates the log, runs ARGV in DIR with no stdin and stdout and stderr in the
log, waits for it, then writes `{"commit": SHA, "exit": <code>}` (or `{"commit": SHA, "error":
"<Type>: <message>"}` when ARGV cannot start) to the result file by a temporary file and
`os.replace`. No shell is involved. `Activator.start` removes the result file before it launches, and
a result counts for a run only when its `commit` is the run's.

Whole-tree wait. `Activator.wait` returns only once the run's whole process tree is gone,
descendants included (P10): the activation's last steps outlive the command's own exit, and the
console's claim on the activation is held until then. It raises `Stopped` when the service stops
and leaves the run going, recording nothing. Past `seconds` it ends the tree, SIGTERM and then
SIGKILL after `KILL_GRACE_SECONDS`, and still returns only when the tree is gone: a process the
console's user cannot signal (root under sudo) keeps the wait going until it exits on its own. A
read of the tree's state that fails counts as alive.

Outcome. `ok` is True only when the recorded exit is 0 and the host's configuration revision
(`host_revision`) equals the commit (P5). The first match wins: the run timed out; no usable result
(`UNRECORDED_REASON`); the command could not start; it exited non-zero (with the last non-empty line
of the log, cut to 200 characters); the revision is not the commit. Every failure, whether the run
never launched or ended badly, carries `NEXT_STEP`, which names the log.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import agent_tools
from agent_tools.console import activation
from agent_tools.project_contract import resolve_project

ACTIVATE_SECONDS = 3600.0
REVISION_SECONDS = 10.0
POLL_SECONDS = 0.5
KILL_GRACE_SECONDS = 5.0
TREE_DIR = "activation-tree"
LOG_FILE = "activation.log"
RESULT_FILE = "activation.result"
UNIT_PREFIX = "agent-console-activation-"
NEXT_STEP = "Its output is in {log}; press Activate again once the cause is fixed."
UNRECORDED_REASON = "the activation ended without recording how it exited"
_LAST_LINE_CHARS = 200
_LOG_TAIL_BYTES = 8192
_REVISION_PATTERN = re.compile(r"[0-9a-f]{40}(-dirty)?")
_REVISION_COMMANDS = {
    "linux": "/run/current-system/sw/bin/nixos-version",
    "darwin": "/run/current-system/sw/bin/darwin-version",
}
_COULD_NOT_RUN = 127


class Refused(Exception):
    """No command can be named for the console to activate."""


class Stopped(Exception):
    """The wait ended because the service is stopping; the run goes on and nothing is recorded."""


@dataclass(frozen=True)
class Outcome:
    commit: str
    ok: bool
    reason: str | None = None
    next_step: str | None = None


@dataclass(frozen=True)
class Run:
    root: str
    commit: str
    tree: str


def activation_command(root: str) -> tuple[list[str], str]:
    """The argv and the cwd (relative to `root`) of the contract's `production.console_activation` command."""
    try:
        snapshot = resolve_project.resolve(root)
    except resolve_project.ContractError as error:
        raise Refused(f"the project contract did not resolve ({error.code})") from None
    production = snapshot.get("production") or {}
    name = production.get("console_activation") if production.get("status") == "declared" else None
    command = snapshot["bindings"]["commands"].get(name) if isinstance(name, str) else None
    if command is None:
        raise Refused("the project contract names no command for the console to activate")
    return list(command["argv"]), os.path.relpath(command["cwd"], snapshot["project"]["root"])


def host_revision(platform: str = sys.platform, *, run=subprocess.run) -> str | None:
    """The configuration revision this host runs (40 hex, maybe `-dirty`); None when it cannot be read."""
    program = _REVISION_COMMANDS.get("linux" if platform.startswith("linux") else platform)
    if program is None:
        return None
    try:
        done = run(
            [program, "--configuration-revision"], stdin=subprocess.DEVNULL, capture_output=True,
            text=True, timeout=REVISION_SECONDS, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    text = done.stdout.strip() if done.returncode == 0 and isinstance(done.stdout, str) else ""
    return text if _REVISION_PATTERN.fullmatch(text) else None


def _unit(tree: str) -> str:
    return tree.removeprefix("scope:")


def _group(tree: str) -> int:
    return int(tree.removeprefix("group:"))


def tree_alive(tree: str, *, run=subprocess.run) -> bool:
    """Whether any process of the tree lives; a read that fails counts as alive."""
    if tree.startswith("scope:"):
        try:
            done = run(
                ["systemctl", "--user", "show", "--property=ActiveState", "--value", _unit(tree)],
                stdin=subprocess.DEVNULL, capture_output=True, text=True,
                timeout=REVISION_SECONDS, check=False)
        except (OSError, subprocess.SubprocessError):
            return True
        return not (done.returncode == 0 and done.stdout.strip() in ("inactive", "failed", ""))
    try:
        os.killpg(_group(tree), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def stop_tree(tree: str, sig: signal.Signals, *, run=subprocess.run) -> None:
    """Send `sig` to every process of the tree the caller may signal."""
    if tree.startswith("scope:"):
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            run(["systemctl", "--user", "kill", f"--signal={sig.name}", _unit(tree)],
                stdin=subprocess.DEVNULL, capture_output=True, timeout=REVISION_SECONDS,
                check=False)
        return
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(_group(tree), sig)


def _write_result(path: Path, payload: dict) -> None:
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".", suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def record(argv: list[str], *, cwd: str, log: Path, result: Path, commit: str) -> int:
    """Run `argv` in `cwd` with its output in `log`, then record how it exited in `result`."""
    try:
        with open(log, "wb") as out:
            code = subprocess.run(
                argv, cwd=cwd, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
                check=False).returncode
        payload = {"commit": commit, "exit": code}
    except Exception as error:
        code = _COULD_NOT_RUN
        payload = {"commit": commit, "error": f"{type(error).__name__}: {error}"}
    _write_result(result, payload)
    return code


_RECORD_OPTIONS = ("--commit", "--cwd", "--log", "--result")
_USAGE = ("usage: activation_run record --commit SHA --cwd DIR --log PATH --result PATH "
          "-- ARGV...")


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments[:1] != ["record"] or "--" not in arguments:
        print(_USAGE, file=sys.stderr)
        return 2
    split = arguments.index("--")
    options, command = arguments[1:split], arguments[split + 1:]
    if not command or options[0::2] != list(_RECORD_OPTIONS) or len(options) != 2 * len(_RECORD_OPTIONS):
        print(_USAGE, file=sys.stderr)
        return 2
    values = dict(zip(options[0::2], options[1::2]))
    return record(
        command, cwd=values["--cwd"], log=Path(values["--log"]), result=Path(values["--result"]),
        commit=values["--commit"])


# The children this process launched, by tree: a finished leader that nobody reaps stays a zombie,
# and a zombie keeps its process group (and its scope) alive.
_CHILDREN: dict[str, subprocess.Popen] = {}


class Activator:
    """Starts and settles one activation run; see the module docstring."""

    def __init__(
        self, state_dir: Path, *, command_of=activation_command, revision=host_revision,
        tip=activation.origin_tip, seconds: float = ACTIVATE_SECONDS,
        scoped: bool = sys.platform.startswith("linux"), popen=subprocess.Popen,
        run=subprocess.run,
    ):
        self.state_dir = Path(state_dir)
        self.log_path = self.state_dir / LOG_FILE
        self._command_of = command_of
        self._revision = revision
        self._tip = tip
        self._seconds = seconds
        self._scoped = scoped
        self._popen = popen
        self._run = run

    def tip(self, root: str) -> str | None:
        """The commit of origin's integration branch at `root`; may raise `ReadFailed`."""
        return self._tip(root)

    def revision(self) -> str | None:
        return self._revision()

    def _failure(self, commit: str, reason: str) -> Outcome:
        return Outcome(commit, False, reason, NEXT_STEP.format(log=self.log_path))

    def _git(self, *arguments: str, log=subprocess.DEVNULL) -> int:
        try:
            return self._run(
                ["git", *arguments], stdin=subprocess.DEVNULL, stdout=log,
                stderr=subprocess.STDOUT, check=False).returncode
        except OSError:
            return _COULD_NOT_RUN

    def _prepare_tree(self, root: str, commit: str, tree: Path) -> str | None:
        """Bring the run's own clone to `commit`; the failed git step as text, else None."""
        steps = [
            ("fetch", ["-C", str(tree), "fetch", "--quiet", "--no-tags", root,
                       "+refs/remotes/origin/*:refs/remotes/source/*"]),
            ("checkout", ["-C", str(tree), "checkout", "--quiet", "--detach", "--force", commit]),
            ("clean", ["-C", str(tree), "clean", "-q", "-fdx"]),
        ]
        if self._git("-C", str(tree), "rev-parse", "--git-dir") != 0:
            shutil.rmtree(tree, ignore_errors=True)
            steps.insert(0, ("clone", ["clone", "--quiet", "--no-checkout", root, str(tree)]))
        with open(self.log_path, "wb") as log:
            for verb, arguments in steps:
                code = self._git(*arguments, log=log)
                if code != 0:
                    return f"git {verb} exited {code}"
        return None

    def start(self, root: str, commit: str) -> Run | Outcome:
        """Launch the activation of `commit`; an `Outcome` (a failure) means nothing was launched."""
        try:
            argv, relative = self._command_of(root)
        except Refused as error:
            return self._failure(commit, str(error))
        tree = self.state_dir / TREE_DIR
        result = self.state_dir / RESULT_FILE
        try:
            self.state_dir.mkdir(parents=True, exist_ok=True)
            result.unlink(missing_ok=True)
            failed = self._prepare_tree(root, commit, tree)
        except OSError as error:
            return self._failure(
                commit, f"the activation command could not start ({type(error).__name__}: {error})")
        if failed is not None:
            return self._failure(commit, f"the tree at {commit[:12]} could not be prepared ({failed})")
        command = [
            sys.executable, "-m", "agent_tools.console.activation_run", "record",
            "--commit", commit, "--cwd", str(tree / relative), "--log", str(self.log_path),
            "--result", str(result), "--", *argv]
        unit = f"{UNIT_PREFIX}{commit[:12]}-{secrets.token_hex(4)}"
        if self._scoped:
            command = ["systemd-run", "--user", "--scope", "--quiet", "--collect",
                       f"--unit={unit}", f"--description=agent console activation {commit[:12]}",
                       "--", *command]
        env = {**os.environ, "PYTHONPATH": str(Path(agent_tools.__file__).resolve().parent.parent)}
        try:
            process = self._popen(
                command, cwd=self.state_dir, env=env, stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        except OSError as error:
            return self._failure(
                commit, f"the activation command could not start ({type(error).__name__}: {error})")
        name = f"scope:{unit}.scope" if self._scoped else f"group:{process.pid}"
        _CHILDREN[name] = process
        return Run(root, commit, name)

    def wait(self, run: Run, stop: threading.Event) -> Outcome:
        """Block until the run's whole tree is gone; `Stopped` when `stop` is set first."""
        began = time.monotonic()
        terminated_at: float | None = None
        killed = False
        while True:
            if stop.is_set():
                raise Stopped()
            child = _CHILDREN.get(run.tree)
            if child is not None and child.poll() is not None:
                _CHILDREN.pop(run.tree, None)
            if not tree_alive(run.tree, run=self._run):
                break
            now = time.monotonic()
            if terminated_at is None and now - began >= self._seconds:
                stop_tree(run.tree, signal.SIGTERM, run=self._run)
                terminated_at = now
            elif terminated_at is not None and not killed and now - terminated_at >= KILL_GRACE_SECONDS:
                stop_tree(run.tree, signal.SIGKILL, run=self._run)
                killed = True
            stop.wait(POLL_SECONDS)
        _CHILDREN.pop(run.tree, None)
        return self._outcome(run, timed_out=terminated_at is not None)

    def _last_line(self) -> str | None:
        try:
            with open(self.log_path, "rb") as handle:
                handle.seek(0, os.SEEK_END)
                handle.seek(max(0, handle.tell() - _LOG_TAIL_BYTES))
                lines = handle.read().decode("utf-8", "replace").splitlines()
        except OSError:
            return None
        lines = [line.strip() for line in lines if line.strip()]
        return lines[-1][:_LAST_LINE_CHARS] if lines else None

    def _recorded(self, commit: str) -> dict | None:
        try:
            document = json.loads((self.state_dir / RESULT_FILE).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return document if isinstance(document, dict) and document.get("commit") == commit else None

    def _outcome(self, run: Run, *, timed_out: bool) -> Outcome:
        commit = run.commit
        if timed_out:
            return self._failure(
                commit,
                f"the activation ran longer than {int(self._seconds // 60)} minutes and was stopped")
        result = self._recorded(commit) or {}
        code, error = result.get("exit"), result.get("error")
        if isinstance(error, str):
            return self._failure(commit, f"the activation command could not start ({error})")
        if isinstance(code, bool) or not isinstance(code, int):
            return self._failure(commit, UNRECORDED_REASON)
        if code != 0:
            last = self._last_line()
            return self._failure(
                commit, f"the activation command exited {code}" + (f" ({last})" if last else ""))
        revision = self.revision()
        if revision is None:
            return self._failure(
                commit, "the activation command finished but this host's revision could not be read")
        if revision != commit:
            return self._failure(
                commit, f"the activation command finished but this host runs {revision[:12]}")
        return Outcome(commit, True)


if __name__ == "__main__":
    sys.exit(main())
