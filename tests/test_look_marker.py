"""Tests for `agent_tools.delivery.look_marker` (issue 1138)."""
import unittest

from agent_tools.claims import forge_markers as fm
from agent_tools.delivery import look_marker as lm

LINE = ("- [ ] [human] before merge: the settings page at 390 px "
        "— measured: the owner, on the console")
BODY = "## Acceptance criteria\n\n" + LINE + "\n"
HEAD = "1a2b3c4" + "d" * 33
NO_ANSWER = f"<!-- agent:look v1 issue=1200 pr=1300 head={HEAD} message=m2 -->\nx"


def comment(cid, body, association="OWNER"):
    found = {"id": cid, "body": body, "updated_at": "2026-11-16T10:00:00Z"}
    if association is not None:
        found["author_association"] = association
    return found


def approved(cid, answer="approved", association="OWNER", issue=1200, pr=1300, head=HEAD):
    return comment(cid, lm.approval_body(issue, pr, head, answer, f"m{cid}"), association)


def judge(*comments):
    return lm.judge(1300, HEAD, [lm.IssueFacts(1200, BODY, tuple(comments))])


class ReadLookTest(unittest.TestCase):
    def test_the_exact_line_form_is_marked(self):
        look = lm.read_look(BODY)
        self.assertIs(look.marked, True)
        self.assertEqual(look.covers, ("the settings page at 390 px",))
        self.assertEqual(look.criteria[0].measured, "the owner, on the console")

    def test_a_ticked_box_is_still_marked(self):
        for box in ("[x]", "[X]"):
            with self.subTest(box=box):
                self.assertIs(lm.read_look(LINE.replace("[ ]", box, 1)).marked, True)

    def test_a_plain_human_criterion_is_unmarked(self):
        text = "- [ ] [human] the owner likes the colours — measured: the owner, on the page"
        self.assertIs(lm.read_look(text).marked, False)

    def test_a_hold_in_prose_is_unmarked(self):
        text = "Hold this for a look before merge: the owner must see the page first."
        self.assertIs(lm.read_look(text).marked, False)

    def test_the_line_inside_a_code_fence_is_unmarked(self):
        for text in (f"```\n{LINE}\n```\n", f"~~~~\n{LINE}\n~~~~\n", f"```text\n{LINE}\n"):
            with self.subTest(text=text):
                self.assertIs(lm.read_look(text).marked, False)

    def test_lines_after_a_closed_fence_are_read(self):
        self.assertIs(lm.read_look("```\nx\n```\n" + LINE).marked, True)

    def test_misspelt_forms_are_unmarked(self):
        edits = {
            "capital human": LINE.replace("[human]", "[Human]"),
            "hyphenated": LINE.replace("before merge:", "before-merge:"),
            "capital before": LINE.replace("before merge:", "Before merge:"),
            "no colon": LINE.replace("before merge:", "before merge"),
            "two hyphens": LINE.replace("—", "--"),
            "no measured": "- [ ] [human] before merge: the settings page at 390 px",
            "empty box": LINE.replace("- [ ] ", "- [] "),
            "leading space": " " + LINE,
            "code kind": LINE.replace("[human]", "[code]"),
            "empty what": "- [ ] [human] before merge:  — measured: x",
        }
        for name, text in edits.items():
            with self.subTest(name=name):
                self.assertIs(lm.read_look(text).marked, False)

    def test_trailing_whitespace_and_crlf_are_ignored(self):
        self.assertIs(lm.read_look(LINE + "  \r").marked, True)

    def test_no_body_is_unmarked(self):
        for body in (None, ""):
            with self.subTest(body=body):
                self.assertIs(lm.read_look(body).marked, False)


