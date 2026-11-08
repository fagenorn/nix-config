"""verify-pending run (issue 630): selection, conditions, the run gate, passes and the command."""
import contextlib
import dataclasses
import hashlib
import io
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from agent_tools import forge_markers as fm
from agent_tools import verify_exec as vx
from agent_tools import verify_facts as vf
from agent_tools import verify_issues as vi
from agent_tools import verify_pending
from agent_tools import verify_run as vr
from agent_tools.resolve_project import resolve
from agent_tools.verify_block import lint_block

from .forge_world import ForgeWorld, host_clock

SLUG, ISSUE = "octo/widgets", 7
MERGE, REV, TIP = "a" * 40, "b" * 40, "c" * 40
T0 = "2026-11-06T10:00:00Z"


def gnode(cid, body, association="OWNER", at=T0):
    """One GraphQL comment node."""
    return {"fullDatabaseId": str(cid), "authorAssociation": association, "body": body,
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


def bkey(*checks, at=10):
    """The identity of a block version: its comment id and a digest of its content (CR-1)."""
    text = json.dumps(block(*checks), sort_keys=True, separators=(",", ":"))
    return f"{at}.{hashlib.sha256(text.encode()).hexdigest()[:16]}"


def marker(kind, fields, sentence="Recorded."):
    return fm.render(kind, fields, sentence)


def result(block_key, index, state, ac="AC1", host="mbp", **extra):
    return marker(vi.RESULT, {"block": str(block_key), "check": str(index), "ac": ac, "state": state,
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
        forged = result(bkey(), 0, "pass") + "\n```verify\n" + json.dumps(block(check(ac="AC9"))) + "\n```"
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
                           gnode(11, result(bkey(), 0, "fail")),
                           gnode(12, result(bkey(), 0, "pass"), "NONE"),
                           gnode(13, fm.end_body(11, "forged"), "NONE"),
                           gnode(14, "a plain comment"))
        self.assertEqual([m.comment_id for m in held.markers], [11])
        self.assertEqual(vi.live_one(held.markers, vi.RESULT, {"block": bkey()}).comment_id, 11)

    def test_marker_time_is_the_creation_time(self):
        node = gnode(11, result(bkey(), 0, "fail"), at="2026-11-01T08:00:00Z")
        node["updatedAt"] = "2026-11-05T08:00:00Z"
        held = self.select(gnode(10, hold(block())), node)
        self.assertEqual(held.markers[0].updated_at.isoformat(), "2026-11-01T08:00:00+00:00")

    def test_latest_result_is_per_block_and_check_not_per_ac(self):
        checks = (check(), check(host="eleven-m5"))
        key = bkey(*checks)
        held = self.select(gnode(10, hold(block(*checks))),
                           gnode(11, result(key, 0, "fail")), gnode(12, result(key, 1, "pass", host="eleven-m5")),
                           gnode(13, result(key, 0, "pass")))
        self.assertEqual(held.key, key)
        self.assertEqual(vi.latest_result(held.markers, held.key, 0).comment_id, 13)
        self.assertEqual(vi.latest_result(held.markers, held.key, 1).comment_id, 12)
        self.assertIsNone(vi.latest_result(held.markers, held.key, 2))
        self.assertIsNone(vi.latest_result(held.markers, bkey(*checks, at=99), 0))

    def test_a_result_of_an_earlier_version_of_an_edited_block_is_never_the_latest(self):
        older = bkey(check(ac="AC1"))
        held = self.select(gnode(10, hold(block(check(ac="AC2")))), gnode(11, result(older, 0, "pass")))
        self.assertNotEqual(held.key, older)
        self.assertEqual(held.key.split(".")[0], "10")
        self.assertIsNone(vi.latest_result(held.markers, held.key, 0))
        self.assertEqual(vi.latest_result(held.markers, older, 0).comment_id, 11)

    def test_reordered_checks_are_another_version(self):
        one, two = check(ac="AC1"), check(ac="AC2", host="eleven-m5")
        self.assertNotEqual(bkey(one, two), bkey(two, one))
        held = self.select(gnode(10, hold(block(two, one))), gnode(11, result(bkey(one, two), 0, "pass")))
        self.assertIsNone(vi.latest_result(held.markers, held.key, 0))

    def test_the_version_ignores_how_the_block_is_spelled(self):
        compact = "```verify\n" + json.dumps(block()) + "\n```"
        spaced = "```verify\n" + json.dumps(block(), indent=2, sort_keys=True) + "\n```"
        self.assertEqual(self.select(gnode(10, compact)).key, self.select(gnode(10, spaced)).key)

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
        self.assertIsNone(vi.live_one(held.markers, vi.DUE, {"block": bkey(), "check": "0"}))

    def test_a_window_before_the_block_carries_over_to_a_replacement_block(self):
        fields = {"event": "deployed", "merge": MERGE, "host": "mbp"}
        held = self.select(gnode(8, marker(vi.WINDOW, fields)), gnode(9, result(8, 0, "pass")),
                           gnode(10, hold(block())), gnode(11, marker(vi.WINDOW, fields, "again")),
                           gnode(12, marker(vi.WINDOW, {**fields, "host": "x"}), "NONE"))
        self.assertEqual([m.comment_id for m in held.markers], [8, 11])
        self.assertEqual(vi.live_one(held.markers, vi.WINDOW, {"event": "deployed", "merge": MERGE}).comment_id, 8)
        ended = self.select(gnode(8, marker(vi.WINDOW, fields)), gnode(9, fm.end_body(8, "stale")),
                            gnode(10, hold(block())))
        self.assertIsNone(vi.live_one(ended.markers, vi.WINDOW, {"event": "deployed", "merge": MERGE}))

    def test_an_ended_result_is_not_the_latest(self):
        held = self.select(gnode(10, hold(block())), gnode(11, result(bkey(), 0, "fail")),
                           gnode(12, result(bkey(), 0, "pass")), gnode(13, fm.end_body(12, "stale")))
        self.assertEqual(vi.latest_result(held.markers, held.key, 0).comment_id, 11)
        gone = self.select(gnode(10, hold(block())), gnode(11, result(bkey(), 0, "pass")),
                           gnode(12, fm.end_body(11, "stale")))
        self.assertIsNone(vi.latest_result(gone.markers, gone.key, 0))

    def test_latest_result_ignores_other_kinds(self):
        held = self.select(gnode(10, hold(block())), gnode(11, result(bkey(), 0, "pass")),
                           gnode(12, marker(vi.RUN, {"block": bkey(), "check": "0", "host": "mbp"})))
        self.assertEqual(vi.latest_result(held.markers, held.key, 0).comment_id, 11)

    def test_comments_are_sorted_by_ascending_id(self):
        comments = vi.comments_from_graphql([gnode(12, "b"), gnode(10, "a"), gnode(11, "c")])
        self.assertEqual([c.id for c in comments], [10, 11, 12])

    def test_bad_payload_is_a_forge_error(self):
        for node in ({"fullDatabaseId": "x", "authorAssociation": "OWNER", "body": "", "createdAt": T0},
                     {"fullDatabaseId": True, "authorAssociation": "OWNER", "body": "", "createdAt": T0},
                     {"fullDatabaseId": 1, "authorAssociation": "OWNER", "body": "", "createdAt": T0},
                     {"fullDatabaseId": "-1", "authorAssociation": "OWNER", "body": "", "createdAt": T0},
                     {"fullDatabaseId": " 1", "authorAssociation": "OWNER", "body": "", "createdAt": T0},
                     {"fullDatabaseId": "\u00b2", "authorAssociation": "OWNER", "body": "", "createdAt": T0},
                     {"fullDatabaseId": "", "authorAssociation": "OWNER", "body": "", "createdAt": T0},
                     {"databaseId": 1, "authorAssociation": "OWNER", "body": "", "createdAt": T0},
                     {"fullDatabaseId": "1", "authorAssociation": None, "body": "", "createdAt": T0},
                     "not an object"):
            with self.assertRaises(fm.ForgeError) as caught:
                vi.comments_from_graphql([node])
            self.assertEqual(caught.exception.code, "payload_invalid")

    def test_a_comment_id_beyond_a_32_bit_int_is_read_from_the_big_integer_field(self):
        big = 6_693_579_241  # a real id of this repository: databaseId (a 32-bit Int) cannot hold it
        comments = vi.comments_from_graphql([gnode(big + 1, "b"), gnode(big, "a"), gnode(2**31, "c")])
        self.assertEqual([c.id for c in comments], [2**31, big, big + 1])

    def test_the_listing_asks_for_the_big_integer_field_alone(self):
        self.assertIn("fullDatabaseId", vr.QUERY)
        self.assertNotRegex(vr.QUERY, r"\bdatabaseId\b")


NOW_HEADERS = "HTTP/2.0 200 OK\r\nDate: Fri, 06 Nov 2026 10:00:00 GMT\r\n\r\n{}"
WRONG = datetime(2030, 1, 1, tzinfo=timezone.utc)


def world_with(test, *tools):
    world = ForgeWorld(test, tools=tools)
    world.respond("gh", ["api", "--include", "rate_limit"], stdout=NOW_HEADERS)
    return world


TRACKER = {"kind": "github", "repo_slug": SLUG, "cli": "gh", "credential_env": {"unset_before_invocation": []}}


def context(world, markers=()):
    return vf.Context(slug=SLUG, root=world.checkout, default_branch="main",
                      tracker=TRACKER, markers=list(markers))


def pushed(world, rev, on_forge=True):
    if on_forge:
        world.respond_json("gh", ["api", f"repos/{SLUG}/commits/{rev}"], {"sha": rev})
    else:
        world.respond("gh", ["api", f"repos/{SLUG}/commits/{rev}"], exit=1,
                      stderr="gh: No commit found for SHA (HTTP 422)")


def ancestry(world, sha, rev, exit):
    world.respond("git", ["-C", str(world.checkout), "merge-base", "--is-ancestor", sha, rev], exit=exit)


class StrictContextTest(unittest.TestCase):
    """Platform 2.0.0: the deploy binding is gone, so the context carries none (P9)."""

    def test_the_context_has_no_deploy_member(self):
        self.assertNotIn("deploy", {f.name for f in dataclasses.fields(vf.Context)})

    def test_released_includes_reads_the_latest_release(self):
        world = world_with(self)
        latest = "v1.2.0"
        world.respond_json("gh", ["api", f"repos/{SLUG}/releases/latest"], {"tag_name": latest, "draft": False})
        world.respond_json("gh", ["api", f"repos/{SLUG}/compare/{MERGE}...{latest}"], {"status": "ahead"})
        world.respond_json("gh", ["api", f"repos/{SLUG}/compare/{latest}...main"], {"status": "ahead"})
        due = vf.evaluate_when({"released_includes": MERGE}, MERGE, context(world))
        self.assertEqual((due.due, due.facts), (True, {"tag": latest}))

    def test_no_observation_reader_survives(self):
        self.assertEqual([name for name in dir(vf) if "observ" in name.lower()
                          or "health" in name.lower()], [])


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


RELEASES = ["api", "--paginate", "--slurp", f"repos/{SLUG}/releases?per_page=100"]
RUNS_SINCE = ["api", "--paginate", "--slurp", f"repos/{SLUG}/actions/workflows/ci.yaml/runs?per_page=100"
              "&branch=main&created=%3E%3D2026-11-01T00%3A00%3A00Z"]


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
        world.respond_json("gh", RELEASES, [[
            {"draft": False, "published_at": "2026-11-02T00:00:00Z"},
            {"draft": True, "published_at": "2026-11-03T00:00:00Z"},
            {"draft": False, "published_at": "2026-10-01T00:00:00Z"}]])
        run = {"probe": "count_since", "source": "releases", "since": "2026-11-01T00:00:00+00:00", "n": 1}
        self.assertEqual(vf.run_probe(run, context(world)).exit, 0)
        self.assertEqual(vf.run_probe({**run, "n": 2}, context(world)).exit, 75)

    def test_count_since_releases_counts_every_page(self):
        world = world_with(self)
        page = [{"draft": False, "published_at": "2026-11-02T00:00:00Z"}] * 100
        world.respond_json("gh", RELEASES, [page, page[:30]])
        run = {"probe": "count_since", "source": "releases", "since": "2026-11-01T00:00:00+00:00", "n": 130}
        self.assertEqual(vf.run_probe(run, context(world)).exit, 0)
        self.assertEqual(vf.run_probe({**run, "n": 131}, context(world)).exit, 75)

    def test_count_since_runs_reads_every_page_of_the_per_workflow_listing(self):
        world = world_with(self)
        ci = {"name": "CI", "path": ".github/workflows/ci.yaml", "created_at": "2026-11-02T00:00:00Z"}
        world.respond_json("gh", RUNS_SINCE, [{"total_count": 103, "workflow_runs": [ci] * 100},
                                              {"total_count": 103, "workflow_runs": [ci] * 3}])
        run = {"probe": "count_since", "source": "runs", "workflow": "ci.yaml", "branch": "main",
               "since": "2026-11-01T00:00:00+00:00", "n": 103}
        self.assertEqual(vf.run_probe(run, context(world)).exit, 0)
        self.assertEqual(vf.run_probe({**run, "n": 104}, context(world)).exit, 75)
        self.assertFalse([argv for argv in world.argvs("gh") if f"repos/{SLUG}/actions/runs?" in " ".join(argv)])

    def test_count_since_runs_refuses_a_truncated_listing(self):
        world = world_with(self)
        ci = {"name": "CI", "path": ".github/workflows/ci.yaml", "created_at": "2026-11-02T00:00:00Z"}
        world.respond_json("gh", RUNS_SINCE, [{"total_count": 1500, "workflow_runs": [ci] * 100}] * 10)
        run = {"probe": "count_since", "source": "runs", "workflow": "ci.yaml", "branch": "main",
               "since": "2026-11-01T00:00:00+00:00", "n": 1200}
        with self.assertRaises(fm.ForgeError) as raised:
            vf.run_probe(run, context(world))
        self.assertIn("truncated", str(raised.exception))


HERMETIC_GIT = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
                "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
                "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}
REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = REPO_ROOT / "home/common/agent-skills/evals/fixture-repo"
MANIFEST = REPO_ROOT / "home/common/agent-skills/platform-manifest.json"


class GateTest(unittest.TestCase):
    VERIFICATION = ["nix-build"]

    def gate(self, **over):
        return vx.gate(check(**over), self.VERIFICATION)

    def test_read_only_forms_run(self):
        self.assertEqual(self.gate(), vx.Gate(True, "due"))
        self.assertTrue(self.gate(run={"script": "scripts/check.sh"}).runnable)
        self.assertTrue(self.gate(run={"command": "nix-build"}).runnable)

    def test_owner_live_and_paid_checks_never_run(self):
        self.assertEqual(self.gate(kind="human", reason="senses", run={"ask": "Does it look right?"}).reason,
                         "owner_check")
        self.assertEqual(self.gate(kind="human", reason="hands",
                                   run={"act": "Plug it in", "then": {"probe": "deployed_includes", "sha": MERGE}}
                                   ).reason, "owner_check")
        self.assertEqual(self.gate(effects="live").reason, "effects_live")
        self.assertEqual(self.gate(effects="paid").reason, "effects_paid")

    def test_a_contract_command_outside_verification_is_live(self):
        self.assertEqual(self.gate(run={"command": "nix-activate"}), vx.Gate(False, "command_not_verification"))


class ExpectTest(unittest.TestCase):
    def test_expect_tests(self):
        out = json.dumps({"a": {"b/c": [1, 2, 3]}, "ok": True, "n": 1})
        self.assertTrue(vx.expect_met(None, "not json"))
        self.assertTrue(vx.expect_met({"json": [{"pointer": "/a/b~1c", "min_len": 3}]}, out))
        self.assertTrue(vx.expect_met({"json": [{"pointer": "/a/b~1c/1", "equals": 2}]}, out))
        self.assertFalse(vx.expect_met({"json": [{"pointer": "/n", "equals": True}]}, out))
        self.assertFalse(vx.expect_met({"json": [{"pointer": "/missing", "equals": 1}]}, out))
        self.assertFalse(vx.expect_met({"json": [{"pointer": "", "min_len": 4}]}, out))
        self.assertFalse(vx.expect_met({"json": [{"pointer": "/ok", "equals": True}]}, "{\"ok\": true, \"ok\": true}"))

    def test_classify(self):
        def result(code, out=""):
            return vx.Result(code, out, "", False)
        self.assertEqual(vx.classify(result(0), None), "met")
        self.assertEqual(vx.classify(result(0, "[]"), {"json": [{"pointer": "", "min_len": 1}]}), "not_met")
        self.assertEqual(vx.classify(result(1), None), "not_met")
        self.assertEqual(vx.classify(result(75), None), "not_yet")
        self.assertEqual(vx.classify(result(2), None), "exit_unexpected")
        self.assertEqual(vx.classify(result(None), None), "exit_unexpected")
        self.assertEqual(vx.classify(vx.Result(None, "", "", True), None), "timeout")
        self.assertEqual(vx.trim("x" * 10 + "tail", 4), "tail")


class ExecuteTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.dir, ignore_errors=True))

    def script(self, name, body):
        path = self.dir / name
        path.write_text(f"#!{sys.executable}\n{body}\n", encoding="utf-8")
        path.chmod(0o755)
        return str(path)

    def test_exit_output_and_no_token(self):
        argv = [self.script("c.py", "import os, sys\nprint(os.environ.get('GITHUB_TOKEN'), os.environ.get('GH_TOKEN'))\n"
                                    "sys.exit(75)")]
        with mock.patch.dict(os.environ, {"GITHUB_TOKEN": "t", "GH_TOKEN": "t"}):
            result = vx.execute(argv, self.dir)
        self.assertEqual((result.exit, result.stdout.strip(), result.timed_out), (75, "None None", False))

    def test_timeout_kills_the_process_group(self):
        pidfile = self.dir / "pid"
        argv = [self.script("slow.py", "import subprocess, sys, time\n"
                                       f"p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
                                       f"open({str(pidfile)!r}, 'w').write(str(p.pid))\ntime.sleep(60)")]
        started = time.monotonic()
        result = vx.execute(argv, self.dir, timeout=2)
        self.assertLess(time.monotonic() - started, 20, "the pipes were held open by a surviving grandchild")
        self.assertTrue(result.timed_out)
        grandchild = int(pidfile.read_text())
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                os.kill(grandchild, 0)
            except ProcessLookupError:
                break
            time.sleep(0.05)
        else:
            self.fail("the grandchild outlived the timeout")

    def test_non_utf8_output_is_a_result_not_an_exception(self):
        argv = [self.script("raw.py", "import sys\nsys.stdout.buffer.write(b'a\\xffb')\nsys.stderr.buffer.write(b'\\xfe')")]
        result = vx.execute(argv, self.dir)
        self.assertEqual((result.exit, result.timed_out), (0, False))
        self.assertEqual((result.stdout, result.stderr), ("a\ufffdb", "\ufffd"))

    def test_non_utf8_output_on_timeout_is_a_result(self):
        argv = [self.script("rawslow.py", "import sys, time\nsys.stdout.buffer.write(b'\\xff')\nsys.stdout.flush()\ntime.sleep(60)")]
        result = vx.execute(argv, self.dir, timeout=2)
        self.assertTrue(result.timed_out)
        self.assertEqual(result.stdout, "\ufffd")

    def test_spawn_error_is_unexpected(self):
        result = vx.execute([str(self.dir / "absent")], self.dir)
        self.assertEqual(vx.classify(result, None), "exit_unexpected")

    def test_run_argv_relativises_against_the_contract_root(self):
        export, wt = Path("/tmp/export-1"), Path("/tmp/wt")
        bindings = {"commands": {"nix-build": {"argv": ["just", "build"], "cwd": "/tmp/export-1/sub", "env": []}}}
        self.assertEqual(vx.run_argv({"command": "nix-build"}, bindings, export, wt), (["just", "build"], wt / "sub"))
        self.assertEqual(vx.run_argv({"script": "s/c.sh", "args": ["x"]}, bindings, export, wt),
                         ([str(wt / "s/c.sh"), "x"], wt))


