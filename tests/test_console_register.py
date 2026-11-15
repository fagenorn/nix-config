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

from agent_tools.console import contract_draft, plan_questions, register
from agent_tools.console.event_log import Event
from agent_tools.console.register import Adopter, RunFailed

from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1052)

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
            {"op": "write-file", "sources": [], "targets": [f".agents/artifacts/evidence/{digest}.json"]},
        ]

        def writes(*paths):
            return [{"op": "write-file", "sources": [], "targets": [path]} for path in paths]

        end = ", and records the adoption"
        handoff = {"migration_map": records[0]["targets"][0],
                   "evidence_record": records[1]["targets"][0]}
        cases = [
            (writes(".agents/runtime/.gitignore", ".gitignore") + records,
             [f"writes .agents/runtime/.gitignore and .gitignore{end}"]),
            (records, ["records the adoption"]),
            (records[:1], ["records the adoption"]),
            (records[1:], ["records the adoption"]),
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
        handoff = {"migration_map": f".agents/knowledge/archive/path-migrations/{digest}.json",
                   "evidence_record": f".agents/artifacts/evidence/{digest}.json"}
        paths = [".agents/artifacts/evidence/checklist.md",
                 ".agents/knowledge/archive/path-migrations/notes.md", handoff["evidence_record"]]
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
    return [
        {"field": "project-id", "label": "Project id", "value": "sample-owner/sample-app",
         "source": "remote", "options": [], "text": True, "reason": None,
         "ask": "Which project is this repository?"},
        {"field": "build-command", "label": "Build command", "value": None, "source": "none",
         "options": [], "text": True, "reason": None,
         "ask": "Which command builds sample-app?\nThe console found none in its files: type "
                "the command, or say it has none."}]


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

    def test_a_no_change_plan_without_a_report_names_its_terminal_handoff(self):
        nc = {"plan": {"state": "ready", "outcome": "no_change", "project_id": "o/r",
                       "blockers": [], "plan_id": "sha256:" + "c" * 64},
              "decisions": {"open": [], "answered": []},
              "handoff": {"next_command": "adopt-project verify --register --repo-root /srv/r"}}
        for document in (register.summary("/srv/r", nc),
                         register.summary("/srv/r", {**nc, "handoff": {"next_command": None}})):
            self.assertEqual((document["result"], document["outcome"], document["lines"],
                              document["note"], document["plan_id"]),
                             ("not_registered", "no_change", [], None, None))
            self.assertEqual(document["headline"],
                             "r needs no adoption change and is not registered yet: run "
                             "adopt-project verify --register --repo-root /srv/r")

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
MANIFEST_STEP = ("The agent platform's files are not installed on this host yet. Run just switch "
                 "in a terminal to install them, then press Register again.")
PLAN_COMMAND = "adopt-project plan --repo-root /srv/r"
REGISTER_COMMAND = "adopt-project verify --register --repo-root /srv/r"
CODE_WORDS = ("adopt.", "platform.", "adopt_failure", "not_integrated", "timed_out", "not_installed")


class NextStepTest(unittest.TestCase):
    def test_a_missing_platform_manifest_says_just_switch_and_register_again(self):
        for repair_id in ("adopt.manifest.invalid", "adopt.manifest.forward_step_missing",
                          "adopt.manifest.forward_step_ambiguous"):
            with self.subTest(repair_id=repair_id):
                row = register.summary("/srv/r", adopt_error(
                    repair_id, "the installed platform manifest was not found"))
                self.assertEqual(row["headline"], "The adoption plan for r could not start: "
                                 "the agent platform's files are not installed on this host.")
                self.assertNotIn("manifest", row["headline"])
                self.assertEqual(row["note"], MANIFEST_STEP)
                reg = register.summary("/srv/r", NO_CHANGE, adopt_error(
                    repair_id, "the installed platform manifest was not found"))
                self.assertEqual(reg["headline"], "r was not registered: "
                                 "the agent platform's files are not installed on this host.")
                self.assertNotIn("manifest", reg["headline"])
                self.assertEqual(reg["note"], MANIFEST_STEP)

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
                self.assertEqual(row["note"],
                                 f"Run {PLAN_COMMAND} in a terminal to see the full reason.")
                reg = register.summary("/srv/r", NO_CHANGE, adopt_error(repair_id, message))
                self.assertEqual(reg["headline"], f"r was not registered: {message}.")
                self.assertNotIn("just switch", row["note"] + reg["note"])

    def test_each_refused_registration_has_its_own_next_step(self):
        again = "then press Register again."
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

    def test_an_unlisted_failure_names_the_terminal_command_for_its_kind(self):
        plan = register.summary("/srv/r", adopt_error("adopt.something.else"))
        self.assertEqual(plan["note"], f"Run {PLAN_COMMAND} in a terminal to see the full reason.")
        for error in ({"code": "adopt_failure"}, adopt_error("adopt.registration.integration_branch_unresolved")["error"]):
            with self.subTest(error=error):
                reg = register.summary("/srv/r", NO_CHANGE, {"error": error})
                self.assertEqual(reg["note"],
                                 f"Run {REGISTER_COMMAND} in a terminal to see the full reason.")
        none = register.summary("/srv/r", NO_CHANGE, {"registered": False, "result": "x"})
        self.assertEqual(none["note"], f"Run {REGISTER_COMMAND} in a terminal to see the full reason.")
        unreadable = register.summary("/srv/r", {"plan": {"outcome": "odd"}})
        self.assertEqual(unreadable["note"], register.run_next_step("/srv/r", "unreadable"))

    def test_every_run_kind_names_the_terminal_command(self):
        retry = "Press Register again. If it keeps failing, run "
        for kind in register.RUN_KINDS:
            with self.subTest(kind=kind):
                note = register.failed("/srv/r", kind)["note"]
                self.assertIn(PLAN_COMMAND, note)
                if kind in ("timed_out", "not_installed", "unavailable", "cancelled"):
                    self.assertTrue(note.startswith(retry), note)
                else:
                    self.assertEqual(note, f"Run {PLAN_COMMAND} in a terminal to see the full reason.")
        self.assertIn(PLAN_COMMAND, register.failed("/srv/r", "ValueError")["note"])

    def test_a_registration_that_raised_names_the_register_command(self):
        for kind in register.RUN_KINDS:
            with self.subTest(kind=kind):
                row = register.failed("/srv/r", kind, "register")
                self.assertEqual(row["headline"],
                                 f"r was not registered: {register.RUN_WORDS[kind]}.")
                self.assertIn(REGISTER_COMMAND, row["note"])
                self.assertNotIn(PLAN_COMMAND, row["note"])

    def test_the_path_is_quoted_for_a_terminal(self):
        self.assertIn("--repo-root '/srv/my repo'", register.failed("/srv/my repo", "failed")["note"])

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

    def test_a_drafting_row_asks_the_open_fields(self):
        fields = draft_fields()
        row = register.drafting("/x/sample-app", fields)
        self.assertEqual((row["result"], row["state"]), ("drafting", "drafting"))
        self.assertTrue(row["plan_id"].startswith("draft:sha256:"))
        self.assertEqual(row["headline"],
                         "What the console read from sample-app: it has no project contract yet")
        self.assertEqual(row["note"], "The draft has 1 open question.")
        self.assertEqual([q["subject"] for q in row["questions"]], ["build-command"])
        self.assertEqual(row["questions"][0]["ask"], fields[1]["ask"])
        self.assertEqual(row["draft"], fields)
        self.assertEqual(row["project_id"], "sample-owner/sample-app")
        self.assertEqual(register.ended(row)[2], row)

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
        running = register.view_entry("/x/sample-app", None)
        self.assertIsNone(running["draft"])
        self.assertEqual(len(running), 19)

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
            "refused": None, "draft": None, "adoption": None, "approve": None})
        latest = {**register.summary("/srv/r", plan_doc(state="ready")), "at": "t"}
        self.assertEqual(register.view_entry(None, latest), {
            "root": "/srv/r", "name": "r", "project_id": "o/r", "status": "done",
            "result": "planned", "outcome": "reconcile",
            "headline": latest["headline"], "lines": [],
            "note": "The plan is ready.",
            "at": "t", "plan_id": PLAN_ID, "state": "ready", "questions": [], "refusal": None,
            "line": "Register r: ready to apply", "refused": None, "draft": None,
            "adoption": None, "approve": None})
        self.assertIsNone(register.view_entry(None, None))

    def test_view_entry_carries_the_adoption_and_its_action(self):
        latest = {**register.summary("/srv/r", plan_doc(state="ready")), "at": "t"}
        adoption = {"status": "done", "headline": "The adoption of r was applied."}
        shown = register.view_entry(None, latest, adoption=adoption, approve="retry")
        self.assertEqual((shown["adoption"], shown["approve"]), (adoption, "retry"))
        self.assertEqual(shown["line"], "The adoption of r was applied.")
        self.assertEqual(register.view_entry(None, latest)["line"], "Register r: ready to apply")
        running = register.view_entry("/srv/r", latest, adoption=adoption, approve="approve")
        self.assertEqual((running["adoption"], running["approve"]), (None, None))
        self.assertEqual(running["line"], "Planning the adoption of r\u2026")


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
        answer = {"id": "contract-draft", "subject": "build-command", "value": "make"}
        self.adopter().plan("/r", answers=[answer], contract="/s/d.json")
        self.adopter().plan("/r", answers=[answer])
        first, second = self.args.read_text().splitlines()[-2:]
        self.assertEqual(first, "plan --repo-root /r --format json --answer contract-draft "
                                "build-command make --contract-draft /s/d.json")
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


class PlatformTest(unittest.TestCase):
    def test_adopter_for(self):
        self.assertIsInstance(register.adopter_for("linux"), Adopter)
        self.assertIsNone(register.adopter_for("darwin"))


if __name__ == "__main__":
    unittest.main()
