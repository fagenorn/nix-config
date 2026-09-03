"""Contract tests for the resolver's platform gate: the manifest and the interval.

Two questions, both answered before the resolver looks at anything else. The
platform installation — the manifest under `$HOME/.agents/share` and the
library under `$HOME/.agents/lib/python` — has to be present and well formed
(R1.3, D12, D36), and the contract's `platform` interval has to parse as a
shape before its bounds can be compared against the installed platform version
(R2.1-R2.5, D7, D8, D9).

The cases live beside `test_resolve_project.py` rather than inside it because
that file is the review package's binding member; the fixtures, the temporary
`HOME` and the subprocess runners are imported from it, and no `TestCase`
crosses over, so neither file collects the other's tests (the pattern
`test_adopt_project_boundaries.py` established). The `platform-status`
subcommand that publishes these same facts has its own suite in
`test_resolve_platform_status.py`.
"""

from __future__ import annotations

import contextlib
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

# The sibling suite is imported as a module, so its directory has to be
# importable however this file was invoked — `python3 <path>` supplies it,
# `python3 -m unittest <path>` does not.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_resolve_project import (
    COMMITTED,
    LIBRARY,
    MANIFEST_MEMBERS,
    REPO_ROOT,
    SCRIPT,
    SUBCOMMANDS,
    InProcessTestCase,
    ResolverTestCase,
    assert_read_only,
    committed_manifest,
    library_members,
    load_module,
    make_home,
    make_stub_bin,
    mutated_manifest,
    run,
    run_with_path,
    source_contract,
)


