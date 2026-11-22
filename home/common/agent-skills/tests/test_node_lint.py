"""The Node adapter's contract (#1467): the pinned tools record, and the adapter
that judges Workflow programs with `node --check` and ESLint.

The suite holds `standard:NODE11`, `standard:NODE12`, `standard:NODE13`,
`standard:NODE14` and `standard:NODE15` by judging their enforcer,
`agent_tools.delivery.node_lint`.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent_tools.delivery import never_rise, node_lint, rule_ids
from agent_tools.delivery.never_rise import Violation
from agent_tools.project_contract import agent_platform

from .conformance_test_support import (
    HERMETIC_ENV, INTEGRATION_REF, REAL_GIT, REPO_ROOT, ReportAssertions, commit_all, doctor,
    fixture, git, make_root, node_tools_env, pinned_node_tools, platform_env, run,
)

TIER = "integration"  # git worlds, nix-built node and eslint, the conformance engine

VALID = {"schema_version": 1, "node": "/abs/node", "eslint": "/abs/eslint"}


def write_record(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class NodeToolsRecordTest(unittest.TestCase):
    """The record the platform package pins node and eslint in."""

    def test_the_record_under_the_platform_root_names_the_two_tools(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "home").mkdir()
            write_record(base / "root" / "node-tools.json", json.dumps(VALID))
            env = {"AGENT_PLATFORM_ROOT": str(base / "root"), "HOME": str(base / "home")}
            with mock.patch.dict(os.environ, env):
                self.assertEqual(agent_platform.node_tools(), ("/abs/node", "/abs/eslint"))

    def test_with_no_root_the_record_is_read_from_home_share(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            expected = home / ".agents" / "share" / "node-tools.json"
            write_record(expected, json.dumps(VALID))
            with mock.patch.dict(os.environ, {"HOME": str(home)}):
                os.environ.pop("AGENT_PLATFORM_ROOT", None)
                self.assertEqual(agent_platform.node_tools(), ("/abs/node", "/abs/eslint"))
                self.assertEqual(agent_platform.node_tools_path(), expected)

    def test_a_non_empty_root_never_falls_back_to_home(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "root").mkdir()
            write_record(base / "home" / ".agents" / "share" / "node-tools.json", json.dumps(VALID))
            env = {"AGENT_PLATFORM_ROOT": str(base / "root"), "HOME": str(base / "home")}
            with mock.patch.dict(os.environ, env):
                with self.assertRaises(agent_platform.NodeToolsError):
                    agent_platform.node_tools()

    def test_a_missing_or_malformed_record_is_refused(self) -> None:
        cases = {
            "no file": None,
            "not json": "not json",
            "not an object": "[]",
            "member missing": json.dumps({"schema_version": 1, "node": "/n"}),
            "extra member": json.dumps({**VALID, "extra": 1}),
            "schema version 2": json.dumps({**VALID, "schema_version": 2}),
            "schema version bool": json.dumps({**VALID, "schema_version": True}),
            "relative node": json.dumps({**VALID, "node": "node"}),
            "empty eslint": json.dumps({**VALID, "eslint": ""}),
        }
        for name, text in cases.items():
            with self.subTest(name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp) / "root"
                root.mkdir()
                if text is not None:
                    write_record(root / "node-tools.json", text)
                with mock.patch.dict(os.environ, {"AGENT_PLATFORM_ROOT": str(root)}):
                    with self.assertRaises(agent_platform.NodeToolsError) as caught:
                        agent_platform.node_tools()
                self.assertIn("node-tools.json", str(caught.exception))


META = "export const meta = { name: 'fixture' }\n"


def pinned_tools() -> node_lint.NodeTools:
    record = pinned_node_tools()
    return node_lint.NodeTools(record["node"], record["eslint"])


def shim(tmp: Path, name: str, script: str) -> str:
    """An executable `<tmp>/<name>` running `script` with shell builtins only."""
    path = tmp / name
    path.write_text("#!/bin/sh\n" + script, encoding="utf-8")
    path.chmod(0o755)
    return str(path)


def make_repo(tmp: Path, files: dict[str, str]) -> tuple[Path, str]:
    """A committed repository on `main` holding `files`; its root and head."""
    root = tmp / "repo"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    for relative, text in files.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    commit_all(root, "fixture")
    return root, git(root, "rev-parse", "HEAD").strip()


def run_command(root: Path, home: str, *args: str) -> subprocess.CompletedProcess:
    env = {"HOME": home, "LANG": "C", "PYTHONPATH": HERMETIC_ENV["PYTHONPATH"],
           "PATH": os.pathsep.join(["/usr/bin", "/bin", str(Path(REAL_GIT).parent)])}
    return subprocess.run(
        [sys.executable, "-m", "agent_tools.delivery.node_lint", "--repo-root", str(root), *args],
        env=env, capture_output=True, text=True, timeout=120)


class NodeLintCommandTest(unittest.TestCase):
    """The `node-lint` command, run as a child process."""

    def test_an_unused_variable_in_a_program_prints_one_node12_line(self) -> None:
        with fixture() as tmp:
            root, _ = make_repo(tmp, {"prog/one.js": META + "const unused = 1\n"})
            home = platform_env(tmp, node_tools=pinned_node_tools())["HOME"]
            proc = run_command(root, home)
        self.assertEqual((proc.returncode, proc.stdout), (1, "NODE12 prog/one.js:2\n"), proc.stderr)

    def test_a_clean_program_exits_zero(self) -> None:
        with fixture() as tmp:
            root, _ = make_repo(tmp, {"prog/one.js": META})
            home = platform_env(tmp, node_tools=pinned_node_tools())["HOME"]
            proc = run_command(root, home)
        self.assertEqual((proc.returncode, proc.stdout), (0, ""), proc.stderr)

    def test_a_program_with_no_tool_record_is_a_usage_error(self) -> None:
        with fixture() as tmp:
            root, _ = make_repo(tmp, {"prog/one.js": META})
            proc = run_command(root, platform_env(tmp)["HOME"])
        self.assertEqual(proc.returncode, 2)
        self.assertTrue(proc.stderr.startswith("node-lint: node-tools:"), proc.stderr)

    def test_a_relative_root_is_a_usage_error(self) -> None:
        with fixture() as tmp:
            proc = run_command(Path("rel"), platform_env(tmp)["HOME"])
        self.assertEqual(proc.returncode, 2)


class NodeLintCasesTest(unittest.TestCase):
    """`lint_files` over one batch of program texts, each judged by the pinned tools."""

    CASES = {
        "clean": META,
        "redeclared_parameter": "export const meta = {}\nconst agent = 1\n",
        "directive_prologue": "'use strict'\nexport const meta = {}\nwith (args) {}\n",
        "does_not_parse": "export const meta = {}\nconst = 1\n",
        "unclosed_block": "export const meta = {}\nif (args) {\n",
        "disable_with_reason": (
            "export const meta = {}\n"
            "const unused = 1 // eslint-disable-line no-unused-vars -- kept for the fixture\n"),
        "disable_without_reason": (
            "export const meta = {}\n// eslint-disable-next-line no-unused-vars\nconst unused = 1\n"),
        "disable_without_rule": (
            "export const meta = {}\nconst unused = 1 // eslint-disable-line -- kept for the fixture\n"),
        "disable_with_empty_reason": (
            "export const meta = {}\nconst unused = 1 // eslint-disable-line no-unused-vars -- ...\n"),
        "inline_configuration": (
            "export const meta = {}\n/* eslint no-unused-vars: off -- kept */\nconst unused = 1\n"),
        "enable": "export const meta = {}\n/* eslint-enable */\n",
        "first_line": "export const meta = {}; const unused = 1\n",
        "runtime_shape": (
            "export const meta = {}\nconst r = await agent('x', { schema: args })\nlog(r)\n"
            "await parallel([])\nawait pipeline([])\nphase('p')\nvoid budget\nvoid workflow\n"
            "return r\n"),
        "undeclared": "export const meta = {}\nmissing()\n",
        "unreachable": "export const meta = {}\nreturn 1\nlog(2)\n",
    }

    @classmethod
    def setUpClass(cls) -> None:
        files = {f"case/{name}.js": text for name, text in cls.CASES.items()}
        cls.found = node_lint.lint_files(files, pinned_tools(), 120)

    def violations(self, name: str) -> list[tuple[str, int]]:
        path = f"case/{name}.js"
        return [(v.rule, v.line) for v in self.found if v.path == path]

    def test_a_clean_program_yields_no_violation(self) -> None:
        self.assertEqual(self.violations("clean"), [])

    def test_redeclaring_a_runtime_parameter_is_one_node11_violation(self) -> None:
        self.assertEqual(self.violations("redeclared_parameter"), [("NODE11", 2)])

    def test_a_directive_prologue_stays_a_directive(self) -> None:
        self.assertEqual(self.violations("directive_prologue"), [("NODE11", 3)])

    def test_a_program_that_does_not_parse_is_one_node11_violation(self) -> None:
        self.assertEqual(self.violations("does_not_parse"), [("NODE11", 2)])

    def test_an_unclosed_block_is_one_node11_on_the_last_source_line(self) -> None:
        self.assertEqual(self.violations("unclosed_block"), [("NODE11", 2)])

    def test_a_disable_comment_with_its_rule_and_a_reason_hides_the_finding(self) -> None:
        self.assertEqual(self.violations("disable_with_reason"), [])

    def test_a_disable_comment_without_a_reason_is_one_node15_violation(self) -> None:
        self.assertEqual(self.violations("disable_without_reason"), [("NODE15", 2)])

    def test_a_disable_comment_naming_no_rule_is_one_node15_violation(self) -> None:
        self.assertEqual(self.violations("disable_without_rule"), [("NODE15", 2)])

    def test_a_reason_without_a_letter_or_digit_is_one_node15_violation(self) -> None:
        self.assertEqual(self.violations("disable_with_empty_reason"), [("NODE15", 2)])

    def test_an_inline_configuration_comment_is_one_node15_violation(self) -> None:
        self.assertEqual(self.violations("inline_configuration"), [("NODE15", 2)])

    def test_an_enable_comment_is_no_violation(self) -> None:
        self.assertEqual(self.violations("enable"), [])

    def test_a_finding_on_the_first_line_names_line_one(self) -> None:
        self.assertEqual(self.violations("first_line"), [("NODE12", 1)])

    def test_the_runtime_shape_parses_and_its_names_are_defined(self) -> None:
        self.assertEqual(self.violations("runtime_shape"), [])

    def test_an_undeclared_name_is_node13(self) -> None:
        self.assertEqual(self.violations("undeclared"), [("NODE13", 2)])

    def test_unreachable_code_is_node14(self) -> None:
        self.assertEqual(self.violations("unreachable"), [("NODE14", 3)])

    def test_a_file_that_is_no_program_is_not_judged(self) -> None:
        self.assertIs(node_lint.is_program("lib/x.js", "const unused = 1\n"), False)
        self.assertIs(node_lint.is_program("lib/x.mjs", "export const meta = {}\n"), False)
        self.assertIs(node_lint.is_program("p.js", "export const meta = {}\n"), True)


class NodeEnforcerTest(unittest.TestCase):
    """The five enforcers: coverage, one shared run per revision, and failures."""

    UNUSED = META + "const unused = 1\n"

    def snapshot(self, root: Path, revision: str) -> never_rise.Snapshot:
        snapshot = never_rise.read_snapshot(root, revision, 60)
        assert snapshot is not None
        return snapshot

    def test_a_program_selected_at_another_revision_stays_covered(self) -> None:
        with fixture() as tmp:
            root, first = make_repo(tmp, {"src/p.js": META})
            (root / "src/p.js").write_text("export const = { name: 'fixture' }\n", encoding="utf-8")
            commit_all(root, "break the meta line")
            second = git(root, "rev-parse", "HEAD").strip()
            tools = pinned_tools

            def node11(also: tuple[str, ...]) -> never_rise.Enforcer:
                return [e for e in node_lint.enforcers(root, 60, tools, also)
                        if e.rule == "NODE11"][0]

            snapshot = self.snapshot(root, second)
            self.assertEqual(node11((first, second)).find(snapshot), [Violation("NODE11", "src/p.js", 1)])
            self.assertEqual(node11(()).find(snapshot), [])

    def test_a_revision_with_no_program_never_resolves_the_tools(self) -> None:
        def tools() -> node_lint.NodeTools:
            raise AssertionError("the tools were resolved")

        with fixture() as tmp:
            root, head = make_repo(tmp, {"lib/x.js": "const unused = 1\n"})
            for enforcer in node_lint.enforcers(root, 60, tools):
                self.assertEqual(never_rise.counted(enforcer, self.snapshot(root, head)), ([], []))

    def test_the_five_enforcers_share_one_run_per_revision(self) -> None:
        with fixture() as tmp:
            root, head = make_repo(tmp, {"p.js": self.UNUSED})
            snapshot = self.snapshot(root, head)
            with mock.patch.object(node_lint, "lint_files", wraps=node_lint.lint_files) as spy:
                found = {e.rule: e.find(snapshot)
                         for e in node_lint.enforcers(root, 60, pinned_tools)}
        self.assertEqual(spy.call_count, 1)
        self.assertEqual(sorted(found), list(node_lint.RULES))
        self.assertEqual(found["NODE12"], [Violation("NODE12", "p.js", 2)])

    def test_a_tool_that_cannot_start_is_an_enforcer_failure(self) -> None:
        def tools() -> node_lint.NodeTools:
            return node_lint.NodeTools("/nonexistent/node", "/nonexistent/eslint")

        with fixture() as tmp:
            root, head = make_repo(tmp, {"p.js": META})
            enforcer = node_lint.enforcers(root, 60, tools)[0]
            with self.assertRaises(never_rise.EnforcerFailure) as caught:
                enforcer.find(self.snapshot(root, head))
        self.assertEqual((caught.exception.tool, caught.exception.reason), ("node", "not_started"))

    def test_a_tools_callable_that_raises_is_an_enforcer_failure(self) -> None:
        def tools() -> node_lint.NodeTools:
            raise ValueError("x")

        with fixture() as tmp:
            root, head = make_repo(tmp, {"p.js": META})
            enforcer = node_lint.enforcers(root, 60, tools)[0]
            with self.assertRaises(never_rise.EnforcerFailure) as caught:
                enforcer.find(self.snapshot(root, head))
        self.assertEqual((caught.exception.tool, caught.exception.reason, caught.exception.detail),
                         ("node-tools", "record_unavailable", "x"))

    def test_a_failed_blob_read_is_history_unreadable(self) -> None:
        with fixture() as tmp:
            root, head = make_repo(tmp, {"p.js": META})
            snapshot = self.snapshot(root, head)
            enforcer = node_lint.enforcers(root, 60, pinned_tools)[0]
            with mock.patch.object(never_rise, "read_blobs", return_value=None):
                with self.assertRaises(never_rise.HistoryUnreadable):
                    enforcer.find(snapshot)

    def test_the_tools_run_with_only_home_and_lang(self) -> None:
        polluted = {"NODE_OPTIONS": "--require /nonexistent", "ESLINT_USE_FLAT_CONFIG": "false"}
        with mock.patch.dict(os.environ, polluted), \
                mock.patch.object(node_lint.subprocess, "run", wraps=subprocess.run) as spy:
            found = node_lint.lint_files({"p.js": self.UNUSED}, pinned_tools(), 60)
        self.assertEqual([(v.rule, v.line) for v in found], [("NODE12", 2)])
        self.assertTrue(spy.call_args_list)
        for call in spy.call_args_list:
            self.assertEqual(set(call.kwargs["env"]), {"HOME", "LANG"})


class NodeToolOutputTest(unittest.TestCase):
    """Incomplete or malformed tool output fails closed."""

    def fails(self, tools: node_lint.NodeTools, tool: str, reason: str) -> None:
        with self.assertRaises(never_rise.EnforcerFailure) as caught:
            node_lint.lint_files({"p.js": "export const meta = {}\n"}, tools, 60)
        self.assertEqual((caught.exception.tool, caught.exception.reason), (tool, reason))

    def with_eslint(self, script: str) -> node_lint.NodeTools:
        tmp = Path(tempfile.mkdtemp(prefix="node-lint-shim-"))
        self.addCleanup(__import__("shutil").rmtree, tmp, True)
        return node_lint.NodeTools(pinned_tools().node, shim(tmp, "eslint", script))

    def test_an_eslint_result_list_missing_a_file_is_an_enforcer_failure(self) -> None:
        self.fails(self.with_eslint("printf '[]'\n"), "eslint", "unreadable_output")

    def test_an_eslint_result_without_a_file_path_is_an_enforcer_failure(self) -> None:
        self.fails(self.with_eslint("printf '[{\"messages\": []}]'\nexit 1\n"),
                   "eslint", "unreadable_output")

    def test_a_message_without_a_line_is_an_enforcer_failure(self) -> None:
        script = ("printf '[{\"filePath\": \"p0.cjs\", \"messages\": "
                  "[{\"ruleId\": \"no-undef\", \"message\": \"x\"}]}]'\nexit 1\n")
        self.fails(self.with_eslint(script), "eslint", "unreadable_output")

    def test_an_unexpected_eslint_exit_is_an_enforcer_failure(self) -> None:
        self.fails(self.with_eslint("exit 2\n"), "eslint", "unexpected_exit")

    def test_a_node_syntax_exit_without_a_diagnostic_is_an_enforcer_failure(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="node-lint-shim-"))
        self.addCleanup(__import__("shutil").rmtree, tmp, True)
        node = shim(tmp, "node", "printf 'garbage' >&2\nexit 1\n")
        self.fails(node_lint.NodeTools(node, pinned_tools().eslint), "node", "unreadable_output")


class NodeRuleMappingTest(unittest.TestCase):
    """The mapping is the pinned ESLint's recommended set, under the shard's rule ids."""

    def test_the_mapping_is_the_recommended_set_of_the_pinned_eslint(self) -> None:
        tools = pinned_tools()
        recommended = (Path(tools.eslint).parents[1] / "lib/node_modules/eslint/node_modules"
                       / "@eslint/js/src/configs/eslint-recommended.js")
        out = subprocess.run(
            [tools.node, "-e",
             "console.log(JSON.stringify(Object.keys(require(process.argv[1]).rules)))",
             str(recommended)],
            capture_output=True, text=True, timeout=60, check=True, env={}).stdout
        self.assertEqual(set(node_lint.ESLINT_RULES), set(json.loads(out)))
        self.assertEqual(len(node_lint.ESLINT_RULES), 61)

    def test_every_rule_id_is_a_rule_of_the_node_shard(self) -> None:
        text = (REPO_ROOT / "home/common/agent-skills/standards/stacks/node.md").read_text(
            encoding="utf-8")
        headings, _ = rule_ids.rule_headings(text)
        ids = {f"{prefix}{number}" for prefix, number, _ in headings}
        self.assertLessEqual(set(node_lint.RULES), ids)
        self.assertEqual(set(node_lint.ESLINT_RULES.values()), {"NODE12", "NODE13", "NODE14"})

class NodeNeverRiseTest(ReportAssertions, unittest.TestCase):
    """The never-rise check judges Workflow programs with the Node enforcers."""

    CHECK_ID = "verification.violations.never_rise"

    def ci(self, root: Path, env: dict) -> tuple[int, dict, dict]:
        code, out, err = run("run", "--purpose", "ci", "--repo-root", str(root), env=env)
        self.assertIn(code, (0, 1), err)
        report = json.loads(out)
        return code, report, {c["id"]: c for c in report["checks"]}

    def summary(self, check: dict) -> list:
        return [check["status"], check["reason_code"], check["repair_id"], check["facts"]]

    def branch(self, tmp: Path, base_text: str, branch_text: str) -> tuple[Path, str]:
        """A root whose integration tip holds `base_text` as a program, then a branch commit."""
        root = make_root(tmp)
        (root / "src").mkdir()
        (root / "src" / "p.js").write_text(base_text, encoding="utf-8")
        commit_all(root, "program")
        git(root, "update-ref", INTEGRATION_REF, "HEAD")
        base = git(root, "rev-parse", "HEAD").strip()
        if branch_text != base_text:
            (root / "src" / "p.js").write_text(branch_text, encoding="utf-8")
            commit_all(root, "branch")
        return root, base

    def rose(self, tmp: Path, base_text: str, branch_text: str) -> dict:
        root, _ = self.branch(tmp, base_text, branch_text)
        code, report, by_id = self.ci(root, node_tools_env(tmp))
        self.assertEqual(code, 1)
        self.assert_validates(report)
        return by_id[self.CHECK_ID]

    def test_a_branch_that_adds_an_unused_variable_to_a_program_turns_ci_red_naming_node12_and_the_line(self) -> None:
        with fixture() as tmp:
            root, base = self.branch(tmp, META, META + "const unused = 1\n")
            code, report, by_id = self.ci(root, node_tools_env(tmp))
            self.assertEqual(code, 1)
            self.assertEqual(
                self.summary(by_id[self.CHECK_ID]),
                ["failed", "violation_count_rose", "violations.never_rise.reduce", {
                    "merge_base": base, "rule": "NODE12", "base_count": 0, "branch_count": 1,
                    "violations": ["NODE12 src/p.js:2"], "rules": ["NODE12"]}])
            self.assert_validates(report)

    def test_a_branch_that_removes_a_finding_passes_ci(self) -> None:
        with fixture() as tmp:
            root, base = self.branch(tmp, META + "const unused = 1\n", META)
            code, _, by_id = self.ci(root, node_tools_env(tmp))
            self.assertEqual(code, 0)
            self.assertEqual(self.summary(by_id[self.CHECK_ID]),
                             ["passed", None, None, {"merge_base": base}])

    def test_existing_findings_level_with_the_merge_base_pass_ci(self) -> None:
        with fixture() as tmp:
            text = META + "const one = 1\nconst two = 2\n"
            root, _ = self.branch(tmp, text, text)
            (root / "README.txt").write_text("notes\n", encoding="utf-8")
            commit_all(root, "readme")
            code, _, by_id = self.ci(root, node_tools_env(tmp))
            self.assertEqual(code, 0)
            self.assertEqual(by_id[self.CHECK_ID]["status"], "passed")

    def test_a_new_bare_disable_comment_turns_ci_red_naming_node15(self) -> None:
        with fixture() as tmp:
            check = self.rose(tmp, META + "const unused = 1\n",
                              META + "// eslint-disable-next-line\nconst unused = 1\n")
            self.assertEqual(
                [check["facts"]["rule"], check["facts"]["violations"], check["facts"]["rules"]],
                ["NODE15", ["NODE15 src/p.js:2"], ["NODE15"]])

    def test_a_new_reasoned_disable_comment_passes_ci(self) -> None:
        with fixture() as tmp:
            root, _ = self.branch(
                tmp, META + "const unused = 1\n",
                META + "// eslint-disable-next-line no-unused-vars -- kept for the fixture\n"
                "const unused = 1\n")
            code, _, _ = self.ci(root, node_tools_env(tmp))
            self.assertEqual(code, 0)

    def test_a_branch_that_breaks_the_parse_turns_ci_red_naming_node11(self) -> None:
        with fixture() as tmp:
            check = self.rose(tmp, META, META + "const = 1\n")
            self.assertEqual([check["facts"]["rule"], check["facts"]["violations"]],
                             ["NODE11", ["NODE11 src/p.js:2"]])

    def test_a_branch_that_breaks_the_meta_declaration_turns_ci_red_naming_node11(self) -> None:
        with fixture() as tmp:
            check = self.rose(tmp, META, "export const = { name: 'fixture' }\n")
            facts = check["facts"]
            self.assertEqual(
                [facts["rule"], facts["base_count"], facts["branch_count"], facts["violations"]],
                ["NODE11", 0, 1, ["NODE11 src/p.js:1"]])

    def test_a_program_with_no_tool_record_is_a_failed_check(self) -> None:
        with fixture() as tmp:
            root, _ = self.branch(tmp, META, META)
            code, report, by_id = self.ci(root, HERMETIC_ENV)
            self.assertEqual(code, 1)
            self.assertEqual(
                self.summary(by_id[self.CHECK_ID]),
                ["failed", "enforcer_failed", "platform.enforcers.install",
                 {"tool": "node-tools", "reason": "record_unavailable"}])
            self.assertNotIn("node-tools.json", json.dumps(by_id[self.CHECK_ID]))
            self.assert_validates(report)

    def test_an_eslint_that_returns_no_result_is_a_failed_check(self) -> None:
        with fixture() as tmp:
            root, _ = self.branch(tmp, META, META)
            eslint = shim(tmp, "eslint", "printf '[]'\n")
            env = platform_env(tmp, node_tools={
                "schema_version": 1, "node": pinned_node_tools()["node"], "eslint": eslint})
            code, _, by_id = self.ci(root, env)
            self.assertEqual(code, 1)
            self.assertEqual(
                self.summary(by_id[self.CHECK_ID]),
                ["failed", "enforcer_failed", "platform.enforcers.install",
                 {"tool": "eslint", "reason": "unreadable_output"}])


RECORDER = """\
import hashlib, json, os, sys
name = os.path.basename(sys.argv[0])
digests = [hashlib.sha256(open(a, "rb").read()).hexdigest()
           for a in sys.argv[1:] if a.endswith(".cjs")]
