"""The console's folder trust (#1078): the key, the exchanging-rename grant, the row, the words.

Every file lives under a temporary directory; no real `~/.claude.json` is read or written.

Run: just agent-workflow-tests
"""

from __future__ import annotations

import contextlib
import errno
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent_tools.console import event_log, folder_trust
from agent_tools.console.event_log import Event
from . import console_test_support as support
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)


def atomic_write(path: Path, text: str) -> None:
    """A writer that replaces the file the way the client does: a temporary, then `os.replace`."""
    temp = path.with_name("writer-" + path.name)
    temp.write_text(text, encoding="utf-8")
    os.replace(temp, path)


def leftovers(directory: Path, prefix: str) -> list[str]:
    return sorted(name for name in os.listdir(directory) if name.startswith(prefix))


class FileCase(unittest.TestCase):
    def setUp(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.dir = Path(holder.name)
        self.path = self.dir / ".claude.json"

    def arrange(self, document, mode: int = 0o600) -> None:
        self.path.write_text(json.dumps(document), encoding="utf-8")
        os.chmod(self.path, mode)

    def parsed(self):
        return json.loads(self.path.read_text(encoding="utf-8"))


TRUSTED = {"hasTrustDialogAccepted": True}


class GrantTest(FileCase):
    def test_only_the_key_changes_and_oauth_account_is_kept(self):
        before = {"oauthAccount": {"emailAddress": "o@example.test"}, "numStartups": 3,
                  "projects": {"/r": {"allowedTools": ["x"]},
                               "/other": {"hasTrustDialogAccepted": False}}}
        self.arrange(before)
        self.assertEqual(folder_trust.grant(self.path, "/r"), "granted")
        expected = json.loads(json.dumps(before))
        expected["projects"]["/r"]["hasTrustDialogAccepted"] = True
        self.assertEqual(self.parsed(), expected)

    def test_a_key_already_true_is_not_written(self):
        self.arrange({"projects": {"/r": dict(TRUSTED)}})
        before = os.stat(self.path)
        self.assertEqual(folder_trust.grant(self.path, "/r"), "already")
        after = os.stat(self.path)
        self.assertEqual((after.st_ino, after.st_mtime_ns), (before.st_ino, before.st_mtime_ns))

    def test_a_concurrent_write_is_re_read_kept_and_the_key_still_set(self):
        self.arrange({"projects": {}})
        calls = []

        def hook(attempt):
            calls.append(attempt)
            if attempt == 0:
                atomic_write(self.path, json.dumps({"projects": {}, "clientField": 1}))

        result = folder_trust.grant(self.path, "/r", before_swap=hook)
        self.assertEqual(result, "granted")
        self.assertEqual(self.parsed(), {"projects": {"/r": dict(TRUSTED)}, "clientField": 1})
        self.assertEqual(calls, [0, 1])

    def test_an_in_place_write_before_the_swap_is_kept(self):
        self.arrange({"projects": {}})

        def hook(attempt):
            if attempt == 0:
                with open(self.path, "r+", encoding="utf-8") as handle:
                    handle.truncate(0)
                    handle.write(json.dumps({"projects": {}, "inPlace": 2}))

        self.assertEqual(folder_trust.grant(self.path, "/r", before_swap=hook), "granted")
        self.assertEqual(self.parsed(), {"projects": {"/r": dict(TRUSTED)}, "inPlace": 2})

    def test_a_writer_that_never_settles_fails_and_keeps_its_content(self):
        self.arrange({"projects": {}})

        def hook(attempt):
            atomic_write(self.path, json.dumps({"n": attempt}))

        result = folder_trust.grant(self.path, "/r", attempts=3, before_swap=hook)
        self.assertEqual(result, "failed")
        self.assertEqual(self.parsed(), {"n": 2})
        self.assertEqual(leftovers(self.dir, ".claude.json.trust-"), [])

    def test_a_write_during_the_put_back_is_kept_beside_the_file(self):
        self.arrange({"projects": {}})
        real = folder_trust.swap
        calls = []

        def hook(attempt):
            atomic_write(self.path, json.dumps({"n": attempt}))

        def wrapper(a, b):
            calls.append(1)
            if len(calls) == 4:
                atomic_write(self.path, json.dumps({"late": 1}))
            real(a, b)

        stderr = io.StringIO()
        with mock.patch.object(folder_trust, "swap", new=wrapper), \
                contextlib.redirect_stderr(stderr):
            result = folder_trust.grant(self.path, "/r", attempts=3, before_swap=hook)
        self.assertEqual(result, "failed")
        kept = leftovers(self.dir, folder_trust.KEPT_PREFIX)
        self.assertEqual(len(kept), 1)
        self.assertEqual(json.loads((self.dir / kept[0]).read_text(encoding="utf-8")), {"late": 1})
        self.assertIn(f"folder_trust: kept {kept[0]}", stderr.getvalue())
        self.assertEqual(self.parsed(), {"n": 2})
        self.assertEqual(leftovers(self.dir, ".claude.json.trust-"), kept)

    def test_a_displaced_document_the_next_attempt_refuses_is_put_back(self):
        for index, text in enumerate(("[]", "not json", '{"projects": []}',
                                      '{"projects": {"/r": 1}}')):
            with self.subTest(text=text):
                path = self.dir / f"refused-{index}.json"
                path.write_text(json.dumps({"projects": {}}), encoding="utf-8")

                def hook(attempt, path=path, text=text):
                    if attempt == 0:
                        atomic_write(path, text)

                self.assertEqual(folder_trust.grant(path, "/r", before_swap=hook), "failed")
                self.assertEqual(path.read_text(encoding="utf-8"), text)
        self.assertEqual(leftovers(self.dir, ".claude.json.trust-"), [])

    def test_a_displaced_document_is_put_back_when_the_next_attempt_cannot_write(self):
        foreign = json.dumps({"projects": {}, "clientField": 1})
        real_temp, real_swap = folder_trust._temp, folder_trust.swap
        for name, patched in (("temp", "_temp"), ("swap", "swap")):
            with self.subTest(step=name):
                path = self.dir / f"cannot-{name}.json"
                path.write_text(json.dumps({"projects": {}}), encoding="utf-8")
                calls = []

                def hook(attempt, path=path):
                    if attempt == 0:
                        atomic_write(path, foreign)

                def fail_second(real):
                    def wrapper(*args):
                        calls.append(1)
                        if len(calls) == 2:
                            raise OSError(errno.ENOSPC, "full")
                        return real(*args)
                    return wrapper

                real = real_temp if name == "temp" else real_swap
                with mock.patch.object(folder_trust, patched, new=fail_second(real)):
                    self.assertEqual(folder_trust.grant(path, "/r", before_swap=hook), "failed")
                self.assertEqual(path.read_text(encoding="utf-8"), foreign)
        self.assertEqual(leftovers(self.dir, ".claude.json.trust-"), [])

    def _unreadable_displaced(self, swap_wrapper):
        """Grant over a client write whose displaced document then cannot be read."""
        self.arrange({"projects": {}})
        foreign = json.dumps({"projects": {}, "clientField": 1})
        real_read = folder_trust._read
        unread = []

        def hook(attempt):
            if attempt == 0:
                atomic_write(self.path, foreign)

        def read(path):
            if Path(path).name.startswith(folder_trust.TEMP_PREFIX) and not unread:
                unread.append(1)
                raise OSError(errno.EIO, "unreadable")
            return real_read(path)

        stderr = io.StringIO()
        with mock.patch.object(folder_trust, "_read", new=read), \
                mock.patch.object(folder_trust, "swap", new=swap_wrapper(folder_trust.swap)), \
                contextlib.redirect_stderr(stderr):
            result = folder_trust.grant(self.path, "/r", before_swap=hook)
        return result, foreign, stderr.getvalue()

    def test_a_displaced_document_is_kept_when_the_rollback_swap_fails(self):
        def failing_second(real):
            calls = []

            def wrapper(a, b):
                calls.append(1)
                if len(calls) == 2:
                    raise OSError(errno.ENOSPC, "full")
                return real(a, b)
            return wrapper

        result, foreign, stderr = self._unreadable_displaced(failing_second)
        self.assertEqual(result, "failed")
        kept = leftovers(self.dir, folder_trust.KEPT_PREFIX)
        self.assertEqual(len(kept), 1)
        self.assertEqual((self.dir / kept[0]).read_text(encoding="utf-8"), foreign)
        self.assertIn(f"folder_trust: kept {kept[0]}", stderr)
        self.assertEqual(leftovers(self.dir, ".claude.json.trust-"), kept)

    def test_a_writer_replacing_the_file_before_the_rollback_swap_is_kept(self):
        def writing_second(real):
            calls = []

            def wrapper(a, b):
                calls.append(1)
                if len(calls) == 2:
                    atomic_write(self.path, json.dumps({"newer": 1}))
                return real(a, b)
            return wrapper

        result, foreign, stderr = self._unreadable_displaced(writing_second)
        self.assertEqual(result, "failed")
        kept = leftovers(self.dir, folder_trust.KEPT_PREFIX)
        self.assertEqual(len(kept), 1)
        self.assertEqual(json.loads((self.dir / kept[0]).read_text(encoding="utf-8")),
                         {"newer": 1})
        self.assertEqual(self.path.read_text(encoding="utf-8"), foreign)
        self.assertEqual(leftovers(self.dir, ".claude.json.trust-"), kept)

    def test_the_mode_is_kept_and_a_new_file_is_0600(self):
        self.arrange({"projects": {}}, mode=0o640)
        self.assertEqual(folder_trust.grant(self.path, "/r"), "granted")
        self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o640)
        fresh = self.dir / "fresh.json"
        self.assertEqual(folder_trust.grant(fresh, "/r"), "granted")
        self.assertEqual(json.loads(fresh.read_text(encoding="utf-8")),
                         {"projects": {"/r": dict(TRUSTED)}})
        self.assertEqual(os.stat(fresh).st_mode & 0o777, 0o600)
        self.assertEqual(leftovers(self.dir, ".claude.json.trust-"), [])

    def test_a_document_that_is_not_an_object_or_a_link_is_never_written(self):
        for index, document in enumerate(([], {"projects": []}, {"projects": {"/r": 1}})):
            with self.subTest(document=document):
                path = self.dir / f"doc-{index}.json"
                path.write_text(json.dumps(document), encoding="utf-8")
                before = path.read_bytes()
                self.assertEqual(folder_trust.grant(path, "/r"), "failed")
                self.assertEqual(path.read_bytes(), before)
        target = self.dir / "target.json"
        target.write_text(json.dumps({"projects": {}}), encoding="utf-8")
        link = self.dir / "link.json"
        link.symlink_to(target)
        before = target.read_bytes()
        self.assertEqual(folder_trust.grant(link, "/r"), "failed")
        self.assertEqual(target.read_bytes(), before)
        self.assertTrue(link.is_symlink())
        self.assertEqual(leftovers(self.dir, ".claude.json.trust-"), [])

    def test_a_read_back_without_the_key_retries_then_fails(self):
        self.arrange({"projects": {}})
        real = folder_trust.swap

        def wrapper(a, b):
            real(a, b)
            atomic_write(self.path, json.dumps({"projects": {}}))

        with mock.patch.object(folder_trust, "swap", new=wrapper):
            self.assertEqual(folder_trust.grant(self.path, "/r", attempts=2), "failed")
        self.assertEqual(self.parsed(), {"projects": {}})
        self.assertEqual(leftovers(self.dir, ".claude.json.trust-"), [])

    def test_without_an_exchanging_rename_nothing_is_written(self):
        self.arrange({"projects": {}})
        before = self.path.read_bytes()
        with mock.patch.object(folder_trust, "swap", side_effect=OSError(errno.EINVAL, "x")):
            self.assertEqual(folder_trust.grant(self.path, "/r"), "failed")
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(leftovers(self.dir, ".claude.json.trust-"), [])


