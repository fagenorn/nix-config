"""The railway-deploy watch adapter (issue 582 P1-P7). Run: just agent-workflow-tests"""
import json
import os
import tempfile
import unittest
from unittest import mock

from agent_tools.release import railway_deploy_adapter as adapter
from agent_tools.release import release_adapter, release_profile, transaction_plan
from . import release_test_support as support
from .railway_world import (BASE_TIP, CONFIG, GREEN, HEAD, HOTFIX, MERGE, OLDER, PR, PR_VIEW, RED,
                            RUNNING, SLUG, TIMED_OUT, UNWATCHED, RailwayWorld, commit_argv,
                            deployment, watched)

REFUSED = {"result": "rejected", "error_class": "unsupported_operation",
           "reference": "deploy: watch_only"}
TARGET = {"kind": "github_repository", "repository": SLUG, "branch": "main"}


def request(candidate=None, **config):
    return {"kind": "effect", "operation": "deploy", "parameters": {
        "target": dict(TARGET), "candidate": candidate or {"commit": MERGE},
        "config": {**CONFIG, **config}}}


def predicate(candidate=None, name="running_subject_identity"):
    value = request(candidate)
    return {"kind": "predicate", "predicate": name, "operation": "deploy",
            "parameters": value["parameters"]}


class DescriptorTest(unittest.TestCase):
    def test_deploy_is_a_registered_watch_only_activation_unit(self):
        descriptor = adapter.describe()
        self.assertEqual(release_adapter.descriptor_problems(descriptor), [])
        self.assertEqual(release_adapter.watch_operation(descriptor), "deploy")
        self.assertIs(release_adapter.REGISTRY["railway-deploy"], adapter)
        self.assertEqual(descriptor["executables"], ["gh", "railway"])
        self.assertEqual(descriptor["operations"]["deploy"]["config_schema"]["members"],
                         {"project": "string", "environment": "string", "services": "string_list"})
        self.assertEqual(descriptor["predicates"]["running_subject_identity"]["support"], "supported")
        self.assertNotIn("railway", release_adapter.REGISTRY)

    def test_invoke_refuses_every_request_without_a_child(self):
        world = RailwayWorld(self)
        for value in (request(), {}, None):
            self.assertEqual(adapter.invoke(value), REFUSED)
        self.assertEqual(world.calls(), [])

    def test_a_request_outside_the_closed_shape_spawns_nothing(self):
        world = RailwayWorld(self)
        bad = [request(services=[]), request(project=""), request(environment="a\nb"),
               request(extra="x"), request({"commit": "A" * 40})]
        bad[3]["parameters"]["config"]["extra"] = "x"
        for value in bad:
            observation = adapter.inspect(value)
            self.assertEqual((observation["outcome"], observation["reason"]),
                             ("unknown", "parameters_invalid"))
        self.assertEqual(world.calls(), [])

    def test_a_malformed_predicate_is_unobservable_and_spawns_nothing(self):
        world = RailwayWorld(self)
        bad_parameters = predicate()
        bad_parameters["parameters"]["config"]["services"] = []
        extra_member = predicate()
        extra_member["extra"] = True
        wrong_operation = predicate()
        wrong_operation["operation"] = "publish"
        for value in (bad_parameters, extra_member, wrong_operation):
            observation = adapter.inspect(value)
            self.assertEqual(release_adapter.predicate_observation_problems(observation), [])
            self.assertEqual((observation["outcome"], observation["reason"]),
                             ("unknown", "identity_unobservable"))
            self.assertIn(observation["reason"],
                          transaction_plan.DERIVED_REASONS["running_subject_identity"])
        self.assertEqual(world.calls(), [])


