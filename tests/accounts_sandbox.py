"""Module fixture that keeps launcher-running tests off the real accounts directory (#1027).

The rule: while a covered test module runs, HOME, CLAUDE_ACCOUNTS_DIR and
CLAUDE_CONFIG_DIR in `os.environ` itself point under one fresh temporary root, so a
test that drops or replaces an environment (the launcher then inherits the process
environment) lands in the sandbox, never in the owner's real `~/.claude-accounts`.

Contract:
- `setUpModule` / `tearDownModule`: bind both names in a test module by import.
  Calls nest by a depth count: only the first set-up makes the root and saves the
  variables, only the matching last tear-down restores them (an unset one stays
  unset) and removes the root. A tear-down at depth 0 does nothing.
- `os.environ` is mutated in place, never rebound: the console modules hold that
  object as their `environ` default, and `putenv` reaches children started with
  `env=None`.
- `root()` is the active sandbox root, None when no fixture is active.
- `ORIGINAL` is each variable's value when this module was first imported.
  `real_accounts_dirs()` is built from `ORIGINAL` and `pwd`, never from the current
  `os.environ`, so it names the real directories even while a fixture is active.
- `real_environment()` is `os.environ` with the three variables put back to `ORIGINAL`
  (removed when they were unset): the environment a fault-injected child starts with.
- `accounts_snapshot(path)` records an accounts directory's structure, never its
  contents, and never follows a link or opens a file: `.` and every root entry as
  `link:<target>`, `dir:<mode>`, `file:<mode>` or `other`; each `profiles/<n>`; and per
  profile directory its shared entries (`capacity_check.SHARED`) and `.claude.json`
  where they exist. `switch/` and launcher transients (`TRANSIENT_PREFIXES`,
  `TRANSIENT_NAMES`) are not listed. A missing path is `{".": "absent"}`.
- `overlaps(writable, protected)`: True when a real-path-resolved writable path equals,
  contains or lies under a resolved protected one (a link is judged by its target).
- `sealed_argv(argv, writable, protected)`: `argv` run under bwrap with the whole
  filesystem read-only, a private `/tmp` and only the writable paths bound writable;
  nothing is mounted at a protected path. None when a writable path overlaps a
  protected one (before bwrap is looked up), or bwrap is missing or its probe fails.
- `isolated_argv(argv, writable, protected)`: fail closed. The sealed argv when there
  is one; else None when any protected path exists (`lexists`); else, only when
  `CI == "true"`, the bare argv; else None.
"""

from __future__ import annotations

import os
import pwd
import shutil
import stat
import subprocess
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

VARIABLES: tuple[str, ...] = ("HOME", "CLAUDE_ACCOUNTS_DIR", "CLAUDE_CONFIG_DIR")
ORIGINAL: dict[str, str | None] = {name: os.environ.get(name) for name in VARIABLES}

TRANSIENT_PREFIXES: tuple[str, ...] = ("bindings.tsv.tmp.",)
TRANSIENT_NAMES: tuple[str, ...] = ("bindings.tsv.lock",)

_depth = 0
_root: Path | None = None
_saved: dict[str, str | None] = {}


def root() -> Path | None:
    return _root


def real_accounts_dirs() -> list[Path]:
    candidates: list[str] = []
    if ORIGINAL["CLAUDE_ACCOUNTS_DIR"]:
        candidates.append(ORIGINAL["CLAUDE_ACCOUNTS_DIR"])
    if ORIGINAL["HOME"]:
        candidates.append(ORIGINAL["HOME"] + "/.claude-accounts")
    candidates.append(pwd.getpwuid(os.getuid()).pw_dir + "/.claude-accounts")
    dirs: list[Path] = []
    for candidate in candidates:
        path = Path(os.path.abspath(candidate))
        if path not in dirs:
            dirs.append(path)
    return dirs


def setUpModule() -> None:
    global _depth, _root, _saved
    _depth += 1
    if _depth != 1:
        return
    sandbox = Path(tempfile.mkdtemp(prefix="accounts-sandbox-")).resolve()
    (sandbox / "home").mkdir()
    _saved = {name: os.environ.get(name) for name in VARIABLES}
    os.environ["HOME"] = str(sandbox / "home")
    os.environ["CLAUDE_ACCOUNTS_DIR"] = str(sandbox / "accounts")
    os.environ["CLAUDE_CONFIG_DIR"] = str(sandbox / "config")
    _root = sandbox


