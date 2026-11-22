"""Contract tests for the Ruff enforcers under the never-rise check.

Each case is judged through one conformance `ci` run on a committed root whose
integration ref the fixture moves (#1460): a finding the branch adds turns the
run red naming its Python rule, findings the base already holds are carried, and
a Ruff that cannot run is a failed check rather than a pass."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from .conformance_test_support import (
    HERMETIC_ENV, INTEGRATION_REF, ReportAssertions, commit_all, fixture, git,
    make_root, run,
)

TIER = "integration"

CHECK_ID = "verification.violations.never_rise"


def ci(case: unittest.TestCase, root: Path, env: dict) -> tuple[int, dict, dict]:
    code, out, err = run("run", "--purpose", "ci", "--repo-root", str(root), env=env)
    case.assertIn(code, (0, 1), err)
    report = json.loads(out)
    return code, report, {c["id"]: c for c in report["checks"]}


def summary(check: dict) -> list:
    return [check["status"], check["reason_code"], check["repair_id"],
            check["facts"]]


def python_base(root: Path, module_text: str) -> str:
    """A covered Python package committed and made the integration tip; its sha."""
    (root / "pyproject.toml").write_text('[project]\nname = "fx"\n', encoding="utf-8")
    (root / "pkg").mkdir()
    (root / "pkg/helper.py").write_text(module_text, encoding="utf-8")
    commit_all(root, "base")
    git(root, "update-ref", INTEGRATION_REF, "HEAD")
    return git(root, "rev-parse", "HEAD").strip()


class RuffNeverRiseCheckTest(ReportAssertions, unittest.TestCase):

    def ruff_env(self) -> dict:
        self.assertIn("AGENT_PLATFORM_TOOLS", HERMETIC_ENV,
                      "run this suite with AGENT_PLATFORM_TOOLS set to the pinned tools")
        return {**HERMETIC_ENV}

    def test_an_added_unused_import_turns_ci_red_naming_the_python_rule(self):
        env = self.ruff_env()
        with fixture() as tmp:
            root = make_root(tmp)
            base = python_base(root, "VALUE = 1\n")
            (root / "pkg/helper.py").write_text("import os\nVALUE = 1\n",
                                                encoding="utf-8")
            commit_all(root, "import")
            code, report, by_id = ci(self, root, env)
            self.assertEqual(code, 1)
            self.assertEqual(report["outcome"], {
                "status": "failed", "primary_check_id": CHECK_ID})
            self.assertEqual(
                summary(by_id[CHECK_ID]),
                ["failed", "violation_count_rose", "violations.never_rise.reduce",
                 {"merge_base": base, "rule": "PY6", "base_count": 0,
                  "branch_count": 1, "violations": ["PY6 pkg/helper.py:1"],
                  "rules": ["PY6"]}])
            self.assert_validates(report)

    def test_existing_findings_are_carried(self):
        env = self.ruff_env()
        with fixture() as tmp:
            root = make_root(tmp)
            base = python_base(root, "import os\nVALUE = 1\n")
            (root / "pkg/other.py").write_text("OTHER = 2\n", encoding="utf-8")
            commit_all(root, "other")
            code, report, by_id = ci(self, root, env)
            self.assertEqual(
                summary(by_id[CHECK_ID]),
                ["passed", None, None, {"merge_base": base}])

    def test_a_ruff_that_cannot_run_is_a_failed_check(self):
        env = {key: value for key, value in self.ruff_env().items()
               if key != "AGENT_PLATFORM_TOOLS"}
        with fixture() as tmp:
            root = make_root(tmp)
            python_base(root, "VALUE = 1\n")
            code, report, by_id = ci(self, root, env)
            self.assertEqual(code, 1)
            self.assertEqual(
                summary(by_id[CHECK_ID]),
                ["failed", "enforcer_failed", "violations.enforcer.repair",
                 {"enforcer": "ruff-lint", "reason": "ruff_unavailable"}])
            self.assert_validates(report)


if __name__ == "__main__":
    unittest.main()
