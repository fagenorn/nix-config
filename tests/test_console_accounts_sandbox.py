"""The accounts sandbox (#1027): no test writes to the real accounts directory.

Every launcher-running test module binds the module fixture of
`tests.accounts_sandbox`, which points HOME, CLAUDE_ACCOUNTS_DIR and
CLAUDE_CONFIG_DIR at one temporary root, so a dropped or replaced environment
lands there and never in the owner's real accounts directory.

Run: just agent-workflow-tests
"""

from __future__ import annotations

import importlib
import json
import os
import pwd
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from subprocess import DEVNULL

from . import accounts_sandbox
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)

ROOT = Path(__file__).resolve().parents[1]
EXTRA_MODULES = ("test_claude_account_routing", "test_claude_code_installed")
OWNER_NAMED = (
    "test_console_account_add", "test_console_account_service", "test_console_signin",
    "test_console_signin_run", "test_console_signin_service", "test_console_manager",
    "test_console_manager_service", "test_console_probe", "test_console_nudge",
    "test_console_capacity_check", "test_console_cleanup_check", "test_console_manager_check",
    "test_console_message_check", "test_console_revive_check", "test_claude_account_routing",
    "test_claude_code_installed",
)

CHILD_FIXTURE = """
import json, os
from pathlib import Path
import tests.accounts_sandbox as s

NAMES = ("HOME", "CLAUDE_ACCOUNTS_DIR", "CLAUDE_CONFIG_DIR")
def read():
    return {v: os.environ.get(v) for v in NAMES}

before = read()
s.setUpModule()
first = str(s.root())
inside = read()
s.setUpModule()
second = str(s.root())
s.tearDownModule()
still = str(s.root())
s.tearDownModule()
after = read()
print(json.dumps({
    "before": before, "first": first, "inside": inside, "second": second, "still": still,
    "after": after, "exists": Path(first).exists(), "root_after": s.root(),
}))
"""

CHILD_REAL_DIRS = """
import json
import tests.accounts_sandbox as s

s.setUpModule()
print(json.dumps([str(p) for p in s.real_accounts_dirs()]))
"""

CHILD = """
import json, os, sys, unittest
VARIABLES = ("HOME", "CLAUDE_ACCOUNTS_DIR", "CLAUDE_CONFIG_DIR")
start = {v: os.environ.get(v) for v in VARIABLES}
from pathlib import Path
from agent_tools.console import account_add
from tests import accounts_sandbox
record, dirs, modules = sys.argv[1], json.loads(sys.argv[2]), sys.argv[3:]
before = {d: accounts_sandbox.accounts_snapshot(Path(d)) for d in dirs}
calls = []
original = account_add.Adder.__call__
def dropped(self, name):
    self._environ = None
    try:
        return original(self, name)
    finally:
        accounts = os.environ.get("CLAUDE_ACCOUNTS_DIR")
        calls.append({"name": name, "accounts": accounts,
                      "created": bool(accounts) and os.path.isdir(os.path.join(accounts, "profiles", name))})
account_add.Adder.__call__ = dropped
unittest.main(module=None, argv=["child", *modules], exit=False)
after = {d: accounts_sandbox.accounts_snapshot(Path(d)) for d in dirs}
with open(record, "w") as handle:
    json.dump({"start": start, "before": before, "after": after, "calls": calls}, handle)
"""

PROBE = """
import sys
for path in sys.argv[1:]:
    try:
        open(path, "w").close()
    except OSError:
        pass
"""


def covered_modules() -> list[str]:
    stems = {path.stem for path in (ROOT / "tests").glob("test_console_*.py")}
    return sorted(stems | set(EXTRA_MODULES))


def child_env(root: Path, **overrides: str) -> dict[str, str]:
    env = dict(os.environ)
    env.pop("CLAUDE_CONFIG_DIR", None)
    env.update(overrides)
    env["PYTHONPATH"] = f"{root / 'python'}{os.pathsep}{root}"
    return env


def tree(base: Path) -> Path:
    acc = base / "acc"
    (acc / "switch").mkdir(parents=True)
    (acc / "chosen-profile").write_text("p1\n")
    (acc / "bindings.tsv").write_text("a\tp1\n")
    (acc / "switch" / "1").write_text("")
    profile = acc / "profiles" / "p1"
    profile.mkdir(parents=True)
    profile.chmod(0o700)
    (profile / "settings.json").symlink_to("/x/.claude/settings.json")
    (profile / ".claude.json").write_text("{}")
    (profile / ".claude.json").chmod(0o600)
    (profile / "history-own").write_text("h")
    return acc


