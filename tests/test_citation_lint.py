"""The citation form an enforcer uses to name a standard's rule (#1442).

Measures the form itself: `citations` finds each citation with its line and
whether its token is a well-formed rule id, a form glued to a word is no
citation, `prefix_of` reads the id's capital letters, and the standards README
states the form and gives the project shards the project prefix.

The citation checks belong to the one standards lint (`standards-lint`,
`agent_tools.delivery.standards_lint`) and are measured through its command line:
it reads only the registered enforcers (the suite recipe's members and the `lint`
command's sources), fails on a citation of an id in no applicable layer, a
malformed citation or a missing enforcer, resolves a project id only against the
project's shards and any other id only against the platform directory, checks no
citation of a repository whose justfile has no suite recipe, refuses bad
arguments, is the command-table row and passes on this checkout. With `--index`
it prints each rule with the enforcers citing it and the two counts, still fails
on a problem, and writes nothing.
"""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from agent_tools.delivery.citation_lint import enforcers
from agent_tools.delivery.context_map_lint import CODE_RE, section, table_rows
from agent_tools.delivery.rule_ids import (
    CITATION, PROJECT_PREFIX, RULE_ID_HEADING, Citation, citations, prefix_of)
from agent_tools.delivery.suite_runner import suite_members
from agent_tools.delivery.verification_command import members

REPO_ROOT = Path(__file__).resolve().parents[1]
TIER = "fast"
README = REPO_ROOT / "home/common/agent-skills/standards/README.md"
BAR = REPO_ROOT / "home/common/agent-skills/standards/the-bar.md"


MALFORMED_TOKENS = (
    "b7", "B07", "B7a", "B", "7", "_B7", "B7_x", "-B7", ".B7", "B7-x", "B7.x", "/B7", "#B7", ".",
    "`", "B7/x", "B7:x", "B7+x", "B7#x", "B7=x", "<id>", "B7`x", "..", "-", "_", "/", "B7/")


def cite(token: str) -> str:
    """One citation of `token`, assembled so this file holds no literal citation."""
    return "standard" + ":" + token


class CitationFormTest(unittest.TestCase):
    def test_a_citation_is_found_with_its_line_and_token(self):
        text = "one\n# " + cite("B7") + " and " + cite("PY3") + "\n"

        found = citations(text)

        self.assertEqual(found, [Citation(2, "B7", True), Citation(2, "PY3", True)])

    def test_a_form_glued_to_a_word_is_no_citation(self):
        for text in ("non" + cite("B7"), "x_" + cite("B7"), "x-" + cite("B7"), "x1" + cite("B7")):
            with self.subTest(text=text):
                self.assertEqual(citations(text), [])

    def test_a_token_that_is_no_rule_id_is_malformed(self):
        for token in MALFORMED_TOKENS:
            with self.subTest(token=token):
                self.assertEqual(citations(cite(token)), [Citation(1, token, False)])

    def test_a_malformed_token_is_reported_whole_when_text_follows_it(self):
        for token in MALFORMED_TOKENS:
            if not token.strip(".`"):
                continue
            with self.subTest(token=token):
                self.assertEqual(citations(cite(token) + " tail"), [Citation(1, token, False)])
                self.assertEqual(citations("`" + cite(token) + "`"), [Citation(1, token, False)])

    def test_a_form_followed_by_a_space_or_the_end_is_prose_not_a_citation(self):
        for text in (cite(""), cite("") + " no worktree", cite("") + "\nB7"):
            with self.subTest(text=text):
                self.assertEqual(citations(text), [])

    def test_trailing_punctuation_ends_the_token(self):
        self.assertEqual(citations(cite("B7") + "."), [Citation(1, "B7", True)])
        self.assertEqual(citations("(" + cite("NET10") + ")"), [Citation(1, "NET10", True)])
        for tail in (",", ";", ":", "!", "?", ")", "`", "'", '"', "`.", ").", "...", "*"):
            with self.subTest(tail=tail):
                self.assertEqual(citations(cite("B7") + tail), [Citation(1, "B7", True)])

    def test_prefix_of_reads_the_capital_letters(self):
        self.assertEqual([prefix_of(i) for i in ("P4", "PY3", "NET10", "B1")], ["P", "PY", "NET", "B"])


