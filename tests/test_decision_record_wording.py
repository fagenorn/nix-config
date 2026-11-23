"""Fail the suite when a test pins a decision record's wording (issue 1309, standard:P14).

A decision record under docs/areas/<area>/adr/ is prose. A test that asserts the prose contains,
equals, starts or ends with given words fails on a rewording and stays green when the recorded
behaviour breaks. Standard P14 forbids such a test; this module is the gate. It scans, with the
standard library `ast`, every member of the `agent-workflow-tests` recipe plus `tests/*.py` and
`home/common/agent-skills/tests/*.py`, never the two guard test files, and reports each wording
assertion as (test id, line). Its own tests run on string fixtures; `SuiteWordingTest` runs it on
the real tree and checks `KEPT_AT_START`, the wording tests on main when the scan landed whose
source names a token, credential, secret, password or keychain, or calls `logins_in`. A listed test
that is gone, no longer names one of those words, or no longer pins wording fails the scan.

Scan rule for a `.py` source:

1. Readers. A reader is any function or method, at any depth, whose body calls
   a name in READ_CALLS with one of the function's own parameters in the call's
   receiver or arguments. A call's name is `func.id` for a Name and
   `func.attr` for an Attribute.
2. Units and environments. An environment maps a name to a set of kinds drawn
   from ADR, AREAS, DOCS, TEXT, PHRASE and MATCH. The module's top-level statements
   (defs and classes excepted) build the module environment, in order. Each
   unit, a top-level function or a method of a top-level class, is walked from
   a copy of it with its parameters bound to no kind.
3. Kinds of an expression E. A Name, or an attribute chain of Names such as
   `self.text`, has the kinds its environment gives it, but a name holding TEXT
   never holds PHRASE. ADR: E's subtree holds a string
   constant ADR_PATH matches, a path expression whose literal text ADR_PATH
   matches, a Name with ADR, or a path expression with a part holding AREAS
   and another part whose text has an `adr` segment, or an f-string, `+` chain,
   `.format` or `%` on a string whose parts hold AREAS and whose text has an
   `adr` segment, or a glob or rglob call whose receiver text and pattern text,
   joined by `/`, ADR_PATH matches. A path expression is a
   string, an f-string, a `+` concatenation, a `/` chain, a call of Path,
   PurePath, joinpath or os.path.join, `"/".join` of a list or tuple, or
   `.format` or `%` on a string; its
   literal text puts `_` for each formatted value or other segment, nothing
   between the operands of `+` and `/` between the segments of the others. Its
   parts are the operands of `/`, the receiver (of joinpath) and the arguments
   of a joining call, and the receiver plus the first argument of a glob or
   rglob call. AREAS: a path expression whose text AREAS_ROOT matches, or a
   Name with AREAS. DOCS: a path expression whose text DOCS_ROOT matches. A Name
   (or attribute chain) with AREAS or DOCS stands, in a path expression's text,
   for `docs/areas` or `docs`. TEXT: a call named in READ_CALLS or in the readers whose receiver or
   any argument has ADR, or a Name with TEXT. PHRASE: E is not TEXT and its
   subtree holds a string constant, an f-string or a Name with PHRASE. MATCH:
   E itself (through `not` and each operand of `and`/`or`) is a wording
   comparison, or E is a Name with MATCH, or a Subscript, Compare or Call with a
   MATCH part (so `len(hits)` of a saved result is MATCH), or a comprehension with
   a MATCH condition (its loop items carry no TEXT: the condition reads the record itself). A wording comparison is a Compare, or a call named in
   MATCH_CALLS or PROBE_CALLS (`startswith`, `search`, `count`, `find`), whose
   parts (the compared operands, or the receiver plus positional arguments) hold
   a TEXT part and a PHRASE part. Any other call (`re.findall`, `split`,
   `joinpath`) is no comparison and its result carries no MATCH, so extracting
   links from a record and checking each target passes.
   A comprehension is evaluated in its own copy of the environment, each
   generator binding its targets before its conditions and element; a lambda
   body binds its parameters to no kind.
4. Fixture methods. The `self.` attributes that `setUpClass` and `setUp` (and their async
   forms; the owner is the first parameter, `cls` or `self`) leave start every method of
   the class, those of its base classes defined in the module included. A
   statement `self.helper()` that names a method of the class or its bases runs
   that method's body, so the attributes it sets stay (a method already
   running is not run again).

5. Bindings follow statement order with flow. An assignment, a for target, a
   with variable and a walrus replace the target's kinds (an augmented
   assignment adds); a target is a name or an attribute chain, and binding a
   name forgets the chains that start with it. `if`, `try` and `match` branches start from the same state
   and join by union. A loop body is walked until its head state stops
   changing. A nested def is walked from a copy of the state at its definition
   with its parameters bound to no kind; its assertions belong to the unit.
   Findings are collected only on the final walk, in the converged states.
6. An assertion is a call whose func is an Attribute named `assert*`, or an
   `assert` statement. Its operands are the values compared: the first
   positional argument of assertTrue, assertFalse, assertIsNone and
   assertIsNotNone, the first two of the other unittest comparisons, every
   positional argument of any other `assert*` call, and every keyword argument
   but msg, places, delta and seq_type. A diagnostic message is no operand. It
   is a finding, recorded once at its line, when one operand has TEXT and
   another has PHRASE (rule A), when an operand or the assert test holds a
   Compare or a comparing or probing Call whose parts hold a TEXT part and a PHRASE part (rule B),
   or when an operand has MATCH (rule C).

Limit. The scan is a tripwire against regrowth, not a proof against every spelling: it catches the
spellings the suite's own tests used before this gate (each has a fixture) and promises nothing
beyond them. It sees only literal phrases compared with text read through a call on a record path,
so a comparison of record text with a value computed from code is not caught. Out of scope: a
recursive glob from a docs root, record text bound in a class body, an f-string or `+` concatenation
over a variable root, an inherited setUp, and similar adversarial spellings.

A `.sh` member is a finding on every line that names a record, because a shell
member never names one. A suite member of any other kind fails the scan, and a
source that does not parse fails it too: nothing is skipped.
"""

import ast
import re
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
ADR_PATH = re.compile(r"docs/areas/[^/\s'\"\x60]+/adr(?:/|$)")
ADR_SEGMENT = re.compile(r"(?:^|/)adr(?:/|$)")
AREAS_ROOT = re.compile(r"(?:^|/)docs/areas/?$")
DOCS_ROOT = re.compile(r"(?:^|/)docs/?$")
# `logins_in` is the check that a record names no login, a credential-shaped leak check.
CREDENTIAL_WORDS = re.compile(r"token|credential|secret|password|keychain|\blogins_in\b", re.IGNORECASE)
GUARD_FILES = frozenset({"tests/test_claude_permission_guard.py", "tests/test_guard_policy.py"})
SUITE_RECIPE = "agent-workflow-tests *args:"
SUITE_GLOBS = ("tests/*.py", "home/common/agent-skills/tests/*.py")
PATH_BUILDERS = frozenset({"Path", "PurePath", "PurePosixPath", "PureWindowsPath", "joinpath"})
GLOB_CALLS = frozenset({"glob", "rglob"})
READ_CALLS = frozenset({"read_text", "read_bytes", "read", "readlines", "open"})
MATCH_CALLS = frozenset({"startswith", "endswith", "search", "match", "fullmatch"})
PROBE_CALLS = frozenset({"count", "find", "rfind", "index", "rindex"})
ONE_OPERAND = frozenset({"assertTrue", "assertFalse", "assertIsNone", "assertIsNotNone"})
TWO_OPERANDS = frozenset({
    "assertEqual", "assertNotEqual", "assertIn", "assertNotIn", "assertIs", "assertIsNot",
    "assertGreater", "assertGreaterEqual", "assertLess", "assertLessEqual", "assertAlmostEqual",
    "assertNotAlmostEqual", "assertRegex", "assertNotRegex", "assertCountEqual",
    "assertMultiLineEqual", "assertSequenceEqual", "assertListEqual", "assertTupleEqual",
    "assertSetEqual", "assertDictEqual", "assertIsInstance", "assertNotIsInstance",
    "assertStartsWith", "assertNotStartsWith", "assertEndsWith", "assertNotEndsWith",
})
DIAGNOSTIC_KEYWORDS = frozenset({"msg", "places", "delta", "seq_type"})

# The kept wording tests (standard:P14). Adding an id here is a new decision with its own record.
KEPT_AT_START = frozenset({
    "tests/test_docs_tree.py::DocsTreeTest.test_the_guest_socket_amendment_is_recorded_as_adr_077",
})
# A sync merge that brings a kept test in from main adds it here, never above.
KEPT_FROM_MAIN: frozenset[str] = frozenset({
    "tests/test_docs_tree.py::DocsTreeTest.test_the_tailnet_name_source_is_recorded_as_adr_078",
})
KEPT_CREDENTIAL_TESTS = KEPT_AT_START | KEPT_FROM_MAIN

