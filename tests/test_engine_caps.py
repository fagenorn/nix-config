"""Contract tests for the engine size caps (`agent_tools.delivery.engine_caps`, #1513).

Each cap is tested at its limit and one past it against a temporary package or
procedures directory, then once against the shipped tree.

Run: just agent-workflow-tests
"""

from __future__ import annotations

import argparse
import ast
import importlib.util
import inspect
import io
import itertools
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Callable
from unittest import mock

from agent_tools.delivery import engine, engine_caps, engine_graders
from agent_tools.delivery.engine_caps import Breach
from agent_tools.delivery.engine_graders import GRADERS, Grader
from tests.guard_policy_world import install_platform_manifest_in_environ

setUpModule = install_platform_manifest_in_environ

REPO_ROOT = Path(__file__).resolve().parents[1]
DELIVERY = REPO_ROOT / "python/agent_tools/delivery"
PROCEDURES = DELIVERY / "procedures"

_unique = itertools.count()


def pad(n: int) -> str:
    return "".join("# pad\n" if i % 2 == 0 else "\n" for i in range(n))


def temp_dir() -> Path:
    directory = Path(tempfile.mkdtemp(prefix="engine-caps-"))
    unittest.addModuleCleanup(shutil.rmtree, directory, ignore_errors=True)
    return directory


def package(files: dict[str, str]) -> Path:
    directory = temp_dir()
    for name, text in files.items():
        (directory / name).write_text(text, encoding="utf-8")
    return directory


def procedures_copy() -> Path:
    target = temp_dir() / "procedures"
    shutil.copytree(PROCEDURES, target)
    return target


def chain(n: int) -> dict:
    header = json.loads((PROCEDURES / "toy-child.json").read_text(encoding="utf-8"))
    steps = []
    for i in range(1, n + 1):
        nxt = f"s{i + 1}" if i < n else "done"
        steps.append(
            {
                "id": f"s{i}",
                "stage": "setup",
                "kind": "command",
                "command": "diff-scope",
                "holds": "run",
                "in": ["run.range"],
                "on": {"ok": nxt, "failed": nxt, "refused": nxt},
            }
        )
    return {
        "format": header["format"],
        "inputs": ["holder", "issue", "range", "repo"],
        "stops": {"halt": {"need": "retry", "reenter": "s1"}},
        "steps": steps,
    }


def write_json(directory: Path, name: str, doc: dict) -> None:
    (directory / f"{name}.json").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")


def toy_with(extra: int, directory: Path) -> None:
    doc = json.loads((directory / "toy.json").read_text(encoding="utf-8"))
    scope = next(item for item in doc["steps"] if item["id"] == "scope")
    for i in range(1, extra + 1):
        copy = dict(scope, id=f"pad-{i}", on={"ok": "done", "failed": "done", "refused": "done"})
        doc["steps"].append(copy)
    write_json(directory, "toy", doc)


def _short(results):
    return "ok"


def long_grader(lines: int) -> Callable:
    text = (
        "def g(results):\n"
        + "    # pad\n" * (lines - 21)
        + "\n"
        + "    # pad\n" * 18
        + '    return "ok"\n'
    )
    path = temp_dir() / "long_grader.py"
    path.write_text(text, encoding="utf-8")
    name = f"long_grader_{next(_unique)}"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.g


def base_package(core: int = 10, engine: int = 10) -> Path:
    return package({"engine.py": pad(engine), "engine_core.py": pad(core)})


def measure(pkg: Path, procedures: Path | None = None, graders=GRADERS) -> tuple[Breach, ...]:
    return engine_caps.breaches(pkg, procedures or procedures_copy(), graders)


