"""The touched-test selector and the `test-touched` recipe (ADR-delivery-012).

`agent_tools.delivery.touched_tests` selects the agent workflow suite's members a branch
touches, builds the host first when a build input changed, and runs the selection through
the suite runner. `SelectTest` and `BuildTriggerTest` run the pure functions on fixtures,
`MainTest` runs `main` against a real temporary git repository with a recording stub for
every command it would start, and `RecipeTest` reads the repository's justfile.
"""

import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent_tools.delivery.suite_runner import suite_members
from agent_tools.delivery.touched_tests import build_trigger, main, select

TIER = "integration"  # MainTest builds a git repository

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER = [sys.executable, "-m", "agent_tools.delivery.suite_runner"]


def reader(texts):
    def read(path):
        return texts.get(path, "")
    return read


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
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        self.env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull,
                        GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid",
                        GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid")
        patcher = mock.patch.dict(os.environ, self.env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.git("init", "-q", "-b", "main")
        self.write("justfile", "agent-workflow-tests *args:\n  runner {{args}} \\\n"
                               "    tests/test_alpha.py\n")
        self.write("python/pkg/alpha.py", "VALUE = 1\n")
        self.write("hosts/m.nix", "{ }\n")
        self.commit("first")
        self.write("python/pkg/alpha.py", "VALUE = 2\n")
        self.write("hosts/m.nix", "{ a = 1; }\n")
        self.commit("second")
        self.calls = []

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

        def execute(argv, cwd):
            self.calls.append((argv, cwd))
            return codes.get(argv[0], codes.get("runner", 0))
        return execute

    def run_main(self, *args, execute=None):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["--root", str(self.root), *args], execute=execute or self.stub())
        return code, out.getvalue(), err.getvalue()

    def test_the_cli_runs_the_selected_members_through_the_suite_runner(self):
        code, _, _ = self.run_main("--base", "HEAD~1", "--source-root", "python",
                                   execute=self.stub({"runner": 3}))
        self.assertEqual(self.calls, [([*RUNNER, "tests/test_alpha.py"], self.root)])
        self.assertEqual(code, 3)

    def test_a_build_input_change_builds_before_the_suite(self):
        code, _, err = self.run_main("--base", "HEAD~1", "--source-root", "python",
                                     "--build-command", "just build", "--build-when", "*.nix")
        self.assertEqual([argv for argv, _ in self.calls],
                         [["just", "build"], [*RUNNER, "tests/test_alpha.py"]])
        self.assertIn("hosts/m.nix", err)
        self.assertEqual(code, 0)

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

    def test_this_test_is_a_suite_member(self):
        self.assertIn("tests/test_touched_tests.py", suite_members(self.justfile))


if __name__ == "__main__":
    unittest.main()