EMPTY: frozenset[str] = frozenset()
# Kinds that mark a name's own value and never spread to an expression that holds the name.
NOT_CARRIED = frozenset({"MATCH", "DOCS"})
COMPREHENSIONS = (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)
LOOPS = (ast.For, ast.AsyncFor, ast.While)
FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)
TRIES = tuple(t for t in (getattr(ast, "Try", None), getattr(ast, "TryStar", None)) if t)


def suite_members(root: Path) -> list[str]:
    lines = (root / "justfile").read_text(encoding="utf-8").splitlines()
    if SUITE_RECIPE not in lines:
        raise ValueError(f"justfile has no {SUITE_RECIPE!r} recipe")
    body = []
    for line in lines[lines.index(SUITE_RECIPE) + 1:]:
        if not line.startswith("  "):
            break
        body.append(line)
    return [line.strip().removesuffix(" \\") for line in body[1:]]


def suite_sources(root: Path) -> list[tuple[str, str]]:
    selected = set(suite_members(root))
    for pattern in SUITE_GLOBS:
        selected.update(path.relative_to(root).as_posix() for path in root.glob(pattern))
    selected -= GUARD_FILES
    members = sorted(selected)
    for member in members:
        if not member.endswith((".py", ".sh")):
            raise ValueError(f"{member}: a suite member that is neither .py nor .sh escapes the scan")
    return [(member, (root / member).read_text(encoding="utf-8")) for member in members]


