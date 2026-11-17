"""The console's comparison of a checkout with its remote, and its fast-forward (#1233).

Run: just agent-workflow-tests
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from agent_tools.console import checkout_remote as cr
from agent_tools.console import manager
from agent_tools.project_contract import adopt_inspection

from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1052)

GIT_ENV = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}


def git(path, *arguments):
    done = subprocess.run(
        ["git", "-C", str(path), *arguments], env=GIT_ENV, check=True, text=True,
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE)
    return done.stdout.strip()


def configure(path):
    git(path, "config", "user.name", "Test")
    git(path, "config", "user.email", "test@example.invalid")
    git(path, "config", "commit.gpgsign", "false")


class CheckoutRemoteTest(unittest.TestCase):
    def setUp(self):
        self.parent = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.parent, ignore_errors=True)
        patched = mock.patch.dict(os.environ, {
            "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_ALLOW_PROTOCOL": "file"})
        patched.start()
        self.addCleanup(patched.stop)

    def pair(self, ahead, *, contract, extra=None):
        seed = self.parent / "seed"
        subprocess.run(["git", "init", "-q", "-b", "main", str(seed)], check=True, env=GIT_ENV)
        configure(seed)
        (seed / "README.md").write_text("# x\n")
        git(seed, "add", "-A")
        git(seed, "commit", "-q", "-m", "first")
        bare = self.parent / "origin.git"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True, env=GIT_ENV)
        git(seed, "remote", "add", "origin", str(bare))
        git(seed, "push", "-q", "origin", "main")
        checkout = self.parent / "checkout"
        subprocess.run(["git", "clone", "-q", str(bare), str(checkout)], check=True, env=GIT_ENV)
        configure(checkout)
        for i in range(ahead):
            (seed / f"notes-{i}.md").write_text(f"{i}\n")
            if i == ahead - 1:
                if contract:
                    (seed / ".agents").mkdir(exist_ok=True)
                    (seed / ".agents" / "project.json").write_text("{}\n")
                for name, text in (extra or {}).items():
                    (seed / name).write_text(text)
            git(seed, "add", "-A")
            git(seed, "commit", "-q", "-m", f"commit {i}")
        git(seed, "push", "-q", "origin", "main")
        return checkout.resolve(), seed

    def lone(self, *, origin=None):
        root = self.parent / "lone"
        subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True, env=GIT_ENV)
        configure(root)
        (root / "README.md").write_text("# x\n")
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "first")
        if origin:
            git(root, "remote", "add", "origin", origin)
        return root

    def stall(self, checkout):
        script = self.parent / "upload-pack"
        script.write_text(
            "#!/bin/sh\n"
            f"if [ -e {self.parent}/listed ]; then touch {self.parent}/fetching; sleep 60; fi\n"
            f"touch {self.parent}/listed\n"
            'exec git upload-pack "$@"\n')
        script.chmod(0o755)
        git(checkout, "config", "remote.origin.uploadpack", str(script))
        return self.parent / "fetching"

    def test_a_checkout_with_no_origin_is_skipped(self):
        root = self.lone()
        self.assertEqual(cr.compare(str(root)), cr.Comparison("skipped", None, 0, False, None))

    def test_an_origin_that_cannot_be_read_is_unreadable_and_keeps_gits_words(self):
        root = self.lone(origin=str(self.parent / "missing.git"))
        seen = cr.compare(str(root))
        self.assertEqual(seen[:4], ("unreadable", None, 0, False))
        self.assertEqual(seen.failure.step, "ls-remote")
        self.assertTrue(seen.failure.detail.startswith("exit "))
        self.assertIn("missing.git", seen.failure.detail)

    def test_a_current_checkout_is_current(self):
        checkout, _ = self.pair(0, contract=False)
        self.assertEqual(cr.compare(str(checkout)), cr.Comparison("current", "main", 0, False, None))

    def test_a_checkout_behind_a_remote_with_a_contract_is_behind_and_unmoved(self):
        checkout, seed = self.pair(1, contract=True)
        head = git(checkout, "rev-parse", "HEAD")
        self.assertEqual(cr.compare(str(checkout)), cr.Comparison("behind", "main", 1, True, None))
        self.assertEqual(git(checkout, "rev-parse", "HEAD"), head)
        self.assertFalse((checkout / ".agents" / "project.json").exists())
        self.assertEqual(git(checkout, "rev-parse", "refs/remotes/origin/main"), git(seed, "rev-parse", "HEAD"))

    def test_every_commit_the_remote_has_is_counted_and_no_contract_is_said(self):
        checkout, _ = self.pair(3, contract=False)
        self.assertEqual(cr.compare(str(checkout)), cr.Comparison("behind", "main", 3, False, None))

    def test_a_configured_fetch_mapping_writes_no_other_ref(self):
        checkout, _ = self.pair(1, contract=True)
        git(checkout, "config", "--add", "remote.origin.fetch", "+refs/heads/main:refs/heads/mirror")
        refs = ("for-each-ref", "--format=%(refname) %(objectname)", "refs/heads", "refs/tags")
        before = git(checkout, *refs)
        self.assertEqual(cr.compare(str(checkout)).state, "behind")
        self.assertEqual(git(checkout, *refs), before)
        self.assertFalse((checkout / ".git" / "FETCH_HEAD").exists())

    def test_the_listing_and_the_fetch_are_adopt_inspections(self):
        checkout, _ = self.pair(1, contract=True)
        argvs = []

        real = manager.run_in_own_group

        def record(argv, **kwargs):
            argvs.append(argv)
            return real(argv, **kwargs)

        with mock.patch.object(cr.manager, "run_in_own_group", side_effect=record):
            cr.compare(str(checkout))
        self.assertTrue(any(tuple(a[-len(adopt_inspection.REMOTE_HEADS_ARGS):]) == adopt_inspection.REMOTE_HEADS_ARGS
                            for a in argvs))
        fetch = adopt_inspection.fetch_pinned_args("main")
        self.assertTrue(any(tuple(a[-len(fetch):]) == fetch for a in argvs))
        for argv in argvs:
            self.assertEqual(argv[:5], ["git", "-c", "core.hooksPath=/dev/null", "-C", str(checkout)])
        for flag in ("--refmap=", "--no-auto-maintenance", "--no-recurse-submodules",
                     "--no-tags", "--no-write-fetch-head"):
            self.assertIn(flag, fetch)

    def test_remote_heads_parses_its_listing(self):
        heads = adopt_inspection.parse_remote_heads(
            b"ref: refs/heads/main\tHEAD\n" + b"a" * 40 + b"\tHEAD\n" + b"a" * 40 + b"\trefs/heads/main\n")
        self.assertEqual(heads.default, "main")
        self.assertEqual(dict(heads.listed), {"main": "a" * 40})
        unlisted = adopt_inspection.parse_remote_heads(
            b"ref: refs/heads/gone\tHEAD\n" + b"a" * 40 + b"\trefs/heads/main\n")
        self.assertIsNone(unlisted.default)

    def test_safe_branch_takes_only_a_safe_name(self):
        for name in ("main", "feature/one", "release-1.2"):
            self.assertTrue(cr.safe_branch(name), name)
        for name in (None, "", "x:y", "-x", "a..b", "a.lock", "a/", "a//b", "a.", "a b"):
            self.assertFalse(cr.safe_branch(name), name)

    def test_an_unsafe_default_branch_is_skipped_and_fetches_nothing(self):
        checkout, _ = self.pair(1, contract=True)
        before = git(checkout, "for-each-ref", "refs/remotes")
        heads = adopt_inspection.RemoteHeads("x:y", frozenset({"x:y"}), {})
        with mock.patch.object(cr.adopt_inspection, "parse_remote_heads", return_value=heads):
            seen = cr.compare(str(checkout))
        self.assertEqual(seen.state, "skipped")
        self.assertEqual(git(checkout, "for-each-ref", "refs/remotes"), before)

    def test_a_fetch_that_runs_past_its_bound_is_unreadable_and_says_so(self):
        checkout, _ = self.pair(1, contract=True)
        self.stall(checkout)
        started = time.monotonic()
        with mock.patch.object(cr, "FETCH_TIMEOUT", 3):
            seen = cr.compare(str(checkout))
        elapsed = time.monotonic() - started
        self.assertEqual(seen.state, "unreadable")
        self.assertEqual(seen.failure, cr.Failure("fetch", "timed out after 3 s"))
        self.assertLess(elapsed, 30)

    def test_a_cancel_during_the_fetch_ends_it_and_nothing_moves(self):
        checkout, _ = self.pair(1, contract=True)
        fetching = self.stall(checkout)
        head = git(checkout, "rev-parse", "HEAD")

        class StopWhenFetching:
            def is_set(self):
                return fetching.exists()

        started = time.monotonic()
        done = cr.update(str(checkout), cancel=StopWhenFetching())
        elapsed = time.monotonic() - started
        self.assertEqual(done, cr.Updated(cr.UNREAD_REASON, cr.Failure("fetch", "cancelled")))
        self.assertEqual(git(checkout, "rev-parse", "HEAD"), head)
        self.assertFalse((checkout / "notes-0.md").exists())
        self.assertLess(elapsed, 30)
        stopped = threading.Event()
        stopped.set()
        seen = cr.compare(str(checkout), cancel=stopped)
        self.assertEqual(seen.state, "unreadable")
        self.assertEqual(seen.failure, cr.Failure("config", "cancelled"))

    def slow_merge(self, checkout, seconds):
        """A checkout whose fast-forward writes a file through a smudge filter that takes `seconds`."""
        marker = self.parent / "merging"
        git(checkout, "config", "filter.slow.smudge", f"touch {marker}; sleep {seconds}; cat")
        return marker

    def test_a_cancel_during_the_merge_lets_it_finish(self):
        checkout, seed = self.pair(
            1, contract=True, extra={".gitattributes": "slow.txt filter=slow\n", "slow.txt": "x\n"})
        merging = self.slow_merge(checkout, 3)

        class StopWhenMerging:
            def is_set(self):
                return merging.exists()

        done = cr.update(str(checkout), cancel=StopWhenMerging())
        self.assertEqual(done, cr.Updated(None, None))
        self.assertEqual(git(checkout, "rev-parse", "HEAD"), git(seed, "rev-parse", "HEAD"))
        self.assertEqual(git(checkout, "status", "--porcelain"), "")
        self.assertFalse((checkout / ".git" / "index.lock").exists())

    def test_a_merge_that_runs_past_the_fetch_bound_is_not_killed(self):
        checkout, seed = self.pair(
            1, contract=True, extra={".gitattributes": "slow.txt filter=slow\n", "slow.txt": "x\n"})
        self.slow_merge(checkout, 4)
        with mock.patch.object(cr, "FETCH_TIMEOUT", 2):
            done = cr.update(str(checkout))
        self.assertEqual(done, cr.Updated(None, None))
        self.assertEqual(git(checkout, "rev-parse", "HEAD"), git(seed, "rev-parse", "HEAD"))
        self.assertFalse((checkout / ".git" / "index.lock").exists())

    def test_a_cancel_before_the_merge_starts_moves_nothing(self):
        checkout, _ = self.pair(1, contract=True)
        head = git(checkout, "rev-parse", "HEAD")
        stopped = threading.Event()
        steps = []
        real = cr._git

        def count_then_stop(root, step, *arguments, **kwargs):
            steps.append(step)
            done = real(root, step, *arguments, **kwargs)
            if step == "rev-list" and steps.count("rev-list") == 2:
                stopped.set()
            return done

        with mock.patch.object(cr, "_git", count_then_stop):
            done = cr.update(str(checkout), cancel=stopped)
        self.assertEqual(done, cr.Updated(cr.NOT_MOVED, cr.Failure("merge", "cancelled")))
        self.assertNotIn("merge", steps)
        self.assertEqual(git(checkout, "rev-parse", "HEAD"), head)

    def test_update_fast_forwards_a_clean_checkout_to_the_remote(self):
        checkout, seed = self.pair(1, contract=True)
        self.assertEqual(cr.update(str(checkout)), cr.Updated(None, None))
        self.assertEqual(git(checkout, "rev-parse", "HEAD"), git(seed, "rev-parse", "HEAD"))
        self.assertEqual((checkout / ".agents" / "project.json").read_text(), "{}\n")

    def test_update_refuses_uncommitted_changes(self):
        checkout, _ = self.pair(1, contract=True)
        head = git(checkout, "rev-parse", "HEAD")
        (checkout / "README.md").write_text("changed\n")
        self.assertEqual(cr.update(str(checkout)), cr.Updated(cr.HAS_CHANGES, None))
        self.assertEqual(git(checkout, "rev-parse", "HEAD"), head)
        self.assertEqual((checkout / "README.md").read_text(), "changed\n")

    def test_update_refuses_another_branch(self):
        checkout, _ = self.pair(1, contract=True)
        git(checkout, "checkout", "-q", "-b", "side")
        head = git(checkout, "rev-parse", "HEAD")
        self.assertEqual(cr.update(str(checkout)), cr.Updated(cr.NOT_ON_BRANCH, None))
        self.assertEqual(git(checkout, "rev-parse", "HEAD"), head)

    def test_update_refuses_a_diverged_checkout(self):
        checkout, _ = self.pair(1, contract=True)
        (checkout / "local.md").write_text("mine\n")
        git(checkout, "add", "-A")
        git(checkout, "commit", "-q", "-m", "local")
        head = git(checkout, "rev-parse", "HEAD")
        self.assertEqual(cr.update(str(checkout)), cr.Updated(cr.DIVERGED, None))
        self.assertEqual(git(checkout, "rev-parse", "HEAD"), head)

    def test_update_never_overwrites_an_ignored_file(self):
        checkout, _ = self.pair(1, contract=False, extra={"local.env": "remote\n"})
        with open(checkout / ".git" / "info" / "exclude", "a") as handle:
            handle.write("local.env\n")
        (checkout / "local.env").write_text("mine\n")
        head = git(checkout, "rev-parse", "HEAD")
        done = cr.update(str(checkout))
        self.assertEqual(done.reason, cr.NOT_MOVED)
        self.assertEqual(done.failure.step, "merge")
        self.assertTrue(done.failure.detail.startswith("exit "))
        self.assertEqual(git(checkout, "rev-parse", "HEAD"), head)
        self.assertEqual((checkout / "local.env").read_text(), "mine\n")

    def test_update_runs_no_hook(self):
        checkout, _ = self.pair(1, contract=True)
        hook = checkout / ".git" / "hooks" / "post-merge"
        hook.write_text(f"#!/bin/sh\ntouch {checkout}/hooked\n")
        hook.chmod(0o755)
        self.assertEqual(cr.update(str(checkout)), cr.Updated(None, None))
        self.assertFalse((checkout / "hooked").exists())

    def test_update_of_a_current_checkout_changes_nothing(self):
        checkout, _ = self.pair(0, contract=False)
        head = git(checkout, "rev-parse", "HEAD")
        self.assertEqual(cr.update(str(checkout)), cr.Updated(None, None))
        self.assertEqual(git(checkout, "rev-parse", "HEAD"), head)

    def test_update_with_an_unreadable_remote_says_so_and_keeps_gits_words(self):
        root = self.lone(origin=str(self.parent / "missing.git"))
        done = cr.update(str(root))
        self.assertEqual(done.reason, cr.UNREAD_REASON)
        self.assertEqual(done.failure.step, "ls-remote")


if __name__ == "__main__":
    unittest.main()
