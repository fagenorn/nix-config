"""Contract tests for `adopt-project migrate` (`agent_tools.project_contract.adopt_migrate`).

`migrate` rewrites the authored contract, regenerates the projections and has
the resolver child judge the result, all in the same store environment. The
resolver is a child process of `adopt_project` (D26), answered in process here
exactly as `test_adopt_project.py` does; the fixtures are the resolver family's
pinned schema-1 contract and its project roots (P11).
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from agent_tools.project_contract import (
    adopt_migrate, attempt_history, derived_values, schema_three)

from .test_adopt_project import AdoptTestCase, git, run, tree_snapshot
from .test_resolve_project import (
    MANAGED_LINE, committed_manifest, install_home, make_home, make_project_root,
    mutated_manifest, RETIRED_MEMBER, run as resolve_run, schema_one,
    source_contract as pinned_contract)
from .test_resolve_schema_three import (
    EXPECTED_DERIVED, ISSUE_READS, make_schema_three_root, named_member_paths,
    schema_three_contract, schema_two_equivalent, values_at, without_retired)

MIGRATION = "bindings-deploy.retire"
MIGRATION_THREE = "platform-constants.retire"


def source_contract() -> dict:
    """The schema-1 contract `migrate` reads: the pinned schema-2 fixture with the two
    inert deploy members back (P11). Platform 2.0.0 refuses it everywhere except here."""
    return schema_one(pinned_contract())


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
                 lambda c: c["bindings"][RETIRED_MEMBER].update(
                     adapter="railway", config={"project": "p"})),
                ("/bindings/deploy/command",
                 lambda c: c["bindings"][RETIRED_MEMBER].update(command="deploy")),
                ("/capabilities/deploy/support",
                 lambda c: c["capabilities"][RETIRED_MEMBER].update(support="available"))):
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

    def nested_target_root(self, *, doubled_import: bool = False, moved: bool = True):
        """A schema-1 project whose codex projection targets generated/AGENTS.md."""
        contract = source_contract()
        for entry in contract["projections"]:
            if entry["kind"] == "generated_file":
                entry["target"] = "generated/AGENTS.md"
        root = make_project_root(contract)
        if moved:
            (root / "generated").mkdir()
            (root / "AGENTS.md").rename(root / "generated/AGENTS.md")
        if doubled_import:
            (root / "CLAUDE.md").write_text(
                f"# authored body\n{MANAGED_LINE}\n{MANAGED_LINE}\n", encoding="utf-8")
        commit_all(root)
        return root

    def test_it_reports_a_projection_target_that_is_not_a_root_file(self):
        root = self.nested_target_root()
        before = (root / "generated/AGENTS.md").read_bytes()
        code, out, err = run("migrate", "--migration", MIGRATION,
                             "--repo-root", str(root), home=self.home)
        self.assertEqual(code, 0, err)
        self.assertNotEqual((root / "generated/AGENTS.md").read_bytes(), before)
        changed = sorted(line[3:] for line in git(
            root, "status", "--porcelain", "--untracked-files=all").splitlines())
        self.assertEqual(json.loads(out)["written"], changed)
        self.assertIn("generated/AGENTS.md", changed)

    def test_a_refusal_restores_a_projection_target_that_is_not_a_root_file(self):
        # write-projections writes generated/AGENTS.md, then refuses the
        # doubled managed import line in CLAUDE.md.
        root = self.nested_target_root(doubled_import=True)
        before = tree_snapshot(root)
        code, out, _ = run("migrate", "--migration", MIGRATION,
                           "--repo-root", str(root), home=self.home)
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(out)["error"]["repair_id"],
                         "adopt.migration.result_invalid")
        self.assertEqual(tree_snapshot(root), before)
        self.assertEqual(git(root, "status", "--porcelain"), "")

    def test_a_refusal_removes_a_projection_target_it_created(self):
        # generated/ and the target do not exist before the run.
        root = self.nested_target_root(doubled_import=True, moved=False)
        before = tree_snapshot(root)
        code, _, _ = run("migrate", "--migration", MIGRATION,
                         "--repo-root", str(root), home=self.home)
        self.assertEqual(code, 2)
        self.assertEqual(tree_snapshot(root), before)
        self.assertFalse((root / "generated").exists())

    @unittest.skipIf(os.geteuid() == 0, "root reads every file")
    def test_an_unreadable_existing_file_refuses_before_any_write_and_survives(self):
        # CLAUDE.md exists but cannot be read, so no byte of it can be backed up.
        root = make_project_root(source_contract())
        commit_all(root)
        unreadable = root / "CLAUDE.md"
        original = unreadable.read_bytes()
        contract_before = (root / ".agents/project.json").read_bytes()
        unreadable.chmod(0)
        code, out, _ = run("migrate", "--migration", MIGRATION,
                           "--repo-root", str(root), home=self.home)
        if unreadable.exists():
            unreadable.chmod(0o644)
        self.assertEqual(code, 2)
        error = json.loads(out)["error"]
        self.assertEqual((error["repair_id"], error["violations"][0]["pointer"]),
                         ("adopt.migration.unreadable", "/CLAUDE.md"))
        self.assertEqual(unreadable.read_bytes(), original)
        self.assertEqual((root / ".agents/project.json").read_bytes(), contract_before)
        self.assertEqual(git(root, "status", "--porcelain"), "")

    def test_a_target_that_is_a_symlink_inside_the_checkout_refuses_and_keeps_the_link(self):
        # The projection writer would replace the link with a regular file, and a
        # restore of the followed bytes alone would leave that file behind.
        root = make_project_root(source_contract())
        (root / "elsewhere.md").write_text("linked\n", encoding="utf-8")
        (root / "AGENTS.md").unlink()
        (root / "AGENTS.md").symlink_to("elsewhere.md")
        commit_all(root)
        contract_before = (root / ".agents/project.json").read_bytes()
        code, out, _ = run("migrate", "--migration", MIGRATION,
                           "--repo-root", str(root), home=self.home)
        self.assertEqual(code, 2)
        error = json.loads(out)["error"]
        self.assertEqual((error["repair_id"], error["violations"][0]["pointer"]),
                         ("adopt.migration.symlink_target", "/AGENTS.md"))
        self.assertTrue((root / "AGENTS.md").is_symlink())
        self.assertEqual(os.readlink(root / "AGENTS.md"), "elsewhere.md")
        self.assertEqual((root / "elsewhere.md").read_text(encoding="utf-8"), "linked\n")
        self.assertEqual((root / ".agents/project.json").read_bytes(), contract_before)
        self.assertEqual(git(root, "status", "--porcelain"), "")

    def test_a_target_through_a_symlink_out_of_the_checkout_refuses_and_writes_nothing(self):
        contract = source_contract()
        for entry in contract["projections"]:
            if entry["kind"] == "generated_file":
                entry["target"] = "generated/AGENTS.md"
        root = make_project_root(contract)
        outside = make_project_root(source_contract())
        external = outside / "AGENTS.md"
        external.write_text("another repository\n", encoding="utf-8")
        (root / "generated").symlink_to(outside)
        (root / "AGENTS.md").unlink()
        commit_all(root)
        contract_before = (root / ".agents/project.json").read_bytes()
        code, out, _ = run("migrate", "--migration", MIGRATION,
                           "--repo-root", str(root), home=self.home)
        self.assertEqual(code, 2)
        error = json.loads(out)["error"]
        self.assertEqual((error["repair_id"], error["violations"][0]["pointer"]),
                         ("adopt.migration.path_outside_checkout", "/generated/AGENTS.md"))
        self.assertEqual(external.read_text(encoding="utf-8"), "another repository\n")
        self.assertEqual((root / ".agents/project.json").read_bytes(), contract_before)

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
            {"id": "future.step", "from_schema": 3, "to_schema": 4}]
        manifest["project_schema_versions"] = [2, 3, 4]
        install_home(self.home, manifest)
        root = make_project_root(source_contract())
        commit_all(root)
        code, out, _ = run("migrate", "--migration", "future.step",
                           "--repo-root", str(root), home=self.home)
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(out)["error"]["repair_id"], "adopt.migration.unknown")
        self.assertEqual(git(root, "status", "--porcelain"), "")


SLUG = "fagenorn/nix-config"
HISTORY_AT = datetime(2026, 11, 22, 12, tzinfo=timezone.utc)
ARTIFACT = ".agents/artifacts/specs/old.md"


def record_history(root) -> None:
    """Twenty delivered attempts in the repository's git directory (untracked by construction)."""
    attempts = [
        attempt_history.Attempt(
            i, 100 + i,
            HISTORY_AT - timedelta(days=21 - i) - timedelta(seconds=i * 3600 + 30),
            HISTORY_AT - timedelta(days=21 - i))
        for i in range(1, 21)]
    attempt_history.write_history(
        root, attempt_history.render_history(SLUG, HISTORY_AT, attempts))