def _call_name(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


_UNKNOWN = "_"


def _text(node: ast.AST, env: dict | None = None) -> str:
    static = _static_text(node, env)
    return _UNKNOWN if static is None else static


def _joining_parts(node: ast.AST) -> list[ast.AST] | None:
    """The parts a path expression joins with `/`, or None when it is not a joining call."""
    if not isinstance(node, ast.Call):
        return None
    name = _call_name(node)
    receiver = node.func.value if isinstance(node.func, ast.Attribute) else None
    if name in PATH_BUILDERS:
        return ([receiver] if name == "joinpath" and receiver is not None else []) + list(node.args)
    if name == "join" and isinstance(node.func, ast.Name):
        return list(node.args)
    if name == "join" and receiver is not None:
        if isinstance(receiver, ast.Constant) and receiver.value == "/":
            if node.args and isinstance(node.args[0], (ast.Tuple, ast.List)):
                return list(node.args[0].elts)
            return None
        if _key(receiver) is not None and _key(receiver).split(".")[-1] in {"path", "posixpath", "ntpath"}:
            return list(node.args)
    return None


def _static_text(node: ast.AST, env: dict | None = None) -> str | None:
    """The literal text of a path expression; `_` stands for the rest. A name the environment
    knows holds the docs root or the areas root stands for that root's text."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if env and isinstance(node, (ast.Name, ast.Attribute)):
        kinds = env.get(_key(node), EMPTY)
        if "AREAS" in kinds:
            return "docs/areas"
        return "docs" if "DOCS" in kinds else None
    if isinstance(node, ast.JoinedStr):
        return "".join(
            v.value if isinstance(v, ast.Constant) and isinstance(v.value, str) else "_"
            for v in node.values
        )
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Div, ast.Add)):
        left, right = _static_text(node.left, env), _static_text(node.right, env)
        joined = [_UNKNOWN if side is None else side for side in (left, right)]
        if isinstance(node.op, ast.Add):
            return None if left is None and right is None else "".join(joined)
        return "/".join(joined)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
        return _static_text(node.left, env) if _is_string(node.left) else None
    if isinstance(node, ast.Call) and _call_name(node) == "format" and isinstance(node.func, ast.Attribute):
        return _static_text(node.func.value, env) if _is_string(node.func.value) else None
    parts = _joining_parts(node)
    if parts is not None:
        return "/".join(_text(part, env) for part in parts)
    return None


def _is_string(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, str)


def _assembled_parts(node: ast.AST) -> list[ast.AST] | None:
    """The parts an f-string, a `+` chain, a `.format` or a `%` assembles into one path, else None."""
    if isinstance(node, ast.JoinedStr):
        return [v.value if isinstance(v, ast.FormattedValue) else v for v in node.values]
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _plus_operands(node)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod) and _is_string(node.left):
        right = node.right
        return [node.left, *(right.elts if isinstance(right, (ast.Tuple, ast.List)) else [right])]
    if isinstance(node, ast.Call) and _call_name(node) == "format" and isinstance(node.func, ast.Attribute):
        if _is_string(node.func.value):
            return [node.func.value, *node.args, *(k.value for k in node.keywords)]
    return None


def _plus_operands(node: ast.AST) -> list[ast.AST]:
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _plus_operands(node.left) + _plus_operands(node.right)
    return [node]


def _glob_text(node: ast.AST, env: dict | None = None) -> str | None:
    """The receiver's text and the pattern's text of a glob call, joined, else None."""
    if isinstance(node, ast.Call) and _call_name(node) in GLOB_CALLS and isinstance(node.func, ast.Attribute) and node.args:
        return f"{_text(node.func.value, env)}/{_text(node.args[0], env)}"
    return None


def _parameters(node) -> list[str]:
    args = node.args
    names = [a.arg for a in args.posonlyargs + args.args + args.kwonlyargs]
    names += [a.arg for a in (args.vararg, args.kwarg) if a]
    return names


def _readers(tree: ast.AST) -> frozenset[str]:
    names = set()
    for node in ast.walk(tree):
        if not isinstance(node, FUNCTIONS):
            continue
        params = set(_parameters(node))
        for call in ast.walk(node):
            if not isinstance(call, ast.Call) or _call_name(call) not in READ_CALLS:
                continue
            operands = [call.func.value] if isinstance(call.func, ast.Attribute) else []
            operands += call.args + [k.value for k in call.keywords]
            if any(isinstance(n, ast.Name) and n.id in params for o in operands for n in ast.walk(o)):
                names.add(node.name)
                break
    return frozenset(names)


def _join(*envs: dict) -> dict:
    joined: dict[str, frozenset[str]] = {}
    for env in envs:
        for name, kinds in env.items():
            joined[name] = joined.get(name, EMPTY) | kinds
    return joined


def _key(node: ast.AST) -> str | None:
    """The dotted name of a Name or an attribute chain of Names, else None."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        return ".".join([node.id, *reversed(parts)])
    return None


def _store(env: dict, name: str, kinds: frozenset[str]) -> None:
    for key in [key for key in env if key.startswith(name + ".")]:
        del env[key]
    if kinds:
        env[name] = kinds
    else:
        env.pop(name, None)


def _bind(target: ast.AST, kinds: frozenset[str], env: dict, add: bool = False) -> None:
    if isinstance(target, ast.Name):
        _store(env, target.id, (env.get(target.id, EMPTY) | kinds) if add else kinds)
    elif isinstance(target, ast.Attribute):
        key = _key(target)
        if key is not None:
            _store(env, key, (env.get(key, EMPTY) | kinds) if add else kinds)
    elif isinstance(target, (ast.Tuple, ast.List)):
        for element in target.elts:
            _bind(element, kinds, env, add)
    elif isinstance(target, ast.Starred):
        _bind(target.value, kinds, env, add)


def _unbind_parameters(node, env: dict) -> None:
    for name in _parameters(node):
        _store(env, name, EMPTY)


class _Scan:
    """One module's scan: the readers are fixed, the environments flow."""

    def __init__(self, readers: frozenset[str]):
        self.readers = readers
        self.collect = False
        self.found: set[int] = set()
        self.methods: dict[str, ast.AST] = {}  # the methods of the class being walked, by name
        self.owner: str | None = None  # the walked method's first parameter, `self` or `cls`
        self.stack: set[str] = set()

    # Expressions -----------------------------------------------------------

    def walk(self, node: ast.AST, env: dict):
        """Yield every sub-node with the environment it is evaluated in."""
        yield node, env
        if isinstance(node, COMPREHENSIONS):
            inner = dict(env)
            for generator in node.generators:
                yield from self.walk(generator.iter, inner)
                _bind(generator.target, self.kinds(generator.iter, inner), inner)
                for condition in generator.ifs:
                    yield from self.walk(condition, inner)
            parts = (node.key, node.value) if isinstance(node, ast.DictComp) else (node.elt,)
            for part in parts:
                yield from self.walk(part, inner)
        elif isinstance(node, ast.Lambda):
            for default in node.args.defaults + [d for d in node.args.kw_defaults if d]:
                yield from self.walk(default, env)
            inner = dict(env)
            _unbind_parameters(node, inner)
            yield from self.walk(node.body, inner)
        else:
            for child in ast.iter_child_nodes(node):
                yield from self.walk(child, env)

    def facts(self, node: ast.AST, env: dict) -> frozenset[str]:
        """The ADR, AREAS, TEXT and PHRASE kinds of the expression."""
        found: set[str] = set()
        for sub, scope in self.walk(node, env):
            static = _static_text(sub, scope)
            if static is not None:
                if isinstance(sub, (ast.Constant, ast.JoinedStr)):
                    found.add("PHRASE")
                if ADR_PATH.search(static):
                    found.add("ADR")
                if AREAS_ROOT.search(static):
                    found.add("AREAS")
            if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load):
                found |= scope.get(sub.id, EMPTY) - NOT_CARRIED
            elif isinstance(sub, ast.Attribute) and isinstance(sub.ctx, ast.Load):
                found |= scope.get(_key(sub), EMPTY) - NOT_CARRIED
            elif isinstance(sub, ast.Call) and _call_name(sub) in READ_CALLS | self.readers:
                operands = [sub.func.value] if isinstance(sub.func, ast.Attribute) else []
                operands += sub.args + [k.value for k in sub.keywords]
                if any("ADR" in self.facts(o, scope) for o in operands):
                    found.add("TEXT")
            combined = _glob_text(sub, scope)
            if combined is not None and ADR_PATH.search(combined):
                found.add("ADR")
            assembled = _assembled_parts(sub)
            if (
                assembled is not None
                and ADR_SEGMENT.search(_text(sub, scope))
                and any("AREAS" in self.facts(part, scope) for part in assembled)
            ):
                found.add("ADR")
            if isinstance(sub, ast.BinOp) and isinstance(sub.op, ast.Div):
                parts = [sub.left, sub.right]
            elif isinstance(sub, ast.Call) and _call_name(sub) in GLOB_CALLS and isinstance(sub.func, ast.Attribute):
                parts = [sub.func.value, *sub.args[:1]]
            else:
                parts = _joining_parts(sub) or []
            if len(parts) > 1 and any(ADR_SEGMENT.search(_text(part, scope)) for part in parts) and any(
                "AREAS" in self.facts(part, scope) for part in parts
            ):
                found.add("ADR")
        if "TEXT" in found:
            found.discard("PHRASE")
        return frozenset(found)

    def kinds(self, node: ast.AST, env: dict) -> frozenset[str]:
        found = self.facts(node, env)
        if self.is_match(node, env):
            found |= {"MATCH"}
        static = _static_text(node, env)
        if static is not None and DOCS_ROOT.search(static):
            found |= {"DOCS"}
        return found

    def parts_pin_wording(self, parts: list[ast.AST], env: dict) -> bool:
        part_kinds = [self.facts(part, env) for part in parts]
        return any("TEXT" in k for k in part_kinds) and any("PHRASE" in k for k in part_kinds)

    def is_wording_comparison(self, node: ast.AST, env: dict) -> bool:
        if isinstance(node, ast.Compare):
            return self.parts_pin_wording([node.left, *node.comparators], env)
        if isinstance(node, ast.Call) and _call_name(node) in MATCH_CALLS | PROBE_CALLS:
            return self.call_pins_wording(node, env)
        return False

    def call_pins_wording(self, call: ast.Call, env: dict) -> bool:
        """A comparing or probing call with record text and a phrase among its parts."""
        return _call_name(call) in MATCH_CALLS | PROBE_CALLS and self.parts_pin_wording(self.call_parts(call), env)

    @staticmethod
    def operands(call: ast.Call) -> list[ast.AST]:
        name = call.func.attr
        positional = list(call.args)
        if name in ONE_OPERAND:
            positional = positional[:1]
        elif name in TWO_OPERANDS:
            positional = positional[:2]
        return positional + [k.value for k in call.keywords if k.arg not in DIAGNOSTIC_KEYWORDS]

    @staticmethod
    def call_parts(call: ast.Call) -> list[ast.AST]:
        receiver = [call.func.value] if isinstance(call.func, ast.Attribute) else []
        return receiver + list(call.args)

    def is_match(self, node: ast.AST, env: dict) -> bool:
        if isinstance(node, (ast.Name, ast.Attribute)):
            return "MATCH" in env.get(_key(node), EMPTY)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            return self.is_match(node.operand, env)
        if isinstance(node, ast.BoolOp):
            return any(self.is_match(value, env) for value in node.values)
        if isinstance(node, ast.Subscript):
            return self.is_match(node.value, env)
        if isinstance(node, COMPREHENSIONS):
            inner = dict(env)
            for generator in node.generators:
                # An item bound by the loop is no record text; the condition must read it itself.
                _bind(generator.target, self.kinds(generator.iter, inner) - {"TEXT"}, inner)
                if any(self.is_match(condition, inner) for condition in generator.ifs):
                    return True
            return False
        if isinstance(node, ast.Compare) and any(self.is_match(p, env) for p in [node.left, *node.comparators]):
            return True
        if isinstance(node, ast.Call) and any(self.is_match(p, env) for p in self.call_parts(node)):
            return True
        return self.is_wording_comparison(node, env)

    def bind_walrus(self, expression: ast.AST, env: dict) -> None:
        for node in ast.walk(expression):
            if isinstance(node, ast.NamedExpr) and isinstance(node.target, ast.Name):
                _store(env, node.target.id, self.kinds(node.value, env))

    # Assertions ------------------------------------------------------------

    def pins_wording(self, args: list[ast.AST], env: dict, rule_a: bool) -> bool:
        argument_kinds = [self.facts(a, env) for a in args]
        if rule_a:
            for i, left in enumerate(argument_kinds):
                for j, right in enumerate(argument_kinds):
                    if i != j and "TEXT" in left and "PHRASE" in right:
                        return True
        for argument in args:
            for sub, scope in self.walk(argument, env):
                if isinstance(sub, ast.Compare) and self.is_wording_comparison(sub, scope):
                    return True
                if isinstance(sub, ast.Call) and self.call_pins_wording(sub, scope):
                    return True
            if self.is_match(argument, env):
                return True
        return False

    def check(self, expression: ast.AST, env: dict) -> None:
        for sub, scope in self.walk(expression, env):
            if (
                isinstance(sub, ast.Call)
                and isinstance(sub.func, ast.Attribute)
                and sub.func.attr.startswith("assert")
                and self.pins_wording(self.operands(sub), scope, rule_a=True)
            ):
                self.found.add(sub.lineno)

    def scan(self, expressions, env: dict) -> None:
        for expression in expressions:
            self.bind_walrus(expression, env)
            if self.collect:
                self.check(expression, env)

    # Statements ------------------------------------------------------------

    def block(self, statements, env: dict, in_unit: bool = True) -> dict:
        for statement in statements:
            env = self.statement(statement, env, in_unit)
        return env

    def loop(self, head: dict, step) -> dict:
        outer = self.collect
        self.collect = False
        while True:
            joined = _join(head, step(dict(head)))
            if joined == head:
                break
            head = joined
        self.collect = outer
        if outer:
            step(dict(head))
        return head

    def statement(self, node: ast.stmt, env: dict, in_unit: bool) -> dict:
        if isinstance(node, FUNCTIONS):
            if in_unit:
                inner = dict(env)
                _unbind_parameters(node, inner)
                self.block(node.body, inner)
            return env
        if isinstance(node, ast.ClassDef):
            return env
        if isinstance(node, ast.Assign):
            self.scan([node.value], env)
            kinds = self.kinds(node.value, env)
            for target in node.targets:
                _bind(target, kinds, env)
        elif isinstance(node, ast.AnnAssign):
            if node.value is not None:
                self.scan([node.value], env)
                _bind(node.target, self.kinds(node.value, env), env)
        elif isinstance(node, ast.AugAssign):
            self.scan([node.value], env)
            _bind(node.target, self.kinds(node.value, env), env, add=True)
        elif isinstance(node, ast.Assert):
            self.bind_walrus(node.test, env)
            if self.collect and self.pins_wording([node.test], env, rule_a=False):
                self.found.add(node.lineno)
            if self.collect and node.msg is not None:
                self.check(node.msg, env)
        elif isinstance(node, ast.If):
            self.scan([node.test], env)
            return _join(self.block(node.body, dict(env), in_unit), self.block(node.orelse, dict(env), in_unit))
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            self.scan([node.iter], env)

            def for_step(state: dict) -> dict:
                _bind(node.target, self.kinds(node.iter, state), state)
                return self.block(node.body, state, in_unit)

            head = self.loop(env, for_step)
            return self.block(node.orelse, dict(head), in_unit)
        elif isinstance(node, ast.While):
            self.scan([node.test], env)
            head = self.loop(env, lambda state: self.block(node.body, state, in_unit))
            return self.block(node.orelse, dict(head), in_unit)
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                self.scan([item.context_expr], env)
                if item.optional_vars is not None:
                    _bind(item.optional_vars, self.kinds(item.context_expr, env), env)
            return self.block(node.body, env, in_unit)
        elif TRIES and isinstance(node, TRIES):
            outs = [self.block(node.orelse, self.block(node.body, dict(env), in_unit), in_unit)]
            for handler in node.handlers:
                inner = dict(env)
                if handler.name:
                    inner.pop(handler.name, None)
                outs.append(self.block(handler.body, inner, in_unit))
            return self.block(node.finalbody, _join(*outs), in_unit)
        elif hasattr(ast, "Match") and isinstance(node, ast.Match):
            self.scan([node.subject], env)
            outs = [env] + [self.block(case.body, dict(env), in_unit) for case in node.cases]
            return _join(*outs)
        elif isinstance(node, ast.Expr):
            self.scan([node.value], env)
            self.inline(node.value, env)
        else:
            self.scan([c for c in ast.iter_child_nodes(node) if isinstance(c, ast.expr)], env)
        return env

    def inline(self, call: ast.AST, env: dict) -> None:
        """`self.helper()` as a statement runs the helper's body: the attributes it sets stay."""
        func = call.func if isinstance(call, ast.Call) else None
        if not (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id == self.owner
            and func.attr in self.methods
            and func.attr not in self.stack
        ):
            return
        method = self.methods[func.attr]
        params = _parameters(method)
        if not params or any(_key(d) == "staticmethod" for d in method.decorator_list):
            return
        caller, callee = self.owner, params[0]
        inner = {(callee + k[len(caller):] if k.startswith(caller + ".") else k): v for k, v in env.items()}
        for name in params[1:]:
            _store(inner, name, EMPTY)
        outer = (self.collect, self.owner)
        self.collect, self.owner = False, callee
        self.stack.add(func.attr)
        try:
            end = self.block(method.body, inner)
        finally:
            self.stack.discard(func.attr)
            self.collect, self.owner = outer
        for key in [k for k in env if k.startswith(caller + ".")]:
            del env[key]
        env.update({caller + k[len(callee):]: v for k, v in end.items() if k.startswith(callee + ".")})


