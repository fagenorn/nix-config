"""The github-actions-health adapter (issue 465 D2, D6-D10, D14, D16). Run: just agent-workflow-tests"""
import json
import os
import tempfile
import time
import unittest
from unittest import mock

from agent_tools.release import actions_health_adapter as adapter
from agent_tools.release import release_adapter, release_profile, transaction_plan
from . import release_test_support as support
from .actions_world import (BASE_TIP, CONFIG, HEAD, HOTFIX, MERGE, OLDER, PR, PR_VIEW, RUN_LIST,
                            SLUG, ActionsWorld, commit_argv, run)

WATCH_SCHEMA = {"workflow": "string", "branch": "string", "services": "string_list",
                "health_url": "string", "health_commit_field": "string"}
REFUSED = {"result": "rejected", "error_class": "unsupported_operation",
           "reference": "deploy: watch_only"}


def request(commit: str = MERGE, **config: object) -> dict:
    return {"kind": "effect", "operation": "deploy", "parameters": {
        "target": {"kind": "github_repository", "repository": SLUG, "branch": "main"},
        "candidate": {"commit": commit}, "config": {**CONFIG, **config}}}


MERGE_MEMBER = {"pr": PR, "base_tip": BASE_TIP}


def bound(candidate: dict, **config: object) -> dict:
    """The request the release core sends: the compiled node's members plus a bound candidate."""
    value = request(**config)
    value["parameters"].update(action="deploy", operation="deploy", candidate=candidate)
    return value


def merge_candidate() -> dict:
    return {"version": "v1.2.3", "commit": HEAD, "merge": dict(MERGE_MEMBER)}


class AdapterContractTest(unittest.TestCase):
    def test_string_list_is_a_closed_config_type(self):
        schema = {"members": {"services": "string_list"}, "required": ["services"]}
        self.assertEqual(release_adapter.config_problems(schema, {"services": ["jarbird", "caddy"]}),
                         [])
        for value in ([], ["a", "a"], ["a", ""], "jarbird", ["a", 1], None):
            with self.subTest(value=value):
                self.assertEqual(release_adapter.config_problems(schema, {"services": value}),
                                 ["config member 'services' must be a string_list"])

    def test_the_registry_carries_one_watch_operation(self):
        descriptor = adapter.describe()
        self.assertEqual(release_adapter.descriptor_problems(descriptor), [])
        self.assertIs(release_adapter.REGISTRY["github-actions-health"], adapter)
        self.assertEqual(release_adapter.DESCRIPTORS["github-actions-health"], descriptor)
        deploy = descriptor["operations"]["deploy"]
        self.assertEqual((deploy["mode"], deploy["support"], deploy["inspect"], deploy["reason"]),
                         ("publication_triggered", "supported", "supported", None))
        self.assertEqual(deploy["config_schema"]["members"], WATCH_SCHEMA)
        self.assertEqual(sorted(deploy["config_schema"]["required"]), sorted(WATCH_SCHEMA))
        self.assertEqual(release_adapter.config_problems(deploy["config_schema"], CONFIG), [])
        self.assertEqual((descriptor["executables"], descriptor["credential_classes"]),
                         (["gh"], ["gh_cli"]))
        self.assertEqual(release_adapter.watch_operation(descriptor), "deploy")
        self.assertIsNone(release_adapter.watch_operation(
            release_adapter.DESCRIPTORS["github-forge"]))

    def test_invoke_refuses_every_request_without_a_child(self):
        world = ActionsWorld(self)
        for value in (request(), {}, None):
            with self.subTest(value=value):
                self.assertEqual(adapter.invoke(value), REFUSED)
        self.assertEqual(release_adapter.invoke_result_problems(adapter.invoke(request())), [])
        self.assertEqual(world.calls(), [])

    def test_a_request_outside_the_closed_shape_spawns_nothing(self):
        world = ActionsWorld(self)
        extra = request()
        extra["parameters"]["pr"] = 1
        cases = {"branch differs from the target": request(branch="dev"),
                 "file url": request(health_url="file:///etc/passwd"),
                 "url without a host": request(health_url="https:///health"),
                 "unparseable url": request(health_url="https://["),
                 "short candidate": request(commit=MERGE[:7]),
                 "upper-case candidate": request(commit=MERGE.upper()),
                 "empty services": request(services=[]),
                 "undeclared config member": request(region="eu"),
                 "empty workflow": request(workflow=""),
                 "NUL in workflow": request(workflow="deploy\x00.yml"),
                 "newline in health field": request(health_commit_field="com\nmit"),
                 "unknown parameter": extra,
                 "unknown operation": dict(request(), operation="tag"),
                 "not a request": []}
        for name, value in cases.items():
            with self.subTest(name):
                observation = adapter.inspect(value)
                self.assertEqual((observation["outcome"], observation["reason"]),
                                 ("unknown", "parameters_invalid"))
                self.assertTrue(observation["facts"]["detail"])
                self.assertEqual(release_adapter.effect_observation_problems(observation), [])
        predicate = adapter.inspect({"kind": "predicate", "predicate": "publication_visible",
                                     "operation": "deploy", "parameters": request()["parameters"]})
        self.assertEqual((predicate["outcome"], predicate["reason"]),
                         ("unknown", "predicate_unsupported"))
        self.assertEqual(release_adapter.predicate_observation_problems(predicate), [])
        self.assertEqual(world.calls(), [])


