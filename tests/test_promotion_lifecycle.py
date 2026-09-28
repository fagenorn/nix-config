"""Seam 1 for classification and the gates up to `authorized` (#127 D6, D7, D29)."""

import json
import subprocess
import sys
import unittest

from agent_tools import agent_gate_bundle as gate

from .promotion_test_support import (LifecycleFixture, citation, draft, run, write_bundle,
                                     write_json)
from .test_agent_gate_bundle import context, flat, stratum

HEADING = "### Investigate before changing"
DESTINATION = "home/common/agent-skills/standards/the-bar.md"


class ClassificationTest(LifecycleFixture, unittest.TestCase):
    def classification(self, document=None, name="c.json"):
        path = self.capture(document, name=name)
        return self.step(path, "evaluating", "--tracker-ref", "7")["classification"]

    def test_binding_requires_a_tracker_ref_and_records_it(self):
        path = self.capture()
        payload = self.assert_refused(path, "evaluating", "tracker_ref_required")
        self.assertEqual(payload["error"]["state"], "captured")
        after = self.step(path, "evaluating", "--tracker-ref", "7")
        self.assertEqual([after["state"], after["tracker"]["ref"], after["history"][-1]],
                         ["evaluating", 7, {"from": "captured", "to": "evaluating",
                                            "actor": None, "rationale": None}])
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), after)

    def test_rule_one_overrides_on_a_whole_line_match(self):
        (self.root / DESTINATION).parent.mkdir(parents=True)
        (self.root / DESTINATION).write_text(f"# The bar\n{HEADING}   \n", encoding="utf-8")
        self.assertEqual(self.classification(), {
            "rule": 1, "rule_id": "duplicate_of_platform",
            "declared_layer": "standard_layer", "overridden_by_rule_1": True})

    def test_prefix_headings_and_symlinked_components_never_match_rule_one(self):
        real = self.root / "real"
        real.mkdir()
        (real / "the-bar.md").write_text(HEADING + "\n", encoding="utf-8")
        (self.root / "linked").symlink_to(real, target_is_directory=True)
        (self.root / DESTINATION).parent.mkdir(parents=True)
        (self.root / DESTINATION).write_text(HEADING + " code\n", encoding="utf-8")
        linked = dict(draft()["destination"], path="linked/the-bar.md")
        for i, document in enumerate((draft(), draft(destination=linked))):
            with self.subTest(path=document["destination"]["path"]):
                self.assertEqual(self.classification(document, name=f"{i}.json")["rule"], 4)

    def test_each_declared_layer_matches_its_own_rule(self):
        admission = {"gate": "issue-64", "decision": "pending", "irreducible_scenario": "s"}
        names = {"native_adapter": "adapter.claude.hooks",
                 "native_extension": "native.codex.review"}
        layers = ("project_local", "core_module", "standard_layer", "native_adapter",
                  "native_extension", "out_of_scope_product")
        for rule, layer in enumerate(layers, start=2):
            with self.subTest(layer=layer):
                destination = dict(draft()["destination"], layer=layer,
                                   name=names.get(layer, "the-bar"))
                document = draft(destination=destination, native_admission=(
                    admission if layer == "native_extension" else None))
                got = self.classification(document, name=f"{rule}.json")
                self.assertEqual([got["rule"], got["rule_id"], got["overridden_by_rule_1"]],
                                 [rule, layer, False])


class TransitionTest(LifecycleFixture, unittest.TestCase):
    def test_pairs_outside_the_table_are_not_permitted(self):
        path = self.capture()
        for target, flags in (("authorized", ("--authorized-by", "x")), ("promoted", ()),
                              ("captured", ()), ("decision_ready", ("--bundle", "b.json"))):
            with self.subTest(target=target):
                self.assert_refused(path, target, "transition_not_permitted", *flags)

    def test_rationale_edges_and_terminal_states(self):
        path = self.capture()
        self.assert_refused(path, "withdrawn", "rationale_required")
        self.assert_refused(path, "withdrawn", "rationale_required", "--rationale", "  ")
        after = self.step(path, "withdrawn", "--rationale", "duplicate idea")
        self.assertEqual(after["history"][-1]["rationale"], "duplicate idea")
        self.assert_refused(path, "evaluating", "transition_not_permitted", exit_code=3)

    def test_flags_without_meaning_for_the_target_are_usage_errors(self):
        path = self.capture()
        self.assert_refused(path, "evaluating", None, "--bundle", "b.json", exit_code=2)
        self.assert_refused(path, "withdrawn", None, "--tracker-ref", "3", exit_code=2)
        self.assert_refused(path, "evaluating", None, "--tracker-ref", "0", exit_code=2)

    def test_an_invalid_candidate_is_an_invalid_document(self):
        path = self.capture()
        document = json.loads(path.read_text(encoding="utf-8"))
        write_json(path, dict(document, state="done"))
        self.assert_refused(path, "evaluating", "invalid_document", "--tracker-ref", "1",
                            exit_code=2)

    def test_no_subcommand_offers_an_override(self):
        for sub in ("capture", "advance", "evaluate", "validate"):
            with self.subTest(sub=sub):
                proc = subprocess.run(
                    [sys.executable, "-m", "agent_tools.promotion", sub, "--help"],
                    capture_output=True, text=True, env=self.env, timeout=60, check=False)
                text = proc.stdout.lower()
                self.assertEqual(proc.returncode, 0)
                self.assertTrue(text.startswith(f"usage: promotion {sub}"), text[:80])
                for word in ("override", "force", "skip"):
                    self.assertNotIn(word, text)


