"""Tests for `agent_tools.delivery.look_approval` (issue 1138): post, status and judge."""
import contextlib
import io
import json
import os
import subprocess
import sys
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


def comment(cid, body, association="OWNER"):
    return {"id": cid, "body": body, "updated_at": T0, "created_at": T0,
            "author_association": association, "user": {"login": "octo"}}


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
        self.seed([comment(5, lm.approval_body(7, 12, OTHER, "approved", "m1"))])
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
                                           "issue": 7, "verdict": "marked", "covers": [WHAT]}))
        self.assertEqual([call["argv"] for call in self.world.calls()], [ISSUE_ARGV])

    def test_an_unmarked_or_fenced_body_is_unmarked(self):
        for body in ("plain", None, "```\n" + BODY + "```\n"):
            with self.subTest(body=body):
                self.world.respond_json("gh", ISSUE_ARGV, {"number": 7, "body": body})
                code, out = run(*self.MARKED)
                self.assertEqual((code, out["verdict"], out["covers"]), (0, "unmarked", []))

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
            "other head": [self.approval(5, head=OTHER)],
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
