import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from .guard_sandbox_git import SandboxGit


class SandboxPushTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.base = Path(directory.name)
        hooks = self.base / "host-hooks"
        hooks.mkdir()
        hook = hooks / "pre-push"
        hook.write_text("#!/bin/sh\necho host pre-push hook refuses >&2\nexit 1\n",
                        encoding="utf-8")
        hook.chmod(0o755)
        host_config = self.base / "host-gitconfig"
        host_config.write_text(f"[core]\n\thooksPath = {hooks}\n", encoding="utf-8")
        patch = mock.patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": str(host_config),
                                             "CLAUDECODE": "1"})
        patch.start()
        self.addCleanup(patch.stop)
        self.remote = self.base / "remote.git"
        self.work = self.base / "work"
        self.work.mkdir()
        subprocess.run(["git", "init", "--quiet", "--bare", str(self.remote)],
                       check=True, capture_output=True)

    def test_the_host_hook_refuses_a_push_that_is_not_isolated(self):
        sandbox = SandboxGit(self.base)
        sandbox.git("init", "--quiet", cwd=self.work)
        sandbox.git("remote", "add", "origin", str(self.remote), cwd=self.work)
        sandbox.git("commit", "--quiet", "--allow-empty", "-m", "init", cwd=self.work)
        refused = subprocess.run(
            ["git", "push", "--quiet", "origin", "HEAD:refs/heads/topic"],
            cwd=self.work, capture_output=True, text=True, check=False)
        self.assertNotEqual(0, refused.returncode)
        self.assertIn("host pre-push hook refuses", refused.stderr)

    def test_a_sandbox_push_reaches_its_remote_past_a_refusing_host_hook(self):
        sandbox = SandboxGit(self.base)
        sandbox.git("init", "--quiet", cwd=self.work)
        sandbox.git("remote", "add", "origin", str(self.remote), cwd=self.work)
        sandbox.git("commit", "--quiet", "--allow-empty", "-m", "init", cwd=self.work)
        sandbox.push(self.work, "origin", "HEAD:refs/heads/topic")
        self.assertIn("refs/heads/topic",
                      sandbox.git("ls-remote", "--heads", "origin", "topic", cwd=self.work))


if __name__ == "__main__":
    unittest.main()
