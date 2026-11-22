"""The eval sandboxes' build-once cache and the classes that restore from it (#1615)."""

import shutil
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from . import test_eval_cases as cases

TIER = "integration"  # every case builds and restores git repository sandboxes


class RestoredSandboxTest(unittest.TestCase):
    """#1615: a sandbox is built once per run and put back in place before every use."""

    @staticmethod
    def head_of(repo):
        return subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True,
                              text=True, check=True).stdout.strip()

    def test_a_restored_sandbox_is_its_build_without_an_earlier_tests_change(self):
        key = f"probe-{self.id()}"
        calls = []

        def build(work):
            calls.append(work)
            repo, git = cases.fixture_sandbox(work)
            head = subprocess.run(git + ["rev-parse", "HEAD"], capture_output=True, text=True,
                                  check=True).stdout.strip()
            return {"repo": str(repo), "head": head, "env": {"OUT": "built"}}

        first_work, first = cases.restored(key, build)
        with open(Path(first["repo"]) / "README.md", "a", encoding="utf-8") as readme:
            readme.write("edit\n")
        subprocess.run(cases.eval_git(Path(first["repo"])) + ["commit", "-qam", "edit"], check=True)
        (first_work / "stray").write_text("x", encoding="utf-8")
        first["head"] = "changed"
        first["env"]["OUT"] = "changed"
        second_work, second = cases.restored(key, build)
        self.assertEqual(len(calls), 1)
        self.assertEqual(second_work, first_work)
        self.assertFalse((second_work / "stray").exists())
        self.assertNotIn("edit", (Path(second["repo"]) / "README.md").read_text(encoding="utf-8"))
        self.assertEqual(self.head_of(second["repo"]), second["head"])
        self.assertNotEqual(second["head"], "changed")
        self.assertEqual(second["env"], {"OUT": "built"})
        status = subprocess.run(["git", "-C", second["repo"], "status", "--porcelain"],
                                capture_output=True, text=True, check=True).stdout
        self.assertEqual(status, "")

    def test_a_failed_build_leaves_nothing_behind_and_the_next_use_builds_again(self):
        key = f"probe-{self.id()}"

        def broken(work):
            (work / "partial").write_text("x", encoding="utf-8")
            raise RuntimeError("build failed")

        with self.assertRaises(RuntimeError):
            cases.restored(key, broken)
        self.assertNotIn(key, cases.BUILT)
        work, built = cases.restored(key, lambda work: (work / "ok").write_text("y", encoding="utf-8"))
        self.assertTrue((work / "ok").exists())
        self.assertFalse((work / "partial").exists())

    def test_a_failed_snapshot_is_not_cached_as_built(self):
        key = f"probe-{self.id()}"
        calls = []

        def build(work):
            calls.append(work)

        with mock.patch.object(shutil, "copytree", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                cases.restored(key, build)
        self.assertNotIn(key, cases.BUILT)
        cases.restored(key, build)
        self.assertEqual(len(calls), 2)

    def test_the_sandboxes_are_forgotten_with_their_directory(self):
        key = f"probe-{self.id()}"
        with mock.patch.object(cases, "SANDBOXES", None), mock.patch.dict(cases.BUILT, clear=True):
            first, _ = cases.restored(key, lambda work: None)
            root = cases.SANDBOXES
            cases.forget_sandboxes(root)
            self.assertFalse(root.exists())
            self.assertIsNone(cases.SANDBOXES)
            self.assertEqual(cases.BUILT, {})
            second, _ = cases.restored(key, lambda work: None)
            self.assertTrue(second.is_dir())
            self.assertNotEqual(cases.SANDBOXES, root)
            cases.forget_sandboxes(cases.SANDBOXES)

    def test_the_first_use_is_already_a_restored_copy(self):
        key = f"probe-{self.id()}"
        held = []
        self.addCleanup(lambda: [handle.close() for handle in held])

        def build(work):
            marker = work / "marker"
            marker.write_text("m", encoding="utf-8")
            held.append(open(marker, "a", encoding="utf-8"))
            return None

        work, _ = cases.restored(key, build)
        held[0].write("changed")
        held[0].flush()
        self.assertEqual((work / "marker").read_text(encoding="utf-8"), "m")

    def test_marked_sandboxes_are_built_once_per_run(self):
        with mock.patch.object(cases, "marked_pr_sandbox", wraps=cases.marked_pr_sandbox) as spy:
            first = cases.MarkedIssueEvalCaseTest("test_every_assert_passes_on_a_good_run").sandbox()
            second = cases.MarkedIssueResumeEvalCaseTest("test_every_assert_passes_on_a_good_run").sandbox()
        self.assertLessEqual(spy.call_count, 1)
        self.assertEqual(first[0], second[0])
        self.assertEqual(self.head_of(second[2]["PRE_WT"]), second[2]["PRE_WT_HEAD"])


class RestoredClassSandboxTest(unittest.TestCase):
    """#1615: the classes' good runs and fixtures are built once per run and restored."""

    def test_direct_delivery_good_runs_are_built_once_per_run(self):
        with mock.patch.object(cases, "implement_issue_three", wraps=cases.implement_issue_three) as spy:
            case = cases.DirectDeliveryEvalCaseTest("test_every_assert_passes_on_a_good_run")
            first = case.good_run()
            second = case.good_run()
        self.assertLessEqual(spy.call_count, 1)
        self.assertEqual(first[3]["WT"], second[3]["WT"])
        subject = subprocess.run(["git", "-C", second[3]["WT"], "log", "-1", "--format=%s"],
                                 capture_output=True, text=True, check=True).stdout.strip()
        self.assertEqual(subject, "feat: rename list --all to --include-done (#3)")

    def test_native_review_good_runs_are_built_once_and_carry_their_output(self):
        with mock.patch.object(cases, "implement_issue_three", wraps=cases.implement_issue_three) as spy:
            case = cases.NativeReviewEvalCaseTest("test_every_assert_passes_on_a_good_run")
            _, _, env = case.good_run()
            default = Path(env["OUT"]).read_text(encoding="utf-8")
            _, _, other = case.good_run(out="other\n")
        self.assertLessEqual(spy.call_count, 1)
        self.assertEqual(default, cases.NativeReviewEvalCaseTest.GOOD_OUT)
        self.assertEqual(Path(other["OUT"]).read_text(encoding="utf-8"), "other\n")
        head = subprocess.run(["git", "-C", other["PRE_WT"], "rev-parse", "HEAD"],
                              capture_output=True, text=True, check=True).stdout.strip()
        self.assertEqual(other["PRE_WT_HEAD"], head)

    def test_writing_plans_fixtures_are_built_once_per_variant(self):
        with mock.patch.object(cases, "writing_plans_fixture", wraps=cases.writing_plans_fixture) as spy:
            _, (_, first) = cases.restored("writing-plans", cases.writing_plans_fixture)
            _, (_, second) = cases.restored("writing-plans", cases.writing_plans_fixture)
            _, (_, bare) = cases.restored("writing-plans-no-plan",
                                    lambda work: cases.writing_plans_fixture(work, with_plan=False))
        self.assertLessEqual(spy.call_count, 2)
        self.assertTrue((Path(first["PLAN_DIR"]) / "p.md").is_file())
        self.assertTrue((Path(second["PLAN_DIR"]) / "p.md").is_file())
        self.assertFalse((Path(bare["PLAN_DIR"]) / "p.md").exists())
        self.assertEqual(Path(first["REPO"]).parent.name, "work")