class ClassificationTest(unittest.TestCase):
    def setUp(self):
        self.world = RailwayWorld(self)
        self.world.status()

    def verdict(self, value=None):
        observation = adapter.inspect(value or request())
        self.assertEqual(release_adapter.effect_observation_problems(observation), [])
        return observation["outcome"], observation["reason"]

    def one_service(self, *entries):
        self.world.deployments("api", *entries)
        return self.verdict(request(services=["api"]))

    def test_the_per_service_table(self):
        cases = (
            ((), ("absent", "deployment_absent")),
            ((deployment("d1", MERGE, "BUILDING"),), ("in_progress", "deployment_in_progress")),
            ((deployment("d1", MERGE, "SUCCESS"),), ("satisfied", "deployed")),
            ((deployment("d1", MERGE, "SLEEPING"),), ("satisfied", "deployed")),
            ((deployment("d2", MERGE, "FAILED", "2026-11-08T11:00:00Z"),
              deployment("d1", OLDER, "REMOVED", "2026-11-08T09:00:00Z"),
              deployment("d0", OLDER, "SUCCESS", "2026-11-08T08:00:00Z")),
             ("diverged", "silent_rollback")),
            ((deployment("d1", MERGE, "CRASHED"),), ("diverged", "deployment_failed")),
            ((deployment("d2", OLDER, "SUCCESS", "2026-11-08T11:00:00Z"),
              deployment("d1", MERGE, "REMOVED")), ("diverged", "superseded")),
            ((deployment("d2", OLDER, "SUCCESS", "2026-11-08T11:00:00Z"),
              deployment("d1", MERGE, "BUILDING")), ("diverged", "superseded")),
            ((deployment("d1", MERGE, "REMOVED"),), ("diverged", "removed")),
            ((deployment("d1", MERGE, "TELEPORTING"),), ("unknown", "status_unrecognized")),
        )
        for entries, expected in cases:
            with self.subTest(expected=expected, entries=[e["id"] for e in entries]):
                self.assertEqual(self.one_service(*entries), expected)

    def test_another_branch_never_matches(self):
        self.assertEqual(self.one_service(deployment("d1", MERGE, branch="dev")),
                         ("absent", "deployment_absent"))

    def test_a_deployment_without_a_commit_serves_but_never_matches(self):
        upload = deployment("d2", None, "SUCCESS", "2026-11-08T11:00:00Z")
        self.assertEqual(self.one_service(upload, deployment("d1", MERGE, "REMOVED")),
                         ("diverged", "superseded"))

    def test_services_aggregate_diverged_then_unknown_then_in_progress_then_absent(self):
        self.world.deployments("api", deployment("d1", MERGE, "SUCCESS"))
        self.world.deployments("admin", deployment("d2", MERGE, "DEPLOYING"))
        self.assertEqual(self.verdict(), ("in_progress", "deployment_in_progress"))
        self.world.deployments("api", deployment("d1", MERGE, "FAILED"))
        self.world.deployments("admin", exit=1, stdout="")
        self.assertEqual(self.verdict(), ("diverged", "deployment_failed"))
        self.world.deployments("api", deployment("d1", MERGE, "SUCCESS"))
        self.world.deployments("admin", deployment("d2", MERGE, "SUCCESS"))
        self.assertEqual(self.verdict(), ("satisfied", "deployed"))

    def test_the_observation_names_each_matched_deployment(self):
        self.world.deployments("api", deployment("d1", MERGE))
        self.world.deployments("admin", deployment("d2", MERGE))
        observation = adapter.inspect(request())
        self.assertEqual(observation["references"],
                         ["railway:nodo-prod/production/api/d1",
                          "railway:nodo-prod/production/admin/d2"])
        self.assertEqual(observation["observed_subject"],
                         {"commit": MERGE, "deployments": {"api": "d1", "admin": "d2"}})
        self.assertEqual([s["service"] for s in observation["facts"]["services"]], ["api", "admin"])

    def test_a_wrongly_linked_project_reads_no_deployments(self):
        self.world.status(name="other-project")
        self.assertEqual(self.verdict(), ("unknown", "project_mismatch"))
        self.world.status(environments=("staging",))
        self.assertEqual(self.verdict(), ("unknown", "project_mismatch"))
        self.assertEqual({c["argv"][0] for c in self.world.calls("railway")}, {"status"})

    def test_a_null_meta_row_is_unavailable_identity_not_a_payload_error(self):
        history = deployment("d0", None, "REMOVED", "2026-11-01T10:00:00Z", meta=None)
        self.assertEqual(self.one_service(deployment("d1", MERGE), history),
                         ("satisfied", "deployed"))
        serving_unknown = deployment("d2", None, "SUCCESS", "2026-11-08T11:00:00Z", meta=None)
        self.assertEqual(self.one_service(serving_unknown, deployment("d1", MERGE, "REMOVED")),
                         ("diverged", "superseded"))

    def test_a_malformed_deployment_list_is_payload_invalid(self):
        self.world.deployments("api", stdout='[{"id": "d1"}]')
        self.assertEqual(self.verdict(request(services=["api"])), ("unknown", "payload_invalid"))

    def test_only_read_only_cli_verbs_are_used(self):
        self.world.deployments("api", deployment("d1", MERGE))
        self.world.deployments("admin", deployment("d2", MERGE))
        adapter.inspect(request())
        self.assertEqual({c["argv"][0] for c in self.world.calls("railway")},
                         {"status", "deployment"})
        self.assertEqual({c["argv"][1] for c in self.world.calls("railway")
                          if c["argv"][0] == "deployment"}, {"list"})


