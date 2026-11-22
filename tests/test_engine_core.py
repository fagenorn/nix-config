"""Contract tests for the engine core (`agent_tools.delivery.engine_core`, #1510).

The core is a pure function from a procedure, the run inputs and the events so
far to the next action. These cases drive it over the checked toy procedure in
`tests/fixtures/engine-core` and over one-mutation copies of it.
"""

from __future__ import annotations

import ast
import copy
import json
import shutil
import tempfile
import threading
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

from agent_tools.delivery import engine_core, engine_graders, procedure_check
from agent_tools.delivery.engine_core import (
    Done,
    Graded,
    RunCall,
    RunCommand,
    RunGroup,
    StartSession,
    Stop,
    Transition,
    call_outcome,
    next_action,
    replay,
)
from agent_tools.delivery.engine_graders import Grader
from tests.engine_walks import describe, edges, reply_errors, reply_schemas, step_outcomes, walk_edges

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = REPO_ROOT / "tests/fixtures/engine-core"
FAN = REPO_ROOT / "tests/fixtures/engine-fan"
INPUTS = {"holder": "h", "issue": "1510", "range": "a..b", "repo": "o/r"}


def toy() -> dict:
    return json.loads((FIXTURE / "toy-core.json").read_text(encoding="utf-8"))


def step(doc: dict, step_id: str) -> dict:
    return next(item for item in doc["steps"] if item["id"] == step_id)


def pair(step_id: str, outcome: str, result: object = None) -> list:
    outcome_event = {"type": "outcome", "step": step_id, "outcome": outcome}
    if result is not None:
        outcome_event["result"] = result
    return [{"type": "entered", "step": step_id}, outcome_event]


def draft_with(items: object) -> list:
    return pair("draft", "drafted", {"status": "drafted", "summary": "s", "items": items})


def entries(*ends: str) -> list[dict]:
    return [{"end": end, "item": item, "run": RUN} for end, item in zip(ends, ("x", "y", "z"))]


RUN = "1-20261121T000000Z-aaaa"
D = draft_with(["x", "y", "z"])
G = [{"type": "entered", "step": "checks"}]
MEMBERS_PASS = pair("lint", "ok") + pair("claim", "free")
LINT = RunCommand("lint", 1, "diff-scope", None, (("run.range", "a..b"),))
CLAIM = RunCommand("claim", 1, "forge-claim", "status", (("run.repo", "o/r"), ("run.issue", "1510"), ("run.holder", "h")))
FAN_CALL = RunCall("fan", 1, "toy-fan-child", ("x", "y", "z"), 2, (("draft.items", ["x", "y", "z"]),))


def refusals(doc: dict, draft_outcomes: tuple[str, ...] = ()) -> tuple:
    """The checker's refusals of `doc` beside the fixture's prompts, its draft reply enum widened by `draft_outcomes`."""
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp)
        for source in FIXTURE.iterdir():
            shutil.copy(source, directory / source.name)
        reply = json.loads((directory / "draft.reply.json").read_text(encoding="utf-8"))
        reply["properties"]["status"]["enum"] += list(draft_outcomes)
        (directory / "draft.reply.json").write_text(json.dumps(reply), encoding="utf-8")
        (directory / "toy-core.json").write_text(json.dumps(doc), encoding="utf-8")
        return procedure_check.check_directory(directory, procedure_check.load_commands()).refusals


def fan() -> dict:
    return json.loads((FAN / "toy-fan.json").read_text(encoding="utf-8"))


def fan_refusals(doc: dict) -> tuple:
    """The checker's refusals of the fan `doc` beside the fan fixture's prompts and child."""
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp)
        for source in FAN.iterdir():
            shutil.copy(source, directory / source.name)
        (directory / "toy-fan.json").write_text(json.dumps(doc), encoding="utf-8")
        return procedure_check.check_directory(directory, procedure_check.load_commands()).refusals


STOP = Stop(name="needs-owner", need="owner-decision", reenter="draft")


