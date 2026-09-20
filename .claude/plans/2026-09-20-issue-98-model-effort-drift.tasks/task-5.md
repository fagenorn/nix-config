# Task 5: Project scheduling, wire repository gates, and prove the complete boundary

**Files:**
- Modify: `scripts/agent-model-drift.py`
- Modify: `tests/test_agent_model_drift.py`
- Modify: `justfile`

**Risk lane:** full — scheduling derivation, report contract completion, and repository test wiring.

**Interfaces:**
- Consumes: Task 2's eight per-run scheduling metrics and coverage/cohort contracts; Task 4's final routing state/report/exit behavior.
- Produces:
  - `def project_scheduling(runs: list[dict], event_window: dict) -> dict` — returns exactly `state`, `metrics`, `wait_token_share`, `occupancy`.
  - Report `metrics` has exactly the eight producer metric keys; each aggregate is exactly `value`, `coverage`, `cohort_digest`.
  - Just recipe `agent-model-drift *args` invoking `python3 scripts/agent-model-drift.py {{args}}`.
  - `tests/test_agent_model_drift.py` is listed in `agent-workflow-tests` immediately after `tests/test_agent_costs.py`; the existing matrix, resolver, release-contract, and gate-bundle entries remain.

**Invariants:**
- Scheduling aggregation uses only producer metric objects. It does not inspect accounting tokens, cache counters, prompts, source paths, current files, or the matrix (D5).
- An aggregate metric is numeric only when every contributing run has `full` coverage and a numeric value. Counts/sums add. Aggregate eligible/paired/reasons use Task 2's coverage merge. Aggregate cohort digest is `cohort_digest(sorted per-run cohort digests)` when every run supplies one; otherwise null.
- Scheduling state is `measured` only when all eight aggregate metrics are full; `partial` when at least one metric is full/partial and the set is not fully measured; otherwise `unmeasured`.
- `wait_token_share = wait_input_tokens / covered_input_tokens` only when both metrics are full, their per-run cohort digests agree pairwise, and the aggregate denominator is positive. `occupancy = claimed_slot_seconds / slot_capacity_seconds` only when both are full, each per-run cohort digest equals `canonical_digest(event_window)`, and the aggregate denominator is positive. Zero denominators yield null ratios, not zero or an error.
- A full token pair with different cohort digests, a full slot pair with a non-window digest, negative/non-integer values, or claimed slots above capacity is malformed input: exit `2`, diagnostic on stderr, empty stdout.
- Scheduling state/ratios never alter top-level or routing state, findings, or exit code (D5).
- The scheduling report contains no verdict or field named `waste`, `cheap`, `useful`, `savings`, `billing`, or `utilization`.
- Wiring is additive. Do not reorder/delete the existing `test_ship_release_contracts.py`, `test_agent_model_matrix.py`, `test_resolve_project.py`, `test_agent_costs.py`, or `test_agent_gate_bundle.py` runner entries (D8).

- [ ] **Step 1: Add failing scheduling/report and wiring tests**

Append these helpers/classes before the test module guard:

```python
def seal_record(value):
    body = copy.deepcopy(value)
    body.pop("record_id", None)
    body.pop("generated_at", None)
    return dict(body, record_id=digest(body),
                generated_at=value.get("generated_at", "2026-09-20T11:01:00Z"))


def full_metric(value, cohort):
    return {"value": value, "coverage": coverage(), "cohort_digest": cohort}


def scheduled_record(values):
    value = record_value()
    run = value["execution_telemetry"]["runs"][0]
    for name, metric in values.items():
        run["scheduling"][name] = metric
        value["execution_telemetry"]["source_coverage"]["scheduling"][name] = \
            copy.deepcopy(metric["coverage"])
    return seal_record(value)


class SchedulingProjectionTest(DriftCliCase):
    def test_absent_scheduling_is_unmeasured_and_does_not_change_routing(self):
        code, out, err = self.run()
        self.assertEqual((code, err), (0, ""))
        report = json.loads(out)
        self.assertEqual(report["state"], "conforming")
        self.assertEqual(report["routing"]["state"], "conforming")
        self.assertEqual(report["scheduling"]["state"], "unmeasured")
        self.assertIsNone(report["scheduling"]["wait_token_share"])
        self.assertIsNone(report["scheduling"]["occupancy"])

    def test_one_supported_metric_is_partial_with_measured_zero(self):
        value = scheduled_record({"spawn_attempts": full_metric(0, digest([]))})
        code, out, _ = self.run(record=value)
        self.assertEqual(code, 0)
        scheduling = json.loads(out)["scheduling"]
        self.assertEqual(scheduling["state"], "partial")
        self.assertEqual(scheduling["metrics"]["spawn_attempts"]["value"], 0)
        self.assertIsNone(scheduling["metrics"]["waits"]["value"])

    def test_fully_covered_zero_metrics_are_measured_without_fake_ratios(self):
        event_window = record_value()["execution_telemetry"]["event_window"]
        window_cohort = digest(event_window)
        response_cohort = digest([["response", "covered-zero"]])
        values = {}
        for name in ("spawn_attempts", "capacity_rejections", "waits", "follow_ups"):
            values[name] = full_metric(0, digest([]))
        for name in ("wait_input_tokens", "covered_input_tokens"):
            values[name] = full_metric(0, response_cohort)
        for name in ("slot_capacity_seconds", "claimed_slot_seconds"):
            values[name] = full_metric(0, window_cohort)
        code, out, _ = self.run(record=scheduled_record(values))
        self.assertEqual(code, 0)
        scheduling = json.loads(out)["scheduling"]
        self.assertEqual(scheduling["state"], "measured")
        self.assertIsNone(scheduling["wait_token_share"])
        self.assertIsNone(scheduling["occupancy"])
        self.assertTrue(all(metric["value"] == 0
                            for metric in scheduling["metrics"].values()))

    def test_compatible_numerators_and_denominators_derive_ratios(self):
        event_window = record_value()["execution_telemetry"]["event_window"]
        response_cohort = digest([["response", "r1"], ["response", "r2"]])
        values = {
            "wait_input_tokens": full_metric(20, response_cohort),
            "covered_input_tokens": full_metric(100, response_cohort),
            "slot_capacity_seconds": full_metric(60, digest(event_window)),
            "claimed_slot_seconds": full_metric(30, digest(event_window)),
        }
        code, out, _ = self.run(record=scheduled_record(values))
        self.assertEqual(code, 0)
        scheduling = json.loads(out)["scheduling"]
        self.assertEqual(scheduling["state"], "partial")
        self.assertEqual(scheduling["wait_token_share"], 0.2)
        self.assertEqual(scheduling["occupancy"], 0.5)

    def test_mismatched_cohorts_and_impossible_slots_are_input_errors(self):
        event_window = record_value()["execution_telemetry"]["event_window"]
        cases = {
            "token-cohort": {
                "wait_input_tokens": full_metric(1, digest(["wait"])),
                "covered_input_tokens": full_metric(2, digest(["covered"])),
            },
            "slot-cohort": {
                "slot_capacity_seconds": full_metric(10, digest(["wrong-window"])),
                "claimed_slot_seconds": full_metric(5, digest(event_window)),
            },
            "slot-order": {
                "slot_capacity_seconds": full_metric(5, digest(event_window)),
                "claimed_slot_seconds": full_metric(6, digest(event_window)),
            },
        }
        for name, values in cases.items():
            with self.subTest(case=name):
                code, out, err = self.run(record=scheduled_record(values))
                self.assertEqual(code, 2)
                self.assertEqual(out, "")
                self.assertNotEqual(err, "")

    def test_report_has_no_scheduling_conclusion_vocabulary(self):
        code, out, _ = self.run()
        self.assertEqual(code, 0)
        scheduling = json.dumps(json.loads(out)["scheduling"], sort_keys=True).lower()
        for forbidden in ("waste", "cheap", "useful", "savings", "billing", "utilization"):
            self.assertNotIn(forbidden, scheduling)


class RepositoryWiringTest(unittest.TestCase):
    def test_justfile_wires_new_suite_without_dropping_issue_100_boundaries(self):
        text = (REPO_ROOT / "justfile").read_text(encoding="utf-8")
        for required in (
            "home/common/agent-skills/tests/test_ship_release_contracts.py",
            "home/common/agent-skills/tests/test_agent_model_matrix.py",
            "home/common/agent-skills/tests/test_resolve_project.py",
            "tests/test_agent_costs.py",
            "tests/test_agent_model_drift.py",
            "tests/test_agent_gate_bundle.py",
            "agent-model-drift *args:",
            "python3 scripts/agent-model-drift.py {{args}}",
        ):
            self.assertIn(required, text)
```

- [ ] **Step 2: Run the scheduling and wiring tests and watch them fail**

Run: `python3 -m unittest -v tests.test_agent_model_drift.SchedulingProjectionTest tests.test_agent_model_drift.RepositoryWiringTest`

Expected: FAIL — scheduling is not aggregated/derived and the new suite/recipe are absent from `justfile`.

- [ ] **Step 3: Implement scheduling projection and additive wiring**

Validate every per-run metric and top-level aggregate coverage before projection. Validate token and slot pairs per run before summing. Aggregate only exact metric names from the closed tuple shared by the record validator; any unknown/missing metric is an input error. Compute ratios with ordinary division only after a positive denominator.

Add the Just test entry immediately after `tests/test_agent_costs.py` and add the recipe beside `agent-costs`. Make no other runner or recipe edit.

- [ ] **Step 4: Run scoped, full, build, and boundary verification**

Run: `python3 -m unittest -v tests/test_agent_costs.py tests/test_agent_model_drift.py home/common/agent-skills/tests/test_agent_model_matrix.py`

Expected: PASS; producer, consumer, and unchanged declaration tests are green.

Run: `just agent-workflow-tests`

Expected: exit `0`; the full durable workflow suite passes, including the new drift suite and existing matrix/resolver/release/gate suites.

Run: `just build`

Expected: exit `0`; Nix evaluation/build succeeds.

Run: `git diff --exit-code "$BASE"..HEAD -- home/common/agent-skills/model-matrix.json home/common/agent-skills/scripts/agent-model-matrix.py home/common/agent-skills/tests/test_agent_model_matrix.py`

Expected: exit `0`; issue 100's matrix/validator/test paths are unchanged from the original task base.

Run: `git diff --check "$DELIVERY_BASE" -- scripts/agent-model-drift.py tests/test_agent_model_drift.py justfile`

Expected: exit `0`; any whitespace error leaves the task incomplete.

- [ ] **Step 5: Commit the complete report boundary**

```bash
git add scripts/agent-model-drift.py tests/test_agent_model_drift.py justfile
git commit -S -m "feat(telemetry): report scheduling measurements" \
  -m "Co-Authored-By: Codex <noreply@openai.com>"
```