@contextlib.contextmanager
def child_environments():
    """Run with forge tokens set, recording the environment each `subprocess.run` child starts with."""
    seen, real = [], subprocess.run

    def spy(argv, *args, **kwargs):
        env = kwargs.get("env")
        seen.append((list(argv), dict(os.environ if env is None else env)))
        return real(argv, *args, **kwargs)

    with mock.patch.dict(os.environ, {"GITHUB_TOKEN": "token-one", "GH_TOKEN": "token-two"}):
        with mock.patch("subprocess.run", spy):
            yield seen
        assert os.environ["GITHUB_TOKEN"] == "token-one" and os.environ["GH_TOKEN"] == "token-two"


def assert_tokenless(test, seen):
    test.assertTrue(any(argv[0] == "git" for argv, _ in seen), "no git child was started")
    for argv, env in seen:
        test.assertEqual({"GITHUB_TOKEN", "GH_TOKEN"} & set(env), set(), argv)


class GitRepos(unittest.TestCase):
    """A bare `origin` and a clone (`root`) that lags it: origin's `main` is one commit ahead."""

    def setUp(self):
        patch = mock.patch.dict(os.environ, HERMETIC_GIT)
        patch.start()
        self.addCleanup(patch.stop)
        self.dir = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(lambda: shutil.rmtree(self.dir, ignore_errors=True))
        self.origin, self.root = self.dir / "origin.git", self.dir / "root"
        self.git(self.dir, "init", "-q", "--bare", "-b", "main", str(self.origin))
        self.git(self.origin, "config", "uploadpack.allowAnySHA1InWant", "true")
        self.git(self.dir, "clone", "-q", str(self.origin), str(self.root))
        self.git(self.root, "config", "commit.gpgsign", "false")

    def git(self, cwd, *args):
        return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True,
                              text=True).stdout.strip()

    def commit(self, message):
        self.git(self.root, "add", "-A")
        self.git(self.root, "commit", "-q", "-m", message)
        return self.git(self.root, "rev-parse", "HEAD")

    def lag(self, to):
        """Push HEAD to origin's main, then move the clone and its tracking ref back to `to`."""
        self.git(self.root, "push", "-q", "origin", "HEAD:main")
        self.git(self.root, "reset", "-q", "--hard", to)
        self.git(self.root, "update-ref", "refs/remotes/origin/main", to)
        subprocess.run(["git", "-C", str(self.root), "update-ref", "-d", "ORIG_HEAD"], capture_output=True)
        self.git(self.root, "reflog", "expire", "--expire=now", "--all")
        self.git(self.root, "gc", "-q", "--prune=now")