class ToyTest(unittest.TestCase):
    def test_the_core_toy_is_a_checked_procedure(self) -> None:
        result = procedure_check.check_directory(FIXTURE, procedure_check.load_commands())
        self.assertEqual(result.refusals, ())
        self.assertEqual(result.procedures, ("toy-core",))


class ActionTest(unittest.TestCase):
    def test_no_events_runs_the_first_command(self) -> None:
        self.assertEqual(
            next_action(toy(), INPUTS, []),
            RunCommand(step="scope", visit=1, command="diff-scope", subcommand=None, args=(("run.range", "a..b"),)),
        )

    def test_an_entered_step_returns_the_same_action(self) -> None:
        self.assertEqual(
            next_action(toy(), INPUTS, [{"type": "entered", "step": "scope"}]),
            next_action(toy(), INPUTS, []),
        )

    def test_an_agent_step_starts_a_session(self) -> None:
        self.assertEqual(
            next_action(toy(), INPUTS, pair("scope", "ok")),
            StartSession(
                step="draft",
                visit=1,
                role="implementer",
                prompt="draft.md",
                reply="draft.reply.json",
                args=(("run.issue", "1510"),),
            ),
        )

    def test_args_read_the_latest_result(self) -> None:
        events = (
            pair("scope", "ok")
            + pair("draft", "stuck", {"status": "stuck", "summary": "s1"})
            + pair("draft", "drafted", {"status": "drafted", "summary": "s2"})
        )
        self.assertEqual(
            next_action(toy(), INPUTS, events),
            StartSession(
                step="review",
                visit=1,
                role="reviewer",
                prompt="review.md",
                reply="review.reply.json",
                args=(("draft.summary", "s2"),),
            ),
        )

    def test_a_decide_step_publishes_its_verdict(self) -> None:
        doc = toy()
        step(doc, "tally")["on"]["accept"] = "publish"
        doc["steps"].append(
            {"id": "publish", "stage": "final review", "kind": "command", "command": "diff-scope",
             "in": ["tally.verdict"], "on": {"ok": "done", "failed": "needs-owner"}}
        )
        self.assertEqual(refusals(doc), ())
        events = (
            pair("scope", "ok")
            + pair("draft", "drafted", {"summary": "s"})
            + pair("review", "approve", {"verdict": "approve"})
        )
        self.assertEqual(
            next_action(doc, INPUTS, events),
            RunCommand(step="publish", visit=1, command="diff-scope", subcommand=None, args=(("tally.verdict", "accept"),)),
        )

    def test_a_decide_step_publishes_nothing_but_its_verdict(self) -> None:
        doc = toy()
        step(doc, "tally")["on"]["accept"] = "publish"
        doc["steps"].append(
            {"id": "publish", "stage": "final review", "kind": "command", "command": "diff-scope",
             "in": ["tally.score"], "on": {"ok": "done", "failed": "needs-owner"}}
        )
        self.assertEqual([(item.step, item.defect) for item in refusals(doc)], [("publish", "unknown_member")])

    def test_an_outcome_is_followed_to_a_stop(self) -> None:
        result = replay(toy(), INPUTS, pair("scope", "failed"))
        self.assertEqual(result.action, STOP)
        self.assertEqual(result.transitions, (Transition("scope", "failed", "needs-owner"),))

    def test_an_approved_review_is_done(self) -> None:
        events = (
            pair("scope", "ok")
            + pair("draft", "drafted", {"summary": "s"})
            + pair("review", "approve", {"verdict": "approve"})
        )
        result = replay(toy(), INPUTS, events)
        self.assertEqual(result.action, Done())
        self.assertEqual(result.transitions[-1], Transition("tally", "accept", "done"))

    def test_shell_outcomes_are_ordinary(self) -> None:
        for outcome in ("no-reply", "out-of-bounds", "refused"):
            with self.subTest(outcome=outcome):
                doc = toy()
                step(doc, "draft")["on"][outcome] = "needs-owner"
                self.assertEqual(refusals(doc, (outcome,)), ())
                result = replay(doc, INPUTS, pair("scope", "ok") + pair("draft", outcome))
                self.assertEqual(result.action, STOP)
                self.assertEqual(result.transitions[-1], Transition("draft", outcome, "needs-owner"))


