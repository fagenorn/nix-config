"""Contract tests for the start-of-run check of `engine deliver`: a new run's procedure set gets the verdict `engine check` gives before the runs directory is touched, and a continued run is not judged again."""

from __future__ import annotations

import fcntl
import json
import os
import subprocess
import sys
import time
import unittest

from agent_tools.delivery.engine_ledger import creation_lock_path
from tests.test_engine_deliver import (
    LAUNCH, EngineProject, run_continued, start_deliver, step, wait_for_process_started,
)
from tests.test_engine_resume import history, rewrite, seed

TIER = "integration"

BROKEN = [step("a", "standin-record", "b"), step("b", "no-such-command", "done")]
REFUSED = {
    "breaches": [],
    "refusals": [{"defect": "unknown_command",
                  "detail": "'no-such-command' is not a command-table id.",
                  "procedure": "deliver", "step": "b"}],
    "verdict": "refused",
}


def runs_root(project: EngineProject):
    return project.world.home / ".agents/state/engine/runs"


def listing(root) -> list[str]:
    return sorted(p.name for p in root.iterdir())


def future(project: EngineProject):
    procedures = project.procedures([step("a", "standin-record", "done")])
    rewrite(procedures / "deliver.json", format=2)
    return procedures


class StartCheckTest(unittest.TestCase):
    def hold(self, path) -> int:
        fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
        self.addCleanup(os.close, fd)
        return fd

    def test_a_refused_procedure_set_prints_one_json_line_and_leaves_the_runs_directory_as_it_was(self):
        project = EngineProject(self)
        root = runs_root(project)
        root.mkdir(parents=True, exist_ok=True)
        before = listing(root)
        procedures = project.procedures(BROKEN)
        done = project.deliver(procedures)
        self.assertEqual(done.returncode, 2, done.stdout + done.stderr)
        self.assertEqual(done.stderr, "")
        self.assertEqual(len(done.stdout.splitlines()), 1)
        self.assertEqual(json.loads(done.stdout), REFUSED)
        self.assertEqual(listing(root), before)
        self.assertFalse(project.record.exists())

    def test_with_no_runs_root_a_refused_procedure_set_creates_none(self):
        project = EngineProject(self)
        self.assertFalse(runs_root(project).exists())
        done = project.deliver(project.procedures(BROKEN))
        self.assertEqual(done.returncode, 2, done.stdout + done.stderr)
        self.assertFalse(runs_root(project).exists())

    def test_a_cap_breach_alone_refuses_the_new_run_naming_the_breach(self):
        project = EngineProject(self)
        root = runs_root(project)
        root.mkdir(parents=True, exist_ok=True)
        before = listing(root)
        procedures = project.procedures([step("a", "standin-record", "done")])
        (procedures / "oversize.md").write_bytes(b"x" * 8193)
        done = project.deliver(procedures)
        self.assertEqual(done.returncode, 2, done.stdout + done.stderr)
        self.assertEqual(done.stderr, "")
        self.assertEqual(json.loads(done.stdout), {
            "breaches": [{"cap": 8192, "size": 8193, "thing": "prompt oversize.md",
                          "unit": "bytes"}],
            "refusals": [], "verdict": "refused"})
        self.assertEqual(listing(root), before)
        self.assertFalse(project.record.exists())

    def test_a_continued_run_is_not_judged_again_against_a_refused_procedure_set(self):
        project = EngineProject(self)
        first = project.deliver(project.procedures([step("a", "standin-fail", "done")]))
        self.assertEqual(first.returncode, 3, first.stdout + first.stderr)
        (run,) = project.runs()
        second = project.deliver(project.procedures(BROKEN))
        self.assertEqual(second.returncode, 3, second.stdout + second.stderr)
        self.assertEqual(json.loads(second.stdout)["end"], "needs-owner")
        self.assertEqual(project.runs(), [run])
        self.assertEqual(len(run_continued(project.events(run))), 1)

    def test_a_refused_set_leaves_an_open_run_in_an_unreadable_format_untouched(self):
        project = EngineProject(self)
        old = seed(project, future(project), "aaaa")
        root = runs_root(project)
        os.close(os.open(creation_lock_path(root, 1512), os.O_RDWR | os.O_CREAT, 0o600))
        before = listing(root)
        events = (old / "events.jsonl").read_bytes()
        done = project.deliver(project.procedures(BROKEN))
        self.assertEqual(done.returncode, 2, done.stdout + done.stderr)
        self.assertEqual(done.stderr, "")
        self.assertEqual(json.loads(done.stdout), REFUSED)
        self.assertEqual((old / "events.jsonl").read_bytes(), events)
        self.assertFalse([e for e in history(project) if e["run"] == old.name])
        self.assertEqual(project.runs(), [old])
        self.assertEqual(listing(root), before)
        self.assertFalse(project.record.exists())

    def test_a_source_changed_after_its_judgement_leaves_the_superseded_candidate_untouched(self):
        project = EngineProject(self)
        old = seed(project, future(project), "aaaa")
        procedures = project.procedures([step("a", "standin-record", "done")])
        document = json.loads((procedures / "deliver.json").read_text(encoding="utf-8"))
        document["steps"][0]["on"]["ok"] = "b"
        document["steps"].append(step("b", "no-such-command", "done"))
        edited = project.tmp / "edited.json"
        edited.write_text(json.dumps(document), encoding="utf-8")
        _, options = project.command()
        process = subprocess.run(
            [sys.executable, "-c", LAUNCH, str(edited), "deliver", "1512", "--procedures",
             str(procedures)], capture_output=True, timeout=120, **options)
        self.assertEqual(process.returncode, 2, process.stdout + process.stderr)
        self.assertEqual(process.stderr, "")
        self.assertEqual(json.loads(process.stdout), REFUSED)
        self.assertEqual((old / "events.jsonl").read_bytes(), b"")
        self.assertFalse([e for e in history(project) if e["run"] == old.name])
        self.assertEqual(project.runs(), [old])
        self.assertFalse(project.record.exists())

    def test_a_held_run_lock_answers_before_the_check_even_on_an_unreadable_copy(self):
        project = EngineProject(self)
        start_deliver(self, project, project.procedures([step("a", "standin-block", "done")]))
        run = wait_for_process_started(project)
        rewrite(run / "procedure/deliver.json", format=2)
        done = project.deliver(project.procedures(BROKEN))
        self.assertEqual(done.returncode, 4, done.stdout + done.stderr)
        self.assertEqual(len(done.stdout.splitlines()), 1)
        self.assertEqual(json.loads(done.stdout)["run"], run.name)

    def test_two_open_unreadable_runs_are_refused_on_stderr_before_a_broken_set_is_judged(self):
        project = EngineProject(self)
        procedures = future(project)
        runs = [seed(project, procedures, "aaaa"), seed(project, procedures, "bbbb")]
        done = project.deliver(project.procedures(BROKEN))
        self.assertEqual(done.returncode, 2, done.stdout + done.stderr)
        self.assertEqual(done.stdout, "")
        self.assertEqual(len(done.stderr.splitlines()), 1)
        for run in runs:
            self.assertIn(run.name, done.stderr)
            self.assertEqual((run / "events.jsonl").read_bytes(), b"")
        self.assertEqual(project.runs(), sorted(runs))

    def test_a_lock_renewal_answers_exit_4_before_a_broken_set_is_judged(self):
        project = EngineProject(self)
        first = project.deliver(project.procedures([step("a", "standin-fail", "done")]))
        self.assertEqual(first.returncode, 3, first.stdout + first.stderr)
        run = project.runs()[0]
        rewrite(run / "procedure/deliver.json", format=2)
        creation = self.hold(creation_lock_path(runs_root(project), 1512))
        fcntl.flock(creation, fcntl.LOCK_EX)
        held = self.hold(run / "lock")
        fcntl.flock(held, fcntl.LOCK_EX)
        os.ftruncate(held, 0)
        before = (run / "events.jsonl").read_bytes()
        process = start_deliver(self, project, project.procedures(BROKEN))
        time.sleep(1.0)
        self.assertIsNone(process.poll())
        os.write(held, json.dumps({"pid": os.getpid(), "started": "2026-11-21T00:00:00Z"}).encode())
        fcntl.flock(creation, fcntl.LOCK_UN)
        stdout, stderr = process.communicate(timeout=60)
        self.assertEqual(process.returncode, 4, stdout + stderr)
        self.assertEqual(json.loads(stdout)["run"], run.name)
        self.assertEqual((run / "events.jsonl").read_bytes(), before)

    def test_a_refusal_the_check_does_not_make_keeps_stdout_empty(self):
        project = EngineProject(self)
        done = project.deliver(project.procedures([step("a", "standin-record", "done")],
                                                  inputs=("issue", "branch")))
        self.assertEqual(done.returncode, 2, done.stdout + done.stderr)
        self.assertEqual(done.stdout, "")
        self.assertEqual(len(done.stderr.splitlines()), 1)
        self.assertIn("branch", done.stderr)
        self.assertEqual(project.runs(), [])

    def test_with_the_issue_lock_file_present_the_judgement_waits_for_the_lock(self):
        project = EngineProject(self)
        root = runs_root(project)
        root.mkdir(parents=True)
        creation = self.hold(creation_lock_path(root, 1512))
        fcntl.flock(creation, fcntl.LOCK_EX)
        process = start_deliver(self, project, project.procedures(BROKEN))
        time.sleep(1.0)
        self.assertIsNone(process.poll())
        fcntl.flock(creation, fcntl.LOCK_UN)
        stdout, stderr = process.communicate(timeout=60)
        self.assertEqual(process.returncode, 2, stdout + stderr)
        self.assertEqual(stderr, "")
        self.assertEqual(json.loads(stdout), REFUSED)
        self.assertEqual(project.runs(), [])


if __name__ == "__main__":
    unittest.main()
