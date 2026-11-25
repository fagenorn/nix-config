"""Contract tests for `verify_rounds` (`agent_tools.delivery.verify_rounds`): the round, fix-range and retest
readings of a delivery's verification, read from its engine ledger, its contract and its worktree.

Ledgers are built with `engine_ledger` under the fixture project's temporary `HOME`; the cases that read
the contract or the worktree run against the committed fixture repository.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent_tools.delivery import engine_caps, engine_ledger, verify_rounds
from tests.test_land_tally import LedgerMaker
from tests.test_verified_tree import HERMETIC_GIT, ProjectCase

TIER = "fast"

S = "1" * 40
C = "2" * 40
H = "3" * 40
LINT_PASS = {"id": "lint", "status": "pass", "exit": 0, "summary": ""}


def failing(summary: str = "boom", **extra) -> dict:
    return {"id": "test", "status": "fail", "exit": 1, "summary": summary, **extra}


def document(verdict: str, head: str = H, results: list | None = None, clean: bool = True) -> dict:
    return {"verdict": verdict, "head": head, "clean": clean,
            "results": [LINT_PASS] if results is None else results}


FAILED = document("failed", results=[LINT_PASS, failing("s")])


class Delivery(LedgerMaker):
    """A delivery's ledger the test builds, under a temporary `HOME`."""

    def start_delivery(self, home: Path) -> None:
        patch = mock.patch.dict(os.environ, {**HERMETIC_GIT, "HOME": str(home)})
        patch.start()
        self.addCleanup(patch.stop)
        self.use_home(home)
        (self.procedures / "verify.json").write_text("{}", encoding="utf-8")
        self.root = self.run_of("deliver")
        self.holder = "host-a/" + self.root.name
        self.calls = 0

    def verify_run(self) -> Path:
        run = self.run_of("verify", parent=self.root)
        self.calls += 1
        self.call(self.root, run, self.calls)
        return run

    def round(self) -> dict:
        return verify_rounds.answer(self.holder, str(self.repo))

    def verified(self, document: dict, step: str = "checks", run: Path | None = None) -> Path:
        run = run or self.verify_run()
        self.visit(run, step, 1, document["verdict"], document)
        return run

    def fix(self, run: Path, visit: int = 1, tests: list | None = None, **extra) -> None:
        result = {"status": "done", "tests": [] if tests is None else tests, **extra}
        self.visit(run, "fix", visit, "done", result)

    def ws_check(self, run: Path, start: str, commit: str, visit: int = 1) -> None:
        self.visit(run, "ws-check", visit, "read",
                   {"verdict": "read", "start_head": start, "commit": commit})


class LedgerCase(Delivery, unittest.TestCase):
    """A delivery with no repository: the contract read is replaced by an empty list of guards."""

    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.start_delivery(Path(scratch.name).resolve())
        guards = mock.patch.object(verify_rounds, "_guards", return_value=[])
        guards.start()
        self.addCleanup(guards.stop)
        self.repo = Path(scratch.name)


class RoundCase(Delivery, ProjectCase):
    """A fixture repository plus a delivery whose verify runs the test builds."""

    def setUp(self):
        super().setUp()
        self.start_delivery(self.scratch / "home")


