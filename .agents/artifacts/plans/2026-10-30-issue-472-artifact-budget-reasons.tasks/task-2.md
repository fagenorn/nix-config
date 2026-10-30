# Task 2: Validator reasons that name the member or bound

**Files:**
- Modify: `home/common/agent-skills/scripts/artifact_budget.py`
- Test: `home/common/agent-skills/tests/test_artifact_budget.py`

**Interfaces:**
- Consumes, from Task 1: `_refuse(label, exc) -> int`, which writes whatever an `ArtifactBudgetError` says onto the refusal line, and the test method `assert_refusal(self, result, label: str) -> str`, which returns the reason.
- Produces, all in `artifact_budget.py`:
  - `_members_fault(value: object, keys: set[str], subject: str) -> str | None`
  - `_require_members(value: object, keys: set[str], subject: str) -> None`
  - `_require_notes(value: object, maximum: int) -> None`
  - `_artifact_fault(value: object, *, kinds: Sequence[str], over: bool, root_only: bool = False) -> str | None`
  - `_validate_finding(value: object, subject: str) -> None`, which gains `subject`.
  - `_detail_fields(value: Mapping[str, object], *, allow_unpublished: bool) -> bool`, which loses `notes_max`.
  - `_v2_cause(model: object, exc: BaseException) -> str`
  - `_valid_artifact` keeps its signature. `_notes` is deleted.

**Invariants:**
- Every validator accepts and refuses exactly the inputs it does at base. The existing matrix and pairing tests stay green without edits.
- Each legacy report validator (producer, SDD, ship-handoff, ship-summary, ledger-result) checks its key set first, then `notes`, then its matrix. With several faults, the reason belongs to the first check that fails in that order (D2, D3).
- Input-supplied member names are sorted and quoted with `json.dumps`. A reason echoes no input value. The one exception is the producer's `state`, and only after it has matched a closed-set state.
- A `state`, `kind` or other input value that cannot be hashed is refused with a reason, never with a `TypeError`. Membership tests on input values use tuples, or an `isinstance(..., str)` guard before a dict lookup.
- The SDD, legacy ship-handoff, ship-summary and ledger-result matrix reasons keep today's text (D3). A v2 reason is `<boundary>: <cause>` (D4, D12).

- [ ] **Step 1: Write the failing tests**

Add `import types` to the module imports. Add these tests after `test_every_producer_report_matrix_row`:

