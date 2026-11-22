"""The skipped-test enforcer: no skipped or disabled test is added (rule standard:B18, #1464).

A test its framework skips, disables, focuses away or excludes from the run is
counted by the project's total, one violation per test, and that total may not
rise against the merge base. Test files, tests, suites and attribute sections
are read by `agent_tools.delivery.suite_source`; this module recognises only the
markers, as name tokens, so text in a string or a comment is never one. A token
counts once even when two rules match it. The chain root of a token is the first
name of the `name . name . ...` run that ends at it.

Python markers: P1 `skipTest` after `.` and before `(`; P2 `skip`, `skipif` or
`importorskip` after `.` whose preceding name is `pytest` or `mark`; P3 `skip`,
`skipIf` or `skipUnless` ending a dotted name right after `@`; P4 `SkipTest`
whose chain follows `raise`. `expectedFailure` and `xfail` run the test and are
no markers. A `skipIf` or `skipif` whose first argument (or `condition=`) is the
name `False`, and a `skipUnless` whose is `True`, never skips and is no marker; any
other condition is one.

C# markers: C1 `Skip` followed by `=` at the top level of the arguments of a
`Fact`, `Theory`, `SkippableFact`, `SkippableTheory` or `InlineData` attribute, and
`Ignore`, `IgnoreReason` or `Explicit` followed by `=` and a value other than `false`
or `null` at the top level of the arguments of a `TestCase` or `TestCaseSource`
attribute;
C2 an attribute named `Ignore` or `Explicit`; C3 `Skip`, `SkipWhen`, `SkipUnless`
or `Ignore` after `Assert .` and before `(`, and `If` or `IfNot` after `Skip .`
and before `(`. Attribute names are compared by their last segment without
`Attribute`.

JavaScript markers: J1 `skip`, `skipIf`, `runIf`, `todo`, `fixme` or `only` after
`.` whose chain root is a test or suite root; J2 `skip` after `.` and before `(`
whose receiver is `this`, `t` or `ctx`; J3 the roots `xit`, `xtest`, `xspecify`,
`fit`, `xdescribe`, `fdescribe`, `xcontext` and `xsuite` before `(` and not after
`.`; J4 a `skip` or `todo` key followed by `:` whose value is not `false`, in an
object literal passed directly to a call whose chain root is a test or suite root.

From markers to violations: A1 a marker inside a test's span marks that test; A2
a marker inside a range of a test's scopes (a skipped class, `describe.skip`, a
class or module `pytestmark`, an ignored fixture) marks that test; A3 a test with
no body, a JavaScript declaration with no callback, is skipped with or without a
marker; A4 a Python, JavaScript or C3 marker that marks no test is one violation
at its own line, while a C1 or C2 marker that marks no test (an attribute on a
property or a production method) is none. Each skipped test is one violation at
its line, however many markers mark it.

`ENFORCER` is a count rule for the never-rise check: the project's total may not
exceed the merge base's, wherever a skip moves to.

The command `skipped-test-lint --repo-root <absolute directory> [--revision <rev>]`
prints every violation at the revision (default `HEAD`), one line each on stdout,
`<rule> <path>:<line>`. Its exits (1 when it printed any, 0 when none, 2 with
`skipped-test-lint: <reason>` on stderr when the root or revision cannot be
read) are those of `agent_tools.delivery.never_rise.run_lint`.
"""

from agent_tools.delivery import never_rise
from agent_tools.delivery.never_rise import Enforcer, Snapshot, Violation
from agent_tools.delivery.suite_source import (
    FAMILIES, JS_SUITE_ROOTS, JS_TEST_ROOTS, TestFile, Token, attribute_sections,
    bracket_pairs, javascript_chain, read_test_files, test_functions)

COMMAND = "skipped-test-lint"
RULE_ID = "B18"

PYTEST_OWNERS = frozenset({"pytest", "mark"})
PYTEST_NAMES = frozenset({"skip", "skipif", "importorskip"})
DECORATOR_NAMES = frozenset({"skip", "skipIf", "skipUnless"})
INERT_CONDITIONS = {"skipIf": "False", "skipif": "False", "skipUnless": "True"}
CS_SKIP_KEYS = frozenset({"Skip"})
CS_IGNORE_KEYS = frozenset({"Ignore", "IgnoreReason", "Explicit"})
CS_ARGUMENT_KEYS = {
    "Fact": CS_SKIP_KEYS, "Theory": CS_SKIP_KEYS, "SkippableFact": CS_SKIP_KEYS,
    "SkippableTheory": CS_SKIP_KEYS, "InlineData": CS_SKIP_KEYS,
    "TestCase": CS_IGNORE_KEYS, "TestCaseSource": CS_IGNORE_KEYS}
