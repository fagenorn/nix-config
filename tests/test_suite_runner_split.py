"""Tests for the suite runner's split of a long member into class parts.

The end-to-end cases run `suite_runner.run_suite` in this process over stub members written
into a fresh work directory; the stubs' tests append one line to `SPLIT_TEST_RECORD` naming
their id and the part variables they ran with, and the two-part case meets at a filesystem
barrier instead of sleeping. The planning, ordering, joining and failure-naming cases call the
module's functions directly.
"""

from __future__ import annotations

import collections
import io
import json
import os
import re
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

from agent_tools.console.permit import _FAILED_MEMBER
from agent_tools.delivery import suite_runner
from agent_tools.delivery.suite_runner import MemberResult
from agent_tools.system.siblings import sibling_argv

TIER = "fast"

REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON_PATH = str(REPO_ROOT / "python")

RECORDING = textwrap.dedent('''\
    import os
    import unittest


    class Recording(unittest.TestCase):
        def note(self):
            values = [os.environ.get(name, "") for name in (
                "SUITE_RUNNER_PART", "SUITE_RUNNER_PART_DIR", "SUITE_RUNNER_PART_MEMBER")]
            line = " ".join([self.id(), *values]) + "\\n"
            descriptor = os.open(os.environ["SPLIT_TEST_RECORD"],
                                 os.O_WRONLY | os.O_APPEND | os.O_CREAT)
            try:
                os.write(descriptor, line.encode())
            finally:
                os.close(descriptor)
            if os.environ.get("SPLIT_TEST_FAIL") == type(self).__name__:
                self.fail("deliberate failure")
''')

BIG_MEMBER = RECORDING + textwrap.dedent('''\


    class A(Recording):
        def test_a1(self):
            self.note()

        def test_a2(self):
            self.note()


    class B(Recording):
        def test_b(self):
            self.note()


    class C(Recording):
        def test_c(self):
            self.note()


    class D(A):
        pass
''')

SMALL_MEMBER = RECORDING + textwrap.dedent('''\


    class X(Recording):
        def test_x(self):
            self.note()


    class Y(Recording):
        def test_y(self):
            self.note()
''')

PAIR_MEMBER = textwrap.dedent('''\
    import os
    import time
    import unittest
    from pathlib import Path

    LIVE = Path(os.environ["SPLIT_TEST_BARRIER"]) / "live"


    class Base(unittest.TestCase):
        def meet(self):
            (LIVE / type(self).__name__).touch()
            deadline = time.monotonic() + 60
            while len(list(LIVE.iterdir())) < 2:
                if time.monotonic() > deadline:
                    self.fail("the barrier was not met within 60 s")
                time.sleep(0.01)


    class P(Base):
        def test_p(self):
            self.meet()


    class Q(Base):
        def test_q(self):
            self.meet()
''')

TIMINGS = {"test_big.py": 400.0, "test_small.py": 10.0}
STARTED = re.compile(r"^suite-runner: start (\S+)$", re.MULTILINE)
ROW = re.compile(r"^suite-runner: +\d+\.\ds wall +\d+\.\ds cpu (passed|failed) \S+$",
                 re.MULTILINE)

BIG_IDS = {"test_big.A.test_a1": 1, "test_big.A.test_a2": 1, "test_big.B.test_b": 1,
           "test_big.C.test_c": 1, "test_big.D.test_a1": 1, "test_big.D.test_a2": 1}
SMALL_IDS = {"test_small.X.test_x": 1, "test_small.Y.test_y": 1}


