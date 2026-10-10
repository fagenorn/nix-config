"""Contract tests for `adopt-project` (`agent_tools.adopt_project`).

Runs `adopt-project` as `python -m agent_tools.adopt_project` under a temporary
`HOME` holding a fixture manifest. The command consumes the resolver only as a
child process of its own interpreter, `agent_tools.resolve_project` run through
`agent_tools.siblings.sibling_argv` (D26, #177 D5).

Fixture repositories are real `git init` checkouts with a hermetic identity and
`commit.gpgsign=false` in the fixture's own local config; nothing here touches
the developer's git configuration or the machine's `~/.agents`.

Two cases import package modules in process: the generic failure wrapper, which
no subprocess run can drive (D23), and the ambiguous forward step, which the
platform library refuses before the router would see it (#177 D7).
"""

from __future__ import annotations

import contextlib
import hashlib
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

from agent_tools import adopt_inspection, adopt_links, adopt_planning, adopt_project

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
TOP_LEVEL_MEMBERS = ["changes", "decisions", "evidence", "handoff",
                     "link_rewrites", "path_references", "plan",
                     "schema_version", "verification"]
PLAN_MEMBERS = ["base_revision", "blockers", "input_digest", "outcome",
                "plan_id", "platform", "project_id", "state"]
HANDOFF_MEMBERS = ["evidence_record", "migration_map", "next_command",
                   "plan_path", "repo_root", "state"]


# --------------------------------------------------------------------------
# Isolation
# --------------------------------------------------------------------------


def install_home(home: Path, manifest: object = COMMITTED) -> Path:
    """Populate `home` with the platform manifest `adopt-project` reads."""
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


def make_home(manifest: object = COMMITTED) -> Path:
    return install_home(Path(tempfile.mkdtemp()).resolve(), manifest)


def install_registry(home: Path, entries: list[dict]) -> None:
    path = home / ".agents" / "state" / "fleet" / "registry.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema_version": 1, "projects": entries}),
        encoding="utf-8")


