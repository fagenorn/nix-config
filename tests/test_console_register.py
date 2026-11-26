"""The console's project registration (#1052): the request, the refusals, the plan runner, the rows.

Run: just agent-workflow-tests
"""

from __future__ import annotations

import copy
import os
import re
import stat
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from agent_tools.console import approve, contract_draft, plan_questions, register
from agent_tools.console.event_log import Event
from agent_tools.console.register import Adopter, RunFailed
from agent_tools.system import siblings

from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1052)

GIT_ENV = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}


def git_init(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(path)], env=GIT_ENV, check=True,
                   stdin=subprocess.DEVNULL)
    return path


class ParseTest(unittest.TestCase):
    def test_a_path_body_is_parsed(self):
        self.assertEqual(register.parse_register_request(b'{"path": "/srv/x"}'), ("/srv/x", False))
        self.assertEqual(register.parse_register_request(b'{"path": ""}'), ("", False))
        self.assertEqual(
            register.parse_register_request(b'{"path": "/srv/x", "unless_open": true}'),
            ("/srv/x", True))

    def test_other_bodies_raise(self):
        for body in (b"[]", b"{}", b'{"path": 1}', b'{"path": "/a", "x": 1}',
                     b'{"path": "/a\\u0000"}', b'{"path": "/a\\n"}', b'{"path": "/a\\u007f"}',
                     b'{"path": "/a", "unless_open": false}', b'{"path": "/a", "unless_open": 1}',
                     b'{"path": "/a", "unless_open": "true"}', b'{"unless_open": true}',
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

    def test_a_path_the_host_cannot_stat_is_not_a_directory(self):
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw).resolve()
            locked = tmp / "locked"
            (locked / "inner").mkdir(parents=True)
            too_long = str(tmp / ("a" * 300))
            cases = [too_long, str(locked / "inner")]
            locked.chmod(0)
            try:
                for path in cases:
                    with self.subTest(path=path[-20:]):
                        self.assertEqual(register.refusal(path, [], home=str(tmp)),
                                         (register.not_directory(path), None))
            finally:
                locked.chmod(0o700)

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
            "generates 2 files from the contract", "writes .agents/runtime/.gitignore",
            "deletes x.md",
            "rewrites 2 links", "rewrites 1 path reference"])

    def test_the_files_written_or_deleted_are_named_up_to_three_then_a_count(self):
        def writes(*paths):
            return [{"op": "write-file", "sources": [], "targets": [path]} for path in paths]

        def deletes(*paths):
            return [{"op": "delete-file", "sources": [path], "targets": []} for path in paths]

        contract = {"op": "write-file", "sources": [], "targets": [".agents/project.json"]}
        cases = [
            (writes("a.md"), ["writes a.md"]),
            (writes("a.md", "b.md"), ["writes a.md and b.md"]),
            (writes("AGENTS.md", "CLAUDE.md", ".agents/instructions/bootstrap.md"),
             ["writes AGENTS.md, CLAUDE.md and .agents/instructions/bootstrap.md"]),
            (writes("a", "b", "c", "d"), ["writes a, b, c and 1 more"]),
            (writes("a", "b", "c", "d", "e", "f"), ["writes a, b, c and 3 more"]),
            ([contract, *writes("a", "b", "c", "d")],
             ["writes the project contract", "writes a, b, c and 1 more"]),
            (deletes("x.md"), ["deletes x.md"]),
            (deletes("a", "b", "c", "d"), ["deletes a, b, c and 1 more"]),
        ]
        for changes, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(register.plan_lines(doc(changes=changes)), expected)

    def test_the_adoptions_own_records_are_never_named_and_close_the_writes_line(self):
        digest = "50051d36e5e98d2b6d8b07c7417d1b1f666906b20ccc3dd6a96569665f4f0ade"
        records = [
            {"op": "write-file", "sources": [],
             "targets": [f".agents/knowledge/archive/path-migrations/{digest}.json"]},
        ]

        def writes(*paths):
            return [{"op": "write-file", "sources": [], "targets": [path]} for path in paths]

        end = ", and records the adoption"
        handoff = {"migration_map": records[0]["targets"][0]}
        cases = [
            (writes(".agents/runtime/.gitignore", ".gitignore") + records,
             [f"writes .agents/runtime/.gitignore and .gitignore{end}"]),
            (records, ["records the adoption"]),
            (writes("a", "b", "c", "d", "e") + records, [f"writes a, b, c and 2 more{end}"]),
            (writes("a", "b", "c") + records[:1], [f"writes a, b and c{end}"]),
            (writes("a") + records, [f"writes a{end}"]),
            (writes("a", "b"), ["writes a and b"]),
        ]
        for changes, expected in cases:
            with self.subTest(expected=expected):
                lines = register.plan_lines(doc(changes=changes, handoff=handoff))
                self.assertEqual(lines, expected)
                self.assertNotIn(digest, " ".join(lines))

    def test_an_ordinary_file_beside_the_adoptions_records_stays_named(self):
        digest = "50051d36e5e98d2b6d8b07c7417d1b1f666906b20ccc3dd6a96569665f4f0ade"
        handoff = {"migration_map": f".agents/knowledge/archive/path-migrations/{digest}.json"}
        paths = [".agents/artifacts/evidence/checklist.md",
                 ".agents/knowledge/archive/path-migrations/notes.md", handoff["migration_map"]]
        changes = [{"op": "write-file", "sources": [], "targets": [path]} for path in paths]
        self.assertEqual(
            register.plan_lines(doc(changes=changes, handoff=handoff)),
            [f"writes {paths[0]} and {paths[1]}, and records the adoption"])

    def test_a_move_outside_agents_drops_the_suffix_and_zero_counts_make_no_line(self):
        self.assertEqual(register.plan_lines(doc(changes=[move("a.md", "docs/a.md")])),
                         ["moves 1 agent file"])


PLAN_ID = "sha256:" + "a" * 64


def plan_doc(outcome="reconcile", state="draft", open_questions=0, blockers=(),
             next_command=None, project_id="o/r", plan_id=PLAN_ID, answered=(),
             decisions_open=None, **extra):
    header = {"state": state, "outcome": outcome, "project_id": project_id,
              "blockers": list(blockers)}
    if plan_id is not None:
        header["plan_id"] = plan_id
    opened = (list(decisions_open) if decisions_open is not None
              else [{"id": f"q{i}"} for i in range(open_questions)])
    return doc(plan=header, decisions={"open": opened, "answered": list(answered)},
               handoff={"next_command": next_command}, **extra)


def draft_fields() -> list[dict]:
    """The draft of a checkout whose remote names it and whose files give a test command but no lint command."""
    return contract_draft.draft("/x/sample-app", {
        "remotes": [("origin", "git@github.com:sample-owner/sample-app.git")],
        "default_branch": "trunk", "branches": ["trunk"], "files": ["justfile"],
        "texts": {"justfile": "test:\n\techo t\n"}})


