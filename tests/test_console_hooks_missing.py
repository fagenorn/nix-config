"""The registration card says so when a project's devenv git hooks are not installed on this host.

Each case has a throwaway repository; the global git configuration is a fake whose hooks path holds a
pre-commit, so a reading that counted it would call the hooks installed.

Run: just agent-workflow-tests
"""

from __future__ import annotations

import os
import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from agent_tools.console import approve, contract_draft, event_log, register
from agent_tools.console.view import derive_view

from . import console_screenshots
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures
from .test_console_register_service import (
    A1, DRAFT, PID_A, PID_B, READY, Case, Fake, answer_of, git, git_repo)

TIER = "integration"

DECLARED = "{ pkgs, ... }: {\n  git-hooks.hooks.needs-dev-shell.enable = true;\n}\n"
PROPOSAL = "commits run in its development shell: devenv shell (found in its files)"


def hooked_repo(path: Path, *, contract: bool = True, text: str = DECLARED) -> Path:
    root = git_repo(path, contract=contract)
    (root / "devenv.nix").write_text(text)
    git(root, "add", "devenv.nix")
    git(root, "commit", "-q", "-m", "devenv")
    return root


def install_hook(root: Path) -> None:
    hook = root / ".git/hooks/pre-commit"
    hook.write_text("#!/bin/sh\nexit 0\n")
    hook.chmod(0o755)


def card(row: dict) -> tuple[dict, dict]:
    latest = {**row, "at": "2026-11-24T08:00:00+00:00"}
    items = approve.apply_items(latest, None, None, "approve", deferred=set())
    shown = derive_view([], registration=register.view_entry(None, latest), apply_items=items)
    return shown["inbox"]["open"][0], shown["registration"]


class GlobalHooksPath:
    """A global git configuration whose hooks path holds an executable pre-commit."""

    def enter_global_hooks_path(self) -> None:
        directory = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, directory, True)
        hooks = directory / "hooks"
        hooks.mkdir()
        (hooks / "pre-commit").write_text("#!/bin/sh\nexit 0\n")
        (hooks / "pre-commit").chmod(0o755)
        config = directory / "gitconfig"
        config.write_text(f"[core]\n\thooksPath = {hooks}\n")
        patch = mock.patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": str(config),
                                             "GIT_CONFIG_SYSTEM": os.devnull})
        patch.start()
        self.addCleanup(patch.stop)


