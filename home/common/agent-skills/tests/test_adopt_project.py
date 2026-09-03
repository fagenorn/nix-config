"""Contract tests for scripts/adopt-project.

Runs `adopt-project` as a subprocess under a temporary `HOME` holding the
platform library, a fixture manifest and an executable copy of the resolver at
`$HOME/.agents/bin/resolve-project` — the absolute path `adopt-project`
invokes and the only way it ever consumes the resolver (D26, D23).

Fixture repositories are real `git init` checkouts with a hermetic identity and
`commit.gpgsign=false` in the fixture's own local config; nothing here touches
the developer's git configuration or the machine's `~/.agents`.

One case loads the module in process, to reach the generic failure wrapper no
subprocess run can drive (D23). It is the only import of either script.
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "adopt-project.py"
RESOLVER = Path(__file__).resolve().parents[1] / "scripts" / "resolve-project.py"
LIBRARY = Path(__file__).resolve().parents[1] / "scripts" / "agent_platform.py"
ADOPT_LIBRARIES = {
    "adopt_inspection": Path(__file__).resolve().parents[1] / "scripts"
                        / "adopt_inspection.py",
    "adopt_planning": Path(__file__).resolve().parents[1] / "scripts"
                      / "adopt_planning.py",
    "adopt_apply": Path(__file__).resolve().parents[1] / "scripts"
                   / "adopt_apply.py",
    "adopt_verify": Path(__file__).resolve().parents[1] / "scripts"
                    / "adopt_verify.py",
}
MANIFEST = Path(__file__).resolve().parents[1] / "platform-manifest.json"
REPO_ROOT = Path(__file__).resolve().parents[4]

COMMITTED = object()

ACTIONS = ("move-canonical", "generate-projection", "retain-product",
           "archive-history", "delete-exact-duplicate", "needs-decision")
OUTCOMES = ("bootstrap", "reconcile", "no_change", "migration_required",
            "repair_required")
PLAN_STATES = ("draft", "ready", "not_applicable")
OPERATION_KINDS = ("git-mv", "write-file", "delete-file",
                   "regenerate-projection")
PROVENANCES = ("tracked", "targeted-ignored",
               "targeted-ignored-metadata-only", "git-worktree-metadata-only",
               "untracked-explicit-paths")
TOP_LEVEL_MEMBERS = ["changes", "decisions", "evidence", "handoff", "plan",
                     "schema_version", "verification"]
PLAN_MEMBERS = ["base_revision", "blockers", "input_digest", "outcome",
                "plan_id", "platform", "project_id", "state"]
HANDOFF_MEMBERS = ["evidence_record", "migration_map", "next_command",
                   "plan_path", "repo_root", "state"]


# --------------------------------------------------------------------------
# Isolation
# --------------------------------------------------------------------------


def install_home(home: Path, manifest: object = COMMITTED, *,
                 library_suffix: str = "", adopt_libraries: bool = True,
                 adopt_suffix: dict[str, str] | None = None) -> Path:
    """Populate `home` as the platform installation `adopt-project` reads.

    `library_suffix` is appended to the installed copy of the shared platform
    library. It is the fixture-level bypass the ambiguous-forward-step case
    needs: the library normally refuses a manifest carrying two records for one
    `from_schema`, so the only way to present that manifest to `adopt-project`
    is to install a library that does not check it. `adopt_suffix` is the same
    hook for the adoption libraries, and `adopt_libraries=False` leaves
    them uninstalled — which only a script run from the deployed layout can
    observe, because in the repository checkout they are the script's own
    siblings.
    """
    library_dir = home / ".agents" / "lib" / "python"
    library_dir.mkdir(parents=True, exist_ok=True)
    installed = library_dir / "agent_platform.py"
    installed.write_text(
        LIBRARY.read_text("utf-8") + library_suffix, encoding="utf-8")
    for name, source in ADOPT_LIBRARIES.items():
        target = library_dir / f"{name}.py"
        target.unlink(missing_ok=True)
        if adopt_libraries:
            target.write_text(
                source.read_text("utf-8")
                + (adopt_suffix or {}).get(name, ""), encoding="utf-8")
    binaries = home / ".agents" / "bin"
    binaries.mkdir(parents=True, exist_ok=True)
    resolver = binaries / "resolve-project"
    shutil.copy(RESOLVER, resolver)
    resolver.chmod(0o755)
    share = home / ".agents" / "share"
    share.mkdir(parents=True, exist_ok=True)
    target = share / "platform-manifest.json"
    target.unlink(missing_ok=True)
    if manifest is COMMITTED:
        shutil.copy(MANIFEST, target)
    elif manifest is None:
        pass
    elif isinstance(manifest, str):
        target.write_text(manifest, encoding="utf-8")
    else:
        target.write_text(json.dumps(manifest), encoding="utf-8")
    return home


def make_home(manifest: object = COMMITTED, *, library_suffix: str = "",
              adopt_libraries: bool = True,
              adopt_suffix: dict[str, str] | None = None) -> Path:
    return install_home(Path(tempfile.mkdtemp()).resolve(), manifest,
                        library_suffix=library_suffix,
                        adopt_libraries=adopt_libraries,
                        adopt_suffix=adopt_suffix)


def declared_members(tuple_name: str) -> tuple[str, ...]:
    """The named member tuple, read out of the script's own source.

    Read rather than copied: a second literal here would drift from the one the
    guard actually enforces, which is the failure these cases are about.
    """
    body = SCRIPT.read_text("utf-8").split(
        f"{tuple_name} = (", 1)[1].split(")", 1)[0]
    return tuple(re.findall(r'"([^"]+)"', body))


def install_registry(home: Path, entries: list[dict]) -> None:
    path = home / ".agents" / "state" / "fleet" / "registry.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema_version": 1, "projects": entries}),
        encoding="utf-8")


def run(*args: str, home: Path) -> tuple[int, str, str]:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, timeout=300,
        env={**os.environ, "HOME": str(home)},
    )
    return proc.returncode, proc.stdout, proc.stderr


def git(root: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True, text=True, timeout=120, check=True,
        env=dict(
            os.environ,
            GIT_CONFIG_GLOBAL=os.devnull,
            GIT_CONFIG_SYSTEM=os.devnull,
            GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid",
            GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid",
        ),
    )
    return proc.stdout


def tree_snapshot(root: Path) -> list[tuple[str, str, int | None]]:
    """Every path under `root` outside `.git`, with its type and file mtime."""
    out = []
    for path in sorted(root.rglob("*")):
        if ".git" in path.relative_to(root).parts:
            continue
        kind = "d" if path.is_dir() else "f"
        out.append((
            str(path.relative_to(root)), kind,
            None if kind == "d" else path.stat().st_mtime_ns,
        ))
    return out


def sha256_hash(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


# --------------------------------------------------------------------------
# Fixture repositories
# --------------------------------------------------------------------------


def source_contract() -> dict:
    return json.loads((REPO_ROOT / ".agents" / "project.json").read_text("utf-8"))


def init_repo() -> Path:
    # `.resolve()` because the platform temp dir is reached through a symlink
    # on macOS; the tool always reports the physical path.
    root = Path(tempfile.mkdtemp()).resolve()
    git(root, "init", "--quiet", "-b", "main")
    git(root, "config", "user.name", "t")
    git(root, "config", "user.email", "t@example.invalid")
    git(root, "config", "commit.gpgsign", "false")
    return root


def commit(root: Path, message: str = "fixture") -> None:
    git(root, "add", "-A")
    git(root, "commit", "--quiet", "-m", message)


def write(root: Path, relative: str, text: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def fixture_contract(**overrides: object) -> dict:
    """A valid schema-1 contract, taken from this repository's own.

    Derived rather than authored so that the fixture cannot drift out of
    validity as the contract's shape evolves; only the members a case is about
    are overridden.
    """
    contract = source_contract()
    contract["project"] = {"id": "fixture/target", "name": "target"}
    contract["bindings"]["paths"]["artifacts"] = {
        "specs": ".agents/artifacts/specs", "plans": ".agents/artifacts/plans"}
    contract["bindings"]["paths"]["rejections"] = [
        ".agents/knowledge/rejections"]
    for key, value in overrides.items():
        contract[key] = value
    return contract


def scaffold(root: Path, contract: dict, home: Path) -> None:
    """Write `contract`, its instruction source and both rendered projections.

    The projections are rendered by the resolver itself rather than by a
    literal copied out of it, so this fixture cannot disagree with the tool
    about what "in sync" means.
    """
    write(root, ".agents/instructions/bootstrap.md", "# invariants\n")
    (root / "home" / "common" / "agent-skills" / "standards").mkdir(
        parents=True, exist_ok=True)
    write(root, ".agents/project.json", json.dumps(contract, indent=2) + "\n")
    proc = subprocess.run(
        [sys.executable, str(RESOLVER), "write-projections",
         "--repo-root", str(root)],
        capture_output=True, text=True, timeout=120,
        env={**os.environ, "HOME": str(home)},
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"fixture projections could not be rendered: {proc.stdout}")


def bootstrap_repo(home: Path, *, remotes: tuple[str, ...] = ()) -> Path:
    """One unrelated tracked file: no `.agents/`, no `.claude/`."""
    root = init_repo()
    write(root, "README.md", "# unrelated\n")
    for index, url in enumerate(remotes):
        git(root, "remote", "add", "origin" if index == 0 else f"r{index}", url)
    commit(root)
    return root


def reconcile_repo(home: Path, *,
                   remotes: tuple[str, ...] = (
                       "git@github.com:fixture/reconcile.git",)) -> Path:
    """Legacy artifact trees and no contract at all."""
    root = init_repo()
    write(root, ".claude/specs/a.md", "# spec a\n")
    write(root, ".claude/plans/b.md", "# plan b\n")
    for index, url in enumerate(remotes):
        git(root, "remote", "add", "origin" if index == 0 else f"r{index}", url)
    commit(root)
    return root


EVIDENCE_RECORD_MEMBERS = ("schema_version", "plan_id", "outcome",
                           "base_revision", "platform", "decisions_accepted",
                           "sources", "checks", "path_migration_map")


def write_adoption_records(root: Path, digest: str = "a1" * 32) -> str:
    """The two records an adoption commits, as `apply` writes them.

    Authored here rather than produced by a run, so a fixture that must
    already *be* adopted needs no apply: `verify` discovers the record by
    listing the tree at `HEAD` (D34) and never by being told its name.
    """
    migration_map = f".agents/knowledge/archive/path-migrations/{digest}.json"
    write(root, migration_map, json.dumps({
        "schema_version": 1, "migration_id": f"sha256:{digest}",
        "moves": []}) + "\n")
    write(root, f".agents/artifacts/evidence/{digest}.json", json.dumps({
        "schema_version": 1, "plan_id": f"sha256:{digest}",
        "outcome": "no_change", "base_revision": git(
            root, "rev-parse", "HEAD").strip(),
        "platform": {"platform_version": "1.0.0",
                     "project_schema_versions": [1],
                     "resolved_schema_version": 1},
        "decisions_accepted": [], "sources": [], "checks": [],
        "path_migration_map": migration_map}) + "\n")
    return migration_map


def adopted_repo(home: Path, *, records: bool = True) -> Path:
    """A conformant checkout: valid contract, sentinel present, nothing legacy.

    The two adoption records a real apply commits are present by default, in
    a commit of their own: without them the checkout carries no adoption
    commit for `verify` to find, so it cannot legitimately verify as adopted
    (D34). `records=False` is the fixture the discovery negatives start from.
    """
    root = init_repo()
    scaffold(root, fixture_contract(), home)
    write(root, ".agents/runtime/.gitignore", "*\n")
    git(root, "add", "-f", ".agents/runtime/.gitignore")
    git(root, "remote", "add", "origin",
        "https://github.com/fixture/target.git")
    commit(root)
    if records:
        write_adoption_records(root)
        commit(root, "adopt")
    return root


def nix_config_shape_repo(home: Path) -> Path:
    """This repository's shape at base: a valid schema-1 contract without
    `platform`, legacy `.claude/specs`, `.claude/plans` and `.out-of-scope`
    trees, a `.claude/skills.config.json`, and no runtime sentinel."""
    root = init_repo()
    contract = fixture_contract()
    contract["bindings"]["paths"]["artifacts"] = {
        "specs": ".claude/specs", "plans": ".claude/plans"}
    contract["bindings"]["paths"]["rejections"] = [".out-of-scope"]
    scaffold(root, contract, home)
    # The projections are rendered from a contract that still declares
    # `platform`; dropping the member afterwards leaves them in sync, because
    # a projection is a pure function of the instruction source, its id and the
    # project schema.
    without_platform = json.loads(
        (root / ".agents" / "project.json").read_text("utf-8"))
    del without_platform["platform"]
    write(root, ".agents/project.json",
          json.dumps(without_platform, indent=2) + "\n")
    write(root, ".claude/specs/x.md", "# spec x\n")
    write(root, ".claude/plans/y.md", "# plan y\n")
    write(root, ".out-of-scope/z.md", "# rejected z\n")
    write(root, ".claude/skills.config.json", json.dumps(
        {"orchestration": {"agentBudgetMinutes": 180, "maxParallel": 2}},
        indent=2) + "\n")
    write(root, ".gitignore", GITIGNORE_WITH_COMMENT)
    git(root, "remote", "add", "origin",
        "https://github.com/fixture/target.git")
    commit(root)
    return root


GITIGNORE_WITH_COMMENT = (
    "result\n"
    "__pycache__/\n"
    "\n"
    "# The lazily created runtime bucket of the .agents/ taxonomy.\n"
    "# It is never tracked.\n"
    ".agents/runtime/\n"
)


class AdoptTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.home = make_home()

    def plan(self, root: Path, *extra: str,
             home: Path | None = None) -> tuple[int, object, str]:
        code, out, err = run("plan", "--repo-root", str(root), *extra,
                             home=home or self.home)
        try:
            payload: object = json.loads(out)
        except json.JSONDecodeError:
            payload = None
        return code, payload, err

    def ready_plan(self, root: Path) -> object:
        code, doc, err = self.plan(root)
        self.assertEqual(code, 0, err)
        return doc

    def assert_read_only(self, root: Path, expected_code: int,
                         *args: str) -> None:
        """Three independent witnesses that `args` wrote nothing under `root`.

        `git status --porcelain` catches a tracked-content or index change, the
        recursive path/type set catches a created directory, and the mtimes
        catch a rewrite with identical bytes (D21).
        """
        before_status = git(root, "status", "--porcelain")
        before_tree = tree_snapshot(root)
        code, _, err = run(*args, home=self.home)
        self.assertEqual(code, expected_code, err)
        self.assertEqual(git(root, "status", "--porcelain"), before_status)
        self.assertEqual(tree_snapshot(root), before_tree)


# --------------------------------------------------------------------------
# Outcome routing — one case per ordered rule
# --------------------------------------------------------------------------


def manifest_with(versions: list[int], migrations: list[dict],
                  platform_version: str = "1.0.0") -> dict:
    return {
        "schema_version": 1,
        "platform_version": platform_version,
        "project_schema_versions": versions,
        "resolved_schema_version": 1,
        "migrations": migrations,
        "deprecations": [],
        "removals": [],
    }


class OutcomeRoutingTest(AdoptTestCase):
    def test_rule_1_no_contract_and_no_agent_surface_is_bootstrap(self):
        doc = self.ready_plan(bootstrap_repo(self.home))
        self.assertEqual(doc["plan"]["outcome"], "bootstrap")

    def test_rule_2_no_contract_with_legacy_surface_is_reconcile(self):
        doc = self.ready_plan(reconcile_repo(self.home))
        self.assertEqual(doc["plan"]["outcome"], "reconcile")

    def test_rule_3_supported_but_not_highest_schema_is_migration_required(self):
        home = make_home(manifest_with(
            [1, 2], [{"id": "project-1-to-2", "from_schema": 1,
                      "to_schema": 2}]))
        root = adopted_repo(home)
        code, doc, err = self.plan(root, home=home)
        self.assertEqual(code, 0, err)
        self.assertEqual(doc["plan"]["outcome"], "migration_required")
        self.assertEqual(doc["plan"]["state"], "not_applicable")
        self.assertEqual(doc["changes"], [])
        self.assertIn("project-1-to-2", doc["handoff"]["next_command"])

    def test_rule_4_unsupported_schema_with_forward_step_migrates(self):
        home = make_home(manifest_with(
            [2], [{"id": "project-1-to-2", "from_schema": 1, "to_schema": 2}]))
        root = adopted_repo(self.home)
        code, doc, err = self.plan(root, home=home)
        self.assertEqual(code, 0, err)
        self.assertEqual(doc["plan"]["outcome"], "migration_required")
        self.assertIn("project-1-to-2", doc["handoff"]["next_command"])

    def test_rule_4_unsupported_schema_without_forward_step_needs_repair(self):
        home = make_home(manifest_with([2], []))
        root = adopted_repo(self.home)
        code, doc, err = self.plan(root, home=home)
        self.assertEqual(code, 0, err)
        self.assertEqual(doc["plan"]["outcome"], "repair_required")
        self.assertEqual(doc["plan"]["state"], "not_applicable")
        self.assertEqual(doc["changes"], [])

    def test_rule_5_nix_config_shape_is_reconcile(self):
        doc = self.ready_plan(nix_config_shape_repo(self.home))
        self.assertEqual(doc["plan"]["outcome"], "reconcile")

    def test_rule_6_conformant_checkout_is_no_change(self):
        doc = self.ready_plan(adopted_repo(self.home))
        self.assertEqual(doc["plan"]["outcome"], "no_change")
        self.assertEqual(doc["plan"]["state"], "not_applicable")
        self.assertEqual(doc["changes"], [])
        self.assertIn("verify --register", doc["handoff"]["next_command"])

    def test_a_drifted_projection_is_reconcilable_rather_than_a_blocker(self):
        root = adopted_repo(self.home)
        write(root, "AGENTS.md", "hand-edited\n")
        commit(root, "drift a projection")
        doc = self.ready_plan(root)
        self.assertEqual(doc["plan"]["outcome"], "reconcile")
        self.assertEqual(doc["plan"]["state"], "ready", doc["plan"]["blockers"])
        self.assertEqual(
            [op["targets"][0] for op in doc["changes"]
             if op["op"] == "regenerate-projection"],
            ["AGENTS.md", "CLAUDE.md"])

    def test_rule_7_current_schema_invalid_with_nothing_to_reconcile(self):
        root = adopted_repo(self.home)
        contract = json.loads(
            (root / ".agents" / "project.json").read_text("utf-8"))
        del contract["project"]["name"]
        write(root, ".agents/project.json", json.dumps(contract, indent=2) + "\n")
        commit(root, "break the contract")
        doc = self.ready_plan(root)
        self.assertEqual(doc["plan"]["outcome"], "repair_required")
        self.assertEqual(doc["plan"]["state"], "not_applicable")
        self.assertEqual(doc["changes"], [])
        self.assertIn("contract.", doc["handoff"]["next_command"])


class ForwardStepRefusalTest(AdoptTestCase):
    def test_absent_forward_step_is_adopt_failure(self):
        home = make_home(manifest_with([1, 2], []))
        root = adopted_repo(self.home)
        code, doc, err = self.plan(root, home=home)
        self.assertEqual(code, 2, err)
        self.assertEqual(doc["error"]["code"], "adopt_failure")
        self.assertEqual(doc["error"]["repair_id"],
                         "adopt.manifest.forward_step_missing")
        self.assertTrue(doc["error"]["violations"])

    def test_ambiguous_forward_step_is_adopt_failure(self):
        # The library refuses two records for one `from_schema`, so the
        # manifest can only reach the router through a library that does not
        # validate migrations.
        home = make_home(
            manifest_with([1, 2], [
                {"id": "a", "from_schema": 1, "to_schema": 2},
                {"id": "b", "from_schema": 1, "to_schema": 2},
            ]),
            library_suffix=(
                "\n\ndef _validate_migrations(source, violations):\n"
                "    return\n"),
        )
        root = adopted_repo(self.home)
        code, doc, err = self.plan(root, home=home)
        self.assertEqual(code, 2, err)
        self.assertEqual(doc["error"]["code"], "adopt_failure")
        self.assertEqual(doc["error"]["repair_id"],
                         "adopt.manifest.forward_step_ambiguous")


# --------------------------------------------------------------------------
# Project identity (D35)
# --------------------------------------------------------------------------


class ProjectIdentityTest(AdoptTestCase):
    def assert_recommended(self, root: Path, expected: str) -> object:
        doc = self.ready_plan(root)
        self.assertEqual(doc["decisions"]["open"], [])
        self.assertEqual(len(doc["decisions"]["recommended"]), 1)
        entry = doc["decisions"]["recommended"][0]
        self.assertEqual(sorted(entry), ["basis", "id", "value"])
        self.assertEqual(entry["id"], "project-id")
        self.assertEqual(entry["value"], expected)
        self.assertEqual(doc["plan"]["project_id"], expected)
        return doc

    def test_single_ssh_remote_is_normalized(self):
        root = reconcile_repo(
            self.home, remotes=("git@github.com:fixture/reconcile.git",))
        self.assert_recommended(root, "fixture/reconcile")

    def test_single_https_remote_is_normalized(self):
        root = reconcile_repo(
            self.home, remotes=("https://github.com/fixture/reconcile.git",))
        self.assert_recommended(root, "fixture/reconcile")

    def test_recommendation_is_byte_identical_across_runs(self):
        root = reconcile_repo(self.home)
        first = run("plan", "--repo-root", str(root), home=self.home)
        second = run("plan", "--repo-root", str(root), home=self.home)
        self.assertEqual(first[0], 0, first[2])
        self.assertEqual(first[1], second[1])

    def assert_open_question(self, root: Path) -> object:
        doc = self.ready_plan(root)
        self.assertEqual(len(doc["decisions"]["open"]), 1)
        entry = doc["decisions"]["open"][0]
        self.assertEqual(
            sorted(entry),
            ["basis", "id", "impact", "recommendation", "value"])
        self.assertEqual(entry["id"], "project-id")
        self.assertEqual(doc["plan"]["state"], "draft")
        return doc

    def test_zero_remotes_opens_the_question(self):
        self.assert_open_question(reconcile_repo(self.home, remotes=()))

    def test_two_remotes_open_the_question(self):
        self.assert_open_question(reconcile_repo(self.home, remotes=(
            "git@github.com:fixture/one.git", "git@github.com:fixture/two.git")))

    def test_unnormalizable_remote_opens_the_question(self):
        self.assert_open_question(
            reconcile_repo(self.home, remotes=("weird-remote",)))

    def test_fleet_collision_at_another_root_opens_the_question(self):
        root = reconcile_repo(self.home)
        install_registry(self.home, [
            {"project_id": "fixture/reconcile", "root": "/elsewhere/checkout"}])
        self.assert_open_question(root)

    def test_fleet_entry_at_the_same_root_does_not_open_the_question(self):
        root = reconcile_repo(self.home)
        install_registry(self.home, [
            {"project_id": "fixture/reconcile", "root": str(root)}])
        self.assert_recommended(root, "fixture/reconcile")

    def test_a_valid_contract_supplies_the_id_without_a_question(self):
        doc = self.ready_plan(adopted_repo(self.home))
        self.assertEqual(doc["plan"]["project_id"], "fixture/target")
        self.assertEqual(doc["decisions"]["recommended"], [])
        self.assertEqual(doc["decisions"]["open"], [])


# --------------------------------------------------------------------------
# Document shape
# --------------------------------------------------------------------------


class DocumentShapeTest(AdoptTestCase):
    def test_exactly_seven_top_level_members(self):
        for name, build in (("bootstrap", bootstrap_repo),
                            ("reconcile", reconcile_repo),
                            ("adopted", adopted_repo),
                            ("nix-config", nix_config_shape_repo)):
            with self.subTest(fixture=name):
                doc = self.ready_plan(build(self.home))
                self.assertEqual(sorted(doc), TOP_LEVEL_MEMBERS)
                self.assertEqual(doc["schema_version"], 1)
                self.assertEqual(sorted(doc["plan"]), PLAN_MEMBERS)
                self.assertEqual(sorted(doc["handoff"]), HANDOFF_MEMBERS)
                self.assertEqual(sorted(doc["decisions"]),
                                 ["answered", "open", "recommended"])
                self.assertEqual(doc["decisions"]["answered"], [])
                self.assertEqual(sorted(doc["verification"]),
                                 ["commit_gates", "ready_gates"])
                self.assertIn(doc["plan"]["state"], PLAN_STATES)
                self.assertIn(doc["plan"]["outcome"], OUTCOMES)

    def test_every_evidence_entry_carries_exactly_one_action(self):
        doc = self.ready_plan(nix_config_shape_repo(self.home))
        self.assertTrue(doc["evidence"])
        for entry in doc["evidence"]:
            with self.subTest(path=entry["path"]):
                self.assertEqual(
                    sorted(entry),
                    ["action", "count", "fingerprint", "lifecycle_class",
                     "note", "path", "provenance", "target"])
                self.assertIn(entry["action"], ACTIONS)
                self.assertIn(entry["provenance"], PROVENANCES)
        paths = [entry["path"] for entry in doc["evidence"]]
        self.assertEqual(paths, sorted(paths))

    def test_every_operation_carries_the_typed_shape(self):
        doc = self.ready_plan(nix_config_shape_repo(self.home))
        self.assertTrue(doc["changes"])
        for op in doc["changes"]:
            with self.subTest(op=op["op"]):
                self.assertEqual(
                    sorted(op),
                    ["after", "approval_class", "before", "op", "sources",
                     "targets"])
                self.assertIn(op["op"], OPERATION_KINDS)
                self.assertEqual(
                    op["approval_class"],
                    "destructive" if op["op"] == "delete-file" else "normal")

    def test_commit_gates_are_all_not_run_at_plan_time(self):
        doc = self.ready_plan(nix_config_shape_repo(self.home))
        self.assertTrue(doc["verification"]["commit_gates"])
        for gate in doc["verification"]["commit_gates"]:
            with self.subTest(gate=gate["id"]):
                self.assertEqual(sorted(gate), ["id", "repair_id", "status"])
                self.assertEqual(gate["status"], "not_run")
                self.assertIsNone(gate["repair_id"])

    def test_a_ready_plan_has_no_needs_decision_and_no_open_question(self):
        doc = self.ready_plan(nix_config_shape_repo(self.home))
        self.assertEqual(doc["plan"]["state"], "ready", doc["plan"]["blockers"])
        self.assertEqual(doc["decisions"]["open"], [])
        self.assertEqual(doc["plan"]["blockers"], [])
        for entry in doc["evidence"]:
            self.assertNotEqual(entry["action"], "needs-decision")
        for gate in doc["verification"]["ready_gates"]:
            self.assertEqual(gate["status"], "passed", gate["id"])

    def test_the_checkout_path_appears_only_in_handoff(self):
        root = nix_config_shape_repo(self.home)
        code, out, err = run("plan", "--repo-root", str(root), home=self.home)
        self.assertEqual(code, 0, err)
        doc = json.loads(out)
        self.assertEqual(doc["handoff"]["repo_root"], str(root))
        for member in ("plan", "evidence", "changes", "decisions",
                       "verification"):
            self.assertNotIn(
                str(root),
                json.dumps(doc[member], sort_keys=True), member)

    def test_stdout_is_compact_sorted_json_with_a_trailing_newline(self):
        code, out, err = run("plan", "--repo-root",
                             str(reconcile_repo(self.home)), home=self.home)
        self.assertEqual(code, 0, err)
        self.assertTrue(out.endswith("\n"))
        self.assertNotIn("\n", out[:-1])
        self.assertEqual(out, json.dumps(
            json.loads(out), sort_keys=True, separators=(",", ":")) + "\n")


# --------------------------------------------------------------------------
# `plan_id`
# --------------------------------------------------------------------------


class PlanIdentityTest(AdoptTestCase):
    def expected_plan_id(self, doc: object) -> str:
        """D15's digest, recomputed here from the document's own inputs.

        The formula is the spec's, not the implementation's: the six named
        members, canonical JSON, SHA-256. Nothing is pasted from a previous
        run.
        """
        source = {
            "adopt_schema_version": doc["schema_version"],
            "project_id": doc["plan"]["project_id"],
            "base_revision": doc["plan"]["base_revision"],
            "platform": doc["plan"]["platform"],
            "evidence": doc["evidence"],
            "decisions_answered": doc["decisions"]["answered"],
        }
        payload = json.dumps(source, sort_keys=True,
                             separators=(",", ":")).encode("utf-8")
        return "sha256:" + hashlib.sha256(payload).hexdigest()

    def test_plan_id_is_the_documented_digest_and_equals_input_digest(self):
        doc = self.ready_plan(nix_config_shape_repo(self.home))
        self.assertEqual(doc["plan"]["plan_id"], self.expected_plan_id(doc))
        self.assertEqual(doc["plan"]["input_digest"], doc["plan"]["plan_id"])

    def test_platform_block_is_the_three_reproducible_manifest_values(self):
        doc = self.ready_plan(nix_config_shape_repo(self.home))
        self.assertEqual(
            doc["plan"]["platform"],
            {"platform_version": "1.0.0", "project_schema_versions": [1],
             "resolved_schema_version": 1})

    def test_two_runs_on_an_unchanged_fixture_are_byte_identical(self):
        root = nix_config_shape_repo(self.home)
        first = run("plan", "--repo-root", str(root), home=self.home)
        second = run("plan", "--repo-root", str(root), home=self.home)
        self.assertEqual(first[0], 0, first[2])
        self.assertEqual(first[1], second[1])

    def test_a_second_checkout_yields_the_same_id_at_a_different_root(self):
        """D15: the id is a property of the repository, not of the machine.

        The copy is planned under a user scope of its own, because a stored
        plan stays bound to the one checkout it was derived from and the
        second checkout's plan is refused rather than allowed to re-point it
        (`test_adopt_project_boundaries.PlanClaimTest`). The two ids are equal
        all the same, which is the property D15 is about.
        """
        root = nix_config_shape_repo(self.home)
        other = Path(tempfile.mkdtemp()).resolve() / "copy"
        shutil.copytree(root, other)
        first = self.ready_plan(root)
        code, second, err = self.plan(other, home=make_home())
        self.assertEqual(code, 0, err)
        self.assertEqual(first["plan"]["plan_id"], second["plan"]["plan_id"])
        self.assertNotEqual(first["handoff"]["repo_root"],
                            second["handoff"]["repo_root"])

    def test_one_changed_tracked_byte_yields_a_different_id(self):
        root = nix_config_shape_repo(self.home)
        before = self.ready_plan(root)["plan"]["plan_id"]
        write(root, ".claude/specs/x.md", "# spec X\n")
        commit(root, "edit one byte")
        self.assertNotEqual(before, self.ready_plan(root)["plan"]["plan_id"])

    def test_a_different_platform_version_yields_a_different_id(self):
        root = nix_config_shape_repo(self.home)
        before = self.ready_plan(root)["plan"]["plan_id"]
        other = make_home(manifest_with([1], [], platform_version="1.1.0"))
        code, doc, err = self.plan(root, home=other)
        self.assertEqual(code, 0, err)
        self.assertNotEqual(before, doc["plan"]["plan_id"])

    def test_the_document_is_stored_under_user_scope_state(self):
        root = nix_config_shape_repo(self.home)
        code, out, err = run("plan", "--repo-root", str(root), home=self.home)
        self.assertEqual(code, 0, err)
        doc = json.loads(out)
        stored = (self.home / ".agents" / "state" / "adopt" / "plans"
                  / (doc["plan"]["plan_id"].split(":", 1)[1] + ".json"))
        self.assertTrue(stored.is_file(), stored)
        self.assertEqual(json.loads(stored.read_text("utf-8")), doc)
        self.assertEqual(doc["handoff"]["plan_path"], str(stored))

    def test_human_format_prints_a_view_and_stores_the_same_document(self):
        root = nix_config_shape_repo(self.home)
        code, out, err = run("plan", "--repo-root", str(root), home=self.home)
        self.assertEqual(code, 0, err)
        doc = json.loads(out)
        stored = (self.home / ".agents" / "state" / "adopt" / "plans"
                  / (doc["plan"]["plan_id"].split(":", 1)[1] + ".json"))
        before = stored.read_bytes()
        stored.unlink()
        code, human, err = run("plan", "--repo-root", str(root),
                               "--format", "human", home=self.home)
        self.assertEqual(code, 0, err)
        with self.assertRaises(json.JSONDecodeError):
            json.loads(human)
        self.assertIn(doc["plan"]["outcome"], human)
        self.assertEqual(stored.read_bytes(), before)


# --------------------------------------------------------------------------
# Inspection boundary
# --------------------------------------------------------------------------


class InspectionBoundaryTest(AdoptTestCase):
    def entry(self, doc: object, path: str) -> dict:
        for candidate in doc["evidence"]:
            if candidate["path"] == path:
                return candidate
        raise AssertionError(
            f"{path!r} is not in {[e['path'] for e in doc['evidence']]}")

    def test_a_secret_shaped_path_is_named_but_never_read(self):
        root = nix_config_shape_repo(self.home)
        write(root, ".claude/specs/secrets/leak.md", "SUPER-SECRET-VALUE\n")
        commit(root, "add a secret-shaped path")
        code, out, err = run("plan", "--repo-root", str(root), home=self.home)
        self.assertEqual(code, 0, err)
        doc = json.loads(out)
        entry = self.entry(doc, ".claude/specs/secrets/leak.md")
        self.assertIsNone(entry["fingerprint"])
        self.assertEqual(entry["action"], "retain-product")
        self.assertIsNone(entry["target"])
        self.assertNotIn("SUPER-SECRET-VALUE", out)
        for op in doc["changes"]:
            self.assertNotIn(".claude/specs/secrets/leak.md",
                             op["sources"] + op["targets"])

    def test_untracked_overlap_keeps_the_plan_draft_with_a_named_blocker(self):
        root = nix_config_shape_repo(self.home)
        write(root, ".claude/specs/draft.md", "# untracked\n")
        doc = self.ready_plan(root)
        self.assertEqual(doc["plan"]["state"], "draft")
        blocked = [b["id"] for b in doc["plan"]["blockers"]]
        self.assertIn("no-untracked-overlap", blocked)
        entry = self.entry(doc, ".claude/specs/draft.md")
        self.assertEqual(entry["provenance"], "untracked-explicit-paths")

    def test_superpowers_and_worktrees_are_metadata_only(self):
        root = nix_config_shape_repo(self.home)
        write(root, ".gitignore",
              GITIGNORE_WITH_COMMENT + ".superpowers/\n.worktrees/\n")
        commit(root, "ignore the residue trees")
        write(root, ".superpowers/sdd/notes.md", "RESIDUE-CONTENT\n")
        write(root, ".worktrees/wt-a/file.md", "WORKTREE-CONTENT\n")
        code, out, err = run("plan", "--repo-root", str(root), home=self.home)
        self.assertEqual(code, 0, err)
        doc = json.loads(out)
        for path in (".superpowers", ".worktrees"):
            with self.subTest(path=path):
                entry = self.entry(doc, path)
                self.assertEqual(entry["provenance"],
                                 "targeted-ignored-metadata-only")
                self.assertIsNone(entry["fingerprint"])
                self.assertEqual(entry["action"], "retain-product")
                self.assertGreaterEqual(entry["count"], 1)
        self.assertNotIn("RESIDUE-CONTENT", out)
        self.assertNotIn("WORKTREE-CONTENT", out)

    def test_registered_worktrees_are_metadata_only(self):
        root = nix_config_shape_repo(self.home)
        linked = Path(tempfile.mkdtemp()).resolve() / "wt-linked"
        git(root, "worktree", "add", "--quiet", str(linked), "-b", "linked")
        doc = self.ready_plan(root)
        entry = self.entry(doc, ".git/worktrees")
        self.assertEqual(entry["provenance"], "git-worktree-metadata-only")
        self.assertIsNone(entry["fingerprint"])
        self.assertEqual(entry["count"], 1)

    def test_read_only_on_a_succeeding_run(self):
        root = nix_config_shape_repo(self.home)
        self.assert_read_only(root, 0, "plan", "--repo-root", str(root))

    def test_read_only_on_a_refusing_run(self):
        home = make_home(manifest_with([1, 2], []))
        root = adopted_repo(self.home)
        before_status = git(root, "status", "--porcelain")
        before_tree = tree_snapshot(root)
        code, _, err = run("plan", "--repo-root", str(root), home=home)
        self.assertEqual(code, 2, err)
        self.assertEqual(git(root, "status", "--porcelain"), before_status)
        self.assertEqual(tree_snapshot(root), before_tree)


# --------------------------------------------------------------------------
# Typed operations
# --------------------------------------------------------------------------


class TypedOperationTest(AdoptTestCase):
    def ops(self, doc: object, kind: str) -> list[dict]:
        return [op for op in doc["changes"] if op["op"] == kind]

    def only_write(self, doc: object, target: str) -> dict:
        matches = [op for op in doc["changes"]
                   if op["op"] == "write-file" and op["targets"] == [target]]
        self.assertEqual(len(matches), 1, target)
        return matches[0]

    def test_moves_are_git_mv_sorted_by_old_path(self):
        doc = self.ready_plan(nix_config_shape_repo(self.home))
        moves = self.ops(doc, "git-mv")
        pairs = [(op["sources"][0], op["targets"][0]) for op in moves]
        self.assertEqual([p[0] for p in pairs], sorted(p[0] for p in pairs))
        self.assertIn((".claude/specs/x.md", ".agents/artifacts/specs/x.md"),
                      pairs)
        self.assertIn((".claude/plans/y.md", ".agents/artifacts/plans/y.md"),
                      pairs)
        self.assertIn((".out-of-scope/z.md",
                       ".agents/knowledge/rejections/z.md"), pairs)

    def test_the_contract_amendment_adds_platform_and_repoints_paths(self):
        root = nix_config_shape_repo(self.home)
        doc = self.ready_plan(root)
        op = self.only_write(doc, ".agents/project.json")
        contract = json.loads(
            (root / ".agents" / "project.json").read_text("utf-8"))
        contract["platform"] = {"min_inclusive": "1.0.0",
                                "max_exclusive": "2.0.0"}
        contract["bindings"]["paths"]["artifacts"] = {
            "specs": ".agents/artifacts/specs",
            "plans": ".agents/artifacts/plans"}
        contract["bindings"]["paths"]["rejections"] = [
            ".agents/knowledge/rejections"]
        expected = json.dumps(contract, indent=2, ensure_ascii=False) + "\n"
        self.assertEqual(op["after"], sha256_hash(expected.encode("utf-8")))

    def test_the_runtime_sentinel_is_exactly_two_bytes(self):
        doc = self.ready_plan(nix_config_shape_repo(self.home))
        op = self.only_write(doc, ".agents/runtime/.gitignore")
        self.assertIsNone(op["before"])
        self.assertEqual(op["after"], sha256_hash(b"*\n"))

    def test_the_migration_map_and_evidence_record_are_named_by_plan_id(self):
        doc = self.ready_plan(nix_config_shape_repo(self.home))
        digest = doc["plan"]["plan_id"].split(":", 1)[1]
        self.assertEqual(
            doc["handoff"]["migration_map"],
            f".agents/knowledge/archive/path-migrations/{digest}.json")
        self.assertEqual(doc["handoff"]["evidence_record"],
                         f".agents/artifacts/evidence/{digest}.json")
        self.only_write(doc, doc["handoff"]["migration_map"])
        self.only_write(doc, doc["handoff"]["evidence_record"])

    def test_the_evidence_record_carries_this_plans_own_outcome(self):
        """The record is only ever a hash in the plan, so its content is
        rebuilt here from D34's members and compared against that hash."""
        doc = self.ready_plan(bootstrap_repo(self.home))
        self.assertEqual(doc["plan"]["outcome"], "bootstrap")
        record = {
            "schema_version": 1,
            "plan_id": doc["plan"]["plan_id"],
            "outcome": doc["plan"]["outcome"],
            "base_revision": doc["plan"]["base_revision"],
            "platform": doc["plan"]["platform"],
            "decisions_accepted": (doc["decisions"]["recommended"]
                                   + doc["decisions"]["answered"]),
            "sources": [{"path": entry["path"], "before": entry["fingerprint"],
                         "after": entry["target"]}
                        for entry in doc["evidence"]],
            "checks": [{"id": gate["id"], "status": gate["status"]}
                       for gate in doc["verification"]["ready_gates"]],
            "path_migration_map": doc["handoff"]["migration_map"],
        }
        expected = json.dumps(record, sort_keys=True, indent=2,
                              ensure_ascii=False) + "\n"
        op = self.only_write(doc, doc["handoff"]["evidence_record"])
        self.assertEqual(op["after"], sha256_hash(expected.encode("utf-8")))

    def test_projections_are_regenerated_last(self):
        doc = self.ready_plan(nix_config_shape_repo(self.home))
        kinds = [op["op"] for op in doc["changes"]]
        regenerations = self.ops(doc, "regenerate-projection")
        self.assertEqual(len(regenerations), 2)
        self.assertEqual(kinds[-2:], ["regenerate-projection"] * 2)
        self.assertEqual(
            sorted(op["targets"][0] for op in regenerations),
            ["AGENTS.md", "CLAUDE.md"])

    def test_no_operation_targets_a_file_outside_the_planned_set(self):
        root = nix_config_shape_repo(self.home)
        write(root, "home/common/agent-skills/skills/writing-plans/SKILL.md",
              "Plans live in `.claude/plans` unless the contract says otherwise.\n")
        commit(root, "add a skill mentioning the legacy path")
        doc = self.ready_plan(root)
        skill = "home/common/agent-skills/skills/writing-plans/SKILL.md"
        for op in doc["changes"]:
            self.assertNotIn(skill, op["sources"] + op["targets"])
        self.assertEqual(
            (root / skill).read_text("utf-8"),
            "Plans live in `.claude/plans` unless the contract says otherwise.\n")

    def test_the_legacy_binding_config_gains_the_three_keys(self):
        root = nix_config_shape_repo(self.home)
        doc = self.ready_plan(root)
        op = self.only_write(doc, ".claude/skills.config.json")
        config = json.loads(
            (root / ".claude" / "skills.config.json").read_text("utf-8"))
        config["specDir"] = ".agents/artifacts/specs"
        config["planDir"] = ".agents/artifacts/plans"
        config["rejectionsDir"] = ".agents/knowledge/rejections"
        expected = json.dumps(config, indent=2, ensure_ascii=False) + "\n"
        self.assertEqual(op["after"], sha256_hash(expected.encode("utf-8")))
        self.assertIn("orchestration", config)

    def test_only_the_declared_legacy_binding_config_is_rewritten(self):
        root = nix_config_shape_repo(self.home)
        write(root, ".claude/other.config.json", json.dumps({"specDir": "x"}))
        commit(root, "add a second config")
        doc = self.ready_plan(root)
        for op in doc["changes"]:
            self.assertNotIn(".claude/other.config.json", op["targets"])


