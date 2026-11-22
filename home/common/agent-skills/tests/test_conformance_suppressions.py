"""Contract tests for how the conformance run treats a suppression marker: a
reasoned one is listed and never fails the never-rise check, a bare one counts
as a violation, and one naming an unknown rule fails the standards lint
(ADR-project-contract-019). Split from test_conformance_checks.py to keep that
file under the size budget (rule B17)."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from .conformance_test_support import (
    ReportAssertions, commit_all, fixture, git, make_root, run,
)
from .test_conformance_checks import write_file

TIER = "integration"  # every case commits a real git repository and runs the conformance engine


def suppression(token: str, reason: str = "") -> str:
    """A suppression marker, assembled so this file holds no literal marker."""
    return "suppress" + "-standard:" + token + (" " + reason if reason else "")


class SuppressionNeverRiseTest(ReportAssertions, unittest.TestCase):
    """The never-rise check's treatment of suppression markers, judged through
    one `ci` run on a committed root."""

    CHECK_ID = "verification.violations.never_rise"

    def ci(self, root: Path) -> tuple[int, dict, dict]:
        code, out, err = run("run", "--purpose", "ci", "--repo-root", str(root))
        self.assertIn(code, (0, 1), err)
        report = json.loads(out)
        return code, report, {c["id"]: c for c in report["checks"]}

    def summary(self, check: dict) -> list:
        return [check["status"], check["reason_code"], check["repair_id"],
                check["facts"]]

    def test_a_new_reasoned_suppression_passes_ci_and_is_listed(self):
        with fixture() as tmp:
            root = make_root(tmp)
            base = git(root, "rev-parse", "HEAD").strip()
            write_file(root, "src/new.py", "x = 1\n" * 1500 + "x = 1  # "
                       + suppression("B17", "generated fixture table") + "\n")
            commit_all(root, "suppressed")
            code, report, by_id = self.ci(root)
            self.assertEqual(code, 0)
            self.assertEqual(
                self.summary(by_id[self.CHECK_ID]),
                ["passed", None, None, {
                    "merge_base": base,
                    "suppressions": ["B17 src/new.py:1501 generated fixture table"],
                    "suppression_count": 1}])
            self.assert_validates(report)

    def test_a_new_bare_suppression_turns_ci_red(self):
        with fixture() as tmp:
            root = make_root(tmp)
            base = git(root, "rev-parse", "HEAD").strip()
            write_file(root, "src/new.py", "x = 1\n" * 1500 + "x = 1  # "
                       + suppression("B17") + "\n")
            commit_all(root, "bare")
            code, report, by_id = self.ci(root)
            self.assertEqual(code, 1)
            self.assertEqual(
                self.summary(by_id[self.CHECK_ID]),
                ["failed", "violation_count_rose", "violations.never_rise.reduce", {
                    "merge_base": base, "rule": "B17", "base_count": 0,
                    "branch_count": 2,
                    "violations": ["B17 src/new.py:1501", "B17 src/new.py:1501"],
                    "rules": ["B17"]}])
            self.assert_validates(report)

    def test_a_new_bare_suppression_of_a_rule_with_no_enforcer_turns_ci_red(self):
        with fixture() as tmp:
            root = make_root(tmp)
            base = git(root, "rev-parse", "HEAD").strip()
            write_file(root, "src/new.py", "x = 1  # " + suppression("B1") + "\n")
            commit_all(root, "bare")
            code, report, by_id = self.ci(root)
            self.assertEqual(code, 1)
            self.assertEqual(self.summary(by_id[self.CHECK_ID]), [
                "failed", "violation_count_rose", "violations.never_rise.reduce", {
                    "merge_base": base, "rule": "B1", "base_count": 0, "branch_count": 1,
                    "violations": ["B1 src/new.py:1"], "rules": ["B1"]}])
            self.assert_validates(report)

    def test_a_long_path_leaves_the_line_and_the_reason_in_the_listing(self):
        with fixture() as tmp:
            root = make_root(tmp)
            directory = "/".join(["d" * 40] * 5)
            write_file(root, f"src/{directory}/new.py", "x = 1  # "
                       + suppression("B17", "generated fixture table") + "\n")
            commit_all(root, "long path")
            code, report, by_id = self.ci(root)
            facts = by_id[self.CHECK_ID]["facts"]
            self.assertEqual([code, facts["suppression_count"]], [0, 1])
            [listed] = facts["suppressions"]
            self.assertLessEqual(len(listed), 200)
            self.assertTrue(listed.startswith("B17 ") and listed.endswith(
                "/new.py:1 generated fixture table"), listed)
            self.assert_validates(report)

    def test_the_new_suppressions_are_bounded(self):
        with fixture() as tmp:
            root = make_root(tmp)
            for index in range(9):
                write_file(root, f"src/n{index}.py", "x = 1  # "
                           + suppression("B17", f"reason {index}") + "\n")
            commit_all(root, "many")
            code, report, by_id = self.ci(root)
            self.assertEqual(code, 0)
            facts = by_id[self.CHECK_ID]["facts"]
            self.assertEqual(
                [len(facts["suppressions"]), facts["suppression_count"]], [8, 9])
            self.assert_validates(report)


class SuppressionStandardsLintTest(ReportAssertions, unittest.TestCase):
    """The standards lint's treatment of a suppression of an unknown rule."""

    STANDARDS_ID = "verification.standards.lint"

    def ci(self, root: Path) -> tuple[int, dict, dict]:
        code, out, err = run("run", "--purpose", "ci", "--repo-root", str(root))
        self.assertIn(code, (0, 1), err)
        report = json.loads(out)
        return code, report, {c["id"]: c for c in report["checks"]}

    def summary(self, check: dict) -> list:
        return [check["status"], check["reason_code"], check["repair_id"],
                check["facts"]]

    def test_a_suppression_of_an_unknown_rule_turns_ci_red(self):
        with fixture() as tmp:
            root = make_root(tmp)
            write_file(root, "src/marked.py", "x = 1  # "
                       + suppression("Z9", "no such rule") + "\n")
            commit_all(root, "marked")
            code, report, by_id = self.ci(root)
            self.assertEqual(code, 1)
            self.assertEqual(self.summary(by_id[self.STANDARDS_ID]), [
                "failed", "standards_lint_failed", "docs.standards.repair",
                {"paths": ["src/marked.py:1"], "count": 1}])
            self.assert_validates(report)
