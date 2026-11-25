"""The engine's fixture project, built in a temporary directory and adopted with the adoption command.

`FixtureProject(test_case, world)` copies `tests/fixtures/engine-fixture-project/` into a new
checkout on `main`, drafts a contract for it from `GuardPolicyWorld.contract`, publishes it to a
local bare `origin`, and runs `adopt-project plan` then `apply` on it exactly as any project is
adopted: no contract is written by hand and nothing is registered. `review_code=True` makes the
independent code review supported through the `codex-companion` command, and `conditions` is the
contract's `verification_conditions`. `required_checks` is the draft's `merge.required_checks`; an empty
one deletes the member, since the resolver refuses an empty list and an absent member means none
declared. `before_pull_request=True` also declares the touched-only test
command and binds `BEFORE_PULL_REQUEST`, over a `suite.just` of two checks of which one imports nothing
from the fixture. When the adoption cannot reach
a ready plan and a commit, the build fails with the command's own output.

`AdoptedFixtures` adopts each distinct set of those options once and hands every later request a copy
(`FixtureProject.copied`): the checkout is copied, re-published to its own bare `origin` in the
requesting world and registered there again. The cache keeps a snapshot of the first fixture's
metadata (`FixtureProject.snapshot`), never the fixture a test holds, and each copy gets its own
`adoption` and `conditions`. `close` removes the cache directory.
"""

from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.guard_policy_world import REPO_ROOT, GuardPolicyWorld

SOURCE = REPO_ROOT / "tests/fixtures/engine-fixture-project"
ADOPT = [sys.executable, "-m", "agent_tools.project_contract.adopt_project"]
MAX_PLANS = 3
TIMEOUT = 300
# The adoption commit takes its author from the environment: a CI runner guesses none from its account.
IDENTITY = {"GIT_AUTHOR_NAME": "fixture", "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
            "GIT_COMMITTER_NAME": "fixture", "GIT_COMMITTER_EMAIL": "fixture@example.invalid"}


