"""The console's plan-approve write (#1054): the guard, the refusals, the run and the pull request's inbox item.

Each case has its own HOME; every repository and remote is a throwaway, the forge a stand-in.

Run: just agent-workflow-tests
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
import shutil
import socketserver
import sys
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path
from unittest import mock

from agent_tools.console import (
    approve, contract_draft, folder_trust, register, register_check, service, signin, sprints)
from agent_tools.console import event_log
from agent_tools.project_contract import adopt_apply, adopt_inspection
from agent_tools.system.forge_api import ForgeError

from . import console_test_support as support
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1052)
from .test_console_register_service import (
    A1, DRAFT, PID_A, PID_B, READ_NO_BUILD, READY, ROOT, CancelChecks, Case, DraftCase, Fake, Held,
    answer_of, assert_freed, assert_held, closing, git, git_repo, real_home_state, reconcile_repository,
    sample_repository)

PATH = "/api/plan-approve"
MERGE_PATH = "/api/adoption-merge"
RETRY_PATH = "/api/adoption-register"
DEFER_PATH = "/api/plan-defer"
OLD_PUSH_NOTE = ("Check that the repository's origin can be reached from this host and accepts the "
                 "push, then press Try again.")
PID_C = "sha256:" + "c" * 64
BRANCH = "adopt-bbbbbbbbbbbb"
COMMIT = "c" * 40
APPLIED = {"branch": BRANCH, "commit": COMMIT, "plan_id": PID_B, "migration_map": "m",
           "evidence_record": "e", "integration_branch": "develop"}
GATE = {"error": {
    "code": "verification_failed", "repair_id": "adopt.gate.cold-clone-resolves",
    "violations": [{"pointer": "/verification/commit_gates/cold-clone-resolves",
                    "message": "a pre-commit gate did not pass"}]}}
STALE_ERROR = {"error": {
    "code": "plan_stale", "repair_id": "adopt.plan.inputs_changed",
    "violations": [{"pointer": "/plan/input_digest",
                    "message": "the repository no longer hashes to the plan's input digest"}]}}
WITH_DELETION = {**READY, "changes": [
    *READY["changes"], {"op": "delete-file", "sources": ["old.md"], "targets": []}]}
SIGNING = {"error": {
    "code": "verification_failed", "repair_id": "adopt.commit.signing_unavailable",
    "violations": [{"pointer": "", "message": "the contract asks for a signed commit "
                                              "and this host could not sign one"}]}}
DISCARD_FAILED = {"error": {
    "code": "adopt_failure", "repair_id": "adopt.discard.failed",
    "violations": [{"pointer": "", "message": "the retained worktree of this plan could not "
                                              "be removed"}]}}
URL = "https://github.com/fixture/r/pull/7"
NOT_INTEGRATED = {"error": {
    "code": "not_integrated", "repair_id": "adopt.registration.not_integrated",
    "violations": [{"pointer": "",
                    "message": "the remote integration branch carries no adoption evidence record"}]}}
NO_REMOTE = {"error": {
    "code": "not_integrated", "repair_id": "adopt.registration.no_remote",
    "violations": [{"pointer": "", "message": "the repository has no origin remote"}]}}
GREEN = {"registered": True, "project_id": "o/r", "result": "adopted"}
REGISTER_ERROR = "console: adoption_register_error "
ERROR_LINE = "console: plan_approve_error "
PLAIN_WORDS = ("adopt.", "verification_failed", "HTTP", "422", "gh_failed", "Traceback")


def attempt_of(text):
    """The attempt token the console put in the body of the pull request it opened."""
    (found,) = re.findall(r"<!-- console-attempt ([0-9a-f]{32}) -->$", text)
    return found


class StandInForge:
    def __init__(self, states=None, open_raises=None, lost=None, find_raises=None,
                 open_block=False, linger=0.0):
        self.linger = linger
        self.states = states or {}
        self.open_raises = open_raises or []
        self.lost = lost or []
        self.find_raises = find_raises or []
        self.open_block = open_block
        self.calls = []
        self.pulls: dict[tuple[str, str], int] = {}
        self.closed: set[int] = set()
        self.next_number = 7
        self.entered = threading.Event()
        self.heads = {}
        self.bases = {}
        self.unread = {}
        self.texts = {}
        self.merge_raises = []
        self.merge_block = None
        self.merge_entered = threading.Event()
        self.read_pause = None
        self.pause_after = 0
        self.paused = False
        self.reads = 0
        self.read_entered = threading.Event()
        self.before_merge = None
        self.ids = {}

    def ident(self, number):
        """The forge's own id of a pull request: fixed by its number unless a test replaces it."""
        return self.ids.get(number, 1000 + number)

    def find_pull_request(self, slug, head, base, cancel=None):
        self.calls.append(("find", slug, head, base))
        if self.find_raises:
            error = self.find_raises.pop(0)
            if isinstance(error, BaseException):
                raise error
        number = self.pulls.get((head, base))
        if number is None or number in self.closed:
            return None
        title, body = self.texts.get(number, (None, None))
        return {"number": number, "url": f"https://github.com/{slug}/pull/{number}",
                "title": title, "body": body, "id": self.ident(number)}

    def open_pull_request(self, slug, head, base, title, body, cancel=None):
        self.calls.append(("open", slug, head, base, title, body))
        if self.open_raises:
            raise self.open_raises.pop(0)
        number = self.next_number
        self.next_number += 1
        self.pulls[(head, base)] = number
        self.texts[number] = (title, body)
        if self.lost:
            raise self.lost.pop(0)
        if self.open_block:
            self.entered.set()
            (cancel or threading.Event()).wait(10)
            time.sleep(self.linger)
            raise approve.Cancelled()
        return {"number": number, "url": f"https://github.com/{slug}/pull/{number}",
                "id": self.ident(number)}

    def pull_request_state(self, slug, number, cancel=None):
        self.calls.append(("state", slug, number))
        found = self.states.get(number, "open")
        if isinstance(found, BaseException):
            raise found
        return found

    def pull_request_reading(self, slug, number, cancel=None):
        self.calls.append(("state", slug, number))
        found = self.states.get(number, "open")
        if isinstance(found, BaseException):
            raise found
        reading = {"state": found, "head": self.heads.get(number, COMMIT),
                   "base": self.bases.get(number, "develop"),
                   "checks_error": self.unread.get(number), "id": self.ident(number)}
        self.reads += 1
        if self.read_pause is not None and self.reads > self.pause_after and not self.paused:
            self.paused = True
            self.read_entered.set()
            self.read_pause.wait(10)
        return reading

    def merge_pull_request(self, slug, number, head, cancel=None):
        self.calls.append(("merge", slug, number, head))
        if self.before_merge is not None:
            self.before_merge()
        self.merge_entered.set()
        if self.merge_block is not None:
            self.merge_block.wait(10)
        if self.merge_raises:
            raise self.merge_raises.pop(0)
        self.states[number] = "merged"

    def mark_closed(self, number):
        self.closed.add(number)


class RacingForge(StandInForge):
    """A forge whose create attempt fails while a person opens a pull request with the console's words."""

    def open_pull_request(self, slug, head, base, title, body, cancel=None):
        self.calls.append(("open", slug, head, base, title, body))
        self.pulls[(head, base)] = 7
        self.texts[7] = (title, body.split("\n\n<!--")[0])
        raise ForgeError("gh_timeout", "api")


class Pusher:
    def __init__(self, raises=None, wait_for_stop=False):
        self.raises = raises or []
        self.wait_for_stop = wait_for_stop
        self.calls = []
        self.entered = threading.Event()

    def __call__(self, root, branch, commit, cancel=None):
        self.calls.append((root, branch, commit))
        self.entered.set()
        if self.raises:
            raise self.raises.pop(0)
        if self.wait_for_stop:
            (cancel or threading.Event()).wait(10)


class RegistryFake(Fake):
    def __init__(self, registry, **fake_arguments):
        super().__init__(**fake_arguments)
        self.registry = registry

    def register(self, root, cancel=None, **operands):
        self.register_operands.append(operands)
        self._run("register", root, cancel)
        if self.register_raises is not None:
            raise self.register_raises
        if self.report is GREEN:
            support.write_registry(self.registry, [{"project_id": "o/r", "root": root}])
        return self.report


_RECONCILE_TEMPLATES: dict[str, Path] = {}


def reconciled(parent: Path, *, contract: bool = False) -> Path:
    """`reconcile_repository(parent, contract=contract)`, copied from one build per flag per process.

    The repository's only absolute path is its origin URL, so a copy re-points it at its own bare origin;
    the index is refreshed because the copy's files are new inodes and product code reads that index.
    """
    if "root" not in _RECONCILE_TEMPLATES:
        root = Path(tempfile.mkdtemp(prefix="approve-reconcile-"))
        unittest.addModuleCleanup(shutil.rmtree, root, True)
        _RECONCILE_TEMPLATES["root"] = root
    flag = "contract" if contract else "plain"
    template = _RECONCILE_TEMPLATES["root"] / flag
    if flag not in _RECONCILE_TEMPLATES:
        reconcile_repository(template, contract=contract)
        _RECONCILE_TEMPLATES[flag] = template
    parent.mkdir(parents=True, exist_ok=True)
    copy = parent / "reconcile"
    shutil.copytree(template / "reconcile", copy, symlinks=True)
    shutil.copytree(template / "origin.git", parent / "origin.git", symlinks=True)
    git(copy, "remote", "set-url", "origin", str(parent / "origin.git"))
    git(copy, "update-index", "-q", "--refresh")
    return copy.resolve()


SERVER_POLL_SECONDS = 0.01


def quick_serve_forever(server, poll_interval=SERVER_POLL_SECONDS):
    "The stdlib serve loop with a short selector poll, so a console's shutdown returns at once."
    return socketserver.BaseServer.serve_forever(server, poll_interval)


def awaited(svc, probe, bound: float, recheck: float):
    """`probe()`'s first truthy answer, waiting on the console's publish between probes; None past `bound`.

    The version is read before each probe, so a publish between the two wakes the next wait at once.
    A closing console answers `wait_for_change` at once, so it is slept out instead of spun on.
    """
    end = time.monotonic() + bound
    while time.monotonic() < end:
        seen = svc.version
        found = probe()
        if found:
            return found
        wait = min(recheck, end - time.monotonic())
        if wait > 0:
            if svc.closing:
                time.sleep(wait)
            else:
                svc.wait_for_change(seen, wait)
    return None


class ApproveCase(Case):
    def setUp(self):
        super().setUp()
        patch = mock.patch.object(service.ConsoleServer, "serve_forever", quick_serve_forever)
        patch.start()
        self.addCleanup(patch.stop)
        self.forge = StandInForge()
        self.pusher = Pusher()
        self.fake = None
        self.kwargs = {}

    def start(self, fake, **kwargs):
        self.fake = fake
        self.kwargs = {"forge": self.forge, "pusher": self.pusher,
                       "slug_of": lambda root: "fixture/r", "dispatch": None,
                       "adoption_seconds": 3600, **kwargs}
        return self.begin(fake, **self.kwargs)

    def restart(self, fake=None):
        self.svc.close()
        return self.begin(self.fake if fake is None else fake, **self.kwargs)

    def ready(self, plan=READY, fake_class=Fake, **fake_arguments):
        fake = fake_class(plan=plan, **fake_arguments)
        self.start(fake)
        self.repo = reconciled(self.parent, contract=True)
        self.shown = self.registered(self.repo)
        self.planned = self.settled_row(self.repo)
        return fake

    def kept(self, plan_id):
        """A copy a failed apply left: the directory and the record `approve.retained` reads."""
        home = self.home / ".agents/state/adopt/worktrees"
        digest = adopt_apply.plan_digest(plan_id)
        (home / digest).mkdir(parents=True, exist_ok=True)
        (home / f"{digest}.failure.json").write_text(json.dumps({
            "branch": f"adopt-{digest[:12]}", "worktree": str(home / digest)}))

    def kept_bare(self, plan_id):
        """A copy a timed-out apply left before it wrote its record: the bare directory."""
        digest = adopt_apply.plan_digest(plan_id)
        (self.home / ".agents/state/adopt/worktrees" / digest).mkdir(parents=True, exist_ok=True)
        self.assertIsNone(approve.retained(plan_id))

    def answer_after_a_failed_apply(self, **fake_arguments):
        self.ready(apply_result=SIGNING, **fake_arguments)
        self.run_approval("apply_failed")
        return self.fake

    def answered(self):
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            status, _, _ = self.answer(answer_of(PID_B, {
                "id": "candidate-class", "subject": ".claude/odd.md", "value": "keep"}))
            self.assertEqual(status, 204)
            return self.settled_row(self.repo)

    def approve(self, body=None, headers=None, raw=None):
        payload = json.dumps(body).encode() if raw is None else raw
        sent = self.own(**{"Content-Type": "application/json"}) if headers is None else headers
        return support.post_page(self.svc.address, PATH, sent, payload)

    def approve_plan(self, plan_id=PID_B):
        return self.approve({"plan_id": plan_id})

    def until(self, *steps, after=0, bound=120):
        def probe():
            with self.svc._ingest:
                found = self.steps()
                busy = self.svc._approving
                shown = self.view()["registration"]
            return shown if len(found) > after and found[-1] in steps and not busy else None

        found = awaited(self.svc, probe, bound, 0.05)
        if found is None:
            self.fail("the approval never reached the expected step")
        return found

    def wait_done(self, root, bound=120):
        def probe():
            found = self.view()["registration"]
            if found is not None and found["root"] == str(root) and found["status"] == "done":
                return found
            return None

        found = awaited(self.svc, probe, bound, 0.1)
        if found is None:
            self.fail("no registration result")
        return found

    def wait_for(self, predicate, bound=120):
        def probe():
            found = self.view()["registration"]
            return found if found is not None and predicate(found) else None

        found = awaited(self.svc, probe, bound, 0.1)
        if found is None:
            self.fail("the registration never reached the expected state")
        return found

    def settled_row(self, root, bound=120):
        """The stored payload of the root's last ended registration, once the run has finished.

        It observes completion through the log and the service's run mark, not through the view,
        which a card or a registered project reduces or drops (ADR-console-035).
        """
        def probe():
            found = [payload for _, payload in self.rows(event_log.REGISTRATION_ENDED)
                     if payload.get("root") == str(root)]
            return found[-1] if self.svc._registering is None and found else None

        found = awaited(self.svc, probe, bound, 0.05)
        if found is None:
            self.fail("no registration result")
        return found

    def run_approval(self, *steps, plan_id=PID_B):
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            after = len(self.steps())
            self.assertEqual(self.approve_plan(plan_id)[::2], (204, b""))
            self.until(*steps, after=after)
            for worker in self.approval_threads():
                worker.join(30)
        return self.view()["registration"], errors.getvalue()

    def refused(self, plan_id, text):
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            status, _, body = self.approve_plan(plan_id)
        self.assertEqual((status, body), (409, text.encode() + b"\n"))
        self.assertIn(f"console: plan_approve_refused {text}", errors.getvalue())

    def steps(self):
        return [found["step"] for _, found in self.rows("adoption.step")]

    def opens(self):
        return [call for call in self.forge.calls if call[0] == "open"]

    def heads(self):
        return git(self.parent / "origin.git", "for-each-ref", "--format=%(refname) %(objectname)")

    def approval_threads(self):
        return [thread for thread in threading.enumerate()
                if thread.name == service.APPROVAL_THREAD and thread.is_alive()]

    def card_words(self):
        """The one apply card's headline, lines and note, which replace the reduced adoption."""
        (card,) = self.apply_cards()
        return {"headline": card["headline"], "lines": card["lines"], "note": card["why"]}

    def adoption(self):
        return self.view()["registration"]["adoption"]

    def opened(self, fake_class=Fake, **fake_arguments):
        fake = self.ready(apply_result=APPLIED, fake_class=fake_class, **fake_arguments)
        self.run_approval("opened")
        return fake

    def items(self):
        return [i for i in self.view()["inbox"]["open"] if i["reason"] == "adoption"]

    def pulls(self):
        return self.rows("adoption.pull_request")

    def poll(self, state, number=7):
        self.forge.states[number] = state
        self.svc.poll_adoptions()

    def registrations(self):
        return [payload for _, payload in self.rows("adoption.registration")]

    def register_calls(self):
        return [call for call in self.fake.calls if call[0] == "register"]

    def retry_items(self):
        return [i for i in self.view()["inbox"]["open"] if i["reason"] == "register_retry"]

    def listed(self, project_id):
        for entry in self.view()["entries"]:
            found = entry["projects"] if entry["type"] == "quiet_group" else [entry]
            if any(one["project_id"] == project_id for one in found):
                return True
        return False

    def retry(self, plan_id):
        status, _, _ = support.post_page(
            self.svc.address, RETRY_PATH, self.own(**{"Content-Type": "application/json"}),
            json.dumps({"plan_id": plan_id}).encode())
        for worker in self.approval_threads():
            worker.join(30)
        return status

    def apply_cards(self):
        return [i for i in self.view()["inbox"]["open"] if i["reason"] == "register_apply"]

    def merge(self, plan_id=PID_B, number=None, commit=None, headers=None):
        with self.svc._ingest:
            found = self.svc._adoptions.get(plan_id)
        if number is None:
            number = found["pull_request"]["number"]
        if commit is None:
            commit = found["commit"]
        sent = self.own(**{"Content-Type": "application/json"}) if headers is None else headers
        status, _, body = support.post_page(
            self.svc.address, MERGE_PATH, sent,
            json.dumps({"plan_id": plan_id, "number": number, "commit": commit}).encode())
        for worker in self.approval_threads():
            worker.join(30)
        return status, body

    def merged_calls(self):
        return [call for call in self.forge.calls if call[0] == "merge"]

    def logged_merge(self, **arguments):
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            answer = self.merge(**arguments)
        return answer, errors.getvalue()

    def last_pull(self):
        return self.pulls()[-1][1]

    def defer(self, plan_id=PID_B, raw=None, headers=None):
        payload = json.dumps({"plan_id": plan_id}).encode() if raw is None else raw
        sent = self.own(**{"Content-Type": "application/json"}) if headers is None else headers
        status, _, body = support.post_page(self.svc.address, DEFER_PATH, sent, payload)
        return status, body

    def deferrals(self):
        return [payload for _, payload in self.rows("adoption.deferred")]

    def settled(self, count, bound=120):
        def probe():
            found = self.registrations()
            with self.svc._ingest:
                busy = PID_B in self.svc._enrolling
            return found if len(found) >= count and not busy else None

        found = awaited(self.svc, probe, bound, 0.05)
        if found is None:
            self.fail("the registration never settled")
        return found


