"""Tests for `agent_tools.delivery.look_marker` (issue 1138)."""
import base64
import hashlib
import json
import unittest
from pathlib import Path
from unittest import mock

from agent_tools.claims import forge_markers as fm
from agent_tools.delivery import look_marker as lm

LINE = ("- [ ] [human] before merge: the settings page at 390 px "
        "— measured: the owner, on the console")
BODY = "## Acceptance criteria\n\n" + LINE + "\n"
HEAD = "1a2b3c4" + "d" * 33
H = HEAD
NO_ANSWER = f"<!-- agent:look v1 issue=1200 pr=1300 head={HEAD} message=m2 -->\nx"


def comment(cid, body, association="OWNER"):
    found = {"id": cid, "body": body, "updated_at": "2026-11-16T10:00:00Z"}
    if association is not None:
        found["author_association"] = association
    return found


def approved(cid, answer="approved", association="OWNER", issue=1200, pr=1300, head=HEAD):
    return comment(cid, lm.approval_body(issue, pr, head, answer, f"m{cid}"), association)


REPO_ROOT = Path(__file__).resolve().parents[1]
B = "b" * 40
A = "5" * 40
T = "6" * 40
X = "8" * 40
F = "9" * 40
F1 = "4" * 40
FORK = "3" * 40
MC = "2" * 40
PAGE = "python/agent_tools/console/page.html"
INBOX = "python/agent_tools/console/inbox.py"
TESTF = "tests/test_console_page.py"
DOC = "docs/x.md"


def contents(text):
    raw = base64.b64encode(text.encode()).decode()
    return {"type": "file", "encoding": "base64",
            "content": "\n".join(raw[i:i + 60] for i in range(0, len(raw), 60))}


def edit(name, tag="e", at=1):
    return {"filename": name, "status": "modified",
            "patch": f"@@ -{at},2 +{at},2 @@\n {name} line 0\n-{name} old\n+{name} {tag}"}


def cmp(files=(), status="ahead", commits=()):
    listed = []
    for entry in files:
        if isinstance(entry, dict):
            listed.append(entry)
        elif isinstance(entry, tuple):
            listed.append(edit(*entry))
        else:
            listed.append(edit(entry))
    return {"status": status, "files": listed, "total_commits": len(commits),
            "commits": [{"sha": sha, "parents": [{"sha": p} for p in parents]}
                        for sha, parents in commits]}


CONSOLE = contents('{"version": 1, "sets": {"console": ["python/agent_tools/console/**"]}}')


def world(after, ah_files, extra=None):
    reads = {
        lm.contents_path(B): CONSOLE,
        lm.compare_path(B, A): cmp([PAGE], commits=[(A, [FORK])]),
        lm.compare_path(A, H): cmp(ah_files),
        lm.compare_path(B, H): cmp(commits=[(A, [FORK])] + after),
    }
    for (a, b), files in (extra or {}).items():
        reads[lm.compare_path(a, b)] = files if isinstance(files, dict) else cmp(files)
    return reads


def cand(answer="approved"):
    return lm.Candidate(1200, A, answer, 10)


def approval(cid, head, answer="approved", association="OWNER", words=None, pr=1300, issue=1200):
    return comment(cid, lm.approval_body(issue, pr, head, answer, f"m{cid}", words=words), association)


DIG = hashlib.sha256(("a" * 64 + "\n" + "c" * 64).encode()).hexdigest()


def pics_approval(cid, head=A, pictures=DIG):
    return comment(cid, lm.approval_body(1200, 1300, head, "approved", f"m{cid}", pictures=pictures))


def carry_comment(cid, a=A, h=H, pictures=DIG, association="OWNER", pr=1300):
    return comment(cid, lm.carry_body(1200, pr, a, h, pictures), association)


def merges_world(after):
    """The three compares the merges-only rule reads; no set file."""
    return {
        lm.compare_path(B, A): cmp([PAGE], commits=[(A, [FORK])]),
        lm.compare_path(A, H): cmp([DOC]),
        lm.compare_path(B, H): cmp(commits=[(A, [FORK])] + after),
    }


def three_reads():
    return (lm.compare_path(B, A), lm.compare_path(A, H), lm.compare_path(B, H))


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

    def test_a_fix_approval_carries_the_words(self):
        lines = lm.approval_body(1200, 1300, HEAD, "fix", "msg-1", words="  make the label bold ").split("\n")
        self.assertEqual(lines, [
            f"<!-- agent:look v1 issue=1200 pr=1300 head={HEAD} answer=fix message=msg-1 -->",
            "The owner approved head 1a2b3c4 of pull request 1300 with one fix.",
            "The fix: make the label bold"])

    def test_bad_fix_words_raise(self):
        for answer, words in (("fix", None), ("fix", "   "), ("fix", "x" * 2001), ("approved", "x")):
            with self.subTest(answer=answer, words=words):
                with self.assertRaises(ValueError):
                    lm.approval_body(1200, 1300, HEAD, answer, "m", words=words)


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


