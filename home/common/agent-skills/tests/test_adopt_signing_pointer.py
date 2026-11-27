"""A refused signature points at the setting that asks for it when the contract authors one.

The apply error is the one source of that fact: the console never reads the checkout to learn it.

Run: just agent-workflow-tests
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent_tools.console import approve
from agent_tools.project_contract import adopt_apply

from .test_adopt_apply import CleanApplyTestCase, apply_repo, run, write_hooks
from .test_adopt_project import bootstrap_repo, commit, drafted_contract, git

TIER = "integration"  # git sandboxes, spawned sh and git

POINTER = "/bindings/vcs/commit/signed"


def contract(version: object = 2, signed: object = True) -> str:
    return json.dumps({"schema_version": version, "bindings": {"vcs": {"commit": {"signed": signed}}}})


class SigningPointerTest(unittest.TestCase):
    def test_only_a_schema_two_contract_that_authors_signed_true_has_a_pointer(self):
        self.assertEqual(adopt_apply.SIGNING_POINTER, POINTER)
        self.assertEqual(approve.SIGNING_POINTER, POINTER)
        self.assertEqual(adopt_apply.signing_pointer(contract().encode()), POINTER)
        for name, text in (
                ("false", contract(signed=False)), ("string", contract(signed="true")),
                ("schema 3", contract(version=3)), ("bool schema", contract(version=True)),
                ("float schema", contract(version=2.0)), ("string schema", contract(version="2")),
                ("no commit", json.dumps({"schema_version": 2, "bindings": {"vcs": {}}})),
                ("not json", "not json"), ("list", "[]"), ("no file", None),
                ("too deep", "[" * 50000 + "]" * 50000)):
            with self.subTest(name):
                self.assertEqual(adopt_apply.signing_pointer(None if text is None else text.encode()), "")


class SigningRefusalTest(CleanApplyTestCase):
    def failing_signer(self, root: Path) -> None:
        git(root, "config", "gpg.format", "openpgp")
        git(root, "config", "gpg.program", str(root / "no-such-signing-program"))
        git(root, "config", "user.signingkey", "DEADBEEF")

    def pointers(self, root: Path, plan_id: str) -> list[str]:
        base = git(root, "rev-parse", "HEAD").strip()
        payload = self.assert_retained(root, plan_id, base, "adopt.commit.signing_unavailable")
        return [item["pointer"] for item in payload["error"]["violations"]]

    def test_a_committed_contract_over_a_mebibyte_still_points_at_its_setting(self):
        root = self.owned(apply_repo(self.home, signed=True))
        path = root / adopt_apply.CONTRACT_FILENAME
        path.write_text(path.read_text("utf-8") + " " * (1 << 20), encoding="utf-8")
        commit(root, "pad the contract")
        self.failing_signer(root)
        plan_id = self.ready_plan(root)["plan"]["plan_id"]
        inspected = []
        real = adopt_apply.signing_pointer

        def spy(raw):
            inspected.append(len(raw))
            return real(raw)

        with mock.patch.object(adopt_apply, "signing_pointer", spy):
            self.assertEqual(self.pointers(root, plan_id), [POINTER])
        self.assertEqual(len(inspected), 1)
        self.assertGreater(inspected[0], 1 << 20)

    def test_a_hook_that_removes_the_worktree_contract_does_not_hide_the_committed_setting(self):
        root = self.owned(apply_repo(self.home, signed=True))
        self.failing_signer(root)
        git(root, "config", "core.hooksPath",
            str(write_hooks(pre_commit="#!/bin/sh\nrm -f .agents/project.json\nexit 1\n")))
        plan_id = self.ready_plan(root)["plan"]["plan_id"]
        self.assertEqual(self.pointers(root, plan_id), [POINTER])
        self.assertFalse((self.worktree(plan_id) / adopt_apply.CONTRACT_FILENAME).exists())

    def test_a_drafted_contract_that_asks_for_signing_has_no_pointer(self):
        root = self.owned(bootstrap_repo(self.home))
        self.failing_signer(root)
        document = drafted_contract()
        document["bindings"]["vcs"]["commit"]["signed"] = True
        self.assertEqual(document["schema_version"], 2)
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        draft = Path(scratch.name) / "draft.json"
        draft.write_text(json.dumps(document), encoding="utf-8")
        code, out, err = run("plan", "--repo-root", str(root), "--contract-draft", str(draft), home=self.home)
        self.assertEqual(code, 0, err or out)
        plan = json.loads(out)
        self.assertEqual(plan["plan"]["state"], "ready", plan["plan"]["blockers"])
        self.assertIn("contract_draft", plan["plan"])
        self.assertEqual(self.pointers(root, plan["plan"]["plan_id"]), [""])
        written = json.loads((self.worktree(plan["plan"]["plan_id"]) / adopt_apply.CONTRACT_FILENAME)
                             .read_text("utf-8"))
        self.assertIs(written["bindings"]["vcs"]["commit"]["signed"], True)


if __name__ == "__main__":
    unittest.main()