CS_OFF_VALUES = frozenset({"false", "null"})
CS_DISABLING_ATTRIBUTES = frozenset({"Ignore", "Explicit"})
CS_ASSERT_NAMES = frozenset({"Skip", "SkipWhen", "SkipUnless", "Ignore"})
CS_SKIP_NAMES = frozenset({"If", "IfNot"})
JS_ROOTS = frozenset(JS_TEST_ROOTS + JS_SUITE_ROOTS)
JS_MEMBER_NAMES = frozenset({"skip", "skipIf", "runIf", "todo", "fixme", "only"})
JS_RECEIVERS = frozenset({"this", "t", "ctx"})
JS_DISABLED_ROOTS = frozenset({
    "xit", "xtest", "xspecify", "fit", "xdescribe", "fdescribe", "xcontext", "xsuite"})
JS_KEYS = frozenset({"skip", "todo"})
OPENERS = frozenset({"(", "[", "{"})


def after_dot(tokens: tuple[Token, ...], i: int) -> bool:
    return i > 0 and tokens[i - 1].text == "."


def before_paren(tokens: tuple[Token, ...], i: int) -> bool:
    return i + 1 < len(tokens) and tokens[i + 1].text == "("


def chain_root(tokens: tuple[Token, ...], i: int) -> int:
    """The index of the first name of the dotted run that ends at token `i`."""
    while i >= 2 and tokens[i - 1].text == "." and tokens[i - 2].kind == "name":
        i -= 2
    return i


def preceding(tokens: tuple[Token, ...], i: int) -> str:
    return tokens[i - 2].text if i >= 2 else ""


def inert(tokens: tuple[Token, ...], i: int) -> bool:
    """Whether token `i` is a conditional skip whose condition is the constant that never skips."""
    never = INERT_CONDITIONS.get(tokens[i].text)
    if never is None or not before_paren(tokens, i):
        return False
    first = i + 2
    if first + 2 < len(tokens) and tokens[first].text == "condition" and tokens[first + 1].text == "=":
        first += 2
    return first + 1 < len(tokens) and tokens[first].text == never and tokens[first + 1].text in (
        ",", ")")


def python_markers(tokens: tuple[Token, ...]) -> dict[int, bool]:
    found: dict[int, bool] = {}
    for i, token in enumerate(tokens):
        if token.kind != "name":
            continue
        dotted_end = not (i + 1 < len(tokens) and tokens[i + 1].text == ".")
        root = chain_root(tokens, i)
        if (token.text == "skipTest" and after_dot(tokens, i) and before_paren(tokens, i)) or (
                token.text in PYTEST_NAMES and after_dot(tokens, i)
                and preceding(tokens, i) in PYTEST_OWNERS) or (
                token.text in DECORATOR_NAMES and dotted_end and root > 0
                and tokens[root - 1].text == "@") or (
                token.text == "SkipTest" and dotted_end and root > 0
                and tokens[root - 1].text == "raise"):
            if not inert(tokens, i):
                found[i] = True
    return found


def argument_skips(tokens: tuple[Token, ...], pairs: dict[int, int], open_: int,
                   keys: frozenset[str]) -> list[int]:
    """The `key =` names, `keys` one of them, at the top level of the call whose `(` is `open_`.

    A call whose `(` has no partner has none. `Skip` counts whatever its value; the `Ignore`
    keys count unless the value is `false` or `null`.
    """
    if open_ not in pairs:
        return []
    found, i, close = [], open_ + 1, pairs[open_]
    while i < close:
        if tokens[i].kind == "op" and tokens[i].text in OPENERS and i in pairs:
            i = pairs[i] + 1
            continue
        if tokens[i].text in keys and i + 2 < close and tokens[i + 1].text == "=" and (
                keys is CS_SKIP_KEYS or tokens[i + 2].text not in CS_OFF_VALUES):
            found.append(i)
        i += 1
    return found


def attribute_markers(tokens: tuple[Token, ...], pairs: dict[int, int],
                      section: tuple[int, int]) -> list[int]:
    found, i, end = [], section[0] + 1, section[1] - 1
    while i < end:
        token = tokens[i]
        if token.kind == "op" and token.text in OPENERS and i in pairs:
            i = pairs[i] + 1
            continue
        if token.kind == "name" and not (i + 1 < end and tokens[i + 1].text in (".", ":")):
            name = token.text[:-9] if token.text.endswith("Attribute") and len(token.text) > 9 \
                else token.text
            if tokens[i - 1].text in ("[", ",", ".", ":"):
                if name in CS_DISABLING_ATTRIBUTES:
                    found.append(i)
                elif name in CS_ARGUMENT_KEYS and before_paren(tokens, i):
                    found.extend(argument_skips(tokens, pairs, i + 1, CS_ARGUMENT_KEYS[name]))
        i += 1
    return found


