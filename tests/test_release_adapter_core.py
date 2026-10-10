"""Outcomes are observed after invocation (#124 AC8). Run: just agent-workflow-tests"""
import unittest

from agent_tools import forge_adapter, release_adapter, release_profile
from . import release_test_support as support
from .forge_world import ForgeWorld
from .test_forge_adapter import ROWS
from .test_transaction_custody import CustodyCase

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

if __name__ == "__main__":
    unittest.main()