class LookAnsweredTest(unittest.TestCase):
    def test_marker_line_reads_one_body_line(self):
        for line in (LINE, LINE + "  \r", LINE.replace("[ ]", "[x]", 1)):
            with self.subTest(line=line):
                self.assertTrue(lm.marker_line(line))
        for line in (" " + LINE, "- [ ] [human] the page", ""):
            with self.subTest(line=line):
                self.assertFalse(lm.marker_line(line))

    def test_merged_head_reads_only_a_merged_pull_request(self):
        self.assertEqual(lm.merged_head({"merged": True, "head": {"sha": HEAD}}), HEAD)
        for pull in ({"merged": False, "head": {"sha": HEAD}}, {"head": {"sha": HEAD}}, {"merged": True},
                     {"merged": True, "head": {"sha": "abc"}}, None):
            with self.subTest(pull=pull):
                self.assertIsNone(lm.merged_head(pull))


class GlobTest(unittest.TestCase):
    def test_glob_match_reads_segments(self):
        for pattern, path in (("python/agent_tools/console/**", PAGE),
                              ("python/agent_tools/console/**", "python/agent_tools/console/a/b.py"),
                              ("tests/test_?.py", "tests/test_a.py"), ("a/*.py", "a/b.py"),
                              ("a/[x].py", "a/[x].py")):
            with self.subTest(pattern=pattern, path=path):
                self.assertIs(lm.glob_match(pattern, path), True)
        for pattern, path in (("python/agent_tools/console/**", "python/agent_tools/consoles/x.py"),
                              ("*.py", "a/b.py"), ("tests/test_?.py", "tests/test_ab.py"),
                              ("a/[x].py", "a/x.py")):
            with self.subTest(pattern=pattern, path=path):
                self.assertIs(lm.glob_match(pattern, path), False)


class LookFilesTest(unittest.TestCase):
    def test_the_set_file_decodes(self):
        self.assertEqual(lm.read_look_files(CONSOLE), {"console": ("python/agent_tools/console/**",)})

    def test_a_malformed_set_file_is_unreadable(self):
        bad = [None, {**CONSOLE, "type": "dir"}, {**CONSOLE, "encoding": "none"}, contents("{"),
               contents('{"version": 2, "sets": {"c": ["a/**"]}}'),
               contents('{"version": true, "sets": {"c": ["a/**"]}}'),
               contents('{"version": 1, "sets": {"c": ["a/**"]}, "owner": "x"}'),
               contents('{"version": 1, "sets": {}}'),
               contents('{"version": 1, "sets": {"c": []}}'),
               contents('{"version": 1, "sets": {"c": ["/a/**"]}}'),
               contents('{"version": 1, "sets": {"c": ["a//b"]}}'),
               contents('{"version": 1, "sets": {"c": ["a/../b"]}}'),
               contents('{"version": 1, "sets": {"Console!": ["a/**"]}}')]
        for found in bad:
            with self.subTest(found=found):
                self.assertIsNone(lm.read_look_files(found))

    def test_the_committed_set_file_declares_the_console_package(self):
        text = (REPO_ROOT / ".github/look-files.json").read_text()
        self.assertEqual(lm.read_look_files(contents(text)), {"console": ("python/agent_tools/console/**",)})


class CompareReadTest(unittest.TestCase):
    def test_compare_files_lists_names_and_previous_names(self):
        renamed = {"filename": "docs/p.html", "previous_filename": PAGE, "status": "renamed"}
        self.assertEqual(lm.compare_files(cmp([PAGE, renamed])), (PAGE, "docs/p.html", PAGE))

    def test_patch_hunks_drop_the_at_lines(self):
        first = lm.patch_hunks(edit(PAGE, "x", at=1)["patch"])
        self.assertEqual(first, lm.patch_hunks(edit(PAGE, "x", at=9)["patch"]))
        self.assertEqual(first, ((f" {PAGE} line 0", f"-{PAGE} old", f"+{PAGE} x"),))
        self.assertEqual(lm.patch_hunks(""), ())
        self.assertEqual(lm.patch_hunks("@@ -1 +1 @@\n-a\n+b\n\\ No newline at end of file\n@@ -9 +9 @@\n c"),
                         (("-a", "+b", "\\ No newline at end of file"), (" c",)))
        for patch in ("garbage", "@@ -1 +1 @@\n*x", " x\n@@ -1 +1 @@\n y"):
            with self.subTest(patch=patch):
                self.assertIsNone(lm.patch_hunks(patch))

    def test_an_unreadable_compare_is_none(self):
        many = {"files": [{"filename": f"f{n}", "status": "added"} for n in range(300)]}
        file = {"filename": "a", "status": "added"}
        for name, found in {"empty": {}, "files not a list": {"files": "x"}, "300 files": many,
                            "weird status": {"files": [{**file, "status": "weird"}]},
                            "numeric name": {"files": [{**file, "filename": 7}]},
                            "previous None": {"files": [{**file, "previous_filename": None}]},
                            "numeric patch": {"files": [{**file, "patch": 7}]},
                            "garbage patch": {"files": [{**file, "patch": "garbage"}]}}.items():
            with self.subTest(name=name):
                self.assertIsNone(lm.compare_files(found))
        good = cmp(commits=[(A, [FORK])])
        for name, found in {"total": {**good, "total_commits": 2},
                            "short sha": {**good, "commits": [{"sha": "ab", "parents": []}]},
                            "no parents": {**good, "commits": [{"sha": A}]}}.items():
            with self.subTest(name=name):
                self.assertIsNone(lm.compare_commits(found))
        self.assertEqual(lm.compare_commits(good), {A: (FORK,)})