class ManifestGateTest(ResolverTestCase):
    """R1.3: a broken platform installation refuses loudly, from every subcommand.

    `write-projections` is included deliberately: the gate has to close before
    the writer, not just before the two readers.
    """

    def refusals(self, manifest: object, root: Path) -> list[list[dict]]:
        """Refuse `resolver_failure` from every subcommand; return each list."""
        self.set_manifest(manifest)
        collected = []
        for subcommand in SUBCOMMANDS:
            with self.subTest(subcommand=subcommand):
                code, out, err = run(subcommand, "--repo-root", str(root),
                                     home=self.home)
                self.assertEqual(code, 2, err or out)
                payload = json.loads(out)
                self.assertEqual(sorted(payload), ["error"])
                error = payload["error"]
                self.assertEqual(sorted(error),
                                 ["code", "repair_id", "violations"])
                self.assertEqual(error["code"], "resolver_failure")
                self.assertTrue(error["repair_id"])
                self.assertTrue(error["violations"])
                pointers = [v["pointer"] for v in error["violations"]]
                self.assertEqual(pointers, sorted(pointers))
                for entry in error["violations"]:
                    self.assertEqual(sorted(entry), ["message", "pointer"])
                collected.append(error)
        repair_ids = {error["repair_id"] for error in collected}
        self.assertEqual(len(repair_ids), 1, repair_ids)
        return [error["violations"] for error in collected]

    def assert_pointers(self, manifest: object, expected: list[str]) -> None:
        for violations in self.refusals(manifest, self.make_root()):
            self.assertEqual([v["pointer"] for v in violations], expected)

    def assert_repair_id(self, manifest: object, expected: str) -> None:
        """The three whole-file failures share the empty pointer, so only the
        repair id tells a caller which one it hit."""
        self.set_manifest(manifest)
        root = self.make_root()
        for subcommand in SUBCOMMANDS:
            with self.subTest(subcommand=subcommand):
                code, out, _ = run(subcommand, "--repo-root", str(root),
                                   home=self.home)
                self.assertEqual(code, 2)
                self.assertEqual(json.loads(out)["error"]["repair_id"], expected)

    def test_a_missing_manifest_refuses(self):
        self.assert_pointers(None, [""])
        self.assert_repair_id(None, "platform.manifest.missing")

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0,
                     "root reads a 0000 file, so the case cannot be staged")
    def test_an_unreadable_manifest_refuses(self):
        root = self.make_root()
        self.set_manifest(COMMITTED)
        installed = self.home / ".agents" / "share" / "platform-manifest.json"
        installed.chmod(0o000)
        self.addCleanup(installed.chmod, 0o600)
        for subcommand in SUBCOMMANDS:
            with self.subTest(subcommand=subcommand):
                code, out, _ = run(subcommand, "--repo-root", str(root),
                                   home=self.home)
                self.assertEqual(code, 2)
                error = json.loads(out)["error"]
                self.assertEqual(error["code"], "resolver_failure")
                self.assertEqual([v["pointer"] for v in error["violations"]], [""])
                self.assertEqual(error["repair_id"],
                                 "platform.manifest.unreadable")

    def test_a_manifest_that_is_not_valid_json_refuses(self):
        self.assert_pointers("{", [""])
        self.assert_repair_id("{", "platform.manifest.parse")

    def test_a_manifest_that_is_not_an_object_refuses(self):
        self.assert_pointers([], [""])
        self.assert_repair_id([], "platform.manifest.not_object")

    def test_an_unexpected_member_refuses(self):
        self.assert_pointers(mutated_manifest(surprise=1), ["/surprise"])

    def test_a_missing_member_refuses(self):
        manifest = committed_manifest()
        del manifest["resolved_schema_version"]
        self.assert_pointers(manifest, ["/resolved_schema_version"])

    def test_a_non_semver_platform_version_refuses(self):
        self.assert_pointers(mutated_manifest(platform_version="one"),
                             ["/platform_version"])

    def test_a_malformed_schema_version_refuses(self):
        for value in (0, -1, True, "1"):
            with self.subTest(schema_version=value):
                self.assert_pointers(mutated_manifest(schema_version=value),
                                     ["/schema_version"])

    def test_a_malformed_resolved_schema_version_refuses(self):
        for value in (0, -1, True, "1"):
            with self.subTest(resolved_schema_version=value):
                self.assert_pointers(
                    mutated_manifest(resolved_schema_version=value),
                    ["/resolved_schema_version"])

    def test_a_malformed_project_schema_versions_refuses(self):
        cases = (
            ({}, "/project_schema_versions"),
            ([], "/project_schema_versions"),
            ([1, 1], "/project_schema_versions"),
            ([2, 1], "/project_schema_versions"),
            ([0], "/project_schema_versions/0"),
            ([True], "/project_schema_versions/0"),
            ([1, "2"], "/project_schema_versions/1"),
        )
        for value, pointer in cases:
            with self.subTest(project_schema_versions=value):
                self.assert_pointers(
                    mutated_manifest(project_schema_versions=value), [pointer])

    def test_the_refusal_bytes_are_stable_across_runs(self):
        root = self.make_root()
        self.set_manifest(None)
        first = run("resolve", "--repo-root", str(root), home=self.home)
        second = run("resolve", "--repo-root", str(root), home=self.home)
        self.assertEqual(first[0], 2)
        self.assertEqual(first[1], second[1])

    def test_the_gate_closes_before_the_repository_is_read(self):
        """A root with no contract at all still reports `resolver_failure`.

        Without the gate this repository is `not_onboarded`, which is exactly
        the masking R1.3 forbids — so the control below pins the other half:
        with a valid manifest the same root does refuse `not_onboarded`.
        """
        root = self.make_root(contract=False, projections=False)
        for subcommand in SUBCOMMANDS:
            with self.subTest(subcommand=subcommand, manifest="valid"):
                code, out, _ = run(subcommand, "--repo-root", str(root),
                                   home=self.home)
                self.assertEqual(code, 2)
                self.assertEqual(json.loads(out)["error"]["code"], "not_onboarded")
        self.set_manifest(None)
        for subcommand in SUBCOMMANDS:
            with self.subTest(subcommand=subcommand, manifest="missing"):
                code, out, _ = run(subcommand, "--repo-root", str(root),
                                   home=self.home)
                self.assertEqual(code, 2)
                self.assertEqual(json.loads(out)["error"]["code"],
                                 "resolver_failure")

    def test_a_manifest_refusal_leaves_the_tree_untouched(self):
        """SF-001: the gate reads the manifest and nothing else."""
        self.set_manifest(None)
        # A root each: `assert_read_only` commits its fixture before running,
        # and a second call against the same root has nothing left to commit.
        for subcommand in SUBCOMMANDS:
            with self.subTest(subcommand=subcommand):
                assert_read_only(self, self.make_root(), 2, subcommand)

    def test_a_manifest_refusal_runs_no_child_process(self):
        root = self.make_root()
        self.set_manifest(None)
        code, out, err = run_with_path(
            str(make_stub_bin(())), "resolve", "--repo-root", str(root),
            home=self.home)
        self.assertEqual(code, 2)
        self.assertEqual(err, "")
        self.assertEqual(json.loads(out)["error"]["code"], "resolver_failure")


