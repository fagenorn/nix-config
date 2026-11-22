"""Contract tests for the locked form of the committed conformance workflow.

Outside the platform's own tree the resolver renders the workflow from the revision `devenv.lock`
pins (ADR-project-contract-018). The cases live beside `test_resolve_project.py` because that file
is over its size limit and may not grow; the case base and fixtures are imported from it.
"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from agent_tools.guard import contract_export
from agent_tools.project_contract import resolve_project

from .locked_workflow_fixture import EXPECTED_LOCKED_WORKFLOW, PLATFORM_MARKER
from .test_resolve_project import (
    EXPECTED_WORKFLOW,
    MANIFEST,
    REPO_ROOT,
    WORKFLOW_TARGET,
    ResolverTestCase,
    git,
    run,
    source_contract,
    with_workflow_entry,
)

TIER = "integration"  # the sparse-export case reads git history


class LockedConformanceWorkflowTest(ResolverTestCase):
    """The locked render, the platform marker that selects it and its sparse export."""

    def run_in(self, command: str, root: Path) -> tuple[int, object, str]:
        code, out, err = run(command, "--repo-root", str(root), home=self.home)
        try:
            payload: object = json.loads(out)
        except json.JSONDecodeError:
            payload = None
        return code, payload, err

    def workflow_root(self) -> Path:
        return self.make_root(with_workflow_entry(source_contract()))

    def test_this_repository_renders_its_own_tree_form(self):
        self.assertIs(resolve_project.conformance_workflow_locked(REPO_ROOT), False)

    def test_the_locked_render_reads_the_platform_revision_from_the_lock(self):
        render = resolve_project.render_conformance_workflow
        self.assertEqual(render("main", 2, locked=True),
                         EXPECTED_LOCKED_WORKFLOW.encode())
        self.assertEqual(
            render("trunk", 3, locked=True),
            EXPECTED_LOCKED_WORKFLOW.replace('- "main"', '- "trunk"')
            .replace("project schema 2", "project schema 3").encode())
        with self.assertRaises(ValueError):
            render("main: x", 2, locked=True)

    def test_the_locked_flag_is_required_and_keyword_only(self):
        with self.assertRaises(TypeError):
            resolve_project.render_conformance_workflow("main", 2)
        with self.assertRaises(TypeError):
            resolve_project.render_conformance_workflow("main", 2, True)

    def test_the_form_follows_the_platform_marker_even_when_it_dangles(self):
        root = self.workflow_root()
        self.assertTrue(resolve_project.conformance_workflow_locked(root))
        marker = root / PLATFORM_MARKER
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.symlink_to(root / "missing-manifest.json")
        self.assertFalse(resolve_project.conformance_workflow_locked(root))

    def test_write_projections_writes_the_locked_form_outside_the_platform_tree(self):
        root = self.workflow_root()
        self.assertFalse((root / PLATFORM_MARKER).exists())
        code, _, err = self.run_in("write-projections", root)
        self.assertEqual(code, 0, err)
        self.assertEqual((root / WORKFLOW_TARGET).read_bytes(),
                         EXPECTED_LOCKED_WORKFLOW.encode())

    def test_write_projections_writes_the_own_tree_form_in_the_platform_tree(self):
        root = self.workflow_root()
        marker = root / PLATFORM_MARKER
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_bytes(MANIFEST.read_bytes())
        code, _, err = self.run_in("write-projections", root)
        self.assertEqual(code, 0, err)
        self.assertEqual((root / WORKFLOW_TARGET).read_bytes(),
                         EXPECTED_WORKFLOW.encode())

    def test_projection_paths_lists_the_platform_marker_when_a_workflow_is_declared(self):
        declared = resolve_project.projection_paths(
            with_workflow_entry(source_contract()))
        self.assertEqual(declared[-1], PLATFORM_MARKER)
        self.assertEqual(declared.count(PLATFORM_MARKER), 1)
        self.assertNotIn(PLATFORM_MARKER,
                         resolve_project.projection_paths(source_contract()))

    def test_a_sparse_export_judges_the_workflow_as_the_checkout_does(self):
        for label, marker, rendered in (
                ("platform tree", True, EXPECTED_WORKFLOW),
                ("other tree", False, EXPECTED_LOCKED_WORKFLOW)):
            with self.subTest(tree=label):
                root = self.workflow_root()
                if marker:
                    path = root / PLATFORM_MARKER
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(MANIFEST.read_bytes())
                target = root / WORKFLOW_TARGET
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(rendered.encode())
                git(root, "add", "-A")
                git(root, "commit", "--quiet", "-m", "fixture")
                commit = git(root, "rev-parse", "HEAD").strip()
                export = Path(tempfile.mkdtemp()).resolve() / "export"
                contract_export.export_contract(root, commit, export)
                self.assertEqual((export / PLATFORM_MARKER).exists(), marker)
                self.assertEqual(
                    self.run_in("check-projections", root)[0], 0)
                code, _, err = self.run_in("check-projections", export)
                self.assertEqual(code, 0, err)


if __name__ == "__main__":
    unittest.main()
