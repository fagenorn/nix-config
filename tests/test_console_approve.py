"""The console's adoption approval (#1054): words, rows, fold and runners.

Run: just agent-workflow-tests
"""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path

from agent_tools.console import approve, event_log, folder_trust, register
from agent_tools.console.event_log import Event
from agent_tools.project_contract import adopt_apply
from agent_tools.system.forge_api import ForgeError

from . import accounts_sandbox
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1054)

PID = "sha256:" + "b" * 64
BRANCH = "adopt-bbbbbbbbbbbb"
COMMIT = "c" * 40
KEPT = {"branch": BRANCH, "worktree": "/h/.agents/state/adopt/worktrees/bbb"}
# What no reason, note, headline or line may show (written out here, not read from register).
INVARIANT = re.compile(r"--plan-id|sha256:|[0-9a-f]{12,}|(?:^|[\s(\"'])/\S")
BANNED = ("git ", "gh auth", "just switch", "adopt-project", PID, BRANCH, COMMIT,
          KEPT["worktree"], "/srv/r")


def step_payload(step="opened", plan_id="p1", **over):
    payload = {"by": "owner", "plan_id": plan_id, "root": "/srv/r", "project_id": "o/r",
               "step": step, "branch": BRANCH, "commit": COMMIT, "base": "develop",
               "pull_request": {"number": 7, "url": "https://example.test/pull/7"},
               "reason": None, "note": None, "kept": None}
    if step != "opened":
        payload["pull_request"] = None
        payload["base"] = None
    return {**payload, **over}


def step_event(seq, at, **kwargs):
    return Event(seq, at, approve.STEP, None, step_payload(**kwargs))


def pull_event(seq, at, plan_id, number, state):
    return Event(seq, at, approve.PULL, None,
                 approve.pull_row(plan_id, number, "u", state)[2])


def registration_event(seq, at, plan_id="p1", number=7, result="registered", project_id="o/r",
                       reason=None, note=None):
    return Event(seq, at, approve.REGISTRATION, None,
                 {"plan_id": plan_id, "number": number, "result": result,
                  "project_id": project_id, "reason": reason, "note": note})


class ParseTest(unittest.TestCase):
    def test_parse_approve_request_takes_exactly_a_plan_id(self):
        self.assertEqual(approve.parse_approve_request(b'{"plan_id": "sha256:aa"}'), "sha256:aa")
        for bad in (b'[]', b'{}', b'{"plan_id": ""}', b'{"plan_id": 1}',
                    b'{"plan_id": "a", "x": 1}', b'{"plan_id": "a\\u0007"}',
                    b'{"plan_id": "a\\u007f"}', b'\xff'):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                approve.parse_approve_request(bad)


class RowTest(unittest.TestCase):
    def test_step_row_takes_exactly_its_members(self):
        payload = step_payload()
        kind, project, row = approve.step_row(payload)
        self.assertEqual((kind, project, row), ("adoption.step", None, payload))
        self.assertIsNot(row, payload)
        self.assertEqual(approve.step_row(step_payload("apply_failed", kept=KEPT))[2]["kept"], KEPT)
        bad_rows = [{k: v for k, v in payload.items() if k != member} for member in payload]
        bad_rows += [
            {**payload, "x": 1}, {**payload, "by": "agent"}, {**payload, "step": "merged"},
            {**payload, "pull_request": {"number": True, "url": "u"}},
            {**payload, "pull_request": {"number": 0, "url": "u"}},
            {**payload, "kept": {"branch": "b"}}, {**payload, "pull_request": None},
            {**payload, "base": None}, {**payload, "plan_id": ""}, {**payload, "root": 1},
            {**payload, "note": 3},
            step_payload("push_failed", branch=None), step_payload("applied", commit=None)]
        for bad in bad_rows:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                approve.step_row(bad)

    def test_pull_row_takes_a_known_state(self):
        kind, project, payload = approve.pull_row("p", 7, "u", "ready")
        self.assertEqual((kind, project), ("adoption.pull_request", None))
        self.assertEqual(payload, {"plan_id": "p", "number": 7, "url": "u", "state": "ready"})
        for args in (("p", 7, "u", "draft"), ("p", 0, "u", "ready"), ("p", True, "u", "ready")):
            with self.subTest(args=args), self.assertRaises(ValueError):
                approve.pull_row(*args)

    def test_the_two_kinds_are_not_kept(self):
        self.assertEqual((approve.STEP, approve.PULL), (event_log.ADOPTION_STEP,
                                                        event_log.ADOPTION_PULL))
        self.assertNotIn(approve.STEP, event_log.KEPT_KINDS)
        self.assertNotIn(approve.PULL, event_log.KEPT_KINDS)


class RegistrationRowTest(unittest.TestCase):
    def test_registration_row_takes_exactly_its_members(self):
        base = {"plan_id": "p1", "number": 7, "result": "waiting", "project_id": None,
                "reason": None, "note": None}
        valid = [base, {**base, "result": "registered", "project_id": "o/r"},
                 {**base, "result": "refused", "reason": "r", "note": "n"}]
        for payload in valid:
            with self.subTest(payload=payload):
                kind, project, row = approve.registration_row(payload)
                self.assertEqual((kind, project, row), (approve.REGISTRATION, None, payload))
                self.assertIsNot(row, payload)
        refused = {**base, "result": "refused", "reason": "r", "note": "n"}
        registered = {**base, "result": "registered", "project_id": "o/r"}
        broken = [{**base, "extra": 1}, {k: v for k, v in base.items() if k != "note"},
                  {**base, "result": "merged"}, {**base, "number": 0}, {**base, "number": True},
                  {**base, "plan_id": ""}, {**registered, "project_id": None},
                  {**refused, "reason": None}, {**refused, "note": None}]
        for payload in broken:
            with self.subTest(broken=payload), self.assertRaises(ValueError):
                approve.registration_row(payload)
        self.assertEqual(approve.REGISTRATION, event_log.ADOPTION_REGISTRATION)
        self.assertEqual(approve.REGISTRATION, "adoption.registration")
        self.assertNotIn(approve.REGISTRATION, event_log.KEPT_KINDS)


