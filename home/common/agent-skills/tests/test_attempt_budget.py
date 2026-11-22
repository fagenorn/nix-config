"""The `attempt-budget` command reads the tracker and records the history (issue 1466).

Every case drives `agent_tools.delivery.attempt_budget` through its public names,
`main` and `tracker_attempts`, against a fake forge: the pull listing and the issue
comments answer from a world built here, and the forge time is fixed.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from agent_tools.claims import forge_markers
from agent_tools.delivery import attempt_budget
from agent_tools.project_contract import attempt_history, resolve_project
from agent_tools.system import forge_api
from agent_tools.system.forge_api import ForgeError

from .test_resolve_project import InProcessTestCase, REPO_ROOT, source_contract
from .test_resolve_schema_three import make_schema_three_root, schema_three_contract

TIER = "fast"

T = datetime(2026, 11, 22, 12, tzinfo=timezone.utc)
SLUG = "fagenorn/nix-config"
BASE = datetime(2026, 10, 1, tzinfo=timezone.utc)
MISSING = object()


def stamp(moment: datetime) -> str:
    return attempt_history.stamp(moment)


def make_pull(number, head_ref, merged_at, *, updated_at=None, base_ref="main",
              base_repo=SLUG, head_repo=SLUG):
    """A closed pull request as the pulls listing returns it."""
    head = {"ref": head_ref}
    if head_repo is not MISSING:
        head["repo"] = None if head_repo is None else {"full_name": head_repo}
    return {
        "number": number,
        "merged_at": None if merged_at is None else stamp(merged_at),
        "updated_at": stamp(updated_at or merged_at or T),
        "base": {"ref": base_ref, "repo": {"full_name": base_repo}},
        "head": head,
    }


def claim_comment(comment_id, issue, created, *, branch=None, marker_issue=None):
    fields = {"issue": str(marker_issue or issue), "holder": "h/b"}
    if branch is not None:
        fields["branch"] = branch
    return {"id": comment_id, "created_at": stamp(created), "updated_at": stamp(created),
            "body": forge_markers.render("claim", fields, "Claimed by h/b.")}


def end_comment(comment_id, of, created):
    return {"id": comment_id, "created_at": stamp(created), "updated_at": stamp(created),
            "body": forge_markers.end_body(of, "done")}


def twenty_world(*, repo=SLUG):
    """Issues 1..20, issue i claimed `i * 3600 + 30` seconds before its merge."""
    pages, comments = [[]], {}
    for i in range(20, 0, -1):
        merged = BASE + timedelta(hours=i)
        pages[0].append(make_pull(100 + i, f"issue-{i}-x", merged, base_repo=repo, head_repo=repo))
        comments[i] = [claim_comment(1000 + i, i, merged - timedelta(seconds=i * 3600 + 30))]
    return {"pages": pages, "comments": comments}


class World:
    """The fake forge: pull pages and issue comments, recording each page path read."""

    def __init__(self, data=None):
        data = data or {"pages": [[]], "comments": {}}
        self.pages = data["pages"]
        self.comments = data["comments"]
        self.paths = []

    def api_get(self, path, allow=()):
        self.paths.append(path)
        number = int(re.search(r"&page=(\d+)", path).group(1))
        return self.pages[number - 1] if number <= len(self.pages) else []

    def list_comments(self, slug, issue):
        return self.comments.get(issue, [])

    def page_numbers(self):
        return [int(re.search(r"&page=(\d+)", p).group(1)) for p in self.paths]

    @contextlib.contextmanager
    def serving(self, now=T):
        with mock.patch.object(forge_api, "api_get", self.api_get), \
                mock.patch.object(forge_markers, "list_comments", self.list_comments), \
                mock.patch.object(forge_api, "server_now", lambda: now):
            yield


class AttemptBudgetCase(InProcessTestCase):
    def setUp(self):
        super().setUp()
        self.root = make_schema_three_root(schema_three_contract())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def run_main(self, argv, world, now=T):
        out = io.StringIO()
        with world.serving(now), contextlib.redirect_stdout(out):
            code = attempt_budget.main(argv)
        return code, json.loads(out.getvalue())

    def command(self, name, world, now=T, root=None):
        return self.run_main([name, "--repo-root", str(root or self.root)], world, now)

    def history(self):
        path = attempt_history.history_path(self.root)
        return json.loads(path.read_text("utf-8"))["attempts"]

    def tracker(self, world, now=T):
        head = attempt_budget.branch_issue("issue-<num>-<slug>")
        with world.serving(now):
            return attempt_budget.tracker_attempts(SLUG, "main", head, now)


class CommandTest(AttemptBudgetCase):
    def test_record_prints_the_twenty_durations_and_the_resolver_reports_the_same_budget(self):
        code, result = self.command("record", World(twenty_world()))
        self.assertEqual(code, 0)
        self.assertEqual(result["command"], "record")
        self.assertEqual(result["budget_minutes"], 1621)
        self.assertEqual(result["percentile_90_minutes"], 1080.5)
        self.assertEqual(len(result["attempts"]), 20)
        for attempt in result["attempts"]:
            self.assertEqual(attempt["duration_minutes"],
                             round((attempt["issue"] * 3600 + 30) / 60, 1))
        self.assertEqual(result["history"], str(attempt_history.history_path(self.root)))
        snapshot = resolve_project.resolve(str(self.root))
        self.assertEqual(
            snapshot["bindings"]["workflow"]["orchestration"]["attempt_budget_minutes"], 1621)

    def test_the_output_has_exactly_the_documented_members(self):
        _, result = self.command("report", World(twenty_world()))
        self.assertEqual(set(result), {
            "command", "repo", "integration_branch", "recorded_at", "budget_minutes", "basis",
            "percentile_90_minutes", "attempts", "history"})
        self.assertEqual(result["repo"], SLUG)
        self.assertEqual(result["integration_branch"], "main")
        self.assertEqual(result["recorded_at"], stamp(T))
        self.assertEqual(set(result["attempts"][0]),
                         {"issue", "pull", "claimed_at", "merged_at", "duration_minutes"})
        self.assertEqual(result["attempts"][0]["issue"], 20)

    def test_report_prints_the_same_and_writes_nothing(self):
        code, result = self.command("report", World(twenty_world()))
        self.assertEqual(code, 0)
        self.assertEqual(result["budget_minutes"], 1621)
        self.assertIsNone(result["history"])
        self.assertFalse(attempt_history.history_path(self.root).exists())

    def test_a_fallback_basis_has_no_percentile(self):
        world = World({"pages": [[make_pull(101, "issue-1-x", BASE)]],
                       "comments": {1: [claim_comment(11, 1, BASE - timedelta(hours=1))]}})
        code, result = self.command("report", world)
        self.assertEqual(code, 0)
        self.assertEqual(result["budget_minutes"], 240)
        self.assertIsNone(result["percentile_90_minutes"])
        self.assertEqual(result["basis"]["reason"], "too_few")

    def test_a_renamed_repository_still_counts_its_deliveries(self):
        code, result = self.command("report", World(twenty_world(repo="Fagenorn/Renamed-Config")))
        self.assertEqual(code, 0)
        self.assertEqual(result["budget_minutes"], 1621)

    def test_a_forge_error_exits_one_and_writes_nothing(self):
        world = World(twenty_world())
        with mock.patch.object(world, "api_get", side_effect=ForgeError("gh_failed", "boom")):
            code, result = self.command("record", world)
        self.assertEqual(code, 1)
        self.assertEqual(result["error"]["code"], "gh_failed")
        self.assertEqual(result["command"], "record")
        self.assertFalse(attempt_history.history_path(self.root).exists())

    def test_a_write_failure_exits_one(self):
        with mock.patch.object(attempt_budget.attempt_history, "write_history",
                               side_effect=OSError("disk full")):
            code, result = self.command("record", World(twenty_world()))
        self.assertEqual(code, 1)
        self.assertEqual(result["error"]["code"], "write_failed")

    def test_a_root_without_a_git_directory_prints_a_write_failure(self):
        root = make_schema_three_root(source_contract())
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        shutil.rmtree(root / ".git")
        code, result = self.command("record", World(twenty_world()), root=root)
        self.assertEqual(code, 1)
        self.assertEqual(result["command"], "record")
        self.assertEqual(result["error"]["code"], "write_failed")

    def test_a_pattern_without_both_placeholders_is_unsupported(self):
        contract = source_contract()
        contract["bindings"]["vcs"]["branch_pattern"] = "issue-<num>"
        root = make_schema_three_root(contract)
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        code, result = self.command("report", World(), root=root)
        self.assertEqual(code, 2)
        self.assertEqual(result["error"]["code"], "branch_pattern_unsupported")

    def test_the_branch_pattern_comes_from_the_snapshot(self):
        contract = source_contract()
        contract["bindings"]["vcs"]["branch_pattern"] = "fix/<num>-<slug>"
        root = make_schema_three_root(contract)
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        world = World({
            "pages": [[make_pull(107, "fix/7-x", BASE + timedelta(hours=2)),
                       make_pull(108, "issue-8-x", BASE + timedelta(hours=3))]],
            "comments": {7: [claim_comment(1, 7, BASE)], 8: [claim_comment(2, 8, BASE)]}})
        code, _ = self.command("record", world, root=root)
        self.assertEqual(code, 0)
        path = attempt_history.history_path(root)
        issues = [a["issue"] for a in json.loads(path.read_text("utf-8"))["attempts"]]
        self.assertEqual(issues, [7])

    def test_a_refused_project_exits_two_with_the_resolvers_error(self):
        unsupported = schema_three_contract()
        unsupported["schema_version"] = 4
        for name, root in (
            ("no remote", make_schema_three_root(schema_three_contract(), remote=None)),
            ("unsupported schema", make_schema_three_root(unsupported)),
        ):
            self.addCleanup(shutil.rmtree, root, ignore_errors=True)
            with self.subTest(name):
                with self.assertRaises(resolve_project.ContractError) as caught:
                    resolve_project.resolve(str(root))
                raised = caught.exception
                code, result = self.command("report", World(), root=root)
                error = result["error"]
                self.assertEqual(code, 2)
                self.assertEqual(error["code"], raised.code)
                self.assertEqual(error["repair_id"], raised.repair_id)
                self.assertEqual(error["violations"], raised.violations)
                if name == "unsupported schema":
                    self.assertEqual(error["code"], "unsupported_schema")
                    self.assertEqual(error["reason_code"], raised.reason_code)
                else:
                    self.assertNotIn("reason_code", error)


class BranchIssueTest(unittest.TestCase):
    def test_the_pattern_matches_any_issue_and_captures_its_number(self):
        head = attempt_budget.branch_issue("issue-<num>-<slug>")
        self.assertEqual(head.fullmatch("issue-1466-a-b").group(1), "1466")
        self.assertIsNone(head.fullmatch("release-1"))
        self.assertIsNone(head.fullmatch("xissue-1-a"))

    def test_other_parts_are_matched_literally(self):
        head = attempt_budget.branch_issue("fix/<num>.<slug>")
        self.assertIsNotNone(head.fullmatch("fix/7.x"))
        self.assertIsNone(head.fullmatch("fixx7.x"))

    def test_a_pattern_that_cannot_be_exact_has_no_matcher(self):
        for pattern in ("issue-<num>", "issue-<slug>", "<num><slug>", "<slug><num>", "x"):
            with self.subTest(pattern):
                self.assertIsNone(attempt_budget.branch_issue(pattern))


class SameRepositoryTest(unittest.TestCase):
    def test_the_names_compare_case_insensitively(self):
        pull = make_pull(1, "a", T, base_repo="Fagenorn/Renamed", head_repo="fagenorn/renamed")
        self.assertTrue(attempt_budget.same_repository(pull))

    def test_a_fork_is_not_the_same_repository(self):
        self.assertFalse(attempt_budget.same_repository(make_pull(1, "a", T, head_repo="x/y")))

    def test_a_deleted_fork_is_none(self):
        self.assertIsNone(attempt_budget.same_repository(make_pull(1, "a", T, head_repo=None)))

    def test_a_malformed_pull_is_a_payload_error(self):
        broken = [make_pull(1, "a", T, head_repo=MISSING)]
        pull = make_pull(1, "a", T)
        pull["head"]["repo"] = "text"
        broken.append(pull)
        pull = make_pull(1, "a", T)
        pull["head"]["repo"] = {"full_name": 5}
        broken.append(pull)
        pull = make_pull(1, "a", T)
        pull["base"]["repo"]["full_name"] = None
        broken.append(pull)
        for pull in broken:
            with self.subTest(pull=pull):
                with self.assertRaises(ForgeError) as caught:
                    attempt_budget.same_repository(pull)
                self.assertEqual(caught.exception.code, "payload_invalid")


class PairTest(unittest.TestCase):
    def test_a_claim_takes_the_earliest_merge_in_its_window(self):
        t1 = BASE
        claims = [attempt_budget.Claim(t1, 1, None, None),
                  attempt_budget.Claim(t1 + timedelta(hours=5), 2, None, None)]
        merges = [attempt_budget.Merge(12, t1 + timedelta(hours=7), "b"),
                  attempt_budget.Merge(10, t1 + timedelta(hours=2), "b"),
                  attempt_budget.Merge(11, t1 + timedelta(hours=3), "b")]
        self.assertEqual(attempt_budget.pair(4, claims, merges), [
            attempt_history.Attempt(4, 10, t1, t1 + timedelta(hours=2)),
            attempt_history.Attempt(4, 12, t1 + timedelta(hours=5), t1 + timedelta(hours=7))])

    def test_claims_tie_on_creation_by_comment_id(self):
        claims = [attempt_budget.Claim(BASE, 9, None, None), attempt_budget.Claim(BASE, 3, None, None)]
        merges = [attempt_budget.Merge(10, BASE + timedelta(hours=1), "b")]
        paired = attempt_budget.pair(4, claims, merges)
        self.assertEqual([a.pull for a in paired], [None, 10])


class TrackerTest(AttemptBudgetCase):
    def one_issue(self, comments, pulls, now=T):
        world = World({"pages": [pulls], "comments": {5: comments}})
        return self.command("record", world, now=now), world

    def test_a_stopped_claim_before_the_delivering_one_is_recorded_unmerged(self):
        t1, t2, merged = BASE, BASE + timedelta(hours=4), BASE + timedelta(hours=9)
        world = World({"pages": [[make_pull(105, "issue-5-x", merged)]],
                       "comments": {5: [claim_comment(1, 5, t1), claim_comment(2, 5, t2)]}})
        code, _ = self.command("record", world)
        self.assertEqual(code, 0)
        attempts = self.history()
        self.assertIn({"issue": 5, "pull": None, "merged_at": None, "claimed_at": stamp(t1)}, attempts)
        self.assertIn({"issue": 5, "pull": 105, "merged_at": stamp(merged), "claimed_at": stamp(t2)},
                      attempts)

    def test_the_start_is_the_claims_creation_not_its_renewal(self):
        t1 = BASE
        merged = t1 + timedelta(hours=5)
        renewed = claim_comment(1, 5, t1)
        renewed["updated_at"] = stamp(t1 + timedelta(hours=3))
        world = World({"pages": [[make_pull(105, "issue-5-x", merged)]], "comments": {5: [renewed]}})
        self.assertEqual(self.tracker(world), [attempt_history.Attempt(5, 105, t1, merged)])

    def test_a_second_merge_with_no_claim_between_is_not_an_attempt(self):
        t1 = BASE
        world = World({"pages": [[make_pull(106, "issue-5-y", t1 + timedelta(hours=6)),
                                  make_pull(105, "issue-5-x", t1 + timedelta(hours=2))]],
                       "comments": {5: [claim_comment(1, 5, t1)]}})
        self.assertEqual(self.tracker(world),
                         [attempt_history.Attempt(5, 105, t1, t1 + timedelta(hours=2))])

    def test_pulls_outside_the_rule_are_ignored(self):
        merged = BASE + timedelta(hours=3)
        rows = [
            make_pull(101, "issue-1-x", merged, base_ref="other"),
            make_pull(102, "issue-2-x", merged, head_repo="someone/fork"),
            make_pull(103, "issue-3-x", merged, head_repo=None),
            make_pull(104, "issue-4-x", None),
            make_pull(105, "release-1", merged),
        ]
        world = World({"pages": [rows],
                       "comments": {n: [claim_comment(n, n, BASE)] for n in range(1, 6)}})
        code, _ = self.command("record", world)
        self.assertEqual(code, 0)
        self.assertEqual(self.history(), [])
        with self.subTest("a pull with no head repo member"):
            world = World({"pages": [[make_pull(101, "issue-1-x", merged, head_repo=MISSING)]],
                           "comments": {1: [claim_comment(1, 1, BASE)]}})
            code, result = self.command("record", world)
            self.assertEqual(code, 1)
            self.assertEqual(result["error"]["code"], "payload_invalid")

    def test_a_claim_released_before_a_merge_is_not_delivered_by_it(self):
        t1 = BASE
        world = World({"pages": [[make_pull(105, "issue-5-x", t1 + timedelta(hours=2))]],
                       "comments": {5: [claim_comment(1, 5, t1),
                                        end_comment(2, 1, t1 + timedelta(hours=1))]}})
        self.command("record", world)
        self.assertEqual(self.history(), [
            {"issue": 5, "pull": None, "merged_at": None, "claimed_at": stamp(t1)}])

    def test_a_claim_released_after_its_merge_is_delivered(self):
        t1 = BASE
        merged = t1 + timedelta(hours=2)
        world = World({"pages": [[make_pull(105, "issue-5-x", merged)]],
                       "comments": {5: [claim_comment(1, 5, t1),
                                        end_comment(2, 1, merged + timedelta(seconds=30))]}})
        self.command("record", world)
        self.assertEqual(self.history(), [
            {"issue": 5, "pull": 105, "merged_at": stamp(merged), "claimed_at": stamp(t1)}])

    def test_an_end_marker_of_another_claim_does_not_end_this_one(self):
        t1 = BASE
        merged = t1 + timedelta(hours=2)
        world = World({"pages": [[make_pull(105, "issue-5-x", merged)]],
                       "comments": {5: [claim_comment(1, 5, t1),
                                        end_comment(2, 99, t1 + timedelta(hours=1))]}})
        self.assertEqual(self.tracker(world), [attempt_history.Attempt(5, 105, t1, merged)])

    def test_a_claim_pairs_only_with_its_branch_and_its_issue(self):
        t1 = BASE
        merged = t1 + timedelta(hours=2)
        with self.subTest("another head"):
            world = World({"pages": [[make_pull(105, "issue-5-b", merged)]],
                           "comments": {5: [claim_comment(1, 5, t1, branch="issue-5-a")]}})
            self.assertEqual(self.tracker(world), [attempt_history.Attempt(5, None, t1, None)])
        with self.subTest("its head"):
            world = World({"pages": [[make_pull(105, "issue-5-a", merged)]],
                           "comments": {5: [claim_comment(1, 5, t1, branch="issue-5-a")]}})
            self.assertEqual(self.tracker(world), [attempt_history.Attempt(5, 105, t1, merged)])
        with self.subTest("a marker naming another issue"):
            world = World({"pages": [[make_pull(105, "issue-5-x", merged)]],
                           "comments": {5: [claim_comment(1, 5, t1, marker_issue=6)]}})
            self.assertEqual(self.tracker(world), [])

    def test_nothing_after_the_forge_time_counts(self):
        merged = T + timedelta(seconds=1)
        world = World({"pages": [[make_pull(105, "issue-5-x", merged)]],
                       "comments": {5: [claim_comment(1, 5, BASE)]}})
        self.assertEqual(self.tracker(world), [])
        self.assertEqual(self.tracker(world, now=T + timedelta(seconds=2)),
                         [attempt_history.Attempt(5, 105, BASE, merged)])

    def test_a_claim_or_an_end_after_the_forge_time_is_ignored(self):
        merged = T - timedelta(hours=1)
        world = World({"pages": [[make_pull(105, "issue-5-x", merged)]],
                       "comments": {5: [claim_comment(1, 5, merged - timedelta(hours=1)),
                                        end_comment(2, 1, T + timedelta(seconds=1)),
                                        claim_comment(3, 5, T + timedelta(seconds=1))]}})
        self.assertEqual(self.tracker(world), [
            attempt_history.Attempt(5, 105, merged - timedelta(hours=1), merged)])

    def test_a_non_list_page_is_a_payload_error(self):
        world = World({"pages": [{"message": "x"}], "comments": {}})
        with world.serving():
            with self.assertRaises(ForgeError) as caught:
                attempt_budget.tracker_attempts(
                    SLUG, "main", attempt_budget.branch_issue("issue-<num>-<slug>"), T)
        self.assertEqual(caught.exception.code, "payload_invalid")

    def test_the_pulls_are_requested_from_the_first_page_by_update(self):
        world = World()
        self.tracker(world)
        self.assertEqual(world.paths, [
            f"repos/{SLUG}/pulls?state=closed&base=main&sort=updated&direction=desc&per_page=100&page=1"])


class PagingTest(AttemptBudgetCase):
    """Page one holds 100 merged pulls, issue i merged at BASE + i hours, claimed 10 minutes before."""

    def full_page(self, claim_for=None):
        page, comments = [], {}
        for i in range(100, 0, -1):
            merged = BASE + timedelta(hours=i)
            page.append(make_pull(100 + i, f"issue-{i}-x", merged))
            comments[i] = [claim_comment(1000 + i, i, merged - timedelta(minutes=10))]
        return page, comments

    def test_a_final_window_reads_no_further_page(self):
        page, comments = self.full_page()
        world = World({"pages": [page], "comments": comments})
        attempts = self.tracker(world)
        self.assertEqual(world.page_numbers(), [1])
        self.assertEqual(len(attempts), 100)

    def test_a_windowed_claim_older_than_the_horizon_reads_the_next_page(self):
        page, comments = self.full_page()
        horizon = BASE + timedelta(hours=1)
        early = BASE
        comments[100] = [claim_comment(2000, 100, early)]
        earlier = make_pull(500, "issue-100-z", BASE)
        world = World({"pages": [page, [earlier]], "comments": comments})
        attempts = self.tracker(world)
        self.assertEqual(world.page_numbers(), [1, 2])
        self.assertLess(early, horizon)
        self.assertIn(attempt_history.Attempt(100, 500, early, BASE), attempts)

    def test_a_windowed_claim_at_the_horizon_reads_the_next_page(self):
        page, comments = self.full_page()
        horizon = BASE + timedelta(hours=1)
        comments[100] = [claim_comment(2000, 100, horizon)]
        same_second = make_pull(500, "issue-100-z", horizon)
        world = World({"pages": [page, [same_second]], "comments": comments})
        attempts = self.tracker(world)
        self.assertEqual(world.page_numbers(), [1, 2])
        self.assertIn(attempt_history.Attempt(100, 500, horizon, horizon), attempts)

    def test_a_short_page_is_the_last(self):
        page, comments = self.full_page()
        world = World({"pages": [page[:50]], "comments": comments})
        self.tracker(world)
        self.assertEqual(world.page_numbers(), [1])

    def test_fewer_than_a_window_of_deliveries_reads_every_page(self):
        page, comments = self.full_page()
        unclaimed = {k: v for k, v in comments.items() if k <= 10}
        world = World({"pages": [page, page[:3]], "comments": unclaimed})
        self.tracker(world)
        self.assertEqual(world.page_numbers(), [1, 2])


class FromSourceTest(AttemptBudgetCase):
    FAKE_GH = """\
