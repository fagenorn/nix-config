"""Contract tests for `revert-check` (#1534): the new tests of a change that still pass at the merge base.

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
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from agent_tools.delivery.engine_commands import PLATFORM_WALL_SECONDS
from agent_tools.delivery.revert_check import BUDGET_SECONDS, TEST_SECONDS, WATCHER, case_ids, check, main

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
SLEEPER = ("import os\nimport time\nimport unittest\n\n\nclass SleepCheck(unittest.TestCase):\n"
           "    def test_sleeps(self):\n        open({marker!r}, 'w').write(str(os.getpid()))\n        time.sleep(30)\n")
BOM_CHECK = "import unittest\n\n\nclass BomCheck(unittest.TestCase):\n    def test_passes(self):\n        self.assertTrue(True)\n"
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
        for path in sorted(p for p in self.worktree.rglob("*") if p.is_file()):
            digest.update(str(path.relative_to(self.worktree)).encode() + b"\0" + path.read_bytes() + b"\0")
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
        scratch = scratch_directory(self)
        before = repository.snapshot()
        code, result = repository.run({"REVERT_CHECK_SCRATCH": scratch})
        self.assertEqual(code, 0)
        self.assertTrue(result["still_passing"])
        self.assertEqual(repository.snapshot(), before)
        self.assertEqual(os.listdir(scratch), [])
        self.assertFalse((repository.tmp / "hooked").exists())
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
        self.assertTrue(eventually(lambda: marker.exists() and marker.read_text().isdigit()))
        pid = int(marker.read_text())
        self.addCleanup(lambda: alive(pid) and os.kill(pid, signal.SIGKILL))
        os.killpg(checker.pid, signal.SIGKILL)
        checker.wait()
        self.assertTrue(eventually(lambda: not alive(pid)), "the test outlived the checker")
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
        self.assertLess(time.monotonic() - started, 20)

    def test_a_spent_budget_runs_no_further_test_and_says_so(self):
        repository = FixtureRepository(self)
        repository.commit(PROOF_CHANGE)
        result = check(str(repository.worktree), "main", scratch_root=scratch_directory(self),
                       environ=os.environ, budget_seconds=0)
        self.assertEqual(result["still_passing"], [])
        self.assertEqual(result["reason"], "the check ran out of its 0 s budget after 0 of 2 new tests")

    def test_the_wall_bound_covers_the_budget_and_one_more_test(self):
        self.assertGreaterEqual(PLATFORM_WALL_SECONDS["revert-check"], BUDGET_SECONDS + TEST_SECONDS)


if __name__ == "__main__":
    unittest.main()
