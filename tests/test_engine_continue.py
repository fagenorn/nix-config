"""Contract tests for the continuation of `engine deliver`: a run stopped at a step is continued
by the next `engine deliver`, which resumes it instead of starting a new run.

Split from tests/test_engine_deliver.py to keep that file under the size budget; the hermetic project,
the stand-in command and the shared step helpers come from there.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from agent_tools.delivery import engine_ledger, engine_shell
from tests.test_engine_deliver import (
    EngineProject, heads, mutating, run_continued, shape, start_deliver, step,
    wait_for_process_started)

TIER = "integration"  # every case runs `engine deliver` against the stand-in command

def gated(project: EngineProject, b_holds: str = "head", c_holds: str = "run") -> Path:
    return project.procedures([
        step("a", "count-a", "c"), step("b", "count-b", "g", holds=b_holds),
        step("c", "count-c", "b", holds=c_holds), step("g", "standin-gate", "done"),
        step("d", "count-d", "done")],
        stops={"needs-owner": {"need": "owner-decision", "reenter": "d"}})



def head(project: EngineProject) -> str:
    return project.world.git(project.root, "rev-parse", "HEAD").strip()



def looped(project: EngineProject) -> Path:
    a = step("a", "count-a", "p", holds="live")
    p = step("p", "standin-parity", None,
             on={"ok": "m", "failed": "needs-owner", "exhausted": "b"})
    p["max_visits"] = 2
    m = step("m", "standin-effect", None,
             on={"ok": "p", "failed": "needs-owner", "exhausted": "b"})
    m.update({"in": ["p.n"], "max_visits": 2, "mutates": True,
              "check": {"command": "standin-effect-check"}})
    return project.procedures([a, p, m, step("b", "count-b", "done")])


class ContinueTest(unittest.TestCase):
    def first_stop(self, project: EngineProject, procedures: Path) -> Path:
        first = project.deliver(procedures)
        self.assertEqual(first.returncode, 3, first.stdout + first.stderr)
        return project.runs()[0]

    def test_a_second_deliver_continues_a_stopped_run_at_its_stops_reentry_step(self):
        project = EngineProject(self)
        procedures = gated(project)
        first = project.deliver(procedures)
        self.assertEqual(first.returncode, 3, first.stdout + first.stderr)
        self.assertEqual(json.loads(first.stdout)["end"], "needs-owner")
        second = project.deliver(procedures)
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        line = json.loads(second.stdout)
        self.assertEqual(line["end"], "done")
        self.assertEqual(line["run"], json.loads(first.stdout)["run"])
        self.assertEqual(len(project.runs()), 1)
        events = project.events(project.runs()[0])
        continued = run_continued(events)
        self.assertEqual(len(continued), 1)
        self.assertIsInstance(continued[0].pop("at"), str)
        self.assertEqual(continued[0], {"event": "run_continued", "step": "d"})
        kinds = [e["event"] for e in events]
        self.assertLess(kinds.index("stop_reached"), kinds.index("run_continued"))
        self.assertEqual([project.calls(n) for n in ("a", "c", "b", "gate", "d")],
                         [1, 1, 1, 1, 1])
        self.assertEqual(heads(events, "b"), [head(project)])
        self.assertEqual(heads(events, "a"), [None])
        self.assertEqual(heads(events, "c"), [None])
        self.assertTrue(all("head" not in e for e in events
                            if e["event"] == "result_stored" and e["step"] != "b"))

    def test_a_moved_head_reenters_at_the_earliest_head_step_and_runs_no_earlier_run_step_again(self):
        project = EngineProject(self)
        procedures = gated(project, c_holds="head")
        first = project.deliver(procedures)
        self.assertEqual(first.returncode, 3, first.stdout + first.stderr)
        before = head(project)
        project.world.git(project.root, "commit", "--quiet", "--allow-empty", "-m", "moved")
        (project.tmp / "gate-open").write_text("go", encoding="utf-8")
        second = project.deliver(procedures)
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertEqual(json.loads(second.stdout)["end"], "done")
        self.assertEqual(json.loads(second.stdout)["run"], json.loads(first.stdout)["run"])
        events = project.events(project.runs()[0])
        continued = run_continued(events)
        self.assertEqual([(e["step"], e["visit"]) for e in continued], [("c", 1)])
        self.assertEqual([project.calls(n) for n in ("a", "c", "b", "gate", "d")],
                         [1, 2, 2, 2, 0])
        self.assertEqual(heads(events, "c"), [before, head(project)])
        self.assertEqual(heads(events, "b"), [before, head(project)])
        for name in ("c", "b", "g"):
            self.assertEqual([e["visit"] for e in events
                              if e["event"] == "step_entered" and e["step"] == name], [1, 2])

    def test_a_live_result_is_redone_by_a_continued_run_though_the_head_stayed(self):
        project = EngineProject(self)
        procedures = gated(project, b_holds="live", c_holds="live")
        first = project.deliver(procedures)
        self.assertEqual(first.returncode, 3, first.stdout + first.stderr)
        (project.tmp / "gate-open").write_text("go", encoding="utf-8")
        second = project.deliver(procedures)
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        events = project.events(project.runs()[0])
        self.assertEqual([(e["step"], e["visit"]) for e in run_continued(events)], [("c", 1)])
        self.assertEqual([project.calls(n) for n in ("a", "c", "b", "gate", "d")],
                         [1, 2, 2, 2, 0])

    def test_a_stop_that_reenters_a_graded_decide_grades_it_again_at_its_visit(self):
        project = EngineProject(self)
        procedures = project.procedures([
            step("r", "count-a", "t"),
            {"id": "t", "stage": "setup", "kind": "decide", "grader": "toy-tally",
             "in": ["run.issue"], "holds": "run", "on": {"accept": "done",
                                                         "revise": "needs-owner"}}],
            stops={"needs-owner": {"need": "owner-decision", "reenter": "t"}})
        first = project.deliver(procedures)
        self.assertEqual(first.returncode, 3, first.stdout + first.stderr)
        second = project.deliver(procedures)
        self.assertEqual(second.returncode, 3, second.stdout + second.stderr)
        self.assertEqual(json.loads(second.stdout)["run"], json.loads(first.stdout)["run"])
        self.assertEqual(len(project.runs()), 1)
        events = project.events(project.runs()[0])
        continued = run_continued(events)
        self.assertEqual(len(continued), 1)
        self.assertIsInstance(continued[0].pop("at"), str)
        self.assertEqual(continued[0], {"event": "run_continued", "step": "t", "visit": 1})
        self.assertEqual(len([e for e in events if e["event"] == "stop_reached"]), 2)
        self.assertEqual(project.calls("a"), 1)

    def test_a_result_stored_just_before_its_grading_is_graded_from_the_ledger_not_run_again(self):
        project = EngineProject(self)
        procedures = project.procedures([
            step("a", "standin-gate", "c", failed="b"), step("b", "count-b", "done"),
            step("c", "count-c", "done")])
        first = project.deliver(procedures)
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        run = project.runs()[0]
        lines = (run / "events.jsonl").read_text().splitlines(keepends=True)
        cut = next(i for i, line in enumerate(lines)
                   if json.loads(line)["event"] == "result_stored") + 1
        self.assertEqual(json.loads(lines[cut - 1])["outcome"], "failed")
        (run / "events.jsonl").write_text("".join(lines[:cut]), encoding="utf-8")
        (run / "results/b.1.json").unlink()
        second = project.deliver(procedures)
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertEqual(json.loads(second.stdout)["run"], run.name)
        after = project.events(run)[cut:]
        self.assertEqual(shape(after), [
            ("outcome_graded", "a", 1), ("transition_taken", "a", 1),
            ("run_continued", "b", 1), ("step_entered", "b", 1), ("process_started", "b", 1),
            ("result_stored", "b", 1), ("outcome_graded", "b", 1),
            ("transition_taken", "b", 1), ("run_done", None, None)])
        self.assertEqual(after[0]["outcome"], "failed")
        self.assertEqual(after[1]["to"], "b")
        self.assertEqual([project.calls("gate"), project.calls("c"), project.calls("b")],
                         [1, 0, 2])

    def test_a_stop_the_owner_never_saw_is_reported_not_walked_past(self):
        for last in ("result_stored", "transition_taken"):
            with self.subTest(killed_after=last):
                project = EngineProject(self)
                procedures = project.procedures([
                    step("a", "standin-gate", "c"), step("b", "count-b", "done"),
                    step("c", "count-c", "done")],
                    stops={"needs-owner": {"need": "owner-decision", "reenter": "b"}})
                run = self.first_stop(project, procedures)
                lines = (run / "events.jsonl").read_text().splitlines(keepends=True)
                cut = next(i for i, line in enumerate(lines)
                           if json.loads(line)["event"] == last) + 1
                (run / "events.jsonl").write_text("".join(lines[:cut]), encoding="utf-8")
                second = project.deliver(procedures)
                self.assertEqual(second.returncode, 3, second.stdout + second.stderr)
                self.assertEqual(json.loads(second.stdout)["end"], "needs-owner")
                after = [e["event"] for e in project.events(run)[cut:]]
                owed = ["outcome_graded", "transition_taken"] if last == "result_stored" else []
                self.assertEqual(after, [*owed, "stop_reached"])
                self.assertEqual(run_continued(project.events(run)), [])
                self.assertEqual(project.calls("b"), 0)
                third = project.deliver(procedures)
                self.assertEqual(third.returncode, 0, third.stdout + third.stderr)
                self.assertEqual([e["step"] for e in run_continued(project.events(run))], ["b"])

    def test_a_run_killed_between_its_grading_and_its_transition_records_the_transition_once(self):
        project = EngineProject(self)
        procedures = project.procedures([
            step("a", "standin-gate", "c", failed="b"), step("b", "count-b", "done"),
            step("c", "count-c", "done")])
        first = project.deliver(procedures)
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        run = project.runs()[0]
        lines = (run / "events.jsonl").read_text().splitlines(keepends=True)
        cut = next(i for i, line in enumerate(lines)
                   if json.loads(line)["event"] == "outcome_graded") + 1
        (run / "events.jsonl").write_text("".join(lines[:cut]), encoding="utf-8")
        (run / "results/b.1.json").unlink()
        second = project.deliver(procedures)
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        after = project.events(run)[cut:]
        self.assertEqual(shape(after), [
            ("transition_taken", "a", 1),
            ("run_continued", "b", 1), ("step_entered", "b", 1), ("process_started", "b", 1),
            ("result_stored", "b", 1), ("outcome_graded", "b", 1),
            ("transition_taken", "b", 1), ("run_done", None, None)])
        self.assertEqual((after[0]["outcome"], after[0]["to"]), ("failed", "b"))

    def test_a_decision_graded_again_after_a_continue_leaves_its_transition_under_a_new_visit(self):
        project = EngineProject(self)
        decision = {"id": "t", "stage": "setup", "kind": "decide", "grader": "toy-tally",
                    "holds": "run", "in": ["run.issue"],
                    "on": {"accept": "done", "revise": "needs-owner"}}
        procedures = project.procedures(
            [step("r", "standin-json", "t"), decision],
            stops={"needs-owner": {"need": "owner-decision", "reenter": "t"}})
        run = self.first_stop(project, procedures)
        second = project.deliver(procedures)
        self.assertEqual(second.returncode, 3, second.stdout + second.stderr)
        events = project.events(run)
        self.assertEqual(
            [(e["event"], e["step"], e["visit"]) for e in events
             if e["event"] in ("transition_taken", "run_continued")],
            [("transition_taken", "r", 1), ("transition_taken", "t", 1),
             ("run_continued", "t", 1), ("transition_taken", "t", 2)])
        self.assertEqual([e["event"] for e in events[-2:]], ["transition_taken", "stop_reached"])

    def test_a_stop_reached_by_the_opening_decision_is_reported_after_a_kill_left_no_event(self):
        project = EngineProject(self)
        decision = {"id": "d", "stage": "setup", "kind": "decide", "grader": "toy-tally",
                    "holds": "run", "in": ["run.issue"],
                    "on": {"accept": "done", "revise": "needs-owner"}}
        procedures = project.procedures([decision])
        run = self.first_stop(project, procedures)
        (run / "events.jsonl").write_text("", encoding="utf-8")
        second = project.deliver(procedures)
        self.assertEqual(second.returncode, 3, second.stdout + second.stderr)
        self.assertEqual(second.stderr, "")
        self.assertEqual(json.loads(second.stdout)["end"], "needs-owner")
        self.assertEqual([e["event"] for e in project.events(run)],
                         ["transition_taken", "stop_reached"])

    def test_the_head_is_read_from_the_project_though_git_dir_names_another_checkout(self):
        project = EngineProject(self)
        other = Path(tempfile.mkdtemp(dir=project.tmp))
        project.world.git(other, "init", "--quiet")
        project.world.git(other, "commit", "--quiet", "--allow-empty", "-m", "elsewhere")
        elsewhere = project.world.git(other, "rev-parse", "HEAD").strip()
        before = head(project)
        self.assertNotEqual(elsewhere, before)
        with mock.patch.dict(os.environ, {"GIT_DIR": str(other / ".git")}):
            self.assertEqual(engine_shell.read_head(str(project.root)), before)
        project.world.git(project.root, "commit", "--quiet", "--allow-empty", "-m", "moved")
        after = head(project)
        self.assertNotEqual(after, before)
        with mock.patch.dict(os.environ, {"GIT_DIR": str(other / ".git")}):
            self.assertEqual(engine_shell.read_head(str(project.root)), after)

    def test_a_head_that_moves_while_its_step_runs_leaves_the_result_stale(self):
        project = EngineProject(self)
        procedures = project.procedures(
            [step("a", "standin-block", "g", holds="head"), step("g", "standin-gate", "done")],
            stops={"needs-owner": {"need": "owner-decision", "reenter": "g"}})
        first = start_deliver(self, project, procedures)
        run = wait_for_process_started(project)
        project.world.git(project.root, "commit", "--quiet", "--allow-empty", "-m", "moved")
        project.release.write_text("go", encoding="utf-8")
        stdout, stderr = first.communicate(timeout=60)
        self.assertEqual(first.returncode, 3, stdout + stderr)
        self.assertEqual(heads(project.events(run), "a"), [None])
        (project.tmp / "gate-open").write_text("go", encoding="utf-8")
        second = project.deliver(procedures)
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        events = project.events(run)
        self.assertEqual([(e["step"], e["visit"]) for e in run_continued(events)], [("a", 1)])
        self.assertEqual(len([e for e in events
                              if e["event"] == "process_started" and e["step"] == "a"]), 2)
        self.assertEqual(project.calls("gate"), 2)
        self.assertEqual(heads(events, "a"), [None, head(project)])

    def test_a_continued_run_reads_its_own_procedure_copy_not_the_source(self):
        project = EngineProject(self)
        procedures = gated(project)
        first = project.deliver(procedures)
        self.assertEqual(first.returncode, 3, first.stdout + first.stderr)
        shutil.rmtree(procedures)
        second = project.deliver(procedures)
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertEqual(json.loads(second.stdout)["end"], "done")
        self.assertEqual(project.calls("d"), 1)

    def seed(self, project: EngineProject, procedures: Path, *tokens: str) -> list[Path]:
        root = project.world.home / ".agents/state/engine/runs"
        now = datetime(2026, 11, 21, tzinfo=timezone.utc)
        return [engine_ledger.create_run(
            project="example/engine", issue=1512, procedure="deliver",
            procedures_dir=procedures, platform_revision="source", host="test",
            inputs={"issue": 1512}, now=now, token=token, root=root) for token in tokens]

    def test_two_open_runs_of_the_issue_are_refused_and_left_unchanged(self):
        project = EngineProject(self)
        procedures = project.procedures([step("a", "standin-record", "done")])
        runs = self.seed(project, procedures, "aaaa", "bbbb")
        done = project.deliver(procedures)
        self.assertEqual(done.returncode, 2, done.stdout + done.stderr)
        self.assertEqual(done.stdout, "")
        self.assertEqual(len(done.stderr.splitlines()), 1, done.stderr)
        for run in runs:
            self.assertIn(run.name, done.stderr)
            self.assertEqual((run / "events.jsonl").read_bytes(), b"")
        self.assertEqual(project.runs(), sorted(runs))
        self.assertFalse(project.record.exists())

    def test_a_run_that_reached_done_without_its_done_event_is_finished_without_running_a_step(self):
        project = EngineProject(self)
        procedures = project.procedures([step("a", "standin-record", "done")])
        (run,) = self.seed(project, procedures, "aaaa")
        at = "2026-11-21T00:00:01Z"
        engine_ledger.append_event(run, {"event": "step_entered", "at": at, "step": "a",
                                         "visit": 1, "stage": "setup"})
        engine_ledger.store_result(run, step="a", visit=1, result={}, at=at, wall_seconds=0,
                                   turns=0, tokens=dict(engine_shell.NO_TOKENS), spend_usd=0,
                                   outcome="ok")
        engine_ledger.append_event(run, {"event": "outcome_graded", "at": at, "step": "a",
                                         "visit": 1, "outcome": "ok"})
        engine_ledger.append_event(run, {"event": "transition_taken", "at": at, "step": "a",
                                         "visit": 1, "outcome": "ok", "to": "done"})
        done = project.deliver(procedures)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(json.loads(done.stdout)["end"], "done")
        events = project.events(run)
        self.assertEqual(events[-1]["event"], "run_done")
        self.assertEqual(run_continued(events), [])
        self.assertFalse(project.record.exists())


class MutatingContinueTest(unittest.TestCase):
    def test_a_run_killed_after_a_mutating_command_took_effect_does_not_run_it_again(self):
        project = EngineProject(self)
        procedures = mutating(project)
        (project.tmp / "kill-after").write_text("1512", encoding="utf-8")
        first = project.deliver(procedures)
        self.assertEqual(first.returncode, -signal.SIGKILL, first.stdout + first.stderr)
        self.assertEqual(project.calls("effect"), 1)
        run = project.runs()[0]
        self.assertFalse([e for e in project.events(run)
                          if e["event"] == "result_stored" and e["step"] == "m"])
        second = project.deliver(procedures)
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        line = json.loads(second.stdout)
        self.assertEqual((line["end"], line["run"]), ("done", run.name))
        self.assertEqual(project.runs(), [run])
        self.assertEqual(project.calls("effect"), 1)
        self.assertEqual(project.calls("checks"), 1)
        self.assertEqual([(e["step"], e["visit"]) for e in run_continued(project.events(run))],
                         [("m", 1)])
        self.assertEqual(json.loads((run / "results/m.2.json").read_text()),
                         {"argv": ["1512"], "verdict": "ok"})
        self.assertEqual((project.calls("a"), project.calls("b")), (1, 1))

    def test_a_rewind_through_a_mutating_loop_checks_every_replayed_visit_and_repeats_no_effect(self):
        project = EngineProject(self)
        procedures = looped(project)
        (project.tmp / "kill-after").write_text("1", encoding="utf-8")
        first = project.deliver(procedures)
        self.assertEqual(first.returncode, -signal.SIGKILL, first.stdout + first.stderr)
        self.assertEqual(project.argvs("effect"), [["0"], ["1"]])
        run = project.runs()[0]
        second = project.deliver(procedures)
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        line = json.loads(second.stdout)
        self.assertEqual((line["end"], line["run"]), ("done", run.name))
        events = project.events(run)
        self.assertEqual([(e["step"], e["visit"]) for e in run_continued(events)], [("a", 1)])
        self.assertEqual(project.argvs("effect"), [["0"], ["1"]])
        self.assertEqual(project.argvs("checks"), [["0"], ["1"]])
        self.assertEqual([e["visit"] for e in events
                          if e["event"] == "step_entered" and e["step"] == "m"], [1, 2, 3, 4])
        self.assertEqual(json.loads((run / "results/m.3.json").read_text()),
                         {"argv": ["0"], "verdict": "ok"})
        self.assertEqual(json.loads((run / "results/m.4.json").read_text()),
                         {"argv": ["1"], "verdict": "ok"})
        self.assertEqual((project.calls("a"), project.calls("b")), (2, 1))

    def test_a_kill_after_the_first_iteration_effect_repeats_no_effect_when_the_replay_visits_other_arguments_first(self):
        project = EngineProject(self)
        procedures = looped(project)
        (project.tmp / "kill-after").write_text("0", encoding="utf-8")
        first = project.deliver(procedures)
        self.assertEqual(first.returncode, -signal.SIGKILL, first.stdout + first.stderr)
        self.assertEqual(project.argvs("effect"), [["0"]])
        second = project.deliver(procedures)
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertEqual(json.loads(second.stdout)["end"], "done")
        self.assertEqual(project.argvs("effect"), [["0"], ["1"]])
        # the check is owed to the step, so the other arguments are checked too: harmless, they ran nothing yet
        self.assertEqual(project.argvs("checks"), [["1"], ["0"]])

    def test_a_mutating_command_whose_check_finds_no_effect_runs_after_the_check(self):
        project = EngineProject(self)
        procedures = mutating(project)
        (project.tmp / "kill-before").write_text("go", encoding="utf-8")
        first = project.deliver(procedures)
        self.assertEqual(first.returncode, -signal.SIGKILL, first.stdout + first.stderr)
        self.assertEqual(project.calls("effect"), 0)
        second = project.deliver(procedures)
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertEqual(json.loads(second.stdout)["end"], "done")
        self.assertEqual((project.calls("effect"), project.calls("checks")), (1, 1))
        self.assertEqual(json.loads((project.runs()[0] / "results/m.2.json").read_text()),
                         {"argv": ["1512"]})

    def test_a_first_visit_of_a_mutating_step_runs_no_check(self):
        project = EngineProject(self)
        done = project.deliver(mutating(project))
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(json.loads(done.stdout)["end"], "done")
        self.assertEqual((project.calls("effect"), project.calls("checks")), (1, 0))
