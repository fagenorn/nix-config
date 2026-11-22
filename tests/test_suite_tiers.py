"""The tier gate for test files (issue 1385, ADR-delivery-015).

`docs/standards/testing.md` names three tiers, `fast`, `integration` and `nightly`. A
test file added after `BASE` declares one (a top-level `TIER = "<tier>"` in a Python
module, a line `TIER=<tier>` in a shell member) and joins that tier's runner: `fast`
and `integration` in the `agent-workflow-tests` recipe, `nightly` in a nightly recipe
and never in the suite. A test file is one named like a test or listed by a runner
recipe. The gate reads the tracked files, the untracked ones that are not ignored and
the tree of `BASE`, in two git processes whatever the number of files, and a missing
`BASE` fails the gate instead of skipping it.
"""

import ast
import fnmatch
import os
import re
import subprocess
import tempfile
import unittest
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

BASE = "9282d2a404f2e447c55bac067a984c8cff48689e"
REPO_ROOT = Path(__file__).resolve().parents[1]
STANDARD = REPO_ROOT / "docs/standards/testing.md"
TIER = "integration"  # this module reads git history

SUITE_RECIPE = "agent-workflow-tests"
NIGHTLY_RECIPES = (
    "evals",
    "console-screenshots",
    "agent-installed-skill-tests",
    "agent-activated-skill-tests",
)
TEST_NAME_PATTERNS = (
    "test_*.py",
    "*_test.py",
    "test_*.sh",
    "test-*.sh",
    "*-test.sh",
    "*_test.sh",
)
# The eval fixture repository's tests are data the evals copy, never tests of this repository.
FIXTURE_PREFIX = "home/common/agent-skills/evals/fixture-repo/"

SHELL_TIER = re.compile(r"^TIER=([a-z]+)$")
TIER_CELL = re.compile(r"^`([a-z]+)`$")


def standard_tiers(text: str) -> list[str]:
    """The tier names in the table under `## Tiers`, in table order."""
    tiers: list[str] = []
    inside = False
    for line in text.splitlines():
        if line.startswith("## "):
            inside = line.strip() == "## Tiers"
            continue
        if not inside or not line.startswith("|"):
            continue
        cells = line.strip().strip("|").split("|")
        match = TIER_CELL.match(cells[0].strip())
        if match:
            tiers.append(match.group(1))
    return tiers


def declared_tier(path: Path) -> str | None:
    """The tier a test file declares, or None; a missing file raises FileNotFoundError."""
    text = path.read_text()
    if path.suffix == ".py":
        for node in ast.parse(text).body:
            if (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == "TIER"
            ):
                value = node.value
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    return value.value
                return None
        return None
    for line in text.splitlines():
        match = SHELL_TIER.match(line)
        if match:
            return match.group(1)
    return None


def recipe_paths(justfile_text: str, name: str) -> list[str]:
    """The `.py` and `.sh` tokens of the named recipe's body, in order."""
    header = re.compile(r"^" + re.escape(name) + r"(?:\s[^:]*)?:")
    lines = justfile_text.splitlines()
    for index, line in enumerate(lines):
        if header.match(line):
            break
    else:
        raise AssertionError(f"justfile has no {name!r} recipe")
    paths: list[str] = []
    for line in lines[index + 1 :]:
        if not line.startswith("  "):
            break
        for token in line.split():
            token = token.removesuffix("\\")
            token = token.removeprefix("./")
            if token.endswith((".py", ".sh")):
                paths.append(token)
    return paths


def candidates(paths: Iterable[str], justfile_text: str) -> list[str]:
    """Every test file: recipe members of the suite and nightly recipes, and test-named paths."""
    found = set(recipe_paths(justfile_text, SUITE_RECIPE))
    for recipe in NIGHTLY_RECIPES:
        found.update(recipe_paths(justfile_text, recipe))
    for path in paths:
        parts = path.split("/")
        if "fixtures" in parts[:-1] or path.startswith(FIXTURE_PREFIX):
            continue
        if any(fnmatch.fnmatchcase(parts[-1], pattern) for pattern in TEST_NAME_PATTERNS):
            found.add(path)
    return sorted(found)


def _git(*args: str) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k not in ("GIT_DIR", "GIT_WORK_TREE")}
    return subprocess.run(
        ["git", "-C", str(REPO_ROOT), *args], capture_output=True, env=env
    )