class GroupTest(unittest.TestCase):
    def test_a_group_runs_its_members_beside_each_other(self) -> None:
        self.assertEqual(fan_refusals(fan()), ())
        self.assertEqual(next_action(fan(), INPUTS, D), RunGroup("checks", 1, (LINT, CLAIM)))
        self.assertEqual(next_action(fan(), INPUTS, D + G), RunGroup("checks", 1, (LINT, CLAIM)))

    def test_a_reported_member_leaves_the_group_action(self) -> None:
        self.assertEqual(next_action(fan(), INPUTS, D + G + pair("lint", "ok")), RunGroup("checks", 1, (CLAIM,)))

    def test_a_group_passes_when_every_member_outcome_is_in_its_pass_set(self) -> None:
        for claim in ("free", "held_by"):
            with self.subTest(claim=claim):
                result = replay(fan(), INPUTS, D + G + pair("lint", "ok") + pair("claim", claim))
                self.assertEqual(result.action, FAN_CALL)
                self.assertIn(Transition("checks", "pass", "fan"), result.transitions)

    def test_a_group_is_blocked_when_one_member_outcome_is_outside_its_pass_set(self) -> None:
        result = replay(fan(), INPUTS, D + G + pair("lint", "failed") + pair("claim", "free"))
        self.assertIn(Transition("checks", "blocked", "checks"), result.transitions)
        self.assertEqual(
            result.action,
            RunGroup("checks", 2, (replace(LINT, visit=2), replace(CLAIM, visit=2))),
        )

    def test_member_outcomes_arrive_in_any_order(self) -> None:
        shuffled = (
            D
            + G
            + [{"type": "entered", "step": "lint"}, {"type": "entered", "step": "claim"}]
            + [{"type": "outcome", "step": "claim", "outcome": "free"}]
            + [{"type": "outcome", "step": "lint", "outcome": "ok"}]
        )
        self.assertEqual(replay(fan(), INPUTS, shuffled), replay(fan(), INPUTS, D + G + MEMBERS_PASS))
        self.assertEqual(next_action(fan(), INPUTS, shuffled), FAN_CALL)

    def test_a_member_result_is_read_under_the_member_id(self) -> None:
        doc = fan()
        step(doc, "once")["in"] = ["claim.verdict"]
        self.assertEqual(fan_refusals(doc), ())
        events = D + G + pair("lint", "ok") + pair("claim", "free", {"verdict": "free"})
        events += pair("fan", "done", {"items": entries("done", "done", "done")})
        self.assertEqual(
            next_action(doc, INPUTS, events),
            RunCall("once", 1, "toy-fan-child", None, 1, (("claim.verdict", "free"),)),
        )

    def test_a_member_past_its_bound_is_exhausted_and_blocks_the_group(self) -> None:
        doc = fan()
        step(doc, "lint")["max_visits"] = 1
        self.assertEqual(fan_refusals(doc), ())
        blocked = D + G + pair("lint", "failed") + pair("claim", "free")
        self.assertEqual(
            next_action(doc, INPUTS, blocked),
            RunGroup("checks", 2, (replace(CLAIM, visit=2),)),
        )
        result = replay(doc, INPUTS, blocked + G + pair("claim", "free"))
        self.assertEqual(
            result.transitions[-3:],
            (
                Transition("checks", "blocked", "checks"),
                Transition("checks", "blocked", "checks"),
                Transition("checks", "exhausted", "needs-owner"),
            ),
        )
        self.assertEqual(result.action, Stop("needs-owner", "owner-decision", "draft"))
        self.assertEqual(
            result.graded,
            (Graded("checks", 1, "blocked", "checks"), Graded("checks", 2, "blocked", "checks")),
        )

    def test_each_group_grade_is_named_with_its_visit(self) -> None:
        failed = G + pair("lint", "failed") + pair("claim", "free")
        first = replay(fan(), INPUTS, D + failed)
        self.assertEqual(first.graded, (Graded("checks", 1, "blocked", "checks"),))
        second = replay(fan(), INPUTS, D + failed + failed)
        self.assertEqual(
            second.graded,
            (Graded("checks", 1, "blocked", "checks"), Graded("checks", 2, "blocked", "checks")),
        )
        self.assertEqual(second.transitions[-1], Transition("checks", "exhausted", "needs-owner"))
        self.assertNotIn("exhausted", [grade.outcome for grade in second.graded])

    def test_a_group_of_decide_members_is_graded_with_no_action(self) -> None:
        doc = decide_member()
        del step(doc, "checks")["members"][1]
        doc["steps"] = [item for item in doc["steps"] if item["id"] != "claim"]
        self.assertEqual(fan_refusals(doc), ())
        result = replay(doc, INPUTS, summarised("approve"))
        self.assertEqual(result.action, FAN_CALL)
        self.assertEqual(result.graded, (Graded("checks", 1, "pass", "fan"),))

    def test_a_decide_member_is_graded_when_its_group_is_entered(self) -> None:
        doc = decide_member()
        self.assertEqual(fan_refusals(doc), ())
        self.assertEqual(next_action(doc, INPUTS, summarised("approve")), RunGroup("checks", 1, (CLAIM,)))
        passed = replay(doc, INPUTS, summarised("approve") + G + pair("claim", "free"))
        self.assertEqual(passed.action, FAN_CALL)
        blocked = replay(doc, INPUTS, summarised("s") + G + pair("claim", "free"))
        self.assertIn(Transition("checks", "blocked", "checks"), blocked.transitions)
        self.assertEqual(blocked.graded, (Graded("checks", 1, "blocked", "checks"),))

    def test_a_group_with_an_input_that_has_no_value_raises_before_any_member_runs(self) -> None:
        doc = fan()
        step(doc, "checks")["in"] = ["draft.ghost"]
        with self.assertRaises(engine_core.CoreError):
            replay(doc, INPUTS, D)

    def test_a_walk_that_raises_after_a_group_grade_reports_the_grade(self) -> None:
        doc = fan()
        step(doc, "fan")["each"] = "draft.status"
        with self.assertRaises(engine_core.CoreError) as raised:
            replay(doc, INPUTS, D + G + MEMBERS_PASS)
        self.assertEqual(raised.exception.graded, (Graded("checks", 1, "pass", "fan"),))


