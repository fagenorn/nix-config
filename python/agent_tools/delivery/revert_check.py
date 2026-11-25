"""`revert-check`: the new tests of a change that still pass at the merge base, as a platform command.

`revert-check --worktree-path <abs path> --integration-branch <name>` (both required; a usage error is
exit 2) prints exactly one compact JSON line, keys sorted, and exits 0 whatever it finds:
`{base, head, new_tests, reason, still_passing, verdict}`. `verdict` is always `ok`; `base` is the
merge base of the worktree's `HEAD` and `refs/remotes/origin/<branch>` and `head` is the worktree's
`HEAD` (each `""` when unread); `new_tests` lists the change's new test ids sorted by file path then
id; `still_passing` is the subset whose run exited 0, in the same order; `reason` is `""` when every
new test ran, else one sentence saying why the check did not run or did not finish. The result is
information for a reviewer and never blocks (issue 1421). The decision is ADR-delivery-022.

A new test is a `test*` method (`def` or `async def`) directly in a top-level class whose bases reach
a base named `TestCase` (a bare name or an attribute `x.TestCase`) through classes defined in the
same file. Its id is `<module>.<Class>.<method>`, `<module>` being the file's path relative to the
worktree root with `.py` dropped and `/` replaced by `.`. It is new when the file at the merge base
(absent counts as empty) lacks `<Class>.<method>`. Only `.py` files changed `A` or `M` between the
merge base and `HEAD` (`git diff --no-renames`) are read. A change with no new test returns empty
lists and `reason ""` and creates nothing.

The check adds a detached scratch worktree at the merge base, made under
`tempfile.mkdtemp(prefix="revert-check-", dir=<scratch root>)` with hooks off, and writes into it the
`HEAD` version (bytes) of each file holding a new test, nothing else of the change. The scratch root
is `$REVERT_CHECK_SCRATCH` or the system temporary directory. Each new test then runs once as
`python -m unittest <id>` with the scratch as the working directory, no standard stream inherited, in
its own session, the process group killed after `TEST_SECONDS`; exit 0 is still passing, any other
exit or a timeout is not. The tests' `PYTHONPATH` is the scratch root, then `<scratch>/<D>` for each
distinct non-empty `D` that is the parent of a top-level package tracked in the scratch (a tracked
`<pkg>/__init__.py` whose parent directory holds no `__init__.py`), sorted, then the inherited entries
whose real path is not the run's worktree or inside it, so the reverted source is what a test
imports. The git variables of `engine_shell.REPOSITORY_ENV` are dropped from every child.

The scratch is always removed (`git worktree remove --force`, the directory, `git worktree prune`);
a removal that fails adds `the scratch worktree <path> could not be removed: <git's last stderr
line>` to `reason`. The run's worktree, index and branch are never written: every git command run
against it is read-only except `worktree add`, `remove` and `prune`.

Every failure is still `ok` with exit 0 and a `reason`: an unreadable `HEAD` or merge base is `the
merge base of HEAD and origin/<branch> could not be read: <git's last stderr line>`; a scratch that
cannot be made is `the scratch worktree could not be made: <error>`; a test that cannot be started
is `a test could not be started: <error>` and stops the run; any other exception is `the check
failed: <ExceptionType>: <error>`. `still_passing` then holds only the tests that already passed.
Before each test, once `BUDGET_SECONDS` have passed since the start, no further test runs and `reason`
is `the check ran out of its <budget> s budget after <k> of <n> new tests`.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable, Mapping, Sequence

from agent_tools.delivery.engine_shell import REPOSITORY_ENV

TEST_SECONDS = 300
BUDGET_SECONDS = 1200
SCRATCH_ENV = "REVERT_CHECK_SCRATCH"
GIT_SECONDS = 120

RunGit = Callable[..., "subprocess.CompletedProcess[bytes]"]


def _reaches_testcase(name: str, classes: Mapping[str, ast.ClassDef], seen: frozenset[str] = frozenset()) -> bool:
    if name in seen:
        return False
    for base in classes[name].bases:
        if isinstance(base, ast.Name) and base.id == "TestCase":
            return True
        if isinstance(base, ast.Attribute) and base.attr == "TestCase":
            return True
        if isinstance(base, ast.Name) and base.id in classes and _reaches_testcase(base.id, classes, seen | {name}):
            return True
    return False


def case_ids(source: str) -> frozenset[str]:
    """The `<Class>.<method>` ids of the test methods of one Python file's text."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return frozenset()
    classes = {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}
    return frozenset(
        f"{name}.{member.name}"
        for name, node in classes.items() if _reaches_testcase(name, classes)
        for member in node.body
        if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)) and member.name.startswith("test"))


