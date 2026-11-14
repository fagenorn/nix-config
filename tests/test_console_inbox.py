"""The console's inbox reader (#859): owner-action markers into inbox items, and the local activity reading."""

import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from agent_tools.claims import forge_markers as fm
from agent_tools.claims import forge_owner_action as foa
from agent_tools.console import inbox
from agent_tools.system.forge_api import ForgeError
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)

SLUG, PROJECT = "octo/widgets", "widgets"
HOLDER = "h1/b1"
QUESTIONS = [
    {"question": "Which host runs the paid smoke test?", "options": ["Run it on host one.", "Run it on host two."]},
    {"question": "May the delivery push the scratch branch?", "options": ["Approve: push the scratch branch.", "Refuse."]},
]
C1, C2, C3 = 6803141410, 6803141420, 6803141430


def decision_body(questions=QUESTIONS, ticks=(), reason="decision", rec=None):
    """A decision prompt; `ticks` holds (question index, option index) pairs to tick."""
    fields = {"issue": "7", "reason": reason, "holder": HOLDER, "round": "1",
              "opts": foa.options_digest(questions), **({"rec": rec} if rec else {})}
    lines = []
    for qi, q in enumerate(questions):
        lines += ["", f"**Q{qi + 1}.** {q['question']}"]
        lines += [f"- [{'x' if (qi, oi) in ticks else ' '}] {o}" for oi, o in enumerate(q["options"])]
    return fm.render(foa.KIND, fields, foa.SENTENCES["decision"], "\n".join(lines))


def bullet_body(reason, items):
    return fm.render(foa.KIND, {"issue": "7", "reason": reason, "holder": HOLDER}, foa.SENTENCES[reason],
                     "\n".join(f"- {i}" for i in items))


def comment_node(cid, body, assoc="OWNER"):
    return {"fullDatabaseId": str(cid), "body": body, "authorAssociation": assoc,
            "updatedAt": "2026-11-10T09:00:00Z"}


def issue_node(number, comments, blocking=0):
    return {"__typename": "Issue", "number": number, "issueDependenciesSummary": {"blocking": blocking},
            "comments": {"totalCount": len(comments), "nodes": comments}}


def pr_node(number, comments):
    return {"__typename": "PullRequest", "number": number,
            "comments": {"totalCount": len(comments), "nodes": comments}}


def page(nodes, more=False, cursor=None, count=None):
    return {"data": {"search": {"issueCount": len(nodes) if count is None else count,
                                "pageInfo": {"hasNextPage": more, "endCursor": cursor}, "nodes": nodes}}}


def read(*pages, **kwargs):
    answers = list(pages)
    return inbox.read_items(PROJECT, SLUG, call=lambda argv: answers.pop(0), **kwargs)


def expected(issue, comment_id, reason, **fields):
    return {"key": f"{SLUG}#{issue}/{comment_id}", "project_id": PROJECT, "repo": SLUG, "issue": issue,
            "comment_id": comment_id, "url": f"https://github.com/{SLUG}/issues/{issue}#issuecomment-{comment_id}",
            "reason": reason, "kind": reason, "question": foa.SENTENCES.get(reason), "detail": "",
            "questions": [], "items": [], "answers": [], "paid": False, "confirm": "",
            "answered": False, **fields}


def three_nodes():
    return [issue_node(7, [comment_node(C1, decision_body())], blocking=2),
            issue_node(8, [comment_node(C2, bullet_body("conflict", ["Merge conflict in flake.lock"]))]),
            pr_node(9, [comment_node(C3, bullet_body("needs-label", ["needs the instruction-budget-raise label"]))])]


