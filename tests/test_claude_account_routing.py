"""The `claude` launcher routes through the cache proxy while its health check answers, unless CLAUDE_CACHE_PROXY=0 (#422, #438, #450).

Each case runs the source `claude-account run` from a temporary copy of the accounts mod whose
`CACHE_PROXY_URL=` line is substituted the way `home/common/claude-code/default.nix` substitutes
it, with the system `env` standing in for claude, so what it prints is the environment claude
would receive.

#1012: a launch with `CLAUDE_ACCOUNT` unset picks the profile the console answers on
`GET /api/profile`, else the choice file, else the most recently used signed-in profile, else the
first by name.
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
import time
import unittest
from pathlib import Path

from agent_tools.hosts import cache_proxy

REPO_ROOT = Path(__file__).resolve().parents[1]
ACCOUNTS = REPO_ROOT / "home" / "common" / "claude-code" / "accounts"
PLACEHOLDER = "CACHE_PROXY_URL="
CONSOLE_LINE = "\nCONSOLE_URL=http://127.0.0.1:27184\n"
CALLER_URL = "http://127.0.0.1:9/caller"
REQUIRED_REFUSAL = "claude-account: CLAUDE_CACHE_PROXY=required and the cache proxy is not answering\n"
REMINDER = "CLAUDE_CODE_TOTAL_TOKENS_REMINDER"
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


class ConsoleHandler(http.server.BaseHTTPRequestHandler):
    """A stand-in console: records each GET path on its server and answers 200 with `server.body`."""

    def do_GET(self):
        self.server.requests.append(self.path)
        body = getattr(self.server, "excluded", b'{"excluded":[]}') if self.path == "/api/excluded" else self.server.body
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


class RecordingProxyHandler(cache_proxy.ProxyHandler):
    """The real handler, recording each request's path on its server before answering it."""

    def parse_request(self):
        parsed = super().parse_request()
        if parsed:
            self.server.requests.append(self.path)
        return parsed


class RecordingProxyServer(cache_proxy.ProxyServer):
    """The real cache-proxy server, whose `requests` lists every request path it received."""

    def __init__(self, *args):
        super().__init__(*args)
        self.requests = []
        self.RequestHandlerClass = RecordingProxyHandler