def repo_paths() -> list[str]:
    """Tracked and untracked, not ignored, paths of the working tree, in one git call."""
    result = _git("ls-files", "-z", "--cached", "--others", "--exclude-standard")
    if result.returncode != 0:
        raise AssertionError(result.stderr.decode(errors="replace"))
    return [p for p in result.stdout.decode().split("\0") if p]


def base_paths(base: str) -> set[str]:
    """Every path in the tree of `base`, in one git call; a missing commit fails."""
    result = _git("ls-tree", "-r", "-z", "--name-only", f"{base}^{{commit}}")
    if result.returncode != 0:
        stderr = result.stderr.decode(errors="replace")
        raise AssertionError(f"base commit {base} is missing; fetch full history: {stderr}")
    return {p for p in result.stdout.decode().split("\0") if p}


def registration_errors(
    tiers: Mapping[str, str | None],
    suite: set[str],
    nightly: set[str],
    known: Sequence[str],
) -> list[str]:
    """At most one error per path, in sorted path order."""
    errors: list[str] = []
    for path in sorted(tiers):
        tier = tiers[path]
        if tier is None or tier not in known:
            errors.append(f"{path}: declares no known tier")
        elif tier in ("fast", "integration") and path not in suite:
            errors.append(f"{path}: a {tier} test is not a member of {SUITE_RECIPE}")
        elif tier == "nightly" and path in suite:
            errors.append(f"{path}: a nightly test is a member of {SUITE_RECIPE}")
        elif tier == "nightly" and path not in nightly:
            errors.append(f"{path}: a nightly test is registered with no nightly recipe")
    return errors


def justfile_text() -> str:
    return (REPO_ROOT / "justfile").read_text()


class StandardTest(unittest.TestCase):
    def test_the_standard_names_the_three_tiers_in_order(self):
        text = STANDARD.read_text()
        self.assertEqual(standard_tiers(text), ["fast", "integration", "nightly"])

    def test_the_standard_is_indexed(self):
        lines = (REPO_ROOT / "docs/standards/README.md").read_text().splitlines()
        rows = [line for line in lines if line.startswith("| [testing.md](testing.md) |")]
        self.assertEqual(len(rows), 1)
        self.assertIn("`tests/**`", rows[0])