class CandidateTest(unittest.TestCase):
    def test_the_latest_trusted_approval_of_another_head_is_the_candidate(self):
        self.assertEqual(lm.carry_candidate([approval(10, A)], 1200, 1300, H), cand())

    def test_no_candidate_for_these_shapes(self):
        shapes = {
            "changes after": [approval(10, A), approval(11, X, "changes")],
            "untrusted": [approval(10, A, association="COLLABORATOR")],
            "changes on this head": [approval(10, A), approval(11, H, "changes")],
            "fix on this head": [approval(10, A), approval(11, H, "fix", words="w")],
            "ended": [approval(10, A), comment(11, fm.end_body(10, "withdrawn"))],
            "another pull request": [approval(10, A, pr=999)],
        }
        for name, comments in shapes.items():
            with self.subTest(name=name):
                self.assertIsNone(lm.carry_candidate(comments, 1200, 1300, H))

    def test_a_fix_answer_is_a_fix_candidate(self):
        found = lm.carry_candidate([approval(10, A, "fix", words="bold label")], 1200, 1300, H)
        self.assertEqual(found.answer, "fix")

    def test_look_prs_lists_the_pull_requests_an_approval_names(self):
        comments = [approval(10, A), approval(11, A, pr=1301, answer="changes"),
                    approval(12, X, pr=1299, answer="fix", words="w"),
                    approval(13, A, pr=1302, association="CONTRIBUTOR")]
        self.assertEqual(lm.look_prs(comments, 1200), (1299, 1300))


TEST_ONLY = ([(H, [A])], [TESTF])


def merge_world(ah, base_files=None):
    """A clean merge of base X into the pull request: A...H is `ah`; X's own look files are `base_files`."""
    extra = {(A, X): base_files or [DOC], (X, A): [PAGE], (X, H): [PAGE]}
    return world([(H, [A, X])], ah, extra)


