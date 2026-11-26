"""A stubbed `engine deliver` run on the fixture project.

`StubbedRun(test_case, ...)` builds the adopted fixture project, a fake tracker (`ForgeWorld`) that
answers every `gh` call the run makes from the one scenario given to the constructor, and a
launcher stand-in (`tests/fixtures/engine-stubbed-run/claude_stub.py`) that answers each agent step
from the scenario's `replies`. `deliver()` runs `engine deliver <issue>` in the fixture checkout;
the other methods read what the run left: its result line, its run directories and events, the
claim comments and the launches. `replies` overrides the default replies by step id (an entry
`<step>.<visit>` answers that visit only); `review_code` is the answer list of the `codex-companion`
stand-in that makes the independent code review supported; `conditions` is the contract's
`verification_conditions`; `before_pull_request` makes the fixture declare the pre-pull-request
commands (lint and the touched-only test), and `slot_history()` reads the slot's history lines.
`fixtures` is an `AdoptedFixtures` that supplies the fixture as a copy of one adopted once; `None`
adopts a new one.

The run installs the real lifecycle guard on a confirmed row for the fixture (the fixture's owner is
not an authorized owner, so only the row authorizes it): `guard(text, cwd)` runs the installed hook
and `guard_log` holds every payload it judged. A fake pull-request forge
(`tests/fixtures/engine-stubbed-run/gh_pulls.py`) fronts the tracker's `gh` over the bare origin;
`pulls()`, `lock_refs()` and `origin_tip(branch)` read what it left, and `visited_steps()` the
(procedure, step) pairs every run entered (`visited()` their step ids). `required_checks` is the
contract's `merge.required_checks` (`()` declares none and the member is absent), `rollup` the pull
requests' `statusCheckRollup` (default: one green `Fixture Checks` run), `forge_events` the one-shot
events that fire on the first `statusCheckRollup` read of a pull request (`"move-head"` adds a commit
to the head branch, `"steal-lock"` hands the land lock of `main` to a second open pull request headed
at `stolen_sha`; `"steal-lock-at-head"` and `"drop-lock-at-head"` fire once each, before the answer,
on a read of `headRefOid` alone: the first as `steal-lock`, the second deleting the lock ref), and
`lock_release_fails` makes every compare-and-swap delete of the land lock refused.

`rollups` answers the i-th distinct head a pull request's rollup is read at with
`rollups[min(i, len(rollups) - 1)]` (`rollup` otherwise); `advance_main` commits once to the bare's
`main` after each of the first n reads of `statusCheckRollup` (`main_change`, `{"path", "text"}`, is
the first one's file, the others add `main-<k>.txt`); `merge_behind` makes each of the first n merges
commit to `main` and fail as not up to date; `merge_policy` makes each of the first n merges fail
on the base branch policy, after which one read of `mergeStateStatus` answers `BLOCKED`. A pull
request's `mergeStateStatus` is `BEHIND` while `main` is not an ancestor of its head, else `CLEAN`.
The environment always sets `LANDING_BOUND_SECONDS` to 0 (no wait on a lock or a pending check).
The replies' `merge`, `same_head`, `leave` and `upstream` effects (see the launcher stand-in) are given the
run's worktree and bare origin when they name none. `extra_files` (relative path to text) is passed to
`FixtureProject`: each file is committed on `main` after the adoption, outside every branch diff.
A resumed session that answered replays its recorded answer and runs no effect again.
`answer(step, entry)` sets `replies[step]` to `entry` with its effects filled the same way and rewrites
the scenario file (`self.scenario`) the stub reads, so the next `deliver()` answers `step` with `entry`.

`blocks` is the issue numbers the issue blocks (the answer to the hold path's blocking read; none by
default). The world also answers the `needs-verification` label creation of the hold path and of its
split children, and registers no `gh auth status`, so the close-out's `verify-pending run` does nothing. `fail_once` is the tracker's one-shot
failures, as `ForgeWorld.comment_store` takes them (a bare operation kind, or `add_label:<label>` for one label).
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
import unittest
from collections.abc import Mapping
from pathlib import Path

from agent_tools.claims import forge_markers
from agent_tools.delivery import issue_branch
from agent_tools.delivery.engine_guard import payload
from tests.engine_fixture import AdoptedFixtures, FixtureProject
from tests.engine_guards import script, standin_guard, write_settings
from tests.forge_world import ForgeWorld
from tests.guard_policy_world import REAL_GIT, REPO_ROOT, GuardPolicyWorld
from tests.test_issue_setup import gh_only

STUB = REPO_ROOT / "tests/fixtures/engine-stubbed-run/claude_stub.py"
COMPANION = REPO_ROOT / "tests/fixtures/engine-stubbed-run/codex_companion_stub.py"
GH_PULLS = REPO_ROOT / "tests/fixtures/engine-stubbed-run/gh_pulls.py"
GUARD_GIT = REPO_ROOT / "tests/fixtures/engine-stubbed-run/guard_git.py"
GUARD_SOURCE = REPO_ROOT / "home/common/claude-code/lifecycle_guard.py"
LOCKS = "refs/agent-locks/land/"
GREEN = [{"__typename": "CheckRun", "name": "Fixture Checks", "status": "COMPLETED",
          "conclusion": "SUCCESS", "startedAt": "2026-11-06T10:00:00Z", "workflowName": "Fixture"}]
ROLES = REPO_ROOT / "home/common/claude-code/agents"
APPLIES = {"verdict": "applies", "details": "greet() is still missing.", "evidence": ""}
CLEAN_LITE = {"verdict": "pass", "findings": [],
              "acceptance": [{"id": "AC1", "met": True, "evidence": "checks/check_greet.py:8"}],
              "escalate": False}
IMPLEMENTED = {
    "reply": {"status": "done", "notes": "Added farewell().",
              "acceptance": [{"id": "AC1", "text": "greet() returns the greeting", "kind": "code",
                              "result": "checks/check_greet.py fails without it"}],
              "sensitive": False, "ineligible": False, "tests": ["checks/check_greet.py"]},
    "commit": {"path": "fixture/farewell.py",
               "text": 'def farewell(name: str) -> str:\n    return f"Goodbye, {name}."\n'}}
VALIDATOR_UNIMPORTABLE_ENGINE = (
    "import sys\n"
    "sys.modules['agent_tools.delivery.procedure_check'] = None\n"
    "sys.modules['agent_tools.delivery.size_caps'] = None\n"
    "from agent_tools.delivery import engine\n"
    "sys.exit(engine.main(sys.argv[1:]))\n")
NOT_BEFORE = {"not_before": "2099-01-01T00:00:00Z"}
EVIDENCE_CHECK = {"ac": "AC2", "kind": "evidence", "host": "any", "when": NOT_BEFORE,
                  "run": {"command": "test"}}
EVIDENCE_BODY = ("Add a greet() function.\n\n## Acceptance criteria\n\n"
                 "- [ ] [code] greet() returns the greeting\n"
                 "- [ ] [evidence] the owner has seen the greeting\n")
REGRADED = {"verdict": "met", "code_unmet": [],
            "acceptance": [{"id": "AC1", "met": True, "evidence": "checks/check_greet.py:8"}]}


def drafted(*checks: dict) -> dict:
    """A `hold-draft` reply that drafted `checks`, each written under its criterion id."""
    return {"verdict": "drafted", "written": [{"ac": c["ac"], "check": json.dumps(c)} for c in checks],
            "detail": ""}


DEFAULT_REPLIES = {"applies": APPLIES, "implement": IMPLEMENTED, "lite-review": CLEAN_LITE,
                   "hold-draft": drafted(EVIDENCE_CHECK), "regrade": REGRADED}
DEFAULT_BODY = ("Add a greet() function to the fixture module.\n\n"
                "## Acceptance criteria\n\n- [ ] [code] greet() returns the greeting\n")
PULL_FIELDS = "number,state,headRefName,closingIssuesReferences"
DROPPED_ENV = ("AGENT_PLATFORM_ROOT", "GITHUB_TOKEN", "GH_TOKEN", "CLAUDE_ACCOUNT",
               "CLAUDE_CODE_SESSION_ID")


class StubbedRun:
    def __init__(self, test_case: unittest.TestCase, *, issue: int = 41, title: str = "Add a greeting",
                 body: str = DEFAULT_BODY, state: str = "open", labels=(), comments=(), pulls=(),
                 replies: dict | None = None, review_code: list | None = None,
                 conditions: dict | None = None, required_checks=FixtureProject.REQUIRED_CHECKS,
                 rollup: list | None = None, forge_events=(), lock_release_fails: bool = False,
                 before_pull_request: bool = False, rollups: list[list] | None = None,
                 advance_main: int = 0, main_change: dict | None = None, merge_behind: int = 0,
                 merge_policy: int = 0, blocks=(), fail_once=(),
                 fixtures: AdoptedFixtures | None = None,
                 extra_files: Mapping[str, str] | None = None) -> None:
        self.test = test_case
        self.issue = issue
        self.title = title
        self.world = GuardPolicyWorld(test_case)
        self.companion_log = self.world.tmp / "companion.log"
        if review_code is not None:
            self._install_companion(review_code)
        options = {"review_code": review_code is not None, "conditions": conditions,
                   "required_checks": required_checks, "before_pull_request": before_pull_request}
        if extra_files:
            options["extra_files"] = dict(extra_files)
        self.fixture = (FixtureProject(test_case, self.world, **options) if fixtures is None
                        else fixtures.project(test_case, self.world, **options))
        self.forge = ForgeWorld(test_case)
        slug = self.fixture.slug
        self.forge.comment_store(slug, issue, comments, labels=list(labels), fail_once=list(fail_once))
        self._respond(slug, issue, title, state, labels, body, list(pulls), list(blocks))
        self.tmp = self.world.tmp / "stubbed-run"
        self.tmp.mkdir()
        self.branch: str = issue_branch.render(self.fixture.branch_pattern, issue,
                                               issue_branch.title_slug(title))
        self.worktree_path: Path = self.fixture.worktree_root / (self.fixture.worktree_prefix + self.branch)
        self.bare = self.world.git(self.fixture.root, "remote", "get-url", "origin").strip()
        self.replies = self._with_worktree({**DEFAULT_REPLIES, **(replies or {})})
        self.scenario = self.tmp / "scenario.json"
        self.scenario.write_text(json.dumps(self.replies), encoding="utf-8")
        self.log = self.tmp / "launches.log"
        stub_bin = self.tmp / "bin"
        stub_bin.mkdir()
        launcher = stub_bin / "claude-account"
        launcher.write_text(f"#!/bin/sh\nexec {sys.executable} {STUB} {self.scenario} {self.log} \"$@\"\n",
                            encoding="utf-8")
        launcher.chmod(0o755)
        self.env = {key: value for key, value in self.world.env.items() if key not in DROPPED_ENV}
        forge_gh = gh_only(self.forge, self.tmp / "gh") / "gh"
        self.env["LANDING_BOUND_SECONDS"] = "0"
        self.stolen_sha: str | None = (hashlib.sha1(b"steal-lock").hexdigest() if any(
            name in forge_events for name in ("steal-lock", "steal-lock-at-head")) else None)
        pulls_bin = self._install_pulls(
            forge_gh, slug, GREEN if rollup is None else rollup, forge_events,
            {"rollups": rollups, "advance": advance_main, "main_change": main_change,
             "merge_behind": merge_behind, "merge_policy": merge_policy})
        self.env["PATH"] = os.pathsep.join(
            [str(stub_bin), str(pulls_bin), str(forge_gh.parent), self.world.env["PATH"]])
        self.env["FORGE_WORLD"] = str(self.forge.state)
        self.env["VERIFY_SLOT_DIR"] = str(self.tmp / "verify-slots")
        self.forge.ref_store(slug, {}, **({"refuse_to": ["0" * 40]} if lock_release_fails else {}))
        self._install_home(pulls_bin / "gh", slug)

    def _install_pulls(self, forge_gh: Path, slug: str, rollup: list, events, knobs: dict) -> Path:
        """The directory of the `gh` front that answers pull-request calls over the bare origin."""
        root = self.fixture.root
        git = self.world.git
        git(root, "remote", "set-head", "origin", "main")
        self.pulls_state = self.tmp / "pulls.json"
        sha = self.stolen_sha
        self.pulls_state.write_text(json.dumps({
            "slug": slug, "bare": self.bare, "git": REAL_GIT, "next": 1, "pulls": [], "rollup": rollup,
            "events": [{"event": name, "sha": sha} for name in events],
            "rollup_heads": [], "advanced": 0, "main_moves": 0, "blocked_once": False, **knobs}),
            encoding="utf-8")
        return script(self.tmp / "pulls-bin" / "gh", sys.executable, str(GH_PULLS),
                      str(self.pulls_state), str(forge_gh)).parent

    def answer(self, step: str, entry: dict) -> None:
        """Answer `step` with `entry` from the next delivery on, every other entry unchanged."""
        self.replies[step] = self._with_worktree({step: entry})[step]
        self.scenario.write_text(json.dumps(self.replies), encoding="utf-8")

    def _with_worktree(self, replies: dict) -> dict:
        """The replies, each `commit`, `merge`, `same_head` and `leave` effect without a worktree made in
        the run's worktree and each `upstream` effect without a bare made in the bare origin."""
        filled = copy.deepcopy(replies)
        for entry in filled.values():
            for effect, member, value in (("commit", "worktree", self.worktree_path),
                                          ("merge", "worktree", self.worktree_path),
                                          ("same_head", "worktree", self.worktree_path),
                                          ("leave", "worktree", self.worktree_path),
                                          ("upstream", "bare", self.bare)):
                if isinstance(entry.get(effect), dict) and member not in entry[effect]:
                    entry[effect][member] = str(value)
        return filled

    def _install_companion(self, answers: list) -> None:
        shims = self.world.tmp / "companion"
        shims.mkdir()
        answers_path = shims / "answers.json"
        answers_path.write_text(json.dumps(answers), encoding="utf-8")
        shim = shims / "codex-companion"
        shim.write_text(f"#!/bin/sh\nexec {sys.executable} {COMPANION} {answers_path} "
                        f"{self.companion_log} \"$@\"\n", encoding="utf-8")
        shim.chmod(0o755)
        self.world.env["PATH"] = os.pathsep.join([str(shims), self.world.env["PATH"]])

    def _respond(self, slug: str, issue: int, title: str, state: str, labels, body: str,
                 pulls: list, blocks: list) -> None:
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
        respond("gh", ["api", f"repos/{slug}/issues/{issue}/dependencies/blocking"],
                [{"number": n} for n in blocks])
        respond("gh", ["api", "-X", "POST", f"repos/{slug}/labels", "-f", "name=needs-verification",
                       "-f", "color=1D76DB"], {"name": "needs-verification"})

    def _install_home(self, gh_bin: Path, slug: str) -> None:
        home = self.world.home
        root = self.fixture.root
        git_bin = script(self.tmp / "guard-git", sys.executable, str(GUARD_GIT), str(root),
                         f"git@github.com:{slug}.git", REAL_GIT)
        self.world.write_base(
            authorized_owners=["fagenorn"], integration_bases={}, git_bin=str(git_bin),
            gh_bin=str(gh_bin), jq_bin=shutil.which("jq") or "/usr/bin/jq")
        self.world.register({"project_id": "example/fixture", "root": str(root)})
        code, report, stderr = self.world.compile()
        self.test.assertEqual((code, report["derived"]), (0, [slug]), f"{report} {stderr}")
        row = self.world.policy()["derived_repositories"][slug]
        self.test.assertEqual(row["required_checks"], list(self.fixture.required_checks))
        look = self.tmp / "look-bin"
        look.write_text(
            f"#!{sys.executable}\nimport os\nimport sys\n"
            f"os.environ['PYTHONPATH'] = {str(REPO_ROOT / 'python')!r}\n"
            "os.execv(sys.executable, [sys.executable, '-m', 'agent_tools.delivery.look_approval',"
            " 'judge', *sys.argv[1:]])\n", encoding="utf-8")
        look.chmod(0o755)
        self.guard_log = self.tmp / "guard.log"
        real = script(self.tmp / "real-guard", sys.executable, "-I", str(GUARD_SOURCE),
                      "--base-policy", str(self.world.base), "--policy", str(self.world.output),
                      "--derive-bin", str(self.world.row_check()), "--look-bin", str(look),
                      "--derive-timeout-seconds", "25")
        write_settings(home, str(standin_guard(self.tmp, "tee-guard", "tee", str(self.guard_log),
                                               str(real))))
        declaration = home / ".agents/share/host-declaration.json"
        declaration.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO_ROOT / "home/common/agent-skills/host-declaration.json", declaration)
        (home / ".claude/agents").mkdir(parents=True, exist_ok=True)
        for name in ("implementer", "reviewer", "reviewer-lite"):
            shutil.copy(ROLES / f"{name}.md", home / ".claude/agents" / f"{name}.md")

    def deliver(self, procedures: Path | None = None, *,
                validator_unimportable: bool = False) -> subprocess.CompletedProcess:
        """`engine deliver <issue>` in the fixture checkout, with the procedures in `procedures` when given.

        `validator_unimportable` runs the engine in a process that cannot import the check or the cap checker.
        """
        extra = ["--procedures", str(procedures)] if procedures is not None else []
        entry = ["-c", VALIDATOR_UNIMPORTABLE_ENGINE] if validator_unimportable else ["-m", "agent_tools.delivery.engine"]
        return subprocess.run([sys.executable, *entry, "deliver", str(self.issue), *extra],
                              cwd=self.fixture.root, env=self.env, capture_output=True, text=True, timeout=600)

    def slot_history(self) -> list[dict]:
        """The lines the verification slot recorded, `[]` when it recorded none."""
        path = Path(self.env["VERIFY_SLOT_DIR"]) / "history.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]

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

    def visited_steps(self) -> set[tuple[str, str]]:
        """The (procedure, step) of every `step_entered` and `transition_taken` event of every run, root and child."""
        return {(json.loads((run / "run.json").read_text(encoding="utf-8"))["procedure"], event["step"])
                for run in self._run_dirs() for event in self.events(run)
                if event["event"] in ("step_entered", "transition_taken")}

    def visited(self) -> set[str]:
        """The step ids `visited_steps` holds, whatever procedure each belongs to."""
        return {step for _, step in self.visited_steps()}

    def transitions(self, run: Path) -> list[tuple[str, str]]:
        return [(event["step"], event["outcome"]) for event in self.events(run)
                if event["event"] == "transition_taken"]

    def claims(self) -> list:
        markers = (forge_markers.parse(comment) for comment in self.forge.stored())
        return [marker for marker in markers
                if marker is not None and marker.kind == "claim" and "released" not in marker.fields]

    def companion_launches(self) -> list[dict]:
        if not self.companion_log.exists():
            return []
        return [json.loads(line) for line in self.companion_log.read_text(encoding="utf-8").splitlines()]

    def launches(self) -> list[dict]:
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines()]

    def pulls(self) -> list[dict]:
        """The fake forge's pull requests now."""
        return json.loads(self.pulls_state.read_text(encoding="utf-8"))["pulls"]

    def lock_refs(self) -> dict:
        """The land lock refs of the tracker fake's ref store now."""
        return {ref: sha for ref, sha in self.forge.refs().items() if ref.startswith(LOCKS)}

    def origin_tip(self, branch: str) -> str | None:
        """The tip of `branch` in the bare origin, or None when it is not there."""
        done = subprocess.run([REAL_GIT, "-C", self.bare, "rev-parse", "--verify", "--quiet",
                               f"refs/heads/{branch}^{{commit}}"], capture_output=True, text=True)
        return done.stdout.strip() if done.returncode == 0 else None

    def guard(self, text: str, cwd: Path) -> subprocess.CompletedProcess:
        """Run the installed settings hook as the engine does, with the Bash payload for `text`."""
        hook = json.loads((self.world.home / ".claude/settings.json").read_text("utf-8"))
        command = hook["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
        return subprocess.run([command], cwd=cwd, env=self.env, capture_output=True, text=True,
                              input=payload(text, str(cwd)).decode("utf-8"), timeout=120)
