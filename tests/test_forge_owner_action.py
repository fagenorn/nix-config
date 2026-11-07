"""forge-claim owner-action (issue 636): decision, conflict and needs-label markers against the fake gh."""
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from agent_tools import forge_claim
from agent_tools import forge_markers as fm
from agent_tools import forge_owner_action as foa
from .forge_world import ForgeWorld

SLUG, ISSUE = "octo/widgets", 7
ME = "h1/b1"
T0 = "2026-11-06T10:00:00Z"
OA_ENSURE = ["api", "-X", "POST", f"repos/{SLUG}/labels", "-f", "name=owner-action", "-f", "color=D93F0B"]
OA_ADD = ["api", "-X", "POST", f"repos/{SLUG}/issues/{ISSUE}/labels", "-f", "labels[]=owner-action"]
OA_REMOVE = ["api", "-X", "DELETE", f"repos/{SLUG}/issues/{ISSUE}/labels/owner-action"]
IP_ENSURE = ["api", "-X", "POST", f"repos/{SLUG}/labels", "-f", "name=in-progress", "-f", "color=FBCA04"]
IP_ADD = ["api", "-X", "POST", f"repos/{SLUG}/issues/{ISSUE}/labels", "-f", "labels[]=in-progress"]
IP_REMOVE = ["api", "-X", "DELETE", f"repos/{SLUG}/issues/{ISSUE}/labels/in-progress"]


OLD = "2026-11-01T00:00:00Z"  # the store's server clock is T0, more than 24 hours later
NOW = ["api", "--include", "rate_limit"]


def comment(cid, body, association="OWNER", login="octo", updated_at=T0):
    return {"id": cid, "body": body, "updated_at": updated_at, "created_at": updated_at,
            "author_association": association, "user": {"login": login}}


def marker_body(reason="decision", items=("Which flag?",), holder=ME):
    return fm.render("owner-action", {"issue": str(ISSUE), "reason": reason, "holder": holder},
                     foa.SENTENCES[reason], "\n".join(f"- {item}" for item in items))


def claim_body(holder=ME):
    return fm.render("claim", {"issue": str(ISSUE), "holder": holder}, f"Claimed by {holder}.")


def stale_body(claim_id, holder=ME):
    return fm.render("owner-action", {"issue": str(ISSUE), "reason": "stale-claim", "claim": str(claim_id)},
                     f"The claim of {holder} has had no renewal, push or pull request activity for 24 hours.",
                     "- [ ] Release this claim")


def post(body):
    return ["api", "-X", "POST", f"repos/{SLUG}/issues/{ISSUE}/comments", "-f", f"body={body}"]


