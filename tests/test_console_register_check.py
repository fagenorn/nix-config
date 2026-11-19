"""The host check that registers a throwaway project from the page and restores the registry (#1052).

Each case has its own HOME, so no case shares a registry, a plan store or an event log with another.

Run: just agent-workflow-tests
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
import unittest.mock
from pathlib import Path

from agent_tools.console import approve, event_log, folder_trust, register, register_check
from agent_tools.console.view import derive_view
from agent_tools.project_contract import agent_platform

from . import accounts_sandbox
from . import console_test_support as support
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1052)
from .test_console_register_service import Fake

ROOT = Path(__file__).resolve().parent.parent
CONTRACT = str(ROOT / register_check.CONTRACT_SOURCE)
WRAPPER = ROOT / "home/common/verify-pending/checks/console-register"


def view(registration):
    return 200, json.dumps({"registration": registration, "entries": []}).encode()


T = "2026-11-19T17:00:00+00:00"
DISMISSED = {"root": "/elsewhere/r", "status": "done", "result": "failed",
             "note": register.LATER_NOTE, "at": T}


def open_documents() -> dict:
    """The views the owner's page shows for an open registration, derived by the console's own code."""
    ready = {**register.DEFAULTS, "root": "/elsewhere/r", "project_id": None, "result": "planned",
             "outcome": "changes", "headline": "What adopting r would change.",
             "lines": ["writes the project contract"], "note": "The plan is ready.",
             "plan_id": "P", "state": "ready", "questions": [], "remote": None, "at": T}
    waiting = {**register.DEFAULTS, "root": "/elsewhere/r", "project_id": None,
               "result": "not_registered", "outcome": "no_change",
               "headline": "r is already adopted and is not registered yet.", "lines": [],
               "note": register.CONFIRM_NOTE, "at": T}
    draft = {**ready, "state": "draft", "note": "The plan is a draft."}
    return {
        "running": derive_view([], registration=register.view_entry("/elsewhere/r", None)),
        "register card": derive_view(
            [], registration=register.view_entry(None, waiting),
            confirm_items=register.confirm_items(waiting, running=False)),
        "apply card": derive_view(
            [], registration=register.view_entry(None, ready),
            apply_items=approve.apply_items(ready, None, None, "approve", deferred=set())),
        "ended and shown": derive_view([], registration=register.view_entry(None, draft)),
    }


def sent(document) -> tuple:
    return 200, json.dumps(document).encode()


def seeded(entries) -> bytes:
    agent_platform.write_registry(entries)
    return agent_platform.registry_path().read_bytes()


class Case(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp(dir=accounts_sandbox.root())).resolve()
        previous = os.environ["HOME"]
        os.environ["HOME"] = str(self.home)
        self.addCleanup(os.environ.__setitem__, "HOME", previous)
        self.addCleanup(shutil.rmtree, self.home, True)
        share = self.home / ".agents/share"
        share.mkdir(parents=True)
        shutil.copy(ROOT / "home/common/agent-skills/platform-manifest.json",
                    share / "platform-manifest.json")
        self.tmp_root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp_root, True)

    def token(self):
        path = agent_platform.state_root() / "console" / "page-token"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("t" * 43 + "\n")

    def run_check(self, argv, **kwargs):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = register_check.main(argv, tmp_root=self.tmp_root, **kwargs)
        lines = out.getvalue().splitlines()
        self.assertEqual(len(lines), 1)
        return code, json.loads(lines[0])


class RealConsoleTest(Case):
    PID = "console-check/register-real"

    def arrange(self):
        """A registry with one project and one profile; what the test needs of them."""
        keep = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, keep, True)
        seeded([{"project_id": "owner/keep", "root": str(keep)}])
        self.keep = keep
        self.store = agent_platform.state_root() / "console" / "events.sqlite3"
        accounts = self.home / "accounts"
        self.work = accounts / "profiles" / "work"
        self.work.mkdir(parents=True)
        self.arranged = {"oauthAccount": {"a": 1}}
        (self.work / ".claude.json").write_text(json.dumps(self.arranged), "utf-8")
        patched = unittest.mock.patch.dict(os.environ, {"CLAUDE_ACCOUNTS_DIR": str(accounts)})
        patched.start()
        self.addCleanup(patched.stop)

    def own_registration(self):
        """The owner's dismissed registration, in the log before the service starts; its entry."""
        other = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, other, True)
        self.store.parent.mkdir(parents=True, exist_ok=True)
        log = event_log.EventLog(self.store)
        log.append([register.ended(register.dismissed(register.failed(str(other), "failed")))])
        log.close()
        return other

    def shown(self, svc):
        return json.loads(support.request(svc.address, "GET", "/api/state")[2])["registration"]

    def service(self, **kwargs):
        return support.service(self, self.store, agent_platform.registry_path(),
                               dispatch=None, profile_dirs=[self.work], trust_home=self.home,
                               **kwargs)

    def check(self, svc, **kwargs):
        return self.run_check(
            ["--url", f"http://127.0.0.1:{svc.address[1]}", "--contract", CONTRACT,
             "--wait", "120"], **kwargs)

    def test_the_check_registers_then_restores_the_registry(self):
        self.arrange()
        svc = self.service(adopter=register.Adopter())
        code, out = self.check(svc)
        self.assertEqual((code, out["status"], out["restored"]), (0, "met", True))
        registry = json.loads(agent_platform.registry_path().read_text())
        self.assertEqual(registry["projects"],
                         [{"project_id": "owner/keep", "root": str(self.keep)}])
        self.assertFalse(Path(out["root"]).exists())
        self.assertEqual(list(self.tmp_root.iterdir()), [])
        for plan in (agent_platform.state_root() / "adopt/plans").glob("*.json"):
            handoff = json.loads(plan.read_text()).get("handoff", {})
            self.assertNotEqual(handoff.get("repo_root"), out["root"])
        results = [json.loads(row[4])["result"] for row in support.log_rows(self.store)
                   if row[2] == "registration.ended"]
        self.assertIn("registered", results)
        (grant,) = [json.loads(row[4]) for row in support.log_rows(self.store)
                    if row[2] == "trust.granted"]
        self.assertEqual(grant["cause"], "register")
        key = os.path.realpath(out["root"])
        for path, expected in ((self.work / ".claude.json", self.arranged),
                               (self.home / ".claude.json", {})):
            document = json.loads(path.read_text("utf-8"))
            self.assertNotIn(key, document.pop("projects", {}))
            self.assertEqual(document, expected)

    def test_the_registration_shown_before_the_run_is_shown_after_it(self):
        self.arrange()
        other = self.own_registration()
        svc = self.service(adopter=register.Adopter(), poll_seconds=3600)
        shown = self.shown(svc)
        self.assertEqual(shown["root"], str(other))
        self.assertEqual(shown["note"], register.LATER_NOTE)
        seen, stale = [], []

        def fetch(url):
            holds = any(entry["project_id"] == self.PID for entry in
                        register_check.service.read_fleet(agent_platform.registry_path()) or [])
            if holds:
                seen.append(True)
            answer = register_check.default_fetch(url)
            if seen and not holds and not stale and not any(self.tmp_root.iterdir()):
                stale.append(json.loads(answer[1]))
                svc.refresh()
            return answer

        code, out = self.check(svc, project_id=self.PID, fetch=fetch, poll=0.05)
        self.assertEqual((code, out["status"]), (0, "met"))
        self.assertEqual(len(stale), 1)
        self.assertNotEqual(stale[0]["registration"], shown)
        self.assertEqual(self.shown(svc), shown)

    def test_a_failed_run_gives_the_page_back_the_registration_it_ran_over(self):
        self.arrange()
        self.own_registration()
        adopter = Fake(raises=register.RunFailed("timed_out"))
        svc = self.service(adopter=adopter)
        shown = self.shown(svc)
        code, out = self.check(svc, project_id=self.PID, poll=0.05)
        self.assertEqual((code, out["status"]), (1, "not_met"))
        self.assertTrue(out["reason"].startswith("The adoption plan for repo failed"))
        self.assertEqual(self.shown(svc), shown)
        (cancel,) = [json.loads(row[4]) for row in support.log_rows(self.store)
                     if row[2] == "registration.cancelled"]
        self.assertTrue(cancel["restore"])
        self.assertEqual(cancel["root"], adopter.calls[0][1])


