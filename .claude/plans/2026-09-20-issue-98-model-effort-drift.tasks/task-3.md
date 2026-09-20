# Task 3: Strictly decode records, validate baselines, and report lifecycle incompatibility

**Files:**
- Create: `scripts/agent-model-drift.py`
- Create: `tests/test_agent_model_drift.py`

**Risk lane:** full — new public CLI, strict input contract, baseline lifecycle, and exit semantics.

**Interfaces:**
- Consumes:
  - Task 2's `agent-cost-record` with version-1 `execution_telemetry`.
  - The repository matrix through `agent-model-matrix.py`'s `validate(root)` and `load_matrix(root)`; never duplicate `EXPECTED_ROLE_TIERS`, reviewer-lite requirements, dispatch validation, or manifest checks (D3, D6, D8).
- Produces:
  - CLI: `agent-model-drift.py --record PATH --baseline PATH --matrix-root PATH --now RFC3339-UTC`.
  - `def load_json(path: Path) -> object` — UTF-8, duplicate-key rejecting via `object_pairs_hook`; raises `InputError` for unreadable or malformed input.
  - `def load_validated_matrix(root: Path) -> tuple[dict, str]` — calls the existing validator, then returns its loaded object and canonical `sha256:` digest.
  - `def validate_record(value: object) -> dict` and `def validate_baseline(value: object, matrix: dict, matrix_digest: str) -> dict` — strict, non-mutating decoders; unknown members, wrong types, duplicate keys, digest mismatch, or unsupported versions raise `InputError`.
  - `def canonical_digest(value: object) -> str` and `def canonical_time(value: str) -> tuple[datetime, str]`.
  - `def evaluate(record: dict, matrix: dict, matrix_digest: str, baseline: dict, now: datetime) -> dict` — pure; Task 3 fully evaluates window/baseline/identity/coverage findings, while Task 4 adds per-observation routing decisions.
  - `def main(argv: list[str] | None = None) -> int` — valid report to stdout plus newline; diagnostics to stderr and exit `2` with empty stdout on every tool/input failure.

The baseline has exactly these top-level members:

```json
{
  "schema_version": 1,
  "kind": "agent-model-baseline",
  "baseline_id": "sha256:<canonical body digest>",
  "captured_at": "2026-09-20T09:00:00Z",
  "valid_from": "2026-09-20T00:00:00Z",
  "valid_before": "2026-09-21T00:00:00Z",
  "matrix_digest": "sha256:...",
  "producer": {"name": "agent-costs", "version": 1, "telemetry_schema_version": 1},
  "harness_versions": {"claude": ["2.1.0"]},
  "model_catalog_version": "catalog-2026-09-20",
  "dispatch_hosts": {"<every matrix dispatch id>": "claude"},
  "catalog": {
    "claude": {
      "models": {"<every declared model tier>": {"allowed": ["..."], "prohibited": ["..."]}},
      "efforts": {"<every declared effort tier>": {"allowed": ["..."], "prohibited": ["..."]}}
    }
  },
  "escalation_reason_codes": ["capacity", "source-unavailable"]
}
```

`baseline_id` is the canonical digest of every member except `baseline_id`. Dispatch-host keys equal the matrix dispatch-id set. Within each host, model-tier keys and effort-tier keys equal the matrix's declared tier sets. Arrays are sorted unique non-empty strings; allowed/prohibited arrays for one tier are disjoint. Host keys are literal execution hosts, not aliases.

The report has exactly `schema_version`, `kind`, `evaluated_at`, `inputs`, `state`, `routing`, and `scheduling`. `inputs` is exactly `record`, `matrix`, `baseline`. `routing` is exactly `state`, `eligible_events`, `evaluated_events`, `findings`. `scheduling` is exactly `state`, `metrics`, `wait_token_share`, `occupancy`. Every finding is exactly `code`, `run_id`, `dispatch`, `role`, `count` and is sorted by those fields with null treated as empty string.

