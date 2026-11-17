"""A manager that fails to start is shown in plain words, never as the raw reason (#1182)."""

import dataclasses
import unittest

from datetime import datetime

from agent_tools.console import event_log, manager, view
from agent_tools.console.event_log import Event
from agent_tools.console.sprints import APPROVED, NOW_FAILED_START_TEXT, Manager, sprint_states
from agent_tools.console.view import InboxRecord, MANAGER_SENTENCE, derive_view, encode_view

from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)
from .test_console_view import T0, T0_MS, briefed, item, session, sprint, state

SID = "a" * 16
NAME = "p00 sprint " + SID
PLAIN = "this account does not trust the project's folder"
GOAL = "make the importer resumable"
RAW = ("Workspace not trusted. Run `claude` in /home/anis/Projects/jarbird once and accept "
       "the trust prompt, then retry.")

UNTRUSTED_TEXT = "this account does not trust the project's folder"
NOT_INSTALLED_TEXT = "a program the manager needs is missing on this host"
SLOW_TEXT = "the launch did not answer in time"
NO_FOLDER_TEXT = "the project's folder is missing"
SETTINGS_TEXT = "the console could not write the manager's settings"
SECRET_TEXT = "the sprint's secret is missing"
REFUSED_TEXT = "the client refused to start the manager"

LAUNCH_FAILURES = (
    ("the project root /srv/p00 is not a directory", NO_FOLDER_TEXT),
    ("cannot write the manager's settings: Permission denied", SETTINGS_TEXT),
    ("systemd-run is not installed", NOT_INSTALLED_TEXT),
    ("the launch did not return within 30 s", SLOW_TEXT),
    ("the sprint's secret is missing", SECRET_TEXT),
    (manager.UNAVAILABLE_TEXT, manager.UNAVAILABLE_TEXT),
    ("error: the directory is not trusted", UNTRUSTED_TEXT),
    ("the launch exited 3", REFUSED_TEXT),
    ("OSError: [Errno 2] No such file: '/tmp/x'", REFUSED_TEXT),
    ("", REFUSED_TEXT),
    (None, REFUSED_TEXT),
    ("systemd-run is not installed; the directory is not trusted", UNTRUSTED_TEXT),
)


class PlainReasonTest(unittest.TestCase):
    def test_the_16_nov_refusal_reads_as_an_untrusted_folder(self):
        said = manager.plain_reason(RAW)
        self.assertEqual(said, UNTRUSTED_TEXT)
        for leak in ("/", "Workspace not trusted", "claude"):
            self.assertNotIn(leak, said)

    def test_each_launch_failure_has_its_plain_words(self):
        for raw, expected in LAUNCH_FAILURES:
            with self.subTest(raw=raw):
                self.assertEqual(manager.plain_reason(raw), expected)

    def test_no_plain_reason_names_a_path_or_echoes_its_input(self):
        for raw in (RAW, *(raw for raw, _ in LAUNCH_FAILURES)):
            with self.subTest(raw=raw):
                said = manager.plain_reason(raw)
                self.assertIn(said, manager.PLAIN_TEXTS)
                self.assertNotIn("/", said)
                self.assertTrue(said != raw or raw in manager.PLAIN_TEXTS)
        self.assertEqual(len(set(manager.PLAIN_TEXTS)), len(manager.PLAIN_TEXTS))
        for text in manager.PLAIN_TEXTS:
            with self.subTest(text=text):
                self.assertNotIn("/", text)
                self.assertNotIn("stalled", text)

    def test_the_raw_reason_reaches_no_member_of_the_view(self):
        plain = ("failed", "could not start a manager: " + UNTRUSTED_TEXT, True)
        first = dataclasses.replace(sprint(SID), manager=Manager("failed", T0, reason=RAW))
        takeover = dataclasses.replace(
            briefed(sprint(SID), decision=APPROVED, at=T0),
            manager=Manager("failed", T0, reason=RAW, takeover=True))
        for name, row in (("a first launch", first), ("a takeover", takeover)):
            with self.subTest(name):
                shown = derive_view([state("p00", 1)], sprints={SID: row},
                                    now_ms=T0_MS + 60_000)
                text = encode_view(shown).decode()
                entry = shown["entries"][0]["sprints"][0]
                self.assertEqual(
                    (entry["manager_state"], entry["manager_text"], entry["retry"]), plain)
                self.assertNotIn("/home/anis/Projects/jarbird", text)
                self.assertNotIn("Workspace not trusted", text)


