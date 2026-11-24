"""Installing a project's missing dev-shell hooks during `adopt-project apply`.

A host that manages a global `core.hooksPath` hands every repository the managed
shims, and the devenv git-hooks installer, run on every shell entry, refuses to
install into a repository while any hooks path is visible. So the hooks a
project declares in `devenv.nix` never land in `<git-common-dir>/hooks`, and the
adoption commit that goes through the dev shell runs without them.

When this runs. Only when the contract names a commit environment, the
adoption worktree's `HEAD` tracks a `devenv.nix` that declares devenv git hooks
(`declares_hooks`), the repository's local configuration sets no
`core.hooksPath`, and `<git-common-dir>/hooks` holds none of `COMMIT_HOOKS`
(`left_alone`). Anything else leaves the repository as it is, with no process
run: a project that sets its own hooks path or already has a hook installed is
never changed, and a dev shell that declares no hooks is never entered for it.

The command. `install` runs the commit environment's own argv followed by
`INSTALL_COMMAND`, so the shell is entered and exits at once, in the same
adoption worktree and through the same environment as the commit that follows
it, which keeps the installer's per-worktree link current for that commit. Its
environment is apply's, plus `MASK`: `GIT_CONFIG_GLOBAL` set to the null device
for this one command, which hides the managed hooks path from the installer
alone. System configuration is left visible; no other command of apply gets the
mask, so the commit itself still runs under the managed hooks.

On every outcome of the install run, a success, a non-zero exit, a timeout and a
launch failure, the installer's own write of a local `core.hooksPath` is
removed in a `finally`, because a local hooks path would take the managed hooks,
the pre-push guard included, out of the repository. A hooks path that cannot be
removed fails the install. A failed install is refused `adopt.commit.failed`
with `commit_output` `{"hook": None, "exit": None, "lines": [...]}`, retained
like a failed commit, and apply does not commit. `local_hooks_paths` and
`restore_hooks_paths` let apply put the repository's local values back after
the commit, whichever way the commit ended, since the commit's own shell entry
may write one.

The limit. The hook this install puts in place is installed under the
installer's link in the adoption worktree. A later dev-shell entry that runs
unmasked in a worktree whose untracked `.pre-commit-config.yaml` link is missing
or stale (any other worktree of the repository, the owner's checkout included)
will uninstall that hook again. It also writes a local hooks path, which takes
the managed hooks, the pre-push guard included, out of the repository. For a
left-alone project whose hook a pre-commit tool installed, the adoption commit's
own shell entry in the fresh adoption worktree is such an entry: apply puts the
hooks path back, but the removed hook stays removed.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path

from agent_tools.project_contract import adopt_apply, adopt_inspection

COMMIT_HOOKS: tuple[str, ...] = ("pre-commit", "prepare-commit-msg", "commit-msg")
MASK: dict[str, str] = {"GIT_CONFIG_GLOBAL": os.devnull}
INSTALL_COMMAND: tuple[str, ...] = ("true",)
TEXT_LIMIT: int = 1 << 20

DECLARATION = re.compile(r"(?m)^[ \t]*(?:git-hooks|pre-commit)[ \t]*[.=]")
HOOKS_PATH = "core.hooksPath"


def installed(hooks_dir: Path) -> list[str]:
    """The `COMMIT_HOOKS` names that are executable regular files in `hooks_dir`."""
    return [name for name in COMMIT_HOOKS
            if (hooks_dir / name).is_file()
            and os.access(hooks_dir / name, os.X_OK)]


def left_alone(local_hooks_path: str | None, hooks_dir: Path) -> bool:
    """Whether the repository already decides its own hooks."""
    return local_hooks_path is not None or bool(installed(hooks_dir))


def declares_hooks(text: str) -> bool:
    """Whether some line of a `devenv.nix` text sets devenv git hooks."""
    return DECLARATION.search(text) is not None


def declared(worktree: Path) -> bool:
    """Whether `HEAD` of `worktree` tracks a `devenv.nix` that declares hooks."""
    code, kind = adopt_inspection.run_git(worktree, "cat-file", "-t",
                                          "HEAD:devenv.nix")
    if code != 0 or kind.strip() != b"blob":
        return False
    code, size = adopt_inspection.run_git(worktree, "cat-file", "-s",
                                          "HEAD:devenv.nix")
    if code != 0 or not size.strip().isdigit() or int(size) > TEXT_LIMIT:
        return False
    code, text = adopt_inspection.run_git(worktree, "cat-file", "blob",
                                          "HEAD:devenv.nix")
    return code == 0 and declares_hooks(text.decode("utf-8", "replace"))


def local_hooks_paths(root: Path) -> list[str] | None:
    """The repository's local `core.hooksPath` values; None when git cannot say."""
    code, out = adopt_inspection.run_git(
        root, "config", "--local", "--get-all", HOOKS_PATH)
    if code == 1:
        return []
    if code != 0:
        return None
    return out.decode("utf-8", "replace").splitlines()


