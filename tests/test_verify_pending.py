"""verify-pending run (issue 630): selection, conditions, the run gate, passes and the command."""
import json
import os
import unittest
from datetime import datetime, timezone
from unittest import mock

from agent_tools import forge_markers as fm
from agent_tools import verify_facts as vf
from agent_tools import verify_issues as vi

from .forge_world import ForgeWorld, host_clock

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


NOW_HEADERS = "HTTP/2.0 200 OK\r\nDate: Fri, 06 Nov 2026 10:00:00 GMT\r\n\r\n{}"
WRONG = datetime(2030, 1, 1, tzinfo=timezone.utc)


def world_with(test, *tools):
    world = ForgeWorld(test, tools=tools)
    world.respond("gh", ["api", "--include", "rate_limit"], stdout=NOW_HEADERS)
    return world


TRACKER = {"kind": "github", "repo_slug": SLUG, "cli": "gh", "credential_env": {"unset_before_invocation": []}}


def context(world, markers=(), deploy=None):
    return vf.Context(slug=SLUG, root=world.checkout, default_branch="main",
                      deploy=deploy or {"adapter": "none", "command": None, "config": {}},
                      tracker=TRACKER, markers=list(markers))


def pushed(world, rev, on_forge=True):
    if on_forge:
        world.respond_json("gh", ["api", f"repos/{SLUG}/commits/{rev}"], {"sha": rev})
    else:
        world.respond("gh", ["api", f"repos/{SLUG}/commits/{rev}"], exit=1,
                      stderr="gh: No commit found for SHA (HTTP 422)")


def ancestry(world, sha, rev, exit):
    world.respond("git", ["-C", str(world.checkout), "merge-base", "--is-ancestor", sha, rev], exit=exit)


