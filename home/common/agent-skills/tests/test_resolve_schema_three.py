"""The schema-3 resolver cases, beside `test_resolve_project.py`, whose helpers it imports.

A schema-3 contract authors only what the platform cannot decide. The resolver
fills the constants in and resolves the result as schema 2 without the four
retired members, so these cases pin that the filled snapshot answers every
member the delivery programs and skills read, and that it agrees with the
schema-2 contract that spells every constant out.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
import re
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from agent_tools.guard import contract_export
from agent_tools.project_contract import (
    adopt_inspection,
    attempt_history,
    derived_values,
    resolve_project,
    schema_three,
)
from agent_tools.project_contract.derived_values import TREE_MANIFEST
from agent_tools.release import release

from .test_resolve_project import (
    MANIFEST,
    REPO_ROOT,
    InProcessTestCase,
    ResolverTestCase,
    committed_manifest,
    git,
    make_project_root,
    mutated_manifest,
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

INDEXED_READ = re.compile(
    r"(?<![\w./-])(bindings\.commands)\[([a-z_]+)\]((?:\.[A-Za-z_][A-Za-z0-9_]*)+)")

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
    "bindings.workflow.verification_before_pull_request",
    "bindings.commands",
}


def schema_three_contract() -> dict:
    return json.loads(SCHEMA_THREE_FIXTURE.read_text("utf-8"))


FIXTURE_REMOTE = "git@github.com:fagenorn/nix-config.git"
FIXTURE_PROTECTION = {"required_status_checks": {
    "strict": True, "checks": [{"context": "Nix Eval"}, {"context": "Agent Workflow Tests"}]}}


def _next_major(version: str) -> str:
    return f"{int(version.split('.')[0]) + 1}.0.0"


def _next_minor(version: str) -> str:
    major, minor, _ = version.split(".")
    return f"{major}.{int(minor) + 1}.0"


EXPECTED_DERIVED = {
    "/project/id": "fagenorn/nix-config",
    "/bindings/tracker/repo_slug": "fagenorn/nix-config",
    "/bindings/vcs/merge/required_checks": ["Nix Eval", "Agent Workflow Tests"],
    "/platform": {
        "min_inclusive": committed_manifest()["platform_version"],
        "max_exclusive": _next_major(committed_manifest()["platform_version"])},
    "/bindings/workflow/orchestration/attempt_budget_minutes": 240,
}


def make_schema_three_root(contract: object, *, projections: bool = True,
                           remote: str | None = FIXTURE_REMOTE,
                           protection: object = FIXTURE_PROTECTION,
                           tree_manifest: bool = True) -> Path:
    """A project root whose knowledge homes exist, so every authored capability is judged ready.

    It also holds what a schema-3 contract's four derived values come from: an
    origin remote, the branch-protection source and, as the platform's own
    repository does, the platform manifest.
    """
    root = make_project_root(contract, projections=projections)
    if remote is not None:
        git(root, "remote", "add", "origin", remote)
    if protection is not None:
        (root / ".github").mkdir()
        (root / ".github" / "branch-protection.json").write_text(
            json.dumps(protection), encoding="utf-8")
    if tree_manifest:
        (root / TREE_MANIFEST).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(MANIFEST, root / TREE_MANIFEST)
    (root / "docs" / "guides").mkdir(parents=True)
    (root / "docs" / "CONTEXT-MAP.md").write_text("# map\n", encoding="utf-8")
    (root / "docs" / "guides" / "architecture.md").write_text("# arch\n", encoding="utf-8")
    (root / "docs" / "operations").mkdir()
    (root / ".agents" / "knowledge" / "hints").mkdir(parents=True)
    (root / ".agents" / "knowledge" / "rejections").mkdir(parents=True)
    return root


def stage_locked_platform(root: Path, store: Path, version: str) -> None:
    """Pin the `agent-platform` input in `root`'s `devenv.lock` and put its tree in `store`."""
    nar = "sha256-" + base64.b64encode(hashlib.sha256(version.encode()).digest()).decode()
    (root / "devenv.lock").write_text(json.dumps({
        "nodes": {"root": {"inputs": {"agent-platform": "agent-platform_2"}},
                  "agent-platform_2": {"locked": {"narHash": nar}}},
        "root": "root", "version": 7}), encoding="utf-8")
    manifest = Path(derived_values.store_path(nar, str(store))) / TREE_MANIFEST
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps({"platform_version": version}), encoding="utf-8")


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


