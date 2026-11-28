"""The console's inbox reader (#859): owner-action markers into inbox items, and the local activity reading."""

import base64
import copy
import hashlib
import json
import os
import re
import tempfile
import unittest
from unittest import mock
from datetime import datetime, timezone
from pathlib import Path

from agent_tools.claims import forge_markers as fm
from agent_tools.claims import forge_owner_action as foa
from agent_tools import canonical
from agent_tools.console import inbox, pictures
from agent_tools.console import event_log, view
from agent_tools.delivery import look_marker
from agent_tools.system import forge_api
from agent_tools.system.forge_api import ForgeError
from agent_tools.verification import verify_answer, verify_issues
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)
from .console_test_support import JPEG, PIXEL, WIDE

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


def issue_node(number, comments, blocking=0, blocks=()):
    return {"__typename": "Issue", "number": number, "issueDependenciesSummary": {"blocking": blocking},
            "blocking": {"totalCount": len(blocks),
                         "nodes": [{"number": n, "state": state, "repository": {"nameWithOwner": repo}}
                                   for n, state, repo in blocks]},
            "comments": {"totalCount": len(comments), "nodes": comments}}


def held_issue(number, body, comments=(), labels=("needs-verification",), assoc="OWNER", blocking=0):
    return {**issue_node(number, list(comments), blocking), "authorAssociation": assoc, "body": body,
            "labels": {"nodes": [{"name": n} for n in labels]}}


def ac_body(*lines):
    return "## Problem\n\nx\n\n## Acceptance criteria\n\n" + "\n".join(lines) + "\n\n## Blocked by\n\n- #1112\n"


HUMAN_HEADING = "The card looks right at 1440 and 480 px"
HUMAN_TEXT = f"{HUMAN_HEADING} \u2014 measured: the owner judges before and after pictures"
HUMAN = f"- [ ] [human] {HUMAN_TEXT}"


def pr_node(number, comments):
    return {"__typename": "PullRequest", "number": number,
            "comments": {"totalCount": len(comments), "nodes": comments}}


def page(nodes, more=False, cursor=None, count=None):
    return {"data": {"search": {"issueCount": len(nodes) if count is None else count,
                                "pageInfo": {"hasNextPage": more, "endCursor": cursor}, "nodes": nodes}}}


def read(*pages, **kwargs):
    answers = list(pages)
    return inbox.read_items(PROJECT, SLUG, call=lambda argv: answers.pop(0) if answers else page([]), **kwargs)


def graphql_read(*pages, **kwargs):
    """`read`, but the answer holds only what the outgoing query selects, as GraphQL answers."""
    answers = list(pages)

    def answer(argv):
        text = " ".join(next(a for a in argv if a.startswith("query=")).split())
        fragment = text.split("... on Issue {", 1)[1].split("... on PullRequest", 1)[0]
        reply = copy.deepcopy(answers.pop(0) if answers else page([]))
        selection = ""
        if "blocking(first: 100) {" in fragment:
            start = fragment.index("blocking(first: 100) {")
            depth, end = 0, start
            for end in range(fragment.index("{", start), len(fragment)):
                depth += {"{": 1, "}": -1}.get(fragment[end], 0)
                if depth == 0:
                    break
            selection = fragment[start:end + 1]
        for node in reply["data"]["search"]["nodes"]:
            if node.get("__typename") != "Issue":
                continue
            if not selection:
                node.pop("blocking", None)
                continue
            connection = node["blocking"]
            if not re.search(r"\btotalCount\b", selection):
                connection.pop("totalCount", None)
            for blocked in connection["nodes"]:
                for name in ("number", "state", "repository"):
                    if not re.search(rf"\b{name}\b", selection):
                        blocked.pop(name, None)
                if "repository" in blocked and not re.search(r"\bnameWithOwner\b", selection):
                    blocked["repository"].pop("nameWithOwner", None)
        return reply
    return inbox.read_items(PROJECT, SLUG, call=answer, **kwargs)


def expected(issue, comment_id, reason, **fields):
    return {"key": f"{SLUG}#{issue}/{comment_id}", "project_id": PROJECT, "repo": SLUG, "issue": issue,
            "comment_id": comment_id, "url": f"https://github.com/{SLUG}/issues/{issue}#issuecomment-{comment_id}",
            "reason": reason, "kind": reason, "question": foa.SENTENCES.get(reason), "detail": "",
            "questions": [], "items": [], "answers": [], "paid": False, "confirm": "",
            "answered": False, "blocking": [], **fields}


MERGE = "a" * 40
NOW = datetime(2026, 11, 16, 10, tzinfo=timezone.utc)


def held_node(number, comments, branch="main"):
    """An issue node that also names its repository's default branch."""
    return {**issue_node(number, comments), "repository": {"defaultBranchRef": {"name": branch}}}


def dated_comment(cid, body, created, assoc="OWNER"):
    return {**comment_node(cid, body, assoc), "createdAt": created, "updatedAt": created}


def hold_body(*checks):
    block = {"v": 1, "merge": MERGE, "checks": list(checks)}
    return "Held for verification.\n\n```verify\n" + json.dumps(block) + "\n```\n"


def window_body(event):
    return fm.render(verify_issues.WINDOW, {"event": event, "merge": MERGE, "host": "mbp"}, "The window opened.")


def prompt_body(block_key, check):
    return verify_body("verify-ask", {"host": "mbp", "block": block_key, "check": str(check)},
                       SENTENCES["verify-ask"], f"{ASK_TEXT}\n\n{ASK_BOXES}")


def three_nodes():
    return [issue_node(7, [comment_node(C1, decision_body())], blocking=2),
            issue_node(8, [comment_node(C2, bullet_body("conflict", ["Merge conflict in flake.lock"]))]),
            pr_node(9, [comment_node(C3, bullet_body("needs-label", ["needs the agent:human-required label"]))])]


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
            expected(9, C3, "needs-label", held_work=1, items=["needs the agent:human-required label"]),
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
            (11, ask(), "verify-ask", ("manual-check", ["passed", "failed", "note"], False, "", "", False)),
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
                question, check_id = (ASK_TEXT, "AC1") if reason == "verify-ask" else (SENTENCES[reason], "")
                self.assertRegex(item["version"], r"^sha256:[0-9a-f]{64}$")
                self.assertEqual({k: v for k, v in item.items() if k != "version"},
                                 expected(n, C1 + n, reason, kind=kind, answers=answers, paid=paid,
                                          confirm=confirm, detail=detail, answered=answered,
                                          question=question, check_id=check_id, reading="", held_work=1))
        self.assertEqual(json.loads(json.dumps(items)), items)

    def test_an_issue_lists_the_open_issues_it_blocks_in_its_own_repository(self):
        blocks = [(21, "OPEN", SLUG), (20, "OPEN", SLUG.upper()), (21, "OPEN", SLUG), (22, "CLOSED", SLUG),
                  (23, "OPEN", "someone/else")]
        nodes = [issue_node(7, [comment_node(C1, decision_body())], blocking=2, blocks=blocks),
                 issue_node(8, [comment_node(C2, ask())], blocks=[(30, "OPEN", SLUG)]),
                 pr_node(9, [comment_node(C3, bullet_body("needs-label", ["needs the label"]))])]
        items = graphql_read(page(nodes))
        self.assertEqual({i["issue"]: i["blocking"] for i in items}, {7: [20, 21], 8: [30], 9: []})
        self.assertEqual([i["held_work"] for i in items if i["issue"] == 7], [3])

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
                         [("manual-check", False, ""), ("verdict", False, "")])

    def test_detail_keeps_checkbox_lines_that_are_not_the_runners_boxes(self):
        text = "Open the staging site.\n- [ ] Check the dock too"
        body = ask(f"{text}\n\n- [ ] Accept\n- [ ] Reject")
        self.assertEqual(self.one(comment_node(C1, body))[0]["detail"], "- [ ] Check the dock too")
        fenced = "```\n- [ ] Restart the service\nopen the dock\n```\n\nThen: probe deployed_includes"
        body = verify_body("verify-act", {"host": "mbp"}, SENTENCES["verify-act"], fenced)
        self.assertEqual(self.one(comment_node(C1, body))[0]["detail"], fenced)
        next_to = ask(f"\n{text}\n- [ ] Accept now\n- [ ] Accept\n- [ ] Reject")
        self.assertEqual(self.one(comment_node(C1, next_to))[0]["detail"],
                         "- [ ] Check the dock too\n- [ ] Accept now")

    def test_a_carriage_return_does_not_reach_the_detail(self):
        body = ask(f"{ASK_TEXT}\r\n\r\n- [ ] Accept\r\n- [ ] Reject\r\n")
        item = self.one(comment_node(C1, body))[0]
        self.assertEqual((item["question"], item["detail"]), (ASK_TEXT, ""))


DEMO_ASK = ("Open the console at 1440 px and say whether the question is readable at a glance. "
            "Note anything that hides it.")
DEMO_QUESTION = "Open the console at 1440 px and say whether the question is readable at a glance."
DEMO_REST = "Note anything that hides it."


def asked(text, sentence=SENTENCES["verify-ask"]):
    return verify_body("verify-ask", {"host": "mbp"}, sentence, f"{text}\n\n{ASK_BOXES}")


