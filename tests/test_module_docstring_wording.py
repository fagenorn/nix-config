"""Fail the suite when a test pins a module docstring's wording (issue 1311, ADR-delivery-011).

A module docstring is prose. A test that asserts the docstring contains, equals,
starts or ends with given words fails on a rewording and stays green when the
documented behaviour breaks. ADR-delivery-011 forbids such a test; this module
is the gate. It scans, with the standard library `ast`, the same sources as
`tests/test_decision_record_wording.py` (every member of the
`agent-workflow-tests` recipe plus `tests/*.py` and
`home/common/agent-skills/tests/*.py`, never the two guard test files) and
reports each such assertion as (test id, line). The tests of the scanner itself
run on string fixtures; `SuiteDocstringTest` runs it on the real tree and checks
the list of kept credential tests. What the scan does not see is in the
Consequences of ADR-delivery-011.

Scan rule for a `.py` source:

1. Call name. A call's name is `func.id` for a Name and `func.attr` for an
   Attribute.
2. DOC. An expression is DOC when it is an Attribute whose `attr` is
   `__doc__` (any receiver); a Call named in DOC_CALLS; a Name or attribute
   chain of Names (`doc`, `self.doc`) bound to DOC; a Call named in TEXT_CALLS
   whose text input is DOC, where the text input of a name in
   ARGUMENT_TEXT_CALLS is its first positional argument (for `join` the receiver
   is only the separator) and of every other name the Attribute receiver
   (`doc.split(sep)` is DOC, `text.split(doc)` is not, since there `doc` is
   only the separator); a BoolOp with a DOC operand; a Subscript whose value is
   DOC; an IfExp with a DOC branch. Any other call of a DOC value (`lint(doc)`,
   `json.loads(...)`, `len(doc)`, a method call such as `self.example()`) is
   not DOC.
3. PHRASE. An expression that is not DOC is PHRASE when it is a non-empty
   `str` Constant; a JoinedStr (f-string) with at least one non-empty literal
   segment, so `f"{parser.description}"` is not PHRASE; a Name or chain bound
   to PHRASE; a Tuple, List or Set with a PHRASE element; a BinOp with a PHRASE
   operand. Nothing else is PHRASE: a call result and an unbound chain are
   not. The empty string is not PHRASE.
4. Environments. The module environment comes from the top-level `Assign` and
   `AnnAssign` statements in order (Name targets). A top-level class body's
   `Assign` statements give the class bindings `self.<NAME>`, `cls.<NAME>` and
   `<Class>.<NAME>`. Each unit (a top-level function, or a method of a
   top-level class, sync or async) is walked from a copy of the module
   environment in this order: first its parameters are unbound (unbinding a
   name also forgets the chains that start with `<name>.`), and only then are
   the class bindings installed, so unbinding `self` never drops
   `self.SENTENCES`. Statements are walked in order, compound bodies in order
   in the same environment (no branch join, except for an `if`): an assignment replaces each
   target's kinds (a Tuple target is bound element-wise when the value is a
   Tuple or List of the same length, else each element gets the value's kinds);
   an augmented assignment adds; binding a name forgets the chains that start
   with `<name>.`; a `for` target gets the union of the element kinds of a
   literal Tuple, List or Set iterable, else the iterable's kinds, before the
   body; a `with ... as v` binds `v` to the context expression's kinds; `if`,
   `while`, `try` (handlers, else, finally) and `match` bodies are walked in
   order, except an `if`: its body and its else branch are each walked from a
   copy of the incoming environment, and the environment after the `if` holds,
   per name, the union of the kinds the two branches else branch being the
   incoming environment when there is none) end with. A nested def or lambda is walked from a copy of the current
   environment with its parameters unbound; its assertions belong to the
   enclosing unit.
5. Assertions and findings. An assertion is an `assert` statement, or an
   expression statement whose value is a Call whose func is an Attribute named
   `assert*`. Its operands are the first positional argument for ONE_OPERAND,
   the first two for TWO_OPERANDS, every positional argument of any other
   `assert*`, and every keyword value except DIAGNOSTIC_KEYWORDS; an `assert`
   statement's operand is its test. A name in CALLABLE_FORM (`assertRaises`,
   `assertRaisesRegex`, `assertWarns`, `assertWarnsRegex`) has as operands only
   its leading exception and regex arguments (1 or 2); when positional arguments
   follow them, they and every keyword value are the arguments of the called
   callable, so a docstring passed there is input, not an operand. It is a
   finding, recorded once at the assertion's line, when (A) one operand is DOC and a different operand is
   PHRASE, or (B) an operand's subtree holds a Compare whose left and
   comparators include a DOC part and a PHRASE part, or a Call named in
   MATCH_CALLS or PROBE_CALLS whose parts (the Attribute receiver plus the
   positional arguments) include a DOC part and a PHRASE part.
6. A `.sh` source is scanned by line, and only for phrase tests: a line is a
   finding when its first non-blank character is not `#`, it matches
   SHELL_DOC, and it matches SHELL_PHRASE_TEST, or matches SHELL_COMPARE and,
   once its empty double-quoted literals are removed, still holds a double-quoted
   literal (a `!= ""` check compares with no phrase). A docstring existence check is
   no finding in any member kind.

A suite member of any kind other than `.py` and `.sh` fails the scan, and a
source that does not parse fails it too: nothing is skipped.
"""