def indexed_reads() -> set[tuple[str, str, str]]:
    """Each (container, index name, member path) a skill reads as `container[index].member`."""
    found: set[tuple[str, str, str]] = set()
    for top in SKILL_ROOTS:
        for path in sorted(top.rglob("*.md")):
            if path.name == "CHANGELOG.md":
                continue
            for match in INDEXED_READ.finditer(path.read_text(encoding="utf-8")):
                found.add((match.group(1), match.group(2), match.group(3)[1:]))
    return found


def indexed_read_misses(snapshot: dict, reads: set[tuple[str, str, str]]) -> list[str]:
    """The indexed reads a snapshot does not answer, for each command a skill's index name selects."""
    review = snapshot["bindings"]["workflow"]["review"]
    selected = {"review_id": [review["plan"], review["code"]]}
    misses = []
    for container, index, member in sorted(reads):
        for command_id in selected.get(index, [None]):
            node = values_at(snapshot, container)[0] if command_id else None
            node = node.get(command_id) if isinstance(node, dict) else None
            for key in member.split("."):
                node = node.get(key, None) if isinstance(node, dict) else None
            if node is None:
                misses.append(f"{container}[{command_id or index}].{member}")
    return misses


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
    set_pointer(out, "/project/name", "nix-config")
    for pointer, value in EXPECTED_DERIVED.items():
        set_pointer(out, pointer, value)
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

    def schema_three_root(self, contract: object, **sources: object) -> Path:
        return self.owned(make_schema_three_root(contract, **sources))


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

    def test_a_schema_three_snapshot_answers_every_indexed_command_read(self):
        reads = indexed_reads()
        self.assertIn(("bindings.commands", "review_id", "argv"), reads)
        root = self.schema_three_root(schema_three_contract())
        code, snap, err = self.resolve(root)
        self.assertEqual(code, 0, err)
        self.assertEqual(indexed_read_misses(snap, reads), [])

    def test_an_indexed_read_of_an_absent_member_is_a_miss(self):
        root = self.schema_three_root(schema_three_contract())
        code, snap, err = self.resolve(root)
        self.assertEqual(code, 0, err)
        misses = indexed_read_misses(
            snap, {("bindings.commands", "review_id", "nonexistent")})
        self.assertEqual(misses, ["bindings.commands[codex-plan-review].nonexistent",
                                  "bindings.commands[codex-diff-review].nonexistent"])

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


class ExportedSourceTest(SchemaThreeCase):
    """The resolver also runs on scratch exports of a pinned commit (ADR-project-contract-014).

    The guard-policy proof resolves the sparse export `contract_export` writes, and adoption's
    verification a `git archive` export. Neither holds a git config, so each is given the
    checkout's `origin` url (`adopt_inspection.seed_origin`).
    """

    def committed(self) -> tuple[Path, str]:
        root = self.schema_three_root(schema_three_contract())
        git(root, "add", "-A")
        git(root, "commit", "--quiet", "-m", "fixture")
        return root, git(root, "rev-parse", "HEAD").strip()

    def exports(self, root: Path, commit: str) -> dict[str, Path]:
        base = self.owned(Path(tempfile.mkdtemp()))
        contract_export.export_contract(root, commit, base / "sparse")
        adopt_inspection.export_commit(root, commit, base / "archive")
        return {"the guard's sparse export": base / "sparse",
                "a git archive export": base / "archive"}

    def resolve_in_process(self, path: Path) -> dict:
        with mock.patch.dict(os.environ, {"HOME": str(self.home)}):
            return resolve_project.resolve(str(path))

    def test_an_export_given_the_origin_resolves_the_derived_values(self):
        root, commit = self.committed()
        for name, export in self.exports(root, commit).items():
            with self.subTest(name):
                adopt_inspection.seed_origin(root, export)
                snapshot = self.resolve_in_process(export)
                self.assertEqual(snapshot["project"]["id"], "fagenorn/nix-config")
                self.assertEqual(snapshot["bindings"]["tracker"]["repo_slug"],
                                 "fagenorn/nix-config")
                self.assertEqual(snapshot["bindings"]["vcs"]["merge"]["required_checks"],
                                 EXPECTED_DERIVED["/bindings/vcs/merge/required_checks"])

    def test_an_export_without_the_origin_is_refused_as_not_derivable(self):
        root, commit = self.committed()
        for name, export in self.exports(root, commit).items():
            with self.subTest(name):
                with self.assertRaises(resolve_project.ContractError) as raised:
                    self.resolve_in_process(export)
                self.assertEqual(raised.exception.code, "invalid_contract")
                self.assertEqual(
                    [v["pointer"] for v in raised.exception.violations],
                    ["/bindings/tracker/repo_slug", "/project/id"])

    def test_the_sparse_export_carries_the_files_the_derivation_reads(self):
        root, commit = self.committed()
        sparse = self.exports(root, commit)["the guard's sparse export"]
        for path in (derived_values.PROTECTION_SOURCE, derived_values.TREE_MANIFEST):
            self.assertEqual((sparse / path).read_bytes(),
                             adopt_inspection.blob_at(root, commit, path))
        self.assertFalse((sparse / derived_values.LOCK_SOURCE).exists())

    def test_the_sparse_export_of_a_schema_two_contract_carries_only_the_contract_files(self):
        root = self.schema_three_root(source_contract())
        git(root, "add", "-A")
        git(root, "commit", "--quiet", "-m", "fixture")
        sparse = self.owned(Path(tempfile.mkdtemp())) / "sparse"
        contract_export.export_contract(root, git(root, "rev-parse", "HEAD").strip(), sparse)
        self.assertFalse((sparse / derived_values.PROTECTION_SOURCE).exists())
        self.assertFalse((sparse / derived_values.TREE_MANIFEST).exists())

    def test_the_seeded_origin_is_left_out_when_it_cannot_be_written_plainly(self):
        root, _ = self.committed()
        cases = ("git@github.com:o/r.git # note", 'git@github.com:o/"r".git',
                 "git@github.com:o/r.git;x", "git@github.com:o/r.git\t# note", None)
        for url in cases:
            with self.subTest(url=url):
                if url is None:
                    git(root, "remote", "remove", "origin")
                else:
                    git(root, "config", "remote.origin.url", url)
                destination = self.owned(Path(tempfile.mkdtemp()))
                adopt_inspection.seed_origin(root, destination)
                self.assertFalse((destination / ".git").exists())