class WorkspaceTest(GitRepos):
    def setUp(self):
        super().setUp()
        (self.root / "f").write_text("one\n")
        self.first = self.commit("one")
        self.git(self.root, "push", "-q", "origin", "HEAD:main")
        (self.root / "f").write_text("two\n")
        self.second = self.commit("two")
        self.lag(self.first)

    def test_a_commit_only_origin_holds_is_fetched_and_checked_out_detached(self):
        with vx.workspace(self.root, self.second) as wt:
            self.assertEqual((wt / "f").read_text(), "two\n")
            kept = wt
        self.assertFalse(kept.exists())
        self.assertFalse(kept.parent.exists())
        self.assertEqual(len(self.git(self.root, "worktree", "list").splitlines()), 1)
        self.assertEqual((self.root / "f").read_text(), "one\n")

    def test_a_held_commit(self):
        with vx.workspace(self.root, self.first) as wt:
            self.assertEqual((wt / "f").read_text(), "one\n")

    def test_a_held_commit_is_not_fetched(self):
        with mock.patch.object(vx, "_git", wraps=vx._git) as git:
            self.assertTrue(vx.ensure_commit(self.root, self.first))
        self.assertEqual([call.args[1] for call in git.call_args_list], ["cat-file"])

    def test_cleanup_after_an_error_and_an_unknown_commit(self):
        with self.assertRaises(RuntimeError):
            with vx.workspace(self.root, self.second) as wt:
                kept = wt
                raise RuntimeError("check crashed")
        self.assertFalse(kept.exists())
        with self.assertRaises(vx.WorkspaceError):
            with vx.workspace(self.root, "f" * 40):
                pass


