"""The procedure format's terms the engine and the check share live in `procedure_terms`."""

from __future__ import annotations

import ast
import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent_tools.delivery import engine_check, engine_graders, procedure_check, procedure_terms, size_caps
from agent_tools.delivery.size_caps import Breach
from tests.guard_policy_world import install_platform_manifest_in_environ
from tests.test_engine_check import (
    PROCEDURES, REPEAT_SCOPE_REFUSED, SHIPPED_OK, _repeat_scope, broken_copy, compact, editing, load, run_check, save,
    step)

setUpModule = install_platform_manifest_in_environ

TIER = "integration"

DELIVERY = Path(__file__).resolve().parents[1] / "python/agent_tools/delivery"


def imported_modules(source: Path) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
            modules.update(f"{node.module}.{alias.name}" for alias in node.names)
    return modules


class TermsTest(unittest.TestCase):
    def test_the_ledger_session_and_commands_import_the_terms_not_the_validator(self):
        for name in ("engine_ledger.py", "engine_session.py", "engine_commands.py"):
            with self.subTest(name):
                modules = imported_modules(DELIVERY / name)
                self.assertNotIn("agent_tools.delivery.procedure_check", modules)
                self.assertIn("agent_tools.delivery.procedure_terms", modules)

    def test_the_validator_uses_the_engines_terms(self):
        for name in ("STAGES", "NEEDS", "ROLES", "WAITS", "NAME_RE", "INPUT_RE", "PLACEHOLDER_RE",
                     "OUT_OF_BOUNDS", "NO_REPLY", "CLAIM_LOST", "QUOTA_WAIT", "SUPERSEDED",
                     "readable_format", "_inside", "_strict_load"):
            with self.subTest(name):
                self.assertIs(getattr(procedure_check, name), getattr(procedure_terms, name))


def run_process(*args: str) -> tuple[int, str, str]:
    done = subprocess.run([sys.executable, "-m", "agent_tools.delivery.procedure_check", *args],
                          capture_output=True, text=True, timeout=60)
    return done.returncode, done.stdout, done.stderr


def in_process(*argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = procedure_check.main(list(argv))
    return code, out.getvalue(), err.getvalue()


def _standin_project(toy: dict) -> None:
    step(toy, "scope")["command"] = "standin-project"


class CheckProcessTest(unittest.TestCase):
    def test_the_check_process_prints_the_line_engine_check_prints(self):
        self.assertEqual(run_process(f"--procedures={PROCEDURES}"), (0, SHIPPED_OK, ""))
        broken = broken_copy(editing("toy", _repeat_scope))
        self.assertEqual(run_process(f"--procedures={broken}"), (1, REPEAT_SCOPE_REFUSED, ""))
        self.assertEqual(run_process(f"--procedures={broken}")[1], run_check("--procedures", str(broken))[1])

    def test_a_project_command_is_declared_with_the_default_verdicts(self):
        broken = broken_copy(editing("toy", _standin_project))
        refused = {(r["procedure"], r["step"], r["defect"])
                   for r in json.loads(run_process(f"--procedures={broken}")[1])["refusals"]}
        self.assertIn(("toy", "scope", "unknown_command"), refused)
        declared = json.loads(
            run_process(f"--procedures={broken}", "--project-command=standin-project")[1])
        self.assertFalse({r["defect"] for r in declared.get("refusals", [])} & {"unknown_command", "undeclared_verdicts"})

    def test_the_declarations_give_each_project_command_the_default_verdicts(self):
        declared = procedure_check.declarations(("standin-json", "release"))
        platform = procedure_terms.load_commands()
        self.assertEqual(set(declared), set(platform) | {"standin-json"})
        self.assertEqual(declared["standin-json"].outcomes(None), ("ok", "failed"))
        self.assertIsNone(declared["standin-json"].outcomes("x"))
        self.assertIsNone(platform["release"])
        self.assertEqual(declared["release"].outcomes(None), ("ok", "failed"))
        self.assertEqual(declared["forge-claim"], platform["forge-claim"])

    def test_a_missing_or_empty_directory_is_usage(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, out, err = run_process(f"--procedures={tmp}/absent")
            self.assertEqual((code, out), (2, ""))
            self.assertEqual(len(err.splitlines()), 1)
            self.assertTrue(err.startswith("procedure-check: "), err)
            self.assertEqual(run_process(f"--procedures={tmp}"),
                             (2, "", f"procedure-check: {tmp} holds no procedure file\n"))

    def test_without_caps_a_measurement_failure_leaves_the_procedure_refusal(self):
        broken = broken_copy(editing("toy", _repeat_scope))
        with mock.patch.object(size_caps, "_breaches", side_effect=OSError("unreadable")):
            self.assertEqual(in_process(f"--procedures={broken}", "--without-caps"),
                             (1, REPEAT_SCOPE_REFUSED, ""))
            code, out, err = in_process(f"--procedures={broken}")
        self.assertEqual((code, out), (2, ""))
        self.assertEqual(len(err.splitlines()), 1)

    def test_without_caps_no_breach_is_reported(self):
        breach = Breach("engine package", 8001, 8000, "lines")
        with mock.patch.object(size_caps, "_breaches", return_value=(breach,)):
            self.assertEqual(in_process(f"--procedures={PROCEDURES}", "--without-caps"), (0, SHIPPED_OK, ""))
            code, out, _ = in_process(f"--procedures={PROCEDURES}")
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out)["breaches"], [breach.as_json()])

    def test_the_check_process_has_only_its_options(self):
        actions = [a for a in procedure_check.build_parser()._actions if a.option_strings != ["-h", "--help"]]
        self.assertEqual({a.dest for a in actions}, {"procedures", "project_command", "without_caps"})