def heading(body):
    item = read(page([issue_node(7, [comment_node(C1, body)])]))[0]
    return item["question"], item["check_id"], item["detail"]


class AskHeadingTest(unittest.TestCase):
    def test_the_demo_ask_heads_its_item(self):
        body = asked(DEMO_ASK, "A3: the owner's answer is needed.")
        self.assertEqual(heading(body), (DEMO_QUESTION, "A3", DEMO_REST))

    def test_the_first_sentence_ends_at_its_terminator(self):
        table = [
            ("Is the dock bright? Say so.", "Is the dock bright?", "Say so."),
            ("Open it! Then look.", "Open it!", "Then look."),
            ('Type "yes." Then stop.', 'Type "yes."', "Then stop."),
            ("Open the dock (then the bar.) Then look.", "Open the dock (then the bar.)", "Then look."),
            ("Check that v1.2 runs and stop.", "Check that v1.2 runs and stop.", ""),
            ("Open the dock", "Open the dock", ""),
            ("Open   the\tsite.   Then look.", "Open the site.", "Then look."),
            ("Open the dock\nthen look.", "Open the dock", "then look."),
            ("Open the dock.\n\nThen look.", "Open the dock.", "Then look."),
        ]
        for text, question, detail in table:
            with self.subTest(text=text):
                self.assertEqual(heading(asked(text)), (question, "AC1", detail))

    def test_an_ask_the_reader_cannot_split_keeps_its_sentence(self):
        sentence = SENTENCES["verify-ask"]
        table = {
            "not the runner's shape": (verify_body("verify-ask", {"host": "mbp"}, "Recorded.",
                                                   f"{ASK_TEXT}\n\n{ASK_BOXES}"), ("Recorded.", "", ASK_TEXT)),
            "a fenced first line": (asked("```\nopen the dock\n```"), (sentence, "", "```\nopen the dock\n```")),
            "a tilde fence": (asked("~~~\nopen the dock\n~~~"), (sentence, "", "~~~\nopen the dock\n~~~")),
            "only boxes": (verify_body("verify-ask", {"host": "mbp"}, sentence, ASK_BOXES), (sentence, "", "")),
            "another reason": (verify_body("verify-act", {"host": "mbp"}, sentence, "Open the dock. Then look."),
                               (sentence, "", "Open the dock. Then look.")),
        }
        for name, (body, want) in table.items():
            with self.subTest(name):
                self.assertEqual(heading(body), want)


def reading_item(body):
    return read(page([issue_node(7, [comment_node(C1, body)])]))[0]


class ReadingTest(unittest.TestCase):
    def test_a_reading_check_carries_its_instruction_apart(self):
        item = reading_item(asked("Is the idle draw under 40 W? Reading: the watts on the plug meter after five idle minutes."))
        self.assertEqual(item["question"], "Is the idle draw under 40 W?")
        self.assertEqual(item["check_id"], "AC1")
        self.assertEqual(item["reading"], "the watts on the plug meter after five idle minutes.")
        self.assertEqual(item["detail"], "")

    def test_text_around_the_reading_stays_in_the_detail(self):
        item = reading_item(asked("Is the idle draw under 40 W? Wait five minutes. Reading:   the  watts on the meter"))
        self.assertEqual(item["reading"], "the watts on the meter")
        self.assertEqual(item["detail"], "Wait five minutes.")

    def test_an_ask_without_a_reading_reads_empty(self):
        item = reading_item(ask())
        self.assertEqual((item["reading"], item["detail"]), ("", ""))

    def test_only_a_manual_check_is_read(self):
        item = reading_item(decision(extra="Reading: the meter\n\n" + DECISION_BOXES))
        self.assertEqual((item["reading"], item["detail"]), ("", "Reading: the meter"))

    def test_a_reading_inside_a_fence_is_not_read(self):
        body = verify_body("verify-ask", {"host": "mbp"}, SENTENCES["verify-ask"],
                           "```\nReading: x\n```\n\n" + ASK_BOXES)
        item = reading_item(body)
        self.assertEqual(item["reading"], "")
        self.assertIn("Reading: x", item["detail"])

    def test_an_empty_reading_is_no_reading(self):
        item = reading_item(asked("Is it on? Reading:"))
        self.assertEqual((item["reading"], item["detail"]), ("", "Reading:"))

    def test_only_the_first_reading_is_taken(self):
        item = reading_item(asked("Is it on? Reading: the lamp\nReading: the fan"))
        self.assertEqual((item["reading"], item["detail"]), ("the lamp", "Reading: the fan"))


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


