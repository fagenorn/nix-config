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

from .test_resolve_platform_status import FLEET_ROW_MEMBERS
from .test_resolve_project import (
    REPO_ROOT,
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
            self.assertEqual(payload["platform_version"], "2.0.0")
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


class FleetPreflightCheckTest(FleetFixtures, ResolverTestCase):
    """The verify check for issue 1451: the checkout's own preflight over the real fleet."""

    SCRIPT = "home/common/verify-pending/checks/fleet-preflight"

    def setUp(self):
        super().setUp()
        install_home(self.home, None)

    def check(self, root: Path = REPO_ROOT,
              env: dict | None = None) -> tuple[int, str, str]:
        proc = subprocess.run(
            [str(root / self.SCRIPT)], cwd=root,
            env=env or {**os.environ, "HOME": str(self.home)},
            capture_output=True, text=True, timeout=120)
        return proc.returncode, proc.stdout, proc.stderr

    def three_project_fleet(self) -> Path:
        entries = [self.project(f"fagenorn/{name}")[0]
                   for name in ("gamma", "alpha", "beta")]
        return install_registry(self.home, registry(*entries))

    def test_the_check_is_committed_executable(self):
        proc = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "ls-files", "-s", self.SCRIPT],
            capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.stdout.split(" ")[0], "100755")

    def test_the_check_matches_a_multi_project_fleet(self):
        self.three_project_fleet()
        code, out, err = self.check()
        self.assertEqual(code, 0, err)
        self.assertEqual(len(out.splitlines()), 1)
        payload = json.loads(out)
        ids = ["fagenorn/alpha", "fagenorn/beta", "fagenorn/gamma"]
        self.assertEqual(payload["verdict"], "green")
        self.assertEqual([r["project_id"] for r in payload["fleet"]], ids)
        self.assertEqual(payload["registered"], ids)
        self.assertEqual(payload["missing"], [])
        self.assertEqual(payload["extra"], [])
        self.assertEqual(payload["refused"], [])
        self.assertEqual(
            payload["manifest_path"],
            str((REPO_ROOT / "home/common/agent-skills/platform-manifest.json").resolve()))

    def test_a_dropped_or_duplicated_row_is_not_met(self):
        registry_file = self.three_project_fleet()
        code, out, err = self.check()
        self.assertEqual(code, 0, err)
        payload = json.loads(out)
        report = {k: payload[k] for k in
                  ("platform_version", "manifest_path", "fleet", "refused")}
        entries = json.loads(registry_file.read_text(encoding="utf-8"))["projects"]
        from agent_tools.verification import verify_checks
        beta = [r for r in report["fleet"] if r["project_id"] == "fagenorn/beta"]
        others = [r for r in report["fleet"] if r["project_id"] != "fagenorn/beta"]
        with self.subTest("unchanged"):
            self.assertEqual(verify_checks.fleet_preflight_verdict(report, entries)[0], 0)
        with self.subTest("dropped"):
            code, verdict = verify_checks.fleet_preflight_verdict(
                {**report, "fleet": others}, entries)
            self.assertEqual(code, 1)
            self.assertEqual(verdict["verdict"], "red")
            self.assertEqual(verdict["missing"], ["fagenorn/beta"])
        with self.subTest("duplicated"):
            code, verdict = verify_checks.fleet_preflight_verdict(
                {**report, "fleet": report["fleet"] + beta}, entries)
            self.assertEqual(code, 1)
            self.assertEqual(verdict["extra"], ["fagenorn/beta"])

    def test_a_refused_project_is_not_met(self):
        alpha, _ = self.project("fagenorn/alpha")
        ahead, _ = self.project("fagenorn/ahead", min_inclusive="2.1.0")
        install_registry(self.home, registry(alpha, ahead))
        code, out, err = self.check()
        self.assertEqual(code, 1, err)
        payload = json.loads(out)
        self.assertEqual(payload["refused"], ["fagenorn/ahead"])
        self.assertEqual(payload["verdict"], "red")
        self.assertEqual(payload["missing"], [])
        self.assertEqual(payload["extra"], [])

    def test_the_judgement_and_the_comparison_read_one_registry_snapshot(self):
        from unittest import mock
        from agent_tools.project_contract import agent_platform
        from agent_tools.verification import verify_checks
        alpha, _ = self.project("fagenorn/alpha")
        beta, _ = self.project("fagenorn/beta")
        manifest = REPO_ROOT / "home/common/agent-skills/platform-manifest.json"
        with mock.patch.object(agent_platform, "read_registry",
                               side_effect=[[alpha], [alpha, beta]]) as read:
            code, verdict = verify_checks.fleet_preflight_check(manifest)
        self.assertEqual(read.call_count, 1)
        self.assertEqual(code, 0, verdict)
        self.assertEqual(verdict["verdict"], "green")
        self.assertEqual(verdict["missing"], [])
        self.assertEqual(verdict["registered"], ["fagenorn/alpha"])

    def test_an_empty_fleet_reports_no_row(self):
        code, out, err = self.check()
        self.assertEqual(code, 0, err)
        payload = json.loads(out)
        self.assertEqual(payload["fleet"], [])
        self.assertEqual(payload["registered"], [])

    def test_an_unreadable_registry_is_an_error(self):
        install_registry(self.home, "{")
        code, out, err = self.check()
        self.assertEqual(code, 2, err)
        self.assertEqual(json.loads(out), {"verdict": "unreadable",
                                           "repair_id": "platform.registry.parse"})

    def test_a_registered_source_checkout_gets_no_bytecode(self):
        entry, root = self.project("fagenorn/self")
        shutil.copytree(REPO_ROOT / "python", root / "python",
                        ignore=shutil.ignore_patterns("__pycache__"))
        manifest = root / "home/common/agent-skills/platform-manifest.json"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / "home/common/agent-skills/platform-manifest.json", manifest)
        script = root / self.SCRIPT
        script.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / self.SCRIPT, script)
        script.chmod(0o755)
        install_registry(self.home, registry(entry))
        before = tree_snapshot(root)
        env = {**os.environ, "HOME": str(self.home)}
        for name in ("PYTHONPYCACHEPREFIX", "PYTHONDONTWRITEBYTECODE", "PYTHONPATH"):
            env.pop(name, None)
        code, out, err = self.check(root, env)
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["registered"], ["fagenorn/self"])
        self.assertEqual(sorted(str(p.relative_to(root))
                                for p in root.rglob("__pycache__")), [])
        self.assertEqual(tree_snapshot(root), before)
