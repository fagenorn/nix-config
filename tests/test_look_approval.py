"""Tests for `agent_tools.delivery.look_approval` (issue 1138): post, status and judge."""
import base64
import contextlib
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent_tools.claims import forge_markers
from agent_tools.delivery import look_approval, look_marker as lm
from .forge_world import ForgeWorld

SLUG, ISSUE, PR = "octo/widgets", 7, 12
HEAD = "1a2b3c4" + "d" * 33
OTHER = "e" * 40
WHAT = "the settings page at 390 px"
BODY = ("## Acceptance criteria\n\n- [ ] [human] before merge: " + WHAT
        + " — measured: the owner, on the console\n")
NO_ANSWER = f"<!-- agent:look v1 issue=7 pr=12 head={HEAD} message=m2 -->\nx"
REPO_ROOT = Path(__file__).resolve().parents[1]
T0 = "2026-11-16T10:00:00Z"
ISSUE_ARGV = ["api", f"repos/{SLUG}/issues/{ISSUE}"]
POST = ["--repo", SLUG, "--issue", "7", "--pr", "12", "--head", HEAD]
STATUS = ["status", *POST]
A = "5" * 40
B = "b" * 40
BT = "3" * 40
MC = "2" * 40
FORK = "e" * 40
PAGE = "python/agent_tools/console/page.html"
TESTF = "tests/test_console_page.py"
PULL_ARGV = ["api", f"repos/{SLUG}/pulls/{PR}"]


def comment(cid, body, association="OWNER"):
    return {"id": cid, "body": body, "updated_at": T0, "created_at": T0,
            "author_association": association, "user": {"login": "octo"}}


def contents(text):
    raw = base64.b64encode(text.encode()).decode()
    return {"type": "file", "encoding": "base64",
            "content": "\n".join(raw[i:i + 60] for i in range(0, len(raw), 60))}


def cmp(files=(), status="ahead", commits=()):
    listed = [{"filename": name, "status": "modified",
               "patch": f"@@ -1,2 +1,2 @@\n {name} line 0\n-{name} old\n+{name} new"} for name in files]
    return {"status": status, "files": listed, "total_commits": len(commits),
            "commits": [{"sha": sha, "parents": [{"sha": p} for p in parents]} for sha, parents in commits]}


CONSOLE = contents('{"version": 1, "sets": {"console": ["python/agent_tools/console/**"]}}')
SHRUNK = contents('{"version": 1, "sets": {"console": ["python/agent_tools/console/*.py"]}}')


def reads(base, ah_files=(TESTF,)):
    return {
        f"contents/.github/look-files.json?ref={base}": CONSOLE,
        f"compare/{base}...{A}": cmp([PAGE, "python/agent_tools/console/view.py"], commits=[(A, [FORK])]),
        f"compare/{A}...{HEAD}": cmp(ah_files),
        f"compare/{base}...{HEAD}": cmp(commits=[(A, [FORK]), (HEAD, [A])]),
    }


def serve(world, slug, served):
    for path, value in served.items():
        world.respond_json("gh", ["api", f"repos/{slug}/{path}"], value)


def run(*argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = look_approval.main(list(argv))
    lines = out.getvalue().splitlines()
    assert len(lines) == 1, out.getvalue()
    return code, json.loads(lines[0])


class PostTest(unittest.TestCase):
    def setUp(self):
        self.world = ForgeWorld(self)

    def post(self):
        return run("post", *POST, "--answer", "approved", "--message", "msg-1")

    def test_post_writes_one_look_marker_and_reads_it_back(self):
        self.world.comment_store(SLUG, ISSUE, [], labels=[])
        code, out = self.post()
        self.assertEqual(code, 0)
        self.assertEqual(out["verdict"], "posted")
        self.assertEqual(out["comment_id"], 100)
        self.assertEqual({k: out[k] for k in ("command", "action", "repo", "issue", "pr", "head", "answer", "message")},
                         {"command": "look-approval", "action": "post", "repo": SLUG, "issue": 7, "pr": 12,
                          "head": HEAD, "answer": "approved", "message": "msg-1"})
        stored = self.world.stored()
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0]["body"].splitlines()[0],
                         f"<!-- agent:look v1 issue=7 pr=12 head={HEAD} answer=approved message=msg-1 -->")

    def test_a_post_the_forge_does_not_trust_is_untrusted(self):
        self.world.comment_store(SLUG, ISSUE, [])
        code, out = self.post()
        self.assertEqual(code, 1)
        self.assertEqual(out["verdict"], "untrusted")


class PostFixTest(unittest.TestCase):
    def setUp(self):
        self.world = ForgeWorld(self)
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def words_file(self, text):
        path = self.tmp / "words.txt"
        path.write_text(text, encoding="utf-8")
        return str(path)

    def fix(self, *tail):
        return run("post", *POST, "--answer", "fix", "--message", "msg-1", *tail)

    def test_a_fix_approval_posts_the_words(self):
        self.world.comment_store(SLUG, ISSUE, [], labels=[])
        code, out = self.fix("--words-file", self.words_file("make the label bold\n"))
        self.assertEqual((code, out["verdict"], out["answer"]), (0, "posted", "fix"))
        lines = self.world.stored()[0]["body"].splitlines()
        self.assertEqual(lines[0], f"<!-- agent:look v1 issue=7 pr=12 head={HEAD} answer=fix message=msg-1 -->")
        self.assertEqual(lines[1], "The owner approved head 1a2b3c4 of pull request 12 with one fix.")
        self.assertEqual(lines[2], "The fix: make the label bold")

    def test_fix_word_errors_come_before_any_gh_call(self):
        cases = {
            "no words file": ["--answer", "fix", "--message", "m"],
            "words with approved": ["--answer", "approved", "--message", "m",
                                    "--words-file", self.words_file("x")],
            "missing file": ["--answer", "fix", "--message", "m", "--words-file", str(self.tmp / "none.txt")],
            "only spaces": ["--answer", "fix", "--message", "m", "--words-file", self.words_file("   \n ")],
            "too long": ["--answer", "fix", "--message", "m", "--words-file", self.words_file("x" * 2001)],
        }
        for name, tail in cases.items():
            with self.subTest(name):
                code, out = run("post", *POST, *tail)
                self.assertEqual((code, out["error"], out["verdict"]), (2, "usage", "error"))
        self.assertEqual(self.world.argvs("gh"), [])


class StatusTest(unittest.TestCase):
    def setUp(self):
        self.world = ForgeWorld(self)

    def seed(self, comments, body=BODY):
        self.world.comment_store(SLUG, ISSUE, comments)
        self.world.respond_json("gh", ISSUE_ARGV, {"number": 7, "body": body})

    def test_status_reads_only_trusted_approvals(self):
        approval = lm.approval_body(7, 12, HEAD, "approved", "m1")
        self.seed([comment(5, approval, "CONTRIBUTOR")])
        code, out = run(*STATUS)
        self.assertEqual((code, out["verdict"], out["comment_id"]), (0, "needed", None))
        self.world.append_comment(comment(6, approval, "OWNER"))
        code, out = run(*STATUS)
        self.assertEqual(code, 0)
        self.assertEqual((out["verdict"], out["comment_id"], out["answer"]), ("approved", 6, "approved"))
        self.assertEqual(out["covers"], [WHAT])

    def test_status_of_another_head_is_needed(self):
        self.seed([comment(5, lm.approval_body(7, 12, A, "approved", "m1"))])
        self.world.respond_json("gh", PULL_ARGV, {"number": 12, "base": {"ref": "main"}, "head": {"sha": HEAD}})
        self.world.respond_json("gh", ["api", f"repos/{SLUG}/branches/main"], {"name": "main", "commit": {"sha": B}})
        serve(self.world, SLUG, reads(B, ah_files=(PAGE,)))
        code, out = run(*STATUS)
        self.assertEqual((code, out["verdict"]), (0, "needed"))

    def test_status_of_an_unmarked_issue_is_unmarked(self):
        self.seed([], body="plain")
        code, out = run(*STATUS)
        self.assertEqual((code, out["verdict"]), (0, "unmarked"))

    def test_status_of_an_issue_with_no_body_key_is_an_error(self):
        self.world.comment_store(SLUG, ISSUE, [])
        self.world.respond_json("gh", ISSUE_ARGV, {"number": 7})
        code, out = run(*STATUS)
        self.assertEqual((code, out["verdict"], out["error"]), (1, "error", "payload_invalid"))

    def test_status_of_a_marker_with_no_answer_is_needed(self):
        cases = {
            "only": ([comment(5, NO_ANSWER)], 5),
            "latest": ([comment(5, lm.approval_body(7, 12, HEAD, "approved", "m1")), comment(6, NO_ANSWER)], 6),
        }
        for name, (comments, cid) in cases.items():
            with self.subTest(name):
                self.seed(comments)
                code, out = run(*STATUS)
                self.assertEqual(code, 0)
                self.assertEqual((out["verdict"], out["answer"], out["comment_id"]), ("needed", None, cid))

    def test_a_forge_outage_is_an_error(self):
        self.world.outage()
        code, out = run(*STATUS)
        self.assertEqual((code, out["verdict"]), (1, "error"))