def summarised(summary: str) -> list:
    return pair("draft", "drafted", {"status": "drafted", "summary": summary, "items": ["x", "y", "z"]})


def decide_member() -> dict:
    doc = fan()
    doc["steps"][2] = {"id": "lint", "stage": "final review", "kind": "decide", "grader": "toy-tally",
                       "in": ["draft.summary"], "max_visits": 2}
    step(doc, "checks")["members"][0] = {"step": "lint", "pass": ["accept"]}
    return doc


class CallTest(unittest.TestCase):
    def test_a_call_over_a_list_returns_its_items_and_bound(self) -> None:
        self.assertEqual(next_action(fan(), INPUTS, D + G + MEMBERS_PASS), FAN_CALL)
        self.assertEqual(next_action(fan(), INPUTS, D + G + MEMBERS_PASS + [{"type": "entered", "step": "fan"}]), FAN_CALL)
        stopped = D + G + MEMBERS_PASS + pair("fan", "child-stop", {"items": entries("done", "child-stop", "done")})
        self.assertEqual(next_action(fan(), INPUTS, stopped), Stop("needs-owner", "owner-decision", "draft"))

    def test_a_call_without_each_runs_once(self) -> None:
        events = D + G + MEMBERS_PASS + pair("fan", "done", {"items": entries("done", "done", "done")})
        self.assertEqual(next_action(fan(), INPUTS, events), RunCall("once", 1, "toy-fan-child", None, 1, ()))
        once = pair("once", "done", {"items": [{"end": "done", "item": None, "run": RUN}]})
        self.assertEqual(next_action(fan(), INPUTS, events + once), Done())

    def test_a_call_over_an_empty_list_has_no_items_and_is_done(self) -> None:
        empty = draft_with([]) + G + MEMBERS_PASS
        self.assertEqual(next_action(fan(), INPUTS, empty), RunCall("fan", 1, "toy-fan-child", (), 2, (("draft.items", []),)))
        events = empty + pair("fan", "done", {"items": []})
        self.assertEqual(next_action(fan(), INPUTS, events), RunCall("once", 1, "toy-fan-child", None, 1, ()))

    def test_call_outcome_is_done_or_the_first_stop_in_list_order(self) -> None:
        self.assertEqual(call_outcome([]), "done")
        self.assertEqual(call_outcome(["done", "done"]), "done")
        self.assertEqual(call_outcome(["done", "b-stop", "a-stop"]), "b-stop")
        self.assertEqual(call_outcome(["a-stop"]), "a-stop")