class EvidenceGateTest(LifecycleFixture, unittest.TestCase):
    def test_decision_ready_needs_distinct_corroboration(self):
        single = {"repositories": [citation()], "platform_governance": None}
        same = {"repositories": [citation(), citation(path="OTHER.md")],
                "platform_governance": None}
        for name, corroboration in (("single", single), ("same", same)):
            with self.subTest(case=name):
                path = self.capture(draft(corroboration=corroboration), name=f"{name}.json")
                self.walk(path, "evaluating")
                write_bundle(self.root, self.BUNDLE, "approved")
                self.assert_refused(path, "decision_ready", "corroboration_insufficient",
                                    "--bundle", self.BUNDLE)
        governed = self.capture(draft(corroboration={
            "repositories": [], "platform_governance": "platform ADR 12"}), name="g.json")
        self.walk(governed, "decision_ready", "unmeasured")

    def test_decision_ready_needs_a_bundle_that_verifies(self):
        path = self.capture()
        self.walk(path, "evaluating")
        edited = write_bundle(self.root, "edited.json", "rejected")
        document = json.loads(edited.read_text(encoding="utf-8"))
        write_json(edited, dict(document, state="approved"))
        (self.root / "text.json").write_text("not json", encoding="utf-8")
        for flags in ((), ("--bundle", "absent.json"), ("--bundle", "../b.json"),
                      ("--bundle", "edited.json"), ("--bundle", "text.json")):
            with self.subTest(flags=flags):
                self.assert_refused(path, "decision_ready", "evidence_unresolvable", *flags)
        write_bundle(self.root, self.BUNDLE, "unmeasured")
        after = self.step(path, "decision_ready", "--bundle", self.BUNDLE)
        bundle = json.loads((self.root / self.BUNDLE).read_text(encoding="utf-8"))
        self.assertEqual(after["evidence"], {
            "bundle_path": self.BUNDLE, "bundle_id": bundle["bundle_id"],
            "state": "unmeasured", "gate_contract": "issue-70", "gate_version": 1})

    def test_authorized_requires_approved_evidence_positively(self):
        for state, code in (("unmeasured", "evidence_unmeasured"),
                            ("rejected", "evidence_rejected")):
            with self.subTest(state=state):
                path = self.capture(name=f"{state}.json")
                self.walk(path, "decision_ready", state)
                self.assert_refused(path, "authorized", code, "--authorized-by", "fagenorn")
        path = self.capture(name="approved.json")
        self.walk(path, "decision_ready", "approved")
        self.assert_refused(path, "authorized", "authorizer_required")
        after = self.step(path, "authorized", "--authorized-by", "fagenorn")
        self.assertEqual(after["history"][-1], {"from": "decision_ready", "to": "authorized",
                                                "actor": "fagenorn", "rationale": None})

    def test_the_recorded_bundle_is_reverified_at_authorized(self):
        path = self.capture()
        self.walk(path, "decision_ready", "approved")
        bundle = self.root / self.BUNDLE
        document = json.loads(bundle.read_text(encoding="utf-8"))
        write_json(bundle, dict(document, generated_at="2000-01-01T00:00:00Z",
                                bundle_id="sha256:" + "0" * 64))
        self.assert_refused(path, "authorized", "evidence_unresolvable",
                            "--authorized-by", "fagenorn")

    def test_a_different_approved_bundle_at_the_path_is_not_the_recorded_bundle(self):
        path = self.capture()
        self.walk(path, "decision_ready", "approved")
        recorded = json.loads(path.read_text(encoding="utf-8"))["evidence"]["bundle_id"]
        manifest = {"identity": {"bound": {}, "pinned": {}},
                    "expansion": {"expanded": False, "checkpoint_ref": None}}
        other = gate.assemble_bundle(manifest, flat(stratum(context(1000, 700))), [], None,
                                     "approved")
        self.assertNotEqual(other["bundle_id"], recorded)
        self.assertEqual(gate.verify_bundle(other), "approved")
        write_json(self.root / self.BUNDLE, other)
        payload = self.assert_refused(path, "authorized", "evidence_unresolvable",
                                      "--authorized-by", "fagenorn")
        self.assertEqual(payload["error"]["violations"][0]["pointer"], "/evidence/bundle_id")

    def test_a_native_extension_needs_admission(self):
        destination = dict(draft()["destination"], layer="native_extension",
                           name="native.claude.review")
        for decision, expected in (("pending", "native_admission_pending"), ("admitted", None)):
            with self.subTest(decision=decision):
                path = self.capture(draft(destination=destination, native_admission={
                    "gate": "issue-64", "decision": decision, "irreducible_scenario": "s"}),
                    name=f"{decision}.json")
                self.walk(path, "decision_ready", "approved")
                if expected:
                    self.assert_refused(path, "authorized", expected,
                                        "--authorized-by", "fagenorn")
                else:
                    self.step(path, "authorized", "--authorized-by", "fagenorn")

    def test_remeasure_clears_evidence_and_binds_the_ref_once(self):
        path = self.capture()
        self.walk(path, "decision_ready", "unmeasured")
        self.assert_refused(path, "evaluating", None, "--tracker-ref", "9", exit_code=2)
        before = json.loads(path.read_text(encoding="utf-8"))
        after = self.step(path, "evaluating")
        self.assertEqual([after["evidence"], after["classification"], after["tracker"]["ref"]],
                         [None, before["classification"], 7])