class QuickShutdownTest(ApproveCase):
    def watch_polls(self):
        seen = []
        changed = threading.Condition()

        class Recording(socketserver._ServerSelector):
            def select(self, timeout=None):
                with changed:
                    seen.append((next(iter(self.get_map().values())).fileobj, timeout))
                    changed.notify_all()
                return super().select(timeout)

        patcher = mock.patch.object(socketserver, "_ServerSelector", Recording)
        patcher.start()
        self.addCleanup(patcher.stop)

        def served(server):
            with changed:
                changed.wait_for(lambda: any(obj is server for obj, _ in seen), 5)
                return [timeout for obj, timeout in seen if obj is server]
        return served

    def test_a_case_console_serves_with_the_quick_shutdown_poll(self):
        served = self.watch_polls()
        self.start(Fake(plan=READY))
        server = self.svc._server
        timeouts = served(server)
        self.svc.close()
        self.assertTrue(timeouts)
        self.assertEqual(set(timeouts), {SERVER_POLL_SECONDS})
        self.assertLess(SERVER_POLL_SECONDS, 0.5)

    def test_a_restarted_console_serves_with_the_quick_shutdown_poll(self):
        served = self.watch_polls()
        self.start(Fake(plan=READY))
        self.restart()
        server = self.svc._server
        timeouts = served(server)
        self.svc.close()
        self.assertTrue(timeouts)
        self.assertEqual(set(timeouts), {SERVER_POLL_SECONDS})


class QuickShutdownPatchTest(unittest.TestCase):
    def test_the_quick_poll_patch_ends_with_the_test(self):
        class Probe(ApproveCase):
            def test_probe(self):
                self.start(Fake(plan=READY))
                self.assertIs(service.ConsoleServer.serve_forever, quick_serve_forever)

        result = unittest.TestResult()
        Probe("test_probe").run(result)
        self.assertTrue(result.wasSuccessful(), result.failures + result.errors)
        self.assertIs(service.ConsoleServer.serve_forever, socketserver.BaseServer.serve_forever)


class PublishWaitTest(ApproveCase):
    def clock(self, sleeps, on_sleep=None):
        """A stand-in `time` for both test modules' helpers: it records every sleep, then really sleeps."""
        real_sleep = time.sleep

        def sleep(seconds):
            sleeps.append(seconds)
            if on_sleep is not None:
                on_sleep()
            real_sleep(seconds)
        stand_in = types.SimpleNamespace(monotonic=time.monotonic, sleep=sleep)
        for module in (sys.modules[__name__], sys.modules[Case.__module__]):
            patcher = mock.patch.object(module, "time", stand_in)
            patcher.start()
            self.addCleanup(patcher.stop)
        return stand_in

    def controlled(self, now):
        """A stand-in `time` on a controlled clock, and a stand-in console whose waits advance it."""
        def sleep(seconds):
            raise AssertionError("slept")
        waits = []

        def wait(seen, timeout):
            waits.append((seen, timeout))
            now[0] += timeout
            return None
        patcher = mock.patch.object(
            sys.modules[__name__], "time", types.SimpleNamespace(monotonic=lambda: now[0], sleep=sleep))
        patcher.start()
        self.addCleanup(patcher.stop)
        return types.SimpleNamespace(version=7, closing=False, wait_for_change=wait), waits

    def test_registered_returns_on_the_publish_without_sleeping(self):
        gate = threading.Event()
        self.addCleanup(gate.set)
        self.start(Fake(plan=READY, block=gate))
        repo = reconciled(self.parent, contract=True)
        sleeps = []
        self.clock(sleeps, on_sleep=gate.set)
        real = self.svc.wait_for_change
        with mock.patch.object(self.svc, "wait_for_change",
                               side_effect=lambda seen, timeout: (gate.set(), real(seen, timeout))[1]) as spy:
            shown = self.registered(repo)
        self.assertEqual((shown["root"], shown["status"]), (str(repo), "done"))
        self.assertEqual(sleeps, [])
        self.assertTrue(spy.called)

    def test_a_wait_on_a_closed_console_waits_out_its_recheck(self):
        self.start(Fake(plan=READY))
        self.svc.close()
        sleeps = []
        self.clock(sleeps)
        found = awaited(self.svc, lambda: None, bound=0.12, recheck=0.05)
        self.assertIsNone(found)
        self.assertTrue(sleeps)
        self.assertLessEqual(len(sleeps), 4)
        self.assertTrue(all(s <= 0.05 for s in sleeps), sleeps)

    def test_awaited_does_not_probe_once_its_deadline_has_passed(self):
        now = [0.0]
        svc, waits = self.controlled(now)
        probes = []
        found = awaited(svc, lambda: (probes.append(now[0]), "late" if now[0] >= 1.0 else None)[1],
                        bound=1.0, recheck=0.5)
        self.assertIsNone(found)
        self.assertEqual(probes, [0.0, 0.5])
        self.assertEqual(waits, [(7, 0.5), (7, 0.5)])

    def test_awaited_returns_an_event_within_its_bound(self):
        now = [0.0]
        svc, waits = self.controlled(now)
        probes = []
        found = awaited(svc, lambda: (probes.append(now[0]), "on time" if now[0] >= 0.5 else None)[1],
                        bound=1.0, recheck=0.5)
        self.assertEqual(found, "on time")
        self.assertEqual(probes, [0.0, 0.5])
        self.assertEqual(waits, [(7, 0.5)])

    def test_wait_done_fails_in_its_words_once_its_bound_passes(self):
        self.start(Fake(plan=READY))
        started = time.monotonic()
        with self.assertRaises(AssertionError) as raised:
            self.wait_done(self.parent / "never", bound=0.2)
        self.assertIn("no registration result", str(raised.exception))
        self.assertGreaterEqual(time.monotonic() - started, 0.2)

    def test_until_reads_steps_and_view_under_the_ingest_lock(self):
        self.opened()
        held = []
        real_steps, real_view = self.steps, self.view
        with mock.patch.object(self, "steps", side_effect=lambda: (
                held.append(self.svc._ingest.locked()), real_steps())[1]), \
                mock.patch.object(self, "view", side_effect=lambda: (
                    held.append(self.svc._ingest.locked()), real_view())[1]):
            shown = self.until("opened")
        self.assertEqual(shown, real_view()["registration"])
        self.assertTrue(held)
        self.assertTrue(all(held), held)


class ApplyCardTest(ApproveCase):
    def test_a_ready_plan_is_one_apply_card_counted_in_the_statement(self):
        self.ready(apply_result=APPLIED)
        (card,) = self.apply_cards()
        self.assertEqual(card["title"], "Register reconcile")
        self.assertEqual(card["headline"], "Apply this adoption?")
        self.assertEqual(card["questions"][0]["options"], ["Apply it", "Not now"])
        self.assertEqual(card["values"], ["apply", "not_now"])
        self.assertEqual(card["lines"], self.planned["lines"])
        self.assertEqual(card["lines"], ["moves 1 agent file under .agents/"])
        self.assertEqual(self.shown["line"], "Register reconcile: needs you")
        self.assertEqual(card["key"], f"register-apply/{PID_B}/{self.shown['at']}")
        view = self.view()
        self.assertIn(card, view["inbox"]["open"])
        self.assertEqual(view["statement"]["inbox_items"], len(view["inbox"]["open"]))

    def test_apply_it_dispatches_the_approve_write_and_the_work_line_says_applying(self):
        gate = threading.Event()
        self.ready(apply_result=APPLIED, apply_block=gate)
        self.addCleanup(gate.set)
        (card,) = self.apply_cards()
        self.assertEqual(self.approve_plan(card["plan_id"])[0], 204)
        self.assertEqual(self.apply_cards(), [])
        self.assertEqual(self.view()["registration"]["line"],
                         "Applying the adoption of reconcile and opening its pull request…")
        gate.set()
        self.until("opened")
        for worker in self.approval_threads():
            worker.join(30)
        self.assertEqual(self.fake.applied, [(PID_B, False)])
        self.assertEqual(self.apply_cards(), [])

    def test_not_now_removes_the_card_until_the_plan_id_changes(self):
        self.ready(apply_result=APPLIED)
        before = self.view()["statement"]["inbox_items"]
        self.assertEqual(self.defer(), (204, b""))
        self.assertEqual(self.apply_cards(), [])
        view = self.view()
        self.assertEqual(view["statement"]["inbox_items"], before - 1)
        self.assertEqual(view["registration"]["line"], "Register reconcile: ready to apply")
        self.assertEqual(self.deferrals(), [{"plan_id": PID_B}])
        self.svc.refresh()
        self.svc.poll_adoptions()
        self.assertEqual(self.apply_cards(), [])
        self.fake.document = {**READY, "plan": {**READY["plan"], "plan_id": PID_A}}
        self.registered(self.repo)
        (card,) = self.apply_cards()
        self.assertEqual(card["plan_id"], PID_A)

    def test_not_now_holds_across_a_restart_and_registering_the_same_plan_again(self):
        self.ready(apply_result=APPLIED)
        self.assertEqual(self.defer()[0], 204)
        self.restart()
        self.assertEqual(self.apply_cards(), [])
        self.registered(self.repo)
        self.assertEqual(self.apply_cards(), [])
        self.assertEqual(self.deferrals(), [{"plan_id": PID_B}])

    def test_not_now_refusals(self):
        self.ready(apply_result=APPLIED)
        own = f"http://127.0.0.1:{self.svc.address[1]}"
        before = len(support.log_rows(self.store))
        status, body = self.defer(headers={"Origin": own, "Content-Type": "application/json"})
        self.assertEqual(status, 403)
        self.assertEqual(len(self.apply_cards()), 1)
        self.assertEqual(self.defer(raw=b"{}"), (400, b"bad plan deferral\n"))
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            self.assertEqual(self.defer(PID_A), (409, approve.DEFER_STALE.encode() + b"\n"))
        self.assertIn(f"console: plan_defer_refused {approve.DEFER_STALE}", errors.getvalue())
        self.assertEqual(len(support.log_rows(self.store)), before)
        self.assertEqual(self.defer()[0], 204)
        after = len(support.log_rows(self.store))
        self.assertEqual(self.defer(), (409, approve.NOT_OFFERED.encode() + b"\n"))
        self.assertEqual(len(support.log_rows(self.store)), after)
        self.assertEqual(len(self.deferrals()), 1)

    def test_a_failed_push_is_one_try_again_card_that_resumes_at_the_push(self):
        self.pusher.raises = [approve.PushFailed("remote rejected the push", "d")]
        fake = self.ready(apply_result=APPLIED)
        shown, _ = self.run_approval("push_failed")
        (card,) = self.apply_cards()
        self.assertEqual(card["questions"][0]["options"], ["Try again", "Not now"])
        self.assertEqual(card["values"], ["retry", "not_now"])
        self.assertEqual(
            card["headline"],
            "The adoption of reconcile was applied, but its branch was not pushed: remote "
            "rejected the push.")
        self.assertEqual(shown["line"], "Register reconcile: needs you")
        self.assertEqual(card["why"], approve.PUSH_NOTE)
        self.assertEqual(card["lines"], [])
        self.run_approval("opened", plan_id=card["plan_id"])
        self.assertEqual(len(fake.applied), 1)
        self.assertEqual(self.pusher.calls, [(str(self.repo), BRANCH, COMMIT)] * 2)
        self.assertEqual(len(self.opens()), 1)
        self.assertEqual(self.apply_cards(), [])

    def test_a_failed_pull_request_is_one_try_again_card_that_resumes_at_the_open(self):
        self.forge.open_raises = [ForgeError("gh_failed", "gh: Validation Failed (HTTP 422)")]
        fake = self.ready(apply_result=APPLIED)
        self.run_approval("open_failed")
        self.assertEqual(self.pusher.calls, [(str(self.repo), BRANCH, COMMIT)])
        (card,) = self.apply_cards()
        self.assertEqual(card["questions"][0]["options"], ["Try again", "Not now"])
        for word in ("HTTP", "422", "gh_failed"):
            self.assertNotIn(word, card["why"])
        self.pusher.raises = [approve.PushFailed("remote rejected the push", "d")]
        shown, _ = self.run_approval("opened", "push_failed", plan_id=card["plan_id"])
        self.assertEqual(shown["adoption"]["step"], "opened")
        self.assertEqual(self.pusher.calls, [(str(self.repo), BRANCH, COMMIT)])
        self.assertEqual(len(fake.applied), 1)
        self.assertEqual(self.steps()[-1], "opened")
        self.assertEqual(self.apply_cards(), [])

    def test_a_failed_apply_offers_apply_it_again(self):
        self.ready(apply_result=GATE)
        shown, _ = self.run_approval("apply_failed")
        (card,) = self.apply_cards()
        self.assertEqual(card["questions"][0]["options"], ["Apply it again", "Not now"])
        self.assertEqual(card["values"], ["apply", "not_now"])
        self.assertEqual(card["why"], "Fix what failed in the repository, then register the "
                                      "repository again.")
        self.assertEqual(shown["line"], "Register reconcile: needs you")

    def test_a_signing_failure_is_one_card_in_plain_words(self):
        self.ready(apply_result={"error": {
            "code": "verification_failed", "repair_id": "adopt.commit.signing_unavailable",
            "violations": [{"pointer": "", "message": "the contract asks for a signed commit "
                                                      "and this host could not sign one"}]}})
        self.run_approval("apply_failed")
        (card,) = self.apply_cards()
        shown = self.view()["registration"]
        self.assertIn("signed commits", card["headline"])
        self.assertEqual(card["why"], approve.SIGNING_NOTE)
        self.assertEqual(card["questions"][0]["options"], ["Apply it again", "Not now"])
        self.assertEqual(shown["line"], "Register reconcile: needs you")
        raw = re.compile(r"--plan-id|sha256:|[0-9a-f]{12,}|(?:^|[\s(\"'])/\S")
        for text in (card["headline"], card["why"], *card["lines"], shown["line"]):
            self.assertIsNone(raw.search(text), text)

    def test_turn_signed_commits_off_after_a_kept_copy_leaves_nothing_of_the_old_plan(self):
        later = {**READY, "plan": {**READY["plan"], "plan_id": PID_A}}
        fake = Fake(plan=[READY, later], apply_result=SIGNING)
        self.start(fake, draft_reader=lambda root: READ_NO_BUILD)
        self.repo = reconciled(self.parent)
        drafting = self.registered(self.repo)
        for field, value in (("commit-signed", "yes"), ("build-command", "none"),
                             ("test-command", "none")):
            before = drafting["plan_id"]
            errors = io.StringIO()
            with contextlib.redirect_stderr(errors):
                status, _, _ = self.answer(answer_of(before, {
                    "id": "contract-draft", "subject": field, "value": value}))
                self.assertEqual(status, 204)
                drafting = self.wait_for(
                    lambda r: r["status"] == "done" and r["plan_id"] != before)
        self.assertEqual(drafting["plan_id"], PID_B)
        self.run_approval("apply_failed")
        self.kept(PID_B)
        (card,) = self.apply_cards()
        self.assertEqual(card["questions"][0]["options"],
                         ["Apply it again", "Turn signed commits off", "Not now"])
        self.assertEqual(card["values"], ["apply", "signing_off", "not_now"])
        before_tree = self.repository_state()
        planned = len(fake.order)
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            status, _, _ = self.answer(answer_of(PID_B, {
                "id": "contract-draft", "subject": "commit-signed", "value": "no"}))
            self.assertEqual(status, 204)
            self.wait_for(lambda r: r["status"] == "done" and r["plan_id"] == PID_A)
        self.assertEqual(fake.order[planned:], [("discard", PID_B), ("plan", str(self.repo))])
        last = self.rows(event_log.REGISTRATION_ENDED)[-1][1]
        fields = {f["field"]: f["value"] for f in last["draft"]}
        self.assertEqual(fields["commit-signed"], "no")
        self.assertEqual(self.repository_state(), before_tree)

    def repository_state(self):
        status = git(self.repo, "status", "--porcelain")
        files = {str(path.relative_to(self.repo)): path.read_bytes()
                 for path in sorted(self.repo.rglob("*"))
                 if path.is_file() and ".git" not in path.relative_to(self.repo).parts}
        return status, files

    def test_apply_it_again_after_a_kept_copy_asks_apply_to_discard_it(self):
        fake = self.ready(apply_result=SIGNING)
        self.run_approval("apply_failed")
        self.run_approval("apply_failed")
        self.assertEqual(fake.discards, [False, True])

    def test_a_draft_change_after_a_failed_apply_discards_its_kept_copy_before_planning(self):
        fake = self.answer_after_a_failed_apply()
        self.kept(PID_B)
        before = len(fake.order)
        self.answered()
        self.assertEqual(fake.order[before:], [("discard", PID_B), ("plan", str(self.repo))])

    def test_a_kept_copy_with_no_record_is_discarded_before_planning(self):
        fake = self.answer_after_a_failed_apply()
        self.kept_bare(PID_B)
        before = len(fake.order)
        self.answered()
        self.assertEqual(fake.order[before:], [("discard", PID_B), ("plan", str(self.repo))])

    def test_a_kept_branch_with_no_directory_is_discarded_before_planning(self):
        fake = self.answer_after_a_failed_apply()
        git(self.repo, "branch", approve.branch_of(PID_B))
        before = len(fake.order)
        self.answered()
        self.assertEqual(fake.order[before:], [("discard", PID_B), ("plan", str(self.repo))])

    def test_a_failed_discard_plans_nothing_and_says_try_again(self):
        fake = self.answer_after_a_failed_apply(discard_result=DISCARD_FAILED)
        self.kept(PID_B)
        before = len(fake.order)
        row = self.answered()
        self.assertEqual(fake.order[before:], [("discard", PID_B)])
        self.assertEqual((row["result"], row["note"]), ("failed", register.DISCARD_STEP))
        raw = re.compile(r"--plan-id|sha256:|[0-9a-f]{12,}|(?:^|[\s(\"'])/\S")
        for text in (row["headline"], row["note"]):
            self.assertIsNone(raw.search(text), text)

    def test_no_kept_copy_runs_no_discard(self):
        fake = self.answer_after_a_failed_apply()
        before = len(fake.order)
        self.answered()
        self.assertEqual(fake.order[before:], [("plan", str(self.repo))])

    def test_not_now_on_a_failed_step_hides_it_and_keeps_the_work_line(self):
        self.pusher.raises = [approve.PushFailed("remote rejected the push", "d")]
        self.ready(apply_result=APPLIED)
        shown, _ = self.run_approval("push_failed")
        self.assertEqual(shown["line"], "Register reconcile: needs you")
        self.assertEqual(self.defer()[0], 204)
        self.assertEqual(self.apply_cards(), [])
        self.assertEqual(
            self.view()["registration"]["line"],
            "The adoption of reconcile was applied, but its branch was not pushed: remote "
            "rejected the push. Check that the repository's origin can be reached from this "
            "host and accepts the push, then choose Try again.")

    def test_an_unexpected_deferral_failure_is_logged_in_full(self):
        self.ready(apply_result=APPLIED)
        errors = io.StringIO()
        with mock.patch.object(self.svc, "defer_plan", side_effect=RuntimeError("the log is gone")):
            with contextlib.redirect_stderr(errors):
                self.assertEqual(self.defer(), (500, b"deferring failed\n"))
        self.assertIn("console: plan_defer_failed RuntimeError: the log is gone", errors.getvalue())
        self.assertIn("Traceback (most recent call last)", errors.getvalue())

    def test_a_failure_row_in_the_old_words_is_shown_in_the_card_words(self):
        self.pusher.raises = [approve.PushFailed("remote rejected the push", "d")]
        self.ready(apply_result=APPLIED)
        self.run_approval("push_failed")
        last = self.rows("adoption.step")[-1][1]
        self.svc.log.append([approve.step_row({**last, "note": OLD_PUSH_NOTE})])
        self.restart()
        (card,) = self.apply_cards()
        self.assertEqual(card["why"], approve.PUSH_NOTE)
        self.assertEqual(self.view()["registration"]["line"], "Register reconcile: needs you")
        self.assertEqual(self.rows("adoption.step")[-1][1]["note"], OLD_PUSH_NOTE)