class ManifestLifecycleArrayTest(ResolverTestCase):
    """D36: `migrations` is validated strictly; `deprecations` and `removals`
    are validated as arrays and never read."""

    def assert_pointer(self, changes: dict, expected: str) -> None:
        self.set_manifest(mutated_manifest(**changes))
        code, out, _ = run("resolve", "--repo-root", str(self.make_root()),
                           home=self.home)
        self.assertEqual(code, 2)
        error = json.loads(out)["error"]
        self.assertEqual(error["code"], "resolver_failure")
        self.assertEqual([v["pointer"] for v in error["violations"]], [expected])

    def test_migrations_must_be_an_array(self):
        self.assert_pointer({"migrations": {}}, "/migrations")

    def test_an_entry_must_be_an_object(self):
        self.assert_pointer({"migrations": ["1-2"]}, "/migrations/0")

    def test_an_entry_member_may_not_be_absent(self):
        self.assert_pointer(
            {"migrations": [{"id": "a", "from_schema": 1}]},
            "/migrations/0/to_schema")

    def test_an_entry_member_may_not_be_unexpected(self):
        self.assert_pointer(
            {"migrations": [
                {"id": "a", "from_schema": 1, "to_schema": 2, "note": "x"}]},
            "/migrations/0/note")

    def test_an_id_must_be_a_non_empty_string(self):
        for value in (1, "", None):
            with self.subTest(id=value):
                self.assert_pointer(
                    {"migrations": [
                        {"id": value, "from_schema": 1, "to_schema": 2}]},
                    "/migrations/0/id")

    def test_ids_must_be_distinct(self):
        self.assert_pointer(
            {"migrations": [
                {"id": "a", "from_schema": 1, "to_schema": 2},
                {"id": "a", "from_schema": 2, "to_schema": 3}]},
            "/migrations")

    def test_from_schema_must_be_a_positive_non_bool_integer(self):
        for value in ("1", True, 0, -1):
            with self.subTest(from_schema=value):
                self.assert_pointer(
                    {"migrations": [
                        {"id": "a", "from_schema": value, "to_schema": 2}]},
                    "/migrations/0/from_schema")

    def test_to_schema_must_be_a_positive_non_bool_integer(self):
        for value in ("2", True, 0, -1):
            with self.subTest(to_schema=value):
                self.assert_pointer(
                    {"migrations": [
                        {"id": "a", "from_schema": 1, "to_schema": value}]},
                    "/migrations/0/to_schema")

    def test_to_schema_must_be_one_step_past_from_schema(self):
        for value in (1, 3):
            with self.subTest(to_schema=value):
                self.assert_pointer(
                    {"migrations": [
                        {"id": "a", "from_schema": 1, "to_schema": value}]},
                    "/migrations/0/to_schema")

    def test_from_schemas_must_be_distinct(self):
        self.assert_pointer(
            {"migrations": [
                {"id": "a", "from_schema": 1, "to_schema": 2},
                {"id": "b", "from_schema": 1, "to_schema": 2}]},
            "/migrations")

    def test_from_schemas_must_ascend(self):
        self.assert_pointer(
            {"migrations": [
                {"id": "a", "from_schema": 2, "to_schema": 3},
                {"id": "b", "from_schema": 1, "to_schema": 2}]},
            "/migrations")

    def test_a_well_formed_migration_chain_is_accepted(self):
        self.set_manifest(mutated_manifest(migrations=[
            {"id": "1-to-2", "from_schema": 1, "to_schema": 2},
            {"id": "2-to-3", "from_schema": 2, "to_schema": 3}]))
        code, out, err = run("resolve", "--repo-root", str(self.make_root()),
                             home=self.home)
        self.assertEqual(code, 0, err or out)

    def test_deprecations_and_removals_must_be_arrays(self):
        for name in ("deprecations", "removals"):
            for value in ({}, 1, "x"):
                with self.subTest(member=name, value=value):
                    self.assert_pointer({name: value}, f"/{name}")

    def test_opaque_array_entries_are_never_read(self):
        """Neither array has a declared entry shape at v1, so any entry passes."""
        self.set_manifest(mutated_manifest(
            deprecations=[{"anything": [1, 2]}], removals=["whatever"]))
        code, out, err = run("resolve", "--repo-root", str(self.make_root()),
                             home=self.home)
        self.assertEqual(code, 0, err or out)