class Recorder:
    def __init__(self, rc: int = 0, raises: BaseException | None = None):
        self.calls: list[list[str]] = []
        self.rc = rc
        self.raises = raises

    def __call__(self, args, **kw):
        self.calls.append(list(args))
        if self.raises is not None:
            raise self.raises
        return subprocess.CompletedProcess(args, self.rc)


class WhichRecorder:
    def __init__(self, found: str | None):
        self.found = found
        self.calls: list[str] = []

    def __call__(self, name):
        self.calls.append(name)
        return self.found


class SandboxTest(unittest.TestCase):
    def test_the_module_fixture_points_home_accounts_and_config_under_one_temporary_root(self):
        r = accounts_sandbox.root()
        self.assertIsNotNone(r)
        self.assertTrue(r.is_relative_to(Path(tempfile.gettempdir()).resolve()))
        self.assertEqual(os.environ["HOME"], str(r / "home"))
        self.assertTrue((r / "home").is_dir())
        self.assertEqual(os.environ["CLAUDE_ACCOUNTS_DIR"], str(r / "accounts"))
        self.assertEqual(os.environ["CLAUDE_CONFIG_DIR"], str(r / "config"))
        for real in accounts_sandbox.real_accounts_dirs():
            self.assertFalse(r.is_relative_to(real), real)
            for name in accounts_sandbox.VARIABLES:
                self.assertFalse(Path(os.environ[name]).is_relative_to(real), (name, real))

    def test_the_fixture_restores_what_it_found_and_removes_its_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            env = child_env(ROOT, HOME=str(t / "fake-home"),
                            CLAUDE_ACCOUNTS_DIR=str(t / "fake-accounts"))
            done = subprocess.run([sys.executable, "-c", CHILD_FIXTURE], cwd=ROOT, env=env,
                                  capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        got = json.loads(done.stdout)
        before, after, inside = got["before"], got["after"], got["inside"]
        self.assertIsNone(before["CLAUDE_CONFIG_DIR"])
        self.assertEqual(after, before)
        self.assertEqual(got["first"], got["second"])
        self.assertEqual(got["still"], got["first"])
        self.assertIs(got["exists"], False)
        self.assertIsNone(got["root_after"])
        for value in inside.values():
            self.assertTrue(value.startswith(got["first"]), value)

    def test_the_real_accounts_dirs_are_the_ones_the_process_started_with(self):
        env = child_env(ROOT, HOME="/nonexistent-1027/h",
                        CLAUDE_ACCOUNTS_DIR="/nonexistent-1027/acc")
        done = subprocess.run([sys.executable, "-c", CHILD_REAL_DIRS], cwd=ROOT, env=env,
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(done.stdout), [
            "/nonexistent-1027/acc",
            "/nonexistent-1027/h/.claude-accounts",
            pwd.getpwuid(os.getuid()).pw_dir + "/.claude-accounts",
        ])

    def test_the_real_environment_carries_the_original_values(self):
        env = accounts_sandbox.real_environment()
        for v in accounts_sandbox.VARIABLES:
            self.assertEqual(env.get(v), accounts_sandbox.ORIGINAL[v], v)
        self.assertEqual(env["PATH"], os.environ["PATH"])


class SnapshotTest(unittest.TestCase):
    def test_an_absent_directory_is_one_absent_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(accounts_sandbox.accounts_snapshot(Path(tmp) / "nope"), {".": "absent"})

    def test_the_snapshot_sees_what_an_add_or_a_sync_changes(self):
        def add_profile(acc):
            (acc / "profiles" / "solo").mkdir()

        def chmod_profile(acc):
            (acc / "profiles" / "p1").chmod(0o755)

        def repoint(acc):
            link = acc / "profiles" / "p1" / "settings.json"
            link.unlink()
            link.symlink_to("/y/settings.json")

        def add_link(acc):
            (acc / "profiles" / "p1" / "skills").symlink_to("/x/.claude/skills")

        def add_root_file(acc):
            (acc / "x").write_text("")

        def drop_chosen(acc):
            (acc / "chosen-profile").unlink()

        changes = {"add profile": add_profile, "chmod": chmod_profile, "repoint": repoint,
                   "shared link": add_link, "root file": add_root_file, "remove": drop_chosen}
        for label, change in changes.items():
            with self.subTest(label), tempfile.TemporaryDirectory() as tmp:
                acc = tree(Path(tmp))
                base = accounts_sandbox.accounts_snapshot(acc)
                change(acc)
                self.assertNotEqual(accounts_sandbox.accounts_snapshot(acc), base)

    def test_the_snapshot_ignores_what_live_sessions_rewrite(self):
        def rewrite_choice(acc):
            (acc / "chosen-profile").write_text("p2\n")
            (acc / "bindings.tsv").write_text("new text\n")

        def rewrite_claude_json(acc):
            (acc / "profiles" / "p1" / ".claude.json").write_text('{"a": 1}')

        def own_file(acc):
            (acc / "profiles" / "p1" / "session-new").write_text("s")

        def switch_entry(acc):
            (acc / "switch" / "2").write_text("")

        def transients(acc):
            (acc / "bindings.tsv.tmp.99").write_text("")
            (acc / "bindings.tsv.lock").mkdir()

        changes = {"contents": rewrite_choice, ".claude.json": rewrite_claude_json,
                   "own file": own_file, "switch": switch_entry, "transients": transients}
        for label, change in changes.items():
            with self.subTest(label), tempfile.TemporaryDirectory() as tmp:
                acc = tree(Path(tmp))
                base = accounts_sandbox.accounts_snapshot(acc)
                change(acc)
                self.assertEqual(accounts_sandbox.accounts_snapshot(acc), base)


class SealTest(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.addCleanup(self._t.cleanup)
        self._r = tempfile.TemporaryDirectory()
        self.addCleanup(self._r.cleanup)
        t = Path(self._t.name)
        self.E = t / "E"
        self.E.mkdir()
        self.M = t / "missing"
        self.T = t / "T"
        self.T.mkdir()
        self.L = t / "L"
        self.L.symlink_to(self.T)
        self.R = Path(self._r.name)
        self.r = os.path.realpath(self.R)

    def test_sealing_makes_the_root_read_only_and_refuses_without_a_working_bwrap(self):
        protected, writable = [self.E, self.M, self.L], [self.R]
        r = self.r
        seal = ["--ro-bind", "/", "/", "--dev", "/dev", "--tmpfs", "/tmp", "--bind", r, r,
                "--setenv", "TMPDIR", "/tmp"]
        run = Recorder(0)
        self.assertIsNone(accounts_sandbox.sealed_argv(["x"], writable, protected, which=lambda n: None, run=run))
        self.assertEqual(run.calls, [])
        run = Recorder(0)
        got = accounts_sandbox.sealed_argv(["x"], writable, protected, which=lambda n: "/b/bwrap", run=run)
        self.assertEqual(got, ["/b/bwrap", *seal, "--", "x"])
        self.assertEqual(run.calls, [["/b/bwrap", *seal, "true"]])
        for argv in (got, run.calls[0]):
            for path in (self.E, self.M, self.L, self.T):
                self.assertNotIn(str(path), argv)
        self.assertIsNone(accounts_sandbox.sealed_argv(["x"], writable, protected, which=lambda n: "/b/bwrap",
                                      run=Recorder(1)))
        self.assertIsNone(accounts_sandbox.sealed_argv(["x"], writable, protected, which=lambda n: "/b/bwrap",
                                      run=Recorder(raises=OSError("no"))))
        self.assertIsNone(accounts_sandbox.sealed_argv(["x"], writable, protected, which=lambda n: "/b/bwrap",
                                      run=Recorder(raises=subprocess.TimeoutExpired("bwrap", 10))))

    def test_sealing_refuses_a_writable_path_that_reaches_a_protected_directory(self):
        cases = {
            "inside": ([self.E], [self.E / "rec"]),
            "parent": ([self.E], [self.E.parent]),
            "through a link": ([self.L], [self.T / "rec"]),
            "missing protected": ([self.M], [self.M / "rec"]),
        }
        for label, (protected, writable) in cases.items():
            with self.subTest(label):
                which, run = WhichRecorder("/b/bwrap"), Recorder(0)
                self.assertIsNone(accounts_sandbox.sealed_argv(["x"], writable, protected, which=which, run=run))
                self.assertEqual(which.calls, [])
                self.assertEqual(run.calls, [])
                self.assertTrue(accounts_sandbox.overlaps(writable, protected))
        self.assertFalse(accounts_sandbox.overlaps([self.R], [self.E, self.M, self.L]))

    def test_a_sealed_child_writes_only_its_writable_paths(self):
        probe_dir = Path(tempfile.mkdtemp(prefix=".seal-probe-", dir=ROOT))
        self.addCleanup(shutil.rmtree, probe_dir, True)
        argv = accounts_sandbox.sealed_argv([sys.executable, "-c", PROBE, str(probe_dir / "x"), str(self.R / "y")],
                           [self.R], [probe_dir])
        if argv is None:
            self.skipTest("no working bwrap here")
        subprocess.run(argv, timeout=60, check=False)
        self.assertFalse((probe_dir / "x").exists())
        self.assertTrue((self.R / "y").is_file())


class IsolationTest(unittest.TestCase):
    def test_the_detector_runs_unsealed_only_on_ci_with_no_real_accounts_directory(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as rec:
            t = Path(tmp)
            E, M = t / "E", t / "missing"
            E.mkdir()
            dangling = t / "dangling"
            dangling.symlink_to(t / "gone")
            writable, argv = [Path(rec)], ["x"]
            none = lambda n: None  # noqa: E731
            bwrap = lambda n: "/b/bwrap"  # noqa: E731
            ci = {"CI": "true"}
            with self.subTest("sealed wins"):
                got = accounts_sandbox.isolated_argv(argv, writable, [E], which=bwrap, run=Recorder(0), environ={})
                self.assertEqual(got[:2], ["/b/bwrap", "--ro-bind"])
            with self.subTest("existing dir, CI, no bwrap"):
                self.assertIsNone(accounts_sandbox.isolated_argv(argv, writable, [E], which=none, environ=ci))
            with self.subTest("dangling link counts as present"):
                self.assertIsNone(accounts_sandbox.isolated_argv(argv, writable, [dangling], which=none, environ=ci))
            with self.subTest("not CI"):
                self.assertIsNone(accounts_sandbox.isolated_argv(argv, writable, [M], which=none, environ={}))
            with self.subTest("CI is exactly true"):
                self.assertIsNone(accounts_sandbox.isolated_argv(argv, writable, [M], which=none,
                                                environ={"CI": "1"}))
            with self.subTest("CI with nothing present"):
                self.assertEqual(accounts_sandbox.isolated_argv(argv, writable, [M], which=none, environ=ci), ["x"])
            with self.subTest("failed probe on CI"):
                self.assertEqual(accounts_sandbox.isolated_argv(argv, writable, [M], which=bwrap, run=Recorder(1),
                                               environ=ci), ["x"])
                self.assertIsNone(accounts_sandbox.isolated_argv(argv, writable, [E], which=bwrap, run=Recorder(1),
                                                environ=ci))
            with self.subTest("overlap is refused"):
                self.assertIsNone(accounts_sandbox.isolated_argv(argv, [M / "rec"], [M], which=none, environ=ci))


class RealAccountsUntouchedTest(unittest.TestCase):
    def test_a_dropped_adder_environment_leaves_the_real_accounts_directory_untouched(self):
        dirs = accounts_sandbox.real_accounts_dirs()
        outer_before = {str(d): accounts_sandbox.accounts_snapshot(d) for d in dirs}
        with tempfile.TemporaryDirectory() as tmp:
            record = Path(tmp) / "record.json"
            env = accounts_sandbox.real_environment()
            env["PYTHONPATH"] = f"{ROOT / 'python'}{os.pathsep}{ROOT}"
            argv = accounts_sandbox.isolated_argv(
                [sys.executable, "-c", CHILD, str(record), json.dumps([str(d) for d in dirs]),
                 "tests.test_console_account_add", "tests.test_console_account_service"],
                [Path(tmp)], dirs)
            if argv is None:
                self.skipTest("the real accounts directories cannot be made unreachable here and "
                              "this is not a CI runner without them, so the fault-injected child "
                              "is not run")
            done = subprocess.run(argv, cwd=ROOT, env=env, stdin=DEVNULL, capture_output=True,
                                  text=True, timeout=600)
            self.assertEqual({str(d): accounts_sandbox.accounts_snapshot(d) for d in dirs}, outer_before,
                             "the real accounts directory changed")
            self.assertTrue(record.is_file(), done.stderr[-2000:])
            rec = json.loads(record.read_text())
        self.assertEqual(rec["start"], {v: accounts_sandbox.ORIGINAL[v]
                                        for v in accounts_sandbox.VARIABLES})
        self.assertEqual(rec["after"], rec["before"])
        self.assertTrue(rec["calls"])
        self.assertTrue(any(c["created"] for c in rec["calls"]))
        for c in rec["calls"]:
            self.assertIsNotNone(c["accounts"])
            accounts = Path(c["accounts"])
            self.assertEqual(accounts.name, "accounts")
            self.assertTrue(accounts.parent.name.startswith("accounts-sandbox-"), c)


class SandboxCoverageTest(unittest.TestCase):
    def test_every_launcher_test_module_installs_the_sandbox(self):
        missing = []
        for stem in covered_modules():
            module = importlib.import_module(f"tests.{stem}")
            if (getattr(module, "setUpModule", None) is not accounts_sandbox.setUpModule
                    or getattr(module, "tearDownModule", None)
                    is not accounts_sandbox.tearDownModule):
                missing.append(stem)
        self.assertEqual(missing, [])

    def test_the_covered_set_holds_every_module_the_owner_named(self):
        self.assertLessEqual(set(OWNER_NAMED), set(covered_modules()))
        for stem in OWNER_NAMED:
            self.assertTrue((ROOT / "tests" / f"{stem}.py").is_file(), stem)


if __name__ == "__main__":
    unittest.main()
