"""forge_markers (issue 623): grammar, reads and writes against the fake gh, and the race table."""
import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from agent_tools.claims import forge_markers as fm
from agent_tools.system import forge_api
from .forge_world import ForgeWorld, NETWORK_DOWN, host_clock

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
                self.assertEqual(forge_api.server_now(), datetime(2026, 11, 6, 12, tzinfo=timezone.utc))

    def test_tolerated_statuses(self):
        self.world.respond("gh", ["api", "-X", "POST", f"repos/{SLUG}/labels", "-f", "name=x",
                                  "-f", "color=FBCA04"], exit=1, stderr="gh: Validation Failed (HTTP 422)")
        self.world.not_found("gh", ["api", "-X", "DELETE", f"repos/{SLUG}/issues/{ISSUE}/labels/x"])
        forge_api.ensure_label(SLUG, "x", "FBCA04")
        forge_api.remove_label(SLUG, ISSUE, "x")
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
        self.assertEqual([i["number"] for i in forge_api.list_issues(SLUG, "follow-up", since)], list(range(1, 102)))

    def test_a_page_that_is_not_issues_is_refused(self):
        world = ForgeWorld(self)
        since = datetime(2026, 11, 6, 10, tzinfo=timezone.utc)
        world.respond_json("gh", ["api", "--paginate", "--slurp", f"repos/{SLUG}/issues?labels=x"
                                  "&state=all&since=2026-11-06T10:00:00Z&per_page=100"], [{"number": 1}])
        with self.assertRaises(forge_api.ForgeError):
            forge_api.list_issues(SLUG, "x", since)


class NoHostClockTest(unittest.TestCase):
    def test_module_reads_no_host_clock(self):
        for module in (fm, forge_api):
            with self.subTest(module=module.__name__):
                source = Path(module.__file__).read_text("utf-8")
                for spelling in ("time.time", ".now(", "utcnow", "date.today", "localtime"):
                    self.assertNotIn(spelling, source)
                self.assertIn("from datetime import datetime", source)


class TransportSeamTest(unittest.TestCase):
    def test_the_transport_lives_in_forge_api(self):
        for name in ("is_transport", "run_gh", "gh_json", "logged_in", "api_get", "api_pages",
                     "server_now", "ensure_label", "add_label", "remove_label", "graphql",
                     "create_issue", "add_blocked_by", "list_issues", "open_issues", "close_issue",
                     "TIMEOUT"):
            with self.subTest(name=name):
                self.assertTrue(hasattr(forge_api, name))
                self.assertFalse(hasattr(fm, name))
        for name in ("_gh", "_json", "subprocess"):
            with self.subTest(name=name):
                self.assertFalse(hasattr(fm, name))

    def test_forge_markers_raises_the_transport_error(self):
        self.assertIs(fm.ForgeError, forge_api.ForgeError)


REF = "refs/agent-locks/land/main"
# Distinct names: the module-level `A` and `B` are the race table's holders (`SCHEDULES` captured
# them at import, `race` reads them at run time); rebinding them here would break RaceTest.
OID_A, OID_B = "a" * 40, "b" * 40
NODE = "R_kgDOtest"


def cas_code(*args):
    """The code of `cas_ref`'s failure, None when applied (issue 740: it returns the ForgeError)."""
    failure = fm.cas_ref(*args)
    return None if failure is None else failure.code


