"""A devenv ad-hoc shell's cache must not make a checkout look dirty.

`devenv -O ... shell -- ...` writes a `.devenv/` directory and a `devenv.lock`
file into the current directory. This repository has no `devenv.nix`, so both
are pure cache, and a delivery's "no uncommitted changes" check fails on them
unless the root `.gitignore` names them (issue 1070).
"""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _status_porcelain(root: Path, host_home: Path) -> list[str]:
    # Isolate git from the host's global and system config and its default
    # global ignore file ($XDG_CONFIG_HOME/git/ignore), so only this
    # repository's own `.gitignore` can hide a path.
    env = {
        **os.environ,
        "HOME": str(host_home),
        "XDG_CONFIG_HOME": str(host_home / ".config"),
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
    }
    out = subprocess.run(
        [
            "git",
            "-c",
            f"core.excludesFile={os.devnull}",
            "-C",
            str(root),
            "status",
            "--porcelain",
            "--untracked-files=all",
        ],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    ).stdout
    return out.splitlines()


def _make_checkout(root: Path, gitignore: bytes) -> None:
    subprocess.run(["git", "init", "--quiet", str(root)], check=True, capture_output=True)
    (root / ".gitignore").write_bytes(gitignore)
    (root / ".devenv").mkdir()
    (root / ".devenv" / "state").write_text("cache\n")
    (root / "devenv.lock").write_text("{}\n")
    (root / "stray.txt").write_text("not ignored\n")


def _hostile_host_home(parent: Path) -> Path:
    # A host whose default global git ignore file already hides the cache.
    home = parent / "home"
    (home / ".config" / "git").mkdir(parents=True)
    (home / ".config" / "git" / "ignore").write_text(".devenv/\ndevenv.lock\n")
    return home


class DevenvCacheIgnoredTests(unittest.TestCase):
    def test_devenv_cache_is_not_listed_by_git_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            _make_checkout(root, (REPO_ROOT / ".gitignore").read_bytes())
            listed = _status_porcelain(root, _hostile_host_home(Path(tmp)))

        # The control: an unrelated untracked file is still reported, so an
        # empty result cannot come from git failing to look at the tree.
        self.assertIn("?? stray.txt", listed)
        self.assertEqual(
            [line for line in listed if "devenv" in line],
            [],
            f"devenv cache shows in git status: {listed}",
        )

    def test_a_host_ignore_file_cannot_mask_a_missing_repo_rule(self):
        # Without the repo's rules the cache must show even though the host's
        # own ignore file names it; otherwise the test above measures the host.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            _make_checkout(root, b"")
            listed = _status_porcelain(root, _hostile_host_home(Path(tmp)))

        self.assertIn("?? .devenv/state", listed)
        self.assertIn("?? devenv.lock", listed)


if __name__ == "__main__":
    unittest.main()
