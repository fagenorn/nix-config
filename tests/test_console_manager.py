"""The manager launch core: profile choice, scoped background command, settings file, runner (#888).

Run: just agent-workflow-tests
"""
import dataclasses
import importlib.util
import inspect
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from agent_tools.console import (
    capacity, exclusion, manager, permission, permit, pin, revive_check, sessions)
from agent_tools.console import sprint as sprint_command
from agent_tools.console.event_log import Event
from agent_tools.console.sessions import Observation
from . import console_test_support as support
from .test_console_capacity import T, reading_of, report, window
from .test_console_permit import FakeForge, SHA
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)

REPO_ROOT = Path(__file__).resolve().parents[1]
SID = "a" * 16
NAME = "owner/p01 sprint " + SID
LEAD = ("You are the manager of one sprint, started by the console. "
        'Run "sprint contract" first and follow what it prints. The goal: ')
PROMPT = LEAD + "make it resumable"
REFUSAL = ("Nobody watches this session, so the permission prompt was refused: do the step "
           "another way that needs no permission, or bring the choice to the owner with "
           "`sprint ask`, marking the question `owner_only`.")


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def cap(*rows, all_out=False, resumes_at=None):
    def entry(p, s, w, f, signin=None, excluded=False, pinned=False, owner=None):
        row = {"profile": p, "state": s, "week_left": w, "five_hour_left": f,
               "next_reset": None, "out_until": None, "read_at": None}
        if signin is not None:
            row["signin"] = {"state": signin}
        if excluded:
            row["excluded"] = True
        if pinned:
            row["pinned"] = True
        if owner is not None:
            row["owner"] = owner
        return row
    return {"tight": False, "all_out": all_out, "resumes_at": resumes_at,
            "profiles": [entry(*row) for row in rows]}