import ast
import re
import tempfile
import textwrap
import unittest
from pathlib import Path

from tests.test_decision_record_wording import (
    DIAGNOSTIC_KEYWORDS,
    JUSTFILE_HEAD,
    MATCH_CALLS,
    ONE_OPERAND,
    PROBE_CALLS,
    TWO_OPERANDS,
    kept_list_problems,
    suite_members,
    suite_sources,
    write_tree,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DOC_CALLS = frozenset({"get_docstring", "getdoc"})
TEXT_CALLS = frozenset({
    "join", "split", "rsplit", "splitlines", "strip", "lstrip", "rstrip", "lower", "upper",
    "casefold", "replace", "removeprefix", "removesuffix", "partition", "rpartition", "dedent",
    "cleandoc",
})
# The TEXT_CALLS whose text input is their first positional argument.
ARGUMENT_TEXT_CALLS = frozenset({"join", "dedent", "cleandoc"})
SHELL_DOC = re.compile(r"__doc__|get_docstring|getdoc")
SHELL_PHRASE_TEST = re.compile(
    r"\bgrep\b|\bin\b|startswith|endswith|\bcount\(|\bfind\(|\bindex\(|\bsearch\(|\bmatch\(|\bassert[A-Z]"
)
SHELL_COMPARE = re.compile(r"==|!=")
SHELL_EMPTY_LITERAL = re.compile(r'\\?"\\?"')
SHELL_LITERAL = re.compile(r'"[^"]+"')
# The count of leading operands (exception, regex) of each assertion that also takes a callable.
CALLABLE_FORM = {"assertRaises": 1, "assertWarns": 1, "assertRaisesRegex": 2, "assertWarnsRegex": 2}

# The docstring tests that name a credential word and were on main when the scan
# landed (ADR-delivery-011). Adding an id here is a new decision with its own record.
KEPT_DOCSTRING_TESTS = frozenset({
    "tests/test_console_pictures.py::PictureCommandTest.test_the_docstring_states_the_picture_contract",
    "tests/test_console_pictures.py::PictureReportCommandTest.test_the_docstring_states_the_secret_check_for_a_brief_and_a_report",
    "tests/test_console_sprint_command.py::CommandContractTest.test_the_command_table_names_the_module_and_its_docstring_states_the_contract",
})

DOC = "DOC"
PHRASE = "PHRASE"
EMPTY: frozenset[str] = frozenset()
FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)
TRIES = tuple(t for t in (getattr(ast, "Try", None), getattr(ast, "TryStar", None)) if t)