class SchemaThreeAuthoredTest(unittest.TestCase):
    """`schema_three.authored` is the question `refusals` answers: may a contract author this member."""

    @staticmethod
    def leaves(node: object, prefix: str = "") -> list[str]:
        if not isinstance(node, dict):
            return [prefix]
        return [leaf for key, child in node.items()
                for leaf in SchemaThreeAuthoredTest.leaves(child, f"{prefix}/{key}")]

    def test_the_authored_members_are_neither_constant_derived_nor_retired(self):
        owned = (*schema_three.CONSTANTS, *schema_three.DERIVED, *schema_three.RETIRED,
                 *schema_three.CONSTANT_CONTAINERS, *schema_three.DERIVED_CONTAINERS)
        for member in schema_three.AUTHORED:
            for other in owned:
                self.assertFalse(
                    member == other or member.startswith(other + "/") or other.startswith(member + "/"),
                    (member, other))
        for leaf in self.leaves(schema_three_contract()):
            if leaf != "/schema_version":
                self.assertTrue(schema_three.authored(leaf), leaf)

    def test_a_platform_command_or_constant_member_is_not_authored(self):
        for pointer in ("/bindings/commands/lint", "/bindings/commands/lint/argv"):
            self.assertTrue(schema_three.authored(pointer), pointer)
        for pointer in ("/bindings/commands/commit-environment", "/bindings/commands/codex-plan-review",
                        "/bindings/commands/lint/cwd", "/bindings/commands/lint/env",
                        "/bindings/vcs/default_branch", "/project/id", "/bindings/workflow/light_lane"):
            self.assertFalse(schema_three.authored(pointer), pointer)
            contract = schema_three_contract()
            set_pointer(contract, pointer, {"argv": ["x"]} if "/commands/" in pointer else "x")
            self.assertIn(pointer, [v["pointer"] for v in schema_three.refusals(contract)])


