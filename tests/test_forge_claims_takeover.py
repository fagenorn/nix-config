"""forge-claim's early takeover of a claim whose holding session provably no longer runs on this host."""
import contextlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent_tools.claims import forge_markers as fm
from agent_tools.console import service, sessions, sprints
from agent_tools.delivery import issue_setup

from .console_test_support import PROC_PID_DOMAIN, fake_proc
from .forge_world import ForgeWorld

try:
    import agent_tools.claims.claim_takeover as claim_takeover
except ModuleNotFoundError as error:  # the starting commit: only the end-to-end cases run there
    if error.name != "agent_tools.claims.claim_takeover":
        raise
    claim_takeover = None

TIER = "fast"

SLUG, ISSUE = "octo/widgets", 7
DEAD = "0d0d0d0d-dead"
TAKER_SESSION = "0e0e0e0e-taker"
SPRINT = "0123456789abcdef"
BRANCH = "issue-7-x"
WT = "/srv/repo/.worktrees/issue-7-x"
ORIGIN = ["remote", "get-url", "origin"]
LIST_WT = ["worktree", "list", "--porcelain", "-z"]
STATUS = ["-C", WT, "status", "--porcelain", "-z", "--untracked-files=all"]
LISTING = ("worktree /srv/repo\0HEAD " + "a" * 40 + "\0branch refs/heads/main\0\0worktree " + WT
           + "\0HEAD " + "b" * 40 + "\0branch refs/heads/issue-7-x\0\0")
ORIGIN_URL = "git@github.com:octo/widgets.git\n"
GOOD = {"pid": 2165, "sessionId": DEAD, "cwd": "/x", "procStart": "976", "pidDomain": PROC_PID_DOMAIN}
CALLER = {"pid": 2164, "sessionId": TAKER_SESSION, "cwd": "/x", "procStart": "976",
          "pidDomain": PROC_PID_DOMAIN}
STATUS_OUT = " M a.py\0?? new.txt\0R  moved.py\0old.py\0"


def denied(target):
    """A PermissionError for `target`, as an unreadable path raises it."""
    return PermissionError(13, "Permission denied", str(target))


def running(proc, pid):
    """Make `pid` run in the fake procfs `proc` with the start time 976, as `fake_proc` makes pid 2164 run."""
    stat = Path(proc) / str(pid) / "stat"
    stat.parent.mkdir(parents=True, exist_ok=True)
    stat.write_text(f"{pid} (a) S " + " ".join(["0"] * 18) + " 976 0 0\n")


