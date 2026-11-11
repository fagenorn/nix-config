"""The console's view (#855): projection, registry diff, ordering and folding, encoding."""

import unittest

from agent_tools.console.event_log import Event
from agent_tools.console.sessions import ENDED, SessionState
from agent_tools.console.view import (
    REGISTERED,
    UNREGISTERED,
    ProjectState,
    derive_view,
    encode_view,
    project_for,
    project_states,
    registry_changes,
)


def state(pid, seq, work=0):
    return ProjectState(pid, f"/srv/{pid}", seq, f"t{seq}", work)


def event(seq, kind, project, payload=None):
    return Event(seq, f"t{seq}", kind, project, payload or {})


def session(sid, state, repo="/srv/p00", seq=1, name=None):
    return SessionState(sid, repo, repo, state, name, seq, f"t{seq}", None)


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
                })
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
        "sentence": "1 registered project, and nothing is waiting on you."}

    def test_a_projects_sessions_form_its_outside_sprints_line(self):
        sessions = [
            session("s1", "working", seq=2),
            session("s2", "waiting_answer", seq=3, name="n2"),
            session("s3", "waiting_permission", seq=4),
            session("s4", "idle", seq=5),
            session("s5", "limit", seq=6),
        ]
        line = derive_view([state("p00", 1)], sessions)["entries"][0][
            "outside_sprints"]
        self.assertEqual(line, {
            "label": "Outside sprints",
            "working": 1,
            "waiting": 2,
            "summary": "1 working, 2 waiting, 1 stopped on a usage limit, 1 idle",
            "sessions": [
                {"session_id": "s2", "name": "n2", "state": "waiting_answer",
                 "state_text": "waiting for an answer in its terminal",
                 "cwd": "/srv/p00"},
                {"session_id": "s3", "name": "s3",
                 "state": "waiting_permission",
                 "state_text": "waiting for a permission in its terminal",
                 "cwd": "/srv/p00"},
                {"session_id": "s1", "name": "s1", "state": "working",
                 "state_text": "working", "cwd": "/srv/p00"},
                {"session_id": "s5", "name": "s5", "state": "limit",
                 "state_text": "stopped on a usage limit", "cwd": "/srv/p00"},
                {"session_id": "s4", "name": "s4", "state": "idle",
                 "state_text": "idle", "cwd": "/srv/p00"},
            ],
        })

    def test_a_session_name_is_its_first_eight_characters_without_one(self):
        line = derive_view([state("p00", 1)], [
            session("0123456789abcdef", "idle")])["entries"][0][
                "outside_sprints"]
        self.assertEqual(line["sessions"][0]["name"], "01234567")

    def test_sessions_of_one_state_order_by_newest_seq_then_id(self):
        sessions = [session("b", "idle", seq=3), session("a", "idle", seq=3),
                    session("c", "idle", seq=9)]
        line = derive_view([state("p00", 1)], sessions)["entries"][0][
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
        view = derive_view([state("p00", 1)], [s9])
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
                    "cwd": "/srv/elsewhere"}]}}])
        self.assertEqual(view["statement"], self.NO_SESSION_STATEMENT)
        self.assertEqual(view["project_count"], 1)
        self.assertEqual(view["entries"][0]["outside_sprints"]["sessions"], [])

    def test_unmanaged_repositories_are_sorted_by_root(self):
        view = derive_view([], [session("s1", "idle", repo="/srv/b"),
                                session("s2", "idle", repo="/srv/a"),
                                session("s3", "idle", repo="/srv/b")])
        self.assertEqual([u["root"] for u in view["unmanaged"]],
                         ["/srv/a", "/srv/b"])
        self.assertEqual(view["unmanaged"][1]["outside_sprints"]["summary"],
                         "2 idle")

    def test_a_waiting_session_is_not_an_inbox_item(self):
        view = derive_view([state("p00", 1)],
                           [session("s1", "waiting_permission")])
        self.assertEqual(view["statement"], self.NO_SESSION_STATEMENT)

    def test_a_project_with_a_live_session_is_not_quiet(self):
        states = [state(f"p0{i}", i + 1) for i in range(5)]
        view = derive_view(states, [session("s1", "idle")])
        entries = view["entries"]
        self.assertEqual([e["type"] for e in entries],
                         ["project", "quiet_group"])
        self.assertEqual(entries[0]["project_id"], "p00")
        self.assertIs(entries[0]["quiet"], False)
        self.assertEqual(entries[1]["count"], 4)

    def test_an_empty_fleet_still_lists_unmanaged_sessions(self):
        view = derive_view([], [session("s1", "working", repo="/srv/x")])
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
        view = derive_view([state("p00", 1)], [s7])
        self.assertEqual(view["unmanaged"], [])
        line = view["entries"][0]["outside_sprints"]
        self.assertEqual(line["sessions"], [])
        self.assertEqual(line["summary"], "No sessions")
        self.assertEqual(view["statement"], self.NO_SESSION_STATEMENT)

    def test_an_ended_session_is_not_listed(self):
        view = derive_view([state("p00", 1)], [session("s8", ENDED)])
        entry = view["entries"][0]
        self.assertEqual(entry["outside_sprints"]["summary"], "No sessions")
        self.assertIs(entry["quiet"], True)
        self.assertEqual(view["unmanaged"], [])


class EncodeTest(unittest.TestCase):
    def test_the_view_encodes_as_compact_sorted_json(self):
        self.assertEqual(encode_view({"b": 1, "a": "é"}),
                         '{"a":"é","b":1}'.encode("utf-8"))
        self.assertNotIn(b"\n", encode_view(derive_view([state("x\ny", 1)])))


if __name__ == "__main__":
    unittest.main()
