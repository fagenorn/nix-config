"""`revert-check`: the new tests of a change that still pass at the merge base, as a platform command.

`revert-check --worktree-path <abs path> --integration-branch <name>` (both required; a usage error is
exit 2) prints exactly one compact JSON line, keys sorted, and exits 0 whatever it finds:
`{base, head, new_tests, reason, still_passing, verdict}`. `verdict` is always `ok`; `base` is the
merge base of the worktree's `HEAD` and `refs/remotes/origin/<branch>` and `head` is the worktree's
`HEAD` (each `""` when unread); `new_tests` lists the change's new test ids sorted by file path then
id; `still_passing` is the subset whose run exited 0, in the same order; `reason` is `""` when every
new test ran, else one sentence saying why the check did not run or did not finish. The result is
information for a reviewer and never blocks. The decision is ADR-delivery-025.

A new test is a `test*` method (`def` or `async def`) directly in a top-level class whose bases reach
a base named `TestCase` (a bare name or an attribute `x.TestCase`) through classes defined in the
same file or imported into it with `from <module> import <Name>` (followed, at the revision read, into the file
`<module>` names, relative to the importing file's directory, a directory above it or the root; a file it cannot
find ends that branch). Its id is `<module>.<Class>.<method>`, `<module>` being the file's path relative to the
worktree root with `.py` dropped and `/` replaced by `.`. It is new when the file at the merge base
(absent counts as empty) lacks `<Class>.<method>`. Only `.py` files changed `A` or `M` between the
merge base and `HEAD` (`git diff --no-renames`) are read, as the blob bytes (so a byte-order mark or a
coding declaration is the parser's). A blob git cannot read ends the check with its error in `reason`.
A change with no new test returns empty lists and `reason ""` and creates nothing.

The check makes a scratch directory with `tempfile.mkdtemp(prefix="revert-check-", dir=<scratch
root>)`, `$REVERT_CHECK_SCRATCH` or else the system temporary directory, made by a guard process in a
session of its own that removes it again once the checker is gone, whenever that happens (an engine stop
kills only the checker's group). The directory holds a checkout of the
merge base (`read-tree` into a private index file, then `checkout-index` into a directory made first, so a
merge base with no file works; no worktree is registered, so no repository-wide `git worktree` command runs).
The checkout is a repository of its own (`git init`, the merge base's index, a detached `HEAD` at the merge
base and the run repository's object directory as an alternate), so a test may run `git` there and the run's
repository is only read. A symlink of the merge base that leads into the run's worktree is pointed at the
same path of the checkout, so a test never writes through it into the run's worktree. Per test there is
a fresh checkout with the `HEAD`
version (bytes) of each file holding a new test written over it, nothing else of the change, so no
test sees what an earlier one left. A write refuses a path that passes through a symlink of the merge
base (it would lead out of the scratch), and a new test's top-level directory that holds no
`__init__.py` gets an empty one, so a regular package of that name on the inherited `PYTHONPATH` cannot
shadow it. Each new test then runs once as `python -m unittest <id>` with the scratch checkout as the
working directory, no standard stream inherited, in its own session behind a small watcher that kills
the session when the checker dies; the guard and the watcher are given the checker's pid, so a checker
that dies before they start is noticed too; the group is also killed after `TEST_SECONDS`. Exit 0 is still passing, any other
exit or a timeout is not; a timeout adds `new tests stopped at the <n> s limit: <ids>` to `reason`, so a test
the limit interrupted is told from one whose assertion failed. The tests' `PYTHONPATH` is the checkout, then `<checkout>/<D>` for each
distinct non-empty `D` that is the parent of a top-level package tracked at the merge base (a tracked
`<pkg>/__init__.py` whose parent directory holds no `__init__.py`), sorted, then the inherited entries
whose real path is not the run's worktree or inside it, so the reverted source is what a test
imports; `PYTHONPYCACHEPREFIX` is the scratch directory's own, so no bytecode lands elsewhere. A top-level
directory of the checkout that shares its name with a package of such a `<D>` and holds no `__init__.py`
gets an empty one too (so it stays ahead of that `<D>`) and `<D>` stays on the path. The git variables of
`engine_shell.REPOSITORY_ENV` are dropped from every child, and no hook of the repository runs
(`core.hooksPath=/dev/null` on every git command).

The scratch directory is always removed, a directory below it that is not writable included (the guard names
it in hex, so no byte of the path can end the line, and the checker deletes only a path of the shape the
guard makes); a removal that fails adds `the scratch worktree <path, as Python writes it> could not be
removed: <error>` to `reason` and leaves the guard alive to retry. The run's worktree, index, refs and
worktree list are never written: the only git commands run against it are reads.

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
import inspect
import json
import os
import posixpath
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
TEST_PYTHON = sys.executable
HOLDER_PREFIX = "revert-check-"


def force_remove(path):
    """Remove `path` and all below it, making each directory below it writable first; what stays raises."""
    pending = [] if os.path.islink(path) else [path]
    while pending:
        directory = pending.pop()
        try:
            os.chmod(directory, 0o700)
            with os.scandir(directory) as entries:
                pending.extend(entry.path for entry in entries if entry.is_dir(follow_symlinks=False))
        except OSError:
            pass
    shutil.rmtree(path)


# Both helpers take the checker's pid in argv rather than reading their parent's: a checker stopped before the
# helper's interpreter has started leaves the helper a parent that is already init, and the pid in argv still
# tells them it is gone.

# Runs as `python -I -c GUARD <checker pid> <scratch root>`, in a session of its own (an engine stop kills only
# the checker's group): it makes the scratch directory, tells the checker its path on one line, the path's bytes
# in hex so no byte of it can end the line (`!<error>` when it cannot be made) and, once the checker is gone,
# removes the directory again until it is gone, so a stop at any point of the scratch's life leaves nothing behind.
GUARD = "import os, shutil, sys, tempfile, time\n" + inspect.getsource(force_remove) + """
parent = int(sys.argv[1])
try:
    holder = os.path.realpath(tempfile.mkdtemp(prefix=%r, dir=sys.argv[2]))
    line = os.fsencode(holder).hex()
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
    try:
        force_remove(holder)
    except OSError:
        pass
    if not os.path.exists(holder):
        break
    time.sleep(%s)
