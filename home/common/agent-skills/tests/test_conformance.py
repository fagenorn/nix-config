"""Contract tests for scripts/conformance.

Runs the engine as a subprocess against temporary repository roots and parses
its stdout, the seam test_resolve_project.py established (D16). The module is
imported only for the seams no subprocess run can reach.

Every run is environment-hermetic (D35): the child never inherits the caller's
environment, so no test can reach the network, the caller's credentials or a
tool the fixture did not place. HERMETIC_ENV points PATH at a stub bin holding
one exit-0 script per tool the contract names; a case that needs a different
tool outcome builds its own bin with make_stub_bin and overrides PATH.
"""

from __future__ import annotations

import contextlib
import fcntl
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "conformance.py"
REPO_ROOT = Path(__file__).resolve().parents[4]
STUB_TOOLS = ("codex", "gh", "git", "just")


def make_stub_bin(directory: Path, exits: dict | None = None) -> str:
    """A bin directory holding one executable stub per STUB_TOOLS.

    Each stub prints nothing and exits 0 unless `exits` names a different code
    for it, so a fixture decides every tool outcome the engine can observe.
    """
    directory.mkdir(parents=True, exist_ok=True)
    for tool in STUB_TOOLS:
        stub = directory / tool
        stub.write_text(f"#!/bin/sh\nexit {(exits or {}).get(tool, 0)}\n",
                        encoding="utf-8")
        stub.chmod(0o755)
    return str(directory)


_HERMETIC_HOME = tempfile.mkdtemp(prefix="conformance-home-")
HERMETIC_ENV = {
    "PATH": make_stub_bin(Path(tempfile.mkdtemp(prefix="conformance-bin-"))),
    "HOME": _HERMETIC_HOME,
    "TMPDIR": _HERMETIC_HOME,
    "LANG": "C",
}


def run(*args: str, env: dict | None = None,
        cwd: str | Path | None = None) -> tuple[int, str, str]:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, timeout=60,
        env=HERMETIC_ENV if env is None else env, cwd=None if cwd is None else str(cwd),
    )
    return proc.returncode, proc.stdout, proc.stderr


@contextlib.contextmanager
def fixture():
    """A temporary directory, as a Path."""
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp)


def doctor(case, root, *extra: str, env: dict | None = None) -> tuple[dict, dict]:
    """One `doctor` run: asserts exit 0, returns (report, {check id: check}).

    Tasks 2-7 read every check through this, so no case re-spells the run, the
    exit assertion or the id index.
    """
    code, out, err = run("run", "--purpose", "doctor", "--repo-root", str(root),
                         *extra, env=env)
    case.assertEqual(code, 0, err)
    report = json.loads(out)
    return report, {c["id"]: c for c in report["checks"]}


def make_root(tmp: Path) -> Path:
    """A temporary project root a clean `doctor` run passes on.

    The committed contract, its instruction source and both projection targets
    are copied byte-for-byte, every directory a knowledge path names is
    created, and the root ignore file covers `.agents/runtime/`, so a fixture
    refuses only for the mutation a case applies to it.
    """
    root = tmp / "project"
    (root / ".agents" / "instructions").mkdir(parents=True)
    for relative in (".agents/project.json", ".agents/instructions/bootstrap.md",
                     "AGENTS.md", "CLAUDE.md"):
        shutil.copy2(REPO_ROOT / relative, root / relative)
    paths = json.loads(
        (root / ".agents/project.json").read_text(encoding="utf-8")
    )["bindings"]["paths"]
    for member in ("context", "standards", "architecture", "operations",
                   "hints", "rejections"):
        for entry in paths[member]:
            target = root / entry
            if not target.exists():  # `architecture` names CLAUDE.md, already copied
                target.mkdir(parents=True)
    (root / ".gitignore").write_text(".agents/runtime/\n", encoding="utf-8")
    return root


def load_module():
    """The engine as an imported module, loaded by path (its name is hyphenated).

    Registered under its spec name before exec_module: the module uses
    postponed annotations, and dataclass construction resolves them through
    sys.modules, so an unregistered module fails to import at all (D36).
    """
    import importlib.util
    from importlib.machinery import SourceFileLoader

    fullname = "conformance_engine"
    spec = importlib.util.spec_from_loader(
        fullname, SourceFileLoader(fullname, str(SCRIPT)))
    module = importlib.util.module_from_spec(spec)
    sys.modules[fullname] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(fullname, None)
        raise
    return module


class ReportAssertions:
    """One assertion both report suites share: the engine's own output, judged
    by the very schema every consumer checks a report against."""

    def assert_validates(self, report: dict) -> None:
        with fixture() as tmp:
            path = tmp / "report.json"
            path.write_text(json.dumps(report), encoding="utf-8")
            code, out, _ = run("validate-report", "--input", str(path))
            self.assertEqual(code, 0, out)


def valid_report() -> dict:
    """A minimal schema-valid report: one failed check and the repair it names."""
    return {
        "schema_version": 1,
        "subject": {"project_id": "fagenorn/nix-config", "root": "/tmp/x",
                    "revision": None, "platform": {"system": "Darwin", "machine": "arm64"}},
        "request": {"purpose": "doctor", "offline": False,
                    "required_capabilities": [], "platform_target": "Darwin/arm64"},
        "outcome": {"status": "failed", "primary_check_id": "repository.contract.present"},
        "checks": [{"id": "repository.contract.present", "domain": "repository",
                    "subject_kind": "contract", "requirement": "required",
                    "status": "failed", "reason_code": "not_onboarded",
                    "repair_id": "onboarding.contract.missing", "facts": {}}],
        "repairs": [{"repair_id": "onboarding.contract.missing",
                     "module": "resolve-project", "safety_class": "user_action",
                     "operation": None}],
    }


def write_report(tmp: Path, mutate=None) -> Path:
    report = valid_report()
    if mutate is not None:
        mutate(report)
    path = tmp / "report.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    return path


# --------------------------------------------------------------------------
# The refusal table: one row per invariant, each mutation leaving exactly one
# violation reachable.
# --------------------------------------------------------------------------


def quiesce(report: dict) -> None:
    """Repair the collateral a mutation of the lone check would cascade into.

    Drops the repair that check names and resets the outcome to the one its
    remaining statuses imply, so a row is refused for the invariant it names
    and for nothing else.
    """
    report["checks"][0]["repair_id"] = None
    report["repairs"].clear()
    report["outcome"] = {"status": "passed", "primary_check_id": None}


def _extra_top_level_member(report: dict) -> None:
    report["extra"] = 1


def _missing_top_level_member(report: dict) -> None:
    report.pop("repairs")


def _timestamp_member(report: dict) -> None:
    report["subject"]["timestamp"] = 0


def _unknown_status(report: dict) -> None:
    report["checks"][0]["status"] = "skipped"


def _unknown_safety_class(report: dict) -> None:
    report["repairs"][0]["safety_class"] = "risky"


def _unknown_subject_kind(report: dict) -> None:
    report["checks"][0]["subject_kind"] = "widget"


def _dangling_repair_id(report: dict) -> None:
    report["repairs"].clear()


def _unreferenced_repair(report: dict) -> None:
    report["checks"][0]["repair_id"] = None


def _oversized_facts(report: dict) -> None:
    report["checks"][0]["facts"] = {f"k{index}": index for index in range(9)}


def _overlong_fact_string(report: dict) -> None:
    report["checks"][0]["facts"] = {"k": "x" * 201}


def _nested_object_fact(report: dict) -> None:
    report["checks"][0]["facts"] = {"k": {"a": 1}}