def failed(s, reason=RAW, at=T0, takeover=False):
    return dataclasses.replace(s, manager=Manager("failed", at, reason=reason, takeover=takeover))


def row(seq, kind, **payload):
    return Event(seq, f"2026-11-12T10:0{seq}:00.000000+00:00", kind, "p00", payload)


def keys(shown):
    return [e["key"] for e in shown["inbox"]["open"]]


def card_keys(shown):
    return [k for k in keys(shown) if k.startswith("failed-start/")]


def sprint_entry(shown):
    return shown["entries"][0]["sprints"][0]


class FailedStartCardTest(unittest.TestCase):
    def test_a_failed_first_launch_is_one_counted_card_with_plain_words(self):
        shown = derive_view([state("p00", 1)], sprints={SID: failed(sprint(SID))},
                            now_ms=T0_MS + 60_000)
        self.assertEqual(shown["inbox"]["open"], [{
            "type": "inbox_item", "reason": "failed_start", "key": "failed-start/" + SID,
            "project_id": "p00", "sprint_id": SID, "title": GOAL,
            "headline": "The manager for " + GOAL + " failed to start.", "last_reason": PLAIN,
            "answered": False, "waiting_since": T0}])
        self.assertEqual(shown["statement"]["inbox_items"], 1)
        self.assertEqual(shown["statement"]["headline"], "1 thing needs you")
        self.assertEqual(shown["statement"]["sentence"], view.FAILED_START_SENTENCE)
        self.assertEqual(view.FAILED_START_SENTENCE,
                         "Retry to start the manager, or drop the sprint.")

    def test_the_headline_is_one_sentence_whatever_stop_the_title_ends_in(self):
        for goal in ("Add resumable uploads. Keep the old route.", "Add resumable uploads!",
                     "Add resumable uploads? Soon.", "Add resumable uploads"):
            with self.subTest(goal=goal):
                shown = derive_view([state("p00", 1)],
                                    sprints={SID: failed(sprint(SID, goal=goal))},
                                    now_ms=T0_MS + 60_000)
                self.assertEqual(shown["inbox"]["open"][0]["headline"],
                                 "The manager for Add resumable uploads failed to start.")

    def test_its_line_reads_failed_to_start_and_waits_on_the_owner(self):
        shown = derive_view([state("p00", 1)], sprints={SID: failed(sprint(SID))},
                            now_ms=T0_MS + 60_000)
        line = sprint_entry(shown)
        self.assertEqual(line["now_text"], "waiting for you: the manager failed to start")
        self.assertEqual(line["now_text"], NOW_FAILED_START_TEXT)
        self.assertEqual((line["ball"], line["ball_text"]), ("owner", "waiting on you"))
        self.assertEqual((line["state"], line["state_text"]), ("drafting", "drafting the brief"))
        self.assertEqual((line["manager_state"], line["retry"]), ("failed", True))

    def test_a_later_start_a_withdrawal_or_a_brief_removes_the_card_and_restores_the_line(self):
        base = [row(1, event_log.GOAL_STATED, sprint_id=SID, goal=GOAL),
                row(2, event_log.MANAGER_FAILED, sprint_id=SID, reason=RAW)]
        self.assertEqual(
            card_keys(derive_view([state("p00", 1)], sprints=sprint_states(base),
                                  now_ms=T0_MS + 5 * 60_000)), ["failed-start/" + SID])
        with self.subTest("a later start"):
            later = row(3, event_log.MANAGER_STARTED, sprint_id=SID, profile="work",
                        session_name=NAME)
            at = int(datetime.fromisoformat(later.at).timestamp() * 1000) + 60_000
            shown = derive_view([state("p00", 1)], sprints=sprint_states([*base, later]),
                                now_ms=at)
            self.assertEqual(shown["inbox"]["open"], [])
            self.assertEqual(shown["statement"]["inbox_items"], 0)
            line = sprint_entry(shown)
            self.assertEqual(line["now_text"], "drafting the brief")
            self.assertEqual(line["manager_state"], "started")
            self.assertEqual(line["ball"], "manager")
        with self.subTest("a withdrawal"):
            gone = row(3, event_log.GOAL_WITHDRAWN, sprint_id=SID, goal=GOAL)
            shown = derive_view([state("p00", 1)], sprints=sprint_states([*base, gone]),
                                now_ms=T0_MS + 5 * 60_000)
            self.assertEqual(shown["inbox"]["open"], [])
            self.assertEqual(shown["statement"]["inbox_items"], 0)
            self.assertEqual(shown["entries"][0]["sprints"], [])
        with self.subTest("a brief"):
            shown = derive_view([state("p00", 1)],
                                sprints={SID: briefed(failed(sprint(SID)))},
                                now_ms=T0_MS + 60_000)
            self.assertEqual(keys(shown), ["brief/" + SID])
            line = sprint_entry(shown)
            self.assertEqual(line["now_text"], "waiting for your approval of the brief")
            self.assertFalse(line["retry"])

    def test_no_card_while_a_retry_is_not_offered_or_is_not_the_owners(self):
        now = T0_MS + 60_000
        only = failed(sprint(SID))
        self.assertEqual(
            card_keys(derive_view([state("p00", 1)], sprints={SID: only}, now_ms=now)),
            ["failed-start/" + SID])
        cases = {
            "an own listed session": dict(sprints={SID: only},
                                          sessions=[session("m1", "idle", name=NAME)]),
            "a takeover": dict(sprints={SID: failed(
                briefed(sprint(SID), decision=APPROVED, at=T0), takeover=True)}),
            "a takeover with no brief": dict(sprints={SID: failed(sprint(SID), takeover=True)}),
            "no managers": dict(sprints={SID: only}, managers=False),
            "a stop": dict(sprints={SID: dataclasses.replace(only, stop_at=T0)}),
            "a stall": dict(sprints={SID: dataclasses.replace(only, stalled="r", stalled_at=T0)}),
            "a quota wait": dict(sprints={SID: dataclasses.replace(
                sprint(SID), manager=Manager("waiting", T0, until=None))}),
            "an unregistered project": dict(sprints={SID: failed(sprint(SID, pid="p09"))}),
        }
        for name, extra in cases.items():
            with self.subTest(name):
                shown = derive_view([state("p00", 1)], now_ms=now, **extra)
                self.assertEqual(card_keys(shown), [])
                if name == "a stall":
                    self.assertEqual(keys(shown), ["manager/" + SID])
                if name == "an unregistered project":
                    self.assertEqual(shown["statement"]["inbox_items"], 0)
                    continue
                line = sprint_entry(shown)
                self.assertNotEqual(line["now_text"], NOW_FAILED_START_TEXT)
                if name == "an own listed session":
                    self.assertEqual(line["ball"], "manager")
                if name == "no managers":
                    self.assertEqual(line["now_text"], "drafting the brief")

    def test_cards_follow_stalls_and_precede_progress_and_tracker_items(self):
        a, b, c, d = "a" * 16, "b" * 16, "c" * 16, "d" * 16
        records = {("p00", "k1"): InboxRecord(item("p00", "k1", held=9), "t1", "u1")}
        sprints = {
            a: dataclasses.replace(sprint(a), stalled="r", stalled_at="t5"),
            b: failed(sprint(b)),
            c: dataclasses.replace(sprint(c), no_progress_at="t1"),
            d: failed(sprint(d), at="2026-11-12T09:00:00.000000+00:00")}
        shown = derive_view([state("p00", 1)], records, sprints=sprints, now_ms=T0_MS + 60_000)
        self.assertEqual(keys(shown), ["manager/" + a, "failed-start/" + d, "failed-start/" + b,
                                       "progress/" + c, "k1"])
        self.assertEqual(shown["statement"]["inbox_items"], 5)
        self.assertEqual(shown["statement"]["sentence"], MANAGER_SENTENCE)
        del sprints[a]
        shown = derive_view([state("p00", 1)], records, sprints=sprints, now_ms=T0_MS + 60_000)
        self.assertEqual(shown["statement"]["sentence"], view.FAILED_START_SENTENCE)


if __name__ == "__main__":
    unittest.main()
