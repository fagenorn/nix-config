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
import shlex
import subprocess
import tempfile
import unittest
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

BASE = "9282d2a404f2e447c55bac067a984c8cff48689e"
REPO_ROOT = Path(__file__).resolve().parents[1]
STANDARD = REPO_ROOT / "docs/standards/testing.md"
TIER = "integration"  # this module reads git history
PROBE_RULE = (
    'A stress probe with large or deeply nested inputs fixes a finite cap on time and peak memory before it starts, starts at a size that fits in 1 GiB, grows in steps (for example doubling), measures time and peak memory at each step and stops before a step whose projected peak would exceed the cap or at the first step that grows faster than its input, never an unbounded loop or one giant input on a shared host. A test that proves a memory bound measures the peak at a small capped size (for example with tracemalloc at a nesting depth whose peak stays under a few hundred MiB) and passes only when that peak is within the claimed limit, never by running the large case.'
)
P19_LINK = " ([issue 1859](https://github.com/fagenorn/nix-config/issues/1859))"

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
TIER_TABLE_HEADER = re.compile(r"^\|\s*Tier\s*\|")
PYTHON_WORD = re.compile(r"^python[0-9.]*$")
MODULE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$")


def standard_tiers(text: str) -> list[str]:
    """The tier names in the table whose header row opens with `Tier`, in table order."""
    tiers: list[str] = []
    inside = False
    for line in text.splitlines():
        if TIER_TABLE_HEADER.match(line):
            inside = True
            continue
        if not line.startswith("|"):
            inside = False
            continue
        if not inside:
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


def _without_comment(line: str) -> str:
    """The line up to a `#` that opens a shell comment: unquoted, at the start of a word."""
    quote = ""
    index = 0
    while index < len(line):
        char = line[index]
        if char == "\\" and quote != "'":
            index += 2
            continue
        if quote:
            if char == quote:
                quote = ""
        elif char in "'\"":
            quote = char
        elif char == "#" and (index == 0 or line[index - 1].isspace()):
            return line[:index]
        index += 1
    return line


def _command_words(line: str) -> list[str]:
    """The words a shell reads from one recipe line: quotes removed, a comment dropped."""
    line = _without_comment(line.rstrip().removesuffix("\\"))
    lexer = shlex.shlex(line, posix=True)
    lexer.whitespace_split = True
    lexer.commenters = ""
    try:
        return list(lexer)
    except ValueError:  # an unbalanced quote: the line continues a quoted string
        return line.split()


def recipe_paths(justfile_text: str, name: str, *, modules: bool = True) -> list[str]:
    """The `.py` and `.sh` arguments of the named recipe's commands, in order.

    A comment names nothing. With `modules`, the argument of `python -m` is a path too,
    its dots turned into slashes and `.py` added.
    """
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
        words = _command_words(line)
        for index, word in enumerate(words):
            if (
                modules
                and word == "-m"
                and 0 < index < len(words) - 1
                and PYTHON_WORD.match(words[index - 1].rsplit("/", 1)[-1])
                and MODULE_NAME.match(words[index + 1])
            ):
                paths.append(words[index + 1].replace(".", "/") + ".py")
            word = word.removeprefix("./")
            if word.endswith((".py", ".sh")):
                paths.append(word)
    return paths


