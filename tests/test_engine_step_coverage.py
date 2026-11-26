"""The step-coverage check inside the parts of one suite member: each part writes its own selection and visits,
and the part that finds every part's file checks their union."""

from __future__ import annotations

import json
import os
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from agent_tools.delivery.suite_runner import PART_DIR_ENV, PART_ENV, PART_MEMBER_ENV
from tests.engine_step_coverage import Step, StepCoverage

TIER = "fast"

T_A = "fake_cov.T.test_a"
U_B = "fake_cov.U.test_b"
V_C = "fake_cov.V.test_c"


def fake_class(name: str, method: str) -> type[unittest.TestCase]:
    return type(name, (unittest.TestCase,), {"__module__": "fake_cov", method: lambda self: None})


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
