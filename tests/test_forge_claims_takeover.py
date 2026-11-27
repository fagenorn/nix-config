"""forge-claim's early takeover of a claim whose holding session provably no longer runs on this host."""
import contextlib
import io
import json
import os
import shutil
import socket
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent_tools.claims import forge_claim
from agent_tools.claims import forge_markers as fm
from agent_tools.console import service, sessions, sprints
from agent_tools.delivery import issue_setup
from agent_tools.system import forge_api
from agent_tools.system.forge_api import ForgeError

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

LIST = ["api", "--paginate", "--slurp", f"repos/{SLUG}/issues/{ISSUE}/comments?per_page=100"]
ENSURE = ["api", "-X", "POST", f"repos/{SLUG}/labels", "-f", "name=in-progress", "-f", "color=FBCA04"]
ADD = ["api", "-X", "POST", f"repos/{SLUG}/issues/{ISSUE}/labels", "-f", "labels[]=in-progress"]
REMOVE = ["api", "-X", "DELETE", f"repos/{SLUG}/issues/{ISSUE}/labels/in-progress"]
OA_ENSURE = ["api", "-X", "POST", f"repos/{SLUG}/labels", "-f", "name=owner-action", "-f", "color=D93F0B"]
OA_ADD = ["api", "-X", "POST", f"repos/{SLUG}/issues/{ISSUE}/labels", "-f", "labels[]=owner-action"]
OA_REMOVE = ["api", "-X", "DELETE", f"repos/{SLUG}/issues/{ISSUE}/labels/owner-action"]
T0 = "2026-11-06T10:00:00Z"
OLD = "2026-11-01T00:00:00Z"
NOW = ["api", "--include", "rate_limit"]
NOW_REPLY = "HTTP/2.0 200 OK\nDate: Fri, 06 Nov 2026 10:00:00 GMT\n\n{}"
PUSH = ["api", f"repos/{SLUG}/activity?ref=refs/heads/{BRANCH}&activity_type=push&per_page=1"]
PRS = ["api", f"repos/{SLUG}/pulls?state=all&head=octo:{BRANCH}&per_page=100"]
HOST = socket.gethostname().split(".", 1)[0]
DEAD_HOLDER = f"{HOST}/session-dead"
TAKER = f"{HOST}/session-taker"


def claim_body(holder, **extra):
    return fm.render("claim", {"issue": str(ISSUE), "holder": holder, **extra}, f"Claimed by {holder}.")


def oa_body(claim_id, holder, ticked=False):
    return fm.render("owner-action", {"issue": str(ISSUE), "reason": "stale-claim", "claim": str(claim_id)},
                     f"The claim of {holder} has had no renewal, push or pull request activity for 24 hours.",
                     f"- [{'x' if ticked else ' '}] Release this claim")


def comment(cid, body, updated_at=T0):
    return {"id": cid, "body": body, "updated_at": updated_at, "created_at": updated_at}


def post(body):
    return ["api", "-X", "POST", f"repos/{SLUG}/issues/{ISSUE}/comments", "-f", f"body={body}"]


def patch(cid, body):
    return ["api", "-X", "PATCH", f"repos/{SLUG}/issues/comments/{cid}", "-f", f"body={body}"]


def common(command, holder):
    return [command, "--repo", SLUG, "--issue", str(ISSUE), "--holder", holder]