FIXTURE_METHODS = ("setUpClass", "asyncSetUpClass", "setUp", "asyncSetUp")


def _class_chain(cls: ast.ClassDef, classes: dict, seen: frozenset = frozenset()) -> list[ast.ClassDef]:
    """The classes of this module a class derives from, bases first, then the class."""
    chain: list[ast.ClassDef] = []
    for base in reversed(cls.bases):
        if isinstance(base, ast.Name) and base.id in classes and base.id not in seen | {cls.name}:
            chain += [c for c in _class_chain(classes[base.id], classes, seen | {cls.name}) if c not in chain]
    return chain + [cls]


def _class_methods(chain: list[ast.ClassDef]) -> dict:
    return {m.name: m for c in chain for m in c.body if isinstance(m, FUNCTIONS)}


def _fixture_attributes(scan: _Scan, chain: list[ast.ClassDef], module_env: dict) -> dict:
    """The `self.` attributes the fixture methods of a class and its bases leave, as each test
    method starts with them. A base's fixtures count even where the class overrides them."""
    carried: dict[str, frozenset[str]] = {}
    outer = (scan.collect, scan.owner, scan.methods)
    scan.collect, scan.methods = False, _class_methods(chain)
    for cls in chain:
        methods = {m.name: m for m in cls.body if isinstance(m, FUNCTIONS)}
        for name in FIXTURE_METHODS:
            method = methods.get(name)
            if method is None or not _parameters(method):
                continue
            env = dict(module_env)
            _unbind_parameters(method, env)
            env.update(carried)
            scan.owner = _parameters(method)[0]
            end = scan.block(method.body, env)
            owner = scan.owner + "."
            carried.update({"self." + key[len(owner):]: kinds for key, kinds in end.items() if key.startswith(owner)})
    scan.collect, scan.owner, scan.methods = outer
    return carried


def wording_findings(path: str, source: str) -> list[tuple[str, int]]:
    if path.endswith(".sh"):
        return [
            (path, number)
            for number, line in enumerate(source.splitlines(), 1)
            if ADR_PATH.search(line)
        ]
    tree = ast.parse(source, filename=path)
    if not any(
        any(
            text is not None and (ADR_PATH.search(text) or AREAS_ROOT.search(text) or DOCS_ROOT.search(text))
            for text in (_static_text(node), _glob_text(node))
        )
        for node in ast.walk(tree)
    ):
        return []  # no literal text can name a record or the areas root
    scan = _Scan(_readers(tree))
    module_env = scan.block(tree.body, {}, in_unit=False)
    findings: list[tuple[str, int]] = []
    classes = {n.name: n for n in tree.body if isinstance(n, ast.ClassDef)}
    for node in tree.body:
        if isinstance(node, FUNCTIONS):
            units = [(node.name, node)]
        elif isinstance(node, ast.ClassDef):
            units = [(f"{node.name}.{m.name}", m) for m in node.body if isinstance(m, FUNCTIONS)]
        else:
            continue
        chain = _class_chain(node, classes) if isinstance(node, ast.ClassDef) else []
        carried = _fixture_attributes(scan, chain, module_env) if chain else {}
        scan.methods = _class_methods(chain)
        for name, unit in units:
            env = dict(module_env)
            _unbind_parameters(unit, env)
            env.update(carried)
            scan.found = set()
            scan.collect = True
            params = _parameters(unit)
            scan.owner = params[0] if chain and params else None
            scan.block(unit.body, env)
            findings += [(f"{path}::{name}", line) for line in scan.found]
    return sorted(findings)


def suite_findings(root: Path) -> list[tuple[str, int]]:
    return sorted(f for path, source in suite_sources(root) for f in wording_findings(path, source))


def _method_span(source: str, test_id: str) -> str | None:
    """The method's text, from its first decorator line to its last line, or None."""
    _, _, name = test_id.partition("::")
    owner, _, method = name.rpartition(".")
    tree = ast.parse(source)
    scope = tree.body
    if owner:
        classes = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == owner]
        if not classes:
            return None
        scope = classes[0].body
    for node in scope:
        if isinstance(node, FUNCTIONS) and node.name == method:
            first = min([node.lineno] + [d.lineno for d in node.decorator_list])
            return "\n".join(source.splitlines()[first - 1:node.end_lineno])
    return None


def kept_list_problems(kept, sources, findings) -> list[str]:
    by_path = dict(sources)
    flagged = {test_id for test_id, _ in findings}
    problems = []
    for test_id in kept:
        path = test_id.partition("::")[0]
        if path in GUARD_FILES:
            problems.append(f"guard file: {test_id}")
        elif path not in by_path or (span := _method_span(by_path[path], test_id)) is None:
            problems.append(f"missing: {test_id}")
        elif not CREDENTIAL_WORDS.search(span):
            problems.append(f"no credential word: {test_id}")
        elif test_id not in flagged:
            problems.append(f"not flagged: {test_id}")
    return sorted(problems)


def _fixture(text):
    return textwrap.dedent(text).lstrip("\n")


READ_THEN_ASSERT = _fixture(r'''
    class T(unittest.TestCase):
        def test_x(self):
            text = (ROOT / "docs/areas/a/adr/001-x.md").read_text()
            self.assertIn("words", text)
''')

LOOP_NEEDLE = _fixture(r'''
    class T(unittest.TestCase):
        def doc(self, path):
            return (ROOT / path).read_text()

        def test_x(self):
            adr = self.doc("docs/areas/a/adr/001-x.md")
            for needle in ("one", "two"):
                self.assertIn(needle, adr)
''')

STARTSWITH_TITLE = _fixture(r'''
    class T(unittest.TestCase):
        def test_x(self):
            found = sorted((ROOT / "docs/areas/a/adr").glob("001-*.md"))
            self.assertTrue(found[0].read_text().startswith("# ADR-a-001"))
''')

MODULE_DIRECTORY = _fixture(r'''
    ADR_DIR = ROOT / "docs/areas/a/adr"


    class T(unittest.TestCase):
        def test_x(self):
            for p in ADR_DIR.glob("*.md"):
                self.assertIn("Decided in", p.read_text())
''')

AREAS_JOIN = _fixture(r'''
    class T(unittest.TestCase):
        def test_x(self):
            for area in (ROOT / "docs/areas").iterdir():
                for p in (area / "adr").glob("*.md"):
                    self.assertIn("Status", p.read_text())
''')

