"""The manager launch core: profile choice, scoped background command, settings file, runner (#888).

Run: just agent-workflow-tests
"""
import json
import os
import shutil
import stat
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from agent_tools.console import manager

REPO_ROOT = Path(__file__).resolve().parents[1]
SID = "a" * 16
NAME = "owner/p01 sprint " + SID
PROMPT = "/manage-sprint make it resumable"


def cap(*rows, all_out=False, resumes_at=None):
    return {"tight": False, "all_out": all_out, "resumes_at": resumes_at,
            "profiles": [{"profile": p, "state": s, "week_left": w, "five_hour_left": f,
                          "next_reset": None, "out_until": None, "read_at": None}
                         for p, s, w, f in rows]}


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

    def test_the_linux_command_runs_the_manager_in_its_own_scope(self):
        command = manager.launch_command(self.launch(), "linux")
        self.assertEqual(command, [
            "systemd-run", "--user", "--scope", "--quiet", "--collect",
            "--description=agent manager " + NAME, "--", "claude-account", "run", "--bg",
            "--name", NAME, "--settings", str(self.settings), PROMPT])
        self.assertFalse([part for part in command if "s3cret" in part])

    def test_no_command_is_built_on_macos(self):
        self.assertIsNone(manager.launch_command(self.launch(), "darwin"))
        self.assertIs(manager.supported("darwin"), False)
        self.assertIs(manager.supported("linux"), True)
        self.assertIsNone(manager.launcher_for("darwin"))
        self.assertIs(manager.launcher_for("linux"), manager.run_launch)


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

    def test_the_identity_is_written_to_a_private_settings_file(self):
        self.run_fake()
        self.assertEqual(json.loads(self.settings.read_text()), {"env": {
            "CONSOLE_SPRINT_ID": SID, "CONSOLE_SPRINT_SECRET": "s3cret"}})
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
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        for name in manager.LAUNCH_TOOLS:
            if name == "systemd-run":
                continue
            found = shutil.which(name)
            if found is None:
                self.skipTest(f"{name} is not installed")
            (bin_dir / name).symlink_to(found)
        bash = shutil.which("bash")
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
        manager.run_launch(self.launch(root=str(self.root)), platform="linux", environ={
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
        with self.subTest("macos"):
            self.root_for = str(self.root)
            run = self.fake()
            with self.assertRaises(manager.LaunchFailed) as caught:
                manager.run_launch(self.launch(root=self.root_for), platform="darwin", run=run,
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


class ProfileTest(unittest.TestCase):
    def test_the_profile_choice_rule(self):
        wait = manager.Wait("2026-11-13T00:00:00+00:00")
        table = [
            (cap(("a", "ok", 40, 90), ("b", "ok", 70, 10)), "a", "b"),
            (cap(("a", "ok", 70, 20), ("b", "ok", 70, 50)), "a", "b"),
            (cap(("b", "ok", 70, 50), ("a", "ok", 70, 50)), "b", "a"),
            (cap(("a", "out", 0, 0), ("b", "reset", 100, 100)), "a", "b"),
            (cap(("a", "ok", None, None), ("b", "ok", 5, 5)), "a", "b"),
            (cap(("a", "unknown", None, None), ("b", "unknown", None, None)), "b", "b"),
            (cap(), "default", "default"),
            (cap(("a", "out", 0, 0), ("b", "unknown", None, None)), "a", "b"),
            (cap(("a", "out", 0, 0), ("b", "unknown", None, None)), "c", "c"),
            (cap(("a", "out", 0, 0), ("b", "out", 0, 0), all_out=True,
                 resumes_at="2026-11-13T00:00:00+00:00"), "a", wait),
        ]
        for capacity, bound, expected in table:
            with self.subTest(rows=capacity["profiles"], bound=bound):
                self.assertEqual(manager.choose_profile(capacity, bound), expected)

    def test_the_bound_profile_is_read_from_the_bindings(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "bindings.tsv").write_text("/srv\tparent\n/srv/p01\twork\n")
            self.assertEqual(manager.bound_profile("/srv/p01", d), "work")
            self.assertEqual(manager.bound_profile("/srv/p02", d), "parent")
            self.assertEqual(manager.bound_profile("/elsewhere", d), "default")
            empty = d / "empty"
            empty.mkdir()
            self.assertEqual(manager.bound_profile("/srv/p01", empty), "default")
            with mock.patch.dict(os.environ, {"CLAUDE_ACCOUNTS_DIR": str(d)}):
                self.assertEqual(manager.bound_profile("/srv/p01"), "work")

    def test_a_linked_worktree_reads_its_main_checkouts_binding(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(os.path.realpath(tmp))
            main, worktree = d / "src" / "repo", d / "work" / "topic"
            admin = main / ".git" / "worktrees" / "topic"
            admin.mkdir(parents=True)
            (admin / "commondir").write_text("../..\n")
            worktree.mkdir(parents=True)
            (worktree / ".git").write_text(f"gitdir: {admin}\n")
            (d / "bindings.tsv").write_text(f"{main}\twork\n")
            self.assertEqual(manager.bound_profile(str(worktree), d), "work")
            self.assertEqual(manager.bound_profile(str(main), d), "work")
            self.assertEqual(manager.bound_profile(str(d / "work"), d), "default")


if __name__ == "__main__":
    unittest.main()
