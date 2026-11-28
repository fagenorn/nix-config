"""The agent_tools layout rule: subpackages are the docs areas, imports follow one table."""

import ast
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from collections.abc import Mapping
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE = REPO_ROOT / "python/agent_tools"
AREAS_DIR = REPO_ROOT / "docs/areas"
SHARED = "system"

# Importing area -> dotted modules of other areas it may import, each edge
# commented with the importing modules. Adding an edge is a reviewed change to
# this table.
ALLOWED_IMPORTS: dict[str, frozenset[str]] = {
    "claims": frozenset({
        "agent_tools.project_contract.agent_platform",  # owner_actions
        "agent_tools.console.sessions",  # claim_takeover
    }),
    "console": frozenset({
        "agent_tools.project_contract.agent_platform",  # service, permission
        "agent_tools.project_contract.resolve_project",  # deliveries, permission, project_question
        "agent_tools.project_contract.adopt_inspection",  # plan_questions, checkout_remote
        "agent_tools.project_contract.adopt_conformance",  # contract_draft, draft_register_check
        "agent_tools.project_contract.adopt_planning",  # draft_register_check
        "agent_tools.project_contract.adopt_project",  # draft_register_check
        "agent_tools.project_contract.attempt_history",  # contract_draft
        "agent_tools.project_contract.derived_values",  # contract_draft
        "agent_tools.project_contract.hook_install",  # contract_draft
        "agent_tools.project_contract.schema_three",  # contract_draft
        "agent_tools.project_contract.adopt_apply",  # approve
        "agent_tools.claims.forge_markers",  # answer, inbox, look_check, look_kept_check
        "agent_tools.claims.forge_land_lock",  # movement, lock_wait_check
        "agent_tools.claims.forge_owner_action",  # answer, inbox
        "agent_tools.claims.owner_actions",  # inbox, look_check, movement, service
        "agent_tools.delivery.look_marker",  # inbox, look_check, look_kept_check
        "agent_tools.delivery.engine_ledger",  # console, engine_runs
        "agent_tools.release.release_profile",  # release_card
        "agent_tools.release.transaction_history",  # movement
        "agent_tools.release.transaction_storage",  # movement
        "agent_tools.verification.verify_checks",  # live_fault_check
        "agent_tools.verification.verify_answer",  # answer, inbox, service
        "agent_tools.verification.verify_owner",  # view
        "agent_tools.verification.verify_wait",  # inbox
        "agent_tools.hosts.model_pricing",  # spend
    }),
    "delivery": frozenset({
        "agent_tools.claims.forge_land_lock",  # landing
        "agent_tools.console.inbox",  # look_approval
        "agent_tools.claims.forge_markers",  # look_marker, look_approval, cleanup_issue
        "agent_tools.project_contract.adopt_conformance",  # proof_run
        "agent_tools.project_contract.agent_platform",  # standards_lint, cleanup_issue, engine_shell
        "agent_tools.project_contract.attempt_history",  # attempt_budget
        "agent_tools.project_contract.derived_values",  # verify_slot
        "agent_tools.project_contract.resolve_project",  # issue_branch, engine_shell
        "agent_tools.verification.verified_tree",  # landing
        "agent_tools.verification.verify_block",  # holding
        "agent_tools.verification.verify_issues",  # holding
        "agent_tools.verification.verify_pending",  # holding
    }),
    "guard": frozenset({
        "agent_tools.project_contract.adopt_inspection",  # guard_policy, contract_export
        "agent_tools.project_contract.adopt_verify",  # guard_policy
        "agent_tools.project_contract.agent_platform",  # guard_policy
        "agent_tools.project_contract.resolve_project",  # guard_policy, contract_export
        "agent_tools.release.forge_adapter",  # guard_policy
        "agent_tools.release.release_profile",  # guard_policy
    }),
    "hosts": frozenset({
        "agent_tools.delivery.verify_history",  # omlx_memory_day
        "agent_tools.delivery.verify_slot",  # omlx_memory_day
    }),
    "project_contract": frozenset({
        "agent_tools.release.release_adapter",  # resolve_project, conformance_checks
        "agent_tools.release.release_profile",  # resolve_project, conformance_checks
        "agent_tools.delivery.hint_phases",  # adopt_inspection, adopt_planning
        "agent_tools.delivery.host_admission",  # conformance_checks
        "agent_tools.delivery.context_map_lint",  # conformance_checks
        "agent_tools.delivery.standards_lint",  # conformance_checks
        "agent_tools.delivery.never_rise",  # conformance_checks
        "agent_tools.delivery.node_lint",  # conformance_checks
        "agent_tools.delivery.record_lint",  # conformance_checks
        "agent_tools.delivery.size_lint",  # conformance_checks
        "agent_tools.delivery.comment_lint",  # conformance_checks
        "agent_tools.delivery.ruff_lint",  # conformance_checks
        "agent_tools.delivery.lint_time",  # conformance
        "agent_tools.delivery.skipped_test_lint",  # conformance_checks
        "agent_tools.delivery.copied_test_lint",  # conformance_checks
        "agent_tools.delivery.instruction_surface_lint",  # conformance_checks
        "agent_tools.delivery.engine_commands",  # conformance_checks
        "agent_tools.delivery.procedure_check",  # conformance_checks
        "agent_tools.release.railway_deploy_adapter",  # host_readiness
        "agent_tools.release.codesigned_artifact_adapter",  # host_readiness
    }),
    "release": frozenset({
        "agent_tools.claims.forge_land_lock",  # release_lock
        "agent_tools.console.release_card",  # release
        "agent_tools.project_contract.resolve_project",  # release
    }),
    "verification": frozenset({
        "agent_tools.project_contract.resolve_project",  # verified_tree, verify_pending
        "agent_tools.console.permission",  # console_production_rerun
        "agent_tools.project_contract.agent_platform",  # verify_checks, verify_pending, adopt_hook_check
        "agent_tools.claims.forge_markers",  # verify_facts, verify_issues, verify_owner, verify_run
        "agent_tools.claims.forge_claim",  # verify_owner
        "agent_tools.claims.forge_owner_action",  # verify_run
        "agent_tools.claims.owner_actions",  # verify_pending
        "agent_tools.guard.guard_policy",  # verify_exec
        "agent_tools.project_contract.adopt_inspection",  # verify_exec
        "agent_tools.project_contract.adopt_verify",  # verify_exec
        "agent_tools.project_contract.adopt_apply",  # verify_checks (run_leashed)
    }),
}


