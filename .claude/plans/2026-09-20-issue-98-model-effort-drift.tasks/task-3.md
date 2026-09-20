# Task 3: Strictly decode current/legacy records and validate baselines

**Files:**
- Create: `scripts/agent-model-drift.py`
- Create: `scripts/agent-model-drift-schema.py`
- Create: `tests/agent_model_drift_test_support.py`
- Create: `tests/test_agent_model_drift_schema.py`

**Risk lane:** full — new public CLI, strict compatibility contract, baseline lifecycle, and exit semantics.

**Interfaces:**
- Consumes Task 2's current `agent-cost-record`, valid legacy schema-v1 records without `execution_telemetry`, and the repository matrix only through `agent-model-matrix.py`'s `validate(root)` and `load_matrix(root)` (D3, D8, D12, D13).
- `agent-model-drift-schema.py` produces `InputError`, `load_json(path)`, `canonical_digest(value)`, `canonical_time(value)`, `load_validated_matrix(root)`, `validate_record(value)`, and `validate_baseline(value, matrix, matrix_digest)`.
- `validate_record` returns `{"record": <decoded>, "telemetry": dict | None}`. `telemetry: None` is reserved for an otherwise valid legacy v1 record; malformed or unsupported telemetry is never downgraded to legacy.
- `agent-model-drift.py` loads its schema sibling with `SourceFileLoader`, owns the CLI `--record PATH --baseline PATH --matrix-root PATH --now RFC3339-UTC`, and produces `main(argv) -> int` plus a pure lifecycle `evaluate(...) -> dict`. Tasks 4–5 add routing and scheduling sibling loaders without moving schema code back into the entry point.
- `tests/agent_model_drift_test_support.py` produces shared production-shaped builders `digest`, `coverage`, `unsupported_metric`, `telemetry`, `record_value`, `legacy_record_value`, `seal_record`, `matrix_fixture`, `baseline_value`, `seal_baseline`, and `DriftCliCase`.
- `record_value` calls Task 2's real `agent_costs.build_record(...)` projection with a complete Claude group, deterministic window, and supplied telemetry. `legacy_record_value` removes only the additive telemetry member from that emitted record and reseals it. The helpers never invent abbreviated `strata` or `fleet.totals` shapes.

The baseline has exactly the design fields: `schema_version`, `kind`, `baseline_id`, `captured_at`, `valid_from`, `valid_before`, `matrix_digest`, `producer`, `harness_versions`, `model_catalog_version`, `dispatch_hosts`, `catalog`, and `escalation_reason_codes`. `baseline_id` digests every other member. Dispatch-host keys equal every matrix dispatch. Per host, model/effort tier keys equal the declared tier sets; sorted unique non-empty string arrays are disjoint within a tier.

The report has exactly `schema_version`, `kind`, `evaluated_at`, `inputs`, `state`, `routing`, `scheduling`, and `context`. `routing` is exactly `state`, `eligible_events`, `evaluated_events`, `comparisons`, `findings`; Task 3 emits no comparisons because its cases have no paired executions. `scheduling` is exactly `state`, `metrics`, `wait_token_share`, `occupancy`. `context` is exactly `cache_read_ratio`; until Task 5 projects available totals, its value is null/unavailable. Findings are exactly code/run/dispatch/role/count and sorted with null treated as empty.