class VisitTest(unittest.TestCase):
    def test_the_entry_past_max_visits_is_exhausted(self) -> None:
        events = pair("scope", "ok") + pair("draft", "stuck")
        second = next_action(toy(), INPUTS, events)
        self.assertIsInstance(second, StartSession)
        self.assertEqual((second.step, second.visit), ("draft", 2))
        result = replay(toy(), INPUTS, events + pair("draft", "stuck"))
        self.assertEqual(result.action, STOP)
        self.assertNotIsInstance(result.action, (RunCommand, StartSession))
        self.assertEqual(
            result.transitions[-2:],
            (Transition("draft", "stuck", "draft"), Transition("draft", "exhausted", "needs-owner")),
        )

    def test_max_visits_defaults_to_one(self) -> None:
        doc = toy()
        del step(doc, "draft")["max_visits"]
        result = replay(doc, INPUTS, pair("scope", "ok") + pair("draft", "stuck"))
        self.assertEqual(result.action, STOP)
        self.assertEqual(result.transitions[-1], Transition("draft", "exhausted", "needs-owner"))

    def test_an_entry_past_the_exhausted_entry_raises(self) -> None:
        doc = toy()
        step(doc, "draft")["on"]["exhausted"] = "draft"
        events = pair("scope", "ok") + pair("draft", "stuck") * 2
        caught: list[BaseException] = []

        def run() -> None:
            try:
                replay(doc, INPUTS, events)
            except BaseException as error:  # noqa: BLE001 - the thread reports what it raised
                caught.append(error)

        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        worker.join(timeout=10)
        self.assertFalse(worker.is_alive())
        self.assertEqual(len(caught), 1)
        self.assertIsInstance(caught[0], engine_core.CoreError)


class DecideTest(unittest.TestCase):
    def test_a_decide_step_follows_its_grader(self) -> None:
        for returned in ("revise", "accept"):
            with self.subTest(returned=returned):
                calls: list[dict] = []
                recorder = Grader(("accept", "revise"), lambda values: calls.append(dict(values)) or returned)
                events = (
                    pair("scope", "ok")
                    + pair("draft", "drafted", {"summary": "s"})
                    + pair("review", "approve", {"verdict": "seen"})
                )
                with mock.patch.dict(engine_graders.GRADERS, {"toy-tally": recorder}):
                    result = replay(toy(), INPUTS, events)
                self.assertEqual(calls, [{"review.verdict": "seen"}])
                if returned == "revise":
                    self.assertEqual(result.action, STOP)
                    self.assertEqual(result.transitions[-1], Transition("tally", "revise", "needs-owner"))
                else:
                    self.assertEqual(result.action, Done())

    def test_the_toy_grader_reads_the_result_not_the_outcome(self) -> None:
        prefix = pair("scope", "ok") + pair("draft", "drafted", {"summary": "s"})
        revised = prefix + pair("review", "approve", {"verdict": "revise"})
        approved = prefix + pair("review", "approve", {"verdict": "approve"})
        self.assertEqual(next_action(toy(), INPUTS, revised), STOP)
        self.assertEqual(next_action(toy(), INPUTS, approved), Done())