class KeptTest(unittest.TestCase):
    def kept(self, reads, answer="approved"):
        return lm.kept(cand(answer), H, lm.Carry(B, reads))

    def test_the_first_run_names_the_four_reads(self):
        self.assertEqual(self.kept({}), lm.Kept(False, (lm.contents_path(B), lm.compare_path(B, A),
                                                       lm.compare_path(A, H), lm.compare_path(B, H))))

    def test_a_head_whose_look_files_did_not_change_keeps_the_approval(self):
        self.assertEqual(self.kept(world(*TEST_ONLY)), lm.Kept(True, ()))
        self.assertEqual(self.kept(world([(H, [A, X])], [DOC])),
                         lm.Kept(False, (lm.compare_path(A, X), lm.compare_path(X, A), lm.compare_path(X, H))))
        extra = {(A, X): [DOC], (X, A): [PAGE], (X, H): [PAGE]}
        self.assertEqual(self.kept(world([(H, [A, X])], [DOC], extra)), lm.Kept(True, ()))

    def test_a_clean_merge_of_two_edits_to_one_look_file_keeps_the_approval(self):
        for at in (1, 9):
            with self.subTest(at=at):
                extra = {(A, X): [(PAGE, "x", at)], (X, A): [(PAGE, "a")], (X, H): [(PAGE, "a")]}
                self.assertEqual(self.kept(world([(H, [A, X])], [(PAGE, "x")], extra)), lm.Kept(True, ()))

    def test_a_clean_merge_that_brings_a_base_look_change_keeps_the_approval(self):
        self.assertEqual(self.kept(world([(H, [A, X])], [INBOX])),
                         lm.Kept(False, (lm.compare_path(A, X), lm.compare_path(X, A), lm.compare_path(X, H))))
        extra = {(A, X): [INBOX], (X, A): [PAGE], (X, H): [PAGE]}
        self.assertEqual(self.kept(world([(H, [A, X])], [INBOX], extra)), lm.Kept(True, ()))
        extra = {(A, T): [TESTF], (T, X): [INBOX], (X, T): [PAGE], (T, H): [INBOX], (X, H): [PAGE, TESTF]}
        self.assertEqual(self.kept(world([(T, [A]), (H, [T, X])], [INBOX, TESTF], extra)), lm.Kept(True, ()))

    def test_a_clean_merge_of_independent_edits_that_change_each_others_context_keeps_the_approval(self):
        def patch(*lines):
            return {"filename": PAGE, "status": "modified", "patch": "@@ -1,5 +1,5 @@\n" + "\n".join(lines)}

        base_side = patch(" l1", " l2 old", " l3", "-l4 old", "+l4 base", " l5")
        base_in_merge = patch(" l1", " l2 pr", " l3", "-l4 old", "+l4 base", " l5")
        pr_side = patch(" l1", "-l2 old", "+l2 pr", " l3", " l4 old", " l5")
        pr_in_merge = patch(" l1", "-l2 old", "+l2 pr", " l3", " l4 base", " l5")
        extra = {(A, X): [base_side], (X, A): [pr_side], (X, H): [pr_in_merge]}
        reads = world([(H, [A, X])], [base_in_merge], extra)
        self.assertEqual(self.kept(reads), lm.Kept(True, ()))
        reads[lm.compare_path(X, H)] = cmp([patch(" l1", "-l2 old", "+l2 other", " l3", " l4 base", " l5")])
        self.assertEqual(self.kept(reads), lm.Kept(False, ()))

    def test_a_merge_where_both_sides_made_the_same_look_edit_is_clean(self):
        extra = {(A, X): [PAGE, INBOX], (X, A): [PAGE], (X, H): []}
        self.assertEqual(self.kept(world([(H, [A, X])], [INBOX], extra)), lm.Kept(True, ()))

    def test_these_later_heads_do_not_keep_the_approval(self):
        renamed = {"filename": "python/agent_tools/console/inbox2.py", "previous_filename": INBOX,
                   "status": "renamed", "patch": ""}
        clean = {(A, X): [INBOX], (X, A): [PAGE], (X, H): [PAGE]}
        edits = {(A, X): [(PAGE, "x")], (X, A): [(PAGE, "a")], (X, H): [(PAGE, "a")]}
        omitted = {"filename": PAGE, "status": "modified"}
        no_cover = world(*TEST_ONLY)
        no_cover[lm.compare_path(B, A)] = cmp([DOC], commits=[(A, [FORK])])
        no_h = world(*TEST_ONLY)
        no_h[lm.compare_path(B, H)] = cmp(commits=[(A, [FORK]), (X, [A])])
        diverged = world(*TEST_ONLY)
        diverged[lm.compare_path(A, H)] = cmp([TESTF], status="diverged")
        long_diverged = world([(T, [A]), (H, [T])], [TESTF], {(A, T): [TESTF], (T, H): [TESTF]})
        long_diverged[lm.compare_path(A, H)] = cmp([TESTF], status="diverged")
        outside = world([(F, [A]), (H, [A])], [TESTF])
        earlier = cmp([PAGE], commits=[(F1, [FORK]), (A, [F1])])
        side_of_a = world([(H, [A, F1])], [TESTF])
        side_of_a[lm.compare_path(B, A)] = earlier
        side_of_a[lm.compare_path(B, H)] = cmp(commits=[(F1, [FORK]), (A, [F1]), (H, [A, F1])])
        eleven = [(f"{n:040x}", [A if n == 0 else f"{n - 1:040x}"]) for n in range(10)]
        cases = {
            "a look commit": world([(H, [A])], [PAGE]),
            "an edit moved within a look file": world([(T, [A]), (H, [T])], [PAGE],
                                                      {(A, T): [PAGE], (T, H): [PAGE]}),
            "a conflict resolved inside a look file": world(
                [(H, [A, X])], [(PAGE, "r")],
                {(A, X): [(PAGE, "x")], (X, A): [(PAGE, "a")], (X, H): [(PAGE, "r")]}),
            "an edit inside a merge": world([(H, [A, X])], [DOC, PAGE],
                                            {(A, X): [DOC], (X, A): [PAGE], (X, H): [PAGE]}),
            "an edit inside a merge to a file only the base changed": world(
                [(H, [A, X])], [INBOX],
                {(A, X): [INBOX], (X, A): [PAGE], (X, H): [PAGE, (INBOX, "extra")]}),
            "a merge that drops the PR's look edit": world(
                [(H, [A, X])], [DOC, (PAGE, "undo")], {(A, X): [DOC], (X, A): [PAGE], (X, H): []}),
            "a merge that drops the base's look edit": world(
                [(H, [A, X])], [DOC], {(A, X): [INBOX, DOC], (X, A): [PAGE], (X, H): [PAGE, INBOX]}),
            "a look edit and its revert": world(
                [(T, [A]), (H, [T])], [TESTF],
                {(A, T): [PAGE], (T, H): [(PAGE, "revert"), TESTF]}),
            "a renamed look file across a merge": world(
                [(H, [A, X])], [renamed], {**clean, (A, X): [renamed]}),
            "a look file whose patch is omitted": world([(H, [A, X])], [omitted], edits),
            "a look file whose patch is omitted on both sides": world(
                [(H, [A, X])], [omitted], {(A, X): [omitted], (X, A): [omitted], (X, H): [omitted]}),
            "A...H diverged": diverged,
            "A...H diverged over a longer chain": long_diverged,
            "a commit outside the first-parent chain": outside,
            "a merge whose second parent is a commit A already had": side_of_a,
            "no covered set": no_cover,
            "H missing from B...H commits": no_h,
            "a merge whose second parent is a PR commit": world([(F1, [A]), (H, [A, F1])], [PAGE]),
            "eleven commits after A": world(eleven + [(H, [eleven[-1][0]])], [TESTF]),
        }
        for name, reads in cases.items():
            with self.subTest(name=name):
                self.assertEqual(self.kept(reads), lm.Kept(False, ()))

    def test_absent_reads_are_not_kept(self):
        no_file = world(*TEST_ONLY)
        no_file[lm.contents_path(B)] = None
        vanished = world(*TEST_ONLY)
        vanished[lm.compare_path(A, H)] = None
        merge = merge_world([DOC])
        merge[lm.compare_path(X, H)] = None
        for name, reads in {"no set file": no_file, "vanished head": vanished, "absent merge read": merge}.items():
            with self.subTest(name=name):
                self.assertEqual(self.kept(reads), lm.Kept(False, ()))

    def test_unreadable_reads_raise(self):
        def altered(path, value):
            reads = world(*TEST_ONLY)
            reads[path] = value
            return reads

        many = {"files": [{"filename": f"f{n}", "status": "added"} for n in range(300)]}
        incomplete = cmp(commits=[(A, [FORK]), (H, [A])])
        incomplete["total_commits"] = 3
        no_commits = cmp([PAGE])
        del no_commits["commits"]
        garbage = merge_world([DOC])
        garbage[lm.compare_path(X, H)] = cmp([{"filename": PAGE, "status": "modified", "patch": "garbage"}])
        cases = {
            "set file": altered(lm.contents_path(B), contents("{")),
            "300 files": altered(lm.compare_path(A, H), many),
            "A...H empty": altered(lm.compare_path(A, H), {}),
            "A...H status": altered(lm.compare_path(A, H), {**cmp([TESTF]), "status": 7}),
            "incomplete commits": altered(lm.compare_path(B, H), incomplete),
            "B...A without commits": altered(lm.compare_path(B, A), no_commits),
            "garbage patch": garbage,
        }
        for name, reads in cases.items():
            with self.subTest(name=name):
                with self.assertRaises(lm.Unreadable):
                    self.kept(reads)

    def test_a_fix_keeps_the_approval_for_exactly_one_look_commit(self):
        one = world([(F, [A]), (H, [F])], [PAGE, TESTF], {(A, F): [PAGE], (F, H): [TESTF]})
        self.assertEqual(self.kept(one, "fix"), lm.Kept(True, ()))
        none = world([(F, [A]), (H, [F])], [PAGE, TESTF], {(A, F): [TESTF], (F, H): [TESTF]})
        two = world([(F1, [A]), (F, [F1]), (H, [F])], [PAGE], {(A, F1): [PAGE], (F1, F): [PAGE], (F, H): [TESTF]})
        side = world([(F1, [A]), (F, [F1]), (H, [A, F])], [PAGE])
        for name, reads in {"no look commit": none, "two look commits": two, "side branch": side,
                            "test only": world(*TEST_ONLY)}.items():
            with self.subTest(name=name):
                self.assertEqual(self.kept(reads, "fix"), lm.Kept(False, ()))

    def test_judge_lists_candidates_and_needs(self):
        comments = (approval(10, A),)
        facts = [lm.IssueFacts(1200, BODY, comments)]
        verdict = lm.judge(1300, H, facts)
        self.assertEqual((verdict.admit, verdict.issue, verdict.candidates, verdict.need),
                         (False, 1200, (cand(),), ()))
        verdict = lm.judge(1300, H, facts, lm.Carry(B, {}))
        self.assertEqual(verdict.need, tuple(sorted((lm.contents_path(B), lm.compare_path(B, A),
                                                     lm.compare_path(A, H), lm.compare_path(B, H)))))
        verdict = lm.judge(1300, H, [*facts, lm.IssueFacts(1201, BODY, ())], lm.Carry(B, {}))
        self.assertEqual((verdict.issue, verdict.candidates, verdict.need), (1200, (), ()))
        reads = world(*TEST_ONLY)
        self.assertEqual(lm.judge(1300, H, facts, lm.Carry(B, reads)), lm.Verdict(True, marked=(1200,)))
        reads[lm.compare_path(A, H)] = {}
        verdict = lm.judge(1300, H, facts, lm.Carry(B, reads))
        self.assertEqual((verdict.admit, verdict.issue, verdict.need), (False, 1200, ()))

    def test_an_exact_approval_still_admits_without_a_carry(self):
        self.assertIs(judge(approval(10, H)).admit, True)



