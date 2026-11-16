"""The console's inbox reader (#859): owner-action markers into inbox items, and the local activity reading."""

import hashlib
import json
import os
import tempfile
import unittest
from unittest import mock
from datetime import datetime, timezone
from pathlib import Path

from agent_tools.claims import forge_markers as fm
from agent_tools.claims import forge_owner_action as foa
from agent_tools.console import inbox, pictures
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


CREATED = "2026-11-10T09:00:00Z"
HOURLY = "Two days after the release, read the hourly rows on kestrel; there are no impossible_usage rows."


def human(when, ask="Read the hourly rows. Count them.", ac="AC1"):
    return {"ac": ac, "kind": "human", "when": when, "run": {"ask": ask}, "reason": "senses", "host": "mbp"}


def block_of(*checks):
    return {"v": 1, "merge": MERGE, "checks": list(checks)}


def future(when_ask=None):
    return human({"not_before": "2026-11-18T10:00:00+00:00"}, *([when_ask] if when_ask else []))


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

    def test_the_search_filters_by_its_three_labels(self):
        calls = []
        answers = [page([], more=True, cursor="c1", count=0), page([], count=0)]

        def call(argv):
            calls.append(argv)
            return answers[len(calls) - 1]

        inbox.read_items(PROJECT, SLUG, call=call)
        self.assertEqual([c[:2] for c in calls], [["api", "graphql"]] * 2)
        self.assertIn("search=repo:octo/widgets is:open label:owner-action,owner-answered,needs-verification",
                      calls[0])
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
