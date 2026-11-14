"""The console capacity-reading verify check (#860): a console shows a fresh reading for an account.

Run: just agent-workflow-tests
"""
import json
import os
import socket
import sqlite3
import subprocess
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from agent_tools.console import capacity_check
from agent_tools.console.event_log import EventLog
from . import accounts_sandbox
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)

ROOT = Path(__file__).resolve().parents[1]
WRAPPER = "home/common/verify-pending/checks/console-capacity-reading"
ABSENT = object()


def serve(test, body, status=200):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    test.addCleanup(thread.join, 5)
    test.addCleanup(server.server_close)
    test.addCleanup(server.shutdown)
    return f"http://127.0.0.1:{server.server_address[1]}/api/state"


def ago(seconds):
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()


def view(*rows, asks=None, runs=None, added=None):
    """A console view; a row is `(name, read_at)` or `(name, read_at, signin)`.

    `asks` is None for a view with no `inbox`, else the keys of the open sign-in items; `runs` is
    the top-level `signin_runs` member, left out when None."""
    document = {"capacity": {"profiles": [
        {"profile": row[0], "read_at": row[1], **({"signin": row[2]} if len(row) > 2 else {})}
        for row in rows]}}
    if asks is not None:
        document["inbox"] = {"open": [{"reason": "signin", "key": key,
                                       "profile": key.split("/", 1)[1]} for key in asks]}
    if runs is not None:
        document["signin_runs"] = runs
    if added is not None:
        document["accounts_added"] = added
    return document


def serve_paths(test, answers):
    """A stub console: `answers` maps a path to `(status, body)`; any other path answers 404.

    Returns the `/api/state` URL."""
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            status, body = answers.get(self.path, (404, b""))
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    test.addCleanup(thread.join, 5)
    test.addCleanup(server.server_close)
    test.addCleanup(server.shutdown)
    return f"http://127.0.0.1:{server.server_address[1]}/api/state"


def excluded_view(*rows):
    """A console view whose rows are `(name, excluded)`."""
    return {"capacity": {"profiles": [{"profile": name, "read_at": None, "excluded": excluded}
                                      for name, excluded in rows]}}