def _timestamp_fact_key(report: dict) -> None:
    report["checks"][0]["facts"] = {"created_at": 1}


def _unsorted_required_capabilities(report: dict) -> None:
    report["request"]["required_capabilities"] = ["worktrees", "tracker"]


def _repairs_out_of_order(report: dict) -> None:
    # A second failed check keeps `checks` sorted by id, and its repair sorts
    # after the one already there — so inserting it first makes `repairs`
    # descending while every other invariant still holds.
    report["checks"].append({
        "id": "repository.projection.fresh", "domain": "repository",
        "subject_kind": "projection", "requirement": "required",
        "status": "failed", "reason_code": "invalid_projection",
        "repair_id": "projection.regenerate", "facts": {}})
    report["repairs"].insert(0, {
        "repair_id": "projection.regenerate", "module": "resolve-project",
        "safety_class": "worktree", "operation": None})


def _failed_check_under_passed_outcome(report: dict) -> None:
    report["outcome"] = {"status": "passed", "primary_check_id": None}


def _required_not_run_under_passed_outcome(report: dict) -> None:
    check = report["checks"][0]
    check["status"] = "not_run"
    check["reason_code"] = "offline_constraint"
    report["outcome"] = {"status": "passed", "primary_check_id": None}


def _primary_check_id_names_a_passing_check(report: dict) -> None:
    report["checks"].append({
        "id": "verification.command.available", "domain": "verification",
        "subject_kind": "command", "requirement": "optional",
        "status": "passed", "reason_code": None, "repair_id": None,
        "facts": {}})
    report["outcome"]["primary_check_id"] = "verification.command.available"


def _suppressed_check_carrying_a_repair(report: dict) -> None:
    check = report["checks"][0]
    check["status"] = "suppressed"
    check["reason_code"] = None
    check["facts"] = {"suppressed_by": "x"}
    report["outcome"] = {"status": "passed", "primary_check_id": None}


def _suppressed_check_without_suppressed_by(report: dict) -> None:
    check = report["checks"][0]
    check["status"] = "suppressed"
    check["reason_code"] = None
    check["facts"] = {}
    quiesce(report)


def _passed_check_carrying_a_reason_code(report: dict) -> None:
    report["checks"][0]["status"] = "passed"
    quiesce(report)


REFUSALS = {
    "extra top-level member": (_extra_top_level_member, "/extra"),
    "missing top-level member": (_missing_top_level_member, "/repairs"),
    "timestamp member": (_timestamp_member, "/subject/timestamp"),
    "unknown status": (_unknown_status, "/checks/0/status"),
    "unknown safety class": (_unknown_safety_class, "/repairs/0/safety_class"),
    "unknown subject kind": (_unknown_subject_kind, "/checks/0/subject_kind"),
    "dangling repair id": (_dangling_repair_id, "/repairs"),
    "unreferenced repair": (_unreferenced_repair, "/repairs"),
    "oversized facts": (_oversized_facts, "/checks/0/facts"),
    "overlong fact string": (_overlong_fact_string, "/checks/0/facts/k"),
    "nested object fact": (_nested_object_fact, "/checks/0/facts/k"),
    "timestamp-named fact key": (_timestamp_fact_key, "/checks/0/facts/created_at"),
    "unsorted required capabilities": (
        _unsorted_required_capabilities, "/request/required_capabilities"),
    "repairs out of order": (_repairs_out_of_order, "/repairs"),
    "failed check under a passed outcome": (
        _failed_check_under_passed_outcome, "/outcome/status"),
    "required not_run under a passed outcome": (
        _required_not_run_under_passed_outcome, "/outcome/status"),
    "primary_check_id naming a passing check": (
        _primary_check_id_names_a_passing_check, "/outcome/primary_check_id"),
    "suppressed check carrying a repair": (
        _suppressed_check_carrying_a_repair, "/checks/0/repair_id"),
    "suppressed check without suppressed_by": (
        _suppressed_check_without_suppressed_by, "/checks/0/facts"),
    "passed check carrying a reason code": (
        _passed_check_carrying_a_reason_code, "/checks/0/reason_code"),
}


class ValidateReportTest(unittest.TestCase):
    """S2: the validator, as a subprocess."""

    def check(self, mutate, pointer: str) -> None:
        with fixture() as tmp:
            path = write_report(tmp, mutate)
            code, out, _ = run("validate-report", "--input", str(path))
            self.assertEqual(code, 2)
            payload = json.loads(out)
            self.assertEqual(payload["error"]["code"], "resolver_failure")
            self.assertIn(pointer, [v["pointer"] for v in payload["error"]["violations"]])

    def test_valid_report_is_accepted(self):
        with fixture() as tmp:
            path = write_report(tmp)
            code, out, _ = run("validate-report", "--input", str(path))
            self.assertEqual(code, 0, out)
            self.assertEqual(json.loads(out), {"valid": True})

    def test_each_schema_violation_is_refused_at_its_pointer(self):
        for name, (mutate, pointer) in REFUSALS.items():
            with self.subTest(case=name):
                self.check(mutate, pointer)

    def test_each_refusal_isolates_exactly_one_violation(self):
        """Every row names the one invariant it breaks and no other."""
        for name, (mutate, pointer) in REFUSALS.items():
            with self.subTest(case=name):
                with fixture() as tmp:
                    path = write_report(tmp, mutate)
                    _, out, _ = run("validate-report", "--input", str(path))
                    violations = json.loads(out)["error"]["violations"]
                    self.assertEqual([v["pointer"] for v in violations], [pointer])

    def test_violations_are_sorted_by_pointer(self):
        def two_violations(report: dict) -> None:
            report["subject"]["timestamp"] = 0
            report["request"]["offline"] = "no"

        with fixture() as tmp:
            path = write_report(tmp, two_violations)
            code, out, _ = run("validate-report", "--input", str(path))
            self.assertEqual(code, 2)
            pointers = [v["pointer"] for v in json.loads(out)["error"]["violations"]]
            self.assertEqual(pointers, ["/request/offline", "/subject/timestamp"])
            self.assertEqual(pointers, sorted(pointers))

    def test_unreadable_input_is_refused(self):
        code, out, _ = run("validate-report", "--input", "/nonexistent/report.json")
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(out)["error"]["code"], "resolver_failure")

    def test_malformed_json_input_is_refused(self):
        with fixture() as tmp:
            path = tmp / "report.json"
            path.write_text("{", encoding="utf-8")
            code, out, _ = run("validate-report", "--input", str(path))
            self.assertEqual(code, 2)
            payload = json.loads(out)
            self.assertEqual(payload["error"]["code"], "resolver_failure")
            self.assertEqual(
                [v["pointer"] for v in payload["error"]["violations"]], [""])

    def test_unknown_subcommand_is_an_argparse_error(self):
        code, out, err = run("frobnicate")
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn("usage:", err)


