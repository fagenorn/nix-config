"""Contract tests for `adopt-project migrate` (`agent_tools.adopt_migrate`).

`migrate` rewrites the authored contract, regenerates the projections and has
the resolver child judge the result, all in the same store environment. The
resolver is a child process of `adopt_project` (D26), answered in process here
exactly as `test_adopt_project.py` does; the fixtures are the resolver family's
pinned schema-1 contract and its project roots (P11).
"""

from __future__ import annotations

import json
import unittest

from agent_tools import adopt_migrate

from .test_adopt_project import AdoptTestCase, git, run, tree_snapshot
from .test_resolve_project import (
    install_home, make_home, make_project_root, mutated_manifest,
    run as resolve_run, source_contract)

MIGRATION = "bindings-deploy.retire"


def commit_all(root, message: str = "fixture") -> None:
    git(root, "add", "-A")
    git(root, "commit", "--quiet", "-m", message)


class MigrateTest(AdoptTestCase):
    def setUp(self) -> None:
        # The resolver family's home also installs the host declaration.
        self.home = make_home()

    def test_it_retires_the_deploy_members_and_widens_the_interval(self):
        root = make_project_root(source_contract())
        code, out, err = run("migrate", "--migration", MIGRATION,
                             "--repo-root", str(root), home=self.home)
        self.assertEqual(code, 0, err)
        contract = json.loads((root / ".agents/project.json").read_text("utf-8"))
        self.assertEqual(contract["schema_version"], 2)
        self.assertNotIn("deploy", contract["bindings"])
        self.assertNotIn("deploy", contract["capabilities"])
        self.assertEqual(contract["platform"],
                         {"min_inclusive": "1.2.0", "max_exclusive": "3.0.0"})
        report = json.loads(out)
        self.assertEqual(report["migration"], MIGRATION)
        self.assertEqual(report["written"], sorted(report["written"]))
        self.assertIn(".agents/project.json", report["written"])
        self.assertIn("AGENTS.md", report["written"])
        code, _, err = resolve_run("check-projections", "--repo-root", str(root),
                                   home=self.home)
        self.assertEqual(code, 0, err)

    def test_it_stages_nothing_and_commits_nothing(self):
        root = make_project_root(source_contract())
        commit_all(root)
        head = git(root, "rev-parse", "HEAD")
        code, _, err = run("migrate", "--migration", MIGRATION,
                           "--repo-root", str(root), home=self.home)
        self.assertEqual(code, 0, err)
        self.assertEqual(git(root, "rev-parse", "HEAD"), head)
        self.assertEqual(git(root, "diff", "--cached", "--name-only"), "")
        self.assertIn(" M .agents/project.json", git(root, "status", "--porcelain"))

    def test_a_deploy_in_use_refuses_and_writes_nothing(self):
        for member, mutate in (
                ("/bindings/deploy/adapter",
                 lambda c: c["bindings"]["deploy"].update(
                     adapter="railway", config={"project": "p"})),
                ("/bindings/deploy/command",
                 lambda c: c["bindings"]["deploy"].update(command="deploy")),
                ("/capabilities/deploy/support",
                 lambda c: c["capabilities"]["deploy"].update(support="available"))):
            with self.subTest(member=member):
                contract = source_contract()
                mutate(contract)
                root = make_project_root(contract)
                commit_all(root)
                self.assert_read_only(root, 2, "migrate", "--migration", MIGRATION,
                                      "--repo-root", str(root))
                _, out, _ = run("migrate", "--migration", MIGRATION,
                                "--repo-root", str(root), home=self.home)
                error = json.loads(out)["error"]
                self.assertEqual(error["repair_id"], "adopt.migration.deploy_in_use")
                self.assertEqual(error["violations"][0]["pointer"], member)

    def test_a_manifest_without_schema_two_refuses_and_restores(self):
        # The installed manifest admits only schema 1, as on a host still at 1.1.0 (P6).
        install_home(self.home, mutated_manifest(project_schema_versions=[1]))
        root = make_project_root(source_contract())
        commit_all(root)
        before = tree_snapshot(root)
        contents = {name: (root / name).read_bytes()
                    for name in (".agents/project.json", "AGENTS.md", "CLAUDE.md")}
        code, out, _ = run("migrate", "--migration", MIGRATION,
                           "--repo-root", str(root), home=self.home)
        self.assertEqual(code, 2)
        error = json.loads(out)["error"]
        self.assertEqual(error["repair_id"], "adopt.migration.result_invalid")
        self.assertTrue(error["violations"][0]["message"])
        self.assertEqual(tree_snapshot(root), before)
        self.assertEqual({name: (root / name).read_bytes() for name in contents}, contents)
        self.assertEqual(git(root, "status", "--porcelain"), "")

    def test_a_second_run_is_not_applicable(self):
        root = make_project_root(source_contract())
        argv = ("migrate", "--migration", MIGRATION, "--repo-root", str(root))
        self.assertEqual(run(*argv, home=self.home)[0], 0)
        commit_all(root, "migrated")
        code, out, _ = run(*argv, home=self.home)
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(out)["error"]["repair_id"],
                         "adopt.migration.not_applicable")
        self.assertEqual(git(root, "status", "--porcelain"), "")

    def test_an_unknown_migration_refuses(self):
        root = make_project_root(source_contract())
        commit_all(root)
        code, out, _ = run("migrate", "--migration", "no-such.step",
                           "--repo-root", str(root), home=self.home)
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(out)["error"]["repair_id"], "adopt.migration.unknown")
        self.assertEqual(git(root, "status", "--porcelain"), "")

    def test_a_manifest_entry_without_an_executor_is_unknown(self):
        manifest = mutated_manifest()
        manifest["migrations"] = [
            *manifest["migrations"],
            {"id": "future.step", "from_schema": 2, "to_schema": 3}]
        manifest["project_schema_versions"] = [1, 2, 3]
        install_home(self.home, manifest)
        root = make_project_root(source_contract())
        commit_all(root)
        code, out, _ = run("migrate", "--migration", "future.step",
                           "--repo-root", str(root), home=self.home)
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(out)["error"]["repair_id"], "adopt.migration.unknown")
        self.assertEqual(git(root, "status", "--porcelain"), "")


class RetireBindingsDeployTest(unittest.TestCase):
    def test_it_is_pure_and_keeps_member_order(self):
        source = source_contract()
        frozen = json.dumps(source)
        out = adopt_migrate.retire_bindings_deploy(source)
        self.assertEqual(json.dumps(source), frozen)
        self.assertEqual(list(out), list(source))
        self.assertEqual(list(out["bindings"]),
                         [k for k in source["bindings"] if k != "deploy"])
        self.assertEqual(list(out["capabilities"]),
                         [k for k in source["capabilities"] if k != "deploy"])

    def test_it_keeps_a_minimum_above_the_floor(self):
        source = source_contract()
        source["platform"] = {"min_inclusive": "1.10.0", "max_exclusive": "2.0.0"}
        out = adopt_migrate.retire_bindings_deploy(source)
        self.assertEqual(out["platform"],
                         {"min_inclusive": "1.10.0", "max_exclusive": "3.0.0"})

    def test_the_registry_names_exactly_the_one_migration(self):
        self.assertEqual(list(adopt_migrate.MIGRATIONS), [MIGRATION])


if __name__ == "__main__":
    unittest.main()
