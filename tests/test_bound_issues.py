"""The filing pass of `agent_tools.delivery.bound_issues`.

Reads engine history lines written to a temporary file and answers the forge from a recording fake
tracker, so each case pins what the pass files, what it leaves unfiled and what it keeps in its seen file.
"""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from agent_tools.delivery import engine_session
from agent_tools.delivery.bound_issues import file_pass, role_marker, step_marker
from agent_tools.delivery.cleanup_issue import Issue, Refusal
from agent_tools.system.forge_api import ForgeError

TIER = "fast"

NOW = datetime(2026, 11, 26, 6, tzinfo=timezone.utc)
IMPL = {"wall_seconds": 3600, "turns": 300, "spend_usd": 20.0}
SMALL = {"wall_seconds": 600, "turns": 60, "spend_usd": 4.0}


class FakeTracker:
    def __init__(self, open_issues=None, writer=True):
        self.open = list(open_issues or [])
        self.writer = writer
        self.created: list[tuple[str, str]] = []

    def trusted_writer(self) -> bool:
        return self.writer

    def open_issues(self) -> list[Issue]:
        return list(self.open)

    def create(self, title: str, body: str) -> int:
        number = 101 + len(self.created)
        self.created.append((title, body))
        self.open.append(Issue(number, body))
        return number


def step(step, role, outcome, wall, turns, spend, *, procedure="direct", visit=1, bounds=IMPL) -> dict:
    return {"step": step, "visit": visit, "outcome": outcome, "wall_seconds": wall, "waits": [],
            "tokens": None, "spend_usd": spend, "account": None, "role": role, "turns": turns,
            "startup_seconds": None, "procedure": procedure, "bounds": bounds}


