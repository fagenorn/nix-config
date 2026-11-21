"""Tests for the adr-number command, its `next` subcommand (issue 1440)."""
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from agent_tools.delivery import adr_number

REPO_ROOT = Path(__file__).resolve().parents[1]
GIT = ("git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false")
ADR_A = Path("docs/areas/a/adr")


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