**Invariants:**
- Matrix validation failure is exit `2`, diagnostic stderr, empty stdout. The reporter never accepts a locally parsed matrix after the repository validator rejects it (D3, D8).
- Current records require the exact post-change outer members and exact telemetry shape. Legacy records require the exact pre-extension v1 outer members. Both verify `record_id` over the body excluding only `record_id` and `generated_at`; an `execution_telemetry` member with a wrong type/version/shape is malformed, not legacy (D1, D12).
- A valid legacy record exits `3` with routing `inconclusive`, exactly `IDENTITY_MISSING` and `ROUTING_COVERAGE_MISSING` global findings, empty comparisons, scheduling `unmeasured`, and no fabricated routing/scheduling values (D12).
- Baseline timestamps are UTC and ordered `valid_from <= captured_at < valid_before`. Malformed time/interval is exit `2`; future capture, stale validity, outside window, or concrete matrix/producer/harness mismatch is valid inconclusive exit `3` (D3, D4).
- Baseline dispatch/tier coverage is exact; missing/extra dispatches or tiers, wrong types, duplicate keys, overlapping classification arrays, digest errors, and unsupported versions are exit `2`.
- Null telemetry identity evidence yields `IDENTITY_MISSING`; unequal concrete producer, harness/runtime, or matrix identity yields `IDENTITY_MISMATCH`. Neither is parser failure.
- Explicit `--now` is the only evaluated time. Identical inputs and time produce byte-identical stdout. Evaluators are pure; only `main` performs I/O.

- [ ] **Step 1: Write the failing support and schema/lifecycle CLI tests**

Create `tests/agent_model_drift_test_support.py` with the imports and helpers below. The `telemetry`, record, matrix, and baseline bodies are complete wire fixtures, not abbreviated test-only shapes.

```python
from __future__ import annotations

import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "agent-model-drift.py"
COST_SCRIPT = REPO_ROOT / "scripts" / "agent-costs.py"
MATRIX = REPO_ROOT / "home/common/agent-skills/model-matrix.json"

_spec = importlib.util.spec_from_file_location("agent_model_drift", SCRIPT)
agent_model_drift = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(agent_model_drift)

_cost_spec = importlib.util.spec_from_file_location(
    "agent_costs_fixture", COST_SCRIPT)
agent_costs = importlib.util.module_from_spec(_cost_spec)
_cost_spec.loader.exec_module(agent_costs)


def digest(value):
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return "sha256:" + hashlib.sha256(payload.encode()).hexdigest()


def coverage(state="full", eligible=0, paired=0, reasons=None):
    return {"state": state, "eligible_events": eligible,
            "paired_events": paired, "reasons": reasons or []}


def unsupported_metric():
    return {"value": None,
            "coverage": coverage("none", reasons=[
                {"code": "source_unsupported", "count": 1}]),
            "cohort_digest": None}


def telemetry(*, start="2026-09-20T10:00:00Z",
              end="2026-09-20T11:00:00Z", harness=None,
              routing_coverage=None, observations=None):
    metrics = {name: unsupported_metric() for name in (
        "spawn_attempts", "capacity_rejections", "waits", "follow_ups",
        "wait_input_tokens", "covered_input_tokens",
        "slot_capacity_seconds", "claimed_slot_seconds")}
    route = routing_coverage or coverage()
    return {
        "schema_version": 1,
        "producer": {"name": "agent-costs", "version": 1,
                     "harness_versions": harness or {"claude": ["2.1.0"]}},
        "event_window": {"start": start, "end": end},
        "source_coverage": {
            "routing": copy.deepcopy(route),
            "scheduling": {name: copy.deepcopy(metric["coverage"])
                           for name, metric in metrics.items()}},
        "runs": [{"run_id": "claude:repo:98",
                  "routing": {"coverage": copy.deepcopy(route),
                              "observations": observations or []},
                  "scheduling": metrics}],
    }


def _producer_record(execution_telemetry):
    group = agent_costs.new_group()
    group["sessions"] = 1
    record = agent_costs.build_record(
        {"claude": {"cost_basis": "list-price",
                    "groups": {("repo", "98"): group}}},
        {"days": 1, "cutoff_epoch": 1,
         "file_mtime_selection": True,
         "whole_selected_file_usage": True,
         "strata": ["claude"], "sources": {"claude": "/redacted"}},
        execution_telemetry=execution_telemetry)
    record["generated_at"] = "2026-09-20T11:01:00Z"
    return record


def record_value(**overrides):
    return _producer_record(telemetry(**overrides))


def legacy_record_value():
    value = record_value()
    value.pop("execution_telemetry")
    return seal_record(value)


def seal_record(value):
    body = copy.deepcopy(value)
    generated_at = body.pop("generated_at", "2026-09-20T11:01:00Z")
    body.pop("record_id", None)
    return dict(body, record_id=digest(body), generated_at=generated_at)


def matrix_fixture(root):
    data = json.loads(MATRIX.read_text(encoding="utf-8"))
    targets = [Path("home/common/agent-skills/model-matrix.json"),
               Path("home/common/agent-skills/scripts/agent-model-matrix.py")]
    targets += [Path(site["path"]) for site in data["dispatch_sites"]]
    targets += [path.relative_to(REPO_ROOT) for path in
                (REPO_ROOT / "home/common/claude-code/agents").glob("*.md")]
    for relative in sorted(set(targets)):
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / relative, destination)
    return data


def baseline_value(matrix, matrix_digest, **updates):
    models = sorted({role["model"] for role in matrix["roles"].values()})
    efforts = sorted({role["effort"] for role in matrix["roles"].values()})
    body = {
        "schema_version": 1, "kind": "agent-model-baseline",
        "captured_at": "2026-09-20T09:00:00Z",
        "valid_from": "2026-09-20T00:00:00Z",
        "valid_before": "2026-09-21T00:00:00Z",
        "matrix_digest": matrix_digest,
        "producer": {"name": "agent-costs", "version": 1,
                     "telemetry_schema_version": 1},
        "harness_versions": {"claude": ["2.1.0"]},
        "model_catalog_version": "catalog-2026-09-20",
        "dispatch_hosts": {site["id"]: "claude" for site in matrix["dispatch_sites"]},
        "catalog": {"claude": {
            "models": {tier: {"allowed": [f"claude-{tier}-5-20260901"],
                              "prohibited": []} for tier in models},
            "efforts": {tier: {"allowed": [tier], "prohibited": []}
                        for tier in efforts}}},
        "escalation_reason_codes": ["capacity", "source-unavailable"],
    }
    body.update(updates)
    return dict(body, baseline_id=digest(body))


def seal_baseline(value):
    body = copy.deepcopy(value)
    body.pop("baseline_id", None)
    return dict(body, baseline_id=digest(body))


class DriftCliCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.matrix_root = self.root / "matrix"
        self.matrix = matrix_fixture(self.matrix_root)
        self.matrix_digest = digest(self.matrix)

    def write(self, name, value):
        path = self.root / name
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def run(self, record=None, baseline=None, now="2026-09-20T12:00:00Z"):
        record = record_value() if record is None else record
        baseline = (baseline_value(self.matrix, self.matrix_digest)
                    if baseline is None else baseline)
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = agent_model_drift.main([
                "--record", str(self.write("record.json", record)),
                "--baseline", str(self.write("baseline.json", baseline)),
                "--matrix-root", str(self.matrix_root), "--now", now])
        return code, stdout.getvalue(), stderr.getvalue()
```