class MarkedTest(unittest.TestCase):
    MARKED = ["marked", "--repo", SLUG, "--issue", "7"]

    def setUp(self):
        self.world = ForgeWorld(self)

    def test_marked_reads_the_marker_from_the_issue_body_alone(self):
        self.world.respond_json("gh", ISSUE_ARGV, {"number": 7, "body": BODY})
        code, out = run(*self.MARKED)
        self.assertEqual((code, out), (0, {"command": "look-approval", "action": "marked", "repo": SLUG,
                                           "issue": 7, "verdict": "marked", "covers": [WHAT],
                                           "acs": ["AC1"]}))
        self.assertEqual([call["argv"] for call in self.world.calls()], [ISSUE_ARGV])

    def test_marked_names_the_criteria_of_the_marker_lines_by_their_place_in_the_issue(self):
        """#1356: a plan may reword the look criterion, so the issue's own marker line is named by its AC id."""
        body = ("## Problem\n\n- [ ] not a criterion\n\n## Acceptance criteria\n\n- [ ] [code] a test\n"
                "- [ ] [human] before merge: " + WHAT + " \u2014 measured: the owner, on the console\n"
                "- [ ] [human] the owner reads the notes \u2014 measured: the owner\n")
        self.world.respond_json("gh", ISSUE_ARGV, {"number": 7, "body": body})
        code, out = run(*self.MARKED)
        self.assertEqual((code, out["verdict"], out["acs"]), (0, "marked", ["AC2"]))

    def test_marked_names_only_the_marker_lines_that_tick_ticks(self):
        """#1356: a fence the console parser closes but the marker reader opens must not suppress a marker tick leaves open."""
        marker = "- [ ] [human] before merge: " + WHAT + " \u2014 measured: the owner, on the console\n"
        body = "## Acceptance criteria\n\n" + marker + "- ```\n  sample\n  ```\n" + marker
        self.assertEqual(lm.tick_markers(body)[1], 1)
        self.world.respond_json("gh", ISSUE_ARGV, {"number": 7, "body": body})
        code, out = run(*self.MARKED)
        self.assertEqual((code, out["verdict"], out["acs"]), (0, "marked", ["AC1"]))

    def test_an_unmarked_or_fenced_body_is_unmarked(self):
        for body in ("plain", None, "```\n" + BODY + "```\n"):
            with self.subTest(body=body):
                self.world.respond_json("gh", ISSUE_ARGV, {"number": 7, "body": body})
                code, out = run(*self.MARKED)
                self.assertEqual((code, out["verdict"], out["covers"], out["acs"]), (0, "unmarked", [], []))

    def test_an_issue_with_no_body_key_is_a_forge_error(self):
        self.world.respond_json("gh", ISSUE_ARGV, {"number": 7})
        code, out = run(*self.MARKED)
        self.assertEqual((code, out["verdict"], out["error"], out["action"]),
                         (1, "error", "payload_invalid", "marked"))

    def test_marked_usage_errors_come_before_any_gh_call(self):
        cases = [["marked", "--repo", "bad", "--issue", "7"],
                 ["marked", "--repo", SLUG, "--issue", "0"],
                 ["marked", "--repo", SLUG]]
        for argv in cases:
            with self.subTest(argv=argv):
                code, out = run(*argv)
                self.assertEqual((code, out["error"], out["action"]), (2, "usage", "marked"))
        self.assertEqual(self.world.calls(), [])


class TickTest(unittest.TestCase):
    PULL_ARGV = ["api", f"repos/{SLUG}/pulls/{PR}"]
    TICK = ["tick", *POST]
    MERGED = {"number": 12, "merged": True, "head": {"sha": HEAD}}
    TICK_BODY = ("## Acceptance criteria\n\n- [ ] [code] the label — measured: a test\n"
                 "- [ ] [human] before merge: " + WHAT + " — measured: the owner, on the console\n"
                 "- [ ] [human] the footer — measured: the owner\n\n```\n"
                 "- [ ] [human] before merge: an example — measured: nobody\n```\n")
    TICKED_BODY = TICK_BODY.replace("- [ ] [human] before merge: " + WHAT, "- [x] [human] before merge: " + WHAT)
    PATCH = ["api", "-X", "PATCH", f"repos/{SLUG}/issues/{ISSUE}", "-f", "body=" + TICKED_BODY]

    def setUp(self):
        self.world = ForgeWorld(self)

    def seed(self, comments, body, pull):
        self.world.comment_store(SLUG, ISSUE, comments)
        self.world.respond_json("gh", ISSUE_ARGV, {"number": 7, "body": body})
        self.world.respond_json("gh", self.PULL_ARGV, pull)
        self.world.respond_json("gh", self.PATCH, {"number": 7})

    def approval(self, cid=5, head=HEAD, answer="approved", association="OWNER"):
        return comment(cid, lm.approval_body(7, 12, head, answer, f"m{cid}"), association)

    def patches(self):
        return [argv for argv in self.world.argvs("gh") if argv[:3] == ["api", "-X", "PATCH"]]

    def test_tick_ticks_only_the_look_marker_box_of_an_approved_merged_head(self):
        self.seed([self.approval()], self.TICK_BODY, self.MERGED)
        code, out = run(*self.TICK)
        self.assertEqual((code, out["verdict"], out["ticked"], out["covers"]), (0, "ticked", 1, [WHAT]))
        self.assertEqual({k: out[k] for k in ("command", "action", "repo", "issue", "pr", "head")},
                         {"command": "look-approval", "action": "tick", "repo": SLUG, "issue": 7, "pr": 12,
                          "head": HEAD})
        self.assertEqual(self.world.argvs("gh").count(self.PATCH), 1)

    def test_tick_writes_nothing_without_a_trusted_approval_of_that_head(self):
        cases = {
            "untrusted": [self.approval(5, association="CONTRIBUTOR")],
            "changes after": [self.approval(5), self.approval(6, answer="changes")],
        }
        for name, comments in cases.items():
            with self.subTest(name):
                self.world = ForgeWorld(self)
                self.seed(comments, self.TICK_BODY, self.MERGED)
                code, out = run(*self.TICK)
                self.assertEqual((code, out["verdict"]), (1, "needed"))
                self.assertEqual(self.patches(), [])

    def test_tick_writes_nothing_unless_the_pull_request_merged_at_that_head(self):
        cases = {
            "not merged": {**self.MERGED, "merged": False},
            "other head": {**self.MERGED, "head": {"sha": OTHER}},
        }
        for name, pull in cases.items():
            with self.subTest(name):
                self.world = ForgeWorld(self)
                self.seed([self.approval()], self.TICK_BODY, pull)
                code, out = run(*self.TICK)
                self.assertEqual((code, out["verdict"]), (1, "not_merged"))
                self.assertEqual(self.patches(), [])

    def test_an_already_ticked_or_unmarked_issue_writes_nothing(self):
        cases = {
            "already": (self.TICKED_BODY, "already"),
            "unmarked": ("## Acceptance criteria\n\n- [ ] [code] x\n", "unmarked"),
        }
        for name, (body, verdict) in cases.items():
            with self.subTest(name):
                self.world = ForgeWorld(self)
                self.seed([self.approval()], body, self.MERGED)
                code, out = run(*self.TICK)
                self.assertEqual((code, out["verdict"], out["ticked"]), (0, verdict, 0))
                self.assertEqual(self.patches(), [])

    def test_tick_usage_errors_come_before_any_gh_call(self):
        code, out = run("tick", "--repo", SLUG, "--issue", "7", "--pr", "12", "--head", "abc")
        self.assertEqual((code, out["error"]), (2, "usage"))
        self.assertEqual(self.world.argvs("gh"), [])


