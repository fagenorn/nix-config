#!/usr/bin/env python3
"""Evaluate strict agent-cost records against a canonical-digest baseline."""
from __future__ import annotations
import argparse
import importlib.machinery
import importlib.util
import json
import sys
from pathlib import Path

_loader = importlib.machinery.SourceFileLoader("agent_model_drift_schema", str(Path(__file__).with_name("agent-model-drift-schema.py")))
_spec = importlib.util.spec_from_loader(_loader.name, _loader)
schema = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = schema
_loader.exec_module(schema)

_routing_loader = importlib.machinery.SourceFileLoader(
    "agent_model_drift_routing", str(Path(__file__).with_name("agent-model-drift-routing.py")))
_routing_spec = importlib.util.spec_from_loader(_routing_loader.name, _routing_loader)
routing_logic = importlib.util.module_from_spec(_routing_spec)
sys.modules[_routing_spec.name] = routing_logic
_routing_loader.exec_module(routing_logic)

_scheduling_loader = importlib.machinery.SourceFileLoader(
    "agent_model_drift_scheduling", str(Path(__file__).with_name("agent-model-drift-scheduling.py")))
_scheduling_spec = importlib.util.spec_from_loader(_scheduling_loader.name, _scheduling_loader)
scheduling_logic = importlib.util.module_from_spec(_scheduling_spec)
sys.modules[_scheduling_spec.name] = scheduling_logic
_scheduling_loader.exec_module(scheduling_logic)


def _finding(code):
    return {"code": code, "run_id": None, "dispatch": None, "role": None, "count": 1}


def evaluate(record, baseline, matrix, matrix_digest, now):
    now_time = schema.canonical_time(now)
    telemetry = record["telemetry"]
    findings = []
    comparisons = []
    evaluated_events = 0
    if telemetry is None:
        findings = [_finding("IDENTITY_MISSING"), _finding("ROUTING_COVERAGE_MISSING")]
    else:
        window = telemetry["event_window"]
        baseline_usable = True
        if window["start"] is None or window["end"] is None:
            findings.append(_finding("WINDOW_UNBOUNDED"))
            baseline_usable = False
        elif not (schema.canonical_time(window["start"]) >= schema.canonical_time(baseline["valid_from"]) and schema.canonical_time(window["end"]) <= schema.canonical_time(baseline["valid_before"])):
            findings.append(_finding("WINDOW_OUTSIDE_BASELINE"))
            baseline_usable = False
        if schema.canonical_time(baseline["captured_at"]) > now_time:
            findings.append(_finding("BASELINE_FUTURE"))
            baseline_usable = False
        if now_time >= schema.canonical_time(baseline["valid_before"]):
            findings.append(_finding("BASELINE_STALE"))
            baseline_usable = False
        producer = telemetry["producer"]
        missing_identity = any(value is None for value in producer["harness_versions"].values())
        if missing_identity:
            findings.append(_finding("IDENTITY_MISSING"))
            baseline_usable = False
        if (baseline["matrix_digest"] != matrix_digest or baseline["producer"] != {"name": producer["name"], "version": producer["version"], "telemetry_schema_version": telemetry["schema_version"]} or (not missing_identity and baseline["harness_versions"] != producer["harness_versions"])):
            findings.append(_finding("IDENTITY_MISMATCH"))
            baseline_usable = False
        if telemetry["source_coverage"]["routing"]["state"] != "full":
            findings.append(_finding("ROUTING_COVERAGE_MISSING"))
        for run in telemetry["runs"]:
            for observation in run["routing"]["observations"]:
                comparison, observation_findings, evaluated = routing_logic.evaluate_observation(
                    observation, matrix, baseline, run["run_id"], run["routing"]["coverage"],
                    baseline_usable=baseline_usable)
                comparisons.append(comparison)
                findings.extend(observation_findings)
                evaluated_events += evaluated
    findings = routing_logic.aggregate_findings(findings)
    comparisons.sort(key=routing_logic.comparison_key)
    state = ("drifted" if any(item["code"] in routing_logic.DRIFT_CODES for item in findings)
             else "conforming" if not findings else "inconclusive")
    routing = {"state": state, "eligible_events": 0 if telemetry is None else telemetry["source_coverage"]["routing"]["eligible_events"], "evaluated_events": evaluated_events, "comparisons": comparisons, "findings": findings}
    if telemetry is None:
        metrics = {name: {"value": None, "coverage": {"state": "none",
                   "eligible_events": 0, "paired_events": 0,
                   "reasons": [{"code": "source_unsupported", "count": 1}]},
                   "cohort_digest": None}
                   for name in schema.SCHEDULING_METRICS}
        scheduling = {"state": "unmeasured", "metrics": metrics,
                      "wait_token_share": None, "occupancy": None}
    else:
        scheduling = scheduling_logic.project_scheduling(
            telemetry["runs"], telemetry["source_coverage"], telemetry["event_window"])
    context = scheduling_logic.project_context(record["record"]["fleet"])
    return {"schema_version": 1, "kind": "agent-model-drift-report", "evaluated_at": now,
            "inputs": {"record": record["record"]["record_id"], "matrix": matrix_digest, "baseline": baseline["baseline_id"]},
            "state": state, "routing": routing,
            "scheduling": scheduling, "context": context}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--record", required=True)
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--matrix-root", required=True)
    parser.add_argument("--now", required=True)
    try:
        args = parser.parse_args(argv)
        matrix = schema.load_validated_matrix(args.matrix_root)
        matrix_digest = schema.canonical_digest(matrix)
        record = schema.validate_record(schema.load_json(args.record))
        baseline = schema.validate_baseline(schema.load_json(args.baseline), matrix, matrix_digest)
        report = evaluate(record, baseline, matrix, matrix_digest, args.now)
    except (schema.InputError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 2
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0 if report["state"] == "conforming" else 3


if __name__ == "__main__":
    raise SystemExit(main())