NESTED_READER = _fixture(r'''
    class T(unittest.TestCase):
        def test_x(self):
            def status(path):
                return next(r for r in (ROOT / path).read_text().splitlines() if r.startswith("- **Status:**"))

            self.assertEqual(status("docs/areas/a/adr/001-x.md"), "- **Status:** accepted")
''')

WITH_OPEN = _fixture(r'''
    class T(unittest.TestCase):
        def test_x(self):
            with open(ROOT / "docs/areas/a/adr/001-x.md") as f:
                text = f.read()
            self.assertNotIn("gone words", text)
''')

GLOB_COUNT = _fixture(r'''
    class T(unittest.TestCase):
        def test_x(self):
            self.assertEqual(len(list((ROOT / "docs/areas/a/adr").glob("001-*.md"))), 1)
''')

NUMBER_UNIQUENESS = _fixture(r'''
    class T(unittest.TestCase):
        def test_x(self):
            for area in sorted((ROOT / "docs/areas").iterdir()):
                seen = {}
                for adr in sorted((area / "adr").glob("[0-9][0-9][0-9]-*.md")):
                    number = adr.name[:3]
                    self.assertNotIn(number, seen, f"{seen.get(number)} and {adr.name}")
                    seen[number] = adr.name
''')

LINK_TARGETS = _fixture(r'''
    class T(unittest.TestCase):
        def test_x(self):
            text = (ROOT / "docs/areas/a/adr/001-x.md").read_text()
            for target in re.findall(r"\]\(([^)]+)\)", text):
                self.assertTrue((ROOT / "docs/areas/a/adr" / target).exists())
''')

LINK_TARGETS_JOINPATH = _fixture(r'''
    class T(unittest.TestCase):
        def test_x(self):
            directory = ROOT / "docs/areas/a/adr"
            text = (directory / "001-x.md").read_text()
            for target in re.findall(r"\]\(([^)]+)\)", text):
                self.assertTrue(directory.joinpath(target).exists())
''')

LINK_MEMBERSHIP = _fixture(r'''
    class T(unittest.TestCase):
        def test_x(self):
            text = (ROOT / "docs/areas/a/adr/001-x.md").read_text()
            for target in re.findall(r"\]\(([^)]+)\)", text):
                self.assertIn(target, KNOWN)
            self.assertTrue(set(re.findall(r"ADR-[a-z]+-\d+", text)) <= KNOWN)
''')

FILE_NAME = _fixture(r'''
    class T(unittest.TestCase):
        def test_x(self):
            found = sorted((ROOT / "docs/areas/a/adr").glob("059-*.md"))
            self.assertEqual(len(found), 1, found)
            self.assertEqual(found[0].name, "059-x.md")
''')

PATH_AS_DATA = _fixture(r'''
    def record(**fields):
        return fields


    def verdict(entry):
        return {"hits": ["risk_path"]}


    class T(unittest.TestCase):
        def test_x(self):
            self.assertEqual(self.verdict(record(paths=["docs/areas/a/adr/001-x.md"]))["hits"], ["risk_path"])
''')

PATH_AS_NEEDLE = _fixture(r'''
    class T(unittest.TestCase):
        def test_x(self):
            self.assertIn("docs/areas/a/adr/001-x.md", (ROOT / "docs/archive/x.md").read_text())
''')

CONTEXT_PHRASE = _fixture(r'''
    class T(unittest.TestCase):
        def test_x(self):
            self.assertIn("**Term**:", (ROOT / "docs/areas/a/CONTEXT.md").read_text())
''')

REBOUND = _fixture(r'''
    class T(unittest.TestCase):
        def test_x(self):
            text = (ROOT / "docs/areas/a/adr/001-x.md").read_text()
            self.assertIn("one", text)
            text = (ROOT / "docs/areas/a/CONTEXT.md").read_text()
            self.assertIn("two", text)
''')

COMPREHENSION_REUSE = _fixture(r'''
    class T(unittest.TestCase):
        def test_x(self):
            lines = (ROOT / "docs/areas/a/adr/001-x.md").read_text().splitlines()
            status = next(row for row in lines if row.startswith("- **Status:**"))
            self.assertEqual(status, "- **Status:** accepted")
            context = (ROOT / "docs/areas/a/CONTEXT.md").read_text().splitlines()
            entry = next(row for row in context if row.startswith("**Term**:"))
            self.assertIn("ADR-a-001", entry)
''')

LOOP_CONVERGENCE = _fixture(r'''
    class T(unittest.TestCase):
        def test_x(self):
            prev = ""
            for p in sorted((ROOT / "docs/areas/a/adr").glob("*.md")):
                current = p.read_text()
                if prev:
                    self.assertNotEqual(prev, current)
                prev = current
''')

MATCH_RESULT = _fixture(r'''
    class T(unittest.TestCase):
        def test_x(self):
            text = (ROOT / "docs/areas/a/adr/001-x.md").read_text()
            found = "words" in text
            self.assertTrue(found)
            decided = re.search(r"(?m)^- \*\*Decided in:\*\*", text)
            self.assertIsNotNone(decided)
''')

KEPT_FIXTURE = _fixture(r'''
    class K(unittest.TestCase):
        def test_token_wording(self):
            text = (ROOT / "docs/areas/a/adr/001-x.md").read_text()
            self.assertIn("words", text)

        def test_plain_wording(self):
            text = (ROOT / "docs/areas/a/adr/001-x.md").read_text()
            self.assertIn("words", text)

        def test_token_no_wording(self):
            text = (ROOT / "docs/areas/a/adr/001-x.md").read_text()
            self.assertEqual(len(text.split()), 3)

        def test_leak_check_wording(self):
            text = (ROOT / "docs/areas/a/adr/001-x.md").read_text()
            self.assertIn("words", text)
            self.assertEqual(logins_in(text), [])
''')

COUNT_PHRASE = _fixture(r'''
    class T(unittest.TestCase):
        def test_x(self):
            text = (ROOT / "docs/areas/a/adr/001-x.md").read_text()
            self.assertEqual(text.count("words"), 1)
''')

COMPREHENSION_SHADOW = _fixture(r'''
    class T(unittest.TestCase):
        def test_x(self):
            text = (ROOT / "docs/areas/a/adr/001-x.md").read_text()
            names = [text for text in ("a", "b")]
            self.assertIn("words", text)
''')

ADJACENT_LITERALS = _fixture(r'''
    class T(unittest.TestCase):
        def test_x(self):
            text = Path("docs/" "areas/a/adr/001-x.md").read_text()
            self.assertIn("words", text)
''')

FSTRING_PATH = _fixture(r'''
    class T(unittest.TestCase):
        def test_x(self):
            a = "a"
            text = Path(f"docs/areas/{a}/adr/001-x.md").read_text()
            self.assertIn("words", text)
''')

SEGMENTED_PATH = _fixture(r'''
    class T(unittest.TestCase):
        def test_x(self):
            text = (ROOT / "docs" / "areas" / "a" / "adr" / "001-x.md").read_text()
            self.assertIn("words", text)
''')

SEGMENTED_PATH_WITH_VARIABLE = _fixture(r'''
    class T(unittest.TestCase):
        def test_x(self):
            area = "a"
            text = (ROOT / "docs" / "areas" / area / "adr" / "001-x.md").read_text()
            self.assertIn("words", text)
''')

SEGMENTED_CONTEXT = _fixture(r'''
    class T(unittest.TestCase):
        def test_x(self):
            text = (ROOT / "docs" / "areas" / "a" / "CONTEXT.md").read_text()
            self.assertIn("words", text)
''')

INSTANCE_ATTRIBUTE = _fixture(r'''
    class T(unittest.TestCase):
        def test_x(self):
            self.text = (ROOT / "docs/areas/a/adr/001-x.md").read_text()
            self.assertIn("words", self.text)
''')

INSTANCE_ATTRIBUTE_REBOUND = _fixture(r'''
    class T(unittest.TestCase):
        def test_x(self):
            self.text = (ROOT / "docs/areas/a/adr/001-x.md").read_text()
            self.text = (ROOT / "docs/areas/a/CONTEXT.md").read_text()
            self.assertIn("words", self.text)
''')

INSTANCE_ATTRIBUTE_OWNER_REBOUND = _fixture(r'''
    class T(unittest.TestCase):
        def test_x(self):
            self.text = (ROOT / "docs/areas/a/adr/001-x.md").read_text()
            self = other
            self.assertIn("words", self.text)
''')

DIAGNOSTIC_MESSAGE = _fixture(r'''
    class T(unittest.TestCase):
        def test_x(self):
            text = (ROOT / "docs/areas/a/adr/001-x.md").read_text()
            self.assertGreater(len(text), 0, "empty record")
            self.assertTrue(text, "words")
            self.assertEqual(len(text.split()), 3, msg="words")
''')

