"""The schema-3 resolver cases, beside `test_resolve_project.py`, whose helpers it imports.

A schema-3 contract authors only what the platform cannot decide. The resolver
fills the constants in and resolves the result as schema 2 without the four
retired members, so these cases pin that the filled snapshot answers every
member the delivery programs and skills read, and that it agrees with the
schema-2 contract that spells every constant out.
"""

from __future__ import annotations

import copy
import json
import os
import re
import shutil
import unittest
from pathlib import Path
from unittest import mock

from agent_tools.project_contract import resolve_project, schema_three
from agent_tools.release import release

from .test_resolve_project import (
    REPO_ROOT,
    ResolverTestCase,
    make_project_root,
    run,
    source_contract,
)

TIER = "fast"

SCHEMA_THREE_FIXTURE = (
    Path(__file__).resolve().parent / "fixtures" / "project-contract-schema-3.json")

EXPECTED_CONSTANTS = {
    "/bindings/vcs/kind": "git",
    "/bindings/vcs/default_branch": "main",
    "/bindings/vcs/branch_pattern": "issue-<num>-<slug>",
    "/bindings/vcs/worktree/root": ".worktrees",
    "/bindings/vcs/worktree/prefix": "worktree-",
    "/bindings/vcs/commit/signed": True,
    "/bindings/vcs/commit/environment": "commit-environment",
    "/bindings/vcs/merge/strategy": "merge",
    "/bindings/vcs/merge/delete_branch": True,
    "/bindings/tracker/kind": "github",
    "/bindings/tracker/cli": "gh",
    "/bindings/tracker/credential_env/unset_before_invocation": ["GITHUB_TOKEN", "GH_TOKEN"],
    "/bindings/paths/context": ["docs/CONTEXT-MAP.md"],
    "/bindings/paths/standards": ["docs/standards"],
    "/bindings/paths/architecture": ["docs/guides/architecture.md"],
    "/bindings/paths/operations": ["docs/operations"],
    "/bindings/paths/hints": [".agents/knowledge/hints"],
    "/bindings/paths/rejections": [".agents/knowledge/rejections"],
    "/bindings/workflow/verification": ["lint", "test"],
    "/bindings/workflow/review/plan": "codex-plan-review",
    "/bindings/workflow/review/code": "codex-diff-review",
    "/bindings/workflow/orchestration/max_parallel": 2,
    "/bindings/workflow/orchestration/attempt_budget_minutes": 240,
}

RETIRED_PATHS = (
    "project.name",
    "bindings.paths.artifacts",
    "bindings.vcs.commit.co_authored_by",
    "bindings.workflow.light_lane",
)

PROGRAM_SOURCES = (
    REPO_ROOT / "home/common/claude-code/skills/deliver-standard/deliver-standard.js",
    REPO_ROOT / "home/common/claude-code/skills/deliver-standard/deliver-batch.js",
)
SKILL_ROOTS = (
    REPO_ROOT / "home/common/agent-skills/skills",
    REPO_ROOT / "home/common/claude-code/skills",
)
MEMBER_PATH = re.compile(
    r"(?<![\w./-])(project|bindings|capabilities)((?:\.[A-Za-z_][A-Za-z0-9_]*)+)")

ISSUE_READS = {
    "project.root",
    "bindings.tracker.repo_slug",
    "bindings.tracker.credential_env.unset_before_invocation",
    "bindings.vcs.integration_branch",
    "bindings.vcs.default_branch",
    "bindings.vcs.merge.strategy",
    "bindings.vcs.merge.delete_branch",
    "bindings.vcs.merge.required_checks",
    "bindings.vcs.worktree.root",
    "bindings.vcs.worktree.prefix",
    "bindings.workflow.orchestration.max_parallel",
    "bindings.workflow.review.plan",
    "bindings.workflow.review.code",
    "capabilities.review.plan",
    "capabilities.review.code",
    "bindings.paths.standards",
    "bindings.paths.hints",
    "bindings.paths.rejections",
    "bindings.workflow.verification",
    "bindings.workflow.verification_conditions",
    "bindings.commands",
}


def schema_three_contract() -> dict:
    return json.loads(SCHEMA_THREE_FIXTURE.read_text("utf-8"))


