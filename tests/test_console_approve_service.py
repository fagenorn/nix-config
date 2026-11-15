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
import threading
import time
from pathlib import Path
from unittest import mock

from agent_tools.console import approve, folder_trust, register, register_check, service, signin
from agent_tools.console import event_log
from agent_tools.project_contract import adopt_apply, adopt_inspection
from agent_tools.system.forge_api import ForgeError

from . import console_test_support as support
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1052)
from .test_console_register_service import (
    DRAFT, PID_A, PID_B, READY, ROOT, Case, Fake, answer_of, git, real_home_state,
    reconcile_repository)

PATH = "/api/plan-approve"
RETRY_PATH = "/api/adoption-register"
DEFER_PATH = "/api/plan-defer"
OLD_PUSH_NOTE = ("Check that the repository's origin can be reached from this host and accepts the "
                 "push, then press Try again.")
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
APPLIED_LINE = f"Applied on the branch {BRANCH} as one commit, cccccccccccc."
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

    def find_pull_request(self, slug, head, base, cancel=None):
        self.calls.append(("find", slug, head, base))
        if self.find_raises:
            error = self.find_raises.pop(0)
            if isinstance(error, BaseException):
                raise error
        number = self.pulls.get((head, base))
        if number is None or number in self.closed:
            return None
        return {"number": number, "url": f"https://github.com/{slug}/pull/{number}"}

    def open_pull_request(self, slug, head, base, title, body, cancel=None):
        self.calls.append(("open", slug, head, base, title, body))
        if self.open_raises:
            raise self.open_raises.pop(0)
        number = self.next_number
        self.next_number += 1
        self.pulls[(head, base)] = number
        if self.lost:
            raise self.lost.pop(0)
        if self.open_block:
            self.entered.set()
            (cancel or threading.Event()).wait(10)
            time.sleep(self.linger)
            raise approve.Cancelled()
        return {"number": number, "url": f"https://github.com/{slug}/pull/{number}"}

    def pull_request_state(self, slug, number, cancel=None):
        self.calls.append(("state", slug, number))
        found = self.states.get(number, "open")
        if isinstance(found, BaseException):
            raise found
        return found

    def mark_closed(self, number):
        self.closed.add(number)


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


class ApproveCase(Case):
    def setUp(self):
        super().setUp()
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
        self.repo = reconcile_repository(self.parent, contract=True)
        self.shown = self.registered(self.repo)
        return fake

    def approve(self, body=None, headers=None, raw=None):
        payload = json.dumps(body).encode() if raw is None else raw
        sent = self.own(**{"Content-Type": "application/json"}) if headers is None else headers
        return support.post_page(self.svc.address, PATH, sent, payload)

    def approve_plan(self, plan_id=PID_B):
        return self.approve({"plan_id": plan_id})

    def until(self, *steps, bound=120):
        return self.wait_for(
            lambda r: r["adoption"] is not None and r["adoption"]["status"] == "done"
            and r["adoption"]["step"] in steps, bound)

    def run_approval(self, *steps, plan_id=PID_B):
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            self.assertEqual(self.approve_plan(plan_id)[::2], (204, b""))
            shown = self.until(*steps)
            for worker in self.approval_threads():
                worker.join(30)
        return shown, errors.getvalue()

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

    def defer(self, plan_id=PID_B, raw=None, headers=None):
        payload = json.dumps({"plan_id": plan_id}).encode() if raw is None else raw
        sent = self.own(**{"Content-Type": "application/json"}) if headers is None else headers
        status, _, body = support.post_page(self.svc.address, DEFER_PATH, sent, payload)
        return status, body

    def deferrals(self):
        return [payload for _, payload in self.rows("adoption.deferred")]

    def settled(self, count, bound=120):
        end = time.monotonic() + bound
        while time.monotonic() < end:
            found = self.registrations()
            with self.svc._ingest:
                busy = PID_B in self.svc._enrolling
            if len(found) >= count and not busy:
                return found
            time.sleep(0.05)
        self.fail("the registration never settled")


