"""forge_markers (issue 623): grammar, reads and writes against the fake gh, and the race table."""
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from agent_tools import forge_markers as fm
from .forge_world import ForgeWorld, host_clock

SLUG, ISSUE = "octo/widgets", 7
LIST = ["api", "--paginate", "--slurp", f"repos/{SLUG}/issues/{ISSUE}/comments?per_page=100"]
T0 = "2026-11-06T10:00:00Z"
A, B = "mbp/session-a", "eleven-m5/session-b"
MATCH = {"issue": str(ISSUE)}


def comment(cid, body, updated_at=T0):
    return {"id": cid, "body": body, "updated_at": updated_at, "created_at": updated_at}


def claim_body(holder, **extra):
    return fm.render("claim", {"issue": str(ISSUE), "holder": holder, **extra}, f"Claimed by {holder}.")


class GrammarTest(unittest.TestCase):
    def test_render_then_parse_round_trips(self):
        body = fm.render("claim", {"issue": "7", "holder": "mbp/session-a"}, "Claimed.", "- [ ] x")
        self.assertEqual(body, "<!-- agent:claim v1 issue=7 holder=mbp/session-a -->\nClaimed.\n- [ ] x")
        marker = fm.parse(comment(5, body))
        self.assertEqual((marker.comment_id, marker.kind, marker.fields),
                         (5, "claim", {"issue": "7", "holder": "mbp/session-a"}))
        self.assertEqual(marker.updated_at, datetime(2026, 11, 6, 10, tzinfo=timezone.utc))

    def test_non_markers_parse_to_none(self):
        for body in ("plain text", "<!-- agent:claim v2 issue=7 -->\nx",
                     "<!-- agent:claim v1 issue=7 issue=8 -->\nx", "<!-- agent:Claim v1 -->\nx",
                     "x\n<!-- agent:claim v1 issue=7 -->", None):
            with self.subTest(body=body):
                self.assertIsNone(fm.parse(comment(1, body)))

    def test_render_refuses_bad_values(self):
        for kind, fields, sentence in (("claim", {"holder": "a b"}, "x"), ("claim", {"Bad": "1"}, "x"),
                                       ("claim", {"k": "v-->"}, "x"), ("claim", {}, "two\nlines"),
                                       ("claim", {}, ""), ("Claim", {}, "x")):
            with self.subTest(fields=fields, sentence=sentence), self.assertRaises(ValueError):
                fm.render(kind, fields, sentence)

    def test_with_fields_keeps_order_and_appends(self):
        marker = fm.parse(comment(1, claim_body("mbp/s") + "\nrest"))
        self.assertEqual(fm.with_fields(marker, holder="m5/t", renewed="1"),
                         "<!-- agent:claim v1 issue=7 holder=m5/t renewed=1 -->\nClaimed by mbp/s.\nrest")

    def test_end_markers_and_released_fields_end_claims(self):
        self.assertEqual(fm.end_body(1, "done"),
                         "<!-- agent:end v1 of=1 reason=done -->\nEnds marker comment 1 (done).")
        markers = [fm.parse(comment(cid, body)) for cid, body in (
            (1, claim_body("b/y")), (2, claim_body("c/z")), (3, claim_body("a/x")),
            (4, fm.end_body(1, "done")), (5, claim_body("d/w", released="done")))]
        self.assertEqual(fm.ended(markers), {1})
        self.assertEqual([fm.is_live(m, markers) for m in markers], [False, True, True, False, False])
        self.assertEqual([m.comment_id for m in fm.contest(markers, "claim", MATCH)], [2, 3])
        self.assertEqual(fm.contest(markers, "claim", {"issue": "8"}), [])