class PlanApproveGuardTest(ApproveCase):
    def test_the_write_is_refused_without_the_token_or_from_another_origin_and_runs_nothing(self):
        fake = self.ready(apply_result=APPLIED)
        json_type = {"Content-Type": "application/json"}
        token = self.token_file.read_text().strip()
        own = f"http://127.0.0.1:{self.svc.address[1]}"
        before = support.log_rows(self.store)
        for headers, text in (
                ({"Origin": own, **json_type}, b"token refused\n"),
                ({"Origin": own, "X-Console-Token": "wrong", **json_type}, b"token refused\n"),
                ({"Origin": "http://evil.example", "X-Console-Token": token, **json_type},
                 b"origin refused\n")):
            with self.subTest(text=text):
                status, _, body = self.approve({"plan_id": PID_B}, headers=headers)
                self.assertEqual((status, body), (403, text))
        self.assertEqual(support.log_rows(self.store), before)
        self.assertEqual(fake.applied, [])
        self.assertEqual(self.rows("adoption.step"), [])


class PlanApproveRefusalTest(ApproveCase):
    def nothing_ran(self, fake):
        self.assertEqual(fake.applied, [])
        self.assertEqual(self.pusher.calls, [])
        self.assertEqual(self.forge.calls, [])
        self.assertEqual(self.rows("adoption.step"), [])

    def test_bodies_are_refused_as_bad_plan_approval(self):
        fake = self.ready(apply_result=APPLIED)
        for raw in (b"[]", b"{}", b'{"plan_id": 1}', json.dumps({"plan_id": PID_B, "x": 1}).encode()):
            with self.subTest(raw=raw):
                status, _, body = self.approve(raw=raw)
                self.assertEqual((status, body), (400, b"bad plan approval\n"))
        status, _, body = self.approve(
            raw=b"{}", headers=self.own(**{"Content-Type": "text/plain"}))
        self.assertEqual((status, body), (415, b"json only\n"))
        status, _, body = self.approve(raw=b'{"plan_id": "' + b"a" * 4990 + b'"}')
        self.assertEqual((status, body), (413, b"too large\n"))
        self.nothing_ran(fake)

    def test_without_a_forge_the_host_refuses(self):
        fake = Fake(plan=READY, apply_result=APPLIED)
        self.start(fake, forge=None)
        self.shown = self.registered(reconciled(self.parent, contract=True))
        self.refused(PID_B, approve.UNAVAILABLE)
        self.assertEqual(approve.UNAVAILABLE,
                         "approving an adoption is not available on this host")
        self.nothing_ran(fake)

    def test_without_an_adopter_the_host_refuses(self):
        self.fake = None
        self.kwargs = {"forge": self.forge, "pusher": self.pusher, "dispatch": None}
        self.begin(None, **self.kwargs)
        self.refused(PID_B, approve.UNAVAILABLE)
        self.assertEqual(self.pusher.calls, [])
        self.assertEqual(self.forge.calls, [])

    def test_an_approval_while_a_run_is_under_way_is_refused(self):
        gate = threading.Event()
        fake = self.ready(apply_result=APPLIED, apply_block=gate)
        self.addCleanup(gate.set)
        self.assertEqual(self.approve_plan()[0], 204)
        self.refused(PID_B, "a registration is already running for reconcile")
        gate.set()
        self.until("opened")
        self.assertEqual(len(fake.applied), 1)

    def test_an_approval_for_another_plan_id_is_stale(self):
        fake = self.ready(apply_result=APPLIED)
        self.refused("sha256:" + "c" * 64, approve.STALE)
        self.nothing_ran(fake)

    def test_an_approval_with_no_registration_is_stale(self):
        fake = Fake(plan=READY, apply_result=APPLIED)
        self.start(fake)
        self.refused(PID_B, approve.STALE)
        self.nothing_ran(fake)

    def test_a_draft_plan_is_not_ready(self):
        fake = self.ready(plan=DRAFT, apply_result=APPLIED)
        self.refused(PID_A, approve.NOT_READY)
        self.nothing_ran(fake)

    def test_an_opened_plan_is_refused_after_a_restart(self):
        self.ready(apply_result=APPLIED)
        self.run_approval("opened")
        self.restart()
        shown = self.view()["registration"]
        self.assertEqual((shown["adoption"]["step"], shown["approve"]), ("opened", None))
        self.refused(PID_B, approve.OPENED)

    def test_a_merged_plan_is_refused_as_merged(self):
        self.ready(apply_result=APPLIED)
        self.run_approval("opened")
        with self.svc._ingest:
            self.svc._adoptions[PID_B] = {**self.svc._adoptions[PID_B], "pull_state": "merged"}
        self.refused(PID_B, approve.MERGED)


class PlanApproveRunTest(ApproveCase):
    def test_the_view_says_applying_while_the_run_is_under_way(self):
        gate = threading.Event()
        self.ready(apply_result=APPLIED, apply_block=gate)
        self.addCleanup(gate.set)
        self.assertEqual(self.approve_plan()[0], 204)
        shown = self.view()["registration"]
        self.assertEqual(shown["status"], "done")
        self.assertEqual(shown["adoption"]["status"], "running")
        self.assertEqual(shown["adoption"]["headline"],
                         "Applying the adoption of reconcile and opening its pull request…")
        self.assertIsNone(shown["approve"])
        gate.set()
        self.assertEqual(self.until("opened")["adoption"]["status"], "done")

    def test_a_green_apply_pushes_and_opens_one_pull_request_against_the_integration_branch(self):
        fake = self.ready(apply_result=APPLIED)
        shown, errors = self.run_approval("opened")
        self.assertEqual(fake.applied, [(PID_B, False)])
        self.assertEqual(self.pusher.calls, [(str(self.repo), BRANCH, COMMIT)])
        self.assertEqual(self.forge.calls, [
            ("find", "fixture/r", BRANCH, "develop"),
            ("open", "fixture/r", BRANCH, "develop", "Adopt reconcile onto the agent platform",
             approve.body(self.planned, attempt_of(self.forge.calls[1][5])))])
        self.assertEqual(self.steps(), ["applied", "opened"])
        self.assertEqual(shown["adoption"], {
            "status": "done", "step": "opened", "state": "open",
            "headline": "The pull request of reconcile is not ready to merge yet.",
            "lines": [],
            "note": None, "branch": BRANCH, "commit": COMMIT, "url": URL})
        self.assertIsNone(shown["approve"])
        self.assertEqual(shown["line"], shown["adoption"]["headline"])
        self.assertEqual(self.view()["registration"]["lines"], [])
        self.assertTrue(errors.rstrip().endswith("console: plan_approve_ended opened"))

    def test_a_failed_gate_is_shown_with_its_reason_and_nothing_is_pushed(self):
        fake = self.ready(apply_result=GATE)
        kept = self.home / ".agents/state/adopt/worktrees" / ("b" * 64)
        kept.mkdir(parents=True)
        record = adopt_apply.failure_record_path("b" * 64)
        record.write_text(json.dumps({"branch": BRANCH, "worktree": str(kept)}))
        before = self.heads()
        shown, errors = self.run_approval("apply_failed")
        adoption = self.card_words()
        self.assertEqual(shown["line"], "Register reconcile: needs you")
        self.assertEqual(
            adoption["headline"],
            "The adoption of reconcile was not applied: the cold-clone-resolves check did not "
            "pass.")
        self.assertEqual(adoption["lines"], [])
        self.assertEqual(
            adoption["note"],
            "Fix what failed in the repository, then register the repository again.")
        self.assertEqual((self.pusher.calls, self.forge.calls), ([], []))
        self.assertEqual(self.heads(), before)
        self.assertEqual(self.steps(), ["apply_failed"])
        self.assertEqual(shown["approve"], "approve")
        logged = [line for line in errors.splitlines() if line.startswith(ERROR_LINE)]
        self.assertEqual(len(logged), 1)
        self.assertIn('"stage": "apply"', logged[0])
        self.assertIn("adopt.gate.cold-clone-resolves", logged[0])
        for text in (adoption["headline"], *adoption["lines"], adoption["note"]):
            for word in PLAIN_WORDS:
                self.assertNotIn(word, text)
        self.assertEqual(len(fake.applied), 1)

    def test_a_drifted_plan_says_to_register_again_and_nothing_is_pushed(self):
        self.ready(apply_result=STALE_ERROR)
        self.run_approval("apply_failed")
        adoption = self.card_words()
        self.assertEqual(
            adoption["headline"],
            "The adoption of reconcile was not applied: the repository changed since this plan "
            "was made.")
        self.assertEqual(adoption["note"],
                         "Register the repository again to make a new plan, then apply that one.")
        self.assertEqual(adoption["lines"], [])
        self.assertEqual((self.pusher.calls, self.forge.calls), ([], []))

    def test_a_run_that_failed_ends_in_words_and_nothing_is_pushed(self):
        fake = self.ready(apply_raises=register.RunFailed("timed_out"))
        self.run_approval("apply_failed")
        adoption = self.card_words()
        self.assertTrue(adoption["headline"].endswith(": it took too long and was stopped."))
        self.assertTrue(adoption["note"].startswith("Choose Apply it again."))
        fake.apply_raises = KeyError("x")
        _, errors = self.run_approval("apply_failed")
        self.assertTrue(self.card_words()["headline"].endswith(": it stopped unexpectedly."))
        self.assertTrue(any(line.startswith(ERROR_LINE) and '"exception": "KeyError"' in line
                            for line in errors.splitlines()))
        self.assertEqual((self.pusher.calls, self.forge.calls), ([], []))
        self.assertEqual(len(fake.applied), 2)

    def test_a_refused_push_keeps_the_branch_and_try_again_resumes_at_the_push(self):
        self.pusher.raises = [approve.PushFailed("remote rejected the push", "stderr detail")]
        fake = self.ready(apply_result=APPLIED)
        shown, errors = self.run_approval("push_failed")
        adoption = self.card_words()
        self.assertEqual(
            adoption["headline"],
            "The adoption of reconcile was applied, but its branch was not pushed: remote "
            "rejected the push.")
        self.assertEqual(adoption["lines"], [])
        self.assertEqual(adoption["note"], approve.PUSH_NOTE)
        self.assertEqual(shown["approve"], "retry")
        self.assertEqual(self.forge.calls, [])
        self.assertEqual(self.steps(), ["applied", "push_failed"])
        self.assertTrue(any(line.startswith(ERROR_LINE) and '"stage": "push"' in line
                            for line in errors.splitlines()))
        shown, _ = self.run_approval("opened")
        self.assertEqual(len(fake.applied), 1)
        self.assertEqual(self.pusher.calls, [(str(self.repo), BRANCH, COMMIT)] * 2)
        self.assertEqual(shown["adoption"]["step"], "opened")
        self.assertEqual(len(self.opens()), 1)

    def stale_row(self, plan_id):
        """The ready row an earlier console saved: its draft carries the retired light-lane field."""
        light = {"field": "light-lane", "label": "light lane",
                 "value": '{"mode": "shadow", "budget_minutes": 90, "risk_paths": []}',
                 "source": "owner", "options": [{"value": "none", "label": "It has no light lane"}],
                 "text": True, "reason": None, "ask": "What is the light lane of reconcile?"}
        row = self.planned
        self.assertEqual((row["state"], row["plan_id"]), ("ready", plan_id))
        reading = {"remotes": [], "default_branch": "develop", "branches": ["develop"],
                   "files": [], "texts": {}}
        fields = contract_draft.draft(str(self.repo), reading)
        at = [f["field"] for f in fields].index("attempt-budget") + 1
        return {**row, "draft": [*fields[:at], light, *fields[at:]]}

    def test_an_upgraded_ready_row_with_a_resumable_adoption_still_resumes_it(self):
        self.pusher.raises = [approve.PushFailed("remote rejected the push", "stderr detail")]
        fake = self.ready(apply_result=APPLIED)
        self.run_approval("push_failed")
        stale = self.stale_row(PID_B)
        self.svc.log.append([(event_log.REGISTRATION_ENDED, None, stale)])
        self.restart()
        self.assertEqual(self.view()["registration"]["approve"], "retry")
        self.assertEqual(self.svc._adoptions[PID_B]["step"], "push_failed")
        self.assertEqual(self.svc._registration["state"], "ready")
        shown, _ = self.run_approval("opened")
        self.assertEqual(shown["adoption"]["step"], "opened")
        self.assertEqual(len(fake.applied), 1)
        self.assertEqual(len(self.opens()), 1)

    def test_a_refused_pull_request_is_shown_in_words_and_logged_in_full(self):
        self.forge.open_raises = [ForgeError("gh_failed", "gh: Validation Failed (HTTP 422)")]
        fake = self.ready(apply_result=APPLIED)
        shown, errors = self.run_approval("open_failed")
        adoption = self.card_words()
        self.assertEqual(
            adoption["headline"],
            "The adoption of reconcile was pushed, but its pull request was not opened: the "
            "forge refused the pull request.")
        self.assertEqual(
            adoption["note"],
            "Check on the forge that the adoption's branch differs from develop and has no pull "
            "request open already, then choose Try again.")
        for text in (adoption["headline"], *adoption["lines"], adoption["note"]):
            for word in ("HTTP", "422", "gh_failed"):
                self.assertNotIn(word, text)
        logged = [line for line in errors.splitlines() if line.startswith(ERROR_LINE)]
        self.assertEqual(len(logged), 1)
        for part in ('"stage": "open"', '"code": "gh_failed"', "HTTP 422"):
            self.assertIn(part, logged[0])
        self.assertEqual(shown["approve"], "retry")
        self.assertEqual([call[0] for call in self.forge.calls], ["find", "open", "find"])
        shown, _ = self.run_approval("opened")
        self.assertEqual(len(self.pusher.calls), 1)
        self.assertEqual(len(self.opens()), 2)
        self.assertEqual(shown["adoption"]["step"], "opened")
        self.assertEqual(len(fake.applied), 1)

    def test_a_pull_request_whose_answer_was_lost_is_found_not_opened_twice(self):
        self.forge.lost = [ForgeError("gh_timeout", "api")]
        self.forge.find_raises = [None, ForgeError("gh_timeout", "api")]
        fake = self.ready(apply_result=APPLIED)
        shown, _ = self.run_approval("open_failed")
        self.assertTrue(self.card_words()["headline"].endswith(
            ": the forge took too long to answer."))
        self.assertEqual(shown["approve"], "retry")
        self.restart()
        shown, _ = self.run_approval("opened")
        self.assertEqual(len(self.opens()), 1)
        self.assertEqual(shown["adoption"]["url"], URL)
        self.assertEqual(len(fake.applied), 1)
        self.assertEqual(self.svc._adoptions[PID_B]["pull_request"],
                         {"number": 7, "url": URL, "created": False, "id": 1007})

    def test_a_pull_request_found_after_the_consoles_own_open_failed_is_the_consoles(self):
        self.forge.lost = [ForgeError("gh_timeout", "api")]
        self.ready(apply_result=APPLIED)
        self.run_approval("opened")
        self.assertEqual(len(self.opens()), 1)
        self.assertEqual(self.svc._adoptions[PID_B]["pull_request"],
                         {"number": 7, "url": URL, "created": True, "id": 1007})

    def test_an_origin_that_is_not_on_github_opens_nothing(self):
        self.ready(apply_result=APPLIED)
        self.kwargs["slug_of"] = lambda root: None
        self.restart()
        self.run_approval("open_failed")
        (card,) = self.apply_cards()
        self.assertEqual(card["why"], approve.NO_SLUG_NOTE)
        self.assertEqual(
            card["headline"],
            "The adoption of reconcile was pushed, but its pull request was not opened: the "
            "repository's origin is not on GitHub.")
        for text in (card["why"], card["headline"]):
            self.assertIsNone(re.search(
                r"--plan-id|sha256:|[0-9a-f]{12,}|(?:^|[\s(\"'])/\S", text))
        self.assertEqual(self.forge.calls, [])
        self.assertEqual(len(self.pusher.calls), 1)

    def test_a_contract_with_no_integration_branch_names_no_branch(self):
        self.ready(apply_result={k: v for k, v in APPLIED.items() if k != "integration_branch"})
        self.run_approval("open_failed")
        (card,) = self.apply_cards()
        self.assertEqual(card["why"], approve.NO_BASE_NOTE)
        self.assertNotIn(BRANCH, card["why"])

    def test_deletions_are_acknowledged_only_when_the_page_showed_them(self):
        fake = self.ready(plan=WITH_DELETION, apply_result=APPLIED)
        self.assertTrue(any(line.startswith("deletes ") for line in self.planned["lines"]))
        self.assertEqual(self.apply_cards()[0]["lines"], self.planned["lines"])
        self.run_approval("opened")
        self.assertEqual(fake.applied, [(PID_B, True)])

    def test_plain_lines_acknowledge_nothing(self):
        fake = self.ready(apply_result=APPLIED)
        self.run_approval("opened")
        self.assertEqual(fake.applied, [(PID_B, False)])