class MergeCarryTest(unittest.TestCase):
    """Issue 1566: a look approval with pictures carries across merges of the integration branch."""

    def test_approval_body_records_the_picture_digest(self):
        body = lm.approval_body(1200, 1300, A, "approved", "m1", pictures=DIG)
        self.assertEqual(body.splitlines()[0],
                         f"<!-- agent:look v1 issue=1200 pr=1300 head={A} answer=approved message=m1 "
                         f"pictures={DIG} -->")
        self.assertEqual(body.splitlines()[1],
                         f"The owner approved head {A[:7]} of pull request 1300 after a look.")
        self.assertEqual(lm.approval_body(1200, 1300, A, "approved", "m1"),
                         f"<!-- agent:look v1 issue=1200 pr=1300 head={A} answer=approved message=m1 -->\n"
                         f"The owner approved head {A[:7]} of pull request 1300 after a look.")
        for answer, words in (("fix", "w"), ("changes", None)):
            with self.subTest(answer=answer):
                with self.assertRaises(ValueError):
                    lm.approval_body(1200, 1300, A, answer, "m1", words=words, pictures=DIG)
        for bad in ("A" * 64, "a" * 63):
            with self.subTest(pictures=bad):
                with self.assertRaises(ValueError):
                    lm.approval_body(1200, 1300, A, "approved", "m1", pictures=bad)

    def test_picture_digest_is_the_hash_of_the_sorted_ids(self):
        expected = hashlib.sha256(("a" * 64 + "\n" + "c" * 64).encode()).hexdigest()
        self.assertEqual(lm.picture_digest(["c" * 64, "a" * 64]), expected)
        self.assertEqual(lm.picture_digest(["a" * 64, "c" * 64]), expected)
        self.assertEqual(lm.picture_id(b"x"), hashlib.sha256(b"x").hexdigest())
        for bad in ([], ["g" * 64]):
            with self.subTest(ids=bad):
                with self.assertRaises(ValueError):
                    lm.picture_digest(bad)

    def test_picture_digest_names_each_pictures_role(self):
        a, c = "a" * 64, "c" * 64
        expected = hashlib.sha256(f"after:{c}\nbefore:{a}".encode()).hexdigest()
        self.assertEqual(lm.picture_digest([("before", a), ("after", c)]), expected)
        self.assertEqual(lm.picture_digest([("after", c), ("before", a)]), expected)
        swapped = lm.picture_digest([("before", c), ("after", a)])
        self.assertNotEqual(swapped, expected)
        self.assertNotEqual(lm.picture_digest([("before", a), ("after", c)]), lm.picture_digest([a, c]))
        self.assertEqual(lm.picture_digest([(None, a), (None, c)]), lm.picture_digest([a, c]))
        for bad in ([("middle", a)], [("before", "g" * 64)], [("before",)]):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    lm.picture_digest(bad)

    def test_carry_line_names_the_smallest_live_line_the_writers_elect(self):
        self.assertEqual(lm.carry_line([carry_comment(101), carry_comment(100)], 1200, 1300, A, H, DIG), 100)
        self.assertEqual(lm.carry_candidate([pics_approval(10), carry_comment(101), carry_comment(100)],
                                            1200, 1300, H).line, 100)

    def test_carry_body_is_the_exact_marker(self):
        self.assertEqual(
            lm.carry_body(1200, 1300, A, H, DIG),
            f"<!-- agent:look-carry v1 issue=1200 pr=1300 from={A} to={H} pictures={DIG} -->\n"
            f"Carried the owner's look approval of head {A[:7]} of pull request 1300 to head {H[:7]}: "
            "only merges of the integration branch came in and the re-rendered pictures are unchanged.")
        cases = {"same head": (1200, 1300, A, A, DIG), "pr 0": (1200, 0, A, H, DIG),
                 "short head": (1200, 1300, A, "a" * 39, DIG), "uppercase digest": (1200, 1300, A, H, "A" * 64)}
        for name, args in cases.items():
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    lm.carry_body(*args)

    def test_the_candidate_names_its_pictures_and_a_matching_carry_line(self):
        self.assertEqual(lm.carry_candidate([pics_approval(10), carry_comment(11)], 1200, 1300, H),
                         lm.Candidate(1200, A, "approved", 10, DIG, 11))
        other = lm.picture_digest(["b" * 64])
        shapes = {
            "another to": [pics_approval(10), carry_comment(11, h=T)],
            "another from": [pics_approval(10), carry_comment(11, a=X)],
            "another digest": [pics_approval(10), carry_comment(11, pictures=other)],
            "another pr": [pics_approval(10), carry_comment(11, pr=999)],
            "a collaborator": [pics_approval(10), carry_comment(11, association="COLLABORATOR")],
            "ended": [pics_approval(10), carry_comment(11), comment(12, fm.end_body(11, "withdrawn"))],
            "no line": [pics_approval(10)],
        }
        for name, comments in shapes.items():
            with self.subTest(name=name):
                self.assertEqual(lm.carry_candidate(comments, 1200, 1300, H),
                                 lm.Candidate(1200, A, "approved", 10, DIG, None))
        self.assertEqual(lm.carry_candidate([approval(10, A), carry_comment(11)], 1200, 1300, H),
                         lm.Candidate(1200, A, "approved", 10, None, None))
        self.assertEqual(lm.carry_candidate([approval(10, A, "fix", words="w"), carry_comment(11)],
                                            1200, 1300, H),
                         lm.Candidate(1200, A, "fix", 10, None, None))

    def test_merges_only_names_its_three_reads(self):
        self.assertEqual(lm.merges_only(A, H, lm.Carry(B, {})), lm.Kept(False, three_reads()))

    def test_merges_of_the_integration_branch_carry(self):
        for after in ([(H, [A, X])], [(T, [A, X]), (H, [T, F])]):
            with self.subTest(after=after):
                self.assertEqual(lm.merges_only(A, H, lm.Carry(B, merges_world(after))), lm.Kept(True, ()))

    def test_merges_only_refuses_each_other_shape(self):
        diverged = merges_world([(H, [A, X])])
        diverged[lm.compare_path(A, H)] = cmp([DOC], status="diverged")
        chained = [(f"{n + 1:040x}", [A if n == 0 else f"{n:040x}", X]) for n in range(lm.CHAIN_LIMIT + 1)]
        chained[-1] = (H, chained[-1][1])
        cases = {
            "a one-parent commit": merges_world([(H, [A])]),
            "a pull request commit as second parent": merges_world([(T, [A]), (H, [T, A])]),
            "a pull request commit as second parent, swapped": merges_world([(T, [A]), (H, [A, T])]),
            "an octopus": merges_world([(H, [A, X, F])]),
            "a merge of an earlier pull request merge": merges_world([(T, [A, X]), (F, [T, X]), (H, [F, T])]),
            "A...H diverged": diverged,
            "too many merges": merges_world(chained),
        }
        for name, reads in cases.items():
            with self.subTest(name=name):
                self.assertEqual(lm.merges_only(A, H, lm.Carry(B, reads)), lm.Kept(False, ()))
        for path in three_reads():
            with self.subTest(none=path):
                reads = {**merges_world([(H, [A, X])]), path: None}
                self.assertEqual(lm.merges_only(A, H, lm.Carry(B, reads)), lm.Kept(False, ()))
        short = merges_world([(H, [A, X])])
        short[lm.compare_path(B, H)]["total_commits"] += 1
        with self.assertRaises(lm.Unreadable):
            lm.merges_only(A, H, lm.Carry(B, short))
        self.assertEqual(lm.merges_only(A, A, lm.Carry(B, merges_world([(H, [A, X])]))), lm.Kept(False, ()))

    def test_kept_asks_the_merge_rule_only_for_an_approved_candidate_with_a_line(self):
        c = lm.Candidate(1200, A, "approved", 10, DIG, 11)
        self.assertEqual(lm.kept(c, H, lm.Carry(B, {})), lm.Kept(False, three_reads()))
        self.assertEqual(lm.kept(c, H, lm.Carry(B, merges_world([(H, [A, X])]))), lm.Kept(True, ()))
        four = lm.Kept(False, (lm.contents_path(B), lm.compare_path(B, A), lm.compare_path(A, H),
                               lm.compare_path(B, H)))
        for other in (lm.Candidate(1200, A, "approved", 10, None, None), lm.Candidate(1200, A, "fix", 10, None, 11)):
            with self.subTest(other=other):
                self.assertEqual(lm.kept(other, H, lm.Carry(B, {})), four)

    def test_an_approval_with_pictures_and_no_line_is_kept_by_no_look_file_rule(self):
        # Issue 1566 review: the owner looked at pictures, so a head no look file changed is kept only by a carry line.
        reads = world(*TEST_ONLY)
        self.assertEqual(lm.kept(lm.Candidate(1200, A, "approved", 10), H, lm.Carry(B, reads)), lm.Kept(True, ()))
        for read in (reads, {}):
            with self.subTest(reads=len(read)):
                pictured = lm.Candidate(1200, A, "approved", 10, DIG, None)
                self.assertEqual(lm.kept(pictured, H, lm.Carry(B, read)), lm.Kept(False, ()))
        self.assertIs(lm.settle(lm.Candidate(1200, A, "approved", 10, DIG, None), H, B, reads.__getitem__), False)
        bare = lm.IssueFacts(1200, BODY, (pics_approval(10),))
        self.assertEqual(lm.judge(1300, H, [bare], lm.Carry(B, reads)).admit, False)

    def test_a_clean_integration_merge_needs_its_carry_line_under_pictures(self):
        merged = merges_world([(H, [A, X])])
        no_line = lm.IssueFacts(1200, BODY, (pics_approval(10),))
        self.assertEqual(lm.judge(1300, H, [no_line], lm.Carry(B, merged)).admit, False)
        lined = lm.IssueFacts(1200, BODY, (pics_approval(10), carry_comment(11)))
        self.assertEqual(lm.judge(1300, H, [lined], lm.Carry(B, merged)).admit, True)

    def test_judge_admits_a_carried_head_only_with_its_line(self):
        carry = lm.Carry(B, merges_world([(H, [A, X])]))
        facts = lm.IssueFacts(1200, BODY, (pics_approval(10), carry_comment(11)))
        self.assertEqual(lm.judge(1300, H, [facts], carry), lm.Verdict(True, marked=(1200,)))
        bare = lm.IssueFacts(1200, BODY, (pics_approval(10),))
        refused = lm.judge(1300, H, [bare], carry)
        self.assertEqual((refused.admit, refused.issue), (False, 1200))
        empty = lm.judge(1300, H, [facts], lm.Carry(B, {}))
        self.assertEqual((empty.admit, empty.issue, empty.need), (False, 1200, tuple(sorted(three_reads()))))

    def test_settle_merges_reads_only_compares(self):
        reads = merges_world([(H, [A, X])])
        seen = []

        def read(path):
            seen.append(path)
            return reads[path]

        self.assertIs(lm.settle_merges(A, H, B, read), True)
        self.assertEqual(len(seen), 3)
        for path in seen:
            self.assertRegex(path, lm.COMPARE_PATH)

    def fallback_world(self):
        after = [(T, [A]), (H, [T])]
        return merges_world(after)

    def test_a_line_that_does_not_carry_falls_back_in_one_batched_run(self):
        c = lm.Candidate(1200, A, "approved", 10, DIG, 11)
        three = self.fallback_world()
        self.assertEqual(lm.kept(c, H, lm.Carry(B, three)),
                         lm.Kept(False, (lm.contents_path(B), lm.compare_path(A, T), lm.compare_path(T, H))))
        full = {**three, lm.contents_path(B): CONSOLE, lm.compare_path(A, T): cmp([DOC]),
                lm.compare_path(T, H): cmp([DOC])}
        self.assertEqual(lm.kept(c, H, lm.Carry(B, full)), lm.Kept(True, ()))

    def test_settle_decides_a_fallback_within_its_runs(self):
        c = lm.Candidate(1200, A, "approved", 10, DIG, 11)
        full = {**self.fallback_world(), lm.contents_path(B): CONSOLE, lm.compare_path(A, T): cmp([DOC]),
                lm.compare_path(T, H): cmp([DOC])}
        seen = []

        def read(path):
            seen.append(path)
            return full[path]

        self.assertIs(lm.settle(c, H, B, read), True)
        self.assertEqual(seen, [*three_reads(), lm.contents_path(B), lm.compare_path(A, T),
                                lm.compare_path(T, H)])