class SummaryTest(unittest.TestCase):
    def test_a_drafted_plan_row_keeps_its_draft(self):
        fields = draft_fields()
        plan = plan_doc(outcome="bootstrap", open_questions=0, changes=[
            {"op": "write-file", "sources": [], "targets": [".agents/project.json"]}])
        row = register.summary("/srv/r", plan, draft=fields)
        self.assertEqual(row["draft"], fields)
        self.assertTrue(row["lines"][0].startswith("writes the project contract"))
        self.assertIsNone(register.summary("/srv/r", plan)["draft"])

    def test_a_draft_with_questions(self):
        row = register.summary("/srv/r", plan_doc(open_questions=2))
        self.assertEqual(row["result"], "planned")
        self.assertEqual(row["headline"], "What adopting r would change: "
                         "it has agent files or a contract to bring up to date")
        self.assertEqual(row["note"], "The plan has 2 open questions.")
        self.assertEqual(row["by"], "owner")
        self.assertEqual(row["root"], "/srv/r")
        self.assertEqual(row["project_id"], "o/r")

    def test_a_planned_row_carries_the_plan_id_state_questions_and_answers(self):
        answered = [{"id": "candidate-class", "subject": ".claude/odd.md",
                     "value": "archive-history"}]
        doc_ = plan_doc(open_questions=0, answered=answered, decisions_open=[
            {"id": "candidate-class", "subject": ".claude/x.md", "value": "archive-history"}])
        row = register.summary("/srv/r", doc_)
        self.assertEqual(row["plan_id"], "sha256:" + "a" * 64)
        self.assertEqual(row["state"], "draft")
        self.assertEqual(row["questions"], plan_questions.questions(doc_))
        self.assertEqual(len(row["questions"]), 1)
        self.assertEqual(row["answered"], answered)
        self.assertEqual(set(row), register.MEMBERS | register.EXTRA | {"draft"})
        self.assertIsNone(row["draft"])

    def test_other_rows_carry_the_defaults(self):
        rows = [register.summary("/srv/r", plan_doc(outcome="no_change", state="ready"),
                                 {"registered": True, "project_id": "o/r"}),
                register.summary("/srv/r", plan_doc(outcome="migration_required",
                                                    state="not_applicable",
                                                    next_command="migrate m")),
                register.failed("/srv/r", "timed_out")]
        for row in rows:
            with self.subTest(result=row["result"]):
                self.assertEqual((row["plan_id"], row["state"], row["questions"], row["answered"],
                                  row["draft"]), (None, None, [], [], None))

    def test_an_adopted_plan_with_no_report_waits_for_the_register_card(self):
        nc = {"plan": {"state": "ready", "outcome": "no_change", "project_id": "o/r",
                       "blockers": [], "plan_id": "sha256:" + "c" * 64},
              "decisions": {"open": [], "answered": []},
              "handoff": {"next_command": "adopt-project verify --register --repo-root /srv/r"}}
        for document in (register.summary("/srv/r", nc),
                         register.summary("/srv/r", {**nc, "handoff": {"next_command": None}})):
            self.assertEqual((document["result"], document["outcome"], document["lines"],
                              document["plan_id"]),
                             ("not_registered", "no_change", [], None))
            self.assertEqual(document["headline"], "r is already adopted and is not registered yet.")
            self.assertEqual(document["note"], "Choose Register it to register it.")
            at = {**document, "at": "2026-11-15T08:00:00+00:00"}
            self.assertTrue(register.waiting(at))
            self.assertFalse(register.waiting(register.dismissed(at)))
            self.assertEqual(register.dismissed(at)["note"],
                             "Not registered. Press Register again to register it.")
        refused = register.summary("/srv/r", nc, {"error": {"repair_id": "adopt.registration.no_remote",
                                                            "message": "no origin"}})
        self.assertFalse(register.waiting({**refused, "at": "2026-11-15T08:00:00+00:00"}))
        self.assertFalse(register.waiting(None))

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
        self.assertEqual(ready["note"], "The plan is ready.")
        self.assertEqual(register.summary("/srv/r", plan_doc(state="ready", plan_id=None))["note"],
                         "The plan is ready.")
        for text in (ready["headline"], ready["note"], *ready["lines"]):
            self.assertNotIn("sha256", text)
            self.assertNotIn("adopt-project", text)
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
                         ("not_registered", "r was not registered: no adoption record."))
        bad = register.summary("/srv/r", plan, {"registered": False, "result": "not_conformant",
                                                "project_id": "o/r"})
        self.assertEqual((bad["result"], bad["headline"]),
                         ("not_registered", "r was not registered: not_conformant."))

    def test_a_plan_error_is_failed(self):
        row = register.summary("/srv/r", {"error": {"code": "not_a_repository", "repair_id": "x",
                                                    "violations": [{"pointer": "", "message": "m"}]}})
        self.assertEqual(row["result"], "failed")
        self.assertIsNone(row["outcome"])
        self.assertEqual(row["headline"], "The adoption plan for r failed: m.")

    def test_a_plan_error_headline_never_shows_the_code(self):
        row = register.summary("/srv/r", {"error": {
            "code": "adopt_failure", "repair_id": "x",
            "violations": [{"pointer": "", "message": "the installed platform\n manifest was not found"}]}})
        self.assertEqual(row["headline"], "The adoption plan for r failed: "
                         "the installed platform manifest was not found.")
        for error in ({"code": "adopt_failure", "repair_id": "x", "violations": []},
                      {"code": "adopt_failure"},
                      {"code": "adopt_failure", "violations": [{"pointer": "", "message": ""}]}):
            with self.subTest(error=error):
                row = register.summary("/srv/r", {"error": error})
                self.assertEqual(row["headline"], "The adoption plan for r could not be made.")

    def test_a_refused_registration_shows_the_message_without_the_code(self):
        plan = plan_doc(outcome="no_change", state="ready")
        report = {"error": {"code": "not_integrated", "repair_id": "x", "violations": []}}
        row = register.summary("/srv/r", plan, report)
        self.assertEqual((row["result"], row["headline"]), ("not_registered", "r was not registered."))

    def test_a_failed_run_says_what_happened_in_words(self):
        words = {
            "timed_out": "it took too long and was stopped",
            "not_installed": "the adoption tool could not be started",
            "unavailable": "the adoption tool could not be started",
            "cancelled": "it was cancelled",
            "failed": "the adoption tool stopped with an error",
            "unreadable": "the adoption tool gave an answer that could not be read",
            "ValueError": "it stopped unexpectedly",
        }
        for kind in register.RUN_KINDS:
            self.assertIn(kind, words)
        for kind, text in words.items():
            with self.subTest(kind=kind):
                row = register.failed("/srv/r", kind)
                self.assertEqual(row, {"by": "owner", "root": "/srv/r", "project_id": None,
                                       "result": "failed", "outcome": None,
                                       "headline": f"The adoption plan for r failed: {text}.",
                                       "lines": [], "note": register.run_next_step("/srv/r", kind),
                                       "plan_id": None, "state": None, "questions": [],
                                       "answered": [], "draft": None})

    def test_a_headline_that_already_ends_in_a_full_stop_gets_no_second(self):
        row = register.summary("/srv/r", {"error": {"code": "adopt_failure", "repair_id": "x",
                                                    "violations": [{"pointer": "", "message": "m."}]}})
        self.assertEqual(row["headline"], "The adoption plan for r failed: m.")


def adopt_error(repair_id, message="m"):
    return {"error": {"code": "adopt_failure", "repair_id": repair_id,
                      "violations": [{"pointer": "", "message": message}]}}


NO_CHANGE = {"plan": {"outcome": "no_change", "state": "ready"}}
CODE_WORDS = ("adopt.", "platform.", "adopt_failure", "not_integrated", "timed_out", "not_installed")