def candidates(paths: Iterable[str], justfile_text: str) -> list[str]:
    """Every test file: recipe members of the suite and nightly recipes, and test-named paths.

    A module a recipe runs with `python -m` counts only when it is one of `paths`.
    """
    repo = set(paths)
    found: set[str] = set()
    for recipe in (SUITE_RECIPE, *NIGHTLY_RECIPES):
        found.update(recipe_paths(justfile_text, recipe, modules=False))
        found.update(path for path in recipe_paths(justfile_text, recipe) if path in repo)
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
        self.assertIn("a stress probe grows in bounded steps from under 1 GiB", rows[0])

    def test_the_standard_states_the_bounded_stress_probe_rule(self):
        lines = STANDARD.read_text().splitlines()
        heading = "### P19. A stress probe grows in bounded steps"
        self.assertEqual(lines.count(heading), 1)
        rest = lines[lines.index(heading) + 1 :]
        end = next((i for i, line in enumerate(rest) if line.startswith("### ")), len(rest))
        body = [line for line in rest[:end] if line.strip()]
        self.assertEqual(body, [PROBE_RULE + P19_LINK])
        self.assertEqual(len(re.findall(r"\.(?=\s|$)", PROBE_RULE)), 2)


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
        self.assertEqual(recipe_paths(text, "agent-workflow-tests"), ["m.py", "tests/a.py", "b/c.sh"])
        self.assertEqual(
            recipe_paths(text, "agent-workflow-tests", modules=False), ["tests/a.py", "b/c.sh"]
        )
        self.assertEqual(recipe_paths(text, "evals"), ["e/run.sh"])
        self.assertEqual(recipe_paths(text, "other"), ["z.py"])
        with self.assertRaises(AssertionError):
            recipe_paths(text, "missing")

    def test_a_comment_names_no_test_path(self):
        text = (
            "evals skill id:\n"
            "  # tests/test_commented.py is not run here\n"
            "  ./e/run.sh {{skill}} # nor is x/test-inline.sh\n"
            '  echo "a # b" q/test_quoted.py\n'
            "  #!/usr/bin/env bash\n"
        )
        self.assertEqual(recipe_paths(text, "evals"), ["e/run.sh", "q/test_quoted.py"])

    def test_a_hash_inside_a_word_is_not_a_comment(self):
        text = (
            "evals skill id:\n"
            "  run ${x#y} tests/test_n.py\n"
            "  run a#b q/test_b.py # tests/test_c.py\n"
            "  run '#' \"#\" r/test_d.py\n"
        )
        self.assertEqual(
            recipe_paths(text, "evals"), ["tests/test_n.py", "q/test_b.py", "r/test_d.py"]
        )

    def test_a_module_run_with_python_dash_m_is_its_path(self):
        text = (
            "console-screenshots out=\"\":\n"
            "  #!/usr/bin/env bash\n"
            '  PW="$b" PYTHONPATH="p" "$py/bin/python3" -m tests.shoot --out "${dir:-x}"\n'
            "  python -m a.b.c \\\n"
            "    x/y.py\n"
            "  git commit -m tests.not_python\n"
            "  python3 -m\n"
            "  python3 -m -x tests.flag\n"
        )
        self.assertEqual(
            recipe_paths(text, "console-screenshots"), ["tests/shoot.py", "a/b/c.py", "x/y.py"]
        )

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
        self.assertIn("tests/console_screenshots.py", recipe_paths(text, "console-screenshots"))


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


class ModuleCandidatesTest(unittest.TestCase):
    others = "".join(
        f"{name}:\n  true\n" for name in (SUITE_RECIPE, *NIGHTLY_RECIPES) if name != "evals"
    )
    text = others + "evals skill id:\n  python3 -m tests.shot\n  python3 -m pkg.tool\n"

    def test_a_module_in_the_repository_is_a_candidate_and_one_outside_it_is_not(self):
        self.assertEqual(candidates(["tests/shot.py", "other.py"], self.text), ["tests/shot.py"])

    def test_a_test_named_in_a_comment_only_is_not_a_candidate_or_a_registration(self):
        text = self.others + "evals skill id:\n  # tests/test_n.py runs here\n  run.sh\n"
        self.assertEqual(candidates(["run.sh"], text), ["run.sh"])
        self.assertNotIn("tests/test_n.py", recipe_paths(text, "evals"))
        self.assertEqual(
            registration_errors(
                {"tests/test_n.py": "nightly"},
                set(),
                set(recipe_paths(text, "evals")),
                ["fast", "integration", "nightly"],
            ),
            ["tests/test_n.py: a nightly test is registered with no nightly recipe"],
        )

    def test_a_nightly_test_run_with_python_dash_m_is_registered(self):
        text = "evals skill id:\n  python3 -m tests.test_n\n"
        self.assertEqual(
            registration_errors(
                {"tests/test_n.py": "nightly"},
                set(),
                set(recipe_paths(text, "evals")),
                ["fast", "integration", "nightly"],
            ),
            [],
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
