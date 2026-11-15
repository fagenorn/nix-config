"""The console's view (#855): projection, registry diff, ordering and folding, encoding."""

import dataclasses
import json
import re
import unittest
from datetime import datetime, timezone

from agent_tools.claims import forge_markers as fm
from agent_tools.claims import forge_owner_action as foa
from agent_tools.console import digest
from agent_tools.console import contract_draft
from agent_tools.console import approve, folder_trust, inbox, register
from agent_tools.console import view
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
from agent_tools.console.sprints import (
    APPROVED,
    CHANGES,
    NONE,
    Brief,
    Closing,
    Manager,
    Observed,
    PendingStop,
    Question,
    Report,
    SprintState,
    first_line,
    sprint_states,
    sprint_title,
)
from agent_tools.console.view import (
    ADOPTING_SENTENCE,
    ALL_OUT_SENTENCE,
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
)
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)
from .test_console_approve import step_payload
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
              (UNREGISTERED, "a", {}),
              (UNREGISTERED, "c", {})]),
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
                 "state_text": "waiting for an answer in its terminal",
                 "cwd": "/srv/p00", "deliveries": []},
                {"session_id": "s3", "name": "s3",
                 "state": "waiting_permission",
                 "state_text": "waiting for a permission in its terminal",
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
                    "state_text": "waiting for an answer in its terminal",
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
             "summary": "1 issue in delivery: 1 queued, moved just now",
             "moved_at": "1970-01-01T00:00:02+00:00",
             "issues": [{"issue": 860, "stage": "queued", "stage_text": "queued"}]},
            {"run_id": "wf_a", "quiet": False, "moved_text": "moved just now",
             "summary": "2 issues in delivery: 1 building, 1 plan review, moved just now",
             "moved_at": "1970-01-01T00:00:01+00:00",
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
            "issues": [{"issue": 858, "stage": "building", "task": 1, "tasks": 3}]})

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
            "updatedAt": "2026-11-10T09:00:00Z"}


def ask_prompt(extra="Open the staging site.\n\n- [ ] Accept\n- [ ] Reject"):
    return fm.render("owner-action", {"reason": "verify-ask", "block": "10.abc", "check": "0", "host": "mbp"},
                     "AC1: the owner's answer is needed.", extra)


def decision_prompt(extra):
    return fm.render("owner-action", {"reason": "verify-decision", "block": "10.abc", "check": "0",
                                      "on": "fail", "result": "55"}, "AC1 failed: the owner decides.", extra)


def held_node(number, comments):
    return {"__typename": "Issue", "number": number, "issueDependenciesSummary": {"blocking": 0},
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

    def test_a_recommendation_keeps_its_index_when_cut_options_collide(self):
        options = ("o" * 85 + "a", "o" * 85 + "b")
        found = self.asking(Question(7, 0, "t9", False, "Which?", "the slice", options,
                                     options[1]))
        (shown,) = found["questions"]
        self.assertEqual(shown["options"], ["o" * 79 + "…", "o" * 79 + "…"])
        self.assertEqual(shown["recommended_index"], 1)


class BriefViewTest(unittest.TestCase):
    def test_a_waiting_brief_is_one_open_item_counted_in_the_statement(self):
        sid = "a" * 16
        view = derive_view([state("p00", 1)], sprints={sid: briefed(sprint(sid), version=2)})
        self.assertEqual(view["inbox"]["open"], [{
            "type": "inbox_item", "reason": "brief", "key": "brief/" + sid,
            "project_id": "p00", "sprint_id": sid, "title": "Ship the importer",
            "version": 2, "brief": PARTS, "answered": False, "waiting_since": "t9"}])
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
                         ("failed", "could not start a manager: the directory is not trusted",
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
                         "Tell the manager to continue, or withdraw the sprint.")
        bare = dataclasses.replace(with_manager(started(A)), no_progress_at=iso(R))
        self.assertIsNone(line(bare, R + MIN)["inbox"]["open"][0]["last_status"])
        both = dataclasses.replace(stopped, stalled="r", stalled_at=iso(R + 40 * MIN))
        shown = line(both, R + 41 * MIN)
        self.assertEqual([i["reason"] for i in shown["inbox"]["open"]], ["manager", "progress"])
        self.assertEqual(shown["statement"]["sentence"], view.MANAGER_SENTENCE)


class SprintReportViewTest(unittest.TestCase):
    def test_the_line_counts_landed_in_delivery_queued_and_held(self):
        it = reported(started(A), R, issues=SEVEN)
        shown = entry(line(it, T0_MS + 5 * MIN))
        self.assertEqual(shown["progress"],
                         {"landed": 3, "in_delivery": 2, "queued": 2, "held": 0, "total": 7})
        self.assertEqual(shown["progress_text"], "3 of 7 landed, 2 in delivery, 2 queued")
        self.assertEqual(shown["state_text"], "on track")
        self.assertEqual(shown["status"], "two slices are building")
        self.assertEqual(shown["status_at"], iso(R))
        self.assertEqual((shown["next"], shown["milestone"], shown["tracker_url"]),
                         ("start the resume slice", "Importer resumes",
                          "https://github.com/owner/p00/milestone/3"))
        held = reported(started(A), R, issues=SEVEN[:6] + ((7, "held"),))
        shown = entry(line(held, T0_MS + 5 * MIN))
        self.assertEqual(shown["progress_text"],
                         "3 of 7 landed, 2 in delivery, 1 queued, 1 held")
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
                           "recommended_index": options.index(recommended)}],
            "items": [], "answers": [], "answered": False, "waiting_since": T0}


