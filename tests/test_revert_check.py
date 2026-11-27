"""Contract tests for `revert-check`: the new tests of a change that still pass at the merge base.

Each case builds a real git repository from the engine fixture project and runs the command (or its
`check` function) against a worktree of it; no stand-in is involved.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from agent_tools.delivery.engine_commands import PLATFORM_WALL_SECONDS
from agent_tools.delivery.revert_check import (
    BUDGET_SECONDS, TEST_SECONDS, WATCHER, case_ids, check, main, seal_argv)

TIER = "integration"  # every case starts git and the tests as processes

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = REPO_ROOT / "tests/fixtures/engine-fixture-project"

FAREWELL_PATH = "fixture/farewell.py"
FAREWELL_SOURCE = 'def farewell(name: str) -> str:\n    return f"Goodbye, {name}."\n'
FAREWELL_CHECK_PATH = "checks/check_farewell.py"
FAREWELL_CHECK = (
    "import unittest\n\n"
    "from fixture.farewell import farewell\n\n\n"
    "class FarewellCheck(unittest.TestCase):\n"
    "    def test_farewell_says_goodbye(self):\n"
    '        self.assertEqual(farewell("Ada"), "Goodbye, Ada.")\n')
GREET_CHECK_PATH = "checks/check_greet.py"
GREET_CHECK_PLUS = (FIXTURE / GREET_CHECK_PATH).read_text().replace(
    "\n\nif __name__",
    '\n    def test_greet_keeps_the_name(self):\n        self.assertIn("Ada", greet("Ada"))\n\n\nif __name__')
PROOF_CHANGE = {FAREWELL_PATH: FAREWELL_SOURCE, FAREWELL_CHECK_PATH: FAREWELL_CHECK,
                GREET_CHECK_PATH: GREET_CHECK_PLUS}
FAREWELL_ID = "checks.check_farewell.FarewellCheck.test_farewell_says_goodbye"
GREET_ID = "checks.check_greet.GreetCheck.test_greet_keeps_the_name"
BRANCH = "issue-1-topic"
SLEEPER = ("import os\nimport subprocess\nimport sys\nimport time\nimport unittest\n\n\nclass SleepCheck(unittest.TestCase):\n"
           "    def test_sleeps(self):\n"
           "        service = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], start_new_session=True)\n"
           "        open({marker!r}, 'w').write(f'{{os.getpid()}} {{service.pid}}\\n')\n        time.sleep(30)\n")
SERVICE = ("import os\nimport subprocess\nimport sys\nimport time\nimport unittest\n\n\nclass ServiceCheck(unittest.TestCase):\n"
           "    def test_starts_a_service(self):\n"
           "        service = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], start_new_session=True)\n"
           "        open({marker!r}, 'w').write(str(service.pid) + '\\n')\n        time.sleep(60)\n")
WRITER = (
    "import unittest\n\n\nclass WriterCheck(unittest.TestCase):\n    def test_writes_outside(self):\n"
    "        for target in {targets!r}:\n            try:\n                open(target, 'w').write('x')\n"
            "            except OSError:\n                pass\n")
READONLY = (
    "import os\nimport unittest\n\n\nclass RoCheck(unittest.TestCase):\n"
    "    def test_a_leaves(self):\n        os.makedirs('ro/sub')\n        open('ro/sub/x', 'w').write('x')\n"
    "        os.chmod('ro/sub', 0o555)\n\n"
    "    def test_b_sees_clean(self):\n        self.assertFalse(os.path.exists('ro'))\n")
BOM_CHECK ="import unittest\n\n\nclass BomCheck(unittest.TestCase):\n    def test_passes(self):\n        self.assertTrue(True)\n"
STATEFUL = (
    "import os\nimport unittest\n\n\nclass StateCheck(unittest.TestCase):\n"
    "    def test_a_writes(self):\n        os.makedirs('data', exist_ok=True)\n"
    "        open('data/flag.txt', 'w').write('x')\n\n"
    "    def test_b_needs(self):\n        self.assertTrue(os.path.exists('data/flag.txt'))\n")


class FixtureRepository:
    """A `main` checkout, its bare `origin` and the run's worktree on `issue-1-topic`."""

    def __init__(self, test_case: unittest.TestCase, base_files: dict[str, str] | None = None) -> None:
        directory = tempfile.TemporaryDirectory()
        test_case.addCleanup(directory.cleanup)
        self.tmp = Path(directory.name).resolve()
        self.main = self.tmp / "main"
        self.origin = self.tmp / "origin.git"
        self.worktree = self.tmp / "wt"
        self.env = {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1",
                    "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@example.com",
                    "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@example.com"}
        self.main.mkdir()
        self.git(self.main, "init", "-q", "-b", "main")
        for name in ("fixture", "checks"):
            shutil.copytree(FIXTURE / name, self.main / name, ignore=shutil.ignore_patterns("__pycache__"))
        for path, text in (base_files or {}).items():
            self.write(self.main, path, text)
        self.commit_in(self.main, "base")
        self.git(self.tmp, "init", "-q", "--bare", "-b", "main", str(self.origin))
        self.git(self.main, "remote", "add", "origin", str(self.origin))
        self.git(self.main, "push", "-q", "origin", "main")
        self.git(self.main, "fetch", "-q", "origin")
        self.git(self.main, "worktree", "add", "-q", "-b", BRANCH, str(self.worktree), "main")

    def git(self, cwd: Path, *args: str) -> str:
        done = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, env=self.env)
        if done.returncode:
            raise AssertionError(f"git {args}: {done.stderr}")
        return done.stdout

    @staticmethod
    def write(root: Path, path: str, text: str) -> None:
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(text)

    def commit_in(self, root: Path, message: str) -> None:
        self.git(root, "add", "-A")
        self.git(root, "-c", "commit.gpgsign=false", "commit", "-q", "-m", message)

    def commit(self, files: dict[str, str]) -> None:
        for path, text in files.items():
            self.write(self.worktree, path, text)
        self.commit_in(self.worktree, "change")

    def run(self, env_extra: dict[str, str], branch: str = "main") -> tuple[int, dict]:
        done = subprocess.run(
            [sys.executable, "-m", "agent_tools.delivery.revert_check", "--worktree-path",
             str(self.worktree), "--integration-branch", branch],
            capture_output=True, text=True, cwd=self.worktree,
            env={**self.env, "PYTHONPATH": str(REPO_ROOT / "python"), **env_extra})
        self.stdout = done.stdout
        return done.returncode, json.loads(done.stdout) if done.stdout else {}

    def snapshot(self) -> tuple[str, str, str]:
        digest = hashlib.sha256()
        for path in sorted(self.worktree.rglob("*")):
            status = path.lstat()
            if stat.S_ISLNK(status.st_mode):
                body = b"link " + os.fsencode(os.readlink(path))
            elif stat.S_ISREG(status.st_mode):
                body = b"file " + path.read_bytes()
            else:
                body = b"other"
            digest.update(str(path.relative_to(self.worktree)).encode() + b"\0"
                          + f"{stat.S_IMODE(status.st_mode):o}".encode() + b"\0" + body + b"\0")
        return (digest.hexdigest(), self.git(self.main, "rev-parse", f"refs/heads/{BRANCH}"),
                self.git(self.main, "worktree", "list", "--porcelain"))


