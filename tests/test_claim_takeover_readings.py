"""The readings behind forge-claim's early takeover that touch the registry's entries and git: an unreadable or malformed registry, and the claimed worktree's report."""
import contextlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent_tools.delivery import issue_setup

from .claim_takeover_support import (BRANCH, CALLER, DEAD, GOOD, LIST_WT, LISTING, ORIGIN, ORIGIN_URL, SLUG,
                                     STATUS, TAKER_SESSION, WT, claim_takeover, denied, running)
from .console_test_support import fake_proc
from .forge_world import ForgeWorld

TIER = "fast"

STATUS_OUT = " M a.py\0?? new.txt\0R  moved.py\0old.py\0"


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
        marked = "branch refs/heads/issue-7-x\0"
        for label, line in (("a bare prunable line", "prunable\0"),
                            ("a prunable line with its reason",
                             "prunable gitdir file points to non-existent location\0")):
            with self.subTest(label):
                self.world = ForgeWorld(self)
                self.ready(listing=LISTING.replace(marked, marked + line))
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


if __name__ == "__main__":
    unittest.main()