class StatusCarryTest(unittest.TestCase):
    BRANCH_ARGV = ["api", f"repos/{SLUG}/branches/main"]
    PULL = {"number": 12, "base": {"ref": "main"}, "head": {"sha": HEAD}}

    def setUp(self):
        self.world = ForgeWorld(self)

    def seed(self, comments, served=None):
        self.world.comment_store(SLUG, ISSUE, comments)
        self.world.respond_json("gh", ISSUE_ARGV, {"number": 7, "body": BODY})
        self.world.respond_json("gh", PULL_ARGV, self.PULL)
        self.world.respond_json("gh", self.BRANCH_ARGV, {"name": "main", "commit": {"sha": B}})
        serve(self.world, SLUG, reads(B) if served is None else served)

    def kept(self):
        return [comment(5, lm.approval_body(7, 12, A, "approved", "m1"))]

    def test_status_of_a_head_that_keeps_an_approval_is_approved(self):
        self.seed(self.kept())
        code, out = run(*STATUS)
        self.assertEqual((code, out["verdict"], out["answer"], out["comment_id"], out["kept_from"]),
                         (0, "approved", "approved", 5, A))
        for argv in self.world.argvs("gh"):
            self.assertFalse(any("ref=main" in part or "compare/main" in part for part in argv), argv)

    def test_status_of_a_head_that_changed_a_look_file_is_needed(self):
        self.seed(self.kept(), reads(B, ah_files=(PAGE,)))
        code, out = run(*STATUS)
        self.assertEqual((code, out["verdict"], out["answer"], out["comment_id"], out["kept_from"]),
                         (0, "needed", None, None, None))

    def test_status_reports_an_unreadable_carry_as_an_error(self):
        malformed = {
            "empty compare": (f"compare/{B}...{HEAD}", {}),
            "unknown file status": (f"compare/{A}...{HEAD}",
                                    {"status": "ahead", "files": [{"filename": PAGE, "status": "weird"}]}),
            "set file a dir": (f"contents/.github/look-files.json?ref={B}", {"type": "dir"}),
        }
        self.seed(self.kept())
        self.world.respond("gh", ["api", f"repos/{SLUG}/compare/{B}...{HEAD}"], exit=1,
                           stderr="gh: Internal Server Error (HTTP 500)")
        code, out = run(*STATUS)
        self.assertEqual((code, out["verdict"]), (1, "error"))
        self.assertNotIn("kept_from", out)
        for name, (path, value) in malformed.items():
            with self.subTest(name):
                self.world = ForgeWorld(self)
                self.seed(self.kept())
                self.world.respond_json("gh", ["api", f"repos/{SLUG}/{path}"], value)
                code, out = run(*STATUS)
                self.assertEqual((code, out["verdict"], out["error"]), (1, "error", "payload_invalid"))
                self.assertNotIn("kept_from", out)
        with self.subTest("pull without a base"):
            self.world = ForgeWorld(self)
            self.seed(self.kept())
            self.world.respond_json("gh", PULL_ARGV, {"number": 12})
            code, out = run(*STATUS)
            self.assertEqual((code, out["verdict"], out["error"]), (1, "error", "payload_invalid"))
            self.assertNotIn("kept_from", out)
        with self.subTest("branch not found"):
            self.world = ForgeWorld(self)
            self.seed(self.kept())
            self.world.not_found("gh", self.BRANCH_ARGV)
            code, out = run(*STATUS)
            self.assertEqual((code, out["verdict"]), (1, "error"))
            self.assertNotIn("kept_from", out)

    def test_status_of_an_absent_carry_read_is_needed(self):
        for path in (f"contents/.github/look-files.json?ref={B}", f"compare/{A}...{HEAD}"):
            with self.subTest(path):
                self.world = ForgeWorld(self)
                self.seed(self.kept())
                self.world.not_found("gh", ["api", f"repos/{SLUG}/{path}"])
                code, out = run(*STATUS)
                self.assertEqual((code, out["verdict"], out["answer"], out["comment_id"], out["kept_from"]),
                                 (0, "needed", None, None, None))

    def test_an_exact_approval_reports_no_kept_head(self):
        self.seed([comment(5, lm.approval_body(7, 12, HEAD, "approved", "m1"))])
        code, out = run(*STATUS)
        self.assertEqual((code, out["verdict"], out["kept_from"]), (0, "approved", None))
        self.assertNotIn(PULL_ARGV, self.world.argvs("gh"))


