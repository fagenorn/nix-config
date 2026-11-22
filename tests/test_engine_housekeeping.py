"""Contract tests for the engine run history (`agent_tools.delivery.engine_housekeeping`, #1519).

Covers the per-step summaries `engine_ledger.fold` derives, the history line built from a finished run,
the append-only history file and its 180-day prune.
"""

from __future__ import annotations

import json
import stat
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agent_tools.delivery import engine_ledger
from agent_tools.delivery.engine_housekeeping import append_history, history_line, prune_history
from tests.guard_policy_world import install_platform_manifest_in_environ

TIER = "integration"  # Task 5's cases run engine deliver with the stand-in commands

setUpModule = install_platform_manifest_in_environ

FIXTURES = Path(__file__).resolve().parent / "fixtures/engine"
RUN = {"run": "1519-20261121T160000Z-a1b2", "project": "example/engine", "issue": 1519}
ZERO = {"input": 0, "cache_write": 0, "cache_read": 0, "output": 0}
DRAFT_TOKENS = {"input": 10, "cache_write": 1, "cache_read": 2, "output": 3}


def never(pid: int, started: str) -> bool:
    return False


def recorded(name: str) -> list[dict]:
    return engine_ledger.replay(FIXTURES / f"{name}.jsonl")


def stored(step: str, at: str, wall: float, tokens: dict, spend: float, turns: int = 0) -> dict:
    return {"at": at, "event": "result_stored", "result": f"results/{step}.1.json",
            "spend_usd": spend, "step": step, "tokens": tokens, "turns": turns, "visit": 1,
            "wall_seconds": wall}


def graded(step: str, at: str, outcome: str) -> dict:
    return {"at": at, "event": "outcome_graded", "outcome": outcome, "step": step, "visit": 1}


def taken(step: str, at: str, outcome: str, to: str) -> dict:
    return {"at": at, "event": "transition_taken", "outcome": outcome, "step": step, "to": to,
            "visit": 1}


def entered(step: str, at: str, stage: str) -> dict:
    return {"at": at, "event": "step_entered", "stage": stage, "step": step, "visit": 1}


def first_case_events() -> list[dict]:
    return [
        entered("scope", "2026-11-21T16:00:00Z", "setup"),
        stored("scope", "2026-11-21T16:00:08Z", 8.0, ZERO, 0),
        graded("scope", "2026-11-21T16:00:08Z", "ok"),
        taken("scope", "2026-11-21T16:00:08Z", "ok", "gate"),
        taken("gate", "2026-11-21T16:00:30Z", "pass", "draft"),
        entered("draft", "2026-11-21T16:01:00Z", "building"),
        {"account": "acct-a", "at": "2026-11-21T16:01:01Z", "event": "session_starting",
         "role": "implementer", "session": "s-1", "step": "draft", "visit": 1},
        {"at": "2026-11-21T16:01:10Z", "event": "wait_started", "until": None,
         "wait": "usage-limit"},
        {"at": "2026-11-21T16:03:10Z", "event": "wait_ended", "wait": "usage-limit"},
        stored("draft", "2026-11-21T16:04:00Z", 30.0, DRAFT_TOKENS, 1.5, turns=3),
        graded("draft", "2026-11-21T16:04:00Z", "ok"),
        taken("draft", "2026-11-21T16:04:00Z", "ok", "done"),
        {"at": "2026-11-21T16:05:00Z", "event": "run_done"},
    ]


ENDED = datetime(2026, 11, 21, 17, tzinfo=timezone.utc)


class HistoryLineTest(unittest.TestCase):
    def test_the_history_line_of_a_folded_run_holds_every_member(self):
        events = first_case_events()
        for event in events:
            engine_ledger.validate_event(event)
        state = engine_ledger.fold(RUN, events, never)
        self.assertEqual(history_line(state, ENDED), {
            "format": 1, "run": RUN["run"], "project": "example/engine", "issue": 1519,
            "end": "done", "need": None, "ended": "2026-11-21T17:00:00Z",
            "steps": [
                {"step": "scope", "visit": 1, "outcome": "ok", "wall_seconds": 8.0, "waits": [],
                 "tokens": ZERO, "spend_usd": 0, "account": None},
                {"step": "gate", "visit": 1, "outcome": "pass", "wall_seconds": None,
                 "waits": [], "tokens": None, "spend_usd": None, "account": None},
                {"step": "draft", "visit": 1, "outcome": "ok", "wall_seconds": 30.0,
                 "waits": [{"wait": "usage-limit", "seconds": 120.0}],
                 "tokens": DRAFT_TOKENS, "spend_usd": 1.5, "account": "acct-a"}]})

    def test_a_stopped_run_names_its_stop_and_need(self):
        events = recorded("stopped")
        stop = [e for e in events if e["event"] == "stop_reached"][0]
        outcomes = [e["outcome"] for e in events if e["event"] == "outcome_graded"]
        line = history_line(engine_ledger.fold(RUN, events, never), ENDED)
        self.assertEqual((line["end"], line["need"]), (stop["stop"], stop["need"]))
        self.assertEqual([s["outcome"] for s in line["steps"]], outcomes)

    def test_a_done_run_wins_over_an_earlier_stop(self):
        events = recorded("stopped") + [{"at": "2026-11-21T16:30:00Z", "event": "run_done"}]
        line = history_line(engine_ledger.fold(RUN, events, never), ENDED)
        self.assertEqual((line["end"], line["need"]), ("done", None))

    def test_a_visit_with_no_graded_outcome_takes_its_transition_outcome(self):
        line = history_line(engine_ledger.fold(RUN, recorded("done"), never), ENDED)
        children = [s for s in line["steps"] if s["step"] == "children"]
        self.assertEqual(len(children), 1)
        self.assertEqual(children[0]["outcome"], "done")
        for member in ("wall_seconds", "tokens", "spend_usd", "account"):
            self.assertIsNone(children[0][member], member)

    def test_an_open_wait_has_no_seconds(self):
        events = recorded("waiting") + [
            {"at": "2026-11-21T16:04:00Z", "event": "stop_reached", "need": "owner-decision",
             "step": "draft", "stop": "needs-owner"}]
        line = history_line(engine_ledger.fold(RUN, events, never), ENDED)
        draft = [s for s in line["steps"] if s["step"] == "draft"][0]
        self.assertEqual(draft["waits"], [{"wait": "usage-limit", "seconds": None}])
        self.assertEqual(draft["account"], "acct-a")

    def test_a_run_neither_done_nor_stopped_has_no_line(self):
        state = engine_ledger.fold(RUN, recorded("running"), never)
        with self.assertRaises(ValueError):
            history_line(state, ENDED)

    def test_the_status_output_does_not_carry_the_steps(self):
        state = engine_ledger.fold(RUN, first_case_events(), never)
        self.assertNotIn("steps", state.as_json())


