"""The activation reading (#1114): which console files this host runs behind origin's integration branch."""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import signal
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from agent_tools.console import activation, activation_run, console, service, view
from agent_tools.console.activation import (
    Activation, blob_id, console_files, origin_files, reader_for, reading)
from agent_tools.console.event_log import EventLog
from agent_tools.console.activation_run import NEXT_STEP, Activator, LastRun, Outcome, Refused, Stopped
from agent_tools.project_contract import resolve_project

from . import accounts_sandbox
from . import console_test_support as support
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)

REPO_ROOT = Path(__file__).resolve().parents[1]
GIT_ENV = {
    **os.environ,
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
}
CONSOLE = "python/agent_tools/console"
FILES = {
    "python/agent_tools/__init__.py": "",
    f"{CONSOLE}/__init__.py": "",
    f"{CONSOLE}/console.py": "from agent_tools.console import view\n",
    f"{CONSOLE}/view.py": "from agent_tools.system import util\nVALUE = 1\n",
    f"{CONSOLE}/manager-contract.md": "contract v1\n",
    "python/agent_tools/system/__init__.py": "",
    "python/agent_tools/system/util.py": "X = 1\n",
    "python/agent_tools/verification/__init__.py": "",
    "python/agent_tools/verification/other.py": "Y = 1\n",
    "docs/notes.md": "notes\n",
    "home/common/agent-skills/skills/demo/SKILL.md": "demo v1\n",
    "hosts/common/demo.nix": "{ }\n",
}
SKILL = "home/common/agent-skills/skills/demo/SKILL.md"


def git(path, *arguments):
    done = subprocess.run(
        ["git", "-C", str(path), *arguments], env=GIT_ENV, check=True, text=True,
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE)
    return done.stdout


def write(root: Path, files: dict[str, str | None]) -> None:
    for name, text in files.items():
        if text is None:
            git(root, "rm", "-q", name)
            continue
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)


def commit(root: Path, files: dict[str, str | None]) -> None:
    write(root, files)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "more")


def repository(parent: Path, name: str, files: dict[str, str]) -> Path:
    """A checkout of `parent/name` with one commit, a bare origin, and `main` sent there and fetched back."""
    root = parent / name
    root.mkdir(parents=True)
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "commit.gpgsign", "false")
    write(root, files)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "one")
    bare = parent / f"{name}-origin.git"
    git(parent, "clone", "-q", "--bare", str(root), str(bare))
    git(root, "remote", "add", "origin", str(bare))
    git(root, "push", "-q", "origin", "main")
    git(root, "fetch", "-q", "origin")
    return root