KEYWORD_OPERANDS = _fixture(r'''
    class T(unittest.TestCase):
        def test_x(self):
            text = (ROOT / "docs/areas/a/adr/001-x.md").read_text()
            self.assertIn(member="words", container=text)
            self.assertIn("more words", text, msg="diagnostic")
''')

SETUP_ATTRIBUTE = _fixture(r'''
    class T(unittest.TestCase):
        def setUp(self):
            self.text = (ROOT / "docs/areas/a/adr/001-x.md").read_text()

        def test_x(self):
            self.assertIn("words", self.text)
''')

SETUP_CLASS_ATTRIBUTE = _fixture(r'''
    class T(unittest.TestCase):
        @classmethod
        def setUpClass(cls):
            cls.text = (ROOT / "docs/areas/a/adr/001-x.md").read_text()

        def test_x(self):
            self.assertIn("words", self.text)
''')

SETUP_OTHER_TEXT = _fixture(r'''
    class T(unittest.TestCase):
        def setUp(self):
            self.text = (ROOT / "docs/areas/a/CONTEXT.md").read_text()

        def test_x(self):
            self.assertIn("words", self.text)
''')

SETUP_ATTRIBUTE_REBOUND = _fixture(r'''
    class T(unittest.TestCase):
        def setUp(self):
            self.text = (ROOT / "docs/areas/a/adr/001-x.md").read_text()

        def test_x(self):
            self.text = "other"
            self.assertIn("words", self.text)
''')

PATTERN_FINDALL = _fixture(r'''
    LOGIN_LIKE = re.compile(r"[\w.+-]+@[\w-]+")


    class T(unittest.TestCase):
        def test_x(self):
            text = (ROOT / "docs/areas/a/adr/001-x.md").read_text()
            self.assertEqual(LOGIN_LIKE.findall(text), [])
''')

LINK_FILTER_COMPREHENSION = _fixture(r'''
    class T(unittest.TestCase):
        def test_x(self):
            directory = ROOT / "docs/areas/a/adr"
            text = (directory / "001-x.md").read_text()
            missing = [
                t for t in re.findall(r"\]\(([^)]+)\)", text)
                if not t.startswith("http") and not (directory / t).exists()
            ]
            self.assertEqual(missing, [])
''')

COMPREHENSION_FILTER = _fixture(r'''
    class T(unittest.TestCase):
        def test_x(self):
            adrs = [
                path for path in (ROOT / "docs/areas/release/adr").glob("*.md")
                if "cannot prove the bundle" in " ".join(path.read_text().split())
            ]
            self.assertEqual(len(adrs), 1)
''')

SAVED_COUNT = _fixture(r'''
    class T(unittest.TestCase):
        def test_x(self):
            text = (ROOT / "docs/areas/a/adr/001-x.md").read_text()
            hits = text.count("words")
            self.assertGreater(hits, 0)
            where = text.find("words")
            self.assertNotEqual(where, -1)
            size = len(text)
            self.assertGreater(size, 0)
''')

SAVED_LITERALS = _fixture(r'''
    PAT = re.compile("Decided in")
    SHAPE_PAT = re.compile(r"(?m)^- \*\*Decided in:\*\* [\w ]+$")


    class T(unittest.TestCase):
        def test_literal_pattern(self):
            text = (ROOT / "docs/areas/a/adr/001-x.md").read_text()
            self.assertTrue(PAT.search(text))

        def test_shape_pattern(self):
            text = (ROOT / "docs/areas/a/adr/001-x.md").read_text()
            self.assertEqual(len(SHAPE_PAT.findall(text)), 1)
''')

SAVED_CALL_RESULTS = _fixture(r'''
    class T(unittest.TestCase):
        def test_findall(self):
            text = (ROOT / "docs/areas/a/adr/001-x.md").read_text()
            hits = re.findall("words", text)
            self.assertTrue(hits)

        def test_split(self):
            text = (ROOT / "docs/areas/a/adr/001-x.md").read_text()
            parts = text.split("words")
            self.assertEqual(len(parts), 2)

        def test_replace(self):
            text = (ROOT / "docs/areas/a/adr/001-x.md").read_text()
            rest = text.replace("words", "")
            self.assertTrue(rest)

        def test_other_text(self):
            text = (ROOT / "docs/areas/a/adr/001-x.md").read_text()
            rows = text.splitlines()
            self.assertEqual(len(rows), 3)
''')

DOCS_ROOT_NAMES = _fixture(r'''
    DOCS = ROOT / "docs"
    DOCS_S = "docs"


    class T(unittest.TestCase):
        def test_glob(self):
            for p in DOCS.glob("areas/*/adr/*.md"):
                self.assertIn("words", p.read_text())

        def test_segments(self):
            text = (DOCS / "areas" / "a" / "adr" / "x.md").read_text()
            self.assertIn("words", text)

        def test_string_name(self):
            text = Path(DOCS_S + "/areas/a/adr/x.md").read_text()
            self.assertIn("words", text)

        def test_attribute(self):
            self.docs = ROOT / "docs"
            text = (self.docs / "areas" / "a" / "adr" / "x.md").read_text()
            self.assertIn("words", text)

        def test_context(self):
            text = (DOCS / "areas" / "a" / "CONTEXT.md").read_text()
            self.assertIn("words", text)

        def test_archive_glob(self):
            for p in DOCS.glob("archive/*.md"):
                self.assertIn("words", p.read_text())

        def test_rebound(self):
            docs = DOCS
            docs = ROOT / "other"
            text = (docs / "areas" / "a" / "adr" / "x.md").read_text()
            self.assertIn("words", text)
''')

INHERITED_FIXTURES = _fixture(r'''
    class Base(unittest.TestCase):
        def setUp(self):
            self.text = (ROOT / "docs/areas/a/adr/001-x.md").read_text()


    class Middle(Base):
        pass


    class T(Middle):
        def test_x(self):
            self.assertIn("words", self.text)


    class ContextBase(unittest.TestCase):
        def setUp(self):
            self.text = (ROOT / "docs/areas/a/CONTEXT.md").read_text()


    class U(ContextBase):
        def test_x(self):
            self.assertIn("words", self.text)
''')

HELPER_FIXTURES = _fixture(r'''
    class T(unittest.TestCase):
        def load(self):
            self.text = (ROOT / "docs/areas/a/adr/001-x.md").read_text()

        def setUp(self):
            self.load()

        def test_x(self):
            self.assertIn("words", self.text)


    class Cls(unittest.TestCase):
        @classmethod
        def read(cls):
            cls.text = (ROOT / "docs/areas/a/adr/001-x.md").read_text()

        @classmethod
        def setUpClass(cls):
            cls.read()

        def test_x(self):
            self.assertIn("words", self.text)


    class Called(unittest.TestCase):
        def load(self):
            self.text = (ROOT / "docs/areas/a/adr/001-x.md").read_text()

        def test_x(self):
            self.load()
            self.assertIn("words", self.text)


    class Other(unittest.TestCase):
        def load(self):
            self.text = (ROOT / "docs/areas/a/adr/001-x.md").read_text()

        def setUp(self):
            self.text = "other"
            other.load()

        def test_x(self):
            self.assertIn("words", self.text)


    class Loop(unittest.TestCase):
        def load(self):
            self.load()
            self.text = (ROOT / "docs/areas/a/adr/001-x.md").read_text()

        def setUp(self):
            self.load()

        def test_x(self):
            self.assertIn("words", self.text)
''')


def _read_of(expression):
    return (
        "class T(unittest.TestCase):\n    def test_x(self):\n        a = 'a'\n"
        f"        text = {expression}\n        self.assertIn('words', text)\n"
    )


def _glob_of(expression):
    return (
        "class T(unittest.TestCase):\n    def test_x(self):\n"
        f"        for p in {expression}:\n            self.assertIn('words', p.read_text())\n"
    )


