"""Contract tests for `program-copies` (`agent_tools.delivery.program_copies`, issues 912 and 981).

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
import time
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

    def placed(self):
        """Place the skill's programs; the printed mapping and its set directory."""
        done = self.place()
        self.assertEqual(done.returncode, 0, done.stderr)
        mapping = json.loads(done.stdout)
        (directory,) = {Path(value).parent for value in mapping.values()}
        return mapping, directory

    def change(self, name, data):
        """Install another version of one program, as an activation does."""
        (self.skill / name).unlink()
        (self.skill / name).write_bytes(data)

    def snapshot(self, directory):
        return {p.name: (p.read_bytes(), p.stat().st_ino, p.stat().st_mtime_ns)
                for p in directory.iterdir() if p.is_file()}

    def sets(self):
        return sorted(p.name for p in self.copies.iterdir() if p.is_dir())

    def test_copies_every_program_byte_for_byte_as_regular_files(self):
        done = self.place()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(len(done.stdout.splitlines()), 1)
        mapping = json.loads(done.stdout)
        (directory,) = {Path(value).parent for value in mapping.values()}
        self.assertEqual(directory.parent, self.copies)
        self.assertRegex(directory.name, r"\A[0-9a-f]{12}\Z")
        self.assertEqual(mapping, {"a.js": str(directory / "a.js"), "b.js": str(directory / "b.js")})
        self.assertEqual((directory / "a.js").read_bytes(), b"A1")
        self.assertEqual((directory / "b.js").read_bytes(), b"B1")
        self.assertFalse((directory / "a.js").is_symlink())
        self.assertFalse((directory / "b.js").is_symlink())
        self.assertEqual(sorted(os.listdir(directory)), ["a.js", "b.js"])
        self.assertEqual(os.listdir(self.copies), [directory.name])
        self.assertEqual((self.repo / ".program-copies" / ".gitignore").read_text(), "*\n")
        self.assertEqual(status(self.repo), "")

    def test_placing_a_changed_set_alters_no_file_of_an_earlier_set(self):
        """#981: a later placement leaves every file of an earlier set as it was."""
        _, first = self.placed()
        before = self.snapshot(first)
        self.change("a.js", b"A2")
        mapping, second = self.placed()
        self.assertNotEqual(second, first)
        self.assertEqual(self.snapshot(first), before)
        self.assertEqual(Path(mapping["a.js"]).read_bytes(), b"A2")
        self.assertEqual(Path(mapping["b.js"]).read_bytes(), b"B1")

    def test_a_batch_keeps_its_child_program_after_a_later_placement(self):
        """#981: the child path a batch was launched with still holds that launch's program, beside the batch's."""
        launch, _ = self.placed()
        batch, child = Path(launch["a.js"]), Path(launch["b.js"])
        self.assertEqual(batch.parent, child.parent)
        self.change("a.js", b"A2")
        self.change("b.js", b"B2")
        later, _ = self.placed()
        self.assertEqual((batch.read_bytes(), child.read_bytes()), (b"A1", b"B1"))
        self.assertEqual(Path(later["b.js"]).read_bytes(), b"B2")
        self.assertNotEqual(later["b.js"], launch["b.js"])

    def test_placing_an_unchanged_set_writes_nothing_and_prints_the_same_path(self):
        """#981: a refresh with the same programs is a no-op."""
        first = self.place()
        mapping, directory = self.placed()
        before = self.snapshot(directory)
        ignore = os.stat(self.repo / ".program-copies" / ".gitignore")
        again = self.place()
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertEqual((again.stdout, json.loads(again.stdout)), (first.stdout, mapping))
        self.assertEqual(self.snapshot(directory), before)
        self.assertEqual(os.listdir(self.copies), [directory.name])
        after = os.stat(self.repo / ".program-copies" / ".gitignore")
        self.assertEqual((after.st_ino, after.st_mtime_ns), (ignore.st_ino, ignore.st_mtime_ns))

    def test_a_set_returns_to_its_own_directory_when_its_programs_return(self):
        _, first = self.placed()
        self.change("a.js", b"A2")
        self.placed()
        self.change("a.js", b"A1")
        _, third = self.placed()
        self.assertEqual(third, first)
        self.assertEqual(len(self.sets()), 2)

    def test_sets_last_used_over_a_day_ago_are_removed(self):
        """#981: old sets are bounded; one used within a day, by a running batch at most four hours old, stays."""
        day = 24 * 60 * 60
        now = time.time()
        _, old = self.placed()
        self.change("a.js", b"A2")
        _, recent = self.placed()
        self.change("a.js", b"A3")
        _, long_ago = self.placed()
        stale = self.copies / ".tmp-crashed"
        stale.mkdir()
        (stale / "a.js").write_bytes(b"partial")
        flat = self.copies / "a.js"
        flat.write_bytes(b"flat")
        note = self.copies / "notes"
        note.mkdir()
        for path, age in ((old, day + 600), (recent, 4 * 60 * 60), (long_ago, 3 * day), (stale, day + 600),
                          (flat, 3 * day), (note, 3 * day)):
            os.utime(path, (now - age, now - age))
        self.change("a.js", b"A4")
        _, current = self.placed()
        self.assertEqual(self.sets(), sorted([recent.name, current.name, "notes"]))
        self.assertEqual(flat.read_bytes(), b"flat")
        self.change("a.js", b"A2")
        os.utime(recent, (now - 3 * day, now - 3 * day))
        _, back = self.placed()
        self.assertEqual(back, recent)
        self.assertGreater(recent.stat().st_mtime, now - 600)
        self.assertEqual(self.sets(), sorted([recent.name, current.name, "notes"]))

    def test_an_existing_set_that_does_not_hold_the_programs_is_refused_and_kept(self):
        _, directory = self.placed()
        (directory / "a.js").write_bytes(b"edited")
        done = self.place()
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertEqual(json.loads(done.stderr)["error"]["code"], "copy_failed")
        self.assertEqual(done.stdout, "")
        self.assertEqual((directory / "a.js").read_bytes(), b"edited")

    def test_flat_copies_of_the_earlier_layout_are_left_as_they_are(self):
        """A batch launched from `.program-copies/<name>/<file>` before issue 981 keeps its programs."""
        self.copies.mkdir(parents=True)
        (self.copies / "a.js").write_bytes(b"A0")
        (self.copies / "b.js").write_bytes(b"B0")
        before = self.snapshot(self.copies)
        _, directory = self.placed()
        self.assertEqual(directory.parent, self.copies)
        self.assertEqual(self.snapshot(self.copies), before)

    def test_a_copy_outlives_its_installed_program(self):
        mapping, _ = self.placed()
        shutil.rmtree(self.store)
        self.assertEqual(Path(mapping["a.js"]).read_bytes(), b"A1")

    def test_a_symlinked_set_directory_is_refused(self):
        _, directory = self.placed()
        outside = self.tmp / "elsewhere"
        shutil.move(str(directory), str(outside))
        directory.symlink_to(outside)
        before = self.snapshot(outside)
        done = self.place()
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertEqual(json.loads(done.stderr)["error"]["code"], "unsafe_destination")
        self.assertEqual(self.snapshot(outside), before)

    def test_a_linked_worktree_places_its_copies_inside_itself(self):
        subprocess.run([*GIT, "-C", str(self.repo), "commit", "-q", "--allow-empty", "-m", "init"], check=True)
        wt = self.tmp / "wt"
        subprocess.run(["git", "-C", str(self.repo), "worktree", "add", "-q", "-b", "wt", str(wt)], check=True)
        done = self.place(wt)
        self.assertEqual(done.returncode, 0, done.stderr)
        mapping = json.loads(done.stdout)
        d = Path(mapping["a.js"]).parent
        self.assertEqual(d.parent, wt / ".program-copies" / "deliver-standard")
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