class RefTest(unittest.TestCase):
    def setUp(self):
        self.world = ForgeWorld(self)

    def test_read_ref_present_and_absent(self):
        self.world.ref_store(SLUG, {REF: OID_A})
        self.assertEqual(fm.read_ref(SLUG, REF), OID_A)
        self.assertIsNone(fm.read_ref(SLUG, "refs/agent-locks/land/dev"))
        self.assertEqual(self.world.argvs("gh")[0], ["api", f"repos/{SLUG}/git/ref/agent-locks/land/main"])

    def test_create_ref_once_then_422(self):
        self.world.ref_store(SLUG)
        self.assertTrue(fm.create_ref(SLUG, REF, OID_A))
        self.assertFalse(fm.create_ref(SLUG, REF, OID_B))
        self.assertEqual(self.world.refs(), {REF: OID_A})
        self.assertEqual(self.world.argvs("gh")[0],
                         ["api", "-X", "POST", f"repos/{SLUG}/git/refs", "-f", f"ref={REF}", "-f", f"sha={OID_A}"])

    def test_node_id(self):
        self.world.ref_store(SLUG)
        self.assertEqual(fm.repo_node_id(SLUG), NODE)

    def test_cas_moves_only_from_the_observed_oid(self):
        self.world.ref_store(SLUG, {REF: OID_A})
        self.assertEqual(cas_code(SLUG, NODE, REF, OID_B, OID_B), "gh_failed")
        self.assertEqual(self.world.refs(), {REF: OID_A})
        self.assertIsNone(cas_code(SLUG, NODE, REF, OID_A, OID_B))
        self.assertEqual(self.world.refs(), {REF: OID_B})
        self.assertEqual(self.world.argvs("gh")[-1],
                         ["api", "graphql", "-f", f"query={fm.UPDATE_REFS}", "-f", f"repositoryId={NODE}",
                          "-f", f"name={REF}", "-f", f"before={OID_A}", "-f", f"after={OID_B}"])
        self.assertIn("force: true", fm.UPDATE_REFS)

    def test_cas_delete_only_from_the_observed_oid(self):
        self.world.ref_store(SLUG, {REF: OID_A})
        self.assertEqual(cas_code(SLUG, NODE, REF, OID_B, fm.ZERO_OID), "gh_failed")
        self.assertEqual(self.world.refs(), {REF: OID_A})
        self.assertIsNone(cas_code(SLUG, NODE, REF, OID_A, fm.ZERO_OID))
        self.assertEqual(self.world.refs(), {})
        self.assertEqual(cas_code(SLUG, NODE, REF, OID_A, fm.ZERO_OID), "gh_failed")

    def test_a_lying_cas_reports_failure_but_applied(self):
        self.world.ref_store(SLUG, {REF: OID_A}, cas_lies=1)
        self.assertEqual(cas_code(SLUG, NODE, REF, OID_A, OID_B), "gh_failed")
        self.assertEqual(fm.read_ref(SLUG, REF), OID_B)

    def test_cas_keeps_the_failure_code(self):
        for code in ("gh_failed", "gh_timeout"):
            with self.subTest(code=code), \
                    mock.patch.object(forge_api, "run_gh", side_effect=fm.ForgeError(code, "x")):
                self.assertEqual(cas_code(SLUG, NODE, REF, OID_A, OID_B), code)
        for code, transient in (("gh_failed", False), ("gh_timeout", True)):
            with self.subTest(code=code), \
                    mock.patch.object(forge_api, "run_gh", side_effect=fm.ForgeError(code, "x")):
                self.assertEqual(fm.cas_ref(SLUG, NODE, REF, OID_A, OID_B).transient, transient)
        with mock.patch.object(forge_api, "run_gh", side_effect=fm.ForgeError("gh_missing", "x")), \
                self.assertRaises(fm.ForgeError) as caught:
            fm.cas_ref(SLUG, NODE, REF, OID_A, OID_B)
        self.assertEqual(caught.exception.code, "gh_missing")

    def test_cas_answering_errors_with_exit_zero_is_not_applied(self):
        for payload in ({"data": {"updateRefs": {"clientMutationId": None}}, "errors": [{"message": "x"}]},
                        {"data": {"updateRefs": None}}):
            with self.subTest(payload=payload), \
                    mock.patch.object(forge_api, "run_gh", return_value=(0, json.dumps(payload))):
                self.assertEqual(cas_code(SLUG, NODE, REF, OID_A, OID_B), "gh_failed")
                self.assertFalse(fm.cas_ref(SLUG, NODE, REF, OID_A, OID_B).transient)

    def test_node_id_outside_the_grammar_is_invalid(self):
        with mock.patch.object(forge_api, "run_gh", return_value=(0, "not a node id\n")), \
                self.assertRaises(fm.ForgeError) as caught:
            fm.repo_node_id(SLUG)
        self.assertEqual(caught.exception.code, "payload_invalid")

    def test_ref_store_default_is_not_shared(self):
        self.world.ref_store(SLUG)
        fm.create_ref(SLUG, REF, OID_A)
        self.world.reset()
        self.world.ref_store(SLUG)
        self.assertEqual(self.world.refs(), {})

    def test_no_ref_delete_through_rest(self):
        self.world.ref_store(SLUG, {REF: OID_A})
        fm.cas_ref(SLUG, NODE, REF, OID_A, fm.ZERO_OID)
        self.assertFalse([a for a in self.world.argvs("gh") if "DELETE" in a and any("git/refs" in p for p in a)])

    def test_commit_pulls(self):
        self.world.respond_json("gh", ["api", f"repos/{SLUG}/commits/{OID_A}/pulls?per_page=100"], [
            {"number": 12, "state": "closed", "merged_at": "2026-11-01T00:00:00Z",
             "base": {"ref": "main"}, "head": {"ref": "issue-7-x", "sha": OID_A}},
            {"number": 13, "state": "open", "merged_at": None,
             "base": {"ref": "dev"}, "head": {"ref": "issue-8-y", "sha": OID_B}}])
        self.assertEqual(fm.commit_pulls(SLUG, OID_A), [
            fm.Pull(12, "closed", True, "main", "issue-7-x", OID_A), fm.Pull(13, "open", False, "dev", "issue-8-y", OID_B)])

    def test_commit_pulls_rejects_a_bad_payload(self):
        self.world.respond_json("gh", ["api", f"repos/{SLUG}/commits/{OID_A}/pulls?per_page=100"], {"number": 1})
        with self.assertRaises(fm.ForgeError) as caught:
            fm.commit_pulls(SLUG, OID_A)
        self.assertEqual(caught.exception.code, "payload_invalid")

    def closed_page(self, page, items):
        self.world.respond_json("gh", ["api", f"repos/{SLUG}/pulls?state=closed&base=main&sort=updated"
                                       f"&direction=desc&per_page=100&page={page}"], items)

    @staticmethod
    def closed_item(number, sha):
        return {"number": number, "state": "closed", "merged_at": None,
                "base": {"ref": "main"}, "head": {"ref": f"issue-{number}-x", "sha": sha}}

    def test_closed_pulls_headed_filters_by_head_sha(self):
        self.closed_page(1, [self.closed_item(12, OID_B), self.closed_item(13, OID_A)])
        self.assertEqual(fm.closed_pulls_headed(SLUG, "main", OID_B),
                         [fm.Pull(12, "closed", False, "main", "issue-12-x", OID_B)])

    def test_closed_pulls_headed_pages_until_a_short_page_or_the_bound(self):
        full = [self.closed_item(n, OID_B) for n in range(100, 200)]
        self.closed_page(1, full)
        self.closed_page(2, [self.closed_item(5, OID_A)])
        self.assertEqual(len(fm.closed_pulls_headed(SLUG, "main", OID_A)), 1)
        for page in range(1, fm.CLOSED_PAGES + 2):
            self.closed_page(page, full)
        self.assertEqual(len(fm.closed_pulls_headed(SLUG, "main", OID_B)), 100 * fm.CLOSED_PAGES)
        pages = [a[1] for a in self.world.argvs("gh") if "state=closed" in a[1]]
        self.assertEqual(len(pages) - 2, fm.CLOSED_PAGES)

    def test_closed_pulls_headed_rejects_a_bad_payload(self):
        self.closed_page(1, {"number": 1})
        with self.assertRaises(fm.ForgeError) as caught:
            fm.closed_pulls_headed(SLUG, "main", OID_A)
        self.assertEqual(caught.exception.code, "payload_invalid")

    def test_closing_issues(self):
        owner, name = SLUG.split("/")
        self.world.respond_json("gh", ["api", "graphql", "-f", f"query={fm.CLOSING_ISSUES}", "-f", f"owner={owner}",
                                       "-f", f"name={name}", "-F", "number=12"],
                                {"data": {"repository": {"pullRequest": {"closingIssuesReferences": {
                                    "nodes": [{"number": 7}, {"number": 9}]}}}}})
        self.assertEqual(fm.closing_issues(SLUG, 12), [7, 9])


