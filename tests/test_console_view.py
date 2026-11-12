"""The console's view (#855): projection, registry diff, ordering and folding, encoding."""

import dataclasses
import json
import unittest
from datetime import datetime

from agent_tools.console.deliveries import (
    DELIVERY_GONE,
    DELIVERY_SEEN,
    DeliveryState,
    IssueStage,
    delivery_changes,
    delivery_states,
    seen_payload,
)
from agent_tools.console.event_log import Event
from agent_tools.console.sessions import ENDED, SessionState
from agent_tools.console.capacity import EMPTY
from agent_tools.console.sprints import APPROVED, CHANGES, NONE, Brief, SprintState
from agent_tools.console.view import (
    ALL_OUT_SENTENCE,
    BRIEF_SENTENCE,
    CHOOSE_SENTENCE,
    INBOX_CHANGED,
    INBOX_GONE,
    INBOX_HEALTH,
    INBOX_SEEN,
    NEEDS_SENTENCE,
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
            "type": "unmanaged", "root": "/srv/elsewhere",
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
             "issues": [{"issue": 860, "stage": "queued", "stage_text": "queued"}]},
            {"run_id": "wf_a", "quiet": False, "moved_text": "moved just now",
             "issues": [
                 {"issue": 856, "stage": "building", "stage_text": "building task 3 of 5"},
                 {"issue": 857, "stage": "plan review", "stage_text": "plan review"}]},
        ])
        self.assertEqual([d["run_id"] for d in by_id["s2"]["deliveries"]], ["wf_c"])
        plain = derive_view([state("p00", 1)], sessions=sessions)
        self.assertEqual(view["entries"][0]["outside_sprints"]["summary"],
                         plain["entries"][0]["outside_sprints"]["summary"])

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


if __name__ == "__main__":
    unittest.main()


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
            **open_item, "type": "inbox_item", "waiting_since": "t1",
            "stale": False, "read_at": "u1"})

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


PARTS = {"done": "ship it", "excluded": ["x"], "slices": ["a"], "risks": ["r"], "asks": ["q"]}


def briefed(sprint, version=1, decision=NONE, reply=None, at="t9"):
    return dataclasses.replace(sprint, brief=Brief(version, PARTS, at, decision, reply))


class BriefViewTest(unittest.TestCase):
    def test_a_waiting_brief_is_one_open_item_counted_in_the_statement(self):
        sid = "a" * 16
        view = derive_view([state("p00", 1)], sprints={sid: briefed(sprint(sid), version=2)})
        self.assertEqual(view["inbox"]["open"], [{
            "type": "inbox_item", "reason": "brief", "key": "brief/" + sid,
            "project_id": "p00", "sprint_id": sid, "goal": "make the importer resumable",
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


class SprintViewTest(unittest.TestCase):
    def test_a_sprint_shows_its_goal_state_and_age(self):
        view = derive_view([state("p00", 1)], sprints={"a" * 16: sprint("a" * 16)},
                           now_ms=T0_MS + 3 * 60_000)
        self.assertEqual(view["entries"][0]["sprints"], [{
            "type": "sprint", "sprint_id": "a" * 16, "goal": "make the importer resumable",
            "state": "drafting", "state_text": "drafting the brief", "stated_at": T0,
            "age_text": "stated 3 min ago", "manager_text": "no manager has picked this up"}])

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
