"""The Node adapter's contract: the adapter that judges Workflow programs
with `node --check` and ESLint, run from the platform's pinned tools directory.

The suite holds `standard:NODE11`, `standard:NODE12`, `standard:NODE13`,
`standard:NODE14` and `standard:NODE15` by judging their enforcer,
`agent_tools.delivery.node_lint`.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent_tools.delivery import never_rise, node_lint, rule_ids
from agent_tools.delivery.never_rise import EnforcerFailed, HistoryUnavailable, Violation

from .conformance_test_support import (
    HERMETIC_ENV, INTEGRATION_REF, REAL_GIT, REPO_ROOT, ReportAssertions, commit_all, doctor,
    fixture, git, make_root, run,
)

TIER = "integration"  # git worlds, the pinned node and eslint, the conformance engine

TOOLS = os.environ.get(node_lint.TOOLS_ENV)


def pinned(name: str) -> str:
    """The pinned tool `name` in the platform's tools directory; the case fails without one."""
    found = shutil.which(name, path=TOOLS) if TOOLS else None
    if found is None:
        raise AssertionError("run through just agent-workflow-tests, which sets AGENT_PLATFORM_TOOLS")
    return found


def tools_dir(case: unittest.TestCase, **replacing: str) -> str:
    """A tools directory linking every pinned tool, `replacing` a tool with a script body."""
    directory = Path(tempfile.mkdtemp(prefix="node-lint-tools-"))
    case.addCleanup(shutil.rmtree, directory, True)
    for entry in Path(TOOLS or "/nonexistent").iterdir():
        (directory / entry.name).symlink_to(entry)
    for name, script in replacing.items():
        (directory / name).unlink()
        (directory / name).write_text("#!/bin/sh\n" + script, encoding="utf-8")
        (directory / name).chmod(0o755)
    return str(directory)


def tools_env(directory: str | None) -> dict:
    """The conformance run's environment with the tools directory set to `directory`, or unset."""
    environment = {k: v for k, v in HERMETIC_ENV.items() if k != node_lint.TOOLS_ENV}
    if directory:
        environment[node_lint.TOOLS_ENV] = directory
    return environment


def using(directory: str | None):
    """The environment with `node_lint.TOOLS_ENV` set to `directory`, or unset."""
    environment = {k: v for k, v in os.environ.items() if k != node_lint.TOOLS_ENV}
    if directory:
        environment[node_lint.TOOLS_ENV] = directory
    return mock.patch.dict(os.environ, environment, clear=True)


META = "export const meta = { name: 'fixture' }\n"


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


def run_command(root: Path, tools: str | None, *args: str) -> subprocess.CompletedProcess:
    env = {"HOME": str(root.parent), "LANG": "C", "PYTHONPATH": HERMETIC_ENV["PYTHONPATH"],
           "PATH": os.pathsep.join(["/usr/bin", "/bin", str(Path(REAL_GIT).parent)]),
           **({node_lint.TOOLS_ENV: tools} if tools else {})}
    return subprocess.run(
        [sys.executable, "-m", "agent_tools.delivery.node_lint", "--repo-root", str(root), *args],
        env=env, capture_output=True, text=True, timeout=120)