def _last_line(done: "subprocess.CompletedProcess[bytes]") -> str:
    lines = done.stderr.decode(errors="replace").strip().splitlines()
    return lines[-1] if lines else f"git exited {done.returncode}"


def _git_runner(environ: Mapping[str, str]) -> RunGit:
    env = {name: value for name, value in environ.items() if name not in REPOSITORY_ENV}

    def run_git(*args: str) -> "subprocess.CompletedProcess[bytes]":
        return subprocess.run(["git", *args], capture_output=True, env=env, stdin=subprocess.DEVNULL,
                              timeout=GIT_SECONDS)
    return run_git


def _show(run_git: RunGit, worktree: str, revision: str, path: str) -> bytes | None:
    done = run_git("-C", worktree, "show", f"{revision}:{path}")
    return done.stdout if done.returncode == 0 else None


def _new_tests(worktree: str, base: str, head: str, run_git: RunGit) -> list[tuple[str, str]]:
    """The `(path, id)` of each new test of the change, sorted by path then id."""
    done = run_git("-C", worktree, "diff", "--no-renames", "--name-only", "--diff-filter=AM", "-z", base, head)
    if done.returncode:
        raise RuntimeError(f"git diff: {_last_line(done)}")
    found: list[tuple[str, str]] = []
    for path in sorted(name for name in done.stdout.decode(errors="replace").split("\0") if name.endswith(".py")):
        text = _show(run_git, worktree, head, path)
        if text is None:
            continue
        before = _show(run_git, worktree, base, path)
        old = case_ids(before.decode(errors="replace")) if before is not None else frozenset()
        module = path[:-len(".py")].replace("/", ".")
        found.extend((path, f"{module}.{case}")
                     for case in sorted(case_ids(text.decode(errors="replace")) - old))
    return found


def _python_path(scratch: str, worktree: str, inherited: str, run_git: RunGit) -> str:
    tracked = run_git("-C", scratch, "ls-files", "-z", "--", "*__init__.py")
    inits = {name for name in tracked.stdout.decode(errors="replace").split("\0") if name}
    roots = set()
    for name in inits:
        package = os.path.dirname(name)
        parent = os.path.dirname(package)
        if parent and os.path.join(parent, "__init__.py") not in inits:
            roots.add(parent)
    run = os.path.realpath(worktree)
    kept = [entry for entry in inherited.split(os.pathsep)
            if entry and os.path.realpath(entry) != run and not os.path.realpath(entry).startswith(run + os.sep)]
    return os.pathsep.join([scratch, *(os.path.join(scratch, root) for root in sorted(roots)), *kept])


def _passes(identifier: str, scratch: str, env: Mapping[str, str], test_seconds: float) -> bool:
    process = subprocess.Popen(
        [sys.executable, "-m", "unittest", identifier], cwd=scratch, env=dict(env),
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True)
    try:
        return process.wait(timeout=test_seconds) == 0
    except subprocess.TimeoutExpired:
        return False
    finally:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except OSError:
            pass
        process.wait()


