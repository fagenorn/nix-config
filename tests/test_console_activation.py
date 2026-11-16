"""The activation reading (#1114): which console files this host runs behind origin's integration branch."""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from agent_tools.console import activation, console, service, view
from agent_tools.console.activation import (
    Activation, blob_id, console_files, origin_files, reader_for, reading)
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

    def test_a_checkout_behind_the_compared_origin_is_marked_behind(self):
        self.assertFalse(self.read().local_behind)
        self.advance({f"{CONSOLE}/view.py": "from agent_tools.system import util\nVALUE = 2\n"})
        self.assertTrue(self.read().local_behind)

    def test_a_checkout_that_already_holds_the_origin_change_is_not_behind(self):
        self.advance({f"{CONSOLE}/view.py": "from agent_tools.system import util\nVALUE = 2\n"})
        git(self.checkout, "merge", "-q", "--ff-only", "origin/main")
        result = self.read()
        self.assertEqual(result.changed, (f"{CONSOLE}/view.py",))
        self.assertFalse(result.local_behind)

    def test_a_failed_read_of_the_checkout_counts_as_behind(self):
        self.advance({f"{CONSOLE}/view.py": "from agent_tools.system import util\nVALUE = 2\n"})
        git(self.checkout, "merge", "-q", "--ff-only", "origin/main")

        def failing(root):
            raise activation.ReadFailed("no head")

        self.assertTrue(self.read(local=failing).local_behind)

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
    def line(self, root, tail="."):
        return {"text": f"A console change merged and is not active on this host: run just switch in {root}{tail}",
                "command": "just switch", "root": root}

    def read(self):
        return reading([str(self.checkout)], console_files(self.package_root), branch_of=lambda r: "main")

    def test_a_console_file_behind_origin_shows_the_line_after_the_checkout_is_updated(self):
        self.advance({"python/agent_tools/console/view.py": "from agent_tools.system import util\nVALUE = 2\n"})
        result = view.derive_view([], activation=self.read())
        self.assertEqual(
            result["activation"],
            self.line(str(self.checkout), " once it is updated to origin's integration branch."))

    def test_an_updated_checkout_shows_the_plain_line(self):
        self.advance({"python/agent_tools/console/view.py": "from agent_tools.system import util\nVALUE = 2\n"})
        git(self.checkout, "merge", "-q", "--ff-only", "origin/main")
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


CHANGED = Activation("/srv/p00", ("python/agent_tools/console/view.py",))


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
            "text": "A console change merged and is not active on this host: run just switch in /srv/p00.",
            "command": "just switch", "root": "/srv/p00"})

    def test_the_reader_is_given_the_registered_roots(self):
        reader = Fake(CHANGED)
        self.opened(reader).poll_activation()
        self.assertEqual(reader.calls[-1], ["/srv/p00", "/srv/p01"])

    def test_a_matching_reading_clears_the_line(self):
        svc = self.opened(Fake(CHANGED, CHANGED, Activation("/srv/p00", ())))
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

    def test_a_failed_production_read_keeps_the_line(self):
        for patcher in (mock.patch.object(activation, "integration_branch", lambda root: "main"),
                        mock.patch.dict(os.environ, {"GIT_CEILING_DIRECTORIES": str(self.tmp)})):
            patcher.start()
            self.addCleanup(patcher.stop)
        support.write_registry(self.registry, [{"project_id": "owner/cfg", "root": str(self.checkout)}])
        self.advance({f"{CONSOLE}/view.py": "from agent_tools.system import util\nVALUE = 2\n"})
        svc = self.opened(reader_for(self.package_root))
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


if __name__ == "__main__":
    unittest.main()