class PromptPictureTest(unittest.TestCase):
    """The pictures a verification prompt names (#1112): anchored opening under the allowed roots."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(os.path.realpath(tmp.name))
        self.root, self.screens, self.outside = base / "root", base / "screens", base / "outside"
        for directory in (self.root, self.root / "shots", self.screens, self.outside):
            directory.mkdir()
        self.pictures_dir = base / "console" / "pictures"

    def check(self, detail):
        return {"question": "Do these read well?", "detail": detail, "reading": "", "check_id": "AC1",
                "reason": "verify-ask", "version": "v"}

    def ids(self, data):
        return hashlib.sha256(data).hexdigest()

    def attach(self, detail, roots=None):
        roots = [self.root, self.screens] if roots is None else roots
        return inbox.attach_pictures(self.check(detail), roots, self.pictures_dir, home=self.root)

    def stored(self, data):
        return pictures.read(self.pictures_dir, self.ids(data))

    def test_named_pngs_in_a_named_folder_become_pictures_with_their_file_names(self):
        (self.root / "shots" / "before.png").write_bytes(PIXEL)
        (self.root / "shots" / "after.png").write_bytes(WIDE)
        got = self.attach("Screenshots in shots/: before.png and after.png.")
        self.assertEqual(got["pictures"], [{"id": self.ids(PIXEL), "line": "before.png", "pair": None},
                                           {"id": self.ids(WIDE), "line": "after.png", "pair": None}])
        self.assertEqual(got["missing_pictures"], [])
        self.assertEqual(self.stored(PIXEL), PIXEL)

    def test_an_absolute_and_a_home_path_resolve(self):
        (self.root / "shots" / "before.png").write_bytes(PIXEL)
        (self.root / "shots" / "after.png").write_bytes(WIDE)
        got = self.attach(f"{self.root / 'shots' / 'before.png'} and `~/shots/after.png`")
        self.assertEqual([p["id"] for p in got["pictures"]], [self.ids(PIXEL), self.ids(WIDE)])

    def test_a_folder_named_alone_lists_its_pngs_by_name(self):
        for name in ("b.png", "a.png", "c.PNG", "notes.txt"):
            (self.root / "shots" / name).write_bytes(PIXEL)
        got = self.attach("See shots/ for the pictures.")
        self.assertEqual([p["line"] for p in got["pictures"]], ["a.png", "b.png", "c.PNG"])

    def test_a_missing_named_png_is_a_missing_line(self):
        got = self.attach("shots/ gone.png")
        self.assertEqual(got["pictures"], [])
        self.assertEqual(got["missing_pictures"], ["gone.png"])

    def test_a_png_outside_the_roots_is_not_served(self):
        (self.outside / "x.png").write_bytes(PIXEL)
        got = self.attach(str(self.outside / "x.png"))
        self.assertEqual(got["pictures"], [])
        self.assertEqual(got["missing_pictures"], [])
        self.assertIsNone(self.stored(PIXEL))

    def test_a_symlink_out_of_a_root_is_not_served(self):
        (self.outside / "x.png").write_bytes(PIXEL)
        (self.root / "link.png").symlink_to(self.outside / "x.png")
        got = self.attach("link.png")
        self.assertEqual(got["pictures"], [])
        self.assertEqual(got["missing_pictures"], [])
        self.assertIsNone(self.stored(PIXEL))

    def test_a_png_named_file_that_is_not_a_png_is_not_served(self):
        (self.root / "fake.png").write_bytes(JPEG)
        got = self.attach("fake.png")
        self.assertEqual(got["pictures"], [])
        self.assertIsNone(self.stored(JPEG))

    def test_a_configured_screenshot_location_is_a_root(self):
        (self.screens / "s.png").write_bytes(WIDE)
        detail = str(self.screens / "s.png")
        got = self.attach(detail)
        self.assertEqual([p["line"] for p in got["pictures"]], ["s.png"])
        self.assertEqual(self.attach(detail, roots=[self.root])["pictures"], [])

    def test_a_file_over_the_size_limit_is_not_served(self):
        (self.root / "big.png").write_bytes(PIXEL[:33] + b"\0" * pictures.MAX_BYTES)
        self.assertEqual(self.attach("big.png")["pictures"], [])

    def test_at_most_eight_pictures_and_eight_missing_lines(self):
        for i in range(10):
            (self.root / "shots" / f"p{i}.png").write_bytes(PIXEL[:33] + bytes([i]))
        self.assertEqual(len(self.attach("shots/")["pictures"]), 8)
        for i in range(10):
            (self.root / "shots" / f"p{i}.png").unlink()
        got = self.attach("shots/ " + " ".join(f"m{i}.png" for i in range(10)))
        self.assertEqual(len(got["missing_pictures"]), 8)

    def test_the_result_is_the_same_on_every_call_and_the_item_is_not_changed(self):
        (self.root / "shots" / "before.png").write_bytes(PIXEL)
        item = self.check("shots/ before.png gone.png")
        roots = [self.root, self.screens]
        first = inbox.attach_pictures(item, roots, self.pictures_dir, home=self.root)
        second = inbox.attach_pictures(item, roots, self.pictures_dir, home=self.root)
        self.assertEqual(first, second)
        self.assertNotIn("pictures", item)

    def test_a_url_is_not_a_folder(self):
        (self.root / "shots" / "before.png").write_bytes(PIXEL)
        got = self.attach("see https://github.com/octo/widgets/pull/1 and shots/before.png")
        self.assertEqual(len(got["pictures"]), 1)
        self.assertEqual(inbox.named_pictures("see https://x.org/a.png")[1], [])
        self.assertEqual(inbox.named_pictures("see https://github.com/octo/widgets/pull/1"), ([], []))
        self.assertEqual(inbox.named_pictures("see https://x.org/a.png"), ([], []))

    def test_an_ancestor_swapped_for_a_symlink_after_the_check_is_not_followed(self):
        (self.outside / "before.png").write_bytes(PIXEL)
        (self.root / "shots").rmdir()
        (self.root / "shots").symlink_to(self.outside)
        with mock.patch("os.path.realpath",
                        side_effect=lambda p, *a, **k: os.path.normpath(os.path.abspath(p))):
            got = self.attach("shots/before.png")
        self.assertEqual(got["pictures"], [])
        self.assertEqual(got["missing_pictures"], [])
        self.assertIsNone(self.stored(PIXEL))
        self.assertEqual(list(self.pictures_dir.glob("*")) if self.pictures_dir.exists() else [], [])

    def test_a_long_file_name_is_cut_to_140_characters(self):
        name = "a" * 150 + ".png"
        (self.root / "shots" / name).write_bytes(PIXEL)
        self.assertEqual(self.attach("shots/")["pictures"][0]["line"], name[:140])

    def test_a_path_is_listed_once(self):
        (self.root / "shots" / "before.png").write_bytes(PIXEL)
        got = self.attach("shots/before.png and ~/shots/before.png and shots/")
        self.assertEqual(got["pictures"], [{"id": self.ids(PIXEL), "line": "before.png", "pair": None}])


    def test_a_source_file_named_as_a_folder_does_not_hide_a_png_under_the_root(self):
        (self.root / "src").mkdir()
        (self.root / "src" / "app.py").write_text("x")
        (self.root / "shot.png").write_bytes(PIXEL)
        got = self.attach("Changed src/app.py; see shot.png")
        self.assertEqual(got["pictures"], [{"id": self.ids(PIXEL), "line": "shot.png", "pair": None}])
        self.assertEqual(got["missing_pictures"], [])

    def test_a_png_under_a_source_file_and_nowhere_else_is_missing(self):
        (self.root / "src").mkdir()
        (self.root / "src" / "app.py").write_text("x")
        got = self.attach("Changed src/app.py; see shot.png")
        self.assertEqual(got["pictures"], [])
        self.assertEqual(got["missing_pictures"], ["shot.png"])

    def test_a_parent_folder_is_listed_after_a_listed_subfolder(self):
        (self.root / "shots" / "sub").mkdir()
        (self.root / "shots" / "sub" / "a.png").write_bytes(PIXEL)
        (self.root / "shots" / "b.png").write_bytes(WIDE)
        got = self.attach("shots/sub/ shots/")
        self.assertEqual([p["line"] for p in got["pictures"]], ["a.png", "b.png"])

    def test_a_review_heading_loses_a_relative_folder_only_when_the_folder_exists(self):
        (self.root / "shots" / "a.png").write_bytes(PIXEL)
        text = "Judge the cards in shots/sub and light/dark here"
        item = {**self.check(""), "question": text, "criterion_text": text, "check_id": ""}
        got = inbox.attach_pictures(item, [self.root, self.screens], self.pictures_dir, home=self.root)
        self.assertEqual(got["question"], text)
        (self.root / "shots" / "sub").mkdir()
        (self.root / "shots" / "sub" / "b.png").write_bytes(WIDE)
        got = inbox.attach_pictures(item, [self.root, self.screens], self.pictures_dir, home=self.root)
        self.assertEqual(got["question"], "Judge the cards and light/dark here")
        self.assertEqual(got["criterion_text"], text)
        self.assertEqual([p["line"] for p in got["pictures"]], ["b.png"])


class HeldReviewTest(unittest.TestCase):
    """A held issue whose only open criteria are owner reviews raises one review item each (#1113)."""

    def review(self, issue, index, text, held_work=1, heading=None):
        return {"key": f"{SLUG}#{issue}/ac{index}", "project_id": PROJECT, "repo": SLUG, "issue": issue,
                "comment_id": None, "url": f"https://github.com/{SLUG}/issues/{issue}",
                "reason": "held-review", "kind": "owner-review", "question": heading or text, "criterion_text": text,
                "detail": text,
                "check_id": "", "reading": "", "questions": [], "items": [], "answers": ["passed", "note"],
                "paid": False, "confirm": "", "answered": False, "held_work": held_work, "blocking": [],
                "version": canonical.telemetry_digest({"issue": issue, "index": index, "kind": "human",
                                                       "text": text}),
                "criterion": index}

    def test_a_held_issue_whose_only_open_criterion_is_human_yields_one_item(self):
        node = held_issue(1091, ac_body("- [x] [code] A", "- [x] [code] B", HUMAN), blocking=1)
        result = read(page([node]))
        self.assertEqual(result, [self.review(1091, 3, HUMAN_TEXT, held_work=2, heading=HUMAN_HEADING)])
        self.assertEqual(result[0]["key"], "octo/widgets#1091/ac3")
        self.assertIsNone(result[0]["comment_id"])
        self.assertEqual(json.loads(json.dumps(result)), result)

    def test_an_open_evidence_or_untagged_criterion_raises_no_review_item(self):
        control = inbox.items_from_node(PROJECT, SLUG, held_issue(7, ac_body("- [x] [code] A", HUMAN)))
        self.assertEqual([i["reason"] for i in control], ["held-review"])
        for extra in ("- [ ] [evidence] E", "- [ ] U"):
            with self.subTest(extra):
                node = held_issue(7, ac_body("- [x] [code] A", extra, HUMAN))
                self.assertEqual(inbox.items_from_node(PROJECT, SLUG, node), [])

    def test_an_open_code_criterion_of_a_held_issue_counts_as_met(self):
        node = held_issue(7, ac_body("- [ ] [code] Unmeasured", "- [ ] [code] Other", HUMAN))
        items = inbox.items_from_node(PROJECT, SLUG, node)
        self.assertEqual([i["key"] for i in items], [f"{SLUG}#7/ac3"])

    def test_any_list_marker_spacing_still_reads_the_criterion(self):
        for bullet in ("-  ", "-\t", "*   ", "+  "):
            with self.subTest(bullet):
                body = ac_body(HUMAN, f"{bullet}[ ] [evidence] Unfinished")
                self.assertEqual([c.kind for c in inbox.acceptance_criteria(body)], ["human", "evidence"])
                self.assertEqual(inbox.items_from_node(PROJECT, SLUG, held_issue(7, body)), [])
        spaced = ac_body(HUMAN, "-  [x] [evidence] Done")
        self.assertEqual([i["criterion"] for i in inbox.items_from_node(PROJECT, SLUG, held_issue(7, spaced))], [1])

    def test_a_verify_block_check_for_the_criterion_suppresses_its_item(self):
        def block(*acs, assoc="OWNER", fenced=True):
            checks = [{"ac": ac, "kind": "human", "host": "any", "when": {"not_before": "2026-11-16T00:00:00Z"},
                       "run": {"ask": "Does it look right?"}} for ac in acs]
            text = json.dumps({"v": 1, "merge": "a" * 40, "checks": checks})
            return dated_comment(C2, f"Held.\n\n```verify\n{text}\n```\n" if fenced else text, CREATED, assoc)

        body = ac_body("- [ ] [code] A", "- [ ] [human] One", "- [ ] [human] Two")

        def keys(*comments):
            node = {**held_issue(7, body, comments=comments), "repository": {"defaultBranchRef": {"name": "main"}}}
            return [i["key"] for i in inbox.items_from_node(PROJECT, SLUG, node, lambda: NOW)
                    if i["reason"] == "held-review"]

        self.assertEqual(keys(), [f"{SLUG}#7/ac2", f"{SLUG}#7/ac3"])
        self.assertEqual(keys(block("AC2")), [f"{SLUG}#7/ac3"])
        self.assertEqual(keys(block("AC2", "AC3")), [])
        self.assertEqual(keys(block("ac3")), [f"{SLUG}#7/ac2"])
        self.assertEqual(keys(block("AC1")), [f"{SLUG}#7/ac2", f"{SLUG}#7/ac3"])
        self.assertEqual(keys(block("AC2", "AC3", assoc="CONTRIBUTOR")), [f"{SLUG}#7/ac2", f"{SLUG}#7/ac3"])
        self.assertEqual(keys(block("AC2", "AC3", fenced=False)), [f"{SLUG}#7/ac2", f"{SLUG}#7/ac3"])
        newer = dated_comment(C3, f"Held again.\n\n```verify\n{json.dumps({'v': 1, 'merge': 'a' * 40, 'checks': []})}\n```\n",
                              CREATED)
        self.assertEqual(keys(block("AC2", "AC3"), newer), [f"{SLUG}#7/ac2", f"{SLUG}#7/ac3"])

    def test_a_card_heading_names_no_file_or_folder_and_the_whole_text_stays_beside_it(self):
        table = {
            "The brief and report cards look right at 1440 and 480 px \u2014 measured: the owner judges the PNG "
            "screenshots under /tmp/held-review-screenshots": "The brief and report cards look right at 1440 and 480 px",
            "The brief and report cards look right at 1440 and 480 px - measured: the owner judges the PNG "
            "screenshots under /x": "The brief and report cards look right at 1440 and 480 px",
            "The card looks right \u2013 MEASURED: the owner judges shots/a.png": "The card looks right",
            "Measured: the owner judges it": "Measured: the owner judges it",
            "A well-measured: card": "A well-measured: card",
            "The card looks right in shots/before.png and shots/after.png": "The card looks right",
            "Look at ~/shots/a.png.": "Look.",
            "See https://example.org/a/b": "See https://example.org/a/b",
            "shots/a.png": inbox.REVIEW_HEADING,
        }
        for text, heading in table.items():
            with self.subTest(text):
                node = held_issue(7, ac_body(f"- [ ] [human] {text}"))
                item, = inbox.items_from_node(PROJECT, SLUG, node)
                self.assertEqual((item["question"], item["criterion_text"]), (heading, text))

    def test_the_detail_keeps_the_whole_text_with_the_measured_tail(self):
        for dash in ("\u2014", "-", "\u2013"):
            text = f"The cards look right at 1440 px {dash} measured: the owner judges the PNG screenshots under /x"
            with self.subTest(dash):
                item, = inbox.items_from_node(PROJECT, SLUG, held_issue(7, ac_body(f"- [ ] [human] {text}")))
                self.assertEqual((item["question"], item["detail"]), ("The cards look right at 1440 px", text))

    def test_a_word_with_a_slash_that_names_no_path_stays_in_the_heading(self):
        for text in ("The Approve/Not yet buttons both work", "Light/dark themes both look right",
                     "The card reads well at 1440/480 px", "The PR for octo/widgets#1113 shows the card",
                     "Tests pass and/or are skipped", "Cost is N/A today"):
            with self.subTest(text):
                node = held_issue(7, ac_body(f"- [ ] [human] {text}"))
                item, = inbox.items_from_node(PROJECT, SLUG, node)
                self.assertEqual((item["question"], item["criterion_text"]), (text, text))
        for text, heading in (("Judge ./shots/a.png and ../x/ and shots/ now", "Judge now"),
                              ("Open ~/shots under /tmp/s please", "Open please")):
            with self.subTest(text):
                node = held_issue(7, ac_body(f"- [ ] [human] {text}"))
                self.assertEqual(inbox.items_from_node(PROJECT, SLUG, node)[0]["question"], heading)

    def test_a_fence_in_a_list_item_ends_with_the_item(self):
        ended = ac_body("- [ ] [human] One", "  ```", "  example", "- [ ] [evidence] Two")
        self.assertEqual([(c.kind, c.text) for c in inbox.acceptance_criteria(ended)],
                         [("human", "One"), ("evidence", "Two")])
        self.assertEqual(inbox.items_from_node(PROJECT, SLUG, held_issue(7, ended)), [])
        reopened = ac_body("- [ ] [human] One", "  ```", "  x", "```", "- [ ] [human] Two")
        self.assertEqual([c.text for c in inbox.acceptance_criteria(reopened)], ["One"])
        kept = ac_body("- [ ] [human] One", "  ```", "", "  - [ ] [code] inner", "  ```", "- [ ] [human] Two")
        self.assertEqual([c.text for c in inbox.acceptance_criteria(kept)], ["One", "Two"])

    def test_a_heading_with_a_trailing_colon_opens_the_section(self):
        for heading in ("## Acceptance criteria:", "### acceptance criteria :", "## Acceptance criteria: ##"):
            with self.subTest(heading=heading):
                body = f"## Problem\n\nx\n\n{heading}\n\n- [ ] [human] One\n"
                self.assertEqual([c.text for c in inbox.acceptance_criteria(body)], ["One"])
        self.assertEqual(inbox.acceptance_criteria("## Acceptance criteria: none\n\n- [ ] One\n"), [])

    def test_a_heading_inside_a_list_item_does_not_end_the_section(self):
        body = ac_body("- [ ] [human] One", "  ### Details", "  more", "- [ ] [evidence] Two")
        self.assertEqual([(c.kind, c.text) for c in inbox.acceptance_criteria(body)],
                         [("human", "One"), ("evidence", "Two")])
        self.assertEqual(inbox.items_from_node(PROJECT, SLUG, held_issue(7, body)), [])
        outside = ac_body("- [ ] [human] One", "### Details", "- [ ] [evidence] Two")
        self.assertEqual([c.text for c in inbox.acceptance_criteria(outside)], ["One"])

    def test_a_fenced_example_nested_under_a_checkbox_is_no_criterion(self):
        for indent in ("    ", "  ", "\t"):
            with self.subTest(indent=repr(indent)):
                body = ac_body("- [ ] [human] Real one", f"{indent}```", f"{indent}- [ ] [human] Example only",
                               f"{indent}```", "- [ ] [human] Second")
                self.assertEqual([c.text for c in inbox.acceptance_criteria(body)], ["Real one", "Second"])
                items = inbox.items_from_node(PROJECT, SLUG, held_issue(7, body))
                self.assertEqual([i["question"] for i in items], ["Real one", "Second"])
        nested = ac_body("- [ ] [human] Real one", "    ```", "    - [ ] [code] Hidden example", "    ```")
        self.assertEqual([c.text for c in inbox.acceptance_criteria(nested)], ["Real one"])
        deep = ac_body("1. Step", "   - [ ] [human] Inner", "      ~~~", "      - [ ] [code] Example", "      ~~~")
        self.assertEqual([c.text for c in inbox.acceptance_criteria(deep)], ["Inner"])
        open_fence = ac_body("- [ ] [human] One", "    ```", "    - [ ] [code] Example")
        self.assertEqual([c.text for c in inbox.acceptance_criteria(open_fence)], ["One"])

    def test_a_fence_opened_after_a_list_marker_hides_its_example_boxes(self):
        for fence in ("~~~", "```"):
            with self.subTest(fence=fence):
                body = ac_body("- [ ] [human] Real one", f"- {fence}", "  - [ ] [human] Example", f"  {fence}",
                               "- [ ] [human] Second")
                self.assertEqual([c.text for c in inbox.acceptance_criteria(body)], ["Real one", "Second"])
        nested = ac_body("- - ~~~", "    - [ ] [code] Example", "    ~~~", "- [ ] [human] Real")
        self.assertEqual([c.text for c in inbox.acceptance_criteria(nested)], ["Real"])
        ordered = ac_body("1. ```", "   - [ ] [human] Example", "   ```", "- [ ] [human] Real")
        self.assertEqual([c.text for c in inbox.acceptance_criteria(ordered)], ["Real"])
        items = inbox.items_from_node(PROJECT, SLUG, held_issue(7, ac_body("- ~~~", "  - [ ] [human] Example", "  ~~~")))
        self.assertEqual(items, [])

    def test_a_live_runner_prompt_suppresses_the_review_item(self):
        node = held_issue(7, ac_body(HUMAN), comments=[comment_node(C1, ask())])
        self.assertEqual([i["reason"] for i in inbox.items_from_node(PROJECT, SLUG, node)], ["verify-ask"])
        control = inbox.items_from_node(PROJECT, SLUG, held_issue(7, ac_body(HUMAN)))
        self.assertEqual([i["reason"] for i in control], ["held-review"])
        ended = held_issue(7, ac_body(HUMAN),
                           comments=[comment_node(C1, ask()), comment_node(C2, fm.end_body(C1, "done"))])
        self.assertEqual([i["reason"] for i in inbox.items_from_node(PROJECT, SLUG, ended)], ["held-review"])

    def test_only_a_trusted_held_issue_is_read(self):
        body = ac_body(HUMAN)
        self.assertEqual(inbox.items_from_node(PROJECT, SLUG, held_issue(7, body, labels=("owner-action",))), [])
        for assoc in ("COLLABORATOR", "CONTRIBUTOR", "NONE"):
            with self.subTest(assoc):
                self.assertEqual(inbox.items_from_node(PROJECT, SLUG, held_issue(7, body, assoc=assoc)), [])
        for assoc in ("OWNER", "MEMBER"):
            with self.subTest(assoc):
                items = inbox.items_from_node(PROJECT, SLUG, held_issue(7, body, assoc=assoc))
                self.assertEqual(len(items), 1)

    def test_two_open_human_criteria_yield_two_items(self):
        node = held_issue(7, ac_body("- [ ] [human] One", "- [x] [code] A", "- [ ] [human] Two"))
        items = inbox.items_from_node(PROJECT, SLUG, node)
        self.assertEqual([i["key"] for i in items], [f"{SLUG}#7/ac1", f"{SLUG}#7/ac3"])
        self.assertEqual([i["question"] for i in items], ["One", "Two"])

    def test_an_open_note_criterion_blocks_nothing(self):
        node = held_issue(7, ac_body("- [ ] [note] Cost read after deploy", HUMAN))
        items = inbox.items_from_node(PROJECT, SLUG, node)
        self.assertEqual([i["criterion"] for i in items], [2])

    def test_criteria_are_read_only_from_the_acceptance_section_outside_fences(self):
        body = ("## What to build\n\n- [ ] [human] Not a criterion\n\n### Acceptance criteria\n\n```\n"
                "- [ ] [code] fenced\n```\n- [ ] [human] Real one\n\n## Blocked by\n\n- [ ] [code] after the section\n")
        line = body.split("\n").index("- [ ] [human] Real one")
        self.assertEqual(inbox.acceptance_criteria(body), [inbox.Criterion(1, False, "human", "Real one", line)])
        items = inbox.items_from_node(PROJECT, SLUG, held_issue(7, body))
        self.assertEqual([i["key"] for i in items], [f"{SLUG}#7/ac1"])
        ticked = inbox.acceptance_criteria("## Acceptance criteria\n\n- [X] [human] Y\n")
        self.assertTrue(ticked[0].ticked)
        crlf = inbox.acceptance_criteria("## Acceptance criteria\r\n\r\n- [ ] [human] Y z\r\n- [x] [code] W\r\n")
        self.assertEqual([c.text for c in crlf], ["Y z", "W"])
        self.assertEqual(inbox.acceptance_criteria("## Problem\n\n- [ ] [human] Y\n"), [])

    def test_the_version_names_the_criterion_it_was_read_from(self):
        def version(*lines):
            return inbox.criterion_version(7, inbox.acceptance_criteria(ac_body(*lines))[2])

        base = version("- [ ] [code] A", "- [ ] [code] B", "- [ ] [human] C")
        self.assertNotEqual(base, version("- [ ] [code] A", "- [ ] [code] B", "- [ ] [human] D"))
        self.assertEqual(base, version("- [x] [code] A", "- [ ] [code] B", "- [ ] [human] C"))

    def test_a_fence_closes_only_on_its_own_delimiter(self):
        mixed = "## Acceptance criteria\n\n```text\n~~~\n- [ ] [human] Example only\n```\n- [ ] [code] Still unfinished\n"
        want = [inbox.Criterion(1, False, "code", "Still unfinished", mixed.split("\n").index("- [ ] [code] Still unfinished"))]
        self.assertEqual(inbox.acceptance_criteria(mixed), want)
        self.assertEqual(inbox.items_from_node(PROJECT, SLUG, held_issue(7, mixed)), [])
        longer = "## Acceptance criteria\n\n````\n```\n- [ ] [human] Inside\n````\n- [ ] [human] Real\n"
        want = [inbox.Criterion(1, False, "human", "Real", longer.split("\n").index("- [ ] [human] Real"))]
        self.assertEqual(inbox.acceptance_criteria(longer), want)
        items = inbox.items_from_node(PROJECT, SLUG, held_issue(7, longer))
        self.assertEqual([(i["key"], i["question"]) for i in items], [(f"{SLUG}#7/ac1", "Real")])
        tilde = "## Acceptance criteria\n\n~~~\n- [ ] [human] In\n~~~~\n- [ ] [human] After\n"
        self.assertEqual([c.text for c in inbox.acceptance_criteria(tilde)], ["After"])
        texted = "## Acceptance criteria\n\n```\n``` x\n- [ ] [human] Still inside\n```\n- [ ] [human] Out\n"
        self.assertEqual([c.text for c in inbox.acceptance_criteria(texted)], ["Out"])


CREATED = "2026-11-10T09:00:00Z"
HOURLY = "Two days after the release, read the hourly rows on kestrel; there are no impossible_usage rows."


def human(when, ask="Read the hourly rows. Count them.", ac="AC1"):
    return {"ac": ac, "kind": "human", "when": when, "run": {"ask": ask}, "reason": "senses", "host": "mbp"}


def block_of(*checks):
    return {"v": 1, "merge": MERGE, "checks": list(checks)}


def future(when_ask=None):
    return human({"not_before": "2026-11-18T10:00:00+00:00"}, *([when_ask] if when_ask else []))


LOOK_LINE = "- [ ] [human] before merge: the settings page at 390 px \u2014 measured: the owner, on the console"
LOOK_HEAD = "1a2b3c4" + "d" * 33


def look(cid, answer="approved", head=LOOK_HEAD, pr=42, assoc="OWNER", issue=7):
    return comment_node(cid, look_marker.approval_body(issue, pr, head, answer, f"m{cid}"), assoc)


class Pulls:
    """A fake `gh` JSON call that answers the pull request 42 read and records every argv."""

    def __init__(self, merged=True, head=LOOK_HEAD):
        self.merged, self.head, self.argvs = merged, head, []

    def __call__(self, argv):
        self.argvs.append(argv)
        if argv != ["api", f"repos/{SLUG}/pulls/42"]:
            raise AssertionError(f"unexpected read {argv}")
        return {"number": 42, "merged": self.merged, "head": {"sha": self.head}}


def NEVER(argv):
    raise AssertionError("no pull request read")


class Forge:
    """A fake `gh` JSON call that answers each `repos/<slug>/<path>` read from a dict and records every argv."""

    def __init__(self, reads):
        self.reads, self.argvs = reads, []

    def __call__(self, argv):
        self.argvs.append(argv)
        prefix = f"repos/{SLUG}/"
        if len(argv) != 2 or argv[0] != "api" or not argv[1].startswith(prefix):
            raise AssertionError(f"unexpected read {argv}")
        path = argv[1][len(prefix):]
        if path not in self.reads:
            raise ForgeError("not_found", path)
        return self.reads[path]


KEPT_A, KEPT_BT, KEPT_MC, KEPT_FORK = "5" * 40, "3" * 40, "2" * 40, "e" * 40
KEPT_PAGE, KEPT_TESTF = "python/agent_tools/console/page.html", "tests/test_console_page.py"


def _kept_compare(files=(), status="ahead", commits=()):
    return {"status": status, "files": [{"filename": f, "status": "modified", "patch": f"@@ -1,2 +1,2 @@\n {f}\n-old\n+new"}
                                         for f in files],
            "total_commits": len(commits),
            "commits": [{"sha": sha, "parents": [{"sha": p} for p in parents]} for sha, parents in commits]}


def kept_reads(ah_files=(KEPT_TESTF,), pull_extra=None):
    """The reads of a merge of the look head over an approval of KEPT_A, as GitHub answers them."""
    raw = base64.b64encode(b'{"version": 1, "sets": {"console": ["python/agent_tools/console/**"]}}').decode()
    pull = {"number": 42, "merged": True, "head": {"sha": LOOK_HEAD}, "merge_commit_sha": KEPT_MC}
    pull.update(pull_extra or {})
    return {
        "pulls/42": pull,
        f"commits/{KEPT_MC}": {"sha": KEPT_MC, "parents": [{"sha": KEPT_BT}, {"sha": LOOK_HEAD}]},
        look_marker.contents_path(KEPT_BT): {"type": "file", "encoding": "base64", "content": raw},
        look_marker.compare_path(KEPT_BT, KEPT_A): _kept_compare([KEPT_PAGE], commits=[(KEPT_A, [KEPT_FORK])]),
        look_marker.compare_path(KEPT_A, LOOK_HEAD): _kept_compare(ah_files),
        look_marker.compare_path(KEPT_BT, LOOK_HEAD): _kept_compare(
            commits=[(KEPT_A, [KEPT_FORK]), (LOOK_HEAD, [KEPT_A])]),
    }


def keys(node, call, **kwargs):
    return [i["key"] for i in inbox.items_from_node(PROJECT, SLUG, node, call=call, **kwargs)]


class LookAnsweredReviewTest(unittest.TestCase):
    """An approved look of the merged head answers its look marker criterion (#1186, ADR-console-054)."""

    CARD = [f"{SLUG}#7/ac2"]

    def node(self, comments=(), body=None):
        return held_issue(7, body or ac_body("- [x] [code] A", LOOK_LINE), comments=list(comments))

    def test_an_approved_look_of_the_merged_head_raises_no_card(self):
        pulls = Pulls()
        self.assertEqual(keys(self.node([look(C1)]), pulls), [])
        self.assertEqual(pulls.argvs, [["api", f"repos/{SLUG}/pulls/42"]])
        self.assertEqual(keys(self.node(), NEVER), self.CARD)

    def test_an_approval_of_another_head_or_an_unmerged_pull_request_still_raises_the_card(self):
        cases = {"other head approved": ([look(C1, head="e" * 40)], Pulls()),
                 "unmerged": ([look(C1)], Pulls(merged=False)),
                 "merged other head": ([look(C1)], Pulls(head="e" * 40))}
        for name, (comments, pulls) in cases.items():
            with self.subTest(name=name):
                self.assertEqual(keys(self.node(comments), pulls), self.CARD)

    def test_a_changes_answer_still_raises_the_card_and_the_latest_answer_decides(self):
        self.assertEqual(keys(self.node([look(C1), look(C2, "changes")]), Pulls()), self.CARD)
        self.assertEqual(keys(self.node([look(C1, "changes"), look(C2)]), Pulls()), [])

    def test_an_untrusted_or_ended_approval_still_raises_the_card(self):
        for assoc in ("COLLABORATOR", "CONTRIBUTOR", "NONE"):
            with self.subTest(assoc=assoc):
                self.assertEqual(keys(self.node([look(C1, assoc=assoc)]), NEVER), self.CARD)
        ended = [look(C1), comment_node(C2, fm.end_body(C1, "done"))]
        self.assertEqual(keys(self.node(ended), NEVER), self.CARD)

    def test_an_ordinary_human_criterion_keeps_its_card_beside_an_answered_look(self):
        body = ac_body(LOOK_LINE, "- [ ] [human] The footer reads well")
        self.assertEqual(keys(self.node([look(C1)], body), Pulls()), self.CARD)

    def test_no_pull_request_is_read_unless_a_look_card_would_be_raised(self):
        bodies = {"ordinary": (ac_body("- [ ] [human] The footer reads well"), [f"{SLUG}#7/ac1"]),
                  "ticked": (ac_body(LOOK_LINE.replace("[ ]", "[x]", 1)), []),
                  "evidence": (ac_body("- [ ] [evidence] E", LOOK_LINE), [])}
        for name, (body, expected) in bodies.items():
            with self.subTest(name=name):
                self.assertEqual(keys(self.node([look(C1)], body), NEVER), expected)

    def test_a_failed_read_raises_the_card_and_a_stop_ends_the_read(self):
        def failed(argv):
            raise ForgeError("gh_failed", "x")

        def stopped(argv):
            raise ForgeError("cancelled")

        self.assertEqual(keys(self.node([look(C1)]), failed), self.CARD)
        for call in (stopped,):
            with self.assertRaises(ForgeError) as caught:
                keys(self.node([look(C1)]), call)
            self.assertEqual(caught.exception.code, "cancelled")
        asked = []

        def cancelled():
            asked.append(1)
            return len(asked) > 1

        with self.assertRaises(ForgeError) as caught:
            keys(self.node([look(C1)]), NEVER, cancelled=cancelled)
        self.assertEqual(caught.exception.code, "cancelled")

    def test_read_items_hands_its_call_to_the_pull_request_read(self):
        for name, order in (("held search", (False, True)), ("owner search", (True, False))):
            with self.subTest(name=name):
                node, pulls, argvs = self.node([look(C1)]), Pulls(), []

                def fake(argv):
                    argvs.append(argv)
                    if argv[:2] == ["api", "graphql"]:
                        index = len([a for a in argvs if a[:2] == ["api", "graphql"]]) - 1
                        return page([node] if order[index] else [])
                    return pulls(argv)

                self.assertEqual(inbox.read_items(PROJECT, SLUG, call=fake), [])
                self.assertEqual(pulls.argvs, [["api", f"repos/{SLUG}/pulls/42"]])

    def test_a_merge_that_keeps_an_earlier_approval_raises_no_card(self):
        forge = Forge(kept_reads())
        self.assertEqual(keys(self.node([look(C1, head=KEPT_A)]), forge), [])
        self.assertEqual(forge.argvs[:2], [["api", f"repos/{SLUG}/pulls/42"],
                                           ["api", f"repos/{SLUG}/commits/{KEPT_MC}"]])

    def test_a_kept_merge_that_cannot_be_read_keeps_the_card(self):
        without_ah = kept_reads()
        del without_ah[look_marker.compare_path(KEPT_A, LOOK_HEAD)]
        malformed = kept_reads()
        malformed[look_marker.compare_path(KEPT_BT, LOOK_HEAD)] = {}
        cases = {"look file changed after": ([look(C1, head=KEPT_A)], kept_reads(ah_files=(KEPT_PAGE,))),
                 "compare not found": ([look(C1, head=KEPT_A)], without_ah),
                 "no merge commit": ([look(C1, head=KEPT_A)], kept_reads(pull_extra={"merge_commit_sha": None})),
                 "malformed answer": ([look(C1, head=KEPT_A)], malformed),
                 "withdrawn": ([look(C1, head=KEPT_A), look(C2, "changes", head=KEPT_A)], kept_reads())}
        for name, (comments, reads) in cases.items():
            with self.subTest(name=name):
                self.assertEqual(keys(self.node(comments), Forge(reads)), self.CARD)

    def test_the_stop_is_asked_before_each_kept_read(self):
        forge = Forge(kept_reads())
        with self.assertRaises(ForgeError) as caught:
            keys(self.node([look(C1, head=KEPT_A)]), forge, cancelled=lambda: len(forge.argvs) >= 2)
        self.assertEqual(caught.exception.code, "cancelled")
        self.assertEqual(len(forge.argvs), 2)
        self.assertFalse([a for a in forge.argvs if "compare/" in a[1] or "contents/" in a[1]])


class WaitingCheckTest(unittest.TestCase):
    def read_held(self, *checks, extra=(), **kwargs):
        comments = [dated_comment(10, hold_body(*checks), CREATED), *extra]
        kwargs.setdefault("now", lambda: NOW)
        return read(page([held_node(7, comments)]), **kwargs)

    def test_a_future_not_before_is_a_waiting_item_not_a_card(self):
        items = self.read_held(future("Read the hourly rows. Count them."))
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["reason"], "verify-wait")
        self.assertEqual(items[0]["answers"], [])
        self.assertEqual(items[0]["wait"], {"reason": "not_before", "until": "2026-11-18T10:00:00+00:00",
                                            "what": "Read the hourly rows."})

    def test_the_waiting_item_has_the_documented_shape(self):
        item = self.read_held(future())[0]
        self.assertEqual(item, {
            "key": f"{SLUG}#7/wait/10/0", "project_id": PROJECT, "repo": SLUG, "issue": 7, "comment_id": 10,
            "url": f"https://github.com/{SLUG}/issues/7#issuecomment-10", "reason": "verify-wait",
            "kind": "waiting", "question": "Read the hourly rows.", "detail": "", "questions": [], "items": [],
            "answers": [], "paid": False, "confirm": "", "answered": False, "held_work": 1,
            "blocking": [],
            "wait": {"reason": "not_before", "until": "2026-11-18T10:00:00+00:00", "what": "Read the hourly rows."}})

    def test_a_live_command_with_no_text_waits_for_approval(self):
        live = {"ac": "AC2", "kind": "evidence", "host": "mbp", "when": {"not_before": "2026-11-18T10:00:00+00:00"},
                "run": {"command": "check-ok"}, "effects": "live"}
        item = self.read_held(live)[0]
        self.assertEqual(item["wait"]["what"], "AC2 waits for your approval to run")
        self.assertEqual(item["question"], "AC2 waits for your approval to run")

    def test_a_long_first_sentence_is_cut(self):
        item = self.read_held(human({"not_before": "2026-11-18T10:00:00+00:00"}, "Read " + "rows " * 60 + "."))[0]
        self.assertEqual(len(item["wait"]["what"]), 140)
        self.assertTrue(item["wait"]["what"].endswith("…"))

    def test_an_unseen_release_names_it_with_no_date(self):
        paths = []

        def api_get(path, allow=()):
            paths.append(path)
            return None

        with mock.patch.object(forge_api, "api_get", side_effect=api_get):
            items = self.read_held(human({"days_after": {"event": "released", "days": 2}}))
        self.assertEqual(paths, [f"repos/{SLUG}/releases/latest"])
        self.assertEqual(items[0]["wait"], {"reason": "not_released", "until": None, "what": "Read the hourly rows."})

    def test_a_worded_wait_without_a_when_member_names_the_field(self):
        check = human({"released_includes": MERGE}, HOURLY)
        key = verify_issues.block_key(10, block_of(check))
        prompt = dated_comment(11, prompt_body(key, 0), CREATED)
        with mock.patch.object(forge_api, "api_get", side_effect=AssertionError("no forge read")):
            items = self.read_held(check, extra=[prompt])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["reason"], "verify-ask")
        self.assertEqual(items[0]["answers"], list(verify_answer.ANSWERS["verify-ask"]))
        self.assertEqual(items[0]["wait"], {"reason": "no_when", "until": None, "what": HOURLY})

    def test_a_stale_check_card_stays_a_counted_card(self):
        check = human({"released_includes": MERGE}, HOURLY)
        key = verify_issues.block_key(10, block_of(check))
        stale = dated_comment(11, verify_body(
            "verify-stale-check", {"host": "mbp", "block": key, "check": "0", "cause": "silent"},
            "AC1 waits on mbp, which last reported 2026-11-01.", "- [ ] Accept without mbp"), CREATED)
        items = self.read_held(check, extra=[stale])
        by_reason = {item["reason"]: item for item in items}
        self.assertNotIn("wait", by_reason["verify-stale-check"])
        self.assertEqual(by_reason["verify-wait"]["wait"]["reason"], "no_when")
        self.assertEqual(len(items), 2)

    def test_an_expiry_decision_stays_a_card_beside_the_asked_line(self):
        check = human({"released_includes": MERGE}, HOURLY)
        key = verify_issues.block_key(10, block_of(check))
        decision = dated_comment(12, verify_body(
            "verify-decision", {"block": key, "check": "0", "on": "expire"},
            "AC1 expired: the owner decides.", "- [ ] Accept as passed\n- [ ] Close as not verified"), CREATED)
        items = self.read_held(check, extra=[dated_comment(11, prompt_body(key, 0), CREATED), decision])
        by_reason = {item["reason"]: item for item in items}
        self.assertNotIn("wait", by_reason["verify-decision"])
        self.assertEqual(by_reason["verify-ask"]["wait"]["reason"], "no_when")

    def test_a_due_prompted_check_is_a_plain_card(self):
        check = human({"not_before": "2026-11-15T10:00:00+00:00"}, "Read the hourly rows.")
        key = verify_issues.block_key(10, block_of(check))
        items = self.read_held(check, extra=[dated_comment(11, prompt_body(key, 0), CREATED)])
        self.assertEqual(len(items), 1)
        self.assertNotIn("wait", items[0])
        self.assertEqual(items[0]["answers"], list(verify_answer.ANSWERS["verify-ask"]))

    def test_a_runnable_evidence_check_raises_no_item(self):
        probe = {"ac": "AC1", "kind": "evidence", "host": "mbp", "when": {"not_before": "2026-11-01T00:00:00+00:00"},
                 "run": {"probe": "deployed_includes", "sha": MERGE}}
        self.assertEqual(self.read_held(probe), [])

    def test_one_clock_read_per_read(self):
        calls = []

        def now():
            calls.append(1)
            return NOW

        nodes = [held_node(n, [dated_comment(10, hold_body(future()), CREATED)]) for n in (7, 8)]
        items = read(page(nodes), now=now)
        self.assertEqual(len(items), 2)
        self.assertEqual(len(calls), 1)

    def test_the_default_clock_is_the_forges(self):
        check = human({"not_before": "2026-11-10T10:00:00+00:00"})
        with mock.patch.object(forge_api, "server_now",
                               return_value=datetime(2026, 11, 1, 10, tzinfo=timezone.utc)) as server:
            items = self.read_held(check, now=None)
        self.assertEqual(items[0]["wait"]["reason"], "not_before")
        self.assertEqual(server.call_count, 1)

    def test_a_stop_during_the_first_fact_read_reads_nothing_more(self):
        stop, paths = [False], []

        def api_get(path, allow=()):
            paths.append(path)
            stop[0] = True
            return {"tag_name": "v1"}

        with mock.patch.object(forge_api, "api_get", side_effect=api_get):
            with self.assertRaises(ForgeError) as raised:
                self.read_held(human({"released_includes": MERGE}), cancelled=lambda: stop[0])
        self.assertEqual(raised.exception.code, "cancelled")
        self.assertEqual(paths, [f"repos/{SLUG}/releases/latest"])

    def test_a_stop_after_the_search_builds_no_node(self):
        asked = []

        def cancelled():
            asked.append(1)
            return len(asked) > 1

        with self.assertRaises(ForgeError) as raised:
            read(page(three_nodes()), cancelled=cancelled)
        self.assertEqual(raised.exception.code, "cancelled")

    def test_a_node_without_a_block_reads_no_clock(self):
        def refuses():
            raise AssertionError("no block, no clock")

        self.assertEqual(read(page(three_nodes()), now=refuses), read(page(three_nodes())))

    def test_a_block_needs_the_repository_and_creation_times(self):
        comments = [dated_comment(10, hold_body(future()), CREATED)]
        bad = {"no repository": issue_node(7, comments),
               "no branch name": {**issue_node(7, comments), "repository": {"defaultBranchRef": None}},
               "no createdAt": held_node(7, [comment_node(10, hold_body(future()))])}
        for name, node in bad.items():
            with self.subTest(name):
                with self.assertRaises(ForgeError) as raised:
                    read(page([node]), now=lambda: NOW)
                self.assertEqual(raised.exception.code, "payload_invalid")