class SchemaThreeFillTest(unittest.TestCase):
    def test_fill_leaves_its_input_unchanged(self):
        source = schema_three_contract()
        source["bindings"]["commands"]["codex-plan-review"] = {"argv": ["true"]}
        before = copy.deepcopy(source)
        view = schema_three.fill(source, EXPECTED_DERIVED)
        self.assertEqual(source, before)
        self.assertNotIn("codex-plan-review", view["bindings"]["commands"])
        self.assertNotIn("paths", source["bindings"])

    def test_fill_drops_a_retired_member_a_contract_still_carries(self):
        source = schema_three_contract()
        source["project"] = {"name": "nix-config"}
        source["bindings"]["vcs"]["commit"] = {"co_authored_by": True}
        source["bindings"]["workflow"]["light_lane"] = {"mode": "shadow"}
        view = schema_three.fill(source, {"/project/id": "fagenorn/nix-config"})
        self.assertEqual(view["project"], {"id": "fagenorn/nix-config"})
        self.assertEqual(sorted(view["bindings"]["vcs"]["commit"]), ["environment", "signed"])
        self.assertNotIn("light_lane", view["bindings"]["workflow"])


    def test_fill_drops_a_retired_member_when_bindings_is_not_an_object(self):
        source = schema_three_contract()
        source["project"] = {"name": "nix-config"}
        source["bindings"] = []
        view = schema_three.fill(source, {
            "/project/id": "fagenorn/nix-config", "/platform": EXPECTED_DERIVED["/platform"]})
        self.assertEqual(view["project"], {"id": "fagenorn/nix-config"})
        self.assertEqual(view["platform"], EXPECTED_DERIVED["/platform"])
        self.assertEqual(view["bindings"], [])

    def test_fill_keeps_no_authored_value_the_repository_could_not_state(self):
        source = schema_three_contract()
        source["project"] = {"id": "fagenorn/nix-config"}
        source["bindings"]["tracker"] = {"repo_slug": "fagenorn/nix-config"}
        source["bindings"]["vcs"]["merge"] = {"required_checks": ["Nix Eval"]}
        source["platform"] = {"min_inclusive": "1.0.0", "max_exclusive": "2.0.0"}
        view = schema_three.fill(source, {})
        self.assertNotIn("id", view["project"])
        self.assertNotIn("repo_slug", view["bindings"]["tracker"])
        self.assertNotIn("required_checks", view["bindings"]["vcs"]["merge"])
        self.assertNotIn("platform", view)
        with self.subTest("a derived value replaces the authored one"):
            view = schema_three.fill(source, {"/project/id": "o/r"})
            self.assertEqual(view["project"], {"id": "o/r"})

    def test_fill_with_nothing_derived_creates_no_top_level_member(self):
        source = schema_three_contract()
        self.assertEqual(sorted(schema_three.fill(source, {})), sorted(source))