class ApprovalBodyTest(unittest.TestCase):
    def test_approval_body_is_the_exact_marker(self):
        body = lm.approval_body(1200, 1300, HEAD, "approved", "msg-1")
        first, second = body.split("\n")
        self.assertEqual(first, f"<!-- agent:look v1 issue=1200 pr=1300 head={HEAD} "
                                "answer=approved message=msg-1 -->")
        self.assertEqual(second, "The owner approved head 1a2b3c4 of pull request 1300 after a look.")
        self.assertEqual(list(fm.parse(comment(5, body)).fields),
                         ["issue", "pr", "head", "answer", "message"])
        changes = lm.approval_body(1200, 1300, HEAD, "changes", "msg-1").split("\n")[1]
        self.assertEqual(changes, "The owner asked for changes to head 1a2b3c4 of pull request 1300.")

    def test_bad_approval_fields_raise(self):
        cases = {
            "short head": (1200, 1300, HEAD[:39], "approved", "m"),
            "upper head": (1200, 1300, HEAD.upper(), "approved", "m"),
            "answer": (1200, 1300, HEAD, "maybe", "m"),
            "message": (1200, 1300, HEAD, "approved", "a b"),
            "issue": (0, 1300, HEAD, "approved", "m"),
            "pr": (1200, True, HEAD, "approved", "m"),
        }
        for name, args in cases.items():
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    lm.approval_body(*args)


class JudgeTest(unittest.TestCase):
    def test_a_trusted_approval_of_this_pr_and_head_admits(self):
        for association in ("OWNER", "MEMBER"):
            with self.subTest(association=association):
                self.assertIs(judge(approved(5, association=association)).admit, True)

    def test_an_untrusted_approval_is_ignored(self):
        for association in ("COLLABORATOR", "CONTRIBUTOR", "NONE", None):
            with self.subTest(association=association):
                verdict = judge(approved(5, association=association))
                self.assertIs(verdict.admit, False)
                self.assertEqual(verdict.issue, 1200)
                self.assertEqual(verdict.covers, ("the settings page at 390 px",))

    def test_an_approval_of_another_head_pr_or_issue_refuses(self):
        for name, found in {"head": approved(5, head="e" * 40), "pr": approved(5, pr=999),
                            "issue": approved(5, issue=7)}.items():
            with self.subTest(name=name):
                self.assertIs(judge(found).admit, False)

    def test_the_latest_answer_decides(self):
        self.assertIs(judge(approved(10), approved(11, "changes")).admit, False)
        self.assertIs(judge(approved(10, "changes"), approved(11)).admit, True)

    def test_an_ended_approval_does_not_count(self):
        self.assertIs(judge(approved(10), comment(11, fm.end_body(10, "withdrawn"))).admit, False)
        self.assertIs(judge(approved(10), comment(11, fm.end_body(10, "withdrawn"),
                                                  "CONTRIBUTOR")).admit, True)

    def test_an_unmarked_issue_needs_no_approval(self):
        for head in (HEAD, None):
            with self.subTest(head=head):
                self.assertIs(lm.judge(1300, head, [lm.IssueFacts(7, "plain", ())]).admit, True)

    def test_a_marked_issue_with_no_head_refuses(self):
        verdict = lm.judge(1300, None, [lm.IssueFacts(1200, BODY, (approved(5),))])
        self.assertIs(verdict.admit, False)
        self.assertEqual(verdict.issue, 1200)

    def test_the_first_marked_issue_in_number_order_is_named(self):
        verdict = lm.judge(1300, HEAD, [lm.IssueFacts(1300, BODY, ()), lm.IssueFacts(1200, BODY, ())])
        self.assertEqual(verdict.issue, 1200)

    def test_a_marker_with_no_answer_does_not_approve(self):
        cases = {"only": ((comment(10, NO_ANSWER),), 10),
                 "after approval": ((approved(10), comment(11, NO_ANSWER)), 11)}
        for name, (comments, latest) in cases.items():
            with self.subTest(name=name):
                verdict = lm.judge(1300, HEAD, [lm.IssueFacts(1200, BODY, comments)])
                self.assertIs(verdict.admit, False)
                self.assertEqual(verdict.issue, 1200)
                self.assertEqual(lm.look_answer(comments, 1200, 1300, HEAD).comment_id, latest)


if __name__ == "__main__":
    unittest.main()
