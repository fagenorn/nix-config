"""Contract tests for the engine run history (`agent_tools.delivery.engine_housekeeping`, #1519).

Covers the per-step summaries `engine_ledger.fold` derives, the history line built from a finished run,
the append-only history file and its 180-day prune, and the sweep of expired run directories.
"""

from __future__ import annotations

import contextlib
import fcntl
import io
import json
import os
import shutil
import stat
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from agent_tools.delivery import engine_housekeeping, engine_ledger, engine_shell
from agent_tools.delivery.engine_housekeeping import (
    IssueUnreadable, TrackerError, _update_cursor, append_history, default_tracker,
    forge_tracker, history_line, housekeep, prune_history, sweep_runs,
)
from agent_tools.system import forge_api
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


NOW = datetime(2026, 11, 21, 12, tzinfo=timezone.utc)
PROJECT = "example/engine"


def seed(root: Path, issue: int, project: str = PROJECT, token: str = "a1b2") -> Path:
    procedures = Path(tempfile.mkdtemp())
    (procedures / "deliver.json").write_text("{}")
    path = engine_ledger.create_run(
        project=project, issue=issue, procedure="deliver", procedures_dir=procedures,
        platform_revision="source", host="test", inputs={"issue": issue},
        now=NOW - timedelta(days=30), token=token, root=root)
    shutil.rmtree(procedures)
    return path


class FakeTracker:
    def __init__(self, answers: dict, tick=None) -> None:
        self.answers = answers
        self.asked: list[int] = []
        self.tick = tick

    def __call__(self, issue: int):
        self.asked.append(issue)
        if self.tick is not None:
            self.tick()
        answer = self.answers.get(issue)
        if isinstance(answer, Exception):
            raise answer
        return answer


def left(root: Path) -> list[str]:
    return sorted(entry.name for entry in root.iterdir() if engine_ledger.RUN_ID_RE.match(entry.name))


def ago(days: float = 0, seconds: float = 0) -> datetime:
    return NOW - timedelta(days=days, seconds=seconds)


class SweepTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.tmp = Path(directory.name)
        self.root = self.tmp / "runs"
        self.cursor = self.tmp / "sweep-cursor.json"

    def sweep(self, tracker, **kw):
        kw.setdefault("cursor", self.cursor)
        return sweep_runs(kw.pop("root", self.root), project=PROJECT, tracker=tracker, now=NOW, **kw)

    def hold(self, path: Path, mode: int = fcntl.LOCK_EX) -> None:
        descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
        self.addCleanup(os.close, descriptor)
        fcntl.flock(descriptor, mode)

    def test_the_sweep_deletes_exactly_the_runs_whose_issue_closed_more_than_14_days_ago(self):
        runs = {n: seed(self.root, n) for n in (101, 102, 103, 104, 105, 106)}
        other = seed(self.root, 107, project="other/project")
        self.hold(runs[104] / "lock")
        tracker = FakeTracker({101: ago(20), 102: ago(13), 103: None, 104: ago(20),
                               105: ago(14), 106: ago(14, 1), 107: ago(20)})
        deleted = self.sweep(tracker)
        self.assertEqual(deleted, sorted([runs[101].name, runs[106].name]))
        self.assertEqual(left(self.root), sorted(
            [runs[102].name, runs[103].name, runs[104].name, runs[105].name, other.name]))
        self.assertEqual([e for e in self.root.iterdir() if e.name.endswith(".expired")], [])
        self.assertNotIn(107, tracker.asked)

    def test_a_tracker_that_errors_deletes_nothing(self):
        runs = [seed(self.root, 101), seed(self.root, 102)]
        self.assertEqual(self.sweep(FakeTracker({101: TrackerError("down"),
                                                 102: TrackerError("down")})), [])
        self.assertEqual(left(self.root), sorted(run.name for run in runs))
        self.assertFalse(self.cursor.exists())

    def test_an_expired_answer_then_a_tracker_error_deletes_nothing(self):
        runs = [seed(self.root, 101), seed(self.root, 102)]
        leftover = self.root / ".100-20261101T000000Z-a1b2.expired"
        leftover.mkdir()
        (leftover / "marker").write_text("x")
        tracker = FakeTracker({101: ago(20), 102: TrackerError("down")})
        self.assertEqual(self.sweep(tracker), [])
        self.assertEqual(left(self.root), sorted(run.name for run in runs))
        self.assertTrue((leftover / "marker").exists())
        self.assertEqual(tracker.asked, [101, 102])
        self.assertFalse(self.cursor.exists())

    def test_an_unreadable_issue_keeps_only_its_runs(self):
        kept, gone = seed(self.root, 101), seed(self.root, 102)
        deleted = self.sweep(FakeTracker({101: IssueUnreadable("gone"), 102: ago(20)}))
        self.assertEqual(deleted, [gone.name])
        self.assertEqual(left(self.root), [kept.name])

    def test_the_tracker_is_asked_once_per_issue(self):
        runs = [seed(self.root, 101), seed(self.root, 101, token="c3d4")]
        tracker = FakeTracker({101: ago(20)})
        self.assertEqual(self.sweep(tracker), sorted(run.name for run in runs))
        self.assertEqual(tracker.asked, [101])

    def test_a_held_creation_lock_keeps_the_issues_runs(self):
        run = seed(self.root, 101)
        self.hold(engine_ledger.creation_lock_path(self.root, 101))
        self.assertEqual(self.sweep(FakeTracker({101: ago(20)})), [])
        self.assertEqual(left(self.root), [run.name])

    def test_the_skipped_run_is_kept_and_its_issues_earlier_runs_are_swept(self):
        first, second = seed(self.root, 101), seed(self.root, 101, token="c3d4")
        with self.subTest("an earlier run of the same issue"):
            tracker = FakeTracker({101: ago(20)})
            self.assertEqual(self.sweep(tracker, skip_run=first.name), [second.name])
            self.assertEqual(left(self.root), [first.name])
            self.assertEqual(tracker.asked, [101])
        with self.subTest("only the skipped run"):
            tracker = FakeTracker({101: ago(20)})
            self.assertEqual(self.sweep(tracker, skip_run=first.name), [])
            self.assertEqual(left(self.root), [first.name])
            self.assertEqual(tracker.asked, [])

    def test_a_run_whose_issue_disagrees_with_its_name_is_kept(self):
        run = seed(self.root, 101)
        document = json.loads((run / "run.json").read_text())
        for wrong in (102, True):
            with self.subTest(issue=wrong):
                (run / "run.json").write_text(json.dumps(
                    {**document, "issue": wrong}, sort_keys=True, separators=(",", ":")) + "\n")
                tracker = FakeTracker({101: ago(20), 102: ago(20)})
                self.assertEqual(self.sweep(tracker), [])
                self.assertEqual(left(self.root), [run.name])
                self.assertEqual(tracker.asked, [])
        with self.subTest("true on a run of issue 1"):
            one = seed(self.root, 1)
            document = json.loads((one / "run.json").read_text())
            (one / "run.json").write_text(json.dumps(
                {**document, "issue": True}, sort_keys=True, separators=(",", ":")) + "\n")
            tracker = FakeTracker({1: ago(20)})
            self.assertEqual(self.sweep(tracker), [])
            self.assertEqual(tracker.asked, [])

    def test_no_tracker_read_starts_after_the_sweep_budget(self):
        kept, gone = seed(self.root, 102), seed(self.root, 101)
        tracker = FakeTracker({101: ago(20), 102: ago(20)})
        deleted = self.sweep(tracker, monotonic=lambda: 61.0 if tracker.asked else 0.0)
        self.assertEqual(tracker.asked, [101])
        self.assertEqual(deleted, [gone.name])
        self.assertEqual(left(self.root), [kept.name])

    def test_repeated_sweeps_reach_an_expired_issue_behind_slow_open_ones(self):
        for issue in (101, 102, 103, 104):
            seed(self.root, issue)
        clock = [0.0]

        def tick():
            clock[0] += 30.0

        answers = {104: ago(20)}
        first = FakeTracker(answers, tick)
        self.assertEqual(self.sweep(first, monotonic=lambda: clock[0]), [])
        self.assertEqual(first.asked, [101, 102])
        second = FakeTracker(answers, tick)
        deleted = self.sweep(second, monotonic=lambda: clock[0])
        self.assertEqual(second.asked, [103, 104])
        self.assertEqual([name.split("-")[0] for name in deleted], ["104"])

    def test_the_cursor_keeps_other_projects_entries(self):
        seed(self.root, 101)
        self.cursor.write_text(json.dumps({"other/project": 7}))
        self.sweep(FakeTracker({}))
        self.assertEqual(json.loads(self.cursor.read_text()),
                         {"other/project": 7, PROJECT: 101})
        self.assertEqual(stat.S_IMODE(self.cursor.stat().st_mode), 0o600)

    def test_two_overlapping_cursor_updates_keep_both_entries(self):
        original = engine_housekeeping._read_cursor
        read, go = threading.Event(), threading.Event()
        first = []

        def slow(cursor):
            result = original(cursor)
            if not first:
                first.append(True)
                read.set()
                go.wait(10)
            return result

        with mock.patch.object(engine_housekeeping, "_read_cursor", slow):
            one = threading.Thread(target=_update_cursor, args=(self.cursor, "a/one", 1))
            two = threading.Thread(target=_update_cursor, args=(self.cursor, "b/two", 2))
            one.start()
            self.assertTrue(read.wait(10))
            two.start()
            two.join(2)
            go.set()
            one.join(10)
            two.join(10)
        self.assertEqual(json.loads(self.cursor.read_text()), {"a/one": 1, "b/two": 2})

    def test_reads_run_under_no_forge_deadline(self):
        seed(self.root, 101)
        seen = []
        self.sweep(lambda issue: seen.append(forge_api._DEADLINE.get()))
        self.assertEqual(seen, [None])

    def test_a_paused_sweep_holds_the_creation_lock_and_shows_no_holder(self):
        run = seed(self.root, 101)
        holders, blocked = [], []

        def paused(path):
            holders.append(engine_shell.lock_holder(path))
            descriptor = os.open(engine_ledger.creation_lock_path(self.root, 101),
                                 os.O_RDWR | os.O_CREAT, 0o600)
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                blocked.append(False)
            except BlockingIOError:
                blocked.append(True)
            finally:
                os.close(descriptor)

        self.assertEqual(self.sweep(FakeTracker({101: ago(20)}), on_locked=paused), [run.name])
        self.assertEqual((holders, blocked), ([None], [True]))
        self.assertEqual(left(self.root), [])

    def test_an_unreadable_run_is_kept(self):
        run = seed(self.root, 101)
        (run / "run.json").write_text("{")
        tracker = FakeTracker({101: ago(20)})
        self.assertEqual(self.sweep(tracker), [])
        self.assertEqual(left(self.root), [run.name])
        self.assertEqual(tracker.asked, [])

    def test_an_unlistable_root_deletes_nothing(self):
        seed(self.root, 101)
        with mock.patch.object(Path, "iterdir", side_effect=PermissionError("denied")):
            self.assertEqual(self.sweep(FakeTracker({101: ago(20)})), [])
        self.assertEqual(self.sweep(FakeTracker({}), root=self.tmp / "absent"), [])

    def test_a_leftover_expired_directory_is_removed(self):
        self.root.mkdir()
        leftover = self.root / ".101-20261101T000000Z-a1b2.expired"
        leftover.mkdir()
        (leftover / "file").write_text("x")
        notes = self.root / ".notes.expired"
        notes.mkdir()
        self.sweep(FakeTracker({}))
        self.assertFalse(leftover.exists())
        self.assertTrue(notes.exists())

    def test_a_failed_removal_writes_one_line_and_the_next_sweep_removes_it(self):
        run = seed(self.root, 101)
        expired = self.root / f".{run.name}.expired"
        captured = io.StringIO()
        with mock.patch("agent_tools.delivery.engine_housekeeping.shutil.rmtree",
                        side_effect=PermissionError("denied")), \
                contextlib.redirect_stderr(captured):
            self.assertEqual(self.sweep(FakeTracker({101: ago(20)})), [])
        self.assertTrue(expired.exists())
        lines = captured.getvalue().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith("engine: housekeeping could not remove "))
        self.assertIn(f".{run.name}.expired", lines[0])
        self.assertTrue(lines[0].endswith("PermissionError: denied"))
        captured = io.StringIO()
        with contextlib.redirect_stderr(captured):
            self.assertEqual(self.sweep(FakeTracker({})), [])
        self.assertFalse(expired.exists())
        self.assertEqual(captured.getvalue(), "")

    def test_find_runs_skips_a_run_renamed_between_listing_and_reading(self):
        first, second = seed(self.root, 101), seed(self.root, 101, token="c3d4")
        original = engine_ledger.read_run
        calls = []

        def renaming(path):
            if not calls:
                calls.append(path)
                os.rename(path, self.root / f".{Path(path).name}.expired")
            return original(path)

        with self.subTest("renamed away"):
            with mock.patch.object(engine_ledger, "read_run", renaming):
                found = engine_ledger.find_runs(self.root, 101, PROJECT)
            self.assertEqual(found, [p for p in (first, second) if p != calls[0]])
        with self.subTest("present but unreadable"):
            (found[0] / "run.json").unlink()
            with self.assertRaises(engine_ledger.LedgerError):
                engine_ledger.find_runs(self.root, 101, PROJECT)


class HousekeepTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.tmp = Path(directory.name)

    def run_housekeep(self, name, tracker, clock=lambda: NOW, prepare=None):
        home = self.tmp / name
        home.mkdir()
        captured = io.StringIO()
        with mock.patch.dict(os.environ, {"HOME": str(home)}), \
                contextlib.redirect_stderr(captured):
            run = seed(engine_ledger.runs_root(), 101)
            if prepare is not None:
                prepare(home)
            self.assertIsNone(housekeep(project=PROJECT, run="999-20261101T000000Z-zzzz",
                                        clock=clock, tracker=tracker))
        return home, run, captured.getvalue().splitlines()

    def test_each_swallowed_exception_writes_one_stderr_line(self):
        def boom(issue):
            raise RuntimeError("boom")

        def down(issue):
            raise TrackerError("down")

        def no_clock():
            raise OSError("no clock")

        def no_kind():
            raise KeyError("kind")

        old = compact({"format": 1, "run": "1-20260101T000000Z-aaaa",
                       "ended": (NOW - timedelta(days=181)).strftime("%Y-%m-%dT%H:%M:%SZ")})

        def history_dir(home):
            (home / ".agents/state/engine/history.jsonl").mkdir()

        def old_history(home):
            (home / ".agents/state/engine/history.jsonl").write_bytes(old)

        with self.subTest("a failing sweep"):
            home, run, lines = self.run_housekeep("sweep", lambda: boom)
            self.assertTrue(run.exists())
            self.assertEqual(len(lines), 1)
            self.assertTrue(lines[0].startswith(
                "engine: housekeeping skipped the run sweep: RuntimeError: boom"))
        with self.subTest("a failing prune"):
            home, run, lines = self.run_housekeep("prune", lambda: boom, prepare=history_dir)
            self.assertEqual(len(lines), 2)
            self.assertTrue(lines[0].startswith("engine: housekeeping skipped the history prune:"))
        with self.subTest("a tracker error"):
            home, run, lines = self.run_housekeep("down", lambda: down)
            self.assertEqual(lines, [])
            self.assertTrue(run.exists())
        with self.subTest("a failing clock"):
            called = []
            home, run, lines = self.run_housekeep(
                "clock", lambda: called.append(True), clock=no_clock, prepare=old_history)
            self.assertEqual(lines, ["engine: housekeeping skipped the history prune and the run "
                                     "sweep: OSError: no clock"])
            self.assertEqual(called, [])
            self.assertEqual((home / ".agents/state/engine/history.jsonl").read_bytes(), old)
            self.assertTrue(run.exists())
        with self.subTest("a failing factory"):
            home, run, lines = self.run_housekeep("factory", no_kind, prepare=old_history)
            self.assertEqual(lines, ["engine: housekeeping skipped the run sweep: KeyError: 'kind'"])
            self.assertEqual((home / ".agents/state/engine/history.jsonl").read_bytes(), b"")


