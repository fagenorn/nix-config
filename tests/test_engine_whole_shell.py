"""Contract tests for the direct-lane implementer: the session runs in its own worktree, every session
with permissions skipped, the lifecycle guard hook judging every command.

The helpers, fixtures and the stand-in launcher are the ones tests/test_engine_session.py defines; the
stubbed delivery is tests/test_engine_stubbed_run.py's.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent_tools.delivery import engine_guard, engine_session
from tests.engine_fixture import AdoptedFixtures
from tests.engine_guards import real_guard
from tests.engine_procedure_copies import PROCEDURES
from tests.engine_step_coverage import StepCoverage
from tests.guard_policy_world import install_platform_manifest_in_environ
from tests.test_engine_deliver import EngineProject
from tests.test_engine_session import (
    RESULT_NORMAL, SCHEMA, SESSION, SETTINGS_GUARDED, SETTINGS_UNGUARDED, SYSTEM, after, copy_roles,
    install_stub, one_step,
)
from tests.test_engine_stubbed_run import Scenario

TIER = "integration"  # every case runs the engine as a child process on a built project

ROOT = Path(__file__).resolve().parents[1]
AGENTS = ROOT / "home/common/claude-code/agents"
FIXTURES = AdoptedFixtures()
STEPS = StepCoverage(PROCEDURES, ())


def setUpModule() -> None:
    install_platform_manifest_in_environ()
    unittest.addModuleCleanup(FIXTURES.close)


def tearDownModule() -> None:
    STEPS.finish(sys.modules[__name__], Scenario)


class ImplementerLaunchTest(unittest.TestCase):
    def test_the_implementer_without_a_worktree_keeps_its_launch(self):
        role = engine_session.read_role(AGENTS, "implementer")

        argv = engine_session.launch_argv(role, SCHEMA, SESSION, SYSTEM)

        self.assertIn("--dangerously-skip-permissions", argv)
        self.assertNotIn("--tools", argv)
        self.assertNotIn("--allowedTools", argv)
        self.assertEqual(argv[argv.index("--disallowedTools") + 1], (
            "Artifact,ArtifactComments,ArtifactData,Workflow,ScheduleWakeup,AskUserQuestion,SendFeedback,"
            "ReportFindings,CronCreate,CronDelete,CronList,RemoteTrigger,mcp__claude_ai_Claude_Docs"))


def git(*words: str, cwd: Path) -> None:
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    subprocess.run(["git", "-c", "user.name=n", "-c", "user.email=n@example.com",
                    "-c", "commit.gpgsign=false", *words], cwd=cwd, env=env, check=True,
                   capture_output=True, text=True)


def local_env_vars() -> list[str]:
    """The variables git lists as repository-local: the independent source for what a session must not inherit."""
    done = subprocess.run(["git", "rev-parse", "--local-env-vars"], capture_output=True, text=True, check=True)
    return done.stdout.split()


class SessionEnvironmentTest(unittest.TestCase):
    def test_a_session_inherits_no_variable_git_names_as_repository_local(self):
        given = {"HOME": "/h", **dict.fromkeys(local_env_vars(), "x")}

        got = engine_session.session_environment(given)

        self.assertIn("GIT_SHALLOW_FILE", local_env_vars())
        self.assertEqual(sorted(set(local_env_vars()) & set(got)), [])
        self.assertEqual(got["HOME"], "/h")

    def test_a_session_inherits_no_bare_mode_switch(self):
        got = engine_session.session_environment({"CLAUDE_CODE_SIMPLE": "1", "HOME": "/h"})

        self.assertNotIn("CLAUDE_CODE_SIMPLE", got)


class OwnWorktreeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.repo, self.wt, self.sib, self.other = (
            self.tmp / "repo", self.tmp / "wt", self.tmp / "sib", self.tmp / "other")
        self.repo.mkdir()
        git("init", "-b", "main", cwd=self.repo)
        git("commit", "--allow-empty", "-m", "first", cwd=self.repo)
        git("worktree", "add", str(self.wt), "-b", "b", cwd=self.repo)
        git("worktree", "add", str(self.sib), "-b", "s", cwd=self.repo)
        self.other.mkdir()
        git("init", cwd=self.other)
        git("commit", "--allow-empty", "-m", "first", cwd=self.other)
        (self.wt / "sub").mkdir()
        (self.wt / "file.txt").write_text("x", encoding="utf-8")

    def test_the_issue_worktree_on_its_branch_is_its_own(self):
        got = engine_session.own_worktree(str(self.wt), "b", str(self.repo))

        self.assertEqual(got, os.path.realpath(self.wt))

    def test_nothing_else_is_an_own_worktree(self):
        cases = {
            "the project root": (str(self.repo), "main"),
            "a sibling worktree": (str(self.sib), "b"),
            "the wrong branch": (str(self.wt), "s"),
            "a foreign repository": (str(self.other), "master"),
            "a subdirectory": (str(self.wt / "sub"), "b"),
            "a missing path": (str(self.tmp / "missing"), "b"),
            "a relative path": ("wt", "b"),
            "a regular file": (str(self.wt / "file.txt"), "b"),
            "no path": (None, "b"),
            "a number as path": (42, "b"),
            "no branch": (str(self.wt), None),
        }
        for name, (path, branch) in cases.items():
            with self.subTest(name):
                self.assertIsNone(engine_session.own_worktree(path, branch, str(self.repo)))

    def test_inherited_repository_variables_do_not_move_the_listing(self):
        with mock.patch.dict(os.environ, {"GIT_DIR": str(self.other / ".git"),
                                          "GIT_WORK_TREE": str(self.other)}):
            got = engine_session.own_worktree(str(self.wt), "b", str(self.repo))

        self.assertEqual(got, os.path.realpath(self.wt))

    def test_the_listing_runs_without_any_variable_git_names_as_repository_local(self):
        seen = {}
        real = subprocess.run

        def spy(argv, **kwargs):
            seen.update(kwargs["env"])
            return real(argv, **kwargs)

        with mock.patch.dict(os.environ, dict.fromkeys(local_env_vars(), "x")), \
                mock.patch.object(subprocess, "run", spy):
            engine_session.own_worktree(str(self.wt), "b", str(self.repo))

        self.assertTrue(seen)
        self.assertEqual(sorted(set(local_env_vars()) & set(seen)), [])


class GuardSettingsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.user = self.tmp / "settings.json"
        shutil.copy(SETTINGS_GUARDED, self.user)
        self.directory = self.tmp / "session"
        (self.directory / ".claude").mkdir(parents=True)

    def project_file(self, name: str, text: str) -> None:
        (self.directory / ".claude" / name).write_text(text, encoding="utf-8")

    def test_project_settings_that_turn_hooks_off_leave_no_guard(self):
        cases = {
            "settings.local.json": '{"disableAllHooks": true}',
            "settings.json": '{"allowManagedHooksOnly": true}',
        }
        for name, text in cases.items():
            with self.subTest(name):
                self.project_file(name, text)
                got = engine_guard.locate(self.user, str(self.directory))
                self.assertIsInstance(got, engine_guard.Unavailable)
                self.assertIn(name, got.reason)
                (self.directory / ".claude" / name).unlink()

    def test_project_settings_that_leave_hooks_on_keep_the_guard(self):
        self.project_file("settings.json", '{"disableAllHooks": false}')

        got = engine_guard.locate(self.user, str(self.directory))

        self.assertIsInstance(got, engine_guard.Hook)

    def test_unreadable_project_settings_leave_no_guard(self):
        self.project_file("settings.json", "{")

        got = engine_guard.locate(self.user, str(self.directory))

        self.assertIsInstance(got, engine_guard.Unavailable)
        self.assertIn("settings.json", got.reason)

    def test_a_directory_with_no_project_settings_or_none_keeps_the_guard(self):
        shutil.rmtree(self.directory / ".claude")

        self.assertIsInstance(engine_guard.locate(self.user, str(self.directory)), engine_guard.Hook)
        self.assertIsInstance(engine_guard.locate(self.user, None), engine_guard.Hook)
        self.assertIsInstance(engine_guard.locate(self.user), engine_guard.Hook)


class WholeShellDeliverTest(Scenario):
    def test_a_session_directory_whose_project_settings_turn_hooks_off_is_not_launched(self):
        project = EngineProject(self)
        project.env.pop("CLAUDE_ACCOUNT", None)
        copy_roles(project, "implementer")
        log = install_stub(project, RESULT_NORMAL)
        (project.root / ".claude").mkdir(exist_ok=True)
        (project.root / ".claude" / "settings.local.json").write_text(
            '{"disableAllHooks": true}', encoding="utf-8")

        done = project.deliver(one_step(project), issue=1514)

        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertIn("disableAllHooks", done.stderr)
        self.assertFalse(log.exists())

    def test_a_session_inherits_no_repository_variables(self):
        project = EngineProject(self)
        project.env.pop("CLAUDE_ACCOUNT", None)
        project.env.update(GIT_DIR="/nowhere/.git", GIT_WORK_TREE="/nowhere",
                           GIT_INDEX_FILE="/nowhere/index", GIT_SHALLOW_FILE="/nowhere/shallow",
                           GIT_CONFIG_PARAMETERS="'core.worktree=/nowhere'")
        copy_roles(project, "implementer")
        log = install_stub(project, RESULT_NORMAL)

        done = project.deliver(one_step(project), issue=1514)

        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        (launch,) = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
        for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_SHALLOW_FILE",
                     "GIT_CONFIG_PARAMETERS"):
            self.assertNotIn(name, launch["git_env"])

    def test_a_relaunch_after_the_session_moved_its_branch_is_refused_before_it_starts(self):
        run = self.stubbed(replies={"implement": {
            "reply": {}, "switch": {"branch": "wandered"}, "miss": True}})

        done = run.deliver()

        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertIn("implement", done.stderr)
        self.assertIn("not a worktree of the project on that branch", done.stderr)
        self.assertEqual(self.keys(run).count("implement"), 1)
        self.assertEqual(self.branch_here(run, run.worktree_path), "wandered")

    def test_the_direct_implement_session_runs_in_its_worktree(self):
        run = self.stubbed()

        run.deliver()

        implement = self.launch(run, "implement")
        self.assertEqual(os.path.realpath(implement["cwd"]), os.path.realpath(run.worktree_path))
        self.assertIn("--dangerously-skip-permissions", implement["argv"])
        self.assertNotIn("--allowedTools", implement["argv"])
        review = self.launch(run, "lite-review")
        self.assertEqual(os.path.realpath(review["cwd"]), os.path.realpath(run.fixture.root))
        self.assertIn("--dangerously-skip-permissions", review["argv"])
        self.assertNotIn("--allowedTools", review["argv"])

    def test_a_whole_shell_step_on_a_host_without_the_guard_starts_no_run(self):
        run = self.stubbed()
        settings = Path(run.world.home) / ".claude" / "settings.json"
        settings.parent.mkdir(parents=True, exist_ok=True)
        settings.write_text(SETTINGS_UNGUARDED.read_text(encoding="utf-8"), encoding="utf-8")

        done = run.deliver()

        self.assertEqual(done.returncode, 2, done.stdout + done.stderr)
        self.assertEqual(run.launches(), [])


class RealGuardTest(unittest.TestCase):
    READ_TABLE = (
        "git log origin/main --oneline -5 | head -3",
        "git show --stat HEAD | head -20",
        "git ls-tree -r HEAD --name-only | grep -i -E 'engine|guard' | head -30",
        "git diff origin/main...HEAD --stat | tail -5",
        "git log --oneline -3; git status --short",
        "ls docs && cat README.md | wc -l",
        "sed -n '1,40p' README.md",
        "grep -rn 'tool-denied' python | head",
        "tail -n 20 justfile",
    )
    REFUSED_TABLE = (
        "git push origin HEAD",
        "nohup git log",
        "setsid git log",
        "git log & disown",
        "gh pr create --repo example/x --fill",
        "gh pr merge 1 --repo example/x --merge",
        "gh release create v1 --repo example/x",
    )

    def test_the_guard_admits_the_read_table_and_refuses_lifecycle_and_detaching_calls_in_every_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            wrapper = real_guard(Path(tmp) / "guard")
            fixture = ROOT / "tests/fixtures/engine-session/result-denied-1740.json"
            recorded = json.loads(fixture.read_text(encoding="utf-8"))[
                "permission_denials"][0]["tool_input"]["command"]
            absent = {k: v for k, v in os.environ.items() if k != "CLAUDE_READ_ONLY_SHELL"}
            environments = {"absent": absent, "set": {**absent, "CLAUDE_READ_ONLY_SHELL": "1"}}
            commands = (recorded, *self.READ_TABLE, *self.REFUSED_TABLE)
            seen: dict[str, dict[str, tuple[int, str]]] = {}
            for name, env in environments.items():
                for command in commands:
                    with self.subTest(environment=name, command=command):
                        done = subprocess.run(
                            [str(wrapper)],
                            input=json.dumps({"tool_name": "Bash", "tool_input": {"command": command}}),
                            env=env, cwd=tmp, capture_output=True, text=True, timeout=60,
                            check=False)
                        seen.setdefault(name, {})[command] = (done.returncode, done.stderr)
                        if command in self.REFUSED_TABLE:
                            self.assertEqual(done.returncode, 2, done.stderr)
                        else:
                            self.assertEqual(done.returncode, 0, done.stderr)
                        if command == "nohup git log":
                            self.assertIn("detaching command `nohup` refused", done.stderr)
                            self.assertIn("background mode", done.stderr)
            for command in commands:
                with self.subTest(command=command):
                    self.assertEqual(seen["absent"].get(command), seen["set"].get(command))


class ReadOnlyRoleToolsTest(unittest.TestCase):
    def test_every_role_an_engine_procedure_runs_without_mutating_can_call_bash(self):
        roles: set[str] = set()
        for path in sorted((ROOT / "python/agent_tools/delivery/procedures").glob("*.json")):
            for step in json.loads(path.read_text(encoding="utf-8")).get("steps", ()):
                if step.get("kind") == "agent" and step.get("mutates") is not True:
                    roles.add(step["role"])
        self.assertLessEqual({"reviewer-lite", "reviewer"}, roles)
        for name in sorted(roles):
            with self.subTest(role=name):
                argv = list(engine_session.launch_argv(
                    engine_session.read_role(AGENTS, name), SCHEMA, SESSION, SYSTEM))
                if "--tools" in argv:
                    self.assertIn("Bash", after(argv, "--tools").split(","))
                if "--disallowedTools" in argv:
                    self.assertNotIn("Bash", after(argv, "--disallowedTools").split(","))


if __name__ == "__main__":
    unittest.main()