class RemoveTest(FileCase):
    def test_the_entry_is_removed_and_nothing_else(self):
        self.arrange({"oauthAccount": {"a": 1},
                      "projects": {"/r": dict(TRUSTED), "/k": {"x": 1}}})
        self.assertEqual(folder_trust.remove_entry(self.path, "/r"), "removed")
        self.assertEqual(self.parsed(), {"oauthAccount": {"a": 1}, "projects": {"/k": {"x": 1}}})
        inode = os.stat(self.path).st_ino
        self.assertEqual(folder_trust.remove_entry(self.path, "/r"), "absent")
        self.assertEqual(os.stat(self.path).st_ino, inode)
        missing = self.dir / "missing.json"
        self.assertEqual(folder_trust.remove_entry(missing, "/r"), "absent")
        self.assertFalse(missing.exists())
        self.assertEqual(leftovers(self.dir, ".claude.json.trust-"), [])


def git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.test",
                    "-c", "commit.gpgsign=false", *args], cwd=cwd, check=True,
                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class KeyTest(unittest.TestCase):
    def test_the_key_is_the_main_checkout_of_a_linked_worktree(self):
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            repo = base / "repo"
            repo.mkdir()
            git("init", "-q", cwd=repo)
            git("commit", "-q", "--allow-empty", "-m", "x", cwd=repo)
            worktree = base / "linked"
            git("worktree", "add", "-q", str(worktree), "-b", "side", cwd=repo)
            plain = base / "plain"
            plain.mkdir()
            expected = os.path.realpath(repo)
            self.assertEqual(folder_trust.trust_key(str(worktree)), expected)
            self.assertEqual(folder_trust.trust_key(str(repo)), expected)
            self.assertIsNone(folder_trust.trust_key(str(plain)))
            self.assertIsNone(folder_trust.trust_key(str(base / "missing")))