class SemverBoundaryTest(ResolverTestCase):
    """D9: strict `MAJOR.MINOR.PATCH`, exercised through the manifest validator."""

    def test_a_loose_version_is_rejected(self):
        for value in ("1.0", "1.0.0.0", "v1.0.0", "1.0.0-rc.1", "1.0.0+build",
                      "01.0.0"):
            with self.subTest(platform_version=value):
                self.set_manifest(mutated_manifest(platform_version=value))
                code, out, _ = run("resolve", "--repo-root",
                                   str(self.make_root()), home=self.home)
                self.assertEqual(code, 2)
                error = json.loads(out)["error"]
                self.assertEqual(error["code"], "resolver_failure")
                self.assertEqual([v["pointer"] for v in error["violations"]],
                                 ["/platform_version"])

    def test_a_strict_version_is_accepted(self):
        # Both spellings sit inside this repository's committed contract
        # interval, so the range check (R2.3) cannot mask the shape question
        # this case is about.
        for value in ("1.0.0", "1.20.30"):
            with self.subTest(platform_version=value):
                self.set_manifest(mutated_manifest(platform_version=value))
                code, out, err = run("resolve", "--repo-root",
                                     str(self.make_root()), home=self.home)
                self.assertEqual(code, 0, err or out)


class PlatformLibraryTest(ResolverTestCase):
    """R1.3 / D12: the library half of the installation refuses like the
    manifest half.

    Every case here runs a copy of the script from `$HOME/.agents/bin`, the
    deployed layout, because in the repository checkout the script's own
    directory holds `agent_platform.py` as a sibling — so a run from `scripts/`
    imports the library whatever `HOME` says and could never observe an
    uninstalled one.
    """

    def deployed(self, home: Path) -> Path:
        binary = home / ".agents" / "bin" / "resolve-project"
        binary.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(SCRIPT, binary)
        return binary

    def run_deployed(self, home: Path, *args: str, unset_home: bool = False,
                     pythonpath: str | None = None) -> tuple[int, str, str]:
        binary = self.deployed(home)
        env = {**os.environ, "HOME": str(home)}
        # `PYTHONPATH` would be a second lookup path the deployed machine does
        # not have; the runner's own may carry one, so each case states the one
        # it means to present.
        env.pop("PYTHONPATH", None)
        if pythonpath is not None:
            env["PYTHONPATH"] = pythonpath
        if unset_home:
            env.pop("HOME", None)
        proc = subprocess.run(
            [sys.executable, str(binary), *args],
            capture_output=True, text=True, timeout=60,
            cwd=str(home), env=env)
        return proc.returncode, proc.stdout, proc.stderr

    def assert_library_refusal(self, code: int, out: str, err: str) -> None:
        self.assertEqual(code, 2, err or out)
        self.assertEqual(err, "")
        payload = json.loads(out)
        self.assertEqual(sorted(payload), ["error"])
        error = payload["error"]
        self.assertEqual(sorted(error), ["code", "repair_id", "violations"])
        self.assertEqual(error["code"], "resolver_failure")
        self.assertEqual(error["repair_id"], "platform.library.missing")
        self.assertTrue(error["violations"])
        for entry in error["violations"]:
            self.assertEqual(sorted(entry), ["message", "pointer"])

    def test_an_uninstalled_library_refuses_on_stdout(self):
        """A valid manifest is installed, so only the missing library can refuse."""
        home = make_home(library=False)
        root = self.make_root()
        for subcommand in SUBCOMMANDS:
            with self.subTest(subcommand=subcommand):
                self.assert_library_refusal(
                    *self.run_deployed(home, subcommand, "--repo-root", str(root)))

    def test_a_library_missing_one_member_refuses_the_same_way(self):
        """The library and the binary are installed separately, so an older
        library can pair with a newer resolver. Every member the resolver uses
        must therefore refuse as `platform.library.missing`, not as an
        `AttributeError` swallowed into `resolver.internal` (R1.3, D12).
        """
        root = self.make_root()
        source = LIBRARY.read_text("utf-8")
        for name in library_members():
            with self.subTest(member=name):
                home = make_home()
                # A module-level `del` after the definitions: the module still
                # imports, and only this one attribute is gone.
                (home / ".agents" / "lib" / "python"
                 / "agent_platform.py").write_text(
                    source + f"\n\ndel {name}\n", encoding="utf-8")
                self.assert_library_refusal(
                    *self.run_deployed(home, "resolve", "--repo-root", str(root)))

    def test_the_declared_members_are_exactly_the_members_used(self):
        """The guard is only as wide as its tuple: a member the resolver reads
        but does not declare is a hole this case closes."""
        used = set(re.findall(r"\bagent_platform\.([A-Za-z_][A-Za-z0-9_]*)",
                              SCRIPT.read_text("utf-8")))
        # `agent_platform.py` appears inside the refusal message, not as an
        # attribute read.
        used.discard("py")
        self.assertEqual(sorted(library_members()), sorted(used))

    def test_an_unset_home_refuses_on_stdout(self):
        home = make_home()
        code, out, err = self.run_deployed(
            home, "resolve", "--repo-root", str(self.make_root()),
            unset_home=True)
        self.assert_library_refusal(code, out, err)

    def test_the_refusal_bytes_are_stable_across_runs(self):
        home = make_home(library=False)
        root = self.make_root()
        first = self.run_deployed(home, "resolve", "--repo-root", str(root))
        second = self.run_deployed(home, "resolve", "--repo-root", str(root))
        self.assertEqual(first[0], 2)
        self.assertEqual(first[1], second[1])

    def test_an_importable_library_is_not_an_installed_one(self):
        """The guard is about *which* file answered the import, not about
        whether the name imports at all.

        With nothing installed at the one path, an `agent_platform` the
        interpreter can still reach — through `PYTHONPATH` here, through
        site-packages on another machine — must not answer in its place, or
        "an uninstalled one is caught here" is not true of any machine whose
        environment carries one.
        """
        home = make_home(library=False)
        elsewhere = Path(tempfile.mkdtemp()).resolve()
        shutil.copy(LIBRARY, elsewhere / "agent_platform.py")
        self.assert_library_refusal(*self.run_deployed(
            home, "resolve", "--repo-root", str(self.make_root()),
            pythonpath=str(elsewhere)))

    def test_the_installed_library_answers_in_the_deployed_layout(self):
        """The control: the same shape with the library installed resolves."""
        home = make_home()
        code, out, err = self.run_deployed(
            home, "resolve", "--repo-root", str(self.make_root()))
        self.assertEqual(code, 0, err or out)
        self.assertEqual(json.loads(out)["schema_version"], 1)

    def test_a_usage_error_still_belongs_to_argparse(self):
        """D16: the library guard runs after parsing, so no JSON appears here."""
        home = make_home(library=False)
        code, out, err = self.run_deployed(home)
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertNotEqual(err, "")


