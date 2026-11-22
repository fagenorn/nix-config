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
from pathlib import Path
from unittest import mock

from agent_tools.delivery import engine_core, engine_graders, procedure_check
from agent_tools.delivery.engine_core import (
    Done,
    Reentry,
    RunCommand,
    StartSession,
    Stop,
    Transition,
    next_action,
    reentry,
    replay,
)
from agent_tools.delivery.engine_graders import Grader
from tests.engine_walks import describe, edges, reply_errors, reply_schemas, step_outcomes, walk_edges

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = REPO_ROOT / "tests/fixtures/engine-core"
SHIPPED_TOY = REPO_ROOT / "python/agent_tools/delivery/procedures/toy.json"
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
             "holds": "run", "in": ["tally.verdict"], "on": {"ok": "done", "failed": "needs-owner"}}
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
             "holds": "run", "in": ["tally.score"], "on": {"ok": "done", "failed": "needs-owner"}}
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


DRAFTED = {"status": "drafted", "summary": "s"}
E1 = (
    pair("scope", "ok")
    + pair("draft", "drafted", DRAFTED)
    + [
        {"type": "entered", "step": "review"},
        {"type": "outcome", "step": "review", "outcome": "revise", "result": {"verdict": "revise"}, "head": "h1"},
    ]
)
DONE_EVENTS = (
    pair("scope", "ok") + pair("draft", "drafted", DRAFTED) + pair("review", "approve", {"verdict": "approve"})
)


def C(step_id: str, visit: int | None) -> dict:
    return {"type": "continued", "step": step_id, "visit": visit}


def DRAFT(visit: int) -> StartSession:
    return StartSession(
        step="draft",
        visit=visit,
        role="implementer",
        prompt="draft.md",
        reply="draft.reply.json",
        args=(("run.issue", "1510"),),
    )


def SCOPE(visit: int, recheck: bool = False) -> RunCommand:
    return RunCommand(
        step="scope",
        visit=visit,
        command="diff-scope",
        subcommand=None,
        args=(("run.range", "a..b"),),
        recheck=recheck,
    )


def M(visit: int, recheck: bool) -> RunCommand:
    return RunCommand(
        step="m",
        visit=visit,
        command="diff-scope",
        subcommand=None,
        args=(("run.range", "a..b"),),
        recheck=recheck,
    )


def inline(steps: list[dict], reenter: str) -> dict:
    return {
        "inputs": ["holder", "issue", "range", "repo"],
        "stops": {"needs-owner": {"need": "owner-decision", "reenter": reenter}},
        "steps": steps,
    }


DECIDE = inline(
    [
        {"id": "scope", "stage": "setup", "kind": "command", "command": "diff-scope", "holds": "run",
         "in": ["run.range"], "on": {"ok": "tally", "failed": "needs-owner"}},
        {"id": "tally", "stage": "final review", "kind": "decide", "grader": "toy-tally", "holds": "run",
         "in": ["scope.verdict"], "on": {"accept": "done", "revise": "needs-owner"}},
    ],
    "tally",
)
LOOP = inline(
    [
        {"id": "a", "stage": "setup", "kind": "command", "command": "diff-scope", "holds": "live",
         "in": ["run.range"], "on": {"ok": "m", "failed": "needs-owner"}},
        {"id": "m", "stage": "building", "kind": "command", "command": "diff-scope", "holds": "run",
         "mutates": True, "check": {"command": "diff-scope"}, "max_visits": 3, "in": ["run.range"],
         "on": {"ok": "m", "failed": "needs-owner", "exhausted": "done"}},
    ],
    "a",
)