class StatusMergeCarryTest(unittest.TestCase):
    """Issue 1566: a carried head is judged from compares alone, the set file never read."""
    BRANCH_ARGV = ["api", f"repos/{SLUG}/branches/main"]
    PULL = {"number": 12, "base": {"ref": "main"}, "head": {"sha": HEAD}}
    DIG = hashlib.sha256(("a" * 64 + "\n" + "c" * 64).encode()).hexdigest()
    X = "7" * 40

    def setUp(self):
        self.world = ForgeWorld(self)

    def pics(self, cid):
        return comment(cid, lm.approval_body(7, 12, A, "approved", f"m{cid}", pictures=self.DIG))

    def line(self, cid):
        return comment(cid, lm.carry_body(7, 12, A, HEAD, self.DIG))

    def served(self, base):
        return {
            f"compare/{base}...{A}": cmp([PAGE], commits=[(A, [FORK])]),
            f"compare/{A}...{HEAD}": cmp([TESTF]),
            f"compare/{base}...{HEAD}": cmp(commits=[(A, [FORK]), (HEAD, [A, self.X])]),
        }

    def seed(self, comments):
        self.world.comment_store(SLUG, ISSUE, comments)
        self.world.respond_json("gh", ISSUE_ARGV, {"number": 7, "body": BODY})
        self.world.respond_json("gh", PULL_ARGV, self.PULL)
        self.world.respond_json("gh", self.BRANCH_ARGV, {"name": "main", "commit": {"sha": B}})
        serve(self.world, SLUG, self.served(B))
        self.world.not_found("gh", ["api", f"repos/{SLUG}/contents/.github/look-files.json?ref={B}"])

    def test_status_of_a_carried_head_is_approved(self):
        self.seed([self.pics(5), self.line(6)])
        code, out = run(*STATUS)
        self.assertEqual((code, out["verdict"], out["answer"], out["comment_id"], out["kept_from"]),
                         (0, "approved", "approved", 5, A))
        for argv in self.world.argvs("gh"):
            self.assertFalse(any("contents/" in part for part in argv), argv)

    def test_a_non_merge_edit_outside_the_look_files_does_not_keep_a_pictured_approval(self):
        # Issue 1566 review: the look file rule alone would approve it and the landing would skip the owner's look.
        for pictured, verdict in ((True, "needed"), (False, "approved")):
            with self.subTest(pictured=pictured):
                self.world = ForgeWorld(self)
                found = self.pics(5) if pictured else comment(5, lm.approval_body(7, 12, A, "approved", "m5"))
                self.world.comment_store(SLUG, ISSUE, [found])
                self.world.respond_json("gh", ISSUE_ARGV, {"number": 7, "body": BODY})
                self.world.respond_json("gh", PULL_ARGV, self.PULL)
                self.world.respond_json("gh", self.BRANCH_ARGV, {"name": "main", "commit": {"sha": B}})
                serve(self.world, SLUG, reads(B))
                code, out = run(*STATUS)
                self.assertEqual((code, out["verdict"]), (0, verdict))

    def test_a_clean_integration_merge_is_approved_only_through_its_carry_line(self):
        for lined, verdict in ((False, "needed"), (True, "approved")):
            with self.subTest(lined=lined):
                self.world = ForgeWorld(self)
                self.seed([self.pics(5), *([self.line(6)] if lined else [])])
                self.world.respond_json("gh", ["api", f"repos/{SLUG}/contents/.github/look-files.json?ref={B}"], CONSOLE)
                code, out = run(*STATUS)
                self.assertEqual((code, out["verdict"]), (0, verdict))

    def test_status_without_the_carry_line_is_needed(self):
        self.seed([self.pics(5)])
        code, out = run(*STATUS)
        self.assertEqual((code, out["verdict"], out["answer"], out["comment_id"], out["kept_from"]),
                         (0, "needed", None, None, None))

    def test_tick_ticks_a_carried_merged_head(self):
        pull = {"number": 12, "merged": True, "head": {"sha": HEAD}, "base": {"ref": "main"},
                "merge_commit_sha": MC}
        self.world.comment_store(SLUG, ISSUE, [self.pics(5), self.line(6)])
        self.world.respond_json("gh", ISSUE_ARGV, {"number": 7, "body": TickTest.TICK_BODY})
        self.world.respond_json("gh", PULL_ARGV, pull)
        self.world.respond_json("gh", TickTest.PATCH, {"number": 7})
        self.world.respond_json("gh", ["api", f"repos/{SLUG}/commits/{MC}"],
                                {"sha": MC, "parents": [{"sha": BT}, {"sha": HEAD}]})
        serve(self.world, SLUG, self.served(BT))
        self.world.not_found("gh", ["api", f"repos/{SLUG}/contents/.github/look-files.json?ref={BT}"])
        code, out = run("tick", *POST)
        self.assertEqual((code, out["verdict"], out["ticked"], out["kept_from"]), (0, "ticked", 1, A))


    def files_served(self, base):
        return {
            f"compare/{base}...{A}": cmp([TESTF], commits=[(A, [FORK])]),
            f"compare/{A}...{HEAD}": cmp(["docs/x.md"]),
            f"compare/{base}...{HEAD}": cmp([TESTF], commits=[(A, [FORK]), (HEAD, [A, self.X])]),
            f"contents/.github/look-files.json?ref={base}": CONSOLE,
        }

    def plain(self, cid):
        return comment(cid, lm.approval_body(7, 12, A, "approved", f"m{cid}"))

    def look_files_line(self, cid):
        return comment(cid, lm.carry_body(7, 12, A, HEAD, None))

    def test_status_of_a_look_files_carried_head_is_approved(self):
        for lined, expected in ((True, (0, "approved", "approved", 5, A)), (False, (0, "needed", None, None, None))):
            with self.subTest(lined=lined):
                self.world = ForgeWorld(self)
                self.seed([self.plain(5), *([self.look_files_line(6)] if lined else [])])
                serve(self.world, SLUG, self.files_served(B))
                code, out = run(*STATUS)
                self.assertEqual((code, out["verdict"], out["answer"], out["comment_id"], out["kept_from"]), expected)

    def test_tick_ticks_a_look_files_carried_merged_head(self):
        pull = {"number": 12, "merged": True, "head": {"sha": HEAD}, "base": {"ref": "main"},
                "merge_commit_sha": MC}
        self.world.comment_store(SLUG, ISSUE, [self.plain(5), self.look_files_line(6)])
        self.world.respond_json("gh", ISSUE_ARGV, {"number": 7, "body": TickTest.TICK_BODY})
        self.world.respond_json("gh", PULL_ARGV, pull)
        self.world.respond_json("gh", TickTest.PATCH, {"number": 7})
        self.world.respond_json("gh", ["api", f"repos/{SLUG}/commits/{MC}"],
                                {"sha": MC, "parents": [{"sha": BT}, {"sha": HEAD}]})
        serve(self.world, SLUG, self.files_served(BT))
        code, out = run("tick", *POST)
        self.assertEqual((code, out["verdict"], out["ticked"], out["kept_from"]), (0, "ticked", 1, A))