def restore_hooks_paths(root: Path, before: list[str]) -> None:
    """Put the repository's local `core.hooksPath` values back to `before`."""
    if local_hooks_paths(root) == before:
        return
    code, _ = adopt_inspection.run_git(
        root, "config", "--local", "--unset-all", HOOKS_PATH)
    failed = code not in (0, 5)
    for value in before:
        if failed:
            break
        code, _ = adopt_inspection.run_git(
            root, "config", "--local", "--add", HOOKS_PATH, value)
        failed = code != 0
    if failed:
        raise adopt_apply.environment_failure([
            "the commit environment left a hooks path in the repository's "
            "configuration that could not be put back"])


def withdrawn(root: Path) -> adopt_inspection.AdoptError | None:
    """Remove any local hooks path; the refusal when one could not be removed."""
    code, _ = adopt_inspection.run_git(
        root, "config", "--local", "--get-all", HOOKS_PATH)
    if code == 1:
        return None
    if code == 0:
        code, _ = adopt_inspection.run_git(
            root, "config", "--local", "--unset-all", HOOKS_PATH)
        if code == 0:
            return None
    return adopt_apply.environment_failure([
        "the hook install left a hooks path in the repository's "
        "configuration that could not be removed"])


def hooks_directory(root: Path) -> Path | None:
    """`<git-common-dir>/hooks`, or None when git does not print it."""
    code, out = adopt_inspection.run_git(
        root, "rev-parse", "--path-format=absolute", "--git-common-dir")
    printed = out.decode("utf-8", "replace").strip()
    return Path(printed) / "hooks" if code == 0 and printed else None


def install(root: Path, worktree: Path, environment: dict) -> list[str] | None:
    """Install the missing hooks with the global hooks path masked, returning the `COMMIT_HOOKS` installed.

    None, with no process run, when the repository is left alone, git cannot answer, or the
    worktree's `devenv.nix` declares no hooks; an `AdoptError` on a failed run.
    """
    code, _ = adopt_inspection.run_git(root, "config", "--local",
                                       "--get-all", HOOKS_PATH)
    if code != 1:
        return None
    hooks_dir = hooks_directory(root)
    if hooks_dir is None or left_alone(None, hooks_dir) \
            or not declared(worktree):
        return None
    name = environment["id"]
    argv = environment["argv"]
    failure = None
    try:
        with tempfile.TemporaryFile() as output:
            try:
                status = adopt_apply.run_leashed(
                    [*argv, *INSTALL_COMMAND], cwd=environment["cwd"],
                    env={**adopt_apply.environment_env(), **MASK},
                    stdout=output,
                    timeout=adopt_apply.ENVIRONMENT_TIMEOUT_SECONDS)
                reason = (f"exited {status}" if status != 0 else None)
            except subprocess.TimeoutExpired:
                reason = ("did not finish within "
                          f"{adopt_apply.ENVIRONMENT_TIMEOUT_SECONDS} seconds")
            except FileNotFoundError:
                reason = f"could not be started: {argv[0]} was not found"
            except OSError as error:
                reason = ("could not be started: "
                          f"{error.strerror or 'an error'}")
            except ValueError:
                reason = ("could not be started: an argument contains a NUL "
                          "character")
            if reason is not None:
                failure = adopt_apply.environment_failure([
                    f"the hook install through the commit environment command "
                    f"{name} {reason}",
                    *adopt_apply.commit_output_lines(
                        *adopt_apply.read_tail(output))])
    finally:
        removal = withdrawn(root)
        if removal is not None:
            raise removal from failure
    if failure is not None:
        raise failure
    return installed(hooks_dir)
