"""The activation reading (#1114): which console files this host runs behind origin's integration branch."""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import signal
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
from agent_tools.console.activation_run import NEXT_STEP, Activator, Outcome, Refused, Stopped
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

    def origin_commit(self) -> str:
        return git(self.checkout, "rev-parse", "refs/remotes/origin/main").strip()

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
            [], activation=Activation("/srv/cfg", ("python/agent_tools/console/view.py",), "a" * 40))
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
        self.act(a)
        self.advance({f"{CONSOLE}/view.py": "VALUE = 3\n"})
        before = self.snapshot_checkout()
        self.act(a, git(self.checkout, "rev-parse", "origin/main").strip())
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

    def test_the_activation_command_is_the_contracts_console_activation(self):
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