class CommittedManifestTest(ResolverTestCase):
    """The committed manifest is the one the store installs (D1), so the suite
    checks that file rather than a fixture."""

    def test_it_declares_exactly_the_seven_members_with_the_v1_values(self):
        manifest = committed_manifest()
        self.assertEqual(sorted(manifest), sorted(MANIFEST_MEMBERS))
        self.assertEqual(manifest["schema_version"], 1)
        self.assertEqual(manifest["platform_version"], "1.0.0")
        self.assertEqual(manifest["project_schema_versions"], [1])
        self.assertEqual(manifest["resolved_schema_version"], 1)
        for name in ("migrations", "deprecations", "removals"):
            with self.subTest(member=name):
                self.assertEqual(manifest[name], [])

    def test_it_loads_and_validates(self):
        # `setUp` installs this exact file; a subcommand that gets as far as
        # answering has loaded and validated it.
        root = self.make_root()
        for subcommand in SUBCOMMANDS:
            with self.subTest(subcommand=subcommand):
                code, out, err = run(subcommand, "--repo-root", str(root),
                                     home=self.home)
                self.assertEqual(code, 0, err or out)



class PlatformIntervalShapeTest(ResolverTestCase):
    """R2.1 / R2.2: the interval's shape is `invalid_contract`, never a range
    verdict. A malformed interval and an out-of-range one are two different
    refusals and are never confused."""

    CASES = (
        ("the member is absent", None, "/platform"),
        ("the member is not an object", "1.0.0", "/platform"),
        ("min_inclusive is absent",
         {"max_exclusive": "2.0.0"}, "/platform/min_inclusive"),
        ("max_exclusive is absent",
         {"min_inclusive": "1.0.0"}, "/platform/max_exclusive"),
        ("an unexpected member",
         {"min_inclusive": "1.0.0", "max_exclusive": "2.0.0", "pin": "1.0.0"},
         "/platform/pin"),
        ("a non-string bound",
         {"min_inclusive": 1, "max_exclusive": "2.0.0"},
         "/platform/min_inclusive"),
        ("a null bound",
         {"min_inclusive": "1.0.0", "max_exclusive": None},
         "/platform/max_exclusive"),
        ("a non-SemVer bound",
         {"min_inclusive": "1.0", "max_exclusive": "2.0.0"},
         "/platform/min_inclusive"),
        ("a pre-release bound",
         {"min_inclusive": "1.0.0", "max_exclusive": "2.0.0-rc.1"},
         "/platform/max_exclusive"),
        ("a build-metadata bound",
         {"min_inclusive": "1.0.0+build", "max_exclusive": "2.0.0"},
         "/platform/min_inclusive"),
        ("an exact pin",
         {"min_inclusive": "1.0.0", "max_exclusive": "1.0.0"},
         "/platform/max_exclusive"),
        ("an inverted interval",
         {"min_inclusive": "2.0.0", "max_exclusive": "1.9.9"},
         "/platform/max_exclusive"),
    )

    def test_each_malformed_interval_is_an_invalid_contract_violation(self):
        for label, value, pointer in self.CASES:
            with self.subTest(case=label):
                contract = source_contract()
                if value is None:
                    del contract["platform"]
                else:
                    contract["platform"] = value
                code, payload, _ = self.resolve(self.make_root(contract))
                self.assertEqual(code, 2)
                error = payload["error"]
                self.assertEqual(error["code"], "invalid_contract")
                self.assertNotIn("reason_code", error)
                self.assertIn(pointer,
                              [v["pointer"] for v in error["violations"]])
                self.assertNotIn("schema_version", payload)