class SplitCase(unittest.TestCase):
    def setUp(self) -> None:
        raw = tempfile.TemporaryDirectory()
        self.addCleanup(raw.cleanup)
        root = Path(raw.name).resolve()
        self.work = root / "work"
        self.work.mkdir()
        self.record = root / "record"
        self.barrier = root / "barrier"
        (self.barrier / "live").mkdir(parents=True)

    def write(self, name: str, source: str) -> str:
        (self.work / name).write_text(source, encoding="utf-8")
        return name

    def environment(self, **extra: str) -> dict[str, str]:
        inherited = os.environ.get("PYTHONPATH")
        return {**os.environ, "SPLIT_TEST_RECORD": str(self.record),
                "SPLIT_TEST_BARRIER": str(self.barrier),
                "PYTHONPATH": os.pathsep.join([PYTHON_PATH, *([inherited] if inherited else [])]),
                **extra}

    def run_members(self, members, timings, *, jobs: int = 4, **extra: str) -> tuple[int, str]:
        out = io.BytesIO()
        cwd = os.getcwd()
        os.chdir(self.work)
        try:
            with mock.patch.dict(os.environ, self.environment(**extra)):
                code = suite_runner.run_suite(members, jobs=jobs, out=out, timings=timings)
        finally:
            os.chdir(cwd)
        return code, out.getvalue().decode()

    def run_big(self, **extra: str) -> tuple[int, str]:
        members = [self.write("test_big.py", BIG_MEMBER), self.write("test_small.py", SMALL_MEMBER)]
        return self.run_members(members, TIMINGS, **extra)

    def records(self) -> list[list[str]]:
        if not self.record.exists():
            return []
        return [line.split(" ") for line in self.record.read_text().splitlines()]

    def recorded_ids(self) -> collections.Counter:
        return collections.Counter(fields[0] for fields in self.records())

    @staticmethod
    def started(output: str) -> list[str]:
        return STARTED.findall(output)


class SplitRunTest(SplitCase):
    def test_a_member_over_the_bound_runs_as_parts_that_run_every_test_exactly_once(self):
        code, output = self.run_big()
        self.assertEqual(code, 0, output)
        self.assertEqual(set(self.started(output)),
                         {"test_big.py::A", "test_big.py::D", "test_big.py::B,C", "test_small.py"})
        self.assertEqual(self.recorded_ids(), collections.Counter({**BIG_IDS, **SMALL_IDS}))

    def test_two_parts_of_one_member_run_at_the_same_time(self):
        member = self.write("test_pair.py", PAIR_MEMBER)
        code, output = self.run_members([member], {"test_pair.py": 400.0}, jobs=2)
        self.assertEqual(set(self.started(output)), {"test_pair.py::P", "test_pair.py::Q"})
        self.assertEqual(code, 0, output)


class PlanUnitsTest(SplitCase):
    def test_only_a_member_over_the_bound_with_two_classes_or_more_is_split(self):
        three = [("A", 1), ("B", 1), ("C", 1)]
        rows = [
            ("m.py", 400.0, three, 3, True),
            ("m.py", 150.0, three, 1, False),
            ("m.py", None, three, 1, False),
            ("m.py", 900.0, [("A", 5)], 1, True),
            ("m.py", 900.0, [], 1, True),
            ("run.sh", 900.0, three, 1, False),
            ("m.py", 900.0, three, 3, True),
            ("m.py", 400.0, [(name, 1) for name in "ABCDE"], 3, True),
        ]
        for member, seconds, listing, parts, called in rows:
            with self.subTest(member=member, seconds=seconds, listing=listing):
                asked = []

                def classes(name, listing=listing):
                    asked.append(name)
                    return listing

                timings = {} if seconds is None else {member: seconds}
                units = suite_runner.plan_units([member], timings, classes)
                self.assertEqual(len(units), parts)
                self.assertEqual(asked, [member] if called else [])
                if parts == 1:
                    unit = units[0]
                    self.assertEqual(unit.classes, ())
                    self.assertEqual(unit.excluded, ())
                    self.assertEqual(unit.seconds, timings.get(member))
                    self.assertEqual(suite_runner.unit_command(unit),
                                     suite_runner.member_command(member))

    def test_classes_are_grouped_by_test_count_and_part_one_excludes_the_other_parts_classes(self):
        units = suite_runner.plan_units(
            ["m.py"], {"m.py": 400.0}, lambda member: [("A", 4), ("B", 1), ("C", 1), ("D", 2)])
        self.assertEqual([unit.label for unit in units], ["m.py::A", "m.py::D", "m.py::B,C"])
        self.assertEqual([unit.seconds for unit in units], [200.0, 100.0, 100.0])
        self.assertEqual(units[0].excluded, ("B", "C", "D"))
        self.assertEqual(units[1].excluded, ())
        self.assertEqual(
            suite_runner.unit_command(units[0]),
            [*sibling_argv("delivery.suite_part"), "m.py",
             "--except", "B", "--except", "C", "--except", "D"])
        self.assertEqual(
            suite_runner.unit_command(units[2]),
            [*sibling_argv("delivery.suite_part"), "m.py", "--only", "B", "--only", "C"])

    def test_the_listing_names_only_the_classes_the_loader_runs(self):
        mixin = textwrap.dedent('''\
            import unittest


            class Helper:
                def test_like(self):
                    pass


            class OnlyTest(unittest.TestCase):
                def test_one(self):
                    pass
        ''')
        hooked = textwrap.dedent('''\
            import unittest


            class F(unittest.TestCase):
                def test_f(self):
                    pass


            class G(unittest.TestCase):
                def test_g(self):
                    pass


            def load_tests(loader, standard_tests, pattern):
                return unittest.TestSuite(loader.loadTestsFromTestCase(F))
        ''')
        two = textwrap.dedent('''\
            import unittest


            class P(unittest.TestCase):
                def test_p1(self):
                    pass

                def test_p2(self):
                    pass


            class Q(unittest.TestCase):
                def test_q(self):
                    pass
        ''')
        rows = [
            ("test_mixin.py", mixin, [("OnlyTest", 1)]),
            ("test_hooked.py", hooked, [("F", 1)]),
            ("test_two.py", two, [("P", 2), ("Q", 1)]),
            ("test_broken.py", "import split_missing_module\n", []),
            ("run.sh", "exit 0\n", []),
        ]
        for name, source, expected in rows:
            with self.subTest(member=name):
                self.write(name, source)
                self.assertEqual(
                    suite_runner.test_classes(name, self.environment(), self.work), expected)
        code, output = self.run_members(["test_mixin.py"], {"test_mixin.py": 400.0})
        self.assertEqual(code, 0, output)
        self.assertEqual(self.started(output), ["test_mixin.py"])