class GitignoreAmendmentTest(AdoptTestCase):
    """The one heuristic in the module, exercised through the operation it
    produces: the plan carries the amended `.gitignore` as a content hash, so
    each case compares that hash against text computed by hand here."""

    def amended(self, original: str) -> dict | None:
        root = nix_config_shape_repo(self.home)
        write(root, ".gitignore", original)
        commit(root, "set the gitignore under test")
        doc = self.ready_plan(root)
        matches = [op for op in doc["changes"]
                   if op["op"] == "write-file"
                   and op["targets"] == [".gitignore"]]
        self.assertLessEqual(len(matches), 1)
        return matches[0] if matches else None

    def test_pattern_with_its_own_comment_block_removes_both(self):
        original = (
            "result\n"
            "\n"
            "# the runtime bucket\n"
            "# never tracked\n"
            ".agents/runtime/\n"
        )
        op = self.amended(original)
        self.assertEqual(op["after"], sha256_hash(b"result\n\n"))

    def test_pattern_with_no_comment_removes_only_the_line(self):
        original = "result\n.agents/runtime/\n__pycache__/\n"
        op = self.amended(original)
        self.assertEqual(op["after"],
                         sha256_hash(b"result\n__pycache__/\n"))

    def test_pattern_amid_other_patterns_keeps_the_comment(self):
        original = (
            "# scratch\n"
            "result\n"
            ".agents/runtime/\n"
            "__pycache__/\n"
        )
        op = self.amended(original)
        self.assertEqual(
            op["after"],
            sha256_hash(b"# scratch\nresult\n__pycache__/\n"))

    def test_a_doubled_blank_line_is_collapsed_to_one(self):
        original = (
            "result\n"
            "\n"
            "# the runtime bucket\n"
            ".agents/runtime/\n"
            "\n"
            "__pycache__/\n"
        )
        op = self.amended(original)
        self.assertEqual(op["after"],
                         sha256_hash(b"result\n\n__pycache__/\n"))

    def test_an_absent_pattern_produces_no_operation(self):
        self.assertIsNone(self.amended("result\n__pycache__/\n"))