class SourceTest(GitRepos):
    def setUp(self):
        super().setUp()
        # The resolver reads the installed platform manifest under `HOME`; a hosted runner has
        # none, so the source manifest is installed into a private one, as `CommandTest` does.
        home = self.dir / "home"
        (home / ".agents" / "share").mkdir(parents=True)
        shutil.copy(MANIFEST, home / ".agents" / "share" / "platform-manifest.json")
        patch = mock.patch.dict(os.environ, {"HOME": str(home)})
        patch.start()
        self.addCleanup(patch.stop)
        shutil.copytree(FIXTURE, self.root, dirs_exist_ok=True)
        self.first = self.commit("fixture")
        self.git(self.root, "push", "-q", "origin", "HEAD:main")
        self.contract = self.root / ".agents" / "project.json"
        contract = json.loads(self.contract.read_text("utf-8"))
        contract["bindings"]["commands"]["check-ok"] = {"argv": ["true"], "cwd": ".", "env": []}
        contract["bindings"]["workflow"]["verification"] = ["test", "check-ok"]
        self.contract.write_text(json.dumps(contract, indent=2), encoding="utf-8")
        self.tip = self.commit("allow check-ok")
        self.lag(self.first)
        self.entry = {"project_id": contract["project"]["id"], "root": str(self.root)}

    def test_the_contract_is_read_at_origin_not_from_the_lagging_checkout(self):
        with vx.project_source(self.entry) as source:
            self.assertIn("check-ok", source.snapshot["bindings"]["workflow"]["verification"])
            self.assertEqual((source.commit, source.branch), (self.tip, "main"))
            self.assertEqual(Path(source.snapshot["bindings"]["commands"]["check-ok"]["cwd"]), source.contract_root)
            export = source.contract_root
        self.assertFalse(export.exists())
        local = json.loads(self.contract.read_text("utf-8"))
        self.assertNotIn("check-ok", local["bindings"]["workflow"]["verification"])

    def test_a_branch_the_contract_does_not_name_is_a_source_error(self):
        real = vx.adopt_verify.remote_source

        @contextlib.contextmanager
        def elsewhere(*args, **kwargs):
            with real(*args, **kwargs) as source:
                yield dataclasses.replace(source, branch="elsewhere")

        with mock.patch.object(vx.adopt_verify, "remote_source", elsewhere):
            with self.assertRaises(vx.SourceError) as caught:
                with vx.project_source(self.entry):
                    pass
        self.assertEqual(str(caught.exception), "branch_mismatch")

    def test_no_forge_token_reaches_a_git_child_of_the_source_read(self):
        with child_environments() as seen:
            with vx.project_source(self.entry):
                pass
        assert_tokenless(self, seen)

    def test_an_unresolvable_contract_at_origin_is_a_source_error(self):
        self.git(self.root, "rm", "-q", ".agents/project.json")
        self.commit("drop the contract")
        self.git(self.root, "push", "-q", "--force", "origin", "HEAD:main")
        with self.assertRaises(vx.SourceError):
            with vx.project_source(self.entry):
                pass


if __name__ == "__main__":
    unittest.main()


class Refs:
    """Every reference resolves: these rows exercise the runner, not the lint's lookups (Task 5 tests those)."""
    def command(self, command_id):
        return "present"

    def script(self, path, sha):
        return "present", "present"

    def flake(self, merge):
        return None


def stored_comment(cid, body, association="OWNER", at=T0):
    return {"id": cid, "body": body, "created_at": at, "updated_at": at, "author_association": association}


def line(index, ac, state, reason):
    return {"repo": SLUG, "issue": ISSUE, "check": index, "ac": ac, "state": state, "reason": reason}


def bindings(root):
    def command(tool):
        return {"argv": [tool], "cwd": str(root), "env": []}
    return {"commands": {"check-ok": command("verify-ok"), "check-bad": command("verify-bad"),
                         "check-later": command("verify-later"), "nix-activate": command("verify-ok")},
            "workflow": {"verification": ["check-ok", "check-bad", "check-later"]},
            "vcs": {"integration_branch": "main", "default_branch": "main"},
            "tracker": TRACKER}


def ok_check(**over):
    return check(run={"command": "check-ok"}, **over)


class PassBase(unittest.TestCase):
    def setUp(self):
        self.world = world_with(self, "verify-ok", "verify-bad", "verify-later", "darwin-version")
        for tool, code in (("verify-ok", 0), ("verify-bad", 1), ("verify-later", 75)):
            self.world.respond(tool, [], exit=code, stdout=f"{tool} ran\n")
        for name, color in (("verification-failed", "B60205"), ("verification-follow-up", "FBCA04"),
                            ("owner-action", "D93F0B")):
            self.world.respond("gh", ["api", "-X", "POST", f"repos/{SLUG}/labels", "-f", f"name={name}",
                                      "-f", f"color={color}"])
        script = self.world.checkout / "scripts" / "check.sh"
        script.parent.mkdir()
        script.write_text(f"#!{sys.executable}\nimport sys\nsys.exit(0)\n", encoding="utf-8")
        script.chmod(0o755)
        self.project = vr.Project("octo/widgets", SLUG, self.world.checkout, self.world.checkout, TIP,
                                  bindings(self.world.checkout))
        self.workspaces = []
        patch = mock.patch.object(vx, "workspace", self.fake_workspace)
        patch.start()
        self.addCleanup(patch.stop)

    @contextlib.contextmanager
    def fake_workspace(self, root, commit):
        self.workspaces.append((root, commit))
        yield self.world.checkout

    def hold(self, *checks, association="OWNER", extra=(), fail_once=(), schedule=(), labels=("needs-verification",)):
        self.world.comment_store(SLUG, ISSUE, [stored_comment(10, hold(block(*checks)), association), *extra],
                                 labels=list(labels), fail_once=list(fail_once), schedule=list(schedule))

    def run_pass(self, host="mbp", report=False):
        return [entry for node in vr.list_held(SLUG)
                for entry in vr.pass_issue(self.project, host, node, Refs(), report=report)]

    def race(self, node, *hosts):
        errors = []

        def runner(host):
            try:
                vr.pass_issue(self.project, host, node, Refs())
            except Exception as error:  # surfaced below
                errors.append(error)
        threads = [threading.Thread(target=runner, args=(host,)) for host in hosts]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(60)
        self.assertEqual(errors, [])

    def mutations(self, since=0):
        """The forge writes since call `since`, bar the lease and the `verify-seen` report marker: a
        run's `verify-run` claim and its delete leave nothing behind, and the report marker is
        bookkeeping, so a pass that changes nothing still shows no other write."""
        def lease(argv):
            return (argv[2] == "POST" and ("agent:verify-run" in argv[-1] or "agent:verify-seen" in argv[-1])) or (
                argv[2] == "DELETE" and "/issues/comments/" in argv[3])
        return [argv for argv in self.world.argvs("gh")[since:] if "-X" in argv and not lease(argv)]

    def leases(self):
        """The `verify-run` claims standing now."""
        return self.markers("verify-run")

    def spawned(self, tool):
        return len([call for call in self.world.calls() if call["tool"] == tool])

    def markers(self, kind):
        found = [fm.parse(c) for c in self.world.stored()]
        return [m for m in found if m and m.kind == kind]

    def second_pass_is_silent(self):
        mark = len(self.world.argvs("gh"))
        self.run_pass()
        self.assertEqual(self.mutations(mark), [])


