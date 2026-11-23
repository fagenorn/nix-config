"""A stubbed `engine deliver` run on the fixture project (#1526).

`StubbedRun(test_case, ...)` builds the adopted fixture project, a fake tracker (`ForgeWorld`) that
answers every `gh` call the run makes from the one scenario given to the constructor, and a
launcher stand-in (`tests/fixtures/engine-stubbed-run/claude_stub.py`) that answers each agent step
from the scenario's `replies`. `deliver()` runs `engine deliver <issue>` in the fixture checkout;
the other methods read what the run left: its result line, its run directories and events, the
claim comments and the launches.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

from agent_tools.claims import forge_markers
from agent_tools.delivery import issue_branch
from tests.engine_fixture import FixtureProject
from tests.engine_guards import standin_guard, write_settings
from tests.forge_world import ForgeWorld
from tests.guard_policy_world import REPO_ROOT, GuardPolicyWorld
from tests.test_issue_setup import gh_only

STUB = REPO_ROOT / "tests/fixtures/engine-stubbed-run/claude_stub.py"
APPLIES = {"verdict": "applies", "details": "greet() is still missing.", "evidence": ""}
DIRECT = {"lane": "direct", "why": "A one-file fix with checkable criteria."}
DEFAULT_BODY = ("Add a greet() function to the fixture module.\n\n"
                "## Acceptance criteria\n\n- [ ] greet() returns the greeting\n")
PULL_FIELDS = "number,state,headRefName,closingIssuesReferences"
DROPPED_ENV = ("AGENT_PLATFORM_ROOT", "GITHUB_TOKEN", "GH_TOKEN", "CLAUDE_ACCOUNT")


class StubbedRun:
    def __init__(self, test_case: unittest.TestCase, *, issue: int = 41, title: str = "Add a greeting",
                 body: str = DEFAULT_BODY, state: str = "open", labels=(), comments=(), pulls=(),
                 replies: dict | None = None) -> None:
        self.test = test_case
        self.issue = issue
        self.title = title
        self.world = GuardPolicyWorld(test_case)
        self.fixture = FixtureProject(test_case, self.world)
        self.forge = ForgeWorld(test_case)
        slug = self.fixture.slug
        self.forge.comment_store(slug, issue, comments, labels=list(labels))
        self._respond(slug, issue, title, state, labels, body, list(pulls))
        self.tmp = self.world.tmp / "stubbed-run"
        self.tmp.mkdir()
        self.replies = {"verdict": APPLIES, "lane": DIRECT} if replies is None else replies
        scenario = self.tmp / "scenario.json"
        scenario.write_text(json.dumps(self.replies), encoding="utf-8")
        self.log = self.tmp / "launches.log"
        stub_bin = self.tmp / "bin"
        stub_bin.mkdir()
        launcher = stub_bin / "claude-account"
        launcher.write_text(f"#!/bin/sh\nexec {sys.executable} {STUB} {scenario} {self.log} \"$@\"\n",
                            encoding="utf-8")
        launcher.chmod(0o755)
        self.env = {key: value for key, value in self.world.env.items() if key not in DROPPED_ENV}
        self.env["PATH"] = os.pathsep.join(
            [str(stub_bin), str(gh_only(self.forge, self.tmp / "gh")), self.world.env["PATH"]])
        self.env["FORGE_WORLD"] = str(self.forge.state)
        self._install_home()
        contract_branch = issue_branch.render(self.fixture.branch_pattern, issue,
                                              issue_branch.title_slug(title))
        self.branch: str = contract_branch
        self.worktree_path: Path = self.fixture.worktree_root / (self.fixture.worktree_prefix + contract_branch)

    def _respond(self, slug: str, issue: int, title: str, state: str, labels, body: str,
                 pulls: list) -> None:
        names = [{"name": name} for name in labels]
        issue_json = {"number": issue, "title": title, "state": state, "labels": names, "body": body}
        respond = self.forge.respond_json
        respond("gh", ["api", f"repos/{slug}/issues/{issue}"], issue_json)
        respond("gh", ["api", "--paginate", "--slurp", f"repos/{slug}/pulls?state=open&per_page=100"],
                [[{"number": p["number"], "updated_at": "2026-11-06T10:00:00Z",
                   "head": {"ref": p["headRefName"], "repo": {"full_name": slug}},
                   "base": {"repo": {"full_name": slug}}}
                  for p in pulls if p["state"] == "OPEN"]])
        respond("gh", ["api", "-X", "POST", f"repos/{slug}/labels", "-f", "name=in-progress",
                       "-f", "color=FBCA04"], {"name": "in-progress"})
        respond("gh", ["pr", "list", "--repo", slug, "--state", "all", "--search", str(issue),
                       "--json", PULL_FIELDS], pulls)

    def _install_home(self) -> None:
        home = self.world.home
        write_settings(home, str(standin_guard(self.tmp, "allow-guard", "allow",
                                               str(self.tmp / "guard.log"))))
        declaration = home / ".agents/share/host-declaration.json"
        declaration.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO_ROOT / "home/common/agent-skills/host-declaration.json", declaration)
        role = home / ".claude/agents/reviewer-lite.md"
        role.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO_ROOT / "home/common/claude-code/agents/reviewer-lite.md", role)

    def deliver(self) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "-m", "agent_tools.delivery.engine", "deliver",
                               str(self.issue)], cwd=self.fixture.root, env=self.env,
                              capture_output=True, text=True, timeout=600)

    @staticmethod
    def line(done: subprocess.CompletedProcess) -> dict:
        lines = done.stdout.splitlines()
        if len(lines) != 1:
            raise AssertionError(f"expected one result line, got {done.stdout!r} ({done.stderr!r})")
        return json.loads(lines[0])

    def _run_dirs(self) -> list[Path]:
        root = self.world.home / ".agents/state/engine/runs"
        if not root.is_dir():
            return []
        return sorted(entry for entry in root.iterdir() if (entry / "run.json").is_file())

    @staticmethod
    def _parent(run: Path) -> str | None:
        return json.loads((run / "run.json").read_text(encoding="utf-8")).get("parent")

    def runs(self) -> list[Path]:
        return [run for run in self._run_dirs() if self._parent(run) is None]

    def children(self, run: Path) -> list[Path]:
        return [child for child in self._run_dirs() if self._parent(child) == run.name]

    @staticmethod
    def events(run: Path) -> list[dict]:
        return [json.loads(line) for line in
                (run / "events.jsonl").read_text(encoding="utf-8").splitlines() if line]

    def transitions(self, run: Path) -> list[tuple[str, str]]:
        return [(event["step"], event["outcome"]) for event in self.events(run)
                if event["event"] == "transition_taken"]

    def claims(self) -> list:
        markers = (forge_markers.parse(comment) for comment in self.forge.stored())
        return [marker for marker in markers
                if marker is not None and marker.kind == "claim" and "released" not in marker.fields]

    def launches(self) -> list[dict]:
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines()]