class RunReportShapeTest(ReportAssertions, unittest.TestCase):
    """AC1: both purposes emit a schema-valid report, differing in shape."""

    def test_doctor_on_a_clean_root_is_schema_valid_and_exits_zero(self):
        with fixture() as tmp:
            report, by_id = doctor(self, make_root(tmp))
            self.assertEqual(sorted(report), ["checks", "outcome", "repairs",
                                              "request", "schema_version", "subject"])
            self.assertGreater(len(by_id), 1)
            self.assertEqual([c["id"] for c in report["checks"]], sorted(by_id))
            self.assert_validates(report)

    def test_workflow_entry_on_a_broken_projection_is_one_root_cause(self):
        with fixture() as tmp:
            root = make_root(tmp)
            (root / "AGENTS.md").write_text("drifted\n", encoding="utf-8")
            code, out, err = run("run", "--purpose", "workflow_entry",
                                 "--repo-root", str(root))
            self.assertEqual(code, 2, err)
            report = json.loads(out)
            self.assertEqual([len(report["checks"]), len(report["repairs"])], [1, 1])
            check, repair = report["checks"][0], report["repairs"][0]
            self.assertEqual(
                [check["id"], check["subject_kind"], check["status"],
                 check["reason_code"], check["repair_id"]],
                ["repository.projection.fresh", "projection", "failed",
                 "invalid_projection", "projection.regenerate"])
            self.assertEqual(report["outcome"], {
                "status": "failed",
                "primary_check_id": "repository.projection.fresh"})
            self.assertEqual(repair["safety_class"], "worktree")
            self.assertEqual(repair["operation"],
                             {"subcommand": "write-projections", "args": []})
            self.assert_validates(report)


class ContractParseFailureTest(ReportAssertions, unittest.TestCase):
    """D33: a parse refusal fills every stage; no evaluator faces a None."""

    def broken(self, tmp):
        root = make_root(tmp)
        (root / ".agents/project.json").write_text("{ broken", encoding="utf-8")
        return root

    def test_doctor_fails_valid_and_suppresses_the_unreached_schema_stage(self):
        with fixture() as tmp:
            report, by_id = doctor(self, self.broken(tmp))
            self.assertEqual(by_id["repository.contract.valid"]["reason_code"],
                             "invalid_contract")
            schema = by_id["compatibility.contract.schema_supported"]
            self.assertEqual(
                [schema["status"], schema["facts"], schema["repair_id"]],
                ["suppressed", {"suppressed_by": "repository.contract.valid"}, None])
            self.assertEqual(report["outcome"]["primary_check_id"],
                             "repository.contract.valid")
            self.assert_validates(report)

    def test_workflow_entry_walks_past_the_suppressed_stage_to_the_root_cause(self):
        with fixture() as tmp:
            code, out, err = run("run", "--purpose", "workflow_entry",
                                 "--repo-root", str(self.broken(tmp)))
            self.assertEqual(code, 2, err)
            report = json.loads(out)
            self.assertEqual(len(report["checks"]), 1)
            self.assertEqual(report["checks"][0]["id"], "repository.contract.valid")
            self.assert_validates(report)


class NotOnboardedTest(unittest.TestCase):
    """D23, D28: identity is null rather than fabricated; the root is discovered."""

    def test_missing_contract_reports_not_onboarded_with_null_identity(self):
        with fixture() as tmp:
            code, out, _ = run("run", "--purpose", "workflow_entry",
                               "--repo-root", str(tmp))
            self.assertEqual(code, 2)
            report = json.loads(out)
            self.assertEqual(report["checks"][0]["reason_code"], "not_onboarded")
            self.assertEqual(
                [report["subject"]["project_id"], report["subject"]["revision"],
                 report["subject"]["root"]], [None, None, str(tmp.resolve())])

    def test_doctor_suppresses_the_cascade_below_a_missing_contract(self):
        with fixture() as tmp:
            report, by_id = doctor(self, tmp)
            self.assertEqual(by_id["repository.contract.present"]["status"], "failed")
            downstream = by_id["compatibility.contract.schema_supported"]
            self.assertEqual(
                [downstream["status"], downstream["facts"]],
                ["suppressed", {"suppressed_by": "repository.contract.present"}])
            self.assertEqual(report["outcome"]["primary_check_id"],
                             "repository.contract.present")

    def test_omitting_repo_root_discovers_the_root_from_a_nested_directory(self):
        """D28: no --repo-root means the resolver's ancestor walk, not the cwd."""
        with fixture() as tmp:
            root = make_root(tmp)
            code, out, err = run("run", "--purpose", "doctor",
                                 cwd=root / ".agents/instructions")
            self.assertEqual(code, 0, err)
            report = json.loads(out)
            self.assertEqual(
                [report["subject"]["root"], report["subject"]["project_id"]],
                [str(root.resolve()), "fagenorn/nix-config"])


class RequiredCapabilityTest(ReportAssertions, unittest.TestCase):
    """--require reuses the resolver's own capability names, closed at the flag."""

    def test_an_unavailable_capability_blocks_workflow_entry(self):
        with fixture() as tmp:
            code, out, err = run("run", "--purpose", "workflow_entry",
                                 "--repo-root", str(make_root(tmp)),
                                 "--require", "release")
            self.assertEqual(code, 2, err)
            report = json.loads(out)
            self.assertEqual(len(report["checks"]), 1)
            check = report["checks"][0]
            self.assertEqual(
                [check["id"], check["status"], check["reason_code"],
                 check["repair_id"]],
                ["host.capability.required", "failed", "capability_unavailable",
                 "capability.required.unavailable"])
            self.assertEqual(report["request"]["required_capabilities"], ["release"])
            self.assert_validates(report)

    def test_repeated_requires_are_deduplicated_sorted_and_known_names(self):
        with fixture() as tmp:
            report, by_id = doctor(self, make_root(tmp),
                                   "--require", "worktrees", "--require", "tracker",
                                   "--require", "worktrees")
            names = report["request"]["required_capabilities"]
            self.assertEqual(names, ["tracker", "worktrees"])
            self.assertLessEqual(
                set(names), set(load_module().load_resolver().CAPABILITY_NAMES))
            self.assertEqual(by_id["host.capability.required"]["status"], "passed")

    def test_an_unknown_capability_is_an_argparse_error(self):
        code, out, err = run("run", "--purpose", "doctor", "--require", "teleport")
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn("usage:", err)


class ReadOnlyTest(unittest.TestCase):
    """SF-003: `run` writes nothing under the subject root.

    Three witnesses, each catching what the others miss: `git status` a
    tracked-content or index change, the recursive path/type set a created
    empty directory, and the mtimes — of directories and of the root itself,
    not only of files — a rewrite with identical bytes and a create-then-delete
    cycle that leaves the path set unchanged. Only the engine subprocess is
    hermetic; the fixture's own git calls use the caller's environment, and
    `commit.gpgsign=false` here is bookkeeping in a throwaway temp repository.
    """

    def git(self, root: Path, *args: str) -> str:
        proc = subprocess.run(
            ["git", "-c", "user.name=fixture", "-c", "user.email=fixture@example.com",
             "-c", "commit.gpgsign=false", *args],
            cwd=str(root), capture_output=True, text=True, timeout=60, check=True)
        return proc.stdout

    def snapshot(self, root: Path) -> list:
        return sorted(
            (str(path.relative_to(root)), path.is_dir(), path.stat().st_mtime_ns)
            for path in root.rglob("*")
            if ".git" not in path.relative_to(root).parts)

    def test_a_doctor_run_leaves_the_subject_root_untouched(self):
        with fixture() as tmp:
            root = make_root(tmp)
            self.git(root, "init", "-q")
            self.git(root, "add", "-A")
            self.git(root, "commit", "-q", "-m", "fixture")
            status = self.git(root, "status", "--porcelain")
            paths, root_mtime = self.snapshot(root), root.stat().st_mtime_ns
            doctor(self, root)
            self.assertEqual(self.git(root, "status", "--porcelain"), status)
            self.assertEqual(self.snapshot(root), paths)
            self.assertEqual(root.stat().st_mtime_ns, root_mtime)


