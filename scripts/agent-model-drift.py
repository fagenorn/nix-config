#!/usr/bin/env python3
"""Evaluate strict agent-cost records against a signed baseline."""
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


def _finding(code):
    return {"code": code, "run": None, "dispatch": None, "role": None, "count": 1}


def evaluate(record, baseline, matrix, matrix_digest, now):
    now_time = schema.canonical_time(now)
    telemetry = record["telemetry"]
    findings = []
    if telemetry is None:
        findings = [_finding("IDENTITY_MISSING"), _finding("ROUTING_COVERAGE_MISSING")]
    else:
        window = telemetry["event_window"]
        if window["start"] is None or window["end"] is None:
            findings.append(_finding("WINDOW_UNBOUNDED"))
        elif not (schema.canonical_time(window["start"]) >= schema.canonical_time(baseline["valid_from"]) and schema.canonical_time(window["end"]) <= schema.canonical_time(baseline["valid_before"])):
            findings.append(_finding("WINDOW_OUTSIDE_BASELINE"))
        if schema.canonical_time(baseline["captured_at"]) > now_time:
            findings.append(_finding("BASELINE_FUTURE"))
        if now_time >= schema.canonical_time(baseline["valid_before"]):
            findings.append(_finding("BASELINE_STALE"))
        producer = telemetry["producer"]
        if producer["harness_versions"] and any(value is None for value in producer["harness_versions"].values()):
            findings.append(_finding("IDENTITY_MISSING"))
        if (baseline["matrix_digest"] != matrix_digest or baseline["producer"] != {"name": producer["name"], "version": producer["version"], "telemetry_schema_version": telemetry["schema_version"]} or baseline["harness_versions"] != producer["harness_versions"]):
            findings.append(_finding("IDENTITY_MISMATCH"))
        if telemetry["source_coverage"]["routing"]["state"] != "full":
            findings.append(_finding("ROUTING_COVERAGE_MISSING"))
    findings.sort(key=lambda item: (item["code"], "", "", ""))
    state = "conforming" if not findings else "inconclusive"
    routing = {"state": state, "eligible_events": 0 if telemetry is None else telemetry["source_coverage"]["routing"]["eligible_events"], "evaluated_events": 0, "comparisons": [], "findings": findings}
    unavailable = {"value": None, "coverage": {"state": "unavailable"}}
    metrics = {name: dict(unavailable) for name in (
        "spawn_attempts", "capacity_rejections", "waits", "follow_ups",
        "wait_input_tokens", "covered_input_tokens", "slot_capacity_seconds",
        "claimed_slot_seconds")}
    return {"schema_version": 1, "kind": "agent-model-drift-report", "evaluated_at": now,
            "inputs": {"record": record["record"]["record_id"], "matrix": matrix_digest, "baseline": baseline["baseline_id"]},
            "state": state, "routing": routing,
            "scheduling": {"state": "unmeasured", "metrics": metrics, "wait_token_share": unavailable, "occupancy": unavailable},
            "context": {"cache_read_ratio": unavailable}}


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
        print("invalid drift input", file=sys.stderr)
        return 2
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0 if report["state"] == "conforming" else 3


if __name__ == "__main__":
    raise SystemExit(main())