class NextStepTest(unittest.TestCase):
    def test_a_failed_discard_before_a_plan_says_try_again(self):
        error = adopt_error("adopt.discard.failed",
                            "the retained worktree of this plan could not be removed")
        self.assertEqual(register.summary("/x/r", error)["note"], register.DISCARD_STEP)
        self.assertEqual(register.DISCARD_STEP,
                         "Choose Try again to remove the copy the last attempt left on this "
                         "computer and plan again.")

    def test_a_missing_manifest_says_the_cause_once_and_the_step_once(self):
        error = {"code": "x", "repair_id": "adopt.manifest.missing", "violations": [
            {"pointer": "", "message": "the installed platform manifest was not found"}]}
        row = register.summary("/srv/fail-app", {"error": error})
        self.assertEqual(row["headline"], "The adoption plan for fail-app could not start: "
                         "the agent platform's files are not installed on this host.")
        self.assertEqual(row["note"], register.MANIFEST_STEP)
        self.assertEqual((row["headline"] + " " + row["note"]).count("not installed"), 1)
        reg = register.summary("/srv/fail-app", NO_CHANGE, {"error": error})
        self.assertEqual(reg["headline"], "fail-app was not registered: "
                         "the agent platform's files are not installed on this host.")
        self.assertEqual(reg["note"], register.MANIFEST_STEP)
        for repair_id in ("adopt.manifest.invalid", "adopt.manifest.forward_step_missing",
                          "adopt.manifest.forward_step_ambiguous"):
            with self.subTest(repair_id=repair_id):
                other = {**error, "repair_id": repair_id}
                self.assertEqual(register.summary("/srv/r", {"error": other})["note"],
                                 register.MANIFEST_STEP)

    def test_a_failed_plan_for_a_missing_platform_names_just_switch(self):
        plan = {"error": {"code": "x", "repair_id": "adopt.manifest.missing", "violations": [
            {"pointer": "", "message": register.MANIFEST_ABSENT}]}}
        row = register.summary("/x/r", plan)
        self.assertEqual(row["note"], "Run just switch on this computer to install them, then "
                                      "choose Try again.")

    def test_any_other_manifest_failure_keeps_its_own_reason(self):
        cases = (
            ("adopt.manifest.invalid", "the installed platform manifest is not valid JSON"),
            ("adopt.manifest.invalid", "the installed platform manifest could not be read"),
            ("adopt.manifest.invalid", "the manifest's platform version is not strict SemVer"),
            ("adopt.manifest.forward_step_missing",
             "no migration steps forward from the project's declared schema"),
            ("adopt.manifest.forward_step_ambiguous",
             "more than one migration steps forward from the project's declared schema"),
        )
        for repair_id, message in cases:
            with self.subTest(repair_id=repair_id, message=message):
                row = register.summary("/srv/r", adopt_error(repair_id, message))
                self.assertEqual(row["headline"], f"The adoption plan for r failed: {message}.")
                self.assertEqual(row["note"], register.unknown_step("r", "plan"))
                reg = register.summary("/srv/r", NO_CHANGE, adopt_error(repair_id, message))
                self.assertEqual(reg["headline"], f"r was not registered: {message}.")
                self.assertEqual(reg["note"], register.unknown_step("r", "register"))
                self.assertNotIn("Switch this computer", row["note"] + reg["note"])

    def test_each_refused_registration_has_its_own_next_step(self):
        again = "then choose Try again."
        cases = {
            "adopt.registration.no_remote": f"Add the repository's origin remote, {again}",
            "adopt.registration.remote_default_unknown":
                "The repository's origin remote needs a published default branch. "
                f"Push one to it, {again}",
            "adopt.git.remote_unreachable":
                f"Check that the repository's remote can be reached from this host, {again}",
            "adopt.git.fetch_failed":
                f"Check that the repository's remote can be reached from this host, {again}",
            "adopt.registration.not_integrated":
                "The adoption is not on the remote's main branch yet. Merge it, " + again,
        }
        for repair_id, step in cases.items():
            with self.subTest(repair_id=repair_id):
                row = register.summary("/srv/r", NO_CHANGE, adopt_error(repair_id, "why"))
                self.assertEqual((row["result"], row["headline"], row["note"]),
                                 ("not_registered", "r was not registered: why.", step))

    def test_no_failure_text_names_a_command_hash_or_path(self):
        forbidden = re.compile(r"--plan-id|sha256:|[0-9a-f]{12,}|(?:^|[\s(\"'])/\S")
        banned = ("adopt-project", "resolve-project", "in a terminal:")
        root = "/srv/a b/app"
        rows = [register.failed(root, kind, verb)
                for kind in (*register.RUN_KINDS, "ValueError") for verb in ("plan", "register")]
        errors = [adopt_error(repair_id) for repair_id in (
            "adopt.manifest.missing", "adopt.something.else", *register.NEXT_STEPS)]
        errors += [{"error": {"code": "adopt_failure"}}, adopt_error("x", "")]
        manifest = adopt_error("adopt.manifest.missing", register.MANIFEST_ABSENT)
        errors.append(manifest)
        raw = ("/srv/a b/app is not a git repository", "plan sha256:" + "b" * 64 + " is stale",
               "branch adopt-bbbbbbbbbbbb exists")
        for message in raw:
            rows.append(register.summary(root, adopt_error("adopt.something.else", message)))
            rows.append(register.summary(root, NO_CHANGE,
                                         adopt_error("adopt.something.else", message)))
            self.assertEqual(rows[-2]["headline"], "The adoption plan for app could not be made.")
            self.assertEqual(rows[-1]["headline"], "app was not registered.")
        for error in errors:
            rows.append(register.summary(root, error))
            rows.append(register.summary(root, NO_CHANGE, error))
        for report in ({"registered": False, "result": "x"}, {"result": "refused /srv/a b/app"}):
            rows.append(register.summary(root, NO_CHANGE, report))
        self.assertEqual(rows[-1]["headline"], "app was not registered.")
        self.assertEqual(rows[-1]["note"], register.unknown_step("app", "register"))
        rows.append(register.summary(root, plan_doc(
            outcome="migration_required", state="not_applicable",
            next_command="migrate bindings-deploy.retire")))
        rows.append(register.summary(root, plan_doc(
            outcome="repair_required", state="not_applicable",
            next_command="repair adopt.schema.no_forward_step")))
        self.assertEqual((rows[-2]["headline"], rows[-2]["note"]), (
            "app needs a migration before it can be adopted.",
            "Ask an agent to migrate it in a terminal, then choose Try again."))
        self.assertEqual((rows[-1]["headline"], rows[-1]["note"]), (
            "app needs a repair before it can be adopted.",
            "Ask an agent to repair its project contract in a terminal, then choose Try again."))
        rows.append(register.summary(root, {"plan": {"outcome": "odd"}}))
        for row in rows:
            with self.subTest(headline=row["headline"], note=row["note"]):
                for text in (row["headline"], row["note"]):
                    self.assertIsNone(forbidden.search(text), text)
                    for word in banned:
                        self.assertNotIn(word, text)
                sentences = lambda text: set(text.removesuffix(".").split(". "))  # noqa: E731
                self.assertFalse(sentences(row["headline"]) & sentences(row["note"]))
        self.assertEqual(register.failed("/srv/r", "timed_out")["note"],
                         "Choose Try again. If it keeps failing, ask an agent to plan the "
                         "adoption of r in a terminal, which shows the full reason.")
        self.assertEqual(register.failed("/srv/r", "failed", "register")["note"],
                         "Choose Try again. If it keeps failing, ask an agent to register r in a "
                         "terminal, which shows the full reason.")

    def test_no_headline_or_next_step_shows_an_internal_code(self):
        rows = [register.failed("/srv/r", kind) for kind in (*register.RUN_KINDS, "ValueError")]
        for repair_id in ("adopt.manifest.invalid", "adopt.registration.no_remote",
                          "adopt.git.fetch_failed", "adopt.registration.not_integrated", "adopt.x"):
            rows.append(register.summary("/srv/r", adopt_error(repair_id)))
            rows.append(register.summary("/srv/r", NO_CHANGE, adopt_error(repair_id)))
        for row in rows:
            for text in (row["headline"], row["note"]):
                for word in CODE_WORDS:
                    self.assertNotIn(word, text)


class FailureCardTest(unittest.TestCase):
    def test_a_failed_row_is_one_try_again_card(self):
        root = "/srv/fail-app"
        manifest = {"error": {"code": "x", "repair_id": "adopt.manifest.missing", "violations": [
            {"pointer": "", "message": register.MANIFEST_ABSENT}]}}
        latest = {**register.summary(root, manifest), "at": "t1"}
        self.assertEqual(register.failure_items(latest, running=False), [{
            "type": "inbox_item", "reason": "register_failed",
            "key": "register-failed//srv/fail-app/t1", "project_id": None, "root": root,
            "name": "fail-app", "title": "Register fail-app", "plan_id": None, "id": None,
            "subject": None, "headline": latest["headline"], "why": latest["note"], "lines": [],
            "refusal": None, "more_questions": 0, "text": False,
            "questions": [{"question": latest["headline"], "options": ["Try again", "Not now"],
                           "chosen": None, "recommended": None, "recommended_index": None}],
            "values": ["try_again", "not_now"], "items": [], "answers": [], "answered": False,
            "waiting_since": "t1"}])
        waiting = {**register.summary("/srv/r", plan_doc(outcome="no_change", state="ready")),
                   "at": "t2"}
        self.assertTrue(register.waiting(waiting))
        for latest_row, running in ((latest, True), (None, False),
                                    (register.dismissed(latest), False), (waiting, False)):
            with self.subTest(latest=latest_row, running=running):
                self.assertEqual(register.failure_items(latest_row, running=running), [])

    def test_the_rows_that_fail(self):
        for result in ("failed", "not_registered", "needs_migration", "needs_repair"):
            self.assertTrue(register.failing({"result": result, "note": "n"}))
        for result in ("planned", "registered", "drafting"):
            self.assertFalse(register.failing({"result": result, "note": "n"}))
        self.assertFalse(register.failing(None))

    def test_parse_confirm_request_takes_the_three_choices(self):
        for choice in ("try_again", "register", "not_now"):
            body = ('{"root": "/r", "choice": "%s"}' % choice).encode()
            self.assertEqual(register.parse_confirm_request(body), ("/r", choice))
        for body in (b'{"root": "/r", "choice": "retry"}', b'{"root": "/r"}',
                     b'{"root": "/r", "choice": "try_again", "x": 1}',
                     b'{"root": "/r\\u0007", "choice": "try_again"}'):
            with self.subTest(body=body), self.assertRaises(ValueError):
                register.parse_confirm_request(body)


class LegacyNoteTest(unittest.TestCase):
    def test_latest_reads_an_old_manifest_note_in_the_new_words(self):
        old = ("Switch this computer to its current configuration to install them, then choose "
               "Try again.")
        self.assertEqual(register.LEGACY_NOTES, {old: register.MANIFEST_STEP})
        row = register.summary("/srv/a", {"error": {
            "code": "x", "repair_id": "adopt.manifest.missing", "violations": [
                {"pointer": "", "message": register.MANIFEST_ABSENT}]}})
        found = register.latest([Event(1, "t1", register.ENDED, None, {**row, "note": old})])
        self.assertEqual(found["note"], register.MANIFEST_STEP)