class PurposeSelectionTest(unittest.TestCase):
    """SF-002: structural rules for all six purposes; Task 7 pins the exact ids.

    The invariants are asserted with and without a required capability, because
    --require widens the selection for every purpose (D38) and must not cost it
    duplicate-freedom, REGISTRY order or dependency closure.
    """

    def test_every_purpose_is_duplicate_free_and_dependency_closed(self):
        module = load_module()
        for purpose in module.PURPOSES:
            for required in ((), ("release",)):
                with self.subTest(purpose=purpose, required=required):
                    selected = module.select(purpose, required)
                    ids = [check.id for check in selected]
                    self.assertEqual(len(ids), len(set(ids)))
                    self.assertEqual(
                        ids, [c.id for c in module.REGISTRY if c.id in set(ids)])
                    for check in selected:
                        for dependency in check.depends_on:
                            self.assertIn(dependency, ids, f"{purpose}: {check.id}")

    def test_a_required_capability_selects_its_check_for_every_purpose(self):
        module = load_module()
        for purpose in module.PURPOSES:
            with self.subTest(purpose=purpose):
                ids = [c.id for c in module.select(purpose, ("release",))]
                self.assertIn("host.capability.required", ids)

    def test_an_unknown_purpose_raises(self):
        with self.assertRaises(ValueError):
            load_module().select("teleport")


class RequiredCapabilitySelectionTest(unittest.TestCase):
    """D38: no purpose reports `passed` while a required capability is missing.

    `adoption`, `ci` and `fleet` carry no `host` domain, so a purely
    domain-derived selection drops the one check that judges `--require` and
    the report answers `passed` with the unmet name still in `request`.
    """

    def test_no_purpose_passes_while_a_required_capability_is_unavailable(self):
        for purpose in ("adoption", "ci", "fleet"):
            with self.subTest(purpose=purpose):
                with fixture() as tmp:
                    code, out, err = run("run", "--purpose", purpose,
                                         "--repo-root", str(make_root(tmp)),
                                         "--require", "release")
                    self.assertEqual(code, 0, err)
                    report = json.loads(out)
                    self.assertEqual(report["outcome"], {
                        "status": "failed",
                        "primary_check_id": "host.capability.required"})
                    check = {c["id"]: c for c in report["checks"]}[
                        "host.capability.required"]
                    self.assertEqual(check["reason_code"], "capability_unavailable")


class PolicyPathSymlinkTest(ReportAssertions, unittest.TestCase):
    """D18: a declared policy path reached through a symlink is a host finding,
    and the walk is bounded at the project root.

    The subject set is every knowledge path the contract declares plus every
    projection source; a projection target is generated and so is excluded.
    """

    CHECK_ID = "host.policy_path.no_follow_readable"
    REPAIR_ID = "host.policy_path.materialize"
    STANDARDS = "home/common/agent-skills/standards"

    def policy_check(self, root, **kwargs) -> tuple[dict, dict]:
        report, by_id = doctor(self, root, **kwargs)
        return report, by_id[self.CHECK_ID]

    def test_a_symlinked_standards_directory_names_it_with_its_link_depth(self):
        with fixture() as tmp:
            root = make_root(tmp)
            declared = root / self.STANDARDS
            real = declared.parent / "standards-materialised"
            declared.rename(real)
            declared.symlink_to(real, target_is_directory=True)
            report, check = self.policy_check(root)
            self.assertEqual(
                [check["domain"], check["subject_kind"], check["status"],
                 check["reason_code"], check["repair_id"]],
                ["host", "path", "failed", "policy_path_symlinked",
                 self.REPAIR_ID])
            self.assertEqual(check["facts"], {
                "paths": [self.STANDARDS], "count": 1, "link_depth": 4,
                "in_nix_store": False})
            repair = {r["repair_id"]: r for r in report["repairs"]}[self.REPAIR_ID]
            self.assertEqual([repair["safety_class"], repair["operation"]],
                             ["user_action", None])
            self.assert_validates(report)

    def test_a_symlinked_projection_source_is_a_finding(self):
        with fixture() as tmp:
            root = make_root(tmp)
            source = root / ".agents/instructions/bootstrap.md"
            real = source.parent / "bootstrap-materialised.md"
            source.rename(real)
            source.symlink_to(real)
            report, check = self.policy_check(root)
            self.assertEqual(check["status"], "failed")
            self.assertEqual(check["facts"]["paths"],
                             [".agents/instructions/bootstrap.md"])
            self.assert_validates(report)

    def test_a_clean_root_passes_with_no_repair_and_no_facts(self):
        with fixture() as tmp:
            report, check = self.policy_check(make_root(tmp))
            self.assertEqual(
                [check["status"], check["reason_code"], check["repair_id"],
                 check["facts"]],
                ["passed", None, None, {}])
            self.assert_validates(report)

    def test_a_root_reached_through_a_symlink_reports_no_component_finding(self):
        """A root the caller names through a symlink: the resolver resolves it
        before any evaluator sees it, so the run reports no component finding.

        This pins that behaviour; it does not falsify the root bound itself
        (D39) — against an already-resolved root, an unbounded walk would find
        nothing above the root either.
        """
        with fixture() as tmp:
            real = tmp / "real"
            real.mkdir()
            root = make_root(real)
            (tmp / "linked").symlink_to(real, target_is_directory=True)
            _, check = self.policy_check(tmp / "linked" / root.name)
            self.assertEqual(check["status"], "passed")

    def test_a_very_long_offending_path_is_bounded_to_the_schema_limit(self):
        """D30: an unbounded fact would fail the engine's own report validation."""
        with fixture() as tmp:
            root = make_root(tmp)
            long_path = "/".join(["d" * 40] * 8)
            contract = root / ".agents/project.json"
            authored = json.loads(contract.read_text(encoding="utf-8"))
            authored["bindings"]["paths"]["standards"] = [long_path]
            contract.write_text(json.dumps(authored, indent=2), encoding="utf-8")
            declared = root / long_path
            declared.parent.mkdir(parents=True)
            real = declared.parent / "materialised"
            real.mkdir()
            declared.symlink_to(real, target_is_directory=True)
            report, check = self.policy_check(root)
            self.assertEqual(check["status"], "failed")
            self.assertEqual(check["facts"]["paths"], [long_path[:200]])
            self.assertEqual(len(check["facts"]["paths"][0]), 200)
            self.assertEqual(check["facts"]["link_depth"], 8)
            self.assert_validates(report)


class HelperOnPathTest(ReportAssertions, unittest.TestCase):
    """The helper check projects the resolver's capability states; it runs no
    PATH search of its own, so the empty-PATH fixture is the whole witness."""

    CHECK_ID = "host.executor.helper_on_path"
    REPAIR_ID = "host.helper.install"

    def test_an_empty_path_reports_the_tool_shaped_blocked_capabilities(self):
        with fixture() as tmp:
            report, by_id = doctor(self, make_root(tmp),
                                   env=dict(HERMETIC_ENV, PATH=""))
            check = by_id[self.CHECK_ID]
            self.assertEqual(
                [check["subject_kind"], check["status"], check["reason_code"],
                 check["repair_id"]],
                ["host_tool", "failed", "helper_missing", self.REPAIR_ID])
            names = check["facts"]["capabilities"]
            self.assertIn("tracker", names)
            self.assertLessEqual(len(names), 8)
            # blocked for vcs_worktree_unsupported, which is not a missing helper
            self.assertNotIn("worktrees", names)
            codes = check["facts"]["reason_codes"]
            self.assertEqual(codes, sorted(set(codes)))
            self.assertLessEqual(set(codes),
                                 {"command_missing", "tracker_cli_missing"})
            repair = {r["repair_id"]: r for r in report["repairs"]}[self.REPAIR_ID]
            self.assertEqual([repair["safety_class"], repair["operation"]],
                             ["user_action", None])
            self.assert_validates(report)

    def test_the_fixture_stub_bin_resolves_every_declared_helper(self):
        with fixture() as tmp:
            report, by_id = doctor(self, make_root(tmp))
            check = by_id[self.CHECK_ID]
            self.assertEqual([check["status"], check["reason_code"],
                              check["repair_id"], check["facts"]],
                             ["passed", None, None, {}])
            self.assert_validates(report)


