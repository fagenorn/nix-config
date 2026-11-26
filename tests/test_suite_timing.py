"""Tests for `agent_tools.delivery.suite_timing`, the suite-time comparison CI runs (issue 1385).

`CompareTest` and `SpeedFactorTest` call the module's functions on reports built
here; `CommandTest` runs `python -m agent_tools.delivery.suite_timing compare` as a
child process over report files in a temporary directory; `CompatibilityTest` loads a
report the suite runner wrote; `ObservedTest` runs `observed` over a stub forge and runs
the committed wrapper.
"""

import contextlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from agent_tools.delivery import suite_runner, suite_timing
from agent_tools.delivery.suite_runner import MemberResult
from agent_tools.delivery.suite_timing import (
    ReportError, compare, declared_shard_count, join_reports, load_report, load_shard_report,
    speed_factor, summary_line)

TIER = "integration"  # this module reads the git index and runs a wrapper

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


def shard_report(index: int, count: int, seconds: dict[str, float], failed=()) -> dict:
    """What the runner writes for one shard: `report(seconds)` plus the counts and the shard."""
    made = report(seconds)
    for row in made["timings"]:
        row["passed"] = row["member"] not in {f"tests/test_{name}.py" for name in failed}
    broken = sum(1 for row in made["timings"] if not row["passed"])
    return {**made, "members": len(seconds), "passed": len(seconds) - broken, "failed": broken,
            "jobs": 4, "wall_seconds": max(seconds.values()), "cpu_seconds": 0.0,
            "shard": index, "shard_count": count}


def write_artifact(root: Path, made: dict | str, attempt: int = 1, status: str = "success",
                   name: str | None = None) -> Path:
    shard = made["shard"] if isinstance(made, dict) else 0
    path = root / (name or f"suite-timing-shard-{shard}-attempt-{attempt}-{status}")
    path.mkdir(parents=True, exist_ok=True)
    (path / "suite-timing.json").write_text(
        made if isinstance(made, str) else json.dumps(made), encoding="utf-8")
    return path


def workflow(root: Path, shards: str = "1, 2") -> Path:
    path = root / "ci.yaml"
    path.write_text("\n".join([
        "jobs:", "  agent-workflow-tests-shard:", "    strategy:", "      matrix:",
        f"        shard: [{shards}]", "  agent-workflow-tests:",
        "    name: Agent Workflow Tests", ""]), encoding="utf-8")
    return path


def run_module(root: Path, *arguments: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "agent_tools.delivery.suite_timing", *arguments],
        capture_output=True, text=True, check=False, cwd=root,
        env={"PYTHONPATH": PYTHON_PATH, "PATH": "/usr/bin:/bin"})


def join(root: Path, needs: str = "success", shards_dir: Path | None = None
         ) -> subprocess.CompletedProcess:
    return run_module(
        root, "join", "--workflow", str(root / "ci.yaml"), "--shard-job",
        "agent-workflow-tests-shard", "--shards-dir", str(shards_dir or root / "shards"),
        "--out", str(root / "out" / "suite-timing.json"), "--needs-result", needs)


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

    def test_growth_exactly_at_the_threshold_is_within_it_whatever_the_float_error(self):
        # 64.4 - 4.4 is 60.00000000000001 in binary floating point; the reports say 60.0.
        base = report({"a": 4.4})
        head = report({"a": 4.4, "new": 60.0})
        self.assertEqual(head["member_seconds"], 64.4)
        comparison = compare(base, head)
        self.assertEqual(comparison.factor, 1.0)
        self.assertEqual(comparison.growth, 60.0)
        self.assertTrue(summary_line(head, comparison, threshold=60.0, base_label="main")
                        .startswith("Suite time changed by +60.0s over main, within the 60s "
                                    "threshold:"))

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

    def test_an_integer_too_large_for_a_float_is_a_bad_report_not_a_crash(self):
        huge = "1" + "0" * 400
        text = (f'{{"version": 1, "member_seconds": {huge}, "timings": '
                '[{"member": "tests/test_a.py", "seconds": 30.0}]}')
        slow = (f'{{"version": 1, "member_seconds": 30.0, "timings": '
                f'[{{"member": "tests/test_a.py", "seconds": {huge}}}]}}')
        good = self.write("good.json", report(BASE))
        for label, content in {"member_seconds": text, "seconds": slow}.items():
            with self.subTest(label):
                bad = self.write("bad.json", content)
                as_base = self.run_compare(good, bad)
                self.assertEqual(as_base.returncode, 0, as_base.stderr)
                self.assertEqual(as_base.stdout.splitlines()[0], NO_BASELINE)
                self.assertTrue(as_base.stderr.startswith("suite-timing: base: "), as_base.stderr)
                self.assertNotIn("Traceback", as_base.stderr)
                as_head = self.run_compare(bad, good)
                self.assertEqual(as_head.returncode, 2, as_head.stderr)
                self.assertEqual(as_head.stdout, "")
                self.assertTrue(as_head.stderr.startswith("suite-timing: "), as_head.stderr)
                self.assertNotIn("Traceback", as_head.stderr)

    def test_a_large_integer_that_fits_a_float_compares_without_overflow(self):
        big = 10 ** 300
        make = lambda: {"version": 1, "member_seconds": big, "timings": [
            {"member": "tests/test_a.py", "seconds": big}]}
        comparison = compare(make(), make())
        self.assertEqual(comparison.factor, 1.0)
        self.assertEqual(comparison.growth, 0.0)