def make_schema_three_root(contract: object, *, projections: bool = True) -> Path:
    """A project root whose knowledge homes exist, so every authored capability is judged ready."""
    root = make_project_root(contract, projections=projections)
    (root / "docs" / "guides").mkdir(parents=True)
    (root / "docs" / "CONTEXT-MAP.md").write_text("# map\n", encoding="utf-8")
    (root / "docs" / "guides" / "architecture.md").write_text("# arch\n", encoding="utf-8")
    (root / "docs" / "operations").mkdir()
    (root / ".agents" / "knowledge" / "hints").mkdir(parents=True)
    (root / ".agents" / "knowledge" / "rejections").mkdir(parents=True)
    return root


def named_member_paths() -> dict[str, list[str]]:
    """Each member path the programs and skills name, mapped to the files naming it."""
    files = list(PROGRAM_SOURCES)
    for top in SKILL_ROOTS:
        files.extend(p for p in sorted(top.rglob("*.md")) if p.name != "CHANGELOG.md")
    found: dict[str, list[str]] = {}
    for path in files:
        text = path.read_text(encoding="utf-8")
        for match in MEMBER_PATH.finditer(text):
            member = match.group(1) + match.group(2)
            named = found.setdefault(member, [])
            relative = path.relative_to(REPO_ROOT).as_posix()
            if relative not in named:
                named.append(relative)
    return found


def values_at(snapshot: dict, path: str) -> list | None:
    """The values a dotted member path reaches in a snapshot, or None when it reaches nothing."""
    keys = path.split(".")
    if keys[0] == "capabilities":
        wanted = ".".join(keys[1:])
        capabilities = snapshot.get("capabilities", {})
        picked = [value for name, value in capabilities.items()
                  if name == wanted or name.startswith(wanted + ".")]
        return picked or None
    value: object = snapshot
    for key in keys:
        if not isinstance(value, dict) or key not in value:
            return None
        value = value[key]
    return [value]


def without_retired(snapshot: dict) -> dict:
    out = copy.deepcopy(snapshot)
    for path in RETIRED_PATHS:
        *parents, last = path.split(".")
        node: object = out
        for key in parents:
            node = node.get(key) if isinstance(node, dict) else None
        if isinstance(node, dict):
            node.pop(last, None)
    return out


def set_pointer(document: dict, pointer: str, value: object) -> None:
    *parents, last = pointer.split("/")[1:]
    node = document
    for key in parents:
        node = node.setdefault(key, {})
    node[last] = copy.deepcopy(value)


def schema_two_equivalent(contract: dict) -> dict:
    """The schema-2 contract that spells out every constant the schema-3 contract leaves to the platform."""
    out = copy.deepcopy(contract)
    out["schema_version"] = 2
    out["project"]["name"] = "nix-config"
    for pointer, value in EXPECTED_CONSTANTS.items():
        set_pointer(out, pointer, value)
    commands = out["bindings"]["commands"]
    for entry in commands.values():
        entry["cwd"] = "."
        entry["env"] = []
    commands["commit-environment"] = {"argv": ["devenv", "shell", "--"], "cwd": ".", "env": []}
    out["bindings"]["paths"]["artifacts"] = {
        "specs": ".agents/artifacts/specs", "plans": ".agents/artifacts/plans"}
    out["bindings"]["vcs"]["commit"]["co_authored_by"] = False
    return out


class SchemaThreeCase(ResolverTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)

    def owned(self, path: Path) -> Path:
        self.addCleanup(shutil.rmtree, path, ignore_errors=True)
        return path

    def schema_three_root(self, contract: object, *, projections: bool = True) -> Path:
        return self.owned(make_schema_three_root(contract, projections=projections))