class NodeLintCommandTest(unittest.TestCase):
    """The `node-lint` command, run as a child process."""

    def test_an_unused_variable_in_a_program_prints_one_node12_line(self) -> None:
        with fixture() as tmp:
            root, _ = make_repo(tmp, {"prog/one.js": META + "const unused = 1\n"})
            proc = run_command(root, TOOLS)
        self.assertEqual((proc.returncode, proc.stdout), (1, "NODE12 prog/one.js:2\n"), proc.stderr)

    def test_a_clean_program_exits_zero(self) -> None:
        with fixture() as tmp:
            root, _ = make_repo(tmp, {"prog/one.js": META})
            proc = run_command(root, TOOLS)
        self.assertEqual((proc.returncode, proc.stdout), (0, ""), proc.stderr)

    def test_a_program_with_no_tools_directory_is_a_usage_error(self) -> None:
        with fixture() as tmp:
            root, _ = make_repo(tmp, {"prog/one.js": META})
            proc = run_command(root, None)
        self.assertEqual((proc.returncode, proc.stdout, proc.stderr),
                         (2, "", "node-lint: tools_unavailable\n"))

    def test_a_relative_root_is_a_usage_error(self) -> None:
        proc = run_command(Path("rel"), TOOLS)
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
        with using(TOOLS):
            cls.found = node_lint.lint_files(files, 120)

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
        with fixture() as tmp, using(TOOLS):
            root, first = make_repo(tmp, {"src/p.js": META})
            (root / "src/p.js").write_text("export const = { name: 'fixture' }\n", encoding="utf-8")
            commit_all(root, "break the meta line")
            second = git(root, "rev-parse", "HEAD").strip()

            def node11(also: tuple[str, ...]) -> never_rise.Enforcer:
                return [e for e in node_lint.enforcers(also) if e.rule == "NODE11"][0]

            snapshot = self.snapshot(root, second)
            self.assertEqual(node11((first, second)).find(snapshot), [Violation("NODE11", "src/p.js", 1)])
            self.assertEqual(node11(()).find(snapshot), [])

    def test_a_revision_with_no_program_never_needs_the_tools(self) -> None:
        with fixture() as tmp, using(None):
            root, head = make_repo(tmp, {"lib/x.js": "const unused = 1\n"})
            for enforcer in node_lint.enforcers():
                self.assertEqual(never_rise.counted(enforcer, self.snapshot(root, head)), ([], []))

    def test_the_five_enforcers_share_one_run_per_revision(self) -> None:
        with fixture() as tmp, using(TOOLS):
            root, head = make_repo(tmp, {"p.js": self.UNUSED})
            snapshot = self.snapshot(root, head)
            with mock.patch.object(node_lint, "lint_files", wraps=node_lint.lint_files) as spy:
                found = {e.rule: e.find(snapshot) for e in node_lint.enforcers()}
        self.assertEqual(spy.call_count, 1)
        self.assertEqual(sorted(found), list(node_lint.RULES))
        self.assertEqual(found["NODE12"], [Violation("NODE12", "p.js", 2)])

    def test_a_tools_directory_that_is_unusable_is_a_closed_failure(self) -> None:
        without_node = tempfile.mkdtemp(prefix="node-lint-tools-")
        self.addCleanup(shutil.rmtree, without_node, True)
        for name, directory in (("unset", None), ("relative", "tools"), ("empty", without_node)):
            with self.subTest(name), fixture() as tmp, using(directory):
                root, head = make_repo(tmp, {"p.js": META})
                with self.assertRaises(EnforcerFailed) as caught:
                    node_lint.enforcers()[0].find(self.snapshot(root, head))
                self.assertEqual((caught.exception.enforcer, caught.exception.reason),
                                 ("node-lint", "tools_unavailable"))

    def test_a_tool_that_cannot_run_or_runs_too_long_is_a_closed_failure(self) -> None:
        cases = {
            "node": ("exit 3\n", "node_failed"),
            "eslint": ("exit 2\n", "eslint_failed"),
        }
        for tool, (script, reason) in cases.items():
            with self.subTest(tool), using(tools_dir(self, **{tool: script})):
                with self.assertRaises(EnforcerFailed) as caught:
                    node_lint.lint_files({"p.js": META}, 60)
                self.assertEqual(caught.exception.reason, reason)
        with using(tools_dir(self, eslint="while :; do :; done\n")):
            with self.assertRaises(EnforcerFailed) as caught:
                node_lint.lint_files({"p.js": META}, 1)
        self.assertEqual(caught.exception.reason, "eslint_failed")

    def test_a_failed_git_read_of_another_revision_is_history_unavailable(self) -> None:
        with fixture() as tmp, using(TOOLS):
            root, head = make_repo(tmp, {"p.js": META})
            snapshot = self.snapshot(root, head)
            with self.assertRaises(HistoryUnavailable):
                node_lint.enforcers(("0" * 40,))[0].find(snapshot)

    def test_the_tools_run_with_only_path_home_and_lang(self) -> None:
        polluted = {"NODE_OPTIONS": "--require /nonexistent", "ESLINT_USE_FLAT_CONFIG": "false"}
        with using(TOOLS), mock.patch.dict(os.environ, polluted), \
                mock.patch.object(node_lint.subprocess, "run", wraps=subprocess.run) as spy:
            found = node_lint.lint_files({"p.js": self.UNUSED}, 60)
        self.assertEqual([(v.rule, v.line) for v in found], [("NODE12", 2)])
        self.assertTrue(spy.call_args_list)
        for call in spy.call_args_list:
            self.assertEqual(set(call.kwargs["env"]), {"PATH", "HOME", "LANG"})
            self.assertEqual(call.kwargs["env"]["PATH"], TOOLS)
            self.assertIn(call.args[0][0], ("node", "eslint"))


