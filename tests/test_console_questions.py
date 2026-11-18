"""A manager's questions and the owner's answers (#891).

Run: just agent-workflow-tests
"""
import contextlib
import io
import json
from datetime import datetime, timezone

from agent_tools.console import manager, nudge, sessions, sprints, service

from . import console_test_support as support
from .test_console_answer import view_of
from .test_console_messages import GOAL_TEXT, PARTS
from .test_console_reports import REPORT
from .test_console_writes import Case
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)

BRIEF = "/api/brief"
APPROVE = "/api/approve"
ASK = "/api/ask"
ROUND_ANSWER = "/api/round-answer"
WITHDRAW = "/api/withdraw-question"
INBOX = "/api/inbox"
JSON = {"Content-Type": "application/json"}
Q0 = {"question": "Which store keeps the checkpoints?", "blocks": "the resume slice",
      "options": ["sqlite", "files"], "recommended": "files"}
Q1 = {"question": "May the reader change?", "blocks": "the reader slice",
      "options": ["yes", "no"], "recommended": "no"}
QW = {"question": "Does the new line read right?", "blocks": "the copy slice",
      "options": ["Approve", "Ask for changes"], "recommended": "Approve",
      "needs_words": ["Ask for changes"]}
ROUND = {"questions": [Q0, Q1]}
OWN_WORDS = "use the reader\nnot the writer"


