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
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

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


def covered_modules() -> list[str]:
    stems = {path.stem for path in (ROOT / "tests").glob("test_console_*.py")}
    return sorted(stems | set(EXTRA_MODULES))


def child_env(root: Path, **overrides: str) -> dict[str, str]:
    env = dict(os.environ)
    env.pop("CLAUDE_CONFIG_DIR", None)
    env.update(overrides)
    env["PYTHONPATH"] = f"{root / 'python'}{os.pathsep}{root}"
    return env


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