def _call_name(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def _chain(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _chain(node.value)
        return None if base is None else f"{base}.{node.attr}"
    return None


def _parameters(function) -> list[str]:
    args = function.args
    names = [a.arg for a in args.posonlyargs + args.args + args.kwonlyargs]
    names += [a.arg for a in (args.vararg, args.kwarg) if a is not None]
    return names


def _set(env: dict, chain: str, kinds: frozenset[str]) -> None:
    for key in [k for k in env if k.startswith(chain + ".")]:
        del env[key]
    if kinds:
        env[chain] = kinds
    else:
        env.pop(chain, None)


def _unbind_parameters(function, env: dict) -> None:
    for name in _parameters(function):
        _set(env, name, EMPTY)


class _Walk:
    def __init__(self) -> None:
        self.found: set[int] = set()

    def is_doc(self, node: ast.AST, env: dict) -> bool:
        if isinstance(node, ast.Attribute) and node.attr == "__doc__":
            return True
        if isinstance(node, (ast.Name, ast.Attribute)):
            chain = _chain(node)
            return chain is not None and DOC in env.get(chain, EMPTY)
        if isinstance(node, ast.Call):
            name = _call_name(node)
            if name in DOC_CALLS:
                return True
            if name in TEXT_CALLS:
                if name in ARGUMENT_TEXT_CALLS:
                    source = node.args[0] if node.args else None
                else:
                    source = node.func.value if isinstance(node.func, ast.Attribute) else None
                return source is not None and self.is_doc(source, env)
            return False
        if isinstance(node, ast.BoolOp):
            return any(self.is_doc(v, env) for v in node.values)
        if isinstance(node, ast.Subscript):
            return self.is_doc(node.value, env)
        if isinstance(node, ast.IfExp):
            return self.is_doc(node.body, env) or self.is_doc(node.orelse, env)
        return False

    def is_phrase(self, node: ast.AST, env: dict) -> bool:
        if self.is_doc(node, env):
            return False
        if isinstance(node, ast.Constant):
            return isinstance(node.value, str) and bool(node.value)
        if isinstance(node, ast.JoinedStr):
            return any(
                isinstance(v, ast.Constant) and isinstance(v.value, str) and v.value
                for v in node.values
            )
        if isinstance(node, (ast.Name, ast.Attribute)):
            chain = _chain(node)
            return chain is not None and PHRASE in env.get(chain, EMPTY)
        if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
            return any(self.is_phrase(e, env) for e in node.elts)
        if isinstance(node, ast.BinOp):
            return self.is_phrase(node.left, env) or self.is_phrase(node.right, env)
        return False

    def kinds(self, node: ast.AST, env: dict) -> frozenset[str]:
        if self.is_doc(node, env):
            return frozenset({DOC})
        return frozenset({PHRASE}) if self.is_phrase(node, env) else EMPTY

    def bind(self, target: ast.AST, value: ast.AST | None, kinds: frozenset[str], env: dict) -> None:
        if isinstance(target, (ast.Tuple, ast.List)):
            elements = target.elts
            plain = not any(isinstance(e, ast.Starred) for e in elements)
            if (
                plain
                and isinstance(value, (ast.Tuple, ast.List))
                and len(value.elts) == len(elements)
                and not any(isinstance(e, ast.Starred) for e in value.elts)
            ):
                pairs = [(t, v, self.kinds(v, env)) for t, v in zip(elements, value.elts)]
                for t, v, k in pairs:
                    self.bind(t, v, k, env)
            else:
                for t in elements:
                    self.bind(t, None, kinds, env)
        elif isinstance(target, ast.Starred):
            self.bind(target.value, None, kinds, env)
        else:
            chain = _chain(target)
            if chain is not None:
                _set(env, chain, kinds)

    def check(self, line: int, operands: list[ast.AST], env: dict) -> None:
        kinds = [self.kinds(o, env) for o in operands]
        pinned = any(
            DOC in k and any(PHRASE in other for j, other in enumerate(kinds) if j != i)
            for i, k in enumerate(kinds)
        )
        if pinned or any(self.compares(sub, env) for o in operands for sub in ast.walk(o)):
            self.found.add(line)

    def compares(self, node: ast.AST, env: dict) -> bool:
        if isinstance(node, ast.Compare):
            parts = [node.left, *node.comparators]
        elif isinstance(node, ast.Call) and _call_name(node) in MATCH_CALLS | PROBE_CALLS:
            parts = [node.func.value] if isinstance(node.func, ast.Attribute) else []
            parts += node.args
        else:
            return False
        kinds = [self.kinds(p, env) for p in parts]
        return any(DOC in k for k in kinds) and any(PHRASE in k for k in kinds)

    def assertion(self, call: ast.Call, env: dict) -> None:
        name = call.func.attr
        if name in ONE_OPERAND:
            operands = call.args[:1]
        elif name in TWO_OPERANDS:
            operands = call.args[:2]
        elif name in CALLABLE_FORM:
            operands = call.args[:CALLABLE_FORM[name]]
            if len(call.args) > CALLABLE_FORM[name]:
                self.check(call.lineno, operands, env)
                return
        else:
            operands = list(call.args)
        operands = operands + [k.value for k in call.keywords if k.arg not in DIAGNOSTIC_KEYWORDS]
        self.check(call.lineno, operands, env)

    def lambdas(self, node: ast.AST, env: dict) -> None:
        for sub in ast.walk(node):
            if isinstance(sub, ast.Lambda):
                inner = dict(env)
                _unbind_parameters(sub, inner)
                for call in ast.walk(sub.body):
                    if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) \
                            and call.func.attr.startswith("assert"):
                        self.assertion(call, inner)

    def block(self, statements: list[ast.stmt], env: dict) -> None:
        for statement in statements:
            self.statement(statement, env)

    def statement(self, node: ast.stmt, env: dict) -> None:
        if isinstance(node, ast.Assign):
            self.lambdas(node.value, env)
            kinds = self.kinds(node.value, env)
            for target in node.targets:
                self.bind(target, node.value, kinds, env)
        elif isinstance(node, ast.AnnAssign):
            if node.value is not None:
                self.lambdas(node.value, env)
                self.bind(node.target, node.value, self.kinds(node.value, env), env)
        elif isinstance(node, ast.AugAssign):
            self.lambdas(node.value, env)
            chain = _chain(node.target)
            if chain is not None:
                added = env.get(chain, EMPTY) | self.kinds(node.value, env)
                if added:
                    env[chain] = added
        elif isinstance(node, ast.Expr):
            self.lambdas(node.value, env)
            call = node.value
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) \
                    and call.func.attr.startswith("assert"):
                self.assertion(call, env)
        elif isinstance(node, ast.Assert):
            self.check(node.lineno, [node.test], env)
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            if isinstance(node.iter, (ast.Tuple, ast.List, ast.Set)):
                kinds = frozenset().union(*(self.kinds(e, env) for e in node.iter.elts))
            else:
                kinds = self.kinds(node.iter, env)
            self.bind(node.target, None, kinds, env)
            self.block(node.body, env)
            self.block(node.orelse, env)
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                self.lambdas(item.context_expr, env)
                if item.optional_vars is not None:
                    self.bind(item.optional_vars, None, self.kinds(item.context_expr, env), env)
            self.block(node.body, env)
        elif isinstance(node, ast.If):
            taken, other = dict(env), dict(env)
            self.block(node.body, taken)
            self.block(node.orelse, other)
            env.clear()
            for branch in (taken, other):
                for chain, kinds in branch.items():
                    env[chain] = env.get(chain, EMPTY) | kinds
        elif isinstance(node, ast.While):
            self.block(node.body, env)
            self.block(node.orelse, env)
        elif TRIES and isinstance(node, TRIES):
            self.block(node.body, env)
            for handler in node.handlers:
                self.block(handler.body, env)
            self.block(node.orelse, env)
            self.block(node.finalbody, env)
        elif isinstance(node, ast.Match):
            for case in node.cases:
                self.block(case.body, env)
        elif isinstance(node, FUNCTIONS):
            inner = dict(env)
            _unbind_parameters(node, inner)
            self.block(node.body, inner)

    def class_bindings(self, node: ast.ClassDef, module_env: dict) -> dict[str, frozenset[str]]:
        local = dict(module_env)
        names: list[str] = []
        for statement in node.body:
            if isinstance(statement, ast.Assign):
                kinds = self.kinds(statement.value, local)
                for target in statement.targets:
                    if isinstance(target, ast.Name):
                        _set(local, target.id, kinds)
                        names.append(target.id)
        bindings = {}
        for name in names:
            for owner in ("self", "cls", node.name):
                if local.get(name):
                    bindings[f"{owner}.{name}"] = local[name]
        return bindings