class QuestionRouteTest(Case):
    def open(self):
        support.write_registry(self.registry, support.entries(2))
        return self.start()

    def secret(self, sid):
        return (self.store.parent / "sprint-secrets" / sid).read_text().removesuffix("\n")

    def approved(self, svc, project_id="owner/p01"):
        sid = svc.state_goal(project_id, GOAL_TEXT)
        body = json.dumps({"sprint_id": sid, "secret": self.secret(sid), "brief": PARTS}).encode()
        self.assertEqual(support.post_page(svc.address, BRIEF, JSON, body)[0], 200)
        body = json.dumps({"project_id": project_id, "sprint_id": sid, "version": 1}).encode()
        self.assertEqual(
            support.post_page(svc.address, APPROVE, self.own(svc, **JSON), body)[0], 204)
        return sid

    def ask(self, svc, sid, secret, round_=ROUND, **headers):
        body = json.dumps({"sprint_id": sid, "secret": secret, "round": round_}).encode()
        return support.post_page(svc.address, ASK, {**JSON, **headers}, body)

    def reply(self, svc, body, **headers):
        raw = json.dumps(body).encode() if isinstance(body, dict) else body
        return support.post_page(svc.address, ROUND_ANSWER, self.own(svc, **{**JSON, **headers}),
                                 raw)

    def inbox(self, svc, sid):
        body = json.dumps({"sprint_id": sid, "secret": self.secret(sid)}).encode()
        return support.post_page(svc.address, INBOX, JSON, body)

    def rows(self, kind):
        return [json.loads(row[4]) | {"seq": row[0]} for row in support.log_rows(self.store)
                if row[2] == kind]

    def asked(self, svc, round_=ROUND):
        sid = self.approved(svc)
        status, _, body = self.ask(svc, sid, self.secret(sid), round_)
        self.assertEqual(status, 200, body)
        return sid, json.loads(body)["round"]

    def answer_body(self, sid, round_id, question, **member):
        return {"project_id": "owner/p01", "sprint_id": sid, "round": round_id,
                "question": question, **member}

    def test_a_round_with_the_secret_is_one_open_item_per_question(self):
        svc = self.open()
        sid = self.approved(svc)
        status, headers, body = self.ask(svc, sid, self.secret(sid))
        self.assertEqual((status, headers["Content-Type"]), (200, "application/json"))
        (row,) = self.rows("questions.asked")
        self.assertEqual(json.loads(body), {"questions": 2, "round": row["seq"]})
        self.assertEqual(body, json.dumps({"questions": 2, "round": row["seq"]},
                                          sort_keys=True, separators=(",", ":")).encode())
        self.assertEqual({k: v for k, v in row.items() if k != "seq"}, {
            "sprint_id": sid, "goal": GOAL_TEXT, "blocker": False, "questions": [Q0, Q1]})
        view = view_of(svc)
        opened = view["inbox"]["open"]
        self.assertEqual([item["key"] for item in opened],
                         [f"question/{sid}/{row['seq']}/0", f"question/{sid}/{row['seq']}/1"])
        self.assertEqual([item["questions"][0]["recommended"] for item in opened],
                         ["files", "no"])
        self.assertEqual(view["statement"]["inbox_items"], 2)

    def test_a_round_is_refused_before_approval_without_the_secret_or_when_malformed(self):
        svc = self.open()
        early = svc.state_goal("owner/p01", GOAL_TEXT)
        sid = self.approved(svc, "owner/p00")
        one_option = {"questions": [{**Q0, "options": ["sqlite"]}]}
        no_recommendation = {"questions": [Q0, {k: v for k, v in Q1.items()
                                                if k != "recommended"}]}
        for name, send, status, text in (
                ("not approved", lambda: self.ask(svc, early, self.secret(early)), 409,
                 sprints.NOT_STARTED),
                ("wrong secret", lambda: self.ask(svc, sid, self.secret(sid) + "x"), 403,
                 sprints.SECRET_REFUSED),
                ("origin", lambda: self.ask(svc, sid, self.secret(sid),
                                            Origin="http://example.com"), 403, "origin refused"),
                ("one option", lambda: self.ask(svc, sid, self.secret(sid), one_option), 409,
                 sprints.OPTION_COUNT.format(n=1)),
                ("no recommendation",
                 lambda: self.ask(svc, sid, self.secret(sid), no_recommendation), 409,
                 sprints.NO_RECOMMENDATION.format(n=2)),
                ("no round",
                 lambda: support.post_page(svc.address, ASK, JSON, json.dumps(
                     {"sprint_id": sid, "secret": self.secret(sid)}).encode()), 400, "bad round")):
            with self.subTest(name):
                got = self.assert_unchanged(svc, send)
                self.assertEqual((got[0], got[2]), (status, text.encode() + b"\n"))
        withdrawn = svc.state_goal("owner/p01", GOAL_TEXT)
        secret = self.secret(withdrawn)
        svc.withdraw_goal("owner/p01", withdrawn)
        got = self.assert_unchanged(svc, lambda: self.ask(svc, withdrawn, secret))
        self.assertEqual((got[0], got[2]), (409, sprints.NOT_OPEN.encode() + b"\n"))

    def test_a_round_over_a_limit_is_refused_with_the_limit_named_and_logs_nothing(self):
        svc = self.open()
        sid = self.approved(svc)
        secret = self.secret(sid)
        cases = [({"question": "q" * 141}, sprints.ASK_TOO_LONG, "140"),
                 ({"question": "q" * 1200}, sprints.ASK_TOO_LONG, "140"),
                 ({"context": "c" * 401}, sprints.CONTEXT_TOO_LONG, "400"),
                 ({"options": ["o" * 81, "files"]}, sprints.OPTION_TOO_LONG, "80"),
                 ({"options": ["o" * 600, "files"]}, sprints.OPTION_TOO_LONG, "80")]
        for changes, text, number in cases:
            with self.subTest(changes=[(k, len(str(v))) for k, v in changes.items()]):
                status, _, body = self.ask(svc, sid, secret, {"questions": [{**Q0, **changes}]})
                self.assertEqual((status, body), (409, text.format(n=1).encode() + b"\n"))
                self.assertIn(number.encode(), body)
        self.assertEqual(self.rows("questions.asked"), [])

    def test_a_round_with_a_context_logs_it_and_the_view_question_keeps_it(self):
        svc = self.open()
        sid = self.approved(svc)
        question = {**Q0, "context": "A crash loses an hour of work."}
        status, _, body = self.ask(svc, sid, self.secret(sid), {"questions": [question]})
        self.assertEqual(status, 200, body)
        (row,) = self.rows("questions.asked")
        self.assertEqual(row["questions"], [question])

    def test_a_second_round_is_refused_while_one_is_open_unless_a_blocker(self):
        svc = self.open()
        sid, first = self.asked(svc)
        secret = self.secret(sid)
        got = self.assert_unchanged(svc, lambda: self.ask(svc, sid, secret, {"questions": [Q0]}))
        self.assertEqual((got[0], got[2]), (409, sprints.ROUND_OPEN.encode() + b"\n"))
        status, _, body = self.ask(svc, sid, secret, {"questions": [Q0], "blocker": True})
        self.assertEqual(status, 200, body)
        self.assertEqual([row["blocker"] for row in self.rows("questions.asked")], [False, True])
        blocker = json.loads(body)["round"]
        for round_id, index in ((first, 0), (first, 1), (blocker, 0)):
            status, _, body = self.reply(svc, self.answer_body(sid, round_id, index, choice=0))
            self.assertEqual(status, 204, body)
        self.assertEqual(self.ask(svc, sid, secret, {"questions": [Q0]})[0], 200)

    def test_an_answer_becomes_a_message_and_the_item_leaves(self):
        svc = self.open()
        sid, round_id = self.asked(svc)
        self.assertEqual(
            self.reply(svc, self.answer_body(sid, round_id, 0, choice=0))[0], 204)
        self.assertEqual(
            self.reply(svc, self.answer_body(sid, round_id, 1, text=OWN_WORDS))[0], 204)
        first, second = self.rows("question.answered")
        self.assertEqual({k: v for k, v in first.items() if k != "seq"}, {
            "sprint_id": sid, "goal": GOAL_TEXT, "round": round_id, "index": 0,
            "question": Q0["question"], "answer": "sqlite", "chosen": "sqlite",
            "recommended": "files", "differs": True})
        self.assertEqual(
            (second["answer"], second["chosen"], second["differs"], second["index"]),
            (OWN_WORDS, None, True, 1))
        self.assertEqual(view_of(svc)["inbox"]["open"], [])
        status, _, body = self.inbox(svc, sid)
        self.assertEqual(status, 200)
        sent = [m for m in json.loads(body)["messages"] if m["kind"] == "answer"]
        self.assertEqual([(m["text"], m["question"], m["round"], m["chosen"]) for m in sent], [
            ("sqlite", Q0["question"], round_id, "sqlite"),
            (OWN_WORDS, Q1["question"], round_id, None)])
        self.assertEqual([m["id"] for m in sent], [first["seq"], second["seq"]])

    def test_an_option_and_words_are_one_answer_and_the_inbox_carries_both(self):
        svc = self.open()
        sid, round_id = self.asked(svc, {"questions": [QW]})
        status, _, body = self.reply(
            svc, self.answer_body(sid, round_id, 0, choice=1, text="make the line shorter"))
        self.assertEqual(status, 204, body)
        (row,) = self.rows("question.answered")
        self.assertEqual({k: v for k, v in row.items() if k != "seq"}, {
            "sprint_id": sid, "goal": GOAL_TEXT, "round": round_id, "index": 0,
            "question": QW["question"], "answer": "Ask for changes", "chosen": "Ask for changes",
            "words": "make the line shorter", "recommended": "Approve", "differs": True})
        (sent,) = [m for m in json.loads(self.inbox(svc, sid)[2])["messages"]
                   if m["kind"] == "answer"]
        self.assertEqual((sent["text"], sent["chosen"], sent["words"]),
                         ("Ask for changes", "Ask for changes", "make the line shorter"))

    def test_an_option_that_needs_words_is_refused_without_them(self):
        svc = self.open()
        sid, round_id = self.asked(svc, {"questions": [QW]})
        got = self.assert_unchanged(
            svc, lambda: self.reply(svc, self.answer_body(sid, round_id, 0, choice=1)))
        self.assertEqual((got[0], got[2]), (409, sprints.WORDS_NEEDED.encode() + b"\n"))
        self.assertEqual(
            self.reply(svc, self.answer_body(sid, round_id, 0, choice=0))[0], 204)
        (row,) = self.rows("question.answered")
        self.assertNotIn("words", row)
        (sent,) = [m for m in json.loads(self.inbox(svc, sid)[2])["messages"]
                   if m["kind"] == "answer"]
        self.assertIsNone(sent["words"])

    def test_a_closed_sprint_takes_no_question_and_no_answer(self):
        svc = self.open()
        sid, round_id = self.asked(svc)
        svc.send_closing(sid, self.secret(sid), {
            "summary": "Stopped early", "issues": [], "differently": "ask sooner"})
        ended = b"this sprint has ended\n"
        got = self.assert_unchanged(
            svc, lambda: self.reply(svc, self.answer_body(sid, round_id, 0, choice=0)))
        self.assertEqual((got[0], got[2]), (409, ended))
        got = self.assert_unchanged(
            svc, lambda: self.ask(svc, sid, self.secret(sid), {**ROUND, "blocker": True}))
        self.assertEqual((got[0], got[2]), (409, ended))
        self.assertEqual(view_of(svc)["inbox"]["open"], [])

    def test_a_done_report_with_a_question_open_leaves_the_sprint_messageable(self):
        svc = self.open()
        sid, round_id = self.asked(svc)
        svc.send_report(sid, self.secret(sid), {**REPORT, "phase": "done"})
        self.assertEqual(svc.send_message("owner/p01", sid, "still here") > 0, True)
        self.assertEqual(
            self.reply(svc, self.answer_body(sid, round_id, 0, choice=0))[0], 204)

    def test_an_answer_follows_the_page_write_rule(self):
        svc = self.open()
        sid, round_id = self.asked(svc)
        valid = self.answer_body(sid, round_id, 0, choice=0)
        raw = json.dumps(valid).encode()
        own = {"Origin": f"http://127.0.0.1:{svc.address[1]}"}
        for name, headers, status, text in (
                ("no token", {**JSON, **own}, 403, "token refused"),
                ("wrong token", {**JSON, **own, "X-Console-Token": "x" * 43}, 403,
                 "token refused"),
                ("foreign origin", {**JSON, "X-Console-Token": self.token(),
                                    "Origin": "http://example.com"}, 403, "origin refused"),
                ("no origin", {**JSON, "X-Console-Token": self.token()}, 403,
                 "origin refused")):
            with self.subTest(name):
                got = self.assert_unchanged(
                    svc, lambda: support.post_page(svc.address, ROUND_ANSWER, headers, raw))
                self.assertEqual((got[0], got[2]), (status, text.encode() + b"\n"))
        self.assertIn(service.ROUND_ANSWER_PATH, service.PAGE_WRITES)
        other = svc.state_goal("owner/p00", GOAL_TEXT)
        for name, body, status, text in (
                ("unknown round", self.answer_body(sid, 999, 0, choice=0), 409,
                 sprints.UNKNOWN_QUESTION),
                ("unknown question", self.answer_body(sid, round_id, 5, choice=0), 409,
                 sprints.UNKNOWN_QUESTION),
                ("not an option", self.answer_body(sid, round_id, 0, choice=2), 409,
                 sprints.NOT_AN_OPTION),
                ("blank text", self.answer_body(sid, round_id, 0, text="  "), 409,
                 sprints.EMPTY_MESSAGE),
                ("another project", {**valid, "project_id": "owner/p00"}, 409, sprints.NOT_OPEN),
                ("another sprint of that project", {**valid, "sprint_id": other,
                                                    "project_id": "owner/p01"}, 409,
                 sprints.NOT_OPEN),
                ("choice and blank text", {**valid, "text": "  "}, 409, sprints.EMPTY_MESSAGE)):
            with self.subTest(name):
                got = self.assert_unchanged(svc, lambda: self.reply(svc, body))
                self.assertEqual((got[0], got[2]), (status, text.encode() + b"\n"))
        self.assertEqual(self.reply(svc, valid)[0], 204)
        got = self.assert_unchanged(svc, lambda: self.reply(svc, valid))
        self.assertEqual((got[0], got[2]),
                         (409, sprints.ANSWERED_ALREADY.encode() + b"\n"))

    def test_a_differing_answer_is_recorded_and_said_in_the_digest(self):
        svc = self.open()
        sid, round_id = self.asked(svc)
        self.assertEqual(self.reply(svc, self.answer_body(sid, round_id, 0, choice=0))[0], 204)
        self.assertEqual(self.reply(svc, self.answer_body(sid, round_id, 1, choice=1))[0], 204)
        self.assertEqual([row["differs"] for row in self.rows("question.answered")],
                         [True, False])
        said = [m["sentence"] for m in view_of(svc)["digest"]["recent"]]
        self.assertIn("An answer for owner/p01: You chose 'sqlite' over the recommended 'files': "
                      "Which store keeps the checkpoints?", said)
        self.assertEqual([s for s in said if "May the reader change?" in s], [])

    def test_questions_and_answers_survive_a_restart(self):
        svc = self.open()
        sid, round_id = self.asked(svc)
        self.assertEqual(self.reply(svc, self.answer_body(sid, round_id, 0, choice=1))[0], 204)
        svc.close()
        again = self.start()
        opened = view_of(again)["inbox"]["open"]
        self.assertEqual([item["key"] for item in opened], [f"question/{sid}/{round_id}/1"])
        with again._ingest:
            kept = [(m.kind, m.text) for m in again._sprints[sid].messages if m.kind == "answer"]
        self.assertEqual(kept, [("answer", "files")])

    def test_the_secret_and_the_owners_words_appear_in_no_stderr_line(self):
        svc = self.open()
        sid, round_id = self.asked(svc)
        secret = self.secret(sid)
        private = "my private words about the store"
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            self.assertEqual(self.ask(svc, sid, secret + "x")[0], 403)
            self.assertEqual(self.ask(svc, sid, secret, {"questions": [Q0]})[0], 409)
            self.assertEqual(
                self.reply(svc, self.answer_body(sid, round_id, 0, text=" " * 3))[0], 409)
            self.assertEqual(
                self.reply(svc, self.answer_body(sid, 999, 0, text=private))[0], 409)
        lines = stderr.getvalue()
        self.assertIn(f"console: ask_refused {sid} secret refused", lines)
        self.assertIn("console: round_answer_refused", lines)
        self.assertNotIn(secret, lines)
        self.assertNotIn(private, lines)

    def test_other_methods_on_either_route_are_refused(self):
        svc = self.open()
        for path in (ASK, ROUND_ANSWER, WITHDRAW):
            for method in ("GET", "PUT", "DELETE"):
                with self.subTest(path=path, method=method):
                    status, headers, _ = support.request(svc.address, method, path)
                    self.assertEqual((status, headers["Allow"]), (405, "POST"))
        self.assertIn(service.WITHDRAW_QUESTION_PATH, service.MANAGER_WRITES)
        self.assertNotIn(service.WITHDRAW_QUESTION_PATH, service.PAGE_WRITES)


