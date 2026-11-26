"""The touched-test selector and the `test-touched` recipe (ADR-delivery-012).

`agent_tools.delivery.touched_tests` selects the agent workflow suite's members a branch
touches, builds the host first when a build input changed, and runs the selection through
the suite runner. `SelectTest` and `BuildTriggerTest` run the pure functions on fixtures,
`SelectionTableTest` pins the selection each kind of diff gets, `MainTest` runs `main` against a real temporary git repository with a recording stub for
every command it would start, and `RecipeTest` reads the repository's justfile.
"""

import contextlib
import fnmatch
import importlib
import io
import json
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent_tools.delivery import comment_lint
from agent_tools.delivery.never_rise import Snapshot
from agent_tools.delivery.suite_runner import REPORT_ENV, suite_members
from agent_tools.delivery.touched_tests import (
    SELECTION_ENV, build_trigger, default_capture, default_execute, main, parse_assignments,
    select, selection)

TIER = "integration"  # MainTest builds a git repository

REPO_ROOT = Path(__file__).resolve().parents[1]
# Real module paths are assembled from this prefix, never spelled out whole: the selector
# selects any member whose text contains a changed path, so a literal real path here would
# make every diff touching that module run this file as well as the engine tier.
DELIVERY = "python/agent_tools/delivery"
RUNNER = [sys.executable, "-m", "agent_tools.delivery.suite_runner"]


def reader(texts):
    def read(path):
        return texts.get(path, "")
    return read


def hermetic_env(environ):
    env = {k: v for k, v in environ.items()
           if not k.startswith("GIT_") and k != SELECTION_ENV}
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull,
               GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid")
    return env


class SelectTest(unittest.TestCase):
    def test_a_changed_module_selects_its_test_files_and_its_importers(self):
        members = ["tests/test_alpha.py", "tests/test_alpha_cli.py",
                   "tests/test_beta.py", "tests/test_gamma.py"]
        read = reader({"tests/test_beta.py": "from pkg.alpha import run\n",
                       "tests/test_gamma.py": "import pkg.alphabet\n# pkg.alpha\n"})
        self.assertEqual(
            select(["python/pkg/alpha.py"], members, read, source_roots=["python"]),
            ["tests/test_alpha.py", "tests/test_alpha_cli.py", "tests/test_beta.py"])

    def test_each_import_form_selects_the_importer(self):
        for text, selected in [
            ("import pkg.alpha\n", True),
            ("import pkg.alpha as a\n", True),
            ("from pkg import alpha\n", True),
            ("from pkg.alpha import x\n", True),
            ("from pkg import alphabet\n", False),
            ('x = "pkg.alpha"\n', False),
        ]:
            with self.subTest(text=text):
                result = select(["python/pkg/alpha.py"], ["tests/test_user.py"],
                                reader({"tests/test_user.py": text}), source_roots=["python"])
                self.assertEqual(result, ["tests/test_user.py"] if selected else [])

    def test_a_changed_or_added_test_file_selects_itself(self):
        members = ["tests/test_beta.py", "tests/test_gamma.py"]
        self.assertEqual(select(["tests/test_gamma.py"], members, reader({})),
                         ["tests/test_gamma.py"])

    def test_a_path_reference_selects_a_path_loaded_test(self):
        members = ["tests/test_prog_program.py"]
        read = reader({"tests/test_prog_program.py": 'PROGRAM = "home/x/prog.js"\n'})
        self.assertEqual(select(["home/x/prog.js"], members, read),
                         ["tests/test_prog_program.py"])
        members = ["home/t/test_h.py", "tests/test_other.py"]
        text = 'with_name("harness.mjs")\n'
        read = reader({"home/t/test_h.py": text, "tests/test_other.py": text})
        self.assertEqual(select(["home/t/harness.mjs"], members, read), ["home/t/test_h.py"])

    def test_a_guard_change_adds_its_paired_table_even_outside_the_suite(self):
        pairs = {"g/guard.py": ["tests/test_guard_table.py"]}
        members = ["tests/test_other.py"]
        self.assertIn("tests/test_guard_table.py",
                      select(["g/guard.py"], members, reader({}), pairs=pairs))
        self.assertNotIn("tests/test_guard_table.py",
                         select(["g/other.py"], members, reader({}), pairs=pairs))

    def test_a_nightly_or_unregistered_test_is_never_selected(self):
        self.assertEqual(select(["tests/test_slow.py"], ["tests/test_fast.py"], reader({})), [])

    def test_the_selection_keeps_member_order_without_duplicates(self):
        members = ["tests/test_zed.py", "tests/test_alpha.py"]
        read = reader({"tests/test_alpha.py":
                       'import pkg.alpha\nPATH = "tests/test_alpha.py"\n'})
        result = select(["tests/test_alpha.py", "python/pkg/alpha.py", "tests/test_zed.py"],
                        members, read, source_roots=["python"])
        self.assertEqual(result, ["tests/test_zed.py", "tests/test_alpha.py"])