class RoundTest(LedgerCase):
    def test_a_failed_verification_with_a_round_left_answers_fix_with_its_problems(self):
        self.verified(FAILED)
        answer = self.round()
        self.assertEqual(answer["verdict"], "fix")
        self.assertEqual(answer["head"], H)
        self.assertIs(answer["clean"], True)
        self.assertEqual(answer["problems"],
                         [{"id": "test", "status": "fail", "summary": "s", "reran": False}])
        self.assertEqual(answer["results"], FAILED["results"])
        self.assertEqual(answer["start_head"], "")
        self.assertIsInstance(answer["guards"], list)

    def test_two_fixes_over_two_verify_runs_of_the_delivery_spend_the_rounds(self):
        first = self.verify_run()
        self.fix(first)
        second = self.verify_run()
        self.fix(second)
        self.visit(second, "checks", 1, "failed", FAILED)
        self.assertEqual(self.round()["verdict"], "spent")

    def test_one_fix_over_two_verify_runs_leaves_a_round(self):
        first = self.verify_run()
        self.fix(first)
        self.verified(FAILED)
        self.assertEqual(self.round()["verdict"], "fix")

    def test_two_fixes_in_one_verify_run_spend_the_rounds(self):
        run = self.verify_run()
        self.fix(run, 1)
        self.fix(run, 2)
        self.visit(run, "checks", 1, "failed", FAILED)
        self.assertEqual(self.round()["verdict"], "spent")

    def test_the_latest_of_checks_and_rerun_is_the_verification_read(self):
        run = self.verified(FAILED)
        self.visit(run, "rerun", 1, "passed", document("passed"))
        self.assertEqual(self.round()["verdict"], "passed")

    def test_a_no_slot_failure_answers_verify(self):
        self.verified(document("failed", results=[failing("slots", no_slot=True)]))
        self.assertEqual(self.round()["verdict"], "verify")

    def test_a_no_slot_failure_in_a_dirty_verification_answers_verify(self):
        self.verified(document("failed", clean=False, results=[failing("slots", no_slot=True)]))
        self.assertEqual(self.round()["verdict"], "verify")

    def test_a_dirty_verification_answers_fix_with_the_dirty_problem(self):
        self.verified(document("dirty", clean=False))
        answer = self.round()
        self.assertEqual(answer["verdict"], "fix")
        self.assertEqual(answer["problems"], [{"id": "?", "status": "dirty",
                                               "summary": verify_rounds.DIRTY, "reran": False}])

    def test_a_verification_whose_head_moved_answers_fix_with_the_moved_problem(self):
        self.verified(document("dirty", clean=True))
        answer = self.round()
        self.assertEqual(answer["verdict"], "fix")
        self.assertEqual(answer["problems"], [{"id": "?", "status": "dirty",
                                               "summary": verify_rounds.MOVED, "reran": False}])

    def test_an_error_verdict_answers_verify(self):
        self.verified(document("error"))
        self.assertEqual(self.round()["verdict"], "verify")

    def test_a_failure_that_failed_its_rerun_again_is_marked_reran_in_problems(self):
        self.verified(document("failed", results=[failing("again", reran=True), failing("once")]))
        self.assertEqual([(p["summary"], p["reran"]) for p in self.round()["problems"]],
                         [("again", True), ("once", False)])

    def test_a_pass_with_no_untested_fix_answers_passed(self):
        self.verified(document("passed"))
        answer = self.round()
        self.assertEqual((answer["verdict"], answer["start_head"], answer["problems"]), ("passed", "", []))

    def test_a_pass_after_an_untested_fix_answers_retest_from_the_verified_head_before_it(self):
        run = self.verified(FAILED)
        self.fix(run)
        self.ws_check(run, S, C)
        self.visit(run, "rerun", 1, "passed", document("passed", head=C))
        answer = self.round()
        self.assertEqual((answer["verdict"], answer["start_head"], answer["head"]), ("retest", S, C))

    def test_a_fix_reply_naming_its_new_commit_as_its_start_is_still_untested(self):
        run = self.verified(FAILED)
        self.fix(run, start_head=C, commit=C)
        self.ws_check(run, S, C)
        self.visit(run, "rerun", 1, "passed", document("passed", head=C))
        self.assertEqual(self.round()["start_head"], S)

    def test_a_fix_whose_ws_check_recorded_nothing_is_untested_from_the_failed_verifications_head(self):
        run = self.verified(FAILED)
        self.fix(run, start_head=C, commit=C)
        self.visit(run, "rerun", 1, "passed", document("passed", head=C))
        answer = self.round()
        self.assertEqual((answer["verdict"], answer["start_head"]), ("retest", H))

    def test_a_fix_agent_that_never_replied_is_untested_across_a_continue(self):
        first = self.verified(FAILED)
        self.enter(first, "fix")
        later = self.verify_run()
        self.visit(later, "checks", 1, "passed", document("passed", head=C))
        answer = self.round()
        self.assertEqual((answer["verdict"], answer["start_head"]), ("retest", H))

    def test_a_ws_check_with_no_start_falls_back_to_the_failed_verifications_head(self):
        run = self.verified(FAILED)
        self.fix(run)
        self.ws_check(run, "", "")
        self.visit(run, "rerun", 1, "passed", document("passed", head=C))
        self.assertEqual(self.round()["start_head"], H)

    def test_a_fix_that_left_the_head_where_the_failure_was_needs_no_retest(self):
        run = self.verified(FAILED)
        self.fix(run)
        later = self.verify_run()
        self.visit(later, "checks", 1, "passed", document("passed", head=H))
        self.assertEqual(self.round()["verdict"], "passed")

    def test_a_verification_at_a_head_other_than_the_reviewed_fix_answers_verify(self):
        run = self.verified(FAILED)
        self.fix(run, tests=["just test"])
        self.ws_check(run, S, C)
        self.visit(run, "checks", 2, "passed", document("passed", head=H))
        self.assertEqual(self.round()["verdict"], "verify")

    def test_a_verification_at_the_reviewed_fix_is_not_unreviewed(self):
        run = self.verified(FAILED)
        self.fix(run, tests=["just test"])
        self.ws_check(run, S, C)
        self.visit(run, "checks", 2, "passed", document("passed", head=C))
        self.assertEqual(self.round()["verdict"], "passed")

    def test_the_answer_carries_the_digest_of_its_results(self):
        self.verified(FAILED)
        expected = hashlib.sha256(json.dumps(FAILED["results"], sort_keys=True, separators=(",", ":"))
                                  .encode("utf-8")).hexdigest()
        self.assertEqual(self.round()["digest"], expected)

    def test_an_unread_fix_range_with_no_test_is_untested(self):
        run = self.verified(FAILED)
        self.fix(run)
        self.ws_check(run, S, "")
        self.visit(run, "rerun", 1, "passed", document("passed", head=C))
        answer = self.round()
        self.assertEqual((answer["verdict"], answer["start_head"]), ("retest", S))

    def test_two_untested_fixes_keep_the_earliest_start(self):
        first = self.verified(FAILED)
        self.fix(first)
        self.ws_check(first, S, C)
        second = self.verify_run()
        self.fix(second)
        self.ws_check(second, C, H)
        self.visit(second, "rerun", 1, "passed", document("passed"))
        self.assertEqual(self.round()["start_head"], S)

    def test_a_retested_done_clears_the_untested_range(self):
        run = self.verified(FAILED)
        self.fix(run)
        self.ws_check(run, S, C)
        self.visit(run, "retested", 1, "done", {"verdict": "done"})
        self.visit(run, "rerun", 1, "passed", document("passed", head=C))
        self.assertEqual(self.round()["verdict"], "passed")

    def test_a_fix_that_recorded_a_test_or_did_not_move_the_head_is_not_untested(self):
        run = self.verified(FAILED)
        self.fix(run, 1, tests=["just test"])
        self.ws_check(run, S, C, 1)
        self.fix(run, 2, tests=[" "])
        self.ws_check(run, C, C, 2)
        self.visit(run, "rerun", 1, "passed", document("passed", head=C))
        self.assertEqual(self.round()["verdict"], "passed")

    def test_a_holder_with_no_verification_answers_the_error_codes(self):
        with self.assertRaises(verify_rounds.TallyError) as bare:
            verify_rounds.answer(self.holder, str(self.repo))
        self.assertEqual(bare.exception.code, "no_verify_run")
        self.verify_run()
        with self.assertRaises(verify_rounds.TallyError) as unread:
            verify_rounds.answer(self.holder, str(self.repo))
        self.assertEqual(unread.exception.code, "no_verification")


