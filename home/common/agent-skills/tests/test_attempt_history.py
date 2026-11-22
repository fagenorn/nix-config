"""The attempt budget rule and its history file (issue 1466).

Every case reads `agent_tools.project_contract.attempt_history` through its public
names only: the rule over a list of attempts, the strict history file and the
never-raising read of it.
"""

from __future__ import annotations

import ast
import json
import os
import shutil
import signal
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from agent_tools.project_contract import attempt_history
from agent_tools.project_contract.attempt_history import (
    FALLBACK_MINUTES,
    HISTORY_DIR,
    HISTORY_FILE,
    WINDOW,
    Attempt,
    budget,
    history_path,
    percentile_90_seconds,
    read,
    render_history,
    write_history,
)

TIER = "fast"

T0 = datetime(2026, 11, 1, tzinfo=timezone.utc)
PERMUTATION = [7, 3, 19, 1, 12, 20, 5, 16, 9, 2, 14, 18, 6, 11, 4, 17, 8, 13, 10, 15]
HISTORY_BASIS = {
    "source": "history",
    "delivered": 20,
    "percentile_90_seconds": 64830,
    "recorded_at": "2026-11-01T00:00:00Z",
}


def delivered(merged_at, seconds, issue, pull):
    return Attempt(issue, pull, merged_at - timedelta(seconds=seconds), merged_at)


def windowed():
    """The twenty delivered attempts of the window, durations not in merge order."""
    return [
        delivered(T0 + timedelta(days=i), h * 3600 + 30, 100 + i, 200 + i)
        for i, h in enumerate(PERMUTATION, start=1)
    ]


def older():
    return [delivered(T0 - timedelta(days=j), 100 * 3600, 300 + j, 400 + j) for j in range(1, 6)]


def scrambled(attempts):
    """An order that is neither merge order nor duration order."""
    ordered = sorted(attempts, key=lambda a: (a.issue * 7919) % 31)
    return ordered


class BudgetRuleTest(unittest.TestCase):
    def test_the_latest_twenty_of_twenty_five_give_one_and_a_half_times_their_nearest_rank_p90(self):
        attempts = scrambled(windowed() + older())
        self.assertEqual(len(attempts), 25)
        result = budget(attempts, T0)
        self.assertEqual(result.minutes, 1621)
        self.assertEqual(result.basis, HISTORY_BASIS)
        self.assertEqual(len(result.used), 20)
        self.assertTrue(all(a.merged_at > T0 for a in result.used))
        merges = [a.merged_at for a in result.used]
        self.assertEqual(merges, sorted(merges, reverse=True))

    def test_nineteen_delivered_give_the_fallback(self):
        result = budget(windowed()[:19], T0)
        self.assertEqual(result.minutes, 240)
        self.assertEqual(result.basis, {"source": "fallback", "reason": "too_few", "delivered": 19})
        self.assertEqual(len(result.used), 19)

    def test_an_unmerged_record_among_twenty_is_not_counted(self):
        attempts = windowed()
        first = attempts[0]
        attempts[0] = Attempt(first.issue, None, first.claimed_at, None)
        result = budget(attempts, T0)
        self.assertEqual(result.minutes, 240)
        self.assertEqual(result.basis, {"source": "fallback", "reason": "too_few", "delivered": 19})

    def test_stopped_attempts_beside_twenty_delivered_do_not_change_the_budget(self):
        late = T0 + timedelta(days=30)
        stopped = [Attempt(900 + n, None, late + timedelta(hours=n), None) for n in range(3)]
        result = budget(windowed() + stopped, T0)
        self.assertEqual(result.minutes, 1621)
        self.assertEqual(result.basis["delivered"], 20)

    def test_the_percentile_is_the_nearest_rank(self):
        self.assertEqual(percentile_90_seconds(list(range(1, 11))), 9)
        self.assertEqual(percentile_90_seconds([5]), 5)
        self.assertEqual(percentile_90_seconds(list(range(1, 21))), 18)
        self.assertEqual(percentile_90_seconds([4, 9, 1, 7, 10, 2, 8, 3, 6, 5]), 9)

    def test_a_history_of_zero_length_attempts_gives_one_minute(self):
        attempts = [delivered(T0 + timedelta(days=i), 0, i, 10 + i) for i in range(1, 21)]
        self.assertTrue(all(a.seconds() == 0 for a in attempts))
        self.assertEqual(budget(attempts, T0).minutes, 1)

    def test_an_unmerged_attempt_has_no_seconds(self):
        self.assertIsNone(Attempt(1, None, T0, None).seconds())