```python
    def test_a_producer_refusal_names_its_member_or_bound(self):
        """Issue 472 AC1, D2, D3: the notes bound and the key set are named; the notes text never is."""
        bound = json.loads(POLICY.read_text(encoding="utf-8"))["phase_reports"]["notes_max_characters"]
        marker = "secret-notes-text"
        notes = marker + "n" * (bound + 1 - len(marker))
        for use_stdin in (True, False):
            with self.subTest(use_stdin=use_stdin):
                result = self.run_validate(
                    "producer", {"state": "failed", "artifact": None, "notes": notes}, use_stdin)
                reason = self.assert_refusal(result, "invalid report")
                self.assertIn("notes", reason)
                self.assertIn(str(bound), reason)
                self.assertIn(str(bound + 1), reason)
                self.assertNotIn(marker, reason)
        keys = {"state": "failed", "artifact": None, "decisions": []}
        reason = self.assert_refusal(self.run_validate("producer", keys, True), "invalid report")
        self.assertIn('"decisions"', reason)
        self.assertIn('"notes"', reason)

    def test_a_producer_refusal_names_the_failing_artifact_member(self):
        """Issue 472 D3: the producer boundary names state, or the artifact member its state breaks."""
        over = self.full("design-spec", True)
        rows = (
            ({"state": "done", "artifact": None}, ("state", "decompose_required")),
            ({"state": [], "artifact": None}, ("state", "decompose_required")),
            ({"state": "stopped", "artifact": over}, ("artifact.kind", "handoff")),
            ({"state": "decompose_required", "artifact": self.full("handoff", True)},
             ("artifact.kind",)),
            ({"state": "complete", "artifact": self.full("handoff", True)},
             ("artifact", '"violations"')),
            ({"state": "complete", "artifact": {**self.full("handoff"), "path": ""}},
             ("artifact.path",)),
            ({"state": "complete", "artifact": {**self.full("handoff"),
                                                "metrics": {**self.metrics(), "file_count": 0}}},
             ("artifact.metrics",)),
            ({"state": "decompose_required", "artifact": {**over, "budget_status": "within_budget"}},
             ("artifact.budget_status",)),
            ({"state": "decompose_required",
              "artifact": {**over, "violations": ["aggregate_bytes", "root_bytes"]}},
             ("artifact.violations",)),
            ({"state": "failed", "artifact": {"kind": "handoff", "path": "h.md",
                                              "metrics": self.metrics()}},
             ("artifact", '"metrics"')),
            ({"state": "failed", "artifact": "h.md"}, ("artifact",)),
        )
        for number, (fields, tokens) in enumerate(rows):
            with self.subTest(row=number):
                result = self.run_validate("producer", {**fields, "notes": "ok"}, number % 2 == 0)
                reason = self.assert_refusal(result, "invalid report")
                for token in tokens:
                    self.assertIn(token, reason)

    def test_every_legacy_boundary_names_its_members_and_notes_bound(self):
        """Issue 472 D3, D12: each legacy validator checks its key set, then notes, before its matrix."""
        bound = json.loads(POLICY.read_text(encoding="utf-8"))["phase_reports"]["notes_max_characters"]
        long_notes = "n" * (bound + 1)
        payloads = {
            "sdd": self.make_sdd("complete", "clean", "clean", "clean", "passed",
                                 "a" * 40, "b" * 40, "none", None),
            "ship-handoff": {**self.lifecycle(), "state": "complete",
                             "spec_artifact": self.full("design-spec"),
                             "plan_artifact": self.full("implementation-plan"),
                             "head_sha": "b" * 40, "review_state": "clean",
                             "report_path": None, "notes": "ok"},
            "ship-summary": {"issue": 49, "state": "stopped", "pr_url": None, "merge_sha": None,
                             "issue_closed": False, "discussion_items": [],
                             "detail_state": "none", "report_path": None, "notes": "ok"},
        }
        for boundary, payload in payloads.items():
            with self.subTest(boundary=boundary):
                self.assertEqual(self.run_validate(boundary, payload, True).returncode, 0)
                reason = self.assert_refusal(
                    self.run_validate(boundary, {**payload, "notes": long_notes}, True),
                    "invalid report")
                self.assertIn("notes", reason)
                self.assertIn(str(bound), reason)
                without = {key: value for key, value in payload.items() if key != "report_path"}
                reason = self.assert_refusal(self.run_validate(boundary, without, False),
                                             "invalid report")
                self.assertIn('"report_path"', reason)
        # Only a whole workflow response reaches this row at the CLI (issue 472 D12).
        ledger = {"issue": 49, "state": "merged", "pr_url": "https://example.test/pr/1",
                  "merge_sha": "c" * 40, "issue_closed": False, "discussion_items": [],
                  "detail_state": "none", "report_path": None, "notes": long_notes}
        with self.assertRaises(artifact_budget.ArtifactBudgetError) as caught:
            artifact_budget.validate_ledger_result(ledger, bound)
        self.assertIn("notes", str(caught.exception))
        self.assertIn(str(bound), str(caught.exception))

    def test_a_detail_refusal_names_the_failing_finding_member(self):
        """Issue 472 AC2, D3: a detail refusal names the finding by index and its member."""
        finding = {"axis": "ship", "severity": "Minor", "status": "minor",
                   "text": "kept", "ruling": None}
        parked = {**finding, "status": "parked"}
        cases = (
            ({"interface_version": 1, "findings": [parked]}, ("findings[0]", "ruling")),
            ({"interface_version": 1, "findings": [finding, parked]}, ("findings[1]", "ruling")),
            ({"interface_version": 1, "findings": [{**finding, "axis": "style"}]},
             ("findings[0].axis",)),
            ({"interface_version": 1,
              "findings": [{key: value for key, value in finding.items() if key != "text"}]},
             ("findings[0]", '"text"')),
            ({"interface_version": 1, "items": []}, ('"findings"', '"items"')),
        )
        for payload, tokens in cases:
            with self.subTest(tokens=tokens):
                result = subprocess.run(
                    [sys.executable, str(SCRIPT), "validate-detail-input", "--input", "-",
                     "--policy", str(POLICY)],
                    input=json.dumps(payload).encode("utf-8"), capture_output=True, check=False)
                reason = self.assert_refusal(result, "invalid detail input")
                for token in tokens:
                    self.assertIn(token, reason)
                self.assertNotIn("style", reason)

    def test_v2_refusals_name_the_boundary_and_its_cause(self):
        """Issue 472 D4: a v2 refusal names its boundary, then the cause it wraps."""
        model = artifact_budget._delivery_model()
        contract, delivery = contract_and_delivery(model)
        handoff = ship_handoff(model, contract, delivery)
        unpaired = self.run_validate("ship-handoff", {**handoff, "acceptance_state": "unmet"}, True)
        reason = self.assert_refusal(unpaired, "invalid report")
        self.assertTrue(reason.startswith("ship-handoff: "), reason)
        self.assertIn("acceptance_state", reason)
        missing_scope = deepcopy(workflow_responses(model)["owner"])
        missing_scope.pop("requested_scope")
        refused = self.run_validate("workflow-response", missing_scope, True)
        reason = self.assert_refusal(refused, "invalid report")
        self.assertTrue(reason.startswith("workflow-response: "), reason)

    def test_a_foreign_v2_cause_is_named_by_its_class(self):
        """Issue 472 D12: a v2 reason carries only the helper's or the model's own message."""
        class ModelError(ValueError):
            pass

        def model_raising(error):
            def validate_delivery_object(value, **_):
                raise error
            return types.SimpleNamespace(DeliveryModelError=ModelError,
                                         validate_delivery_object=validate_delivery_object)

        cases = (
            (ModelError("invalid checkpoint"), "ship-checkpoint: invalid checkpoint"),
            (ValueError("invalid literal for int() with base 10: 'secret'"),
             "ship-checkpoint: ValueError"),
            (KeyError("secret"), "ship-checkpoint: KeyError"),
        )
        for error, expected in cases:
            with self.subTest(error=type(error).__name__), mock.patch.object(
                    artifact_budget, "_delivery_model", return_value=model_raising(error)):
                with self.assertRaises(artifact_budget.ArtifactBudgetError) as caught:
                    artifact_budget.validate_delivery_model_report({}, 500, "ship-checkpoint")
                self.assertEqual(str(caught.exception), expected)
        with mock.patch.object(artifact_budget, "_delivery_model",
                               return_value=model_raising(KeyError("secret"))):
            with self.assertRaises(artifact_budget.ArtifactBudgetError) as caught:
                artifact_budget.validate_workflow_response_report({}, 500)
        self.assertEqual(str(caught.exception), "workflow-response: KeyError")
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: the Unit run on `home/common/agent-skills/tests/test_artifact_budget.py` with `-k names_its_member_or_bound -k failing_artifact_member -k members_and_notes_bound -k failing_finding_member -k boundary_and_its_cause -k named_by_its_class`.
Expected: FAIL in all 6 tests. Each fails on a missing token, for example `AssertionError: 'notes' not found in 'invalid producer report'`, or because a v2 reason does not start with the boundary: today the reason is `invalid ship-handoff`.

- [ ] **Step 3: Write the minimal implementation**

All edits are in `artifact_budget.py`. The helpers carry the reason format (D2), so write them as given:

```python
def _quoted(names: set[str]) -> str:
    return ", ".join(json.dumps(name) for name in sorted(names))


