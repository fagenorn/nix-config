"""Tests for `agent_tools.delivery.suite_timing`, the suite-time comparison CI runs (issue 1385).

`CompareTest` and `SpeedFactorTest` call the module's functions on reports built
here; `CommandTest` runs `python -m agent_tools.delivery.suite_timing compare` as a
child process over report files in a temporary directory; `CompatibilityTest` loads a
report the suite runner wrote.
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from agent_tools.delivery import suite_runner
from agent_tools.delivery.suite_runner import MemberResult
from agent_tools.delivery.suite_timing import compare, load_report, speed_factor, summary_line

TIER = "fast"

REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON_PATH = str(REPO_ROOT / "python")
NO_BASELINE = ("Suite time: no main baseline to compare with; 60.0s of member time. "
               "Slowest test: tests/test_c.py (30.0s).")


def report(seconds: dict[str, float]) -> dict:
    rows = sorted(seconds.items(), key=lambda item: -item[1])
    return {
        "version": 1,
        "member_seconds": round(sum(seconds.values()), 1),
        "timings": [{"member": f"tests/test_{name}.py", "seconds": value,
                     "cpu_seconds": 0.0, "passed": True} for name, value in rows],
    }


def line_for(base: dict[str, float], head: dict[str, float]) -> str:
    base_report, head_report = report(base), report(head)
    return summary_line(head_report, compare(base_report, head_report),
                        threshold=60.0, base_label="main")


BASE = {"a": 10, "b": 20, "c": 30}


class CompareTest(unittest.TestCase):
    def test_a_new_slow_member_past_the_threshold_gets_a_growth_line(self):
        self.assertEqual(
            line_for(BASE, {**BASE, "slow": 90}),
            "Suite time grew by 90.0s over main, past the 60s threshold: 60.0s to 150.0s of "
            "member time at runner speed 1.00. Largest growth: tests/test_slow.py (+90.0s). "
            "Slowest test: tests/test_slow.py (90.0s).")

    def test_the_largest_growth_and_the_slowest_test_are_named_apart(self):
        base = {**BASE, "big": 200}
        self.assertEqual(
            line_for(base, {**base, "new": 80}),
            "Suite time grew by 80.0s over main, past the 60s threshold: 260.0s to 340.0s of "
            "member time at runner speed 1.00. Largest growth: tests/test_new.py (+80.0s). "
            "Slowest test: tests/test_big.py (200.0s).")

    def test_growth_within_the_threshold_says_so(self):
        self.assertEqual(
            line_for(BASE, {**BASE, "d": 40}),
            "Suite time changed by +40.0s over main, within the 60s threshold: 60.0s to "
            "100.0s of member time at runner speed 1.00. Slowest test: tests/test_d.py (40.0s).")

    def test_growth_equal_to_the_threshold_is_within_it(self):
        self.assertTrue(line_for(BASE, {**BASE, "e": 60}).startswith(
            "Suite time changed by +60.0s over main, within the 60s threshold:"))

    def test_growth_that_rounds_to_the_threshold_is_past_it(self):
        base = report({"a": 10.0, "b": 20.0, "c": 1.6})
        head = report({"a": 11.0, "b": 20.0, "c": 3.2, "new": 60.6})
        comparison = compare(base, head)
        self.assertGreater(comparison.growth, 60.0)
        self.assertEqual(
            summary_line(head, comparison, threshold=60.0, base_label="main"),
            "Suite time grew by 60.0s over main, past the 60s threshold: 31.6s to 94.8s of "
            "member time at runner speed 1.10. Largest growth: tests/test_new.py (+60.6s). "
            "Slowest test: tests/test_new.py (60.6s).")

    def test_an_existing_member_that_grew_most_is_named(self):
        self.assertEqual(
            line_for(BASE, {"a": 15, "b": 30, "c": 160}),
            "Suite time grew by 115.0s over main, past the 60s threshold: 60.0s to 205.0s of "
            "member time at runner speed 1.50. Largest growth: tests/test_c.py (+115.0s). "
            "Slowest test: tests/test_c.py (160.0s).")

    def test_a_slower_runner_is_not_growth(self):
        base = report({"a": 50, "b": 100, "c": 150})
        head = report({"a": 75, "b": 150, "c": 225})
        comparison = compare(base, head)
        self.assertEqual(comparison.factor, 1.5)
        self.assertEqual(comparison.growth, 0.0)
        self.assertEqual(
            summary_line(head, comparison, threshold=60.0, base_label="main"),
            "Suite time changed by +0.0s over main, within the 60s threshold: 300.0s to "
            "450.0s of member time at runner speed 1.50. Slowest test: tests/test_c.py (225.0s).")

    def test_a_removed_member_counts_against_growth(self):
        self.assertEqual(
            line_for({**BASE, "gone": 100}, BASE),
            "Suite time changed by -100.0s over main, within the 60s threshold: 160.0s to "
            "60.0s of member time at runner speed 1.00. Slowest test: tests/test_c.py (30.0s).")


class SpeedFactorTest(unittest.TestCase):
    def test_members_under_a_second_in_the_base_are_ignored(self):
        base = report({"a": 0.2, "b": 0.3, "c": 10, "d": 20})
        head = report({"a": 2.0, "b": 3.0, "c": 10, "d": 20})
        self.assertEqual(speed_factor(base, head), 1.0)

    def test_no_common_member_over_a_second_means_speed_one(self):
        self.assertEqual(speed_factor(report({"a": 0.5}), report({"b": 5})), 1.0)


class CommandTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)

    def write(self, name: str, content: dict | str) -> Path:
        path = self.directory / name
        path.write_text(content if isinstance(content, str) else json.dumps(content),
                        encoding="utf-8")
        return path

    def run_compare(self, head: Path, base: Path, *extra: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "agent_tools.delivery.suite_timing", "compare",
             "--head", str(head), "--base", str(base), "--base-label", "main", *extra],
            capture_output=True, text=True, check=False, cwd=self.directory,
            env={"PYTHONPATH": PYTHON_PATH, "PATH": "/usr/bin:/bin"})

    def test_the_command_prints_the_line_then_the_slowest_tests(self):
        head = {**BASE, "slow": 90}
        result = self.run_compare(self.write("head.json", report(head)),
                                  self.write("base.json", report(BASE)))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout,
            line_for(BASE, head) + "\n\n| Slowest tests | Seconds |\n|---|---:|\n"
            "| tests/test_slow.py | 90.0 |\n| tests/test_c.py | 30.0 |\n"
            "| tests/test_b.py | 20.0 |\n| tests/test_a.py | 10.0 |\n")
        many = {f"m{index:02d}": 100 - index for index in range(12)}
        result = self.run_compare(self.write("many.json", report(many)),
                                  self.write("base.json", report(BASE)))
        rows = [row for row in result.stdout.splitlines() if row.startswith("| tests/")]
        self.assertEqual(len(rows), 10)

    def test_the_threshold_flag_moves_the_bound(self):
        result = self.run_compare(self.write("head.json", report({**BASE, "d": 40})),
                                  self.write("base.json", report(BASE)),
                                  "--threshold", "30")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.startswith(
            "Suite time grew by 40.0s over main, past the 30s threshold:"), result.stdout)

    def test_no_baseline_or_an_unreadable_one_prints_the_no_baseline_line(self):
        head = self.write("head.json", report(BASE))
        unordered = report({"a": 1.0, "b": 90.0})
        unordered["timings"].sort(key=lambda row: row["seconds"])
        twice = report({"a": 10.0, "b": 20.0})
        twice["timings"][1]["member"] = twice["timings"][0]["member"]
        cases = {
            "missing": (self.directory / "absent.json", ""),
            "truncated": (self.write("truncated.json", "{"), ""),
            "newer": (self.write("newer.json", '{"version": 2}'), "version"),
            "unordered": (self.write("unordered.json", unordered), "slowest first"),
            "duplicate": (self.write("duplicate.json", twice), "twice"),
        }
        for label, (base, reason) in cases.items():
            with self.subTest(label):
                result = self.run_compare(head, base)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.splitlines()[0], NO_BASELINE)
                self.assertTrue(result.stderr.startswith("suite-timing: base: "), result.stderr)
                self.assertIn(reason, result.stderr)
                if label == "truncated":
                    self.assertEqual(len(result.stderr.splitlines()), 1)

    def test_a_bad_head_report_or_threshold_is_a_usage_error(self):
        good = json.dumps(report(BASE))
        unordered = report({"a": 1.0, "b": 90.0})
        unordered["timings"].sort(key=lambda row: row["seconds"])
        twice = report({"a": 10.0, "b": 20.0})
        twice["timings"][0]["member"] = "tests/test_a.py"
        empty = report(BASE)
        empty["timings"] = []
        cases = {
            "missing": (self.directory / "absent.json", "", ()),
            "version": (self.write("v.json", {**report(BASE), "version": 2}), "version", ()),
            "duplicate key": (self.write("dup.json", good.replace(
                '"version": 1', '"version": 1, "version": 1')), "", ()),
            "nan": (self.write("nan.json", good.replace(
                f'"member_seconds": {report(BASE)["member_seconds"]}',
                '"member_seconds": NaN')), "", ()),
            "empty": (self.write("empty.json", empty), "", ()),
            "unordered": (self.write("unordered.json", unordered), "slowest first", ()),
            "twice": (self.write("twice.json", twice), "twice", ()),
            "negative threshold": (self.write("ok1.json", report(BASE)), "", ("--threshold", "-1")),
            "nan threshold": (self.write("ok2.json", report(BASE)), "", ("--threshold", "nan")),
        }
        base = self.write("base.json", report(BASE))
        for label, (head, reason, extra) in cases.items():
            with self.subTest(label):
                result = self.run_compare(head, base, *extra)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertEqual(result.stdout, "")
                self.assertIn(reason, result.stderr)
                if not extra:
                    self.assertTrue(result.stderr.startswith("suite-timing: "), result.stderr)


class CompatibilityTest(unittest.TestCase):
    def test_the_runners_report_is_a_valid_head(self):
        results = [MemberResult(0, "tests/test_a.py", 0, 1.2, 1.0),
                   MemberResult(1, "tests/test_b.py", 0, 3.4, 2.0)]
        written = suite_runner.timing_report(results, jobs=2, wall_seconds=3.0)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "report.json"
            suite_runner.write_report(path, written)
            self.assertEqual(load_report(path), written)


if __name__ == "__main__":
    unittest.main()