class SkipTest(unittest.TestCase):
    """Plan P5.5: Railway also skips after failed or timed-out CI, and a skip proves nothing
    about the serving code unless the serving row is the push's immediate predecessor at the
    released commit's first parent. Without both kinds of evidence a skip is never ok."""

    def setUp(self):
        self.world = RailwayWorld(self)
        self.world.status()

    def skipped_api(self, *runs, older=True, parent=OLDER, **options):
        entries = [deployment("d2", MERGE, "SKIPPED", "2026-11-08T11:00:00Z")]
        if older:
            entries.append(deployment("d1", OLDER, "SUCCESS"))
        self.world.deployments("api", *entries)
        if runs or options:
            self.world.check_runs(MERGE, *runs, **options)
        if parent is not None:
            self.world.commit_parents(MERGE, parent, HOTFIX)
        return self.observe()

    def observe(self):
        observation = adapter.inspect(request(services=["api"]))
        self.assertEqual(release_adapter.effect_observation_problems(observation), [])
        self.last = observation
        return observation["outcome"], observation["reason"]

    def detail(self):
        return self.last["facts"]["services"][0]["skip_evidence"]

    def reads(self, needle):
        return [c["argv"] for c in self.world.calls("gh") if any(needle in a for a in c["argv"])]

    def test_a_skip_with_green_checks_after_the_parent_serving_row_is_benign(self):
        self.assertEqual(self.skipped_api(GREEN, ("completed", "neutral")),
                         ("satisfied", "skipped"))
        self.assertEqual(self.detail(), "complete")
        self.assertEqual(self.reads("git/commits"), [adapter.parent_argv(SLUG, MERGE)])

    def test_a_skip_after_failed_or_timed_out_ci_is_diverged(self):
        self.assertEqual(self.skipped_api(GREEN, RED), ("diverged", "skipped_after_ci_failure"))
        self.setUp()
        self.assertEqual(self.skipped_api(TIMED_OUT), ("diverged", "skipped_after_ci_failure"))

    def test_a_skip_without_ci_evidence_is_unknown(self):
        cases = (
            dict(runs=(), options={"total": 0}),
            dict(runs=(RUNNING,), options={}),
            dict(runs=(GREEN,), options={"total": 150}),
            dict(runs=(), options={"exit": 1, "stdout": ""}),
            dict(runs=(GREEN,), options={}, older=False),
        )
        for case in cases:
            with self.subTest(case=case):
                self.setUp()
                self.assertEqual(self.skipped_api(*case["runs"], older=case.get("older", True),
                                                  **case["options"]),
                                 ("unknown", "skip_unexplained"))

    def test_a_check_run_without_a_conclusion_member_is_unread_not_a_crash(self):
        """Regression (COR-002): GitHub writes `conclusion: null` for a run in progress; a run
        with no `conclusion` member at all is outside the closed shape and must not raise."""
        payload = {"total_count": 1, "check_runs": [{"id": 1, "name": "ci",
                                                     "status": "in_progress"}]}
        self.assertEqual(self.skipped_api(stdout=json.dumps(payload)),
                         ("unknown", "skip_unexplained"))
        self.assertEqual(self.detail(), "checks_unread")

    def test_green_checks_after_a_failed_attempt_do_not_explain_the_skip(self):
        """Regression (COR-001): CI that failed, caused Railway's skip and then turned green
        leaves the older serving row without the candidate's changes; the skip is explained
        by a CI failure, not by an unchanged watch path, so it stays unknown."""
        self.assertEqual(self.skipped_api(("completed", "failure", "ci"),
                                          ("completed", "success", "ci"), GREEN),
                         ("unknown", "skip_unexplained"))
        self.assertEqual(self.detail(), "checks_rerun")
        self.setUp()
        self.assertEqual(self.skipped_api(("completed", "failure", "ci"),
                                          ("completed", "failure", "ci")),
                         ("diverged", "skipped_after_ci_failure"))

    def test_one_job_name_in_two_check_suites_is_two_checks_not_a_re_run(self):
        """Regression (nodo-prod v0.51.1): two workflows each publish a job named `lint`, each
        in its own check suite; nothing was re-run, so the CI route is complete."""
        self.assertEqual(self.skipped_api(GREEN + ("lint", 118372805136), GREEN + ("build", 5),
                                          GREEN + ("lint", 118373146276)),
                         ("satisfied", "skipped"))
        self.assertEqual(self.detail(), "complete")

    def test_a_second_run_of_a_name_within_one_check_suite_is_a_re_run(self):
        self.assertEqual(self.skipped_api(("completed", "failure", "lint", 7),
                                          GREEN + ("lint", 7), GREEN + ("lint", 8)),
                         ("unknown", "skip_unexplained"))
        self.assertEqual(self.detail(), "checks_rerun")
        self.setUp()
        self.assertEqual(self.skipped_api(GREEN + ("lint", 7), GREEN + ("lint", 7)),
                         ("unknown", "skip_unexplained"))
        self.assertEqual(self.detail(), "checks_rerun")

    def test_a_failure_in_one_suite_is_not_hidden_by_a_green_namesake_in_another(self):
        """A new workflow run of the commit is a new suite: the failed one stays its own
        check's latest run."""
        self.assertEqual(self.skipped_api(("completed", "failure", "lint", 7),
                                          GREEN + ("lint", 8)),
                         ("diverged", "skipped_after_ci_failure"))

    def test_a_malformed_check_suite_is_read_as_no_suite(self):
        payload = {"total_count": 2, "check_runs": [
            {"id": 1, "name": "lint", "status": "completed", "conclusion": "success",
             "check_suite": {"id": "7"}},
            {"id": 2, "name": "lint", "status": "completed", "conclusion": "success",
             "check_suite": None}]}
        self.assertEqual(self.skipped_api(stdout=json.dumps(payload)),
                         ("unknown", "skip_unexplained"))
        self.assertEqual(self.detail(), "checks_rerun")

    def test_a_full_page_of_green_checks_is_still_over_the_limit(self):
        self.assertEqual(self.skipped_api(*[GREEN] * 101), ("unknown", "skip_unexplained"))
        self.assertEqual(self.detail(), "checks_over_limit")

    def test_an_intervening_failed_deployment_leaves_the_skip_unexplained(self):
        """Regression (plan review PR-001): green checks and an older serving row are not enough
        when a failed push sits between them — its code never served."""
        self.world.deployments("api", deployment("d3", MERGE, "SKIPPED", "2026-11-08T12:00:00Z"),
                               deployment("d2", HOTFIX, "FAILED", "2026-11-08T11:00:00Z"),
                               deployment("d1", OLDER, "SUCCESS", "2026-11-08T10:00:00Z"))
        self.world.check_runs(MERGE, GREEN)
        self.world.commit_parents(MERGE, OLDER)
        self.assertEqual(self.observe(), ("unknown", "skip_unexplained"))
        self.assertEqual(self.detail(), "intervening_deployment")
        self.assertEqual(self.reads("git/commits"), [])

    def test_an_intervening_skipped_push_leaves_the_skip_unexplained(self):
        self.world.deployments("api", deployment("d3", MERGE, "SKIPPED", "2026-11-08T12:00:00Z"),
                               deployment("d2", HOTFIX, "SKIPPED", "2026-11-08T11:00:00Z"),
                               deployment("d1", OLDER, "SUCCESS", "2026-11-08T10:00:00Z"))
        self.world.check_runs(MERGE, GREEN)
        self.assertEqual(self.observe(), ("unknown", "skip_unexplained"))
        self.assertEqual(self.detail(), "intervening_deployment")

    def test_a_serving_row_of_unknown_identity_leaves_the_skip_unexplained(self):
        """Regression (plan review PR-001): a serving row without a commit proves nothing."""
        self.world.deployments("api", deployment("d2", MERGE, "SKIPPED", "2026-11-08T11:00:00Z"),
                               deployment("d1", None, "SUCCESS", meta=None))
        self.world.check_runs(MERGE, GREEN)
        self.assertEqual(self.observe(), ("unknown", "skip_unexplained"))
        self.assertEqual(self.detail(), "serving_identity_unknown")
        self.assertEqual(self.reads("git/commits"), [])

    def test_a_serving_commit_that_is_not_the_first_parent_leaves_the_skip_unexplained(self):
        self.assertEqual(self.skipped_api(GREEN, parent=HOTFIX), ("unknown", "skip_unexplained"))
        self.assertEqual(self.detail(), "serving_not_parent")

    def test_an_unread_parent_leaves_the_skip_unexplained(self):
        self.world.deployments("api", deployment("d2", MERGE, "SKIPPED", "2026-11-08T11:00:00Z"),
                               deployment("d1", OLDER, "SUCCESS"))
        self.world.check_runs(MERGE, GREEN)
        self.world.commit_parents(MERGE, exit=1, stdout="")
        self.assertEqual(self.observe(), ("unknown", "skip_unexplained"))
        self.assertEqual(self.detail(), "parent_unread")

    def test_supersession_is_judged_before_the_skip_and_reads_no_evidence(self):
        self.world.deployments("api", deployment("d3", OLDER, "SUCCESS", "2026-11-08T12:00:00Z"),
                               deployment("d2", MERGE, "SKIPPED", "2026-11-08T11:00:00Z"))
        self.assertEqual(self.observe(), ("diverged", "superseded"))
        self.assertEqual(self.reads("check-runs") + self.reads("git/commits"), [])

    def test_the_evidence_is_read_once_and_only_for_a_skip(self):
        self.world.deployments("api", deployment("d2", MERGE, "SKIPPED", "2026-11-08T11:00:00Z"),
                               deployment("d1", OLDER))
        self.world.deployments("admin", deployment("d4", MERGE, "SKIPPED", "2026-11-08T11:00:00Z"),
                               deployment("d3", OLDER))
        self.world.check_runs(MERGE, GREEN)
        self.world.commit_parents(MERGE, OLDER)
        self.assertEqual(adapter.inspect(request())["outcome"], "satisfied")
        self.assertEqual(self.reads("check-runs"), [adapter.check_runs_argv(SLUG, MERGE)])
        self.assertEqual(self.reads("git/commits"), [adapter.parent_argv(SLUG, MERGE)])
        self.assertIn("-X", self.reads("check-runs")[0])


