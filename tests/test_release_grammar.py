"""Release profile grammar and adapter descriptors (#124). Run: just agent-workflow-tests"""
import copy
import unittest

from agent_tools import forge_adapter, release_adapter, release_profile
from . import release_test_support as support

def violations(release, contract=None):
    return release_profile.grammar_violations(
        release, contract if contract is not None else support.base_contract(),
        support.descriptors())

class DescriptorTest(unittest.TestCase):
    def test_forge_and_fixture_descriptors_are_valid(self):
        self.assertEqual(release_adapter.descriptor_problems(forge_adapter.describe()), [])
        self.assertEqual(release_adapter.descriptor_problems(support.FIXTURE_STORE), [])

    def test_registry_is_closed(self):
        self.assertEqual(sorted(release_adapter.REGISTRY), ["github-forge"])
        self.assertEqual(sorted(release_adapter.DESCRIPTORS), ["github-forge"])

    def test_forge_descriptor_pins_pr_merge_unsupported(self):
        op = forge_adapter.describe()["operations"]["pr_merge"]
        self.assertEqual((op["mode"], op["support"], op["inspect"], op["reason"], op["mutability"]),
                         ("materialize", "unsupported", "supported", "target_cas_unproven", "pointer_cas"))
        self.assertEqual(forge_adapter.describe()["host_capacity"], "not_required")

    def test_descriptor_problems_catch_each_rule(self):
        cases = {
            "extra member": lambda d: d.update(extra=1),
            "bad version": lambda d: d.update(adapter_contract_version="1.0"),
            "mode null without recovery": lambda d: d["operations"]["tag"].update(mode=None),
            "reserved predicate missing": lambda d: d["predicates"].pop("running_subject_identity"),
            "publication without visibility": lambda d: d["predicates"]["publication_visible"].update(
                support="unsupported", reason="r"),
            "latency over core cap": lambda d: d["collector"].update(max_collection_latency_ms=300_001),
        }
        for name, mutate in cases.items():
            with self.subTest(name):
                descriptor = forge_adapter.describe()
                mutate(descriptor)
                self.assertNotEqual(release_adapter.descriptor_problems(descriptor), [])

    def test_build_descriptors_refuses_a_name_mismatch(self):
        with self.assertRaises(ValueError):
            release_adapter.build_descriptors({"other-name": forge_adapter})

class GrammarAcceptsTest(unittest.TestCase):
    def test_valid_shapes_have_no_violations(self):
        self.assertEqual(violations("unsupported"), [])
        self.assertEqual(violations(support.release_of("github-release", support.forge_profile())), [])
        self.assertEqual(violations(support.release_of("restorable", support.restorable_profile())), [])
        self.assertEqual(violations(support.release_of("restorable", support.destroyed_anchor_profile())), [])

    def test_vocabularies_left_to_the_core_are_not_judged(self):
        profile = support.forge_profile()
        del profile["publication"]["actions"][0]["observation_deadline_ms"]
        profile["proof"]["obligations"].append({
            "id": "derived:published_artifact_identity:tag", "semantic": "published_artifact_identity",
            "form": "event", "predicate": "publication_visible", "collector": "forge",
            "required": True, "deps": [], "parameters": {}})
        profile["recovery"]["units"]["tag"]["posture"] = "not-a-posture"
        self.assertEqual(violations(support.release_of("github-release", profile)), [])

