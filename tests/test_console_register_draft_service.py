"""A drafted registration's derived values through the service.

A refusal of a value the platform derives, or of the project id adoption derived, is the plan's
failed row with its retry card, on the registration run and on the answer of the last question
alike; no drafted field reopens for it. A saved draft of an earlier table gets its facts from a
fresh reading before it plans. The cases live beside `test_console_register_service.py` because
that file is over its size limit and may not grow; its fakes and helpers are imported from it.

Run: just agent-workflow-tests
"""

from __future__ import annotations

import contextlib
import io
import json

from agent_tools.console import contract_draft, event_log, register

from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures
from .test_console_register_service import READ_ALL, DraftCase, Fake, answer_of, git_repo

TIER = "integration"  # every case runs a real git repository and a started service

FACT_ERROR = {"error": {
    "code": "adopt_failure", "repair_id": "adopt.draft.invalid",
    "violations": [{"pointer": "/platform",
                    "message": "cannot be derived: devenv.lock could not be read"}]}}
LINT_ERROR = {"error": {
    "code": "adopt_failure", "repair_id": "adopt.draft.invalid",
    "violations": [{"pointer": "/bindings/commands/lint/argv", "message": "must not be empty"}]}}
READ_ONLY_LINT_OPEN = {**READ_ALL, "texts": {"justfile": "test:\n\techo t\n"}}
READ_HOMES = {**READ_ALL, "files": [*READ_ALL["files"], "docs/CONTEXT-MAP.md"]}
REGISTRATION_ERROR = "console: registration_error "
READY = {
    "plan": {"state": "ready", "outcome": "reconcile", "project_id": "o/r", "blockers": [],
             "plan_id": "sha256:" + "b" * 64},
    "decisions": {"open": [], "recommended": [], "answered": []},
    "changes": [{"op": "write-file", "sources": [], "targets": [".agents/project.json"]}],
    "link_rewrites": {"inbound": {"links": 0, "files": []}, "outbound": {"links": 0, "files": []},
                      "unrewritable": [], "already_broken": 0},
    "path_references": [], "handoff": {"next_command": None}}


class Keeping(Fake):
    """A `Fake` that keeps the contract file its plan was given, which is gone when the plan returns."""

    drafted = None

    def plan(self, root, cancel=None, answers=(), contract=None, environment=None):
        self.drafted = None if contract is None else json.loads(open(contract).read())
        return super().plan(root, cancel=cancel, answers=answers, contract=contract,
                            environment=environment)


class FactRefusalTest(DraftCase):
    def failure_cards(self):
        return [i for i in self.view()["inbox"]["open"] if i["reason"] == "register_failed"]

    def assert_failed_with_retry(self, row):
        self.assertEqual((row["result"], row["draft"], row["questions"]), ("failed", None, []))
        (card,) = self.failure_cards()
        self.assertEqual([o["label"] if isinstance(o, dict) else o
                          for o in card["questions"][0]["options"]], ["Try again", "Not now"])

    def test_a_not_derivable_refusal_is_a_failure_row_with_retry(self):
        fake = Fake(plan=FACT_ERROR)
        self.begin(fake, draft_reader=lambda root: READ_ALL)
        repo = git_repo(self.parent / "r", contract=False)
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            self.assertEqual(self.post({"path": str(repo)})[0], 204)
            row = self.settled_row(repo)
        self.assertEqual(fake.calls, [("plan", str(repo))])
        self.assert_failed_with_retry(row)
        logged = [json.loads(line[len(REGISTRATION_ERROR):]) for line in errors.getvalue().splitlines()
                  if line.startswith(REGISTRATION_ERROR)]
        self.assertEqual(logged, [{"root": str(repo), "verb": "plan", "error": FACT_ERROR["error"]}])

    def test_a_refusal_of_a_drafted_value_still_reopens_its_card(self):
        self.begin(Fake(plan=LINT_ERROR), draft_reader=lambda root: READ_ALL)
        reg = self.registered(git_repo(self.parent / "r", contract=False))
        self.assertEqual(reg["result"], "drafting")
        (question,) = reg["questions"]
        self.assertEqual((question["subject"], question["why"]),
                         ("lint-command", "The plan refused the lint command: must not be empty"))
        self.assertEqual(self.failure_cards(), [])

    def test_a_saved_draft_without_facts_gets_them_before_it_plans(self):
        repo = git_repo(self.parent / "r", contract=False)
        earlier = []
        for field in ("project-id", "default-branch", "integration-branch", "test-command", "release"):
            value, source = {"project-id": ("o/r", "remote"), "default-branch": ("trunk", "remote"),
                             "integration-branch": (None, None),
                             "test-command": ("make test", "files"),
                             "release": ("unsupported", "start")}[field]
            earlier.append({"field": field, "label": "old", "value": value, "source": source,
                            "options": [], "text": True, "reason": None, "ask": "Its remote did not say"})
        saved = register.drafting(str(repo), earlier)
        self.store.parent.mkdir(parents=True, exist_ok=True)
        log = event_log.EventLog(self.store)
        try:
            log.append([register.ended(saved)])
        finally:
            getattr(log, "close", lambda: None)()
        fake = Keeping(plan=READY)
        self.begin(fake, draft_reader=lambda root: READ_HOMES)
        shown = self.view()["registration"]
        self.assertEqual([q["subject"] for q in shown["questions"]], ["lint-command"])
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            row = self.answered_draft(shown["plan_id"], "lint-command", "make lint")
        self.assertEqual((row["result"], row["state"]), ("planned", "ready"))
        capabilities = fake.drafted["capabilities"]
        self.assertEqual(
            {name: capabilities[name]["support"] for name in capabilities if name.startswith("knowledge.")},
            {"knowledge.context": "supported", "knowledge.standards": "unsupported",
             "knowledge.architecture": "unsupported", "knowledge.hints": "unsupported"})
        self.assertEqual(fake.drafted["bindings"]["commands"]["test"], {"argv": ["make", "test"]})
        stored = self.rows(event_log.REGISTRATION_ENDED)[-1][1]["draft"]
        self.assertEqual([f["field"] for f in stored], [*contract_draft.FIELDS, *contract_draft.FACTS])

    def test_answering_the_last_question_with_an_underivable_fact_is_a_failure_row_with_retry(self):
        fake = Fake(plan=FACT_ERROR)
        self.begin(fake, draft_reader=lambda root: READ_ONLY_LINT_OPEN)
        repo = git_repo(self.parent / "r", contract=False)
        drafting = self.registered(repo)
        self.assertEqual([q["subject"] for q in drafting["questions"]], ["lint-command"])
        self.assertEqual(fake.calls, [])
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            status, _, _ = self.answer(answer_of(drafting["plan_id"], {
                "id": contract_draft.QUESTION_ID, "subject": "lint-command", "value": "just lint"}))
            self.assertEqual(status, 204)
            row = self.wait_for(lambda r: r["status"] == "done" and r["result"] == "failed")
        self.assertEqual(fake.calls, [("plan", str(repo))])
        self.assertEqual(row["result"], "failed")
        self.assertIsNone(row["refusal"])
        self.assertIsNone(self.svc._answer_refusal)
        self.assert_failed_with_retry(self.rows(event_log.REGISTRATION_ENDED)[-1][1])