class DeclaredTierTest(unittest.TestCase):
    def declared(self, suffix: str, text: str) -> str | None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / f"member{suffix}"
            path.write_text(text)
            return declared_tier(path)

    def test_a_python_module_declares_its_tier_at_top_level(self):
        cases = {
            'TIER = "fast"\n': "fast",
            'import os\nTIER = "nightly"\n': "nightly",
            'def f():\n    TIER = "fast"\n': None,
            "TIER = 3\n": None,
            'TIER: str = "fast"\n': None,
            "x = 1\n": None,
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(self.declared(".py", text), expected)

    def test_a_shell_member_declares_its_tier_on_its_own_line(self):
        cases = {
            "#!/usr/bin/env bash\nTIER=nightly\n": "nightly",
            "  TIER=fast\n": None,
            "echo TIER=fast\n": None,
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(self.declared(".sh", text), expected)


class RecipePathsTest(unittest.TestCase):
    def test_a_recipe_body_lists_its_test_paths(self):
        text = (
            "x:\n  y.py\n"
            "agent-workflow-tests *args:\n"
            '  PYTHONPATH="p" python3 -m m {{args}} \\\n'
            "    tests/a.py \\\n    b/c.sh\n\n"
            "agent-workflow-tests-x:\n  q.py\n"
            "evals skill id:\n  ./e/run.sh {{skill}}\n"
            "other: build\n  z.py\n"
        )
        self.assertEqual(recipe_paths(text, "agent-workflow-tests"), ["tests/a.py", "b/c.sh"])
        self.assertEqual(recipe_paths(text, "evals"), ["e/run.sh"])
        self.assertEqual(recipe_paths(text, "other"), ["z.py"])
        with self.assertRaises(AssertionError):
            recipe_paths(text, "missing")

    def test_the_real_justfile_has_every_runner(self):
        text = justfile_text()
        suite = recipe_paths(text, SUITE_RECIPE)
        self.assertIn("tests/test_suite_runner.py", suite)
        self.assertIn("tests/test_suite_tiers.py", suite)
        self.assertIn("home/common/agent-skills/evals/tests/test-run-eval-tree.sh", suite)
        for recipe in NIGHTLY_RECIPES:
            with self.subTest(recipe=recipe):
                recipe_paths(text, recipe)
        self.assertIn(
            "tests/test_claude_code_installed.py",
            recipe_paths(text, "agent-installed-skill-tests"),
        )


class CandidatesTest(unittest.TestCase):
    def test_recipe_members_and_named_test_files_are_candidates(self):
        text = (
            "agent-workflow-tests *args:\n  run extra/check.sh\n"
            "evals skill id:\n  run it\n"
            "console-screenshots out=\"\":\n  run it\n"
            "agent-installed-skill-tests: build\n  python3 n/test_n.py\n"
            "agent-activated-skill-tests:\n  run it\n"
        )
        paths = [
            "tests/test-example.sh",
            "tests/helper.py",
            "extra/check.sh",
            "tests/fixtures/x/test_data.py",
            "home/common/agent-skills/evals/fixture-repo/tests/test_cli.py",
            "a/b_test.py",
            "run.sh",
            "home/x/tests/activate-test.sh",
        ]
        self.assertEqual(
            candidates(paths, text),
            [
                "a/b_test.py",
                "extra/check.sh",
                "home/x/tests/activate-test.sh",
                "n/test_n.py",
                "tests/test-example.sh",
            ],
        )


class RegistrationTest(unittest.TestCase):
    known = ["fast", "integration", "nightly"]

    def test_registered_tests_of_each_tier_pass(self):
        tiers = {
            "tests/test_a.py": "fast",
            "tests/test_b.py": "integration",
            "x/test-n.sh": "nightly",
        }
        suite = {"tests/test_a.py", "tests/test_b.py"}
        self.assertEqual(registration_errors(tiers, suite, {"x/test-n.sh"}, self.known), [])

    def test_a_nightly_test_whose_only_registration_is_removed_fails(self):
        tiers = {"x/test-n.sh": "nightly"}
        self.assertEqual(
            registration_errors(tiers, set(), set(), self.known),
            ["x/test-n.sh: a nightly test is registered with no nightly recipe"],
        )

    def test_a_nightly_test_in_the_suite_fails(self):
        tiers = {"x/test-n.sh": "nightly"}
        self.assertEqual(
            registration_errors(tiers, {"x/test-n.sh"}, {"x/test-n.sh"}, self.known),
            ["x/test-n.sh: a nightly test is a member of agent-workflow-tests"],
        )

    def test_an_unregistered_new_shell_test_fails(self):
        tiers = {"tests/test-example.sh": "fast"}
        self.assertEqual(
            registration_errors(tiers, set(), set(), self.known),
            ["tests/test-example.sh: a fast test is not a member of agent-workflow-tests"],
        )

    def test_a_registered_shell_member_without_a_tier_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            check = Path(tmp) / "check.sh"
            check.write_text("#!/usr/bin/env bash\necho ok\n")
            tier = declared_tier(check)
            self.assertEqual(
                registration_errors({"extra/check.sh": tier}, {"extra/check.sh"}, set(), self.known),
                ["extra/check.sh: declares no known tier"],
            )
            check.write_text("TIER=slow\n")
            self.assertEqual(
                registration_errors(
                    {"extra/check.sh": declared_tier(check)}, {"extra/check.sh"}, set(), self.known
                ),
                ["extra/check.sh: declares no known tier"],
            )


class GateTest(unittest.TestCase):
    def test_every_test_added_since_the_base_declares_a_tier_and_joins_its_runner(self):
        text = justfile_text()
        base = base_paths(BASE)
        added = [p for p in candidates(repo_paths(), text) if p not in base]
        self.assertIn("tests/test_suite_tiers.py", added)
        nightly: set[str] = set()
        for recipe in NIGHTLY_RECIPES:
            nightly.update(recipe_paths(text, recipe))
        self.assertEqual(
            registration_errors(
                {p: declared_tier(REPO_ROOT / p) for p in added},
                set(recipe_paths(text, SUITE_RECIPE)),
                nightly,
                standard_tiers(STANDARD.read_text()),
            ),
            [],
        )

    def test_a_missing_base_commit_fails_instead_of_skipping(self):
        with self.assertRaises(AssertionError):
            base_paths("0" * 40)


if __name__ == "__main__":
    unittest.main()