class FactBoundingTest(unittest.TestCase):
    """D30: the one route from an authored value into `facts`, tested directly.

    S3 is the only seam that reaches the pair: every subprocess case observes
    it through a subject short enough that truncation never shows.
    """

    def test_bound_fact_truncates_to_the_schema_limit(self):
        module = load_module()
        self.assertEqual(module.bound_fact("x" * 250), "x" * 200)
        self.assertEqual(module.bound_fact("short"), "short")
        self.assertTrue(module.is_fact_value(module.bound_fact("x" * 250)))

    def test_bound_facts_sorts_truncates_and_caps_the_list(self):
        module = load_module()
        self.assertEqual(module.bound_facts(["b", "c", "a"]), ["a", "b", "c"])
        self.assertEqual(
            module.bound_facts([f"e{index}" for index in range(12)]),
            ["e0", "e1", "e10", "e11", "e2", "e3", "e4", "e5"])
        self.assertEqual(module.bound_facts(["y" * 300, "z"], limit=1), ["y" * 200])
        self.assertTrue(module.is_fact_value(
            module.bound_facts([f"{index}" + "w" * 300 for index in range(12)])))


class Rebinding:
    """Restore every module attribute a case replaces, so none leaks forward."""

    def rebind(self, owner, name, value):
        original = getattr(owner, name)
        self.addCleanup(setattr, owner, name, original)
        setattr(owner, name, value)


class EvaluatorResolutionTest(Rebinding, unittest.TestCase):
    """S3: an evaluator is resolved through the module that declared it.

    `load_module` builds a fresh instance per call under one shared
    `sys.modules` key, so resolving an evaluator through that key would fetch
    the newest instance's function and silently bypass a rebind made on the
    instance under test — the very thing S3 is reserved for.
    """

    def test_a_rebound_evaluator_is_the_one_evaluate_calls(self):
        module = load_module()
        load_module()  # a second instance now owns the shared sys.modules name
        self.rebind(module, "check_contract_present", lambda _context: module.Outcome(
            "failed", "not_onboarded", "onboarding.contract.missing"))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = module.main(["run", "--purpose", "doctor", "--offline",
                                "--repo-root", str(REPO_ROOT)])
        self.assertEqual(code, 0)
        by_id = {c["id"]: c for c in json.loads(buf.getvalue())["checks"]}
        self.assertEqual(
            [by_id["repository.contract.present"]["status"],
             by_id["repository.contract.present"]["reason_code"]],
            ["failed", "not_onboarded"])


class EngineFailureTest(Rebinding, unittest.TestCase):
    """S3: the boundary refuses; the ladder's declared catch does not (D17, D29).

    Both cases pass --offline, and every later S3 case calling main must: in
    process there is no hermetic runner, so evaluate's offline rule is what
    keeps Task 4's network check from spawning a child (D35).
    """

    def test_an_unexpected_engine_exception_becomes_the_refusal(self):
        module = load_module()
        self.rebind(module, "build_report", lambda *a, **k: (_ for _ in ()).throw(
            RuntimeError("sentinel-exception-detail")))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = module.main(["run", "--purpose", "doctor", "--offline",
                                "--repo-root", str(REPO_ROOT)])
        self.assertEqual(code, 2)
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["error"]["code"], "resolver_failure")
        self.assertEqual(payload["error"]["repair_id"], "conformance.internal")
        self.assertEqual([v["message"] for v in payload["error"]["violations"]],
                         [module.ENGINE_FAILURE_MESSAGE])
        self.assertNotIn("sentinel-exception-detail", buf.getvalue())

    def test_a_resolver_exception_is_a_check_finding_not_the_refusal(self):
        module = load_module()
        self.rebind(module.load_resolver(), "discover_root",
                    lambda _arg: (_ for _ in ()).throw(RuntimeError("boom")))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = module.main(["run", "--purpose", "doctor", "--offline",
                                "--repo-root", "/"])
        self.assertEqual(code, 0)
        check = {c["id"]: c for c in json.loads(buf.getvalue())["checks"]}[
            "repository.contract.resolvable"]
        self.assertEqual([check["status"], check["reason_code"]],
                         ["failed", "resolver_failure"])


def gh_env(tmp: Path, exit_code: int) -> dict:
    """The hermetic environment with a `gh` stub exiting `exit_code`."""
    return dict(HERMETIC_ENV,
                PATH=make_stub_bin(tmp / "stubbin", {"gh": exit_code}))


class OfflineRuleTest(ReportAssertions, unittest.TestCase):
    """AC4: offline is an input; a network check reports not_run and the
    outcome is incomplete, never a pass."""

    def test_doctor_offline_marks_the_network_check_not_run_and_incomplete(self):
        with fixture() as tmp:
            report, by_id = doctor(self, make_root(tmp), "--offline",
                                   env=gh_env(tmp, 0))
            self.assertTrue(report["request"]["offline"])
            check = by_id["host.tracker.credential"]
            self.assertEqual(
                [check["status"], check["reason_code"], check["repair_id"],
                 check["facts"]],
                ["not_run", "offline_constraint", "conformance.rerun_online", {}])
            self.assertEqual(report["outcome"], {
                "status": "incomplete",
                "primary_check_id": "host.tracker.credential"})
            repair = {r["repair_id"]: r for r in report["repairs"]}[
                "conformance.rerun_online"]
            self.assertEqual(repair["safety_class"], "read_only")
            self.assertIsNone(repair["operation"])
            self.assert_validates(report)

    def test_offline_never_yields_a_passing_network_check(self):
        """The body must not run: a stub that would pass online still not_run."""
        with fixture() as tmp:
            root, env = make_root(tmp), gh_env(tmp, 0)
            online = doctor(self, root, env=env)[1]["host.tracker.credential"]
            offline = doctor(self, root, "--offline",
                             env=env)[1]["host.tracker.credential"]
            self.assertEqual([online["status"], offline["status"]],
                             ["passed", "not_run"])

    def test_workflow_entry_selects_no_network_check(self):
        """Asserted, not assumed: --offline cannot change the entry outcome."""
        with fixture() as tmp:
            root, env = make_root(tmp), gh_env(tmp, 1)
            plain = run("run", "--purpose", "workflow_entry", "--repo-root",
                        str(root), env=env)
            offline = run("run", "--purpose", "workflow_entry", "--repo-root",
                          str(root), "--offline", env=env)
            self.assertEqual(plain[0], 0, plain[2])
            self.assertEqual(offline[0], 0, offline[2])
            self.assertEqual(json.loads(plain[1])["outcome"],
                             json.loads(offline[1])["outcome"])
            self.assertNotIn("host.tracker.credential",
                             [c["id"] for c in json.loads(offline[1])["checks"]])