FIRST = question_entry(0, "Which store keeps the checkpoints?", ["sqlite", "files"], "files",
                       "the resume slice")
SECOND = question_entry(1, "May the reader change?", ["yes", "no"], "no", "the reader slice")


class QuestionViewTest(unittest.TestCase):
    def test_each_open_question_is_one_inbox_item_with_its_recommendation(self):
        shown = derive_view([state("p00", 1)], sprints={A: asked(started(A))})
        self.assertEqual(shown["inbox"]["open"], [FIRST, SECOND])
        self.assertEqual(shown["statement"]["inbox_items"], 2)
        self.assertEqual(shown["statement"]["headline"], "2 things need you")
        self.assertEqual(shown["statement"]["sentence"], QUESTION_SENTENCE)
        self.assertEqual(QUESTION_SENTENCE,
                         "Choose an option with its number and press Enter, or answer in your own words.")

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
        self.assertEqual(len(line(waiting, C + MIN + DAY - 1)["inbox"]["open"]), 1)
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
             "text": f"The manager of a withdrawn goal could not be stopped: {reason}; "
                     "trying again"}
            for sid, reason, at in (("b" * 16, "boom", T0), ("e" * 16, "zzz", T0),
                                    ("a" * 16, "late", iso(T0_MS + MIN)))])
        self.assertEqual(derive_view([state("p00", 1)])["unstopped"], [])


class SprintViewTest(unittest.TestCase):
    def test_a_sprint_shows_its_goal_state_and_age(self):
        view = derive_view([state("p00", 1)], sprints={"a" * 16: sprint("a" * 16)},
                           now_ms=T0_MS + 3 * 60_000)
        self.assertEqual(view["entries"][0]["sprints"], [{
            "type": "sprint", "sprint_id": "a" * 16,
            "title": "make the importer resumable", "goal": "make the importer resumable",
            "state": "drafting", "state_text": "drafting the brief", "stated_at": T0,
            "age_text": "stated 3 min ago", "manager_text": "no manager has picked this up",
            "manager_state": "none", "manager_until": None, "retry": True,
            "progress": None, "progress_text": None, "status": None, "status_at": None,
            "next": None, "milestone": None, "tracker_url": None, "issues": [], "waiting": 0,
            "sessions": [], "messages": [], "reach_text": None,
            "stoppable": True, "ended_at": None, "stop_text": None, "closing": None,
            "state_until": None}])

    def test_a_sprint_older_than_two_minutes_says_no_manager_has_picked_it_up(self):
        for now_ms, expected in ((None, None), (T0_MS, None), (T0_MS + 120_000, None),
                                 (T0_MS + 120_001, "no manager has picked this up")):
            with self.subTest(now_ms=now_ms):
                view = derive_view([state("p00", 1)], sprints={"a" * 16: sprint("a" * 16)},
                                   now_ms=now_ms)
                shown = view["entries"][0]["sprints"][0]
                self.assertEqual(shown["manager_text"], expected)
                if now_ms is None:
                    self.assertEqual(shown["age_text"], "stated just now")

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


