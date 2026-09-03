"""Contract tests for the closed registry, purpose selection and the acceptance gate.

Everything that judges the registry as a declaration rather than through an
evaluator: which checks a purpose selects, that every declared repair resolves
and none is unreachable, that registry order is topological, and the end-to-end
acceptance demo the issue's gate names."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

# The suite modules are imported by path, so the tests directory is not
# already on sys.path; the shared support module lives beside them.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from conformance_test_support import (  # noqa: E402
    REPO_ROOT, ReportAssertions, doctor, fixture, load_module, make_root, run,
)


class PurposeSelectionTest(unittest.TestCase):
    """SF-002: structural rules for all six purposes; Task 7 pins the exact ids.

    The invariants are asserted with and without a required capability, because
    --require widens the selection for every purpose (D38) and must not cost it
    duplicate-freedom, REGISTRY order or dependency closure.
    """

    def test_every_purpose_is_duplicate_free_and_dependency_closed(self):
        module = load_module()
        for purpose in module.PURPOSES:
            for required in ((), ("release",)):
                with self.subTest(purpose=purpose, required=required):
                    selected = module.select(purpose, required)
                    ids = [check.id for check in selected]
                    self.assertEqual(len(ids), len(set(ids)))
                    self.assertEqual(
                        ids, [c.id for c in module.REGISTRY if c.id in set(ids)])
                    for check in selected:
                        for dependency in check.depends_on:
                            self.assertIn(dependency, ids, f"{purpose}: {check.id}")

    def test_a_required_capability_selects_its_check_for_every_purpose(self):
        module = load_module()
        for purpose in module.PURPOSES:
            with self.subTest(purpose=purpose):
                ids = [c.id for c in module.select(purpose, ("release",))]
                self.assertIn("host.capability.required", ids)

    def test_an_unknown_purpose_raises(self):
        with self.assertRaises(ValueError):
            load_module().select("teleport")


class RequiredCapabilitySelectionTest(unittest.TestCase):
    """D38: no purpose reports `passed` while a required capability is missing.

    `adoption`, `ci` and `fleet` carry no `host` domain, so a purely
    domain-derived selection drops the one check that judges `--require` and
    the report answers `passed` with the unmet name still in `request`.
    """

    def test_no_purpose_passes_while_a_required_capability_is_unavailable(self):
        for purpose in ("adoption", "ci", "fleet"):
            with self.subTest(purpose=purpose):
                with fixture() as tmp:
                    code, out, err = run("run", "--purpose", purpose,
                                         "--repo-root", str(make_root(tmp)),
                                         "--require", "release")
                    self.assertEqual(code, 0, err)
                    report = json.loads(out)
                    self.assertEqual(report["outcome"], {
                        "status": "failed",
                        "primary_check_id": "host.capability.required"})
                    check = {c["id"]: c for c in report["checks"]}[
                        "host.capability.required"]
                    self.assertEqual(check["reason_code"], "capability_unavailable")


REGISTERED_CHECK_IDS = (
    "compatibility.contract.schema_supported",
    "host.capability.required",
    "host.executor.helper_on_path",
    "host.policy_path.no_follow_readable",
    "host.tracker.credential",
    "repository.contract.present",
    "repository.contract.resolvable",
    "repository.contract.valid",
    "repository.ignore.runtime_sentinel",
    "repository.paths.classified",
    "repository.projection.fresh",
    "repository.release_profile.observation_deadline",
    "repository.release_profile.restore_anchor",
    "repository.release_profile.rolled_back_reachable",
    "repository.residue.nested_ledger",
    "repository.residue.root_scratch",
    "verification.commands.no_shell_indirection",
)

ENTRY_LADDER_IDS = (
    "repository.contract.resolvable", "repository.contract.present",
    "compatibility.contract.schema_supported", "repository.contract.valid",
    "repository.projection.fresh", "host.capability.required")


def ids_with(*prefixes):
    return tuple(i for i in REGISTERED_CHECK_IDS if i.startswith(prefixes))


PURPOSE_SELECTION = {
    "workflow_entry": ENTRY_LADDER_IDS,
    "adoption": ids_with("repository.", "compatibility."),
    "fleet": ids_with("repository.", "compatibility."),
    "ci": ids_with("repository.", "compatibility.", "verification."),
    "local": tuple(dict.fromkeys(ENTRY_LADDER_IDS + ids_with("host."))),
    "doctor": REGISTERED_CHECK_IDS,
}


class RegistryClosureTest(unittest.TestCase):
    def test_the_registry_is_exactly_the_seventeen_declared_checks(self):
        module = load_module()
        self.assertEqual(sorted(c.id for c in module.REGISTRY),
                         sorted(REGISTERED_CHECK_IDS))

    def test_every_declared_repair_resolves_and_none_is_unreachable(self):
        """D31: repair_ids_for reads the registry's own findings declaration."""
        module = load_module()
        declared = set()
        for check in module.REGISTRY:
            for repair_id in module.registry.repair_ids_for(check):
                self.assertIn(repair_id, module.REPAIRS, check.id)
                declared.add(repair_id)
        self.assertEqual(declared, set(module.REPAIRS))

    def test_no_declared_repair_is_destructive(self):
        """D10: the whole v1 repair vocabulary, judged in one place."""
        module = load_module()
        for repair_id, repair in sorted(module.REPAIRS.items()):
            with self.subTest(repair=repair_id):
                self.assertIn(repair["safety_class"], module.SAFETY_CLASSES)
                self.assertNotEqual(repair["safety_class"], "destructive")

    def test_registry_order_is_topological(self):
        module = load_module()
        seen = set()
        for check in module.REGISTRY:
            for dependency in check.depends_on:
                self.assertIn(dependency, seen, f"{check.id} precedes {dependency}")
            seen.add(check.id)

    def test_the_workflow_entry_ladder_names_only_registered_checks(self):
        """`select` intersects the ladder with REGISTRY, so an id no check
        declares is dropped in silence rather than refused."""
        module = load_module()
        self.assertEqual(
            [check_id for check_id in module.registry.WORKFLOW_ENTRY_LADDER
             if check_id not in module.REGISTRY_BY_ID], [])

    def test_every_network_check_declares_the_offline_finding(self):
        """D7: the offline rule emits that pair before the dispatch, so a
        network check not declaring it is a guard_finding refusal at runtime."""
        module = load_module()
        network = [check for check in module.REGISTRY if check.network]
        self.assertTrue(network)
        for check in network:
            with self.subTest(check=check.id):
                self.assertIn(("offline_constraint", "conformance.rerun_online"),
                              check.findings)

    def test_every_resolver_code_is_declared_by_the_check_its_stage_names(self):
        """D33 against D31: `stage_repair_id` reads the stage check's own
        findings, so a code whose stage names a check that never declares it
        is a KeyError at the moment the resolver refuses."""
        module = load_module()
        for code, stage in sorted(module.registry.CODE_STAGES.items()):
            with self.subTest(code=code):
                check = module.REGISTRY_BY_ID[module.registry.STAGE_CHECKS[stage]]
                self.assertIn(code, check.reason_codes)
                self.assertIn(module.CHECKS_MODULE.stage_repair_id(stage, code),
                              module.REPAIRS)

    def test_every_purpose_selects_exactly_the_declared_ids(self):
        """SF-002: one discriminating matrix over the closed registry."""
        module = load_module()
        for purpose, expected in PURPOSE_SELECTION.items():
            with self.subTest(purpose=purpose):
                ids = [c.id for c in module.select(purpose)]
                self.assertEqual(sorted(ids), sorted(expected))
                self.assertEqual(len(ids), len(set(ids)))