class RetirePlatformConstantsTest(AdoptTestCase):
    def setUp(self) -> None:
        self.home = make_home()
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)

    def root(self, mutate=None, *, before=None, **sources):
        contract = schema_two_equivalent(schema_three_contract())
        if mutate is not None:
            mutate(contract)
        root = make_schema_three_root(contract, **sources)
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        if before is not None:
            before(root)
        commit_all(root)
        return root

    def migrate(self, root):
        return run("migrate", "--migration", MIGRATION_THREE,
                   "--repo-root", str(root), home=self.home)

    def contract_bytes(self, root) -> bytes:
        return (root / ".agents/project.json").read_bytes()

    def assert_refused(self, root, repair_id, pointers):
        status = git(root, "status", "--porcelain")
        contract = self.contract_bytes(root)
        code, out, err = self.migrate(root)
        self.assertEqual(code, 2, err)
        error = json.loads(out)["error"]
        self.assertEqual(error["repair_id"], repair_id)
        self.assertEqual([v["pointer"] for v in error["violations"]], pointers)
        self.assertEqual(git(root, "status", "--porcelain"), status)
        self.assertEqual(self.contract_bytes(root), contract)

    def assert_migrates(self, root) -> dict:
        code, out, err = self.migrate(root)
        self.assertEqual(code, 0, err)
        return json.loads(out)

    def test_it_migrates_the_schema_two_equivalent_to_the_schema_three_fixture(self):
        root = self.root()
        code, out, err = resolve_run("resolve", "--repo-root", str(root), home=self.home)
        self.assertEqual(code, 0, err)
        snap2 = json.loads(out)
        report = self.assert_migrates(root)
        self.assertEqual(json.loads(self.contract_bytes(root)), schema_three_contract())
        self.assertLessEqual({".agents/project.json", "AGENTS.md"}, set(report["written"]))
        self.assertIn("(project schema 3)", (root / "AGENTS.md").read_text("utf-8"))
        code, _, err = resolve_run("check-projections", "--repo-root", str(root),
                                   home=self.home)
        self.assertEqual(code, 0, err)
        code, out, err = resolve_run("resolve", "--repo-root", str(root), home=self.home)
        self.assertEqual(code, 0, err)
        snap3 = json.loads(out)
        for path in sorted(set(named_member_paths()) | ISSUE_READS):
            with self.subTest(path=path):
                self.assertIsNotNone(values_at(snap3, path))
                self.assertEqual(values_at(snap3, path),
                                 values_at(without_retired(snap2), path))

    def test_it_is_pure_and_inverts_the_schema_three_fill(self):
        source = schema_two_equivalent(schema_three_contract())
        frozen = json.dumps(source)
        out = adopt_migrate.retire_platform_constants(
            source, derived_values.Derived(dict(EXPECTED_DERIVED), []))
        self.assertEqual(json.dumps(source), frozen)
        self.assertEqual(json.dumps(out), json.dumps(schema_three_contract()))

    def test_the_pinned_schema_two_fixture_is_refused_at_each_differing_constant(self):
        root = make_schema_three_root(pinned_contract())
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        commit_all(root)
        self.assert_refused(root, "adopt.migration.constant_differs", [
            "/bindings/commands/commit-environment",
            "/bindings/paths/architecture",
            "/bindings/paths/context",
            "/bindings/paths/hints",
            "/bindings/paths/operations",
            "/bindings/paths/standards",
            "/bindings/tracker/credential_env/unset_before_invocation",
            "/bindings/vcs/commit/environment",
            "/bindings/workflow/verification"])

    def test_a_differing_platform_command_or_command_constant_is_refused_by_name(self):
        def argv(c):
            c["bindings"]["commands"]["commit-environment"]["argv"] = ["nix", "develop", "-c"]

        def deleted(c):
            del c["bindings"]["commands"]["commit-environment"]

        def cwd(c):
            c["bindings"]["commands"]["lint"]["cwd"] = "sub"

        def env(c):
            c["bindings"]["commands"]["test"]["env"] = ["CI"]

        def signed(c):
            c["bindings"]["vcs"]["commit"]["signed"] = 1

        def parallel(c):
            c["bindings"]["workflow"]["orchestration"]["max_parallel"] = 2.0

        def malformed(c):
            c["bindings"] = "x"

        cases = (
            ("argv", argv, {}, ["/bindings/commands/commit-environment"]),
            ("deleted", deleted, {}, ["/bindings/commands/commit-environment"]),
            ("cwd", cwd, {}, ["/bindings/commands/lint/cwd"]),
            ("env", env, {}, ["/bindings/commands/test/env"]),
            ("signed", signed, {}, ["/bindings/vcs/commit/signed"]),
            ("parallel", parallel, {}, ["/bindings/workflow/orchestration/max_parallel"]),
            ("malformed", malformed, {"projections": False},
             sorted([*schema_three.CONSTANTS, "/bindings/commands/commit-environment"])))
        for name, mutate, sources, pointers in cases:
            with self.subTest(name):
                root = self.root(mutate, **sources)
                self.assert_refused(root, "adopt.migration.constant_differs", pointers)
        with self.subTest("a review command schema 2 supplies implicitly"):
            root = self.root(lambda c: c["bindings"]["commands"].pop("codex-plan-review", None))
            self.assert_migrates(root)

    def test_a_disagreeing_derived_value_is_refused_by_name(self):
        def slug(c):
            c["bindings"]["tracker"]["repo_slug"] = "someone/else"

        def project(c):
            c["project"]["id"] = "someone/else"

        def checks(c):
            c["bindings"]["vcs"]["merge"]["required_checks"] = ["Nix Eval"]

        def interval(c):
            c["platform"] = {"min_inclusive": "1.2.0", "max_exclusive": "2.0.0"}

        for name, mutate, pointer in (
                ("repo_slug", slug, "/bindings/tracker/repo_slug"),
                ("project id", project, "/project/id"),
                ("required checks", checks, "/bindings/vcs/merge/required_checks"),
                ("interval", interval, "/platform")):
            with self.subTest(name):
                self.assert_refused(self.root(mutate),
                                    "adopt.migration.derived_differs", [pointer])

    def test_an_attempt_budget_other_than_the_derived_one_is_refused_by_name(self):
        budget = "/bindings/workflow/orchestration/attempt_budget_minutes"

        def orchestration(c):
            return c["bindings"]["workflow"]["orchestration"]

        def other(c):
            orchestration(c)["attempt_budget_minutes"] = 480

        def dropped(c):
            del orchestration(c)["attempt_budget_minutes"]

        def basis(c):
            orchestration(c)["attempt_budget_basis"] = {
                "source": "fallback", "reason": "no_history"}

        for name, mutate, pointer in (
                ("other", other, budget), ("absent", dropped, budget),
                ("basis", basis, budget.replace("minutes", "basis"))):
            with self.subTest(name):
                self.assert_refused(self.root(mutate),
                                    "adopt.migration.derived_differs", [pointer])
        with self.subTest("history"):
            root = self.root(before=record_history)
            derived = attempt_history.read(root, SLUG).minutes
            self.assertNotEqual(derived, 240)
            status = git(root, "status", "--porcelain")
            code, out, err = self.migrate(root)
            self.assertEqual(code, 2, err)
            error = json.loads(out)["error"]
            self.assertEqual(error["repair_id"], "adopt.migration.derived_differs")
            self.assertEqual([v["pointer"] for v in error["violations"]], [budget])
            self.assertIn(json.dumps(derived), error["violations"][0]["message"])
            self.assertEqual(git(root, "status", "--porcelain"), status)
        with self.subTest("history, authored budget equals it"):
            def match(c):
                orchestration(c)["attempt_budget_minutes"] = 1621
            root = self.root(match, before=record_history)
            self.assertEqual(attempt_history.read(root, SLUG).minutes, 1621)
            self.assert_migrates(root)
            self.assertNotIn(
                "orchestration", json.loads(self.contract_bytes(root))["bindings"]["workflow"])

    def test_no_declared_checks_accept_absent_or_null_and_refuse_an_empty_list(self):
        none = {"required_status_checks": None}

        def absent(c):
            del c["bindings"]["vcs"]["merge"]["required_checks"]

        def null(c):
            c["bindings"]["vcs"]["merge"]["required_checks"] = None

        def empty(c):
            c["bindings"]["vcs"]["merge"]["required_checks"] = []

        with self.subTest("absent"):
            self.assert_migrates(self.root(absent, protection=none))
        with self.subTest("null"):
            root = self.root(null, protection=none)
            self.assert_migrates(root)
            self.assertNotIn("merge", json.loads(self.contract_bytes(root))["bindings"]["vcs"])
        with self.subTest("empty"):
            self.assert_refused(self.root(empty, protection=none),
                                "adopt.migration.derived_differs",
                                ["/bindings/vcs/merge/required_checks"])

    def test_a_platform_interval_admitting_the_stated_version_is_dropped(self):
        def wide(c):
            c["platform"] = {"min_inclusive": "1.2.0", "max_exclusive": "3.0.0"}

        root = self.root(wide)
        self.assert_migrates(root)
        self.assertNotIn("platform", json.loads(self.contract_bytes(root)))
        code, _, err = resolve_run("resolve", "--repo-root", str(root), home=self.home)
        self.assertEqual(code, 0, err)

    def test_an_underivable_value_is_refused_before_any_write(self):
        self.assert_refused(self.root(protection=None), "adopt.migration.not_derivable",
                            ["/bindings/vcs/merge/required_checks"])

    def test_a_differing_constant_is_reported_before_a_derived_value(self):
        def mutate(c):
            c["bindings"]["paths"]["standards"] = ["docs/standards", "more"]
            c["bindings"]["tracker"]["repo_slug"] = "someone/else"

        self.assert_refused(self.root(mutate), "adopt.migration.constant_differs",
                            ["/bindings/paths/standards"])

    def test_it_deletes_every_tracked_file_under_the_artifacts_directory(self):
        def tracked(root):
            for name in (ARTIFACT, ".agents/artifacts/evidence/rec.json"):
                (root / name).parent.mkdir(parents=True, exist_ok=True)
                (root / name).write_text(f"tracked {name}\n", encoding="utf-8")

        root = self.root(before=tracked)
        (root / ".agents/artifacts/notes").mkdir()
        (root / ".agents/artifacts/notes/scratch.md").write_text("scratch\n", encoding="utf-8")
        (root / "notes.txt").write_text("notes\n", encoding="utf-8")
        report = self.assert_migrates(root)
        for name in (ARTIFACT, ".agents/artifacts/evidence/rec.json"):
            self.assertFalse((root / name).exists(), name)
            self.assertIn(name, report["written"])
        self.assertEqual((root / ".agents/artifacts/notes/scratch.md").read_text("utf-8"),
                         "scratch\n")
        self.assertEqual((root / "notes.txt").read_text("utf-8"), "notes\n")
        status = git(root, "status", "--porcelain").splitlines()
        self.assertIn(f" D {ARTIFACT}", status)
        self.assertIn(" D .agents/artifacts/evidence/rec.json", status)
        self.assertEqual(git(root, "diff", "--cached", "--name-only"), "")

    def test_a_projection_target_inside_the_artifacts_directory_is_refused(self):
        def generated(c):
            for entry in c["projections"]:
                if entry["kind"] == "generated_file":
                    entry["target"] = ".agents/artifacts/AGENTS.md"

        def managed(c):
            for entry in c["projections"]:
                if entry["kind"] == "managed_import":
                    entry["target"] = ".agents/artifacts/CLAUDE.md"

        def move(name):
            def before(root):
                (root / ".agents/artifacts").mkdir(parents=True)
                (root / name).rename(root / ".agents/artifacts" / name)
            return before

        for name, mutate in (("AGENTS.md", generated), ("CLAUDE.md", managed)):
            with self.subTest(name):
                root = self.root(mutate, before=move(name))
                code, _, err = resolve_run("resolve", "--repo-root", str(root), home=self.home)
                self.assertEqual(code, 0, err)
                target = root / ".agents/artifacts" / name
                kept = target.read_bytes()
                self.assert_refused(root, "adopt.migration.projection_in_retired_tree",
                                    [f"/.agents/artifacts/{name}"])
                self.assertEqual(target.read_bytes(), kept)

    def test_a_projection_target_spelled_differently_is_still_inside_the_artifacts_directory(self):
        def dotted(c):
            for entry in c["projections"]:
                if entry["kind"] == "generated_file":
                    entry["target"] = "./.agents/artifacts/AGENTS.md"

        def through_link(c):
            for entry in c["projections"]:
                if entry["kind"] == "generated_file":
                    entry["target"] = "shortcut/AGENTS.md"

        def tracked(root):
            (root / ".agents/artifacts").mkdir(parents=True)
            (root / "AGENTS.md").rename(root / ".agents/artifacts/AGENTS.md")

        def linked(root):
            tracked(root)
            (root / "shortcut").symlink_to(".agents/artifacts")

        for name, mutate, before, pointer in (
                ("dotted", dotted, tracked, "/./.agents/artifacts/AGENTS.md"),
                ("link", through_link, linked, "/shortcut/AGENTS.md")):
            with self.subTest(name):
                root = self.root(mutate, before=before)
                target = root / ".agents/artifacts/AGENTS.md"
                kept = target.read_bytes()
                self.assert_refused(
                    root, "adopt.migration.projection_in_retired_tree", [pointer])
                self.assertEqual(target.read_bytes(), kept)

    def test_a_projection_target_in_another_case_is_refused_on_a_case_insensitive_checkout(self):
        def upper(c):
            for entry in c["projections"]:
                if entry["kind"] == "generated_file":
                    entry["target"] = ".agents/ARTIFACTS/AGENTS.md"

        def tracked(root):
            (root / ".agents/artifacts").mkdir(parents=True)
            (root / "AGENTS.md").rename(root / ".agents/artifacts/AGENTS.md")

        root = self.root(upper, before=tracked)
        if not (root / ".agents/ARTIFACTS/AGENTS.md").exists():
            self.skipTest("the checkout's filesystem is case sensitive")
        target = root / ".agents/artifacts/AGENTS.md"
        kept = target.read_bytes()
        self.assert_refused(root, "adopt.migration.projection_in_retired_tree",
                            ["/.agents/ARTIFACTS/AGENTS.md"])
        self.assertEqual(target.read_bytes(), kept)

    def test_a_retired_file_the_resolver_recreates_is_refused_and_restored(self):
        def tracked(root):
            (root / ARTIFACT).parent.mkdir(parents=True)
            (root / ARTIFACT).write_text("original\n", encoding="utf-8")

        root = self.root(before=tracked)
        before = tree_snapshot(root)
        source = json.loads(self.contract_bytes(root))

        def recreating(repo, command):
            (repo / ARTIFACT).write_text("recreated\n", encoding="utf-8")
            return 0, {}

        with self.assertRaises(adopt_migrate.adopt_inspection.AdoptError) as caught:
            adopt_migrate.migrate(root, MIGRATION_THREE, committed_manifest(),
                                  source, recreating)
        self.assertEqual(caught.exception.repair_id,
                         "adopt.migration.retired_file_recreated")
        self.assertEqual([v["pointer"] for v in caught.exception.violations],
                         [f"/{ARTIFACT}"])
        self.assertEqual(tree_snapshot(root), before)
        self.assertEqual((root / ARTIFACT).read_text("utf-8"), "original\n")

    def test_an_edit_git_cannot_see_is_refused_and_kept(self):
        def tracked(root):
            (root / ARTIFACT).parent.mkdir(parents=True)
            (root / ARTIFACT).write_text("original\n", encoding="utf-8")

        for flag in ("--assume-unchanged", "--skip-worktree"):
            with self.subTest(flag):
                root = self.root(before=tracked)
                git(root, "update-index", flag, ARTIFACT)
                (root / ARTIFACT).write_text("edited\n", encoding="utf-8")
                self.assert_refused(
                    root, "adopt.migration.artifact_modified", [f"/{ARTIFACT}"])
                self.assertEqual((root / ARTIFACT).read_text("utf-8"), "edited\n")

    def test_a_tracked_file_named_like_the_artifacts_directory_is_not_deleted(self):
        def tracked(root):
            (root / ".agents/artifacts").write_text("a file\n", encoding="utf-8")

        root = self.root(before=tracked)
        report = self.assert_migrates(root)
        self.assertEqual((root / ".agents/artifacts").read_text("utf-8"), "a file\n")
        self.assertNotIn(".agents/artifacts", report["written"])

    def test_a_schema_version_that_is_not_an_integer_is_not_applicable(self):
        for value in (2.0, True):
            with self.subTest(value=value):
                root = self.root(lambda c: c.update(schema_version=value))
                contract = self.contract_bytes(root)
                code, out, err = self.migrate(root)
                self.assertEqual(code, 2, err)
                self.assertEqual(json.loads(out)["error"]["repair_id"],
                                 "adopt.migration.not_applicable")
                self.assertEqual(self.contract_bytes(root), contract)

    def test_a_checkout_pinning_an_older_platform_is_refused(self):
        def pinned(c):
            c["platform"] = {"min_inclusive": "2.0.0", "max_exclusive": "3.0.0"}

        def older(root):
            manifest = root / derived_values.TREE_MANIFEST
            document = json.loads(manifest.read_text("utf-8"))
            document["platform_version"] = "2.0.0"
            manifest.write_text(json.dumps(document), encoding="utf-8")

        root = self.root(pinned, before=older)
        self.assert_refused(root, "adopt.migration.pinned_platform_too_old", ["/platform"])

    def test_an_unstaged_edit_to_a_tracked_artifact_is_refused_and_kept(self):
        def tracked(root):
            (root / ARTIFACT).parent.mkdir(parents=True)
            (root / ARTIFACT).write_text("original\n", encoding="utf-8")

        root = self.root(before=tracked)
        (root / ARTIFACT).write_text("edited\n", encoding="utf-8")
        (root / "notes.txt").write_text("notes\n", encoding="utf-8")
        self.assert_refused(root, "adopt.migration.artifact_modified", [f"/{ARTIFACT}"])
        self.assertEqual((root / ARTIFACT).read_text("utf-8"), "edited\n")
        self.assertEqual(git(root, "diff", "--cached", "--name-only"), "")
        with self.subTest("staged"):
            root = self.root(before=tracked)
            (root / ARTIFACT).write_text("staged\n", encoding="utf-8")
            git(root, "add", ARTIFACT)
            self.assert_migrates(root)
            self.assertFalse((root / ARTIFACT).exists())
            self.assertEqual(git(root, "show", f":{ARTIFACT}"), "staged\n")

    def test_a_symlinked_artifact_directory_is_refused(self):
        def tracked(root):
            (root / ARTIFACT).parent.mkdir(parents=True)
            (root / ARTIFACT).write_text("original\n", encoding="utf-8")

        root = self.root(before=tracked)
        (root / "elsewhere").mkdir()
        (root / ".agents/artifacts/specs").rename(root / "elsewhere/specs")
        (root / ".agents/artifacts/specs").symlink_to("../../elsewhere/specs")
        code, out, err = self.migrate(root)
        self.assertEqual(code, 2, err)
        error = json.loads(out)["error"]
        self.assertEqual(error["repair_id"], "adopt.migration.symlink_target")
        self.assertEqual([v["pointer"] for v in error["violations"]], [f"/{ARTIFACT}"])
        self.assertEqual((root / "elsewhere/specs/old.md").read_text("utf-8"), "original\n")

    def test_a_resolver_refusal_restores_the_contract_and_the_retired_artifacts(self):
        install_home(self.home, mutated_manifest(project_schema_versions=[2]))

        def tracked(root):
            (root / ARTIFACT).parent.mkdir(parents=True)
            (root / ARTIFACT).write_text("original\n", encoding="utf-8")
            (root / ARTIFACT).chmod(0o755)

        root = self.root(before=tracked)
        before = tree_snapshot(root)
        names = (".agents/project.json", "AGENTS.md", "CLAUDE.md", ARTIFACT)
        contents = {name: (root / name).read_bytes() for name in names}
        mode = stat.S_IMODE((root / ARTIFACT).stat().st_mode)
        code, out, err = self.migrate(root)
        self.assertEqual(code, 2, err)
        self.assertEqual(json.loads(out)["error"]["repair_id"],
                         "adopt.migration.result_invalid")
        self.assertEqual(tree_snapshot(root), before)
        self.assertEqual({name: (root / name).read_bytes() for name in names}, contents)
        self.assertEqual(stat.S_IMODE((root / ARTIFACT).stat().st_mode), mode)
        self.assertEqual(git(root, "status", "--porcelain"), "")

    def test_the_schema_one_migration_reads_no_derivation_input(self):
        root = make_project_root(source_contract())
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        commit_all(root)
        with mock.patch.object(derived_values, "derive", side_effect=AssertionError("derive")), \
                mock.patch.object(attempt_history, "read", side_effect=AssertionError("read")):
            code, _, err = run("migrate", "--migration", MIGRATION,
                               "--repo-root", str(root), home=self.home)
        self.assertEqual(code, 0, err)

    def test_a_second_run_is_not_applicable(self):
        root = self.root()
        self.assert_migrates(root)
        commit_all(root, "migrated")
        code, out, _ = self.migrate(root)
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(out)["error"]["repair_id"],
                         "adopt.migration.not_applicable")
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

    def test_the_registry_names_exactly_the_manifests_migrations(self):
        self.assertEqual(
            list(adopt_migrate.MIGRATIONS),
            [m["id"] for m in committed_manifest()["migrations"]])
        self.assertEqual(list(adopt_migrate.MIGRATIONS), [MIGRATION, MIGRATION_THREE])


if __name__ == "__main__":
    unittest.main()
