import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent_tools.delivery import comment_lint
from agent_tools.delivery.never_rise import Snapshot

from .guard_sandbox_git import SandboxGit

TIER = "integration"  # creates real git repositories and pushes between them

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
        self.host_git("init", "--quiet", "--bare", str(self.remote), cwd=self.base)

    def host_git(self, *argv, cwd, check=True):
        """Raw git as the host runs it: the simulated host config, no inherited `GIT_*` override."""
        env = {k: v for k, v in os.environ.items()
               if not k.startswith("GIT_") or k == "GIT_CONFIG_GLOBAL"}
        return subprocess.run(["git", *argv], cwd=cwd, env=env, check=check,
                              capture_output=True, text=True)

    def test_the_host_hook_refuses_a_push_that_is_not_isolated(self):
        sandbox = SandboxGit(self.base)
        sandbox.git("init", "--quiet", cwd=self.work)
        sandbox.git("remote", "add", "origin", str(self.remote), cwd=self.work)
        sandbox.git("commit", "--quiet", "--allow-empty", "-m", "init", cwd=self.work)
        refused = self.host_git("push", "--quiet", "origin", "HEAD:refs/heads/topic",
                                cwd=self.work, check=False)
        self.assertNotEqual(0, refused.returncode)
        self.assertIn("host pre-push hook refuses", refused.stderr)

    def test_the_refusal_control_ignores_the_callers_git_overrides(self):
        other = self.base / "other"
        other.mkdir()
        elsewhere = self.base / "elsewhere-hooks"
        elsewhere.mkdir()
        overrides = {"GIT_DIR": str(other), "GIT_CONFIG_COUNT": "1",
                     "GIT_CONFIG_KEY_0": "core.hooksPath",
                     "GIT_CONFIG_VALUE_0": str(elsewhere)}
        sandbox = SandboxGit(self.base)
        sandbox.git("init", "--quiet", cwd=self.work)
        sandbox.git("remote", "add", "origin", str(self.remote), cwd=self.work)
        sandbox.git("commit", "--quiet", "--allow-empty", "-m", "init", cwd=self.work)
        with mock.patch.dict(os.environ, overrides):
            refused = self.host_git("push", "--quiet", "origin", "HEAD:refs/heads/topic",
                                    cwd=self.work, check=False)
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


class SandboxSourceCommentsTest(unittest.TestCase):
    def test_the_support_module_comments_name_no_issue(self):
        path = Path(__file__).resolve().with_name("guard_sandbox_git.py")
        snapshot = Snapshot(revision="", line_counts={},
                            contents={path.name: path.read_bytes()})
        (reference, _, _) = comment_lint.enforcers("fagenorn/nix-config")
        self.assertEqual([], reference.find(snapshot))


if __name__ == "__main__":
    unittest.main()
