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
"""

from __future__ import annotations

import os
import pwd
import shutil
import tempfile
from pathlib import Path

VARIABLES: tuple[str, ...] = ("HOME", "CLAUDE_ACCOUNTS_DIR", "CLAUDE_CONFIG_DIR")
ORIGINAL: dict[str, str | None] = {name: os.environ.get(name) for name in VARIABLES}

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