class SettleTest(unittest.TestCase):
    def test_settle_reads_what_kept_names(self):
        reads = merge_world([INBOX], [INBOX])
        seen = []

        def read(path):
            seen.append(path)
            return reads[path]

        self.assertIs(lm.settle(cand(), H, B, read), True)
        self.assertEqual(seen, [lm.contents_path(B), lm.compare_path(B, A), lm.compare_path(A, H),
                                lm.compare_path(B, H), lm.compare_path(A, X), lm.compare_path(X, A),
                                lm.compare_path(X, H)])

        def boom(path):
            raise RuntimeError(path)

        with self.assertRaises(RuntimeError):
            lm.settle(cand(), H, B, boom)
        seen.clear()

        def not_found(path):
            seen.append(path)
            return None if path == lm.contents_path(B) else reads[path]

        self.assertIs(lm.settle(cand(), H, B, not_found), False)
        self.assertEqual(len(seen), 4)
        bad = {**reads, lm.compare_path(A, H): {}}
        with self.assertRaises(lm.Unreadable):
            lm.settle(cand(), H, B, bad.__getitem__)

    def test_settle_stops_at_its_bounds(self):
        count = iter(range(1000))
        calls = []

        def fresh(*_):
            calls.append(1)
            return lm.Kept(False, (f"compare/{B}...{next(count):040x}",))

        read = mock.Mock(return_value={})
        with mock.patch.object(lm, "kept", side_effect=fresh):
            self.assertIs(lm.settle(cand(), H, B, read), False)
        self.assertEqual((len(calls), read.call_count), (lm.CARRY_RUNS, lm.CARRY_RUNS - 1))
        read = mock.Mock(return_value={})
        many = lm.Kept(False, tuple(f"compare/{B}...{n:040x}" for n in range(49)))
        with mock.patch.object(lm, "kept", return_value=many):
            self.assertIs(lm.settle(cand(), H, B, read), False)
        read.assert_not_called()


