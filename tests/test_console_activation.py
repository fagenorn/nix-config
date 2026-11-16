"""The activation reading (#1114): which console files this host runs behind origin's integration branch."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent_tools.console import activation, view
from agent_tools.console.activation import (
    Activation, blob_id, console_files, origin_files, reader_for, reading)
from agent_tools.project_contract import resolve_project

from . import accounts_sandbox
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
}


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

    def read(self, roots=None, **seams):
        seams.setdefault("branch_of", lambda root: "main")
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
        self.assertEqual(self.read(), Activation(str(self.checkout), ()))

    def test_a_console_file_behind_origin_is_named(self):
        self.advance({f"{CONSOLE}/view.py": "from agent_tools.system import util\nVALUE = 2\n"})
        self.assertEqual(self.read().changed, (f"{CONSOLE}/view.py",))

    def test_the_manager_contract_behind_origin_is_named(self):
        self.advance({f"{CONSOLE}/manager-contract.md": "contract v2\n"})
        self.assertEqual(self.read().changed, (f"{CONSOLE}/manager-contract.md",))

    def test_an_imported_module_behind_origin_is_named(self):
        self.advance({"python/agent_tools/system/util.py": "X = 2\n"})
        self.assertEqual(self.read().changed, ("python/agent_tools/system/util.py",))

    def test_a_change_outside_the_console_files_is_not_named(self):
        self.advance({"docs/notes.md": "more\n", "python/agent_tools/verification/other.py": "Y = 2\n"})
        self.assertEqual(self.read().changed, ())

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
            Activation(str(self.checkout), ()))

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
        with mock.patch.object(activation.resolve_project, "resolve", side_effect=broken):
            with self.assertRaises(activation.ReadFailed):
                activation.integration_branch(str(REPO_ROOT))

    def test_reader_for_reads_the_running_files_once(self):
        reader = reader_for(self.package_root)
        (self.package_root / "agent_tools/console/view.py").write_text("VALUE = 9\n")
        with mock.patch.object(activation, "integration_branch", lambda root: "main"):
            self.assertEqual(reader([str(self.checkout)]).changed, ())


class ActivationViewTest(Trees):
    def line(self, root):
        return {"text": f"A console change merged and is not active on this host: run just switch in {root}.",
                "command": "just switch", "root": root}

    def read(self):
        return reading([str(self.checkout)], console_files(self.package_root), branch_of=lambda r: "main")

    def test_a_console_file_behind_origin_shows_the_line(self):
        self.advance({"python/agent_tools/console/view.py": "from agent_tools.system import util\nVALUE = 2\n"})
        result = view.derive_view([], activation=self.read())
        self.assertEqual(result["activation"], self.line(str(self.checkout)))

    def test_a_matching_tree_shows_no_line(self):
        self.assertIsNone(view.derive_view([], activation=self.read())["activation"])

    def test_a_difference_outside_the_console_files_shows_no_line(self):
        self.advance({"docs/notes.md": "more\n", "python/agent_tools/verification/other.py": "Y = 2\n"})
        self.assertIsNone(view.derive_view([], activation=self.read())["activation"])

    def test_no_reading_shows_no_line(self):
        self.assertIsNone(view.derive_view([])["activation"])
        self.assertIsNone(view.derive_view([], activation=None)["activation"])

    def test_the_line_is_not_an_inbox_item(self):
        result = view.derive_view(
            [], activation=Activation("/srv/cfg", ("python/agent_tools/console/view.py",)))
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


if __name__ == "__main__":
    unittest.main()