class AdoptionPollTest(ApproveCase):
    def test_a_ready_pull_request_raises_one_inbox_item_with_its_link(self):
        self.opened()
        self.poll("ready")
        pulls = self.pulls()
        self.assertEqual(len(pulls), 1)
        self.assertEqual(self.items(), [{
            "type": "inbox_item", "reason": "adoption", "key": f"adoption/{PID_B}",
            "project_id": "o/r", "name": "reconcile",
            "headline": "The adoption of o/r is ready to merge", "url": URL, "number": 7,
            "answered": False, "waiting_since": self.svc._adoptions[PID_B]["pull_at"],
            "plan_id": PID_B, "number": 7, "commit": COMMIT, "merge": True, "why": None}])
        self.assertEqual(self.view()["statement"]["inbox_items"], 1)
        self.assertEqual(self.adoption()["headline"],
                         "The pull request of reconcile is ready to merge.")
        self.assertEqual(self.forge.calls[-1], ("state", "fixture/r", 7))

    def test_a_merged_pull_request_closes_the_item(self):
        fake = self.opened()
        fake.report = NOT_INTEGRATED
        self.poll("ready")
        self.poll("merged")
        self.assertEqual(self.items(), [])
        self.assertEqual(self.adoption()["headline"],
                         "The pull request of reconcile was merged; waiting for develop on "
                         "origin to carry it before registering.")
        self.assertIsNone(self.adoption()["note"])

    def test_a_closed_pull_request_closes_the_item(self):
        self.opened()
        self.poll("ready")
        self.poll("closed")
        self.assertEqual(self.items(), [])
        self.assertEqual(self.card_words()["headline"],
                         "The pull request of reconcile was closed without merging.")
        self.assertEqual(self.view()["registration"]["line"], "Register reconcile: needs you")

    def test_a_closed_adoption_asks_for_a_clean_up_and_is_approved_again_with_the_same_plan(self):
        fake = self.opened()
        self.poll("ready")
        self.poll("closed")
        self.assertEqual(self.card_words()["note"], approve.CLOSED_NOTE)
        self.assertEqual(self.view()["registration"]["approve"], "approve")
        self.forge.mark_closed(7)
        shown = self.registered(self.repo)
        self.assertEqual((shown["plan_id"], shown["approve"]), (PID_B, "approve"))
        self.run_approval("opened")
        self.assertEqual(len(fake.applied), 2)
        self.assertEqual(len(self.opens()), 2)
        self.assertEqual(self.svc._adoptions[PID_B]["pull_request"]["number"], 8)
        self.assertEqual(self.adoption()["state"], "open")
        self.assertEqual(self.items(), [])

    def test_a_merged_adoption_is_not_approved_again(self):
        fake = self.opened()
        fake.report = NOT_INTEGRATED
        self.poll("ready")
        self.poll("merged")
        self.assertIsNone(self.view()["registration"]["approve"])
        self.assertIsNone(self.adoption()["note"])
        steps = self.steps()
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            status, _, body = self.approve_plan()
        self.assertEqual((status, body), (409, approve.MERGED.encode() + b"\n"))
        self.assertEqual(len(fake.applied), 1)
        self.assertEqual(self.steps(), steps)

    def test_a_found_pull_request_is_the_one_polled(self):
        self.forge.lost = [ForgeError("gh_timeout", "api")]
        self.forge.find_raises = [None, ForgeError("gh_timeout", "api")]
        self.ready(apply_result=APPLIED)
        self.run_approval("open_failed")
        self.restart()
        self.run_approval("opened")
        self.forge.calls.clear()
        self.poll("ready")
        self.assertEqual(self.forge.calls, [("state", "fixture/r", 7)])
        self.assertEqual([i["url"] for i in self.items()], [URL])

    def test_the_poll_reads_the_repository_the_pull_request_was_opened_in(self):
        self.opened()
        for moved in (lambda root: None, lambda root: "other/unrelated"):
            self.kwargs["slug_of"] = moved
            self.restart()
            self.forge.calls.clear()
            self.poll("ready")
            self.assertEqual(self.forge.calls, [("state", "fixture/r", 7)])
        self.assertEqual([i["url"] for i in self.items()], [URL])

    def test_a_pull_request_that_is_no_longer_ready_closes_the_item(self):
        self.opened()
        self.poll("ready")
        self.poll("open")
        self.assertEqual(self.items(), [])
        self.assertEqual(self.adoption()["headline"],
                         "The pull request of reconcile is not ready to merge yet.")

    def test_an_unchanged_state_appends_nothing(self):
        self.opened()
        self.poll("open")
        self.assertEqual(len(self.pulls()), 1)
        self.poll("open")
        self.assertEqual(len(self.pulls()), 1)
        self.poll("ready")
        self.poll("ready")
        self.assertEqual(len(self.pulls()), 2)

    def test_a_finished_pull_request_is_read_no_more(self):
        self.opened()
        self.poll("merged")
        self.forge.calls.clear()
        self.svc.poll_adoptions()
        self.assertEqual([c for c in self.forge.calls if c[0] == "state"], [])

    def test_a_failed_read_keeps_the_item_and_logs_one_line(self):
        self.opened()
        self.poll("ready")
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            self.poll(ForgeError("gh_timeout", "api"))
        lines = [l for l in errors.getvalue().splitlines()
                 if l.startswith("console: adoption_poll_failed sha256:")]
        self.assertEqual(len(lines), 1)
        self.assertEqual(len(self.items()), 1)
        self.assertEqual(len(self.pulls()), 1)

    def test_the_item_survives_a_restart(self):
        self.opened()
        self.poll("ready")
        before = self.items()
        self.assertEqual(len(before), 1)
        self.restart()
        self.assertEqual(self.items(), before)

    def test_the_poll_thread_reads_at_once_when_started(self):
        self.opened()
        self.forge.calls.clear()
        self.restart()
        end = time.monotonic() + 10
        while time.monotonic() < end and ("state", "fixture/r", 7) not in self.forge.calls:
            time.sleep(0.05)
        self.assertIn(("state", "fixture/r", 7), self.forge.calls)