class PlatformRangeTest(ResolverTestCase):
    """R2.3 / R2.4: the range and schema-set questions, answered only after
    shape validation has passed, as `unsupported_schema` with a reason code."""

    def assert_unsupported(self, code: int, payload: object,
                           reason_code: str, pointer: str) -> None:
        self.assertEqual(code, 2)
        error = payload["error"]
        self.assertEqual(error["code"], "unsupported_schema")
        self.assertEqual(error["reason_code"], reason_code)
        self.assertEqual([v["pointer"] for v in error["violations"]], [pointer])
        self.assertNotIn("schema_version", payload)

    def test_a_platform_at_the_max_bound_is_out_of_range(self):
        # The committed contract declares [1.0.0, 2.0.0); `max_exclusive` is
        # exclusive, so 2.0.0 is already outside it.
        self.set_manifest(mutated_manifest(platform_version="2.0.0"))
        code, payload, _ = self.resolve(self.make_root())
        self.assert_unsupported(code, payload, "platform_too_new", "/platform")

    def test_a_platform_below_the_min_bound_is_out_of_range(self):
        self.set_manifest(mutated_manifest(platform_version="0.9.0"))
        code, payload, _ = self.resolve(self.make_root())
        self.assert_unsupported(code, payload, "platform_too_old", "/platform")

    def test_the_min_bound_itself_is_inside_the_range(self):
        self.set_manifest(mutated_manifest(platform_version="1.0.0"))
        code, snap, err = self.resolve(self.make_root())
        self.assertEqual(code, 0, err)
        self.assertEqual(snap["schema_version"], 1)

    def test_a_malformed_interval_never_reaches_the_range_check(self):
        """An out-of-range platform *and* a malformed interval: the shape
        answer wins, because the range check runs only after it passes."""
        self.set_manifest(mutated_manifest(platform_version="9.9.9"))
        contract = source_contract()
        contract["platform"] = {"min_inclusive": "1.0", "max_exclusive": "2.0.0"}
        code, payload, _ = self.resolve(self.make_root(contract))
        self.assertEqual(code, 2)
        self.assertEqual(payload["error"]["code"], "invalid_contract")
        self.assertNotIn("reason_code", payload["error"])

    def test_a_schema_absent_from_the_manifest_set_is_unsupported(self):
        contract = source_contract()
        contract["schema_version"] = 2
        code, payload, _ = self.resolve(self.make_root(contract))
        self.assert_unsupported(code, payload, "project_schema_unsupported",
                                "/schema_version")
        self.assertEqual(payload["error"]["repair_id"],
                         "contract.schema_version.unsupported")

    def test_a_supported_non_current_schema_resolves(self):
        """R2.5: no refusal, no deprecation notice, still four members."""
        self.set_manifest(mutated_manifest(project_schema_versions=[1, 2]))
        code, snap, err = self.resolve(self.make_root())
        self.assertEqual(code, 0, err)
        self.assertEqual(
            sorted(snap),
            ["bindings", "capabilities", "project", "schema_version"])
        for word in ("deprecat", "removal", "migration", "notice"):
            self.assertNotIn(word, json.dumps(snap).lower())

    def test_the_snapshot_version_is_the_manifests_resolved_version(self):
        """D8: the snapshot's interface version comes from the manifest, not
        from the contract's declared schema and not from a source literal."""
        self.set_manifest(mutated_manifest(
            project_schema_versions=[1, 2], resolved_schema_version=2))
        contract = source_contract()
        self.assertEqual(contract["schema_version"], 1)
        code, snap, err = self.resolve(self.make_root(contract))
        self.assertEqual(code, 0, err)
        self.assertEqual(snap["schema_version"], 2)