class LongIssueTest(unittest.TestCase):
    """An issue with more comments than the search's last-100 window is read whole (#1129)."""

    def rest(self, comments):
        return [[{"id": c["id"], "author_association": "OWNER", "body": c["body"], "created_at": CREATED}
                 for c in comments]]

    def long_held(self, number=7):
        window = [dated_comment(10, hold_body(future()), CREATED)]
        node = held_node(number, window)
        node["comments"]["totalCount"] = 101
        every = [{"id": 5, "body": "an early comment"}, {"id": 10, "body": window[0]["body"]}]
        return node, every

    def test_a_held_issue_past_a_hundred_comments_does_not_fail_the_read(self):
        node, every = self.long_held()
        ordinary = issue_node(8, [comment_node(C2, bullet_body("conflict", ["Merge conflict in flake.lock"]))])
        every += [{"id": 6 + n, "body": f"comment {n}"} for n in range(99)]
        with mock.patch.object(forge_api, "api_pages", return_value=self.rest(every)) as pages:
            items = read(page([node, ordinary]), now=lambda: NOW)
        self.assertEqual(pages.call_args_list, [mock.call(f"repos/{SLUG}/issues/7/comments?per_page=100")])
        self.assertEqual(sorted((i["issue"], i["reason"]) for i in items),
                         [(7, "verify-wait"), (8, "conflict")])

    def test_a_listing_still_short_of_the_total_is_incomplete(self):
        node, every = self.long_held()
        with mock.patch.object(forge_api, "api_pages", return_value=self.rest(every)):
            with self.assertRaises(ForgeError) as raised:
                read(page([node]), now=lambda: NOW)
        self.assertEqual(raised.exception.code, "payload_incomplete")

    def test_a_complete_node_reads_no_listing(self):
        with mock.patch.object(forge_api, "api_pages", side_effect=AssertionError("no listing")):
            self.assertEqual(len(read(page(three_nodes()))), 3)


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
        no_blocking = issue_node(7, [])
        del no_blocking["blocking"]

        def blocked(**fields):
            return page([{**issue_node(7, []), "blocking": {"totalCount": 1, "nodes": [
                {"number": 21, "state": "OPEN", "repository": {"nameWithOwner": SLUG}, **fields}]}}])
        no_number = blocked()
        del no_number["data"]["search"]["nodes"][0]["blocking"]["nodes"][0]["number"]
        table = [
            ("fewer nodes than issueCount", page([issue_node(7, [])], count=3), "payload_incomplete"),
            ("no data", {"data": {}}, "payload_invalid"),
            ("hasNextPage not bool", page([], more="yes"), "payload_invalid"),
            ("no dependency summary", page([no_summary]), "payload_invalid"),
            ("blocking is a bool", page([issue_node(7, [], blocking=True)]), "payload_invalid"),
            ("blocking truncated", page([{**issue_node(7, []), "blocking": {"totalCount": 101, "nodes": []}}]),
             "payload_incomplete"),
            ("no blocking connection", page([no_blocking]), "payload_invalid"),
            ("a blocked issue with no number", no_number, "payload_invalid"),
            ("a blocked issue number is a bool", blocked(number=True), "payload_invalid"),
            ("a blocked issue state is empty", blocked(state=""), "payload_invalid"),
            ("a blocked issue state is unknown", blocked(state="MERGED"), "payload_invalid"),
            ("a blocked issue state is not a string", blocked(state=1), "payload_invalid"),
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

    def test_the_owner_search_filters_by_its_two_labels(self):
        calls = []
        answers = [page([], more=True, cursor="c1", count=0), page([], count=0), page([], count=0)]

        def call(argv):
            calls.append(argv)
            return answers[len(calls) - 1]

        inbox.read_items(PROJECT, SLUG, call=call)
        self.assertEqual([c[:2] for c in calls], [["api", "graphql"]] * 3)
        self.assertIn("search=repo:octo/widgets is:open label:owner-action,owner-answered", calls[0])
        self.assertFalse([a for a in calls[0] if a.startswith("after=")])
        self.assertIn("after=c1", calls[1])
        fragment = inbox.QUERY.split("... on Issue {")[1].split("... on PullRequest")[0]
        for member in ("authorAssociation", "body", "labels(first: 100) { nodes { name } }"):
            with self.subTest(member):
                self.assertIn(member, fragment)

    def test_the_held_issues_are_read_by_their_own_search(self):
        calls = []

        def call(argv):
            calls.append(argv)
            return page([])

        inbox.read_items(PROJECT, SLUG, call=call)
        self.assertEqual(len(calls), 2)
        self.assertIn("search=repo:octo/widgets is:open label:needs-verification", calls[1])
        self.assertNotIn("search=repo:octo/widgets is:open label:needs-verification", calls[0])

    def test_more_than_a_hundred_held_issues_do_not_fail_the_read(self):
        decision = issue_node(7, [comment_node(C1, decision_body())])
        calls = []

        def call(argv):
            calls.append(argv)
            if any("label:owner-action" in a for a in argv):
                return page([decision])
            first = 1000 + 25 * len(calls)
            return page([held_issue(first + n, ac_body(HUMAN)) for n in range(25)],
                        more=True, cursor=f"h{len(calls)}", count=130)

        items = inbox.read_items(PROJECT, SLUG, call=call)
        self.assertEqual(len(calls), 1 + 4)
        self.assertIn(f"{SLUG}#7/{C1}", [i["key"] for i in items])
        self.assertEqual(len([i for i in items if i["reason"] == "held-review"]), 100)

    def test_a_held_issue_with_more_than_a_hundred_comments_is_skipped_and_the_rest_read(self):
        big = {**held_issue(1001, ac_body(HUMAN)), "comments": {"totalCount": 101, "nodes": []}}
        with mock.patch.object(forge_api, "api_pages", return_value=[[]]):
            items = read(page([issue_node(7, [comment_node(C1, decision_body())])]),
                         page([big, held_issue(1002, ac_body(HUMAN))], count=5))
        self.assertEqual([i["key"] for i in items], [f"{SLUG}#1002/ac1", f"{SLUG}#7/{C1}"])

    def test_a_held_node_the_owner_search_returned_is_read_once(self):
        node = held_issue(1001, ac_body(HUMAN))
        items = read(page([node]), page([node]))
        self.assertEqual([i["key"] for i in items], [f"{SLUG}#1001/ac1"])

    def test_the_owner_search_still_fails_on_overflow(self):
        with self.assertRaises(ForgeError) as raised:
            read(*[page([], more=True, cursor=f"c{n}", count=0) for n in range(4)])
        self.assertEqual(raised.exception.code, "payload_incomplete")

    def test_the_held_label_is_the_runners(self):
        from agent_tools.verification import verify_run
        self.assertEqual(inbox.HELD_LABEL, verify_run.NEEDS)

    def test_a_malformed_label_connection_fails_the_read(self):
        for labels in ({"nodes": "x"}, {"nodes": [{"name": 3}]}):
            with self.subTest(labels=labels):
                node = {**held_issue(7, ac_body(HUMAN)), "labels": labels}
                with self.assertRaises(ForgeError) as raised:
                    read(page([node]))
                self.assertEqual(raised.exception.code, "payload_invalid")

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


BLOCK, PROMPT, RESULT, END, CLOSE = 7008519004, 7008523711, 7008980881, 7008981257, 7008983081
BODY_1326 = ac_body("- [ ] [human] AC5 of #1320: the Sharing panel reads plainly (taste: only the owner can judge)")
CHECK_1326 = {"ac": "AC5", "kind": "human", "host": "any", "reason": "taste",
              "when": {"not_before": "2026-11-10T00:00:00Z"}, "run": {"ask": "Does the Sharing panel read plainly?"}}
BLOCK_1326 = {"v": 1, "merge": MERGE, "checks": [CHECK_1326]}
KEY_1326 = verify_issues.block_key(BLOCK, BLOCK_1326)
CARD = "octo/widgets#1326/ac1"


def comment_1326(cid, body, assoc="OWNER"):
    return dated_comment(cid, body, CREATED, assoc)


def block_comment_1326(*checks, cid=BLOCK):
    return comment_1326(cid, hold_body(*checks))


def prompt_1326(key=KEY_1326):
    return comment_1326(PROMPT, fm.render(
        "owner-action", {"reason": "verify-ask", "block": key, "check": "0", "host": "eleven-m5"},
        "AC5: the owner's answer is needed.",
        "Does the Sharing panel read plainly?\n\n- [x] Accept\n- [ ] Reject"))


def result_1326(state="pass", key=KEY_1326, check="0", cid=RESULT, assoc="OWNER"):
    return comment_1326(cid, fm.render(
        "verify-result", {"block": key, "check": check, "ac": "AC5", "state": state, "host": "eleven-m5"},
        "AC5 pass on eleven-m5."), assoc)


def end_1326(of=PROMPT, reason="answered", cid=END):
    return comment_1326(cid, fm.end_body(of, reason))


def closed_1326(fields=None, cid=CLOSE):
    return comment_1326(cid, fm.render(
        "verify-closed", {"block": KEY_1326, "outcome": "verified"} if fields is None else fields,
        "Verified: AC5."))


def node_1326(comments, **extra):
    return {**held_issue(1326, BODY_1326, comments=comments), "repository": {"defaultBranchRef": {"name": "main"}},
            **extra}


def reviews(node):
    return [i["key"] for i in read(page([]), page([node]), now=lambda: NOW) if i["reason"] == "held-review"]


class SettledHoldTest(unittest.TestCase):
    def test_the_1326_close_raises_no_review_card_at_any_later_step(self):
        block, prompt, result, end = block_comment_1326(CHECK_1326), prompt_1326(), result_1326(), end_1326()
        self.assertEqual(reviews(node_1326([block, prompt, end])), [CARD])
        steps = {"a result": [block, prompt, result], "its end": [block, prompt, result, end],
                 "the close": [block, prompt, result, end, closed_1326()]}
        for name, comments in steps.items():
            with self.subTest(name):
                self.assertEqual(reviews(node_1326(comments)), [])
        with self.subTest("a closed issue"):
            self.assertEqual(reviews(node_1326(steps["the close"], state="CLOSED")), [])

    def test_every_check_passed_settles_the_hold(self):
        block = block_comment_1326(CHECK_1326)
        other = {**CHECK_1326, "ac": "AC6"}
        two = block_comment_1326(CHECK_1326, other)
        two_key = verify_issues.block_key(BLOCK, {"v": 1, "merge": MERGE, "checks": [CHECK_1326, other]})
        cases = {
            "pass": ([block, result_1326("pass")], []),
            "hit": ([block, result_1326("hit")], []),
            "fail": ([block, result_1326("fail")], [CARD]),
            "another block": ([block, result_1326(key="1.0000000000000000")], [CARD]),
            "untrusted": ([block, result_1326(assoc="CONTRIBUTOR")], [CARD]),
            "ended": ([block, result_1326(), end_1326(RESULT, "superseded")], [CARD]),
            "one of two": ([two, result_1326(key=two_key)], [CARD]),
            "both of two": ([two, result_1326(key=two_key), result_1326(key=two_key, check="1", cid=RESULT + 1)], []),
        }
        for name, (comments, want) in cases.items():
            with self.subTest(name):
                self.assertEqual(reviews(node_1326(comments)), want)

    def test_a_verify_closed_marker_of_the_held_block_settles_the_hold(self):
        block = block_comment_1326(CHECK_1326)
        newer = block_comment_1326({**CHECK_1326, "when": {"not_before": "2026-11-11T00:00:00Z"}}, cid=CLOSE + 1)
        cases = {
            "verified": ([block, closed_1326()], []),
            "expired": ([block, closed_1326({"block": KEY_1326, "outcome": "expired"})], []),
            "pending": ([block, closed_1326({"block": KEY_1326, "outcome": "pending"})], [CARD]),
            "no outcome": ([block, closed_1326({"block": KEY_1326})], [CARD]),
            "another block": ([block, closed_1326({"block": "1.0000000000000000", "outcome": "verified"})],
                              [CARD]),
            "a newer block": ([block, closed_1326(), newer], [CARD]),
        }
        for name, (comments, want) in cases.items():
            with self.subTest(name):
                self.assertEqual(reviews(node_1326(comments)), want)

    def test_a_closed_held_issue_raises_no_review_card(self):
        def keys(**extra):
            node = {**held_issue(7, ac_body(HUMAN)), **extra}
            return [i["key"] for i in inbox.items_from_node(PROJECT, SLUG, node)]

        self.assertEqual(keys(state="CLOSED"), [])
        self.assertEqual(keys(state="OPEN"), [f"{SLUG}#7/ac1"])
        self.assertEqual(keys(), [f"{SLUG}#7/ac1"])
        for state in ("MERGED", 3, None):
            with self.subTest(state=state), self.assertRaises(ForgeError) as caught:
                keys(state=state)
            self.assertEqual(caught.exception.code, "payload_invalid")

    def test_the_issue_query_selects_its_state(self):
        fragment = inbox.QUERY.split("... on Issue {")[1].split("... on PullRequest")[0]
        self.assertIn("state", [line.strip() for line in fragment.split("\n")])

    def test_a_raised_review_card_is_gone_after_one_reading_of_its_settled_hold(self):
        block, prompt, result, end = block_comment_1326(CHECK_1326), prompt_1326(), result_1326(), end_1326()
        first = read(page([]), page([node_1326([block, prompt, end])]), now=lambda: NOW)
        records = view.inbox_records([event_log.Event(i + 1, "t1", event_log.INBOX_SEEN, PROJECT, item)
                                      for i, item in enumerate(first)])
        self.assertIn((PROJECT, CARD), records)
        settled = [block, prompt, result, end, closed_1326()]
        for name, node in {"open": node_1326(settled), "closed": node_1326(settled, state="CLOSED")}.items():
            with self.subTest(name):
                second = read(page([]), page([node]), now=lambda: NOW)
                changes = view.inbox_changes(records, PROJECT, second)
                self.assertIn((event_log.INBOX_GONE, PROJECT, {"key": CARD}), changes)
                after = view.inbox_records(
                    [event_log.Event(100 + i, "t2", kind, project, payload)
                     for i, (kind, project, payload) in enumerate(changes)], records)
                self.assertNotIn((PROJECT, CARD), after)


if __name__ == "__main__":
    unittest.main()
