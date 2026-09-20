import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from agent_model_drift_test_support import (
    DriftCliCase, baseline_value, coverage, record_value, seal_baseline)


def observation(matrix, dispatch_id="sdd-first-pass-task-review", *,
                observed_host="claude", observed_model=None,
                observed_effort=None, role=None, dispatch=True,
                escalation=None, count=1):
    site = next(site for site in matrix["dispatch_sites"]
                if site["id"] == dispatch_id)
    return {
        "declaration": {
            "dispatch_id": dispatch_id if dispatch else None,
            "role": site["role"] if role is None else role,
            "authority": "structured-dispatch" if dispatch
                         else "runtime-agent-type",
        },
        "requested": {"host": "claude", "model": site["model"],
                      "effort": site["effort"]},
        "configured": {"host": None, "model": None, "effort": None},
        "observed": {
            "host": observed_host,
            "model": observed_model or f"claude-{site['model']}-5-20260901",
            "effort": observed_effort or site["effort"],
            "authority": "assistant-execution",
        },
        "escalation": escalation,
        "count": count,
        "first_event_at": "2026-09-20T10:05:00Z",
        "last_event_at": "2026-09-20T10:05:00Z",
    }


class RoutingEvaluationTest(DriftCliCase):
    def run_observations(self, observations, *, baseline=None,
                         routing_coverage=None):
        route_coverage = routing_coverage or coverage(
            "full", sum(item["count"] for item in observations),
            sum(item["count"] for item in observations))
        record = record_value(routing_coverage=route_coverage,
                              observations=observations)
        return self.run(record=record, baseline=baseline)

    def finding_codes(self, report):
        return [finding["code"] for finding in report["routing"]["findings"]]

    def test_fully_covered_declared_execution_conforms(self):
        code, out, err = self.run_observations([observation(self.matrix)])
        self.assertEqual((code, err), (0, ""))
        report = json.loads(out)
        self.assertEqual(report["state"], "conforming")
        self.assertEqual(report["routing"]["evaluated_events"], 1)
        self.assertEqual(report["routing"]["findings"], [])
        self.assertEqual(report["routing"]["comparisons"], [{
            "run_id": "claude:repo:98", "dispatch": "sdd-first-pass-task-review",
            "role": "reviewer", "count": 1,
            "declaration": {"dispatch_id": "sdd-first-pass-task-review",
                            "role": "reviewer", "host": "claude",
                            "model": "opus", "effort": "high",
                            "authority": "structured-dispatch"},
            "requested": {"host": "claude", "model": "opus", "effort": "high"},
            "observed": {"host": "claude", "model": "claude-opus-5-20260901",
                         "effort": "high"},
            "coverage": coverage("full", 1, 1), "escalation": None,
        }])

    def test_request_declaration_mismatch_is_drift(self):
        item = observation(self.matrix)
        item["requested"]["model"] = "sonnet"
        code, out, _ = self.run_observations([item])
        self.assertEqual(code, 3)
        report = json.loads(out)
        self.assertEqual(report["state"], "drifted")
        self.assertIn("REQUEST_DECLARATION_MISMATCH", self.finding_codes(report))
        self.assertEqual(report["routing"]["comparisons"][0]["requested"]["model"],
                         "sonnet")

    def test_requested_host_mismatch_is_drift_and_remains_visible(self):
        item = observation(self.matrix)
        item["requested"]["host"] = "codex"
        code, out, _ = self.run_observations([item])
        self.assertEqual(code, 3)
        report = json.loads(out)
        self.assertEqual(report["state"], "drifted")
        self.assertIn("REQUEST_DECLARATION_MISMATCH", self.finding_codes(report))
        self.assertEqual(report["routing"]["comparisons"][0]["requested"]["host"],
                         "codex")

    def test_prohibited_model_effort_and_host_are_drift(self):
        base = baseline_value(self.matrix, self.matrix_digest)
        base["catalog"]["claude"]["models"]["opus"]["prohibited"] = [
            "claude-opus-4-retired"]
        base["catalog"]["claude"]["efforts"]["high"]["prohibited"] = ["xhigh"]
        base = seal_baseline(base)
        cases = {
            "model": (observation(self.matrix,
                                  observed_model="claude-opus-4-retired"),
                      "OBSERVED_MODEL_PROHIBITED"),
            "effort": (observation(self.matrix, observed_effort="xhigh"),
                       "OBSERVED_EFFORT_PROHIBITED"),
            "host": (observation(self.matrix, observed_host="codex"),
                     "OBSERVED_HOST_PROHIBITED"),
        }
        for name, (item, expected) in cases.items():
            with self.subTest(case=name):
                code, out, _ = self.run_observations([item], baseline=base)
                self.assertEqual(code, 3)
                report = json.loads(out)
                self.assertEqual(report["state"], "drifted")
                self.assertIn(expected, self.finding_codes(report))

    def test_missing_and_unclassified_execution_are_inconclusive(self):
        cases = {
            "missing-model": (None, "high", "EXECUTION_MODEL_MISSING"),
            "missing-effort": ("claude-opus-5-20260901", None,
                               "EXECUTION_EFFORT_MISSING"),
            "unclassified-model": ("claude-opus-unknown", "high",
                                   "MODEL_UNCLASSIFIED"),
            "unclassified-effort": ("claude-opus-5-20260901", "ultra",
                                    "EFFORT_UNCLASSIFIED"),
        }
        for name, (model, effort, expected) in cases.items():
            with self.subTest(case=name):
                item = observation(self.matrix)
                item["observed"]["model"] = model
                item["observed"]["effort"] = effort
                code, out, _ = self.run_observations([item])
                self.assertEqual(code, 3)
                report = json.loads(out)
                self.assertEqual(report["state"], "inconclusive")
                self.assertIn(expected, self.finding_codes(report))

    def test_aggregate_only_coverage_never_implies_conformance(self):
        route_coverage = coverage(
            "none", 3, 0,
            [{"code": "role_ambiguous", "count": 3}])
        code, out, _ = self.run_observations(
            [], routing_coverage=route_coverage)
        self.assertEqual(code, 3)
        report = json.loads(out)
        self.assertEqual(report["state"], "inconclusive")
        self.assertIn("ROUTING_COVERAGE_MISSING", self.finding_codes(report))
        self.assertNotIn("REQUEST_DECLARATION_MISMATCH", self.finding_codes(report))
        self.assertEqual(report["routing"]["eligible_events"], 3)
        self.assertEqual(report["routing"]["comparisons"], [])

    def test_reviewer_lite_requires_dispatch(self):
        item = observation(self.matrix, "sdd-scoped-task-rereview", dispatch=False)
        code, out, _ = self.run_observations([item])
        self.assertEqual(code, 3)
        report = json.loads(out)
        self.assertEqual(report["state"], "inconclusive")
        self.assertIn("DISPATCH_REQUIRED", self.finding_codes(report))

    def test_valid_escalation_targets_a_new_declared_dispatch(self):
        item = observation(
            self.matrix, "sdd-task-rereview-escalation",
            escalation={"source_dispatch_id": "sdd-scoped-task-rereview",
                        "reason_code": "capacity"})
        code, out, err = self.run_observations([item])
        self.assertEqual((code, err), (0, ""))
        report = json.loads(out)
        self.assertEqual(report["state"], "conforming")
        self.assertEqual(report["routing"]["comparisons"][0]["escalation"], {
            "source_dispatch_id": "sdd-scoped-task-rereview",
            "target_dispatch_id": "sdd-task-rereview-escalation",
            "reason_code": "capacity",
        })

    def test_missing_or_out_of_scope_escalation_reason_is_drift(self):
        for reason in (None, "cheaper"):
            with self.subTest(reason=reason):
                item = observation(
                    self.matrix, "sdd-task-rereview-escalation",
                    escalation={"source_dispatch_id": "sdd-scoped-task-rereview",
                                "reason_code": reason})
                code, out, _ = self.run_observations([item])
                self.assertEqual(code, 3)
                report = json.loads(out)
                self.assertEqual(report["state"], "drifted")
                self.assertIn("ESCALATION_INVALID", self.finding_codes(report))

    def test_same_request_hot_substitution_remains_drift(self):
        base = baseline_value(self.matrix, self.matrix_digest)
        base["catalog"]["claude"]["models"]["sonnet"]["prohibited"] = [
            "claude-opus-5-20260901"]
        base = seal_baseline(base)
        item = observation(
            self.matrix, "sdd-scoped-task-rereview",
            observed_model="claude-opus-5-20260901")
        code, out, _ = self.run_observations([item], baseline=base)
        self.assertEqual(code, 3)
        report = json.loads(out)
        self.assertEqual(report["state"], "drifted")
        self.assertIn("OBSERVED_MODEL_PROHIBITED", self.finding_codes(report))

    def test_drift_precedes_unrelated_inconclusive_and_findings_are_sorted(self):
        drift = observation(self.matrix, count=2)
        drift["requested"]["effort"] = "medium"
        missing = observation(self.matrix, "from-issue-plan-review")
        missing["observed"]["model"] = None
        code, out, _ = self.run_observations([missing, drift])
        self.assertEqual(code, 3)
        report = json.loads(out)
        self.assertEqual(report["state"], "drifted")
        findings = report["routing"]["findings"]
        self.assertEqual(findings, sorted(
            findings, key=lambda item: (item["code"], item["run_id"] or "",
                                        item["dispatch"] or "",
                                        item["role"] or "", item["count"])))
        mismatch = next(item for item in findings
                        if item["code"] == "REQUEST_DECLARATION_MISMATCH")
        self.assertEqual(mismatch["count"], 2)