class ReasonCodePositionTest(ResolverTestCase):
    """D7: `reason_code` is a member of the error object exactly when the code
    is `unsupported_schema`, and of no other refusal this tool can emit."""

    def refusal(self, *args: str, root: Path | None = None) -> dict:
        code, out, err = run(*args, home=self.home)
        self.assertEqual(code, 2, err or out)
        return json.loads(out)["error"]

    def test_every_other_error_code_carries_no_reason_code(self):
        cases: list[tuple[str, dict]] = []

        empty = Path(tempfile.mkdtemp()).resolve()
        cases.append(("not_onboarded", self.refusal(
            "resolve", "--repo-root", str(empty))))

        contract = source_contract()
        del contract["bindings"]["deploy"]
        cases.append(("invalid_contract", self.refusal(
            "resolve", "--repo-root", str(self.make_root(contract)))))

        drifted = self.make_root()
        (drifted / "AGENTS.md").write_text("hand edited\n", encoding="utf-8")
        cases.append(("invalid_projection", self.refusal(
            "check-projections", "--repo-root", str(drifted))))

        cases.append(("capability_unavailable", self.refusal(
            "resolve", "--repo-root", str(self.make_root()),
            "--require", "release")))

        broken = self.make_root()
        self.set_manifest(None)
        cases.append(("resolver_failure", self.refusal(
            "resolve", "--repo-root", str(broken))))

        seen = {code for code, _ in cases}
        self.assertEqual(seen, {"not_onboarded", "invalid_contract",
                                "invalid_projection", "capability_unavailable",
                                "resolver_failure"})
        for code, error in cases:
            with self.subTest(code=code):
                self.assertEqual(error["code"], code)
                self.assertNotIn("reason_code", error)
                self.assertEqual(sorted(error),
                                 ["code", "repair_id", "violations"])

    def test_unsupported_schema_always_carries_one_from_the_closed_set(self):
        closed = ("platform_too_old", "platform_too_new",
                  "project_schema_unsupported")
        contract = source_contract()
        contract["schema_version"] = 2
        errors = [self.refusal("resolve", "--repo-root",
                               str(self.make_root(contract)))]
        for version in ("0.9.0", "2.0.0"):
            self.set_manifest(mutated_manifest(platform_version=version))
            errors.append(self.refusal("resolve", "--repo-root",
                                       str(self.make_root())))
        for error in errors:
            self.assertEqual(error["code"], "unsupported_schema")
            self.assertIn(error["reason_code"], closed)
            self.assertEqual(
                sorted(error),
                ["code", "reason_code", "repair_id", "violations"])
        self.assertEqual({error["reason_code"] for error in errors},
                         set(closed))


