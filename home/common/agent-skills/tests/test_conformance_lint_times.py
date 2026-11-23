"""`conformance run --lint-times`: one stderr line naming each never-rise lint's time."""

from __future__ import annotations

import json
import unittest

from agent_tools.delivery import lint_time
from agent_tools.project_contract import conformance_checks

from .conformance_test_support import ReportAssertions, fixture, make_root, run

TIER = "integration"


def record_lines(err: str) -> list[str]:
    return [line for line in err.splitlines() if line.startswith(lint_time.RECORD_PREFIX)]


class LintTimesRunTest(ReportAssertions, unittest.TestCase):
    def test_a_ci_run_with_lint_times_prints_one_record_naming_every_enforcer(self):
        with fixture() as tmp:
            root = make_root(tmp)
            contract = json.loads((root / ".agents/project.json").read_text("utf-8"))
            expected = [e.rule for e in conformance_checks.never_rise_enforcers(contract)]
            code, out, err = run("run", "--purpose", "ci", "--repo-root", str(root),
                                 "--lint-times")
        self.assertIn(code, (0, 1), err)
        self.assertEqual(len(out.splitlines()), 1)
        self.assert_validates(json.loads(out))
        self.assertEqual(len(record_lines(err)), 1)
        record = lint_time.parse_log(err)
        self.assertIsNotNone(record)
        self.assertEqual([t.lint for t in record.lints], expected)
        self.assertEqual(record.total_ms, sum(t.base_ms + t.branch_ms for t in record.lints))

    def test_a_ci_run_without_the_flag_prints_no_record(self):
        with fixture() as tmp:
            root = make_root(tmp)
            code, out, err = run("run", "--purpose", "ci", "--repo-root", str(root))
        self.assertIn(code, (0, 1), err)
        self.assertEqual(record_lines(err), [])

    def test_a_run_whose_purpose_skips_never_rise_prints_no_record(self):
        with fixture() as tmp:
            root = make_root(tmp)
            code, out, err = run("run", "--purpose", "adoption", "--repo-root", str(root),
                                 "--lint-times")
        self.assertEqual(code, 0, err)
        self.assertEqual(record_lines(err), [])


if __name__ == "__main__":
    unittest.main()