class FoldTest(unittest.TestCase):
    def test_the_latest_step_and_pull_state_fold_per_plan(self):
        events = [step_event(1, "t1", step="applied"), step_event(2, "t2"),
                  pull_event(3, "t3", "p1", 7, "ready"),
                  step_event(4, "t4", step="push_failed", plan_id="p2")]
        found = approve.adoptions(events)
        self.assertEqual((found["p1"]["step"], found["p1"]["pull_state"],
                          found["p1"]["pull_at"], found["p1"]["at"]),
                         ("opened", "ready", "t3", "t2"))
        self.assertIsNone(found["p2"]["pull_state"])
        self.assertIsNone(found["p2"]["pull_at"])
        later = approve.adoptions([pull_event(5, "t5", "p1", 7, "merged")], found)
        self.assertEqual((later["p1"]["pull_state"], later["p1"]["pull_at"]), ("merged", "t5"))
        self.assertEqual(found["p1"]["pull_state"], "ready")

    def test_a_new_step_resets_the_pull_state(self):
        found = approve.adoptions([
            step_event(1, "t1"), pull_event(2, "t2", "p1", 7, "ready"),
            step_event(3, "t3", step="open_failed")])
        self.assertIsNone(found["p1"]["pull_state"])
        self.assertEqual(found["p1"]["step"], "open_failed")

    def test_a_pull_row_for_another_number_or_an_unopened_step_is_ignored(self):
        found = approve.adoptions([step_event(1, "t1"), pull_event(2, "t2", "p1", 8, "ready")])
        self.assertEqual(found["p1"]["pull_state"], "open")
        found = approve.adoptions([step_event(1, "t1", step="push_failed"),
                                   pull_event(2, "t2", "p1", 7, "ready")])
        self.assertIsNone(found["p1"]["pull_state"])
        broken = Event(3, "t3", approve.STEP, None,
                       {k: v for k, v in step_payload("applied").items() if k != "note"})
        self.assertEqual(approve.adoptions([broken]), {})
        self.assertEqual(approve.adoptions([pull_event(4, "t4", "zz", 7, "ready")]), {})

    def test_a_registration_row_folds_only_onto_its_merged_pull_request(self):
        merged = [step_event(1, "t1"), pull_event(2, "t2", "p1", 7, "merged")]
        found = approve.adoptions([*merged, registration_event(3, "t3")])
        self.assertEqual(found["p1"]["registration"],
                         {"result": "registered", "project_id": "o/r", "reason": None,
                          "note": None, "at": "t3"})
        other = approve.adoptions([*merged, registration_event(3, "t3", number=8)])
        self.assertIsNone(other["p1"]["registration"])
        unmerged = approve.adoptions([step_event(1, "t1", plan_id="p2"),
                                      registration_event(2, "t2", plan_id="p2")])
        self.assertIsNone(unmerged["p2"]["registration"])
        reset = approve.adoptions([*merged, registration_event(3, "t3"),
                                   step_event(4, "t4", step="open_failed")])
        self.assertIsNone(reset["p1"]["registration"])
        self.assertIsNone(approve.adoptions([step_event(1, "t1")])["p1"]["registration"])
        kept = approve.adoptions([pull_event(5, "t5", "p1", 7, "merged")], found)
        self.assertEqual(kept["p1"]["registration"]["at"], "t3")

    def test_enrolling_lists_merged_adoptions_not_yet_registered_or_refused(self):
        events = []
        for number, (plan, state) in enumerate(
                [("p1", "merged"), ("p2", "merged"), ("p3", "merged"), ("p4", "merged"),
                 ("p5", "closed"), ("p6", "open")]):
            events += [step_event(10 * number + 1, "a", plan_id=plan),
                       pull_event(10 * number + 2, "b", plan, 7, state)]
        events += [registration_event(100, "c", plan_id="p2", result="waiting", project_id=None),
                   registration_event(101, "c", plan_id="p3"),
                   registration_event(102, "c", plan_id="p4", result="refused", project_id=None,
                                      reason="r", note="n")]
        result = approve.enrolling(approve.adoptions(events))
        self.assertEqual([e["plan_id"] for e in result], ["p1", "p2"])

    def test_waiting_lists_open_and_ready_by_plan_id(self):
        found = approve.adoptions([
            step_event(1, "t1", plan_id="p2"), step_event(2, "t2", plan_id="p1"),
            pull_event(3, "t3", "p1", 7, "ready"), step_event(4, "t4", plan_id="p3"),
            pull_event(5, "t5", "p3", 7, "merged"),
            step_event(6, "t6", step="push_failed", plan_id="p4")])
        self.assertEqual([e["plan_id"] for e in approve.waiting(found)], ["p1", "p2"])


FORGE_ERRORS = (
    KeyError("x"), ForgeError("gh_missing", "x"), ForgeError("gh_timeout", "api"),
    ForgeError("gh_failed", "error connecting to api.github.com", transient=True),
    ForgeError("gh_failed", "gh: Bad credentials (HTTP 401)"),
    ForgeError("gh_failed", "gh: Forbidden (HTTP 403)"),
    ForgeError("gh_failed", "gh: Validation Failed (HTTP 422)"),
    ForgeError("gh_failed", "gh: Not Found (HTTP 404)"),
    ForgeError("payload_invalid", "x"), ForgeError("gh_failed", "gh: odd (HTTP 418)"))