def _members_fault(value: object, keys: set[str], subject: str) -> str | None:
    """Why `value` is not an object with exactly `keys`, or None (issue 472 D2, D3)."""
    if not isinstance(value, dict):
        return f"{subject} must be a JSON object"
    missing, unexpected = keys - set(value), set(value) - keys
    parts = ([f"missing {_quoted(missing)}"] if missing else []) + (
        [f"unexpected {_quoted(unexpected)}"] if unexpected else [])
    return f"{subject} members: {'; '.join(parts)}" if parts else None


def _require_members(value: object, keys: set[str], subject: str) -> None:
    fault = _members_fault(value, keys, subject)
    if fault is not None:
        raise ArtifactBudgetError(fault)


def _require_notes(value: object, maximum: int) -> None:
    """Refuse notes that are not a string of at most `maximum` characters (issue 472 D3)."""
    if not isinstance(value, str):
        raise ArtifactBudgetError("notes must be a string")
    if len(value) > maximum:
        raise ArtifactBudgetError(f"notes has {len(value)} characters; the bound is {maximum}")
```

1. **`_artifact_fault`** replaces the body of `_valid_artifact`. It returns the first fault in this order, or None:
   1. the key set, through `_members_fault(value, expected, "artifact")`. `expected` is `{"kind", "path"}` when `root_only`. Otherwise it is `{"kind", "path", "metrics", "budget_status"}`, plus `"violations"` when `over`.
   2. `value["kind"] not in kinds` gives `f"artifact.kind must be {' or '.join(kinds)}"`. `kinds` is a tuple.
   3. `not _valid_path(value["path"])` gives `"artifact.path must be a non-empty string without NUL"`. With `root_only`, the function returns None here.
   4. `not _valid_metrics(value["metrics"])` gives `"artifact.metrics must be four non-negative integer counts of one measurement"`.
   5. A `budget_status` other than `over_budget` when `over` (`within_budget` otherwise) gives `f"artifact.budget_status must be {status}"`.
   6. When `over`, today's `violations` test, kept in its order so a list with an unhashable element fails the equality before `set()` runs, gives `"artifact.violations must be distinct violation codes in checker order"`.

   `_valid_artifact(value, *, kind=None, over=None, root_only=False)` becomes `_artifact_fault(value, kinds=KINDS if kind is None else (kind,), over=over is True, root_only=root_only) is None`.
2. **The producer.** Add a module constant above `validate_producer_report`:

```python
# Each producer state's allowed artifact kinds and budget side; `failed` takes a
# root-only artifact or null (issue 472 D3).
_PRODUCER_ARTIFACTS = {
    "complete": (KINDS, False),
    "decompose_required": (("design-spec", "implementation-plan", "review-package"), True),
    "stopped": (("handoff",), True),
}
```

   `validate_producer_report` runs `_require_members(value, {"state", "artifact", "notes"}, "producer report")` and then `_require_notes(value["notes"], notes_max_characters)`. Next it checks `state` and its artifact:
   - `state == "failed"`: the fault is None for a null artifact. Otherwise it is `_artifact_fault(artifact, kinds=KINDS, over=False, root_only=True)`.
   - `isinstance(state, str) and state in _PRODUCER_ARTIFACTS`: the fault is `_artifact_fault(artifact, kinds=kinds, over=over)` from that row.
   - Otherwise it raises `ArtifactBudgetError("state must be complete, decompose_required, stopped or failed")`.

   A fault raises `ArtifactBudgetError(f"{fault} for state {state}")`.
3. **SDD, ship handoff, ship summary, ledger result.** Each replaces its key-set test with `_require_members(value, keys, "<subject>")`, using the subjects `"SDD report"`, `"ship handoff"`, `"ship summary"` and `"ledger result"`. It then runs `_require_notes(value["notes"], notes_max_characters)`. Remove the old key-set and notes terms from each `if`, and keep every other term and every existing reason. In `validate_ledger_result`, this applies to the merged, not-closed branch, which drops `_notes` from its conjunction. `_detail_fields` drops its notes check and its `notes_max` parameter. Its docstring says: "Callers check `notes` with `_require_notes` first, so `notes` is a string here." Delete `_notes`.
4. **Detail input.**
   - `validate_detail_input` runs `_require_members(value, {"interface_version", "findings"}, "detail input")`.
   - It then raises `"interface_version must be 1"` and `"findings must be a non-empty list"` where it raises its version and findings reasons today.
   - It calls `_validate_finding(finding, f"findings[{index}]")` for each `index, finding in enumerate(findings)`.
   - The review-package manifest's JSONL loop in `_validate_manifest` is the other caller (Phase-5 B1). It iterates `for line_number, line in enumerate(lines, 1):` and calls `_validate_finding(finding, f"shard-{number:03d}.jsonl line {line_number}")`, reusing the loop's existing shard `number`, so a delivery-detail package that validates at base still validates. The existing delivery-detail and review-package success tests stay green without edits.
   - `_validate_finding` starts with `_require_members(value, keys, subject)`. It keeps today's checks in today's order, but each enum membership test is against a tuple literal, not a set, so an unhashable value such as `"axis": []` is refused with the reason below instead of a `TypeError` (Phase-5 S1). It raises:
     - `f"{subject}.axis must be conformance, correctness or ship"`
     - `f"{subject}.severity must be Critical, Important, Minor, Blocking, Should-fix or Discussion"`
     - `f"{subject}.status must be parked, residual, discussion or minor"`
     - `f"{subject}.text must be a non-empty string"`
     - `f"{subject}.ruling must be null or a non-empty string"`
     - `f"{subject}.ruling is required for a parked finding"`
5. **v2 causes (D4, D12).** Add:

```python
def _v2_cause(model: object, exc: BaseException) -> str:
    """The message of an error this helper or the delivery model raised, else the class name (issue 472 D12)."""
    if isinstance(exc, (ArtifactBudgetError, model.DeliveryModelError)):
        return str(exc)
    return type(exc).__name__
```

   `validate_workflow_response_report` raises `ArtifactBudgetError(f"workflow-response: {_v2_cause(model, exc)}") from exc`. `validate_delivery_model_report` raises `ArtifactBudgetError(f"{boundary}: {_v2_cause(model, exc)}") from exc`.

- [ ] **Step 4: Verify**

Run: the Unit run on `home/common/agent-skills/tests/test_artifact_budget.py`.
Expected: PASS, 53 tests, `OK`. The matrix and pairing tests pass without edits.

Run: `bash -c 'if rg -n "def _notes\(" home/common/agent-skills/scripts/artifact_budget.py; then exit 1; fi'`
Expected: exit 0 with no output. At the start of this task it prints the `_notes` definition and exits 1.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/scripts/artifact_budget.py home/common/agent-skills/tests/test_artifact_budget.py
git commit -m "feat(artifact-budget): name the failing member or bound in validator refusals (issue 472)"
```