class PassTransitionsTest(PassBase):
    def test_pass_closes_once_in_a_recoverable_order_and_a_rerun_posts_nothing(self):
        self.hold(ok_check())
        self.assertEqual(self.run_pass(), [line(0, "AC1", "pass", "changed"), line(None, None, "closed", "verified")])
        self.assertEqual([m.fields["state"] for m in self.markers("verify-result")], ["pass"])
        closed, = self.markers("verify-closed")
        self.assertEqual(closed.body.split("\n")[1], "Verified: AC1.")
        self.assertEqual((self.world.issue()["state"], self.world.issue()["state_reason"]), ("closed", "completed"))
        self.assertEqual(self.world.issue()["labels"], [])
        issue = f"repos/{SLUG}/issues/{ISSUE}"
        finishing = [(a[2], a[3]) for a in self.mutations() if a[3] == issue or a[3].startswith(issue + "/labels/")]
        self.assertEqual(finishing, [("DELETE", issue + "/labels/verification-failed"), ("PATCH", issue),
                                     ("DELETE", issue + "/labels/needs-verification")])
        self.second_pass_is_silent()

    def test_fail_labels_before_recording_and_a_rerun_posts_nothing(self):
        self.hold(check(run={"command": "check-bad"}))
        self.run_pass()
        self.assertEqual([m.fields["state"] for m in self.markers("verify-result")], ["fail"])
        self.assertIn("verification-failed", self.world.issue()["labels"])
        self.assertEqual(self.world.issue()["state"], "open")
        posts = [a[3] for a in self.mutations() if a[2] == "POST"]
        self.assertLess(posts.index(f"repos/{SLUG}/issues/{ISSUE}/labels"),
                        posts.index(f"repos/{SLUG}/issues/{ISSUE}/comments"))
        self.second_pass_is_silent()
        self.assertEqual(self.spawned("verify-bad"), 2)

    def test_on_fail_ask_records_the_fail_without_a_label(self):
        self.hold(check(run={"command": "check-bad"}, on_fail="ask"))
        self.assertEqual(self.run_pass(), [line(0, "AC1", "fail", "fail_ask")])
        self.assertEqual([m.fields["state"] for m in self.markers("verify-result")], ["fail"])
        self.assertNotIn("verification-failed", self.world.issue()["labels"])
        self.assertEqual([a for a in self.mutations() if "verification-failed" in " ".join(a)], [])
        self.assertEqual(len([m for m in self.markers("owner-action") if m.fields["reason"] == "verify-decision"]), 1)
        self.second_pass_is_silent()

    def test_fail_then_pass_changes_state_and_clears_the_label(self):
        self.hold(check(run={"command": "check-bad"}))
        self.run_pass()
        self.world.respond("verify-bad", [], exit=0)
        self.run_pass()
        self.assertEqual([m.fields["state"] for m in self.markers("verify-result")], ["fail", "pass"])
        self.assertNotIn("verification-failed", self.world.issue()["labels"])
        self.assertEqual(self.world.issue()["state"], "closed")

    def test_observe_miss_closes_and_files_one_follow_up(self):
        self.hold(check(mode="observe", run={"command": "check-bad"}))
        self.run_pass()
        created, = self.world.issue()["created"]
        self.assertIn(f"#{ISSUE}", created["title"])
        self.assertEqual(created["labels"], ["verification-follow-up"])
        self.assertEqual(fm.parse({"id": 500, "body": created["body"], "updated_at": T0}).fields,
                         {"issue": str(ISSUE), "block": bkey(check(mode="observe", run={"command": "check-bad"})),
                          "check": "0"})
        result, = self.markers("verify-result")
        self.assertEqual((result.fields["state"], result.fields["followup"]), ("miss", "500"))
        self.assertEqual(len(self.markers("verify-followup")), 1)
        self.assertEqual(self.markers("verify-closed")[0].body.split("\n")[1],
                         "Verified: none. Observed below target: AC1 (follow-up #500).")
        self.assertEqual(self.world.issue()["state_reason"], "completed")
        self.second_pass_is_silent()
        self.assertEqual(len(self.world.issue()["created"]), 1)

    def test_observe_hit_is_verified(self):
        self.hold(ok_check(mode="observe"))
        self.run_pass()
        self.assertEqual(self.markers("verify-result")[0].fields["state"], "hit")
        self.assertEqual(self.markers("verify-closed")[0].body.split("\n")[1], "Verified: AC1.")

    def test_expiry_closes_as_not_verified(self):
        due = marker("verify-due", {"block": bkey(check(run={"command": "check-later"})), "check": "0",
                                    "host": "mbp"})
        self.hold(check(run={"command": "check-later"}),
                  extra=[stored_comment(11, due, at="2026-10-15T10:00:00Z")])
        with host_clock(WRONG, vf, fm):
            self.run_pass()
        self.assertEqual(self.spawned("verify-later"), 0)
        self.assertEqual(self.markers("verify-result")[0].fields["state"], "expired")
        self.assertEqual(self.markers("verify-closed")[0].body.split("\n")[1], "Not verified: AC1 expired.")
        self.assertEqual(self.world.issue()["state_reason"], "not_planned")
        self.assertIn("needs-verification", self.world.issue()["labels"])
        self.second_pass_is_silent()

    def test_not_yet_posts_one_due_marker(self):
        self.hold(check(run={"command": "check-later"}))
        self.assertEqual(self.run_pass()[0]["reason"], "not_yet")
        self.assertEqual(len(self.markers("verify-due")), 1)
        self.second_pass_is_silent()
        self.assertEqual(self.spawned("verify-later"), 2)
        self.assertEqual(self.markers("verify-result"), [])

    def test_two_hosts_close_only_when_both_checks_resolved(self):
        self.hold(ok_check(ac="AC1"), ok_check(ac="AC2", host="eleven-m5"))
        self.run_pass("mbp")
        self.assertEqual(self.markers("verify-closed"), [])
        self.run_pass("eleven-m5")
        self.assertEqual(self.markers("verify-closed")[0].body.split("\n")[1], "Verified: AC1, AC2.")

    def test_two_checks_of_one_ac_keep_separate_results(self):
        self.hold(ok_check(), ok_check(host="eleven-m5"))
        self.assertEqual(self.run_pass("mbp"), [line(0, "AC1", "pass", "changed"),
                                                line(1, "AC1", "pending", "not_this_host")])
        self.assertEqual(self.markers("verify-closed"), [])
        self.run_pass("eleven-m5")
        self.assertEqual([m.fields["check"] for m in self.markers("verify-result")], ["0", "1"])
        self.assertEqual(self.markers("verify-closed")[0].body.split("\n")[1], "Verified: AC1.")

    def test_each_run_form_checks_out_the_commit_it_was_checked_at(self):
        pinned = "d" * 40
        self.hold(ok_check(ac="AC1"), check(ac="AC2", run={"script": "scripts/check.sh"}),
                  check(ac="AC3", run={"script": "scripts/check.sh", "at": pinned}))
        self.run_pass()
        self.assertEqual([commit for _, commit in self.workspaces], [TIP, MERGE, pinned])

    def test_window_opening_posts_one_marker(self):
        self.world.respond_json("darwin-version", ["--json"], {"configurationRevision": REV})
        pushed(self.world, REV)
        ancestry(self.world, MERGE, REV, 0)
        self.hold(ok_check(when={"days_after": {"event": "deployed", "days": 7}}))
        self.assertEqual(self.run_pass()[0]["reason"], "window_opening")
        window, = self.markers("window-open")
        self.assertEqual(window.fields, {"event": "deployed", "merge": MERGE, "host": "mbp"})
        mark = len(self.world.argvs("gh"))
        self.assertEqual(self.run_pass()[0]["reason"], "window_not_open")
        self.assertEqual(self.mutations(mark), [])

    def test_a_replacement_block_inherits_the_window_and_posts_none(self):
        self.world.respond_json("darwin-version", ["--json"], {"configurationRevision": REV})
        pushed(self.world, REV)
        ancestry(self.world, MERGE, REV, 0)
        opened = marker("window-open", {"event": "deployed", "merge": MERGE, "host": "mbp"})
        self.hold(ok_check(when={"days_after": {"event": "deployed", "days": 7}}),
                  extra=[stored_comment(9, opened, at="2026-11-04T10:00:00Z")])
        self.assertEqual(self.run_pass()[0]["reason"], "window_not_open")
        self.assertEqual(len(self.markers("window-open")), 1)
        self.assertEqual(self.mutations(), [])

    def test_an_ended_pass_is_rechecked_and_closes_only_on_the_fresh_pass(self):
        self.hold(ok_check(), extra=[stored_comment(11, result(bkey(ok_check()), 0, "pass")),
                                     stored_comment(12, fm.end_body(11, "withdrawn"))])
        self.assertEqual(self.run_pass()[0], line(0, "AC1", "pass", "changed"))
        self.assertEqual(self.spawned("verify-ok"), 1)
        self.assertEqual(self.world.issue()["state"], "closed")
        self.assertEqual(len(self.markers("verify-result")), 2)

    def test_an_ended_pass_alone_never_closes(self):
        self.hold(check(run={"command": "check-later"}),
                  extra=[stored_comment(11, result(bkey(check(run={"command": "check-later"})), 0, "pass")),
                         stored_comment(12, fm.end_body(11, "withdrawn"))])
        self.assertEqual(self.run_pass()[0]["state"], "pending")
        self.assertEqual((self.world.issue()["state"], self.spawned("verify-later")), ("open", 1))

    def test_report_is_read_only(self):
        self.hold(ok_check())
        self.assertEqual(self.run_pass(report=True), [line(0, "AC1", "due", "due")])
        self.assertEqual((self.mutations(), self.spawned("verify-ok"), self.workspaces), ([], 0, []))

    def test_a_comment_id_beyond_a_32_bit_int_runs_and_closes_the_issue(self):
        big = 6_693_579_241  # this repository's ids: the block is read, and the run's own markers read back
        self.world.comment_store(SLUG, ISSUE, [stored_comment(big, hold(block(ok_check())))],
                                 next_id=big + 40, labels=["needs-verification"])
        self.assertEqual(self.run_pass(), [line(0, "AC1", "pass", "changed"), line(None, None, "closed", "verified")])
        result_marker, = self.markers("verify-result")
        self.assertEqual(result_marker.fields["block"], bkey(ok_check(), at=big))
        self.assertGreater(result_marker.comment_id, 2**32)
        self.assertEqual(self.world.issue()["state"], "closed")

    def test_a_closed_marker_finishes_an_interrupted_close(self):
        closed = marker("verify-closed", {"block": bkey(ok_check()), "outcome": "verified"}, "Verified: AC1.")
        self.hold(ok_check(), extra=[stored_comment(11, closed)])
        self.assertEqual(self.run_pass()[-1], line(None, None, "closed", "verified"))
        self.assertEqual(self.spawned("verify-ok"), 0)
        self.assertEqual((self.world.issue()["state"], self.world.issue()["labels"]), ("closed", []))
        self.assertEqual(len(self.world.stored()), 2)


