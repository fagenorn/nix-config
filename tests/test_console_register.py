"""The console's project registration (#1052): the request, the refusals, the plan runner, the rows.

Run: just agent-workflow-tests
"""

from __future__ import annotations

import os
import stat
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path

from agent_tools.console import register
from agent_tools.console.event_log import Event
from agent_tools.console.register import Adopter, RunFailed

GIT_ENV = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}


def git_init(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(path)], env=GIT_ENV, check=True,
                   stdin=subprocess.DEVNULL)
    return path


class ParseTest(unittest.TestCase):
    def test_a_path_body_is_parsed(self):
        self.assertEqual(register.parse_register_request(b'{"path": "/srv/x"}'), "/srv/x")
        self.assertEqual(register.parse_register_request(b'{"path": ""}'), "")

    def test_other_bodies_raise(self):
        for body in (b"[]", b"{}", b'{"path": 1}', b'{"path": "/a", "x": 1}',
                     b'{"path": "/a\\u0000"}', b'{"path": "/a\\n"}', b'{"path": "/a\\u007f"}',
                     b"\xff"):
            with self.subTest(body=body), self.assertRaises(ValueError):
                register.parse_register_request(body)


class RefusalTest(unittest.TestCase):
    def test_the_refusals_in_order(self):
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw).resolve()
            repo = git_init(tmp / "repo")
            sub = repo / "sub"
            sub.mkdir()
            plain = tmp / "plain"
            plain.mkdir()
            other = git_init(tmp / "other")
            entries = [{"project_id": "o/known", "root": str(other)}]
            cases = [
                ("  ", (register.EMPTY, None)),
                ("rel/x", (register.RELATIVE, None)),
                (str(tmp / "missing"),
                 (f"{tmp}/missing is not a directory on this host", None)),
                (str(plain), (register.not_toplevel(str(plain)), None)),
                (str(sub), (register.not_toplevel(str(sub)), None)),
                (str(other), (register.already_registered(str(other), "o/known"), None)),
                (str(repo), (None, repo.resolve())),
            ]
            for path, expected in cases:
                with self.subTest(path=path):
                    self.assertEqual(register.refusal(path, entries, home=str(tmp)), expected)

    def test_a_tilde_path_expands_to_home(self):
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw).resolve()
            repo = git_init(tmp / "r")
            self.assertEqual(register.refusal("~/r", [], home=str(tmp)), (None, repo.resolve()))
        self.assertEqual(register.expand("~", "/h"), "/h")
        self.assertEqual(register.expand(" ~/a ", "/h"), "/h/a")
        self.assertEqual(register.expand(" /x ", "/h"), "/x")

    def test_the_toplevel_seam_decides_without_git(self):
        with tempfile.TemporaryDirectory() as raw:
            plain = Path(raw).resolve()
            self.assertEqual(
                register.refusal(str(plain), [], home="/",
                                 toplevel=lambda p: Path(p).resolve()),
                (None, plain.resolve()))

    def test_the_name_is_the_last_segment(self):
        self.assertEqual(register.name_of("/srv/r"), "r")


def doc(**extra):
    base = {"changes": [], "link_rewrites": {"inbound": {"links": 0, "files": []},
                                              "outbound": {"links": 0, "files": []},
                                              "unrewritable": [], "already_broken": 0},
            "path_references": []}
    base.update(extra)
    return base


def move(src, dst):
    return {"op": "git-mv", "sources": [src], "targets": [dst]}


class LinesTest(unittest.TestCase):
    def test_each_change_kind_makes_its_line_in_order(self):
        document = doc(
            changes=[
                move(".claude/specs/a.md", ".agents/artifacts/specs/a.md"),
                move(".claude/plans/b.md", ".agents/artifacts/plans/b.md"),
                {"op": "write-file", "sources": [], "targets": [".agents/project.json"]},
                {"op": "regenerate-projection", "sources": [], "targets": ["AGENTS.md"]},
                {"op": "regenerate-projection", "sources": [], "targets": ["CLAUDE.md"]},
                {"op": "write-file", "sources": [], "targets": [".agents/runtime/.gitignore"]},
                {"op": "delete-file", "sources": ["x.md"], "targets": []},
            ],
            link_rewrites={"inbound": {"links": 1, "files": ["r.md"]},
                           "outbound": {"links": 1, "files": []},
                           "unrewritable": [], "already_broken": 0},
            path_references=[{"answer": "rewrite"}, {"answer": "retain"}, {"answer": None}])
        self.assertEqual(register.plan_lines(document), [
            "moves 2 agent files under .agents/", "writes the project contract",
            "generates 2 files from the contract", "writes 1 other file", "deletes 1 file",
            "rewrites 2 links", "rewrites 1 path reference"])

    def test_a_move_outside_agents_drops_the_suffix_and_zero_counts_make_no_line(self):
        self.assertEqual(register.plan_lines(doc(changes=[move("a.md", "docs/a.md")])),
                         ["moves 1 agent file"])