class ApplyCardTest(ApproveCase):
    def test_a_ready_plan_is_one_apply_card_counted_in_the_statement(self):
        self.ready(apply_result=APPLIED)
        (card,) = self.apply_cards()
        self.assertEqual(card["title"], "Register reconcile")
        self.assertEqual(card["headline"], "Apply this adoption?")
        self.assertEqual(card["questions"][0]["options"], ["Apply it", "Not now"])
        self.assertEqual(card["values"], ["apply", "not_now"])
        self.assertEqual(card["lines"], self.shown["lines"])
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
        self.assertEqual(card["headline"], shown["adoption"]["headline"])
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
        self.assertEqual(card["why"], shown["adoption"]["note"])

    def test_not_now_on_a_failed_step_hides_it_and_keeps_the_work_line(self):
        self.pusher.raises = [approve.PushFailed("remote rejected the push", "d")]
        self.ready(apply_result=APPLIED)
        shown, _ = self.run_approval("push_failed")
        self.assertEqual(self.defer()[0], 204)
        self.assertEqual(self.apply_cards(), [])
        self.assertEqual(self.view()["registration"]["line"], shown["line"])

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
        self.assertEqual(self.adoption()["note"], approve.PUSH_NOTE)
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
        self.shown = self.registered(reconcile_repository(self.parent, contract=True))
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
             approve.body(self.shown))])
        self.assertEqual(self.steps(), ["applied", "opened"])
        self.assertEqual(shown["adoption"], {
            "status": "done", "step": "opened", "state": "open",
            "headline": "Waiting for the pull request of reconcile to be ready to merge.",
            "lines": [APPLIED_LINE, f"Pushed {BRANCH} to origin.",
                      "Opened pull request #7 against develop."],
            "note": None, "branch": BRANCH, "commit": COMMIT, "url": URL})
        self.assertIsNone(shown["approve"])
        self.assertEqual(shown["line"], shown["adoption"]["headline"])
        self.assertTrue(errors.rstrip().endswith("console: plan_approve_ended opened"))

    def test_a_failed_gate_is_shown_with_its_reason_and_nothing_is_pushed(self):
        fake = self.ready(apply_result=GATE)
        kept = self.home / ".agents/state/adopt/worktrees" / ("b" * 64)
        kept.mkdir(parents=True)
        record = adopt_apply.failure_record_path("b" * 64)
        record.write_text(json.dumps({"branch": BRANCH, "worktree": str(kept)}))
        before = self.heads()
        shown, errors = self.run_approval("apply_failed")
        adoption = shown["adoption"]
        self.assertEqual(
            adoption["headline"],
            "The adoption of reconcile was not applied: the cold-clone-resolves check did not "
            "pass.")
        self.assertEqual(adoption["lines"],
                         [f"Apply kept its worktree at {kept} and its branch {BRANCH}."])
        self.assertTrue(adoption["note"].startswith("Fix what failed in the repository"))
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
        shown, _ = self.run_approval("apply_failed")
        adoption = shown["adoption"]
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
        shown, _ = self.run_approval("apply_failed")
        adoption = shown["adoption"]
        self.assertTrue(adoption["headline"].endswith(": it took too long and was stopped."))
        self.assertTrue(adoption["note"].startswith("Choose Apply it again."))
        fake.apply_raises = KeyError("x")
        shown, errors = self.run_approval("apply_failed")
        self.assertTrue(shown["adoption"]["headline"].endswith(": it stopped unexpectedly."))
        self.assertTrue(any(line.startswith(ERROR_LINE) and '"exception": "KeyError"' in line
                            for line in errors.splitlines()))
        self.assertEqual((self.pusher.calls, self.forge.calls), ([], []))
        self.assertEqual(len(fake.applied), 2)

    def test_a_refused_push_keeps_the_branch_and_try_again_resumes_at_the_push(self):
        self.pusher.raises = [approve.PushFailed("remote rejected the push", "stderr detail")]
        fake = self.ready(apply_result=APPLIED)
        shown, errors = self.run_approval("push_failed")
        adoption = shown["adoption"]
        self.assertEqual(adoption["headline"],
                         f"The branch {BRANCH} was not pushed: remote rejected the push.")
        self.assertEqual(adoption["lines"], [APPLIED_LINE])
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

    def test_a_refused_pull_request_is_shown_in_words_and_logged_in_full(self):
        self.forge.open_raises = [ForgeError("gh_failed", "gh: Validation Failed (HTTP 422)")]
        fake = self.ready(apply_result=APPLIED)
        shown, errors = self.run_approval("open_failed")
        adoption = shown["adoption"]
        self.assertEqual(
            adoption["headline"],
            f"The pull request for {BRANCH} was not opened: the forge refused the pull request.")
        self.assertEqual(
            adoption["note"],
            f"Check on the forge that {BRANCH} differs from develop and has no pull request open "
            "already, then choose Try again.")
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
        self.assertTrue(shown["adoption"]["headline"].endswith(
            ": the forge took too long to answer."))
        self.assertEqual(shown["approve"], "retry")
        self.restart()
        shown, _ = self.run_approval("opened")
        self.assertEqual(len(self.opens()), 1)
        self.assertEqual(shown["adoption"]["url"], URL)
        self.assertEqual(len(fake.applied), 1)
        self.assertEqual(self.svc._adoptions[PID_B]["pull_request"], {"number": 7, "url": URL})

    def test_an_origin_that_is_not_on_github_opens_nothing(self):
        self.ready(apply_result=APPLIED)
        self.kwargs["slug_of"] = lambda root: None
        self.restart()
        shown, _ = self.run_approval("open_failed")
        self.assertEqual(
            shown["adoption"]["headline"],
            f"The pull request for {BRANCH} was not opened: the repository's origin is not on "
            "GitHub.")
        self.assertEqual(self.forge.calls, [])
        self.assertEqual(len(self.pusher.calls), 1)

    def test_deletions_are_acknowledged_only_when_the_page_showed_them(self):
        fake = self.ready(plan=WITH_DELETION, apply_result=APPLIED)
        self.assertTrue(any(line.startswith("deletes ") for line in self.shown["lines"]))
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
            "answered": False, "waiting_since": self.svc._adoptions[PID_B]["pull_at"]}])
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
        self.assertEqual(self.adoption()["headline"],
                         "The pull request of reconcile was closed without merging.")

    def test_a_closed_adoption_names_its_branch_and_is_approved_again_with_the_same_plan(self):
        fake = self.opened()
        self.poll("ready")
        self.poll("closed")
        self.assertEqual(self.adoption()["note"], approve.closed_note(str(self.repo), BRANCH))
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
                         "Waiting for the pull request of reconcile to be ready to merge.")

    def test_an_unchanged_state_appends_nothing(self):
        self.opened()
        self.poll("open")
        self.assertEqual(self.pulls(), [])
        self.poll("ready")
        self.poll("ready")
        self.assertEqual(len(self.pulls()), 1)

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


