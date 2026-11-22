"""Contract tests for group and call steps in `engine deliver` (#1517).

A group runs its members beside each other; a call runs a child procedure as runs of their
own, one per item of its `each` list. Commands are the stand-ins of
tests/fixtures/engine-deliver/standin.py in a hermetic project; the engine runs as a child
process from source, or in process where a test needs to watch or fault a child's walk.
"""

from __future__ import annotations

import json
import os
import threading
import unittest
from pathlib import Path
from unittest import mock

from agent_tools.delivery import engine_ledger, engine_shell
from tests.test_engine_deliver import EngineProject, step
from tests.test_engine_session import DRAFT_REPLY, RESULT_NORMAL, copy_roles, install_stub

TIER = "integration"

REAL_WALK = engine_shell._walk


def GROUP(b_command: str) -> list[dict]:
    return [
        {"id": "checks", "stage": "final review", "kind": "group",
         "members": [{"step": "a", "pass": ["ok"]}, {"step": "b", "pass": ["ok"]}],
         "on": {"pass": "done", "blocked": "needs-owner"}},
        {"id": "a", "stage": "final review", "kind": "command", "command": "standin-stamp",
         "in": ["run.issue"]},
        {"id": "b", "stage": "final review", "kind": "command", "command": b_command,
         "in": ["run.issue"]},
    ]


def GROUP_LOOP() -> list[dict]:
    steps = GROUP("standin-stamp-fail")
    steps[0].update({"max_visits": 2,
                     "on": {"pass": "done", "blocked": "checks", "exhausted": "needs-owner"}})
    steps[1]["max_visits"] = 2
    steps[2]["max_visits"] = 2
    return steps


def child(steps: list[dict], inputs=("issue", "item")) -> dict:
    return {"steps": steps, "inputs": list(inputs),
            "stops": {"child-stop": {"need": "retry", "reenter": steps[0]["id"]}}}


def FAN(items_command: str, parallel: int) -> list[dict]:
    return [
        {"id": "list", "stage": "setup", "kind": "command", "command": items_command,
         "on": {"ok": "fan", "failed": "needs-owner"}},
        {"id": "fan", "stage": "landing", "kind": "call", "procedure": "fan-child",
         "in": ["list.argv"], "each": "list.argv", "parallel": parallel,
         "on": {"done": "done", "child-stop": "needs-owner"}},
    ]


def fan_children(work: str = "standin-stamp") -> dict[str, dict]:
    return {"fan-child": child([
        {"id": "work", "stage": "building", "kind": "command", "command": work,
         "in": ["run.item"], "on": {"ok": "judge", "failed": "child-stop"}},
        {"id": "judge", "stage": "building", "kind": "decide", "grader": "toy-tally",
         "in": ["run.item"], "on": {"accept": "done", "revise": "child-stop"}}])}


class WalkSpy:
    """Wraps the real `_walk`: a root run passes through, a child run is observed."""

    def __init__(self, real, *, rendezvous: int = 0, before=None) -> None:
        self.real, self.rendezvous, self.before = real, rendezvous, before
        self.condition = threading.Condition()
        self.active = self.peak = self.arrivals = 0
        self.records: list[tuple[str, bool]] = []
        self.met: list[bool] = []

    def __call__(self, run_dir: Path, table) -> tuple[int, dict]:
        run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
        if "parent" not in run:
            return self.real(run_dir, table)
        parent = engine_ledger.replay(run_dir.parent / run["parent"] / "events.jsonl")
        seen = any(e["event"] == "call" and e["child"] == run_dir.name for e in parent)
        with self.condition:
            self.records.append((run_dir.name, seen))
            self.active += 1
            self.peak = max(self.peak, self.active)
            arrival = self.arrivals
            self.arrivals += 1
            self.condition.notify_all()
            if arrival < self.rendezvous:
                self.met.append(self.condition.wait_for(
                    lambda: self.active >= self.rendezvous, timeout=30))
        try:
            if self.before is not None:
                self.before(run["inputs"].get("item"))
            return self.real(run_dir, table)
        finally:
            with self.condition:
                self.active -= 1
                self.condition.notify_all()


def run_document(run: Path) -> dict:
    return json.loads((run / "run.json").read_text(encoding="utf-8"))


def roots(project: EngineProject) -> list[Path]:
    return [run for run in project.runs() if "parent" not in run_document(run)]


