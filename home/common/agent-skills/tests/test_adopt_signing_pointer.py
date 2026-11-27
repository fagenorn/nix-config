"""A refused signature points at the setting that asks for it when the contract authors one.

The apply error is the one source of that fact: the console never reads the checkout to learn it.

Run: just agent-workflow-tests
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_tools.console import approve
from agent_tools.project_contract import adopt_apply

from .test_adopt_apply import ApplyTestCase, apply_repo
from .test_adopt_project import commit, git

TIER = "integration"  # git sandboxes, spawned sh and git

POINTER = "/bindings/vcs/commit/signed"


def contract(version: object = 2, signed: object = True) -> str:
    return json.dumps({"schema_version": version, "bindings": {"vcs": {"commit": {"signed": signed}}}})


class SigningPointerTest(unittest.TestCase):
    def pointer(self, text: str | None) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            if text is not None:
                (Path(tmp) / ".agents").mkdir()
                (Path(tmp) / adopt_apply.CONTRACT_FILENAME).write_text(text, encoding="utf-8")
            return adopt_apply.signing_pointer(Path(tmp))

    def test_only_a_schema_two_contract_that_authors_signed_true_has_a_pointer(self):
        self.assertEqual(adopt_apply.SIGNING_POINTER, POINTER)
        self.assertEqual(approve.SIGNING_POINTER, POINTER)
        self.assertEqual(self.pointer(contract()), POINTER)
        for name, text in (
                ("false", contract(signed=False)), ("string", contract(signed="true")),
                ("schema 3", contract(version=3)), ("bool schema", contract(version=True)),
                ("float schema", contract(version=2.0)), ("string schema", contract(version="2")),
                ("no commit", json.dumps({"schema_version": 2, "bindings": {"vcs": {}}})),
                ("not json", "not json"), ("list", "[]"), ("no file", None),
                ("too deep", "[" * 50000 + "]" * 50000)):
            with self.subTest(name):
                self.assertEqual(self.pointer(text), "")


class SigningRefusalTest(ApplyTestCase):
    def test_a_committed_contract_over_a_mebibyte_still_points_at_its_setting(self):
        root = apply_repo(self.home, signed=True)
        padded = (root / adopt_apply.CONTRACT_FILENAME).read_text("utf-8") + " " * (1 << 20)
        (root / adopt_apply.CONTRACT_FILENAME).write_text(padded, encoding="utf-8")
        commit(root, "pad the contract")
        git(root, "config", "gpg.format", "openpgp")
        git(root, "config", "gpg.program", str(root / "no-such-signing-program"))
        git(root, "config", "user.signingkey", "DEADBEEF")
        plan_id = self.ready_plan(root)["plan"]["plan_id"]
        base = git(root, "rev-parse", "HEAD").strip()
        payload = self.assert_retained(root, plan_id, base, "adopt.commit.signing_unavailable")
        self.assertEqual([item["pointer"] for item in payload["error"]["violations"]], [POINTER])


if __name__ == "__main__":
    unittest.main()
