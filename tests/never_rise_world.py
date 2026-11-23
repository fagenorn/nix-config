"""The temporary git world the never-rise suites share: a fixture environment, a repository and its commits."""

import os
import subprocess
from pathlib import Path

from agent_tools.delivery import never_rise


def fixture_env(extra=None):
    env = {k: v for k, v in os.environ.items() if k not in never_rise.SELECTION_VARIABLES}
    env.update({
        "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
        "GIT_AUTHOR_NAME": "fixture", "GIT_COMMITTER_NAME": "fixture",
        "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
        "GIT_COMMITTER_EMAIL": "fixture@example.invalid"})
    env.update(extra or {})
    return env


def git(root, *args, env=None):
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, timeout=60,
        check=True, env=env or fixture_env()).stdout


def repo(tmp):
    root = Path(tmp) / "repo"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    return root


def write(root, relative, text):
    path = Path(root) / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(text, bytes):
        path.write_bytes(text)
    else:
        path.write_text(text)


def commit_all(root, message="commit"):
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", message)


def mark_base(root):
    git(root, "update-ref", "refs/remotes/origin/main", "HEAD")
    return git(root, "rev-parse", "HEAD").strip()