class ReadWriteTest(unittest.TestCase):
    def setUp(self):
        self.world = ForgeWorld(self)

    def test_list_flattens_pages_and_drops_non_markers(self):
        self.world.respond_json("gh", LIST, [[comment(4, claim_body("b/y")), comment(1, "hello")],
                                             [comment(2, claim_body("a/x"))]])
        self.assertEqual([m.comment_id for m in fm.list_markers(SLUG, ISSUE)], [2, 4])

    def test_server_now_reads_the_date_header_not_the_host_clock(self):
        self.world.respond("gh", ["api", "--include", "rate_limit"],
                           stdout="HTTP/2.0 200 OK\ndate: Fri, 06 Nov 2026 12:00:00 GMT\n\n{}")
        for instant in (datetime(1970, 1, 1, tzinfo=timezone.utc), datetime(2100, 1, 1, tzinfo=timezone.utc)):
            with self.subTest(instant=instant), host_clock(instant, fm):
                self.assertEqual(fm.datetime.now(timezone.utc), instant)  # the seam reaches the module
                self.assertEqual(fm.server_now(), datetime(2026, 11, 6, 12, tzinfo=timezone.utc))

    def test_tolerated_statuses(self):
        self.world.respond("gh", ["api", "-X", "POST", f"repos/{SLUG}/labels", "-f", "name=x",
                                  "-f", "color=FBCA04"], exit=1, stderr="gh: Validation Failed (HTTP 422)")
        self.world.not_found("gh", ["api", "-X", "DELETE", f"repos/{SLUG}/issues/{ISSUE}/labels/x"])
        fm.ensure_label(SLUG, "x", "FBCA04")
        fm.remove_label(SLUG, ISSUE, "x")
        self.world.respond("gh", LIST, exit=1, stderr="gh: Server Error (HTTP 500)")
        with self.assertRaises(fm.ForgeError) as raised:
            fm.list_markers(SLUG, ISSUE)
        self.assertEqual(raised.exception.code, "gh_failed")

    def test_branch_activity(self):
        self.world.respond_json("gh", ["api", f"repos/{SLUG}/activity?ref=refs/heads/topic"
                                       "&activity_type=push&per_page=1"], [{"timestamp": T0}])
        self.world.respond_json("gh", ["api", f"repos/{SLUG}/pulls?state=all&head=octo:topic&per_page=100"],
                                [{"updated_at": "2026-11-05T00:00:00Z"}, {"updated_at": T0}])
        t0 = datetime(2026, 11, 6, 10, tzinfo=timezone.utc)
        self.assertEqual((fm.latest_push(SLUG, "topic"), fm.latest_pr_event(SLUG, "topic")), (t0, t0))

    def test_token_never_reaches_gh(self):
        self.world.respond_json("gh", LIST, [[]])
        fm.list_markers(SLUG, ISSUE)
        self.assertFalse(any(call["token_visible"] for call in self.world.calls()))

    def test_a_later_edit_cannot_revive_an_ended_marker(self):
        self.world.comment_store(SLUG, ISSUE, [comment(5, claim_body(A, released="done"))], next_id=9)
        self.assertEqual(fm.end(SLUG, ISSUE, 5, "done"), 9)
        fm.edit(SLUG, 5, claim_body(A, renewed="1"))  # a stale rewrite drops `released`
        markers = fm.list_markers(SLUG, ISSUE)
        self.assertEqual([m.comment_id for m in markers], [5, 9])
        self.assertFalse(fm.is_live(markers[0], markers))
        self.assertEqual(fm.contest(markers, "claim", MATCH), [])


def live_claims(world):
    markers = [m for m in (fm.parse(c) for c in world.stored()) if m]
    return fm.contest(markers, "claim", MATCH)


def write_claim(holder):
    return fm.write(SLUG, ISSUE, "claim", {"issue": str(ISSUE), "holder": holder},
                    f"Claimed by {holder}.", MATCH)


def post_of(holder):
    return f"post:holder={holder}"


def race(writer):
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = {holder: pool.submit(writer, holder) for holder in (A, B)}
    return {holder: future.result() for holder, future in futures.items()}


# Each row forces one interleaving of the two writers' post and re-read on the shared store; the
# server assigns ids in post order, so the first poster wins. A writer that lists before it posts
# never reaches its first scheduled entry and fails with the fake's exit 66.
SCHEDULES = [
    ("A post, A read, B post, B read", [post_of(A), "list", post_of(B), "list"], A),
    ("A post, B post, both read", [post_of(A), post_of(B), "list", "list"], A),
    ("B post, A post, both read", [post_of(B), post_of(A), "list", "list"], B),
    ("B post, B read, A post, A read", [post_of(B), "list", post_of(A), "list"], B),
]


