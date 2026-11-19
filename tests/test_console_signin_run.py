"""The console's sign-in runner (#1026): command, environment, link and code rules, runs, rows and fold.

Run: just agent-workflow-tests
"""

import contextlib
import inspect
import io
import json
import os
import socket
import sys
import tempfile
import textwrap
import threading
import time
import unittest
from contextlib import redirect_stderr
from pathlib import Path

from agent_tools.console import event_log, signin_run
from agent_tools.console.event_log import Event
from agent_tools.console.signin_run import (
    ACTED, ENDED, CODE_END, CODE_INPUT, LINK_WAIT, LOGIN_DEADLINE, MAX_CODE_CHARS, MAX_LINK_CHARS,
    Ended, NotRunning, SignIns, Started, StartFailed, acted, ended, ended_state, login_command,
    login_environment, parse_code_request, parse_profile_request, runs_for, valid_link)
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)
from .process_liveness import process_alive

LINK = "https://claude.example/oauth/authorize?state=SENTINEL-LINK-7f3a"
CODE = "SENTINEL-CODE-91c2#x"
LOOPBACK_LINK = ("https://claude.example/oauth/authorize?code=true"
                 "&redirect_uri=http%3A%2F%2Flocalhost%3A54321%2Fcallback"
                 "&state=SENTINEL-LINK-loop")
MANUAL_LINK = ("https://claude.example/oauth/authorize?code=true"
               "&redirect_uri=https%3A%2F%2Fplatform.claude.example%2Foauth%2Fcode%2Fcallback"
               "&state=SENTINEL-LINK-manual")
NOISE_LINK = ("https://claude.example/oauth/authorize"
              "?redirect_uri=http%3A%2F%2Flocalhost%3A1%2Fcallback&state=SENTINEL-OUT")
BAD_LINK = ("https://[SENTINEL-OUT/oauth/authorize"
            "?redirect_uri=https%3A%2F%2Fplatform.claude.example%2Fcb")
LOOPBACK_FORWARD = "ssh -N -L 54321:localhost:54321 console-host"


def route_of(link):
    return (getattr(link, "url", link), getattr(link, "route", None),
            getattr(link, "port", None), getattr(link, "forward", None))


@contextlib.contextmanager
def stderr_text():
    """Everything written to stderr inside the block: Python's and descriptor 2's, joined."""
    class Captured:
        text = ""

    captured = Captured()
    python_side = io.StringIO()
    saved = os.dup(2)
    with tempfile.TemporaryFile() as descriptor_side:
        try:
            with contextlib.redirect_stderr(python_side):
                os.dup2(descriptor_side.fileno(), 2)
                yield captured
        finally:
            os.dup2(saved, 2)
            os.close(saved)
            descriptor_side.seek(0)
            captured.text = python_side.getvalue() + descriptor_side.read().decode(
                "utf-8", "replace")