def example_line(run: str, ended: datetime) -> dict:
    return {"format": 1, "run": run, "ended": ended.strftime("%Y-%m-%dT%H:%M:%SZ")}


def compact(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode() + b"\n"


class HistoryFileTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.tmp = Path(directory.name)

    def test_a_continued_run_that_ends_again_appends_a_second_complete_line(self):
        path = self.tmp / "history.jsonl"
        events = recorded("continued")
        first_ended = datetime(2026, 11, 21, 16, 5, tzinfo=timezone.utc)
        first = history_line(engine_ledger.fold(RUN, events[:6], never), first_ended)
        append_history(first, path)
        before = path.read_bytes()
        rest = events + [
            stored("draft", "2026-11-21T16:10:00Z", 30.0, DRAFT_TOKENS, 1.5, turns=3),
            graded("draft", "2026-11-21T16:10:00Z", "ok"),
            taken("draft", "2026-11-21T16:10:00Z", "ok", "done"),
            {"at": "2026-11-21T16:10:01Z", "event": "run_done"}]
        for event in rest:
            engine_ledger.validate_event(event)
        second = history_line(engine_ledger.fold(RUN, rest, never), ENDED)
        append_history(second, path)
        lines = [json.loads(text) for text in path.read_text().splitlines()]
        self.assertEqual(len(lines), 2)
        self.assertTrue(path.read_bytes().startswith(before))
        self.assertEqual([line["run"] for line in lines], [RUN["run"], RUN["run"]])
        self.assertEqual(lines[0]["end"], "needs-owner")
        self.assertEqual(lines[1]["end"], "done")
        self.assertIsNone(lines[1]["need"])
        self.assertEqual([(s["step"], s["visit"]) for s in lines[1]["steps"]],
                         [("scope", 1), ("draft", 1)])

    def test_each_append_adds_one_compact_line_to_a_0600_file_under_new_parents(self):
        path = self.tmp / "a/b/history.jsonl"
        lines = [example_line("1-20261121T160000Z-aaaa", ENDED),
                 example_line("2-20261121T160000Z-bbbb", ENDED)]
        for line in lines:
            append_history(line, path)
        self.assertEqual(path.read_text().splitlines(),
                         [json.dumps(line, sort_keys=True, separators=(",", ":"))
                          for line in lines])
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_an_append_cuts_a_torn_tail_first(self):
        path = self.tmp / "history.jsonl"
        path.write_bytes(b'{"a":1}\n{"tor')
        line = example_line("1-20261121T160000Z-aaaa", ENDED)
        append_history(line, path)
        self.assertEqual(path.read_bytes(), b'{"a":1}\n' + compact(line))

    def test_a_prune_drops_lines_older_than_180_days_and_keeps_the_rest_byte_for_byte(self):
        path = self.tmp / "history.jsonl"
        now = datetime(2026, 11, 21, tzinfo=timezone.utc)
        old = [example_line("1-20260101T000000Z-aaaa", now - timedelta(days=181)),
               example_line("2-20260101T000000Z-aaaa", now - timedelta(days=180, seconds=1))]
        kept = [compact(example_line("3-20260101T000000Z-aaaa", now - timedelta(days=180))),
                compact(example_line("4-20260101T000000Z-aaaa", now - timedelta(days=10))),
                b"not json\n", b'{"run":"x"}\n']
        path.write_bytes(compact(old[0]) + compact(old[1]) + b"".join(kept) + b'{"ended":')
        self.assertEqual(prune_history(now, path), 2)
        self.assertEqual(path.read_bytes(), b"".join(kept))

    def test_a_prune_that_drops_nothing_leaves_the_file_untouched(self):
        path = self.tmp / "history.jsonl"
        now = datetime(2026, 11, 21, tzinfo=timezone.utc)
        path.write_bytes(compact(example_line("1-20260101T000000Z-aaaa", now - timedelta(days=1)))
                         + compact(example_line("2-20260101T000000Z-aaaa", now)))
        before = path.stat()
        self.assertEqual(prune_history(now, path), 0)
        after = path.stat()
        self.assertEqual((after.st_ino, after.st_mtime_ns), (before.st_ino, before.st_mtime_ns))

    def test_a_prune_of_a_missing_file_creates_nothing(self):
        path = self.tmp / "absent/history.jsonl"
        self.assertEqual(prune_history(ENDED, path), 0)
        self.assertFalse(path.exists())
        self.assertFalse(path.parent.exists())


if __name__ == "__main__":
    unittest.main()