class SchemaThreeRefusalTest(SchemaThreeCase):
    """A schema-3 contract that authors a constant or a retired member is refused by name."""

    @staticmethod
    def section(pointer: str) -> str:
        keys = pointer.split("/")[1:]
        return keys[0] if keys[0] in ("project", "platform") else keys[1]

    def refused_rows(self) -> list[tuple[str, str, object, str]]:
        """(label, pointer set, value, pointer refused) for each authored constant or retired member."""
        rows = [(f"constant {pointer}", pointer, value, pointer)
                for pointer, value in EXPECTED_CONSTANTS.items()]
        for pointer, value in EXPECTED_DERIVED.items():
            rows.append((f"derived {pointer}", pointer, value, pointer))
        rows.append(("derived basis", schema_three.ATTEMPT_BUDGET_BASIS,
                     {"source": "fallback", "reason": "no_history"},
                     schema_three.ATTEMPT_BUDGET_BASIS))
        rows.append(("empty /project", "/project", {}, "/project"))
        rows.append(("project not an object", "/project", "nix-config", "/project"))
        for container in schema_three.CONSTANT_CONTAINERS:
            rows.append((f"empty {container}", container, {}, container))
        rows.append(("paths not an object", "/bindings/paths", None, "/bindings/paths"))
        for member, value in (("cwd", "."), ("env", [])):
            pointer = f"/bindings/commands/lint/{member}"
            rows.append((f"command {member}", pointer, value, pointer))
        for command_id in ("codex-plan-review", "codex-diff-review", "commit-environment"):
            pointer = f"/bindings/commands/{command_id}"
            rows.append((f"platform id {command_id}", pointer,
                         {"argv": list(schema_three.COMMANDS[command_id]["argv"])}, pointer))
        rows.append(("malformed platform id", "/bindings/commands/codex-plan-review", None,
                     "/bindings/commands/codex-plan-review"))
        rows.extend([
            ("retired project.name", "/project/name", "nix-config", "/project/name"),
            ("retired paths.artifacts", "/bindings/paths/artifacts",
             {"specs": ".agents/artifacts/specs", "plans": ".agents/artifacts/plans"},
             "/bindings/paths/artifacts"),
            ("retired co_authored_by", "/bindings/vcs/commit/co_authored_by", False,
             "/bindings/vcs/commit/co_authored_by"),
            ("retired light_lane", "/bindings/workflow/light_lane",
             {"mode": "shadow", "budget_minutes": 90, "risk_paths": []},
             "/bindings/workflow/light_lane"),
        ])
        return rows

    def test_each_authored_constant_or_retired_member_is_refused_by_its_pointer(self):
        for label, pointer, value, refused in self.refused_rows():
            with self.subTest(label):
                contract = schema_three_contract()
                set_pointer(contract, pointer, value)
                code, payload, _ = self.resolve(self.schema_three_root(contract))
                error = self.assert_refusal(code, payload, "invalid_contract")
                self.assertEqual([v["pointer"] for v in error["violations"]], [refused])
                if refused in schema_three.RETIRED:
                    kind = "retired_member"
                elif refused in schema_three.DERIVED + schema_three.DERIVED_CONTAINERS:
                    kind = "derived_value"
                else:
                    kind = "platform_constant"
                self.assertEqual(
                    error["repair_id"], f"contract.{self.section(refused)}.{kind}")
                for violation in error["violations"]:
                    self.assertTrue(violation["message"])

    def test_a_command_id_with_a_slash_or_tilde_is_refused_at_its_escaped_pointer(self):
        for command_id, token in (("ci/lint", "ci~1lint"), ("ci~lint", "ci~0lint")):
            with self.subTest(command_id):
                contract = schema_three_contract()
                contract["bindings"]["commands"][command_id] = {
                    "argv": ["just", "lint"], "cwd": "."}
                code, payload, _ = self.resolve(self.schema_three_root(contract))
                error = self.assert_refusal(code, payload, "invalid_contract")
                self.assertEqual([v["pointer"] for v in error["violations"]],
                                 [f"/bindings/commands/{token}/cwd"])
                self.assertEqual(error["repair_id"], "contract.commands.platform_constant")

    def test_a_retired_member_beside_a_malformed_bindings_is_refused_once(self):
        contract = schema_three_contract()
        contract["project"] = {"name": "nix-config"}
        contract["bindings"] = []
        code, payload, _ = self.resolve(self.schema_three_root(contract))
        error = self.assert_refusal(code, payload, "invalid_contract")
        pointers = [v["pointer"] for v in error["violations"]]
        self.assertEqual(pointers.count("/project/name"), 1)
        self.assertEqual(sorted(pointers), ["/bindings", "/project/name"])

    def test_a_float_schema_version_is_not_schema_three(self):
        contract = schema_two_equivalent(schema_three_contract())
        contract["schema_version"] = 3.0
        code, payload, _ = self.resolve(self.owned(make_project_root(contract)))
        error = self.assert_refusal(code, payload, "invalid_contract")
        self.assertEqual([v["pointer"] for v in error["violations"]], ["/schema_version"])
        self.assertEqual(error["repair_id"], "contract.schema_version.invalid")

    def test_a_missing_verification_command_is_refused_at_its_command(self):
        def drop(*ids):
            def mutate(contract):
                for command_id in ids:
                    del contract["bindings"]["commands"][command_id]
            return mutate

        def drop_namespace(contract):
            del contract["bindings"]["commands"]

        rows = [
            ("lint", drop("lint"), ["/bindings/commands/lint"]),
            ("lint and test", drop("lint", "test"),
             ["/bindings/commands/lint", "/bindings/commands/test"]),
            ("no commands member", drop_namespace,
             ["/bindings/commands/lint", "/bindings/commands/test"]),
        ]
        for label, mutate, pointers in rows:
            with self.subTest(label):
                contract = schema_three_contract()
                # The pre-pull-request list names `lint`; this case is about the constants.
                del contract["bindings"]["workflow"]["verification_before_pull_request"]
                mutate(contract)
                code, payload, _ = self.resolve(self.schema_three_root(contract))
                error = self.assert_refusal(code, payload, "invalid_contract")
                self.assertEqual([v["pointer"] for v in error["violations"]], pointers)
                self.assertEqual(error["repair_id"], "contract.commands.member_missing")

    def test_a_malformed_commands_namespace_keeps_its_shape_error(self):
        contract = schema_three_contract()
        contract["bindings"]["commands"] = []
        code, payload, _ = self.resolve(self.schema_three_root(contract))
        error = self.assert_refusal(code, payload, "invalid_contract")
        self.assertEqual([v["pointer"] for v in error["violations"]], ["/bindings/commands"])
        self.assertEqual(error["repair_id"], "contract.bindings.not_object")

    def test_schema_two_still_reads_an_authored_platform_id_as_authored(self):
        contract = source_contract()
        contract["bindings"]["commands"]["codex-plan-review"] = {
            "argv": ["true"], "cwd": ".", "env": []}
        code, snap, err = self.resolve(self.owned(make_project_root(contract)))
        self.assertEqual(code, 0, err)
        self.assertEqual(snap["bindings"]["commands"]["codex-plan-review"]["argv"], ["true"])