class SettleTest(Case):
    PID = "console-check/register-test"

    def late_writer(self, root_box, written):
        def late():
            with agent_platform.registry_transaction() as entries:
                agent_platform.write_registry(
                    [*entries, {"project_id": self.PID, "root": root_box[0]}])
            plans = agent_platform.state_root() / "adopt/plans"
            plans.mkdir(parents=True, exist_ok=True)
            (plans / "late.json").write_text(json.dumps({"handoff": {"repo_root": root_box[0]}}))
            written.set()
        return late

    def late_run(self, status, cancel_status=204, shown=5, trust=False):
        keep = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, keep, True)
        before = seeded([{"project_id": "owner/keep", "root": str(keep)}])
        self.token()
        root_box, written, timers = [None], threading.Event(), []
        cancels, checks, gone = [], [], threading.Event()

        def post(url, headers, body):
            if url.endswith("/api/register-cancel"):
                cancels.append((json.loads(body), dict(headers)))
                if cancel_status == 204:
                    gone.set()
                return cancel_status, b""
            if url.endswith("/api/trust-check"):
                checks.append(json.loads(body))
                return 204, b""
            root_box[0] = json.loads(body)["path"]
            timer = threading.Timer(1.0, self.late_writer(root_box, written))
            timers.append(timer)
            timer.start()
            return status, b""

        def fetch(url):
            if root_box[0] is None:
                return view(None)
            if not written.is_set():
                return view({"root": root_box[0], "status": "running", "result": None,
                             "headline": "Planning…"})
            if gone.is_set():
                return view(None)
            document = {"registration": {
                "root": root_box[0], "status": "done", "result": "not_registered",
                "headline": "r was not registered: x", "cancel": True,
                "at": "2026-11-15T08:00:00+00:00"}, "entries": []}
            if trust:
                document["inbox"] = {"open": [{"reason": "trust_failed", "root": root_box[0],
                                               "profile": "work"}]}
            return sent(document)

        code, out = self.run_check(["--wait", "0.2", "--contract", CONTRACT], fetch=fetch,
                                   post=post, project_id=self.PID, poll=0.05, settle=30,
                                   shown=shown)
        for timer in timers:
            timer.join()
        self.root_box, self.cancels, self.checks = root_box, cancels, checks
        self.assertEqual(agent_platform.registry_path().read_bytes(), before)
        self.assertFalse((agent_platform.state_root() / "adopt/plans/late.json").exists())
        self.assertEqual(list(self.tmp_root.iterdir()), [])
        if cancel_status == 204:
            self.assertEqual((code, out["status"], out["reason"]), (1, "not_met", "no result"))
        return code, out

    def test_a_late_write_is_restored_because_the_check_waits_for_the_run(self):
        self.late_run(204)

    def test_a_failed_run_cancels_its_own_registration(self):
        self.late_run(204)
        self.assertEqual([body for body, _ in self.cancels],
                         [{"root": self.root_box[0], "restore": True}])
        headers = self.cancels[0][1]
        self.assertEqual(headers["Origin"], "http://127.0.0.1:27184")
        self.assertEqual(headers[register_check.write_guard.TOKEN_HEADER], "t" * 43)
        self.assertEqual(headers["Content-Type"], "application/json")

    def test_a_failed_run_left_shown_keeps_its_verdict(self):
        code, out = self.late_run(204, cancel_status=409, shown=0.3)
        self.assertEqual((code, out), (1, {
            "status": "not_restored", "leftovers": ["registration"],
            "verdict": {"status": "not_met", "reason": "no result"}}))
        self.assertEqual(len(self.cancels), 1)

    def test_a_trust_card_its_cancel_removed_is_not_a_leftover(self):
        code, out = self.late_run(204, trust=True)
        self.assertEqual((code, out), (1, {"status": "not_met", "reason": "no result"}))
        self.assertEqual(len(self.checks), 1)
        self.assertEqual(len(self.cancels), 1)

    def test_an_unanswered_post_still_waits_for_the_run(self):
        self.late_run(None)

    def test_a_run_that_never_settles_is_left_and_named(self):
        before = seeded([])
        self.token()
        root_box = [None]

        def post(url, headers, body):
            root_box[0] = json.loads(body)["path"]
            return 204, b""

        def fetch(url):
            if root_box[0] is None:
                return view(None)
            return view({"root": root_box[0], "status": "running", "result": None,
                         "headline": "Planning…"})

        code, out = self.run_check(["--wait", "0.1", "--contract", CONTRACT], fetch=fetch,
                                   post=post, project_id=self.PID, poll=0.05, settle=0.3)
        self.assertEqual(code, 1)
        self.assertEqual(out, {"project_id": self.PID, "root": root_box[0],
                               "status": "unsettled"})
        self.assertTrue(Path(root_box[0]).exists())
        self.assertEqual(agent_platform.registry_path().read_bytes(), before)

    def test_the_default_wait_covers_the_console_run(self):
        self.assertEqual(register_check.SETTLE_SECONDS,
                         2 * register.RUN_TIMEOUT + register.GIT_TIMEOUT + 60)
        self.assertEqual(register_check.parser().parse_args([]).wait,
                         register_check.SETTLE_SECONDS)
        self.assertGreater(register_check.POST_TIMEOUT, register.GIT_TIMEOUT)
        self.assertEqual(register_check.SHOWN_SECONDS, 30)