class CapacityCheckTest(unittest.TestCase):
    def run_check(self, *args, env=None):
        done = subprocess.run([ROOT / WRAPPER, *args], cwd=ROOT, capture_output=True, text=True,
                              timeout=60, env={**os.environ, **(env or {})})
        return done.returncode, done.stdout

    def test_a_fresh_reading_is_met(self):
        url = serve(self, view(("home", ago(5000)), ("work", ago(60))))
        code, out = self.run_check("--url", url)
        document = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual(document["status"], "met")
        self.assertEqual(document["profile"], "work")
        self.assertIn(document["age_seconds"], range(59, 70))

    def test_a_stale_or_missing_reading_is_not_met(self):
        for rows in ([("work", ago(601))], [("work", None)], []):
            with self.subTest(rows=rows):
                code, out = self.run_check("--url", serve(self, view(*rows)))
                document = json.loads(out)
                self.assertEqual(code, 1)
                self.assertEqual(document["status"], "not_met")
                self.assertEqual(document["profiles"], [name for name, _ in rows])

    def test_the_age_limit_is_an_argument(self):
        url = serve(self, view(("work", ago(601))))
        code, out = self.run_check("--url", url, "--max-age", "700")
        self.assertEqual((code, json.loads(out)["status"]), (0, "met"))

    def test_a_console_that_is_down_or_old_is_not_yet(self):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            closed = probe.getsockname()[1]
        cases = [(f"http://127.0.0.1:{closed}/api/state", "not_running"),
                 (serve(self, {"statement": {}}), "not_deployed"),
                 (serve(self, b"not json"), "not_deployed"),
                 (serve(self, view(), status=500), "not_running")]
        for url, status in cases:
            with self.subTest(status=status, url=url):
                code, out = self.run_check("--url", url)
                self.assertEqual((code, json.loads(out)), (75, {"status": status}))

    def test_every_profile_fresh_is_met(self):
        url = serve(self, view(("work", ago(60)), ("spare", ago(800))))
        code, out = self.run_check("--url", url, "--every", "--max-age", "900")
        document = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual(document["status"], "met")
        self.assertEqual(document["profiles"], 2)
        self.assertIn(document["oldest_age_seconds"], range(799, 810))

    def test_a_profile_without_a_fresh_reading_is_not_yet_with_every(self):
        cases = [([("work", ago(60)), ("spare", None), ("old", ago(1000))], ["spare", "old"]),
                 ([], [])]
        for rows, names in cases:
            with self.subTest(rows=rows):
                code, out = self.run_check("--url", serve(self, view(*rows)), "--every",
                                           "--max-age", "900")
                self.assertEqual((code, json.loads(out)),
                                 (75, {"status": "pending", "profiles": names}))

    def test_every_skips_a_signed_out_profile(self):
        url = serve(self, view(("work", ago(60), {"state": "signed_in"}),
                               ("default", None, {"state": "signed_out"})))
        code, out = self.run_check("--url", url, "--every", "--max-age", "900")
        document = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual(document["status"], "met")
        self.assertEqual(document["profiles"], 1)
        self.assertEqual(document["signed_out"], ["default"])

    def test_every_still_waits_on_a_signed_in_profile_without_a_reading(self):
        signed_in, signed_out = {"state": "signed_in"}, {"state": "signed_out"}
        cases = [([("work", ago(60), signed_in), ("spare", None, signed_in),
                   ("default", None, signed_out)], ["spare"]),
                 ([("default", None, signed_out)], [])]
        for rows, names in cases:
            with self.subTest(rows=rows):
                code, out = self.run_check("--url", serve(self, view(*rows)), "--every",
                                           "--max-age", "900")
                self.assertEqual((code, json.loads(out)),
                                 (75, {"status": "pending", "profiles": names}))

    def test_signin_is_met_when_every_profile_knows_its_sign_in(self):
        url = serve(self, view(("work", ago(60), {"state": "signed_in"}),
                               ("default", None, {"state": "signed_out"})))
        code, out = self.run_check("--url", url, "--signin")
        self.assertEqual((code, json.loads(out)),
                         (0, {"status": "met", "profiles": 2, "signed_out": ["default"]}))

    def test_signin_is_pending_on_an_unknown_profile(self):
        cases = [([("work", ago(60), {"state": "signed_in"}),
                   ("spare", None, {"state": "unknown"})], ["spare"]),
                 ([], [])]
        for rows, names in cases:
            with self.subTest(rows=rows):
                code, out = self.run_check("--url", serve(self, view(*rows)), "--signin")
                self.assertEqual((code, json.loads(out)),
                                 (75, {"status": "pending", "profiles": names}))

    def test_signin_on_a_console_without_sign_in_is_not_deployed(self):
        url = serve(self, view(("work", ago(60)), ("spare", None)))
        code, out = self.run_check("--url", url, "--signin")
        self.assertEqual((code, json.loads(out)), (75, {"status": "not_deployed"}))

    def test_signin_and_every_together_are_refused(self):
        self.assertEqual(self.run_check("--every", "--signin")[0], 2)

    def test_accounts_is_met_with_named_profiles_only(self):
        url = serve(self, view(("spare", None), ("work", ago(60)), asks=["signin/spare"]))
        code, out = self.run_check("--url", url, "--accounts")
        self.assertEqual((code, json.loads(out)),
                         (0, {"status": "met", "profiles": ["spare", "work"]}))

    def test_accounts_is_not_met_on_a_default_row_or_its_sign_in_item(self):
        cases = [(view(("default", None), ("work", ago(60)), asks=[]),
                  {"status": "not_met", "default_row": True, "default_signin": False}),
                 (view(("work", ago(60)), asks=["signin/default"]),
                  {"status": "not_met", "default_row": False, "default_signin": True})]
        for document, expected in cases:
            with self.subTest(expected=expected):
                code, out = self.run_check("--url", serve(self, document), "--accounts")
                self.assertEqual((code, json.loads(out)), (1, expected))

    def test_accounts_on_an_empty_strip_is_not_yet(self):
        code, out = self.run_check("--url", serve(self, view(asks=[])), "--accounts")
        self.assertEqual((code, json.loads(out)), (75, {"status": "pending", "profiles": []}))

    def test_accounts_without_a_readable_inbox_is_not_yet(self):
        work = view(("work", ago(60)))
        cases = [work, {**work, "inbox": []}, {**work, "inbox": {}},
                 {**work, "inbox": {"open": {}}}, view(("default", None))]
        for document in cases:
            with self.subTest(document=document):
                code, out = self.run_check("--url", serve(self, document), "--accounts")
                self.assertEqual((code, json.loads(out)), (75, {"status": "no_inbox"}))

    def test_accounts_is_exclusive_with_every_and_signin(self):
        for other in ("--every", "--signin"):
            with self.subTest(other=other):
                done = subprocess.run([ROOT / WRAPPER, "--accounts", other], cwd=ROOT,
                                      capture_output=True, text=True, timeout=60)
                self.assertEqual(done.returncode, 2)
                self.assertIn("not allowed with argument", done.stderr)

    def exclusion(self, state, profile):
        url = serve_paths(self, {"/api/state": (200, state), "/api/profile": profile})
        code, out = self.run_check("--url", url, "--exclusion")
        return code, json.loads(out)

    def test_exclusion_is_met_when_the_choice_is_another_profile(self):
        state = excluded_view(("home", True), ("work", False))
        self.assertEqual(self.exclusion(state, (200, {"profile": "work"})),
                         (0, {"status": "met", "profile": "work", "excluded": ["home"]}))

    def test_exclusion_is_not_met_when_the_choice_is_excluded(self):
        state = excluded_view(("home", True), ("work", False))
        self.assertEqual(self.exclusion(state, (200, {"profile": "home"})),
                         (1, {"status": "not_met", "profile": "home", "excluded": ["home"]}))

    def test_exclusion_without_data_is_not_yet(self):
        none_excluded = excluded_view(("home", False), ("work", False))
        one_excluded = excluded_view(("home", True), ("work", False))
        no_flag = {"capacity": {"profiles": [{"profile": "home", "read_at": None}]}}
        cases = [
            (none_excluded, (200, {"profile": "work"}),
             {"status": "pending", "profile": "work", "excluded": []}),
            (one_excluded, (200, {"profile": None}),
             {"status": "pending", "profile": None, "excluded": ["home"]}),
            (no_flag, (200, {"profile": "work"}), {"status": "not_deployed"}),
            (excluded_view(("home", 1)), (200, {"profile": "work"}), {"status": "not_deployed"}),
            (one_excluded, (404, b""), {"status": "no_profile"}),
            (one_excluded, (200, {"chosen": "work"}), {"status": "no_profile"}),
            (one_excluded, (200, {"profile": 3}), {"status": "no_profile"}),
            (one_excluded, (200, b"not json"), {"status": "no_profile"}),
        ]
        for state, profile, expected in cases:
            with self.subTest(profile=profile, expected=expected):
                self.assertEqual(self.exclusion(state, profile), (75, expected))

    def test_exclusion_is_exclusive_with_the_other_modes(self):
        for other in ("--every", "--signin", "--accounts"):
            with self.subTest(other=other):
                done = subprocess.run([ROOT / WRAPPER, "--exclusion", other], cwd=ROOT,
                                      capture_output=True, text=True, timeout=60)
                self.assertEqual(done.returncode, 2)
                self.assertIn("not allowed with argument", done.stderr)

    def test_page_signin_is_met_when_a_page_signed_in_profile_has_no_open_item(self):
        url = serve(self, view(("work", ago(5)), asks=[],
                               runs={"work": {"state": "signed_in", "at": ago(60)}}))
        code, out = self.run_check("--url", url, "--page-signin")
        self.assertEqual((code, json.loads(out)), (0, {"status": "met", "profiles": ["work"]}))

    def test_page_signin_is_not_met_while_the_item_stays_open(self):
        url = serve(self, view(("work", ago(5)), asks=["signin/work"],
                               runs={"work": {"state": "signed_in", "at": ago(60)}}))
        code, out = self.run_check("--url", url, "--page-signin")
        self.assertEqual((code, json.loads(out)),
                         (1, {"status": "not_met", "profiles": ["work"]}))

    def test_page_signin_is_not_yet_without_a_page_sign_in(self):
        for runs in ({"work": {"state": "timed_out", "at": ago(60)}}, {}):
            with self.subTest(runs=runs):
                url = serve(self, view(("work", ago(5)), asks=[], runs=runs))
                code, out = self.run_check("--url", url, "--page-signin")
                self.assertEqual((code, json.loads(out)), (75, {"status": "pending"}))

    def test_page_signin_on_an_older_console_is_not_yet(self):
        cases = [(view(("work", ago(5)), asks=[]), "not_deployed"),
                 (view(("work", ago(5)), asks=[], runs=[]), "not_deployed"),
                 (view(("work", ago(5)), runs={"work": {"state": "signed_in"}}), "no_inbox")]
        for document, status in cases:
            with self.subTest(status=status):
                code, out = self.run_check("--url", serve(self, document), "--page-signin")
                self.assertEqual((code, json.loads(out)), (75, {"status": status}))

    def test_page_signin_is_exclusive_with_the_other_modes(self):
        for other in ("--every", "--signin", "--accounts"):
            with self.subTest(other=other):
                done = subprocess.run([ROOT / WRAPPER, "--page-signin", other], cwd=ROOT,
                                      capture_output=True, text=True, timeout=60)
                self.assertEqual(done.returncode, 2)
                self.assertIn("not allowed with argument", done.stderr)

    # `--page-add` (#1037) reads the console's event log, never the profiles. The rows below are
    # the ones the console recorded on anis-desktop on 2026-11-14 (events 80704 to 80729).
    ZZCHECK = [
        ("account.added", None, {"by": "owner", "profile": "zzcheck"}),
        ("signin.acted", None, {"action": "start", "by": "owner", "outcome": "started",
                                "profile": "zzcheck"}),
        ("signin.acted", None, {"action": "cancel", "by": "owner", "outcome": "cancelled",
                                "profile": "zzcheck"}),
        ("signin.ended", None, {"attempt": 2, "outcome": "cancelled", "profile": "zzcheck"}),
    ]

    def log_home(self, rows):
        """A temporary HOME whose console log holds `rows`; returns (home, log path)."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        home = Path(tmp.name)
        log = home / ".agents" / "state" / "console" / "events.sqlite3"
        EventLog(log).append(rows)
        return home, log

    def page_add(self, rows, *extra):
        home, log = self.log_home(rows)
        code, out = self.run_check("--page-add", *extra, env={"HOME": str(home)})
        return code, json.loads(out)

    def test_page_add_is_met_by_the_recorded_rows_with_no_profile_on_the_host(self):
        home, log = self.log_home(self.ZZCHECK)
        self.assertFalse((home / ".claude-accounts").exists())
        self.assertFalse((home / ".claude").exists())
        code, out = self.run_check("--page-add", env={"HOME": str(home),
                                                      "CLAUDE_ACCOUNTS_DIR": str(home / "none")})
        self.assertEqual((code, json.loads(out)), (0, {"profiles": ["zzcheck"], "status": "met"}))

    def test_page_add_is_met_by_the_log_option_and_needs_no_console(self):
        home, log = self.log_home(self.ZZCHECK)
        code, out = self.run_check("--page-add", "--log", str(log),
                                   "--url", "http://127.0.0.1:1/api/state",
                                   env={"HOME": str(home / "elsewhere")})
        self.assertEqual((code, json.loads(out)), (0, {"profiles": ["zzcheck"], "status": "met"}))

    def test_page_add_lists_every_added_profile_with_a_start_after_its_add(self):
        rows = [*self.ZZCHECK,
                ("account.added", None, {"by": "owner", "profile": "alpha"}),
                ("account.added", None, {"by": "owner", "profile": "late"}),
                ("signin.acted", None, {"action": "start", "by": "owner",
                                        "outcome": "started", "profile": "alpha"})]
        self.assertEqual(self.page_add(rows),
                         (0, {"profiles": ["alpha", "zzcheck"], "status": "met"}))

    def test_page_add_is_not_yet_without_an_add_followed_by_a_page_sign_in_start(self):
        added = ("account.added", None, {"by": "owner", "profile": "p"})

        def start(**changes):
            payload = {"action": "start", "by": "owner", "outcome": "started", "profile": "p"}
            return ("signin.acted", None, {**payload, **changes})

        cases = {
            "empty log": [],
            "add only": [added],
            "start before the add": [start(), added],
            "start of another profile": [added, start(profile="q")],
            "start that failed": [added, start(outcome="failed")],
            "start joining a running one": [added, start(outcome="running")],
            "start by someone else": [added, start(by="manager")],
            "code instead of start": [added, start(action="code", outcome="sent")],
            "cancel only": [added, start(action="cancel", outcome="cancelled")],
            "start without an add": [start()],
            "add by someone else": [("account.added", None, {"by": "manager", "profile": "p"}),
                                    start()],
            "add with no profile": [("account.added", None, {"by": "owner"}), start()],
            "add with a non-string profile": [("account.added", None, {"by": "owner",
                                                                       "profile": 3}),
                                              start(profile=3)],
            "other kinds only": [("goal.stated", None, {"profile": "p"})],
        }
        for label, rows in cases.items():
            with self.subTest(label=label):
                self.assertEqual(self.page_add(rows), (75, {"status": "pending"}))

    def test_page_add_is_not_yet_without_a_readable_log(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "junk").write_text("not a database")
        empty = sqlite3.connect(root / "empty.sqlite3")
        empty.execute("CREATE TABLE other (x)")
        empty.commit()
        empty.close()
        for name in ("missing", "junk", "empty.sqlite3"):
            with self.subTest(name=name):
                code, out = self.run_check("--page-add", "--log", str(root / name),
                                           env={"HOME": str(root)})
                self.assertEqual((code, json.loads(out)), (75, {"status": "no_log"}))
        self.assertEqual(sorted(path.name for path in root.iterdir()),
                         ["empty.sqlite3", "junk"])

    def test_page_add_reads_the_log_without_writing_anything(self):
        home, log = self.log_home(self.ZZCHECK)
        directory = log.parent
        before_bytes = log.read_bytes()
        before_files = sorted(path.name for path in directory.iterdir())
        os.chmod(log, 0o400)
        os.chmod(directory, 0o500)
        self.addCleanup(os.chmod, directory, 0o700)
        code, out = self.run_check("--page-add", env={"HOME": str(home)})
        self.assertEqual((code, json.loads(out)["status"]), (0, "met"))
        os.chmod(directory, 0o700)
        self.assertEqual(log.read_bytes(), before_bytes)
        self.assertEqual(sorted(path.name for path in directory.iterdir()), before_files)

    def test_page_add_leaves_the_accounts_directory_untouched(self):
        home, log = self.log_home(self.ZZCHECK)
        accounts = home / "accounts"
        before = accounts_sandbox.accounts_snapshot(accounts)
        self.run_check("--page-add", env={"HOME": str(home), "CLAUDE_ACCOUNTS_DIR": str(accounts)})
        self.assertEqual(accounts_sandbox.accounts_snapshot(accounts), before)
        self.assertFalse(accounts.exists())

    def test_the_shared_entries_are_the_launchers(self):
        text = (ROOT / "home/common/claude-code/accounts/bin/claude-account").read_text()
        listed = text.split("SHARED=(", 1)[1].split(")", 1)[0]
        self.assertEqual(tuple(listed.split()), capacity_check.SHARED)

    def test_page_add_is_exclusive_with_the_other_modes(self):
        for other in ("--every", "--signin", "--accounts", "--page-signin"):
            with self.subTest(other=other):
                done = subprocess.run([ROOT / WRAPPER, "--page-add", other], cwd=ROOT,
                                      capture_output=True, text=True, timeout=60)
                self.assertEqual(done.returncode, 2)
                self.assertIn("not allowed with argument", done.stderr)

    def pin_check(self, view):
        url = serve_paths(self, {"/api/state": (200, view)})
        code, out = self.run_check("--url", url, "--pin")
        return code, json.loads(out)

    def pin_view(self, launches=ABSENT, pin=None):
        document = {"capacity": {"profiles": []}, "pin": pin}
        if launches is not ABSENT:
            document["pin_launches"] = launches
        return document

    def test_pin_is_met_by_a_launch_under_the_pin_even_with_no_pin_in_force(self):
        self.assertEqual(self.pin_check(self.pin_view(["work", "home"], pin=None)),
                         (0, {"status": "met", "profiles": ["home", "work"]}))
        lapsed = {"profile": "work", "in_effect": False, "reason": "out of allowance",
                  "until": None, "instead": "home"}
        self.assertEqual(self.pin_check(self.pin_view(["home"], pin=lapsed)),
                         (0, {"status": "met", "profiles": ["home"]}))

    def test_pin_without_a_launch_under_the_pin_is_not_yet(self):
        pending = (75, {"status": "pending", "profiles": []})
        self.assertEqual(self.pin_check(self.pin_view([])), pending)
        held = {"profile": "home", "in_effect": True, "reason": None, "until": None,
                "instead": None}
        self.assertEqual(self.pin_check(self.pin_view([], pin=held)), pending)

    def test_pin_on_a_console_without_the_member_is_not_deployed(self):
        for name, view in (("absent", self.pin_view()), ("string", self.pin_view("home")),
                           ("non-string member", self.pin_view(["home", 1])),
                           ("null", self.pin_view(None))):
            with self.subTest(name=name):
                self.assertEqual(self.pin_check(view), (75, {"status": "not_deployed"}))

    def test_pin_is_exclusive_with_the_other_modes(self):
        for other in ("--every", "--signin", "--accounts", "--exclusion", "--page-signin",
                      "--page-add"):
            with self.subTest(other=other):
                done = subprocess.run([ROOT / WRAPPER, "--pin", other], cwd=ROOT,
                                      capture_output=True, text=True, timeout=60)
                self.assertEqual(done.returncode, 2)
                self.assertIn("not allowed with argument", done.stderr)

    REMOVED = [
        ("account.added", None, {"by": "owner", "profile": "zzgone"}),
        ("account.removal", None, {"by": "owner", "profile": "zzgone", "outcome": "removed",
                                   "kind": "removed"}),
    ]

    def page_remove(self, rows, document=None, *, directories=(), url=None):
        """Run `--page-remove` over a log of `rows`, a stub console and a profiles directory
        holding `directories`; returns (exit code, parsed output)."""
        home, log = self.log_home(rows)
        accounts = home / "accounts"
        for name in directories:
            (accounts / "profiles" / name).mkdir(parents=True)
        if url is None:
            url = serve(self, document if document is not None else view(("work", ago(5))))
        code, out = self.run_check("--page-remove", "--url", url,
                                   env={"HOME": str(home), "CLAUDE_ACCOUNTS_DIR": str(accounts)})
        return code, json.loads(out)

    def test_page_remove_is_met_when_an_added_profile_was_removed_and_is_gone(self):
        self.assertEqual(self.page_remove(self.REMOVED),
                         (0, {"profiles": ["zzgone"], "status": "met"}))

    def test_page_remove_reads_a_removal_of_an_already_signed_out_profile(self):
        rows = [self.REMOVED[0],
                ("account.removal", None, {"by": "owner", "profile": "zzgone",
                                           "outcome": "removed_signed_out_already",
                                           "kind": "removed"})]
        self.assertEqual(self.page_remove(rows), (0, {"profiles": ["zzgone"], "status": "met"}))

    def test_page_remove_is_not_met_while_the_directory_or_the_row_stays(self):
        not_met = (1, {"profiles": ["zzgone"], "status": "not_met"})
        with self.subTest(case="directory"):
            self.assertEqual(self.page_remove(self.REMOVED, directories=["zzgone"]), not_met)
        with self.subTest(case="row"):
            listed = view(("work", ago(5)), ("zzgone", ago(5)))
            self.assertEqual(self.page_remove(self.REMOVED, listed), not_met)

    def test_page_remove_is_not_yet_without_an_owner_add_then_removal(self):
        added = self.REMOVED[0]

        def removal(**changes):
            payload = {"by": "owner", "profile": "zzgone", "outcome": "removed",
                       "kind": "removed", **changes}
            return ("account.removal", None, payload)

        cases = {
            "no rows": [],
            "removal without an add": [removal()],
            "removal that failed to sign out": [added, removal(outcome="signout_failed")],
            "add after the removal": [added, removal(), added],
            "removal by someone else": [added, removal(by="manager")],
            "removal of another profile": [added, removal(profile="other")],
        }
        for label, rows in cases.items():
            with self.subTest(label=label):
                self.assertEqual(self.page_remove(rows), (75, {"status": "pending"}))

    def test_page_remove_is_not_yet_without_a_log_or_a_console(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        code, out = self.run_check("--page-remove", "--url", serve(self, view(("work", ago(5)))),
                                   env={"HOME": tmp.name})
        self.assertEqual((code, json.loads(out)), (75, {"status": "no_log"}))
        self.assertEqual(self.page_remove(self.REMOVED, url="http://127.0.0.1:1/api/state"),
                         (75, {"status": "not_running"}))
        self.assertEqual(self.page_remove(self.REMOVED, {"other": 1}),
                         (75, {"status": "not_deployed"}))

    def test_page_remove_reads_the_log_without_writing_anything(self):
        home, log = self.log_home(self.REMOVED)
        directory = log.parent
        before_bytes = log.read_bytes()
        before_mtime = log.stat().st_mtime_ns
        before_files = sorted(path.name for path in directory.iterdir())
        os.chmod(log, 0o400)
        os.chmod(directory, 0o500)
        self.addCleanup(os.chmod, directory, 0o700)
        code, out = self.run_check("--page-remove", "--url", serve(self, view(("work", ago(5)))),
                                   env={"HOME": str(home),
                                        "CLAUDE_ACCOUNTS_DIR": str(home / "accounts")})
        self.assertEqual((code, json.loads(out)["status"]), (0, "met"))
        os.chmod(directory, 0o700)
        self.assertEqual(log.read_bytes(), before_bytes)
        self.assertEqual(log.stat().st_mtime_ns, before_mtime)
        self.assertEqual(sorted(path.name for path in directory.iterdir()), before_files)
        self.assertFalse((home / "accounts").exists())

    def test_page_remove_is_exclusive_with_the_other_modes(self):
        for other in ("--pin", "--page-add", "--every"):
            with self.subTest(other=other):
                done = subprocess.run([ROOT / WRAPPER, "--page-remove", other], cwd=ROOT,
                                      capture_output=True, text=True, timeout=60)
                self.assertEqual(done.returncode, 2)
                self.assertIn("not allowed with argument", done.stderr)

    def test_without_every_one_fresh_profile_still_meets(self):
        url = serve(self, view(("work", ago(60)), ("spare", None)))
        code, out = self.run_check("--url", url)
        document = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual(document["status"], "met")
        self.assertEqual(document["profile"], "work")

    def test_the_wrapper_is_committed_executable(self):
        listed = subprocess.run(["git", "ls-files", "-s", WRAPPER], cwd=ROOT,
                                capture_output=True, text=True, check=True).stdout
        self.assertTrue(listed.startswith("100755"), listed)

    def test_an_off_loopback_url_is_refused(self):
        for url in ("http://example.test/api/state", "https://127.0.0.1/api/state"):
            with self.subTest(url=url):
                self.assertEqual(self.run_check("--url", url)[0], 2)

    def test_a_bad_max_age_is_refused(self):
        for value in ("0", "-5", "x"):
            with self.subTest(value=value):
                self.assertEqual(self.run_check("--max-age", value)[0], 2)


if __name__ == "__main__":
    unittest.main()