class BoundaryTest(unittest.TestCase):
    def test_a_core_of_600_lines_passes_and_601_is_refused(self):
        self.assertEqual(measure(base_package(core=600)), ())
        self.assertEqual(
            measure(base_package(core=601)), (Breach("core", 601, 600, "lines"),)
        )

    def test_a_last_line_without_a_newline_counts(self):
        pkg = package({"engine.py": pad(10), "engine_core.py": pad(600) + "x = 1"})
        self.assertEqual(measure(pkg), (Breach("core", 601, 600, "lines"),))

    def test_cr_lf_and_crlf_each_separate_lines_at_the_boundaries(self):
        for name, separator in (("CR", b"\r"), ("LF", b"\n"), ("CRLF", b"\r\n")):
            for trailing in (True, False):
                with self.subTest(separator=name, trailing=trailing):
                    for count, expected in ((600, ()), (601, (Breach("core", 601, 600, "lines"),))):
                        body = separator.join(b"x = 1" for _ in range(count)) + (separator if trailing else b"")
                        pkg = base_package()
                        (pkg / "engine_core.py").write_bytes(body)
                        self.assertEqual(measure(pkg), expected)
                    pkg = base_package(core=10, engine=0)
                    (pkg / "engine.py").write_bytes(separator.join(b"x = 1" for _ in range(6990)) + separator)
                    self.assertEqual(measure(pkg), ())
                    (pkg / "engine.py").write_bytes(separator.join(b"x = 1" for _ in range(6991)) + separator)
                    self.assertEqual(measure(pkg), (Breach("engine package", 7001, 7000, "lines"),))

    def test_a_package_of_7000_lines_passes_and_7001_is_refused(self):
        self.assertEqual(measure(base_package(core=600, engine=6400)), ())
        self.assertEqual(
            measure(base_package(core=600, engine=6401)),
            (Breach("engine package", 7001, 7000, "lines"),),
        )

    def test_the_package_is_the_engine_modules_and_what_they_import(self):
        files = {
            "engine.py": "from agent_tools.delivery import helper\n" + pad(9),
            "engine_core.py": "from agent_tools.delivery.other import x\n" + pad(9),
            "engine_x.py": "from . import rel\n" + pad(9),
            "helper.py": "import agent_tools.delivery.deep\n" + pad(9),
            "other.py": pad(10),
            "deep.py": pad(10),
            "rel.py": pad(10),
            "unrelated.py": pad(5000),
            "__init__.py": pad(5000),
        }
        pkg = package(files)
        self.assertEqual(
            [p.name for p in engine_caps.engine_modules(pkg)],
            ["deep.py", "engine.py", "engine_core.py", "engine_x.py", "helper.py", "other.py", "rel.py"],
        )
        self.assertEqual(measure(pkg), ())
        (pkg / "helper.py").write_text("import agent_tools.delivery.deep\n" + pad(6999), encoding="utf-8")
        self.assertEqual(measure(pkg), (Breach("engine package", 7060, 7000, "lines"),))

    def test_a_procedure_of_40_steps_passes_and_41_is_refused(self):
        copy = procedures_copy()
        write_json(copy, "chain", chain(40))
        self.assertEqual(measure(base_package(), copy), ())
        write_json(copy, "chain", chain(41))
        self.assertEqual(
            measure(base_package(), copy), (Breach("procedure chain", 41, 40, "steps"),)
        )

    def test_group_members_count_as_steps_once(self):
        copy = procedures_copy()
        toy_with(33, copy)
        self.assertEqual(measure(base_package(), copy), ())
        fresh = procedures_copy()
        toy_with(34, fresh)
        self.assertEqual(
            measure(base_package(), fresh), (Breach("procedure toy", 41, 40, "steps"),)
        )

    def test_25_graders_pass_and_a_26th_is_refused(self):
        many = lambda n: {f"g-{i:02d}": Grader(("ok",), _short) for i in range(n)}
        self.assertEqual(measure(base_package(), graders=many(25)), ())
        self.assertEqual(
            measure(base_package(), graders=many(26)),
            (Breach("graders", 26, 25, "graders"),),
        )

    def test_a_grader_of_40_lines_passes_and_41_is_refused(self):
        self.assertEqual(
            measure(base_package(), graders={"long": Grader(("ok",), long_grader(40))}), ()
        )
        self.assertEqual(
            measure(base_package(), graders={"long": Grader(("ok",), long_grader(41))}),
            (Breach("grader long", 41, 40, "lines"),),
        )

    def test_a_prompt_of_8192_bytes_passes_and_8193_is_refused(self):
        for size, expected in ((8192, ()), (8193, (Breach("prompt toy-review.md", 8193, 8192, "bytes"),))):
            with self.subTest(size=size):
                copy = procedures_copy()
                path = copy / "toy-review.md"
                current = path.read_bytes()
                path.write_bytes(current + b"a" * (size - len(current)))
                self.assertEqual(measure(base_package(), copy), expected)

    def test_the_prompt_cap_is_on_bytes_not_characters(self):
        copy = procedures_copy()
        (copy / "toy-review.md").write_text("é" * 4096, encoding="utf-8")
        self.assertEqual(measure(base_package(), copy), ())
        (copy / "toy-review.md").write_text("é" * 4097, encoding="utf-8")
        self.assertEqual(
            measure(base_package(), copy), (Breach("prompt toy-review.md", 8194, 8192, "bytes"),)
        )

    def test_breaches_come_in_a_fixed_order(self):
        copy = procedures_copy()
        write_json(copy, "chain", chain(41))
        (copy / "toy-review.md").write_bytes(b"a" * 8193)
        graders = {f"g-{i:02d}": Grader(("ok",), _short) for i in range(25)}
        graders["long"] = Grader(("ok",), long_grader(41))
        self.assertEqual(
            measure(base_package(core=601, engine=6400), copy, graders),
            (
                Breach("core", 601, 600, "lines"),
                Breach("engine package", 7001, 7000, "lines"),
                Breach("graders", 26, 25, "graders"),
                Breach("grader long", 41, 40, "lines"),
                Breach("procedure chain", 41, 40, "steps"),
                Breach("prompt toy-review.md", 8193, 8192, "bytes"),
            ),
        )

    def test_an_unreadable_procedure_is_left_to_phase_a(self):
        copy = procedures_copy()
        (copy / "bad.json").write_text("{", encoding="utf-8")
        (copy / "odd.json").write_text('{"steps": 5}', encoding="utf-8")
        self.assertEqual(measure(base_package(), copy), ())

    def test_a_symlink_out_of_the_procedure_directory_is_not_measured(self):
        outside = temp_dir()
        write_json(outside, "big", chain(41))
        (outside / "big.md").write_bytes(b"a" * 9000)
        copy = procedures_copy()
        (copy / "linked.json").symlink_to(outside / "big.json")
        (copy / "linked.md").symlink_to(outside / "big.md")
        self.assertEqual(measure(base_package(), copy), ())

    def test_a_symlink_inside_the_procedure_directory_is_measured(self):
        copy = procedures_copy()
        (copy / "target.md").write_bytes(b"a" * 8193)
        (copy / "linked.md").symlink_to(copy / "target.md")
        self.assertEqual(
            measure(base_package(), copy),
            (Breach("prompt linked.md", 8193, 8192, "bytes"), Breach("prompt target.md", 8193, 8192, "bytes")),
        )

    def test_a_deeply_nested_procedure_is_left_to_phase_a(self):
        copy = procedures_copy()
        (copy / "deep.json").write_bytes(b"[" * 100000 + b"]" * 100000)
        self.assertEqual(measure(base_package(), copy), ())
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = engine.main(["check", "--procedures", str(copy)])
        self.assertEqual((code, err.getvalue()), (1, ""))
        document = json.loads(out.getvalue())
        self.assertEqual(document["breaches"], [])
        self.assertIn(("deep", "unreadable_procedure"), [(r["procedure"], r["defect"]) for r in document["refusals"]])

    def test_a_prompt_removed_after_enumeration_is_a_value_error(self):
        copy = procedures_copy()
        real = engine_caps.procedure_check._inside

        def vanish(directory, name):
            found = real(directory, name)
            if name == "toy-review.md":
                found.unlink()
            return found

        with mock.patch.object(engine_caps.procedure_check, "_inside", vanish):
            with self.assertRaises(ValueError) as caught:
                measure(base_package(), copy)
        self.assertNotIn("\n", str(caught.exception))

    def test_every_md_file_is_a_prompt_and_only_md_files_are(self):
        copy = procedures_copy()
        (copy / "notes.txt").write_bytes(b"a" * 9000)
        (copy / "big.reply.json").write_bytes(b"a" * 9000)
        write_json(copy, "long.reply", chain(41))
        self.assertEqual(measure(base_package(), copy), ())
        fresh = procedures_copy()
        (fresh / "extra.md").write_bytes(b"a" * 8193)
        self.assertEqual(
            measure(base_package(), fresh), (Breach("prompt extra.md", 8193, 8192, "bytes"),)
        )

    def test_an_unmeasurable_grader_or_a_missing_core_is_a_value_error(self):
        with self.assertRaises(ValueError):
            measure(base_package(), graders={"builtin": Grader(("ok",), len)})
        with self.assertRaises(ValueError):
            measure(package({"engine.py": pad(10)}))

    def test_a_breach_is_reported_as_cap_size_thing_and_unit(self):
        self.assertEqual(
            Breach("core", 601, 600, "lines").as_json(),
            {"cap": 600, "size": 601, "thing": "core", "unit": "lines"},
        )