class FixtureProject:
    VERIFICATION = ["lint", "test"]
    BEFORE_PULL_REQUEST = ["lint", "test-touched"]
    REQUIRED_CHECKS = ["Fixture Checks"]

    def __init__(self, test_case: unittest.TestCase, world: GuardPolicyWorld, *,
                 slug: str = "example/fixture", review_code: bool = False,
                 conditions: dict | None = None, required_checks=REQUIRED_CHECKS,
                 before_pull_request: bool = False) -> None:
        self.world = world
        self.required_checks = list(required_checks)
        self.before_pull_request = before_pull_request
        self.slug = slug
        self.review_code = review_code
        self.conditions = conditions
        self.root = world.tmp / "fixture"
        shutil.copytree(SOURCE, self.root)
        world.git(self.root, "init", "--quiet", "-b", "main")
        world.git(self.root, "config", "commit.gpgsign", "false")
        draft = self._draft()
        self._commit_source(draft)
        world.publish(self.root, ["main"])
        world.identity(self.root, f"git@github.com:{slug}.git")
        world.provider(slug)
        draft_path = world.tmp / "fixture-draft.json"
        draft_path.write_text(json.dumps(draft, indent=2) + "\n", encoding="utf-8")
        plan = self._plan(draft_path)
        self.adoption = self._adopt(plan["plan"]["plan_id"])
        world.git(self.root, "merge", "--quiet", "--ff-only", self.adoption["commit"])
        world.git(self.root, "push", "--quiet", "origin", "main")
        vcs = draft["bindings"]["vcs"]
        self.branch_pattern: str = vcs["branch_pattern"]
        self.worktree_root: Path = self.root / vcs["worktree"]["root"]
        self.worktree_prefix: str = vcs["worktree"]["prefix"]

    @classmethod
    def copied(cls, world: GuardPolicyWorld, source: Path, template: FixtureProject) -> FixtureProject:
        """A fixture of `template`'s variant: `source` copied into `world` and published there again."""
        fixture = cls.__new__(cls)
        fixture.world = world
        fixture.root = world.tmp / "fixture"
        shutil.copytree(source, fixture.root, symlinks=True)
        world.git(fixture.root, "update-index", "-q", "--refresh")
        world.publish(fixture.root, ["main"])
        world.identity(fixture.root, f"git@github.com:{template.slug}.git")
        world.provider(template.slug)
        fixture.slug = template.slug
        fixture.review_code = template.review_code
        fixture.conditions = copy.deepcopy(template.conditions)
        fixture.required_checks = list(template.required_checks)
        fixture.before_pull_request = template.before_pull_request
        fixture.adoption = copy.deepcopy(template.adoption)
        fixture.branch_pattern = template.branch_pattern
        fixture.worktree_prefix = template.worktree_prefix
        fixture.worktree_root = fixture.root / os.path.relpath(template.worktree_root, template.root)
        return fixture

    def snapshot(self) -> FixtureProject:
        """The metadata of this fixture as it is now, sharing no mutable member with it."""
        template = copy.copy(self)
        template.conditions = copy.deepcopy(self.conditions)
        template.required_checks = list(self.required_checks)
        template.adoption = copy.deepcopy(self.adoption)
        return template

    def _draft(self) -> dict:
        draft = self.world.contract(self.slug, self.slug, publication_free=True)
        commands = draft["bindings"]["commands"]
        commands["lint"] = {"argv": [sys.executable, "-m", "py_compile", "fixture/greet.py"],
                            "cwd": ".", "env": []}
        commands["test"] = {"argv": [sys.executable, "-m", "unittest", "discover", "-s", "checks",
                                     "-p", "check_*.py"], "cwd": ".", "env": []}
        for review in ("codex-plan-review", "codex-diff-review"):
            commands[review] = {"argv": [sys.executable, "-c", "pass"], "cwd": ".", "env": []}
        if self.review_code:
            draft["capabilities"]["review.code"]["support"] = "supported"
            commands["codex-diff-review"]["argv"] = ["codex-companion", "task", "--fresh", "--reviewer",
                                                     "diff-review"]
        if self.conditions is not None:
            draft["bindings"]["workflow"]["verification_conditions"] = self.conditions
        draft["bindings"]["workflow"].pop("verification_before_pull_request", None)
        if self.before_pull_request:
            commands["test-touched"] = {
                "argv": [sys.executable, "-m", "agent_tools.delivery.touched_tests", "--base", "origin/main",
                         "--suite-file", "suite.just", "--cover", "fixture/greet.py=checks/check_greet.py"],
                "cwd": ".", "env": []}
            draft["bindings"]["workflow"]["verification_before_pull_request"] = list(self.BEFORE_PULL_REQUEST)
        # The fixture has no devenv and signs nothing: the adoption commit runs plain and unsigned.
        commands.pop("commit-environment")
        draft["bindings"]["vcs"]["commit"].update(signed=False)
        del draft["bindings"]["vcs"]["commit"]["environment"]
        draft["bindings"]["workflow"]["verification"] = list(self.VERIFICATION)
        merge = draft["bindings"]["vcs"]["merge"]
        if self.required_checks:
            merge["required_checks"] = list(self.required_checks)
        else:
            merge.pop("required_checks", None)
        return draft

    def _commit_source(self, draft: dict) -> None:
        (self.root / ".agents/instructions").mkdir(parents=True)
        (self.root / ".agents/instructions/bootstrap.md").write_text("# invariants\n", "utf-8")
        paths = draft["bindings"]["paths"]
        for name in ("standards", "rejections"):
            for relative in paths[name]:
                (self.root / relative).mkdir(parents=True, exist_ok=True)
                (self.root / relative / "keep.md").write_text("# keep\n", "utf-8")
        for relative in (*paths["context"], *paths["architecture"]):
            target = self.root / relative
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("# knowledge\n", "utf-8")
        (self.root / ".github").mkdir(exist_ok=True)
        (self.root / ".github/lane-paths.json").write_text(
            json.dumps({"version": 1, "sets": {"secrets": ["secrets/"]}}), "utf-8")
        if self.before_pull_request:
            (self.root / "suite.just").write_text(
                "agent-workflow-tests *args:\n  runner {{args}} \\\n    checks/check_greet.py \\\n"
                "    checks/check_other.py\n", "utf-8")
            (self.root / "checks/check_other.py").write_text(
                "import unittest\n\n\nclass OtherTest(unittest.TestCase):\n"
                "    def test_upper(self):\n        self.assertEqual(\"a\".upper(), \"A\")\n", "utf-8")
        self.world.git(self.root, "add", "-A")
        self.world.git(self.root, "commit", "--quiet", "-m", "fixture source")

    def _run(self, *args: str) -> tuple[int, dict | None, str]:
        done = subprocess.run([*ADOPT, *args], capture_output=True, text=True, timeout=TIMEOUT,
                              env={**self.world.env, **IDENTITY}, cwd=self.root)
        try:
            document = json.loads(done.stdout)
        except ValueError:
            document = None
        return done.returncode, document, f"{done.stdout}{done.stderr}"

    def _plan(self, draft_path: Path) -> dict:
        answers: list[str] = []
        last = ""
        for _ in range(MAX_PLANS):
            code, plan, last = self._run("plan", "--repo-root", str(self.root), "--format", "json",
                                         "--contract-draft", str(draft_path), *answers)
            if code != 0 or not isinstance(plan, dict):
                raise AssertionError(f"the fixture's adoption plan failed:\n{last}")
            if plan["plan"]["state"] == "ready":
                return plan
            for question in plan["decisions"]["open"]:
                value = question.get("value")
                if value is None and question.get("answers"):
                    value = question["answers"][0]
                if value is None:
                    raise AssertionError(f"the fixture's adoption plan has an open question "
                                         f"with no answer in the draft:\n{last}")
                answers += ["--answer", question["id"], question["subject"], value]
        raise AssertionError(f"the fixture's adoption plan is not ready after {MAX_PLANS} plans:\n{last}")

    def _adopt(self, plan_id: str) -> dict:
        code, adoption, output = self._run("apply", "--plan-id", plan_id)
        if code != 0 or not isinstance(adoption, dict) or "commit" not in adoption:
            raise AssertionError(f"the fixture's adoption did not apply:\n{output}")
        return adoption


class AdoptedFixtures:
    """Each variant of `FixtureProject` adopted once, then copied into every later world."""

    def __init__(self) -> None:
        self.directory: Path | None = None
        self._templates: dict[str, tuple[Path, FixtureProject]] = {}

    def project(self, test_case: unittest.TestCase, world: GuardPolicyWorld, **options) -> FixtureProject:
        key = json.dumps(options, sort_keys=True)
        if key in self._templates:
            source, template = self._templates[key]
            return FixtureProject.copied(world, source, template)
        if self.directory is None:
            self.directory = Path(tempfile.mkdtemp(prefix="adopted-fixtures-"))
        fixture = FixtureProject(test_case, world, **options)
        source = self.directory / str(len(self._templates)) / "fixture"
        shutil.copytree(fixture.root, source, symlinks=True)
        self._templates[key] = (source, fixture.snapshot())
        return fixture

    def close(self) -> None:
        if self.directory is not None:
            shutil.rmtree(self.directory, ignore_errors=True)
        self.directory = None
        self._templates = {}
