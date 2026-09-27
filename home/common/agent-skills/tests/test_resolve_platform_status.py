"""Contract tests for `resolve-project platform-status` and its fleet view.

The fourth subcommand publishes the platform's version facts and a
compatibility verdict for a named project (R3, D2, D5, D6), and, under
`--fleet`, one verdict row per registered project read from
`$HOME/.agents/state/fleet/registry.json` (R3.4, R3.6, D18). The split it pins
is D6's: a contract that cannot be parsed into an interval is a refusal, while
an interval that parses and falls outside the range is a reported verdict on
exit 0.

The cases live beside `test_resolve_project.py` rather than inside it because
that file is the review package's binding member; the fixtures, the temporary
`HOME` and the subprocess runner are imported from it, and no `TestCase`
crosses over, so neither file collects the other's tests (the pattern
`test_adopt_project_boundaries.py` established). The gate these facts come
from — the manifest and the interval — has its own suite in
`test_resolve_platform.py`.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import sys
import tempfile
import unittest
from pathlib import Path

# The sibling suite is imported as a module, so its directory has to be
# importable however this file was invoked — `python3 <path>` supplies it,
# `python3 -m unittest <path>` does not.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_resolve_project import (
    ResolverTestCase,
    committed_manifest,
    git,
    install_registry,
    mutated_manifest,
    registry,
    run,
    source_contract,
    tree_snapshot,
)


PLATFORM_STATUS_MEMBERS = [
    "compatibility", "fleet", "platform", "project", "schema_version",
]
# The manifest's six data members plus the deployment identity (D2); the
# manifest's own `schema_version` is not one of them.
PLATFORM_BLOCK_MEMBERS = [
    "deprecations", "manifest_path", "migrations", "platform_version",
    "project_schema_versions", "removals", "resolved_schema_version",
]
PROJECT_BLOCK_MEMBERS = [
    "platform_interval", "project_id", "project_schema_version", "root",
]
COMPATIBILITY_MEMBERS = ["compatible", "reason_code", "repair_id"]
FLEET_ROW_MEMBERS = [
    "compatible", "platform_interval", "project_id", "project_schema_version",
    "reason_code", "repair_id", "root",
]


class PlatformStatusTest(ResolverTestCase):
    """R3 / D5 / D6: the fourth subcommand publishes the platform's version
    facts and a compatibility verdict, and refuses only what `resolve` refuses.

    The split this class pins is D6's: a contract that cannot be *parsed* into
    an interval is a refusal, an interval that parses and falls outside the
    range is a reported verdict on exit 0 — the case the operation exists for.
    """

    def status(self, *args: str) -> tuple[int, object, str]:
        code, out, err = run("platform-status", *args, home=self.home)
        try:
            payload: object = json.loads(out)
        except json.JSONDecodeError:
            payload = None
        return code, payload, err

    def test_with_no_target_the_platform_block_stands_alone(self):
        code, payload, err = self.status()
        self.assertEqual(code, 0, err)
        self.assertEqual(sorted(payload), PLATFORM_STATUS_MEMBERS)
        self.assertIsNone(payload["project"])
        self.assertIsNone(payload["compatibility"])
        self.assertIsNone(payload["fleet"])

    def test_the_platform_block_reports_the_manifests_data_members(self):
        """The installed manifest is the committed file (`setUp`), so the
        expected values come from that file rather than from a second run."""
        code, payload, err = self.status()
        self.assertEqual(code, 0, err)
        block = payload["platform"]
        self.assertEqual(sorted(block), PLATFORM_BLOCK_MEMBERS)
        manifest = committed_manifest()
        for name in ("platform_version", "project_schema_versions",
                     "resolved_schema_version", "migrations", "deprecations",
                     "removals"):
            with self.subTest(member=name):
                self.assertEqual(block[name], manifest[name])

    def test_the_manifest_path_is_the_resolved_installed_file(self):
        """D2: the deployment identity is the path of the file actually
        loaded, absolute and reported verbatim."""
        code, payload, err = self.status()
        self.assertEqual(code, 0, err)
        reported = payload["platform"]["manifest_path"]
        self.assertEqual(
            reported,
            str(self.home / ".agents" / "share" / "platform-manifest.json"))
        self.assertTrue(Path(reported).is_absolute())

    def test_stdout_is_compact_sorted_json_with_a_trailing_newline(self):
        code, out, err = run("platform-status", home=self.home)
        self.assertEqual(code, 0, err)
        self.assertTrue(out.endswith("\n"))
        self.assertNotIn("\n", out[:-1])
        self.assertEqual(out, json.dumps(
            json.loads(out), sort_keys=True, separators=(",", ":")) + "\n")

    def test_a_compatible_project_reports_a_clean_verdict(self):
        root = self.make_root()
        code, payload, err = self.status("--repo-root", str(root))
        self.assertEqual(code, 0, err)
        self.assertEqual(sorted(payload), PLATFORM_STATUS_MEMBERS)
        project = payload["project"]
        self.assertEqual(sorted(project), PROJECT_BLOCK_MEMBERS)
        self.assertEqual(project["project_id"], "fagenorn/nix-config")
        self.assertEqual(project["root"], str(root))
        self.assertEqual(project["project_schema_version"], 1)
        self.assertEqual(project["platform_interval"],
                         source_contract()["platform"])
        self.assertEqual(sorted(payload["compatibility"]),
                         COMPATIBILITY_MEMBERS)
        self.assertEqual(payload["compatibility"], {
            "compatible": True, "reason_code": None, "repair_id": None})
        self.assertIsNone(payload["fleet"])

    def test_an_out_of_range_platform_is_a_verdict_on_exit_zero(self):
        """D6: the committed contract declares [1.0.0, 2.0.0), so 0.9.0 is
        below its floor and 2.0.0 has already reached its exclusive ceiling."""
        cases = (
            ("0.9.0", "platform_too_old", "contract.platform.too_old"),
            ("2.0.0", "platform_too_new", "contract.platform.too_new"),
        )
        for version, reason_code, repair_id in cases:
            with self.subTest(platform_version=version):
                self.set_manifest(mutated_manifest(platform_version=version))
                code, payload, err = self.status(
                    "--repo-root", str(self.make_root()))
                self.assertEqual(code, 0, err)
                self.assertNotIn("error", payload)
                self.assertEqual(payload["compatibility"], {
                    "compatible": False, "reason_code": reason_code,
                    "repair_id": repair_id})
                self.assertEqual(payload["project"]["platform_interval"],
                                 source_contract()["platform"])
                self.assertEqual(payload["platform"]["platform_version"],
                                 version)

    def test_an_unsupported_project_schema_is_a_verdict_on_exit_zero(self):
        contract = source_contract()
        contract["schema_version"] = 2
        code, payload, err = self.status(
            "--repo-root", str(self.make_root(contract)))
        self.assertEqual(code, 0, err)
        self.assertNotIn("error", payload)
        self.assertEqual(payload["project"]["project_schema_version"], 2)
        self.assertEqual(payload["compatibility"], {
            "compatible": False,
            "reason_code": "project_schema_unsupported",
            "repair_id": "contract.schema_version.unsupported"})

    def test_a_structurally_invalid_contract_refuses_exactly_like_resolve(self):
        """R3.5: the same one-object error, the same code, the same exit."""
        contract = source_contract()
        del contract["bindings"]["deploy"]
        root = self.make_root(contract)
        code, payload, err = self.status("--repo-root", str(root))
        self.assertEqual(code, 2, err)
        self.assertEqual(sorted(payload), ["error"])
        self.assertEqual(payload["error"]["code"], "invalid_contract")
        self.assertEqual((code, payload), self.resolve(root)[:2])

    def test_a_malformed_interval_refuses_rather_than_reporting(self):
        contract = source_contract()
        contract["platform"] = {"min_inclusive": "1.0", "max_exclusive": "2.0.0"}
        code, payload, err = self.status(
            "--repo-root", str(self.make_root(contract)))
        self.assertEqual(code, 2, err)
        self.assertEqual(payload["error"]["code"], "invalid_contract")
        self.assertEqual([v["pointer"] for v in payload["error"]["violations"]],
                         ["/platform/min_inclusive"])

    def test_a_directory_with_no_contract_refuses_not_onboarded(self):
        empty = Path(tempfile.mkdtemp()).resolve()
        code, payload, err = self.status("--repo-root", str(empty))
        self.assertEqual(code, 2, err)
        self.assertEqual(sorted(payload), ["error"])
        self.assertEqual(payload["error"]["code"], "not_onboarded")


class PlatformStatusFleetTest(ResolverTestCase):
    """R3.4 / D18: one verdict row per registered project, ordered by
    `project_id`, and never a refusal for a project the operator did not name.

    The registry is staged by hand here, apart from its writer
    (`adopt-project verify --register`); this subcommand only reads it.
    """

    def fleet(self, *args: str) -> tuple[int, object, str]:
        code, out, err = run("platform-status", "--fleet", *args,
                             home=self.home)
        try:
            payload: object = json.loads(out)
        except json.JSONDecodeError:
            payload = None
        return code, payload, err

    def registered(self, project_id: str,
                   contract: object | None = None) -> tuple[dict, Path]:
        """A fixture root and the registry entry naming it."""
        root = self.make_root(contract)
        return {"project_id": project_id, "root": str(root)}, root

    def assert_reported_broken(self, row: dict, entry: dict) -> None:
        """The graceful row a broken registered project yields (R3.4)."""
        self.assertEqual(sorted(row), FLEET_ROW_MEMBERS)
        self.assertEqual(row["project_id"], entry["project_id"])
        self.assertEqual(row["root"], entry["root"])
        self.assertFalse(row["compatible"])
        self.assertEqual(row["reason_code"], "project_schema_unsupported")
        self.assertEqual(row["repair_id"], "contract.schema_version.unsupported")

    def test_an_absent_registry_is_the_empty_fleet(self):
        """And the state root is read, never created (R3.6)."""
        code, payload, err = self.fleet()
        self.assertEqual(code, 0, err)
        self.assertEqual(payload["fleet"], [])
        self.assertIsNone(payload["project"])
        self.assertIsNone(payload["compatibility"])
        self.assertFalse((self.home / ".agents" / "state").exists())

    def test_two_registered_projects_are_ordered_by_project_id(self):
        alpha_contract = source_contract()
        alpha_contract["project"]["id"] = "fagenorn/alpha"
        beta_contract = source_contract()
        beta_contract["project"]["id"] = "fagenorn/beta"
        alpha, _ = self.registered("fagenorn/alpha", alpha_contract)
        beta, _ = self.registered("fagenorn/beta", beta_contract)
        # Written in descending order, so the order asserted below is the
        # reader's and not the file's.
        install_registry(self.home, registry(beta, alpha))
        code, payload, err = self.fleet()
        self.assertEqual(code, 0, err)
        rows = payload["fleet"]
        self.assertEqual([row["project_id"] for row in rows],
                         ["fagenorn/alpha", "fagenorn/beta"])
        for row, entry in zip(rows, (alpha, beta)):
            with self.subTest(project_id=entry["project_id"]):
                self.assertEqual(sorted(row), FLEET_ROW_MEMBERS)
                self.assertEqual(row["root"], entry["root"])
                self.assertEqual(row["project_schema_version"], 1)
                self.assertEqual(row["platform_interval"],
                                 source_contract()["platform"])
                self.assertTrue(row["compatible"])
                self.assertIsNone(row["reason_code"])
                self.assertIsNone(row["repair_id"])

    def test_a_registered_root_that_is_gone_is_a_reported_row(self):
        entry, root = self.registered("fagenorn/gone")
        shutil.rmtree(root)
        install_registry(self.home, registry(entry))
        code, payload, err = self.fleet()
        self.assertEqual(code, 0, err)
        self.assertNotIn("error", payload)
        self.assertEqual(len(payload["fleet"]), 1)
        row = payload["fleet"][0]
        self.assert_reported_broken(row, entry)
        self.assertIsNone(row["project_schema_version"])
        self.assertIsNone(row["platform_interval"])

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0,
                     "root reads a 0000 file, so the case cannot be staged")
    def test_a_registered_root_with_an_unreadable_contract_is_a_reported_row(self):
        entry, root = self.registered("fagenorn/unreadable")
        contract = root / ".agents" / "project.json"
        self.addCleanup(contract.chmod, stat.S_IMODE(contract.stat().st_mode))
        contract.chmod(0o000)
        install_registry(self.home, registry(entry))
        code, payload, err = self.fleet()
        self.assertEqual(code, 0, err)
        self.assertNotIn("error", payload)
        self.assertEqual(len(payload["fleet"]), 1)
        row = payload["fleet"][0]
        self.assert_reported_broken(row, entry)
        self.assertIsNone(row["project_schema_version"])
        self.assertIsNone(row["platform_interval"])

    def test_an_invalid_contract_is_reported_in_the_fleet_and_refused_when_named(self):
        """The split of R3.4 against R3.5, in one case so it cannot regress:
        the operator named this repository, so `--repo-root` refuses it; the
        registry named it, so `--fleet` describes it."""
        contract = source_contract()
        del contract["bindings"]["deploy"]
        entry, root = self.registered("fagenorn/invalid", contract)
        install_registry(self.home, registry(entry))
        code, payload, err = self.fleet()
        self.assertEqual(code, 0, err)
        self.assertNotIn("error", payload)
        self.assertEqual(len(payload["fleet"]), 1)
        row = payload["fleet"][0]
        self.assert_reported_broken(row, entry)
        # Only the verdict is negative: what the contract does declare is
        # reported as declared.
        self.assertEqual(row["project_schema_version"], 1)
        self.assertEqual(row["platform_interval"], source_contract()["platform"])
        named_code, named_out, named_err = run(
            "platform-status", "--repo-root", str(root), home=self.home)
        self.assertEqual(named_code, 2, named_err)
        self.assertEqual(json.loads(named_out)["error"]["code"],
                         "invalid_contract")

    def test_a_registered_id_the_contract_no_longer_declares_is_incompatible(self):
        """A registry entry is an identity and a location and nothing else
        (D18), and the version facts beside it are read live. A root that has
        been replaced — or whose contract renamed the project — leaves the
        stale identity in the row, so reporting it compatible would pass the
        stale half off as the fresh one. The preflight has to say so."""
        contract = source_contract()
        contract["project"]["id"] = "fagenorn/renamed"
        entry, _ = self.registered("fagenorn/original", contract)
        install_registry(self.home, registry(entry))
        code, payload, err = self.fleet()
        self.assertEqual(code, 0, err)
        self.assertEqual(len(payload["fleet"]), 1)
        row = payload["fleet"][0]
        self.assertEqual(sorted(row), FLEET_ROW_MEMBERS)
        # The registry's identity still names the row, as D18 requires.
        self.assertEqual(row["project_id"], "fagenorn/original")
        self.assertFalse(row["compatible"])
        self.assertEqual(row["reason_code"], "project_identity_mismatch")
        self.assertEqual(row["repair_id"], "registry.project_id.mismatch")
        # Only the verdict is negative: what the contract declares is still
        # reported as declared.
        self.assertEqual(row["project_schema_version"], 1)
        self.assertEqual(row["platform_interval"], source_contract()["platform"])

    def test_a_broken_contract_keeps_its_own_reason_over_the_identity_one(self):
        """A row the contract already failed carries a verdict and a repair id
        for that failure; re-labelling it with the identity question would
        replace one true answer with another."""
        contract = source_contract()
        contract["project"]["id"] = "fagenorn/renamed"
        del contract["bindings"]["deploy"]
        entry, _ = self.registered("fagenorn/original", contract)
        install_registry(self.home, registry(entry))
        code, payload, err = self.fleet()
        self.assertEqual(code, 0, err)
        self.assert_reported_broken(payload["fleet"][0], entry)

    def test_the_broken_rows_touch_neither_the_registry_nor_the_roots(self):
        """The three witnesses of resolver D21 over every broken row at once.

        The two git witnesses are taken with the unreadable fixture in its
        readable state either side of the run, because `git status` cannot read
        a 0000 file; a write by the resolver would still show, as changed bytes
        or as a changed mtime.
        """
        gone_entry, gone_root = self.registered("fagenorn/gone")
        unreadable_entry, unreadable_root = self.registered("fagenorn/unreadable")
        invalid_contract = source_contract()
        del invalid_contract["bindings"]["deploy"]
        invalid_entry, invalid_root = self.registered(
            "fagenorn/invalid", invalid_contract)
        shutil.rmtree(gone_root)
        live = (unreadable_root, invalid_root)
        for root in live:
            git(root, "add", "-A")
            git(root, "commit", "--quiet", "-m", "fixture")
        before = {str(root): (git(root, "status", "--porcelain"),
                              tree_snapshot(root)) for root in live}
        path = install_registry(self.home, registry(
            gone_entry, unreadable_entry, invalid_entry))
        before_registry = (path.read_bytes(), path.stat().st_mtime_ns)
        contract = unreadable_root / ".agents" / "project.json"
        mode = stat.S_IMODE(contract.stat().st_mode)
        contract.chmod(0o000)
        try:
            code, payload, err = self.fleet()
        finally:
            contract.chmod(mode)
        self.assertEqual(code, 0, err)
        self.assertEqual(len(payload["fleet"]), 3)
        for row in payload["fleet"]:
            with self.subTest(project_id=row["project_id"]):
                self.assertFalse(row["compatible"])
        for root in live:
            with self.subTest(root=str(root)):
                self.assertEqual(
                    (git(root, "status", "--porcelain"), tree_snapshot(root)),
                    before[str(root)])
        self.assertFalse(gone_root.exists())
        self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns),
                         before_registry)

    def test_a_malformed_registry_refuses_as_resolver_failure(self):
        """The registry is platform-written state, so a corrupt one is an
        installation defect and never an assumed empty fleet."""
        cases = (
            ("not JSON", "{"),
            ("not an object", "[]"),
            ("an unexpected member",
             {"schema_version": 1, "projects": [], "pinned": True}),
            ("a missing member", {"schema_version": 1}),
            ("a non-array projects", {"schema_version": 1, "projects": {}}),
            ("an entry that is not an object",
             {"schema_version": 1, "projects": ["a/b"]}),
            ("an entry missing root",
             {"schema_version": 1, "projects": [{"project_id": "a/b"}]}),
            ("an entry with an unexpected member",
             {"schema_version": 1,
              "projects": [{"project_id": "a/b", "root": "/x", "pinned": True}]}),
        )
        for label, content in cases:
            with self.subTest(registry=label):
                install_registry(self.home, content)
                code, payload, err = self.fleet()
                self.assertEqual(code, 2, err)
                self.assertEqual(sorted(payload), ["error"])
                error = payload["error"]
                self.assertEqual(sorted(error),
                                 ["code", "repair_id", "violations"])
                self.assertEqual(error["code"], "resolver_failure")
                self.assertTrue(error["repair_id"].startswith(
                    "platform.registry."), error["repair_id"])
                self.assertTrue(error["violations"])
                pointers = [v["pointer"] for v in error["violations"]]
                self.assertEqual(pointers, sorted(pointers))
                for entry in error["violations"]:
                    self.assertEqual(sorted(entry), ["message", "pointer"])

    def test_repo_root_and_fleet_compose(self):
        entry, _ = self.registered("fagenorn/registered")
        install_registry(self.home, registry(entry))
        named = self.make_root()
        code, payload, err = self.fleet("--repo-root", str(named))
        self.assertEqual(code, 0, err)
        self.assertEqual(sorted(payload), PLATFORM_STATUS_MEMBERS)
        self.assertEqual(payload["project"]["root"], str(named))
        self.assertTrue(payload["compatibility"]["compatible"])
        self.assertEqual([row["project_id"] for row in payload["fleet"]],
                         ["fagenorn/registered"])


if __name__ == "__main__":
    unittest.main()