RECORD_READS = {
    "a + concatenation": 'Path("docs/areas/" + a + "/adr/001-x.md").read_text()',
    "a + concatenation in a chain": '(ROOT / ("docs/areas/" + a) / "adr").joinpath("001-x.md").read_text()',
    "Path with segment arguments": 'Path("docs", "areas", "a", "adr", "001-x.md").read_text()',
    "joinpath with segment arguments": 'ROOT.joinpath("docs", "areas", "a", "adr", "001-x.md").read_text()',
    "joinpath on an areas root": '(ROOT / "docs/areas").joinpath("a", "adr", "001-x.md").read_text()',
    "Path of an areas root": 'Path(ROOT / "docs/areas", a, "adr", "001-x.md").read_text()',
    "os.path.join": 'open(os.path.join("docs", "areas", "a", "adr", "001-x.md")).read()',
    "os.path.join of a variable root": 'open(os.path.join(ROOT, "docs/areas", a, "adr", "001-x.md")).read()',
    "a separator join": 'Path("/".join(["docs", "areas", a, "adr", "001-x.md"])).read_text()',
    "a joined areas root": 'Path("/".join(("docs", "areas"))).joinpath(a, "adr", "001-x.md").read_text()',
}
RECORD_GLOBS = {
    "glob over the areas root": '(ROOT / "docs/areas").glob("*/adr/*.md")',
    "rglob over the areas root": '(ROOT / "docs" / "areas").rglob("adr/*.md")',
    "glob over a segmented areas root": 'Path("docs", "areas").glob("*/adr/*.md")',
    "glob of the root with a full pattern": 'ROOT.glob("docs/areas/*/adr/*.md")',
    "glob of the root with a + pattern": 'ROOT.glob("docs/areas/" + "*/adr/*.md")',
    "glob of docs with an areas pattern": '(ROOT / "docs").glob("areas/*/adr/*.md")',
    "rglob of docs with an areas pattern": '(ROOT / "docs").rglob("areas/**/adr/*.md")',
    "glob of an area with an adr pattern": '(ROOT / "docs/areas/a").glob("adr/*.md")',
    "glob of a literal receiver": 'Path("docs").glob("areas/*/adr/*.md")',
    "glob of a variable receiver": 'ROOT.joinpath("docs").glob("areas/" + "*/adr/*.md")',
}
NOT_RECORD_READS = {
    "a CONTEXT.md by + concatenation": 'Path("docs/areas/" + a + "/CONTEXT.md").read_text()',
    "a CONTEXT.md by segments": 'Path("docs", "areas", "a", "CONTEXT.md").read_text()',
    "a CONTEXT.md by os.path.join": 'open(os.path.join("docs", "areas", a, "CONTEXT.md")).read()',
    "an archive by joinpath": 'ROOT.joinpath("docs", "archive", "x.md").read_text()',
    "a sum": "str(1 + 2)",
}
NOT_RECORD_GLOBS = {
    "a CONTEXT.md glob over the areas root": '(ROOT / "docs/areas").glob("*/CONTEXT.md")',
    "a glob of the tests": 'ROOT.glob("tests/*.py")',
    "a CONTEXT.md glob of docs": '(ROOT / "docs").glob("areas/*/CONTEXT.md")',
}
AREAS_HEAD = "AREAS = ROOT / 'docs/areas'\nAREAS_S = 'docs/areas'\n"
AREAS_READS = {
    "an f-string over an areas path name": 'open(f"{AREAS}/{a}/adr/001-x.md").read()',
    "an f-string over an areas string name": 'Path(f"{AREAS_S}/{a}/adr/001-x.md").read_text()',
    "a + concatenation over an areas name": 'Path(AREAS_S + "/" + a + "/adr/001-x.md").read_text()',
    "a format over an areas name": 'Path("{}/{}/adr/001-x.md".format(AREAS_S, a)).read_text()',
    "a % format over an areas name": 'Path("%s/%s/adr/001-x.md" % (AREAS_S, a)).read_text()',
}
NOT_AREAS_READS = {
    "an f-string naming a CONTEXT.md": 'Path(f"{AREAS_S}/{a}/CONTEXT.md").read_text()',
    "an f-string with no areas name": 'Path(f"{a}/adr/001-x.md").read_text()',
    "a + concatenation naming a CONTEXT.md": 'Path(AREAS_S + "/" + a + "/CONTEXT.md").read_text()',
}

TEST_ID = "tests/test_f.py::T.test_x"

JUSTFILE_HEAD = (
    "agent-workflow-tests *args:\n"
    '  PYTHONPATH="{{agent_tools_path}}" python3 -m agent_tools.delivery.suite_runner {{args}} \\\n'
)
SHELL_MEMBER = "#!/usr/bin/env bash\ngrep -q 'words' docs/areas/a/adr/001-x.md\n"


def write_tree(root, files):
    for name, text in files.items():
        target = Path(root) / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")


