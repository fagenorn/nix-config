"""A listed colleague adds and signs in his own account from the guest door (#1343, ADR-console-087).

Run: just agent-workflow-tests
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import unittest
from unittest import mock
from datetime import datetime, timezone
from pathlib import Path

from agent_tools.console import (
    account_add, account_remove, folder_trust, guest, service, signin, signin_run, sprints)

from . import console_test_support as support
from .test_console_account_service import NOW, Listing
from .test_console_guest_actions import SECOND, GuestWriteCase
from .test_console_guest_service import COLLEAGUE, JSON, STRANGER, TAILNET
from .test_console_signin_run import (
    CODE, FAKE, LOOPBACK_LINK, MANUAL_LINK, stderr_text, until)
from .test_console_stream import next_frame
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)

ADD = "/api/guest-account"
CODE_ROUTE = "/api/guest-signin-code"
CANCEL = "/api/guest-signin-cancel"
ROUTES = (ADD, CODE_ROUTE, CANCEL)
VALID = {ADD: {"consent": True}, CODE_ROUTE: {"attempt": 1, "code": CODE}, CANCEL: {"attempt": 1}}
PLANTED = "sk-ant-oat01-PLANTED-zq77"


class Unreadable:
    """The profile listing of a case, which fails while the case's `list_error` is set."""

    def __init__(self, case):
        self.case = case

    def __iter__(self):
        if self.case.list_error is not None:
            raise self.case.list_error
        return iter(Listing(self.case.profiles))


class GuestAccountCase(GuestWriteCase):
    def setUp(self):
        super().setUp()
        self.profiles = self.store.parent.parent / "accounts" / "profiles"
        support.profile_dir(self.store, "work")
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        script = bin_dir / "claude-account"
        script.write_text(FAKE % {"python": sys.executable})
        script.chmod(0o755)
        self.record = self.root / "record.jsonl"
        self.environ = {"HOME": str(self.root), "PATH": f"{bin_dir}:/usr/bin:/bin",
                        "FAKE_RECORD": str(self.record), "FAKE_MODE": "code",
                        "FAKE_LINK": LOOPBACK_LINK, "FAKE_MANUAL": MANUAL_LINK}
        self.now = [NOW]
        self.status_of = {}
        self.read_error = {}
        self.added = []
        self.add_error = None
        self.after_add = None
        self.remove_fails = False
        self.grant_error = None
        self.list_error = None
        self.granted = []
        self.link_wait = 5
        self.end_gate = threading.Event()
        self.end_gate.set()
        self.responses = []
        # Every directory reads as one inode: a replacement that the filesystem gives the freed inode at once.
        same = os.stat_result((0o40700, 4242, 1, 2, 0, 0, 64, 0, 0, 0))
        patch = mock.patch.object(account_add, "_stat", lambda _: same)
        patch.start()
        self.addCleanup(patch.stop)

    def read(self, one):
        if one.profile in self.read_error:
            raise self.read_error[one.profile]
        return self.status_of.get(one.profile, signin.Status("signed_out", None))

    def adder(self, name):
        self.added.append(name)
        if self.add_error is not None:
            raise self.add_error
        (self.profiles / name).mkdir(mode=0o700)
        if self.after_add is not None:
            self.after_add(name)

    def remover(self, name):
        if self.remove_fails:
            raise account_remove.RemoveFailed("failed")
        shutil.rmtree(self.profiles / name)

    def granter(self, path, key):
        self.granted.append(Path(path).parent.name)
        if self.grant_error is not None:
            raise self.grant_error
        return folder_trust.grant(path, key)

    def gate(self, on_end):
        def ended(*args):
            self.end_gate.wait(10)
            return on_end(*args)
        return ended

    def begin(self):
        if not self.store.exists():
            self.seed(colleagues={COLLEAGUE: ["owner/p01"], SECOND: ["owner/p01"]})

        def factory(on_end):
            return signin_run.SignIns(on_end=self.gate(on_end), environ=self.environ,
                                      link_wait=self.link_wait, manual_grace=0.2,
                                      host="console-host")
        self.svc = self.start(
            profile_dirs=Unreadable(self), signin_reader=self.read, signin_runs=factory,
            account_adder=self.adder, signer_out=lambda one: None, account_remover=self.remover,
            trust_granter=self.granter,
            clock=lambda: self.now[0],
            log_clock=lambda: datetime.fromtimestamp(self.now[0], timezone.utc).isoformat(
                timespec="microseconds"),
            session_poll_seconds=3600, probe_tick_seconds=3600,
            probe_dispatch=lambda job: job())
        self.svc.poll_sessions()
        return self.svc

    def names(self):
        return {p.name for p in self.profiles.glob("*")}

    def lines(self):
        if not self.record.exists():
            return []
        return [json.loads(line) for line in self.record.read_text().splitlines()]

    def code_records(self):
        return [line["code"] for line in self.lines() if "code" in line]

    def clients(self):
        return [line for line in self.lines() if "argv" in line]

    def owner_view(self):
        return json.loads(self.svc.view_bytes)

    def guest_view(self, login=COLLEAGUE):
        return json.loads(self.svc.guest_view_bytes(login))

    def owner_of(self, profile):
        return next(entry["owner"] for entry in self.owner_view()["capacity"]["profiles"]
                    if entry["profile"] == profile)

    def own_state(self, login=COLLEAGUE):
        own = self.guest_view(login)["own_signin"]
        return None if own is None else own["state"]

    def start_seqs(self):
        return [row[0] for row in support.log_rows(self.store) if row[2] == "signin.acted"
                and json.loads(row[4])["action"] == "start"]

    def post(self, path, body, login=COLLEAGUE, **kwargs):
        status, answer = self.guest_post(self.svc, path, body, logins=(login,), **kwargs)
        self.responses.append((status, dict(self.last_headers), answer))
        return status, answer

    def get(self, path, login=COLLEAGUE):
        got = self.guest(self.svc, "GET", path, logins=(login,))
        self.responses.append(got)
        return got

    def add(self, login=COLLEAGUE):
        return self.post(ADD, {"consent": True}, login)

    def timed(self, call):
        box = []
        thread = threading.Thread(target=lambda: box.append(call()), daemon=True)
        thread.start()
        thread.join(10)
        self.assertFalse(thread.is_alive(), "the call did not return")
        return box[0]

    def shown_attempt(self, login=COLLEAGUE):
        return self.guest_view(login)["own_signin"]["attempt"]

    def sent_code(self, login=COLLEAGUE):
        attempt = self.shown_attempt(login)
        status, _ = self.timed(lambda: self.post(CODE_ROUTE, {"attempt": attempt, "code": CODE}, login))
        self.assertEqual(status, 204)
        self.assertEqual(self.timed(lambda: self.owner(self.svc, "GET", "/api/state"))[0], 200)

    def signed_in(self, profile, login=COLLEAGUE):
        self.status_of[profile] = signin.Status("signed_in", None, f"{profile}@corp-zq.invalid")
        self.sent_code(login)
        until(self, lambda: self.own_state(login) == "signed_in")

    def cancelled(self, login=COLLEAGUE):
        attempt = self.shown_attempt(login)
        status, _ = self.timed(lambda: self.post(CANCEL, {"attempt": attempt}, login))
        self.assertEqual(status, 204)
        self.assertEqual(self.timed(lambda: self.owner(self.svc, "GET", "/api/state"))[0], 200)
        until(self, lambda: self.own_state(login) == "cancelled")

    def acted(self):
        return self.rows("signin.acted")

    def added_rows(self):
        """The `account.added` payloads, each colleague's identity checked present and then left out."""
        rows = self.rows("account.added")
        for row in rows:
            if row["by"] != "owner":
                self.assertTrue(row.get("identity"), row)
        return [{key: value for key, value in row.items() if key != "identity"} for row in rows]

    def replace_dir(self, name):
        """The owner removes a profile with the CLI and makes another of the name, which every directory reads
        as the same inode of (see `setUp`), as a filesystem that reuses a freed inode gives it."""
        shutil.rmtree(self.profiles / name)
        (self.profiles / name).mkdir(mode=0o700)