class Trees(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.checkout = repository(self.tmp, "checkout", FILES)
        self.built = self.origin_commit()
        self.package_root = self.tmp / "pkg"
        shutil.copytree(self.checkout / "python", self.package_root)
        cache = self.package_root / "agent_tools/console/__pycache__"
        cache.mkdir()
        (cache / "view.cpython-313.pyc").write_bytes(b"\0bytecode")
        self.running = console_files(self.package_root)

    def second_clone(self) -> Path:
        clone = self.tmp / "second"
        if not clone.exists():
            git(self.tmp, "clone", "-q", str(self.tmp / "checkout-origin.git"), str(clone))
            git(clone, "config", "commit.gpgsign", "false")
        return clone

    def advance(self, files):
        clone = self.second_clone()
        commit(clone, files)
        git(clone, "push", "-q", "origin", "main")
        git(self.checkout, "fetch", "-q", "origin")

    def origin_commit(self) -> str:
        return git(self.checkout, "rev-parse", "refs/remotes/origin/main").strip()

    def read(self, roots=None, **seams):
        seams.setdefault("branch_of", lambda root: "main")
        seams.setdefault("revision", lambda: self.built)
        return reading([str(self.checkout)] if roots is None else roots, self.running, **seams)


class ActivationReadingTest(Trees):
    def test_a_blob_id_is_gits(self):
        file = self.tmp / "x.txt"
        file.write_bytes(b"x\n")
        self.assertEqual(blob_id(b"x\n"), git(self.tmp, "hash-object", str(file)).strip())

    def test_the_console_files_are_its_directory_and_the_modules_it_imports(self):
        files = console_files(self.package_root)
        self.assertEqual(set(files), {
            "python/agent_tools/__init__.py",
            f"{CONSOLE}/__init__.py",
            f"{CONSOLE}/console.py",
            f"{CONSOLE}/view.py",
            f"{CONSOLE}/manager-contract.md",
            "python/agent_tools/system/__init__.py",
            "python/agent_tools/system/util.py",
        })
        for key, value in files.items():
            relative = key.removeprefix("python/")
            self.assertEqual(value, blob_id((self.package_root / relative).read_bytes()), key)

    def test_a_matching_tree_names_nothing(self):
        self.assertEqual(self.read(), Activation(str(self.checkout), (), self.origin_commit()))

    def test_a_console_file_behind_origin_is_named(self):
        self.advance({f"{CONSOLE}/view.py": "from agent_tools.system import util\nVALUE = 2\n"})
        self.assertEqual(self.read().changed, (f"{CONSOLE}/view.py",))

    def test_the_manager_contract_behind_origin_is_named(self):
        self.advance({f"{CONSOLE}/manager-contract.md": "contract v2\n"})
        self.assertEqual(self.read().changed, (f"{CONSOLE}/manager-contract.md",))

    def test_an_imported_module_behind_origin_is_named(self):
        self.advance({"python/agent_tools/system/util.py": "X = 2\n"})
        self.assertEqual(self.read().changed, ("python/agent_tools/system/util.py",))

    def test_the_reading_names_the_origin_commit_it_compared(self):
        self.advance({f"{CONSOLE}/view.py": "from agent_tools.system import util\nVALUE = 2\n"})
        result = self.read()
        self.assertEqual(result.commit, git(self.checkout, "rev-parse", "refs/remotes/origin/main").strip())
        self.assertEqual(result.changed, (f"{CONSOLE}/view.py",))

    def test_origin_tip_is_the_remote_tracking_commit(self):
        expected = git(self.checkout, "rev-parse", "refs/remotes/origin/main").strip()
        with mock.patch.object(activation, "integration_branch", lambda root: "main"):
            self.assertEqual(activation.origin_tip(str(self.checkout)), expected)
        with mock.patch.object(activation, "integration_branch", lambda root: "nope"):
            self.assertIsNone(activation.origin_tip(str(self.checkout)))
        with mock.patch.object(activation, "integration_branch", lambda root: None):
            self.assertIsNone(activation.origin_tip(str(self.checkout)))

    def test_a_change_outside_the_console_files_is_another_change(self):
        self.advance({"docs/notes.md": "more\n", "python/agent_tools/verification/other.py": "Y = 2\n"})
        self.assertEqual(self.read(), Activation(
            str(self.checkout), (), self.origin_commit(), ("python/agent_tools/verification/other.py",)))

    def test_pending_is_any_change(self):
        self.assertIs(Activation("/r", (), C).pending, False)
        self.assertIs(Activation("/r", ("x",), C).pending, True)
        self.assertIs(Activation("/r", (), C, ("y",)).pending, True)

    def test_only_documentation_paths_are_not_host_built(self):
        for path in ("docs/notes.md", "tests/test_x.py", ".github/workflows/ci.yaml", ".agents/project.json",
                     "README.md", "CLAUDE.md", "AGENTS.md", "justfile", ".gitignore", ".sops.yaml",
                     "home/common/claude-code/README.md", "home/common/agent-skills/README.md",
                     "home/linux/claude-local/README.md", "hosts/darwin/eleven-m5/README.md",
                     "home/common/agent-skills/evals/README.md", "home/common/agent-skills/evals/run-eval.sh",
                     "home/common/agent-skills/tests/test_x.py", "home/common/agent-skills/tests/fixtures/f.json",
                     "lib/omlx-check.nix", "lib/agent-platform-check.nix"):
            with self.subTest(path=path):
                self.assertFalse(activation.host_built(path))
        for path in (SKILL, "home/common/agent-skills/skills/grill-with-docs/ADR-FORMAT.md",
                     "home/common/agent-skills/standards/README.md",
                     "home/common/claude-code/skills/deliver-standard/SKILL.md",
                     "patches/agent-plugins/codex-plugin-cc.patch", "hosts/common/common-packages.nix",
                     "flake.lock", "flake.nix", "secrets/secrets.yaml", "data/zshrc/common/50-aliases",
                     "python/README.md", "home/common/claude-code/README.md.orig", "newdir/README.md",
                     "home/common/agent-skills/evals-notes.md", "home/common/agent-skills/tests-notes.md",
                     "lib/omlx-check.nix.orig", "lib/agent-platform-check.nix.orig", "lib/agent-tools.nix",
                     "newdir/file"):
            with self.subTest(path=path):
                self.assertTrue(activation.host_built(path))

    def test_a_skill_change_is_another_change(self):
        self.advance({SKILL: "demo v2\n"})
        self.assertEqual(self.read(), Activation(str(self.checkout), (), self.origin_commit(), (SKILL,)))

    def test_a_documentation_only_change_names_nothing(self):
        self.advance({"docs/notes.md": "more\n", "README.md": "r\n", "CLAUDE.md": "c\n", "AGENTS.md": "a\n",
                      "justfile": "j\n", ".gitignore": "g\n", ".sops.yaml": "s\n", "tests/test_x.py": "T = 1\n",
                      ".github/workflows/x.yaml": "x\n", ".agents/project.json": "{}\n"})
        result = self.read()
        self.assertEqual(result, Activation(str(self.checkout), (), self.origin_commit()))
        self.assertIs(result.pending, False)

    def test_a_module_readme_only_change_names_nothing(self):
        self.advance({"home/common/claude-code/README.md": "r\n", "home/common/agent-skills/README.md": "r\n",
                      "home/linux/claude-local/README.md": "r\n", "hosts/darwin/eleven-m5/README.md": "r\n",
                      "home/common/agent-skills/evals/README.md": "r\n"})
        result = self.read()
        self.assertEqual(result.other, ())
        self.assertIs(result.pending, False)
        self.advance({"home/common/agent-skills/standards/README.md": "s\n"})
        self.assertEqual(self.read().other, ("home/common/agent-skills/standards/README.md",))

    def test_a_change_only_a_flake_check_reads_names_nothing(self):
        self.advance({"lib/omlx-check.nix": "{ }\n", "home/common/agent-skills/tests/test_x.py": "T = 1\n"})
        result = self.read()
        self.assertEqual(result, Activation(str(self.checkout), (), self.origin_commit()))
        self.assertIs(result.pending, False)

    def test_a_console_change_is_not_also_another_change(self):
        self.advance({f"{CONSOLE}/view.py": "from agent_tools.system import util\nVALUE = 2\n",
                      "python/agent_tools/system/util.py": "X = 2\n"})
        self.assertEqual(self.read().changed, (f"{CONSOLE}/view.py", "python/agent_tools/system/util.py"))
        self.assertEqual(self.read().other, ())

    def test_a_deleted_host_file_is_another_change(self):
        self.advance({"hosts/common/demo.nix": None})
        self.assertEqual(self.read().other, ("hosts/common/demo.nix",))

    def test_the_comparison_starts_at_the_hosts_revision(self):
        self.advance({SKILL: "demo v2\n"})
        tip = self.origin_commit()
        self.assertEqual(self.read(revision=lambda: tip).other, ())
        self.assertEqual(self.read(revision=lambda: tip + "-dirty").other, ())
        self.assertEqual(self.read(revision=lambda: self.built + "-dirty").other, (SKILL,))

    def test_an_unreadable_revision_or_an_unknown_commit_is_a_failed_read(self):
        with self.assertRaises(activation.ReadFailed):
            self.read(revision=lambda: None)
        with self.assertRaises(activation.ReadFailed):
            self.read(revision=lambda: "f" * 40)
        plain = repository(self.tmp, "a-plain", {"README.md": "x\n"})
        self.assertIsNone(self.read([str(plain)], revision=lambda: None))

    def test_reader_for_reads_the_host_revision_on_every_call(self):
        self.advance({SKILL: "demo v2\n"})
        revisions = iter([self.built, self.origin_commit()])
        reader = reader_for(self.package_root, revision=lambda: next(revisions))
        with mock.patch.object(activation, "integration_branch", lambda root: "main"):
            self.assertEqual(reader([str(self.checkout)]).other, (SKILL,))
            self.assertEqual(reader([str(self.checkout)]).other, ())

    def test_a_console_file_added_or_removed_on_origin_is_named(self):
        self.advance({f"{CONSOLE}/added.py": "Z = 1\n", f"{CONSOLE}/manager-contract.md": None})
        self.assertEqual(
            self.read().changed, (f"{CONSOLE}/added.py", f"{CONSOLE}/manager-contract.md"))

    def test_an_unpushed_or_unfetched_change_is_not_read(self):
        commit(self.checkout, {f"{CONSOLE}/view.py": "VALUE = 3\n"})
        clone = self.second_clone()
        commit(clone, {f"{CONSOLE}/view.py": "VALUE = 4\n"})
        git(clone, "push", "-q", "origin", "main")
        before = git(self.checkout, "for-each-ref")
        result = self.read()
        self.assertEqual(result.changed, ())
        self.assertEqual(git(self.checkout, "for-each-ref"), before)

    def test_the_root_is_the_registered_checkout_whose_origin_carries_the_console(self):
        plain = repository(self.tmp, "a-plain", {"README.md": "x\n"})
        result = self.read([str(self.checkout), str(plain)])
        self.assertEqual(result.root, str(self.checkout))
        self.assertIsNone(self.read([str(plain)]))

    def test_a_root_that_is_not_the_consoles_checkout_is_no_reading(self):
        self.assertIsNone(self.read(branch_of=lambda root: "nope"))
        self.assertIsNone(self.read(branch_of=lambda root: None))
        self.assertIsNone(origin_files(str(self.checkout), "nope"))

    def test_a_failed_read_raises_rather_than_reading_nothing(self):
        with self.assertRaises(activation.ReadFailed):
            self.read([str(self.tmp / "missing")])
        for failure in (subprocess.TimeoutExpired(["git"], 30), OSError("disk")):
            with self.subTest(failure=failure), \
                    mock.patch.object(activation.subprocess, "run", side_effect=failure):
                with self.assertRaises(activation.ReadFailed):
                    origin_files(str(self.checkout), "main")
        self.assertEqual(
            self.read([str(self.tmp / "a-missing"), str(self.checkout)]),
            Activation(str(self.checkout), (), self.origin_commit()))

    def test_the_integration_branch_is_the_project_contracts(self):
        home = Path(tempfile.mkdtemp(dir=accounts_sandbox.root())).resolve()
        previous = os.environ["HOME"]
        os.environ["HOME"] = str(home)
        self.addCleanup(os.environ.__setitem__, "HOME", previous)
        self.addCleanup(shutil.rmtree, home, True)
        (home / ".agents/share").mkdir(parents=True)
        shutil.copy(REPO_ROOT / "home/common/agent-skills/platform-manifest.json",
                    home / ".agents/share/platform-manifest.json")
        self.assertEqual(activation.integration_branch(str(REPO_ROOT)), "main")
        self.assertIsNone(activation.integration_branch(str(self.checkout)))
        broken = resolve_project.ContractError("resolver_failure", "resolver.internal", [])
        with mock.patch.object(activation.resolve_project, "resolve_core", side_effect=broken):
            with self.assertRaises(activation.ReadFailed):
                activation.integration_branch(str(REPO_ROOT))

    def test_reader_for_reads_the_running_files_once(self):
        reader = reader_for(self.package_root, revision=lambda: self.built)
        (self.package_root / "agent_tools/console/view.py").write_text("VALUE = 9\n")
        with mock.patch.object(activation, "integration_branch", lambda root: "main"):
            self.assertEqual(reader([str(self.checkout)]).changed, ())


C = "c" * 40
READ = Activation("/srv/cfg", ("python/agent_tools/console/view.py",), C)
NOW = 1_800_000_000_000
FAILURE = "the activation command exited 3 (sudo: a password is required)"
NEXT = "Its output is in /s/activation.log; press Activate again once the cause is fixed."


class ActivationViewTest(Trees):
    def read(self):
        return reading([str(self.checkout)], console_files(self.package_root), branch_of=lambda r: "main",
                       revision=lambda: self.built)

    def test_a_pending_change_offers_activate_for_its_commit(self):
        self.assertEqual(view.derive_view([], activation=READ)["activation"], {
            "text": f"A console change merged at {C[:12]} is not active on this host.",
            "state": "pending", "commit": C, "root": "/srv/cfg", "activate": True})

    def test_a_running_activation_reads_activating_and_offers_nothing(self):
        run = LastRun(C, "/srv/cfg", "running", None, None, None)
        line = view.derive_view([], activation=READ, activation_run=run, now_ms=NOW)["activation"]
        self.assertEqual(line["text"], f"Switching this computer to the new version ({C[:12]}). The console may restart before it reports.")
        self.assertEqual((line["state"], line["commit"], line["activate"]), ("running", C, False))

    def test_a_finished_activation_reads_activated_at_its_commit(self):
        run = LastRun(C, "/srv/cfg", "activated", None, None, NOW - 1000)
        line = view.derive_view([], activation=None, activation_run=run, now_ms=NOW)["activation"]
        self.assertEqual(line["text"], f"Switched this computer to the new version ({C[:12]}).")
        self.assertEqual((line["state"], line["commit"], line["activate"]), ("activated", C, False))

    def test_a_failed_activation_reads_its_reason_and_next_step(self):
        run = LastRun(C, "/srv/cfg", "failed", FAILURE, NEXT, NOW - 1000)
        line = view.derive_view([], activation=READ, activation_run=run, now_ms=NOW)["activation"]
        self.assertEqual(line["text"], f"Switching this computer to the new version ({C[:12]}) failed: {FAILURE}. {NEXT}")
        self.assertEqual((line["state"], line["activate"]), ("failed", True))

    def test_another_change_offers_activate_in_plain_words(self):
        line = view.derive_view([], activation=Activation("/srv/cfg", (), C, (SKILL,)))["activation"]
        self.assertEqual(line, {
            "text": f"A change to the agent tooling merged at {C[:12]} and is not active on this host.",
            "state": "pending", "commit": C, "root": "/srv/cfg", "activate": True})

    def test_a_change_beyond_the_agent_tooling_reads_as_the_host_configuration(self):
        reading_ = Activation("/srv/cfg", (), C, ("hosts/common/common-packages.nix", SKILL))
        self.assertEqual(
            view.derive_view([], activation=reading_)["activation"]["text"],
            f"A change to the host configuration merged at {C[:12]} and is not active on this host.")

    def test_agent_tooling_is_the_agent_paths(self):
        tooling = (
            "python/agent_tools/verification/other.py", SKILL, "home/common/agent-guidance/AGENTS.md",
            "home/common/agent-tools/default.nix", "home/common/claude-code/default.nix",
            "home/common/codex/default.nix", "patches/agent-plugins/codex-plugin-cc.patch",
            "lib/agent-tools.nix", "lib/agent-plugins.nix")
        configuration = (
            "hosts/common/common-packages.nix", "home/common/console/default.nix", "lib/helpers.nix",
            "flake.lock", "data/zshrc/common/50-aliases")
        for kind, paths in (("agent tooling", tooling), ("host configuration", configuration)):
            for path in paths:
                with self.subTest(path=path):
                    line = view.derive_view([], activation=Activation("/srv/cfg", (), C, (path,)))["activation"]
                    self.assertEqual(
                        line["text"], f"A change to the {kind} merged at {C[:12]} and is not active on this host.")

    def test_a_console_change_keeps_the_console_wording_beside_another_change(self):
        line = view.derive_view([], activation=Activation(
            "/srv/cfg", ("python/agent_tools/console/view.py",), C, (SKILL,)))["activation"]
        self.assertEqual(line["text"], f"A console change merged at {C[:12]} is not active on this host.")

    def test_a_failed_run_for_another_change_offers_activate_again(self):
        run = LastRun(C, "/srv/cfg", "failed", FAILURE, NEXT, NOW - 1000)
        line = view.derive_view(
            [], activation=Activation("/srv/cfg", (), C, (SKILL,)), activation_run=run, now_ms=NOW)["activation"]
        self.assertEqual((line["state"], line["activate"]), ("failed", True))

    def test_a_failed_run_for_the_shown_commit_stays_retryable_with_nothing_pending(self):
        run = LastRun(C, "/srv/cfg", "failed", FAILURE, NEXT, NOW - 1000)
        for now in (NOW, NOW + view.OUTCOME_MS - 1001):
            with self.subTest(now=now):
                line = view.derive_view(
                    [], activation=Activation("/srv/cfg", (), C), activation_run=run, now_ms=now)["activation"]
                self.assertEqual((line["state"], line["commit"], line["activate"]), ("failed", C, True))

    def test_a_failed_run_for_the_shown_commit_clears_a_day_after_it_finished_with_nothing_pending(self):
        run = LastRun(C, "/srv/cfg", "failed", FAILURE, NEXT, NOW - 1000)
        for now in (NOW + view.OUTCOME_MS - 1000, NOW + 10 * 24 * 3600 * 1000):
            with self.subTest(now=now):
                self.assertIsNone(view.derive_view(
                    [], activation=Activation("/srv/cfg", (), C), activation_run=run,
                    now_ms=now)["activation"])

    def test_a_pending_change_after_an_activated_run_for_its_commit_is_pending_again(self):
        run = LastRun(C, "/srv/cfg", "activated", None, None, NOW - 1000)
        for reading_ in (Activation("/srv/cfg", (), C, (SKILL,)), READ):
            with self.subTest(reading=reading_):
                line = view.derive_view([], activation=reading_, activation_run=run, now_ms=NOW)["activation"]
                self.assertEqual((line["state"], line["commit"], line["activate"]), ("pending", C, True))

    def test_an_activated_run_with_nothing_pending_offers_nothing(self):
        run = LastRun(C, "/srv/cfg", "activated", None, None, NOW - 1000)
        line = view.derive_view(
            [], activation=Activation("/srv/cfg", (), C), activation_run=run, now_ms=NOW)["activation"]
        self.assertEqual((line["state"], line["activate"]), ("activated", False))
        self.assertIsNone(view.derive_view(
            [], activation=Activation("/srv/cfg", (), C), activation_run=run,
            now_ms=NOW + view.OUTCOME_MS)["activation"])

    def test_offers_activate_is_a_pending_change_or_a_fresh_failed_run_for_the_shown_commit(self):
        none = Activation("/srv/cfg", (), C)

        def failed(commit):
            return LastRun(commit, "/srv/cfg", "failed", FAILURE, NEXT, NOW)

        table = (
            (None, None, False), (None, failed(C), False), (none, None, False), (READ, None, True),
            (Activation("/srv/cfg", (), C, (SKILL,)), None, True), (none, failed(C), True),
            (none, failed("d" * 40), False),
            (none, LastRun(C, "/srv/cfg", "failed", FAILURE, NEXT, NOW - view.OUTCOME_MS + 1), True),
            (none, LastRun(C, "/srv/cfg", "failed", FAILURE, NEXT, NOW - view.OUTCOME_MS), False),
            (none, LastRun(C, "/srv/cfg", "failed", FAILURE, NEXT, None), False),
            (READ, LastRun(C, "/srv/cfg", "failed", FAILURE, NEXT, NOW - view.OUTCOME_MS), True),
            (none, LastRun(C, "/srv/cfg", "activated", None, None, NOW), False),
            (none, LastRun(C, "/srv/cfg", "running", None, None, None), False))
        for index, (reading_, run, expected) in enumerate(table):
            with self.subTest(row=index):
                self.assertIs(view.offers_activate(reading_, run, NOW), expected)
        self.assertIs(view.offers_activate(none, failed(C), None), False)

    def test_a_newer_pending_commit_replaces_an_old_outcome(self):
        run = LastRun("d" * 40, "/srv/cfg", "failed", FAILURE, NEXT, NOW - 1000)
        line = view.derive_view([], activation=READ, activation_run=run, now_ms=NOW)["activation"]
        self.assertEqual((line["state"], line["commit"], line["activate"]), ("pending", C, True))

    def test_an_outcome_with_nothing_pending_clears_after_a_day(self):
        for finished, shown in ((NOW - view.OUTCOME_MS, False), (NOW - view.OUTCOME_MS + 1, True)):
            run = LastRun(C, "/srv/cfg", "activated", None, None, finished)
            line = view.derive_view([], activation=None, activation_run=run, now_ms=NOW)["activation"]
            self.assertEqual(line is not None, shown)

    def test_a_matching_tree_shows_no_line(self):
        self.assertIsNone(view.derive_view([], activation=self.read())["activation"])

    def test_a_documentation_only_difference_shows_no_line(self):
        self.advance({"docs/notes.md": "more\n", "README.md": "r\n"})
        self.assertIsNone(view.derive_view([], activation=self.read())["activation"])

    def test_a_module_readme_only_difference_shows_no_line(self):
        self.advance({"home/common/claude-code/README.md": "r\n", "home/linux/claude-local/README.md": "r\n"})
        self.assertIsNone(view.derive_view([], activation=self.read())["activation"])

    def test_a_skill_merged_on_origin_shows_the_agent_tooling_line(self):
        self.advance({SKILL: "demo v2\n"})
        tip = self.origin_commit()
        self.assertEqual(view.derive_view([], activation=self.read())["activation"], {
            "text": f"A change to the agent tooling merged at {tip[:12]} and is not active on this host.",
            "state": "pending", "commit": tip, "root": str(self.checkout), "activate": True})

    def test_a_nix_module_merged_on_origin_shows_the_host_configuration_line(self):
        self.advance({"hosts/common/demo.nix": "{ x = 1; }\n"})
        tip = self.origin_commit()
        self.assertEqual(
            view.derive_view([], activation=self.read())["activation"]["text"],
            f"A change to the host configuration merged at {tip[:12]} and is not active on this host.")

    def test_no_reading_shows_no_line(self):
        self.assertIsNone(view.derive_view([])["activation"])
        self.assertIsNone(view.derive_view([], activation=None)["activation"])

    def test_the_line_is_not_an_inbox_item(self):
        result = view.derive_view([], activation=READ)
        self.assertEqual(result["statement"], view.derive_view([])["statement"])
        self.assertEqual(result["statement"]["headline"], "Nothing needs you")
        self.assertEqual(json.loads(view.encode_view(result))["activation"]["root"], "/srv/cfg")

    def test_the_command_is_the_justfiles_activation_recipe(self):
        lines = (REPO_ROOT / "justfile").read_text().splitlines()
        for attribute in ("[macos]", "[linux]"):
            self.assertTrue(any(
                lines[i] == attribute and lines[i + 1].startswith("switch ")
                for i in range(len(lines) - 1)), attribute)
        self.assertEqual(view.ACTIVATE_COMMAND, "just switch")


CHANGED = Activation("/srv/p00", ("python/agent_tools/console/view.py",), "a" * 40)


class Fake:
    """A reader answering each call from a list: an Activation or None is returned, an exception raised."""

    def __init__(self, *steps):
        self.steps = list(steps)
        self.calls = []
        self.called = threading.Event()

    def __call__(self, roots):
        self.calls.append(list(roots))
        self.called.set()
        step = self.steps.pop(0) if len(self.steps) > 1 else self.steps[0]
        if isinstance(step, BaseException):
            raise step
        return step


ReadError = object()


def shown(svc):
    return json.loads(svc.view_bytes)["activation"]


class ActivationServiceTest(Trees):
    def setUp(self):
        super().setUp()
        self.store = self.tmp / "console" / "events.sqlite3"
        self.registry = self.tmp / "fleet" / "registry.json"
        support.write_registry(self.registry, support.entries(2))

    def opened(self, reader):
        svc = service.ConsoleService(
            self.store, self.registry, port=0, session_dirs=lambda: [], repo_of=lambda cwd: cwd,
            activation_reader=reader, activation_seconds=3600)
        self.addCleanup(svc.close)
        return svc

    def test_a_reading_with_changes_shows_the_line(self):
        svc = self.opened(Fake(CHANGED))
        svc.poll_activation()
        self.assertEqual(shown(svc), {
            "text": f"A console change merged at {'a' * 12} is not active on this host.",
            "state": "pending", "commit": "a" * 40, "root": "/srv/p00", "activate": True})

    def test_the_reader_is_given_the_registered_roots(self):
        reader = Fake(CHANGED)
        self.opened(reader).poll_activation()
        self.assertEqual(reader.calls[-1], ["/srv/p00", "/srv/p01"])

    def test_a_matching_reading_clears_the_line(self):
        svc = self.opened(Fake(CHANGED, CHANGED, Activation("/srv/p00", (), "a" * 40)))
        svc.poll_activation()
        rows, version = support.log_rows(self.store), svc.version
        svc.poll_activation()
        self.assertEqual(svc.version, version)
        svc.poll_activation()
        self.assertIsNone(shown(svc))
        self.assertEqual(svc.version, version + 1)
        self.assertEqual(support.log_rows(self.store), rows)

    def test_a_failing_read_keeps_the_last_line_and_says_so(self):
        svc = self.opened(Fake(CHANGED, RuntimeError("boom")))
        captured = io.StringIO()
        with contextlib.redirect_stderr(captured):
            svc.poll_activation()
            svc.poll_activation()
        self.assertEqual(shown(svc)["root"], "/srv/p00")
        self.assertEqual(captured.getvalue().splitlines(), ["console: activation_failed RuntimeError: boom"])

    def test_no_reader_starts_no_thread_and_shows_no_line(self):
        svc = support.service(self, self.store, self.registry)
        self.assertIsNone(shown(svc))
        self.assertNotIn(service.ACTIVATION_THREAD, [t.name for t in threading.enumerate()])

    def test_the_thread_reads_at_start_and_stops_on_close(self):
        reader = Fake(CHANGED)
        svc = support.service(
            self, self.store, self.registry, activation_reader=reader, activation_seconds=3600)
        self.assertTrue(reader.called.wait(5))
        self.assertEqual(len(reader.calls), 1)
        threads = [t for t in threading.enumerate() if t.name == service.ACTIVATION_THREAD]
        self.assertEqual(len(threads), 1)
        self.assertTrue(threads[0].is_alive())
        svc.close()
        self.assertFalse(threads[0].is_alive())

    def test_console_main_gives_the_service_an_activation_reader(self):
        recorded = {}

        def recorder(*args, **kwargs):
            recorded.update(kwargs)
            raise OSError("stop here")

        with mock.patch.object(console.service, "ConsoleService", recorder), \
                contextlib.redirect_stderr(io.StringIO()):
            console.main(["--port", "0"])
        self.assertTrue(callable(recorded["activation_reader"]))

    def test_a_failed_revision_read_keeps_the_line(self):
        for patcher in (mock.patch.object(activation, "integration_branch", lambda root: "main"),
                        mock.patch.dict(os.environ, {"GIT_CEILING_DIRECTORIES": str(self.tmp)})):
            patcher.start()
            self.addCleanup(patcher.stop)
        support.write_registry(self.registry, [{"project_id": "owner/cfg", "root": str(self.checkout)}])
        self.advance({f"{CONSOLE}/view.py": "from agent_tools.system import util\nVALUE = 2\n"})
        revisions = iter([self.built, None])
        svc = self.opened(reader_for(self.package_root, revision=lambda: next(revisions)))
        svc.poll_activation()
        self.assertEqual(shown(svc)["root"], str(self.checkout))
        version = svc.version
        captured = io.StringIO()
        with contextlib.redirect_stderr(captured):
            svc.poll_activation()
        self.assertEqual(shown(svc)["root"], str(self.checkout))
        self.assertEqual(svc.version, version)
        lines = captured.getvalue().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith("console: activation_failed ReadFailed: "), lines[0])

    def test_console_main_gives_the_reader_the_hosts_revision(self):
        recorded = {}

        def reader(*args, **kwargs):
            recorded.update(kwargs)
            return lambda roots: None

        def stop(*args, **kwargs):
            raise OSError("stop here")

        with mock.patch.object(console.activation, "reader_for", reader), \
                mock.patch.object(console.service, "ConsoleService", stop), \
                contextlib.redirect_stderr(io.StringIO()):
            console.main(["--port", "0"])
        self.assertIs(recorded["revision"], activation_run.host_revision)

    def test_a_failed_production_read_keeps_the_line(self):
        for patcher in (mock.patch.object(activation, "integration_branch", lambda root: "main"),
                        mock.patch.dict(os.environ, {"GIT_CEILING_DIRECTORIES": str(self.tmp)})):
            patcher.start()
            self.addCleanup(patcher.stop)
        support.write_registry(self.registry, [{"project_id": "owner/cfg", "root": str(self.checkout)}])
        self.advance({f"{CONSOLE}/view.py": "from agent_tools.system import util\nVALUE = 2\n"})
        svc = self.opened(reader_for(self.package_root, revision=lambda: self.built))
        svc.poll_activation()
        self.assertEqual(shown(svc)["root"], str(self.checkout))
        version = svc.version
        (self.checkout / ".git").rename(self.checkout / ".git-away")
        captured = io.StringIO()
        with contextlib.redirect_stderr(captured):
            svc.poll_activation()
        self.assertEqual(shown(svc)["root"], str(self.checkout))
        self.assertEqual(svc.version, version)
        lines = captured.getvalue().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith("console: activation_failed ReadFailed: "), lines[0])