class ReadmeFormTest(unittest.TestCase):
    def test_the_readme_states_the_citation_form(self):
        block = section(README.read_text("utf-8"), "Rule ids")
        bar_ids = set()
        for line in BAR.read_text("utf-8").splitlines():
            match = RULE_ID_HEADING.match(line)
            if match and match["hashes"] == "###":
                bar_ids.add(match["prefix"] + match["number"])

        spans = [span for span in CODE_RE.findall(block)
                 if CITATION.fullmatch(span) and citations(span)[0].well_formed]

        self.assertTrue(spans)
        for span in spans:
            self.assertIn(citations(span)[0].token, bar_ids)

    def test_the_readme_gives_project_shards_the_project_prefix(self):
        rows = table_rows(section(README.read_text("utf-8"), "Rule ids"))

        row = next(r for r in rows if "docs/standards/" in CODE_RE.findall(r[0]))

        self.assertEqual(CODE_RE.findall(row[1])[0], PROJECT_PREFIX)


PLATFORM_README = (
    "# Standards\n\n## Rule ids\n\n| Layer file | Prefix |\n|---|---|\n"
    "| `the-bar.md` | `B` |\n| `stacks/python.md` | `PY` |\n"
    "| the repo's `docs/standards/` shards | `P` |\n")
LINT_SOURCE_TEXT = '"""Fixture lint (ADR-delivery-012)."""\n'


class LintTestCase(unittest.TestCase):
    def fixture(self, *, files: dict[str, str], members: list[str],
                project_shards: dict[str, str] | None = None) -> tuple[Path, Path, Path]:
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        base = Path(scratch.name)
        root, platform = base / "root", base / "platform"
        project = root / "docs" / "standards"
        (platform / "stacks").mkdir(parents=True)
        project.mkdir(parents=True)
        (platform / "README.md").write_text(PLATFORM_README, "utf-8")
        (platform / "the-bar.md").write_text(
            "# The bar\n\n### B1. One\n\nBody.\n\n### B2. Two\n\nBody.\n", "utf-8")
        (platform / "stacks" / "python.md").write_text("# Python\n\n### PY1. Py\n\nBody.\n", "utf-8")
        for name, text in (project_shards or {}).items():
            (project / name).write_text(text, "utf-8")
        if project_shards:
            rows = "".join(f"| [{name}]({name}) | `x/**` | Shard. |\n" for name in sorted(project_shards))
            (project / "README.md").write_text(
                "# Project standards\n\n| Shard | governs | Gist |\n|---|---|---|\n" + rows, "utf-8")
        justfile = "agent-workflow-tests *args:\n  PYTHONPATH=x python3 -m agent_tools.delivery.suite_runner {{args}} \\\n"
        justfile += " \\\n".join(f"    {m}" for m in members) + "\n"
        (root / "justfile").write_text(justfile, "utf-8")
        written = dict(files)
        for member in members_of_lint(root):
            written.setdefault(member, LINT_SOURCE_TEXT)
        for relative, text in written.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, "utf-8")
        return root, platform, project

    def run_lint(self, root, platform, project, *extra):
        return subprocess.run(
            [sys.executable, "-m", "agent_tools.delivery.standards_lint", "--repo-root", str(root),
             "--platform-standards", str(platform), *extra],
            capture_output=True, text=True, timeout=120,
            env={**os.environ, "PYTHONPATH": str(REPO_ROOT / "python")})


def members_of_lint(root: Path) -> list[str]:
    """The repository-relative lint sources, as `enforcers` derives them."""
    return [
        "python/" + m.argv[m.argv.index("-m") + 1].replace(".", "/") + ".py"
        for m in members("lint", root)]


class DiscoveryTest(LintTestCase):
    def test_suite_members_are_the_recipe_lines_after_the_runner_line(self):
        text = "x:\n  a\nagent-workflow-tests *args:\n  RUN \\\n    t/a.py \\\n    t/b.sh\nnext:\n  c\n"

        self.assertEqual(suite_members(text), ["t/a.py", "t/b.sh"])

    def test_a_justfile_without_the_suite_recipe_is_refused(self):
        with self.assertRaises(ValueError):
            suite_members("lint:\n  x\n")

    def test_enforcers_are_the_suite_members_and_the_lint_sources(self):
        root, _, _ = self.fixture(
            files={"tests/test_a.py": "x = 1\n", "tests/test_b.py": "x = 1\n"},
            members=["tests/test_b.py", "tests/test_a.py"])

        self.assertEqual(enforcers(root), sorted([
            "tests/test_a.py", "tests/test_b.py",
            "python/agent_tools/delivery/agnostic_lint.py",
            "python/agent_tools/delivery/context_map_lint.py",
            "python/agent_tools/instruction_load.py"]))

    def test_an_unregistered_file_is_never_read(self):
        root, platform, project = self.fixture(
            files={"tests/test_a.py": "x = 1\n", "tests/test_c.py": cite("Z9") + "\n"},
            members=["tests/test_a.py"])

        result = self.run_lint(root, platform, project)

        self.assertEqual(result.returncode, 0, result.stderr)


