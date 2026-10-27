"""The github-actions-health adapter (issue 465 D2, D6-D10, D14, D16). Run: just agent-workflow-tests"""
import json
import os
import tempfile
import time
import unittest
from unittest import mock

from agent_tools import actions_health_adapter as adapter
from agent_tools import release_adapter
from .actions_world import CONFIG, HOTFIX, MERGE, OLDER, RUN_LIST, SLUG, ActionsWorld, run

WATCH_SCHEMA = {"workflow": "string", "branch": "string", "services": "string_list",
                "health_url": "string", "health_commit_field": "string"}
REFUSED = {"result": "rejected", "error_class": "unsupported_operation",
           "reference": "deploy: bridge_watch_only"}


def request(commit: str = MERGE, **config: object) -> dict:
    return {"kind": "effect", "operation": "deploy", "parameters": {
        "target": {"kind": "github_repository", "repository": SLUG, "branch": "main"},
        "candidate": {"commit": commit}, "config": {**CONFIG, **config}}}


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
                         ("publication_triggered", "unsupported", "supported", "bridge_watch_only"))
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
        predicate = adapter.inspect({"kind": "predicate", "predicate": "running_subject_identity",
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
        self.assertEqual(sorted(facts), ["health", "run", "runs", "services"])
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


if __name__ == "__main__":
    unittest.main()
