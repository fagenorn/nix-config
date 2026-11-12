"""Contract tests for `program-copies` (`agent_tools.delivery.program_copies`, issue 912).

The command runs as `python -m agent_tools.delivery.program_copies` against temporary git
checkouts, a main one and a linked worktree, with a skill directory whose program is a
symlink into a stand-in store (agent-helpers rule 5).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

GIT = ("git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false")


def run(*args):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    return subprocess.run([sys.executable, "-m", "agent_tools.delivery.program_copies", *args],
                          capture_output=True, text=True, env=env, check=False)


def status(checkout):
    return subprocess.run(["git", "-C", str(checkout), "status", "--porcelain", "--untracked-files=all"],
                          capture_output=True, text=True, check=True).stdout


class ProgramCopiesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.store = self.tmp / "store"
        self.store.mkdir()
        (self.store / "a.js").write_bytes(b"A1")
        (self.store / "b.js").write_bytes(b"B1")
        self.skill = self.tmp / "skills" / "deliver-standard"
        self.skill.mkdir(parents=True)
        (self.skill / "a.js").symlink_to(self.store / "a.js")
        (self.skill / "b.js").write_bytes(b"B1")
        (self.skill / "SKILL.md").write_text("skill\n")
        self.repo = self.tmp / "repo"
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        self.copies = self.repo / ".program-copies" / "deliver-standard"

    def place(self, repo=None):
        return run("--repo-root", str(repo or self.repo), "--from", str(self.skill))

    def test_copies_every_program_byte_for_byte_as_regular_files(self):
        done = self.place()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(done.stdout),
                         {"a.js": str(self.copies / "a.js"), "b.js": str(self.copies / "b.js")})
        self.assertEqual(len(done.stdout.splitlines()), 1)
        self.assertEqual((self.copies / "a.js").read_bytes(), b"A1")
        self.assertEqual((self.copies / "b.js").read_bytes(), b"B1")
        self.assertFalse((self.copies / "a.js").is_symlink())
        self.assertFalse((self.copies / "b.js").is_symlink())
        self.assertNotIn("SKILL.md", os.listdir(self.copies))
        self.assertEqual((self.repo / ".program-copies" / ".gitignore").read_text(), "*\n")
        self.assertEqual(status(self.repo), "")

    def test_a_changed_program_is_replaced_and_an_unchanged_one_is_kept(self):
        self.assertEqual(self.place().returncode, 0)
        os.link(self.copies / "a.js", self.tmp / "kept-a.js")
        before = os.stat(self.copies / "b.js")
        store2 = self.tmp / "store2"
        store2.mkdir()
        (store2 / "a.js").write_bytes(b"A2")
        (self.skill / "a.js").unlink()
        (self.skill / "a.js").symlink_to(store2 / "a.js")
        done = self.place()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual((self.copies / "a.js").read_bytes(), b"A2")
        self.assertEqual((self.tmp / "kept-a.js").read_bytes(), b"A1")
        after = os.stat(self.copies / "b.js")
        self.assertEqual((after.st_ino, after.st_mtime_ns), (before.st_ino, before.st_mtime_ns))
        self.assertEqual(sorted(os.listdir(self.copies)), ["a.js", "b.js"])

    def test_a_copy_outlives_its_installed_program(self):
        self.assertEqual(self.place().returncode, 0)
        shutil.rmtree(self.store)
        self.assertEqual((self.copies / "a.js").read_bytes(), b"A1")

    def test_an_existing_symlink_copy_becomes_a_regular_file(self):
        self.copies.mkdir(parents=True)
        (self.copies / "a.js").symlink_to(self.store / "a.js")
        done = self.place()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertFalse((self.copies / "a.js").is_symlink())
        self.assertEqual((self.copies / "a.js").read_bytes(), b"A1")

    def test_a_linked_worktree_places_its_copies_inside_itself(self):
        subprocess.run([*GIT, "-C", str(self.repo), "commit", "-q", "--allow-empty", "-m", "init"], check=True)
        wt = self.tmp / "wt"
        subprocess.run(["git", "-C", str(self.repo), "worktree", "add", "-q", "-b", "wt", str(wt)], check=True)
        d = wt / ".program-copies" / "deliver-standard"
        done = self.place(wt)
        self.assertEqual(done.returncode, 0, done.stderr)
        mapping = json.loads(done.stdout)
        self.assertEqual(mapping, {"a.js": str(d / "a.js"), "b.js": str(d / "b.js")})
        for value in mapping.values():
            self.assertTrue(value.startswith(str(wt) + os.sep))
        self.assertEqual((d / "a.js").read_bytes(), b"A1")
        self.assertFalse((self.repo / ".program-copies").exists())
        self.assertFalse((self.repo / ".git" / "program-copies").exists())
        self.assertEqual(status(wt), "")

    def test_refusals(self):
        (self.repo / "sub").mkdir()
        (self.tmp / "plain").mkdir()
        only_doc = self.tmp / "only-doc"
        only_doc.mkdir()
        (only_doc / "SKILL.md").write_text("x\n")
        cases = [
            ("no programs", ["--repo-root", str(self.repo), "--from", str(only_doc)], 1, "no_programs"),
            ("missing from", ["--repo-root", str(self.repo), "--from", str(self.tmp / "nope")], 1, "no_programs"),
            ("plain dir", ["--repo-root", str(self.tmp / "plain"), "--from", str(self.skill)], 1, "not_a_checkout"),
            ("subdirectory", ["--repo-root", str(self.repo / "sub"), "--from", str(self.skill)], 1, "not_a_checkout"),
            ("git dir", ["--repo-root", str(self.repo / ".git"), "--from", str(self.skill)], 1, "not_a_checkout"),
            ("relative from", ["--repo-root", str(self.repo), "--from", "skills/deliver-standard"], 2, "relative_path"),
        ]
        for label, argv, code, error in cases:
            with self.subTest(label):
                done = run(*argv)
                self.assertEqual(done.returncode, code, done.stderr)
                self.assertEqual(json.loads(done.stderr)["error"]["code"], error)
                self.assertFalse((self.repo / ".program-copies").exists())
                self.assertFalse((self.repo / "sub" / ".program-copies").exists())

    def test_an_unsafe_destination_is_refused_before_anything_is_written(self):
        (self.repo / "app.js").write_bytes(b"tracked")
        outside = self.tmp / "outside"
        outside.mkdir()
        linked_base = self.tmp / "linked-base"
        linked_base.mkdir()
        linked_dir = self.tmp / "linked-dir"
        linked_dir.mkdir()
        (linked_dir / ".program-copies").mkdir()
        (linked_dir / ".program-copies" / "deliver-standard").symlink_to(outside)
        (linked_base / ".program-copies").symlink_to(outside)
        for repo in (linked_base, linked_dir):
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
        cases = [
            ("dot-dot name", self.repo, str(self.skill / "sub" / ".."), self.repo / "app.js"),
            ("symlinked copy root", linked_base, str(self.skill), outside / "deliver-standard" / "a.js"),
            ("symlinked copy directory", linked_dir, str(self.skill), outside / "a.js"),
        ]
        (self.skill / "sub").mkdir()
        for label, repo, source, victim in cases:
            with self.subTest(label):
                done = run("--repo-root", str(repo), "--from", source)
                self.assertEqual(done.returncode, 1, done.stderr)
                self.assertEqual(json.loads(done.stderr)["error"]["code"], "unsafe_destination")
                self.assertEqual(done.stdout, "")
                self.assertNotEqual(victim.read_bytes() if victim.exists() else None, b"A1")
        self.assertEqual((self.repo / "app.js").read_bytes(), b"tracked")
        self.assertEqual(os.listdir(outside), [])
        self.assertFalse((self.repo / ".program-copies").exists())

    def test_help_names_the_command(self):
        done = run("--help")
        self.assertEqual(done.returncode, 0)
        self.assertTrue(done.stdout.startswith("usage: program-copies"))


if __name__ == "__main__":
    unittest.main()
