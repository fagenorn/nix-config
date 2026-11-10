"""The agent_tools layout rule: subpackages are the docs areas, imports follow one table."""

import ast
import tempfile
import unittest
from collections.abc import Mapping
from pathlib import Path

from agent_tools import instruction_load

REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE = REPO_ROOT / "python/agent_tools"
AREAS_DIR = REPO_ROOT / "docs/areas"
SHARED = "system"

# Importing area -> dotted modules of other areas it may import. Adding an edge
# is a reviewed change to this table.
ALLOWED_IMPORTS: dict[str, frozenset[str]] = {
    "claims": frozenset({"agent_tools.project_contract.agent_platform"}),
    "guard": frozenset({
        "agent_tools.project_contract.adopt_inspection",
        "agent_tools.project_contract.adopt_verify",
        "agent_tools.project_contract.agent_platform",
        "agent_tools.project_contract.resolve_project",
    }),
}

# Flat modules that have not moved into their area yet; each move removes a name.
UNMOVED: frozenset[str] = frozenset({
    "actions_health_adapter", "agent_gate_bundle", "agent_gate_corpus", "agnostic_lint",
    "artifact_budget", "cache_keepalive", "cache_proxy", "codesigned_artifact_adapter",
    "context_map_lint", "diff_scope", "forge_adapter", "host_admission", "issue_branch",
    "keepalive_pings", "lane_triage", "launchd_agent_adapter", "model_pricing",
    "promotion", "promotion_lifecycle", "promotion_schema", "railway_deploy_adapter",
    "release", "release_adapter", "release_cutover", "release_driver", "release_merge",
    "release_profile", "release_verification", "run_profile", "subagent_prefix",
    "suite_runner", "transaction_core", "transaction_custody",
    "transaction_disposition", "transaction_history", "transaction_invocation",
    "transaction_plan", "transaction_proof", "transaction_receipt",
    "transaction_recovery", "transaction_recovery_plan", "transaction_storage",
    "verified_tree", "verify_block", "verify_checks", "verify_exec", "verify_facts",
    "verify_issues", "verify_owner", "verify_pending", "verify_run", "worktree_forge",
})


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


def gate_modules(root: Path) -> frozenset[str]:
    """The flat gate-file modules and every flat module they import."""
    prefix, suffix = "python/agent_tools/", ".py"
    pending = [path[len(prefix):-len(suffix)] for path in instruction_load.GATE_FILES
               if path.startswith(prefix) and path.endswith(suffix)
               and "/" not in path[len(prefix):-len(suffix)]]
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


def _structure(root: Path, areas, flat_allowed, unmoved) -> list[str]:
    found = []
    flat = {path.stem for path in root.glob("*.py")}
    for stem in sorted(flat - flat_allowed - unmoved):
        found.append(f"flat module agent_tools.{stem} is not allowed at the top level")
    for name in sorted(unmoved - flat):
        found.append(f"unmoved module agent_tools.{name} is no longer flat")
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


def _import_violations(root, areas, allowed, unmoved) -> list[str]:
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
        if importer_area is None and parts and parts[0] in unmoved:
            continue
        for line, level, module, names in _imports(ast.parse(path.read_text("utf-8"))):
            if level:
                found.append(f"{importer}:{line} uses a relative import")
                continue
            for target in _targets(root, module, names):
                target_parts = target.split(".")
                if len(target_parts) == 1:
                    continue
                if area_of(target_parts) is None and target_parts[1] in unmoved:
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
                      flat_allowed: frozenset[str], unmoved: frozenset[str]) -> list[str]:
    """Sorted layout messages for an agent_tools package directory; [] when clean."""
    return sorted(_structure(root, areas, flat_allowed, unmoved)
                  + _import_violations(root, areas, allowed, unmoved))


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

    def violations(self, files, *, allowed=None, unmoved=frozenset()):
        return layout_violations(
            self.tree(files),
            areas=frozenset({"alpha", "beta", "system"}),
            allowed=DEFAULT_ALLOWED if allowed is None else allowed,
            flat_allowed=frozenset({"__init__", "canonical"}),
            unmoved=unmoved)

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

    def test_an_unmoved_module_is_exempt_until_it_moves(self):
        files = {**BASE, "stray.py": "from agent_tools.alpha import b\n"}
        self.assertEqual(self.violations(files, unmoved=frozenset({"stray"})), [])
        self.assertEqual(self.violations(files, unmoved=frozenset({"stray", "gone"})),
                         ["unmoved module agent_tools.gone is no longer flat"])

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
    def test_the_flat_allowance_is_the_instruction_budget_gate_closure(self):
        self.assertEqual(
            gate_modules(PACKAGE),
            frozenset({"instruction_load", "skill_lint", "agent_model_matrix", "canonical"}))

    def test_the_package_follows_the_layout_rule(self):
        self.assertEqual(
            layout_violations(PACKAGE, areas=area_packages(AREAS_DIR),
                              allowed=ALLOWED_IMPORTS,
                              flat_allowed=gate_modules(PACKAGE) | {"__init__"},
                              unmoved=UNMOVED), [])

    def test_the_areas_are_the_docs_areas(self):
        self.assertEqual(
            area_packages(AREAS_DIR),
            frozenset({"claims", "delivery", "guard", "hosts", "project_contract",
                       "release", "system", "verification"}))


if __name__ == "__main__":
    unittest.main()
