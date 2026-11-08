"""Outcomes are observed after invocation (#124 AC8). Run: just agent-workflow-tests"""
import plistlib
import unittest
from pathlib import Path

from agent_tools import (actions_health_adapter, codesigned_artifact_adapter, forge_adapter,
                         launchd_agent_adapter, release_adapter, release_profile)
from agent_tools.transaction_storage import InvocationRefused
from . import release_test_support as support
from .forge_world import ForgeWorld
from .host_world import IDENTITY, HostWorld
from .test_forge_adapter import ROWS
from .test_transaction_custody import CustodyCase

REPO = Path(__file__).resolve().parents[1]

class PostInvocationObservationTest(CustodyCase):
    def setUp(self):
        super().setUp()
        self.world = ForgeWorld(self)
        compiled = release_profile.compile_profile("github-release", support.forge_profile(),
                                                   support.base_contract())
        self.inputs = release_profile.bind_candidate(compiled, support.CANDIDATE)
        self.binding = release_adapter.core_binding(forge_adapter, compiled, "forge")
        self.tid = self.store.create("release-k", self.inputs["subject"],
                                     concurrency_keys=self.inputs["concurrency_keys"],
                                     proof=self.inputs["proof"], recovery=self.inputs["recovery"],
                                     authority_class="test").transaction_id
        self.custody = self.acquire(self.tid)
        for target in ("awaiting_verification", "ready", "publishing"):
            self.store.advance(self.tid, target, reason="r", external_state="known", custody=self.custody)
        self.tag = self.inputs["proof"]["units"][0]

    def test_an_accepted_invoke_that_never_lands_is_observed_absent(self):
        self.world.invoke_ready()
        self.world.not_found("gh", ROWS["tag.ref"]["argv"][1:])
        self.store.inspect_action(self.custody, name="tag", parameters=self.tag["parameters"],
                                  effect=self.binding)
        after = self.store.invoke_action(self.custody, name="tag", parameters=self.tag["parameters"],
                                         effect=self.binding)
        events = [e for e in after.events if e["type"] in ("invocation_returned", "action_inspected")]
        self.assertEqual([(e["type"], e.get("result"), e.get("outcome")) for e in events[-2:]],
                         [("invocation_returned", "accepted", None), ("action_inspected", None, "absent")])
        reads = [c["argv"] for c in self.world.calls() if c["tool"] == "gh"]
        target_reads = [i for i, argv in enumerate(reads) if argv == ROWS["tag.ref"]["argv"][1:]]
        self.assertEqual(len(target_reads), 2)
        between = reads[target_reads[0] + 1:target_reads[1]]
        self.assertEqual(between, [ROWS["invoke.repository"]["argv"][1:], ROWS["tag.compare"]["argv"][1:]])

class PublicationFreeBindingTest(unittest.TestCase):
    """No request reaches the adapter through a publication-free profile (#368 D3, D8)."""

    def test_every_request_is_refused_before_any_child_process(self):
        world = ForgeWorld(self)
        publishing = release_profile.compile_profile("github-release", support.forge_profile(),
                                                     support.base_contract())
        release = release_profile.bind_candidate(publishing, support.CANDIDATE)["proof"]["units"][1]
        self.assertEqual(release["parameters"]["operation"], "release")
        compiled = release_profile.compile_profile(
            "forge-target", support.publication_free_profile(), support.base_contract())
        binding = release_adapter.core_binding(forge_adapter, compiled, "forge")
        requests = {"inspect": {"parameters": release["parameters"]},
                    "invoke": {"parameters": release["parameters"]},
                    "observe": {"predicate": "publication_visible",
                                "parameters": {"parameters": release["parameters"]}}}
        for name, request in requests.items():
            with self.subTest(request=name):
                with self.assertRaisesRegex(ValueError, "is not a node bound to this alias"):
                    getattr(binding, name)(request)
        self.assertEqual(world.calls(), [])