# --------------------------------------------------------------------------
# Refusals
# --------------------------------------------------------------------------


class RefusalTest(AdoptTestCase):
    def test_a_plain_directory_is_not_a_repository(self):
        plain = Path(tempfile.mkdtemp()).resolve()
        code, doc, err = self.plan(plain)
        self.assertEqual(code, 2, err)
        self.assertEqual(doc["error"]["code"], "not_a_repository")
        self.assertEqual(sorted(doc["error"]),
                         ["code", "repair_id", "violations"])
        self.assertTrue(doc["error"]["violations"])

    def test_an_absent_directory_is_not_a_repository(self):
        missing = Path(tempfile.mkdtemp()).resolve() / "absent"
        code, doc, err = self.plan(missing)
        self.assertEqual(code, 2, err)
        self.assertEqual(doc["error"]["code"], "not_a_repository")

    def test_violations_are_sorted_by_pointer(self):
        code, doc, _ = self.plan(Path(tempfile.mkdtemp()).resolve())
        self.assertEqual(code, 2)
        pointers = [v["pointer"] for v in doc["error"]["violations"]]
        self.assertEqual(pointers, sorted(pointers))

    def test_a_broken_manifest_is_adopt_failure_not_resolver_failure(self):
        home = make_home("{ not json")
        code, doc, err = self.plan(bootstrap_repo(self.home), home=home)
        self.assertEqual(code, 2, err)
        self.assertEqual(doc["error"]["code"], "adopt_failure")
        self.assertEqual(doc["error"]["repair_id"], "adopt.manifest.invalid")

    def test_an_unknown_subcommand_is_an_argparse_usage_error(self):
        code, out, _ = run("register", "--plan-id", "x", home=self.home)
        self.assertEqual(code, 2)
        self.assertEqual(out, "")

    def test_the_parser_exposes_the_three_verbs_and_nothing_else(self):
        code, out, err = run("--help", home=self.home)
        self.assertEqual(code, 0, err)
        choices = re.search(r"usage: adopt-project \[-h\] \{([^}]*)\}", out)
        self.assertEqual(choices.group(1), "plan,apply,verify")


