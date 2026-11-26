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

Class names (`class_name`). A class defined in the member's own module is named by its
`__qualname__`; a class the member imports from another module is named `<module>:<qualname>`,
so two same-named classes of different modules stay two classes.

Selection (`selected`). `--only` keeps a test whose class name is named,
`--except` keeps every test whose class is not named: a class that only inherits its tests
and a class no option names are kept. A loader failure (an import or load error, a test
whose class lives in `unittest.loader`) is kept in every part, so the error prints and
fails each part instead of ending with exit 5 and no message.

Listing (`--list`). The member is imported through unittest's own loader and nothing runs,
no test and no fixture. Each class the loader would run prints as `<class name> <count>`, in
first-appearance order, so a mixin that is no `TestCase`, a base with no tests and a class a
`load_tests` hook leaves out are not listed. The rows go to the process's original stdout;
while the member is imported, file descriptor 1 is the process's stderr, so what the member
prints cannot pass for a row. A loader failure prints its error on stderr.

A suite that is an instance of a `TestSuite` subclass cannot be split: its own `run` may run
tests that flattening would drop. `--list`, `--only` and `--except` then print
`suite-part: ...` on stderr and exit 1, so the runner runs the member whole.

Failure line. A part whose result is not successful ends its stderr with
`suite-part: failed classes ` and the sorted, comma-joined, distinct class names of its
failures, errors and unexpected successes (a failing subtest counts as its test). A fixture
error names the class of a class fixture and `setUpModule` or `tearDownModule` for a module
fixture. A successful part prints no such line.

Exits. Those of `python -m unittest`: 1 when the result is not successful, else 5 when no
test ran and none was skipped, else 0. A usage error exits 2 before any test runs;
`--list` exits 0, or 1 when the suite held a loader failure or a `TestSuite` subclass.
"""

import argparse
import os
import re
import sys
import unittest
from collections.abc import Collection, Iterable, Iterator, Mapping, Sequence
from typing import TextIO
from unittest.util import strclass

FAILED_CLASSES = "suite-part: failed classes "

LOADER_MODULE = "unittest.loader"
FIXTURE = re.compile(r"^(?P<method>\w+) \((?P<parent>.+)\)$")


class UnsplittableSuite(Exception):
    """A suite whose own `run` may run tests flattening would lose."""


def flattened(tests: Iterable) -> Iterator[unittest.TestCase]:
    """The tests of a suite, nested suites flattened, in order; a `TestSuite` subclass raises."""
    for test in tests:
        if isinstance(test, unittest.TestSuite):
            if type(test) is not unittest.TestSuite:
                raise UnsplittableSuite(f"cannot split a {strclass(type(test))} suite")
            yield from flattened(test)
        else:
            yield test


def is_loader_failure(test: unittest.TestCase) -> bool:
    return type(test).__module__ == LOADER_MODULE


def module_name(member: str) -> str | None:
    """The module name unittest gives a member's path, None when the path leaves the working directory."""
    path = os.path.normpath(member).removesuffix(".py")
    return None if path.startswith("..") or os.path.isabs(path) else path.replace(os.sep, ".")


def class_name(cls: type, module: str | None) -> str:
    """`cls`'s `__qualname__` when `module` defines it, else `<module>:<qualname>`."""
    if cls.__module__ == module:
        return cls.__qualname__
    return f"{cls.__module__}:{cls.__qualname__}"


def selected(tests: Iterable[unittest.TestCase], *, only: Collection[str] = (),
             excluded: Collection[str] = (), module: str | None = None) -> list[unittest.TestCase]:
    """The tests a part runs: those of `only`, or all but those of `excluded`; loader failures always."""
    if bool(only) == bool(excluded):
        raise ValueError("give exactly one of only and excluded")
    kept = []
    for test in tests:
        name = class_name(type(test), module)
        if is_loader_failure(test) or (name in only if only else name not in excluded):
            kept.append(test)
    return kept


class ClassFilterLoader(unittest.TestLoader):
    """A loader whose suite holds only the tests `selected` keeps."""

    def __init__(self, *, only: Collection[str] = (), excluded: Collection[str] = (),
                 module: str | None = None):
        super().__init__()
        self.only = tuple(only)
        self.excluded = tuple(excluded)
        self.module = module

    def loadTestsFromNames(self, names, module=None):
        loaded = super().loadTestsFromNames(names, module)
        return self.suiteClass(selected(flattened(loaded), only=self.only, excluded=self.excluded,
                                           module=self.module))


class ClassListing:
    """A test runner that writes the classes of the suite with their test counts to `stream` and runs nothing."""

    def __init__(self, stream: TextIO, module: str | None = None):
        self.stream = stream
        self.module = module

    def run(self, test) -> unittest.TestResult:
        counts: dict[str, int] = {}
        failures = []
        for case in flattened(test):
            if is_loader_failure(case):
                failures.append(case)
            else:
                name = class_name(type(case), self.module)
                counts[name] = counts.get(name, 0) + 1
        for name, count in counts.items():
            print(f"{name} {count}", file=self.stream)
        if failures:
            return unittest.TextTestRunner(stream=sys.stderr).run(unittest.TestSuite(failures))
        return unittest.TestResult()


def failed_class(test, names: Mapping[str, str], module: str | None) -> str:
    """The class name a failing test or fixture error belongs to; `names` maps a class's
    `unittest.util.strclass` to its class name, for the fixture errors that carry only that."""
    wrapped = getattr(test, "test_case", None)
    if isinstance(wrapped, unittest.TestCase):
        test = wrapped
    if isinstance(test, unittest.TestCase):
        return class_name(type(test), module)
    described = FIXTURE.match(getattr(test, "description", ""))
    if described is None:
        return str(test)
    if "Module" in described["method"]:
        return described["method"]
    return names.get(described["parent"], described["parent"])


def failed_classes(result: unittest.TestResult, suite: unittest.TestSuite,
                   module: str | None) -> list[str]:
    names = {strclass(type(test)): class_name(type(test), module) for test in flattened(suite)}
    tests = [test for test, _ in result.failures + result.errors] + list(result.unexpectedSuccesses)
    return sorted({failed_class(test, names, module) for test in tests})


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


def list_classes(member: str, module: str | None) -> int:
    """Print the member's classes on the original stdout, with descriptor 1 on stderr meanwhile."""
    original = os.dup(1)
    sys.stdout.flush()
    os.dup2(2, 1)
    try:
        with os.fdopen(os.dup(original), "w", encoding="utf-8") as stream:
            program = unittest.main(module=None, argv=["python -m unittest", member],
                                    testRunner=ClassListing(stream, module), exit=False)
    finally:
        sys.stdout.flush()
        os.dup2(original, 1)
        os.close(original)
    return 0 if program.result.wasSuccessful() else 1


def run_part(args: argparse.Namespace, module: str | None) -> int:
    loader = ClassFilterLoader(only=args.only, excluded=args.excluded, module=module)
    program = unittest.main(module=None, argv=["python -m unittest", "-v", args.member],
                            testLoader=loader, exit=False)
    result = program.result
    if not result.wasSuccessful():
        print(FAILED_CLASSES + ",".join(failed_classes(result, program.test, module)),
              file=sys.stderr)
    return exit_code(result)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse(argv)
    module = module_name(args.member)
    try:
        return list_classes(args.member, module) if args.listing else run_part(args, module)
    except UnsplittableSuite as error:
        print(f"suite-part: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
