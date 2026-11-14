"""The console's add-account write (#1027): the guard, the refusals, the row, the launcher's profile, the sign-in.

Run: just agent-workflow-tests
"""
import contextlib
import io
import json
import os
import shutil
import stat
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path

from agent_tools.console import account_add, signin, signin_run

from . import console_test_support as support
from .test_console_signin_run import CODE, FAKE, LINK, until
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)

ADD = "/api/account-add"
SIGNIN_CODE = "/api/signin-code"
SIGNIN_CANCEL = "/api/signin-cancel"
NOW = 1794000000
ROOT = Path(__file__).resolve().parent.parent
ACCOUNTS_MODULE = ROOT / "home/common/claude-code/accounts"
BAD_NAME = b"not an account name: use a-z, 0-9, - and _\n"
UNAVAILABLE = b"adding an account is not available on this host\n"


class Listing:
    def __init__(self, profiles):
        self.profiles = profiles

    def __iter__(self):
        return iter(sorted(p for p in self.profiles.glob("*") if p.is_dir()))


class Case(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.store = self.root / "state/console/events.sqlite3"
        self.registry = self.root / "state/fleet/registry.json"
        self.token_file = self.store.parent / "page-token"
        support.write_registry(self.registry, [])
        self.accounts = self.store.parent.parent / "accounts"
        self.profiles = self.accounts / "profiles"
        support.profile_dir(self.store, "work")
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        script = bin_dir / "claude-account"
        script.write_text(FAKE % {"python": sys.executable})
        script.chmod(0o755)
        self.environ = {"HOME": str(self.root), "PATH": f"{bin_dir}:/usr/bin:/bin",
                        "FAKE_RECORD": str(self.root / "record.jsonl"), "FAKE_MODE": "code",
                        "FAKE_LINK": LINK}
        self.now = [NOW]
        self.mono = [1000.0]
        self.read_error = {}
        self.reads = []
        self.added = []

    def read(self, one):
        self.reads.append(one.profile)
        if one.profile in self.read_error:
            raise self.read_error[one.profile]
        return signin.Status("signed_out", None)

    def adder(self, name):
        self.added.append(name)
        (self.profiles / name).mkdir(mode=0o700)

    def begin(self, adder="default", runs=True, reader=True):
        def factory(on_end):
            return signin_run.SignIns(on_end=on_end, environ=self.environ,
                                      clock=lambda: self.mono[0], link_wait=5)
        self.svc = support.service(
            self, self.store, self.registry, profile_dirs=Listing(self.profiles),
            clock=lambda: self.now[0],
            log_clock=lambda: datetime.fromtimestamp(self.now[0], timezone.utc).isoformat(
                timespec="microseconds"),
            session_poll_seconds=3600, probe_tick_seconds=3600,
            probe_dispatch=lambda job: job(), signin_reader=self.read if reader else None,
            signin_runs=factory if runs else None,
            account_adder=self.adder if adder == "default" else adder)
        self.svc.poll_sessions()
        return self.svc

    def own(self, **headers):
        return {"Origin": f"http://127.0.0.1:{self.svc.address[1]}",
                "X-Console-Token": self.token_file.read_text().strip(), **headers}

    def post(self, body=None, headers=None, raw=None, path=ADD):
        payload = json.dumps(body).encode() if raw is None else raw
        sent = self.own(**{"Content-Type": "application/json"}) if headers is None else headers
        return support.post_page(self.svc.address, path, sent, payload)

    def rows(self, kind):
        return [(row[0], json.loads(row[4])) for row in support.log_rows(self.store)
                if row[2] == kind]

    def view(self):
        return json.loads(self.svc.view_bytes)

    def start_attempt(self, name):
        starts = [seq for seq, payload in self.rows("signin.acted")
                  if payload["profile"] == name and payload["action"] == "start"]
        self.assertEqual(len(starts), 1)
        return starts[0]

    def names(self):
        return {p.name for p in self.profiles.glob("*")}


class AccountWriteTest(Case):
    def test_the_add_route_is_refused_without_the_origin_or_the_token(self):
        self.begin()
        before = support.log_rows(self.store)
        json_type = {"Content-Type": "application/json"}
        own = f"http://127.0.0.1:{self.svc.address[1]}"
        for headers, text in (
                (json_type, b"origin refused\n"),
                ({"Origin": own, **json_type}, b"token refused\n"),
                (self.own(**{**json_type, "Origin": "http://evil.test"}), b"origin refused\n")):
            with self.subTest(text=text):
                status, _, body = self.post({"name": "fresh"}, headers=headers)
                self.assertEqual((status, body), (403, text))
        self.assertEqual(support.log_rows(self.store), before)
        self.assertEqual(self.added, [])
        self.assertFalse((self.profiles / "fresh").exists())

    def test_an_invalid_default_or_existing_name_is_refused_and_creates_nothing(self):
        self.begin()
        before = support.log_rows(self.store)
        for name, text in (("Work", BAD_NAME), ("", BAD_NAME), ("../x", BAD_NAME),
                           ("a.b", BAD_NAME), ("default", b"default is not an account name\n"),
                           ("work", b"account work already exists\n")):
            with self.subTest(name=name):
                status, _, body = self.post({"name": name})
                self.assertEqual((status, body), (409, text))
        self.assertEqual(support.log_rows(self.store), before)
        self.assertEqual(self.added, [])
        self.assertEqual(self.names(), {"work"})
        self.assertFalse((self.root / "record.jsonl").exists())

    def test_bodies_are_refused_as_bad_account(self):
        self.begin()
        before = support.log_rows(self.store)
        for raw in (b"{}", b'{"name":1}', b'{"name":"a","x":1}'):
            with self.subTest(raw=raw):
                status, _, body = self.post(raw=raw)
                self.assertEqual((status, body), (400, b"bad account\n"))
        status, _, body = self.post({"name": "a"}, headers=self.own(**{"Content-Type": "text/plain"}))
        self.assertEqual((status, body), (415, b"json only\n"))
        status, _, body = self.post(raw=b"x" * 4097)
        self.assertEqual((status, body), (413, b"too large\n"))
        self.assertEqual(support.log_rows(self.store), before)
        self.assertEqual(self.added, [])

    def test_an_accepted_add_appends_one_owner_action_row_naming_the_profile(self):
        self.begin()
        status, _, _ = self.post({"name": "fresh"})
        self.assertEqual(status, 200)
        self.assertEqual([p for _, p in self.rows("account.added")],
                         [{"by": "owner", "profile": "fresh"}])
        self.assertEqual(self.added, ["fresh"])
        self.assertEqual([p for _, p in self.rows("signin.acted")],
                         [{"by": "owner", "profile": "fresh", "action": "start",
                           "outcome": "started"}])

    def test_without_the_seams_the_host_refuses(self):
        for label, make in (("adder", lambda: self.begin(adder=None)),
                            ("runs", lambda: self.begin(runs=False)),
                            ("reader", lambda: self.begin(reader=False))):
            with self.subTest(label=label):
                make()
                before = support.log_rows(self.store)
                status, _, body = self.post({"name": "fresh"})
                self.assertEqual((status, body), (409, UNAVAILABLE))
                self.assertEqual(self.names(), {"work"})
                self.assertEqual(support.log_rows(self.store), before)
                self.assertEqual(self.added, [])
                self.svc.close()

    def test_a_launcher_failure_answers_502_and_appends_nothing(self):
        def failing(name):
            raise account_add.AddFailed("failed")
        self.begin(adder=failing)
        before = support.log_rows(self.store)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            status, _, body = self.post({"name": "fresh"})
        self.assertEqual((status, body), (502, b"the account could not be created: failed\n"))
        self.assertEqual(err.getvalue(), "console: account_add_failed fresh failed\n")
        self.assertEqual(support.log_rows(self.store), before)

    def test_a_profile_the_listing_does_not_show_is_not_listed(self):
        self.begin(adder=self.added.append)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            status, _, body = self.post({"name": "fresh"})
        self.assertEqual((status, body), (502, b"the account could not be created: not_listed\n"))
        self.assertEqual(self.rows("account.added"), [])
        self.assertFalse((self.root / "record.jsonl").exists())

    def test_two_adds_of_one_name_create_it_once(self):
        entered = threading.Event()
        gate = threading.Event()

        def slow(name):
            self.added.append(name)
            entered.set()
            gate.wait(10)
            (self.profiles / name).mkdir(mode=0o700)
        self.begin(adder=slow)
        answers = []

        def go():
            answers.append(self.post({"name": "fresh"}))
        first = threading.Thread(target=go)
        first.start()
        self.assertTrue(entered.wait(10))
        second = threading.Thread(target=go)
        second.start()
        second.join(0.2)
        gate.set()
        first.join(10)
        second.join(10)
        self.assertEqual(sorted(status for status, _, _ in answers), [200, 409])
        self.assertEqual([body for status, _, body in answers if status == 409],
                         [b"account fresh already exists\n"])
        self.assertEqual(self.added, ["fresh"])


class AccountSigninTest(Case):
    def test_an_add_answers_the_sign_in_link_and_opens_the_sign_in_item(self):
        self.begin()
        status, headers, body = self.post({"name": "fresh"})
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "application/json")
        self.assertEqual(headers["Cache-Control"], "no-store")
        attempt = self.start_attempt("fresh")
        self.assertEqual(json.loads(body), {"attempt": attempt, "link": LINK, "profile": "fresh"})
        self.assertIn("fresh", self.reads)
        view = self.view()
        self.assertIn("signin/fresh", [item["key"] for item in view["inbox"]["open"]])
        self.assertEqual(view["signin_runs"]["fresh"],
                         {"state": "running", "at": None, "attempt": attempt})

    def test_the_view_lists_an_added_account_after_a_restart(self):
        self.begin()
        status, _, _ = self.post({"name": "fresh"})
        self.assertEqual(status, 200)
        self.assertEqual(self.view()["accounts_added"], ["fresh"])
        self.svc.close()
        self.begin()
        self.assertEqual(self.view()["accounts_added"], ["fresh"])

    def test_retention_drops_an_expired_added_account_as_a_restart_does(self):
        svc = self.begin()
        status, _, _ = self.post({"name": "fresh"})
        self.assertEqual(status, 200)
        self.assertEqual(self.view()["accounts_added"], ["fresh"])
        self.now[0] += 91 * 86400
        self.assertGreaterEqual(svc.retain(), 1)
        self.assertEqual(self.view()["accounts_added"], [])
        svc.close()
        self.begin()
        self.assertEqual(self.view()["accounts_added"], [])

    def test_a_failed_status_read_still_starts_a_sign_in_the_page_can_finish(self):
        self.read_error = {"fresh": signin.StatusFailed("timeout")}
        self.begin()
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            status, _, body = self.post({"name": "fresh"})
        self.assertEqual(status, 200)
        attempt = self.start_attempt("fresh")
        self.assertEqual(json.loads(body), {"attempt": attempt, "link": LINK, "profile": "fresh"})
        self.assertIn("console: signin_add_read_failed fresh timeout\n", err.getvalue())
        self.assertEqual([p for _, p in self.rows("signin.reading") if p["profile"] == "fresh"], [])
        view = self.view()
        row = next(r for r in view["capacity"]["profiles"] if r["profile"] == "fresh")
        self.assertEqual(row["signin"]["state"], "unknown")
        self.assertIs(row["signin"]["ask"], False)
        self.assertNotIn("signin/fresh", [item["key"] for item in view["inbox"]["open"]])
        self.assertEqual(view["signin_runs"]["fresh"],
                         {"state": "running", "at": None, "attempt": attempt})
        status, _, body = self.post({"profile": "fresh", "code": CODE}, path=SIGNIN_CODE)
        self.assertEqual((status, body), (204, b""))
        self.assertIn({"by": "owner", "profile": "fresh", "action": "code", "outcome": "sent"},
                      [p for _, p in self.rows("signin.acted")])

    def test_a_sign_in_that_cannot_start_keeps_the_added_profile(self):
        self.environ["PATH"] = "/usr/bin:/bin"
        self.begin()
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            status, _, body = self.post({"name": "fresh"})
        self.assertEqual(
            (status, body),
            (502, b"the account was added; its sign-in could not start: not_installed\n"))
        self.assertEqual(err.getvalue(), "console: signin_start_failed fresh not_installed\n")
        self.assertEqual(len(self.rows("account.added")), 1)
        self.assertEqual([p["outcome"] for _, p in self.rows("signin.acted")], ["failed"])
        self.assertTrue((self.profiles / "fresh").exists())

    def test_a_cancelled_sign_in_leaves_the_profile_signed_out_with_its_item(self):
        self.environ["FAKE_MODE"] = "hang"
        self.begin()
        status, _, _ = self.post({"name": "fresh"})
        self.assertEqual(status, 200)
        status, _, _ = self.post({"profile": "fresh"}, path=SIGNIN_CANCEL)
        self.assertEqual(status, 204)
        until(self, lambda: self.view()["signin_runs"]["fresh"]["state"] == "cancelled")
        self.assertTrue((self.profiles / "fresh").exists())
        items = {item["key"]: item for item in self.view()["inbox"]["open"]}
        self.assertIn("signin/fresh", items)
        self.assertEqual(items["signin/fresh"]["signin"]["state"], "signed_out")

    def test_the_link_is_in_no_row_or_stderr_line(self):
        self.begin()
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            status, _, _ = self.post({"name": "fresh"})
        self.assertEqual(status, 200)
        for row in support.log_rows(self.store):
            self.assertNotIn(LINK, json.dumps(row))
        self.assertNotIn(LINK, err.getvalue())
        self.assertNotIn(LINK, self.svc.view_bytes.decode())


