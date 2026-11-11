"""The console answers a decision prompt on the tracker and marks the item answered at once (#862).

Run: just agent-workflow-tests
"""
import json
import tempfile
import time
import unittest
from pathlib import Path

from agent_tools.claims import forge_markers as fm
from agent_tools.console import answer, inbox, service, view
from agent_tools.system.forge_api import ForgeError

from . import console_test_support as support
from .forge_world import ForgeWorld
from .test_console_tracker import Scripted
from .test_forge_owner_action import ISSUE, QUESTIONS, SLUG, box_body, comment

C = 6803141410
QS = [{"question": q["question"], "options": q["options"]} for q in QUESTIONS]
STATE = ["api", f"repos/{SLUG}/issues/{ISSUE}"]
COMMENTS = ["api", "--paginate", "--slurp", f"repos/{SLUG}/issues/{ISSUE}/comments?per_page=100"]


def patches(world):
    return [argv for argv in world.argvs("gh") if "-X" in argv]


class TickOnTrackerTest(unittest.TestCase):
    def setUp(self):
        self.world = ForgeWorld(self)
        self.world.respond_json("gh", STATE, {"number": ISSUE, "state": "open"})

    def test_a_tick_edits_exactly_the_chosen_boxes_as_the_owner(self):
        self.world.comment_store(SLUG, ISSUE, [comment(C, box_body())])
        answer.tick_on_tracker(SLUG, ISSUE, C, QS, [1, 0])
        ticked = box_body(ticks={(0, 1), (1, 0)})
        self.assertEqual(self.world.stored()[0]["body"], ticked)
        self.assertEqual(self.world.argvs("gh"), [
            STATE, COMMENTS,
            ["api", "-X", "PATCH", f"repos/{SLUG}/issues/comments/{C}", "-f", "body=" + ticked]])
        self.assertTrue(all(call["token_visible"] is False for call in self.world.calls()))

    def test_a_closed_parent_is_refused_and_never_edited(self):
        self.world.comment_store(SLUG, ISSUE, [comment(C, box_body())])
        self.world.respond_json("gh", STATE, {"number": ISSUE, "state": "closed"})
        with self.assertRaises(answer.Refused) as caught:
            answer.tick_on_tracker(SLUG, ISSUE, C, QS, [1, 0])
        self.assertEqual(str(caught.exception), answer.CLOSED)
        self.assertEqual(self.world.argvs("gh"), [STATE])
        self.assertEqual(self.world.stored()[0]["body"], box_body())

    def test_an_unreadable_parent_is_a_payload_error(self):
        self.world.comment_store(SLUG, ISSUE, [comment(C, box_body())])
        for value in ([], {"number": ISSUE}, {"state": 1}):
            with self.subTest(value=value):
                self.world.respond_json("gh", STATE, value)
                with self.assertRaises(ForgeError) as caught:
                    answer.tick_on_tracker(SLUG, ISSUE, C, QS, [1, 0])
                self.assertEqual(caught.exception.code, "payload_invalid")
        self.assertEqual(patches(self.world), [])

    def test_an_ended_untrusted_or_missing_prompt_is_refused_and_never_edited(self):
        table = {
            "ended": [comment(C, box_body()), comment(C + 1, fm.end_body(C, "resolved"))],
            "untrusted": [comment(C, box_body(), association="NONE")],
            "missing": [comment(C + 5, box_body())],
            "another kind": [comment(C, fm.render(
                "claim", {"issue": str(ISSUE), "reason": "decision", "holder": "h1/b1"}, "Claimed."))],
        }
        for name, comments in table.items():
            with self.subTest(name):
                self.world.comment_store(SLUG, ISSUE, comments)
                with self.assertRaises(answer.Refused) as caught:
                    answer.tick_on_tracker(SLUG, ISSUE, C, QS, [1, 0])
                self.assertEqual(str(caught.exception), answer.GONE)
                self.assertEqual(patches(self.world), [])

    def test_a_changed_prompt_is_refused(self):
        self.world.comment_store(SLUG, ISSUE, [comment(C, box_body())])
        changed = [dict(QS[0], options=[QS[0]["options"][0], "Run it on host three."]), QS[1]]
        with self.assertRaises(answer.Refused) as caught:
            answer.tick_on_tracker(SLUG, ISSUE, C, changed, [1, 0])
        self.assertEqual(str(caught.exception), answer.CHANGED)
        self.assertEqual(patches(self.world), [])

    def test_an_answered_prompt_is_refused(self):
        self.world.comment_store(SLUG, ISSUE, [comment(C, box_body(ticks={(0, 0), (1, 0)}))])
        with self.assertRaises(answer.Refused) as caught:
            answer.tick_on_tracker(SLUG, ISSUE, C, QS, [1, 0])
        self.assertEqual(str(caught.exception), answer.ALREADY)
        self.assertEqual(patches(self.world), [])

    def test_a_refused_edit_raises_the_forge_error_and_changes_nothing(self):
        self.world.comment_store(SLUG, ISSUE, [comment(C, box_body())], fail_once=["edit"])
        with self.assertRaises(ForgeError) as caught:
            answer.tick_on_tracker(SLUG, ISSUE, C, QS, [1, 0])
        self.assertEqual(caught.exception.code, "gh_failed")
        self.assertEqual(self.world.stored()[0]["body"], box_body())


