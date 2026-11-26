"""The stubbed world's own knobs: the fake forge's moving `main`, refused merges and per-head checks,
and the launcher stand-in's `merge`, `upstream` and `same_head` effects."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

from agent_tools.delivery import engine_stop
from tests.engine_stubbed_world import GREEN, STUB, StubbedRun
from tests.guard_policy_world import REAL_GIT, install_platform_manifest_in_environ

TIER = "integration"  # every case builds a repository and runs a fake forge or the stub as a process

setUpModule = install_platform_manifest_in_environ

RED = [{"__typename": "CheckRun", "name": "Fixture Checks", "status": "COMPLETED",
        "conclusion": "FAILURE", "startedAt": "2026-11-06T10:00:00Z", "workflowName": "Fixture"}]
BRANCH = "issue-41-add-a-greeting"
LOCK = "refs/agent-locks/land/main"
SLUG = "example/fixture"


def git(run: StubbedRun, *args: str, root: Path | None = None) -> str:
    return run.world.git(root or run.fixture.root, *args).strip()


def bare_git(run: StubbedRun, *args: str) -> str:
    done = subprocess.run([REAL_GIT, "-C", run.bare, *args], capture_output=True, text=True, check=True)
    return done.stdout.strip()


def committing(run: StubbedRun, text: str = "R = 1\n") -> dict:
    return {"reply": {"status": "done"},
            "commit": {"worktree": str(run.fixture.root), "path": "fixture/resumed.py", "text": text}}


def commits(run: StubbedRun) -> int:
    return git(run, "log", "--format=%s").splitlines().count("stub change")


class ForgeTest(unittest.TestCase):
    def push_commit(self, run: StubbedRun, text: str) -> str:
        """Commit one file on the branch (made when absent) of the fixture, push it, return its tip."""
        root = run.fixture.root
        if run.origin_tip(BRANCH) is None:
            git(run, "switch", "--quiet", "-c", BRANCH)
        else:
            git(run, "switch", "--quiet", BRANCH)
        (root / "greeting.txt").write_text(text, encoding="utf-8")
        git(run, "add", "-A")
        git(run, "commit", "--quiet", "-m", f"Work: {text.strip()}")
        git(run, "switch", "--quiet", "main")
        git(run, "push", "--quiet", "origin", BRANCH)
        return run.origin_tip(BRANCH)

    def opened(self, run: StubbedRun) -> str:
        head = self.push_commit(run, "a greeting\n")
        self.gh(run, "pr", "create", "--repo", SLUG, "--base", "main", "--head", BRANCH,
                "--title", "Add a greeting", "--body", "Closes #41.")
        return head

    def gh(self, run: StubbedRun, *argv: str, check: bool = True) -> subprocess.CompletedProcess:
        done = subprocess.run(["gh", *argv], cwd=run.fixture.root, env=run.env, capture_output=True,
                              text=True, timeout=120)
        if check:
            self.assertEqual(done.returncode, 0, done.stderr)
        return done

    def view(self, run: StubbedRun, fields: str) -> dict:
        return json.loads(self.gh(run, "pr", "view", "1", "--repo", SLUG, "--json", fields).stdout)

    def merge(self, run: StubbedRun, head: str) -> subprocess.CompletedProcess:
        return self.gh(run, "pr", "merge", "1", "--repo", SLUG, "--merge", "--match-head-commit", head,
                       "--delete-branch", check=False)

    def test_rollups_answer_per_distinct_head_and_the_last_repeats(self):
        run = StubbedRun(self, rollups=[RED, GREEN])
        self.opened(run)
        fields = "headRefOid,statusCheckRollup"
        first = [self.view(run, fields)["statusCheckRollup"] for _ in range(2)]
        self.push_commit(run, "a second greeting\n")
        second = [self.view(run, fields)["statusCheckRollup"] for _ in range(2)]
        self.assertEqual(first + second, [RED, RED, GREEN, GREEN])
        heads = json.loads(run.pulls_state.read_text("utf-8"))["rollup_heads"]
        self.assertEqual(len(heads), 2)

    def test_advance_main_commits_to_main_after_each_of_the_first_n_rollup_reads(self):
        run = StubbedRun(self, advance_main=2,
                         main_change={"path": "fixture/farewell.py", "text": "x\n"})
        self.opened(run)
        before = bare_git(run, "rev-list", "--count", "main")
        tip = bare_git(run, "rev-parse", "main")
        for _ in range(3):
            self.view(run, "statusCheckRollup")
        self.assertEqual(int(bare_git(run, "rev-list", "--count", "main")) - int(before), 2)
        first, second = bare_git(run, "rev-list", "--reverse", f"{tip}..main").split()
        self.assertEqual(bare_git(run, "show", "--name-only", "--format=", first), "fixture/farewell.py")
        self.assertEqual(bare_git(run, "show", "--name-only", "--format=", second), "main-2.txt")

    def test_merge_state_reads_behind_when_main_is_not_an_ancestor_of_the_head(self):
        run = StubbedRun(self, advance_main=1)
        self.opened(run)
        self.assertEqual(self.view(run, "mergeStateStatus")["mergeStateStatus"], "CLEAN")
        self.view(run, "statusCheckRollup")
        self.assertEqual(self.view(run, "mergeStateStatus")["mergeStateStatus"], "BEHIND")
        fresh = StubbedRun(self)
        self.opened(fresh)
        self.assertEqual(self.view(fresh, "mergeStateStatus")["mergeStateStatus"], "CLEAN")

    def test_merge_behind_moves_main_and_refuses_the_first_n_merges(self):
        run = StubbedRun(self, merge_behind=1)
        head = self.opened(run)
        tip = bare_git(run, "rev-parse", "main")
        done = self.merge(run, head)
        self.assertEqual(done.returncode, 1)
        self.assertIn("Pull request #1 is not mergeable: the head branch is not up to date with the "
                      "base branch", done.stderr)
        self.assertEqual([p["state"] for p in run.pulls()], ["OPEN"])
        self.assertNotEqual(bare_git(run, "rev-parse", "main"), tip)
        self.assertEqual(self.view(run, "mergeStateStatus")["mergeStateStatus"], "BEHIND")

    def test_merge_policy_refuses_and_reports_blocked_once(self):
        run = StubbedRun(self, merge_policy=1)
        head = self.opened(run)
        done = self.merge(run, head)
        self.assertEqual(done.returncode, 1)
        self.assertIn("the base branch policy prohibits the merge", done.stderr)
        states = [self.view(run, "mergeStateStatus")["mergeStateStatus"] for _ in range(2)]
        self.assertEqual(states, ["BLOCKED", "CLEAN"])
        self.assertEqual(self.merge(run, head).returncode, 0)
        self.assertEqual([p["state"] for p in run.pulls()], ["MERGED"])

    def test_a_lock_event_at_head_fires_on_the_head_only_read(self):
        dropping = StubbedRun(self, forge_events=("drop-lock-at-head",))
        dropping.forge.set_ref(LOCK, "1" * 40)
        self.opened(dropping)
        self.view(dropping, "headRefOid,statusCheckRollup")
        self.assertEqual(dropping.lock_refs(), {LOCK: "1" * 40})
        self.view(dropping, "headRefOid")
        self.assertEqual(dropping.lock_refs(), {})
        stealing = StubbedRun(self, forge_events=("steal-lock-at-head",))
        stealing.forge.set_ref(LOCK, "1" * 40)
        self.opened(stealing)
        self.view(stealing, "headRefOid,statusCheckRollup")
        self.assertEqual(stealing.lock_refs(), {LOCK: "1" * 40})
        self.view(stealing, "headRefOid")
        self.assertEqual(stealing.lock_refs(), {LOCK: stealing.stolen_sha})

    def test_a_repeated_lock_event_at_head_fires_again_on_the_next_such_read(self):
        run = StubbedRun(self, forge_events=("drop-lock-at-head", "drop-lock-at-head"))
        self.opened(run)
        run.forge.set_ref(LOCK, "1" * 40)
        self.view(run, "headRefOid")
        self.assertEqual(run.lock_refs(), {})
        run.forge.set_ref(LOCK, "2" * 40)
        self.view(run, "headRefOid")
        self.assertEqual(run.lock_refs(), {})
        run.forge.set_ref(LOCK, "3" * 40)
        self.view(run, "headRefOid")
        self.assertEqual(run.lock_refs(), {LOCK: "3" * 40})

    def test_the_bound_seam_is_zero_in_the_run_environment(self):
        self.assertEqual(StubbedRun(self).env["LANDING_BOUND_SECONDS"], "0")


class StubTest(unittest.TestCase):
    def play(self, run: StubbedRun, entry: dict) -> dict:
        """Run the stub on a scenario of one entry for step `fix`, as the launcher shim does."""
        scenario = run.tmp / "stub-scenario.json"
        scenario.write_text(json.dumps({"fix": entry}), encoding="utf-8")
        done = subprocess.run(
            [sys.executable, str(STUB), str(scenario), str(run.tmp / "stub.log"),
             "--append-system-prompt-file", str(run.tmp / "fix.1.system.md")],
            input="prompt", env=run.env, capture_output=True, text=True, timeout=120)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout)["structured_output"]

    def stub_argv(self, run: StubbedRun, entry: dict, *flags: str) -> list[str]:
        scenario = run.tmp / "stub-scenario.json"
        scenario.write_text(json.dumps({"fix": entry}), encoding="utf-8")
        return [sys.executable, str(STUB), str(scenario), str(run.tmp / "stub.log"), *flags,
                "--append-system-prompt-file", str(run.tmp / "fix.1.system.md")]

    def launch(self, run: StubbedRun, entry: dict, *flags: str) -> subprocess.CompletedProcess:
        return subprocess.run(self.stub_argv(run, entry, *flags), input="prompt", env=run.env,
                              capture_output=True, text=True, timeout=120)

    def diverged(self, run: StubbedRun, shared: str | None = None) -> Path:
        """The fixture root on a branch with one commit, `main` of the bare ahead of it by one."""
        root = run.fixture.root
        git(run, "switch", "--quiet", "-c", "feature")
        (root / (shared or "feature.txt")).write_text("feature\n", encoding="utf-8")
        git(run, "add", "-A")
        git(run, "commit", "--quiet", "-m", "feature")
        other = run.tmp / "other"
        subprocess.run([REAL_GIT, "clone", "-q", "--branch", "main", run.bare, str(other)], check=True)
        (other / (shared or "main.txt")).write_text("main\n", encoding="utf-8")
        git(run, "add", "-A", root=other)
        git(run, "commit", "--quiet", "-m", "main moves", root=other)
        git(run, "push", "--quiet", "origin", "HEAD:refs/heads/main", root=other)
        return root

    def test_the_same_head_effect_answers_the_worktree_head_as_start_and_commit_and_commits_nothing(self):
        run = StubbedRun(self)
        head = git(run, "rev-parse", "HEAD")
        reply = self.play(run, {"reply": {"status": "done"}, "same_head": {"worktree": str(run.fixture.root)}})
        self.assertEqual((reply["start_head"], reply["commit"], reply["status"]), (head, head, "done"))
        self.assertEqual(git(run, "rev-parse", "HEAD"), head)

    def test_the_merge_effect_commits_a_clean_merge_of_main(self):
        run = StubbedRun(self)
        root = self.diverged(run)
        self.play(run, {"reply": {"status": "done"}, "merge": {"worktree": str(root)}})
        self.assertEqual(len(git(run, "rev-list", "--parents", "-n", "1", "HEAD").split()), 3)
        self.assertEqual((root / "main.txt").read_text("utf-8"), "main\n")
        self.assertEqual(git(run, "status", "--porcelain"), "")

    def test_the_merge_effect_aborts_a_conflict_without_a_resolution(self):
        run = StubbedRun(self)
        root = self.diverged(run, "shared.txt")
        head = git(run, "rev-parse", "HEAD")
        self.play(run, {"reply": {"status": "done"}, "merge": {"worktree": str(root)}})
        self.assertEqual(git(run, "rev-parse", "HEAD"), head)
        self.assertFalse((root / ".git" / "MERGE_HEAD").exists())
        self.assertEqual((root / "shared.txt").read_text("utf-8"), "feature\n")

    def test_the_merge_effect_commits_a_resolution_it_is_given(self):
        run = StubbedRun(self)
        root = self.diverged(run, "shared.txt")
        self.play(run, {"reply": {"status": "done"},
                        "merge": {"worktree": str(root), "resolve": {"shared.txt": "both\n"}}})
        self.assertEqual(len(git(run, "rev-list", "--parents", "-n", "1", "HEAD").split()), 3)
        self.assertEqual((root / "shared.txt").read_text("utf-8"), "both\n")
        self.assertEqual(git(run, "status", "--porcelain"), "")

    def test_the_upstream_effect_commits_to_the_bare_main(self):
        run = StubbedRun(self)
        before = bare_git(run, "rev-parse", "main")
        self.play(run, {"reply": {"status": "done"},
                        "upstream": {"bare": run.bare, "path": "up/stream.txt", "text": "up\n"}})
        self.assertEqual(bare_git(run, "show", "main:up/stream.txt"), "up")
        self.assertEqual(bare_git(run, "rev-parse", "main^"), before)
        self.assertEqual(bare_git(run, "log", "-1", "--format=%an"), "stub upstream")

    def test_answer_rewrites_one_reply_for_the_next_delivery(self):
        run = StubbedRun(self)
        entry = {"reply": {"status": "done"}, "commit": {"path": "fixture/x.py", "text": "X = 1\n"}}

        run.answer("fix", entry)

        scenario = json.loads(run.scenario.read_text(encoding="utf-8"))
        self.assertEqual(scenario["fix"]["commit"],
                         {"path": "fixture/x.py", "text": "X = 1\n", "worktree": str(run.worktree_path)})
        self.assertEqual(scenario["fix"]["reply"], {"status": "done"})
        self.assertEqual(scenario["implement"], run.replies["implement"])
        self.assertEqual(run.replies["fix"], scenario["fix"])
        self.assertEqual(scenario["implement"]["commit"]["worktree"], str(run.worktree_path))

    def test_the_leave_effect_writes_one_untracked_file_and_keeps_the_head(self):
        run = StubbedRun(self)
        root = str(run.fixture.root)
        head = git(run, "rev-parse", "HEAD")

        reply = self.play(run, {"reply": {"status": "done"}, "same_head": {"worktree": root},
                                "leave": {"worktree": root, "path": "fixture/scratch.txt", "text": "x\n"}})

        self.assertEqual(git(run, "status", "--porcelain"), "?? fixture/scratch.txt")
        self.assertEqual((run.fixture.root / "fixture/scratch.txt").read_text("utf-8"), "x\n")
        self.assertEqual(git(run, "rev-parse", "HEAD"), head)
        self.assertEqual((reply["start_head"], reply["commit"], reply["status"]), (head, head, "done"))

    def test_the_world_fills_the_worktree_and_the_bare_an_effect_names_none_of(self):
        entry = {"reply": {"status": "done"}, "merge": {}, "same_head": {}, "commit": {"path": "a", "text": "b"},
                 "upstream": {"path": "up.txt", "text": "up\n"}}
        run = StubbedRun(self, replies={"fix": entry})
        filled = run.replies["fix"]
        worktree = str(run.worktree_path)
        self.assertEqual([filled[effect]["worktree"] for effect in ("merge", "same_head", "commit")],
                         [worktree] * 3)
        self.assertEqual(filled["upstream"]["bare"], run.bare)

    def test_the_world_fills_the_worktree_a_leave_effect_names_none_of(self):
        run = StubbedRun(self, replies={"fix": {"reply": {"status": "done"},
                                                "leave": {"path": "fixture/scratch.txt", "text": "x\n"}}})
        self.assertEqual(run.replies["fix"]["leave"]["worktree"], str(run.worktree_path))


    def test_a_resumed_session_that_answered_replays_its_answer_and_commits_nothing(self):
        run = StubbedRun(self)
        first = self.launch(run, committing(run), "--session-id", "s-1")
        second = self.launch(run, committing(run), "--resume", "s-1")
        self.assertEqual((first.returncode, second.returncode), (0, 0), first.stderr + second.stderr)
        answered = json.loads(first.stdout)["structured_output"]
        self.assertEqual(json.loads(second.stdout)["structured_output"], answered)
        self.assertEqual(commits(run), 1)
        self.assertEqual(git(run, "rev-parse", "HEAD"), answered["commit"])

    def test_a_resume_of_a_session_with_no_recorded_answer_runs_its_entry(self):
        run = StubbedRun(self)
        done = self.launch(run, committing(run), "--resume", "s-2")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(commits(run), 1)
        self.assertEqual(json.loads(done.stdout)["structured_output"]["commit"], git(run, "rev-parse", "HEAD"))

    def test_a_session_whose_stdout_is_closed_still_records_its_answer(self):
        run = StubbedRun(self)
        r, w = os.pipe()
        os.close(r)
        stub = subprocess.Popen(self.stub_argv(run, committing(run), "--session-id", "s-3"),
                                stdin=subprocess.PIPE, stdout=w, stderr=subprocess.PIPE, env=run.env, text=True)
        os.close(w)
        _, stderr = stub.communicate("prompt", timeout=120)
        head = git(run, "rev-parse", "HEAD")
        self.assertEqual(stub.returncode, 0, stderr)
        record = run.tmp / "stub.log.sessions" / "s-3.json"
        self.assertTrue(record.exists())
        self.assertEqual(json.loads(record.read_text(encoding="utf-8"))["structured_output"]["commit"], head)
        self.assertEqual(commits(run), 1)
        resumed = self.launch(run, committing(run), "--resume", "s-3")
        self.assertEqual(resumed.returncode, 0, resumed.stderr)
        self.assertEqual(json.loads(resumed.stdout)["structured_output"]["commit"], head)
        self.assertEqual(commits(run), 1)

    def test_a_launch_with_no_session_flag_writes_no_answer_record(self):
        run = StubbedRun(self)
        reply = self.play(run, {"reply": {"status": "done"},
                                "leave": {"worktree": str(run.fixture.root), "path": "left.txt", "text": "x\n"}})
        self.assertEqual(reply["status"], "done")
        sessions = run.tmp / "stub.log.sessions"
        self.assertEqual(list(sessions.iterdir()) if sessions.exists() else [], [])

    def test_a_fresh_launch_under_a_recorded_session_id_answers_its_entry_not_the_record(self):
        run = StubbedRun(self)
        self.launch(run, {"status": "first"}, "--session-id", "s-5")
        again = self.launch(run, {"status": "second"}, "--session-id", "s-5")
        self.assertEqual(json.loads(again.stdout)["structured_output"], {"status": "second"})
        resumed = self.launch(run, {"status": "third"}, "--resume", "s-5")
        self.assertEqual(json.loads(resumed.stdout)["structured_output"], {"status": "second"})

    def test_a_fresh_launch_with_no_entry_clears_the_record_a_resume_would_replay(self):
        run = StubbedRun(self)
        self.launch(run, {"status": "first"}, "--session-id", "s-6")
        for flag in ("--session-id", "--resume"):
            argv = self.stub_argv(run, {"status": "unused"}, flag, "s-6")
            (run.tmp / "stub-scenario.json").write_text("{}", encoding="utf-8")
            done = subprocess.run(argv, input="prompt", env=run.env, capture_output=True, text=True, timeout=120)
            self.assertNotIn("structured_output", json.loads(done.stdout), flag)

    def test_a_step_is_asleep_once_the_stub_logged_and_reached_its_first_launch_wait(self):
        run = StubbedRun(self)
        scenario = run.tmp / "stub-scenario.json"
        scenario.write_text(json.dumps({"fix": {"reply": {"status": "done"}, "sleep": 0}}), encoding="utf-8")
        self.assertFalse(run.asleep("fix"))

        done = subprocess.run([sys.executable, str(STUB), str(scenario), str(run.log),
                               "--append-system-prompt-file", str(run.tmp / "fix.1.system.md")],
                              input="prompt", env=run.env, capture_output=True, text=True, timeout=120)

        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertTrue(run.asleep("fix"))
        self.assertFalse(run.asleep("other"))
        self.assertEqual([launch["key"] for launch in run.launches()], ["fix"])

    def test_the_cleanup_kills_a_recorded_process_that_is_still_itself_and_spares_a_recycled_id(self):
        run = StubbedRun(self)
        sleepers = [subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
                                     start_new_session=True) for _ in range(2)]
        for sleeper in sleepers:
            self.addCleanup(sleeper.wait)
            self.addCleanup(sleeper.kill)
        with mock.patch.dict(os.environ, {"PATH": run.env["PATH"]}):
            actual = engine_stop.process_started_at(sleepers[0].pid)
        directory = run.world.home / ".agents/state/engine/runs/r-1"
        directory.mkdir(parents=True)
        (directory / "run.json").write_text("{}", encoding="utf-8")
        recorded = [{"event": "process_started", "pid": sleepers[0].pid,
                     "started": actual.strftime("%Y-%m-%dT%H:%M:%SZ")},
                    {"event": "process_started", "pid": sleepers[1].pid, "started": "2000-01-01T00:00:00Z"}]
        (directory / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in recorded), encoding="utf-8")

        run._kill_started()

        self.assertEqual(sleepers[0].wait(timeout=30), -signal.SIGKILL)
        self.assertIsNone(sleepers[1].poll())


if __name__ == "__main__":
    unittest.main()
