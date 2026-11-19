"""The console page account verify check (#894): a throwaway profile added and removed through the page.

Run: just agent-workflow-tests
"""
import contextlib
import io
import json
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest import mock

from agent_tools.console import capacity_check, page_account_check
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)

ROOT = Path(__file__).resolve().parents[1]
WRAPPER = "home/common/verify-pending/checks/console-page-account"
NAME = "zzcheck-mac"
URL = "http://127.0.0.1:27184"
PENDING = (75, '{"status": "pending"}')
MET = (0, '{"profiles": ["zzcheck-mac"], "status": "met"}')
ADD = "/api/account-add"
CANCEL = "/api/signin-cancel"
REMOVE = "/api/account-remove"
OK_ADD = (200, '{"attempt": 7, "link": "https://example.invalid/x", "profile": "zzcheck-mac"}')
BUSY = (409, "zzcheck-mac is still being read; try again in a moment")
RUNNING = (409, "a sign-in is running for zzcheck-mac; cancel it first")
LEFTOVER = (409, "account zzcheck-mac already exists")


class World:
    """Fakes for main's seams: a client factory answering from per-path scripts, a read, a sleep."""

    def __init__(self, test, answers, reads=(PENDING, MET)):
        self.answers = {path: list(script) for path, script in answers.items()}
        self.posts, self.built, self.reads, self.slept = [], [], [], []
        self.read_script = list(reads)
        directory = Path(tempfile.mkdtemp())
        test.addCleanup(lambda: [path.unlink() for path in directory.iterdir()] or directory.rmdir())
        self.token_file = directory / "token"
        self.token_file.write_text("tok123\n", encoding="utf-8")
        world = self

        class Client:
            def __init__(self, url, token):
                world.built.append((url, token))

            def post(self, path, document):
                world.posts.append((path, document))
                script = world.answers[path]
                return script.pop(0) if len(script) > 1 else script[0]

        self.client = Client

    def read(self, mode, after_seq, url):
        self.reads.append((mode, after_seq, url))
        script = self.read_script
        return script.pop(0) if len(script) > 1 else script[0]

    def run(self, *argv, token_file=None):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = page_account_check.main(
                [*argv, "--token-file", str(token_file or self.token_file)],
                client=self.client, read=self.read, sleep=self.slept.append)
        return code, out.getvalue()

    def paths(self):
        return [path for path, _ in self.posts]