class ClassificationTest(unittest.TestCase):
    def setUp(self):
        self.world = ActionsWorld(self)

    def observe(self, *runs: dict, **health: object) -> dict:
        self.world.runs(*runs)
        self.world.routes.pop("/health", None)
        if health:
            self.world.health(**health)
        observation = adapter.inspect(request(health_url=self.world.url()))
        self.assertEqual(release_adapter.effect_observation_problems(observation), [])
        return observation

    def verdict(self, *runs: dict, **health: object) -> tuple[str, str]:
        observation = self.observe(*runs, **health)
        return observation["outcome"], observation["reason"]

    def test_satisfied_needs_a_successful_run_and_a_matching_health_commit(self):
        self.assertEqual(self.verdict(run(8, MERGE), commit=MERGE), ("satisfied", "deployed"))
        self.assertEqual(self.verdict(run(8, MERGE), commit=MERGE[:7]), ("satisfied", "deployed"))
        self.assertEqual(self.verdict(run(8, MERGE), commit=MERGE[:12].upper()),
                         ("satisfied", "deployed"))
        self.assertEqual(self.verdict(run(8, MERGE), commit=OLDER),
                         ("diverged", "health_commit_mismatch"))
        self.assertEqual(self.verdict(run(8, MERGE), commit=MERGE[:6]),
                         ("unknown", "health_payload_invalid"))
        self.assertEqual(self.verdict(run(8, MERGE, conclusion="failure"), commit=MERGE),
                         ("diverged", "run_failed"))

    def test_intermediate_rows_never_read_health(self):
        self.assertEqual(self.verdict(run(7, OLDER)), ("absent", "run_absent"))
        self.assertEqual(self.verdict(), ("absent", "run_absent"))
        for status in ("queued", "in_progress", "waiting"):
            with self.subTest(status=status):
                observation = self.observe(run(8, MERGE, status=status), commit=MERGE)
                self.assertEqual((observation["outcome"], observation["reason"]),
                                 ("in_progress", "run_in_progress"))
                self.assertEqual(observation["facts"]["run"]["status"], status)
                self.assertIsNone(observation["facts"]["health"])
        self.assertEqual(self.world.requests, [])

    def test_a_failed_run_is_a_silent_rollback_only_while_an_older_commit_serves(self):
        for conclusion in ("failure", "timed_out", "cancelled"):
            with self.subTest(conclusion=conclusion):
                self.assertEqual(self.verdict(run(8, MERGE, conclusion=conclusion), commit=OLDER),
                                 ("diverged", "silent_rollback"))
                self.assertEqual(
                    self.verdict(run(8, MERGE, conclusion=conclusion), status=503, body=b"down"),
                    ("diverged", "run_failed"))

    def test_only_the_newest_run_at_the_merge_commit_decides(self):
        stale_failure = run(8, MERGE, conclusion="failure")
        newer_success = run(9, MERGE, created="2026-10-27T11:00:00Z")
        observation = self.observe(stale_failure, newer_success, commit=MERGE)
        self.assertEqual((observation["outcome"], observation["reason"]), ("satisfied", "deployed"))
        self.assertEqual([entry["id"] for entry in observation["facts"]["runs"]], [9, 8])
        self.assertEqual(observation["facts"]["run"]["id"], 9)
        newer_failure = run(9, MERGE, conclusion="failure", created="2026-10-27T11:00:00Z")
        self.assertEqual(self.verdict(run(8, MERGE), newer_failure, commit=OLDER),
                         ("diverged", "silent_rollback"))
        other_branch = run(9, MERGE, branch="release", created="2026-10-27T11:00:00Z")
        observation = self.observe(other_branch, run(8, MERGE), commit=MERGE)
        self.assertEqual((observation["outcome"], observation["facts"]["run"]["id"]),
                         ("satisfied", 8))
        offset = run(9, OLDER, created="2026-10-27T11:00:00+02:00")  # 09:00Z, before run 8
        self.assertEqual([entry["id"] for entry in self.observe(offset, run(8, MERGE),
                                                                 commit=MERGE)["facts"]["runs"]],
                         [8, 9])

    def test_a_newer_run_supersedes_only_a_completed_unsatisfied_run(self):
        hotfix = run(9, HOTFIX, status="queued", created="2026-10-27T11:00:00Z")
        self.assertEqual(self.verdict(hotfix, run(8, MERGE, conclusion="cancelled"), commit=OLDER),
                         ("diverged", "superseded"))
        self.assertEqual(self.verdict(run(9, HOTFIX, created="2026-10-27T11:00:00Z"), run(8, MERGE),
                                      commit=HOTFIX),
                         ("diverged", "superseded"))
        self.assertEqual(self.verdict(hotfix, run(8, MERGE), commit=MERGE),
                         ("satisfied", "deployed"))
        self.assertEqual(self.verdict(hotfix, run(8, MERGE, status="in_progress")),
                         ("in_progress", "run_in_progress"))

    def test_the_observation_names_the_run_the_health_read_and_the_services(self):
        observation = self.observe(run(7, OLDER, created="2026-10-27T09:00:00Z"), run(8, MERGE),
                                   commit=MERGE)
        self.assertEqual(observation["observed_subject"], {"commit": MERGE, "run": 8})
        self.assertEqual(observation["references"],
                         [f"repos/{SLUG}/actions/runs/8", self.world.url()])
        facts = observation["facts"]
        self.assertEqual(sorted(facts), ["health", "released", "run", "runs", "services"])
        self.assertEqual(facts["released"], MERGE)
        self.assertEqual(facts["services"], CONFIG["services"])
        self.assertEqual(facts["run"], {"id": 8, "status": "success", "commit": MERGE,
                                        "branch": "main", "createdAt": "2026-10-27T10:00:00Z"})
        self.assertEqual([entry["id"] for entry in facts["runs"]], [8, 7])
        self.assertEqual(facts["health"], {"status": "ok", "http_status": 200, "commit": MERGE,
                                           "detail": None})
        headers = self.world.requests[-1]["headers"]
        self.assertEqual((self.world.requests[-1]["path"], headers["Accept"],
                          headers["Cache-Control"], headers["User-Agent"]),
                         ("/health", "application/json", "no-cache", adapter.USER_AGENT))
        self.assertEqual([call["argv"] for call in self.world.calls()], [RUN_LIST])
        self.assertTrue(self.world.calls()[0]["token_visible"])  # the adapter strips nothing (D10)

    def test_a_health_read_is_one_strict_bounded_get(self):
        self.world.health(path="/moved", commit=MERGE)
        nan = b'{"commit": "%s", "load": NaN}' % MERGE.encode()
        twice = b'{"commit": "%s", "commit": "%s"}' % (MERGE.encode(), MERGE.encode())
        cases = {
            "503": (dict(status=503, body=b"maintenance"), "health_unreachable"),
            "redirect": (dict(status=302, body=b"", headers={"Location": "/moved"}),
                         "health_unreachable"),
            "204": (dict(status=204, body=b""), "health_unreachable"),
            "html": (dict(body=b"<html>ok</html>"), "health_payload_invalid"),
            "array": (dict(body=json.dumps([MERGE]).encode()), "health_payload_invalid"),
            "missing field": (dict(body=b'{"sha": "%s"}' % MERGE.encode()),
                              "health_payload_invalid"),
            "duplicate key": (dict(body=twice), "health_payload_invalid"),
            "nan": (dict(body=nan), "health_payload_invalid"),
            "oversized": (dict(body=json.dumps({"commit": MERGE, "pad": "x" * 65536}).encode()),
                          "health_payload_invalid"),
        }
        for name, (health, reason) in cases.items():
            with self.subTest(name):
                observation = self.observe(run(8, MERGE), **health)
                self.assertEqual((observation["outcome"], observation["reason"]),
                                 ("unknown", reason))
                self.assertEqual(observation["facts"]["health"]["status"], reason)
                self.assertTrue(observation["facts"]["health"]["detail"])
                self.assertLessEqual(len(observation["facts"]["health"]["detail"]), 240)
        unreachable = self.observe(run(8, MERGE), status=503, body=b"maintenance")
        self.assertEqual(unreachable["facts"]["health"]["http_status"], 503)
        self.assertIn("maintenance", unreachable["facts"]["health"]["detail"])
        self.assertNotIn("/moved", [entry["path"] for entry in self.world.requests])
        self.world.runs(run(8, MERGE))
        closed = adapter.inspect(request(health_url="http://127.0.0.1:9/health"))
        self.assertEqual((closed["outcome"], closed["reason"]), ("unknown", "health_unreachable"))

    def test_an_argument_the_os_cannot_pass_is_a_failed_lookup_not_a_raise(self):
        observation = adapter.inspect(request(workflow="deploy\ud800.yml",
                                              health_url=self.world.url()))
        self.assertEqual((observation["outcome"], observation["reason"]),
                         ("unknown", "lookup_failed"))
        self.assertTrue(observation["facts"]["detail"])
        self.assertEqual(release_adapter.effect_observation_problems(observation), [])
        self.assertEqual(self.world.calls(), [])

    def test_a_failed_run_list_is_unknown_with_its_detail(self):
        self.world.runs(exit=1, stdout="", stderr="HTTP 502: Bad Gateway")
        observation = adapter.inspect(request(health_url=self.world.url()))
        self.assertEqual((observation["outcome"], observation["reason"],
                          observation["facts"]["detail"]),
                         ("unknown", "lookup_failed", "HTTP 502: Bad Gateway"))
        bad_entries = {"not json": None, "not a list": {},
                       "zero id": [dict(run(8, MERGE), databaseId=0)],
                       "short sha": [dict(run(8, MERGE), headSha=MERGE[:7])],
                       "naive time": [run(8, MERGE, created="2026-10-27T10:00:00")],
                       "prose time": [run(8, MERGE, created="yesterday")],
                       "completed without conclusion": [dict(run(8, MERGE), conclusion="")]}
        for name, entries in bad_entries.items():
            with self.subTest(name):
                self.world.runs(stdout="not json" if entries is None else json.dumps(entries))
                observation = adapter.inspect(request(health_url=self.world.url()))
                self.assertEqual((observation["outcome"], observation["reason"]),
                                 ("unknown", "payload_invalid"))
                self.assertEqual(observation["facts"]["services"], CONFIG["services"])
        self.assertEqual(self.world.requests, [])

    def test_one_collection_budget_bounds_both_reads(self):
        with mock.patch.object(adapter, "COLLECTION_BUDGET_SECONDS", 1):
            self.world.runs(run(8, MERGE), sleep=2)
            slow_list = adapter.inspect(request(health_url=self.world.url()))
            self.assertEqual((slow_list["outcome"], slow_list["reason"]),
                             ("unknown", "lookup_timeout"))
            self.world.runs(run(8, MERGE))
            self.world.health(commit=MERGE, delay=2)
            slow_health = adapter.inspect(request(health_url=self.world.url()))
            self.assertEqual((slow_health["outcome"], slow_health["reason"]),
                             ("unknown", "health_unreachable"))
        with mock.patch.object(adapter, "COLLECTION_BUDGET_SECONDS", 3):
            for name, status, delay, body_delay in (("trickled body", 200, 1.0, 2.5),
                                                    ("stalled error body", 503, 0, 4)):
                with self.subTest(name):
                    self.world.runs(run(8, MERGE))
                    self.world.health(status, body=b"maintenance" if status != 200 else None,
                                      commit=MERGE, delay=delay, body_delay=body_delay)
                    started = time.monotonic()
                    observation = adapter.inspect(request(health_url=self.world.url()))
                    self.assertLess(time.monotonic() - started, 3.4)
                    self.assertEqual((observation["outcome"], observation["reason"]),
                                     ("unknown", "health_unreachable"))
                    self.assertEqual(observation["facts"]["health"]["http_status"], status)
                    self.assertTrue(observation["facts"]["health"]["detail"])
        empty = tempfile.TemporaryDirectory()
        self.addCleanup(empty.cleanup)
        with mock.patch.dict(os.environ, {"PATH": empty.name}):
            missing = adapter.inspect(request(health_url=self.world.url()))
        self.assertEqual((missing["outcome"], missing["reason"]), ("unknown", "executable_missing"))

    def test_the_two_reads_share_the_budget(self):
        """Each read fits the budget alone, but the health read gets only what the list left."""
        with mock.patch.object(adapter, "COLLECTION_BUDGET_SECONDS", 3):
            self.world.runs(run(8, MERGE), sleep=2)
            self.world.health(commit=MERGE, delay=2)
            started = time.monotonic()
            observation = adapter.inspect(request(health_url=self.world.url()))
            self.assertLess(time.monotonic() - started, 3.4)
        self.assertEqual((observation["outcome"], observation["reason"]),
                         ("unknown", "health_unreachable"))
        self.assertEqual(len(self.world.calls()), 1)
        self.assertEqual([seen["path"] for seen in self.world.requests], ["/health"])