class CheckTest(LintTestCase):
    def test_a_citation_of_an_id_in_no_layer_fails_naming_file_and_id(self):
        root, platform, project = self.fixture(
            files={"tests/test_a.py": "x = 1\n# " + cite("Z9") + "\n"}, members=["tests/test_a.py"])

        failed = self.run_lint(root, platform, project)
        (root / "tests/test_a.py").write_text("x = 1\n", "utf-8")
        passed = self.run_lint(root, platform, project)

        self.assertEqual(failed.returncode, 1)
        self.assertIn("tests/test_a.py:2: cites Z9, which is in no applicable layer",
                      failed.stdout.splitlines())
        self.assertEqual(passed.returncode, 0, passed.stderr)
        self.assertEqual(passed.stdout, "")

    def test_a_citation_in_a_lint_source_is_checked(self):
        root, platform, project = self.fixture(
            files={"python/agent_tools/delivery/agnostic_lint.py": cite("Z8") + "\n"},
            members=["tests/test_a.py"])

        result = self.run_lint(root, platform, project)

        self.assertEqual(result.returncode, 1)
        self.assertIn("python/agent_tools/delivery/agnostic_lint.py:1: cites Z8", result.stdout)

    def test_a_malformed_citation_fails(self):
        root, platform, project = self.fixture(
            files={"tests/test_a.py": cite("b7") + "\n"}, members=["tests/test_a.py"])

        result = self.run_lint(root, platform, project)

        self.assertEqual(result.returncode, 1)
        self.assertIn("tests/test_a.py:1: malformed citation " + cite("b7"),
                      result.stdout.splitlines())

    def test_a_missing_registered_enforcer_fails(self):
        root, platform, project = self.fixture(files={}, members=["tests/test_gone.py"])

        result = self.run_lint(root, platform, project)

        self.assertEqual(result.returncode, 1)
        self.assertIn("tests/test_gone.py: registered enforcer is missing",
                      result.stdout.splitlines())

    def test_a_deleted_rule_fails_its_citation(self):
        root, platform, project = self.fixture(
            files={"tests/test_a.py": cite("B2") + "\n"}, members=["tests/test_a.py"])

        before = self.run_lint(root, platform, project)
        (platform / "README.md").write_text(PLATFORM_README, "utf-8")
        (platform / "the-bar.md").write_text("# The bar\n\n### B1. One\n\nBody.\n", "utf-8")
        after = self.run_lint(root, platform, project)

        self.assertEqual(before.returncode, 0, before.stderr)
        self.assertEqual(after.returncode, 1)
        self.assertIn("cites B2", after.stdout)


    def test_a_citation_led_or_continued_by_a_separator_is_malformed_in_an_enforcer(self):
        for token in MALFORMED_TOKENS:
            with self.subTest(token=token):
                root, platform, project = self.fixture(
                    files={"tests/test_a.py": "# " + cite(token) + "\n"}, members=["tests/test_a.py"])

                result = self.run_lint(root, platform, project)

                self.assertEqual(result.returncode, 1)
                self.assertIn("tests/test_a.py:1: malformed citation " + cite(token),
                              result.stdout.splitlines())

    def test_a_commented_out_or_fenced_rule_heading_is_no_rule(self):
        hidden = {
            "comment.md": "# C\n\n<!--\n### P1. Retired\n\nBody.\n-->\n",
            "one_line.md": "# O\n\n<!-- ### P2. Retired -->\n",
            "fence.md": "# F\n\n```md\n### P3. Example\n```\n",
            "tilde.md": "# T\n\n~~~md\n### P4. Example\n~~~\n"}
        for token in ("P1", "P2", "P3", "P4"):
            with self.subTest(token=token):
                root, platform, project = self.fixture(
                    files={"tests/test_a.py": cite(token) + "\n"}, members=["tests/test_a.py"],
                    project_shards=hidden)

                result = self.run_lint(root, platform, project)

                self.assertEqual(result.returncode, 1)
                self.assertIn(f"cites {token}, which is in no applicable layer", result.stdout)

    def test_a_commented_out_bar_heading_is_no_rule(self):
        root, platform, project = self.fixture(
            files={"tests/test_a.py": cite("B3") + "\n"}, members=["tests/test_a.py"])
        bar = platform / "the-bar.md"
        bar.write_text(bar.read_text("utf-8") + "\n<!--\n### B3. Retired\n\nBody.\n-->\n", "utf-8")

        result = self.run_lint(root, platform, project)

        self.assertEqual(result.returncode, 1)
        self.assertIn("cites B3", result.stdout)