class NodeToolOutputTest(unittest.TestCase):
    """Incomplete or malformed tool output fails closed."""

    def fails(self, directory: str, reason: str) -> None:
        with using(directory), self.assertRaises(EnforcerFailed) as caught:
            node_lint.lint_files({"p.js": "export const meta = {}\n"}, 60)
        self.assertEqual((caught.exception.enforcer, caught.exception.reason), ("node-lint", reason))

    def test_an_eslint_result_list_missing_a_file_is_a_closed_failure(self) -> None:
        self.fails(tools_dir(self, eslint="printf '[]'\n"), "eslint_output_unreadable")

    def test_an_eslint_result_without_a_file_path_is_a_closed_failure(self) -> None:
        self.fails(tools_dir(self, eslint="printf '[{\"messages\": []}]'\nexit 1\n"),
                   "eslint_output_unreadable")

    def test_a_message_without_a_line_is_a_closed_failure(self) -> None:
        script = ("printf '[{\"filePath\": \"p0.cjs\", \"messages\": "
                  "[{\"ruleId\": \"no-undef\", \"message\": \"x\"}]}]'\nexit 1\n")
        self.fails(tools_dir(self, eslint=script), "eslint_output_unreadable")

    def test_a_node_syntax_exit_without_a_diagnostic_is_a_closed_failure(self) -> None:
        self.fails(tools_dir(self, node="printf 'garbage' >&2\nexit 1\n"), "node_output_unreadable")


