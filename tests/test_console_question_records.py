"""One project's records document, the file a project question session reads (#1271).

Run: just agent-workflow-tests
"""

from __future__ import annotations

import json
import unittest

from agent_tools.console import deliveries, event_log, question_records, sprints, view
from agent_tools.console.event_log import Event
from agent_tools.console.spend import Tokens

from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)

P, O = "owner/p01", "owner/p00"
P_ROOT, O_ROOT = "/srv/p01", "/srv/p00"
DAY1, DAY2 = "2026-11-16", "2026-11-17"
P_SPRINT, O_SPRINT = "1111111111111111", "0000000000000000"
MOVED_MS = 1_700_000_000_000
NEXT_STEP = "Its output is in /x.log; press Activate again once the cause is fixed."


def at(n: int) -> str:
    return f"2026-11-17T08:00:{n:02d}+00:00"


def seen(seq: int, project: str, session: str, run: str, issues: list[dict]) -> Event:
    payload = {"session_id": session, "run_id": run, "moved_ms": MOVED_MS, "issues": issues}
    return Event(seq, at(seq), deliveries.DELIVERY_SEEN, project, payload)


def stage(issue: int, name: str = "queued", task=None, tasks=None) -> dict:
    return {"issue": issue, "stage": name, "task": task, "tasks": tasks, "locking": False}


def activation(seq: int, kind: str, payload: dict) -> Event:
    return Event(seq, at(seq), kind, None, payload)


EVENTS = [
    seen(1, P, "s-1", "wf_a", [stage(7, "building", 2, 3)]),
    seen(2, P, "s-1", "wf_b", [stage(7), stage(8)]),
    seen(3, O, "s-0", "wf_a", [stage(9)]),
    activation(4, event_log.ACTIVATION_STARTED,
               {"root": P_ROOT, "commit": "c" * 40, "tree": "group:1"}),
    activation(5, event_log.ACTIVATION_FINISHED,
               {"root": P_ROOT, "commit": "c" * 40, "ok": False,
                "reason": "it exited 1: error: build failed", "next_step": NEXT_STEP}),
    activation(6, event_log.ACTIVATION_STARTED,
               {"root": O_ROOT, "commit": "d" * 40, "tree": "group:1"}),
    activation(7, event_log.ACTIVATION_FINISHED,
               {"root": O_ROOT, "commit": "d" * 40, "ok": True, "reason": None, "next_step": None}),
]


def day(name: str, project: dict, items: dict) -> dict:
    return {"day": name,
            "project": {p: t.wire() for p, t in project.items()},
            "project_items": {p: {kind: {item: {phase: t.wire() for phase, t in phases.items()}
                                         for item, phases in by_item.items()}
                                  for kind, by_item in kinds.items()}
                              for p, kinds in items.items()}}


SPEND = {"approximate": False, "days": [
    day(DAY1, {P: Tokens(input=100, dollars=1.0), O: Tokens(input=900, dollars=9.0)},
        {P: {"run": {"wf_a": {"implement": Tokens(input=60, dollars=0.6)}}},
         O: {"run": {"wf_a": {"plan": Tokens(input=900, dollars=9.0)}}}}),
    day(DAY2, {P: Tokens(input=50, output=10, dollars=0.5)},
        {P: {"run": {"wf_a": {"plan": Tokens(input=20, dollars=0.2)},
                     "wf_b": {"implement": Tokens(input=30, dollars=0.3)}},
             "sprint": {P_SPRINT: {"manager": Tokens(input=5, dollars=0.05)}}},
         O: {"sprint": {O_SPRINT: {"manager": Tokens(input=7)}}}}),
]}


def sprint(sid: str, project: str, seq: int, **fields) -> sprints.SprintState:
    return sprints.SprintState(sid, project, f"goal {sid}. More.", seq, at(seq), **fields)


def records(**over) -> dict:
    arguments = {
        "root": P_ROOT, "events": EVENTS, "spend": SPEND,
        "live_runs": frozenset({("s-1", "wf_b")}),
        "sprint_states": {P_SPRINT: sprint(P_SPRINT, P, 1), O_SPRINT: sprint(O_SPRINT, O, 2)},
        "inbox": {}, "written_at": at(30)}
    arguments.update(over)
    return question_records.project_records(P, **arguments)