class DerivedValuesTest(SchemaThreeCase):
    """The tracker repo, project id, required checks and platform range come from the repository."""

    def refused(self, root: Path) -> dict:
        code, payload, _ = self.resolve(root)
        return self.assert_refusal(code, payload, "invalid_contract")

    def test_a_schema_three_snapshot_takes_its_tracker_repo_and_project_id_from_the_remote(self):
        # The release profile names the repository it publishes to, and it must
        # be the tracker's: move it with the remote.
        contract = schema_three_contract()
        profile = contract["release"]["profiles"]["github-release"]
        profile["bindings"]["targets"]["repository"]["repository"] = "fagenorn/scratch-derived"
        profile["target"]["concurrency_keys"] = ["release/fagenorn/scratch-derived"]
        root = self.schema_three_root(
            contract, remote="https://github.com/fagenorn/scratch-derived.git")
        code, snap, err = self.resolve(root)
        self.assertEqual(code, 0, err)
        self.assertEqual(snap["project"]["id"], "fagenorn/scratch-derived")
        self.assertEqual(snap["bindings"]["tracker"]["repo_slug"], "fagenorn/scratch-derived")

    def test_a_missing_remote_refuses_by_name(self):
        error = self.refused(self.schema_three_root(schema_three_contract(), remote=None))
        self.assertEqual([v["pointer"] for v in error["violations"]],
                         ["/bindings/tracker/repo_slug", "/project/id"])
        self.assertEqual(error["repair_id"], "contract.tracker.not_derivable")
        for violation in error["violations"]:
            self.assertIn("git remote origin", violation["message"])

    def test_required_checks_equal_the_protection_sources_contexts(self):
        code, snap, err = self.resolve(self.schema_three_root(schema_three_contract()))
        self.assertEqual(code, 0, err)
        self.assertEqual(snap["bindings"]["vcs"]["merge"]["required_checks"],
                         ["Nix Eval", "Agent Workflow Tests"])

    def test_a_protection_source_that_lists_none_gives_none(self):
        for label, protection in (
                ("null", {"required_status_checks": None}),
                ("empty", {"required_status_checks": {"strict": True, "checks": []}})):
            with self.subTest(label):
                root = self.schema_three_root(schema_three_contract(), protection=protection)
                code, snap, err = self.resolve(root)
                self.assertEqual(code, 0, err)
                self.assertNotIn("required_checks", snap["bindings"]["vcs"]["merge"])

    def test_an_unreadable_protection_source_refuses_by_name(self):
        for label, protection in (
                ("absent", None),
                ("no checks", {"required_status_checks": {"contexts": ["Nix Eval"]}})):
            with self.subTest(label):
                error = self.refused(self.schema_three_root(
                    schema_three_contract(), protection=protection))
                self.assertEqual([v["pointer"] for v in error["violations"]],
                                 ["/bindings/vcs/merge/required_checks"])
                self.assertEqual(error["repair_id"], "contract.vcs.not_derivable")
                self.assertIn(".github/branch-protection.json", error["violations"][0]["message"])

    def test_the_platforms_own_tree_takes_its_range_from_its_own_manifest_with_no_lock(self):
        root = self.schema_three_root(schema_three_contract())
        code, _, err = self.resolve(root)
        self.assertEqual(code, 0, err)
        for version, reason in ((_next_minor(committed_manifest()["platform_version"]), "platform_too_old"), ("1.9.0", "platform_too_new")):
            with self.subTest(version):
                (root / TREE_MANIFEST).write_text(
                    json.dumps(mutated_manifest(platform_version=version)), encoding="utf-8")
                code, payload, _ = self.resolve(root)
                error = self.assert_refusal(code, payload, "unsupported_schema")
                self.assertEqual(error["reason_code"], reason)
                self.assertEqual([v["pointer"] for v in error["violations"]], ["/platform"])

    def test_an_unparseable_lock_beside_the_trees_own_manifest_still_resolves(self):
        root = self.schema_three_root(schema_three_contract())
        (root / "devenv.lock").write_text("not json", encoding="utf-8")
        code, _, err = self.resolve(root)
        self.assertEqual(code, 0, err)

    def test_the_resolver_cites_the_input_rule_record(self):
        source = Path(resolve_project.__file__).read_text(encoding="utf-8")
        self.assertIn("ADR-project-contract-014", source)

    def test_an_underivable_id_hides_no_other_missing_member(self):
        contract = schema_three_contract()
        del contract["bindings"]
        error = self.refused(self.schema_three_root(contract, remote=None))
        by_pointer = {v["pointer"]: v["message"] for v in error["violations"]}
        self.assertEqual(by_pointer.get("/bindings"), "required member is absent")
        self.assertIn("/bindings/tracker/repo_slug", by_pointer)
        self.assertIn("/project/id", by_pointer)
        self.assertNotIn("/project", by_pointer)


    def test_an_underivable_value_hides_the_shape_errors_beneath_it(self):
        contract = schema_three_contract()
        contract["platform"] = {"min_inclusive": "2"}
        error = self.refused(self.schema_three_root(contract, tree_manifest=False))
        self.assertEqual([v["pointer"] for v in error["violations"]], ["/platform", "/platform"])
        messages = [v["message"] for v in error["violations"]]
        self.assertEqual(sum("is derived from the repository" in m for m in messages), 1)
        self.assertEqual(sum("cannot be derived" in m for m in messages), 1)