class PlanApproveCloseTest(ApproveCase):
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
        self.assertEqual(card["why"], folder_trust.failed_words(self.key, "solo"))
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
        adoption = shown["adoption"]
        if adoption["step"] == "apply_failed":
            self.fail(f"{adoption['headline']} {adoption['note']}")
        found = re.fullmatch(r"Applied on the branch (adopt-[0-9a-f]{12}) as one commit, "
                             r"([0-9a-f]{12})\.", adoption["lines"][0])
        self.assertIsNotNone(found)
        branch, prefix = found.groups()
        tip = git(self.repo, "rev-parse", branch).strip()
        self.assertTrue(tip.startswith(prefix))
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
             "Adopt repo onto the agent platform", approve.body(self.shown))])

    def test_a_plan_that_drifted_since_it_was_planned_is_refused_in_plain_words_and_nothing_is_pushed(self):
        (self.repo / ".claude/late.md").write_text("# late\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "late")
        shown, _ = self.run_approval("opened", "apply_failed", plan_id=self.shown["plan_id"])
        adoption = shown["adoption"]
        self.assertEqual(adoption["step"], "apply_failed")
        self.assertTrue(adoption["headline"].endswith(
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
        self.assertEqual(self.adoption()["headline"], "reconcile is registered as o/r.")
        view = self.view()
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
        self.assertEqual(self.adoption()["headline"],
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
        self.assertEqual(view["registration"]["line"],
                         f"reconcile was not registered: {reason}. {note}")
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
        self.assertEqual(self.adoption()["headline"],
                         "repo is registered as fixture/console-merged.")
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