class ReadTest(unittest.TestCase):
    def root(self, git=True):
        path = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, path, ignore_errors=True)
        if git:
            (path / ".git").mkdir()
        return path

    def put(self, root, data):
        path = history_path(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))

    def assertFallback(self, result, reason):
        self.assertEqual(result.minutes, FALLBACK_MINUTES)
        self.assertEqual(result.basis, {"source": "fallback", "reason": reason})
        self.assertEqual(result.used, ())

    def small_document(self):
        attempts = [
            Attempt(1458, 1612, T0 - timedelta(hours=4), T0 - timedelta(hours=1)),
            Attempt(1458, None, T0 - timedelta(days=2), None),
        ]
        return json.loads(render_history("o/r", T0, attempts))

    def test_a_root_without_a_git_directory_is_no_history(self):
        self.assertFallback(read(self.root(git=False), "o/r"), "no_history")

    def test_a_missing_file_is_no_history(self):
        self.assertFallback(read(self.root(), "o/r"), "no_history")

    def test_bytes_that_are_not_json_are_unreadable(self):
        root = self.root()
        self.put(root, b"{not json")
        self.assertFallback(read(root, "o/r"), "unreadable")

    def test_invalid_utf8_and_a_duplicate_key_are_unreadable(self):
        rendered = render_history("o/r", T0, [])
        duplicate = rendered.replace('"repo": "o/r",', '"repo": "o/r", "repo": "o/r",')
        self.assertNotEqual(rendered, duplicate)
        nan = rendered.replace('"attempts": []', '"attempts": NaN')
        for name, data in (("bytes", b"\xff"), ("duplicate", duplicate), ("nan", nan),
                           ("nesting", "[" * 100000)):
            with self.subTest(name):
                root = self.root()
                self.put(root, data)
                self.assertFallback(read(root, "o/r"), "unreadable")

    def test_a_fifo_is_unreadable_and_never_blocks(self):
        root = self.root()
        path = history_path(root)
        path.parent.mkdir(parents=True)
        os.mkfifo(path)

        def hung(signum, frame):
            raise AssertionError("the history read blocked on a FIFO")

        previous = signal.signal(signal.SIGALRM, hung)
        self.addCleanup(signal.signal, signal.SIGALRM, previous)
        signal.alarm(20)
        self.addCleanup(signal.alarm, 0)
        self.assertFallback(read(root, "o/r"), "unreadable")

    def test_each_wrong_shape_is_invalid(self):
        def mutate(change):
            document = self.small_document()
            change(document)
            return json.dumps(document)

        def item(key, value):
            return lambda d: d.__setitem__(key, value)

        def attempt(index, key, value):
            return lambda d: d["attempts"][index].__setitem__(key, value)

        rows = {
            "version 2": item("version", 2),
            "version true": item("version", True),
            "missing member": lambda d: d.pop("repo"),
            "extra member": item("extra", 1),
            "pull without merge": attempt(1, "pull", 5),
            "merge without pull": attempt(0, "pull", None),
            "merge before claim": attempt(0, "merged_at", "2026-10-01T00:00:00Z"),
            "no Z": attempt(0, "claimed_at", "2026-11-22T12:00:00"),
            "recorded_at no Z": item("recorded_at", "2026-11-22T12:00:00"),
            "unpadded stamp": item("recorded_at", "2026-11-2T1:02:03Z"),
            "issue true": attempt(0, "issue", True),
            "issue zero": attempt(0, "issue", 0),
            "attempts not a list": item("attempts", {}),
            "attempt extra member": attempt(0, "note", "x"),
        }
        for name, change in rows.items():
            with self.subTest(name):
                root = self.root()
                self.put(root, mutate(change))
                self.assertFallback(read(root, "o/r"), "invalid")

    def test_another_repositorys_history_is_other_repository(self):
        root = self.root()
        self.put(root, render_history("o/other", T0, []))
        self.assertFallback(read(root, "o/r"), "other_repository")
        self.assertFallback(read(root, None), "other_repository")

    def test_a_written_history_reads_back_to_the_same_budget(self):
        root = self.root()
        path = write_history(root, render_history("o/r", T0, windowed() + older()))
        self.assertEqual(path, history_path(root))
        result = read(root, "o/r")
        self.assertEqual(result.minutes, 1621)
        self.assertEqual(result.basis, HISTORY_BASIS)
        self.assertEqual(sorted(p.name for p in path.parent.iterdir()), [HISTORY_FILE])
        self.assertEqual(path.parent.name, HISTORY_DIR)

    def test_a_linked_worktree_reads_the_common_directory(self):
        base = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, base, ignore_errors=True)
        root = base / "wt"
        gitdir = base / "gits" / "x"
        common = base / "common"
        root.mkdir()
        gitdir.mkdir(parents=True)
        common.mkdir()
        (root / ".git").write_text(f"gitdir: {gitdir}\n", encoding="utf-8")
        (gitdir / "commondir").write_text("../../common\n", encoding="utf-8")
        self.assertEqual(
            history_path(root).resolve(),
            (common / HISTORY_DIR / HISTORY_FILE).resolve(),
        )


class ModuleBoundaryTest(unittest.TestCase):
    def test_a_read_starts_no_child_process_and_opens_no_connection(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        (root / ".git").mkdir()
        write_history(root, render_history("o/r", T0, windowed()))
        expected = read(root, "o/r")
        with mock.patch("subprocess.Popen", side_effect=AssertionError), \
                mock.patch("socket.socket", side_effect=AssertionError):
            self.assertEqual(read(root, "o/r"), expected)
        self.assertEqual(expected.minutes, 1621)

    def test_the_module_imports_no_resolver(self):
        tree = ast.parse(Path(attempt_history.__file__).read_text(encoding="utf-8"))
        resolver = "agent_tools.project_contract.resolve_project"
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotEqual(alias.name, resolver)
            elif isinstance(node, ast.ImportFrom):
                self.assertNotEqual(node.module, resolver)
                if node.module == "agent_tools.project_contract":
                    self.assertNotIn("resolve_project", [a.name for a in node.names])


if __name__ == "__main__":
    unittest.main()
