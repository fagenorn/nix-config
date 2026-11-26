"""The cross-module rule of the step coverage: every procedure `deliver` reaches is judged by a coverage
module that runs in the suite, and a procedure file nothing reaches is a named exemption.

Also the step-coverage check inside the parts of one suite member: each part writes its own selection and
visits, and the part that finds every part's file checks their union."""

from __future__ import annotations

import copy
import json
import os
import shutil
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from agent_tools.delivery.suite_runner import PART_DIR_ENV, PART_ENV, PART_MEMBER_ENV
from tests.engine_procedure_copies import PROCEDURES
from tests.engine_step_coverage import (
    COVERAGE_MODULES, PROCEDURE_NAMES, UNREACHABLE, Step, StepCoverage, check_scopes, reachable, scopes)
from tests.test_suite_tiers import SUITE_RECIPE, justfile_text, recipe_paths

TIER = "fast"  # reads the shipped procedure files and the justfile, copies a few small files

STUBBED_RUN = "tests.test_engine_stubbed_run"
LAND_RECOVERY = "tests.test_engine_land_recovery"
VERIFY_ROUNDS = "tests.test_engine_verify_rounds"

T_A = "fake_cov.T.test_a"
U_B = "fake_cov.U.test_b"
V_C = "fake_cov.V.test_c"


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


def fake_class(name: str, method: str) -> type[unittest.TestCase]:
    return type(name, (unittest.TestCase,), {"__module__": "fake_cov", method: lambda self: None})


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


class StepCoverageJoinTest(unittest.TestCase):
    def setUp(self) -> None:
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name)
        self.procedures = self.root / "procedures"
        self.procedures.mkdir()
        (self.procedures / "p.json").write_text(json.dumps({"steps": [{"id": "s1"}, {"id": "s2"}]}), "utf-8")
        self.member = self.root / "test_fake.py"
        self.member.write_text("", "utf-8")
        self.other = self.root / "test_other.py"
        self.other.write_text("", "utf-8")
        self.module = types.ModuleType("fake_cov")
        self.module.__file__ = str(self.member)
        for name, method in (("T", "test_a"), ("U", "test_b")):
            setattr(self.module, name, fake_class(name, method))
        self.fresh_parts()

    def fresh_parts(self) -> None:
        self.parts = Path(tempfile.mkdtemp(dir=self.root))

    def part_files(self) -> list[str]:
        return sorted(path.name for path in self.parts.glob("*.json"))

    def finish_part(self, number: int, selected: list[str], recorded: list[Step], *, of: int = 2,
                    member: Path | None = None, module: types.ModuleType | None = None) -> None:
        environment = {PART_ENV: f"{number}/{of}", PART_DIR_ENV: str(self.parts),
                       PART_MEMBER_ENV: str(member or self.member)}
        coverage = StepCoverage(self.procedures, ("p",))
        for test_id in selected:
            coverage.select(test_id)
        coverage.record(recorded)
        with mock.patch.dict(os.environ, environment):
            return coverage.finish(module or self.module)

    def test_the_last_part_to_finish_checks_the_union_and_names_a_step_no_part_visited(self) -> None:
        for order in ((1, 2), (2, 1)):
            with self.subTest(order=order):
                self.fresh_parts()
                cases = {1: ([T_A], [("p", "s1")]), 2: ([U_B], [])}
                self.assertIsNone(self.finish_part(order[0], *cases[order[0]]))
                with self.assertRaises(AssertionError) as raised:
                    self.finish_part(order[1], *cases[order[1]])
                self.assertIn("p.s2", str(raised.exception))

    def test_parts_that_together_visit_every_step_pass(self) -> None:
        self.assertIsNone(self.finish_part(1, [T_A], [("p", "s1")]))
        self.assertIsNone(self.finish_part(2, [U_B], [("p", "s2")]))
        self.assertEqual(self.part_files(), ["1.json", "2.json"])

    def test_a_part_whose_selection_covers_the_module_checks_alone_and_writes_no_part_file(self) -> None:
        with self.assertRaises(AssertionError) as raised:
            self.finish_part(1, [T_A, U_B], [("p", "s1")])
        self.assertIn("p.s2", str(raised.exception))
        self.assertEqual(self.part_files(), [])

    def test_a_test_no_part_selected_fails_the_join_by_name(self) -> None:
        self.module.V = fake_class("V", "test_c")
        self.assertIsNone(self.finish_part(1, [T_A], [("p", "s1")]))
        self.assertEqual(self.part_files(), ["1.json"])
        with self.assertRaises(AssertionError) as raised:
            self.finish_part(2, [U_B], [("p", "s2")])
        self.assertEqual(self.part_files(), ["1.json", "2.json"])
        self.assertIn(V_C, str(raised.exception))

    def test_a_module_that_is_not_the_parts_member_checks_nothing_and_writes_nothing(self) -> None:
        without_file = types.ModuleType("fake_cov")
        for name, method in (("T", "test_a"), ("U", "test_b")):
            setattr(without_file, name, fake_class(name, method))
        rows = {"another member": {"member": self.other}, "no module file": {"module": without_file}}
        for label, row in rows.items():
            with self.subTest(label):
                self.assertIsNone(self.finish_part(1, [T_A], [], of=1, **row))
                self.assertEqual(self.part_files(), [])


if __name__ == "__main__":
    unittest.main()
