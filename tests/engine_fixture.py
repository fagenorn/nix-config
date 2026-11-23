"""The engine's fixture project, built in a temporary directory and adopted with the adoption command.

`FixtureProject(test_case, world)` copies `tests/fixtures/engine-fixture-project/` into a new
checkout on `main`, drafts a contract for it from `GuardPolicyWorld.contract`, publishes it to a
local bare `origin`, and runs `adopt-project plan` then `apply` on it exactly as any project is
adopted: no contract is written by hand and nothing is registered. When the adoption cannot reach
a ready plan and a commit, the build fails with the command's own output.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

from tests.guard_policy_world import REPO_ROOT, GuardPolicyWorld

SOURCE = REPO_ROOT / "tests/fixtures/engine-fixture-project"
ADOPT = [sys.executable, "-m", "agent_tools.project_contract.adopt_project"]
MAX_PLANS = 3
TIMEOUT = 300


class FixtureProject:
    VERIFICATION = ["lint", "test"]
    REQUIRED_CHECKS = ["Fixture Checks"]

    def __init__(self, test_case: unittest.TestCase, world: GuardPolicyWorld, *,
                 slug: str = "example/fixture") -> None:
        self.world = world
        self.slug = slug
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

    def _draft(self) -> dict:
        draft = self.world.contract(self.slug, self.slug)
        commands = draft["bindings"]["commands"]
        commands["lint"] = {"argv": [sys.executable, "-m", "py_compile", "fixture/greet.py"],
                            "cwd": ".", "env": []}
        commands["test"] = {"argv": [sys.executable, "-m", "unittest", "discover", "-s", "checks",
                                     "-p", "check_*.py"], "cwd": ".", "env": []}
        for review in ("codex-plan-review", "codex-diff-review"):
            commands[review] = {"argv": [sys.executable, "-c", "pass"], "cwd": ".", "env": []}
        # The fixture has no devenv and signs nothing: the adoption commit runs plain and unsigned.
        commands.pop("commit-environment")
        draft["bindings"]["vcs"]["commit"].update(signed=False)
        del draft["bindings"]["vcs"]["commit"]["environment"]
        draft["bindings"]["workflow"]["verification"] = list(self.VERIFICATION)
        draft["bindings"]["vcs"]["merge"]["required_checks"] = list(self.REQUIRED_CHECKS)
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
        self.world.git(self.root, "add", "-A")
        self.world.git(self.root, "commit", "--quiet", "-m", "fixture source")

    def _run(self, *args: str) -> tuple[int, dict | None, str]:
        done = subprocess.run([*ADOPT, *args], capture_output=True, text=True, timeout=TIMEOUT,
                              env=self.world.env, cwd=self.root)
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
