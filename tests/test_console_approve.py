"""The console's adoption approval (#1054): words, rows, fold and runners.

Run: just agent-workflow-tests
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path

from agent_tools.console import approve, event_log, register
from agent_tools.console.event_log import Event
from agent_tools.project_contract import adopt_apply
from agent_tools.system.forge_api import ForgeError

from . import accounts_sandbox
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1054)

PID = "sha256:" + "b" * 64
BRANCH = "adopt-bbbbbbbbbbbb"
COMMIT = "c" * 40
KEPT = {"branch": BRANCH, "worktree": "/h/.agents/state/adopt/worktrees/bbb"}


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

    def test_waiting_lists_open_and_ready_by_plan_id(self):
        found = approve.adoptions([
            step_event(1, "t1", plan_id="p2"), step_event(2, "t2", plan_id="p1"),
            pull_event(3, "t3", "p1", 7, "ready"), step_event(4, "t4", plan_id="p3"),
            pull_event(5, "t5", "p3", 7, "merged"),
            step_event(6, "t6", step="push_failed", plan_id="p4")])
        self.assertEqual([e["plan_id"] for e in approve.waiting(found)], ["p1", "p2"])


class WordsTest(unittest.TestCase):
    def test_each_forge_failure_reads_its_reason_and_next_step(self):
        again = "then press Try again."
        cases = [
            (KeyError("x"), (register.UNEXPECTED, approve.OPEN_NOTE)),
            (ForgeError("gh_missing", "x"),
             ("gh is not installed on this host",
              "Install gh and sign it in with gh auth login, " + again)),
            (ForgeError("gh_timeout", "api"),
             ("the forge took too long to answer",
              "Press Try again; the console first looks for a pull request the forge may have "
              "opened already.")),
            (ForgeError("gh_failed", "error connecting to api.github.com", transient=True),
             ("the forge could not be reached",
              "Check this host's network connection, " + again)),
            (ForgeError("gh_failed", "gh: Bad credentials (HTTP 401)"),
             ("gh is not signed in, or may not open pull requests on this repository",
              "Sign gh in with gh auth login on this host with access to the repository, "
              + again)),
            (ForgeError("gh_failed", "gh: Forbidden (HTTP 403)"),
             ("gh is not signed in, or may not open pull requests on this repository",
              "Sign gh in with gh auth login on this host with access to the repository, "
              + again)),
            (ForgeError("gh_failed", "gh: Validation Failed (HTTP 422)"),
             ("the forge refused the pull request",
              f"Check on the forge that {BRANCH} differs from develop and has no pull request "
              "open already, " + again)),
            (ForgeError("gh_failed", "gh: Not Found (HTTP 404)"),
             ("the forge does not know the repository or the branch",
              f"Check that origin is the GitHub repository and that {BRANCH} reached it, "
              + again)),
            (ForgeError("payload_invalid", "x"),
             ("the forge answered in a way the console does not understand",
              approve.OPEN_NOTE)),
            (ForgeError("gh_failed", "gh: odd (HTTP 418)"),
             ("the forge answered in a way the console does not understand",
              approve.OPEN_NOTE)),
        ]
        for error, expected in cases:
            with self.subTest(error=repr(error)):
                got = approve.forge_failure(error, BRANCH, "develop")
                self.assertEqual(got, expected)
                for text in got:
                    for word in ("HTTP", "401", "403", "404", "422", "gh_", "payload_invalid",
                                 "KeyError"):
                        self.assertNotIn(word, text)

    def test_each_apply_error_reads_its_reason_and_next_step(self):
        def error(code="verification_failed", repair_id="", message=None):
            violations = [] if message is None else [{"pointer": "", "message": message}]
            return {"code": code, "repair_id": repair_id, "violations": violations}

        def words(err, kept=None, acknowledge=False):
            return approve.apply_failure("/srv/r", PID, err, kept, acknowledge)

        terminal = (f"Run adopt-project apply --plan-id {PID} in a terminal to see the full "
                    "reason.")
        self.assertEqual(words(error("plan_stale", "adopt.plan.inputs_changed")), (
            "the repository changed since this plan was made",
            "Register the repository again to make a new plan, then approve that one."))
        self.assertEqual(words(error(repair_id="adopt.worktree.dirty")), (
            "an uncommitted change in the repository overlaps what the plan changes",
            "Commit or set aside the uncommitted change in /srv/r, then press Approve again."))
        self.assertEqual(words(error(repair_id="adopt.worktree.retained"), KEPT), (
            "an earlier attempt of this plan is still kept",
            f"Remove the kept worktree with git worktree remove {KEPT['worktree']} and delete "
            f"the branch {BRANCH}, then press Approve again."))
        self.assertEqual(words(error(repair_id="adopt.worktree.retained")), (
            "an earlier attempt of this plan is still kept", terminal))
        self.assertEqual(words(error(repair_id="adopt.worktree.unavailable")), (
            "the adoption's branch or worktree could not be created",
            f"If the branch {BRANCH} is left from an earlier attempt, delete it with git -C "
            f"/srv/r branch -D {BRANCH}, then press Approve again."))
        self.assertEqual(words(error(repair_id="adopt.gate.no-new-broken-link"), KEPT), (
            "the no-new-broken-link check did not pass",
            f"Fix what failed in the repository (the kept worktree at {KEPT['worktree']} shows "
            f"it), remove that worktree and the branch {BRANCH}, then register the repository "
            "again."))
        self.assertEqual(words(error(repair_id="adopt.gate.no-new-broken-link")), (
            "the no-new-broken-link check did not pass", terminal))
        self.assertEqual(words(error(repair_id="adopt.manifest.missing")), (
            "the agent platform's files are not installed on this host yet",
            "Run just switch in a terminal to install them, then press Approve again."))
        self.assertEqual(words(error(message="a  pre-commit\ngate")),
                         ("a pre-commit gate", terminal))
        self.assertEqual(words(error()), ("it could not be applied", terminal))
        self.assertTrue(words(error(), acknowledge=True)[1].endswith(
            "--acknowledge-deletions in a terminal to see the full reason."))
        self.assertTrue(approve.terminal_note("p", True).endswith(
            " --acknowledge-deletions in a terminal to see the full reason."))

    def test_a_run_failure_reads_in_words(self):
        self.assertEqual(approve.run_failure(PID, "timed_out", False), (
            "it took too long and was stopped",
            f"Press Approve again. If it keeps failing, run adopt-project apply --plan-id {PID} "
            "in a terminal to see the full reason."))
        self.assertEqual(approve.run_failure(PID, "failed", False), (
            "the adoption tool stopped with an error", approve.terminal_note(PID, False)))
        self.assertEqual(approve.run_failure(PID, "Boom", False)[0], "it stopped unexpectedly")

    def test_no_reason_or_note_shows_a_code_or_kind(self):
        texts = []
        for repair in ("adopt.worktree.dirty", "adopt.worktree.retained",
                       "adopt.worktree.unavailable", "adopt.gate.g", "adopt.manifest.x", ""):
            for kept in (None, KEPT):
                texts += approve.apply_failure(
                    "/srv/r", PID, {"code": "plan_stale", "repair_id": repair,
                                    "violations": []}, kept, False)
        texts += approve.apply_failure("/srv/r", PID, {"code": "plan_stale", "repair_id": "",
                                                       "violations": []}, None, False)
        for kind in (*register.RUN_KINDS, "KeyError"):
            texts += approve.run_failure(PID, kind, False)
        for text in texts:
            for word in ("adopt.", "plan_stale", "verification_failed", "KeyError", "timed_out",
                         "not_installed", "unreadable", "Error"):
                self.assertNotIn(word, text)

    def test_reason_of_collapses_and_cuts(self):
        self.assertEqual(approve.reason_of("a\n  b"), "a b")
        cut = approve.reason_of("x" * 300)
        self.assertEqual((len(cut), cut[-1]), (200, "…"))

    def test_line_words(self):
        self.assertEqual(approve.applied_line(BRANCH, COMMIT),
                         f"Applied on the branch {BRANCH} as one commit, {'c' * 12}.")
        self.assertEqual(approve.pushed_line(BRANCH), f"Pushed {BRANCH} to origin.")
        self.assertEqual(approve.opened_line(7, "develop"),
                         "Opened pull request #7 against develop.")
        self.assertEqual(approve.kept_line(KEPT),
                         f"Apply kept its worktree at {KEPT['worktree']} and its branch "
                         f"{BRANCH}.")
        self.assertEqual(approve.running_headline("r"),
                         "Applying the adoption of r and opening its pull request…")
        self.assertEqual(approve.branch_of(PID), BRANCH)


class EntryTest(unittest.TestCase):
    def adoption(self, step, pull_state=None, **over):
        return {**step_payload(step, **over), "at": "t", "pull_state": pull_state,
                "pull_at": None}

    def test_the_entry_per_step_and_pull_state(self):
        applied = f"Applied on the branch {BRANCH} as one commit, {'c' * 12}."
        pushed = f"Pushed {BRANCH} to origin."
        opened = "Opened pull request #7 against develop."
        closed = (f"Delete the branch {BRANCH} with git -C /srv/r branch -D {BRANCH} and git -C "
                  f"/srv/r push origin --delete {BRANCH}, then press Approve to apply the plan "
                  "again.")
        merged = ("Bring /srv/r up to date with develop on origin, which now holds the "
                  "adoption, then register the repository again to add it to the projects.")
        url = "https://example.test/pull/7"
        table = [
            (self.adoption("applied"),
             ("applied", None, "The adoption of r was applied, but its branch is not pushed yet.",
              [applied], approve.APPLIED_NOTE, None)),
            (self.adoption("apply_failed", reason="it broke", note="N", kept=KEPT,
                           branch=None, commit=None),
             ("apply_failed", None, "The adoption of r was not applied: it broke.",
              [approve.kept_line(KEPT)], "N", None)),
            (self.adoption("apply_failed", reason="it broke.", note="N", branch=None,
                           commit=None),
             ("apply_failed", None, "The adoption of r was not applied: it broke.", [], "N",
              None)),
            (self.adoption("push_failed", reason="no route", note="N"),
             ("push_failed", None, f"The branch {BRANCH} was not pushed: no route.",
              [applied], "N", None)),
            (self.adoption("open_failed", reason="refused", note="N"),
             ("open_failed", None,
              f"The pull request for {BRANCH} was not opened: refused.", [applied, pushed],
              "N", None)),
            (self.adoption("opened", "open"),
             ("opened", "open", "Waiting for the pull request of r to be ready to merge.",
              [applied, pushed, opened], None, url)),
            (self.adoption("opened", "ready"),
             ("opened", "ready", "The pull request of r is ready to merge.",
              [applied, pushed, opened], None, url)),
            (self.adoption("opened", "merged"),
             ("opened", "merged", "The pull request of r was merged.",
              [applied, pushed, opened], merged, url)),
            (self.adoption("opened", "closed"),
             ("opened", "closed", "The pull request of r was closed without merging.",
              [applied, pushed, opened], closed, url)),
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
        self.assertEqual(approve.closed_note("/srv/r", BRANCH), closed)
        self.assertEqual(approve.merged_note("/srv/r", "develop"), merged)

    def test_none_and_running(self):
        self.assertIsNone(approve.entry(None, running=False, name="r"))
        self.assertEqual(approve.entry(None, running=True, name="r"), {
            "status": "running", "step": None, "state": None,
            "headline": "Applying the adoption of r and opening its pull request…",
            "lines": [], "note": None, "branch": None, "commit": None, "url": None})


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

    def test_a_refused_push_raises_its_last_stderr_line(self):
        git("remote", "set-url", "origin", str(self.tmp / "missing.git"), cwd=self.root)
        done = subprocess.run(
            ["git", "-C", str(self.root), "push", "--quiet", "origin",
             f"refs/heads/{ADOPTION}:refs/heads/{ADOPTION}"],
            env=GIT_ENV, text=True, capture_output=True, stdin=subprocess.DEVNULL)
        last = [line for line in done.stderr.splitlines() if line.strip()][-1].strip()
        with self.assertRaises(approve.PushFailed) as refused:
            self.push()
        reason = refused.exception.reason
        self.assertEqual(reason, last)
        self.assertNotIn("\n", reason)
        self.assertLessEqual(len(reason), 200)
        self.assertIn(last, refused.exception.detail)

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