def held(project: str, key: str, issue: int, reason: str, **item) -> tuple:
    document = {"key": key, "issue": issue, "reason": reason, "kind": "owner-check",
                "question": f"q {key}", "detail": f"d {key}", **item}
    return (project, key), view.InboxRecord(document, at(20), at(21))


class ProjectRecordsTest(unittest.TestCase):
    def test_spend_by_day_run_issue_phase_and_sprint_is_this_projects_only(self):
        r = records()
        self.assertEqual([d["day"] for d in r["spend"]["days"]], [DAY1, DAY2])
        self.assertEqual(r["spend"]["days"][1]["tokens"], 60)
        self.assertEqual([x["run_id"] for x in r["spend"]["runs"]], ["wf_a", "wf_b"])
        run_a, run_b = r["spend"]["runs"]
        self.assertEqual(run_a["tokens"], 80)
        self.assertNotEqual(run_a["tokens"], 980)
        self.assertEqual(
            {phase: f["tokens"] for phase, f in run_a["phases"].items()},
            {"implement": 60, "plan": 20})
        self.assertEqual(set(run_a["days"]), {DAY1, DAY2})
        self.assertEqual(run_a["issues"], [7])
        self.assertEqual(run_b["issues"], [7, 8])
        self.assertEqual([s["sprint_id"] for s in r["spend"]["sprints"]], [P_SPRINT])
        self.assertEqual((r["spend"]["first_day"], r["spend"]["last_day"]), (DAY1, DAY2))
        text = question_records.encode(r)
        for foreign in (O_SPRINT, O, O_ROOT, "d" * 40, "s-0"):
            self.assertNotIn(foreign, text)
        self.assertEqual(r["spend"]["note"], question_records.SPEND_NOTE)

    def test_an_issues_total_counts_only_runs_that_named_it_alone(self):
        self.assertEqual(records()["spend"]["issues"], [
            {"issue": 7, "tokens": 80, "dollars": 0.8, "approximate": False,
             "runs": ["wf_a"], "shared_runs": ["wf_b"]},
            {"issue": 8, "tokens": 0, "dollars": 0.0, "approximate": False,
             "runs": [], "shared_runs": ["wf_b"]}])

    def test_a_run_is_live_only_when_the_service_says_its_session_is(self):
        r = records()
        self.assertEqual([(d["run_id"], d["live"]) for d in r["deliveries"]],
                         [("wf_b", True), ("wf_a", False)])
        self.assertEqual(r["deliveries"][1]["issues"],
                         [{"issue": 7, "stage": "building task 2 of 3"}])
        for entry in r["deliveries"]:
            self.assertEqual(set(entry), {"run_id", "session_id", "first_seen_at", "last_seen_at",
                                          "moved_at", "live", "issues"})
        self.assertEqual(r["deliveries"][1]["moved_at"], "2023-11-14T22:13:20+00:00")
        self.assertEqual(r["deliveries"][1]["first_seen_at"], at(1))
        self.assertEqual({d["live"] for d in records(live_runs=frozenset())["deliveries"]}, {False})

    def test_sprints_are_this_projects_newest_first_with_title_end_and_report(self):
        newer = "2222222222222222"
        report = sprints.Report(at(9), "on track", sprints.DONE, "m", "https://x/y",
                                ((7, "done"),), (), "ship it")
        states = {
            P_SPRINT: sprint(P_SPRINT, P, 1),
            newer: sprint(newer, P, 5, report=report),
            O_SPRINT: sprint(O_SPRINT, O, 3)}
        r = records(sprint_states=states)
        listed = r["sprints"]
        self.assertEqual([s["sprint_id"] for s in listed], [newer, P_SPRINT])
        self.assertEqual(listed[0]["title"], sprints.sprint_title(states[newer]))
        self.assertEqual(listed[0]["ended_at"], sprints.ended_at(states[newer]))
        self.assertEqual(listed[0]["report"]["issues"], [{"issue": 7, "status": "done"}])
        self.assertEqual(listed[0]["report"]["phase"], sprints.DONE)
        self.assertIsNone(listed[1]["report"])
        self.assertIsNone(listed[1]["closing"])

    def test_held_checks_are_verify_and_held_review_items_of_this_project_with_their_times(self):
        wait = {"since": at(1)}
        inbox = dict([
            held(P, "k-ask", 7, "verify-ask"),
            held(P, "k-wait", 8, "verify-wait", wait=wait),
            held(P, "k-review", 9, "held-review", answered=True),
            held(P, "k-decision", 10, "decision"),
            held(O, "k-other", 11, "verify-ask")])
        inbox[(P, "k-ask")] = view.InboxRecord(inbox[(P, "k-ask")].item,
                                               "2026-11-17T08:00:00+00:00", at(21))
        inbox[(P, "k-review")] = view.InboxRecord(inbox[(P, "k-review")].item, at(20), at(21),
                                                  "2026-11-17T09:30:00+00:00")
        checks = records(inbox=inbox)["held_checks"]
        self.assertEqual(sorted(h["issue"] for h in checks), [7, 8, 9])
        by_issue = {h["issue"]: h for h in checks}
        self.assertEqual(by_issue[7]["waiting_since"], "2026-11-17T08:00:00+00:00")
        self.assertIsNone(by_issue[7]["answered_at"])
        self.assertIs(by_issue[9]["answered"], True)
        self.assertEqual(by_issue[9]["answered_at"], "2026-11-17T09:30:00+00:00")
        self.assertEqual(by_issue[8]["wait"], wait)
        for entry in checks:
            self.assertEqual(set(entry), {"key", "issue", "reason", "kind", "question", "detail",
                                          "waiting_since", "answered", "answered_at", "wait"})

    def test_activations_are_this_roots_runs_with_how_each_ended(self):
        self.assertEqual(records()["activations"], [{
            "commit": "c" * 40, "state": "failed", "started_at": at(4), "finished_at": at(5),
            "reason": "it exited 1: error: build failed", "next_step": NEXT_STEP}])

    def test_a_path_registered_to_another_project_before_keeps_that_projects_records_out(self):
        old = "owner/old"

        def registry(seq, kind, project, payload, when):
            return Event(seq, f"{when}T12:00:00+00:00", kind, project, payload)

        for ending in (
            registry(101, event_log.PROJECT_UNREGISTERED, old, {}, DAY1),
            registry(101, "project.registered", old, {"root": "/srv/elsewhere"}, DAY1),
        ):
            with self.subTest(ending=ending.kind):
                events = [registry(100, "project.registered", old, {"root": P_ROOT}, DAY1)] + EVENTS + [
                    ending, registry(102, "project.registered", P, {"root": P_ROOT}, DAY2),
                    activation(103, event_log.ACTIVATION_FINISHED,
                               {"root": P_ROOT, "commit": "e" * 40, "ok": True, "reason": None,
                                "next_step": None})]
                r = records(events=sorted(events, key=lambda event: event.seq))
                self.assertEqual([a["commit"] for a in r["activations"]], ["e" * 40])
                self.assertEqual([d["tokens"] for d in r["spend"]["days"]], [0, 60])
                self.assertEqual([(x["run_id"], x["tokens"]) for x in r["spend"]["runs"]],
                                 [("wf_b", 30), ("wf_a", 20)])
                self.assertEqual(
                    [x["sprint_id"] for x in r["spend"]["sprints"]], [P_SPRINT])

    def test_the_projects_own_registrations_and_unrelated_ones_drop_nothing(self):
        def registry(seq, kind, project, payload):
            return Event(seq, f"{DAY2}T12:00:00+00:00", kind, project, payload)

        events = sorted([
            registry(100, "project.registered", P, {"root": P_ROOT}),
            registry(101, "project.registered", O, {"root": O_ROOT}),
            *EVENTS,
            registry(102, event_log.PROJECT_UNREGISTERED, P, {}),
            registry(103, "project.registered", P, {"root": P_ROOT}),
            registry(104, event_log.PROJECT_UNREGISTERED, O, {})], key=lambda event: event.seq)
        r = records(events=events)
        self.assertEqual([a["commit"] for a in r["activations"]], ["c" * 40])
        self.assertEqual([d["tokens"] for d in r["spend"]["days"]], [100, 60])
        self.assertEqual(r, records())

    def test_no_spend_view_is_null_spend_and_the_rest_is_still_written(self):
        r = records(spend=None)
        self.assertIsNone(r["spend"])
        self.assertTrue(r["deliveries"])
        self.assertTrue(r["activations"])

    def test_encode_is_sorted_indented_json_that_ends_in_a_newline(self):
        r = records()
        text = question_records.encode(r)
        self.assertTrue(text.endswith("\n"))
        self.assertEqual(json.loads(text), r)
        self.assertIn('\n "project_id": "owner/p01"', text)


if __name__ == "__main__":
    unittest.main()