class CarryVerbTest(unittest.TestCase):
    """Issue 1566: `carry` checks a merges-only head and records one carry line for it."""
    BRANCH_ARGV = ["api", f"repos/{SLUG}/branches/main"]
    X = "7" * 40
    T = "6" * 40
    DIG = lm.picture_digest([("before", lm.picture_id(b"before")), ("after", lm.picture_id(b"after"))])
    LINE = lm.carry_body(7, 12, A, HEAD, DIG)

    def setUp(self):
        self.world = ForgeWorld(self)
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.before = self.tmp / "before.png"
        self.after = self.tmp / "after.png"
        self.before.write_bytes(b"before")
        self.after.write_bytes(b"after")

    def carry_args(self, *, source=A):
        return ["carry", *POST, "--from", source, "--before", str(self.before), "--after", str(self.after)]

    def merges(self, tail=None):
        return {
            f"compare/{B}...{A}": cmp([PAGE], commits=[(A, [FORK])]),
            f"compare/{A}...{HEAD}": cmp(["docs/x.md"]),
            f"compare/{B}...{HEAD}": cmp(commits=tail or [(A, [FORK]), (HEAD, [A, self.X])]),
        }

    def seed(self, comments, compares=None, *, body=BODY, head=HEAD, state="open", trusted=True):
        self.world.comment_store(SLUG, ISSUE, comments, **({"labels": []} if trusted else {}))
        self.world.respond_json("gh", ISSUE_ARGV, {"number": 7, "body": body})
        self.world.respond_json("gh", PULL_ARGV, {"number": 12, "state": state, "base": {"ref": "main"},
                                                  "head": {"sha": head}})
        self.world.respond_json("gh", self.BRANCH_ARGV, {"name": "main", "commit": {"sha": B}})
        serve(self.world, SLUG, self.merges() if compares is None else compares)

    def pics(self, cid, pictures=None, head=A, answer="approved"):
        return comment(cid, lm.approval_body(7, 12, head, answer, f"m{cid}", pictures=(pictures or self.DIG) if answer == "approved" else None))

    def posted(self):
        return [a for a in self.world.argvs("gh") if a[:3] == ["api", "-X", "POST"]]

    def test_carry_posts_one_carry_line_when_only_merges_came_in_and_the_pictures_match(self):
        self.seed([self.pics(5)])
        code, out = run(*self.carry_args())
        self.assertEqual((code, out["verdict"], out["from"], out["reason"], out["pictures"], out["comment_id"]),
                         (0, "carried", A, None, self.DIG, 100))
        self.assertEqual(list(out), ["command", "action", "repo", "issue", "pr", "head", "verdict", "from",
                                     "reason", "rule", "pictures", "comment_id"])
        self.assertEqual(out["rule"], "pictures")
        stored = self.world.stored()
        self.assertEqual([c["id"] for c in stored], [5, 100])
        self.assertEqual(stored[1]["body"], self.LINE)
        self.assertFalse([c for c in stored if c["id"] != 5 and c["body"].startswith("<!-- agent:look v1")])

    def test_a_repeat_carry_posts_nothing_new(self):
        self.seed([self.pics(5), comment(6, self.LINE)])
        code, out = run(*self.carry_args())
        self.assertEqual((code, out["verdict"], out["comment_id"]), (0, "carried", 6))
        self.assertEqual(len(self.world.stored()), 2)
        self.assertEqual(self.posted(), [])

    def assert_needed(self, reason, code=0):
        got, out = run(*self.carry_args())
        self.assertEqual((got, out["verdict"], out["reason"], out["comment_id"]), (code, "needed", reason, None))
        self.assertEqual(self.posted(), [])
        return out

    def test_a_changed_picture_carries_nothing(self):
        self.after.write_bytes(b"after, moved")
        self.seed([self.pics(5)])
        self.assert_needed("pictures-differ")
        for argv in self.world.argvs("gh"):
            self.assertFalse(any("pulls/" in part or "compare/" in part for part in argv), argv)

    def test_swapped_before_and_after_pictures_carry_nothing(self):
        # The same two picture ids, each in the other's role, are another card: the approved after picture differs.
        self.seed([self.pics(5)])
        argv = ["carry", *POST, "--from", A, "--before", str(self.after), "--after", str(self.before)]
        code, out = run(*argv)
        self.assertEqual((code, out["verdict"], out["reason"], out["comment_id"]), (0, "needed", "pictures-differ", None))
        self.assertEqual(self.posted(), [])
        for argv in self.world.argvs("gh"):
            self.assertFalse(any("pulls/" in part or "compare/" in part for part in argv), argv)

    def test_a_repeat_carry_names_the_line_the_writers_kept_when_two_are_visible(self):
        # Writers keep the smallest live line and delete the other, so a retry that sees both names the smaller.
        self.seed([self.pics(5), comment(101, self.LINE), comment(100, self.LINE)])
        code, out = run(*self.carry_args())
        self.assertEqual((code, out["verdict"], out["comment_id"]), (0, "carried", 100))
        self.assertEqual(self.posted(), [])

    def test_a_non_merge_commit_carries_nothing(self):
        self.seed([self.pics(5)], self.merges([(A, [FORK]), (HEAD, [A])]))
        self.assert_needed("not-merges")

    def test_no_carried_approval_carries_nothing(self):
        cases = {
            "no comments": [],
            "changes on another head": [self.pics(5, head=OTHER, answer="changes")],
            "a fix approval": [comment(5, lm.approval_body(7, 12, A, "fix", "m5", words="bold"))],
        }
        for name, comments in cases.items():
            with self.subTest(name):
                self.world = ForgeWorld(self)
                self.seed(comments)
                self.assert_needed("no-approval")

    def test_a_carry_from_another_head_than_the_approval_carries_nothing(self):
        self.seed([self.pics(5)])
        got, out = run(*self.carry_args(source=self.T))
        self.assertEqual((got, out["verdict"], out["reason"], out["from"]), (0, "needed", "source-differs", A))
        self.assertEqual(self.posted(), [])
        for argv in self.world.argvs("gh"):
            self.assertFalse(any("pulls/" in part or "compare/" in part for part in argv), argv)

    def test_an_exact_approval_needs_no_carry(self):
        self.seed([comment(5, lm.approval_body(7, 12, HEAD, "approved", "m5"))])
        code, out = run(*self.carry_args())
        self.assertEqual((code, out["verdict"], out["comment_id"]), (0, "approved", None))
        self.assertEqual(self.posted(), [])

    def test_an_unmarked_issue_is_unmarked(self):
        self.seed([self.pics(5)], body="no marker here")
        code, out = run(*self.carry_args())
        self.assertEqual((code, out["verdict"]), (0, "unmarked"))
        self.assertEqual(self.world.argvs("gh"), [ISSUE_ARGV])

    def test_a_moved_pull_request_posts_nothing(self):
        for name, extra in {"head": {"head": OTHER}, "state": {"state": "closed"}}.items():
            with self.subTest(name):
                self.world = ForgeWorld(self)
                self.seed([self.pics(5)], **extra)
                code, out = run(*self.carry_args())
                self.assertEqual((code, out["verdict"]), (1, "moved"))
                self.assertEqual(self.posted(), [])

    def test_an_untrusted_carry_post_is_untrusted(self):
        self.seed([self.pics(5)], trusted=False)
        code, out = run(*self.carry_args())
        self.assertEqual((code, out["verdict"]), (1, "untrusted"))

    def test_an_unreadable_compare_is_an_error(self):
        compares = self.merges()
        compares[f"compare/{B}...{HEAD}"] = {}
        self.seed([self.pics(5)], compares)
        code, out = run(*self.carry_args())
        self.assertEqual((code, out["verdict"], out["error"]), (1, "error", "payload_invalid"))
        self.assertEqual(self.posted(), [])

    def test_overlapping_carries_settle_on_one_trusted_line(self):
        real = forge_markers._posted
        for rival, comment_id, deleted in ((99, 99, True), (101, 100, False)):
            with self.subTest(rival=rival):
                self.world = ForgeWorld(self)
                self.seed([self.pics(5)])

                def rival_first(slug, issue, body, rival=rival):
                    self.world.append_comment({"id": rival, "body": self.LINE, "author_association": "OWNER",
                                               "created_at": T0, "updated_at": T0})
                    return real(slug, issue, body)

                with mock.patch.object(forge_markers, "_posted", side_effect=rival_first):
                    code, out = run(*self.carry_args())
                self.assertEqual((code, out["verdict"], out["comment_id"]), (0, "carried", comment_id))
                delete = ["api", "-X", "DELETE", f"repos/{SLUG}/issues/comments/100"]
                self.assertEqual(delete in self.world.argvs("gh"), deleted)
                lines = [c["id"] for c in self.world.stored() if c["body"].startswith("<!-- agent:look-carry")]
                self.assertEqual(lines, [99] if deleted else [100, 101])

    TESTCONTENTS = f"contents/.github/look-files.json?ref={B}"

    def files(self, a_files=(TESTF,), h_files=(TESTF,), tail=None, ah_files=("docs/x.md",)):
        return {
            f"compare/{B}...{A}": cmp(a_files, commits=[(A, [FORK])]),
            f"compare/{A}...{HEAD}": cmp(ah_files),
            f"compare/{B}...{HEAD}": cmp(h_files, commits=tail or [(A, [FORK]), (HEAD, [A, self.X])]),
            self.TESTCONTENTS: CONSOLE,
        }

    def plain(self, cid):
        return comment(cid, lm.approval_body(7, 12, A, "approved", f"m{cid}"))

    def look_files_run(self, *extra):
        return run("carry", *POST, "--from", A, *extra)

    def assert_look_needed(self, reason, rule="look-files"):
        code, out = self.look_files_run()
        self.assertEqual((code, out["verdict"], out["reason"], out["rule"], out["comment_id"]),
                         (0, "needed", reason, rule, None))
        self.assertEqual(self.posted(), [])
        return out

    def test_an_approval_without_pictures_carries_by_the_unchanged_look_file_diff(self):
        self.seed([self.plain(5)], self.files())
        code, out = self.look_files_run()
        self.assertEqual((code, out["verdict"], out["from"], out["reason"], out["rule"], out["pictures"],
                          out["comment_id"]), (0, "carried", A, None, "look-files", None, 100))
        self.assertEqual(list(out), ["command", "action", "repo", "issue", "pr", "head", "verdict", "from",
                                     "reason", "rule", "pictures", "comment_id"])
        self.assertEqual(self.world.stored()[-1]["body"], lm.carry_body(7, 12, A, HEAD, None))

    def test_an_unchanged_change_to_a_look_file_carries(self):
        self.seed([self.plain(5)], self.files((PAGE,), (PAGE,)))
        code, out = self.look_files_run()
        self.assertEqual((code, out["verdict"], out["rule"]), (0, "carried", "look-files"))

    def test_a_changed_look_file_diff_carries_nothing(self):
        self.seed([self.plain(5)], self.files((TESTF,), (TESTF, PAGE)))
        self.assert_look_needed("look-files-differ")

    def test_a_non_merge_commit_carries_nothing_under_the_look_file_rule(self):
        self.seed([self.plain(5)], self.files(tail=[(A, [FORK]), (HEAD, [A])]))
        self.assert_look_needed("not-merges")

    def test_an_absent_look_file_set_carries_nothing(self):
        compares = self.files()
        del compares[self.TESTCONTENTS]
        self.seed([self.plain(5)], compares)
        self.world.not_found("gh", ["api", f"repos/{SLUG}/{self.TESTCONTENTS}"])
        self.assert_look_needed("no-look-files")

    def test_an_unreadable_look_file_set_is_an_error(self):
        compares = self.files()
        compares[self.TESTCONTENTS] = contents("{}")
        self.seed([self.plain(5)], compares)
        code, out = self.look_files_run()
        self.assertEqual((code, out["verdict"], out["error"]), (1, "error", "payload_invalid"))
        self.assertEqual(self.posted(), [])

    def test_a_pictured_approval_with_no_picture_given_carries_nothing(self):
        self.seed([self.pics(5)])
        self.assert_look_needed("pictures-missing", "pictures")
        for argv in self.world.argvs("gh"):
            self.assertFalse(any("pulls/" in part or "compare/" in part for part in argv), argv)

    def test_a_repeat_look_files_carry_posts_nothing_new(self):
        self.seed([self.plain(5), comment(6, lm.carry_body(7, 12, A, HEAD, None))], self.files())
        code, out = self.look_files_run()
        self.assertEqual((code, out["verdict"], out["comment_id"]), (0, "carried", 6))
        self.assertEqual(self.posted(), [])

    def test_the_look_file_carry_reads_each_path_once(self):
        self.seed([self.plain(5)], self.files())
        self.look_files_run()
        reads_made = [a for a in self.world.argvs("gh")
                      if a[0] == "api" and ("compare/" in a[1] or "contents/" in a[1])]
        self.assertEqual(len(reads_made), 4)
        self.assertEqual(len(reads_made), len({tuple(a) for a in reads_made}))

    def test_a_look_files_line_does_not_carry_a_pictured_approval(self):
        self.seed([self.pics(5), comment(6, lm.carry_body(7, 12, A, HEAD, None))])
        code, out = run(*self.carry_args())
        self.assertEqual((code, out["verdict"], out["rule"], out["comment_id"]), (0, "carried", "pictures", 100))
        self.assertEqual(self.world.stored()[-1]["body"], self.LINE)

    def test_a_merge_that_brought_a_look_file_in_carries_nothing(self):
        self.seed([self.plain(5)], self.files(ah_files=("docs/x.md", PAGE)))
        self.assert_look_needed("look-files-differ")

    def test_a_look_file_one_merge_brought_in_and_a_later_merge_took_out_carries_nothing(self):
        two = [(A, [FORK]), (self.T, [A, self.X]), (HEAD, [self.T, OTHER])]
        compares = self.files(tail=two)
        compares[f"compare/{A}...{self.T}"] = cmp([PAGE])
        compares[f"compare/{self.T}...{HEAD}"] = cmp([PAGE])
        self.seed([self.plain(5)], compares)
        self.assert_look_needed("look-files-differ")
        compares[f"compare/{A}...{self.T}"] = cmp(["docs/x.md"])
        compares[f"compare/{self.T}...{HEAD}"] = cmp(["docs/y.md"])
        self.seed([self.plain(5)], compares)
        code, out = self.look_files_run()
        self.assertEqual((code, out["verdict"], out["rule"]), (0, "carried", "look-files"))

    def test_an_unreadable_listing_of_the_merges_is_an_error(self):
        compares = self.files()
        compares[f"compare/{A}...{HEAD}"] = {"status": "ahead", "files": "x", "total_commits": 0, "commits": []}
        self.seed([self.plain(5)], compares)
        code, out = self.look_files_run()
        self.assertEqual((code, out["verdict"], out["error"]), (1, "error", "payload_invalid"))
        self.assertIn(f"compare/{A}...{HEAD}", out["detail"])
        self.assertEqual(self.posted(), [])

    def test_a_malformed_pictures_field_carries_nothing(self):
        bad = comment(5, forge_markers.render(lm.KIND, {"issue": "7", "pr": "12", "head": A,
                                                         "answer": "approved", "message": "m5",
                                                         "pictures": "zz"}, "x"))
        for name, extra in (("none given", []), ("pictures given", ["--before", str(self.before), "--after", str(self.after)])):
            with self.subTest(name):
                self.world = ForgeWorld(self)
                self.seed([bad], self.files())
                code, out = self.look_files_run(*extra)
                self.assertEqual((code, out["verdict"], out["reason"], out["rule"]),
                                 (0, "needed", "pictures-unreadable", None))
                self.assertEqual(self.posted(), [])
                for argv in self.world.argvs("gh"):
                    self.assertFalse(any("pulls/" in part or "compare/" in part for part in argv), argv)

    def test_a_line_naming_both_rules_never_wins_the_write(self):
        odd = comment(6, forge_markers.render(lm.CARRY_KIND, {"issue": "7", "pr": "12", "from": A, "to": HEAD,
                                                              "pictures": self.DIG, "rule": "look-files"}, "x"))
        for name, approval, compares, argv in (
                ("look-files", self.plain(5), self.files(), ["carry", *POST, "--from", A]),
                ("pictures", self.pics(5), None, self.carry_args())):
            with self.subTest(name):
                self.world = ForgeWorld(self)
                self.seed([approval, odd], compares)
                code, out = run(*argv)
                self.assertEqual((code, out["verdict"], out["comment_id"]), (0, "carried", 100))
                self.assertFalse([a for a in self.world.argvs("gh") if a[:3] == ["api", "-X", "DELETE"]])
                self.assertEqual([c["id"] for c in self.world.stored()], [5, 6, 100])
                if name == "look-files":
                    code, out = run(*STATUS)
                    self.assertEqual((code, out["verdict"], out["comment_id"], out["kept_from"]),
                                     (0, "approved", 5, A))

    def own_files_comment(self, cid, **extra):
        fields = {"issue": "7", "pr": "12", "from": A, "to": HEAD, "rule": "own-files", **extra}
        return comment(cid, forge_markers.render(lm.CARRY_KIND, fields, "x"))

    def own_files_run(self, *extra):
        return run("carry", *POST, "--from", A, "--own-files", *extra)

    def test_carry_own_files_records_a_line_when_the_merges_touch_no_own_file(self):
        self.seed([self.pics(5)])
        code, out = self.own_files_run()
        self.assertEqual((code, out["verdict"], out["from"], out["reason"], out["rule"], out["pictures"],
                          out["comment_id"]), (0, "carried", A, None, "own-files", None, 100))
        self.assertEqual(list(out), ["command", "action", "repo", "issue", "pr", "head", "verdict", "from",
                                     "reason", "rule", "pictures", "comment_id"])
        self.assertEqual(self.world.stored()[-1]["body"].splitlines()[0],
                         f"<!-- agent:look-carry v1 issue=7 pr=12 from={A} to={HEAD} rule=own-files -->")
        self.assertEqual(len(self.posted()), 1)
        for argv in self.world.argvs("gh"):
            self.assertFalse(any("contents/" in part for part in argv), argv)

    def test_carry_own_files_refuses_when_a_merge_touches_an_own_file(self):
        compares = self.merges()
        compares[f"compare/{A}...{HEAD}"] = cmp([PAGE])
        self.seed([self.pics(5)], compares)
        code, out = self.own_files_run()
        self.assertEqual((code, out["verdict"], out["reason"], out["rule"], out["comment_id"]),
                         (0, "needed", "own-files-touched", "own-files", None))
        self.assertEqual(self.posted(), [])

    def test_carry_own_files_refuses_a_malformed_pictures_field(self):
        bad = comment(5, forge_markers.render(lm.KIND, {"issue": "7", "pr": "12", "head": A,
                                                         "answer": "approved", "message": "m5",
                                                         "pictures": "nothex"}, "x"))
        self.seed([bad])
        code, out = self.own_files_run()
        self.assertEqual((code, out["verdict"], out["reason"], out["rule"], out["comment_id"]),
                         (0, "needed", "pictures-unreadable", None, None))
        self.assertEqual(self.posted(), [])

    def test_carry_own_files_refuses_a_non_merge_commit(self):
        self.seed([self.pics(5)], self.merges([(A, [FORK]), (HEAD, [A])]))
        code, out = self.own_files_run()
        self.assertEqual((code, out["verdict"], out["reason"], out["comment_id"]), (0, "needed", "not-merges", None))
        self.assertEqual(self.posted(), [])

    def test_carry_own_files_with_a_picture_flag_is_a_usage_error(self):
        for flag in ("--before", "--after", "--picture"):
            with self.subTest(flag=flag):
                self.world = ForgeWorld(self)
                code, out = self.own_files_run(flag, str(self.before))
                self.assertEqual((code, out["verdict"], out["error"]), (2, "error", "usage"))
                self.assertEqual(self.world.argvs("gh"), [])

    def test_status_reads_an_own_files_carry_line_as_a_kept_approval(self):
        self.seed([self.pics(5), self.own_files_comment(6)])
        code, out = run(*STATUS)
        self.assertEqual((code, out["verdict"], out["comment_id"], out["kept_from"]), (0, "approved", 5, A))

    def test_a_line_naming_own_files_and_pictures_carries_nothing(self):
        self.seed([self.pics(5), self.own_files_comment(6, pictures=self.DIG)])
        code, out = run(*STATUS)
        self.assertEqual((code, out["verdict"]), (0, "needed"))

    def test_a_truncated_compare_never_carries_by_own_files(self):
        compares = self.merges()
        compares[f"compare/{A}...{HEAD}"] = cmp([f"docs/f{n}.md" for n in range(lm.COMPARE_FILE_LIMIT)])
        self.seed([self.pics(5)], compares)
        code, out = self.own_files_run()
        self.assertEqual((code, out["verdict"], out["reason"]), (0, "needed", "own-files-touched"))
        self.assertEqual(self.posted(), [])

    def test_plain_carry_does_not_short_circuit_on_an_own_files_line(self):
        self.seed([self.pics(5), self.own_files_comment(70)])
        code, out = run(*self.carry_args())
        self.assertEqual((code, out["verdict"], out["rule"], out["comment_id"]), (0, "carried", "pictures", 100))
        self.assertEqual(len(self.posted()), 1)

    def test_carry_usage_errors_come_before_any_gh_call(self):
        full = self.carry_args()
        cases = {
            "unreadable after": ["carry", *POST, "--from", A, "--before", str(self.before),
                                 "--after", str(self.tmp / "none.png")],
            "missing file": ["carry", *POST, "--from", A, "--picture", str(self.tmp / "none.png")],
            "head not hex": ["carry", *POST[:-1], "xyz", "--from", A, "--picture", str(self.before)],
            "no from": ["carry", *POST, "--picture", str(self.before)],
            "from is head": ["carry", *POST, "--from", HEAD, "--picture", str(self.before)],
        }
        self.assertEqual(full[0], "carry")
        for name, argv in cases.items():
            with self.subTest(name):
                self.world = ForgeWorld(self)
                code, out = run(*argv)
                self.assertEqual((code, out["verdict"], out["error"]), (2, "error", "usage"))
                self.assertEqual(self.world.argvs("gh"), [])


