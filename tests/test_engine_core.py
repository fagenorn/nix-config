"""Contract tests for the engine core (`agent_tools.delivery.engine_core`, #1510).

The core is a pure function from a procedure, the run inputs and the events so
far to the next action. These cases drive it over the checked toy procedure in
`tests/fixtures/engine-core` and over one-mutation copies of it.
"""

from __future__ import annotations

import copy
import json
import threading
import unittest
from pathlib import Path
from unittest import mock

from agent_tools.delivery import engine_core, engine_graders, procedure_check
from agent_tools.delivery.engine_core import (
    Done,
    RunCommand,
    StartSession,
    Stop,
    Transition,
    next_action,
    replay,
)
from agent_tools.delivery.engine_graders import Grader

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
            ("missing run input", toy(), {}, []),
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


if __name__ == "__main__":
    unittest.main()
