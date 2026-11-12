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
from agent_tools.verification import verify_answer

from . import console_test_support as support
from .forge_world import ForgeWorld
from .test_console_inbox import act, approve, ask
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


P = "owner/p00"
NOTE = "The login page loads, but slowly.\nSecond line: naïve ✓"
CHECKS = {n: items(n, C + n, body)[0] for n, body in (
    (7, ask()), (8, ask()), (9, ask()), (10, approve("paid")), (11, act()), (12, approve()))}
ASK7, ASK8, ASK9, PAID10, ACT11, LIVE12 = (CHECKS[n] for n in (7, 8, 9, 10, 11, 12))
ALL_CHECKS = list(CHECKS.values())


class CheckAnswerServiceTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = Path(tmp.name) / "state/console/events.sqlite3"
        self.registry = Path(tmp.name) / "fleet" / "registry.json"
        self.calls = []
        self.raise_ = None
        self.inside = None

    def recorder(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if self.inside is not None:
            self.inside()
        if self.raise_ is not None:
            raise self.raise_

    def make(self, tracker, **kwargs):
        support.write_registry(self.registry, support.entries(1))
        svc = service.ConsoleService(
            self.store, self.registry, port=0, tracker=tracker, owner_path=self.recorder,
            slug_of=lambda root: SLUG, activity=lambda root: time.time(), session_dirs=lambda: [],
            profile_dirs=lambda: [], repo_of=lambda cwd: cwd,
            branch_pattern_of=lambda repo: "issue-<num>-<slug>", **kwargs)
        self.addCleanup(svc.close)
        return svc

    def open(self, tracker):
        return self.make(tracker)

    def serve(self, items):
        svc = self.make(Scripted(items), tracker_seconds=3600)
        svc.poll_tracker()
        svc.start()
        self.headers = {"Origin": f"http://127.0.0.1:{svc.address[1]}",
                        "X-Console-Token": (self.store.parent / "page-token").read_text().strip(),
                        "Content-Type": "application/json"}
        return svc

    def keys(self, svc, section):
        return [i["key"] for i in view_of(svc)["inbox"][section]]

    def test_passed_failed_and_note_reach_the_owner_path_unchanged(self):
        svc = self.serve([ASK7, ASK8, ASK9])
        svc.answer_check(P, ASK7["key"], "passed", ASK7["version"])
        svc.answer_check(P, ASK8["key"], "failed", ASK8["version"])
        svc.answer_check(P, ASK9["key"], "note", ASK9["version"], note=NOTE)
        body = json.dumps({"project_id": P, "key": ASK9["key"], "answer": "note", "version": ASK9["version"],
                           "note": NOTE}).encode()
        got = support.post_page(svc.address, "/api/check-answer", self.headers, body)
        self.assertEqual((got[0], got[2]), (204, b""))
        self.assertEqual(self.calls, [
            ((SLUG, 7, C + 7, "passed"), {"version": ASK7["version"], "note": None, "paid": False}),
            ((SLUG, 8, C + 8, "failed"), {"version": ASK8["version"], "note": None, "paid": False}),
            ((SLUG, 9, C + 9, "note"), {"version": ASK9["version"], "note": NOTE, "paid": False}),
            ((SLUG, 9, C + 9, "note"), {"version": ASK9["version"], "note": NOTE, "paid": False})])

    def test_a_paid_approval_without_its_typed_confirmation_is_refused(self):
        svc = self.open(Scripted([PAID10, LIVE12]))
        svc.poll_tracker()
        rows = [(PAID10, c) for c in (None, "", "Octo/widgets#10", "octo/widgets#10 ", "octo/widgets#1")]
        rows += [(LIVE12, c) for c in (None, "octo/widgets#1")]
        for item, confirm in rows:
            with self.subTest(key=item["key"], confirm=confirm):
                with self.assertRaises(answer.Refused) as caught:
                    svc.answer_check(P, item["key"], "approve", item["version"], confirm=confirm)
                self.assertEqual(str(caught.exception), answer.CONFIRM)
        bare = self.open(Scripted([{**LIVE12, "confirm": ""}]))
        bare.poll_tracker()
        with self.assertRaises(answer.Refused) as caught:
            bare.answer_check(P, LIVE12["key"], "approve", LIVE12["version"], confirm="")
        self.assertEqual(str(caught.exception), answer.CONFIRM)
        self.assertEqual(self.calls, [])
        svc.answer_check(P, PAID10["key"], "approve", PAID10["version"], confirm="octo/widgets#10")
        svc.answer_check(P, LIVE12["key"], "approve", LIVE12["version"], confirm="octo/widgets#12")
        self.assertEqual(self.calls, [
            ((SLUG, 10, C + 10, "approve"), {"version": PAID10["version"], "note": None, "paid": True}),
            ((SLUG, 12, C + 12, "approve"), {"version": LIVE12["version"], "note": None, "paid": False})])

    def test_a_paid_approval_is_excluded_from_any_multi_item_action(self):
        self.assertEqual(service.PAGE_WRITES, {"/api/looked", "/api/answer", "/api/check-answer",
                                               "/api/goal", "/api/withdraw", "/api/approve",
                                               "/api/reply", "/api/retry-manager",
                                               "/api/message", "/api/stop", "/api/round-answer",
                                               "/api/continue"})
        keys = [PAID10["key"], LIVE12["key"]]
        single = {"project_id": P, "key": LIVE12["key"], "answer": "approve", "version": LIVE12["version"],
                  "confirm": "octo/widgets#12"}
        several = [
            {**single, "key": keys, "confirm": "octo/widgets#10"},
            {**single, "items": [{"project_id": P, "key": LIVE12["key"]}]},
            [single, {**single, "key": PAID10["key"]}]]
        for body in several:
            with self.subTest(body=body):
                with self.assertRaises(ValueError):
                    answer.parse_check_request(json.dumps(body).encode())
        svc = self.serve([PAID10, LIVE12])
        got = support.post_page(svc.address, "/api/check-answer", self.headers, json.dumps(several[0]).encode())
        self.assertEqual((got[0], got[2]), (400, b"bad answer\n"))
        self.assertEqual(self.calls, [])
        self.assertEqual(sorted(self.keys(svc, "open")), sorted(keys))

    def test_an_answer_the_item_cannot_take_never_reaches_the_owner_path(self):
        decision = {**ASK7, "key": "octo/widgets#20/1", "answers": []}
        svc = self.open(Scripted([ASK7, ACT11, decision]))
        svc.poll_tracker()
        table = [
            (P, ASK7["key"], "keep", answer.NOT_AN_ANSWER),
            (P, ACT11["key"], "passed", answer.NOT_OPEN),
            (P, "octo/widgets#99/1", "passed", answer.NOT_OPEN),
            ("owner/p99", ASK7["key"], "passed", answer.NOT_OPEN),
            (P, decision["key"], "passed", answer.NOT_OPEN)]
        for project, key, word, reason in table:
            with self.subTest(key=key, word=word, project=project):
                with self.assertRaises(answer.Refused) as caught:
                    svc.answer_check(project, key, word, "any")
                self.assertEqual(str(caught.exception), reason)
        self.assertEqual(self.calls, [])

    def test_a_sent_answer_leaves_the_count_and_a_note_does_not(self):
        svc = self.open(Scripted([ASK7, ASK8]))
        svc.poll_tracker()
        self.assertEqual(view_of(svc)["statement"]["inbox_items"], 2)
        svc.answer_check(P, ASK7["key"], "passed", ASK7["version"])
        self.assertEqual(self.keys(svc, "answered"), [ASK7["key"]])
        self.assertEqual(view_of(svc)["statement"]["inbox_items"], 1)
        rows = support.log_rows(self.store)
        svc.answer_check(P, ASK8["key"], "note", ASK8["version"], note=NOTE)
        self.assertEqual(support.log_rows(self.store), rows)
        self.assertEqual(self.keys(svc, "open"), [ASK8["key"]])
        self.assertEqual(view_of(svc)["statement"]["inbox_items"], 1)

    def test_a_read_begun_before_a_sent_answer_keeps_it_answered(self):
        calls = []

        def tracker(project_id, slug, *, cancelled):
            calls.append(project_id)
            if len(calls) == 2:
                svc.answer_check(P, ASK7["key"], "passed", ASK7["version"])
            return [ASK7]

        svc = self.open(tracker)
        svc.poll_tracker()
        svc.poll_tracker()
        self.assertEqual(self.keys(svc, "answered"), [ASK7["key"]])
        svc.poll_tracker()
        self.assertEqual(self.keys(svc, "open"), [ASK7["key"]])

    def test_a_refused_owner_path_appends_nothing(self):
        for error in (verify_answer.Refused(verify_answer.ALREADY), ForgeError("gh_failed", "HTTP 403")):
            with self.subTest(error=type(error).__name__):
                svc = self.open(Scripted([ASK7]))
                svc.poll_tracker()
                rows, version = support.log_rows(self.store), svc.version
                self.raise_ = error
                with self.assertRaises(type(error)):
                    svc.answer_check(P, ASK7["key"], "passed", ASK7["version"])
                self.assertEqual(support.log_rows(self.store), rows)
                self.assertEqual(svc.version, version)
                self.assertEqual(self.keys(svc, "open"), [ASK7["key"]])
                svc.close()

    def test_the_owner_path_runs_outside_the_ingest_lock(self):
        svc = self.open(Scripted([ASK7]))
        svc.poll_tracker()
        free = []

        def probe():
            free.append(svc._ingest.acquire(blocking=False))
            if free[-1]:
                svc._ingest.release()

        self.inside = probe
        svc.answer_check(P, ASK7["key"], "passed", ASK7["version"])
        self.assertEqual(free, [True])

    def test_a_second_answer_while_one_is_sending_is_refused(self):
        svc = self.open(Scripted([ASK7]))
        svc.poll_tracker()
        raised = []

        def again():
            self.inside = None
            try:
                svc.answer_check(P, ASK7["key"], "passed", ASK7["version"])
            except answer.Refused as error:
                raised.append(error)

        self.inside = again
        svc.answer_check(P, ASK7["key"], "passed", ASK7["version"])
        self.assertEqual([str(e) for e in raised], [answer.SENDING])
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.keys(svc, "answered"), [ASK7["key"]])


