# Task 2: Transport validators for the summary

**Files:**
- Modify: `home/common/agent-skills/scripts/artifact_budget.py`
- Modify: `home/common/agent-skills/tests/test_artifact_budget.py`
- Modify: `tests/test_review_gate.py`

**Interfaces:**
- Consumes: Task 1's summary shape (`agent_tools.review_gate.SUMMARY_KEYS`, `RECOMMENDATION_KEYS`) and `review-feasibility gate` output. `artifact_budget.py` stays a flat script and imports nothing from `agent_tools`; it restates the closed key sets.
- Produces, in `artifact_budget.py`:
  - `summary_fault(value: object, *, limits: ArtifactLimits, policy_sha256: str) -> str | None`: the one structural check both boundaries share (D5).
  - `validate_producer_report(value, notes_max_characters, *, review_limits: ArtifactLimits, policy_sha256: str) -> None`.
  - `validate_sdd_report(value, notes_max_characters, *, review_limits: ArtifactLimits, policy_sha256: str) -> None`.
  - `main` passes `review_limits=limits["review-package"]` and the loaded policy identity to those two validators only.

**Invariants:**
- `summary_fault` returns `None` exactly when: the keys are exactly the fourteen summary keys; `schema_version` is the int 1 (not a bool); `kind` is `review-feasibility-summary`; `state` is `complete` or `decompose_required`; `plan` is a relative POSIX path with no empty, `.` or `..` part; `base` and `head` are 40-hex; `completed_through` is a non-bool int `>= 0`; the four digests match `sha256:[0-9a-f]{64}`; `artifact_policy_sha256 == policy_sha256`; `metrics` pass `_valid_metrics`; `violations` equals the codes `_BOUNDS` gives for those metrics against `limits`, in checker order; `state` is `decompose_required` iff `violations` is non-empty; `recommended_boundary` is null when `complete`, otherwise null or exactly `{id, tasks, prerequisite_commit, metrics}` with `id` matching `[A-Za-z0-9][A-Za-z0-9_.-]*`, `tasks` sorted unique positive non-bool ints containing `completed_through + 1`, a 40-hex `prerequisite_commit`, and valid metrics with no violation. `packing_policy_sha256` is checked for shape only.
- Producer (`implementation-plan` only carries `projection`):
  - `complete`: exactly `state, artifact, projection, notes`; a within-budget artifact; projection valid, `state: complete`, `completed_through: 0`, `plan == artifact.path`.
  - `decompose_required`: either the existing over-budget artifact without `projection` (artifact overage), or a within-budget artifact plus a projection with `state: decompose_required`, `completed_through: 0` and `plan == artifact.path`.
  - `failed`: never `projection`. Every other kind refuses `projection`; every other existing row is unchanged.
- SDD: `decompose_required` has the eleven existing keys plus `stop`, with `review_state: unknown`, both verdicts and `verification_state` `not_run`, 40-hex `base_sha`/`head_sha`, `acceptance_state: not_applicable`, `detail_state: none`, `report_path: null`, and `stop` exactly one of `{"kind":"projected_overflow","projection":<summary, state decompose_required, base == base_sha, head == head_sha>}` or `{"kind":"actual_overage","artifact":<over-budget review-package artifact>}`. Other states refuse `stop`.
- Every refusal names its field (`projection.<key>`, `stop.<key>`) in the existing `artifact-budget: invalid report: <reason>` line, never the notes text.

- [ ] **Step 1: Write the failing tests**

In `home/common/agent-skills/tests/test_artifact_budget.py`, inside `ArtifactBudgetCliTest`, using its `run_validate`, `full`, `metrics` and `assert_refusal` helpers:

