"""Contract tests for the conformance side of `adopt-project plan`.

The pure lock, input-declaration and protection edits, and the plan's conformance member and gate
for a project with a devenv lock (ADR-project-contract-018). The cases live beside
`test_adopt_project.py` because that file is over its size limit and may not grow; its fixtures
and case base are imported from it, and the fixtures the conformance cases share are defined here.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

from agent_tools.project_contract import (adopt_conformance, adopt_planning, adopt_project,
                                          derived_values)

from ._inprocess_cli import run_module
from .test_adopt_project import (
    MANIFEST,
    PLAN_MEMBERS,
    REPO_ROOT,
    AdoptTestCase,
    _resolver_in_process,
    adopted_repo,
    bootstrap_repo,
    commit,
    documented_plan_id,
    drafted_contract,
    git,
    make_home,
    nix_config_shape_repo,
    run,
    sha256_hash,
    write,
)

TIER = "integration"  # every plan case runs a real git repository


# --------------------------------------------------------------------------
# The conformance file edits (pure functions of bytes)
# --------------------------------------------------------------------------

FIXTURE_REVISION = {
    "type": "github", "owner": "fixture", "repo": "platform", "rev": "0f" * 20,
    "narHash": "sha256-" + "A" * 43 + "=", "lastModified": 1700000000,
}
DEVENV_YAML = "inputs:\n  nixpkgs:\n    url: github:cachix/devenv-nixpkgs/rolling\n"
DEVENV_YAML_DECLARED = (DEVENV_YAML + "  agent-platform:\n"
                        "    url: github:fixture/platform\n    flake: false\n")
DEVENV_LOCK = json.dumps({
    "nodes": {
        "nixpkgs": {
            "locked": {"lastModified": 1, "narHash": "sha256-" + "B" * 43 + "=",
                       "owner": "cachix", "repo": "devenv-nixpkgs",
                       "rev": "ab" * 20, "type": "github"},
            "original": {"owner": "cachix", "repo": "devenv-nixpkgs",
                         "type": "github"},
        },
        "root": {"inputs": {"nixpkgs": "nixpkgs"}},
    },
    "root": "root",
    "version": 7,
}, indent=2, sort_keys=True)


def locked_platform_node(revision: dict) -> dict:
    return {"flake": False, "locked": revision,
            "original": {"owner": revision["owner"], "repo": revision["repo"],
                         "type": "github"}}


def lock_bytes(document: dict) -> bytes:
    return json.dumps(document, indent=2, sort_keys=True).encode()


class LockEntryTest(unittest.TestCase):
    def lock(self) -> dict:
        return json.loads(DEVENV_LOCK)

    def test_a_lock_gains_the_platform_node_and_root_input(self):
        entry = adopt_conformance.lock_with_platform(
            DEVENV_LOCK.encode(), FIXTURE_REVISION)
        expected = self.lock()
        expected["nodes"]["agent-platform"] = locked_platform_node(FIXTURE_REVISION)
        expected["nodes"]["root"]["inputs"]["agent-platform"] = "agent-platform"
        self.assertIs(entry.kept, False)
        self.assertEqual(entry.node, "agent-platform")
        self.assertEqual(entry.locked, FIXTURE_REVISION)
        self.assertEqual(json.loads(entry.after), expected)
        self.assertTrue(entry.after.endswith(b"}"))

    def test_the_lock_keeps_its_bytes_style(self):
        for name, ending in (("devenv.lock", b"}"), ("flake.lock", b"}\n")):
            with self.subTest(name):
                data = (REPO_ROOT / name).read_bytes()
                entry = adopt_conformance.lock_with_platform(data, FIXTURE_REVISION)
                expected = json.loads(data)
                root = expected["nodes"][expected["root"]]
                expected["nodes"]["agent-platform"] = locked_platform_node(FIXTURE_REVISION)
                root.setdefault("inputs", {})["agent-platform"] = "agent-platform"
                self.assertEqual(json.loads(entry.after), expected)
                self.assertEqual(entry.after, json.dumps(
                    expected, indent=2, sort_keys=True, ensure_ascii=False).encode()
                    + (b"\n" if ending.endswith(b"\n") else b""))
                self.assertTrue(entry.after.endswith(ending))
                self.assertEqual(entry.after.endswith(b"\n"), data.endswith(b"\n"))

    def test_a_taken_node_name_gets_the_next_free_key(self):
        document = self.lock()
        document["nodes"]["agent-platform"] = {"flake": False, "locked": {}}
        entry = adopt_conformance.lock_with_platform(lock_bytes(document), FIXTURE_REVISION)
        self.assertEqual(entry.node, "agent-platform_2")
        result = json.loads(entry.after)
        self.assertEqual(result["nodes"]["root"]["inputs"]["agent-platform"],
                         "agent-platform_2")
        self.assertEqual(result["nodes"]["agent-platform"],
                         document["nodes"]["agent-platform"])
        self.assertEqual(result["nodes"]["agent-platform_2"],
                         locked_platform_node(FIXTURE_REVISION))

    def test_a_well_formed_entry_is_kept_as_found(self):
        document = self.lock()
        found = {**FIXTURE_REVISION, "rev": "1e" * 20}
        document["nodes"]["agent-platform"] = locked_platform_node(found)
        document["nodes"]["root"]["inputs"]["agent-platform"] = "agent-platform"
        entry = adopt_conformance.lock_with_platform(lock_bytes(document), FIXTURE_REVISION)
        self.assertIsNone(entry.after)
        self.assertIs(entry.kept, True)
        self.assertEqual(entry.locked["rev"], "1e" * 20)

    def test_an_existing_entry_out_of_shape_is_never_replaced(self):
        def variant(mutate, reference="agent-platform"):
            document = self.lock()
            document["nodes"]["agent-platform"] = locked_platform_node(dict(FIXTURE_REVISION))
            document["nodes"]["root"]["inputs"]["agent-platform"] = reference
            mutate(document["nodes"]["agent-platform"])
            return lock_bytes(document)

        def drop_nar_hash(node):
            del node["locked"]["narHash"]

        cases = {
            "a follows path": variant(lambda node: None, ["nixpkgs"]),
            "a missing node": variant(lambda node: None, "absent"),
            "flake true": variant(lambda node: node.update(flake=True)),
            "no narHash": variant(drop_nar_hash),
            "git type": variant(lambda node: node["locked"].update(type="git")),
            "repo differs": variant(lambda node: node["original"].update(repo="other")),
        }
        for name, data in cases.items():
            with self.subTest(name):
                with self.assertRaises(adopt_conformance.Undeclarable) as caught:
                    adopt_conformance.lock_with_platform(data, FIXTURE_REVISION)
                self.assertEqual(caught.exception.repair_id,
                                 adopt_conformance.LOCK_ENTRY_INCOMPATIBLE)

    def test_a_lock_out_of_shape_is_unreadable(self):
        def with_root_inputs(value):
            document = self.lock()
            document["nodes"]["root"]["inputs"] = value
            return lock_bytes(document)

        cases = {
            "not json": b"not json",
            "a list": b"[]",
            "no nodes": b'{"root": "root"}',
            "no root": b'{"nodes": {"root": {}}}',
            "root not a string": b'{"nodes": {"root": {}}, "root": 1}',
            "root names no node": b'{"nodes": {}, "root": "root"}',
            "root inputs a list": with_root_inputs(["nixpkgs"]),
            "duplicate keys": b'{"nodes": {}, "nodes": {}, "root": "root"}',
            "invalid utf-8": b'{"nodes": {"root": {}}, "root": "\xff"}',
        }
        for name, data in cases.items():
            with self.subTest(name):
                with self.assertRaises(adopt_conformance.Undeclarable) as caught:
                    adopt_conformance.lock_with_platform(data, FIXTURE_REVISION)
                self.assertEqual(caught.exception.repair_id,
                                 adopt_conformance.LOCK_UNREADABLE)


class InputDeclarationTest(unittest.TestCase):
    def declare(self, data):
        return adopt_conformance.declare_input(data, "fixture", "platform")

    def test_the_declaration_is_inserted_into_the_inputs_block(self):
        self.assertEqual(self.declare(DEVENV_YAML.encode()), DEVENV_YAML_DECLARED.encode())

    def test_a_file_without_inputs_gains_the_block(self):
        expected = (b"imports: []\ninputs:\n  agent-platform:\n"
                    b"    url: github:fixture/platform\n    flake: false\n")
        for data in (b"imports: []\n", b"imports: []"):
            with self.subTest(data):
                self.assertEqual(self.declare(data), expected)

    def test_a_compatible_declaration_is_kept(self):
        declared = DEVENV_YAML_DECLARED
        swapped = DEVENV_YAML + ("  agent-platform:\n    flake: false\n"
                                 "    url: github:fixture/platform\n")
        for name, text in (
                ("as declared", declared),
                ("quoted key", declared.replace("  agent-platform:", '  "agent-platform":')),
                ("swapped body", swapped),
                ("comment after the key",
                 declared.replace("  agent-platform:", "  agent-platform: # pinned"))):
            with self.subTest(name):
                self.assertIsNone(self.declare(text.encode()))

    def test_an_incompatible_declaration_is_refused(self):
        cases = {
            "other url": DEVENV_YAML_DECLARED.replace("fixture/platform", "other/platform"),
            "flake true": DEVENV_YAML_DECLARED.replace("flake: false", "flake: true"),
            "no flake line": DEVENV_YAML + ("  agent-platform:\n"
                                           "    url: github:fixture/platform\n"),
            "extra line": DEVENV_YAML_DECLARED + "    follows: nixpkgs\n",
            "inline value": DEVENV_YAML + "  agent-platform: github:fixture/platform\n",
        }
        body = "    url: github:fixture/platform\n    flake: false\n"
        for value in ("|", "x", "&a", "{}"):
            cases[f"inline {value} before a declaration-shaped body"] = (
                DEVENV_YAML + f"  agent-platform: {value}\n" + body)
        for name, text in cases.items():
            with self.subTest(name):
                with self.assertRaises(adopt_conformance.Undeclarable) as caught:
                    self.declare(text.encode())
                self.assertEqual(caught.exception.repair_id,
                                 adopt_conformance.INPUT_INCOMPATIBLE)

    def test_a_shape_the_edit_cannot_handle_is_undeclarable(self):
        cases = {
            "flow mapping": b"{}\n",
            "document marker": b"---\ninputs: {}\n",
            "inline inputs": b"inputs: {}\n",
            "tab-indented child": b"inputs:\n\tnixpkgs:\n\t\turl: github:a/b\n",
            "two inputs lines": b"inputs:\n  a:\n    url: github:a/b\ninputs:\n",
            "a sequence": b"- a\n",
            "an indented flow mapping under inputs": b"inputs:\n  {}\n",
            "an indented sequence under inputs": b"inputs:\n  - a\n",
            "a child outdented from the first": b"inputs:\n    a:\n      url: x\n  b:\n",
            "invalid utf-8": b"inputs:\n  \xff:\n",
            "no file": None,
        }
        for name, data in cases.items():
            with self.subTest(name):
                with self.assertRaises(adopt_conformance.Undeclarable) as caught:
                    self.declare(data)
                self.assertEqual(caught.exception.repair_id,
                                 adopt_conformance.INPUT_UNDECLARABLE)


class ProtectionFileTest(unittest.TestCase):
    def require(self, document):
        return adopt_conformance.require_in_protection_file(json.dumps(document).encode())

    def test_conformance_is_appended_in_the_resolvers_shape(self):
        data = (REPO_ROOT / ".github" / "branch-protection.json").read_bytes()
        before = json.loads(data)
        result = adopt_conformance.require_in_protection_file(data)
        after = json.loads(result)
        checks = before["required_status_checks"]["checks"]
        self.assertEqual(after["required_status_checks"]["checks"],
                         [*checks, {"context": "Conformance"}])
        self.assertEqual(len(checks), 3)
        self.assertTrue(all(entry["app_id"] == 15368 for entry in checks))
        after["required_status_checks"]["checks"] = checks
        self.assertEqual(after, before)
        self.assertTrue(result.endswith(b"\n"))
        with tempfile.TemporaryDirectory() as raw:
            target = Path(raw) / ".github" / "branch-protection.json"
            target.parent.mkdir()
            target.write_bytes(result)
            self.assertEqual(derived_values.required_checks(Path(raw)),
                             ["Nix Eval", "Instruction Budget", "Agent Workflow Tests",
                              "Conformance"])

    def test_a_contexts_list_beside_checks_is_kept_in_step(self):
        document = {"required_status_checks": {
            "checks": [{"context": "Nix Eval"}], "contexts": ["Nix Eval"]}}
        section = json.loads(self.require(document))["required_status_checks"]
        self.assertEqual(section["checks"],
                         [{"context": "Nix Eval"}, {"context": "Conformance"}])
        self.assertEqual(section["contexts"], ["Nix Eval", "Conformance"])
        document = {"required_status_checks": {
            "checks": [{"context": "Conformance"}], "contexts": ["Conformance"]}}
        self.assertIsNone(self.require(document))

    def test_a_file_outside_the_resolvers_shape_is_refused(self):
        def section(**members):
            return {"required_status_checks": members}

        cases = {
            "null section": {"required_status_checks": None},
            "contexts only": section(strict=True, contexts=["Nix Eval"]),
            "checks not a list": section(checks={"context": "Nix Eval"}),
            "entry without context": section(checks=[{"app_id": 1}]),
            "duplicate context": section(checks=[{"context": "A"}, {"context": "A"}]),
            "contexts holding a number": section(checks=[{"context": "A"}], contexts=[1]),
        }
        for name, document in cases.items():
            with self.subTest(name):
                with self.assertRaises(adopt_conformance.Undeclarable) as caught:
                    self.require(document)
                self.assertEqual(caught.exception.repair_id,
                                 adopt_conformance.PROTECTION_FILE_UNREQUIRED)


# --------------------------------------------------------------------------
# The adoption plan's conformance writes
# --------------------------------------------------------------------------

CONFORMANCE_WORKFLOW = ".github/workflows/conformance.yaml"
CONFORMANCE_MEMBER = {
    "revision": FIXTURE_REVISION,
    "lock": {"path": "devenv.lock", "input": "agent-platform", "node": "agent-platform"},
    "workflow": CONFORMANCE_WORKFLOW,
    "required_check": {"repo": "fixture/target", "branch": "main", "context": "Conformance"},
}
CONFORMANCE_GATE = "conformance-plannable"
PLATFORM_MANIFEST_TREE_PATH = "home/common/agent-skills/platform-manifest.json"


def install_platform_revision(home: Path, record: dict | None = FIXTURE_REVISION) -> None:
    """The installed revision record under `home`, or none for None."""
    target = home / ".agents" / "share" / "platform-revision.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.unlink(missing_ok=True)
    if record is not None:
        target.write_text(json.dumps({"schema_version": 1, **record}), encoding="utf-8")


def edit_contract(root: Path, mutate) -> None:
    """Rewrite the committed contract through `mutate`; the caller commits."""
    path = root / ".agents" / "project.json"
    contract = json.loads(path.read_text("utf-8"))
    mutate(contract)
    path.write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8")


def write_devenv(root: Path, *, slug: str = "fixture/target", lock: str = DEVENV_LOCK,
                 yaml: str = DEVENV_YAML) -> None:
    """The two devenv files, the contract's tracker slug, in one commit."""
    write(root, "devenv.lock", lock)
    write(root, "devenv.yaml", yaml)

    def name_slug(contract: dict) -> None:
        old = contract["bindings"]["tracker"]["repo_slug"]
        contract["bindings"]["tracker"]["repo_slug"] = slug
        if isinstance(contract.get("release"), dict):
            # The release profile names the repository the tracker names.
            contract["release"] = json.loads(json.dumps(contract["release"]).replace(old, slug))

    if (root / ".agents" / "project.json").exists():
        edit_contract(root, name_slug)
    commit(root, "add devenv")