class CommandLineTest(RoundCase):
    def run_tool(self, *args):
        return subprocess.run([sys.executable, "-m", "agent_tools.delivery.verify_rounds", *args],
                              cwd=self.repo, capture_output=True, text=True, check=False,
                              env={**self.env, "PYTHONPATH": os.pathsep.join(sys.path)})

    def test_a_holder_with_no_run_answers_error_with_exit_1(self):
        done = self.run_tool("round", "--holder", "h/none", "--worktree-path", str(self.repo))
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertEqual(done.stdout.count("\n"), 1)
        self.assertEqual(json.loads(done.stdout)["verdict"], "error")
        self.assertEqual(json.loads(done.stdout)["error"], "no_run")

    def test_a_round_prints_one_line_and_exits_0(self):
        self.verified(FAILED)
        done = self.run_tool("round", "--holder", self.holder, "--worktree-path", str(self.repo))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.count("\n"), 1)
        self.assertEqual(sorted(json.loads(done.stdout)),
                         ["clean", "digest", "guards", "head", "problems", "results", "start_head", "verdict"])

    def test_a_missing_flag_is_a_usage_error_with_exit_1(self):
        for argv in (("round", "--holder", "h/x"), ("fix-range", "--worktree-path", str(self.repo)),
                     ("retested",), ()):
            done = self.run_tool(*argv)
            self.assertEqual(done.returncode, 1, argv)
            self.assertEqual(json.loads(done.stdout)["error"], "usage", argv)

    def test_the_fix_range_reads_the_live_head_and_the_range(self):
        (self.repo / "a.json").write_text(json.dumps({"a": {"b": 1}}, indent=4) + "\n")
        self.commit_all("add a.json")
        start = self.git("rev-parse", "HEAD")
        (self.repo / "a.json").write_text(json.dumps({"a": {"b": 1}}, indent=2) + "\n")
        self.commit_all("re-indent")
        done = self.run_tool("fix-range", "--worktree-path", str(self.repo), "--head", start)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(done.stdout),
                         {"verdict": "read", "start_head": start, "commit": self.git("rev-parse", "HEAD"),
                          "whitespace_only": True, "changed_paths": ["a.json"]})

    def test_a_fix_range_with_an_unknown_start_is_unread_and_disables_narrowing(self):
        done = self.run_tool("fix-range", "--worktree-path", str(self.repo), "--head", "f" * 40)
        self.assertEqual(done.returncode, 0, done.stderr)
        answer = json.loads(done.stdout)
        self.assertEqual((answer["verdict"], answer["whitespace_only"], answer["changed_paths"],
                          answer["commit"], answer["start_head"]), ("unread", False, [], "", "f" * 40))
        self.assertTrue(answer["detail"])


