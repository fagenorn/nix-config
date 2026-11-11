"""The console's view (#855): projection, registry diff, ordering and folding, encoding."""

import unittest

from agent_tools.console.event_log import Event
from agent_tools.console.view import (
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
    project_states,
    read_states,
    registry_changes,
)


def state(pid, seq, work=0):
    return ProjectState(pid, f"/srv/{pid}", seq, f"t{seq}", work)


def event(seq, kind, project, payload=None):
    return Event(seq, f"t{seq}", kind, project, payload or {})


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