class AdoptionMergeTest(ApproveCase):
    def green(self):
        fake = self.opened(fake_class=RegistryFake, registry=self.registry)
        fake.report = GREEN
        return fake

    def refused_merge(self, text, **arguments):
        (status, body), errors = self.logged_merge(**arguments)
        self.assertEqual((status, body), (409, text.encode() + b"\n"))
        self.assertEqual(self.merged_calls(), [])
        return errors

    def test_a_ready_pull_request_at_its_recorded_head_is_merged_at_that_head_and_registered(self):
        self.green()
        self.poll("ready")
        (item,) = self.items()
        self.assertIs(item["merge"], True)
        self.assertIsNone(item["why"])
        (status, body), errors = self.logged_merge()
        self.assertEqual((status, body), (204, b""))
        self.assertEqual(self.merged_calls(), [("merge", "fixture/r", 7, COMMIT)])
        self.assertEqual((self.last_pull()["state"], self.last_pull()["head"]), ("merged", COMMIT))
        self.assertEqual(self.settled(1)[-1]["result"], "registered")
        self.assertTrue(self.listed("o/r"))
        self.assertEqual(self.items(), [])
        self.assertIn(f"console: adoption_merge_ended {PID_B} merged", errors)

    def test_a_moved_head_offers_no_merge_and_says_why(self):
        self.opened()
        self.forge.heads[7] = "d" * 40
        self.poll("ready")
        (item,) = self.items()
        self.assertIs(item["merge"], False)
        self.assertEqual(item["why"], approve.MOVED_WHY)
        pulls = self.pulls()
        self.refused_merge(approve.MOVED)
        self.assertEqual(self.pulls(), pulls)

    def test_a_failed_check_offers_no_merge_and_says_why(self):
        self.opened()
        self.poll("failing")
        (item,) = self.items()
        self.assertIs(item["merge"], False)
        self.assertEqual(item["why"], approve.FAILING_WHY)
        self.refused_merge(approve.FAILING)

    def test_a_closed_pull_request_offers_no_merge_and_says_why(self):
        self.opened()
        self.poll("ready")
        self.poll("closed")
        self.assertEqual(self.items(), [])
        self.assertEqual(self.card_words()["headline"],
                         "The pull request of reconcile was closed without merging.")
        self.refused_merge(approve.CLOSED_PULL)

    def test_a_closed_pull_request_of_an_earlier_registration_keeps_its_reason(self):
        self.opened()
        self.poll("ready")
        self.poll("closed")
        self.assertEqual(self.items(), [])
        self.registered(git_repo(self.parent / "r2"))
        apply = len(self.apply_cards())
        (item,) = self.items()
        self.assertEqual((item["plan_id"], item["merge"], item["why"]),
                         (PID_B, False, approve.CLOSED_WHY))
        self.assertEqual(len(self.apply_cards()), apply)

    def test_a_pull_request_the_console_did_not_open_offers_no_merge(self):
        self.forge.pulls[(APPLIED["branch"], APPLIED["integration_branch"])] = 7
        self.forge.texts[7] = ("Someone else's change", "another body")
        self.ready(apply_result=APPLIED)
        self.run_approval("opened")
        self.assertEqual(self.opens(), [])
        self.assertIs(self.svc._adoptions[PID_B]["pull_request"]["created"], False)
        self.poll("ready")
        (item,) = self.items()
        self.assertIs(item["merge"], False)
        self.assertEqual(item["why"], approve.FOUND_WHY)
        self.refused_merge(approve.FOUND)

    def test_a_manual_pull_request_that_copies_the_consoles_words_is_not_the_consoles(self):
        self.forge.pulls[(APPLIED["branch"], APPLIED["integration_branch"])] = 7
        self.forge.texts[7] = (approve.title("reconcile"),
                               "Copied by hand. " + approve.signature(PID_B))
        self.ready(apply_result=APPLIED)
        self.run_approval("opened")
        self.assertEqual(self.opens(), [])
        self.assertIs(self.svc._adoptions[PID_B]["pull_request"]["created"], False)
        self.poll("ready")
        (item,) = self.items()
        self.assertEqual((item["merge"], item["why"]), (False, approve.FOUND_WHY))
        self.refused_merge(approve.FOUND)

    def test_a_pull_request_with_the_consoles_words_but_not_its_attempt_is_not_the_consoles(self):
        self.forge = RacingForge()
        self.ready(apply_result=APPLIED)
        self.run_approval("opened")
        self.assertEqual(len(self.opens()), 1)
        self.assertEqual(self.svc._adoptions[PID_B]["pull_request"],
                         {"number": 7, "url": URL, "created": False, "id": 1007})
        self.poll("ready")
        (item,) = self.items()
        self.assertEqual((item["merge"], item["why"]), (False, approve.FOUND_WHY))
        self.refused_merge(approve.FOUND)

    def test_a_pull_request_retargeted_after_the_last_poll_is_not_merged_into_its_new_branch(self):
        self.opened()
        self.poll("ready")
        self.assertIs(self.items()[0]["merge"], True)
        self.forge.bases[7] = "release"
        errors = self.refused_merge(approve.RETARGETED)
        self.assertIn("console: adoption_merge_refused", errors)
        self.assertEqual((self.last_pull()["state"], self.last_pull()["base"]),
                         ("ready", "release"))
        (item,) = self.items()
        self.assertEqual((item["merge"], item["why"]), (False, approve.RETARGETED_WHY))

    def test_a_reading_rejected_as_stale_does_not_authorize_a_merge_into_the_old_branch(self):
        self.opened()
        self.poll("ready")
        self.forge.read_pause = threading.Event()
        self.forge.pause_after = self.forge.reads
        answers = []
        clicker = threading.Thread(target=lambda: answers.append(self.logged_merge()))
        clicker.start()
        self.assertTrue(self.forge.read_entered.wait(10))
        self.assertTrue(self.svc._record_reading(
            PID_B, 7, {"state": "ready", "head": COMMIT, "base": "release", "id": 1007}))
        self.forge.read_pause.set()
        clicker.join(30)
        (((status, body), _),) = answers
        self.assertEqual((status, body), (409, approve.RETARGETED.encode() + b"\n"))
        self.assertEqual(self.merged_calls(), [])
        self.assertEqual((self.last_pull()["state"], self.last_pull()["base"]),
                         ("ready", "release"))

    def test_a_replacement_repository_that_reuses_the_name_and_number_is_not_merged(self):
        self.green()
        self.poll("ready")
        self.assertIs(self.items()[0]["merge"], True)
        pulls = self.pulls()
        self.forge.ids[7] = 5007
        errors = self.refused_merge(approve.FOUND)
        self.assertIn("console: adoption_merge_refused", errors)
        self.poll("merged")
        self.assertEqual(self.pulls(), pulls)
        self.assertEqual(self.registrations(), [])

    def test_a_pull_request_the_forge_gave_no_id_offers_no_merge(self):
        self.opened()
        with self.svc._ingest:
            found = self.svc._adoptions[PID_B]
            found["pull_request"] = {key: value for key, value in found["pull_request"].items()
                                     if key != "id"}
        self.poll("ready")
        (item,) = self.items()
        self.assertEqual((item["merge"], item["why"]), (False, approve.FOUND_WHY))
        self.refused_merge(approve.FOUND)

    def test_a_merge_recovered_into_another_branch_is_not_acknowledged(self):
        self.green()
        self.poll("ready")
        self.forge.merge_raises = [ForgeError("gh_timeout", "api")]
        self.forge.before_merge = lambda: (self.forge.states.update({7: "merged"}),
                                           self.forge.bases.update({7: "release"}))
        self.assertEqual(self.merge(), (409, approve.MERGED_ELSEWHERE_BASE.encode() + b"\n"))
        self.assertEqual((self.last_pull()["state"], self.last_pull()["base"]),
                         ("merged", "release"))
        self.settled(1)

    def test_a_click_on_a_card_whose_step_was_applied_again_is_refused_in_words(self):
        self.opened()
        self.poll("ready")
        self.poll("closed")
        self.forge.mark_closed(7)
        self.registered(self.repo)
        self.forge.open_raises = [ForgeError("gh_failed", "gh: Unprocessable (HTTP 422)")]
        self.run_approval("open_failed")
        self.assertIsNone(self.svc._adoptions[PID_B]["pull_request"])
        self.refused_merge(approve.NO_PULL, number=7, commit=COMMIT)

    def test_a_registration_that_cannot_be_dispatched_does_not_undo_an_acknowledged_merge(self):
        def refusing(job):
            raise RuntimeError("no thread")

        self.green()
        self.poll("ready")
        dispatch, self.svc._approval_dispatch = self.svc._approval_dispatch, refusing
        (status, body), errors = self.logged_merge()
        self.assertEqual((status, body), (204, b""))
        self.assertEqual((self.last_pull()["state"], self.last_pull()["head"]), ("merged", COMMIT))
        self.assertIn("console: adoption_register_dispatch_failed RuntimeError", errors)
        self.assertEqual(self.register_calls(), [])
        self.svc._approval_dispatch = dispatch
        self.svc.poll_adoptions()
        self.settled(1)
        self.assertEqual(len(self.register_calls()), 1)

    def test_a_pull_request_retargeted_since_it_was_opened_offers_no_merge(self):
        self.opened()
        self.forge.bases[7] = "release"
        self.poll("ready")
        (item,) = self.items()
        self.assertEqual((item["merge"], item["why"]), (False, approve.RETARGETED_WHY))
        self.refused_merge(approve.RETARGETED)
        self.forge.bases[7] = "develop"
        self.poll("ready")
        self.assertIs(self.items()[0]["merge"], True)

    def test_a_click_from_a_replaced_pull_requests_card_merges_nothing(self):
        self.opened()
        self.poll("ready")
        self.poll("closed")
        self.forge.mark_closed(7)
        self.registered(self.repo)
        self.run_approval("opened")
        self.poll("ready", number=8)
        self.refused_merge(approve.STALE_CARD, number=7, commit=COMMIT)
        self.assertEqual(self.forge.states[8], "ready")
        self.assertFalse([p for _, p in self.pulls() if p["number"] == 8 and p["state"] == "merged"])

    def test_a_head_moved_since_the_last_read_is_refused_by_the_forge_and_the_card_says_why(self):
        self.opened()
        self.poll("ready")
        self.forge.merge_raises = [ForgeError("gh_failed", "gh: Head branch was modified (HTTP 409)")]
        self.forge.before_merge = lambda: self.forge.heads.update({7: "d" * 40})
        (status, body), errors = self.logged_merge()
        self.assertEqual((status, body), (409, approve.MOVED.encode() + b"\n"))
        self.assertEqual(self.merged_calls(), [("merge", "fixture/r", 7, COMMIT)])
        self.assertEqual((self.last_pull()["head"], self.last_pull()["state"]), ("d" * 40, "ready"))
        (item,) = self.items()
        self.assertIs(item["merge"], False)
        self.assertIn("console: adoption_merge_error ", errors)
        for word in PLAIN_WORDS:
            self.assertNotIn(word, body.decode())

    def test_a_lost_answer_after_the_forge_merged_at_the_recorded_head_registers(self):
        self.green()
        self.poll("ready")
        self.forge.merge_raises = [ForgeError("gh_timeout", "api")]
        self.forge.before_merge = lambda: self.forge.states.update({7: "merged"})
        self.assertEqual(self.merge(), (204, b""))
        self.assertEqual((self.last_pull()["state"], self.last_pull()["head"]), ("merged", COMMIT))
        self.settled(1)
        self.assertEqual(len(self.register_calls()), 1)

    def test_a_refused_merge_then_a_merge_at_another_head_is_not_acknowledged(self):
        self.green()
        self.poll("ready")
        self.forge.merge_raises = [ForgeError("gh_failed", "gh: Head branch was modified (HTTP 409)")]
        self.forge.before_merge = lambda: (self.forge.states.update({7: "merged"}),
                                           self.forge.heads.update({7: "d" * 40}))
        self.assertEqual(self.merge(), (409, approve.MERGED_ELSEWHERE.encode() + b"\n"))
        self.assertEqual((self.last_pull()["state"], self.last_pull()["head"]), ("merged", "d" * 40))
        self.assertFalse([p for _, p in self.pulls()
                          if p["state"] == "merged" and p["head"] == COMMIT])
        self.settled(1)

    def test_a_failed_merge_whose_re_read_fails_says_the_forge_words(self):
        self.opened()
        self.poll("ready")
        pulls = self.pulls()
        self.forge.merge_raises = [ForgeError("gh_timeout", "api")]
        self.forge.before_merge = lambda: self.forge.states.update(
            {7: ForgeError("gh_timeout", "api")})
        (status, body), errors = self.logged_merge()
        self.assertEqual((status, body), (409, b"the forge took too long to answer\n"))
        self.assertIn("console: adoption_poll_failed", errors)
        self.assertEqual(self.pulls(), pulls)

    def test_a_cancelled_merge_says_the_console_is_stopping(self):
        self.opened()
        self.poll("ready")
        pulls = self.pulls()
        self.forge.merge_raises = [approve.Cancelled()]
        self.assertEqual(self.merge(), (409, register.STOPPING.encode() + b"\n"))
        self.assertEqual(self.pulls(), pulls)

    def test_an_unread_or_malformed_head_offers_no_merge_until_a_matching_read(self):
        self.opened()
        self.forge.heads[7] = None
        self.poll("ready")
        (item,) = self.items()
        self.assertIs(item["merge"], False)
        self.assertEqual(item["why"], approve.UNREAD_WHY)
        self.refused_merge(approve.UNREAD)
        self.forge.heads[7] = COMMIT
        self.poll("ready")
        self.assertIs(self.items()[0]["merge"], True)
        count = len(self.pulls())
        self.forge.heads[7] = None
        self.poll("ready")
        self.assertEqual(len(self.pulls()), count + 1)
        self.assertIs(self.items()[0]["merge"], False)

    def test_a_moved_head_whose_checks_could_not_be_read_stops_offering_merge(self):
        self.opened()
        self.poll("ready")
        self.assertIs(self.items()[0]["merge"], True)
        self.forge.heads[7] = "d" * 40
        self.forge.unread[7] = ForgeError("gh_timeout", "api")
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            self.poll("open")
        self.assertIn(f"console: adoption_poll_failed {PID_B} ForgeError", errors.getvalue())
        (item,) = self.items()
        self.assertEqual((item["merge"], item["why"]), (False, approve.MOVED_WHY))
        self.refused_merge(approve.MOVED)

    def test_a_failing_pull_request_stays_failing_while_its_checks_cannot_be_read(self):
        self.opened()
        self.poll("failing")
        count = len(self.pulls())
        self.forge.unread[7] = ForgeError("gh_timeout", "api")
        with contextlib.redirect_stderr(io.StringIO()):
            self.poll("open")
        self.assertEqual(len(self.pulls()), count)
        (item,) = self.items()
        self.assertEqual(item["why"], approve.FAILING_WHY)

    def test_a_confirmation_read_that_finished_after_a_newer_reading_is_not_recorded(self):
        self.opened()
        self.poll("ready")
        self.forge.merge_raises = [ForgeError("gh_failed", "gh: not mergeable (HTTP 405)")]
        self.forge.read_pause = threading.Event()
        self.forge.pause_after = self.forge.reads + 1
        answers = []
        clicker = threading.Thread(target=lambda: answers.append(self.logged_merge()))
        clicker.start()
        self.assertTrue(self.forge.read_entered.wait(10))
        self.assertTrue(self.svc._record_reading(
            PID_B, 7, {"state": "closed", "head": COMMIT, "base": "develop"}))
        self.forge.read_pause.set()
        clicker.join(30)
        (((status, body), _),) = answers
        self.assertEqual((status, body), (409, approve.CLOSED_PULL.encode() + b"\n"))
        self.assertEqual(self.last_pull()["state"], "closed")
        self.assertEqual(self.svc._adoptions[PID_B]["pull_state"], "closed")
        self.assertFalse([i for i in self.items() if i["merge"]])

    def test_an_obsolete_poll_reading_does_not_undo_a_merge(self):
        self.green()
        self.poll("ready")
        self.forge.read_pause = threading.Event()
        self.forge.pause_after = self.forge.reads
        poller = threading.Thread(target=self.svc.poll_adoptions)
        poller.start()
        self.assertTrue(self.forge.read_entered.wait(10))
        self.assertEqual(self.merge(), (204, b""))
        self.forge.read_pause.set()
        poller.join(30)
        self.assertEqual(self.last_pull()["state"], "merged")
        self.assertEqual(self.items(), [])
        self.settled(1)
        self.assertEqual(len(self.register_calls()), 1)

    def blocked_click(self):
        self.opened()
        self.poll("ready")
        self.forge.merge_block = threading.Event()
        answers = []
        clicker = threading.Thread(target=lambda: answers.append(self.merge()))
        clicker.start()
        self.assertTrue(self.forge.merge_entered.wait(10))
        return clicker, answers

    def test_a_second_click_while_merging_is_refused(self):
        clicker, answers = self.blocked_click()
        self.assertEqual(self.merge(), (409, approve.MERGING.encode() + b"\n"))
        self.forge.merge_block.set()
        clicker.join(30)
        self.assertEqual(answers, [(204, b"")])
        self.assertEqual(len(self.merged_calls()), 1)
        self.assertEqual(self.merge(), (409, approve.MERGED.encode() + b"\n"))

    def test_closing_waits_for_an_admitted_merge_to_record_its_outcome(self):
        clicker, answers = self.blocked_click()
        closer = threading.Thread(target=self.svc.close)
        closer.start()
        closer.join(3)
        self.assertTrue(closer.is_alive())
        self.forge.merge_block.set()
        clicker.join(30)
        closer.join(30)
        self.assertEqual(answers, [(204, b"")])
        self.assertEqual(json.loads(support.log_rows(self.store)[-1][4])["state"], "merged")

    def test_a_refusal_appends_nothing_and_logs_one_line(self):
        self.opened()
        self.poll("open")
        before = support.log_rows(self.store)
        errors = self.refused_merge(approve.NOT_READY_PULL)
        self.assertEqual(support.log_rows(self.store), before)
        self.assertEqual(errors.count("console: adoption_merge_refused"), 1)

    def test_a_console_without_a_forge_refuses_the_merge(self):
        self.start(Fake(plan=READY), forge=None)
        self.refused_merge(approve.MERGE_UNAVAILABLE, number=7, commit=COMMIT)

    def test_a_stopping_console_refuses_the_merge(self):
        self.opened()
        self.poll("ready")
        self.svc._stop.set()
        self.refused_merge(register.STOPPING)


class PlanApproveFailingTest(ApproveCase):
    def test_a_failing_pull_request_is_not_applied_again(self):
        fake = self.opened()
        self.poll("failing")
        steps = self.steps()
        self.refused(PID_B, approve.OPENED)
        self.assertEqual(self.steps(), steps)
        self.assertEqual(len(fake.applied), 1)


class AdoptionMergeGuardTest(ApproveCase):
    def test_the_merge_is_refused_without_the_page_origin_and_token_and_merges_nothing(self):
        self.opened()
        self.poll("ready")
        before = support.log_rows(self.store)
        json_type = {"Content-Type": "application/json"}
        token = self.token_file.read_text().strip()
        own = f"http://127.0.0.1:{self.svc.address[1]}"
        for headers, text in (
                ({"X-Console-Token": token, **json_type}, b"origin refused\n"),
                ({"Origin": own, **json_type}, b"token refused\n"),
                ({"Origin": own, "X-Console-Token": "wrong", **json_type}, b"token refused\n"),
                ({"Origin": "http://evil.example", "X-Console-Token": token, **json_type},
                 b"origin refused\n")):
            with self.subTest(text=text, headers=sorted(headers)):
                self.assertEqual(self.merge(headers=headers), (403, text))
        self.assertEqual(support.log_rows(self.store), before)
        self.assertEqual([c for c in self.forge.calls if c[0] == "merge"], [])

    def test_the_route_is_an_owner_page_write_and_no_manager_or_guest_route(self):
        self.opened()
        self.assertIn(service.ADOPTION_MERGE_PATH, service.PAGE_WRITES)
        self.assertIn(service.ADOPTION_MERGE_PATH, service.OWNER_ONLY)
        self.assertNotIn(service.ADOPTION_MERGE_PATH, service.GUEST_WRITES)
        self.assertNotIn(service.ADOPTION_MERGE_PATH, service.MANAGER_WRITES)
        status, headers, _ = support.request(self.svc.address, "GET", MERGE_PATH)
        self.assertEqual((status, headers["Allow"]), (405, "POST"))
        sent = self.own(**{"Content-Type": "application/json"})
        for body in ({}, {"plan_id": PID_B}):
            with self.subTest(body=body):
                status, _, text = support.post_page(
                    self.svc.address, MERGE_PATH, sent, json.dumps(body).encode())
                self.assertEqual((status, text), (400, b"bad adoption merge\n"))


class PlanApproveCloseTest(ApproveCase):
    def test_a_registration_queued_behind_a_kept_copy_starts_no_discard_after_the_stop(self):
        fake = self.answer_after_a_failed_apply()
        self.kept(PID_B)
        queued = []
        self.kwargs["dispatch"] = queued.append
        self.restart()
        self.assertEqual(self.post({"path": str(self.repo)})[0], 204)
        self.assertEqual(len(queued), 1)
        before = list(fake.order)
        closer, errors = closing(self.svc)
        assert_held(self, closer)
        queued[0]()
        assert_freed(self, closer, errors)
        self.assertEqual(fake.order, before)
        self.assertIsNone(self.svc._registering)

    def test_closing_between_the_push_and_the_pull_request_opens_nothing_and_resumes(self):
        self.pusher.wait_for_stop = True
        fake = self.ready(apply_result=APPLIED)
        self.assertEqual(self.approve_plan()[0], 204)
        self.assertTrue(self.pusher.entered.wait(30))
        self.svc.close()
        self.assertEqual(self.approval_threads(), [])
        self.assertEqual(self.forge.calls, [])
        self.assertEqual(self.steps(), ["applied"])
        self.pusher.wait_for_stop = False
        self.restart()
        self.assertEqual(self.view()["registration"]["approve"], "retry")
        self.run_approval("opened")
        self.assertEqual(len(fake.applied), 1)
        self.assertEqual(len(self.opens()), 1)

    def test_closing_after_apply_succeeded_keeps_its_row_and_a_restart_resumes_at_the_push(self):
        gate = threading.Event()
        self.addCleanup(gate.set)
        fake = self.ready(apply_result=APPLIED, apply_block=gate)
        self.assertEqual(self.approve_plan()[0], 204)
        closing = threading.Thread(target=self.svc.close)
        closing.start()
        end = time.monotonic() + 30
        while time.monotonic() < end and not self.svc._closed:
            time.sleep(0.01)
        self.assertTrue(self.svc._closed)
        gate.set()
        closing.join(30)
        self.assertFalse(closing.is_alive())
        self.assertEqual(self.pusher.calls, [])
        self.assertEqual(self.steps(), ["applied"])
        self.restart()
        self.assertEqual(self.view()["registration"]["approve"], "retry")
        self.run_approval("opened")
        self.assertEqual(len(fake.applied), 1)
        self.assertEqual(len(self.opens()), 1)

    def test_closing_during_a_forge_call_stops_it_and_a_retry_finds_its_pull_request(self):
        self.forge.open_block = True
        self.forge.linger = 1.0
        fake = self.ready(apply_result=APPLIED)
        self.assertEqual(self.approve_plan()[0], 204)
        self.assertTrue(self.forge.entered.wait(30))
        started = time.monotonic()
        self.svc.close()
        self.assertLess(time.monotonic() - started, 5)
        self.assertEqual(self.approval_threads(), [])
        self.assertEqual(self.steps(), ["applied"])
        self.forge.open_block = False
        self.forge.linger = 0.0
        self.restart()
        shown, _ = self.run_approval("opened")
        self.assertEqual(shown["adoption"]["url"], URL)
        self.assertEqual(len(self.opens()), 1)
        self.assertEqual(len(fake.applied), 1)


    def test_an_approval_accepted_before_the_stop_holds_close(self):
        self.ready(apply_result=APPLIED)
        queued = []
        self.svc._approval_dispatch = queued.append
        self.assertEqual(self.approve_plan()[0], 204)
        self.assertEqual(len(queued), 1)
        closer, errors = closing(self.svc)
        assert_held(self, closer)
        queued[0]()
        assert_freed(self, closer, errors)
        self.assertIsNone(self.svc._registering)

    def test_a_failed_approval_thread_start_lists_no_worker(self):
        self.ready(apply_result=APPLIED)
        original = threading.Thread.start

        def start(thread):
            if thread.name == service.APPROVAL_THREAD:
                raise RuntimeError("can't start new thread")
            return original(thread)

        with mock.patch.object(threading.Thread, "start", start):
            status = self.approve_plan()[0]
        self.assertEqual(status, 500)
        self.assertEqual(self.svc._approval_workers, [])
        self.assertIsNone(self.svc._registering)
        self.svc.close()


class CancelReservationTest(CancelChecks, ApproveCase):
    """A cancel keeps its reservation until its row is in the log (#1330)."""

    def setUp(self):
        super().setUp()
        self.arrange_profiles()

    def start(self, fake, **kwargs):
        return super().start(fake, **{**self.trust, **kwargs})

    def test_the_reservation_is_held_while_the_cancellation_is_appended(self):
        self.ready(apply_result=SIGNING)
        self.run_approval("apply_failed")
        self.kept(PID_B)
        held = []
        append = self.svc.log.append

        def recording(events):
            if any(event[0] == event_log.REGISTRATION_CANCELLED for event in events):
                held.append(self.svc._registering)
            return append(events)

        with mock.patch.object(self.svc.log, "append", recording):
            self.assertEqual(self.cancel({"root": str(self.repo)})[::2], (204, b""))
        self.assertEqual(held, [str(self.repo)])
        self.assertIsNone(self.svc._registering)


