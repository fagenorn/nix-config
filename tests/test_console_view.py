"""The console's view (#855): projection, registry diff, ordering and folding, encoding."""

import dataclasses
import itertools
import json
import re
import unittest
from datetime import datetime, timezone
from pathlib import Path

from unittest import mock

from agent_tools.claims import forge_markers as fm
from agent_tools.claims import forge_owner_action as foa
from agent_tools.console import digest
from agent_tools.console import contract_draft
from agent_tools.console import approve, folder_trust, inbox, register, release_card
from agent_tools.console import spend
from agent_tools.console import idle, view
from agent_tools.console.deliveries import (
    DELIVERY_GONE,
    DELIVERY_SEEN,
    DeliveryState,
    IssueStage,
    delivery_changes,
    delivery_states,
    seen_payload,
)
from agent_tools.console import event_log
from agent_tools.console.event_log import Event
from agent_tools.console.sessions import ENDED, SessionState
from agent_tools.console.capacity import EMPTY, CapacityState, capacity_view
from agent_tools.console.manager import session_name
from agent_tools.console.permission import AUTO, BYPASS, NOT_DECLARED, RULES_IN_PLACE, Permission
from agent_tools.console.movement import (
    LocalReading,
    ProjectMovement,
    PullMovement,
    PullRequest,
    SessionMovement,
    merged,
    pulls_from_answer,
)
from agent_tools.console import sessions as sessions_module
from agent_tools.console import sprints as sprints_module
from agent_tools.console.sprints import (
    APPROVED,
    CHANGES,
    MESSAGE_ANSWER,
    NONE,
    Brief,
    Closing,
    Manager,
    Message,
    Notice,
    Observed,
    PendingStop,
    Question,
    QuestionLook,
    QuestionPicture,
    Report,
    SprintState,
    cut,
    first_line,
    sprint_states,
    sprint_title,
)
from .test_console_sprints import (
    PARTS as PARTS_ROW,
    REPORT as REPORT_ROW,
    approved as approved_row,
    at as at_row,
    ms as ms_row,
    reported as reported_row,
    seen as seen_row,
    sent as sent_row,
    stated as stated_row,
)
from agent_tools.console.view import (
    ADOPTING_SENTENCE,
    ALL_OUT_SENTENCE,
    ANSWER_SENTENCE,
    BRIEF_SENTENCE,
    CHOOSE_SENTENCE,
    INBOX_CHANGED,
    INBOX_GONE,
    INBOX_HEALTH,
    INBOX_SEEN,
    NEEDS_SENTENCE,
    QUESTION_SENTENCE,
    REGISTER_SENTENCE,
    REGISTER_STEP_SENTENCE,
    REGISTERED,
    STALE_HEADLINE,
    STALE_SENTENCE,
    UNREGISTERED,
    WAIT_TEXT,
    InboxRecord,
    ProjectState,
    ReadState,
    derive_view,
    encode_view,
    health_change,
    inbox_changes,
    inbox_records,
    project_for,
    project_states,
    read_states,
    registry_changes,
    sprint_ball,
)
from agent_tools.system import forge_api
from agent_tools.verification import verify_issues
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)
from .test_console_approve import step_payload
from .test_console_inbox import (
    PROJECT as WAIT_PROJECT, SLUG as WAIT_SLUG, MERGE as WAIT_MERGE, block_of, dated_comment, held_node as held_issue,
    hold_body, human, page as tracker_page, prompt_body, window_body)
from .test_console_register import plan_doc


def state(pid, seq, work=0):
    return ProjectState(pid, f"/srv/{pid}", seq, f"t{seq}", work)


def event(seq, kind, project, payload=None):
    return Event(seq, f"t{seq}", kind, project, payload or {})


def session(sid, state, repo="/srv/p00", seq=1, name=None):
    return SessionState(sid, repo, repo, state, name, seq, f"t{seq}", None)


def item(pid, key, answered=False, held=1):
    return {"key": key, "project_id": pid, "repo": f"owner/{pid}", "issue": 7,
            "comment_id": 11, "url": f"https://example.test/{key}",
            "reason": "question", "question": "Which one?", "questions": [],
            "items": [], "answered": answered, "held_work": held}


def ids(entries):
    return [entry["project_id"] for entry in entries]


ADOPTION_ITEM = {
    "type": "inbox_item", "reason": "adoption", "key": "adoption/sha256:" + "b" * 64,
    "project_id": "o/r", "name": "r", "headline": "The adoption of o/r is ready to merge",
    "url": "https://github.com/o/r/pull/7", "number": 7, "answered": False,
    "waiting_since": "2026-01-01T00:00:00Z"}


class FoldTableTest(unittest.TestCase):
    def test_quiet_projects_past_three_fold_into_one_group(self):
        table = [
            (2, ["project", "project"], ["p01", "p00"], None),
            (3, ["project"] * 3, ["p02", "p01", "p00"], None),
            (4, ["quiet_group"], None, (4, "4 quiet projects", "p03")),
            (5, ["quiet_group"], None, (5, "5 quiet projects", "p04")),
            (12, ["quiet_group"], None, (12, "12 quiet projects", "p11")),
        ]
        for n, types, project_ids, group in table:
            with self.subTest(projects=n):
                result = derive_view(state(f"p{i:02d}", i + 1) for i in range(n))
                self.assertEqual(result["project_count"], n)
                entries = result["entries"]
                self.assertEqual([e["type"] for e in entries], types)
                if group is None:
                    self.assertEqual(ids(entries), project_ids)
                else:
                    count, label, first = group
                    self.assertEqual(entries[0]["count"], count)
                    self.assertEqual(entries[0]["label"], label)
                    self.assertEqual(ids(entries[0]["projects"])[0], first)
                    self.assertEqual(len(entries[0]["projects"]), count)
        five = derive_view(state(f"p{i:02d}", i + 1) for i in range(5))
        self.assertEqual(ids(five["entries"][0]["projects"]),
                         ["p04", "p03", "p02", "p01", "p00"])

    def test_active_projects_come_first_by_recency(self):
        active = [state("a1", 5, 1), state("a2", 9, 2)]
        quiet = [state(f"q{i}", i) for i in range(1, 5)]
        folded = derive_view(quiet + active)["entries"]
        self.assertEqual([e["type"] for e in folded],
                         ["project", "project", "quiet_group"])
        self.assertEqual(ids(folded[:2]), ["a2", "a1"])
        self.assertEqual(folded[2]["count"], 4)
        shown = derive_view(quiet[:3] + active)["entries"]
        self.assertEqual(ids(shown), ["a2", "a1", "q3", "q2", "q1"])
        self.assertEqual([e["quiet"] for e in shown],
                         [False, False, True, True, True])
        self.assertEqual(shown[0]["open_work"], 2)

    def test_equal_recency_orders_by_project_id(self):
        entries = derive_view([state("b", 1), state("a", 1)])["entries"]
        self.assertEqual(ids(entries), ["a", "b"])


class StatementTest(unittest.TestCase):
    def test_the_statement_says_nothing_needs_you(self):
        table = [
            (0, "No project is registered yet."),
            (1, "1 registered project, and nothing is waiting on you."),
            (5, "5 registered projects, and nothing is waiting on you."),
        ]
        for n, sentence in table:
            with self.subTest(projects=n):
                result = derive_view(state(f"p{i}", i) for i in range(n))
                self.assertEqual(result["statement"], {
                    "inbox_items": 0,
                    "headline": "Nothing needs you",
                    "sentence": sentence,
                    "stale": False,
                })
                self.assertEqual(result["inbox"], {"open": [], "answered": []})
                if n == 0:
                    self.assertEqual(result["entries"], [])


class ProjectionTest(unittest.TestCase):
    EVENTS = [
        event(1, REGISTERED, "a", {"root": "/a1"}),
        event(2, REGISTERED, "b", {"root": "/b"}),
        event(3, REGISTERED, "a", {"root": "/a2"}),
        event(4, UNREGISTERED, "b"),
        event(5, "other", "a"),
        event(6, "other", "zzz"),
    ]

    def test_events_fold_into_project_states(self):
        self.assertEqual(project_states(self.EVENTS),
                         {"a": ProjectState("a", "/a2", 5, "t5", 0)})

    def test_folding_onto_states_equals_folding_everything(self):
        first = project_states(self.EVENTS[:3])
        before = dict(first)
        rest = project_states(self.EVENTS[3:], first)
        self.assertEqual(rest, project_states(self.EVENTS))
        self.assertEqual(first, before)


class RegistryChangesTest(unittest.TestCase):
    def test_differences_become_events(self):
        a, b, c = state("a", 1), state("b", 1), state("c", 1)
        table = [
            ({}, [{"project_id": "b", "root": "/b"},
                  {"project_id": "a", "root": "/a"}],
             [(REGISTERED, "a", {"root": "/a"}),
              (REGISTERED, "b", {"root": "/b"})]),
            ({"a": a, "b": b}, [{"project_id": "b", "root": "/srv/b"},
                                {"project_id": "a", "root": "/srv/a"}], []),
            ({"a": a}, [{"project_id": "a", "root": "/new"}],
             [(REGISTERED, "a", {"root": "/new"})]),
            ({"c": c, "a": a}, [{"project_id": "b", "root": "/b"}],
             [(REGISTERED, "b", {"root": "/b"}),
              (UNREGISTERED, "a", {"root": "/srv/a"}),
              (UNREGISTERED, "c", {"root": "/srv/c"})]),
        ]
        for states, entries, expected in table:
            with self.subTest(states=sorted(states), entries=entries):
                self.assertEqual(registry_changes(states, entries), expected)


class SessionViewTest(unittest.TestCase):
    NO_SESSION_STATEMENT = {
        "inbox_items": 0, "headline": "Nothing needs you",
        "sentence": "1 registered project, and nothing is waiting on you.",
        "stale": False}

    def test_a_projects_sessions_form_its_outside_sprints_line(self):
        sessions = [
            session("s1", "working", seq=2),
            session("s2", "waiting_answer", seq=3, name="n2"),
            session("s3", "waiting_permission", seq=4),
            session("s4", "idle", seq=5),
            session("s5", "limit", seq=6),
        ]
        line = derive_view([state("p00", 1)], sessions=sessions)["entries"][0][
            "outside_sprints"]
        self.assertEqual(line, {
            "label": "Outside sprints",
            "working": 1,
            "waiting": 2,
            "summary": "1 working, 2 waiting, 1 stopped on a usage limit, 1 idle",
            "sessions": [
                {"session_id": "s2", "name": "n2", "state": "waiting_answer",
                 "state_text": "waiting for an answer",
                 "cwd": "/srv/p00", "deliveries": []},
                {"session_id": "s3", "name": "s3",
                 "state": "waiting_permission",
                 "state_text": "waiting for a permission",
                 "cwd": "/srv/p00", "deliveries": []},
                {"session_id": "s1", "name": "s1", "state": "working",
                 "state_text": "working", "cwd": "/srv/p00",
                 "deliveries": []},
                {"session_id": "s5", "name": "s5", "state": "limit",
                 "state_text": "stopped on a usage limit", "cwd": "/srv/p00",
                 "deliveries": []},
                {"session_id": "s4", "name": "s4", "state": "idle",
                 "state_text": "idle", "cwd": "/srv/p00",
                 "deliveries": []},
            ],
        })

    def test_a_session_name_is_its_first_eight_characters_without_one(self):
        line = derive_view([state("p00", 1)], sessions=[
            session("0123456789abcdef", "idle")])["entries"][0][
                "outside_sprints"]
        self.assertEqual(line["sessions"][0]["name"], "01234567")

    def test_sessions_of_one_state_order_by_newest_seq_then_id(self):
        sessions = [session("b", "idle", seq=3), session("a", "idle", seq=3),
                    session("c", "idle", seq=9)]
        line = derive_view([state("p00", 1)], sessions=sessions)["entries"][0][
            "outside_sprints"]
        self.assertEqual([s["session_id"] for s in line["sessions"]],
                         ["c", "a", "b"])

    def test_a_project_without_sessions_says_no_sessions(self):
        view = derive_view([state("p00", 1)])
        self.assertEqual(view["entries"][0]["outside_sprints"], {
            "label": "Outside sprints", "working": 0, "waiting": 0,
            "summary": "No sessions", "sessions": []})
        self.assertEqual(view["unmanaged"], [])

    def test_an_unregistered_repository_is_not_yet_managed_and_raises_nothing(self):
        s9 = session("s9", "waiting_answer", repo="/srv/elsewhere")
        view = derive_view([state("p00", 1)], sessions=[s9])
        self.assertEqual(view["unmanaged"], [{
            "type": "unmanaged", "root": "/srv/elsewhere", "name": "elsewhere",
            "label": "Not yet managed",
            "outside_sprints": {
                "label": "Outside sprints", "working": 0, "waiting": 1,
                "summary": "1 waiting",
                "sessions": [{
                    "session_id": "s9", "name": "s9",
                    "state": "waiting_answer",
                    "state_text": "waiting for an answer",
                    "cwd": "/srv/elsewhere", "deliveries": []}]}}])
        self.assertEqual(view["statement"], self.NO_SESSION_STATEMENT)
        self.assertEqual(view["project_count"], 1)
        self.assertEqual(view["entries"][0]["outside_sprints"]["sessions"], [])

    def test_an_unmanaged_repository_is_named_by_its_last_path_segment(self):
        sessions = [session("s1", "idle", repo="/srv/elsewhere"),
                    session("s2", "idle", repo="/")]
        unmanaged = derive_view([], sessions=sessions)["unmanaged"]
        self.assertEqual([(u["root"], u["name"]) for u in unmanaged],
                         [("/", "/"), ("/srv/elsewhere", "elsewhere")])
        self.assertEqual(view.repo_name("/srv/elsewhere/"), "elsewhere")

    def test_unmanaged_repositories_are_sorted_by_root(self):
        view = derive_view([], sessions=[session("s1", "idle", repo="/srv/b"),
                                session("s2", "idle", repo="/srv/a"),
                                session("s3", "idle", repo="/srv/b")])
        self.assertEqual([u["root"] for u in view["unmanaged"]],
                         ["/srv/a", "/srv/b"])
        self.assertEqual(view["unmanaged"][1]["outside_sprints"]["summary"],
                         "2 idle")

    def test_a_waiting_session_is_not_an_inbox_item(self):
        view = derive_view([state("p00", 1)],
                           sessions=[session("s1", "waiting_permission")])
        self.assertEqual(view["statement"], self.NO_SESSION_STATEMENT)

    def test_a_project_with_a_live_session_is_not_quiet(self):
        states = [state(f"p0{i}", i + 1) for i in range(5)]
        view = derive_view(states, sessions=[session("s1", "idle")])
        entries = view["entries"]
        self.assertEqual([e["type"] for e in entries],
                         ["project", "quiet_group"])
        self.assertEqual(entries[0]["project_id"], "p00")
        self.assertIs(entries[0]["quiet"], False)
        self.assertEqual(entries[1]["count"], 4)

    def test_an_empty_fleet_still_lists_unmanaged_sessions(self):
        view = derive_view([], sessions=[session("s1", "working", repo="/srv/x")])
        self.assertEqual(view["project_count"], 0)
        self.assertEqual(view["entries"], [])
        self.assertEqual(len(view["unmanaged"]), 1)
        self.assertEqual(view["statement"]["sentence"],
                         "No project is registered yet.")

    def test_project_for_matches_the_root_exactly(self):
        states = {"owner/a": ProjectState("owner/a", "/srv/a", 1, "t1"),
                  "owner/b": ProjectState("owner/b", "/srv/a", 2, "t2")}
        self.assertEqual(project_for("/srv/a", states), "owner/a")
        self.assertIsNone(project_for("/srv/a/sub", states))
        self.assertIsNone(project_for("/srv", states))

    def test_a_session_outside_any_repository_is_not_listed(self):
        s7 = SessionState("s7", None, "/home/u", "waiting_answer", None, 2,
                          "t2", None)
        view = derive_view([state("p00", 1)], sessions=[s7])
        self.assertEqual(view["unmanaged"], [])
        line = view["entries"][0]["outside_sprints"]
        self.assertEqual(line["sessions"], [])
        self.assertEqual(line["summary"], "No sessions")
        self.assertEqual(view["statement"], self.NO_SESSION_STATEMENT)

    def test_an_ended_session_is_not_listed(self):
        view = derive_view([state("p00", 1)], sessions=[session("s8", ENDED)])
        entry = view["entries"][0]
        self.assertEqual(entry["outside_sprints"]["summary"], "No sessions")
        self.assertIs(entry["quiet"], True)
        self.assertEqual(view["unmanaged"], [])


class DigestViewTest(unittest.TestCase):
    def test_the_view_carries_the_digest_it_is_given(self):
        given = {"since": None, "first_visit": True, "recent": [], "earlier": [], "omitted": 0}
        self.assertEqual(derive_view([], digest=given)["digest"], given)
        self.assertIsNone(derive_view([])["digest"])


class SpendViewWireTest(unittest.TestCase):
    def test_view_carries_thirty_daily_totals_by_each_dimension(self):
        today = "2026-11-16"
        snap = spend.Snapshot(
            {spend.Key(today, "s1", None, None, spend.SESSION):
                spend.priced("claude-sonnet-4-6", {"input_tokens": 1330})},
            {}, {}, {}, {"s1": "/srv/p00"})
        v = spend.spend_view(snap, today=today, project_of={"/srv/p00": "p00"}.get,
                             profiles={"s1": "p1"})
        shown = json.loads(view.encode_view(derive_view([state("p00", 1)], spend=v)))
        self.assertEqual(len(shown["spend"]["days"]), 30)
        for day in shown["spend"]["days"]:
            self.assertEqual(set(day), {"day", "total", "session", "project", "sprint", "run",
                                        "phase", "account", "aspect", "sprint_phase", "run_phase",
                                        "project_items"})
        self.assertEqual(shown["spend"]["days"][-1]["project"]["p00"]["input"], 1330)

    def test_view_without_spend_is_null(self):
        self.assertIsNone(derive_view([state("p00", 1)])["spend"])


def run(sid, run_id, moved_ms, *issues):
    return {(sid, run_id): DeliveryState(sid, run_id, moved_ms, tuple(issues))}


def seen(seq, sid, run_id, moved_ms, issues):
    return event(seq, DELIVERY_SEEN, None, {
        "session_id": sid, "run_id": run_id, "moved_ms": moved_ms, "issues": issues})


def gone(seq, sid, run_id):
    return event(seq, DELIVERY_GONE, None, {"session_id": sid, "run_id": run_id})


def issue_row(issue, stage, task=None, tasks=None):
    return {"issue": issue, "stage": stage, "task": task, "tasks": tasks}


def session_entries(view):
    lines = [entry["outside_sprints"] for entry in view["entries"]
             if entry["type"] == "project"]
    lines += [entry["outside_sprints"] for entry in view["unmanaged"]]
    return [s for line in lines for s in line["sessions"]]


class DeliveryViewTest(unittest.TestCase):
    def test_a_journal_unchanged_for_fifteen_minutes_reads_quiet_and_never_stalled(self):
        moved = 1_000_000_000_000
        table = [
            (-5_000, False, "moved just now"),
            (0, False, "moved just now"),
            (59_999, False, "moved just now"),
            (60_000, False, "moved 1 min ago"),
            (899_999, False, "moved 14 min ago"),
            (900_000, True, "quiet for 15 min"),
            (1_320_000, True, "quiet for 22 min"),
            (259_200_000, True, "quiet for 4320 min"),
        ]
        deliveries = run("s1", "wf_1", moved, IssueStage(858, "building", 2, 3))
        for elapsed, quiet, text in table:
            with self.subTest(elapsed=elapsed):
                view = derive_view([state("p00", 1)], sessions=[session("s1", "working")],
                                   deliveries=deliveries, now_ms=moved + elapsed)
                entry = session_entries(view)[0]["deliveries"][0]
                self.assertEqual((entry["quiet"], entry["moved_text"]), (quiet, text))
                self.assertNotIn(b"stalled", encode_view(view).lower())

    def test_a_sessions_runs_list_each_issues_stage(self):
        deliveries = {
            **run("s1", "wf_a", 1000, IssueStage(857, "plan review"),
                  IssueStage(856, "building", 3, 5)),
            **run("s1", "wf_b", 2000, IssueStage(860, "queued")),
            **run("s2", "wf_c", 1500, IssueStage(861, "done")),
        }
        sessions = [session("s1", "working"), session("s2", "idle", seq=2)]
        view = derive_view([state("p00", 1)], sessions=sessions,
                           deliveries=deliveries, now_ms=2000)
        by_id = {s["session_id"]: s for s in session_entries(view)}
        self.assertEqual(by_id["s1"]["deliveries"], [
            {"run_id": "wf_b", "quiet": False, "moved_text": "moved just now",
             "wait_text": None,
             "summary": "1 issue in delivery: 1 queued, moved just now",
             "moved_at": "1970-01-01T00:00:02+00:00",
             "journal_at": "1970-01-01T00:00:02+00:00",
             "reading_at": "1970-01-01T00:00:02+00:00",
             "issues": [{"issue": 860, "stage": "queued", "stage_text": "queued"}]},
            {"run_id": "wf_a", "quiet": False, "moved_text": "moved just now",
             "wait_text": None,
             "summary": "2 issues in delivery: 1 building, 1 plan review, moved just now",
             "moved_at": "1970-01-01T00:00:01+00:00",
             "journal_at": "1970-01-01T00:00:01+00:00",
             "reading_at": "1970-01-01T00:00:01+00:00",
             "issues": [
                 {"issue": 856, "stage": "building", "stage_text": "building task 3 of 5"},
                 {"issue": 857, "stage": "plan review", "stage_text": "plan review"}]},
        ])
        self.assertEqual([d["run_id"] for d in by_id["s2"]["deliveries"]], ["wf_c"])
        plain = derive_view([state("p00", 1)], sessions=sessions)
        self.assertEqual(view["entries"][0]["outside_sprints"]["summary"],
                         plain["entries"][0]["outside_sprints"]["summary"])

    def test_a_delivery_run_is_one_sentence_of_counts_by_stage(self):
        moved = 1_000_000_000_000
        table = [
            ((IssueStage(1, "landing"), IssueStage(2, "working"),
              IssueStage(3, "working"), IssueStage(4, "queued")), 16 * 60_000,
             "4 issues in delivery: 1 landing, 2 working, 1 queued, quiet for 16 min"),
            ((IssueStage(856, "building", 3, 5),), 0,
             "1 issue in delivery: 1 building, moved just now"),
            ((IssueStage(5, "planning"), IssueStage(6, "done"),
              IssueStage(7, "plan review")), 120_000,
             "3 issues in delivery: 1 done, 1 plan review, 1 planning, moved 2 min ago"),
            ((), 0, "No issue in delivery yet, moved just now"),
        ]
        for issues, elapsed, expected in table:
            with self.subTest(expected=expected):
                view = derive_view(
                    [state("p00", 1)], sessions=[session("s1", "working")],
                    deliveries=run("s1", "wf_1", moved, *issues),
                    now_ms=moved + elapsed)
                summary = session_entries(view)[0]["deliveries"][0]["summary"]
                self.assertEqual(summary, expected)
                self.assertNotIn("#", summary)

    def test_runs_of_an_ended_or_unlisted_session_are_not_shown(self):
        deliveries = {**run("s3", "wf_1", 1, IssueStage(1, "building")),
                      **run("ghost", "wf_2", 1, IssueStage(2, "building"))}
        view = derive_view([state("p00", 1)], sessions=[session("s3", ENDED)],
                           deliveries=deliveries, now_ms=1)
        self.assertEqual(session_entries(view), [])
        self.assertNotIn(b"wf_", encode_view(view))

    def test_delivery_events_fold_into_runs(self):
        first = [
            seen(1, "s1", "wf_1", 10, [issue_row(858, "planning")]),
            seen(2, "s1", "wf_1", 20, [issue_row(858, "building", 1, 3)]),
            seen(3, "s1", "wf_1", True, [issue_row(858, "planning")]),
        ]
        rest = [
            seen(4, "s1", "wf_1", 30, [issue_row("858", "planning")]),
            seen(5, "s1", "wf_1", 30, [issue_row(858, "stalled")]),
            gone(6, "s2", "wf_9"),
        ]
        expected = run("s1", "wf_1", 20, IssueStage(858, "building", 1, 3))
        folded = delivery_states(first + rest)
        self.assertEqual(folded, expected)
        self.assertEqual(delivery_states(rest, delivery_states(first)), folded)
        self.assertEqual(delivery_states([gone(7, "s1", "wf_1")], folded), {})

    def test_delivery_changes_append_only_differences(self):
        a = DeliveryState("s1", "wf_1", 10, (IssueStage(858, "building", 1, 3),))
        b = DeliveryState("s2", "wf_2", 10, ())
        states = {("s1", "wf_1"): a, ("s2", "wf_2"): b}
        owner = lambda sid: "owner/p00"
        self.assertEqual(delivery_changes(states, {("s1", "wf_1"): a}, {"s1"}, owner), [])
        moved = DeliveryState("s1", "wf_1", 11, a.issues)
        self.assertEqual(
            delivery_changes(states, {("s1", "wf_1"): moved}, {"s1"}, owner),
            [(DELIVERY_SEEN, "owner/p00", seen_payload(moved))])
        self.assertEqual(
            delivery_changes(states, {}, {"s1"}, owner),
            [(DELIVERY_GONE, "owner/p00", {"session_id": "s1", "run_id": "wf_1"})])
        self.assertEqual(
            delivery_changes(states, {}, {"s1", "s2"}, owner),
            [(DELIVERY_GONE, "owner/p00", {"session_id": "s1", "run_id": "wf_1"}),
             (DELIVERY_GONE, "owner/p00", {"session_id": "s2", "run_id": "wf_2"})])
        self.assertEqual(seen_payload(a), {
            "session_id": "s1", "run_id": "wf_1", "moved_ms": 10,
            "issues": [{"issue": 858, "stage": "building", "task": 1, "tasks": 3, "locking": False}]})

    def test_a_gone_run_leaves_the_session(self):
        folded = delivery_states([
            seen(1, "s1", "wf_1", 10, [issue_row(858, "building")]),
            gone(2, "s1", "wf_1")])
        view = derive_view([state("p00", 1)], sessions=[session("s1", "working")],
                           deliveries=folded, now_ms=0)
        self.assertEqual(session_entries(view)[0]["deliveries"], [])


class EncodeTest(unittest.TestCase):
    def test_the_view_encodes_as_compact_sorted_json(self):
        self.assertEqual(encode_view({"b": 1, "a": "é"}),
                         '{"a":"é","b":1}'.encode("utf-8"))
        self.assertNotIn(b"\n", encode_view(derive_view([state("x\ny", 1)])))


class ExclusionViewTest(unittest.TestCase):
    def test_the_view_marks_an_excluded_profile(self):
        from tests import test_console_capacity as capacity_tests
        readings = CapacityState({"work": capacity_tests.open_reading()}, {})
        names = ["home", "work"]
        plain = capacity_view(names, readings, capacity_tests.T)
        capacity = capacity_view(names, readings, capacity_tests.T, excluded={"work"})
        shown = derive_view([state("p00", 1)], capacity=capacity)
        self.assertEqual({e["profile"]: e["excluded"] for e in shown["capacity"]["profiles"]},
                         {"home": False, "work": True})
        plain_shown = derive_view([state("p00", 1)], capacity=plain)
        week = {e["profile"]: e["week_left"] for e in plain_shown["capacity"]["profiles"]}
        self.assertEqual({e["profile"]: e["week_left"] for e in shown["capacity"]["profiles"]}, week)
        self.assertIsNotNone(week["work"])


if __name__ == "__main__":
    unittest.main()


class PinViewTest(unittest.TestCase):
    def test_the_view_carries_the_pin_note(self):
        note = {"profile": "home", "in_effect": False, "reason": "out of allowance",
                "until": "2026-11-20T09:30:00+00:00", "instead": "work"}
        shown = derive_view([state("p00", 1)], pin=note)
        self.assertEqual(shown["pin"], note)
        self.assertIsNone(derive_view([state("p00", 1)])["pin"])
        self.assertIn(b'"pin":{"in_effect":false', encode_view(shown))

    def test_the_view_lists_the_profiles_launched_under_the_pin(self):
        shown = derive_view([state("p00", 1)], pin_launches=["work", "home", "work"])
        self.assertEqual(shown["pin_launches"], ["home", "work"])
        self.assertEqual(derive_view([state("p00", 1)])["pin_launches"], [])