class WordsTest(unittest.TestCase):
    def test_each_forge_failure_reads_its_reason_and_next_step(self):
        again = "then choose Try again."
        sign_in = ("Sign gh in on this computer with an account that may open pull requests on "
                   "the repository, " + again)
        cases = [
            (KeyError("x"), (register.UNEXPECTED, approve.OPEN_NOTE)),
            (ForgeError("gh_missing", "x"),
             ("gh is not installed on this host",
              "Install gh on this computer and sign it in, " + again)),
            (ForgeError("gh_timeout", "api"),
             ("the forge took too long to answer",
              "Choose Try again; the console first looks for a pull request the forge may have "
              "opened already.")),
            (ForgeError("gh_failed", "error connecting to api.github.com", transient=True),
             ("the forge could not be reached",
              "Check this host's network connection, " + again)),
            (ForgeError("gh_failed", "gh: Bad credentials (HTTP 401)"),
             ("gh is not signed in, or may not open pull requests on this repository", sign_in)),
            (ForgeError("gh_failed", "gh: Forbidden (HTTP 403)"),
             ("gh is not signed in, or may not open pull requests on this repository", sign_in)),
            (ForgeError("gh_failed", "gh: Validation Failed (HTTP 422)"),
             ("the forge refused the pull request",
              "Check on the forge that the adoption's branch differs from develop and has no "
              "pull request open already, " + again)),
            (ForgeError("gh_failed", "gh: Not Found (HTTP 404)"),
             ("the forge does not know the repository or the branch",
              "Check that origin is the GitHub repository and that the adoption's branch "
              "reached it, " + again)),
            (ForgeError("payload_invalid", "x"),
             ("the forge answered in a way the console does not understand",
              approve.OPEN_NOTE)),
            (ForgeError("gh_failed", "gh: odd (HTTP 418)"),
             ("the forge answered in a way the console does not understand",
              approve.OPEN_NOTE)),
        ]
        for error, expected in cases:
            with self.subTest(error=repr(error)):
                got = approve.forge_failure(error, "develop")
                self.assertEqual(got, expected)
                for text in got:
                    for word in ("HTTP", "401", "403", "404", "422", "gh_", "payload_invalid",
                                 "KeyError"):
                        self.assertNotIn(word, text)

    def test_each_apply_error_reads_its_reason_and_next_step(self):
        def error(code="verification_failed", repair_id="", message=None):
            violations = [] if message is None else [{"pointer": "", "message": message}]
            return {"code": code, "repair_id": repair_id, "violations": violations}

        def words(err, kept=None):
            return approve.apply_failure("r", err, kept)

        leftover = ("A leftover copy of the adoption is kept on this computer; ask an agent to "
                    "remove it before you choose Apply it again.")
        commit_note = ("Choose Apply it again. If it keeps failing, ask an agent to apply the "
                       "adoption of r in a terminal, which shows the full reason.")
        self.assertEqual(approve.KEPT_SENTENCE, leftover)
        self.assertEqual(words(error("plan_stale", "adopt.plan.inputs_changed")), (
            "the repository changed since this plan was made",
            "Register the repository again to make a new plan, then apply that one."))
        self.assertEqual(words(error(repair_id="adopt.worktree.dirty")), (
            "an uncommitted change in the repository overlaps what the plan changes",
            "Set aside the uncommitted change in r, then choose Apply it again. To keep the "
            "change instead, commit it, then register the repository again to make a new "
            "plan."))
        self.assertEqual(words(error(repair_id="adopt.worktree.retained"), KEPT), (
            "an earlier attempt of this plan is still kept",
            "A leftover copy of the adoption is kept on this computer; ask an agent to remove "
            "it, then choose Apply it again."))
        self.assertEqual(words(error(repair_id="adopt.worktree.unavailable")), (
            "the adoption's branch or worktree could not be created",
            "If a branch from an earlier attempt of this adoption is left, ask an agent to "
            "delete it, then choose Apply it again."))
        self.assertEqual(words(error(repair_id="adopt.commit.failed"), KEPT), (
            "the adoption commit could not be made", commit_note + " " + leftover))
        self.assertEqual(words(error(repair_id="adopt.commit.failed")), (
            "the adoption commit could not be made", commit_note))
        self.assertEqual(words(error(repair_id="adopt.gate.no-new-broken-link"), KEPT), (
            "the no-new-broken-link check did not pass",
            "Fix what failed in the repository, then register the repository again. "
            + leftover))
        self.assertEqual(words(error(repair_id="adopt.gate.no-new-broken-link")), (
            "the no-new-broken-link check did not pass",
            "Fix what failed in the repository, then register the repository again."))
        self.assertEqual(words(error(repair_id="adopt.manifest.missing"), KEPT), (
            "the agent platform's files are not installed on this host yet",
            "Switch this computer to its current configuration to install them, then choose "
            "Apply it again."))
        for repair, reason in (
                ("adopt.format.failed", "a formatter the project declares did not run cleanly"),
                ("adopt.operation.failed", "one of the plan's changes could not be written"),
                ("adopt.plan.unknown_id", "the stored plan could not be used"),
                ("adopt.resolver.failed", "the project contract could not be read"),
                ("adopt.commit.unresolved_policy",
                 "the adoption commit did not pass its own checks")):
            with self.subTest(repair=repair):
                self.assertEqual(words(error(repair_id=repair)), (reason, commit_note))
                self.assertEqual(words(error(repair_id=repair), KEPT),
                                 (reason, commit_note + " " + leftover))
        self.assertEqual(words(error(message="a  pre-commit\ngate")),
                         ("it could not be applied", commit_note))
        self.assertEqual(words(error(), KEPT),
                         ("it could not be applied", commit_note + " " + leftover))
        self.assertEqual(words(error()), ("it could not be applied", commit_note))

    def test_a_failed_discard_on_apply_it_again_offers_it_again(self):
        error = {"code": "adopt_failure", "repair_id": "adopt.discard.failed",
                 "violations": [{"pointer": "", "message": "the retained worktree of this plan "
                                                           "could not be removed"}]}
        self.assertEqual(approve.DISCARD_REPAIR, "adopt.discard.failed")
        self.assertEqual(approve.apply_failure("r", error, None),
                         (approve.DISCARD_REASON, approve.RETAINED_NOTE))
        self.assertEqual(approve.DISCARD_REASON, "the copy that the last attempt left on this "
                                                 "computer could not be removed")
        self.assertEqual(approve.RETAINED_NOTE,
                         "Choose Apply it again to remove the copy that attempt left on this "
                         "computer and apply the plan again.")

    def test_a_run_failure_reads_in_words(self):
        note = ("Choose Apply it again. If it keeps failing, ask an agent to apply the adoption "
                "of r in a terminal, which shows the full reason.")
        self.assertEqual(approve.run_failure("r", "timed_out"),
                         ("it took too long and was stopped", note))
        self.assertEqual(approve.run_failure("r", "failed"),
                         ("the adoption tool stopped with an error", note))
        self.assertEqual(approve.run_failure("r", "Boom"), ("it stopped unexpectedly", note))

    def test_each_note_names_the_option_of_its_card(self):
        again = [approve.forge_failure(error, "develop")[1] for error in FORGE_ERRORS]
        again += [approve.PUSH_NOTE, approve.OPEN_NOTE, approve.APPLIED_NOTE]
        for note in again:
            with self.subTest(note=note):
                self.assertIn("Try again", note)
        not_now = [approve.NO_SLUG_NOTE, approve.NO_BASE_NOTE]
        for note in not_now:
            with self.subTest(note=note):
                self.assertIn("Not now", note)
                self.assertNotIn("Try again", note)
        apply_it = []
        for repair, kept in (("adopt.worktree.dirty", None), ("adopt.worktree.retained", KEPT),
                             ("adopt.worktree.unavailable", None),
                             (approve.SIGNING_REPAIR, KEPT), (approve.COMMIT_REPAIR, None),
                             (register.MANIFEST_PREFIX + "missing", None)):
            apply_it.append(approve.apply_failure(
                "r", {"code": "verification_failed", "repair_id": repair,
                      "violations": []}, kept)[1])
        apply_it += [approve.run_failure("r", kind)[1] for kind in register.RETRY_KINDS]
        apply_it.append(approve.CLOSED_NOTE)
        for note in apply_it:
            with self.subTest(note=note):
                self.assertIn("Apply it again", note)
        for note in again + not_now + apply_it:
            with self.subTest(note=note):
                self.assertNotIn("press", note.lower())
                self.assertNotIn("Approve", note)
        self.assertEqual(
            approve.CLOSED_NOTE,
            "Ask an agent to delete the adoption's branch on this computer and on origin, then "
            "choose Apply it again.")

    def test_no_reason_or_note_shows_a_code_or_kind(self):
        texts = []
        for repair in ("adopt.worktree.dirty", "adopt.worktree.retained",
                       "adopt.worktree.unavailable", "adopt.gate.g", "adopt.manifest.x", ""):
            for kept in (None, KEPT):
                texts += approve.apply_failure(
                    "r", {"code": "plan_stale", "repair_id": repair,
                          "violations": []}, kept)
        texts += approve.apply_failure("r", {"code": "plan_stale", "repair_id": "",
                                             "violations": []}, None)
        for kind in (*register.RUN_KINDS, "KeyError"):
            texts += approve.run_failure("r", kind)
        for text in texts:
            for word in ("adopt.", "plan_stale", "verification_failed", "KeyError", "timed_out",
                         "not_installed", "unreadable", "Error"):
                self.assertNotIn(word, text)

    def test_reason_of_collapses_and_cuts(self):
        self.assertEqual(approve.reason_of("a\n  b"), "a b")
        cut = approve.reason_of("x" * 300)
        self.assertEqual((len(cut), cut[-1]), (200, "…"))

    def test_the_running_headline_and_the_plan_branch(self):
        self.assertEqual(approve.running_headline("r"),
                         "Applying the adoption of r and opening its pull request…")
        self.assertEqual(approve.branch_of(PID), BRANCH)


