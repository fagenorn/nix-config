"""Tests for `agent_tools.delivery.suite_part`, the entry that runs or lists some classes of one member.

Each case writes a stub member into a fresh work directory and starts
`python -m agent_tools.delivery.suite_part` there as a child process. The stub's tests
append their id to the file `SUITE_PART_RECORD` names, so a case reads what ran, in what
order, and whether a fixture ran at all. `SUITE_PART_FAIL` names the classes (comma-separated; or `module`,
or `E-setup`) whose test, fixture or class setup fails.
"""

import collections
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TIER = "fast"

REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON_PATH = str(REPO_ROOT / "python")
TIMEOUT = 120

STUB_MEMBER = '''\
import os
import unittest


def record(line):
    with open(os.environ["SUITE_PART_RECORD"], "a") as handle:
        handle.write(line + "\\n")


def setUpModule():
    record("setUpModule")
    if os.environ.get("SUITE_PART_FAIL") == "module":
        raise RuntimeError("module fixture failed")


def tearDownModule():
    record("tearDownModule")


class Recording(unittest.TestCase):
    def note(self):
        record(self.id())
        if type(self).__name__ in os.environ.get("SUITE_PART_FAIL", "").split(","):
            self.fail("planned failure")


class A(Recording):
    def test_a1(self):
        self.note()

    def test_a2(self):
        self.note()


class B(Recording):
    def test_b(self):
        self.note()


class D(A):
    pass


class E(Recording):
    @classmethod
    def setUpClass(cls):
        if os.environ.get("SUITE_PART_FAIL") == "E-setup":
            raise RuntimeError("class fixture failed")

    def test_e(self):
        self.note()


class Helper:
    def test_helper(self):
        record("helper")
'''

NAMED_MEMBER = '''\
import unittest


class A(unittest.TestCase):
    def test_a(self):
        pass


class C(unittest.TestCase):
    def test_case(self):
        self.fail("planned failure")


class S(unittest.TestCase):
    def test_sub(self):
        with self.subTest("row"):
            self.fail("planned failure")
'''

NOISY_MEMBER = '''\
import os
import unittest

print("A 1")
os.write(1, b"A 1\\n")


class A(unittest.TestCase):
    def test_a(self):
        pass
'''

CUSTOM_MEMBER = '''\
import unittest


class A(unittest.TestCase):
    def test_a(self):
        pass


class Adding(unittest.TestSuite):
    def run(self, result, debug=False):
        self.addTest(A("test_a"))
        return super().run(result, debug)


def load_tests(loader, tests, pattern):
    return Adding()
'''

LEFT_MODULE = '''\
import os
import unittest


class Cases(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.environ.get("SUITE_PART_FAIL") == "left-setup":
            raise RuntimeError("class fixture failed")

    def test_one(self):
        pass
'''

ALIAS_MEMBER = '''\
from left import Cases as LeftCases
from right import Cases as RightCases
'''

BROKEN_MEMBER = "import suite_part_missing_module\n"

HOOKED_MEMBER = '''\
import unittest


class F(unittest.TestCase):
    def test_f(self):
        pass


class G(unittest.TestCase):
    def test_g(self):
        pass


def load_tests(loader, tests, pattern):
    return unittest.TestSuite([F("test_f")])
'''