class RaceTest(unittest.TestCase):
    def test_two_writers_converge_to_one_live_claim(self):
        for name, schedule, winner in SCHEDULES:
            with self.subTest(name):
                world = ForgeWorld(self)
                world.comment_store(SLUG, ISSUE, next_id=101, schedule=schedule)
                results = race(write_claim)
                loser = B if winner == A else A
                self.assertTrue(results[winner].won)
                self.assertFalse(results[loser].won)
                self.assertEqual(results[loser].winner.comment_id, results[winner].own_id)
                self.assertEqual(results[loser].winner.fields["holder"], winner)
                self.assertEqual([m.fields["holder"] for m in live_claims(world)], [winner])
                self.assertNotIn(results[loser].own_id, [c["id"] for c in world.stored()])
                comment_posts = [a for a in world.argvs("gh")
                                 if a[:4] == ["api", "-X", "POST", f"repos/{SLUG}/issues/{ISSUE}/comments"]]
                self.assertEqual(len(comment_posts), 2)
                self.assertEqual([a for a in world.argvs("gh") if "DELETE" in a],
                                 [["api", "-X", "DELETE", f"repos/{SLUG}/issues/comments/{results[loser].own_id}"]])

    def test_the_table_catches_a_writer_that_reads_before_posting(self):
        def check_then_post(holder):
            if not fm.contest(fm.list_markers(SLUG, ISSUE), "claim", MATCH):
                fm.post(SLUG, ISSUE, claim_body(holder))

        world = ForgeWorld(self)
        world.comment_store(SLUG, ISSUE, next_id=101, schedule=["list", "list", post_of(A), post_of(B)])
        race(check_then_post)
        self.assertEqual(len(live_claims(world)), 2)  # the final-state check above would reject it

    def test_an_ended_claim_does_not_win(self):
        world = ForgeWorld(self)
        world.comment_store(SLUG, ISSUE, [comment(90, claim_body(B)), comment(91, fm.end_body(90, "done"))],
                            next_id=101)
        result = write_claim(A)
        self.assertEqual((result.won, result.own_id), (True, 101))
        self.assertFalse(any("DELETE" in argv for argv in world.argvs("gh")))


TRUSTED = ("OWNER", "MEMBER")


def by(association, cid, body):
    return {**comment(cid, body), "author_association": association}


class TrustedContestTest(unittest.TestCase):
    def setUp(self):
        self.world = ForgeWorld(self)

    def test_untrusted_markers_never_win_or_end_a_contest(self):
        self.world.comment_store(SLUG, ISSUE, [by("NONE", 1, claim_body("x/forged")),
                                               by("OWNER", 2, claim_body(B)),
                                               by("NONE", 3, fm.end_body(2, "forged"))])
        self.assertEqual([m.comment_id for m in fm.list_markers(SLUG, ISSUE, TRUSTED)], [2])
        result = fm.write(SLUG, ISSUE, "claim", {"issue": str(ISSUE), "holder": A}, f"Claimed by {A}.", MATCH,
                          associations=TRUSTED)
        self.assertEqual((result.won, result.winner.comment_id), (False, 2))

    def test_the_own_comment_counts_whatever_its_association(self):
        self.world.comment_store(SLUG, ISSUE, [by("NONE", 1, claim_body("x/forged"))])
        result = fm.write(SLUG, ISSUE, "claim", {"issue": str(ISSUE), "holder": A}, f"Claimed by {A}.", MATCH,
                          associations=TRUSTED)
        self.assertTrue(result.won)
        self.assertEqual([c["id"] for c in self.world.stored()], [1, result.own_id])

    def test_no_associations_keeps_the_issue_623_reading(self):
        self.world.comment_store(SLUG, ISSUE, [by("NONE", 1, claim_body("x/forged"))])
        self.assertEqual([m.comment_id for m in fm.list_markers(SLUG, ISSUE)], [1])
        result = fm.write(SLUG, ISSUE, "claim", {"issue": str(ISSUE), "holder": A}, f"Claimed by {A}.", MATCH)
        self.assertEqual((result.won, result.winner.comment_id), (False, 1))


class ListIssuesTest(unittest.TestCase):
    def test_every_page_of_the_labelled_issues_is_read(self):
        world = ForgeWorld(self)
        since = datetime(2026, 11, 6, 10, tzinfo=timezone.utc)
        world.respond_json("gh", ["api", "--paginate", "--slurp", f"repos/{SLUG}/issues?labels=follow-up"
                                  "&state=all&since=2026-11-06T10:00:00Z&per_page=100"],
                           [[{"number": n} for n in range(1, 101)], [{"number": 101}]])
        self.assertEqual([i["number"] for i in fm.list_issues(SLUG, "follow-up", since)], list(range(1, 102)))

    def test_a_page_that_is_not_issues_is_refused(self):
        world = ForgeWorld(self)
        since = datetime(2026, 11, 6, 10, tzinfo=timezone.utc)
        world.respond_json("gh", ["api", "--paginate", "--slurp", f"repos/{SLUG}/issues?labels=x"
                                  "&state=all&since=2026-11-06T10:00:00Z&per_page=100"], [{"number": 1}])
        with self.assertRaises(fm.ForgeError):
            fm.list_issues(SLUG, "x", since)


class NoHostClockTest(unittest.TestCase):
    def test_module_reads_no_host_clock(self):
        source = Path(fm.__file__).read_text("utf-8")
        for spelling in ("time.time", ".now(", "utcnow", "date.today", "localtime"):
            self.assertNotIn(spelling, source)
        self.assertIn("from datetime import datetime", source)


if __name__ == "__main__":
    unittest.main()