class ProgramReadsTest(SchemaThreeCase):
    def test_a_schema_three_snapshot_answers_every_member_the_programs_and_skills_name(self):
        reads = named_member_paths()
        root = self.schema_three_root(schema_three_contract())
        code, snap, err = self.resolve(root)
        self.assertEqual(code, 0, err)
        self.assertLessEqual(
            {"project.root", "bindings.tracker.repo_slug", "bindings.vcs.merge.required_checks",
             "bindings.paths", "bindings.vcs"}, set(reads))
        for path in sorted(set(reads) | ISSUE_READS):
            with self.subTest(path=path):
                self.assertIsNotNone(values_at(snap, path), reads.get(path, "the issue"))

    def test_every_constant_is_filled(self):
        root = self.schema_three_root(schema_three_contract())
        code, snap, err = self.resolve(root)
        self.assertEqual(code, 0, err)
        for pointer, expected in EXPECTED_CONSTANTS.items():
            with self.subTest(pointer=pointer):
                node: object = snap
                for key in pointer.split("/")[1:]:
                    node = node[key]
                if pointer.startswith("/bindings/paths/"):
                    expected = [f"{root}/{entry}" for entry in expected]
                self.assertEqual(node, expected)
        commands = snap["bindings"]["commands"]
        self.assertEqual(
            commands["lint"], {"argv": ["just", "lint"], "cwd": str(root), "env": []})
        self.assertEqual(
            commands["commit-environment"],
            {"argv": ["devenv", "shell", "--"], "cwd": str(root), "env": []})

    def test_it_agrees_with_its_schema_two_equivalent_on_every_member_the_programs_read(self):
        root3 = self.schema_three_root(schema_three_contract())
        root2 = self.schema_three_root(schema_two_equivalent(schema_three_contract()))
        code3, snap3, err3 = self.resolve(root3)
        code2, snap2, err2 = self.resolve(root2)
        self.assertEqual(code3, 0, err3)
        self.assertEqual(code2, 0, err2)
        self.assertIn("artifacts", snap2["bindings"]["paths"])
        self.assertIn("co_authored_by", snap2["bindings"]["vcs"]["commit"])
        kept2 = without_retired(snap2)

        def spelled(values: list, root: Path) -> str:
            return json.dumps(values, sort_keys=True).replace(str(root), "<root>")

        for path in sorted(set(named_member_paths()) | ISSUE_READS):
            with self.subTest(path=path):
                got3, got2 = values_at(snap3, path), values_at(kept2, path)
                self.assertIsNotNone(got3)
                self.assertIsNotNone(got2)
                self.assertEqual(spelled(got3, root3), spelled(got2, root2))

    def test_absent_optional_homes_are_still_filled(self):
        root = self.schema_three_root(schema_three_contract())
        (root / "docs/guides/architecture.md").unlink()
        shutil.rmtree(root / "docs/operations")
        code, snap, err = self.resolve(root)
        self.assertEqual(code, 0, err)
        paths = snap["bindings"]["paths"]
        self.assertEqual(paths["architecture"], [f"{root}/docs/guides/architecture.md"])
        self.assertEqual(paths["operations"], [f"{root}/docs/operations"])
        self.assertEqual(snap["capabilities"]["knowledge.architecture"]["state"], "blocked")


class ReleaseReadsTest(SchemaThreeCase):
    """The release core reads the filled view, never the authored schema-3 source."""

    def test_the_release_driver_builds_its_router_from_a_schema_three_contract(self):
        root = self.schema_three_root(schema_three_contract())
        code, snapshot, err = self.resolve(root)
        self.assertEqual(code, 0, err)
        with mock.patch.dict(os.environ, {"HOME": str(self.home)}):
            project = release._project(snapshot, root)
            driver = release.Driver(project, profile_id=None, approvals=lambda *_: True)
            driver._router()

    def test_the_view_reader_fills_the_constants_the_release_core_reads(self):
        root = self.schema_three_root(schema_three_contract())
        view = resolve_project.load_contract_view(root)
        bindings = view["bindings"]
        self.assertEqual(
            bindings["tracker"]["credential_env"]["unset_before_invocation"],
            ["GITHUB_TOKEN", "GH_TOKEN"])
        self.assertEqual(bindings["tracker"]["kind"], "github")
        self.assertEqual(bindings["vcs"]["default_branch"], "main")
        self.assertEqual(view["schema_version"], 3)

    def test_the_view_reader_returns_a_schema_two_contract_unchanged(self):
        root = self.schema_three_root(source_contract())
        self.assertEqual(resolve_project.load_contract_view(root),
                         resolve_project.load_contract(root))