class ApplyWordsTest(unittest.TestCase):
    SIGNING = {"code": "verification_failed", "repair_id": "adopt.commit.signing_unavailable",
               "violations": [{"pointer": "", "message": "the contract asks for a signed commit "
                                                         "and this host could not sign one"}]}

    def assert_plain(self, text):
        self.assertIsNone(INVARIANT.search(text), text)
        for banned in BANNED:
            self.assertNotIn(banned, text)

    def test_a_signing_failure_names_its_cause_and_next_step(self):
        reason = ("the project asks for signed commits and this computer could not sign the "
                  "adoption commit")
        note = ("Set up a signing key on this computer, then choose Apply it again. To turn "
                "signed commits off in the project's settings instead, commit that change, then "
                "register the repository again to make a new plan.")
        got_kept = approve.apply_failure("r", self.SIGNING, KEPT)
        got_none = approve.apply_failure("r", self.SIGNING, None)
        self.assertEqual(got_none, (reason, note))
        self.assertEqual(got_kept, (reason, note + " " + approve.KEPT_SENTENCE))
        self.assertNotIn("leftover", got_none[1])
        adoption = {**step_payload("apply_failed", reason=got_kept[0], note=got_kept[1],
                                   kept=KEPT, branch=None, commit=None),
                    "at": "t", "pull_state": None, "pull_at": None}
        self.assertEqual(
            approve.entry(adoption, running=False, name="r")["headline"],
            "The adoption of r was not applied: the project asks for signed commits and this "
            "computer could not sign the adoption commit.")

    def test_no_failure_card_or_line_shows_a_command_hash_or_path(self):
        texts = [approve.CLOSED_NOTE, approve.NO_SLUG_NOTE, approve.NO_BASE_NOTE,
                 approve.PUSH_REFUSED, approve.PUSH_NOTE, approve.OPEN_NOTE, approve.APPLIED_NOTE]
        for repair in ("adopt.worktree.dirty", "adopt.worktree.retained",
                       "adopt.worktree.unavailable", approve.SIGNING_REPAIR,
                       approve.COMMIT_REPAIR, "adopt.gate.no-new-broken-link",
                       register.MANIFEST_PREFIX + "missing", "adopt.format.failed",
                       "adopt.operation.failed", "adopt.plan.unknown_id",
                       "adopt.resolver.failed", "adopt.commit.unresolved_policy",
                       "adopt.zzz.unknown", ""):
            for kept in (None, KEPT):
                texts += approve.apply_failure(
                    "r", {"code": "x", "repair_id": repair, "violations": []}, kept)
        texts += approve.apply_failure(
            "r", {"code": "plan_stale", "repair_id": "", "violations": []}, KEPT)
        for kind in (*register.RUN_KINDS, "KeyError"):
            texts += approve.run_failure("r", kind)
        for error in FORGE_ERRORS:
            texts += approve.forge_failure(error, "develop")
        for text in texts:
            with self.subTest(text=text):
                self.assert_plain(text)
        rows = [("applied", None, {}),
                ("apply_failed", None, {"reason": "it broke", "note": "N", "kept": KEPT,
                                        "branch": None, "commit": None}),
                ("push_failed", None, {"reason": approve.PUSH_REFUSED,
                                       "note": approve.PUSH_NOTE}),
                ("open_failed", None, {"reason": "the forge refused the pull request",
                                       "note": approve.OPEN_NOTE}),
                *(("opened", state, {}) for state in ("open", "ready", "merged", "closed"))]
        for step, state, over in rows:
            with self.subTest(step=step, state=state):
                adoption = {**step_payload(step, **over), "at": "t", "pull_state": state,
                            "pull_at": None}
                got = approve.entry(adoption, running=False, name="r")
                self.assertEqual(got["lines"], [])
                self.assert_plain(got["headline"])
                if got["note"] is not None:
                    self.assert_plain(got["note"])

    def test_raw_diagnostics_never_reach_a_card(self):
        def error(repair, message):
            return {"code": "x", "repair_id": repair,
                    "violations": [{"pointer": "", "message": message}]}

        errors = [
            {**error("adopt.format.failed",
                     "the declared formatter 'fmt' exited 1; stderr ends: "
                     "/h/.agents/state/adopt/worktrees/" + "b" * 64 + "/x.nix: bad"),
             "code": "verification_failed"},
            error("adopt.operation.failed", "could not write /srv/r/.claude/x"),
            error("adopt.plan.unknown_id", "no plan " + PID),
            error("adopt.zzz.unknown", "branch adopt-bbbbbbbbbbbb exists")]
        reasons = ["a formatter the project declares did not run cleanly",
                   "one of the plan's changes could not be written",
                   "the stored plan could not be used", "it could not be applied"]
        for err, reason in zip(errors, reasons):
            with self.subTest(reason=reason):
                got = approve.apply_failure("r", err, None)
                self.assertEqual(got[0], reason)
                for text in got:
                    self.assert_plain(text)
        outcome = approve.registration_outcome("/srv/r", {"error": error(
            "adopt.git.fetch_failed",
            "fatal: '/srv/remote.git' does not appear to be a git repository")})
        self.assertEqual(outcome["reason"], "it could not be registered")


def report_error(repair, message):
    return {"error": {"code": "not_integrated", "repair_id": repair,
                      "violations": [{"pointer": "", "message": message}]}}


FULL_REASON = ("Choose Retry. If it keeps failing, ask an agent to register r in a terminal, "
               "which shows the full reason.")
UNCHECKED = "the adoption on the remote did not pass the registration's checks"


def refused(reason, note):
    return {"result": "refused", "project_id": None, "reason": reason, "note": note}


class OutcomeTest(unittest.TestCase):
    def table(self):
        return [
            (report_error("adopt.registration.not_integrated",
                          "the remote integration branch carries no adoption evidence record"),
             {"result": "waiting", "project_id": None, "reason": None, "note": None}),
            ({"registered": True, "project_id": "o/r", "result": "adopted"},
             {"result": "registered", "project_id": "o/r", "reason": None, "note": None}),
            (report_error("adopt.registration.no_remote", "the repository has no origin remote"),
             refused("the repository has no origin remote",
                     "Add the repository's origin remote, then choose Retry.")),
            (report_error("adopt.manifest.missing", register.MANIFEST_ABSENT),
             refused("the agent platform's files are not installed on this host",
                     "Switch this computer to its current configuration to install them, then "
                     "choose Retry.")),
            (report_error("adopt.registration.integration_branch_unresolved", "m"),
             refused("m", FULL_REASON)),
            ({"registered": False, "result": "not_conformant"},
             refused(UNCHECKED, FULL_REASON)),
            ({"registered": True}, refused(UNCHECKED, FULL_REASON)),
            (None, refused("the adoption tool gave an answer that could not be read",
                           FULL_REASON)),
        ]

    def test_each_report_reads_as_waiting_registered_or_refused(self):
        for report, expected in self.table():
            with self.subTest(report=report):
                self.assertEqual(approve.registration_outcome("/srv/r", report), expected)

    def test_a_run_failure_reads_in_words_with_retry(self):
        got = {kind: approve.run_outcome("/srv/r", kind)
               for kind in ("timed_out", "failed", "KeyError")}
        self.assertEqual(got["timed_out"], refused(
            "it took too long and was stopped", FULL_REASON))
        self.assertEqual(got["failed"], refused(
            "the adoption tool stopped with an error", FULL_REASON))
        self.assertEqual(got["KeyError"]["reason"], "it stopped unexpectedly")
        for outcome in got.values():
            self.assertEqual((outcome["result"], outcome["project_id"]),
                             ("refused", None))

    def test_no_reason_or_note_shows_a_code_or_sends_the_owner_to_register_again(self):
        outcomes = [expected for _, expected in self.table() if expected["result"] == "refused"]
        outcomes += [approve.run_outcome("/srv/r", kind) for kind in register.RUN_KINDS]
        for outcome in outcomes:
            with self.subTest(outcome=outcome):
                for text in (outcome["reason"], outcome["note"]):
                    for banned in ("adopt.", "_", "Register again", "press Register"):
                        self.assertNotIn(banned, text)
                self.assertIn("Retry", outcome["note"])
        for report, expected in self.table():
            if expected["result"] == "refused":
                self.assertEqual(approve.registration_outcome("/srv/r", report), expected)