class JoinTest(unittest.TestCase):
    def test_join_reports_orders_rows_slowest_first_ties_by_shard(self):
        joined = join_reports([shard_report(2, 2, {"c": 5, "d": 1}),
                               shard_report(1, 2, {"a": 5, "b": 2})], 2)
        self.assertEqual([row["member"] for row in joined["timings"]],
                         ["tests/test_a.py", "tests/test_c.py", "tests/test_b.py",
                          "tests/test_d.py"])
        self.assertEqual(joined["shard_summaries"], [
            {"shard": 1, "members": 2, "failed": 0, "wall_seconds": 5},
            {"shard": 2, "members": 2, "failed": 0, "wall_seconds": 5}])
        self.assertEqual(list(joined), [
            "version", "members", "passed", "failed", "jobs", "shard_count", "wall_seconds",
            "member_seconds", "cpu_seconds", "timings", "shard_summaries"])

    def test_the_declared_shard_count_is_read_from_the_shard_job_only(self):
        with tempfile.TemporaryDirectory() as directory:
            text = workflow(Path(directory)).read_text(encoding="utf-8")
        job = "agent-workflow-tests-shard"
        self.assertEqual(declared_shard_count(text, job), 2)
        self.assertEqual(declared_shard_count(text + "        shard: [1, 2, 3]\n", job), 2)
        cases = {
            "no shard job": (text, "other-job"),
            "two matrix lines": (text.replace(
                "    strategy:", "    strategy:\n      matrix:\n        shard: [1, 2]"), job),
            "not from 1": (text.replace("[1, 2]", "[2, 3]"), job),
        }
        for label, (made, name) in cases.items():
            with self.subTest(label), self.assertRaises(ReportError):
                declared_shard_count(made, name)


class JoinCommandTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.shards = self.root / "shards"
        self.out = self.root / "out" / "suite-timing.json"

    def lines(self, result: subprocess.CompletedProcess) -> list[str]:
        return result.stdout.splitlines()

    def test_the_shard_reports_join_into_one_report_the_compare_reads(self):
        workflow(self.root)
        write_artifact(self.shards, shard_report(1, 2, {"a": 30, "b": 10}))
        write_artifact(self.shards, shard_report(2, 2, {"c": 20, "d": 15}))
        result = join(self.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        joined = load_report(self.out)
        self.assertEqual([row["member"] for row in joined["timings"]],
                         ["tests/test_a.py", "tests/test_c.py", "tests/test_d.py",
                          "tests/test_b.py"])
        self.assertEqual((joined["member_seconds"], joined["members"], joined["shard_count"],
                          joined["wall_seconds"]), (75, 4, 2, 30))
        self.assertEqual(self.lines(result), [
            "suite-timing: shard 1 of 2 passed: 2 members in 30s",
            "suite-timing: shard 2 of 2 passed: 2 members in 20s",
            "suite-timing: every shard passed"])
        compared = run_module(self.root, "compare", "--head", str(self.out), "--base",
                              str(self.out), "--base-label", "main")
        self.assertEqual(compared.returncode, 0, compared.stderr)

    def test_a_failed_shard_fails_the_join_naming_it_and_still_writes_the_report(self):
        workflow(self.root)
        write_artifact(self.shards, shard_report(1, 2, {"a": 30, "b": 10}))
        write_artifact(self.shards, shard_report(2, 2, {"c": 20, "d": 15}, failed=("c",)),
                       status="failure")
        result = join(self.root, needs="failure")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("suite-timing: shard 2 of 2 failed: 1 of 2 members failed: "
                      "tests/test_c.py", self.lines(result))
        self.assertEqual(self.lines(result)[-1], "suite-timing: failed shards: 2")
        self.assertEqual(load_report(self.out)["failed"], 1)

    def test_shards_that_left_no_report_are_named_from_the_declaration(self):
        workflow(self.root, "1, 2, 3, 4")
        result = join(self.root, needs="failure")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(self.lines(result), [
            *(f"suite-timing: shard {i} of 4 failed: it wrote no report" for i in range(1, 5)),
            "suite-timing: failed shards: 1, 2, 3, 4"])
        self.assertFalse(self.out.exists())

    def test_a_shard_whose_job_failed_is_named_though_its_report_passed(self):
        workflow(self.root)
        write_artifact(self.shards, shard_report(1, 2, {"a": 30}))
        write_artifact(self.shards, shard_report(2, 2, {"c": 20}), status="failure")
        result = join(self.root, needs="failure")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("suite-timing: shard 2 of 2 failed: its job had failed when it "
                      "uploaded a passing report", self.lines(result))
        self.assertEqual(self.lines(result)[-1], "suite-timing: failed shards: 2")
        self.assertTrue(self.out.exists())

    def test_a_rerun_attempt_supersedes_the_earlier_one(self):
        workflow(self.root)
        write_artifact(self.shards, shard_report(1, 2, {"a": 30}))
        write_artifact(self.shards, shard_report(2, 2, {"c": 20}, failed=("c",)),
                       attempt=1, status="failure")
        write_artifact(self.shards, shard_report(2, 2, {"c": 20}), attempt=2)
        result = join(self.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.lines(result)[-1], "suite-timing: every shard passed")
        self.assertEqual(load_report(self.out)["failed"], 0)

    def test_an_invalid_incomplete_or_inconsistent_set_fails_and_writes_nothing(self):
        one, two = (shard_report(1, 2, {"a": 3, "b": 1}), shard_report(2, 2, {"c": 2, "d": 1}))

        def arrange(first=one, second=two, extra=None):
            def made():
                write_artifact(self.shards, first)
                if second is not None:
                    write_artifact(self.shards, second)
                for name in extra or ():
                    (self.shards / name).mkdir()
            return made

        def broken(**changes):
            return {**two, **changes}

        def unreadable():
            write_artifact(self.shards, shard_report(1, 1, {"a": 1}))
            for shard in (2, 3, 4):
                write_artifact(self.shards, '{"version": 1', name=(
                    f"suite-timing-shard-{shard}-attempt-1-success"))

        reasoned = "suite-timing: shard 2 of 2 failed: its report is invalid: "
        cases = {
            "wrong shard and unreadable files": (
                "1, 2, 3, 4", unreadable, [
                    "suite-timing: shard 1 of 4 failed: its report is invalid: shard 1 of 1 "
                    "in artifact suite-timing-shard-1-attempt-1-success, expected 1 of 4"],
                "suite-timing: failed shards: 1, 2, 3, 4"),
            "a shard without a report": (
                "1, 2, 3", arrange(first=shard_report(1, 3, {"a": 3}), second=None),
                ["suite-timing: shard 3 of 3 failed: it wrote no report"],
                "suite-timing: failed shards: 2, 3"),
            "failed count against the rows": (
                "1, 2", arrange(second=broken(
                    timings=[{**row, "passed": row["member"] != "tests/test_c.py"}
                             for row in two["timings"]], passed=2)),
                [reasoned + "failed is 0 but 1 timing rows did not pass"],
                "suite-timing: failed shards: 2"),
            "passed count": (
                "1, 2", arrange(second=broken(passed=5)),
                [reasoned + "passed is 5, not members 2 minus failed 0"],
                "suite-timing: failed shards: 2"),
            "passed that is text": (
                "1, 2", arrange(second=broken(passed="2")),
                [reasoned + "passed is '2', not an integer"],
                "suite-timing: failed shards: 2"),
            "members against the rows": (
                "1, 2", arrange(second=broken(members=3)),
                [reasoned + "members is 3 but timings has 2 rows"],
                "suite-timing: failed shards: 2"),
            "an artifact of no shard": (
                "1, 2", arrange(extra=("suite-timing-shard-x",)),
                [], "suite-timing: artifact suite-timing-shard-x is not "
                    "suite-timing-shard-<n>-attempt-<a>-<success|failure>"),
            "one shard and attempt twice": (
                "1, 2", arrange(extra=("suite-timing-shard-2-attempt-1-failure",)),
                [], "suite-timing: artifacts suite-timing-shard-2-attempt-1-failure and "
                    "suite-timing-shard-2-attempt-1-success are both shard 2 attempt 1"),
            "a shard the workflow does not declare": (
                "1, 2", arrange(extra=("suite-timing-shard-3-attempt-1-success",)),
                [], "suite-timing: artifact suite-timing-shard-3-attempt-1-success is shard 3, "
                    "the workflow declares 2"),
            "a member in two shards": (
                "1, 2", arrange(second=shard_report(2, 2, {"a": 2, "c": 1})),
                [], "suite-timing: member tests/test_a.py is in shard 1 and shard 2"),
            "a matrix that skips a shard": (
                "1, 2, 4", arrange(),
                [], f"suite-timing: {self.root / 'ci.yaml'}: the matrix shards are "
                    "[1, 2, 4], not 1 to 3"),
        }
        for label, (shards, setup, expected, last) in cases.items():
            with self.subTest(label):
                shutil.rmtree(self.shards, ignore_errors=True)
                self.shards.mkdir()
                workflow(self.root, shards)
                setup()
                result = join(self.root)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertFalse(self.out.exists())
                for line in expected:
                    self.assertIn(line, self.lines(result))
                if label == "wrong shard and unreadable files":
                    self.assertTrue(any(
                        line.startswith("suite-timing: shard 2 of 4 failed: its report is "
                                        "invalid: ") for line in self.lines(result)))
                self.assertEqual(self.lines(result)[-1], last)

    def test_shard_jobs_that_did_not_succeed_fail_the_join_though_every_report_passed(self):
        workflow(self.root)
        write_artifact(self.shards, shard_report(1, 2, {"a": 30}))
        write_artifact(self.shards, shard_report(2, 2, {"c": 20}))
        for outcome in ("failure", "cancelled", "skipped"):
            with self.subTest(outcome):
                result = join(self.root, needs=outcome)
                self.assertEqual(result.returncode, 1, result.stderr)
                lines = self.lines(result)
                self.assertIn(f"suite-timing: the shard jobs concluded {outcome} though every "
                              "shard uploaded a passing report from a passing job", lines)
                self.assertEqual(lines[-1], "suite-timing: unconfirmed shards: 1, 2")
                self.assertTrue(self.out.exists())
                self.out.unlink()


class CompatibilityTest(unittest.TestCase):
    def test_growth_just_over_the_threshold_survives_the_runners_report(self):
        base = [MemberResult(0, "tests/test_a.py", 0, 10.0, 1.0),
                MemberResult(1, "tests/test_b.py", 0, 20.0, 1.0)]
        head = [*base, MemberResult(2, "tests/test_new.py", 0, 60.04, 1.0)]
        with tempfile.TemporaryDirectory() as directory:
            reports = {}
            for label, results in (("base", base), ("head", head)):
                path = Path(directory) / f"{label}.json"
                suite_runner.write_report(
                    path, suite_runner.timing_report(results, jobs=2, wall_seconds=1.0))
                reports[label] = load_report(path)
        comparison = compare(reports["base"], reports["head"])
        self.assertGreater(comparison.growth, 60.0)
        self.assertTrue(summary_line(reports["head"], comparison, threshold=60.0,
                                     base_label="main")
                        .startswith("Suite time grew by 60.0s over main, past the 60s "
                                    "threshold:"))

    def test_the_runners_report_is_a_valid_head(self):
        results = [MemberResult(0, "tests/test_a.py", 0, 1.2, 1.0),
                   MemberResult(1, "tests/test_b.py", 0, 3.4, 2.0)]
        written = suite_runner.timing_report(results, jobs=2, wall_seconds=3.0)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "report.json"
            suite_runner.write_report(path, written)
            self.assertEqual(load_report(path), written)

    def test_a_shard_report_the_runner_writes_is_a_valid_shard_report(self):
        results = [MemberResult(0, "tests/test_a.py", 0, 1.0, 0.5),
                   MemberResult(1, "tests/test_b.py", 1, 2.0, 0.5)]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            suite_runner.write_report(path, suite_runner.timing_report(
                results, jobs=4, wall_seconds=2.0, shard=(1, 2)))
            loaded = load_shard_report(path)
            self.assertEqual((loaded["shard"], loaded["shard_count"], loaded["failed"]),
                             (1, 2, 1))
            suite_runner.write_report(path, suite_runner.timing_report(
                results, jobs=4, wall_seconds=2.0))
            with self.assertRaisesRegex(ReportError, "shard"):
                load_shard_report(path)


MERGE = "a" * 40
LISTING = "repos/o/r/actions/workflows/ci.yaml/runs?branch=main&event=push"
START = datetime(2026, 11, 27, 10, 0, 0, tzinfo=timezone.utc)
OBSERVED = ["observed", "--repo", "o/r", "--branch", "main", "--merge", MERGE, "--runs", "3",
            "--before-seconds", "1222", "--target-seconds", "480"]
WRAPPER = "home/common/verify-pending/checks/agent-workflow-tests-wall"


def stamp(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


class ObservedWorld:
    """A forge for `observed`: the merge run 100 and `after` runs a minute apart, each with attempt 1 jobs."""

    def __init__(self, after=2, finals=None):
        self.ids = list(range(100, 101 + after))
        self.finals = {100: 420, 101: 540, 102: 360, **(finals or {})}
        self.status = {}
        self.jobs = {}

    def created(self, run_id):
        return START + timedelta(minutes=run_id - 100)

    def run(self, run_id):
        return {"id": run_id, "head_sha": MERGE if run_id == 100 else f"{run_id:040x}",
                "created_at": stamp(self.created(run_id)), "status": self.status.get(run_id, "completed"),
                "run_attempt": 1}

    def listing(self, run_id):
        made = self.created(run_id)
        offset = self.finals.get(run_id, 60)

        def job(name, **fields):
            return {"name": name, "status": "completed", "conclusion": "success", **fields}
        return {"jobs": [job("Nix Eval"),
                         job("Agent Workflow Tests Shard 1", started_at=stamp(made + timedelta(seconds=5))),
                         job("Agent Workflow Tests Shard 2", started_at=stamp(made)),
                         job("Agent Workflow Tests", completed_at=stamp(made + timedelta(seconds=offset)))]}

    def gets(self):
        gets = {f"{LISTING}&head_sha={MERGE}&per_page=100": {"workflow_runs": [self.run(100)]}}
        for run_id in self.ids:
            gets[f"repos/o/r/actions/runs/{run_id}/attempts/1/jobs?per_page=100"] = \
                self.jobs.get(run_id) or self.listing(run_id)
        return gets

    def pages(self):
        runs = [self.run(run_id) for run_id in reversed(self.ids)]
        return {f"{LISTING}&created=>={stamp(START)}&per_page=100":
                [{"workflow_runs": runs[at:at + 100]} for at in range(0, len(runs), 100)]}


def call(argv, gets, pages):
    """(exit code, parsed stdout line or None, stderr, paths read) of `suite_timing.main(argv)` over a stub forge."""
    read = []

    def api_get(path):
        read.append(path)
        if isinstance(gets, Exception):
            raise gets
        return gets[path]

    def api_pages(path):
        read.append(path)
        return pages[path]
    out, err = io.StringIO(), io.StringIO()
    with mock.patch.object(suite_timing.forge_api, "api_get", side_effect=api_get), \
            mock.patch.object(suite_timing.forge_api, "api_pages", side_effect=api_pages), \
            contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = suite_timing.main(argv)
        except SystemExit as stop:
            code = stop.code
    return code, (json.loads(out.getvalue()) if out.getvalue() else None), err.getvalue(), read


class ObservedTest(unittest.TestCase):
    def observe(self, world, argv=OBSERVED):
        return call(argv, world.gets(), world.pages())

    def test_the_first_runs_from_the_merge_are_timed_from_first_shard_to_final_job(self):
        code, line, _, _ = self.observe(ObservedWorld(after=2))

        self.assertEqual(code, 0)
        self.assertEqual(line["state"], "met")
        self.assertEqual([row["run"] for row in line["runs"]], [100, 101, 102])
        self.assertEqual([row["wall_seconds"] for row in line["runs"]], [420, 540, 360])
        self.assertEqual([row["change_seconds"] for row in line["runs"]], [-802, -682, -862])
        self.assertEqual([row["conclusion"] for row in line["runs"]], ["success"] * 3)
        self.assertEqual((line["median_seconds"], line["target_seconds"]), (420, 480))

        at_target = [*OBSERVED[:-1], "420"]
        self.assertEqual(self.observe(ObservedWorld(after=2), at_target)[:2][0], 1)
        self.assertEqual(self.observe(ObservedWorld(after=2), at_target)[1]["state"], "not_met")

        code, line, _, _ = self.observe(ObservedWorld(after=1))
        self.assertEqual((code, line["state"], line["median_seconds"]), (75, "not_yet", None))

        running = ObservedWorld(after=2)
        running.status[102] = "in_progress"
        running.jobs[102] = running.listing(102)
        running.jobs[102]["jobs"][-1]["status"] = "in_progress"
        self.assertEqual(self.observe(running)[:2][0], 75)

        absent = ObservedWorld(after=2)
        gets = absent.gets()
        gets[f"{LISTING}&head_sha={MERGE}&per_page=100"] = {"workflow_runs": []}
        self.assertEqual(call(OBSERVED, gets, absent.pages())[0], 75)

        bare = ObservedWorld(after=2)
        bare.jobs[101] = {"jobs": [bare.listing(101)["jobs"][-1]]}
        code, line, err, _ = self.observe(bare)
        self.assertEqual((code, line["state"]), (1, "not_met"))
        self.assertIn("101", err)

    def test_a_late_reading_after_many_newer_runs_finds_the_same_window(self):
        world = ObservedWorld(after=105, finals={run_id: 60 for run_id in range(103, 206)})

        code, line, _, read = self.observe(world)

        self.assertEqual(code, 0)
        self.assertEqual([row["run"] for row in line["runs"]], [100, 101, 102])
        self.assertEqual(line["median_seconds"], 420)
        self.assertIn(f"{LISTING}&head_sha={MERGE}&per_page=100", read)
        self.assertEqual([path for path in read if "created=>=" in path],
                         [f"{LISTING}&created=>={stamp(START)}&per_page=100"])

    def test_each_run_is_measured_on_its_first_attempt(self):
        world = ObservedWorld(after=2)
        gets, pages = world.gets(), world.pages()
        pages[f"{LISTING}&created=>={stamp(START)}&per_page=100"][0]["workflow_runs"][1]["run_attempt"] = 2
        second = world.listing(101)
        second["jobs"] = [second["jobs"][-1]]
        gets["repos/o/r/actions/runs/101/attempts/2/jobs?per_page=100"] = second

        code, line, _, read = call(OBSERVED, gets, pages)

        self.assertEqual(code, 0)
        self.assertEqual([row["wall_seconds"] for row in line["runs"]], [420, 540, 360])
        self.assertFalse([path for path in read if "/attempts/2/" in path])

    def test_bad_arguments_or_an_unreadable_listing_exit_2(self):
        world = ObservedWorld(after=2)
        bad_page = {f"{LISTING}&created=>={stamp(START)}&per_page=100": [{"workflow_runs": "x"}]}
        cases = [
            (["--repo", "bad"], world.gets(), world.pages()),
            (["--repo", "o/r\n"], world.gets(), world.pages()),
            (["--merge", "abc"], world.gets(), world.pages()),
            (["--runs", "0"], world.gets(), world.pages()),
            (["--target-seconds", "0"], world.gets(), world.pages()),
            (["--before-seconds", "nan"], world.gets(), world.pages()),
            ([], world.gets(), bad_page),
            ([], suite_timing.forge_api.ForgeError("gh_failed", "x"), world.pages()),
        ]
        for override, gets, pages in cases:
            with self.subTest(override=override, gets=type(gets).__name__):
                argv = list(OBSERVED)
                for flag, value in zip(override[::2], override[1::2]):
                    argv[argv.index(flag) + 1] = value
                code, line, err, _ = call(argv, gets, pages)
                self.assertEqual((code, line), (2, None))
                self.assertTrue(err.startswith("suite-timing: "), err)

    def test_the_check_is_committed_executable_and_runs_the_observed_command(self):
        staged = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "ls-files", "-s", WRAPPER],
            capture_output=True, text=True, check=True).stdout
        bare = subprocess.run(
            ["/bin/sh", str(REPO_ROOT / WRAPPER)], cwd=REPO_ROOT, capture_output=True,
            text=True, stdin=subprocess.DEVNULL, timeout=60)
        helped = subprocess.run(
            ["/bin/sh", str(REPO_ROOT / WRAPPER), "--help"], cwd=REPO_ROOT, capture_output=True,
            text=True, stdin=subprocess.DEVNULL, timeout=60)

        self.assertTrue(staged.startswith("100755"))
        self.assertEqual(bare.returncode, 2)
        self.assertIn("--repo", bare.stderr)
        self.assertEqual(helped.returncode, 0)
        self.assertIn("--target-seconds", helped.stdout)


if __name__ == "__main__":
    unittest.main()