""" % (HOLDER_PREFIX, WATCH_SECONDS, WATCH_SECONDS)

# Runs as `python -I -c WATCHER <id> <checker pid> [<python>]`: the test's session leader. It runs the test
# (`<python> -m unittest <id>`, with no standard stream of the test shared with it) and, once the checker is gone,
# kills its whole session. When it cannot start the test it writes why to its own standard error and exits 1, and
# nothing else of it ever reaches that stream, so a message there is a launch error and never a test's outcome.
WATCHER = """
import os, signal, subprocess, sys, threading, time
parent = int(sys.argv[2])
def watch():
    while os.getppid() == parent:
        time.sleep(%s)
    os.killpg(0, signal.SIGKILL)
threading.Thread(target=watch, daemon=True).start()
try:
    child = subprocess.Popen([sys.argv[3] if len(sys.argv) > 3 else sys.executable, "-m", "unittest", sys.argv[1]],
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
except OSError as error:
    sys.stderr.write(str(error).replace("\\n", " ") + "\\n")
    sys.exit(1)
sys.exit(child.wait())
""" % WATCH_SECONDS

RunGit = Callable[..., "subprocess.CompletedProcess[bytes]"]


def _testcase_classes(classes: Mapping[str, ast.ClassDef], imported: set[str] = frozenset()) -> set[str]:
    """The names of the classes whose bases reach `TestCase` (or an imported name in `imported`), each visited once."""
    children: dict[str, list[str]] = {}
    found: set[str] = set()
    for name, node in classes.items():
        for base in node.bases:
            if (isinstance(base, ast.Name) and (base.id == "TestCase" or base.id in imported)) or (
                    isinstance(base, ast.Attribute) and base.attr == "TestCase"):
                found.add(name)
            elif isinstance(base, ast.Name) and base.id in classes:
                children.setdefault(base.id, []).append(name)
    pending = list(found)
    while pending:
        for child in children.get(pending.pop(), ()):
            if child not in found:
                found.add(child)
                pending.append(child)
    return found


Load = Callable[[str], "str | bytes | None"]


def _module_paths(path: str, module: str | None, level: int) -> list[str]:
    """The files `from <module> import ...` (with `level` leading dots) in the file `path` may name, in order."""
    parts = module.split(".") if module else []
    if not parts:
        return []
    directory = posixpath.dirname(path)
    if level:
        for _ in range(level - 1):
            directory = posixpath.dirname(directory)
        directories = [directory]
    else:
        directories = [directory]
        while directory:
            directory = posixpath.dirname(directory)
            directories.append(directory)
    stems = ["/".join(piece for piece in (base, *parts) if piece) for base in directories]
    return [name for stem in stems for name in (f"{stem}.py", f"{stem}/__init__.py")]


def _reaching(source: str | bytes, path: str, load: Load | None, memo: dict[str, set[str]]) -> set[str]:
    """The names of the classes of one file that reach `TestCase`, an imported base followed into its file."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return set()
    memo[path] = set()
    classes = {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}
    imports = {(alias.asname or alias.name): (node.module, node.level, alias.name)
               for node in tree.body if isinstance(node, ast.ImportFrom) for alias in node.names}
    bases = {base.id for node in classes.values() for base in node.bases
             if isinstance(base, ast.Name) and base.id in imports and base.id not in classes}
    imported: set[str] = set()
    for name in sorted(bases):
        module, level, original = imports[name]
        for candidate in _module_paths(path, module, level) if load else ():
            if candidate not in memo:
                text = load(candidate)
                if text is None:
                    continue
                memo[candidate] = _reaching(text, candidate, load, memo)
            if original in memo[candidate]:
                imported.add(name)
            break
    reaching = _testcase_classes(classes, imported)
    memo[path] = reaching
    return reaching


def case_ids(source: str | bytes, path: str = "", load: Load | None = None) -> frozenset[str]:
    """The `<Class>.<method>` ids of the test methods of one Python file's text or bytes.

    A base imported with `from <module> import <Name>` is followed into the file `load(<path>)` returns (None
    for a file that does not exist), `<path>` being the file's path from the repository root; without `load`
    only the classes of the file itself count."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return frozenset()
    classes = {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}
    reaching = _reaching(source, path, load, {})
    return frozenset(
        f"{name}.{member.name}"
        for name, node in classes.items() if name in reaching
        for member in node.body
        if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)) and member.name.startswith("test"))


def _last_line(done: "subprocess.CompletedProcess[bytes]") -> str:
    lines = done.stderr.decode(errors="replace").strip().splitlines()
    return lines[-1] if lines else f"git exited {done.returncode}"


def _git_runner(environ: Mapping[str, str]) -> RunGit:
    env = {name: value for name, value in environ.items() if name not in REPOSITORY_ENV}

    def run_git(*args: str, index: str | None = None) -> "subprocess.CompletedProcess[bytes]":
        # No hook of the repository runs: a hook such as post-index-change runs in the run's worktree.
        return subprocess.run(["git", "-c", "core.hooksPath=/dev/null", *args], capture_output=True, stdin=subprocess.DEVNULL, timeout=GIT_SECONDS,
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


def _loader(run_git: RunGit, worktree: str, revision: str) -> Load:
    """A `Load` of the files at `revision`, each read once."""
    cache: dict[str, bytes | None] = {}

    def load(path: str) -> bytes | None:
        if path not in cache:
            cache[path] = _read(run_git, worktree, revision, path)
        return cache[path]
    return load


def _new_tests(worktree: str, base: str, head: str, run_git: RunGit) -> tuple[list[tuple[str, str]], dict[str, bytes]]:
    """The `(path, id)` of each new test, sorted by path then id, and the head blob of each file holding one."""
    done = run_git("-C", worktree, "diff", "--no-renames", "--name-only", "--diff-filter=AM", "-z", base, head)
    if done.returncode:
        raise RuntimeError(f"git diff: {_last_line(done)}")
    found: list[tuple[str, str]] = []
    blobs: dict[str, bytes] = {}
    loaders = {revision: _loader(run_git, worktree, revision) for revision in (base, head)}
    for path in sorted(name for name in done.stdout.decode(errors="replace").split("\0") if name.endswith(".py")):
        text = _read(run_git, worktree, head, path)
        if text is None:
            raise RuntimeError(f"{path} is not in {head}")
        before = _read(run_git, worktree, base, path)
        old = case_ids(before, path, loaders[base]) if before is not None else frozenset()
        module = path[:-len(".py")].replace("/", ".")
        added = sorted(case_ids(text, path, loaders[head]) - old)
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
    # A regular package of a root beats a namespace directory of the scratch root that shares its name
    # (whatever the path order), so such a directory becomes a regular package itself, which the scratch
    # root's place ahead of every added root then keeps first. A root that cannot be kept apart (the
    # directory is a symlink of the merge base) is left out.
    usable = []
    for root in sorted(roots):
        try:
            for name in sorted(roots[root] & taken):
                directory = os.path.join(scratch, name)
                if os.path.isdir(directory) and not os.path.exists(os.path.join(directory, "__init__.py")):
                    _write(scratch, f"{name}/__init__.py", b"")
        except RuntimeError:
            continue
        usable.append(root)
    run = os.path.realpath(worktree)
    kept = [entry for entry in inherited.split(os.pathsep)
            if entry and os.path.realpath(entry) != run and not os.path.realpath(entry).startswith(run + os.sep)]
    return os.pathsep.join([scratch, *(os.path.join(scratch, root) for root in usable), *kept])


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


def _tracked_links(worktree: str, base: str, run_git: RunGit) -> list[str]:
    """The paths of the symlinks tracked at `base`."""
    tracked = run_git("-C", worktree, "ls-tree", "-r", "-z", base)
    if tracked.returncode:
        raise RuntimeError(f"git ls-tree {base}: {_last_line(tracked)}")
    entries = (entry.partition("\t") for entry in tracked.stdout.decode(errors="replace").split("\0"))
    return [name for meta, _, name in entries if meta.startswith("120000 ")]


def _object_directory(worktree: str, run_git: RunGit) -> str:
    done = run_git("-C", worktree, "rev-parse", "--path-format=absolute", "--git-path", "objects")
    if done.returncode:
        raise OSError(f"git rev-parse --git-path objects: {_last_line(done)}")
    return done.stdout.decode(errors="replace").strip()


def _confine_links(worktree: str, tree: str, links: Sequence[str]) -> None:
    """Point each symlink of the checkout that leads into the run's worktree at the same path of the checkout."""
    run = os.path.realpath(worktree)
    for name in links:
        link = os.path.join(tree, name)
        target = os.path.realpath(link)
        if target == run or target.startswith(run + os.sep):
            os.unlink(link)
            os.symlink(os.path.join(tree, os.path.relpath(target, run)), link)


def _checkout(worktree: str, holder: str, tree: str, blobs: Mapping[str, bytes], run_git: RunGit, *,
              base: str, links: Sequence[str], objects: str) -> None:
    """A fresh checkout of the merge base at `tree` with the head version of each new-test file over it.

    The checkout is a repository of its own whose index is the merge base's and whose objects are the run
    repository's, read through `objects/info/alternates`, so a test may run `git` there."""
    try:
        force_remove(tree)
    except FileNotFoundError:
        pass
    os.makedirs(tree)
    done = run_git("-C", worktree, "checkout-index", "-a", "-f", f"--prefix={tree}/", index=os.path.join(holder, "index"))
    if done.returncode:
        raise OSError(f"git checkout-index: {_last_line(done)}")
    done = run_git("init", "-q", "--template=", tree)
    if done.returncode:
        raise OSError(f"git init: {_last_line(done)}")
    shutil.copyfile(os.path.join(holder, "index"), os.path.join(tree, ".git", "index"))
    with open(os.path.join(tree, ".git", "HEAD"), "w") as handle:
        handle.write(base + "\n")
    with open(os.path.join(tree, ".git", "objects", "info", "alternates"), "wb") as handle:
        handle.write(os.fsencode(objects) + b"\n")
    _confine_links(worktree, tree, links)
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
    try:
        holder = os.fsdecode(bytes.fromhex(line))
    except ValueError:
        holder = ""
    if not os.path.isabs(holder) or not os.path.basename(holder).startswith(HOLDER_PREFIX):
        # Nothing is deleted on the strength of a path that is not the guard's own: the guard, which
        # still holds its directory, removes it once this process is gone.
        raise OSError("the scratch guard named no scratch directory")
    return guard, holder


class _TimedOut(Exception):
    """A test ran past its time limit and its session was killed."""


def _passes(identifier: str, scratch: str, env: Mapping[str, str], test_seconds: float) -> bool:
    """Whether the test exits 0; an OSError when the watcher could not start it, `_TimedOut` when it ran too long."""
    process = subprocess.Popen(
        [sys.executable, "-I", "-c", WATCHER, identifier, str(os.getpid()), TEST_PYTHON], cwd=scratch,
        env=dict(env), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        start_new_session=True)
    try:
        _, error = process.communicate(timeout=test_seconds)
    except subprocess.TimeoutExpired:
        raise _TimedOut(identifier) from None
    finally:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except OSError:
            pass
        process.wait()
        if process.stderr:
            process.stderr.close()
    if process.returncode and error.strip():
        raise OSError(error.decode(errors="replace").strip().splitlines()[-1])
    return process.returncode == 0


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
    timed_out: list[str] = []
    try:
        try:
            guard, holder = _guard(scratch_root)
            done = run_git("-C", worktree, "read-tree", result["base"], index=os.path.join(holder, "index"))
            if done.returncode:
                raise OSError(f"git read-tree: {_last_line(done)}")
            objects = _object_directory(worktree, run_git)
        except (OSError, subprocess.SubprocessError) as error:
            result["reason"] = f"the scratch worktree could not be made: {error}"
            return
        tree = os.path.join(holder, "tree")
        inits = _tracked_inits(worktree, result["base"], run_git)
        links = _tracked_links(worktree, result["base"], run_git)
        env = {name: value for name, value in environ.items() if name not in REPOSITORY_ENV}
        env["PYTHONPYCACHEPREFIX"] = os.path.join(holder, "pycache")
        for ran, (_, identifier) in enumerate(found):
            if time.monotonic() - started >= budget_seconds:
                result["reason"] = (f"the check ran out of its {budget_seconds:g} s budget "
                                    f"after {ran} of {len(found)} new tests")
                break
            _checkout(worktree, holder, tree, blobs, run_git, base=result["base"], links=links, objects=objects)
            env["PYTHONPATH"] = _python_path(tree, worktree, environ.get("PYTHONPATH", ""), inits)
            try:
                passed = _passes(identifier, tree, env, test_seconds)
            except _TimedOut:
                timed_out.append(identifier)
                continue
            except OSError as error:
                result["reason"] = f"a test could not be started: {error}"
                break
            if passed:
                result["still_passing"].append(identifier)
    except Exception as error:
        result["reason"] = f"the check failed: {type(error).__name__}: {error}"
    finally:
        if timed_out:
            message = f"new tests stopped at the {test_seconds:g} s limit: {', '.join(timed_out)}"
            result["reason"] = f"{result['reason']} {message}".strip()
        removed = True
        if holder is not None:
            removed = _remove(holder, result)
        if guard is not None:
            if removed:
                guard.kill()
            if guard.stdout:
                guard.stdout.close()
            if removed:
                guard.wait()


def _remove(holder: str, result: dict) -> bool:
    """Remove the scratch directory; False (with the reason added) when it remains, for the guard to retry."""
    problem = ""
    try:
        force_remove(holder)
    except FileNotFoundError:
        pass
    except OSError as error:
        problem = f"{type(error).__name__}: {error}"
    if problem:
        message = f"the scratch worktree {holder!r} could not be removed: {problem}"
        result["reason"] = f"{result['reason']} {message}".strip()
    return not os.path.exists(holder)


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