class ActivatePageWriteTest(Trees):
    """The Activate page write (#1193): one run for the shown commit, held until its whole tree is gone."""

    def setUp(self):
        super().setUp()
        self.advance({f"{CONSOLE}/view.py": "VALUE = 2\n"})
        self.commit = git(self.checkout, "rev-parse", "origin/main").strip()
        self.store = self.tmp / "console" / "events.sqlite3"
        self.registry = self.tmp / "fleet" / "registry.json"
        support.write_registry(self.registry, support.entries(2))
        self.release = self.tmp / "release"
        self.ran = self.tmp / "ran"
        self.addCleanup(self.kill_trees)
        self.addCleanup(self.release.touch)

    def kill_trees(self):
        if not self.store.exists():
            return
        for _, _, kind, _, payload in support.log_rows(self.store):
            tree = json.loads(payload).get("tree") if kind == "activation.started" else None
            if isinstance(tree, str) and tree.startswith("group:"):
                activation_run.stop_tree(tree, signal.SIGKILL)

    def hold(self):
        return ("import time, pathlib\n"
                f"r = pathlib.Path({str(self.release)!r})\n"
                "end = time.time() + 30\n"
                "while not r.exists() and time.time() < end:\n    time.sleep(0.05)\n")

    def standin(self, tail="", head=""):
        return (head + "import subprocess, pathlib\n"
                f"open({str(self.ran)!r}, 'a').write("
                "subprocess.run(['git', 'rev-parse', 'HEAD'], capture_output=True, text=True)"
                ".stdout.strip() + '\\n')\n" + self.hold() + tail)

    def activator(self, body=None, tip=None):
        return activation_run.Activator(
            self.tmp / "state", command_of=lambda root: ([sys.executable, "-c", body or self.standin()], "."),
            revision=lambda: self.commit, tip=tip or (lambda root: self.commit), scoped=False)

    def reading(self):
        return Fake(Activation(str(self.checkout), (CONSOLE + "/view.py",), self.commit))

    def open(self, reader=None, activator=None, **kwargs):
        svc = support.service(
            self, self.store, self.registry, activation_reader=reader or self.reading(),
            activator=activator or self.activator(), activation_seconds=3600, **kwargs)
        svc.poll_activation()
        return svc

    def headers(self, svc, **changes):
        headers = {"Content-Type": "application/json", "Origin": f"http://127.0.0.1:{svc.address[1]}",
                   "X-Console-Token": svc.page_token, **changes}
        return {name: value for name, value in headers.items() if value is not None}

    def post(self, svc, body=None, **changes):
        body = {"commit": self.commit} if body is None else body
        return support.post_page(
            svc.address, "/api/activate", self.headers(svc, **changes), json.dumps(body).encode())

    def payloads(self, kind):
        return [json.loads(row[4]) for row in support.log_rows(self.store) if row[2] == kind]

    def kinds(self):
        return [row[2] for row in support.log_rows(self.store) if row[2].startswith("activation.")]

    def await_finished(self, count=1, seconds=20):
        deadline = time.monotonic() + seconds
        while len(self.payloads("activation.finished")) < count:
            self.assertLess(time.monotonic(), deadline, "no finished row")
            time.sleep(0.05)

    def await_file(self, path, seconds=10):
        deadline = time.monotonic() + seconds
        while not path.exists():
            self.assertLess(time.monotonic(), deadline, f"{path} never appeared")
            time.sleep(0.05)

    def test_an_activation_for_another_change_is_admitted(self):
        svc = self.open(reader=Fake(Activation(str(self.checkout), (), self.commit, (SKILL,))))
        status, _, body = self.post(svc)
        self.assertEqual((status, body), (204, b""))
        self.release.touch()
        self.await_finished()
        self.assertEqual(self.ran.read_text().splitlines(), [self.commit])

    def test_a_rollback_after_an_activated_run_offers_activate_again(self):
        pending = Activation(str(self.checkout), (), self.commit, (SKILL,))
        current = [pending]
        svc = self.open(reader=lambda roots: current[0])
        self.assertEqual((shown(svc)["state"], shown(svc)["activate"]), ("pending", True))
        self.assertEqual(self.post(svc)[0], 204)
        current[0] = None
        self.release.touch()
        self.await_finished()
        deadline = time.monotonic() + 20
        while shown(svc) is None or shown(svc)["state"] != "activated":
            self.assertLess(time.monotonic(), deadline, shown(svc))
            time.sleep(0.05)
        self.assertIs(shown(svc)["activate"], False)
        current[0] = pending
        svc.poll_activation()
        line = shown(svc)
        self.assertEqual((line["state"], line["commit"], line["activate"]), ("pending", self.commit, True))

    def await_state(self, svc, state):
        deadline = time.monotonic() + 20
        while shown(svc) is None or shown(svc)["state"] != state:
            self.assertLess(time.monotonic(), deadline, shown(svc))
            time.sleep(0.05)

    def refused_nothing(self, svc):
        deadline = time.monotonic() + 20
        while True:
            status, _, body = self.post(svc)
            if body.strip() != b"an activation is already running":
                return status, body.strip()
            self.assertLess(time.monotonic(), deadline, "the run's claim was never released")
            time.sleep(0.05)

    def test_a_failed_completion_read_does_not_offer_activate_again_for_the_same_commit(self):
        pending = Activation(str(self.checkout), (), self.commit, (SKILL,))
        steps = [pending]
        svc = self.open(reader=lambda roots: steps[0] if steps[0] is not ReadError else self.raise_read())
        self.assertEqual(self.post(svc)[0], 204)
        steps[0] = ReadError
        self.release.touch()
        self.await_finished()
        self.await_state(svc, "activated")
        self.assertIs(shown(svc)["activate"], False)
        self.assertEqual(self.refused_nothing(svc), (409, b"nothing to activate"))
        svc.poll_activation()
        self.assertEqual((shown(svc)["state"], shown(svc)["activate"]), ("activated", False))
        steps[0] = None
        svc.poll_activation()
        self.assertEqual((shown(svc)["state"], shown(svc)["activate"]), ("activated", False))
        steps[0] = pending
        svc.poll_activation()
        self.assertEqual((shown(svc)["state"], shown(svc)["activate"]), ("pending", True))
        self.assertEqual(len(self.payloads("activation.started")), 1)

    def raise_read(self):
        raise activation.ReadFailed("the revision could not be read")

    def test_a_poll_begun_before_completion_does_not_overwrite_the_refresh(self):
        pending = Activation(str(self.checkout), (), self.commit, (SKILL,))
        entered, gate, slow_calls = threading.Event(), threading.Event(), []
        refreshed = [False]

        def reader(roots):
            if threading.current_thread().name == "slow-poll":
                slow_calls.append(1)
                entered.set()
                self.assertTrue(gate.wait(20))
                return pending
            return None if refreshed[0] else pending

        svc = self.open(reader=reader)
        self.assertEqual(self.post(svc)[0], 204)
        slow = threading.Thread(target=svc.poll_activation, name="slow-poll")
        slow.start()
        self.addCleanup(slow.join)
        self.addCleanup(gate.set)
        self.assertTrue(entered.wait(20))
        refreshed[0] = True
        self.release.touch()
        self.await_finished()
        self.await_state(svc, "activated")
        gate.set()
        slow.join()
        self.assertEqual(len(slow_calls), 1)
        self.assertEqual((shown(svc)["state"], shown(svc)["activate"]), ("activated", False))
        self.assertEqual(self.refused_nothing(svc), (409, b"nothing to activate"))

    def test_a_failed_run_stays_retryable_after_the_hosts_revision_reached_the_tip(self):
        before = self.commit
        self.advance({SKILL: "demo v2\n"})
        self.commit = self.origin_commit()
        running_root = self.tmp / "pkg-tip"
        shutil.copytree(self.second_clone() / "python", running_root)
        host = [before]
        with mock.patch.object(activation, "integration_branch", lambda root: "main"):
            real = activation.reader_for(running_root, revision=lambda: host[0])
            svc = self.open(reader=lambda roots: real([str(self.checkout)]),
                            activator=self.activator("raise SystemExit(4)\n"))
            self.assertEqual((shown(svc)["state"], shown(svc)["activate"]), ("pending", True))
            status, _, body = self.post(svc)
            self.assertEqual((status, body.strip()), (204, b""))
            self.await_finished()
            (finished,) = self.payloads("activation.finished")
            self.assertIs(finished["ok"], False)
            host[0] = self.commit
            svc.poll_activation()
            self.assertIs(real([str(self.checkout)]).pending, False)
            line = shown(svc)
            self.assertEqual((line["state"], line["commit"], line["activate"]), ("failed", self.commit, True))
            deadline = time.monotonic() + 20
            while True:
                status, _, body = self.post(svc)
                if body.strip() != b"an activation is already running":
                    break
                self.assertLess(time.monotonic(), deadline, "the first run's claim was never released")
                time.sleep(0.05)
            self.assertEqual((status, body), (204, b""))
            self.await_finished(2)

    def test_a_failed_run_is_no_longer_retryable_a_day_after_it_finished_once_the_host_runs_the_commit(self):
        skew = [0.0]
        pending = Activation(str(self.checkout), (), self.commit, (SKILL,))
        host = [pending]
        svc = self.open(reader=lambda roots: host[0],
                        activator=self.activator("raise SystemExit(4)\n"),
                        clock=lambda: time.time() + skew[0])
        self.assertEqual((shown(svc)["state"], shown(svc)["activate"]), ("pending", True))
        status, _, body = self.post(svc)
        self.assertEqual((status, body.strip()), (204, b""))
        self.await_finished()
        host[0] = Activation(str(self.checkout), (), self.commit)
        svc.poll_activation()
        line = shown(svc)
        self.assertEqual((line["state"], line["activate"]), ("failed", True))
        skew[0] = 10 * 24 * 3600
        svc.poll_activation()
        svc._publish()
        self.assertIsNone(shown(svc))
        deadline = time.monotonic() + 20
        while True:
            status, _, body = self.post(svc)
            if body.strip() != b"an activation is already running":
                break
            self.assertLess(time.monotonic(), deadline, "the first run's claim was never released")
            time.sleep(0.05)
        self.assertEqual((status, body.strip()), (409, b"nothing to activate"))
        self.assertEqual(len(self.payloads("activation.started")), 1)

    def test_an_approved_activation_runs_the_stand_in_once_for_the_shown_commit(self):
        svc = self.open()
        status, _, body = self.post(svc)
        self.assertEqual((status, body), (204, b""))
        self.release.touch()
        self.await_finished()
        self.assertEqual(self.ran.read_text().splitlines(), [self.commit])
        self.assertNotEqual(self.commit, git(self.checkout, "rev-parse", "HEAD").strip())
        (started,) = self.payloads("activation.started")
        self.assertEqual((started["root"], started["commit"]), (str(self.checkout), self.commit))
        self.assertTrue(started["tree"].startswith("group:"))
        (finished,) = self.payloads("activation.finished")
        self.assertEqual(finished["root"], str(self.checkout))
        self.assertEqual(finished["commit"], self.commit)
        self.assertIs(finished["ok"], True)
        self.assertIsNone(finished["reason"])

    def test_an_activation_without_the_token_is_refused_and_runs_nothing(self):
        svc = self.open()
        for change in ({"X-Console-Token": None}, {"X-Console-Token": "wrong"}):
            status, _, body = self.post(svc, **change)
            self.assertEqual((status, body.strip()), (403, b"token refused"))
        status, _, body = self.post(svc, Origin="http://example.invalid")
        self.assertEqual((status, body.strip()), (403, b"origin refused"))
        self.assertFalse(self.ran.exists())
        self.assertEqual(self.kinds(), [])

    def test_a_second_activation_while_one_runs_is_refused(self):
        svc = self.open()
        self.assertEqual(self.post(svc)[0], 204)
        status, _, body = self.post(svc)
        self.assertEqual((status, body.strip()), (409, b"an activation is already running"))
        self.release.touch()
        self.await_finished()
        self.assertEqual(self.ran.read_text().splitlines(), [self.commit])
        self.assertEqual(len(self.payloads("activation.started")), 1)

    def test_a_second_activation_is_refused_while_a_descendant_of_the_first_runs(self):
        body = ("import subprocess, sys\n"
                f"subprocess.Popen([sys.executable, '-c', {self.hold()!r}])\n")
        svc = self.open(activator=self.activator(body))
        self.assertEqual(self.post(svc)[0], 204)
        self.await_file(self.tmp / "state" / "activation.result")
        status, _, answer = self.post(svc)
        self.assertEqual((status, answer.strip()), (409, b"an activation is already running"))
        self.assertEqual(self.payloads("activation.finished"), [])
        self.release.touch()
        self.await_finished()
        (finished,) = self.payloads("activation.finished")
        self.assertIs(finished["ok"], True)

    def test_an_activation_for_a_commit_that_is_not_the_shown_tip_is_refused(self):
        svc = self.open(activator=self.activator(tip=lambda root: "f" * 40))
        status, _, body = self.post(svc, {"commit": "f" * 40})
        self.assertEqual(
            (status, body.strip()),
            (409, b"that version is no longer the latest main version on origin"))
        self.assertEqual(self.kinds(), [])
        self.assertFalse(self.ran.exists())

    def test_an_activation_after_the_tip_moved_is_refused(self):
        svc = self.open(activator=self.activator(tip=lambda root: "e" * 40))
        status, _, body = self.post(svc)
        self.assertEqual(
            (status, body.strip()),
            (409, b"that version is no longer the latest main version on origin"))
        self.assertEqual(self.kinds(), [])

        def unreadable(root):
            raise activation.ReadFailed("x")

        other = self.open(activator=self.activator(tip=unreadable))
        status, _, body = self.post(other)
        self.assertEqual(
            (status, body.strip()),
            (409, b"the latest main version on origin could not be read"))
        self.assertEqual(self.kinds(), [])
        self.assertFalse(self.ran.exists())

    def test_an_activation_with_no_line_shown_is_refused(self):
        svc = self.open(reader=Fake(None))
        status, _, body = self.post(svc)
        self.assertEqual((status, body.strip()), (409, b"nothing to activate"))
        self.assertEqual(self.kinds(), [])

    def scoped_activator(self, popen):
        def systemctl_inactive(argv, **kwargs):
            if argv[0] != "systemctl":
                return subprocess.run(argv, **kwargs)
            return subprocess.CompletedProcess(argv, 0, stdout="inactive\n")

        return activation_run.Activator(
            self.tmp / "state", command_of=lambda root: ([sys.executable, "-c", "pass"], "."),
            revision=lambda: self.commit, tip=lambda root: self.commit, scoped=True, popen=popen,
            run=systemctl_inactive)

    def test_the_started_row_is_committed_before_the_run_launches(self):
        seen = []

        class Process:
            pid = 4242

            def poll(self):
                return 0

        def popen(argv, **kwargs):
            seen.append(self.kinds())
            return Process()

        svc = self.open(activator=self.scoped_activator(popen))
        self.assertEqual(self.post(svc)[0], 204)
        self.await_finished()
        self.assertEqual(seen, [["activation.started"]])

    def test_a_started_row_that_cannot_be_written_launches_nothing(self):
        launched = []

        def popen(*args, **kwargs):
            launched.append(args)
            raise OSError("no launch in this test")

        svc = self.open(activator=self.scoped_activator(popen))
        append = svc.log.append

        def refuse_started(entries):
            if any(kind == "activation.started" for kind, _, _ in entries):
                raise sqlite3.OperationalError("database is locked")
            return append(entries)

        with mock.patch.object(svc.log, "append", refuse_started):
            self.assertEqual(self.post(svc)[0], 204)
        (finished,) = self.payloads("activation.finished")
        self.assertIs(finished["ok"], False)
        self.assertIn("database is locked", finished["reason"])
        self.assertEqual(self.payloads("activation.started"), [])
        self.assertEqual(launched, [])
        self.assertEqual(self.post(svc)[0], 204)
        self.assertEqual(len(launched), 1)

    def test_a_bad_activation_body_is_refused(self):
        svc = self.open()
        for body in ({}, {"commit": "ABC"}, {"commit": self.commit, "x": 1}):
            status, _, answer = self.post(svc, body)
            self.assertEqual((status, answer.strip()), (400, b"bad activation"), body)
        self.assertEqual(self.kinds(), [])

    def test_a_run_cut_by_a_restart_is_settled_from_its_recorded_exit(self):
        body = self.standin(tail="print('switch-to-configuration failed')\nraise SystemExit(4)\n")
        first = self.open(activator=self.activator(body))
        self.assertEqual(self.post(first)[0], 204)
        first.close()
        self.assertEqual(self.payloads("activation.finished"), [])
        second = self.open(activator=self.activator(body))
        status, _, answer = self.post(second)
        self.assertEqual((status, answer.strip()), (409, b"an activation is already running"))
        self.release.touch()
        self.await_finished()
        (finished,) = self.payloads("activation.finished")
        self.assertIs(finished["ok"], False)
        self.assertEqual(
            finished["reason"], "the activation command exited 4 (switch-to-configuration failed)")

    def test_a_started_row_without_a_tree_is_settled_as_unrecorded(self):
        log = EventLog(self.store)
        log.append([("activation.started", None, {"root": str(self.checkout), "commit": self.commit})])
        log.close()
        self.open()
        (finished,) = self.payloads("activation.finished")
        self.assertIs(finished["ok"], False)
        self.assertEqual(finished["reason"], activation_run.UNRECORDED_REASON)
        self.assertIsNotNone(finished["next_step"])

    def test_closing_during_a_run_appends_no_finished_row(self):
        svc = self.open()
        self.assertEqual(self.post(svc)[0], 204)
        (started,) = self.payloads("activation.started")
        began = time.monotonic()
        svc.close()
        self.assertLess(time.monotonic() - began, 15)
        self.assertEqual(self.payloads("activation.finished"), [])
        self.assertTrue(activation_run.tree_alive(started["tree"]))

    def test_console_main_gives_the_service_an_activator(self):
        recorded = {}

        def recorder(*args, **kwargs):
            recorded.update(kwargs)
            raise OSError("stop here")

        with mock.patch.object(console.service, "ConsoleService", recorder), \
                contextlib.redirect_stderr(io.StringIO()):
            console.main(["--port", "0"])
        self.assertIsInstance(recorded["activator"], activation_run.Activator)