class LauncherCase(unittest.TestCase):
    switch = {}  # the CLAUDE_CACHE_PROXY setting every launch of the class starts from

    def setUp(self):
        for tool in ("bash", "env"):
            self.assertIsNotNone(shutil.which(tool), f"{tool} is required on PATH")
        version = subprocess.run([shutil.which("bash"), "-c", 'echo "${BASH_VERSINFO[0]} ${BASH_VERSINFO[1]}"'],
                                 capture_output=True, text=True, check=True).stdout.split()
        self.assertGreaterEqual(tuple(map(int, version)), (4, 4),
                                "the health probe needs bash 4.4 or later ($! must name a process substitution)")
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root)

    def serve(self, server):
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return "http://127.0.0.1:%d" % server.server_address[1]

    def healthy_proxy(self):
        """The real cache-proxy server; a health probe never reaches its upstream.

        `self.proxy_requests` lists the paths it has received, so a test can tell a probe from none."""
        upstream = cache_proxy.parse_upstream("http://127.0.0.1:%d" % closed_port())
        server = RecordingProxyServer(0, upstream, cache_proxy.LineLog(io.StringIO()))
        self.proxy_requests = server.requests
        return self.serve(server)

    def foreign_listener(self):
        return self.serve(socketserver.ThreadingTCPServer(("127.0.0.1", 0), ForeignHandler))

    def redirecting_listener(self):
        return self.serve(socketserver.ThreadingTCPServer(("127.0.0.1", 0), RedirectHandler))

    def silent_listener(self):
        """A port whose listener completes TCP handshakes but never reads or answers."""
        listener = socket.socket()
        self.addCleanup(listener.close)
        listener.bind(("127.0.0.1", 0))
        listener.listen(8)
        return "http://127.0.0.1:%d" % listener.getsockname()[1]

    def run_launcher(self, proxy_url, env=None, substitute=True, without_curl_and_jq=False, console_url=None):
        """`claude-account run` from a fresh copy of the mod, as a finished process.

        `without_curl_and_jq` points the copy's CURL and JQ at paths that do not exist."""
        copy = Path(tempfile.mkdtemp(dir=self.root)) / "accounts"
        shutil.copytree(ACCOUNTS, copy)
        script = copy / "bin" / "claude-account"
        text = script.read_text()
        self.assertEqual(text.count(PLACEHOLDER), 1)
        if substitute:
            text = text.replace(PLACEHOLDER, PLACEHOLDER + proxy_url)
        if without_curl_and_jq:
            for line in ("\nCURL=curl\n", "\nJQ=jq\n"):
                self.assertEqual(text.count(line), 1)
                text = text.replace(line, line.replace("=", "=/nonexistent/"))
        self.assertEqual(text.count(CONSOLE_LINE), 1)
        text = text.replace(CONSOLE_LINE, "\nCONSOLE_URL=" + (console_url or "http://127.0.0.1:%d" % closed_port()) + "\n")
        script.write_text(text)
        home, work = self.root / "home", self.root / "work"
        home.mkdir(exist_ok=True)
        work.mkdir(exist_ok=True)
        # An allowlist: the stand-in claude prints its environment, and a failing assertion shows it.
        child = {key: os.environ[key] for key in ("PATH", "TMPDIR") if key in os.environ}
        child.update(HOME=str(home), CLAUDE_ACCOUNTS_DIR=str(self.root / "accounts-state"),
                     CLAUDE_BIN=shutil.which("env"), **{**self.switch, **(env or {})})
        return subprocess.run([shutil.which("bash"), str(script), "run"], cwd=work, env=child,
                              capture_output=True, text=True, timeout=TIMEOUT, check=False)

    def launch(self, proxy_url, env=None, substitute=True, without_curl_and_jq=False, console_url=None):
        """The environment the stand-in claude printed; the launch must succeed silently."""
        completed = self.run_launcher(proxy_url, env, substitute, without_curl_and_jq, console_url)
        self.assertEqual((completed.returncode, completed.stderr), (0, ""))
        return dict(line.split("=", 1) for line in completed.stdout.splitlines() if "=" in line)

    def assert_routed(self, environment, url):
        self.assertEqual(environment.get("ANTHROPIC_BASE_URL"), url)
        self.assertEqual(environment.get("ENABLE_TOOL_SEARCH"), "true")
        self.assertEqual(environment.get(REMINDER), "padded-countdown")

    def assert_direct(self, environment):
        self.assertNotIn("ANTHROPIC_BASE_URL", environment)
        self.assertNotIn("ENABLE_TOOL_SEARCH", environment)
        self.assertNotIn(REMINDER, environment)

    def assert_not_probed(self):
        """No request reached the proxy: an opted-out launch costs no health check."""
        self.assertEqual(self.proxy_requests, [])


class RoutingTest(LauncherCase):
    """Launches with CLAUDE_CACHE_PROXY=1 keep #422's health-checked routing."""

    switch = {"CLAUDE_CACHE_PROXY": "1"}

    def test_a_healthy_proxy_routes_the_launch_after_one_probe(self):
        url = self.healthy_proxy()
        self.assert_routed(self.launch(url), url)
        self.assertEqual(self.proxy_requests, [cache_proxy.HEALTH_PATH])

    def test_the_probe_starts_no_curl_or_jq(self):
        url = self.healthy_proxy()
        self.assert_routed(self.launch(url, without_curl_and_jq=True), url)

    def test_a_listener_that_never_answers_launches_direct_within_two_seconds(self):
        url = self.silent_listener()
        started = time.monotonic()
        environment = self.launch(url)
        self.assertLess(time.monotonic() - started, 2.0)
        self.assert_direct(environment)

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
        self.assertNotIn(REMINDER, environment)

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

    def test_a_caller_set_reminder_value_is_kept_even_when_empty(self):
        url = self.healthy_proxy()
        for value in ("countdown", ""):
            with self.subTest(value=value):
                environment = self.launch(url, {REMINDER: value})
                self.assertEqual((environment.get("ANTHROPIC_BASE_URL"), environment.get(REMINDER)),
                                 (url, value))

    def test_an_unsubstituted_copy_never_routes(self):
        url = self.healthy_proxy()
        self.assert_direct(self.launch(url, substitute=False))
        environment = self.launch(url, {"ANTHROPIC_BASE_URL": url}, substitute=False)
        self.assertEqual(environment.get("ANTHROPIC_BASE_URL"), url)
        self.assertNotIn("ENABLE_TOOL_SEARCH", environment)
        self.assertNotIn(REMINDER, environment)