class GuardsTest(RoundCase):
    def declare(self, ids: dict, conditions: dict | None = None, before: list | None = None) -> None:
        path = self.repo / ".agents" / "project.json"
        contract = json.loads(path.read_text(encoding="utf-8"))
        bindings = contract["bindings"]
        bindings["commands"] = {name: {"argv": [sys.executable, name], "cwd": cwd, "env": []}
                                for name, cwd in ids.items()}
        bindings["workflow"]["verification"] = list(ids)
        bindings["workflow"].pop("verification_before_pull_request", None)
        bindings["workflow"].pop("verification_conditions", None)
        if conditions is not None:
            bindings["workflow"]["verification_conditions"] = conditions
        if before is not None:
            bindings["workflow"]["verification_before_pull_request"] = before
        path.write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8")
        (self.repo / "sub").mkdir(exist_ok=True)

    def guards(self) -> list:
        self.verified(FAILED)
        return self.round()["guards"]

    def test_the_guards_are_the_contracts_pre_commit_commands(self):
        self.declare({"lint": ".", "test": "sub", "suite": "."},
                     conditions={"lint": {"pre_commit": True}})
        self.assertEqual(self.guards(),
                         [{"id": "lint", "argv": [sys.executable, "lint"], "cwd": str(self.repo.resolve())}])

    def test_with_no_pre_commit_flag_the_guards_are_the_verified_ids(self):
        self.declare({"lint": ".", "test": "sub", "suite": "."}, before=["test", "lint"])
        found = self.guards()
        self.assertEqual([g["id"] for g in found], ["test", "lint"])
        self.assertEqual(found[0], {"id": "test", "argv": [sys.executable, "test"],
                                    "cwd": str((self.repo / "sub").resolve())})
        self.assertTrue(all(os.path.isabs(g["cwd"]) for g in found))

    def test_a_refused_contract_is_contract_refused(self):
        (self.repo / ".agents" / "project.json").write_text("{}", encoding="utf-8")
        self.verified(FAILED)
        with self.assertRaises(verify_rounds.TallyError) as refused:
            self.round()
        self.assertEqual(refused.exception.code, "contract_refused")