class RecoveryTest(PassBase):
    def test_a_failed_close_is_finished_by_the_next_pass(self):
        self.hold(ok_check(), fail_once=["close"])
        self.assertEqual(self.run_pass()[-1]["reason"], "forge_error")
        self.assertEqual(self.world.issue()["state"], "open")
        self.assertIn("needs-verification", self.world.issue()["labels"])
        self.assertEqual(self.run_pass()[-1], line(None, None, "closed", "verified"))
        self.assertEqual((self.world.issue()["state"], self.world.issue()["labels"]), ("closed", []))
        self.assertEqual(len(self.markers("verify-closed")), 1)
        self.assertEqual(self.spawned("verify-ok"), 1)

    def test_a_failed_label_is_added_by_the_next_pass(self):
        self.hold(check(run={"command": "check-bad"}), fail_once=["add_label"])
        self.assertEqual(self.run_pass()[-1]["reason"], "forge_error")
        self.assertEqual(self.markers("verify-result"), [])
        self.run_pass()
        self.assertIn("verification-failed", self.world.issue()["labels"])
        self.assertEqual([m.fields["state"] for m in self.markers("verify-result")], ["fail"])

    def test_a_failed_follow_up_edit_files_no_second_issue(self):
        self.hold(check(mode="observe", run={"command": "check-bad"}), fail_once=["edit"])
        self.assertEqual(self.run_pass()[-1]["reason"], "forge_error")
        self.assertEqual(len(self.world.issue()["created"]), 1)
        self.assertNotIn("followup", self.markers("verify-result")[0].fields)
        self.run_pass()
        self.assertEqual(len(self.world.issue()["created"]), 1)
        self.assertEqual(self.markers("verify-result")[0].fields["followup"], "500")
        self.assertEqual(self.world.issue()["state"], "closed")
        self.assertEqual(self.spawned("verify-bad"), 1)

    def test_two_hosts_recovering_one_follow_up_file_one_issue(self):
        miss = result(bkey(check(mode="observe", host="any", run={"command": "check-bad"})), 0, "miss")
        self.hold(check(mode="observe", host="any", run={"command": "check-bad"}),
                  extra=[stored_comment(11, miss)],
                  schedule=["post:agent:verify-followup", "post:agent:verify-followup", "list", "list"])
        node, = vr.list_held(SLUG)
        self.race(node, "mbp", "anis-desktop")
        self.assertEqual(len(self.world.issue()["created"]), 1)
        self.assertEqual(len(self.markers("verify-followup")), 1)
        self.assertEqual(self.markers("verify-result")[0].fields["followup"], "500")
        self.assertEqual(self.spawned("verify-bad"), 0)


class RunnerTrustTest(PassBase):
    """The runner reads back only OWNER and MEMBER markers, so it must itself be one (finding 1)."""

    def setUp(self):
        super().setUp()
        self.hold(ok_check())

    def identity(self, login, owner="octo", kind="User", membership=None):
        self.world.respond_json("gh", ["api", "user"], {"login": login})
        self.world.respond_json("gh", ["api", f"repos/{SLUG}"], {"owner": {"login": owner, "type": kind}})
        path = ["api", f"user/memberships/orgs/{owner}"]
        if membership is None:
            self.world.not_found("gh", path)
        else:
            self.world.respond_json("gh", path, {"state": membership})

    def pass_repo(self, **kwargs):
        return vr.pass_repo(self.project, "mbp", Refs(), **kwargs)

    def assert_refused(self):
        self.assertEqual(self.pass_repo(), [{"repo": SLUG, "issue": None, "check": None, "ac": None,
                                             "state": "skipped", "reason": "runner_untrusted"}])
        self.assertEqual((self.mutations(), self.spawned("verify-ok"), self.workspaces), ([], 0, []))

    def test_a_collaborator_account_on_a_user_owned_repository_is_refused_before_any_write(self):
        self.identity("helper")
        self.assert_refused()

    def test_the_repository_owner_runs(self):
        self.identity("Octo")
        self.assertIn(line(None, None, "closed", "verified"), self.pass_repo())

    def test_an_active_organization_member_runs(self):
        self.identity("helper", owner="acme", kind="Organization", membership="active")
        self.assertIn(line(None, None, "closed", "verified"), self.pass_repo())

    def test_a_pending_or_absent_organization_membership_is_refused(self):
        self.identity("helper", owner="acme", kind="Organization", membership="pending")
        self.assert_refused()
        self.identity("helper", owner="acme", kind="Organization", membership=None)
        self.assert_refused()

    def test_a_report_writes_nothing_and_needs_no_identity(self):
        self.assertEqual(self.pass_repo(report=True), [line(0, "AC1", "due", "due")])
        self.assertNotIn(["api", "user"], self.world.argvs("gh"))

    def test_an_unreadable_identity_is_a_forge_error(self):
        self.world.respond_json("gh", ["api", "user"], {"name": "no login"})
        with self.assertRaises(fm.ForgeError):
            self.pass_repo()


class SameHostRecoveryTest(PassBase):
    def test_two_runs_on_the_claims_own_host_leave_one_open_follow_up(self):
        observe = check(mode="observe", host="any", run={"command": "check-bad"})
        key = {"block": bkey(observe), "check": "0"}
        self.hold(observe, extra=[stored_comment(11, result(key["block"], 0, "miss")),
                                  stored_comment(12, marker("verify-followup", {**key, "host": "mbp"}))],
                  schedule=["list_issues", "list_issues", "create_issue", "create_issue",
                            "list_issues", "list_issues"])
        node, = vr.list_held(SLUG)
        self.race(node, "mbp", "mbp")
        created = self.world.issue()["created"]
        self.assertEqual([(c["number"], c["state"]) for c in created], [(500, "open"), (501, "closed")])
        self.assertEqual(self.markers("verify-result")[0].fields["followup"], "500")
        self.assertEqual(self.world.issue()["state"], "closed")


class NeverRunTest(PassBase):
    def assert_never_run(self, reason, *checks, association="OWNER"):
        self.hold(*checks, association=association)
        lines = self.run_pass()
        self.assertEqual(lines[0]["reason"], reason)
        self.assertEqual((self.spawned("verify-ok"), self.workspaces, self.markers("verify-result")), (0, [], []))

    def test_non_member_block(self):
        self.assert_never_run("no_block", ok_check(), association="CONTRIBUTOR")

    def test_inline_code_run(self):
        self.assert_never_run("block_invalid", check(run={"tool": "python3", "args": ["-c", "print(1)"]}))

    def test_live_and_paid(self):
        self.assert_never_run("owner_asked", ok_check(effects="live"))
        self.assert_never_run("owner_asked", ok_check(effects="paid"))

    def test_ask_and_act(self):
        self.assert_never_run("owner_asked", check(kind="human", reason="senses", run={"ask": "Is it bright?"}))
        self.assert_never_run("owner_asked", check(kind="human", reason="hands",
                                                   run={"act": "Plug it in", "then": {"command": "check-ok"}}))

    def test_a_block_naming_nix_activate_is_not_run(self):
        self.assert_never_run("command_not_verification", check(run={"command": "nix-activate"}))

    def test_another_hosts_check(self):
        self.assert_never_run("not_this_host", ok_check(host="eleven-m5"))


class ForgedMarkerTest(PassBase):
    """fagenorn/nix-config is public: a marker-shaped comment by any other author changes nothing (P3)."""

    def test_a_forged_closed_marker_neither_wins_nor_blocks_the_close(self):
        forged = marker("verify-closed", {"block": bkey(ok_check()), "outcome": "verified"}, "Verified: AC1.")
        self.hold(ok_check(), extra=[stored_comment(11, forged, "NONE")])
        self.assertEqual(self.run_pass()[-1], line(None, None, "closed", "verified"))
        self.assertEqual(self.spawned("verify-ok"), 1)
        self.assertEqual(self.world.issue()["state"], "closed")
        self.assertEqual(len(self.markers("verify-closed")), 2)  # the forged one and the runner's, never deleted

    def test_a_forged_run_marker_does_not_take_a_shared_check(self):
        forged = marker("verify-run", {"block": bkey(ok_check(host="any")), "check": "0", "host": "eleven-m5"})
        self.hold(ok_check(host="any"), extra=[stored_comment(11, forged, "NONE")])
        self.assertEqual(self.run_pass()[0], line(0, "AC1", "pass", "changed"))
        self.second_pass_is_silent()

    def test_a_forged_result_never_counts(self):
        self.hold(check(run={"command": "check-bad"}),
                  extra=[stored_comment(11, result(bkey(check(run={"command": "check-bad"})), 0, "pass"), "NONE")])
        self.run_pass()
        self.assertEqual(self.world.issue()["state"], "open")
        self.assertIn("verification-failed", self.world.issue()["labels"])