class SchemaThreeFillTest(unittest.TestCase):
    def test_fill_leaves_its_input_unchanged(self):
        source = schema_three_contract()
        source["bindings"]["commands"]["codex-plan-review"] = {"argv": ["true"]}
        before = copy.deepcopy(source)
        view = schema_three.fill(source)
        self.assertEqual(source, before)
        self.assertNotIn("codex-plan-review", view["bindings"]["commands"])
        self.assertNotIn("paths", source["bindings"])

    def test_fill_drops_a_retired_member_a_contract_still_carries(self):
        source = schema_three_contract()
        source["project"]["name"] = "nix-config"
        source["bindings"]["vcs"]["commit"] = {"co_authored_by": True}
        source["bindings"]["workflow"]["light_lane"] = {"mode": "shadow"}
        view = schema_three.fill(source)
        self.assertEqual(sorted(view["project"]), ["id"])
        self.assertEqual(sorted(view["bindings"]["vcs"]["commit"]), ["environment", "signed"])
        self.assertNotIn("light_lane", view["bindings"]["workflow"])


class SnapshotRetirementTest(SchemaThreeCase):
    def test_a_schema_three_snapshot_is_resolved_schema_two_without_retired_members(self):
        root = self.schema_three_root(schema_three_contract())
        code, snap, err = self.resolve(root)
        self.assertEqual(code, 0, err)
        self.assertEqual(snap["schema_version"], 2)
        self.assertEqual(sorted(snap["project"]), ["id", "root"])
        self.assertNotIn("artifacts", snap["bindings"]["paths"])
        self.assertEqual(sorted(snap["bindings"]["vcs"]["commit"]), ["environment", "signed"])
        self.assertNotIn("light_lane", snap["bindings"]["workflow"])

    def test_the_projection_header_records_schema_three(self):
        root = self.schema_three_root(schema_three_contract(), projections=False)
        code, out, err = run("write-projections", "--repo-root", str(root), home=self.home)
        self.assertEqual(code, 0, err)
        agents = root / "AGENTS.md"
        self.assertTrue(agents.exists())
        self.assertIn("(project schema 3)", agents.read_text("utf-8"))
        code, out, err = run("check-projections", "--repo-root", str(root), home=self.home)
        self.assertEqual(code, 0, err)

    def test_authored_members_keep_their_schema_two_rules(self):
        def delete(path):
            def mutate(contract):
                node = contract
                *parents, last = path
                for key in parents:
                    node = node[key]
                del node[last]
            return mutate

        def assign(path, value):
            def mutate(contract):
                node = contract
                *parents, last = path
                for key in parents:
                    node = node[key]
                node[last] = value
            return mutate

        cases = [
            ("integration_branch", delete(["bindings", "vcs", "integration_branch"]),
             ["/bindings/vcs/integration_branch"], "contract.vcs.member_missing"),
            ("repo_slug", delete(["bindings", "tracker", "repo_slug"]),
             ["/bindings/tracker/repo_slug"], "contract.tracker.member_missing"),
            ("empty argv", assign(["bindings", "commands", "lint", "argv"], []),
             ["/bindings/commands/lint/argv"], "contract.commands.empty_argv"),
            ("vcs extra", assign(["bindings", "vcs", "extra"], "x"),
             ["/bindings/vcs/extra"], "contract.vcs.member_unexpected"),
            ("verification condition",
             assign(["bindings", "workflow", "verification_conditions"],
                    {"nix-build": {"pre_commit": True}}),
             ["/bindings/workflow/verification_conditions/nix-build"],
             "contract.workflow.unknown_verification_id"),
            ("bindings not an object", assign(["bindings"], []), ["/bindings"], None),
            ("vcs not an object", assign(["bindings", "vcs"], []), ["/bindings/vcs"], None),
        ]
        for label, mutate, pointers, repair_id in cases:
            with self.subTest(label):
                contract = schema_three_contract()
                mutate(contract)
                root = self.schema_three_root(contract)
                code, payload, _ = self.resolve(root)
                error = self.assert_refusal(code, payload, "invalid_contract")
                self.assertEqual([v["pointer"] for v in error["violations"]], pointers)
                if repair_id is not None:
                    self.assertEqual(error["repair_id"], repair_id)


if __name__ == "__main__":
    unittest.main()