class ContinueTest(unittest.TestCase):
    def test_a_moved_head_reenters_at_the_head_step_and_rewinds_its_visit(self) -> None:
        self.assertEqual(reentry(toy(), INPUTS, E1, "h2"), Reentry(step="review", visit=1, stale=("review",)))
        self.assertEqual(
            next_action(toy(), INPUTS, E1 + [C("review", 1)]),
            StartSession(
                step="review",
                visit=2,
                role="reviewer",
                prompt="review.md",
                reply="review.reply.json",
                args=(("draft.summary", "s"),),
            ),
        )

    def test_a_rewind_forgets_the_heads_it_discarded(self) -> None:
        self.assertEqual(reentry(toy(), INPUTS, E1 + [C("review", 1)], "h2"), Reentry("review", 2, ()))

    def test_an_unchanged_head_reenters_at_the_stops_reenter_step(self) -> None:
        self.assertEqual(reentry(toy(), INPUTS, E1, "h1"), Reentry("draft", 1, ()))

    def test_a_stop_reenter_step_never_reached_is_entered_fresh(self) -> None:
        events = pair("scope", "failed")
        self.assertEqual(reentry(toy(), INPUTS, events, "h1"), Reentry("draft", None, ()))
        self.assertEqual(next_action(toy(), INPUTS, events + [C("draft", None)]), DRAFT(1))

    def test_a_rewind_to_a_stop_reenter_restores_its_visit_bound(self) -> None:
        events = pair("scope", "ok") + pair("draft", "stuck") * 2
        self.assertEqual(reentry(toy(), INPUTS, events, None), Reentry("draft", 2, ()))
        self.assertEqual(next_action(toy(), INPUTS, events + [C("draft", 2)]), DRAFT(3))
        result = replay(toy(), INPUTS, events + [C("draft", 2)] + pair("draft", "stuck"))
        self.assertEqual(result.action, STOP)
        self.assertEqual(result.transitions[-1], Transition("draft", "exhausted", "needs-owner"))

    def test_a_stop_reentering_a_graded_decide_rewinds_it_at_its_visit(self) -> None:
        events = pair("scope", "ok", {"verdict": "revise"})
        self.assertEqual(reentry(DECIDE, INPUTS, events, None), Reentry("tally", 1, ()))
        result = replay(DECIDE, INPUTS, events + [C("tally", 1)])
        self.assertEqual(result.action, Stop("needs-owner", "owner-decision", "tally"))
        self.assertEqual(result.transitions, replay(DECIDE, INPUTS, events).transitions)

    def test_an_interrupted_step_is_reentered_under_a_new_visit(self) -> None:
        events = pair("scope", "ok") + [{"type": "entered", "step": "draft"}]
        self.assertEqual(reentry(toy(), INPUTS, events, None), Reentry("draft", 1, ()))
        self.assertEqual(next_action(toy(), INPUTS, events + [C("draft", 1)]), DRAFT(2))

    def test_a_step_never_entered_keeps_its_visit(self) -> None:
        events = pair("scope", "ok")
        self.assertEqual(reentry(toy(), INPUTS, events, None), Reentry("draft", 1, ()))
        self.assertEqual(next_action(toy(), INPUTS, events + [C("draft", 1)]), DRAFT(1))

    def test_a_live_result_is_stale_whatever_the_head(self) -> None:
        doc = toy()
        step(doc, "scope")["holds"] = "live"
        events = pair("scope", "ok") + [{"type": "entered", "step": "draft"}]
        self.assertEqual(reentry(doc, INPUTS, events, "h1"), Reentry("scope", 1, ("scope",)))
        self.assertEqual(next_action(doc, INPUTS, events + [C("scope", 1)]), SCOPE(2))

    def test_an_unreadable_or_unrecorded_head_is_stale(self) -> None:
        self.assertEqual(reentry(toy(), INPUTS, E1, None).stale, ("review",))
        unrecorded = copy.deepcopy(E1)
        del unrecorded[-1]["head"]
        self.assertEqual(reentry(toy(), INPUTS, unrecorded, "h1").stale, ("review",))

    def test_the_earliest_stale_result_in_executed_order_wins(self) -> None:
        doc = toy()
        by_id = {item["id"]: item for item in doc["steps"]}
        doc["steps"] = [by_id[name] for name in ("scope", "tally", "review", "draft")]
        by_id["draft"]["holds"] = "live"
        self.assertEqual(reentry(doc, INPUTS, E1, "h2"), Reentry("draft", 1, ("draft", "review")))
        self.assertEqual(next_action(doc, INPUTS, E1 + [C("draft", 1)]), DRAFT(2))

    def test_only_a_steps_latest_result_is_judged(self) -> None:
        doc = toy()
        step(doc, "draft")["holds"] = "head"
        events = (
            pair("scope", "ok")
            + [
                {"type": "entered", "step": "draft"},
                {"type": "outcome", "step": "draft", "outcome": "stuck", "head": "h0"},
                {"type": "entered", "step": "draft"},
                {"type": "outcome", "step": "draft", "outcome": "drafted", "result": DRAFTED, "head": "h1"},
                {"type": "entered", "step": "review"},
            ]
        )
        self.assertEqual(reentry(doc, INPUTS, events, "h1"), Reentry("review", 1, ()))

    def test_a_mutating_command_is_rechecked_once_for_each_visit_a_rewind_discarded(self) -> None:
        history = pair("a", "ok") + pair("m", "ok") + [{"type": "entered", "step": "m"}]
        self.assertEqual(next_action(LOOP, INPUTS, pair("a", "ok")), M(1, False))
        self.assertEqual(
            next_action(LOOP, INPUTS, pair("a", "ok") + [{"type": "entered", "step": "m"}, C("m", 1)]),
            M(2, True),
        )
        rewound = history + [C("a", 1)]
        again = next_action(LOOP, INPUTS, rewound)
        self.assertIsInstance(again, RunCommand)
        self.assertEqual((again.step, again.visit, again.recheck), ("a", 2, False))
        self.assertEqual(next_action(LOOP, INPUTS, rewound + pair("a", "ok")), M(3, True))
        self.assertEqual(next_action(LOOP, INPUTS, rewound + pair("a", "ok") + pair("m", "ok")), M(4, True))
        self.assertEqual(next_action(LOOP, INPUTS, rewound + pair("a", "ok") + pair("m", "ok") * 2), M(5, False))
        second = rewound + pair("a", "ok") + [{"type": "entered", "step": "m"}, C("m", 3)]
        self.assertEqual(next_action(LOOP, INPUTS, second), M(4, True))
        self.assertEqual(next_action(LOOP, INPUTS, second + pair("m", "ok")), M(5, True))
        self.assertEqual(next_action(toy(), INPUTS, [{"type": "entered", "step": "scope"}, C("scope", 1)]), SCOPE(2))

    def test_a_rewound_upstream_that_changes_the_arguments_still_owes_the_check(self) -> None:
        doc = inline(
            [
                {"id": "s", "stage": "setup", "kind": "command", "command": "diff-scope", "holds": "head",
                 "in": ["run.range"], "on": {"ok": "m", "failed": "needs-owner"}},
                {"id": "m", "stage": "building", "kind": "command", "command": "diff-scope", "holds": "run",
                 "mutates": True, "check": {"command": "diff-scope"}, "in": ["s.title"],
                 "on": {"ok": "done", "failed": "needs-owner"}},
            ],
            "s",
        )
        first = pair("s", "ok", {"title": "t1"})
        events = first + [{"type": "entered", "step": "m"}, C("s", 1)] + pair("s", "ok", {"title": "t2"})
        action = next_action(doc, INPUTS, events)
        self.assertEqual((action.step, action.args, action.recheck), ("m", (("s.title", "t2"),), True))
        self.assertEqual(next_action(doc, INPUTS, first), RunCommand(
            "m", 1, "diff-scope", None, (("s.title", "t1"),), False))

    def test_a_done_run_has_no_reentry(self) -> None:
        with self.assertRaises(engine_core.CoreError):
            reentry(toy(), INPUTS, DONE_EVENTS, "h1")


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
        shipped = json.loads(SHIPPED_TOY.read_text(encoding="utf-8"))
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
            ("continued after done", toy(), INPUTS, DONE_EVENTS + [C("scope", 1)]),
            ("continued to an arrival the walk lacks", toy(), INPUTS, pair("scope", "ok") + [C("review", 1)]),
            ("continued with no visit while a step is pending", toy(), INPUTS, pair("scope", "ok") + [C("draft", None)]),
            ("continued to no step", toy(), INPUTS, pair("scope", "failed") + [C("nope", None)]),
            (
                "continued without a step",
                toy(),
                INPUTS,
                pair("scope", "failed") + [{"type": "continued", "visit": None}],
            ),
            (
                "group step",
                shipped,
                INPUTS,
                pair("scope", "ok") + pair("draft", "drafted", {"status": "drafted", "summary": "s", "items": []}),
            ),
        )
        for name, doc, inputs, events in table:
            with self.subTest(name=name):
                before = copy.deepcopy((doc, inputs, events))
                with self.assertRaises(engine_core.CoreError):
                    next_action(doc, inputs, events)
                self.assertEqual((doc, inputs, events), before)


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