FAKE = textwrap.dedent('''\
    #!%(python)s
    import json, os, socket, subprocess, sys, time

    def record(entry):
        with open(os.environ["FAKE_RECORD"], "a") as handle:
            handle.write(json.dumps(entry) + "\\n")

    mode = os.environ["FAKE_MODE"]
    record({"argv": sys.argv[1:], "account": os.environ.get("CLAUDE_ACCOUNT"),
            "browser_set": bool(os.environ.get("BROWSER")),
            "api_key": "ANTHROPIC_API_KEY" in os.environ,
            "token": "ANTHROPIC_AUTH_TOKEN" in os.environ,
            "base_url": "ANTHROPIC_BASE_URL" in os.environ,
            "proxy": os.environ.get("CLAUDE_CACHE_PROXY"),
            "leader": os.getsid(0) == os.getpid(), "cwd": os.getcwd(),
            "stdin_tty": os.isatty(0)})

    def out(text, stream=sys.stdout):
        stream.write(text)
        stream.flush()

    def offer(manual):
        out("Opening browser to sign in...\\n")
        out("If the browser didn't open, visit: \\x1b]8;;" + manual + "\\x07" + manual
            + "\\x1b]8;;\\x07\\n")

    noise = os.environ.get("FAKE_NOISE")
    manual = os.environ.get("FAKE_MANUAL")
    delay = os.environ.get("FAKE_MANUAL_DELAY")
    if noise:
        for _ in range(200):
            out("SENTINEL-OUT " + "x" * 1490 + "\\n")
        out("see javascript:SENTINEL-OUT and " + noise + "\\n")
    if os.environ.get("FAKE_BAD"):
        out(os.environ["FAKE_BAD"] + "\\n")
    if manual and not delay:
        offer(manual)
    if mode != "nolink":
        subprocess.run([os.environ["BROWSER"], os.environ["FAKE_LINK"]])
    if manual and delay:
        time.sleep(float(delay))
        offer(manual)
        record({"manual_written": True})
    if noise:
        for _ in range(200):
            out("SENTINEL-OUT " + "x" * 1490 + "\\n")
            out("SENTINEL-ERR " + "y" * 1490 + "\\n", sys.stderr)
    if mode != "nolink":
        out("Paste code here if prompted > ")
    if mode in ("code", "nolink"):
        line = sys.stdin.readline()
        record({"code": line.rstrip("\\r\\n")})
        sys.exit(int(os.environ.get("FAKE_EXIT", "0")))
    if mode == "deaf":
        os.close(0)
        record({"deaf": True})
        time.sleep(600)
    if mode == "stuck":
        record({"stuck": True})
        time.sleep(600)
    if mode == "hang":
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen()
        record({"grandchild": child.pid, "port": server.getsockname()[1]})
        time.sleep(600)
    ''')


