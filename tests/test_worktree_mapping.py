"""`agent_tools.worktree_mapping`: the #130 checklist C7 rule as code (issue 585)."""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent_tools import verify_exec, worktree_mapping
from agent_tools.worktree_mapping import MappingError, classify, classify_root, ledger_matches

ROOT = Path(__file__).resolve().parents[1]
CHECK = "home/common/verify-pending/checks/worktree-mapping"
GIT_ENV = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}


def git(*argv, cwd):
    subprocess.run(["git", *argv], cwd=cwd, check=True, capture_output=True,
                   env={**os.environ, **GIT_ENV})


class Fleet:
    """One repository with linked worktrees and hand-written ledgers."""

    def __init__(self, case):
        self._tmp = tempfile.TemporaryDirectory()
        case.addCleanup(self._tmp.cleanup)
        self.base = Path(os.path.realpath(self._tmp.name))
        self.root = self.base / "repo"
        self.root.mkdir()
        git("init", "-q", "-b", "main", cwd=self.root)
        git("commit", "-q", "--allow-empty", "-m", "a", cwd=self.root)

    def worktree(self, name, *, detach=False, at=None):
        path = Path(at) if at else self.base / name
        if detach:
            git("worktree", "add", "-q", "--detach", str(path), cwd=self.root)
        else:
            git("worktree", "add", "-q", "-b", name, str(path), cwd=self.root)
        return str(path)

    def ledger(self, name, *paths):
        d = self.root / ".superpowers" / "workflows" / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "state.json").write_text(json.dumps({"worktrees": list(paths)}), encoding="utf-8")


def report(**verdicts):
    return {"counts": {}, "ledgers": [{"ledger": k, "verdict": v} for k, v in verdicts.items()]}


def printing(rep):
    """A fake `workflow-state` body that prints `rep` as its dry-run report."""
    return "printf '%s\\n' '" + json.dumps(rep) + "'\n"


def fake_home(case, body):
    """A HOME whose `.agents/bin/workflow-state` runs `body`."""
    tmp = tempfile.TemporaryDirectory()
    case.addCleanup(tmp.cleanup)
    bin_dir = Path(tmp.name) / ".agents" / "bin"
    bin_dir.mkdir(parents=True)
    fake = bin_dir / "workflow-state"
    fake.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    fake.chmod(0o755)
    return tmp.name


class ClassifyTest(unittest.TestCase):
    def test_the_c7_precedence(self):
        v = {"a": "current", "b": "migrate", "c": "refused", "d": "migrated"}
        self.assertEqual(classify([], v), "unmapped")
        self.assertEqual(classify(["b", "a"], v), "current")
        self.assertEqual(classify(["d"], v), "current")
        self.assertEqual(classify(["c", "b"], v), "migrate")
        self.assertEqual(classify(["c"], v), "refused-only")
        self.assertEqual(classify(["absent"], v), "refused-only")


class ClassifyRootTest(unittest.TestCase):
    def setUp(self):
        self.fleet = Fleet(self)

    def test_a_root_without_linked_worktrees_is_green(self):
        got = classify_root(self.fleet.root, report())
        self.assertEqual((got["worktrees"], got["verdict"]), (0, "green"))

    def test_each_class_and_the_row_verdict(self):
        f = self.fleet
        cur, mig, ref, un = (f.worktree(n) for n in ("cur", "mig", "ref", "un"))
        f.ledger("L1", cur)
        f.ledger("L2", mig)
        f.ledger("L3", ref)
        got = classify_root(f.root, report(L1="current", L2="migrate", L3="refused"))
        self.assertEqual(got["counts"], {"current": 1, "migrate": 1, "refused-only": 1, "unmapped": 1})
        self.assertEqual(got["verdict"], "red")
        self.assertEqual([p["path"] for p in got["paths"]], [cur, mig, ref, un])
        self.assertEqual(got["paths"][2], {"class": "refused-only", "path": ref, "ledgers": ["L3"]})

    def test_refused_only_is_red(self):
        f = self.fleet
        f.ledger("L3", f.worktree("ref"))
        self.assertEqual(classify_root(f.root, report(L3="refused"))["verdict"], "red")

    def test_migrate_only_is_human_pending(self):
        f = self.fleet
        f.ledger("L2", f.worktree("mig"))
        self.assertEqual(classify_root(f.root, report(L2="migrate"))["verdict"], "human-pending")

    def test_a_prefix_path_does_not_map(self):
        f = self.fleet
        short = f.worktree("x")
        f.ledger("L1", short + "-y")
        self.assertEqual(ledger_matches(f.root, short), [])

    def test_the_realpath_maps(self):
        f = self.fleet
        real = f.worktree("real")
        link = f.base / "alias"
        link.symlink_to(real)
        f.ledger("L1", real)
        self.assertEqual(ledger_matches(f.root, str(link)), ["L1"])

    def test_lookalikes_of_a_runner_workspace_are_not_excluded(self):
        f = self.fleet
        (f.base / "verify-pending-short").mkdir()
        (f.base / "verify-pending-abcdefgh").mkdir()
        wrong_parent = f.worktree("a", detach=True, at=f.base / "verify-pending-short" / "wt")
        on_branch = f.worktree("b", at=f.base / "verify-pending-abcdefgh" / "wt")
        got = classify_root(f.root, report())
        self.assertEqual(got["excluded"], [])
        # Porcelain order: git lists linked worktrees sorted by path, so
        # ".../verify-pending-abcdefgh/wt" comes before ".../verify-pending-short/wt".
        self.assertEqual([p["path"] for p in got["paths"]], [on_branch, wrong_parent])
        self.assertEqual(got["verdict"], "red")

    def test_a_report_without_ledgers_is_refused(self):
        with self.assertRaises(MappingError):
            classify_root(self.fleet.root, {"counts": {}})

    def test_a_git_failure_is_refused(self):
        with self.assertRaises(MappingError):
            classify_root(self.fleet.base / "missing", report())