def delivery_targets(targets) -> list[str]:
    """The targets that are the delivery package or a module under it."""
    return sorted(t for t in targets if t == "agent_tools.delivery"
                  or t.startswith("agent_tools.delivery."))


def area_packages(areas_dir: Path) -> frozenset[str]:
    """The area names a subpackage may carry: one per docs/areas directory."""
    return frozenset(d.name.replace("-", "_") for d in areas_dir.iterdir() if d.is_dir())


def _imports(tree: ast.AST):
    """Yield (line, level, module, names) for every import, nested ones included."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, 0, alias.name, None
        elif isinstance(node, ast.ImportFrom):
            yield (node.lineno, node.level, node.module or "",
                   [alias.name for alias in node.names])


def _targets(root: Path, module: str, names) -> list[str]:
    """The dotted modules one import statement reaches, or [] for a foreign one."""
    parts = module.split(".")
    if parts[0] != "agent_tools":
        return []
    if names is None:
        return [module]
    if len(parts) == 1:
        return [f"agent_tools.{name}" for name in names]
    if len(parts) == 2:
        found = [f"{module}.{name}" for name in names
                 if (root / parts[1] / f"{name}.py").is_file() or (root / parts[1] / name).is_dir()]
        return found or [module]
    return [module]


FLAT_ROOTS = ("instruction_load", "skill_lint")


def flat_modules(root: Path) -> frozenset[str]:
    """The flat root modules and every flat module they import."""
    pending = list(FLAT_ROOTS)
    seen: set[str] = set()
    while pending:
        name = pending.pop()
        source = root / f"{name}.py"
        if name in seen or not source.is_file():
            continue
        seen.add(name)
        for _line, level, module, names in _imports(ast.parse(source.read_text("utf-8"))):
            if level:
                continue
            for target in _targets(root, module, names):
                parts = target.split(".")
                if len(parts) >= 2 and parts[0] == "agent_tools":
                    pending.append(parts[1])
    return frozenset(seen)


def _has_python(directory: Path) -> bool:
    return any(directory.rglob("*.py"))


def _docstring_only(init: Path) -> bool:
    body = ast.parse(init.read_text("utf-8")).body
    return not body or (len(body) == 1 and isinstance(body[0], ast.Expr)
                        and isinstance(body[0].value, ast.Constant)
                        and isinstance(body[0].value.value, str))


def _structure(root: Path, areas, flat_allowed) -> list[str]:
    found = []
    flat = {path.stem for path in root.glob("*.py")}
    for stem in sorted(flat - flat_allowed):
        found.append(f"flat module agent_tools.{stem} is not allowed at the top level")
    for package in sorted(d for d in root.iterdir()
                          if d.is_dir() and d.name != "__pycache__" and _has_python(d)):
        name = package.name
        if name not in areas:
            found.append(f"subpackage agent_tools.{name} is not an area")
        if not (package / "__init__.py").is_file():
            found.append(f"subpackage agent_tools.{name} has no __init__.py")
        elif not _docstring_only(package / "__init__.py"):
            found.append(f"subpackage agent_tools.{name} __init__.py holds more than a docstring")
        for inner in sorted(d for d in package.iterdir()
                            if d.is_dir() and d.name != "__pycache__" and _has_python(d)):
            found.append(f"nested package agent_tools.{name}.{inner.name} is not allowed")
    return found


def _import_violations(root, areas, allowed) -> list[str]:
    found = []
    used: set[tuple[str, str]] = set()

    def area_of(parts: list[str]) -> str | None:
        """The area a dotted name sits in, None for a top-level module."""
        if len(parts) >= 3 or (len(parts) == 2 and (root / parts[1]).is_dir()):
            return parts[1]
        return None

    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root).with_suffix("")
        parts = list(rel.parts[:-1]) if rel.name == "__init__" else list(rel.parts)
        importer = ".".join(["agent_tools", *parts])
        importer_area = parts[0] if len(parts) > 1 or (path.parent != root) else None
        for line, level, module, names in _imports(ast.parse(path.read_text("utf-8"))):
            if level:
                found.append(f"{importer}:{line} uses a relative import")
                continue
            for target in _targets(root, module, names):
                target_parts = target.split(".")
                if len(target_parts) == 1:
                    continue
                target_area = area_of(target_parts)
                if importer_area is None:
                    ok = target_area is None
                elif importer_area == SHARED:
                    ok = target_area in (None, SHARED)
                elif target_area in (None, SHARED, importer_area):
                    ok = True
                else:
                    ok = target in allowed.get(importer_area, frozenset())
                    if ok:
                        used.add((importer_area, target))
                if not ok:
                    found.append(f"{importer}:{line} may not import {target}")
    for area, targets in allowed.items():
        for target in sorted(targets - {t for a, t in used if a == area}):
            found.append(f"allowed edge {area} -> {target} is unused")
    return found


def layout_violations(root: Path, *, areas: frozenset[str],
                      allowed: Mapping[str, frozenset[str]],
                      flat_allowed: frozenset[str]) -> list[str]:
    """Sorted layout messages for an agent_tools package directory; [] when clean."""
    return sorted(_structure(root, areas, flat_allowed)
                  + _import_violations(root, areas, allowed))


BASE = {
    "__init__.py": '"""Root."""\n',
    "canonical.py": "",
    "alpha/__init__.py": '"""Alpha."""\n',
    "alpha/a.py": ("from agent_tools.alpha import b\n"
                   "from agent_tools import canonical\n"
                   "from agent_tools.system import util\n"),
    "alpha/b.py": "",
    "beta/__init__.py": '"""Beta."""\n',
    "beta/c.py": "from agent_tools.alpha.a import X\n",
    "system/__init__.py": '"""System."""\n',
    "system/util.py": "",
}
DEFAULT_ALLOWED = {"beta": frozenset({"agent_tools.alpha.a"})}


class SyntheticLayoutTest(unittest.TestCase):
    def tree(self, files):
        parent = tempfile.TemporaryDirectory()
        self.addCleanup(parent.cleanup)
        root = Path(parent.name) / "agent_tools"
        for rel, text in files.items():
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, "utf-8")
        return root

    def violations(self, files, *, allowed=None):
        return layout_violations(
            self.tree(files),
            areas=frozenset({"alpha", "beta", "system"}),
            allowed=DEFAULT_ALLOWED if allowed is None else allowed,
            flat_allowed=frozenset({"__init__", "canonical"}))

    def test_a_clean_tree_has_no_violations(self):
        self.assertEqual(self.violations(BASE), [])

    def test_a_planted_cross_area_import_is_refused(self):
        files = {**BASE, "beta/d.py": "from agent_tools.alpha import b\n"}
        self.assertEqual(self.violations(files),
                         ["agent_tools.beta.d:1 may not import agent_tools.alpha.b"])

    def test_an_import_inside_a_function_is_refused(self):
        files = {**BASE, "beta/e.py": "def f():\n    import agent_tools.alpha.b\n"}
        self.assertEqual(self.violations(files),
                         ["agent_tools.beta.e:2 may not import agent_tools.alpha.b"])

    def test_importing_another_area_package_is_refused(self):
        files = {**BASE, "beta/g.py": "from agent_tools import alpha\n"}
        self.assertEqual(self.violations(files),
                         ["agent_tools.beta.g:1 may not import agent_tools.alpha"])

    def test_a_relative_import_is_refused(self):
        files = {**BASE, "alpha/f.py": "from . import b\n"}
        self.assertEqual(self.violations(files),
                         ["agent_tools.alpha.f:1 uses a relative import"])

    def test_system_may_not_import_an_area(self):
        files = {**BASE, "system/util2.py": "from agent_tools.alpha import b\n"}
        self.assertEqual(self.violations(files),
                         ["agent_tools.system.util2:1 may not import agent_tools.alpha.b"])

    def test_a_top_level_module_imports_only_top_level_modules(self):
        files = {**BASE, "canonical.py": "from agent_tools.system import util\n"}
        self.assertEqual(self.violations(files),
                         ["agent_tools.canonical:1 may not import agent_tools.system.util"])

    def test_a_flat_module_outside_the_allowance_is_refused(self):
        files = {**BASE, "stray.py": ""}
        self.assertEqual(self.violations(files),
                         ["flat module agent_tools.stray is not allowed at the top level"])

    def test_a_subpackage_that_is_not_an_area_is_refused(self):
        files = {**BASE, "gamma/__init__.py": '"""Gamma."""\n', "gamma/x.py": ""}
        self.assertEqual(self.violations(files),
                         ["subpackage agent_tools.gamma is not an area"])

    def test_a_subpackage_needs_a_docstring_only_init(self):
        files = {key: text for key, text in BASE.items() if key != "alpha/__init__.py"}
        self.assertEqual(self.violations(files),
                         ["subpackage agent_tools.alpha has no __init__.py"])
        files = {**BASE, "alpha/__init__.py":
                 '"""A."""\nfrom agent_tools.alpha import b\n'}
        self.assertEqual(
            self.violations(files),
            ["subpackage agent_tools.alpha __init__.py holds more than a docstring"])

    def test_a_nested_package_is_refused(self):
        files = {**BASE, "alpha/inner/__init__.py": '"""Inner."""\n',
                 "alpha/inner/x.py": ""}
        self.assertEqual(self.violations(files),
                         ["nested package agent_tools.alpha.inner is not allowed"])

    def test_an_unused_allowed_edge_is_refused(self):
        allowed = {"beta": frozenset({"agent_tools.alpha.a", "agent_tools.alpha.b"})}
        self.assertEqual(self.violations(BASE, allowed=allowed),
                         ["allowed edge beta -> agent_tools.alpha.b is unused"])


class LayoutRuleTest(unittest.TestCase):
    def test_verification_imports_nothing_from_delivery(self):
        self.assertEqual(delivery_targets(ALLOWED_IMPORTS["verification"]), [])

    def test_the_delivery_package_itself_counts_as_delivery(self):
        self.assertEqual(
            delivery_targets({"agent_tools.delivery", "agent_tools.delivery.x",
                              "agent_tools.deliveryx", "agent_tools.claims.forge_markers"}),
            ["agent_tools.delivery", "agent_tools.delivery.x"])

    def test_the_flat_allowance_is_the_closure_of_instruction_load_and_skill_lint(self):
        self.assertEqual(
            flat_modules(PACKAGE),
            frozenset({"instruction_load", "skill_lint", "agent_model_matrix", "canonical"}))

    def test_the_package_follows_the_layout_rule(self):
        self.assertEqual(
            layout_violations(PACKAGE, areas=area_packages(AREAS_DIR),
                              allowed=ALLOWED_IMPORTS,
                              flat_allowed=flat_modules(PACKAGE) | {"__init__"}), [])

    def test_the_areas_are_the_docs_areas(self):
        self.assertEqual(
            area_packages(AREAS_DIR),
            frozenset({"claims", "console", "delivery", "guard", "hosts", "project_contract",
                       "release", "system", "verification"}))


class LightLaneRetirementTest(unittest.TestCase):
    def test_the_repository_contract_declares_no_light_lane(self):
        home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, home, True)
        (home / ".agents" / "share").mkdir(parents=True)
        manifest = REPO_ROOT / "home/common/agent-skills/platform-manifest.json"
        (home / ".agents" / "share" / "platform-manifest.json").write_bytes(manifest.read_bytes())
        env = {**os.environ, "HOME": str(home), "PYTHONPATH": str(REPO_ROOT / "python")}
        done = subprocess.run(
            [sys.executable, "-m", "agent_tools.project_contract.resolve_project", "resolve",
             "--repo-root", str(REPO_ROOT)],
            env=env, text=True, stdin=subprocess.DEVNULL, capture_output=True)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        snapshot = json.loads(done.stdout)
        self.assertNotIn("light_lane", snapshot["bindings"]["workflow"])

    def test_the_lane_triage_command_is_retired(self):
        table = (REPO_ROOT / "lib/agent-tools.nix").read_text()
        justfile = (REPO_ROOT / "justfile").read_text()
        timings = json.loads((PACKAGE / "delivery/suite_timings.json").read_text())
        self.assertIsNone(re.search(r'^\s*"lane-triage"\s*=', table, re.M))
        self.assertEqual(sorted(PACKAGE.rglob("lane_triage.py")), [])
        self.assertFalse((REPO_ROOT / "tests/test_lane_triage.py").exists())
        self.assertNotIn("tests/test_lane_triage.py", justfile)
        self.assertNotIn("tests/test_lane_triage.py", timings)

    def test_the_launcher_floor_names_no_lane_triage(self):
        # The launcher test runs only under the installed-skill gate; this suite reads its source.
        tree = ast.parse((REPO_ROOT / "tests/test_agent_tools_launchers.py").read_text())
        (floor,) = [node.value for node in tree.body
                    if isinstance(node, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == "LAUNCHER_FLOOR"
                            for t in node.targets)]
        self.assertNotIn("lane-triage", ast.literal_eval(floor))

    def test_only_the_resolver_names_the_light_lane_binding(self):
        named = []
        for path in PACKAGE.rglob("*"):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            if "light_lane" in text:
                named.append(str(path.relative_to(REPO_ROOT)))
        self.assertEqual(sorted(named), ["python/agent_tools/project_contract/resolve_project.py",
                          "python/agent_tools/project_contract/schema_three.py"])


if __name__ == "__main__":
    unittest.main()