class LayerTest(LintTestCase):
    def test_a_project_id_resolves_only_against_its_own_shards(self):
        files = {"tests/test_a.py": cite("P1") + "\n"}
        root_a, platform_a, project_a = self.fixture(
            files=files, members=["tests/test_a.py"],
            project_shards={"a.md": "# A\n\n### P1. A rule\n\nBody.\n"})
        root_b, platform_b, project_b = self.fixture(
            files=files, members=["tests/test_a.py"],
            project_shards={"b.md": "# B\n\n### P2. B rule\n\nBody.\n"})

        a = self.run_lint(root_a, platform_a, project_a)
        b = self.run_lint(root_b, platform_b, project_b)

        self.assertEqual(a.returncode, 0, a.stderr)
        self.assertEqual(b.returncode, 1)
        self.assertIn("tests/test_a.py:1: cites P1, which is in no applicable layer",
                      b.stdout.splitlines())

    def test_a_bar_id_resolves_only_against_the_platform_directory(self):
        shadow = {"x.md": "# X\n\n### B9. Shadow\n\nBody.\n"}
        root, platform, project = self.fixture(
            files={"tests/test_a.py": cite("B9") + "\n"}, members=["tests/test_a.py"],
            project_shards=shadow)
        known_root, known_platform, known_project = self.fixture(
            files={"tests/test_a.py": cite("B1") + "\n"}, members=["tests/test_a.py"],
            project_shards=shadow)

        shadowed = self.run_lint(root, platform, project)
        known = self.run_lint(known_root, known_platform, known_project)

        self.assertIn("tests/test_a.py:1: cites B9, which is in no applicable layer",
                      shadowed.stdout.splitlines())
        self.assertNotIn("cites", known.stdout)

    def test_a_stack_id_resolves_against_the_stack_shards(self):
        root, platform, project = self.fixture(
            files={"tests/test_a.py": cite("PY1") + "\n"}, members=["tests/test_a.py"])
        other_root, other_platform, other_project = self.fixture(
            files={"tests/test_a.py": cite("PY2") + "\n"}, members=["tests/test_a.py"])

        known = self.run_lint(root, platform, project)
        unknown = self.run_lint(other_root, other_platform, other_project)

        self.assertEqual(known.returncode, 0, known.stderr)
        self.assertEqual(unknown.returncode, 1)
        self.assertIn("cites PY2", unknown.stdout)