class WrapperTest(unittest.TestCase):
    def run_check(self, fake_body, *roots, flags=()):
        argv = [str(ROOT / CHECK), *flags]
        for r in roots:
            argv += ["--repo-root", str(r)]
        return subprocess.run(argv, cwd=ROOT, capture_output=True, text=True, timeout=60,
                              env={**os.environ, **GIT_ENV, "HOME": fake_home(self, fake_body)})

    def test_green_root_exits_0(self):
        f = Fleet(self)
        f.ledger("L1", f.worktree("cur"))
        done = self.run_check(printing(report(L1="current")), f.root)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertTrue(json.loads(done.stdout)["met"])

    def test_red_root_exits_1_and_human_pending_exits_75(self):
        red, pending = Fleet(self), Fleet(self)
        red.worktree("un")
        pending.ledger("L2", pending.worktree("mig"))
        body = printing(report(L2="migrate"))
        self.assertEqual(self.run_check(body, pending.root).returncode, 75)
        done = self.run_check(body, pending.root, red.root)
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertEqual([r["verdict"] for r in json.loads(done.stdout)["roots"]], ["human-pending", "red"])

    def test_red_pending_reads_red_as_not_yet(self):
        red = Fleet(self)
        red.worktree("un")
        done = self.run_check(printing(report()), red.root, flags=("--red-pending",))
        self.assertEqual(done.returncode, 75, done.stderr)
        self.assertEqual(json.loads(done.stdout)["roots"][0]["verdict"], "red")

    def test_a_failing_dry_run_is_exit_2_with_its_diagnostic(self):
        f = Fleet(self)
        done = self.run_check("echo boom >&2\nexit 4\n", f.root)
        self.assertEqual((done.returncode, done.stdout), (2, ""))
        self.assertIn("workflow-state exit 4: boom", done.stderr)

    def test_wrapper_is_committed_executable(self):
        mode = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-s", CHECK],
                              capture_output=True, text=True, check=True).stdout.split(" ")[0]
        self.assertEqual(mode, "100755")


class RunnerSeamTest(unittest.TestCase):
    """The check as verify-pending runs it: the committed script inside a detached worktree that
    `verify_exec.workspace` adds to the very root it inspects, with a second runner workspace
    open on the same root at the same time (O2, P7)."""

    def setUp(self):
        f = self.fleet = Fleet(self)
        shutil.copytree(ROOT / "python" / "agent_tools", f.root / "python" / "agent_tools",
                        ignore=shutil.ignore_patterns("__pycache__"))
        (f.root / CHECK).parent.mkdir(parents=True)
        shutil.copy2(ROOT / CHECK, f.root / CHECK)
        git("add", "python", CHECK, cwd=f.root)
        git("commit", "-q", "-m", "check", cwd=f.root)
        self.commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=f.root, check=True,
                                     capture_output=True, text=True).stdout.strip()

    def run_in_runner(self, rep, *flags):
        """({realpaths of both runner worktrees}, Result) of one run through the real seam."""
        home = fake_home(self, printing(rep))
        with mock.patch.dict(os.environ, {**GIT_ENV, "HOME": home}):
            with verify_exec.workspace(self.fleet.root, self.commit) as other, \
                    verify_exec.workspace(self.fleet.root, self.commit) as wt:
                argv, cwd = verify_exec.run_argv(
                    {"script": CHECK, "args": [*flags, "--repo-root", str(self.fleet.root)]},
                    {}, self.fleet.root, wt)
                return ({os.path.realpath(other), os.path.realpath(wt)},
                        verify_exec.execute(argv, cwd))

    def test_runner_worktrees_never_turn_their_root_red(self):
        f = self.fleet
        f.ledger("L1", f.worktree("cur"))
        runners, result = self.run_in_runner(report(L1="current"), "--red-pending")
        self.assertEqual(verify_exec.classify(result, None), "met", result.stderr)
        got = json.loads(result.stdout)["roots"][0]
        self.assertEqual({os.path.realpath(p) for p in got["excluded"]}, runners)
        self.assertEqual((got["worktrees"], got["verdict"]), (1, "green"))

    def test_only_runner_worktrees_are_left_out(self):
        self.fleet.worktree("stray")
        _, result = self.run_in_runner(report(), "--red-pending")
        self.assertEqual(verify_exec.classify(result, None), "not_yet", result.stderr)
        got = json.loads(result.stdout)["roots"][0]
        self.assertEqual((got["counts"]["unmapped"], len(got["excluded"])), (1, 2))
        _, result = self.run_in_runner(report())
        self.assertEqual(verify_exec.classify(result, None), "not_met", result.stderr)


if __name__ == "__main__":
    unittest.main()