class InboxFoldTest(unittest.TestCase):
    def test_a_changed_item_keeps_its_waiting_since(self):
        first = item("p", "k1")
        events = [
            Event(1, "t1", INBOX_SEEN, "p", first),
            Event(2, "t2", INBOX_CHANGED, "p", dict(first, answered=True)),
        ]
        record = inbox_records(events)[("p", "k1")]
        self.assertEqual(record.waiting_since, "t1")
        self.assertEqual(record.updated_at, "t2")
        self.assertIs(record.item["answered"], True)

    def test_answered_at_is_when_the_item_was_answered_not_its_last_change(self):
        open_ = item("p", "k")
        answered = {**open_, "answered": True}
        later = {**answered, "held_work": 3}
        e1 = Event(1, "t1", INBOX_SEEN, "p", open_)
        e2 = Event(2, "t2", INBOX_CHANGED, "p", answered)
        e3 = Event(3, "t3", INBOX_CHANGED, "p", later)
        e4 = Event(4, "t4", INBOX_CHANGED, "p", {**later, "answered": False})
        s1 = Event(1, "t9", INBOX_SEEN, "p", answered)
        one = inbox_records([e1, e2, e3])
        split = inbox_records([e3], inbox_records([e1, e2]))
        reopened = inbox_records([e1, e2, e3, e4])
        first_seen = inbox_records([s1])
        self.assertEqual(one[("p", "k")].answered_at, "t2")
        self.assertEqual(one[("p", "k")].updated_at, "t3")
        self.assertEqual(split[("p", "k")].answered_at, "t2")
        self.assertIsNone(reopened[("p", "k")].answered_at)
        self.assertEqual(first_seen[("p", "k")].answered_at, "t9")
        self.assertIsNone(inbox_records([e1])[("p", "k")].answered_at)

    def test_gone_and_unregistered_drop_items(self):
        a, b = item("p", "ka"), item("q", "kb")
        events = [
            Event(1, "t1", INBOX_SEEN, "p", a),
            Event(2, "t2", INBOX_SEEN, "q", b),
            Event(3, "t3", INBOX_GONE, "p", {"key": "ka"}),
            Event(4, "t4", UNREGISTERED, "q", {}),
        ]
        self.assertEqual(inbox_records(events), {})


class InboxChangesTest(unittest.TestCase):
    def test_changes_append_only_differences(self):
        a, b, d, e = (item("p", k) for k in ("ka", "kb", "kd", "ke"))
        c = item("q", "kc")
        b2 = dict(b, answered=True)
        records = {(x["project_id"], x["key"]): InboxRecord(x, "t1", "t1")
                   for x in (a, b, e, c)}
        self.assertEqual(
            inbox_changes(records, "p", [d, b2, a]),
            [(INBOX_CHANGED, "p", b2), (INBOX_SEEN, "p", d),
             (INBOX_GONE, "p", {"key": "ke"})])
        self.assertEqual(inbox_changes(records, "p", [a, b, e]), [])


class SharedKeyTest(unittest.TestCase):
    def test_a_key_two_projects_share_is_kept_once_per_project(self):
        a, b = item("p", "k"), item("q", "k")
        events = [Event(1, "t1", INBOX_SEEN, "p", a), Event(2, "t2", INBOX_SEEN, "q", b)]
        records = inbox_records(events)
        self.assertEqual(sorted(records), [("p", "k"), ("q", "k")])
        self.assertEqual(inbox_changes(records, "p", [a]), [])
        self.assertEqual(inbox_changes(records, "q", [b]), [])
        self.assertEqual(inbox_changes(records, "p", []), [(INBOX_GONE, "p", {"key": "k"})])
        result = derive_view([state("p", 1), state("q", 2)], records)
        self.assertEqual([e["project_id"] for e in result["inbox"]["open"]], ["p", "q"])
        gone = inbox_records([Event(3, "t3", INBOX_GONE, "p", {"key": "k"})], records)
        self.assertEqual(sorted(gone), [("q", "k")])
        left = inbox_records([Event(3, "t3", UNREGISTERED, "p", {})], records)
        self.assertEqual(sorted(left), [("q", "k")])


class InboxStatementTest(unittest.TestCase):
    def records(self, *items, waiting=None):
        waiting = waiting or {}
        return {(i["project_id"], i["key"]): InboxRecord(i, waiting.get(i["key"], "t1"), "u1")
                for i in items}

    def test_an_answered_item_is_shown_and_not_counted(self):
        open_item, done = item("p", "ko"), item("p", "kd", answered=True)
        result = derive_view([state("p", 1)], self.records(open_item, done))
        self.assertEqual(result["statement"]["inbox_items"], 1)
        self.assertEqual(result["statement"]["headline"], "1 thing needs you")
        self.assertEqual([e["key"] for e in result["inbox"]["open"]], ["ko"])
        self.assertEqual([e["key"] for e in result["inbox"]["answered"]], ["kd"])
        self.assertEqual(result["inbox"]["answered"][0]["type"], "inbox_item")
        self.assertEqual(result["inbox"]["open"][0], {
            **{k: v for k, v in open_item.items() if k != "question"},
            "type": "inbox_item", "waiting_since": "t1", "stale": False, "read_at": "u1",
            "headline": "Which one?", "more_questions": 0, "answered_at": None})

    def test_an_items_headline_is_its_first_question_with_a_count(self):
        boiler = foa.SENTENCES["decision"]

        def q(text):
            return {"question": text, "options": ["a", "b"], "chosen": None,
                    "recommended": None}

        def decision(key, questions):
            return {**item("p", key), "reason": "decision", "question": boiler,
                    "questions": questions}

        three = decision("k3", [q("Which database?"), q("Which port?"), q("Which host?")])
        one = decision("k1", [q("Which cache?")])
        unread = decision("k0", [])
        conflict = {**item("p", "kc"), "reason": "conflict", "items": ["x"],
                    "question": "Landing stopped on a second merge conflict."}
        opened = derive_view([state("p", 1)], self.records(three, one, unread, conflict))[
            "inbox"]["open"]
        by_key = {entry["key"]: entry for entry in opened}
        self.assertEqual(
            {k: (e["headline"], e["more_questions"]) for k, e in by_key.items()},
            {"k3": ("Which database?", 2), "k1": ("Which cache?", 0),
             "k0": (view.UNREAD_DECISION, 0),
             "kc": ("Landing stopped on a second merge conflict.", 0)})
        for entry in by_key.values():
            self.assertNotIn("question", entry)

    def test_the_decision_boilerplate_is_nowhere_in_the_view(self):
        boiler = foa.SENTENCES["decision"]
        asked = {"question": "Which one?", "options": ["a", "b"], "chosen": None,
                 "recommended": None}
        base = {**item("p", "kd"), "reason": "decision", "question": boiler,
                "questions": [asked]}
        events = [
            Event(1, "2026-11-11T10:00:00+00:00", INBOX_SEEN, "p", base),
            Event(2, "2026-11-11T10:01:00+00:00", INBOX_SEEN, "p",
                  {**base, "key": "kd2", "answered": True})]
        made = digest.digest(digest.moments(events, {}, {}), None,
                             datetime.fromisoformat("2026-11-11T12:00:00+00:00"))
        result = derive_view([state("p", 1)], inbox_records(events), digest=made)
        self.assertEqual(len(result["digest"]["recent"]), 2)
        self.assertNotIn(boiler.encode(), encode_view(result))
        self.assertIsNone(re.search(r"#\d", json.dumps(result["digest"])))

    def test_an_answered_item_carries_when_it_was_answered(self):
        records = {("p", "ko"): InboxRecord(item("p", "ko"), "t1", "u1"),
                   ("p", "kd"): InboxRecord(item("p", "kd", answered=True), "t1", "u3", "u2")}
        result = derive_view([state("p", 1)], records)["inbox"]
        self.assertEqual(result["answered"][0]["answered_at"], "u2")
        self.assertIsNone(result["open"][0]["answered_at"])

    def test_the_headline_counts_open_items(self):
        table = [(0, "Nothing needs you"), (1, "1 thing needs you"),
                 (3, "3 things need you")]
        for n, headline in table:
            with self.subTest(open=n):
                records = self.records(*(item("p", f"k{i}") for i in range(n)))
                statement = derive_view([state("p", 1)], records)["statement"]
                self.assertEqual(statement["headline"], headline)
                self.assertEqual(statement["inbox_items"], n)
                if n:
                    self.assertEqual(statement["sentence"], NEEDS_SENTENCE)

    def test_the_sentence_offers_the_keys_only_when_an_item_can_be_answered(self):
        decision = {**item("p", "kd"), "reason": "decision", "questions": [
            {"question": "Which?", "options": ["a", "b"], "chosen": None,
             "recommended": None}]}
        table = [
            ("a question", [item("p", "kq")], NEEDS_SENTENCE),
            ("a decision behind a conflict",
             [{**item("p", "kc"), "reason": "conflict", "items": ["x"]}, decision],
             CHOOSE_SENTENCE),
            ("an unverified prompt", [{**decision, "questions": []}], NEEDS_SENTENCE),
            ("an answered decision",
             [item("p", "kq"), {**decision, "answered": True}], NEEDS_SENTENCE),
        ]
        for name, items, expected in table:
            with self.subTest(name):
                sentence = derive_view([state("p", 1)], self.records(*items))[
                    "statement"]["sentence"]
                self.assertEqual(sentence, expected)

    def test_a_verify_item_says_it_can_be_answered_here(self):
        check = {**item("p", "kv"), "reason": "verify-ask", "kind": "manual-check",
                 "answers": ["passed", "failed", "note"]}
        act = {**item("p", "ka"), "reason": "verify-act", "kind": "act", "answers": []}
        decision = {**item("p", "kd"), "reason": "decision", "questions": [
            {"question": "Which?", "options": ["a", "b"], "chosen": None, "recommended": None}]}
        table = [("a manual check", [check], view.ANSWER_SENTENCE),
                 ("a manual check and a decision", [check, decision], CHOOSE_SENTENCE),
                 ("an act prompt alone", [act], NEEDS_SENTENCE)]
        for name, items, expected in table:
            with self.subTest(name):
                sentence = derive_view([state("p", 1)], self.records(*items))["statement"]["sentence"]
                self.assertEqual(sentence, expected)

    def test_open_items_are_ordered_by_held_work(self):
        items = [item("p", "a", held=1), item("p", "b", held=5),
                 item("p", "c", held=3), item("p", "d", held=3)]
        records = self.records(*items, waiting={"a": "t1", "b": "t3",
                                                "c": "t2", "d": "t1"})
        result = derive_view([state("p", 1)], records)
        self.assertEqual([e["key"] for e in result["inbox"]["open"]],
                         ["b", "d", "c", "a"])

    def test_a_stale_tracker_never_says_nothing_needs_you(self):
        states = [state("p", 1)]
        failed = {"p": ReadState(False, "r1")}
        empty = derive_view(states, None, failed)["statement"]
        self.assertEqual(empty["headline"], STALE_HEADLINE)
        self.assertIs(empty["stale"], True)
        self.assertEqual(empty["sentence"], STALE_SENTENCE.format(projects="p"))
        records = self.records(item("p", "k"))
        shown = derive_view(states, records, failed)
        self.assertEqual(shown["statement"]["headline"], "1 thing needs you")
        self.assertEqual(shown["statement"]["sentence"],
                         STALE_SENTENCE.format(projects="p"))
        self.assertIs(shown["inbox"]["open"][0]["stale"], True)
        self.assertEqual(shown["inbox"]["open"][0]["read_at"], "r1")
        unknown = derive_view(states, records, {"p": ReadState(False, None)})
        self.assertEqual(unknown["inbox"]["open"][0]["read_at"], "u1")
        healthy = {"p": ReadState(True, "r2")}
        fresh = derive_view(states, records, healthy)["inbox"]["open"][0]
        self.assertIs(fresh["stale"], False)
        self.assertEqual(fresh["read_at"], "r2")
        quiet = derive_view(states, None, healthy)["statement"]
        self.assertEqual(quiet["headline"], "Nothing needs you")
        self.assertIs(quiet["stale"], False)

    def test_items_of_unregistered_projects_are_not_shown(self):
        records = self.records(item("q", "k"))
        result = derive_view([state("p", 1)], records,
                             {"q": ReadState(False, "r1")})
        self.assertEqual(result["statement"]["inbox_items"], 0)
        self.assertEqual(result["inbox"], {"open": [], "answered": []})
        self.assertIs(result["statement"]["stale"], False)


SLUG, OWNER_PROJECT = "octo/widgets", "owner/p00"
HOLD = 'Held for verification.\n\n```verify\n{"checks": []}\n```'


def owner_comment(cid, body):
    return {"fullDatabaseId": str(cid), "body": body, "authorAssociation": "OWNER",
            "createdAt": "2026-11-10T09:00:00Z", "updatedAt": "2026-11-10T09:00:00Z"}


def ask_prompt(extra="Open the staging site.\n\n- [ ] Accept\n- [ ] Reject"):
    return fm.render("owner-action", {"reason": "verify-ask", "block": "10.abc", "check": "0", "host": "mbp"},
                     "AC1: the owner's answer is needed.", extra)


def decision_prompt(extra):
    return fm.render("owner-action", {"reason": "verify-decision", "block": "10.abc", "check": "0",
                                      "on": "fail", "result": "55"}, "AC1 failed: the owner decides.", extra)


def held_node(number, comments):
    return {"__typename": "Issue", "number": number, "issueDependenciesSummary": {"blocking": 0},
            "repository": {"defaultBranchRef": {"name": "main"}},
            "blocking": {"totalCount": 0, "nodes": []},
            "comments": {"totalCount": len(comments), "nodes": comments}}


def inbox_view(node):
    """What the page derives for one registered project whose tracker read returned `node`."""
    items = inbox.items_from_node(OWNER_PROJECT, SLUG, node)
    events = [event(1, REGISTERED, OWNER_PROJECT, {"root": "/srv/p00"})]
    events += [Event(2 + n, f"t{2 + n}", kind, project, payload)
               for n, (kind, project, payload) in enumerate(inbox_changes({}, OWNER_PROJECT, items))]
    return derive_view(project_states(events).values(), inbox_records(events))


class HeldVerificationViewTest(unittest.TestCase):
    def test_a_held_issue_with_no_owner_prompt_yields_no_inbox_item(self):
        def marker(kind, **fields):
            return fm.render(kind, {"block": "10.abc", "check": "0", **fields}, "Recorded.")
        quiet = [HOLD, marker("verify-due"), marker("verify-seen"), marker("verify-result", state="pass"),
                 marker("verify-run"), ask_prompt()]
        quiet_comments = [owner_comment(100 + n, body) for n, body in enumerate(quiet)]
        quiet_comments.append(owner_comment(200, fm.end_body(105, "resolved")))
        held = inbox_view(held_node(21, quiet_comments))
        self.assertEqual(held["inbox"], {"open": [], "answered": []})
        self.assertEqual(held["statement"]["inbox_items"], 0)
        live = inbox_view(held_node(22, [*quiet_comments[:5], owner_comment(105, ask_prompt())]))
        self.assertEqual([i["kind"] for i in live["inbox"]["open"]], ["manual-check"])
        self.assertEqual(live["statement"]["inbox_items"], 1)

    def test_a_prompt_with_both_boxes_ticked_stays_open_and_counted(self):
        both = [owner_comment(300, ask_prompt("Open the staging site.\n\n- [x] Accept\n- [x] Reject")),
                owner_comment(301, decision_prompt("- [x] Accept as passed\n- [x] Close as not verified"))]
        result = inbox_view(held_node(23, both))
        self.assertEqual([i["kind"] for i in result["inbox"]["open"]], ["manual-check", "verdict"])
        self.assertEqual(result["inbox"]["answered"], [])
        self.assertEqual(result["statement"]["inbox_items"], 2)


    def test_a_manual_check_is_headed_by_its_ask(self):
        ask = ("Open the console at 1440 px and say whether the question is readable at a glance. "
               "Note anything that hides it.")
        node = held_node(24, [owner_comment(400, ask_prompt(f"{ask}\n\n- [ ] Accept\n- [ ] Reject")),
                              owner_comment(401, decision_prompt(
                                  "- [ ] Accept as passed\n- [ ] Close as not verified"))])
        by_kind = {i["kind"]: i for i in inbox_view(node)["inbox"]["open"]}
        check = by_kind["manual-check"]
        self.assertEqual((check["headline"], check["check_id"], check["detail"]),
                         ("Open the console at 1440 px and say whether the question is readable at a glance.",
                          "AC1", "Note anything that hides it."))
        self.assertNotIn("question", check)
        verdict = by_kind["verdict"]
        self.assertEqual((verdict["headline"], verdict["check_id"]), ("AC1 failed: the owner decides.", ""))


class InboxHealthTest(unittest.TestCase):
    def test_health_is_folded_from_its_changes(self):
        table = [
            (Event(1, "t1", INBOX_HEALTH, "p", {"ok": True}),
             {"p": ReadState(True, "t1")}),
            (Event(2, "t2", INBOX_HEALTH, "p", {"ok": False, "read_at": "t1"}),
             {"p": ReadState(False, "t1")}),
            (Event(3, "t3", INBOX_HEALTH, "p", {"ok": False, "read_at": None}),
             {"p": ReadState(False, None)}),
            (Event(4, "t4", INBOX_HEALTH, "p", {"ok": "no"}),
             {"p": ReadState(False, None)}),
            (Event(4, "t4", INBOX_HEALTH, "p", {"ok": False, "read_at": "t0"}),
             {"p": ReadState(False, "t0")}),
            (Event(4, "t4", INBOX_HEALTH, "p", {"ok": False, "read_at": 5}),
             {"p": ReadState(False, None)}),
            (Event(5, "t5", UNREGISTERED, "p", {}), {}),
        ]
        health = {}
        for ev, expected in table:
            with self.subTest(seq=ev.seq):
                health = read_states([ev], health)
                self.assertEqual(health, expected)

    def test_only_a_change_of_health_is_an_event(self):
        ok, bad = ReadState(True, "r1"), ReadState(False, "r1")
        down = [(INBOX_HEALTH, "p", {"ok": False, "read_at": "r1"})]
        up = [(INBOX_HEALTH, "p", {"ok": True})]
        table = [
            ({}, True, None, up),
            ({}, False, None,
             [(INBOX_HEALTH, "p", {"ok": False, "read_at": None})]),
            ({"p": ok}, False, "r1", down),
            ({"p": ok}, True, None, []),
            ({"p": bad}, False, "r1", []),
            ({"p": bad}, True, None, up),
        ]
        for health, flag, read_at, expected in table:
            with self.subTest(health=health, ok=flag):
                self.assertEqual(health_change(health, "p", flag, read_at),
                                 expected)
        self.assertEqual(INBOX_HEALTH, "inbox.health")


T0 = "2026-11-12T10:00:00.000000+00:00"
T0_MS = int(datetime.fromisoformat(T0).timestamp() * 1000)


def sprint(sid, pid="p00", seq=5, goal="make the importer resumable"):
    return SprintState(sid, pid, goal, seq, T0)


PARTS = {"title": "Ship the importer", "done": "ship it", "excluded": ["x"], "slices": ["a"],
         "risks": ["r"], "asks": ["q"]}


def briefed(sprint, version=1, decision=NONE, reply=None, at="t9"):
    return dataclasses.replace(sprint, brief=Brief(version, PARTS, at, decision, reply))


GOAL = "Make the importer resumable after a crash. " + "g" * 1357
TITLE = "Importer resumes after a crash"


def first_screen_view(**extra):
    """A view of four sprints of one project, each with a different open item, all with `GOAL`."""
    names = ("brief", "stall", "idle", "stop")
    ids = {name: chr(ord("a") + n) * 16 for n, name in enumerate(names)}
    sprints = {
        ids["brief"]: sprint(ids["brief"], seq=8, goal=GOAL),
        ids["stall"]: dataclasses.replace(sprint(ids["stall"], seq=7, goal=GOAL), stalled="x",
                                          stalled_at=T0),
        ids["idle"]: dataclasses.replace(sprint(ids["idle"], seq=6, goal=GOAL), no_progress_at=T0),
        ids["stop"]: sprint(ids["stop"], seq=5, goal=GOAL)}
    sprints[ids["brief"]] = briefed(sprints[ids["brief"]])
    pending = {ids["stop"]: PendingStop(ids["stop"], "p00", GOAL, T0, "boom", T0)}
    return derive_view([state("p00", 1)], sprints=sprints, pending=pending, **extra), ids


class FirstScreenViewTest(unittest.TestCase):
    def test_a_long_goal_is_carried_only_by_its_sprint_entry(self):
        sid = "a" * 16
        s = briefed(sprint(sid, goal=GOAL), decision=APPROVED)
        s = dataclasses.replace(s, brief=dataclasses.replace(
            s.brief, parts={**PARTS, "title": TITLE}))
        s = dataclasses.replace(s, questions=(
            Question(7, 0, "t9", False, "Which store keeps the checkpoints?", "the resume slice",
                     ("sqlite", "files"), "files", context="A crash loses an hour of work."),))
        view = derive_view([state("p00", 1)], sprints={sid: s})
        text = encode_view(view).decode()
        self.assertEqual(text.count(GOAL), 1)
        (shown,) = view["entries"][0]["sprints"]
        self.assertEqual((shown["title"], shown["goal"]), (TITLE, GOAL))
        (asking,) = view["inbox"]["open"]
        self.assertEqual(asking["title"], TITLE)
        self.assertEqual(asking["context"], "A crash loses an hour of work.")
        self.assertNotIn("goal", asking)

    def test_every_item_names_the_sprint_by_its_title(self):
        view, ids = first_screen_view()
        items = {i["reason"]: i for i in view["inbox"]["open"]}
        self.assertEqual(sorted(items), ["brief", "manager", "progress"])
        title = sprint_title(sprint("z" * 16, goal=GOAL))
        for found in (*items.values(), *view["unstopped"]):
            with self.subTest(found.get("reason", "unstopped")):
                self.assertLessEqual(len(found["title"]), 60)
                self.assertNotIn("goal", found)
        self.assertEqual(items["brief"]["title"], "Ship the importer")
        self.assertEqual(items["manager"]["title"], title)
        self.assertEqual(items["manager"]["headline"], "managers keep failing on " + title)
        self.assertEqual(items["progress"]["headline"],
                         "the manager has stopped making progress on " + title)
        self.assertEqual(view["unstopped"][0]["title"], title)
        shown = sum(len(e["sprints"]) for e in view["entries"])
        self.assertEqual(shown, 4)
        self.assertEqual(encode_view(view).decode().count(GOAL), shown)

    def test_a_sprint_without_a_brief_is_named_by_its_goals_first_sentence(self):
        sid = "a" * 16
        view = derive_view([state("p00", 1)], sprints={sid: sprint(sid, goal=GOAL)})
        self.assertEqual(view["entries"][0]["sprints"][0]["title"],
                         "Make the importer resumable after a crash.")

    def asking(self, question):
        sid = "a" * 16
        s = dataclasses.replace(sprint(sid), questions=(question,))
        (found,) = derive_view([state("p00", 1)], sprints={sid: s})["inbox"]["open"]
        return found

    def test_a_logged_question_over_the_limits_shows_cut(self):
        long_option = "o" * 120
        found = self.asking(Question(7, 0, "t9", False, "q" * 600, "the slice",
                                     (long_option, "files"), long_option, context="c" * 900))
        (shown,) = found["questions"]
        self.assertEqual(len(found["headline"]), 140)
        self.assertTrue(found["headline"].endswith("…"))
        self.assertEqual(len(found["context"]), 400)
        self.assertEqual(len(shown["options"][0]), 80)
        self.assertEqual(shown["recommended"], shown["options"][0])
        self.assertEqual(shown["recommended_index"], 0)

    def test_a_questions_pictures_reach_its_entry_cut(self):
        found = self.asking(Question(7, 0, "t9", False, "Which?", "the slice", ("a", "b"), "a",
                                     pictures=(QuestionPicture("a" * 64, "l" * 200, "before"),
                                               QuestionPicture("b" * 64, "x"))))
        self.assertEqual(found["pictures"],
                         [{"id": "a" * 64, "line": cut("l" * 200, 140), "pair": "before"},
                          {"id": "b" * 64, "line": "x", "pair": None}])
        plain = self.asking(Question(7, 0, "t9", False, "Which?", "the slice", ("a", "b"), "a"))
        self.assertEqual(plain["pictures"], [])

    def test_a_recommendation_keeps_its_index_when_cut_options_collide(self):
        options = ("o" * 85 + "a", "o" * 85 + "b")
        found = self.asking(Question(7, 0, "t9", False, "Which?", "the slice", options,
                                     options[1]))
        (shown,) = found["questions"]
        self.assertEqual(shown["options"], ["o" * 79 + "…", "o" * 79 + "…"])
        self.assertEqual(shown["recommended_index"], 1)


class BriefViewTest(unittest.TestCase):
    def test_a_briefs_pictures_reach_its_entry_cut(self):
        sid = "a" * 16
        s = briefed(sprint(sid))
        plain = derive_view([state("p00", 1)], sprints={sid: s})
        self.assertEqual(plain["inbox"]["open"][0]["pictures"], [])
        s = dataclasses.replace(s, brief=dataclasses.replace(s.brief, pictures=(
            QuestionPicture("a" * 64, "l" * 200, "before"), QuestionPicture("b" * 64, "x"))))
        item = derive_view([state("p00", 1)], sprints={sid: s})["inbox"]["open"][0]
        self.assertEqual(item["pictures"], [
            {"id": "a" * 64, "line": cut("l" * 200, 140), "pair": "before"},
            {"id": "b" * 64, "line": "x", "pair": None}])
        self.assertNotIn("pictures", item["brief"])

    def test_a_waiting_brief_is_one_open_item_counted_in_the_statement(self):
        sid = "a" * 16
        view = derive_view([state("p00", 1)], sprints={sid: briefed(sprint(sid), version=2)})
        self.assertEqual(view["inbox"]["open"], [{
            "type": "inbox_item", "reason": "brief", "key": "brief/" + sid,
            "project_id": "p00", "sprint_id": sid, "title": "Ship the importer",
            "version": 2, "brief": PARTS, "pictures": [], "answered": False,
            "waiting_since": "t9", "started_by": None}])
        self.assertEqual(view["statement"]["inbox_items"], 1)
        self.assertEqual(view["statement"]["headline"], "1 thing needs you")
        self.assertEqual(view["statement"]["sentence"], BRIEF_SENTENCE)

    def test_briefs_lead_the_tracker_items(self):
        a, b = "a" * 16, "b" * 16
        records = {("p00", "k1"): InboxRecord(item("p00", "k1", held=9), "t1", "u1")}
        view = derive_view([state("p00", 1)], records, sprints={
            a: briefed(sprint(a), at="t7"), b: briefed(sprint(b), at="t5")})
        self.assertEqual([e["key"] for e in view["inbox"]["open"]],
                         ["brief/" + b, "brief/" + a, "k1"])
        self.assertEqual(view["statement"]["inbox_items"], 3)

    def test_a_brief_of_a_sprint_with_a_stop_requested_is_no_item(self):
        sid = "a" * 16
        stopping = dataclasses.replace(briefed(sprint(sid)), stop_at="t10")
        view = derive_view([state("p00", 1)], sprints={sid: stopping})
        self.assertEqual(view["inbox"]["open"], [])

    def test_a_stopping_sprints_pending_brief_is_not_the_owners_ball_nor_a_task(self):
        sid = "a" * 16
        stopping = dataclasses.replace(briefed(sprint(sid)), stop_at="t10")
        view = derive_view([state("p00", 1)], sprints={sid: stopping}, now_ms=T0_MS)
        self.assertNotEqual(view["entries"][0]["sprints"][0]["ball"], "owner")
        self.assertNotEqual(sprint_ball(stopping, T0_MS, 0, ()), "owner")
        self.assertEqual(sprint_ball(briefed(sprint(sid)), T0_MS, 0, ()), "owner")
        self.assertEqual(view["statement"]["inbox_items"], 0)
        self.assertEqual(view["statement"]["headline"], "Nothing needs you")

    def test_a_brief_of_a_closed_or_stopped_sprint_is_no_item(self):
        a, b = "a" * 16, "b" * 16
        view = derive_view([state("p00", 1)], sprints={
            a: closed(briefed(sprint(a)), 5 * MIN, ((12, "landed"),)),
            b: dataclasses.replace(briefed(sprint(b)), stopped_at="t10")})
        self.assertEqual(view["inbox"]["open"], [])

    def test_a_decided_or_unregistered_brief_is_no_item(self):
        a, b, c = "a" * 16, "b" * 16, "c" * 16
        view = derive_view([state("p00", 1)], sprints={
            a: briefed(sprint(a), decision=APPROVED),
            b: briefed(sprint(b), decision=CHANGES, reply="shrink it"),
            c: briefed(sprint(c, pid="p09"))})
        self.assertEqual(view["inbox"]["open"], [])
        self.assertEqual(view["statement"], derive_view([state("p00", 1)])["statement"])

    def test_an_approved_brief_makes_the_sprint_starting(self):
        sid = "a" * 16
        for decision, name, text in ((APPROVED, "starting", "starting"),
                                     (NONE, "drafting", "drafting the brief")):
            with self.subTest(decision=decision):
                view = derive_view([state("p00", 1)], sprints={
                    sid: briefed(sprint(sid), decision=decision)})
                shown = view["entries"][0]["sprints"][0]
                self.assertEqual((shown["state"], shown["state_text"]), (name, text))

    def test_a_sprint_with_a_brief_never_says_no_manager(self):
        a, b = "a" * 16, "b" * 16
        view = derive_view([state("p00", 1)], sprints={a: briefed(sprint(a, seq=6)),
                                                       b: sprint(b, seq=5)},
                           now_ms=T0_MS + 10 * 60_000)
        shown = {s["sprint_id"]: s["manager_text"] for s in view["entries"][0]["sprints"]}
        self.assertEqual(shown, {a: None, b: "no manager has picked this up"})

    def test_the_brief_sentence_yields_only_to_all_out_and_stale(self):
        sid = "a" * 16
        sprints = {sid: briefed(sprint(sid))}
        decision = {**item("p00", "kd"), "reason": "decision", "questions": [
            {"question": "Which?", "options": ["a", "b"], "chosen": None, "recommended": None}]}
        records = {("p00", "kd"): InboxRecord(decision, "t1", "u1")}
        stale = STALE_SENTENCE.format(projects="p00")
        table = [
            ("a decision item", {"records": records}, BRIEF_SENTENCE),
            ("a stale project", {"health": {"p00": ReadState(False, None)}}, stale),
            ("every profile out", {"capacity": {**EMPTY, "all_out": True}}, ALL_OUT_SENTENCE),
        ]
        for name, extra, expected in table:
            with self.subTest(name):
                view = derive_view([state("p00", 1)], sprints=sprints, **extra)
                self.assertEqual(view["statement"]["sentence"], expected)