class GuestAccountTest(GuestAccountCase):
    def test_a_listed_colleague_adds_a_profile_he_owns_and_signs_it_in_after_the_tick(self):
        self.begin()
        status, body = self.add()
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"attempt": self.start_seqs()[0], "link": MANUAL_LINK,
                                            "route": "manual"})
        self.assertEqual(self.names(), {"work", "colleague-1"})
        self.assertEqual(self.added_rows(), [{"by": COLLEAGUE, "profile": "colleague-1"}])
        self.assertEqual(self.acted(), [{"by": COLLEAGUE, "profile": "colleague-1",
                                         "action": "start", "outcome": "started"}])
        self.assertEqual([line["account"] for line in self.clients()], ["colleague-1"])
        self.assertEqual(self.owner_of("colleague-1"), COLLEAGUE)
        self.assertEqual(self.own_state(), "running")
        self.status_of["colleague-1"] = signin.Status("signed_in", None, "c1@corp-zq.invalid")
        self.sent_code()
        until(self, lambda: self.own_state() == "signed_in")
        self.assertEqual(self.code_records(), [CODE])
        self.assertEqual([(row["action"], row["by"]) for row in self.acted()],
                         [("start", COLLEAGUE), ("code", COLLEAGUE)])
        yours = [row for row in self.guest_view()["pool"]["accounts"] if row["label"] == "yours"]
        self.assertEqual([row["in_use"] for row in yours], [True])

    def test_a_second_add_while_his_sign_in_runs_joins_it(self):
        self.begin()
        first = self.add()
        second = self.add()
        self.assertEqual((first[0], second[0]), (200, 200))
        self.assertEqual(json.loads(first[1]), json.loads(second[1]))
        self.assertEqual(self.names(), {"work", "colleague-1"})
        self.assertEqual([row["outcome"] for row in self.acted()], ["started", "running"])
        self.assertEqual(len(self.clients()), 1)

    def test_an_add_after_a_cancel_signs_in_the_same_profile_again(self):
        self.begin()
        self.assertEqual(self.add()[0], 200)
        self.cancelled()
        self.assertEqual(self.add()[0], 200)
        self.assertEqual(self.names(), {"work", "colleague-1"})
        self.assertEqual([row["by"] for row in self.acted() if row["action"] == "cancel"],
                         [COLLEAGUE])
        starts = [row for row in self.acted() if row["action"] == "start"]
        self.assertEqual(starts[-1]["profile"], "colleague-1")
        self.assertEqual(len(starts), 2)

    def test_an_add_joins_his_live_sign_in_before_another_profile_not_signed_in(self):
        svc = self.begin()
        self.assertEqual(self.add()[0], 200)
        self.signed_in("colleague-1")
        self.assertEqual(self.add()[0], 200)
        self.cancelled()
        attempt, _ = svc.start_signin(
            "colleague-1", by=guest.GuestActor(COLLEAGUE, TAILNET, svc._guest_epoch))
        status, body = self.add()
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["attempt"], attempt)
        self.assertEqual(self.names(), {"work", "colleague-1", "colleague-2"})
        self.assertEqual(self.acted()[-1]["profile"], "colleague-1")
        self.assertEqual(len(self.clients()), 3)

    def test_an_add_after_his_account_signed_in_creates_another(self):
        self.begin()
        self.assertEqual(self.add()[0], 200)
        self.signed_in("colleague-1")
        self.assertEqual(self.add()[0], 200)
        self.assertEqual(self.names(), {"work", "colleague-1", "colleague-2"})
        self.assertEqual(self.owner_of("colleague-2"), COLLEAGUE)

    def test_a_loopback_only_sign_in_hands_the_guest_no_link(self):
        del self.environ["FAKE_MANUAL"]
        self.begin()
        status, body = self.add()
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"attempt": self.start_seqs()[0], "link": None,
                                            "route": "loopback"})
        for word in (b"localhost", b"ssh", b"console-host"):
            self.assertNotIn(word, body)

    def test_a_sign_in_with_no_link_yet_answers_none(self):
        self.environ["FAKE_MODE"] = "nolink"
        del self.environ["FAKE_MANUAL"]
        self.link_wait = 0.5
        self.begin()
        first = self.add()
        self.assertEqual(first[0], 200)
        self.assertEqual(json.loads(first[1]),
                         {"attempt": self.start_seqs()[0], "link": None, "route": None})
        second = self.add()
        self.assertEqual(json.loads(second[1])["attempt"], json.loads(first[1])["attempt"])