def plan_doc(outcome="reconcile", state="draft", open_questions=0, blockers=(),
             next_command=None, project_id="o/r", **extra):
    return doc(plan={"state": state, "outcome": outcome, "project_id": project_id,
                     "blockers": list(blockers)},
               decisions={"open": [{"id": f"q{i}"} for i in range(open_questions)]},
               handoff={"next_command": next_command}, **extra)


class SummaryTest(unittest.TestCase):
    def test_a_draft_with_questions(self):
        row = register.summary("/srv/r", plan_doc(open_questions=2))
        self.assertEqual(row["result"], "planned")
        self.assertEqual(row["headline"], "What adopting r would change: "
                         "it has agent files or a contract to bring up to date")
        self.assertEqual(row["note"], "The plan has 2 open questions.")
        self.assertEqual(row["by"], "owner")
        self.assertEqual(row["root"], "/srv/r")
        self.assertEqual(row["project_id"], "o/r")

    def test_one_open_question_is_singular(self):
        row = register.summary("/srv/r", plan_doc(open_questions=1))
        self.assertEqual(row["note"], "The plan has 1 open question.")

    def test_the_headline_names_the_outcome(self):
        boot = register.summary("/srv/r", plan_doc(outcome="bootstrap", open_questions=1))
        rec = register.summary("/srv/r", plan_doc(outcome="reconcile", open_questions=1))
        self.assertEqual(boot["headline"], "What adopting r would change: "
                         "it has no agent files or project contract yet")
        self.assertEqual(rec["headline"], "What adopting r would change: "
                         "it has agent files or a contract to bring up to date")
        self.assertEqual((boot["outcome"], rec["outcome"]), ("bootstrap", "reconcile"))

    def test_a_ready_plan_and_a_blocked_draft(self):
        ready = register.summary("/srv/r", plan_doc(state="ready"))
        self.assertEqual(ready["note"], "The plan is ready to apply.")
        blocked = register.summary("/srv/r", plan_doc(
            blockers=[{"id": "g", "message": "the tree is\n dirty"}]))
        self.assertEqual(blocked["note"], "The plan is a draft: the tree is dirty")
        bare = register.summary("/srv/r", plan_doc())
        self.assertEqual(bare["note"], "The plan is a draft.")

    def test_no_change_registered_refused_and_not_conformant(self):
        plan = plan_doc(outcome="no_change", state="ready")
        ok = register.summary("/srv/r", plan, {"registered": True, "project_id": "o/r",
                                               "result": "adopted"})
        self.assertEqual((ok["result"], ok["headline"]), ("registered", "r is registered as o/r."))
        refused = register.summary("/srv/r", plan, {"error": {
            "code": "not_integrated", "repair_id": "x",
            "violations": [{"pointer": "", "message": "no  adoption\nrecord"}]}})
        self.assertEqual((refused["result"], refused["headline"]),
                         ("not_registered", "r was not registered: not_integrated: no adoption record"))
        bad = register.summary("/srv/r", plan, {"registered": False, "result": "not_conformant",
                                                "project_id": "o/r"})
        self.assertEqual((bad["result"], bad["headline"]),
                         ("not_registered", "r was not registered: not_conformant"))

    def test_migration_and_repair_name_their_command(self):
        mig = register.summary("/srv/r", plan_doc(outcome="migration_required", state="not_applicable",
                                                  next_command="migrate bindings-deploy.retire"))
        self.assertEqual(mig["result"], "needs_migration")
        self.assertEqual(mig["headline"], "r needs migration bindings-deploy.retire first: run "
                         "adopt-project migrate --migration bindings-deploy.retire --repo-root /srv/r")
        rep = register.summary("/srv/r", plan_doc(outcome="repair_required", state="not_applicable",
                                                  next_command="repair adopt.schema.no_forward_step"))
        self.assertEqual(rep["result"], "needs_repair")
        self.assertEqual(rep["headline"], "r needs repair adopt.schema.no_forward_step first: run "
                         "resolve-project resolve --repo-root /srv/r")

    def test_a_plan_error_is_failed(self):
        row = register.summary("/srv/r", {"error": {"code": "not_a_repository", "repair_id": "x",
                                                    "violations": [{"pointer": "", "message": "m"}]}})
        self.assertEqual(row["result"], "failed")
        self.assertIsNone(row["outcome"])
        self.assertTrue(row["headline"].startswith("The adoption plan for r failed: not_a_repository: "))

    def test_failed_names_its_kind(self):
        row = register.failed("/srv/r", "timed_out")
        self.assertEqual(row, {"by": "owner", "root": "/srv/r", "project_id": None,
                               "result": "failed", "outcome": None,
                               "headline": "The adoption plan for r failed: timed_out",
                               "lines": [], "note": None})