def withdraw(svc, sid, secret, round_id, index, **headers):
    body = json.dumps({"sprint_id": sid, "secret": secret, "round": round_id,
                       "index": index}).encode()
    return support.post_page(svc.address, WITHDRAW, {**JSON, **headers}, body)


def sprint_entry(view, sid):
    projects = [member for entry in view["entries"]
                for member in (entry["projects"] if entry["type"] == "quiet_group" else [entry])]
    return next(entry for project in projects for entry in project["sprints"]
                if entry["sprint_id"] == sid)


class QuestionWithdrawTest(QuestionRouteTest):
    """A manager takes back or replaces its own open question (#1099)."""

    def settled(self, svc):
        """Sprint A with question 1 answered and question 0 withdrawn; sprint B with one open."""
        sid, r = self.asked(svc)
        self.assertEqual(self.reply(svc, self.answer_body(sid, r, 1, choice=0))[0], 204)
        self.assertEqual(withdraw(svc, sid, self.secret(sid), r, 0)[0], 200)
        other = self.approved(svc, "owner/p00")
        status, _, body = self.ask(svc, other, self.secret(other), {"questions": [Q0]})
        self.assertEqual(status, 200, body)
        return sid, r, other, json.loads(body)["round"]

    def test_a_withdrawn_question_leaves_the_view_and_the_waiting_count(self):
        svc = self.open()
        sid, r = self.asked(svc)
        self.assertEqual(sprint_entry(view_of(svc), sid)["waiting"], 2)
        before = support.log_rows(self.store)
        status, _, body = withdraw(svc, sid, self.secret(sid), r, 0)
        after = support.log_rows(self.store)
        self.assertEqual((status, body), (200, b'{"index":0,"round":%d}' % r))
        self.assertEqual(after[:len(before)], before)
        self.assertEqual(len(after), len(before) + 1)
        self.assertEqual(after[-1][2], "question.withdrawn")
        (row,) = self.rows("question.withdrawn")
        self.assertEqual({k: v for k, v in row.items() if k != "seq"}, {
            "sprint_id": sid, "goal": GOAL_TEXT, "round": r, "index": 0,
            "question": Q0["question"]})
        view = view_of(svc)
        self.assertEqual([item["key"] for item in view["inbox"]["open"]],
                         [f"question/{sid}/{r}/1"])
        self.assertEqual(view["statement"]["inbox_items"], 1)
        entry = sprint_entry(view, sid)
        self.assertEqual((entry["waiting"], entry["state_text"]), (1, "waiting on you (1)"))

    def test_withdraw_refuses_another_sprints_an_unknown_an_answered_or_a_withdrawn_question(self):
        svc = self.open()
        sid, r, _other, rb = self.settled(svc)
        secret = self.secret(sid)
        gone = svc.state_goal("owner/p01", GOAL_TEXT)
        gone_secret = self.secret(gone)
        svc.withdraw_goal("owner/p01", gone)
        text = lambda reason: reason.encode() + b"\n"  # noqa: E731
        for name, send, status, body in (
                ("another sprint's", lambda: withdraw(svc, sid, secret, rb, 0), 409,
                 text(sprints.QUESTION_FOREIGN)),
                ("unknown round", lambda: withdraw(svc, sid, secret, 999, 0), 409,
                 text(sprints.UNKNOWN_QUESTION)),
                ("unknown index", lambda: withdraw(svc, sid, secret, r, 5), 409,
                 text(sprints.UNKNOWN_QUESTION)),
                ("answered", lambda: withdraw(svc, sid, secret, r, 1), 409,
                 text(sprints.ANSWERED_ALREADY)),
                ("withdrawn", lambda: withdraw(svc, sid, secret, r, 0), 409,
                 text(sprints.WITHDRAWN_ALREADY)),
                ("wrong secret", lambda: withdraw(svc, sid, secret + "x", r, 0), 403,
                 b"secret refused\n"),
                ("origin", lambda: withdraw(svc, sid, secret, r, 0,
                                                 Origin="http://example.com"), 403,
                 b"origin refused\n"),
                ("no index", lambda: support.post_page(svc.address, WITHDRAW, JSON, json.dumps(
                    {"sprint_id": sid, "secret": secret, "round": r}).encode()), 400,
                 b"bad withdraw question\n"),
                ("withdrawn goal", lambda: withdraw(svc, gone, gone_secret, r, 0), 409,
                 text(sprints.NOT_OPEN))):
            with self.subTest(name):
                got = self.assert_unchanged(svc, send)
                self.assertEqual((got[0], got[2]), (status, body))

    def test_a_replacing_round_withdraws_the_named_question_in_the_same_write(self):
        svc = self.open()
        sid, r = self.asked(svc)
        secret = self.secret(sid)
        mark = {"round": r, "index": 0}
        got = self.assert_unchanged(svc, lambda: self.ask(
            svc, sid, secret, {"questions": [{**Q0, "replaces": mark}]}))
        self.assertEqual((got[0], got[2]), (409, sprints.ROUND_OPEN.encode() + b"\n"))
        self.assertEqual(self.reply(svc, self.answer_body(sid, r, 1, choice=0))[0], 204)
        rows_before = len(support.log_rows(self.store))
        status, _, body = self.ask(svc, sid, secret, {"questions": [
            {**Q0, "context": "now with the pictures", "replaces": mark}]})
        self.assertEqual(status, 200, body)
        self.assertEqual(len(support.log_rows(self.store)), rows_before + 1)
        self.assertEqual(self.rows("question.withdrawn"), [])
        self.assertEqual(self.rows("questions.asked")[-1]["questions"][0]["replaces"], mark)
        r2 = json.loads(body)["round"]
        self.assertEqual([item["key"] for item in view_of(svc)["inbox"]["open"]],
                         [f"question/{sid}/{r2}/0"])

    def test_a_replaces_mark_naming_a_question_that_cannot_be_withdrawn_is_refused(self):
        svc = self.open()
        sid, r, _other, rb = self.settled(svc)
        secret = self.secret(sid)
        for mark, reason in (({"round": rb, "index": 0}, sprints.QUESTION_FOREIGN),
                             ({"round": 999, "index": 0}, sprints.UNKNOWN_QUESTION),
                             ({"round": r, "index": 1}, sprints.ANSWERED_ALREADY),
                             ({"round": r, "index": 0}, sprints.WITHDRAWN_ALREADY)):
            expected = sprints.REPLACES_REFUSED.format(
                n=1, round=mark["round"], index=mark["index"], reason=reason)
            for dry in (False, True):
                with self.subTest(mark=mark, dry_run=dry):
                    body = json.dumps({"sprint_id": sid, "secret": secret,
                                       "round": {"questions": [{**Q0, "replaces": mark}]},
                                       **({"dry_run": True} if dry else {})})
                    got = self.assert_unchanged(svc, lambda: support.post_page(
                        svc.address, ASK, JSON, body.encode()))
                    self.assertEqual((got[0], got[2]), (409, expected.encode() + b"\n"))
        got = self.assert_unchanged(svc, lambda: self.ask(
            svc, sid, secret, {"questions": [{**Q0, "replaces": {"round": r}}]}))
        self.assertEqual((got[0], got[2]),
                         (409, sprints.REPLACES_SHAPE.format(n=1).encode() + b"\n"))

    def test_an_answer_to_a_withdrawn_question_is_refused_and_stores_no_message(self):
        svc = self.open()
        sid, r = self.asked(svc)
        self.assertEqual(withdraw(svc, sid, self.secret(sid), r, 0)[0], 200)
        taken = sprints.TAKEN_BACK.encode() + b"\n"
        for member in ({"choice": 0}, {"text": "mine"}):
            with self.subTest(member=member):
                got = self.assert_unchanged(
                    svc, lambda: self.reply(svc, self.answer_body(sid, r, 0, **member)))
                self.assertEqual((got[0], got[2]), (409, taken))
        self.assertEqual(self.rows("question.answered"), [])
        status, _, body = self.inbox(svc, sid)
        self.assertEqual([m for m in json.loads(body)["messages"] if m["kind"] == "answer"], [])

    def test_an_answer_to_a_replaced_question_is_refused_the_same_way(self):
        svc = self.open()
        sid, r = self.asked(svc)
        self.assertEqual(self.reply(svc, self.answer_body(sid, r, 1, choice=0))[0], 204)
        status, _, body = self.ask(svc, sid, self.secret(sid), {"questions": [
            {**Q0, "replaces": {"round": r, "index": 0}}]})
        self.assertEqual(status, 200, body)
        got = self.assert_unchanged(
            svc, lambda: self.reply(svc, self.answer_body(sid, r, 0, choice=0)))
        self.assertEqual((got[0], got[2]), (409, sprints.TAKEN_BACK.encode() + b"\n"))
        self.assertEqual(len(self.rows("question.answered")), 1)

    def test_a_withdrawal_and_a_replacement_survive_a_restart(self):
        svc = self.open()
        sid, r = self.asked(svc)
        self.assertEqual(withdraw(svc, sid, self.secret(sid), r, 0)[0], 200)
        svc.close()
        again = self.start()
        self.assertEqual([item["key"] for item in view_of(again)["inbox"]["open"]],
                         [f"question/{sid}/{r}/1"])

    def test_the_secret_appears_in_no_withdraw_stderr_line(self):
        svc = self.open()
        sid, r = self.asked(svc)
        secret = self.secret(sid)
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            self.assertEqual(withdraw(svc, sid, secret + "x", r, 0)[0], 403)
            self.assertEqual(withdraw(svc, sid, secret, 999, 0)[0], 409)
        lines = stderr.getvalue()
        self.assertIn(f"console: withdraw_question_refused {sid} secret refused", lines)
        self.assertIn(
            f"console: withdraw_question_refused {sid} this question is not known", lines)
        self.assertNotIn(secret, lines)

    def test_an_answer_to_the_withdrawn_last_question_of_a_done_sprint_says_it_was_taken_back(self):
        svc = self.open()
        sid, r = self.asked(svc, {"questions": [Q0]})
        svc.send_report(sid, self.secret(sid), {**REPORT, "phase": "done"})
        self.assertEqual(withdraw(svc, sid, self.secret(sid), r, 0)[0], 200)
        taken = sprints.TAKEN_BACK.encode() + b"\n"
        for member in ({"choice": 0}, {"text": "mine"}):
            with self.subTest(member=member):
                got = self.assert_unchanged(
                    svc, lambda: self.reply(svc, self.answer_body(sid, r, 0, **member)))
                self.assertEqual((got[0], got[2]), (409, taken))
        self.assertEqual(self.rows("question.answered"), [])
        status, _, body = self.inbox(svc, sid)
        self.assertEqual([m for m in json.loads(body)["messages"] if m["kind"] == "answer"], [])
        got = self.assert_unchanged(
            svc, lambda: self.reply(svc, self.answer_body(sid, r, 5, choice=0)))
        self.assertEqual((got[0], got[2]), (409, b"this sprint has ended\n"))


