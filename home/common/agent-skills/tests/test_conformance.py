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


if __name__ == "__main__":
    unittest.main()