class EventErrorTest(unittest.TestCase):
    def test_an_unknown_event_type_raises(self) -> None:
        cases = (
            [{"type": "step-skipped", "step": "scope"}],
            pair("scope", "ok") + [{"type": "note"}],
            ["entered"],
        )
        for index, events in enumerate(cases):
            with self.subTest(index=index):
                with self.assertRaises(engine_core.CoreError) as caught:
                    next_action(toy(), INPUTS, events)
                if index == 0:
                    self.assertIn("step-skipped", str(caught.exception))

    def test_each_bad_sequence_raises(self) -> None:
        exhausted_draft = pair("scope", "ok") + pair("draft", "exhausted")
        table = (
            ("outcome before entered", toy(), INPUTS, [{"type": "outcome", "step": "scope", "outcome": "ok"}]),
            ("entered for another step", toy(), INPUTS, [{"type": "entered", "step": "draft"}]),
            ("entered twice", toy(), INPUTS, [{"type": "entered", "step": "scope"}] * 2),
            (
                "outcome for another step",
                toy(),
                INPUTS,
                [
                    {"type": "entered", "step": "scope"},
                    {"type": "outcome", "step": "draft", "outcome": "drafted"},
                ],
            ),
            (
                "event after the run stopped",
                toy(),
                INPUTS,
                pair("scope", "failed") + [{"type": "entered", "step": "draft"}],
            ),
            ("reported exhausted", toy(), INPUTS, exhausted_draft),
            ("unmapped outcome", toy(), INPUTS, pair("scope", "maybe")),
            ("result not an object", toy(), INPUTS, pair("scope", "ok", ["x"])),
            (
                "missing result member",
                toy(),
                INPUTS,
                pair("scope", "ok") + pair("draft", "drafted", {"status": "drafted"}),
            ),
            (
                "missing member resolved before a later approval",
                toy(),
                INPUTS,
                pair("scope", "ok") + pair("draft", "drafted", {"status": "drafted"}) + pair("review", "approve", {"verdict": "approve"}),
            ),
            ("missing run input", toy(), {}, []),
            ("a member entered before its group", fan(), INPUTS, D + [{"type": "entered", "step": "lint"}]),
            ("a member entered twice", fan(), INPUTS, D + G + [{"type": "entered", "step": "lint"}] * 2),
            (
                "a member outcome before its entered",
                fan(),
                INPUTS,
                D + G + [{"type": "outcome", "step": "lint", "outcome": "ok"}],
            ),
            (
                "an outcome naming the group",
                fan(),
                INPUTS,
                D + G + [{"type": "outcome", "step": "checks", "outcome": "pass"}],
            ),
            ("an event naming a step outside the group", fan(), INPUTS, D + G + [{"type": "entered", "step": "fan"}]),
            ("a member reporting exhausted", fan(), INPUTS, D + G + pair("lint", "exhausted")),
            (
                "each not a list",
                fan(),
                INPUTS,
                draft_with("x") + G + MEMBERS_PASS,
            ),
            (
                "an item that is an object",
                fan(),
                INPUTS,
                draft_with(["approve", {"id": 2}]) + G + MEMBERS_PASS,
            ),
            (
                "an item that is a boolean",
                fan(),
                INPUTS,
                draft_with([True]) + G + MEMBERS_PASS,
            ),
            (
                "a call outcome that disagrees with its ends",
                fan(),
                INPUTS,
                D + G + MEMBERS_PASS + pair("fan", "child-stop", {"items": entries("done", "done", "done")}),
            ),
            (
                "a call result with a wrong entry count",
                fan(),
                INPUTS,
                D + G + MEMBERS_PASS + pair("fan", "done", {"items": []}),
            ),
            ("a member that is a call step", call_member(), INPUTS, D),
        )
        for name, doc, inputs, events in table:
            with self.subTest(name=name):
                before = copy.deepcopy((doc, inputs, events))
                with self.assertRaises(engine_core.CoreError):
                    next_action(doc, inputs, events)
                self.assertEqual((doc, inputs, events), before)