**Invariants:**
- Matrix validation failure is an input/tool failure: exit `2`, diagnostic on stderr, no JSON on stdout. The reporter never accepts a hand-parsed matrix after the repository validator rejects it (D3, D8).
- The record decoder requires exact outer members emitted by `build_record` and exact telemetry members from Tasks 1–2. It validates `record_id` against the body excluding only `record_id` and `generated_at`; accounting subdocuments are treated as opaque known objects because routing never consumes or reinterprets them.
- Baseline times are aware UTC and ordered `valid_from <= captured_at < valid_before`. A malformed interval is exit `2`; a well-formed capture after `--now`, expiration at/before `--now`, or telemetry window outside the validity interval is a valid inconclusive report (D3, D4).
- Telemetry producer name/version/schema, selected harness-version keys and sorted version arrays, and matrix digest must exactly match the baseline. Null/missing harness version evidence yields `IDENTITY_MISSING`; unequal concrete identity yields `IDENTITY_MISMATCH`. Either suppresses conformance (D3).
- Null event-window bounds yield `WINDOW_UNBOUNDED`. No proven drift exists in Task 3, so lifecycle/coverage findings yield `inconclusive`; a fully covered bounded zero-event cohort with fresh matching identity is `conforming` (D4).
- `evaluated_at` is the canonicalized explicit `--now`, never wall-clock time. Identical inputs and `--now` produce byte-identical stdout.
- The evaluator never opens a file, reads the environment, or imports transcript parsers. Only `main` performs I/O.

- [ ] **Step 1: Write the failing baseline and lifecycle CLI tests**

Create `tests/test_agent_model_drift.py` with this complete initial contract:

```python
"""CLI contract for the structured model/effort drift reporter."""

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
MATRIX = REPO_ROOT / "home/common/agent-skills/model-matrix.json"

_spec = importlib.util.spec_from_file_location("agent_model_drift", SCRIPT)
agent_model_drift = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(agent_model_drift)


def digest(value):
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=True)
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


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
    routing = routing_coverage or coverage()
    return {
        "schema_version": 1,
        "producer": {"name": "agent-costs", "version": 1,
                     "harness_versions": harness or {"claude": ["2.1.0"]}},
        "event_window": {"start": start, "end": end},
        "source_coverage": {
            "routing": copy.deepcopy(routing),
            "scheduling": {name: copy.deepcopy(metric["coverage"])
                           for name, metric in metrics.items()},
        },
        "runs": [{"run_id": "claude:repo:98",
                  "routing": {"coverage": copy.deepcopy(routing),
                              "observations": observations or []},
                  "scheduling": metrics}],
    }


def record_value(**telemetry_overrides):
    body = {
        "schema_version": 1, "kind": "agent-cost-record",
        "window": {"days": 1, "cutoff_epoch": 1,
                   "file_mtime_selection": True,
                   "whole_selected_file_usage": True,
                   "strata": ["claude"], "sources": {"claude": "/redacted"}},
        "strata": {}, "fleet": {"informative": True, "totals": {}},
        "notes": "comparative telemetry",
        "execution_telemetry": telemetry(**telemetry_overrides),
    }
    return dict(body, record_id=digest(body), generated_at="2026-09-20T11:01:00Z")


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
        "dispatch_hosts": {site["id"]: "claude"
                           for site in matrix["dispatch_sites"]},
        "catalog": {"claude": {
            "models": {tier: {"allowed": [f"claude-{tier}-5-20260901"],
                              "prohibited": []} for tier in models},
            "efforts": {tier: {"allowed": [tier], "prohibited": []}
                        for tier in efforts},
        }},
        "escalation_reason_codes": ["capacity", "source-unavailable"],
    }
    body.update(updates)
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
        record_path = self.write("record.json", record or record_value())
        baseline_path = self.write(
            "baseline.json", baseline or baseline_value(self.matrix, self.matrix_digest))
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = agent_model_drift.main([
                "--record", str(record_path), "--baseline", str(baseline_path),
                "--matrix-root", str(self.matrix_root), "--now", now])
        return code, stdout.getvalue(), stderr.getvalue()


class BaselineLifecycleTest(DriftCliCase):
    def test_fresh_matching_zero_event_cohort_is_conforming_and_deterministic(self):
        first = self.run()
        second = self.run()
        self.assertEqual(first, second)
        code, out, err = first
        self.assertEqual((code, err), (0, ""))
        report = json.loads(out)
        self.assertEqual(report["schema_version"], 1)
        self.assertEqual(report["kind"], "agent-model-drift-report")
        self.assertEqual(report["evaluated_at"], "2026-09-20T12:00:00Z")
        self.assertEqual(report["state"], "conforming")
        self.assertEqual(report["routing"], {
            "state": "conforming", "eligible_events": 0,
            "evaluated_events": 0, "findings": []})
        self.assertEqual(report["inputs"], {
            "record": record_value()["record_id"],
            "matrix": self.matrix_digest,
            "baseline": baseline_value(self.matrix, self.matrix_digest)["baseline_id"],
        })

    def test_lifecycle_and_identity_gaps_are_inconclusive(self):
        cases = {
            "unbounded": (record_value(start=None, end=None), None,
                          "WINDOW_UNBOUNDED"),
            "future": (None, baseline_value(
                self.matrix, self.matrix_digest,
                captured_at="2026-09-20T13:00:00Z"), "BASELINE_FUTURE"),
            "stale": (None, baseline_value(
                self.matrix, self.matrix_digest,
                valid_before="2026-09-20T12:00:00Z"), "BASELINE_STALE"),
            "outside": (record_value(start="2026-09-19T23:00:00Z"), None,
                        "WINDOW_OUTSIDE_BASELINE"),
            "identity-missing": (record_value(harness={"claude": None}), None,
                                 "IDENTITY_MISSING"),
        }
        for name, (record, baseline, code_name) in cases.items():
            with self.subTest(case=name):
                code, out, err = self.run(record=record, baseline=baseline)
                self.assertEqual((code, err), (3, ""))
                report = json.loads(out)
                self.assertEqual(report["state"], "inconclusive")
                self.assertIn(code_name,
                              [finding["code"] for finding in
                               report["routing"]["findings"]])

    def test_malformed_duplicate_unknown_and_digest_inputs_exit_two(self):
        valid_baseline = baseline_value(self.matrix, self.matrix_digest)
        bad_record = record_value()
        bad_record["extra"] = True
        for name, record, baseline in (
            ("unknown-record", bad_record, valid_baseline),
            ("bad-record-digest", dict(record_value(), record_id="sha256:bad"),
             valid_baseline),
            ("unknown-baseline", None, dict(valid_baseline, extra=True)),
            ("unsupported-version", None, dict(valid_baseline, schema_version=2)),
        ):
            with self.subTest(case=name):
                code, out, err = self.run(record=record, baseline=baseline)
                self.assertEqual(code, 2)
                self.assertEqual(out, "")
                self.assertNotEqual(err, "")

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


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the new suite and watch it fail**

Run: `python3 -m unittest -v tests/test_agent_model_drift.py`

Expected: ERROR at import — `scripts/agent-model-drift.py` does not exist.

- [ ] **Step 3: Implement strict loading and lifecycle evaluation**

Create the executable script with a `SourceFileLoader` for `<matrix-root>/home/common/agent-skills/scripts/agent-model-matrix.py`; register the loaded module in `sys.modules`, call `validate(matrix_root)`, reject any returned error, and only then call `load_matrix(matrix_root)`. Compute its digest locally from the validated object.

Implement one collecting schema validator per input. Every validator checks exact member sets before accessing values and reports a stable JSON-pointer-like location in `InputError`; `main` prints one concise diagnostic line without input content. Recompute both record and baseline digests. Validate sorted/unique catalog and identity arrays, exact dispatch coverage, exact declared tier coverage, disjoint classifications, and all time ordering.

Implement lifecycle/identity findings and deterministic report projection. A finding caused by global input validity has `run_id`, `dispatch`, and `role` null with count `1`. Sum eligible/paired counts from run routing coverage only after verifying top-level aggregate coverage agrees with that sum.

- [ ] **Step 4: Verify strict inputs and baseline lifecycle**

Run: `python3 -m unittest -v tests.test_agent_model_drift.BaselineLifecycleTest`

Expected: PASS; fresh zero-event input is byte-deterministic/conforming, valid lifecycle gaps exit `3` with reports, and malformed inputs exit `2` with empty stdout.

Run: `git diff --check "$DELIVERY_BASE" -- scripts/agent-model-drift.py tests/test_agent_model_drift.py`

Expected: exit `0`; no other file belongs to this task.

- [ ] **Step 5: Commit the strict consumer foundation**

```bash
git add scripts/agent-model-drift.py tests/test_agent_model_drift.py
git commit -S -m "feat(telemetry): validate drift baselines" \
  -m "Co-Authored-By: Codex <noreply@openai.com>"
```