NODO_DELTA = ("docs/operations/deploy.md", "docs/areas/data/adr/001-pooler.md",
              "src/Infrastructure/Data/Retry.cs", "src/Infrastructure/DependencyInjection.cs",
              "tests/Infrastructure.Tests/Data/RetryTests.cs")


class WatchPathSkipTest(unittest.TestCase):
    """ADR-release-013: a skip the CI route cannot explain is benign only when Railway says no
    watched file changed and the serving row's commit is an ancestor of the released commit
    with no change under the service's root directory. The shape is nodo-prod's v0.51.1: api
    deployed the merge commit, admin skipped it and still serves the previous main tip, which
    a release later disposed as failed had deployed."""

    def setUp(self):
        self.world = RailwayWorld(self)
        self.world.status()
        self.world.deployments("api", deployment("4fa7e1d2", MERGE, created="2026-11-08T14:02:33Z"))
        self.world.check_runs(MERGE, total=0)
        self.world.commit_parents(MERGE, BASE_TIP, HEAD)

    def admin(self, *older, skipped=None, files=NODO_DELTA, **compare):
        skipped = skipped or watched("86ee94aa", MERGE, "SKIPPED", "2026-11-08T14:02:33Z")
        older = older or (watched("10043c13", BASE_TIP, created="2026-11-08T04:05:53Z"),
                          watched("a10190b2", OLDER, "REMOVED", "2026-11-07T23:12:57Z"))
        self.world.deployments("admin", skipped, *older)
        self.world.compare(BASE_TIP, MERGE, *files, **compare)
        observation = adapter.inspect(request())
        self.assertEqual(release_adapter.effect_observation_problems(observation), [])
        self.last = observation
        entry = observation["facts"]["services"][1]
        return entry["outcome"], entry["reason"]

    def evidence(self):
        entry = self.last["facts"]["services"][1]
        return entry["skip_evidence"], entry.get("watch_evidence")

    def compares(self):
        return [c["argv"] for c in self.world.calls("gh") if "/compare/" in c["argv"][-1]]

    def refused(self, watch, ci="checks_none"):
        self.assertEqual((self.last["outcome"], self.last["reason"]),
                         ("unknown", "skip_unexplained"))
        self.assertEqual(self.evidence(), (ci, watch))
        self.assertEqual(self.last["references"][-1], f"railway-skip:admin/{ci}/{watch}")

    def test_the_nodo_shape_is_benign_whatever_ci_evidence_is_missing(self):
        for runs, options in (((), {"total": 0}), ((GREEN, GREEN + ("ci",), GREEN + ("ci",)), {}),
                              ((GREEN,), {"total": 150}), ((), {"exit": 1, "stdout": ""})):
            with self.subTest(runs=runs, options=options):
                self.world.check_runs(MERGE, *runs, **options)
                self.assertEqual(self.admin(ahead=7), ("satisfied", "skipped"))
                self.assertEqual(self.evidence(), ("watch_paths_unchanged", None))
        self.assertEqual(self.compares()[0], adapter.compare_argv(SLUG, BASE_TIP, MERGE))
        self.assertIn(f"github:{SLUG}/compare/{BASE_TIP}...{MERGE}", self.last["references"])
        self.assertEqual(self.last["observed_subject"]["deployments"],
                         {"api": "4fa7e1d2", "admin": "86ee94aa"})
        self.assertEqual(adapter.inspect(predicate())["reason"], "running")

    def test_a_failed_check_is_still_diverged_and_reads_no_comparison(self):
        self.world.check_runs(MERGE, RED)
        self.assertEqual(self.admin(), ("diverged", "skipped_after_ci_failure"))
        self.assertEqual(self.compares(), [])

    def test_the_ci_route_alone_reads_no_comparison(self):
        self.world.check_runs(MERGE, GREEN)
        self.assertEqual(self.admin(), ("satisfied", "skipped"))
        self.assertEqual(self.evidence(), ("complete", None))
        self.assertEqual(self.compares(), [])

    def test_a_serving_row_that_failed_crashed_or_was_removed_stays_unexplained(self):
        for status in ("FAILED", "CRASHED", "REMOVED", "REMOVING", "BUILDING"):
            with self.subTest(status=status):
                self.admin(watched("10043c13", BASE_TIP, status, "2026-11-08T04:05:53Z"),
                           watched("a10190b2", OLDER, created="2026-11-07T23:12:57Z"))
                self.refused("intervening_deployment", "intervening_deployment")
        self.assertEqual(self.compares(), [])

    def test_no_serving_row_stays_unexplained(self):
        self.admin(watched("0ld", BASE_TIP, "SKIPPED", "2026-11-08T04:05:53Z"))
        self.refused("no_serving_deployment", "intervening_deployment")
        self.world.deployments("admin", watched("86ee94aa", MERGE, "SKIPPED", "2026-11-08T14:02:33Z"))
        self.last = adapter.inspect(request())
        self.refused("no_serving_deployment", "no_serving_deployment")

    def test_a_serving_commit_that_is_not_an_ancestor_stays_unexplained(self):
        for compare in ({"status": "diverged", "behind": 2, "merge_base": OLDER},
                        {"status": "behind", "behind": 1, "merge_base": MERGE},
                        {"status": "ahead", "behind": 0, "merge_base": OLDER},
                        {"status": "ahead", "behind": 1}):
            with self.subTest(compare=compare):
                self.admin(**compare)
                self.refused("serving_not_ancestor")

    def test_a_serving_row_of_an_unrelated_branch_stays_unexplained(self):
        self.admin(watched("10043c13", BASE_TIP, created="2026-11-08T04:05:53Z", branch="dev"))
        self.refused("serving_identity_unknown", "serving_identity_unknown")
        self.assertEqual(self.compares(), [])

    def test_a_watched_path_changed_in_between_stays_unexplained(self):
        for files in ((*NODO_DELTA, "admin/src/App.tsx"), ("admin/railway.toml",),
                      (("docs/moved.md", "admin/README.md"),), (("admin/new.ts", "web/old.ts"),)):
            with self.subTest(files=files):
                self.admin(files=files)
                self.refused("watched_path_changed")
        self.admin(files=("administration/readme.md", "src/admin/page.cs"))
        self.assertEqual(self.last["outcome"], "satisfied")

    def test_a_service_at_the_repository_root_watches_every_path(self):
        rows = (watched("86ee94aa", MERGE, "SKIPPED", "2026-11-08T14:02:33Z", root=None),
                watched("10043c13", BASE_TIP, created="2026-11-08T04:05:53Z", root=None))
        self.admin(rows[1], skipped=rows[0])
        self.refused("watched_path_changed")
        self.admin(rows[1], skipped=rows[0], files=(), status="identical")
        self.assertEqual(self.last["outcome"], "satisfied")

    def test_a_skip_railway_does_not_attribute_to_watch_paths_stays_unexplained(self):
        for skipped in (None, "", "CI check suite failed", 7):
            with self.subTest(skipped=skipped):
                self.admin(skipped=watched("86ee94aa", MERGE, "SKIPPED", "2026-11-08T14:02:33Z",
                                           skipped=skipped))
                self.refused("skip_reason_unstated")
        self.assertEqual(self.compares(), [])
        self.assertEqual(UNWATCHED, adapter.SKIP_REASON_UNWATCHED)

    def test_watch_patterns_the_adapter_cannot_evaluate_stay_unexplained(self):
        for patterns, root in ((("/shared/**",), "admin"), (("**", "../api/**"), "admin"),
                               ("**", "admin"), (("**",), 7)):
            with self.subTest(patterns=patterns, root=root):
                self.admin(skipped=watched("86ee94aa", MERGE, "SKIPPED", "2026-11-08T14:02:33Z",
                                           patterns=patterns, root=root))
                self.refused("watch_patterns_unsupported")
        self.admin(watched("10043c13", BASE_TIP, created="2026-11-08T04:05:53Z", root="web"))
        self.refused("root_directory_changed")

    def test_an_unread_or_truncated_comparison_stays_unexplained(self):
        self.admin(exit=1, stdout="")
        self.refused("diff_unread")
        self.admin(stdout=json.dumps({"status": "ahead", "behind_by": 0,
                                      "merge_base_commit": {"sha": BASE_TIP}}))
        self.refused("diff_unread")
        self.admin(files=tuple(f"docs/{n}.md" for n in range(adapter.COMPARE_FILE_LIMIT)))
        self.refused("diff_over_limit")

    def test_absent_watch_patterns_cover_the_whole_root(self):
        bare = deployment("86ee94aa", MERGE, "SKIPPED", "2026-11-08T14:02:33Z",
                          meta={"commitHash": MERGE, "branch": "main", "rootDirectory": "admin",
                                "skippedReason": UNWATCHED})
        for name, skipped in (("null patterns",
                               watched("86ee94aa", MERGE, "SKIPPED", "2026-11-08T14:02:33Z",
                                       patterns=None)),
                              ("no manifest", bare)):
            with self.subTest(name):
                self.assertEqual(self.admin(skipped=skipped), ("satisfied", "skipped"))
                self.assertEqual(self.evidence(), ("watch_paths_unchanged", None))

    def test_a_config_file_outside_the_root_directory_is_watched(self):
        skipped = watched("86ee94aa", MERGE, "SKIPPED", "2026-11-08T14:02:33Z",
                          config="/deploy/admin.railway.toml")
        self.admin(skipped=skipped, files=(*NODO_DELTA, "deploy/admin.railway.toml"))
        self.refused("watched_path_changed")
        self.admin(skipped=skipped, files=NODO_DELTA)
        self.assertEqual(self.last["outcome"], "satisfied")

    def test_a_root_directory_written_with_slashes_is_the_same_root(self):
        skipped = watched("86ee94aa", MERGE, "SKIPPED", "2026-11-08T14:02:33Z", root="/admin/")
        serving = watched("10043c13", BASE_TIP, created="2026-11-08T04:05:53Z", root="admin")
        self.admin(serving, skipped=skipped, files=(*NODO_DELTA, "admin/src/App.tsx"))
        self.refused("watched_path_changed")
        self.assertEqual(self.admin(serving, skipped=skipped), ("satisfied", "skipped"))

    def test_a_comparison_status_other_than_ahead_or_identical_is_not_an_ancestor(self):
        for status in ("diverged", "behind"):
            with self.subTest(status=status):
                self.admin(status=status)
                self.refused("serving_not_ancestor")

    def test_the_comparison_file_limit_is_three_hundred(self):
        self.assertEqual(self.admin(files=tuple(f"docs/{n}.md" for n in range(299))),
                         ("satisfied", "skipped"))
        self.admin(files=tuple(f"docs/{n}.md" for n in range(300)))
        self.refused("diff_over_limit")

    def test_older_skipped_pushes_are_stepped_over(self):
        """Two releases in a row that leave the service alone: the comparison spans both."""
        self.assertEqual(self.admin(watched("skip1", HOTFIX, "SKIPPED", "2026-11-08T09:00:00Z"),
                                    watched("10043c13", BASE_TIP, created="2026-11-08T04:05:53Z")),
                         ("satisfied", "skipped"))

    def test_supersession_and_silent_rollback_are_judged_before_any_skip_evidence(self):
        self.world.deployments("admin", watched("new", OLDER, created="2026-11-08T15:00:00Z"),
                               watched("86ee94aa", MERGE, "SKIPPED", "2026-11-08T14:02:33Z"))
        self.assertEqual(adapter.inspect(request())["reason"], "superseded")
        self.world.deployments("admin", watched("86ee94aa", MERGE, "FAILED", "2026-11-08T14:02:33Z"),
                               watched("10043c13", BASE_TIP, created="2026-11-08T04:05:53Z"))
        self.assertEqual(adapter.inspect(request())["reason"], "silent_rollback")
        self.assertEqual(self.compares(), [])

    def test_one_comparison_serves_every_skipped_service(self):
        rows = (watched("s2", MERGE, "SKIPPED", "2026-11-08T14:02:33Z", root="api"),
                watched("s1", BASE_TIP, created="2026-11-08T04:05:53Z", root="api"))
        self.world.deployments("api", *rows)
        self.assertEqual(self.admin(), ("satisfied", "skipped"))
        self.assertEqual(len(self.compares()), 1)


