import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import MappingProxyType
from unittest import mock

from agent_tools.delivery import hint_phases, never_rise, procedure_check, rule_ids, standards_lint
from agent_tools.delivery.never_rise import Rise, Snapshot, Violation
from agent_tools.project_contract import conformance_checks

REPO_ROOT = Path(__file__).resolve().parents[1]
TIER = "fast"

PLATFORM_FILES = {
    "README.md": (
        "# Standards\n\n## Rule ids\n\n| Layer file | Prefix |\n|---|---|\n"
        "| `the-bar.md` | `B` |\n| `stacks/python.md` | `PY` |\n"
        "| the repo's `docs/standards/` shards | `P` |\n"),
    "the-bar.md": "# The bar\n\n### B1. Fail loud\n\nbody\n",
    "stacks/python.md": "# Python\n\n### PY1. Use pathlib\n\nbody\n",
    "acceptance-planning.md": (
        "# Planning\n\n## Rules\n\n- **R1. First rule.** body\n- **R2. Second rule.** body\n"),
}
REPO_FILES = {
    "docs/standards/README.md": (
        "# Project standards\n\n| Shard | governs | Gist |\n|---|---|---|\n"
        "| [helpers.md](helpers.md) | `python/**`, `scripts/*.py` | Helpers. |\n"),
    "docs/standards/helpers.md": "# Helpers\n\n### P1. Helpers live in the package\n\nbody\n",
}
HELPERS_ROW = "| [helpers.md](helpers.md) | `python/**`, `scripts/*.py` | Helpers. |\n"
DASH = "—"


def run_lint(*args, env=None):
    return subprocess.run(
        [sys.executable, "-m", "agent_tools.delivery.standards_lint", *args],
        text=True, capture_output=True, stdin=subprocess.DEVNULL, env=env)


def write_files(base: Path, files: dict[str, str]) -> None:
    for name, text in files.items():
        path = base / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def make_tree(tmp: Path) -> tuple[Path, Path]:
    repo, platform = tmp / "repo", tmp / "platform"
    write_files(platform, PLATFORM_FILES)
    write_files(repo, REPO_FILES)
    return repo, platform


def lint_fixture(repo: Path, platform: Path):
    return run_lint("--repo-root", str(repo), "--platform-standards", str(platform))


class StructureTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.tmp = Path(temp.name)
        self.repo, self.platform = make_tree(self.tmp)
        self.index = self.repo / "docs/standards/README.md"
        self.helpers = self.repo / "docs/standards/helpers.md"
        self.bar = self.platform / "the-bar.md"
        self.python = self.platform / "stacks/python.md"
        self.planning = self.platform / "acceptance-planning.md"

    def edit(self, path: Path, old: str, new: str) -> None:
        text = path.read_text(encoding="utf-8")
        self.assertIn(old, text)
        path.write_text(text.replace(old, new), encoding="utf-8")

    def pad_index(self, lines: int) -> None:
        text = self.index.read_text(encoding="utf-8")
        text += "\n" * (lines - len(text.splitlines()))
        self.assertEqual(len(text.splitlines()), lines)
        self.index.write_text(text, encoding="utf-8")

    def assert_fails_with(self, line: str) -> None:
        result = lint_fixture(self.repo, self.platform)
        self.assertEqual((result.returncode, result.stdout), (1, line + "\n"))

    def assert_fails_with_all(self, *lines: str) -> None:
        result = lint_fixture(self.repo, self.platform)
        self.assertEqual((result.returncode, result.stdout), (1, "".join(f"{line}\n" for line in lines)))

    def assert_passes(self) -> None:
        result = lint_fixture(self.repo, self.platform)
        self.assertEqual((result.returncode, result.stdout), (0, ""))

    def test_the_clean_fixture_passes(self):
        result = lint_fixture(self.repo, self.platform)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))

    def test_a_41_line_index_fails(self):
        self.pad_index(41)
        self.assert_fails_with("docs/standards/README.md: index is 41 lines, over 40")

    def test_a_40_line_index_passes(self):
        self.pad_index(40)
        self.assert_passes()

    def test_an_unindexed_shard_fails(self):
        write_files(self.repo, {"docs/standards/extra.md": "# Extra\n\n### P2. Extra rule\n\nbody\n"})
        self.assert_fails_with("docs/standards/extra.md: has no row in docs/standards/README.md")

    def test_a_row_naming_a_missing_shard_fails(self):
        with self.index.open("a", encoding="utf-8") as handle:
            handle.write("| [gone.md](gone.md) | `x/**` | Gone. |\n")
        self.assert_fails_with("docs/standards/README.md: row names a missing shard gone.md")

    def test_a_repeated_index_row_fails(self):
        with self.index.open("a", encoding="utf-8") as handle:
            handle.write(HELPERS_ROW)
        self.assert_fails_with("docs/standards/README.md: row 2 repeats the shard helpers.md")

    def test_a_numbered_rule_beside_a_valid_heading_fails(self):
        self.helpers.write_text(
            "# Helpers\n\n### P1. Helpers live in the package\n\nbody\n\n1. Another rule\n",
            encoding="utf-8")
        self.assert_fails_with("docs/standards/helpers.md: line 7: no well-formed id: 1. Another rule")

    def test_an_index_table_that_is_not_rendered_indexes_nothing(self):
        table = REPO_FILES["docs/standards/README.md"].split("\n\n", 1)[1]
        for name, opener, closer in (("comment", "<!--", "-->"), ("fence", "```markdown", "```")):
            with self.subTest(name=name):
                self.index.write_text(f"# Project standards\n\n{opener}\n{table}{closer}\n", encoding="utf-8")
                result = lint_fixture(self.repo, self.platform)
                self.assertEqual((result.returncode, result.stdout), (1, (
                    "docs/standards/README.md: index has no governs column\n"
                    "docs/standards/helpers.md: has no row in docs/standards/README.md\n")))

    def test_an_index_table_in_indented_code_indexes_nothing(self):
        table = REPO_FILES["docs/standards/README.md"].split("\n\n", 1)[1]
        indented = "".join(f"    {line}\n" for line in table.splitlines())
        self.index.write_text(f"# Project standards\n\nExample:\n\n{indented}", encoding="utf-8")
        self.assert_fails_with_all(
            "docs/standards/README.md: index has no governs column",
            "docs/standards/helpers.md: has no row in docs/standards/README.md")

    def test_a_prefix_row_that_is_not_rendered_is_no_prefix_row(self):
        write_files(self.platform, {"stacks/node.md": "# Node\n\n### NODE1. x\n\nbody\n"})
        for name, opener, closer in (("comment", "<!--", "-->"), ("fence", "```", "```")):
            with self.subTest(name=name):
                write_files(self.platform, {"README.md": PLATFORM_FILES["README.md"]})
                with (self.platform / "README.md").open("a", encoding="utf-8") as handle:
                    handle.write(f"\n{opener}\n| `stacks/node.md` | `NODE` |\n{closer}\n")
                self.assert_fails_with("stacks/node.md: has no prefix row in README.md")

    def test_a_numbered_rule_with_either_delimiter_and_no_id_fails(self):
        for line in ("1. Another rule", "1) Another rule"):
            with self.subTest(line=line):
                self.helpers.write_text(
                    f"# Helpers\n\n### P1. Helpers live in the package\n\nbody\n\n{line}\n",
                    encoding="utf-8")
                self.assert_fails_with(f"docs/standards/helpers.md: line 7: no well-formed id: {line}")

    def test_a_same_directory_link_names_its_shard(self):
        self.edit(self.index, "(helpers.md)", "(./helpers.md)")
        self.assert_passes()

    def test_a_row_linking_the_index_itself_names_a_missing_shard(self):
        with self.index.open("a", encoding="utf-8") as handle:
            handle.write("| [README.md](README.md) | `x/**` | Index. |\n")
        self.assert_fails_with("docs/standards/README.md: row names a missing shard README.md")

    def test_a_prefix_row_missing_its_second_cell_is_skipped(self):
        write_files(self.platform, {"stacks/node.md": "# Node\n\n### NODE1. x\n\nbody\n"})
        with (self.platform / "README.md").open("a", encoding="utf-8") as handle:
            handle.write("| `stacks/node.md` |\n")
        self.assert_fails_with("stacks/node.md: has no prefix row in README.md")

    def test_a_glob_with_ordinary_filename_characters_passes(self):
        self.edit(self.index, "`python/**`, `scripts/*.py`", "`packages/@scope/**`, `src/C++/**`")
        self.assert_passes()

    def test_a_brace_or_parenthesis_glob_passes(self):
        self.edit(self.index, "`python/**`, `scripts/*.py`", "`src/**/*.{ts,tsx}`, `app/(group)/**`")
        self.assert_passes()

    def test_a_bare_star_governs_fails(self):
        for value in ("*", "**", "**/*"):
            with self.subTest(value=value):
                index = REPO_FILES["docs/standards/README.md"].replace(
                    "`python/**`, `scripts/*.py`", f"`{value}`")
                self.index.write_text(index, encoding="utf-8")
                self.assert_fails_with(
                    f"docs/standards/README.md: helpers.md governs `{value}`, which matches every path")

    def test_a_prose_governs_fails(self):
        self.edit(self.index, "`python/**`, `scripts/*.py`", "all helper code")
        self.assert_fails_with(
            "docs/standards/README.md: helpers.md governs prose, not path globs: all helper code")

    def test_a_code_span_with_a_space_is_no_glob(self):
        self.edit(self.index, "`python/**`, `scripts/*.py`", "`every python file`")
        self.assert_fails_with(
            "docs/standards/README.md: helpers.md governs `every python file`, which is not a path glob")

    def test_a_heading_with_two_ids_fails(self):
        self.edit(self.helpers, "### P1. Helpers live in the package", "### P1. P2. Helpers")
        self.assert_fails_with("docs/standards/helpers.md: line 3: more than one id: ### P1. P2. Helpers")

    def test_a_rule_with_no_id_fails(self):
        self.edit(self.helpers, "### P1. Helpers live in the package", "### Helpers live in the package")
        self.assert_fails_with(
            "docs/standards/helpers.md: line 3: no well-formed id: ### Helpers live in the package")

    def test_a_heading_over_100_characters_fails(self):
        heading = "### P1. " + "x" * 93
        self.assertEqual(len(heading), 101)
        self.edit(self.helpers, "### P1. Helpers live in the package", heading)
        self.assert_fails_with(
            "docs/standards/helpers.md: line 3: heading is 101 characters, over 100")

    def test_a_100_character_heading_passes(self):
        heading = "### P1. " + "x" * 92
        self.assertEqual(len(heading), 100)
        self.edit(self.helpers, "### P1. Helpers live in the package", heading)
        self.assert_passes()

    def sized(self, path: Path, filler: str, size: int) -> None:
        self.edit(path, "body", filler)
        self.assertEqual(len(path.read_bytes()), size)
        if size == 8193:  # more bytes than characters, so a size read as len(text) passes
            self.assertEqual(len(path.read_text(encoding="utf-8")), 2793)

    def test_a_shard_over_8_kb_fails(self):
        self.sized(self.helpers, DASH * 2700 + "x" * 44, 8193)
        self.assert_fails_with("docs/standards/helpers.md: is 8193 bytes, over 8192")

    def test_an_8192_byte_shard_passes(self):
        self.sized(self.helpers, DASH * 2700 + "x" * 43, 8192)
        self.assert_passes()

    def test_a_stack_shard_over_8_kb_fails(self):
        self.sized(self.python, DASH * 2700 + "x" * 60, 8193)
        self.assert_fails_with("stacks/python.md: is 8193 bytes, over 8192")

    def test_a_stack_shard_with_no_prefix_row_fails(self):
        write_files(self.platform, {"stacks/node.md": "# Node\n\n### NODE1. x\n\nbody\n"})
        self.assert_fails_with("stacks/node.md: has no prefix row in README.md")

    def test_a_planning_rule_with_two_ids_fails(self):
        self.edit(self.planning, "- **R1. First rule.** body", "- **R1. R2. First rule.** body")
        self.assert_fails_with(
            "acceptance-planning.md: line 5: more than one id: - **R1. R2. First rule.** body")

    def test_a_planning_rule_with_no_id_fails(self):
        for line in ("- **First rule.** body", "- **r1. First rule.** body"):
            with self.subTest(line=line):
                text = PLATFORM_FILES["acceptance-planning.md"].replace("- **R1. First rule.** body", line)
                self.planning.write_text(text, encoding="utf-8")
                self.assert_fails_with(f"acceptance-planning.md: line 5: no well-formed id: {line}")

    def test_a_planning_rule_title_over_the_cap_fails(self):
        line = "- **R1. " + "x" * 90 + ".**"
        self.assertEqual(len(line), 101)
        self.edit(self.planning, "- **R1. First rule.** body", line)
        self.assert_fails_with("acceptance-planning.md: line 5: rule title is 101 characters, over 100")

    def test_the_platform_root_names_the_default_standards(self):
        standards = self.tmp / "root/standards"
        write_files(standards, PLATFORM_FILES)
        (standards / "the-bar.md").write_text("# The bar\n\n### B1. B2. Fail loud\n\nbody\n", encoding="utf-8")
        env = {**os.environ, "AGENT_PLATFORM_ROOT": str(self.tmp / "root")}
        result = run_lint("--repo-root", str(self.repo), env=env)
        self.assertEqual(
            (result.returncode, result.stdout),
            (1, "the-bar.md: line 3: more than one id: ### B1. B2. Fail loud\n"))
        (standards / "the-bar.md").write_text(PLATFORM_FILES["the-bar.md"], encoding="utf-8")
        result = run_lint("--repo-root", str(self.repo), env=env)
        self.assertEqual((result.returncode, result.stdout), (0, ""))

    def test_a_relative_root_is_misuse(self):
        result = run_lint("--repo-root", "repo", "--platform-standards", str(self.platform))
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertTrue(result.stderr.startswith("standards-lint: "))


class HintTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.repo, self.platform = make_tree(Path(temp.name))
        self.hints = self.repo / ".agents/knowledge/hints"

    def assert_fails_with(self, line: str) -> None:
        result = lint_fixture(self.repo, self.platform)
        self.assertEqual((result.returncode, result.stdout), (1, line + "\n"))

    def assert_passes(self) -> None:
        result = lint_fixture(self.repo, self.platform)
        self.assertEqual((result.returncode, result.stdout), (0, ""))

    def test_a_hint_named_for_no_reading_phase_fails(self):
        for name in ("deploy.md", "verifying.md"):
            with self.subTest(name=name):
                temp = tempfile.TemporaryDirectory()
                self.addCleanup(temp.cleanup)
                self.repo, self.platform = make_tree(Path(temp.name))
                write_files(self.repo, {f".agents/knowledge/hints/{name}": "Deploy carefully.\n"})
                self.assert_fails_with(
                    f".agents/knowledge/hints/{name}: named for no delivery phase that reads hints")

    def test_a_directory_under_hints_fails(self):
        (self.hints / "planning").mkdir(parents=True)
        self.assert_fails_with(
            ".agents/knowledge/hints/planning: named for no delivery phase that reads hints")

    def test_a_hint_over_the_line_budget_fails(self):
        write_files(self.repo, {".agents/knowledge/hints/planning.md": "step\n" * 61})
        self.assert_fails_with(".agents/knowledge/hints/planning.md: is 61 lines, over 60")

    def test_a_60_line_hint_passes(self):
        write_files(self.repo, {".agents/knowledge/hints/planning.md": "step\n" * 60})
        self.assert_passes()

    def test_a_hint_for_each_reading_phase_passes(self):
        write_files(self.repo, {
            f".agents/knowledge/hints/{name}": "x\n"
            for name in ("planning.md", "plan-review.md", "building.md", "final-review.md")})
        self.assert_passes()

    def test_the_hint_names_come_from_the_one_home(self):
        write_files(self.repo, {".agents/knowledge/hints/x.md": "x\n"})
        self.assertEqual(
            standards_lint.hint_problems(self.repo),
            [".agents/knowledge/hints/x.md: named for no delivery phase that reads hints"])
        with mock.patch.object(hint_phases, "HINT_FILES", ("x.md",)):
            self.assertEqual(standards_lint.hint_problems(self.repo), [])

    def test_the_hint_stages_are_briefed_procedure_stages(self):
        self.assertLessEqual(set(hint_phases.HINT_STAGES), set(procedure_check.STAGES))
        self.assertEqual(
            hint_phases.HINT_FILES, ("planning.md", "plan-review.md", "building.md", "final-review.md"))


class RoutedSetBudgetTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        write_files(self.root / "standards", {
            "the-bar.md": "### B1. One\n" + "x" * 4084,
            "stacks/python.md": "# Python\n" + "y" * 4087})
        patch = mock.patch.dict(os.environ, {"AGENT_PLATFORM_ROOT": str(self.root)})
        patch.start()
        self.addCleanup(patch.stop)

    def snapshot(self, shards: dict[str, tuple[int, str]], paths: tuple[str, ...] = ("big/x.py",)):
        """One shard per name: its byte size and the glob it governs."""
        rows = "".join(f"| [{name}]({name}) | `{glob}` | Gist. |\n"
                       for name, (_, glob) in shards.items())
        files = {"docs/standards/README.md": "# P\n\n| Shard | governs | Gist |\n|---|---|---|\n" + rows}
        files.update({f"docs/standards/{name}": b"z" * size for name, (size, _) in shards.items()})
        contents = {path: (text if isinstance(text, bytes) else text.encode())
                    for path, text in files.items()}
        return Snapshot("a" * 40, {}, contents=MappingProxyType(contents),
                        paths=frozenset(contents) | frozenset(paths))

    def test_a_branch_putting_one_path_over_24_kb_rises_naming_it(self):
        base = self.snapshot({"a.md": (8000, "big/**")})
        branch = self.snapshot({"a.md": (8000, "big/**"), "b.md": (9000, "big/**")})

        risen = never_rise.compare(base, branch, {}, [standards_lint.ROUTED_SET_ENFORCER])

        self.assertEqual(risen, (Rise("B26", 0, 1, (Violation("B26", "big/x.py", 25192, 1),)),))
        self.assertEqual(risen[0].new[0].text(), "B26 big/x.py:25192")

    def test_a_path_at_24_kb_is_no_violation_and_one_byte_more_is(self):
        at = self.snapshot({"a.md": (16384, "big/**")})
        over = self.snapshot({"a.md": (16385, "big/**")})

        self.assertEqual(standards_lint.routed_set_violations(at), [])
        self.assertEqual(standards_lint.routed_set_violations(over),
                         [Violation("B26", "big/x.py", 24577, 1)])

    def test_an_over_budget_path_that_grows_does_not_rise(self):
        base = self.snapshot({"a.md": (8000, "big/**"), "b.md": (9000, "big/**")})
        branch = self.snapshot({"a.md": (8000, "big/**"), "b.md": (9500, "big/**")})

        self.assertEqual(never_rise.compare(base, branch, {}, [standards_lint.ROUTED_SET_ENFORCER]), ())

    def test_a_renamed_over_budget_path_does_not_rise(self):
        shards = {"a.md": (8000, "big/**"), "b.md": (9000, "big/**"),
                  "c.md": (8000, "moved/**"), "d.md": (9000, "moved/**")}
        base = self.snapshot(shards, ("big/x.py",))
        branch = self.snapshot(shards, ("moved/x.py",))
        enforcers = [standards_lint.ROUTED_SET_ENFORCER]

        self.assertEqual(never_rise.compare(base, branch, {"moved/x.py": "big/x.py"}, enforcers), ())
        risen = never_rise.compare(base, branch, {}, enforcers)
        self.assertEqual([v.path for rise in risen for v in rise.new], ["moved/x.py"])

    def test_a_platform_with_no_bar_fails_the_enforcer(self):
        (self.root / "standards" / "the-bar.md").unlink()

        with self.assertRaises(never_rise.EnforcerFailed) as failed:
            standards_lint.routed_set_violations(self.snapshot({"a.md": (10, "big/**")}))

        self.assertEqual(failed.exception.enforcer, "B26")
        empty = self.snapshot({"a.md": (10, "big/**")})._replace(paths=frozenset())
        self.assertEqual(standards_lint.routed_set_violations(empty), [])

    def test_the_enforcer_is_registered_with_the_never_rise_check(self):
        self.assertIn(standards_lint.ROUTED_SET_ENFORCER,
                      conformance_checks.never_rise_enforcers({"bindings": {}}))

    def test_the_bar_holds_b26_and_the_enforcer_cites_it(self):
        bar = REPO_ROOT / "home/common/agent-skills/standards/the-bar.md"
        module = Path(standards_lint.__file__).read_text(encoding="utf-8")

        self.assertIn("B26", rule_ids.sections(bar.read_text(encoding="utf-8")))
        self.assertIn("B26", {c.token for c in rule_ids.citations(module) if c.well_formed})


class LiveTreeTest(unittest.TestCase):
    def test_the_lint_passes_on_this_repository(self):
        result = run_lint(
            "--repo-root", str(REPO_ROOT),
            "--platform-standards", str(REPO_ROOT / "home/common/agent-skills/standards"))
        self.assertEqual((result.returncode, result.stdout), (0, ""))

    def test_the_standards_readme_sends_hints_to_the_knowledge_directory(self):
        text = (REPO_ROOT / "home/common/agent-skills/standards/README.md").read_text(encoding="utf-8")
        self.assertIn(".agents/knowledge/hints/", text)
        self.assertNotIn(".claude/hints/", text)
        self.assertNotIn("REVIEW-CONTRACT.md", text)


if __name__ == "__main__":
    unittest.main()