def tearDownModule() -> None:
    global _depth, _root, _saved
    if _depth == 0:
        return
    _depth -= 1
    if _depth != 0:
        return
    for name, value in _saved.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value
    if _root is not None:
        shutil.rmtree(_root, ignore_errors=True)
    _root = None
    _saved = {}


def real_environment() -> dict[str, str]:
    env = dict(os.environ)
    for name in VARIABLES:
        if ORIGINAL[name] is None:
            env.pop(name, None)
        else:
            env[name] = ORIGINAL[name]
    return env


def _describe(path: str) -> str:
    mode = os.lstat(path).st_mode
    if stat.S_ISLNK(mode):
        return "link:" + os.readlink(path)
    if stat.S_ISDIR(mode):
        return f"dir:{stat.S_IMODE(mode):o}"
    if stat.S_ISREG(mode):
        return f"file:{stat.S_IMODE(mode):o}"
    return "other"


def _is_real_dir(path: str) -> bool:
    return stat.S_ISDIR(os.lstat(path).st_mode)


def accounts_snapshot(path: Path) -> dict[str, str]:
    from agent_tools.console import capacity_check

    root_path = os.fspath(path)
    try:
        os.lstat(root_path)
    except FileNotFoundError:
        return {".": "absent"}
    snap = {".": _describe(root_path)}
    if not _is_real_dir(root_path):
        return snap
    for name in sorted(os.listdir(root_path)):
        if name in TRANSIENT_NAMES or name.startswith(TRANSIENT_PREFIXES):
            continue
        snap[name] = _describe(os.path.join(root_path, name))
    profiles = os.path.join(root_path, "profiles")
    if os.path.lexists(profiles) and _is_real_dir(profiles):
        for name in sorted(os.listdir(profiles)):
            entry = os.path.join(profiles, name)
            snap[f"profiles/{name}"] = _describe(entry)
            if not _is_real_dir(entry):
                continue
            for shared in (*capacity_check.SHARED, ".claude.json"):
                if os.path.lexists(os.path.join(entry, shared)):
                    snap[f"profiles/{name}/{shared}"] = _describe(os.path.join(entry, shared))
    return snap


def overlaps(writable: Iterable[Path], protected: Iterable[Path]) -> bool:
    resolved_protected = [os.path.realpath(str(p)) for p in protected]
    for w in (os.path.realpath(str(w)) for w in writable):
        for p in resolved_protected:
            if os.path.commonpath([w, p]) in (w, p):
                return True
    return False


def sealed_argv(
    argv: Sequence[str],
    writable: Sequence[Path],
    protected: Iterable[Path],
    *,
    which=shutil.which,
    run=subprocess.run,
) -> list[str] | None:
    if overlaps(writable, protected):
        return None
    bwrap = which("bwrap")
    if bwrap is None:
        return None
    binds: list[str] = []
    for w in writable:
        real = os.path.realpath(str(w))
        binds += ["--bind", real, real]
    seal = ["--ro-bind", "/", "/", "--dev", "/dev", "--tmpfs", "/tmp", *binds,
            "--setenv", "TMPDIR", "/tmp"]
    try:
        probe = run([bwrap, *seal, "true"], stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10,
                    check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if probe.returncode != 0:
        return None
    return [bwrap, *seal, "--", *argv]


def isolated_argv(
    argv: Sequence[str],
    writable: Sequence[Path],
    protected: Iterable[Path],
    *,
    which=shutil.which,
    run=subprocess.run,
    environ: Mapping[str, str] = os.environ,
) -> list[str] | None:
    protected = list(protected)
    if overlaps(writable, protected):
        return None
    sealed = sealed_argv(argv, writable, protected, which=which, run=run)
    if sealed is not None:
        return sealed
    if any(os.path.lexists(str(p)) for p in protected):
        return None
    if environ.get("CI") == "true":
        return list(argv)
    return None