class NodeRuleMappingTest(unittest.TestCase):
    """The mapping is the pinned ESLint's recommended set, under the shard's rule ids."""

    def test_the_mapping_is_the_recommended_set_of_the_pinned_eslint(self) -> None:
        eslint = os.path.realpath(pinned("eslint"))
        recommended = (Path(eslint).parents[1] / "lib/node_modules/eslint/node_modules"
                       / "@eslint/js/src/configs/eslint-recommended.js")
        out = subprocess.run(
            [pinned("node"), "-e",
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
        code, report, by_id = self.ci(root, tools_env(TOOLS))
        self.assertEqual(code, 1)
        self.assert_validates(report)
        return by_id[self.CHECK_ID]

    def test_a_branch_that_adds_an_unused_variable_to_a_program_turns_ci_red_naming_node12_and_the_line(self) -> None:
        with fixture() as tmp:
            root, base = self.branch(tmp, META, META + "const unused = 1\n")
            code, report, by_id = self.ci(root, tools_env(TOOLS))
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
            code, _, by_id = self.ci(root, tools_env(TOOLS))
            self.assertEqual(code, 0)
            self.assertEqual(self.summary(by_id[self.CHECK_ID]),
                             ["passed", None, None, {"merge_base": base}])

    def test_existing_findings_level_with_the_merge_base_pass_ci(self) -> None:
        with fixture() as tmp:
            text = META + "const one = 1\nconst two = 2\n"
            root, _ = self.branch(tmp, text, text)
            (root / "README.txt").write_text("notes\n", encoding="utf-8")
            commit_all(root, "readme")
            code, _, by_id = self.ci(root, tools_env(TOOLS))
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
            code, _, _ = self.ci(root, tools_env(TOOLS))
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

    def test_a_program_with_no_tools_directory_is_a_failed_check(self) -> None:
        with fixture() as tmp:
            root, _ = self.branch(tmp, META, META)
            code, report, by_id = self.ci(root, tools_env(None))
            self.assertEqual(code, 1)
            self.assertEqual(
                self.summary(by_id[self.CHECK_ID]),
                ["failed", "enforcer_failed", "violations.enforcer.repair",
                 {"enforcer": "node-lint", "reason": "tools_unavailable"}])
            self.assert_validates(report)

    def test_an_eslint_that_returns_no_result_is_a_failed_check(self) -> None:
        with fixture() as tmp:
            root, _ = self.branch(tmp, META, META)
            code, _, by_id = self.ci(root, tools_env(tools_dir(self, eslint="printf '[]'\n")))
            self.assertEqual(code, 1)
            self.assertEqual(
                self.summary(by_id[self.CHECK_ID]),
                ["failed", "enforcer_failed", "violations.enforcer.repair",
                 {"enforcer": "node-lint", "reason": "eslint_output_unreadable"}])


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

    def recording_tools(self, tmp: Path) -> str:
        """A tools directory whose `node` and `eslint` record their arguments, then run the pinned ones."""
        directory = Path(tools_dir(self))
        for name in ("node", "eslint"):
            path = directory / name
            path.unlink()
            path.write_text(f"#!{sys.executable} -I\nPINNED = {pinned(name)!r}\n" + RECORDER,
                            encoding="utf-8")
            path.chmod(0o755)
        return str(directory)

    def calls(self, directory: str, name: str) -> list[dict]:
        log = Path(directory) / f"{name}.jsonl"
        return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]

    def never_rise_check(self, directory: str) -> dict:
        """The doctor's never-rise check on this repository, run with the tools in `directory`."""
        _, by_id = doctor(self, REPO_ROOT, "--offline", env=tools_env(directory))
        return by_id["verification.violations.never_rise"]

    def assert_never_rise_passed(self, check: dict) -> None:
        self.assertEqual(check["status"], "passed", check)

    def test_doctor_on_this_repository_lints_both_programs_with_both_tools(self) -> None:
        with fixture() as tmp:
            directory = self.recording_tools(tmp)
            expected = {
                hashlib.sha256(node_lint.wrap(git(REPO_ROOT, "show", f"HEAD:{path}")).text
                               .encode()).hexdigest()
                for path in self.PROGRAMS}
            self.assert_never_rise_passed(self.never_rise_check(directory))
            seen =lambda name, flag: {  # noqa: E731
                d for call in self.calls(directory, name) if flag(call["argv"]) for d in call["digests"]}
            self.assertLessEqual(expected, seen(
                "node", lambda argv: argv[:1] == ["--check"]))
            self.assertLessEqual(expected, seen(
                "eslint", lambda argv: node_lint.CONFIG in argv))
            self.assertLessEqual(expected, seen(
                "eslint", lambda argv: node_lint.INLINE_CONFIG in argv))

    def test_the_doctor_test_fails_when_the_doctor_reports_a_broken_tool(self) -> None:
        broken = {"node": ("exit 3\n", "node_failed"), "eslint": ("exit 2\n", "eslint_failed")}
        for tool, (script, reason) in broken.items():
            with self.subTest(tool):
                check = self.never_rise_check(tools_dir(self, **{tool: script}))
                self.assertEqual(
                    [check["status"], check["reason_code"], check["facts"]],
                    ["failed", "enforcer_failed", {"enforcer": "node-lint", "reason": reason}])
                with self.assertRaises(AssertionError):
                    self.assert_never_rise_passed(check)

    def test_doctor_on_a_runner_that_takes_over_a_minute_still_completes(self) -> None:
        slowed = {name: f'/bin/sleep 10\nexec {pinned(name)} "$@"\n' for name in ("node", "eslint")}
        directory = tools_dir(self, **slowed)
        self.assert_never_rise_passed(self.never_rise_check(directory))


if __name__ == "__main__":
    unittest.main()