class GrammarRefusesTest(unittest.TestCase):
    def refused(self, mutate, repair_id, pointer_prefix="/release"):
        profile = support.forge_profile()
        contract = support.base_contract()
        mutate(profile, contract)
        found = violations(support.release_of("github-release", profile), contract)
        self.assertTrue(found, "expected a violation")
        self.assertIn(repair_id, [v["repair_id"] for v in found])
        for v in found:
            self.assertIn(v["repair_id"], release_profile.GRAMMAR_REPAIR_IDS)
            self.assertEqual(sorted(v), ["message", "pointer", "repair_id"])
        self.assertTrue(any(v["pointer"].startswith(pointer_prefix) for v in found))

    def test_top_level_shapes(self):
        for value in (None, "", "Unsupported", {}, {"profiles": {}}, {"profiles": {"Bad_Id": {}}},
                      {"profiles": {}, "extra": 1}, []):
            with self.subTest(value=value):
                self.assertIn("contract.release.invalid",
                              [v["repair_id"] for v in violations(value)])

    def test_each_rule(self):
        def act(**kw):
            return lambda p, c: p["publication"]["actions"][0].update(**kw)
        cases = [
            (lambda p, c: p.pop("limits"), "invalid"),
            (lambda p, c: p.update(limits={"max_spend": 1}), "invalid"),
            (lambda p, c: p["requirements"]["adapters"]["forge"].update(min_inclusive="2.0.0"), "invalid"),
            (lambda p, c: p["requirements"]["adapters"].update(
                forge={"min_inclusive": "2.0.0", "max_exclusive": "3.0.0"}), "adapter_unsupported"),
            (lambda p, c: p["bindings"]["adapters"]["forge"].update(adapter="railway"), "adapter_unsupported"),
            (act(target="nowhere"), "reference_unknown"),
            (act(deps=["github-release"]), "reference_unknown"),
            (act(effect="reversible_bounded_spend"), "effect_unsupported"),
            (act(operation="pr_merge", mode="materialize"), "adapter_unsupported"),
            (act(mode="promote"), "adapter_unsupported"),
            (act(config_schema_version=2), "config_invalid"),
            (act(config={"x": 1}), "config_invalid"),
            (act(observation_deadline_ms=True), "invalid"),
            (lambda p, c: p["recovery"]["units"].pop("tag"), "reference_unknown"),
            (lambda p, c: p["proof"]["obligations"].append({
                "id": "o", "semantic": "liveness", "form": "event", "predicate": "p",
                "collector": "nobody", "required": True, "deps": [], "parameters": {}}), "reference_unknown"),
            (lambda p, c: p["bindings"]["targets"]["repository"].update(repository="x/y"), "same_repository"),
            (lambda p, c: p["bindings"]["targets"]["repository"].update(branch="dev"), "same_repository"),
            (lambda p, c: c["bindings"]["tracker"].update(kind="gitlab"), "same_repository"),
        ]
        for index, (mutate, repair) in enumerate(cases):
            with self.subTest(index=index, repair=repair):
                self.refused(mutate, "contract.release." + repair)

    def test_profiles_force_deploy_unsupported(self):
        self.refused(lambda p, c: c["capabilities"]["deploy"].update(support="supported"),
                     "contract.release.deploy_conflict", "/capabilities/deploy/support")

    def test_malformed_bindings_report_only_invalid(self):
        def drop_bindings(p, c):
            del p["bindings"]
        cases = {
            "missing bindings": drop_bindings,
            "adapters list": lambda p, c: p["bindings"].update(adapters=[]),
            "targets string": lambda p, c: p["bindings"].update(targets="x"),
            "principals null": lambda p, c: p["bindings"].update(principals=None),
            "credentials list": lambda p, c: p["bindings"].update(credentials=[]),
        }
        for name, mutate in cases.items():
            with self.subTest(name):
                profile, contract = support.forge_profile(), support.base_contract()
                mutate(profile, contract)
                found = violations(support.release_of("github-release", profile), contract)
                self.assertTrue(found)
                self.assertEqual({v["repair_id"] for v in found}, {"contract.release.invalid"})

    def test_malformed_contract_never_raises(self):
        for contract in ({}, {"bindings": []}, {"bindings": {"tracker": None}}, []):
            with self.subTest(contract=contract):
                violations(support.release_of("github-release", support.forge_profile()), contract)

if __name__ == "__main__":
    unittest.main()
