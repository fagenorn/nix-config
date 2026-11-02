"""Outcomes are observed after invocation (#124 AC8). Run: just agent-workflow-tests"""
import unittest
from pathlib import Path

from agent_tools import (actions_health_adapter, codesigned_artifact_adapter, forge_adapter,
                         launchd_agent_adapter, release_adapter, release_profile)
from . import release_test_support as support
from .forge_world import ForgeWorld
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
        """Issue 547 D22: values measured at base 328f08da."""
        digest = release_adapter.descriptor_digest
        self.assertEqual(digest(release_adapter.DESCRIPTORS["github-forge"]),
                         "sha256:efe2899b3f41bfde870ab28366beb81a8359e5eb050a2be1534b71810473004a")
        self.assertEqual(digest(release_adapter.DESCRIPTORS["github-actions-health"]),
                         "sha256:2453a459491301250c59b62fa08b4846b13ada3970a4b0583710426b251dc55e")
        self.assertEqual(release_profile.profile_digest(support.forge_profile()),
                         "sha256:4be9656c19dce516d183fb3c581fbf3be8026ea490497ff15d8292fc79f06573")
        self.assertEqual(release_profile.profile_digest(support.publication_free_profile()),
                         "sha256:f98d60dd0f7484bfee7fd017d4edd4b6c23007db767b0a2f2a504a9c4b6cddab")


if __name__ == "__main__":
    unittest.main()


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