class ReadingTest(unittest.TestCase):
    def setUp(self):
        self.ct = claim_takeover
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        self.tmp = Path(tmpdir.name)
        procfs = fake_proc(self.tmp)
        for name, value in (("PROC", procfs["proc"]), ("MACHINE_ID", procfs["machine_id"])):
            patch = mock.patch.object(self.ct, name, value)
            patch.start()
            self.addCleanup(patch.stop)
        self.proc = procfs["proc"]
        running(self.proc, 2166)
        self.registry = self.tmp / "sessions"
        self.registry.mkdir()
        self.dirs_patch = mock.patch.object(self.ct, "registry_dirs", lambda: [self.registry])
        self.dirs_patch.start()
        self.addCleanup(self.dirs_patch.stop)
        self.record(**CALLER)

    def record(self, name=None, **fields):
        (self.registry / f"{name or fields['pid']}.json").write_text(json.dumps(fields))

    def raw(self, name, text):
        (self.registry / f"{name}.json").write_text(text)

    def reading(self):
        return self.ct.session_reading(DEAD, TAKER_SESSION)

    def empty(self):
        for path in self.registry.glob("*.json"):
            path.unlink()

    def fresh(self):
        """An emptied registry holding the caller's running record again."""
        self.empty()
        self.record(**CALLER)

    def test_a_session_missing_from_a_fully_read_registry_reads_gone(self):
        self.record(**{**GOOD, "pid": 2166})
        (self.registry / "2166.json").unlink()

        result = self.reading()

        self.assertEqual(result, self.ct.GONE)

    def test_a_recorded_session_whose_process_is_absent_reads_gone(self):
        self.record(**GOOD)

        self.assertEqual(self.reading(), self.ct.GONE)

    def test_a_running_session_reads_running(self):
        self.record(**{**GOOD, "pid": 2166})
        self.assertEqual(self.reading(), self.ct.RUNNING)
        with self.subTest("an integer start time"):
            self.record(**{**GOOD, "pid": 2166, "procStart": 976})
            self.assertEqual(self.reading(), self.ct.RUNNING)

    def test_a_well_formed_start_time_mismatch_reads_gone(self):
        self.record(**{**GOOD, "pid": 2166, "procStart": "975"})

        self.assertEqual(self.reading(), self.ct.GONE)

    def test_a_registry_that_does_not_show_its_caller_running_is_unreadable(self):
        self.empty()
        with self.subTest("empty registry"):
            self.assertEqual(self.reading(), self.ct.UNREADABLE)
        with self.subTest("no registry directory"):
            with mock.patch.object(self.ct, "registry_dirs", lambda: [self.tmp / "missing"]):
                self.assertEqual(self.reading(), self.ct.UNREADABLE)
        with self.subTest("only the holder"):
            self.record(**GOOD)
            self.assertEqual(self.reading(), self.ct.UNREADABLE)
        with self.subTest("the caller's process is absent"):
            self.empty()
            self.record(**{**CALLER, "pid": 2165})
            self.assertEqual(self.reading(), self.ct.UNREADABLE)
        with self.subTest("the caller's record is malformed"):
            self.empty()
            self.record(**{**CALLER, "procStart": "unknown"})
            self.assertEqual(self.reading(), self.ct.UNREADABLE)

    def test_inconclusive_evidence_reads_unreadable(self):
        def without(key):
            return {k: v for k, v in GOOD.items() if k != key}

        (self.proc / "2167").mkdir()
        cases = {
            "malformed start of a running pid": ("2166", {**GOOD, "pid": 2166, "procStart": "unknown"}),
            "noncanonical start of a running pid": ("2166", {**GOOD, "pid": 2166, "procStart": "0976"}),
            "malformed start of an absent pid": ("2165", {**GOOD, "procStart": "unknown"}),
            "no start": ("2165", without("procStart")),
            "boolean start": ("2165", {**GOOD, "procStart": True}),
            "truncated stat": ("2167", {**GOOD, "pid": 2167}),
            "start field not digits": ("2167", {**GOOD, "pid": 2167}),
            "other pid domain": ("2165", {**GOOD, "pidDomain": "linux:other:pid:[1]"}),
            "no pid domain": ("2165", without("pidDomain")),
            "bad pid string": ("9", {**GOOD, "pid": "2165"}),
            "bad pid boolean": ("9", {**GOOD, "pid": True}),
            "bad pid zero": ("9", {**GOOD, "pid": 0}),
            "bad pid negative": ("9", {**GOOD, "pid": -1}),
            "no cwd": ("2165", without("cwd")),
            "cwd with NUL": ("2165", {**GOOD, "cwd": "/a\u0000b"}),
        }
        stats = {
            "truncated stat": "2167 (a) S 0 0\n",
            "start field not digits": "2167 (a) S " + " ".join(["0"] * 18) + " x 0 0\n",
        }
        for label, (name, fields) in cases.items():
            with self.subTest(label):
                self.fresh()
                if label in stats:
                    (self.proc / "2167" / "stat").write_text(stats[label])
                self.record(name, **fields)
                self.assertEqual(self.reading(), self.ct.UNREADABLE)
        machine_id = self.ct.MACHINE_ID
        ident = machine_id.read_text()
        with self.subTest("machine id missing"):
            self.fresh()
            self.record(**GOOD)
            machine_id.unlink()
            self.assertEqual(self.reading(), self.ct.UNREADABLE)
            machine_id.write_text(ident)
        with self.subTest("machine id empty"):
            self.fresh()
            self.record(**GOOD)
            machine_id.write_text("")
            self.assertEqual(self.reading(), self.ct.UNREADABLE)
            machine_id.write_text(ident)
        with self.subTest("a stat read that fails"):
            self.fresh()
            self.record(**GOOD)
            with mock.patch.object(self.ct.sessions, "process_matches", side_effect=OSError("io")):
                self.assertEqual(self.reading(), self.ct.UNREADABLE)
        for label, name, text in (
            ("a file that is not JSON", "9", "{"),
            ("a document that is not an object", "9", "[]"),
            ("no session id", "9", '{"pid": 9, "cwd": "/x"}'),
            ("a duplicate key", "2165",
             '{"pid": 2166, "pid": 2165, "sessionId": "' + DEAD + '", "cwd": "/x", '
             '"procStart": "976", "pidDomain": "' + PROC_PID_DOMAIN + '"}'),
            ("a non-finite literal", "2165",
             '{"pid": 2165, "sessionId": "' + DEAD + '", "cwd": "/x", "procStart": "976", '
             '"pidDomain": "' + PROC_PID_DOMAIN + '", "extra": NaN}'),
        ):
            with self.subTest(label):
                self.fresh()
                self.raw(name, text)
                self.assertEqual(self.reading(), self.ct.UNREADABLE)
        with self.subTest("a decoder recursion"):
            self.fresh()
            self.record(**GOOD)
            with mock.patch.object(self.ct.json, "loads", side_effect=RecursionError("deep")):
                self.assertEqual(self.reading(), self.ct.UNREADABLE)
        with self.subTest("two records, one running"):
            self.fresh()
            self.record(**GOOD)
            self.record(**{**GOOD, "pid": 2166})
            self.assertEqual(self.reading(), self.ct.RUNNING)

    def test_without_procfs_an_absent_pid_reads_gone(self):
        def kill(pid, sig):
            if pid == 2165:
                raise ProcessLookupError(3, "No such process")
            if pid == 2163:
                raise PermissionError(1, "Operation not permitted")

        bare = tempfile.TemporaryDirectory()
        self.addCleanup(bare.cleanup)
        caller = {key: value for key, value in CALLER.items() if key not in ("procStart", "pidDomain")}
        cases = (
            ("no holder record", [], self.ct.GONE),
            ("an absent pid", [{"pid": 2165, "sessionId": DEAD, "cwd": "/x"}], self.ct.GONE),
            ("a running pid", [{"pid": 2166, "sessionId": DEAD, "cwd": "/x"}], self.ct.RUNNING),
            ("a pid we may not signal", [{"pid": 2163, "sessionId": DEAD, "cwd": "/x"}], self.ct.RUNNING),
        )
        with mock.patch.object(self.ct, "PROC", Path(bare.name)), \
                mock.patch("os.kill", side_effect=kill):
            for label, holders, expected in cases:
                with self.subTest(label):
                    self.empty()
                    self.record(**caller)
                    for holder in holders:
                        self.record(**holder)
                    self.assertEqual(self.reading(), expected)
            with self.subTest("the caller's pid is absent"):
                self.empty()
                self.record(**{**caller, "pid": 2165})
                self.assertEqual(self.reading(), self.ct.UNREADABLE)

    def test_registry_dirs_are_the_consoles_on_a_readable_tree(self):
        self.dirs_patch.stop()
        base = self.tmp / "tree"
        home, accounts = base / "home", base / "accounts"
        for path in ("accounts/profiles/b/sessions", "accounts/profiles/a/sessions",
                     "accounts/profiles/.hidden/sessions", "accounts/profiles/c"):
            (base / path).mkdir(parents=True)
        (home / ".claude").mkdir(parents=True)
        (base / "accounts/profiles/d").mkdir()
        (base / "accounts/profiles/d/sessions").write_text("")
        (base / "accounts/profiles/e").write_text("")
        profiles = accounts / "profiles"
        expected = [home / ".claude/sessions", profiles / ".hidden/sessions", profiles / "a/sessions",
                    profiles / "b/sessions", profiles / "d/sessions"]
        env = {"HOME": str(home), "CLAUDE_ACCOUNTS_DIR": str(accounts)}
        with mock.patch.dict(os.environ, env):
            self.assertEqual(self.ct.registry_dirs(), expected)
            self.assertEqual(service.default_session_dirs(), expected)
        with self.subTest("no profiles"):
            bare = base / "bare"
            bare.mkdir()
            with mock.patch.dict(os.environ, {**env, "CLAUDE_ACCOUNTS_DIR": str(bare)}):
                self.assertEqual(self.ct.registry_dirs(), [home / ".claude/sessions"])
                self.assertEqual(service.default_session_dirs(), [home / ".claude/sessions"])
        default = home / ".claude-accounts"
        (default / "profiles/t1/sessions").mkdir(parents=True)
        both = [home / ".claude/sessions", default / "profiles/t1/sessions"]
        with self.subTest("the default root by name"):
            with mock.patch.dict(os.environ, {**env, "CLAUDE_ACCOUNTS_DIR": str(default)}):
                self.assertEqual(self.ct.registry_dirs(), both)
                self.assertEqual(service.default_session_dirs(), both)
        with self.subTest("unset"):
            with mock.patch.dict(os.environ, env):
                os.environ.pop("CLAUDE_ACCOUNTS_DIR")
                self.assertEqual(self.ct.registry_dirs(), both)
                self.assertEqual(service.default_session_dirs(), both)
        with self.subTest("a redirected root keeps the default one"):
            with mock.patch.dict(os.environ, env):
                self.assertEqual(self.ct.registry_dirs(),
                                 service.default_session_dirs() + [default / "profiles/t1/sessions"])

    def test_the_sprint_pattern_is_the_consoles(self):
        self.assertEqual(self.ct.SPRINT.pattern, sprints.SPRINT_ID.pattern)

    def test_this_host_is_the_short_hostname(self):
        for name, expected in (("eleven-m5.local", "eleven-m5"), ("anis-desktop", "anis-desktop")):
            with self.subTest(name):
                with mock.patch.object(self.ct.socket, "gethostname", return_value=name):
                    self.assertEqual(self.ct.this_host(), expected)

    def test_identity_fields_take_the_session_and_sprint_only(self):
        environ = {"CLAUDE_CODE_SESSION_ID": "54d279fd-ab94", "CONSOLE_SPRINT_ID": SPRINT,
                   "CONSOLE_SPRINT_SECRET": "s3cret"}

        result = self.ct.identity_fields(environ)

        self.assertEqual(result, {"session": "54d279fd-ab94", "sprint": SPRINT})
        self.assertEqual(list(result), ["session", "sprint"])
        self.assertNotIn("s3cret", result.values())
        with self.subTest("a session outside its pattern"):
            self.assertNotIn("session", self.ct.identity_fields({**environ, "CLAUDE_CODE_SESSION_ID": "a b"}))
        with self.subTest("a sprint outside its pattern"):
            self.assertNotIn("sprint", self.ct.identity_fields(
                {**environ, "CONSOLE_SPRINT_ID": "0123456789ABCDEF"}))
        with self.subTest("an empty environment"):
            self.assertEqual(self.ct.identity_fields({}), {})

    def test_qualifies_needs_every_condition(self):
        def claim(**fields):
            return fm.parse({"id": 5, "updated_at": "2026-11-06T10:00:00Z", "body": fm.render(
                "claim", {"issue": "7", "holder": "eleven-m5/session-dead", "branch": BRANCH, **fields},
                "Claimed.")})

        full = {"session": DEAD, "sprint": SPRINT}
        env = {"CLAUDE_CODE_SESSION_ID": TAKER_SESSION, "CONSOLE_SPRINT_ID": SPRINT}
        reading = mock.Mock(return_value=self.ct.GONE)
        with mock.patch.object(self.ct, "this_host", return_value="eleven-m5"), \
                mock.patch.object(self.ct, "session_reading", reading):
            self.assertTrue(self.ct.qualifies(claim(**full), env))
            reading.assert_called_once_with(DEAD, TAKER_SESSION)
            cases = (
                ("claim without session", claim(sprint=SPRINT), env, "eleven-m5"),
                ("claim without sprint", claim(session=DEAD), env, "eleven-m5"),
                ("other host", claim(**full), env, "anis-desktop"),
                ("taker without session", claim(**full), {"CONSOLE_SPRINT_ID": SPRINT}, "eleven-m5"),
                ("taker without sprint", claim(**full), {"CLAUDE_CODE_SESSION_ID": TAKER_SESSION},
                 "eleven-m5"),
                ("taker of another sprint", claim(**full),
                 {**env, "CONSOLE_SPRINT_ID": "fedcba9876543210"}, "eleven-m5"),
                ("same session", claim(**full), {**env, "CLAUDE_CODE_SESSION_ID": DEAD}, "eleven-m5"),
            )
            for label, marker, environ, host in cases:
                with self.subTest(label):
                    reading.reset_mock()
                    with mock.patch.object(self.ct, "this_host", return_value=host):
                        self.assertFalse(self.ct.qualifies(marker, environ))
                    reading.assert_not_called()
            for other in (self.ct.RUNNING, self.ct.UNREADABLE):
                with self.subTest(f"reading {other}"):
                    reading.return_value = other
                    self.assertFalse(self.ct.qualifies(claim(**full), env))