def _shell_phrase_test(line: str) -> bool:
    if SHELL_PHRASE_TEST.search(line):
        return True
    return bool(SHELL_COMPARE.search(line) and SHELL_LITERAL.search(SHELL_EMPTY_LITERAL.sub("", line)))


def docstring_findings(path: str, source: str) -> list[tuple[str, int]]:
    if path.endswith(".sh"):
        return [
            (path, number)
            for number, line in enumerate(source.splitlines(), 1)
            if not line.lstrip().startswith("#") and SHELL_DOC.search(line) and _shell_phrase_test(line)
        ]
    tree = ast.parse(source, filename=path)
    walk = _Walk()
    module_env: dict = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            kinds = walk.kinds(node.value, module_env)
            for target in node.targets:
                walk.bind(target, node.value, kinds, module_env)
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            walk.bind(node.target, node.value, walk.kinds(node.value, module_env), module_env)
    findings: set[tuple[str, int]] = set()
    for node in tree.body:
        if isinstance(node, FUNCTIONS):
            units, bindings = [(node.name, node)], {}
        elif isinstance(node, ast.ClassDef):
            units = [(f"{node.name}.{m.name}", m) for m in node.body if isinstance(m, FUNCTIONS)]
            bindings = walk.class_bindings(node, module_env)
        else:
            continue
        for name, unit in units:
            env = dict(module_env)
            _unbind_parameters(unit, env)
            env.update(bindings)
            walk.found = set()
            walk.block(unit.body, env)
            findings.update((f"{path}::{name}", line) for line in walk.found)
    return sorted(findings)