class CancelCloseTest(CancelChecks, ApproveCase):
    """Close waits for the discard of a Cancel registration, which runs on the request's own thread (#1330)."""

    def setUp(self):
        super().setUp()
        self.arrange_profiles()

    def start(self, fake, **kwargs):
        return super().start(fake, **{**self.trust, **kwargs})

    def test_close_waits_for_the_discard_of_a_cancel(self):
        held = self.answer_after_a_failed_apply(fake_class=Held, hold="discard")
        self.addCleanup(held.release.set)
        git(self.repo, "branch", approve.branch_of(PID_B))
        answers = []
        request = threading.Thread(target=lambda: answers.append(
            self.cancel({"root": str(self.repo)})))
        request.start()
        self.assertTrue(held.entered.wait(10))
        closer, errors = closing(self.svc)
        assert_held(self, closer)
        held.release.set()
        assert_freed(self, closer, errors)
        request.join(10)
        self.assertFalse(request.is_alive())
        self.assertEqual(answers[0][0], 204)


class TrustGrantTest(ApproveCase):
    """The Apply approval grants the folder's trust in every profile and logs it (#1078)."""

    def setUp(self):
        super().setUp()
        self.key = str(self.parent / "reconcile")
        self.arranged = {"oauthAccount": {"emailAddress": "o@example.test"}, "keep": [1, 2],
                         "projects": {self.key: {"allowedTools": ["Bash"]}}}
        self.files = {"default": self.home / ".claude.json"}
        for name in ("work", "solo"):
            directory = self.parent / "accounts" / "profiles" / name
            directory.mkdir(parents=True)
            self.files[name] = directory / ".claude.json"
        self.rearrange()
        self.trust = {"profile_dirs": [self.files[n].parent for n in ("work", "solo")],
                      "trust_home": self.home}
        self.granted = []

    def rearrange(self, names=("default", "work", "solo")):
        for name in names:
            self.files[name].write_text(json.dumps(self.arranged), "utf-8")

    def snapshot(self):
        return {name: (path.read_bytes(), path.stat().st_mtime_ns)
                for name, path in self.files.items()}

    def trusted(self):
        return {**self.arranged, "projects": {self.key: {
            "allowedTools": ["Bash"], "hasTrustDialogAccepted": True}}}

    def start(self, fake, **kwargs):
        return super().start(fake, **{**self.trust, **kwargs})

    def trust_rows(self):
        return [payload for _, payload in self.rows("trust.granted")]

    def parsed(self, name):
        return json.loads(self.files[name].read_text("utf-8"))

    def test_apply_it_sets_the_key_in_both_profiles_and_the_home_file_and_nothing_else(self):
        self.ready(apply_result=APPLIED)
        self.run_approval("opened")
        for name in ("default", "work", "solo"):
            with self.subTest(file=name):
                self.assertEqual(self.parsed(name), self.trusted())

    def test_one_owner_action_row_names_each_profile_and_its_result(self):
        def granter(path, key):
            if path.parent.name == "solo":
                raise RuntimeError("o@example.test")
            return folder_trust.grant(path, key)

        self.trust["trust_granter"] = granter
        self.ready(apply_result=APPLIED)
        _, errors = self.run_approval("opened")
        self.assertEqual(self.trust_rows(), [{
            "by": "owner", "cause": "apply", "project": "o/r", "root": self.key,
            "profiles": [{"profile": "default", "result": "granted"},
                         {"profile": "solo", "result": "failed"},
                         {"profile": "work", "result": "granted"}]}])
        self.assertIn("console: trust_grant_error solo RuntimeError", errors)
        self.assertIn("console: trust_granted apply o/r 2 0 1", errors)
        self.assertNotIn("o@example.test", errors)
        for row in support.log_rows(self.store):
            self.assertNotIn("o@example.test", row[4])

    def test_a_failed_grant_still_applies(self):
        self.trust["trust_granter"] = lambda path, key: folder_trust.FAILED
        self.ready(apply_result=APPLIED)
        self.run_approval("opened")
        self.assertEqual(self.steps()[0], "applied")
        self.assertEqual([p["result"] for p in self.trust_rows()[0]["profiles"]], ["failed"] * 3)

    def test_not_now_try_again_and_the_merged_registration_write_no_trust(self):
        self.pusher.raises = [approve.PushFailed("remote rejected the push", "d")]
        fake = self.ready(apply_result=APPLIED, fake_class=RegistryFake, registry=self.registry)
        fake.report = GREEN
        self.assertEqual(self.defer()[0], 204)
        self.assertEqual(self.trust_rows(), [])
        self.run_approval("push_failed")
        self.assertEqual(len(self.trust_rows()), 1)
        self.rearrange()
        before = self.snapshot()
        self.run_approval("opened")
        self.poll("merged")
        self.assertEqual(len(self.register_calls()), 1)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(len(self.trust_rows()), 1)

    def test_without_a_trust_home_the_home_file_is_not_a_target(self):
        self.trust["trust_home"] = None
        self.ready(apply_result=APPLIED)
        self.run_approval("opened")
        self.assertEqual([p["profile"] for p in self.trust_rows()[0]["profiles"]],
                         ["solo", "work"])
        self.assertEqual(self.parsed("default"), self.arranged)

    def test_a_grant_that_close_overtakes_keeps_its_row(self):
        entered, gate = threading.Event(), threading.Event()
        self.addCleanup(gate.set)

        def granter(path, key):
            if path.parent.name == "work":
                entered.set()
                gate.wait(30)
            return folder_trust.grant(path, key)

        self.trust["trust_granter"] = granter
        self.ready(apply_result=APPLIED)
        granting = threading.Thread(
            target=self.svc._grant_trust, args=("apply", str(self.repo), "p"))
        granting.start()
        self.assertTrue(entered.wait(30))
        closing = threading.Thread(target=self.svc.close)
        closing.start()
        end = time.monotonic() + 30
        while time.monotonic() < end and not self.svc._closed:
            time.sleep(0.01)
        self.assertTrue(self.svc._closed)
        log_closed, close_log = threading.Event(), self.svc.log.close
        self.svc.log.close = lambda: (log_closed.set(), close_log())
        # A close that does not wait for the grant closes the log within this bound.
        log_closed.wait(2)
        gate.set()
        for thread in (granting, closing):
            thread.join(30)
            self.assertFalse(thread.is_alive())
        (row,) = self.trust_rows()
        self.assertEqual([p["profile"] for p in row["profiles"]], ["default", "solo", "work"])
        self.assertEqual(self.parsed("work"), self.trusted())

    CHECK = "/api/trust-check"

    def check(self, body):
        return support.post_page(
            self.svc.address, self.CHECK,
            self.own(**{"Content-Type": "application/json"}), json.dumps(body).encode())

    def trust_cards(self):
        return [card for card in self.view()["inbox"]["open"] if card["reason"] == "trust_failed"]

    def test_a_failed_read_back_shows_its_card_and_check_again_clears_it(self):
        self.trust["trust_granter"] = lambda path, key: (
            folder_trust.FAILED if path.parent.name == "solo" else folder_trust.grant(path, key))
        self.ready(apply_result=APPLIED)
        self.run_approval("opened")
        (card,) = self.trust_cards()
        self.assertEqual(card["title"], "Trust o/r")
        self.assertEqual(card["why"], folder_trust.failed_words("o/r", "solo"))
        self.svc._trust_granter = folder_trust.grant
        self.assertEqual(self.check({"root": self.key, "profile": "solo"})[::2], (204, b""))
        rows = self.trust_rows()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1]["cause"], "check")
        self.assertEqual(rows[1]["profiles"], [{"profile": "solo", "result": "granted"}])
        self.assertEqual(self.trust_cards(), [])
        self.assertEqual(self.parsed("solo"), self.trusted())

    def test_removing_the_account_clears_its_check_again_card(self):
        self.trust["trust_granter"] = lambda path, key: (
            folder_trust.FAILED if path.parent.name == "solo" else folder_trust.grant(path, key))
        solo = self.files["solo"].parent

        def remover(name):
            shutil.rmtree(solo)
            self.trust["profile_dirs"].remove(solo)

        self.trust.update(
            account_remover=remover, signer_out=lambda one: None,
            signin_reader=lambda one: signin.Status("signed_in", None))
        self.ready(apply_result=APPLIED)
        self.run_approval("opened")
        self.assertEqual(len(self.trust_cards()), 1)
        counted = self.view()["statement"]["inbox_items"]
        status, _, _ = support.post_page(
            self.svc.address, "/api/account-remove",
            self.own(**{"Content-Type": "application/json"}),
            json.dumps({"profile": "solo", "typed": "solo"}).encode())
        self.assertEqual(status, 204)
        self.assertEqual(self.trust_cards(), [])
        self.assertEqual(self.view()["statement"]["inbox_items"], counted - 1)

    def test_checking_again_a_worktree_whose_key_never_resolved_trusts_the_main_checkout(self):
        self.ready(apply_result=APPLIED)
        linked = self.parent / "linked"
        git(self.repo, "worktree", "add", "-q", "-b", "wt", str(linked))
        slot = os.path.realpath(linked)
        with mock.patch.object(folder_trust, "trust_key", return_value=None), \
                contextlib.redirect_stderr(io.StringIO()):
            self.svc._grant_trust("apply", str(linked), "p")
        self.assertEqual(len(self.trust_cards()), 3)
        self.assertEqual(self.check({"root": slot, "profile": "solo"})[::2], (204, b""))
        key = os.path.realpath(self.key)
        self.assertEqual(self.parsed("solo")["projects"], {
            key: {"allowedTools": ["Bash"], "hasTrustDialogAccepted": True}})
        self.assertEqual(sorted(card["profile"] for card in self.trust_cards()),
                         ["default", "work"])

    def test_a_grant_that_an_account_removal_overtakes_publishes_nothing_for_that_account(self):
        entered, gate = threading.Event(), threading.Event()
        self.addCleanup(gate.set)

        def granter(path, key):
            if path.parent.name == "solo":
                entered.set()
                gate.wait(30)
                return folder_trust.FAILED
            return folder_trust.grant(path, key)

        self.trust["trust_granter"] = granter
        solo = self.files["solo"].parent

        def remover(name):
            shutil.rmtree(solo)
            self.trust["profile_dirs"].remove(solo)

        self.trust.update(
            account_remover=remover, signer_out=lambda one: None,
            signin_reader=lambda one: signin.Status("signed_in", None))
        self.ready(apply_result=APPLIED)
        granting = threading.Thread(
            target=self.svc._grant_trust, args=("apply", str(self.repo), "p"))
        granting.start()
        self.assertTrue(entered.wait(30))
        status, _, _ = support.post_page(
            self.svc.address, "/api/account-remove",
            self.own(**{"Content-Type": "application/json"}),
            json.dumps({"profile": "solo", "typed": "solo"}).encode())
        self.assertEqual(status, 204)
        gate.set()
        granting.join(30)
        self.assertFalse(granting.is_alive())
        self.assertEqual(self.trust_cards(), [])
        for row in self.trust_rows():
            self.assertNotIn("solo", [p["profile"] for p in row["profiles"]])

    def test_a_check_of_a_pair_never_named_is_refused(self):
        self.trust["trust_granter"] = lambda path, key: (
            folder_trust.FAILED if path.parent.name == "solo" else folder_trust.grant(path, key))
        self.ready(apply_result=APPLIED)
        self.run_approval("opened")
        before = self.snapshot()
        rows = len(self.trust_rows())
        for body in ({"root": self.key, "profile": "work"},
                     {"root": self.key, "profile": "default"},
                     {"root": "/nowhere", "profile": "solo"}):
            with self.subTest(body=body):
                errors = io.StringIO()
                with contextlib.redirect_stderr(errors):
                    status, _, text = self.check(body)
                self.assertEqual(
                    (status, text), (409, b"that folder is not waiting for a trust check\n"))
                self.assertIn("console: trust_check_refused", errors.getvalue())
        self.assertEqual(self.check({"root": self.key})[0], 400)
        self.assertEqual(len(self.trust_rows()), rows)
        self.assertEqual(self.snapshot(), before)

    def test_a_grant_after_close_writes_nothing(self):
        self.ready(apply_result=APPLIED)
        self.svc.close()
        before = self.snapshot()
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            self.assertEqual(self.svc._grant_trust("apply", str(self.repo), "p"), [])
        self.assertIn("console: trust_grant_skipped closing", errors.getvalue())
        self.assertEqual(self.snapshot(), before)


class CancelAfterApplyTest(CancelChecks, ApproveCase):
    """Cancel registration of a plan ready to apply, or whose apply failed (#1088, ADR-console-037)."""

    CHECK = "/api/trust-check"

    def setUp(self):
        super().setUp()
        self.arrange_profiles()

    def start(self, fake, **kwargs):
        return super().start(fake, **{**self.trust, **kwargs})

    def test_cancel_ready_to_apply(self):
        self.ready(apply_result=APPLIED)
        self.assertEqual(len(self.apply_cards()), 1)
        self.assertTrue(self.view()["registration"]["cancel"])
        self.assert_cancelled(self.repo)
        self.assertEqual(self.apply_cards(), [])
        self.assertEqual(self.view()["statement"]["inbox_items"], 0)

    def test_cancel_after_not_now_on_the_apply_card(self):
        self.ready(apply_result=APPLIED)
        self.assertEqual(self.defer()[0], 204)
        self.assertEqual(self.apply_cards(), [])
        self.assert_cancelled(self.repo)
        self.assertEqual(self.view()["statement"]["inbox_items"], 0)

    def test_cancel_after_a_failed_apply(self):
        self.ready(apply_result=SIGNING)
        self.run_approval("apply_failed")
        self.assertEqual(len(self.apply_cards()), 1)
        self.assert_cancelled(self.repo)
        self.assertEqual(self.apply_cards(), [])
        self.assertEqual(self.view()["statement"]["inbox_items"], 0)
        self.assertNotIn(("discard", PID_B), self.fake.order)

    def test_after_not_now_and_cancel_registering_the_same_repository_again_offers_apply_it(self):
        self.ready(apply_result=APPLIED)
        self.assertEqual(self.defer()[0], 204)
        self.assert_cancelled(self.repo)
        again = self.registered(self.repo)
        self.assertEqual(again["state"], "ready")
        (card,) = self.apply_cards()
        self.assertEqual([o["label"] if isinstance(o, dict) else o
                          for o in card["questions"][0]["options"]], ["Apply it", "Not now"])
        self.assertEqual(card["plan_id"], PID_B)

    def test_after_a_failed_apply_and_cancel_registering_again_offers_a_fresh_apply_it(self):
        self.ready(apply_raises=register.RunFailed("timed_out"))
        self.run_approval("apply_failed")
        self.assert_cancelled(self.repo)
        self.registered(self.repo)
        (card,) = self.apply_cards()
        self.assertEqual(card["questions"][0]["options"][0], "Apply it")
        self.assertEqual(card["why"], folder_trust.TRUST_SENTENCE)

    def test_cancel_after_a_failed_apply_removes_the_kept_copy(self):
        self.ready(apply_result=SIGNING)
        self.run_approval("apply_failed")
        self.kept(PID_B)
        self.assert_cancelled(self.repo)
        self.assertEqual(self.fake.order[-1], ("discard", PID_B))
        self.assertEqual(self.fake.order.count(("discard", PID_B)), 1)

    def test_cancel_after_a_failed_apply_removes_a_copy_that_has_no_record(self):
        self.ready(apply_result=SIGNING)
        self.run_approval("apply_failed")
        self.kept_bare(PID_B)
        self.assert_cancelled(self.repo)
        self.assertEqual(self.fake.order.count(("discard", PID_B)), 1)

    def test_cancel_after_a_failed_apply_removes_a_branch_that_has_no_copy(self):
        self.ready(apply_result=SIGNING)
        self.run_approval("apply_failed")
        git(self.repo, "branch", approve.branch_of(PID_B))
        self.assert_cancelled(self.repo)
        self.assertEqual(self.fake.order.count(("discard", PID_B)), 1)

    def test_cancel_of_a_failure_with_no_plan_id_cleans_the_earlier_failed_apply(self):
        fake = self.answer_after_a_failed_apply(discard_result=DISCARD_FAILED)
        self.kept(PID_B)
        row = self.answered()
        self.assertEqual((row["result"], row["plan_id"]), ("failed", None))
        fake.discard_result = None
        self.assertEqual(self.cancel({"root": str(self.repo)})[::2], (204, b""))
        self.assertEqual(fake.order[-1], ("discard", PID_B))
        self.assertIsNone(self.view()["registration"])
        self.assertEqual(sorted(str(r[1]["plan_id"]) for r in self.rows("registration.cancelled")),
                         sorted([str(None), PID_B]))
        self.assertEqual(self.apply_cards(), [])
        self.assertEqual(self.inbox_of(self.repo), [])
        self.restart()
        self.assertIsNone(self.view()["registration"])
        self.assertEqual(self.apply_cards(), [])

    def test_a_check_again_under_way_when_the_registration_is_cancelled_brings_no_card_back(self):
        mode = {"block": None}

        def granter(path, key):
            if mode["block"] is not None:
                mode["block"].wait(30)
                return folder_trust.FAILED
            return folder_trust.FAILED if path.parent.name == "solo" else folder_trust.grant(path, key)

        self.trust["trust_granter"] = granter
        self.ready(apply_result=SIGNING)
        self.run_approval("apply_failed")
        self.assertTrue([i for i in self.view()["inbox"]["open"] if i["reason"] == "trust_failed"])
        rows = len(self.rows("trust.granted"))
        gate = threading.Event()
        self.addCleanup(gate.set)
        mode["block"] = gate
        answers = []
        retry = threading.Thread(target=lambda: answers.append(support.post_page(
            self.svc.address, self.CHECK, self.own(**{"Content-Type": "application/json"}),
            json.dumps({"root": str(self.repo), "profile": "solo"}).encode())))
        retry.start()
        end = time.monotonic() + 30
        while time.monotonic() < end and self.svc._grants_running == 0:
            time.sleep(0.01)
        self.assertEqual(self.svc._grants_running, 1)
        self.assertEqual(self.cancel({"root": str(self.repo)})[::2], (204, b""))
        gate.set()
        retry.join(30)
        self.assertFalse(retry.is_alive())
        self.assertEqual(len(self.rows("trust.granted")), rows)
        self.assertEqual(self.inbox_of(self.repo), [])
        self.restart()
        self.assertEqual(self.inbox_of(self.repo), [])

    def test_a_cancel_whose_discard_fails_is_refused_and_keeps_the_registration(self):
        self.ready(apply_result=SIGNING, discard_result=DISCARD_FAILED)
        self.run_approval("apply_failed")
        self.kept(PID_B)
        before = support.log_rows(self.store)
        self.refused_cancel({"root": str(self.repo)}, register.CANCEL_DISCARD_FAILED)
        self.assertEqual(support.log_rows(self.store), before)
        self.assertEqual(self.rows("registration.cancelled"), [])
        self.assertEqual(self.fake.order[-1], ("discard", PID_B))
        shown = self.view()["registration"]
        self.assertIsNotNone(shown)
        self.assertEqual((shown["status"], shown["cancel"]), ("done", True))
        self.assertEqual(len(self.apply_cards()), 1)
        self.fake.discard_result = None
        self.assert_cancelled(self.repo)

    def test_a_cancel_whose_discard_raises_is_refused_and_keeps_the_registration(self):
        self.ready(apply_result=SIGNING)
        self.run_approval("apply_failed")
        self.kept(PID_B)

        def failing(plan_id, cancel=None):
            raise register.RunFailed("timed_out")

        self.fake.discard = failing
        self.refused_cancel({"root": str(self.repo)}, register.CANCEL_DISCARD_FAILED)
        self.assertEqual(self.rows("registration.cancelled"), [])
        self.assertTrue(self.view()["registration"]["cancel"])

    def test_cancel_drops_the_trust_failure_cards_and_survives_a_restart(self):
        self.trust["trust_granter"] = lambda path, key: (
            folder_trust.FAILED if path.parent.name == "solo" else folder_trust.grant(path, key))
        self.ready(apply_result=SIGNING)
        self.run_approval("apply_failed")
        self.assertEqual(len(self.apply_cards()), 1)
        (trust,) = [i for i in self.view()["inbox"]["open"] if i["reason"] == "trust_failed"]
        self.assertEqual(trust["root"], str(self.repo))
        rows = len(self.rows("trust.granted"))
        files = {name: (path.read_bytes(), path.stat().st_mtime_ns)
                 for name, path in self.files.items()}
        self.assert_cancelled(self.repo)

        def settled():
            self.assertEqual(self.inbox_of(self.repo), [])
            self.assertEqual(len(self.rows("trust.granted")), rows)
            self.assertEqual({name: (path.read_bytes(), path.stat().st_mtime_ns)
                              for name, path in self.files.items()}, files)
            status, _, body = support.post_page(
                self.svc.address, self.CHECK, self.own(**{"Content-Type": "application/json"}),
                json.dumps({"root": str(self.repo), "profile": "solo"}).encode())
            self.assertEqual((status, body), (409, folder_trust.NOT_FAILED.encode() + b"\n"))

        settled()
        self.restart()
        self.assertIsNone(self.view()["registration"])
        settled()

    def test_cancel_is_refused_once_the_branch_is_pushed(self):
        self.ready(apply_result=APPLIED)
        self.run_approval("opened")
        self.assertIs(self.view()["registration"]["cancel"], False)
        before = support.log_rows(self.store)
        self.refused_cancel({"root": str(self.repo)}, register.CANCEL_REFUSED)
        self.assertEqual(support.log_rows(self.store), before)
        self.assertEqual(self.rows("registration.cancelled"), [])
        self.assertIsNotNone(self.view()["registration"])

    def test_the_view_offers_cancel_before_apply_only(self):
        gate = threading.Event()
        self.addCleanup(gate.set)
        self.ready(apply_result=APPLIED, apply_block=gate)
        self.assertIs(self.view()["registration"]["cancel"], True)
        self.assertEqual(self.approve_plan()[0], 204)
        self.assertIs(self.view()["registration"]["cancel"], False)
        gate.set()
        self.until("opened")
        for worker in self.approval_threads():
            worker.join(30)
        self.assertIs(self.view()["registration"]["cancel"], False)

    def test_the_view_offers_cancel_after_apply_failed(self):
        self.ready(apply_result=SIGNING)
        self.run_approval("apply_failed")
        self.assertIs(self.view()["registration"]["cancel"], True)