class PageAccountCheckTest(unittest.TestCase):
    ARGS = ("--page-add", "--after-seq", "226986")

    def test_a_reading_already_met_posts_nothing(self):
        world = World(self, {}, reads=[MET])
        code, out = world.run("--page-remove", "--after-seq", "226986",
                              token_file=Path("/nonexistent/token"))
        self.assertEqual((code, out), (0, MET[1] + "\n"))
        self.assertEqual((world.built, world.posts, len(world.reads)), ([], [], 1))

    def test_the_round_trip_adds_cancels_and_removes_then_reads(self):
        world = World(self, {ADD: [OK_ADD], CANCEL: [(204, "")], REMOVE: [(204, "")]})
        code, out = world.run(*self.ARGS)
        self.assertEqual((code, out), (0, MET[1] + "\n"))
        self.assertEqual(world.built, [(URL, "tok123")] * 1)
        self.assertEqual(world.posts, [(ADD, {"name": NAME}), (CANCEL, {"profile": NAME}),
                                       (REMOVE, {"profile": NAME, "typed": NAME})])
        self.assertEqual(world.reads, [("page-add", 226986, URL)] * 2)
        self.assertNotIn("https://example.invalid/x", out)

    def test_a_console_without_the_gates_is_not_yet(self):
        world = World(self, {ADD: [(409, "adding an account is not available on this host")]})
        code, out = world.run(*self.ARGS)
        self.assertEqual((code, json.loads(out)), (75, {"status": "not_available"}))
        self.assertEqual((world.paths(), len(world.reads)), ([ADD], 1))

    def test_a_console_that_does_not_answer_is_not_yet(self):
        world = World(self, {ADD: [(None, "the console did not answer")]})
        code, out = world.run(*self.ARGS)
        self.assertEqual((code, json.loads(out)), (75, {"status": "not_running"}))
        self.assertEqual(world.paths(), [ADD])

    def test_no_token_is_not_yet(self):
        world = World(self, {})
        code, out = world.run(*self.ARGS, token_file=Path("/nonexistent/token"))
        self.assertEqual((code, json.loads(out)), (75, {"status": "no_token"}))
        self.assertEqual((world.built, world.posts), ([], []))

    def test_a_sign_in_that_cannot_start_still_removes_the_profile(self):
        reason = "the account was added; its sign-in could not start: spawn"
        world = World(self, {ADD: [(502, reason)],
                             CANCEL: [(409, "no sign-in is running for zzcheck-mac")],
                             REMOVE: [(204, "")]})
        code, out = world.run(*self.ARGS)
        self.assertEqual((code, json.loads(out)), (1, {"reason": reason, "status": "not_met"}))
        self.assertEqual(world.paths(), [ADD, CANCEL, REMOVE])
        self.assertEqual(len(world.reads), 1)

    def test_a_removal_still_being_read_is_retried_a_bounded_number_of_times(self):
        world = World(self, {ADD: [OK_ADD], CANCEL: [(204, "")], REMOVE: [BUSY, BUSY, (204, "")]})
        code, out = world.run(*self.ARGS)
        self.assertEqual((code, out), (0, MET[1] + "\n"))
        self.assertEqual(world.slept, [5, 5])
        with self.subTest("never done"):
            world = World(self, {ADD: [OK_ADD], CANCEL: [(204, "")], REMOVE: [BUSY]})
            code, out = world.run(*self.ARGS)
            document = json.loads(out)
            self.assertEqual((code, document["status"]), (1, "not_met"))
            self.assertTrue(document["reason"].startswith(
                f"the throwaway profile {NAME} was not removed: 409"), document)
            self.assertEqual(world.paths().count(REMOVE), 6)
            self.assertEqual(world.slept, [5] * 5)
            self.assertEqual(len(world.reads), 1)

    def test_a_cancelled_sign_in_still_running_is_waited_for_then_removed(self):
        world = World(self, {ADD: [OK_ADD], CANCEL: [(204, "")], REMOVE: [RUNNING, (204, "")]})
        code, out = world.run(*self.ARGS)
        self.assertEqual((code, out), (0, MET[1] + "\n"))
        self.assertEqual(world.slept, [5])

    def test_a_profile_that_was_already_there_is_left_alone(self):
        world = World(self, {ADD: [LEFTOVER], CANCEL: [(204, "")], REMOVE: [(204, "")]})
        code, out = world.run(*self.ARGS)
        document = json.loads(out)
        self.assertEqual((code, document["status"]), (1, "not_met"))
        self.assertIn(f"a profile named {NAME} already exists", document["reason"])
        self.assertEqual(world.paths(), [ADD])
        self.assertEqual(len(world.reads), 1)

    def test_an_unfinished_cleanup_is_resumed_before_the_met_reading_is_accepted(self):
        world = World(self, {CANCEL: [(204, "")], REMOVE: [(204, "")]}, reads=[MET])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = page_account_check.main(
                [*self.ARGS, "--token-file", str(world.token_file)], client=world.client,
                read=world.read, sleep=world.slept.append, left=lambda name, line: True)
        self.assertEqual((code, out.getvalue()), (0, MET[1] + "\n"))
        self.assertEqual(world.posts, [(CANCEL, {"profile": NAME}),
                                       (REMOVE, {"profile": NAME, "typed": NAME})])
        with self.subTest("the cleanup cannot reach the console"):
            world = World(self, {CANCEL: [(None, "the console did not answer")]}, reads=[MET])
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = page_account_check.main(
                    [*self.ARGS, "--token-file", str(world.token_file)], client=world.client,
                    read=world.read, sleep=world.slept.append, left=lambda name, line: True)
            self.assertEqual((code, json.loads(out.getvalue())), (75, {"status": "not_running"}))

    def test_a_lingering_profile_needs_the_reading_and_the_disk_to_name_it(self):
        directory = Path(tempfile.mkdtemp())
        self.addCleanup(directory.rmdir)
        (directory / "profiles").mkdir()
        self.addCleanup((directory / "profiles").rmdir)
        with mock.patch.object(capacity_check, "profiles_dir", lambda: directory / "profiles"):
            self.assertFalse(page_account_check.lingering(NAME, MET[1]))
            (directory / "profiles" / NAME).mkdir()
            self.addCleanup((directory / "profiles" / NAME).rmdir)
            self.assertTrue(page_account_check.lingering(NAME, MET[1]))
            self.assertFalse(page_account_check.lingering(NAME, '{"profiles": ["other"], "status": "met"}'))
            self.assertFalse(page_account_check.lingering(NAME, "not json"))

    def test_bad_arguments_exit_2(self):
        bad = [(), ("--page-add", "--page-remove", "--after-seq", "1"), ("--page-add",),
               ("--page-add", "--after-seq", "0"),
               ("--page-add", "--after-seq", "1", "--url", "http://example.com"),
               ("--page-add", "--after-seq", "1", "--name", "Bad.Name")]
        for argv in bad:
            with self.subTest(argv=argv):
                world = World(self, {})
                err = io.StringIO()
                with contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as raised:
                    world.run(*argv)
                self.assertEqual(raised.exception.code, 2)
                self.assertEqual(world.reads, [])

    def test_the_page_client_meets_the_write_guard(self):
        seen = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                size = int(self.headers.get("Content-Length", "0"))
                seen.append((self.command, self.path, self.headers.get_all("Origin"),
                             self.headers.get_all("X-Console-Token"),
                             self.headers.get_all("Content-Type"),
                             json.loads(self.rfile.read(size))))
                body = b'{"profile": "zzcheck-mac", "link": "https://example.invalid/x"}'
                if self.path == ADD:
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                else:
                    self.send_response(204)
                    self.send_header("Content-Length", "0")
                    self.end_headers()

            def log_message(self, *args):
                pass

        server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        port = server.server_address[1]
        world = World(self, {})
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = page_account_check.main(
                ["--page-add", "--after-seq", "1", "--url", f"http://127.0.0.1:{port}",
                 "--token-file", str(world.token_file)], read=world.read, sleep=world.slept.append)
        self.assertEqual(code, 0)
        self.assertEqual([(method, path) for method, path, *_ in seen],
                         [("POST", ADD), ("POST", CANCEL), ("POST", REMOVE)])
        for _, _, origin, token, content_type, _ in seen:
            self.assertEqual(origin, [f"http://127.0.0.1:{port}"])
            self.assertEqual(token, ["tok123"])
            self.assertEqual(content_type, ["application/json"])
        self.assertNotIn("tok123", out.getvalue() + err.getvalue())

    def test_the_default_reading_is_the_watermarked_page_check(self):
        calls = []

        def recorder(argv):
            calls.append(argv)
            print('{"status": "pending"}')
            return 75

        out = io.StringIO()
        with mock.patch.object(capacity_check, "main", recorder), contextlib.redirect_stdout(out):
            answer = page_account_check.reading("page-remove", 226986, URL)
        self.assertEqual(answer, (75, '{"status": "pending"}'))
        self.assertEqual(calls, [["--page-remove", "--after-seq", "226986", "--url",
                                  URL + "/api/state"]])
        self.assertEqual(out.getvalue(), "")

    def test_the_wrapper_is_executable_in_the_index(self):
        listed = subprocess.run(["git", "ls-files", "-s", WRAPPER], cwd=ROOT,
                                capture_output=True, text=True, check=True).stdout
        self.assertTrue(listed.startswith("100755"), listed)


if __name__ == "__main__":
    unittest.main()