class MarkerTableTest(unittest.TestCase):
    def test_each_reason_kind_becomes_an_inbox_item(self):
        items = read(page(three_nodes()))
        table = [
            expected(7, C1, "decision", held_work=3, questions=[
                {"question": QUESTIONS[0]["question"], "options": QUESTIONS[0]["options"], "chosen": None,
                 "recommended": None},
                {"question": QUESTIONS[1]["question"], "options": QUESTIONS[1]["options"], "chosen": None,
                 "recommended": None}]),
            expected(8, C2, "conflict", held_work=1, items=["Merge conflict in flake.lock"]),
            expected(9, C3, "needs-label", held_work=1, items=["needs the instruction-budget-raise label"]),
        ]
        self.assertEqual(len(items), 3)
        for item, want in zip(items, table):
            with self.subTest(reason=want["reason"]):
                self.assertEqual(item, want)

    def test_a_ticked_prompt_reads_as_answered(self):
        full = read(page([issue_node(7, [comment_node(C1, decision_body(ticks=((0, 1), (1, 0))))])]))[0]
        self.assertIs(full["answered"], True)
        self.assertEqual([q["chosen"] for q in full["questions"]],
                         ["Run it on host two.", "Approve: push the scratch branch."])
        half = read(page([issue_node(7, [comment_node(C1, decision_body(ticks=((0, 0),)))])]))[0]
        self.assertIs(half["answered"], False)

    def test_a_prompt_names_its_recommended_option(self):
        items = read(page([issue_node(7, [comment_node(C1, decision_body(rec="2.0"))])]))
        self.assertEqual([q["recommended"] for q in items[0]["questions"]], ["Run it on host two.", None])

    def test_only_a_decision_prompt_carries_questions(self):
        body = decision_body(reason="conflict")
        items = read(page([issue_node(7, [comment_node(C1, body)])]))
        self.assertEqual([(i["reason"], i["questions"]) for i in items], [("conflict", [])])

    def test_an_item_survives_a_json_round_trip(self):
        items = read(page(three_nodes()))
        self.assertEqual(json.loads(json.dumps(items)), items)


class NoItemTest(unittest.TestCase):
    def test_markers_that_are_not_waiting_raise_no_item(self):
        claim = fm.render("claim", {"issue": "7", "holder": HOLDER}, "Claimed.")
        table = {
            "untrusted author": [comment_node(C1, decision_body(), "CONTRIBUTOR")],
            "ended": [comment_node(C1, decision_body()), comment_node(C1 + 1, fm.end_body(C1, "resolved"))],
            "claim marker": [comment_node(C1, claim)],
            "plain comment": [comment_node(C1, "just a note")],
            "other reason": [comment_node(C1, bullet_body("conflict", []).replace("reason=conflict", "reason=other"))],
        }
        for name, comments in table.items():
            with self.subTest(name):
                self.assertEqual(read(page([issue_node(7, comments)])), [])


ASK_TEXT = "Open the staging site and confirm the login works."
SENTENCES = {"verify-ask": "AC1: the owner's answer is needed.",
             "verify-approve": "AC1 has live effects: tick the box to run it once on mbp.",
             "verify-act": "AC1 needs the owner to act on mbp; the runner then checks it.",
             "verify-decision": "AC1 failed: the owner decides.",
             "verify-stale-check": "AC1 waits on eleven-m5, which last reported never."}
ACT_TEXT = "```\nopen the dock\n```\n\nThen: probe deployed_includes"
ASK_BOXES = "- [ ] Accept\n- [ ] Reject"
DECISION_BOXES = "- [ ] Accept as passed\n- [ ] Close as not verified"


def verify_body(reason, fields, sentence, extra):
    return fm.render("owner-action", {"reason": reason, "block": "10.abc", "check": "0", **fields}, sentence, extra)


def ask(extra=f"{ASK_TEXT}\n\n{ASK_BOXES}"):
    return verify_body("verify-ask", {"host": "mbp"}, SENTENCES["verify-ask"], extra)


def approve(effects="live", extra='Command: ["just", "smoke"]\n\n- [ ] Run it'):
    return verify_body("verify-approve", {"host": "mbp", "effects": effects, "round": "1", "run": "d1"},
                       SENTENCES["verify-approve"], extra)


def act():
    return verify_body("verify-act", {"host": "mbp"}, SENTENCES["verify-act"], ACT_TEXT)


def decision(extra=DECISION_BOXES):
    return verify_body("verify-decision", {"on": "fail", "result": "55"}, SENTENCES["verify-decision"], extra)


def stale():
    return verify_body("verify-stale-check", {"host": "eleven-m5", "cause": "silent", "last": "never"},
                       SENTENCES["verify-stale-check"], "- [ ] Accept without eleven-m5")


