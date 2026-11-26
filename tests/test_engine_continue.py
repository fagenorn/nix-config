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
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from agent_tools.delivery import engine_heads, engine_ledger, engine_shell
from agent_tools.delivery.engine_heads import Settled
from tests import never_rise_world
from tests.test_engine_deliver import (
    EngineProject, heads, mutating, run_continued, shape, start_deliver, step,
    wait_for_process_started)

from tests.test_engine_ledger import EXAMPLES, new_run, store

TIER = "integration"  # every case runs `engine deliver` against the stand-in command

def gated(project: EngineProject, b_holds: str = "head", c_holds: str = "run") -> Path:
    return project.procedures([
        step("a", "count-a", "c"), step("b", "count-b", "g", holds=b_holds),
        step("c", "count-c", "b", holds=c_holds), step("g", "standin-gate", "done"),
        step("d", "count-d", "done")],
        stops={"needs-owner": {"need": "owner-decision", "reenter": "d"}})



def head(project: EngineProject) -> str:
    return project.world.git(project.root, "rev-parse", "HEAD").strip()



def head_of(project: EngineProject, root: Path) -> str:
    return project.world.git(root, "rev-parse", "HEAD").strip()


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

    def checkout_procedures(self, project: EngineProject, middle: list[dict],
                            stops: dict, source: str = "standin-side") -> Path:
        project.world.git(project.root, "worktree", "add", "-q", "-b", "side",
                          str(project.tmp / "side"))
        return project.procedures(
            [step("p", source, middle[0]["id"]), *middle,
             step("g", "standin-gate", "done")], stops=stops)

    def based_procedures(self, project: EngineProject) -> tuple[Path, Path]:
        """A run holding a `b` result for the side checkout's merge base with `refs/remotes/origin/main`."""
        b = step("b", "count-b", "g", holds="head")
        b.update({"in": ["p.path", "p.branch"], "repository": "p.path", "base": "p.branch"})
        procedures = self.checkout_procedures(
            project, [b], {"needs-owner": {"need": "owner-decision", "reenter": "g"}}, "standin-based")
        side = project.tmp / "side"
        project.world.git(side, "commit", "--quiet", "--allow-empty", "-m", "side")
        return procedures, side

    def test_a_result_holding_for_a_merge_base_is_kept_while_the_base_is_unchanged(self):
        project = EngineProject(self)
        procedures, side = self.based_procedures(project)
        first = project.deliver(procedures)
        self.assertEqual(first.returncode, 3, first.stdout + first.stderr)
        second = project.deliver(procedures)
        self.assertEqual(second.returncode, 3, second.stdout + second.stderr)
        events = project.events(project.runs()[0])
        self.assertEqual(run_continued(events)[-1]["step"], "g")
        self.assertEqual(project.calls("b"), 1)
        (stored,) = [e for e in events if e["event"] == "result_stored" and e["step"] == "b"]
        merge_base = project.world.git(side, "merge-base", "refs/remotes/origin/main", "HEAD").strip()
        self.assertEqual(stored["base"], {"ref": "refs/remotes/origin/main", "sha": merge_base})
        self.assertEqual(stored["head"], head_of(project, side))

    def test_a_continue_after_the_integration_branch_took_the_topics_commits_runs_the_step_again(self):
        project = EngineProject(self)
        procedures, side = self.based_procedures(project)
        first = project.deliver(procedures)
        self.assertEqual(first.returncode, 3, first.stdout + first.stderr)
        project.world.git(project.root, "update-ref", "refs/remotes/origin/main", head_of(project, side))
        second = project.deliver(procedures)
        self.assertEqual(second.returncode, 3, second.stdout + second.stderr)
        events = project.events(project.runs()[0])
        self.assertEqual(run_continued(events)[-1]["step"], "b")
        self.assertEqual(project.calls("b"), 2)
        stored = [e for e in events if e["event"] == "result_stored" and e["step"] == "b"]
        self.assertEqual([e["head"] for e in stored], [head_of(project, side)] * 2)
        self.assertNotEqual(stored[0]["base"], stored[1]["base"])
        self.assertNotIn("reused_from", stored[1])

    def test_a_head_step_naming_a_checkout_is_judged_by_that_checkouts_head(self):
        project = EngineProject(self)
        side = project.tmp / "side"
        b = step("b", "count-b", "g", holds="head")
        b.update({"in": ["p.path"], "repository": "p.path"})
        procedures = self.checkout_procedures(
            project, [b], {"needs-owner": {"need": "owner-decision", "reenter": "g"}})
        first = project.deliver(procedures)
        self.assertEqual(first.returncode, 3, first.stdout + first.stderr)
        run = json.loads(first.stdout)["run"]
        project.world.git(project.root, "commit", "--quiet", "--allow-empty", "-m", "elsewhere")
        second = project.deliver(procedures)
        self.assertEqual(second.returncode, 3, second.stdout + second.stderr)
        self.assertEqual(json.loads(second.stdout)["run"], run)
        self.assertEqual(len(project.runs()), 1)
        events = project.events(project.runs()[0])
        self.assertEqual(run_continued(events)[-1]["step"], "g")
        self.assertEqual(project.calls("b"), 1)
        stored = [e for e in events if e["event"] == "result_stored" and e["step"] == "b"]
        self.assertEqual([e["repository"] for e in stored], [str(side)])
        self.assertEqual(heads(events, "b"), [head_of(project, side)])
        project.world.git(side, "commit", "--quiet", "--allow-empty", "-m", "moved")
        third = project.deliver(procedures)
        self.assertEqual(third.returncode, 3, third.stdout + third.stderr)
        self.assertEqual(json.loads(third.stdout)["run"], run)
        events = project.events(project.runs()[0])
        self.assertEqual(run_continued(events)[-1]["step"], "b")
        self.assertEqual(project.calls("b"), 2)
        self.assertEqual(heads(events, "b")[-1], head_of(project, side))
        self.assertNotEqual(heads(events, "b")[0], heads(events, "b")[-1])

    def test_a_head_that_moves_while_a_checkout_step_runs_ends_it_out_of_bounds(self):
        project = EngineProject(self)
        side = project.tmp / "side"
        a = step("a", "standin-block", "g", holds="head",
                 on={"ok": "g", "failed": "needs-owner", "out-of-bounds": "moved"})
        a.update({"in": ["p.path"], "repository": "p.path"})
        procedures = self.checkout_procedures(project, [a], {
            "needs-owner": {"need": "owner-decision", "reenter": "g"},
            "moved": {"need": "owner-decision", "reenter": "a"}})
        first = start_deliver(self, project, procedures)
        deadline = time.monotonic() + 30
        while not any(e["event"] == "process_started" and e["step"] == "a"
                      for run in project.runs() for e in project.events(run)):
            self.assertLess(time.monotonic(), deadline, "step a never started its process")
            time.sleep(0.05)
        project.world.git(side, "commit", "--quiet", "--allow-empty", "-m", "moved")
        project.release.write_text("go", encoding="utf-8")
        stdout, stderr = first.communicate(timeout=60)
        self.assertEqual(first.returncode, 3, stdout + stderr)
        self.assertEqual(json.loads(stdout)["end"], "moved")
        run = project.runs()[0]
        events = project.events(run)
        self.assertEqual(json.loads((run / "results/a.1.json").read_text()),
                         {"bound": "head-moved"})
        stored = [e for e in events if e["event"] == "result_stored" and e["step"] == "a"]
        self.assertEqual([(e["outcome"], "head" in e, "repository" in e) for e in stored],
                         [("out-of-bounds", False, False)])
        self.assertEqual([e for e in events
                          if e["event"] == "step_entered" and e["step"] == "g"], [])

    def test_a_checkout_that_is_not_an_absolute_path_is_refused_without_running_its_command(self):
        for command in ("standin-relative", "standin-listed"):
            with self.subTest(command):
                project = EngineProject(self)
                b = step("b", "count-b", "g", holds="head", refused="bad")
                b.update({"in": ["p.path"], "repository": "p.path"})
                procedures = project.procedures(
                    [step("p", command, "b"), b, step("g", "standin-gate", "done")],
                    stops={"bad": {"need": "owner-decision", "reenter": "b"},
                           "needs-owner": {"need": "owner-decision", "reenter": "g"}})
                done = project.deliver(procedures)
                self.assertEqual(done.returncode, 3, done.stdout + done.stderr)
                self.assertEqual(json.loads(done.stdout)["end"], "bad")
                self.assertEqual(project.calls("b"), 0)
                run = project.runs()[0]
                result = json.loads((run / "results/b.1.json").read_text())
                self.assertEqual(result["verdict"], "refused")
                self.assertTrue(result["reason"].startswith(
                    "repository p.path is not an absolute path"), result)
                stored = [e for e in project.events(run)
                          if e["event"] == "result_stored" and e["step"] == "b"]
                self.assertEqual([("head" in e, "repository" in e) for e in stored],
                                 [(False, False)])

    def test_a_refused_checkout_opens_no_wait_its_step_declares(self):
        project = EngineProject(self)
        b = step("b", "count-b", "g", holds="head", refused="bad")
        b.update({"in": ["p.path"], "repository": "p.path", "wait": "checks"})
        procedures = project.procedures(
            [step("p", "standin-relative", "b"), b, step("g", "standin-gate", "done")],
            stops={"bad": {"need": "owner-decision", "reenter": "b"},
                   "needs-owner": {"need": "owner-decision", "reenter": "g"}})
        done = project.deliver(procedures)
        self.assertEqual(done.returncode, 3, done.stdout + done.stderr)
        kinds = [e["event"] for e in project.events(project.runs()[0])]
        self.assertEqual(kinds.count("wait_started"), kinds.count("wait_ended"))
        self.assertNotIn("wait_started", kinds)

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

    def test_a_run_saved_in_the_previous_procedure_format_is_superseded_by_a_new_run(self):
        project = EngineProject(self)
        procedures = gated(project)
        first = project.deliver(procedures)
        self.assertEqual(first.returncode, 3, first.stdout + first.stderr)
        (old,) = project.runs()
        saved = old / "procedure/deliver.json"
        document = json.loads(saved.read_text(encoding="utf-8"))
        self.assertEqual(document["format"], 2)
        saved.write_text(json.dumps({**document, "format": 1}), encoding="utf-8")
        second = project.deliver(procedures)
        self.assertEqual(second.returncode, 3, second.stdout + second.stderr)
        (earlier, later) = project.runs()
        self.assertEqual(earlier, old)
        stops = [e for e in project.events(old) if e["event"] == "stop_reached"]
        self.assertEqual((stops[-1]["stop"], stops[-1]["need"]), ("superseded", "nothing"))
        self.assertEqual(json.loads(second.stdout)["run"], later.name)
        self.assertEqual(json.loads((later / "procedure/deliver.json").read_text())["format"], 2)
        self.assertEqual(project.calls("a"), 2)

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

    def test_a_call_continued_after_a_kill_checks_a_childs_change_before_it_can_repeat_it(self):
        project = EngineProject(self)
        fan = {"id": "fan", "stage": "landing", "kind": "call", "holds": "run",
               "procedure": "fan-child", "on": {"done": "done", "child-stop": "needs-owner"}}
        m = step("m", "standin-effect", "done", failed="child-stop", mutates=True)
        m["check"] = {"command": "standin-effect-check"}
        child = {"steps": [m], "inputs": ["issue"],
                 "stops": {"child-stop": {"need": "retry", "reenter": "m"}}}
        procedures = project.procedures([fan], children={"fan-child": child})
        (project.tmp / "kill-after").write_text("1512", encoding="utf-8")
        first = project.deliver(procedures)
        self.assertEqual(first.returncode, -signal.SIGKILL, first.stdout + first.stderr)
        self.assertEqual(project.argvs("effect"), [["1512"]])
        second = project.deliver(procedures)
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertEqual(json.loads(second.stdout)["end"], "done")
        self.assertEqual(project.argvs("effect"), [["1512"]])
        self.assertEqual(project.argvs("checks"), [["1512"]])

    def test_a_first_visit_of_a_mutating_step_runs_no_check(self):
        project = EngineProject(self)
        done = project.deliver(mutating(project))
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(json.loads(done.stdout)["end"], "done")
        self.assertEqual((project.calls("effect"), project.calls("checks")), (1, 0))


