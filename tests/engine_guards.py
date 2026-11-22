"""Shared fixtures for the engine's lifecycle-guard tests (issue 1515).

Not a test module. Every guard fixture is written at `<dir>/bin/<GUARD_NAME>`,
the generated wrapper's name, so `engine_guard.locate` accepts it.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import stat
import sys
from pathlib import Path

from tests.guard_policy_world import REAL_GIT

REPO_ROOT = Path(__file__).resolve().parents[1]
GUARD_SOURCE = REPO_ROOT / "home/common/claude-code/lifecycle_guard.py"
STANDIN_GUARD = REPO_ROOT / "tests/fixtures/engine-deliver/standin_guard.py"
GUARD_NAME = "claude-bash-lifecycle-guard"


def script(path: Path, *words: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\nexec " + " ".join(shlex.quote(word) for word in words)
                    + ' "$@"\n', encoding="utf-8")
    path.chmod(0o755)
    return path


def standin_guard(directory: Path, name: str, mode: str, *words: str) -> Path:
    return script(directory / name / "bin" / GUARD_NAME,
                  sys.executable, str(STANDIN_GUARD), mode, *words)


def real_guard(directory: Path, *, owners: tuple[str, ...] = ("example",)) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    gh = directory / "gh-stub"
    gh.write_text("#!/bin/sh\nexit 64\n", encoding="utf-8")
    gh.chmod(0o755)
    derive = directory / "derive-stub"
    derive.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    derive.chmod(0o755)
    base = directory / "base-policy.json"
    base.write_text(json.dumps({
        "authorized_owners": list(owners), "integration_bases": {},
        "git_bin": REAL_GIT, "gh_bin": str(gh),
        "jq_bin": shutil.which("jq") or "/usr/bin/jq"}), encoding="utf-8")
    compiled = directory / "compiled-policy.json"
    compiled.write_text(json.dumps({"derived_repositories": {}, "derivation": None}),
                        encoding="utf-8")
    return script(directory / "bin" / GUARD_NAME, sys.executable, "-I", str(GUARD_SOURCE),
                  "--base-policy", str(base), "--policy", str(compiled),
                  "--derive-bin", str(derive))


def write_settings(home: Path, command: str, timeout: object = 30, *,
                   extra: dict | None = None) -> Path:
    path = home / ".claude" / "settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    hook = {"type": "command", "command": command, "timeout": timeout, **(extra or {})}
    path.write_text(json.dumps({"hooks": {"PreToolUse": [
        {"matcher": "Bash", "hooks": [hook]}]}}), encoding="utf-8")
    return path


RECORDER = """#!{python}
import json, os, sys
with open({log!r}, "a", encoding="utf-8") as handle:
    handle.write(json.dumps({{"argv": sys.argv[1:]}}) + "\\n")
real = {real!r}
if real:
    os.execv(real, [real, *sys.argv[1:]])
"""


def recorder(directory: Path, name: str, log: Path, real: str | None) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(RECORDER.format(python=sys.executable, log=str(log), real=real),
                    encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def payloads(log: Path) -> list[dict]:
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line]
