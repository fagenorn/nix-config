"""Step coverage of a test module, collected from the runs its own tests made.

A step is a pair of a procedure name and a step id: two procedures may each declare a step of one id.
A `StepCoverage` learns which tests the runner selected (`select`, called as a test is about to run:
a test the runner built but filtered out is never selected) and which steps the module's runs visited
(`record`, a union across calls). `check` compares the visited steps with the steps the shipped
procedures declare, but only when the runner selected every test of the module: a run of part of the
module checks nothing. `finish` is the module teardown: it counts the tests of a class whose
`setUpClass` skipped or failed as selected (the class was entered, its tests never ran), checks, and
resets the selection and the visits, so the next suite in the same interpreter starts clean.
A check judges only the procedures it names: a visited step of another procedure is ignored.
`test_ids` names the module's tests with a fresh loader, so a `-k` filter on the shared default loader
cannot narrow it, and leaves out each test a decorator skips: a decorator skip is part of the module's
shape, so the check then fails if the skip lost a step. It names only the tests of `base`.
Across modules, `check_scopes` holds the coverage modules to one rule: every procedure `deliver` reaches,
through `call` steps, is in the scope of at least one module of `COVERAGE_MODULES`, every judged procedure
is reachable, and every procedure file is reachable or named in `UNREACHABLE`. A new coverage module is
registered in `COVERAGE_MODULES` and in `scopes`. `toy` and `toy-child` are exempt because the engine refuses to run
`toy` and nothing calls either; the exemption fails once `deliver` reaches either or its file is gone.
"""

from __future__ import annotations

import json
import types
import unittest
from collections.abc import Iterable, Mapping
from pathlib import Path

Step = tuple[str, str]
PROCEDURE_NAMES = ("setup", "deliver", "direct", "verify", "land", "close-out")
UNREACHABLE = ("toy", "toy-child")
COVERAGE_MODULES = ("tests.test_engine_stubbed_run", "tests.test_engine_land_recovery",
                    "tests.test_engine_verify_rounds")


class StepCoverage:
    def __init__(self, procedures: Path, names: tuple[str, ...] = PROCEDURE_NAMES) -> None:
        self._procedures = procedures
        self._names = names
        self._selected: set[str] = set()
        self._recorded: set[Step] = set()

    @property
    def names(self) -> tuple[str, ...]:
        return self._names

    def declared(self) -> set[Step]:
        return {(name, step["id"]) for name in self._names
                for step in json.loads((self._procedures / f"{name}.json").read_text("utf-8"))["steps"]}

    def select(self, test_id: str) -> None:
        self._selected.add(test_id)

    def reset(self) -> None:
        self._selected = set()
        self._recorded = set()

    def selected_ids(self) -> frozenset[str]:
        return frozenset(self._selected)

    def record(self, steps: Iterable[Step]) -> None:
        self._recorded.update(steps)

    def recorded(self) -> frozenset[Step]:
        return frozenset(self._recorded)

    def check(self, module_tests: Iterable[str]) -> None:
        if not set(module_tests) <= self._selected:
            return
        declared = self.declared()
        unvisited = sorted(f"{procedure}.{step}" for procedure, step in declared - self._recorded)
        undeclared = sorted(f"{procedure}.{step}" for procedure, step in self._recorded - declared
                             if procedure in self._names)
        if unvisited or undeclared:
            raise AssertionError(f"steps no run visited: {unvisited}; steps no procedure declares: {undeclared}")


    def finish(self, module: types.ModuleType, base: type[unittest.TestCase] = unittest.TestCase) -> None:
        entered = [test for test in _flattened(unittest.TestLoader().loadTestsFromModule(module))
                   if vars(type(test)).get("_classSetupFailed")]
        try:
            self._selected.update(test.id() for test in entered)
            self.check(test_ids(module, base))
        finally:
            for test in entered:
                type(test)._classSetupFailed = False
            self.reset()


def reachable(procedures: Path, entry: str = "deliver") -> tuple[str, ...]:
    seen = {entry}
    queue = [entry]
    while queue:
        name = queue.pop(0)
        path = procedures / f"{name}.json"
        if not path.is_file():
            raise AssertionError(f"procedure {name} has no file")
        for step in json.loads(path.read_text("utf-8"))["steps"]:
            if step.get("kind") == "call" and step["procedure"] not in seen:
                seen.add(step["procedure"])
                queue.append(step["procedure"])
    return tuple(sorted(seen))


def scopes() -> dict[str, tuple[str, ...]]:
    # Imported here: each coverage module imports this one, so a top-level import would be circular.
    from tests import test_engine_land_recovery, test_engine_stubbed_run, test_engine_verify_rounds
    modules = (test_engine_stubbed_run, test_engine_land_recovery, test_engine_verify_rounds)
    return {module.__name__: module.STEPS.names for module in modules}


def check_scopes(procedures: Path, scopes: Mapping[str, tuple[str, ...]],
                 exempt: tuple[str, ...] = UNREACHABLE) -> None:
    files = {path.stem for path in procedures.glob("*.json")
             if path.is_file() and not path.name.endswith(".reply.json")}
    reach = set(reachable(procedures))
    judged = {name for scope in scopes.values() for name in scope}
    groups = (
        ("procedures no stubbed-run module judges", reach - judged),
        ("procedures judged but not reachable from deliver", judged - reach),
        ("procedure files neither reachable from deliver nor exempt", files - reach - set(exempt)),
        ("exempt procedures deliver reaches or that are gone",
         {name for name in exempt if name in reach or name not in files}),
    )
    found = [f"{label}: {sorted(names)}" for label, names in groups if names]
    if found:
        raise AssertionError("; ".join(found))


def _flattened(suite: unittest.TestSuite) -> Iterable[unittest.TestCase]:
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            yield from _flattened(test)
        else:
            yield test


def test_ids(module: types.ModuleType, base: type[unittest.TestCase] = unittest.TestCase) -> set[str]:
    ids = set()
    for test in _flattened(unittest.TestLoader().loadTestsFromModule(module)):
        method = getattr(test, test._testMethodName, None)
        skipped = getattr(test, "__unittest_skip__", False) or getattr(method, "__unittest_skip__", False)
        if isinstance(test, base) and not skipped:
            ids.add(test.id())
    return ids
