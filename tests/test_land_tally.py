"""Contract tests for `land_tally` (`agent_tools.delivery.land_tally`): the counts a landing reads from its ledger.

The rules are pure functions of transitions and lock answers; the ledger readers run against runs made with
`engine_ledger` under a temporary `HOME`.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from agent_tools.delivery import engine_ledger, land_tally

TIER = "fast"

NOW = datetime(2026, 11, 24, 9, 0, 0, tzinfo=timezone.utc)
AT = "2026-11-24T09:00:00Z"
ZERO_TOKENS = {"input": 0, "cache_write": 0, "cache_read": 0, "output": 0}


def answer(position: int, waited_s: int = 3000) -> dict:
    return {"verdict": "land-contended", "waited_s": waited_s, "position": position}


class LockBudgetTest(unittest.TestCase):
    def test_a_fourth_wait_that_ended_behind_others_is_spent(self):
        a = {"verdict": "land-contended", "waited_s": 3000, "position": 2}
        self.assertIs(land_tally.lock_budget([[a, a, a]]), True)
        self.assertIs(land_tally.lock_budget([[a, a, a, a]]), False)

    def test_a_wait_that_ended_first_in_line_spends_no_retry(self):
        p2, p1 = answer(2), answer(1)
        self.assertIs(land_tally.lock_budget([[p2, p2, p2, p1]]), True)
        self.assertIs(land_tally.lock_budget([[p2, p2, p2, p1, p2]]), False)

    def test_a_better_place_spends_no_retry(self):
        places = [answer(position) for position in (4, 3, 2, 2, 2)]
        self.assertIs(land_tally.lock_budget([places]), True)
        self.assertIs(land_tally.lock_budget([places + [answer(2)]]), False)

    def test_six_hours_of_waiting_is_spent_whatever_the_retries(self):
        self.assertIs(land_tally.lock_budget([[answer(1)] * 6]), True)
        self.assertIs(land_tally.lock_budget([[answer(1)] * 7]), False)
        self.assertIs(land_tally.lock_budget([[answer(1, waited_s=10)] * 7]), False)

    def test_the_ceiling_spans_runs_of_waits_and_the_retry_count_does_not(self):
        p2 = answer(2)
        self.assertIs(land_tally.lock_budget([[p2, p2, p2], [p2]]), True)
        self.assertIs(land_tally.lock_budget([[p2] * 3, [p2] * 4]), False)


class PendingTest(unittest.TestCase):
    def test_three_pending_reads_before_the_lock_are_spent(self):
        self.assertIs(land_tally.pending_spent([("gate", "pending")] * 2), False)
        self.assertIs(land_tally.pending_spent([("gate", "pending")] * 3), True)

    def test_a_non_pending_read_before_the_lock_resets_the_count(self):
        trans = [("gate", "pending"), ("gate", "pending"), ("gate", "red"), ("gate", "pending")]
        self.assertIs(land_tally.pending_spent(trans), False)

    def test_pending_reads_under_the_lock_are_never_reset(self):
        trans = [("lock", "held"), ("gate", "pending"), ("gate", "green"), ("gate", "pending"),
                 ("retake", "pending")]
        self.assertIs(land_tally.pending_spent(trans), True)

    def test_a_release_moves_the_count_back_to_the_reads_before_the_lock(self):
        trans = [("lock", "held"), ("gate", "pending"), ("fix-unlock", "released"), ("gate", "pending"),
                 ("gate", "pending")]
        self.assertIs(land_tally.pending_spent(trans), False)


class StaleTest(unittest.TestCase):
    def test_only_the_first_red_after_a_rerun_is_stale_eligible(self):
        rerun = [("ci-fixed", "unchanged"), ("gate", "pending"), ("gate", "red")]
        self.assertIs(land_tally.stale_eligible(rerun), True)
        self.assertIs(land_tally.stale_eligible(rerun + [("stale", "real"), ("gate", "red")]), False)
        self.assertIs(land_tally.stale_eligible([("gate", "red")]), False)
        answered = [("ci-fixed", "silent"), ("gate", "pending"), ("stale", "real"), ("gate", "red")]
        self.assertIs(land_tally.stale_eligible(answered), False)


class LedgerMaker:
    """Builds runs, calls and step visits with `engine_ledger` under `use_home`'s runs root."""

    def use_home(self, home: Path) -> None:
        self.home = home
        self.procedures = home / "procedures"
        self.procedures.mkdir(exist_ok=True)
        for name in ("deliver", "land", "land-attempt"):
            (self.procedures / f"{name}.json").write_text("{}", encoding="utf-8")
        self.token = iter("abcdefghijklmnopqrstuvwxyz")

    def run_of(self, procedure: str, *, issue: int = 7, parent: Path | None = None) -> Path:
        return engine_ledger.create_run(
            project="example/project", issue=issue, procedure=procedure, procedures_dir=self.procedures,
            platform_revision="0" * 40, host="host-a", inputs={"holder": "host-a/x"}, now=NOW,
            token=f"{next(self.token)}111", parent=None if parent is None else parent.name,
            root=self.home / ".agents" / "state" / "engine" / "runs")

    def call(self, parent: Path, child: Path, visit: int = 1) -> None:
        engine_ledger.append_event(parent, {"event": "call", "at": AT, "step": "call", "visit": visit,
                                            "child": child.name, "index": 0, "items": 1})

    def enter(self, run: Path, step: str, visit: int = 1) -> None:
        engine_ledger.append_event(run, {"event": "step_entered", "at": AT, "step": step, "visit": visit,
                                         "stage": "landing"})

    def visit(self, run: Path, step: str, visit: int, outcome: str, result: dict) -> None:
        self.enter(run, step, visit)
        engine_ledger.store_result(run, step=step, visit=visit, result=result, at=AT, wall_seconds=0,
                                   turns=0, tokens=dict(ZERO_TOKENS), spend_usd=0)
        engine_ledger.append_event(run, {"event": "outcome_graded", "at": AT, "step": step, "visit": visit,
                                         "outcome": outcome})
        engine_ledger.append_event(run, {"event": "transition_taken", "at": AT, "step": step, "visit": visit,
                                         "outcome": outcome, "to": "next"})

    def delivery(self) -> tuple[Path, Path, Path, Path, Path]:
        """The root `deliver` run, then `land` L1 with its attempt A1 and `land` L2 with its attempt A2."""
        root = self.run_of("deliver")
        l1 = self.run_of("land", parent=root)
        self.call(root, l1, 1)
        a1 = self.run_of("land-attempt", parent=l1)
        self.call(l1, a1)
        l2 = self.run_of("land", parent=root)
        self.call(root, l2, 2)
        a2 = self.run_of("land-attempt", parent=l2)
        self.call(l2, a2)
        return root, l1, a1, l2, a2