class ManagerViewTest(unittest.TestCase):
    SID = "a" * 16
    NAME = "p00 sprint " + "a" * 16

    def shown(self, manager=None, now_ms=T0_MS, sessions=(), brief=False, **extra):
        shown = dataclasses.replace(sprint(self.SID), manager=manager)
        if brief:
            shown = briefed(shown)
        view = derive_view([state("p00", 1)], sessions=sessions, sprints={self.SID: shown},
                           now_ms=now_ms, **extra)
        return view["entries"][0]["sprints"][0]

    def test_a_started_manager_shows_no_text_and_no_retry(self):
        manager = Manager("started", T0, "work", self.NAME)
        entry = self.shown(manager, T0_MS + 10 * 60_000,
                           [session("m1", "working", name=self.NAME)])
        self.assertEqual((entry["manager_state"], entry["manager_text"], entry["retry"],
                          entry["manager_until"]), ("started", None, False, None))
        self.assertEqual([s["session_id"] for s in entry["sessions"]], ["m1"])

    def test_a_started_manager_that_never_appears_offers_retry(self):
        manager = Manager("started", T0, "work", self.NAME)
        early = self.shown(manager, T0_MS + 60_000)
        self.assertEqual((early["manager_state"], early["retry"]), ("started", False))
        late = self.shown(manager, T0_MS + 10 * 60_000)
        self.assertEqual((late["manager_state"], late["manager_text"], late["retry"]),
                         ("missing", "the manager is not running", True))
        briefed_ = self.shown(manager, T0_MS + 10 * 60_000, brief=True)
        self.assertEqual((briefed_["manager_state"], briefed_["retry"]), ("started", False))

    def test_a_failed_start_shows_its_reason_and_retry(self):
        entry = self.shown(Manager("failed", T0, reason="the directory is not trusted"))
        self.assertEqual((entry["manager_state"], entry["manager_text"], entry["retry"]),
                         ("failed", "could not start a manager: this account does not trust the project's folder",
                          True))

    def test_waiting_on_quota_reads_until_the_earliest_reset(self):
        until = "2026-11-13T00:00:00+00:00"
        entry = self.shown(Manager("waiting", T0, until=until))
        self.assertEqual((entry["manager_state"], entry["manager_text"],
                          entry["manager_until"], entry["retry"]),
                         ("waiting", "waiting on quota until", until, True))

    def test_no_manager_after_two_minutes_offers_retry(self):
        late = self.shown(None, T0_MS + 120_001)
        self.assertEqual((late["manager_state"], late["retry"]), ("none", True))
        self.assertEqual(self.shown(None, T0_MS)["retry"], False)
        done = self.shown(None, T0_MS + 120_001, brief=True)
        self.assertEqual((done["retry"], done["manager_text"]), (False, None))

    def test_without_managers_every_sprint_says_not_available(self):
        failed = Manager("failed", T0, reason="x")
        entry = self.shown(failed, managers=False)
        self.assertEqual((entry["manager_state"], entry["manager_text"], entry["retry"]),
                         ("unavailable", "managers are not available on this host yet", False))
        sprints = {self.SID: dataclasses.replace(sprint(self.SID), manager=failed)}
        self.assertIs(derive_view([state("p00", 1)], sprints=sprints, managers=False)["managers"],
                      False)
        self.assertIs(derive_view([state("p00", 1)], sprints=sprints)["managers"], True)

    def test_a_sprint_session_shows_inside_its_sprint_not_outside(self):
        sessions = [session("m1", "working", name=self.NAME, seq=3),
                    session("o1", "idle", seq=2),
                    session("w1", "waiting_answer", name=self.NAME, seq=4)]
        view = derive_view([state("p00", 1)], sessions=sessions,
                           sprints={self.SID: sprint(self.SID)}, now_ms=T0_MS + 10 * 60_000)
        project = view["entries"][0]
        entry = project["sprints"][0]
        self.assertEqual([(s["session_id"], s["state_text"]) for s in entry["sessions"]],
                         [("w1", "waiting for an answer"), ("m1", "working")])
        outside = project["outside_sprints"]
        self.assertEqual([s["session_id"] for s in outside["sessions"]], ["o1"])
        self.assertEqual((outside["working"], outside["waiting"], outside["summary"]),
                         (0, 0, "1 idle"))
        self.assertIsNone(entry["manager_text"])
        permission = derive_view(
            [state("p00", 1)], sessions=[session("p1", "waiting_permission", name=self.NAME)],
            sprints={self.SID: sprint(self.SID)})["entries"][0]["sprints"][0]
        self.assertEqual(permission["sessions"][0]["state_text"], "waiting for a permission")




MIN = 60_000
R = T0_MS + MIN
SEVEN = ((1, "landed"), (2, "landed"), (3, "landed"), (4, "building"), (5, "plan review"),
         (6, "queued"), (7, "queued"))
A = "a" * 16