class ReuseTest(unittest.TestCase):
    """A checkout step at an unchanged head takes the result an earlier run of the delivery stored."""

    def checkout_step(self, id: str, command: str, ok: str, repository: bool = True) -> dict:
        found = step(id, command, ok, holds="head")
        found["in"] = ["p.path"]
        if repository:
            found["repository"] = "p.path"
        return found

    def child_procedures(self, project: EngineProject, r: dict) -> Path:
        project.world.git(project.root, "worktree", "add", "-q", "-b", "side",
                          str(project.tmp / "side"))
        c = {"id": "c", "stage": "setup", "kind": "call", "procedure": "kid", "holds": "live",
             "on": {"done": "done", "needs-owner": "needs-owner"}}
        steps = [step("p", "standin-side", "r"), r, step("g", "standin-gate", "done")]
        return project.procedures(
            [c], stops={"needs-owner": {"need": "owner-decision", "reenter": "c"}},
            children={"kid": {"steps": steps, "inputs": ["issue"], "stops": {
                "needs-owner": {"need": "owner-decision", "reenter": "p"}}}})

    def delivered_twice(self, project: EngineProject, procedures: Path, between=None):
        first = project.deliver(procedures)
        self.assertEqual(first.returncode, 3, first.stdout + first.stderr)
        if between:
            between()
        second = project.deliver(procedures)
        self.assertEqual(second.returncode, 3, second.stdout + second.stderr)
        self.assertEqual(json.loads(second.stdout)["run"], json.loads(first.stdout)["run"])
        runs = project.runs()[0].parent
        root = runs / json.loads(first.stdout)["run"]
        kids = [e["child"] for e in project.events(root) if e["event"] == "call"]
        return root, [runs / kid for kid in kids]

    def stored(self, project: EngineProject, run: Path, step_id: str) -> list[dict]:
        return [e for e in project.events(run) if e["event"] == "result_stored"
                and e["step"] == step_id]

    def test_a_checkout_step_at_an_unchanged_head_reuses_the_result_an_earlier_child_run_stored(self):
        project = EngineProject(self)
        procedures = self.child_procedures(project, self.checkout_step("r", "count-b", "g"))
        _, kids = self.delivered_twice(project, procedures)
        self.assertEqual(len(kids), 2)
        self.assertEqual(project.calls("b"), 1)
        (first,), (second,) = (self.stored(project, kid, "r") for kid in kids)
        self.assertNotIn("reused_from", first)
        self.assertEqual(second["reused_from"], {"run": kids[0].name, "step": "r", "visit": 1})
        for member in ("reuse_key", "head", "repository"):
            self.assertEqual(second[member], first[member], member)
        self.assertEqual((kids[1] / second["result"]).read_bytes(),
                         (kids[0] / first["result"]).read_bytes())
        self.assertEqual([e for e in project.events(kids[1])
                          if e["event"] == "process_started" and e["step"] == "r"], [])

    def test_a_moved_merge_base_runs_the_checkout_step_again_at_the_same_head(self):
        for moved in (False, True):
            with self.subTest(moved=moved):
                project = EngineProject(self)
                side = project.tmp / "side"
                r = self.checkout_step("r", "count-b", "g")
                r.update({"in": ["p.path", "p.branch"], "base": "p.branch"})
                project.world.git(project.root, "worktree", "add", "-q", "-b", "side", str(side))
                c = {"id": "c", "stage": "setup", "kind": "call", "procedure": "kid", "holds": "live",
                     "on": {"done": "done", "needs-owner": "needs-owner"}}
                steps = [step("p", "standin-based", "r"), r, step("g", "standin-gate", "done")]
                procedures = project.procedures(
                    [c], stops={"needs-owner": {"need": "owner-decision", "reenter": "c"}},
                    children={"kid": {"steps": steps, "inputs": ["issue"], "stops": {
                        "needs-owner": {"need": "owner-decision", "reenter": "p"}}}})
                project.world.git(side, "commit", "--quiet", "--allow-empty", "-m", "side")
                _, kids = self.delivered_twice(project, procedures, lambda: moved and project.world.git(
                    project.root, "update-ref", "refs/remotes/origin/main", head_of(project, side)))
                self.assertEqual(project.calls("b"), 2 if moved else 1)
                (first,), (second,) = (self.stored(project, kid, "r") for kid in kids)
                self.assertEqual(second["head"], first["head"])
                self.assertEqual("reused_from" in second, not moved)
                self.assertEqual(second["base"] != first["base"], moved)

    def test_a_moved_head_runs_the_checkout_step_again(self):
        project = EngineProject(self)
        procedures = self.child_procedures(project, self.checkout_step("r", "count-b", "g"))
        _, kids = self.delivered_twice(project, procedures, lambda: project.world.git(
            project.tmp / "side", "commit", "--quiet", "--allow-empty", "-m", "moved"))
        self.assertEqual(project.calls("b"), 2)
        (first,), (second,) = (self.stored(project, kid, "r") for kid in kids)
        self.assertNotIn("reused_from", second)
        self.assertNotEqual(second["head"], first["head"])

    def test_a_second_step_with_the_same_command_arguments_and_head_reuses_the_first(self):
        project = EngineProject(self)
        project.world.git(project.root, "worktree", "add", "-q", "-b", "side",
                          str(project.tmp / "side"))
        procedures = project.procedures([
            step("p", "standin-side", "r1"), self.checkout_step("r1", "count-b", "r2"),
            self.checkout_step("r2", "count-b", "g"), step("g", "standin-gate", "done")])
        first = project.deliver(procedures)
        self.assertEqual(first.returncode, 3, first.stdout + first.stderr)
        run = project.runs()[0]
        self.assertEqual(project.calls("b"), 1)
        (second,) = self.stored(project, run, "r2")
        self.assertEqual(second["reused_from"], {"run": run.name, "step": "r1", "visit": 1})

    def test_a_result_that_did_not_end_ok_is_not_reused(self):
        project = EngineProject(self)
        procedures = self.child_procedures(
            project, self.checkout_step("r", "standin-stamp-fail", "g"))
        self.delivered_twice(project, procedures)
        self.assertEqual(len(project.stamps.read_text().splitlines()), 2)

    def test_a_step_without_a_checkout_is_never_reused(self):
        project = EngineProject(self)
        procedures = self.child_procedures(
            project, self.checkout_step("r", "count-b", "g", repository=False))
        root, kids = self.delivered_twice(project, procedures)
        self.assertEqual(project.calls("b"), 2)
        self.assertEqual([e for run in (root, *kids) for e in project.events(run)
                          if "reuse_key" in e], [])


