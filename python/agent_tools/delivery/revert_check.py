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
merge base and `HEAD` (`git diff --no-renames`) are read, as the blob bytes (so a byte-order mark or a
coding declaration is the parser's). A blob git cannot read ends the check with its error in `reason`.
A change with no new test returns empty lists and `reason ""` and creates nothing.

The check makes a scratch directory with `tempfile.mkdtemp(prefix="revert-check-", dir=<scratch
root>)`, `$REVERT_CHECK_SCRATCH` or else the system temporary directory, made by a guard process in a
session of its own that removes it again once the checker is gone, whenever that happens (an engine stop
kills only the checker's group). The directory holds a checkout of the
merge base (`read-tree` into a private index file, then `checkout-index`; no worktree is registered,
so no repository-wide `git worktree` command runs) and, per test, a fresh checkout with the `HEAD`
version (bytes) of each file holding a new test written over it, nothing else of the change, so no
test sees what an earlier one left. A write refuses a path that passes through a symlink of the merge
base (it would lead out of the scratch), and a new test's top-level directory that holds no
`__init__.py` gets an empty one, so a regular package of that name on the inherited `PYTHONPATH` cannot
shadow it. Each new test then runs once as `python -m unittest <id>` with the scratch checkout as the
working directory, no standard stream inherited, in its own session behind a small watcher that kills
the session when the checker dies; the guard and the watcher are given the checker's pid, so a checker
that dies before they start is noticed too; the group is also killed after `TEST_SECONDS`. Exit 0 is still passing, any other
exit or a timeout is not. The tests' `PYTHONPATH` is the checkout, then `<checkout>/<D>` for each
distinct non-empty `D` that is the parent of a top-level package tracked at the merge base (a tracked
`<pkg>/__init__.py` whose parent directory holds no `__init__.py`), sorted, then the inherited entries
whose real path is not the run's worktree or inside it, so the reverted source is what a test
imports; `PYTHONPYCACHEPREFIX` is the scratch directory's own, so no bytecode lands elsewhere. The git
variables of `engine_shell.REPOSITORY_ENV` are dropped from every child.

The scratch directory is always removed; a removal that fails adds `the scratch worktree <path> could
not be removed: <error>` to `reason`. The run's worktree, index, refs and worktree list are never
written: the only git commands run against it are reads.

Every failure is still `ok` with exit 0 and a `reason`: an unreadable `HEAD` or merge base is `the
merge base of HEAD and origin/<branch> could not be read: <git's last stderr line>`; a scratch that
cannot be made (a temporary directory included) is `the scratch worktree could not be made: <error>`;
a test that cannot be started is `a test could not be started: <error>` and stops the run; any other
exception is `the check failed: <ExceptionType>: <error>`. `still_passing` then holds only the tests
that already passed. Before each test, once `BUDGET_SECONDS` have passed since the start, no further
test runs and `reason` is `the check ran out of its <budget> s budget after <k> of <n> new tests`.
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
from typing import Callable, Mapping, Sequence

from agent_tools.delivery.engine_shell import REPOSITORY_ENV

TEST_SECONDS = 300
BUDGET_SECONDS = 1200
SCRATCH_ENV = "REVERT_CHECK_SCRATCH"
GIT_SECONDS = 120
WATCH_SECONDS = 0.1

# Both helpers take the checker's pid in argv rather than reading their parent's: a checker stopped before the
# helper's interpreter has started leaves the helper a parent that is already init, and the pid in argv still
# tells them it is gone.
#
# Runs as `python -I -c GUARD <checker pid> <scratch root>`, in a session of its own (an engine stop kills only
# the checker's group): it makes the scratch directory, tells the checker its path on one line (`!<error>` when
# it cannot be made) and, once the checker is gone, removes the directory again until it is gone, so a stop at
# any point of the scratch's life leaves nothing behind.
GUARD = """
import os, shutil, sys, tempfile, time
parent = int(sys.argv[1])
try:
    holder = os.path.realpath(tempfile.mkdtemp(prefix="revert-check-", dir=sys.argv[2]))
    line = holder
except OSError as error:
    holder, line = None, "!" + str(error).replace("\\n", " ")
try:
    print(line, flush=True)
except OSError:
    pass
if holder is None:
    sys.exit(1)
while os.getppid() == parent:
    time.sleep(%s)
for _ in range(100):
    shutil.rmtree(holder, ignore_errors=True)
    if not os.path.exists(holder):
        break
    time.sleep(%s)
""" % (WATCH_SECONDS, WATCH_SECONDS)

# Runs as `python -I -c WATCHER <id> <checker pid>`: the test's session leader. It runs the test and, once the
# checker is gone, kills its whole session.
WATCHER = """
import os, signal, subprocess, sys, threading, time
parent = int(sys.argv[2])
def watch():
    while os.getppid() == parent:
        time.sleep(%s)
    os.killpg(0, signal.SIGKILL)
threading.Thread(target=watch, daemon=True).start()
sys.exit(subprocess.Popen([sys.executable, "-m", "unittest", sys.argv[1]]).wait())
""" % WATCH_SECONDS

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


def case_ids(source: str | bytes) -> frozenset[str]:
    """The `<Class>.<method>` ids of the test methods of one Python file's text or bytes."""
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

    def run_git(*args: str, index: str | None = None) -> "subprocess.CompletedProcess[bytes]":
        return subprocess.run(["git", *args], capture_output=True, stdin=subprocess.DEVNULL, timeout=GIT_SECONDS,
                              env={**env, "GIT_INDEX_FILE": index} if index else env)
    return run_git


def _read(run_git: RunGit, worktree: str, revision: str, path: str) -> bytes | None:
    """The blob of `path` at `revision`; None when the revision has no such path; an unreadable blob raises."""
    listed = run_git("-C", worktree, "ls-tree", "-z", "--name-only", revision, "--", path)
    if listed.returncode:
        raise RuntimeError(f"git ls-tree {revision} {path}: {_last_line(listed)}")
    if not listed.stdout:
        return None
    done = run_git("-C", worktree, "show", f"{revision}:{path}")
    if done.returncode:
        raise RuntimeError(f"git show {revision}:{path}: {_last_line(done)}")
    return done.stdout


def _new_tests(worktree: str, base: str, head: str, run_git: RunGit) -> tuple[list[tuple[str, str]], dict[str, bytes]]:
    """The `(path, id)` of each new test of the change, sorted by path then id, and the head blob of each file holding one."""
    done = run_git("-C", worktree, "diff", "--no-renames", "--name-only", "--diff-filter=AM", "-z", base, head)
    if done.returncode:
        raise RuntimeError(f"git diff: {_last_line(done)}")
    found: list[tuple[str, str]] = []
    blobs: dict[str, bytes] = {}
    for path in sorted(name for name in done.stdout.decode(errors="replace").split("\0") if name.endswith(".py")):
        text = _read(run_git, worktree, head, path)
        if text is None:
            raise RuntimeError(f"{path} is not in {head}")
        before = _read(run_git, worktree, base, path)
        old = case_ids(before) if before is not None else frozenset()
        module = path[:-len(".py")].replace("/", ".")
        added = sorted(case_ids(text) - old)
        if added:
            blobs[path] = text
            found.extend((path, f"{module}.{case}") for case in added)
    return found, blobs


def _tracked_inits(worktree: str, base: str, run_git: RunGit) -> set[str]:
    tracked = run_git("-C", worktree, "ls-tree", "-r", "-z", "--name-only", base)
    if tracked.returncode:
        raise RuntimeError(f"git ls-tree {base}: {_last_line(tracked)}")
    return {name for name in tracked.stdout.decode(errors="replace").split("\0")
            if name == "__init__.py" or name.endswith("/__init__.py")}


def _python_path(scratch: str, worktree: str, inherited: str, inits: set[str]) -> str:
    taken = set(os.listdir(scratch))
    roots: dict[str, set[str]] = {}
    for name in inits:
        package = os.path.dirname(name)
        parent = os.path.dirname(package)
        if parent and os.path.join(parent, "__init__.py") not in inits:
            roots.setdefault(parent, set()).add(os.path.relpath(package, parent).split(os.sep)[0])
    # A root whose package shares a name with a top-level entry of the scratch root would shadow it
    # (a regular package beats a namespace directory whatever the path order), so the scratch root's own
    # names stay ahead of every added root.
    roots = {root: names for root, names in roots.items() if not names & taken}
    run = os.path.realpath(worktree)
    kept = [entry for entry in inherited.split(os.pathsep)
            if entry and os.path.realpath(entry) != run and not os.path.realpath(entry).startswith(run + os.sep)]
    return os.pathsep.join([scratch, *(os.path.join(scratch, root) for root in sorted(roots)), *kept])


def _write(root: str, path: str, data: bytes) -> None:
    """Write `data` at `path` under `root`, refusing a path that passes through a symlink."""
    parts = path.split("/")
    current = root
    for part in parts[:-1]:
        current = os.path.join(current, part)
        if os.path.islink(current):
            raise RuntimeError(f"{path} passes through the symlink {os.path.relpath(current, root)} of the merge base")
        if not os.path.isdir(current):
            os.mkdir(current)
    descriptor = os.open(os.path.join(current, parts[-1]), os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o644)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(data)


def _checkout(worktree: str, holder: str, tree: str, blobs: Mapping[str, bytes], run_git: RunGit) -> None:
    """A fresh checkout of the merge base at `tree` with the head version of each new-test file over it."""
    shutil.rmtree(tree, ignore_errors=True)
    done = run_git("-C", worktree, "checkout-index", "-a", "-f", f"--prefix={tree}/", index=os.path.join(holder, "index"))
    if done.returncode:
        raise OSError(f"git checkout-index: {_last_line(done)}")
    for path, data in sorted(blobs.items()):
        _write(tree, path, data)
    for top in sorted({path.split("/")[0] for path in blobs if "/" in path}):
        if not os.path.exists(os.path.join(tree, top, "__init__.py")):
            _write(tree, f"{top}/__init__.py", b"")


def _guard(scratch_root: str | None) -> tuple["subprocess.Popen[str]", str]:
    """Start the guard of the scratch directory and return it with the directory it made."""
    guard = subprocess.Popen(
        [sys.executable, "-I", "-c", GUARD, str(os.getpid()), scratch_root or tempfile.gettempdir()],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
        start_new_session=True)
    line = guard.stdout.readline().strip() if guard.stdout else ""
    if not line or line.startswith("!"):
        guard.wait()
        raise OSError(line[1:] or "the scratch guard exited without making a directory")
    return guard, line


def _passes(identifier: str, scratch: str, env: Mapping[str, str], test_seconds: float) -> bool:
    process = subprocess.Popen(
        [sys.executable, "-I", "-c", WATCHER, identifier, str(os.getpid())], cwd=scratch, env=dict(env),
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


def check(worktree: str, integration_branch: str, *, environ: Mapping[str, str], scratch_root: str | None,
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
        found, blobs = _new_tests(worktree, result["base"], result["head"], run_git)
        result["new_tests"] = [identifier for _, identifier in found]
        if found:
            _run_in_scratch(worktree, result, found, blobs, run_git, environ, scratch_root,
                            test_seconds, budget_seconds, started)
    except Exception as error:
        result["reason"] = f"the check failed: {type(error).__name__}: {error}"
    return result


def _run_in_scratch(worktree: str, result: dict, found: list[tuple[str, str]], blobs: Mapping[str, bytes],
                    run_git: RunGit, environ: Mapping[str, str], scratch_root: str | None, test_seconds: float,
                    budget_seconds: float, started: float) -> None:
    guard = holder = None
    try:
        try:
            guard, holder = _guard(scratch_root)
            done = run_git("-C", worktree, "read-tree", result["base"], index=os.path.join(holder, "index"))
            if done.returncode:
                raise OSError(f"git read-tree: {_last_line(done)}")
        except (OSError, subprocess.SubprocessError) as error:
            result["reason"] = f"the scratch worktree could not be made: {error}"
            return
        tree = os.path.join(holder, "tree")
        inits = _tracked_inits(worktree, result["base"], run_git)
        env = {name: value for name, value in environ.items() if name not in REPOSITORY_ENV}
        env["PYTHONPYCACHEPREFIX"] = os.path.join(holder, "pycache")
        for ran, (_, identifier) in enumerate(found):
            if time.monotonic() - started >= budget_seconds:
                result["reason"] = (f"the check ran out of its {budget_seconds:g} s budget "
                                    f"after {ran} of {len(found)} new tests")
                break
            _checkout(worktree, holder, tree, blobs, run_git)
            env["PYTHONPATH"] = _python_path(tree, worktree, environ.get("PYTHONPATH", ""), inits)
            try:
                passed = _passes(identifier, tree, env, test_seconds)
            except OSError as error:
                result["reason"] = f"a test could not be started: {error}"
                break
            if passed:
                result["still_passing"].append(identifier)
    except Exception as error:
        result["reason"] = f"the check failed: {type(error).__name__}: {error}"
    finally:
        if holder is not None:
            _remove(holder, result)
        if guard is not None:
            guard.kill()
            guard.wait()
            if guard.stdout:
                guard.stdout.close()


def _remove(holder: str, result: dict) -> None:
    problem = ""
    try:
        shutil.rmtree(holder)
    except FileNotFoundError:
        pass
    except OSError as error:
        problem = f"{type(error).__name__}: {error}"
        shutil.rmtree(holder, ignore_errors=True)
    if problem:
        message = f"the scratch worktree {holder} could not be removed: {problem}"
        result["reason"] = f"{result['reason']} {message}".strip()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="revert-check", description=__doc__)
    parser.add_argument("--worktree-path", required=True)
    parser.add_argument("--integration-branch", required=True)
    args = parser.parse_args(argv)
    result = check(args.worktree_path, args.integration_branch, environ=os.environ,
                   scratch_root=os.environ.get(SCRATCH_ENV) or None)
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
