"""Activate reads the contract's branch and command through the core read, not the full resolve."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from agent_tools.console import activation, activation_run
from agent_tools.project_contract import resolve_project

from . import accounts_sandbox
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures

TIER = "fast"

REPO_ROOT = Path(__file__).resolve().parents[1]


class ActivationContractTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(dir=accounts_sandbox.root())).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        home = self.tmp / "home"
        (home / ".agents/share").mkdir(parents=True)
        shutil.copy(REPO_ROOT / "home/common/agent-skills/platform-manifest.json",
                    home / ".agents/share/platform-manifest.json")
        previous = os.environ["HOME"]
        os.environ["HOME"] = str(home)
        self.addCleanup(os.environ.__setitem__, "HOME", previous)

    def contract_root(self, mutate) -> Path:
        """A root carrying this repository's contract as `mutate` changes it, with its instruction sources."""
        root = self.tmp / "contract-root"
        (root / ".agents/instructions").mkdir(parents=True)
        contract = json.loads((REPO_ROOT / ".agents/project.json").read_text(encoding="utf-8"))
        mutate(contract)
        (root / ".agents/project.json").write_text(json.dumps(contract), encoding="utf-8")
        for name in (".agents/instructions/bootstrap.md", "AGENTS.md", "CLAUDE.md"):
            shutil.copy(REPO_ROOT / name, root / name)
        return root

    def test_activate_reads_a_contract_the_installed_resolver_cannot_fully_read(self):
        def newer(contract):
            contract["platform"] = {"min_inclusive": "99.0.0", "max_exclusive": "100.0.0"}
            contract["bindings"]["paths"]["playbooks"] = ["docs/playbooks"]

        root = self.contract_root(newer)
        with self.assertRaises(resolve_project.ContractError):
            resolve_project.resolve(str(root))
        self.assertEqual(activation.integration_branch(str(root)), "main")
        self.assertEqual(activation_run.activation_command(str(root)), (["just", "switch"], "."))

    def test_a_broken_branch_member_still_fails_the_activation_read(self):
        root = self.contract_root(lambda contract: contract["bindings"]["vcs"].pop("integration_branch"))
        with self.assertRaises(activation.ReadFailed):
            activation.integration_branch(str(root))
        with self.assertRaises(activation_run.Refused) as refused:
            activation_run.activation_command(str(root))
        self.assertEqual(str(refused.exception), "the project contract did not resolve (invalid_contract)")

    def test_a_root_without_a_contract_is_still_no_activation_branch(self):
        empty = self.tmp / "empty"
        empty.mkdir()
        self.assertIsNone(activation.integration_branch(str(empty)))


if __name__ == "__main__":
    unittest.main()
