"""The console's remove-account write (#1030): the guard, the refusals, the mark, the sign-out first, the rows, the effects.

Run: just agent-workflow-tests
"""
import contextlib
import io
import json
import os
import shutil
import tempfile
import threading
import time
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from agent_tools.console import account_remove, probe, signin, signin_run, sprints
from agent_tools.console.event_log import EventLog

from . import console_test_support as support
from .test_console_account_service import Listing
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)

REMOVE = "/api/account-remove"
NOW = 1794000000
LONG = "a" * 129


class Case(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.store = self.root / "state/console/events.sqlite3"
        self.registry = self.root / "state/fleet/registry.json"
        self.token_file = self.store.parent / "page-token"
        support.write_registry(self.registry, [])
        self.profiles = self.store.parent.parent / "accounts" / "profiles"
        support.profile_dir(self.store, "work")
        support.profile_dir(self.store, "home")
        self.choice_file = self.profiles.parent / "chosen-profile"
        self.now = [NOW]
        self.calls = []
        self.during = []
        self.signout_error = None
        self.status = signin.Status("signed_in", None)
        self.read_gate = {}
        self.read_error = None

    def signer_out(self, one):
        self.calls.append(("signout", one.profile))
        for each in list(self.during):
            each()
        if self.signout_error is not None:
            raise self.signout_error

    def remover(self, name):
        self.calls.append(("rm", name))
        shutil.rmtree(self.profiles / name)

    def reader(self, one):
        self.calls.append(("read", one.profile))
        gate = self.read_gate.get(one.profile)
        if gate is not None:
            gate.wait(10)
        if self.read_error is not None:
            raise self.read_error
        return self.status

    def begin(self, signer_out="default", remover="default", reader="default", runs=None,
              probe_dispatch=lambda job: job(), seed=()):
        if seed:
            self.store.parent.mkdir(parents=True, exist_ok=True)
            log = EventLog(self.store)
            try:
                log.append(list(seed))
            finally:
                log.close()
        self.svc = support.service(
            self, self.store, self.registry, profile_dirs=Listing(self.profiles),
            clock=lambda: self.now[0],
            log_clock=lambda: datetime.fromtimestamp(self.now[0], timezone.utc).isoformat(
                timespec="microseconds"),
            session_poll_seconds=3600, probe_tick_seconds=3600, probe_dispatch=probe_dispatch,
            signin_reader=self.reader if reader == "default" else reader,
            signin_runs=runs,
            signer_out=self.signer_out if signer_out == "default" else signer_out,
            account_remover=self.remover if remover == "default" else remover,
            choice_file=self.choice_file)
        self.svc.poll_sessions()
        return self.svc

    def own(self, **headers):
        return {"Origin": f"http://127.0.0.1:{self.svc.address[1]}",
                "X-Console-Token": self.token_file.read_text().strip(), **headers}

    def post(self, body=None, headers=None, raw=None):
        payload = json.dumps(body).encode() if raw is None else raw
        sent = self.own(**{"Content-Type": "application/json"}) if headers is None else headers
        return support.post_page(self.svc.address, REMOVE, sent, payload)

    def remove(self, name="work"):
        return self.post({"profile": name, "typed": name})

    def rows(self, kind):
        return [(row[0], json.loads(row[4])) for row in support.log_rows(self.store)
                if row[2] == kind]

    def view(self):
        return json.loads(self.svc.view_bytes)

    def ask(self):
        return support.request(self.svc.address, "GET", "/api/profile")[2]


class RemoveWriteTest(Case):
    def test_the_removal_route_is_refused_without_the_origin_or_the_token(self):
        self.begin()
        before = support.log_rows(self.store)
        json_type = {"Content-Type": "application/json"}
        own = f"http://127.0.0.1:{self.svc.address[1]}"
        for headers, text in (
                (json_type, b"origin refused\n"),
                ({"Origin": own, **json_type}, b"token refused\n"),
                (self.own(**{**json_type, "Origin": "http://evil.test"}), b"origin refused\n")):
            with self.subTest(text=text):
                status, _, body = self.post({"profile": "work", "typed": "work"}, headers=headers)
                self.assertEqual((status, body), (403, text))
        self.assertEqual(support.log_rows(self.store), before)
        self.assertEqual(self.calls, [])
        self.assertTrue((self.profiles / "work").is_dir())

    def test_a_typed_name_that_does_not_match_is_refused_and_removes_nothing(self):
        self.begin()
        before = support.log_rows(self.store)
        for typed in ("", "Work", "home", "work "):
            with self.subTest(typed=typed):
                err = io.StringIO()
                with contextlib.redirect_stderr(err):
                    status, _, body = self.post({"profile": "work", "typed": typed})
                self.assertEqual((status, body), (409, b"the typed name does not match\n"))
                self.assertEqual(
                    err.getvalue(), "console: account_remove_refused the typed name does not match\n")
        self.assertEqual(support.log_rows(self.store), before)
        self.assertEqual(self.calls, [])
        self.assertTrue((self.profiles / "work").is_dir())

    def test_an_unknown_or_default_profile_is_refused(self):
        self.begin()
        before = support.log_rows(self.store)
        for name in ("default", "gone"):
            with self.subTest(name=name):
                status, _, body = self.remove(name)
                self.assertEqual((status, body), (409, b"no such profile\n"))
        self.assertEqual(support.log_rows(self.store), before)
        self.assertEqual(self.calls, [])

    def test_bodies_are_refused_as_bad_removal(self):
        self.begin()
        before = support.log_rows(self.store)
        for raw in (b"{}", b'{"profile":"work"}', b'{"profile":"work","typed":1}'):
            with self.subTest(raw=raw):
                status, _, body = self.post(raw=raw)
                self.assertEqual((status, body), (400, b"bad removal\n"))
        status, _, body = self.post(
            {"profile": "work", "typed": "work"}, headers=self.own(**{"Content-Type": "text/plain"}))
        self.assertEqual((status, body), (415, b"json only\n"))
        status, _, body = self.post(raw=b"x" * 4097)
        self.assertEqual((status, body), (413, b"too large\n"))
        self.assertEqual(support.log_rows(self.store), before)
        self.assertEqual(self.calls, [])

    def test_without_the_seams_the_host_refuses(self):
        for label, make in (("signer_out", lambda: self.begin(signer_out=None)),
                            ("remover", lambda: self.begin(remover=None)),
                            ("reader", lambda: self.begin(reader=None))):
            with self.subTest(label=label):
                make()
                before = support.log_rows(self.store)
                status, _, body = self.remove()
                self.assertEqual(
                    (status, body), (409, b"removing an account is not available on this host\n"))
                self.assertEqual(support.log_rows(self.store), before)
                self.assertEqual(self.calls, [])
                self.assertTrue((self.profiles / "work").is_dir())
                self.svc.close()

    def test_a_profile_whose_sign_in_is_running_is_refused(self):
        stub = types.SimpleNamespace(running=lambda: frozenset({"work"}), close=lambda: None)
        self.begin(runs=lambda on_end: stub)
        before = support.log_rows(self.store)
        status, _, body = self.remove()
        self.assertEqual((status, body), (409, b"a sign-in is running for work; cancel it first\n"))
        self.assertEqual(support.log_rows(self.store), before)
        self.assertEqual(self.calls, [])


class RemoveRunTest(Case):
    def test_an_accepted_removal_signs_out_under_the_profile_before_it_removes(self):
        self.begin()
        status, _, body = self.remove()
        self.assertEqual((status, body), (204, b""))
        self.assertEqual(self.calls, [("signout", "work"), ("rm", "work")])
        self.assertFalse((self.profiles / "work").exists())
        self.assertTrue((self.profiles / "home").is_dir())

    def test_an_accepted_removal_appends_one_owner_action_row(self):
        self.begin()
        self.assertEqual(self.remove()[::2], (204, b""))
        self.assertEqual([p for _, p in self.rows("account.removal")],
                         [{"by": "owner", "profile": "work", "outcome": "removed", "kind": None}])
        self.assertEqual(self.rows("profile.pin"), [])
        self.assertEqual(self.rows("profile.exclusion"), [])

    def test_a_failed_sign_out_of_a_signed_in_profile_deletes_nothing_and_says_why(self):
        for label, error in (("signed_in", None), ("unreadable", signin.StatusFailed("timed_out"))):
            with self.subTest(label=label):
                self.calls.clear()
                self.signout_error = account_remove.SignOutFailed("exited")
                self.read_error = error
                self.begin()
                before = len(self.rows("account.removal"))
                err = io.StringIO()
                with contextlib.redirect_stderr(err):
                    status, _, body = self.remove()
                self.assertEqual(
                    (status, body),
                    (502, b"the account was not removed: its sign-out failed: exited\n"))
                self.assertEqual(self.calls, [("signout", "work"), ("read", "work")])
                self.assertTrue((self.profiles / "work").is_dir())
                self.assertEqual(
                    [p for _, p in self.rows("account.removal")][before:],
                    [{"by": "owner", "profile": "work", "outcome": "signout_failed",
                      "kind": "exited"}])
                self.assertIn("console: account_remove_signout_failed work exited", err.getvalue())
                self.svc.close()

    def test_a_failed_sign_out_of_a_profile_that_reads_signed_out_still_removes_it(self):
        self.signout_error = account_remove.SignOutFailed("exited")
        self.status = signin.Status("signed_out", None)
        self.begin()
        self.assertEqual(self.remove()[::2], (204, b""))
        self.assertEqual(self.calls, [("signout", "work"), ("read", "work"), ("rm", "work")])
        self.assertFalse((self.profiles / "work").exists())
        self.assertEqual(
            [p for _, p in self.rows("account.removal")],
            [{"by": "owner", "profile": "work", "outcome": "removed_signed_out_already",
              "kind": "exited"}])

    def test_a_launcher_failure_keeps_the_profile_and_records_it(self):
        def failing(name):
            self.calls.append(("rm", name))
            raise account_remove.RemoveFailed("failed")
        svc = self.begin(remover=failing)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            status, _, body = self.remove()
        self.assertEqual(
            (status, body), (502, b"the account was signed out but not removed: failed\n"))
        self.assertIn("console: account_remove_failed work failed", err.getvalue())
        self.assertEqual([p for _, p in self.rows("account.removal")],
                         [{"by": "owner", "profile": "work", "outcome": "remove_failed",
                           "kind": "failed"}])
        self.assertTrue((self.profiles / "work").is_dir())
        self.assertIn("work", [p["profile"] for p in self.view()["capacity"]["profiles"]])
        self.now[0] += probe.PROBE_FIRST_SECONDS
        self.assertIn("work", [p.profile for p in svc.probe_round()])

    def test_a_remover_that_deletes_nothing_leaves_the_profile_still_listed(self):
        self.begin(remover=lambda name: self.calls.append(("rm", name)))
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            status, _, body = self.remove()
        self.assertEqual(
            (status, body), (502, b"the account was signed out but not removed: still_listed\n"))
        self.assertIn("console: account_remove_failed work still_listed", err.getvalue())
        self.assertEqual([p["kind"] for _, p in self.rows("account.removal")], ["still_listed"])

    def test_any_other_failure_is_500_with_the_type_only(self):
        def failing(name):
            raise RuntimeError("secret-text")
        self.begin(remover=failing)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            status, _, body = self.remove()
        self.assertEqual((status, body), (500, b"removing the account failed\n"))
        self.assertEqual(err.getvalue(), "console: account_remove_failed RuntimeError\n")
        self.assertNotIn("secret-text", err.getvalue())

    def test_two_removals_of_one_profile_run_once(self):
        entered = threading.Event()
        gate = threading.Event()

        def slow(one):
            self.calls.append(("signout", one.profile))
            entered.set()
            gate.wait(10)
        self.begin(signer_out=slow)
        answers = []

        def go():
            answers.append(self.remove())
        first = threading.Thread(target=go)
        first.start()
        self.assertTrue(entered.wait(10))
        second = threading.Thread(target=go)
        second.start()
        second.join(0.2)
        gate.set()
        first.join(10)
        second.join(10)
        self.assertEqual(sorted(status for status, _, _ in answers), [204, 409])
        self.assertEqual([body for status, _, body in answers if status == 409],
                         [b"no such profile\n"])
        self.assertEqual(self.calls.count(("rm", "work")), 1)
        self.assertEqual(len(self.rows("account.removal")), 1)

    def test_a_long_launcher_valid_name_is_removed(self):
        support.profile_dir(self.store, LONG)
        self.begin()
        self.assertEqual(self.remove(LONG)[::2], (204, b""))
        self.assertEqual(self.calls, [("signout", LONG), ("rm", LONG)])
        self.assertEqual([p["profile"] for _, p in self.rows("account.removal")], [LONG])


class RemoveEffectTest(Case):
    def test_a_removed_profile_leaves_the_strip_the_sign_in_the_probe_and_the_choice(self):
        svc = self.begin(seed=[signin.entry("work", signin.Status("signed_out", None)),
                               signin_run.ended("work", "failed", 1)])
        keys = lambda: [i["key"] for i in self.view()["inbox"]["open"]]  # noqa: E731
        self.assertIn("signin/work", keys())
        self.assertEqual(self.remove()[::2], (204, b""))
        self.assertEqual([p["profile"] for p in self.view()["capacity"]["profiles"]], ["home"])
        self.assertNotIn("signin/work", keys())
        self.assertNotIn("work", self.view()["signin_runs"])
        mark = len(self.calls)
        self.now[0] += probe.PROBE_FIRST_SECONDS
        self.assertEqual([p.profile for p in svc.probe_round()], ["home"])
        self.assertIn(("read", "home"), self.calls[mark:])
        self.assertNotIn(("read", "work"), self.calls[mark:])
        self.assertEqual(self.ask(), b'{"profile":"home"}')
        self.assertEqual(self.choice_file.read_text(), "home\n")

    def test_removing_drops_the_pin_and_the_exclusion_and_records_them(self):
        svc = self.begin()
        svc.set_pin("work", True)
        mark = len(support.log_rows(self.store))
        self.assertEqual(self.remove()[::2], (204, b""))
        after = [(row[2], json.loads(row[4])) for row in support.log_rows(self.store)[mark:]]
        self.assertEqual(after, [
            ("profile.pin", {"profile": "work", "pinned": False}),
            ("account.removal", {"by": "owner", "profile": "work", "outcome": "removed",
                                 "kind": None})])
        self.assertIsNone(svc._pinned)
        self.assertIsNone(self.view()["pin"])
        svc.close()
        self.assertIsNone(self.begin()._pinned)
        self.svc.close()
        support.profile_dir(self.store, "work")
        svc = self.begin()
        svc.set_exclusion("work", True)
        mark = len(support.log_rows(self.store))
        self.assertEqual(self.remove()[::2], (204, b""))
        after = [(row[2], json.loads(row[4])) for row in support.log_rows(self.store)[mark:]]
        self.assertEqual(after, [
            ("profile.exclusion", {"profile": "work", "excluded": False}),
            ("account.removal", {"by": "owner", "profile": "work", "outcome": "removed",
                                 "kind": None})])
        self.assertEqual(support.request(svc.address, "GET", "/api/excluded")[2],
                         b'{"excluded":[]}')
        svc.close()
        again = self.begin()
        self.assertEqual(again.excluded_profiles(), [])

    def test_a_running_session_under_the_profile_is_not_stopped(self):
        support.write_session(self.profiles / "work" / "sessions", pid=os.getpid(),
                              session_id="s1", cwd=str(self.root), status="idle")
        svc = support.service(
            self, self.store, self.registry, profile_dirs=Listing(self.profiles),
            session_dirs=[self.profiles / "work" / "sessions"], clock=lambda: self.now[0],
            session_poll_seconds=3600, probe_tick_seconds=3600,
            signin_reader=self.reader, signer_out=self.signer_out,
            account_remover=self.remover)
        self.svc = svc
        svc.poll_sessions()
        before = dict(svc._sessions)
        self.assertEqual([s.profile for s in before.values()], ["work"])
        self.assertEqual(self.remove()[::2], (204, b""))
        self.assertEqual(svc._sessions, before)
        self.assertEqual(self.rows("sprint.stop_requested"), [])
        self.assertEqual(self.rows("manager.stopped"), [])


class RemoveInterleavingTest(Case):
    def test_no_probe_of_the_profile_starts_during_its_removal(self):
        def round_():
            self.now[0] += probe.PROBE_FIRST_SECONDS
            self.calls.append(("round", [p.profile for p in self.svc.probe_round()]))
        self.during = [round_]
        self.begin()
        self.assertEqual(self.remove()[::2], (204, b""))
        self.assertIn(("round", ["home"]), self.calls)
        self.assertNotIn(("read", "work"), self.calls)

    def test_the_choice_never_names_a_profile_being_removed(self):
        self.begin(seed=[signin.entry("work", signin.Status("signed_in", None)),
                         signin.entry("home", signin.Status("signed_out", None))])
        self.assertEqual(self.ask(), b'{"profile":"work"}')
        self.during = [lambda: self.calls.append(("ask", self.ask()))]
        self.assertEqual(self.remove()[::2], (204, b""))
        self.assertIn(("ask", b'{"profile":null}'), self.calls)
        self.assertNotIn("work", self.choice_file.read_text() if self.choice_file.exists() else "")

    def test_a_sign_in_cannot_start_during_the_removal(self):
        stub = types.SimpleNamespace(
            running=lambda: frozenset(),
            start=lambda profile: (self.calls.append(("start", profile)),
                                   types.SimpleNamespace(fresh=True, run=1))[1],
            wait_link=lambda profile: None, close=lambda: None)

        def try_start():
            try:
                self.svc.start_signin("work")
            except sprints.Refused as error:
                self.calls.append(("refused", str(error)))
        self.during = [try_start]
        self.begin(runs=lambda on_end: stub)
        self.assertEqual(self.remove()[::2], (204, b""))
        self.assertIn(("refused", "work is being removed"), self.calls)
        self.assertNotIn(("start", "work"), self.calls)
        self.assertEqual(
            [p for _, p in self.rows("signin.acted") if p["profile"] == "work"], [])

    def start_slow_probe(self):
        self.read_gate = {"work": threading.Event()}
        svc = self.begin(probe_dispatch=lambda job: threading.Thread(target=job).start())
        self.now[0] += probe.PROBE_FIRST_SECONDS
        svc.probe_round()
        deadline = time.monotonic() + 5
        while ("read", "work") not in self.calls and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertIn(("read", "work"), self.calls)
        return svc

    def test_a_probe_of_the_profile_already_running_ends_before_the_sign_out(self):
        self.start_slow_probe()
        answers = []
        thread = threading.Thread(target=lambda: answers.append(self.remove()))
        thread.start()
        thread.join(0.3)
        self.assertTrue(thread.is_alive())
        self.assertNotIn(("signout", "work"), self.calls)
        self.read_gate["work"].set()
        thread.join(10)
        self.assertEqual(answers[0][::2], (204, b""))
        self.assertGreater(self.calls.index(("signout", "work")),
                           self.calls.index(("read", "work")))

    def test_a_probe_that_does_not_end_refuses_the_removal_for_now(self):
        svc = self.start_slow_probe()
        with mock.patch.object(account_remove, "DRAIN_TIMEOUT", 0.2):
            status, _, body = self.remove()
        self.assertEqual((status, body), (409, b"work is still being read; try again in a moment\n"))
        self.assertEqual(self.rows("account.removal"), [])
        self.assertNotIn(("signout", "work"), self.calls)
        self.assertTrue((self.profiles / "work").is_dir())
        self.read_gate["work"].set()
        deadline = time.monotonic() + 5
        while svc._probing and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertFalse(svc._probing)
        self.assertEqual(self.remove()[::2], (204, b""))


if __name__ == "__main__":
    unittest.main()