def locked_lock_text() -> str:
    document = json.loads(DEVENV_LOCK)
    document["nodes"]["agent-platform"] = locked_platform_node(FIXTURE_REVISION)
    document["nodes"]["root"]["inputs"]["agent-platform"] = "agent-platform"
    return json.dumps(document, indent=2, sort_keys=True)


def conformance_failure(doc: object, repair_id: str) -> dict:
    return {"id": CONFORMANCE_GATE, "status": "failed", "repair_id": repair_id}


class ConformanceAdoptionPlanTest(AdoptTestCase):
    def setUp(self) -> None:
        super().setUp()
        install_platform_revision(self.home)

    def devenv_repo(self, **devenv: object) -> Path:
        root = nix_config_shape_repo(self.home)
        write_devenv(root, **devenv)
        return root

    def fresh_home(self) -> None:
        """A plan id binds to one checkout, so a case with several has a home each."""
        self.home = make_home()
        install_platform_revision(self.home)

    def gates(self, doc: object) -> list[dict]:
        return [gate for gate in doc["verification"]["ready_gates"] if gate["id"] == CONFORMANCE_GATE]

    def targets(self, doc: object, kind: str = "write-file") -> list[str]:
        return [target for op in doc["changes"] if op["op"] == kind for target in op["targets"]]

    def test_the_plan_lists_the_lock_entry_the_workflow_and_the_required_check_and_names_the_revision(self):
        root = self.devenv_repo()
        doc = self.ready_plan(root)
        self.assertEqual(doc["plan"]["state"], "ready", doc["plan"]["blockers"])
        self.assertEqual(doc["plan"]["conformance"], CONFORMANCE_MEMBER)
        written = self.targets(doc)
        self.assertIn("devenv.lock", written)
        self.assertIn("devenv.yaml", written)
        (yaml_op,) = [op for op in doc["changes"] if op["targets"] == ["devenv.yaml"]]
        self.assertEqual(yaml_op["after"], sha256_hash(DEVENV_YAML_DECLARED.encode()))
        (workflow,) = [op for op in doc["changes"]
                       if op["op"] == "regenerate-projection" and op["targets"] == [CONFORMANCE_WORKFLOW]]
        self.assertEqual(workflow["sources"], [".agents/project.json"])
        code, human, err = run("plan", "--repo-root", str(root), "--format", "human", home=self.home)
        self.assertEqual(code, 0, err)
        self.assertIn("platform lock: agent-platform at " + "0f" * 20 + " (devenv.lock)", human)
        self.assertIn("workflow: .github/workflows/conformance.yaml", human)
        self.assertIn("required check: Conformance on main of fixture/target", human)

    def test_a_repository_without_a_devenv_lock_plans_none_of_the_three_writes(self):
        doc = self.ready_plan(nix_config_shape_repo(self.home))
        self.assertNotIn("conformance", doc["plan"])
        self.assertEqual(sorted(doc["plan"]), PLAN_MEMBERS)
        touched = [target for op in doc["changes"] for target in op["targets"]]
        for path in ("devenv.lock", "devenv.yaml", ".github/branch-protection.json", CONFORMANCE_WORKFLOW):
            self.assertNotIn(path, touched)
        self.assertEqual(doc["plan"]["plan_id"], documented_plan_id(doc))
        self.assertEqual([gate["status"] for gate in self.gates(doc)], ["passed"])

    def test_the_platforms_own_tree_plans_none_of_the_three_writes(self):
        root = self.devenv_repo()
        write(root, PLATFORM_MANIFEST_TREE_PATH, "{}\n")
        commit(root, "the platform's own tree")
        doc = self.ready_plan(root)
        self.assertNotIn("conformance", doc["plan"])
        touched = [target for op in doc["changes"] for target in op["targets"]]
        for path in ("devenv.lock", "devenv.yaml", CONFORMANCE_WORKFLOW):
            self.assertNotIn(path, touched)
        self.assertEqual(self.gates(doc), [{"id": CONFORMANCE_GATE, "status": "passed", "repair_id": None}])

    def test_inputs_come_from_the_base_commit(self):
        with self.subTest("an untracked manifest"):
            self.fresh_home()
            root = self.devenv_repo()
            write(root, PLATFORM_MANIFEST_TREE_PATH, "{}\n")
            doc = self.ready_plan(root)
            self.assertEqual(doc["plan"]["conformance"], CONFORMANCE_MEMBER)
        with self.subTest("a staged deletion of the lock"):
            self.fresh_home()
            root = self.devenv_repo()
            git(root, "rm", "--cached", "--quiet", "devenv.lock")
            doc = self.ready_plan(root)
            self.assertEqual(doc["plan"]["conformance"], CONFORMANCE_MEMBER)
            with mock.patch.object(adopt_project.subprocess, "run", _resolver_in_process), \
                    mock.patch.dict(os.environ, {"HOME": str(self.home)}):
                composed = adopt_project.compose_plan(root, json.loads(MANIFEST.read_text("utf-8")), [])
            self.assertIn("devenv.lock", composed.overlap)
        with self.subTest("a lock that is a symlink"):
            self.fresh_home()
            root = self.devenv_repo()
            (root / "devenv.lock").unlink()
            write(root, "real.lock", DEVENV_LOCK)
            (root / "devenv.lock").symlink_to("real.lock")
            commit(root, "link the lock")
            doc = self.ready_plan(root)
            self.assertEqual(self.gates(doc), [conformance_failure(doc, "adopt.conformance.lock_unreadable")])

    def test_a_kept_pin_must_be_the_installed_revision(self):
        root = self.devenv_repo(lock=locked_lock_text(), yaml=DEVENV_YAML_DECLARED)
        doc = self.ready_plan(root)
        self.assertEqual(doc["plan"]["state"], "ready", doc["plan"]["blockers"])
        self.assertEqual(doc["plan"]["conformance"]["revision"], FIXTURE_REVISION)
        written = self.targets(doc)
        self.assertNotIn("devenv.lock", written)
        self.assertNotIn("devenv.yaml", written)
        self.fresh_home()
        stale = json.loads(locked_lock_text())
        stale["nodes"]["agent-platform"] = locked_platform_node({**FIXTURE_REVISION, "rev": "1e" * 20})
        root = self.devenv_repo(lock=json.dumps(stale, indent=2, sort_keys=True), yaml=DEVENV_YAML_DECLARED)
        doc = self.ready_plan(root)
        self.assertEqual(doc["plan"]["state"], "draft")
        self.assertEqual(self.gates(doc), [conformance_failure(doc, "adopt.conformance.pin_incompatible")])

    def test_the_plan_repeats_the_conformance_member(self):
        root = self.devenv_repo()
        doc = self.ready_plan(root)
        self.assertEqual(doc["plan"]["conformance"], CONFORMANCE_MEMBER)
        self.assertEqual(self.gates(doc), [{"id": CONFORMANCE_GATE, "status": "passed",
                                            "repair_id": None}])

    def test_the_running_revision_enters_the_plan_id(self):
        root = self.devenv_repo()
        first = self.ready_plan(root)
        other = make_home()
        install_platform_revision(other, {**FIXTURE_REVISION, "rev": "1e" * 20})
        code, second, err = self.plan(root, home=other)
        self.assertEqual(code, 0, err)
        self.assertNotEqual(first["plan"]["plan_id"], second["plan"]["plan_id"])
        self.assertEqual(first["plan"]["plan_id"], documented_plan_id(first))
        self.assertEqual(second["plan"]["plan_id"], documented_plan_id(second))

    def test_a_repository_that_cannot_take_the_writes_stays_draft(self):
        def protection(text: str):
            def change(root: Path) -> None:
                write(root, ".github/branch-protection.json", text)
                commit(root, "protect")
            return change

        def remove_yaml(root: Path) -> None:
            git(root, "rm", "--quiet", "devenv.yaml")
            commit(root, "drop the yaml")

        def no_tracker(root: Path) -> None:
            edit_contract(root, lambda contract: contract["bindings"]["tracker"].update(kind="none"))
            commit(root, "no tracker")

        cases = {
            "revision_unknown": ({}, None, lambda root: None),
            "revision_unknown (null rev)": ({}, {**FIXTURE_REVISION, "rev": None}, lambda root: None),
            "tracker_unnamed": ({}, FIXTURE_REVISION, no_tracker),
            "origin_mismatch": ({"slug": "fixture/other"}, FIXTURE_REVISION, lambda root: None),
            "lock_unreadable": ({"lock": "not json"}, FIXTURE_REVISION, lambda root: None),
            "input_undeclarable (no file)": ({}, FIXTURE_REVISION, remove_yaml),
            "input_undeclarable (flow)": ({"yaml": "{}\n"}, FIXTURE_REVISION, lambda root: None),
            "protection_file_unrequired (null)": (
                {}, FIXTURE_REVISION, protection('{"required_status_checks": null}\n')),
            "protection_file_unrequired (contexts)": (
                {}, FIXTURE_REVISION, protection('{"required_status_checks": {"contexts": ["Nix Eval"]}}\n')),
        }
        for name, (devenv, record, change) in cases.items():
            with self.subTest(name):
                # A plan id binds to one checkout, so each case has its own home.
                self.home = make_home()
                install_platform_revision(self.home, record)
                root = self.devenv_repo(**devenv)
                change(root)
                doc = self.ready_plan(root)
                repair = "adopt.conformance." + name.split(" ")[0]
                self.assertEqual(doc["plan"]["state"], "draft")
                self.assertEqual(self.gates(doc), [conformance_failure(doc, repair)])
                self.assertIn({"id": CONFORMANCE_GATE,
                               "message": adopt_planning.GATE_MESSAGES[CONFORMANCE_GATE]},
                              doc["plan"]["blockers"])
                self.assertNotIn("conformance", doc["plan"])

    def test_a_colliding_projection_stays_draft(self):
        def collide_by_id(contract: dict) -> None:
            contract["projections"].append({
                "id": "conformance.workflow", "agent": "claude", "kind": "managed_import",
                "target": "OTHER.md", "source": ".agents/instructions/bootstrap.md"})

        root = self.devenv_repo()
        edit_contract(root, collide_by_id)
        commit(root, "collide by id")
        doc = self.ready_plan(root)
        self.assertEqual(doc["plan"]["state"], "draft")
        self.assertEqual(self.gates(doc), [conformance_failure(doc, "adopt.conformance.projection_collides")])
        self.assertNotIn("conformance", doc["plan"])

        draft = drafted_contract()
        draft["bindings"]["tracker"]["repo_slug"] = "fixture/target"
        draft["projections"] = [{
            "id": "other.entry", "agent": "codex", "kind": "generated_file",
            "target": CONFORMANCE_WORKFLOW, "source": "README.md"}]
        self.fresh_home()
        scratch = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, scratch, ignore_errors=True)
        path = scratch / "draft.json"
        path.write_text(json.dumps(draft), encoding="utf-8")
        root = bootstrap_repo(self.home, remotes=("https://github.com/fixture/target.git",))
        write_devenv(root)
        code, doc, err = self.plan(root, "--contract-draft", str(path))
        self.assertEqual(code, 0, err or doc)
        self.assertEqual(doc["plan"]["state"], "draft")
        self.assertEqual(self.gates(doc), [conformance_failure(doc, "adopt.conformance.projection_collides")])

    def test_a_branch_the_workflow_cannot_carry_is_refused_before_ready(self):
        def unsafe(contract: dict) -> None:
            contract["bindings"]["vcs"]["integration_branch"] = "release candidate"

        plain = nix_config_shape_repo(self.home)
        edit_contract(plain, unsafe)
        commit(plain, "an unusual branch")
        doc = self.ready_plan(plain)
        self.assertEqual(doc["plan"]["state"], "ready", doc["plan"]["blockers"])
        self.fresh_home()
        root = self.devenv_repo()
        edit_contract(root, unsafe)
        commit(root, "an unusual branch")
        doc = self.ready_plan(root)
        self.assertEqual(doc["plan"]["state"], "draft")
        self.assertEqual(self.gates(doc), [conformance_failure(doc, "adopt.conformance.contract_refused")])
        self.assertNotIn("conformance", doc["plan"])

    def test_the_protection_file_gains_conformance(self):
        root = self.devenv_repo()
        original = {"required_status_checks": {"strict": True, "checks": [{"context": "Nix Eval", "app_id": 15368}]}}
        write(root, ".github/branch-protection.json", json.dumps(original, indent=2) + "\n")
        commit(root, "protect")
        doc = self.ready_plan(root)
        self.assertEqual(doc["plan"]["state"], "ready", doc["plan"]["blockers"])
        expected = {"required_status_checks": {"strict": True, "checks": [
            {"context": "Nix Eval", "app_id": 15368}, {"context": "Conformance"}]}}
        (op,) = [op for op in doc["changes"] if op["targets"] == [".github/branch-protection.json"]]
        self.assertEqual(op["op"], "write-file")
        self.assertEqual(op["after"], sha256_hash((json.dumps(expected, indent=2) + "\n").encode()))

    def test_a_path_reference_edit_and_the_declaration_share_one_write(self):
        root = self.devenv_repo(yaml=DEVENV_YAML + "# notes: .claude/specs/x.md\n")
        doc = self.ready_plan(root)
        rows = [row for row in doc["path_references"] if row["path"] == "devenv.yaml"]
        self.assertEqual(len(rows), 1, doc["path_references"])
        answer = [value for value in rows[0]["answers"] if value != "retain"][0]
        code, doc, err = self.plan(root, "--answer", "path-reference", rows[0]["subject"], answer)
        self.assertEqual(code, 0, err or doc)
        self.assertEqual(doc["plan"]["state"], "ready", doc["plan"]["blockers"])
        (op,) = [op for op in doc["changes"] if "devenv.yaml" in op["sources"] + op["targets"]]
        self.assertEqual(op["op"], "write-file")
        rewritten = DEVENV_YAML_DECLARED + "# notes: .agents/artifacts/specs/x.md\n"
        self.assertEqual(op["after"], sha256_hash(rewritten.encode()))

    def test_outstanding_conformance_work_is_never_routed_to_no_change(self):
        with self.subTest("a lock the plan cannot edit"):
            root = adopted_repo(self.home)
            write_devenv(root, lock="not json")
            doc = self.ready_plan(root)
            self.assertEqual(doc["plan"]["outcome"], "reconcile")
            self.assertEqual(doc["plan"]["state"], "draft")
            self.assertEqual(self.gates(doc), [conformance_failure(doc, "adopt.conformance.lock_unreadable")])
        def settled_tree(**adoption) -> Path:
            root = adopted_repo(self.home, **adoption)
            write_devenv(root, lock=locked_lock_text(), yaml=DEVENV_YAML_DECLARED)
            edit_contract(root, lambda contract: contract["projections"].append(
                dict(adopt_conformance.PROJECTION_ENTRY)))
            proc = run_module("agent_tools.project_contract.resolve_project",
                              ("write-projections", "--repo-root", str(root)),
                              env={**os.environ, "HOME": str(self.home)})
            self.assertEqual(proc.returncode, 0, proc.stdout)
            commit(root, "the settled tree")
            return root

        self.fresh_home()
        with self.subTest("a settled tree with no adoption commit is outstanding"):
            doc = self.ready_plan(settled_tree(adoption=False))
            self.assertEqual(doc["plan"]["outcome"], "reconcile")
            self.assertEqual(doc["plan"]["state"], "ready", doc["plan"]["blockers"])
            self.assertEqual(doc["plan"]["conformance"], CONFORMANCE_MEMBER)
            written = self.targets(doc)
            for path in ("devenv.lock", "devenv.yaml", ".github/branch-protection.json"):
                self.assertNotIn(path, written)
        self.fresh_home()
        root = settled_tree()
        with self.subTest("a settled tree with an adoption commit is no_change"):
            doc = self.ready_plan(root)
            self.assertEqual(doc["plan"]["outcome"], "no_change")
        for label, record in (("no installed revision", None),
                              ("a dirty build", {**FIXTURE_REVISION, "rev": None})):
            with self.subTest(f"a settled repository on a host with {label}"):
                other = make_home()
                install_platform_revision(other, record)
                code, doc, err = self.plan(root, home=other)
                self.assertEqual(code, 0, err)
                self.assertEqual(doc["plan"]["outcome"], "no_change", doc["plan"])
        with self.subTest("a settled repository cloned from a fork"):
            git(root, "remote", "set-url", "origin", "https://github.com/fork/target.git")
            doc = self.ready_plan(root)
            self.assertEqual(doc["plan"]["outcome"], "no_change", doc["plan"])
        with self.subTest("an unsettled repository keeps its cause when the revision is unknown"):
            git(root, "remote", "set-url", "origin", "https://github.com/fixture/target.git")
            git(root, "rm", "--quiet", "devenv.yaml")
            commit(root, "drop the yaml")
            other = make_home()
            install_platform_revision(other, None)
            code, doc, err = self.plan(root, home=other)
            self.assertEqual(code, 0, err)
            self.assertNotEqual(doc["plan"]["outcome"], "no_change")
            self.assertEqual(self.gates(doc), [conformance_failure(doc, "adopt.conformance.revision_unknown")])


if __name__ == "__main__":
    unittest.main()
