"""Release profile compiler (#124 AC1). Run: just agent-workflow-tests"""
import tempfile
import unittest
from pathlib import Path

from agent_tools import release_profile
from agent_tools.transaction_core import TransactionStore
from agent_tools.transaction_storage import ProofPlanRejected
from . import release_test_support as support

D = support.descriptors

def compile_(profile_id, profile):
    return release_profile.compile_profile(profile_id, profile, support.base_contract(), D())

def tree(root):
    """Every path under the store root: create must add none (D20)."""
    return sorted(str(p.relative_to(root)) for p in root.rglob("*"))

def reasons(error):
    return [f["reason"] for f in error.findings]

class AcceptanceOneTest(unittest.TestCase):
    def test_accepts_the_forge_and_the_restorable_profile(self):
        forge = compile_("github-release", support.forge_profile())
        self.assertEqual(forge["schema"], "release-profile/v1")
        self.assertEqual([n["id"] for n in forge["publication"]], ["tag", "github-release"])
        self.assertEqual(dict(forge["deadlines"]), {"tag": 600000, "github-release": 600000})
        restorable = compile_("restorable", support.restorable_profile())
        self.assertEqual([n["id"] for n in restorable["publication"]],
                         ["publish-artifact", "promote-pointer"])

    def test_rejects_the_three_issue_cases(self):
        cases = (("github-release", support.derived_class_profile(), "proof.derived_class_named"),
                 ("github-release", support.missing_deadline_profile(), "observation_deadline_optional"),
                 ("restorable", support.unreachable_rollback_profile(), "rolled_back_unreachable"))
        for profile_id, profile, reason in cases:
            with self.subTest(reason=reason):
                with self.assertRaises(release_profile.ProfileInadmissible) as caught:
                    compile_(profile_id, profile)
                self.assertIn(reason, reasons(caught.exception))
                for finding in caught.exception.findings:
                    self.assertEqual(sorted(finding), ["detail", "pointer", "reason", "rule"])

    def test_compile_refuses_before_any_store_exists(self):
        """D20: compile_profile refuses the three inadmissible profiles, so no bind or create follows."""
        cases = (("github-release", support.derived_class_profile()),
                 ("github-release", support.missing_deadline_profile()),
                 ("restorable", support.unreachable_rollback_profile()))
        for profile_id, profile in cases:
            with self.subTest(profile_id=profile_id), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                before = tree(root)
                with self.assertRaises(release_profile.ProfileInadmissible):
                    inputs = release_profile.bind_candidate(compile_(profile_id, profile), support.CANDIDATE)
                    TransactionStore(root).create(
                        "k", inputs["subject"], concurrency_keys=inputs["concurrency_keys"],
                        proof=inputs["proof"], recovery=inputs["recovery"], authority_class="test")
                self.assertEqual(tree(root), before)

    def test_the_core_refuses_a_derived_class_before_any_lock(self):
        """AC1: declarations the core itself refuses leave the store root as it was; a control
        create from an accepted profile's declarations does write, so the check can fail."""
        def create(root, profile_id, profile):
            proof, recovery = release_profile.lower(profile_id, profile, D())
            return TransactionStore(root).create(
                "k", {"profile_id": profile_id}, concurrency_keys=["release/test"],
                proof=proof, recovery=recovery, authority_class="test")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            before = tree(root)
            with self.assertRaises(ProofPlanRejected) as caught:
                create(root, "github-release", support.derived_class_profile())
            self.assertEqual(caught.exception.reason, "derived_class_named")
            self.assertEqual(tree(root), before)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            before = tree(root)
            create(root, "github-release", support.forge_profile())
            self.assertNotEqual(tree(root), before)

class RulesTest(unittest.TestCase):
    def test_every_finding_is_reported(self):
        profile = support.missing_deadline_profile()
        del profile["publication"]["actions"][1]["observation_deadline_ms"]
        with self.assertRaises(release_profile.ProfileInadmissible) as caught:
            compile_("github-release", profile)
        self.assertEqual([f["pointer"] for f in caught.exception.findings],
                         ["/release/profiles/github-release/publication/actions/0",
                          "/release/profiles/github-release/publication/actions/1"])

    def test_out_of_bounds_and_destroyed_anchor(self):
        profile = support.forge_profile()
        profile["publication"]["actions"][0]["observation_deadline_ms"] = 7_200_001
        self.assertEqual([f["reason"] for f in release_profile.rule_findings(
            "observation_deadline", "github-release", profile, support.base_contract(), D())],
            ["observation_deadline_out_of_bounds"])
        found = release_profile.rule_findings("restore_anchor", "restorable",
                                              support.destroyed_anchor_profile(),
                                              support.base_contract(), D())
        self.assertEqual([(f["reason"], f["pointer"]) for f in found],
                         [("restore_anchor_destroyed",
                           "/release/profiles/restorable/recovery/units/promote-pointer/anchor/target")])

class FrozenAndBoundTest(unittest.TestCase):
    def test_compiled_profile_is_frozen_deterministic_and_detached(self):
        profile = support.forge_profile()
        first = compile_("github-release", profile)
        self.assertEqual(first["digest"], compile_("github-release", support.forge_profile())["digest"])
        profile["publication"]["actions"][0]["id"] = "changed"
        self.assertEqual(first["publication"][0]["id"], "tag")
        with self.assertRaises(TypeError):
            first["target"]["environment"] = "x"
        self.assertEqual(set(first), {"schema", "profile_id", "profile_version", "digest", "target",
                                      "adapters", "publication", "activation", "deadlines",
                                      "proof_declaration", "recovery_declaration", "limits",
                                      "candidate_members"})

    def test_bind_candidate_is_exactly_the_create_input(self):
        compiled = compile_("github-release", support.forge_profile())
        inputs = release_profile.bind_candidate(compiled, support.CANDIDATE)
        self.assertEqual(sorted(inputs), ["concurrency_keys", "proof", "recovery", "subject"])
        self.assertEqual(inputs["subject"], {
            "profile_id": "github-release", "profile_version": 1, "profile_digest": compiled["digest"],
            "candidate": {"version": "v1.2.3", "commit": "1" * 40}})
        tag, release = inputs["proof"]["units"]
        self.assertNotIn("title", tag["parameters"])
        self.assertEqual((release["parameters"]["title"], release["parameters"]["notes"]),
                         ("v1.2.3 \u2014 release", "notes body"))
        self.assertEqual(release["parameters"]["target"], {
            "handle": "repository", "kind": "github_repository",
            "branch": "main", "repository": "fagenorn/nix-config"})
        with tempfile.TemporaryDirectory() as tmp:
            TransactionStore(Path(tmp).resolve()).create(
                "k", inputs["subject"], concurrency_keys=inputs["concurrency_keys"],
                proof=inputs["proof"], recovery=inputs["recovery"], authority_class="test")

    def test_bind_candidate_refuses_bad_input(self):
        compiled = compile_("github-release", support.forge_profile())
        with self.assertRaises(TypeError):
            release_profile.bind_candidate(release_profile.thaw(compiled), support.CANDIDATE)
        for bad in ({"version": "1.2.3"}, {"commit": "abc"}, {"title": 'a "quoted" title'},
                    {"extra": 1}):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    release_profile.bind_candidate(compiled, {**support.CANDIDATE, **bad})

if __name__ == "__main__":
    unittest.main()