class ForgeTrackerTest(unittest.TestCase):
    BASE = {"number": 101, "repository_url": "https://api.github.com/repos/example/engine"}

    def answer(self, payload):
        with mock.patch("agent_tools.system.forge_api.api_get", return_value=payload) as patched:
            return forge_tracker(PROJECT)(101), patched

    def test_the_forge_tracker_reads_state_and_closed_at(self):
        closed = {"state": "closed", "closed_at": "2026-11-01T00:00:00Z"}
        with self.subTest("open"):
            result, patched = self.answer({**self.BASE, "state": "open"})
            self.assertIsNone(result)
            patched.assert_called_once_with("repos/example/engine/issues/101", allow=(404, 410))
        with self.subTest("closed"):
            result, _ = self.answer({**self.BASE, **closed})
            self.assertEqual(result, datetime(2026, 11, 1, tzinfo=timezone.utc))
        with self.subTest("case-folded repository"):
            result, _ = self.answer({**self.BASE, **closed,
                                     "repository_url": "https://api.github.com/repos/Example/Engine"})
            self.assertEqual(result, datetime(2026, 11, 1, tzinfo=timezone.utc))
        unreadable = {
            "another repository": {**self.BASE, **closed, "repository_url": ".../repos/other/repo"},
            "another number": {**self.BASE, **closed, "number": 102},
            "a bool number": {**self.BASE, **closed, "number": True},
            "a pull request": {**self.BASE, **closed, "pull_request": {}},
            "a weird state": {**self.BASE, "state": "weird"},
            "no closed_at": {**self.BASE, "state": "closed", "closed_at": None},
            "no payload": None,
            "a list": [],
        }
        for name, payload in unreadable.items():
            with self.subTest(name), self.assertRaises(IssueUnreadable):
                self.answer(payload)
        with self.subTest("a forge failure"):
            with mock.patch("agent_tools.system.forge_api.api_get",
                            side_effect=forge_api.ForgeError("gh_failed", "x")), \
                    self.assertRaises(TrackerError):
                forge_tracker(PROJECT)(101)

    def test_a_tracker_kind_other_than_github_is_a_tracker_error(self):
        with mock.patch("agent_tools.system.forge_api.api_get") as patched:
            with self.assertRaises(TrackerError):
                default_tracker({"kind": "gitlab", "repo_slug": PROJECT})(101)
            patched.assert_not_called()
        with mock.patch("agent_tools.system.forge_api.api_get",
                        return_value={**self.BASE, "state": "open"}) as patched:
            default_tracker({"kind": "github", "repo_slug": PROJECT})(101)
        self.assertEqual(patched.call_args.args, ("repos/example/engine/issues/101",))


if __name__ == "__main__":
    unittest.main()