def run(*argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = forge_claim.main(list(argv))
    return code, json.loads(out.getvalue())


def interleave(test, after_listing, action):
    """Run `action` once, right after the `after_listing`-th listing of the module under test returns."""
    real, seen = fm.list_markers, [0]

    def listing(*args, **kwargs):
        result = real(*args, **kwargs)
        seen[0] += 1
        if seen[0] == after_listing:
            action()
        return result
    patcher = mock.patch.object(fm, "list_markers", listing)
    patcher.start()
    test.addCleanup(patcher.stop)


PD = {"pid": "2165", "pstart": "976"}  # the dead holder's process, as its claim records it
PT = {"pid": "2164", "pstart": "976"}  # the taker's running process
DEAD_CLAIM = claim_body(DEAD_HOLDER, branch=BRANCH, session=DEAD, sprint=SPRINT, **PD)
TAKEOVER = {"claim": 5, "holder": DEAD_HOLDER, "branch": BRANCH, "worktree": WT,
            "uncommitted": ["a.py", "new.txt"]}


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

    def reading(self, pid=2165, start="976"):
        return self.ct.session_reading(DEAD, TAKER_SESSION, pid, start)

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

    def test_a_session_whose_id_changed_in_place_is_judged_by_its_recorded_process(self):
        # Claude Code rewrites a running session's record with the new id: no record names the old one.
        self.record(**{**GOOD, "pid": 2166, "sessionId": "0b0b0b0b-renamed"})

        with self.subTest("the recorded process still runs"):
            self.assertEqual(self.reading(pid=2166), self.ct.RUNNING)
        with self.subTest("the recorded process is gone"):
            self.assertEqual(self.reading(pid=2165), self.ct.GONE)
        with self.subTest("the recorded start time differs"):
            self.assertEqual(self.reading(pid=2166, start="975"), self.ct.GONE)
        with self.subTest("no start time on a host with /proc"):
            self.assertEqual(self.reading(pid=2165, start=None), self.ct.UNREADABLE)
        with self.subTest("a record of the session still runs"):
            self.record(**{**GOOD, "pid": 2166})
            self.assertEqual(self.reading(pid=2165), self.ct.RUNNING)

    def test_a_dangling_symlink_or_a_fifo_in_the_registry_reads_unreadable(self):
        self.record(**{**GOOD, "pid": 2166})
        with self.subTest("a dangling symlink named for the holder"):
            (self.registry / "2166.json").unlink()
            (self.registry / "2166.json").symlink_to(self.tmp / "missing.json")
            self.assertEqual(self.reading(), self.ct.UNREADABLE)
        with self.subTest("a symlink to a readable record"):
            (self.registry / "2166.json").unlink()
            self.record(name="target", **{**GOOD, "pid": 2166})
            (self.registry / "2166.json").symlink_to(self.registry / "target.json")
            self.assertEqual(self.reading(), self.ct.UNREADABLE)
        with self.subTest("a FIFO"):
            (self.registry / "2166.json").unlink()
            (self.registry / "target.json").unlink()
            os.mkfifo(self.registry / "2166.json")
            self.assertEqual(self.reading(), self.ct.UNREADABLE)

    def test_an_entry_that_vanishes_after_the_listing_is_skipped(self):
        listed = [self.registry / "2164.json", self.registry / "2170.json"]
        with mock.patch.object(self.ct, "_json_files", lambda directory: listed):
            self.assertEqual(self.reading(), self.ct.GONE)

    def test_process_fields_name_the_callers_running_process(self):
        env = {"CLAUDE_CODE_SESSION_ID": TAKER_SESSION}
        self.assertEqual(self.ct.process_fields(env), {"pid": "2164", "pstart": "976"})
        with self.subTest("an integer start time"):
            self.record(**{**CALLER, "procStart": 976})
            self.assertEqual(self.ct.process_fields(env), {"pid": "2164", "pstart": "976"})
        with self.subTest("no session"):
            self.assertEqual(self.ct.process_fields({}), {})
        with self.subTest("the process does not run"):
            self.empty()
            self.record(**{**CALLER, "pid": 2165})
            self.assertEqual(self.ct.process_fields(env), {})
        with self.subTest("two running records"):
            self.fresh()
            self.record(**{**CALLER, "pid": 2166})
            self.assertEqual(self.ct.process_fields(env), {})
        with self.subTest("an unreadable registry"):
            self.fresh()
            (self.registry / "9.json").symlink_to(self.tmp / "missing.json")
            self.assertEqual(self.ct.process_fields(env), {})
        with self.subTest("no procfs: the pid alone"):
            bare = tempfile.TemporaryDirectory()
            self.addCleanup(bare.cleanup)
            self.empty()
            dated = {"pid": 2164, "sessionId": TAKER_SESSION, "cwd": "/x", "procStart": "Fri Nov 27 16:45:09 2026",
                     "pidDomain": "darwin"}
            self.record(**dated)
            with mock.patch.object(self.ct, "PROC", Path(bare.name)), mock.patch("os.kill"):
                self.assertEqual(self.ct.process_fields(env), {"pid": "2164"})

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

        full = {"session": DEAD, "sprint": SPRINT, **PD}
        env = {"CLAUDE_CODE_SESSION_ID": TAKER_SESSION, "CONSOLE_SPRINT_ID": SPRINT}
        reading = mock.Mock(return_value=self.ct.GONE)
        with mock.patch.object(self.ct, "this_host", return_value="eleven-m5"), \
                mock.patch.object(self.ct, "session_reading", reading):
            self.assertTrue(self.ct.qualifies(claim(**full), env))
            reading.assert_called_once_with(DEAD, TAKER_SESSION, 2165, "976")
            cases = (
                ("claim without session", claim(sprint=SPRINT), env, "eleven-m5"),
                ("claim without sprint", claim(session=DEAD, **PD), env, "eleven-m5"),
                ("claim without a process", claim(session=DEAD, sprint=SPRINT), env, "eleven-m5"),
                ("claim with a malformed pid", claim(**{**full, "pid": "0"}), env, "eleven-m5"),
                ("claim with a malformed start time", claim(**{**full, "pstart": "0976"}), env, "eleven-m5"),
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
        real = getattr(os, name)

        def fake(path, *args, **kwargs):
            if isinstance(path, (str, bytes, os.PathLike)) and Path(os.fsdecode(path)) == target:
                raise denied(target)
            return real(path, *args, **kwargs)

        with mock.patch(f"os.{name}", fake):
            yield

    def reading(self):
        return self.ct.session_reading(DEAD, TAKER_SESSION, 2165, "976")

    def test_an_unreadable_registry_reads_unreadable(self):
        self.assertEqual(self.reading(), self.ct.RUNNING)
        profiles = self.accounts / "profiles"
        for label, name, target in (
            ("sessions directory unreadable", "scandir", self.profile),
            ("profile unreadable", "stat", self.profile),
            ("profiles unreadable", "scandir", profiles),
            ("record unreadable", "open", self.profile / "2166.json"),
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

    def test_a_prunable_registration_is_never_read(self):
        prunable = LISTING.replace("branch refs/heads/issue-7-x\0",
                                   "branch refs/heads/issue-7-x\0prunable gitdir file points to non-existent location\0")
        self.assertNotEqual(prunable, LISTING)
        with self.subTest("a bare prunable line"):
            self.world = ForgeWorld(self)
            self.ready(listing=LISTING.replace("branch refs/heads/issue-7-x\0", "branch refs/heads/issue-7-x\0prunable\0"))
            self.assertEqual(self.ct.worktree_report(SLUG, BRANCH), (None, None))
            self.assertEqual(self.world.argvs("git"), [ORIGIN, LIST_WT])
        with self.subTest("a prunable line with its reason"):
            self.world = ForgeWorld(self)
            self.ready(listing=prunable)
            self.assertEqual(self.ct.worktree_report(SLUG, BRANCH), (None, None))
            self.assertEqual(self.world.argvs("git"), [ORIGIN, LIST_WT])

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


class TakeoverWorld(unittest.TestCase):
    """The fake forge, the session registry and the process table every takeover test runs in."""

    def setUp(self):
        self.slept = []
        patcher = mock.patch.object(forge_claim, "sleep", self.slept.append)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.fresh_world()
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        self.tmp = Path(tmpdir.name)
        self.home = self.tmp / "home"
        self.registry = self.home / ".claude" / "sessions"
        self.registry.mkdir(parents=True)
        self.accounts = self.tmp / "accounts"
        env = mock.patch.dict(os.environ, {"HOME": str(self.home), "CLAUDE_ACCOUNTS_DIR": str(self.accounts),
                                           "CLAUDE_CODE_SESSION_ID": TAKER_SESSION,
                                           "CONSOLE_SPRINT_ID": SPRINT})
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("CONSOLE_SPRINT_SECRET", None)
        procfs = fake_proc(self.tmp)
        running(procfs["proc"], 2166)
        if claim_takeover is not None:
            for name, value in (("PROC", procfs["proc"]), ("MACHINE_ID", procfs["machine_id"])):
                proc_patch = mock.patch.object(claim_takeover, name, value)
                proc_patch.start()
                self.addCleanup(proc_patch.stop)
        self.registry_only(self.taker_record())

    def fresh_world(self):
        self.world = ForgeWorld(self)
        for argv in (ENSURE, ADD, REMOVE, OA_ENSURE, OA_ADD, OA_REMOVE):
            self.world.respond("gh", argv)

    def record(self, session, pid):
        return {"pid": pid, "sessionId": session, "cwd": "/x", "procStart": "976", "pidDomain": PROC_PID_DOMAIN}

    def taker_record(self):
        return self.record(TAKER_SESSION, 2164)

    def dead_record(self, session=DEAD):
        return self.record(session, 2165)

    def running_record(self, session=DEAD):
        return self.record(session, 2166)

    def registry_only(self, *records, junk=None):
        for path in self.registry.glob("*.json"):
            path.unlink()
        for record in records:
            (self.registry / f"{record['pid']}.json").write_text(json.dumps(record))
        if junk is not None:
            (self.registry / "junk.json").write_text(junk)

    def profile_record(self, profile, record, root=None):
        directory = (root or self.accounts) / "profiles" / profile / "sessions"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"{record['pid']}.json").write_text(json.dumps(record))

    @contextlib.contextmanager
    def deny_scandir(self, target):
        real = os.scandir

        def fake(path=".", *args, **kwargs):
            if isinstance(path, (str, bytes, os.PathLike)) and Path(os.fsdecode(path)) == target:
                raise denied(target)
            return real(path, *args, **kwargs)
        with mock.patch("os.scandir", fake):
            yield

    def store(self, *comments, next_id=40, fail_once=(), lose_reply=()):
        self.world.comment_store(SLUG, ISSUE, list(comments), next_id=next_id, fail_once=list(fail_once),
                                 lose_reply=list(lose_reply))

    def git_ready(self, origin=ORIGIN_URL, listing=LISTING, status=" M a.py\0?? new.txt\0"):
        for argv, out in ((ORIGIN, origin), (LIST_WT, listing), (STATUS, status)):
            if out is not None:
                self.world.respond("git", argv, stdout=out)

    def status_ready(self):
        self.world.respond("gh", NOW, stdout=NOW_REPLY)
        self.world.respond_json("gh", PUSH, [])
        self.world.respond_json("gh", PRS, [])

    def rewrite(self, cid, body):
        path = self.world.state / "store.json"
        store = json.loads(path.read_text("utf-8"))
        for stored in store["comments"]:
            if stored["id"] == cid:
                stored["body"] = body
        path.write_text(json.dumps(store), encoding="utf-8")

    def mutations(self):
        return [argv for argv in self.world.argvs("gh") if "-X" in argv]

    def live(self, kind="claim"):
        markers = [m for m in (fm.parse(c) for c in self.world.stored()) if m]
        return [m for m in markers if m.kind == kind and fm.is_live(m, markers)]


class TakeoverAcquireTest(TakeoverWorld):
    def takeover_world(self, claim=DEAD_CLAIM, updated_at=T0):
        self.git_ready()
        self.store(comment(5, claim, updated_at))
        self.registry_only(self.taker_record(), self.running_record())
        (self.registry / "2166.json").unlink()

    def acquire(self, *extra):
        return run(*common("acquire", TAKER), "--branch", BRANCH, *extra)

    def test_a_gone_same_host_holder_of_the_same_sprint_is_taken_over_at_once(self):
        self.takeover_world()

        code, out = self.acquire()

        self.assertEqual((code, out["verdict"], out["comment_id"], out["by"]), (0, "acquired", 41, None))
        self.assertEqual(out["takeover"], TAKEOVER)
        self.assertEqual(self.mutations(), [
            post(fm.end_body(5, "holder-gone", successor=TAKER_SESSION, sprint=SPRINT)),
            patch(5, claim_body(DEAD_HOLDER, branch=BRANCH, session=DEAD, sprint=SPRINT, **PD, released="holder-gone")),
            post(claim_body(TAKER, branch=BRANCH, session=TAKER_SESSION, sprint=SPRINT, **PT, took="5")),
            ENSURE, ADD])
        self.assertEqual([m.fields["holder"] for m in self.live()], [TAKER])

    def test_a_holder_whose_record_names_a_dead_process_is_taken_over_too(self):
        self.takeover_world()
        self.registry_only(self.taker_record(), self.dead_record())

        code, out = self.acquire()

        self.assertEqual((code, out["verdict"], out["comment_id"], out["by"]), (0, "acquired", 41, None))
        self.assertEqual(out["takeover"], TAKEOVER)
        self.assertEqual(self.mutations()[0],
                         post(fm.end_body(5, "holder-gone", successor=TAKER_SESSION, sprint=SPRINT)))
        self.assertEqual(len(self.mutations()), 5)

    def test_every_other_case_keeps_the_day_and_the_owner_box(self):
        def claim(**changes):
            fields = {"branch": BRANCH, "session": DEAD, "sprint": SPRINT, **PD, **changes}
            return claim_body(DEAD_HOLDER, **{k: v for k, v in fields.items() if v is not None})

        def without_taker_session():
            os.environ.pop("CLAUDE_CODE_SESSION_ID")

        def without_taker_sprint():
            os.environ.pop("CONSOLE_SPRINT_ID")

        def another_sprint():
            os.environ["CONSOLE_SPRINT_ID"] = "fedcba9876543210"

        def redirected():
            empty = self.tmp / "empty-accounts"
            empty.mkdir()
            os.environ["CLAUDE_ACCOUNTS_DIR"] = str(empty)
            self.profile_record("t1", self.running_record(), root=self.home / ".claude-accounts")

        blocked = self.accounts / "profiles" / "b" / "sessions"
        cases = [
            ("other host", f"not-{HOST}/session-dead",
             claim_body(f"not-{HOST}/session-dead", branch=BRANCH, session=DEAD, sprint=SPRINT),
             lambda: None, None),
            ("liveness unreadable", DEAD_HOLDER, claim(),
             lambda: self.registry_only(self.taker_record(), junk="{"), None),
            ("malformed record", DEAD_HOLDER, claim(),
             lambda: self.registry_only(self.taker_record(), {**self.dead_record(), "pid": "x"}), None),
            ("holder still runs", DEAD_HOLDER, claim(),
             lambda: self.registry_only(self.taker_record(), self.running_record()), None),
            ("holder runs in a dot-prefixed profile", DEAD_HOLDER, claim(),
             lambda: self.profile_record(".hidden", self.running_record()), None),
            ("the holder's profile cannot be read", DEAD_HOLDER, claim(),
             lambda: self.profile_record("b", self.running_record()), blocked),
            ("accounts root redirected", DEAD_HOLDER, claim(), redirected, None),
            ("caller not in the registry", DEAD_HOLDER, claim(),
             lambda: self.registry_only(self.dead_record()), None),
            ("caller's record not running", DEAD_HOLDER, claim(),
             lambda: self.registry_only(self.dead_record(TAKER_SESSION)), None),
            ("claim records no process", DEAD_HOLDER, claim(pid=None, pstart=None), lambda: None, None),
            ("holder's process runs under a new session id", DEAD_HOLDER, claim(pid="2166"),
             lambda: self.registry_only(self.taker_record(), self.running_record("0b0b0b0b-renamed")), None),
            ("claim has no session", DEAD_HOLDER, claim(session=None), lambda: None, None),
            ("claim has no sprint", DEAD_HOLDER, claim(sprint=None), lambda: None, None),
            ("taker has no session", DEAD_HOLDER, claim(), without_taker_session, None),
            ("taker has no sprint", DEAD_HOLDER, claim(), without_taker_sprint, None),
            ("taker of another sprint", DEAD_HOLDER, claim(), another_sprint, None),
        ]
        for label, holder, body, prepare, deny in cases:
            with self.subTest(label), mock.patch.dict(os.environ):
                self.fresh_world()
                self.git_ready()
                self.status_ready()
                self.registry_only(self.taker_record())
                shutil.rmtree(self.accounts, ignore_errors=True)
                shutil.rmtree(self.home / ".claude-accounts", ignore_errors=True)
                prepare()
                self.store(comment(5, body, OLD), comment(30, oa_body(5, holder)))
                with self.deny_scandir(deny) if deny is not None else contextlib.nullcontext():
                    code, out = run(*common("acquire", TAKER), "--branch", BRANCH)
                    self.assertEqual((code, out["verdict"], out["by"], out["takeover"]),
                                     (3, "held_by", holder, None))
                    self.assertEqual(self.mutations(), [])
                    code, out = run(*common("status", TAKER))
                    self.assertEqual((code, out["verdict"], out["comment_id"], out["owner_action_comment_id"],
                                      out["owner_action_posted"]), (0, "stale", 5, 30, False))
                self.assertEqual(self.world.argvs("git"), [])

    def test_a_registry_entry_that_cannot_be_read_whole_keeps_the_day_and_the_owner_box(self):
        for label, make in (("a dangling symlink named for the holder's session",
                             lambda path: path.symlink_to(self.tmp / "missing.json")),
                            ("a FIFO", os.mkfifo)):
            with self.subTest(label):
                self.fresh_world()
                self.git_ready()
                self.store(comment(5, DEAD_CLAIM, T0))
                self.registry_only(self.taker_record())
                make(self.registry / "2165.json")

                code, out = self.acquire()

                self.assertEqual((code, out["verdict"], out["by"], out["takeover"]),
                                 (3, "held_by", DEAD_HOLDER, None))
                self.assertEqual(self.mutations(), [])

    def test_a_prunable_registration_is_not_reported_as_the_claimed_worktree(self):
        self.takeover_world()
        self.git_ready(listing=LISTING.replace("branch refs/heads/issue-7-x\0",
                                               "branch refs/heads/issue-7-x\0prunable gitdir file is gone\0"))

        code, out = self.acquire()

        self.assertEqual((code, out["verdict"]), (0, "acquired"))
        self.assertIsNone(out["takeover"]["worktree"])
        self.assertIsNone(out["takeover"]["uncommitted"])
        self.assertEqual(self.world.argvs("git"), [ORIGIN, LIST_WT])

    def test_acquire_records_the_callers_own_process(self):
        self.store(next_id=11)

        run(*common("acquire", TAKER))

        self.assertEqual(self.mutations()[0],
                         post(claim_body(TAKER, session=TAKER_SESSION, sprint=SPRINT, pid="2164", pstart="976")))
        with self.subTest("no running record names the session"):
            self.fresh_world()
            self.store(next_id=11)
            self.registry_only()

            run(*common("acquire", TAKER))

            self.assertEqual(self.mutations()[0], post(claim_body(TAKER, session=TAKER_SESSION, sprint=SPRINT)))

    def test_a_losing_replacement_claim_reports_the_takeover_only_for_its_own_winner(self):
        batch = f"{HOST}/{HOST}-20261127-1310"
        theirs = claim_body(batch, branch=BRANCH, session="0f0f0f0f-other", sprint=SPRINT, pid="2166",
                            pstart="976")
        ours = claim_body(batch, branch=BRANCH, session=TAKER_SESSION, sprint=SPRINT, **PT, took="5")
        for label, winning, report in (("another session of the holder wins", theirs, None),
                                       ("a claim of the caller's takeover wins", ours, TAKEOVER)):
            with self.subTest(label):
                self.fresh_world()
                self.takeover_world()
                interleave(self, 3, lambda: self.world.append_comment(comment(39, winning)))

                code, out = run(*common("acquire", batch), "--branch", BRANCH)

                self.assertEqual((code, out["verdict"], out["comment_id"]), (0, "already_held", 39))
                self.assertEqual(out["takeover"], report)

    def test_uncommitted_edits_are_reported_never_discarded(self):
        self.takeover_world()
        self.git_ready(status=" M a.py\0?? new.txt\0R  moved.py\0old.py\0")

        code, out = self.acquire()

        self.assertEqual(out["takeover"]["uncommitted"], ["a.py", "new.txt", "moved.py"])
        self.assertEqual(self.world.argvs("git"), [ORIGIN, LIST_WT, STATUS])
        calls = self.world.calls()
        last_git = max(i for i, call in enumerate(calls) if call["tool"] == "git")
        end = post(fm.end_body(5, "holder-gone", successor=TAKER_SESSION, sprint=SPRINT))
        ended = next(i for i, call in enumerate(calls) if call["tool"] == "gh" and call["argv"] == end)
        self.assertLess(last_git, ended)

    def test_a_takeover_whose_worktree_cannot_be_found_still_takes_over(self):
        self.takeover_world()
        self.git_ready(listing="worktree /srv/repo\0branch refs/heads/main\0\0", status=None)

        code, out = self.acquire()

        self.assertEqual((code, out["verdict"]), (0, "acquired"))
        self.assertIsNone(out["takeover"]["worktree"])
        self.assertIsNone(out["takeover"]["uncommitted"])
        self.assertEqual(self.world.argvs("git"), [ORIGIN, LIST_WT])

    def test_a_worktree_of_another_repository_is_not_reported(self):
        self.takeover_world()
        self.git_ready(origin="git@github.com:octo/other.git\n")

        code, out = self.acquire()

        self.assertEqual((code, out["verdict"]), (0, "acquired"))
        self.assertIsNone(out["takeover"]["worktree"])
        self.assertIsNone(out["takeover"]["uncommitted"])
        self.assertEqual(self.world.argvs("git"), [ORIGIN])

    def test_a_stale_gone_holder_is_taken_over_and_its_owner_prompt_retired(self):
        self.git_ready()
        self.store(comment(5, DEAD_CLAIM, OLD), comment(30, oa_body(5, DEAD_HOLDER)))

        code, out = self.acquire()

        self.assertEqual((code, out["verdict"], out["comment_id"]), (0, "acquired", 42))
        self.assertEqual(self.mutations(), [
            post(fm.end_body(5, "holder-gone", successor=TAKER_SESSION, sprint=SPRINT)),
            patch(5, claim_body(DEAD_HOLDER, branch=BRANCH, session=DEAD, sprint=SPRINT, **PD, released="holder-gone")),
            post(fm.end_body(30, "released")), OA_REMOVE,
            post(claim_body(TAKER, branch=BRANCH, session=TAKER_SESSION, sprint=SPRINT, **PT, took="5")),
            ENSURE, ADD])

    def test_a_claim_released_before_the_fresh_listing_is_not_ended_again(self):
        self.takeover_world()
        interleave(self, 1, lambda: self.world.append_comment(comment(39, fm.end_body(5, "done"))))

        code, out = self.acquire()

        self.assertEqual((code, out["verdict"], out["comment_id"]), (0, "acquired", 40))
        self.assertIsNone(out["takeover"])
        self.assertEqual(self.mutations(), [
            post(claim_body(TAKER, branch=BRANCH, session=TAKER_SESSION, sprint=SPRINT, **PT)), ENSURE, ADD])

    def test_a_fresh_claim_that_changed_is_not_ended(self):
        cases = {
            "renewed in place": (lambda: None, claim_body(DEAD_HOLDER, branch=BRANCH, session=DEAD,
                                                          sprint=SPRINT, renewed="1")),
            "another session": (lambda: self.registry_only(self.taker_record(),
                                                           self.running_record("0f0f0f0f-live")),
                                claim_body(DEAD_HOLDER, branch=BRANCH, session="0f0f0f0f-live", sprint=SPRINT)),
        }
        for label, (prepare, body) in cases.items():
            with self.subTest(label):
                self.fresh_world()
                self.takeover_world()
                prepare()
                interleave(self, 1, lambda: self.rewrite(5, body))

                code, out = self.acquire()

                self.assertEqual((code, out["verdict"], out["by"]), (3, "held_by", DEAD_HOLDER))
                self.assertIsNone(out["takeover"])
                self.assertEqual(self.mutations(), [])

    def test_the_registry_is_read_again_after_the_fresh_listing(self):
        self.takeover_world()
        interleave(self, 2, lambda: self.registry_only(self.taker_record(), self.running_record()))

        code, out = self.acquire()

        self.assertEqual((code, out["verdict"], out["by"]), (3, "held_by", DEAD_HOLDER))
        self.assertIsNone(out["takeover"])
        self.assertEqual(self.mutations(), [])

    def test_a_takeover_without_a_branch_records_the_former_branch(self):
        self.takeover_world()

        code, out = run(*common("acquire", TAKER))

        self.assertEqual((code, out["verdict"]), (0, "acquired"))
        self.assertEqual(self.mutations()[2],
                         post(claim_body(TAKER, branch=BRANCH, session=TAKER_SESSION, sprint=SPRINT, **PT, took="5")))

    def test_acquire_records_the_session_and_sprint_of_its_environment(self):
        self.store(next_id=11)
        os.environ["CONSOLE_SPRINT_SECRET"] = "s3cret"

        code, out = run(*common("acquire", TAKER))

        self.assertEqual(self.mutations(),
                         [post(claim_body(TAKER, session=TAKER_SESSION, sprint=SPRINT, **PT)), ENSURE, ADD])
        self.assertIsNone(out["takeover"])
        self.assertFalse(any("s3cret" in part for argv in self.mutations() for part in argv))
        with self.subTest("values outside their form"), mock.patch.dict(os.environ):
            self.fresh_world()
            self.store(next_id=11)
            os.environ["CLAUDE_CODE_SESSION_ID"] = "a b"
            os.environ["CONSOLE_SPRINT_ID"] = "0123456789ABCDEF"

            run(*common("acquire", TAKER))

            self.assertEqual(self.mutations(), [post(claim_body(TAKER)), ENSURE, ADD])

    def test_renew_records_the_renewing_session_and_sprint(self):
        self.store(comment(5, claim_body(TAKER, session=DEAD, sprint=SPRINT)))

        code, out = run(*common("renew", TAKER))

        self.assertEqual((code, out["verdict"]), (0, "renewed"))
        self.assertEqual(self.mutations()[0],
                         patch(5, claim_body(TAKER, renewed="1", session=TAKER_SESSION, sprint=SPRINT, **PT)))
        self.assertNotIn("takeover", out)

    def test_a_renewal_that_cannot_name_its_session_drops_the_old_one(self):
        holder = f"{HOST}/batch-1"
        self.store(comment(5, claim_body(holder, branch=BRANCH, session=DEAD, sprint=SPRINT, **PD), T0))
        with mock.patch.dict(os.environ):
            os.environ.pop("CLAUDE_CODE_SESSION_ID")
            code, out = run(*common("renew", holder))
        self.assertEqual((code, out["verdict"]), (0, "renewed"))
        self.assertEqual(self.mutations()[0],
                         patch(5, claim_body(holder, branch=BRANCH, renewed="1", sprint=SPRINT)))
        before = len(self.mutations())
        self.git_ready()

        code, out = run(*common("acquire", TAKER), "--branch", BRANCH)

        self.assertEqual((code, out["verdict"], out["by"], out["takeover"]), (3, "held_by", holder, None))
        self.assertEqual(self.mutations()[before:], [])
        self.assertEqual(self.world.argvs("git"), [])

    def test_a_renewal_by_another_session_drops_took(self):
        holder = f"{HOST}/batch-1"
        cases = [
            ("the same session and sprint", {}, None,
             claim_body(holder, branch=BRANCH, renewed="1", session=TAKER_SESSION, sprint=SPRINT, **PT,
                        took="5", tookbranch=BRANCH)),
            ("another session", {"CLAUDE_CODE_SESSION_ID": "0f0f0f0f-next"}, None,
             claim_body(holder, branch=BRANCH, renewed="1", session="0f0f0f0f-next", sprint=SPRINT)),
            ("no session", {}, "CLAUDE_CODE_SESSION_ID",
             claim_body(holder, branch=BRANCH, renewed="1", sprint=SPRINT)),
            ("another sprint", {"CONSOLE_SPRINT_ID": "fedcba9876543210"}, None,
             claim_body(holder, branch=BRANCH, renewed="1", session=TAKER_SESSION, sprint="fedcba9876543210",
                        **PT)),
        ]
        for label, environment, popped, expected in cases:
            with self.subTest(label), mock.patch.dict(os.environ, environment):
                if popped:
                    os.environ.pop(popped)
                self.fresh_world()
                self.store(comment(5, claim_body(holder, branch=BRANCH, session=TAKER_SESSION, sprint=SPRINT,
                                                 **PD, took="5", tookbranch=BRANCH)))

                code, out = run(*common("renew", holder))

                self.assertEqual((code, out["verdict"]), (0, "renewed"))
                self.assertEqual(self.mutations()[0], patch(5, expected))

    def test_a_takeover_whose_end_is_not_the_first_is_not_finished(self):
        self.takeover_world()
        interleave(self, 2, lambda: self.world.append_comment(comment(
            39, fm.end_body(5, "holder-gone", successor="0f0f0f0f-other", sprint=SPRINT))))

        code, out = self.acquire()

        self.assertEqual((code, out["verdict"], out["comment_id"]), (0, "acquired", 41))
        self.assertIsNone(out["takeover"])
        self.assertEqual(self.mutations(), [
            post(fm.end_body(5, "holder-gone", successor=TAKER_SESSION, sprint=SPRINT)),
            post(claim_body(TAKER, branch=BRANCH, session=TAKER_SESSION, sprint=SPRINT, **PT)), ENSURE, ADD])

    def test_every_acquire_answer_carries_a_takeover_member(self):
        with self.subTest("held_by"):
            self.store(comment(5, claim_body(f"not-{HOST}/x")))
            code, out = run(*common("acquire", TAKER))
            self.assertEqual((code, out["verdict"]), (3, "held_by"))
            self.assertIn("takeover", out)
            self.assertIsNone(out["takeover"])
        with self.subTest("usage"), contextlib.redirect_stderr(io.StringIO()):
            code, out = run(*common("acquire", "no-slash"))
            self.assertEqual((code, out["error"]), (2, "usage"))
            self.assertIsNone(out["takeover"])
        with self.subTest("exhausted retries"):
            self.fresh_world()
            self.store()
            self.world.outage()
            code, out = run(*common("acquire", TAKER))
            self.assertEqual(code, 1)
            self.assertIs(out["transient"], True)
            self.assertIsNone(out["takeover"])
        with self.subTest("status and renew usage errors"), contextlib.redirect_stderr(io.StringIO()):
            for argv in (["status", "--repo", SLUG], ["renew", "--repo", SLUG]):
                code, out = run(*argv)
                self.assertNotIn("takeover", out)


class TakeoverRecoveryTest(TakeoverWorld):
    def setUp(self):
        super().setUp()
        self.END = fm.end_body(5, "holder-gone", successor=TAKER_SESSION, sprint=SPRINT)
        self.OTHER_END = fm.end_body(5, "holder-gone", successor="0f0f0f0f-other", sprint=SPRINT)
        self.RELEASED_5 = claim_body(DEAD_HOLDER, branch=BRANCH, session=DEAD, sprint=SPRINT, **PD, released="holder-gone")
        self.NEW_CLAIM = claim_body(TAKER, branch=BRANCH, session=TAKER_SESSION, sprint=SPRINT, **PT, took="5")
        self.BATCH = f"{HOST}/{HOST}-20261127-1310"
        self.PLAIN = claim_body(TAKER, branch=BRANCH, session=TAKER_SESSION, sprint=SPRINT, **PT)
        self.GONE_5 = claim_body(self.BATCH, branch=BRANCH, session=DEAD, sprint=SPRINT, **PD)
        self.HANDED = claim_body(self.BATCH, branch=BRANCH, session=TAKER_SESSION, sprint=SPRINT, **PT,
                                 took="5", tookbranch=BRANCH)
        self.HANDED_REPORT = {**TAKEOVER, "holder": self.BATCH}

    def acquire(self, holder=TAKER):
        return run(*common("acquire", holder), "--branch", BRANCH)

    def test_a_retried_takeover_still_reports_it(self):
        for name, faults in (("edit fails once", {"fail_once": ["edit"]}),
                             ("edit reply lost", {"lose_reply": ["edit"]})):
            with self.subTest(name):
                self.fresh_world()
                self.slept.clear()
                self.git_ready()
                self.store(comment(5, DEAD_CLAIM, T0), **faults)

                code, out = self.acquire()

                self.assertEqual((code, out["verdict"], out["comment_id"]), (0, "acquired", 41))
                self.assertEqual(out["takeover"], TAKEOVER)
                self.assertEqual(self.slept, [20])
                self.assertEqual(self.mutations().count(post(self.END)), 1)
                stored = {c["id"]: c["body"] for c in self.world.stored()}
                self.assertEqual(stored[5], self.RELEASED_5)
                self.assertEqual([m.fields["holder"] for m in self.live()], [TAKER])
                self.assertEqual(stored[41], self.NEW_CLAIM)
                self.assertEqual(self.world.argvs("git"), [ORIGIN, LIST_WT, STATUS])
                if name == "edit reply lost":
                    self.assertEqual(self.mutations().count(patch(5, self.RELEASED_5)), 1)

    def test_a_retry_reports_the_worktree_read_before_the_end(self):
        self.git_ready(status=" M a.py\0?? new.txt\0")
        self.store(comment(5, DEAD_CLAIM, T0), lose_reply=["edit"])
        interleave(self, 3, lambda: self.world.respond("git", STATUS, stdout="?? later.txt\0"))

        code, out = self.acquire()

        self.assertEqual((code, out["verdict"], out["comment_id"]), (0, "acquired", 41))
        self.assertEqual(self.slept, [20])
        self.assertEqual(out["takeover"]["uncommitted"], ["a.py", "new.txt"])
        self.assertEqual(self.world.argvs("git"), [ORIGIN, LIST_WT, STATUS])
        calls = self.world.calls()
        last_git = max(i for i, call in enumerate(calls) if call["tool"] == "git")
        end_post = next(i for i, call in enumerate(calls) if call["tool"] == "gh" and call["argv"] == post(self.END))
        self.assertLess(last_git, end_post)

    def test_only_the_successor_finishes_an_interrupted_takeover(self):
        expected = [patch(5, self.RELEASED_5), post(fm.end_body(30, "released")), OA_REMOVE,
                    post(self.NEW_CLAIM), ENSURE, ADD]
        for name, ends in (("the successor's end", [comment(39, self.END)]),
                           ("two ends, the caller's first", [comment(38, self.END), comment(39, self.OTHER_END)])):
            with self.subTest(name):
                self.fresh_world()
                self.git_ready()
                self.store(comment(5, DEAD_CLAIM, OLD), comment(30, oa_body(5, DEAD_HOLDER)), *ends)

                code, out = self.acquire()

                self.assertEqual((code, out["verdict"], out["comment_id"]), (0, "acquired", 41))
                self.assertEqual(out["takeover"], TAKEOVER)
                self.assertEqual(self.mutations(), expected)
        no_session_claim = claim_body(TAKER, branch=BRANCH, sprint=SPRINT)
        grants_nothing = (
            ("another successor", [comment(39, self.OTHER_END)], self.PLAIN, False),
            ("another sprint", [comment(39, fm.end_body(5, "holder-gone", successor=TAKER_SESSION,
                                                        sprint="fedcba9876543210"))], self.PLAIN, False),
            ("an ordinary release", [comment(39, fm.end_body(5, "holder-gone"))], self.PLAIN, False),
            ("two ends, another successor first", [comment(38, self.OTHER_END), comment(39, self.END)],
             self.PLAIN, False),
            ("an ordinary release first", [comment(38, fm.end_body(5, "done")), comment(39, self.END)],
             self.PLAIN, False),
            ("caller without a session", [comment(39, self.END)], no_session_claim, True))
        for name, ends, plain, without_session in grants_nothing:
            with self.subTest(name), mock.patch.dict(os.environ):
                self.fresh_world()
                self.git_ready()
                self.store(comment(5, DEAD_CLAIM, OLD), comment(30, oa_body(5, DEAD_HOLDER)), *ends)
                if without_session:
                    os.environ.pop("CLAUDE_CODE_SESSION_ID")

                code, out = self.acquire()

                self.assertEqual((code, out["verdict"], out["comment_id"]), (0, "acquired", 40))
                self.assertIsNone(out["takeover"])
                self.assertEqual(self.world.argvs("git"), [])
                self.assertEqual(self.mutations(), [post(plain), ENSURE, ADD])

    def test_an_already_held_acquire_after_a_takeover_reports_it(self):
        self.git_ready()
        self.store(comment(5, self.RELEASED_5), comment(39, self.END), comment(41, self.NEW_CLAIM), next_id=50)

        code, out = self.acquire()

        self.assertEqual((code, out["verdict"], out["comment_id"]), (0, "already_held", 41))
        self.assertEqual(out["takeover"], TAKEOVER)
        self.assertEqual(self.mutations(), [ENSURE, ADD])

    def test_an_older_takeover_is_not_reported_again(self):
        with self.subTest("a later claim was released"):
            self.git_ready()
            self.store(comment(5, self.RELEASED_5), comment(39, self.END),
                       comment(41, claim_body(TAKER, released="done")), comment(42, fm.end_body(41, "done")),
                       next_id=50)

            code, out = self.acquire()

            self.assertEqual((code, out["verdict"], out["comment_id"]), (0, "acquired", 50))
            self.assertIsNone(out["takeover"])
            self.assertEqual(self.world.argvs("git"), [])
        with self.subTest("another holder holds it now"):
            self.fresh_world()
            self.git_ready()
            self.store(comment(5, self.RELEASED_5), comment(39, self.END),
                       comment(41, claim_body("anis-desktop/batch-x")), next_id=50)

            code, out = self.acquire()

            self.assertEqual((code, out["verdict"], out["by"]), (3, "held_by", "anis-desktop/batch-x"))
            self.assertIsNone(out["takeover"])

    def handoff_world(self, *extra, **options):
        self.git_ready()
        self.store(comment(5, self.GONE_5, T0), *extra, **options)

    def test_a_new_session_of_the_same_holder_takes_over_a_gone_session(self):
        for name, records in (("the old session left no record", None),
                              ("the old session left a dead record", True)):
            with self.subTest(name):
                self.fresh_world()
                self.handoff_world()
                if records:
                    self.registry_only(self.taker_record(), self.dead_record())

                code, out = self.acquire(self.BATCH)

                self.assertEqual((code, out["verdict"], out["comment_id"]), (0, "already_held", 5))
                self.assertEqual(out["takeover"], self.HANDED_REPORT)
                self.assertEqual(self.mutations(), [patch(5, self.HANDED), ENSURE, ADD])

    def test_the_same_session_of_the_same_holder_stays_already_held(self):
        cases = (
            ("same session", claim_body(self.BATCH, branch=BRANCH, session=TAKER_SESSION, sprint=SPRINT),
             None, {}, None),
            ("old session still runs", self.GONE_5, (lambda: self.registry_only(
                self.taker_record(), self.running_record())), {}, None),
            ("caller not in the registry", self.GONE_5, self.registry_only, {}, None),
            ("after the handoff", self.HANDED, None, {}, self.HANDED_REPORT),
            ("same session, another sprint", self.HANDED, None, {"CONSOLE_SPRINT_ID": "fedcba9876543210"}, None))
        for name, claim, prepare, env, report in cases:
            with self.subTest(name), mock.patch.dict(os.environ, env):
                self.fresh_world()
                self.git_ready()
                self.store(comment(5, claim, T0))
                if prepare is not None:
                    prepare()

                code, out = self.acquire(self.BATCH)

                self.assertEqual((code, out["verdict"], out["comment_id"]), (0, "already_held", 5))
                self.assertEqual(out["takeover"], report)
                self.assertEqual(self.mutations(), [ENSURE, ADD])
                if report is None:
                    self.assertEqual(self.world.argvs("git"), [])

    def test_a_same_holder_claim_that_changed_is_not_refreshed(self):
        self.handoff_world()
        interleave(self, 1, lambda: self.rewrite(5, claim_body(self.BATCH, branch=BRANCH, session=DEAD,
                                                               sprint=SPRINT, renewed="1")))

        code, out = self.acquire(self.BATCH)

        self.assertEqual((code, out["verdict"], out["comment_id"]), (0, "already_held", 5))
        self.assertIsNone(out["takeover"])
        self.assertEqual(self.mutations(), [ENSURE, ADD])

    def test_a_handoff_follows_the_claim_that_now_holds(self):
        plain = claim_body(self.BATCH, branch=BRANCH, session=TAKER_SESSION, sprint=SPRINT, **PT)
        with self.subTest("released before the fresh listing"):
            self.handoff_world()
            interleave(self, 1, lambda: self.world.append_comment(comment(39, fm.end_body(5, "done"))))

            code, out = self.acquire(self.BATCH)

            self.assertEqual((code, out["verdict"], out["comment_id"]), (0, "acquired", 40))
            self.assertIsNone(out["takeover"])
            self.assertEqual(self.mutations(), [post(plain), ENSURE, ADD])
        with self.subTest("replaced by another holder"):
            self.fresh_world()
            self.handoff_world()

            def replace():
                self.world.append_comment(comment(38, fm.end_body(5, "done")))
                self.world.append_comment(comment(39, claim_body("anis-desktop/batch-x")))
            interleave(self, 1, replace)

            code, out = self.acquire(self.BATCH)

            self.assertEqual((code, out["verdict"], out["comment_id"], out["by"]),
                             (3, "held_by", 39, "anis-desktop/batch-x"))
            self.assertIsNone(out["takeover"])
            self.assertEqual(self.mutations(), [])
        with self.subTest("released after the edit"):
            self.fresh_world()
            self.handoff_world()
            interleave(self, 2, lambda: self.world.append_comment(comment(39, fm.end_body(5, "done"))))

            code, out = self.acquire(self.BATCH)

            self.assertEqual((code, out["verdict"], out["comment_id"]), (0, "acquired", 40))
            self.assertIsNone(out["takeover"])
            self.assertEqual(self.mutations(), [patch(5, self.HANDED), post(plain), ENSURE, ADD])

    def test_a_handoff_overwritten_by_another_session_reports_nothing(self):
        self.git_ready()
        self.store(comment(5, self.GONE_5, OLD), comment(30, oa_body(5, self.BATCH)))
        real_edit = fm.edit

        def edit(slug, comment_id, body):
            real_edit(slug, comment_id, body)
            self.rewrite(5, claim_body(self.BATCH, branch=BRANCH, session="0f0f0f0f-other", sprint=SPRINT,
                                       took="5"))
        patcher = mock.patch.object(fm, "edit", edit)
        patcher.start()
        self.addCleanup(patcher.stop)

        code, out = self.acquire(self.BATCH)

        self.assertEqual((code, out["verdict"], out["comment_id"]), (0, "already_held", 5))
        self.assertIsNone(out["takeover"])
        self.assertEqual(self.mutations(), [patch(5, self.HANDED), ENSURE, ADD])
        self.assertEqual([m.comment_id for m in self.live("owner-action")], [30])

    def test_a_handoff_retires_only_the_prompts_it_found(self):
        unrelated = fm.render("owner-action", {"issue": str(ISSUE), "reason": "conflict", "holder": self.BATCH},
                              "Resolve the conflict.")
        with self.subTest("the handoff"):
            self.fresh_world()
            self.slept.clear()
            self.git_ready()
            self.store(comment(5, self.GONE_5, OLD), comment(30, oa_body(5, self.BATCH)), comment(31, unrelated))

            code, out = self.acquire(self.BATCH)

            self.assertEqual((code, out["verdict"], out["comment_id"]), (0, "already_held", 5))
            self.assertEqual(out["takeover"], self.HANDED_REPORT)
            self.assertEqual(self.mutations(), [patch(5, self.HANDED), post(fm.end_body(30, "renewed")),
                                                ENSURE, ADD])
            self.assertEqual([m.comment_id for m in self.live("owner-action")], [31])
        with self.subTest("a retry after a failed retirement"):
            self.fresh_world()
            self.slept.clear()
            self.git_ready()
            self.store(comment(5, self.GONE_5, OLD), comment(30, oa_body(5, self.BATCH)), fail_once=["post"])
            interleave(self, 3, lambda: self.world.append_comment(comment(61, oa_body(5, self.BATCH))))

            code, out = self.acquire(self.BATCH)

            self.assertEqual((code, out["verdict"], out["comment_id"]), (0, "already_held", 5))
            self.assertEqual(out["takeover"], self.HANDED_REPORT)
            self.assertEqual(self.slept, [20])
            self.assertEqual(self.mutations().count(patch(5, self.HANDED)), 1)
            self.assertIn(post(fm.end_body(30, "renewed")), self.mutations())
            self.assertNotIn(OA_REMOVE, self.mutations())
            self.assertEqual([m.comment_id for m in self.live("owner-action")], [61])
            self.assertEqual(self.world.argvs("git"), [ORIGIN, LIST_WT, STATUS])
        with self.subTest("a retry after a failed label removal"):
            self.fresh_world()
            self.slept.clear()
            self.git_ready()
            self.store(comment(5, self.GONE_5, OLD), comment(30, oa_body(5, self.BATCH)))
            real_remove, calls = forge_api.remove_label, []

            def remove(slug, issue, name):
                calls.append(name)
                if len(calls) == 1:
                    raise ForgeError("gh_failed", "HTTP 502", transient=True)
                return real_remove(slug, issue, name)
            patcher = mock.patch.object(forge_api, "remove_label", remove)
            patcher.start()
            self.addCleanup(patcher.stop)

            code, out = self.acquire(self.BATCH)

            self.assertEqual((code, out["verdict"], out["comment_id"]), (0, "already_held", 5))
            self.assertEqual(out["takeover"], self.HANDED_REPORT)
            self.assertEqual(self.slept, [20])
            self.assertEqual(self.mutations(), [patch(5, self.HANDED), post(fm.end_body(30, "renewed")),
                                                OA_REMOVE, ENSURE, ADD])
        with self.subTest("a later call"):
            self.fresh_world()
            self.slept.clear()
            self.git_ready()
            self.store(comment(5, self.HANDED), comment(60, oa_body(5, self.BATCH)))

            code, out = self.acquire(self.BATCH)

            self.assertEqual((code, out["verdict"], out["comment_id"]), (0, "already_held", 5))
            self.assertEqual(out["takeover"], self.HANDED_REPORT)
            self.assertEqual(self.mutations(), [ENSURE, ADD])
            self.assertEqual([m.comment_id for m in self.live("owner-action")], [60])

    def test_a_handoff_then_a_renewal_by_another_session_reports_nothing(self):
        self.git_ready()
        self.store(comment(5, self.HANDED))
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ID": "0f0f0f0f-next"}):
            self.registry_only(self.taker_record(), self.record("0f0f0f0f-next", 2166))

            code, out = run(*common("renew", self.BATCH))
            self.assertEqual((code, out["verdict"]), (0, "renewed"))

            code, out = self.acquire(self.BATCH)

            self.assertEqual((code, out["verdict"], out["comment_id"]), (0, "already_held", 5))
            self.assertIsNone(out["takeover"])
            self.assertEqual(self.world.argvs("git"), [])


    def test_a_handoff_keeps_reporting_the_branch_it_found_after_a_renewal_changes_the_branch(self):
        other = "issue-7-other"
        for label, branch_at_handoff, expected in (("a branch", BRANCH, BRANCH), ("no branch", None, None)):
            with self.subTest(label):
                self.fresh_world()
                self.git_ready()
                gone = claim_body(self.BATCH, session=DEAD, sprint=SPRINT, **PD,
                                  **({"branch": branch_at_handoff} if branch_at_handoff else {}))
                self.store(comment(5, gone, T0))
                self.acquire(self.BATCH)

                code, out = run(*common("renew", self.BATCH), "--branch", other)
                self.assertEqual((code, out["verdict"]), (0, "renewed"))
                code, out = self.acquire(self.BATCH)

                self.assertEqual((code, out["verdict"], out["comment_id"]), (0, "already_held", 5))
                self.assertEqual(out["takeover"]["branch"], expected)
                self.assertEqual(out["takeover"]["worktree"], WT if expected else None)
                stored = {c["id"]: c["body"] for c in self.world.stored()}
                self.assertIn(f"branch={other}", stored[5])
                self.assertIn(f"tookbranch={expected or '-'}", stored[5])

    def test_a_handoff_restores_the_owner_label_for_a_prompt_posted_meanwhile(self):
        self.git_ready()
        self.store(comment(5, self.GONE_5, OLD), comment(30, oa_body(5, self.BATCH)))
        real_remove = forge_api.remove_label

        def remove(slug, issue, name):
            if name == "owner-action":  # a concurrent status posts and labels a new prompt
                self.world.append_comment(comment(61, oa_body(5, self.BATCH)))
            return real_remove(slug, issue, name)
        patcher = mock.patch.object(forge_api, "remove_label", remove)
        patcher.start()
        self.addCleanup(patcher.stop)

        code, out = self.acquire(self.BATCH)

        self.assertEqual((code, out["verdict"], out["comment_id"]), (0, "already_held", 5))
        self.assertEqual(self.mutations(), [patch(5, self.HANDED), post(fm.end_body(30, "renewed")), OA_REMOVE,
                                            OA_ENSURE, OA_ADD, ENSURE, ADD])
        self.assertEqual([m.comment_id for m in self.live("owner-action")], [61])


class TakeoverStatusTest(TakeoverWorld):
    def status(self):
        return run(*common("status", TAKER))

    def test_status_reports_a_takeover_eligible_claim(self):
        self.store(comment(5, DEAD_CLAIM, T0))
        self.status_ready()

        code, out = self.status()

        self.assertEqual((code, out["verdict"], out["comment_id"], out["by"]),
                         (0, "takeover-eligible", 5, DEAD_HOLDER))
        self.assertEqual((out["activity_at"], out["owner_action_comment_id"], out["owner_action_posted"]),
                         (None, None, False))
        self.assertEqual(self.mutations(), [])
        self.assertEqual(self.world.argvs("gh"), [LIST])
        self.assertNotIn("takeover", out)

    def test_a_stale_takeover_eligible_claim_posts_no_owner_prompt(self):
        obsolete = (comment(3, claim_body("x/y", released="done")), comment(29, oa_body(3, "x/y")),
                    comment(5, DEAD_CLAIM, OLD))
        cases = (("no prompt yet", (comment(5, DEAD_CLAIM, OLD),), []),
                 ("its own prompt", (comment(5, DEAD_CLAIM, OLD), comment(30, oa_body(5, DEAD_HOLDER))), []),
                 ("an obsolete prompt of an older claim", obsolete,
                  [post(fm.end_body(29, "released")), OA_REMOVE]))
        for name, comments, mutations in cases:
            with self.subTest(name):
                self.fresh_world()
                self.status_ready()
                self.store(*comments)

                code, out = self.status()

                self.assertEqual((code, out["verdict"]), (0, "takeover-eligible"))
                self.assertEqual(self.mutations(), mutations)

    def test_status_keeps_its_verdicts_when_the_claim_does_not_qualify(self):
        other_host = claim_body(f"not-{HOST}/session-dead", branch=BRANCH, session=DEAD, sprint=SPRINT)
        cases = (
            ("other host", (comment(5, other_host, OLD), comment(30, oa_body(5, "x/y"))), None, {},
             "stale", 30),
            ("taker of another sprint", (comment(5, DEAD_CLAIM, T0),), None,
             {"CONSOLE_SPRINT_ID": "fedcba9876543210"}, "held_by", None),
            ("holder still runs", (comment(5, DEAD_CLAIM, T0),),
             (self.taker_record(), self.running_record()), {}, "held_by", None),
            ("caller not in the registry", (comment(5, DEAD_CLAIM, T0),), (), {}, "held_by", None),
            ("holder's session id changed in place",
             (comment(5, claim_body(DEAD_HOLDER, branch=BRANCH, session=DEAD, sprint=SPRINT, pid="2166",
                                    pstart="976"), T0),),
             (self.taker_record(), self.running_record("0b0b0b0b-renamed")), {}, "held_by", None))
        for name, comments, records, env, verdict, prompt in cases:
            with self.subTest(name), mock.patch.dict(os.environ, env):
                self.fresh_world()
                self.status_ready()
                self.store(*comments)
                if records is not None:
                    self.registry_only(*records)

                code, out = self.status()

                self.assertEqual((code, out["verdict"], out["owner_action_comment_id"]), (0, verdict, prompt))

    def test_a_takeover_eligible_status_is_followed_by_the_takeover(self):
        self.git_ready()
        self.status_ready()
        self.store(comment(5, DEAD_CLAIM, T0))

        code, out = self.status()
        self.assertEqual((code, out["verdict"]), (0, "takeover-eligible"))

        code, out = run(*common("acquire", TAKER), "--branch", BRANCH)

        self.assertEqual((code, out["verdict"], out["comment_id"]), (0, "acquired", 41))
        self.assertEqual(out["takeover"], TAKEOVER)

    def test_the_status_verdict_is_declared_to_the_engine(self):
        declared = Path(__file__).resolve().parents[1] / "python/agent_tools/delivery/command_verdicts.json"
        self.assertEqual(json.loads(declared.read_text())["forge-claim"]["subcommands"]["status"],
                         ["free", "held_by", "stale", "takeover-eligible", "error"])


if __name__ == "__main__":
    unittest.main()