class StatusMergedTest(unittest.TestCase):
    BRANCH_ARGV = ["api", f"repos/{SLUG}/branches/main"]
    COMMIT_ARGV = ["api", f"repos/{SLUG}/commits/{MC}"]
    PULL = {"number": 12, "merged": True, "head": {"sha": HEAD}, "base": {"ref": "main"}, "merge_commit_sha": MC}

    def setUp(self):
        self.world = ForgeWorld(self)

    def seed(self, pull=None):
        self.world.comment_store(SLUG, ISSUE, [comment(5, lm.approval_body(7, 12, A, "approved", "m1"))])
        self.world.respond_json("gh", ISSUE_ARGV, {"number": 7, "body": BODY})
        self.world.respond_json("gh", PULL_ARGV, self.PULL if pull is None else pull)
        self.world.respond_json("gh", self.COMMIT_ARGV, {"sha": MC, "parents": [{"sha": BT}, {"sha": HEAD}]})
        self.world.respond_json("gh", self.BRANCH_ARGV, {"name": "main", "commit": {"sha": B}})
        for path in (f"contents/.github/look-files.json?ref={B}", f"compare/{B}...{A}", f"compare/{B}...{HEAD}"):
            self.world.not_found("gh", ["api", f"repos/{SLUG}/{path}"])
        serve(self.world, SLUG, reads(BT))

    def test_status_of_a_merged_head_settles_a_kept_approval_at_the_merge_commits_first_parent(self):
        self.seed()
        code, out = run(*STATUS)
        self.assertEqual((code, out["verdict"], out["answer"], out["comment_id"], out["kept_from"]),
                         (0, "approved", "approved", 5, A))
        self.assertNotIn(self.BRANCH_ARGV, self.world.argvs("gh"))

    def test_status_of_a_merged_head_with_an_unreadable_merge_commit_is_an_error(self):
        with self.subTest("no merge commit sha"):
            self.seed({k: v for k, v in self.PULL.items() if k != "merge_commit_sha"})
            code, out = run(*STATUS)
            self.assertEqual((code, out["verdict"], out["error"]), (1, "error", "payload_invalid"))
            self.assertNotIn("kept_from", out)
        with self.subTest("merge commit not found"):
            self.world = ForgeWorld(self)
            self.seed()
            self.world.not_found("gh", self.COMMIT_ARGV)
            code, out = run(*STATUS)
            self.assertEqual((code, out["verdict"], out["error"]), (1, "error", "payload_invalid"))
            self.assertNotIn("kept_from", out)

    def test_an_indirect_merge_is_settled_at_the_landing_commit_the_caller_resolved(self):
        """#1356 I3: a null merge_commit_sha alone is an error; the resolved landing commit stands in for it."""
        indirect = {k: v for k, v in self.PULL.items() if k != "merge_commit_sha"}
        self.seed(dict(indirect, merge_commit_sha=None))
        code, out = run(*STATUS, "--merge-commit", MC)
        self.assertEqual((code, out["verdict"], out["kept_from"]), (0, "approved", A))
        self.assertIn(self.COMMIT_ARGV, self.world.argvs("gh"))