class VerifyPromptTableTest(unittest.TestCase):
    def test_each_owner_prompt_kind_becomes_an_inbox_item(self):
        rows = [  # issue, body, reason, then (kind, answers, paid, confirm, detail, answered)
            (11, ask(), "verify-ask", ("manual-check", ["passed", "failed", "note"], False, "", ASK_TEXT, False)),
            (12, approve(), "verify-approve",
             ("approval", ["approve"], False, "octo/widgets#12", 'Command: ["just", "smoke"]', False)),
            (13, approve("paid"), "verify-approve",
             ("paid-approval", ["approve"], True, "octo/widgets#13", 'Command: ["just", "smoke"]', False)),
            (14, act(), "verify-act", ("act", [], False, "", ACT_TEXT, False)),
            (15, decision(), "verify-decision", ("verdict", ["passed", "failed"], False, "", "", False)),
            (16, stale(), "verify-stale-check", ("stale-check", ["keep", "drop"], False, "", "", False)),
        ]
        nodes = [issue_node(n, [comment_node(C1 + n, body)]) for n, body, _, _ in rows]
        items = read(page(nodes))
        self.assertEqual(len(items), len(rows))
        for item, (n, body, reason, want) in zip(items, rows):
            with self.subTest(reason=reason, issue=n):
                kind, answers, paid, confirm, detail, answered = want
                self.assertRegex(item["version"], r"^sha256:[0-9a-f]{64}$")
                self.assertEqual({k: v for k, v in item.items() if k != "version"},
                                 expected(n, C1 + n, reason, kind=kind, answers=answers, paid=paid,
                                          confirm=confirm, detail=detail, answered=answered,
                                          question=SENTENCES[reason], held_work=1))
        self.assertEqual(json.loads(json.dumps(items)), items)

    def test_the_version_names_the_prompt_content_the_owner_saw(self):
        def version(body):
            return read(page([issue_node(7, [comment_node(C1, body)])]))[0]["version"]
        self.assertEqual(version(ask()), version(ask()))
        for name, revised in {
                "instructions": ask(f"Open the production site.\n\n{ASK_BOXES}"),
                "host": verify_body("verify-ask", {"host": "eleven-m5"}, SENTENCES["verify-ask"],
                                    f"{ASK_TEXT}\n\n{ASK_BOXES}"),
                "check": verify_body("verify-ask", {"host": "mbp", "check": "1"}, SENTENCES["verify-ask"],
                                     f"{ASK_TEXT}\n\n{ASK_BOXES}")}.items():
            with self.subTest(name):
                self.assertNotEqual(version(revised), version(ask()))

    def one(self, *comments):
        return read(page([issue_node(7, list(comments))]))

    def test_a_ticked_or_consumed_prompt_reads_answered(self):
        ticked = ask(f"{ASK_TEXT}\n\n- [x] Accept\n- [ ] Reject")
        self.assertIs(self.one(comment_node(C1, ticked))[0]["answered"], True)
        run = fm.render("verify-run", {"block": "10.abc", "check": "0", "consumed": str(C1)}, "Consumed.")
        items = self.one(comment_node(C1, approve()), comment_node(C1 + 1, run))
        self.assertEqual([(i["kind"], i["answered"]) for i in items], [("approval", True)])
        self.assertIs(self.one(comment_node(C1, act()))[0]["answered"], False)

    def test_a_prompt_with_both_boxes_ticked_stays_open(self):
        both_ask = ask(f"{ASK_TEXT}\n\n- [x] Accept\n- [x] Reject")
        both_decision = decision("- [x] Accept as passed\n- [x] Close as not verified")
        items = self.one(comment_node(C1, both_ask), comment_node(C1 + 1, both_decision))
        self.assertEqual([(i["kind"], i["answered"], i["detail"]) for i in items],
                         [("manual-check", False, ASK_TEXT), ("verdict", False, "")])

    def test_detail_keeps_checkbox_lines_that_are_not_the_runners_boxes(self):
        text = "Open the staging site.\n- [ ] Check the dock too"
        body = ask(f"{text}\n\n- [ ] Accept\n- [ ] Reject")
        self.assertEqual(self.one(comment_node(C1, body))[0]["detail"], text)
        fenced = "```\n- [ ] Restart the service\nopen the dock\n```\n\nThen: probe deployed_includes"
        body = verify_body("verify-act", {"host": "mbp"}, SENTENCES["verify-act"], fenced)
        self.assertEqual(self.one(comment_node(C1, body))[0]["detail"], fenced)
        next_to = ask(f"\n{text}\n- [ ] Accept now\n- [ ] Accept\n- [ ] Reject")
        self.assertEqual(self.one(comment_node(C1, next_to))[0]["detail"], f"{text}\n- [ ] Accept now")

    def test_a_carriage_return_does_not_reach_the_detail(self):
        body = ask(f"{ASK_TEXT}\r\n\r\n- [ ] Accept\r\n- [ ] Reject\r\n")
        self.assertEqual(self.one(comment_node(C1, body))[0]["detail"], ASK_TEXT)


