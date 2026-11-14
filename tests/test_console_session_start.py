"""The console's SessionStart relay script (#857): a stopped or hung console costs a session nothing.

Run: just agent-workflow-tests
"""
import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from agent_tools.console import service

from . import console_test_support as support
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "home/common/claude-code/console-session-start.sh"
NIX_FILE = ROOT / "home/common/claude-code/default.nix"


def free_port():
    with socket.socket() as probe:
        probe.bind((service.HOST, 0))
        return probe.getsockname()[1]


def script(test):
    curl = shutil.which("curl")
    if curl is None:
        raise AssertionError("curl is not on PATH")
    directory = tempfile.mkdtemp()
    test.addCleanup(shutil.rmtree, directory, True)
    path = Path(directory) / "console-session-start"
    path.write_text(TEMPLATE.read_text(encoding="utf-8").replace("@curl@", curl), encoding="utf-8")
    path.chmod(0o755)
    return path


def run(path, port, stdin, home, env_extra=None):
    env = {"PATH": os.environ.get("PATH", ""), "HOME": str(home), **(env_extra or {})}
    return subprocess.run([str(path), str(port)], input=stdin, env=env, timeout=30,
                          capture_output=True)


class SessionStartHookTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)
        self.home = self.root / "home"
        self.home.mkdir()

    def test_a_stopped_console_costs_the_session_nothing(self):
        path = script(self)
        started = time.monotonic()
        done = run(path, free_port(), support.hook_body("session start"), self.home)
        elapsed = time.monotonic() - started
        self.assertEqual(done.returncode, 0)
        self.assertEqual(done.stdout, b"")
        self.assertEqual(done.stderr, b"")
        self.assertLess(elapsed, 1.0)

    def test_a_hung_console_is_abandoned_after_a_second(self):
        path = script(self)
        with socket.socket() as hung:
            hung.bind((service.HOST, 0))
            hung.listen()
            started = time.monotonic()
            done = run(path, hung.getsockname()[1], support.hook_body("session start"), self.home)
            elapsed = time.monotonic() - started
        self.assertEqual(done.returncode, 0)
        self.assertEqual(done.stdout, b"")
        self.assertLess(elapsed, 3.0)

    def test_a_running_console_records_the_session_start(self):
        path = script(self)
        store, registry = self.root / "events.db", self.root / "registry.json"
        support.write_registry(registry, support.entries(1))
        svc = support.service(self, store, registry, session_dirs=[])
        dead = f"http://{service.HOST}:{free_port()}"
        (self.home / ".curlrc").write_text(f'proxy = "{dead}"\n', encoding="utf-8")
        proxies = {"http_proxy": dead, "HTTP_PROXY": dead, "ALL_PROXY": dead}
        done = run(path, svc.address[1],
                   support.hook_body("session start", cwd="/srv/p00"), self.home, proxies)
        self.assertEqual(done.returncode, 0)
        self.assertEqual(done.stdout, b"")
        deadline = time.monotonic() + 2.0
        rows = []
        while time.monotonic() < deadline:
            rows = [row for row in support.log_rows(store) if row[2] == "session.hook"]
            if rows:
                break
            time.sleep(0.02)
        self.assertEqual(len(rows), 1)
        self.assertEqual(json.loads(rows[0][4])["event"], "SessionStart")
        self.assertEqual(rows[0][3], "owner/p00")

    def test_the_settings_and_the_script_name_the_console(self):
        nix = NIX_FILE.read_text(encoding="utf-8")
        host, port, hook = service.HOST, service.DEFAULT_PORT, service.HOOK_PATH
        self.assertIn(f'"http://{host}:{port}{hook}"', nix)
        self.assertIn(f'"http://{host}:{port}/*"', nix)
        self.assertIn("./console-session-start.sh", nix)
        template = TEMPLATE.read_text(encoding="utf-8")
        self.assertEqual(template.splitlines()[0], "#!/bin/sh")
        self.assertIn("@curl@ -q ", template)
        self.assertIn(f'"http://{host}:${{1:-{port}}}{hook}"', template)
        self.assertEqual(template.count("@curl@"), 1)


if __name__ == "__main__":
    unittest.main()