with open(os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), name + ".jsonl"), "a") as out:
    out.write(json.dumps({"argv": sys.argv[1:], "digests": digests}) + "\\n")
os.execv(PINNED, [PINNED, *sys.argv[1:]])
"""


class ThisRepositoryNodeTest(unittest.TestCase):
    """This repository's two programs reach both tools, as the executable boundary shows."""

    PROGRAMS = ("home/common/claude-code/skills/deliver-standard/deliver-standard.js",
                "home/common/claude-code/skills/deliver-standard/deliver-batch.js")

    def recording(self, tmp: Path, name: str, pinned: str) -> str:
        path = tmp / name
        path.write_text(f"#!{sys.executable} -I\nPINNED = {pinned!r}\n" + RECORDER,
                        encoding="utf-8")
        path.chmod(0o755)
        return str(path)

    def calls(self, tmp: Path, name: str) -> list[dict]:
        log = tmp / f"{name}.jsonl"
        return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]

    def test_doctor_on_this_repository_lints_both_programs_with_both_tools(self) -> None:
        with fixture() as tmp:
            pinned = pinned_node_tools()
            env = platform_env(tmp, node_tools={
                "schema_version": 1,
                "node": self.recording(tmp, "node", pinned["node"]),
                "eslint": self.recording(tmp, "eslint", pinned["eslint"])})
            expected = {
                hashlib.sha256(node_lint.wrap(git(REPO_ROOT, "show", f"HEAD:{path}")).text
                               .encode()).hexdigest()
                for path in self.PROGRAMS}
            _, by_id = doctor(self, REPO_ROOT, "--offline", env=env)
            self.assertEqual(by_id["verification.violations.never_rise"]["status"], "passed")
            seen = lambda name, flag: {  # noqa: E731
                d for call in self.calls(tmp, name) if flag(call["argv"]) for d in call["digests"]}
            self.assertLessEqual(expected, seen(
                "node", lambda argv: argv[:1] == ["--check"]))
            self.assertLessEqual(expected, seen(
                "eslint", lambda argv: node_lint.CONFIG in argv))
            self.assertLessEqual(expected, seen(
                "eslint", lambda argv: node_lint.INLINE_CONFIG in argv))


if __name__ == "__main__":
    unittest.main()