class CommittedIntervalTest(ResolverTestCase):
    """The mutual gate: the committed manifest and the committed contract
    check each other, so bumping one without the other fails here."""

    def test_the_committed_contract_declares_the_interval(self):
        platform = source_contract()["platform"]
        self.assertEqual(sorted(platform), ["max_exclusive", "min_inclusive"])
        self.assertEqual(platform["min_inclusive"], "1.0.0")
        self.assertEqual(platform["max_exclusive"], "2.0.0")

    def test_the_committed_platform_version_is_inside_the_interval(self):
        platform = source_contract()["platform"]
        version = committed_manifest()["platform_version"]
        low = tuple(int(part) for part in platform["min_inclusive"].split("."))
        high = tuple(int(part) for part in platform["max_exclusive"].split("."))
        active = tuple(int(part) for part in version.split("."))
        self.assertTrue(low <= active < high,
                        f"{version} is outside "
                        f"[{platform['min_inclusive']}, "
                        f"{platform['max_exclusive']})")

    def test_the_committed_schema_version_is_one_the_manifest_supports(self):
        self.assertIn(source_contract()["schema_version"],
                      committed_manifest()["project_schema_versions"])

    def test_this_repository_resolves_under_the_committed_manifest(self):
        code, out, err = run("resolve", "--repo-root", str(REPO_ROOT),
                             home=self.home)
        self.assertEqual(code, 0, err or out)
        self.assertEqual(json.loads(out)["schema_version"],
                         committed_manifest()["resolved_schema_version"])


class SchemaReasonDispatchTest(InProcessTestCase):
    """D7: both mappings over `SCHEMA_REASON_CODES` are exhaustive, and the
    `reason_code` position rule is enforced where the object is emitted rather
    than trusted from the caller."""

    def setUp(self) -> None:
        super().setUp()
        self.module = load_module()
        self.assertTrue(self.module.bootstrap_platform_library())
        self.codes = self.module.agent_platform.SCHEMA_REASON_CODES

    def test_the_closed_set_is_exactly_the_four_members(self):
        self.assertEqual(self.codes,
                         ("platform_too_old", "platform_too_new",
                          "project_schema_unsupported",
                          "project_identity_mismatch"))

    def test_every_member_maps_to_a_repair_id_and_a_message(self):
        ids, messages = set(), set()
        for reason_code in self.codes:
            with self.subTest(reason_code=reason_code):
                repair_id = self.module.schema_reason_repair_id(reason_code)
                message = self.module.schema_reason_message(reason_code)
                self.assertTrue(repair_id and isinstance(repair_id, str))
                self.assertTrue(message and isinstance(message, str))
                ids.add(repair_id)
                messages.add(message)
        self.assertEqual(len(ids), len(self.codes))
        self.assertEqual(len(messages), len(self.codes))

    def test_an_unknown_reason_code_raises_in_both_dispatches(self):
        for mapping in (self.module.schema_reason_repair_id,
                        self.module.schema_reason_message):
            with self.subTest(mapping=mapping.__name__):
                with self.assertRaises(ValueError):
                    mapping("platform_sideways")

    def test_emit_error_refuses_a_misplaced_reason_code(self):
        buffer = io.StringIO()
        with self.assertRaises(ValueError):
            with contextlib.redirect_stdout(buffer):
                self.module.emit_error(
                    "invalid_contract", "contract.parse",
                    [{"pointer": "", "message": "x"}], "platform_too_old")
        with self.assertRaises(ValueError):
            with contextlib.redirect_stdout(buffer):
                self.module.emit_error(
                    "unsupported_schema", "contract.platform.too_old",
                    [{"pointer": "", "message": "x"}], None)
        with self.assertRaises(ValueError):
            with contextlib.redirect_stdout(buffer):
                self.module.emit_error(
                    "unsupported_schema", "contract.platform.too_old",
                    [{"pointer": "", "message": "x"}], "platform_sideways")
        self.assertEqual(buffer.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