class UnreadableRegistryTest(unittest.TestCase):
    def setUp(self):
        self.ct = claim_takeover
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        self.tmp = Path(tmpdir.name)
        procfs = fake_proc(self.tmp)
        for name, value in (("PROC", procfs["proc"]), ("MACHINE_ID", procfs["machine_id"])):
            patch = mock.patch.object(self.ct, name, value)
            patch.start()
            self.addCleanup(patch.stop)
        running(procfs["proc"], 2166)
        self.home, self.accounts = self.tmp / "home", self.tmp / "accounts"
        env = mock.patch.dict(os.environ, {"HOME": str(self.home), "CLAUDE_ACCOUNTS_DIR": str(self.accounts)})
        env.start()
        self.addCleanup(env.stop)
        self.default = self.home / ".claude" / "sessions"
        self.profile = self.accounts / "profiles" / "b" / "sessions"
        for directory in (self.default, self.profile):
            directory.mkdir(parents=True)
        (self.default / "2164.json").write_text(json.dumps(CALLER))
        (self.profile / "2166.json").write_text(json.dumps({**GOOD, "pid": 2166}))

    @contextlib.contextmanager
    def deny(self, name, target):
        if name == "read_bytes":
            real = Path.read_bytes

            def fake(path):
                if path == target:
                    raise denied(target)
                return real(path)

            patch = mock.patch.object(Path, "read_bytes", fake)
        else:
            real = getattr(os, name)

            def fake(path, *args, **kwargs):
                if isinstance(path, (str, bytes, os.PathLike)) and Path(os.fsdecode(path)) == target:
                    raise denied(target)
                return real(path, *args, **kwargs)

            patch = mock.patch(f"os.{name}", fake)
        with patch:
            yield

    def reading(self):
        return self.ct.session_reading(DEAD, TAKER_SESSION)

    def test_an_unreadable_registry_reads_unreadable(self):
        self.assertEqual(self.reading(), self.ct.RUNNING)
        profiles = self.accounts / "profiles"
        for label, name, target in (
            ("sessions directory unreadable", "scandir", self.profile),
            ("profile unreadable", "stat", self.profile),
            ("profiles unreadable", "scandir", profiles),
            ("record unreadable", "read_bytes", self.profile / "2166.json"),
            ("default directory unreadable", "scandir", self.default),
        ):
            with self.subTest(label), self.deny(name, target):
                self.assertEqual(self.reading(), self.ct.UNREADABLE)

    def test_a_malformed_registry_reads_unreadable(self):
        (self.profile / "2166.json").unlink()
        self.assertEqual(self.reading(), self.ct.GONE)
        with self.subTest("a sessions path that is a file"):
            blocker = self.accounts / "profiles" / "c" / "sessions"
            blocker.parent.mkdir()
            blocker.write_text("")
            self.addCleanup(blocker.unlink, missing_ok=True)
            self.assertEqual(self.reading(), self.ct.UNREADABLE)
            blocker.unlink()
        with self.subTest("a third session's malformed record"):
            third = self.profile / "2170.json"
            third.write_text('{"pid": "bad", "sessionId": "0c0c0c0c-third", "cwd": "/x"}')
            self.assertEqual(self.reading(), self.ct.UNREADABLE)
            third.unlink()
        with self.subTest("profiles is a file"):
            other = self.tmp / "accounts2"
            other.mkdir()
            (other / "profiles").write_text("")
            with mock.patch.dict(os.environ, {"CLAUDE_ACCOUNTS_DIR": str(other)}):
                self.assertEqual(self.reading(), self.ct.UNREADABLE)