class EntryTest(unittest.TestCase):
    def adoption(self, step, pull_state=None, **over):
        return {**step_payload(step, **over), "at": "t", "pull_state": pull_state,
                "pull_at": None}

    def test_the_entry_per_step_and_pull_state(self):
        waits = ("The pull request of r was merged; waiting for develop on origin to carry it "
                 "before registering.")
        url = "https://example.test/pull/7"
        table = [
            (self.adoption("applied"),
             ("applied", None, "The adoption of r was applied, but its branch is not pushed yet.",
              [], approve.APPLIED_NOTE, None)),
            (self.adoption("apply_failed", reason="it broke", note="N", kept=KEPT,
                           branch=None, commit=None),
             ("apply_failed", None, "The adoption of r was not applied: it broke.",
              [], "N", None)),
            (self.adoption("apply_failed", reason="it broke.", note="N", branch=None,
                           commit=None),
             ("apply_failed", None, "The adoption of r was not applied: it broke.", [], "N",
              None)),
            (self.adoption("push_failed", reason="no route", note="N"),
             ("push_failed", None,
              "The adoption of r was applied, but its branch was not pushed: no route.",
              [], "N", None)),
            (self.adoption("open_failed", reason="refused", note="N"),
             ("open_failed", None,
              "The adoption of r was pushed, but its pull request was not opened: refused.",
              [], "N", None)),
            (self.adoption("opened", "open"),
             ("opened", "open", "r: waiting for its pull request to be ready to merge",
              [], None, url)),
            (self.adoption("opened", "ready"),
             ("opened", "ready", "The pull request of r is ready to merge.",
              [], None, url)),
            (self.adoption("opened", "merged"),
             ("opened", "merged", waits, [], None, url)),
            (self.adoption("opened", "closed"),
             ("opened", "closed", "The pull request of r was closed without merging.",
              [], approve.CLOSED_NOTE, url)),
        ]
        for adoption, (step, state, headline, lines, note, link) in table:
            with self.subTest(step=step, state=state):
                got = approve.entry(adoption, running=False, name="r")
                self.assertEqual(set(got), {"status", "step", "state", "headline", "lines",
                                            "note", "branch", "commit", "url"})
                self.assertEqual(
                    (got["status"], got["step"], got["state"], got["headline"], got["lines"],
                     got["note"], got["url"]),
                    ("done", step, state, headline, lines, note, link))
                self.assertEqual((got["branch"], got["commit"]),
                                 (adoption["branch"], adoption["commit"]))

    def test_a_merged_adoption_reads_its_registration_state(self):
        waits = ("The pull request of r was merged; waiting for develop on origin to carry it "
                 "before registering.")
        stamp = {"project_id": None, "reason": None, "note": None, "at": "t"}
        table = [
            ({}, False, waits),
            ({"registration": None}, False, waits),
            ({"registration": {**stamp, "result": "waiting"}}, False, waits),
            ({"registration": {**stamp, "result": "registered", "project_id": "o/r"}}, False,
             "r is registered as o/r."),
            ({"registration": {**stamp, "result": "refused", "reason": "no origin",
                               "note": "Add the origin, then choose Retry."}}, False,
             "r was not registered: no origin. Add the origin, then choose Retry."),
            ({}, True, "Registering r…"),
        ]
        for over, registering, headline in table:
            with self.subTest(headline=headline):
                adoption = {**self.adoption("opened", "merged", base="develop"), **over}
                got = approve.entry(adoption, running=False, name="r", registering=registering)
                self.assertEqual(got["headline"], headline)
                self.assertIsNone(got["note"])
                self.assertEqual(set(got), {"status", "step", "state", "headline", "lines",
                                            "note", "branch", "commit", "url"})
                self.assertEqual(got["lines"], [])

    def test_none_and_running(self):
        self.assertIsNone(approve.entry(None, running=False, name="r"))
        self.assertEqual(approve.entry(None, running=True, name="r"), {
            "status": "running", "step": None, "state": None,
            "headline": "Applying the adoption of r and opening its pull request…",
            "lines": [], "note": None, "branch": None, "commit": None, "url": None})


    def test_a_note_stored_in_the_old_words_reads_in_the_card_words(self):
        cases = [
            ("push_failed",
             "Check that the repository's origin can be reached from this host and accepts the "
             "push, then press Try again.", approve.PUSH_NOTE),
            ("open_failed",
             "Press Try again; the console first looks for a pull request the forge may have "
             "opened already.",
             "Choose Try again; the console first looks for a pull request the forge may have "
             "opened already."),
            ("open_failed",
             f"Check on the forge that {BRANCH} differs from develop and has no pull request "
             "open already, then press Try again.",
             f"Check on the forge that {BRANCH} differs from develop and has no pull request "
             "open already, then choose Try again."),
            ("apply_failed",
             "Commit or set aside the uncommitted change in /srv/r, then press Approve again.",
             "Commit or set aside the uncommitted change in /srv/r, then choose Apply it again."),
            ("apply_failed",
             "Press Approve again. If it keeps failing, run adopt-project apply --plan-id p1 in "
             "a terminal to see the full reason.",
             "Choose Apply it again. If it keeps failing, run adopt-project apply --plan-id p1 "
             "in a terminal to see the full reason."),
            ("apply_failed",
             "Register the repository again to make a new plan, then approve that one.",
             "Register the repository again to make a new plan, then apply that one."),
        ]
        self.assertEqual(approve.PUSH_NOTE, "Check that the repository's origin can be reached "
                         "from this host and accepts the push, then choose Try again.")
        for step, old, new in cases:
            with self.subTest(old=old):
                found = self.adoption(step, reason="r", note=old)
                self.assertEqual(approve.entry(found, running=False, name="r")["note"], new)
                self.assertEqual(found["note"], old)
        self.assertIsNone(approve.current_note(None))
        self.assertEqual(approve.current_note("Remove it first."), "Remove it first.")


class RetryEntryTest(unittest.TestCase):
    def test_only_a_refused_registration_is_a_retry_item(self):
        note = "Add the repository's origin remote, then choose Retry."
        reason = "the repository has no origin remote"
        events = []
        for seq, (plan, root, at) in enumerate([("p1", "/srv/r", "t5"), ("p0", "/srv/zz", "t4")]):
            events += [step_event(10 * seq + 1, "a", plan_id=plan, root=root, project_id=None),
                       pull_event(10 * seq + 2, "b", plan, 7, "merged"),
                       registration_event(10 * seq + 3, at, plan_id=plan, result="refused",
                                          project_id=None, reason=reason, note=note)]
        events += [step_event(40, "a", plan_id="p2"), pull_event(41, "b", "p2", 7, "merged"),
                   registration_event(42, "c", plan_id="p2", result="waiting", project_id=None),
                   step_event(43, "a", plan_id="p3"), pull_event(44, "b", "p3", 7, "merged"),
                   registration_event(45, "c", plan_id="p3")]
        found = approve.adoptions(events)
        items = approve.retry_entries(found)
        self.assertEqual([i["key"] for i in items],
                         ["register-retry/p0/t4", "register-retry/p1/t5"])
        headline = "r was not registered: the repository has no origin remote."
        self.assertEqual(items[1], {
            "type": "inbox_item", "reason": "register_retry", "key": "register-retry/p1/t5",
            "project_id": None, "root": "/srv/r", "name": "r", "title": "Register r",
            "plan_id": "p1", "id": None, "subject": None, "headline": headline, "why": note,
            "refusal": None, "more_questions": 0,
            "questions": [{"question": headline, "options": ["Retry"], "chosen": None,
                           "recommended": None, "recommended_index": None}],
            "values": ["retry"], "items": [], "answers": [], "answered": False,
            "waiting_since": "t5"})
        self.assertEqual([i["plan_id"] for i in approve.retry_entries(found, running={"p1"})],
                         ["p0"])