class ActivationRunTest(Trees):
    """The activation runner (#1193): the command, run in its own clone, judged by its recorded exit."""

    def setUp(self):
        super().setUp()
        self.advance({f"{CONSOLE}/view.py": "VALUE = 2\n"})
        self.commit = git(self.checkout, "rev-parse", "origin/main").strip()
        self.state = self.tmp / "state"
        self.release = self.tmp / "release"
        self.addCleanup(self.release.touch)

    def script(self, body):
        return [sys.executable, "-c", body]

    def activator(self, body, **seams):
        seams.setdefault("revision", lambda: self.commit)
        seams.setdefault("scoped", False)
        argv = seams.pop("argv", None) or self.script(body)
        seams.setdefault("command_of", lambda root: (argv, "."))
        return Activator(self.state, **seams)

    def started(self, activator, commit=None):
        run = activator.start(str(self.checkout), commit or self.commit)
        self.assertIsInstance(run, activation_run.Run, run)
        pgid = int(run.tree.removeprefix("group:")) if run.tree.startswith("group:") else None
        if pgid is not None:
            self.addCleanup(lambda: activation_run.stop_tree(run.tree, signal.SIGKILL))
        return run

    def act(self, activator, commit=None):
        return activator.wait(self.started(activator, commit), threading.Event())

    def snapshot_checkout(self):
        worktrees = self.checkout / ".git/worktrees"
        return (git(self.checkout, "for-each-ref"), git(self.checkout, "worktree", "list", "--porcelain"),
                sorted(path.name for path in worktrees.iterdir()) if worktrees.exists() else [])

    def await_file(self, path, seconds=10):
        deadline = time.monotonic() + seconds
        while not path.exists():
            self.assertLess(time.monotonic(), deadline, f"{path} never appeared")
            time.sleep(0.05)

    def hold(self, extra=""):
        return ("import time, pathlib\n"
                f"r = pathlib.Path({str(self.release)!r})\n"
                "end = time.time() + 30\n"
                "while not r.exists() and time.time() < end:\n    time.sleep(0.05)\n" + extra)

    def test_a_run_executes_the_command_in_a_tree_at_the_commit(self):
        marker = self.tmp / "marker"
        body = ("import subprocess, pathlib\n"
                f"pathlib.Path({str(marker)!r}).write_text(subprocess.run(['git', 'rev-parse', 'HEAD'], "
                "capture_output=True, text=True).stdout.strip())\n")
        a = self.activator(body)
        run = self.started(a)
        outcome = a.wait(run, threading.Event())
        self.assertEqual(outcome, Outcome(self.commit, True))
        self.assertEqual(marker.read_text(), self.commit)
        self.assertNotEqual(self.commit, git(self.checkout, "rev-parse", "HEAD").strip())
        self.assertTrue(run.tree.startswith("group:"))

    def test_the_run_writes_nothing_to_the_checkout(self):
        git(self.checkout, "worktree", "add", "-q", "--detach", str(self.tmp / "gone"))
        shutil.rmtree(self.tmp / "gone")
        a = self.activator("pass")
        self.advance({f"{CONSOLE}/view.py": "VALUE = 3\n"})
        newer = git(self.checkout, "rev-parse", "origin/main").strip()
        before = self.snapshot_checkout()
        self.act(a)
        self.act(a, newer)
        self.assertEqual(self.snapshot_checkout(), before)
        self.assertIn("gone", git(self.checkout, "worktree", "list", "--porcelain"))

    def test_a_second_run_moves_the_tree_to_its_commit(self):
        marker = self.tmp / "marker"
        body = ("import subprocess, pathlib\n"
                f"pathlib.Path({str(marker)!r}).write_text(subprocess.run(['git', 'rev-parse', 'HEAD'], "
                "capture_output=True, text=True).stdout.strip())\n")
        a = self.activator(body)
        self.act(a)
        self.advance({f"{CONSOLE}/view.py": "VALUE = 3\n"})
        newer = git(self.checkout, "rev-parse", "origin/main").strip()
        self.assertNotEqual(newer, self.commit)
        self.act(a, newer)
        self.assertEqual(marker.read_text(), newer)

    def test_a_failing_command_reports_its_exit_and_last_line(self):
        a = self.activator("import sys\nprint('first\\nsudo: a password is required', end='')\nsys.exit(3)\n")
        outcome = self.act(a)
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.reason, "the activation command exited 3 (sudo: a password is required)")
        self.assertEqual(outcome.next_step, NEXT_STEP.format(log=self.state / "activation.log"))
        self.assertIn("first", (self.state / "activation.log").read_text())

    def test_a_mismatched_revision_is_a_failure(self):
        outcome = self.act(self.activator("pass", revision=lambda: "b" * 40))
        self.assertEqual(
            outcome.reason, f"the activation command finished but this host runs {'b' * 12}")
        outcome = self.act(self.activator("pass", revision=lambda: None))
        self.assertEqual(
            outcome.reason, "the activation command finished but this host's revision could not be read")

    def test_a_command_that_cannot_start_is_a_failure(self):
        outcome = self.act(self.activator("", argv=[str(self.tmp / "absent")]))
        self.assertFalse(outcome.ok)
        self.assertTrue(
            outcome.reason.startswith("the activation command could not start (FileNotFoundError"),
            outcome.reason)

    def test_a_run_past_its_time_ends_its_whole_tree(self):
        marker = self.tmp / "grandchild"
        body = ("import subprocess, sys, time, pathlib\n"
                "g = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
                f"pathlib.Path({str(marker)!r}).write_text(str(g.pid))\n"
                "time.sleep(60)\n")
        a = self.activator(body, seconds=1)
        run = self.started(a)
        began = time.monotonic()
        outcome = a.wait(run, threading.Event())
        self.assertLess(time.monotonic() - began, 15)
        self.assertEqual(
            outcome.reason, "the activation ran longer than 0 minutes and was stopped")
        with self.assertRaises(ProcessLookupError):
            os.kill(int(marker.read_text()), 0)

    def test_the_run_is_not_finished_while_a_descendant_lives(self):
        grandchild = ("import subprocess, sys\n"
                      f"subprocess.Popen([sys.executable, '-c', {self.hold()!r}])\n")
        a = self.activator(grandchild)
        run = self.started(a)
        results = []
        thread = threading.Thread(target=lambda: results.append(a.wait(run, threading.Event())))
        thread.start()
        self.addCleanup(thread.join, 20)
        self.await_file(self.state / "activation.result")
        time.sleep(1.5)
        self.assertTrue(thread.is_alive())
        self.release.touch()
        thread.join(10)
        self.assertEqual(results, [Outcome(self.commit, True)])

    def test_a_stop_leaves_the_run_going_and_records_nothing(self):
        a = self.activator(self.hold())
        run = self.started(a)
        stop = threading.Event()
        threading.Timer(0.5, stop.set).start()
        began = time.monotonic()
        with self.assertRaises(Stopped):
            a.wait(run, stop)
        self.assertLess(time.monotonic() - began, 5)
        self.assertTrue(activation_run.tree_alive(run.tree))
        self.assertFalse((self.state / "activation.result").exists())
        self.release.touch()

    def test_a_restarted_console_reads_the_runs_recorded_failure(self):
        a = self.activator(self.hold("print('switch-to-configuration failed')\nraise SystemExit(4)\n"))
        run = self.started(a)
        stopped = threading.Event()
        stopped.set()
        with self.assertRaises(Stopped):
            a.wait(run, stopped)
        self.release.touch()
        restarted = Activator(self.state, revision=lambda: self.commit, scoped=False)
        self.assertEqual(
            restarted.wait(run, threading.Event()),
            Outcome(self.commit, False, "the activation command exited 4 (switch-to-configuration failed)",
                    NEXT_STEP.format(log=self.state / "activation.log")))

    def test_a_scoped_launch_runs_in_its_own_user_scope(self):
        launched = {}

        class Process:
            pid = 4242

            def poll(self):
                return 0

        def popen(argv, **kwargs):
            launched.update(argv=argv, kwargs=kwargs)
            return Process()

        run = self.activator("pass", scoped=True, popen=popen).start(str(self.checkout), self.commit)
        argv = launched["argv"]
        self.assertEqual(argv[:5], ["systemd-run", "--user", "--scope", "--quiet", "--collect"])
        self.assertRegex(argv[5], r"^--unit=agent-console-activation-[0-9a-f]{12}-[0-9a-f]{8}$")
        self.assertEqual(
            argv[argv.index("--") + 1:][:4],
            [sys.executable, "-m", "agent_tools.console.activation_run", "record"])
        self.assertIs(launched["kwargs"]["start_new_session"], True)
        self.assertIn("PYTHONPATH", launched["kwargs"]["env"])
        self.assertEqual(run.tree, "scope:" + argv[5][len("--unit="):] + ".scope")

    def test_a_scoped_run_is_recorded_before_its_process_launches(self):
        order = []

        class Process:
            pid = 4242

            def poll(self):
                return 0

        def popen(argv, **kwargs):
            order.append("launch")
            return Process()

        a = self.activator("pass", scoped=True, popen=popen)
        run = a.start(str(self.checkout), self.commit, lambda run: order.append(("record", run.tree)))
        self.assertEqual(order, [("record", run.tree), "launch"])
        self.assertTrue(run.tree.startswith("scope:"))

    def test_a_scoped_run_whose_record_fails_launches_nothing(self):
        def popen(*args, **kwargs):
            raise AssertionError("nothing may be launched")

        def record(run):
            raise sqlite3.OperationalError("database is locked")

        a = self.activator("pass", scoped=True, popen=popen)
        with self.assertRaises(sqlite3.OperationalError):
            a.start(str(self.checkout), self.commit, record)

    def test_a_group_run_whose_record_fails_is_killed(self):
        launched = []

        def popen(argv, **kwargs):
            process = subprocess.Popen(argv, **kwargs)
            launched.append(process)
            return process

        def record(run):
            raise sqlite3.OperationalError("database is locked")

        a = self.activator(self.hold(), popen=popen)
        with self.assertRaises(sqlite3.OperationalError):
            a.start(str(self.checkout), self.commit, record)
        self.addCleanup(lambda: launched[0].poll() is None and launched[0].kill())
        self.assertIsNotNone(launched[0].poll())
        self.assertFalse(activation_run.tree_alive(f"group:{launched[0].pid}"))

    def test_the_record_command_runs_under_the_consoles_own_isolation(self):
        launched = []

        class Process:
            pid = 4242

            def poll(self):
                return 0

        def popen(argv, **kwargs):
            launched.append(argv)
            return Process()

        for isolated in (0, 1):
            with self.subTest(isolated=isolated), \
                    mock.patch.object(sys, "flags", mock.Mock(isolated=isolated)):
                self.activator("pass", popen=popen).start(str(self.checkout), self.commit)
                argv = launched[-1]
                self.assertEqual(
                    argv[:argv.index("record")],
                    [sys.executable, *(["-I"] if isolated else []), "-m",
                     "agent_tools.console.activation_run"])

    def test_a_launched_child_not_yet_reaped_keeps_the_run_alive(self):
        # Before systemd-run registers the scope, systemctl shows the unit as inactive (exit 0).
        polls = []

        class Process:
            pid = 4242

            def poll(self):
                polls.append(None)
                return None if len(polls) < 3 else 0

        def inactive(argv, **kwargs):
            if argv[0] != "systemctl":
                return subprocess.run(argv, **kwargs)
            return subprocess.CompletedProcess(argv, 0, stdout="inactive\n")

        a = self.activator("pass", scoped=True, popen=lambda argv, **kwargs: Process(), run=inactive)
        run = a.start(str(self.checkout), self.commit)
        self.assertIsInstance(run, activation_run.Run, run)
        a.wait(run, threading.Event())
        self.assertGreaterEqual(len(polls), 3)

    def test_a_scope_tree_reads_its_state_from_systemctl(self):
        calls = []

        def answer(code, out):
            def fake(argv, **kwargs):
                calls.append(argv)
                return subprocess.CompletedProcess(argv, code, stdout=out)
            return fake

        def broken(argv, **kwargs):
            raise OSError("no systemctl")

        self.assertTrue(activation_run.tree_alive("scope:u.scope", run=answer(0, "active\n")))
        self.assertFalse(activation_run.tree_alive("scope:u.scope", run=answer(0, "inactive\n")))
        self.assertTrue(activation_run.tree_alive("scope:u.scope", run=answer(1, "")))
        self.assertTrue(activation_run.tree_alive("scope:u.scope", run=broken))
        self.assertEqual(
            calls[0], ["systemctl", "--user", "show", "--property=ActiveState", "--value", "u.scope"])
        calls.clear()
        activation_run.stop_tree("scope:u.scope", signal.SIGTERM, run=answer(0, ""))
        self.assertEqual(calls, [["systemctl", "--user", "kill", "--signal=SIGTERM", "u.scope"]])

    def manifest_home(self):
        home = Path(tempfile.mkdtemp(dir=accounts_sandbox.root())).resolve()
        previous = os.environ["HOME"]
        os.environ["HOME"] = str(home)
        self.addCleanup(os.environ.__setitem__, "HOME", previous)
        self.addCleanup(shutil.rmtree, home, True)
        (home / ".agents/share").mkdir(parents=True)
        shutil.copy(REPO_ROOT / "home/common/agent-skills/platform-manifest.json",
                    home / ".agents/share/platform-manifest.json")

    def contract_root(self, production=None) -> Path:
        """A project root carrying this repository's contract, with `production` added when given."""
        root = self.tmp / "contract-root"
        (root / ".agents/instructions").mkdir(parents=True)
        contract = json.loads((REPO_ROOT / ".agents/project.json").read_text(encoding="utf-8"))
        if production is not None:
            contract["production"] = production
        (root / ".agents/project.json").write_text(json.dumps(contract), encoding="utf-8")
        for name in (".agents/instructions/bootstrap.md", "AGENTS.md", "CLAUDE.md"):
            shutil.copy(REPO_ROOT / name, root / name)
        return root

    def test_the_activation_command_is_the_contracts_console_activation(self):
        self.manifest_home()
        root = self.contract_root({
            "none": False,
            "changes": {"commands": ["nix-activate"], "key_files": [], "mcp_tools": []},
            "read_only": {"commands": ["nix-build"], "mcp_tools": []},
            "release_profile": "github-release",
            "console_activation": "nix-activate"})
        self.assertEqual(activation_run.activation_command(str(root)), (["just", "switch"], "."))

    def test_this_repositorys_own_contract_names_nix_activate_as_its_console_activation(self):
        self.manifest_home()
        self.assertEqual(activation_run.activation_command(str(REPO_ROOT)), (["just", "switch"], "."))

    def test_a_contract_without_console_activation_names_no_command(self):
        self.manifest_home()
        with self.assertRaises(Refused):
            activation_run.activation_command(str(self.checkout))

        def refuse(root):
            raise Refused("x")

        def popen(*args, **kwargs):
            raise AssertionError("nothing may be launched")

        a = Activator(self.state, command_of=refuse, popen=popen, scoped=False)
        self.assertEqual(
            a.start(str(self.checkout), self.commit),
            Outcome(self.commit, False, "x", NEXT_STEP.format(log=self.state / "activation.log")))

    def test_host_revision_reads_the_configuration_revision(self):
        seen = []

        def answer(code, out):
            def fake(argv, **kwargs):
                seen.append(argv)
                return subprocess.CompletedProcess(argv, code, stdout=out)
            return fake

        def broken(argv, **kwargs):
            raise OSError("absent")

        self.assertEqual(activation_run.host_revision("linux", run=answer(0, "a" * 40 + "\n")), "a" * 40)
        self.assertEqual(seen[0][0], "/run/current-system/sw/bin/nixos-version")
        self.assertIsNone(activation_run.host_revision("linux", run=answer(1, "a" * 40)))
        self.assertIsNone(activation_run.host_revision("linux", run=answer(0, "x")))
        self.assertIsNone(activation_run.host_revision("linux", run=broken))


if __name__ == "__main__":
    unittest.main()
