"""One project's records document, the file a project question session reads (#1271).

Run: just agent-workflow-tests
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from agent_tools.console import (
    deliveries, event_log, project_question, question_records, spend, sprints, transcript_digest, view)
from agent_tools.console.event_log import Event
from agent_tools.console.spend import Tokens
from agent_tools.console.transcript_digest import PhaseFigures, RunDigest

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

    def test_a_delivery_issue_keeps_the_raw_stage_the_sprints_part_keeps(self):
        rows = [seen(1, P, "s-1", "wf_a", [stage(12, "landing"), stage(13, "verifying"), stage(14, "building")])]
        issues = records(events=rows)["deliveries"][0]["issues"]
        self.assertEqual(issues, [{"issue": 12, "stage": "landing"}, {"issue": 13, "stage": "verifying"},
                                  {"issue": 14, "stage": "building"}])

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

    def test_a_pruned_predecessor_registry_still_keeps_its_activations_out(self):
        # Retention removed the predecessor's registered and unregistered rows but kept the newest
        # activation rows (EVENTS seq 4 to 7); only this project's later registration is retained.
        events = EVENTS + [
            Event(200, f"{DAY2}T12:00:00+00:00", "project.registered", P, {"root": P_ROOT}),
            activation(201, event_log.ACTIVATION_FINISHED,
                       {"root": P_ROOT, "commit": "e" * 40, "ok": True, "reason": None,
                        "next_step": None})]
        r = records(events=events)
        self.assertEqual([a["commit"] for a in r["activations"]], ["e" * 40])

    def test_an_unregistration_alone_names_its_root_and_ends_the_predecessors_ownership(self):
        # An older log kept the predecessor's unregistration (its payload names the root) but neither its
        # registration nor this project's own, so only the payload says whose activations these are.
        events = EVENTS + [
            Event(100, f"{DAY1}T12:00:00+00:00", event_log.PROJECT_UNREGISTERED, "owner/old",
                  {"root": P_ROOT}),
            activation(103, event_log.ACTIVATION_FINISHED,
                       {"root": P_ROOT, "commit": "e" * 40, "ok": True, "reason": None,
                        "next_step": None})]
        r = records(events=events)
        self.assertEqual([a["commit"] for a in r["activations"]], ["e" * 40])
        self.assertEqual([d["tokens"] for d in r["spend"]["days"]], [0, 60])

    def test_a_move_off_the_root_with_its_registration_pruned_still_keeps_the_predecessors_spend_out(self):
        # The old retention pruned the predecessor's registration at the root but kept its later one
        # under another root; that row names only the new root, so the successor's own retained
        # registration at the root is the cutoff.
        events = EVENTS + [
            Event(100, f"{DAY1}T10:00:00+00:00", "project.registered", "owner/old",
                  {"root": "/srv/elsewhere"}),
            Event(101, f"{DAY1}T12:00:00+00:00", "project.registered", P, {"root": P_ROOT})]
        r = records(events=events)
        self.assertEqual([d["tokens"] for d in r["spend"]["days"]], [0, 60])

    def test_a_predecessors_activation_stays_out_after_retention_removed_every_old_row(self):
        # The host's newest activation rows are kept whatever their age; the registrations that say
        # who owned the path when they were written must be kept with them, the new project's own
        # registration included, or the predecessor's failure reads as the new project's.
        old, day = "2026-08-01T00:00:00.000000+00:00", [""]
        with tempfile.TemporaryDirectory() as directory:
            log = event_log.EventLog(Path(directory) / "events.sqlite3", clock=lambda: day[0])
            self.addCleanup(log.close)
            day[0] = old
            log.append([("project.registered", "owner/old", {"root": P_ROOT}),
                        (event_log.ACTIVATION_STARTED, None,
                         {"root": P_ROOT, "commit": "c" * 40, "tree": "group:1"}),
                        (event_log.ACTIVATION_FINISHED, None,
                         {"root": P_ROOT, "commit": "c" * 40, "ok": False,
                          "reason": "it exited 1: error: build failed", "next_step": NEXT_STEP}),
                        (event_log.PROJECT_UNREGISTERED, "owner/old", {})])
            day[0] = "2026-08-02T00:00:00.000000+00:00"
            log.append([("project.registered", P, {"root": P_ROOT})])
            day[0] = "2026-11-17T00:00:00.000000+00:00"
            log.retain()
            retained = log.events()
        self.assertEqual([e.kind for e in retained if e.kind.startswith("activation")],
                         [event_log.ACTIVATION_STARTED, event_log.ACTIVATION_FINISHED])
        self.assertEqual(records(events=retained)["activations"], [])

    def test_the_projects_own_registrations_and_unrelated_ones_drop_nothing(self):
        def registry(seq, kind, project, payload):
            return Event(seq, f"{DAY2}T12:00:00+00:00", kind, project, payload)

        events = sorted([
            registry(0, "project.registered", P, {"root": P_ROOT}),
            registry(101, "project.registered", O, {"root": O_ROOT}),
            *EVENTS,
            registry(102, event_log.PROJECT_UNREGISTERED, P, {}),
            registry(103, "project.registered", P, {"root": P_ROOT}),
            registry(104, event_log.PROJECT_UNREGISTERED, O, {})], key=lambda event: event.seq)
        r = records(events=events)
        self.assertEqual([a["commit"] for a in r["activations"]], ["c" * 40])
        self.assertEqual([d["tokens"] for d in r["spend"]["days"]], [100, 60])
        self.assertEqual(r, records())

    def test_a_project_registered_after_another_keeps_its_own_spend_on_the_registration_day(self):
        # Nothing shows the earlier project ever held this root: no activation row of the root
        # precedes this project's registration, so the other project's registration under its own
        # root cuts nothing from this project's spend.
        events = [Event(-2, f"{DAY1}T09:00:00+00:00", "project.registered", O, {"root": O_ROOT}),
                  Event(-1, f"{DAY1}T10:00:00+00:00", "project.registered", P, {"root": P_ROOT}),
                  *EVENTS]
        r = records(events=events)
        self.assertEqual([d["tokens"] for d in r["spend"]["days"]], [100, 60])
        self.assertEqual([a["commit"] for a in r["activations"]], ["c" * 40])

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


    def assert_sections_read_alone(self, r, text, index):
        lines = text.split("\n")
        for name in sorted(index):
            with self.subTest(name):
                offset, limit = index[name]
                part = "\n".join(lines[offset - 1:offset - 1 + limit])
                head = ' "' + name + '": '
                self.assertTrue(part.startswith(head))
                self.assertEqual(json.loads(part.removeprefix(head).removesuffix(",")), r[name])

    def test_each_section_reads_alone_by_its_offset_and_limit(self):
        r = records()
        expected = set(r) - {"project_id", "written_at", "transcripts"}
        self.assertIsNone(r["transcripts"])
        text = question_records.encode(r)
        index = question_records.section_lines(text)
        self.assertEqual(
            expected, {"spend", "sprints", "deliveries", "activations", "held_checks"})
        self.assertEqual(set(index), expected)
        self.assert_sections_read_alone(r, text, index)
        self.assertLess(index["spend"][1], len(text.split("\n")))

    def test_a_line_separator_inside_a_reason_moves_no_sections_offset(self):
        events = list(EVENTS)
        events[4] = activation(
            5, event_log.ACTIVATION_FINISHED,
            {**EVENTS[4].payload, "reason": "exit 1 see log\u0085then end"})
        r = records(events=events)
        text = question_records.encode(r)
        lines = text.split("\n")
        index = question_records.section_lines(text)
        self.assertIn("\u0085", text)
        self.assertGreater(len(text.splitlines()), len(lines) - 1)
        self.assertIn("\u0085", r["activations"][0]["reason"])
        self.assert_sections_read_alone(r, text, index)
        self.assertEqual(
            json.loads("\n".join(lines[index["spend"][0] - 1:][:index["spend"][1]])
                       .removeprefix(' "spend": ').removesuffix(",")), r["spend"])

    def test_text_with_no_section_gives_no_offsets(self):
        self.assertEqual(question_records.section_lines('{\n "project_id": "owner/p01"\n}\n'), {})
        self.assertEqual(question_records.section_lines(""), {})
        self.assertEqual(question_records.section_lines("not json"), {})


def digest(issues, script, wall, phases, started="2026-11-17T08:00:00+00:00",
           ended="2026-11-17T09:00:00+00:00") -> RunDigest:
    return RunDigest(tuple(issues), script, started, ended, wall, {
        name: PhaseFigures(1, 2, 3, seconds, Tokens(input=tokens, dollars=tokens / 100))
        for name, (seconds, tokens) in phases.items()})


RUN_A = digest((7,), "deliver-standard", 900, {"implement": (600, 150), "plan": (120, 40)})
RUN_B = digest((7, 8), "deliver-batch", 400, {"plan": (300, 500)},
               "2026-11-17T10:00:00+00:00", "2026-11-17T11:00:00+00:00")


class TranscriptsPartTest(unittest.TestCase):
    def test_scripts_phases_and_issues_are_counted(self):
        part = records(transcripts=[RUN_A, RUN_B])["transcripts"]
        self.assertEqual(set(part), {"note", "first_at", "last_at", "runs", "agents", "scripts",
                                     "phases", "issues"})
        self.assertEqual(part["note"], question_records.TRANSCRIPTS_NOTE)
        self.assertEqual((part["first_at"], part["last_at"], part["runs"], part["agents"]),
                         ("2026-11-17T08:00:00+00:00", "2026-11-17T11:00:00+00:00", 2, 3))
        top = part["scripts"][0]
        self.assertEqual((top["script"], top["runs"], top["seconds"], top["tokens"]),
                         ("deliver-batch", 1, 400, 500))
        self.assertEqual([p["phase"] for p in part["phases"]], ["implement", "plan"])
        self.assertEqual([p["seconds"] for p in part["phases"]], [600, 420])
        self.assertEqual(part["issues"], [
            {"issue": 7, "runs": 1, "shared_runs": 1, "seconds": 900, "tokens": 190,
             "dollars": 1.9, "approximate": False,
             "phases": {"implement": {"seconds": 600, "tokens": 150, "dollars": 1.5,
                                      "approximate": False},
                        "plan": {"seconds": 120, "tokens": 40, "dollars": 0.4,
                                 "approximate": False}}},
            {"issue": 8, "runs": 0, "shared_runs": 1, "seconds": 0, "tokens": 0,
             "dollars": 0.0, "approximate": False, "phases": {}}])

    def test_an_issue_counts_only_runs_that_delivered_it_alone(self):
        issues = records(transcripts=[RUN_A, RUN_B])["transcripts"]["issues"]
        self.assertEqual(issues[0]["tokens"], 190)
        self.assertNotEqual(issues[0]["tokens"], 690)

    def test_without_transcripts_the_part_is_null(self):
        r = records()
        self.assertIsNone(r["transcripts"])
        self.assertEqual(set(r), {"project_id", "written_at", "transcripts", *question_records.SECTIONS})

    def test_the_transcripts_part_has_its_own_lines(self):
        r = records(transcripts=[RUN_A, RUN_B])
        text = question_records.encode(r)
        self.assertNotIn("transcripts", question_records.section_lines(text))
        index = question_records.section_lines(text, question_records.DEEP_SECTIONS)
        offset, limit = index["transcripts"]
        part = "\n".join(text.split("\n")[offset - 1:offset - 1 + limit])
        self.assertTrue(part.startswith(' "transcripts": '))
        self.assertEqual(json.loads(part.removeprefix(' "transcripts": ').removesuffix(",")),
                         r["transcripts"])
        self.assertEqual(set(index), {*question_records.SECTIONS, "transcripts"})

    def test_run_issues_are_the_projects_own_delivery_rows(self):
        rows = [seen(1, P, "s-1", "wf_a", [stage(7)]), seen(2, O, "s-0", "wf_a", [stage(9)])]
        self.assertEqual(question_records.run_issues(rows, P), {"wf_a": (7,)})

    def test_owner_since_is_the_day_after_the_predecessor_left(self):
        def registry(seq, kind, project, payload):
            return Event(seq, f"{DAY1}T12:00:00+00:00", kind, project, payload)

        for ending in (registry(101, event_log.PROJECT_UNREGISTERED, "owner/old", {}),
                       registry(101, "project.registered", "owner/old", {"root": "/srv/elsewhere"})):
            with self.subTest(ending=ending.kind):
                events = [registry(100, "project.registered", "owner/old", {"root": P_ROOT})
                          ] + EVENTS + [ending, Event(102, f"{DAY2}T12:00:00+00:00",
                                                     "project.registered", P, {"root": P_ROOT})]
                self.assertEqual(question_records.owner_since(
                    sorted(events, key=lambda e: e.seq), P, P_ROOT), DAY2)
        self.assertIsNone(question_records.owner_since(EVENTS, P, P_ROOT))

    def test_a_predecessors_work_after_it_left_and_before_the_project_registered_is_not_counted(self):
        def registry(seq, kind, project, payload, when):
            return Event(seq, f"{when}T12:00:00+00:00", kind, project, payload)

        friday = "2026-11-20"
        events = sorted(EVENTS + [
            registry(100, "project.registered", "owner/old", {"root": P_ROOT}, DAY1),
            registry(101, event_log.PROJECT_UNREGISTERED, "owner/old", {}, DAY1),
            registry(102, "project.registered", P, {"root": P_ROOT}, friday)], key=lambda e: e.seq)
        self.assertEqual(question_records.owner_since(events, P, P_ROOT), friday)
        r = records(events=events)
        self.assertEqual([d["tokens"] for d in r["spend"]["days"]], [0, 0])
        self.assertEqual(r["spend"]["runs"], [])

    def test_a_token_shaped_run_name_reaches_neither_reader_nor_the_records(self):
        token = "ghp_" + "A1b2" * 9
        run = f"wf_{token}"
        directory = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(directory, ignore_errors=True))
        tree = Path(os.path.realpath(directory)) / "projects"
        run_dir = tree / "-srv-p01" / "sid-1" / "subagents" / "workflows" / run
        run_dir.mkdir(parents=True)
        (run_dir / "journal.jsonl").write_text(json.dumps(
            {"type": "started", "agentId": "a1", "label": "impl", "phase": "Tasks"}) + "\n")
        line = {"type": "assistant", "sessionId": "sid-1", "timestamp": "2026-11-17T08:00:00Z",
                "cwd": P_ROOT,
                "message": {"id": "m1", "model": "claude-sonnet-4-6", "usage": {"input_tokens": 3},
                            "content": []}}
        (run_dir / "agent-a1.jsonl").write_text(json.dumps(line) + "\n")
        reader = spend.SpendReader(repo_of=lambda cwd: P_ROOT)
        reader.read([tree], "2026-11-01")
        view_of = spend.spend_view(reader.snapshot(), today="2026-11-17", project_of={P_ROOT: P}.get,
                                   profiles={})
        runs = transcript_digest.project_runs(
            [tree], P, {P_ROOT: P}.get, "2026-11-01", {run: [7]}, repo_of=lambda cwd: P_ROOT)
        self.assertEqual(len(runs), 1)
        r = records(spend=view_of, transcripts=runs)
        self.assertEqual([x["run_id"] for x in r["spend"]["runs"]], [question_records.RUN_WITHHELD])
        self.assertEqual(r["spend"]["runs"][0]["tokens"], 3)
        text = question_records.encode(r)
        self.assertNotIn(token, text)
        self.assertFalse(project_question.credential_shaped(text))

    def test_a_token_in_a_transcript_never_reaches_the_records(self):
        token = "ghp_" + "A1b2" * 9
        run = f"wf_{token}"
        directory = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(directory, ignore_errors=True))
        tree = Path(os.path.realpath(directory)) / "projects"
        run_dir = tree / "-srv-p01" / f"sid-{token}" / "subagents" / "workflows" / run
        run_dir.mkdir(parents=True)
        (run_dir / "journal.jsonl").write_text(json.dumps(
            {"type": "started", "agentId": "a1", "label": f"impl-{token}", "phase": "Tasks"}) + "\n")
        line = {"type": "assistant", "sessionId": token, "timestamp": "2026-11-17T08:00:00Z",
                "cwd": f"{P_ROOT}/{token}",
                "message": {"id": "m1", "model": "claude-sonnet-4-6", "usage": {"input_tokens": 3},
                            "content": [{"type": "text", "text": token},
                                        {"type": "tool_use", "id": "t1", "name": "Read",
                                         "input": {"p": token}}]}}
        (run_dir / "agent-a1.jsonl").write_text(json.dumps(line) + "\n")
        runs = transcript_digest.project_runs(
            [tree], P, {P_ROOT: P}.get, "2026-11-01", {run: [7]}, repo_of=lambda cwd: P_ROOT)
        text = question_records.encode(records(transcripts=runs))
        self.assertNotIn(token, text)
        self.assertFalse(project_question.credential_shaped(text))
        part = json.loads(text)["transcripts"]
        self.assertEqual(part["runs"], 1)
        self.assertEqual(part["issues"][0]["issue"], 7)


if __name__ == "__main__":
    unittest.main()
