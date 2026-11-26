"""Contract tests for `fleet-preflight`, the check the switch recipes run before activation (issue 1451).

The command judges every project in the host's fleet registry against a
candidate platform manifest, with this checkout's code, and refuses the switch
when a project could not run on the candidate. The cases run it as a real child
process under a temporary `HOME`, so they pin the process contract: exit codes,
the text and JSON outputs, and that nothing is written. The fixtures come from
`test_resolve_project.py` and the row shape from `test_resolve_platform_status.py`.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import mock

from agent_tools.project_contract import derived_values, fleet_preflight

from .test_resolve_platform_status import FLEET_ROW_MEMBERS
from .test_resolve_project import (
    REPO_ROOT,
    InProcessTestCase,
    ResolverTestCase,
    committed_manifest,
    git,
    install_home,
    install_registry,
    mutated_manifest,
    registry,
    source_contract,
    tree_snapshot,
)
from .test_resolve_schema_three import (
    EXPECTED_DERIVED,
    make_schema_three_root,
    schema_three_contract,
    stage_locked_platform,
)


class FleetFixtures:
    """Registered-project fixtures shared by the preflight and its verify check."""

    def project(self, project_id: str, *, min_inclusive: str = "1.2.0",
                max_exclusive: str = "3.0.0",
                contract: dict | None = None) -> tuple[dict, Path]:
        if contract is None:
            contract = source_contract()
            contract["project"]["id"] = project_id
            contract["platform"] = {"min_inclusive": min_inclusive,
                                    "max_exclusive": max_exclusive}
        root = self.make_root(contract)
        return {"project_id": project_id, "root": str(root)}, root


class FleetPreflightTest(FleetFixtures, ResolverTestCase):
    def candidate(self, version: str | None = None) -> Path:
        manifest = (committed_manifest() if version is None
                    else mutated_manifest(platform_version=version))
        path = Path(tempfile.mkdtemp()).resolve() / "platform-manifest.json"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        return path

    def preflight(self, *args: str, env: dict | None = None,
                  cwd: Path | None = None, timeout: int = 60) -> tuple[int, str, str]:
        proc = subprocess.run(
            [sys.executable, "-m", "agent_tools.project_contract.fleet_preflight",
             *args],
            capture_output=True, text=True, timeout=timeout, cwd=cwd,
            env={**os.environ, "HOME": str(self.home), **(env or {})},
        )
        return proc.returncode, proc.stdout, proc.stderr

    def rows(self, out: str) -> list[list[str]]:
        return [line.split(" ") for line in out.splitlines()
                if line.split(" ")[0] in ("compatible", "refused")]

    def two_project_fleet(self) -> tuple[Path, Path]:
        """alpha accepts 3.0.0, beta does not; declared in descending order."""
        alpha, alpha_root = self.project("fagenorn/alpha", max_exclusive="4.0.0")
        beta, beta_root = self.project("fagenorn/beta")
        install_registry(self.home, registry(beta, alpha))
        return alpha_root, beta_root

    def test_a_schema_two_project_is_reported_with_its_deprecated_use(self):
        entry, root = self.project("fagenorn/alpha")
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        install_registry(self.home, registry(entry))
        manifest = self.candidate()
        self.addCleanup(shutil.rmtree, manifest.parent, ignore_errors=True)
        code, out, err = self.preflight("--manifest", str(manifest), "--json")
        self.assertEqual(code, 0, err)
        payload = json.loads(out)
        self.assertEqual(payload["fleet"][0]["deprecated_uses"],
                         ["platform-constants"])
        self.assertEqual(payload["refused"], [])
        code, out, err = self.preflight("--manifest", str(manifest))
        self.assertEqual(code, 0, err)
        lines = out.splitlines()
        at = lines.index(f"compatible fagenorn/alpha {root}")
        self.assertEqual(
            lines[at + 1],
            f"deprecated fagenorn/alpha {root} platform-constants")
        self.assertEqual(self.rows(out),
                         [["compatible", "fagenorn/alpha", str(root)]])

    def test_an_out_of_range_project_refuses_with_its_reason_code(self):
        alpha_root, beta_root = self.two_project_fleet()
        candidate = self.candidate("3.0.0")
        code, out, err = self.preflight("--manifest", str(candidate))
        self.assertEqual(code, 1, err)
        first = out.splitlines()[0]
        self.assertIn("3.0.0", first)
        self.assertIn(str(candidate), first)
        self.assertEqual(self.rows(out), [
            ["compatible", "fagenorn/alpha", str(alpha_root)],
            ["refused", "fagenorn/beta", str(beta_root),
             "platform_too_new", "contract.platform.too_new"],
        ])

    def test_a_structurally_invalid_contract_refuses(self):
        contract = source_contract()
        contract["project"]["id"] = "fagenorn/broken"
        del contract["bindings"]["paths"]
        entry, root = self.project("fagenorn/broken", contract=contract)
        install_registry(self.home, registry(entry))
        code, out, err = self.preflight("--manifest", str(self.candidate()))
        self.assertEqual(code, 1, err)
        self.assertEqual(self.rows(out), [
            ["refused", "fagenorn/broken", str(root),
             "project_schema_unsupported", "contract.schema_version.unsupported"],
        ])

    def test_a_compatible_fleet_passes_on_a_host_with_no_installed_platform(self):
        install_home(self.home, None)
        entry, root = self.project("fagenorn/alpha")
        install_registry(self.home, registry(entry))
        code, out, err = self.preflight("--manifest", str(self.candidate()))
        self.assertEqual(code, 0, err)
        self.assertEqual(self.rows(out), [["compatible", "fagenorn/alpha", str(root)]])
        self.assertEqual(err, "")

    def test_an_absent_registry_is_the_empty_fleet_and_passes(self):
        code, out, err = self.preflight("--manifest", str(self.candidate()))
        self.assertEqual(code, 0, err)
        self.assertEqual(self.rows(out), [])
        self.assertTrue(out.strip())
        self.assertFalse((self.home / ".agents" / "state").exists())

    def test_an_unreadable_registry_refuses(self):
        entry, _ = self.project("fagenorn/alpha")
        candidate = str(self.candidate())
        state = self.home / ".agents" / "state"
        fleet = state / "fleet"
        missing = self.home / "missing"

        def unreadable() -> str:
            install_registry(self.home, registry(entry)).chmod(0o000)
            return "platform.registry.unreadable"

        def not_json() -> str:
            install_registry(self.home, "{")
            return "platform.registry.parse"

        def unknown_member() -> str:
            install_registry(
                self.home, {"schema_version": 1, "projects": [], "pinned": True})
            return "platform.registry."

        def dangling_registry() -> str:
            fleet.mkdir(parents=True, exist_ok=True)
            os.symlink(missing, fleet / "registry.json")
            return "platform.registry.unreadable"

        def dangling_directory() -> str:
            state.mkdir(parents=True, exist_ok=True)
            os.symlink(missing, fleet)
            return "platform.registry.unreadable"

        def fifo_registry() -> str:
            fleet.mkdir(parents=True, exist_ok=True)
            os.mkfifo(fleet / "registry.json")
            return "platform.registry.unreadable"

        cases = {
            "chmod 000": (unreadable, False),
            "fifo registry": (fifo_registry, True),
            "not json": (not_json, True),
            "unknown member": (unknown_member, False),
            "dangling registry link": (dangling_registry, True),
            "dangling fleet link": (dangling_directory, False),
        }
        for name, (make, with_json) in cases.items():
            with self.subTest(name):
                repair_id = make()
                try:
                    code, out, err = self.preflight(
                        "--manifest", candidate, timeout=20)
                    self.assertEqual(code, 2, err)
                    self.assertEqual(out, "")
                    self.assertIn(repair_id, err)
                    if with_json:
                        code, out, err = self.preflight(
                            "--manifest", candidate, "--json")
                        self.assertEqual(code, 2, err)
                        payload = json.loads(out)
                        self.assertEqual(list(payload), ["error"])
                        self.assertEqual(payload["error"]["code"],
                                         "resolver_failure")
                        self.assertEqual(payload["error"]["repair_id"],
                                         repair_id)
                finally:
                    registry_file = fleet / "registry.json"
                    if registry_file.exists() and not registry_file.is_symlink():
                        registry_file.chmod(0o600)
                    if state.is_symlink() or fleet.is_symlink():
                        (fleet if fleet.is_symlink() else state).unlink()
                    if state.exists():
                        shutil.rmtree(state)

    def test_a_home_that_is_not_an_absolute_path_refuses(self):
        entry, _ = self.project("fagenorn/alpha")
        install_registry(self.home, registry(entry))
        candidate = str(self.candidate())
        elsewhere = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, elsewhere, True)
        for home in ("", "relative/home"):
            with self.subTest(home=home):
                code, out, err = self.preflight(
                    "--manifest", candidate, cwd=elsewhere,
                    env={"HOME": home, "PYTHONPATH": str(REPO_ROOT / "python")})
                self.assertEqual(code, 2, err)
                self.assertEqual(out, "")
                self.assertIn("platform.registry.unreadable", err)

    def test_the_preflight_changes_no_project_and_no_registry(self):
        alpha_root, beta_root = self.two_project_fleet()
        registry_file = self.home / ".agents" / "state" / "fleet" / "registry.json"
        candidate = self.candidate("3.0.0")
        for root in (alpha_root, beta_root):
            git(root, "add", "-A")
            git(root, "commit", "--quiet", "-m", "fixture")

        def record() -> dict:
            state = {str(r): (git(r, "status", "--porcelain"), tree_snapshot(r))
                     for r in (alpha_root, beta_root)}
            for path in (registry_file, candidate):
                state[str(path)] = (path.read_bytes(), path.stat().st_mtime_ns)
            return state

        before = record()
        code, _, err = self.preflight("--manifest", str(candidate))
        self.assertEqual(code, 1, err)
        code, out, err = self.preflight("--manifest", str(candidate), "--json")
        self.assertEqual(code, 1, err)
        self.assertEqual(json.loads(out)["refused"], ["fagenorn/beta"])
        self.assertEqual(record(), before)
        self.assertEqual(
            sorted(p.name for p in registry_file.parent.iterdir()),
            ["registry.json"])

    def test_the_json_report(self):
        self.two_project_fleet()
        candidate = self.candidate("3.0.0")
        code, out, err = self.preflight("--manifest", str(candidate), "--json")
        self.assertEqual(code, 1, err)
        payload = json.loads(out)
        self.assertEqual(sorted(payload), [
            "fleet", "manifest_path", "platform_version", "refused",
            "schema_version"])
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["platform_version"], "3.0.0")
        self.assertEqual(payload["manifest_path"], str(candidate.resolve()))
        self.assertEqual([r["project_id"] for r in payload["fleet"]],
                         ["fagenorn/alpha", "fagenorn/beta"])
        for row in payload["fleet"]:
            self.assertEqual(sorted(row), FLEET_ROW_MEMBERS)
        self.assertEqual(payload["refused"], ["fagenorn/beta"])
        self.assertTrue(out.endswith("\n"))
        self.assertFalse(out.endswith("\n\n"))

    def test_the_preflight_has_no_skip_option(self):
        from agent_tools.project_contract import fleet_preflight
        parser = fleet_preflight.build_parser()
        self.assertEqual(parser.prog, "fleet-preflight")
        options = {option for action in parser._actions
                   for option in action.option_strings}
        self.assertEqual(options, {"-h", "--help", "--manifest", "--json"})
        code, out, _ = self.preflight()
        self.assertEqual((code, out), (2, ""))
        code, out, _ = self.preflight("--manifest", str(self.candidate()),
                                      "--force")
        self.assertEqual((code, out), (2, ""))

    def test_the_installed_platform_never_changes_the_verdict(self):
        self.two_project_fleet()
        platform_root = Path(tempfile.mkdtemp()).resolve()
        manifest_file = platform_root / "platform-manifest.json"
        with self.subTest("installed is newer"):
            newer = mutated_manifest(platform_version="3.0.0")
            self.set_manifest(newer)
            manifest_file.write_text(json.dumps(newer), encoding="utf-8")
            code, out, err = self.preflight(
                "--manifest", str(self.candidate()), "--json",
                env={"AGENT_PLATFORM_ROOT": str(platform_root)})
            self.assertEqual(code, 0, err)
            payload = json.loads(out)
            self.assertEqual(payload["refused"], [])
            self.assertEqual(payload["platform_version"],
                             committed_manifest()["platform_version"])
        with self.subTest("installed is older"):
            self.set_manifest(committed_manifest())
            manifest_file.write_text(json.dumps(committed_manifest()),
                                     encoding="utf-8")
            code, out, err = self.preflight(
                "--manifest", str(self.candidate("3.0.0")), "--json",
                env={"AGENT_PLATFORM_ROOT": str(platform_root)})
            self.assertEqual(code, 1, err)
            payload = json.loads(out)
            self.assertEqual(payload["refused"], ["fagenorn/beta"])
            self.assertEqual(payload["platform_version"], "3.0.0")

    def test_the_command_has_one_table_row(self):
        table = (REPO_ROOT / "lib" / "agent-tools.nix").read_text("utf-8")
        row = '    "fleet-preflight" = "project_contract.fleet_preflight";'
        self.assertEqual(table.splitlines().count(row), 1)


class SchemaThreeFleetTest(InProcessTestCase):
    """A schema-3 fleet member is judged against its derived range and identity (ADR-project-contract-014)."""

    def candidate(self, version: str) -> Path:
        directory = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        path = directory / "platform-manifest.json"
        path.write_text(json.dumps(mutated_manifest(platform_version=version)),
                        encoding="utf-8")
        return path

    def register(self, root: Path) -> None:
        install_registry(self.home, registry(
            {"project_id": "fagenorn/nix-config", "root": str(root)}))

    def test_a_schema_three_project_is_judged_against_its_locked_range(self):
        store = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, store, ignore_errors=True)
        root = make_schema_three_root(schema_three_contract(), tree_manifest=False)
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        stage_locked_platform(root, store, "2.0.0")
        self.register(root)
        patch = mock.patch.object(derived_values, "STORE_DIR", str(store))
        patch.start()
        self.addCleanup(patch.stop)
        with self.subTest("3.0.0"):
            report = fleet_preflight.preflight(self.candidate("3.0.0"))
            self.assertEqual(report["refused"], ["fagenorn/nix-config"])
            row = report["fleet"][0]
            self.assertEqual(row["reason_code"], "platform_too_new")
            self.assertEqual(row["platform_interval"],
                             {"min_inclusive": "2.0.0", "max_exclusive": "3.0.0"})
            self.assertEqual(row["project_schema_version"], 3)
        with self.subTest("2.5.0"):
            report = fleet_preflight.preflight(self.candidate("2.5.0"))
            self.assertEqual(report["refused"], [])
            self.assertTrue(report["fleet"][0]["compatible"])

    def preflight_subprocess(self, manifest: Path) -> tuple[int, str, str]:
        proc = subprocess.run(
            [sys.executable, "-m", "agent_tools.project_contract.fleet_preflight",
             "--manifest", str(manifest), "--json"],
            capture_output=True, text=True, timeout=60,
            env={**os.environ, "HOME": str(self.home)})
        return proc.returncode, proc.stdout, proc.stderr

    def test_the_platforms_own_tree_is_compatible_with_a_candidate_from_that_tree(self):
        root = make_schema_three_root(schema_three_contract())
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        self.register(root)
        manifest = Path(tempfile.mkdtemp()).resolve() / "platform-manifest.json"
        self.addCleanup(shutil.rmtree, manifest.parent, ignore_errors=True)
        manifest.write_text(json.dumps(committed_manifest()), encoding="utf-8")
        code, out, err = self.preflight_subprocess(manifest)
        self.assertEqual(code, 0, err)
        row = json.loads(out)["fleet"][0]
        self.assertTrue(row["compatible"])
        self.assertEqual(row["platform_interval"], EXPECTED_DERIVED["/platform"])

    def test_an_underivable_schema_three_row_is_refused_not_crashed(self):
        root = make_schema_three_root(schema_three_contract(), remote=None)
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        self.register(root)
        manifest = Path(tempfile.mkdtemp()).resolve() / "platform-manifest.json"
        self.addCleanup(shutil.rmtree, manifest.parent, ignore_errors=True)
        manifest.write_text(json.dumps(committed_manifest()), encoding="utf-8")
        code, out, err = self.preflight_subprocess(manifest)
        self.assertEqual(code, 1, err)
        row = json.loads(out)["fleet"][0]
        self.assertEqual(row["reason_code"], "project_schema_unsupported")