class RegistryTest(unittest.TestCase):
    def test_codesigned_artifact_is_registered(self):
        self.assertIs(release_adapter.REGISTRY["codesigned-artifact"], codesigned_artifact_adapter)
        descriptor = release_adapter.DESCRIPTORS["codesigned-artifact"]
        self.assertEqual(descriptor, codesigned_artifact_adapter.describe())
        self.assertIsNone(release_adapter.watch_operation(descriptor))

    def test_the_registry_holds_four_adapters_and_one_deploy_watch(self):
        self.assertIs(release_adapter.REGISTRY["launchd-agent"], launchd_agent_adapter)
        self.assertEqual(release_adapter.DESCRIPTORS["launchd-agent"], launchd_agent_adapter.describe())
        self.assertEqual({name: release_adapter.watch_operation(descriptor)
                          for name, descriptor in release_adapter.DESCRIPTORS.items()},
                         {"codesigned-artifact": None, "github-actions-health": "deploy",
                          "github-forge": None, "launchd-agent": None})

    def test_no_agent_tools_module_names_argus(self):
        """AC2: the vocabulary is neutral."""
        modules = sorted((REPO / "python/agent_tools").glob("*.py"))
        self.assertGreater(len(modules), 50)
        for path in modules:
            with self.subTest(module=path.name):
                self.assertNotIn("argus", path.read_text("utf-8").lower())

    def test_prior_descriptors_and_forge_profiles_keep_their_base_digests(self):
        """Issue 547 D22: values measured at base 328f08da; github-forge values re-measured for issue 554 D16. github-actions-health re-measured for issue 555 D3."""
        digest = release_adapter.descriptor_digest
        self.assertEqual(digest(release_adapter.DESCRIPTORS["github-forge"]),
                         "sha256:b20ecb89221b3a7c29db4409d1852e469ff7f1891378ee2ed35e22c02c73953b")
        self.assertEqual(digest(release_adapter.DESCRIPTORS["github-actions-health"]),
                         "sha256:dfb551af8d553c39c7f34793c3c81a7752a5d7b31c878d0eb94f1628b274784d")
        self.assertEqual(release_profile.profile_digest(support.forge_profile()),
                         "sha256:39be394179cf572e159af867163c48bef871c71fdad2f1e1cfccd6d270515cf4")
        self.assertEqual(release_profile.profile_digest(support.publication_free_profile()),
                         "sha256:2767a4c3836a3a86eaffd807dd6672a2b2383ade2c39d739c0aa9036f7c2b7b3")