def stamp(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def line(run: str, ended: datetime, steps: list[dict], end: str = "done") -> dict:
    return {"format": 1, "run": run, "project": "example/fixture", "issue": 41, "end": end,
            "need": None, "ended": stamp(ended), "steps": steps}


class Paths:
    def __init__(self, test: unittest.TestCase) -> None:
        directory = tempfile.TemporaryDirectory()
        test.addCleanup(directory.cleanup)
        root = Path(directory.name)
        self.history, self.seen, self.lock = root / "history.jsonl", root / "seen.json", root / "pass.lock"

    def write(self, *lines: dict) -> None:
        self.history.write_text("".join(json.dumps(item) + "\n" for item in lines), encoding="utf-8")

    def file(self, tracker, now: datetime = NOW):
        return file_pass(tracker, self.history, self.seen, self.lock, now)


def kinds(filed) -> list[tuple[str, str]]:
    return [(item.kind, item.key) for item in filed]


def has_line(body: str, wanted: str) -> bool:
    return any(each.rstrip() == wanted for each in body.splitlines())


OUT = step("implement", "implementer", "out-of-bounds", 700.0, 50, 3.0)
REVIEW = step("review", None, "pass", 10.0, 0, 0, bounds=None)


class FilePassTest(unittest.TestCase):
    def test_an_out_of_bounds_step_and_a_wide_bound_each_file_one_issue_and_a_second_pass_files_none(self):
        paths, tracker = Paths(self), FakeTracker()
        paths.write(line("r1", NOW - timedelta(days=1), [OUT, REVIEW]))

        first = paths.file(tracker)
        second = paths.file(tracker)

        self.assertEqual(kinds(first), [("out-of-bounds", "direct.implement"),
                                        ("wide-bound", "implementer")])
        self.assertEqual([item.issue for item in first], [101, 102])
        self.assertTrue(has_line(tracker.created[0][1], step_marker("direct", "implement")))
        self.assertTrue(has_line(tracker.created[1][1], role_marker("implementer")))
        self.assertEqual(second, [])
        self.assertEqual(len(tracker.created), 2)

    def test_the_issues_carry_their_title_and_acceptance_criterion(self):
        paths, tracker = Paths(self), FakeTracker()
        paths.write(line("r1", NOW - timedelta(days=1), [OUT]))

        paths.file(tracker)

        (out_title, out_body), (wide_title, wide_body) = tracker.created
        self.assertEqual(out_title, "Engine step direct.implement ended out-of-bounds")
        self.assertEqual(out_body.splitlines()[:2], [step_marker("direct", "implement"), ""])
        self.assertIn("r1", out_body.splitlines()[2])
        self.assertIn("## Acceptance criteria", out_body)
        self.assertIn("- [ ] [code] Step direct.implement fits its bounds in the next run that reaches it, "
                      "or its bound is changed by a reviewed change — measured: the engine history",
                      out_body.splitlines())
        self.assertEqual(wide_title,
                         "The implementer role's bounds are more than five times its largest use in 14 days")
        self.assertEqual(wide_body.splitlines()[:5], [
            role_marker("implementer"), "", "- wall_seconds: bound 3600, largest use 700.0",
            "- turns: bound 300, largest use 50", "- spend_usd: bound 20.0, largest use 3.0"])
        self.assertIn("- [ ] [code] Each bound listed in engine_session.ROLE_BOUNDS for implementer is at "
                      "most five times the largest use above — measured: a comparison of the table's value "
                      "with the largest use the engine history shows in 14 days", wide_body.splitlines())

    def test_an_open_issue_with_the_marker_files_nothing(self):
        paths = Paths(self)
        tracker = FakeTracker([Issue(7, f"text\n{step_marker('direct', 'implement')}  \n"),
                               Issue(8, f"{role_marker('implementer')}\n")])
        paths.write(line("r1", NOW - timedelta(days=1), [OUT]))

        self.assertEqual(paths.file(tracker), [])
        self.assertEqual(tracker.created, [])

    def test_a_closed_out_of_bounds_issue_is_not_filed_again_for_the_same_occurrence(self):
        paths = Paths(self)
        paths.write(line("r1", NOW - timedelta(days=1), [OUT]))
        paths.file(FakeTracker())

        again = paths.file(FakeTracker())

        self.assertEqual(kinds(again), [("wide-bound", "implementer")])

    def test_the_continued_line_of_a_run_does_not_refile_its_earlier_visit(self):
        paths = Paths(self)
        paths.write(line("r1", NOW - timedelta(days=2), [OUT], end="fault"),
                    line("r1", NOW - timedelta(days=1), [OUT], end="done"))
        first = FakeTracker()

        paths.file(first)
        second = FakeTracker()
        paths.file(second)

        self.assertEqual([title for title, _ in first.created].count(
            "Engine step direct.implement ended out-of-bounds"), 1)
        self.assertNotIn("Engine step direct.implement ended out-of-bounds",
                         [title for title, _ in second.created])

    def test_two_procedures_with_the_same_step_id_are_two_keys(self):
        paths = Paths(self)
        tracker = FakeTracker([Issue(7, step_marker("land", "release"))])
        paths.write(line("r1", NOW - timedelta(days=1), [
            step("release", None, "out-of-bounds", 5.0, 0, 0, procedure="land", bounds=None),
            step("release", None, "out-of-bounds", 5.0, 0, 0, procedure="close-out", bounds=None)]))

        self.assertEqual(kinds(paths.file(tracker)), [("out-of-bounds", "close-out.release")])


class WideBoundTest(unittest.TestCase):
    def used(self, wall, turns, spend, *, ended=NOW - timedelta(days=1), **kwargs) -> dict:
        return line("r1", ended, [step("implement", "implementer", "ok", wall, turns, spend, **kwargs)])

    def test_a_bound_of_exactly_five_times_the_largest_use_files_nothing(self):
        paths = Paths(self)
        paths.write(self.used(720.0, 60, 4.0))

        self.assertEqual(paths.file(FakeTracker()), [])

    def test_one_dimension_over_files_one_issue_naming_only_it(self):
        paths, tracker = Paths(self), FakeTracker()
        paths.write(self.used(720.0, 60, 3.9))

        self.assertEqual(kinds(paths.file(tracker)), [("wide-bound", "implementer")])
        body = tracker.created[0][1]
        self.assertTrue(has_line(body, "- spend_usd: bound 20.0, largest use 3.9"))
        self.assertNotIn("wall_seconds", body)
        self.assertNotIn("- turns", body)

    def test_the_largest_of_several_uses_decides_in_either_order(self):
        big = self.used(800.0, 60, 4.0, ended=NOW - timedelta(days=2))
        small = line("r2", NOW - timedelta(days=1), [step("implement", "implementer", "ok", 100.0, 60, 4.0)])
        for order in ((big, small), (small, big)):
            with self.subTest(first=order[0]["run"]):
                paths = Paths(self)
                paths.write(*order)

                self.assertEqual(paths.file(FakeTracker()), [])

    def test_a_use_older_than_fourteen_days_is_not_counted(self):
        paths, tracker = Paths(self), FakeTracker()
        paths.write(
            line("old", NOW - timedelta(days=15), [step("implement", "implementer", "out-of-bounds",
                                                         3600.0, 300, 20.0)]),
            line("new", NOW - timedelta(days=1), [step("implement", "implementer", "ok", 100.0, 10, 1.0)]))

        self.assertEqual(kinds(paths.file(tracker)), [("wide-bound", "implementer")])

    def test_the_recorded_bound_is_judged_not_the_installed_table(self):
        table = {"implementer": engine_session.Bounds(3600, 300, 20.0)}
        paths = Paths(self)
        paths.write(self.used(720.0, 60, 4.0, bounds=SMALL))
        with mock.patch.object(engine_session, "ROLE_BOUNDS", table):
            self.assertEqual(paths.file(FakeTracker()), [])

        small_table = {"implementer": engine_session.Bounds(600, 60, 4.0)}
        newest = self.used(100.0, 10, 1.0, ended=NOW - timedelta(days=1), bounds=IMPL)
        older = self.used(700.0, 50, 3.0, ended=NOW - timedelta(days=3), bounds=SMALL)
        for order in ((newest, older), (older, newest)):
            with self.subTest(first=order[0]["ended"]):
                again = Paths(self)
                again.write(*order)
                with mock.patch.object(engine_session, "ROLE_BOUNDS", small_table):
                    self.assertEqual(kinds(again.file(FakeTracker())), [("wide-bound", "implementer")])

    def test_a_role_with_no_recorded_bound_files_nothing(self):
        paths = Paths(self)
        paths.write(line("r1", NOW - timedelta(days=1),
                         [step("review", "reviewer", "ok", 10.0, 1, 0.1, bounds=None)]))

        self.assertEqual(paths.file(FakeTracker()), [])


class PassGuardTest(unittest.TestCase):
    def test_an_untrusted_writer_files_nothing(self):
        paths, tracker = Paths(self), FakeTracker(writer=False)
        paths.write(line("r1", NOW - timedelta(days=1), [OUT]))

        with self.assertRaises(Refusal):
            paths.file(tracker)

        self.assertEqual(tracker.created, [])
        self.assertFalse(paths.seen.exists())

    def test_a_failed_create_keeps_the_seen_file(self):
        paths, tracker = Paths(self), FakeTracker()
        paths.write(line("r1", NOW - timedelta(days=1), [OUT]))

        with mock.patch.object(tracker, "create", side_effect=ForgeError("gh_failed", "boom")):
            with self.assertRaises(ForgeError):
                paths.file(tracker)

        self.assertFalse(paths.seen.exists())

    def test_two_overlapping_passes_file_one_issue(self):
        paths = Paths(self)
        paths.write(line("r1", NOW - timedelta(days=1), [OUT]))
        inside, release, second_in = threading.Event(), threading.Event(), threading.Event()
        calls = []

        class Gated(FakeTracker):
            def open_issues(self):
                calls.append(1)
                if len(calls) == 1:
                    inside.set()
                    release.wait(5)
                else:
                    second_in.set()
                return super().open_issues()

        tracker = Gated()
        first = threading.Thread(target=paths.file, args=(tracker,))
        second = threading.Thread(target=paths.file, args=(tracker,))
        first.start()
        self.assertTrue(inside.wait(5))
        second.start()
        second_in.wait(0.5)
        release.set()
        first.join(10)
        second.join(10)

        self.assertEqual(len(tracker.created), 2)


if __name__ == "__main__":
    unittest.main()
