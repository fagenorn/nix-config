"""The cross-module rule of the step coverage: every procedure `deliver` reaches is judged by a coverage
module that runs in the suite, and a procedure file nothing reaches is a named exemption."""

from __future__ import annotations

import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from tests.engine_procedure_copies import PROCEDURES
from tests.engine_step_coverage import (
    COVERAGE_MODULES, PROCEDURE_NAMES, UNREACHABLE, StepCoverage, check_scopes, reachable, scopes)
from tests.test_suite_tiers import SUITE_RECIPE, justfile_text, recipe_paths

TIER = "fast"  # reads the shipped procedure files and the justfile, copies a few small files

STUBBED_RUN = "tests.test_engine_stubbed_run"
LAND_RECOVERY = "tests.test_engine_land_recovery"
VERIFY_ROUNDS = "tests.test_engine_verify_rounds"


def load(procedures: Path, name: str) -> dict:
    return json.loads((procedures / f"{name}.json").read_text("utf-8"))


def store(procedures: Path, name: str, document: dict) -> None:
    (procedures / f"{name}.json").write_text(json.dumps(document), "utf-8")


def add_call(procedures: Path, caller: str, callee: str, step_id: str) -> None:
    document = load(procedures, caller)
    document["steps"].append({"id": step_id, "kind": "call", "procedure": callee})
    store(procedures, caller, document)


def refusal(procedures: Path, given: dict[str, tuple[str, ...]]) -> str:
    with unittest.TestCase().assertRaises(AssertionError) as raised:
        check_scopes(procedures, given)
    return str(raised.exception)


class ProcedureScopeTest(unittest.TestCase):
    def copy(self) -> Path:
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        shutil.copytree(PROCEDURES, tmp / "procedures")
        return tmp / "procedures"

    def test_a_procedure_no_module_judges_fails_naming_it(self):
        procedures = self.copy()
        store(procedures, "extra", load(procedures, "verify"))
        add_call(procedures, "deliver", "extra", "extra-call")
        self.assertIn("procedures no stubbed-run module judges: ['extra']", refusal(procedures, scopes()))

    def test_every_shipped_procedure_is_judged_by_a_coverage_module(self):
        given = scopes()
        self.assertIsNone(check_scopes(PROCEDURES, given))
        self.assertEqual(
            reachable(PROCEDURES),
            ("close-out", "deliver", "direct", "land", "land-attempt", "setup", "verify"))
        self.assertEqual(set(given), set(COVERAGE_MODULES))
        self.assertIn("verify", given[STUBBED_RUN])
        self.assertIn("verify", given[VERIFY_ROUNDS])

    def test_a_judged_procedure_deliver_does_not_reach_fails_naming_it(self):
        given = scopes()
        given[LAND_RECOVERY] += ("toy",)
        self.assertIn("procedures judged but not reachable from deliver: ['toy']", refusal(PROCEDURES, given))

    def test_an_unreachable_procedure_file_that_is_not_exempt_fails_naming_it(self):
        procedures = self.copy()
        store(procedures, "stray", load(procedures, "toy-child"))
        self.assertIn("procedure files neither reachable from deliver nor exempt: ['stray']",
                      refusal(procedures, scopes()))

    def test_an_exempt_procedure_deliver_reaches_fails_naming_it(self):
        for callee, stale in (("toy-child", "['toy-child']"), ("toy", "['toy', 'toy-child']")):
            with self.subTest(callee=callee):
                procedures = self.copy()
                add_call(procedures, "deliver", callee, "toy-call")
                self.assertIn(f"exempt procedures deliver reaches or that are gone: {stale}",
                              refusal(procedures, scopes()))

    def test_an_exempt_procedure_whose_file_is_gone_fails_naming_it(self):
        for name in UNREACHABLE:
            with self.subTest(name=name):
                procedures = self.copy()
                (procedures / f"{name}.json").unlink()
                self.assertIn(f"exempt procedures deliver reaches or that are gone: ['{name}']",
                              refusal(procedures, scopes()))

    def test_an_exempt_procedure_whose_file_is_replaced_by_a_non_file_fails_naming_it(self):
        for name in UNREACHABLE:
            for kind in ("directory", "dangling symlink"):
                with self.subTest(name=name, kind=kind):
                    procedures = self.copy()
                    path = procedures / f"{name}.json"
                    path.unlink()
                    if kind == "directory":
                        path.mkdir()
                    else:
                        path.symlink_to(procedures / "absent-target")
                    self.assertIn(f"exempt procedures deliver reaches or that are gone: ['{name}']",
                                  refusal(procedures, scopes()))

    def test_a_call_to_a_procedure_with_no_file_fails_naming_it(self):
        procedures = self.copy()
        add_call(procedures, "deliver", "ghost", "ghost-call")
        with self.assertRaises(AssertionError) as raised:
            reachable(procedures)
        self.assertIn("procedure ghost has no file", str(raised.exception))

    def test_every_coverage_module_runs_in_the_suite_recipe(self):
        members = set(recipe_paths(justfile_text(), SUITE_RECIPE))
        for module in COVERAGE_MODULES:
            with self.subTest(module=module):
                self.assertIn(module.replace(".", "/") + ".py", members)

    def test_the_coverage_scope_is_the_names_it_was_built_with(self):
        self.assertEqual(StepCoverage(PROCEDURES, ("land-attempt",)).names, ("land-attempt",))
        self.assertEqual(StepCoverage(PROCEDURES).names, PROCEDURE_NAMES)

    def test_a_shipped_procedure_set_with_one_unvisited_step_fails_naming_it(self):
        procedures = self.copy()
        deliver = load(procedures, "deliver")
        closing = next(step for step in deliver["steps"] if step["id"] == "closing")
        deliver["steps"].append({**copy.deepcopy(closing), "id": "unvisited"})
        store(procedures, "deliver", deliver)
        coverage = StepCoverage(procedures)
        coverage.select("m.T.test_a")
        coverage.record(StepCoverage(PROCEDURES).declared())
        with self.assertRaises(AssertionError) as raised:
            coverage.check(["m.T.test_a"])
        self.assertIn("deliver.unvisited", str(raised.exception))
        self.assertNotIn("deliver.closing", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
