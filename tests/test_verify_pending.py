"""verify-pending run (issue 630): selection, conditions, the run gate, passes and the command."""
import contextlib
import dataclasses
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from agent_tools import forge_markers as fm
from agent_tools import verify_exec as vx
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


HERMETIC_GIT = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
                "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
                "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}
REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = REPO_ROOT / "home/common/agent-skills/evals/fixture-repo"


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

    def test_an_unresolvable_contract_at_origin_is_a_source_error(self):
        self.git(self.root, "rm", "-q", ".agents/project.json")
        self.commit("drop the contract")
        self.git(self.root, "push", "-q", "--force", "origin", "HEAD:main")
        with self.assertRaises(vx.SourceError):
            with vx.project_source(self.entry):
                pass


if __name__ == "__main__":
    unittest.main()
