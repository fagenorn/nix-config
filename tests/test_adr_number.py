"""Tests for the adr-number command, its `next` and `renumber` subcommands (issue 1440)."""
import errno
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent_tools.delivery import adr_number, context_map_lint

REPO_ROOT = Path(__file__).resolve().parents[1]
GIT = ("git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false")
ADR_A = Path("docs/areas/a/adr")
RECORDS = "docs/areas/console/adr"
MAP = "docs/CONTEXT-MAP.md"


def run_git(root, *args):
    return subprocess.run(GIT + ("-C", str(root)) + args, check=True, capture_output=True, text=True).stdout


def init_repo(path):
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True, capture_output=True, text=True)
    return Path(path).resolve()


def write(root, rel, text):
    target = Path(root) / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def commit(root, message):
    run_git(root, "add", "-A")
    run_git(root, "commit", "-q", "-m", message)


def run_tool(*args):
    return subprocess.run([sys.executable, "-m", "agent_tools.delivery.adr_number", *map(str, args)],
                          capture_output=True, text=True, timeout=120)


def error_code(done):
    return json.loads(done.stderr)["error"]["code"]


def record(rel):
    return f"# ADR-a-{Path(rel).name[:3]} — Title\n"


def add_record(root, name, message=None):
    rel = ADR_A / name
    write(root, rel, record(rel))
    commit(root, message or f"add {name}")


def next_of(root, directory=None, base="main"):
    return run_tool("next", "--repo-root", root, "--dir", directory or root / ADR_A, "--base", base)


class NextNumberTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name).resolve()
        self.root = init_repo(self.tmp / "repo")

    def three_then_delete(self):
        for name in ("001-one.md", "002-two.md", "003-three.md"):
            add_record(self.root, name)
        run_git(self.root, "rm", "-q", str(ADR_A / "003-three.md"))
        commit(self.root, "drop 003")

    def test_a_deleted_records_number_counts_as_used(self):
        self.three_then_delete()
        done = next_of(self.root)
        self.assertEqual((done.returncode, done.stdout, done.stderr), (0, "004\n", ""))
        sha = run_git(self.root, "rev-parse", "main").strip()
        self.assertEqual(adr_number.next_number(self.root, self.root / ADR_A, sha), 4)

    def test_the_bases_history_counts(self):
        add_record(self.root, "001-one.md")
        run_git(self.root, "checkout", "-q", "-b", "feature")
        run_git(self.root, "checkout", "-q", "main")
        add_record(self.root, "005-five.md")
        run_git(self.root, "rm", "-q", str(ADR_A / "005-five.md"))
        commit(self.root, "drop 005")
        run_git(self.root, "checkout", "-q", "feature")
        add_record(self.root, "002-two.md")
        done = next_of(self.root)
        self.assertEqual((done.returncode, done.stdout), (0, "006\n"))

    def test_another_directorys_numbers_do_not_count(self):
        write(self.root, ADR_A / "001-one.md", record("001-one.md"))
        write(self.root, "docs/areas/b/adr/009-nine.md", record("009-nine.md"))
        write(self.root, "docs/areas/a/adr/old/008-eight.md", record("008-eight.md"))
        commit(self.root, "records")
        done = next_of(self.root)
        self.assertEqual((done.returncode, done.stdout), (0, "002\n"))

    def test_an_uncommitted_record_counts(self):
        add_record(self.root, "001-one.md")
        write(self.root, ADR_A / "002-two.md", record("002-two.md"))
        done = next_of(self.root)
        self.assertEqual((done.returncode, done.stdout), (0, "003\n"))

    def test_a_directory_with_no_records_starts_at_001(self):
        write(self.root, "README.md", "x\n")
        commit(self.root, "readme")
        done = next_of(self.root)
        self.assertEqual((done.returncode, done.stdout), (0, "001\n"))

    def test_a_shallow_history_is_refused_for_next(self):
        self.three_then_delete()
        shallow = self.tmp / "shallow"
        full = self.tmp / "full"
        subprocess.run(["git", "clone", "-q", "--depth", "1", "--no-single-branch", f"file://{self.root}", str(shallow)],
                       check=True, capture_output=True, text=True)
        subprocess.run(["git", "clone", "-q", f"file://{self.root}", str(full)],
                       check=True, capture_output=True, text=True)
        self.assertEqual(run_git(shallow, "rev-parse", "--is-shallow-repository").strip(), "true")
        control = next_of(full.resolve(), base="origin/main")
        self.assertEqual((control.returncode, control.stdout), (0, "004\n"))
        done = next_of(shallow.resolve(), base="origin/main")
        self.assertEqual((done.returncode, done.stdout, error_code(done)), (1, "", "shallow_history"))

    def test_numbers_past_999_are_refused(self):
        add_record(self.root, "999-last.md")
        done = next_of(self.root)
        self.assertEqual((done.returncode, done.stdout, error_code(done)), (1, "", "numbers_exhausted"))

    def test_misuse_exits_2(self):
        add_record(self.root, "001-one.md")
        cases = {
            "relative root": (("--repo-root", ".", "--dir", self.root / ADR_A, "--base", "main"), "misuse"),
            "relative dir": (("--repo-root", self.root, "--dir", str(ADR_A), "--base", "main"), "misuse"),
            "dir outside root": (("--repo-root", self.root, "--dir", self.tmp, "--base", "main"), "misuse"),
            "root not toplevel": (("--repo-root", self.root / "docs", "--dir", self.root / ADR_A, "--base", "main"),
                                  "not_a_repository_root"),
            "unknown base": (("--repo-root", self.root, "--dir", self.root / ADR_A, "--base", "nosuch"),
                             "base_unknown"),
        }
        for name, (args, code) in cases.items():
            with self.subTest(name):
                done = run_tool("next", *args)
                self.assertEqual((done.returncode, done.stdout, error_code(done)), (2, "", code))
        with self.subTest("no subcommand"):
            done = run_tool()
            self.assertEqual((done.returncode, done.stdout), (2, ""))

    def test_a_record_added_and_deleted_beside_a_treesame_merge_counts(self):
        root = self.root
        for name in ("001-one.md", "002-two.md", "003-three.md"):
            write(root, ADR_A / name, record(name))
        commit(root, "three records")
        run_git(root, "checkout", "-q", "-b", "late")
        with (root / ADR_A / "003-three.md").open("a", encoding="utf-8") as handle:
            handle.write("edit\n")
        commit(root, "late edit")
        run_git(root, "checkout", "-q", "main")
        run_git(root, "checkout", "-q", "-b", "add")
        add_record(root, "004-four.md", "add 004")
        run_git(root, "checkout", "-q", "main")
        run_git(root, "merge", "-q", "--no-ff", "--no-edit", "add")
        run_git(root, "checkout", "-q", "-b", "drop")
        run_git(root, "rm", "-q", str(ADR_A / "004-four.md"))
        commit(root, "drop 004")
        run_git(root, "checkout", "-q", "main")
        run_git(root, "merge", "-q", "--no-ff", "--no-edit", "drop")
        run_git(root, "checkout", "-q", "late")
        run_git(root, "merge", "-q", "--no-edit", "main")
        run_git(root, "checkout", "-q", "main")
        run_git(root, "merge", "-q", "--no-ff", "--no-edit", "late")
        self.assertNotIn("add 004", run_git(root, "log", "--format=%s", "HEAD", "--", "docs/areas/a/adr"))
        self.assertIn("add 004", run_git(root, "log", "--full-history", "--format=%s", "HEAD", "--", "docs/areas/a/adr"))
        done = next_of(root)
        self.assertEqual((done.returncode, done.stdout, done.stderr), (0, "005\n", ""))


def tree_state(root):
    root = Path(root)
    files = sorted((path.relative_to(root).as_posix(), path.read_bytes())
                   for path in root.rglob("*") if path.is_file() and ".git" not in path.relative_to(root).parts)
    return (run_git(root, "rev-parse", "HEAD"), run_git(root, "status", "--porcelain=v1", "-uall"),
            run_git(root, "ls-files", "-s"), files)