class WordingScanTest(unittest.TestCase):
    def found(self, source):
        return wording_findings("tests/test_f.py", source)

    def test_a_phrase_asserted_in_a_read_record_is_found(self):
        self.assertEqual(self.found(READ_THEN_ASSERT), [(TEST_ID, 4)])

    def test_a_needle_bound_by_a_loop_over_literals_is_a_phrase(self):
        self.assertEqual(self.found(LOOP_NEEDLE), [(TEST_ID, 8)])

    def test_a_record_path_spelled_as_adjacent_literals_is_scanned(self):
        self.assertEqual(self.found(ADJACENT_LITERALS), [(TEST_ID, 4)])

    def test_a_record_path_spelled_as_an_f_string_or_segments_is_scanned(self):
        with self.subTest("an f-string"):
            self.assertEqual(self.found(FSTRING_PATH), [(TEST_ID, 5)])
        with self.subTest("segments of one chain"):
            self.assertEqual(self.found(SEGMENTED_PATH), [(TEST_ID, 4)])
        with self.subTest("segments with a variable among them"):
            self.assertEqual(self.found(SEGMENTED_PATH_WITH_VARIABLE), [(TEST_ID, 5)])
        with self.subTest("segments naming a CONTEXT.md, not a record"):
            self.assertEqual(self.found(SEGMENTED_CONTEXT), [])

    def test_a_record_path_built_by_concatenation_arguments_or_a_glob_is_scanned(self):
        for label, expression in RECORD_READS.items():
            with self.subTest(label):
                self.assertEqual(self.found(_read_of(expression)), [(TEST_ID, 5)])
        for label, expression in RECORD_GLOBS.items():
            with self.subTest(label):
                self.assertEqual(self.found(_glob_of(expression)), [(TEST_ID, 4)])
        for label, expression in NOT_RECORD_READS.items():
            with self.subTest(label):
                self.assertEqual(self.found(_read_of(expression)), [])
        for label, expression in NOT_RECORD_GLOBS.items():
            with self.subTest(label):
                self.assertEqual(self.found(_glob_of(expression)), [])

    def test_a_record_path_built_from_an_areas_name_is_scanned(self):
        for label, expression in AREAS_READS.items():
            with self.subTest(label):
                self.assertEqual(self.found(AREAS_HEAD + _read_of(expression)), [(TEST_ID, 7)])
        for label, expression in NOT_AREAS_READS.items():
            with self.subTest(label):
                self.assertEqual(self.found(AREAS_HEAD + _read_of(expression)), [])

    def test_record_text_read_in_a_fixture_method_is_found_in_the_tests(self):
        with self.subTest("setUp"):
            self.assertEqual(self.found(SETUP_ATTRIBUTE), [(TEST_ID, 6)])
        with self.subTest("setUpClass"):
            self.assertEqual(self.found(SETUP_CLASS_ATTRIBUTE), [(TEST_ID, 7)])
        with self.subTest("a fixture reading a CONTEXT.md"):
            self.assertEqual(self.found(SETUP_OTHER_TEXT), [])
        with self.subTest("the attribute rebound in the test"):
            self.assertEqual(self.found(SETUP_ATTRIBUTE_REBOUND), [])

    def test_a_saved_shape_pattern_applied_to_record_text_is_no_phrase(self):
        self.assertEqual(self.found(PATTERN_FINDALL), [])

    def test_a_saved_pattern_counts_only_through_a_matching_call(self):
        self.assertEqual(
            self.found(SAVED_LITERALS),
            [("tests/test_f.py::T.test_literal_pattern", 8)],
        )

    def test_a_saved_result_of_a_call_that_neither_compares_nor_probes_is_no_match(self):
        self.assertEqual(self.found(SAVED_CALL_RESULTS), [])

    def test_a_comprehension_filtered_on_a_phrase_is_a_match_result(self):
        self.assertEqual(self.found(COMPREHENSION_FILTER), [(TEST_ID, 7)])

    def test_a_long_path_chain_is_read_in_linear_time(self):
        chain = ast.parse("ROOT" + "".join(f' / "s{i}"' for i in range(18)), mode="eval").body
        calls = []
        real = _static_text

        def counting(node, env=None):
            calls.append(node)
            return real(node, env)

        with mock.patch.dict(globals(), {"_static_text": counting}):
            text = real(chain)
        self.assertEqual(text, "_/" + "/".join(f"s{i}" for i in range(18)))
        self.assertLess(len(calls), 100)

    def test_a_docs_root_held_in_a_name_names_records(self):
        self.assertEqual(
            self.found(DOCS_ROOT_NAMES),
            [
                ("tests/test_f.py::T.test_attribute", 21),
                ("tests/test_f.py::T.test_glob", 8),
                ("tests/test_f.py::T.test_segments", 12),
                ("tests/test_f.py::T.test_string_name", 16),
            ],
        )

    def test_record_text_set_by_an_inherited_or_called_fixture_is_found(self):
        with self.subTest("a base class setUp"):
            self.assertEqual(self.found(INHERITED_FIXTURES), [("tests/test_f.py::T.test_x", 12)])
        with self.subTest("a helper called from a fixture or a test"):
            self.assertEqual(
                [(test.split("::")[1], line) for test, line in self.found(HELPER_FIXTURES)],
                [("Called.test_x", 31), ("Cls.test_x", 22), ("Loop.test_x", 55), ("T.test_x", 9)],
            )

    def test_a_saved_phrase_count_or_position_is_found(self):
        self.assertEqual(self.found(SAVED_COUNT), [(TEST_ID, 5), (TEST_ID, 7)])

    def test_record_text_kept_on_an_instance_attribute_is_found(self):
        with self.subTest("read then asserted through the attribute"):
            self.assertEqual(self.found(INSTANCE_ATTRIBUTE), [(TEST_ID, 4)])
        with self.subTest("the attribute rebound to other text"):
            self.assertEqual(self.found(INSTANCE_ATTRIBUTE_REBOUND), [])
        with self.subTest("the owner name rebound"):
            self.assertEqual(self.found(INSTANCE_ATTRIBUTE_OWNER_REBOUND), [])

    def test_a_diagnostic_message_is_no_operand_and_a_keyword_operand_is(self):
        with self.subTest("a message beside record text"):
            self.assertEqual(self.found(DIAGNOSTIC_MESSAGE), [])
        with self.subTest("keyword operands"):
            self.assertEqual(self.found(KEYWORD_OPERANDS), [(TEST_ID, 4), (TEST_ID, 5)])

    def test_a_title_checked_with_startswith_is_found(self):
        with self.subTest("a match call on the text"):
            self.assertEqual(self.found(STARTSWITH_TITLE), [(TEST_ID, 4)])
        with self.subTest("a call counting a phrase in the text"):
            self.assertEqual(self.found(COUNT_PHRASE), [(TEST_ID, 4)])

    def test_a_module_level_record_directory_taints_its_uses(self):
        self.assertEqual(self.found(MODULE_DIRECTORY), [(TEST_ID, 7)])

    def test_an_areas_directory_joined_with_adr_names_records(self):
        self.assertEqual(self.found(AREAS_JOIN), [(TEST_ID, 5)])

    def test_a_nested_reader_makes_record_text(self):
        self.assertEqual(self.found(NESTED_READER), [(TEST_ID, 6)])

    def test_a_record_read_through_open_is_text(self):
        self.assertEqual(self.found(WITH_OPEN), [(TEST_ID, 5)])

    def test_structure_checks_are_not_findings(self):
        cases = {
            "glob count": GLOB_COUNT,
            "number uniqueness": NUMBER_UNIQUENESS,
            "link targets": LINK_TARGETS,
            "link targets by joinpath": LINK_TARGETS_JOINPATH,
            "link membership": LINK_MEMBERSHIP,
            "link filter comprehension": LINK_FILTER_COMPREHENSION,
            "file name": FILE_NAME,
        }
        for label, source in cases.items():
            with self.subTest(label):
                self.assertEqual(self.found(source), [])

    def test_a_record_path_as_data_is_not_a_finding(self):
        cases = {
            "path inside a record() call": PATH_AS_DATA,
            "needle in a non-record document": PATH_AS_NEEDLE,
            "phrase on CONTEXT.md text": CONTEXT_PHRASE,
        }
        for label, source in cases.items():
            with self.subTest(label):
                self.assertEqual(self.found(source), [])

    def test_the_scan_reads_the_recipe_members_and_globs_but_never_the_guard_files(self):
        tree = {
            "justfile": JUSTFILE_HEAD
            + "    tests/test_guard_policy.py \\\n"
            + "    extra/test_listed.py \\\n"
            + "    extra/test-listed.sh\n",
            "tests/test_guard_policy.py": READ_THEN_ASSERT,
            "tests/test_claude_permission_guard.py": READ_THEN_ASSERT,
            "tests/test_other.py": READ_THEN_ASSERT,
            "home/common/agent-skills/tests/test_more.py": READ_THEN_ASSERT,
            "extra/test_listed.py": READ_THEN_ASSERT,
            "extra/test-listed.sh": SHELL_MEMBER,
        }
        with self.subTest("members, globs and the guard files"):
            with tempfile.TemporaryDirectory() as tmp:
                write_tree(tmp, tree)
                root = Path(tmp)
                self.assertEqual(
                    [path for path, _ in suite_sources(root)],
                    [
                        "extra/test-listed.sh",
                        "extra/test_listed.py",
                        "home/common/agent-skills/tests/test_more.py",
                        "tests/test_other.py",
                    ],
                )
                self.assertEqual(
                    suite_findings(root),
                    [
                        ("extra/test-listed.sh", 2),
                        ("extra/test_listed.py::T.test_x", 4),
                        ("home/common/agent-skills/tests/test_more.py::T.test_x", 4),
                        ("tests/test_other.py::T.test_x", 4),
                    ],
                )
        with self.subTest("a member of another kind"):
            with tempfile.TemporaryDirectory() as tmp:
                odd = dict(tree)
                odd["justfile"] = (
                    JUSTFILE_HEAD
                    + "    tests/test_guard_policy.py \\\n"
                    + "    extra/test_listed.py \\\n"
                    + "    extra/test-listed.sh \\\n"
                    + "    extra/test_odd.rb\n"
                )
                odd["extra/test_odd.rb"] = "puts 1\n"
                write_tree(tmp, odd)
                with self.assertRaisesRegex(ValueError, "extra/test_odd.rb"):
                    suite_findings(Path(tmp))
        with self.subTest("a justfile with no recipe"):
            with tempfile.TemporaryDirectory() as tmp:
                write_tree(tmp, {"justfile": "build:\n  true\n"})
                with self.assertRaises(ValueError):
                    suite_sources(Path(tmp))

    def test_a_source_that_does_not_parse_fails_the_scan(self):
        with self.assertRaises(SyntaxError):
            wording_findings("tests/test_bad.py", "def (:\n")

    def test_a_name_rebound_to_other_text_is_no_longer_record_text(self):
        self.assertEqual(self.found(REBOUND), [(TEST_ID, 4)])

    def test_a_comprehension_name_does_not_leak_into_the_next(self):
        with self.subTest("two comprehensions"):
            self.assertEqual(self.found(COMPREHENSION_REUSE), [(TEST_ID, 5)])
        with self.subTest("a comprehension name shadowing an outer name"):
            self.assertEqual(self.found(COMPREHENSION_SHADOW), [(TEST_ID, 5)])

    def test_record_text_dominates_a_phrase_across_a_loop(self):
        self.assertEqual(self.found(LOOP_CONVERGENCE), [])

    def test_a_match_result_asserted_alone_is_found(self):
        self.assertEqual(self.found(MATCH_RESULT), [(TEST_ID, 5), (TEST_ID, 7)])

    def test_the_kept_list_checks_each_id(self):
        sources = [("tests/test_guard_policy.py", KEPT_FIXTURE), ("tests/test_k.py", KEPT_FIXTURE)]
        findings = wording_findings("tests/test_k.py", KEPT_FIXTURE)
        cases = {
            "tests/test_k.py::K.test_token_wording": [],
            "tests/test_k.py::K.test_leak_check_wording": [],
            "tests/test_k.py::K.test_tokn_wording": ["missing: tests/test_k.py::K.test_tokn_wording"],
            "tests/test_k.py::K.test_plain_wording": [
                "no credential word: tests/test_k.py::K.test_plain_wording"
            ],
            "tests/test_k.py::K.test_token_no_wording": [
                "not flagged: tests/test_k.py::K.test_token_no_wording"
            ],
            "tests/test_guard_policy.py::K.test_token_wording": [
                "guard file: tests/test_guard_policy.py::K.test_token_wording"
            ],
        }
        for kept_id, expected in cases.items():
            with self.subTest(kept_id):
                self.assertEqual(kept_list_problems({kept_id}, sources, findings), expected)


class SuiteWordingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sources = suite_sources(REPO_ROOT)
        cls.findings = suite_findings(REPO_ROOT)

    def test_every_kept_credential_test_still_pins_wording_and_names_a_credential(self):
        self.assertEqual(kept_list_problems(KEPT_CREDENTIAL_TESTS, self.sources, self.findings), [])
        self.assertTrue(KEPT_AT_START.isdisjoint(KEPT_FROM_MAIN))

    def test_no_suite_test_pins_a_decision_records_wording(self):
        left = sorted(
            {f"{test}:{line}" for test, line in self.findings if test not in KEPT_CREDENTIAL_TESTS}
        )
        self.assertEqual(left, [], "\n".join(left))


if __name__ == "__main__":
    unittest.main()
