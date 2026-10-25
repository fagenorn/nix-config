"""The `claude` launcher routes through the cache proxy only when its health check answers (#422).

Each case runs the source `claude-account run` from a temporary copy of the accounts mod whose
`CACHE_PROXY_URL=` line is substituted the way `home/common/claude-code/default.nix` substitutes
it, with the system `env` standing in for claude, so what it prints is the environment claude
would receive.
"""

import http.server
import io
import os
import shutil
import socket
import socketserver
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

from agent_tools import cache_proxy

REPO_ROOT = Path(__file__).resolve().parents[1]
ACCOUNTS = REPO_ROOT / "home" / "common" / "claude-code" / "accounts"
PLACEHOLDER = "CACHE_PROXY_URL="
SCRUBBED = ("ANTHROPIC_BASE_URL", "ENABLE_TOOL_SEARCH", "CLAUDE_ACCOUNT", "CLAUDE_ACCOUNTS_DIR",
            "CLAUDE_ACCOUNT_LAUNCHER", "CLAUDE_BIN", "CLAUDE_CODE_PLUGIN_DIRS", "CLAUDE_CONFIG_DIR",
            "CLAUDE_CODE_ENABLE_FINE_GRAINED_TOOL_STREAMING")
CALLER_URL = "http://127.0.0.1:9/caller"
FGTS = "CLAUDE_CODE_ENABLE_FINE_GRAINED_TOOL_STREAMING"
MARKER_BODY = b'{"service":"cache-proxy","status":"ok"}'
TIMEOUT = 30


def closed_port():
    """A loopback port nothing listens on: bound, then freed."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class ForeignHandler(http.server.BaseHTTPRequestHandler):
    """Another service on the proxy's port: 200 to every GET, without the cache-proxy marker."""

    def do_GET(self):
        body = b'{"service":"other","status":"ok"}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass


class RedirectHandler(http.server.BaseHTTPRequestHandler):
    """Answers every GET with a 302 whose body carries the cache-proxy marker."""

    def do_GET(self):
        self.send_response(302)
        self.send_header("Location", "http://127.0.0.1:9/elsewhere")
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(MARKER_BODY)))
        self.end_headers()
        self.wfile.write(MARKER_BODY)

    def log_message(self, format, *args):
        pass