def make_collision(tmp, synced):
    root = init_repo(Path(tmp) / "collision")
    write(root, "docs/README.md", "# docs\n")
    write(root, MAP, "## Areas\n| Area | Context file | Gist | governs |\n|---|---|---|---|\n"
          "| Console | [CONTEXT](./areas/console/CONTEXT.md) | x | `docs/**` |\n\n"
          "## Terms\n| Term | Area |\n|---|---|\n| Thing | Console |\n")
    write(root, "docs/areas/console/CONTEXT.md", "---\narea: Console\nbudget: 200\n---\n\n**Thing**: a term\n")
    write(root, f"{RECORDS}/001-first.md", "# ADR-console-001 — First\n\nBody.\n")
    write(root, "docs/guides/notes.md", "".join(f"line {n}\n" for n in range(1, 13)))
    commit(root, "fork")
    run_git(root, "checkout", "-q", "-b", "feature")
    run_git(root, "checkout", "-q", "main")
    write(root, f"{RECORDS}/012-base-choice.md", "# ADR-console-012 — Base choice\n\nBase body.\n")
    lines = (root / "docs/guides/notes.md").read_text(encoding="utf-8").splitlines(keepends=True)
    lines.insert(2, "Base cites ADR-console-012.\n")
    write(root, "docs/guides/notes.md", "".join(lines))
    commit(root, "base record")
    run_git(root, "checkout", "-q", "feature")
    write(root, f"{RECORDS}/012-branch-choice.md",
          "# ADR-console-012 — Branch choice\n\nSee ADR-console-001.\nThis record is ADR-console-012.\n")
    with (root / "docs/guides/notes.md").open("a", encoding="utf-8") as handle:
        handle.write("Branch cites ADR-console-012.\n")
    write(root, "docs/guides/branch-guide.md", "Read ADR-console-012.\n")
    write(root, "src/note.py", "# ADR-console-012 decides this.\n")
    commit(root, "branch record")
    if synced:
        run_git(root, "merge", "-q", "--no-edit", "main")
    return root


def renumber_args(root, *extra):
    return ("renumber", "--repo-root", str(root), "--record", str(root / RECORDS / "012-branch-choice.md"),
            "--base", "main", *extra)


class RenumberTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name).resolve()

    def test_a_synced_collision_renumbers_the_branch_record(self):
        root = make_collision(self.tmp, synced=True)
        self.assertTrue(any("number 012 is already" in e for e in context_map_lint.check(root, root / MAP)))
        head = run_git(root, "rev-parse", "HEAD")
        base_bytes = (root / RECORDS / "012-base-choice.md").read_bytes()
        done = run_tool(*renumber_args(root))
        self.assertEqual((done.returncode, done.stderr), (0, ""))
        self.assertEqual(json.loads(done.stdout), {
            "from": "ADR-console-012", "to": "ADR-console-013",
            "record": "docs/areas/console/adr/013-branch-choice.md",
            "rewritten": ["docs/areas/console/adr/013-branch-choice.md", "docs/guides/branch-guide.md",
                          "docs/guides/notes.md", "src/note.py"]})
        self.assertFalse((root / RECORDS / "012-branch-choice.md").exists())
        index, errors = context_map_lint.index_records(root / "docs" / "areas", str, root)
        self.assertEqual(errors, [])
        self.assertEqual(index[("console", "013")], root / RECORDS / "013-branch-choice.md")
        self.assertEqual(index[("console", "012")], root / RECORDS / "012-base-choice.md")
        notes = (root / "docs/guides/notes.md").read_text(encoding="utf-8").splitlines()
        self.assertEqual(notes[2], "Base cites ADR-console-012.")
        self.assertEqual(notes[-1], "Branch cites ADR-console-013.")
        self.assertEqual((root / "docs/guides/branch-guide.md").read_text(encoding="utf-8"), "Read ADR-console-013.\n")
        self.assertEqual((root / "src/note.py").read_text(encoding="utf-8"), "# ADR-console-013 decides this.\n")
        self.assertEqual((root / RECORDS / "012-base-choice.md").read_bytes(), base_bytes)
        self.assertIn("RM docs/areas/console/adr/012-branch-choice.md -> docs/areas/console/adr/013-branch-choice.md",
                      run_git(root, "status", "--porcelain=v1").splitlines())
        self.assertEqual(run_git(root, "rev-parse", "HEAD"), head)
        self.assertEqual(context_map_lint.check(root, root / MAP), [])

    def test_an_unsynced_branch_takes_one_past_the_bases_number(self):
        root = make_collision(self.tmp, synced=False)
        self.assertFalse((root / RECORDS / "012-base-choice.md").exists())
        done = run_tool(*renumber_args(root))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(done.stdout)["to"], "ADR-console-013")
        self.assertEqual((root / "docs/guides/branch-guide.md").read_text(encoding="utf-8"), "Read ADR-console-013.\n")
        self.assertEqual(context_map_lint.check(root, root / MAP), [])

    def test_an_explicit_target_is_used(self):
        root = make_collision(self.tmp, synced=True)
        done = run_tool(*renumber_args(root, "--to", "020"))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(done.stdout)["record"], "docs/areas/console/adr/020-branch-choice.md")
        index, errors = context_map_lint.index_records(root / "docs" / "areas", str, root)
        self.assertEqual(errors, [])
        self.assertIn(("console", "020"), index)
        self.assertEqual(context_map_lint.check(root, root / MAP), [])

    def test_uncommitted_and_untracked_citations_are_rewritten(self):
        root = make_collision(self.tmp, synced=True)
        with (root / "docs/guides/notes.md").open("a", encoding="utf-8") as handle:
            handle.write("Draft line cites ADR-console-012.\n")
        write(root, "docs/guides/draft.md", "Draft cites ADR-console-012.\n")
        done = run_tool(*renumber_args(root))
        self.assertEqual(done.returncode, 0, done.stderr)
        notes = (root / "docs/guides/notes.md").read_text(encoding="utf-8").splitlines()
        self.assertEqual(notes[-1], "Draft line cites ADR-console-013.")
        self.assertEqual(notes[2], "Base cites ADR-console-012.")
        self.assertEqual((root / "docs/guides/draft.md").read_text(encoding="utf-8"), "Draft cites ADR-console-013.\n")
        self.assertIn("docs/guides/draft.md", json.loads(done.stdout)["rewritten"])


    def test_a_branch_added_map_link_follows_the_renamed_file(self):
        root = make_collision(self.tmp, synced=True)
        with (root / MAP).open("a", encoding="utf-8") as handle:
            handle.write("\nSee [ADR-console-012](areas/console/adr/012-branch-choice.md) and "
                         "[the base](areas/console/adr/012-base-choice.md).\n")
        done = run_tool(*renumber_args(root))
        self.assertEqual(done.returncode, 0, done.stderr)
        last = (root / MAP).read_text(encoding="utf-8").splitlines()[-1]
        self.assertEqual(last, "See [ADR-console-013](areas/console/adr/013-branch-choice.md) and "
                               "[the base](areas/console/adr/012-base-choice.md).")
        self.assertEqual(context_map_lint.check(root, root / MAP), [])

    def test_a_same_named_file_in_another_area_keeps_its_link(self):
        root = make_collision(self.tmp, synced=True)
        write(root, "docs/guides/links.md",
              "[mine](../areas/console/adr/012-branch-choice.md) "
              "[other](../areas/other/adr/012-branch-choice.md).\n")
        done = run_tool(*renumber_args(root))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual((root / "docs/guides/links.md").read_text(encoding="utf-8"),
                         "[mine](../areas/console/adr/013-branch-choice.md) "
                         "[other](../areas/other/adr/012-branch-choice.md).\n")

    def test_edits_around_a_base_citation_do_not_redirect_it_under_inter_hunk_context(self):
        root = make_collision(self.tmp, synced=True)
        run_git(root, "config", "diff.interHunkContext", "1")
        lines = (root / "docs/guides/notes.md").read_text(encoding="utf-8").splitlines(keepends=True)
        self.assertEqual(lines[2], "Base cites ADR-console-012.\n")
        lines[1], lines[3] = "edited above\n", "edited below\n"
        write(root, "docs/guides/notes.md", "".join(lines))
        done = run_tool(*renumber_args(root))
        self.assertEqual(done.returncode, 0, done.stderr)
        notes = (root / "docs/guides/notes.md").read_text(encoding="utf-8").splitlines()
        self.assertEqual(notes[1:4], ["edited above", "Base cites ADR-console-012.", "edited below"])
        self.assertEqual(notes[-1], "Branch cites ADR-console-013.")

    def test_a_longer_citation_with_the_same_prefix_is_not_rewritten(self):
        root = make_collision(self.tmp, synced=True)
        write(root, "docs/guides/draft.md",
              "ADR-console-012-001 stays, ADR-console-012 moves, ADR-console-0123 stays.\n")
        done = run_tool(*renumber_args(root))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual((root / "docs/guides/draft.md").read_text(encoding="utf-8"),
                         "ADR-console-012-001 stays, ADR-console-013 moves, ADR-console-0123 stays.\n")

    def test_a_changed_latin_1_file_is_left_alone(self):
        root = make_collision(self.tmp, synced=True)
        legacy = "docs/guides/legacy.txt"
        (root / legacy).write_bytes(b"caf\xe9 ADR-console-012\n")
        commit(root, "latin-1 file")
        with (root / legacy).open("ab") as handle:
            handle.write(b"caf\xe9 again\n")
        before = (root / legacy).read_bytes()
        done = run_tool(*renumber_args(root))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual((root / legacy).read_bytes(), before)
        self.assertNotIn(legacy, json.loads(done.stdout)["rewritten"])
        self.assertEqual((root / "docs/guides/branch-guide.md").read_text(encoding="utf-8"), "Read ADR-console-013.\n")

    def test_a_full_disk_leaves_the_draft_and_the_tree_as_they_were(self):
        root = make_collision(self.tmp, synced=True)
        write(root, "docs/guides/draft.md", "Draft cites ADR-console-012.\n")
        before = tree_state(root)
        full = OSError(errno.ENOSPC, os.strerror(errno.ENOSPC))
        with mock.patch.object(adr_number.os, "write", side_effect=full):
            with self.assertRaises(adr_number.NumberRefusal) as caught:
                adr_number.renumber(root, root / RECORDS / "012-branch-choice.md", "main", None)
        self.assertEqual((caught.exception.code, caught.exception.exit_code), ("write_failed", 1))
        self.assertEqual(tree_state(root), before)

    def test_a_hard_linked_draft_is_replaced_never_written_through(self):
        root = make_collision(self.tmp, synced=True)
        outside = self.tmp / "outside.md"
        outside.write_text("Outside cites ADR-console-012.\n", encoding="utf-8")
        os.link(outside, root / "docs/guides/linked.md")
        done = run_tool(*renumber_args(root))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(outside.read_text(encoding="utf-8"), "Outside cites ADR-console-012.\n")
        self.assertEqual((root / "docs/guides/linked.md").read_text(encoding="utf-8"),
                         "Outside cites ADR-console-013.\n")


class RenumberRefusalTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name).resolve()

    def refused(self, root, args, code, exit_code=1):
        before = tree_state(root)
        done = run_tool(*args)
        self.assertEqual((done.returncode, done.stdout, error_code(done)), (exit_code, "", code))
        self.assertEqual(tree_state(root), before)

    def test_a_target_number_ever_used_is_refused(self):
        root = make_collision(self.tmp, synced=False)
        run_git(root, "checkout", "-q", "main")
        write(root, f"{RECORDS}/005-gone.md", "# ADR-console-005 — Gone\n")
        commit(root, "add 005")
        run_git(root, "rm", "-q", f"{RECORDS}/005-gone.md")
        commit(root, "drop 005")
        run_git(root, "checkout", "-q", "feature")
        run_git(root, "merge", "-q", "--no-edit", "main")
        for target in ("005", "012", "001"):
            with self.subTest(target):
                self.refused(root, renumber_args(root, "--to", target), "number_used")

    def test_a_missing_record_is_refused(self):
        root = make_collision(self.tmp, synced=True)
        args = ("renumber", "--repo-root", str(root), "--record", str(root / RECORDS / "014-none.md"),
                "--base", "main")
        self.refused(root, args, "record_missing")

    def test_a_shallow_history_is_refused(self):
        root = make_collision(self.tmp, synced=True)
        shallow = self.tmp / "shallow"
        subprocess.run(["git", "clone", "-q", "--depth", "1", "--no-single-branch", "--branch", "feature",
                        f"file://{root}", str(shallow)], check=True, capture_output=True, text=True)
        shallow = shallow.resolve()
        self.assertEqual(run_git(shallow, "rev-parse", "--is-shallow-repository").strip(), "true")
        args = ("renumber", "--repo-root", str(shallow), "--record", str(shallow / RECORDS / "012-branch-choice.md"),
                "--base", "origin/main")
        self.refused(shallow, args, "shallow_history")

    def test_an_untracked_record_is_refused(self):
        root = make_collision(self.tmp, synced=True)
        write(root, f"{RECORDS}/015-loose.md", "# ADR-console-015 — Loose\n")
        args = ("renumber", "--repo-root", str(root), "--record", str(root / RECORDS / "015-loose.md"),
                "--base", "main")
        self.refused(root, args, "record_untracked")

    def test_a_header_that_does_not_name_the_record_is_refused(self):
        root = make_collision(self.tmp, synced=True)
        write(root, f"{RECORDS}/014-odd.md", "# ADR-console-016 — Odd\n")
        commit(root, "odd record")
        args = ("renumber", "--repo-root", str(root), "--record", str(root / RECORDS / "014-odd.md"),
                "--base", "main")
        self.refused(root, args, "header_mismatch")

    def test_a_record_the_base_published_is_refused(self):
        root = make_collision(self.tmp, synced=True)
        base_record = root / RECORDS / "012-base-choice.md"
        args = ("renumber", "--repo-root", str(root), "--record", str(base_record), "--base", "main")
        self.refused(root, args, "record_published")

    def test_a_record_at_the_merge_base_is_refused_even_when_the_base_dropped_it(self):
        root = make_collision(self.tmp, synced=True)
        run_git(root, "checkout", "-q", "main")
        run_git(root, "rm", "-q", f"{RECORDS}/001-first.md")
        commit(root, "drop 001")
        run_git(root, "checkout", "-q", "feature")
        args = ("renumber", "--repo-root", str(root), "--record", str(root / RECORDS / "001-first.md"),
                "--base", "main")
        self.refused(root, args, "record_published")

    def test_a_malformed_target_is_misuse(self):
        root = make_collision(self.tmp, synced=True)
        for target in ("13", "000", "abc", "\u0660\u0660\u0660", "\uff10\uff10\uff11"):
            with self.subTest(target):
                self.refused(root, renumber_args(root, "--to", target), "misuse", exit_code=2)


class RenumberRangeTest(unittest.TestCase):
    def test_a_target_outside_1_to_999_is_refused_inside_renumber(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_collision(Path(tmp).resolve(), synced=True)
            for target in (0, 1000):
                with self.subTest(target):
                    with self.assertRaises(adr_number.NumberRefusal) as caught:
                        adr_number.renumber(root, root / RECORDS / "012-branch-choice.md", "main", target)
                    self.assertEqual((caught.exception.code, caught.exception.exit_code), ("misuse", 2))


class CommandTableTest(unittest.TestCase):
    def test_the_command_table_runs_the_module(self):
        table = (REPO_ROOT / "lib/agent-tools.nix").read_text(encoding="utf-8")
        self.assertIsNotNone(re.search(r'^\s*"adr-number" = "delivery\.adr_number";$', table, re.M))
        self.assertEqual(adr_number.build_parser().prog, "adr-number")
        done = run_tool("--help")
        self.assertEqual(done.returncode, 0)
        self.assertTrue(done.stdout.startswith("usage: adr-number "), done.stdout)


if __name__ == "__main__":
    unittest.main()