def children_of(project: EngineProject) -> list[Path]:
    return [run for run in project.runs() if "parent" in run_document(run)]


def stamps(project: EngineProject) -> list[dict]:
    return [json.loads(line) for line in project.stamps.read_text(encoding="utf-8").splitlines()]


def result(run: Path, name: str) -> dict:
    return json.loads((run / "results" / name).read_text(encoding="utf-8"))


def graded(events: list[dict], name: str) -> list[dict]:
    return [e for e in events if e["event"] == "outcome_graded" and e["step"] == name]


class GroupTest(unittest.TestCase):
    def test_a_group_of_two_members_passes_and_both_ran_at_the_same_moment(self):
        project = EngineProject(self)
        procedures = project.procedures(GROUP("standin-stamp"))
        done = project.deliver(procedures, issue=1517)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(json.loads(done.stdout)["end"], "done")
        runs = project.runs()
        self.assertEqual(len(runs), 1)
        records = stamps(project)
        self.assertEqual(len(records), 2)
        self.assertLess(max(r["start"] for r in records), min(r["end"] for r in records))
        self.assertTrue((runs[0] / "results/a.1.json").is_file())
        self.assertTrue((runs[0] / "results/b.1.json").is_file())
        self.assertFalse((runs[0] / "results/checks.1.json").exists())
        events = project.events(runs[0])
        self.assertEqual((events[0]["event"], events[0]["step"], events[0]["visit"]),
                         ("step_entered", "checks", 1))
        index = {}
        for position, event in enumerate(events):
            if event["event"] == "outcome_graded":
                index[event["step"]] = position
            if event["event"] == "transition_taken":
                self.assertNotIn(event["step"], ("a", "b"))
                if event["step"] == "checks":
                    index["transition"] = position
                    self.assertEqual(event["to"], "done")
        self.assertEqual(graded(events, "checks")[0]["outcome"], "pass")
        self.assertEqual(graded(events, "checks")[0]["visit"], 1)
        self.assertGreater(index["checks"], max(index["a"], index["b"]))
        self.assertGreater(index["transition"], index["checks"])

    def test_a_member_outside_its_pass_set_blocks_the_group(self):
        project = EngineProject(self)
        done = project.deliver(project.procedures(GROUP("standin-stamp-fail")), issue=1517)
        self.assertEqual(done.returncode, 3, done.stdout + done.stderr)
        self.assertEqual(json.loads(done.stdout)["end"], "needs-owner")
        events = project.events(project.runs()[0])
        self.assertEqual([e["outcome"] for e in graded(events, "checks")], ["blocked"])
        records = stamps(project)
        self.assertEqual(len(records), 2)
        self.assertLess(max(r["start"] for r in records), min(r["end"] for r in records))

    def test_a_group_blocked_on_two_visits_records_each_grade_once(self):
        project = EngineProject(self)
        done = project.deliver(project.procedures(GROUP_LOOP()), issue=1517)
        self.assertEqual(done.returncode, 3, done.stdout + done.stderr)
        self.assertEqual(json.loads(done.stdout)["end"], "needs-owner")
        events = project.events(project.runs()[0])
        self.assertEqual([(e["visit"], e["outcome"]) for e in graded(events, "checks")],
                         [(1, "blocked"), (2, "blocked")])
        self.assertEqual([(e["visit"], e["outcome"], e["to"]) for e in events
                          if e["event"] == "transition_taken" and e["step"] == "checks"],
                         [(1, "blocked", "checks"), (2, "blocked", "checks")])
        self.assertFalse([e for e in events
                          if e.get("step") == "checks" and e.get("outcome") == "exhausted"])
        self.assertEqual(len(stamps(project)), 4)

    def test_a_group_of_decide_members_records_its_grade(self):
        project = EngineProject(self)
        procedures = project.procedures([
            {"id": "checks", "stage": "final review", "kind": "group",
             "members": [{"step": "j", "pass": ["accept"]}],
             "on": {"pass": "done", "blocked": "needs-owner"}},
            {"id": "j", "stage": "final review", "kind": "decide", "grader": "toy-tally",
             "in": ["run.issue"]}])
        done = project.deliver(procedures, issue=1517)
        self.assertEqual(done.returncode, 3, done.stdout + done.stderr)
        self.assertEqual(json.loads(done.stdout)["end"], "needs-owner")
        events = project.events(project.runs()[0])
        grades = graded(events, "checks")
        self.assertEqual([(e["visit"], e["outcome"]) for e in grades], [(1, "blocked")])
        transitions = [e for e in events
                       if e["event"] == "transition_taken" and e["step"] == "checks"]
        self.assertEqual([e["to"] for e in transitions], ["needs-owner"])
        stop = next(i for i, e in enumerate(events) if e["event"] == "stop_reached")
        self.assertLess(events.index(grades[0]), stop)
        self.assertLess(events.index(transitions[0]), stop)

    def test_a_group_whose_declared_input_has_no_value_starts_no_member(self):
        project = EngineProject(self)
        steps = [
            {"id": "prepare", "stage": "setup", "kind": "command", "command": "standin-json",
             "in": ["run.issue"], "on": {"ok": "checks", "failed": "needs-owner"}},
            *GROUP("standin-stamp")]
        steps[1]["in"] = ["prepare.ticket"]
        done = project.deliver(project.procedures(steps), issue=1517)
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertEqual(done.stdout, "")
        self.assertFalse(project.stamps.exists())
        events = project.events(project.runs()[0])
        self.assertFalse([e for e in events if e.get("step") in ("a", "b")])

    def test_a_completed_group_keeps_its_grade_when_its_successor_cannot_resolve_its_items(self):
        project = EngineProject(self)
        steps = GROUP("standin-stamp")
        steps[0]["on"] = {"pass": "fan", "blocked": "needs-owner"}
        steps[1]["command"] = "standin-items-object"
        steps.append({"id": "fan", "stage": "landing", "kind": "call", "procedure": "fan-child",
                      "in": ["a.argv"], "each": "a.argv",
                      "on": {"done": "done", "child-stop": "needs-owner"}})
        done = project.deliver(project.procedures(steps, children=fan_children()), issue=1517)
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertEqual(done.stdout, "")
        events = project.events(roots(project)[0])
        self.assertEqual([(e["visit"], e["outcome"]) for e in graded(events, "checks")],
                         [(1, "pass")])
        self.assertEqual([(e["outcome"], e["to"]) for e in events
                          if e["event"] == "transition_taken" and e["step"] == "checks"],
                         [("pass", "fan")])


