"""The console hook-cost verify check (#857, #838 item 6): a stopped console adds at most 10 ms per hook call.

Run: just agent-workflow-tests
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from agent_tools.console.hook_cost import console_hooks
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)

ROOT = Path(__file__).resolve().parents[1]
WRAPPER = "home/common/verify-pending/checks/console-hook-cost"
HTTP_EVENTS = ("Stop", "StopFailure", "PermissionRequest", "Notification", "SessionEnd")
SELECTED = [("Notification", "http"), ("PermissionRequest", "http"), ("SessionEnd", "http"),
            ("SessionStart", "command"), ("Stop", "http"), ("StopFailure", "http")]


def executable(path, body):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    path.chmod(0o755)
    return path


# Like the real relay: delivers stdin to the port and always exits 0.
POSTING = (f"{sys.executable} -c 'import sys, urllib.request as r; "
           "r.urlopen(r.Request(\"http://127.0.0.1:\" + sys.argv[1] + \"/api/hooks\", "
           "sys.stdin.buffer.read(), {\"Content-Type\": \"application/json\"}))' \"$1\" "
           "2>/dev/null; exit 0")


def http_hook(url):
    return {"type": "http", "url": url, "timeout": 2}


def deployed_settings(path, port, console_script, extra=None):
    url = f"http://127.0.0.1:{port}/api/hooks"
    hooks = {event: [{"hooks": [http_hook(url)]}] for event in HTTP_EVENTS}
    hooks["SessionStart"] = [{"hooks": [{"type": "command", "command": str(console_script)}]}]
    for event, entries in (extra or {}).items():
        hooks.setdefault(event, []).extend(entries)
    Path(path).write_text(json.dumps({"hooks": hooks}), encoding="utf-8")
    return Path(path)


class HookCostTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = self.tmp / "home"
        self.home.mkdir()

    def run_check(self, *args, home=None):
        env = {**os.environ, "PYTHONPATH": str(ROOT / "python"), "HOME": str(home or self.home)}
        return subprocess.run(
            [sys.executable, "-m", "agent_tools.console.hook_cost", *args],
            cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)

    def extra_hooks(self):
        marker = executable(self.tmp / "marker-hook", f"touch {self.tmp}/ran")
        return {"SessionStart": [{"hooks": [{"type": "command", "command": str(marker)}]}],
                "Stop": [{"hooks": [http_hook("http://192.0.2.1:27184/api/hooks")]}]}

    def deployed(self, script_body):
        listener = socket.socket()
        self.addCleanup(listener.close)
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        script = executable(self.tmp / "bin" / "0000-console-session-start", script_body)
        settings = deployed_settings(self.tmp / "settings.json", listener.getsockname()[1],
                                     script, self.extra_hooks())
        return listener, settings

    def test_no_deployed_hooks_is_not_yet(self):
        done = self.run_check()
        self.assertEqual(done.returncode, 75)
        self.assertEqual(json.loads(done.stdout), {"status": "not_deployed"})
        empty = self.tmp / "empty.json"
        empty.write_text(json.dumps({"hooks": {"PreToolUse": []}}), encoding="utf-8")
        self.assertEqual(self.run_check("--settings", str(empty)).returncode, 75)
        marker = executable(self.tmp / "marker-hook", f"touch {self.tmp}/ran")
        other = self.tmp / "other.json"
        other.write_text(json.dumps({"hooks": {
            "Stop": [{"hooks": [http_hook("http://192.0.2.1:27184/api/hooks")]}],
            "SessionStart": [{"hooks": [{"type": "command", "command": str(marker)}]}]}}),
            encoding="utf-8")
        self.assertEqual(self.run_check("--settings", str(other)).returncode, 75)
        self.assertFalse((self.tmp / "ran").exists())

    def test_console_hooks_selects_only_the_console(self):
        script = self.tmp / "bin" / "0000-console-session-start"
        settings = json.loads(deployed_settings(self.tmp / "s.json", 27184, script,
                                                self.extra_hooks()).read_text())
        settings["hooks"]["Stop"].append(
            {"hooks": [http_hook("http://127.0.0.1:27184/other")]})
        settings["hooks"]["SessionStart"].append(
            {"hooks": [{"type": "command", "command": "sh -c 'x-console-session-start'"}]})
        settings["hooks"]["Notification"].append({"hooks": "x"})
        self.assertEqual([(h["event"], h["kind"]) for h in console_hooks(settings)], SELECTED)

    def test_a_deployed_settings_is_measured_in_both_modes(self):
        listener, settings = self.deployed(POSTING)
        done = self.run_check("--settings", str(settings), "--calls", "3", "--budget-ms", "1000")
        self.assertEqual(done.returncode, 0, done.stderr)
        report = json.loads(done.stdout)
        self.assertEqual(report["status"], "met")
        self.assertEqual(report["calls"], 3)
        self.assertEqual(report["budget_ms"], 1000.0)
        self.assertEqual([(h["event"], h["kind"]) for h in report["hooks"]], SELECTED)
        for hook in report["hooks"]:
            for mode in ("stopped", "running"):
                median, worst = hook[mode]["median"], hook[mode]["max"]
                self.assertIsInstance(median, float)
                self.assertIsInstance(worst, float)
                self.assertTrue(0 <= median <= worst)
        self.assertFalse((self.tmp / "ran").exists())
        listener.setblocking(False)
        with self.assertRaises(BlockingIOError):
            listener.accept()

    def test_a_slow_session_start_script_is_not_met_even_when_http_is_fast(self):
        _, settings = self.deployed(f"sleep 0.2; {POSTING}")
        done = self.run_check("--settings", str(settings), "--calls", "3", "--budget-ms", "100")
        self.assertEqual(done.returncode, 1, done.stderr)
        report = json.loads(done.stdout)
        self.assertEqual(report["status"], "not_met")
        for hook in report["hooks"]:
            if hook["kind"] == "command":
                self.assertGreaterEqual(hook["stopped"]["median"], 100)
            else:
                self.assertLess(hook["stopped"]["median"], 100)

    def test_a_miss_is_not_met(self):
        _, settings = self.deployed(POSTING)
        done = self.run_check("--settings", str(settings), "--calls", "3", "--budget-ms", "0")
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertEqual(json.loads(done.stdout)["status"], "not_met")

    def assert_failed(self, settings, command_failures):
        done = self.run_check("--settings", str(settings), "--calls", "2", "--budget-ms", "1000")
        self.assertEqual(done.returncode, 1, done.stderr)
        report = json.loads(done.stdout)
        self.assertEqual(report["status"], "failed")
        for hook in report["hooks"]:
            if hook["kind"] == "command":
                self.assertEqual(hook["failures"], command_failures)
            else:
                self.assertEqual(hook["failures"], {"running": 0, "stopped": 0})

    def test_a_relay_that_cannot_run_is_failed_not_met(self):
        _, settings = self.deployed(POSTING)
        (self.tmp / "bin" / "0000-console-session-start").unlink()
        self.assert_failed(settings, {"running": 2, "stopped": 2})
        executable(self.tmp / "bin" / "0000-console-session-start", POSTING).chmod(0o644)
        self.assert_failed(settings, {"running": 2, "stopped": 2})

    def test_a_relay_that_exits_non_zero_is_failed(self):
        _, settings = self.deployed("cat >/dev/null; exit 3")
        self.assert_failed(settings, {"running": 2, "stopped": 2})

    def test_a_relay_that_delivers_nothing_is_failed_in_running_mode(self):
        _, settings = self.deployed("cat >/dev/null; exit 0")
        self.assert_failed(settings, {"running": 2, "stopped": 0})

    def test_the_check_wrapper_runs_the_module(self):
        path = ROOT / WRAPPER
        self.assertTrue(path.exists())
        self.assertTrue(os.access(path, os.X_OK))
        self.assertIn("-m agent_tools.console.hook_cost", path.read_text(encoding="utf-8"))
        mode = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-s", WRAPPER],
                              capture_output=True, text=True, check=True).stdout
        self.assertTrue(mode.startswith("100755"), mode)
        done = subprocess.run([str(path)], cwd=ROOT, capture_output=True, text=True, timeout=60,
                              env={**os.environ, "HOME": str(self.home)})
        self.assertEqual(done.returncode, 75, done.stderr)


if __name__ == "__main__":
    unittest.main()
