"""forge-claim (issue 623): acquire, renew and release against the fake gh."""
import contextlib
import io
import json
import os
import subprocess
import sys
import unittest

from agent_tools import forge_claim
from agent_tools import forge_markers as fm
from .forge_world import ForgeWorld

SLUG, ISSUE = "octo/widgets", 7
ME, OTHER = "mbp/session-a", "eleven-m5/session-b"
T0 = "2026-11-06T10:00:00Z"
MATCH = {"issue": str(ISSUE)}
LIST = ["api", "--paginate", "--slurp", f"repos/{SLUG}/issues/{ISSUE}/comments?per_page=100"]
ENSURE = ["api", "-X", "POST", f"repos/{SLUG}/labels", "-f", "name=in-progress", "-f", "color=FBCA04"]
ADD = ["api", "-X", "POST", f"repos/{SLUG}/issues/{ISSUE}/labels", "-f", "labels[]=in-progress"]
REMOVE = ["api", "-X", "DELETE", f"repos/{SLUG}/issues/{ISSUE}/labels/in-progress"]
OA_ENSURE = ["api", "-X", "POST", f"repos/{SLUG}/labels", "-f", "name=owner-action", "-f", "color=D93F0B"]
OA_ADD = ["api", "-X", "POST", f"repos/{SLUG}/issues/{ISSUE}/labels", "-f", "labels[]=owner-action"]
OA_REMOVE = ["api", "-X", "DELETE", f"repos/{SLUG}/issues/{ISSUE}/labels/owner-action"]


def claim_body(holder, **extra):
    return fm.render("claim", {"issue": str(ISSUE), "holder": holder, **extra}, f"Claimed by {holder}.")


def oa_body(claim_id, holder, ticked=False):
    return fm.render("owner-action", {"issue": str(ISSUE), "reason": "stale-claim", "claim": str(claim_id)},
                     f"The claim of {holder} has had no renewal, push or pull request activity for 24 hours.",
                     f"- [{'x' if ticked else ' '}] Release this claim")


def comment(cid, body, updated_at=T0):
    return {"id": cid, "body": body, "updated_at": updated_at, "created_at": updated_at}


def post(body):
    return ["api", "-X", "POST", f"repos/{SLUG}/issues/{ISSUE}/comments", "-f", f"body={body}"]


def patch(cid, body):
    return ["api", "-X", "PATCH", f"repos/{SLUG}/issues/comments/{cid}", "-f", f"body={body}"]


def common(command, holder=ME):
    return [command, "--repo", SLUG, "--issue", str(ISSUE), "--holder", holder]