class WhenTest(unittest.TestCase):
    def deployed(self, revision, *, git_exit=None, compare=None, tool="darwin-version", on_forge=True):
        world = world_with(self, tool)
        world.respond_json(tool, ["--json"], {"configurationRevision": revision})
        pushed(world, REV, on_forge)
        if git_exit is not None:
            ancestry(world, MERGE, REV, git_exit)
        if compare == 404:
            world.not_found("gh", ["api", f"repos/{SLUG}/compare/{MERGE}...{REV}"])
        elif compare is not None:
            world.respond_json("gh", ["api", f"repos/{SLUG}/compare/{MERGE}...{REV}"], {"status": compare})
        due = vf.evaluate_when({"deployed_includes": MERGE}, MERGE, context(world))
        return world, due

    def test_deployed_ancestor_is_due(self):
        world, due = self.deployed(REV, git_exit=0)
        self.assertEqual((due.due, due.reason, due.facts), (True, "due", {"rev": REV}))

    def test_deployed_non_ancestor_is_pending(self):
        _, due = self.deployed(REV, git_exit=1)
        self.assertEqual((due.due, due.reason), (False, "not_deployed"))

    def test_null_revision_stays_pending_without_git(self):
        world, due = self.deployed(None)
        self.assertEqual(due.reason, "revision_unknown")
        self.assertEqual(world.argvs("git"), [])

    def test_dirty_suffix_is_stripped(self):
        world, due = self.deployed(REV + "-dirty", git_exit=0)
        self.assertTrue(due.due)
        self.assertIn(["-C", str(world.checkout), "merge-base", "--is-ancestor", MERGE, REV], world.argvs("git"))

    def test_unknown_object_falls_back_to_compare(self):
        _, due = self.deployed(REV, git_exit=128, compare="ahead")
        self.assertTrue(due.due)
        _, due = self.deployed(REV, git_exit=128, compare="diverged")
        self.assertEqual(due.reason, "not_deployed")

    def test_a_local_ancestor_the_forge_lacks_stays_pending(self):
        world, due = self.deployed(REV, git_exit=0, on_forge=False)
        self.assertEqual(due.reason, "revision_unpushed")
        self.assertEqual(world.argvs("git"), [])

    def test_compare_404_stays_pending(self):
        _, due = self.deployed(REV, git_exit=128, compare=404)
        self.assertEqual(due.reason, "compare_unknown")

    def test_nixos_version_when_no_darwin_version(self):
        _, due = self.deployed(REV, git_exit=0, tool="nixos-version")
        self.assertTrue(due.due)

    def released(self, latest, *, contains="ahead", on_default="ahead"):
        world = world_with(self)
        if latest is None:
            world.not_found("gh", ["api", f"repos/{SLUG}/releases/latest"])
        else:
            world.respond_json("gh", ["api", f"repos/{SLUG}/releases/latest"], {"tag_name": latest, "draft": False})
            world.respond_json("gh", ["api", f"repos/{SLUG}/compare/{MERGE}...{latest}"], {"status": contains})
            world.respond_json("gh", ["api", f"repos/{SLUG}/compare/{latest}...main"], {"status": on_default})
        return vf.evaluate_when({"released_includes": MERGE}, MERGE, context(world))

    def test_release_tag_containing_the_sha_is_due(self):
        due = self.released("v1.2.0")
        self.assertEqual((due.due, due.facts), (True, {"tag": "v1.2.0"}))
        self.assertTrue(self.released("v1.2.0", contains="identical", on_default="identical").due)

    def test_release_tag_not_containing_or_off_default_is_pending(self):
        self.assertEqual(self.released("v1.2.0", contains="behind").reason, "not_released")
        self.assertEqual(self.released("v1.2.0", on_default="diverged").reason, "not_released")
        self.assertEqual(self.released(None).reason, "not_released")

    def test_bound_deploy_watch_decides_release_inclusion(self):
        world = world_with(self)
        bound = context(world, deploy={"adapter": "github-actions-health", "command": None, "config": {}})
        with mock.patch.object(vf, "deploy_observation", return_value={"outcome": "satisfied"}):
            self.assertTrue(vf.evaluate_when({"released_includes": MERGE}, MERGE, bound).due)
        with mock.patch.object(vf, "deploy_observation", return_value={"outcome": "absent"}):
            self.assertEqual(vf.evaluate_when({"released_includes": MERGE}, MERGE, bound).reason, "not_released")
        self.assertEqual(world.argvs("gh"), [])

    def test_a_command_backed_watch_stays_pending_without_tags(self):
        world = world_with(self)
        deploy = {"adapter": "custom-reader", "command": "deploy-read", "config": {}}
        due = vf.evaluate_when({"released_includes": MERGE}, MERGE, context(world, deploy=deploy))
        self.assertEqual(due.reason, "deploy_watch_unread")
        self.assertEqual(world.argvs("gh"), [])

    def test_the_bound_adapter_runs_with_no_token_and_the_environment_comes_back(self):
        world = world_with(self)
        deploy = {"adapter": "github-actions-health", "command": None,
                  "config": {"workflow": "deploy.yaml", "branch": "main", "services": ["web"],
                             "health_url": "https://health.example.invalid/version",
                             "health_commit_field": "commit"}}
        world.respond_json("gh", ["run", "list", "--repo", SLUG, "--workflow", "deploy.yaml", "--branch", "main",
                                  "--limit", "5", "--json", "databaseId,status,conclusion,headSha,headBranch,createdAt"],
                           [{"databaseId": 1, "status": "in_progress", "conclusion": "", "headSha": MERGE,
                             "headBranch": "main", "createdAt": T0}])
        with mock.patch.dict(os.environ, {"GH_TOKEN": "user-token"}):
            due = vf.evaluate_when({"released_includes": MERGE}, MERGE, context(world, deploy=deploy))
            self.assertEqual((os.environ["GITHUB_TOKEN"], os.environ["GH_TOKEN"]), ("harness-token", "user-token"))
        self.assertEqual(due.reason, "not_released")
        runs = [call for call in world.calls() if call["argv"][:2] == ["run", "list"]]
        self.assertEqual([call["token_visible"] for call in runs], [False])

    def ci(self, runs):
        world = world_with(self)
        world.respond_json("gh", ["api", f"repos/{SLUG}/actions/runs?branch=main&head_sha={MERGE}&per_page=100"],
                           {"total_count": len(runs), "workflow_runs": runs})
        when = {"ci_run_includes": {"workflow": "ci.yaml", "branch": "main", "sha": MERGE}}
        return vf.evaluate_when(when, MERGE, context(world))

    def test_ci_run_inclusion(self):
        ok = {"name": "CI", "path": ".github/workflows/ci.yaml", "status": "completed", "conclusion": "success"}
        self.assertTrue(self.ci([ok]).due)
        self.assertTrue(self.ci([{**ok, "name": "ci.yaml", "path": ".github/workflows/renamed.yaml"}]).due)
        self.assertEqual(self.ci([{**ok, "status": "in_progress", "conclusion": None}]).reason, "ci_not_passed")
        self.assertEqual(self.ci([{**ok, "path": ".github/workflows/other.yaml", "name": "Other"}]).reason,
                         "ci_not_passed")

    def test_not_before_reads_the_server_clock(self):
        world = world_with(self)
        with host_clock(WRONG, vf, fm):
            self.assertTrue(vf.evaluate_when({"not_before": "2026-11-06T09:00:00+00:00"}, MERGE, context(world)).due)
            self.assertEqual(vf.evaluate_when({"not_before": "2026-11-06T11:00:00+00:00"}, MERGE,
                                              context(world)).reason, "not_before")

    def window(self, at, days):
        world = world_with(self)
        nodes = [gnode(10, hold(block())),
                 gnode(11, marker(vi.WINDOW, {"event": "deployed", "merge": MERGE, "host": "eleven-m5"}), at=at)]
        held = vi.select(vi.comments_from_graphql(nodes))
        with host_clock(WRONG, vf, fm):
            return world, vf.evaluate_when({"days_after": {"event": "deployed", "days": days}}, MERGE,
                                           context(world, held.markers))

    def test_days_after_window_opened_by_another_host(self):
        world, due = self.window("2026-10-28T10:00:00Z", 7)  # the server says 2026-11-06
        self.assertTrue(due.due)
        self.assertEqual(world.argvs("git"), [])
        _, due = self.window("2026-11-03T10:00:00Z", 7)
        self.assertEqual(due.reason, "window_not_open")

    def test_days_after_without_a_window_reports_opening(self):
        world = world_with(self, "darwin-version")
        world.respond_json("darwin-version", ["--json"], {"configurationRevision": REV})
        pushed(world, REV)
        ancestry(world, MERGE, REV, 0)
        due = vf.evaluate_when({"days_after": {"event": "deployed", "days": 7}}, MERGE, context(world))
        self.assertEqual((due.due, due.reason, due.open_window), (False, "window_opening", "deployed"))
        ancestry(world, MERGE, REV, 1)
        self.assertEqual(vf.evaluate_when({"days_after": {"event": "deployed", "days": 7}}, MERGE,
                                          context(world)).reason, "window_not_open")

    def test_first_unmet_member_stops_evaluation(self):
        world = world_with(self, "darwin-version")
        due = vf.evaluate_when({"not_before": "2027-01-01T00:00:00+00:00", "deployed_includes": MERGE},
                               MERGE, context(world))
        self.assertEqual(due.reason, "not_before")
        self.assertNotIn("darwin-version", [call["tool"] for call in world.calls()])