class AccountProfileTest(Case):
    def test_an_added_profile_is_the_one_the_launchers_add_makes(self):
        home = self.root / "home"
        claude = home / ".claude"
        claude.mkdir(parents=True)
        (self.root / "store").mkdir()
        (self.root / "store/settings.json").write_text("{}")
        (claude / "settings.json").symlink_to(self.root / "store/settings.json")
        (claude / "CLAUDE.md").write_text("guidance")
        (claude / "skills").mkdir()
        (claude / "plugins").mkdir()
        (home / ".claude.json").write_text(json.dumps(
            {"oauthAccount": {"emailAddress": "o@example.test"}, "hasCompletedOnboarding": True,
             "projects": {}}))
        jq = shutil.which("jq")
        if jq is None:
            self.fail("jq is not on PATH; the launcher's .claude.json copy needs it")
        module = self.root / "mod"
        shutil.copytree(ACCOUNTS_MODULE, module)
        launcher = module / "bin/claude-account"
        text = launcher.read_text()
        self.assertEqual(text.count("\nJQ=jq\n"), 1)
        launcher.write_text(text.replace("\nJQ=jq\n", f"\nJQ={jq}\n"))
        launch_env = {"HOME": str(home), "CLAUDE_ACCOUNTS_DIR": str(self.accounts),
                      "PATH": os.environ["PATH"]}
        import subprocess
        done = subprocess.run([shutil.which("bash"), str(launcher), "add", "solo"],
                              env=launch_env, capture_output=True, check=False)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.begin(adder=account_add.Adder(command=[shutil.which("bash"), str(launcher)],
                                           environ=launch_env))
        status, _, _ = self.post({"name": "twin"})
        self.assertEqual(status, 200)
        a = self.profiles / "solo"
        b = self.profiles / "twin"
        self.assertEqual(stat.S_IMODE(os.stat(b).st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(os.stat(a).st_mode), 0o700)
        self.assertEqual(sorted(os.listdir(b)), sorted(os.listdir(a)))
        for entry in os.listdir(a):
            if (a / entry).is_symlink():
                self.assertTrue((b / entry).is_symlink(), entry)
                self.assertEqual(os.readlink(b / entry), os.readlink(a / entry))
                self.assertEqual(os.readlink(a / entry), str(claude / entry))
        copied = json.loads((b / ".claude.json").read_text())
        self.assertEqual(copied, json.loads((a / ".claude.json").read_text()))
        self.assertNotIn("oauthAccount", copied)
        for one in (a, b):
            self.assertEqual(stat.S_IMODE(os.stat(one / ".claude.json").st_mode), 0o600)


if __name__ == "__main__":
    unittest.main()
