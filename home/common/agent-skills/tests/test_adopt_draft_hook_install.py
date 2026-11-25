"""The registration of a project with no contract, on a host with a managed global hooks path.

The console drafts a schema-3 contract for such a project; its commit environment is the platform's
`devenv shell --`, never an authored member. These cases plan the draft, put the registration row's
words on it, and apply it with a fake `devenv` on `PATH`, so the registration's claim (the row names
the dev shell and Apply installs the hooks) is held to what the adoption commit does.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from unittest import mock

from agent_tools.console import approve, contract_draft, register

from .test_adopt_apply import ApplyTestCase
from .test_adopt_conformance_apply import DEFAULT_PROTECTION, stub_forge
from .test_adopt_hook_install import (
    CONFIG_VARIABLE,
    DECLARED,
    INSTALLER_SCRIPT,
    PASSED,
    UNDECLARED,
    fake_global,
    managed_hooks,
)
from .test_adopt_schema_three_draft import schema_three_checkout, schema_three_draft
from .test_adopt_project import commit, git, run, write

TIER = "integration"  # git sandboxes, spawned sh and git

FAKE_DEVENV = ('#!/bin/sh\n[ "$1" = shell ] && [ "$2" = -- ] || '
               '{ echo "fake devenv: unexpected arguments" >&2; exit 64; }\nshift 2\n' + INSTALLER_SCRIPT)
SIGNER = ("#!/bin/sh\ncat >/dev/null\n"
          "printf '\\n[GNUPG:] SIG_CREATED D 1 8 00 1700000000 X\\n' >&2\n"
          "printf -- '-----BEGIN PGP SIGNATURE-----\\n\\nx\\n-----END PGP SIGNATURE-----\\n'\n")
DRAFTED_LINE = "commits run in its development shell: devenv shell"
READING = {"remotes": [("origin", "https://github.com/fixture/target.git")],
           "default_branch": "main", "branches": ["main"]}


class DraftedHookInstallTest(ApplyTestCase):
    def setUp(self) -> None:
        super().setUp()
        directory, self.scratch = (Path(tempfile.mkdtemp()).resolve() for _ in range(2))
        for path in (directory, self.scratch):
            self.addCleanup(shutil.rmtree, path, True)
        managed = managed_hooks(directory)
        config = directory / "hooks-config.yaml"
        config.write_text("repos: []\n", encoding="utf-8")
        bin_dir, _, _ = stub_forge(directory / "bin", {"protection": DEFAULT_PROTECTION})
        devenv = Path(bin_dir) / "devenv"
        devenv.write_text(FAKE_DEVENV, encoding="utf-8")
        devenv.chmod(0o755)
        self.signer = directory / "signer"
        self.signer.write_text(SIGNER, encoding="utf-8")
        self.signer.chmod(0o755)
        patcher = mock.patch.dict(os.environ, {
            "GIT_CONFIG_GLOBAL": str(fake_global(directory, managed)),
            "GIT_CONFIG_SYSTEM": os.devnull,
            CONFIG_VARIABLE: str(config),
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def drafted_checkout(self, text: str) -> Path:
        root = schema_three_checkout(self, self.home, self.scratch)
        write(root, "devenv.nix", text)
        commit(root, "add devenv.nix")
        git(root, "config", "gpg.format", "openpgp")
        git(root, "config", "gpg.program", str(self.signer))
        git(root, "config", "user.signingkey", "DEADBEEF")
        return root

    def drafted_plan(self, root: Path) -> dict:
        draft = self.scratch / "draft.json"
        draft.write_text(json.dumps(schema_three_draft()), encoding="utf-8")
        code, out, err = run("plan", "--repo-root", str(root), "--contract-draft", str(draft),
                             home=self.home)
        self.assertEqual(code, 0, err or out)
        doc = json.loads(out)
        self.assertEqual(doc["plan"]["state"], "ready", doc["plan"].get("blockers"))
        return doc

    def registration(self, root: Path, doc: dict) -> dict:
        return register.hooks_noted(
            register.summary(str(root), doc, draft=contract_draft.draft(str(root), READING)))

    def card_lines(self, row: dict) -> list[str]:
        latest = {**row, "at": "2026-11-24T08:00:00+00:00"}
        return approve.apply_items(latest, None, None, "approve", deferred=set())[0]["lines"]

    def test_a_drafted_registration_with_missing_dev_shell_hooks_names_the_dev_shell_and_apply_installs_and_runs_them(
            self):
        root = self.drafted_checkout(DECLARED)
        doc = self.drafted_plan(root)
        row = self.registration(root, doc)
        plan_id = doc["plan"]["plan_id"]
        self.succeed(root, plan_id)
        verification = self.stored_document(plan_id)["verification"]
        self.assertNotIn("commit_environment", doc["plan"])
        self.assertEqual(row["lines"][:2], [DRAFTED_LINE, register.HOOKS_LINE])
        self.assertEqual(self.card_lines(row)[:2], [DRAFTED_LINE, register.HOOKS_LINE])
        self.assertTrue((root / ".git/hooks/pre-commit").is_file())
        self.assertEqual(verification["hook_install"], {"installed": ["pre-commit"]})
        self.assertIn(PASSED, verification["commit_output"]["lines"])

    def test_a_drafted_registration_without_dev_shell_hooks_names_no_commit_environment(self):
        root = self.drafted_checkout(UNDECLARED)
        doc = self.drafted_plan(root)
        row = self.registration(root, doc)
        self.assertNotIn("commit_environment", doc["plan"])
        self.assertEqual(row["lines"], register.plan_lines(doc))
        self.assertNotIn(DRAFTED_LINE, self.card_lines(row))
