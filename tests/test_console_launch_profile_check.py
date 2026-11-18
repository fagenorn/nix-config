"""The launch-profile verify check (#894): `claude` launches under the console's profile and falls back to a named one.

Run: just agent-workflow-tests
"""
import contextlib
import http.server
import io
import json
import os
import shutil
import socket
import stat
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

from agent_tools.console import launch_profile_check as check
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)

ROOT = Path(__file__).resolve().parents[1]
WRAPPER = "home/common/verify-pending/checks/console-launch-profile"
LINE = "CONSOLE_URL=http://127.0.0.1:27184"
LAUNCHER = "#!/usr/bin/env bash\nset -eu\n" + LINE + "\nrun_it\n"


def snapshot(path):
    return sorted((str(p.relative_to(path)), stat.S_IMODE(p.lstat().st_mode)) for p in path.rglob("*"))


def closed_url():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return "http://127.0.0.1:%d" % probe.getsockname()[1]


class Layout(unittest.TestCase):
    """The installed layout in a temporary directory: a store mod, two-line wrappers, an accounts root."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.mod = self.tmp / "store" / "mod"
        (self.mod / "bin").mkdir(parents=True)
        (self.mod / "hooks").mkdir()
        (self.mod / "hooks" / "hooks.json").write_text("{}")
        self.launcher = self.mod / "bin" / "claude-account"
        self.launcher.write_text(LAUNCHER)
        self.launcher.chmod(0o755)
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.wrap("claude-account", '"$@"')
        self.wrap("claude", 'run "$@"')
        self.accounts = self.tmp / "accounts"
        for name in ("work", "home"):
            (self.accounts / "profiles" / name).mkdir(parents=True)
        self.home = self.tmp / "owner-home"
        self.home.mkdir()
        self.environ = {"HOME": str(self.home), "CLAUDE_ACCOUNTS_DIR": str(self.accounts), "PATH": str(self.bin)}
        self.calls = []
        self.body = b'{"profile": "work"}'
        self.writes = {"claude": lambda acc: acc / "profiles" / "work",
                       "mod": lambda acc: acc / "profiles" / "home"}
        self.codes = {}
        self.missing = False

    def wrap(self, name, args):
        path = self.bin / name
        path.write_text("#!/bin/sh\nexec %s/bin/claude-account %s\n" % (self.mod, args))
        path.chmod(0o755)

    def which(self, name):
        found = self.bin / name
        return str(found) if found.exists() else None

    def fetch(self, url):
        self.fetched = url
        return self.body

    def fake_run(self, argv, **kwargs):
        kind = "claude" if argv == ["claude"] else "mod"
        self.calls.append((kind, argv, kwargs))
        if self.missing and kind == "claude":
            raise FileNotFoundError("claude")
        line = self.writes[kind]
        if line is not None:
            acc = Path(kwargs["env"]["CLAUDE_ACCOUNTS_DIR"])
            text = line(acc)
            Path(kwargs["env"]["LAUNCH_PROFILE_OUT"]).write_text(str(text) + "\n")
        return subprocess.CompletedProcess(argv, self.codes.get(kind, 0))

    def main(self, *argv, fetch=None):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = check.main(list(argv), run=self.fake_run, fetch=fetch or self.fetch,
                              which=self.which, environ=self.environ)
        text = out.getvalue()
        return code, json.loads(text) if text else None


class VerdictTest(Layout):
    def spy_copy(self):
        """Records what `copy_mod` made while the temporary directory still exists."""
        copied = {}
        original = check.copy_mod

        def spy(mod, into, url):
            launcher = original(mod, into, url)
            copied.update(launcher=launcher, text=launcher.read_text(),
                          hooks=(launcher.parent.parent / "hooks" / "hooks.json").exists())
            return launcher

        check.copy_mod = spy
        self.addCleanup(setattr, check, "copy_mod", original)
        return copied

    def test_a_launch_under_the_consoles_profile_and_a_named_fallback_is_met(self):
        copied = self.spy_copy()
        code, out = self.main()
        self.assertEqual((code, out), (0, {"console_profile": "work", "fallback": "home",
                                           "launched": "work", "status": "met"}))
        (_, a_argv, a_kw), (_, b_argv, b_kw) = self.calls
        self.assertEqual(a_argv, ["claude"])
        self.assertEqual(b_argv[1:], ["run"])
        self.assertEqual(b_argv[0], str(copied["launcher"]))
        self.assertEqual(copied["launcher"].name, "claude-account")
        self.assertTrue(copied["hooks"])
        self.assertIn("\nCONSOLE_URL=http://127.0.0.1:", copied["text"])
        self.assertNotIn("27184", copied["text"])
        for kw in (a_kw, b_kw):
            env = kw["env"]
            self.assertNotIn("CLAUDE_ACCOUNT", env)
            self.assertEqual(env["CLAUDE_CACHE_PROXY"], "0")
            tmp = Path(env["CLAUDE_BIN"]).parent
            self.assertNotEqual(tmp, self.tmp)
            for key in ("HOME", "CLAUDE_ACCOUNTS_DIR", "LAUNCH_PROFILE_OUT"):
                self.assertTrue(Path(env[key]).is_relative_to(tmp), key)
            self.assertNotEqual(env["CLAUDE_ACCOUNTS_DIR"], str(self.accounts))
            self.assertEqual(kw["stdin"], subprocess.DEVNULL)
            self.assertTrue(kw["start_new_session"])
            self.assertEqual(kw["timeout"], 60)

    def test_the_launch_environment_drops_what_would_redirect_it(self):
        self.environ.update(CLAUDE_ACCOUNT="home", CLAUDE_CONFIG_DIR="/x", CLAUDE_CODE_PLUGIN_DIRS="/y",
                            CONSOLE_SPRINT_ID="s", CONSOLE_SPRINT_SECRET="t", KEEP="1")
        self.main()
        for _, _, kw in self.calls:
            env = kw["env"]
            for key in ("CLAUDE_ACCOUNT", "CLAUDE_CONFIG_DIR", "CLAUDE_CODE_PLUGIN_DIRS",
                        "CONSOLE_SPRINT_ID", "CONSOLE_SPRINT_SECRET"):
                self.assertNotIn(key, env)
            self.assertEqual(env["KEEP"], "1")

    def test_a_launcher_on_path_that_is_the_script_itself_is_its_own_mod(self):
        (self.bin / "claude-account").unlink()
        (self.bin / "claude-account").symlink_to(self.launcher)
        copied = self.spy_copy()
        code, out = self.main()
        self.assertEqual((code, out["status"]), (0, "met"))
        self.assertTrue(copied["hooks"])

    def test_a_wrapper_whose_target_has_no_address_line_is_not_met(self):
        self.launcher.write_text("#!/usr/bin/env bash\nrun_it\n")
        code, out = self.main()
        self.assertEqual((code, out["reason"]), (1, "the launcher's console address line is not found"))
        self.assertEqual([kind for kind, _, _ in self.calls], ["claude"])
        (self.bin / "claude-account").write_text("#!/bin/sh\necho hello\n")
        code, out = self.main()
        self.assertEqual((code, out["reason"]), (1, "the launcher's mod is not found"))

    def test_a_launcher_that_ignores_the_console_is_not_met(self):
        self.writes["claude"] = lambda acc: acc / "profiles" / "home"
        code, out = self.main()
        self.assertEqual((code, out["status"], out["reason"]),
                         (1, "not_met", "the launch did not use the console's profile"))

    def test_a_fallback_to_default_is_not_met(self):
        self.writes["mod"] = lambda acc: ""
        code, out = self.main()
        self.assertEqual((code, out["reason"]),
                         (1, "the launch with the console stopped did not use a named profile"))

    def test_a_console_without_a_choice_is_not_yet(self):
        self.body = b'{"profile": null}'
        self.assertEqual(self.main(), (75, {"status": "no_profile_chosen"}))
        self.assertEqual(self.calls, [])

    def test_a_console_that_does_not_answer_is_not_yet(self):
        self.assertEqual(self.main(fetch=lambda url: None), (75, {"status": "not_running"}))
        self.assertEqual(self.calls, [])

    def test_a_host_without_named_profiles_is_not_yet(self):
        shutil.rmtree(self.accounts / "profiles" / "work")
        shutil.rmtree(self.accounts / "profiles" / "home")
        (self.accounts / "profiles" / "Bad.Name").mkdir()
        self.assertEqual(self.main(), (75, {"status": "no_profiles"}))
        self.assertEqual(self.calls, [])

    def test_a_console_profile_that_is_not_configured_is_not_met(self):
        self.body = b'{"profile": "ghost"}'
        code, out = self.main()
        self.assertEqual((code, out["reason"]), (1, "the console's profile is not a configured profile"))
        self.assertEqual(self.calls, [])

    def test_a_malformed_console_answer_is_not_met(self):
        for body in (b"not json", b'{"profile": "work", "x": 1}', b'{"profile": 3}', b"[]"):
            self.body = body
            code, out = self.main()
            self.assertEqual((code, out["reason"]), (1, "the console's profile answer is malformed"), body)

    def test_a_missing_launcher_is_not_yet(self):
        self.missing = True
        self.assertEqual(self.main(), (75, {"status": "not_installed"}))
        self.missing = False
        (self.bin / "claude-account").unlink()
        self.assertEqual(self.main(), (75, {"status": "not_installed"}))

    def test_a_launch_that_fails_is_not_met(self):
        self.codes["claude"] = 1
        code, out = self.main()
        self.assertEqual((code, out["reason"]), (1, "the online launch exited 1"))
        self.codes = {"mod": 3}
        code, out = self.main()
        self.assertEqual((code, out["reason"]), (1, "the offline launch exited 3"))

    def test_a_launch_that_never_reaches_the_client_is_not_met(self):
        self.writes["claude"] = None
        code, out = self.main()
        self.assertEqual((code, out["reason"]), (1, "the launch did not reach the client"))

    def test_an_off_loopback_url_is_refused(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            self.main("--url", "http://example.com")
        self.assertEqual(raised.exception.code, 2)

    def test_the_check_asks_the_url_it_is_given(self):
        self.main("--url", "http://127.0.0.1:9999")
        self.assertEqual(self.fetched, "http://127.0.0.1:9999")

    def test_the_check_writes_nothing_outside_its_directory(self):
        before = (snapshot(self.accounts), snapshot(self.home))
        code, _ = self.main()
        self.assertEqual(code, 0)
        self.assertEqual((snapshot(self.accounts), snapshot(self.home)), before)
        for _, _, kw in self.calls:
            for key in ("LAUNCH_PROFILE_OUT", "HOME", "CLAUDE_ACCOUNTS_DIR"):
                self.assertFalse(Path(kw["env"][key]).parent.exists(), key)

    def test_the_choice_file_is_copied_into_the_isolated_root(self):
        (self.accounts / "chosen-profile").write_text("home\n")
        seen = []
        self.writes["claude"] = lambda acc: (seen.append((acc / "chosen-profile").read_text()),
                                             acc / "profiles" / "work")[1]
        self.main()
        self.assertEqual(seen, ["home\n"])


class InstalledLayoutTest(Layout):
    @unittest.skipUnless(shutil.which("bash") and shutil.which("jq"), "needs bash and jq")
    def test_the_real_launcher_through_its_installed_layout(self):
        shutil.rmtree(self.mod.parent)
        shutil.copytree(ROOT / "home/common/claude-code/accounts", self.mod)
        self.addCleanup(subprocess.run, ["chmod", "-R", "u+w", str(self.mod.parent)])
        subprocess.run(["chmod", "-R", "a-w", str(self.mod.parent)], check=True)
        found = check.find_mod(self.which)
        self.assertEqual(found, self.mod.resolve())
        t = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, t, True)
        accounts, names = check.isolated_accounts(self.accounts, t)
        self.assertEqual(names, ["home", "work"])
        client = check.stub_client(t)
        (t / "work").mkdir()
        (t / "home").mkdir()
        for url, expected in ((closed_url(), "home"), (self.serve('{"profile":"work"}'), "work")):
            out = t / ("out-" + expected)
            env = check.launch_env(os.environ, accounts, t / "home", client, out)
            copy = check.copy_mod(found, t / ("copy-" + expected), url)
            self.assertEqual(check.launch(subprocess.run, [str(copy), "run"], t / "work", env), 0)
            self.assertEqual(out.read_text().rstrip("\n"), str(accounts / "profiles" / expected))

    def serve(self, body):
        data = body.encode()

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200 if self.path == "/api/profile" else 404)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return "http://127.0.0.1:%d" % server.server_address[1]


class WrapperTest(unittest.TestCase):
    def test_the_wrapper_is_executable_in_the_index(self):
        listed = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-s", WRAPPER],
                                capture_output=True, text=True, check=True).stdout
        self.assertTrue(listed.startswith("100755"), listed)


if __name__ == "__main__":
    unittest.main()