class RetestedTest(RoundCase):
    def setUp(self):
        super().setUp()
        self.head = self.git("rev-parse", "HEAD")

    def reread(self, round_head=None, reply=True, **members):
        """The answer for a fresh verify run holding a `round` result and, unless `reply` is false, a retest."""
        run = self.verify_run()
        head = round_head or self.head
        self.visit(run, "round", 1, "passed", {"verdict": "passed", "head": head})
        if reply:
            members = {"status": "done", "start_head": self.head, "commit": self.head, "clean": True,
                       "tests": ["just test"], **members}
            self.visit(run, "retest", 1, "done", members)
        return verify_rounds.retested(self.holder, str(self.repo))

    def test_a_clean_tested_retest_at_the_verified_head_is_done(self):
        self.assertEqual(self.reread()["verdict"], "done")

    def test_a_retest_that_does_not_speak_for_the_round_is_untested(self):
        for members in ({"status": "blocked"}, {"start_head": "4" * 40}, {"commit": "4" * 40},
                        {"tests": [" "]}, {"round_head": "4" * 40}):
            with self.subTest(members):
                answer = self.reread(**members)
                self.assertEqual((answer["verdict"], answer["detail"]),
                                 ("untested", verify_rounds.UNTESTED))

    def test_a_head_that_moved_after_the_round_is_untested(self):
        (self.repo / "later.txt").write_text("later\n")
        self.commit_all("later")
        self.assertEqual(self.reread()["verdict"], "untested")

    def test_a_retest_with_no_reply_is_untested(self):
        self.assertEqual(self.reread(reply=False)["verdict"], "untested")

    def test_a_reply_that_says_dirty_is_dirty(self):
        answer = self.reread(clean=False)
        self.assertEqual((answer["verdict"], answer["detail"]), ("dirty", verify_rounds.RETEST_DIRTY))

    def test_an_untracked_file_is_dirty_when_git_is_set_to_hide_untracked_files(self):
        self.git("config", "status.showUntrackedFiles", "no")
        (self.repo / "scratch.txt").write_text("x\n")
        self.assertEqual(self.reread(clean=True)["verdict"], "dirty")

    def test_an_untracked_file_is_dirty_whatever_the_reply_says(self):
        (self.repo / "scratch.txt").write_text("x\n")
        self.assertEqual(self.reread(clean=True)["verdict"], "dirty")


class PackageTest(unittest.TestCase):
    def test_no_engine_module_imports_verify_rounds(self):
        directory = Path(engine_ledger.__file__).parent
        self.assertNotIn(directory / "verify_rounds.py", engine_caps.engine_modules(directory))


if __name__ == "__main__":
    unittest.main()