class MergeTest(unittest.TestCase):
    def setUp(self):
        self.world = RailwayWorld(self)
        self.world.status()

    def merge_candidate(self):
        return {"version": "v1.2.3", "commit": HEAD, "merge": {"pr": PR, "base_tip": BASE_TIP}}

    def test_the_merge_commit_is_the_watched_commit(self):
        self.world.merged()
        self.world.deployments("api", deployment("d1", MERGE))
        self.world.deployments("admin", deployment("d2", MERGE))
        observation = adapter.inspect(request(self.merge_candidate()))
        self.assertEqual((observation["outcome"], observation["facts"]["released"]),
                         ("satisfied", MERGE))
        self.assertEqual([c["argv"] for c in self.world.calls("gh")], [PR_VIEW, commit_argv(MERGE)])

    def test_an_open_release_pr_reads_no_railway_state(self):
        self.world.merged(state="OPEN", oid=None)
        observation = adapter.inspect(request(self.merge_candidate()))
        self.assertEqual((observation["outcome"], observation["reason"]),
                         ("absent", "release_unmerged"))
        self.assertEqual(self.world.calls("railway"), [])


class FailureTest(unittest.TestCase):
    def test_a_failed_status_read_is_unknown_with_its_detail(self):
        world = RailwayWorld(self)
        world.respond("railway", ["status", "--json"], None, exit=1, stderr="Unauthorized")
        observation = adapter.inspect(request())
        self.assertEqual((observation["outcome"], observation["reason"]), ("unknown", "lookup_failed"))
        self.assertIn("Unauthorized", observation["facts"]["detail"])

    def test_a_missing_cli_is_executable_missing(self):
        RailwayWorld(self)
        empty = tempfile.TemporaryDirectory()
        self.addCleanup(empty.cleanup)
        with mock.patch.dict(os.environ, {"PATH": empty.name}):
            observation = adapter.inspect(request())
        self.assertEqual((observation["outcome"], observation["reason"]),
                         ("unknown", "executable_missing"))

    def test_one_budget_bounds_every_read(self):
        world = RailwayWorld(self)
        world.status()
        world.deployments("api", deployment("d1", MERGE), sleep=3)
        with mock.patch.object(adapter, "COLLECTION_BUDGET_SECONDS", 1):
            observation = adapter.inspect(request(services=["api"]))
        self.assertEqual((observation["outcome"], observation["reason"]),
                         ("unknown", "lookup_timeout"))