class UnitOrderTest(SplitCase):
    def test_unknown_units_start_first_then_the_longest_estimate_ties_in_unit_order(self):
        units = [suite_runner.Unit(0, "a.py", seconds=50.0), suite_runner.Unit(1, "b.py"),
                 suite_runner.Unit(2, "c.py", seconds=20.0), suite_runner.Unit(3, "d.py", seconds=50.0)]
        self.assertEqual(suite_runner.unit_order(units), [1, 0, 3, 2])
        members = ["a.py", "b.py", "c.py", "d.py", "e.py"]
        timings = {"a.py": 5.0, "b.py": 50.0, "d.py": 5.0, "e.py": 20.0}
        whole = suite_runner.plan_units(members, timings, lambda member: [])
        self.assertEqual([whole[i].member_index for i in suite_runner.unit_order(whole)],
                         suite_runner.schedule_order(members, timings))


class JoinTest(SplitCase):
    def test_join_sums_the_parts_seconds_and_takes_the_first_failing_parts_exit(self):
        units = [suite_runner.Unit(0, "m.py", classes=("A",), excluded=("B", "C"), part=1, parts=3),
                 suite_runner.Unit(0, "m.py", classes=("B",), part=2, parts=3),
                 suite_runner.Unit(0, "m.py", classes=("C",), part=3, parts=3),
                 suite_runner.Unit(1, "w.py")]
        results = [MemberResult(0, "m.py::A", 0, 1.25, 0.5),
                   MemberResult(1, "m.py::B", 1, 2.5, 1.0),
                   MemberResult(2, "m.py::C", -9, 4.0, 1.5),
                   MemberResult(3, "w.py", 0, 0.75, 0.25)]
        self.assertEqual(suite_runner.join_results(["m.py", "w.py"], units, results),
                         [MemberResult(0, "m.py", 1, 7.75, 3.0),
                          MemberResult(1, "w.py", 0, 0.75, 0.25)])

    def test_a_split_run_reports_one_table_row_and_one_report_row_per_member(self):
        code, output = self.run_big(SUITE_RUNNER_REPORT="report.json")
        self.assertEqual(code, 0, output)
        rows = [line for line in output.splitlines() if ROW.match(line)]
        self.assertEqual(len(rows), 2, output)
        self.assertFalse([row for row in rows if "::" in row])
        self.assertTrue(any(line.startswith("suite-runner: summary members=2 passed=2 failed=0 ")
                            for line in output.splitlines()), output)
        report = json.loads((self.work / "report.json").read_text())
        self.assertEqual(report["members"], 2)
        self.assertEqual({row["member"] for row in report["timings"]},
                         {"test_big.py", "test_small.py"})


