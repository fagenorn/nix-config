"""Module-interface seam for agent_tools.siblings (#177 D5, D9, D15)."""

import subprocess
import sys
import types
import unittest
from unittest import mock

from agent_tools import siblings


class SiblingArgvTest(unittest.TestCase):
    def argv_under(self, isolated):
        with mock.patch.object(siblings.sys, "flags",
                               types.SimpleNamespace(isolated=isolated)):
            return siblings.sibling_argv("resolve_project")

    def test_a_non_isolated_caller_runs_its_sibling_without_isolation(self):
        self.assertEqual(self.argv_under(0),
                         [sys.executable, "-m", "agent_tools.resolve_project"])

    def test_an_isolated_caller_runs_its_sibling_isolated(self):
        self.assertEqual(self.argv_under(1),
                         [sys.executable, "-I", "-m", "agent_tools.resolve_project"])

    def test_the_argv_runs_the_named_package_module(self):
        completed = subprocess.run(
            [*siblings.sibling_argv("diff_scope"), "--help"],
            capture_output=True, text=True, timeout=60, check=False)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertTrue(completed.stdout.startswith("usage: diff-scope "),
                        completed.stdout[:200])


if __name__ == "__main__":
    unittest.main()
