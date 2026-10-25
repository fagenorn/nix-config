"""agent_tools.phase_budget: the one home of the phase-gate budget (issue 432)."""
import os
import subprocess
import sys
import unittest
from pathlib import Path

from agent_tools import phase_budget
from agent_tools.phase_budget import PhaseBudget, crossing_threshold, handoff_threshold, parse


class GrammarTest(unittest.TestCase):
    def test_defaults_hand_off_at_110000_in_every_phase(self):
        budget = PhaseBudget()
        self.assertEqual([handoff_threshold(budget, p) for p in (None, 0, 5, 6, 7)], [110_000] * 5)
        self.assertEqual((budget.turn_ceiling, budget.turn_headroom, budget.context_headroom,
                          budget.guard, budget.cap), (120, 2, 10_000, 0, None))

    def test_a_base_threshold_and_a_later_range_win(self):
        budget = parse("threshold=140000,threshold:6-7=170000,threshold:7-7=200000")
        self.assertEqual([handoff_threshold(budget, p) for p in (None, 0, 5, 6, 7)],
                         [140_000, 140_000, 140_000, 170_000, 200_000])

    def test_bad_items_raise_naming_the_item(self):
        for spec in ("", "threshold=", "threshold=0", "threshold=9x", "threshold:3-1=5",
                     "threshold:0-8=5", "threshold=1,threshold=2", "boot=slim", "guard=40000",
                     "cap=2", "threshold=1,,cap=2"):
            with self.subTest(spec=spec), self.assertRaises(ValueError):
                parse(spec)

    def test_replay_knobs_accept_guard_and_cap(self):
        budget = parse("guard=40000,cap=2", knobs=phase_budget.REPLAY_KNOBS)
        self.assertEqual((budget.guard, budget.cap), (40_000, 2))
        with self.assertRaises(ValueError):
            parse("cap=0", knobs=phase_budget.REPLAY_KNOBS)
        based = parse("threshold=140000", knobs=phase_budget.REPLAY_KNOBS,
                      base=PhaseBudget(guard=5, cap=3))
        self.assertEqual((based.threshold, based.guard, based.cap), (140_000, 5, 3))

    def test_the_guard_raises_the_crossing_above_baseline(self):
        guarded = parse("guard=40000", knobs=phase_budget.REPLAY_KNOBS)
        self.assertEqual(crossing_threshold(guarded, 6, 98_000), 138_000)
        self.assertEqual(crossing_threshold(guarded, 6, 29_000), 110_000)
        self.assertEqual(crossing_threshold(guarded, 6, None), 110_000)
        self.assertEqual(crossing_threshold(PhaseBudget(), 6, 98_000), 110_000)


class EnvironmentTest(unittest.TestCase):
    def current_in_child(self, value):
        env = {key: val for key, val in os.environ.items() if key != phase_budget.ENVIRONMENT}
        if value is not None:
            env[phase_budget.ENVIRONMENT] = value
        return subprocess.run(
            [sys.executable, "-c", "from agent_tools import phase_budget as p; "
             "b = p.current(); print(p.handoff_threshold(b, 6), p.handoff_threshold(b, 1))"],
            capture_output=True, text=True, env=env, check=False)

    def test_unset_is_the_default(self):
        self.assertEqual(self.current_in_child(None).stdout.split(), ["110000", "110000"])

    def test_the_override_uses_the_same_grammar(self):
        out = self.current_in_child("threshold=90000,threshold:6-7=170000")
        self.assertEqual(out.stdout.split(), ["170000", "90000"])

    def test_an_invalid_override_raises(self):
        out = self.current_in_child("threshold=lots")
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("ValueError", out.stderr)


class MovedGateTest(unittest.TestCase):
    def test_workflow_state_holds_no_copy_of_select_phase_action(self):
        script = (Path(__file__).resolve().parents[1]
                  / "home/common/agent-skills/scripts/workflow-state.py")
        text = script.read_text(encoding="utf-8")
        self.assertNotIn("def select_phase_action", text)
        self.assertIn("select_phase_action", text)