class TickCarryTest(unittest.TestCase):
    TICK = ["tick", *POST]
    PULL = {"number": 12, "merged": True, "head": {"sha": HEAD}, "base": {"ref": "main"}, "merge_commit_sha": MC}
    COMMIT = {"sha": MC, "parents": [{"sha": BT}, {"sha": HEAD}]}
    PATCH = TickTest.PATCH

    def setUp(self):
        self.world = ForgeWorld(self)

    def seed(self, served=None, pull=None, comments=None):
        self.world.comment_store(SLUG, ISSUE, [comment(5, lm.approval_body(7, 12, A, "approved", "m5"))]
                                 if comments is None else comments)
        self.world.respond_json("gh", ISSUE_ARGV, {"number": 7, "body": TickTest.TICK_BODY})
        self.world.respond_json("gh", PULL_ARGV, self.PULL if pull is None else pull)
        self.world.respond_json("gh", self.PATCH, {"number": 7})
        self.world.respond_json("gh", ["api", f"repos/{SLUG}/commits/{MC}"], self.COMMIT)
        self.world.respond_json("gh", ["api", f"repos/{SLUG}/contents/.github/look-files.json?ref=main"], SHRUNK)
        serve(self.world, SLUG, reads(BT) if served is None else served)

    def patches(self):
        return [argv for argv in self.world.argvs("gh") if argv[:3] == ["api", "-X", "PATCH"]]

    def test_tick_ticks_under_a_kept_approval(self):
        self.seed()
        code, out = run(*self.TICK)
        self.assertEqual((code, out["verdict"], out["ticked"], out["kept_from"]), (0, "ticked", 1, A))
        self.assertEqual(len(self.patches()), 1)

    def test_tick_accepts_an_own_files_carry_line(self):
        pictured = comment(5, lm.approval_body(7, 12, A, "approved", "m5", pictures=CarryVerbTest.DIG))
        line = comment(6, lm.carry_body(7, 12, A, HEAD, None, rule=lm.OWN_FILES_RULE))
        served = {f"compare/{BT}...{A}": cmp([PAGE], commits=[(A, [FORK])]),
                  f"compare/{A}...{HEAD}": cmp(["docs/x.md"]),
                  f"compare/{BT}...{HEAD}": cmp(commits=[(A, [FORK]), (HEAD, [A, "7" * 40])])}
        self.seed(served, comments=[pictured, line])
        code, out = run(*self.TICK)
        self.assertEqual((code, out["verdict"], out["ticked"], out["kept_from"]), (0, "ticked", 1, A))
        self.assertEqual(len(self.patches()), 1)

    def test_tick_of_an_indirect_merge_ticks_at_the_landing_commit_the_caller_resolved(self):
        """#1356 I3: the same resolved landing commit serves `tick`; without it the null merge_commit_sha is an error."""
        self.seed(pull=dict(self.PULL, merge_commit_sha=None))
        code, out = run(*self.TICK)
        self.assertEqual((code, out["verdict"]), (1, "error"))
        self.assertEqual(self.patches(), [])
        code, out = run(*self.TICK, "--merge-commit", MC)
        self.assertEqual((code, out["verdict"], out["ticked"], out["kept_from"]), (0, "ticked", 1, A))
        self.assertEqual(len(self.patches()), 1)

    def test_tick_reads_the_set_at_the_merge_base(self):
        self.seed(reads(BT, ah_files=(PAGE,)))
        code, out = run(*self.TICK)
        self.assertEqual((code, out["verdict"]), (1, "needed"))
        self.assertEqual(self.patches(), [])
        for argv in self.world.argvs("gh"):
            self.assertFalse(argv[-1].endswith("?ref=main"), argv)

    def test_tick_reports_an_unreadable_carry_as_an_error(self):
        cases = {
            "http 500": lambda: self.world.respond(
                "gh", ["api", f"repos/{SLUG}/compare/{BT}...{HEAD}"], exit=1,
                stderr="gh: Internal Server Error (HTTP 500)"),
            "empty compare": lambda: self.world.respond_json(
                "gh", ["api", f"repos/{SLUG}/compare/{BT}...{HEAD}"], {}),
            "no merge commit sha": lambda: self.world.respond_json(
                "gh", PULL_ARGV, {k: v for k, v in self.PULL.items() if k != "merge_commit_sha"}),
            "merge commit not found": lambda: self.world.not_found("gh", ["api", f"repos/{SLUG}/commits/{MC}"]),
        }
        for name, break_it in cases.items():
            with self.subTest(name):
                self.world = ForgeWorld(self)
                self.seed()
                break_it()
                code, out = run(*self.TICK)
                self.assertEqual((code, out["verdict"]), (1, "error"))
                if name != "http 500":
                    self.assertEqual(out["error"], "payload_invalid")
                self.assertEqual(self.patches(), [])