class RunningIdentityTest(unittest.TestCase):
    def setUp(self):
        self.world = RailwayWorld(self)
        self.world.status()

    def answer(self, value):
        observation = adapter.inspect(value)
        self.assertEqual(release_adapter.predicate_observation_problems(observation), [])
        if observation["outcome"] != "satisfied" and value["predicate"] == "running_subject_identity":
            self.assertIn(observation["reason"],
                          transaction_plan.DERIVED_REASONS["running_subject_identity"])
        return observation["outcome"], observation["reason"]

    def test_every_service_serving_the_released_commit_is_running(self):
        self.world.deployments("api", deployment("d1", MERGE))
        self.world.deployments("admin", deployment("d2", MERGE))
        self.assertEqual(self.answer(predicate()), ("satisfied", "running"))

    def test_a_service_serving_another_commit_is_a_subject_mismatch(self):
        self.world.deployments("api", deployment("d1", MERGE))
        self.world.deployments("admin", deployment("d3", MERGE, "FAILED", "2026-11-08T11:00:00Z"),
                               deployment("d2", OLDER))
        self.assertEqual(self.answer(predicate()), ("unsatisfied", "subject_mismatch"))

    def test_a_benign_skip_is_running_and_a_ci_failure_skip_is_a_mismatch(self):
        self.world.deployments("api", deployment("d1", MERGE))
        self.world.deployments("admin", deployment("d3", MERGE, "SKIPPED", "2026-11-08T11:00:00Z"),
                               deployment("d2", OLDER))
        self.world.check_runs(MERGE, GREEN)
        self.world.commit_parents(MERGE, OLDER)
        self.assertEqual(self.answer(predicate()), ("satisfied", "running"))
        self.world.check_runs(MERGE, RED)
        self.assertEqual(self.answer(predicate()), ("unsatisfied", "subject_mismatch"))
        self.world.check_runs(MERGE, RUNNING)
        self.assertEqual(self.answer(predicate()), ("unknown", "identity_unobservable"))

    def test_a_skip_without_code_evidence_is_never_running(self):
        self.world.deployments("api", deployment("d1", MERGE))
        self.world.check_runs(MERGE, GREEN)
        self.world.commit_parents(MERGE, OLDER)
        for older in ([deployment("d2", HOTFIX, "FAILED", "2026-11-08T10:30:00Z"),
                       deployment("d1o", OLDER, "SUCCESS", "2026-11-08T10:00:00Z")],
                      [deployment("d1o", None, "SUCCESS", "2026-11-08T10:00:00Z", meta=None)]):
            with self.subTest(older=[e["id"] for e in older]):
                self.world.deployments("admin",
                                       deployment("d3", MERGE, "SKIPPED", "2026-11-08T11:00:00Z"),
                                       *older)
                self.assertEqual(self.answer(predicate()), ("unknown", "identity_unobservable"))

    def test_an_unreadable_service_is_unobservable_and_other_predicates_unsupported(self):
        self.world.deployments("api", deployment("d1", MERGE))
        self.world.deployments("admin", exit=1, stdout="")
        self.assertEqual(self.answer(predicate()), ("unknown", "identity_unobservable"))
        self.assertEqual(self.answer(predicate(name="publication_visible")),
                         ("unknown", "predicate_unsupported"))


