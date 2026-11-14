"""The console's account adder (#1027): the name rule, the request, the row, the launcher run.

Run: just agent-workflow-tests
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from agent_tools.console import account_add, event_log
from agent_tools.console.event_log import Event
from agent_tools.console.account_add import AddFailed, Adder, adder_for, added, added_state
from agent_tools.console.account_add import already_exists
from agent_tools.console.account_add import parse_add_request, refusal
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)

LAUNCHER = (Path(__file__).resolve().parents[1]
            / "home/common/claude-code/accounts/bin/claude-account")
BASH = shutil.which("bash")


def launcher_env(root: Path) -> dict[str, str]:
    claude = root / "home" / ".claude"
    claude.mkdir(parents=True)
    (root / "store").mkdir()
    (root / "store" / "settings.json").write_text("{}")
    (claude / "settings.json").symlink_to(root / "store" / "settings.json")
    (claude / "CLAUDE.md").write_text("guidance")
    (claude / "skills").mkdir()
    return {"HOME": str(root / "home"), "CLAUDE_ACCOUNTS_DIR": str(root / "accounts"),
            "PATH": os.environ["PATH"]}


class NameRuleTest(unittest.TestCase):
    def test_the_console_rule_is_the_launchers(self):
        names = ["work", "a-b_c9", "-h", "0", "", "default", "Work", "a.b", "../x", "a b",
                 "x/y", "é", "a\n"]
        with tempfile.TemporaryDirectory() as tmp:
            env = launcher_env(Path(tmp))
            for name in names:
                with self.subTest(name=name):
                    proc = subprocess.run([BASH, str(LAUNCHER), "add", name], env=env,
                                          stdin=subprocess.DEVNULL, capture_output=True,
                                          timeout=30)
                    self.assertEqual(proc.returncode == 0, refusal(name) is None)

    def test_refusal_reasons(self):
        text = "not an account name: use a-z, 0-9, - and _"
        self.assertEqual(refusal("Work"), text)
        self.assertEqual(refusal(""), text)
        self.assertEqual(refusal("../x"), text)
        self.assertEqual(refusal("default"), "default is not an account name")
        self.assertIsNone(refusal("work"))
        self.assertEqual(already_exists("work"), "account work already exists")


class RequestTest(unittest.TestCase):
    def test_parse_add_request(self):
        self.assertEqual(parse_add_request(b'{"name":"work"}'), "work")
        self.assertEqual(parse_add_request(b'{"name":""}'), "")
        for body in (b'{}', b'{"name":1}', b'{"name":"a","x":1}', b'[]', b'"work"', b'\xff',
                     b'not json'):
            with self.subTest(body=body):
                with self.assertRaises(ValueError):
                    parse_add_request(body)

    def test_the_added_row(self):
        self.assertEqual(added("work"), ("account.added", None, {"by": "owner",
                                                                  "profile": "work"}))
        for name in ("default", "Work"):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    added(name)
        self.assertEqual(account_add.ADDED, "account.added")
        self.assertEqual(event_log.ACCOUNT_ADDED, "account.added")
        self.assertNotIn("account.added", event_log.KEPT_KINDS)

    def test_added_state_folds_the_added_rows(self):
        rows = [("account.added", None, {"by": "owner", "profile": "b"}),
                ("account.added", None, {"by": "owner", "profile": "a"}),
                ("account.added", None, {"profile": "default"}),
                ("account.added", None, {"profile": 3}),
                ("signin.acted", None, {"by": "owner", "profile": "z", "action": "start",
                                        "outcome": "started"})]
        events = [Event(seq=n, at=f"t{n}", kind=kind, project=project, payload=payload)
                  for n, (kind, project, payload) in enumerate(rows, start=1)]
        self.assertEqual(added_state(events), frozenset({"a", "b"}))
        later = Event(seq=9, at="t9", kind="account.added", project=None,
                      payload={"by": "owner", "profile": "c"})
        self.assertEqual(added_state([later], frozenset({"a"})), frozenset({"a", "c"}))


class AdderTest(unittest.TestCase):
    def test_the_adder_runs_the_launchers_add(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = launcher_env(root)
            Adder(command=[BASH, str(LAUNCHER)], environ=env)("solo")
            profile = root / "accounts" / "profiles" / "solo"
            self.assertTrue(profile.is_dir())
            self.assertEqual(stat.S_IMODE(profile.stat().st_mode), 0o700)
            self.assertEqual(os.readlink(profile / "settings.json"),
                             str(root / "home/.claude/settings.json"))
            self.assertEqual(os.readlink(profile / "skills"),
                             str(root / "home/.claude/skills"))

    def test_an_invalid_name_starts_no_process(self):
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / "ran"
            command = [sys.executable, "-c", f"open({str(marker)!r}, 'w').close()"]
            for name in ("../x", "default", ""):
                with self.subTest(name=name):
                    with self.assertRaises(ValueError):
                        Adder(command=command)(name)
            self.assertFalse(marker.exists())

    def test_failures_have_kinds(self):
        with tempfile.TemporaryDirectory() as tmp:
            cases = [
                ("not_installed", Adder(command=[str(Path(tmp) / "missing")])),
                ("failed", Adder(command=[sys.executable, "-c", "import sys; sys.exit(3)"])),
                ("timed_out", Adder(command=[sys.executable, "-c", "import time; time.sleep(30)"],
                                    timeout=0.5)),
            ]
            for kind, adder in cases:
                with self.subTest(kind=kind):
                    started = time.monotonic()
                    with self.assertRaises(AddFailed) as caught:
                        adder("work")
                    self.assertEqual(caught.exception.kind, kind)
                    self.assertEqual(str(caught.exception), kind)
                    self.assertLess(time.monotonic() - started, 10)
        self.assertIsNone(Adder(command=[sys.executable, "-c", "pass"])("work"))

    def test_a_timeout_ends_the_launchers_descendants(self):
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / "wrote"
            script = f"(sleep 2; touch {marker}) & wait"
            adder = Adder(command=[BASH, "-c", script, "launcher"], timeout=0.5)
            with self.assertRaises(AddFailed) as caught:
                adder("work")
            self.assertEqual(caught.exception.kind, "timed_out")
            time.sleep(3)
            self.assertFalse(marker.exists())

    def test_adder_for(self):
        self.assertIsInstance(adder_for("linux"), Adder)
        self.assertIsNone(adder_for("darwin"))


if __name__ == "__main__":
    unittest.main()