```python
    def summary(self, state="complete", **changes):
        identity = "sha256:" + hashlib.sha256(POLICY.read_bytes()).hexdigest()
        over = state == "decompose_required"
        value = {"schema_version": 1, "kind": "review-feasibility-summary", "state": state,
                 "plan": "artifacts/implementation-plan.json", "base": "a" * 40, "head": "b" * 40,
                 "completed_through": 0, "plan_package_sha256": "sha256:" + "1" * 64,
                 "forecast_sha256": "sha256:" + "2" * 64, "packing_policy_sha256": "sha256:" + "3" * 64,
                 "artifact_policy_sha256": identity,
                 "metrics": {"root_bytes": 17000 if over else 1000, "total_bytes": 19000 if over else 3000,
                             "file_count": 2, "largest_member_bytes": 2000},
                 "violations": ["root_bytes"] if over else [],
                 "recommended_boundary": {"id": "c1", "tasks": [1, 2], "prerequisite_commit": "c" * 40,
                     "metrics": {"root_bytes": 900, "total_bytes": 2900, "file_count": 2,
                                 "largest_member_bytes": 2000}} if over else None}
        value.update(changes)
        return value

    def plan_report(self, state, projection, over=False):
        value = {"state": state, "artifact": self.full("implementation-plan", over), "notes": "n"}
        if projection is not None:
            value["projection"] = projection
        return value

    def sdd_stop(self, stop, **changes):
        value = {"state": "decompose_required", "review_state": "unknown", "conformance_verdict": "not_run",
                 "correctness_verdict": "not_run", "verification_state": "not_run", "base_sha": "a" * 40,
                 "head_sha": "b" * 40, "acceptance_state": "not_applicable", "detail_state": "none",
                 "report_path": None, "notes": "projected overflow at bbbbbbb through 0", "stop": stop}
        value.update(changes)
        return value

    def test_projection_rows_at_the_producer_boundary(self):
        over = self.summary("decompose_required")
        rows = [
            (self.plan_report("complete", self.summary()), True),
            (self.plan_report("decompose_required", over), True),
            (self.plan_report("decompose_required", {**over, "recommended_boundary": None}), True),  # D18
            (self.plan_report("decompose_required", None, over=True), True),
            (self.plan_report("complete", None), False),
            (self.plan_report("complete", over), False),
            (self.plan_report("decompose_required", self.summary()), False),
            (self.plan_report("decompose_required", over, over=True), False),
            (self.plan_report("complete", self.summary(completed_through=1)), False),
            (self.plan_report("complete", self.summary(plan="other.md")), False),
            (self.plan_report("complete", self.summary(artifact_policy_sha256="sha256:" + "0" * 64)), False),
            (self.plan_report("complete", self.summary(violations=["root_bytes"])), False),
            (self.plan_report("decompose_required", {**over, "violations": []}), False),
            (self.plan_report("complete", {**self.summary(), "extra": 1}), False),
            (self.plan_report("complete", self.summary(schema_version=True)), False),
            ({"state": "failed", "artifact": None, "notes": "n", "projection": self.summary()}, False),
            ({"state": "complete", "artifact": self.full("design-spec"), "notes": "n",
              "projection": self.summary(plan="artifacts/design-spec.json")}, False),
        ]
        bad_recommendations = [{"tasks": [2]}, {"tasks": [1, 1]}, {"prerequisite_commit": "c" * 39},
                               {"metrics": over["metrics"]}, {"id": "../x"}]
        for change in bad_recommendations:
            rows.append((self.plan_report("decompose_required", {**over, "recommended_boundary":
                         {**over["recommended_boundary"], **change}}), False))
        for number, (payload, valid) in enumerate(rows):
            with self.subTest(number=number):
                result = self.run_validate("producer", payload, number % 2 == 0)
                self.assertEqual(result.returncode, 0 if valid else 2, result.stderr)
                if not valid:
                    self.assert_refusal(result, "invalid report")

    def test_decompose_required_rows_at_the_sdd_boundary(self):
        over = self.summary("decompose_required", head="b" * 40)
        artifact = self.full("review-package", True)
        rows = [
            (self.sdd_stop({"kind": "projected_overflow", "projection": over}), True),
            (self.sdd_stop({"kind": "projected_overflow", "projection": {**over, "recommended_boundary": None}}),
             True),                                                                     # D18
            (self.sdd_stop({"kind": "actual_overage", "artifact": artifact}), True),
            (self.sdd_stop({"kind": "projected_overflow", "projection": self.summary()}), False),
            (self.sdd_stop({"kind": "projected_overflow", "projection": {**over, "head": "d" * 40}}), False),
            (self.sdd_stop({"kind": "actual_overage", "artifact": self.full("review-package")}), False),
            (self.sdd_stop({"kind": "actual_overage", "artifact": self.full("design-spec", True)}), False),
            (self.sdd_stop({"kind": "other", "projection": over}), False),
            (self.sdd_stop({"kind": "projected_overflow", "projection": over}, review_state="clean"), False),
            (self.sdd_stop({"kind": "projected_overflow", "projection": over}, report_path="x"), False),
            (self.sdd_stop({"kind": "projected_overflow", "projection": over}, verification_state="passed"), False),
        ]
        failed = {"state": "failed", "review_state": "unknown", "conformance_verdict": "not_run",
                  "correctness_verdict": "not_run", "verification_state": "not_run", "base_sha": None,
                  "head_sha": None, "acceptance_state": "not_applicable", "detail_state": "none",
                  "report_path": None, "notes": "n"}
        rows += [(failed, True), ({**failed, "stop": {"kind": "actual_overage", "artifact": artifact}}, False)]
        for number, (payload, valid) in enumerate(rows):
            with self.subTest(number=number):
                result = self.run_validate("sdd", payload, number % 2 == 0)
                self.assertEqual(result.returncode, 0 if valid else 2, result.stderr)
```