def call_member() -> dict:
    doc = fan()
    step(doc, "lint").update(kind="call", procedure="toy-fan-child")
    del step(doc, "lint")["command"], step(doc, "lint")["in"]
    return doc


PURE_CALLS = {"open", "exec", "eval", "compile", "__import__", "input", "breakpoint"}


def impure(source: str, allowed: set[str]) -> list[str]:
    """Every import outside `allowed` and every call of a builtin that reads or runs code, sorted."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                found.add(".")
            elif node.module.startswith("agent_tools"):
                found.update(f"{node.module}.{alias.name}" for alias in node.names)
            else:
                found.add(node.module)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in PURE_CALLS:
            found.add(f"call:{node.func.id}")
    return sorted(name for name in found if name not in allowed)


def toy_coverage():
    return walk_edges(toy(), INPUTS, step_outcomes(FIXTURE, "toy-core"), reply_schemas(FIXTURE, "toy-core"))


class WalkTest(unittest.TestCase):
    def test_the_walks_take_every_edge_of_the_toy(self) -> None:
        doc = toy()
        coverage = toy_coverage()
        self.assertEqual(coverage.unwalked, ())
        self.assertEqual([(w.edge.step, w.edge.outcome) for w in coverage.walks], list(edges(doc)))
        for walk in coverage.walks:
            self.assertTrue(walk.end == "done" or walk.end in doc["stops"])
            print(describe(walk))
        self.assertEqual(
            [describe(walk) for walk in coverage.walks],
            [
                "scope:ok -> draft | scope=ok draft=drafted review=approve => done",
                "scope:failed -> needs-owner | scope=failed => needs-owner",
                "draft:drafted -> review | scope=ok draft=drafted review=approve => done",
                "draft:stuck -> draft | scope=ok draft=stuck draft=stuck => needs-owner",
                "draft:exhausted -> needs-owner | scope=ok draft=stuck draft=stuck => needs-owner",
                "review:approve -> tally | scope=ok draft=drafted review=approve => done",
                "review:revise -> tally | scope=ok draft=drafted review=revise => needs-owner",
                "tally:accept -> done | scope=ok draft=drafted review=approve => done",
                "tally:revise -> needs-owner | scope=ok draft=drafted review=revise => needs-owner",
            ],
        )

    def test_the_walks_take_every_edge_of_the_fan_toy(self) -> None:
        doc = fan()
        self.assertEqual(fan_refusals(doc), ())
        coverage = walk_edges(doc, INPUTS, step_outcomes(FAN, "toy-fan"), reply_schemas(FAN, "toy-fan"))
        self.assertEqual(coverage.unwalked, ())
        self.assertEqual([(w.edge.step, w.edge.outcome) for w in coverage.walks], list(edges(doc)))
        wanted = edges(doc)
        for edge in (
            ("checks", "pass"),
            ("checks", "blocked"),
            ("checks", "exhausted"),
            ("fan", "done"),
            ("fan", "child-stop"),
            ("once", "done"),
            ("once", "child-stop"),
        ):
            self.assertIn(edge, wanted)
        self.assertEqual([edge for edge in wanted if edge[0] in ("lint", "claim")], [])
        for walk in coverage.walks:
            self.assertTrue(walk.end == "done" or walk.end in doc["stops"])
        stop = next(w for w in coverage.walks if (w.edge.step, w.edge.outcome) == ("fan", "child-stop"))
        reported = {e["step"]: e["result"] for e in stop.events if e["type"] == "outcome"}
        self.assertTrue(reported["draft"]["items"])
        ends = [entry["end"] for entry in reported["fan"]["items"]]
        self.assertEqual(len(ends), len(reported["draft"]["items"]))
        self.assertEqual(call_outcome(ends), "child-stop")

    def test_the_walks_report_schema_valid_replies(self) -> None:
        expected = {
            "draft": {"status": "drafted", "summary": "draft.summary", "items": []},
            "review": {"verdict": "approve", "notes": "x"},
        }
        schemas = reply_schemas(FIXTURE, "toy-core")
        seen: set[str] = set()
        for walk in toy_coverage().walks:
            for event in walk.events:
                if event["type"] == "outcome" and event["step"] in schemas:
                    result = event["result"]
                    self.assertEqual(reply_errors(schemas[event["step"]], result), [])
                    self.assertEqual(sorted(result), sorted(expected[event["step"]]))
                    self.assertEqual(result[next(iter(expected[event["step"]]))], event["outcome"])
                    seen.add(event["step"])
        self.assertEqual(seen, set(expected))

    def test_a_reply_the_schema_rejects_is_refused(self) -> None:
        schema = reply_schemas(FIXTURE, "toy-core")["draft"]
        self.assertNotEqual(reply_errors(schema, {"status": "drafted", "summary": "s"}), [])
        self.assertNotEqual(reply_errors(schema, {"status": "other", "summary": "s", "items": []}), [])
        self.assertNotEqual(reply_errors(schema, {"status": "drafted", "summary": 1, "items": []}), [])
        self.assertEqual(reply_errors(schema, {"status": "drafted", "summary": "s", "items": ["a"]}), [])

    def test_an_edge_no_walk_takes_is_reported(self) -> None:
        doc = toy()
        step(doc, "scope")["on"]["error"] = "needs-owner"
        coverage = walk_edges(doc, INPUTS, step_outcomes(FIXTURE, "toy-core"), reply_schemas(FIXTURE, "toy-core"))
        self.assertEqual(coverage.unwalked, (("scope", "error"),))


class PurityTest(unittest.TestCase):
    def test_the_core_returns_the_same_action_for_the_same_inputs(self) -> None:
        doc = toy()
        for walk in toy_coverage().walks:
            for k in range(len(walk.events) + 1):
                with self.subTest(edge=describe(walk), k=k):
                    events = list(walk.events[:k])
                    snapshot = copy.deepcopy((doc, INPUTS, events))
                    first = next_action(*copy.deepcopy((doc, INPUTS, events)))
                    second = next_action(*copy.deepcopy((doc, INPUTS, events)))
                    third = next_action(doc, INPUTS, events)
                    self.assertEqual(first, second)
                    self.assertEqual(first, third)
                    self.assertEqual((doc, INPUTS, events), snapshot)

    def test_the_core_imports_only_pure_modules(self) -> None:
        delivery = REPO_ROOT / "python/agent_tools/delivery"
        core = (delivery / "engine_core.py").read_text(encoding="utf-8")
        graders = (delivery / "engine_graders.py").read_text(encoding="utf-8")
        common = {"__future__", "dataclasses", "typing", "collections.abc"}
        self.assertEqual(impure(core, common | {"agent_tools.delivery.engine_graders"}), [])
        self.assertEqual(impure(graders, common), [])

    def test_the_purity_check_refuses_an_impure_source(self) -> None:
        allowed = {"__future__", "dataclasses", "typing"}
        sources = (
            "import time",
            "from datetime import datetime",
            "from pathlib import Path",
            "import subprocess",
            "import os.path",
            "import random",
            "from . import engine_graders",
            "from agent_tools.delivery import procedure_check",
            "open('f')",
            "__import__('os')",
        )
        for source in sources:
            with self.subTest(source=source):
                self.assertNotEqual(impure(source, allowed), [])
        self.assertEqual(impure("from dataclasses import dataclass", {"dataclasses"}), [])


if __name__ == "__main__":
    unittest.main()
