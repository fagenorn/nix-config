"""Contract tests for the direct-lane implementer's whole shell: the session runs in its own worktree with
`Bash`, `Edit` and `Write` preapproved, the lifecycle guard hook still judging every command.

The helpers, fixtures and the stand-in launcher are the ones tests/test_engine_session.py defines; the
stubbed delivery is tests/test_engine_stubbed_run.py's.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

from agent_tools.delivery import engine_guard, engine_session
from tests.engine_fixture import AdoptedFixtures
from tests.engine_procedure_copies import PROCEDURES
from tests.engine_step_coverage import StepCoverage
from tests.guard_policy_world import install_platform_manifest_in_environ
from tests.test_engine_deliver import EngineProject
from tests.test_engine_session import (
    GIT_READ_ONLY, GIT_WRITING, NEVER, RESULT_NORMAL, SCHEMA, SESSION, SETTINGS_GUARDED,
    SETTINGS_UNGUARDED, SYSTEM, copy_roles, install_stub, one_step,
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


def _rule_matches(pattern: str, command: str) -> bool:
    if pattern.endswith(":*"):  # the legacy prefix form: the prefix alone or followed by a space and anything
        prefix = pattern[:-2]
        return command == prefix or command.startswith(prefix + " ")
    return re.fullmatch(".*".join(re.escape(part) for part in pattern.split("*")), command) is not None


def client_admits(command: str, allowed: list[str], denied: list[str]) -> bool:
    """Whether the client runs the single `command` under these `--allowedTools`/`--disallowedTools` words.

    Models the wildcard forms of https://code.claude.com/docs/en/permissions (`*` matches any run of
    characters, `:*` is the legacy prefix form, a deny rule is checked before an allow rule); CI runs no client."""
    def bash_rules(rules: list[str]) -> list[str]:
        return [rule[len("Bash("):-1] for rule in rules if rule.startswith("Bash(") and rule.endswith(")")]

    if any(_rule_matches(pattern, command) for pattern in bash_rules(denied)):
        return False
    return "Bash" in allowed or any(_rule_matches(pattern, command) for pattern in bash_rules(allowed))


def words_after(argv: tuple[str, ...] | list[str], flag: str) -> list[str]:
    return argv[argv.index(flag) + 1].split(",")


def whole_shell_argv() -> tuple[engine_session.Role, tuple[str, ...]]:
    role = replace(engine_session.read_role(AGENTS, "implementer"), whole_shell=True)
    return role, engine_session.launch_argv(role, SCHEMA, SESSION, SYSTEM)


WHOLE_SHELL_DENIED = [
    "Bash(git push)", "Bash(git push *)",
    "Bash(git * push)", "Bash(git * push *)",
    "Bash(git stash)", "Bash(git stash *)",
    "Bash(git * stash)", "Bash(git * stash *)",
    "Bash(git reset --hard)", "Bash(git reset --hard *)",
    "Bash(git * reset --hard)", "Bash(git * reset --hard *)",
    "Bash(git clean)", "Bash(git clean *)",
    "Bash(git * clean)", "Bash(git * clean *)",
    "Bash(git checkout --)", "Bash(git checkout -- *)",
    "Bash(git * checkout --)", "Bash(git * checkout -- *)",
    "Bash(git branch -D)", "Bash(git branch -D *)",
    "Bash(git * branch -D)", "Bash(git * branch -D *)",
    "Bash(git branch -d)", "Bash(git branch -d *)",
    "Bash(git * branch -d)", "Bash(git * branch -d *)",
    "Bash(gh pr create)", "Bash(gh pr create *)", "Bash(gh * pr create *)",
    "Bash(gh pr merge)", "Bash(gh pr merge *)", "Bash(gh * pr merge *)",
    "Bash(gh release create)", "Bash(gh release create *)", "Bash(gh * release create *)",
]


class WholeShellArgvTest(unittest.TestCase):
    def test_the_recorded_1639_call_split_one_command_per_call_is_admitted(self):
        role, argv = whole_shell_argv()
        allowed, denied = words_after(argv, "--allowedTools"), words_after(argv, "--disallowedTools")
        w = "/srv/p/.worktrees/worktree-issue-1639"

        commands = [
            f"git -C {w} rev-parse HEAD",
            f"git -C {w} status --short",
            f"git -C {w} log --oneline -3",
            f"sed -n 70,130p {w}/python/agent_tools/console/prompt_card.py",
            f"PYTHONPATH={w}/python python3 -m unittest tests.test_x",
            f"git -C {w} add {w}/python/agent_tools/console/prompt_card.py",
            f"git -C {w} commit -m 'Read the card once'",
        ]

        for command in commands:
            with self.subTest(command):
                self.assertTrue(client_admits(command, allowed, denied))
        self.assertEqual(allowed, ["Bash", "Edit", "Write"])

    def test_the_rule_model_reads_the_documented_wildcard_forms(self):
        cases = [
            ("Bash(npm run build)", "npm run build", True),
            ("Bash(npm run build)", "npm run build --watch", False),
            ("Bash(npm run test *)", "npm run test unit", True),
            ("Bash(git * main)", "git checkout main", True),
            ("Bash(git * main)", "git checkout dev", False),
            ("Bash(* --version)", "node --version", True),
            ("Bash(npm run test:*)", "npm run test unit", True),
            ("Bash(npm run test:*)", "npm run test", True),
            ("Bash(ls *)", "lsof", False),
        ]
        for rule, command, expected in cases:
            with self.subTest(rule=rule, command=command):
                self.assertEqual(client_admits(command, [rule], []), expected)

    def test_the_whole_shell_denies_each_lifecycle_verb_and_destructive_git_command_in_every_option_form(self):
        role, argv = whole_shell_argv()
        allowed, denied = words_after(argv, "--allowedTools"), words_after(argv, "--disallowedTools")
        refused = [
            "git push origin b", "git -C /wt push origin b", "git --no-pager push origin b",
            "git -c core.pager=cat push origin b", "git --git-dir=/wt/.git push", "git stash",
            "git -C /wt stash pop", "git -C /wt reset --hard HEAD", "git --no-pager reset --hard",
            "git clean -fd", "git -C /wt clean -fdx", "git -C /wt checkout -- f.py",
            "git -C /wt branch -D b", "git -C /wt branch -d b",
            "gh pr create --repo a/b --base main --head b --title t --body b",
            "gh pr merge 5 --repo a/b --merge --delete-branch", "gh --repo a/b pr merge 5",
            "gh release create v1",
        ]
        admitted = ["git -C /wt checkout --detach", "git -C /wt branch --show-current",
                    "git -C /wt reset HEAD f.py"]

        for command in refused:
            with self.subTest(refused=command):
                self.assertFalse(client_admits(command, allowed, denied))
        for command in admitted:
            with self.subTest(admitted=command):
                self.assertTrue(client_admits(command, allowed, denied))
        own = len(role.disallowed)
        self.assertEqual(denied[:own], list(role.disallowed))
        self.assertEqual(denied[own:], WHOLE_SHELL_DENIED)
        self.assertEqual(len(WHOLE_SHELL_DENIED), 37)

    def test_a_whole_shell_launch_keeps_the_hooks_and_dont_ask(self):
        _, argv = whole_shell_argv()

        self.assertTrue(NEVER.isdisjoint(argv))
        self.assertEqual(argv[argv.index("--permission-mode") + 1], "dontAsk")
        self.assertNotIn("--tools", argv)
        self.assertEqual(argv[-2], "--append-system-prompt-file")

    def test_the_other_roles_keep_their_narrow_lists(self):
        # Each role's baseline, written out here and not read from its role file: a tool added to a role
        # file changes the launch and fails this table until the table is changed on purpose.
        expected = {
            "planner": ("Read,Glob,Grep,Bash,Write,Edit,Skill,Agent(Explore)",
                        f"Read,Glob,Grep,{GIT_READ_ONLY},Write,Edit,Skill,Agent(Explore)", GIT_WRITING),
            "reviewer": ("Read,Glob,Grep,Bash,Write,Skill",
                         f"Read,Glob,Grep,{GIT_READ_ONLY},Write,Skill", GIT_WRITING),
            "reviewer-lite": ("Read,Glob,Grep,Bash,Write",
                              f"Read,Glob,Grep,{GIT_READ_ONLY},Write", GIT_WRITING),
        }
        for name, (tools, allowed, denied) in expected.items():
            with self.subTest(name):
                role = engine_session.read_role(AGENTS, name)
                argv = engine_session.launch_argv(role, SCHEMA, SESSION, SYSTEM)
                self.assertEqual(argv[argv.index("--tools") + 1], tools)
                self.assertEqual(argv[argv.index("--allowedTools") + 1], allowed)
                self.assertEqual(argv[argv.index("--disallowedTools") + 1], denied)
                with self.assertRaises(engine_session.RoleError):
                    engine_session.launch_argv(replace(role, whole_shell=True), SCHEMA, SESSION, SYSTEM)

    def test_the_implementer_without_a_worktree_keeps_its_launch(self):
        role = engine_session.read_role(AGENTS, "implementer")

        argv = engine_session.launch_argv(role, SCHEMA, SESSION, SYSTEM)

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
        self.assertIn("--allowedTools", implement["argv"])
        self.assertEqual(words_after(implement["argv"], "--allowedTools"), ["Bash", "Edit", "Write"])
        review = self.launch(run, "lite-review")
        self.assertEqual(os.path.realpath(review["cwd"]), os.path.realpath(run.fixture.root))
        self.assertNotIn("Bash,Edit,Write", review["argv"])

    def test_a_whole_shell_step_on_a_host_without_the_guard_starts_no_run(self):
        run = self.stubbed()
        settings = Path(run.world.home) / ".claude" / "settings.json"
        settings.parent.mkdir(parents=True, exist_ok=True)
        settings.write_text(SETTINGS_UNGUARDED.read_text(encoding="utf-8"), encoding="utf-8")

        done = run.deliver()

        self.assertEqual(done.returncode, 2, done.stdout + done.stderr)
        self.assertEqual(run.launches(), [])


if __name__ == "__main__":
    unittest.main()