class TrackerCredentialTest(ReportAssertions, unittest.TestCase):
    """D7, D20: the one network-flagged check. It records whether a credential
    exists and the hostname its closed table names — never a token, a username
    or a line of CLI output, so `facts` is asserted whole in every branch."""

    CHECK_ID = "host.tracker.credential"
    REPAIR_ID = "host.tracker.authenticate"

    def test_an_authenticated_cli_passes_with_a_boolean_and_a_hostname(self):
        with fixture() as tmp:
            report, by_id = doctor(self, make_root(tmp), env=gh_env(tmp, 0))
            check = by_id[self.CHECK_ID]
            self.assertEqual(
                [check["status"], check["subject_kind"], check["reason_code"],
                 check["repair_id"]],
                ["passed", "tracker", None, None])
            self.assertEqual(check["facts"], {
                "authenticated": True, "cli_invoked": True,
                "host": "github.com"})
            self.assert_validates(report)

    def test_an_unauthenticated_cli_fails_and_names_a_user_action_repair(self):
        with fixture() as tmp:
            report, by_id = doctor(self, make_root(tmp), env=gh_env(tmp, 1))
            check = by_id[self.CHECK_ID]
            self.assertEqual(
                [check["status"], check["reason_code"], check["repair_id"]],
                ["failed", "tracker_credential_missing", self.REPAIR_ID])
            self.assertEqual(check["facts"], {
                "authenticated": False, "cli_invoked": True,
                "host": "github.com"})
            repair = {r["repair_id"]: r for r in report["repairs"]}[self.REPAIR_ID]
            self.assertEqual([repair["safety_class"], repair["operation"]],
                             ["user_action", None])
            self.assert_validates(report)

    def test_an_unrecognised_tracker_kind_is_not_run_never_a_pass(self):
        """D20: the CLI would have succeeded, and the check still refuses to
        pass a tracker this engine cannot interrogate."""
        with fixture() as tmp:
            root = make_root(tmp)
            contract = root / ".agents/project.json"
            authored = json.loads(contract.read_text(encoding="utf-8"))
            authored["bindings"]["tracker"]["kind"] = "forgejo"
            contract.write_text(json.dumps(authored, indent=2), encoding="utf-8")
            report, by_id = doctor(self, root, env=gh_env(tmp, 0))
            check = by_id[self.CHECK_ID]
            self.assertEqual(
                [check["status"], check["reason_code"], check["repair_id"]],
                ["not_run", "unsupported_tracker_kind", self.REPAIR_ID])
            self.assertEqual(check["facts"], {"kind": "forgejo", "cli": "gh"})
            self.assertEqual(report["outcome"], {
                "status": "incomplete", "primary_check_id": self.CHECK_ID})
            self.assert_validates(report)

    def test_ci_omits_the_tracker_check(self):
        """The spec's "CI owns its own auth": `ci` selects repository,
        compatibility and verification, never host."""
        with fixture() as tmp:
            code, out, err = run("run", "--purpose", "ci", "--repo-root",
                                 str(make_root(tmp)), env=gh_env(tmp, 1))
            self.assertEqual(code, 0, err)
            self.assertNotIn(self.CHECK_ID,
                             [c["id"] for c in json.loads(out)["checks"]])


def write_file(root: Path, relative: str, text: str = "x\n") -> Path:
    """One file at `relative` under `root`, with every parent created."""
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return target


class PathClassificationTest(ReportAssertions, unittest.TestCase):
    """#72: the four lifecycle classes are closed. A path matching none of them
    is a finding, never a new implicit class, and every offender is named
    repository-relative so a reader can open it."""

    CHECK_ID = "repository.paths.classified"
    REPAIR_ID = "lifecycle.path.classify"

    def test_a_conformant_tree_passes_with_no_repair_and_no_facts(self):
        with fixture() as tmp:
            report, by_id = doctor(self, make_root(tmp))
            check = by_id[self.CHECK_ID]
            self.assertEqual(
                [check["domain"], check["subject_kind"], check["status"],
                 check["reason_code"], check["repair_id"], check["facts"]],
                ["repository", "path", "passed", None, None, {}])
            self.assert_validates(report)

    def test_a_path_outside_every_class_is_a_finding(self):
        """An unadmitted `artifacts/` bucket is unclassified for the same reason
        a stray directory is: the class list, not the parent, admits a path."""
        for relative in (".agents/scratchpad/notes.txt",
                         ".agents/artifacts/scratch/x.md"):
            with self.subTest(relative=relative), fixture() as tmp:
                root = make_root(tmp)
                write_file(root, relative)
                report, by_id = doctor(self, root)
                check = by_id[self.CHECK_ID]
                self.assertEqual(
                    [check["status"], check["reason_code"], check["repair_id"]],
                    ["failed", "unclassified_path", self.REPAIR_ID])
                self.assertEqual(check["facts"],
                                 {"paths": [relative], "count": 1})
                repair = {r["repair_id"]: r
                          for r in report["repairs"]}[self.REPAIR_ID]
                self.assertEqual(
                    [repair["module"], repair["safety_class"], repair["operation"]],
                    ["conformance", "user_action", None])
                self.assert_validates(report)

    def test_runtime_state_is_a_class_not_an_escape(self):
        with fixture() as tmp:
            root = make_root(tmp)
            write_file(root, ".agents/runtime/state/run-1/state.json", "{}\n")
            report, by_id = doctor(self, root)
            check = by_id[self.CHECK_ID]
            self.assertEqual([check["status"], check["facts"]], ["passed", {}])
            self.assert_validates(report)

    def test_many_long_offending_paths_are_capped_and_bounded(self):
        """D30: a repository-relative path has no length ceiling, so an
        unbounded fact would fail the engine's own report validation and turn a
        repository finding into `resolver_failure`."""
        with fixture() as tmp:
            root = make_root(tmp)
            deep = "/".join([".agents/scratchpad"] + ["d" * 40] * 6)
            for index in range(12):
                write_file(root, f"{deep}/f{index:02d}.txt")
            report, by_id = doctor(self, root)
            check = by_id[self.CHECK_ID]
            self.assertEqual(check["status"], "failed")
            self.assertEqual(len(check["facts"]["paths"]), 8)
            self.assertEqual(check["facts"]["count"], 12)
            self.assertEqual({len(path) for path in check["facts"]["paths"]},
                             {200})
            self.assert_validates(report)


class IgnoreSentinelTest(ReportAssertions, unittest.TestCase):
    """#72: `.agents/runtime/` is covered by a root rule or by the committed
    sentinel — either spelling, because both are legitimate homes. Only the
    tracked ignore files are read; `.git/info/exclude` is machine-local and a
    machine-local rule cannot be the repository's classification."""

    CHECK_ID = "repository.ignore.runtime_sentinel"
    REPAIR_ID = "lifecycle.ignore.repair"

    def build(self, tmp: Path, gitignore: str, sentinel: bool = False) -> Path:
        root = make_root(tmp)
        (root / ".gitignore").write_text(gitignore, encoding="utf-8")
        if sentinel:
            write_file(root, ".agents/runtime/.gitignore", "*\n")  # exactly b"*\n"
        return root

    def test_either_spelling_of_the_runtime_rule_passes(self):
        for label, gitignore, sentinel in (
                ("root rule", "# comment\n\n.agents/runtime/\n", False),
                ("committed sentinel", "result\n", True)):
            with self.subTest(coverage=label), fixture() as tmp:
                report, by_id = doctor(self, self.build(tmp, gitignore, sentinel))
                check = by_id[self.CHECK_ID]
                self.assertEqual(
                    [check["domain"], check["subject_kind"], check["status"],
                     check["reason_code"], check["repair_id"], check["facts"]],
                    ["repository", "path", "passed", None, None, {}])
                self.assert_validates(report)

    def test_neither_spelling_present_is_the_missing_finding(self):
        with fixture() as tmp:
            report, by_id = doctor(self, self.build(tmp, "result\n"))
            check = by_id[self.CHECK_ID]
            self.assertEqual(
                [check["status"], check["reason_code"], check["repair_id"]],
                ["failed", "runtime_ignore_missing", self.REPAIR_ID])
            self.assertEqual(check["facts"],
                             {"root_gitignore": True, "sentinel": False})
            repair = {r["repair_id"]: r for r in report["repairs"]}[self.REPAIR_ID]
            self.assertEqual(
                [repair["module"], repair["safety_class"], repair["operation"]],
                ["conformance", "worktree", None])
            self.assert_validates(report)

    def test_an_overbroad_rule_outranks_a_covered_runtime_subtree(self):
        """The runtime rule is present and the check still fails: an overbroad
        ignore conceals authored truth, so it is the finding that is reported."""
        with fixture() as tmp:
            report, by_id = doctor(
                self, self.build(tmp, ".agents/runtime/\n.agents/*\n"))
            check = by_id[self.CHECK_ID]
            self.assertEqual(
                [check["status"], check["reason_code"], check["repair_id"]],
                ["failed", "overbroad_ignore", self.REPAIR_ID])
            self.assertEqual(check["facts"],
                             {"rules": [".agents/*"], "count": 1})
            self.assert_validates(report)