class PlanApproveRealTest(ApproveCase):
    def setUp(self):
        super().setUp()
        self.before = real_home_state()
        contract = json.loads((ROOT / register_check.CONTRACT_SOURCE).read_text("utf-8"))
        contract["bindings"]["vcs"]["commit"]["signed"] = False
        contract["bindings"]["commands"]["nix-build"]["argv"] = ["true"]
        source = self.parent / "contract.json"
        source.write_text(json.dumps(contract), "utf-8")
        self.repo = register_check.adopted_repository(
            self.parent / "approve", "fixture/console-approve", source)
        for name, text in ((".claude/odd.md", "# odd\n"), (".claude/specs/a.md", "# a\n")):
            (self.repo / name).parent.mkdir(parents=True, exist_ok=True)
            (self.repo / name).write_text(text)
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "legacy")
        self.remote = self.parent / "approve" / "origin.git"
        self.start(register.Adopter(), pusher=approve.push,
                   slug_of=lambda root: "fixture/console-approve")
        self.shown = self.become_ready()
        self.planned = self.settled_row(self.repo)
        self.status0 = git(self.repo, "status", "--porcelain")
        self.head0 = git(self.repo, "rev-parse", "HEAD").strip()
        self.branch0 = git(self.repo, "branch", "--show-current")
        self.main0 = git(self.remote, "rev-parse", "refs/heads/main").strip()
        self.addCleanup(self.untouched)

    def untouched(self):
        self.assertEqual(json.loads(self.registry.read_text())["projects"], [])
        self.assertEqual(real_home_state(), self.before)

    def become_ready(self):
        shown = self.registered(self.repo)
        for _ in range(4):
            if shown["state"] == "ready":
                return shown
            question = shown["questions"][0]
            plan_id = shown["plan_id"]
            given = {"id": question["id"], "subject": question["subject"],
                     "value": question["options"][0]["value"]}
            self.assertEqual(self.answer(answer_of(plan_id, given))[0], 204)
            shown = self.wait_for(lambda r: r["status"] == "done"
                                  and (r["plan_id"] != plan_id or r["refusal"] is not None))
        if shown["state"] != "ready":
            self.fail("the plan never became ready")
        return shown

    def refs(self):
        return git(self.remote, "for-each-ref", "--format=%(refname) %(objectname)").splitlines()

    def test_approving_a_ready_throwaway_plan_applies_pushes_one_branch_and_requests_one_pull_request(self):
        shown, _ = self.run_approval("opened", "apply_failed", plan_id=self.shown["plan_id"])
        if self.steps()[-1] == "apply_failed":
            adoption = self.card_words()
            self.fail(f"{adoption['headline']} {adoption['note']}")
        adoption = shown["adoption"]
        branch = adoption["branch"]
        self.assertRegex(branch, r"adopt-[0-9a-f]{12}")
        tip = git(self.repo, "rev-parse", branch).strip()
        self.assertEqual(tip, adoption["commit"])
        self.assertEqual(git(self.repo, "rev-list", "--count", f"{self.head0}..{branch}").strip(),
                         "1")
        self.assertEqual(git(self.repo, "status", "--porcelain"), self.status0)
        self.assertEqual(git(self.repo, "rev-parse", "HEAD").strip(), self.head0)
        self.assertEqual(git(self.repo, "branch", "--show-current"), self.branch0)
        self.assertEqual(sorted(self.refs()),
                         sorted([f"refs/heads/main {self.main0}", f"refs/heads/{branch} {tip}"]))
        self.assertEqual(self.opens(), [
            ("open", "fixture/console-approve", branch, "main",
             "Adopt repo onto the agent platform",
             approve.body(self.planned, attempt_of(self.opens()[0][5])))])

    def test_a_real_apply_and_its_pull_request_run_no_linux_only_command(self):
        shims = self.parent / "shims"
        shims.mkdir()
        marker = self.parent / "linux-tool-ran"
        for name in ("systemd-run", "systemctl"):
            shim = shims / name
            shim.write_text(f"#!/bin/sh\nprintf '%s\\n' \"$0\" >> {marker}\nexit 1\n")
            shim.chmod(0o755)
        with mock.patch.dict(os.environ, {"PATH": f"{shims}{os.pathsep}{os.environ['PATH']}"}):
            self.run_approval("opened", "apply_failed", plan_id=self.shown["plan_id"])
        self.assertEqual(self.steps()[-1], "opened")
        self.assertEqual(len(self.opens()), 1)
        self.assertFalse(marker.exists())

    def test_a_plan_that_drifted_since_it_was_planned_is_refused_in_plain_words_and_nothing_is_pushed(self):
        (self.repo / ".claude/late.md").write_text("# late\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "late")
        shown, _ = self.run_approval("opened", "apply_failed", plan_id=self.shown["plan_id"])
        self.assertEqual(self.steps()[-1], "apply_failed")
        self.assertEqual(shown["approve"], "approve")
        self.assertTrue(self.card_words()["headline"].endswith(
            "the repository changed since this plan was made."))
        self.assertEqual(self.refs(), [f"refs/heads/main {self.main0}"])
        self.assertEqual(self.forge.calls, [])


class MergedRegistrationTest(ApproveCase):
    def merged(self, report, **fake_arguments):
        fake = self.opened(fake_class=RegistryFake, registry=self.registry, **fake_arguments)
        fake.report = report
        return fake

    def captured(self, job):
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            job()
        return errors.getvalue()

    def results(self):
        return [row["result"] for row in self.registrations()]

    def test_a_merged_pull_request_registers_once_and_a_green_one_is_listed_at_once(self):
        self.merged(GREEN)
        self.poll("ready")
        self.poll("merged")
        self.assertTrue(self.listed("o/r"))
        self.poll("merged")
        self.assertEqual(len(self.register_calls()), 1)
        self.assertEqual(self.registrations(), [{
            "plan_id": PID_B, "number": 7, "result": "registered", "project_id": "o/r",
            "reason": None, "note": None}])
        view = self.view()
        self.assertIsNone(view["registration"])
        self.assertIn("o/r was registered.", [m["sentence"] if isinstance(m, dict) else m
                                               for m in view["digest"]["recent"]])
        self.assertEqual(view["statement"]["inbox_items"], 0)

    def test_the_registration_names_the_recorded_integration_branch_and_the_plan(self):
        fake = self.merged(GREEN)
        self.poll("merged")
        self.assertEqual(self.svc._adoptions[PID_B]["base"], APPLIED["integration_branch"])
        self.assertEqual(fake.register_operands,
                         [{"integration_branch": "develop", "plan_id": PID_B}])

    def test_before_the_remote_carries_the_adoption_the_registration_waits_and_retries_on_the_next_look(self):
        fake = self.merged(NOT_INTEGRATED)
        self.poll("merged")
        self.poll("merged")
        self.assertEqual(len(self.register_calls()), 2)
        self.assertEqual(self.results(), ["waiting"])
        self.assertEqual(json.loads(self.registry.read_text())["projects"], [])
        self.assertEqual(self.retry_items(), [])
        self.assertEqual(self.view()["statement"]["inbox_items"], 0)
        self.assertEqual(self.adoption()["headline"],
                         "The pull request of reconcile was merged; waiting for develop on "
                         "origin to carry it before registering.")
        fake.report = GREEN
        self.poll("merged")
        self.assertEqual(self.results(), ["waiting", "registered"])
        self.assertTrue(self.listed("o/r"))

    def test_a_closed_pull_request_ends_with_no_registration(self):
        self.merged(GREEN)
        self.poll("ready")
        self.poll("closed")
        self.poll("closed")
        self.assertEqual(self.register_calls(), [])
        self.assertEqual(self.registrations(), [])
        self.assertEqual(json.loads(self.registry.read_text())["projects"], [])
        self.assertEqual(self.card_words()["headline"],
                         "The pull request of reconcile was closed without merging.")
        self.assertEqual(self.retry_items(), [])

    def test_another_refusal_is_shown_with_its_reason_and_retry_runs_it_again(self):
        fake = self.merged(NO_REMOTE)
        self.poll("merged")
        self.poll("merged")
        self.assertEqual(len(self.register_calls()), 1)
        reason = "the repository has no origin remote"
        note = "Add the repository's origin remote, then choose Retry."
        (row,) = self.registrations()
        self.assertEqual((row["result"], row["reason"], row["note"]), ("refused", reason, note))
        view = self.view()
        self.assertEqual(view["registration"]["line"], "Register reconcile: needs you")
        self.assertIsNone(view["registration"]["approve"])
        (item,) = self.retry_items()
        self.assertEqual(item["title"], "Register reconcile")
        self.assertEqual(item["questions"][0]["options"], ["Retry"])
        self.assertEqual(item["values"], ["retry"])
        self.assertEqual(item["why"], note)
        self.assertEqual(view["statement"]["inbox_items"], 1)
        fake.report = GREEN
        self.assertEqual(self.retry(PID_B), 204)
        self.assertEqual(len(self.register_calls()), 2)
        self.assertEqual(self.results(), ["refused", "registered"])
        self.assertEqual(self.retry_items(), [])
        self.assertTrue(self.listed("o/r"))

    def test_a_retry_asked_after_the_stop_is_refused(self):
        self.merged(NO_REMOTE)
        self.poll("merged")
        calls = len(self.register_calls())
        self.assertEqual(len(self.retry_items()), 1)
        self.svc._stop.set()
        with self.assertRaises(sprints.Refused) as caught:
            self.svc.retry_registration(PID_B)
        self.assertEqual(str(caught.exception), register.STOPPING)
        self.assertNotIn(PID_B, self.svc._enrolling)
        self.assertEqual(len(self.register_calls()), calls)

    def test_a_retry_is_refused_in_order_and_runs_nothing(self):
        fake = self.merged(NO_REMOTE)
        self.poll("merged")
        calls = len(self.register_calls())
        rows = self.registrations()

        def post(body=None, raw=None):
            payload = json.dumps(body).encode() if raw is None else raw
            return support.post_page(self.svc.address, RETRY_PATH,
                                     self.own(**{"Content-Type": "application/json"}), payload)

        for body, raw in (({"plan_id": ""}, None), ({"x": 1}, None), (None, b"[")):
            with self.subTest(body=body, raw=raw):
                status, _, answer = post(body, raw)
                self.assertEqual((status, answer), (400, b"bad registration retry\n"))

        def refused(plan_id, text):
            errors = self.captured(lambda: self.assertEqual(
                post({"plan_id": plan_id})[::2], (409, text.encode() + b"\n")))
            self.assertIn(f"console: adoption_register_refused {text}", errors)

        refused("sha256:" + "f" * 64, approve.NOT_REFUSED)
        fake.report = NOT_INTEGRATED
        self.assertEqual(self.retry(PID_B), 204)
        self.assertEqual(self.results(), ["refused", "waiting"])
        refused(PID_B, approve.NOT_REFUSED)
        calls_now = len(self.register_calls())
        rows_now = self.registrations()
        with self.svc._ingest:
            self.svc._enrolling.add(PID_B)
        try:
            refused(PID_B, register.running("reconcile"))
        finally:
            with self.svc._ingest:
                self.svc._enrolling.discard(PID_B)
        self.assertEqual(len(self.register_calls()), calls_now)
        self.assertEqual(self.registrations(), rows_now)
        self.assertEqual((calls, rows[0]["result"]), (1, "refused"))

    def test_without_an_adopter_a_retry_is_unavailable(self):
        self.start(None)
        status, _, body = support.post_page(
            self.svc.address, RETRY_PATH, self.own(**{"Content-Type": "application/json"}),
            json.dumps({"plan_id": PID_B}).encode())
        self.assertEqual((status, body), (409, register.UNAVAILABLE.encode() + b"\n"))

    def test_a_waiting_registration_survives_a_restart_and_registers_on_the_first_look(self):
        fake = self.merged(NOT_INTEGRATED)
        self.poll("merged")
        fake.report = GREEN
        self.restart()
        end = time.monotonic() + 10
        while time.monotonic() < end and self.results()[-1:] != ["registered"]:
            time.sleep(0.05)
        self.assertEqual(self.results()[-1:], ["registered"])
        self.assertTrue(self.listed("o/r"))

    def test_a_failed_run_is_refused_in_words_and_logged_in_full(self):
        self.merged(None, register_raises=register.RunFailed("timed_out"))
        errors = self.captured(lambda: self.poll("merged"))
        (row,) = self.registrations()
        self.assertEqual((row["result"], row["reason"]),
                         ("refused", "it took too long and was stopped"))
        lines = [line for line in errors.splitlines() if line.startswith(REGISTER_ERROR)]
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0][len(REGISTER_ERROR):])["failure"], "timed_out")
        self.assertNotIn("timed_out", f"{row['reason']} {row['note']} "
                         f"{self.view()['registration']['line']}")

    def test_a_registration_stopped_by_the_console_closing_appends_nothing(self):
        fake = self.merged(None)
        service_ = self.svc

        def stopping(root, cancel=None, **operands):
            fake.calls.append(("register", root))
            service_._stop.set()
            raise register.RunFailed("cancelled")

        fake.register = stopping
        self.forge.states[7] = "merged"
        self.svc.poll_adoptions()
        self.assertEqual(len(self.register_calls()), 1)
        self.assertEqual(self.registrations(), [])

    def test_the_registration_runs_outside_the_lock_once_per_plan_and_says_registering(self):
        fake = self.merged(GREEN)
        fake.block = threading.Event()
        self.addCleanup(fake.block.set)
        self.forge.states[7] = "merged"
        helper = threading.Thread(target=self.svc.poll_adoptions)
        helper.start()
        end = time.monotonic() + 10
        while time.monotonic() < end and len(self.register_calls()) < 1:
            time.sleep(0.02)
        self.assertEqual(len(self.register_calls()), 1)
        self.svc.record_look()
        self.svc.register_merged()
        headline = self.adoption()["headline"]
        self.assertEqual(len(self.register_calls()), 1)
        self.assertEqual(headline, "Registering reconcile\u2026")
        self.assertIsNone(self.svc._registering)
        self.assertEqual(self.retry_items(), [])
        fake.block.set()
        helper.join(30)
        self.assertEqual(self.results(), ["registered"])

    def test_a_report_that_failed_its_checks_is_refused_and_logged_in_full(self):
        checks = [adopt_inspection.verify_check_entry(
            "path-migration-map", "failed", "the evidence record names no path migration map")]
        self.merged({"registered": False, "result": "not_conformant", "project_id": "o/r",
                     "checks": checks, "blockers": []})
        errors = self.captured(lambda: self.poll("merged"))
        (row,) = self.registrations()
        self.assertEqual((row["result"], row["reason"]), (
            "refused", "the adoption on the remote did not pass the registration's checks"))
        lines = [line for line in errors.splitlines() if line.startswith(REGISTER_ERROR)]
        self.assertEqual(len(lines), 1)
        record = json.loads(lines[0][len(REGISTER_ERROR):])
        self.assertEqual((record["plan_id"], record["stage"]), (PID_B, "register"))
        self.assertEqual(record["report"]["checks"], checks)
        self.assertNotIn("the evidence record names no path migration map",
                         f"{row['reason']} {row['note']}")

    def test_a_retry_that_meets_the_same_refusal_appends_a_row_and_a_fresh_card(self):
        fake = self.merged(NO_REMOTE)
        self.poll("merged")
        first = self.retry_items()[0]["key"]
        self.assertEqual(self.retry(PID_B), 204)
        rows = self.registrations()
        self.assertEqual([row["result"] for row in rows], ["refused", "refused"])
        self.assertEqual(rows[0]["reason"], rows[1]["reason"])
        (item,) = self.retry_items()
        second = item["key"]
        self.assertNotEqual(second, first)
        self.assertEqual(
            second, f"register-retry/{PID_B}/{self.svc._adoptions[PID_B]['registration']['at']}")
        fake.report = GREEN
        self.assertEqual(self.retry(PID_B), 204)
        self.assertEqual(self.results(), ["refused", "refused", "registered"])
        self.assertEqual(len(self.register_calls()), 3)
        self.assertEqual(self.retry_items(), [])
        self.assertTrue(self.listed("o/r"))