class AcceptanceDemoTest(ReportAssertions, unittest.TestCase):
    """D22: the demo the issue names, against this repository's committed root."""

    def test_doctor_on_this_repository_reports_every_registered_check(self):
        report, by_id = doctor(self, REPO_ROOT, "--offline")
        self.assertEqual([c["id"] for c in report["checks"]],
                         sorted(REGISTERED_CHECK_IDS))
        self.assertEqual(report["subject"]["project_id"], "fagenorn/nix-config")
        self.assertNotIn("failed", [c["status"] for c in report["checks"]])
        self.assertEqual(by_id["host.tracker.credential"]["reason_code"],
                         "offline_constraint")
        self.assertEqual(report["outcome"]["status"], "incomplete")
        for repair in report["repairs"]:
            self.assertNotEqual(repair["safety_class"], "destructive")
        self.assert_validates(report)

    def test_workflow_entry_on_a_broken_contract_stops_at_one_root_cause(self):
        with fixture() as tmp:
            root = make_root(tmp)
            (root / ".agents/project.json").write_text("{ broken", encoding="utf-8")
            code, out, err = run("run", "--purpose", "workflow_entry",
                                 "--repo-root", str(root))
            self.assertEqual(code, 2, err)
            report = json.loads(out)
            self.assertEqual(len(report["checks"]), 1)
            self.assertEqual(len(report["repairs"]), 1)
            self.assertEqual(report["checks"][0]["id"], "repository.contract.valid")
            self.assertEqual(report["checks"][0]["reason_code"], "invalid_contract")
            self.assertEqual(report["outcome"]["primary_check_id"],
                             "repository.contract.valid")
            self.assert_validates(report)


if __name__ == "__main__":
    unittest.main()