class HeldReuseTest(unittest.TestCase):
    """The lookup, in process: `engine_heads.settle` over a ledger built by hand."""

    KEY = '["count-b",null,[["p.path","/side"]]]'

    def world(self, tmp: str):
        checkout = never_rise_world.repo(tmp)
        never_rise_world.write(checkout, "a.txt", "a")
        never_rise_world.commit_all(checkout)
        head = never_rise_world.git(checkout, "rev-parse", "HEAD").strip()
        root = new_run(tmp, token="aaaa")
        store(root, step="r", visit=1, head=head, repository=str(checkout), outcome="ok",
              reuse_key=self.KEY)
        return root, checkout, head

    def test_a_head_that_moves_during_the_lookup_is_not_reused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, checkout, head = self.world(tmp)
            with mock.patch.object(engine_heads, "read_head", side_effect=[head, "b" * 40]):
                self.assertEqual(engine_heads.settle(root, self.KEY, str(checkout)),
                                 Settled(engine_heads.Mark(head, None), None, True))
            with mock.patch.object(engine_heads, "read_head", side_effect=[head, head]):
                settled = engine_heads.settle(root, self.KEY, str(checkout))
            self.assertEqual(settled.hit[:3], (root.name, "r", 1))
            self.assertFalse(settled.moved)

    def test_each_base_ref_of_one_checkout_is_read_on_its_own(self):
        with tempfile.TemporaryDirectory() as tmp:
            checkout = never_rise_world.repo(tmp)
            never_rise_world.write(checkout, "a.txt", "a")
            never_rise_world.commit_all(checkout)
            c0 = never_rise_world.git(checkout, "rev-parse", "HEAD").strip()
            never_rise_world.write(checkout, "b.txt", "b")
            never_rise_world.commit_all(checkout)
            c1 = never_rise_world.git(checkout, "rev-parse", "HEAD").strip()
            for ref in ("refs/remotes/origin/main", "refs/remotes/origin/other"):
                never_rise_world.git(checkout, "update-ref", ref, c0)
            never_rise_world.git(checkout, "update-ref", "refs/remotes/origin/main", c1)
            ledger = [{"event": "result_stored", "repository": str(checkout),
                       "base": {"ref": ref, "sha": c0}}
                      for ref in ("refs/remotes/origin/main", "refs/remotes/origin/other")]
            self.assertEqual(engine_heads.checkout_bases(ledger),
                             {(str(checkout), "refs/remotes/origin/main"): c1,
                              (str(checkout), "refs/remotes/origin/other"): c0})

    def test_an_unreadable_run_in_the_delivery_is_a_miss(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, checkout, head = self.world(tmp)
            child = new_run(tmp, token="bbbb")
            (child / "events.jsonl").write_text("not json\n")
            engine_ledger.append_event(root, {**EXAMPLES["call"], "visit": 1,
                                              "child": child.name})
            settled = engine_heads.settle(root, self.KEY, str(checkout))
            self.assertIsNone(settled.hit)
            self.assertFalse(settled.moved)