class UsageTest(LintTestCase):
    def test_a_relative_path_is_a_usage_error(self):
        root, platform, project = self.fixture(files={}, members=["tests/test_a.py"])

        result = self.run_lint(".", platform, project)

        self.assertEqual(result.returncode, 2)

    def test_a_platform_directory_without_the_bar_is_a_usage_error(self):
        root, platform, project = self.fixture(files={}, members=["tests/test_a.py"])
        (platform / "the-bar.md").unlink()

        result = self.run_lint(root, platform, project)

        self.assertEqual(result.returncode, 2)
        self.assertIn("the-bar.md", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_a_justfile_without_the_suite_recipe_registers_no_enforcer(self):
        root, platform, project = self.fixture(
            files={"tests/test_a.py": cite("Z9") + "\n"}, members=["tests/test_a.py"])
        (root / "justfile").write_text("lint:\n  x\n", "utf-8")

        plain = self.run_lint(root, platform, project)
        indexed = self.run_lint(root, platform, project, "--index")

        self.assertEqual((plain.returncode, plain.stdout), (0, ""), plain.stderr)
        self.assertEqual(indexed.returncode, 0, indexed.stderr)
        self.assertEqual(indexed.stdout.splitlines(), [
            "B1. One", "B2. Two", "PY1. Py", "judged rules: 3", "enforcers citing nothing: 0"])

    def test_an_argument_the_old_citation_lint_took_is_refused(self):
        root, platform, project = self.fixture(files={}, members=["tests/test_a.py"])

        result = self.run_lint(root, platform, project, "--project-standards", str(project))

        self.assertEqual(result.returncode, 2)


class IndexTest(LintTestCase):
    def index_fixture(self, other: str, *, project_shards=None):
        root, platform, project = self.fixture(
            files={"tests/test_a.py": "# " + cite("B1") + "\n# " + cite("B1") + "\n",
                   "tests/test_b.py": other},
            members=["tests/test_a.py", "tests/test_b.py"], project_shards=project_shards)
        (platform / "stacks" / "python.md").unlink()
        return root, platform, project

    def test_the_index_lists_the_citing_enforcer_and_both_counts(self):
        root, platform, project = self.index_fixture("x = 1\n")

        result = self.run_lint(root, platform, project, "--index")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), [
            "B1. One", "  tests/test_a.py", "B2. Two", "judged rules: 1",
            "enforcers citing nothing: 1"])

    def test_a_decision_record_citation_counts_as_citing(self):
        root, platform, project = self.index_fixture("# ADR-delivery-012\n")

        result = self.run_lint(root, platform, project, "--index")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines()[-1], "enforcers citing nothing: 0")

    def test_rules_are_listed_bar_then_stacks_then_project(self):
        root, platform, project = self.fixture(
            files={"tests/test_a.py": "x = 1\n"}, members=["tests/test_a.py"],
            project_shards={"b.md": "# B\n\n### P2. Two\n\nBody.\n",
                            "a.md": "# A\n\n### P1. One\n\nBody.\n"})

        result = self.run_lint(root, platform, project, "--index")

        lines = result.stdout.splitlines()
        rule_lines = [line for line in lines if not line.startswith("  ")][:-2]
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(rule_lines, ["B1. One", "B2. Two", "PY1. Py", "P1. One", "P2. Two"])
        self.assertIn("judged rules: 5", lines)

    def test_a_bar_id_shadowed_by_a_project_rule_is_not_credited_in_the_index(self):
        root, platform, project = self.fixture(
            files={"tests/test_a.py": cite("B9") + "\n"}, members=["tests/test_a.py"],
            project_shards={"x.md": "# X\n\n### B9. Shadow\n\nBody.\n"})
        (platform / "stacks" / "python.md").unlink()

        result = self.run_lint(root, platform, project, "--index")

        self.assertEqual(result.returncode, 1)
        self.assertIn("cites B9", result.stdout)
        lines = result.stdout.splitlines()
        self.assertIn("tests/test_a.py:1: cites B9, which is in no applicable layer", lines)
        self.assertEqual(lines[-5:], [
            "B1. One", "B2. Two", "B9. Shadow", "judged rules: 3", "enforcers citing nothing: 0"])

    def test_the_index_still_fails_on_an_unknown_citation(self):
        root, platform, project = self.index_fixture("# " + cite("Z9") + "\n")

        result = self.run_lint(root, platform, project, "--index")

        lines = result.stdout.splitlines()
        self.assertEqual(result.returncode, 1)
        self.assertIn("cites Z9", result.stdout)
        self.assertTrue(lines[-2].startswith("judged rules: "))
        self.assertTrue(lines[-1].startswith("enforcers citing nothing: "))



class PackagingTest(unittest.TestCase):
    def test_the_citation_checks_join_the_one_standards_lint_command(self):
        table = (REPO_ROOT / "lib/agent-tools.nix").read_text("utf-8")

        self.assertIn('"standards-lint" = "delivery.standards_lint";', table)
        self.assertNotIn("delivery.citation_lint", table)


class CheckoutTest(LintTestCase):
    def test_the_lint_passes_on_this_checkout(self):
        result = self.run_lint(
            REPO_ROOT, REPO_ROOT / "home/common/agent-skills/standards", REPO_ROOT / "docs/standards")

        self.assertEqual((result.returncode, result.stdout), (0, ""), result.stderr)

    def test_the_index_is_printed_on_this_checkout_and_writes_nothing(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        status = ["git", "-C", str(REPO_ROOT), "status", "--porcelain", "--untracked-files=all"]
        before = subprocess.run(status, capture_output=True, text=True, env=env, timeout=120).stdout

        result = self.run_lint(
            REPO_ROOT, REPO_ROOT / "home/common/agent-skills/standards",
            REPO_ROOT / "docs/standards", "--index")

        after = subprocess.run(status, capture_output=True, text=True, env=env, timeout=120).stdout
        lines = result.stdout.splitlines()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertRegex(lines[-2], r"judged rules: [0-9]+")
        self.assertRegex(lines[-1], r"enforcers citing nothing: [0-9]+")
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