class StaleVersionTest(PassBase):
    """A result belongs to one version of the block: editing or reordering its checks starts afresh (CR-1)."""

    def test_a_pass_of_an_earlier_version_of_the_block_neither_closes_nor_counts(self):
        earlier = bkey(ok_check())
        edited = check(run={"command": "check-bad"})  # same comment, same index, a different check
        self.hold(edited, extra=[stored_comment(11, result(earlier, 0, "pass"))])
        self.assertEqual(self.run_pass()[0], line(0, "AC1", "fail", "changed"))
        self.assertEqual(self.spawned("verify-bad"), 1)
        self.assertEqual((self.world.issue()["state"], self.markers("verify-closed")), ("open", []))
        self.assertIn("verification-failed", self.world.issue()["labels"])

    def test_the_results_recorded_by_a_pass_carry_the_version(self):
        self.hold(ok_check())
        self.run_pass()
        result_marker, = self.markers("verify-result")
        self.assertEqual(result_marker.fields["block"], bkey(ok_check()))
        self.assertEqual(self.markers("verify-closed")[0].fields["block"], bkey(ok_check()))


class RaceTest(PassBase):
    def test_two_hosts_racing_on_an_any_check_run_it_once(self):
        runs = f"repos/{SLUG}/actions/runs?branch=main&head_sha={MERGE}&per_page=100"
        self.world.respond_json("gh", ["api", runs], {"workflow_runs": [
            {"name": "ci.yaml", "path": "x/ci.yaml", "status": "completed", "conclusion": "success"}]})
        probe = {"probe": "ci_run_includes", "workflow": "ci.yaml", "branch": "main", "sha": MERGE}
        self.hold(check(host="any", run=probe),
                  schedule=["post:agent:verify-run", "post:agent:verify-run", "list", "list"])
        node, = vr.list_held(SLUG)
        self.race(node, "mbp", "anis-desktop")
        self.assertEqual(len([a for a in self.world.argvs("gh") if a == ["api", runs]]), 1)
        self.assertEqual(self.leases(), [])  # the winner released its lease
        self.assertEqual(len(self.markers("verify-result")), 1)
        self.assertEqual(len(self.markers("verify-closed")), 1)
        self.assertEqual(self.world.issue()["state"], "closed")



class LeaseTest(PassBase):
    """One run of a check at a time, whatever the host: a same-host retry is not exempt (COR-001)."""

    def claim(self, cid, at=T0, host="mbp"):
        return stored_comment(cid, marker("verify-run", {"block": bkey(ok_check()), "check": "0", "host": host}),
                              at=at)

    def test_two_overlapping_runs_of_one_host_run_the_check_once(self):
        self.hold(ok_check(), schedule=["post:agent:verify-run", "post:agent:verify-run", "list", "list"])
        node, = vr.list_held(SLUG)
        self.race(node, "mbp", "mbp")
        self.assertEqual(self.spawned("verify-ok"), 1)
        self.assertEqual(len(self.markers("verify-result")), 1)
        self.assertEqual(self.leases(), [])
        self.assertEqual(self.world.issue()["state"], "closed")

    def test_a_standing_lease_keeps_every_other_run_off_the_check_even_the_same_host(self):
        self.hold(ok_check(), extra=[self.claim(11, at="2026-11-06T09:45:00Z")])
        self.assertEqual(self.run_pass(), [line(0, "AC1", "pending", "lost_contest")])
        self.assertEqual((self.spawned("verify-ok"), self.markers("verify-result"), self.workspaces), (0, [], []))
        self.assertEqual([m.comment_id for m in self.leases()], [11])

    def test_the_claim_of_a_run_that_died_is_ended_and_the_check_runs(self):
        self.hold(ok_check(), extra=[self.claim(11, at="2026-11-06T09:00:00Z")])
        self.assertEqual(self.run_pass(), [line(0, "AC1", "pass", "changed"), line(None, None, "closed", "verified")])
        self.assertEqual([m.fields["of"] for m in self.markers("end")], ["11"])
        self.assertEqual(self.spawned("verify-ok"), 1)

    def test_the_lease_is_released_whatever_the_outcome(self):
        for held in (ok_check(), check(run={"command": "check-bad"}), check(run={"command": "check-later"})):
            self.hold(held)
            self.run_pass()
            self.assertEqual(self.leases(), [])

    def test_a_run_that_missed_another_runs_result_does_not_run_the_check_again(self):
        self.hold(ok_check())
        stale, = vr.list_held(SLUG)  # listed before the first run recorded anything
        self.run_pass()
        self.assertEqual(self.spawned("verify-ok"), 1)
        lines = vr.pass_issue(self.project, "mbp", stale, Refs())
        self.assertEqual(lines, [line(0, "AC1", "pending", "lost_contest")])
        self.assertEqual((self.spawned("verify-ok"), len(self.markers("verify-result"))), (1, 1))
        self.assertEqual(self.leases(), [])


class BlockReplacedTest(PassBase):
    """An owner who replaces the block while a check runs has new checks nobody has run (COR-002)."""

    def test_a_block_replaced_during_the_run_is_not_closed_on_and_is_run_next_pass(self):
        self.hold(ok_check())
        replacement = block(check(ac="AC2", run={"command": "check-ok"}))
        real = vx.execute

        def replace_then_run(argv, cwd):
            self.world.append_comment(stored_comment(11, hold(replacement)))
            return real(argv, cwd)

        with mock.patch.object(vx, "execute", replace_then_run):
            lines = self.run_pass()
        self.assertEqual(lines, [line(0, "AC1", "pass", "changed"), line(None, None, "skipped", "block_changed")])
        issue = self.world.issue()
        self.assertEqual(issue["state"], "open")
        self.assertIn("needs-verification", issue["labels"])
        self.assertEqual(self.run_pass(), [line(0, "AC2", "pass", "changed"), line(None, None, "closed", "verified")])
        self.assertEqual(self.spawned("verify-ok"), 2)
        self.assertEqual(self.world.issue()["state"], "closed")


class DuplicateFollowUpTest(PassBase):
    """A duplicate follow-up left open by an interrupted close is closed by a later pass (COR-003)."""

    def test_the_next_pass_closes_the_higher_numbered_duplicate_before_recording_the_follow_up(self):
        observe = check(mode="observe", run={"command": "check-bad"})
        key = bkey(observe)
        tag = {"issue": str(ISSUE), "block": key, "check": "0"}

        def filed(number):
            return {"number": number, "title": "Follow-up", "body": fm.render(vi.FOLLOWUP_OF, tag, "Follow-up."),
                    "labels": ["verification-follow-up"], "author_association": "OWNER", "updated_at": T0,
                    "state": "open", "state_reason": None}

        self.world.comment_store(
            SLUG, ISSUE,
            [stored_comment(10, hold(block(observe))), stored_comment(11, result(key, 0, "miss")),
             stored_comment(12, marker(vi.FOLLOWUP, {"block": key, "check": "0", "host": "mbp"}))],
            labels=["needs-verification"], created=[filed(500), filed(501)], fail_once=["close"])
        self.assertEqual(self.run_pass()[-1], line(None, None, "skipped", "forge_error"))
        self.assertEqual([c["state"] for c in self.world.issue()["created"]], ["open", "open"])
        self.assertNotIn("followup", self.markers("verify-result")[0].fields)
        self.assertEqual(self.world.issue()["state"], "open")
        self.assertEqual(self.run_pass()[-1], line(None, None, "closed", "verified"))
        self.assertEqual([(c["number"], c["state"]) for c in self.world.issue()["created"]],
                         [(500, "open"), (501, "closed")])
        self.assertEqual(self.markers("verify-result")[0].fields["followup"], "500")
        self.assertEqual(self.world.issue()["state"], "closed")