class ShellIndirectionTest(ReportAssertions, unittest.TestCase):
    """The command *policy* check: the resolver already validated command shape,
    and neither re-implements the other. Facts carry command ids, never argv."""

    CHECK_ID = "verification.commands.no_shell_indirection"
    REPAIR_ID = "contract.commands.destructure"

    def with_argv(self, root: Path, command_id: str, argv: list) -> Path:
        contract = root / ".agents/project.json"
        authored = json.loads(contract.read_text(encoding="utf-8"))
        authored["bindings"]["commands"][command_id]["argv"] = argv
        contract.write_text(json.dumps(authored, indent=2), encoding="utf-8")
        return root

    def test_plain_argv_passes_with_no_repair_and_no_facts(self):
        with fixture() as tmp:
            report, by_id = doctor(self, make_root(tmp))
            check = by_id[self.CHECK_ID]
            self.assertEqual(
                [check["domain"], check["subject_kind"], check["status"],
                 check["reason_code"], check["repair_id"], check["facts"]],
                ["verification", "command", "passed", None, None, {}])
            self.assert_validates(report)

    def test_a_shell_or_a_metacharacter_names_the_offending_command_id(self):
        for label, argv in (("shell -c", ["bash", "-c", "just build"]),
                            ("metacharacter", ["just", "build && just switch"])):
            with self.subTest(indirection=label), fixture() as tmp:
                root = self.with_argv(make_root(tmp), "nix-build", argv)
                report, by_id = doctor(self, root)
                check = by_id[self.CHECK_ID]
                self.assertEqual(
                    [check["status"], check["reason_code"], check["repair_id"]],
                    ["failed", "shell_indirection", self.REPAIR_ID])
                self.assertEqual(check["facts"],
                                 {"commands": ["nix-build"], "count": 1})
                repair = {r["repair_id"]: r
                          for r in report["repairs"]}[self.REPAIR_ID]
                self.assertEqual(
                    [repair["module"], repair["safety_class"], repair["operation"]],
                    ["resolve-project", "user_action", None])
                self.assert_validates(report)

    def test_ci_selects_the_verification_check_and_fleet_does_not(self):
        """The purpose table's own claim, proved rather than assumed."""
        for purpose, expected in (("ci", True), ("fleet", False)):
            with self.subTest(purpose=purpose), fixture() as tmp:
                code, out, err = run("run", "--purpose", purpose, "--repo-root",
                                     str(make_root(tmp)))
                self.assertEqual(code, 0, err)
                ids = [c["id"] for c in json.loads(out)["checks"]]
                self.assertEqual(self.CHECK_ID in ids, expected)


def make_run(root: Path, worktree: str, run_id: str, states: list, *,
             lock: bool = True, results: bool = True,
             ledger: str | None = None) -> Path:
    """A nested ledger run directory, by default a removable one.

    `lock` writes the canonical state.lock, `results` gives each terminal
    attempt a matching durable result, and `ledger` replaces the state.json
    bytes outright. A removable run needs all of them (D34).
    """
    run = root / ".worktrees" / worktree / ".superpowers" / "workflows" / run_id
    run.mkdir(parents=True)
    attempts = [{"state": s,
                 "result": {"state": s} if results else None} for s in states]
    run.joinpath("state.json").write_text(
        ledger if ledger is not None
        else json.dumps({"issues": {"1": {"attempts": attempts}}}),
        encoding="utf-8")
    if lock:
        run.joinpath("state.lock").write_bytes(b"")
    return run