def suite_findings(root: Path) -> list[tuple[str, int]]:
    return sorted(f for path, source in suite_sources(root) for f in docstring_findings(path, source))


def _fixture(text):
    return textwrap.dedent(text).lstrip("\n")


def _body(text):
    return textwrap.indent(_fixture(text), " " * 8)


TEST_ID = "tests/test_f.py::T.test_x"
HEAD = "class T(unittest.TestCase):\n    def test_x(self):\n"

DIRECT_ATTRIBUTE = _fixture(r'''
    class T(unittest.TestCase):
        def test_x(self):
            self.assertIn("phrase", mod.__doc__)
''')

LOOP_NEEDLE = _fixture(r'''
    class T(unittest.TestCase):
        def test_x(self):
            for needle in ("a", "b"):
                with self.subTest(needle):
                    self.assertIn(needle, mod.__doc__)
''')

SAVED_DOC = HEAD + _body(r'''
        doc = mod.__doc__
        self.assertIn("a", doc)
        self.assertNotIn("b", doc)
''')

NORMALISED_DOC = HEAD + _body(r'''
        doc = " ".join(mod.__doc__.split())
        self.assertIn("a b", doc)
        self.assertIn("c d", " ".join((mod.__doc__ or "").split()))
''')

CLASS_CONSTANT = _fixture(r'''
    class T(unittest.TestCase):
        SENTENCES = ("a b", "c d")

        def test_x(self):
            doc = " ".join((mod.__doc__ or "").split())
            for sentence in self.SENTENCES:
                self.assertIn(sentence, doc)
''')

PARSED_DOCSTRING = HEAD + _body(r'''
        doc = ast.get_docstring(ast.parse((ROOT / "python/agent_tools/x.py").read_text()))
        self.assertIn("a", doc)
        source = (ROOT / "python/agent_tools/y.py").read_text()
        flat = " ".join((ast.get_docstring(ast.parse(source)) or "").split())
        self.assertNotIn("b", flat)
        self.assertIn("c", inspect.getdoc(mod))
''')

FSTRING_NEEDLE = HEAD + _body(r'''
        doc = " ".join(mod.__doc__.split())
        self.assertIn(f"names the {len(mod.STATES)} screens", doc)
''')

MODULE_CONSTANT = _fixture(r'''
    NAME = "Domain does not support specified action"


    class T(unittest.TestCase):
        def test_x(self):
            self.assertIn(NAME, mod.__doc__)
            for needle in ("verify_checks.x", NAME):
                self.assertIn(needle, mod.__doc__)
''')

MIXED = HEAD + _body(r'''
        self.assertEqual(mod.run("a"), "a")
        self.assertIn("a", mod.run("a"))
        self.assertIn("notice_block", mod.__doc__)
''')

COMPARING_FORMS = HEAD + _body(r'''
        self.assertTrue("a" in mod.__doc__)
        assert "b" in mod.__doc__
        self.assertTrue(mod.__doc__.startswith("c"))
        self.assertIsNotNone(re.search("d", mod.__doc__))
        self.assertRegex(mod.__doc__, "e")
        self.assertGreaterEqual(mod.__doc__.count("f"), 1)
''')