def csharp_markers(tokens: tuple[Token, ...]) -> dict[int, bool]:
    found: dict[int, bool] = {}
    pairs = bracket_pairs(tokens)
    for section in attribute_sections(tokens):
        for i in attribute_markers(tokens, pairs, section):
            found[i] = False
    for i, token in enumerate(tokens):
        if token.kind == "name" and after_dot(tokens, i) and before_paren(tokens, i) and (
                (token.text in CS_ASSERT_NAMES and preceding(tokens, i) == "Assert")
                or (token.text in CS_SKIP_NAMES and preceding(tokens, i) == "Skip")):
            found[i] = True
    return found


def javascript_object_markers(tokens: tuple[Token, ...], pairs: dict[int, int]) -> list[int]:
    found = []
    for i in range(len(tokens)):
        chain = javascript_chain(tokens, pairs, i)
        if chain is None or chain[0] not in JS_ROOTS:
            continue
        j, close = chain[2] + 1, pairs[chain[2]]
        while j < close:
            if tokens[j].text == "{" and j in pairs:
                found.extend(object_keys(tokens, pairs, j))
            j = pairs[j] + 1 if tokens[j].text in OPENERS and j in pairs else j + 1
    return found


def object_keys(tokens: tuple[Token, ...], pairs: dict[int, int], open_: int) -> list[int]:
    found, i, close = [], open_ + 1, pairs[open_]
    while i < close:
        if tokens[i].kind == "name" and tokens[i].text in JS_KEYS and tokens[i - 1].text in (
                "{", ",") and i + 2 < close + 1 and tokens[i + 1].text == ":" and (
                tokens[i + 2].text != "false"):
            found.append(i)
        i = pairs[i] + 1 if tokens[i].text in OPENERS and i in pairs else i + 1
    return found


def javascript_markers(tokens: tuple[Token, ...]) -> dict[int, bool]:
    found: dict[int, bool] = {}
    pairs = bracket_pairs(tokens)
    for i, token in enumerate(tokens):
        if token.kind != "name":
            continue
        dotted = after_dot(tokens, i)
        if dotted and token.text in JS_MEMBER_NAMES and tokens[chain_root(tokens, i)].text in JS_ROOTS:
            found[i] = True
        elif dotted and token.text == "skip" and before_paren(tokens, i) and (
                preceding(tokens, i) in JS_RECEIVERS):
            found[i] = True
        elif not dotted and token.text in JS_DISABLED_ROOTS and before_paren(tokens, i):
            found[i] = True
    for i in javascript_object_markers(tokens, pairs):
        found[i] = True
    return found


def classified(test_file: TestFile) -> dict[int, bool]:
    """Each marker's token index, true when it counts on its own line while unattached."""
    readers = {"python": python_markers, "csharp": csharp_markers,
               "javascript": javascript_markers}
    if test_file.family not in readers:
        raise ValueError(f"unknown family {test_file.family!r}; expected one of {FAMILIES}")
    return readers[test_file.family](test_file.tokens)


def markers(test_file: TestFile) -> list[int]:
    """The token index of each marker of the file, ascending."""
    return sorted(classified(test_file))


def skipped(test_file: TestFile) -> list[int]:
    """The 1-based violation lines of the file, ascending."""
    found = classified(test_file)
    tests = test_functions(test_file)
    marked: set[int] = set()
    attached: set[int] = set()
    for n, test in enumerate(tests):
        if test.body is None:
            marked.add(n)
        for i in found:
            if test.span[0] <= i < test.span[1] or any(a <= i < b for a, b in test.scopes):
                marked.add(n)
                attached.add(i)
    lines = [tests[n].line for n in marked]
    lines += [test_file.tokens[i].line for i, alone in found.items() if alone and i not in attached]
    return sorted(lines)


def find(snapshot: Snapshot) -> list[Violation]:
    return [Violation(RULE_ID, test_file.path, line)
            for test_file in read_test_files(snapshot) for line in skipped(test_file)]


ENFORCER = Enforcer(RULE_ID, find)


def main(argv: list[str] | None = None) -> int:
    return never_rise.run_lint(COMMAND, ENFORCER, argv)


if __name__ == "__main__":
    raise SystemExit(main())