def run(*argv):
    """In-process: policy and clock rows."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = forge_claim.main(list(argv))
    return code, json.loads(out.getvalue())


def start_cli(*argv):
    """A child `python -m agent_tools.forge_claim` in the current (fake) world."""
    return subprocess.Popen([sys.executable, "-m", "agent_tools.forge_claim", *argv], stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, env=dict(os.environ))


def finish(proc):
    stdout, _ = proc.communicate(timeout=120)
    lines = stdout.splitlines()
    assert len(lines) == 1, stdout  # exactly one JSON object, one line (D8)
    return proc.returncode, json.loads(lines[0])


def run_cli(*argv):
    return finish(start_cli(*argv))


class Base(unittest.TestCase):
    def setUp(self):
        self.fresh_world()

    def fresh_world(self):
        self.world = ForgeWorld(self)
        for argv in (ENSURE, ADD, REMOVE, OA_ENSURE, OA_ADD, OA_REMOVE):
            self.world.respond("gh", argv)

    def store(self, *comments, next_id=40, schedule=()):
        self.world.comment_store(SLUG, ISSUE, list(comments), next_id=next_id, schedule=schedule)

    def mutations(self):
        return [argv for argv in self.world.argvs("gh") if "-X" in argv]

    def live(self, kind="claim"):
        markers = [m for m in (fm.parse(c) for c in self.world.stored()) if m]
        return [m for m in markers if m.kind == kind and fm.is_live(m, markers)]


class AcquireTest(Base):
    def test_free_issue_is_acquired_and_labelled(self):
        self.store(next_id=11)
        code, out = run(*common("acquire"))
        self.assertEqual((code, out["verdict"], out["comment_id"], out["by"]), (0, "acquired", 11, None))
        self.assertEqual(self.mutations(), [post(claim_body(ME)), ENSURE, ADD])
        self.assertEqual([m.fields["holder"] for m in self.live()], [ME])

    def test_branch_is_recorded(self):
        self.store(next_id=11)
        code, out = run(*common("acquire"), "--branch", "issue-7-x")
        self.assertEqual((code, out["verdict"]), (0, "acquired"))
        self.assertEqual(self.live()[0].fields["branch"], "issue-7-x")

    def test_own_claim_resumes(self):
        self.store(comment(5, claim_body(ME)))
        code, out = run(*common("acquire"))
        self.assertEqual((code, out["verdict"], out["comment_id"]), (0, "already_held", 5))
        self.assertEqual(self.mutations(), [ENSURE, ADD])

    def test_other_claim_is_held_by_and_untouched(self):
        self.store(comment(5, claim_body(OTHER)))
        code, out = run(*common("acquire"))
        self.assertEqual((code, out["verdict"], out["by"]), (3, "held_by", OTHER))
        self.assertEqual(self.mutations(), [])

    def test_forge_error_is_exit_1(self):
        self.world.respond("gh", LIST, exit=1, stderr="gh: Server Error (HTTP 500)")
        code, out = run(*common("acquire"))
        self.assertEqual((code, out["verdict"], out["error"]), (1, "error", "gh_failed"))

    def test_usage_errors_are_json_exit_2(self):
        for argv in (common("acquire", holder="no-slash"), ["steal", "--repo", SLUG], []):
            with self.subTest(argv=argv):
                with contextlib.redirect_stderr(io.StringIO()):
                    code, out = run(*argv)
                self.assertEqual((code, out["verdict"], out["error"]), (2, "error", "usage"))
                self.assertTrue(out["detail"])
        self.assertEqual(self.world.argvs("gh"), [])


class CliTest(Base):
    """`python -m agent_tools.forge_claim` as a child process (docs/standards/agent-helpers.md rule 5)."""

    def test_acquire_exit_0_one_json_line(self):
        self.store(next_id=11)
        code, out = run_cli(*common("acquire"))
        self.assertEqual((code, out["verdict"], out["comment_id"]), (0, "acquired", 11))

    def test_held_by_exit_3(self):
        self.store(comment(5, claim_body(OTHER)))
        code, out = run_cli(*common("acquire"))
        self.assertEqual((code, out["verdict"], out["by"]), (3, "held_by", OTHER))

    def test_forge_error_exit_1(self):
        self.world.respond("gh", LIST, exit=1, stderr="gh: Server Error (HTTP 500)")
        code, out = run_cli(*common("acquire"))
        self.assertEqual((code, out["error"]), (1, "gh_failed"))

    def test_usage_error_exit_2(self):
        code, out = run_cli(*common("acquire", holder="no-slash"))
        self.assertEqual((code, out["verdict"], out["error"]), (2, "error", "usage"))

    def test_racing_acquires_leave_one_claim(self):
        self.store(next_id=101, schedule=["list", "list", f"post:holder={ME}", f"post:holder={OTHER}",
                                          "list", "list"])
        mine, theirs = start_cli(*common("acquire")), start_cli(*common("acquire", holder=OTHER))
        (my_code, my_out), (their_code, their_out) = finish(mine), finish(theirs)
        self.assertEqual((my_code, my_out["verdict"], my_out["comment_id"]), (0, "acquired", 101))
        self.assertEqual((their_code, their_out["verdict"], their_out["by"]), (3, "lost_to", ME))
        self.assertEqual([m.fields["holder"] for m in self.live()], [ME])
        self.assertNotIn(102, [c["id"] for c in self.world.stored()])


class ReleaseRenewTest(Base):
    def test_renew_edits_the_same_comment(self):
        for before, after in (({}, "1"), ({"renewed": "1"}, "2")):
            with self.subTest(before=before):
                self.fresh_world()
                self.store(comment(5, claim_body(ME, **before)))
                code, out = run(*common("renew"))
                self.assertEqual((code, out["verdict"], out["comment_id"]), (0, "renewed", 5))
                self.assertEqual(self.mutations(), [patch(5, claim_body(ME, renewed=after))])
                self.assertEqual([c["id"] for c in self.world.stored()], [5])

    def test_renew_by_another_holder_is_not_held(self):
        self.store(comment(5, claim_body(OTHER)))
        code, out = run(*common("renew"))
        self.assertEqual((code, out["verdict"], out["by"]), (3, "not_held", OTHER))
        self.assertEqual(self.mutations(), [])

    def test_renew_retires_the_owner_action_on_its_claim(self):
        self.store(comment(5, claim_body(ME)), comment(30, oa_body(5, ME)))
        code, out = run(*common("renew"))
        self.assertEqual((code, out["verdict"]), (0, "renewed"))
        self.assertEqual(self.mutations(), [patch(5, claim_body(ME, renewed="1")),
                                            post(fm.end_body(30, "renewed")), OA_REMOVE])
        self.assertEqual(self.live("owner-action"), [])

    def test_release_removes_the_label_when_no_live_claim_remains(self):
        self.store(comment(5, claim_body(ME)))
        code, out = run(*common("release"))
        self.assertEqual((code, out["verdict"], out["comment_id"], out["label_removed"]),
                         (0, "released", 5, True))
        self.assertEqual(self.mutations(), [post(fm.end_body(5, "done")),
                                            patch(5, claim_body(ME, released="done")), REMOVE])
        self.assertEqual(self.live(), [])

    def test_release_keeps_the_label_while_another_live_claim_remains(self):
        self.store(comment(5, claim_body(ME)), comment(9, claim_body(OTHER)))
        code, out = run(*common("release"), "--reason", "merged")
        self.assertEqual((code, out["verdict"], out["label_removed"]), (0, "released", False))
        self.assertEqual(self.mutations(), [post(fm.end_body(5, "merged")),
                                            patch(5, claim_body(ME, released="merged"))])

    def test_release_retires_the_owner_action_and_its_label(self):
        self.store(comment(5, claim_body(ME)), comment(30, oa_body(5, ME)))
        code, out = run(*common("release"))
        self.assertEqual((code, out["verdict"]), (0, "released"))
        self.assertEqual(self.mutations(), [post(fm.end_body(5, "done")), patch(5, claim_body(ME, released="done")),
                                            post(fm.end_body(30, "released")), OA_REMOVE, REMOVE])
        self.assertEqual(self.live("owner-action"), [])

    def test_release_ends_only_the_claim_of_its_own_holder(self):
        self.store(comment(3, claim_body(OTHER)), comment(5, claim_body(ME)))
        code, out = run(*common("release"))
        self.assertEqual((code, out["verdict"], out["comment_id"], out["label_removed"]),
                         (0, "released", 5, False))
        self.assertEqual(self.mutations(), [post(fm.end_body(5, "done")),
                                            patch(5, claim_body(ME, released="done"))])

    def test_renew_leaves_an_owner_action_of_another_claim(self):
        self.store(comment(5, claim_body(ME)), comment(30, oa_body(99, OTHER)))
        code, out = run(*common("renew"))
        self.assertEqual((code, out["verdict"]), (0, "renewed"))
        self.assertEqual(self.mutations(), [patch(5, claim_body(ME, renewed="1"))])
        self.assertEqual([m.comment_id for m in self.live("owner-action")], [30])

    def test_release_without_a_claim_is_not_held(self):
        self.store()
        code, out = run(*common("release"))
        self.assertEqual((code, out["verdict"]), (3, "not_held"))
        self.assertEqual(self.mutations(), [])

    def test_a_delayed_renewal_cannot_revive_a_released_claim(self):
        # renew reads claim 5; release ends it; OTHER acquires; only then does renew's PATCH land.
        self.store(comment(5, claim_body(ME)),
                   schedule=["list", "post:agent:end v1 of=5 ", f"post:holder={OTHER}", "patch:5:renewed=1"])
        renewal = start_cli(*common("renew"))
        self.world.wait_cursor(1)
        code, out = run_cli(*common("release"))
        self.assertEqual((code, out["verdict"]), (0, "released"))
        code, out = run_cli(*common("acquire", holder=OTHER))
        self.assertEqual((code, out["verdict"]), (0, "acquired"))
        code, out = finish(renewal)
        self.assertEqual((code, out["verdict"], out["comment_id"]), (3, "not_held", 5))
        claim5 = next(c["body"] for c in self.world.stored() if c["id"] == 5)
        self.assertEqual(claim5, claim_body(ME, renewed="1"))  # the stale PATCH dropped `released` ...
        self.assertEqual([m.fields["holder"] for m in self.live()], [OTHER])  # ... and the end still holds


if __name__ == "__main__":
    unittest.main()