class GuestAccountRefusalTest(GuestAccountCase):
    def nothing_started(self):
        self.assertEqual(self.added, [])
        self.assertEqual(self.added_rows(), [])
        self.assertEqual(self.acted(), [])
        self.assertEqual(self.clients(), [])

    def no_sign_in_started(self):
        self.assertEqual(self.acted(), [])
        self.assertEqual(self.clients(), [])

    def test_each_guest_account_write_is_guarded_like_a_guest_write(self):
        svc = self.begin()
        origin = "https://" + TAILNET
        guards = (
            ("no token", {"token": None}, 403, "token refused"),
            ("owner token", {"token": self.owner_token()}, 403, "token refused"),
            ("http origin", {"origin": "http://" + TAILNET}, 403, "origin refused"),
            ("no origin", {"origin": None}, 403, "origin refused"),
            ("two origins", {"origin": [origin, origin]}, 403, "origin refused"),
            ("no login", {"logins": ()}, 403, guest.NOT_SHARED_TEXT),
            ("two logins", {"logins": (COLLEAGUE, SECOND)}, 403, guest.NOT_SHARED_TEXT),
            ("one login twice", {"logins": (COLLEAGUE, COLLEAGUE)}, 403, guest.NOT_SHARED_TEXT),
            ("unlisted login", {"logins": (STRANGER,)}, 403, guest.NOT_SHARED_TEXT))
        for route in ROUTES:
            for name, kwargs, status, text in guards:
                with self.subTest(route=route, case=name):
                    got = self.still(svc, lambda: self.guest_post(
                        svc, route, b"", send_body=False, **kwargs))
                    self.assertEqual(got, (status, text.encode() + b"\n"))
            with self.subTest(route=route, case="a GET"):
                got = self.still(svc, lambda: self.guest_post(
                    svc, route, b"", send_body=False, method="GET"))
                self.assertEqual(got, (405, b"method not allowed\n"))
                self.assertEqual(self.last_headers["Allow"], "POST")
        self.nothing_started()

    def test_no_login_header_creates_and_starts_nothing(self):
        svc = self.begin()
        for route in ROUTES:
            with self.subTest(route=route):
                got = self.still(svc, lambda: self.guest_post(svc, route, VALID[route], logins=()))
                self.assertEqual(got, (403, guest.NOT_SHARED_TEXT.encode() + b"\n"))
        self.nothing_started()

    def test_an_unlisted_login_creates_and_starts_nothing(self):
        svc = self.begin()
        for route in ROUTES:
            with self.subTest(route=route):
                got = self.still(svc, lambda: self.guest_post(
                    svc, route, VALID[route], logins=(STRANGER,)))
                self.assertEqual(got[0], 403)
        self.nothing_started()

    def test_two_login_headers_create_and_start_nothing(self):
        svc = self.begin()
        for route in ROUTES:
            for logins in ((COLLEAGUE, COLLEAGUE), (COLLEAGUE, SECOND)):
                with self.subTest(route=route, logins=logins):
                    got = self.still(svc, lambda: self.guest_post(
                        svc, route, VALID[route], logins=logins))
                    self.assertEqual(got[0], 403)
        self.nothing_started()

    def test_the_owner_is_refused_a_sign_in_of_a_profile_a_colleague_added(self):
        """#1361, ADR-console-087 D3: the owner's start for his account starts no run and writes no row."""
        svc = self.begin()
        self.assertEqual(self.add()[0], 200)
        self.cancelled()
        before = (self.acted(), len(self.clients()))
        headers = {"Origin": f"http://127.0.0.1:{svc.address[1]}",
                   "X-Console-Token": self.owner_token(), **JSON}
        status, _, answer = support.post_page(
            svc.address, service.SIGNIN_PATH, headers, json.dumps({"profile": "colleague-1"}).encode())
        self.assertEqual(status, 409)
        self.assertEqual(answer, guest.colleague_signin_text("colleague-1", COLLEAGUE).encode() + b"\n")
        self.assertIn(COLLEAGUE.encode(), answer)
        with self.assertRaises(sprints.Refused) as raised:
            svc.start_signin("colleague-1")
        self.assertEqual(str(raised.exception), guest.colleague_signin_text("colleague-1", COLLEAGUE))
        self.assertEqual((self.acted(), len(self.clients())), before)
        self.assertEqual(self.own_state(), "cancelled")
        attempt, _ = svc.start_signin("work")
        self.assertGreater(attempt, 0)

    def test_a_sign_in_of_a_profile_not_his_is_refused(self):
        svc = self.begin()
        self.assertEqual(self.add()[0], 200)
        first = self.own_signin_attempt()
        owner_only = (403, guest.OWNER_ONLY_TEXT.encode() + b"\n")
        for route, body in ((service.SIGNIN_PATH, {"profile": "colleague-1"}),
                            (service.SIGNIN_PATH, {"profile": "work"}),
                            (service.SIGNIN_CODE_PATH, {"profile": "colleague-1", "code": CODE})):
            with self.subTest(route=route, body=body):
                self.assertEqual(self.post(route, body, SECOND), owner_only)
        no_run = (409, guest.NO_OWN_SIGNIN_TEXT.encode() + b"\n")
        self.assertEqual(self.post(CODE_ROUTE, {"attempt": first, "code": CODE}, SECOND), no_run)
        self.assertEqual(self.post(CANCEL, {"attempt": first}, SECOND), no_run)
        theirs = guest.GuestActor(SECOND, TAILNET, svc._guest_epoch)
        for profile in ("colleague-1", "work"):
            with self.subTest(profile=profile):
                with self.assertRaises(sprints.Refused) as raised:
                    svc.start_signin(profile, by=theirs)
                self.assertEqual(str(raised.exception), guest.NO_OWN_SIGNIN_TEXT)
        self.assertEqual(self.code_records(), [])
        self.assertEqual(len(self.clients()), 1)
        self.assertEqual(self.guest_view()["own_signin"]["attempt"], first)
        self.assertEqual(self.own_state(), "running")
        self.assertEqual([row for row in self.acted() if row["by"] == SECOND], [])
        self.assertEqual(self.add(SECOND)[0], 200)
        self.assertEqual(self.names(), {"work", "colleague-1", "colleague-2"})
        self.assertEqual(self.owner_of("colleague-2"), SECOND)
        self.assertEqual(self.owner_of("colleague-1"), COLLEAGUE)

    def test_a_stale_attempt_cannot_cancel_or_pass_a_code_to_a_newer_sign_in(self):
        self.begin()
        first = json.loads(self.add()[1])["attempt"]
        self.cancelled()
        second = json.loads(self.add()[1])["attempt"]
        self.assertNotEqual(first, second)
        fixed = (409, guest.NO_OWN_SIGNIN_TEXT.encode() + b"\n")
        self.assertEqual(self.post(CANCEL, {"attempt": first}), fixed)
        self.assertEqual(self.post(CODE_ROUTE, {"attempt": first, "code": CODE}), fixed)
        self.assertEqual(self.post(CANCEL, {"attempt": second + 1000}), fixed)
        self.assertEqual(self.code_records(), [])
        self.assertEqual(self.own_state(), "running")
        self.assertEqual([row["action"] for row in self.acted()], ["start", "cancel", "start"])
        self.assertEqual(self.post(CANCEL, {"attempt": second})[0], 204)
        until(self, lambda: self.own_state() == "cancelled")

    def test_code_and_cancel_act_on_the_attempt_his_page_shows_among_two_live_sign_ins(self):
        svc = self.begin()
        self.assertEqual(self.add()[0], 200)
        self.signed_in("colleague-1")
        self.assertEqual(self.add()[0], 200)
        self.signed_in("colleague-2")
        theirs = guest.GuestActor(COLLEAGUE, TAILNET, svc._guest_epoch)
        older, _ = svc.start_signin("colleague-1", by=theirs)
        newer, _ = svc.start_signin("colleague-2", by=theirs)
        self.assertLess(older, newer)
        self.assertEqual(self.shown_attempt(), newer)
        self.assertEqual(svc._signin_runs.running(), {"colleague-1", "colleague-2"})
        self.assertEqual(self.timed(lambda: self.post(CANCEL, {"attempt": newer}))[0], 204)
        until(self, lambda: svc._signin_runs.running() == {"colleague-1"})
        cancels = [row["profile"] for row in self.acted() if row["action"] == "cancel"]
        self.assertEqual(cancels, ["colleague-2"])
        self.assertEqual(self.timed(lambda: self.post(CANCEL, {"attempt": newer}))[0], 409)
        self.assertEqual(self.timed(lambda: self.post(CANCEL, {"attempt": older}))[0], 204)
        until(self, lambda: not svc._signin_runs.running())

    def test_a_colleague_removed_while_the_link_is_awaited_gets_no_link(self):
        svc = self.begin()
        runs = svc._signin_runs
        awaited = runs.wait_link

        def wait_then_revoke(profile):
            link = awaited(profile)
            svc.remove_colleague(COLLEAGUE)
            return link
        runs.wait_link = wait_then_revoke
        status, body = self.add()
        self.assertEqual(status, 409)
        self.assertIn(body.decode().strip(), (guest.REVOKED_TEXT, guest.NOT_SHARED_TEXT))
        self.assertNotIn(b"https", body)
        self.assertNotIn(b"link", body)

    def test_an_add_whose_profile_listing_cannot_be_read_records_and_creates_nothing(self):
        self.begin()
        (self.profiles / "colleague-1").mkdir()
        self.list_error = OSError("cannot list")
        status, body = self.add()
        self.assertEqual(status, 502)
        self.assertEqual(body, b"the account could not be created: unavailable\n")
        self.nothing_started()
        self.list_error = None
        self.assertEqual(self.add()[0], 200)
        self.assertEqual(self.names(), {"work", "colleague-1", "colleague-2"})
        self.assertEqual(self.added, ["colleague-2"])
        self.assertEqual(self.added_rows(), [{"by": COLLEAGUE, "profile": "colleague-2"}])
        self.assertIsNone(self.owner_of("colleague-1"))
        self.assertEqual(self.owner_of("colleague-2"), COLLEAGUE)
        self.assertEqual([line["account"] for line in self.clients()], ["colleague-2"])

    def test_an_add_that_fails_before_the_directory_exists_never_makes_a_later_owner_profile_his(self):
        self.begin()
        self.add_error = account_add.AddFailed("failed")
        self.assertEqual(self.add()[0], 502)
        self.assertEqual(self.added, ["colleague-1"])
        self.assertEqual(self.added_rows(), [])
        self.add_error = None
        (self.profiles / "colleague-1").mkdir()
        self.assertEqual(self.add()[0], 200)
        self.assertEqual(self.names(), {"work", "colleague-1", "colleague-2"})
        self.assertEqual(self.added_rows(), [{"by": COLLEAGUE, "profile": "colleague-2"}])
        self.assertIsNone(self.owner_of("colleague-1"))
        self.assertEqual([line["account"] for line in self.clients()], ["colleague-2"])

    def test_an_add_whose_launcher_returned_but_whose_listing_failed_is_recovered_by_the_retry(self):
        self.begin()

        def unreadable(name):
            self.list_error = OSError("cannot list")
        self.after_add = unreadable
        self.assertEqual(self.add()[0], 502)
        self.assertEqual(self.names(), {"work", "colleague-1"})
        self.assertEqual(self.added_rows(), [])
        self.assertEqual(self.added, ["colleague-1"])
        self.list_error = None
        self.after_add = None
        self.assertEqual(self.add()[0], 200)
        self.assertEqual(self.names(), {"work", "colleague-1"})
        self.assertEqual(self.added, ["colleague-1"])
        self.assertEqual(self.added_rows(), [{"by": COLLEAGUE, "profile": "colleague-1"}])
        self.assertEqual(self.owner_of("colleague-1"), COLLEAGUE)
        self.assertEqual([line["account"] for line in self.clients()], ["colleague-1"])

    def test_a_profile_the_owner_replaced_before_the_retry_is_not_taken_by_the_retry(self):
        self.begin()

        def unreadable(name):
            self.list_error = OSError("cannot list")
        self.after_add = unreadable
        self.assertEqual(self.add()[0], 502)
        self.list_error = None
        self.after_add = None
        self.replace_dir("colleague-1")
        status, _ = self.add()
        self.assertEqual(status, 200)
        self.assertEqual(self.names(), {"work", "colleague-1", "colleague-2"})
        self.assertEqual(self.added, ["colleague-1", "colleague-2"])
        self.assertEqual(self.added_rows(), [{"by": COLLEAGUE, "profile": "colleague-2"}])
        self.assertIsNone(self.owner_of("colleague-1"))
        self.assertEqual(self.owner_of("colleague-2"), COLLEAGUE)
        self.assertEqual([line["account"] for line in self.clients()], ["colleague-2"])

    def test_a_profile_replaced_between_the_launcher_and_the_listing_is_not_his(self):
        self.begin()
        self.after_add = lambda name: None
        real = self.svc._scan_accounts
        scans = []

        def replaced_before_the_second_listing():
            scans.append(1)
            if len(scans) == 2:  # the listing after the launcher returned
                self.replace_dir("colleague-1")
            return real()
        self.svc._scan_accounts = replaced_before_the_second_listing
        status, body = self.add()
        self.assertEqual((status, body), (502, b"the account could not be created: not_listed\n"))
        self.assertEqual(self.added_rows(), [])
        self.assertEqual(self.clients(), [])
        self.svc._scan_accounts = real
        self.svc.poll_sessions()
        self.assertIsNone(self.owner_of("colleague-1"))
        self.assertEqual(self.add()[0], 200)
        self.assertEqual([line["account"] for line in self.clients()], ["colleague-2"])
        self.assertEqual(self.owner_of("colleague-2"), COLLEAGUE)

    def test_a_profile_the_owner_replaced_after_his_add_is_no_longer_his_to_sign_in(self):
        svc = self.removed_and_made_again()
        self.replace_dir("colleague-1")
        theirs = guest.GuestActor(COLLEAGUE, TAILNET, svc._guest_epoch)
        with self.assertRaises(sprints.Refused) as raised:
            svc.start_signin("colleague-1", by=theirs)
        self.assertEqual(str(raised.exception), guest.NO_OWN_SIGNIN_TEXT)
        self.assertEqual([line["account"] for line in self.clients()], ["colleague-1"])
        svc.poll_sessions()
        self.assertIsNone(self.owner_of("colleague-1"))
        self.assertEqual([row for row in self.guest_view()["pool"]["accounts"]
                          if row["label"] == "yours"], [])
        self.assertEqual(self.add()[0], 200)
        self.assertEqual(self.names(), {"work", "colleague-1", "colleague-2"})
        self.assertEqual([line["account"] for line in self.clients()], ["colleague-1", "colleague-2"])
        self.assertEqual(self.owner_of("colleague-2"), COLLEAGUE)
        self.assertEqual(self.owner_of("colleague-1"), None)
        svc.close()
        self.begin()
        self.assertIsNone(self.owner_of("colleague-1"))
        self.assertEqual(self.owner_of("colleague-2"), COLLEAGUE)

    def test_a_row_that_recorded_no_directory_gives_the_colleague_no_write(self):
        svc = self.begin()
        (self.profiles / "colleague-1").mkdir(mode=0o700)
        with svc._ingest:
            svc._fold(svc.log.append([account_add.added("colleague-1", by=COLLEAGUE)]))
        svc.poll_sessions()
        theirs = guest.GuestActor(COLLEAGUE, TAILNET, svc._guest_epoch)
        with self.assertRaises(sprints.Refused) as raised:
            svc.start_signin("colleague-1", by=theirs)
        self.assertEqual(str(raised.exception), guest.NO_OWN_SIGNIN_TEXT)
        self.assertEqual(self.clients(), [])
        self.assertEqual(self.add()[0], 200)
        self.assertEqual(self.names(), {"work", "colleague-1", "colleague-2"})
        self.assertEqual([line["account"] for line in self.clients()], ["colleague-2"])

    def test_a_second_add_waits_for_the_first_to_grant_the_folder_trust(self):
        repo = self.root / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True, stdin=subprocess.DEVNULL)
        entered, release = threading.Event(), threading.Event()
        real = self.granter

        def gated(path, key):
            entered.set()
            release.wait(10)
            return real(path, key)
        self.granter = gated
        self.begin()
        support.write_registry(self.registry, [{"project_id": "repo", "root": str(repo)}])
        answers = []
        first = threading.Thread(target=lambda: answers.append(self.add()), daemon=True)
        first.start()
        self.assertTrue(entered.wait(10))
        second = threading.Thread(target=lambda: answers.append(self.add()), daemon=True)
        second.start()
        second.join(1.5)
        self.assertTrue(second.is_alive(), "the second add did not wait for the grant")
        self.assertEqual(self.clients(), [])
        release.set()
        first.join(10)
        second.join(10)
        self.assertEqual(sorted(status for status, _ in answers), [200, 200])
        self.assertEqual(self.names(), {"work", "colleague-1"})
        self.assertEqual(len(self.clients()), 1)

    def test_a_live_sign_in_code_or_cancel_is_refused_once_the_owner_replaced_the_profile(self):
        svc = self.begin()
        self.assertEqual(self.add()[0], 200)
        attempt = self.shown_attempt()
        self.replace_dir("colleague-1")
        fixed = (409, guest.NO_OWN_SIGNIN_TEXT.encode() + b"\n")
        self.assertEqual(self.post(CODE_ROUTE, {"attempt": attempt, "code": CODE}), fixed)
        self.assertEqual(self.post(CANCEL, {"attempt": attempt}), fixed)
        self.assertEqual(self.code_records(), [])
        self.assertEqual(svc._signin_runs.running(), {"colleague-1"})

    def test_a_launcher_that_fails_after_the_directory_exists_leaves_it_unowned_and_the_retry_grants_a_new_one(self):
        repo = self.root / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True, stdin=subprocess.DEVNULL)
        svc = self.begin()
        support.write_registry(self.registry, [{"project_id": "repo", "root": str(repo)}])

        def killed(name):
            raise OSError("the process ended")
        self.after_add = killed
        self.assertEqual(self.add()[0], 500)
        self.assertEqual(self.names(), {"work", "colleague-1"})
        self.assertEqual(self.added_rows(), [])
        svc.poll_sessions()
        self.after_add = None
        self.assertEqual(self.add()[0], 200)
        self.assertEqual(self.names(), {"work", "colleague-1", "colleague-2"})
        self.assertEqual(self.added, ["colleague-1", "colleague-2"])
        self.assertEqual(self.added_rows(), [{"by": COLLEAGUE, "profile": "colleague-2"}])
        self.assertIsNone(self.owner_of("colleague-1"))
        self.assertEqual([line["account"] for line in self.clients()], ["colleague-2"])
        self.assertIn("colleague-2", self.granted)
        self.assertNotIn("colleague-1", self.granted)

    def test_a_profile_whose_credential_slot_is_not_fresh_is_never_his(self):
        # A reused name can find the launcher's keychain entry of a profile the owner removed with the CLI.
        self.begin()
        self.status_of["colleague-1"] = signin.Status("signed_in", None, "someone@corp-zq.invalid")
        status, body = self.add()
        self.assertEqual((status, body), (502, b"the account could not be created: not_listed\n"))
        self.assertEqual(self.added_rows(), [])
        self.no_sign_in_started()
        self.read_error["colleague-2"] = signin.StatusFailed("unreadable")  # a read that fails proves nothing
        self.assertEqual(self.add()[0], 502)
        self.assertEqual(self.added_rows(), [])
        self.no_sign_in_started()
        del self.read_error["colleague-2"]
        self.assertEqual(self.add()[0], 200)
        self.assertEqual(self.added, ["colleague-1", "colleague-2", "colleague-3"])
        self.assertEqual(self.added_rows(), [{"by": COLLEAGUE, "profile": "colleague-3"}])
        self.assertIsNone(self.owner_of("colleague-1"))
        self.assertIsNone(self.owner_of("colleague-2"))
        self.assertEqual(self.owner_of("colleague-3"), COLLEAGUE)
        self.assertEqual([line["account"] for line in self.clients()], ["colleague-3"])

    def test_an_add_whose_marker_could_not_be_written_is_refused_whatever_marker_is_found_later(self):
        self.begin()
        self.after_add = lambda name: (self.profiles / name / account_add.MARKER).write_text("a" * 32)
        status, body = self.add()
        self.assertEqual((status, body), (502, b"the account could not be created: not_listed\n"))
        self.assertEqual(self.added_rows(), [])
        self.no_sign_in_started()
        self.after_add = None
        self.assertEqual(self.add()[0], 200)
        self.assertEqual(self.added_rows(), [{"by": COLLEAGUE, "profile": "colleague-2"}])
        self.assertIsNone(self.owner_of("colleague-1"))
        self.assertEqual(self.owner_of("colleague-2"), COLLEAGUE)
        self.assertEqual([line["account"] for line in self.clients()], ["colleague-2"])

    def test_with_no_other_profile_listed_a_listing_that_fails_after_the_launcher_leaves_the_profile_unowned(self):
        shutil.rmtree(self.profiles / "work")
        self.begin()

        def unreadable(name):
            self.list_error = OSError("cannot list")
        self.after_add = unreadable
        self.assertEqual(self.add()[0], 502)
        self.list_error = None
        self.after_add = None
        self.assertEqual(self.add()[0], 200)
        self.assertEqual(self.names(), {"colleague-1", "colleague-2"})
        self.assertEqual(self.added_rows(), [{"by": COLLEAGUE, "profile": "colleague-2"}])
        self.assertIsNone(self.owner_of("colleague-1"))
        self.assertEqual(self.owner_of("colleague-2"), COLLEAGUE)

    def test_a_link_fetched_for_a_profile_replaced_while_it_was_awaited_is_refused(self):
        svc = self.begin()
        runs = svc._signin_runs
        awaited = runs.wait_link

        def wait_then_replace(profile):
            link = awaited(profile)
            self.replace_dir(profile)
            return link
        runs.wait_link = wait_then_replace
        status, body = self.add()
        self.assertEqual((status, body), (409, guest.NO_OWN_SIGNIN_TEXT.encode() + b"\n"))
        self.assertNotIn(b"https", body)

    def test_a_link_retry_for_a_profile_replaced_while_it_was_awaited_is_refused(self):
        svc = self.begin()
        first = json.loads(self.add()[1])["attempt"]
        runs = svc._signin_runs
        awaited = runs.wait_link

        def wait_then_replace(profile):
            link = awaited(profile)
            self.replace_dir(profile)
            return link
        runs.wait_link = wait_then_replace
        status, body = self.post(ADD, {"consent": True, "attempt": first})
        self.assertEqual((status, body), (409, guest.NO_OWN_SIGNIN_TEXT.encode() + b"\n"))
        self.assertNotIn(b"https", body)

    def test_a_link_fetched_after_the_run_ended_is_refused(self):
        svc = self.begin()
        runs = svc._signin_runs
        awaited = runs.wait_link

        def wait_then_end(profile):
            link = awaited(profile)
            with svc._ingest:
                del svc._signin_live[profile]  # what the run's end callback does
            return link
        runs.wait_link = wait_then_end
        status, body = self.add()
        self.assertEqual((status, body), (409, guest.NO_OWN_SIGNIN_TEXT.encode() + b"\n"))
        self.assertNotIn(b"https", body)

    def test_a_link_fetched_while_the_ended_clients_final_read_runs_is_refused(self):
        svc = self.begin()
        runs = svc._signin_runs
        awaited = runs.wait_link

        def wait_then_end(profile):
            link = awaited(profile)
            runs.send_code(profile, CODE)  # the fake client exits on a code
            end = time.monotonic() + 10
            while profile in runs.running() and time.monotonic() < end:
                time.sleep(0.02)
            return link
        runs.wait_link = wait_then_end
        self.end_gate.clear()  # the end callback, which clears the live attempt, waits behind its final read
        try:
            status, body = self.add()
            with svc._ingest:
                held = dict(svc._signin_live)
        finally:
            self.end_gate.set()
        self.assertEqual((status, body), (409, guest.NO_OWN_SIGNIN_TEXT.encode() + b"\n"))
        self.assertIn("colleague-1", held)
        self.assertNotIn(b"https", body)

    def test_a_link_retry_names_the_shown_attempt_and_creates_and_starts_nothing(self):
        self.environ["FAKE_MODE"] = "nolink"
        del self.environ["FAKE_MANUAL"]
        self.link_wait = 0.5
        self.begin()
        first = json.loads(self.add()[1])
        self.assertEqual((first["link"], first["route"]), (None, None))
        status, body = self.post(ADD, {"consent": True, "attempt": first["attempt"]})
        self.assertEqual((status, json.loads(body)["attempt"]), (200, first["attempt"]))
        self.assertEqual(self.names(), {"work", "colleague-1"})
        self.assertEqual(self.added, ["colleague-1"])
        self.assertEqual(len(self.clients()), 1)
        self.assertEqual([row["action"] for row in self.acted()], ["start"])

    def test_a_link_retry_for_an_attempt_that_is_over_creates_no_other_account(self):
        self.begin()
        first = json.loads(self.add()[1])["attempt"]
        self.signed_in("colleague-1")
        fixed = (409, guest.NO_OWN_SIGNIN_TEXT.encode() + b"\n")
        self.assertEqual(self.post(ADD, {"consent": True, "attempt": first}), fixed)
        self.assertEqual(self.post(ADD, {"consent": True, "attempt": first + 1000}), fixed)
        self.assertEqual(self.post(ADD, {"consent": True, "attempt": first}, SECOND), fixed)
        self.assertEqual(self.names(), {"work", "colleague-1"})
        self.assertEqual(self.added, ["colleague-1"])
        self.assertEqual(len(self.clients()), 1)
        self.assertEqual(self.post(ADD, {"consent": False, "attempt": first})[1],
                         guest.CONSENT_TEXT.encode() + b"\n")

    def own_signin_attempt(self):
        return self.guest_view()["own_signin"]["attempt"]

    def removed_and_made_again(self):
        svc = self.begin()
        self.assertEqual(self.add()[0], 200)
        self.cancelled()
        return svc

    def test_a_profile_the_owner_removed_and_made_again_is_no_longer_his(self):
        svc = self.removed_and_made_again()
        svc.remove_account("colleague-1", "colleague-1")
        (self.profiles / "colleague-1").mkdir()
        svc.poll_sessions()
        self.assertIsNone(self.owner_of("colleague-1"))
        self.assertEqual([row for row in self.guest_view()["pool"]["accounts"]
                          if row["label"] == "yours"], [])
        self.assertEqual(self.add()[0], 200)
        self.assertEqual(self.names(), {"work", "colleague-1", "colleague-2"})
        self.assertEqual([line["account"] for line in self.clients()],
                         ["colleague-1", "colleague-2"])
        self.now[0] += 91 * 86400
        svc.retain()
        svc.close()
        self.begin()
        self.assertIsNone(self.owner_of("colleague-1"))

    def test_a_failed_removal_leaves_the_profile_his(self):
        svc = self.removed_and_made_again()
        self.remove_fails = True
        with self.assertRaises(account_remove.RemoveFailed):
            svc.remove_account("colleague-1", "colleague-1")
        self.assertEqual(self.owner_of("colleague-1"), COLLEAGUE)
        self.now[0] += 91 * 86400
        svc.retain()
        svc.close()
        self.begin()
        self.assertEqual(self.owner_of("colleague-1"), COLLEAGUE)

    def test_a_colleague_cannot_read_a_credential_or_a_sign_in_output(self):
        self.begin()
        owner_only = guest.OWNER_ONLY_TEXT.encode() + b"\n"
        for path in ("/api/profile", "/api/excluded", "/spend"):
            with self.subTest(path=path):
                status, _, body = self.get(path)
                self.assertEqual((status, body), (403, owner_only))
        self.assertEqual(self.post(service.SIGNIN_LINK_PATH, {"profile": "colleague-1"}),
                         (403, owner_only))

    def test_a_start_without_the_tick_creates_and_starts_nothing(self):
        self.begin()
        self.assertEqual(self.post(ADD, {"consent": False}),
                         (409, guest.CONSENT_TEXT.encode() + b"\n"))
        for body in ({}, {"consent": "true"}, {"consent": True, "profile": "work"}):
            with self.subTest(body=body):
                self.assertEqual(self.post(ADD, body), (400, b"bad account\n"))
        self.nothing_started()
        self.assertFalse(self.record.exists())
        self.assertEqual(self.names(), {"work"})

    def test_a_colleague_removed_before_the_add_creates_nothing(self):
        svc = self.begin()
        self.in_flight(svc, lambda: svc.remove_colleague(COLLEAGUE))
        status, body = self.add()
        self.assertIn((status, body.decode().strip()),
                      ((403, guest.NOT_SHARED_TEXT), (409, guest.NOT_SHARED_TEXT),
                       (409, guest.REVOKED_TEXT), (403, guest.REVOKED_TEXT)))
        self.assertEqual(self.added, [])
        self.assertEqual(self.names(), {"work"})

    def test_a_colleague_removed_during_the_add_keeps_the_created_profile_and_starts_nothing(self):
        svc = self.begin()
        self.after_add = lambda name: svc.remove_colleague(COLLEAGUE)
        status, body = self.add()
        self.assertEqual(status, 409)
        self.assertIn(body.decode().strip(), (guest.REVOKED_TEXT, guest.NOT_SHARED_TEXT))
        self.assertEqual(self.names(), {"work", "colleague-1"})
        self.assertEqual(self.added_rows(), [{"by": COLLEAGUE, "profile": "colleague-1"}])
        self.assertEqual(self.acted(), [])
        self.assertEqual(self.clients(), [])
        self.assertEqual(self.owner_of("colleague-1"), COLLEAGUE)

    def test_a_code_or_cancel_after_the_client_ended_is_refused_in_fixed_words(self):
        svc = self.begin()
        self.assertEqual(self.add()[0], 200)
        self.end_gate.clear()
        try:
            attempt = self.shown_attempt()
            self.assertEqual(self.post(CODE_ROUTE, {"attempt": attempt, "code": CODE})[0], 204)
            until(self, lambda: "colleague-1" not in svc._signin_runs.running())
            fixed = (409, guest.NO_OWN_SIGNIN_TEXT.encode() + b"\n")
            for route, body in ((CODE_ROUTE, {"attempt": attempt, "code": CODE}),
                                (CANCEL, {"attempt": attempt})):
                with self.subTest(route=route):
                    got = self.post(route, body)
                    self.assertEqual(got, fixed)
                    self.assertNotIn(b"colleague-1", got[1])
        finally:
            self.end_gate.set()

    def test_the_owners_port_takes_no_guest_account_write(self):
        svc = self.begin()
        page = {"Origin": f"http://127.0.0.1:{svc.address[1]}", **JSON}
        for route in ROUTES:
            payload = json.dumps(VALID[route]).encode()
            with self.subTest(route=route):
                got = self.unchanged(svc, lambda: support.post_page(
                    svc.address, route, {**page, "X-Console-Token": self.owner_token()}, payload))
                self.assertEqual((got[0], got[2]), (404, b"not found\n"))
                got = self.unchanged(svc, lambda: support.post_page(
                    svc.address, route, page, payload))
                self.assertEqual((got[0], got[2]), (403, b"token refused\n"))
        self.nothing_started()

    def test_the_owners_port_refuses_each_guest_account_write_before_reading_its_body(self):
        svc = self.begin()
        for route in ROUTES:
            with self.subTest(route=route), socket.create_connection(svc.address, timeout=5) as sock:
                sock.sendall((
                    f"POST {route} HTTP/1.1\r\nHost: 127.0.0.1:{svc.address[1]}\r\n"
                    f"Origin: http://127.0.0.1:{svc.address[1]}\r\n"
                    f"X-Console-Token: {self.owner_token()}\r\n"
                    "Content-Type: application/json\r\nContent-Length: 64\r\n\r\n").encode())
                answer = b""
                while b"not found\n" not in answer:
                    got = sock.recv(4096)
                    if not got:
                        break
                    answer += got
                self.assertTrue(answer.startswith((b"HTTP/1.0 404", b"HTTP/1.1 404")), answer)
                self.assertTrue(answer.endswith(b"not found\n"), answer)
        self.nothing_started()

    def test_no_guest_account_refusal_or_stderr_line_names_a_login_or_a_profile(self):
        self.begin()
        with stderr_text() as err:
            self.post(ADD, {"consent": False})
            self.post(ADD, {})
            self.post(ADD, {"consent": True}, STRANGER)
            self.post(CODE_ROUTE, VALID[CODE_ROUTE], SECOND)
            self.post(CANCEL, VALID[CANCEL], SECOND)
            self.add_error = account_add.AddFailed("failed")
            failed = self.add()
            self.assertEqual(failed[0], 502)
            self.add_error = None
            self.registry.write_text("not json")
            self.read_error["colleague-2"] = signin.StatusFailed("boom")
            self.assertEqual(self.add()[0], 502)  # a failed status read proves no fresh slot, so the add is refused
            self.assertEqual(self.add()[0], 200)
            self.sent_code()
            until(self, lambda: self.own_state() == "failed")
        for status, headers, body in self.responses:
            for word in (COLLEAGUE, SECOND, "colleague-1", "colleague-2", "colleague-3", "work"):
                self.assertNotIn(word.encode(), body)
        for word in (COLLEAGUE, SECOND, "colleague-1", "colleague-2", "colleague-3", "work"):
            self.assertNotIn(word, err.text)
        self.assertIn("signin_add_read_failed boom", err.text)
        self.assertIn("trust_account_registry_unreadable", err.text)

    def test_a_failed_trust_grant_or_a_refused_link_of_his_own_profile_names_nothing(self):
        repo = self.root / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True, stdin=subprocess.DEVNULL)
        self.grant_error = OSError("planted-grant-failure")
        self.environ["FAKE_LINK"] = "javascript:SENTINEL-BAD"
        del self.environ["FAKE_MANUAL"]
        self.link_wait = 0.5
        self.begin()
        support.write_registry(self.registry, [{"project_id": "repo", "root": str(repo)}])
        with stderr_text() as err:
            self.assertEqual(self.add()[0], 200)
        for word in (COLLEAGUE, SECOND, "colleague-1", "colleague-2", "work"):
            self.assertNotIn(word, err.text)
        self.assertIn("console: trust_grant_error OSError", err.text)
        self.assertIn("console: signin_link_refused\n", err.text)
        self.assertNotIn("planted-grant-failure", err.text)