def pull(head=H, sha=MC):
    found = {"merged": True, "head": {"sha": head}}
    if sha is not None:
        found["merge_commit_sha"] = sha
    return found


class MergedUnderLookTest(unittest.TestCase):
    def reader(self, reads):
        self.seen = []

        def read(path):
            self.seen.append(path)
            if path not in reads:
                raise RuntimeError(path)
            return reads[path]

        return read

    def world_at_b(self):
        return {**world(*TEST_ONLY), f"commits/{MC}": {"sha": MC, "parents": [{"sha": B}, {"sha": H}]}}

    def test_an_exact_approval_of_the_merged_head_needs_no_read(self):
        read = self.reader({})
        self.assertIs(lm.merged_under_look([approval(10, H)], 1200, 1300, pull(), read), True)
        self.assertIs(lm.merged_under_look([approval(10, A), approval(11, H, "changes")],
                                           1200, 1300, pull(), read), False)
        self.assertEqual(self.seen, [])

    def test_a_merged_head_that_keeps_an_earlier_approval_is_under_the_look(self):
        read = self.reader(self.world_at_b())
        self.assertIs(lm.merged_under_look([approval(10, A)], 1200, 1300, pull(), read), True)
        self.assertEqual(self.seen[:5], [f"commits/{MC}", lm.contents_path(B), lm.compare_path(B, A),
                                         lm.compare_path(A, H), lm.compare_path(B, H)])

    def test_these_merges_are_not_under_the_look(self):
        read = self.reader({})
        unmerged = {"merged": False, "head": {"sha": H}}
        self.assertIs(lm.merged_under_look([approval(10, A)], 1200, 1300, unmerged, read), False)
        self.assertIs(lm.merged_under_look([approval(10, A, association="CONTRIBUTOR")],
                                           1200, 1300, pull(), read), False)
        self.assertEqual(self.seen, [])
        reads = self.world_at_b()
        reads[lm.compare_path(A, H)] = cmp([PAGE])
        self.assertIs(lm.merged_under_look([approval(10, A)], 1200, 1300, pull(), self.reader(reads)), False)

    def test_an_unreadable_merge_raises(self):
        comments = [approval(10, A)]
        with self.assertRaises(lm.Unreadable):
            lm.merged_under_look(comments, 1200, 1300, pull(sha=None), self.reader({}))
        reads = {**self.world_at_b(), f"commits/{MC}": {"parents": []}}
        with self.assertRaises(lm.Unreadable):
            lm.merged_under_look(comments, 1200, 1300, pull(), self.reader(reads))
        reads = self.world_at_b()
        del reads[lm.compare_path(A, H)]
        with self.assertRaises(RuntimeError):
            lm.merged_under_look(comments, 1200, 1300, pull(), self.reader(reads))
        reads = {**self.world_at_b(), lm.compare_path(B, H): {"commits": "x"}}
        with self.assertRaises(lm.Unreadable):
            lm.merged_under_look(comments, 1200, 1300, pull(), self.reader(reads))


class TickMarkersTest(unittest.TestCase):
    def test_only_unticked_marker_lines_outside_fences_are_ticked(self):
        body = ("## Acceptance criteria\r\n\r\n- [ ] [code] A — measured: a test  \r\n" + LINE
                + "\r\n- [ ] [human] the footer\r\n```\r\n" + LINE + "\r\n```\r\n")
        ticked = body.replace(LINE, "- [x]" + LINE[5:], 1)
        self.assertEqual(lm.tick_markers(body), (ticked, 1))
        self.assertEqual(lm.tick_markers(ticked), (ticked, 0))
        self.assertEqual(lm.tick_markers(None), ("", 0))


if __name__ == "__main__":
    unittest.main()