def eventually(condition, seconds: float = 20) -> bool:
    deadline = time.monotonic() + seconds
    while not condition():
        if time.monotonic() > deadline:
            return False
        time.sleep(0.05)
    return True


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def scratch_directory(test_case: unittest.TestCase) -> str:
    directory = tempfile.TemporaryDirectory()
    test_case.addCleanup(directory.cleanup)
    return directory.name


def regular_file(test_case: unittest.TestCase) -> str:
    directory = scratch_directory(test_case)
    path = os.path.join(directory, "not-a-directory")
    Path(path).write_text("x")
    return path


class CommandTest(unittest.TestCase):
    def test_only_the_new_test_that_still_passes_without_its_source_is_listed(self):
        repository = FixtureRepository(self)
        repository.commit(PROOF_CHANGE)
        scratch = scratch_directory(self)
        code, result = repository.run({"REVERT_CHECK_SCRATCH": scratch})
        self.assertEqual(code, 0)
        self.assertEqual(result, {
            "verdict": "ok", "reason": "",
            "base": repository.git(repository.main, "rev-parse", "origin/main").strip(),
            "head": repository.git(repository.worktree, "rev-parse", "HEAD").strip(),
            "new_tests": [FAREWELL_ID, GREET_ID], "still_passing": [GREET_ID]})
        self.assertEqual(len(repository.stdout.splitlines()), 1)

    def test_the_run_worktree_and_branch_are_unchanged_and_no_scratch_worktree_is_left(self):
        repository = FixtureRepository(self)
        repository.commit(PROOF_CHANGE)
        hook = repository.main / ".git/hooks/post-checkout"
        hook.write_text(f"#!/bin/sh\ntouch '{repository.tmp / 'hooked'}'\n")
        hook.chmod(0o755)
        index_hook = repository.main / ".git/hooks/post-index-change"
        index_hook.write_text(f"#!/bin/sh\ntouch '{repository.tmp / 'index-hooked'}'\necho hooked >> {FAREWELL_PATH}\n")
        index_hook.chmod(0o755)
        scratch = scratch_directory(self)
        before = repository.snapshot()
        code, result = repository.run({"REVERT_CHECK_SCRATCH": scratch})
        self.assertEqual(code, 0)
        self.assertTrue(result["still_passing"])
        self.assertEqual(repository.snapshot(), before)
        self.assertEqual(os.listdir(scratch), [])
        self.assertFalse((repository.tmp / "hooked").exists())
        self.assertFalse((repository.tmp / "index-hooked").exists())
        listed = [line for line in before[2].splitlines() if line.startswith("worktree ")]
        self.assertEqual(sorted(listed), sorted(f"worktree {p}" for p in (repository.main, repository.worktree)))

    def test_the_outcome_is_ok_when_no_test_is_new_or_the_check_cannot_run(self):
        with self.subTest("no new test"):
            repository = FixtureRepository(self)
            repository.commit({FAREWELL_PATH: FAREWELL_SOURCE})
            code, result = repository.run({"REVERT_CHECK_SCRATCH": regular_file(self)})
            self.assertEqual(code, 0)
            self.assertEqual((result["verdict"], result["new_tests"], result["still_passing"], result["reason"]),
                             ("ok", [], [], ""))
        with self.subTest("scratch cannot be made"):
            repository = FixtureRepository(self)
            repository.commit(PROOF_CHANGE)
            code, result = repository.run({"REVERT_CHECK_SCRATCH": regular_file(self)})
            self.assertEqual(code, 0)
            self.assertEqual(result["verdict"], "ok")
            self.assertEqual(result["still_passing"], [])
            self.assertEqual(result["new_tests"], [FAREWELL_ID, GREET_ID])
            self.assertTrue(result["reason"].startswith("the scratch worktree could not be made: "), result["reason"])
        with self.subTest("merge base unreadable"):
            repository = FixtureRepository(self)
            repository.commit(PROOF_CHANGE)
            code, result = repository.run({"REVERT_CHECK_SCRATCH": scratch_directory(self)}, "no-such-branch")
            self.assertEqual(code, 0)
            self.assertEqual((result["verdict"], result["new_tests"], result["still_passing"]), ("ok", [], []))
            self.assertTrue(result["reason"].startswith(
                "the merge base of HEAD and origin/no-such-branch could not be read"), result["reason"])