class ApplyItemTest(unittest.TestCase):
    LATEST = {"root": "/srv/sample-app", "plan_id": "p", "state": "ready",
              "lines": ["moves 2 agent files under .agents/", "writes the project contract"],
              "at": "t1"}

    def adoption(self, step, pull_state=None, **over):
        return {**step_payload(step), "at": "t2", "pull_state": pull_state, "pull_at": None,
                **over}

    def item(self, key, headline, why, lines, first, value, since):
        return {"type": "inbox_item", "reason": "register_apply", "key": key,
                "project_id": None, "root": "/srv/sample-app", "name": "sample-app",
                "title": "Register sample-app", "plan_id": "p", "id": None, "subject": None,
                "headline": headline, "why": why, "lines": lines, "refusal": None,
                "more_questions": 0, "text": False,
                "questions": [{"question": headline, "options": [first, "Not now"],
                               "chosen": None, "recommended": None,
                               "recommended_index": None}],
                "values": [value, "not_now"], "items": [], "answers": [], "answered": False,
                "waiting_since": since}

    def test_a_ready_plan_with_no_adoption_is_one_apply_item(self):
        got = approve.apply_items(self.LATEST, None, None, approve.action(
            self.LATEST, None, available=True, running=False))
        self.assertEqual(got, [self.item(
            "register-apply/p/t1", "Apply this adoption?", folder_trust.TRUST_SENTENCE,
            list(self.LATEST["lines"]),
            "Apply it", "apply", "t1")])

    def test_the_apply_card_says_what_registering_allows(self):
        got = approve.apply_items(self.LATEST, None, None, "approve")
        self.assertEqual(
            got[0]["why"],
            "Registering lets agents run in this folder with the folder's own settings and hooks.")

    def test_a_resumable_step_is_one_try_again_item(self):
        for step in approve.RESUMABLE:
            with self.subTest(step=step):
                found = self.adoption(step, reason="no route", note="N")
                entry = approve.entry(found, running=False, name="sample-app")
                got = approve.apply_items(self.LATEST, found, entry, "retry")
                self.assertEqual(got, [self.item(
                    "register-apply/p/t1/t2", entry["headline"], entry["note"], [],
                    "Try again", "retry", "t2")])

    def test_a_failed_apply_and_a_closed_pull_request_offer_apply_it_again(self):
        failed = self.adoption("apply_failed", reason="it broke", note="Remove it first.",
                               kept=KEPT, branch=None, commit=None)
        closed = self.adoption("opened", "closed", root="/srv/sample-app", pull_at="t3")
        self.assertEqual(closed["pull_at"], "t3")
        for found, since in ((failed, "t2"), (closed, "t3")):
            with self.subTest(step=found["step"]):
                entry = approve.entry(found, running=False, name="sample-app")
                got = approve.apply_items(self.LATEST, found, entry, "approve")
                self.assertEqual(got, [self.item(
                    "register-apply/p/t1/t2", entry["headline"], entry["note"], [],
                    "Apply it again", "apply", since)])
        self.assertEqual(
            approve.entry(closed, running=False, name="sample-app")["note"],
            approve.CLOSED_NOTE)

    def test_no_action_or_a_deferred_plan_is_no_item(self):
        self.assertEqual(approve.apply_items(self.LATEST, None, None, None), [])
        self.assertEqual(approve.apply_items(None, None, None, "approve"), [])
        self.assertEqual(approve.apply_items(self.LATEST, None, None, "approve",
                                             deferred=frozenset({"p"})), [])
        self.assertEqual(len(approve.apply_items(self.LATEST, None, None, "approve",
                                                 deferred=frozenset({"q"}))), 1)

    def test_the_deferral_row_and_its_fold(self):
        self.assertEqual(approve.deferral_row("p"),
                         (event_log.ADOPTION_DEFERRED, None, {"plan_id": "p"}))
        for bad in ("", None, 3):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                approve.deferral_row(bad)
        self.assertEqual(approve.DEFERRED, "adoption.deferred")
        self.assertEqual(event_log.ADOPTION_DEFERRED, "adoption.deferred")
        self.assertNotIn(event_log.ADOPTION_DEFERRED, event_log.KEPT_KINDS)
        events = [Event(1, "t", approve.DEFERRED, None, {"plan_id": "p"}),
                  Event(2, "t", approve.DEFERRED, None, {"plan_id": ""}),
                  Event(3, "t", approve.DEFERRED, None, {"plan_id": "q", "x": 1}),
                  Event(4, "t", approve.STEP, None, {"plan_id": "r"})]
        self.assertEqual(approve.deferrals(events), frozenset({"p"}))
        self.assertEqual(approve.deferrals([], frozenset({"z"})), frozenset({"z"}))


class ActionTest(unittest.TestCase):
    READY = {"state": "ready", "plan_id": "p", "lines": []}

    def act(self, latest=READY, adoption=None, available=True, running=False):
        return approve.action(latest, adoption, available=available, running=running)

    def test_the_action_table(self):
        self.assertEqual(self.act(), "approve")
        self.assertEqual(self.act(adoption={"step": "apply_failed"}), "approve")
        for step in approve.RESUMABLE:
            self.assertEqual(self.act(adoption={"step": step}), "retry")
        for state in ("open", "ready", "merged"):
            self.assertIsNone(self.act(adoption={"step": "opened", "pull_state": state}))
        self.assertEqual(self.act(adoption={"step": "opened", "pull_state": "closed"}),
                         "approve")
        self.assertIsNone(self.act(available=False))
        self.assertIsNone(self.act(running=True))
        self.assertIsNone(self.act(latest=None))
        self.assertIsNone(self.act(latest={**self.READY, "state": "draft"}))
        self.assertIsNone(self.act(latest={**self.READY, "plan_id": None}))

    def test_deletions_are_acknowledged_only_when_a_deletes_line_is_shown(self):
        self.assertTrue(approve.acknowledges({"lines": ["moves 1 agent file", "deletes a.json"]}))
        self.assertFalse(approve.acknowledges({"lines": ["writes deletes.md"]}))
        self.assertFalse(approve.acknowledges({"lines": []}))


class TitleBodyTest(unittest.TestCase):
    def test_the_title_and_body_are_plain_words_from_the_plan(self):
        self.assertEqual(approve.title("r"), "Adopt r onto the agent platform")
        self.assertEqual(
            approve.body({"headline": "H", "lines": ["a", "b"], "plan_id": "p"}),
            "H\n\n- a\n- b\n\nPlan p, approved by the owner on the console. Merge it once its "
            "required checks pass.")


class PullSlugTest(unittest.TestCase):
    def test_the_repository_is_read_from_the_recorded_link(self):
        self.assertEqual(approve.pull_slug({"number": 7, "url": "https://github.com/o/r/pull/7"}),
                         "o/r")

    def test_a_link_that_is_not_a_pull_request_link_of_that_number_names_no_repository(self):
        for url in ("https://example.test/pull/7", "https://github.com/o/r/pull/8",
                    "https://github.com/o/r/issues/7", "https://github.com/o/r/pull/7/files", ""):
            with self.subTest(url=url):
                self.assertIsNone(approve.pull_slug({"number": 7, "url": url}))


class InboxEntryTest(unittest.TestCase):
    def test_only_a_ready_pull_request_is_an_item(self):
        events = [
            step_event(1, "a1", plan_id="p1"), pull_event(2, "a2", "p1", 7, "ready"),
            step_event(3, "a3", plan_id="p2"),
            step_event(4, "a4", plan_id="p3"), pull_event(5, "a5", "p3", 7, "merged"),
            step_event(6, "a6", step="push_failed", plan_id="p4"),
            step_event(7, "a7", plan_id="p0", root="/srv/zz", project_id=None),
            pull_event(8, "a8", "p0", 7, "ready")]
        events[1] = Event(2, "t2", approve.PULL, None,
                          approve.pull_row("p1", 7, "https://example.test/pull/7", "ready")[2])
        events[7] = Event(8, "t1", approve.PULL, None,
                          approve.pull_row("p0", 7, "u", "ready")[2])
        found = approve.inbox_entries(approve.adoptions(events))
        self.assertEqual([e["key"] for e in found], ["adoption/p0", "adoption/p1"])
        self.assertEqual(found[0]["headline"], "The adoption of zz is ready to merge")
        self.assertEqual(found[1], {
            "type": "inbox_item", "reason": "adoption", "key": "adoption/p1",
            "project_id": "o/r", "name": "r", "headline": "The adoption of o/r is ready to merge",
            "url": "https://example.test/pull/7", "number": 7, "answered": False,
            "waiting_since": "t2"})


