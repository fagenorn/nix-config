"""The railway-deploy watch adapter (issue 582 P1-P7). Run: just agent-workflow-tests"""
import json
import os
import tempfile
import unittest
from unittest import mock

from agent_tools import railway_deploy_adapter as adapter
from agent_tools import release_adapter, release_profile, transaction_plan
from . import release_test_support as support
from .railway_world import (BASE_TIP, CONFIG, GREEN, HEAD, HOTFIX, MERGE, OLDER, PR, PR_VIEW, RED,
                            RUNNING, SLUG, TIMED_OUT, RailwayWorld, commit_argv, deployment)

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