class HooksMissingCardTest(GlobalHooksPath, unittest.TestCase):
    def setUp(self):
        self.enter_global_hooks_path()
        self.parent = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.parent, True)

    def test_a_ready_plan_whose_hooks_are_missing_says_so_first_and_states_no_commit_environment(self):
        root = hooked_repo(self.parent / "r")
        row = register.hooks_noted(register.summary(str(root), READY))
        shown, _entry = card(row)
        self.assertEqual(shown["lines"][0], register.HOOKS_LINE)
        self.assertEqual(register.HOOKS_LINE, "installs its git hooks on this host (not installed now)")
        for line in (*shown["lines"], *row["lines"]):
            self.assertFalse(line.startswith("commits run in its development shell"), line)
        self.assertEqual(row["lines"], [register.HOOKS_LINE, *register.plan_lines(READY)])

    def test_a_ready_plan_whose_hooks_are_installed_reads_as_today(self):
        root = hooked_repo(self.parent / "r")
        install_hook(root)
        row = register.summary(str(root), READY)
        self.assertEqual(register.hooks_noted(row), row)
        self.assertEqual(row["lines"], register.plan_lines(READY))
        draft = contract_draft.reconcile_fields(
            str(root), {"hooks": ["pre-commit"], "stranded": ["pre-commit"],
                        "environments": ["devenv.nix"]})
        shown, _entry = card(register.hooks_noted(register.summary(str(root), READY, draft=draft)))
        self.assertEqual(shown["lines"], [PROPOSAL, *register.plan_lines(READY)])

    def test_a_non_planned_row_or_none_is_unchanged(self):
        root = hooked_repo(self.parent / "r")
        self.assertIsNone(register.hooks_noted(None))
        failed = register.failed(str(root), "timed_out")
        self.assertEqual(register.hooks_noted(failed), failed)
        noted = register.hooks_noted(register.summary(str(root), READY))
        self.assertEqual(register.hooks_noted(noted), noted)


    def test_a_drafted_contract_leaves_the_hooks_uninstalled_and_says_so_on_every_surface(self):
        root = hooked_repo(self.parent / "r", contract=False)
        fields = contract_draft.draft(str(root), {**contract_draft.read(str(root)),
                                                  "default_branch": "main", "branches": ["main"]})
        row = register.hooks_noted(register.summary(str(root), READY, draft=fields))
        self.assertEqual(register.HOOKS_LEFT_LINE,
                         "leaves its git hooks uninstalled on this host "
                         "(no commit environment to install them in)")
        self.assertEqual(row["lines"], [register.HOOKS_LEFT_LINE, *register.plan_lines(READY)])
        shown, _entry = card(row)
        self.assertEqual(shown["lines"][0], register.HOOKS_LEFT_LINE)
        self.assertNotIn(register.HOOKS_LINE, shown["lines"])
        deferred = register.view_entry(None, {**row, "at": "2026-11-24T08:00:00+00:00"})
        self.assertEqual(deferred["lines"], [register.HOOKS_LEFT_LINE, *register.plan_lines(READY)])
        self.assertEqual(register.hooks_noted(row), row)

    def test_a_commit_environment_answered_none_leaves_the_hooks_uninstalled(self):
        root = hooked_repo(self.parent / "r")
        proposal = contract_draft.reconcile_fields(
            str(root), {"hooks": ["pre-commit"], "stranded": ["pre-commit"],
                        "environments": ["devenv.nix"]})
        declined, error = contract_draft.set_value(proposal, "commit-environment", "none")
        self.assertIsNone(error)
        row = register.hooks_noted(register.summary(str(root), READY, draft=declined))
        self.assertEqual(row["lines"], [register.HOOKS_LEFT_LINE, *register.plan_lines(READY)])
        shown, _entry = card(row)
        self.assertEqual(shown["lines"][1], register.HOOKS_LEFT_LINE)
        self.assertNotIn(register.HOOKS_LINE, shown["lines"])

    def test_a_proposed_commit_environment_keeps_the_installing_line(self):
        root = hooked_repo(self.parent / "r")
        proposal = contract_draft.reconcile_fields(
            str(root), {"hooks": ["pre-commit"], "stranded": ["pre-commit"],
                        "environments": ["devenv.nix"]})
        row = register.hooks_noted(register.summary(str(root), READY, draft=proposal))
        self.assertEqual(row["lines"], [register.HOOKS_LINE, *register.plan_lines(READY)])
        shown, _entry = card(row)
        self.assertEqual(shown["lines"], [PROPOSAL, register.HOOKS_LINE, *register.plan_lines(READY)])

    def test_the_adoption_pull_request_body_leaves_the_uninstalled_line_out(self):
        root = hooked_repo(self.parent / "r", contract=False)
        fields = contract_draft.draft(str(root), {**contract_draft.read(str(root)),
                                                  "default_branch": "main", "branches": ["main"]})
        row = register.hooks_noted(register.summary(str(root), READY, draft=fields))
        latest = {**row, "at": "2026-11-24T08:00:00+00:00", "headline": "H", "plan_id": PID_A}
        self.assertIn(register.HOOKS_LEFT_LINE, latest["lines"])
        self.assertNotIn(register.HOOKS_LEFT_LINE, approve.body(latest))