def run(*args: str, home: Path) -> tuple[int, str, str]:
    proc = subprocess.run(
        [sys.executable, "-m", "agent_tools.adopt_project", *args],
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
    # Every standards path the contract declares, not a literal copy of one:
    # the contract is this repository's own, so a path it gains exists here too.
    for standards in contract["bindings"]["paths"]["standards"]:
        (root / standards).mkdir(parents=True, exist_ok=True)
    write(root, ".agents/project.json", json.dumps(contract, indent=2) + "\n")
    proc = subprocess.run(
        [sys.executable, "-m", "agent_tools.resolve_project", "write-projections",
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
    # This repository's GitHub release profile derives a `blocked` release
    # capability on any host without the forge adapter's executables on PATH,
    # which no conformant checkout may carry; the fixture opts out of release
    # to keep its verdict host-independent.
    scaffold(root, fixture_contract(release="unsupported"), home)
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


def record_trees_repo(home: Path) -> Path:
    """`nix_config_shape_repo` plus one tracked record under each of
    `.claude/handoffs`, `.claude/notes` and `.claude/research` (#340)."""
    root = nix_config_shape_repo(home)
    write(root, ".claude/handoffs/h.md", "# handoff h\n")
    write(root, ".claude/notes/n.md", "# note n\n")
    write(root, ".claude/research/r.md", "# research r\n")
    commit(root, "add agent records")
    return root


LINK_README_BEFORE = (
    "# readme\n"
    "\n"
    "See [spec x](.claude/specs/x.md#intro) and [plans](./.claude/plans/).\n"
    "Image: ![diagram](<.claude/specs/x.md> \"Spec x\") and [plan y][y].\n"
    "Broken: [gone](.claude/specs/missing.md). "
    "Web: [site](https://example.com/.claude/specs/x.md).\n"
    "Self: [me](README.md). Code: `[c](.claude/specs/x.md)`.\n"
    "\n"
    "~~~\n"
    "[fenced](.claude/specs/x.md)\n"
    "~~~\n"
    "\n"
    "[y]: .claude/plans/y.md \"Plan y\"\n")
LINK_README_AFTER = (
    "# readme\n"
    "\n"
    "See [spec x](.agents/artifacts/specs/x.md#intro) and "
    "[plans](./.agents/artifacts/plans/).\n"
    "Image: ![diagram](<.agents/artifacts/specs/x.md> \"Spec x\") and "
    "[plan y][y].\n"
    "Broken: [gone](.claude/specs/missing.md). "
    "Web: [site](https://example.com/.claude/specs/x.md).\n"
    "Self: [me](README.md). Code: `[c](.claude/specs/x.md)`.\n"
    "\n"
    "~~~\n"
    "[fenced](.claude/specs/x.md)\n"
    "~~~\n"
    "\n"
    "[y]: .agents/artifacts/plans/y.md \"Plan y\"\n")

# Base path -> base text, and path after the moves -> rewritten text (#345).
LINKED_BASE = {
    "README.md": LINK_README_BEFORE,
    ".claude/rules/r.md": "# rule r\n\nFollow [spec x](../specs/x.md).\n",
    ".claude/specs/x.md": (
        "# spec x\n\nBack to [readme](../../README.md), "
        "[plan y](../plans/y.md) and "
        "[rejected z](../../.out-of-scope/z.md).\n"),
}
LINKED_AFTER = {
    "README.md": LINK_README_AFTER,
    ".claude/rules/r.md": (
        "# rule r\n\nFollow [spec x](../../.agents/artifacts/specs/x.md).\n"),
    ".agents/artifacts/specs/x.md": (
        "# spec x\n\nBack to [readme](../../../README.md), "
        "[plan y](../plans/y.md) and "
        "[rejected z](../../knowledge/rejections/z.md).\n"),
}
LINKED_SOURCES = {"README.md": "README.md",
                  ".claude/rules/r.md": ".claude/rules/r.md",
                  ".agents/artifacts/specs/x.md": ".claude/specs/x.md"}
LINKED_SUMMARY = {
    "inbound": {"links": 5, "files": [".claude/rules/r.md", "README.md"]},
    "outbound": {"links": 2, "files": [".agents/artifacts/specs/x.md"]},
    "unrewritable": [],
    "already_broken": 1,
}
DISSOLVED_README = "# readme\n\nAgent records: [records](.claude/).\n"


def write_linked_tree(root: Path) -> None:
    """Inbound links from a root file and a retained `.claude/` file, and
    outbound links from a moved spec, over any fixture carrying
    `.claude/specs/x.md`, `.claude/plans/y.md` and `.out-of-scope/z.md`."""
    for path, text in LINKED_BASE.items():
        write(root, path, text)
    commit(root, "link the agent trees")


def linked_repo(home: Path) -> Path:
    root = nix_config_shape_repo(home)
    write_linked_tree(root)
    return root


CHECK_LINKS = "tools/check_links.py"
UNRELATED_SCRIPT = "tools/list_docs.py"
# A repository's own link check (#350): it exempts `.claude/`, where the
# already-broken link of `REFERENCE_TREE` lives. Line 7 holds the one path
# reference; every other token names nothing the plan moves.
CHECK_LINKS_SCRIPT = r'''#!/usr/bin/env python3
# Fail when a Markdown file outside the exempt trees has a broken relative link.
import os
import re
import sys

EXEMPT = ("docs/archive/", ".claude/")
LINK = re.compile(r"\]\(([^)#\s]+)")


def main(root):
    broken = []
    for folder, _, names in sorted(os.walk(root)):
        for name in sorted(names):
            path = os.path.relpath(os.path.join(folder, name), root)
            if not path.endswith(".md") or path.startswith(EXEMPT):
                continue
            with open(os.path.join(root, path), encoding="utf-8") as handle:
                text = handle.read()
            for target in LINK.findall(text):
                if "://" not in target and not os.path.exists(
                        os.path.join(root, os.path.dirname(path), target)):
                    broken.append(f"{path}: {target}")
    print("\n".join(broken) or "ok")
    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
'''
CHECK_LINKS_EXTENDED = CHECK_LINKS_SCRIPT.replace(
    '".claude/")',
    '".claude/", ".agents/artifacts/plans/", ".agents/artifacts/specs/")')
REFERENCE_SUBJECT = f"{CHECK_LINKS}:7:29"
REFERENCE_ROW = {
    "subject": REFERENCE_SUBJECT, "path": CHECK_LINKS, "line": 7,
    "column": 29, "literal": ".claude/", "answers": ["extend", "retain"],
    "answer": None,
    "additions": [".agents/artifacts/plans/", ".agents/artifacts/specs/"],
    "replacement": None}
REFERENCE_TREE = {
    "README.md": "# readme\n\nSee [spec x](.claude/specs/x.md).\n",
    ".claude/specs/x.md": "# spec x\n\nGone: [gone](missing.md).\n",
    ".claude/rules/r.md": "# rule r\n",
    UNRELATED_SCRIPT: 'ROOTS = ("docs/standards/", "home/")\nprint(ROOTS)\n',
}


def write_reference_tree(root: Path, *, script: bool = True) -> None:
    """An inbound link, an already-broken link inside a moved tree, retained
    `.claude/` content, an unrelated script and, with `script`, the link
    check, over any fixture carrying `.claude/specs` and `.claude/plans`."""
    for path, text in REFERENCE_TREE.items():
        write(root, path, text)
    if script:
        write(root, CHECK_LINKS, CHECK_LINKS_SCRIPT)
    commit(root, "reference the agent trees")


def referenced_repo(home: Path, *, script: bool = True) -> Path:
    root = nix_config_shape_repo(home)
    write_reference_tree(root, script=script)
    return root


def write_dissolved_tree(root: Path) -> None:
    """`.claude/` loses its last retained file and gains a research record,
    so its members move under two different prefixes and a link to the
    directory itself has no single successor (D5)."""
    git(root, "rm", "--quiet", ".claude/skills.config.json")
    write(root, ".claude/research/r.md", "# research r\n")
    write(root, "README.md", DISSOLVED_README)
    commit(root, "link the dissolving agent tree")


def candidate_repo(home: Path, *paths: str) -> Path:
    """`nix_config_shape_repo` plus tracked agent paths no row classifies."""
    root = nix_config_shape_repo(home)
    for path in paths:
        write(root, path, f"# {path}\n")
    commit(root, "add unclassified agent paths")
    return root


def ignored_symlink_repo(home: Path) -> Path:
    """`nix_config_shape_repo` plus an ignored `.claude/settings.local.json`
    that is a symlink out of the checkout: the one way an ignored candidate
    stays `needs-decision`."""
    root = nix_config_shape_repo(home)
    outside = Path(tempfile.mkdtemp()).resolve() / "settings.json"
    outside.write_text("{}\n", encoding="utf-8")
    with (root / ".gitignore").open("a", encoding="utf-8") as handle:
        handle.write(".claude/settings.local.json\n")
    (root / ".claude" / "settings.local.json").symlink_to(outside)
    commit(root, "ignore an escaping local settings link")
    return root


def tracked_symlink_repo(home: Path) -> Path:
    """`nix_config_shape_repo` plus a tracked `.claude/link.md` that is a
    symlink out of the checkout: an unclassified candidate `apply` could
    never move, because its stored operation would name an uncontained
    path."""
    root = nix_config_shape_repo(home)
    outside = Path(tempfile.mkdtemp()).resolve() / "elsewhere.md"
    outside.write_text("# outside the repository\n", encoding="utf-8")
    (root / ".claude" / "link.md").symlink_to(outside)
    commit(root, "track an escaping agent link")
    return root


LINK = ".claude/link.md"


ODD = ".claude/odd.md"
ARCHIVED = ".agents/knowledge/archive/adopted/.claude/odd.md"


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
        # The platform library refuses two records for one `from_schema`, so
        # the router's own refusal is reached at the module seam (#177 D7).
        manifest = manifest_with([1, 2], [
            {"id": "a", "from_schema": 1, "to_schema": 2},
            {"id": "b", "from_schema": 1, "to_schema": 2},
        ])
        with self.assertRaises(adopt_planning.AdoptError) as caught:
            adopt_planning.select_forward_step(manifest, 1)
        self.assertEqual(caught.exception.code, "adopt_failure")
        self.assertEqual(caught.exception.repair_id,
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
    def test_exactly_nine_top_level_members(self):
        for name, build in (("bootstrap", bootstrap_repo),
                            ("reconcile", reconcile_repo),
                            ("adopted", adopted_repo),
                            ("nix-config", nix_config_shape_repo)):
            with self.subTest(fixture=name):
                doc = self.ready_plan(build(self.home))
                self.assertEqual(sorted(doc), TOP_LEVEL_MEMBERS)
                self.assertEqual(sorted(doc["link_rewrites"]),
                                 ["already_broken", "inbound", "outbound",
                                  "unrewritable"])
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


def documented_plan_id(doc: object) -> str:
    """D15's digest, recomputed here from the document's own inputs.

    The formula is the spec's, not the implementation's: the eight named
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
        "link_rewrites": doc["link_rewrites"],
        "path_references": doc["path_references"],
    }
    payload = json.dumps(source, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


class PlanIdentityTest(AdoptTestCase):
    def test_plan_id_is_the_documented_digest_and_equals_input_digest(self):
        doc = self.ready_plan(nix_config_shape_repo(self.home))
        self.assertEqual(doc["plan"]["plan_id"], documented_plan_id(doc))
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
            "link_rewrites": doc["link_rewrites"],
            "path_references": doc["path_references"],
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

    def test_the_legacy_deploy_member_is_generated(self):
        root = nix_config_shape_repo(self.home)
        write(root, ".claude/skills.config.json",
              json.dumps({"deploy": {"adapter": "none"}, "orchestration": {"maxParallel": 2}}))
        commit(root, "carry a deploy member")
        doc = self.ready_plan(root)
        op = self.only_write(doc, ".claude/skills.config.json")
        config = {"orchestration": {"maxParallel": 2},
                  "specDir": ".agents/artifacts/specs",
                  "planDir": ".agents/artifacts/plans",
                  "rejectionsDir": ".agents/knowledge/rejections"}
        expected = json.dumps(config, indent=2, ensure_ascii=False) + "\n"
        self.assertEqual(op["after"], sha256_hash(expected.encode("utf-8")))

    def test_only_the_declared_legacy_binding_config_is_rewritten(self):
        root = nix_config_shape_repo(self.home)
        write(root, ".claude/other.config.json", json.dumps({"specDir": "x"}))
        commit(root, "add a second config")
        doc = self.ready_plan(root)
        for op in doc["changes"]:
            self.assertNotIn(".claude/other.config.json", op["targets"])


class RecordTreeClassificationTest(AdoptTestCase):
    """#340 AC1: the three record trees are classified centrally."""

    def test_the_three_record_trees_plan_to_ready(self):
        doc = self.ready_plan(record_trees_repo(self.home))
        self.assertEqual(doc["plan"]["state"], "ready",
                         doc["plan"]["blockers"])
        self.assertEqual(doc["decisions"]["open"], [])
        pairs = [(op["sources"][0], op["targets"][0])
                 for op in doc["changes"] if op["op"] == "git-mv"]
        for pair in ((".claude/handoffs/h.md",
                      ".agents/artifacts/handoffs/h.md"),
                     (".claude/notes/n.md", ".agents/artifacts/notes/n.md"),
                     (".claude/research/r.md",
                      ".agents/artifacts/specs/r.md")):
            self.assertIn(pair, pairs)
        entries = {entry["path"]: entry for entry in doc["evidence"]}
        for group, target in (
                (".claude/handoffs", ".agents/artifacts/handoffs"),
                (".claude/notes", ".agents/artifacts/notes"),
                (".claude/research", ".agents/artifacts/specs")):
            with self.subTest(group=group):
                entry = entries[group]
                self.assertEqual(
                    (entry["provenance"], entry["lifecycle_class"],
                     entry["action"], entry["target"], entry["count"]),
                    ("tracked", "durable-artifact", "move-canonical",
                     target, 1))

    def test_two_moves_into_one_destination_fail_the_destination_gate(self):
        root = nix_config_shape_repo(self.home)
        write(root, ".claude/research/x.md", "# research x\n")
        commit(root, "collide with .claude/specs/x.md")
        doc = self.ready_plan(root)
        gate = next(gate for gate in doc["verification"]["ready_gates"]
                    if gate["id"] == "no-existing-destination")
        self.assertEqual(gate, {"id": "no-existing-destination",
                                "status": "failed",
                                "repair_id": "adopt.destination.occupied"})
        self.assertEqual(doc["plan"]["state"], "draft")
        self.assertIn("no-existing-destination",
                      [blocker["id"] for blocker in doc["plan"]["blockers"]])

    def test_a_destination_inside_another_fails_the_destination_gate(self):
        root = nix_config_shape_repo(self.home)
        # `.agents/artifacts/specs/x.md` is `.claude/specs/x.md`'s destination
        # and this record's destination's parent: distinct paths, one of
        # which would have to be both a file and a directory.
        write(root, ".claude/research/x.md/r.md", "# research r\n")
        commit(root, "nest a destination inside another")
        self.assert_destination_gate_fails(self.ready_plan(root))

    def test_a_destination_under_an_existing_file_fails_the_gate(self):
        root = nix_config_shape_repo(self.home)
        write(root, ".agents/artifacts/notes", "a file, not a directory\n")
        write(root, ".claude/notes/n.md", "# note n\n")
        commit(root, "put a file where a destination's parent goes")
        self.assert_destination_gate_fails(self.ready_plan(root))

    def test_a_dangling_symlink_destination_parent_fails_the_gate(self):
        root = nix_config_shape_repo(self.home)
        (root / ".agents" / "artifacts").mkdir(parents=True, exist_ok=True)
        (root / ".agents" / "artifacts" / "notes").symlink_to("missing")
        write(root, ".claude/notes/n.md", "# note n\n")
        commit(root, "put a dangling link where a destination's parent goes")
        self.assert_destination_gate_fails(self.ready_plan(root))

    def test_a_dangling_symlink_at_a_destination_fails_the_gate(self):
        root = nix_config_shape_repo(self.home)
        notes = root / ".agents" / "artifacts" / "notes"
        notes.mkdir(parents=True, exist_ok=True)
        (notes / "n.md").symlink_to("missing")
        write(root, ".claude/notes/n.md", "# note n\n")
        commit(root, "put a dangling link where a destination goes")
        self.assert_destination_gate_fails(self.ready_plan(root))

    def test_a_symlinked_directory_destination_parent_fails_the_gate(self):
        """A link to a real directory is still a link, not a directory the
        move can create its destination in."""
        root = nix_config_shape_repo(self.home)
        write(root, "elsewhere/keep.md", "# keep\n")
        (root / ".agents" / "artifacts").mkdir(parents=True, exist_ok=True)
        (root / ".agents" / "artifacts" / "notes").symlink_to(
            "../../elsewhere", target_is_directory=True)
        write(root, ".claude/notes/n.md", "# note n\n")
        commit(root, "put a directory link where a destination's parent goes")
        self.assert_destination_gate_fails(self.ready_plan(root))

    def assert_destination_gate_fails(self, doc: object) -> None:
        gate = next(gate for gate in doc["verification"]["ready_gates"]
                    if gate["id"] == "no-existing-destination")
        self.assertEqual(gate["status"], "failed", gate)
        self.assertEqual(doc["plan"]["state"], "draft")


class CandidateQuestionTest(AdoptTestCase):
    """#340 AC2: every undecided candidate carries a stable question."""

    OPEN_MEMBERS = ["basis", "id", "impact", "recommendation", "subject",
                    "value"]

    def only_open(self, doc: object) -> dict:
        self.assertEqual(len(doc["decisions"]["open"]), 1,
                         doc["decisions"]["open"])
        entry = doc["decisions"]["open"][0]
        self.assertEqual(sorted(entry), self.OPEN_MEMBERS)
        self.assertEqual(entry["id"], "candidate-class")
        return entry

    def test_a_tracked_candidate_opens_one_archive_question(self):
        doc = self.ready_plan(candidate_repo(self.home, ".claude/odd.md"))
        entry = self.only_open(doc)
        self.assertEqual((entry["subject"], entry["value"]),
                         (".claude/odd.md", "archive-history"))
        for member in ("basis", "impact", "recommendation"):
            self.assertNotIn(".claude/odd.md", entry[member])
        self.assertEqual(doc["plan"]["state"], "draft")
        self.assertEqual(
            sorted(blocker["id"] for blocker in doc["plan"]["blockers"]),
            ["no-needs-decision", "no-open-decisions"])

    def test_the_prose_is_fixed_across_candidates(self):
        doc = self.ready_plan(candidate_repo(
            self.home, ".claude/zeta/b.md", ".claude/a.md"))
        entries = doc["decisions"]["open"]
        self.assertEqual([entry["subject"] for entry in entries],
                         [".claude/a.md", ".claude/zeta/b.md"])
        for member in ("basis", "impact", "recommendation"):
            self.assertEqual(entries[0][member], entries[1][member])

    def test_a_secret_shaped_candidate_has_no_answer(self):
        doc = self.ready_plan(candidate_repo(
            self.home, ".claude/secrets/key.md"))
        entry = self.only_open(doc)
        self.assertEqual(entry["subject"], ".claude/secrets/key.md")
        self.assertIsNone(entry["value"])

    def test_a_tracked_symlink_out_of_the_repository_has_no_answer(self):
        doc = self.ready_plan(tracked_symlink_repo(self.home))
        entry = self.only_open(doc)
        self.assertEqual((entry["subject"], entry["value"]), (LINK, None))

    def test_an_ignored_candidate_is_offered_retention(self):
        doc = self.ready_plan(ignored_symlink_repo(self.home))
        entry = self.only_open(doc)
        self.assertEqual((entry["subject"], entry["value"]),
                         (".claude/settings.local.json", "retain-product"))

    def test_project_id_sorts_before_candidate_questions(self):
        root = reconcile_repo(self.home, remotes=())
        write(root, ".claude/odd.md", "# odd\n")
        commit(root, "add an unclassified agent path")
        doc = self.ready_plan(root)
        self.assertEqual([entry["id"] for entry in doc["decisions"]["open"]],
                         ["project-id", "candidate-class"])
        self.assertEqual(sorted(doc["decisions"]["open"][0]),
                         ["basis", "id", "impact", "recommendation", "value"])

    def test_the_human_view_names_each_subject_and_its_answer(self):
        root = candidate_repo(self.home, ".claude/odd.md",
                              ".claude/secrets/key.md")
        code, human, err = run("plan", "--repo-root", str(root),
                               "--format", "human", home=self.home)
        self.assertEqual(code, 0, err)
        self.assertIn("open candidate-class .claude/odd.md "
                      "(answer: archive-history): ", human)
        self.assertIn("open candidate-class .claude/secrets/key.md "
                      "(answer: none): ", human)

    def test_the_question_set_is_closed(self):
        self.assertEqual(adopt_inspection.QUESTION_IDS,
                         ("project-id", "candidate-class", "path-reference"))
        for function in (adopt_inspection.question_impact,
                         adopt_inspection.question_recommendation):
            with self.subTest(function=function.__name__):
                with self.assertRaises(ValueError):
                    function("candidate-class:.claude/odd.md")
        with self.assertRaises(ValueError):
            adopt_inspection.candidate_answer("untracked-explicit-paths",
                                              ".claude/odd.md", True)


class CandidateAnswerTest(AdoptTestCase):
    """#340 AC2: answering a candidate is reflected in the plan id."""

    def answered(self, root: Path, *triples: tuple[str, str, str]):
        args = [token for triple in triples
                for token in ("--answer", *triple)]
        return self.plan(root, *args)

    def stored_plans(self) -> list[str]:
        store = self.home / ".agents" / "state" / "adopt" / "plans"
        return sorted(path.name for path in store.iterdir()) \
            if store.is_dir() else []

    def refused(self, root: Path, repair_id: str,
                *triples: tuple[str, str, str]) -> None:
        before = self.stored_plans()
        code, payload, err = self.answered(root, *triples)
        self.assertEqual(code, 2, err or payload)
        self.assertEqual(payload["error"]["code"], "adopt_failure")
        self.assertEqual(payload["error"]["repair_id"], repair_id)
        self.assertEqual(payload["error"]["violations"][0]["pointer"],
                         "/decisions/answered")
        self.assertEqual(self.stored_plans(), before)

    def first_violation(self, root: Path, *triples) -> tuple[str, dict]:
        code, payload, err = self.answered(root, *triples)
        self.assertEqual(code, 2, err or payload)
        return (payload["error"]["repair_id"],
                payload["error"]["violations"][0])

    def test_answering_reaches_ready_and_changes_the_plan_id(self):
        root = candidate_repo(self.home, ODD)
        draft = self.ready_plan(root)
        code, doc, err = self.answered(
            root, ("candidate-class", ODD, "archive-history"))
        self.assertEqual(code, 0, err)
        self.assertNotEqual(doc["plan"]["plan_id"], draft["plan"]["plan_id"])
        self.assertEqual(doc["plan"]["state"], "ready",
                         doc["plan"]["blockers"])
        self.assertEqual(doc["decisions"]["open"], [])
        self.assertEqual(doc["decisions"]["answered"], [
            {"id": "candidate-class", "subject": ODD,
             "value": "archive-history"}])
        # The independent oracle, with every other digest input held
        # constant: the id covers the non-empty answers, and the same
        # document with no answers digests differently.
        self.assertEqual(doc["plan"]["plan_id"], documented_plan_id(doc))
        unanswered = {**doc, "decisions": {**doc["decisions"],
                                           "answered": []}}
        self.assertNotEqual(doc["plan"]["plan_id"],
                            documented_plan_id(unanswered))
        entry = next(e for e in doc["evidence"] if e["path"] == ODD)
        self.assertEqual(
            (entry["lifecycle_class"], entry["action"], entry["target"]),
            ("unclassified", "archive-history", ARCHIVED))
        pairs = [(op["sources"][0], op["targets"][0])
                 for op in doc["changes"] if op["op"] == "git-mv"]
        self.assertIn((ODD, ARCHIVED), pairs)

    def test_an_answered_ignored_candidate_is_retained_without_an_operation(self):
        path = ".claude/settings.local.json"
        code, doc, err = self.answered(
            ignored_symlink_repo(self.home),
            ("candidate-class", path, "retain-product"))
        self.assertEqual(code, 0, err)
        self.assertEqual(doc["plan"]["state"], "ready",
                         doc["plan"]["blockers"])
        self.assertEqual(doc["decisions"]["open"], [])
        entry = next(e for e in doc["evidence"] if e["path"] == path)
        self.assertEqual((entry["action"], entry["target"]),
                         ("retain-product", None))
        for op in doc["changes"]:
            self.assertNotIn(path, op["sources"] + op["targets"])

    def test_a_non_candidate_question_id_is_an_invalid_answer(self):
        self.refused(candidate_repo(self.home, ODD),
                     "adopt.decisions.invalid_answer",
                     ("project-id", ODD, "archive-history"))

    def test_a_value_the_question_does_not_offer_is_an_invalid_answer(self):
        self.refused(candidate_repo(self.home, ODD),
                     "adopt.decisions.invalid_answer",
                     ("candidate-class", ODD, "retain-product"))

    def test_every_answer_to_a_secret_shaped_candidate_is_invalid(self):
        root = candidate_repo(self.home, ".claude/secrets/key.md")
        for value in ("archive-history", "retain-product"):
            with self.subTest(value=value):
                self.refused(root, "adopt.decisions.invalid_answer",
                             ("candidate-class", ".claude/secrets/key.md",
                              value))

    def test_archiving_a_tracked_symlink_out_of_the_repository_is_invalid(self):
        root = tracked_symlink_repo(self.home)
        for value in ("archive-history", "retain-product"):
            with self.subTest(value=value):
                self.refused(root, "adopt.decisions.invalid_answer",
                             ("candidate-class", LINK, value))

    def test_one_subject_answered_twice_is_an_invalid_answer(self):
        self.refused(candidate_repo(self.home, ODD),
                     "adopt.decisions.invalid_answer",
                     ("candidate-class", ODD, "archive-history"),
                     ("candidate-class", ODD, "archive-history"))

    def test_a_subject_that_is_not_an_undecided_candidate_is_unmatched(self):
        root = candidate_repo(self.home, ODD)
        for subject in (".claude/missing.md", ".claude/specs/x.md"):
            with self.subTest(subject=subject):
                self.refused(root, "adopt.decisions.unmatched_answer",
                             ("candidate-class", subject, "archive-history"))

    def test_the_human_view_prints_the_answer(self):
        root = candidate_repo(self.home, ODD)
        code, human, err = run(
            "plan", "--repo-root", str(root), "--format", "human",
            "--answer", "candidate-class", ODD, "archive-history",
            home=self.home)
        self.assertEqual(code, 0, err)
        self.assertIn(f"answered candidate-class {ODD}: archive-history\n",
                      human)

    def test_answer_order_on_the_command_line_does_not_matter(self):
        root = candidate_repo(self.home, ODD, ".claude/a.md")
        first = ("candidate-class", ".claude/a.md", "archive-history")
        second = ("candidate-class", ODD, "archive-history")
        forward = run("plan", "--repo-root", str(root), "--answer", *first,
                      "--answer", *second, home=self.home)
        backward = run("plan", "--repo-root", str(root), "--answer", *second,
                       "--answer", *first, home=self.home)
        self.assertEqual(forward[0], 0, forward[2])
        self.assertEqual(forward[1], backward[1])

    def test_competing_violations_report_the_sorted_first_one(self):
        root = candidate_repo(self.home, ODD)
        bad_id = ("project-id", ODD, "archive-history")
        unmatched = ("candidate-class", ".claude/missing.md",
                     "archive-history")
        expected = ("adopt.decisions.unmatched_answer",
                    {"pointer": "/decisions/answered",
                     "message": "the answered subject is not an undecided "
                                "candidate of this inspection"})
        for triples in ((bad_id, unmatched), (unmatched, bad_id)):
            with self.subTest(triples=triples):
                self.assertEqual(self.first_violation(root, *triples),
                                 expected)

    def test_a_duplicate_subject_is_reported_before_its_value(self):
        root = candidate_repo(self.home, ODD)
        good = ("candidate-class", ODD, "archive-history")
        bad = ("candidate-class", ODD, "retain-product")
        expected = ("adopt.decisions.invalid_answer",
                    {"pointer": "/decisions/answered",
                     "message": "a candidate is answered more than once"})
        for triples in ((good, bad), (bad, good)):
            with self.subTest(triples=triples):
                self.assertEqual(self.first_violation(root, *triples),
                                 expected)

    def test_the_recommendation_names_the_answer_flag(self):
        self.assertIn("plan --answer candidate-class <subject> <value>",
                      adopt_inspection.question_recommendation(
                          "candidate-class"))

    def test_archive_history_relocates(self):
        self.assertTrue(adopt_inspection.action_relocates("archive-history"))


class LinkRewritePlanTest(AdoptTestCase):
    """#345: `plan` rewrites relative Markdown links across the moves."""

    def link_writes(self, doc: object) -> list[dict]:
        return [op for op in doc["changes"] if op["op"] == "write-file"
                and op["targets"][0] in LINKED_AFTER]

    def test_the_linked_fixture_plans_to_ready_with_the_rewrites(self):
        doc = self.ready_plan(linked_repo(self.home))
        self.assertEqual(doc["plan"]["state"], "ready",
                         doc["plan"]["blockers"])
        writes = self.link_writes(doc)
        self.assertEqual([op["targets"] for op in writes],
                         [[".agents/artifacts/specs/x.md"],
                          [".claude/rules/r.md"], ["README.md"]])
        for op in writes:
            target = op["targets"][0]
            self.assertEqual(op["sources"], [target])
            self.assertEqual(op["before"], sha256_hash(
                LINKED_BASE[LINKED_SOURCES[target]].encode("utf-8")))
            self.assertEqual(op["after"], sha256_hash(
                LINKED_AFTER[target].encode("utf-8")))
        order = [(op["op"], op["targets"][0] if op["targets"] else None)
                 for op in doc["changes"]]
        legacy = order.index(("write-file", ".claude/skills.config.json"))
        first = order.index(("write-file", ".agents/artifacts/specs/x.md"))
        projections = [index for index, (kind, _) in enumerate(order)
                       if kind == "regenerate-projection"]
        self.assertLess(legacy, first)
        self.assertTrue(projections)
        self.assertLess(first + 2, min(projections))

    def test_anchors_titles_and_reference_definitions_survive_and_urls_stay(self):
        doc = self.ready_plan(linked_repo(self.home))
        readme = next(op for op in self.link_writes(doc)
                      if op["targets"] == ["README.md"])
        self.assertEqual(readme["after"], sha256_hash(
            LINK_README_AFTER.encode("utf-8")))
        before = [link.target
                  for link in adopt_links.links(LINK_README_BEFORE)]
        after = [link.target for link in adopt_links.links(LINK_README_AFTER)]
        self.assertEqual(list(zip(before, after)), [
            (".claude/specs/x.md#intro", ".agents/artifacts/specs/x.md#intro"),
            ("./.claude/plans/", "./.agents/artifacts/plans/"),
            (".claude/specs/x.md", ".agents/artifacts/specs/x.md"),
            (".claude/specs/missing.md", ".claude/specs/missing.md"),
            ("https://example.com/.claude/specs/x.md",
             "https://example.com/.claude/specs/x.md"),
            ("README.md", "README.md"),
            (".claude/plans/y.md", ".agents/artifacts/plans/y.md"),
        ])

    def test_the_summary_is_published_and_enters_the_plan_id(self):
        doc = self.ready_plan(linked_repo(self.home))
        self.assertEqual(doc["link_rewrites"], LINKED_SUMMARY)
        self.assertEqual(doc["plan"]["plan_id"], documented_plan_id(doc))

    def test_a_different_rewrite_set_is_a_different_plan_id(self):
        doc = self.ready_plan(linked_repo(self.home))
        inputs = (doc["plan"]["project_id"], doc["plan"]["base_revision"],
                  doc["plan"]["platform"], doc["evidence"],
                  doc["decisions"]["answered"])
        self.assertEqual(
            adopt_planning.compute_plan_id(*inputs, doc["link_rewrites"],
                                           doc["path_references"]),
            doc["plan"]["plan_id"])
        other = json.loads(json.dumps(LINKED_SUMMARY))
        other["inbound"] = {"links": 4, "files": ["README.md"]}
        self.assertNotEqual(
            adopt_planning.compute_plan_id(*inputs, other,
                                           doc["path_references"]),
            doc["plan"]["plan_id"])

    def test_the_human_view_prints_one_link_line(self):
        code, out, err = run("plan", "--repo-root",
                             str(linked_repo(self.home)), "--format", "human",
                             home=self.home)
        self.assertEqual(code, 0, err)
        self.assertIn("\nlinks: inbound 5 in 2 files, outbound 2 in 1 files, "
                      "unrewritable 0, already broken 1\n", out)

    def test_a_dissolved_directory_link_keeps_the_plan_draft(self):
        root = nix_config_shape_repo(self.home)
        write_dissolved_tree(root)
        code, doc, err = self.plan(root)
        self.assertEqual(code, 0, err)
        self.assertEqual(doc["plan"]["state"], "draft")
        self.assertEqual(
            [gate for gate in doc["verification"]["ready_gates"]
             if gate["status"] == "failed"],
            [{"id": "no-unrewritable-link", "status": "failed",
              "repair_id": "adopt.link.unrewritable"}])
        self.assertEqual(doc["link_rewrites"]["unrewritable"],
                         [{"path": "README.md", "target": ".claude/"}])
        self.assertIn(
            {"id": "no-unrewritable-link",
             "message": "a relative Markdown link into or out of a moved "
                        "path cannot be rewritten to resolve to the same "
                        "target"},
            doc["plan"]["blockers"])

    def test_the_link_gate_is_the_last_ready_gate(self):
        self.assertEqual(adopt_inspection.READY_GATES[-2:],
                         ("no-secret-path-in-moves", "no-unrewritable-link"))

    def test_a_markdown_file_any_other_operation_names_is_a_derivation_bug(self):
        op = adopt_planning.operation
        link = op("write-file", ["README.md"], ["README.md"],
                  "sha256:" + "0" * 64, "sha256:" + "1" * 64)
        adopt_planning.check_markdown_writes([link], {"README.md"})
        delete = op("delete-file", ["notes.md"], [],
                    "git-object:" + "0" * 40, None)
        for changes, targets in (([link], set()),
                                 ([link, link], {"README.md"}),
                                 ([], {"README.md"}),
                                 ([delete], set())):
            with self.subTest(changes=changes, targets=targets):
                with self.assertRaises(ValueError):
                    adopt_planning.check_markdown_writes(changes, targets)


class PathReferencePlanTest(AdoptTestCase):
    """#350: `plan` asks about every path literal naming a moved tree."""

    def answered(self, root: Path, value: str,
                 subject: str = REFERENCE_SUBJECT) -> object:
        code, doc, err = self.plan(root, "--answer", "path-reference",
                                   subject, value)
        self.assertEqual(code, 0, err or doc)
        return doc

    def stored_plans(self) -> list[str]:
        store = self.home / ".agents" / "state" / "adopt" / "plans"
        return sorted(path.name for path in store.iterdir()) \
            if store.is_dir() else []

    def naming(self, doc: object, path: str) -> list[dict]:
        return [op for op in doc["changes"]
                if path in op["sources"] + op["targets"]]

    def test_an_open_reference_keeps_the_plan_draft_with_a_stable_question(self):
        root = referenced_repo(self.home)
        doc = self.ready_plan(root)
        self.assertEqual(doc["plan"]["state"], "draft")
        self.assertEqual(
            [gate["id"] for gate in doc["verification"]["ready_gates"]
             if gate["status"] != "passed"], ["no-open-decisions"])
        (question,) = [entry for entry in doc["decisions"]["open"]
                       if entry["id"] == "path-reference"]
        self.assertEqual(sorted(question), ["answers", "basis", "id", "impact",
                                            "recommendation", "subject"])
        self.assertEqual(question["subject"], REFERENCE_SUBJECT)
        self.assertEqual(question["answers"], ["extend", "retain"])
        for member in ("basis", "impact", "recommendation"):
            self.assertNotIn("tools/", question[member])
        self.assertEqual(doc["path_references"], [REFERENCE_ROW])
        self.assertEqual(self.naming(doc, CHECK_LINKS), [])
        self.assertEqual(doc["plan"]["plan_id"], documented_plan_id(doc))
        again = self.ready_plan(root)
        self.assertEqual(again["decisions"]["open"], doc["decisions"]["open"])
        self.assertEqual(again["plan"]["plan_id"], doc["plan"]["plan_id"])

    def test_answering_extend_reaches_ready_with_one_write(self):
        doc = self.answered(referenced_repo(self.home), "extend")
        self.assertEqual(doc["plan"]["state"], "ready",
                         doc["plan"]["blockers"])
        self.assertEqual(doc["decisions"]["open"], [])
        self.assertEqual(doc["decisions"]["answered"],
                         [{"id": "path-reference",
                           "subject": REFERENCE_SUBJECT, "value": "extend"}])
        self.assertEqual(doc["path_references"],
                         [{**REFERENCE_ROW, "answer": "extend"}])
        (write_op,) = self.naming(doc, CHECK_LINKS)
        self.assertEqual(write_op["op"], "write-file")
        self.assertEqual(write_op["sources"], [CHECK_LINKS])
        self.assertEqual(write_op["targets"], [CHECK_LINKS])
        self.assertEqual(write_op["before"],
                         sha256_hash(CHECK_LINKS_SCRIPT.encode("utf-8")))
        self.assertEqual(write_op["after"],
                         sha256_hash(CHECK_LINKS_EXTENDED.encode("utf-8")))
        order = [(op["op"], op["targets"][0] if op["targets"] else None)
                 for op in doc["changes"]]
        script = order.index(("write-file", CHECK_LINKS))
        self.assertLess(order.index(("write-file", "README.md")), script)
        self.assertLess(script, min(
            index for index, (kind, _) in enumerate(order)
            if kind == "regenerate-projection"))
        self.assertEqual(doc["plan"]["plan_id"], documented_plan_id(doc))

    def test_retain_reaches_ready_and_writes_nothing(self):
        doc = self.answered(referenced_repo(self.home), "retain")
        self.assertEqual(doc["plan"]["state"], "ready",
                         doc["plan"]["blockers"])
        self.assertEqual(doc["path_references"],
                         [{**REFERENCE_ROW, "answer": "retain"}])
        self.assertEqual(self.naming(doc, CHECK_LINKS), [])

    def test_the_answer_is_covered_by_the_plan_id(self):
        root = referenced_repo(self.home)
        opened = self.ready_plan(root)
        extended = self.answered(root, "extend")
        retained = self.answered(root, "retain")
        self.assertEqual(len({doc["plan"]["plan_id"]
                              for doc in (opened, extended, retained)}), 3)
        inputs = (extended["plan"]["project_id"],
                  extended["plan"]["base_revision"],
                  extended["plan"]["platform"], extended["evidence"],
                  extended["decisions"]["answered"],
                  extended["link_rewrites"])
        self.assertEqual(
            adopt_planning.compute_plan_id(*inputs,
                                           extended["path_references"]),
            extended["plan"]["plan_id"])
        other = [{**extended["path_references"][0],
                  "additions": [".agents/artifacts/specs/"]}]
        self.assertNotEqual(adopt_planning.compute_plan_id(*inputs, other),
                            extended["plan"]["plan_id"])

    def test_markdown_rewriting_is_unchanged_and_other_files_are_untouched(self):
        def markdown_writes(doc: object) -> list[tuple]:
            return [(op["targets"], op["before"], op["after"])
                    for op in doc["changes"] if op["op"] == "write-file"
                    and adopt_links.is_markdown_path(op["targets"][0])]

        with_script = self.answered(referenced_repo(self.home), "extend")
        without = self.ready_plan(referenced_repo(self.home, script=False))
        self.assertEqual(without["plan"]["state"], "ready",
                         without["plan"]["blockers"])
        self.assertEqual(without["path_references"], [])
        self.assertTrue(markdown_writes(without))
        self.assertEqual(markdown_writes(with_script),
                         markdown_writes(without))
        self.assertEqual(with_script["link_rewrites"],
                         without["link_rewrites"])
        self.assertEqual(self.naming(with_script, UNRELATED_SCRIPT), [])
        self.assertEqual(
            [op["targets"] for op in with_script["changes"]
             if op["op"] == "write-file"
             and op["targets"][0].startswith("tools/")], [[CHECK_LINKS]])

    def test_invalid_reference_answers_refuse_and_store_nothing(self):
        root = referenced_repo(self.home)
        ok = ("path-reference", REFERENCE_SUBJECT, "extend")
        for triples, repair_id in (
                ((("path-reference", f"{CHECK_LINKS}:1:1", "retain"),),
                 "adopt.decisions.unmatched_answer"),
                ((("path-reference", REFERENCE_SUBJECT, "rewrite"),),
                 "adopt.decisions.invalid_answer"),
                ((ok, ("path-reference", REFERENCE_SUBJECT, "retain")),
                 "adopt.decisions.invalid_answer"),
                ((ok, ("path-ref", REFERENCE_SUBJECT, "retain")),
                 "adopt.decisions.invalid_answer")):
            with self.subTest(triples=triples):
                before = self.stored_plans()
                code, payload, err = self.plan(root, *[
                    token for triple in triples
                    for token in ("--answer", *triple)])
                self.assertEqual(code, 2, err or payload)
                self.assertEqual(payload["error"]["code"], "adopt_failure")
                self.assertEqual(payload["error"]["repair_id"], repair_id)
                self.assertEqual(
                    payload["error"]["violations"][0]["pointer"],
                    "/decisions/answered")
                self.assertEqual(self.stored_plans(), before)

    def test_the_human_view_prints_the_references(self):
        root = referenced_repo(self.home)
        code, out, err = run("plan", "--repo-root", str(root), "--format",
                             "human", home=self.home)
        self.assertEqual(code, 0, err)
        self.assertIn("\nreferences: 1 occurrences, extended 0, rewritten 0, "
                      "retained 0, open 1\n", out)
        self.assertIn(f"\nopen path-reference {REFERENCE_SUBJECT} "
                      "(answers: extend|retain): ", out)
        code, out, err = run("plan", "--repo-root", str(root), "--format",
                             "human", "--answer", "path-reference",
                             REFERENCE_SUBJECT, "extend", home=self.home)
        self.assertEqual(code, 0, err)
        self.assertIn("\nreferences: 1 occurrences, extended 1, rewritten 0, "
                      "retained 0, open 0\n", out)

    def test_a_reference_to_an_answered_candidate_is_asked_in_either_answer_order(self):
        # Line 1 of the file holds `PATHS = [".claude/odd.md"]`: the quote
        # opens in column 10, so the literal starts in column 11.
        naming_file = "tools/odd_paths.py"
        subject = f"{naming_file}:1:11"
        root = candidate_repo(self.home, ODD)
        write(root, naming_file, f'PATHS = ["{ODD}"]\n')
        commit(root, "name the candidate")
        candidate = ("candidate-class", ODD, "archive-history")
        reference = ("path-reference", subject, "rewrite")

        def questions(doc: object, question_id: str) -> list[dict]:
            return [entry for entry in doc["decisions"]["open"]
                    if entry["id"] == question_id]

        unanswered = self.ready_plan(root)
        self.assertEqual(len(questions(unanswered, "candidate-class")), 1)
        self.assertEqual(questions(unanswered, "path-reference"), [])
        self.assertEqual(unanswered["path_references"], [])

        code, archived, err = self.plan(root, "--answer", *candidate)
        self.assertEqual(code, 0, err or archived)
        self.assertEqual(archived["plan"]["state"], "draft")
        (question,) = questions(archived, "path-reference")
        self.assertEqual(question["subject"], subject)
        self.assertEqual(question["answers"],
                         ["extend", "rewrite", "retain"])
        self.assertEqual(len(archived["decisions"]["open"]), 1)
        (row,) = archived["path_references"]
        self.assertEqual((row["subject"], row["literal"], row["answer"]),
                         (subject, ODD, None))

        results = []
        for triples in ((candidate, reference), (reference, candidate)):
            code, doc, err = self.plan(root, *[
                token for triple in triples
                for token in ("--answer", *triple)])
            self.assertEqual(code, 0, err or doc)
            self.assertEqual(doc["plan"]["state"], "ready",
                             doc["plan"]["blockers"])
            results.append(doc)
        first, second = results
        self.assertEqual(first["path_references"], second["path_references"])
        self.assertEqual(first["path_references"][0]["answer"], "rewrite")
        self.assertEqual(first["plan"]["plan_id"], second["plan"]["plan_id"])
        (write_op,) = self.naming(first, naming_file)
        self.assertEqual(write_op["after"], sha256_hash(
            f'PATHS = ["{ARCHIVED}"]\n'.encode("utf-8")))

    def test_a_reference_target_any_other_operation_names_is_a_derivation_bug(self):
        op = adopt_planning.operation
        target = "tools/check_links.py"
        write_op = op("write-file", [target], [target],
                      "sha256:" + "0" * 64, "sha256:" + "1" * 64)
        adopt_planning.check_reference_writes([write_op], {target})
        delete = op("delete-file", [target], [],
                    "git-object:" + "0" * 40, None)
        move = op("git-mv", [target], ["tools/moved.py"],
                  "git-object:" + "0" * 40, "git-object:" + "0" * 40)
        different = op("write-file", ["tools/other.py"], [target],
                       "sha256:" + "0" * 64, "sha256:" + "1" * 64)
        for changes in ([], [write_op, write_op], [write_op, delete],
                        [write_op, move], [different]):
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):
                    adopt_planning.check_reference_writes(changes, {target})


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

    Importing `agent_tools.adopt_project` and making the inspection entry point
    raise is the one monkeypatch this suite is allowed.
    """

    def test_an_unexpected_exception_becomes_adopt_failure(self):
        home = make_home()
        root = bootstrap_repo(home)
        buffer = io.StringIO()
        with mock.patch.dict(os.environ, {"HOME": str(home)}), \
                mock.patch.object(
                    adopt_project, "inspect_repository",
                    side_effect=RuntimeError("SECRET-TRACEBACK-TEXT")), \
                contextlib.redirect_stdout(buffer):
            code = adopt_project.main(["plan", "--repo-root", str(root)])
        self.assertEqual(code, 2)
        payload = json.loads(buffer.getvalue())
        self.assertEqual(payload["error"]["code"], "adopt_failure")
        self.assertEqual(payload["error"]["repair_id"], "adopt.internal")
        self.assertNotIn("SECRET-TRACEBACK-TEXT", buffer.getvalue())
        self.assertNotIn("RuntimeError", buffer.getvalue())


if __name__ == "__main__":
    unittest.main()