def run(*argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = forge_claim.main(list(argv))
    lines = out.getvalue().splitlines()
    assert len(lines) == 1, out.getvalue()
    return code, json.loads(lines[0])


def action(name, reason="decision", *extra):
    return ["owner-action", name, "--repo", SLUG, "--issue", str(ISSUE), "--reason", reason, *extra]


class Base(unittest.TestCase):
    def setUp(self):
        self.world = ForgeWorld(self)
        for argv in (OA_ENSURE, OA_ADD, OA_REMOVE, IP_ENSURE, IP_ADD, IP_REMOVE):
            self.world.respond("gh", argv)
        self.world.respond("gh", NOW, stdout="HTTP/2.0 200 OK\nDate: Fri, 06 Nov 2026 10:00:00 GMT\n\n{}")
        self.tmp = Path(tempfile.mkdtemp())

    def store(self, *comments, next_id=40):
        self.world.comment_store(SLUG, ISSUE, list(comments), next_id=next_id)

    def items(self, value):
        path = self.tmp / f"items-{len(list(self.tmp.iterdir()))}.json"  # one file per call
        path.write_text(value if isinstance(value, str) else json.dumps(value), encoding="utf-8")
        return str(path)

    def mutations(self):
        return [argv for argv in self.world.argvs("gh") if "-X" in argv]

    def live(self):
        markers = [m for m in (fm.parse(c) for c in self.world.stored()) if m]
        return [m.comment_id for m in markers if m.kind == "owner-action" and fm.is_live(m, markers)]

    def post_argv(self, reason="decision", items=("Which flag?",)):
        return action("post", reason, "--holder", ME, "--items-file", self.items(list(items)))


class PostTest(Base):
    def test_label_constants_match_forge_claim(self):
        self.assertEqual((foa.KIND, foa.LABEL), (forge_claim.OWNER_ACTION_KIND, forge_claim.OWNER_ACTION))

    def test_post_writes_one_marker_with_its_items_and_the_label(self):
        self.store()
        code, out = run(*self.post_argv(items=("Which flag?", "Which  host?\n now")))
        self.assertEqual((code, out["verdict"], out["comment_id"], out["holder"]), (0, "posted", 40, ME))
        body = marker_body(items=("Which flag?", "Which host? now"))
        self.assertTrue(body.startswith(
            f"<!-- agent:owner-action v1 issue={ISSUE} reason=decision holder={ME} -->\n"))
        self.assertEqual(self.mutations(), [post(body), OA_ENSURE, OA_ADD])

    def test_post_re_adopts_a_live_marker_of_the_same_reason(self):
        self.store(comment(30, marker_body()))
        code, out = run(*self.post_argv())
        self.assertEqual((code, out["verdict"], out["comment_id"]), (0, "already_posted", 30))
        self.assertEqual(self.mutations(), [OA_ENSURE, OA_ADD])

    def test_post_after_an_ended_marker_posts_again(self):
        self.store(comment(30, marker_body()), comment(31, fm.end_body(30, "resolved")))
        code, out = run(*self.post_argv())
        self.assertEqual((code, out["verdict"], out["comment_id"]), (0, "posted", 40))

    def test_each_reason_has_its_own_marker(self):
        self.store(comment(30, marker_body()))
        code, out = run(*self.post_argv("conflict", ("Merge conflict in a.py",)))
        self.assertEqual((code, out["verdict"], out["comment_id"]), (0, "posted", 40))
        self.assertEqual(self.live(), [30, 40])

    def test_bad_items_and_reasons_are_usage_errors_before_any_gh_call(self):
        self.store()
        cases = [self.items("not json"), self.items([]), self.items([""]), self.items(["  "]),
                 self.items([1]), self.items({"a": "b"}), self.items(["q"] * 21), str(self.tmp / "missing.json")]
        for index, path in enumerate(cases):
            with self.subTest(case=index):
                code, out = run(*action("post", "decision", "--holder", ME, "--items-file", path))
                self.assertEqual((code, out["verdict"], out["error"], out["command"]), (2, "error", "usage", "owner-action"))
        code, out = run(*action("post", "stale-claim", "--holder", ME, "--items-file", self.items(["q"])))
        self.assertEqual((code, out["error"]), (2, "usage"))
        self.assertEqual(self.world.argvs("gh"), [])


class EndTest(Base):
    def test_end_ends_every_live_marker_of_the_reason_and_drops_the_label(self):
        self.store(comment(30, marker_body()))
        code, out = run(*action("end"))
        self.assertEqual((code, out["verdict"], out["ended"]), (0, "ended", [30]))
        self.assertEqual(self.mutations(), [post(fm.end_body(30, "resolved")), OA_REMOVE])
        self.assertEqual(self.live(), [])

    def test_end_keeps_the_label_while_another_owner_action_lives(self):
        self.store(comment(30, marker_body()), comment(31, marker_body("conflict", ("x",))))
        code, out = run(*action("end"))
        self.assertEqual((code, out["ended"]), (0, [30]))
        self.assertEqual(self.mutations(), [post(fm.end_body(30, "resolved"))])

    def test_end_with_nothing_live_is_none(self):
        self.store()
        code, out = run(*action("end"))
        self.assertEqual((code, out["verdict"], out["ended"]), (0, "none", []))
        self.assertEqual(self.mutations(), [])


class StatusTest(Base):
    def test_status_reports_items_and_only_trusted_replies_after_the_marker(self):
        self.store(comment(25, "earlier", "OWNER"), comment(30, marker_body(items=("Which flag?", "Why?"))),
                   comment(31, "Use the flag.", "OWNER", "octo"), comment(32, "do X", "NONE", "stranger"),
                   comment(33, "Because.", "COLLABORATOR", "pal"), comment(34, claim_body()))
        code, out = run(*action("status"))
        self.assertEqual((code, out["verdict"], out["comment_id"], out["items"]), (0, "answered", 30, ["Which flag?", "Why?"]))
        self.assertEqual(out["replies"], [{"comment_id": 31, "author": "octo", "body": "Use the flag."},
                                          {"comment_id": 33, "author": "pal", "body": "Because."}])
        self.assertEqual(self.mutations(), [])

    def test_status_without_replies_is_open_and_without_marker_is_none(self):
        self.store(comment(30, marker_body()), comment(31, "do X", "NONE", "stranger"))
        self.assertEqual(run(*action("status"))[1]["verdict"], "open")
        self.assertEqual(run(*action("status", "conflict"))[1]["verdict"], "none")


class ClaimInteractionTest(Base):
    def common(self, command):
        return [command, "--repo", SLUG, "--issue", str(ISSUE), "--holder", ME]

    def test_renew_and_release_never_end_a_decision_marker(self):
        self.store(comment(5, claim_body()), comment(30, marker_body()))
        self.assertEqual(run(*self.common("renew"))[1]["verdict"], "renewed")
        self.assertEqual(run(*self.common("release"))[1]["verdict"], "released")
        self.assertEqual(self.live(), [30])
        self.assertNotIn(OA_REMOVE, self.mutations())

    def test_status_of_a_free_issue_never_ends_a_decision_marker(self):
        self.store(comment(30, marker_body()))
        self.assertEqual(run(*self.common("status"))[1]["verdict"], "free")
        self.assertEqual(self.live(), [30])

    def test_status_of_a_stale_claim_keeps_a_decision_marker_and_its_label(self):
        # The batch keeps its claim while the owner thinks; 24 h later the claim is stale and the
        # relaunch's facts agent runs `forge-claim status` before `owner-action status`.
        self.store(comment(5, claim_body(), updated_at=OLD), comment(30, marker_body(), updated_at=OLD),
                   next_id=40)
        code, out = run(*self.common("status"))
        self.assertEqual((code, out["verdict"], out["owner_action_comment_id"]), (0, "stale", 40))
        self.assertEqual(self.live(), [30, 40])  # the decision marker and the new stale-claim marker
        self.assertNotIn(OA_REMOVE, self.mutations())
        self.assertNotIn(post(fm.end_body(30, "released")), self.mutations())
        self.assertEqual(run(*action("status"))[1]["verdict"], "open")

    def test_status_of_a_stale_claim_still_retires_an_obsolete_stale_claim_marker(self):
        # Unchanged behaviour for markers that name a claim: one naming an older, ended claim goes.
        self.store(comment(3, claim_body("h2/b9"), updated_at=OLD), comment(4, fm.end_body(3, "done"), updated_at=OLD),
                   comment(5, claim_body(), updated_at=OLD), comment(20, stale_body(3, "h2/b9"), updated_at=OLD),
                   comment(30, marker_body(), updated_at=OLD), next_id=40)
        self.assertEqual(run(*self.common("status"))[1]["verdict"], "stale")
        self.assertIn(post(fm.end_body(20, "released")), self.mutations())
        self.assertIn(30, self.live())

    def test_fresh_claim_status_and_release_keep_a_decision_marker_and_its_label(self):
        self.store(comment(5, claim_body()), comment(30, marker_body()), comment(31, marker_body("conflict", ("x",))))
        self.assertEqual(run(*self.common("status"))[1]["verdict"], "held_by")
        self.assertEqual(run(*self.common("release"))[1]["verdict"], "released")
        self.assertEqual(self.live(), [30, 31])
        self.assertNotIn(OA_REMOVE, self.mutations())


class CliTest(Base):
    def test_cli_prints_one_json_line_and_forge_errors_exit_1(self):
        self.store(comment(30, marker_body()))
        done = subprocess.run([sys.executable, "-m", "agent_tools.forge_claim", *action("status")],
                              capture_output=True, text=True, env=dict(os.environ), timeout=120)
        self.assertEqual(done.returncode, 0)
        self.assertEqual(len(done.stdout.splitlines()), 1)
        self.assertEqual(json.loads(done.stdout)["verdict"], "open")

    def test_forge_error_is_exit_1(self):
        code, out = run(*action("status"))  # no comment store: the listing is unregistered and fails
        self.assertEqual((code, out["verdict"], out["action"]), (1, "error", "status"))