class CheckTest(unittest.TestCase):
    def test_case_ids_follow_in_file_bases_to_testcase(self):
        source = (
            "import unittest\n\n"
            "class A(unittest.TestCase):\n    def test_a(self): pass\n    def helper(self): pass\n\n"
            "class B(A):\n    def test_b(self): pass\n\n"
            "class C(TestCase):\n    async def test_c(self): pass\n\n"
            "class D(object):\n    def test_d(self): pass\n\n"
            "def test_e(): pass\n")
        self.assertEqual(case_ids(source), frozenset({"A.test_a", "B.test_b", "C.test_c"}))
        self.assertEqual(case_ids("def broken(:"), frozenset())

    def test_case_ids_resolve_an_aliased_testcase_import(self):
        source = (
            "from unittest import TestCase as Case\nfrom unittest.case import TestCase\n\n"
            "class Sample(Case):\n    def test_a(self): pass\n\n"
            "class Child(Sample):\n    def test_b(self): pass\n\n"
            "class Direct(TestCase):\n    def test_c(self): pass\n")
        self.assertEqual(case_ids(source), frozenset({"Sample.test_a", "Child.test_b", "Direct.test_c"}))
        self.assertEqual(case_ids("from other import Thing as Case\n\nclass S(Case):\n    def test_a(self): pass\n"),
                         frozenset())

    def test_case_ids_follow_an_imported_base_into_its_file(self):
        files = {
            "tests/base.py": "import unittest\n\nclass Scenario(unittest.TestCase): pass\n\nclass Plain: pass\n",
            "tests/mid.py": "from tests.base import Scenario as S\n\nclass Mid(S): pass\n",
            "tests/loop_a.py": "from tests.loop_b import B\n\nclass A(B): pass\n",
            "tests/loop_b.py": "from tests.loop_a import A\n\nclass B(A): pass\n",
            "tests/pkg/__init__.py": "from tests.base import Scenario\n\nclass Packaged(Scenario): pass\n"}
        source = (
            "from tests.mid import Mid\nfrom tests.base import Plain\nfrom .base import Scenario\n"
            "from tests.loop_a import A\nfrom tests.missing import Gone\nfrom tests.pkg import Packaged\n"
            "from tests.nowhere import Missing\n\n"
            "class One(Mid):\n    def test_one(self): pass\n\n"
            "class Two(Plain):\n    def test_two(self): pass\n\n"
            "class Three(Scenario):\n    def test_three(self): pass\n\n"
            "class Four(A):\n    def test_four(self): pass\n\n"
            "class Five(Gone):\n    def test_five(self): pass\n\n"
            "class Six(Packaged):\n    def test_six(self): pass\n")
        self.assertEqual(case_ids(source, "tests/test_x.py", files.get),
                         frozenset({"One.test_one", "Three.test_three", "Six.test_six"}))
        self.assertEqual(case_ids(source, "tests/test_x.py"), frozenset())

    def test_a_new_test_of_a_class_with_an_imported_testcase_base_is_listed_and_run(self):
        repository = FixtureRepository(self, {
            "checks/base_scenario.py": "import unittest\n\n\nclass Scenario(unittest.TestCase):\n    pass\n"})
        repository.commit({"checks/check_sub.py": (
            "from checks.base_scenario import Scenario\n\n\nclass SubCheck(Scenario):\n"
            "    def test_sub(self):\n        self.assertTrue(True)\n")})
        result = check(str(repository.worktree), "main", scratch_root=scratch_directory(self), environ=os.environ)
        self.assertEqual(result["new_tests"], ["checks.check_sub.SubCheck.test_sub"])
        self.assertEqual(result["still_passing"], result["new_tests"])
        self.assertEqual(result["reason"], "")

    def test_a_symlink_of_the_merge_base_into_the_run_worktree_is_never_written_through(self):
        repository = FixtureRepository(self, {"data/out.txt": "original\n"})
        os.makedirs(repository.main / "fixtures")
        os.symlink(repository.worktree / "data/out.txt", repository.main / "fixtures/output")
        repository.commit_in(repository.main, "an absolute link into the run worktree")
        repository.git(repository.main, "push", "-q", "origin", "main")
        repository.git(repository.main, "fetch", "-q", "origin")
        repository.git(repository.worktree, "merge", "-q", "--ff-only", "main")
        repository.commit({"checks/check_writer.py": (
            "import unittest\n\n\nclass WriterCheck(unittest.TestCase):\n"
            "    def test_writes(self):\n        open('fixtures/output', 'w').write('overwritten\\n')\n")})
        before = repository.snapshot()
        result = check(str(repository.worktree), "main", scratch_root=scratch_directory(self), environ=os.environ)
        self.assertEqual(result["still_passing"], ["checks.check_writer.WriterCheck.test_writes"])
        self.assertEqual((repository.worktree / "data/out.txt").read_text(), "original\n")
        self.assertEqual(repository.snapshot(), before)

    def test_a_merge_base_with_no_file_still_runs_the_independent_test(self):
        repository = FixtureRepository(self)
        repository.git(repository.main, "rm", "-rq", "fixture", "checks")
        repository.commit_in(repository.main, "empty")
        repository.git(repository.main, "push", "-q", "origin", "main")
        repository.git(repository.main, "fetch", "-q", "origin")
        repository.git(repository.worktree, "merge", "-q", "--ff-only", "main")
        self.assertEqual(repository.git(repository.worktree, "ls-files").strip(), "")
        repository.commit({FAREWELL_PATH: FAREWELL_SOURCE, "checks/check_mixed.py": (
            "import unittest\n\n\nclass MixedCheck(unittest.TestCase):\n"
            "    def test_needs_source(self):\n        from fixture.farewell import farewell\n"
            "        self.assertEqual(farewell('Ada'), 'Goodbye, Ada.')\n\n"
            "    def test_independent(self):\n        self.assertTrue(True)\n")})
        result = check(str(repository.worktree), "main", scratch_root=scratch_directory(self), environ=os.environ)
        self.assertEqual(result["new_tests"], ["checks.check_mixed.MixedCheck.test_independent",
                                               "checks.check_mixed.MixedCheck.test_needs_source"])
        self.assertEqual(result["still_passing"], ["checks.check_mixed.MixedCheck.test_independent"])
        self.assertEqual(result["reason"], "")

    def test_a_test_may_run_git_in_the_checkout_of_the_merge_base(self):
        repository = FixtureRepository(self, {"README.md": "read me\n"})
        repository.commit({"checks/check_git.py": (
            "import subprocess\nimport unittest\n\n\nclass GitCheck(unittest.TestCase):\n"
            "    def test_tracks_the_readme(self):\n"
            "        subprocess.run(['git', 'ls-files', '--error-unmatch', 'README.md'], check=True)\n"
            "        subprocess.run(['git', 'cat-file', '-e', 'HEAD:README.md'], check=True)\n")})
        before = repository.snapshot()
        result = check(str(repository.worktree), "main", scratch_root=scratch_directory(self), environ=os.environ)
        self.assertEqual(result["still_passing"], ["checks.check_git.GitCheck.test_tracks_the_readme"])
        self.assertEqual(repository.snapshot(), before)

    def test_the_reverted_package_root_wins_and_the_run_worktree_is_not_imported(self):
        repository = FixtureRepository(self, {
            "src/pkg/__init__.py": "", "src/pkg/calc.py": "def add(a, b):\n    return a + b\n"})
        worktree = str(repository.worktree)
        repository.commit({
            "src/pkg/calc.py": "def add(a, b):\n    return a + b\n\n\ndef double(a):\n    return 2 * a\n",
            "src/extra/__init__.py": "", "src/extra/word.py": 'WORD = "w"\n',
            "checks/check_calc.py": (
                "import unittest\n\n\nclass CalcCheck(unittest.TestCase):\n"
                "    def test_add(self):\n        from pkg.calc import add\n        self.assertEqual(add(1, 2), 3)\n\n"
                "    def test_double(self):\n        from pkg.calc import double\n        self.assertEqual(double(2), 4)\n"),
            "checks/check_extra.py": (
                "import unittest\n\n\nclass ExtraCheck(unittest.TestCase):\n"
                "    def test_word(self):\n        from extra.word import WORD\n        self.assertEqual(WORD, 'w')\n")})
        before = repository.snapshot()
        result = check(worktree, "main", scratch_root=scratch_directory(self), environ={
            **os.environ, "PYTHONPATH": f"{worktree}/src{os.pathsep}{REPO_ROOT / 'python'}"})
        self.assertEqual(result["still_passing"], ["checks.check_calc.CalcCheck.test_add"])
        self.assertEqual(len(result["new_tests"]), 3)
        self.assertEqual(repository.snapshot(), before)

    def test_a_package_root_does_not_shadow_a_top_level_name_of_the_scratch_root(self):
        repository = FixtureRepository(self, {
            "tests/check_old.py": "", "nested/tests/__init__.py": "", "nested/tests/helper.py": "VALUE = 1\n"})
        repository.commit({"tests/check_new.py": (
            "import unittest\n\n\nclass NewCheck(unittest.TestCase):\n"
            "    def test_new(self):\n        self.assertTrue(True)\n")})
        result = check(str(repository.worktree), "main", scratch_root=scratch_directory(self),
                       environ=os.environ)
        self.assertEqual(result["new_tests"], ["tests.check_new.NewCheck.test_new"])
        self.assertEqual(result["still_passing"], ["tests.check_new.NewCheck.test_new"])

    def test_a_symlink_of_the_merge_base_is_never_written_through(self):
        repository = FixtureRepository(self)
        linked = repository.worktree / "linked"
        repository.git(repository.main, "rm", "-rq", "checks")
        os.symlink(linked, repository.main / "checks")
        repository.commit_in(repository.main, "checks becomes a link")
        repository.git(repository.main, "push", "-q", "origin", "main")
        repository.git(repository.main, "fetch", "-q", "origin")
        repository.git(repository.worktree, "merge", "-q", "--ff-only", "main")
        repository.write(repository.worktree, "linked/check_greet.py", "UNCOMMITTED EDIT\n")
        repository.git(repository.worktree, "rm", "-q", "checks")
        repository.write(repository.worktree, GREET_CHECK_PATH, GREET_CHECK_PLUS)
        repository.git(repository.worktree, "add", "checks")
        repository.git(repository.worktree, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "checks is a directory")
        before = repository.snapshot()
        result = check(str(repository.worktree), "main", scratch_root=scratch_directory(self), environ=os.environ)
        self.assertEqual(result["still_passing"], [])
        self.assertIn("symlink", result["reason"])
        self.assertEqual(repository.snapshot(), before)
        self.assertEqual((linked / "check_greet.py").read_text(), "UNCOMMITTED EDIT\n")

    def test_an_unrelated_worktree_whose_path_is_gone_stays_registered(self):
        repository = FixtureRepository(self)
        repository.commit(PROOF_CHANGE)
        other = repository.tmp / "other"
        repository.git(repository.main, "worktree", "add", "-q", "--detach", str(other), "main")
        other.rename(repository.tmp / "unmounted")
        result = check(str(repository.worktree), "main", scratch_root=scratch_directory(self), environ=os.environ)
        self.assertEqual(result["still_passing"], [GREET_ID])
        self.assertIn(f"worktree {other}", repository.git(repository.main, "worktree", "list", "--porcelain"))

    def test_an_engine_stop_during_a_test_leaves_no_test_and_no_scratch_behind(self):
        repository = FixtureRepository(self)
        marker = repository.tmp / "test-pid"
        repository.commit({"checks/check_sleep.py": SLEEPER.format(marker=str(marker))})
        scratch = scratch_directory(self)
        before = repository.snapshot()
        checker = subprocess.Popen(
            [sys.executable, "-m", "agent_tools.delivery.revert_check", "--worktree-path", str(repository.worktree),
             "--integration-branch", "main"],
            cwd=repository.worktree, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env={**repository.env, "PYTHONPATH": str(REPO_ROOT / "python"), "REVERT_CHECK_SCRATCH": scratch})
        self.addCleanup(checker.wait)
        self.addCleanup(lambda: checker.poll() is None and os.killpg(checker.pid, signal.SIGKILL))
        self.assertTrue(eventually(lambda: marker.exists() and marker.read_text().endswith("\n")))
        pids = [int(word) for word in marker.read_text().split()]
        for pid in pids:
            self.addCleanup(lambda pid=pid: alive(pid) and os.kill(pid, signal.SIGKILL))
        os.killpg(checker.pid, signal.SIGKILL)
        checker.wait()
        for pid in pids:
            self.assertTrue(eventually(lambda pid=pid: not alive(pid)), "the test or its service outlived the checker")
        self.assertTrue(eventually(lambda: os.listdir(scratch) == []), os.listdir(scratch))
        self.assertEqual(repository.snapshot(), before)

    def test_a_watcher_whose_checker_is_already_gone_runs_no_test(self):
        directory = Path(scratch_directory(self))
        marker = directory / "ran"
        (directory / "probe_ran.py").write_text(
            "import unittest\n\n\nclass Probe(unittest.TestCase):\n    def test_ran(self):\n"
            f"        open({str(marker)!r}, 'w').write('x')\n")
        gone = subprocess.Popen([sys.executable, "-c", "pass"])
        gone.wait()
        watcher = subprocess.Popen(
            [sys.executable, "-I", "-c", WATCHER, "probe_ran.Probe.test_ran", str(gone.pid)], cwd=directory,
            env={**os.environ, "PYTHONPATH": str(directory)}, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, start_new_session=True)
        self.addCleanup(lambda: watcher.poll() is None and os.killpg(watcher.pid, signal.SIGKILL))
        self.assertNotEqual(watcher.wait(timeout=20), 0)
        time.sleep(1)
        self.assertFalse(marker.exists(), "the test ran although its checker was already gone")

    def test_an_engine_stop_while_the_scratch_is_being_filled_leaves_no_scratch_behind(self):
        repository = FixtureRepository(self)
        repository.commit(PROOF_CHANGE)
        scratch = scratch_directory(self)
        stub = Path(scratch_directory(self))
        marker = stub / "filling"
        real_git = shutil.which("git", path=repository.env.get("PATH"))
        (stub / "git").write_text(
            "#!/bin/sh\nfor argument in \"$@\"; do\n  if [ \"$argument\" = checkout-index ]; then\n"
            f"    echo x > {marker}\n    sleep 30\n  fi\ndone\nexec {real_git} \"$@\"\n")
        (stub / "git").chmod(0o755)
        checker = subprocess.Popen(
            [sys.executable, "-m", "agent_tools.delivery.revert_check", "--worktree-path", str(repository.worktree),
             "--integration-branch", "main"],
            cwd=repository.worktree, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env={**repository.env, "PYTHONPATH": str(REPO_ROOT / "python"), "REVERT_CHECK_SCRATCH": scratch,
                 "PATH": f"{stub}{os.pathsep}{repository.env.get('PATH', '')}"})
        self.addCleanup(checker.wait)
        self.addCleanup(lambda: checker.poll() is None and os.killpg(checker.pid, signal.SIGKILL))
        self.assertTrue(eventually(lambda: marker.exists()))
        self.assertTrue(os.listdir(scratch), "the scratch directory was not made before the checkout")
        os.killpg(checker.pid, signal.SIGKILL)
        checker.wait()
        self.assertTrue(eventually(lambda: os.listdir(scratch) == []), os.listdir(scratch))

    def test_bytecode_goes_to_the_scratch_whatever_the_inherited_cache_prefix(self):
        repository = FixtureRepository(self)
        repository.commit(PROOF_CHANGE)
        before = repository.snapshot()
        result = check(str(repository.worktree), "main", scratch_root=scratch_directory(self), environ={
            **os.environ, "PYTHONPYCACHEPREFIX": str(repository.worktree / "pycache")})
        self.assertEqual(result["still_passing"], [GREET_ID])
        self.assertFalse((repository.worktree / "pycache").exists())
        self.assertEqual(repository.snapshot(), before)

    def test_each_test_runs_on_a_fresh_checkout_of_the_merge_base(self):
        repository = FixtureRepository(self)
        repository.commit({"checks/check_state.py": STATEFUL, "data/flag.txt": "x"})
        result = check(str(repository.worktree), "main", scratch_root=scratch_directory(self), environ=os.environ)
        self.assertEqual(result["new_tests"], ["checks.check_state.StateCheck.test_a_writes",
                                               "checks.check_state.StateCheck.test_b_needs"])
        self.assertEqual(result["still_passing"], ["checks.check_state.StateCheck.test_a_writes"])

    def test_a_module_with_a_byte_order_mark_is_discovered(self):
        repository = FixtureRepository(self)
        (repository.worktree / FAREWELL_CHECK_PATH).write_bytes(b"\xef\xbb\xbf" + BOM_CHECK.encode())
        repository.commit_in(repository.worktree, "bom")
        result = check(str(repository.worktree), "main", scratch_root=scratch_directory(self), environ=os.environ)
        self.assertEqual(result["new_tests"], ["checks.check_farewell.BomCheck.test_passes"])
        self.assertEqual(result["still_passing"], result["new_tests"])
        self.assertEqual(result["reason"], "")

    def test_a_regular_package_of_the_inherited_path_does_not_shadow_the_checks_directory(self):
        repository = FixtureRepository(self)
        repository.commit(PROOF_CHANGE)
        other = Path(scratch_directory(self))
        repository.write(other, "checks/__init__.py", "")
        result = check(str(repository.worktree), "main", scratch_root=scratch_directory(self), environ={
            **os.environ, "PYTHONPATH": f"{other}{os.pathsep}{REPO_ROOT / 'python'}"})
        self.assertEqual(result["new_tests"], [FAREWELL_ID, GREET_ID])
        self.assertEqual(result["still_passing"], [GREET_ID])

    def test_a_head_blob_git_cannot_read_is_the_reason_not_a_silent_skip(self):
        repository = FixtureRepository(self)
        repository.commit({GREET_CHECK_PATH: GREET_CHECK_PLUS})
        blob = repository.git(repository.worktree, "rev-parse", f"HEAD:{GREET_CHECK_PATH}").strip()
        (repository.main / ".git/objects" / blob[:2] / blob[2:]).unlink()
        result = check(str(repository.worktree), "main", scratch_root=scratch_directory(self), environ=os.environ)
        self.assertEqual((result["new_tests"], result["still_passing"]), ([], []))
        self.assertTrue(result["reason"].startswith("the check failed: RuntimeError: git show "), result["reason"])
        self.assertIn(GREET_CHECK_PATH, result["reason"])

    def test_no_usable_temporary_directory_is_a_reason_not_a_crash(self):
        repository = FixtureRepository(self)
        repository.commit(PROOF_CHANGE)
        argv = ["--worktree-path", str(repository.worktree), "--integration-branch", "main"]
        out = io.StringIO()
        with mock.patch.dict(os.environ, {}, clear=False) as environ, \
                mock.patch("tempfile.gettempdir", side_effect=FileNotFoundError("no usable temporary directory")), \
                contextlib.redirect_stdout(out):
            environ.pop("REVERT_CHECK_SCRATCH", None)
            code = main(argv)
        result = json.loads(out.getvalue())
        self.assertEqual((code, result["verdict"], result["still_passing"]), (0, "ok", []))
        self.assertEqual(result["new_tests"], [FAREWELL_ID, GREET_ID])
        self.assertTrue(result["reason"].startswith("the scratch worktree could not be made: "), result["reason"])

    def test_a_new_test_that_outlives_its_bound_is_not_listed(self):
        repository = FixtureRepository(self)
        repository.commit({"checks/check_slow.py": (
            "import time\nimport unittest\n\n\nclass SlowCheck(unittest.TestCase):\n"
            "    def test_sleeps(self):\n        time.sleep(30)\n")})
        started = time.monotonic()
        result = check(str(repository.worktree), "main", scratch_root=scratch_directory(self),
                       environ=os.environ, test_seconds=1)
        self.assertEqual(result["new_tests"], ["checks.check_slow.SlowCheck.test_sleeps"])
        self.assertEqual(result["still_passing"], [])
        self.assertEqual(result["reason"], "new tests stopped at the 1 s limit: checks.check_slow.SlowCheck.test_sleeps")
        self.assertLess(time.monotonic() - started, 20)

    def test_a_service_a_timed_out_test_started_in_its_own_session_is_killed_too(self):
        repository = FixtureRepository(self)
        marker = repository.tmp / "service-pid"
        repository.commit({"checks/check_service.py": SERVICE.format(marker=str(marker))})
        result = check(str(repository.worktree), "main", scratch_root=scratch_directory(self),
                       environ=os.environ, test_seconds=5)
        self.assertEqual(result["still_passing"], [])
        self.assertIn("stopped at the 5 s limit", result["reason"])
        pid = int(marker.read_text())
        self.addCleanup(lambda: alive(pid) and os.kill(pid, signal.SIGKILL))
        self.assertTrue(eventually(lambda: not alive(pid)), "the service outlived the timed out test")

    def test_a_new_test_cannot_write_into_the_live_worktree_or_its_git_directory(self):
        repository = FixtureRepository(self)
        targets = [str(repository.worktree / "leak.txt"), str(repository.main / ".git" / "leak.txt")]
        repository.commit({"checks/check_writer.py": WRITER.format(targets=targets)})
        scratch = scratch_directory(self)
        sealed = bool(seal_argv([str(repository.worktree), str(repository.main / ".git")], scratch))
        result = check(str(repository.worktree), "main", scratch_root=scratch, environ=os.environ)
        self.assertEqual(result["still_passing"], result["new_tests"])
        self.assertEqual([Path(target).exists() for target in targets], [not sealed] * 2)
        for target in targets:
            Path(target).unlink(missing_ok=True)

    def test_the_seal_names_the_protected_paths_and_the_writable_one_or_is_empty(self):
        def run(code):
            return lambda argv, **_: subprocess.CompletedProcess(argv, code)
        found = lambda name: f"/bin/{name}"  # noqa: E731
        darwin = seal_argv(["/w", "/g"], "/s", system="darwin", which=found, run=run(0))
        self.assertEqual(darwin[0], "/bin/sandbox-exec")
        self.assertEqual([word for word in darwin if word.startswith(("P0=", "P1=", "W="))], ["P0=/w", "P1=/g", "W=/s"])
        linux = seal_argv(["/w", "/g"], "/s", system="linux", which=found, run=run(0))
        self.assertEqual(linux[0], "/bin/bwrap")
        self.assertEqual(linux[linux.index("--ro-bind"):linux.index("--ro-bind") + 3], ["--ro-bind", "/w", "/w"])
        self.assertIn("/g", linux)
        self.assertEqual(linux[linux.index("--bind", 3):][:3], ["--bind", "/s", "/s"])
        self.assertEqual(seal_argv(["/w"], "/s", system="darwin", which=found, run=run(1)), [])
        self.assertEqual(seal_argv(["/w"], "/s", system="linux", which=lambda name: None, run=run(0)), [])
        self.assertEqual(seal_argv(["/w"], "/s", system="plan9", which=found, run=run(0)), [])

    def test_a_new_test_module_that_cannot_be_parsed_is_named_in_the_reason(self):
        repository = FixtureRepository(self)
        repository.commit({**PROOF_CHANGE, "checks/check_broken.py": "def broken(:\n"})
        result = check(str(repository.worktree), "main", scratch_root=scratch_directory(self), environ=os.environ)
        self.assertEqual(result["still_passing"], [GREET_ID])
        self.assertIn("checks/check_broken.py: SyntaxError", result["reason"])
        self.assertTrue(result["reason"].startswith("changed Python files that could not be parsed"), result["reason"])

    def test_the_snapshot_notices_a_retargeted_link_and_a_changed_mode(self):
        repository = FixtureRepository(self)
        (repository.worktree / "one.txt").write_text("same")
        (repository.worktree / "two.txt").write_text("same")
        os.symlink("one.txt", repository.worktree / "link")
        first = repository.snapshot()
        (repository.worktree / "link").unlink()
        os.symlink("two.txt", repository.worktree / "link")
        second = repository.snapshot()
        self.assertNotEqual(first, second)
        (repository.worktree / "one.txt").chmod(0o755)
        self.assertNotEqual(repository.snapshot(), second)

    def test_a_spent_budget_runs_no_further_test_and_says_so(self):
        repository = FixtureRepository(self)
        repository.commit(PROOF_CHANGE)
        result = check(str(repository.worktree), "main", scratch_root=scratch_directory(self),
                       environ=os.environ, budget_seconds=0)
        self.assertEqual(result["still_passing"], [])
        self.assertEqual(result["reason"], "the check ran out of its 0 s budget after 0 of 2 new tests")

    def test_a_newline_in_the_scratch_root_never_redirects_the_cleanup(self):
        repository = FixtureRepository(self)
        repository.commit(PROOF_CHANGE)
        parent = Path(scratch_directory(self))
        victim = parent / "victim"
        victim.mkdir()
        (victim / "keep.txt").write_text("keep")
        root = parent / "victim\nroot"
        root.mkdir()
        result = check(str(repository.worktree), "main", scratch_root=str(root), environ=os.environ)
        self.assertEqual((result["still_passing"], result["reason"]), ([GREET_ID], ""))
        self.assertEqual((victim / "keep.txt").read_text(), "keep")
        self.assertEqual(os.listdir(victim), ["keep.txt"])
        self.assertEqual(os.listdir(root), [])

    def test_a_populated_read_only_directory_is_removed_between_tests_and_at_the_end(self):
        repository = FixtureRepository(self)
        repository.commit({"checks/check_readonly.py": READONLY})
        scratch = scratch_directory(self)
        self.addCleanup(subprocess.run, ["chmod", "-R", "u+rwx", scratch])
        result = check(str(repository.worktree), "main", scratch_root=scratch, environ=os.environ)
        self.assertEqual(result["new_tests"], ["checks.check_readonly.RoCheck.test_a_leaves",
                                               "checks.check_readonly.RoCheck.test_b_sees_clean"])
        self.assertEqual(result["still_passing"], result["new_tests"])
        self.assertEqual(result["reason"], "")
        self.assertEqual(os.listdir(scratch), [])

    def test_a_package_root_whose_name_a_namespace_directory_of_the_scratch_root_shares_stays_reachable(self):
        repository = FixtureRepository(self, {
            "tests/check_old.py": "", "src/tests/__init__.py": "", "src/pkg/__init__.py": "",
            "src/pkg/calc.py": "def add(a, b):\n    return a + b\n"})
        repository.commit({"checks/check_calc.py": (
            "import unittest\n\n\nclass CalcCheck(unittest.TestCase):\n"
            "    def test_add(self):\n        from pkg.calc import add\n        self.assertEqual(add(1, 2), 3)\n")})
        result = check(str(repository.worktree), "main", scratch_root=scratch_directory(self), environ=os.environ)
        self.assertEqual(result["new_tests"], ["checks.check_calc.CalcCheck.test_add"])
        self.assertEqual(result["still_passing"], result["new_tests"])
        self.assertEqual(result["reason"], "")

    def test_a_watcher_that_cannot_spawn_the_test_reports_why(self):
        repository = FixtureRepository(self)
        repository.commit(PROOF_CHANGE)
        with mock.patch("agent_tools.delivery.revert_check.TEST_PYTHON", "/nonexistent/python"):
            result = check(str(repository.worktree), "main", scratch_root=scratch_directory(self),
                           environ=os.environ)
        self.assertEqual(result["new_tests"], [FAREWELL_ID, GREET_ID])
        self.assertEqual(result["still_passing"], [])
        self.assertTrue(result["reason"].startswith("a test could not be started: "), result["reason"])
        self.assertIn("/nonexistent/python", result["reason"])

    def test_repeated_diamond_inheritance_without_a_testcase_ancestor_is_discovered_in_linear_work(self):
        levels = 20
        lines = ["class P0: pass", "class Q0(P0): pass", "class R0(P0): pass"]
        for level in range(1, levels + 1):
            lines += [f"class P{level}(Q{level - 1}, R{level - 1}): pass", f"class Q{level}(P{level}): pass",
                      f"class R{level}(P{level}): pass"]
        lines.append(f"class Leaf(P{levels}):\n    def test_leaf(self): pass")
        started = time.monotonic()
        self.assertEqual(case_ids("\n".join(lines) + "\n"), frozenset())
        self.assertLess(time.monotonic() - started, 2)
        self.assertEqual(case_ids("\n".join(["import unittest", "class P0(unittest.TestCase): pass", *lines[1:]]) + "\n"),
                         frozenset({"Leaf.test_leaf"}))

    def test_the_wall_bound_covers_the_budget_and_one_more_test(self):
        self.assertGreaterEqual(PLATFORM_WALL_SECONDS["revert-check"], BUDGET_SECONDS + TEST_SECONDS)


if __name__ == "__main__":
    unittest.main()
