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
from .test_adopt_schema_three_draft import schema_three_checkout
from .test_adopt_project import commit, git, run, write

TIER = "integration"  # git sandboxes, spawned sh and git

FAKE_DEVENV = ('#!/bin/sh\n[ "$1" = shell ] && [ "$2" = -- ] || '
               '{ echo "fake devenv: unexpected arguments" >&2; exit 64; }\nshift 2\n' + INSTALLER_SCRIPT)
SIGNER = ("#!/bin/sh\ncat >/dev/null\n"
          "printf '\\n[GNUPG:] SIG_CREATED D 1 8 00 1700000000 X\\n' >&2\n"
          "printf -- '-----BEGIN PGP SIGNATURE-----\\n\\nx\\n-----END PGP SIGNATURE-----\\n'\n")
DRAFTED_LINE = "commits run in its development shell: devenv shell"
ONE_LINE = "{ ... }: { git-hooks.hooks.needs-dev-shell.enable = true; }\n"
SWITCHED_OFF = "{ ... }: {\n  git-hooks.hooks.needs-dev-shell.enable = false;\n}\n"
SWITCHED_OFF_IN_SET = "{ ... }: {\n  git-hooks.hooks.needs-dev-shell = { enable = false; };\n}\n"
STRINGS_BEFORE = ('{ pkgs, ... }:\n{\n  scripts.clean.exec = "rm -rf build/*";\n'
                  '  env.URL = "http://x/#a";\n  git-hooks.hooks.needs-dev-shell.enable = true;\n'
                  '  /* formatting */\n  languages.nix.enable = true;\n}\n')
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

    def drafted_fields(self, root: Path) -> list[dict]:
        """The console's draft with the two open command fields answered, once."""
        fields = contract_draft.draft(str(root), READING)
        for field in ("lint-command", "test-command"):
            fields, error = contract_draft.set_value(fields, field, "true")
            self.assertIsNone(error)
        return fields

    def drafted_plan(self, root: Path, fields: list[dict]) -> dict:
        draft = self.scratch / "draft.json"
        draft.write_text(json.dumps(contract_draft.contract(fields)), encoding="utf-8")
        code, out, err = run("plan", "--repo-root", str(root), "--contract-draft", str(draft),
                             home=self.home)
        self.assertEqual(code, 0, err or out)
        doc = json.loads(out)
        self.assertEqual(doc["plan"]["state"], "ready", doc["plan"].get("blockers"))
        return doc

    def registration(self, root: Path, doc: dict, fields: list[dict]) -> dict:
        return register.hooks_noted(register.summary(str(root), doc, draft=fields))

    def card_lines(self, row: dict) -> list[str]:
        latest = {**row, "at": "2026-11-24T08:00:00+00:00"}
        return approve.apply_items(latest, None, None, "approve", deferred=set())[0]["lines"]

    def test_a_drafted_registration_with_missing_dev_shell_hooks_names_the_dev_shell_and_apply_installs_and_runs_them(
            self):
        root = self.drafted_checkout(DECLARED)
        fields = self.drafted_fields(root)
        doc = self.drafted_plan(root, fields)
        row = self.registration(root, doc, fields)
        plan_id = doc["plan"]["plan_id"]
        self.succeed(root, plan_id)
        verification = self.stored_document(plan_id)["verification"]
        self.assertNotIn("commit_environment", doc["plan"])
        expected = [DRAFTED_LINE, register.HOOKS_LINE, *register.plan_lines(doc)]
        self.assertEqual(row["lines"], expected)
        self.assertEqual(self.card_lines(row), expected)
        self.assertTrue((root / ".git/hooks/pre-commit").is_file())
        self.assertEqual(verification["hook_install"], {"installed": ["pre-commit"]})
        self.assertIn(PASSED, verification["commit_output"]["lines"])

    def test_a_drafted_registration_whose_only_hook_setting_is_one_line_names_the_dev_shell(self):
        root = self.drafted_checkout(ONE_LINE)
        fields = self.drafted_fields(root)
        row = self.registration(root, self.drafted_plan(root, fields), fields)
        self.assertEqual(self.card_lines(row)[:2], [DRAFTED_LINE, register.HOOKS_LINE])

    def test_a_drafted_registration_with_a_hook_setting_after_strings_holding_comment_openers_names_the_dev_shell(
            self):
        root = self.drafted_checkout(STRINGS_BEFORE)
        fields = self.drafted_fields(root)
        row = self.registration(root, self.drafted_plan(root, fields), fields)
        self.assertEqual(self.card_lines(row)[:2], [DRAFTED_LINE, register.HOOKS_LINE])

    def test_a_drafted_registration_whose_only_hook_setting_switches_it_off_names_no_dev_shell(self):
        for text in (SWITCHED_OFF, SWITCHED_OFF_IN_SET):
            with self.subTest(text=text):
                root = self.drafted_checkout(text)
                fields = self.drafted_fields(root)
                doc = self.drafted_plan(root, fields)
                row = self.registration(root, doc, fields)
                self.assertEqual(self.card_lines(row), register.plan_lines(doc))

    def test_a_drafted_registration_without_dev_shell_hooks_names_no_commit_environment(self):
        root = self.drafted_checkout(UNDECLARED)
        fields = self.drafted_fields(root)
        doc = self.drafted_plan(root, fields)
        row = self.registration(root, doc, fields)
        self.assertNotIn("commit_environment", doc["plan"])
        self.assertEqual(row["lines"], register.plan_lines(doc))
        self.assertEqual(self.card_lines(row), register.plan_lines(doc))