def until(test, condition, seconds=10.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if condition():
            return
        time.sleep(0.02)
    test.fail("condition not reached in time")


class ConstantsTest(unittest.TestCase):
    def test_the_command_environment_and_limits(self):
        self.assertEqual(login_command(), ["claude-account", "run", "auth", "login"])
        environ = {"HOME": "/h", "PATH": "/bin", "ANTHROPIC_API_KEY": "k",
                   "ANTHROPIC_AUTH_TOKEN": "t", "ANTHROPIC_BASE_URL": "http://x",
                   "CLAUDE_CACHE_PROXY": "1"}
        env = login_environment("work", environ, "/x/browser")
        self.assertEqual(env["CLAUDE_ACCOUNT"], "work")
        self.assertEqual(env["BROWSER"], "/x/browser")
        self.assertEqual(env["CLAUDE_CACHE_PROXY"], "0")
        for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL"):
            self.assertNotIn(name, env)
        self.assertEqual((LOGIN_DEADLINE, LINK_WAIT, MAX_LINK_CHARS, MAX_CODE_CHARS),
                         (600, 15, 4096, 512))
        self.assertEqual((signin_run.MANUAL_GRACE, signin_run.ROUTES),
                         (2.0, ("manual", "loopback", "unknown")))
        self.assertIn(CODE_INPUT, ("pipe", "pty"))
        self.assertEqual(CODE_END, {"pipe": "\n", "pty": "\r"})
        self.assertEqual(event_log.SIGNIN_ACTED, "signin.acted")
        self.assertEqual(event_log.SIGNIN_ENDED, "signin.ended")
        self.assertNotIn("signin.acted", event_log.KEPT_KINDS)
        self.assertNotIn("signin.ended", event_log.KEPT_KINDS)
        self.assertEqual((ACTED, ENDED), ("signin.acted", "signin.ended"))


class ParseTest(unittest.TestCase):
    def test_the_request_and_link_tables(self):
        self.assertEqual(parse_profile_request(b'{"profile":"work"}'), "work")
        for body in (b'[]', b'{}', b'{"profile":""}', b'{"profile":1}', b'{"profile":"w","x":1}',
                     b'\xff'):
            with self.subTest(body=body), self.assertRaises(ValueError):
                parse_profile_request(body)
        self.assertEqual(parse_code_request(b'{"profile":"work","code":"ab#C-1"}'),
                         ("work", "ab#C-1"))
        for code in ("", "a b", "a\nb", "é", "a" * 513):
            with self.subTest(code=code), self.assertRaises(ValueError):
                parse_code_request(json.dumps({"profile": "work", "code": code}).encode())
        for body in (b'{"profile":"work"}', b'{"code":"a"}',
                     b'{"profile":"work","code":"a","x":1}', b'{"profile":"","code":"a"}'):
            with self.subTest(body=body), self.assertRaises(ValueError):
                parse_code_request(body)
        self.assertEqual(parse_code_request(
            json.dumps({"profile": "work", "code": "a" * 512}).encode())[1], "a" * 512)
        self.assertTrue(valid_link(LINK))
        for text in ("http://x", "javascript:alert(1)", "https://a b", "https://x\n",
                     "https://" + "a" * 4089):
            with self.subTest(text=text[:20]):
                self.assertFalse(valid_link(text))
        self.assertTrue(valid_link("https://" + "a" * 4088))


    def test_link_route_table(self):
        def query(text):
            return "https://a.example/o?" + text

        rows = [
            (LOOPBACK_LINK, ("loopback", 54321)),
            (query("redirect_uri=http%3A%2F%2F127.0.0.1%3A8%2Fcallback"), ("loopback", 8)),
            (query("redirect_uri=http%3A%2F%2F%5B%3A%3A1%5D%3A9%2Fcallback"), ("loopback", 9)),
            (query("redirect_uri=http%3A%2F%2Flocalhost%2Fcallback"), ("loopback", 80)),
            (query("redirect_uri=http%3A%2F%2F%5B0%3A0%3A0%3A0%3A0%3A0%3A0%3A1%5D%3A54321%2Fcallback"),
             ("loopback", 54321)),
            (query("redirect_uri=http%3A%2F%2F%5B0%3A0%3A0%3A0%3A0%3A0%3A0%3A1%5D%2Fcallback"),
             ("loopback", 80)),
            (query("redirect_uri=https%3A%2F%2F%5B0%3A0%3A0%3A0%3A0%3A0%3A0%3A1%5D%3A5%2Fcb"), None),
            ("https://?redirect_uri=https%3A%2F%2Fexample.com%2Fcallback", None),
            ("https://:8443/o?redirect_uri=https%3A%2F%2Fexample.com%2Fcallback", None),
            (query("redirect_uri=http%3A%2F%2Flocalhost%3A99999%2Fcallback"), None),
            (query("redirect_uri=https%3A%2F%2Fexample.com%3A99999%2Fcb"), None),
            (query("redirect_uri=https%3A%2F%2Fexample.com%3A0%2Fcb"), None),
            (query("redirect_uri=https%3A%2F%2Fexample.com%3A8443%2Fcb"), ("manual", None)),
            ("https://a.example:99999/o?redirect_uri=https%3A%2F%2Fexample.com%2Fcb", None),
            (query("redirect_uri=http%3A%2F%2F%5B%3A%3A1%2Fcallback"), None),
            (BAD_LINK, None),
            (MANUAL_LINK, ("manual", None)),
            (LINK, None),
            (query("redirect_uri=http%3A%2F%2Fevil.example%2Fcb"), None),
            (query("redirect_uri=https%3A%2F%2Flocalhost%3A5%2Fcb"), None),
            (query("redirect_uri=https%3A%2F%2Fplatform.claude.example%2Fcb"
                   "&redirect_uri=http%3A%2F%2Flocalhost%3A5%2Fcb"), None),
        ]
        for url, expected in rows:
            with self.subTest(url=url[:60]):
                self.assertEqual(signin_run.link_route(url), expected)

    def test_output_links_finds_each_https_token_of_a_line(self):
        manual = MANUAL_LINK.encode()
        rows = [
            (b"If the browser didn't open, visit: \x1b]8;;" + manual + b"\x07" + manual
             + b"\x1b]8;;\x07", [MANUAL_LINK, MANUAL_LINK]),
            (b"visit: " + manual, [MANUAL_LINK]),
            (b"javascript:x https://a b", ["https://a"]),
            (b"\xffhttps://x\xff", ["https://x"]),
            (b"https://" + b"a" * 4089, []),
            (b"no link here", []),
        ]
        for line, expected in rows:
            with self.subTest(line=line[:40]):
                self.assertEqual(signin_run.output_links(line), expected)

    def test_lines_drop_a_token_the_limit_cut_in_two(self):
        rows = [
            (10, b"ab cdefghijkl\n", [b"ab "]),
            (10, b"abcdefghi jkl\n", [b"abcdefghi "]),
            (10, b"abcdefghijkl\nnext\n", [b"", b"next"]),
            (10, b"abcdefghij\n", [b"abcdefghij"]),
        ]
        for limit, data, expected in rows:
            with self.subTest(data=data):
                self.assertEqual(signin_run._Lines(limit).feed(data), expected)
        chunked = signin_run._Lines(10)
        self.assertEqual(chunked.feed(b"ab cdefgh") + chunked.feed(b"ijkl\n"), [b"ab "])

    def test_forward_command_table(self):
        self.assertEqual(signin_run.forward_command(54321, "console-host"), LOOPBACK_FORWARD)
        self.assertEqual(signin_run.forward_command(80, "h"), "ssh -N -L 80:localhost:80 h")
        for port, host in ((0, "h"), (65536, "h"), (5, "a b"), (5, "-x"), (5, ""), (5, "h;rm")):
            with self.subTest(port=port, host=host):
                self.assertIsNone(signin_run.forward_command(port, host))

    def test_answer_members(self):
        self.assertEqual(signin_run.answer_members(None),
                         {"link": None, "route": None, "port": None, "forward": None})
        self.assertEqual(
            signin_run.answer_members(signin_run.Link(
                LOOPBACK_LINK, "loopback", 54321, "ssh -N -L 54321:localhost:54321 h")),
            {"link": LOOPBACK_LINK, "route": "loopback", "port": 54321,
             "forward": "ssh -N -L 54321:localhost:54321 h"})
        self.assertEqual(
            signin_run.answer_members(signin_run.Link(LINK, "unknown", None, None)),
            {"link": LINK, "route": "unknown", "port": None, "forward": None})


class EntryTest(unittest.TestCase):
    def test_rows_and_fold(self):
        self.assertEqual(acted("work", "start", "started"),
                         ("signin.acted", None, {"by": "owner", "profile": "work",
                                                 "action": "start", "outcome": "started"}))
        for call in (lambda: acted("work", "code", "started"),
                     lambda: acted("work", "stop", "cancelled"),
                     lambda: ended("work", "running", 3),
                     lambda: ended("work", "failed", 0),
                     lambda: ended("work", "failed", True)):
            with self.assertRaises(ValueError):
                call()
        self.assertEqual(ended("work", "timed_out", 7),
                         ("signin.ended", None, {"profile": "work", "outcome": "timed_out",
                                                 "attempt": 7}))
        rows = [
            ended("work", "failed", 5), ended("work", "signed_in", 7), ended("", "failed", 8),
            ("signin.ended", None, {"profile": "x", "outcome": "bogus", "attempt": 9}),
            ("signin.ended", None, {"profile": "y", "outcome": "failed", "attempt": "9"}),
            acted("work", "start", "started"),
        ]
        events = [Event(seq=n, at=f"t{n}", kind=kind, project=project, payload=payload)
                  for n, (kind, project, payload) in enumerate(rows, start=1)]
        folded = ended_state(events)
        self.assertEqual(folded, {"work": Ended("signed_in", "t2", 7)})
        half = ended_state(events[:3])
        self.assertEqual(ended_state(events[3:], half), folded)

    def test_an_older_attempts_late_row_never_replaces_a_newer_result(self):
        rows = [ended("work", "signed_in", 9), ended("work", "cancelled", 4),
                ended("work", "failed", 9)]
        events = [Event(seq=n, at=f"t{n}", kind=kind, project=project, payload=payload)
                  for n, (kind, project, payload) in enumerate(rows, start=1)]
        self.assertEqual(ended_state(events[:2]), {"work": Ended("signed_in", "t1", 9)})
        self.assertEqual(ended_state(events), {"work": Ended("failed", "t3", 9)})
        self.assertEqual(ended_state(events[1:2], ended_state(events[:1])),
                         {"work": Ended("signed_in", "t1", 9)})


class RunTest(unittest.TestCase):
    def arrange(self, mode, **extra):
        root = Path(tempfile.mkdtemp(prefix="signin-run-test-"))
        self.addCleanup(lambda: __import__("shutil").rmtree(root, ignore_errors=True))
        self.bin = root / "bin"
        self.bin.mkdir()
        script = self.bin / "claude-account"
        script.write_text(FAKE % {"python": sys.executable})
        script.chmod(0o755)
        self.record = root / "record.jsonl"
        self.environ = {"HOME": str(root), "PATH": f"{self.bin}:/usr/bin:/bin",
                        "ANTHROPIC_API_KEY": "k", "ANTHROPIC_AUTH_TOKEN": "t",
                        "ANTHROPIC_BASE_URL": "http://127.0.0.1:1",
                        "FAKE_RECORD": str(self.record), "FAKE_MODE": mode, "FAKE_LINK": LINK}
        self.environ.update(extra)
        self.ends = []
        self.now = [1000.0]
        self.kwargs = {}
        return root

    def make(self, **kwargs):
        wanted = {"manual_grace": 0.2, "host": "console-host", **kwargs}
        known = inspect.signature(SignIns).parameters
        runs = SignIns(on_end=lambda *args: self.ends.append(args), environ=self.environ,
                       clock=lambda: self.now[0],
                       **{key: value for key, value in wanted.items() if key in known})
        self.addCleanup(runs.close)
        return runs

    def lines(self):
        if not self.record.exists():
            return []
        return [json.loads(line) for line in self.record.read_text().splitlines()]

    def wait_record(self, key):
        found = []
        def has():
            found[:] = [line for line in self.lines() if key in line]
            return bool(found)
        until(self, has)
        return found[0]

    def alive(self, pid):
        return process_alive(pid)

    def test_the_link_the_client_hands_its_browser_is_returned(self):
        self.arrange("code")
        runs = self.make()
        self.assertEqual(runs.start("work"), Started(1, True))
        self.assertEqual(route_of(runs.wait_link("work")), (LINK, "unknown", None, None))
        self.assertEqual(runs.running(), frozenset({"work"}))
        first = self.lines()[0]
        self.assertEqual(first["argv"], ["run", "auth", "login"])
        self.assertEqual(first["account"], "work")
        self.assertTrue(first["browser_set"])
        self.assertFalse(first["api_key"] or first["token"] or first["base_url"])
        self.assertEqual(first["proxy"], "0")
        self.assertTrue(first["leader"])
        self.assertEqual(first["stdin_tty"], signin_run.CODE_INPUT == "pty")

    def test_a_pasted_code_reaches_the_clients_input(self):
        self.arrange("code")
        runs = self.make()
        runs.start("work")
        runs.wait_link("work")
        cwd = self.lines()[0]["cwd"]
        runs.send_code("work", CODE)
        until(self, lambda: self.ends)
        self.assertIn({"code": CODE}, self.lines())
        self.assertEqual(self.ends, [("work", 1, "exited", 0)])
        self.assertEqual(runs.running(), frozenset())
        self.assertFalse(os.path.exists(cwd))

    def test_a_second_start_while_one_runs_starts_no_second_client(self):
        self.arrange("code")
        runs = self.make()
        self.assertEqual(runs.start("work"), Started(1, True))
        self.assertEqual(runs.start("work"), Started(1, False))
        self.assertEqual(route_of(runs.wait_link("work")), (LINK, "unknown", None, None))
        self.assertEqual(route_of(runs.wait_link("work")), (LINK, "unknown", None, None))
        self.assertEqual(len([line for line in self.lines() if "argv" in line]), 1)

    def test_a_run_past_its_deadline_is_killed_with_its_group_and_its_port_released(self):
        self.arrange("hang")
        runs = self.make()
        runs.start("work")
        found = self.wait_record("grandchild")
        self.now[0] += 599
        self.assertEqual(runs.expire(), [])
        self.now[0] += 1
        self.assertEqual(runs.expire(), ["work"])
        until(self, lambda: self.ends)
        self.assertEqual(self.ends[0][:3], ("work", 1, "timed_out"))
        self.assertIsInstance(self.ends[0][3], int)
        until(self, lambda: not self.alive(found["grandchild"]), 5)
        with self.assertRaises(ConnectionRefusedError):
            socket.create_connection(("127.0.0.1", found["port"]), timeout=1)
        self.assertEqual(runs.start("work"), Started(2, True))
        until(self, lambda: len([line for line in self.lines() if "argv" in line]) == 2)

    def test_a_cancelled_run_is_killed_with_its_group(self):
        self.arrange("hang")
        runs = self.make()
        runs.start("work")
        found = self.wait_record("grandchild")
        runs.cancel("work")
        until(self, lambda: self.ends)
        self.assertEqual(self.ends[0][:3], ("work", 1, "cancelled"))
        self.assertIsInstance(self.ends[0][3], int)
        until(self, lambda: not self.alive(found["grandchild"]), 5)

    def test_a_write_the_clients_input_refuses_is_not_a_missing_run(self):
        self.arrange("deaf")
        runs = self.make()
        runs.start("work")
        self.wait_record("deaf")
        with self.assertRaises(BrokenPipeError):
            runs.send_code("work", CODE)
        self.assertEqual(runs.running(), frozenset({"work"}))
        runs.cancel("work")
        until(self, lambda: self.ends)

    def test_a_client_that_stopped_reading_cannot_hold_up_a_cancel(self):
        self.arrange("stuck")
        runs = self.make()
        runs.start("work")
        self.wait_record("stuck")
        outcome = []

        def fill():
            for _ in range(2000):
                try:
                    runs.send_code("work", "x" * MAX_CODE_CHARS)
                except OSError as error:
                    outcome.append(error)
                    return
            outcome.append(None)

        writer = threading.Thread(target=fill, daemon=True)
        writer.start()
        writer.join(10)
        self.assertFalse(writer.is_alive(), "a write to a full input blocked")
        self.assertIsInstance(outcome[0], BlockingIOError)
        done = threading.Event()

        def cancel():
            runs.cancel("work")
            done.set()

        threading.Thread(target=cancel, daemon=True).start()
        self.assertTrue(done.wait(5), "cancel waited on the blocked write")
        until(self, lambda: self.ends)
        self.assertEqual(self.ends[0][:3], ("work", 1, "cancelled"))

    def test_code_and_cancel_need_a_running_sign_in(self):
        self.arrange("code")
        runs = self.make()
        with self.assertRaises(NotRunning):
            runs.send_code("work", "a")
        with self.assertRaises(NotRunning):
            runs.cancel("work")

    def test_an_unusable_link_is_dropped_without_its_text(self):
        self.arrange("code", FAKE_LINK="javascript:SENTINEL-BAD")
        runs = self.make(link_wait=0.5)
        err = io.StringIO()
        with redirect_stderr(err):
            runs.start("work")
            self.assertIsNone(runs.wait_link("work"))
            until(self, lambda: err.getvalue())
        self.assertEqual(err.getvalue(), "console: signin_link_refused work\n")
        self.assertNotIn("SENTINEL-BAD", err.getvalue())

    def test_a_client_offering_a_manual_link_hands_back_the_manual_route(self):
        self.arrange("code", FAKE_LINK=LOOPBACK_LINK, FAKE_MANUAL=MANUAL_LINK)
        runs = self.make()
        runs.start("work")
        link = runs.wait_link("work")
        runs.send_code("work", CODE)
        until(self, lambda: self.ends)
        self.assertEqual(route_of(link), (MANUAL_LINK, "manual", None, None))
        self.assertIn({"code": CODE}, self.lines())

    def test_a_client_offering_only_a_loopback_link_names_its_port_and_forward_command(self):
        self.arrange("code", FAKE_LINK=LOOPBACK_LINK)
        runs = self.make()
        runs.start("work")
        link = runs.wait_link("work")
        self.assertEqual(route_of(link), (LOOPBACK_LINK, "loopback", 54321, LOOPBACK_FORWARD))

    def test_a_link_whose_return_cannot_be_read_is_handed_out_as_unknown(self):
        for fake_link in (LINK, "https://a.example/o?redirect_uri=http%3A%2F%2Flocalhost"
                                "%3A99999%2Fcallback"):
            with self.subTest(link=fake_link[:40]):
                self.arrange("code", FAKE_LINK=fake_link)
                runs = self.make()
                runs.start("work")
                link = runs.wait_link("work")
                self.assertEqual(route_of(link), (fake_link, "unknown", None, None))

    def test_a_manual_link_printed_after_the_browser_call_within_the_grace_wins(self):
        self.arrange("code", FAKE_LINK=LOOPBACK_LINK, FAKE_MANUAL=MANUAL_LINK,
                     FAKE_MANUAL_DELAY="0.3")
        runs = self.make(manual_grace=3)
        runs.start("work")
        link = runs.wait_link("work")
        self.assertEqual(route_of(link)[:2], (MANUAL_LINK, "manual"))

    def test_a_loopback_link_is_answered_once_the_grace_passes(self):
        self.arrange("code", FAKE_LINK=LOOPBACK_LINK)
        runs = self.make(manual_grace=0.3, link_wait=10)
        runs.start("work")
        began = time.monotonic()
        link = runs.wait_link("work")
        elapsed = time.monotonic() - began
        self.assertEqual(route_of(link)[1], "loopback")
        self.assertLess(elapsed, 5)

    def test_the_route_handed_out_stays_the_same_for_the_attempt(self):
        self.arrange("code", FAKE_LINK=LOOPBACK_LINK, FAKE_MANUAL=MANUAL_LINK,
                     FAKE_MANUAL_DELAY="1.0")
        runs = self.make(manual_grace=0.2)
        expected = (LOOPBACK_LINK, "loopback", 54321, LOOPBACK_FORWARD)
        runs.start("work")
        first = runs.wait_link("work")
        self.assertEqual(route_of(first), expected)
        self.wait_record("manual_written")
        until(self, lambda: getattr(runs._runs.get("work"), "manual", None) is not None)
        second = runs.wait_link("work")
        self.assertEqual(route_of(second), expected)

    def test_an_unusable_manual_link_does_not_displace_a_working_one(self):
        unusable = ("https://claude.example/oauth/authorize?code=true"
                    "&redirect_uri=https%3A%2F%2Fexample.com%3A99999%2Fcb&state=SENTINEL-OUT")
        self.arrange("code", FAKE_LINK=LOOPBACK_LINK, FAKE_BAD=unusable,
                     FAKE_MANUAL=MANUAL_LINK)
        runs = self.make()
        runs.start("work")
        self.assertEqual(route_of(runs.wait_link("work")), (MANUAL_LINK, "manual", None, None))

    def test_a_line_cut_by_the_output_limit_never_hands_out_a_shortened_link(self):
        cut = len(MANUAL_LINK) - 5
        long_line = " " * (signin_run.MAX_OUTPUT_LINE - cut) + MANUAL_LINK
        self.arrange("code", FAKE_LINK=LOOPBACK_LINK, FAKE_BAD=long_line,
                     FAKE_MANUAL=MANUAL_LINK, FAKE_MANUAL_DELAY="0.3")
        runs = self.make(manual_grace=5)
        runs.start("work")
        self.assertEqual(route_of(runs.wait_link("work")), (MANUAL_LINK, "manual", None, None))

    def test_a_request_deadline_inside_the_grace_waits_out_the_grace_for_the_manual_link(self):
        self.arrange("code", FAKE_LINK=LOOPBACK_LINK, FAKE_MANUAL=MANUAL_LINK,
                     FAKE_MANUAL_DELAY="1.5")
        runs = self.make(manual_grace=8, link_wait=0.6)
        runs.start("work")
        self.assertEqual(route_of(runs.wait_link("work")), (MANUAL_LINK, "manual", None, None))
        self.assertEqual(route_of(runs.wait_link("work")), (MANUAL_LINK, "manual", None, None))

    def test_a_request_deadline_inside_the_grace_still_ends_with_the_grace(self):
        self.arrange("code", FAKE_LINK=LOOPBACK_LINK, FAKE_MANUAL=MANUAL_LINK,
                     FAKE_MANUAL_DELAY="3.0")
        runs = self.make(manual_grace=0.8, link_wait=0.4)
        runs.start("work")
        expected = (LOOPBACK_LINK, "loopback", 54321, LOOPBACK_FORWARD)
        self.assertEqual(route_of(runs.wait_link("work")), expected)
        self.assertEqual(route_of(runs.wait_link("work")), expected)

    def test_a_malformed_link_on_the_output_is_skipped_and_the_run_finishes(self):
        self.arrange("code", FAKE_LINK=LOOPBACK_LINK, FAKE_BAD=BAD_LINK,
                     FAKE_MANUAL=MANUAL_LINK)
        runs = self.make()
        with stderr_text() as captured:
            runs.start("work")
            link = runs.wait_link("work")
            runs.send_code("work", CODE)
            until(self, lambda: self.ends)
        self.assertEqual(route_of(link), (MANUAL_LINK, "manual", None, None))
        self.assertEqual(len(self.ends), 1)
        self.assertIn({"code": CODE}, self.lines())
        self.assertNotIn("SENTINEL", captured.text)

    def test_client_output_is_read_but_reaches_no_stderr_line(self):
        self.arrange("code", FAKE_LINK=LOOPBACK_LINK, FAKE_MANUAL=MANUAL_LINK,
                     FAKE_NOISE=NOISE_LINK)
        runs = self.make()
        with stderr_text() as captured:
            runs.start("work")
            link = runs.wait_link("work")
            runs.send_code("work", CODE)
            until(self, lambda: self.ends)
        self.assertEqual(route_of(link), (MANUAL_LINK, "manual", None, None))
        self.assertIn({"code": CODE}, self.lines())
        self.assertEqual(captured.text, "")
        self.assertNotIn("SENTINEL-OUT", repr(link))

    def test_a_missing_client_is_not_installed(self):
        root = self.arrange("code")
        empty = root / "empty"
        empty.mkdir()
        self.environ["PATH"] = str(empty)
        runs = self.make()
        before = {name for name in os.listdir(tempfile.gettempdir())
                  if name.startswith("console-login-")}
        with self.assertRaises(StartFailed) as raised:
            runs.start("work")
        self.assertEqual(raised.exception.kind, "not_installed")
        self.assertEqual(str(raised.exception), "not_installed")
        self.assertEqual(runs.running(), frozenset())
        after = {name for name in os.listdir(tempfile.gettempdir())
                 if name.startswith("console-login-")}
        self.assertEqual(after - before, set())

    def test_close_kills_every_run_and_reports_none(self):
        self.arrange("hang")
        runs = self.make()
        runs.start("work")
        runs.close()
        self.assertEqual(self.ends, [])
        self.assertEqual(runs.running(), frozenset())

    def test_runs_are_linux_and_macos_only(self):
        self.assertIs(runs_for("linux"), SignIns)
        self.assertIs(runs_for("darwin"), SignIns)
        self.assertIsNone(runs_for("win32"))


if __name__ == "__main__":
    unittest.main()