class ExternalGitDirKeyTest(unittest.TestCase):
    def test_a_submodule_and_a_separate_git_dir_are_keyed_by_their_checkout(self):
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            library = base / "library"
            library.mkdir()
            git("init", "-q", cwd=library)
            git("commit", "-q", "--allow-empty", "-m", "x", cwd=library)
            super_repo = base / "super"
            super_repo.mkdir()
            git("init", "-q", cwd=super_repo)
            git("-c", "protocol.file.allow=always", "submodule", "add", "-q", str(library), "sub",
                cwd=super_repo)
            separate = base / "separate"
            separate.mkdir()
            git("init", "-q", f"--separate-git-dir={base / 'meta'}", cwd=separate)
            for checkout in (super_repo / "sub", separate):
                with self.subTest(checkout=checkout.name):
                    self.assertEqual(folder_trust.trust_key(str(checkout)),
                                     os.path.realpath(checkout))


class RowTest(unittest.TestCase):
    def test_the_row_is_the_exact_tuple_and_refuses_what_is_not_valid(self):
        row = folder_trust.granted_row("apply", "p", "/r",
                                       [("default", "granted"), ("work", "failed")])
        self.assertEqual(row, ("trust.granted", None,
                               {"by": "owner", "cause": "apply", "project": "p", "root": "/r",
                                "profiles": [{"profile": "default", "result": "granted"},
                                             {"profile": "work", "result": "failed"}]}))
        self.assertEqual(folder_trust.START_CAUSE, "console-start")
        self.assertEqual(
            folder_trust.granted_row("console-start", "p", "/r", [("default", "already")])[2]["cause"],
            "console-start")
        for args in (("other", "p", "/r", [("work", "granted")]),
                     ("apply", "p", "/r", [("work", "maybe")]),
                     ("apply", "p", "/r", [("Bad Name", "granted")]),
                     ("apply", "", "/r", [("work", "granted")]),
                     ("apply", "p", "", [("work", "granted")])):
            with self.subTest(args=args), self.assertRaises(ValueError):
                folder_trust.granted_row(*args)

    def test_failures_fold_by_root_and_profile(self):
        def event(seq, results, payload=None):
            row = folder_trust.granted_row("apply", "p", "/r", results)
            return Event(seq=seq, at=f"t{seq}", kind=row[0], project=None,
                         payload=row[2] if payload is None else payload)

        failed = event(1, [("work", "failed")])
        granted = event(2, [("work", "granted")])
        self.assertEqual(folder_trust.failures([failed]),
                         {("/r", "work"): {"root": "/r", "project": "p", "profile": "work",
                                           "at": "t1"}})
        self.assertEqual(folder_trust.failures([failed, granted]), {})
        invalid = event(3, [("work", "failed")], payload={"by": "owner", "root": "/r"})
        self.assertEqual(folder_trust.failures([invalid]), {})
        state = folder_trust.failures([failed])
        again = folder_trust.failures([granted], state)
        self.assertEqual(again, {})
        self.assertEqual(len(state), 1)
        other = Event(seq=4, at="t4", kind=event_log.ACCOUNT_ADDED, project=None,
                      payload={"by": "owner", "profile": "work"})
        self.assertEqual(folder_trust.failures([other]), {})

    def test_a_cancel_drops_that_roots_trust_failures(self):
        def granted(seq, root):
            row = folder_trust.granted_row("apply", "p", root, [("work", "failed")])
            return Event(seq=seq, at=f"t{seq}", kind=row[0], project=None, payload=row[2])

        def cancel(seq, root, payload=None):
            return Event(seq=seq, at=f"t{seq}", kind=event_log.REGISTRATION_CANCELLED,
                         project=None,
                         payload=payload or {"by": "owner", "root": root, "plan_id": "P"})

        events = [granted(1, "/x/r"), granted(2, "/x/s")]
        self.assertEqual(set(folder_trust.failures([*events, cancel(3, "/x/r")])),
                         {("/x/s", "work")})
        self.assertEqual(set(folder_trust.failures([cancel(3, "/x/r")],
                                                   folder_trust.failures(events))),
                         {("/x/s", "work")})
        self.assertEqual(len(folder_trust.failures([*events, cancel(3, "/x/other")])), 2)
        bad = cancel(3, "/x/r", {"root": "/x/r", "plan_id": "P"})
        self.assertEqual(len(folder_trust.failures([*events, bad])), 2)
        later = folder_trust.failures([*events, cancel(3, "/x/r"), granted(4, "/x/r")])
        self.assertEqual(set(later), {("/x/r", "work"), ("/x/s", "work")})

    def test_removing_the_account_drops_its_failed_pairs_only_when_it_is_gone(self):
        def removal(seq, profile, outcome, kind=None):
            return Event(seq=seq, at=f"t{seq}", kind=event_log.ACCOUNT_REMOVAL, project=None,
                         payload={"by": "owner", "profile": profile, "outcome": outcome,
                                  "kind": kind})

        row = folder_trust.granted_row("apply", "p", "/r",
                                       [("work", "failed"), ("solo", "failed")])
        failed = Event(seq=1, at="t1", kind=row[0], project=None, payload=row[2])
        for outcome, kind in (("removed", None), ("removed_signed_out_already", "timeout")):
            with self.subTest(outcome=outcome):
                kept = folder_trust.failures([failed, removal(2, "solo", outcome, kind)])
                self.assertEqual(list(kept), [("/r", "work")])
        for outcome in ("signout_failed", "remove_failed"):
            with self.subTest(outcome=outcome):
                kept = folder_trust.failures([failed, removal(2, "solo", outcome, "timeout")])
                self.assertEqual(sorted(kept), [("/r", "solo"), ("/r", "work")])
        again = folder_trust.failures(
            [removal(2, "solo", "removed"), Event(seq=3, at="t3", kind=row[0], project=None,
                                                   payload=row[2])],
            folder_trust.failures([failed]))
        self.assertEqual(sorted(again), [("/r", "solo"), ("/r", "work")])