class RestoreTest(Case):
    PID = "console-check/register-leftover"

    def registered_run(self, cards=(), stays=False, left=False, final=None):
        """A stubbed console that registers, leaving one stored plan behind; the output.

        `cards` are the profiles whose Check again card the run left for the fixture's root, plus
        one card of another root; a trust check clears the fixture's unless `stays`. Confirming
        registers the fixture's project; with `left` the page then keeps showing a done registration
        of it, and with `final` the page answers that once the registry no longer holds it.
        """
        seeded([])
        self.token()
        box = [None]
        plans = agent_platform.state_root() / "adopt/plans"
        self.plan = plans / "leftover.json"

        self.posts = posts = []
        confirmed = []

        checked = []

        def post(url, headers, body):
            posts.append((url.rsplit("/", 1)[-1], json.loads(body)))
            if url.endswith("/api/trust-check"):
                checked.append(json.loads(body)["profile"])
                return 204, b""
            if url.endswith("/api/register-confirm"):
                confirmed.append(True)
                agent_platform.write_registry([{"project_id": self.PID, "root": box[0]}])
                return 204, b""
            box[0] = json.loads(body)["path"]
            plans.mkdir(parents=True, exist_ok=True)
            self.plan.write_text(json.dumps({"handoff": {"repo_root": box[0]}}))
            return 204, b""

        def fetch(url):
            if box[0] is None:
                return view(None)
            holds = any(entry["project_id"] == self.PID for entry in
                        register_check.service.read_fleet(agent_platform.registry_path()) or [])
            if final is not None and confirmed and not holds:
                return 200, final
            registration = {
                "root": box[0], "status": "done", "result": "registered", "note": None,
                "cancel": False, "at": "2026-11-15T08:01:00+00:00"} if confirmed and left else (
                None if confirmed else {
                "root": box[0], "status": "done", "result": "not_registered",
                "outcome": "no_change",
                "headline": "r is already adopted and is not registered yet.",
                "line": "Register r: needs you", "lines": [], "note": None, "adoption": None,
                "at": "2026-11-15T08:00:00+00:00"})
            key = os.path.realpath(box[0])
            open_cards = [{"reason": "trust_failed", "root": "/elsewhere", "profile": "other"}]
            if not confirmed:
                open_cards.append({"reason": "register_confirm", "root": box[0]})
            if stays or not checked:
                open_cards += [{"reason": "trust_failed", "root": key, "profile": name}
                               for name in cards]
            return 200, json.dumps({
                "registration": registration,
                "entries": [{"project_id": self.PID}] if holds else [],
                "inbox": {"open": open_cards}}).encode()

        return self.run_check(["--wait", "1", "--contract", CONTRACT], fetch=fetch, post=post,
                              project_id=self.PID, poll=0.05, settle=5, shown=0.3)

    def test_a_registration_left_shown_is_not_restored_and_named(self):
        code, out = self.registered_run(left=True)
        self.assertEqual((code, out), (1, {"status": "not_restored",
                                           "leftovers": ["registration"]}))

    def test_a_view_without_its_members_never_proves_the_restore(self):
        code, out = self.registered_run(final=b"{}")
        self.assertEqual((code, out), (1, {"status": "not_restored",
                                           "leftovers": ["registration"]}))

    def test_a_plan_that_cannot_be_deleted_is_not_restored_and_is_named(self):
        real = Path.unlink

        def unlink(path, *args, **kwargs):
            if path.name == "leftover.json":
                raise PermissionError("held")
            return real(path, *args, **kwargs)

        with unittest.mock.patch.object(Path, "unlink", unlink):
            code, out = self.registered_run()
        self.assertEqual(
            (code, out), (1, {"status": "not_restored", "leftovers": [str(self.plan)]}))

    def test_a_directory_that_cannot_be_removed_is_not_restored_and_is_named(self):
        with unittest.mock.patch.object(register_check.shutil, "rmtree"):
            code, out = self.registered_run()
        self.assertEqual(code, 1)
        self.assertEqual(out["status"], "not_restored")
        self.assertEqual(len(out["leftovers"]), 1)
        self.assertTrue(Path(out["leftovers"][0]).is_dir())
        shutil.rmtree(out["leftovers"][0])

    def test_a_clean_restore_is_met(self):
        code, out = self.registered_run()
        self.assertEqual((code, out["status"], out["restored"]), (0, "met", True))
        self.assertFalse(self.plan.exists())
        self.assertEqual([name for name, _ in self.posts],
                         ["register-project", "register-confirm"])
        self.assertEqual(self.posts[1][1], {"root": self.posts[0][1]["path"], "choice": "register"})

    def test_the_check_answers_the_register_card_and_meets_on_the_listed_project(self):
        code, out = self.registered_run()
        self.assertEqual(code, 0)
        self.assertEqual(out["status"], "met")
        posted = self.posts[0][1]["path"]
        self.assertIn(("register-confirm", {"root": posted, "choice": "register"}), self.posts)

    def test_a_trust_card_the_run_left_is_checked_again_before_the_restore(self):
        code, out = self.registered_run(cards=("solo",))
        self.assertEqual((code, out["status"], out["restored"]), (0, "met", True))
        checks = [body for name, body in self.posts if name == "trust-check"]
        self.assertEqual(checks, [{"root": os.path.realpath(self.posts[0][1]["path"]),
                                   "profile": "solo"}])

    def test_a_trust_card_that_stays_is_not_restored_and_is_named(self):
        code, out = self.registered_run(cards=("solo",), stays=True)
        self.assertEqual((code, out), (1, {"status": "not_restored",
                                           "leftovers": ["trust card solo"]}))

    def test_a_trust_entry_that_cannot_be_removed_is_named(self):
        with unittest.mock.patch.object(register_check.folder_trust, "remove_entry",
                                        return_value="failed"):
            code, out = self.registered_run()
        expected = [str(path) for _, path in folder_trust.targets(
            Path.home(), register_check.service.default_profile_dirs())]
        self.assertEqual((code, out), (1, {"status": "not_restored", "leftovers": expected}))