In `tests/test_review_gate.py`, add to `GateTest` (the fixture's `PATH` already runs the source `artifact-budget`):

```python
    def test_every_gate_summary_validates_at_both_boundaries(self):
        for build in (lambda: None, self.bare_overflow, self.oversize):
            build()
            gated = self.gate(0)
            summary = json.loads(gated.stdout)
            checked = subprocess.run(['artifact-budget', 'check', '--kind', 'implementation-plan', '--root',
                                      self.plan_path(), '--format', 'json'], env=self.env, capture_output=True)
            artifact = {'kind': 'implementation-plan', 'path': 'all.md', 'budget_status': 'within_budget',
                        'metrics': json.loads(checked.stdout)['metrics']}
            state = summary['state']
            producer = {'state': state, 'artifact': artifact, 'projection': summary, 'notes': 'n'}
            reports = [('producer', producer)]
            if state == 'decompose_required':
                reports.append(('sdd', {'state': state, 'review_state': 'unknown', 'conformance_verdict': 'not_run',
                    'correctness_verdict': 'not_run', 'verification_state': 'not_run', 'base_sha': summary['base'],
                    'head_sha': summary['head'], 'acceptance_state': 'not_applicable', 'detail_state': 'none',
                    'report_path': None, 'notes': 'n', 'stop': {'kind': 'projected_overflow', 'projection': summary}}))
            for boundary, report in reports:
                raw = json.dumps(report, sort_keys=True, separators=(',', ':')).encode() + b'\n'
                done = subprocess.run(['artifact-budget', 'validate-report', '--boundary', boundary, '--input', '-'],
                                      input=raw, env=self.env, capture_output=True)
                self.assertEqual((done.returncode, done.stdout), (0, raw), done.stderr)
```

- [ ] **Step 2: Run and watch it fail**

Run: `timeout 900 python3 -m unittest home/common/agent-skills/tests/test_artifact_budget.py 2>&1 | tail -3`
Expected: FAIL — the valid projection rows are refused (`projection` is an unknown member).

- [ ] **Step 3: Implement**

- Add `summary_fault` beside `_artifact_fault`, with the fourteen keys and the four recommendation keys as module constants. Derive `violations` from `_BOUNDS` and the `ArtifactLimits` passed in, never from a second table.
- `validate_producer_report`: when `"projection" in value`, require `state` in `{"complete", "decompose_required"}` and an `implementation-plan` artifact, check `summary_fault`, then the state, ordinal and `plan == artifact.path` bindings above; the artifact is checked as within budget in both projection rows. Without `projection`, an `implementation-plan` `complete` is refused (`projection is required for implementation-plan`); every other row keeps its current rule and message.
- `validate_sdd_report`: branch on `state == "decompose_required"` before `_require_members`, so that state requires `stop` and every other state keeps the existing eleven-key check.
- Producer fixtures elsewhere in the suites that send an `implementation-plan` `complete` report through `--boundary producer` gain a valid `projection`; find them with `rg -l '"implementation-plan"' home/common/agent-skills/tests tests`.

- [ ] **Step 4: Verify**

Run: `timeout 900 python3 -m unittest home/common/agent-skills/tests/test_artifact_budget.py 2>&1 | tail -3` — Expected: `OK`.
Run: `PYTHONPATH=python timeout 900 python3 -m unittest tests/test_review_gate.py 2>&1 | tail -3` — Expected: `OK`.
Run: `timeout 3600 just build 2>&1 | tail -2` — Expected: success.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/scripts/artifact_budget.py home/common/agent-skills/tests/test_artifact_budget.py tests/test_review_gate.py
git commit -m "feat(budget): validate review-feasibility summaries in reports"
```

Decisions: D3, D5, D18.

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[],"commit_subject_bytes":[64,64,64,64],"id":2,"records":[{"bounds":[{"added_lines":160,"boundary":"all","deleted_lines":25,"record_bytes":16384,"support":{"covers":["r2a"],"kind":"authored-cumulative/v1"}},{"added_lines":160,"boundary":"c1","deleted_lines":25,"record_bytes":16384,"support":{"covers":["r2a"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r2a","last_task":2,"owner":2,"path":"home/common/agent-skills/scripts/artifact_budget.py"},{"bounds":[{"added_lines":200,"boundary":"all","deleted_lines":10,"record_bytes":14336,"support":{"covers":["r2b"],"kind":"authored-cumulative/v1"}},{"added_lines":200,"boundary":"c1","deleted_lines":10,"record_bytes":14336,"support":{"covers":["r2b"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r2b","last_task":2,"owner":2,"path":"home/common/agent-skills/tests/test_artifact_budget.py"},{"bounds":[{"added_lines":320,"boundary":"all","deleted_lines":0,"record_bytes":18432,"support":{"covers":["r1c","r2c"],"kind":"authored-cumulative/v1"}},{"added_lines":320,"boundary":"c1","deleted_lines":0,"record_bytes":18432,"support":{"covers":["r1c","r2c"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"r2c","last_task":2,"owner":2,"path":"tests/test_review_gate.py"}]}}
```