class NestedLedgerResidueTest(ReportAssertions, unittest.TestCase):
    """AC5: orphaned ledgers are reported with non-destructive repairs unless a
    lock proves no live owner."""

    CHECK_ID = "repository.residue.nested_ledger"
    RETAIN_ID = "lifecycle.residue.nested_ledger.retain"
    REMOVE_ID = "lifecycle.residue.nested_ledger.remove"

    def check(self, root):
        return doctor(self, root)[1][self.CHECK_ID]

    def test_a_locked_merged_run_with_results_is_removable(self):
        with fixture() as tmp:
            root = make_root(tmp)
            make_run(root, "worktree-a", "run-1", ["merged"])
            report, by_id = doctor(self, root)
            check = by_id[self.CHECK_ID]
            self.assertEqual(
                [check["status"], check["reason_code"], check["repair_id"]],
                ["warning", "terminal_residue", self.REMOVE_ID])
            self.assertEqual(check["facts"]["runs"],
                             [".worktrees/worktree-a/.superpowers/workflows/run-1"])
            self.assertEqual([check["facts"]["terminal"],
                              check["facts"]["live_owner"]], [1, 0])
            self.assertEqual(
                {r["repair_id"]: r for r in report["repairs"]}[
                    self.REMOVE_ID]["safety_class"],
                "worktree")
            self.assert_validates(report)

    def test_neither_proof_alone_makes_a_run_removable(self):
        """D34: a missing lock, a missing result, a mismatched result, a
        non-merged state and a malformed ledger are all unacknowledged."""
        cases = {
            "no_lock": dict(states=["merged"], lock=False),
            "no_result": dict(states=["merged"], results=False),
            "not_merged": dict(states=["merged", "failed"]),
            "still_active": dict(states=["active"], results=False),
            "malformed": dict(states=["merged"], ledger="{ broken"),
            "mismatched": dict(states=["merged"],
                               ledger=json.dumps({"issues": {"1": {"attempts": [
                                   {"state": "merged",
                                    "result": {"state": "stopped"}}]}}})),
        }
        for name, kwargs in cases.items():
            with self.subTest(case=name), fixture() as tmp:
                root = make_root(tmp)
                make_run(root, "worktree-a", "run-1", **kwargs)
                check = self.check(root)
                self.assertEqual(
                    [check["reason_code"], check["repair_id"],
                     check["facts"]["terminal"]],
                    ["unacknowledged_residue", self.RETAIN_ID, 0])

    def test_a_held_lock_reports_live_owner_and_outranks_terminal_residue(self):
        """The kernel, not a sleep, proves the live owner (D16)."""
        with fixture() as tmp:
            root = make_root(tmp)
            make_run(root, "worktree-a", "run-1", ["merged"])
            live = make_run(root, "worktree-b", "run-2", ["active"], results=False)
            fd = os.open(live / "state.lock", os.O_RDONLY)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                report, by_id = doctor(self, root)
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)
            check = by_id[self.CHECK_ID]
            self.assertEqual(
                [check["status"], check["reason_code"], check["repair_id"]],
                ["warning", "live_owner", self.RETAIN_ID])
            self.assertEqual([check["facts"]["live_owner"],
                              check["facts"]["count"]], [1, 2])
            self.assertEqual(
                {r["repair_id"]: r for r in report["repairs"]}[
                    self.RETAIN_ID]["safety_class"],
                "user_action")
            self.assert_validates(report)

    def test_the_lock_is_released_and_never_created(self):
        """The probe writes nothing: an unlocked run stays unlocked, and the
        lock the engine did take is free again once the run has finished."""
        with fixture() as tmp:
            root = make_root(tmp)
            unlocked = make_run(root, "worktree-a", "run-1", ["merged"],
                                lock=False)
            locked = make_run(root, "worktree-b", "run-2", ["merged"])
            doctor(self, root)
            self.assertFalse((unlocked / "state.lock").exists())
            fd = os.open(locked / "state.lock", os.O_RDONLY)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)

    def test_no_worktrees_passes(self):
        with fixture() as tmp:
            report, by_id = doctor(self, make_root(tmp))
            check = by_id[self.CHECK_ID]
            self.assertEqual(
                [check["domain"], check["subject_kind"], check["requirement"],
                 check["status"], check["reason_code"], check["repair_id"],
                 check["facts"]],
                ["repository", "residue", "optional", "passed", None, None, {}])
            self.assert_validates(report)

    def test_residue_never_drives_the_outcome_to_failed(self):
        """D8: a warning is recorded with its repair and left out of the
        outcome, so a machine holding residue is not a broken repository."""
        with fixture() as tmp:
            root = make_root(tmp)
            make_run(root, "worktree-a", "run-1", ["failed"])
            report, by_id = doctor(self, root)
            self.assertEqual(by_id[self.CHECK_ID]["status"], "warning")
            self.assertEqual(report["outcome"],
                             {"status": "passed", "primary_check_id": None})
            self.assert_validates(report)

    def test_no_repair_in_the_report_is_destructive(self):
        """D10: v1 satisfies the cleanup rule by never reaching for the
        exemption — no repair it can emit carries `destructive`."""
        with fixture() as tmp:
            root = make_root(tmp)
            make_run(root, "worktree-a", "run-1", ["merged"])
            write_file(root, "producer-report-abc123.json", "{}\n")
            report, _ = doctor(self, root)
            self.assertTrue(report["repairs"])
            self.assertNotIn("destructive",
                             [r["safety_class"] for r in report["repairs"]])
            self.assert_validates(report)

    def test_an_unlistable_worktree_root_yields_no_runs_rather_than_an_error(self):
        """D19, D32: `Path.is_dir` swallows an OSError and answers False, so it
        never protects the listing after it. One unreadable directory must not
        turn a whole doctor run into `resolver_failure` with no report."""
        with fixture() as tmp:
            root = make_root(tmp)
            make_run(root, "worktree-a", "run-1", ["merged"])
            worktrees = root / ".worktrees"
            worktrees.chmod(0o000)
            try:
                if os.access(worktrees, os.R_OK):  # root, or a mode-less fs
                    self.skipTest("mode bits do not restrict this process")
                report, by_id = doctor(self, root)
            finally:
                worktrees.chmod(0o755)
            check = by_id[self.CHECK_ID]
            self.assertEqual([check["status"], check["reason_code"],
                              check["facts"]], ["passed", None, {}])
            self.assert_validates(report)



class RootScratchResidueTest(ReportAssertions, unittest.TestCase):
    """Scratch that escaped $TMPDIR into the repository root. The pattern set is
    a constant, so the check still reports on an invalid contract."""

    CHECK_ID = "repository.residue.root_scratch"
    REPAIR_ID = "lifecycle.residue.root_scratch"

    def test_root_scratch_is_named_with_its_worktree_repair(self):
        with fixture() as tmp:
            root = make_root(tmp)
            write_file(root, "producer-report-abc123.json", "{}\n")
            write_file(root, "brief.tmp.AbC123")
            report, by_id = doctor(self, root)
            check = by_id[self.CHECK_ID]
            self.assertEqual(
                [check["domain"], check["subject_kind"], check["requirement"],
                 check["status"], check["reason_code"], check["repair_id"]],
                ["repository", "residue", "optional", "warning",
                 "root_scratch_present", self.REPAIR_ID])
            self.assertEqual(
                check["facts"],
                {"files": ["brief.tmp.AbC123", "producer-report-abc123.json"],
                 "count": 2})
            repair = {r["repair_id"]: r for r in report["repairs"]}[self.REPAIR_ID]
            self.assertEqual(
                [repair["module"], repair["safety_class"], repair["operation"]],
                ["conformance", "worktree", None])
            self.assert_validates(report)

    def test_a_clean_root_passes(self):
        with fixture() as tmp:
            report, by_id = doctor(self, make_root(tmp))
            check = by_id[self.CHECK_ID]
            self.assertEqual([check["status"], check["reason_code"],
                              check["repair_id"], check["facts"]],
                             ["passed", None, None, {}])
            self.assert_validates(report)

    def test_an_invalid_contract_does_not_suppress_it(self):
        """It depends only on `repository.contract.present`, so it still reports
        where a contract-derived sibling is suppressed."""
        with fixture() as tmp:
            root = make_root(tmp)
            contract = root / ".agents/project.json"
            authored = json.loads(contract.read_text(encoding="utf-8"))
            authored["bindings"]["extra"] = True
            contract.write_text(json.dumps(authored, indent=2), encoding="utf-8")
            write_file(root, "producer-report-x.json", "{}\n")
            report, by_id = doctor(self, root)
            self.assertEqual(
                [by_id["repository.contract.valid"]["status"],
                 by_id["repository.paths.classified"]["status"],
                 by_id[self.CHECK_ID]["status"],
                 by_id[self.CHECK_ID]["reason_code"]],
                ["failed", "suppressed", "warning", "root_scratch_present"])
            self.assert_validates(report)

    def test_an_unlistable_root_yields_no_names_rather_than_an_error(self):
        """Traversable but unreadable (mode 0o111): the resolver still opens the
        contract by name while the root itself cannot be listed, so the check
        can only answer `passed` (D19, D32)."""
        with fixture() as tmp:
            root = make_root(tmp)
            write_file(root, "producer-report-x.json", "{}\n")
            root.chmod(0o111)
            try:
                if os.access(root, os.R_OK) or not os.access(root, os.X_OK):
                    self.skipTest("mode bits do not restrict this process")
                report, by_id = doctor(self, root)
            finally:
                root.chmod(0o755)
            check = by_id[self.CHECK_ID]
            self.assertEqual([check["status"], check["reason_code"],
                              check["facts"]], ["passed", None, {}])
            self.assert_validates(report)



class ScratchPatternConsistencyTest(unittest.TestCase):
    """D11: the engine holds the scratch policy and the tracked .gitignore is
    its backstop, so every pattern must appear in both."""

    def test_every_scratch_pattern_is_backstopped_by_the_tracked_gitignore(self):
        rules = {line.strip() for line
                 in (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()}
        for pattern in load_module().ROOT_SCRATCH_PATTERNS:
            with self.subTest(pattern=pattern):
                self.assertIn(pattern, rules)


if __name__ == "__main__":
    unittest.main()