class PinnedReferencesTest(GitRepos):
    """The lint's lookups for the runner read origin's commits, never the lagging checkout (P17)."""

    def setUp(self):
        super().setUp()
        (self.root / "README").write_text("x\n")
        self.base = self.commit("base")
        self.git(self.root, "push", "-q", "origin", "HEAD:main")
        script = self.root / "scripts" / "check.sh"
        script.parent.mkdir()
        script.write_text("#!/bin/sh\nexit 0\n")
        script.chmod(0o755)
        (self.root / "scripts" / "link.sh").symlink_to("check.sh")
        self.merge = self.commit("add the check")
        self.lag(self.base)
        self.refs = verify_pending.PinnedReferences(self.root, {"check-ok"})

    def test_a_merge_the_checkout_lacks_is_fetched_before_the_lookup(self):
        self.assertEqual(self.refs.script("scripts/check.sh", self.merge), ("present", "present"))
        self.assertEqual(self.refs.script("scripts/link.sh", self.merge), ("present", "absent"))
        held = {"v": 1, "merge": self.merge, "checks": [check(run={"script": "scripts/check.sh"})]}
        self.assertTrue(lint_block(held, refs=self.refs)["ok"])
        self.assertFalse((self.root / "scripts").exists())

    def test_the_flake_is_read_at_the_merge_after_fetching_it(self):
        self.assertEqual(self.refs.flake(self.merge), ("present", "absent"))
        self.assertEqual(self.refs.flake("f" * 40), ("absent", "unknown"))

    def test_commands_come_from_the_snapshot(self):
        self.assertEqual((self.refs.command("check-ok"), self.refs.command("nix-activate")), ("present", "absent"))

    def test_an_unknown_commit_is_absent(self):
        self.assertEqual(self.refs.script("scripts/check.sh", "f" * 40)[0], "absent")

    def test_no_forge_token_reaches_a_git_child_of_a_lookup(self):
        with child_environments() as seen:
            self.refs.script("scripts/check.sh", self.merge)
            self.refs.flake(self.merge)
            self.refs.flake("f" * 40)
        assert_tokenless(self, seen)


class CommandTest(PassBase):
    def setUp(self):
        super().setUp()
        self.world.respond("gh", ["auth", "status"], stdout="Logged in\n")
        self.world.respond_json("gh", ["api", "user"], {"login": "octo"})
        self.world.respond_json("gh", ["api", f"repos/{SLUG}"], {"owner": {"login": "octo", "type": "User"}})
        home = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(lambda: shutil.rmtree(home, ignore_errors=True))
        (home / ".agents" / "share").mkdir(parents=True)
        shutil.copy(MANIFEST, home / ".agents" / "share" / "platform-manifest.json")
        self.root = home / "project"
        shutil.copytree(FIXTURE, self.root)
        contract_path = self.root / ".agents" / "project.json"
        contract = json.loads(contract_path.read_text("utf-8"))
        contract["bindings"]["tracker"].update({"kind": "github", "repo_slug": SLUG})
        contract["bindings"]["commands"]["check-ok"] = {"argv": ["verify-ok"], "cwd": ".", "env": []}
        contract["bindings"]["commands"]["test"]["argv"] = ["verify-ok"]  # PATH is the fake bin alone
        contract["bindings"]["workflow"]["verification"] = ["test", "check-ok"]
        contract_path.write_text(json.dumps(contract, indent=2), encoding="utf-8")
        self.registry = home / ".agents" / "state" / "fleet" / "registry.json"
        self.registry.parent.mkdir(parents=True)
        self.register({"project_id": "octo/widgets", "root": str(self.root)})
        patch = mock.patch.dict(os.environ, {"HOME": str(home)})
        patch.start()
        self.addCleanup(patch.stop)
        self.sources = []
        patch = mock.patch.object(vx, "project_source", self.fake_source)
        patch.start()
        self.addCleanup(patch.stop)

    @contextlib.contextmanager
    def fake_source(self, entry):
        """The contract as origin's integration branch holds it: here, the copied fixture at TIP."""
        self.sources.append(entry["project_id"])
        try:
            snapshot = resolve(entry["root"])
        except Exception as error:  # ContractError: the real seam raises SourceError
            raise vx.SourceError(str(error)) from None
        yield vx.Source(snapshot, Path(snapshot["project"]["root"]), TIP, "main")

    def register(self, *entries):
        self.registry.write_text(json.dumps({"schema_version": 1, "projects": list(entries)}), encoding="utf-8")

    def cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = verify_pending.main(list(argv))
            except SystemExit as exit:
                code = exit.code
        return code, [json.loads(entry) for entry in out.getvalue().splitlines()], err.getvalue()

    def test_demo_one_run_closes_the_issue_and_a_second_posts_nothing(self):
        self.hold(ok_check())
        code, lines, _ = self.cli("run", "--host", "mbp")
        self.assertEqual(code, 0)
        self.assertIn(line(None, None, "closed", "verified"), lines)
        self.assertEqual(self.markers("verify-closed")[0].body.split("\n")[1], "Verified: AC1.")
        self.assertEqual(self.workspaces, [(self.root, TIP)])
        mark = len(self.world.argvs("gh"))
        self.assertEqual(self.cli("run", "--host", "mbp")[:2], (0, []))
        self.assertEqual(self.mutations(mark), [])

    def test_a_runner_the_forge_would_not_trust_is_refused_and_exits_1(self):
        self.world.respond_json("gh", ["api", "user"], {"login": "helper"})
        self.hold(ok_check())
        code, lines, err = self.cli("run", "--host", "mbp")
        self.assertEqual((code, lines), (1, [{"repo": SLUG, "issue": None, "check": None, "ac": None,
                                              "state": "skipped", "reason": "runner_untrusted"}]))
        self.assertIn(SLUG, err)
        self.assertEqual((self.mutations(), self.spawned("verify-ok")), ([], 0))

    def test_no_forge_credential_exits_0_quietly(self):
        self.world.respond("gh", ["auth", "status"], exit=1, stderr="You are not logged into any GitHub hosts")
        self.hold(ok_check())
        self.assertEqual(self.cli("run", "--host", "mbp"), (0, [], "verify-pending: no-forge-credential\n"))
        self.assertEqual(self.world.argvs("gh"), [["auth", "status"]])
        self.assertEqual(self.sources, [])

    def test_usage_errors_exit_2(self):
        self.hold(ok_check())
        self.assertEqual(self.cli("run", "--host", "MBP!")[0], 2)
        self.assertEqual(self.cli("run", "--host", "mbp", "--repo", "other/repo")[0], 2)
        self.assertEqual(self.spawned("verify-ok"), 0)

    def test_report_prints_due_checks_and_writes_nothing(self):
        self.hold(ok_check(), ok_check(ac="AC2", host="eleven-m5"))
        code, lines, _ = self.cli("run", "--host", "mbp", "--repo", SLUG, "--report")
        self.assertEqual(code, 0)
        self.assertEqual([(entry["check"], entry["state"], entry["reason"]) for entry in lines],
                         [(0, "due", "due"), (1, "pending", "not_this_host")])
        self.assertEqual((self.mutations(), self.spawned("verify-ok")), ([], 0))

    def test_issue_alone_filters_every_project_as_the_issue_writes_it(self):
        self.hold(ok_check())
        self.assertEqual(self.cli("run", "--host", "mbp", "--issue", "8")[:2], (0, []))
        self.assertEqual(self.spawned("verify-ok"), 0)
        code, lines, _ = self.cli("run", "--host", "mbp", "--issue", str(ISSUE))
        self.assertEqual(code, 0)
        self.assertIn(line(None, None, "closed", "verified"), lines)

    def test_issue_with_repo(self):
        self.hold(ok_check())
        self.assertEqual(self.cli("run", "--host", "mbp", "--repo", SLUG, "--issue", "8")[:2], (0, []))
        self.assertEqual(self.spawned("verify-ok"), 0)

    def test_forge_error_is_reported_and_exits_1(self):
        owner, name = SLUG.split("/")
        self.world.respond("gh", ["api", "graphql", "-f", f"query={vr.QUERY}", "-f", f"owner={owner}",
                                  "-f", f"name={name}"], exit=1, stderr="gh: Server Error (HTTP 502)")
        code, lines, _ = self.cli("run", "--host", "mbp")
        self.assertEqual((code, lines), (1, [{"repo": SLUG, "issue": None, "check": None, "ac": None,
                                              "state": "skipped", "reason": "forge_error"}]))

    def test_an_unresolvable_project_is_reported(self):
        empty = self.root.parent / "empty"
        empty.mkdir()
        self.register({"project_id": "a/broken", "root": str(empty)})
        self.assertEqual(self.cli("run", "--host", "mbp")[:2], (0, [{"repo": "a/broken", "issue": None, "check": None,
                                                                    "ac": None, "state": "skipped",
                                                                    "reason": "project_unresolved"}]))


class RecipeTest(unittest.TestCase):
    def test_just_verify_runs_the_command_and_the_suite_runs_this_file(self):
        lines = (REPO_ROOT / "justfile").read_text(encoding="utf-8").splitlines()
        start = lines.index("verify host *args:")
        self.assertEqual(lines[start + 1],
                         '  PYTHONPATH="{{agent_tools_path}}" python3 -m agent_tools.verify_pending run --host {{host}} {{args}}')
        self.assertIn("    tests/test_verify_pending.py \\", lines)