class RoutingTest(unittest.TestCase):
    def setUp(self):
        for tool in ("bash", "curl", "jq", "env"):
            self.assertIsNotNone(shutil.which(tool), f"{tool} is required on PATH")
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root)

    def serve(self, server):
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return "http://127.0.0.1:%d" % server.server_address[1]

    def healthy_proxy(self):
        """The real cache-proxy server; a health probe never reaches its upstream."""
        upstream = cache_proxy.parse_upstream("http://127.0.0.1:%d" % closed_port())
        return self.serve(cache_proxy.ProxyServer(0, upstream, cache_proxy.LineLog(io.StringIO())))

    def foreign_listener(self):
        return self.serve(socketserver.ThreadingTCPServer(("127.0.0.1", 0), ForeignHandler))

    def redirecting_listener(self):
        return self.serve(socketserver.ThreadingTCPServer(("127.0.0.1", 0), RedirectHandler))

    def launch(self, proxy_url, env=None, substitute=True):
        """`claude-account run` from a fresh copy; the environment the stand-in claude printed."""
        copy = Path(tempfile.mkdtemp(dir=self.root)) / "accounts"
        shutil.copytree(ACCOUNTS, copy)
        script = copy / "bin" / "claude-account"
        text = script.read_text()
        self.assertEqual(text.count(PLACEHOLDER), 1)
        if substitute:
            script.write_text(text.replace(PLACEHOLDER, PLACEHOLDER + proxy_url))
        home, work = self.root / "home", self.root / "work"
        home.mkdir(exist_ok=True)
        work.mkdir(exist_ok=True)
        child = {key: value for key, value in os.environ.items() if key not in SCRUBBED}
        child.update(HOME=str(home), CLAUDE_ACCOUNTS_DIR=str(self.root / "accounts-state"),
                     CLAUDE_BIN=shutil.which("env"), **(env or {}))
        completed = subprocess.run([shutil.which("bash"), str(script), "run"], cwd=work, env=child,
                                   capture_output=True, text=True, timeout=TIMEOUT, check=False)
        self.assertEqual((completed.returncode, completed.stderr), (0, ""))
        return dict(line.split("=", 1) for line in completed.stdout.splitlines() if "=" in line)

    def assert_routed(self, environment, url):
        self.assertEqual(environment.get("ANTHROPIC_BASE_URL"), url)
        self.assertEqual(environment.get("ENABLE_TOOL_SEARCH"), "true")

    def assert_direct(self, environment):
        self.assertNotIn("ANTHROPIC_BASE_URL", environment)
        self.assertNotIn("ENABLE_TOOL_SEARCH", environment)
        self.assertNotIn(FGTS, environment)

    def test_a_healthy_proxy_routes_the_launch(self):
        url = self.healthy_proxy()
        self.assert_routed(self.launch(url), url)

    def test_a_closed_port_launches_direct(self):
        self.assert_direct(self.launch("http://127.0.0.1:%d" % closed_port()))

    def test_a_foreign_listener_without_the_marker_launches_direct(self):
        self.assert_direct(self.launch(self.foreign_listener()))

    def test_a_redirect_carrying_the_marker_launches_direct(self):
        self.assert_direct(self.launch(self.redirecting_listener()))

    def test_a_caller_set_endpoint_is_left_alone(self):
        environment = self.launch(self.healthy_proxy(), {"ANTHROPIC_BASE_URL": CALLER_URL})
        self.assertEqual(environment.get("ANTHROPIC_BASE_URL"), CALLER_URL)
        self.assertNotIn("ENABLE_TOOL_SEARCH", environment)

    def test_an_inherited_proxy_url_is_unset_when_the_proxy_is_down(self):
        url = "http://127.0.0.1:%d" % closed_port()
        self.assert_direct(self.launch(url, {"ANTHROPIC_BASE_URL": url}))

    def test_a_caller_chosen_config_dir_takes_the_early_exec_and_is_routed(self):
        url = self.healthy_proxy()
        config = str(self.root / "custom-config")
        environment = self.launch(url, {"CLAUDE_CONFIG_DIR": config})
        self.assertEqual(environment.get("CLAUDE_CONFIG_DIR"), config)
        # Only the account loop exports the launcher pid, so its absence proves the early exec.
        self.assertNotIn("CLAUDE_ACCOUNT_LAUNCHER", environment)
        self.assert_routed(environment, url)

    def test_a_caller_set_tool_search_value_is_kept(self):
        url = self.healthy_proxy()
        environment = self.launch(url, {"ENABLE_TOOL_SEARCH": "false"})
        self.assertEqual((environment.get("ANTHROPIC_BASE_URL"), environment.get("ENABLE_TOOL_SEARCH")),
                         (url, "false"))

    def test_a_routed_launch_turns_fine_grained_tool_streaming_on(self):
        url = self.healthy_proxy()
        environment = self.launch(url)
        self.assert_routed(environment, url)
        self.assertEqual(environment.get(FGTS), "1")

    def test_a_caller_set_fine_grained_streaming_value_is_kept(self):
        url = self.healthy_proxy()
        environment = self.launch(url, {FGTS: "0"})
        self.assertEqual((environment.get("ANTHROPIC_BASE_URL"), environment.get(FGTS)), (url, "0"))

    def test_a_caller_set_endpoint_gets_no_fine_grained_streaming(self):
        environment = self.launch(self.healthy_proxy(), {"ANTHROPIC_BASE_URL": CALLER_URL})
        self.assertNotIn(FGTS, environment)

    def test_an_unsubstituted_copy_never_routes(self):
        url = self.healthy_proxy()
        self.assert_direct(self.launch(url, substitute=False))
        environment = self.launch(url, {"ANTHROPIC_BASE_URL": url}, substitute=False)
        self.assertEqual(environment.get("ANTHROPIC_BASE_URL"), url)
        self.assertNotIn("ENABLE_TOOL_SEARCH", environment)


if __name__ == "__main__":
    unittest.main()
