"""The copied-test enforcer: no two tests share a body (rule standard:B24).

A test whose body repeats another test's is one violation. Test files and tests
are read by `agent_tools.delivery.suite_source`, which gives each test's body as
its tokens with comments and whitespace dropped and the test name, decorators,
attributes, parameters and a JavaScript title left out; this module recognises
no test of its own. The key of a test is `(family, body)`, so bodies of
different families never match and a body one token apart is another key. A
test with no body, a JavaScript declaration with no callback, has no key and is
never a copy; a focused or disabled declaration with a callback is keyed like
any other.

All tests of all test files are ordered by `(path, line)`. Within each key held
by n tests, n >= 2, the first is kept and each of the other n - 1 is one
violation at its line. `find` returns its violations sorted by `(path, line)`.

`ENFORCER` is a count rule for the never-rise check: the project's total may not
exceed the merge base's, wherever a copy moves to.

The command `copied-test-lint --repo-root <absolute directory> [--revision <rev>]`
prints every violation at the revision (default `HEAD`), one line each on stdout,
`<rule> <path>:<line>`, those a reasoned suppression marker of the rule does not
cover and one line for each bare marker of the rule (`agent_tools.delivery.never_rise.counted`).
It exits 1 when it printed any, 0 when none and 2 with one line
`copied-test-lint: <reason>` on stderr when the root or revision cannot be
read.
"""

import argparse

from agent_tools.delivery import never_rise
from agent_tools.delivery.never_rise import Enforcer, Snapshot, Violation
from agent_tools.delivery.suite_source import read_test_files, test_functions

COMMAND = "copied-test-lint"
RULE_ID = "B24"


def find(snapshot: Snapshot) -> list[Violation]:
    tests = sorted(
        (test_file.path, test.line, (test_file.family, test.body))
        for test_file in read_test_files(snapshot) for test in test_functions(test_file)
        if test.body is not None)
    seen: set[tuple[str, tuple[str, ...]]] = set()
    found = []
    for path, line, key in tests:
        if key in seen:
            found.append(Violation(RULE_ID, path, line))
        seen.add(key)
    return found


ENFORCER = Enforcer(RULE_ID, find)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog=COMMAND)
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--revision", default="HEAD")
    args = parser.parse_args(argv)
    snapshot = never_rise.command_snapshot(COMMAND, args.repo_root, args.revision)
    if snapshot is None:
        return 2
    kept, marked = never_rise.counted(ENFORCER, snapshot)
    found = sorted(kept + marked, key=lambda v: (v.path, v.line))
    for violation in found:
        print(violation.text())
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())
