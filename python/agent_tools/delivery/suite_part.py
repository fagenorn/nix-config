"""Run, or list, some test classes of one suite member, as one part of that member.

A part is the suite runner's unit for some classes of one `.py` member: it behaves as
`python -m unittest -v <member>` restricted to the tests of those classes, in one process,
so the module's fixtures (`setUpModule`, `tearDownModule`, module cleanups) run once per
part. The module has no command-table row, after `agent_tools.delivery.suite_runner`.

    python -m agent_tools.delivery.suite_part <member> --only CLASS [--only CLASS]...
    python -m agent_tools.delivery.suite_part <member> --except CLASS [--except CLASS]...
    python -m agent_tools.delivery.suite_part <member> --list

`<member>` is a `.py` path relative to the working directory. Exactly one kind of option
is given.

Selection (`selected`). `--only` keeps a test whose class `__qualname__` is named,
`--except` keeps every test whose class is not named: a class that only inherits its tests
and a class no option names are kept. A loader failure (an import or load error, a test
whose class lives in `unittest.loader`) is kept in every part, so the error prints and
fails each part instead of ending with exit 5 and no message.

Listing (`--list`). The member is imported through unittest's own loader and nothing runs,
no test and no fixture. Each class the loader would run prints as `<qualname> <count>`, in
first-appearance order, so a mixin that is no `TestCase`, a base with no tests and a class a
`load_tests` hook leaves out are not listed. A loader failure prints its error on stderr.

Failure line. A part whose result is not successful ends its stderr with
`suite-part: failed classes ` and the sorted, comma-joined, distinct class names of its
failures, errors and unexpected successes. A fixture error names the class of a class
fixture and `setUpModule` or `tearDownModule` for a module fixture. A successful part
prints no such line.

Exits. Those of `python -m unittest`: 1 when the result is not successful, else 5 when no
test ran and none was skipped, else 0. A usage error exits 2 before any test runs;
`--list` exits 0, or 1 when the suite held a loader failure.
"""

import argparse
import re
import sys
import unittest
from collections.abc import Collection, Iterable, Iterator, Sequence

FAILED_CLASSES = "suite-part: failed classes "

LOADER_MODULE = "unittest.loader"
FIXTURE = re.compile(r"^(?P<method>\w+) \((?P<parent>.+)\)$")


def flattened(tests: Iterable) -> Iterator[unittest.TestCase]:
    """The tests of a suite, nested suites flattened, in order."""
    for test in tests:
        if isinstance(test, unittest.TestSuite):
            yield from flattened(test)
        else:
            yield test


def is_loader_failure(test: unittest.TestCase) -> bool:
    return type(test).__module__ == LOADER_MODULE


def selected(tests: Iterable[unittest.TestCase], *, only: Collection[str] = (),
             excluded: Collection[str] = ()) -> list[unittest.TestCase]:
    """The tests a part runs: those of `only`, or all but those of `excluded`; loader failures always."""
    if bool(only) == bool(excluded):
        raise ValueError("give exactly one of only and excluded")
    kept = []
    for test in tests:
        name = type(test).__qualname__
        if is_loader_failure(test) or (name in only if only else name not in excluded):
            kept.append(test)
    return kept


class ClassFilterLoader(unittest.TestLoader):
    """A loader whose suite holds only the tests `selected` keeps."""

    def __init__(self, *, only: Collection[str] = (), excluded: Collection[str] = ()):
        super().__init__()
        self.only = tuple(only)
        self.excluded = tuple(excluded)

    def loadTestsFromNames(self, names, module=None):
        loaded = super().loadTestsFromNames(names, module)
        return self.suiteClass(selected(flattened(loaded), only=self.only, excluded=self.excluded))


class ClassListing:
    """A test runner that lists the classes of the suite with their test counts and runs nothing."""

    def run(self, test) -> unittest.TestResult:
        counts: dict[str, int] = {}
        failures = []
        for case in flattened(test):
            if is_loader_failure(case):
                failures.append(case)
            else:
                name = type(case).__qualname__
                counts[name] = counts.get(name, 0) + 1
        for name, count in counts.items():
            print(f"{name} {count}")
        if failures:
            return unittest.TextTestRunner(stream=sys.stderr).run(unittest.TestSuite(failures))
        return unittest.TestResult()


def failed_class(test) -> str:
    """The class a failing test or fixture error belongs to."""
    test = getattr(test, "test_case", test)
    if isinstance(test, unittest.TestCase):
        return type(test).__qualname__
    described = FIXTURE.match(getattr(test, "description", ""))
    if described is None:
        return str(test)
    if "Module" in described["method"]:
        return described["method"]
    return described["parent"].rsplit(".", 1)[-1]


def failed_classes(result: unittest.TestResult) -> list[str]:
    tests = [test for test, _ in result.failures + result.errors] + list(result.unexpectedSuccesses)
    return sorted({failed_class(test) for test in tests})


def exit_code(result: unittest.TestResult) -> int:
    if not result.wasSuccessful():
        return 1
    if result.testsRun == 0 and len(result.skipped) == 0:
        return 5
    return 0


def parse(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m agent_tools.delivery.suite_part")
    parser.add_argument("member", help="a .py test module path relative to the working directory")
    parser.add_argument("--only", action="append", dest="only", default=[], metavar="CLASS")
    parser.add_argument("--except", action="append", dest="excluded", default=[], metavar="CLASS")
    parser.add_argument("--list", action="store_true", dest="listing")
    args = parser.parse_args(argv)
    if not args.member.endswith(".py"):
        parser.error("the member must be a .py path")
    kinds = [bool(args.only), bool(args.excluded), args.listing]
    if sum(kinds) != 1:
        parser.error("give exactly one of --only, --except and --list")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = parse(argv)
    if args.listing:
        program = unittest.main(module=None, argv=["python -m unittest", args.member],
                                testRunner=ClassListing(), exit=False)
        return 0 if program.result.wasSuccessful() else 1
    loader = ClassFilterLoader(only=args.only, excluded=args.excluded)
    program = unittest.main(module=None, argv=["python -m unittest", "-v", args.member],
                            testLoader=loader, exit=False)
    result = program.result
    if not result.wasSuccessful():
        print(FAILED_CLASSES + ",".join(failed_classes(result)), file=sys.stderr)
    return exit_code(result)


if __name__ == "__main__":
    raise SystemExit(main())