class HostLocalCoreTest(CustodyCase):
    """Issue 547 D16: the real core settles the Argus-shaped profile over the host world."""

    def setUp(self):
        super().setUp()
        self.world = HostWorld(self)
        self.world.environ(ARGUS_CODESIGN_IDENTITY=None)
        self.world.identities(IDENTITY)
        self.world.bundle("daemon/notifyd/Argus.app", identifier="dev.argus.pings")
        self.world.program("devenv")
        self.compiled = release_profile.compile_profile("argus", support.argus_shaped_profile(),
                                                        support.base_contract())
        self.bindings = {alias: release_adapter.core_binding(
            release_adapter.REGISTRY[identity["adapter"]], self.compiled, alias)
            for alias, identity in self.compiled["adapters"].items()}
        self.alias = {node["id"]: node["adapter"]
                      for node in (*self.compiled["publication"], *self.compiled["activation"])}

    def advance(self, tid, custody, *states):
        for state in states:
            self.store.advance(tid, state, reason="r", custody=custody)

    def begin(self, key, version):
        candidate = {"version": version, "commit": self.world.head(), "title": version, "notes": ""}
        inputs = release_profile.bind_candidate(self.compiled, candidate)
        tid = self.store.create(key, inputs["subject"], concurrency_keys=inputs["concurrency_keys"],
                                proof=inputs["proof"], recovery=inputs["recovery"],
                                authority_class="test").transaction_id
        custody = self.acquire(tid)
        self.advance(tid, custody, "awaiting_verification", "ready", "publishing")
        return tid, custody, {unit["name"]: unit["parameters"] for unit in inputs["proof"]["units"]}

    def act(self, custody, name, parameters, invoke=True):
        effect = self.bindings[self.alias[name]]
        after = self.store.inspect_action(custody, name=name, parameters=parameters, effect=effect)
        if invoke:
            after = self.store.invoke_action(custody, name=name, parameters=parameters, effect=effect)
        return [e["outcome"] for e in after.events if e["type"] == "action_inspected"][-1]

    def release(self, key, version):
        tid, custody, units = self.begin(key, version)
        self.assertEqual(self.act(custody, "notifier", units["notifier"]), "satisfied")
        self.advance(tid, custody, "published", "activating")
        self.assertEqual(self.act(custody, "daemon", units["daemon"]), "satisfied")
        self.advance(tid, custody, "proving")
        plan = self.store.load(tid).proof_plan
        collector = {entry["obligation_id"]: entry["collector"] for entry in plan["obligations"]}
        for identity in collector:
            self.store.collect_obligation(custody, obligation_id=identity,
                                          observer=self.bindings[collector[identity]])
        self.store.start_cohort(custody)
        for identity in plan["cohort"]["members"]:
            self.store.collect_obligation(custody, obligation_id=identity,
                                          observer=self.bindings[collector[identity]])
        return self.store.settle_proof(custody)

    def stamp_and_plist(self):
        bundle = self.world.home / "Library/Application Support/Argus/Argus.app/Contents/Info.plist"
        with open(bundle, "rb") as handle:
            info = plistlib.load(handle)
        with open(self.world.plist_path("dev.argus.daemon"), "rb") as handle:
            agent = plistlib.load(handle)
        return (info["AgentReleaseVersion"], info["AgentReleaseCommit"]), agent

    def verbs(self):
        return [call["argv"][0] for call in self.world.calls("launchctl")]

    def test_a_bound_candidate_settles_succeeded(self):
        settled = self.release("release-1", "v1.0.0")
        self.assertEqual(settled.state, "succeeded")
        stamp, agent = self.stamp_and_plist()
        self.assertEqual(stamp, ("v1.0.0", self.world.head()))
        self.assertEqual(agent["EnvironmentVariables"], {"AGENT_RELEASE_VERSION": "v1.0.0",
                                                         "AGENT_RELEASE_COMMIT": self.world.head()})
        self.assertEqual(agent["ProgramArguments"],
                         [str(self.world.bin / "devenv"), "shell", "--", "daemon", "run"])
        self.assertEqual(agent["WorkingDirectory"], str(self.world.checkout))
        self.assertNotIn("bootout", self.verbs())

    def test_a_second_release_replaces_both_units(self):
        self.assertEqual(self.release("release-1", "v1.0.0").state, "succeeded")
        first = len(self.world.calls("launchctl"))
        head = self.world.commit()
        self.assertEqual(self.release("release-2", "v1.0.1").state, "succeeded")
        stamp, agent = self.stamp_and_plist()
        self.assertEqual(stamp, ("v1.0.1", head))
        self.assertEqual(agent["EnvironmentVariables"], {"AGENT_RELEASE_VERSION": "v1.0.1",
                                                         "AGENT_RELEASE_COMMIT": head})
        later = [call["argv"][0] for call in self.world.calls("launchctl")[first:]]
        self.assertEqual([verb for verb in later if verb != "print"], ["bootout", "bootstrap"])
        self.assertEqual(sorted(path.name for path in
                                (self.world.home / "Library/Application Support/Argus").iterdir()),
                         ["Argus.app"])

    def test_a_job_from_a_foreign_plist_parks_the_daemon_without_mutation(self):
        self.world.load_job("dev.argus.daemon",
                            path=str(self.world.home / "Library/LaunchAgents/other.plist"))
        seed = len(self.world.calls("launchctl"))
        tid, custody, units = self.begin("release-1", "v1.0.0")
        self.assertEqual(self.act(custody, "notifier", units["notifier"]), "satisfied")
        self.advance(tid, custody, "published", "activating")
        self.assertEqual(self.act(custody, "daemon", units["daemon"], invoke=False), "diverged")
        with self.assertRaises(InvocationRefused) as refused:
            self.store.invoke_action(custody, name="daemon", parameters=units["daemon"],
                                     effect=self.bindings["launchd"])
        self.assertEqual(refused.exception.reason, "not_absent")
        self.assertEqual({call["argv"][0] for call in self.world.calls("launchctl")[seed:]}, {"print"})
        self.assertFalse(self.world.plist_path("dev.argus.daemon").exists())


class WatchOperationTest(unittest.TestCase):
    """Only a publication_triggered operation is a deploy watch (issue 547 D10)."""

    def descriptor(self, *modes, inspect="supported"):
        descriptor = actions_health_adapter.describe()
        entry = descriptor["operations"]["deploy"]
        descriptor["operations"] = {f"op{index}": {**entry, "mode": mode, "inspect": inspect}
                                    for index, mode in enumerate(modes)}
        return descriptor

    def test_only_a_single_inspectable_publication_triggered_operation_is_watched(self):
        cases = ((("publication_triggered",), "supported", "op0"),
                 (("local_apply",), "supported", None),
                 (("provider_deploy",), "supported", None),
                 (("convergent_pull",), "supported", None),
                 (("materialize", "publication_triggered"), "supported", "op1"),
                 (("local_apply", "publication_triggered"), "supported", "op1"),
                 (("publication_triggered", "publication_triggered"), "supported", None),
                 (("publication_triggered",), "unsupported", None))
        for modes, inspect, expected in cases:
            with self.subTest(modes=modes, inspect=inspect):
                self.assertEqual(release_adapter.watch_operation(self.descriptor(*modes, inspect=inspect)),
                                 expected)


if __name__ == "__main__":
    unittest.main()