#!{python}
import json, os, re, sys

world = json.load(open(os.environ["ATTEMPT_WORLD"]))
argv = sys.argv[1:]
if argv == ["api", "--include", "rate_limit"]:
    sys.stdout.write("HTTP/2.0 200 OK\\r\\nDate: Sun, 22 Nov 2026 12:00:00 GMT\\r\\n\\r\\n{{}}")
    sys.exit(0)
if len(argv) == 2 and argv[0] == "api":
    found = re.fullmatch(r"repos/fagenorn/nix-config/pulls\\?.*&page=(\\d+)", argv[1])
    if found:
        pages = world["pages"]
        number = int(found.group(1))
        print(json.dumps(pages[number - 1] if number <= len(pages) else []))
        sys.exit(0)
if len(argv) == 4 and argv[:3] == ["api", "--paginate", "--slurp"]:
    found = re.fullmatch(r"repos/fagenorn/nix-config/issues/(\\d+)/comments\\?per_page=100", argv[3])
    if found:
        print(json.dumps([world["comments"].get(found.group(1), [])]))
        sys.exit(0)
sys.exit(1)
"""

    def test_report_runs_from_source_against_a_fake_gh(self):
        directory = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        data = twenty_world()
        (directory / "world.json").write_text(
            json.dumps({"pages": data["pages"],
                        "comments": {str(k): v for k, v in data["comments"].items()}}),
            encoding="utf-8")
        gh = directory / "bin" / "gh"
        gh.parent.mkdir()
        gh.write_text(self.FAKE_GH.format(python=sys.executable), encoding="utf-8")
        gh.chmod(gh.stat().st_mode | stat.S_IXUSR)
        env = {
            **os.environ,
            "PYTHONPATH": str(REPO_ROOT / "python"),
            "PATH": f"{gh.parent}{os.pathsep}{os.environ['PATH']}",
            "HOME": os.environ["HOME"],
            "ATTEMPT_WORLD": str(directory / "world.json"),
        }
        done = subprocess.run(
            [sys.executable, "-m", "agent_tools.delivery.attempt_budget", "report",
             "--repo-root", str(self.root)],
            env=env, capture_output=True, text=True, timeout=120, cwd=str(directory))
        self.assertEqual(done.returncode, 0, done.stderr)
        result = json.loads(done.stdout)
        self.assertEqual(result["command"], "report")
        self.assertEqual(result["budget_minutes"], 1621)
        self.assertEqual(len(result["attempts"]), 20)


if __name__ == "__main__":
    unittest.main()
