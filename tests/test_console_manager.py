"""The manager launch core: profile choice, scoped background command, settings file, runner (#888).

Run: just agent-workflow-tests
"""
import inspect
import json
import os
import shutil
import stat
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from agent_tools.console import manager, revive_check, sessions
from agent_tools.console.event_log import Event
from agent_tools.console.sessions import Observation

REPO_ROOT = Path(__file__).resolve().parents[1]
SID = "a" * 16
NAME = "owner/p01 sprint " + SID
LEAD = ("You are the manager of one sprint, started by the console. "
        'Run "sprint contract" first and follow what it prints. The goal: ')
PROMPT = LEAD + "make it resumable"
REFUSAL = ("Nobody watches this session, so the permission prompt was refused: do the step "
           "another way that needs no permission, or bring the choice to the owner with "
           "`sprint ask`.")


def cap(*rows, all_out=False, resumes_at=None):
    def entry(p, s, w, f, signin=None):
        row = {"profile": p, "state": s, "week_left": w, "five_hour_left": f,
               "next_reset": None, "out_until": None, "read_at": None}
        if signin is not None:
            row["signin"] = {"state": signin}
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

    def test_the_linux_command_runs_the_manager_in_its_own_scope(self):
        command = manager.launch_command(self.launch(), "linux")
        self.assertEqual(command, [
            "systemd-run", "--user", "--scope", "--quiet", "--collect",
            "--description=agent manager " + NAME, "--", "claude-account", "run", "--bg",
            "--name", NAME, "--settings", str(self.settings), PROMPT])
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

    def test_the_settings_turn_the_isolation_guard_off_and_refuse_every_permission_prompt(self):
        self.run_fake()
        settings = json.loads(self.settings.read_text())
        self.assertEqual(set(settings), {"env", "worktree", "hooks"})
        self.assertEqual(settings["worktree"], {"bgIsolation": "none"})
        self.assertEqual(set(settings["hooks"]), {"PermissionRequest"})
        [group] = settings["hooks"]["PermissionRequest"]
        self.assertNotIn("matcher", group)
        [hook] = group["hooks"]
        self.assertEqual(hook["type"], "command")
        done = subprocess.run(["sh", "-c", hook["command"]], capture_output=True, text=True,
                              check=True)
        self.assertEqual(json.loads(done.stdout), {"hookSpecificOutput": {
            "hookEventName": "PermissionRequest",
            "decision": {"behavior": "deny", "message": REFUSAL}}})
        self.assertEqual(done.stderr, "")

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

    def test_with_no_sign_in_known_the_answer_is_default_unless_default_is_signed_out(self):
        unknown = (None, None)
        table = [
            (cap(("a", "out", 0, 0), ("b", "unknown", *unknown)), {"a": T_LATE}, "default"),
            (cap(), {}, "default"),
            (cap(("default", "ok", 90, 90, "signed_out")), {}, None),
            (cap(("default", "out", 0, 0, "signed_out"), ("work", "unknown", *unknown)), {}, None),
        ]
        for capacity, last_use, expected in table:
            with self.subTest(capacity=capacity["profiles"], last_use=last_use):
                self.assertEqual(manager.session_profile(capacity, last_use), expected)

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
                         ["capacity", "last_use"])

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


if __name__ == "__main__":
    unittest.main()