class RetainedTest(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp(dir=accounts_sandbox.root())).resolve()
        previous = os.environ["HOME"]
        os.environ["HOME"] = str(self.home)
        self.addCleanup(os.environ.__setitem__, "HOME", previous)
        self.addCleanup(shutil.rmtree, self.home, True)
        self.record = adopt_apply.failure_record_path("b" * 64)
        self.record.parent.mkdir(parents=True)
        self.worktree = self.home / "wt"
        self.worktree.mkdir()

    def write(self, text):
        self.record.write_text(text)

    def test_a_kept_worktree_is_read_from_the_failure_record(self):
        self.write(json.dumps({"branch": BRANCH, "worktree": str(self.worktree)}))
        self.assertEqual(approve.retained(PID),
                         {"branch": BRANCH, "worktree": str(self.worktree)})

    def test_a_record_whose_worktree_is_gone_is_none(self):
        self.write(json.dumps({"branch": BRANCH, "worktree": str(self.worktree)}))
        self.worktree.rmdir()
        self.assertIsNone(approve.retained(PID))

    def test_a_bad_plan_id_or_record_is_none(self):
        self.assertIsNone(approve.retained("x"))
        self.assertIsNone(approve.retained(PID))
        self.write("[]")
        self.assertIsNone(approve.retained(PID))
        self.write(json.dumps({"branch": 1, "worktree": str(self.worktree)}))
        self.assertIsNone(approve.retained(PID))
        self.write(json.dumps({"branch": BRANCH, "worktree": str(self.worktree),
                               "pad": "x" * 70000}))
        self.assertIsNone(approve.retained(PID))


ADOPTION = "adopt-0123456789ab"
GIT_ENV = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}


def sandbox_dir() -> Path:
    return Path(tempfile.mkdtemp(dir=accounts_sandbox.root()))


def git(*args, cwd=None, env=None):
    done = subprocess.run(["git", *args], cwd=cwd, env=env or GIT_ENV, text=True,
                          capture_output=True, stdin=subprocess.DEVNULL)
    assert done.returncode == 0, done.stderr
    return done.stdout


def fake_bin(directory: Path, name: str, script: str) -> Path:
    path = directory / name
    path.write_text("#!/bin/sh\n" + script)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return directory


class PushTest(unittest.TestCase):
    def setUp(self):
        self.tmp = sandbox_dir()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.root = self.tmp / "repo"
        self.remote = self.tmp / "origin.git"
        git("init", "-q", "--bare", str(self.remote))
        git("init", "-q", "-b", "main", str(self.root))
        for key, value in (("user.name", "t"), ("user.email", "t@example.test"),
                           ("commit.gpgsign", "false"), ("tag.gpgsign", "false")):
            git("config", key, value, cwd=self.root)
        git("commit", "-q", "--allow-empty", "-m", "one", cwd=self.root)
        git("remote", "add", "origin", str(self.remote), cwd=self.root)
        git("push", "-q", "origin", "main", cwd=self.root)
        for branch in (ADOPTION, "other"):
            git("checkout", "-q", "-b", branch, "main", cwd=self.root)
            git("commit", "-q", "--allow-empty", "-m", branch, cwd=self.root)
        git("checkout", "-q", "main", cwd=self.root)
        self.main = self.sha("main")
        self.fake = sandbox_dir()
        self.addCleanup(shutil.rmtree, self.fake, ignore_errors=True)

    def sha(self, ref):
        return git("rev-parse", ref, cwd=self.root).strip()

    def refs(self):
        return git("for-each-ref", "--format=%(refname) %(objectname)",
                   cwd=self.remote).splitlines()

    def push(self, branch=ADOPTION, commit=None, **kwargs):
        commit = self.sha(ADOPTION) if commit is None else commit
        return approve.push(str(self.root), branch, commit, environ=GIT_ENV, **kwargs)

    def test_the_push_sends_exactly_the_one_branch(self):
        before = git("status", "--porcelain", cwd=self.root)
        self.push()
        self.assertEqual(sorted(self.refs()),
                         [f"refs/heads/{ADOPTION} {self.sha(ADOPTION)}",
                          f"refs/heads/main {self.main}"])
        self.assertEqual(git("status", "--porcelain", cwd=self.root), before)

    def test_a_branch_that_moved_after_apply_publishes_only_the_recorded_commit(self):
        recorded = self.sha(ADOPTION)
        git("checkout", "-q", ADOPTION, cwd=self.root)
        git("commit", "-q", "--allow-empty", "-m", "later", cwd=self.root)
        git("checkout", "-q", "main", cwd=self.root)
        self.assertNotEqual(self.sha(ADOPTION), recorded)
        self.push(commit=recorded)
        self.assertEqual(sorted(self.refs()),
                         [f"refs/heads/{ADOPTION} {recorded}", f"refs/heads/main {self.main}"])

    def test_a_commit_that_is_not_a_full_hash_is_refused_before_any_process(self):
        before = self.refs()
        for commit in (ADOPTION, "main", self.sha(ADOPTION)[:12], self.sha(ADOPTION).upper(), ""):
            with self.subTest(commit=commit), self.assertRaises(approve.PushFailed) as refused:
                self.push(commit=commit)
            self.assertEqual(refused.exception.reason, "that is not the commit apply recorded")
        self.assertEqual(self.refs(), before)

    def test_tags_never_follow_the_branch(self):
        git("config", "push.followTags", "true", cwd=self.root)
        git("tag", "-a", "v1", "-m", "v1", ADOPTION, cwd=self.root)
        self.push()
        self.assertEqual(sorted(self.refs()),
                         [f"refs/heads/{ADOPTION} {self.sha(ADOPTION)}",
                          f"refs/heads/main {self.main}"])
        self.assertEqual(git("tag", "--list", cwd=self.remote), "")

    def test_a_branch_that_is_not_an_adoption_branch_is_never_pushed(self):
        before = self.refs()
        for branch in ("other", "adopt-xyz"):
            with self.subTest(branch=branch), self.assertRaises(approve.PushFailed) as refused:
                self.push(branch)
            self.assertEqual(refused.exception.reason, "that branch is not an adoption branch")
            self.assertEqual(str(refused.exception), refused.exception.reason)
        self.assertEqual(self.refs(), before)

    def test_a_rejected_push_reads_in_fixed_words_and_logs_git_output(self):
        remote = self.tmp / "remote.git"
        git("init", "-q", "--bare", str(remote))
        fake_bin(remote / "hooks", "pre-receive", "exit 1\n")
        git("remote", "set-url", "origin", str(remote), cwd=self.root)
        branch = "adopt-" + "b" * 12
        with self.assertRaises(approve.PushFailed) as refused:
            approve.push(str(self.root), branch, self.sha(ADOPTION), environ=GIT_ENV)
        self.assertEqual(refused.exception.reason, approve.PUSH_REFUSED)
        self.assertEqual(str(refused.exception), approve.PUSH_REFUSED)
        self.assertIn("remote.git", refused.exception.detail)

    def test_the_push_runs_with_prompts_off(self):
        seen = self.fake / "seen"
        fake_bin(self.fake, "git",
                 f'echo "$GIT_TERMINAL_PROMPT" > {seen}.prompt\necho "$@" > {seen}.args\n')
        approve.push(str(self.root), ADOPTION, self.sha(ADOPTION),
                     environ={**os.environ, "PATH": f"{self.fake}:{os.environ['PATH']}"})
        self.assertEqual(Path(f"{seen}.prompt").read_text().strip(), "0")
        self.assertEqual(
            Path(f"{seen}.args").read_text().strip(),
            f"-C {self.root} push --quiet --no-follow-tags origin "
            f"{self.sha(ADOPTION)}:refs/heads/{ADOPTION}")

    def test_a_push_that_takes_too_long_reads_in_words(self):
        fake_bin(self.fake, "git", "sleep 5\n")
        with self.assertRaises(approve.PushFailed) as slow:
            approve.push(str(self.root), ADOPTION, self.sha(ADOPTION), timeout=0.5,
                         environ={"PATH": f"{self.fake}:{os.environ['PATH']}"})
        self.assertEqual(slow.exception.reason, "it took too long and was stopped")
        empty = sandbox_dir()
        self.addCleanup(shutil.rmtree, empty, ignore_errors=True)
        with self.assertRaises(approve.PushFailed) as missing:
            approve.push(str(self.root), ADOPTION, self.sha(ADOPTION), environ={"PATH": str(empty)})
        self.assertEqual(missing.exception.reason, "git could not be started")