class SuitePartTest(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.work = Path(scratch.name)
        self.record = self.work / "record.txt"
        (self.work / "test_m.py").write_text(STUB_MEMBER)

    def environment(self, extra=None, record=None):
        inherited = os.environ.get("PYTHONPATH")
        env = dict(os.environ)
        env["PYTHONPATH"] = PYTHON_PATH + (os.pathsep + inherited if inherited else "")
        env["SUITE_PART_RECORD"] = str(record or self.record)
        env.pop("SUITE_PART_FAIL", None)
        env.update(extra or {})
        return env

    def part(self, *args, extra=None, record=None):
        return subprocess.run(
            [sys.executable, "-m", "agent_tools.delivery.suite_part", *args],
            cwd=self.work, env=self.environment(extra, record), stdin=subprocess.DEVNULL,
            capture_output=True, text=True, timeout=TIMEOUT)

    def baseline(self, record):
        return subprocess.run(
            [sys.executable, "-m", "unittest", "-v", "test_m.py"],
            cwd=self.work, env=self.environment(record=record), stdin=subprocess.DEVNULL,
            capture_output=True, text=True, timeout=TIMEOUT)

    def recorded(self, record=None):
        return (record or self.record).read_text().splitlines()

    def test_only_runs_the_named_classes_tests_inside_one_module_fixture(self):
        done = self.part("test_m.py", "--only", "A")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.recorded(),
                         ["setUpModule", "test_m.A.test_a1", "test_m.A.test_a2", "tearDownModule"])

    def test_except_runs_every_other_test_including_a_class_no_option_names(self):
        done = self.part("test_m.py", "--except", "A")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(set(self.recorded()) - {"setUpModule", "tearDownModule"},
                         {"test_m.B.test_b", "test_m.D.test_a1", "test_m.D.test_a2", "test_m.E.test_e"})

    def test_complementary_parts_run_the_whole_modules_tests_exactly_once(self):
        whole = self.work / "whole.txt"
        second = self.work / "second.txt"
        self.assertEqual(self.baseline(whole).returncode, 0)
        for args in (["--only", "A", "--only", "B"], ["--except", "A", "--except", "B"]):
            done = self.part("test_m.py", *args, record=second)
            self.assertEqual(done.returncode, 0, done.stderr)

        def tests(path):
            return collections.Counter(
                line for line in path.read_text().splitlines()
                if line not in ("setUpModule", "tearDownModule"))

        self.assertEqual(tests(second), tests(whole))
        self.assertEqual(set(tests(second).values()), {1})

    def test_exit_codes_match_unittest(self):
        rows = (
            (["--only", "A"], {}, 0),
            (["--only", "B"], {"SUITE_PART_FAIL": "B"}, 1),
            (["--only", "Missing"], {}, 5),
        )
        for args, extra, expected in rows:
            with self.subTest(args=args, extra=extra):
                done = self.part("test_m.py", *args, extra=extra)
                self.assertEqual(done.returncode, expected, done.stderr)

    def test_a_member_that_fails_to_import_fails_every_part_with_its_error(self):
        (self.work / "test_broken.py").write_text(BROKEN_MEMBER)
        for args in (["--only", "A"], ["--except", "A"]):
            with self.subTest(args=args):
                done = self.part("test_broken.py", *args)
                self.assertEqual(done.returncode, 1, done.stderr)
                self.assertIn("suite_part_missing_module", done.stdout + done.stderr)

    def test_a_failing_part_names_the_classes_of_its_failing_tests_last(self):
        rows = (
            (["--except", "A"], "D", "suite-part: failed classes D"),
            (["--only", "A", "--only", "B"], "B", "suite-part: failed classes B"),
            (["--only", "A", "--only", "B"], "A,B", "suite-part: failed classes A,B"),
            (["--except", "E"], "A,B,D", "suite-part: failed classes A,B,D"),
            (["--only", "E"], "E-setup", "suite-part: failed classes E"),
            (["--only", "A"], "module", "suite-part: failed classes setUpModule"),
        )
        for args, fail, expected in rows:
            with self.subTest(args=args, fail=fail):
                done = self.part("test_m.py", *args, extra={"SUITE_PART_FAIL": fail})
                self.assertNotEqual(done.returncode, 0)
                lines = [line for line in done.stderr.splitlines() if line.strip()]
                self.assertEqual(lines[-1], expected)
        done = self.part("test_m.py", "--only", "A")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertFalse([line for line in done.stderr.splitlines() if line.startswith("suite-part:")])

    def test_list_names_each_class_the_loader_runs_with_its_test_count(self):
        done = self.part("test_m.py", "--list")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.splitlines(), ["A 2", "B 1", "D 2", "E 1"])
        self.assertFalse(self.record.exists())
        (self.work / "test_hooked.py").write_text(HOOKED_MEMBER)
        (self.work / "test_broken.py").write_text(BROKEN_MEMBER)
        with self.subTest(member="test_hooked.py"):
            hooked = self.part("test_hooked.py", "--list")
            self.assertEqual(hooked.returncode, 0, hooked.stderr)
            self.assertEqual(hooked.stdout.splitlines(), ["F 1"])
        with self.subTest(member="test_broken.py"):
            broken = self.part("test_broken.py", "--list")
            self.assertEqual(broken.returncode, 1, broken.stderr)
            self.assertIn("suite_part_missing_module", broken.stdout + broken.stderr)

    def test_a_failing_test_named_test_case_and_a_failing_subtest_name_their_own_classes(self):
        (self.work / "test_named.py").write_text(NAMED_MEMBER)
        rows = (
            (["--only", "A", "--only", "C"], "C"),
            (["--only", "S"], "S"),
            (["--except", "A"], "C,S"),
        )
        for args, expected in rows:
            with self.subTest(args=args):
                done = self.part("test_named.py", *args)
                self.assertEqual(done.returncode, 1, done.stderr)
                lines = [line for line in done.stderr.splitlines() if line.strip()]
                self.assertEqual(lines[-1], "suite-part: failed classes " + expected)

    def test_what_the_member_prints_while_it_is_listed_never_reaches_the_rows(self):
        (self.work / "test_noisy.py").write_text(NOISY_MEMBER)
        done = self.part("test_noisy.py", "--list")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.splitlines(), ["A 1"])
        self.assertIn("A 1", done.stderr)

    def test_a_suite_that_may_run_tests_it_does_not_hold_cannot_be_listed_or_split(self):
        (self.work / "test_custom.py").write_text(CUSTOM_MEMBER)
        for args in (["--list"], ["--only", "A"], ["--except", "A"]):
            with self.subTest(args=args):
                done = self.part("test_custom.py", *args)
                self.assertEqual(done.returncode, 1, done.stderr)
                self.assertEqual(done.stdout, "")
                self.assertIn("suite-part: cannot split a test_custom.Adding suite", done.stderr)

    def test_a_class_from_another_module_is_named_with_its_module(self):
        (self.work / "left.py").write_text(LEFT_MODULE)
        (self.work / "right.py").write_text(LEFT_MODULE)
        (self.work / "test_alias.py").write_text(ALIAS_MEMBER)
        listed = self.part("test_alias.py", "--list")
        self.assertEqual(listed.stdout.splitlines(), ["left:Cases 1", "right:Cases 1"])
        only = self.part("test_alias.py", "--only", "left:Cases")
        self.assertEqual(only.returncode, 0, only.stderr)
        self.assertIn("Ran 1 test", only.stderr)
        rest = self.part("test_alias.py", "--except", "left:Cases")
        self.assertIn("Ran 1 test", rest.stderr)
        failed = self.part("test_alias.py", "--only", "left:Cases",
                           extra={"SUITE_PART_FAIL": "left-setup"})
        self.assertEqual(failed.returncode, 1)
        lines = [line for line in failed.stderr.splitlines() if line.strip()]
        self.assertEqual(lines[-1], "suite-part: failed classes left:Cases")

    def test_usage_errors_exit_2_before_any_test_runs(self):
        (self.work / "run.sh").write_text("true\n")
        rows = (
            ["test_m.py"],
            ["test_m.py", "--only", "A", "--except", "B"],
            ["test_m.py", "--list", "--only", "A"],
            ["run.sh", "--only", "A"],
        )
        for args in rows:
            with self.subTest(args=args):
                done = self.part(*args)
                self.assertEqual(done.returncode, 2, done.stderr)
                self.assertFalse(self.record.exists())


if __name__ == "__main__":
    unittest.main()
