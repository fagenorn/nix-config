"""The verification commands `lint` and `test` (issue 1446, ADR-delivery-012).

`just lint` and `just test` run `agent_tools.delivery.verification_command`, which runs
every member of the command and names each one that failed. These tests run the module
and the real recipes, and they compare the lint members with the steps of the
pull-request workflows, so a workflow lint that is not a member fails here.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent_tools.delivery.verification_command import Member, members
from agent_tools.system.siblings import sibling_argv

REPO_ROOT = Path(__file__).resolve().parents[1]
REAL_JUST = shutil.which("just")


def git_env() -> dict[str, str]:
    """The environment with every `GIT_*` variable removed, so no variable the caller
    exported (`GIT_DIR`, `GIT_WORK_TREE`, `GIT_INDEX_FILE`, ...) selects the repository a
    `git -C <dir>` command acts on."""
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def child_env(**extra: str) -> dict[str, str]:
    env = git_env()
    env["PYTHONPATH"] = str(REPO_ROOT / "python")
    env.update(extra)
    return env


def run_entry(command_args, cwd, env):
    return subprocess.run(
        [sys.executable, "-m", "agent_tools.delivery.verification_command", *command_args],
        cwd=cwd, env=env, capture_output=True, text=True, timeout=600)


def stub_just(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "just"
    path.write_text(
        "#!/bin/sh\n"
        "printf '%s\\t%s\\n' \"$PWD\" \"$*\" >> \"$STUB_LOG\"\n"
        "[ \"$1\" = \"${STUB_FAIL:-}\" ] && exit 3\n"
        "[ \"$1\" = \"${STUB_EXEC_FOR:-}\" ] && exec \"$STUB_PYTHON\" -m unittest -v"
        " -k \"$STUB_EXEC_K\" \"$STUB_EXEC_FILE\"\n"
        "exit 0\n", "utf-8")
    path.chmod(0o755)
    return path


def read_stub_log(log: Path) -> list[tuple[str, str]]:
    """The stub's records as (directory, arguments); a tab separates them, so a directory
    holding a space is not split."""
    return [tuple(line.split("\t", 1)) for line in log.read_text().splitlines()]


def module_stderr(result) -> list[str]:
    """stderr lines without the `error: Recipe ...` line `just` itself appends on a failure."""
    return [l for l in result.stderr.splitlines() if not l.startswith("error: Recipe ")]


class JustCase(unittest.TestCase):
    def run_just(self, args, cwd, env):
        # Fail, never skip: CI's suite runs inside a shell that has `just`.
        self.assertIsNotNone(REAL_JUST)
        return subprocess.run(
            [REAL_JUST, *args], cwd=cwd, env=env, capture_output=True, text=True, timeout=600)

    def tmp(self) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        return Path(directory.name).resolve()


class MembersTest(unittest.TestCase):
    def test_lint_members_are_the_repositorys_four_lints_in_order(self):
        root = Path("/r")
        self.assertEqual(members("lint", root), (
            Member("agnostic-lint",
                   (*sibling_argv("delivery.agnostic_lint"), "--root", str(root))),
            Member("context-map-lint",
                   (*sibling_argv("delivery.context_map_lint"), "--repo-root", str(root),
                    "--context-map", str(root / "docs" / "CONTEXT-MAP.md"))),
            Member("skill-lint",
                   (*sibling_argv("skill_lint"), "check", "--root", str(root))),
            Member("dotnet-format",
                   (*sibling_argv("delivery.dotnet_format_lint"), "--root", str(root))),
        ))

    def test_test_members_are_the_build_then_the_suite(self):
        self.assertEqual(members("test", Path("/r")), (
            Member("nix-build", ("just", "build")),
            Member("agent-workflow-tests", ("just", "agent-workflow-tests"),
                   (("WORKFLOW_POLICY_SURFACE", "source"),)),
        ))

    def test_no_lint_member_builds_a_host_configuration(self):
        for m in members("lint", REPO_ROOT):
            for word in ("just", "nix", "build"):
                self.assertNotIn(word, m.argv, m.id)

    def test_an_unknown_command_is_refused(self):
        with self.assertRaises(ValueError):
            members("build", Path("/r"))


class UsageTest(JustCase):
    def test_a_missing_or_unknown_command_is_a_usage_error(self):
        tmp = self.tmp()
        self.assertEqual(run_entry([], tmp, child_env()).returncode, 2)
        self.assertEqual(run_entry(["build"], tmp, child_env()).returncode, 2)


class TestEntryPointTest(JustCase):
    def run_test_recipe(self, fail: str):
        tmp = self.tmp()
        stub_just(tmp / "bin")
        log = tmp / "log"
        env = child_env(PATH=f"{tmp / 'bin'}{os.pathsep}{os.environ['PATH']}",
                        STUB_LOG=str(log), STUB_FAIL=fail)
        result = self.run_just(["--justfile", str(REPO_ROOT / "justfile"), "test"], tmp, env)
        return result, read_stub_log(log)

    def test_a_failing_member_fails_test_naming_it(self):
        result, entries = self.run_test_recipe("build")
        stderr = module_stderr(result)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("test: nix-build failed (exit 3)", stderr)
        self.assertEqual(stderr[-1], "test: failed: nix-build")
        self.assertFalse([l for l in stderr if l.startswith("test: agent-workflow-tests failed")])
        self.assertEqual([args for _, args in entries], ["build", "agent-workflow-tests"])
        for pwd, _ in entries:
            self.assertEqual(Path(pwd).resolve(), REPO_ROOT)

    def test_the_last_member_failing_is_named(self):
        result, _ = self.run_test_recipe("agent-workflow-tests")
        stderr = module_stderr(result)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("test: agent-workflow-tests failed (exit 3)", stderr)
        self.assertEqual(stderr[-1], "test: failed: agent-workflow-tests")

    def test_every_member_passing_passes_test(self):
        result, entries = self.run_test_recipe("")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines()[-1], "test: passed: nix-build, agent-workflow-tests")
        self.assertEqual([args for _, args in entries], ["build", "agent-workflow-tests"])
        for pwd, _ in entries:
            self.assertEqual(Path(pwd).resolve(), REPO_ROOT)

    def test_a_member_that_cannot_start_fails_naming_it(self):
        tmp = self.tmp()
        (tmp / "empty").mkdir()
        result = run_entry(["test"], tmp, child_env(PATH=str(tmp / "empty")))
        stderr = module_stderr(result)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertTrue([l for l in stderr if l.startswith("test: nix-build failed (cannot start")])
        self.assertTrue(
            [l for l in stderr if l.startswith("test: agent-workflow-tests failed (cannot start")])
        self.assertEqual(stderr[-1], "test: failed: nix-build, agent-workflow-tests")


COMPARISON = "test_installed_policy_surface_matches_source_contract"
CONTRACTS = "home/common/agent-skills/tests/test_workflow_skill_contracts.py"


class ActivatedSkillsComparisonTest(JustCase):
    """The host's activated skills are compared with the source only after activation
    (issue 1580): `test` runs the suite source-only, the way CI does, and the kept
    entry point `agent-activated-skill-tests` runs the comparison."""

    def fixture_home(self, differing: bool) -> Path:
        home = self.tmp()
        skills = home / ".claude" / "skills"
        shutil.copytree(REPO_ROOT / "home/common/agent-skills/skills", skills)
        shutil.copytree(REPO_ROOT / "home/common/claude-code/skills", skills, dirs_exist_ok=True)
        bin_dir = home / ".agents" / "bin"
        bin_dir.mkdir(parents=True)
        for name, source in (("resolve-project", "project_contract/resolve_project.py"),
                             ("context-map-lint", "delivery/context_map_lint.py")):
            shutil.copy2(REPO_ROOT / "python/agent_tools" / source, bin_dir / name)
            (bin_dir / name).chmod(0o755)
        if differing:
            entry = skills / "deliver-direct" / "SKILL.md"
            text = entry.read_text(encoding="utf-8")
            self.assertIn("bindings.workflow.verification", text)
            entry.write_text(text.replace("bindings.workflow.verification", "the verification"),
                             encoding="utf-8")
        return home

    def env_for(self, home: Path, **extra: str) -> dict[str, str]:
        env = child_env(HOME=str(home))
        env.pop("WORKFLOW_POLICY_SURFACE", None)
        env.update(extra)
        return env

    def run_comparison(self, home: Path, **extra: str):
        return subprocess.run(
            [sys.executable, "-m", "unittest", "-v", "-k", COMPARISON, CONTRACTS],
            cwd=REPO_ROOT, env=self.env_for(home, **extra), capture_output=True, text=True,
            timeout=600)

    def test_the_test_command_passes_on_a_differing_home_with_the_switch_unset(self):
        home = self.fixture_home(differing=True)
        # Control: run bare, the comparison fails, so the fixture really differs.
        self.assertNotEqual(self.run_comparison(home).returncode, 0)
        # The production `test` command starts the stubbed suite member with the differing
        # home and no switch of its own; only the command's own environment can skip it.
        tmp = self.tmp()
        stub_just(tmp / "bin")
        env = self.env_for(
            home, PATH=f"{tmp / 'bin'}{os.pathsep}{os.environ['PATH']}",
            STUB_LOG=str(tmp / "log"), STUB_EXEC_FOR="agent-workflow-tests",
            STUB_PYTHON=sys.executable, STUB_EXEC_K=COMPARISON, STUB_EXEC_FILE=CONTRACTS)
        result = run_entry(["test"], REPO_ROOT, env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines()[-1],
                         "test: passed: nix-build, agent-workflow-tests")
        self.assertIn("skipped", result.stderr)

    def test_the_kept_entry_point_fails_on_the_same_differing_home(self):
        home = self.fixture_home(differing=True)
        result = self.run_just(
            ["--justfile", str(REPO_ROOT / "justfile"), "agent-activated-skill-tests"],
            REPO_ROOT, self.env_for(home))
        self.assertNotEqual(result.returncode, 0, result.stderr)
        self.assertIn("FAILED", result.stderr)

    def test_the_kept_entry_point_passes_on_a_matching_home(self):
        home = self.fixture_home(differing=False)
        result = self.run_just(
            ["--justfile", str(REPO_ROOT / "justfile"), "agent-activated-skill-tests"],
            REPO_ROOT, self.env_for(home))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_the_kept_entry_point_ignores_the_source_only_switch(self):
        home = self.fixture_home(differing=True)
        result = self.run_just(
            ["--justfile", str(REPO_ROOT / "justfile"), "agent-activated-skill-tests"],
            REPO_ROOT, self.env_for(home, WORKFLOW_POLICY_SURFACE="source"))
        self.assertNotEqual(result.returncode, 0, result.stderr)


def scratch_checkout() -> Path:
    """A fresh git repository holding a copy of the tree, committed once."""
    env = git_env()
    scratch = Path(tempfile.mkdtemp()).resolve()
    listing = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files", "-z", "--cached", "--others",
         "--exclude-standard"], capture_output=True, check=True, env=env).stdout
    for raw in listing.split(b"\0"):
        if not raw:
            continue
        relative = os.fsdecode(raw)
        source = REPO_ROOT / relative
        target = scratch / relative
        if source.is_symlink():
            target.parent.mkdir(parents=True, exist_ok=True)
            os.symlink(os.readlink(source), target)
        elif source.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    for args in (["init", "-q"], ["add", "-A"],
                 ["-c", "user.name=t", "-c", "user.email=t@example.invalid",
                  "-c", "commit.gpgsign=false", "commit", "-qm", "scratch"]):
        subprocess.run(["git", "-C", str(scratch), *args], check=True,
                       capture_output=True, env=env)
    return scratch


class LintEntryPointTest(JustCase):
    @classmethod
    def setUpClass(cls):
        cls.scratch = scratch_checkout()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.scratch, ignore_errors=True)

    def test_lint_passes_on_a_copy_of_the_tree(self):
        result = self.run_just(["lint"], self.scratch, child_env())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines()[-1],
            "lint: passed: agnostic-lint, context-map-lint, skill-lint, dotnet-format")

    def test_an_unformatted_csharp_file_fails_lint_naming_dotnet_format(self):
        fixtures = REPO_ROOT / "tests" / "fixtures" / "dotnet-format"
        shared = self.scratch / "dotnet"
        if not shared.exists():
            shared.mkdir()
            (shared / "AgentTools.slnx").write_text("<Solution />\n", "utf-8")
            self.addCleanup(shutil.rmtree, shared, ignore_errors=True)
        before = {p.relative_to(shared): p.read_bytes() for p in shared.rglob("*") if p.is_file()}
        scratch = scratch_checkout()
        self.addCleanup(shutil.rmtree, scratch, ignore_errors=True)
        shutil.rmtree(scratch / "dotnet", ignore_errors=True)
        project = scratch / "dotnet"
        (project / "Planted").mkdir(parents=True)
        shutil.copy(fixtures / "Planted.slnx.fixture", project / "Planted.slnx")
        shutil.copy(fixtures / "Planted.csproj.fixture", project / "Planted" / "Planted.csproj")
        source = project / "Planted" / "Sample.cs"
        shutil.copy(fixtures / "Unformatted.cs.fixture", source)
        env = child_env(HOME=str(self.tmp()), TMPDIR=str(self.tmp()))
        result = self.run_just(["lint"], scratch, env)
        stderr = module_stderr(result)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("dotnet-format-lint: dotnet format would change files", stderr)
        self.assertIn("lint: dotnet-format failed (exit 1)", stderr)
        self.assertTrue(stderr[-1].startswith("lint: failed:"), stderr[-1])
        self.assertIn("dotnet-format", stderr[-1].removeprefix("lint: failed:").replace(
            " ", "").split(","))
        shutil.copy(fixtures / "Formatted.cs.fixture", source)
        result = self.run_just(["lint"], scratch, env)
        self.assertIn("dotnet-format-lint: passed", result.stdout.splitlines(), result.stderr)
        self.assertFalse([l for l in module_stderr(result)
                          if l.startswith("lint: dotnet-format failed")])
        after = {p.relative_to(shared): p.read_bytes() for p in shared.rglob("*") if p.is_file()}
        self.assertEqual(after, before)

    def test_a_context_map_violation_fails_lint_naming_context_map_lint(self):
        map_path = self.scratch / "docs" / "CONTEXT-MAP.md"
        original = map_path.read_text("utf-8")
        self.assertIn("| Check | Verification |", original)
        map_path.write_text(original.replace("| Check | Verification |", "| Check | Claims |"),
                            "utf-8")
        self.addCleanup(map_path.write_text, original, "utf-8")
        result = self.run_just(["lint"], self.scratch, child_env())
        stderr = module_stderr(result)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("lint: context-map-lint failed (exit 1)", stderr)
        self.assertEqual(stderr[-1], "lint: failed: context-map-lint")
        self.assertFalse([l for l in stderr if l.startswith("lint: agnostic-lint failed")
                          or l.startswith("lint: skill-lint failed")])


class RecipeTest(JustCase):
    def test_lint_and_test_are_argument_free_recipes_running_the_module(self):
        dump = json.loads(self.run_just(
            ["--justfile", str(REPO_ROOT / "justfile"), "--dump", "--dump-format", "json"],
            REPO_ROOT, child_env()).stdout)["recipes"]
        lines = (REPO_ROOT / "justfile").read_text("utf-8").splitlines()
        for name in ("lint", "test"):
            self.assertEqual(dump[name]["parameters"], [], name)
            self.assertEqual(dump[name]["attributes"], [], name)
            self.assertEqual(dump[name]["dependencies"], [], name)
            self.assertEqual(
                lines[lines.index(f"{name}:") + 1],
                f'  PYTHONPATH="{{{{agent_tools_path}}}}" '
                f"python3 -m agent_tools.delivery.verification_command {name}")
            self.assertEqual(len(dump[name]["body"]), 1, name)


# A fail-closed line parser for the workflow shapes this repository uses, after
# tests/test_branch_protection.py: every form it does not understand raises.

TRIGGER_KEY = re.compile(r"^(?:on|\"on\"|'on')\s*:")
NAME = re.compile(r"^[a-z_]+$")
COMMENT_TAIL = re.compile(r"\s+#.*$")
STEP_KEY = re.compile(r"^([A-Za-z_-]+):\s*(.*)$")


def workflow_triggers(path: Path) -> set[str]:
    lines = path.read_text("utf-8").splitlines()
    found = [i for i, line in enumerate(lines) if TRIGGER_KEY.match(line)]
    if len(found) != 1:
        raise AssertionError(f"{path.name}: expected one top-level `on:`, found {len(found)}")
    index = found[0]
    if not lines[index].startswith("on:"):
        raise AssertionError(f"{path.name}: a quoted `on` key is not supported")
    value = COMMENT_TAIL.sub("", lines[index].split(":", 1)[1]).strip()
    if value == "":
        names: set[str] = set()
        entry_indent = None
        for line in lines[index + 1:]:
            if line.strip() == "" or line.lstrip().startswith("#"):
                continue
            if not line.startswith(" "):
                break
            indent = len(line) - len(line.lstrip())
            if entry_indent is None:
                entry_indent = indent
            if indent < entry_indent or entry_indent != 2:
                raise AssertionError(
                    f"{path.name}: trigger entries must be indented two spaces, found {line!r}")
            if indent == entry_indent:
                match = re.match(r"^  ([a-z_]+):", line)
                if not match:
                    raise AssertionError(f"{path.name}: unsupported `on:` line {line!r}")
                names.add(match.group(1))
        return names
    if value.startswith("["):
        if not value.endswith("]"):
            raise AssertionError(f"{path.name}: unsupported `on:` value {value!r}")
        names = {part.strip() for part in value[1:-1].split(",")}
        if not all(NAME.match(name) for name in names):
            raise AssertionError(f"{path.name}: unsupported `on:` value {value!r}")
        return names
    if NAME.match(value):
        return {value}
    raise AssertionError(f"{path.name}: unsupported `on:` value {value!r}")


def pull_request_workflows(directory: Path) -> list[Path]:
    paths = sorted([*directory.glob("*.yaml"), *directory.glob("*.yml")])
    return [p for p in paths
            if workflow_triggers(p) & {"pull_request", "pull_request_target"}]


def _blank_or_comment(line: str) -> bool:
    return line.strip() == "" or line.lstrip().startswith("#")


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _split_jobs(path: Path) -> list[tuple[str, list[str]]]:
    lines = path.read_text("utf-8").splitlines()
    starts = [i for i, line in enumerate(lines) if re.match(r"^jobs:\s*$", line)]
    if len(starts) != 1:
        raise AssertionError(f"{path.name}: expected one top-level `jobs:`, found {len(starts)}")
    jobs: list[tuple[str, list[str]]] = []
    for line in lines[starts[0] + 1:]:
        if _blank_or_comment(line):
            if jobs:
                jobs[-1][1].append(line)
            continue
        if _indent(line) == 0:
            break
        match = re.match(r"^  ([A-Za-z0-9_-]+):\s*$", line)
        if match:
            jobs.append((match.group(1), []))
        elif _indent(line) < 4 or not jobs:
            raise AssertionError(f"{path.name}: unsupported jobs line {line!r}")
        else:
            jobs[-1][1].append(line)
    return jobs


def _job_steps(path: Path, job: str, lines: list[str]) -> list[str]:
    where = f"{path.name}: job {job}"
    steps_at = None
    for i, line in enumerate(lines):
        if _blank_or_comment(line) or _indent(line) != 4:
            continue
        if re.match(r"^    uses:", line):
            raise AssertionError(f"{where}: a reusable workflow is not supported")
        if re.match(r"^    steps:\s*$", line):
            if steps_at is not None:
                raise AssertionError(f"{where}: two `steps:` lines")
            steps_at = i
        elif not re.match(r"^    [A-Za-z0-9_-]+:", line):
            raise AssertionError(f"{where}: unsupported line {line!r}")
    if steps_at is None:
        raise AssertionError(f"{where}: no `steps:`")
    block = []
    for line in lines[steps_at + 1:]:
        if not _blank_or_comment(line) and _indent(line) <= 4:
            break
        block.append(line)
    return block


def _executable(path: Path, job: str, step: list[str]) -> str:
    where = f"{path.name}: job {job}"
    uses, run = [], []
    i = 0
    while i < len(step):
        line = step[i]
        i += 1
        if _blank_or_comment(line):
            continue
        text = line[8:] if line.startswith("      - ") else line.strip() if _indent(line) == 8 else None
        if text is None:
            continue
        match = STEP_KEY.match(text)
        if not match:
            continue
        key, value = match.group(1), match.group(2).rstrip()
        if key == "uses":
            uses.append(value)
        elif key == "run":
            if value == "|":
                body = []
                while i < len(step) and (step[i].strip() == "" or _indent(step[i]) > 8):
                    body.append(step[i])
                    i += 1
                while body and body[-1].strip() == "":
                    body.pop()
                if not body:
                    raise AssertionError(f"{where}: empty `run: |`")
                width = _indent(body[0])
                run.append("\n".join(b[width:].rstrip() for b in body))
            elif value == "" or value[0] in "|>":
                raise AssertionError(f"{where}: unsupported `run:` form {value!r}")
            else:
                # A plain scalar continues on every following line indented past its key.
                parts = [value]
                while i < len(step) and (step[i].strip() == "" or _indent(step[i]) > 8):
                    if not _blank_or_comment(step[i]):
                        parts.append(step[i].strip())
                    i += 1
                run.append(" ".join(parts))
    if len(uses) + len(run) != 1:
        raise AssertionError(f"{where}: a step needs exactly one of `uses:` and `run:`")
    return (uses or run)[0]


def workflow_steps(path: Path) -> list[tuple[str, str, str]]:
    keys: list[tuple[str, str, str]] = []
    for job, lines in _split_jobs(path):
        where = f"{path.name}: job {job}"
        steps: list[list[str]] = []
        for line in _job_steps(path, job, lines):
            if _blank_or_comment(line):
                if steps:
                    steps[-1].append(line)
                continue
            if line.startswith("      - "):
                steps.append([line])
            elif _indent(line) < 8 or not steps:
                raise AssertionError(f"{where}: unsupported step line {line!r}")
            else:
                steps[-1].append(line)
        if not steps:
            raise AssertionError(f"{where}: no steps")
        for step in steps:
            key = (path.name, job, _executable(path, job, step))
            if key in keys:
                raise AssertionError(f"{where}: two equal steps {key[2]!r}")
            keys.append(key)
    return keys


def classify(found, table):
    found, table = set(found), set(table)
    return sorted(found - table), sorted(table - found)


def invokes_module(text: str, module: str) -> bool:
    """Whether `text` runs exactly `-m <module>`, not a module whose name merely contains it."""
    return module in re.findall(r"(?:^|\s)-m\s+([\w.]+)(?![\w.-])", text)


CI_EVAL = (
    "nix eval --show-trace \\\n"
    "  --extra-experimental-features 'nix-command flakes' \\\n"
    "  --raw '.#nixosConfigurations.anis-desktop.config.system.build.toplevel.drvPath'")
SUITE_TIMING_COMPARE = (
    'PYTHONPATH=python python3 -m agent_tools.delivery.suite_timing compare '
    '--head suite-timing/head/suite-timing.json --base suite-timing/base/suite-timing.json '
    '--base-label "$BASE_REF" >> "$GITHUB_STEP_SUMMARY"')
BASE_PLATFORM_READ = "\n".join([
    'base="git+file://$GITHUB_WORKSPACE?rev=${{ github.event.pull_request.base.sha || github.event.before }}"',
    'nix build "$base#agent-platform" --out-link "$RUNNER_TEMP/base-platform"',
    '"$RUNNER_TEMP/base-platform/bin/resolve-project" platform-status --repo-root . '
    '>"$RUNNER_TEMP/base-status.json" 2>"$RUNNER_TEMP/base-warnings.txt" '
    '|| { cat "$RUNNER_TEMP/base-status.json"; exit 1; }',
    "sed 's/^/::warning::/' \"$RUNNER_TEMP/base-warnings.txt\"",
    "jq -e '.compatibility.compatible' \"$RUNNER_TEMP/base-status.json\"",
])
CHECKOUT, INSTALL = "actions/checkout@v4", "DeterminateSystems/nix-installer-action@v4"
SETUP = ("not-lint", "runner setup")

CI_STEP_CLASSES = {
    ("ci.yaml", "flake-checker", CHECKOUT): SETUP,
    ("ci.yaml", "flake-checker", INSTALL): SETUP,
    ("ci.yaml", "nix-eval", CHECKOUT): SETUP,
    ("ci.yaml", "nix-eval", INSTALL): SETUP,
    ("ci.yaml", "agent-workflow-tests", CHECKOUT): SETUP,
    ("ci.yaml", "agent-workflow-tests", INSTALL): SETUP,
    ("ci.yaml", "flake-checker", "DeterminateSystems/flake-checker-action@v5"):
        ("not-lint", "annotates flake.lock health and never fails a run"),
    ("ci.yaml", "nix-eval", CI_EVAL): ("not-lint", "evaluates a host configuration"),
    ("ci.yaml", "nix-eval", "nix build --no-link '.#packages.x86_64-linux.agent-platform'"):
        ("not-lint", "builds the platform package"),
    ("ci.yaml", "nix-eval", "nix eval --raw '.#packages.aarch64-darwin.agent-platform.drvPath'"):
        ("not-lint", "evaluates the macOS platform package"),
    ("ci.yaml", "nix-eval", "nix build --no-link '.#checks.x86_64-linux.agent-platform'"):
        ("not-lint", "runs the platform package with no home configuration"),
    ("ci.yaml", "nix-eval", "nix build --no-link '.#checks.x86_64-linux.omlx-adapter'"):
        ("not-lint", "tests the adapter against its pinned upstream"),
    ("ci.yaml", "agent-workflow-tests",
     "WORKFLOW_POLICY_SURFACE=source nix shell --inputs-from . nixpkgs#just nixpkgs#nodejs "
     "--command just agent-workflow-tests"):
        ("not-lint", "the suite, the test member agent-workflow-tests"),
    ("ci.yaml", "agent-workflow-tests", "actions/upload-artifact@v4"):
        ("not-lint", "uploads the suite timing report"),
    ("ci.yaml", "suite-timing-baseline", "actions/download-artifact@v4"):
        ("not-lint", "downloads the run's suite timing report"),
    ("ci.yaml", "suite-timing-baseline", "actions/cache/save@v4"):
        ("not-lint", "keeps main's suite timing report as the baseline"),
    ("ci.yaml", "suite-timing", CHECKOUT): SETUP,
    ("ci.yaml", "suite-timing", "actions/download-artifact@v4"):
        ("not-lint", "downloads the run's suite timing report"),
    ("ci.yaml", "suite-timing", "actions/cache/restore@v4"):
        ("not-lint", "restores main's suite timing baseline"),
    ("ci.yaml", "suite-timing", SUITE_TIMING_COMPARE):
        ("not-lint", "reports suite time growth over main and never fails a run"),
    ("ci.yaml", "nix-eval", "nix build --no-link '.#checks.x86_64-linux.agnostic-lint'"):
        ("lint", "agnostic-lint"),
    ("conformance.yaml", "conformance", CHECKOUT): SETUP,
    ("conformance.yaml", "conformance", INSTALL): SETUP,
    ("conformance.yaml", "conformance", "nix shell .#agent-platform --command conformance run --purpose ci --lint-times"):
        ("not-lint", "runs the conformance engine against the checkout"),
    ("conformance.yaml", "conformance", BASE_PLATFORM_READ):
        ("not-lint", "reads the head contract with the base platform"),
}


class InvokesModuleTest(unittest.TestCase):
    MODULE = "agent_tools.delivery.agnostic_lint"

    def test_the_complete_module_argument_is_compared(self):
        for text in (f"python3 -m {self.MODULE} --root x", f"python3 -m {self.MODULE}",
                     f"PYTHONPATH=p python3 -m {self.MODULE}\ntouch out",
                     f"python3 -m {self.MODULE}'"):
            with self.subTest(text):
                self.assertTrue(invokes_module(text, self.MODULE))
        for text in (f"python3 -m {self.MODULE}_v2 --root x", f"python3 -m {self.MODULE}.extra",
                     f"python3 -m x.{self.MODULE}", f"python3 -m {self.MODULE}-v2",
                     f"python3 -mx {self.MODULE}", "python3 -m other"):
            with self.subTest(text):
                self.assertFalse(invokes_module(text, self.MODULE))


class CiLintMembersTest(unittest.TestCase):
    def test_every_pull_request_ci_step_is_classified(self):
        found = set()
        for path in pull_request_workflows(REPO_ROOT / ".github" / "workflows"):
            found |= set(workflow_steps(path))
        unclassified, stale = classify(found, CI_STEP_CLASSES)
        self.assertEqual(([], []), (unclassified, stale),
                         f"unclassified: {unclassified}\nstale: {stale}")

    def test_every_pull_request_lint_step_is_a_lint_member(self):
        lint = {m.id: m for m in members("lint", REPO_ROOT)}
        flake = (REPO_ROOT / "flake.nix").read_text("utf-8")
        for key, (kind, member_id) in CI_STEP_CLASSES.items():
            if kind != "lint":
                continue
            self.assertIn(member_id, lint, key)
            member = lint[member_id]
            module = member.argv[member.argv.index("-m") + 1]
            executable = key[2]
            if invokes_module(executable, module):
                continue
            self.assertRegex(executable, rf"\.#checks\.[a-z0-9_-]+\.{re.escape(member_id)}\b")
            start = flake.index(f"{member_id} = ")
            body = flake[start:flake.index("'';", start)]
            self.assertTrue(invokes_module(body, module), key)


class StubLogTest(JustCase):
    def test_a_checkout_path_with_a_space_is_recorded_whole(self):
        tmp = self.tmp()
        stub = stub_just(tmp / "bin")
        checkout = tmp / "nix config"
        checkout.mkdir()
        log = tmp / "log"
        subprocess.run([str(stub), "build", "--flag"], cwd=checkout, check=True,
                       env={**os.environ, "STUB_LOG": str(log), "PWD": str(checkout)})
        self.assertEqual([(Path(pwd), args) for pwd, args in read_stub_log(log)],
                         [(checkout, "build --flag")])


def git_in(repo: Path, *args: str) -> str:
    """Run `git -C repo ...` with no `GIT_*` variable inherited, so the repository acted on is
    `repo` whatever the caller exported."""
    return subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.invalid",
         "-c", "commit.gpgsign=false", *args],
        check=True, capture_output=True, text=True, env=git_env()).stdout


class ScratchCheckoutTest(JustCase):
    def test_repository_selection_variables_do_not_reach_the_callers_checkout(self):
        caller = self.tmp()
        git_in(caller, "init", "-q")
        (caller / "f").write_text("one\n", "utf-8")
        git_in(caller, "add", "f")
        git_in(caller, "commit", "-qm", "base")
        (caller / "f").write_text("two\n", "utf-8")
        git_in(caller, "add", "f")
        (caller / "f").write_text("three\n", "utf-8")

        def state():
            return [git_in(caller, *args)
                    for args in (["rev-parse", "HEAD"], ["diff", "--cached"], ["diff"])]

        before = state()
        polluted = {"GIT_DIR": str(caller / ".git"), "GIT_WORK_TREE": str(caller),
                    "GIT_INDEX_FILE": str(caller / ".git" / "index")}
        with mock.patch.dict(os.environ, polluted):
            self.assertFalse([k for k in child_env() if k.startswith("GIT_")])
            scratch = scratch_checkout()
        self.addCleanup(shutil.rmtree, scratch, True)
        self.assertEqual(state(), before)
        self.assertTrue((scratch / ".git").is_dir())
        self.assertEqual(git_in(scratch, "log", "--format=%s").split(), ["scratch"])


class ScratchCheckoutUnderGitDirTest(JustCase):
    def test_the_scratch_checkout_test_leaves_a_repository_named_by_git_dir_alone(self):
        # A hook or wrapper exports GIT_DIR with no GIT_WORK_TREE; the test's own git
        # calls must not stage, commit or read in that repository.
        caller = self.tmp()
        git_in(caller, "init", "-q")
        (caller / "g").write_text("one\n", "utf-8")
        git_in(caller, "add", "g")
        git_in(caller, "commit", "-qm", "base")
        (caller / "g").write_text("two\n", "utf-8")
        git_in(caller, "add", "g")
        before = [git_in(caller, *args) for args in (
            ["rev-parse", "HEAD"], ["diff", "--cached", "--name-status"], ["status", "--short"])]
        env = {**os.environ, "GIT_DIR": str(caller / ".git"), "PYTHONPATH": str(REPO_ROOT / "python")}
        env.pop("GIT_WORK_TREE", None)
        env.pop("GIT_INDEX_FILE", None)
        result = subprocess.run(
            [sys.executable, "-m", "unittest", "tests.test_verification_command."
             "ScratchCheckoutTest.test_repository_selection_variables_do_not_reach_the_callers_checkout"],
            cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=600)
        after = [git_in(caller, *args) for args in (
            ["rev-parse", "HEAD"], ["diff", "--cached", "--name-status"], ["status", "--short"])]
        self.assertEqual(after, before)
        self.assertEqual(result.returncode, 0, result.stderr)


class CiParserTest(JustCase):
    JOB = "jobs:\n  lint:\n    runs-on: x\n    steps:\n      - run: {run}\n"

    def workflow(self, directory: Path, name: str, on: str, run: str = "x") -> Path:
        path = directory / name
        path.write_text(f"name: W\n\n{on}\n\n" + self.JOB.format(run=run), "utf-8")
        return path

    def test_a_flow_list_trigger_is_a_pull_request_workflow(self):
        directory = self.tmp()
        run = "python3 -m agent_tools.delivery.context_map_lint"
        path = self.workflow(directory, "w.yaml", "on: [pull_request]", run)
        self.assertEqual(pull_request_workflows(directory), [path])
        self.assertIn(("w.yaml", "lint", run),
                      classify(workflow_steps(path), CI_STEP_CLASSES)[0])

    def test_a_scalar_trigger_is_a_pull_request_workflow(self):
        directory = self.tmp()
        run = "python3 -m agent_tools.delivery.context_map_lint"
        path = self.workflow(directory, "w.yaml", "on: pull_request_target", run)
        self.assertEqual(pull_request_workflows(directory), [path])
        self.assertIn(("w.yaml", "lint", run),
                      classify(workflow_steps(path), CI_STEP_CLASSES)[0])
        other = self.tmp()
        self.workflow(other, "w.yaml", "on: push", run)
        self.assertEqual(pull_request_workflows(other), [])

    def test_an_unsupported_trigger_form_fails(self):
        fixtures = {
            "flow mapping": "on: {pull_request: {}}",
            "quoted key": '"on":\n  pull_request:',
            "block list": "on:\n  - pull_request",
            "no trigger": "env: {}",
        }
        for label, on in fixtures.items():
            with self.subTest(label):
                directory = self.tmp()
                self.workflow(directory, "w.yaml", on)
                with self.assertRaises(AssertionError) as caught:
                    pull_request_workflows(directory)
                self.assertIn("w.yaml", str(caught.exception))

    def test_a_trigger_indented_beyond_two_spaces_is_refused(self):
        directory = self.tmp()
        self.workflow(directory, "w.yaml", "on:\n    pull_request:\n      branches: [main]",
                      "python3 -m agent_tools.delivery.context_map_lint")
        with self.assertRaises(AssertionError) as caught:
            pull_request_workflows(directory)
        self.assertIn("w.yaml", str(caught.exception))

    def test_a_continuation_line_of_an_inline_run_is_part_of_the_step(self):
        directory = self.tmp()
        path = directory / "w.yaml"
        path.write_text("name: W\non: pull_request\njobs:\n  j:\n    steps:\n"
                        "      - run: nix build x\n          && ruff check .\n"
                        "          && ruff format .\n      - run: y\n", "utf-8")
        self.assertEqual(workflow_steps(path), [
            ("w.yaml", "j", "nix build x && ruff check . && ruff format ."),
            ("w.yaml", "j", "y")])

    def test_a_lint_continued_onto_a_classified_inline_run_is_unclassified(self):
        directory = self.tmp()
        lines = (REPO_ROOT / ".github" / "workflows" / "ci.yaml").read_text("utf-8").splitlines()
        original = "nix build --no-link '.#checks.x86_64-linux.omlx-adapter'"
        at = next(i for i, line in enumerate(lines) if line.endswith(f"run: {original}"))
        lines.insert(at + 1, "          && PYTHONPATH=python python3 -m agent_tools.delivery.context_map_lint")
        copy = directory / "ci.yaml"
        copy.write_text("\n".join(lines) + "\n", "utf-8")
        unclassified, stale = classify(workflow_steps(copy), CI_STEP_CLASSES)
        self.assertEqual(len(unclassified), 1)
        self.assertTrue(unclassified[0][2].startswith(original + " && "))
        self.assertIn(("ci.yaml", "nix-eval", original), stale)

    def test_a_lint_appended_to_a_classified_step_is_unclassified(self):
        directory = self.tmp()
        lines = (REPO_ROOT / ".github" / "workflows" / "ci.yaml").read_text("utf-8").splitlines()
        added = "          PYTHONPATH=python python3 -m agent_tools.delivery.context_map_lint"
        at = next(i for i, line in enumerate(lines) if line.endswith("toplevel.drvPath'"))
        lines.insert(at + 1, added)
        copy = directory / "ci.yaml"
        copy.write_text("\n".join(lines) + "\n", "utf-8")
        unclassified, stale = classify(workflow_steps(copy), CI_STEP_CLASSES)
        self.assertEqual(len(unclassified), 1)
        self.assertEqual(unclassified[0][:2], ("ci.yaml", "nix-eval"))
        self.assertTrue(unclassified[0][2].endswith(added.strip()))
        self.assertIn(("ci.yaml", "nix-eval", CI_EVAL), stale)

    def test_an_unsupported_step_form_fails(self):
        head = "name: W\non: pull_request\njobs:\n  j:\n"
        fixtures = {
            "reusable workflow": head + "    uses: ./.github/workflows/x.yaml\n",
            "no steps": head + "    runs-on: x\n",
            "folded run": head + "    steps:\n      - run: >-\n          x\n",
            "neither": head + "    steps:\n      - name: x\n",
            "four-space step": head + "    steps:\n    - run: x\n",
            "two equal steps": head + "    steps:\n      - run: x\n      - run: x\n",
        }
        for label, text in fixtures.items():
            with self.subTest(label):
                directory = self.tmp()
                path = directory / "w.yaml"
                path.write_text(text, "utf-8")
                with self.assertRaises(AssertionError) as caught:
                    workflow_steps(path)
                self.assertIn("w.yaml", str(caught.exception))
                self.assertIn("j", str(caught.exception).split("job", 1)[1])


if __name__ == "__main__":
    unittest.main()