class DraftingFake(Fake):
    """A `Fake` that keeps the contract file its plan was given, which is gone when the plan returns."""

    def plan(self, root, cancel=None, answers=(), contract=None, environment=None):
        self.drafted = None if contract is None else json.loads(Path(contract).read_text())
        return super().plan(root, cancel=cancel, answers=answers, contract=contract,
                            environment=environment)


class RetiredCoAuthorPlanTest(ApproveCase):
    """A ready plan saved before the console stopped drafting the co-author setting (#1449)."""

    def test_approving_it_plans_again_from_the_refreshed_draft_and_applies_nothing(self):
        repo = sample_repository(self.parent, remote=True)
        fields = contract_draft.draft(str(repo), contract_draft.read(str(repo)))
        for field in ("build-command", "test-command"):
            fields, error = contract_draft.set_value(
                fields, field, "none", entries=[], root=str(repo))
            self.assertIsNone(error)
        record = {"field": "co-authored-by", "label": "co-author lines in commits", "value": "yes",
                  "source": "owner",
                  "options": [{"value": "yes", "label": "yes"}, {"value": "no", "label": "no"}],
                  "text": False, "reason": None, "ask": "Should its commits carry co-author lines?"}
        row = register.summary(str(repo), READY, draft=[*fields[:8], record, *fields[8:]])
        self.assertEqual((row["plan_id"], row["state"]), (PID_B, "ready"))
        log = event_log.EventLog(self.store)
        try:
            log.append([register.ended(row)])
        finally:
            close = getattr(log, "close", None)
            if close is not None:
                close()
        replanned = {**READY, "plan": {**READY["plan"], "plan_id": PID_C}}
        fake = DraftingFake(plan=replanned, apply_result=APPLIED)
        self.start(fake)
        self.assertEqual(self.view()["registration"]["plan_id"], PID_B)
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            self.assertEqual(self.approve_plan()[::2], (204, b""))
            again = self.wait_for(lambda r: r["status"] == "done" and r["plan_id"] != PID_B)
        self.assertEqual((again["plan_id"], again["state"]), (PID_C, "ready"))
        self.assertEqual(fake.applied, [])
        self.assertEqual(fake.calls, [("plan", str(repo))])
        self.assertIs(fake.drafted["bindings"]["vcs"]["commit"]["co_authored_by"], False)
        self.refused(PID_B, approve.STALE)


class MergedRealCase(ApproveCase):
    evidence_plan = PID_B

    def setUp(self):
        super().setUp()
        self.before = real_home_state()
        self.addCleanup(lambda: self.assertEqual(real_home_state(), self.before))
        self.repo = register_check.adopted_repository(
            self.parent / "merged", "fixture/console-merged", ROOT / register_check.CONTRACT_SOURCE)
        self.remote = self.parent / "merged" / "origin.git"
        evidence = next((self.repo / ".agents/artifacts/evidence").glob("*.json"))
        record = json.loads(evidence.read_text())
        evidence.write_text(json.dumps({**record, "plan_id": self.evidence_plan}) + "\n")
        git(self.repo, "add", str(evidence))
        git(self.repo, "commit", "-q", "--amend", "--no-edit")
        self.tip = git(self.repo, "rev-parse", "HEAD").strip()
        git(self.repo, "push", "--quiet", "--force", "origin", "HEAD~1:refs/heads/main")
        planned = {
            "by": "owner", "root": str(self.repo), "project_id": "fixture/console-merged",
            "result": "planned", "outcome": "reconcile", "headline": "The plan is ready.",
            "lines": [], "note": None, "plan_id": PID_B, "state": "ready", "questions": [],
            "answered": []}
        opened = {key: None for key in approve.STEP_MEMBERS}
        opened.update({
            "by": "owner", "plan_id": PID_B, "root": str(self.repo),
            "project_id": "fixture/console-merged", "step": "opened", "branch": BRANCH,
            "commit": COMMIT, "base": "main",
            "pull_request": {"number": 7,
                             "url": "https://github.com/fixture/console-merged/pull/7"}})
        log = event_log.EventLog(self.store)
        try:
            log.append([register.ended(planned), approve.step_row(opened)])
        finally:
            close = getattr(log, "close", None)
            if close is not None:
                close()
        self.forge.states[7] = "merged"
        self.start(register.Adopter(), slug_of=lambda root: "fixture/console-merged")


class MergedRegistrationRealTest(MergedRealCase):
    def test_before_the_remote_carries_the_adoption_nothing_is_registered(self):
        results = [row["result"] for row in self.settled(1)]
        self.assertEqual(json.loads(self.registry.read_text())["projects"], [])
        self.assertEqual(results, ["waiting"])
        self.assertEqual(self.adoption()["headline"],
                         "The pull request of repo was merged; waiting for main on origin to "
                         "carry it before registering.")
        self.assertEqual(self.retry_items(), [])
        self.assertEqual(git(self.repo, "rev-parse", "HEAD").strip(), self.tip)

    def test_a_merged_adoption_on_the_remote_registers_and_is_listed_with_a_digest_line(self):
        self.settled(1)
        git(self.repo, "push", "--quiet", "--force", "origin", f"{self.tip}:refs/heads/main")
        self.svc.poll_adoptions()
        self.assertEqual(json.loads(self.registry.read_text())["projects"],
                         [{"project_id": "fixture/console-merged", "root": str(self.repo)}])
        self.assertTrue(self.listed("fixture/console-merged"))
        self.assertEqual([row["result"] for row in self.registrations()],
                         ["waiting", "registered"])
        self.assertIsNone(self.view()["registration"])
        recent = self.view()["digest"]["recent"]
        self.assertIn("fixture/console-merged was registered.",
                      [m["sentence"] if isinstance(m, dict) else m for m in recent])
        self.assertEqual(git(self.repo, "rev-parse", "HEAD").strip(), self.tip)


class MergedReadoptionRealTest(MergedRealCase):
    evidence_plan = PID_A

    def test_the_remote_carrying_an_earlier_adoption_does_not_register_the_new_plan(self):
        self.settled(1)
        git(self.repo, "push", "--quiet", "--force", "origin", f"{self.tip}:refs/heads/main")
        self.svc.poll_adoptions()
        self.assertEqual(json.loads(self.registry.read_text())["projects"], [])
        self.assertEqual([row["result"] for row in self.registrations()], ["waiting"])
        self.assertFalse(self.listed("fixture/console-merged"))
        self.assertEqual(self.retry_items(), [])


class ReconcileProposalTest(ApproveCase):
    """A contract checkout whose installed hook is stranded proposes the commit environment (#1333)."""

    PID_C = "sha256:" + "c" * 64
    PID_D = "sha256:" + "d" * 64
    READ_STRANDED = {"hooks": ["pre-commit"], "stranded": ["pre-commit"],
                     "environments": ["devenv.nix"]}
    READ_UNSTRANDED = {**READ_STRANDED, "stranded": []}
    TOOK = {**READY, "plan": {**READY["plan"], "commit_environment": ["devenv", "shell", "--"]}}
    LEFT = READY
    LINE = "commits run in its development shell: devenv shell (found in its files)"
    draft_answer = DraftCase.draft_answer
    answered_draft = DraftCase.answered_draft

    def settled_card(self, root):
        self.registered(root)
        (card,) = self.apply_cards()
        return card

    def test_a_stranded_hook_and_devenv_plan_the_contract_checkout_with_the_command(self):
        fake = Fake(plan=self.TOOK)
        self.start(fake, hook_reader=lambda root: self.READ_STRANDED)
        root = git_repo(self.parent / "r")
        card = self.settled_card(root)
        self.assertEqual(fake.environments, ["devenv shell --"])
        self.assertEqual(fake.contracts, [(None, False, True)])
        self.assertEqual(fake.answers, [[]])
        (_, row), = self.rows("registration.ended")[-1:]
        self.assertEqual(row["draft"], contract_draft.reconcile_fields(str(root), self.READ_STRANDED))
        self.assertEqual(card["lines"][0], self.LINE)

    def test_no_stranded_hook_plans_as_today(self):
        fake = Fake(plan=READY)
        self.start(fake, hook_reader=lambda root: self.READ_UNSTRANDED)
        card = self.settled_card(git_repo(self.parent / "r"))
        self.assertEqual(fake.environments, [None])
        (_, row), = self.rows("registration.ended")[-1:]
        self.assertIsNone(row["draft"])
        self.assertFalse([x for x in card["lines"]
                          if x.startswith("commits run in its development shell")])

    def test_a_plan_that_did_not_take_the_command_carries_no_proposal(self):
        fake = Fake(plan=self.LEFT)
        self.start(fake, hook_reader=lambda root: self.READ_STRANDED)
        card = self.settled_card(git_repo(self.parent / "r"))
        self.assertEqual(fake.environments, ["devenv shell --"])
        (_, row), = self.rows("registration.ended")[-1:]
        self.assertIsNone(row["draft"])
        self.assertFalse([x for x in card["lines"]
                          if x.startswith("commits run in its development shell")])

    def test_the_owner_changes_the_proposal_to_none_and_to_another_command(self):
        fake = Fake(plan=[
            self.TOOK, {**self.LEFT, "plan": {**self.LEFT["plan"], "plan_id": self.PID_C}},
            {**self.TOOK, "plan": {**self.TOOK["plan"], "plan_id": self.PID_D}}])
        self.start(fake, hook_reader=lambda root: self.READ_STRANDED)
        self.registered(git_repo(self.parent / "r"))
        self.assertEqual(self.defer(PID_B)[0], 204)
        self.assertEqual(self.apply_cards(), [])
        self.answered_draft(PID_B, "commit-environment", "none")
        self.assertIsNone(fake.environments[-1])
        self.assertIsNone(fake.contracts[-1][0])
        (card,) = self.apply_cards()
        self.assertEqual(card["lines"][0], "commits run in its development shell: none (set by you)")
        self.answered_draft(self.PID_C, "commit-environment", "nix develop -c")
        self.assertEqual(fake.environments[-1], "nix develop -c")
        (card,) = self.apply_cards()
        self.assertEqual(card["lines"][0],
                         "commits run in its development shell: nix develop -c (set by you)")

    def test_an_answer_to_another_question_resends_the_command(self):
        took = {**DRAFT, "plan": {**DRAFT["plan"], "commit_environment": ["devenv", "shell", "--"]}}
        fake = Fake(plan=[took, self.TOOK])
        self.start(fake, hook_reader=lambda root: self.READ_STRANDED)
        self.registered(git_repo(self.parent / "r"))
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            self.assertEqual(self.answer(answer_of(PID_A, A1))[0], 204)
            self.wait_for(lambda r: r["status"] == "done" and r["plan_id"] == PID_B)
        self.assertEqual(fake.environments, ["devenv shell --", "devenv shell --"])
        self.assertEqual(fake.answers, [[], [A1]])

    def test_an_answer_run_whose_plan_left_the_command_out_carries_no_proposal(self):
        took = {**DRAFT, "plan": {**DRAFT["plan"], "commit_environment": ["devenv", "shell", "--"]}}
        fake = Fake(plan=[took, self.LEFT])
        self.start(fake, hook_reader=lambda root: self.READ_STRANDED)
        self.registered(git_repo(self.parent / "r"))
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            self.assertEqual(self.answer(answer_of(PID_A, A1))[0], 204)
            self.wait_for(lambda r: r["status"] == "done" and r["plan_id"] == PID_B)
        (_, row), = self.rows("registration.ended")[-1:]
        self.assertIsNone(row["draft"])

    def test_only_a_fresh_run_reads_the_hooks(self):
        reads = []
        nothing = {**READY, "plan": {**READY["plan"], "outcome": "no_change"}, "changes": []}

        class Answered(Fake):
            def plan(self, root, cancel=None, answers=(), contract=None, environment=None):
                super().plan(root, cancel, answers, contract, environment)
                return nothing if answers else DRAFT

        def read(root):
            reads.append(root)
            return self.READ_UNSTRANDED

        fake = Answered(report={"registered": True, "project_id": "o/r"})
        self.start(fake, hook_reader=read)
        root = git_repo(self.parent / "r")
        self.registered(root)
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            self.assertEqual(self.answer(answer_of(PID_A, A1))[0], 204)
            self.wait_for(lambda r: r["status"] == "done" and r["outcome"] == "no_change")
            self.assertEqual(self.confirm({"root": str(root), "choice": "register"})[0], 204)
            self.wait_for(lambda r: r["result"] == "registered")
        self.assertEqual(len(reads), 1)


class ReconciledCopyTest(ApproveCase):
    def test_a_reconciled_copy_is_the_reconcile_build_with_its_own_origin(self):
        with mock.patch(f"{__name__}.reconcile_repository", wraps=reconcile_repository) as spy:
            first = reconciled(self.parent / "a", contract=True)
            second = reconciled(self.parent / "b", contract=True)
        git(first, "diff-index", "--quiet", "HEAD", "--")
        self.assertLessEqual(spy.call_count, 1)
        self.assertEqual(first, (self.parent / "a" / "reconcile").resolve())
        self.assertEqual(git(first, "config", "--get", "remote.origin.url").strip(),
                         str(self.parent / "a" / "origin.git"))
        self.assertEqual(git(first, "log", "--format=%s"), "legacy\none\n")
        self.assertEqual(git(first, "branch", "--show-current").strip(), "main")
        self.assertTrue((first / ".agents/project.json").is_file())
        self.assertEqual((first / ".claude/specs/a.md").read_text(), "# spec a\n")
        self.assertEqual(git(first, "status", "--porcelain"), "")
        git(first, "commit", "-q", "--allow-empty", "-m", "x")
        git(first, "push", "-q", "origin", "main")
        self.assertNotEqual(git(self.parent / "a" / "origin.git", "rev-parse", "main"),
                            git(self.parent / "b" / "origin.git", "rev-parse", "main"))
        self.assertEqual(second, (self.parent / "b" / "reconcile").resolve())

    def test_a_reconciled_copy_without_a_contract_has_no_contract_file(self):
        root = reconciled(self.parent / "c")
        self.assertFalse((root / ".agents").exists())
        self.assertEqual(git(root, "log", "--format=%s"), "legacy\none\n")