class HooksMissingReadingTest(GlobalHooksPath, unittest.TestCase):
    def setUp(self):
        self.enter_global_hooks_path()
        self.parent = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.parent, True)

    def test_a_declared_devenv_hook_missing_from_the_hooks_directory_is_missing(self):
        root = hooked_repo(self.parent / "r")
        self.assertTrue(contract_draft.hooks_missing(str(root)))

    def test_an_installed_hook_or_an_own_hooks_path_is_not_missing(self):
        installed = hooked_repo(self.parent / "installed")
        install_hook(installed)
        self.assertFalse(contract_draft.hooks_missing(str(installed)))
        own = hooked_repo(self.parent / "own")
        git(own, "config", "core.hooksPath", ".githooks")
        self.assertFalse(contract_draft.hooks_missing(str(own)))

    def test_a_devenv_file_that_declares_no_hooks_or_is_untracked_or_cancelled_is_not_missing(self):
        plain = hooked_repo(self.parent / "plain", text="{ }\n")
        self.assertFalse(contract_draft.hooks_missing(str(plain)))
        untracked = git_repo(self.parent / "untracked")
        (untracked / "devenv.nix").write_text(DECLARED)
        self.assertFalse(contract_draft.hooks_missing(str(untracked)))
        declared = hooked_repo(self.parent / "declared")
        stopped = threading.Event()
        stopped.set()
        self.assertFalse(contract_draft.hooks_missing(str(declared), stopped))
        self.assertFalse(contract_draft.hooks_missing(str(self.parent / "absent")))


class HooksMissingServiceTest(GlobalHooksPath, Case):
    def setUp(self):
        super().setUp()
        self.enter_global_hooks_path()

    def test_a_registration_whose_hooks_are_missing_opens_its_apply_card_on_the_line(self):
        self.begin(Fake(plan=READY), forge=object())
        root = hooked_repo(self.parent / "r")
        self.registered(root)
        self.assertEqual(self.rows("registration.ended")[-1][1]["lines"][0], register.HOOKS_LINE)
        (apply_card,) = [i for i in self.view()["inbox"]["open"] if i["reason"] == "register_apply"]
        self.assertEqual(apply_card["lines"][0], register.HOOKS_LINE)

    def test_the_adoption_pull_request_body_leaves_the_line_out(self):
        row = register.hooks_noted(register.summary(str(hooked_repo(self.parent / "r")), READY))
        latest = {**row, "at": "2026-11-24T08:00:00+00:00", "headline": "H", "plan_id": PID_A}
        self.assertIn(register.HOOKS_LINE, latest["lines"])
        text = approve.body(latest)
        self.assertNotIn(register.HOOKS_LINE, text)
        for line in register.plan_lines(READY):
            self.assertIn(f"- {line}", text)

    def test_an_answer_run_keeps_the_line(self):
        self.begin(Fake(plan=[DRAFT, READY]))
        root = hooked_repo(self.parent / "r")
        self.registered(root)
        self.assertEqual(self.answer(answer_of(PID_A, A1))[0], 204)
        self.wait_for(lambda r: r["status"] == "done" and r["plan_id"] == PID_B)
        lines = self.rows("registration.ended")[-1][1]["lines"]
        self.assertEqual(lines[0], register.HOOKS_LINE)
        self.assertEqual(lines.count(register.HOOKS_LINE), 1)

    def test_a_registration_whose_hooks_are_installed_plans_as_today(self):
        self.begin(Fake(plan=READY))
        root = hooked_repo(self.parent / "r")
        install_hook(root)
        self.registered(root)
        for _at, row in self.rows("registration.ended"):
            self.assertNotIn(register.HOOKS_LINE, row["lines"])


class RecordingSeed:
    """The one method the screenshot seed calls: put(at, kind, project, payload)."""

    def __init__(self) -> None:
        self.puts: list[tuple[str, dict]] = []

    def put(self, at, kind, project, payload) -> None:
        self.puts.append((kind, payload))

    def ended(self) -> dict:
        (payload,) = [p for kind, p in self.puts if kind == event_log.REGISTRATION_ENDED]
        return payload


class HooksMissingPictureTest(unittest.TestCase):
    def seeded(self, state: str) -> dict:
        root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, root, True)
        git(root, "init", "-q")
        seed = RecordingSeed()
        console_screenshots._seed_registration(seed, state, str(root))
        return seed.ended()

    def test_the_register_apply_state_seeds_the_uninstalled_line_first(self):
        self.assertEqual(self.seeded("register-apply")["lines"],
                         [register.HOOKS_LEFT_LINE, *console_screenshots.REGISTER_PLAN_LINES])

    def test_the_reconcile_states_keep_today_s_lines(self):
        self.assertEqual(self.seeded("register-reconcile-apply")["lines"],
                         list(console_screenshots.REGISTER_PLAN_LINES))


if __name__ == "__main__":
    unittest.main()
