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

    def seed(self, served=None, pull=None):
        self.world.comment_store(SLUG, ISSUE, [comment(5, lm.approval_body(7, 12, A, "approved", "m5"))])
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