class DefaultRoutingTest(LauncherCase):
    """Routing is on by default (#450 D3, D18): unset, empty or 1 probes and routes, and only 0 opts out."""

    def test_an_unset_or_empty_switch_routes_after_one_probe(self):
        url = self.healthy_proxy()
        for switch in ({}, {"CLAUDE_CACHE_PROXY": ""}):
            with self.subTest(switch=switch):
                self.proxy_requests.clear()
                self.assert_routed(self.launch(url, switch), url)
                self.assertEqual(self.proxy_requests, [cache_proxy.HEALTH_PATH])

    def test_a_zero_switch_launches_direct_without_a_probe(self):
        self.assert_direct(self.launch(self.healthy_proxy(), {"CLAUDE_CACHE_PROXY": "0"}))
        self.assert_not_probed()

    def test_an_inherited_proxy_url_is_unset_under_zero_and_decided_again_otherwise(self):
        url = self.healthy_proxy()
        self.assert_direct(self.launch(url, {"ANTHROPIC_BASE_URL": url, "CLAUDE_CACHE_PROXY": "0"}))
        self.assert_not_probed()
        self.assert_routed(self.launch(url, {"ANTHROPIC_BASE_URL": url}), url)
        self.assertEqual(self.proxy_requests, [cache_proxy.HEALTH_PATH])
        down = "http://127.0.0.1:%d" % closed_port()
        self.assert_direct(self.launch(down, {"ANTHROPIC_BASE_URL": down}))

    def test_a_caller_set_endpoint_is_left_alone_either_way(self):
        url = self.healthy_proxy()
        for switch in ({}, {"CLAUDE_CACHE_PROXY": "0"}):
            with self.subTest(switch=switch):
                environment = self.launch(url, {"ANTHROPIC_BASE_URL": CALLER_URL, **switch})
                self.assertEqual(environment.get("ANTHROPIC_BASE_URL"), CALLER_URL)
                self.assertNotIn("ENABLE_TOOL_SEARCH", environment)
                self.assertNotIn(REMINDER, environment)
        self.assert_not_probed()

    def test_any_other_switch_value_fails_before_claude_starts(self):
        url = self.healthy_proxy()
        for substitute in (True, False):
            with self.subTest(substitute=substitute):
                completed = self.run_launcher(url, {"CLAUDE_CACHE_PROXY": "yes"}, substitute)
                self.assertEqual((completed.returncode, completed.stdout), (1, ""))
                self.assertEqual(completed.stderr,
                                 "claude-account: CLAUDE_CACHE_PROXY must be 1, 0, required or unset\n")


class RequiredRoutingTest(LauncherCase):
    """CLAUDE_CACHE_PROXY=required routes through the proxy or refuses the launch, never direct (#1009)."""

    switch = {"CLAUDE_CACHE_PROXY": "required"}

    def test_a_healthy_proxy_routes_a_required_launch_after_one_probe(self):
        url = self.healthy_proxy()
        self.assert_routed(self.launch(url), url)
        self.assertEqual(self.proxy_requests, [cache_proxy.HEALTH_PATH])

    def test_an_unavailable_proxy_refuses_a_required_launch_before_claude_starts(self):
        cases = (
            ("closed port", "http://127.0.0.1:%d" % closed_port(), True),
            ("silent", self.silent_listener(), True),
            ("foreign", self.foreign_listener(), True),
            ("redirect", self.redirecting_listener(), True),
            ("unsubstituted", self.healthy_proxy(), False),
        )
        for name, url, substitute in cases:
            with self.subTest(name):
                completed = self.run_launcher(url, None, substitute)
                self.assertEqual((completed.returncode, completed.stdout, completed.stderr),
                                 (1, "", REQUIRED_REFUSAL))

    def test_a_caller_set_endpoint_does_not_bypass_required(self):
        url = self.healthy_proxy()
        self.assert_routed(self.launch(url, {"ANTHROPIC_BASE_URL": CALLER_URL}), url)
        dead = "http://127.0.0.1:%d" % closed_port()
        completed = self.run_launcher(dead, {"ANTHROPIC_BASE_URL": CALLER_URL})
        self.assertEqual((completed.returncode, completed.stdout, completed.stderr),
                         (1, "", REQUIRED_REFUSAL))