class ParseCheckRequestTest(unittest.TestCase):
    BASE = {"project_id": P, "key": "octo/widgets#7/1", "answer": "passed", "version": "v1"}

    def parse(self, value):
        return answer.parse_check_request(value if isinstance(value, bytes) else json.dumps(value).encode())

    def test_valid_bodies_round_trip(self):
        self.assertEqual(self.parse(self.BASE), (P, "octo/widgets#7/1", "passed", "v1", None, None))
        self.assertEqual(self.parse({**self.BASE, "answer": "note", "note": NOTE}),
                         (P, "octo/widgets#7/1", "note", "v1", NOTE, None))
        self.assertEqual(self.parse({**self.BASE, "answer": "approve", "confirm": "octo/widgets#7"}),
                         (P, "octo/widgets#7/1", "approve", "v1", None, "octo/widgets#7"))
        for word in answer.CHECK_ANSWERS:
            if word != "note":
                self.assertEqual(self.parse({**self.BASE, "answer": word})[2], word)
        self.assertEqual(self.parse({**self.BASE, "confirm": "x" * 200})[5], "x" * 200)

    def test_anything_else_is_a_value_error(self):
        no_answer = {k: v for k, v in self.BASE.items() if k != "answer"}
        table = {
            "missing answer": no_answer,
            "missing version": {k: v for k, v in self.BASE.items() if k != "version"},
            "empty version": {**self.BASE, "version": ""},
            "non-string version": {**self.BASE, "version": 5},
            "extra key": {**self.BASE, "extra": 1},
            "unknown word": {**self.BASE, "answer": "maybe"},
            "note with passed": {**self.BASE, "note": "hi"},
            "note without a note": {**self.BASE, "answer": "note"},
            "blank note": {**self.BASE, "answer": "note", "note": " \n\t"},
            "long note": {**self.BASE, "answer": "note", "note": "n" * (verify_answer.MAX_NOTE_CHARS + 1)},
            "non-string note": {**self.BASE, "answer": "note", "note": 5},
            "long confirm": {**self.BASE, "confirm": "c" * 201},
            "non-string confirm": {**self.BASE, "confirm": 5},
            "empty key": {**self.BASE, "key": ""},
            "empty project": {**self.BASE, "project_id": ""},
            "duplicate key": (b'{"project_id": "p", "project_id": "q", "key": "k", "answer": "passed", "version": "v"}'),
            "nan": (b'{"project_id": "p", "key": "k", "answer": "passed", "version": "v", "confirm": NaN}'),
            "not an object": [self.BASE],
        }
        for name, body in table.items():
            with self.subTest(name):
                with self.assertRaises(ValueError):
                    self.parse(body)
        self.assertEqual(self.parse({**self.BASE, "answer": "note", "note": "n" * 600})[4], "n" * 600)


if __name__ == "__main__":
    unittest.main()