class WatchBindingTest(unittest.TestCase):
    """Issue 555 D3, D6: `deploy` binds as a watch-only activation unit of a release profile."""

    def setUp(self):
        self.world = ActionsWorld(self)

    def argvs(self) -> list[list[str]]:
        return [call["argv"] for call in self.world.calls()]

    def verdict(self, candidate: dict) -> tuple[str, str]:
        observation = adapter.inspect(bound(candidate, health_url=self.world.url()))
        self.assertEqual(release_adapter.effect_observation_problems(observation), [])
        return observation["outcome"], observation["reason"]

    def predicate(self, candidate: dict, name: str = "running_subject_identity") -> tuple[str, str]:
        observation = adapter.inspect({"kind": "predicate", "predicate": name, "operation": "deploy",
                                       "parameters": bound(candidate, health_url=self.world.url())
                                       ["parameters"]})
        self.assertEqual(release_adapter.predicate_observation_problems(observation), [])
        if name == "running_subject_identity" and observation["outcome"] != "satisfied":
            self.assertIn(observation["reason"],
                          transaction_plan.DERIVED_REASONS["running_subject_identity"])
        return observation["outcome"], observation["reason"]

    def test_deploy_is_bindable_answers_the_activation_predicate_and_is_never_invoked(self):
        descriptor = adapter.describe()
        deploy = descriptor["operations"]["deploy"]
        self.assertEqual((descriptor["adapter_contract_version"], deploy["mode"], deploy["support"],
                          deploy["reason"], deploy["candidate_members"]),
                         ("1.1.0", "publication_triggered", "supported", None, []))
        self.assertEqual(descriptor["predicates"]["running_subject_identity"],
                         {"support": "supported", "reason": None})
        self.assertEqual(descriptor["predicates"]["publication_visible"]["support"], "unsupported")
        self.assertEqual(release_adapter.descriptor_problems(descriptor), [])
        self.assertEqual(release_adapter.watch_operation(descriptor), "deploy")
        self.assertEqual(adapter.invoke(bound(merge_candidate())), REFUSED)
        self.assertEqual(self.world.calls(), [])

    def test_a_bound_candidate_is_judged_like_the_bridge_candidate(self):
        self.world.runs(run(8, MERGE))
        self.world.health(commit=MERGE)
        for candidate in ({"commit": MERGE}, {"version": "v1.2.3", "commit": MERGE}):
            with self.subTest(candidate=candidate):
                observation = adapter.inspect(bound(candidate, health_url=self.world.url()))
                self.assertEqual((observation["outcome"], observation["reason"]),
                                 ("satisfied", "deployed"))
                self.assertEqual(observation["facts"]["released"], MERGE)
        self.assertEqual(self.argvs(), [RUN_LIST, RUN_LIST])
        for candidate in ({"version": "1.2.3", "commit": MERGE}, {"version": "v1.2.3"},
                          {"version": "v1.2.3", "commit": MERGE, "notes": "x"},
                          {"version": "v1.2.3", "commit": MERGE, "merge": {"pr": 0, "base_tip": BASE_TIP}},
                          {"version": "v1.2.3", "commit": MERGE, "merge": {"pr": True, "base_tip": BASE_TIP}},
                          {"version": "v1.2.3", "commit": MERGE, "merge": {"pr": PR}},
                          {"commit": MERGE, "merge": dict(MERGE_MEMBER)}):
            with self.subTest(candidate=candidate):
                self.assertEqual(self.verdict(candidate), ("unknown", "parameters_invalid"))
        self.assertEqual(len(self.world.calls()), 2)

    def test_with_a_merge_binding_the_released_commit_is_the_merge_commit(self):
        self.world.merged()
        self.world.runs(run(9, MERGE))
        self.world.health(commit=MERGE)
        observation = adapter.inspect(bound(merge_candidate(), health_url=self.world.url()))
        self.assertEqual((observation["outcome"], observation["reason"]), ("satisfied", "deployed"))
        self.assertEqual(observation["facts"]["released"], MERGE)
        self.assertEqual(observation["observed_subject"], {"commit": MERGE, "run": 9})
        self.assertEqual(observation["references"][:3],
                         [f"repos/{SLUG}/pulls/{PR}", f"repos/{SLUG}/git/commits/{MERGE}",
                          f"repos/{SLUG}/actions/runs/9"])
        self.assertEqual(self.argvs(), [PR_VIEW, commit_argv(MERGE), RUN_LIST])
        self.world.health(commit=HEAD)
        self.assertEqual(self.verdict(merge_candidate()), ("diverged", "health_commit_mismatch"))

    def test_an_unresolved_merge_reads_neither_runs_nor_health(self):
        self.world.runs(run(9, MERGE))
        self.world.health(commit=MERGE)
        cases = ((dict(state="OPEN", oid=None), ("absent", "release_unmerged")),
                 (dict(state="CLOSED", oid=None), ("diverged", "release_merge_mismatch")),
                 (dict(base="dev"), ("diverged", "release_merge_mismatch")),
                 (dict(parents=(OLDER, HEAD)), ("diverged", "release_merge_mismatch")),
                 (dict(parents=(HEAD, BASE_TIP)), ("diverged", "release_merge_mismatch")),
                 (dict(state="DRAFT", oid=None), ("unknown", "payload_invalid")))
        for kwargs, expected in cases:
            with self.subTest(**{key: str(value) for key, value in kwargs.items()}):
                self.world.merged(**kwargs)
                self.assertEqual(self.verdict(merge_candidate()), expected)
        self.world.respond(PR_VIEW, None, exit=1, stderr="HTTP 502")
        observation = adapter.inspect(bound(merge_candidate(), health_url=self.world.url()))
        self.assertEqual((observation["outcome"], observation["reason"]), ("unknown", "lookup_failed"))
        self.assertIn("HTTP 502", observation["facts"]["detail"])
        self.assertIsNone(observation["facts"]["released"])
        self.assertNotIn(RUN_LIST, self.argvs())
        self.assertEqual(self.world.requests, [])

    def test_running_subject_identity_reads_the_health_commit_of_the_released_commit(self):
        plain = {"version": "v1.2.3", "commit": MERGE}
        self.world.health(commit=MERGE[:12])
        self.assertEqual(self.predicate(plain), ("satisfied", "running"))
        self.world.health(commit=OLDER)
        self.assertEqual(self.predicate(plain), ("unsatisfied", "subject_mismatch"))
        self.world.health(status=503, body=b"down")
        self.assertEqual(self.predicate(plain), ("unknown", "identity_unobservable"))
        self.world.merged()
        self.world.health(commit=MERGE)
        self.assertEqual(self.predicate(merge_candidate()), ("satisfied", "running"))
        self.world.health(commit=HEAD)
        self.assertEqual(self.predicate(merge_candidate()), ("unsatisfied", "subject_mismatch"))
        self.world.merged(state="OPEN", oid=None)
        self.assertEqual(self.predicate(merge_candidate()), ("unknown", "identity_unobservable"))
        self.assertEqual(self.predicate(plain, "publication_visible"),
                         ("unknown", "predicate_unsupported"))
        self.assertEqual(self.predicate({"version": "1.2.3", "commit": MERGE}),
                         ("unknown", "identity_unobservable"))
        wrong = adapter.inspect({"kind": "predicate", "predicate": "running_subject_identity",
                                 "operation": "release",
                                 "parameters": bound(plain, health_url=self.world.url())["parameters"]})
        self.assertEqual((wrong["outcome"], wrong["reason"]), ("unknown", "identity_unobservable"))
        self.assertNotIn(RUN_LIST, self.argvs())