class CancelFoldTest(unittest.TestCase):
    def ended_event(self, seq, root="/x/r", plan_id="P"):
        row = {**register.summary(root, plan_doc(state="ready")), "plan_id": plan_id}
        return Event(seq, f"t{seq}", register.ENDED, None, row)

    def cancel_event(self, seq, root="/x/r", plan_id="P"):
        row = register.cancelled_row(root, plan_id)
        return Event(seq, f"t{seq}", row[0], None, row[2])

    def test_a_cancel_row_folds_the_registration_away(self):
        self.assertEqual(register.cancelled_row("/x/r", "P"),
                         ("registration.cancelled", None,
                          {"by": "owner", "root": "/x/r", "plan_id": "P"}))
        self.assertEqual(register.CANCELLED, "registration.cancelled")
        ended = self.ended_event(1)
        self.assertIsNotNone(register.latest([ended]))
        self.assertIsNone(register.latest([ended, self.cancel_event(2)]))
        again = self.ended_event(3)
        self.assertEqual(register.latest([ended, self.cancel_event(2), again])["at"], "t3")
        for other in (self.cancel_event(2, root="/x/other"), self.cancel_event(2, plan_id="Q"),
                      Event(2, "t2", register.CANCELLED, None, {"root": "/x/r", "plan_id": "P"})):
            with self.subTest(other=other.payload):
                self.assertEqual(register.latest([ended, other])["at"], "t1")
        state = register.latest([ended])
        self.assertIsNone(register.latest([self.cancel_event(2)], state))
        self.assertIsNotNone(state)

    def test_a_restoring_cancel_folds_back_to_the_registration_before(self):
        a = Event(1, "t1", register.ENDED, None,
                  register.dismissed(register.failed("/x/a", "failed")))
        ended = self.ended_event(2)
        row = register.cancelled_row("/x/r", "P", restore=True)
        restoring = Event(3, "t3", row[0], None, row[2])
        self.assertEqual(row[2], {"by": "owner", "root": "/x/r", "plan_id": "P", "restore": True})
        found = register.fold([a, ended, restoring])
        self.assertEqual(found.latest["root"], "/x/a")
        self.assertEqual(found.latest["at"], "t1")
        self.assertEqual(found.before, ())
        self.assertIsNone(register.fold([a, ended, self.cancel_event(3)]).latest)

    def test_a_restoring_cancel_never_returns_an_older_entry_of_a_recurring_root(self):
        a1 = register.dismissed(register.failed("/x/a", "failed"))
        b = register.failed("/x/b", "failed")
        a2 = register.failed("/x/a", "failed")

        def restoring(seq, root):
            row = register.cancelled_row(root, None, restore=True)
            return Event(seq, f"t{seq}", row[0], None, row[2])

        events = [Event(1, "t1", register.ENDED, None, a1), Event(2, "t2", register.ENDED, None, b),
                  Event(3, "t3", register.ENDED, None, a2), restoring(4, "/x/a"),
                  restoring(5, "/x/b")]
        self.assertEqual(register.fold(events[:4]).latest["root"], "/x/b")
        found = register.fold(events)
        self.assertIsNone(found.latest)
        self.assertEqual(found.before, ())

    def test_cancellable_before_apply_only(self):
        planned = {"result": "planned"}
        self.assertFalse(register.cancellable(None, None))
        self.assertTrue(register.cancellable(planned, None))
        self.assertTrue(register.cancellable({"result": "failed"}, None))
        self.assertFalse(register.cancellable({"result": "registered"}, None))
        self.assertTrue(register.cancellable(planned, {"step": "apply_failed"}))
        for step in ("applied", "push_failed", "open_failed", "opened"):
            with self.subTest(step=step):
                self.assertFalse(register.cancellable(planned, {"step": step}))

    def test_parse_cancel_request(self):
        self.assertEqual(register.parse_cancel_request(b'{"root": "/x/r"}'), ("/x/r", False))
        self.assertEqual(register.parse_cancel_request(b'{"root": "/x/r", "restore": true}'),
                         ("/x/r", True))
        for body in (b'{"root": "/x/r", "restore": false}', b'{"root": "/x/r", "restore": 1}',
                     b'{"root": "/x/r", "choice": "register"}', b'{}', b'{"root": ""}',
                     b'{"root": 3}', b'{"root": "/x\nr"}', b'{"root": "/x\u007fr"}',
                     b'not json', b'\xff', b'[]'):
            with self.subTest(body=body), self.assertRaises(ValueError):
                register.parse_cancel_request(body)
        self.assertEqual(register.CANCEL_REFUSED,
                         "only a registration that was not applied yet can be cancelled")
        self.assertEqual(
            register.CANCEL_DISCARD_FAILED,
            "The copy that the failed attempt left on this computer could not be removed, so the "
            "registration was not cancelled. Choose Cancel registration to try again.")


class OpenShownTest(unittest.TestCase):
    def test_only_none_and_a_dismissed_entry_are_not_open(self):
        self.assertEqual(register.OPEN_SHOWN, "another registration is open on the page")
        self.assertIs(register.open_shown(None), False)
        self.assertIs(register.open_shown(
            {"root": "/x/r", "status": "done", "note": register.LATER_NOTE}), False)
        for entry in ({"root": "/x/r", "status": "done", "note": None},
                      {"root": "/x/r", "status": "running", "note": None},
                      {"root": "/x/r", "status": "done", "note": "The plan is a draft."},
                      "not a dict"):
            with self.subTest(entry=entry):
                self.assertIs(register.open_shown(entry), True)