class RowTest(unittest.TestCase):
    def test_ended_validates_and_latest_folds(self):
        p1 = register.summary("/srv/a", plan_doc(open_questions=1))
        p2 = register.summary("/srv/b", plan_doc(state="ready"))
        self.assertEqual(register.ended(p1)[0], "registration.ended")
        self.assertEqual(register.ended(p1), (register.ENDED, None, p1))
        for bad in ({**p1, "extra": 1}, {**p1, "result": "x"}, {**p1, "by": "x"},
                    {**p1, "lines": [1]}, {**p1, "lines": "a"}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                register.ended(bad)
        events = [Event(1, "t1", register.ENDED, None, p1),
                  Event(2, "t2", register.ENDED, None, {**p1, "result": "x"}),
                  Event(3, "t3", register.ENDED, None, p2),
                  Event(4, "t4", "other.kind", None, p1),
                  Event(5, "t5", register.ENDED, None, {**p1, "extra": 1})]
        self.assertEqual(register.latest(events), {**p2, "at": "t3"})
        self.assertEqual(register.latest([], {"a": 1}), {"a": 1})

    def test_view_entry_running_done_none(self):
        self.assertEqual(register.view_entry("/srv/r", None), {
            "root": "/srv/r", "name": "r", "project_id": None, "status": "running",
            "result": None, "outcome": None, "headline": "Planning the adoption of r…",
            "lines": [], "note": None, "at": None})
        latest = {**register.summary("/srv/r", plan_doc(state="ready")), "at": "t"}
        self.assertEqual(register.view_entry(None, latest), {
            "root": "/srv/r", "name": "r", "project_id": "o/r", "status": "done",
            "result": "planned", "outcome": "reconcile",
            "headline": latest["headline"], "lines": [], "note": "The plan is ready to apply.",
            "at": "t"})
        self.assertIsNone(register.view_entry(None, None))


FAKE = """#!/bin/sh
echo "$@" >> "$FAKE_ARGS"
if [ "$FAKE_SLEEP" = 1 ]; then sleep 30; fi
printf '%s' "$FAKE_OUT"
exit "$FAKE_EXIT"
"""


class AdopterTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.script = self.tmp / "fake"
        self.script.write_text(FAKE)
        self.script.chmod(self.script.stat().st_mode | stat.S_IXUSR)
        self.args = self.tmp / "args"

    def adopter(self, *, out='{"a":1}', code=0, sleep=False, timeout=30, command=None):
        environ = {"PATH": os.environ["PATH"], "FAKE_ARGS": str(self.args), "FAKE_OUT": out,
                   "FAKE_EXIT": str(code), "FAKE_SLEEP": "1" if sleep else "0"}
        return Adopter(command=command or (str(self.script),), environ=environ, timeout=timeout)

    def test_plan_and_register_argv(self):
        adopter = self.adopter()
        adopter.plan("/r")
        adopter.register("/r")
        self.assertEqual(self.args.read_text().splitlines(),
                         ["plan --repo-root /r --format json", "verify --repo-root /r --register"])

    def test_exit_0_and_2_return_the_object(self):
        for code in (0, 2):
            with self.subTest(code=code):
                self.assertEqual(self.adopter(code=code).plan("/r"), {"a": 1})

    def test_other_exit_is_failed_and_bad_json_unreadable(self):
        with self.assertRaises(RunFailed) as failed:
            self.adopter(code=1).plan("/r")
        self.assertEqual((failed.exception.kind, str(failed.exception)), ("failed", "failed"))
        for out in ("not json", "[1]"):
            with self.subTest(out=out), self.assertRaises(RunFailed) as bad:
                self.adopter(out=out).register("/r")
            self.assertEqual(bad.exception.kind, "unreadable")

    def test_a_timeout_is_timed_out(self):
        with self.assertRaises(RunFailed) as failed:
            self.adopter(sleep=True, timeout=0.5).plan("/r")
        self.assertEqual(failed.exception.kind, "timed_out")

    def test_a_missing_command_is_not_installed(self):
        with self.assertRaises(RunFailed) as failed:
            self.adopter(command=(str(self.tmp / "nope"),)).plan("/r")
        self.assertEqual(failed.exception.kind, "not_installed")

    def test_a_set_cancel_ends_the_run_as_cancelled(self):
        cancel = threading.Event()
        timer = threading.Timer(0.3, cancel.set)
        timer.start()
        self.addCleanup(timer.cancel)
        started = time.monotonic()
        with self.assertRaises(RunFailed) as failed:
            self.adopter(sleep=True).plan("/r", cancel)
        self.assertEqual(failed.exception.kind, "cancelled")
        self.assertLess(time.monotonic() - started, 10)


class PlatformTest(unittest.TestCase):
    def test_adopter_for(self):
        self.assertIsInstance(register.adopter_for("linux"), Adopter)
        self.assertIsNone(register.adopter_for("darwin"))


if __name__ == "__main__":
    unittest.main()
