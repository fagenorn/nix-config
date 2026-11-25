"""Step coverage of a test module, collected from the runs its own tests made.

A `StepCoverage` learns which tests began (`started`) and which steps the module's runs visited
(`record`, a union across calls). `check` compares the visited steps with the steps the shipped
procedures declare, but only once every test of the module began: a run of part of the module
checks nothing. `test_ids` names the module's tests with a fresh loader, so a `-k` filter on the
shared default loader cannot narrow it, and leaves out each test a decorator skips: a skipped
test never begins, so counting it would let a skip silence the check.
"""

from __future__ import annotations

import json
import types
import unittest
from collections.abc import Iterable
from pathlib import Path

PROCEDURE_NAMES = ("setup", "deliver", "direct", "verify", "land", "close-out")


class StepCoverage:
    def __init__(self, procedures: Path, names: tuple[str, ...] = PROCEDURE_NAMES) -> None:
        self._procedures = procedures
        self._names = names
        self._started: set[str] = set()
        self._recorded: set[str] = set()

    def declared(self) -> set[str]:
        return {step["id"] for name in self._names
                for step in json.loads((self._procedures / f"{name}.json").read_text("utf-8"))["steps"]}

    def started(self, test_id: str) -> None:
        self._started.add(test_id)

    def started_ids(self) -> frozenset[str]:
        return frozenset(self._started)

    def record(self, steps: Iterable[str]) -> None:
        self._recorded.update(steps)

    def recorded(self) -> frozenset[str]:
        return frozenset(self._recorded)

    def check(self, module_tests: Iterable[str]) -> None:
        if not set(module_tests) <= self._started:
            return
        declared = self.declared()
        unvisited = sorted(declared - self._recorded)
        undeclared = sorted(self._recorded - declared)
        if unvisited or undeclared:
            raise AssertionError(f"steps no run visited: {unvisited}; steps no procedure declares: {undeclared}")


def _flattened(suite: unittest.TestSuite) -> Iterable[unittest.TestCase]:
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            yield from _flattened(test)
        else:
            yield test


def test_ids(module: types.ModuleType) -> set[str]:
    ids = set()
    for test in _flattened(unittest.TestLoader().loadTestsFromModule(module)):
        method = getattr(test, test._testMethodName, None)
        if not (getattr(test, "__unittest_skip__", False) or getattr(method, "__unittest_skip__", False)):
            ids.add(test.id())
    return ids
