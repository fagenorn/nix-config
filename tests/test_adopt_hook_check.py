"""The verify check that an adoption installed a project's missing git hooks and its commit ran them.

Run: just agent-workflow-tests
"""
import contextlib
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent_tools.project_contract import agent_platform
from agent_tools.verification import adopt_hook_check
from tests.test_verify_checks import committed_mode

TIER = "integration"  # it builds a sandbox git repository and runs git

ROOT = Path(__file__).resolve().parents[1]
WRAPPER = "home/common/verify-pending/checks/adopt-hook-install"
MARKER = "needs-dev-shell"
T = 1700000000
MET = {
    "hook_install": {"installed": ["pre-commit"]},
    "commit_output": {
        "hook": None, "exit": None,
        "lines": ["git-hooks.nix: updating /x repo", "needs-dev-shell....Passed"],
    },
}


class AdoptHookCheckTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name) / "home"
        self.home.mkdir()
        self.repo = Path(tmp.name) / "repo"
        self.repo.mkdir()
        env = mock.patch.dict(os.environ, {
            "HOME": str(self.home), "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
        })
        env.start()
        self.addCleanup(env.stop)
        commit_env = {
            **os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com",
            "GIT_COMMITTER_DATE": f"@{T} +0000", "GIT_AUTHOR_DATE": f"@{T} +0000",
        }
        for args in (["init", "-q"], ["commit", "-q", "--allow-empty", "--no-gpg-sign", "-m", "x"]):
            subprocess.run(["git", "-C", str(self.repo), *args], check=True, env=commit_env,
                           capture_output=True)
        self.sha = subprocess.run(["git", "-C", str(self.repo), "rev-parse", "HEAD"], check=True,
                                  capture_output=True, text=True).stdout.strip()

    def store(self, name, verification, mtime):
        directory = agent_platform.state_root() / "adopt" / "plans"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{name}.json"
        path.write_text(json.dumps({"plan": {"plan_id": "sha256:" + name}, "verification": verification}))
        os.utime(path, (mtime, mtime))
        return path

    def run_main(self, *argv):
        out = io.StringIO()
        before = os.getcwd()
        os.chdir(self.repo)
        try:
            with contextlib.redirect_stdout(out):
                code = adopt_hook_check.main(list(argv))
        finally:
            os.chdir(before)
        return code, out.getvalue()

    def check(self, marker=MARKER):
        return self.run_main("--since", self.sha, "--marker", marker)

    def test_a_plan_stored_after_the_commit_whose_output_carries_the_hook_marker_is_met(self):
        self.store("a" * 64, MET, T + 60)
        code, out = self.check()
        self.assertEqual(code, 0)
        self.assertEqual(out, json.dumps({
            "installed": ["pre-commit"], "lines": MET["commit_output"]["lines"], "marker": MARKER,
            "plan_id": "sha256:" + "a" * 64, "status": "met",
        }, sort_keys=True) + "\n")

    def test_a_plan_whose_commit_output_lacks_the_marker_does_not_count(self):
        lines = ["git-hooks.nix: updating /x repo", "Running tasks"]
        self.store("a" * 64, {**MET, "commit_output": {"hook": None, "exit": None, "lines": lines}}, T + 60)
        code, out = self.check()
        self.assertEqual((code, json.loads(out)), (75, {"status": "waiting"}))

    def test_a_plan_stored_before_the_commit_does_not_count(self):
        self.store("a" * 64, MET, T - 60)
        self.assertEqual(self.check()[0], 75)

    def test_a_plan_without_installed_hooks_does_not_count(self):
        self.store("a" * 64, {**MET, "hook_install": {"installed": []}}, T + 60)
        self.assertEqual(self.check()[0], 75)
        self.store("b" * 64, {"commit_output": MET["commit_output"]}, T + 60)
        self.assertEqual(self.check()[0], 75)

    def test_no_plan_directory_is_waiting_and_bad_arguments_are_errors(self):
        self.assertEqual(self.check()[0], 75)
        for argv in (["--since", "nothex", "--marker", MARKER],
                     ["--since", "HEAD", "--marker", MARKER],
                     ["--since", self.sha, "--marker", ""],
                     ["--since", self.sha, "--marker", "a\nb"],
                     ["--since", "0" * 40, "--marker", MARKER]):
            with self.subTest(argv=argv):
                code, out = self.run_main(*argv)
                self.assertEqual(code, 2)
                self.assertEqual(json.loads(out)["status"], "error")
        directory = agent_platform.state_root() / "adopt" / "plans"
        directory.mkdir(parents=True)
        bad = directory / "bad.json"
        bad.write_text("{not json")
        os.utime(bad, (T + 90, T + 90))
        self.store("a" * 64, MET, T + 60)
        self.assertEqual(self.check()[0], 0)

    def test_the_wrapper_is_committed_executable_and_runs_the_module(self):
        self.assertEqual(committed_mode(WRAPPER), "100755")
        last = (ROOT / WRAPPER).read_text().splitlines()[-1]
        self.assertEqual(last, 'PYTHONPATH=python exec python3 -m agent_tools.verification.adopt_hook_check "$@"')


if __name__ == "__main__":
    unittest.main()