NESTED_AND_FUNCTION = _fixture(r'''
    def test_top():
        assert "a" in mod.__doc__


    class T(unittest.TestCase):
        def test_x(self):
            def check(text):
                self.assertIn("b", mod.__doc__)
            check(1)
''')

DOCSTRING_EXISTS = HEAD + _body(r'''
        self.assertTrue((mod.f.__doc__ or "").strip())
        self.assertIsNotNone(mod.__doc__)
        self.assertTrue(mod.__doc__, "the module has no docstring")
        self.assertGreater(len(mod.__doc__), 0)
        self.assertNotEqual(mod.__doc__.strip(), "")
''')

HELP_USAGE = HEAD + _body(r'''
        result = run_cli(["--help"])
        self.assertIn("usage: tool", result.stdout)
        self.assertIn("usage:", mod.build_parser().format_help())
''')

DOCSTRING_AS_INPUT = _fixture(r'''
    class T(unittest.TestCase):
        def example(self):
            return mod.__doc__

        def test_x(self):
            result, verdict = lint(self.example())
            self.assertEqual((result.returncode, verdict["ok"]), (0, True))
            block = json.loads(mod.__doc__.split("```verify\n", 1)[1].split("\n```", 1)[0])
            self.assertIn("checks", block)
            self.assertIn(("checks[0].run", "run_form"), lint(mod.__doc__))
''')

COMPUTED_COMPARISON = HEAD + _body(r'''
        self.assertEqual(mod.build_parser().description, mod.__doc__)
        self.assertIn(mod.USAGE_LINE, mod.__doc__)
        self.assertEqual(mod.__doc__, f"{parser.description}")
        self.assertEqual(text.split(mod.__doc__), ["left", "right"])
''')

CALLABLE_FIXTURE = HEAD + _body(r'''
        self.assertRaisesRegex(ValueError, "invalid", parse, mod.__doc__)
        self.assertRaises(ValueError, parse, mod.__doc__)
        self.assertRaisesRegex(ValueError, "invalid", parse, text=mod.__doc__)
''')

BRANCHES = HEAD + _body(r'''
        text = mod.__doc__
        if flag:
            text = run_cli(["--help"]).stdout
            self.assertIn("usage:", text)
        else:
            self.assertIn("phrase", text)
        self.assertIn("after", text)
''')

REBOUND = HEAD + _body(r'''
        doc = mod.__doc__
        doc = run_cli(["--help"]).stdout
        self.assertIn("usage:", doc)
''')