class SprintMessageViewTest(unittest.TestCase):
    TEXT = "leave the importer's schema alone"

    def test_a_messages_state_moves_from_sent_to_delivered_to_read(self):
        sent_row = messaged_row(3, self.TEXT)
        base = {"id": 3, "kind": "text", "version": None, "text": self.TEXT,
                "at": message_at(3)}
        entry = message_entry(message_rows(sent_row))
        self.assertEqual(entry["messages"], [{
            **base, "state": "sent", "state_text": "sent", "read_at": None, "reply": None,
            "reply_at": None}])
        self.assertIsNone(entry["reach_text"])
        entry = message_entry(message_rows(sent_row, nudged_row(4, 3, True)))
        self.assertEqual(entry["messages"][0]["state"], "delivered")
        self.assertEqual(entry["messages"][0]["state_text"], "delivered")
        entry = message_entry(message_rows(
            sent_row, nudged_row(4, 3, True),
            message_row(5, event_log.SPRINT_READ, {"through": 3})))
        self.assertEqual(entry["messages"][0]["state"], "read")
        self.assertEqual(entry["messages"][0]["state_text"], "read")
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
                         "Try again to start a new manager, or withdraw the sprint.")
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

    def test_an_adoption_item_sets_its_sentence_and_needs_no_registered_project(self):
        shown = derive_view([], adoption_items=[ADOPTION_ITEM])
        self.assertEqual(shown["statement"]["inbox_items"], 1)
        self.assertEqual(shown["statement"]["sentence"],
                         "Open the pull request to merge the adoption.")
        self.assertEqual(shown["inbox"]["open"], [ADOPTION_ITEM])
        self.assertIsNot(shown["inbox"]["open"][0], ADOPTION_ITEM)
        asked_too = derive_view([state("p00", 1)], sprints={A: asked(started(A))},
                                adoption_items=[ADOPTION_ITEM])
        self.assertEqual(asked_too["statement"]["sentence"], view.ADOPTION_SENTENCE)

    def test_a_capacity_without_sign_in_raises_nothing(self):
        shown = derive_view([state("p00", 1)], capacity=out())
        self.assertEqual([e for e in shown["inbox"]["open"] if e["reason"] == "signin"], [])


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
        ask = {"id": "contract-draft", "subject": "project-id",
               "ask": "Which project is this repository?\nIt has no remote that names it: type "
                      "its id, as owner/name.",
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
                   "texts": {"justfile": "build:\n\ttrue\ntest:\n\ttrue\n"}}
        fields = contract_draft.draft("/x/sample-app", reading)
        row = register.drafting("/x/sample-app", fields)
        shown = derive_view([], registration=register.view_entry(
            None, {**row, "at": "2026-11-15T08:00:00+00:00"}))
        entries = shown["registration"]["draft"]
        texts = ([e["line"] for e in entries] + [o["label"] for e in entries for o in e["options"]]
                 + [shown["registration"]["draft_more"]])
        self.assertEqual(len(entries), 29)
        for text in texts:
            for term in ("<num>", "<slug>", "light lane", "hint", "operations path",
                         "rejection path"):
                self.assertNotIn(term, text.lower())
        self.assertEqual(
            shown["registration"]["draft_more"],
            f"and {len(contract_draft.FIELDS) - len(contract_draft.MAIN)} more settings at "
            "their usual values")
        self.assertEqual(shown["registration"]["draft_more"],
                         "and 22 more settings at their usual values")

    def test_a_text_card_carries_the_placeholder_of_its_field(self):
        ask = {"id": "contract-draft", "subject": "project-id",
               "ask": "Which project is this repository?", "options": [],
               "recommended": None, "why": None, "text": True}
        shown = derive_view([], registration=reg([ask, ASK_A]))
        first, second = shown["inbox"]["open"]
        self.assertEqual(first["placeholder"], "owner/name")
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
                         "sample-app: waiting for its pull request to be ready to merge")
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
