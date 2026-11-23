"""Contract tests for planning the adoption of a drafted schema-3 contract.

A schema-3 draft leaves the project id, the tracker slug, the required checks and the platform
interval to the repository (ADR-project-contract-014), so the plan resolves it strictly: in a
scratch tree holding the base revision's export, the checkout's authored origin, the conformance
writes and the projections the contract generates. The cases live beside `test_adopt_project.py`
because that file is over its size limit and may not grow; its fixtures and case base are imported
from it and from `test_adopt_conformance.py`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import tempfile
import subprocess
from unittest import mock

from agent_tools.project_contract import (adopt_apply, adopt_conformance, adopt_inspection,
                                          adopt_project, derived_values, resolve_project)

from agent_tools.system.siblings import sibling_argv

from . import test_adopt_project
from .test_adopt_conformance import (
    FIXTURE_REVISION,
    install_platform_revision,
    locked_lock_text,
    write_devenv,
)
from .test_adopt_apply import BOOTSTRAP, ENTRY_AGENTS
from .test_adopt_project import (
    MANIFEST,
    AdoptTestCase,
    _resolver_in_process,
    bootstrap_repo,
    commit,
    git,
    sha256_hash,
    write,
)

TIER = "integration"  # every case runs a real git repository

PROTECTION = {"required_status_checks": {"strict": True, "checks": [{"context": "Nix Eval"}]}}
STALE_PROJECTION = {"error": {"code": "invalid_projection",
                              "violations": [{"pointer": "/projections/0", "message": "x"}]}}


def schema_three_draft() -> dict:
    """The contract the console drafts: only the members schema 3 leaves authored."""
    return {
        "schema_version": 3,
        "bindings": {
            "vcs": {"integration_branch": "main"},
            "commands": {"lint": {"argv": ["true"]}, "test": {"argv": ["true"]}},
        },
        "capabilities": {name: {"support": "unsupported"}
                         for name in resolve_project.AUTHORED_CAPABILITY_NAMES},
        "projections": [],
        "release": "unsupported",
    }


class SchemaThreeDraftPlanTest(AdoptTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.draft = schema_three_draft()
        self.scratch = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)

    def draft_file(self) -> str:
        path = self.scratch / "draft.json"
        path.write_text(json.dumps(self.draft), encoding="utf-8")
        return str(path)

    def stored_plans(self) -> list[str]:
        directory = self.home / ".agents/state/adopt/plans"
        return sorted(path.name for path in directory.glob("*")) if directory.exists() else []

    def schema_three_repo(self, *, protection: bool = True, devenv: bool = True) -> Path:
        install_platform_revision(self.home)
        store = self.scratch / "store"
        manifest = (Path(derived_values.store_path(FIXTURE_REVISION["narHash"], str(store)))
                    / derived_values.TREE_MANIFEST)
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(
            json.dumps({"platform_version": json.loads(MANIFEST.read_text("utf-8"))["platform_version"]}),
            encoding="utf-8")
        patch = mock.patch.object(derived_values, "STORE_DIR", str(store))
        patch.start()
        self.addCleanup(patch.stop)
        root = self.root = bootstrap_repo(
            self.home, remotes=("https://github.com/fixture/target.git",))
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        if protection:
            write(root, ".github/branch-protection.json", json.dumps(PROTECTION))
        if devenv:
            write_devenv(root)
        return root

    def answering(self, verb: str, document: dict, *, scratch_only: bool = False):
        """The in-process resolver child, except that `verb` answers `document` (exit 2).

        The seam is the child process the `run` helper patches in, not `run_resolver`;
        `scratch_only` leaves a resolver run on the checkout itself alone.
        """
        prefix = sibling_argv("project_contract.resolve_project")

        def child(argv, *args, **kwargs):
            if (list(argv[:len(prefix)]) == prefix and argv[len(prefix)] == verb
                    and (not scratch_only or Path(argv[-1]).resolve() != self.root)):
                return subprocess.CompletedProcess(
                    list(argv), 2, json.dumps(document).encode("utf-8"), b"")
            return _resolver_in_process(argv, *args, **kwargs)

        return mock.patch.object(test_adopt_project, "_resolver_in_process", child)

    def test_a_schema_three_draft_plans_ready(self):
        root = self.schema_three_repo()
        code, doc, err = self.plan(root, "--contract-draft", self.draft_file())
        self.assertEqual(code, 0, err or doc)
        plan = doc["plan"]
        self.assertEqual(plan["state"], "ready", plan["blockers"])
        self.assertEqual(plan["blockers"], [])
        # The tracked `.github` protection file is agent surface, so a draft is routed `reconcile`.
        self.assertEqual(plan["outcome"], "reconcile")
        self.assertEqual(plan["project_id"], "fixture/target")
        self.assertEqual(plan["contract_draft"], self.draft)
        self.assertEqual(plan["conformance"]["required_check"],
                         {"repo": "fixture/target", "branch": "main", "context": "Conformance"})
        (write_op,) = [op for op in doc["changes"]
                       if op["op"] == "write-file" and op["targets"] == [".agents/project.json"]]
        written = adopt_inspection.authored_bytes(
            {**json.loads(json.dumps(self.draft, sort_keys=True)),
             "projections": [adopt_conformance.PROJECTION_ENTRY]})
        self.assertEqual(write_op["after"], sha256_hash(written))

    def test_a_schema_three_draft_resolves_with_the_converted_bootstrap_source(self):
        root = self.schema_three_repo()
        write(root, "AGENTS.md", ENTRY_AGENTS)
        commit(root, "hand-write the entry file")
        code, doc, err = self.plan(root, "--contract-draft", self.draft_file())
        self.assertEqual(code, 0, err or doc)
        self.assertEqual(doc["plan"]["state"], "ready", doc["plan"]["blockers"])
        self.assertEqual(
            {entry["path"]: entry["action"] for entry in doc["evidence"]}["AGENTS.md"],
            "convert-to-source")
        self.assertEqual([op["before"] for op in doc["changes"]
                          if op["op"] == "write-file" and op["targets"] == [BOOTSTRAP]], [None])

    def test_a_schema_three_draft_without_a_protection_file_is_refused_not_derivable(self):
        root = self.schema_three_repo(protection=False)
        before = self.stored_plans()
        code, doc, err = self.plan(root, "--contract-draft", self.draft_file())
        self.assertEqual(code, 2, err)
        self.assertEqual(doc["error"]["repair_id"], "adopt.draft.invalid")
        (violation,) = [v for v in doc["error"]["violations"]
                        if v["pointer"] == "/bindings/vcs/merge/required_checks"]
        self.assertTrue(violation["message"].startswith("cannot be derived"), violation)
        self.assertEqual(self.stored_plans(), before)

    def test_a_schema_three_draft_of_a_repository_without_devenv_is_refused_not_derivable(self):
        root = self.schema_three_repo(devenv=False)
        code, doc, err = self.plan(root, "--contract-draft", self.draft_file())
        self.assertEqual(code, 2, err)
        self.assertEqual(doc["error"]["repair_id"], "adopt.draft.invalid")
        (violation,) = [v for v in doc["error"]["violations"] if v["pointer"] == "/platform"]
        self.assertTrue(violation["message"].startswith("cannot be derived"), violation)

    def test_a_schema_three_draft_with_a_conformance_repair_plans_draft_naming_the_repair(self):
        root = self.schema_three_repo()
        install_platform_revision(self.home, None)  # the platform revision is unknown
        code, doc, err = self.plan(root, "--contract-draft", self.draft_file())
        self.assertEqual(code, 0, err or doc)
        plan = doc["plan"]
        self.assertEqual(plan["state"], "draft")
        self.assertEqual(plan["project_id"], "fixture/target")
        (gate,) = [gate for gate in doc["verification"]["ready_gates"]
                   if gate["id"] == "conformance-plannable"]
        self.assertEqual(gate, {"id": "conformance-plannable", "status": "failed",
                                "repair_id": adopt_conformance.REVISION_UNKNOWN})

    def test_seed_origin_writes_the_authored_origin_url(self):
        root = bootstrap_repo(self.home, remotes=("https://github.com/fixture/target.git",))
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        bare = self.scratch / "bare.git"
        git(self.scratch, "init", "--quiet", "--bare", str(bare))
        git(root, "config", f"url.{bare}.insteadOf", "https://github.com/fixture/target.git")
        destination = self.scratch / "export"
        destination.mkdir()
        adopt_inspection.seed_origin(root, destination)
        self.assertIn("url = https://github.com/fixture/target.git",
                      (destination / ".git" / "config").read_text(encoding="utf-8"))

    def test_a_schema_three_draft_whose_projection_cannot_be_generated_is_refused(self):
        root = self.schema_three_repo()
        before = self.stored_plans()
        with self.answering("write-projections", STALE_PROJECTION):
            code, doc, err = self.plan(root, "--contract-draft", self.draft_file())
        self.assertEqual(code, 2, err)
        self.assertEqual(doc["error"]["repair_id"], "adopt.draft.invalid")
        self.assertIn("/projections", [v["pointer"] for v in doc["error"]["violations"]])
        self.assertEqual(self.stored_plans(), before)

    def test_a_schema_three_draft_the_resolver_refuses_as_a_stale_projection_is_not_ready(self):
        root = self.schema_three_repo()
        before = self.stored_plans()
        with self.answering("resolve", STALE_PROJECTION, scratch_only=True):
            code, doc, err = self.plan(root, "--contract-draft", self.draft_file())
        self.assertEqual(code, 2, err)
        self.assertEqual(doc["error"]["repair_id"], "adopt.draft.invalid")
        self.assertEqual(self.stored_plans(), before)

    def test_the_cold_clone_gate_resolves_a_schema_three_contract(self):
        root = self.schema_three_repo()
        write(root, "devenv.lock", locked_lock_text())
        write(root, ".agents/project.json", json.dumps(self.draft))
        git(root, "add", "devenv.lock", ".agents/project.json")
        with mock.patch.object(adopt_project.subprocess, "run", _resolver_in_process), \
                mock.patch.dict(os.environ, {"HOME": str(self.home)}):
            run = adopt_apply.GateRun(root, [], adopt_project.run_resolver)
            self.assertTrue(adopt_apply.gate_cold_clone_resolves(run))