class DocstringScanTest(unittest.TestCase):
    def found(self, source):
        return docstring_findings("tests/test_f.py", source)

    def test_a_phrase_asserted_in_a_module_docstring_is_found(self):
        self.assertEqual(self.found(DIRECT_ATTRIBUTE), [(TEST_ID, 3)])

    def test_a_needle_bound_by_a_loop_over_literals_is_a_phrase(self):
        self.assertEqual(self.found(LOOP_NEEDLE), [(TEST_ID, 5)])

    def test_a_saved_docstring_and_a_negative_pin_are_found(self):
        self.assertEqual(self.found(SAVED_DOC), [(TEST_ID, 4), (TEST_ID, 5)])

    def test_a_whitespace_normalised_docstring_is_still_docstring_text(self):
        self.assertEqual(self.found(NORMALISED_DOC), [(TEST_ID, 4), (TEST_ID, 5)])

    def test_a_class_constant_of_sentences_is_a_phrase(self):
        self.assertEqual(self.found(CLASS_CONSTANT), [(TEST_ID, 7)])

    def test_a_parsed_or_inspected_docstring_is_docstring_text(self):
        self.assertEqual(self.found(PARSED_DOCSTRING), [(TEST_ID, 4), (TEST_ID, 7), (TEST_ID, 8)])

    def test_an_f_string_needle_is_a_phrase(self):
        self.assertEqual(self.found(FSTRING_NEEDLE), [(TEST_ID, 4)])

    def test_a_module_constant_needle_is_a_phrase(self):
        self.assertEqual(self.found(MODULE_CONSTANT), [(TEST_ID, 6), (TEST_ID, 8)])

    def test_only_the_docstring_assertion_of_a_mixed_test_is_found(self):
        self.assertEqual(self.found(MIXED), [(TEST_ID, 5)])

    def test_a_comparison_or_probe_inside_an_assertion_is_found(self):
        self.assertEqual(self.found(COMPARING_FORMS), [(TEST_ID, line) for line in range(3, 9)])

    def test_a_top_level_function_and_a_nested_def_are_scanned(self):
        self.assertEqual(
            self.found(NESTED_AND_FUNCTION),
            [(TEST_ID, 8), ("tests/test_f.py::test_top", 2)],
        )

    def test_a_docstring_existence_check_passes(self):
        self.assertEqual(self.found(DOCSTRING_EXISTS), [])

    def test_a_docstring_passed_to_a_callable_form_assertion_passes(self):
        self.assertEqual(self.found(CALLABLE_FIXTURE), [])

    def test_each_branch_of_an_if_is_scanned_from_the_incoming_bindings(self):
        self.assertEqual(self.found(BRANCHES), [(TEST_ID, 8), (TEST_ID, 9)])

    def test_a_help_usage_check_passes(self):
        self.assertEqual(self.found(HELP_USAGE), [])

    def test_a_docstring_used_as_input_passes(self):
        self.assertEqual(self.found(DOCSTRING_AS_INPUT), [])

    def test_a_docstring_compared_with_a_computed_value_passes(self):
        self.assertEqual(self.found(COMPUTED_COMPARISON), [])

    def test_a_rebound_name_forgets_the_docstring(self):
        self.assertEqual(self.found(REBOUND), [])

    def test_a_source_that_does_not_parse_fails_the_scan(self):
        with self.assertRaises(SyntaxError):
            docstring_findings("tests/test_f.py", "def (:\n")


class DocstringTreeTest(unittest.TestCase):
    def findings(self, files):
        with tempfile.TemporaryDirectory() as tmp:
            write_tree(tmp, files)
            return suite_findings(Path(tmp))

    def test_a_shell_member_testing_a_docstring_phrase_is_found(self):
        script = (
            "#!/usr/bin/env bash\n"
            "python3 -c 'import m; print(m.__doc__)' | grep -q words\n"
            "python3 -c 'import m; assert \"words\" in m.__doc__'\n"
        )
        found = self.findings({"justfile": JUSTFILE_HEAD + "    tests/x.sh\n", "tests/x.sh": script})
        self.assertEqual(found, [("tests/x.sh", 2), ("tests/x.sh", 3)])

    def test_a_shell_docstring_existence_check_or_comment_passes(self):
        script = (
            "#!/usr/bin/env bash\n"
            "# grep m.__doc__ for words\n"
            "python3 -c 'import m; assert m.__doc__'\n"
            "python3 -c 'import m; assert (m.__doc__ or \"\") != \"\"'\n"
        )
        found = self.findings({"justfile": JUSTFILE_HEAD + "    tests/x.sh\n", "tests/x.sh": script})
        self.assertEqual(found, [])

    def test_the_guard_files_are_never_scanned(self):
        found = self.findings({
            "justfile": JUSTFILE_HEAD + "    tests/test_guard_policy.py\n",
            "tests/test_guard_policy.py": DIRECT_ATTRIBUTE,
            "tests/test_claude_permission_guard.py": DIRECT_ATTRIBUTE,
        })
        self.assertEqual(found, [])


class SuiteDocstringTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sources = suite_sources(REPO_ROOT)
        cls.findings = suite_findings(REPO_ROOT)

    def test_every_kept_docstring_credential_test_still_pins_a_docstring_and_names_a_credential(self):
        self.assertEqual(kept_list_problems(KEPT_DOCSTRING_TESTS, self.sources, self.findings), [])

    def test_no_suite_test_pins_a_module_docstrings_wording(self):
        left = sorted({f"{t}:{line}" for t, line in self.findings if t not in KEPT_DOCSTRING_TESTS})
        self.assertEqual(left, [], "\n".join(left))

    def test_the_scan_is_one_member_of_the_suite_recipe(self):
        self.assertEqual(suite_members(REPO_ROOT).count("tests/test_module_docstring_wording.py"), 1)


if __name__ == "__main__":
    unittest.main()