class GuestAccountTextTest(unittest.TestCase):
    def test_only_the_guest_texts_pass_through(self):
        for text in (guest.CONSENT_TEXT, guest.NO_OWN_SIGNIN_TEXT, guest.ACCOUNT_BUSY_TEXT,
                     guest.ACCOUNT_UNAVAILABLE_TEXT, guest.NOT_SHARED_TEXT, guest.REVOKED_TEXT):
            with self.subTest(text=text):
                self.assertEqual(guest.account_text(text), text)
        self.assertEqual(guest.account_text("no sign-in is running for work"),
                         guest.ACCOUNT_BUSY_TEXT)
        self.assertEqual(guest.account_text(account_remove.removing("work")),
                         guest.ACCOUNT_BUSY_TEXT)


class GuestAccountSecrecyTest(GuestAccountCase):
    def test_no_guest_response_of_the_flow_carries_a_credential_or_the_clients_output(self):
        self.environ.update(FAKE_BAD=PLANTED, FAKE_NOISE="SENTINEL-OUT-noise")

        def plant(name):
            (self.profiles / name / ".credentials.json").write_text(json.dumps(
                {"claudeAiOauth": {"accessToken": PLANTED, "refreshToken": PLANTED}}))
        self.after_add = plant
        svc = self.begin()
        self.get("/")
        added = self.add()
        self.assertEqual(added[0], 200)
        self.assertEqual(json.loads(added[1])["link"], MANUAL_LINK)
        self.get("/api/state")
        self.assertEqual(json.loads(self.add()[1])["link"], MANUAL_LINK)
        self.status_of["colleague-1"] = signin.Status(
            "signed_in", None, "planted-zq@corp-zq.invalid")
        self.sent_code()
        until(self, lambda: self.own_state() == "signed_in")
        self.get("/api/state")
        stream = self.open_stream(svc)
        self.responses.append((200, dict(stream.getheaders()), next_frame(stream)))
        self.add()
        self.cancelled()
        self.post(ADD, {"consent": False})
        self.post(ADD, {})
        self.post(CODE_ROUTE, VALID[CODE_ROUTE], SECOND)
        self.post(CANCEL, VALID[CANCEL], SECOND)
        # The first response is the guest page, which carries the guest write token by design (ADR-console-066, the
        # guest page contract); AC3 covers the owner's token, a credential and the client's output in every response
        # and the guest token in every response of the account API.
        page, *api = self.responses
        self.assertIn(self.guest_token().encode(), page[2])
        for status, headers, body in api:
            blob = (str(status) + json.dumps(headers)).encode() + body
            with self.subTest(status=status, word="the guest token"):
                self.assertNotIn(self.guest_token().encode(), blob)
        for status, headers, body in self.responses:
            blob = (str(status) + json.dumps(headers)).encode() + body
            for word in (PLANTED, "SENTINEL-OUT", "SENTINEL-ERR", self.owner_token(),
                         "planted-zq", "colleague-1", CODE):
                with self.subTest(status=status, word=word):
                    self.assertNotIn(word.encode(), blob)
        self.assertGreaterEqual(len(self.responses), 10)


if __name__ == "__main__":
    unittest.main()