class LockedPlatformTest(InProcessTestCase):
    """A repository that is not the platform's own takes its range from the locked revision."""

    def locked(self, version: str) -> tuple[Path, Path]:
        store = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, store, ignore_errors=True)
        root = make_schema_three_root(schema_three_contract(), tree_manifest=False)
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        stage_locked_platform(root, store, version)
        patch = mock.patch.object(derived_values, "STORE_DIR", str(store))
        patch.start()
        self.addCleanup(patch.stop)
        return root, store

    def test_a_locked_revision_gives_the_range_up_to_the_next_major(self):
        root, _ = self.locked("2.0.0")
        snapshot = resolve_project.resolve(str(root))
        self.assertEqual(snapshot["project"]["id"], "fagenorn/nix-config")
        for version, reason in (("2.3.0", "platform_too_old"), ("1.0.0", "platform_too_new")):
            with self.subTest(version):
                other, store = self.locked(version)
                with self.assertRaises(resolve_project.ContractError) as raised:
                    resolve_project.resolve(str(other))
                self.assertEqual(raised.exception.code, "unsupported_schema")
                self.assertEqual(raised.exception.reason_code, reason)

    def test_a_locked_revision_not_in_the_store_refuses_by_name(self):
        root, store = self.locked("2.0.0")
        shutil.rmtree(store)
        store.mkdir()
        with self.assertRaises(resolve_project.ContractError) as raised:
            resolve_project.resolve(str(root))
        error = raised.exception
        self.assertEqual(error.code, "invalid_contract")
        self.assertEqual(error.repair_id, "contract.platform.not_derivable")
        self.assertEqual([v["pointer"] for v in error.violations], ["/platform"])
        self.assertIn("Nix store", error.violations[0]["message"])


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


