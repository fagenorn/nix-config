"""Conformance judges every procedure file the platform ships, found by listing, with the verdict `engine check` gives, against the judged project's commands."""

from __future__ import annotations

import contextlib
import io
import json
import shutil
import unittest
from pathlib import Path

from agent_tools.delivery import engine
from agent_tools.project_contract import conformance_checks

from .conformance_test_support import (
    REPO_ROOT, PlatformHome, Rebinding, ReportAssertions, commit_all, fixture,
    load_module, make_root, run,
)

TIER = "integration"

OVERSIZE = "prompt oversize.md 8193 of 8192 bytes"
MISSING_ERROR = "unmapped_outcome deliver issue: on does not map 'error'."


class ShippedProceduresCheckTest(PlatformHome, Rebinding, ReportAssertions, unittest.TestCase):
    CHECK_ID = "verification.procedures.engine_check"
    REPAIR_ID = "procedures.engine_check.repair"
    SOURCE = REPO_ROOT / "python/agent_tools/delivery/procedures"

    def copy(self, tmp: Path) -> Path:
        return shutil.copytree(self.SOURCE, tmp / "procedures")

    def shipped_count(self) -> int:
        return len([p for p in self.SOURCE.glob("*.json") if not p.name.endswith(".reply.json")])

    def drop_error_outcome(self, procedures: Path) -> None:
        path = procedures / "deliver.json"
        doc = json.loads(path.read_text("utf-8"))
        for step in doc["steps"]:
            if step.get("id") == "issue":
                del step["on"]["error"]
        path.write_text(json.dumps(doc), "utf-8")

    def ci(self, root: Path, procedures: Path) -> tuple[int, dict]:
        self.rebind(load_module().CHECKS_MODULE, "SHIPPED_PROCEDURES", procedures)
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = load_module().main(
                ["run", "--purpose", "ci", "--offline", "--repo-root", str(root)])
        return code, json.loads(buffer.getvalue())

    def check(self, report: dict) -> dict:
        return next(c for c in report["checks"] if c["id"] == self.CHECK_ID)

    def failed(self, report: dict) -> list[str]:
        return [c["id"] for c in report["checks"] if c["status"] == "failed"]

    def probe(self, command: str, on: dict, step_id: str = "probe") -> dict:
        return {"format": 1, "inputs": [], "stops": {}, "steps": [
            {"id": step_id, "stage": "setup", "kind": "command", "holds": "run",
             "command": command, "on": on}]}

    def write(self, procedures: Path, name: str, doc: dict) -> None:
        (procedures / name).write_text(json.dumps(doc), "utf-8")

    def test_a_shipped_procedure_missing_an_outcome_turns_ci_red_naming_the_procedure_and_the_refusal(self):
        with fixture() as tmp:
            root = make_root(tmp)
            procedures = self.copy(tmp)
            self.drop_error_outcome(procedures)
            code, report = self.ci(root, procedures)
        check = self.check(report)
        self.assertEqual(code, 1)
        self.assertEqual(self.failed(report), [self.CHECK_ID])
        self.assertEqual(
            [check["domain"], check["subject_kind"], check["requirement"], check["status"],
             check["reason_code"], check["repair_id"]],
            ["verification", "command", "required", "failed", "procedure_refused",
             self.REPAIR_ID])
        self.assertEqual(check["facts"], {"procedures": ["deliver"],
                                          "refusals": [MISSING_ERROR], "count": 1})
        repair = {r["repair_id"]: r for r in report["repairs"]}[self.REPAIR_ID]
        self.assertEqual([repair["module"], repair["safety_class"], repair["operation"]],
                         ["conformance", "user_action", None])
        self.assert_validates(report)

    def test_the_shipped_procedures_pass_ci_through_the_command(self):
        with fixture() as tmp:
            root = make_root(tmp)
            code, out, err = run("run", "--purpose", "ci", "--repo-root", str(root))
        self.assertEqual(code, 0, err)
        check = self.check(json.loads(out))
        self.assertEqual([check["status"], check["reason_code"], check["repair_id"],
                          check["facts"]],
                         ["passed", None, None, {"procedure_count": self.shipped_count()}])

    def test_a_broken_procedure_under_a_new_name_is_refused_with_no_list_edited(self):
        with fixture() as tmp:
            root = make_root(tmp)
            procedures = self.copy(tmp)
            self.write(procedures, "zz-new.json",
                       self.probe("lint", {"ok": "done", "refused": "done"}))
            code, report = self.ci(root, procedures)
        check = self.check(report)
        self.assertEqual(code, 1)
        self.assertEqual(self.failed(report), [self.CHECK_ID])
        self.assertEqual(check["reason_code"], "procedure_refused")
        self.assertEqual(check["facts"], {
            "procedures": ["zz-new"],
            "refusals": ["unmapped_outcome zz-new probe: on does not map 'failed'."],
            "count": 1})

    def test_a_command_id_absent_from_the_contract_fails_that_project_and_passes_one_that_declares_it(self):
        with fixture() as tmp:
            procedures = self.copy(tmp)
            self.write(procedures, "probe.json", self.probe(
                "procedure-probe", {"ok": "done", "failed": "done", "refused": "done"}))
            declaring = make_root(tmp / "declaring")
            path = declaring / ".agents/project.json"
            contract = json.loads(path.read_text("utf-8"))
            commands = contract["bindings"]["commands"]
            commands["procedure-probe"] = json.loads(json.dumps(commands["lint"]))
            path.write_text(json.dumps(contract, indent=2), "utf-8")
            commit_all(declaring, "declare procedure-probe")
            lacking = make_root(tmp / "lacking")
            code_d, report_d = self.ci(declaring, procedures)
            code_l, report_l = self.ci(lacking, procedures)
        declared = self.check(report_d)
        self.assertEqual(code_d, 0)
        self.assertEqual(report_d["outcome"]["status"], "passed")
        self.assertEqual([declared["status"], declared["reason_code"], declared["facts"]],
                         ["passed", None, {"procedure_count": self.shipped_count() + 1}])
        absent = self.check(report_l)
        self.assertEqual(code_l, 1)
        self.assertEqual(self.failed(report_l), [self.CHECK_ID])
        self.assertEqual([absent["status"], absent["reason_code"]],
                         ["failed", "procedure_refused"])
        self.assertEqual(absent["facts"], {
            "procedures": ["probe"],
            "refusals": ["unknown_command probe probe: 'procedure-probe' is not a command-table id."],
            "count": 1})

    def test_a_cap_breach_alone_fails_with_its_own_reason(self):
        with fixture() as tmp:
            root = make_root(tmp)
            procedures = self.copy(tmp)
            (procedures / "oversize.md").write_bytes(b"x" * 8193)
            _, report = self.ci(root, procedures)
        check = self.check(report)
        self.assertEqual([check["status"], check["reason_code"], check["repair_id"]],
                         ["failed", "procedure_cap_exceeded", self.REPAIR_ID])
        self.assertEqual(check["facts"], {"breaches": [OVERSIZE], "breach_count": 1})

    def test_a_refusal_and_a_breach_report_both_under_the_refusal(self):
        with fixture() as tmp:
            root = make_root(tmp)
            procedures = self.copy(tmp)
            self.drop_error_outcome(procedures)
            (procedures / "oversize.md").write_bytes(b"x" * 8193)
            _, report = self.ci(root, procedures)
        check = self.check(report)
        self.assertEqual(check["reason_code"], "procedure_refused")
        self.assertEqual(check["facts"], {
            "procedures": ["deliver"], "refusals": [MISSING_ERROR], "count": 1,
            "breaches": [OVERSIZE], "breach_count": 1})
        self.assert_validates(report)

    def test_a_long_step_id_keeps_the_defect_in_the_bounded_fact(self):
        with fixture() as tmp:
            root = make_root(tmp)
            procedures = self.copy(tmp)
            self.write(procedures, "long.json", self.probe(
                "lint", {"ok": "done", "refused": "done"}, step_id="s" * 200))
            _, report = self.ci(root, procedures)
        check = self.check(report)
        self.assertEqual(check["reason_code"], "procedure_refused")
        self.assertEqual(check["facts"]["refusals"], [
            ("unmapped_outcome long " + "s" * 200 + ": on does not map 'failed'.")[:200]])
        self.assertTrue(check["facts"]["refusals"][0].startswith("unmapped_outcome long "))
        self.assert_validates(report)

    def test_an_unusable_procedure_directory_fails_with_its_own_reason(self):
        with fixture() as tmp:
            root = make_root(tmp)
            empty = tmp / "empty"
            empty.mkdir()
            _, report = self.ci(root, empty)
        check = self.check(report)
        self.assertEqual([check["status"], check["reason_code"], check["repair_id"]],
                         ["failed", "procedure_check_unusable", self.REPAIR_ID])
        self.assertEqual(set(check["facts"]), {"reason"})
        self.assertIn("holds no procedure file", check["facts"]["reason"])

    def test_the_check_reads_the_directory_engine_check_defaults_to(self):
        self.assertEqual(conformance_checks.SHIPPED_PROCEDURES.resolve(),
                         engine.PROCEDURES_DIR.resolve())
        self.assertEqual(conformance_checks.DELIVERY_PACKAGE.resolve(),
                         engine.ENGINE_DIR.resolve())