def check(worktree: str, integration_branch: str, *, environ: Mapping[str, str], scratch_root: str,
          test_seconds: float = TEST_SECONDS, budget_seconds: float = BUDGET_SECONDS) -> dict:
    started = time.monotonic()
    result: dict = {"verdict": "ok", "base": "", "head": "", "new_tests": [], "still_passing": [], "reason": ""}
    run_git = _git_runner(environ)
    try:
        head = run_git("-C", worktree, "rev-parse", "HEAD")
        if head.returncode == 0:
            result["head"] = head.stdout.decode().strip()
        base = run_git("-C", worktree, "merge-base", "HEAD", f"refs/remotes/origin/{integration_branch}")
        if head.returncode or base.returncode:
            failed = head if head.returncode else base
            result["reason"] = (f"the merge base of HEAD and origin/{integration_branch} "
                                f"could not be read: {_last_line(failed)}")
            return result
        result["base"] = base.stdout.decode().strip()
        found = _new_tests(worktree, result["base"], result["head"], run_git)
        result["new_tests"] = [identifier for _, identifier in found]
        if found:
            _run_in_scratch(worktree, result, found, run_git, environ, scratch_root,
                            test_seconds, budget_seconds, started)
    except Exception as error:
        result["reason"] = f"the check failed: {type(error).__name__}: {error}"
    return result


def _run_in_scratch(worktree: str, result: dict, found: list[tuple[str, str]], run_git: RunGit,
                    environ: Mapping[str, str], scratch_root: str, test_seconds: float,
                    budget_seconds: float, started: float) -> None:
    scratch = None
    added = False
    try:
        try:
            scratch = os.path.realpath(tempfile.mkdtemp(prefix="revert-check-", dir=scratch_root))
            done = run_git("-C", worktree, "-c", "core.hooksPath=/dev/null", "worktree", "add",
                           "--detach", "--quiet", scratch, result["base"])
            if done.returncode:
                raise OSError(_last_line(done))
            added = True
        except (OSError, subprocess.SubprocessError) as error:
            result["reason"] = f"the scratch worktree could not be made: {error}"
            return
        for path in sorted({path for path, _ in found}):
            text = _show(run_git, worktree, result["head"], path)
            if text is None:
                raise RuntimeError(f"{path} is not readable at {result['head']}")
            target = Path(scratch, path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(text)
        env = {name: value for name, value in environ.items() if name not in REPOSITORY_ENV}
        env["PYTHONPATH"] = _python_path(scratch, worktree, environ.get("PYTHONPATH", ""), run_git)
        for ran, (_, identifier) in enumerate(found):
            if time.monotonic() - started >= budget_seconds:
                result["reason"] = (f"the check ran out of its {budget_seconds:g} s budget "
                                    f"after {ran} of {len(found)} new tests")
                break
            try:
                passed = _passes(identifier, scratch, env, test_seconds)
            except OSError as error:
                result["reason"] = f"a test could not be started: {error}"
                break
            if passed:
                result["still_passing"].append(identifier)
    except Exception as error:
        result["reason"] = f"the check failed: {type(error).__name__}: {error}"
    finally:
        if scratch is not None:
            _remove(worktree, scratch, added, result, run_git)


def _remove(worktree: str, scratch: str, added: bool, result: dict, run_git: RunGit) -> None:
    problem = ""
    try:
        if added:
            done = run_git("-C", worktree, "worktree", "remove", "--force", scratch)
            if done.returncode:
                problem = _last_line(done)
    except Exception as error:
        problem = f"{type(error).__name__}: {error}"
    shutil.rmtree(scratch, ignore_errors=True)
    try:
        run_git("-C", worktree, "worktree", "prune")
    except Exception:
        pass
    if problem:
        message = f"the scratch worktree {scratch} could not be removed: {problem}"
        result["reason"] = f"{result['reason']} {message}".strip()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="revert-check", description=__doc__)
    parser.add_argument("--worktree-path", required=True)
    parser.add_argument("--integration-branch", required=True)
    args = parser.parse_args(argv)
    scratch_root = os.environ.get(SCRATCH_ENV) or tempfile.gettempdir()
    result = check(args.worktree_path, args.integration_branch, environ=os.environ, scratch_root=scratch_root)
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
