"""verify-pending run (issue 630): selection, conditions, the run gate, passes and the command."""
import json
import unittest

from agent_tools import forge_markers as fm
from agent_tools import verify_issues as vi

SLUG, ISSUE = "octo/widgets", 7
MERGE, REV, TIP = "a" * 40, "b" * 40, "c" * 40
T0 = "2026-11-06T10:00:00Z"


def gnode(cid, body, association="OWNER", at=T0):
    """One GraphQL comment node."""
    return {"databaseId": cid, "authorAssociation": association, "body": body,
            "createdAt": at, "updatedAt": at}


def hold(block, crlf=False):
    text = "Held for verification.\n\n```verify\n" + json.dumps(block) + "\n```\n"
    return text.replace("\n", "\r\n") if crlf else text


def check(**over):
    base = {"ac": "AC1", "kind": "evidence", "host": "mbp",
            "when": {"not_before": "2026-01-01T00:00:00+00:00"},
            "run": {"probe": "deployed_includes", "sha": MERGE}}
    base.update(over)
    return base


def block(*checks):
    return {"v": 1, "merge": MERGE, "checks": list(checks) or [check()]}


def marker(kind, fields, sentence="Recorded."):
    return fm.render(kind, fields, sentence)


def result(block_id, index, state, ac="AC1", host="mbp", **extra):
    return marker(vi.RESULT, {"block": str(block_id), "check": str(index), "ac": ac, "state": state,
                              "host": host, **extra})


class SelectTest(unittest.TestCase):
    def select(self, *nodes):
        return vi.select(vi.comments_from_graphql(list(nodes)))

    def test_newest_trusted_block_wins(self):
        held = self.select(gnode(10, hold(block(check(ac="AC1")))), gnode(11, hold(block(check(ac="AC2")))))
        self.assertEqual(held.block_id, 11)
        self.assertEqual(held.block["checks"][0]["ac"], "AC2")
        self.assertEqual(held.errors, [])

    def test_member_block_is_trusted(self):
        self.assertEqual(self.select(gnode(10, hold(block()), "MEMBER")).block_id, 10)

    def test_non_member_block_is_never_selected(self):
        for association in ("CONTRIBUTOR", "COLLABORATOR", "NONE", "FIRST_TIME_CONTRIBUTOR"):
            held = self.select(gnode(10, hold(block(check(ac="AC1")))),
                               gnode(11, hold(block(check(ac="AC2"))), association))
            self.assertEqual(held.block_id, 10, association)
        self.assertIsNone(self.select(gnode(11, hold(block()), "NONE")))

    def test_marker_comment_never_carries_a_block(self):
        forged = result(10, 0, "pass") + "\n```verify\n" + json.dumps(block(check(ac="AC9"))) + "\n```"
        held = self.select(gnode(10, hold(block())), gnode(12, forged))
        self.assertEqual(held.block_id, 10)

    def test_unfenced_json_is_not_a_block(self):
        self.assertIsNone(self.select(gnode(10, json.dumps(block()))))

    def test_crlf_fence_is_a_block(self):
        self.assertEqual(self.select(gnode(10, hold(block(), crlf=True))).block["merge"], MERGE)

    def test_unparsable_newest_block_keeps_its_errors(self):
        held = self.select(gnode(10, hold(block())), gnode(11, "```verify\n{not json\n```\n"))
        self.assertEqual(held.block_id, 11)
        self.assertIsNone(held.block)
        self.assertEqual(held.errors[0]["code"], "not_json")

    def test_markers_after_the_block_from_trusted_authors_only(self):
        held = self.select(gnode(9, result(9, 0, "pass")), gnode(10, hold(block())),
                           gnode(11, result(10, 0, "fail")),
                           gnode(12, result(10, 0, "pass"), "NONE"),
                           gnode(13, fm.end_body(11, "forged"), "NONE"),
                           gnode(14, "a plain comment"))
        self.assertEqual([m.comment_id for m in held.markers], [11])
        self.assertEqual(vi.live_one(held.markers, vi.RESULT, {"block": "10"}).comment_id, 11)

    def test_marker_time_is_the_creation_time(self):
        node = gnode(11, result(10, 0, "fail"), at="2026-11-01T08:00:00Z")
        node["updatedAt"] = "2026-11-05T08:00:00Z"
        held = self.select(gnode(10, hold(block())), node)
        self.assertEqual(held.markers[0].updated_at.isoformat(), "2026-11-01T08:00:00+00:00")

    def test_latest_result_is_per_block_and_check_not_per_ac(self):
        held = self.select(gnode(10, hold(block(check(), check(host="eleven-m5")))),
                           gnode(11, result(10, 0, "fail")), gnode(12, result(10, 1, "pass", host="eleven-m5")),
                           gnode(13, result(10, 0, "pass")))
        self.assertEqual(vi.latest_result(held.markers, 10, 0).comment_id, 13)
        self.assertEqual(vi.latest_result(held.markers, 10, 1).comment_id, 12)
        self.assertIsNone(vi.latest_result(held.markers, 10, 2))
        self.assertIsNone(vi.latest_result(held.markers, 99, 0))

    def test_live_one_honours_end_markers(self):
        fields = {"event": "deployed", "merge": MERGE, "host": "mbp"}
        held = self.select(gnode(10, hold(block())), gnode(11, marker(vi.WINDOW, fields)),
                           gnode(12, marker(vi.WINDOW, {**fields, "host": "eleven-m5"})))
        match = {"event": "deployed", "merge": MERGE}
        self.assertEqual(vi.live_one(held.markers, vi.WINDOW, match).comment_id, 11)
        ended = self.select(gnode(10, hold(block())), gnode(11, marker(vi.WINDOW, fields)),
                            gnode(12, marker(vi.WINDOW, {**fields, "host": "eleven-m5"})),
                            gnode(13, fm.end_body(11, "stale")))
        self.assertEqual(vi.live_one(ended.markers, vi.WINDOW, match).comment_id, 12)
        self.assertIsNone(vi.live_one(held.markers, vi.DUE, {"block": "10", "check": "0"}))

    def test_latest_result_ignores_other_kinds(self):
        held = self.select(gnode(10, hold(block())), gnode(11, result(10, 0, "pass")),
                           gnode(12, marker(vi.RUN, {"block": "10", "check": "0", "host": "mbp"})))
        self.assertEqual(vi.latest_result(held.markers, 10, 0).comment_id, 11)

    def test_comments_are_sorted_by_ascending_id(self):
        comments = vi.comments_from_graphql([gnode(12, "b"), gnode(10, "a"), gnode(11, "c")])
        self.assertEqual([c.id for c in comments], [10, 11, 12])

    def test_bad_payload_is_a_forge_error(self):
        for node in ({"databaseId": "x", "authorAssociation": "OWNER", "body": "", "createdAt": T0},
                     {"databaseId": True, "authorAssociation": "OWNER", "body": "", "createdAt": T0},
                     {"databaseId": 1, "authorAssociation": None, "body": "", "createdAt": T0},
                     "not an object"):
            with self.assertRaises(fm.ForgeError) as caught:
                vi.comments_from_graphql([node])
            self.assertEqual(caught.exception.code, "payload_invalid")


if __name__ == "__main__":
    unittest.main()