def iso(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat(timespec="microseconds")


def started(sid, decided_ms=T0_MS):
    return dataclasses.replace(
        sprint(sid), brief=Brief(1, PARTS, T0, APPROVED, None, iso(decided_ms)))


def reported(state, at_ms, phase="running", issues=SEVEN, inbox=(),
             status="two slices are building"):
    return dataclasses.replace(state, report=Report(
        iso(at_ms), status, phase, "Importer resumes",
        "https://github.com/owner/p00/milestone/3", issues, inbox, "start the resume slice"))


def observed(state, moved_ms, *stages, run_id="wf_c"):
    return dataclasses.replace(
        state, observed=tuple(Observed(s.issue, moved_ms, "s1", run_id, s) for s in stages),
        moved_ms=moved_ms)


def entry(view):
    return next(s for e in view["entries"] for s in e["sprints"])


def line(sprint_state, now_ms, records=None, projects=None, **extra):
    projects = projects or [state("p00", 1)]
    return derive_view(projects, records, sprints={A: sprint_state}, now_ms=now_ms, **extra)


def open_item(pid, key, issue, answered=False):
    return InboxRecord({**item(pid, key, answered=answered), "issue": issue}, "t1", "u1")


CHECK_Q = "Do the before and after pictures read well?"
MISSING = object()
HELD_SPRINT = reported(started(A), R, issues=((12, "building"), (13, "landed"), (30, "held")))


def check_item(pid, key, issue, blocking=(), answered=False):
    return InboxRecord({
        **item(pid, key, answered=answered), "issue": issue, "reason": "verify-ask",
        "kind": "manual-check", "question": CHECK_Q, "answers": ["passed", "failed", "note"],
        **({} if blocking is MISSING else {"blocking": blocking})}, "t1", "u1")


NAME = "p00 sprint " + A
U = "2026-11-13T09:30:00+00:00"


def with_manager(s, profile="work", state="started"):
    return dataclasses.replace(s, manager=Manager(state, T0, profile, NAME))


def out(profile="work"):
    return {"tight": False, "all_out": False, "resumes_at": None, "no_reading": None,
            "profiles": [{"profile": profile, "state": "out", "week_left": 0,
                          "five_hour_left": None, "next_reset": None, "out_until": U,
                          "read_at": T0}]}


class SprintQuotaViewTest(unittest.TestCase):
    def test_state_waiting_on_quota_replaces_starting_on_track_and_quiet(self):
        cases = ((with_manager(started(A)), T0_MS + 5 * MIN),
                 (with_manager(reported(started(A), R)), R + 4 * MIN),
                 (with_manager(reported(started(A), R)), R + 16 * MIN))
        for it, now in cases:
            with self.subTest(now=now):
                shown = entry(line(it, now, capacity=out()))
                self.assertEqual((shown["state"], shown["state_text"], shown["state_until"]),
                                 ("quota", "waiting on quota until", U))

    def test_quota_never_replaces_waiting_closing_done_or_drafting(self):
        records = {("p00", "k1"): open_item("p00", "k1", 12)}
        waiting = reported(started(A), R, issues=((12, "building"),))
        closing = with_manager(reported(started(A), R, phase="closing"))
        cases = (
            ("waiting", with_manager(waiting), R + 4 * MIN, records),
            ("closing", closing, R + MIN, None),
            ("quiet", closing, R + 20 * MIN, None),
            ("done", with_manager(reported(started(A), R, phase="done")), R + MIN, None),
            ("drafting", with_manager(sprint(A)), R + MIN, None),
            ("stopping", dataclasses.replace(with_manager(started(A)), stop_at=T0), R + MIN, None),
        )
        for expected, it, now, recs in cases:
            with self.subTest(expected=expected, now=now):
                shown = entry(line(it, now, recs, capacity=out()))
                self.assertEqual(shown["state"], expected)
                self.assertIsNone(shown["state_until"])

    def test_only_the_managers_own_out_profile_makes_it_wait(self):
        it = with_manager(reported(started(A), R))
        for label, sprint_state, extra in (
                ("other profile", it, {"capacity": out("home")}),
                ("failed manager", with_manager(reported(started(A), R), state="failed"),
                 {"capacity": out()}),
                ("no capacity", it, {})):
            with self.subTest(label):
                shown = entry(line(sprint_state, R + 4 * MIN, **extra))
                self.assertEqual(shown["state"], "on_track")
                self.assertIsNone(shown["state_until"])

    def test_a_manager_that_stopped_making_progress_is_one_inbox_item(self):
        stopped = dataclasses.replace(with_manager(reported(started(A), R)),
                                      no_progress_at=iso(R + 30 * MIN))
        shown = line(stopped, R + 31 * MIN)
        expected = {"type": "inbox_item", "reason": "progress", "key": "progress/" + A,
                    "project_id": "p00", "sprint_id": A, "title": "Ship the importer",
                    "headline": "the manager has stopped making progress on "
                                "Ship the importer",
                    "last_status": "two slices are building", "answered": False,
                    "waiting_since": iso(R + 30 * MIN)}
        self.assertEqual(shown["inbox"]["open"], [expected])
        self.assertEqual(shown["statement"]["inbox_items"], 1)
        self.assertEqual(shown["statement"]["headline"], "1 thing needs you")
        self.assertEqual(shown["statement"]["sentence"], view.PROGRESS_SENTENCE)
        self.assertEqual(view.PROGRESS_SENTENCE,
                         "Tell the manager to continue, or drop the sprint.")
        bare = dataclasses.replace(with_manager(started(A)), no_progress_at=iso(R))
        self.assertIsNone(line(bare, R + MIN)["inbox"]["open"][0]["last_status"])
        both = dataclasses.replace(stopped, stalled="r", stalled_at=iso(R + 40 * MIN))
        shown = line(both, R + 41 * MIN)
        self.assertEqual([i["reason"] for i in shown["inbox"]["open"]], ["manager", "progress"])
        self.assertEqual(shown["statement"]["sentence"], view.MANAGER_SENTENCE)


def permission_item(sid=A, prompt=7, title="make the importer resumable"):
    """A permission card as `prompt_card.inbox_entries` shapes it (#1424)."""
    return {"type": "inbox_item", "reason": "permission", "key": f"permission/{prompt}",
            "project_id": "p00", "sprint_id": sid, "prompt": prompt, "title": title,
            "headline": f"The manager of {title} asks to run a command",
            "words": "Create the delivery's worktree", "command": "git worktree add ../w",
            "answered": False, "waiting_since": iso(R)}


class HeadingCountsOwnerBallTest(unittest.TestCase):
    """The heading never says "Nothing needs you" beside a sprint whose ball is the owner's (#1247)."""

    def shown(self, sprint_state, sessions=(), records=None, prompts=()):
        return derive_view([state("p00", 1)], records, sprints={A: sprint_state},
                           sessions=sessions, now_ms=R + 2 * MIN, managers=True,
                           prompt_items=prompts)

    def test_every_sprint_state_with_the_owners_ball_is_counted_in_the_heading(self):
        base = with_manager(reported(started(A), R))
        working = [session("s1", "working", name=NAME)]
        card = [permission_item()]
        table = [
            ("an open permission card", base, working, None, card, 1),
            ("a brief", dataclasses.replace(sprint(A), brief=Brief(1, PARTS, T0, NONE, None, None)),
             [], None, (), 1),
            ("a stall", dataclasses.replace(base, stalled="r", stalled_at=iso(R + MIN)), [], None, (), 1),
            ("no progress", dataclasses.replace(base, no_progress_at=iso(R + MIN)), [], None, (), 1),
            ("a failed start", dataclasses.replace(
                with_manager(sprint(A), state="failed"),
                manager=Manager("failed", T0, "work", NAME, reason="x")), [], None, (), 1),
            ("an open item the sprint names", reported(started(A), R, inbox=(12,)), [],
             {("p00", "k1"): open_item("p00", "k1", 12)}, (), 1),
            ("a stall and an open card", dataclasses.replace(
                base, stalled="r", stalled_at=iso(R + MIN)), working, None, card, 2),
            ("an open item and an open card", reported(started(A), R, inbox=(12,)), working,
             {("p00", "k1"): open_item("p00", "k1", 12)}, card, 2),
        ]
        for label, sprint_state, sessions, records, prompts, count in table:
            with self.subTest(label):
                shown = self.shown(sprint_state, sessions, records, prompts)
                self.assertEqual(entry(shown)["ball"], "owner")
                self.assertEqual(shown["statement"]["inbox_items"], count)
                self.assertEqual(shown["statement"]["headline"],
                                 "1 thing needs you" if count == 1 else f"{count} things need you")


class PermissionPromptViewTest(unittest.TestCase):
    """Only an open permission card counts; a manager's waiting state raises nothing (#1424)."""

    base = with_manager(reported(started(A), R))
    now = R + 2 * MIN

    def shown(self, session_state="working", prompts=(), sprint_state=None, **extra):
        sessions = [] if session_state is None else [session("s1", session_state, name=NAME)]
        return derive_view([state("p00", 1)], None, sprints={A: sprint_state or self.base},
                           sessions=sessions, now_ms=self.now, managers=True,
                           prompt_items=prompts, **extra)

    def test_a_manager_wait_with_no_open_card_raises_nothing(self):
        for waiting in ("waiting_permission", "waiting_answer"):
            with self.subTest(waiting):
                shown = self.shown(waiting)
                self.assertNotEqual(entry(shown)["ball"], "owner")
                self.assertEqual(shown["statement"]["inbox_items"], 0)
                self.assertEqual(shown["statement"]["headline"], "Nothing needs you")
                self.assertNotIn("permission", entry(shown)["now_text"])
                self.assertNotIn("answer", entry(shown)["now_text"])

    def test_an_open_card_is_one_counted_item_naming_its_command(self):
        card = permission_item()
        for session_state in ("working", "waiting_permission"):
            with self.subTest(session_state):
                shown = self.shown(session_state, [card])
                self.assertEqual(shown["inbox"]["open"], [card])
                self.assertEqual(shown["inbox"]["open"][0]["command"], "git worktree add ../w")
                self.assertEqual(shown["inbox"]["open"][0]["words"], "Create the delivery's worktree")
                self.assertEqual(shown["statement"]["inbox_items"], 1)
                self.assertEqual(shown["statement"]["headline"], "1 thing needs you")
                self.assertEqual(shown["statement"]["sentence"], view.PERMISSION_SENTENCE)
                self.assertEqual(entry(shown)["ball"], "owner")
                self.assertEqual(entry(shown)["now_text"], sprints_module.NOW_PERMISSION_TEXT)

    def test_an_open_card_is_not_filtered_by_registered_projects(self):
        card = {**permission_item(), "project_id": "p99"}
        shown = self.shown("working", [card])
        self.assertEqual(shown["inbox"]["open"], [card])
        self.assertEqual(shown["statement"]["inbox_items"], 1)

    def test_no_shown_text_sends_the_owner_to_a_terminal(self):
        held = moving(sessions=(SessionMovement("s1", A, None, None, None, R + MIN, True),))
        stopping = dataclasses.replace(self.base, stop_at=iso(R + MIN))
        table = [
            ("an open card", self.shown("working", [permission_item()])),
            ("a waiting answer", self.shown("waiting_answer")),
            ("a waiting permission", self.shown("waiting_permission")),
            ("a deaf manager", self.shown("idle", movement=held)),
            ("a stopping sprint with an open card",
             self.shown("working", [permission_item()], sprint_state=stopping)),
        ]
        for label, shown in table:
            with self.subTest(label):
                self.assertNotIn("terminal", json.dumps(shown["statement"]).lower())
                sprint_entry = entry(shown)
                self.assertNotIn("terminal", (sprint_entry["now_text"] or "").lower())
                self.assertNotIn("terminal", (sprint_entry["ball_text"] or "").lower())
                for held_session in sprint_entry["sessions"]:
                    self.assertNotIn("terminal", held_session["state_text"].lower())
        for module in (view, sprints_module):
            for name, value in vars(module).items():
                if name.startswith("__") or not isinstance(value, str):
                    continue
                with self.subTest(module=module.__name__, name=name):
                    self.assertNotIn("terminal", value.lower())
        for name, value in sessions_module.STATE_TEXT.items():
            with self.subTest(state=name):
                self.assertNotIn("terminal", value.lower())

    def test_a_deaf_manager_still_counts_with_its_own_sentence(self):
        held = moving(sessions=(SessionMovement("s1", A, None, None, None, R + MIN, True),))
        shown = self.shown("idle", movement=held)
        self.assertEqual(shown["statement"]["inbox_items"], 1)
        self.assertEqual(shown["statement"]["sentence"], view.DEAF_SENTENCE)
        B = "b" * 16
        other = permission_item(sid=B, prompt=8)
        both = derive_view(
            [state("p00", 1)], None,
            sprints={A: self.base, B: reported(with_manager(started(B)), R)},
            sessions=[session("s1", "idle", name=NAME)], now_ms=self.now, managers=True,
            movement=held, prompt_items=[other])
        self.assertEqual(both["statement"]["inbox_items"], 2)
        self.assertEqual(both["statement"]["sentence"], view.PERMISSION_SENTENCE)

    def test_an_open_card_outranks_tracker_items_in_the_sentence(self):
        card = [permission_item()]
        decision = {**item("p00", "kd"), "issue": 99, "reason": "decision", "questions": [
            {"question": "Which?", "options": ["a", "b"], "chosen": None, "recommended": None}]}
        question = {**item("p00", "kq"), "issue": 99}

        def records(*items):
            return {("p00", i["key"]): InboxRecord(i, "t1", "u1") for i in items}

        table = [
            ("a card alone", card, None, self.base, 1, view.PERMISSION_SENTENCE),
            ("a card beside an unrelated decision", card, records(decision), self.base, 2,
             view.PERMISSION_SENTENCE),
            ("a card beside an unrelated question", card, records(question), self.base, 2,
             view.PERMISSION_SENTENCE),
            ("the decision alone", (), records(decision), self.base, 1, CHOOSE_SENTENCE),
            ("the question alone", (), records(question), self.base, 1, NEEDS_SENTENCE),
            ("a card beside an asked sprint question", card, None, asked(self.base), 3,
             view.QUESTION_SENTENCE),
        ]
        for label, prompts, recs, sprint_state, count, sentence in table:
            with self.subTest(label):
                shown = derive_view([state("p00", 1)], recs, sprints={A: sprint_state},
                                    sessions=[session("s1", "working", name=NAME)],
                                    now_ms=self.now, managers=True, prompt_items=prompts)
                self.assertEqual(shown["statement"]["inbox_items"], count)
                self.assertEqual(shown["statement"]["sentence"], sentence)

    def test_a_manager_that_cannot_hear_the_console_is_counted_with_its_own_sentence(self):
        base = reported(with_manager(started(A)), R)
        held = moving(sessions=(SessionMovement("s1", A, None, None, None, R + MIN, True),))
        table = [
            ("an idle manager", base, [session("s1", "idle", name=NAME)]),
            ("a working manager", base, [session("s1", "working", name=NAME)]),
            ("no registry session", dataclasses.replace(base, manager_session="s1"), []),
            ("a question wait", base, [session("s1", "waiting_answer", name=NAME)]),
            ("a permission wait", base, [session("s1", "waiting_permission", name=NAME)]),
        ]
        for label, sprint_state, sessions in table:
            with self.subTest(label):
                shown = derive_view([state("p00", 1)], None, sprints={A: sprint_state},
                                    sessions=sessions, now_ms=R + 2 * MIN, managers=True,
                                    movement=held)
                self.assertEqual(entry(shown)["ball"], "owner")
                self.assertEqual(shown["statement"]["inbox_items"], 1)
                self.assertEqual(shown["statement"]["headline"], "1 thing needs you")
                self.assertEqual(shown["statement"]["sentence"], view.DEAF_SENTENCE)

    def test_a_deaf_manager_whose_sprint_is_stopping_reads_the_recovery_sentence(self):
        held = moving(sessions=(SessionMovement("s1", A, None, None, None, R + MIN, True),))
        stopping = dataclasses.replace(reported(with_manager(started(A)), R), stop_at=iso(R + MIN))
        for session_state in ("idle", "waiting_permission"):
            with self.subTest(session_state):
                shown = derive_view([state("p00", 1)], None, sprints={A: stopping},
                                    sessions=[session("s1", session_state, name=NAME)],
                                    now_ms=R + 2 * MIN, managers=True, movement=held)
                self.assertEqual(shown["statement"]["inbox_items"], 1)
                self.assertEqual(shown["statement"]["sentence"], view.DEAF_SENTENCE)

    def test_a_stopping_manager_waiting_raises_nothing(self):
        stopping = dataclasses.replace(self.base, stop_at=iso(R + MIN))
        for waiting in ("waiting_answer", "waiting_permission"):
            with self.subTest(waiting):
                shown = self.shown(waiting, sprint_state=stopping)
                self.assertEqual(entry(shown)["now_text"], view.NOW_STOPPING_TEXT)
                self.assertEqual(shown["statement"]["inbox_items"], 0)
                self.assertEqual(shown["statement"]["headline"], "Nothing needs you")

    def test_a_deaf_manager_beside_an_open_card_reads_both(self):
        B = "b" * 16
        deaf = reported(with_manager(started(A)), R)
        asking = reported(dataclasses.replace(
            with_manager(started(B)), manager=Manager("started", T0, "work", session_name("p00", B))), R)
        shown = derive_view(
            [state("p00", 1)], None, sprints={A: deaf, B: asking},
            sessions=[session("s1", "idle", name=NAME),
                      session("s2", "working", name=session_name("p00", B))],
            now_ms=R + 2 * MIN, managers=True, prompt_items=[permission_item(sid=B, prompt=8)],
            movement=moving(sessions=(SessionMovement("s1", A, None, None, None, R + MIN, True),)))
        self.assertEqual(shown["statement"]["inbox_items"], 2)
        self.assertEqual(shown["statement"]["sentence"], view.PERMISSION_SENTENCE)

    def test_a_sprint_the_manager_holds_is_not_counted(self):
        shown = self.shown("working")
        self.assertEqual(entry(shown)["ball"], "manager")
        self.assertEqual(shown["statement"]["inbox_items"], 0)
        self.assertEqual(shown["statement"]["headline"], "Nothing needs you")


class SprintReportViewTest(unittest.TestCase):
    def test_a_reports_pictures_reach_the_sprint_entry_cut(self):
        it = reported(started(A), R)
        self.assertEqual(entry(line(it, R + MIN))["pictures"], [])
        it = dataclasses.replace(it, report=dataclasses.replace(
            it.report, pictures=(QuestionPicture("c" * 64, "m" * 150),)))
        self.assertEqual(entry(line(it, R + MIN))["pictures"],
                         [{"id": "c" * 64, "line": cut("m" * 150, 140), "pair": None}])
        self.assertEqual(entry(line(started(A), R + MIN))["pictures"], [])
        ended = closed(it, R + MIN, ((12, "landed"),))
        self.assertEqual(entry(line(ended, R + 2 * MIN))["pictures"], [])

    def test_the_line_counts_landed_in_delivery_queued_and_held(self):
        it = reported(started(A), R, issues=SEVEN)
        shown = entry(line(it, T0_MS + 5 * MIN))
        self.assertEqual(shown["progress"],
                         {"landed": 3, "in_delivery": 2, "queued": 2, "held": 0, "total": 7})
        self.assertEqual(shown["progress_text"], "3 done, 2 in work, 2 waiting to start")
        self.assertEqual(shown["state_text"], "on track")
        self.assertEqual(shown["status"], "two slices are building")
        self.assertEqual(shown["status_at"], iso(R))
        self.assertEqual((shown["next"], shown["milestone"], shown["tracker_url"]),
                         ("start the resume slice", "Importer resumes",
                          "https://github.com/owner/p00/milestone/3"))
        held = reported(started(A), R, issues=SEVEN[:6] + ((7, "held"),))
        shown = entry(line(held, T0_MS + 5 * MIN))
        self.assertEqual(shown["progress_text"],
                         "3 done, 2 in work, 1 waiting to start, 1 waiting for a check")
        self.assertEqual(shown["progress"]["held"], 1)

    def test_state_drafting_the_brief(self):
        it = reported(dataclasses.replace(
            started(A), brief=Brief(2, PARTS, T0, NONE, None, None)), R)
        shown = entry(line(it, R + MIN))
        self.assertEqual((shown["state"], shown["state_text"]), ("drafting", "drafting the brief"))

    def test_state_starting(self):
        shown = entry(line(started(A), T0_MS + 5 * MIN))
        self.assertEqual((shown["state"], shown["state_text"]), ("starting", "starting"))
        self.assertIsNone(shown["progress"])
        self.assertEqual(shown["issues"], [])
        self.assertEqual(shown["waiting"], 0)

    def test_state_on_track(self):
        shown = entry(line(reported(started(A), R), R + 4 * MIN))
        self.assertEqual((shown["state"], shown["state_text"]), ("on_track", "on track"))

    def test_state_waiting_on_you_counts_open_items_of_the_sprint(self):
        it = reported(started(A), R, issues=((12, "building"), (13, "queued")), inbox=(40,))
        records = {("p00", "k1"): open_item("p00", "k1", 12),
                   ("p00", "k2"): open_item("p00", "k2", 40),
                   ("p00", "k3"): open_item("p00", "k3", 13, answered=True),
                   ("p00", "k4"): open_item("p00", "k4", 99),
                   ("p01", "k5"): open_item("p01", "k5", 12)}
        shown = entry(line(it, R + 4 * MIN, records, [state("p00", 1), state("p01", 2)]))
        self.assertEqual((shown["state"], shown["state_text"]), ("waiting", "waiting on you (2)"))
        self.assertEqual(shown["waiting"], 2)

    def test_an_approval_the_console_holds_points_the_line_at_the_page_never_the_tracker(self):
        for look_state, words in (("failed", "waiting for you to press Retry on your approval"),
                                  ("posting", "recording your approval")):
            with self.subTest(look_state=look_state):
                base = reported(started(A), R, issues=((12, "building"),))
                held = dataclasses.replace(
                    Question(41, 0, T0, False, "Approve the card?", "the card", ("Approve", "Change"),
                             "Approve"),
                    answer="Approve", chosen="Approve", answered_at=T0, look_state=look_state)
                shown = entry(line(dataclasses.replace(base, questions=(held,)), R + 4 * MIN))
                self.assertEqual((shown["ball"], shown["waiting"]), ("owner", 1))
                self.assertEqual(shown["now_text"], words)

    def test_a_held_check_that_blocks_no_open_issue_leaves_the_ball_with_the_manager(self):
        for blocking in ([], [99], [13], [30]):
            with self.subTest(blocking=blocking):
                records = {("p00", "k1"): check_item("p00", "k1", 30, blocking)}
                shown = entry(line(HELD_SPRINT, R + 4 * MIN, records))
                self.assertEqual((shown["ball"], shown["ball_text"]),
                                 ("manager", "manager working"))
                self.assertEqual(shown["now_text"], "Working on 1 issue.")
                self.assertEqual(shown["waiting"], 0)
                self.assertEqual(shown["state"], "on_track")

    def test_a_held_check_is_a_check_line_and_still_an_inbox_item(self):
        records = {("p00", "k1"): check_item("p00", "k1", 30, [])}
        view = line(HELD_SPRINT, R + 4 * MIN, records)
        self.assertEqual(entry(view)["checks"], [{
            "project_id": "p00", "key": "k1", "issue": 30, "question": CHECK_Q,
            "text": "Your check: " + CHECK_Q}])
        self.assertEqual(view["statement"]["inbox_items"], 1)
        self.assertEqual(view["statement"]["headline"], "1 thing needs you")
        self.assertEqual([e["key"] for e in view["inbox"]["open"]], ["k1"])

    def test_a_check_whose_issue_blocks_an_open_issue_of_the_sprint_keeps_the_ball_with_the_owner(
            self):
        queued = reported(started(A), R, issues=((12, "building"), (14, "queued"), (30, "held")))
        for sprint_state, blocking in ((HELD_SPRINT, [12]), (queued, [14])):
            with self.subTest(blocking=blocking):
                records = {("p00", "k1"): check_item("p00", "k1", 30, blocking)}
                shown = entry(line(sprint_state, R + 4 * MIN, records))
                self.assertEqual(shown["ball"], "owner")
                self.assertEqual(shown["now_text"], "waiting for your decision on the tracker")
                self.assertEqual(shown["waiting"], 1)
                self.assertEqual(shown["state"], "waiting")
                self.assertEqual(shown["checks"], [])

    def test_a_check_on_an_open_issue_of_the_sprint_keeps_the_ball_with_the_owner(self):
        for stage in ("building", "verifying", "queued"):
            with self.subTest(stage=stage):
                sprint_state = reported(started(A), R, issues=((12, stage),))
                records = {("p00", "k1"): check_item("p00", "k1", 12, [])}
                shown = entry(line(sprint_state, R + 4 * MIN, records))
                self.assertEqual(shown["ball"], "owner")
                self.assertEqual(shown["now_text"], "waiting for your decision on the tracker")
                self.assertEqual(shown["waiting"], 1)
                self.assertEqual(shown["state"], "waiting")
                self.assertEqual(shown["checks"], [])

    def test_a_check_with_no_blocking_list_counts_as_waiting(self):
        for blocking in (MISSING, "12"):
            with self.subTest(blocking=blocking):
                records = {("p00", "k1"): check_item("p00", "k1", 30, blocking)}
                shown = entry(line(HELD_SPRINT, R + 4 * MIN, records))
                self.assertEqual(shown["ball"], "owner")
                self.assertEqual(shown["waiting"], 1)
                self.assertEqual(shown["checks"], [])

    def test_a_held_review_card_blocking_nothing_is_a_check_line(self):
        review = InboxRecord({
            **check_item("p00", "k1", 30, []).item, "reason": inbox.REVIEW_REASON,
            "kind": inbox.REVIEW_KIND, "answers": ["passed", "note"]}, "t1", "u1")
        shown = entry(line(HELD_SPRINT, R + 4 * MIN, {("p00", "k1"): review}))
        self.assertNotEqual(shown["ball"], "owner")
        self.assertEqual(shown["waiting"], 0)
        self.assertEqual([c["key"] for c in shown["checks"]], ["k1"])

    def test_a_held_review_card_blocking_an_open_issue_keeps_the_ball_with_the_owner(self):
        review = InboxRecord({
            **check_item("p00", "k1", 30, [12]).item, "reason": inbox.REVIEW_REASON,
            "kind": inbox.REVIEW_KIND, "answers": ["passed", "note"]}, "t1", "u1")
        shown = entry(line(HELD_SPRINT, R + 4 * MIN, {("p00", "k1"): review}))
        self.assertEqual(shown["ball"], "owner")
        self.assertEqual(shown["waiting"], 1)
        self.assertEqual(shown["checks"], [])

    def test_only_an_owner_check_becomes_a_check_line(self):
        record = InboxRecord(
            {**item("p00", "k1"), "issue": 30, "reason": "decision", "blocking": []}, "t1", "u1")
        shown = entry(line(HELD_SPRINT, R + 4 * MIN, {("p00", "k1"): record}))
        self.assertEqual(shown["ball"], "owner")
        self.assertEqual(shown["waiting"], 1)
        self.assertEqual(shown["checks"], [])

    def test_checks_are_ordered_by_waiting_since_then_key(self):
        later = dataclasses.replace(check_item("p00", "k1", 30, []), waiting_since="t2")
        earlier = dataclasses.replace(check_item("p00", "k2", 30, []), waiting_since="t1")
        shown = entry(line(HELD_SPRINT, R + 4 * MIN,
                           {("p00", "k1"): later, ("p00", "k2"): earlier}))
        self.assertEqual([c["key"] for c in shown["checks"]], ["k2", "k1"])

    def test_state_quiet_may_be_stuck(self):
        view = line(reported(started(A), R), R + 16 * MIN)
        shown = entry(view)
        self.assertEqual((shown["state"], shown["state_text"]),
                         ("quiet", "quiet for 16 min \u2014 may be stuck"))
        self.assertNotIn("stalled", json.dumps(view))

    def test_state_closing(self):
        shown = entry(line(reported(started(A), R, phase="closing"), R + MIN))
        self.assertEqual((shown["state"], shown["state_text"]), ("closing", "closing"))

    def test_state_done(self):
        it = reported(started(A), R, phase="done")
        records = {("p00", "k1"): open_item("p00", "k1", 4)}
        shown = entry(line(it, R + 60 * MIN, records))
        self.assertEqual((shown["state"], shown["state_text"]), ("done", "done"))

    def test_state_precedence(self):
        records = {("p00", "k1"): open_item("p00", "k1", 4)}
        shown = entry(line(reported(started(A), R), R + 30 * MIN, records))
        self.assertEqual(shown["state"], "waiting")
        shown = entry(line(reported(started(A), R, phase="closing"), R + 20 * MIN))
        self.assertEqual(shown["state"], "quiet")
        shown = entry(line(started(A), T0_MS + 15 * MIN))
        self.assertEqual((shown["state"], shown["state_text"]),
                         ("quiet", "quiet for 15 min \u2014 may be stuck"))

    def test_quiet_after_fifteen_minutes_with_a_controlled_clock(self):
        it = reported(started(A), R, issues=SEVEN)
        for now_ms, expected in ((R + 15 * MIN - 1, ("on_track", "on track")),
                                 (R + 15 * MIN, ("quiet", "quiet for 15 min \u2014 may be stuck")),
                                 (R + 16 * MIN, ("quiet", "quiet for 16 min \u2014 may be stuck")),
                                 (None, ("on_track", "on track"))):
            with self.subTest(now_ms=now_ms):
                shown = entry(line(it, now_ms))
                self.assertEqual((shown["state"], shown["state_text"]), expected)
        moved = observed(it, R + 10 * MIN, IssueStage(4, "final review"))
        shown = entry(line(moved, R + 16 * MIN))
        self.assertEqual((shown["state"], shown["state_text"]), ("on_track", "on track"))

    def test_between_reports_an_issue_follows_its_delivery_run(self):
        it = reported(started(A), R, issues=((12, "queued"), (13, "building"), (14, "landing")))
        it = observed(it, R + 3 * MIN, IssueStage(12, "building", 2, 4), IssueStage(14, "done"))
        live = {("s1", "wf_z"): DeliveryState("s1", "wf_z", R + 5 * MIN,
                                              (IssueStage(13, "verifying"),))}
        shown = entry(line(it, R + 6 * MIN, sessions=[session("s1", "working")],
                           deliveries=live))
        self.assertEqual(shown["issues"], [
            {"issue": 12, "stage": "building", "stage_text": "building task 2 of 4"},
            {"issue": 13, "stage": "building", "stage_text": "building"},
            {"issue": 14, "stage": "closed out", "stage_text": "closed out"}])
        self.assertEqual(shown["progress"],
                         {"landed": 0, "in_delivery": 3, "queued": 0, "held": 0, "total": 3})

    def test_a_reported_outcome_is_kept_against_a_run(self):
        it = reported(started(A), R, issues=((14, "held"), (15, "landed"), (16, "building")))
        it = observed(it, R + 3 * MIN, IssueStage(14, "done"), IssueStage(15, "done"),
                      IssueStage(16, "final review"))
        shown = entry(line(it, R + 4 * MIN))
        self.assertEqual(shown["issues"], [
            {"issue": 14, "stage": "held", "stage_text": "held"},
            {"issue": 15, "stage": "landed", "stage_text": "landed"},
            {"issue": 16, "stage": "final review", "stage_text": "final review"}])
        self.assertEqual(shown["progress"],
                         {"landed": 1, "in_delivery": 1, "queued": 0, "held": 1, "total": 3})



def asked(sprint_state):
    return dataclasses.replace(sprint_state, questions=(
        Question(41, 0, T0, False, "Which store keeps the checkpoints?", "the resume slice",
                 ("sqlite", "files"), "files"),
        Question(41, 1, T0, False, "May the reader change?", "the reader slice",
                 ("yes", "no"), "no")))


def answer_question(sprint_state, index):
    questions = tuple(
        dataclasses.replace(q, answer="sqlite", chosen="sqlite", differs=True, answered_at=T0)
        if q.index == index else q for q in sprint_state.questions)
    return dataclasses.replace(sprint_state, questions=questions)


def question_entry(index, text, options, recommended, blocks, sid=A):
    return {"type": "inbox_item", "reason": "question", "key": f"question/{sid}/41/{index}",
            "project_id": "p00", "sprint_id": sid, "title": "Ship the importer",
            "round": 41, "index": index, "blocker": False, "blocks": blocks,
            "headline": text, "context": None, "more_questions": 0,
            "questions": [{"question": text, "options": options, "chosen": None,
                           "recommended": recommended,
                           "recommended_index": options.index(recommended),
                           "needs_words_index": []}],
            "pictures": [], "look": None,
            "items": [], "answers": [], "answered": False, "waiting_since": T0,
            "started_by": None}


FIRST = question_entry(0, "Which store keeps the checkpoints?", ["sqlite", "files"], "files",
                       "the resume slice")
SECOND = question_entry(1, "May the reader change?", ["yes", "no"], "no", "the reader slice")


class SprintUnreadLineTest(unittest.TestCase):
    """The sprint line says a delivered, unread message waits to be read (#1379)."""

    base = reported(started(A), R)
    baseline = entry(line(base, R + 4 * MIN))["now_text"]

    @staticmethod
    def msg(**fields):
        return Message(9, "text", T0, None, "hi", **fields)

    def shown(self, sprint_state, records=None):
        return entry(line(sprint_state, R + 4 * MIN, records))["now_text"]

    def test_a_delivered_unread_message_reads_waiting_for_the_manager_to_read_it(self):
        sprint_state = dataclasses.replace(self.base, messages=(self.msg(delivered_at=T0),))
        shown = self.shown(sprint_state)
        self.assertEqual(shown, "waiting for the manager to read your message")
        self.assertNotEqual(self.baseline, shown)

    def test_a_read_or_undelivered_message_keeps_the_stage_phrase(self):
        for label, message in (("read", self.msg(delivered_at=T0, read_at=T0)),
                               ("undelivered", self.msg())):
            with self.subTest(label):
                sprint_state = dataclasses.replace(self.base, messages=(message,))
                self.assertEqual(self.shown(sprint_state), self.baseline)

    def test_a_waiting_item_still_comes_before_the_unread_line(self):
        waiting = reported(started(A), R, issues=((12, "building"),), inbox=(40,))
        records = {("p00", "k2"): open_item("p00", "k2", 40)}
        sprint_state = dataclasses.replace(waiting, messages=(self.msg(delivered_at=T0),))
        self.assertEqual(self.shown(sprint_state, records), "waiting for your decision on the tracker")
        self.assertEqual(self.shown(waiting, records), "waiting for your decision on the tracker")


class QuestionViewTest(unittest.TestCase):
    def test_each_open_question_is_one_inbox_item_with_its_recommendation(self):
        shown = derive_view([state("p00", 1)], sprints={A: asked(started(A))})
        self.assertEqual(shown["inbox"]["open"], [FIRST, SECOND])
        self.assertEqual(shown["statement"]["inbox_items"], 2)
        self.assertEqual(shown["statement"]["headline"], "2 things need you")
        self.assertEqual(shown["statement"]["sentence"], QUESTION_SENTENCE)
        self.assertEqual(QUESTION_SENTENCE,
                         "Choose an option with its number and press Enter, or answer in your own words.")

    def test_a_question_names_the_options_that_need_words_by_index(self):
        state_ = asked(started(A))
        first, *rest = state_.questions
        state_ = dataclasses.replace(
            state_, questions=(dataclasses.replace(first, needs_words=("files",)), *rest))
        shown = derive_view([state("p00", 1)], sprints={A: state_})
        self.assertEqual(shown["inbox"]["open"][0]["questions"][0]["needs_words_index"], [1])

    def test_an_owner_only_question_says_so_and_others_say_nothing(self):
        state_ = asked(started(A))
        first, *rest = state_.questions
        state_ = dataclasses.replace(
            state_, questions=(dataclasses.replace(first, owner_only=True), *rest))
        entries = derive_view([state("p00", 1)], sprints={A: state_})["inbox"]["open"]
        self.assertIs(entries[0]["owner_only"], True)
        self.assertNotIn("owner_only", entries[1])

    def test_a_consequential_question_says_so_and_others_say_nothing(self):
        state_ = asked(started(A))
        first, second = state_.questions
        state_ = dataclasses.replace(state_, questions=(
            dataclasses.replace(first, consequential=True),
            dataclasses.replace(second, owner_only=True)))
        entries = derive_view([state("p00", 1)], sprints={A: state_})["inbox"]["open"]
        self.assertIs(entries[0]["consequential"], True)
        self.assertIs(entries[1]["owner_only"], True)
        self.assertNotIn("consequential", entries[1])

    def test_a_look_or_a_before_and_after_pair_makes_a_question_consequential(self):
        before = QuestionPicture("a" * 64, "the page before", "before")
        after = QuestionPicture("b" * 64, "the page after", "after")
        for name, change, consequential in (
                ("look", {"look": QuestionLook(12, 34, "a" * 40, "files")}, True),
                ("pair", {"pictures": (before, after)}, True),
                ("one picture", {"pictures": (before,)}, False)):
            with self.subTest(name):
                state_ = asked(started(A))
                first, *rest = state_.questions
                state_ = dataclasses.replace(
                    state_, questions=(dataclasses.replace(first, **change), *rest))
                entries = derive_view([state("p00", 1)], sprints={A: state_})["inbox"]["open"]
                if consequential:
                    self.assertIs(entries[0]["consequential"], True)
                else:
                    self.assertNotIn("consequential", entries[0])

    def test_a_consequential_card_hides_its_recommendation_from_a_page_that_preselects_it(self):
        # A page from before the mark preselects `recommended_index`, or `recommended` by text,
        # so a consequential card names the badge only in `badge_index` (#1265).
        before = QuestionPicture("a" * 64, "the page before", "before")
        after = QuestionPicture("b" * 64, "the page after", "after")
        for name, change in (("marked", {"consequential": True}),
                             ("look", {"look": QuestionLook(12, 34, "a" * 40, "files")}),
                             ("pair", {"pictures": (before, after)})):
            with self.subTest(name):
                state_ = asked(started(A))
                first, *rest = state_.questions
                state_ = dataclasses.replace(
                    state_, questions=(dataclasses.replace(first, **change), *rest))
                (found, *_) = derive_view([state("p00", 1)], sprints={A: state_})["inbox"]["open"]
                (shown,) = found["questions"]
                self.assertIsNone(shown["recommended"])
                self.assertIsNone(shown["recommended_index"])
                self.assertEqual(shown["badge_index"], first.options.index(first.recommended))

    def test_an_ordinary_card_keeps_its_recommendation_and_names_no_badge_field(self):
        state_ = asked(started(A))
        (found, *_) = derive_view([state("p00", 1)], sprints={A: state_})["inbox"]["open"]
        (shown,) = found["questions"]
        self.assertIsNotNone(shown["recommended"])
        self.assertIsNotNone(shown["recommended_index"])
        self.assertNotIn("badge_index", shown)

    def test_questions_follow_briefs_and_lead_tracker_items(self):
        b = "b" * 16
        records = {("p00", "k1"): InboxRecord(
            {**item("p00", "k1"), "reason": "decision", "questions": [
                {"question": "Which one?", "options": ["x"], "chosen": None}]}, "t1", "u1")}
        shown = derive_view([state("p00", 1)], records, sprints={
            A: asked(started(A)), b: briefed(sprint(b), at="t5")})
        self.assertEqual([i["reason"] for i in shown["inbox"]["open"]],
                         ["brief", "question", "question", "decision"])
        self.assertEqual(shown["statement"]["sentence"], BRIEF_SENTENCE)
        self.assertEqual(shown["statement"]["inbox_items"], 4)

    def test_the_sprint_waits_on_you_while_questions_are_open_and_not_after(self):
        it = reported(asked(started(A)), R)
        shown = line(it, R + 4 * MIN)
        self.assertEqual((entry(shown)["state"], entry(shown)["state_text"]),
                         ("waiting", "waiting on you (2)"))
        self.assertEqual(entry(shown)["waiting"], 2)
        shown = entry(line(answer_question(it, 0), R + 4 * MIN))
        self.assertEqual((shown["state"], shown["state_text"]), ("waiting", "waiting on you (1)"))
        shown = line(answer_question(answer_question(it, 0), 1), R + 4 * MIN)
        self.assertEqual((entry(shown)["state"], entry(shown)["state_text"]),
                         ("on_track", "on track"))
        self.assertEqual(entry(shown)["waiting"], 0)
        self.assertEqual(shown["inbox"]["open"], [])

    def test_a_done_sprint_with_open_questions_waits_on_you_until_they_are_answered(self):
        it = asked(reported(started(A), R, phase="done"))
        shown = line(it, R + 4 * MIN)
        self.assertEqual((entry(shown)["state"], entry(shown)["state_text"]),
                         ("waiting", "waiting on you (2)"))
        self.assertEqual(len(shown["inbox"]["open"]), 2)
        shown = entry(line(answer_question(answer_question(it, 0), 1), R + 4 * MIN))
        self.assertEqual((shown["state"], shown["state_text"]), ("done", "done"))

    def test_an_unregistered_projects_questions_are_not_shown(self):
        shown = derive_view([state("p00", 1)], sprints={
            A: dataclasses.replace(asked(started(A)), project_id="p09")})
        self.assertEqual(shown["inbox"]["open"], [])
        self.assertEqual(shown["statement"]["inbox_items"], 0)


DAY = 24 * 60 * MIN
SUMMARY = "Importer resumes after a crash\nwith detail"


def closed(state, at_ms, issues, summary=SUMMARY):
    return dataclasses.replace(state, closing=Closing(
        iso(at_ms), summary.strip(), first_line(summary), tuple(issues), "cut smaller slices"))


def stopped(state, stop_ms, stopped_ms=None):
    return dataclasses.replace(
        state, stop_at=iso(stop_ms),
        stopped_at=None if stopped_ms is None else iso(stopped_ms))


working_session = session("s1", "working", name=NAME)
idle_session = session("s1", "idle", name=NAME)


def failed_at(s, at_ms):
    return dataclasses.replace(s, manager=Manager("failed", iso(at_ms), "work", NAME))


class SprintMovementViewTest(unittest.TestCase):
    """One movement reading (#1109) behind the state, the ball and the now-sentence prefix."""

    base = reported(with_manager(started(A)), R)

    def test_a_working_manager_session_keeps_the_sprint_off_quiet_and_nobody(self):
        now = R + 20 * MIN
        shown = entry(line(self.base, now, sessions=[working_session]))
        self.assertEqual((shown["state"], shown["state_text"]), ("on_track", "on track"))
        self.assertEqual((shown["ball"], shown["ball_text"]), ("manager", "manager working"))
        self.assertEqual(shown["now_text"], "Working on 2 issues.")

    def test_a_folded_run_on_an_unreported_issue_keeps_the_sprint_moving(self):
        rows = [
            stated_row(1, "p00", A, "make the importer resumable"),
            sent_row(2, A, 1, PARTS_ROW), approved_row(3, A, 1),
            reported_row(4, A, REPORT_ROW),
            Event(5, at_row(5), "session.seen", "p00", {
                "session_id": "s1", "cwd": "/srv/p00", "repo": "/srv/p00", "state": "idle",
                "name": NAME}),
            seen_row(6, "wf_m", ms_row(4) + 18 * MIN, ((99, "planning"),), project="p00",
                     session_id="s1")]
        now = ms_row(4) + 20 * MIN
        for label, extra in (("run only", []), ("failed after the run", [Event(
                7, iso(ms_row(4) + 19 * MIN), event_log.MANAGER_FAILED, "p00",
                {"sprint_id": A, "reason": "launch failed"})])):
            with self.subTest(label):
                folded = sprint_states(rows + extra)[A]
                shown = entry(line(folded, now))
                self.assertEqual(shown["state"], "on_track")
                self.assertEqual(shown["ball"], "manager")
                self.assertEqual(shown["now_text"], "Working on 1 issue.")

    def test_the_state_the_ball_and_the_last_seen_prefix_agree_over_every_movement_signal(self):
        now, recent = R + 20 * MIN, R + 18 * MIN
        for flags in itertools.product((False, True), repeat=4):
            has_working_session, has_run, has_report, has_approval = flags
            s = self.base
            if has_approval:
                s = dataclasses.replace(
                    s, brief=dataclasses.replace(s.brief, decided_at=iso(recent)))
            if has_report:
                s = dataclasses.replace(s, report=dataclasses.replace(s.report, at=iso(recent)))
            if has_run:
                s = dataclasses.replace(s, moved_ms=recent)
            sessions = [working_session if has_working_session else idle_session]
            with self.subTest(working=has_working_session, run=has_run, report=has_report,
                              approval=has_approval):
                shown = entry(line(s, now, sessions=sessions))
                quiet = shown["state"] == "quiet"
                nobody = shown["ball"] == "nobody"
                prefixed = shown["now_text"].startswith("last seen ")
                self.assertEqual(quiet, nobody)
                self.assertEqual(nobody, prefixed)
                self.assertEqual(quiet, not any(flags))
                if not any(flags):
                    self.assertEqual(shown["state_text"], "quiet for 20 min \u2014 may be stuck")
        clockless = entry(line(self.base, None, sessions=[idle_session]))
        self.assertEqual((clockless["state"], clockless["ball"]), ("on_track", "manager"))

    def test_a_sprint_with_nothing_moving_for_twenty_minutes_reads_quiet_and_nothing_running(self):
        shown = entry(line(self.base, R + 20 * MIN, sessions=[idle_session]))
        self.assertEqual((shown["state"], shown["state_text"]),
                         ("quiet", "quiet for 20 min \u2014 may be stuck"))
        self.assertEqual((shown["ball"], shown["ball_text"]),
                         ("nobody", "nothing running, may be stuck"))
        self.assertEqual(shown["now_text"], "last seen working on 2 issues.")

    def test_a_failed_launch_drops_only_the_goals_freshness(self):
        now = R + 20 * MIN
        run_before = failed_at(dataclasses.replace(
            reported(started(A), R), moved_ms=R + 18 * MIN), R + 19 * MIN)
        run_after = failed_at(dataclasses.replace(
            reported(started(A), R), moved_ms=R + 19 * MIN), R + 18 * MIN)
        report_before = failed_at(reported(started(A), R + 10 * MIN), R + 11 * MIN)
        for label, s in (("a run before the failure", run_before),
                         ("a run after the failure", run_after),
                         ("a report before the failure", report_before)):
            with self.subTest(label):
                shown = entry(line(s, now))
                self.assertEqual((shown["state"], shown["ball"]), ("on_track", "manager"))
                self.assertEqual(shown["now_text"], "Working on 2 issues.")
        with self.subTest("nothing moved for twenty minutes"):
            shown = entry(line(failed_at(reported(started(A), R), R + 5 * MIN), now))
            self.assertEqual((shown["state"], shown["state_text"]),
                             ("quiet", "quiet for 20 min \u2014 may be stuck"))
            self.assertEqual(shown["ball"], "nobody")
            self.assertEqual(shown["now_text"], "last seen working on 2 issues.")
        with self.subTest("drafting, a failed start is the owner's card"):
            fresh = failed_at(sprint(A), T0_MS)
            at = T0_MS + MIN
            self.assertEqual(entry(line(fresh, at))["ball"], "owner")
            self.assertEqual(entry(line(fresh, at, sessions=[idle_session]))["ball"], "manager")
            self.assertEqual(entry(line(fresh, at, sessions=[working_session]))["ball"],
                             "manager")

    def test_a_freshly_stated_goal_moves_until_its_launch_fails_to_the_owner(self):
        fresh = with_manager(sprint(A))
        self.assertEqual(entry(line(fresh, T0_MS + MIN))["ball"], "manager")
        self.assertEqual(entry(line(fresh, T0_MS + 15 * MIN))["ball"], "nobody")
        failed = with_manager(sprint(A), state="failed")
        self.assertEqual(entry(line(failed, T0_MS + MIN))["ball"], "owner")


def moving(**kw):
    return {"p00": ProjectMovement(**kw)}


class SprintWaitViewTest(unittest.TestCase):
    """CI, a committing delivery and a release step move a sprint and name its wait (#1110)."""

    base = reported(with_manager(started(A)), R)
    now = R + 20 * MIN

    def shown(self, movement, now=None, sessions=None, sprint_state=None):
        return entry(line(sprint_state or self.base, now or self.now,
                          sessions=[idle_session] if sessions is None else sessions,
                          movement=movement))

    def test_a_check_in_progress_on_its_pull_request_reads_waiting_for_ci(self):
        now = self.now
        answer = json.loads(
            (Path(__file__).parent / "fixtures/console/forge-pulls.json").read_text())
        movement = {"p00": merged(None, pulls_from_answer(answer, "issue-<num>-<slug>"),
                                  now - MIN, LocalReading((), False))}
        shown = self.shown(movement)
        self.assertEqual(shown["state"], "on_track")
        self.assertEqual((shown["ball"], shown["ball_text"]), ("manager", "manager working"))
        self.assertEqual(shown["now_text"], "waiting for CI on its pull request")
        self.assertNotIn("may be stuck", json.dumps(shown))
        with self.subTest("not the sprint's pull request"):
            other = reported(with_manager(started(A)), R, issues=((1, "landed"), (2, "building")))
            shown = self.shown(movement, sprint_state=other)
            self.assertEqual(shown["state"], "quiet")
            self.assertEqual(shown["ball"], "nobody")
            self.assertTrue(shown["now_text"].startswith("last seen "))

    def test_a_commit_five_minutes_ago_reads_a_delivery_is_committing(self):
        now = self.now
        for label, movement in (
                ("on its pull request's branch",
                 moving(pulls=(PullMovement(40, frozenset({4}), None, now - 5 * MIN),),
                        read_ms=now - MIN)),
                ("on a delivery run's branch", moving(branches=((5, now - 5 * MIN),)))):
            with self.subTest(label):
                shown = self.shown(movement)
                self.assertEqual(shown["state"], "on_track")
                self.assertEqual(shown["ball"], "manager")
                self.assertEqual(shown["now_text"], "a delivery is committing")
        with self.subTest("a branch of another issue"):
            self.assertEqual(
                self.shown(moving(branches=((99, now - 5 * MIN),)))["state"], "quiet")

    def test_a_release_in_progress_reads_waiting_for_a_release_step(self):
        shown = self.shown(moving(release_ms=self.now - MIN))
        self.assertEqual(shown["state"], "on_track")
        self.assertEqual(shown["ball"], "manager")
        self.assertEqual(shown["now_text"], "waiting for a release step")

    def test_a_delivery_waiting_for_or_holding_the_land_lock_reads_waiting_its_turn_to_merge(self):
        now = self.now
        holding = PullRequest(40, frozenset({4}), False, None, True)
        queued = PullRequest(41, frozenset({99}), False, None, True)
        cases = (
            ("holding", {"p00": merged(None, (holding,), now - MIN, LocalReading((), False))}),
            ("waiting in a lock step",
             {"p00": merged(None, (queued,), now - MIN, LocalReading((), False), locking={4})}),
            ("a kept lock time", moving(locks=((4, now - MIN),))))
        for label, movement in cases:
            with self.subTest(label):
                shown = self.shown(movement)
                self.assertEqual((shown["state"], shown["ball"], shown["now_text"]),
                                 ("on_track", "manager", "waiting its turn to merge"))
                self.assertNotIn("stuck", json.dumps(shown))
                self.assertNotIn("stalled", json.dumps(shown))
        with self.subTest("not the sprint's issue"):
            shown = self.shown(moving(locks=((99, now - MIN),)))
            self.assertEqual(shown["state"], "quiet")
            self.assertTrue(shown["now_text"].startswith("last seen "))
        with self.subTest("an open question is read first"):
            text = self.shown(moving(locks=((4, now - MIN),)),
                              sprint_state=asked(self.base))["now_text"]
            self.assertTrue(text.startswith("waiting for your answer: "))

    def test_a_lock_wait_last_seen_over_fifteen_minutes_ago_reads_may_be_stuck(self):
        now = self.now
        for minutes in (16, 14):
            with self.subTest(minutes=minutes):
                seen = now - minutes * MIN
                first = merged(None, (PullRequest(40, frozenset({4}), False, None, True),),
                               seen, LocalReading((), False))
                gone = merged(first, (PullRequest(40, frozenset({4}), False, None, False),),
                              now - MIN, LocalReading((), False))
                shown = self.shown({"p00": gone})
                if minutes == 16:
                    self.assertEqual((shown["state"], shown["state_text"]),
                                     ("quiet", "quiet for 16 min \u2014 may be stuck"))
                    self.assertEqual(shown["ball"], "nobody")
                    self.assertEqual(shown["now_text"],
                                     "last seen working on 2 issues.")
                else:
                    self.assertEqual(shown["ball"], "manager")
                    self.assertEqual(shown["now_text"], "waiting its turn to merge")

    def test_a_shown_merge_refusal_is_read_before_any_wait_sentence(self):
        now = self.now
        refused = reported(with_manager(started(A)), R, status="merge refused: checks not green")
        for label, movement in (("CI", moving(pulls=(PullMovement(40, frozenset({4}), now - MIN, None),),
                                              read_ms=now - MIN)),
                                ("a commit", moving(branches=((5, now - 5 * MIN),))),
                                ("a release", moving(release_ms=now - MIN)),
                                ("a lock wait", moving(locks=((4, now - MIN),)))):
            with self.subTest(label):
                shown = self.shown(movement, sprint_state=refused)
                self.assertEqual(shown["state"], "on_track")
                self.assertEqual(shown["now_text"], "merge refused: checks not green")

    def test_every_signal_finished_and_twenty_quiet_minutes_reads_may_be_stuck(self):
        now = self.now
        for label, quiet_min, ball in (("twenty minutes", 20, "nobody"),
                                       ("fourteen minutes is still moving", 14, "manager")):
            with self.subTest(label):
                seen = now - quiet_min * MIN
                first = merged(None, (PullRequest(40, frozenset({4}), True, seen - 5 * MIN),),
                               seen, LocalReading(((5, seen),), True))
                gone = merged(first, (), now - MIN, LocalReading((), False))
                shown = self.shown({"p00": gone})
                self.assertEqual(shown["ball"], ball)
                if quiet_min == 20:
                    self.assertEqual((shown["state"], shown["state_text"]),
                                     ("quiet", "quiet for 20 min \u2014 may be stuck"))
                    self.assertEqual(shown["ball_text"], "nothing running, may be stuck")
                    self.assertEqual(shown["now_text"],
                                     "last seen working on 2 issues.")

    def test_the_wait_sentence_follows_ci_then_committing_then_release_then_the_land_lock(self):
        now = self.now
        pull = PullMovement(40, frozenset({4}), now - MIN, now - MIN)
        cases = (
            ("all four", moving(pulls=(pull,), read_ms=now - MIN, release_ms=now - MIN,
                                locks=((4, now - MIN),)),
             "waiting for CI on its pull request"),
            ("no CI", moving(pulls=(dataclasses.replace(pull, running_ms=None),),
                             read_ms=now - MIN, release_ms=now - MIN),
             "a delivery is committing"),
            ("only a release", moving(release_ms=now - MIN), "waiting for a release step"),
            ("a release and a lock wait", moving(release_ms=now - MIN, locks=((4, now - MIN),)),
             "waiting for a release step"),
            ("only a lock wait", moving(locks=((4, now - MIN),)), "waiting its turn to merge"))
        for label, movement, sentence in cases:
            with self.subTest(label):
                self.assertEqual(self.shown(movement)["now_text"], sentence)

    def test_the_wait_sentence_shows_only_while_nothing_else_moves(self):
        now = self.now
        movement = moving(release_ms=now - MIN)
        stage = "Working on 2 issues."
        with self.subTest("a working session"):
            self.assertEqual(self.shown(movement, sessions=[working_session])["now_text"], stage)
        with self.subTest("a fresh report"):
            fresh = reported(with_manager(started(A)), now - 2 * MIN)
            self.assertEqual(self.shown(movement, sprint_state=fresh)["now_text"], stage)
        with self.subTest("an open question"):
            text = self.shown(movement, sprint_state=asked(self.base))["now_text"]
            self.assertTrue(text.startswith("waiting for your answer: "))
        with self.subTest("no clock"):
            shown = entry(line(self.base, None, sessions=[idle_session], movement=movement))
            self.assertEqual(shown["now_text"], stage)

    def test_a_wait_signal_moves_a_sprint_whose_manager_failed(self):
        now = self.now
        movement = moving(pulls=(PullMovement(40, frozenset({4}), now - MIN, None),),
                          read_ms=now - MIN)
        shown = self.shown(movement, sessions=[], sprint_state=failed_at(self.base, R + 5 * MIN))
        self.assertEqual(shown["ball"], "manager")
        self.assertEqual(shown["now_text"], "waiting for CI on its pull request")

    def test_a_signal_that_disappears_keeps_moving_the_sprint_for_the_window(self):
        now = self.now
        seen = now - 10 * MIN
        cases = (
            ("a merged pull request after CI",
             (PullRequest(40, frozenset({4}), True, None),), LocalReading((), False),
             "waiting for CI on its pull request"),
            ("a merged pull request after a commit",
             (PullRequest(40, frozenset({4}), False, seen),), LocalReading((), False),
             "a delivery is committing"),
            ("a deleted branch", (), LocalReading(((5, seen),), False),
             "a delivery is committing"),
            ("a finished release", (), LocalReading((), True), "waiting for a release step"))
        for label, pulls, local, sentence in cases:
            with self.subTest(label):
                first = merged(None, pulls, seen, local)
                gone = {"p00": merged(first, (), now - MIN, LocalReading((), False))}
                shown = self.shown(gone)
                self.assertEqual((shown["state"], shown["ball"]), ("on_track", "manager"))
                self.assertEqual(shown["now_text"], sentence)
                later = self.shown(gone, now=now + 10 * MIN)
                self.assertEqual((later["state"], later["state_text"]),
                                 ("quiet", "quiet for 20 min \u2014 may be stuck"))
                self.assertEqual(later["ball"], "nobody")


class SprintRunLineViewTest(unittest.TestCase):
    """A sprint issue's run line reads its sprint's movement, not the journal alone (#1212)."""

    base = reported(with_manager(started(A)), R)
    now = R + 45 * MIN

    def run_of(self, issue=4, moved=R, sid="d1"):
        return run(sid, "wf_d", moved, IssueStage(issue, "landing"))

    def shown(self, movement, deliveries=None, sprint_state=None, now=None, sessions=None):
        return line(sprint_state or self.base, now or self.now,
                    sessions=sessions or [idle_session, session("d1", "idle")],
                    deliveries=deliveries or self.run_of(), movement=movement)

    def run_line(self, view, run_id="wf_d"):
        found = [d for s in session_entries(view) for d in s["deliveries"]]
        found += [d for e in view["entries"] for sp in e["sprints"]
                  for s in sp["sessions"] for d in s["deliveries"]]
        return next(d for d in found if d["run_id"] == run_id)

    def test_a_run_of_a_sprint_issue_whose_only_movement_is_a_fresh_wait_names_that_wait(self):
        now = self.now
        pull = PullMovement(40, frozenset({4}), now - MIN, now - MIN)
        cases = (
            ("a land lock wait", moving(locks=((4, now - MIN),)), "waiting its turn to merge"),
            ("CI on its pull request",
             moving(pulls=(PullMovement(40, frozenset({4}), now - MIN, None),), read_ms=now - MIN),
             "waiting for CI on its pull request"),
            ("a commit on its branch", moving(branches=((4, now - 5 * MIN),)),
             "a delivery is committing"),
            ("a release step", moving(release_ms=now - MIN), "waiting for a release step"),
            ("the order, CI first",
             moving(pulls=(pull,), read_ms=now - MIN, release_ms=now - MIN,
                    locks=((4, now - MIN),)), "waiting for CI on its pull request"),
            ("the order, release before the lock",
             moving(release_ms=now - MIN, locks=((4, now - MIN),)),
             "waiting for a release step"),
            ("committing before release and lock",
             moving(branches=((4, now - MIN),), release_ms=now - MIN, locks=((4, now - MIN),)),
             "a delivery is committing"))
        for label, movement, sentence in cases:
            with self.subTest(label):
                view = self.shown(movement)
                r = self.run_line(view)
                self.assertEqual((r["quiet"], r["moved_text"]), (False, sentence))
                self.assertEqual(r["wait_text"], sentence)
                self.assertEqual(r["summary"], "1 issue in delivery: 1 landing, " + sentence)
                for word in ("quiet", "stuck", "stalled"):
                    self.assertNotIn(word, r["moved_text"])
                    self.assertNotIn(word, r["summary"])
                    self.assertNotIn(word, r["wait_text"] or "")
                if label == "a land lock wait":
                    self.assertEqual(entry(view)["now_text"], "waiting its turn to merge")
        with self.subTest("a journal that moved itself"):
            r = self.run_line(self.shown(moving(locks=((4, now - MIN),)),
                                         deliveries=self.run_of(moved=now - 2 * MIN)))
            self.assertEqual((r["quiet"], r["moved_text"], r["wait_text"]),
                             (False, "moved 1 min ago", None))
            self.assertEqual(r["reading_at"],
                             datetime.fromtimestamp((now - MIN) / 1000, timezone.utc).isoformat())
        with self.subTest("session output moves it too"):
            r = self.run_line(self.shown(moving(
                locks=((4, now - MIN),),
                sessions=(SessionMovement("d1", A, now - 3 * MIN, None, None),))))
            self.assertEqual((r["quiet"], r["moved_text"], r["wait_text"]),
                             (False, "moved 1 min ago", None))

    def test_a_run_whose_own_session_wrote_output_reads_its_moved_time_not_quiet(self):
        now = self.now
        with self.subTest("output"):
            r = self.run_line(self.shown(moving(
                sessions=(SessionMovement("d1", A, now - 3 * MIN, None, None),))))
            self.assertEqual((r["quiet"], r["moved_text"], r["wait_text"]),
                             (False, "moved 3 min ago", None))
            self.assertEqual(r["reading_at"],
                             datetime.fromtimestamp((now - 3 * MIN) / 1000, timezone.utc).isoformat())
            journal = datetime.fromtimestamp(R / 1000, timezone.utc).isoformat()
            self.assertEqual((r["journal_at"], r["moved_at"]), (journal, journal))
        with self.subTest("a running check"):
            r = self.run_line(self.shown(moving(
                sessions=(SessionMovement("d1", A, None, now - 2 * MIN, None),))))
            self.assertEqual((r["quiet"], r["moved_text"], r["wait_text"]),
                             (False, "moved 2 min ago", None))
        with self.subTest("a run of the manager's session with no issue yet"):
            view = self.shown(
                moving(sessions=(SessionMovement("s1", A, now - 3 * MIN, None, None),)),
                deliveries=run("s1", "wf_m", R), sessions=[idle_session])
            r = self.run_line(view, "wf_m")
            self.assertEqual((r["quiet"], r["moved_text"], r["wait_text"]),
                             (False, "moved 3 min ago", None))

    def test_a_run_of_a_sprint_issue_with_nothing_moved_for_fifteen_minutes_still_reads_quiet(self):
        now = self.now
        with self.subTest("nothing moved"):
            r = self.run_line(self.shown(None))
            self.assertEqual((r["quiet"], r["moved_text"], r["wait_text"]),
                             (True, "quiet for 45 min", None))
            self.assertEqual(r["summary"], "1 issue in delivery: 1 landing, quiet for 45 min")
        with self.subTest("a lock wait last seen 16 minutes ago"):
            view = self.shown(moving(locks=((4, now - 16 * MIN),)))
            r = self.run_line(view)
            self.assertEqual((r["quiet"], r["moved_text"], r["wait_text"]),
                             (True, "quiet for 16 min", None))
            self.assertEqual(r["reading_at"],
                             datetime.fromtimestamp((now - 16 * MIN) / 1000, timezone.utc).isoformat())
            self.assertEqual(entry(view)["state_text"], "quiet for 16 min \u2014 may be stuck")
        with self.subTest("another issue's wait"):
            view = self.shown(moving(locks=((5, now - MIN),)))
            r = self.run_line(view)
            self.assertEqual((r["quiet"], r["moved_text"], r["wait_text"]),
                             (True, "quiet for 45 min", None))
            self.assertEqual(entry(view)["now_text"], "waiting its turn to merge")
        with self.subTest("another session's output"):
            r = self.run_line(self.shown(moving(
                sessions=(SessionMovement("s9", A, now - MIN, None, None),))))
            self.assertEqual((r["quiet"], r["moved_text"], r["wait_text"]),
                             (True, "quiet for 45 min", None))

    def test_a_run_outside_any_running_sprint_is_unchanged(self):
        now = self.now
        with self.subTest("not a sprint issue"):
            r = self.run_line(self.shown(moving(locks=((99, now - MIN),)),
                                         deliveries=self.run_of(issue=99)))
            self.assertEqual((r["quiet"], r["moved_text"], r["wait_text"]),
                             (True, "quiet for 45 min", None))
        with self.subTest("an ended sprint"):
            r = self.run_line(self.shown(
                moving(locks=((4, now - MIN),)),
                sprint_state=stopped(self.base, now - 30 * MIN, now - 29 * MIN)))
            self.assertEqual((r["quiet"], r["moved_text"], r["wait_text"]),
                             (True, "quiet for 45 min", None))
        with self.subTest("a project with no sprint"):
            view = derive_view([state("p00", 1)], sessions=[session("d1", "idle")],
                               deliveries=self.run_of(), now_ms=now,
                               movement=moving(locks=((4, now - MIN),)))
            r = self.run_line(view)
            self.assertEqual((r["quiet"], r["moved_text"], r["wait_text"]),
                             (True, "quiet for 45 min", None))
        with self.subTest("no clock"):
            view = line(self.base, None, sessions=[idle_session, session("d1", "idle")],
                        deliveries=self.run_of(), movement=moving(locks=((4, R),)))
            r = self.run_line(view)
            self.assertEqual((r["quiet"], r["moved_text"], r["wait_text"]),
                             (False, "moved just now", None))


class DeafManagerViewTest(unittest.TestCase):
    """A manager that holds the console's wake behind a prompt nobody at a terminal will answer (#1229)."""

    base = reported(with_manager(started(A)), R)
    now = R + 2 * MIN
    DEAF = "the manager cannot hear the console"

    def shown(self, held, session_state="idle", sid="s1", sessions=None):
        sessions = [session(sid, session_state, name=NAME)] if sessions is None else sessions
        return entry(line(self.base, self.now, sessions=sessions, movement=moving(
            sessions=(SessionMovement(sid, A, None, None, None, self.now - MIN, held),))))

    def test_a_held_undelivered_message_reads_the_manager_cannot_hear_the_console(self):
        for state in ("idle", "working", "waiting_permission"):
            with self.subTest(state):
                shown = self.shown(True, state)
                self.assertTrue(shown["now_text"].startswith(self.DEAF), shown["now_text"])
                self.assertIn("drop the sprint", shown["now_text"])
                self.assertNotIn("permission", shown["now_text"])
                self.assertEqual((shown["ball"], shown["ball_text"]), ("owner", "waiting on you"))

    def test_a_permission_wait_without_a_card_and_an_idle_manager_read_as_the_manager(self):
        shown = self.shown(False, "waiting_permission")
        self.assertEqual(shown["ball"], "manager")
        self.assertNotIn("permission", shown["now_text"])
        prompted = entry(derive_view(
            [state("p00", 1)], None, sprints={A: self.base}, now_ms=self.now, managers=True,
            sessions=[session("s1", "waiting_permission", name=NAME)],
            prompt_items=[permission_item()],
            movement=moving(sessions=(SessionMovement("s1", A, None, None, None, self.now - MIN, False),))))
        self.assertEqual((prompted["now_text"], prompted["ball"]),
                         (sprints_module.NOW_PERMISSION_TEXT, "owner"))
        shown = self.shown(False, "working")
        self.assertEqual((shown["now_text"], shown["ball"]),
                         ("Working on 2 issues.", "manager"))

    def test_a_question_wait_without_a_card_reads_as_the_manager(self):
        shown = self.shown(False, "waiting_answer")
        self.assertNotEqual(shown["ball"], "owner")
        self.assertNotIn("answer", shown["now_text"])

    def test_only_the_managers_held_message_counts(self):
        delivery = session("d1", "working", name="other-name")
        shown = entry(line(self.base, self.now, sessions=[working_session, delivery],
                           movement=moving(sessions=(
                               SessionMovement("d1", A, None, None, None, self.now - MIN, True),))))
        self.assertEqual(shown["now_text"], "Working on 2 issues.")
        other = entry(line(self.base, self.now, sessions=[working_session], movement=moving(
            sessions=(SessionMovement("s1", "b" * 16, None, None, None, self.now - MIN, True),))))
        self.assertEqual(other["now_text"], "Working on 2 issues.")

    def test_no_movement_reading_never_reads_deaf(self):
        shown = entry(line(self.base, self.now, sessions=[working_session], movement=None))
        self.assertEqual(shown["now_text"], "Working on 2 issues.")


class SessionSignalViewTest(unittest.TestCase):
    """Session output and a running check move a sprint without naming a wait (#1185)."""

    base = reported(with_manager(started(A)), R)
    now = R + 20 * MIN

    def shown(self, movement, sessions=None, sprint_state=None):
        return entry(line(sprint_state or self.base, self.now,
                          sessions=[idle_session] if sessions is None else sessions,
                          movement=movement))

    def test_session_output_moves_the_sprint_and_names_no_wait(self):
        now = self.now
        shown = self.shown(moving(sessions=(SessionMovement("s1", A, now - 5 * MIN, None, None),)))
        self.assertEqual((shown["state"], shown["ball"]), ("on_track", "manager"))
        self.assertEqual(shown["now_text"], "Working on 2 issues.")
        shown = self.shown(moving(sessions=(SessionMovement("s1", A, now - 5 * MIN, None, None),),
                                  release_ms=now - MIN))
        self.assertEqual(shown["now_text"], "Working on 2 issues.")

    def test_a_running_check_moves_a_sprint_whose_manager_failed(self):
        now = self.now
        shown = self.shown(moving(sessions=(SessionMovement("s1", A, None, now - MIN, None),)),
                           sessions=[], sprint_state=failed_at(self.base, R + 5 * MIN))
        self.assertEqual((shown["state"], shown["ball"]), ("on_track", "manager"))

    def test_another_sprints_session_moves_nothing(self):
        now = self.now
        shown = self.shown(moving(sessions=(SessionMovement("s1", "b" * 16, now - MIN, None, None),)))
        self.assertEqual((shown["state"], shown["ball"]), ("quiet", "nobody"))

    def test_a_nudged_idle_managers_reply_does_not_move_the_sprint(self):
        now = self.now
        self.assertEqual(view.NUDGE_REPLY_MS, idle.IDLE_AFTER_MS)

        def nudged_at(ago, **kw):
            return dataclasses.replace(self.base, idle_nudges=1, idle_nudged_at=iso(now - ago), **kw)

        reply = moving(sessions=(SessionMovement("s1", A, now - 3 * MIN, now - 3 * MIN, None),))
        shown = self.shown(reply, sprint_state=nudged_at(4 * MIN))
        self.assertEqual((shown["state"], shown["state_text"]),
                         ("quiet", "quiet for 20 min \u2014 may be stuck"))
        self.assertEqual(shown["ball"], "nobody")
        self.assertEqual(self.shown(reply)["state"], "on_track")
        self.assertEqual(self.shown(reply, sprint_state=nudged_at(9 * MIN))["state"], "on_track")
        delivery = moving(sessions=(SessionMovement("d1", A, now - 3 * MIN, None, None),))
        self.assertEqual(self.shown(delivery, sprint_state=nudged_at(4 * MIN))["state"], "on_track")
        known = moving(sessions=(SessionMovement("m2", A, now - 3 * MIN, None, None),))
        self.assertEqual(
            self.shown(known, sprint_state=nudged_at(4 * MIN, manager_session="m2"))["state"],
            "quiet")

    def test_the_sprint_entry_carries_its_movement_sessions_nudge_and_base_time(self):
        now = self.now

        def utc(ms):
            return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat()

        s = dataclasses.replace(self.base, manager_session="m2", idle_nudged_at=iso(now - 30 * MIN))
        shown = self.shown(moving(sessions=(
            SessionMovement("d1", A, None, None, None, now - MIN),
            SessionMovement("m2", A, None, None, None, now - MIN),
            SessionMovement("s1", A, None, None, None),
            SessionMovement("x1", "b" * 16, None, None, None, now - MIN))), sprint_state=s)
        self.assertEqual(shown["movement"], {
            "sessions": [{"session_id": "d1", "manager": False, "read_at": utc(now - MIN)},
                         {"session_id": "m2", "manager": True, "read_at": utc(now - MIN)},
                         {"session_id": "s1", "manager": True, "read_at": None}],
            "nudged_at": iso(now - 30 * MIN),
            "base_at": utc(R),
            "issues": [1, 2, 3, 4, 5, 6, 7], "engine": {"moving": False, "waits": []},
            "waits": {"ci_at": None, "commit_at": None, "release_at": None, "lock_at": None}})
        self.assertEqual(self.shown(None, sprint_state=s)["movement"]["sessions"], [])

    def test_the_sprint_entry_publishes_its_wait_signal_times_whatever_it_says_now(self):
        now = self.now

        def utc(ms):
            return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat()

        shown = self.shown(moving(
            pulls=(PullMovement(1, frozenset({4}), now - 3 * MIN, now - 5 * MIN),),
            release_ms=now - 7 * MIN,
            sessions=(SessionMovement("s1", A, now - 5 * MIN, None, None),)))
        self.assertEqual(shown["now_text"], "Working on 2 issues.")
        self.assertEqual(shown["movement"]["waits"], {
            "ci_at": utc(now - 3 * MIN), "commit_at": utc(now - 5 * MIN),
            "release_at": utc(now - 7 * MIN), "lock_at": None})

    def test_the_sprint_entry_publishes_its_land_lock_wait_time_and_its_issues_with_the_inbox(self):
        now = self.now

        def utc(ms):
            return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat()

        inbox_only = reported(with_manager(started(A)), R, issues=((4, "building"),), inbox=(9,))
        shown = self.shown(moving(locks=((9, now - 2 * MIN), (99, now - MIN))),
                           sprint_state=inbox_only)
        self.assertEqual(shown["movement"]["waits"]["lock_at"], utc(now - 2 * MIN))
        self.assertEqual(shown["movement"]["issues"], [4, 9])
        self.assertEqual([i["issue"] for i in shown["issues"]], [4])
        self.assertEqual(self.shown(None, sprint_state=inbox_only)["movement"]["waits"]["lock_at"],
                         None)
        bare = self.shown(None, sprint_state=started(A))
        self.assertEqual(bare["movement"]["issues"], [])

    def test_sprint_sessions_of_names_the_manager_and_the_sessions_delivering_its_issues(self):
        sprint_a = dataclasses.replace(
            reported(started(A), R, issues=((4, "building"),), inbox=(9,)), manager_session="m2")
        B = "b" * 16
        sprint_b = dataclasses.replace(started(B), stopped_at=iso(R))
        sessions = [session("m1", "idle", name=NAME), session("m2", "idle"),
                    session("d1", "idle"), session("d2", "idle"), session("x1", "idle"),
                    session("e1", ENDED, name=NAME),
                    session("o1", "idle", repo="/srv/other", name=NAME),
                    session("y1", "idle", name=session_name("p00", B))]
        deliveries = {("d1", "wf_1"): DeliveryState("d1", "wf_1", 1, (IssueStage(4, "building"),)),
                      ("d2", "wf_2"): DeliveryState("d2", "wf_2", 1, (IssueStage(9, "building"),)),
                      ("x1", "wf_3"): DeliveryState("x1", "wf_3", 1, (IssueStage(99, "building"),))}
        found = view.sprint_sessions_of("p00", [sprint_a, sprint_b], sessions, deliveries,
                                        {"p00": state("p00", 1)})
        self.assertEqual(found, {"m1": frozenset({A}), "m2": frozenset({A}),
                                 "d1": frozenset({A}), "d2": frozenset({A})})

    def test_sprint_nudge_replies_names_the_nudged_managers_of_running_sprints(self):
        nudged = iso(R + MIN)
        sprint_a = dataclasses.replace(started(A), manager_session="m2", idle_nudged_at=nudged)
        B = "b" * 16
        sprint_b = dataclasses.replace(started(B), idle_nudged_at=None)
        sessions = [session("m1", "idle", name=NAME), session("m2", "idle"),
                    session("d1", "idle"), session("e1", ENDED, name=NAME),
                    session("y1", "idle", name=session_name("p00", B))]
        found = view.sprint_nudge_replies("p00", [sprint_a, sprint_b], sessions,
                                          {"p00": state("p00", 1)})
        self.assertEqual(found, {"m1": ((A, R + MIN),), "m2": ((A, R + MIN),)})


class SprintEndViewTest(unittest.TestCase):
    def test_a_closed_sprint_reads_done_with_what_landed(self):
        it = reported(started(A), R, issues=((12, "building"), (13, "queued"), (14, "held")))
        C = R + 5 * MIN
        it = closed(it, C, ((12, "landed"), (13, "dropped"), (14, "held")))
        shown = entry(line(it, C + MIN))
        self.assertEqual((shown["state"], shown["state_text"]), ("done", "done"))
        self.assertEqual(shown["closing"], {
            "at": iso(C), "summary": SUMMARY, "first_line": "Importer resumes after a crash",
            "differently": "cut smaller slices", "landed": [12], "held": [14], "dropped": [13],
            "counts_text": "1 landed, 1 held for verification, 1 dropped"})
        self.assertIs(shown["stoppable"], False)
        self.assertEqual(shown["ended_at"], iso(C))
        self.assertIsNone(shown["stop_text"])

    def test_a_sprint_ended_by_a_closing_shows_the_closing_and_nothing_of_the_last_report(self):
        it = reported(started(A), R, issues=((12, "building"), (13, "queued"), (14, "held")))
        C = R + 5 * MIN
        shown = entry(line(it, C))
        self.assertIsNotNone(shown["status"])
        self.assertIsNotNone(shown["next"])
        self.assertEqual(shown["progress"]["in_delivery"], 1)
        closed_it = closed(it, C, ((12, "landed"), (13, "dropped"), (14, "held")))
        shown = entry(line(closed_it, C + MIN))
        for member in ("status", "status_at", "next", "progress", "progress_text"):
            self.assertIsNone(shown[member], member)
        self.assertEqual(shown["milestone"], it.report.milestone)
        self.assertEqual(shown["tracker_url"], it.report.tracker_url)
        self.assertEqual(shown["issues"], [
            {"issue": 12, "stage": "landed", "stage_text": "landed"},
            {"issue": 13, "stage": "dropped", "stage_text": "dropped"},
            {"issue": 14, "stage": "held", "stage_text": "held for verification"}])
        self.assertEqual(shown["closing"]["counts_text"],
                         "1 landed, 1 held for verification, 1 dropped")

    def test_a_done_sprint_folds_into_finished_sprints_after_24_hours(self):
        C = R + 5 * MIN
        it = closed(reported(started(A), R), C, ((12, "landed"),))
        before = line(it, C + DAY - 1)
        self.assertEqual([s["sprint_id"] for s in before["entries"][0]["sprints"]], [A])
        self.assertIsNone(before["entries"][0]["finished_sprints"])
        after = line(it, C + DAY)
        project = after["entries"][0]
        self.assertEqual(project["sprints"], [])
        self.assertEqual(project["finished_sprints"]["label"], "Finished sprints")
        self.assertEqual(project["finished_sprints"]["count"], 1)
        self.assertEqual([s["sprint_id"] for s in project["finished_sprints"]["sprints"]], [A])
        self.assertIs(project["quiet"], True)
        unclocked = line(it, None)["entries"][0]
        self.assertEqual([s["sprint_id"] for s in unclocked["sprints"]], [A])
        self.assertIsNone(unclocked["finished_sprints"])

    def test_a_finished_sprint_keeps_its_manager_session_and_drops_its_brief(self):
        C = R + 5 * MIN
        manager = session("m1", "idle", name=session_name("p00", A))
        it = closed(reported(started(A), R), C, ((12, "landed"),))
        project = line(it, C + DAY, sessions=[manager])["entries"][0]
        finished = project["finished_sprints"]["sprints"][0]
        self.assertEqual([s["session_id"] for s in finished["sessions"]], ["m1"])
        self.assertEqual(project["outside_sprints"]["sessions"], [])
        self.assertIs(project["quiet"], True)
        waiting = stopped(briefed(started(A)), C, C + MIN)
        self.assertEqual(line(waiting, C + MIN + DAY - 1)["inbox"]["open"], [])
        gone = line(waiting, C + MIN + DAY)
        self.assertEqual(gone["inbox"]["open"], [])
        self.assertEqual(gone["statement"]["inbox_items"], 0)

    def test_a_stopped_sprint_reads_stopped_by_you_and_keeps_its_report(self):
        S = R + 2 * MIN
        plain = stopped(reported(started(A), R), S, S + MIN)
        shown = entry(line(plain, S + 2 * MIN))
        self.assertEqual((shown["state"], shown["state_text"]), ("stopped", "stopped by you"))
        self.assertIsNone(shown["closing"])
        self.assertEqual(shown["ended_at"], iso(S + MIN))
        with_closing = closed(plain, S + MIN, ((12, "landed"),))
        shown = entry(line(with_closing, S + 2 * MIN))
        self.assertEqual((shown["state"], shown["state_text"]), ("stopped", "stopped by you"))
        self.assertEqual(shown["closing"]["first_line"], "Importer resumes after a crash")
        stopping = stopped(reported(started(A), R), S)
        shown = entry(line(stopping, S + 2 * MIN))
        self.assertEqual((shown["state"], shown["state_text"]), ("stopping", "stopping"))
        self.assertIsNone(shown["stop_text"])
        self.assertIsNone(shown["ended_at"])
        failed = dataclasses.replace(stopping, stop_reason="boom")
        shown = entry(line(failed, S + 2 * MIN))
        self.assertEqual(shown["stop_text"], "could not stop the manager: boom; trying again")
        done = dataclasses.replace(plain, stop_reason="boom")
        self.assertIsNone(entry(line(done, S + 2 * MIN))["stop_text"])
        self.assertEqual(entry(line(plain, S + MIN + DAY - 1))["state"], "stopped")
        folded = line(plain, S + MIN + DAY)["entries"][0]
        self.assertEqual(folded["sprints"], [])
        self.assertEqual(folded["finished_sprints"]["sprints"][0]["state"], "stopped")

    def test_a_sprint_done_by_its_report_folds_too(self):
        done = reported(started(A), R, phase="done")
        shown = entry(line(done, R + MIN))
        self.assertEqual((shown["state"], shown["ended_at"], shown["closing"]),
                         ("done", iso(R), None))
        self.assertEqual([s["sprint_id"] for s in line(done, R + DAY - 1)["entries"][0]["sprints"]],
                         [A])
        folded = line(done, R + DAY)["entries"][0]
        self.assertEqual(folded["sprints"], [])
        self.assertEqual([s["sprint_id"] for s in folded["finished_sprints"]["sprints"]], [A])
        R2 = R + 10 * MIN
        again = reported(done, R2, phase="running")
        shown = entry(line(again, R2 + 2 * DAY))
        self.assertEqual(shown["ended_at"], None)
        later = closed(done, R + 3 * MIN, ((12, "landed"),))
        self.assertEqual(entry(line(later, R + 4 * MIN))["ended_at"], iso(R + 3 * MIN))

    def test_stop_is_offered_only_before_a_sprint_ends_or_stops(self):
        C = R + 5 * MIN
        cases = {
            "drafting": (briefed(sprint(A)), True),
            "on track": (reported(started(A), R), True),
            "closed": (closed(reported(started(A), R), C, ((12, "landed"),)), False),
            "done by report": (reported(started(A), R, phase="done"), False),
            "stopping": (stopped(reported(started(A), R), C), False),
            "stopped": (stopped(reported(started(A), R), C, C + MIN), False),
        }
        for name, (it, expected) in cases.items():
            with self.subTest(name):
                self.assertIs(entry(line(it, C + 2 * MIN))["stoppable"], expected)

    def test_unstopped_withdrawn_managers_are_listed(self):
        goal = "make the importer resumable"
        pending = {
            "b" * 16: PendingStop("b" * 16, "p00", goal, T0, "boom", T0),
            "a" * 16: PendingStop("a" * 16, "p00", goal, T0, "late", iso(T0_MS + MIN)),
            "c" * 16: PendingStop("c" * 16, "p00", goal, T0),
            "d" * 16: PendingStop("d" * 16, "p09", goal, T0, "boom", T0),
            "e" * 16: PendingStop("e" * 16, "p00", goal, T0, "zzz", T0)}
        view = derive_view([state("p00", 1)], pending=pending)
        self.assertEqual(view["unstopped"], [
            {"project_id": "p00", "sprint_id": sid, "title": goal, "failed_at": at,
             "text": f"The manager of a dropped sprint could not be stopped: {reason}; "
                     "trying again"}
            for sid, reason, at in (("b" * 16, "boom", T0), ("e" * 16, "zzz", T0),
                                    ("a" * 16, "late", iso(T0_MS + MIN)))])
        self.assertEqual(derive_view([state("p00", 1)])["unstopped"], [])


class ActorViewTest(unittest.TestCase):
    GUEST = "colleague@example.invalid"

    def test_an_answer_message_carries_the_question_it_answers_and_others_carry_none(self):
        sid = "d" * 16
        when = at_row(9)

        def row(seq, kind, **payload):
            return Event(seq, when, kind, "owner/p00",
                         {"sprint_id": sid, "goal": "one", **payload})

        ask = {"question": "Which store?", "blocks": "b", "options": ["sqlite", "files"],
               "recommended": "files"}
        rows = [row(20, event_log.GOAL_STATED), row(21, event_log.BRIEF_SENT, version=1, brief=PARTS_ROW),
                row(22, event_log.BRIEF_APPROVED, version=1),
                row(23, event_log.QUESTIONS_ASKED, blocker=False, questions=[ask]),
                row(24, event_log.QUESTION_ANSWERED, round=23, index=0, question="Which store?",
                    answer="sqlite", chosen="sqlite", recommended="files", differs=True)]
        shown = derive_view([state("owner/p00", 1)], sprints=sprint_states(rows), now_ms=T0_MS)
        messages = shown["entries"][0]["sprints"][0]["messages"]
        (answer,) = [m for m in messages if m["kind"] == "answer"]
        self.assertEqual(answer["question"], "Which store?")
        self.assertTrue(all(m["question"] is None for m in messages if m["kind"] != "answer"))

    def test_the_sprint_its_cards_and_its_messages_carry_their_actor(self):
        from .test_console_sprints import guest_rows
        u, v = "d" * 16, "e" * 16
        rows = [*guest_rows(A, self.GUEST), *guest_rows(B)]
        when = at_row(9)

        def row(seq, kind, sid, **payload):
            return Event(seq, when, kind, "owner/p00",
                         {"sprint_id": sid, "goal": "one", **payload})

        ask = {"question": "Which store?", "blocks": "b", "options": ["sqlite", "files"],
               "recommended": "files"}
        rows += [
            row(20, event_log.GOAL_STATED, u, by=self.GUEST),
            row(21, event_log.BRIEF_SENT, u, version=1, brief=PARTS_ROW),
            row(22, event_log.GOAL_STATED, v, by=self.GUEST),
            row(23, event_log.BRIEF_SENT, v, version=1, brief=PARTS_ROW),
            row(24, event_log.BRIEF_APPROVED, v, version=1),
            row(25, event_log.QUESTIONS_ASKED, v, blocker=False, questions=[ask]),
        ]
        shown = derive_view([state("owner/p00", 1)], sprints=sprint_states(rows),
                            now_ms=T0_MS)
        by_id = {s["sprint_id"]: s for s in shown["entries"][0]["sprints"]}
        mine, owners = by_id[A], by_id[B]
        self.assertEqual(mine["started_by"], self.GUEST)
        self.assertEqual([m["by"] for m in mine["messages"]], [self.GUEST] * len(mine["messages"]))
        self.assertTrue(mine["messages"])
        self.assertEqual(mine["approval"]["by"], self.GUEST)
        self.assertIsNone(owners["started_by"])
        self.assertTrue(owners["messages"])
        self.assertEqual([m["by"] for m in owners["messages"]], [None] * len(owners["messages"]))
        items = {i["key"]: i for i in shown["inbox"]["open"]}
        self.assertEqual(items[f"brief/{u}"]["started_by"], self.GUEST)
        question = next(i for k, i in items.items() if k.startswith(f"question/{v}/"))
        self.assertEqual(question["started_by"], self.GUEST)


class SprintViewTest(unittest.TestCase):
    def test_a_sprint_shows_its_goal_state_and_age(self):
        view = derive_view([state("p00", 1)], sprints={"a" * 16: sprint("a" * 16)},
                           now_ms=T0_MS + 3 * 60_000)
        self.assertEqual(view["entries"][0]["sprints"], [{
            "type": "sprint", "sprint_id": "a" * 16,
            "title": "make the importer resumable", "goal": "make the importer resumable",
            "state": "drafting", "state_text": "drafting the brief",
            "ball": "manager", "ball_text": "manager working", "now_text": "drafting the brief",
            "now_until": None,
            "stated_at": T0, "started_by": None, "age_text": "goal set 3 min ago", "manager_text": "no manager has picked this up",
            "manager_state": "none", "manager_until": None, "retry": True, "move": False,
            "progress": None, "progress_text": None, "status": None, "status_at": None, "work_text": None,
            "next": None, "milestone": None, "tracker_url": None, "issues": [], "waiting": 0,
            "checks": [], "waits": [], "live_faults": [], "now_titled": False, "legend": None,
            "sessions": [], "messages": [], "approval": None, "reach_text": None,
            "tell_text": "The manager picks it up at its next turn.",
            "stoppable": True, "ended_at": None, "stop_text": None, "closing": None,
            "state_until": None, "pictures": [], "permission_text": None,
        "movement": {"sessions": [], "nudged_at": None,
                     "base_at": "2026-11-12T10:00:00+00:00",
                     "issues": [], "engine": {"moving": False, "waits": []},
                     "waits": {"ci_at": None, "commit_at": None, "release_at": None,
                               "lock_at": None}}}])

    def test_a_sprint_shows_its_permission_mode_and_reason(self):
        sprints = {
            "a" * 16: dataclasses.replace(sprint("a" * 16),
                                          permission=Permission(BYPASS, RULES_IN_PLACE)),
            "b" * 16: dataclasses.replace(sprint("b" * 16),
                                          permission=Permission(AUTO, NOT_DECLARED)),
            "c" * 16: sprint("c" * 16),
        }
        view = derive_view([state("p00", 1)], sprints=sprints, now_ms=T0_MS)
        shown = {entry["sprint_id"]: entry["permission_text"]
                 for entry in view["entries"][0]["sprints"]}
        self.assertEqual(shown, {"a" * 16: "bypass: production rules in place",
                                 "b" * 16: "auto: no production rules declared",
                                 "c" * 16: None})

    def test_a_sprint_older_than_two_minutes_says_no_manager_has_picked_it_up(self):
        for now_ms, expected in ((None, None), (T0_MS, None), (T0_MS + 120_000, None),
                                 (T0_MS + 120_001, "no manager has picked this up")):
            with self.subTest(now_ms=now_ms):
                view = derive_view([state("p00", 1)], sprints={"a" * 16: sprint("a" * 16)},
                                   now_ms=now_ms)
                shown = view["entries"][0]["sprints"][0]
                self.assertEqual(shown["manager_text"], expected)
                if now_ms is None:
                    self.assertEqual(shown["age_text"], "goal set just now")

    def test_sprints_order_newest_first(self):
        view = derive_view([state("p00", 1)], sprints={
            "a" * 16: sprint("a" * 16, seq=5), "b" * 16: sprint("b" * 16, seq=9)})
        self.assertEqual([s["sprint_id"] for s in view["entries"][0]["sprints"]],
                         ["b" * 16, "a" * 16])

    def test_sprints_of_an_unregistered_project_are_not_shown(self):
        view = derive_view([state("p00", 1)], sprints={"b" * 16: sprint("b" * 16, pid="p09")})
        self.assertNotIn("b" * 16, json.dumps(view))
        self.assertEqual(view["entries"][0]["sprints"], [])
        self.assertEqual(view["statement"], derive_view([state("p00", 1)])["statement"])

    def test_a_project_with_a_sprint_is_never_quiet(self):
        view = derive_view([state(f"p{i:02d}", i + 1) for i in range(5)],
                           sprints={"a" * 16: sprint("a" * 16)})
        first = view["entries"][0]
        self.assertEqual(first["project_id"], "p00")
        self.assertIs(first["quiet"], False)
        self.assertEqual(len(first["sprints"]), 1)
        self.assertEqual(view["entries"][-1]["type"], "quiet_group")
        self.assertEqual(view["entries"][-1]["count"], 4)

    def test_recent_projects_lists_registered_projects_newest_first(self):
        view = derive_view([state("p00", 1), state("p01", 3), state("p02", 2), state("p03", 3)])
        self.assertEqual(view["recent_projects"], ["p01", "p03", "p02", "p00"])
        self.assertEqual(derive_view([])["recent_projects"], [])


MESSAGE_SID = "a" * 16


def message_at(seq):
    return f"2026-11-12T10:{seq:02d}:00.000000+00:00"


def message_row(seq, kind, payload):
    return Event(seq, message_at(seq), kind, "p00", {"sprint_id": MESSAGE_SID, **payload})


def message_rows(*more):
    rows = [message_row(1, event_log.GOAL_STATED, {"goal": "make the importer resumable"}),
            message_row(2, event_log.MANAGER_STARTED, {"profile": "work", "session_name": "m"})]
    return [*rows, *more]


def messaged_row(seq, text):
    return message_row(seq, event_log.SPRINT_MESSAGED, {"goal": "g", "text": text})


def nudged_row(seq, through, ok):
    payload = {"through": through, "route": "relay", "ok": ok}
    if not ok:
        payload["reason"] = "no route"
    return message_row(seq, event_log.SPRINT_NUDGED, payload)


def message_entry(rows):
    folded = sprint_states(rows)
    return derive_view([state("p00", 1)], sprints=folded,
                       now_ms=T0_MS)["entries"][0]["sprints"][0]


B = "b" * 16
C = "c" * 16


def at_min(n):
    return iso(T0_MS + n * MIN)


def with_notices(state_, *notices):
    return dataclasses.replace(state_, notices=tuple(notices))


class NoticeViewTest(unittest.TestCase):
    def test_a_projects_open_notices_are_listed_newest_first_with_their_words(self):
        sa = with_notices(
            sprint(A, goal="Fix the settings page"),
            Notice(3, at_min(3), "claim", "the page fold",
                   what="python/agent_tools/console/page.html", until="the board fold lands"),
            Notice(7, at_min(7), "hand-off", "the importer needs a retry", to="owner"),
            Notice(4, at_min(4), "heads-up", "taken back", withdrawn_at=at_min(5)))
        sb = with_notices(
            sprint(B, seq=6, goal="Keep the importer fast"),
            Notice(5, at_min(5), "heads-up", "sprint ask gains a dry run"),
            Notice(6, at_min(6), "heads-up", "ended with its sprint", ended_at=at_min(6)),
            Notice(8, at_min(8), "hand-off", "take the reader", to=A))
        sc = sprint(C, pid="p01", goal="Retire the old exporter")

        view_ = derive_view([state("p00", 1), state("p01", 2)], sprints={A: sa, B: sb, C: sc},
                            now_ms=T0_MS + 10 * MIN)
        by_id = {e["project_id"]: e for e in view_["entries"]}

        self.assertEqual(by_id["p00"]["notices"], [
            {"id": 8, "sprint_id": B, "poster": "Keep the importer fast", "kind": "hand-off",
             "kind_text": "Hand-off", "text": "take the reader", "what": None,
             "until_text": None, "to_text": "for Fix the settings page", "at": at_min(8),
             "owner": False},
            {"id": 7, "sprint_id": A, "poster": "Fix the settings page", "kind": "hand-off",
             "kind_text": "Hand-off", "text": "the importer needs a retry", "what": None,
             "until_text": None, "to_text": "for you", "at": at_min(7), "owner": False},
            {"id": 5, "sprint_id": B, "poster": "Keep the importer fast", "kind": "heads-up",
             "kind_text": "Heads-up", "text": "sprint ask gains a dry run", "what": None,
             "until_text": None, "to_text": None, "at": at_min(5), "owner": False},
            {"id": 3, "sprint_id": A, "poster": "Fix the settings page", "kind": "claim",
             "kind_text": "Claim", "text": "the page fold",
             "what": "python/agent_tools/console/page.html",
             "until_text": "until the board fold lands", "to_text": None, "at": at_min(3),
             "owner": False}])
        self.assertEqual(by_id["p01"]["notices"], [])

    def test_a_hand_off_to_a_sprint_not_in_the_view_reads_for_another_sprint(self):
        sa = with_notices(sprint(A), Notice(3, at_min(3), "hand-off", "the reader is yours",
                                            to="d" * 16))

        notices = derive_view([state("p00", 1)], sprints={A: sa})["entries"][0]["notices"]

        self.assertEqual([n["to_text"] for n in notices], ["for another sprint"])

    def test_notices_never_count_in_the_statement_or_the_inbox(self):
        sa = with_notices(
            sprint(A),
            Notice(3, at_min(3), "hand-off", "the importer needs a retry", to="owner"),
            Notice(4, at_min(4), "claim", "the page fold", what="page.html", until="Friday"))
        bare = dataclasses.replace(sa, notices=())

        with_ = derive_view([state("p00", 1)], sprints={A: sa}, now_ms=T0_MS)
        without = derive_view([state("p00", 1)], sprints={A: bare}, now_ms=T0_MS)

        self.assertEqual(len(with_["entries"][0]["notices"]), 2)
        self.assertEqual(with_["statement"], without["statement"])
        self.assertEqual(with_["inbox"], without["inbox"])
        self.assertEqual(with_["statement"]["inbox_items"], 0)
        self.assertEqual(with_["statement"]["headline"], "Nothing needs you")

        owner = {"p00": (Notice(9, at_min(9), "heads-up", "routes are frozen until Friday"),)}
        owned = derive_view([state("p00", 1)], sprints={A: sa}, owner_notices=owner,
                            now_ms=T0_MS)

        self.assertEqual(len(owned["entries"][0]["notices"]), 3)
        self.assertEqual(owned["statement"], without["statement"])
        self.assertEqual(owned["inbox"], without["inbox"])
        self.assertEqual(owned["recent_projects"], without["recent_projects"])
        self.assertEqual(owned["entries"][0]["open_work"], without["entries"][0]["open_work"])

    def test_the_owners_open_notices_join_the_board_as_from_you(self):
        sa = with_notices(
            sprint(A, goal="Fix the settings page"),
            Notice(5, at_min(5), "heads-up", "sprint ask gains a dry run"))
        owner = {"p00": (Notice(9, at_min(9), "heads-up", "routes are frozen until Friday"),
                         Notice(7, at_min(7), "heads-up", "taken back",
                                withdrawn_at=at_min(8)))}

        view_ = derive_view([state("p00", 1)], sprints={A: sa}, owner_notices=owner,
                            now_ms=T0_MS + 10 * MIN)

        self.assertEqual(view_["entries"][0]["notices"], [
            {"id": 9, "sprint_id": None, "poster": "You", "kind": "heads-up",
             "kind_text": "Heads-up", "text": "routes are frozen until Friday", "what": None,
             "until_text": None, "to_text": None, "at": at_min(9), "owner": True},
            {"id": 5, "sprint_id": A, "poster": "Fix the settings page", "kind": "heads-up",
             "kind_text": "Heads-up", "text": "sprint ask gains a dry run", "what": None,
             "until_text": None, "to_text": None, "at": at_min(5), "owner": False}])

    def test_a_project_with_a_running_sprint_offers_the_post(self):
        stopping = dataclasses.replace(sprint(C, pid="p01"), stop_at=T0)

        view_ = derive_view([state("p00", 1), state("p01", 2), state("p02", 3)],
                            sprints={A: sprint(A), C: stopping}, now_ms=T0_MS)

        self.assertEqual({e["project_id"]: e["notice_post"] for e in view_["entries"]},
                         {"p00": True, "p01": False, "p02": False})

    PATH = "python/agent_tools/console/page.html"

    def claim(self, sid, notice_id, minute, text, issue, live_fault=True, what=None):
        return with_notices(started(sid), Notice(
            notice_id, at_min(minute), "claim", text, what=what or self.PATH, until=text + " lands",
            issue=issue, live_fault=live_fault))

    def line(self, sa, sb):
        return (sprint_title(sa) + " and " + sprint_title(sb) + " both fix a live fault in "
                + self.PATH + "; the rule could not decide which lands first")

    def overlaps(self, states, projects=(("p00", 1),)):
        return {e["project_id"]: e["overlaps"] for e in derive_view(
            [state(pid, seq) for pid, seq in projects], sprints=states,
            now_ms=T0_MS + 10 * MIN)["entries"]}

    def test_an_unsettled_overlap_is_one_line_and_raises_no_question(self):
        sa = self.claim(A, 3, 3, "the form", 12)
        sb = self.claim(B, 5, 5, "the upload row", 13)

        v = derive_view([state("p00", 1)], sprints={A: sa, B: sb}, now_ms=T0_MS + 10 * MIN)

        self.assertEqual(v["entries"][0]["overlaps"],
                         [{"sprints": [A, B], "files": [self.PATH], "text": self.line(sa, sb)}])
        self.assertEqual(v["statement"]["inbox_items"], 0)
        self.assertEqual([i for i in v["inbox"]["open"] if i.get("reason") == "question"], [])

    def test_the_overlap_line_goes_when_either_claim_ends(self):
        sa = self.claim(A, 3, 3, "the form", 12)
        sb = self.claim(B, 5, 5, "the upload row", 13)
        before = {A: sa, B: sb}
        self.assertTrue(sprints_module.takes_notices(sa))
        self.assertTrue(sprints_module.takes_notices(sb))
        self.assertEqual(sb.state, sprints_module.STARTING)
        self.assertEqual(self.overlaps(before)["p00"],
                         [{"sprints": [A, B], "files": [self.PATH], "text": self.line(sa, sb)}])
        withdrawn = sprint_states([Event(
            20, at_min(7), event_log.NOTICE_WITHDRAWN, "p00",
            {"sprint_id": A, "goal": "Fix the settings page", "notice": 3})], before)
        landed = sprint_states([Event(
            21, at_min(7), event_log.SPRINT_REPORTED, "p00",
            {"sprint_id": B, "goal": "Add resumable uploads",
             "report": {**REPORT_ROW,
                        "issues": [{"issue": 12, "stage": "building"},
                                   {"issue": 13, "stage": "landed"}],
                        "inbox": []}})], before)
        for name, after, other in (("withdrawn", withdrawn, "the upload row"),
                                   ("landed", landed, "the form")):
            with self.subTest(name):
                v = derive_view([state("p00", 1)], sprints=after, now_ms=T0_MS + 10 * MIN)
                self.assertEqual(v["entries"][0]["overlaps"], [])
                self.assertEqual([n["text"] for n in v["entries"][0]["notices"]], [other])

    def test_two_claims_on_one_bracketed_file_draw_a_line(self):
        path = "app/[[]id]/page.tsx"
        sa = self.claim(A, 3, 3, "the form", 12, what=path)
        sb = self.claim(B, 5, 5, "the upload row", 13, what=path)
        self.assertEqual(self.overlaps({A: sa, B: sb})["p00"], [{
            "sprints": [A, B], "files": [path],
            "text": self.line(sa, sb).replace(self.PATH, path)}])

    def test_a_settled_overlap_draws_no_line(self):
        for name, fault_a, fault_b in (("one fault", False, True), ("none", False, False)):
            with self.subTest(name):
                sa = self.claim(A, 3, 3, "the form", 12, live_fault=fault_a)
                sb = self.claim(B, 5, 5, "the upload row", 13, live_fault=fault_b)
                self.assertEqual(self.overlaps({A: sa, B: sb})["p00"], [])
        sa = self.claim(A, 3, 3, "the form", 12)
        sb = self.claim(B, 5, 5, "the upload row", 13)
        every = self.overlaps({A: sa, B: sb}, (("p00", 1), ("p01", 2)))
        self.assertEqual(sorted(every), ["p00", "p01"])
        self.assertEqual(every["p01"], [])
        self.assertEqual(len(every["p00"]), 1)


class SprintMessageViewTest(unittest.TestCase):
    TEXT = "leave the importer's schema alone"

    def test_a_messages_state_moves_from_sent_to_picked_up(self):
        sent_row = messaged_row(3, self.TEXT)
        entry = message_entry(message_rows(sent_row))
        self.assertEqual(entry["messages"], [{
            "id": 3, "kind": "text", "version": None, "text": self.TEXT, "at": message_at(3),
            "state": "sent", "state_text": "sent, the manager picks it up within a minute",
            "action_text": None, "read_at": None, "reply": None, "reply_at": None,
            "words": None, "new": False, "by": None, "question": None}])
        self.assertIsNone(entry["reach_text"])
        entry = message_entry(message_rows(sent_row, nudged_row(4, 3, True)))
        self.assertEqual(entry["messages"][0]["state"], "sent")
        entry = message_entry(message_rows(
            sent_row, nudged_row(4, 3, True),
            message_row(5, event_log.SPRINT_READ, {"through": 3})))
        self.assertEqual(entry["messages"][0]["state"], "picked_up")
        self.assertEqual(entry["messages"][0]["state_text"], "picked up")
        self.assertEqual(entry["messages"][0]["read_at"], message_at(5))

    def test_two_failed_nudges_show_manager_not_reachable_and_keep_the_messages(self):
        plain = message_entry(message_rows(messaged_row(3, self.TEXT)))
        one = message_entry(message_rows(messaged_row(3, self.TEXT), nudged_row(4, 3, False)))
        self.assertIsNone(one["reach_text"])
        two = message_entry(message_rows(
            messaged_row(3, self.TEXT), nudged_row(4, 3, False), nudged_row(5, 3, False)))
        self.assertEqual(two["reach_text"], "manager not reachable")
        self.assertEqual([(m["id"], m["state"]) for m in two["messages"]], [(3, "sent")])
        self.assertEqual(two["retry"], plain["retry"])

    def test_a_reply_shows_under_its_message(self):
        entry = message_entry(message_rows(
            messaged_row(3, self.TEXT),
            message_row(4, event_log.SPRINT_ANSWERED,
                        {"message": 3, "reply": "kept the schema"})))
        self.assertEqual((entry["messages"][0]["reply"], entry["messages"][0]["reply_at"]),
                         ("kept the schema", message_at(4)))

    def test_an_approval_and_a_change_request_are_listed_as_messages(self):
        parts = {"done": "d", "excluded": ["x"], "slices": ["a"], "risks": ["r"], "asks": ["q"]}
        brief = {"goal": "g", "brief": parts}
        entry = message_entry(message_rows(
            message_row(3, event_log.BRIEF_SENT, {"version": 1, **brief}),
            message_row(4, event_log.BRIEF_REPLIED,
                        {"version": 1, "goal": "g", "reply": "smaller slices"}),
            message_row(5, event_log.BRIEF_SENT, {"version": 2, **brief}),
            message_row(6, event_log.BRIEF_APPROVED, {"version": 2, "goal": "g"})))
        self.assertEqual([(m["id"], m["kind"], m["version"], m["text"])
                          for m in entry["messages"]],
                         [(4, "changes", 1, "smaller slices"), (6, "approved", 2, None)])

    def test_an_answer_with_words_carries_the_option_and_the_words_in_its_message(self):
        answered = [Message(7, MESSAGE_ANSWER, message_at(7), None, "Ask for changes",
                            question="Approve?", round_id=5, chosen="Ask for changes",
                            words="split the reader slice"),
                    Message(8, MESSAGE_ANSWER, message_at(8), None, "Approve",
                            question="Ship?", round_id=5, chosen="Approve")]
        shown = derive_view([state("p00", 1)], sprints={
            A: dataclasses.replace(started(A), messages=tuple(answered))}, now_ms=T0_MS)
        messages = shown["entries"][0]["sprints"][0]["messages"]
        self.assertEqual([(m["kind"], m["text"], m["words"]) for m in messages],
                         [("answer", "Ask for changes", "split the reader slice"),
                          ("answer", "Approve", None)])

    def test_only_the_ten_newest_messages_are_shown(self):
        rows = message_rows(*(messaged_row(seq, f"note {seq}") for seq in range(3, 15)))
        entry = message_entry(rows)
        self.assertEqual(view.SHOWN_MESSAGES, 10)
        self.assertEqual([m["id"] for m in entry["messages"]], list(range(5, 15)))


class ReviveViewTest(unittest.TestCase):
    SID = "a" * 16
    GOAL = "make the importer resumable"

    @staticmethod
    def row(seq, kind, **payload):
        return Event(seq, f"2026-11-12T10:0{seq}:00.000000+00:00", kind, "p00", payload)

    def stated(self, sid=None):
        return self.row(1, event_log.GOAL_STATED, sprint_id=sid or self.SID, goal=self.GOAL)

    def stalled(self, seq=3, sid=None, reason="r"):
        return self.row(seq, event_log.MANAGER_STALLED, sprint_id=sid or self.SID,
                        goal=self.GOAL, reason=reason)

    def test_a_restart_and_a_takeover_each_add_one_digest_sentence_and_no_inbox_item(self):
        rows = [
            self.stated(),
            self.row(2, event_log.MANAGER_STARTED, sprint_id=self.SID, profile="work",
                     session_name="n"),
            self.row(3, event_log.MANAGER_WOKEN, sprint_id=self.SID, ok=True, goal=self.GOAL,
                     session_id="s-1"),
            self.row(4, event_log.MANAGER_STARTED, sprint_id=self.SID, takeover=True,
                     goal=self.GOAL, profile="work", session_name="n")]
        folded = sprint_states(rows)
        made = digest.moments(rows, {}, {})
        now = datetime.fromisoformat("2026-11-12T11:00:00.000000+00:00")
        shown = derive_view([state("p00", 1)], sprints=folded,
                            digest=digest.digest(made, None, now))
        self.assertEqual([m["sentence"] for m in shown["digest"]["recent"]], [
            "A new manager took over " + self.GOAL,
            "The manager of " + self.GOAL + " was restarted"])
        self.assertEqual(shown["inbox"]["open"], [])
        self.assertEqual(shown["statement"]["inbox_items"], 0)

    def test_a_stalled_sprint_is_one_counted_inbox_item_with_its_reason(self):
        folded = sprint_states([self.stated(), self.stalled()])
        shown = derive_view([state("p00", 1)], sprints=folded)
        self.assertEqual(shown["inbox"]["open"], [{
            "type": "inbox_item", "reason": "manager", "key": "manager/" + self.SID,
            "project_id": "p00", "sprint_id": self.SID, "title": self.GOAL,
            "headline": "managers keep failing on " + self.GOAL, "last_reason": "r",
            "answered": False, "waiting_since": "2026-11-12T10:03:00.000000+00:00"}])
        self.assertEqual(shown["statement"]["inbox_items"], 1)
        self.assertEqual(shown["statement"]["headline"], "1 thing needs you")
        self.assertEqual(shown["statement"]["sentence"], view.MANAGER_SENTENCE)
        self.assertEqual(view.MANAGER_SENTENCE,
                         "Try again to start a new manager, or drop the sprint.")
        entry = shown["entries"][0]["sprints"][0]
        self.assertEqual((entry["manager_state"], entry["manager_text"], entry["retry"]),
                         ("stalled", "managers keep failing: r", True))

    def test_a_stalled_manager_seen_again_leaves_no_stall_item_and_reads_started(self):
        seen = self.row(4, "session.seen", session_id="s-1", cwd="/x", repo=None, state="idle",
                        name="p00 sprint " + self.SID)
        started = self.row(2, event_log.MANAGER_STARTED, sprint_id=self.SID, profile="work",
                           session_name="p00 sprint " + self.SID)
        folded = sprint_states([self.stated(), started, self.stalled(), seen])
        shown = derive_view([state("p00", 1)], sprints=folded)
        self.assertEqual(shown["inbox"]["open"], [])
        self.assertEqual(shown["statement"]["inbox_items"], 0)
        entry = shown["entries"][0]["sprints"][0]
        self.assertEqual((entry["manager_state"], entry["retry"]), ("started", False))

    def test_stall_items_follow_briefs_and_precede_tracker_items(self):
        a, b, c = "a" * 16, "b" * 16, "c" * 16
        stall = dataclasses.replace
        records = {("p00", "k1"): InboxRecord(item("p00", "k1", held=9), "t1", "u1")}
        shown = derive_view([state("p00", 1)], records, sprints={
            a: stall(sprint(a), stalled="r", stalled_at="t7"),
            b: stall(sprint(b), stalled="r", stalled_at="t5"),
            c: briefed(sprint(c), at="t9")})
        self.assertEqual([e["key"] for e in shown["inbox"]["open"]],
                         ["brief/" + c, "manager/" + b, "manager/" + a, "k1"])
        self.assertEqual(shown["statement"]["inbox_items"], 4)
        self.assertEqual(shown["statement"]["sentence"], BRIEF_SENTENCE)

    def test_a_stall_of_an_unregistered_project_is_not_shown(self):
        sprints = {self.SID: dataclasses.replace(
            sprint(self.SID, pid="p09"), stalled="r", stalled_at="t7")}
        shown = derive_view([state("p00", 1)], sprints=sprints)
        self.assertEqual(shown["inbox"]["open"], [])
        self.assertEqual(shown["statement"], derive_view([state("p00", 1)])["statement"])


def signin_entry(profile, state, ask, since=None, days_left=None, ends_at=None, ever=False):
    return {"profile": profile, "state": "unknown", "week_left": None, "five_hour_left": None,
            "next_reset": None, "out_until": None, "read_at": None,
            "signin": {"state": state, "ends_at": ends_at, "days_left": days_left, "ask": ask,
                       "since": since, "ever_signed_in": ever}}


def signin_capacity(*entries):
    return {"tight": False, "all_out": False, "resumes_at": None, "no_reading": None,
            "profiles": list(entries)}


def signin_item(profile, signin, run=None):
    return {"type": "inbox_item", "reason": "signin", "key": f"signin/{profile}",
            "project_id": None, "profile": profile,
            "headline": f"Sign in to {profile}" + (" again" if signin["ever_signed_in"] else ""),
            "action": "signin", "run": run, "signin": signin, "answered": False,
            "waiting_since": signin["since"]}


class SigninViewTest(unittest.TestCase):
    def test_each_asking_profile_is_one_inbox_item_with_the_sign_in_action(self):
        spare = signin_entry("spare", "signed_out", True, since="t1")
        work = signin_entry("work", "signed_in", True, since="2026-11-10T09:00:00+00:00",
                            days_left=2, ends_at="2026-11-13T09:00:00+00:00", ever=True)
        home = signin_entry("home", "signed_in", False, days_left=20,
                            ends_at="2026-12-03T09:00:00+00:00", ever=True)
        shown = derive_view([state("p00", 1)], capacity=signin_capacity(home, spare, work))
        self.assertEqual(shown["inbox"]["open"], [signin_item("spare", spare["signin"]),
                                                  signin_item("work", work["signin"])])
        self.assertEqual(shown["statement"]["inbox_items"], 2)
        self.assertEqual(shown["statement"]["headline"], "2 things need you")
        self.assertEqual(shown["statement"]["sentence"], view.SIGNIN_SENTENCE)
        self.assertEqual(view.SIGNIN_SENTENCE,
                         "Press Sign in, then finish signing in in your browser.")
        self.assertNotIn("CLAUDE_ACCOUNT", json.dumps(shown))
        fresh = signin_entry("work", "signed_in", False, days_left=30,
                             ends_at="2026-12-13T09:00:00+00:00")
        shown = derive_view([state("p00", 1)], capacity=signin_capacity(home, fresh))
        self.assertEqual(shown["inbox"]["open"], [])
        self.assertEqual(shown["statement"]["headline"], "Nothing needs you")

    def test_a_signed_out_profile_a_colleague_added_raises_no_sign_in_item(self):
        """#1361, ADR-console-087: signing a colleague's account in is his, never the owner's."""
        mine = signin_entry("work", "signed_out", True, since="t1", ever=True)
        his = {**signin_entry("colleague-1", "signed_out", True, since="t2"), "owner": "ana@corp.invalid"}
        plain = {**signin_entry("home", "signed_out", True, since="t3"), "owner": None}
        shown = derive_view([state("p00", 1)], capacity=signin_capacity(mine, his, plain))
        self.assertEqual([i["key"] for i in shown["inbox"]["open"]], ["signin/home", "signin/work"])
        self.assertEqual(shown["statement"]["inbox_items"], 2)
        alone = derive_view([state("p00", 1)], capacity=signin_capacity(his))
        self.assertEqual(alone["inbox"]["open"], [])
        self.assertEqual(alone["statement"]["headline"], "Nothing needs you")

    def test_a_never_signed_in_profile_is_offered_sign_in_not_sign_in_again(self):
        fresh = signin_entry("fresh", "signed_out", True, since="t1")
        work = signin_entry("work", "signed_out", True, since="t2", ever=True)
        shown = derive_view([state("p00", 1)], capacity=signin_capacity(fresh, work))
        self.assertEqual([i["headline"] for i in shown["inbox"]["open"]],
                         ["Sign in to fresh", "Sign in to work again"])
        self.assertEqual(view.SIGNIN_FIRST_HEADLINE, "Sign in to {profile}")

    def test_an_items_run_is_the_profiles_sign_in_run(self):
        spare = signin_entry("spare", "signed_out", True, since="t1")
        home = signin_entry("home", "signed_in", False, days_left=20,
                            ends_at="2026-12-03T09:00:00+00:00")
        runs = {"spare": {"state": "timed_out", "at": "t2", "attempt": 4},
                "home": {"state": "signed_in", "at": "t3", "attempt": 2}}
        shown = derive_view([state("p00", 1)], capacity=signin_capacity(home, spare),
                            signin_runs=runs)
        self.assertEqual(shown["inbox"]["open"], [signin_item(
            "spare", spare["signin"], {"state": "timed_out", "at": "t2", "attempt": 4})])
        self.assertEqual(shown["signin_runs"], runs)
        bare = derive_view([state("p00", 1)], capacity=signin_capacity(home, spare))
        self.assertEqual(bare["signin_runs"], {})

    def test_the_view_lists_the_accounts_added_from_the_page(self):
        home = signin_entry("home", "signed_in", False, days_left=20,
                            ends_at="2026-12-03T09:00:00+00:00")
        shown = derive_view([state("p00", 1)], capacity=signin_capacity(home),
                            accounts_added=["b", "a", "b"])
        self.assertEqual(shown["accounts_added"], ["a", "b"])
        bare = derive_view([state("p00", 1)], capacity=signin_capacity(home))
        self.assertEqual(bare["accounts_added"], [])

    def test_the_view_carries_the_registration(self):
        entry = {"root": "/r", "name": "r", "status": "done", "lines": ["a"]}
        shown = derive_view([], registration=entry)["registration"]
        self.assertEqual(shown, entry)
        self.assertIsNot(shown, entry)
        self.assertIsNone(derive_view([])["registration"])

    def test_the_view_counts_the_running_sessions_of_each_profile(self):
        def under(sid, status, profile):
            return SessionState(sid, "/srv/p00", "/srv/p00", status, None, 1, "t1", None, profile)

        running = [under("s1", "working", "work"), under("s2", "working", "work"),
                   under("s3", ENDED, "work"), under("s4", "idle", "home"),
                   under("s5", "working", None)]
        cap = capacity_view(["home", "work", "spare"], CapacityState({}, {}), 0.0)
        shown = derive_view([state("p00", 1)], sessions=(s for s in running), capacity=cap)
        self.assertEqual(shown["profile_sessions"], {"home": 1, "spare": 0, "work": 2})
        self.assertEqual(derive_view([state("p00", 1)])["profile_sessions"], {})

    def test_sign_in_items_follow_progress_and_precede_questions(self):
        ask = signin_entry("spare", "signed_out", True, since="t1")
        records = {("p00", "k1"): InboxRecord(
            {**item("p00", "k1"), "reason": "decision", "questions": [
                {"question": "Which one?", "options": ["x"], "chosen": None}]}, "t1", "u1")}
        b = "b" * 16
        sprints = {A: asked(started(A)), b: dataclasses.replace(
            with_manager(started(b)), no_progress_at=iso(R))}
        shown = derive_view([state("p00", 1)], records, sprints=sprints,
                            capacity=signin_capacity(ask))
        self.assertEqual([e["reason"] for e in shown["inbox"]["open"]],
                         ["progress", "signin", "question", "question", "decision"])
        self.assertEqual(shown["statement"]["sentence"], view.PROGRESS_SENTENCE)
        without = derive_view([state("p00", 1)], records, sprints={A: asked(started(A))},
                              capacity=signin_capacity(ask))
        self.assertEqual([e["reason"] for e in without["inbox"]["open"]],
                         ["signin", "question", "question", "decision"])
        self.assertEqual(without["statement"]["sentence"], view.SIGNIN_SENTENCE)
        c = "c" * 16
        briefed_too = derive_view([state("p00", 1)], records, capacity=signin_capacity(ask),
                                  sprints={A: asked(started(A)), c: briefed(sprint(c), at="t5")})
        self.assertEqual(briefed_too["statement"]["sentence"], BRIEF_SENTENCE)

    def test_adoption_items_follow_sign_ins_and_precede_questions(self):
        ask = signin_entry("spare", "signed_out", True, since="t1")
        one = asked(started(A))
        one = dataclasses.replace(one, questions=one.questions[:1])
        shown = derive_view([state("p00", 1)], sprints={A: one},
                            capacity=signin_capacity(ask), adoption_items=[ADOPTION_ITEM])
        self.assertEqual([e["reason"] for e in shown["inbox"]["open"]],
                         ["signin", "adoption", "question"])
        self.assertEqual(shown["statement"]["inbox_items"], 3)
        self.assertEqual(shown["statement"]["sentence"], view.SIGNIN_SENTENCE)

    def test_release_items_are_open_inbox_entries_after_adoptions(self):
        shown = derive_view([state("p00", 1)], sprints={A: asked(started(A))},
                            adoption_items=[ADOPTION_ITEM], release_items=[RELEASE_ITEM])
        reasons = [e["reason"] for e in shown["inbox"]["open"]]
        self.assertEqual(reasons[:2], ["adoption", "release"])
        self.assertEqual(shown["inbox"]["open"][1], RELEASE_ITEM)
        self.assertIsNot(shown["inbox"]["open"][1], RELEASE_ITEM)
        self.assertEqual(shown["statement"]["inbox_items"], len(reasons))
        alone = derive_view([], release_items=[RELEASE_ITEM])
        self.assertEqual(alone["statement"]["inbox_items"], 1)

    def test_an_adoption_item_sets_its_sentence_and_needs_no_registered_project(self):
        shown = derive_view([], adoption_items=[ADOPTION_ITEM])
        self.assertEqual(shown["statement"]["inbox_items"], 1)
        self.assertEqual(shown["statement"]["sentence"],
                         "Merge the adoption from its card; when it cannot be merged there, the card says why.")
        self.assertEqual(shown["inbox"]["open"], [ADOPTION_ITEM])
        self.assertIsNot(shown["inbox"]["open"][0], ADOPTION_ITEM)
        asked_too = derive_view([state("p00", 1)], sprints={A: asked(started(A))},
                                adoption_items=[ADOPTION_ITEM])
        self.assertEqual(asked_too["statement"]["sentence"], view.ADOPTION_SENTENCE)

    def test_a_capacity_without_sign_in_raises_nothing(self):
        shown = derive_view([state("p00", 1)], capacity=out())
        self.assertEqual([e for e in shown["inbox"]["open"] if e["reason"] == "signin"], [])


RELEASE_ITEM = release_card.inbox_entries(
    {3: release_card.Card(3, "a" * 40, "v1.2.0", "2026-11-21T08:00:00+00:00", "open")})[0]

PID = "sha256:" + "a" * 64
ASK_A = {"id": "candidate-class", "subject": ".claude/odd.md",
         "ask": "What should happen to .claude/odd.md? No rule covers this agent file.",
         "options": [{"value": "archive-history",
                      "label": "Archive it under .agents/knowledge/archive/adopted/"}],
         "recommended": None, "why": None}
ASK_B = {"id": "path-reference", "subject": "tools/show.sh:1:5",
         "ask": "tools/show.sh line 1 names .claude/specs/a.md, which this plan moves. "
                "Should it follow the move?",
         "options": [{"value": "rewrite", "label": "Change it to .agents/artifacts/specs/a.md"},
                     {"value": "retain", "label": "Leave it as it is"}],
         "recommended": None, "why": None}
ASK_WHY = {"id": "candidate-class", "subject": ".claude/secrets/key.md",
           "ask": "What should happen to .claude/secrets/key.md?", "options": [],
           "recommended": None,
           "why": ".claude/secrets/key.md looks like a secret, so it cannot be answered here: "
                  "remove it from the repository in its own commit, then register the "
                  "repository again."}


def reg(questions, **over):
    return {"root": "/srv/sample-app", "name": "sample-app", "status": "done", "plan_id": PID,
            "at": "2026-11-15T08:00:00+00:00", "questions": questions, "refusal": None,
            "refused": None, **over}


def register_item(index, ask):
    return {"type": "inbox_item", "reason": "register", "key": f"register/{PID}/{index}",
            "project_id": None, "root": "/srv/sample-app", "name": "sample-app",
            "title": "Register sample-app", "plan_id": PID, "id": ask["id"],
            "subject": ask["subject"], "headline": ask["ask"], "why": ask["why"],
            "refusal": None, "more_questions": 0,
            "questions": [{"question": ask["ask"], "options": [o["label"] for o in ask["options"]],
                           "chosen": None, "recommended": None, "recommended_index": None}],
            "text": False, "placeholder": None, "values": [o["value"] for o in ask["options"]],
            "items": [], "answers": [], "answered": False,
            "waiting_since": "2026-11-15T08:00:00+00:00"}


class RegisterItemViewTest(unittest.TestCase):
    def decision(self):
        record = {**item("p", "k1"), "reason": "decision", "questions": [
            {"question": "Which?", "options": ["a", "b"], "chosen": None, "recommended": None}]}
        return {("p", "k1"): InboxRecord(record, "t1", "u1")}

    def test_two_open_plan_questions_are_two_counted_items(self):
        shown = derive_view([], registration=reg([ASK_A, ASK_B]))
        self.assertEqual(shown["inbox"]["open"],
                         [register_item(0, ASK_A), register_item(1, ASK_B)])
        self.assertEqual(shown["statement"]["inbox_items"], 2)
        self.assertEqual(shown["statement"]["headline"], "2 things need you")

    def test_a_text_question_is_a_counted_register_item_with_a_text_field(self):
        ask = {"id": "contract-draft", "subject": "integration-branch",
               "ask": "Which branch does finished work of sample-app merge into?\nIt has no remote, "
                      "so the console cannot tell: choose a branch or type its name.",
               "options": [], "recommended": None, "why": None, "text": True}
        shown = derive_view([], registration=reg([ask]))
        (entry,) = shown["inbox"]["open"]
        self.assertEqual((entry["text"], entry["questions"], entry["why"]), (True, [], None))
        self.assertEqual(shown["statement"]["inbox_items"], 1)
        self.assertEqual(shown["statement"]["sentence"], "Type the answer on its card and press Enter.")
        self.assertEqual(shown["statement"]["sentence"], view.REGISTER_TYPE_SENTENCE)

    def test_no_drafted_value_line_uses_an_internal_term(self):
        reading = {"remotes": [("origin", "git@github.com:sample-owner/sample-app.git")],
                   "default_branch": "trunk", "branches": ["trunk"],
                   "files": ["README.md", "justfile"],
                   "texts": {"justfile": "lint:\n\ttrue\ntest:\n\ttrue\n"}}
        fields = contract_draft.draft("/x/sample-app", reading)
        row = register.drafting("/x/sample-app", fields)
        shown = derive_view([], registration=register.view_entry(
            None, {**row, "at": "2026-11-15T08:00:00+00:00"}))
        entries = shown["registration"]["draft"]
        texts = ([e["line"] for e in entries] + [o["label"] for e in entries for o in e["options"]]
                 + [shown["registration"]["draft_more"]])
        self.assertEqual(len(entries), len(contract_draft.FIELDS) + len(contract_draft.FACTS))
        for text in texts:
            for term in ("<num>", "<slug>", "light lane", "hint", "operations path",
                         "rejection path"):
                self.assertNotIn(term, text.lower())
        self.assertEqual(
            shown["registration"]["draft_more"],
            f"and {len([f for f in contract_draft.FIELDS if f not in contract_draft.MAIN])} more "
            "settings at their usual values")
        self.assertEqual(shown["registration"]["draft_more"],
                         "and 2 more settings at their usual values")

    def test_a_text_card_carries_the_placeholder_of_its_field(self):
        ask = {"id": "contract-draft", "subject": "integration-branch",
               "ask": "Which branch does finished work merge into?", "options": [],
               "recommended": None, "why": None, "text": True}
        shown = derive_view([], registration=reg([ask, ASK_A]))
        first, second = shown["inbox"]["open"]
        self.assertEqual(first["placeholder"], "a branch name")
        self.assertIsNone(second["placeholder"])

    def test_the_registration_carries_its_draft_lines(self):
        lines = [{"field": "project-id", "line": "Project id: o/r (read from the remote)",
                  "value": "o/r", "options": [], "text": True}]
        shown = derive_view([], registration=reg([ASK_A], draft=lines))
        self.assertEqual(shown["registration"]["draft"], lines)
        (entry,) = shown["inbox"]["open"]
        self.assertIs(entry["text"], False)

    def test_a_question_with_no_offered_answer_is_an_item_with_its_why_and_no_options(self):
        shown = derive_view([], registration=reg([ASK_WHY]))
        (entry,) = shown["inbox"]["open"]
        self.assertEqual((entry["why"], entry["questions"], entry["values"], entry["headline"]),
                         (ASK_WHY["why"], [], [], ASK_WHY["ask"]))
        self.assertEqual(shown["statement"]["inbox_items"], 1)
        self.assertEqual(shown["statement"]["sentence"], REGISTER_STEP_SENTENCE)

    def test_a_running_or_questionless_registration_adds_no_item(self):
        for registration in (reg([ASK_A], status="running"), reg([]), None):
            with self.subTest(registration=registration):
                shown = derive_view([], registration=registration)
                self.assertEqual(shown["inbox"]["open"], [])
                self.assertEqual(shown["statement"]["inbox_items"], 0)

    def test_plan_questions_sit_before_tracker_items(self):
        shown = derive_view([state("p", 1)], self.decision(), registration=reg([ASK_A]))
        self.assertEqual([e["key"] for e in shown["inbox"]["open"]], [f"register/{PID}/0", "k1"])
        self.assertEqual(shown["statement"]["inbox_items"], 2)

    def test_the_refusal_shows_on_the_refused_question_only(self):
        refused = {"id": "path-reference", "subject": "tools/show.sh:1:5"}
        text = "The plan refused that answer: no"
        shown = derive_view([], registration=reg([ASK_A, ASK_B], refusal=text, refused=refused))
        self.assertEqual([e["refusal"] for e in shown["inbox"]["open"]], [None, text])

    def test_the_sentence_says_how_to_answer_a_plan_question(self):
        def sentence(registration, records=None):
            return derive_view([state("p", 1)], records, registration=registration)[
                "statement"]["sentence"]

        self.assertEqual(sentence(reg([ASK_A])), REGISTER_SENTENCE)
        self.assertEqual(sentence(reg([ASK_A]), self.decision()), REGISTER_SENTENCE)
        self.assertEqual(sentence(reg([ASK_WHY]), self.decision()), CHOOSE_SENTENCE)


RETRY_AT = "2026-11-15T09:00:00+00:00"
RETRY_ITEM = {
    "type": "inbox_item", "reason": "register_retry", "key": f"register-retry/{PID}/{RETRY_AT}",
    "project_id": None, "root": "/srv/sample-app", "name": "sample-app",
    "title": "Register sample-app", "plan_id": PID, "id": None, "subject": None,
    "headline": "sample-app was not registered: the repository has no origin remote.",
    "why": "Add the repository's origin remote, then choose Retry.",
    "refusal": None, "more_questions": 0,
    "questions": [{"question": "sample-app was not registered: the repository has no origin "
                               "remote.", "options": ["Retry"], "chosen": None,
                   "recommended": None, "recommended_index": None}],
    "values": ["retry"], "items": [], "answers": [], "answered": False,
    "waiting_since": RETRY_AT}


class RetryItemViewTest(unittest.TestCase):
    def test_a_retry_item_is_one_counted_entry_before_plan_questions_and_tracker_items(self):
        shown = derive_view([state("p", 1)], RegisterItemViewTest.decision(self),
                            registration=reg([ASK_A]), retry_items=[RETRY_ITEM])
        self.assertEqual([e["key"] for e in shown["inbox"]["open"]],
                         [RETRY_ITEM["key"], f"register/{PID}/0", "k1"])
        self.assertEqual(shown["statement"]["inbox_items"], 3)
        self.assertEqual(shown["statement"]["headline"], "3 things need you")
        first = shown["inbox"]["open"][0]
        self.assertEqual(first, RETRY_ITEM)
        self.assertIsNot(first, RETRY_ITEM)

    def test_a_retry_item_sets_the_register_sentence(self):
        records = RegisterItemViewTest.decision(self)
        without = derive_view([state("p", 1)], records)
        self.assertEqual(without["statement"]["sentence"], CHOOSE_SENTENCE)
        shown = derive_view([state("p", 1)], records, retry_items=[RETRY_ITEM])
        self.assertEqual(shown["statement"]["sentence"], REGISTER_SENTENCE)

    def test_a_retry_item_needs_no_registered_project(self):
        shown = derive_view([], retry_items=[RETRY_ITEM])
        self.assertEqual(shown["inbox"]["open"], [RETRY_ITEM])
        self.assertEqual(shown["statement"]["inbox_items"], 1)
        self.assertEqual(shown["statement"]["headline"], "1 thing needs you")


APPLY_ITEM = {
    "type": "inbox_item", "reason": "register_apply",
    "key": f"register-apply/{PID}/2026-11-15T08:00:00+00:00",
    "project_id": None, "root": "/srv/sample-app", "name": "sample-app",
    "title": "Register sample-app", "plan_id": PID, "id": None, "subject": None,
    "headline": "Apply this adoption?", "why": None, "lines": ["writes the project contract"],
    "refusal": None, "more_questions": 0,
    "questions": [{"question": "Apply this adoption?", "options": ["Apply it", "Not now"],
                   "chosen": None, "recommended": None, "recommended_index": None}],
    "text": False, "values": ["apply", "not_now"], "items": [], "answers": [],
    "answered": False, "waiting_since": "2026-11-15T08:00:00+00:00"}


class ApplyItemViewTest(unittest.TestCase):
    def test_an_apply_item_is_one_counted_entry_with_the_registration_cards(self):
        shown = derive_view([state("p", 1)], RegisterItemViewTest.decision(self),
                            registration=reg([ASK_A]), retry_items=[RETRY_ITEM],
                            apply_items=[APPLY_ITEM])
        self.assertEqual([e["key"] for e in shown["inbox"]["open"]],
                         [RETRY_ITEM["key"], f"register/{PID}/0", APPLY_ITEM["key"], "k1"])
        self.assertEqual(shown["statement"]["inbox_items"], 4)
        self.assertEqual(shown["statement"]["headline"], "4 things need you")
        third = shown["inbox"]["open"][2]
        self.assertEqual(third, APPLY_ITEM)
        self.assertIsNot(third, APPLY_ITEM)

    def test_an_apply_item_sets_the_register_sentence(self):
        records = RegisterItemViewTest.decision(self)
        without = derive_view([state("p", 1)], records)
        self.assertEqual(without["statement"]["sentence"], CHOOSE_SENTENCE)
        shown = derive_view([state("p", 1)], records, apply_items=[APPLY_ITEM])
        self.assertEqual(shown["statement"]["sentence"], REGISTER_SENTENCE)

    def test_an_apply_item_needs_no_registered_project(self):
        shown = derive_view([], apply_items=[APPLY_ITEM])
        self.assertEqual(shown["inbox"]["open"], [APPLY_ITEM])
        self.assertEqual(shown["statement"]["inbox_items"], 1)
        self.assertEqual(shown["statement"]["headline"], "1 thing needs you")


class ProposedEnvironmentViewTest(unittest.TestCase):
    """The view the owner sees for a ready plan whose checkout proposes a commit environment."""

    LINE = "commits run in its development shell: devenv shell (found in its files)"
    LATEST = {"root": "/srv/sample-app", "plan_id": PID, "state": "ready",
              "at": "2026-11-15T08:00:00+00:00", "project_id": None, "result": "planned",
              "outcome": "changes", "headline": "What adopting sample-app would change.",
              "lines": ["moves 2 agent files under .agents/", "writes the project contract"],
              "note": None, "questions": [], "remote": None}

    def latest(self):
        fields = contract_draft.reconcile_fields("/srv/sample-app", {
            "stranded": ["pre-commit"], "environments": ["devenv.nix"]})
        return {**self.LATEST, "draft": fields}

    def test_an_adopted_registration_offers_no_integration_branch_card(self):
        latest = {**self.LATEST, "result": "drafting", "state": "drafting", "outcome": None,
                  "questions": [{"id": contract_draft.QUESTION_ID, "subject": "integration-branch",
                                 "ask": "Which branch?", "why": "It names the branch.",
                                 "options": [], "text": True}]}
        adoption = {"status": "done", "step": "opened", "state": "merged", "headline": "adopted",
                    "lines": [], "note": None, "branch": None, "commit": None, "url": None}
        self.assertEqual(
            [e["reason"] for e in view._register_entries(register.view_entry(None, latest))],
            ["register"])
        self.assertEqual(
            view._register_entries(register.view_entry(None, latest, adoption=adoption)), [])

    def test_the_ready_apply_card_states_the_proposal_first_and_hides_the_draft(self):
        latest = self.latest()
        items = approve.apply_items(latest, None, None, "approve", deferred=set())
        shown = derive_view([], registration=register.view_entry(None, latest),
                            apply_items=items)
        (card,) = shown["inbox"]["open"]
        self.assertEqual(card["reason"], "register_apply")
        self.assertEqual(card["lines"], [self.LINE, *latest["lines"]])
        self.assertEqual(card["questions"][0]["options"], ["Apply it", "Not now"])
        entry = shown["registration"]
        self.assertEqual((entry["line"], entry["lines"], entry["draft"], entry["draft_more"]),
                         ("Register sample-app: needs you", [], None, None))

    def test_a_reconcile_plan_s_apply_card_states_the_proposal_first(self):
        latest = {**self.LATEST, "outcome": "reconcile", "draft": contract_draft.reconcile_fields(
            "/srv/sample-app", {"hooks": ["pre-commit"], "stranded": ["pre-commit"],
                                "environments": ["devenv.nix"]})}
        items = approve.apply_items(latest, None, None, "approve", deferred=set())
        shown = derive_view([], registration=register.view_entry(None, latest), apply_items=items)
        (card,) = shown["inbox"]["open"]
        self.assertEqual(card["lines"], [self.LINE, *latest["lines"]])
        (row,) = register.view_entry(None, latest)["draft"]
        self.assertEqual((row["field"], row["line"], row["more"]),
                         ("commit-environment", self.LINE, False))
        self.assertIsNone(register.view_entry(None, latest)["draft_more"])

    def test_with_no_card_asking_the_draft_offers_the_proposal_as_a_changeable_line(self):
        latest = self.latest()
        shown = derive_view([], registration=register.view_entry(None, latest))
        self.assertEqual(shown["inbox"]["open"], [])
        rows = {row["field"]: row for row in shown["registration"]["draft"]}
        self.assertEqual(rows["commit-environment"]["line"], self.LINE)
        self.assertIs(rows["commit-environment"]["text"], True)
        self.assertEqual(rows["commit-environment"]["placeholder"],
                         "the development shell command")


class RegisterConfirmTest(unittest.TestCase):
    WAITING = {"by": "owner", "root": "/srv/sample-app", "project_id": None,
               "result": "not_registered", "outcome": "no_change",
               "headline": "sample-app is already adopted and is not registered yet.",
               "lines": [], "note": "Choose Register it to register it.",
               "at": "2026-11-15T08:00:00+00:00"}

    def test_the_register_card_says_what_registering_allows(self):
        items = register.confirm_items(self.WAITING, running=False)
        shown = derive_view([], confirm_items=items)
        (card,) = shown["inbox"]["open"]
        self.assertEqual(card["reason"], "register_confirm")
        self.assertEqual(card["why"], "Registering lets agents run in this folder with the "
                                      "folder's own settings and hooks.")
        self.assertEqual(card["questions"][0]["options"], ["Register it", "Not now"])
        self.assertEqual(card["values"], ["register", "not_now"])
        self.assertEqual(shown["statement"]["inbox_items"], 1)
        self.assertEqual(shown["statement"]["sentence"], REGISTER_SENTENCE)
        self.assertEqual(register.confirm_items(self.WAITING, running=True), [])

    def test_a_behind_card_is_counted_and_the_work_line_says_needs_you(self):
        latest = {**register.behind("/srv/sample-app", 2, False), "at": "2026-11-15T08:00:00+00:00"}
        shown = derive_view([], registration=register.view_entry(None, latest),
                            confirm_items=register.confirm_items(latest, running=False))
        (card,) = shown["inbox"]["open"]
        self.assertEqual(card["reason"], "register_behind")
        self.assertEqual(shown["statement"]["inbox_items"], 1)
        self.assertEqual(shown["statement"]["sentence"], REGISTER_SENTENCE)
        self.assertEqual(shown["registration"]["line"], "Register sample-app: needs you")

    def test_the_remote_sentence_stays_beside_the_needs_you_line(self):
        latest = {**register.unread(register.update_failed("/srv/sample-app",
                                                           "another branch is checked out")),
                  "at": "t"}
        shown = derive_view([], registration=register.view_entry(None, latest),
                            failure_items=register.failure_items(latest, running=False))
        self.assertEqual(shown["registration"]["line"], "Register sample-app: needs you")
        self.assertEqual(shown["registration"]["remote"], register.REMOTE_UNREAD)


class RegisterFailureViewTest(unittest.TestCase):
    ROOT = "/srv/fail-app"

    def test_a_failed_plan_is_one_counted_card_and_the_work_line_says_needs_you(self):
        manifest = {"error": {"code": "x", "repair_id": "adopt.manifest.missing", "violations": [
            {"pointer": "", "message": register.MANIFEST_ABSENT}]}}
        latest = {**register.summary(self.ROOT, manifest), "at": "2026-11-15T08:00:00+00:00"}
        shown = derive_view([], registration=register.view_entry(None, latest),
                            failure_items=register.failure_items(latest, running=False))
        (card,) = shown["inbox"]["open"]
        self.assertEqual(card["reason"], "register_failed")
        self.assertEqual(card["title"], "Register fail-app")
        self.assertEqual(shown["statement"]["inbox_items"], 1)
        self.assertEqual(shown["statement"]["headline"], "1 thing needs you")
        self.assertEqual(shown["statement"]["sentence"], REGISTER_SENTENCE)
        line = shown["registration"]
        self.assertEqual(line["line"], "Register fail-app: needs you")
        self.assertEqual(line["lines"], [])
        self.assertIsNone(line["note"])
        self.assertIsNone(line["adoption"])
        self.assertEqual((card["headline"] + " " + card["why"]).count("not installed"), 1)
        sentences = lambda text: set(text.split(". "))  # noqa: E731
        self.assertEqual(sentences(card["headline"]) & sentences(card["why"]), set())

    def test_an_apply_card_reduces_the_work_line_and_a_plan_question_does_not(self):
        entry = {**reg([]), "root": "/srv/r", "name": "r", "line": "x", "lines": ["writes a"],
                 "note": "n", "adoption": {"status": "done", "headline": "h"}}
        card = {**APPLY_ITEM, "root": "/srv/r"}
        shown = derive_view([], registration=entry, apply_items=[card])["registration"]
        self.assertEqual((shown["line"], shown["lines"], shown["note"], shown["adoption"]),
                         ("Register r: needs you", [], None, None))
        asked = derive_view([], registration={**entry, "questions": [ASK_A]})
        self.assertEqual(asked["inbox"]["open"][0]["reason"], "register")
        self.assertEqual(asked["registration"]["line"], "x")
        self.assertEqual(derive_view([], registration=entry)["registration"], entry)

    def test_a_reduced_registration_keeps_its_cancel(self):
        entry = {**reg([]), "root": "/srv/r", "name": "r", "line": "x", "lines": ["writes a"],
                 "note": "n", "adoption": None, "cancel": True}
        card = {**APPLY_ITEM, "root": "/srv/r"}
        shown = derive_view([], registration=entry, apply_items=[card])["registration"]
        self.assertEqual((shown["line"], shown["cancel"]), ("Register r: needs you", True))
        self.assertTrue(derive_view([], registration=entry)["registration"]["cancel"])

    def test_an_apply_card_clears_the_drafted_settings_beside_the_work_line(self):
        lines = [{"field": "project-id", "line": "Project id: o/r (read from the remote)",
                  "value": "o/r", "options": [], "text": True}]
        entry = {**reg([]), "root": "/srv/r", "name": "r", "line": "x", "lines": ["writes a"],
                 "note": "n", "adoption": None, "draft": lines, "draft_more": "and 1 more setting"}
        card = {**APPLY_ITEM, "root": "/srv/r"}
        shown = derive_view([], registration=entry, apply_items=[card])["registration"]
        self.assertEqual((shown["line"], shown["draft"], shown["draft_more"]),
                         ("Register r: needs you", None, None))
        plain = derive_view([], registration=entry)["registration"]
        self.assertEqual((plain["draft"], plain["draft_more"]), (lines, "and 1 more setting"))

    def test_a_registered_root_leaves_only_its_project_and_digest_line(self):
        opened = step_payload("opened", plan_id="p1", root="/srv/p00", project_id="p00")
        adoption = approve.entry({**opened, "pull_state": "merged", "pull_at": "t",
                                  "at": "t", "registration": {
                                      "result": "registered", "project_id": "p00",
                                      "reason": None, "note": None}},
                                 running=False, name="p00")
        entry = {**reg([]), "root": "/srv/p00", "name": "p00", "project_id": "p00",
                 "line": adoption["headline"], "adoption": adoption}
        moment = Event(1, "2026-11-15T09:00:00+00:00", event_log.ADOPTION_REGISTRATION, None,
                       {"plan_id": "p1", "number": 7, "result": "registered",
                        "project_id": "p00", "reason": None, "note": None})
        d = digest.digest(digest.moments([moment], {}, {}), None,
                          datetime(2026, 11, 15, 10, 0, tzinfo=timezone.utc))
        shown = derive_view([state("p00", 1)], registration=entry, digest=d)
        self.assertIsNone(shown["registration"])
        self.assertEqual([e["project_id"] for e in shown["entries"]], ["p00"])
        self.assertIn("p00 was registered.", [m["sentence"] for m in shown["digest"]["recent"]])
        elsewhere = derive_view([state("p01", 1)], registration=entry)
        self.assertEqual(elsewhere["registration"], entry)

    def test_an_adoption_work_line_is_one_sentence(self):
        opened = step_payload("opened", plan_id="p1", root="/srv/sample-app",
                              branch="adopt-bbbbbbbbbbbb", commit="c" * 40,
                              pull_request={"number": 7,
                                            "url": "https://github.com/o/sample-app/pull/7"})
        adoption = approve.entry({**opened, "at": "t", "pull_state": "open", "pull_at": "t"},
                                 running=False, name="sample-app")
        latest = {**register.summary("/srv/sample-app", plan_doc(state="ready")),
                  "lines": ["moves 1 agent file under .agents/"], "at": "t"}
        entry = register.view_entry(None, latest, adoption=adoption, approve=None)
        shown = derive_view([], registration=entry)["registration"]
        self.assertEqual(len(re.findall(r"[.!?](?=\s|$)", shown["line"])), 1)
        self.assertEqual(shown["lines"], [])

    def test_an_open_pull_request_reads_in_words_and_the_statement_says_adoption_under_way(self):
        opened = step_payload("opened", plan_id="p1", root="/srv/sample-app",
                              branch="adopt-bbbbbbbbbbbb", commit="c" * 40,
                              pull_request={"number": 7,
                                            "url": "https://github.com/o/sample-app/pull/7"})
        adoption = approve.entry({**opened, "at": "t", "pull_state": "open", "pull_at": "t"},
                                 running=False, name="sample-app")
        latest = {**register.summary("/srv/sample-app", plan_doc(state="ready")), "at": "t"}
        entry = register.view_entry(None, latest, adoption=adoption, approve=None)
        shown = derive_view([], registration=entry)
        self.assertEqual(shown["registration"]["line"],
                         "The pull request of sample-app is not ready to merge yet.")
        self.assertEqual(shown["registration"]["adoption"]["lines"], [])
        self.assertEqual(shown["registration"]["adoption"]["url"],
                         "https://github.com/o/sample-app/pull/7")
        text = " ".join([shown["registration"]["line"], *shown["registration"]["adoption"]["lines"]])
        self.assertIsNone(re.search(r"[0-9a-f]{12,}", text))
        self.assertEqual(shown["statement"]["sentence"], ADOPTING_SENTENCE)
        self.assertNotEqual(shown["statement"]["sentence"], "No project is registered yet.")


class TrustItemTest(unittest.TestCase):
    FAILED = {("/home/o/repo", "work"): {
        "root": "/home/o/repo", "project": "repo", "profile": "work",
        "at": "2026-11-15T10:00:00+00:00"}}

    def test_a_failed_profile_is_a_card_with_plain_words(self):
        shown = derive_view([], trust_items=folder_trust.items(self.FAILED))
        (card,) = shown["inbox"]["open"]
        self.assertEqual(card["reason"], "trust_failed")
        self.assertEqual(
            card["why"],
            "Open Claude Code in the repo folder under the work profile, accept its trust prompt "
            "and close it, then choose Check again.")
        self.assertEqual(card["command"], "cd /home/o/repo && CLAUDE_ACCOUNT=work claude")
        self.assertEqual(card["questions"][0]["options"], ["Check again"])
        self.assertEqual(card["values"], ["check"])
        self.assertEqual(shown["statement"]["inbox_items"], 1)
        self.assertEqual(shown["statement"]["sentence"], REGISTER_SENTENCE)


class WaitingLineTest(unittest.TestCase):
    UNTIL = iso(T0_MS + 2 * DAY)
    NAMING = reported(started(A), T0_MS + MIN, issues=((619, "held"),))

    def waiting(self, issue=619, key="k-wait", reason="not_before", until=UNTIL, what="Read the hourly rows.",
                project="p00"):
        return InboxRecord(
            {**item(project, key), "issue": issue, "reason": "verify-wait", "answers": [],
             "url": f"https://example.test/{key}", "wait": {"reason": reason, "until": until, "what": what}},
            "t1", "t1")

    def view_of(self, *records, sprints=True, now_ms=T0_MS, projects=None):
        owned = {(r.item["project_id"], r.item["key"]): r for r in records}
        return derive_view(projects or [state("p00", 1)], owned, now_ms=now_ms,
                           sprints={A: self.NAMING} if sprints else None)

    def test_a_waiting_check_is_a_line_under_its_sprint_and_not_counted(self):
        shown = self.view_of(self.waiting())
        self.assertEqual(shown["statement"]["inbox_items"], 0)
        self.assertEqual(shown["statement"]["headline"], "Nothing needs you")
        self.assertEqual(shown["inbox"]["open"], [])
        self.assertEqual(entry(shown)["waits"], [{
            "key": "k-wait", "issue": 619, "url": "https://example.test/k-wait", "until": self.UNTIL,
            "text": "Read the hourly rows."}])
        self.assertEqual(entry(shown)["waiting"], 0)
        self.assertEqual(shown["entries"][0]["waits"], [])

    def test_a_prompted_waiting_check_becomes_a_card_once_its_time_passes(self):
        check = human({"days_after": {"event": "released", "days": 2}}, "Two days of rows after the release. Count them.")
        key = verify_issues.block_key(10, block_of(check))
        hold = dated_comment(10, hold_body(check), "2026-11-16T08:00:00Z")
        window = dated_comment(11, window_body("released"), "2026-11-16T09:00:00Z")
        prompt = dated_comment(12, prompt_body(key, 0), "2026-11-18T09:15:00Z")
        project = WAIT_PROJECT
        sprint = dataclasses.replace(reported(started(A), T0_MS + MIN, issues=((619, "held"),)), project_id=project)
        records, seq = {}, [0]

        def read(nodes, clock):
            with mock.patch.object(forge_api, "api_get", side_effect=AssertionError("the marker dates the window")):
                items = inbox.read_items(
                    project, WAIT_SLUG, call=lambda argv: tracker_page([held_issue(619, nodes)]), now=lambda: clock)
            events = []
            for kind, owner, payload in inbox_changes(records, project, items):
                seq[0] += 1
                events.append(Event(seq[0], f"t{seq[0]}", kind, owner, payload))
            records.update(inbox_records(events, records))
            for gone in [k for k in records if k[1] not in {i["key"] for i in items}]:
                del records[gone]  # the items of this read are the whole inbox
            return derive_view([state(project, 1)], records, now_ms=T0_MS, sprints={A: sprint})

        first = read([hold, window], datetime(2026, 11, 16, 10, tzinfo=timezone.utc))
        self.assertEqual(first["statement"]["inbox_items"], 0)
        self.assertEqual([(w["until"], w["text"]) for w in entry(first)["waits"]],
                         [("2026-11-18T09:00:00+00:00", "Two days of rows after the release.")])
        second = read([hold, window], datetime(2026, 11, 18, 9, 1, tzinfo=timezone.utc))
        self.assertEqual(second["statement"]["inbox_items"], 0)
        self.assertEqual([(w["until"], w["text"]) for w in entry(second)["waits"]],
                         [(None, "Due now: the next verification pass asks you here")])
        third = read([hold, window, prompt], datetime(2026, 11, 18, 9, 16, tzinfo=timezone.utc))
        self.assertEqual(third["statement"]["inbox_items"], 1)
        self.assertEqual(third["inbox"]["open"][0]["key"], f"{WAIT_SLUG}#619/12")
        self.assertEqual(entry(third)["waits"], [])
        self.assertEqual(third["entries"][0]["waits"], [])

    def test_a_host_clock_past_the_date_keeps_the_line(self):
        shown = self.view_of(self.waiting(), now_ms=T0_MS + 30 * DAY)
        self.assertEqual(shown["statement"]["inbox_items"], 0)
        (wait,) = entry(shown)["waits"]
        self.assertEqual(wait["until"], self.UNTIL)
        self.assertEqual(wait["text"], "Read the hourly rows.")

    def test_an_undated_wait_reads_its_reason(self):
        texts = {
            "not_released": "Waiting for the release to be seen: no release yet includes its merge",
            "no_when": "Waiting with no date: its wording states a wait, but its verify block has no when field "
                       "for that wait",
            "due": "Due now: the next verification pass asks you here",
            "due_command": "Due now: the next verification pass asks you here, "
                           "unless it refuses the command as not a verification command"}
        shown = self.view_of(*(self.waiting(key=f"k-{reason}", reason=reason, until=None) for reason in texts))
        self.assertEqual({w["key"]: (w["until"], w["text"]) for w in entry(shown)["waits"]},
                         {f"k-{reason}": (None, text) for reason, text in texts.items()})
        self.assertEqual([w["key"] for w in entry(shown)["waits"]], sorted(f"k-{r}" for r in texts))
        self.assertEqual(set(WAIT_TEXT), {"window_opening", "not_released", "not_deployed", "ci_not_passed",
                                          "unknown", "no_when", "due", "due_command"})
        self.assertEqual(WAIT_TEXT["window_opening"],
                         "Waiting for the next verification pass to start its wait: what it waits for has been seen")
        self.assertEqual(WAIT_TEXT["not_deployed"], "Waiting for the deploy to be seen: no deploy is known to include its merge")
        self.assertEqual(WAIT_TEXT["ci_not_passed"], "Waiting for a CI run to pass at its commit")
        self.assertEqual(WAIT_TEXT["unknown"], "Waiting: the tracker could not say whether it is due yet")

    def test_a_wait_no_sprint_owns_is_under_its_project(self):
        shown = self.view_of(self.waiting(), sprints=False)
        (project,) = shown["entries"]
        self.assertEqual(project["type"], "project")
        self.assertEqual([w["key"] for w in project["waits"]], ["k-wait"])
        self.assertIs(project["quiet"], False)
        self.assertEqual(shown["statement"]["inbox_items"], 0)

    def test_a_wait_is_under_its_project_once_the_sprint_naming_it_has_ended(self):
        ended = {"stopped": stopped(self.NAMING, T0_MS + 2 * MIN, T0_MS + 2 * MIN),
                 "closing": closed(self.NAMING, T0_MS + 2 * MIN, ((619, "held"),))}
        for how, sprint in ended.items():
            with self.subTest(how):
                shown = derive_view([state("p00", 1)], {("p00", "k-wait"): self.waiting()},
                                    now_ms=T0_MS + 3 * MIN, sprints={A: sprint})
                self.assertEqual(entry(shown)["waits"], [])
                self.assertEqual([w["key"] for w in shown["entries"][0]["waits"]], ["k-wait"])

    def test_a_wait_under_a_sprint_that_does_not_name_its_issue_is_under_its_project(self):
        shown = self.view_of(self.waiting(issue=7))
        self.assertEqual(entry(shown)["waits"], [])
        self.assertEqual([w["key"] for w in shown["entries"][0]["waits"]], ["k-wait"])

    def test_a_project_with_only_a_wait_is_not_folded_into_the_quiet_group(self):
        projects = [state(f"p{n:02d}", n) for n in range(view.FOLD_AFTER + 2)]
        shown = self.view_of(self.waiting(project="p00"), sprints=False, projects=projects)
        self.assertEqual([e["type"] for e in shown["entries"]].count("quiet_group"), 1)
        self.assertEqual(shown["entries"][0]["project_id"], "p00")
        self.assertEqual(shown["entries"][0]["type"], "project")

    def test_a_due_check_is_a_counted_card(self):
        card = InboxRecord({**item("p00", "k-ask"), "issue": 619, "reason": "verify-ask",
                            "answers": ["passed", "failed", "note"]}, "t1", "t1")
        shown = self.view_of(card)
        self.assertEqual(shown["statement"]["inbox_items"], 1)
        self.assertEqual(shown["statement"]["sentence"], ANSWER_SENTENCE)
        self.assertEqual(entry(shown)["waits"], [])


class TrackerReadViewTest(unittest.TestCase):
    READ_AT = "2026-11-16T13:00:00.000000+00:00"
    BEGAN_AT = "2026-11-16T12:59:58.000000+00:00"

    def test_a_project_entry_carries_its_last_tracker_read(self):
        cases = (
            (ReadState(True, self.READ_AT, self.BEGAN_AT),
             {"ok": True, "read_at": self.READ_AT, "began_at": self.BEGAN_AT}),
            (ReadState(True, self.READ_AT), {"ok": True, "read_at": self.READ_AT, "began_at": None}),
            (ReadState(False, None), {"ok": False, "read_at": None, "began_at": None}),
        )
        for read, wire in cases:
            with self.subTest(read=read):
                shown = derive_view([state("p00", 1)], health={"p00": read})
                self.assertEqual(shown["entries"][0]["tracker_read"], wire)
        self.assertIsNone(derive_view([state("p00", 1)])["entries"][0]["tracker_read"])

    def test_an_active_project_entry_carries_its_read_too(self):
        shown = derive_view([state("p00", 1, work=2)],
                            health={"p00": ReadState(True, self.READ_AT)})
        self.assertEqual(shown["entries"][0]["tracker_read"],
                         {"ok": True, "read_at": self.READ_AT, "began_at": None})
        self.assertIsNone(derive_view([state("p00", 1, work=2)])["entries"][0]["tracker_read"])

    def test_a_quiet_project_in_a_group_carries_its_read_too(self):
        projects = [state(f"p{n:02d}", n) for n in range(view.FOLD_AFTER + 2)]
        shown = derive_view(projects, health={"p01": ReadState(True, self.READ_AT)})
        (group,) = [e for e in shown["entries"] if e["type"] == "quiet_group"]
        reads = {p["project_id"]: p["tracker_read"] for p in group["projects"]}
        self.assertEqual(reads["p01"], {"ok": True, "read_at": self.READ_AT, "began_at": None})
        self.assertIsNone(reads["p00"])

    def test_the_read_changes_no_statement(self):
        self.assertEqual(
            derive_view([state("p00", 1)],
                        health={"p00": ReadState(True, self.READ_AT)})["statement"],
            derive_view([state("p00", 1)])["statement"])