class StubTest(Case):
    def test_a_console_that_does_not_answer_is_not_running(self):
        code, out = self.run_check([], fetch=lambda url: (None, b""))
        self.assertEqual((code, out), (75, {"status": "not_running"}))

    def test_a_console_without_the_member_is_not_deployed(self):
        code, out = self.run_check([], fetch=lambda url: (200, b'{"capacity": {}}'))
        self.assertEqual((code, out), (75, {"status": "not_deployed"}))

    def test_a_busy_console_is_not_yet_and_restores(self):
        before = seeded([{"project_id": "owner/keep", "root": "/somewhere"}])
        self.token()
        code, out = self.run_check(
            ["--contract", CONTRACT], fetch=lambda url: view(None),
            post=lambda url, headers, body: (409, b"a registration is already running for x\n"))
        self.assertEqual((code, out), (75, {"status": "busy"}))
        self.assertEqual(agent_platform.registry_path().read_bytes(), before)
        self.assertEqual(list(self.tmp_root.iterdir()), [])

    def test_another_refusal_is_not_met(self):
        seeded([])
        self.token()
        code, out = self.run_check(
            ["--contract", CONTRACT], fetch=lambda url: view(None),
            post=lambda url, headers, body: (409, b"... is not the top of a git checkout\n"))
        self.assertEqual((code, out["status"]), (1, "not_met"))
        self.assertTrue(out["reason"].startswith("refused 409 "))

    def test_an_open_registration_makes_the_check_busy_and_posts_nothing(self):
        before = seeded([{"project_id": "owner/keep", "root": "/somewhere"}])
        self.token()
        for name, document in open_documents().items():
            with self.subTest(name):
                posts = []

                def post(url, headers, body):
                    posts.append((url, body))
                    return 500, b"posted"

                code, out = self.run_check(["--contract", CONTRACT],
                                           fetch=lambda url, d=document: sent(d), post=post)
                self.assertEqual((code, out), (75, {"status": "busy"}))
                self.assertEqual(posts, [])
                self.assertEqual(list(self.tmp_root.iterdir()), [])
                self.assertEqual(agent_platform.registry_path().read_bytes(), before)

    def test_the_fixtures_of_the_open_states_are_what_the_console_shows(self):
        documents = open_documents()
        (card,) = documents["apply card"]["inbox"]["open"]
        self.assertEqual(card["reason"], "register_apply")
        self.assertIsNone(documents["apply card"]["registration"]["note"])
        self.assertEqual(documents["ended and shown"]["inbox"]["open"], [])
        self.assertEqual(documents["ended and shown"]["registration"]["note"],
                         "The plan is a draft.")

    def test_a_dismissed_registration_does_not_make_the_check_busy(self):
        seeded([])
        self.token()
        posts = []

        def post(url, headers, body):
            posts.append((url, json.loads(body)))
            return 409, b"... is not the top of a git checkout\n"

        code, out = self.run_check(["--contract", CONTRACT], fetch=lambda url: view(DISMISSED),
                                   post=post)
        self.assertEqual((code, out["status"]), (1, "not_met"))
        (url, body), = posts
        self.assertTrue(url.endswith("/api/register-project"))
        self.assertIs(body["unless_open"], True)

    def test_an_open_registration_is_busy_before_the_token_is_read(self):
        seeded([])
        code, out = self.run_check(["--contract", CONTRACT],
                                   fetch=lambda url: sent(open_documents()["running"]))
        self.assertEqual((code, out), (75, {"status": "busy"}))

    def changed_while_building(self, first, later):
        before = seeded([{"project_id": "owner/keep", "root": "/somewhere"}])
        self.token()
        reads, posts = [], []

        def fetch(url):
            reads.append(url)
            return first if len(reads) == 1 else later

        def post(url, headers, body):
            posts.append(url)
            return 204, b""

        code, out = self.run_check(["--contract", CONTRACT], fetch=fetch, post=post)
        self.assertEqual((code, out), (75, {"status": "busy"}))
        self.assertEqual(posts, [])
        self.assertEqual(len(reads), 2)
        self.assertEqual(list(self.tmp_root.iterdir()), [])
        self.assertEqual(agent_platform.registry_path().read_bytes(), before)

    def test_a_registration_opened_while_the_fixture_is_built_is_busy(self):
        self.changed_while_building(view(None), sent(open_documents()["register card"]))

    def test_a_dismissed_registration_cancelled_while_the_fixture_is_built_is_busy(self):
        self.changed_while_building(view(DISMISSED), view(None))

    def test_an_open_refusal_is_busy(self):
        before = seeded([{"project_id": "owner/keep", "root": "/somewhere"}])
        self.token()
        code, out = self.run_check(
            ["--contract", CONTRACT], fetch=lambda url: view(None),
            post=lambda url, headers, body: (409, (register.OPEN_SHOWN + "\n").encode()))
        self.assertEqual((code, out), (75, {"status": "busy"}))
        self.assertEqual(agent_platform.registry_path().read_bytes(), before)
        self.assertEqual(list(self.tmp_root.iterdir()), [])

    def test_the_restore_wait_never_sleeps_past_its_bound(self):
        started = time.monotonic()
        result = register_check._restore_view(
            lambda url: view({"root": "/elsewhere", "status": "done", "at": "x"}),
            lambda *a: (204, b""), "http://127.0.0.1:1", "t", Path("/r"), "p", None, 5.0, 0.2)
        self.assertEqual(result, (["registration"], False))
        self.assertLess(time.monotonic() - started, 2.0)

    def test_a_changed_entry_of_the_same_root_status_and_time_is_not_the_saved_one(self):
        saved = {"root": "/elsewhere/r", "status": "done", "result": "failed",
                 "note": register.LATER_NOTE, "line": "x", "adoption": None, "at": T}
        changed = {**saved, "note": "Choose Try again.", "line": "y",
                   "adoption": {"headline": "h", "note": None}}
        for shown, expected in ((changed, (["registration"], False)), (saved, ([], False))):
            with self.subTest(note=shown["note"]):
                self.assertEqual(register_check._restore_view(
                    lambda url, d=shown: view(d), lambda *a: (204, b""), "http://127.0.0.1:1",
                    "t", Path("/r"), "p", saved, 0.01, 0.2), expected)

    def test_a_read_that_ends_past_the_deadline_posts_no_cancel(self):
        now, fetches, posts = [0.0], [], []

        def fetch(url):
            fetches.append(url)
            now[0] += 1.0
            return view({"root": "/r", "status": "done", "result": "failed", "note": None,
                         "cancel": True, "at": "x"})

        def post(url, headers, body):
            posts.append(url)
            return 204, b""

        def sleep(seconds):
            now[0] += seconds

        with unittest.mock.patch.object(register_check.time, "monotonic", lambda: now[0]), \
                unittest.mock.patch.object(register_check.time, "sleep", sleep):
            result = register_check._restore_view(
                fetch, post, "http://127.0.0.1:1", "t", Path("/r"), "p", None, 0.1, 0.5)
        self.assertEqual(result, (["registration"], False))
        self.assertEqual(posts, [])
        self.assertEqual(len(fetches), 1)

    def test_a_foreign_url_is_a_usage_error(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            register_check.main(["--url", "http://example.com:1"])
        self.assertEqual(raised.exception.code, 2)


class WrapperTest(unittest.TestCase):
    def test_the_wrapper_runs_the_module(self):
        done = subprocess.run([str(WRAPPER), "--url", "http://127.0.0.1:1"], cwd=ROOT,
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 75)
        self.assertEqual(json.loads(done.stdout), {"status": "not_running"})
        self.assertTrue(os.access(WRAPPER, os.X_OK))


if __name__ == "__main__":
    unittest.main()
