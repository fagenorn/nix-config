"""Contract tests for `adopt-project verify` and the fleet registry.

`verify` is the read-only conformance verb and, with `--register`, the one
writer of `~/.agents/state/fleet/registry.json`. The cases below are therefore
two suites in one: the conformance report and its evidence-record discovery
(D34), and the locked registration transaction whose far side is
`resolve-project platform-status --fleet` (D18, D19).

They live beside `test_adopt_project.py` rather than inside it because that
file is the review package's binding member; the fixtures, the
temporary-`HOME` isolation and the git helper are imported from it and from
`test_adopt_apply.py`, and no `TestCase` crosses over, so no file collects
another's tests (the pattern `test_adopt_project_boundaries.py` established).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# The sibling suites are imported as modules, so their directory has to be
# importable however this file was invoked — `python3 <path>` supplies it,
# `python3 -m unittest <path>` does not.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_adopt_project import (
    EVIDENCE_RECORD_MEMBERS,
    RESOLVER,
    commit,
    adopted_repo,
    fixture_contract,
    git,
    init_repo,
    make_home,
    reconcile_repo,
    run,
    scaffold,
    tree_snapshot,
    write,
    write_adoption_records,
)
from test_adopt_apply import apply_repo

VERIFY_MEMBERS = ["adoption_commit", "blockers", "checks", "evidence_record",
                  "migration_map", "project_id", "registered", "result",
                  "root", "schema_version"]
CHECK_IDS = ["contract-resolves", "projections-in-sync",
             "no-unclassified-agent-path", "adoption-evidence-record",
             "adoption-commit-derived", "path-migration-map"]


def verifiable_repo(home: Path, *, project_id: str = "fixture/target",
                    tracker_cli: str = "gh") -> Path:
    """A conformant checkout carrying the two adoption records, on `main`.

    The identity and the tracker binary are the two knobs the cases below
    need: distinct ids for the registry, and a tracker CLI that cannot resolve
    for the `adopted_with_blockers` verdict.
    """
    root = init_repo()
    contract = fixture_contract()
    contract["project"] = {"id": project_id, "name": project_id.split("/")[-1]}
    contract["bindings"]["tracker"]["cli"] = tracker_cli
    scaffold(root, contract, home)
    write(root, ".agents/runtime/.gitignore", "*\n")
    git(root, "add", "-f", ".agents/runtime/.gitignore")
    commit(root)
    write_adoption_records(root)
    commit(root, "adopt")
    return root


class VerifyTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.home = make_home()

    # -- running ----------------------------------------------------------

    def verify(self, root: Path, *extra: str) -> tuple[int, object, str]:
        code, out, err = run("verify", "--repo-root", str(root), *extra,
                             home=self.home)
        try:
            payload: object = json.loads(out)
        except json.JSONDecodeError:
            payload = None
        return code, payload, err

    def report(self, root: Path, *extra: str) -> dict:
        code, payload, err = self.verify(root, *extra)
        self.assertEqual(code, 0, err or payload)
        return payload

    def refuse(self, root: Path, code: str, *extra: str) -> dict:
        exit_code, payload, err = self.verify(root, *extra)
        self.assertEqual(exit_code, 2, err or payload)
        self.assertEqual(payload["error"]["code"], code, payload)
        self.assertTrue(payload["error"]["violations"])
        return payload

    def check(self, report: dict, check_id: str) -> dict:
        found = [entry for entry in report["checks"]
                 if entry["id"] == check_id]
        self.assertEqual(len(found), 1, report["checks"])
        return found[0]

    # -- the registry -----------------------------------------------------

    def registry_path(self) -> Path:
        return self.home / ".agents" / "state" / "fleet" / "registry.json"

    def registry(self) -> object:
        return json.loads(self.registry_path().read_text("utf-8"))

    def fleet(self) -> list[dict]:
        proc = subprocess.run(
            [sys.executable, str(RESOLVER), "platform-status", "--fleet"],
            capture_output=True, text=True, timeout=120,
            env={**os.environ, "HOME": str(self.home)})
        self.assertEqual(proc.returncode, 0, proc.stdout)
        return json.loads(proc.stdout)["fleet"]


# --------------------------------------------------------------------------
# The read-only report
# --------------------------------------------------------------------------


class VerifyReadOnlyTest(VerifyTestCase):
    def test_a_conformant_checkout_is_adopted_and_writes_nothing(self):
        root = adopted_repo(self.home)
        before_status = git(root, "status", "--porcelain")
        before_tree = tree_snapshot(root)
        report = self.report(root)
        self.assertEqual(report["result"], "adopted", report)
        self.assertEqual(sorted(report), VERIFY_MEMBERS)
        self.assertEqual(report["schema_version"], 1)
        self.assertEqual(report["project_id"], "fixture/target")
        self.assertEqual(report["root"], str(root))
        self.assertEqual(report["blockers"], [])
        self.assertIs(report["registered"], False)
        self.assertEqual([entry["id"] for entry in report["checks"]],
                         CHECK_IDS)
        self.assertEqual(
            sorted({entry["status"] for entry in report["checks"]}),
            ["passed"])
        # The three independent witnesses of D21, plus the registry: read-only
        # `verify` stores no snapshot and creates no fleet file.
        self.assertEqual(git(root, "status", "--porcelain"), before_status)
        self.assertEqual(tree_snapshot(root), before_tree)
        self.assertFalse(self.registry_path().exists())

    def test_the_adoption_commit_is_the_commit_that_added_the_record(self):
        root = adopted_repo(self.home)
        introduced = git(root, "rev-parse", "HEAD").strip()
        write(root, "later.md", "# later\n")
        commit(root, "unrelated")
        report = self.report(root)
        self.assertEqual(report["adoption_commit"], introduced)
        self.assertNotEqual(report["adoption_commit"],
                            git(root, "rev-parse", "HEAD").strip())
        self.assertEqual(report["evidence_record"],
                         f".agents/artifacts/evidence/{'a1' * 32}.json")
        self.assertEqual(
            report["migration_map"],
            f".agents/knowledge/archive/path-migrations/{'a1' * 32}.json")

    def test_a_drifted_projection_is_not_conformant_and_names_it(self):
        root = adopted_repo(self.home)
        write(root, "AGENTS.md", "hand-edited\n")
        report = self.report(root)
        self.assertEqual(report["result"], "not_conformant", report)
        drift = self.check(report, "projections-in-sync")
        self.assertEqual(drift["status"], "failed")
        self.assertIn("codex.entry", drift["detail"])
        self.assertIs(report["registered"], False)

    def test_a_blocked_capability_is_adopted_with_blockers(self):
        root = verifiable_repo(self.home, tracker_cli="no-such-tracker-cli")
        report = self.report(root)
        self.assertEqual(report["result"], "adopted_with_blockers", report)
        self.assertEqual(report["blockers"], [{
            "capability": "tracker",
            "repair_id": "capability.tracker.tracker_cli_missing",
        }])
        self.assertEqual(
            sorted({entry["status"] for entry in report["checks"]}),
            ["passed"])

    def test_a_repository_without_a_contract_is_not_conformant(self):
        root = reconcile_repo(self.home)
        report = self.report(root)
        self.assertEqual(report["result"], "not_conformant", report)
        contract = self.check(report, "contract-resolves")
        self.assertEqual(contract["status"], "failed")
        self.assertIn("not_onboarded", contract["detail"])
        self.assertIsNone(report["project_id"])

    def test_a_plain_directory_is_not_a_repository(self):
        self.refuse(Path(tempfile.mkdtemp()), "not_a_repository")


# --------------------------------------------------------------------------
# Evidence-record discovery (D34)
# --------------------------------------------------------------------------


class EvidenceDiscoveryTest(VerifyTestCase):
    def not_conformant(self, root: Path) -> dict:
        report = self.report(root)
        self.assertEqual(report["result"], "not_conformant", report)
        return report

    def test_no_record_at_all_names_the_absence(self):
        report = self.not_conformant(adopted_repo(self.home, records=False))
        entry = self.check(report, "adoption-evidence-record")
        self.assertEqual(entry["status"], "failed")
        self.assertIn("no adoption evidence record", entry["detail"])
        self.assertIsNone(report["adoption_commit"])
        self.assertEqual(
            self.check(report, "adoption-commit-derived")["status"], "not_run")

    def test_a_record_that_is_not_valid_json_is_not_conformant(self):
        root = adopted_repo(self.home, records=False)
        write(root, ".agents/artifacts/evidence/broken.json", "{not json")
        commit(root, "broken record")
        report = self.not_conformant(root)
        self.assertIn("does not parse",
                      self.check(report, "adoption-evidence-record")["detail"])

    def test_a_record_missing_a_required_member_is_not_conformant(self):
        root = adopted_repo(self.home, records=False)
        record = {name: None for name in EVIDENCE_RECORD_MEMBERS}
        del record["path_migration_map"]
        write(root, ".agents/artifacts/evidence/partial.json",
              json.dumps(record) + "\n")
        commit(root, "partial record")
        report = self.not_conformant(root)
        self.assertIn("does not parse",
                      self.check(report, "adoption-evidence-record")["detail"])

    def test_two_committed_records_name_the_ambiguity(self):
        root = adopted_repo(self.home)
        write_adoption_records(root, digest="b2" * 32)
        commit(root, "a second adoption record")
        report = self.not_conformant(root)
        entry = self.check(report, "adoption-evidence-record")
        self.assertIn("more than one", entry["detail"])
        self.assertIsNone(report["adoption_commit"])

    def test_an_untracked_record_is_not_the_adoption_record(self):
        root = adopted_repo(self.home, records=False)
        write_adoption_records(root)
        report = self.not_conformant(root)
        self.assertIn("no adoption evidence record",
                      self.check(report, "adoption-evidence-record")["detail"])

    def test_a_record_naming_an_absent_migration_map_is_not_conformant(self):
        root = adopted_repo(self.home, records=False)
        write_adoption_records(root)
        (root / ".agents" / "knowledge" / "archive" / "path-migrations"
         / f"{'a1' * 32}.json").unlink()
        commit(root, "record without its map")
        report = self.not_conformant(root)
        entry = self.check(report, "path-migration-map")
        self.assertEqual(entry["status"], "failed")
        self.assertIn("path migration map", entry["detail"])


# --------------------------------------------------------------------------
# Registration (D19, D18)
# --------------------------------------------------------------------------


class RegistrationTest(VerifyTestCase):
    def test_an_unintegrated_adoption_commit_refuses_not_integrated(self):
        root = apply_repo(self.home)
        code, out, err = run("plan", "--repo-root", str(root), home=self.home)
        self.assertEqual(code, 0, err or out)
        plan_id = json.loads(out)["plan"]["plan_id"]
        code, out, err = run("apply", "--plan-id", plan_id, home=self.home)
        self.assertEqual(code, 0, err or out)
        branch = json.loads(out)["branch"]
        # The adoption commit exists only on its own branch, which is exactly
        # the pre-merge state D19 forbids registering from.
        git(root, "checkout", "--quiet", branch)
        report = self.report(root)
        self.assertEqual(report["result"], "adopted", report)
        self.refuse(root, "not_integrated", "--register")
        self.assertFalse(self.registry_path().exists())

    def test_registration_after_the_merge_writes_exactly_two_members(self):
        root = apply_repo(self.home)
        code, out, err = run("plan", "--repo-root", str(root), home=self.home)
        self.assertEqual(code, 0, err or out)
        plan_id = json.loads(out)["plan"]["plan_id"]
        code, out, err = run("apply", "--plan-id", plan_id, home=self.home)
        self.assertEqual(code, 0, err or out)
        git(root, "merge", "--ff-only", "--quiet", json.loads(out)["branch"])
        report = self.report(root, "--register")
        self.assertEqual(report["result"], "adopted", report)
        self.assertIs(report["registered"], True)
        self.assertEqual(self.registry(), {
            "schema_version": 1,
            "projects": [{"project_id": "fixture/target", "root": str(root)}],
        })

    def test_a_second_identical_registration_is_byte_identical(self):
        root = verifiable_repo(self.home)
        self.report(root, "--register")
        first = self.registry_path().read_bytes()
        self.report(root, "--register")
        self.assertEqual(self.registry_path().read_bytes(), first)

    def test_the_same_id_at_another_root_refuses_and_changes_nothing(self):
        root = verifiable_repo(self.home)
        self.report(root, "--register")
        before = self.registry_path().read_bytes()
        other = verifiable_repo(self.home)
        self.refuse(other, "duplicate_project_id", "--register")
        self.assertEqual(self.registry_path().read_bytes(), before)

    def test_registration_needs_a_conformant_checkout(self):
        root = verifiable_repo(self.home)
        write(root, "AGENTS.md", "hand-edited\n")
        report = self.report(root, "--register")
        self.assertEqual(report["result"], "not_conformant", report)
        self.assertIs(report["registered"], False)
        self.assertFalse(self.registry_path().exists())

    def test_two_projects_are_stored_ordered_by_project_id(self):
        beta = verifiable_repo(self.home, project_id="fixture/beta")
        alpha = verifiable_repo(self.home, project_id="fixture/alpha")
        self.report(beta, "--register")
        self.report(alpha, "--register")
        self.assertEqual(
            [entry["project_id"] for entry in self.registry()["projects"]],
            ["fixture/alpha", "fixture/beta"])

    def test_two_concurrent_registrations_both_survive(self):
        alpha = verifiable_repo(self.home, project_id="fixture/alpha")
        beta = verifiable_repo(self.home, project_id="fixture/beta")
        environment = {**os.environ, "HOME": str(self.home)}
        processes = [
            subprocess.Popen(
                [sys.executable,
                 str(Path(__file__).resolve().parents[1] / "scripts"
                     / "adopt-project.py"),
                 "verify", "--repo-root", str(root), "--register"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                env=environment)
            for root in (alpha, beta)
        ]
        results = [process.communicate() for process in processes]
        for process, (out, err) in zip(processes, results):
            self.assertEqual(process.returncode, 0, err or out)
            self.assertIs(json.loads(out)["registered"], True)
        self.assertEqual(self.registry(), {
            "schema_version": 1,
            "projects": [
                {"project_id": "fixture/alpha", "root": str(alpha)},
                {"project_id": "fixture/beta", "root": str(beta)},
            ],
        })

    def test_the_resolver_lists_the_registered_project_as_compatible(self):
        root = verifiable_repo(self.home)
        self.report(root, "--register")
        self.assertEqual(self.fleet(), [{
            "project_id": "fixture/target",
            "root": str(root),
            "project_schema_version": 1,
            "platform_interval": {"min_inclusive": "1.0.0",
                                  "max_exclusive": "2.0.0"},
            "compatible": True,
            "reason_code": None,
            "repair_id": None,
        }])


if __name__ == "__main__":
    unittest.main()