class ProfileChoiceTest(LauncherCase):
    """A launch with CLAUDE_ACCOUNT unset starts under the profile the console chooses (#1012).

    The order is the console's answer, the choice file, the most recently used signed-in named
    profile, the first named profile by name; with no named profile the client is unprofiled."""

    switch = {"CLAUDE_CACHE_PROXY": "0"}

    def setUp(self):
        super().setUp()
        self.assertIsNotNone(shutil.which("jq"), "jq is required on PATH")
        self.state = self.root / "accounts-state"
        self.now = time.time()
        self.console_requests = []

    def profile(self, name, signed_in, used=None):
        directory = self.state / "profiles" / name
        directory.mkdir(parents=True, exist_ok=True)
        record = directory / ".claude.json"
        record.write_text('{"oauthAccount": {"emailAddress": "%s@example.invalid"}}' % name if signed_in else "{}")
        if used is not None:
            os.utime(record, (used, used))

    def choose(self, text):
        self.state.mkdir(parents=True, exist_ok=True)
        (self.state / "chosen-profile").write_text(text)

    def bind(self, name):
        work = self.root / "work"
        work.mkdir(exist_ok=True)
        self.state.mkdir(parents=True, exist_ok=True)
        (self.state / "bindings.tsv").write_text("%s\t%s\n" % (work.resolve(), name))

    def console(self, body, excluded=None):
        server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), ConsoleHandler)
        server.body = body
        if excluded is not None:
            server.excluded = excluded
        server.requests = self.console_requests
        return self.serve(server)

    def chosen(self, environment):
        return environment.get("CLAUDE_CONFIG_DIR")

    def path(self, name):
        return str(self.state / "profiles" / name)

    def closed(self):
        return "http://127.0.0.1:%d" % closed_port()

    def test_the_console_choice_wins_over_the_binding(self):
        self.profile("a", True, self.now - 100)
        self.profile("b", True, self.now)
        self.bind("b")
        self.choose("b\n")
        url = self.console(b'{"profile":"a"}')
        environment = self.launch(self.closed(), console_url=url)
        self.assertEqual(self.chosen(environment), self.path("a"))
        self.assertEqual(self.console_requests, ["/api/profile"])

    def test_an_unusable_console_answer_counts_as_none(self):
        self.profile("a", False, self.now)
        self.profile("b", True, self.now - 100)
        bodies = (b'{"profile":null}', b'{"profile":"default"}', b'{"profile":"ghost"}', b'{"profile":"../a"}',
                  b'{"profile": "a"}', b"not json")
        for body in bodies:
            with self.subTest(body=body):
                environment = self.launch(self.closed(), console_url=self.console(body))
                self.assertEqual(self.chosen(environment), self.path("b"))

    def test_the_choice_file_is_used_when_the_console_is_down(self):
        self.profile("a", True, self.now - 100)
        self.profile("b", True, self.now)
        self.choose(" a \n")
        self.bind("b")
        self.assertEqual(self.chosen(self.launch(self.closed())), self.path("a"))

    def test_a_silent_console_falls_back_within_the_deadline(self):
        url = self.silent_listener()
        self.profile("a", True, self.now - 100)
        self.profile("b", True, self.now)
        self.choose("a\n")
        started = time.monotonic()
        environment = self.launch(self.closed(), console_url=url)
        elapsed = time.monotonic() - started
        self.assertEqual(self.chosen(environment), self.path("a"))
        self.assertLess(elapsed, 2.0)

    def test_the_most_recently_used_signed_in_profile_is_next(self):
        self.profile("a", True, self.now - 100)
        self.profile("b", True, self.now)
        self.profile("c", False, self.now + 100)
        self.profile("default", True, self.now + 200)
        self.bind("a")
        for choice in (None, "ghost\n", "default\n"):
            with self.subTest(choice=choice):
                (self.state / "chosen-profile").unlink(missing_ok=True)
                if choice is not None:
                    self.choose(choice)
                self.assertEqual(self.chosen(self.launch(self.closed())), self.path("b"))

    def test_equal_use_breaks_ties_by_name(self):
        self.profile("b", True, self.now)
        self.profile("a", True, self.now)
        self.assertEqual(self.chosen(self.launch(self.closed())), self.path("a"))

    def test_the_first_named_profile_is_the_last_resort(self):
        self.profile("b", False, self.now)
        self.profile("a", False, self.now - 100)
        self.bind("b")
        self.assertEqual(self.chosen(self.launch(self.closed())), self.path("a"))

    def test_with_no_named_profile_the_launch_is_unprofiled_and_asks_no_console(self):
        (self.state / "profiles" / "default").mkdir(parents=True)
        (self.state / "profiles" / ".hidden").mkdir(parents=True)
        url = self.console(b'{"profile":"default"}')
        environment = self.launch(self.closed(), console_url=url)
        self.assertNotIn("CLAUDE_CONFIG_DIR", environment)
        self.assertEqual(self.console_requests, [])

    def test_claude_account_wins_over_the_console(self):
        self.profile("a", True, self.now)
        self.profile("b", True, self.now)
        url = self.console(b'{"profile":"a"}')
        environment = self.launch(self.closed(), {"CLAUDE_ACCOUNT": "b"}, console_url=url)
        self.assertEqual(self.chosen(environment), self.path("b"))
        self.assertEqual(self.console_requests, [])

    def test_a_caller_set_config_dir_wins_over_the_console(self):
        self.profile("a", True, self.now)
        url = self.console(b'{"profile":"a"}')
        custom = str(self.root / "custom")
        environment = self.launch(self.closed(), {"CLAUDE_CONFIG_DIR": custom}, console_url=url)
        self.assertEqual(self.chosen(environment), custom)
        self.assertNotIn("CLAUDE_ACCOUNT_LAUNCHER", environment)
        self.assertEqual(self.console_requests, [])

    def test_an_option_like_profile_name_is_launched(self):
        def fresh():
            shutil.rmtree(self.state, ignore_errors=True)

        with self.subTest("console"):
            fresh()
            self.profile("-n", False, self.now - 100)
            self.profile("a", True, self.now)
            url = self.console(b'{"profile":"-n"}')
            self.assertEqual(self.chosen(self.launch(self.closed(), console_url=url)), self.path("-n"))
        with self.subTest("choice file"):
            fresh()
            self.profile("-n", False, self.now - 100)
            self.profile("a", True, self.now)
            self.choose("-n\n")
            self.assertEqual(self.chosen(self.launch(self.closed())), self.path("-n"))
        with self.subTest("most recently used"):
            fresh()
            self.profile("-n", True, self.now)
            self.profile("a", True, self.now - 100)
            self.assertEqual(self.chosen(self.launch(self.closed())), self.path("-n"))
        with self.subTest("first by name"):
            fresh()
            self.profile("-e", False, self.now)
            self.profile("a", False, self.now)
            self.assertEqual(self.chosen(self.launch(self.closed())), self.path("-e"))

    def test_an_excluded_profile_is_not_the_most_recently_used_fallback(self):
        self.profile("a", True, self.now - 100)
        self.profile("b", True, self.now)
        url = self.console(b'{"profile":null}', b'{"excluded":["b"]}')
        environment = self.launch(self.closed(), console_url=url)
        self.assertEqual(self.chosen(environment), self.path("a"))
        self.assertEqual(self.console_requests, ["/api/profile", "/api/excluded"])

    def test_an_excluded_profile_is_not_the_first_named_last_resort(self):
        self.profile("a", False, self.now)
        self.profile("b", False, self.now)
        url = self.console(b'{"profile":null}', b'{"excluded":["a"]}')
        self.assertEqual(self.chosen(self.launch(self.closed(), console_url=url)), self.path("b"))

    def test_the_sole_signed_in_profile_excluded_is_not_started_by_the_fallback(self):
        self.profile("work", True, self.now)
        url = self.console(b'{"profile":null}', b'{"excluded":["work"]}')
        environment = self.launch(self.closed(), console_url=url)
        self.assertNotIn("CLAUDE_CONFIG_DIR", environment)

    def test_a_profile_excluded_among_two_leaves_the_other_one_signed_out_to_sign_in(self):
        self.profile("work", True, self.now)
        self.profile("other", False, self.now - 100)
        url = self.console(b'{"profile":null}', b'{"excluded":["work"]}')
        self.assertEqual(self.chosen(self.launch(self.closed(), console_url=url)), self.path("other"))

    def test_an_unusable_exclusion_answer_excludes_nothing(self):
        self.profile("a", True, self.now - 100)
        self.profile("b", True, self.now)
        bodies = (b'{"excluded":[b]}', b'{"excluded": ["b"]}', b'{"excluded":["../b"]}', b"not json", b"")
        for body in bodies:
            with self.subTest(body=body):
                url = self.console(b'{"profile":null}', body)
                self.assertEqual(self.chosen(self.launch(self.closed(), console_url=url)), self.path("b"))


if __name__ == "__main__":
    unittest.main()