class SelectionTableTest(unittest.TestCase):
    MEMBERS = ["tests/test_engine_alpha.py", "tests/test_engine_beta.py",
               "tests/test_engine_gamma.py", "tests/test_touched_tests.py",
               "tests/test_unrelated.py"]
    TEXTS = {
        "tests/test_engine_beta.py": "from agent_tools.delivery import engine_beta\n",
        "tests/test_engine_gamma.py": "from tests.engine_gamma_world import GammaRun\n",
        "tests/test_touched_tests.py": "from agent_tools.delivery.touched_tests import main\n",
        "tests/test_unrelated.py": "import json\n",
    }
    COVERS = {"python/agent_tools/delivery/engine*.py": ["tests/test_engine_*.py"],
              "python/agent_tools/delivery/procedure_zeta.py": ["tests/test_engine_*.py"]}
    PAIRS = {"home/common/claude-code/lifecycle_guard.py": ["tests/test_claude_permission_guard.py"]}
    ENGINE_TIER = ["tests/test_engine_alpha.py", "tests/test_engine_beta.py",
                   "tests/test_engine_gamma.py"]

    def test_each_diff_selects_its_row(self):
        everything = self.MEMBERS
        rows = {
            "engine module and its test": (
                ["python/agent_tools/delivery/engine_alpha.py", "tests/test_engine_alpha.py"],
                False, [], self.ENGINE_TIER),
            "a file CI cannot test": (["hosts/m.nix"], True, ["hosts/m.nix"], everything),
            "a file CI cannot test beside an engine module": (
                ["hosts/m.nix", "python/agent_tools/delivery/engine_beta.py"],
                True, ["hosts/m.nix"], everything),
            "a file CI cannot test beside the guard": (
                ["hosts/m.nix", "home/common/claude-code/lifecycle_guard.py"],
                True, ["hosts/m.nix"], everything + ["tests/test_claude_permission_guard.py"]),
            "nothing a member covers": (["docs/notes.md"], False, [], []),
            "a module outside the engine": (
                ["python/agent_tools/delivery/touched_tests.py"],
                False, [], ["tests/test_touched_tests.py"]),
            "an engine module outside engine*.py and its test": (
                ["python/agent_tools/delivery/procedure_zeta.py", "tests/test_engine_alpha.py"],
                False, [], self.ENGINE_TIER),
        }
        for name, (changed, full, because, selected) in rows.items():
            with self.subTest(row=name):
                self.assertEqual(
                    selection(changed, self.MEMBERS, reader(self.TEXTS),
                              source_roots=["python"], pairs=self.PAIRS, covers=self.COVERS,
                              build_globs=["*.nix"]),
                    {"changed": changed, "full": full, "full_because": because,
                     "selected": selected})


class BuildTriggerTest(unittest.TestCase):
    def test_a_build_glob_matches_nested_paths(self):
        self.assertEqual(build_trigger(["hosts/darwin/m/default.nix"], ["*.nix"]),
                         "hosts/darwin/m/default.nix")
        self.assertEqual(build_trigger(["data/zshrc/common/50-x"], ["data/*"]),
                         "data/zshrc/common/50-x")
        self.assertIsNone(build_trigger(["docs/a.md"], ["*.nix", "data/*"]))


class MainTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.env = hermetic_env(os.environ)
        patcher = mock.patch.dict(os.environ, self.env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.git("init", "-q", "-b", "main")
        self.write("justfile", "agent-workflow-tests *args:\n  runner {{args}} \\\n"
                               "    tests/test_alpha.py \\\n    tests/test_beta.py\n")
        self.write("tests/test_alpha.py", "from pkg import alpha\n")
        self.write("tests/test_beta.py", "import json\n")
        self.write("python/pkg/alpha.py", "VALUE = 1\n")
        self.write("hosts/m.nix", "{ }\n")
        self.commit("first")
        self.write("python/pkg/alpha.py", "VALUE = 2\n")
        self.write("hosts/m.nix", "{ a = 1; }\n")
        self.commit("second")
        self.calls = []
        self.environments = []

    def git(self, *args):
        subprocess.run(["git", "-C", str(self.root), *args], check=True,
                       capture_output=True, text=True)

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def commit(self, message):
        self.git("add", "-A")
        self.git("-c", "commit.gpgsign=false", "commit", "-q", "-m", message)

    def stub(self, codes=None):
        codes = codes or {}

        def execute(argv, cwd, env=None):
            self.calls.append((argv, cwd))
            self.environments.append(env)
            return codes.get(argv[0], codes.get("runner", 0))
        return execute

    def capturing(self, output="", code=0):
        def capture(argv, cwd):
            self.calls.append((argv, cwd))
            self.environments.append(None)
            return code, output
        return capture

    def run_main(self, *args, execute=None, capture=None):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["--root", str(self.root), *args], execute=execute or self.stub(),
                        capture=capture or self.capturing())
        return code, out.getvalue(), err.getvalue()

    def test_the_cli_runs_the_selected_members_through_the_suite_runner(self):
        code, _, _ = self.run_main("--base", "HEAD~1", "--source-root", "python",
                                   execute=self.stub({"runner": 3}))
        self.assertEqual(self.calls, [([*RUNNER, "tests/test_alpha.py"], self.root)])
        self.assertEqual(code, 3)

    def test_a_build_input_change_builds_and_runs_every_member(self):
        code, _, err = self.run_main("--base", "HEAD~1", "--source-root", "python",
                                     "--build-command", "just build", "--build-when", "*.nix")
        self.assertEqual([argv for argv, _ in self.calls],
                         [["just", "build"], [*RUNNER, "tests/test_alpha.py", "tests/test_beta.py"]])
        self.assertIn("hosts/m.nix", err)
        self.assertEqual(code, 0)

    def test_main_writes_the_selection_to_the_file_the_variable_names(self):
        out = self.root / "selection.json"
        with mock.patch.dict(os.environ, {SELECTION_ENV: str(out)}):
            self.run_main("--base", "HEAD~1", "--source-root", "python")
        self.assertEqual(json.loads(out.read_text()),
                         {"base": "HEAD~1", "changed": ["hosts/m.nix", "python/pkg/alpha.py"],
                          "full": False, "full_because": [], "selected": ["tests/test_alpha.py"]})

    def test_the_suite_file_flag_reads_the_members_from_that_file(self):
        self.write("suite.just", "agent-workflow-tests *args:\n  runner {{args}} \\\n"
                                 "    tests/test_gamma.py\n")
        self.write("tests/test_gamma.py", "from pkg import alpha\n")
        self.run_main("--base", "HEAD~1", "--source-root", "python",
                      "--suite-file", "suite.just")
        self.assertEqual([argv for argv, _ in self.calls], [[*RUNNER, "tests/test_gamma.py"]])

    def test_an_empty_selection_is_still_written(self):
        out = self.root / "selection.json"
        with mock.patch.dict(os.environ, {SELECTION_ENV: str(out)}):
            code, _, _ = self.run_main("--base", "HEAD", "--source-root", "python")
        document = json.loads(out.read_text())
        self.assertEqual(code, 0)
        self.assertEqual(self.calls, [])
        self.assertEqual((document["selected"], document["changed"]), ([], []))

    def test_a_selection_that_cannot_be_written_changes_no_exit(self):
        out = self.root / "missing" / "selection.json"
        with mock.patch.dict(os.environ, {SELECTION_ENV: str(out)}):
            code, _, err = self.run_main("--base", "HEAD~1", "--source-root", "python")
        self.assertEqual(code, 0)
        self.assertIn("test-touched: cannot write the selection to", err)

    def test_a_cover_without_an_equals_sign_is_a_usage_error(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            main(["--base", "HEAD", "--root", str(self.root), "--cover", "a.py"])
        self.assertEqual(raised.exception.code, 2)

    def test_the_commands_main_starts_do_not_see_the_selection_variable(self):
        probe = "import os, sys; sys.exit(3 if 'VERIFIED_TREE_SELECTION' in os.environ else 0)"
        with mock.patch.dict(os.environ, {SELECTION_ENV: str(self.root / "selection.json")}):
            code = default_execute([sys.executable, "-c", probe], self.root)
        self.assertEqual(code, 0)

    def test_the_hermetic_environment_drops_the_selection_variable(self):
        env = hermetic_env({"VERIFIED_TREE_SELECTION": "x", "GIT_DIR": "y", "HOME": "h"})
        self.assertNotIn("VERIFIED_TREE_SELECTION", env)
        self.assertNotIn("GIT_DIR", env)
        self.assertEqual(env["HOME"], "h")

    def test_a_failed_build_stops_before_the_suite(self):
        code, _, _ = self.run_main("--base", "HEAD~1", "--source-root", "python",
                                   "--build-command", "just build", "--build-when", "*.nix",
                                   execute=self.stub({"just": 1}))
        self.assertEqual(code, 1)
        self.assertEqual([argv for argv, _ in self.calls], [["just", "build"]])

    def test_no_build_input_changed_runs_no_build(self):
        self.run_main("--base", "HEAD~1", "--source-root", "python",
                      "--build-command", "just build", "--build-when", "flake.lock")
        self.assertNotIn(["just", "build"], [argv for argv, _ in self.calls])

    def test_no_touched_member_runs_nothing_and_passes(self):
        code, out, _ = self.run_main("--base", "HEAD", "--source-root", "python")
        self.assertEqual(code, 0)
        self.assertEqual(self.calls, [])
        self.assertIn("test-touched: no suite member is touched by HEAD...HEAD", out)

    def test_an_unknown_base_is_a_usage_error(self):
        code, _, _ = self.run_main("--base", "nope")
        self.assertEqual(code, 2)

    def test_a_pair_without_an_equals_sign_is_a_usage_error(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            main(["--base", "HEAD", "--root", str(self.root), "--pair", "a.py"])
        self.assertEqual(raised.exception.code, 2)

    def test_a_build_glob_without_a_build_command_is_a_usage_error(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            main(["--base", "HEAD", "--root", str(self.root), "--build-when", "*.nix"])
        self.assertEqual(raised.exception.code, 2)


    ENV_FLAGS = ("--source-root", "python", "--build-command", "just build",
                 "--env-from", "tests/test_alpha.py=just env")
    ENV_OUTPUT = "FIRST_PATH=/store/first\nSECOND_PATH=/store/second\n"

    def test_a_selected_env_member_builds_then_runs_with_the_variables_the_command_prints(self):
        code, _, _ = self.run_main("--base", "HEAD~1", *self.ENV_FLAGS,
                                   capture=self.capturing(self.ENV_OUTPUT))
        self.assertEqual(self.calls, [(["just", "build"], self.root),
                                      (["just", "env"], self.root),
                                      ([*RUNNER, "tests/test_alpha.py"], self.root)])
        self.assertEqual(self.environments[2],
                         {"FIRST_PATH": "/store/first", "SECOND_PATH": "/store/second"})
        self.assertEqual(code, 0)

    def test_no_env_member_selected_runs_no_build_and_no_env_command(self):
        self.run_main("--base", "HEAD~1", "--source-root", "python", "--build-command",
                      "just build", "--env-from", "tests/test_beta.py=just env")
        self.assertEqual(self.calls, [([*RUNNER, "tests/test_alpha.py"], self.root)])
        self.assertEqual(self.environments, [None])

    def test_a_full_selection_builds_once_and_only_the_env_member_gets_the_variables(self):
        self.run_main("--base", "HEAD~1", *self.ENV_FLAGS, "--build-when", "*.nix",
                      capture=self.capturing(self.ENV_OUTPUT))
        self.assertEqual([argv for argv, _ in self.calls],
                         [["just", "build"], ["just", "env"],
                          [*RUNNER, "tests/test_beta.py"], [*RUNNER, "tests/test_alpha.py"]])
        self.assertIsNone(self.environments[2])
        self.assertEqual(self.environments[3]["FIRST_PATH"], "/store/first")

    def test_a_failed_build_stops_before_the_env_command(self):
        code, _, _ = self.run_main("--base", "HEAD~1", *self.ENV_FLAGS,
                                   execute=self.stub({"just": 4}))
        self.assertEqual(code, 4)
        self.assertEqual([argv for argv, _ in self.calls], [["just", "build"]])

    def test_a_failed_env_command_stops_before_the_suite(self):
        code, _, _ = self.run_main("--base", "HEAD~1", *self.ENV_FLAGS,
                                   capture=self.capturing("", 5))
        self.assertEqual(code, 5)
        self.assertEqual([argv for argv, _ in self.calls], [["just", "build"], ["just", "env"]])

    def test_an_env_command_line_that_is_no_assignment_stops_before_the_suite(self):
        code, _, err = self.run_main("--base", "HEAD~1", *self.ENV_FLAGS,
                                     capture=self.capturing("not an assignment\n"))
        self.assertEqual(code, 2)
        self.assertIn("not an assignment", err)
        self.assertNotIn([*RUNNER, "tests/test_alpha.py"], [argv for argv, _ in self.calls])

    def test_a_failing_plain_member_does_not_skip_the_env_member(self):
        code, _, _ = self.run_main("--base", "HEAD~1", *self.ENV_FLAGS, "--build-when", "*.nix",
                                   execute=self.stub({"just": 0, "runner": 3}),
                                   capture=self.capturing(self.ENV_OUTPUT))
        self.assertEqual(code, 3)
        self.assertEqual(len([a for a, _ in self.calls if a[:3] == RUNNER]), 2)

    @staticmethod
    def report(member, seconds, passed):
        return {"version": 1, "members": 1, "passed": int(passed), "failed": int(not passed),
                "jobs": 1, "wall_seconds": seconds, "member_seconds": seconds,
                "cpu_seconds": seconds,
                "timings": [{"member": member, "seconds": seconds, "cpu_seconds": seconds,
                             "passed": passed}]}

    def reporting(self, failing):
        def execute(argv, cwd, env=None):
            self.calls.append((argv, cwd))
            if argv[:3] != RUNNER:
                return 0
            member = argv[-1]
            if env and REPORT_ENV in env:
                Path(env[REPORT_ENV]).write_text(
                    json.dumps(self.report(member, 2.0 if member == failing else 1.0,
                                           member != failing)), encoding="utf-8")
            return 3 if member == failing else 0
        return execute

    def test_a_mixed_selection_leaves_one_report_covering_both_runs(self):
        with mock.patch.dict(os.environ, {REPORT_ENV: "out/report.json"}):
            code, _, _ = self.run_main("--base", "HEAD~1", *self.ENV_FLAGS,
                                       "--build-when", "*.nix",
                                       execute=self.reporting("tests/test_beta.py"),
                                       capture=self.capturing(self.ENV_OUTPUT))
        merged = json.loads((self.root / "out/report.json").read_text(encoding="utf-8"))
        self.assertEqual(code, 3)
        self.assertEqual((merged["members"], merged["passed"], merged["failed"]), (2, 1, 1))
        self.assertEqual([(row["member"], row["passed"]) for row in merged["timings"]],
                         [("tests/test_beta.py", False), ("tests/test_alpha.py", True)])
        self.assertEqual((merged["member_seconds"], merged["wall_seconds"]), (3.0, 3.0))

    def test_a_single_run_keeps_the_report_path_it_was_given(self):
        with mock.patch.dict(os.environ, {REPORT_ENV: "out/report.json"}):
            self.run_main("--base", "HEAD~1", "--source-root", "python")
        self.assertEqual(self.environments, [None])

    def test_an_env_member_without_a_build_command_is_a_usage_error(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            main(["--base", "HEAD", "--root", str(self.root),
                  "--env-from", "tests/test_alpha.py=just env"])
        self.assertEqual(raised.exception.code, 2)

    def test_the_default_runner_adds_the_environment_to_the_inherited_one(self):
        probe = "import os, sys; sys.exit(0 if os.environ.get('ADDED') == 'yes' else 3)"
        code = default_execute([sys.executable, "-c", probe], self.root, {"ADDED": "yes"})
        self.assertEqual(code, 0)

    def test_the_default_capture_returns_the_exit_code_and_stdout(self):
        code, out = default_capture([sys.executable, "-c", "print('A=1')"], self.root)
        self.assertEqual((code, out), (0, "A=1\n"))


class RecipeTest(unittest.TestCase):
    def setUp(self):
        self.justfile = (REPO_ROOT / "justfile").read_text(encoding="utf-8")
        start = self.justfile.index("\ntest-touched:\n")
        end = self.justfile.find("\n\n", start + 1)
        self.recipe = self.justfile[start:end]

    def test_the_recipe_pairs_the_lifecycle_guard_with_its_adversarial_table(self):
        guard = "home/common/claude-code/lifecycle_guard.py"
        table = "tests/test_claude_permission_guard.py"
        self.assertIn("python3 -m agent_tools.delivery.touched_tests", self.recipe)
        self.assertIn(f"--pair {guard}={table}", self.recipe)
        self.assertIn("--source-root python", self.recipe)
        self.assertTrue((REPO_ROOT / guard).is_file())
        self.assertTrue((REPO_ROOT / table).is_file())

    def test_the_recipe_builds_the_host_when_a_build_input_changes(self):
        self.assertIn("--build-command 'just build'", self.recipe)
        self.assertIn("--build-when '*.nix'", self.recipe)
        self.assertIn("--build-when flake.lock", self.recipe)
        self.assertIn("build target_host=hostname", self.justfile)

    def test_the_recipe_runs_the_guard_test_with_the_variables_a_fresh_build_gives(self):
        guard_test = "tests/test_claude_permission_guard.py"
        self.assertIn(f"--env-from '{guard_test}=just claude-guard-test-env'", self.recipe)
        start = self.justfile.index("\nclaude-guard-test-env:\n")
        helper = self.justfile[start:self.justfile.find("\n\n", start + 1)]
        for variable in ("CLAUDE_SETTINGS_PATH", "CLAUDE_GUARD_BASE_POLICY_PATH"):
            self.assertIn(variable, helper)
            self.assertIn(variable, (REPO_ROOT / guard_test).read_text(encoding="utf-8"))

    def test_the_helper_comment_stays_within_the_comment_length_rule(self):
        data = self.justfile.encode("utf-8")
        snapshot = Snapshot("HEAD", {}, contents={"justfile": data})
        length = next(e for e in comment_lint.enforcers(None) if e.rule == comment_lint.LENGTH_RULE)
        recipe_line = self.justfile[:self.justfile.index("\nclaude-guard-test-env:\n")].count("\n") + 1
        self.assertNotIn(recipe_line, [v.line for v in length.find(snapshot)])

    def test_the_helper_prints_the_settings_and_the_base_policy_under_their_own_names(self):
        store = "/nix/store/h1-"
        listing = [f"{store}other", f"{store}claude-code-settings.json",
                   f"{store}claude-bash-lifecycle-guard-base-policy.json"]
        with tempfile.TemporaryDirectory() as scratch:
            bin_dir = Path(scratch) / "bin"
            bin_dir.mkdir()
            fake = bin_dir / "nix-store"
            fake.write_text("#!/bin/sh\ncat <<'EOF'\n" + "\n".join(listing) + "\nEOF\n",
                            encoding="utf-8")
            fake.chmod(0o755)
            path = f"{bin_dir}{os.pathsep}{os.environ['PATH']}"
            with mock.patch.dict(os.environ, {"PATH": path}):
                code, out = default_capture(
                    ["just", "--justfile", str(REPO_ROOT / "justfile"),
                     "--working-directory", scratch, "claude-guard-test-env"], Path(scratch))
        self.assertEqual(code, 0)
        self.assertEqual(parse_assignments(out),
                         {"CLAUDE_SETTINGS_PATH": listing[1],
                          "CLAUDE_GUARD_BASE_POLICY_PATH": listing[2]})

    def test_the_recipe_covers_the_engine_with_its_tier(self):
        for source in [f"{DELIVERY}/engine*.py",
                       f"{DELIVERY}/host_admission.py",
                       f"{DELIVERY}/procedure_check.py",
                       f"{DELIVERY}/procedure_terms.py",
                       f"{DELIVERY}/size_caps.py",
                       f"{DELIVERY}/lane_rule.py",
                       f"{DELIVERY}/rule_reader.py",
                       f"{DELIVERY}/procedures/*",
                       "tests/engine_*.py", "tests/fixtures/engine-*"]:
            self.assertIn(f"--cover '{source}=tests/test_engine_*.py'", self.recipe)
        self.assertTrue(any(fnmatch.fnmatchcase(m, "tests/test_engine_*.py")
                            for m in suite_members(self.justfile)))

    def test_the_recipe_covers_every_engine_module_with_the_engine_tier(self):
        words = shlex.split(self.recipe.splitlines()[-1])
        covers = [words[i + 1].split("=", 1) for i, w in enumerate(words) if w == "--cover"]
        caps = importlib.import_module("agent_tools.delivery.size_caps")
        modules = [p.relative_to(REPO_ROOT).as_posix()
                   for p in caps.engine_modules(REPO_ROOT / "python/agent_tools/delivery")]
        self.assertIn(f"{DELIVERY}/procedure_terms.py", modules)
        for module in modules:
            with self.subTest(module=module):
                self.assertTrue(any(fnmatch.fnmatchcase(module, source)
                                    and fnmatch.fnmatchcase("tests/test_engine_*.py", member)
                                    for source, member in covers))

    def test_an_engine_diff_selects_the_engine_tier_and_not_this_file(self):
        words = shlex.split(self.recipe.splitlines()[-1])
        values = lambda flag: [words[i + 1] for i, w in enumerate(words) if w == flag]
        pairs, covers = {}, {}
        for flag, table in (("--pair", pairs), ("--cover", covers)):
            for value in values(flag):
                source, member = value.split("=", 1)
                table.setdefault(source, []).append(member)
        members = suite_members(self.justfile)
        engine_tier = [m for m in members if fnmatch.fnmatchcase(m, "tests/test_engine_*.py")]
        for name in ["engine_slots", "engine_core", "host_admission", "procedure_check"]:
            with self.subTest(module=name):
                result = selection(
                    [f"{DELIVERY}/{name}.py", f"tests/test_{name}.py"], members,
                    lambda path: (REPO_ROOT / path).read_text(encoding="utf-8"),
                    source_roots=values("--source-root"), pairs=pairs, covers=covers,
                    build_globs=values("--build-when"))
                self.assertNotIn("tests/test_touched_tests.py", result["selected"])
                self.assertEqual(set(engine_tier) - set(result["selected"]), set())

    def test_a_diff_to_any_engine_tier_member_does_not_select_this_file(self):
        words = shlex.split(self.recipe.splitlines()[-1])
        values = lambda flag: [words[i + 1] for i, w in enumerate(words) if w == flag]
        pairs, covers = {}, {}
        for flag, table in (("--pair", pairs), ("--cover", covers)):
            for value in values(flag):
                source, member = value.split("=", 1)
                table.setdefault(source, []).append(member)
        members = suite_members(self.justfile)
        engine_tier = [m for m in members if fnmatch.fnmatchcase(m, "tests/test_engine_*.py")]
        for member in engine_tier:
            with self.subTest(member=member):
                result = selection(
                    [member], members,
                    lambda path: (REPO_ROOT / path).read_text(encoding="utf-8"),
                    source_roots=values("--source-root"), pairs=pairs, covers=covers,
                    build_globs=values("--build-when"))
                self.assertNotIn("tests/test_touched_tests.py", result["selected"])

    def test_this_test_is_a_suite_member(self):
        self.assertIn("tests/test_touched_tests.py", suite_members(self.justfile))


if __name__ == "__main__":
    unittest.main()
