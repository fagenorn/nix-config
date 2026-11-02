"""The codesigned-artifact adapter (issue 547). Run: just agent-workflow-tests"""
import ast
import inspect as introspect
import unittest
from unittest import mock

from agent_tools import codesigned_artifact_adapter as adapter, release_adapter
from .host_world import IDENTITY, HostWorld

PATH = "~/Library/Application Support/Notifier/Notifier.app"
CONFIG = {"source": "build/Notifier.app", "identity_prefix": "Apple Development",
          "identity_env": "NOTIFIER_SIGNING_IDENTITY", "adhoc_fallback": False}
DESCRIPTOR = {"name": "codesigned-artifact", "adapter_contract_version": "1.0.0",
              "operations": {"install": {
                  "mode": "materialize", "support": "supported", "inspect": "supported",
                  "reason": None, "mutability": "in_place", "config_schema_version": 1,
                  "config_schema": {"members": {"adhoc_fallback": "boolean", "identity_env": "string",
                                                "identity_prefix": "string", "source": "string"},
                                    "required": ["adhoc_fallback", "identity_prefix", "source"]},
                  "effects": ["reversible_no_incremental_spend", "irreversible"],
                  "recovery_capable": False, "candidate_members": []}},
              "predicates": {"publication_visible": {"support": "supported", "reason": None},
                             "running_subject_identity": {"support": "unsupported",
                                                          "reason": "no_activation_mode"}},
              "collector": {"max_collection_latency_ms": 30000, "max_concurrent_collections": 1},
              "target_kinds": {"installed_bundle": ["path"]},
              "credential_classes": ["codesigning_identity"],
              "executables": ["codesign", "git", "security"], "host_capacity": "not_required"}


class Case(unittest.TestCase):
    def setUp(self):
        self.world = HostWorld(self)
        self.world.environ(NOTIFIER_SIGNING_IDENTITY=None)
        self.world.identities(IDENTITY)
        self.candidate = {"version": "v1.2.3", "commit": self.world.head()}

    def parameters(self, **config):
        return {"action": "notifier", "operation": "install",
                "target": {"handle": "notifier", "kind": "installed_bundle", "path": PATH},
                "candidate": dict(self.candidate), "config": {**CONFIG, **config}}

    def effect(self, parameters=None):
        return adapter.inspect({"kind": "effect", "operation": "install",
                                "parameters": parameters or self.parameters()})

    def visible(self, parameters=None):
        return adapter.inspect({"kind": "predicate", "predicate": "publication_visible",
                                "operation": "install", "parameters": parameters or self.parameters()})

    def install(self, stamp="candidate", identity=IDENTITY[0]):
        stamp = (self.candidate["version"], self.candidate["commit"]) if stamp == "candidate" else stamp
        return self.world.installed(PATH[2:], stamp=stamp, identity=identity)


class DescribeTest(Case):
    def test_descriptor_is_exact_valid_and_fresh(self):
        self.assertEqual(adapter.describe(), DESCRIPTOR)
        self.assertEqual(release_adapter.descriptor_problems(adapter.describe()), [])
        adapter.describe()["operations"].clear()
        self.assertEqual(adapter.describe(), DESCRIPTOR)
        self.assertNotIn("codesigned-artifact", release_adapter.REGISTRY)


class ClassificationTest(Case):
    def test_each_row_of_the_inspect_table(self):
        def tamper():
            path = self.install()
            (path / "Contents/MacOS/notifier").write_bytes(b"changed")
        rows = (
            ("no entry", lambda: None, ("absent", "bundle_absent"), ("unsatisfied", "ref_absent")),
            ("symlink", lambda: (self.world.home / PATH[2:]).parent.mkdir(parents=True) or
             (self.world.home / PATH[2:]).symlink_to(self.world.checkout),
             ("diverged", "target_unexpected"), ("unsatisfied", "subject_mismatch")),
            ("regular file", lambda: (self.world.home / PATH[2:]).parent.mkdir(parents=True) or
             (self.world.home / PATH[2:]).write_text("x"),
             ("diverged", "target_unexpected"), ("unsatisfied", "subject_mismatch")),
            ("no stamp", lambda: self.install(stamp=None), ("absent", "bundle_unmanaged"),
             ("unsatisfied", "subject_mismatch")),
            ("other release", lambda: self.install(stamp=("v1.2.2", "f" * 40)),
             ("absent", "bundle_other_release"), ("unsatisfied", "subject_mismatch")),
            ("unsigned", lambda: self.install(identity=None), ("diverged", "signature_invalid"),
             ("unsatisfied", "digest_mismatch")),
            ("tampered", tamper, ("diverged", "signature_invalid"), ("unsatisfied", "digest_mismatch")),
            ("ad hoc refused", lambda: self.install(identity="-"), ("diverged", "signature_policy"),
             ("unsatisfied", "subject_mismatch")),
            ("signed", lambda: self.install(), ("satisfied", "installed"), ("satisfied", "installed")),
            ("verify exit 2", lambda: self.install() and self.world.fail("codesign", "verify", exit=2),
             ("unknown", "lookup_failed"), ("unknown", "store_unreachable")),
            ("display fails", lambda: self.install() and self.world.fail("codesign", "display", exit=1),
             ("unknown", "lookup_failed"), ("unknown", "store_unreachable")),
            ("codesign missing", lambda: self.install() and (self.world.bin / "codesign").unlink(),
             ("unknown", "executable_missing"), ("unknown", "store_unreachable")))
        for name, arrange, effect, visible in rows:
            with self.subTest(row=name):
                self.setUp()
                arrange()
                before = self.world.tree()
                observed = self.effect()
                self.assertEqual((observed["outcome"], observed["reason"]), effect)
                self.assertEqual(release_adapter.effect_observation_problems(observed), [])
                predicate = self.visible()
                self.assertEqual((predicate["outcome"], predicate["reason"]), visible)
                self.assertEqual(sorted(predicate), ["observed_at", "outcome", "reason", "references"])
                self.assertEqual(release_adapter.predicate_observation_problems(predicate), [])
                self.assertEqual(self.world.tree(), before)
                self.assertEqual({c["tool"] for c in self.world.calls()} - {"codesign"}, set())

    def test_ad_hoc_is_installed_when_the_policy_allows_it(self):
        self.install(identity="-")
        observed = self.effect(self.parameters(adhoc_fallback=True))
        self.assertEqual((observed["outcome"], observed["reason"]), ("satisfied", "installed"))
        self.assertEqual(observed["facts"]["signature"],
                         {"identifier": "dev.example.notifier", "authority": None,
                          "team_identifier": None, "adhoc": True})

    def test_a_verify_past_the_budget_is_lookup_timeout(self):
        self.install()
        self.world.fail("codesign", "verify", exit=0, sleep=3)
        with mock.patch.object(adapter, "INSPECT_BUDGET_SECONDS", 1):
            observed = self.effect()
        self.assertEqual((observed["outcome"], observed["reason"]), ("unknown", "lookup_timeout"))
        self.assertEqual(observed["facts"]["detail"], "")