class ProbeTest(unittest.TestCase):
    def test_deployed_probe_exits(self):
        world = world_with(self, "darwin-version")
        world.respond_json("darwin-version", ["--json"], {"configurationRevision": REV})
        pushed(world, REV)
        ancestry(world, MERGE, REV, 0)
        self.assertEqual(vf.run_probe({"probe": "deployed_includes", "sha": MERGE}, context(world)).exit, 0)
        ancestry(world, MERGE, REV, 1)
        self.assertEqual(vf.run_probe({"probe": "deployed_includes", "sha": MERGE}, context(world)).exit, 75)

    def test_ci_probe_failure_is_not_met(self):
        world = world_with(self)
        world.respond_json("gh", ["api", f"repos/{SLUG}/actions/runs?branch=main&head_sha={MERGE}&per_page=100"],
                           {"workflow_runs": [{"name": "ci.yaml", "path": "x/ci.yaml", "status": "completed",
                                               "conclusion": "failure"}]})
        run = {"probe": "ci_run_includes", "workflow": "ci.yaml", "branch": "main", "sha": MERGE}
        self.assertEqual(vf.run_probe(run, context(world)).exit, 1)

    def test_count_since_releases(self):
        world = world_with(self)
        world.respond_json("gh", ["api", f"repos/{SLUG}/releases?per_page=100"], [
            {"draft": False, "published_at": "2026-11-02T00:00:00Z"},
            {"draft": True, "published_at": "2026-11-03T00:00:00Z"},
            {"draft": False, "published_at": "2026-10-01T00:00:00Z"}])
        run = {"probe": "count_since", "source": "releases", "since": "2026-11-01T00:00:00+00:00", "n": 1}
        self.assertEqual(vf.run_probe(run, context(world)).exit, 0)
        self.assertEqual(vf.run_probe({**run, "n": 2}, context(world)).exit, 75)


if __name__ == "__main__":
    unittest.main()