Create `tests/test_agent_model_drift_schema.py` with the full CLI cases:

```python
import contextlib
import copy
import io
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from agent_model_drift_test_support import (
    DriftCliCase, agent_model_drift, baseline_value, legacy_record_value,
    record_value, seal_baseline, seal_record)


class BaselineLifecycleTest(DriftCliCase):
    def test_fresh_matching_zero_event_cohort_is_deterministic_and_conforming(self):
        first, second = self.run(), self.run()
        self.assertEqual(first, second)
        code, out, err = first
        self.assertEqual((code, err), (0, ""))
        report = json.loads(out)
        self.assertEqual(set(report), {
            "schema_version", "kind", "evaluated_at", "inputs", "state",
            "routing", "scheduling", "context"})
        self.assertEqual(report["schema_version"], 1)
        self.assertEqual(report["kind"], "agent-model-drift-report")
        self.assertEqual(report["evaluated_at"], "2026-09-20T12:00:00Z")
        self.assertEqual(report["inputs"], {
            "record": record_value()["record_id"],
            "matrix": self.matrix_digest,
            "baseline": baseline_value(
                self.matrix, self.matrix_digest)["baseline_id"],
        })
        self.assertEqual((report["state"], report["routing"]), (
            "conforming", {"state": "conforming", "eligible_events": 0,
                           "evaluated_events": 0, "comparisons": [], "findings": []}))

    def test_valid_legacy_v1_is_unknown_not_malformed(self):
        code, out, err = self.run(record=legacy_record_value())
        self.assertEqual((code, err), (3, ""))
        report = json.loads(out)
        self.assertEqual(report["state"], "inconclusive")
        self.assertEqual([finding["code"] for finding in report["routing"]["findings"]],
                         ["IDENTITY_MISSING", "ROUTING_COVERAGE_MISSING"])
        self.assertEqual(report["routing"]["comparisons"], [])
        self.assertEqual(report["scheduling"]["state"], "unmeasured")

    def test_lifecycle_and_concrete_identity_incompatibility_exit_three(self):
        cases = {
            "unbounded": (record_value(start=None, end=None), None,
                          "WINDOW_UNBOUNDED"),
            "future": (None, baseline_value(self.matrix, self.matrix_digest,
                captured_at="2026-09-20T13:00:00Z"), "BASELINE_FUTURE"),
            "stale": (None, baseline_value(self.matrix, self.matrix_digest,
                valid_before="2026-09-20T12:00:00Z"), "BASELINE_STALE"),
            "outside": (record_value(start="2026-09-19T23:00:00Z"), None,
                        "WINDOW_OUTSIDE_BASELINE"),
            "identity-missing": (record_value(harness={"claude": None}), None,
                                 "IDENTITY_MISSING"),
            "producer-mismatch": (None, baseline_value(
                self.matrix, self.matrix_digest,
                producer={"name": "agent-costs", "version": 2,
                          "telemetry_schema_version": 1}), "IDENTITY_MISMATCH"),
            "harness-mismatch": (None, baseline_value(
                self.matrix, self.matrix_digest,
                harness_versions={"claude": ["2.0.0"]}), "IDENTITY_MISMATCH"),
            "matrix-mismatch": (None, baseline_value(
                self.matrix, "sha256:" + "0" * 64), "IDENTITY_MISMATCH"),
        }
        for name, (record, baseline, expected) in cases.items():
            with self.subTest(case=name):
                code, out, err = self.run(record=record, baseline=baseline)
                self.assertEqual((code, err), (3, ""))
                self.assertIn(expected, [item["code"] for item in
                                         json.loads(out)["routing"]["findings"]])

    def test_malformed_baseline_boundaries_exit_two_with_empty_stdout(self):
        valid = baseline_value(self.matrix, self.matrix_digest)
        cases = {}
        for name in ("wrong-type", "bad-time", "missing-dispatch", "extra-dispatch",
                     "missing-model-tier", "extra-effort-tier", "overlap",
                     "unsupported-version", "unknown-member"):
            candidate = copy.deepcopy(valid)
            if name == "wrong-type":
                candidate["dispatch_hosts"] = []
            elif name == "bad-time":
                candidate["captured_at"] = "not-a-time"
            elif name == "missing-dispatch":
                candidate["dispatch_hosts"].pop(next(iter(candidate["dispatch_hosts"])))
            elif name == "extra-dispatch":
                candidate["dispatch_hosts"]["unknown"] = "claude"
            elif name == "missing-model-tier":
                candidate["catalog"]["claude"]["models"].pop("opus")
            elif name == "extra-effort-tier":
                candidate["catalog"]["claude"]["efforts"]["ultra"] = {
                    "allowed": ["ultra"], "prohibited": []}
            elif name == "overlap":
                tier = candidate["catalog"]["claude"]["models"]["opus"]
                tier["prohibited"] = list(tier["allowed"])
            elif name == "unsupported-version":
                candidate["schema_version"] = 2
            else:
                candidate["extra"] = True
            cases[name] = seal_baseline(candidate)
        for name, candidate in cases.items():
            with self.subTest(case=name):
                code, out, err = self.run(baseline=candidate)
                self.assertEqual(code, 2)
                self.assertEqual(out, "")
                self.assertNotEqual(err, "")

    def test_malformed_record_and_rejected_matrix_exit_two(self):
        bad_type = record_value()
        bad_type["execution_telemetry"] = []
        bad_version = record_value()
        bad_version["schema_version"] = 2
        unknown = record_value()
        unknown["extra"] = True
        for candidate in map(seal_record, (bad_type, bad_version, unknown)):
            code, out, err = self.run(record=candidate)
            self.assertEqual(code, 2)
            self.assertEqual(out, "")
            self.assertNotEqual(err, "")

        matrix_path = (self.matrix_root /
                       "home/common/agent-skills/model-matrix.json")
        matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
        matrix["roles"]["reviewer"]["model"] = "sonnet"
        matrix_path.write_text(json.dumps(matrix), encoding="utf-8")
        code, out, err = self.run()
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertNotEqual(err, "")

    def test_corrupted_record_and_baseline_ids_exit_two_without_report(self):
        cases = {
            "record-id": (dict(record_value(), record_id="sha256:" + "0" * 64),
                          None),
            "baseline-id": (None, dict(
                baseline_value(self.matrix, self.matrix_digest),
                baseline_id="sha256:" + "0" * 64)),
        }
        for name, (record, baseline) in cases.items():
            with self.subTest(case=name):
                code, out, err = self.run(record=record, baseline=baseline)
                self.assertEqual(code, 2)
                self.assertEqual(out, "")
                self.assertNotEqual(err, "")

    def test_duplicate_json_keys_exit_two_before_decode(self):
        record_path = self.write("record.json", record_value())
        duplicate = self.root / "duplicate.json"
        duplicate.write_text('{"schema_version":1,"schema_version":1}\n',
                             encoding="utf-8")
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = agent_model_drift.main([
                "--record", str(record_path), "--baseline", str(duplicate),
                "--matrix-root", str(self.matrix_root),
                "--now", "2026-09-20T12:00:00Z"])
        self.assertEqual(code, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertNotEqual(stderr.getvalue(), "")
```