class CallTest(unittest.TestCase):
    def deliver_in_process(self, project: EngineProject, steps: list[dict], spy: WalkSpy,
                           children: dict[str, dict] | None = None) -> tuple[int, dict]:
        procedures = project.procedures(steps, children=children)
        with project.inside(), mock.patch.object(engine_shell, "_walk", spy):
            return engine_shell.deliver(1517, procedures)

    def test_a_call_over_three_items_with_parallel_two_runs_three_child_runs_never_more_than_two_at_once(self):
        project = EngineProject(self)
        spy = WalkSpy(REAL_WALK, rendezvous=2)
        code, line = self.deliver_in_process(project, FAN("standin-items", 2), spy,
                                             fan_children())
        self.assertEqual((code, line["end"]), (0, "done"))
        self.assertEqual(len(project.runs()), 4)
        (root,) = roots(project)
        self.assertEqual(run_document(root)["procedure"], "deliver")
        kids = children_of(project)
        self.assertEqual(len(kids), 3)
        for kid in kids:
            document = run_document(kid)
            self.assertEqual(document["parent"], root.name)
            self.assertEqual(document["procedure"], "fan-child")
            self.assertEqual(document["inputs"], {"issue": 1517, "item": "approve"})
        self.assertEqual(spy.peak, 2)
        self.assertEqual(spy.met, [True, True])
        records = stamps(project)
        self.assertEqual(len(records), 3)
        self.assertTrue(all(r["argv"] == ["approve"] for r in records))
        events = project.events(root)
        calls = [e for e in events if e["event"] == "call"]
        self.assertEqual(len(calls), 3)
        for call in calls:
            self.assertEqual((call["step"], call["visit"], call["items"]), ("fan", 1, 3))
        self.assertEqual(sorted(c["index"] for c in calls), [0, 1, 2])
        self.assertEqual({c["child"] for c in calls}, {kid.name for kid in kids})
        self.assertEqual([e["outcome"] for e in graded(events, "fan")], ["done"])
        items = result(root, "fan.1.json")["items"]
        self.assertEqual(len(items), 3)
        for entry in items:
            self.assertEqual((entry["end"], entry["item"]), ("done", "approve"))
        for call in calls:
            self.assertEqual(items[call["index"]]["run"], call["child"])
        for kid in kids:
            self.assertEqual(project.events(kid)[-1]["event"], "run_done")

    def test_the_parent_records_each_call_event_before_its_child_walks(self):
        project = EngineProject(self)
        spy = WalkSpy(REAL_WALK)
        self.deliver_in_process(project, FAN("standin-items", 2), spy, fan_children())
        self.assertEqual(len(spy.records), 3)
        self.assertTrue(all(seen for _, seen in spy.records))

    def test_a_child_that_ends_in_a_stop_makes_that_stop_the_call_outcome(self):
        project = EngineProject(self)
        done = project.deliver(project.procedures(FAN("standin-items-mixed", 2),
                                                  children=fan_children()), issue=1517)
        self.assertEqual(done.returncode, 3, done.stdout + done.stderr)
        self.assertEqual(json.loads(done.stdout)["end"], "needs-owner")
        (root,) = roots(project)
        events = project.events(root)
        self.assertEqual([e["outcome"] for e in graded(events, "fan")], ["child-stop"])
        items = result(root, "fan.1.json")["items"]
        self.assertEqual([entry["end"] for entry in items], ["done", "child-stop", "done"])
        stopped = project.events(root.parent / items[1]["run"])[-1]
        self.assertEqual((stopped["event"], stopped["stop"]), ("stop_reached", "child-stop"))

    def test_a_call_without_each_runs_one_child(self):
        project = EngineProject(self)
        procedures = project.procedures(
            [{"id": "once", "stage": "landing", "kind": "call", "procedure": "solo",
              "on": {"done": "done", "child-stop": "needs-owner"}}],
            children={"solo": child([step("work", "standin-json", "done", failed="child-stop")],
                                    inputs=("issue",))})
        done = project.deliver(procedures, issue=1517)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(len(project.runs()), 2)
        (root,) = roots(project)
        (kid,) = children_of(project)
        calls = [e for e in project.events(root) if e["event"] == "call"]
        self.assertEqual([(c["index"], c["items"], c["child"]) for c in calls],
                         [(0, 1, kid.name)])
        self.assertEqual(result(root, "once.1.json"),
                         {"items": [{"end": "done", "item": None, "run": kid.name}]})
        self.assertEqual(run_document(kid)["inputs"], {"issue": 1517})

    def test_a_call_over_an_empty_list_runs_no_child_and_is_done(self):
        project = EngineProject(self)
        done = project.deliver(project.procedures(FAN("standin-json", 2),
                                                  children=fan_children()), issue=1517)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(len(project.runs()), 1)
        (root,) = roots(project)
        events = project.events(root)
        self.assertFalse([e for e in events if e["event"] == "call"])
        self.assertEqual(result(root, "fan.1.json"), {"items": []})
        self.assertEqual([e["outcome"] for e in graded(events, "fan")], ["done"])

    def test_status_reports_the_root_run_not_a_child(self):
        project = EngineProject(self)
        done = project.deliver(project.procedures(FAN("standin-items", 2),
                                                  children=fan_children()), issue=1517)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        (root,) = roots(project)
        status = project.status(1517)
        self.assertEqual(status.returncode, 0, status.stdout + status.stderr)
        state = json.loads(status.stdout)
        self.assertEqual(state["run"], root.name)
        self.assertIs(state["done"], True)

    def test_a_faulting_child_starts_no_further_child_and_faults_the_parent(self):
        project = EngineProject(self)
        done = project.deliver(project.procedures(
            FAN("standin-items", 1), children=fan_children("standin-says-maybe")), issue=1517)
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertEqual(done.stdout, "")
        self.assertEqual(len(project.runs()), 2)
        (root,) = roots(project)
        events = project.events(root)
        self.assertEqual(len([e for e in events if e["event"] == "call"]), 1)
        self.assertEqual(graded(events, "fan"), [])

    def test_a_fault_stops_admission_while_a_sibling_runs_on(self):
        project = EngineProject(self)
        fault_seen = threading.Event()
        waited: list[bool] = []
        real_fail = engine_shell._Admission.fail

        def fail(admission) -> None:
            real_fail(admission)
            fault_seen.set()

        def before(item) -> None:
            if item == "maybe":
                raise engine_shell.Fault("injected")
            if item == "hold":
                waited.append(fault_seen.wait(30))

        spy = WalkSpy(REAL_WALK, before=before)
        procedures = project.procedures(FAN("standin-items-hold", 2), children=fan_children())
        with project.inside(), mock.patch.object(engine_shell, "_walk", spy), \
                mock.patch.object(engine_shell._Admission, "fail", fail):
            with self.assertRaises(engine_shell.Fault):
                engine_shell.deliver(1517, procedures)
        self.assertEqual(waited, [True])
        kids = children_of(project)
        self.assertEqual(sorted(run_document(kid)["inputs"]["item"] for kid in kids),
                         ["hold", "maybe"])
        self.assertEqual(len(project.runs()), 3)
        (root,) = roots(project)
        events = project.events(root)
        calls = [e for e in events if e["event"] == "call"]
        self.assertEqual(sorted(c["index"] for c in calls), [0, 1])
        held = next(kid for kid in kids if run_document(kid)["inputs"]["item"] == "hold")
        self.assertEqual(project.events(held)[-1]["event"], "stop_reached")
        self.assertEqual(graded(events, "fan"), [])
        with project.inside():
            for kid in kids:
                self.assertIsNone(engine_shell.lock_holder(kid))

    def test_a_child_whose_publication_faults_leaves_no_descriptor_open(self):
        project = EngineProject(self)
        real = engine_ledger.create_run

        def create(**kwargs):
            if kwargs.get("parent") is not None:
                inner = kwargs["before_publish"]

                def publish(staged: Path) -> None:
                    inner(staged)
                    raise OSError("injected")

                kwargs["before_publish"] = publish
            return real(**kwargs)

        procedures = project.procedures(FAN("standin-items", 1), children=fan_children())
        before = len(os.listdir("/dev/fd"))
        with project.inside(), mock.patch.object(engine_ledger, "create_run", create):
            with self.assertRaises(engine_shell.Fault):
                engine_shell.deliver(1517, procedures)
        self.assertEqual(len(os.listdir("/dev/fd")), before)
        self.assertEqual(project.runs(), roots(project))
        self.assertEqual(len(project.runs()), 1)
        self.assertFalse([e for e in project.events(project.runs()[0]) if e["event"] == "call"])

    def test_a_failed_call_event_leaves_no_child_the_parent_does_not_name(self):
        project = EngineProject(self)
        real = engine_ledger.append_event

        def append(run_dir, event):
            if event["event"] == "call" and event["index"] == 2:
                raise OSError("injected")
            return real(run_dir, event)

        procedures = project.procedures(FAN("standin-items", 2), children=fan_children())
        with project.inside(), mock.patch.object(engine_ledger, "append_event", append):
            with self.assertRaises(engine_shell.Fault):
                engine_shell.deliver(1517, procedures)
        (root,) = roots(project)
        named = {e["child"] for e in project.events(root) if e["event"] == "call"}
        self.assertEqual(len(named), 2)
        self.assertEqual({kid.name for kid in children_of(project)}, named)
        with project.inside():
            for kid in children_of(project):
                self.assertIsNone(engine_shell.lock_holder(kid))

    def test_a_worker_that_cannot_start_is_a_fault_after_the_started_worker_is_drained(self):
        project = EngineProject(self)
        walking = threading.Event()
        real_start = threading.Thread.start
        starts: list[str] = []

        def start(thread) -> None:
            if getattr(thread._target, "__qualname__", "").endswith("worker"):
                starts.append("worker")
                if len(starts) == 2:
                    walking.wait(30)
                    raise RuntimeError("can't start new thread")
            real_start(thread)

        spy = WalkSpy(REAL_WALK, before=lambda item: walking.set())
        procedures = project.procedures(FAN("standin-items", 2), children=fan_children())
        with project.inside(), mock.patch.object(engine_shell, "_walk", spy), \
                mock.patch.object(threading.Thread, "start", start):
            with self.assertRaises(engine_shell.Fault):
                engine_shell.deliver(1517, procedures)
        (kid,) = children_of(project)
        self.assertEqual(project.events(kid)[-1]["event"], "run_done")
        (root,) = roots(project)
        self.assertEqual(len([e for e in project.events(root) if e["event"] == "call"]), 1)
        with project.inside():
            self.assertIsNone(engine_shell.lock_holder(kid))

    def test_an_item_that_is_no_string_or_integer_faults_before_any_child(self):
        project = EngineProject(self)
        done = project.deliver(project.procedures(FAN("standin-items-object", 2),
                                                  children=fan_children()), issue=1517)
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertEqual(done.stdout, "")
        self.assertEqual(len(project.runs()), 1)
        events = project.events(project.runs()[0])
        self.assertFalse([e for e in events if e["event"] == "call"])
        self.assertFalse([e for e in events
                          if e["event"] == "step_entered" and e["step"] == "fan"])