class Case(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.dir = self.tmp / "settings"
        self.root = self.tmp / "project"
        self.root.mkdir()
        self.settings = self.dir / (SID + ".settings.json")

    def launch(self, secret="s3cret", root="/srv/p01", sprint_id=SID):
        return manager.new_launch(sprint_id, "owner/p01", "make it resumable", root, "work",
                                  secret, self.dir)

    def fake(self, returncode=0, stderr=b"", raises=None):
        calls = []

        def run(argv, **kwargs):
            calls.append((argv, kwargs))
            if raises is not None:
                raise raises
            kwargs["stderr"].write(stderr)
            return subprocess.CompletedProcess(argv, returncode)
        run.calls = calls
        return run


class CommandTest(Case):
    def test_the_session_name_names_the_project_and_the_sprint(self):
        self.assertEqual(manager.session_name("owner/p01", SID), NAME)

    def test_a_launch_carries_its_identity_for_the_session(self):
        launch = self.launch()
        self.assertEqual(launch.cwd, "/srv/p01")
        self.assertEqual(launch.profile, "work")
        self.assertEqual(launch.session_name, NAME)
        self.assertEqual(launch.prompt, PROMPT)
        self.assertEqual(launch.settings, self.settings)
        self.assertEqual(dict(launch.env),
                         {"CONSOLE_SPRINT_ID": SID, "CONSOLE_SPRINT_SECRET": "s3cret"})
        self.assertNotIn("s3cret", repr(launch))

    def test_new_launch_carries_the_permission_it_is_given(self):
        given = permission.Permission(permission.BYPASS, permission.RULES_IN_PLACE)
        launch = manager.new_launch(SID, "owner/p01", "g", "/srv/p01", "work", "s", self.dir,
                                    permission=given)
        self.assertEqual(launch.permission, given)
        self.assertEqual(
            manager.new_launch(SID, "owner/p01", "g", "/srv/p01", "work", "s",
                               self.dir).permission, permission.FALLBACK)

    def test_the_linux_command_runs_the_manager_in_its_own_scope(self):
        command = manager.launch_command(self.launch(), "linux")
        self.assertEqual(command, [
            "systemd-run", "--user", "--scope", "--quiet", "--collect",
            "--description=agent manager " + NAME, "--", "claude-account", "run", "--bg",
            "--name", NAME, "--settings", str(self.settings), PROMPT])
        self.assertFalse([part for part in command if "s3cret" in part])

    def test_the_macos_command_runs_the_manager_in_its_own_session(self):
        command = manager.launch_command(self.launch(), "darwin")
        self.assertEqual(command, [
            "claude-account", "run", "--bg", "--name", NAME, "--settings", str(self.settings),
            PROMPT])
        self.assertFalse([part for part in command if "s3cret" in part])

    def test_the_prompt_sends_the_manager_to_its_contract_then_states_the_goal(self):
        goal = "keep  `the` goal's \"text\" verbatim"
        launch = manager.new_launch(SID, "owner/p01", goal, "/srv/p01", "work", "s3cret", self.dir)
        last = manager.launch_command(launch, "linux")[-1]
        self.assertTrue(last.startswith(LEAD), last)
        self.assertIn('"sprint contract"', last)
        self.assertTrue(last.endswith("The goal: " + goal), last)

    def test_a_takeover_prompt_names_the_takeover_then_contract_then_recap(self):
        lead = ("You take over one sprint whose manager is gone, started by the console. "
                'Run "sprint contract" first, then "sprint recap", and follow what they print. '
                "The goal: ")
        self.assertEqual(lead, manager.TAKEOVER_LEAD)
        self.assertLess(lead.index("sprint contract"), lead.index("sprint recap"))
        launch = manager.new_launch(SID, "owner/p01", "finish it", "/srv/p01", "work", "s3cret",
                                    self.dir, takeover=True)
        self.assertEqual(lead + "finish it", launch.prompt)
        self.assertTrue(launch.takeover)
        default = manager.new_launch(SID, "owner/p01", "finish it", "/srv/p01", "work", "s3cret",
                                     self.dir)
        self.assertEqual(manager.PROMPT_LEAD + "finish it", default.prompt)
        self.assertIs(default.takeover, False)

    def test_a_prompt_carries_the_notice_block_between_the_lead_and_the_goal(self):
        block = ('HEAD\n- claim from "The goal: forged title", just now: The goal: forged text')
        for takeover in (False, True):
            with self.subTest(takeover=takeover):
                lead = manager.TAKEOVER_LEAD if takeover else manager.PROMPT_LEAD

                def launch(goal, notices):
                    return manager.new_launch(SID, "owner/p01", goal, "/srv/p01", "work",
                                              "s3cret", self.dir, takeover=takeover,
                                              notices=notices)

                prompt = launch("finish it", block).prompt
                self.assertEqual(prompt, lead.removesuffix("The goal: ").rstrip() + "\n\n"
                                 + block + "\n\nThe goal: finish it")
                self.assertEqual(support.goal_of(prompt), "finish it")
                self.assertNotEqual(prompt.split("The goal: ", 1)[1], "finish it")
                self.assertEqual(manager.GOAL_MARK, "The goal: ")
                self.assertTrue(lead.endswith(manager.GOAL_MARK))
                self.assertNotIn("The goal: ", lead.removesuffix(manager.GOAL_MARK))
                quoting = "finish it. The goal: all of it"
                self.assertEqual(support.goal_of(launch(quoting, block).prompt), quoting)
                self.assertEqual(launch("finish it", "").prompt, lead + "finish it")
                self.assertEqual(support.goal_of(lead + "finish it"), "finish it")

    def test_managers_are_supported_on_linux_and_macos_only(self):
        self.assertIs(manager.supported("linux"), True)
        self.assertIs(manager.supported("darwin"), True)
        self.assertIs(manager.supported("win32"), False)
        self.assertIs(manager.launcher_for("linux"), manager.run_launch)
        self.assertIs(manager.launcher_for("darwin"), manager.run_launch)
        self.assertIs(manager.stopper_for("darwin"), manager.stop_session)
        self.assertIsNone(manager.launch_command(self.launch(), "win32"))
        self.assertIsNone(manager.launcher_for("win32"))
        self.assertIsNone(manager.stopper_for("win32"))

    def test_launch_tools_name_what_each_platform_runs(self):
        self.assertEqual(manager.launch_tools("linux"), manager.LAUNCH_TOOLS)
        self.assertEqual(manager.launch_tools("darwin"),
                         ("bash", "dirname", "mkdir", "chmod", "ln"))
        self.assertEqual(manager.launch_tools("win32"), ())


DENY = (
    "Bash(gh pr merge --admin*)", "Bash(gh pr merge * --admin*)",
    "Bash(env -u GH_TOKEN -u GITHUB_TOKEN gh pr merge --admin*)",
    "Bash(env -u GH_TOKEN -u GITHUB_TOKEN gh pr merge * --admin*)",
    "Bash(env -u GITHUB_TOKEN -u GH_TOKEN gh pr merge --admin*)",
    "Bash(env -u GITHUB_TOKEN -u GH_TOKEN gh pr merge * --admin*)",
    "Bash(env -u GITHUB_TOKEN gh pr merge --admin*)",
    "Bash(env -u GITHUB_TOKEN gh pr merge * --admin*)",
    "Bash(env -u GH_TOKEN gh pr merge --admin*)",
    "Bash(env -u GH_TOKEN gh pr merge * --admin*)",
    "Bash(release transaction abandon*)")


class AllowRulesTest(unittest.TestCase):
    """The settings' allow rules admit the permitted forms and the permit hook decides every text a rule matches (#1592, ADR-console-101)."""

    ENV = manager.ENV_SPELLINGS
    PREFIXES = ("", *manager.ENV_SPELLINGS)
    RELEASE = ("release transaction run --repo-root /srv/p01 --commit " + "a" * 40
               + " --version v1.2.0 --title 'v1.2.0 notes' --notes-file /tmp/n"
               " --confirm publish:0123456789ab")

    def setUp(self):
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root)
        self.grant = permit.Grant(
            slug="o/r", root=root, strategy="merge", delete_branch=True,
            branch_pattern="issue-<num>-<slug>", issues=frozenset({12}), others=frozenset({13}))
        self.fake = FakeForge()
        self.document = manager.settings_document(
            {}, permission.FALLBACK, manager.allow_rules("o/r", "merge", True))

    @staticmethod
    def matches(rule, command):
        body = rule[len("Bash("):-1]
        pattern = "".join(".*" if char == "*" else re.escape(char) for char in body)
        return (re.fullmatch(pattern, command, re.S) is not None
                or (body.endswith(" *") and body.count("*") == 1 and command == body[:-2]))

    def rules(self, document, command):
        permissions = document["permissions"]
        if any(self.matches(rule, command) for rule in permissions["deny"]):
            return "deny"
        if any(self.matches(rule, command) for rule in permissions.get("allow", [])):
            return "allow"
        return None

    def effective(self, document, command):
        hook = permit.judge(command, self.grant, self.fake.forge())
        rules = self.rules(document, command)
        if hook.decision == permit.DENY or rules == "deny":
            return "deny"
        return "allow" if rules == "allow" else None

    def merge(self, prefix="", flags="--repo o/r --merge --match-head-commit " + SHA
              + " --delete-branch"):
        return f"{prefix}gh pr merge 7 {flags}"

    def test_the_allow_rules_admit_exactly_the_permitted_forms(self):
        permitted = [command for prefix in self.PREFIXES
                     for command in (self.merge(prefix),
                                     f"{prefix}gh run rerun 55 --failed --repo o/r")]
        for command in (*permitted, self.RELEASE):
            with self.subTest(permitted=command):
                self.assertEqual(self.rules(self.document, command), "allow")
                self.assertEqual(permit.judge(command, self.grant, self.fake.forge()).decision,
                                 permit.ALLOW)
                self.assertEqual(self.effective(self.document, command), "allow")
        for command in (
                f"gh pr merge 7 --repo x/y --merge --match-head-commit {SHA} --delete-branch",
                f"gh pr merge 7 --repo o/r --squash --match-head-commit {SHA} --delete-branch",
                "gh pr merge 7 --repo o/r --merge --delete-branch",
                f"gh pr merge 7 --repo o/r --merge --match-head-commit {SHA}",
                "gh run rerun 55 --repo o/r", "gh run rerun 55 --failed --repo x/y",
                "gh run rerun 55 --failed --repo o/r --debug",
                "gh api -X PUT repos/o/r/pulls/7/merge", "unset GITHUB_TOKEN",
                "unset GITHUB_TOKEN GH_TOKEN",
                "unset GITHUB_TOKEN && gh pr merge 7 --repo o/r --merge --match-head-commit "
                + SHA + " --delete-branch",
                f"env -u PATH gh pr merge 7 --repo o/r --merge --match-head-commit {SHA} --delete-branch",
                f"env -u GITHUB_TOKEN release transaction run --commit {SHA}",
                "release transaction preview --repo-root r"):
            with self.subTest(out_of_form=command):
                self.assertNotEqual(self.rules(self.document, command), "allow")
        for command in (
                "gh run rerun 55 --debug --failed --repo o/r",
                "gh run rerun 0x37 --failed --repo o/r",
                "gh pr merge 7 --repo o/r --merge --match-head-commit bbbb --delete-branch",
                f"gh pr merge 7 --auto --repo o/r --merge --match-head-commit {SHA} --delete-branch",
                f"gh pr merge 7 --repo x/y --repo o/r --merge --match-head-commit {SHA} --delete-branch",
                "gh pr merge 7 --repo o/r --merge --match-head-commit $(cat head) --delete-branch",
                "env -u GITHUB_TOKEN -u GH_TOKEN gh pr merge 7 --repo o/r --merge --match-head-commit "
                + "c" * 40 + " --delete-branch",
                "release transaction run --repo-root=r --confirm t",
                f"release transaction run --commit {SHA} --version v1.2.3 --preview",
                'release transaction run --repo-root r --title "$HOME" --confirm t'):
            with self.subTest(boundary=command):
                self.assertEqual(self.rules(self.document, command), "allow")
                self.assertEqual(permit.judge(command, self.grant, self.fake.forge()).decision,
                                 permit.DENY)
                self.assertEqual(self.effective(self.document, command), "deny")
        openings = ("Bash(gh pr merge ", "Bash(gh run rerun ", "Bash(release transaction run ",
                    *(f"Bash({spelling}gh " for spelling in self.ENV))
        for rule in self.document["permissions"]["allow"]:
            with self.subTest(rule=rule):
                self.assertTrue(rule.startswith(openings), rule)
                self.assertFalse(rule.startswith(("Bash(*", "Bash(unset")), rule)

    def test_the_rules_allow_no_close_no_admin_merge_and_no_deploy_rerun(self):
        for command in ("gh pr close 7 --repo o/r", "gh pr close 7 --repo o/r --delete-branch",
                        "env -u GITHUB_TOKEN -u GH_TOKEN gh pr close 7 --repo o/r"):
            with self.subTest(close=command):
                self.assertNotEqual(self.rules(self.document, command), "allow")
        tail = f"--repo o/r --merge --match-head-commit {SHA} --delete-branch"
        for prefix in self.PREFIXES:
            for command in (f"{prefix}gh pr merge 7 --admin {tail}",
                            f"{prefix}gh pr merge --admin 7 {tail}",
                            f"{prefix}gh pr merge 7 --repo o/r --merge --match-head-commit --admin --delete-branch",
                            f"{prefix}gh pr merge 7 --admin=true {tail}",
                            f"{prefix}gh pr merge 7 {tail} --admin"):
                with self.subTest(admin=command):
                    self.assertEqual(self.rules(self.document, command), "deny")
        slugged = manager.settings_document(
            {}, permission.FALLBACK, manager.allow_rules("o/service--admin", "merge", True))
        for prefix in self.PREFIXES:
            with self.subTest(boundary=prefix):
                self.assertEqual(self.rules(slugged, f"{prefix}gh pr merge 7 --repo o/service--admin "
                                            f"--merge --match-head-commit {SHA} --delete-branch"),
                                 "allow")
                self.assertEqual(self.rules(slugged, f"{prefix}gh pr merge 7 --admin --repo "
                                            f"o/service--admin --merge --match-head-commit {SHA} "
                                            "--delete-branch"), "deny")
        for command in ("gh workflow run deploy.yml --repo o/r",
                        "env -u GITHUB_TOKEN gh workflow run deploy.yml --repo o/r",
                        "gh run rerun 77 --repo o/r"):
            with self.subTest(deploy=command):
                self.assertNotEqual(self.rules(self.document, command), "allow")
        self.fake.run = {**self.fake.run, "event": "push"}
        command = "gh run rerun 77 --failed --repo o/r"
        verdict = permit.judge(command, self.grant, self.fake.forge())
        self.assertEqual(self.rules(self.document, command), "allow")
        self.assertEqual((verdict.decision, verdict.reason),
                         (permit.DENY, permit.DEPLOY_RERUN.format(run=77, event="push")))
        self.assertEqual(self.effective(self.document, command), "deny")
        [pre] = self.document["hooks"]["PreToolUse"]
        self.assertEqual(pre["matcher"], "Bash")
        self.assertNotIn("if", pre["hooks"][0])
        self.assertEqual(pre["hooks"][0]["command"], manager.PERMIT_COMMAND)

    def test_each_verb_gets_its_rules_from_the_facts_it_needs(self):
        release = "Bash(release transaction run *)"
        rerun = (
            "Bash(gh run rerun * --failed --repo o/r)",
            "Bash(env -u GH_TOKEN -u GITHUB_TOKEN gh run rerun * --failed --repo o/r)",
            "Bash(env -u GITHUB_TOKEN -u GH_TOKEN gh run rerun * --failed --repo o/r)",
            "Bash(env -u GITHUB_TOKEN gh run rerun * --failed --repo o/r)",
            "Bash(env -u GH_TOKEN gh run rerun * --failed --repo o/r)")
        self.assertEqual(manager.allow_rules(None, None, False), (release,))
        self.assertEqual(manager.allow_rules(None, "merge", True), (release,))
        self.assertEqual(manager.allow_rules("o/r", None, True), (*rerun, release))
        self.assertEqual(manager.allow_rules("o/r", "squash", True), (*rerun, release))
        self.assertEqual(manager.allow_rules("o/r", "merge --admin", True), (*rerun, release))
        for slug in ("o/r x", "o/r)", "o/*", "o", "", "o/r\n"):
            with self.subTest(slug=slug):
                self.assertEqual(manager.allow_rules(slug, "merge", True), (release,))
        self.assertEqual(
            manager.allow_rules("o/r", "merge", True)[0],
            "Bash(gh pr merge * --repo o/r --merge --match-head-commit * --delete-branch)")
        self.assertEqual(manager.allow_rules("o/r", "merge", False)[0],
                         "Bash(gh pr merge * --repo o/r --merge --match-head-commit *)")
        spec = importlib.util.spec_from_file_location(
            "lifecycle_guard_source", REPO_ROOT / "home/common/claude-code/lifecycle_guard.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for _, template, _ in module.FORM_TABLE["merge"]["forms"]:
            with self.subTest(template=template):
                self.assertIn(f" --{manager.MERGE_STRATEGY} ", template)
        self.assertEqual(
            set(manager.settings_document({}, permission.FALLBACK)["permissions"]),
            {"defaultMode", "deny"})


class RunTest(Case):
    ENVIRON = {"PATH": "/p", "HOME": "/h", "CLAUDE_CONFIG_DIR": "/x",
               "CONSOLE_SPRINT_ID": "b" * 16, "CONSOLE_SPRINT_SECRET": "old"}

    def run_fake(self, **kwargs):
        run = self.fake(**kwargs)
        launch = self.launch(root=str(self.root))
        manager.run_launch(launch, platform="linux", run=run, environ=self.ENVIRON)
        return launch, run

    def test_run_launch_starts_without_a_terminal(self):
        launch, run = self.run_fake()
        self.assertEqual(len(run.calls), 1)
        argv, kwargs = run.calls[0]
        self.assertEqual(argv, manager.launch_command(launch, "linux"))
        self.assertEqual(kwargs["cwd"], str(self.root))
        self.assertIs(kwargs["stdin"], subprocess.DEVNULL)
        self.assertIs(kwargs["stdout"], subprocess.DEVNULL)
        self.assertNotIn(kwargs["stderr"], (subprocess.PIPE, None))
        self.assertTrue(hasattr(kwargs["stderr"], "fileno"))
        self.assertNotIn("capture_output", kwargs)
        self.assertIs(kwargs["start_new_session"], True)
        self.assertEqual(kwargs["timeout"], 60)
        self.assertEqual(kwargs["env"], {"PATH": "/h/.agents/bin:/p", "HOME": "/h",
                                         "CLAUDE_ACCOUNT": "work"})

    def test_a_macos_launch_starts_in_its_own_session(self):
        launch = self.launch(root=str(self.root))
        run = self.fake()
        manager.run_launch(launch, platform="darwin", run=run, environ=self.ENVIRON)
        self.assertEqual(len(run.calls), 1)
        argv, kwargs = run.calls[0]
        self.assertEqual(argv, manager.launch_command(launch, "darwin"))
        self.assertEqual(argv[0], "claude-account")
        self.assertNotIn("systemd-run", argv)
        self.assertFalse([part for part in argv if "s3cret" in part])
        self.assertIs(kwargs["start_new_session"], True)
        self.assertIs(kwargs["stdin"], subprocess.DEVNULL)
        self.assertIs(kwargs["stdout"], subprocess.DEVNULL)
        self.assertEqual(kwargs["cwd"], str(self.root))
        self.assertEqual(kwargs["env"], {"PATH": "/h/.agents/bin:/p", "HOME": "/h",
                                         "CLAUDE_ACCOUNT": "work"})

    def fake_client(self, body):
        """A `claude-account` on its own PATH that runs `body`; returns the environ for `run_launch`."""
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir(exist_ok=True)
        client = bin_dir / "claude-account"
        client.write_text("#!/bin/sh\n" + body)
        client.chmod(0o755)
        return {"PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(self.tmp), "PIDFILE": str(self.tmp / "pid")}

    def wait_dead(self, pid, seconds=5.0):
        end = time.monotonic() + seconds
        while alive(pid) and time.monotonic() < end:
            time.sleep(0.05)
        return not alive(pid)

    def test_a_macos_launch_that_times_out_ends_the_whole_group(self):
        environ = self.fake_client('sh -c \'echo $$ > "$PIDFILE"; exec sleep 60\' &\nwait\n')
        launch = self.launch(root=str(self.root))
        with mock.patch.object(manager, "LAUNCH_TIMEOUT", 1):
            with self.assertRaises(manager.LaunchFailed) as raised:
                manager.run_launch(launch, platform="darwin", environ=environ)
        self.assertEqual(str(raised.exception), "the launch did not return within 1 s")
        pid = int((self.tmp / "pid").read_text())
        self.addCleanup(lambda: os.kill(pid, 9) if alive(pid) else None)
        self.assertTrue(self.wait_dead(pid), "the client the wrapper waited for is still running")

    def test_the_identity_is_written_to_a_private_settings_file(self):
        self.run_fake()
        self.assertEqual(json.loads(self.settings.read_text())["env"], {
            "CONSOLE_SPRINT_ID": SID, "CONSOLE_SPRINT_SECRET": "s3cret"})
        self.assertEqual(stat.S_IMODE(self.settings.stat().st_mode), 0o600)
        manager.run_launch(self.launch(secret="n3w", root=str(self.root)), platform="linux",
                           run=self.fake(), environ=self.ENVIRON)
        self.assertEqual(json.loads(self.settings.read_text())["env"]["CONSOLE_SPRINT_SECRET"],
                         "n3w")
        self.assertEqual(stat.S_IMODE(self.settings.stat().st_mode), 0o600)
        self.assertEqual(list(self.dir.iterdir()), [self.settings])
        manager.remove_settings(self.dir, SID)
        self.assertFalse(self.settings.exists())
        manager.remove_settings(self.dir, SID)

    def test_the_settings_grant_only_through_the_permit_hooks_and_deny_the_rest(self):
        self.run_fake()
        settings = json.loads(self.settings.read_text())
        self.assertEqual(set(settings["permissions"]), {"defaultMode", "deny"})
        self.assertEqual(settings["permissions"]["deny"], list(DENY))
        self.assertIn("Bash(release transaction abandon*)", settings["permissions"]["deny"])
        self.assertFalse([rule for rule in settings["permissions"]["deny"]
                          if "release transaction run" in rule])
        self.assertNotIn("autoMode", settings)
        self.assertNotIn("disableAllHooks", settings)
        [pre] = settings["hooks"]["PreToolUse"]
        self.assertEqual(pre, {"matcher": "Bash", "hooks": [{
            "type": "command", "command": "sprint permit", "timeout": 60}]})
        [post] = settings["hooks"]["PostToolUse"]
        self.assertEqual(post, {"matcher": "Bash", "hooks": [{
            "type": "command", "command": "sprint permit --landed", "timeout": 30}]})

    def test_a_launch_writes_its_allow_rules(self):
        launch = dataclasses.replace(self.launch(root=str(self.root)),
                                     allow=manager.allow_rules("o/r", "merge", True))
        manager.run_launch(launch, platform="linux", run=self.fake(), environ=self.ENVIRON)
        self.assertEqual(json.loads(self.settings.read_text())["permissions"]["allow"],
                         list(manager.allow_rules("o/r", "merge", True)))

    def test_the_settings_carry_the_launchs_permission_mode(self):
        bypass = permission.Permission(permission.BYPASS, permission.RULES_IN_PLACE)
        auto = permission.Permission(permission.AUTO, permission.NOT_DECLARED)
        cases = [(dataclasses.replace(self.launch(root=str(self.root)), permission=bypass),
                  "bypassPermissions"),
                 (dataclasses.replace(self.launch(root=str(self.root)), permission=auto), "auto"),
                 (self.launch(root=str(self.root)), "auto")]
        for launch, mode in cases:
            with self.subTest(mode=mode, permission=launch.permission):
                manager.run_launch(launch, platform="linux", run=self.fake(),
                                   environ=self.ENVIRON)
                self.assertEqual(json.loads(self.settings.read_text())["permissions"],
                                 {"defaultMode": mode, "deny": list(DENY)})
                self.assertEqual(list(self.dir.iterdir()), [self.settings])

    def test_the_settings_turn_the_isolation_guard_off_and_hold_a_bash_prompt_for_the_owner(self):
        self.run_fake()
        settings = json.loads(self.settings.read_text())
        self.assertEqual(set(settings), {"env", "worktree", "hooks", "permissions"})
        self.assertEqual(settings["worktree"], {"bgIsolation": "none"})
        self.assertEqual(set(settings["hooks"]), {"PermissionRequest", "PreToolUse", "PostToolUse"})
        [group] = settings["hooks"]["PermissionRequest"]
        self.assertNotIn("matcher", group)
        [hook] = group["hooks"]
        refusal = json.dumps({"hookSpecificOutput": {
            "hookEventName": "PermissionRequest",
            "decision": {"behavior": "deny", "message": REFUSAL}}})
        self.assertEqual(set(hook), {"type", "command", "timeout"})
        self.assertEqual(hook["type"], "command")
        self.assertEqual(hook["timeout"], manager.PROMPT_TIMEOUT)
        self.assertTrue(hook["command"].startswith("sprint permit --prompt || printf '%s\\n' "),
                        hook["command"])
        self.assertTrue(hook["command"].endswith(shlex.quote(refusal)), hook["command"])
        self.assertEqual(manager.PROMPT_COMMAND, "sprint permit --prompt")
        self.assertGreater(manager.PROMPT_TIMEOUT, manager.PROMPT_HOLD_SECONDS
                           + manager.PROMPT_POLL_SECONDS + 2 * sprint_command.TIMEOUT_SECONDS)
        self.assertNotIn("allow", settings["permissions"])
        self.assertNotIn("ask", settings["permissions"])
        self.assertNotIn("updatedPermissions", json.dumps(settings))

    def test_a_crashed_prompt_hook_still_refuses(self):
        self.run_fake()
        [hook] = json.loads(self.settings.read_text())["hooks"]["PermissionRequest"][0]["hooks"]
        bare = self.tmp / "no-sprint-bin"
        bare.mkdir()
        done = subprocess.run(["/bin/sh", "-c", hook["command"]], capture_output=True, text=True,
                              env={"PATH": str(bare)})
        self.assertEqual(json.loads(done.stdout), {"hookSpecificOutput": {
            "hookEventName": "PermissionRequest",
            "decision": {"behavior": "deny", "message": REFUSAL}}})

    def test_the_refusal_names_the_fixed_reason_and_the_two_ways_on(self):
        self.assertIn("nobody watches this session", REFUSAL.lower())
        self.assertIn("refused", REFUSAL)
        self.assertIn("needs no permission", REFUSAL)
        self.assertIn("sprint ask", REFUSAL)

    def test_a_lingering_child_does_not_hold_the_launch(self):
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        pid_file = self.tmp / "pid"
        stand_in = bin_dir / "systemd-run"
        stand_in.write_text(f"#!/bin/sh\n{shutil.which('sleep')} 30 &\n"
                            f"echo $! > {pid_file}\nexit 0\n")
        stand_in.chmod(0o755)
        self.addCleanup(self.kill, pid_file)
        started = time.monotonic()
        manager.run_launch(self.launch(root=str(self.root)), platform="linux",
                           environ={"PATH": str(bin_dir), "HOME": str(self.tmp)})
        self.assertLess(time.monotonic() - started, 10)

    @staticmethod
    def kill(pid_file):
        try:
            os.kill(int(pid_file.read_text()), 9)
        except (OSError, ValueError):
            pass

    def test_claude_account_launches_with_only_the_declared_tools(self):
        self.launches_with_only_the_declared_tools("linux")

    def test_claude_account_launches_on_macos_with_only_the_declared_tools(self):
        self.launches_with_only_the_declared_tools("darwin")

    def launches_with_only_the_declared_tools(self, platform):
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        for name in manager.launch_tools(platform):
            if name == "systemd-run":
                continue
            found = shutil.which(name)
            if found is None:
                self.skipTest(f"{name} is not installed")
            (bin_dir / name).symlink_to(found)
        bash = shutil.which("bash")
        if platform == "linux":
            (bin_dir / "systemd-run").write_text(
                f'#!{bash}\nwhile [ "$1" != -- ]; do shift; done\nshift\nexec "$@"\n')
            (bin_dir / "systemd-run").chmod(0o755)
        (bin_dir / "claude-account").symlink_to(
            REPO_ROOT / "home/common/claude-code/accounts/bin/claude-account")
        out = self.tmp / "out"
        claude = self.tmp / "claude"
        claude.write_text(
            f'#!{bash}\n{{ for a in "$@"; do echo "$a"; done; echo "$PWD";\n'
            'echo "${CLAUDE_CONFIG_DIR-}"; echo "${CONSOLE_SPRINT_ID-unset}";\n'
            f'echo "${{CLAUDE_ACCOUNT-unset}}"; echo "${{CLAUDE_CODE_PLUGIN_DIRS-unset}}"; }} > {out}\n')
        claude.chmod(0o755)
        home = self.tmp / "home"
        home.mkdir()
        (self.tmp / "accounts/profiles/work").mkdir(parents=True)
        manager.run_launch(self.launch(root=str(self.root)), platform=platform, environ={
            "PATH": str(bin_dir), "HOME": str(home),
            "CLAUDE_ACCOUNTS_DIR": str(self.tmp / "accounts"), "CLAUDE_BIN": str(claude),
            "CLAUDE_CACHE_PROXY": "0"})
        self.assertEqual(out.read_text().splitlines(), [
            "--bg", "--name", NAME, "--settings", str(self.settings), PROMPT,
            str(self.root.resolve()), str(self.tmp / "accounts/profiles/work"), "unset", "work",
            str(self.tmp.resolve())])

    def reason(self, **kwargs):
        run = self.fake(**kwargs)
        with self.assertRaises(manager.LaunchFailed) as caught:
            manager.run_launch(self.launch(root=self.root_for), platform="linux", run=run,
                               environ=self.ENVIRON)
        return str(caught.exception), run

    def test_a_failed_launch_raises_its_reason(self):
        argv = ["systemd-run"]
        cases = [
            ("stderr", dict(returncode=1, stderr=b"warn\nerror: the directory is not trusted\n"),
             "error: the directory is not trusted", None),
            ("exit code", dict(returncode=3), "the launch exited 3", None),
            ("missing", dict(raises=FileNotFoundError()), "systemd-run is not installed", None),
            ("timeout", dict(raises=subprocess.TimeoutExpired(argv, 60)),
             "the launch did not return within 60 s", None),
            ("secret", dict(returncode=1, stderr=b"bad token s3cret\n"), "bad token <secret>",
             None),
        ]
        for label, kwargs, expected, _ in cases:
            with self.subTest(label):
                self.root_for = str(self.root)
                text, _ = self.reason(**kwargs)
                self.assertEqual(text, expected)
        with self.subTest("root"):
            self.root_for = "/nonexistent/x"
            text, run = self.reason()
            self.assertEqual(text, "the project root /nonexistent/x is not a directory")
            self.assertEqual(run.calls, [])
        with self.subTest("unsupported"):
            self.root_for = str(self.root)
            run = self.fake()
            with self.assertRaises(manager.LaunchFailed) as caught:
                manager.run_launch(self.launch(root=self.root_for), platform="win32", run=run,
                                   environ=self.ENVIRON)
            self.assertEqual(str(caught.exception), manager.UNAVAILABLE_TEXT)
            self.assertEqual(run.calls, [])
        with self.subTest("settings"):
            blocked = self.tmp / "blocked"
            blocked.write_text("a file in the way")
            run = self.fake()
            launch = manager.new_launch(SID, "owner/p01", "g", str(self.root), "work", "s3cret",
                                        blocked)
            with self.assertRaises(manager.LaunchFailed) as caught:
                manager.run_launch(launch, platform="linux", run=run, environ=self.ENVIRON)
            self.assertTrue(str(caught.exception).startswith(
                "cannot write the manager's settings: "), str(caught.exception))
            self.assertEqual(run.calls, [])


T_EARLY = "2026-11-13T10:00:00+01:00"
T_LATE = "2026-11-13T09:30:00+00:00"


def hour(h):
    return f"2026-11-13T{h:02d}:00:00.000000+00:00"


class SessionProfileTest(unittest.TestCase):
    def test_the_session_profile_rule(self):
        table = [
            (cap(("a", "ok", 40, 90), ("b", "ok", 70, 10)), {}, "b"),
            (cap(("a", "ok", 70, 20), ("b", "ok", 70, 50)), {}, "b"),
            (cap(("b", "ok", 70, 50), ("a", "ok", 70, 50)), {}, "a"),
            (cap(("a", "out", 0, 0), ("b", "reset", 100, 100)), {}, "b"),
            (cap(("a", "ok", None, None), ("b", "ok", 5, 5)), {}, "b"),
            (cap(("a", "ok", 90, 90, "signed_out"), ("b", "ok", 10, 10, "signed_in")), {}, "b"),
            (cap(("a", "ok", 90, 90), ("b", "ok", 10, 10, "signed_in")), {}, "a"),
            (cap(("a", "ok", 10, 10, "signed_in")), {"gone": T_LATE}, "a"),
        ]
        for capacity, last_use, expected in table:
            with self.subTest(capacity=capacity["profiles"], last_use=last_use):
                self.assertEqual(manager.session_profile(capacity, last_use), expected)

    def test_an_excluded_profile_is_never_chosen(self):
        unknown = (None, None)
        table = [
            (cap(("a", "ok", 90, 90, None, True), ("b", "ok", 10, 10)), {}, "b"),
            (cap(("a", "ok", 90, 90, None, True)), {}, None),
            (cap(("a", "unknown", *unknown, "signed_in", True),
                 ("b", "unknown", *unknown, "signed_in")), {"a": T_LATE, "b": T_EARLY}, "b"),
            (cap(("a", "unknown", *unknown, "signed_in", True)), {"a": T_LATE}, None),
        ]
        for capacity, last_use, expected in table:
            with self.subTest(capacity=capacity["profiles"], last_use=last_use):
                self.assertEqual(manager.session_profile(capacity, last_use), expected)
        self.assertEqual(manager.choose_profile(cap(("a", "ok", 90, 90, None, True)), {}),
                         manager.Wait(None))

    def test_a_duplicate_profile_is_never_chosen(self):
        c = cap(("a", "out", 0, 0, "signed_in"), ("b", "ok", 80, 80, "signed_in"))
        c["profiles"][1]["duplicate_of"] = "a"
        d = cap(("a", "ok", 10, 10, "signed_in"), ("b", "ok", 90, 90, "signed_in"))
        d["profiles"][1]["duplicate_of"] = "a"
        self.assertEqual(manager.session_profile(c, {"b": T_LATE}), "a")
        self.assertEqual(manager.session_profile(d, {}), "a")

    def test_a_pinned_profile_with_room_wins(self):
        table = [
            cap(("a", "ok", 90, 90), ("b", "ok", 10, 10, None, False, True)),
            cap(("a", "ok", 90, 90), ("b", "reset", None, None, "signed_in", False, True)),
        ]
        for capacity in table:
            with self.subTest(capacity=capacity["profiles"]):
                self.assertEqual(manager.session_profile(capacity, {}), "b")
        self.assertEqual(manager.choose_profile(table[0], {}), "b")

    def test_a_pinned_profile_without_room_falls_back(self):
        unknown = (None, None)
        table = [
            (cap(("a", "ok", 90, 90), ("b", "out", 0, 0, None, False, True)), "a"),
            (cap(("a", "ok", 90, 90), ("b", "ok", 99, 99, "signed_out", False, True)), "a"),
            (cap(("a", "ok", 10, 10), ("b", "unknown", *unknown, "signed_in", False, True)), "a"),
            (cap(("a", "ok", 10, 10), ("b", "ok", 99, 99, None, True, True)), "a"),
            (cap(("b", "ok", 99, 99, None, True, True)), None),
        ]
        for capacity, expected in table:
            with self.subTest(capacity=capacity["profiles"]):
                self.assertEqual(manager.session_profile(capacity, {}), expected)
        self.assertEqual(manager.choose_profile(
            cap(("a", "out", 0, 0), ("b", "out", 0, 0, None, False, True),
                all_out=True, resumes_at="r"), {}), manager.Wait("r"))

    def test_with_no_room_the_most_recently_used_signed_in_profile_answers(self):
        unknown = (None, None)
        table = [
            (cap(("a", "unknown", *unknown, "signed_in"), ("b", "unknown", *unknown, "signed_in"),
                 ("c", "unknown", *unknown, "signed_out")),
             {"a": T_LATE, "b": T_EARLY, "c": "2026-11-13T11:00:00+00:00"}, "a"),
            (cap(("a", "out", 0, 0, "signed_in"), ("b", "unknown", *unknown, "signed_in")),
             {"b": T_EARLY}, "b"),
            (cap(("b", "unknown", *unknown, "signed_in"), ("a", "unknown", *unknown, "signed_in")),
             {}, "a"),
            (cap(("a", "unknown", *unknown), ("b", "unknown", *unknown, "signed_in")),
             {"a": T_LATE}, "b"),
            (cap(("a", "out", 0, 0, "signed_in"), all_out=True), {}, "a"),
        ]
        for capacity, last_use, expected in table:
            with self.subTest(capacity=capacity["profiles"], last_use=last_use):
                self.assertEqual(manager.session_profile(capacity, last_use), expected)

    def test_with_no_room_and_none_signed_in_nothing_is_chosen(self):
        unknown = (None, None)
        table = [
            (cap(("a", "out", 0, 0), ("b", "unknown", *unknown)), {"a": T_LATE}),
            (cap(), {}),
            (cap(("work", "ok", 90, 90, "signed_out")), {}),
            (cap(("work", "out", 0, 0, "signed_out"), ("home", "unknown", *unknown)),
             {"home": T_LATE}),
        ]
        for capacity, last_use in table:
            with self.subTest(capacity=capacity["profiles"], last_use=last_use):
                self.assertIsNone(manager.session_profile(capacity, last_use))
        self.assertEqual(manager.choose_profile(cap(), {}), manager.Wait(None))

    def test_profile_use_survives_a_session_leaving(self):
        def seen(seq, h, sid, profile):
            return Event(seq, hour(h), sessions.SEEN, "/srv/p01", {
                "session_id": sid, "cwd": "/srv/p01", "repo": "/srv/p01", "state": "idle",
                "profile": profile})

        def row(seq, h, kind, sid):
            return Event(seq, hour(h), kind, "/srv/p01", {"session_id": sid, "event": "Stop"})

        events = [
            seen(1, 9, "s-1", "work"),
            row(2, 11, sessions.HOOK, "s-1"),
            seen(3, 10, "s-2", "home"),
            row(4, 8, sessions.HOOK, "s-9"),
            Event(5, hour(12), sessions.GONE, "/srv/p01", {"session_id": "s-1"}),
            Event(6, hour(12), sessions.GONE, "/srv/p01", {"session_id": "s-2"}),
            row(7, 13, sessions.HOOK, "s-1"),
        ]
        use = manager.profile_use(events)
        self.assertEqual(dict(use.last), {"work": hour(11), "home": hour(10)})
        self.assertEqual(dict(use.owner), {})
        later = manager.profile_use([Event(8, hour(14), sessions.PROFILE, "/srv/p01", {
            "session_id": "s-3", "profile": "home"})], use)
        self.assertEqual(dict(later.last), {"work": hour(11), "home": hour(14)})
        self.assertEqual(dict(use.last), {"work": hour(11), "home": hour(10)})
        earlier = manager.profile_use([Event(9, "2026-11-13T15:00:00+05:00", sessions.SEEN,
                                             "/srv/p01", {"session_id": "s-4", "profile": "work",
                                                          "cwd": "/srv/p01", "repo": "/srv/p01",
                                                          "state": "idle"})], use)
        self.assertEqual(earlier.last["work"], hour(11))

    def test_a_newer_use_within_the_same_millisecond_wins(self):
        def stamp(micro):
            return f"2026-11-13T09:00:00.{micro:06d}+00:00"

        events = [
            Event(1, stamp(100), sessions.SEEN, "/srv/p01", {
                "session_id": "s-a", "cwd": "/srv/p01", "repo": "/srv/p01", "state": "idle",
                "profile": "a"}),
            Event(2, stamp(500), sessions.SEEN, "/srv/p01", {
                "session_id": "s-b", "cwd": "/srv/p01", "repo": "/srv/p01", "state": "idle",
                "profile": "b"}),
            Event(3, stamp(900), sessions.HOOK, "/srv/p01", {
                "session_id": "s-a", "event": "Stop"}),
        ]
        use = manager.profile_use(events)
        self.assertEqual(dict(use.last), {"a": stamp(900), "b": stamp(500)})
        both = cap(("a", "unknown", None, None, "signed_in"),
                   ("b", "unknown", None, None, "signed_in"))
        self.assertEqual(manager.session_profile(both, use.last), "a")

    def test_write_choice_replaces_the_file_atomically(self):
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / "accounts" / manager.CHOICE_FILE
            manager.write_choice(path, "work")
            self.assertEqual(path.read_text(), "work\n")
            self.assertEqual(sorted(os.listdir(path.parent)), ["chosen-profile"])
            first = path.stat().st_ino
            manager.write_choice(path, "home")
            self.assertEqual(path.read_text(), "home\n")
            self.assertNotEqual(path.stat().st_ino, first)
            self.assertEqual(sorted(os.listdir(path.parent)), ["chosen-profile"])
            sources = []

            def refuse(source, destination):
                sources.append(Path(source))
                raise OSError("full")

            with mock.patch("agent_tools.console.manager.os.replace", side_effect=refuse):
                with self.assertRaises(OSError):
                    manager.write_choice(path, "work")
            self.assertEqual(path.read_text(), "home\n")
            self.assertEqual(len(sources), 1)
            self.assertEqual(sources[0].parent, path.parent)
            self.assertFalse(sources[0].exists())
            self.assertEqual(sorted(os.listdir(path.parent)), ["chosen-profile"])
            manager.write_choice(path, None)
            self.assertFalse(path.exists())
            manager.write_choice(path, None)

    def test_read_choice_reads_the_first_line_or_nothing(self):
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / manager.CHOICE_FILE
            self.assertIsNone(manager.read_choice(path))
            for content, expected in [(b"home\n", "home"), (b"", None), (b"  \n", None),
                                      (b"\xff\xfe", None)]:
                with self.subTest(content=content):
                    path.write_bytes(content)
                    self.assertEqual(manager.read_choice(path), expected)


class ProfileTest(unittest.TestCase):
    def test_the_launch_choice_is_the_session_choice_or_a_wait(self):
        unknown = (None, None)
        table = [
            (cap(("a", "ok", 40, 90), ("b", "ok", 70, 10)), {}),
            (cap(("a", "ok", 90, 90, "signed_out"), ("b", "ok", 10, 10, "signed_in")), {}),
            (cap(("a", "out", 0, 0, "signed_in"), ("b", "unknown", *unknown, "signed_in")),
             {"b": T_EARLY}),
            (cap(("a", "unknown", *unknown, "signed_in"), ("b", "unknown", *unknown, "signed_in")),
             {"a": T_LATE, "b": T_EARLY}),
        ]
        for capacity, last_use in table:
            with self.subTest(capacity=capacity["profiles"], last_use=last_use):
                self.assertEqual(manager.choose_profile(capacity, last_use),
                                 manager.session_profile(capacity, last_use))
        until = "2026-11-13T00:00:00+00:00"
        self.assertEqual(manager.choose_profile(
            cap(("a", "out", 0, 0), ("b", "out", 0, 0), all_out=True, resumes_at=until), {}),
            manager.Wait(until))
        self.assertEqual(manager.choose_profile(cap(("default", "ok", 90, 90, "signed_out")), {}),
                         manager.Wait(None))

    def test_the_binding_is_no_longer_an_input(self):
        self.assertFalse(hasattr(manager, "bound_profile"))
        self.assertEqual(list(inspect.signature(manager.choose_profile).parameters),
                         ["capacity", "last_use", "starter", "waiting"])

    def test_quota_wait_reads_only_an_out_profile(self):
        until = "2026-11-13T00:00:00+00:00"
        capacity = {"profiles": [
            {"profile": "work", "state": "out", "week_left": 0, "five_hour_left": 0,
             "next_reset": until, "out_until": until, "read_at": None},
            {"profile": "home", "state": "ok", "week_left": 50, "five_hour_left": 50,
             "next_reset": None, "out_until": None, "read_at": None}]}
        self.assertEqual(manager.quota_wait(capacity, "work"), manager.Wait(until))
        for profile in ("home", "gone", None):
            with self.subTest(profile=profile):
                self.assertIsNone(manager.quota_wait(capacity, profile))


class ClientEnvironmentTest(unittest.TestCase):
    def test_a_client_never_inherits_a_platform_root(self):
        environ = {"HOME": "/home/u", "PATH": "/bin",
                   "AGENT_PLATFORM_ROOT": "/nix/store/x-agent-platform/share/agent-platform"}
        env = manager.client_environment("p", environ)
        self.assertNotIn("AGENT_PLATFORM_ROOT", env)
        self.assertEqual(env["PATH"], "/home/u/.agents/bin:/bin")
        self.assertIn("AGENT_PLATFORM_ROOT", environ)


class StopTest(unittest.TestCase):
    FULL = "0123456789abcdef-0123-4567"

    def test_the_stop_names_the_first_eight_characters_under_the_sessions_profile(self):
        calls = []

        def run(argv, **kwargs):
            calls.append((argv, kwargs))
            return SimpleNamespace(returncode=0)

        environ = {"HOME": "/home/u", "PATH": "/bin", "CONSOLE_SPRINT_SECRET": "s"}
        manager.stop_session(self.FULL, "work", run=run, environ=environ)
        argv, kwargs = calls[0]
        self.assertEqual(argv, ["claude-account", "run", "stop", "01234567"])
        self.assertEqual(kwargs["env"]["CLAUDE_ACCOUNT"], "work")
        self.assertNotIn("CONSOLE_SPRINT_SECRET", kwargs["env"])
        self.assertIs(kwargs["stdin"], subprocess.DEVNULL)
        self.assertEqual(kwargs["timeout"], 60)

    def test_a_stop_in_flight_is_ended_with_its_group_when_the_console_closes(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        client = tmp / "claude-account"
        client.write_text('#!/bin/sh\nsh -c \'echo $$ > "$PIDFILE"; exec sleep 60\' &\nwait\n')
        client.chmod(0o755)
        environ = {"PATH": f"{tmp}:/usr/bin:/bin", "HOME": str(tmp), "PIDFILE": str(tmp / "pid")}
        outcome = []

        def stop():
            try:
                manager.stop_session(self.FULL, "work", environ=environ)
                outcome.append(None)
            except manager.StopFailed as error:
                outcome.append(error)

        worker = threading.Thread(target=stop, daemon=True)
        worker.start()
        end = time.monotonic() + 5
        while not (tmp / "pid").exists() and time.monotonic() < end:
            time.sleep(0.02)
        pid = int((tmp / "pid").read_text())
        self.addCleanup(lambda: os.kill(pid, 9) if alive(pid) else None)
        self.assertTrue(alive(pid))
        manager.reap_stops()
        worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertIsInstance(outcome[0], manager.StopFailed)
        end = time.monotonic() + 5
        while alive(pid) and time.monotonic() < end:
            time.sleep(0.05)
        self.assertFalse(alive(pid))

    def test_a_failed_stop_raises_its_one_line_reason(self):
        def failing(argv, **kwargs):
            kwargs["stderr"].write(b"first\nNo job matching '01234567'\n")
            return SimpleNamespace(returncode=1)

        def silent(argv, **kwargs):
            return SimpleNamespace(returncode=3)

        def missing(argv, **kwargs):
            raise FileNotFoundError

        def slow(argv, **kwargs):
            raise subprocess.TimeoutExpired(argv, 60)

        cases = ((failing, "No job matching '01234567'"), (silent, "the stop exited 3"),
                 (missing, "claude-account is not installed"),
                 (slow, "the stop did not return within 60 s"))
        for stand_in, reason in cases:
            with self.subTest(reason):
                with self.assertRaises(manager.StopFailed) as raised:
                    manager.stop_session(self.FULL, "work", run=stand_in, environ={})
                self.assertEqual(str(raised.exception), reason)

    def test_every_listed_session_of_the_names_is_stopped_and_the_rest_left(self):
        def listed(session_id, name, profile):
            return Observation(session_id, "/srv", 1, "idle", None, name, None, profile)

        registry = {1: listed("s-a", "n a", "work"), 2: listed("s-b", "n b", None),
                    3: listed("s-c", "other", "work")}
        stopped = []
        manager.stop_listed(["n a", "n b"], lambda: registry,
                            lambda session_id, profile: stopped.append((session_id, profile)))
        self.assertEqual(stopped, [("s-a", "work"), ("s-b", "default")])

    def test_one_failed_stop_does_not_leave_the_others_running(self):
        registry = {i: Observation(f"s-{i}", "/srv", 1, "idle", None, "n", None, "work")
                    for i in (1, 2, 3)}
        stopped = []

        def stop(session_id, profile):
            stopped.append(session_id)
            if session_id != "s-3":
                raise manager.StopFailed(f"no {session_id}")

        with self.assertRaises(manager.StopFailed) as raised:
            manager.stop_listed(["n"], lambda: registry, stop)
        self.assertEqual(stopped, ["s-1", "s-2", "s-3"])
        self.assertEqual(str(raised.exception), "no s-1")

    def test_the_removal_names_the_first_eight_characters_under_the_sessions_profile(self):
        calls = []

        def run(argv, **kwargs):
            calls.append((argv, kwargs))
            return SimpleNamespace(returncode=0)

        environ = {"HOME": "/home/u", "PATH": "/bin", "CONSOLE_SPRINT_SECRET": "s"}
        manager.remove_session(self.FULL, "work", run=run, environ=environ)
        argv, kwargs = calls[0]
        self.assertEqual(argv, ["claude-account", "run", "rm", "01234567"])
        self.assertEqual(kwargs["env"]["CLAUDE_ACCOUNT"], "work")
        self.assertNotIn("CONSOLE_SPRINT_SECRET", kwargs["env"])
        self.assertIs(kwargs["stdin"], subprocess.DEVNULL)
        self.assertEqual(kwargs["timeout"], 60)

    def test_a_failed_removal_raises_its_one_line_reason(self):
        def failing(argv, **kwargs):
            kwargs["stderr"].write(b"first\nno such session\n\n")
            return SimpleNamespace(returncode=1)

        def silent(argv, **kwargs):
            return SimpleNamespace(returncode=3)

        def missing(argv, **kwargs):
            raise FileNotFoundError

        def slow(argv, **kwargs):
            raise subprocess.TimeoutExpired(argv, 60)

        self.assertTrue(issubclass(manager.RemoveFailed, manager.StopFailed))
        cases = ((failing, "no such session"), (silent, "the removal exited 3"),
                 (missing, "claude-account is not installed"),
                 (slow, "the removal did not return within 60 s"))
        for stand_in, reason in cases:
            with self.subTest(reason):
                with self.assertRaises(manager.RemoveFailed) as raised:
                    manager.remove_session(self.FULL, "work", run=stand_in, environ={})
                self.assertEqual(str(raised.exception), reason)

    def test_a_stop_is_recorded_once_and_a_failed_one_not_at_all(self):
        registry = {
            1: Observation("s-a", "/srv", 1, "idle", None, "n", None, "work"),
            2: Observation("s-b", "/srv", 1, "idle", None, "n", None, None),
            3: Observation("s-c", "/srv", 1, "idle", None, "n", None, "work")}

        def stop(session_id, profile):
            if session_id == "s-c":
                raise manager.StopFailed("no s-c")

        stopped = [{"session_id": "s-a", "profile": "work"}]
        with self.assertRaises(manager.StopFailed) as raised:
            manager.stop_listed(["n"], lambda: registry, stop, stopped)
        self.assertEqual(str(raised.exception), "no s-c")
        self.assertEqual(stopped, [{"session_id": "s-a", "profile": "work"},
                                   {"session_id": "s-b", "profile": "default"}])

    def test_a_removed_entry_does_not_hide_a_new_stop_of_the_same_id(self):
        registry = {1: Observation("s-a", "/srv", 1, "idle", None, "n", None, "work")}
        stopped = [{"session_id": "s-a", "profile": "work", "removed": True}]
        manager.stop_listed(["n"], lambda: registry, lambda session_id, profile: None, stopped)
        self.assertEqual(stopped, [{"session_id": "s-a", "profile": "work", "removed": True},
                                   {"session_id": "s-a", "profile": "work"}])

    def test_a_retry_that_stops_the_same_id_under_another_profile_records_it_too(self):
        registry = {1: Observation("s-a", "/srv", 1, "idle", None, "n", None, "p2")}
        stopped = [{"session_id": "s-a", "profile": "work"}]
        manager.stop_listed(["n"], lambda: registry, lambda session_id, profile: None, stopped)
        self.assertEqual(stopped, [{"session_id": "s-a", "profile": "work"},
                                   {"session_id": "s-a", "profile": "p2"}])
        calls = []
        manager.remove_stopped(stopped, lambda session_id, profile: calls.append(profile))
        self.assertEqual(calls, ["work", "p2"])

    def test_every_unremoved_session_is_removed_and_a_failure_is_kept_for_the_retry(self):
        stopped = [{"session_id": "s-a", "profile": "work", "removed": True},
                   {"session_id": "s-b", "profile": "work"},
                   {"session_id": "s-c", "profile": "default"},
                   {"session_id": "s-d", "profile": "work"}]
        calls = []

        def remove(session_id, profile):
            calls.append((session_id, profile))
            if session_id == "s-c":
                raise manager.RemoveFailed("no s-c")

        with self.assertRaises(manager.RemoveFailed) as raised:
            manager.remove_stopped(stopped, remove)
        self.assertEqual(str(raised.exception), "no s-c")
        self.assertEqual(calls, [("s-b", "work"), ("s-c", "default"), ("s-d", "work")])
        self.assertEqual([entry.get("removed") for entry in stopped], [True, True, None, True])
        calls.clear()
        self.assertIsNone(manager.remove_stopped(
            stopped, lambda session_id, profile: calls.append((session_id, profile))))
        self.assertEqual(calls, [("s-c", "default")])

    def test_the_revive_check_removes_through_the_shared_removal(self):
        default = inspect.signature(revive_check.main).parameters["remove"].default
        self.assertIs(default, manager.remove_session)
        self.assertFalse(hasattr(revive_check, "default_remove"))

    def test_before_runs_ahead_of_each_stop_and_removal_and_its_exception_ends_the_loop(self):
        registry = {1: Observation("s-a", "/srv", 1, "idle", None, "n", None, "work"),
                    2: Observation("s-b", "/srv", 1, "idle", None, "n", None, "work")}
        calls = []
        stopped = []

        def stop(session_id, profile):
            calls.append(("stop", session_id))

        def remove(session_id, profile):
            calls.append(("remove", session_id))

        def before():
            calls.append(("before", len(stopped)))
            if len(calls) > 2:
                raise manager.OutOfTime(manager.OUT_OF_TIME_TEXT)

        self.assertFalse(issubclass(manager.OutOfTime, manager.StopFailed))
        with self.assertRaises(manager.OutOfTime):
            manager.stop_listed(["n"], lambda: registry, stop, stopped, before)
        self.assertEqual(calls, [("before", 0), ("stop", "s-a"), ("before", 1)])
        self.assertEqual(stopped, [{"session_id": "s-a", "profile": "work"}])

        calls.clear()
        entries = [{"session_id": "s-a", "profile": "work"},
                   {"session_id": "s-b", "profile": "work"}]

        def second_refuses():
            calls.append(("before",))
            if len(calls) > 2:
                raise manager.OutOfTime(manager.OUT_OF_TIME_TEXT)

        with self.assertRaises(manager.OutOfTime):
            manager.remove_stopped(entries, remove, second_refuses)
        self.assertEqual(calls, [("before",), ("remove", "s-a"), ("before",)])
        self.assertIs(entries[0]["removed"], True)
        self.assertNotIn("removed", entries[1])

    def test_the_finish_guard_saves_then_refuses_a_call_that_could_outlast_the_run(self):
        now = [1530.0]
        saves = []
        guard = manager.finish_guard(lambda: now[0], 1000.0, 540, lambda: saves.append(now[0]))
        self.assertEqual(manager.FINISH_LIMIT, 590)
        self.assertIsNone(guard())
        self.assertEqual(saves, [1530.0])
        now[0] = 1531.0
        with self.assertRaises(manager.OutOfTime) as raised:
            guard()
        self.assertEqual(str(raised.exception), manager.OUT_OF_TIME_TEXT)
        self.assertEqual(saves, [1530.0, 1531.0])
        wide = manager.finish_guard(lambda: now[0], 1000.0, 2000, lambda: None)
        now[0] = 2990.0
        self.assertIsNone(wide())
        now[0] = 2991.0
        with self.assertRaises(manager.OutOfTime):
            wide()

    def test_mark_removed_marks_the_open_entry_or_records_a_removed_one(self):
        stopped = [{"session_id": "s-a", "profile": "work", "removed": True},
                   {"session_id": "s-a", "profile": "work"}]
        manager.mark_removed(stopped, "s-a", "work")
        manager.mark_removed(stopped, "s-b", "p2")
        self.assertEqual(stopped, [
            {"session_id": "s-a", "profile": "work", "removed": True},
            {"session_id": "s-a", "profile": "work", "removed": True},
            {"session_id": "s-b", "profile": "p2", "removed": True}])

    def test_mark_removed_does_not_mark_the_same_id_under_another_profile(self):
        stopped = [{"session_id": "s-a", "profile": "work"}]
        manager.mark_removed(stopped, "s-a", "p2")
        self.assertEqual(stopped, [
            {"session_id": "s-a", "profile": "work"},
            {"session_id": "s-a", "profile": "p2", "removed": True}])


class ExclusionTest(unittest.TestCase):
    def test_the_fold_keeps_the_last_valid_row_of_each_profile(self):
        events = [
            Event(1, hour(9), "profile.exclusion", None, {"profile": "work", "excluded": True}),
            Event(2, hour(10), "profile.exclusion", None, {"profile": "home", "excluded": True}),
            Event(3, hour(11), "profile.exclusion", None, {"profile": "work", "excluded": False}),
            Event(4, hour(12), "profile.exclusion", None, {"profile": "home", "excluded": 0}),
            Event(5, hour(13), "profile.exclusion", None, {"profile": "", "excluded": False}),
            Event(6, hour(14), "profile.exclusion", None, {"excluded": False}),
            Event(7, hour(15), "session.seen", None, {"profile": "home", "excluded": False}),
        ]
        self.assertEqual(exclusion.excluded_profiles(events), frozenset({"home"}))
        self.assertEqual(
            exclusion.excluded_profiles(events[3:], exclusion.excluded_profiles(events[:3])),
            frozenset({"home"}))
        self.assertEqual(exclusion.excluded_profiles([]), frozenset())
        self.assertEqual(exclusion.entry("work", True),
                         ("profile.exclusion", None, {"profile": "work", "excluded": True}))

    def test_a_request_names_one_profile_and_a_bool(self):
        self.assertEqual(exclusion.parse_request(b'{"profile":"work","excluded":true}'),
                         ("work", True))
        self.assertEqual(exclusion.parse_request(b'{"excluded":false,"profile":"home"}'),
                         ("home", False))
        refused = {
            "no excluded": b'{"profile":"work"}',
            "integer excluded": b'{"profile":"work","excluded":1}',
            "empty profile": b'{"profile":"","excluded":true}',
            "extra key": b'{"profile":"work","excluded":true,"x":1}',
            "not an object": b"[]",
            "not utf-8": b"\xff",
            "long profile": ('{"profile":"%s","excluded":true}' % ("a" * 129)).encode(),
        }
        for name, body in refused.items():
            with self.subTest(name), self.assertRaises(ValueError):
                exclusion.parse_request(body)


class PinTest(unittest.TestCase):
    def test_the_fold_keeps_one_pin_and_moves_it(self):
        events = [
            Event(1, hour(9), "profile.pin", None, {"profile": "work", "pinned": True}),
            Event(2, hour(10), "profile.pin", None, {"profile": "home", "pinned": True}),
            Event(3, hour(11), "profile.pin", None, {"profile": "work", "pinned": False}),
            Event(4, hour(12), "profile.pin", None, {"profile": "home", "pinned": 1}),
            Event(5, hour(13), "profile.pin", None, {"profile": "", "pinned": True}),
            Event(6, hour(14), "profile.pin", None, {"pinned": True}),
            Event(7, hour(15), "session.seen", None, {"profile": "x", "pinned": True}),
        ]
        self.assertEqual(pin.pinned_profile(events), "home")
        self.assertEqual(pin.pinned_profile(events[2:], pin.pinned_profile(events[:2])), "home")
        self.assertIsNone(pin.pinned_profile(
            events + [Event(8, hour(16), "profile.pin", None,
                            {"profile": "home", "pinned": False})]))
        self.assertIsNone(pin.pinned_profile([]))
        self.assertEqual(pin.entry("work", True),
                         ("profile.pin", None, {"profile": "work", "pinned": True}))

    def test_launches_under_the_pin_in_force_are_kept(self):
        def ev(seq, kind, payload):
            return Event(seq, hour(seq), kind, None, payload)

        def pinned(seq, profile, value=True):
            return ev(seq, "profile.pin", {"profile": profile, "pinned": value})

        def seen(seq, sid, profile):
            return ev(seq, "session.seen", {"session_id": sid, "profile": profile})

        def started(seq, sid, profile):
            return ev(seq, "manager.started", {"sprint_id": sid, "profile": profile})

        events = [
            seen(1, "s1", "work"), started(2, "x", "work"), pinned(3, "work"),
            seen(4, "s1", "work"), seen(5, "s2", "home"), pinned(6, "home"),
            started(7, "y", "work"), seen(8, "s3", "home"), pinned(9, "home", False),
            started(10, "z", "home"), seen(11, "s4", "work"),
        ]
        state = pin.pin_launches(events)
        self.assertEqual(state.launched, frozenset({"home"}))
        self.assertIsNone(state.pinned)
        self.assertEqual(state.seen, frozenset({"s1", "s2", "s3", "s4"}))
        self.assertEqual(pin.pin_launches(events[5:], pin.pin_launches(events[:5])), state)
        self.assertEqual(pin.pin_launches([
            pinned(1, "work"), started(2, "x", "work"), pinned(3, "work", False)]).launched,
            frozenset({"work"}))
        self.assertEqual(pin.pin_launches([
            pinned(1, "work", 1), started(2, "x", "work")]).launched, frozenset())
        self.assertEqual(pin.pin_launches([]), pin.PinLaunches(None, frozenset(), frozenset()))

    def test_a_session_that_started_before_the_pin_is_not_a_launch_under_it(self):
        def ev(seq, kind, payload):
            return Event(seq, hour(seq), kind, None, payload)

        hook = ev(1, "session.hook", {"session_id": "s1", "event": "SessionStart"})
        profile = ev(2, "session.profile", {"session_id": "s1", "profile": "home"})
        pinned = ev(3, "profile.pin", {"profile": "home", "pinned": True})
        later_seen = ev(4, "session.seen", {"session_id": "s1", "profile": "home"})
        self.assertEqual(pin.pin_launches([hook, profile, pinned, later_seen]).launched,
                         frozenset())
        state = pin.pin_launches([hook, profile, pinned])
        self.assertEqual(pin.pin_launches([later_seen], state).launched, frozenset())

    def test_a_session_that_started_under_the_pin_is_a_launch_once_its_profile_is_known(self):
        def ev(seq, kind, payload):
            return Event(seq, hour(seq), kind, None, payload)

        pinned = ev(1, "profile.pin", {"profile": "home", "pinned": True})
        hook = ev(2, "session.hook", {"session_id": "s1", "event": "SessionStart"})
        profile = ev(3, "session.profile", {"session_id": "s1", "profile": "home"})
        started = pin.pin_launches([pinned, hook])
        self.assertEqual(started.launched, frozenset())
        self.assertEqual(pin.pin_launches([profile], started).launched, frozenset({"home"}))
        unpinned = ev(4, "profile.pin", {"profile": "home", "pinned": False})
        self.assertEqual(pin.pin_launches([pinned, hook, unpinned, profile]).launched,
                         frozenset({"home"}))
        other = ev(3, "session.profile", {"session_id": "s1", "profile": "work"})
        self.assertEqual(pin.pin_launches([pinned, hook, other, profile]).launched, frozenset())
        stray = ev(3, "session.profile", {"session_id": "s9", "profile": "home"})
        self.assertEqual(pin.pin_launches([pinned, stray]).launched, frozenset())

    def test_the_note_says_why_the_pin_is_not_in_effect(self):
        out = cap(("a", "ok", 9, 9), ("b", "out", 0, 0, None, False, True))
        out["profiles"][1]["out_until"] = "2026-11-20T09:30:00+00:00"
        unknown = (None, None)
        table = [
            (None, cap(("a", "ok", 9, 9)), "a", None),
            ("b", cap(("a", "ok", 9, 9), ("b", "ok", 1, 1, None, False, True)), "b",
             {"profile": "b", "in_effect": True, "reason": None, "until": None, "instead": None}),
            ("b", out, "a",
             {"profile": "b", "in_effect": False, "reason": "out of allowance",
              "until": "2026-11-20T09:30:00+00:00", "instead": "a"}),
            ("b", cap(("a", "ok", 9, 9), ("b", "ok", 1, 1, "signed_out", False, True)), "a",
             {"profile": "b", "in_effect": False, "reason": "signed out",
              "until": None, "instead": "a"}),
            ("b", cap(("a", "ok", 9, 9), ("b", "unknown", *unknown, None, False, True)), "a",
             {"profile": "b", "in_effect": False, "reason": "no reading yet",
              "until": None, "instead": "a"}),
            ("b", cap(("a", "ok", 9, 9), ("b", "ok", 1, 1, None, True, True)), "a",
             {"profile": "b", "in_effect": False, "reason": "excluded",
              "until": None, "instead": "a"}),
            ("b", cap(("a", "ok", 9, 9), ("b", "ok", 1, 1, "signed_out", True, True)), "a",
             {"profile": "b", "in_effect": False, "reason": "excluded",
              "until": None, "instead": "a"}),
            ("gone", cap(("a", "ok", 9, 9)), None,
             {"profile": "gone", "in_effect": False, "reason": "not a listed account",
              "until": None, "instead": None}),
        ]
        for pinned, capacity, chosen, expected in table:
            with self.subTest(pinned=pinned, capacity=capacity["profiles"]):
                self.assertEqual(pin.note(pinned, capacity, chosen), expected)

    def test_a_request_names_one_profile_and_a_bool(self):
        self.assertEqual(pin.parse_request(b'{"profile":"work","pinned":true}'), ("work", True))
        self.assertEqual(pin.parse_request(b'{"pinned":false,"profile":"home"}'), ("home", False))
        refused = {
            "no pinned": b'{"profile":"work"}',
            "integer pinned": b'{"profile":"work","pinned":1}',
            "empty profile": b'{"profile":"","pinned":true}',
            "extra key": b'{"profile":"work","pinned":true,"x":1}',
            "not an object": b"[]",
            "not utf-8": b"\xff",
            "long profile": ('{"profile":"%s","pinned":true}' % ("a" * 129)).encode(),
        }
        for name, body in refused.items():
            with self.subTest(name), self.assertRaises(ValueError):
                pin.parse_request(body)


ALICE = "alice@example.invalid"
BOB = "bob@example.invalid"


class ColleagueAccountTest(unittest.TestCase):
    """A colleague's account serves his own sprints first and anyone's when it has room (#1344, ADR-console-087 D1)."""

    def test_his_own_sprint_takes_his_account_while_it_has_room_though_an_owner_account_has_more(self):
        shown = cap(("work", "ok", 90, 90), ("colleague-1", "ok", 10, 10, None, False, False, ALICE))
        self.assertEqual(manager.session_profile(shown, {}, ALICE), "colleague-1")
        self.assertEqual(manager.choose_profile(shown, {}, ALICE), "colleague-1")
        self.assertEqual(manager.session_profile(shown, {}), "work")

    def test_his_own_sprint_chooses_among_his_accounts_by_the_usual_rule(self):
        shown = cap(("work", "ok", 90, 90), ("c1", "ok", 10, 10, None, False, False, ALICE),
                    ("c2", "ok", 40, 10, None, False, False, ALICE),
                    ("b1", "ok", 99, 99, None, False, False, BOB))
        self.assertEqual(manager.session_profile(shown, {}, ALICE), "c2")

    def test_his_own_sprint_falls_to_the_usual_choice_when_his_account_has_no_room(self):
        unknown = (None, None)
        table = [
            cap(("work", "ok", 20, 20), ("c1", "out", 0, 0, None, False, False, ALICE)),
            cap(("work", "ok", 20, 20), ("c1", "ok", 90, 90, "signed_out", False, False, ALICE)),
            cap(("work", "ok", 20, 20), ("c1", "ok", 90, 90, None, True, False, ALICE)),
            cap(("work", "ok", 20, 20), ("c1", "unknown", *unknown, "signed_in", False, False, ALICE)),
        ]
        for shown in table:
            with self.subTest(shown=shown["profiles"]):
                self.assertEqual(manager.session_profile(shown, {}, ALICE), "work")

    def test_another_sprint_takes_his_account_when_it_has_room_and_none_of_his_waits(self):
        shown = cap(("work", "ok", 20, 20), ("c1", "ok", 90, 90, None, False, False, ALICE))
        self.assertEqual(manager.session_profile(shown, {}), "c1")
        self.assertEqual(manager.session_profile(shown, {}, BOB), "c1")
        self.assertEqual(manager.session_profile(shown, {}, None, frozenset({BOB})), "c1")
        self.assertEqual(manager.session_profile(shown, {}, BOB, frozenset({ALICE})), "work")
        self.assertEqual(manager.session_profile(shown, {}, None, frozenset({ALICE})), "work")
        self.assertEqual(manager.choose_profile(shown, {}, None, frozenset({ALICE})), "work")

    def test_the_tight_pool_of_one_low_owner_account_and_two_out(self):
        low = ("work", "ok", 5, 5)
        out = ("home", "out", 0, 0)
        colleague_out = ("c1", "out", 0, 0, None, False, False, ALICE)
        shown = cap(low, out, colleague_out)
        for starter in (None, ALICE, BOB):
            self.assertEqual(manager.session_profile(shown, {}, starter), "work")
        room = cap(low, out, ("c1", "ok", 50, 50, None, False, False, ALICE))
        self.assertEqual(manager.session_profile(room, {}), "c1")
        self.assertEqual(manager.session_profile(room, {}, None, frozenset({ALICE})), "work")
        self.assertEqual(manager.session_profile(room, {}, ALICE, frozenset({ALICE})), "c1")

    def test_a_barred_account_is_not_the_no_room_fallback_either(self):
        unknown = (None, None)
        shown = cap(("work", "out", 0, 0, "signed_in"),
                    ("c1", "unknown", *unknown, "signed_in", False, False, ALICE))
        self.assertEqual(manager.session_profile(shown, {"c1": T_LATE}, None), "work")
        self.assertEqual(manager.session_profile(shown, {"c1": T_LATE}, ALICE), "c1")
        self.assertEqual(manager.session_profile(shown, {"c1": T_LATE}, None, frozenset({ALICE})),
                         "work")
        only = cap(("c1", "ok", 90, 90, "signed_in", False, False, ALICE))
        self.assertIsNone(manager.session_profile(only, {}, None, frozenset({ALICE})))
        self.assertEqual(manager.choose_profile(only, {}, None, frozenset({ALICE})),
                         manager.Wait(None))

    def test_the_owners_pin_outranks_the_preference_and_the_reservation(self):
        pinned = cap(("work", "ok", 20, 20, None, False, True),
                     ("c1", "ok", 90, 90, None, False, False, ALICE))
        self.assertEqual(manager.session_profile(pinned, {}, ALICE), "work")
        theirs = cap(("work", "ok", 90, 90), ("c1", "ok", 20, 20, None, False, True, ALICE))
        self.assertEqual(manager.session_profile(theirs, {}, None, frozenset({ALICE})), "c1")
        self.assertEqual(manager.session_profile(theirs, {}, BOB, frozenset({ALICE})), "c1")

    def test_the_owners_own_accounts_are_chosen_as_before_with_a_colleague_in_the_pool(self):
        shown = cap(("a", "ok", 40, 90), ("b", "ok", 70, 10),
                    ("c1", "out", 0, 0, None, False, False, ALICE))
        for starter in (None, ALICE, BOB):
            for waiting in (frozenset(), frozenset({ALICE})):
                self.assertEqual(manager.session_profile(shown, {}, starter, waiting), "b")

    def test_a_fold_with_one_owner_and_one_colleague_account(self):
        def read(profile, used):
            return reading_of(report(status="allowed", reset=T + 3600, binding="7d",
                                     claim="seven_day",
                                     windows={"7d": window("allowed", used, T + 3600)}), profile)
        state = capacity.CapacityState({"work": read("work", 0.1),
                                        "colleague-1": read("colleague-1", 0.7)}, {})
        fold = capacity.capacity_view(["work", "colleague-1"], state, T,
                                      owners={"colleague-1": ALICE})
        self.assertEqual(manager.session_profile(fold, {}), "work")
        self.assertEqual(manager.session_profile(fold, {}, ALICE), "colleague-1")
        self.assertEqual(manager.choose_profile(fold, {}, ALICE), "colleague-1")

    def test_a_colleagues_account_without_a_room_reading_is_only_his_own_fallback(self):
        unknown = (None, None)
        shown = cap(("work", "out", 0, 0, "signed_in"),
                    ("c1", "unknown", *unknown, "signed_in", False, False, ALICE))
        for starter, expected in ((None, "work"), (BOB, "work"), (ALICE, "c1")):
            self.assertEqual(manager.session_profile(shown, {"c1": T_LATE}, starter), expected)

    def test_the_wait_is_over_the_accounts_the_sprint_may_use(self):
        soon, later = "2026-11-13T01:00:00+00:00", "2026-11-13T02:00:00+00:00"
        shown = cap(("work", "out", 0, 0, "signed_in"), ("c1", "ok", 50, 50, None, False, False, ALICE))
        shown["profiles"][0]["out_until"] = later
        self.assertEqual(manager.choose_profile(shown, {}), "c1")
        self.assertEqual(manager.choose_profile(shown, {}, None, frozenset({ALICE})), manager.Wait(later))
        self.assertEqual(manager.choose_profile(shown, {}, ALICE, frozenset({ALICE})), "c1")
        other = cap(("work", "out", 0, 0, "signed_in"), ("home", "out", 0, 0, "signed_in"),
                    ("c1", "ok", 50, 50, None, False, False, ALICE))
        other["profiles"][0]["out_until"] = later
        other["profiles"][1]["out_until"] = soon
        self.assertEqual(manager.choose_profile(other, {}, BOB, frozenset({ALICE})), manager.Wait(soon))

    def test_a_pin_with_room_is_not_a_wait_whatever_else_reads(self):
        shown = cap(("work", "out", 0, 0, "signed_in"),
                    ("c1", "ok", 50, 50, None, False, True, ALICE))
        self.assertEqual(manager.choose_profile(shown, {}, None, frozenset({ALICE})), "c1")

    def test_an_alias_of_a_colleagues_profile_is_his_account_whichever_profile_keeps_it(self):
        shown = cap(("a-work", "ok", 90, 90), ("c1", "ok", 90, 90, None, False, False, ALICE),
                    ("other", "ok", 10, 10))
        shown["profiles"][0]["same_account_as"] = ["c1"]
        shown["profiles"][1]["same_account_as"] = ["a-work"]
        shown["profiles"][1]["duplicate_of"] = "a-work"
        self.assertEqual(manager.session_profile(shown, {}, ALICE), "a-work")
        self.assertEqual(manager.session_profile(shown, {}, BOB, frozenset({ALICE})), "other")
        self.assertEqual(manager.session_profile(shown, {}, None, frozenset({ALICE})), "other")
        self.assertEqual(manager.session_profile(shown, {}), "a-work")
        self.assertTrue(manager.colleague_account(shown, "a-work"))
        self.assertFalse(manager.colleague_account(shown, "other"))


if __name__ == "__main__":
    unittest.main()