class ItemsTest(unittest.TestCase):
    @staticmethod
    def event(seq, results):
        row = folder_trust.granted_row("apply", "p", "/r", results)
        return Event(seq=seq, at=f"t{seq}", kind=row[0], project=None, payload=row[2])

    def test_items_follow_the_fold(self):
        failed = self.event(1, [("work", "failed")])
        granted = self.event(2, [("work", "granted")])
        (card,) = folder_trust.items(folder_trust.failures([failed]))
        self.assertEqual(card["key"], "trust/work//r/t1")
        self.assertEqual(card["why"], folder_trust.failed_words("p", "work"))
        self.assertEqual(card["command"], folder_trust.command("/r", "work"))
        self.assertEqual(folder_trust.items(folder_trust.failures([failed, granted])), [])


class RequestTest(unittest.TestCase):
    def test_a_check_request_is_exactly_a_root_and_a_profile(self):
        self.assertEqual(
            folder_trust.parse_check_request(b'{"root": "/r", "profile": "work"}'),
            ("/r", "work"))
        for body in (b"[]", b"\xff", b'{"root": "/r"}', b'{"root": "", "profile": "w"}',
                     b'{"root": "/r", "profile": 1}', b'{"root": "/r\\n", "profile": "w"}',
                     b'{"root": "/r", "profile": "w", "x": 1}'):
            with self.subTest(body=body), self.assertRaises(ValueError):
                folder_trust.parse_check_request(body)