class AdoptFailureWrapperTest(unittest.TestCase):
    """The generic wrapper, reachable only in process (D23).

    Loading the module by path and making the inspection entry point raise is
    the one monkeypatch this suite is allowed; nothing else here imports
    either script.
    """

    def load(self):
        # Each library caches in `sys.modules` under its one name, while every
        # case here runs under a temporary `HOME` of its own. The binding guard
        # checks *which* file answered the import, so a copy left behind by an
        # earlier `HOME` would fail it; a deployed run has one `HOME`.
        for name in ("agent_platform", *ADOPT_LIBRARIES):
            sys.modules.pop(name, None)
        spec = importlib.util.spec_from_file_location("adopt_project", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_an_unexpected_exception_becomes_adopt_failure(self):
        home = make_home()
        root = bootstrap_repo(home)
        module = self.load()
        buffer = io.StringIO()
        with mock.patch.dict(os.environ, {"HOME": str(home)}), \
                mock.patch.object(
                    module, "inspect_repository",
                    side_effect=RuntimeError("SECRET-TRACEBACK-TEXT")), \
                contextlib.redirect_stdout(buffer):
            code = module.main(["plan", "--repo-root", str(root)])
        self.assertEqual(code, 2)
        payload = json.loads(buffer.getvalue())
        self.assertEqual(payload["error"]["code"], "adopt_failure")
        self.assertEqual(payload["error"]["repair_id"], "adopt.internal")
        self.assertNotIn("SECRET-TRACEBACK-TEXT", buffer.getvalue())
        self.assertNotIn("RuntimeError", buffer.getvalue())


class AdoptLibraryTest(unittest.TestCase):
    """The adoption libraries refuse exactly as the platform library does.

    `adopt_inspection.py`, `adopt_planning.py`, `adopt_apply.py` and
    `adopt_verify.py` are separately installed files, so an older set can meet
    a newer binary. Every member the binary
    reads must therefore surface as `adopt.library.missing` through the D12
    error object, never as an `AttributeError` swallowed into `adopt.internal`.

    Every case runs a copy of the script from `$HOME/.agents/bin`, the deployed
    layout, because in the repository checkout the libraries are the script's
    own siblings — a run from `scripts/` imports them whatever `HOME` says and
    could never observe an uninstalled one.
    """

    def run_deployed(self, home: Path, root: Path) -> tuple[int, str, str]:
        binary = home / ".agents" / "bin" / "adopt-project"
        binary.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(SCRIPT, binary)
        env = {**os.environ, "HOME": str(home)}
        # `PYTHONPATH` would be a second lookup path the deployed machine does
        # not have; the runner's own may carry one.
        env.pop("PYTHONPATH", None)
        proc = subprocess.run(
            [sys.executable, str(binary), "plan", "--repo-root", str(root)],
            capture_output=True, text=True, timeout=300, cwd=str(home),
            env=env)
        return proc.returncode, proc.stdout, proc.stderr

    def assert_library_refusal(self, code: int, out: str, err: str) -> None:
        self.assertEqual(code, 2, err or out)
        self.assertEqual(err, "")
        payload = json.loads(out)
        self.assertEqual(sorted(payload), ["error"])
        error = payload["error"]
        self.assertEqual(sorted(error), ["code", "repair_id", "violations"])
        self.assertEqual(error["code"], "adopt_failure")
        self.assertEqual(error["repair_id"], "adopt.library.missing")
        self.assertTrue(error["violations"])
        for entry in error["violations"]:
            self.assertEqual(sorted(entry), ["message", "pointer"])

    def test_uninstalled_adoption_libraries_refuse_on_stdout(self):
        """A valid manifest and platform library are installed, so only the
        missing adoption libraries can refuse."""
        home = make_home(adopt_libraries=False)
        self.assert_library_refusal(
            *self.run_deployed(home, bootstrap_repo(home)))

    def test_a_library_missing_one_member_refuses_the_same_way(self):
        for module, tuple_name in (
                ("adopt_inspection", "ADOPT_INSPECTION_MEMBERS"),
                ("adopt_planning", "ADOPT_PLANNING_MEMBERS"),
                ("adopt_apply", "ADOPT_APPLY_MEMBERS"),
                ("adopt_verify", "ADOPT_VERIFY_MEMBERS")):
            members = declared_members(tuple_name)
            self.assertTrue(members)
            for name in members:
                with self.subTest(module=module, member=name):
                    # A module-level `del` after the definitions: the module
                    # still imports, and only this one attribute is gone.
                    home = make_home(
                        adopt_suffix={module: f"\n\ndel {name}\n"})
                    self.assert_library_refusal(
                        *self.run_deployed(home, bootstrap_repo(home)))

    def test_the_declared_members_are_exactly_the_members_used(self):
        """The guard is only as wide as its tuple: a member the binary reads
        but does not declare is a hole these cases close."""
        source = SCRIPT.read_text("utf-8")
        for module, tuple_name in (
                ("adopt_inspection", "ADOPT_INSPECTION_MEMBERS"),
                ("adopt_planning", "ADOPT_PLANNING_MEMBERS"),
                ("adopt_apply", "ADOPT_APPLY_MEMBERS"),
                ("adopt_verify", "ADOPT_VERIFY_MEMBERS")):
            with self.subTest(module=module):
                used = set(re.findall(
                    rf"\b{module}\.([A-Za-z_][A-Za-z0-9_]*)", source))
                # The module file name appears in the refusal message, not as
                # an attribute read.
                used.discard("py")
                self.assertEqual(sorted(declared_members(tuple_name)),
                                 sorted(used))

    def test_the_refusal_bytes_are_stable_across_runs(self):
        home = make_home(adopt_libraries=False)
        root = bootstrap_repo(home)
        first = self.run_deployed(home, root)
        second = self.run_deployed(home, root)
        self.assertEqual(first[0], 2)
        self.assertEqual(first[1], second[1])

    def test_the_installed_libraries_answer_in_the_deployed_layout(self):
        """The control: the same shape with both libraries installed plans."""
        home = make_home()
        code, out, err = self.run_deployed(home, bootstrap_repo(home))
        self.assertEqual(code, 0, err or out)
        self.assertEqual(json.loads(out)["plan"]["outcome"], "bootstrap")


if __name__ == "__main__":
    unittest.main()