class FailureTest(SplitCase):
    def test_a_failing_part_names_the_member_and_the_class_that_failed(self):
        rows = [("C", "test_big.py::B,C", "test_big.py::C"),
                ("D", "test_big.py::D", "test_big.py::D")]
        for failing, label, expected in rows:
            with self.subTest(failing=failing):
                self.record.unlink(missing_ok=True)
                code, output = self.run_big(SPLIT_TEST_FAIL=failing)
                lines = output.splitlines()
                self.assertEqual(code, 1, output)
                self.assertTrue(
                    re.search(r"^suite-runner: end " + re.escape(label)
                              + r" failed exit=1 \d+\.\ds$", output, re.MULTILINE), output)
                at = lines.index("suite-runner: failed test_big.py")
                self.assertEqual(lines[at + 1], f"suite-runner: failed part {expected}")
                self.assertEqual(
                    [line for line in lines if line.startswith("suite-runner: failed part ")],
                    [f"suite-runner: failed part {expected}"])
                self.assertEqual(_FAILED_MEMBER.findall(output), ["test_big.py"])

    def test_the_failed_part_line_falls_back_to_the_parts_label(self):
        part = suite_runner.Unit(0, "m.py", classes=("A",), excluded=("B",), part=1, parts=2)
        failed = MemberResult(0, "m.py::A", 1, 1.0, 1.0)
        passed = MemberResult(0, "m.py::A", 0, 1.0, 1.0)
        rows = [
            (part, failed, b"x\nsuite-part: failed classes D\n", "m.py::D"),
            (part, failed, b"suite-part: failed classes A\nsuite-part: failed classes D,E\n",
             "m.py::D,E"),
            (part, failed, b"Killed\n", "m.py::A"),
            (part, passed, b"suite-part: failed classes D\n", None),
            (suite_runner.Unit(0, "m.py"), MemberResult(0, "m.py", 1, 1.0, 1.0),
             b"x\nsuite-part: failed classes D\n", None),
        ]
        for unit, result, output, expected in rows:
            with self.subTest(output=output, passed=result.passed, whole=not unit.classes):
                self.assertEqual(suite_runner.part_failure(unit, result, output), expected)


class SerialTest(SplitCase):
    def test_one_job_runs_a_member_over_the_bound_whole(self):
        code, output = self.run_big_serial()
        self.assertEqual(code, 0, output)
        self.assertEqual(self.started(output), ["test_big.py", "test_small.py"])
        self.assertEqual(self.recorded_ids(), collections.Counter({**BIG_IDS, **SMALL_IDS}))

    def run_big_serial(self) -> tuple[int, str]:
        members = [self.write("test_big.py", BIG_MEMBER), self.write("test_small.py", SMALL_MEMBER)]
        return self.run_members(members, TIMINGS, jobs=1)


class PartEnvironmentTest(SplitCase):
    def test_each_part_gets_its_number_and_the_members_shared_directory_and_path(self):
        code, output = self.run_big()
        self.assertEqual(code, 0, output)
        numbers = {}
        directories = set()
        members = set()
        for test_id, number, directory, member in self.records():
            if test_id.startswith("test_big."):
                numbers.setdefault(test_id.split(".")[1], set()).add(number)
                directories.add(directory)
                members.add(member)
            else:
                self.assertEqual((number, directory, member), ("", "", ""))
        self.assertEqual(numbers, {"A": {"1/3"}, "D": {"2/3"}, "B": {"3/3"}, "C": {"3/3"}})
        self.assertEqual(len(directories), 1)
        directory = directories.pop()
        self.assertTrue(directory.endswith("/0"), directory)
        self.assertEqual(members, {str((self.work / "test_big.py").resolve())})
        self.assertFalse(os.path.exists(directory))
        parent = {suite_runner.PART_ENV: "1/2", suite_runner.PART_DIR_ENV: "/x",
                  suite_runner.PART_MEMBER_ENV: "/y", "KEEP": "1"}
        environment = suite_runner.member_environment(parent, "/cache")
        for name in (suite_runner.PART_ENV, suite_runner.PART_DIR_ENV,
                     suite_runner.PART_MEMBER_ENV):
            self.assertNotIn(name, environment)
        self.assertEqual(environment["KEEP"], "1")


if __name__ == "__main__":
    unittest.main()