CAP_NAMES = {
    "CORE_LINES": 600,
    "PACKAGE_LINES": 7000,
    "PROCEDURE_STEPS": 40,
    "GRADER_COUNT": 25,
    "GRADER_LINES": 40,
    "PROMPT_BYTES": 8192,
}


class StaticImmunityTest(unittest.TestCase):
    def setUp(self):
        self.tree = ast.parse((DELIVERY / "engine_caps.py").read_text(encoding="utf-8"))

    def test_the_caps_are_int_literals_assigned_once(self):
        for name in CAP_NAMES:
            with self.subTest(name=name):
                assigns = [
                    node
                    for node in self.tree.body
                    if (isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets))
                    or (isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == name)
                ]
                self.assertEqual(len(assigns), 1)
                value = assigns[0].value
                self.assertIsInstance(value, ast.Constant)
                self.assertIs(type(value.value), int)
        self.assertEqual({name: getattr(engine_caps, name) for name in CAP_NAMES}, CAP_NAMES)

    def test_the_measurement_takes_no_cap_and_reads_no_environment(self):
        self.assertEqual(
            list(inspect.signature(engine_caps.breaches).parameters),
            ["package_dir", "procedures_dir", "graders"],
        )
        names = {node.id for node in ast.walk(self.tree) if isinstance(node, ast.Name)}
        attrs = {node.attr for node in ast.walk(self.tree) if isinstance(node, ast.Attribute)}
        self.assertEqual((names | attrs) & {"environ", "environb", "getenv"}, set())
        self.assertNotIn("__file__", names)
        imported = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                imported |= {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom):
                imported.add((node.module or "").split(".")[0])
        self.assertNotIn("os", imported)