class CompiledRailwayWatchTest(unittest.TestCase):
    """AC3: the unit the release core compiles and binds is one the real adapter accepts."""

    def setUp(self):
        self.world = RailwayWorld(self)
        self.world.status()

    def bound(self, profile, candidate):
        compiled = release_profile.compile_profile("railway", profile, support.base_contract())
        inputs = release_profile.bind_candidate(compiled, candidate)
        unit = next(u["parameters"] for u in inputs["proof"]["units"] if u["name"] == "deploy")
        return unit, release_adapter.core_binding(adapter, compiled, "railway")

    def test_a_railway_watched_profile_compiles_and_its_unit_is_accepted(self):
        unit, binding = self.bound(support.railway_watched_profile(), dict(support.CANDIDATE))
        self.assertEqual(unit["target"], {"handle": "railway-site", "kind": "github_repository",
                                          "repository": SLUG, "branch": "main"})
        self.assertEqual(unit["config"], support.RAILWAY_CONFIG)
        commit = support.CANDIDATE["commit"]
        self.world.deployments("api", deployment("d1", commit))
        self.world.deployments("admin", deployment("d2", commit))
        result = binding.inspect({"parameters": unit})
        self.assertEqual((result["outcome"], json.loads(result["reference"])["reason"]),
                         ("satisfied", "deployed"))
        observed = binding.observe({"predicate": "running_subject_identity",
                                    "parameters": {"name": "deploy", "parameters": unit}})
        self.assertEqual((observed["outcome"], observed["reason"]), ("satisfied", "running"))

    def test_the_merge_shape_watches_the_merge_commit(self):
        candidate = {**support.CANDIDATE, "merge": dict(support.MERGE)}
        unit, binding = self.bound(support.railway_watched_merge_profile(), candidate)
        self.assertEqual(unit["candidate"]["merge"], support.MERGE)
        self.world.merged(parents=(support.MERGE["base_tip"], support.CANDIDATE["commit"]))
        self.world.deployments("api", deployment("d1", MERGE))
        self.world.deployments("admin", deployment("d2", MERGE, "FAILED"))
        result = binding.inspect({"parameters": unit})
        self.assertEqual((result["outcome"], json.loads(result["reference"])["reason"]),
                         ("diverged", "deployment_failed"))
