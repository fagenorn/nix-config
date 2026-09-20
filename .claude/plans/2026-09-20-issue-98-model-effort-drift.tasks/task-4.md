# Task 4: Evaluate declarations, concrete execution, and escalation lineage

**Files:**
- Modify: `scripts/agent-model-drift.py`
- Modify: `tests/test_agent_model_drift.py`

**Risk lane:** full — routing conformance/drift decisions and escalation semantics.

**Interfaces:**
- Consumes: Task 3's strict decoded record/matrix/baseline, pure `evaluate`, report/finding schema, lifecycle and identity findings.
- Produces:
  - `def evaluate_observation(observation: dict, run_id: str, matrix: dict, baseline: dict, baseline_usable: bool) -> list[dict]` — returns sorted findings for one aggregate observation; never mutates inputs.
  - `def classify_concrete(catalog: dict, host: str, kind: str, tier: str, concrete: str) -> str` — returns exactly `allowed | prohibited | unclassified`; raises `AssertionError` if one concrete value is both allowed and prohibited.
  - `def declaration_for(observation: dict, matrix: dict) -> tuple[dict | None, list[dict]]` — resolves an authoritative carried dispatch first, otherwise an unambiguous canonical role; it returns findings rather than guessing.
  - `def validate_escalation(observation: dict, matrix: dict, baseline: dict) -> bool` — true only for a declared target dispatch, a different declared source dispatch, and an allowed reason code.
  - Task 3's `evaluate` now folds every run/observation, aggregates identical findings by `(code, run_id, dispatch, role)`, and applies drift precedence.

**Invariants:**
- Requested `role`, `model`, and `effort` are checked against the validated matrix before any concrete observed value is classified. A carried dispatch must match its row exactly (D6).
- A missing/unknown/ambiguous role yields `ROLE_AMBIGUOUS`. Reviewer-lite and every non-null escalation require a carried dispatch; absent dispatch yields `DISPATCH_REQUIRED` and cannot conform (D6).
- For a role-only declaration, the permitted host is derivable only when every matrix dispatch for that role has one identical `dispatch_hosts` value. Otherwise dispatch is required. No host alias is normalized.
- Concrete host unequal to the permitted host yields `OBSERVED_HOST_PROHIBITED`. A concrete model/effort in the requested tier's `prohibited` list yields its drift code; absent from both lists yields its unclassified inconclusive code. Null model/effort yields the corresponding missing code (D3, D4).
- `requested` or `configured` equality never fills a null observed field. Configuration-only Codex evidence remains inconclusive even when its strings match the declaration (D2).
- Any request/matrix mismatch, prohibited concrete host/model/effort, or invalid escalation makes routing `drifted` even when another observation or global check is inconclusive. Baseline/catalog-dependent drift is evaluated only when baseline identity/lifecycle is usable; request-vs-current-matrix drift remains authoritative without it (D4).
- Valid escalation changes the declaration to the target dispatch already carried in `declaration.dispatch_id`; it never blesses a model substitution on the source request. `source_dispatch_id == target`, unknown source/target, absent reason, or a reason outside `escalation_reason_codes` yields `ESCALATION_INVALID` (D6).
- The strict observation decoder accepts `escalation: null` or the exact two-member object from Task 1; either member may be null so missing lineage reaches `ESCALATION_INVALID`. Other types or extra members remain malformed-input exit `2`.
- Findings multiply by observation `count`, are aggregated and sorted, and never include request/result/child/source identities.

- [ ] **Step 1: Add the failing routing decision table**

Append these helpers and tests before the module's `if __name__ == "__main__"` guard:

```python
def seal_baseline(value):
    body = copy.deepcopy(value)
    body.pop("baseline_id", None)
    return dict(body, baseline_id=digest(body))


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

    def test_request_declaration_mismatch_is_drift(self):
        item = observation(self.matrix)
        item["requested"]["model"] = "sonnet"
        code, out, _ = self.run_observations([item])
        self.assertEqual(code, 3)
        report = json.loads(out)
        self.assertEqual(report["state"], "drifted")
        self.assertIn("REQUEST_DECLARATION_MISMATCH", self.finding_codes(report))

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
        self.assertEqual(json.loads(out)["state"], "conforming")

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
```

- [ ] **Step 2: Run the routing table and watch it fail**

Run: `python3 -m unittest -v tests.test_agent_model_drift.RoutingEvaluationTest`

Expected: FAIL — Task 3 does not classify per-observation request, catalog, host, or escalation evidence.

- [ ] **Step 3: Implement the pure routing evaluator**

Index the validated matrix once inside `evaluate`: roles by name, dispatches by id, and dispatch hosts by role. Validate each observation against exact closed member sets before evaluation. Resolve the current declaration, then request correctness, escalation validity, observed host, model, and effort in that order; collect all independent findings rather than returning after the first.

For baseline-dependent classifications, use the requested matrix tier and the literal observed host. `classify_concrete` consults only that host/tier pair. It does not search other hosts or tiers and never compares names lexically. A concrete value missing from both arrays is unclassified.

Count `evaluated_events` only for observations whose exact execution host/model/effort reach an allowed/prohibited classification; missing/unclassified evidence remains eligible but unevaluated. Set the report routing state from all findings with the design precedence, and mirror it in top-level `state`.

- [ ] **Step 4: Verify routing and retained lifecycle behavior**

Run: `python3 -m unittest -v tests/test_agent_model_drift.py`

Expected: PASS; request, host, model, effort, escalation, coverage, sorting, lifecycle, strict-input, exit, and deterministic-output tests are green.

Run: `git diff --check "$DELIVERY_BASE" -- scripts/agent-model-drift.py tests/test_agent_model_drift.py`

Expected: exit `0`; no producer or matrix file changes are present in this task.

- [ ] **Step 5: Commit the routing evaluator**

```bash
git add scripts/agent-model-drift.py tests/test_agent_model_drift.py
git commit -S -m "feat(telemetry): evaluate routing drift" \
  -m "Co-Authored-By: Codex <noreply@openai.com>"
```