class ObservationTest(Case):
    def test_a_satisfied_observation_carries_stamp_and_signature(self):
        path = str(self.world.home / PATH[2:])
        self.install()
        observed = self.effect()
        self.assertEqual(observed["observed_subject"], {
            "version": "v1.2.3", "commit": self.world.head(), "identifier": "dev.example.notifier",
            "authority": IDENTITY[1]})
        self.assertEqual(observed["references"], [path])
        self.assertEqual(observed["facts"], {
            "path": path, "stamp": {"version": "v1.2.3", "commit": self.world.head()},
            "signature": {"identifier": "dev.example.notifier", "authority": IDENTITY[1],
                          "team_identifier": "TEAMID0001", "adhoc": False}})

    def test_stderr_detail_is_bounded(self):
        self.install()
        self.world.fail("codesign", "verify", exit=2, stderr="e" * 1000)
        self.assertEqual(len(self.effect()["facts"]["detail"]), 240)


class ShapeTest(Case):
    def test_requests_outside_the_closed_shape_start_no_child(self):
        def with_(mutate):
            parameters = self.parameters()
            mutate(parameters)
            return parameters

        def path(value):
            return lambda p: p["target"].update(path=value)

        mutations = {
            "target kind": lambda p: p["target"].update(kind="github_repository"),
            "target extra": lambda p: p["target"].update(domain="gui/501"),
            "absolute path": path("/Users/x/N.app"),
            "dotdot path": path("~/a/../N.app"),
            "empty segment": path("~//N.app"),
            "dot segment": path("~/./N.app"),
            "control path": path("~/N\n.app"),
            "version": lambda p: p["candidate"].update(version="1.2.3"),
            "uppercase commit": lambda p: p["candidate"].update(commit="A" * 40),
            "missing source": lambda p: p["config"].pop("source"),
            "extra config": lambda p: p["config"].update(entitlements="x"),
            "absolute source": lambda p: p["config"].update(source="/abs/N.app"),
            "dotdot source": lambda p: p["config"].update(source="build/../N.app"),
            "bad env name": lambda p: p["config"].update(identity_env="1BAD"),
            "adhoc string": lambda p: p["config"].update(adhoc_fallback="yes"),
            "extra parameter": lambda p: p.update(title="t"),
            "parameter operation": lambda p: p.update(operation="publish"),
        }
        self.install()
        started = len(self.world.calls())
        for name, mutate in mutations.items():
            with self.subTest(mutation=name):
                parameters = with_(mutate)
                observed = self.effect(parameters)
                self.assertEqual((observed["outcome"], observed["reason"]),
                                 ("unknown", "parameters_invalid"))
                self.assertEqual(observed["references"], [])
                self.assertEqual(release_adapter.effect_observation_problems(observed), [])
                predicate = self.visible(parameters)
                self.assertEqual((predicate["outcome"], predicate["reason"]),
                                 ("unknown", "store_unreachable"))
                self.assertEqual(len(self.world.calls()), started)
        with self.subTest(mutation="request operation"):
            request = {"kind": "effect", "operation": "publish", "parameters": self.parameters()}
            self.assertEqual(adapter.inspect(request)["reason"], "parameters_invalid")
            request = {"kind": "predicate", "predicate": "publication_visible",
                       "operation": "publish", "parameters": self.parameters()}
            self.assertEqual(adapter.inspect(request)["reason"], "store_unreachable")
        for name, request in (("not a dict", []), ("no kind", {"operation": "install"})):
            with self.subTest(request=name):
                observed = adapter.inspect(request)
                self.assertEqual((observed["outcome"], observed["reason"]),
                                 ("unknown", "parameters_invalid"))
        self.assertEqual(len(self.world.calls()), started)

    def test_an_undeclared_predicate_is_unsupported(self):
        for predicate in ("running_subject_identity", "agent_running"):
            with self.subTest(predicate=predicate):
                observed = adapter.inspect({"kind": "predicate", "predicate": predicate,
                                            "operation": "install", "parameters": self.parameters()})
                self.assertEqual((observed["outcome"], observed["reason"]),
                                 ("unknown", "predicate_unsupported"))

    def test_the_module_imports_only_stdlib_and_canonical(self):
        tree = ast.parse(introspect.getsource(adapter))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("agent_tools"):
                self.assertEqual(node.module, "agent_tools.canonical")
            if isinstance(node, ast.Import):
                self.assertFalse([a.name for a in node.names if a.name.startswith("agent_tools")])