ECHO_ARGV = ("import json, sys; print(json.dumps({'breaches': [], 'refusals': [{'defect': 'x', "
             "'detail': ' '.join(sys.argv[1:]), 'procedure': 'p', 'step': 's'}], "
             "'verdict': 'refused'})); sys.exit(1)")

BROKEN_CHILDREN = (
    "print('x')",
    "import sys; print('{\"procedures\":[],\"verdict\":\"ok\"}'); sys.exit(1)",
    "import sys; sys.exit(3)",
    "import sys; print('{\"verdict\":\"refused\",\"refusals\":[]}'); sys.exit(1)",
    "import sys; print('{\"breaches\":[],\"refusals\":[],\"verdict\":\"refused\"}'); sys.exit(1)",
    "import sys; print('{\"breaches\":[],\"refusals\":[null],\"verdict\":\"refused\"}'); sys.exit(1)",
    "import sys; print('{\"breaches\":[],\"refusals\":[{\"defect\":\"x\",\"procedure\":\"p\","
    "\"step\":\"s\"}],\"verdict\":\"refused\"}'); sys.exit(1)",
    "import sys; print('{\"breaches\":[{\"cap\":8000,\"size\":\"big\",\"thing\":\"t\","
    "\"unit\":\"lines\"}],\"refusals\":[],\"verdict\":\"refused\"}'); sys.exit(1)",
    "print('{\"procedures\":[1],\"verdict\":\"ok\"}')",
)


def fake_child(script: str):
    return mock.patch.object(engine_check, "sibling_argv", return_value=[sys.executable, "-c", script])


class VerdictTest(unittest.TestCase):
    def test_verdict_reads_the_check_process_verdict(self):
        self.assertEqual(engine_check.verdict(PROCEDURES, (), caps=True), (0, json.loads(SHIPPED_OK)))
        broken = broken_copy(editing("toy", _repeat_scope))
        self.assertEqual(engine_check.verdict(broken, (), caps=True),
                         (1, json.loads(REPEAT_SCOPE_REFUSED)))

    def test_the_arguments_reach_the_child_unambiguously(self):
        with fake_child(ECHO_ARGV):
            for caps, detail in ((False, "--procedures=-fixtures --project-command=-a "
                                         "--project-command=b --without-caps"),
                                 (True, "--procedures=-fixtures --project-command=-a --project-command=b")):
                with self.subTest(caps=caps):
                    code, document = engine_check.verdict(Path("-fixtures"), ("-a", "b"), caps=caps)
                    self.assertEqual(code, 1)
                    self.assertEqual([r["detail"] for r in document["refusals"]], [detail])

    def test_project_commands_reach_the_check(self):
        copy = broken_copy(editing("toy", _standin_project))
        _, declared = engine_check.verdict(copy, ("standin-project",), caps=True)
        self.assertNotIn("unknown_command", {r["defect"] for r in declared.get("refusals", [])})
        _, undeclared = engine_check.verdict(copy, (), caps=True)
        self.assertIn(("toy", "scope"), {(r["procedure"], r["step"]) for r in undeclared["refusals"]
                                          if r["defect"] == "unknown_command"})

    def test_a_usage_exit_is_a_check_error_with_the_bare_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(engine_check.CheckError) as raised:
                engine_check.verdict(Path(tmp), (), caps=True)
            self.assertEqual(str(raised.exception), f"{tmp} holds no procedure file")

    def test_a_child_that_breaks_the_contract_is_a_check_error(self):
        for script in BROKEN_CHILDREN:
            with self.subTest(script), fake_child(script):
                with self.assertRaises(engine_check.CheckError):
                    engine_check.verdict(PROCEDURES, (), caps=True)

    def test_a_child_that_writes_bytes_that_are_not_text_is_a_check_error(self):
        for exit_code, stream in ((1, "stdout"), (2, "stderr"), (0, "stdout")):
            script = f"import sys; sys.{stream}.buffer.write(bytes([255])); sys.exit({exit_code})"
            with self.subTest(stream=stream, exit_code=exit_code), fake_child(script):
                with self.assertRaises(engine_check.CheckError):
                    engine_check.verdict(PROCEDURES, (), caps=True)

    def test_a_child_past_its_time_is_a_check_error(self):
        with mock.patch.object(engine_check, "CHECK_SECONDS", 1), fake_child("import time; time.sleep(30)"):
            with self.assertRaises(engine_check.CheckError) as raised:
                engine_check.verdict(PROCEDURES, (), caps=True)
        self.assertIn("did not finish", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