class PassThroughTest(unittest.TestCase):
    def test_a_call_without_each_passes_the_parents_item_to_its_child(self):
        project = EngineProject(self)
        inner = {"id": "inner", "stage": "landing", "kind": "call", "procedure": "grand",
                 "on": {"done": "done", "child-stop": "child-stop"}}
        children = {"fan-child": child([inner]),
                    "grand": child([step("work", "standin-json", "done", failed="child-stop")])}
        done = project.deliver(project.procedures(FAN("standin-items", 1), children=children),
                               issue=1517)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        by_run = {run.name: run_document(run) for run in children_of(project)}
        grand = [doc for doc in by_run.values() if doc["procedure"] == "grand"]
        self.assertEqual([doc["inputs"]["item"] for doc in grand], ["approve"] * 3)


class ChildKeepAliveTest(unittest.TestCase):
    def test_a_child_renews_the_claim_before_each_of_its_mutating_steps(self):
        project = EngineProject(self)
        project.answer({"stdout": '{"verdict":"renewed"}', "exit": 0})
        steps = FAN("standin-items", 1)
        steps[1]["on"]["claim-lost"] = "needs-owner"
        work = {"id": "work", "stage": "building", "kind": "command", "command": "standin-stamp",
                "in": ["run.item"], "mutates": True, "on": {"ok": "done", "failed": "child-stop"}}
        document = child([work])
        document["stops"]["claim-lost"] = {"need": "retry", "reenter": "work"}
        done = project.deliver(
            project.procedures(steps, keep_alive={"command": "standin-keep-alive",
                                                  "in": ["run.issue"]},
                               children={"fan-child": document}), issue=1517)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(project.renewal_calls(), [{"argv": ["1517"]}] * 3)
        for kid in children_of(project):
            events = project.events(kid)
            self.assertEqual([e["event"] for e in events if e["event"] in
                              ("keep_alive_ran", "step_entered")],
                             ["keep_alive_ran", "step_entered"])