class WorktreeReportTest(unittest.TestCase):
    def setUp(self):
        self.ct = claim_takeover
        self.world = ForgeWorld(self)

    def ready(self, origin=ORIGIN_URL, listing=LISTING, status=STATUS_OUT):
        for argv, out in ((ORIGIN, origin), (LIST_WT, listing), (STATUS, status)):
            if out is not None:
                self.world.respond("git", argv, stdout=out)

    def test_the_report_runs_three_read_only_git_commands(self):
        self.ready()

        result = self.ct.worktree_report(SLUG, BRANCH)

        self.assertEqual(result, (WT, ["a.py", "new.txt", "moved.py"]))
        self.assertEqual(self.world.argvs("git"), [ORIGIN, LIST_WT, STATUS])

    def test_a_clean_worktree_reports_no_paths(self):
        self.ready(status="")

        self.assertEqual(self.ct.worktree_report(SLUG, BRANCH), (WT, []))

    def test_a_worktree_of_another_repository_is_never_read(self):
        for label, origin in (("another repository", "https://github.com/octo/other.git\n"),
                              ("not on github", "git@example.com:octo/widgets.git\n"),
                              ("no origin", None)):
            with self.subTest(label):
                self.world = ForgeWorld(self)
                self.ready(origin=origin)
                self.assertEqual(self.ct.worktree_report(SLUG, BRANCH), (None, None))
                self.assertEqual(self.world.argvs("git"), [ORIGIN])
        with self.subTest("a different case"):
            self.world = ForgeWorld(self)
            self.ready(origin="git@github.com:Octo/Widgets.git\n")
            self.assertEqual(self.ct.worktree_report(SLUG, BRANCH),
                             (WT, ["a.py", "new.txt", "moved.py"]))

    def test_a_report_it_cannot_read_is_null(self):
        with self.subTest("no branch"):
            self.ready()
            self.assertEqual(self.ct.worktree_report(SLUG, None), (None, None))
            self.assertEqual(self.world.argvs("git"), [])
        for label, kwargs, expected in (
            ("no listing", {"listing": None}, (None, None)),
            ("the branch is not listed", {"listing": LISTING.replace("issue-7-x\0", "other\0")},
             (None, None)),
            ("no status", {"status": None}, (WT, None)),
            ("a malformed status entry", {"status": "X\0"}, (WT, None)),
        ):
            with self.subTest(label):
                self.world = ForgeWorld(self)
                self.ready(**kwargs)
                self.assertEqual(self.ct.worktree_report(SLUG, BRANCH), expected)

    def completed(self, argv_tail, stdout):
        return subprocess.CompletedProcess(["git", *argv_tail], 0, stdout=stdout, stderr=b"")

    def byte_outputs(self):
        return [b"git@github.com:octo/widgets.git\n",
                b"worktree /srv/re\npo\0branch refs/heads/issue-7-x\0\0",
                b"?? caf\xe9.txt\0?? caf\\xe9.txt\0 M a\nb.txt\0"]

    def test_paths_are_read_as_bytes(self):
        outputs = [self.completed([], out) for out in self.byte_outputs()]

        with mock.patch.object(self.ct.subprocess, "run", side_effect=outputs) as run:
            result = self.ct.worktree_report(SLUG, BRANCH)

        self.assertEqual(result, ("/srv/re\npo", [os.fsdecode(b"caf\xe9.txt"), "caf\\xe9.txt", "a\nb.txt"]))
        self.assertNotEqual(result[1][0], result[1][1])
        self.assertEqual(os.fsencode(result[1][0]), b"caf\xe9.txt")
        argv = run.call_args_list[2].args[0]
        self.assertEqual(argv[:2] + argv[3:], ["git", "-C", *STATUS[2:]])
        self.assertEqual(os.fsdecode(argv[2]), "/srv/re\npo")
        for call in run.call_args_list:
            self.assertNotIn("text", call.kwargs)
            self.assertNotIn("encoding", call.kwargs)

    def test_git_runs_without_repository_selectors(self):
        self.assertEqual(self.ct.REPOSITORY_ENV, issue_setup.REPOSITORY_ENV)
        outputs = [self.completed([], out) for out in self.byte_outputs()]
        selectors = {"GIT_DIR": "/elsewhere/.git", "GIT_INDEX_FILE": "/tmp/other-index",
                     "GIT_WORK_TREE": "/elsewhere", "GIT_OPTIONAL_LOCKS": "1"}

        with mock.patch.dict(os.environ, selectors), \
                mock.patch.object(self.ct.subprocess, "run", side_effect=outputs) as run:
            self.ct.worktree_report(SLUG, BRANCH)

        calls = run.call_args_list
        self.assertEqual([call.args[0][1:] for call in calls][:2], [ORIGIN, LIST_WT])
        self.assertEqual(calls[2].args[0][1], "-C")
        self.assertEqual(calls[2].args[0][3:], STATUS[2:])
        for call in calls:
            env = call.kwargs["env"]
            self.assertEqual(set(env) & set(self.ct.REPOSITORY_ENV), set())
            self.assertEqual(env["GIT_OPTIONAL_LOCKS"], "0")
            self.assertEqual(env["PATH"], os.environ["PATH"])


if __name__ == "__main__":
    unittest.main()
