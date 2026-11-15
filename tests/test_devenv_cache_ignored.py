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


def _status_porcelain(root: Path) -> list[str]:
    # Isolate git from the host's global and system ignore rules, so only this
    # repository's own `.gitignore` can hide a path.
    env = {
        **os.environ,
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
    }
    out = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain", "--untracked-files=all"],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    ).stdout
    return out.splitlines()


class DevenvCacheIgnoredTests(unittest.TestCase):
    def test_devenv_cache_is_not_listed_by_git_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(
                ["git", "init", "--quiet", str(root)], check=True, capture_output=True
            )
            (root / ".gitignore").write_bytes((REPO_ROOT / ".gitignore").read_bytes())
            (root / ".devenv").mkdir()
            (root / ".devenv" / "state").write_text("cache\n")
            (root / "devenv.lock").write_text("{}\n")
            (root / "stray.txt").write_text("not ignored\n")

            listed = _status_porcelain(root)

        # The control: an unrelated untracked file is still reported, so an
        # empty result cannot come from git failing to look at the tree.
        self.assertIn("?? stray.txt", listed)
        self.assertEqual(
            [line for line in listed if "devenv" in line],
            [],
            f"devenv cache shows in git status: {listed}",
        )


if __name__ == "__main__":
    unittest.main()