class PreflightTest(unittest.TestCase):
    def test_a_child_reached_by_many_call_paths_is_validated_once_per_supplied_input_set(self):
        project = EngineProject(self)
        levels = 20

        def calls(target: str, last: str) -> list[dict]:
            return [{"id": name, "stage": "landing", "kind": "call", "procedure": target,
                     "on": {"done": "done", "child-stop": other}}
                    for name, other in (("first", "second"), ("second", last))]

        steps = calls("level1", "needs-owner")
        children = {}
        for level in range(1, levels):
            target = f"level{level + 1}"
            body = (calls(target, "child-stop") if level < levels - 1 else
                    [step("work", "standin-json", "done", failed="child-stop")])
            children[f"level{level}"] = child(body, inputs=("issue",))
        procedures = project.procedures(steps, children=children)
        loads = []
        real = engine_shell._load

        def load(path):
            loads.append(path.name)
            self.assertLess(len(loads), 500, "the preflight reloads a child for every call path")
            return real(path)

        with project.inside(), mock.patch.object(engine_shell, "_load", load):
            engine_shell._validate(procedures, engine_shell._resolve()[1])
        self.assertLessEqual(len(loads), 2 * levels)


class RefusalTest(unittest.TestCase):
    def test_a_call_the_engine_cannot_run_is_refused(self):
        solo = child([step("work", "standin-json", "done", failed="child-stop")],
                     inputs=("issue",))
        call = {"id": "once", "stage": "landing", "kind": "call", "procedure": "solo",
                "on": {"done": "done", "child-stop": "needs-owner"}}

        def undeclared(project: EngineProject) -> Path:
            return project.procedures([call], children={"solo": child(
                [step("work", "standin-json", "done", failed="child-stop")],
                inputs=("issue", "repo"))})

        def itself(project: EngineProject) -> Path:
            return project.procedures([{
                "id": "loop", "stage": "landing", "kind": "call", "procedure": "deliver",
                "on": {"done": "done", "needs-owner": "needs-owner"}}])

        def member(project: EngineProject) -> Path:
            return project.procedures([
                {"id": "checks", "stage": "final review", "kind": "group",
                 "members": [{"step": "c", "pass": ["done"]}],
                 "on": {"pass": "done", "blocked": "needs-owner"}},
                {"id": "c", "stage": "final review", "kind": "call", "procedure": "solo"}],
                children={"solo": solo})

        def mutating(project: EngineProject) -> Path:
            return project.procedures([call], children={"solo": child([
                {"id": "j", "stage": "building", "kind": "decide", "grader": "toy-tally",
                 "in": ["run.issue"], "mutates": True,
                 "on": {"accept": "done", "revise": "child-stop"}}], inputs=("issue",))})

        def unread_role(project: EngineProject) -> Path:
            copy_roles(project, "implementer")
            directory = project.procedures([call], children={"solo": child([
                {"id": "look", "stage": "building", "kind": "agent", "role": "reviewer",
                 "prompt": "draft.md", "reply": "draft.reply.json", "outcome_from": "status",
                 "in": ["run.issue"], "on": {"drafted": "done", "stuck": "child-stop"}}],
                inputs=("issue",))})
            (directory / "draft.md").write_text("Draft issue {{run.issue}}.\n", encoding="utf-8")
            (directory / "draft.reply.json").write_text(json.dumps(DRAFT_REPLY), encoding="utf-8")
            return directory

        cases = {
            "a child input the parent does not supply": ("repo", undeclared),
            "a procedure that calls itself": ("calls", itself),
            "a call member of a group": ("group", member),
            "a mutating child step": ("mutates", mutating),
            "a child agent step whose role file does not read": ("role reviewer", unread_role),
        }
        for name, (word, build) in cases.items():
            with self.subTest(name):
                project = EngineProject(self)
                done = project.deliver(build(project), issue=1517)
                self.assertEqual(done.returncode, 2, done.stdout + done.stderr)
                self.assertEqual(done.stdout, "")
                self.assertEqual(len(done.stderr.splitlines()), 1, done.stderr)
                self.assertIn(word, done.stderr)
                self.assertEqual(project.runs(), [])