class ShippedTreeTest(unittest.TestCase):
    def test_the_shipped_tree_passes_every_cap(self):
        self.assertEqual(engine_caps.breaches(DELIVERY, PROCEDURES, engine_graders.GRADERS), ())
        names = {p.name for p in engine_caps.engine_modules(DELIVERY)}
        self.assertLessEqual(
            {"engine.py", "engine_caps.py", "engine_core.py", "engine_graders.py", "engine_ledger.py", "procedure_check.py"},
            names,
        )
        result = subprocess.run(
            [sys.executable, "-m", "agent_tools.delivery.engine", "check"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, '{"procedures":["close-out","deliver","direct","land","land-attempt","setup","toy","toy-child","verify"],"verdict":"ok"}\n')


def compact(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"


def package_copy(edit: Callable[[Path], None]) -> Path:
    root = temp_dir()
    shutil.copytree(
        REPO_ROOT / "python/agent_tools",
        root / "agent_tools",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    edit(root / "agent_tools" / "delivery")
    return root


def grow(path: Path, target: int) -> None:
    assert path.read_bytes().endswith(b"\n")
    with path.open("a", encoding="utf-8") as handle:
        while engine_caps.physical_lines(path) < target:
            handle.write("# pad\n")
            handle.flush()
    assert engine_caps.physical_lines(path) == target


def run_copy(root: Path, *args: str, extra_env: dict[str, str] | None = None) -> tuple[int, str, str]:
    done = subprocess.run(
        [sys.executable, "-m", "agent_tools.delivery.engine", "check", *args],
        env={**os.environ, "PYTHONPATH": str(root), **(extra_env or {})},
        cwd=root,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return done.returncode, done.stdout, done.stderr


def run_check(*args: str) -> tuple[int, str, str]:
    done = subprocess.run(
        [sys.executable, "-m", "agent_tools.delivery.engine", "check", *args],
        capture_output=True,
        text=True,
        timeout=60,
    )
    return done.returncode, done.stdout, done.stderr


def check_in_process(graders) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with mock.patch.object(engine_graders, "GRADERS", graders):
        with redirect_stdout(out), redirect_stderr(err):
            code = engine.main(["check"])
    return code, out.getvalue(), err.getvalue()


CORE_BREACH = {"cap": 600, "size": 601, "thing": "core", "unit": "lines"}


class CheckRefusesTest(unittest.TestCase):
    def test_check_refuses_a_core_over_600_lines(self):
        root = package_copy(lambda d: grow(d / "engine_core.py", 601))
        code, out, _ = run_copy(root)
        document = json.loads(out)
        self.assertEqual(code, 1)
        self.assertEqual(document["verdict"], "refused")
        self.assertIn(CORE_BREACH, document["breaches"])
        self.assertEqual(document["refusals"], [])

    def test_check_refuses_an_engine_package_over_7000_lines(self):
        def edit(d: Path) -> None:
            total = sum(engine_caps.physical_lines(p) for p in engine_caps.engine_modules(d))
            ledger = d / "engine_ledger.py"
            grow(ledger, engine_caps.physical_lines(ledger) + 7001 - total)

        code, out, _ = run_copy(package_copy(edit))
        document = json.loads(out)
        self.assertEqual(code, 1)
        self.assertIn({"cap": 7000, "size": 7001, "thing": "engine package", "unit": "lines"}, document["breaches"])
        self.assertNotIn("core", [b["thing"] for b in document["breaches"]])

    def test_check_refuses_a_41st_step_naming_the_procedure(self):
        copy = procedures_copy()
        write_json(copy, "chain", chain(41))
        code, out, _ = run_check("--procedures", str(copy))
        self.assertEqual(code, 1)
        self.assertEqual(
            out,
            compact(
                {
                    "breaches": [{"cap": 40, "size": 41, "thing": "procedure chain", "unit": "steps"}],
                    "refusals": [],
                    "verdict": "refused",
                }
            ),
        )
        ok = procedures_copy()
        write_json(ok, "chain", chain(40))
        code, out, _ = run_check("--procedures", str(ok))
        self.assertEqual(code, 0)
        self.assertEqual(out, compact({"procedures": ["chain", "close-out", "deliver", "direct", "land", "land-attempt", "setup", "toy", "toy-child", "verify"], "verdict": "ok"}))
        fresh = procedures_copy()
        toy_with(34, fresh)
        code, out, _ = run_check("--procedures", str(fresh))
        document = json.loads(out)
        self.assertEqual(code, 1)
        self.assertEqual(
            document["breaches"], [{"cap": 40, "size": 41, "thing": "procedure toy", "unit": "steps"}]
        )
        self.assertTrue(document["refusals"])

    def test_check_refuses_a_26th_grader(self):
        many = lambda n: {f"g-{i:02d}": Grader(("ok",), _short) for i in range(n)}
        code, out, _ = check_in_process(many(26))
        self.assertEqual(code, 1)
        self.assertEqual(
            json.loads(out)["breaches"],
            [{"cap": 25, "size": 26, "thing": "graders", "unit": "graders"}],
        )
        self.assertEqual(check_in_process(many(25))[0], 0)

    def test_check_refuses_a_41_line_grader(self):
        code, out, _ = check_in_process({"long": Grader(("ok",), long_grader(41))})
        self.assertEqual(code, 1)
        self.assertEqual(
            json.loads(out)["breaches"],
            [{"cap": 40, "size": 41, "thing": "grader long", "unit": "lines"}],
        )
        self.assertEqual(check_in_process({"long": Grader(("ok",), long_grader(40))})[0], 0)

    def test_check_refuses_a_prompt_over_8_kb(self):
        for size in (8193, 8192):
            with self.subTest(size=size):
                copy = procedures_copy()
                path = copy / "toy-review.md"
                current = path.read_bytes()
                path.write_bytes(current + b"a" * (size - len(current)))
                code, out, _ = run_check("--procedures", str(copy))
                if size == 8193:
                    self.assertEqual(code, 1)
                    self.assertEqual(
                        out,
                        compact(
                            {
                                "breaches": [
                                    {"cap": 8192, "size": 8193, "thing": "prompt toy-review.md", "unit": "bytes"}
                                ],
                                "refusals": [],
                                "verdict": "refused",
                            }
                        ),
                    )
                else:
                    self.assertEqual(code, 0)
                    self.assertEqual(out, compact({"procedures": ["close-out", "deliver", "direct", "land", "land-attempt", "setup", "toy", "toy-child", "verify"], "verdict": "ok"}))

    def test_a_filesystem_error_while_measuring_is_usage(self):
        error = FileNotFoundError(2, "No such file or directory", "toy-review.md")
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(engine_caps, "_breaches", side_effect=error):
            with redirect_stdout(out), redirect_stderr(err):
                code = engine.main(["check"])
        self.assertEqual((code, out.getvalue()), (2, ""))
        self.assertEqual(len(err.getvalue().splitlines()), 1)

    def test_an_unmeasurable_grader_is_usage(self):
        code, out, err = check_in_process({"builtin": Grader(("ok",), len)})
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertEqual(len(err.splitlines()), 1)


OPTION_VALUES = {"procedures": lambda root: str(root / "agent_tools/delivery/procedures")}


class ImmunityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = package_copy(lambda d: grow(d / "engine_core.py", 601))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root, ignore_errors=True)

    def test_no_option_lifts_a_cap(self):
        actions = engine.build_parser()._actions
        subparsers = next(a for a in actions if isinstance(a, argparse._SubParsersAction))
        check = subparsers.choices["check"]
        options = [a for a in check._actions if not isinstance(a, argparse._HelpAction)]
        self.assertEqual({a.dest for a in options}, set(OPTION_VALUES), "a new option needs a row here")
        code, out, _ = run_copy(self.root)
        self.assertEqual(code, 1)
        self.assertIn(CORE_BREACH, json.loads(out)["breaches"])
        for action in options:
            for option in action.option_strings:
                with self.subTest(option=option):
                    code, out, _ = run_copy(self.root, option, OPTION_VALUES[action.dest](self.root))
                    self.assertEqual(code, 1)
                    self.assertIn(CORE_BREACH, json.loads(out)["breaches"])
        for action in check._actions:
            if isinstance(action, argparse._HelpAction):
                for option in action.option_strings:
                    with self.subTest(help=option):
                        code, out, err = run_copy(self.root, option)
                        self.assertEqual((code, err), (0, ""))
                        self.assertTrue(out.startswith("usage:"), out)
                        self.assertNotIn('"verdict"', out)

    def test_no_environment_variable_lifts_a_cap(self):
        extra_env = {}
        for name in CAP_NAMES:
            for variable in (name, f"ENGINE_{name}", f"ENGINE_CAP_{name}"):
                extra_env[variable] = "1000000"
        extra_env.update(ENGINE_CAPS="off", ENGINE_NO_CAPS="1", ENGINE_CHECK_CAPS="0")
        code, out, _ = run_copy(self.root, extra_env=extra_env)
        self.assertEqual(code, 1)
        self.assertIn(CORE_BREACH, json.loads(out)["breaches"])
        tree = ast.parse((DELIVERY / "engine.py").read_text(encoding="utf-8"))
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        self.assertEqual((names | attrs) & {"environ", "environb", "getenv"}, set())


class PackageLocationTest(unittest.TestCase):
    def test_the_package_is_located_through_its_resources_not_file(self):
        tree = ast.parse((DELIVERY / "engine.py").read_text(encoding="utf-8"))
        assigns = [
            node
            for node in tree.body
            if (isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "ENGINE_DIR" for t in node.targets))
            or (isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == "ENGINE_DIR")
        ]
        self.assertEqual(len(assigns), 1)
        used = {n.id for n in ast.walk(assigns[0].value) if isinstance(n, ast.Name)}
        self.assertNotIn("__file__", used)
        self.assertEqual(engine.ENGINE_DIR.resolve(), DELIVERY.resolve())


if __name__ == "__main__":
    unittest.main()
