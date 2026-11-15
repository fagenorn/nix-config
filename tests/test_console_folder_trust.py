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
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent_tools.console import event_log, folder_trust
from agent_tools.console.event_log import Event
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


class RowTest(unittest.TestCase):
    def test_the_row_is_the_exact_tuple_and_refuses_what_is_not_valid(self):
        row = folder_trust.granted_row("apply", "p", "/r",
                                       [("default", "granted"), ("work", "failed")])
        self.assertEqual(row, ("trust.granted", None,
                               {"by": "owner", "cause": "apply", "project": "p", "root": "/r",
                                "profiles": [{"profile": "default", "result": "granted"},
                                             {"profile": "work", "result": "failed"}]}))
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


class WordsTest(unittest.TestCase):
    def test_the_words_and_the_targets(self):
        self.assertEqual(
            folder_trust.failed_words("/home/o/repo", "work"),
            "Run this in a terminal: cd /home/o/repo && CLAUDE_ACCOUNT=work claude, "
            "then accept the prompt and type /exit.")
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


if __name__ == "__main__":
    unittest.main()