class NoVerifyItemTest(unittest.TestCase):
    def test_prompts_that_do_not_need_the_owner_raise_no_item(self):
        no_block = fm.render("owner-action", {"reason": "verify-ask", "check": "0"}, "x.", ASK_BOXES)
        other = fm.render("verify-result", {"block": "10.abc", "check": "0", "state": "pass"}, "Passed.")
        table = {
            "ended": [comment_node(C1, ask()), comment_node(C1 + 1, fm.end_body(C1, "resolved"))],
            "collaborator prompt": [comment_node(C1, ask(), "COLLABORATOR")],
            "no block field": [comment_node(C1, no_block)],
            "other verify kind": [comment_node(C1, other)],
        }
        for name, comments in table.items():
            with self.subTest(name):
                self.assertEqual(read(page([issue_node(7, comments)])), [])

    def test_a_collaborators_end_does_not_hide_an_owners_prompt(self):
        comments = [comment_node(C1, ask()), comment_node(C1 + 1, fm.end_body(C1, "answered"), "COLLABORATOR")]
        items = read(page([issue_node(7, comments)]))
        self.assertEqual([i["kind"] for i in items], ["manual-check"])


class ReadTest(unittest.TestCase):
    def endless(self, calls):
        def call(argv):
            calls.append(argv)
            return page([], more=True, cursor=f"c{len(calls)}", count=0)
        return call

    def test_a_read_never_makes_a_fifth_call(self):
        calls = []
        with self.assertRaises(ForgeError) as raised:
            inbox.read_items(PROJECT, SLUG, call=self.endless(calls))
        self.assertEqual(raised.exception.code, "payload_incomplete")
        self.assertEqual(len(calls), 4)

    def test_an_incomplete_answer_fails_the_read(self):
        bad_id = lambda value: issue_node(7, [{**comment_node(C1, decision_body()), "fullDatabaseId": value}])
        no_summary = issue_node(7, [])
        del no_summary["issueDependenciesSummary"]
        no_type = issue_node(7, [])
        del no_type["__typename"]
        table = [
            ("comments truncated", page([{**issue_node(7, [comment_node(C1, decision_body())]),
                                          "comments": {"totalCount": 101,
                                                       "nodes": [comment_node(C1, decision_body())]}}]),
             "payload_incomplete"),
            ("fewer nodes than issueCount", page([issue_node(7, [])], count=3), "payload_incomplete"),
            ("no data", {"data": {}}, "payload_invalid"),
            ("hasNextPage not bool", page([], more="yes"), "payload_invalid"),
            ("no dependency summary", page([no_summary]), "payload_invalid"),
            ("blocking is a bool", page([issue_node(7, [], blocking=True)]), "payload_invalid"),
            ("no typename", page([no_type]), "payload_invalid"),
            ("a discussion", page([{**issue_node(7, []), "__typename": "Discussion"}]), "payload_invalid"),
            ("id not digits", page([bad_id("68x")]), "payload_invalid"),
            ("id none", page([bad_id(None)]), "payload_invalid"),
        ]
        for name, answer, code in table:
            with self.subTest(name):
                with self.assertRaises(ForgeError) as raised:
                    read(answer)
                self.assertEqual(raised.exception.code, code)

    def test_an_integer_comment_id_is_read_and_a_boolean_is_refused(self):
        def node(value):
            return issue_node(7, [{**comment_node(C1, decision_body()), "fullDatabaseId": value}])

        self.assertEqual([i["comment_id"] for i in read(page([node(C1)]))], [C1])
        with self.assertRaises(ForgeError) as raised:
            read(page([node(True)]))
        self.assertEqual(raised.exception.code, "payload_invalid")

    def test_a_repeated_cursor_fails_the_read(self):
        with self.assertRaises(ForgeError) as raised:
            read(page([], more=True, cursor="c1", count=0), page([], more=True, cursor="c1", count=0))
        self.assertEqual(raised.exception.code, "payload_invalid")

    def test_the_search_filters_by_both_labels(self):
        calls = []
        answers = [page([], more=True, cursor="c1", count=0), page([], count=0)]

        def call(argv):
            calls.append(argv)
            return answers[len(calls) - 1]

        inbox.read_items(PROJECT, SLUG, call=call)
        self.assertEqual([c[:2] for c in calls], [["api", "graphql"]] * 2)
        self.assertIn("search=repo:octo/widgets is:open label:owner-action,owner-answered", calls[0])
        self.assertFalse([a for a in calls[0] if a.startswith("after=")])
        self.assertIn("after=c1", calls[1])

    def test_a_cancelled_read_stops_before_the_next_call(self):
        calls = []
        with self.assertRaises(ForgeError) as raised:
            inbox.read_items(PROJECT, SLUG, call=self.endless(calls), cancelled=lambda: True)
        self.assertEqual((raised.exception.code, len(calls)), ("cancelled", 0))
        calls.clear()
        with self.assertRaises(ForgeError) as raised:
            inbox.read_items(PROJECT, SLUG, call=self.endless(calls), cancelled=lambda: len(calls) >= 1)
        self.assertEqual((raised.exception.code, len(calls)), ("cancelled", 1))


class ActivityTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()

    def layout(self):
        """A main checkout with a linked worktree `wt`; returns (main, wt, main git dir, worktree git dir)."""
        main = self.root / "main"
        git = main / ".git"
        gitdir = git / "worktrees" / "wt"
        (git / "logs").mkdir(parents=True)
        (gitdir / "logs").mkdir(parents=True)
        (gitdir / "commondir").write_text("../..\n", encoding="utf-8")
        wt = self.root / "wt"
        wt.mkdir()
        (wt / ".git").write_text(f"gitdir: {gitdir}\n", encoding="utf-8")
        return main, wt, git, gitdir

    def touch(self, path, when):
        path.write_text("x", encoding="utf-8")
        os.utime(path, (when, when))

    def test_local_activity_is_the_newest_git_write(self):
        now = datetime.now(timezone.utc).timestamp()
        main, wt, git, gitdir = self.layout()
        self.touch(git / "FETCH_HEAD", now - 3000)
        self.touch(git / "logs" / "HEAD", now - 2000)
        self.touch(gitdir / "logs" / "HEAD", now - 100)
        self.assertAlmostEqual(inbox.local_activity(str(main)), now - 100, delta=1e-3)
        self.assertAlmostEqual(inbox.local_activity(str(wt)), now - 100, delta=1e-3)
        empty = self.root / "empty"
        empty.mkdir()
        self.assertIsNone(inbox.local_activity(str(empty)))

    def test_a_linked_worktree_reads_the_common_dir(self):
        now = datetime.now(timezone.utc).timestamp()
        main, wt, git, gitdir = self.layout()
        self.touch(gitdir / "logs" / "HEAD", now - 5000)
        self.touch(git / "index", now - 10)
        self.assertAlmostEqual(inbox.local_activity(str(wt)), now - 10, delta=1e-3)

    def test_a_fetch_in_a_linked_worktree_counts(self):
        now = datetime.now(timezone.utc).timestamp()
        main, wt, git, gitdir = self.layout()
        for path in (git / "FETCH_HEAD", git / "logs" / "HEAD", git / "index",
                     gitdir / "logs" / "HEAD", gitdir / "index"):
            self.touch(path, now - 5000)
        self.touch(gitdir / "FETCH_HEAD", now - 50)
        self.assertAlmostEqual(inbox.local_activity(str(main)), now - 50, delta=1e-3)
        self.assertAlmostEqual(inbox.local_activity(str(wt)), now - 50, delta=1e-3)

    def test_activity_within_one_day_is_active(self):
        now = 1_800_000_000.0

        def iso(seconds):
            return datetime.fromtimestamp(now - seconds, timezone.utc).isoformat()

        table = [
            (iso(100), None, True),
            (iso(86400), None, True),
            (iso(86401), None, False),
            (iso(200000), now - 10, True),
            (None, None, False),
            ("t5", None, False),
            (datetime.fromtimestamp(now - 100, timezone.utc).replace(tzinfo=None).isoformat(), None, False),
        ]
        for last, local, want in table:
            with self.subTest(last=last, local=local):
                self.assertIs(inbox.is_active(last, local, now), want)


if __name__ == "__main__":
    unittest.main()