if __name__ == "__main__":
    unittest.main()


class TransportTest(unittest.TestCase):
    """Issue 740 D2: `_gh` marks a transport failure transient; the fake gh's outage and lost replies."""

    def setUp(self):
        self.world = ForgeWorld(self)

    def raised(self, call):
        with self.assertRaises(forge_api.ForgeError) as caught:
            call()
        return caught.exception

    def test_transport_failures_are_transient(self):
        for stderr in (NETWORK_DOWN, "error connecting to api.github.com\ncheck your internet connection",
                       "gh: Server Error (HTTP 500)", "gh: Bad Gateway (HTTP 502)",
                       'Get "https://api.github.com/": net/http: TLS handshake timeout',
                       "read tcp 10.0.0.2:5000->20.250.119.72:443: read: connection reset by peer",
                       "x" * 300 + " dial tcp: lookup api.github.com: no such host"):
            with self.subTest(stderr=stderr[:40]):
                self.world.respond("gh", LIST, exit=1, stderr=stderr)
                error = self.raised(lambda: fm.list_markers(SLUG, ISSUE))
                self.assertEqual((error.code, error.transient), ("gh_failed", True))

    def test_other_failures_are_not_transient(self):
        for stderr in ("gh: Forbidden (HTTP 403)", "gh: Not Found (HTTP 404)",
                       "gh: Validation Failed (HTTP 422)", "HTTP 401: Bad credentials"):
            with self.subTest(stderr=stderr):
                self.world.respond("gh", LIST, exit=1, stderr=stderr)
                error = self.raised(lambda: fm.list_markers(SLUG, ISSUE))
                self.assertEqual((error.code, error.transient), ("gh_failed", False))
        error = self.raised(lambda: fm.read_ref(SLUG, "refs/heads/x"))  # unregistered: the fake exits 64
        self.assertEqual((error.code, error.transient), ("gh_failed", False))

    def test_a_timeout_is_transient(self):
        with mock.patch.object(forge_api.subprocess, "run",
                               side_effect=forge_api.subprocess.TimeoutExpired("gh", forge_api.TIMEOUT)):
            error = self.raised(lambda: fm.list_markers(SLUG, ISSUE))
        self.assertEqual((error.code, error.transient), ("gh_timeout", True))

    def test_constructed_errors_default_by_code(self):
        self.assertTrue(forge_api.ForgeError("gh_timeout", "x").transient)
        for code in ("gh_failed", "gh_missing", "payload_invalid"):
            with self.subTest(code=code):
                self.assertFalse(forge_api.ForgeError(code, "x").transient)
        self.assertTrue(forge_api.ForgeError("gh_failed", "x", transient=True).transient)
        self.assertFalse(forge_api.ForgeError("gh_timeout", "x", transient=False).transient)

    def test_an_outage_fails_the_next_calls_and_changes_nothing(self):
        self.world.comment_store(SLUG, ISSUE, [comment(5, claim_body(A))])
        self.world.outage(2)
        for _ in range(2):
            self.assertTrue(self.raised(lambda: fm.post(SLUG, ISSUE, "hello")).transient)
        self.assertEqual([c["id"] for c in self.world.stored()], [5])
        self.assertEqual([m.comment_id for m in fm.list_markers(SLUG, ISSUE)], [5])
        self.world.outage()
        for _ in range(3):
            self.assertTrue(self.raised(lambda: fm.list_markers(SLUG, ISSUE)).transient)
        self.world.outage(0)
        self.assertEqual([m.comment_id for m in fm.list_markers(SLUG, ISSUE)], [5])

    def test_reset_forgets_the_outage(self):
        self.world.outage()
        self.world.reset()
        self.world.comment_store(SLUG, ISSUE, [comment(5, claim_body(A))])
        self.assertEqual([m.comment_id for m in fm.list_markers(SLUG, ISSUE)], [5])

    def test_a_lost_reply_applies_then_fails_transient_once(self):
        self.world.comment_store(SLUG, ISSUE, [], next_id=40, lose_reply=["post"])
        self.assertTrue(self.raised(lambda: fm.post(SLUG, ISSUE, "hello")).transient)
        self.assertEqual([c["id"] for c in self.world.stored()], [40])
        self.assertEqual(fm.post(SLUG, ISSUE, "again"), 41)  # the entry was consumed
        ref = "refs/agent-locks/land/main"
        self.world.ref_store(SLUG, {}, lose_reply=["create", "get"])
        self.assertTrue(self.raised(lambda: fm.create_ref(SLUG, ref, "a" * 40)).transient)
        self.assertEqual(self.world.refs(), {ref: "a" * 40})
        self.assertTrue(self.raised(lambda: fm.read_ref(SLUG, ref)).transient)
        self.assertEqual(fm.read_ref(SLUG, ref), "a" * 40)

    def test_a_cas_transport_failure_is_returned_with_its_class(self):
        self.world.ref_store(SLUG, {REF: OID_A})
        bad_gateway = forge_api.subprocess.CompletedProcess(["gh"], 1, stdout="", stderr="gh: Bad Gateway (HTTP 502)\n")
        with mock.patch.object(forge_api.subprocess, "run", return_value=bad_gateway):
            failure = fm.cas_ref(SLUG, NODE, REF, OID_A, OID_B)
        self.assertIsInstance(failure, forge_api.ForgeError)
        self.assertEqual((failure.code, failure.transient), ("gh_failed", True))
        self.assertEqual(self.world.refs(), {REF: OID_A})
        failure = fm.cas_ref(SLUG, NODE, REF, OID_B, OID_B)  # the fake's GraphQL error answer: not a transport error
        self.assertEqual((failure.code, failure.transient), ("gh_failed", False))