class GhJsonTest(unittest.TestCase):
    SCRIPT = """case "$FAKE_GH" in
token) printf '{"token": "%s%s"}' "${GITHUB_TOKEN-unset}" "${GH_TOKEN-unset}" ;;
fail) echo 'gh: Validation Failed (HTTP 422)' >&2; exit 1 ;;
text) printf nope ;;
sleep) echo $$ > "$FAKE_PID"; sleep 30 ;;
esac
"""

    def setUp(self):
        self.fake = sandbox_dir()
        self.addCleanup(shutil.rmtree, self.fake, ignore_errors=True)
        fake_bin(self.fake, "gh", self.SCRIPT)
        self.pid = self.fake / "pid"

    def environ(self, mode):
        return {"PATH": f"{self.fake}:{os.environ['PATH']}", "GITHUB_TOKEN": "t",
                "GH_TOKEN": "t", "FAKE_GH": mode, "FAKE_PID": str(self.pid)}

    def test_the_child_sees_no_token(self):
        self.assertEqual(approve.gh_json(["api", "x"], environ=self.environ("token")),
                         {"token": "unsetunset"})

    def test_a_failed_call_is_a_forge_error_with_its_stderr(self):
        with self.assertRaises(ForgeError) as failed:
            approve.gh_json(["api", "x"], environ=self.environ("fail"))
        error = failed.exception
        self.assertEqual((error.code, error.detail, error.transient),
                         ("gh_failed", "gh: Validation Failed (HTTP 422)", False))
        with self.assertRaises(ForgeError) as text:
            approve.gh_json(["api", "x"], environ=self.environ("text"))
        self.assertEqual(text.exception.code, "payload_invalid")
        empty = sandbox_dir()
        self.addCleanup(shutil.rmtree, empty, ignore_errors=True)
        with self.assertRaises(ForgeError) as missing:
            approve.gh_json(["api", "x"], environ={"PATH": str(empty)})
        self.assertEqual(missing.exception.code, "gh_missing")
        with self.assertRaises(ForgeError) as slow:
            approve.gh_json(["api", "x"], timeout=0.5, environ=self.environ("sleep"))
        self.assertEqual(slow.exception.code, "gh_timeout")

    def test_a_set_cancel_ends_the_call_and_its_process(self):
        cancel = threading.Event()
        timer = threading.Timer(0.3, cancel.set)
        timer.start()
        self.addCleanup(timer.cancel)
        started = time.monotonic()
        with self.assertRaises(approve.Cancelled):
            approve.gh_json(["api", "x"], cancel, environ=self.environ("sleep"))
        self.assertLess(time.monotonic() - started, 5)
        pid = int(self.pid.read_text())
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)


class GitHubForgeTest(unittest.TestCase):
    def forge(self, *answers):
        self.calls = []
        queue = list(answers)

        def gh_json(argv, cancel=None):
            self.calls.append((argv, cancel))
            return queue.pop(0)
        return approve.GitHubForge(gh_json=gh_json)

    def test_open_posts_one_pull_request_and_builds_its_link_locally(self):
        event = threading.Event()
        forge = self.forge({"number": 7, "html_url": "https://evil.example/x"})
        self.assertEqual(
            forge.open_pull_request("o/r", ADOPTION, "main", "T", "B\n- x", cancel=event),
            {"number": 7, "url": "https://github.com/o/r/pull/7"})
        self.assertEqual(self.calls, [(["api", "-X", "POST", "repos/o/r/pulls", "-f", "title=T",
                                        "-f", f"head={ADOPTION}", "-f", "base=main",
                                        "-f", "body=B\n- x"], event)])

    def test_open_refuses_an_answer_without_a_number(self):
        for answer in ({}, {"number": True}, {"number": 0}, []):
            with self.subTest(answer=answer), self.assertRaises(ForgeError) as bad:
                self.forge(answer).open_pull_request("o/r", ADOPTION, "main", "T", "B")
            self.assertEqual(bad.exception.code, "payload_invalid")

    def test_find_returns_the_open_pull_request_of_the_head_and_base(self):
        listing = [{"number": 3, "head": {"ref": "other"}, "base": {"ref": "main"}},
                   {"number": 7, "head": {"ref": ADOPTION}, "base": {"ref": "main"}}]
        forge = self.forge(listing)
        self.assertEqual(forge.find_pull_request("o/r", ADOPTION, "main"),
                         {"number": 7, "url": "https://github.com/o/r/pull/7"})
        self.assertEqual(self.calls[0][0],
                         ["api", "-X", "GET", "repos/o/r/pulls", "-f", f"head=o:{ADOPTION}",
                          "-f", "base=main", "-f", "state=open"])
        self.assertIsNone(self.forge([]).find_pull_request("o/r", ADOPTION, "main"))
        only = [{"number": 7, "head": {"ref": ADOPTION}, "base": {"ref": "develop"}}]
        self.assertIsNone(self.forge(only).find_pull_request("o/r", ADOPTION, "main"))
        with self.assertRaises(ForgeError) as bad:
            self.forge({}).find_pull_request("o/r", ADOPTION, "main")
        self.assertEqual(bad.exception.code, "payload_invalid")

    def test_the_state_table(self):
        for mergeable in ("clean", "unstable", "has_hooks"):
            with self.subTest(mergeable=mergeable):
                forge = self.forge({"state": "open", "merged": False,
                                    "mergeable_state": mergeable})
                self.assertEqual(forge.pull_request_state("o/r", 7), "ready")
        self.assertEqual(self.calls[0][0], ["api", "repos/o/r/pulls/7"])
        for mergeable in ("blocked", "behind", "dirty", "unknown", "draft", None):
            with self.subTest(mergeable=mergeable):
                answer = {"state": "open", "merged": False}
                if mergeable:
                    answer["mergeable_state"] = mergeable
                self.assertEqual(self.forge(answer).pull_request_state("o/r", 7), "open")
        self.assertEqual(self.forge({"state": "closed", "merged": True})
                         .pull_request_state("o/r", 7), "merged")
        self.assertEqual(self.forge({"state": "closed", "merged": False})
                         .pull_request_state("o/r", 7), "closed")
        for answer in ({}, []):
            with self.subTest(answer=answer), self.assertRaises(ForgeError) as bad:
                self.forge(answer).pull_request_state("o/r", 7)
            self.assertEqual(bad.exception.code, "payload_invalid")

    def test_the_forge_offers_no_merge(self):
        self.assertEqual({name for name in dir(approve.GitHubForge) if not name.startswith("_")},
                         {"find_pull_request", "open_pull_request", "pull_request_state"})

    def test_forge_for(self):
        self.assertIsInstance(approve.forge_for("linux"), approve.GitHubForge)
        self.assertIsNone(approve.forge_for("darwin"))


if __name__ == "__main__":
    unittest.main()
