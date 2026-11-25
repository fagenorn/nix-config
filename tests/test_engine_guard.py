"""Contract tests for the engine's lifecycle-guard seam (`engine_guard`, issue 1515).

`locate` finds the guard hook in the generated settings by its wrapper name and
`judge` runs it on one command with the Bash hook payload. A stand-in guard
(tests/fixtures/engine-deliver/standin_guard.py) stands for the real guard
program, which is never imported.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from agent_tools.delivery.engine_guard import (
    Hook, Unavailable, Verdict, judge, locate, settings_path)
from tests.engine_guards import REPO_ROOT, payloads, standin_guard, write_settings

TIER = "fast"

GUARD = "/nix/store/x/bin/claude-bash-lifecycle-guard"
MERGE = "gh pr merge 7 --repo example/engine --merge"


def gone(test: unittest.TestCase, pid: int, what: str) -> None:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.05)
    test.fail(f"{what} {pid} outlived the guard")


def kill_quietly(pid: int) -> None:
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


class JudgeTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.d = Path(self._tmp.name)

    def hook(self, mode: str, *words: str, timeout: float = 5) -> Hook:
        return Hook(str(standin_guard(self.d, "g", mode, *words)), timeout)

    def pids(self) -> list[int]:
        return [int(line) for line in (self.d / "pids").read_text().split()]

    def test_the_guard_gets_the_bash_payload_in_the_directory_and_its_exit_2_refuses_with_its_text(self):
        hook = self.hook("refuse", str(self.d / "log"),
                         "lifecycle guard: unsafe merge: missing --delete-branch")
        verdict = judge(hook, MERGE, str(self.d))
        self.assertEqual(verdict, Verdict(
            False, "lifecycle guard: unsafe merge: missing --delete-branch"))
        self.assertEqual(payloads(self.d / "log"), [{
            "cwd": os.path.realpath(self.d),
            "payload": {"cwd": str(self.d), "hook_event_name": "PreToolUse",
                        "tool_input": {"command": MERGE}, "tool_name": "Bash"}}])

    def test_exit_0_allows_with_no_reason(self):
        verdict = judge(self.hook("allow", str(self.d / "log")), "true", str(self.d))
        self.assertEqual(verdict, Verdict(True, None))
        self.assertEqual(len(payloads(self.d / "log")), 1)

    def test_a_refusal_keeps_the_guard_text_exactly_but_its_line_ending(self):
        text = "lifecycle guard: branch 'a  b' (two spaces)\tand a tab"
        verdict = judge(self.hook("refuse", str(self.d / "log"), text), "x", str(self.d))
        self.assertEqual(verdict, Verdict(False, text))
        padded = "  lifecycle guard: padded \t "
        verdict = judge(self.hook("refuse", str(self.d / "log"), padded), "x", str(self.d))
        self.assertEqual(verdict, Verdict(False, padded))

    def test_any_other_exit_refuses_naming_the_exit_and_the_text(self):
        for code in ("1", "3"):
            with self.subTest(code=code):
                verdict = judge(self.hook("exit", str(self.d / "log"), code, "boom"),
                                "x", str(self.d))
                self.assertFalse(verdict.allowed)
                self.assertIn(code, verdict.reason)
                self.assertIn("boom", verdict.reason)
        verdict = judge(self.hook("refuse", str(self.d / "log"), ""), "x", str(self.d))
        self.assertFalse(verdict.allowed)
        self.assertTrue(verdict.reason.strip())

    def test_a_guard_past_its_timeout_is_refused_and_its_process_is_gone(self):
        hook = self.hook("sleep", str(self.d / "pids"), timeout=0.5)
        started = time.monotonic()
        verdict = judge(hook, "true", str(self.d))
        self.assertLess(time.monotonic() - started, 10)
        self.assertFalse(verdict.allowed)
        self.assertIn("did not answer within", verdict.reason)
        for pid in self.pids():
            gone(self, pid, "process")

    def test_a_timed_out_guard_whose_group_cannot_be_signalled_is_still_refused_and_reaped(self):
        hook = self.hook("sleep", str(self.d / "pids"), timeout=0.5)

        def kill_grandchild():
            try:
                kill_quietly(self.pids()[1])
            except (FileNotFoundError, IndexError, ValueError):
                pass

        self.addCleanup(kill_grandchild)
        with mock.patch("agent_tools.delivery.engine_guard.os.killpg",
                        side_effect=PermissionError(1, "Operation not permitted")):
            verdict = judge(hook, "true", str(self.d))
        self.assertFalse(verdict.allowed)
        self.assertIn("did not answer within", verdict.reason)
        gone(self, self.pids()[0], "guard")

    def test_a_timed_out_guard_takes_a_descendant_in_another_session_with_it(self):
        hook = self.hook("sleep-away", str(self.d / "pids"), timeout=0.5)

        def kill_both():
            try:
                for pid in self.pids():
                    kill_quietly(pid)
            except (FileNotFoundError, ValueError):
                pass

        self.addCleanup(kill_both)
        verdict = judge(hook, "true", str(self.d))
        self.assertFalse(verdict.allowed)
        self.assertIn("did not answer within", verdict.reason)
        self.assertEqual(len(self.pids()), 2)
        for pid in self.pids():
            gone(self, pid, "process")

    def test_a_sigterm_while_waiting_kills_the_guard_and_its_group(self):
        hook = self.hook("sleep-away", str(self.d / "pids"), timeout=60)
        code = ("from agent_tools.delivery.engine_guard import Hook, judge\n"
                f"judge(Hook({hook.command!r}, 60), 'true', {str(self.d)!r})\n")
        engine = subprocess.Popen([sys.executable, "-c", code], cwd=REPO_ROOT,
                                  env={**os.environ, "PYTHONPATH": "python"},
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        def kill_all():
            kill_quietly(engine.pid)
            try:
                for pid in self.pids():
                    kill_quietly(pid)
            except (FileNotFoundError, ValueError):
                pass
            engine.wait()

        self.addCleanup(kill_all)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if (self.d / "pids").exists() and len(self.pids()) == 2:
                break
            time.sleep(0.05)
        self.assertEqual(len(self.pids()), 2)
        engine.send_signal(signal.SIGTERM)
        self.assertEqual(engine.wait(timeout=20), 128 + signal.SIGTERM)
        for pid in self.pids():
            gone(self, pid, "process")

    def test_an_interrupted_guard_is_killed_with_its_group_before_the_interrupt_propagates(self):
        hook = self.hook("sleep", str(self.d / "pids"), timeout=60)
        main = threading.get_ident()

        def interrupt_when_started():
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                try:
                    if len(self.pids()) == 2:
                        break
                except (FileNotFoundError, ValueError):
                    pass
                time.sleep(0.05)
            signal.pthread_kill(main, signal.SIGINT)

        threading.Thread(target=interrupt_when_started, daemon=True).start()

        def kill_both():
            try:
                for pid in self.pids():
                    kill_quietly(pid)
            except (FileNotFoundError, ValueError):
                pass

        self.addCleanup(kill_both)
        with self.assertRaises(KeyboardInterrupt):
            judge(hook, "true", str(self.d))
        for pid in self.pids():
            gone(self, pid, "process")

    def test_a_guard_that_cannot_be_run_is_refused_with_its_path(self):
        missing = str(self.d / "no-such-guard")
        verdict = judge(Hook(missing, 5), "true", str(self.d))
        self.assertFalse(verdict.allowed)
        self.assertIn(missing, verdict.reason)
        hook = self.hook("allow", str(self.d / "log"))
        self.assertFalse(judge(hook, "true", str(self.d / "no-such-directory")).allowed)
        self.assertFalse(judge(Hook("/bin/g\x00x", 5), "true", str(self.d)).allowed)

    def test_an_unavailable_guard_is_refused_with_its_reason(self):
        self.assertEqual(judge(Unavailable("The settings name no guard."), "x", str(self.d)),
                         Verdict(False, "The settings name no guard."))

    def test_the_guard_output_never_reaches_the_caller(self):
        hook = self.hook("noisy", str(self.d / "log"))
        code = ("from agent_tools.delivery.engine_guard import Hook, judge\n"
                f"judge(Hook({hook.command!r}, 5), 'true', {str(self.d)!r})\n")
        done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                              cwd=REPO_ROOT, env={**os.environ, "PYTHONPATH": "python"},
                              check=False)
        self.assertEqual((done.stdout, done.stderr, done.returncode), ("", "", 0))


class LocateTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.d = Path(self._tmp.name)
        self.path = self.d / "settings.json"

    def entry(self, matcher: str = "Bash", *hooks: dict) -> dict:
        return {"matcher": matcher, "hooks": list(hooks) or [self.hook()]}

    @staticmethod
    def hook(**changes) -> dict:
        return {"type": "command", "command": GUARD, "timeout": 30, **changes}

    @staticmethod
    def settings(*entries: dict) -> str:
        return json.dumps({"hooks": {"PreToolUse": list(entries)}})

    def locate(self, text: str):
        self.path.write_text(text, encoding="utf-8")
        return locate(self.path)

    def test_the_generated_settings_shape_is_located(self):
        text = self.settings(self.entry(), self.entry("Edit|Write|MultiEdit|NotebookEdit"),
                             self.entry("^mcp__"))
        self.assertEqual(self.locate(text), Hook(GUARD, 30))
        with self.subTest("empty args"):
            self.assertEqual(self.locate(self.settings(self.entry("Bash", self.hook(args=[])))),
                             Hook(GUARD, 30))
        with self.subTest("a longer timeout"):
            self.assertEqual(
                self.locate(self.settings(self.entry("Bash", self.hook(timeout=3600)))),
                Hook(GUARD, 3600))

    def test_a_hook_switch_that_is_on_is_unavailable(self):
        doc = json.loads(self.settings(self.entry()))
        for name, value in (("disableAllHooks", True), ("allowManagedHooksOnly", True),
                            ("disableAllHooks", "yes"), ("disableAllHooks", 0)):
            with self.subTest(name=name, value=value):
                found = self.locate(json.dumps({**doc, name: value}))
                self.assertIsInstance(found, Unavailable)
                self.assertIn(name, found.reason)
        for name in ("disableAllHooks", "allowManagedHooksOnly"):
            with self.subTest(name=name, value=False):
                self.assertEqual(self.locate(json.dumps({**doc, name: False})), Hook(GUARD, 30))

    def test_a_guard_hook_with_an_if_filter_is_unavailable(self):
        documents = {
            "on the hook": self.settings(
                self.entry("Bash", self.hook(**{"if": "Bash(git push *)"}))),
            "empty on the hook": self.settings(self.entry("Bash", self.hook(**{"if": ""}))),
            "on the entry": self.settings({**self.entry(), "if": "Bash(*)"}),
        }
        for name, text in documents.items():
            with self.subTest(name):
                found = self.locate(text)
                self.assertIsInstance(found, Unavailable)
                self.assertIn("if filter", found.reason)
        self.assertEqual(self.locate(self.settings(self.entry())), Hook(GUARD, 30))

    def test_an_asynchronous_guard_hook_is_unavailable(self):
        for name, value in (("async", True), ("async", "true"), ("async", 1),
                            ("asyncRewake", True), ("asyncRewake", "yes")):
            with self.subTest(name=name, value=value):
                found = self.locate(self.settings(self.entry("Bash", self.hook(**{name: value}))))
                self.assertIsInstance(found, Unavailable)
                self.assertIn("asynchronous", found.reason)
        for name in ("async", "asyncRewake"):
            with self.subTest(name=name, value=False):
                self.assertEqual(
                    self.locate(self.settings(self.entry("Bash", self.hook(**{name: False})))),
                    Hook(GUARD, 30))

    def test_every_other_shape_is_unavailable_with_a_reason(self):
        def with_hook(**changes) -> str:
            return self.settings(self.entry("Bash", self.hook(**changes)))

        timeout_free = {k: v for k, v in self.hook().items() if k != "timeout"}
        documents = {
            "not JSON": "{not json",
            "an array": "[]",
            "a duplicate key": '{"hooks": {}, "hooks": {}}',
            "a NaN literal": '{"hooks": NaN}',
            "deep nesting": "[" * 200000,
            "no hooks": "{}",
            "no Bash entry": self.settings(self.entry("Edit")),
            "two Bash entries": self.settings(self.entry(), self.entry()),
            "two command hooks": self.settings(self.entry("Bash", self.hook(), self.hook())),
            "no command hook": self.settings(self.entry("Bash", {"type": "prompt"})),
            "a sole Bash hook that is not the guard": with_hook(command="/usr/bin/true"),
            "a name that only starts like the guard": with_hook(command=GUARD + "-old"),
            "a relative command": with_hook(command="x/bin/claude-bash-lifecycle-guard"),
            "a command with a space": with_hook(command="/a b/bin/claude-bash-lifecycle-guard"),
            "a command with a NUL": with_hook(command="/a\u0000b/bin/claude-bash-lifecycle-guard"),
            "args": with_hook(args=["--x"]),
            "string args": with_hook(args="x"),
            "no timeout": self.settings(self.entry("Bash", timeout_free)),
            "zero timeout": with_hook(timeout=0),
            "negative timeout": with_hook(timeout=-1),
            "boolean timeout": with_hook(timeout=True),
            "string timeout": with_hook(timeout="30"),
            "too long a timeout": with_hook(timeout=3601),
            "an infinite timeout": with_hook(timeout=0).replace(
                '"timeout": 0', '"timeout": 1e400'),
            "a huge integer timeout": with_hook(timeout=0).replace(
                '"timeout": 0', '"timeout": 1' + "0" * 400),
        }
        for name, text in documents.items():
            with self.subTest(name):
                found = self.locate(text)
                self.assertIsInstance(found, Unavailable)
                self.assertTrue(found.reason.strip())
        with self.subTest("a missing file"):
            found = locate(self.d / "absent.json")
            self.assertIsInstance(found, Unavailable)
            self.assertTrue(found.reason.strip())

    def test_settings_path_is_under_home(self):
        self.assertEqual(settings_path({"HOME": "/h"}), Path("/h/.claude/settings.json"))

    def test_a_home_that_is_not_an_absolute_path_names_no_settings_and_reads_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_settings(Path(tmp), GUARD, 12)
            previous = os.getcwd()
            os.chdir(tmp)
            self.addCleanup(os.chdir, previous)
            for name, environ in {"empty": {"HOME": ""}, "relative": {"HOME": "."},
                                  "named": {"HOME": "sub/dir"}, "unset": {}}.items():
                with self.subTest(name):
                    path = settings_path(environ)
                    self.assertIsInstance(path, Unavailable)
                    self.assertIn("HOME", path.reason)
                    self.assertEqual(locate(path), path)


class SettingsHelperTest(unittest.TestCase):
    def test_the_written_settings_are_located(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_settings(Path(tmp), GUARD, 12)
            self.assertEqual(locate(path), Hook(GUARD, 12))


if __name__ == "__main__":
    unittest.main()