- [ ] **Step 2: Run the schema suite and watch it fail**

Run: `python3 -m unittest -v tests/test_agent_model_drift_schema.py`

Expected: ERROR at support-module import because `scripts/agent-model-drift.py` does not exist.

- [ ] **Step 3: Implement bounded schema and CLI modules**

Create `agent-model-drift-schema.py` with all strict loaders/validators. Load the matrix validator from the supplied root, register it in `sys.modules`, call `validate(root)`, reject any errors, then call `load_matrix(root)`. Schema validation collects stable JSON-pointer violations but `main` prints one concise diagnostic line without source content.

Create `agent-model-drift.py` as the thin entry point and lifecycle report shell. Recompute record/baseline digests; distinguish exact current and legacy outer-member sets; validate top-level aggregate coverage against run sums. Emit global findings with null run/dispatch/role and count 1. For Task 3's unavailable scheduling/context, emit the final exact shapes with null values and unavailable coverage so later modules replace values without changing the report schema.

- [ ] **Step 4: Verify strict compatibility and lifecycle boundaries**

Run: `python3 -m unittest -v tests/test_agent_model_drift_schema.py`

Expected: PASS; valid producer-projected current and legacy records, exact report identity/time/input digests, lifecycle/identity incompatibility, corrupted record/baseline ids, malformed types/times/catalog coverage/overlap, and rejected matrix cases have the specified exits/stdout.

Run: `git diff --check -- scripts/agent-model-drift.py scripts/agent-model-drift-schema.py tests/agent_model_drift_test_support.py tests/test_agent_model_drift_schema.py`

Expected: exit `0`; these four paths are the complete Task 3 expected scope.

- [ ] **Step 5: Commit the strict consumer foundation**

```bash
git add scripts/agent-model-drift.py scripts/agent-model-drift-schema.py \
  tests/agent_model_drift_test_support.py tests/test_agent_model_drift_schema.py
git commit -S -m "feat(telemetry): validate drift baselines" \
  -m "Co-Authored-By: Codex <noreply@openai.com>"
```