T0 = 1_800_000_000.0


class QuestionNudgeTest(Case):
    """An answer nudges a started manager; a round the manager sends does not (#891)."""

    def setUp(self):
        super().setUp()
        support.write_registry(self.registry, support.entries(2))
        self.queued = support.Queued()
        self.nudges = []
        self.listed = {}

    def log_clock(self):
        return datetime.fromtimestamp(T0, timezone.utc).isoformat(timespec="microseconds")

    def nudger(self, sent):
        self.nudges.append(sent)

    def begin(self):
        support.sign_in(self.store, "work")
        return self.start(
            launcher=support.Launches(), profile_dirs=[support.profile_dir(self.store, "work")],
            dispatch=self.queued, nudger=self.nudger, listing=lambda: dict(self.listed),
            clock=lambda: T0, log_clock=self.log_clock, session_poll_seconds=3600)

    def nudged(self):
        return [(row[0], json.loads(row[4])) for row in support.log_rows(self.store)
                if row[2] == "sprint.nudged"]

    def test_an_answer_nudges_a_started_manager(self):
        svc = self.begin()
        sid = svc.state_goal("owner/p01", GOAL_TEXT)
        self.queued.run_next()
        name = manager.session_name("owner/p01", sid)
        self.listed["s-1"] = sessions.Observation("s-1", "/srv/p01", 1, "idle", None, name, None)
        secret = (self.store.parent / "sprint-secrets" / sid).read_text().removesuffix("\n")
        svc.send_brief(sid, secret, PARTS)
        svc.approve_brief("owner/p01", sid, 1)
        self.queued.run_next()
        settled = (len(self.nudges), len(self.nudged()))
        round_id, count = svc.ask_questions(sid, secret, ROUND)
        self.assertEqual((count, self.queued.jobs), (2, []))
        self.assertEqual((len(self.nudges), len(self.nudged())), settled)
        seq = svc.answer_question("owner/p01", sid, round_id, 0, 0, None)
        self.queued.run_next()
        self.assertEqual(len(self.nudges), settled[0] + 1)
        self.assertEqual(self.nudges[-1], nudge.Nudge(
            sid, "relay", name, "s-1", "work", "/srv/p01"))
        self.assertNotIn("sqlite", repr(self.nudges[-1]))
        (_, row) = self.nudged()[-1]
        self.assertEqual((row["ok"], row["through"]), (True, seq))
        self.assertEqual(len(self.nudged()), settled[1] + 1)