class LedgerTest(LedgerMaker, unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patch = mock.patch.dict(os.environ, {"HOME": tmp.name})
        patch.start()
        self.addCleanup(patch.stop)
        self.use_home(Path(tmp.name))

    def test_the_delivery_runs_are_the_root_then_each_called_run_and_its_descendants(self):
        root, l1, a1, l2, a2 = self.delivery()
        self.assertEqual(land_tally.delivery_runs("host-a/" + root.name), [root, l1, a1, l2, a2])
        self.assertEqual(land_tally.attempts("host-a/" + root.name), [a1, a2])
        self.assertEqual(land_tally.current("host-a/" + root.name), a2)

    def test_a_holder_with_no_run_or_no_attempt_is_a_tally_error(self):
        with self.assertRaises(land_tally.TallyError) as missing:
            land_tally.delivery_runs("host-a/9-20261124T090000Z-zzzz")
        self.assertEqual(missing.exception.code, "no_run")
        root = self.run_of("deliver")
        with self.assertRaises(land_tally.TallyError) as none:
            land_tally.current("host-a/" + root.name)
        self.assertEqual(none.exception.code, "no_attempt")

    def test_ci_fixes_count_every_attempt_run_of_the_delivery_and_no_other(self):
        root, _, a1, _, a2 = self.delivery()
        for run in (a1, a2):
            self.enter(run, land_tally.CI_FIX)
        other = self.run_of("land-attempt", issue=8)
        self.enter(other, land_tally.CI_FIX)
        holder = "host-a/" + root.name
        self.assertEqual(land_tally.entered(land_tally.attempts(holder), land_tally.CI_FIX), 2)
        self.assertEqual(land_tally.entered(land_tally.attempts(holder), land_tally.SYNC_FIX), 0)

    def test_lock_answers_group_contended_waits_into_runs_ended_by_a_hold(self):
        run = self.run_of("land-attempt")
        a1, a2, a3 = answer(3), answer(2), answer(1)
        self.visit(run, "lock", 1, "contended", {"verdict": "contended", "lock": a1})
        self.visit(run, "lock", 2, "contended", {"verdict": "contended", "lock": a2})
        self.visit(run, "lock", 3, "held", {"verdict": "held", "lock": {"verdict": "acquired"}})
        self.visit(run, "relock", 1, "contended", {"verdict": "contended", "lock": a3})
        self.assertEqual(land_tally.lock_answers(run), [[a1, a2], [a3]])
        self.assertEqual([step for step, _ in land_tally.transitions(run)],
                         ["lock", "lock", "lock", "relock"])

    def test_the_locked_shas_are_the_lock_shas_of_held_and_retaken_results(self):
        run = self.run_of("land-attempt")
        self.visit(run, "lock", 1, "held", {"verdict": "held", "lock": {"lock_sha": "1" * 40}})
        self.visit(run, "recheck", 1, "retaken", {"verdict": "retaken", "lock": {"lock_sha": "2" * 40}})
        self.visit(run, "lock", 2, "contended", {"verdict": "contended", "lock": {"lock_sha": "3" * 40}})
        self.assertEqual(land_tally.locked_shas(run), {"1" * 40, "2" * 40})

    def test_the_held_shas_span_every_attempt_of_the_delivery(self):
        root, _, a1, _, a2 = self.delivery()
        self.visit(a1, "lock", 1, "held", {"verdict": "held", "lock": {"lock_sha": "1" * 40}})
        self.visit(a2, "recheck", 1, "retaken", {"verdict": "retaken", "lock": {"lock_sha": "2" * 40}})
        self.assertEqual(land_tally.held_shas("host-a/" + root.name), {"1" * 40, "2" * 40})

    def test_the_latest_result_is_the_stored_result_of_the_latest_graded_visit_among_the_steps(self):
        run = self.run_of("land-attempt")
        self.assertIsNone(land_tally.latest_result(run, land_tally.CHECK_STEPS))
        self.visit(run, "gate", 1, "red", {"verdict": "red", "failing": ["A"]})
        self.visit(run, "lock", 1, "held", {"verdict": "held"})
        self.visit(run, "retake", 1, "red", {"verdict": "red", "failing": ["B"]})
        self.assertEqual(land_tally.latest_result(run, land_tally.CHECK_STEPS)["failing"], ["B"])


if __name__ == "__main__":
    unittest.main()