class ChildSessionTest(unittest.TestCase):
    def test_an_agent_step_of_each_child_run_runs_as_that_child_runs_session(self):
        project = EngineProject(self)
        project.env.pop("CLAUDE_ACCOUNT", None)
        copy_roles(project, "reviewer")
        log = install_stub(project, RESULT_NORMAL)
        directory = project.procedures(FAN("standin-items-mixed", 2), children={
            "fan-child": child([
                {"id": "look", "stage": "building", "kind": "agent", "role": "reviewer",
                 "prompt": "item.md", "reply": "draft.reply.json", "outcome_from": "status",
                 "in": ["run.item"], "on": {"drafted": "done", "stuck": "child-stop"}}])})
        (directory / "item.md").write_text("Review item {{run.item}}.\n", encoding="utf-8")
        (directory / "draft.reply.json").write_text(json.dumps(DRAFT_REPLY), encoding="utf-8")

        done = project.deliver(directory, issue=1517)

        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(json.loads(done.stdout)["end"], "done")
        kids = children_of(project)
        self.assertEqual(len(kids), 3)
        for kid in kids:
            events = engine_ledger.replay(kid / "events.jsonl")
            starts = [e for e in events if e["event"] == "session_starting"]
            self.assertEqual([(e["step"], e["visit"]) for e in starts], [("look", 1)])
            self.assertTrue((kid / "results" / "look.1.json").is_file())
            for name in ("look.1.system.md", "look.1.prompt.md", "look.1.json"):
                self.assertTrue((kid / "sessions" / name).is_file(), name)
        (root,) = roots(project)
        events = engine_ledger.replay(root / "events.jsonl")
        self.assertEqual([e for e in events if e["event"] == "session_starting"], [])
        self.assertFalse((root / "sessions").exists())
        lines = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(lines), 3)
        self.assertEqual(sorted(line["stdin"] for line in lines),
                         ["Review item approve.\n", "Review item approve.\n",
                          "Review item nope.\n"])
        self.assertTrue(all(line["announced"] for line in lines))
        self.assertEqual([e["outcome"] for e in graded(events, "fan")], ["done"])


if __name__ == "__main__":
    unittest.main()