def node(number, comment_id, body):
    return {"__typename": "Issue", "number": number, "issueDependenciesSummary": {"blocking": 0},
            "comments": {"totalCount": 1, "nodes": [{
                "fullDatabaseId": str(comment_id), "body": body, "authorAssociation": "OWNER",
                "updatedAt": "2026-11-10T09:00:00Z"}]}}


def items(number, comment_id, body):
    return inbox.items_from_node("owner/p00", SLUG, node(number, comment_id, body))


ITEM = items(ISSUE, C, box_body())[0]
TICKED = items(ISSUE, C, box_body(ticks={(0, 1), (1, 0)}))[0]
ANSWERED = items(ISSUE, C + 1, box_body(ticks={(0, 0), (1, 0)}))[0]
CONFLICT = items(8, C + 2, fm.render(
    "owner-action", {"issue": "8", "reason": "conflict", "holder": "h1/b1"},
    "This pull request conflicts with its base.", "- Merge conflict in flake.lock"))[0]


def view_of(svc):
    return json.loads(svc.view_bytes)


class AnswerServiceTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = Path(tmp.name) / "console" / "events.sqlite3"
        self.registry = Path(tmp.name) / "fleet" / "registry.json"
        self.ticks = []
        self.raise_ = None
        self.inside = None

    def recorder(self, *args):
        self.ticks.append(args)
        if self.inside is not None:
            self.inside()
        if self.raise_ is not None:
            raise self.raise_

    def open(self, tracker):
        support.write_registry(self.registry, support.entries(1))
        svc = service.ConsoleService(
            self.store, self.registry, port=0, tracker=tracker, tick=self.recorder,
            slug_of=lambda root: SLUG, activity=lambda root: time.time(), session_dirs=lambda: [],
            repo_of=lambda cwd: cwd)
        self.addCleanup(svc.close)
        return svc

    def keys(self, svc, section):
        return [i["key"] for i in view_of(svc)["inbox"][section]]

    def test_an_answer_leaves_the_count_at_once_and_the_list_when_consumed(self):
        tracker = Scripted([ITEM], [TICKED], [])
        svc = self.open(tracker)
        svc.poll_tracker()
        self.assertEqual(view_of(svc)["statement"]["inbox_items"], 1)
        svc.answer("owner/p00", ITEM["key"], [1, 0])
        self.assertEqual(len(tracker.calls), 1)
        self.assertEqual(view_of(svc)["statement"]["inbox_items"], 0)
        self.assertEqual(self.keys(svc, "open"), [])
        self.assertEqual(self.keys(svc, "answered"), [ITEM["key"]])
        self.assertEqual(self.ticks, [(SLUG, ISSUE, C, ITEM["questions"], [1, 0])])
        svc.poll_tracker()
        self.assertEqual(view_of(svc)["statement"]["inbox_items"], 0)
        self.assertEqual(self.keys(svc, "open"), [])
        self.assertEqual(self.keys(svc, "answered"), [ITEM["key"]])
        svc.poll_tracker()
        self.assertEqual(self.keys(svc, "open") + self.keys(svc, "answered"), [])

    def test_a_refused_tick_appends_nothing_and_keeps_the_item_open(self):
        for error in (answer.Refused(answer.CHANGED), ForgeError("gh_failed", "HTTP 403")):
            with self.subTest(error=type(error).__name__):
                svc = self.open(Scripted([ITEM]))
                svc.poll_tracker()
                rows, version = support.log_rows(self.store), svc.version
                self.raise_ = error
                with self.assertRaises(type(error)):
                    svc.answer("owner/p00", ITEM["key"], [1, 0])
                self.assertEqual(support.log_rows(self.store), rows)
                self.assertEqual(svc.version, version)
                self.assertEqual(self.keys(svc, "open"), [ITEM["key"]])
                self.raise_ = None
                svc.answer("owner/p00", ITEM["key"], [1, 0])
                self.assertEqual(self.keys(svc, "answered"), [ITEM["key"]])
                svc.close()

    def test_an_answer_the_inbox_cannot_take_never_ticks(self):
        svc = self.open(Scripted([ITEM, ANSWERED, CONFLICT]))
        svc.poll_tracker()
        table = [
            ("owner/p00", ITEM["key"], [2, 0], answer.CHOOSE),
            ("owner/p00", ITEM["key"], [0], answer.CHOOSE),
            ("owner/p00", ITEM["key"], [True, 0], answer.CHOOSE),
            ("owner/p00", ITEM["key"], "10", answer.CHOOSE),
            ("owner/p00", ITEM["key"], (1, 0), answer.CHOOSE),
            ("owner/p00", "octo/widgets#99/1", [0, 0], answer.NOT_OPEN),
            ("owner/p00", ANSWERED["key"], [0, 0], answer.NOT_OPEN),
            ("owner/p00", CONFLICT["key"], [0], answer.NOT_OPEN),
            ("owner/p99", ITEM["key"], [1, 0], answer.NOT_OPEN),
        ]
        for project, key, choices, reason in table:
            with self.subTest(key=key, choices=choices, project=project):
                with self.assertRaises(answer.Refused) as caught:
                    svc.answer(project, key, choices)
                self.assertEqual(str(caught.exception), reason)
        self.assertEqual(self.ticks, [])

    def test_a_second_answer_while_one_is_sending_is_refused(self):
        svc = self.open(Scripted([ITEM]))
        svc.poll_tracker()
        raised = []

        def again():
            self.inside = None
            try:
                svc.answer("owner/p00", ITEM["key"], [1, 0])
            except answer.Refused as error:
                raised.append(error)

        self.inside = again
        svc.answer("owner/p00", ITEM["key"], [1, 0])
        self.assertEqual([str(e) for e in raised], [answer.SENDING])
        self.assertEqual(len(self.ticks), 1)
        self.assertEqual(self.keys(svc, "answered"), [ITEM["key"]])

    def test_the_next_read_of_the_ticked_prompt_appends_nothing(self):
        svc = self.open(Scripted([ITEM], [TICKED]))
        svc.poll_tracker()
        svc.answer("owner/p00", ITEM["key"], [1, 0])
        before = [row for row in support.log_rows(self.store) if row[2] == view.INBOX_CHANGED]
        self.assertEqual(len(before), 1)
        svc.poll_tracker()
        after = [row for row in support.log_rows(self.store) if row[2] == view.INBOX_CHANGED]
        self.assertEqual(after, before)

    def test_a_read_begun_before_the_answer_keeps_it_answered_and_a_later_one_is_authoritative(self):
        calls = []

        def tracker(project_id, slug, *, cancelled):
            calls.append(project_id)
            if len(calls) == 2:
                svc.answer("owner/p00", ITEM["key"], [1, 0])
            return [ITEM]

        svc = self.open(tracker)
        svc.poll_tracker()
        svc.poll_tracker()
        self.assertEqual(self.keys(svc, "answered"), [ITEM["key"]])
        self.assertEqual(view_of(svc)["statement"]["inbox_items"], 0)
        svc.poll_tracker()
        self.assertEqual(self.keys(svc, "open"), [ITEM["key"]])
        self.assertEqual(view_of(svc)["statement"]["inbox_items"], 1)
        self.assertEqual(svc._answered, {})

    def test_a_prompt_that_changed_while_sending_is_not_marked_answered(self):
        svc = self.open(Scripted([ITEM]))
        svc.poll_tracker()
        edited = {**ITEM, "questions": [{**q, "options": [o + " (edited)" for o in q["options"]]}
                                        for q in ITEM["questions"]]}

        def edit_on_tracker():
            self.inside = None
            svc._tracker = Scripted([edited])
            svc.poll_tracker()

        self.inside = edit_on_tracker
        svc.answer("owner/p00", ITEM["key"], [1, 0])
        self.assertEqual(self.keys(svc, "open"), [ITEM["key"]])
        self.assertEqual(self.keys(svc, "answered"), [])

    def test_the_tick_runs_outside_the_ingest_lock(self):
        svc = self.open(Scripted([ITEM]))
        svc.poll_tracker()
        free = []

        def probe():
            free.append(svc._ingest.acquire(blocking=False))
            if free[-1]:
                svc._ingest.release()

        self.inside = probe
        svc.answer("owner/p00", ITEM["key"], [1, 0])
        self.assertEqual(free, [True])


if __name__ == "__main__":
    unittest.main()