class UnregisteredFoldTest(unittest.TestCase):
    """A registration whose project is unregistered gives way to the one shown before it (#1334)."""

    y = register.dismissed(register.failed("/x/y", "failed"))
    r_wait = {**register.failed("/x/r", "failed"), "project_id": "c/r", "result": "not_registered",
              "outcome": "no_change", "note": register.CONFIRM_NOTE}
    r_done = {**r_wait, "result": "registered", "note": None}

    @staticmethod
    def ended(seq, row):
        return Event(seq, f"t{seq}", register.ENDED, None, row)

    @staticmethod
    def reg(seq, project, root):
        return Event(seq, f"t{seq}", "project.registered", project, {"root": root})

    @staticmethod
    def gone(seq, payload, project="c/r"):
        return Event(seq, f"t{seq}", "project.unregistered", project, payload)

    def a_events(self):
        return [self.ended(1, self.y), self.ended(2, self.r_wait), self.reg(3, "c/r", "/x/r"),
                self.ended(4, self.r_done), self.gone(5, {"root": "/x/r"})]

    def test_an_unregistered_root_gives_way_to_the_registration_shown_before_it(self):
        events = self.a_events()
        folded = register.fold(events)
        self.assertEqual(folded.latest["root"], "/x/y")
        self.assertEqual(folded.latest["at"], "t1")
        self.assertEqual(folded.latest["note"], register.LATER_NOTE)
        self.assertEqual(folded.before, ())
        self.assertEqual(dict(folded.roots), {})
        self.assertEqual(register.latest(events)["at"], "t1")
        run = register.fold(events[:4])
        self.assertEqual(run.latest["at"], "t4")
        self.assertEqual([e["root"] for e in run.before], ["/x/y"])

    def test_with_nothing_before_it_the_registration_folds_to_none(self):
        folded = register.fold([self.ended(1, self.r_wait), self.ended(2, self.r_done),
                                self.gone(3, {"root": "/x/r"})])
        self.assertIsNone(folded.latest)
        self.assertEqual(folded.before, ())

    def test_a_rootless_row_takes_its_root_from_the_registered_row(self):
        folded = register.fold(self.a_events()[:4] + [self.gone(5, {})])
        self.assertEqual(folded.latest["root"], "/x/y")

    def test_a_rootless_row_of_an_unknown_or_other_root_changes_nothing(self):
        card2 = {**self.r_wait, "root": "/x/r2"}
        cases = {
            "other root": ([self.ended(1, self.y), self.reg(2, "c/r", "/x/r1"),
                            self.ended(3, card2), self.gone(4, {})], "t3"),
            "unknown": ([self.ended(1, self.y), self.ended(2, card2), self.gone(3, {})], "t2"),
        }
        for name, (events, at) in cases.items():
            with self.subTest(name=name):
                folded = register.fold(events)
                self.assertEqual(folded.latest["root"], "/x/r2")
                self.assertEqual(folded.latest["at"], at)

    def test_an_unregistered_row_of_another_registration_changes_nothing(self):
        for other in (self.gone(4, {"root": "/x/other"}, "c/other"), self.gone(4, {}, "c/other"),
                      self.gone(4, {"root": "/x/other"}, "c/r")):
            with self.subTest(other=other):
                folded = register.fold([self.ended(1, self.y), self.ended(2, self.r_wait),
                                        self.ended(3, self.r_done), other])
                self.assertEqual(folded.latest["root"], "/x/r")
                self.assertEqual(folded.latest["at"], "t3")

    def test_a_root_another_project_still_holds_keeps_its_registration(self):
        events = self.a_events()[:3] + [self.reg(4, "c/r2", "/x/r"), self.ended(5, self.r_done),
                                        self.gone(6, {"root": "/x/r"}),
                                        self.gone(7, {"root": "/x/r"}, "c/r2")]
        held = register.fold(events[:6])
        self.assertEqual((held.latest["root"], held.latest["at"]), ("/x/r", "t5"))
        self.assertEqual([e["root"] for e in held.before], ["/x/y"])
        self.assertEqual(dict(held.roots), {"c/r2": "/x/r"})
        left = register.fold(events)
        self.assertEqual((left.latest["root"], left.latest["at"]), ("/x/y", "t1"))
        self.assertEqual(dict(left.roots), {})

    def test_a_removed_root_never_returns_from_the_chain(self):
        a1 = register.dismissed(register.failed("/x/a", "failed"))
        b = register.failed("/x/b", "failed")
        a2 = register.failed("/x/a", "failed")
        events = [self.ended(1, a1), self.ended(2, b), self.ended(3, a2),
                  self.gone(4, {"root": "/x/b"}, "c/b"), self.gone(5, {"root": "/x/a"}, "c/a")]
        three = register.fold(events[:3])
        final = register.fold(events)
        self.assertEqual(three.latest["at"], "t3")
        self.assertEqual([(e["root"], e["at"]) for e in three.before], [("/x/b", "t2")])
        self.assertIsNone(final.latest)
        self.assertEqual(final.before, ())

    def with_check(self):
        a = register.dismissed(register.failed("/x/a", "failed"))
        b_done = {**register.failed("/x/b", "failed"), "project_id": "o/b", "result": "registered",
                  "note": None}
        c_wait = {**self.r_wait, "root": "/x/c", "project_id": "c/c"}
        c_done = {**c_wait, "result": "registered", "note": None}
        owner = [("ended", a), ("reg", "o/b", "/x/b"), ("ended", b_done)]
        check = [("ended", c_wait), ("reg", "c/c", "/x/c"), ("ended", c_done),
                 ("gone", {"root": "/x/c"}, "c/c")]
        tail = [("gone", {"root": "/x/b"}, "o/b")]

        def build(spec):
            events = []
            for seq, (kind, *args) in enumerate(spec, 1):
                events.append({"ended": self.ended, "reg": self.reg, "gone": self.gone}[kind](
                    seq, *args))
            return events

        return build(owner + tail), build(owner + check + tail)

    def test_a_check_in_between_leaves_a_later_removal_unchanged(self):
        without, with_check = self.with_check()
        for events in (without, with_check):
            folded = register.fold(events)
            self.assertEqual(folded.latest["root"], "/x/a")
            self.assertEqual(folded.latest["at"], "t1")

    def test_an_owner_cancel_clears_the_chain(self):
        f = register.failed("/x/f", "failed")
        row = register.cancelled_row("/x/f", None)
        cancel = Event(3, "t3", row[0], None, row[2])
        events = [self.ended(1, self.y), self.ended(2, f), cancel, self.ended(4, self.r_done),
                  self.gone(5, {"root": "/x/r"})]
        cleared = register.fold(events[:3])
        self.assertIsNone(cleared.latest)
        self.assertEqual(cleared.before, ())
        self.assertIsNone(register.fold(events).latest)

    def test_an_incremental_fold_equals_the_whole_fold(self):
        _, with_check = self.with_check()
        whole = register.fold(with_check)
        for i in range(len(with_check) + 1):
            with self.subTest(split=i):
                first = register.fold(with_check[:i])
                kept = copy.deepcopy(first)
                self.assertEqual(register.fold(with_check[i:], first), whole)
                self.assertEqual(first, kept)


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

    def test_ended_takes_the_twelve_members_and_still_reads_a_legacy_row(self):
        p = register.summary("/srv/a", plan_doc(open_questions=1))
        twelve = {k: v for k, v in p.items() if k != "draft"}
        legacy = {k: p[k] for k in register.MEMBERS}
        self.assertEqual(register.ended(p)[2], p)
        self.assertEqual(register.ended(twelve)[2], twelve)
        self.assertEqual(register.ended(legacy)[2], legacy)
        self.assertEqual(register.latest([Event(1, "t1", register.ENDED, None, twelve)]),
                         {**twelve, "draft": None, "at": "t1"})
        self.assertEqual(register.latest([Event(1, "t1", register.ENDED, None, legacy)]),
                         {**legacy, **register.DEFAULTS, "at": "t1"})
        for bad in ({**p, "answered": [{"id": "x"}]},
                    {**p, "answered": [{"id": "x", "subject": "s", "value": 1}]},
                    {**p, "questions": "q"}, {**p, "plan_id": 3},
                    {k: v for k, v in p.items() if k != "state"}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                register.ended(bad)

    def test_a_ready_plan_saved_with_a_retired_draft_record_is_marked_for_planning_again(self):
        retired = {"field": "co-authored-by", "label": "co-author lines in commits", "value": "yes",
                   "source": "owner", "options": [], "text": False, "reason": None,
                   "ask": "Should its commits carry co-author lines?"}
        current = draft_fields()
        saved = register.summary("/srv/a", plan_doc(state="ready"), draft=[*current, retired])
        found = register.latest([Event(1, "t1", register.ENDED, None, saved)])
        self.assertIs(found["replan"], True)
        self.assertEqual(found["plan_id"], saved["plan_id"])
        self.assertEqual([f["field"] for f in found["draft"]], [f["field"] for f in current])
        for row in (register.summary("/srv/a", plan_doc(state="ready"), draft=current),
                    register.summary("/srv/a", plan_doc(state="ready"))):
            with self.subTest(draft=row["draft"]):
                self.assertNotIn(
                    "replan", register.latest([Event(1, "t1", register.ENDED, None, row)]))

    def test_a_drafting_row_asks_the_open_fields(self):
        fields = draft_fields()
        row = register.drafting("/x/sample-app", fields)
        self.assertEqual((row["result"], row["state"]), ("drafting", "drafting"))
        self.assertTrue(row["plan_id"].startswith("draft:sha256:"))
        self.assertEqual(row["headline"],
                         "What the console read from sample-app: it has no project contract yet")
        self.assertEqual(row["note"], "The draft has 1 open question.")
        self.assertEqual([q["subject"] for q in row["questions"]], ["lint-command"])
        self.assertEqual(row["questions"][0]["ask"], fields[1]["ask"])
        self.assertEqual(row["draft"], fields)
        self.assertEqual(row["project_id"], "sample-owner/sample-app")
        self.assertEqual(register.ended(row)[2], row)
        unread = [{**f, "source": None} if f["field"] == "project-identity" else f for f in fields]
        self.assertIsNone(register.drafting("/x/sample-app", unread)["project_id"])

    def test_a_repository_with_no_remote_words_its_integration_branch_card_plainly(self):
        fields = contract_draft.draft("/x/sample-app", {
            "remotes": [], "default_branch": None, "branches": ["trunk"], "files": [], "texts": {}})
        row = register.drafting("/x/sample-app", fields)
        (ask,) = [q["ask"] for q in row["questions"] if q["subject"] == "integration-branch"]
        self.assertIn("It has no remote, so the console cannot tell", ask)
        self.assertNotIn("Its remote", ask)

    def test_a_row_saved_before_the_plain_words_is_read_back_in_them(self):
        reading = {"remotes": [], "default_branch": None, "branches": ["trunk"], "files": [],
                   "texts": {}}
        now = contract_draft.draft("/x/sample-app", reading)
        # The same draft as an earlier console saved it: internal labels, old option and card words.
        old_label = {"production": "production", "release": "release profile"}
        saved = []
        for f in now:
            f = {**f, "label": old_label.get(f["field"], f["label"])}
            if f["field"] == "production":
                f["options"] = [{"value": "none", "label": "It has no production"}]
            if f["field"] == "integration-branch":
                f["ask"] = ("Which branch is the default branch of sample-app?\n"
                            "It has no remote at all: choose a branch or type its name.")
            if f["field"] == "release":
                f.update(value='{"kind": "x"}', source="owner")
            saved.append(f)
        row = register.drafting("/x/sample-app", saved)
        found = register.latest([Event(1, "t1", register.ENDED, None, row)])
        draft = {f["field"]: f for f in found["draft"]}
        self.assertEqual(draft["production"]["label"], "production rules")
        self.assertEqual(draft["production"]["options"],
                         [{"value": "none", "label": "It declares no production rules"}])
        self.assertEqual(draft["release"]["label"], "how it is released")
        self.assertEqual((draft["release"]["value"], draft["release"]["source"]),
                         ('{"kind": "x"}', "owner"))
        self.assertIn("It has no remote, so the console cannot tell", draft["integration-branch"]["ask"])
        self.assertEqual(draft["integration-branch"]["options"], [{"value": "trunk", "label": "trunk"}])
        (branch,) = [q for q in found["questions"] if q["subject"] == "integration-branch"]
        self.assertEqual(branch["ask"], draft["integration-branch"]["ask"])
        self.assertNotIn("Its remote", "".join(q["ask"] for q in found["questions"]))
        self.assertEqual(found["plan_id"], row["plan_id"])
        shown = {e["field"]: e["line"] for e in register.view_entry(None, found)["draft"]}
        self.assertNotIn("production", shown["release"].lower())

    def test_a_row_saved_with_the_light_lane_field_reads_back_without_it(self):
        reading = {"remotes": [], "default_branch": None, "branches": ["trunk"], "files": [],
                   "texts": {}}
        now = contract_draft.draft("/x/sample-app", reading)
        light = {"field": "light-lane", "label": "light lane",
                 "value": '{"mode": "shadow", "budget_minutes": 90, "risk_paths": []}',
                 "source": "owner", "options": [{"value": "none", "label": "It has no light lane"}],
                 "text": True, "reason": None, "ask": "What is the light lane of sample-app?"}
        kept = [f for f in now if f["field"] != "light-lane"]
        saved = []
        for f in kept:
            saved.append(f)
            if f["field"] == "test-command":
                saved.append(light)
        row = register.drafting("/x/sample-app", saved)
        found = register.latest([Event(1, "t1", register.ENDED, None, row)])
        entry = register.view_entry(None, found)
        self.assertEqual([f["field"] for f in found["draft"]], [f["field"] for f in kept])
        self.assertNotIn("light-lane", [e["field"] for e in entry["draft"]])
        self.assertEqual(found["plan_id"], row["plan_id"])

    def planned_with_light_lane(self, light_value, *, state, refused=None):
        """The row an earlier console saved: a full draft carrying the retired light-lane record."""
        root = "/x/sample-app"
        reading = {"remotes": [("origin", "git@github.com:sample-owner/sample-app.git")],
                   "default_branch": "trunk", "branches": ["trunk"], "files": ["README.md"],
                   "texts": {}}
        fields = contract_draft.draft(root, reading)
        for field in ("lint-command", "test-command"):
            fields, _ = contract_draft.set_value(fields, field, "just " + field[:4])
        light = {"field": "light-lane", "label": "light lane", "value": light_value,
                 "source": "owner", "options": [{"value": "none", "label": "It has no light lane"}],
                 "text": True, "reason": refused, "ask": "What is the light lane of sample-app?"}
        at = [f["field"] for f in fields].index("test-command") + 1
        saved = [*fields[:at], light, *fields[at:]]
        if state is None:
            return root, register.drafting(root, saved)
        return root, register.summary(root, plan_doc(outcome="bootstrap", state=state),
                                      draft=saved)

    SHADOW = '{"mode": "shadow", "budget_minutes": 90, "risk_paths": []}'

    def test_a_ready_plan_that_wrote_a_light_lane_is_planned_again_before_apply(self):
        root, row = self.planned_with_light_lane(self.SHADOW, state="ready")
        self.assertEqual((row["state"], row["plan_id"]), ("ready", PLAN_ID))
        found = register.latest([Event(1, "t1", register.ENDED, None, row)])
        self.assertEqual((found["result"], found["state"]), ("drafting", "drafting"))
        self.assertEqual(found["plan_id"], PLAN_ID)
        self.assertEqual([q["subject"] for q in found["questions"]], ["integration-branch"])
        self.assertNotIn("light-lane", [f["field"] for f in found["draft"]])
        answered, refusal = contract_draft.set_value(found["draft"], "integration-branch", "trunk")
        self.assertIsNone(refusal)
        self.assertEqual(contract_draft.open_fields(answered), [])
        self.assertNotIn("workflow", contract_draft.contract(answered)["bindings"])

    def test_a_cancel_naming_the_saved_plan_still_ends_a_replanned_registration(self):
        root, row = self.planned_with_light_lane(self.SHADOW, state="ready")
        events = [Event(1, "t1", register.ENDED, None, row),
                  Event(2, "t2", *register.cancelled_row(root, PLAN_ID))]
        self.assertIsNone(register.fold(events).latest)

    def test_a_replanned_registration_keeps_the_plan_id_adoptions_are_keyed_by(self):
        _, row = self.planned_with_light_lane(self.SHADOW, state="ready")
        found = register.latest([Event(1, "t1", register.ENDED, None, row)])
        self.assertEqual((found["plan_id"], found["state"]), (PLAN_ID, "drafting"))

    def adoption_entry(self, step, state=None):
        return {"status": "done", "step": step, "state": state, "headline": "adopted",
                "lines": [], "note": None, "branch": None, "commit": None, "url": None}

    def test_a_replanned_registration_with_an_adoption_past_a_failed_apply_has_no_question(self):
        _, row = self.planned_with_light_lane(self.SHADOW, state="ready")
        found = register.latest([Event(1, "t1", register.ENDED, None, row)])
        self.assertEqual([q["subject"] for q in found["questions"]], ["integration-branch"])
        for step, state in (("applied", None), ("push_failed", None), ("open_failed", None),
                            ("opened", "ready"), ("opened", "failing"), ("opened", "merged")):
            with self.subTest(step=step, state=state):
                shown = register.view_entry(None, found, adoption=self.adoption_entry(step, state))
                self.assertEqual(shown["questions"], [])
                self.assertFalse(register.plans_again(step, state))
        for step, state in ((None, None), ("apply_failed", None), ("opened", "closed")):
            with self.subTest(step=step, state=state):
                shown = register.view_entry(None, found, adoption=self.adoption_entry(step, state))
                self.assertEqual([q["subject"] for q in shown["questions"]], ["integration-branch"])
                self.assertTrue(register.plans_again(step, state))
        self.assertEqual([q["subject"] for q in register.view_entry(None, found)["questions"]],
                         ["integration-branch"])

    def test_the_saved_plan_stands_in_for_the_replanned_row_once_its_adoption_is_past_a_failed_apply(self):
        _, row = self.planned_with_light_lane(self.SHADOW, state="ready")
        state = register.fold([Event(1, "t1", register.ENDED, None, row)])
        self.assertEqual(state.latest["state"], "drafting")
        self.assertEqual(register.shown(state, {}), state.latest)
        for step, pull in (("applied", None), ("push_failed", None), ("open_failed", None),
                           ("opened", "open"), ("opened", "merged")):
            with self.subTest(step=step, pull=pull):
                found = register.shown(state, {PLAN_ID: {"step": step, "pull_state": pull}})
                self.assertEqual((found["state"], found["plan_id"]), ("ready", PLAN_ID))
        for step, pull in (("apply_failed", None), ("opened", "closed")):
            with self.subTest(step=step, pull=pull):
                found = register.shown(state, {PLAN_ID: {"step": step, "pull_state": pull}})
                self.assertEqual(found["state"], "drafting")
        _, plain = self.planned_with_light_lane(self.SHADOW, state=None)
        drafting = register.fold([Event(1, "t1", register.ENDED, None, plain)])
        self.assertEqual(drafting.held, ())

    def test_the_saved_plan_stands_in_again_when_the_page_falls_back_to_its_row(self):
        """Another root's registration pushes the replanned row into `before` (#1445)."""
        _, row = self.planned_with_light_lane(self.SHADOW, state="ready")
        other = register.failed("/x/other", "failed")
        adoptions = {PLAN_ID: {"step": "push_failed", "pull_state": None}}
        opened = [Event(1, "t1", register.ENDED, None, row),
                  Event(2, "t2", register.ENDED, None, other),
                  Event(3, "t3", "project.registered", "c/other", {"root": "/x/other"})]
        gone = Event(4, "t4", "project.unregistered", "c/other", {"root": "/x/other"})
        cancelled = Event(4, "t4", *register.cancelled_row("/x/other", other["plan_id"], restore=True))
        for name, last in (("unregistered", gone), ("cancelled", cancelled)):
            with self.subTest(fall_back=name):
                before = register.fold(opened)
                self.assertEqual(register.shown(before, adoptions)["root"], "/x/other")
                state = register.fold([last], before)
                self.assertEqual(state.latest["state"], "drafting")
                found = register.shown(state, adoptions)
                self.assertEqual((found["state"], found["plan_id"]), ("ready", PLAN_ID))
                self.assertEqual(register.shown(state, {})["state"], "drafting")
                whole = register.fold([*opened, last])
                self.assertEqual(register.shown(whole, adoptions)["state"], "ready")

    def test_a_ready_plan_whose_light_lane_was_none_keeps_its_plan(self):
        _, row = self.planned_with_light_lane("none", state="ready")
        found = register.latest([Event(1, "t1", register.ENDED, None, row)])
        self.assertEqual((found["result"], found["state"], found["plan_id"]),
                         ("planned", "ready", PLAN_ID))
        self.assertNotIn("light-lane", [f["field"] for f in found["draft"]])

    def test_a_draft_whose_only_question_was_the_light_lane_still_has_a_card(self):
        _, row = self.planned_with_light_lane(
            self.SHADOW, state=None,
            refused="The plan refused the light lane: not a light lane")
        self.assertEqual([q["subject"] for q in row["questions"]], ["light-lane"])
        found = register.latest([Event(1, "t1", register.ENDED, None, row)])
        self.assertEqual((found["result"], found["state"]), ("drafting", "drafting"))
        self.assertEqual([q["subject"] for q in found["questions"]], ["integration-branch"])
        self.assertEqual(found["note"], "The draft has 1 open question.")
        self.assertNotIn("light-lane", [f["field"] for f in found["draft"]])

    def test_ended_takes_thirteen_members_and_checks_the_draft(self):
        row = register.drafting("/x/sample-app", draft_fields())
        self.assertEqual(len(row), 13)
        self.assertEqual(register.ended(row)[2], row)
        lacking = [{k: v for k, v in row["draft"][0].items() if k != "ask"}, *row["draft"][1:]]
        extra = [{**row["draft"][0], "more": 1}, *row["draft"][1:]]
        for bad in ({**row, "draft": lacking}, {**row, "draft": extra}, {**row, "draft": "x"},
                    {**row, "draft": ["x"]}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                register.ended(bad)
        self.assertEqual(register.ended({**row, "draft": None})[2]["draft"], None)
        legacy = {k: row[k] for k in register.MEMBERS}
        self.assertEqual(register.latest([Event(1, "t1", register.ENDED, None, legacy)])["draft"],
                         None)

    def test_a_drafting_row_says_its_questions_in_one_line(self):
        fields = draft_fields()
        row = register.drafting("/x/sample-app", fields)
        entry = register.view_entry(None, {**row, "at": "t"})
        self.assertEqual(entry["line"], "Register sample-app: 1 question open")
        self.assertEqual(entry["draft"], contract_draft.shown(fields))
        self.assertEqual(entry["draft_more"], contract_draft.more_line(draft_fields()))
        running = register.view_entry("/x/sample-app", None)
        self.assertIsNone(running["draft"])
        self.assertIsNone(running["draft_more"])
        self.assertEqual(len(running), 22)
        self.assertEqual(len(entry), 22)
        full = contract_draft.draft("/x/sample-app", {
            "remotes": [("origin", "git@github.com:sample-owner/sample-app.git")],
            "default_branch": "trunk", "branches": ["trunk"], "files": ["README.md"], "texts": {}})
        shown = register.view_entry(None, {**register.drafting("/x/sample-app", full), "at": "t"})
        self.assertEqual(shown["draft_more"], "and 2 more settings at their usual values")

    def test_the_draft_id_follows_the_values(self):
        one = draft_fields()
        two = draft_fields()
        two[0]["value"] = "sample-owner/other-app"
        self.assertNotEqual(register.drafting("/x/a", one)["plan_id"],
                            register.drafting("/x/a", two)["plan_id"])
        self.assertEqual(register.drafting("/x/a", one)["plan_id"],
                         register.drafting("/x/a", draft_fields())["plan_id"])

    def test_view_entry_again_and_refusal(self):
        self.assertEqual(register.view_entry("/srv/r", None, again=True)["headline"],
                         "Planning the adoption of r again with your answer\u2026")
        latest = {**register.summary("/srv/r", plan_doc(open_questions=1)), "at": "t"}
        self.assertEqual(register.view_entry(
            None, latest, refusal={"plan_id": latest["plan_id"], "text": "T", "id": "q0",
                     "subject": ""})["refusal"], "T")
        self.assertIsNone(register.view_entry(
            None, latest, refusal={"plan_id": "sha256:other", "text": "T", "id": "q0",
                     "subject": ""})["refusal"])
        self.assertIsNone(register.view_entry(
            "/srv/r", latest, refusal={"plan_id": latest["plan_id"], "text": "T", "id": "q0",
                                   "subject": ""})["refusal"])

    def test_view_entry_names_the_refused_question(self):
        latest = {**register.summary("/srv/r", plan_doc(open_questions=1)), "at": "t"}
        given = {"plan_id": latest["plan_id"], "text": "T", "id": "q0", "subject": ""}
        shown = register.view_entry(None, latest, refusal=given)
        self.assertEqual((shown["refusal"], shown["refused"]), ("T", {"id": "q0", "subject": ""}))
        other = register.view_entry(None, latest, refusal={**given, "plan_id": "sha256:other"})
        self.assertEqual((other["refusal"], other["refused"]), (None, None))
        running = register.view_entry("/srv/r", latest, refusal=given)
        self.assertEqual((running["refusal"], running["refused"]), (None, None))

    def test_view_entry_line_says_the_state_in_one_line(self):
        def row(doc, extra=None):
            return {**register.summary("/srv/r", doc, extra), "at": "t"}

        def line(latest):
            return register.view_entry(None, latest)["line"]

        failed = {**register.failed("/srv/r", "timed_out"), "at": "t"}
        blocker = row(plan_doc(blockers=[{"message": "a blocker"}]))
        registered = row(plan_doc(outcome="no_change", state="ready"),
                         {"registered": True, "project_id": "o/r"})
        self.assertEqual(
            [line(row(plan_doc(open_questions=2))), line(row(plan_doc(open_questions=1))),
             line(row(plan_doc(state="ready"))), line(blocker), line(failed), line(registered)],
            ["Register r: 2 questions open", "Register r: 1 question open",
             "Register r: ready to apply", "The plan is a draft: a blocker",
             f"{failed['headline']} {failed['note']}", "r is registered as o/r."])
        self.assertEqual(register.view_entry("/srv/r", None)["line"],
                         "Planning the adoption of r\u2026")
        self.assertEqual(register.view_entry("/srv/r", None, again=True)["line"],
                         "Planning the adoption of r again with your answer\u2026")

    def test_view_entry_running_done_none(self):
        self.assertEqual(register.view_entry("/srv/r", None), {
            "root": "/srv/r", "name": "r", "project_id": None, "status": "running",
            "result": None, "outcome": None, "headline": "Planning the adoption of r…",
            "lines": [], "note": None, "at": None, "plan_id": None, "state": None,
            "questions": [], "refusal": None, "line": "Planning the adoption of r\u2026",
            "refused": None, "draft": None, "draft_more": None, "adoption": None,
            "approve": None, "cancel": False, "remote": None})
        latest = {**register.summary("/srv/r", plan_doc(state="ready")), "at": "t"}
        self.assertEqual(register.view_entry(None, latest), {
            "root": "/srv/r", "name": "r", "project_id": "o/r", "status": "done",
            "result": "planned", "outcome": "reconcile",
            "headline": latest["headline"], "lines": [],
            "note": "The plan is ready.",
            "at": "t", "plan_id": PLAN_ID, "state": "ready", "questions": [], "refusal": None,
            "line": "Register r: ready to apply", "refused": None, "draft": None,
            "draft_more": None, "adoption": None, "approve": None, "cancel": False,
            "remote": None})
        self.assertTrue(register.view_entry(None, latest, cancel=True)["cancel"])
        self.assertFalse(register.view_entry("/srv/r", None, cancel=True)["cancel"])
        self.assertIsNone(register.view_entry(None, None))

    def test_view_entry_carries_the_adoption_and_its_action(self):
        latest = {**register.summary("/srv/r", plan_doc(state="ready")), "at": "t"}
        adoption = {"status": "done", "headline": "The adoption of r was applied.",
                    "note": None}
        shown = register.view_entry(None, latest, adoption=adoption, approve="retry")
        self.assertEqual((shown["adoption"], shown["approve"]), (adoption, "retry"))
        self.assertEqual(shown["line"], "The adoption of r was applied.")
        self.assertEqual(register.view_entry(None, latest)["line"], "Register r: ready to apply")
        running = register.view_entry("/srv/r", latest, adoption=adoption, approve="approve")
        self.assertEqual((running["adoption"], running["approve"]), (None, None))
        self.assertEqual(running["line"], "Planning the adoption of r\u2026")

    def opened_adoption(self, pull_state, note=None):
        found = approve.entry(
            {"step": "opened", "plan_id": "p1", "root": "/srv/r", "project_id": "o/r",
             "branch": "adopt-bbbbbbbbbbbb", "commit": "c" * 40, "base": "develop",
             "pull_request": {"number": 7, "url": "https://example.test/pull/7"},
             "reason": None, "note": None, "kept": None, "at": "t", "pull_state": pull_state,
             "pull_at": "t"},
            running=False, name="r")
        return {**found, "note": note}

    def drafted_latest(self):
        full = contract_draft.draft("/x/r", {
            "remotes": [("origin", "git@github.com:sample-owner/r.git")],
            "default_branch": "trunk", "branches": ["trunk"], "files": ["README.md"], "texts": {}})
        return {**register.summary("/srv/r", plan_doc(state="ready", open_questions=0)),
                "lines": ["moves 1 agent file under .agents/"], "draft": full, "at": "t"}

    def test_view_entry_with_an_adoption_holds_one_sentence_and_no_lines(self):
        latest = {**register.summary("/srv/r", plan_doc(state="ready")),
                  "lines": ["moves 1 agent file under .agents/"], "at": "t"}
        waiting = register.view_entry(None, latest, adoption=self.opened_adoption("open"),
                                      approve=None)
        self.assertEqual(waiting["lines"], [])
        self.assertEqual(waiting["line"], "The proposed change of r is not ready to merge yet.")
        closed = register.view_entry(
            None, latest, adoption=self.opened_adoption("closed", approve.CLOSED_NOTE),
            approve=None)
        self.assertEqual(closed["lines"], [])
        self.assertEqual(closed["line"], closed["adoption"]["headline"] + " " + approve.CLOSED_NOTE)
        self.assertEqual(register.view_entry(None, latest)["lines"], latest["lines"])

    def test_view_entry_with_an_adoption_draws_no_draft(self):
        latest = self.drafted_latest()
        alone = register.view_entry(None, latest)
        self.assertTrue(alone["draft"])
        self.assertTrue(any(entry["more"] for entry in alone["draft"]))
        self.assertIsNotNone(alone["draft_more"])
        for state in ("open", "ready"):
            with self.subTest(state=state):
                shown = register.view_entry(None, latest, adoption=self.opened_adoption(state),
                                            approve=None)
                self.assertIsNone(shown["draft"])
                self.assertIsNone(shown["draft_more"])


FAKE = """#!/bin/sh
echo "$@" >> "$FAKE_ARGS"
if [ "$FAKE_SLEEP" = 1 ]; then sleep 30; fi
printf '%s' "$FAKE_OUT"
exit "$FAKE_EXIT"
"""


class BehindTest(unittest.TestCase):
    """The behind row, its Update card, the failed update and the unread-remote sentence (#1233)."""

    def behind_latest(self):
        return {**register.behind("/x/r", 1, True), "at": "t"}

    def test_a_behind_row_says_the_count_and_whether_the_remote_has_a_contract(self):
        row = register.behind("/x/r", 1, True)
        self.assertEqual(row["headline"],
                         "r is 1 commit behind its remote, which already has a project contract.")
        self.assertEqual(register.behind("/x/r", 3, False)["headline"],
                         "r is 3 commits behind its remote, which has no project contract yet.")
        self.assertEqual(row["result"], "behind")
        self.assertEqual(row["note"], register.BEHIND_NOTE)
        self.assertIsNone(row["plan_id"])
        self.assertEqual(row["lines"], [])
        self.assertEqual(row["questions"], [])
        self.assertEqual(register.ended(row)[2], row)

    def test_a_behind_row_is_one_update_card(self):
        latest = self.behind_latest()
        (card,) = register.confirm_items(latest, running=False)
        self.assertEqual(card["reason"], "register_behind")
        self.assertEqual(card["key"], "register-behind//x/r/t")
        self.assertEqual(card["questions"][0]["options"], ["Update it", "Not now"])
        self.assertEqual(card["values"], ["update", "not_now"])
        self.assertEqual(card["headline"], latest["headline"])
        self.assertEqual(card["why"], register.BEHIND_NOTE)
        self.assertEqual(register.confirm_items(latest, running=True), [])
        self.assertEqual(register.failure_items(latest, running=False), [])
        self.assertIs(register.waiting(latest), False)
        self.assertIs(register.failing(latest), False)

    def test_not_now_on_a_behind_row_removes_its_card(self):
        gone = {**register.dismissed(self.behind_latest()), "at": "u"}
        self.assertEqual(gone["result"], "behind")
        self.assertEqual(gone["note"], register.LATER_NOTE)
        self.assertEqual(register.confirm_items(gone, running=False), [])
        self.assertEqual(register.failure_items(gone, running=False), [])

    def test_parse_confirm_request_takes_update(self):
        self.assertEqual(register.parse_confirm_request(b'{"root": "/x/r", "choice": "update"}'),
                         ("/x/r", "update"))

    def test_a_failed_update_is_a_try_again_card(self):
        row = register.update_failed("/x/r", "it has changes that are not committed")
        self.assertEqual(row["headline"], "r could not be updated: it has changes that are not committed.")
        self.assertEqual(row["note"], "Update the checkout in a terminal, then choose Try again.")
        self.assertEqual(row["result"], "failed")
        latest = {**row, "at": "t"}
        self.assertIs(register.failing(latest), True)
        (item,) = register.failure_items(latest, running=False)
        self.assertEqual(item["values"], ["try_again", "not_now"])

    def test_an_unread_remote_rides_on_the_row_and_the_entry(self):
        row = register.unread(register.summary("/x/r", plan_doc()))
        self.assertEqual(row["remote"], register.REMOTE_UNREAD)
        self.assertEqual(row["lines"], register.summary("/x/r", plan_doc())["lines"])
        self.assertEqual(register.ended(row)[2], row)
        with self.assertRaises(ValueError):
            register.ended({**row, "remote": 5})
        found = register.latest([Event(1, "t1", register.ENDED, None, row)])
        self.assertEqual(register.view_entry(None, found)["remote"], register.REMOTE_UNREAD)
        self.assertEqual(register.dismissed(found)["remote"], register.REMOTE_UNREAD)
        plain = {**register.summary("/x/r", plan_doc()), "at": "t"}
        self.assertIsNone(register.view_entry(None, plain)["remote"])
        self.assertIsNone(register.view_entry("/x/r", None)["remote"])


class AdopterTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.script = self.tmp / "fake"
        self.script.write_text(FAKE)
        self.script.chmod(self.script.stat().st_mode | stat.S_IXUSR)
        self.args = self.tmp / "args"

    def adopter(self, *, out='{"a":1}', code=0, sleep=False, timeout=30, command=None,
                apply_timeout=None):
        environ = {"PATH": os.environ["PATH"], "FAKE_ARGS": str(self.args), "FAKE_OUT": out,
                   "FAKE_EXIT": str(code), "FAKE_SLEEP": "1" if sleep else "0"}
        extra = {} if apply_timeout is None else {"apply_timeout": apply_timeout}
        return Adopter(command=command or (str(self.script),), environ=environ, timeout=timeout,
                       **extra)

    def test_plan_and_register_argv(self):
        adopter = self.adopter()
        adopter.plan("/r")
        adopter.register("/r")
        self.assertEqual(self.args.read_text().splitlines(),
                         ["plan --repo-root /r --format json", "verify --repo-root /r --register"])

    def test_register_argv_carries_the_integration_branch_and_the_plan_id(self):
        adopter = self.adopter()
        adopter.register("/r", integration_branch="develop", plan_id="sha256:aa")
        adopter.register("/r", plan_id="sha256:aa")
        self.assertEqual(self.args.read_text().splitlines(),
                         ["verify --repo-root /r --register --integration-branch develop "
                          "--plan-id sha256:aa",
                          "verify --repo-root /r --register --plan-id sha256:aa"])

    def test_apply_argv_with_and_without_the_deletion_acknowledgement(self):
        adopter = self.adopter()
        adopter.apply("sha256:aa")
        adopter.apply("sha256:aa", acknowledge_deletions=True)
        self.assertEqual(self.args.read_text().splitlines(),
                         ["apply --plan-id sha256:aa",
                          "apply --plan-id sha256:aa --acknowledge-deletions"])

    def test_apply_discards_the_retained_copy_when_asked(self):
        adopter = self.adopter()
        adopter.apply("sha256:aa", acknowledge_deletions=True, discard_retained=True)
        adopter.apply("sha256:aa", acknowledge_deletions=True)
        self.assertEqual(self.args.read_text().splitlines(),
                         ["apply --plan-id sha256:aa --acknowledge-deletions --discard-retained",
                          "apply --plan-id sha256:aa --acknowledge-deletions"])

    def test_discard_runs_the_discard_subcommand(self):
        self.adopter().discard("sha256:aa")
        self.assertEqual(self.args.read_text().splitlines(), ["discard --plan-id sha256:aa"])

    def test_apply_has_its_own_timeout(self):
        self.assertEqual(register.APPLY_TIMEOUT, 1800)
        with self.assertRaises(RunFailed) as failed:
            self.adopter(sleep=True, timeout=60, apply_timeout=1).apply("sha256:aa")
        self.assertEqual(failed.exception.kind, "timed_out")

    def test_plan_sends_every_answer_in_order(self):
        self.adopter().plan("/r", answers=[
            {"id": "candidate-class", "subject": ".claude/odd.md", "value": "archive-history"},
            {"id": "path-reference", "subject": "tools/show.sh:1:5", "value": "rewrite"}])
        self.assertEqual(self.args.read_text().splitlines()[-1],
                         "plan --repo-root /r --format json --answer candidate-class "
                         ".claude/odd.md archive-history --answer path-reference "
                         "tools/show.sh:1:5 rewrite")

    def test_plan_sends_the_drafted_contract_after_the_answers(self):
        answer = {"id": "contract-draft", "subject": "lint-command", "value": "make"}
        self.adopter().plan("/r", answers=[answer], contract="/s/d.json")
        self.adopter().plan("/r", answers=[answer])
        first, second = self.args.read_text().splitlines()[-2:]
        self.assertEqual(first, "plan --repo-root /r --format json --answer contract-draft "
                                "lint-command make --contract-draft /s/d.json")
        self.assertNotIn("--contract-draft", second)

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


FORBIDDEN = ("systemd-run", "systemctl", "/proc")


class PlatformTest(unittest.TestCase):
    def test_adopter_for_each_platform(self):
        for platform in ("linux", "darwin", "win32"):
            with self.subTest(platform=platform):
                found = register.adopter_for(platform)
                if platform == "win32":
                    self.assertIsNone(found)
                else:
                    self.assertIsInstance(found, Adopter)

    def test_a_darwin_adopter_runs_only_its_sibling_and_no_linux_tool(self):
        records = []

        def run(argv, **kwargs):
            records.append((argv, kwargs))
            return subprocess.CompletedProcess(argv, 0, b'{"plan": {}}', None)

        with mock.patch.object(register.manager, "run_in_own_group", run):
            adopter = register.adopter_for("darwin")
            plan_id = "sha256:" + "a" * 64
            adopter.plan("/r")
            adopter.register("/r", integration_branch="main", plan_id=plan_id)
            adopter.apply(plan_id, acknowledge_deletions=True, discard_retained=True)
            adopter.discard(plan_id)
        sibling = siblings.sibling_argv("project_contract.adopt_project")
        self.assertEqual(len(records), 4)
        for argv, kwargs in records:
            with self.subTest(argv=argv):
                self.assertEqual(argv[:len(sibling)], sibling)
                self.assertFalse(any(word in element for word in FORBIDDEN for element in argv))
                self.assertIs(kwargs["start_new_session"], True)


if __name__ == "__main__":
    unittest.main()