class CarryJudgeTest(unittest.TestCase):
    ROUND_ONE = sorted([f"contents/.github/look-files.json?ref={B}", f"compare/{B}...{A}",
                        f"compare/{A}...{HEAD}", f"compare/{B}...{HEAD}"])

    def judge(self, stdin):
        return JudgeTest.judge(self, stdin)

    def payload(self, carry=None):
        data = {"pr": 12, "head": HEAD, "issues": [{"number": 1200, "body": BODY, "comments": [
            comment(5, lm.approval_body(1200, 12, A, "approved", "m1"))]}]}
        if carry is not None:
            data["carry"] = carry
        return json.dumps(data)

    def test_a_refusal_names_the_carry_candidates(self):
        code, out = self.judge(self.payload())
        self.assertEqual((code, out), (1, {
            "command": "look-approval", "action": "judge", "verdict": "refuse", "issue": 1200, "covers": [WHAT],
            "candidates": [{"issue": 1200, "head": A, "answer": "approved"}]}))

    def test_a_carry_run_names_its_reads(self):
        code, out = self.judge(self.payload({"base": B, "reads": {}}))
        self.assertEqual(code, 1)
        self.assertEqual(out["need"], self.ROUND_ONE)

    def test_a_kept_approval_admits_once_its_reads_are_given(self):
        served = {path: value for path, value in reads(B).items()}
        code, out = self.judge(self.payload({"base": B, "reads": served}))
        self.assertEqual((code, out), (0, {"command": "look-approval", "action": "judge", "verdict": "admit",
                                           "marked": [1200]}))

    def test_a_changed_look_file_refuses_with_nothing_to_read(self):
        code, out = self.judge(self.payload({"base": B, "reads": reads(B, ah_files=(PAGE,))}))
        self.assertEqual((code, out["verdict"]), (1, "refuse"))
        self.assertNotIn("need", out)

    def test_the_guard_runs_admit_a_pictured_approval_carried_by_its_own_files_line(self):
        digest = CarryVerbTest.DIG
        data = {"pr": 12, "head": HEAD, "issues": [{"number": 1200, "body": BODY, "comments": [
            comment(5, lm.approval_body(1200, 12, A, "approved", "m1", pictures=digest)),
            comment(6, lm.carry_body(1200, 12, A, HEAD, None, rule=lm.OWN_FILES_RULE))]}]}
        served = {f"compare/{B}...{A}": cmp([PAGE], commits=[(A, [FORK])]),
                  f"compare/{A}...{HEAD}": cmp(["docs/b.md"]),
                  f"compare/{B}...{HEAD}": cmp(commits=[(A, [FORK]), (HEAD, [A, "7" * 40])])}
        code, out = self.judge(json.dumps(data))
        self.assertEqual((code, out["verdict"], out["candidates"]),
                         (1, "refuse", [{"issue": 1200, "head": A, "answer": "approved"}]))
        code, out = self.judge(json.dumps({**data, "carry": {"base": B, "reads": {}}}))
        self.assertEqual((code, out["verdict"]), (1, "refuse"))
        self.assertEqual(out["need"], sorted(f"compare/{x}...{y}" for x, y in ((B, A), (A, HEAD), (B, HEAD))))
        for path in out["need"]:
            self.assertTrue(lm.read_path_ok(path, B), path)
        code, out = self.judge(json.dumps({**data, "carry": {"base": B, "reads": served}}))
        self.assertEqual((code, out), (0, {"command": "look-approval", "action": "judge", "verdict": "admit",
                                           "marked": [1200]}))

    def test_a_malformed_carry_is_a_usage_error(self):
        cases = [[], {"base": B}, {"base": "main", "reads": {}}, {"base": B, "reads": []},
                 {"base": B, "reads": {"issues/1": {}}}, {"base": B, "reads": {}, "x": 1}]
        for carry in cases:
            with self.subTest(carry=carry):
                code, out = self.judge(self.payload(carry))
                self.assertEqual((code, out["verdict"], out["error"]), (2, "error", "usage"))


class UsageTest(unittest.TestCase):
    def test_bad_arguments_are_usage_errors_before_any_gh_call(self):
        world = ForgeWorld(self)
        cases = {
            "short head": ["status", "--repo", SLUG, "--issue", "7", "--pr", "12", "--head", HEAD[:39]],
            "answer": ["post", *POST, "--answer", "maybe", "--message", "m"],
            "message": ["post", *POST, "--answer", "approved", "--message", "a b"],
            "issue": ["status", "--repo", SLUG, "--issue", "x", "--pr", "12", "--head", HEAD],
            "repo": ["status", "--repo", "nope", "--issue", "7", "--pr", "12", "--head", HEAD],
            "verb": ["frobnicate", *POST],
            "merge commit": ["tick", *POST, "--merge-commit", MC[:39]],
            "missing pr": ["status", "--repo", SLUG, "--issue", "7", "--head", HEAD],
        }
        for name, argv in cases.items():
            with self.subTest(name):
                code, out = run(*argv)
                self.assertEqual((code, out["error"], out["verdict"]), (2, "usage", "error"))
                self.assertEqual(out["command"], "look-approval")
        self.assertEqual(world.calls(), [])


class JudgeTest(unittest.TestCase):
    def judge(self, stdin):
        env = {**os.environ, "PYTHONPATH": str(REPO_ROOT / "python")}
        done = subprocess.run([sys.executable, "-m", "agent_tools.delivery.look_approval", "judge"],
                              input=stdin, env=env, capture_output=True, text=True)
        self.assertEqual(len(done.stdout.splitlines()), 1, done.stdout + done.stderr)
        return done.returncode, json.loads(done.stdout)

    def payload(self, comments=(), pr=12):
        return json.dumps({"pr": pr, "head": HEAD, "issues": [
            {"number": 1200, "body": BODY, "comments": list(comments)}]})

    def test_judge_answers_from_stdin(self):
        approval = comment(5, lm.approval_body(1200, 12, HEAD, "approved", "m1"))
        code, out = self.judge(self.payload())
        self.assertEqual((code, out), (1, {"command": "look-approval", "action": "judge",
                                           "verdict": "refuse", "issue": 1200, "covers": [WHAT]}))
        code, out = self.judge(self.payload([approval]))
        self.assertEqual((code, out), (0, {"command": "look-approval", "action": "judge", "verdict": "admit",
                                           "marked": [1200]}))
        unmarked = json.dumps({"pr": 12, "head": HEAD, "issues": [
            {"number": 7, "body": "plain", "comments": []}]})
        code, out = self.judge(unmarked)
        self.assertEqual((code, out), (0, {"command": "look-approval", "action": "judge",
                                           "verdict": "admit", "marked": []}))
        code, out = self.judge("{")
        self.assertEqual((code, out["error"]), (2, "usage"))
        code, out = self.judge(self.payload(pr=True))
        self.assertEqual((code, out["error"]), (2, "usage"))
        code, out = self.judge(self.payload([{**approval, "id": "x"}]))
        self.assertEqual((code, out["verdict"], out["error"]), (2, "error", "payload_invalid"))


if __name__ == "__main__":
    unittest.main()
