"""Shared portable fixtures for the retained review suites (issue 234 D8, D12, D17).

Everything here runs real Git in temporary directories: repositories with a
hermetic identity and fixed dates, optional SSH-signed commits from an
ephemeral key, a hostile Git configuration, a read-only preservation snapshot
and the source-tree budget authority. It declares no TestCase, so it is
support rather than a suite and is not listed as one.
"""

import hashlib
import os
import subprocess
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1]

_IDENTITY = {
    "GIT_AUTHOR_NAME": "Fixture", "GIT_AUTHOR_EMAIL": "fixture@example.test",
    "GIT_COMMITTER_NAME": "Fixture", "GIT_COMMITTER_EMAIL": "fixture@example.test",
    "GIT_AUTHOR_DATE": "2026-01-01T00:00:00+0000",
    "GIT_COMMITTER_DATE": "2026-01-01T00:00:00+0000",
    # The user's global and system configuration (signing keys, hooks, rename
    # settings) never reaches a fixture; tests add hostility explicitly.
    "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
}

_HOSTILE = (("diff.renames", "copies"), ("diff.renameLimit", "1"), ("core.quotePath", "false"),
            ("diff.noprefix", "true"), ("diff.mnemonicPrefix", "true"), ("color.ui", "always"),
            ("diff.external", "false"))
HOSTILE_GIT_ENV = {"GIT_CONFIG_COUNT": str(len(_HOSTILE))}
for _n, (_key, _value) in enumerate(_HOSTILE):
    HOSTILE_GIT_ENV[f"GIT_CONFIG_KEY_{_n}"] = _key
    HOSTILE_GIT_ENV[f"GIT_CONFIG_VALUE_{_n}"] = _value


def git(repo, *args, env=None, input=None) -> str:
    """Run `git -C repo args` hermetically and return stripped stdout text."""
    merged = dict(os.environ, **_IDENTITY, **(env or {}))
    return subprocess.run(["git", "-C", str(repo), *args], env=merged, input=input,
                          check=True, capture_output=True, text=True).stdout.strip()


def init_repo(tmp) -> Path:
    """A fresh repository at `tmp/repo` that never signs unless asked to."""
    repo = Path(tmp) / "repo"
    repo.mkdir(parents=True)
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "commit.gpgsign", "false")
    return repo


def commit_files(repo, files, message, *, sign_key=None) -> str:
    """Write (bytes) or delete (None) each path, commit all of them, return the commit.

    With `sign_key`, the commit is SSH-signed by that private key file.
    """
    repo = Path(repo)
    for path, data in files.items():
        target = repo / path
        if data is None:
            git(repo, "rm", "-q", "--", path)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        git(repo, "add", "-f", "--", path)
    signing = [] if sign_key is None else [
        "-c", "gpg.format=ssh", "-c", f"user.signingkey={sign_key}", "-c", "commit.gpgsign=true"]
    git(repo, *signing, "commit", "-q", "--allow-empty", "-m", message)
    return git(repo, "rev-parse", "HEAD")


def ssh_signer(tmp) -> tuple[Path, bytes]:
    """An ephemeral ed25519 key under `tmp` and its allowed-signers line."""
    key = Path(tmp) / "signer"
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "fixture",
                    "-f", str(key)], check=True, capture_output=True)
    public = key.with_suffix(".pub").read_bytes().split()
    return key, b"fixture@example.test " + public[0] + b" " + public[1] + b"\n"


def snapshot(repo) -> tuple:
    """Refs, index, status and every file's content digest, `.git` included.

    Git reads run with optional locks disabled, so collecting it writes nothing.
    """
    repo = Path(repo)
    env = {"GIT_OPTIONAL_LOCKS": "0"}
    refs = git(repo, "for-each-ref", "--format=%(objectname) %(refname)", env=env)
    index = hashlib.sha256(git(repo, "ls-files", "--stage", "-z", env=env).encode()).hexdigest()
    status = git(repo, "status", "--porcelain=v2", "-z", "--untracked-files=all", env=env)
    files = []
    for root, dirs, names in os.walk(repo):
        dirs.sort()
        for name in names:
            path = Path(root) / name
            data = os.readlink(path).encode() if path.is_symlink() else path.read_bytes()
            files.append((path.relative_to(repo).as_posix(), hashlib.sha256(data).hexdigest()))
    return refs, index, status, tuple(sorted(files))


def source_budget_env(tmp) -> dict:
    """An environment whose `artifact-budget` is this source tree's helper and policy.

    Tests call `describe("review-package")` under
    `patch.dict(os.environ, env, clear=True)`: the installed helper lacks
    `describe` until a switch.
    """
    home = Path(tmp) / "budget-home"
    (home / ".agents/lib/python").mkdir(parents=True)
    (home / ".agents/share").mkdir(parents=True)
    legacy = SOURCE / "home/common/agent-skills"
    (home / ".agents/lib/python/artifact_budget.py").symlink_to(legacy / "scripts/artifact_budget.py")
    (home / ".agents/share/artifact-budget-policy.json").symlink_to(legacy / "artifact-budget-policy.json")
    return dict(os.environ, HOME=str(home), PYTHONPATH=str(SOURCE / "python"),
                PATH=str(legacy / "scripts") + os.pathsep + os.environ["PATH"])
