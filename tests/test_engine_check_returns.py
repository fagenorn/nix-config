"""`engine check` accepts a call step's `returns` and refuses each one the child cannot honor."""

from __future__ import annotations

import copy
import json
import shutil
import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path

from tests.guard_policy_world import install_platform_manifest_in_environ
from tests.test_engine_check import PROCEDURES, compact, run_check, step

TIER = "integration"

setUpModule = install_platform_manifest_in_environ

KID = {
    "format": 1, "inputs": ["issue", "range"],
    "stops": {"kid-stop": {"need": "retry", "reenter": "scope"}},
    "steps": [
        {"id": "scope", "stage": "setup", "kind": "command", "command": "diff-scope", "holds": "run",
         "in": ["run.range"], "on": {"ok": "draft", "failed": "kid-stop", "refused": "kid-stop"}},
        {"id": "draft", "stage": "building", "kind": "agent", "role": "reviewer", "prompt": "toy-draft.md",
         "reply": "toy-draft.reply.json", "outcome_from": "status", "holds": "run", "in": ["run.issue"],
         "on": {"drafted": "grade", "stuck": "note", "no-reply": "kid-stop", "out-of-bounds": "kid-stop"}},
        {"id": "grade", "stage": "building", "kind": "decide", "grader": "toy-tally", "holds": "run",
         "in": ["draft.summary"], "on": {"accept": "done", "revise": "kid-stop"}},
        {"id": "note", "stage": "building", "kind": "command", "command": "diff-scope", "holds": "run",
         "in": ["run.range"], "on": {"ok": "kid-stop", "failed": "kid-stop", "refused": "kid-stop"}}]}
PARENT = {
    "format": 1, "inputs": ["issue", "range"],
    "stops": {"kid-stop": {"need": "retry", "reenter": "call"},
              "held": {"need": "owner-decision", "reenter": "use"}},
    "steps": [
        {"id": "call", "stage": "building", "kind": "call", "procedure": "kid", "holds": "run",
         "returns": ["draft.summary"], "on": {"done": "use", "kid-stop": "kid-stop"}},
        {"id": "use", "stage": "building", "kind": "agent", "role": "reviewer", "prompt": "toy-draft.md",
         "reply": "toy-draft.reply.json", "outcome_from": "status", "holds": "run",
         "in": ["run.issue", "call.summary"],
         "on": {"drafted": "done", "stuck": "held", "no-reply": "held", "out-of-bounds": "held"}}]}
RECOVER = {"id": "recover", "stage": "building", "kind": "command", "command": "diff-scope", "holds": "run",
           "in": ["run.range"], "on": {"ok": "use", "failed": "kid-stop", "refused": "kid-stop"}}

Change = Callable[[dict, dict], None]


def returning(*paths: str, read: str | None = None) -> Change:
    def change(kid: dict, parent: dict) -> None:
        step(parent, "call")["returns"] = list(paths)
        if read is not None:
            step(parent, "use")["in"] = ["run.issue", read]
    return change


def returning_value(value: object) -> Change:
    def change(kid: dict, parent: dict) -> None:
        step(parent, "call")["returns"] = value
    return change


def per_item(kid: dict, parent: dict) -> None:
    step(parent, "call").update({"in": ["run.issue"], "each": "run.issue"})


def spent_draft_ends_the_child_with_no_reply(kid: dict, parent: dict) -> None:
    draft = step(kid, "draft")
    draft["max_visits"] = 1
    draft["on"].update({"no-reply": "draft", "exhausted": "done"})


def reached_after_the_child_stopped(kid: dict, parent: dict) -> None:
    step(parent, "call")["on"]["kid-stop"] = "recover"
    parent["steps"].insert(1, copy.deepcopy(RECOVER))


def returns_removed(kid: dict, parent: dict) -> None:
    del step(parent, "call")["returns"]
    step(parent, "use")["in"] = ["run.issue"]


def reads_unreturned(kid: dict, parent: dict) -> None:
    del step(parent, "call")["returns"]
    step(parent, "use")["in"] = ["run.issue", "call.summary"]


CALL_INVALID = [("parent", "call", "invalid_field")]
CALL_UNPRODUCED = [("parent", "call", "unproduced_input")]
CALL_UNKNOWN = [("parent", "call", "unknown_member")]
ROWS: list[tuple[str, Change, list[tuple[str, str, str]]]] = [
    ("a string", returning_value("draft.summary"), CALL_INVALID),
    ("an empty list", returning_value([]), CALL_INVALID),
    ("a repeated path", returning("draft.summary", "draft.summary"), CALL_INVALID),
    ("a run path", returning("run.issue"), CALL_INVALID),
    ("one member name twice", returning("draft.summary", "note.summary"), CALL_INVALID),
    ("the reserved name items", returning("draft.items"), CALL_INVALID),
    ("a call with each", per_item, CALL_INVALID),
    ("a step the child lacks", returning("nope.summary"), CALL_UNPRODUCED),
    ("a step off every route to done", returning("note.summary"), CALL_UNPRODUCED),
    ("a step whose spent bound ends the child with no reply", spent_draft_ends_the_child_with_no_reply,
     CALL_UNPRODUCED),
    ("a member the reply lacks", returning("draft.reason", read="call.reason"), CALL_UNKNOWN),
    ("a decide verdict", returning("grade.verdict", read="call.verdict"), CALL_UNKNOWN),
    ("a reader reached after the child stopped", reached_after_the_child_stopped,
     [("parent", "use", "unproduced_input")]),
    ("a read of a member nothing returns", reads_unreturned, [("parent", "use", "unknown_member")]),
]


def refusals_of(kid: dict, parent: dict) -> tuple[int, str]:
    directory = Path(tempfile.mkdtemp(prefix="engine-returns-"))
    unittest.addModuleCleanup(shutil.rmtree, directory, ignore_errors=True)
    for name in ("toy-draft.md", "toy-draft.reply.json"):
        shutil.copy(PROCEDURES / name, directory / name)
    for name, doc in (("kid", kid), ("parent", parent)):
        (directory / f"{name}.json").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    code, out, _ = run_check("--procedures", str(directory))
    return code, out


class ReturnsCheckTest(unittest.TestCase):
    def test_a_call_returning_a_member_its_child_stores_before_done_checks_ok(self):
        self.assertEqual(refusals_of(copy.deepcopy(KID), copy.deepcopy(PARENT)),
                         (0, compact({"procedures": ["kid", "parent"], "verdict": "ok"})))

    def test_each_bad_returns_or_read_is_refused_by_step_and_defect(self):
        for name, change, expected in ROWS:
            with self.subTest(name):
                kid, parent = copy.deepcopy(KID), copy.deepcopy(PARENT)
                change(kid, parent)
                triples = sorted((r["procedure"], r["step"], r["defect"])
                                 for r in json.loads(refusals_of(kid, parent)[1])["refusals"])
                self.assertEqual(triples, sorted(expected))