class WordsTest(unittest.TestCase):
    def test_the_words_and_the_targets(self):
        self.assertEqual(
            folder_trust.failed_words("repo", "work"),
            ("Open Claude Code in the repo folder under the work profile, accept its trust "
             "prompt and close it, then choose Check again."))
        self.assertEqual(folder_trust.command("/a b", "work"),
                         "cd '/a b' && CLAUDE_ACCOUNT=work claude")
        self.assertEqual(folder_trust.TRUST_SENTENCE,
                         "Registering lets agents run in this folder with the folder's own "
                         "settings and hooks.")
        self.assertEqual(
            folder_trust.targets(Path("/h"), [Path("/a/profiles/work"), Path("/a/profiles/Bad")]),
            [("default", Path("/h/.claude.json")), ("work", Path("/a/profiles/work/.claude.json"))])
        self.assertEqual(folder_trust.targets(None, [Path("/a/profiles/work")]),
                         [("work", Path("/a/profiles/work/.claude.json"))])


class CommandTest(unittest.TestCase):
    """`folder-trust grant-registered --profile <name>` run as the module, in a sandboxed HOME."""

    def setUp(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.base = Path(holder.name)
        self.home = self.base / "home"
        self.accounts = self.base / "accounts"
        self.home.mkdir()
        (self.home / ".claude.json").write_text("{}", encoding="utf-8")
        self.env = {**os.environ, "HOME": str(self.home), "CLAUDE_ACCOUNTS_DIR": str(self.accounts),
                    "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "python")}

    def repo(self, name: str) -> Path:
        repo = self.base / name
        repo.mkdir()
        git("init", "-q", cwd=repo)
        return repo

    def register(self, **projects: Path) -> None:
        support.write_registry(
            self.home / ".agents/state/fleet/registry.json",
            [{"project_id": project_id, "root": str(root)} for project_id, root in projects.items()])

    def profile(self, name: str, document=None) -> Path:
        directory = self.accounts / "profiles" / name
        directory.mkdir(parents=True)
        (directory / ".claude.json").write_text(
            json.dumps({"oauthAccount": {"x": 1}} if document is None else document),
            encoding="utf-8")
        return directory / ".claude.json"

    def run_command(self, *argv: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "agent_tools.console.folder_trust", *argv], env=self.env,
            stdin=subprocess.DEVNULL, capture_output=True, text=True, check=False)

    def test_grant_registered_sets_every_registered_root_in_the_named_profile_only(self):
        a, b = self.repo("a"), self.repo("b")
        self.register(alpha=a, beta=b)
        work, other = self.profile("work"), self.profile("other")
        other_before = other.read_bytes()
        home_before = (self.home / ".claude.json").read_bytes()
        done = self.run_command("grant-registered", "--profile", "work")
        self.assertEqual((done.returncode, done.stdout), (0, "alpha: granted\nbeta: granted\n"),
                         done.stderr)
        document = json.loads(work.read_text(encoding="utf-8"))
        self.assertEqual(document["oauthAccount"], {"x": 1})
        for repo in (a, b):
            self.assertIs(
                document["projects"][os.path.realpath(repo)]["hasTrustDialogAccepted"], True)
        self.assertEqual(other.read_bytes(), other_before)
        self.assertEqual((self.home / ".claude.json").read_bytes(), home_before)

    def test_a_failed_project_prints_its_command_and_exits_1(self):
        a = self.repo("a")
        self.register(alpha=a)
        self.profile("work", {"projects": []})
        done = self.run_command("grant-registered", "--profile", "work")
        key = os.path.realpath(a)
        self.assertEqual(done.returncode, 1)
        self.assertEqual(
            done.stdout.splitlines(),
            ["alpha: failed",
             f"  Run this in a terminal: cd {key} && CLAUDE_ACCOUNT=work claude, "
             "then accept the prompt and type /exit."])

    def test_an_absent_registry_is_nothing_and_a_bad_name_is_exit_2(self):
        self.profile("work")
        done = self.run_command("grant-registered", "--profile", "work")
        self.assertEqual((done.returncode, done.stdout), (0, ""), done.stderr)
        bad = self.run_command("grant-registered", "--profile=default")
        self.assertEqual((bad.returncode, bad.stderr),
                         (2, "folder-trust: default is not an account name\n"))
        missing = self.run_command("grant-registered", "--profile=ghost")
        self.assertEqual((missing.returncode, missing.stderr), (2, "folder-trust: no account ghost\n"))

    def test_an_unreadable_registry_is_exit_1(self):
        self.profile("work")
        path = self.home / ".agents/state/fleet/registry.json"
        path.parent.mkdir(parents=True)
        path.write_text("not json", encoding="utf-8")
        done = self.run_command("grant-registered", "--profile=work")
        self.assertEqual((done.returncode, done.stderr),
                         (1, "folder-trust: the project registry cannot be read\n"))

    def test_a_profile_named_like_an_option_is_granted(self):
        a = self.repo("a")
        self.register(alpha=a)
        target = self.profile("-h")
        done = self.run_command("grant-registered", "--profile=-h")
        self.assertEqual((done.returncode, done.stdout), (0, "alpha: granted\n"), done.stderr)
        self.assertIs(json.loads(target.read_text(encoding="utf-8"))["projects"][
            os.path.realpath(a)]["hasTrustDialogAccepted"], True)


class CheckRegisteredTest(CommandTest):
    """`folder-trust check-registered`: read-only, one JSON line, exit 0 only when all is trusted."""

    ROOT = Path(__file__).resolve().parent.parent
    WRAPPER = "home/common/verify-pending/checks/console-folder-trust"

    def trusted(self, *keys: str) -> dict:
        return {"projects": {key: {"hasTrustDialogAccepted": True} for key in keys}}

    def snapshot(self, *paths: Path) -> dict:
        found = {}
        for path in paths:
            status = path.stat()
            found[path] = (status.st_ino, status.st_mtime_ns, path.read_bytes())
        return found

    def check(self) -> tuple[subprocess.CompletedProcess, dict]:
        done = self.run_command("check-registered")
        return done, (json.loads(done.stdout) if done.stdout else None)

    def all_trusted(self) -> list[Path]:
        keys = [os.path.realpath(self.repo("alpha")), os.path.realpath(self.repo("beta"))]
        self.register(alpha=Path(keys[0]), beta=Path(keys[1]))
        document = self.trusted(*keys)
        (self.home / ".claude.json").write_text(json.dumps(document), encoding="utf-8")
        return [self.home / ".claude.json", self.profile("solo", document),
                self.profile("work", document)]

    def test_check_registered_is_met_when_every_target_trusts_every_project(self):
        files = self.all_trusted()
        before = self.snapshot(*files)
        done, report = self.check()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(report, {"status": "met", "projects": 2, "missing": []})
        self.assertEqual(self.snapshot(*files), before)

    def test_check_registered_names_each_missing_pair_and_writes_nothing(self):
        alpha, beta = self.repo("alpha"), self.repo("beta")
        self.register(alpha=alpha, beta=beta)
        keys = [os.path.realpath(alpha), os.path.realpath(beta)]
        solo = self.profile("solo", self.trusted(keys[1]))
        work = self.profile("work", {"projects": {
            keys[0]: {"hasTrustDialogAccepted": True},
            keys[1]: {"hasTrustDialogAccepted": False}}})
        (self.home / ".claude.json").unlink()
        before = self.snapshot(solo, work)
        done, report = self.check()
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertEqual(report, {"status": "not_met", "projects": 2, "missing": [
            {"project": "alpha", "profile": "default"}, {"project": "alpha", "profile": "solo"},
            {"project": "beta", "profile": "default"}, {"project": "beta", "profile": "work"}]})
        self.assertFalse((self.home / ".claude.json").exists())
        self.assertEqual(self.snapshot(solo, work), before)

    def test_check_registered_fails_on_an_unreadable_or_absent_registry(self):
        self.register(alpha=self.repo("alpha"))
        path = self.home / ".agents/state/fleet/registry.json"
        for label, damage in (("unreadable", lambda: path.write_text("{", encoding="utf-8")),
                              ("absent", path.unlink)):
            with self.subTest(label):
                damage()
                done, report = self.check()
                self.assertEqual(done.returncode, 1, done.stderr)
                self.assertEqual(report, {"status": "registry_unreadable", "projects": 0,
                                          "missing": []})

    def test_the_wrapper_is_committed_executable_and_runs_the_check(self):
        self.all_trusted()
        done = subprocess.run(
            [str(self.ROOT / self.WRAPPER)], cwd=self.ROOT, env=self.env,
            stdin=subprocess.DEVNULL, capture_output=True, text=True, check=False)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(done.stdout)["status"], "met")
        staged = subprocess.run(
            ["git", "-C", str(self.ROOT), "ls-files", "-s", self.WRAPPER],
            capture_output=True, text=True, check=True).stdout
        self.assertEqual(staged.split()[0], "100755")


if __name__ == "__main__":
    unittest.main()