class CompiledWatchTest(unittest.TestCase):
    """Issue 555 D9: the unit the release core compiles and binds is one the real adapter accepts."""

    def setUp(self):
        self.world = ActionsWorld(self)
        self.compiled = release_profile.compile_profile(
            "watched", support.watched_profile(health_url=self.world.url()), support.base_contract())
        inputs = release_profile.bind_candidate(self.compiled, dict(support.CANDIDATE))
        self.unit = next(unit["parameters"] for unit in inputs["proof"]["units"]
                         if unit["name"] == "deploy")
        self.binding = release_adapter.core_binding(adapter, self.compiled, "watch")

    def test_the_bound_target_carries_the_handle_and_is_accepted(self):
        self.assertEqual(self.unit["target"], {"handle": "site", "kind": "github_repository",
                                               "repository": SLUG, "branch": "main"})
        commit = support.CANDIDATE["commit"]
        self.world.runs(run(9, commit))
        self.world.health(commit=commit)
        result = self.binding.inspect({"parameters": self.unit})
        self.assertEqual(result["outcome"], "satisfied")
        self.assertEqual(json.loads(result["reference"])["reason"], "deployed")
        observed = self.binding.observe({"predicate": "running_subject_identity",
                                         "parameters": {"name": "deploy", "parameters": self.unit}})
        self.assertEqual((observed["outcome"], observed["reason"]), ("satisfied", "running"))
        self.world.health(commit=OLDER)
        observed = self.binding.observe({"predicate": "running_subject_identity",
                                         "parameters": {"name": "deploy", "parameters": self.unit}})
        self.assertEqual((observed["outcome"], observed["reason"]), ("unsatisfied", "subject_mismatch"))

    def test_a_merge_bound_unit_watches_the_merge_commit_through_the_core_binding(self):
        compiled = release_profile.compile_profile(
            "watched", support.watched_merge_profile(health_url=self.world.url()),
            support.base_contract())
        inputs = release_profile.bind_candidate(compiled, {**support.CANDIDATE, "merge": support.MERGE})
        unit = next(unit["parameters"] for unit in inputs["proof"]["units"] if unit["name"] == "deploy")
        binding = release_adapter.core_binding(adapter, compiled, "watch")
        self.world.merged(parents=(support.MERGE["base_tip"], support.CANDIDATE["commit"]))
        self.world.runs(run(9, MERGE))
        self.world.health(commit=MERGE)
        result = binding.inspect({"parameters": unit})
        self.assertEqual(result["outcome"], "satisfied")
        self.assertEqual(json.loads(result["reference"])["references"][:2],
                         [f"repos/{SLUG}/pulls/{support.MERGE['pr']}",
                          f"repos/{SLUG}/git/commits/{MERGE}"])
        observed = binding.observe({"predicate": "running_subject_identity",
                                    "parameters": {"name": "deploy", "parameters": unit}})
        self.assertEqual((observed["outcome"], observed["reason"]), ("satisfied", "running"))
        self.assertEqual([call["argv"] for call in self.world.calls()][:3],
                         [PR_VIEW, commit_argv(MERGE), RUN_LIST])

    def test_a_handle_that_is_not_a_non_empty_string_is_parameters_invalid(self):
        for handle in ("", 7, None):
            with self.subTest(handle=handle):
                value = request(health_url=self.world.url())
                value["parameters"]["target"]["handle"] = handle
                observation = adapter.inspect(value)
                self.assertEqual((observation["outcome"], observation["reason"]),
                                 ("unknown", "parameters_invalid"))
        self.assertEqual(self.world.calls(), [])


if __name__ == "__main__":
    unittest.main()