class AttemptBudgetSnapshotTest(SchemaThreeCase):
    """A schema-3 snapshot carries the budget its recorded history derives, and the basis of it."""

    T = datetime(2026, 11, 22, 12, tzinfo=timezone.utc)
    SLUG = "fagenorn/nix-config"
    FALLBACK = 240

    def record(self, root: Path, attempts: list, repo: str = SLUG) -> None:
        attempt_history.write_history(
            root, attempt_history.render_history(repo, self.T, attempts))

    def twenty(self) -> list:
        return [
            attempt_history.Attempt(
                i, 100 + i, self.T - timedelta(days=21 - i) - timedelta(seconds=i * 3600 + 30),
                self.T - timedelta(days=21 - i))
            for i in range(1, 21)]

    def orchestration(self, snap: dict) -> dict:
        return snap["bindings"]["workflow"]["orchestration"]

    def assert_fallback(self, root: Path, basis: dict) -> None:
        code, snap, err = self.resolve(root)
        self.assertEqual(code, 0, err)
        self.assertEqual(self.orchestration(snap)["attempt_budget_minutes"], self.FALLBACK)
        self.assertEqual(self.orchestration(snap)["attempt_budget_basis"], basis)

    def test_a_schema_three_snapshot_carries_the_budget_its_recorded_history_derives(self):
        root = self.schema_three_root(schema_three_contract())
        self.record(root, self.twenty())
        code, snap, err = self.resolve(root)
        self.assertEqual(code, 0, err)
        self.assertEqual(self.orchestration(snap)["attempt_budget_minutes"], 1621)
        self.assertEqual(self.orchestration(snap)["attempt_budget_basis"], {
            "source": "history", "delivered": 20, "percentile_90_seconds": 64830,
            "recorded_at": "2026-11-22T12:00:00Z"})

    def test_a_schema_two_snapshot_keeps_its_authored_budget_beside_a_recorded_history(self):
        contract = source_contract()
        contract["bindings"]["workflow"]["orchestration"]["attempt_budget_minutes"] = 180
        root = self.schema_three_root(contract)
        self.record(root, self.twenty(), repo=contract["bindings"]["tracker"]["repo_slug"])
        code, snap, err = self.resolve(root)
        self.assertEqual(code, 0, err)
        self.assertEqual(self.orchestration(snap)["attempt_budget_minutes"], 180)
        self.assertNotIn("attempt_budget_basis", self.orchestration(snap))

    def test_a_removed_history_gives_the_fallback_and_the_project_resolves(self):
        root = self.schema_three_root(schema_three_contract())
        self.record(root, self.twenty())
        attempt_history.history_path(root).unlink()
        self.assert_fallback(root, {"source": "fallback", "reason": "no_history"})

    def test_a_corrupted_history_gives_the_fallback_and_the_project_resolves(self):
        root = self.schema_three_root(schema_three_contract())
        self.record(root, self.twenty())
        attempt_history.history_path(root).write_bytes(b'{"version": 1, "repo"')
        self.assert_fallback(root, {"source": "fallback", "reason": "unreadable"})

    def test_an_invalid_history_gives_the_fallback(self):
        root = self.schema_three_root(schema_three_contract())
        attempts = self.twenty()
        first = attempts[0]
        attempts[0] = first._replace(merged_at=first.claimed_at - timedelta(seconds=1))
        self.record(root, attempts)
        self.assert_fallback(root, {"source": "fallback", "reason": "invalid"})

    def test_another_repositorys_history_gives_the_fallback(self):
        root = self.schema_three_root(schema_three_contract())
        self.record(root, self.twenty(), repo="o/other")
        self.assert_fallback(root, {"source": "fallback", "reason": "other_repository"})

    def test_nineteen_delivered_give_the_fallback_with_their_count(self):
        root = self.schema_three_root(schema_three_contract())
        self.record(root, self.twenty()[:19])
        self.assert_fallback(
            root, {"source": "fallback", "reason": "too_few", "delivered": 19})

    def test_a_resolve_leaves_the_history_untouched(self):
        root = self.schema_three_root(schema_three_contract())
        self.record(root, self.twenty())
        path = attempt_history.history_path(root)
        before = (path.read_bytes(), sorted(os.listdir(path.parent)))
        for _ in range(2):
            code, _, err = self.resolve(root)
            self.assertEqual(code, 0, err)
            self.assertEqual((path.read_bytes(), sorted(os.listdir(path.parent))), before)

    def test_a_schema_two_source_derives_nothing_and_reads_no_history(self):
        root = self.schema_three_root(source_contract())
        self.record(root, self.twenty(), repo=source_contract()["bindings"]["tracker"]["repo_slug"])
        with mock.patch.object(attempt_history, "read", side_effect=AssertionError("read")):
            self.assertEqual(
                resolve_project.derive_for(root, source_contract()),
                derived_values.Derived({}, []))

    def test_the_schema_three_history_read_starts_no_child_process_and_opens_no_connection(self):
        root = self.schema_three_root(schema_three_contract())
        self.record(root, self.twenty())
        expected = resolve_project.derive_for(root, schema_three_contract())
        with mock.patch("subprocess.Popen", side_effect=AssertionError), \
                mock.patch("socket.socket", side_effect=AssertionError):
            self.assertEqual(
                resolve_project.derive_for(root, schema_three_contract()), expected)
        self.assertEqual(expected.values[schema_three.ATTEMPT_BUDGET], 1621)


class PrePullRequestListTest(SchemaThreeCase):
    POINTER = "/bindings/workflow/verification_before_pull_request"

    def test_a_schema_three_contract_may_author_the_pre_pull_request_list(self):
        code, snap, err = self.resolve(self.schema_three_root(schema_three_contract()))
        self.assertEqual(code, 0, err)
        self.assertEqual(snap["bindings"]["workflow"]["verification_before_pull_request"],
                         ["lint"])
        # D5: the ids are checked although schema 3 never checks `verification`.
        contract = schema_three_contract()
        contract["bindings"]["workflow"]["verification_before_pull_request"] = ["nope"]
        code, payload, _ = self.resolve(self.schema_three_root(contract))
        error = self.assert_refusal(code, payload, "invalid_contract")
        self.assertEqual([v["pointer"] for v in error["violations"]],
                         [self.POINTER + "/0"])
        self.assertEqual(error["repair_id"], "contract.workflow.unknown_command_id")


if __name__ == "__main__":
    unittest.main()
