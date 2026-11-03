# Task 3: Ship-summary and SDD detail refusals name the member and rule

**Files:**
- Modify: `home/common/agent-skills/scripts/artifact_budget.py` (`_detail_fields` becomes `_detail_fault`; `validate_sdd_report`; `validate_ship_summary_report`)
- Test: `home/common/agent-skills/tests/test_artifact_budget.py` (two new methods on `ArtifactBudgetCliTest`)

**Interfaces:**
- Consumes: `ArtifactBudgetCliTest.run_validate(boundary, payload, use_stdin)`, `assert_refusal(result, label) -> str` (exit 2, empty stdout, one line `artifact-budget: <label>: <reason>`, returns `<reason>`) and `make_sdd(...)`; `POLICY`; `artifact_budget._delivery_model()`; and `contract_and_delivery` and `custody` from `._delivery_model_fixtures`, all already imported in that test module. The v2 `ship-summary` boundary wraps the v1 rule as `ship-summary: <v1 reason>` through `validate_delivery_model_report` and `_v2_cause`, which do not change.
- Produces: `_detail_fault(value: Mapping[str, object], *, allow_unpublished: bool) -> str | None`, which replaces `_detail_fields` and returns the failing rule or `None`. Its callers are `validate_sdd_report` and `validate_ship_summary_report`. The reasons below are the CLI contract after `artifact-budget: invalid report: `.

**Invariants:**
- `validate_ship_summary_report` keeps its order: the key set, then `notes`, then the field rules in the order of the table below, then the state rules. It raises at the first failure, so one input always gives one line (D6).
- Each new reason keeps the old text as its prefix (`invalid ship summary`, `invalid ship summary state`, `invalid SDD report`) and adds `: <member> <rule>`. `invalid PR URL` folds into `invalid ship summary` (D6). A reason names a state only when the rule depends on it, and only after that state has passed the closed-set check, so no input value is echoed.
- Every input that is accepted today stays accepted, and every input that is refused today stays refused. Only the reason text changes.
- `validate_ledger_result`, ship-handoff, `invalid SDD state` and the SDD report's `acceptance_state` refusal (`invalid SDD report`, bare) keep their text (D6, spec § Out of scope).

Reasons, in check order:

| Rule | Reason |
|---|---|
| `issue` | `invalid ship summary: issue must be a positive integer` |
| `discussion_items` | `invalid ship summary: discussion_items must be an empty list` |
| `issue_closed` | `invalid ship summary: issue_closed must be a boolean` |
| detail | `invalid ship summary: <_detail_fault reason>` |
| `pr_url` | `invalid ship summary: pr_url must be null or a non-empty string` |
| merged, `pr_url` | `invalid ship summary state: pr_url must be a non-empty string when state is merged` |
| merged, `merge_sha` | `invalid ship summary state: merge_sha must be a 40-hex commit when state is merged` |
| merged, `detail_state` | `invalid ship summary state: detail_state must be none or present when state is merged` |
| stopped or failed, `merge_sha` | `invalid ship summary state: merge_sha must be null when state is <state>` |
| stopped or failed, `issue_closed` | `invalid ship summary state: issue_closed must be false when state is <state>` |
| any other state | `invalid ship summary state: state must be merged, stopped or failed` |

`_detail_fault` reasons, where `<state>` is `present` or `unpublished`:
- `detail_state must be none, present or unpublished`, or `detail_state must be none or present` when `allow_unpublished` is false;
- `report_path must be null when detail_state is none`;
- `report_path must be a path under .superpowers/issue-delivery/ when detail_state is present` (when `_relative_path(path, durable=True)` fails);
- `report_path must be a path under .superpowers/ outside issue-delivery/ when detail_state is unpublished` (when `_relative_path(path, durable=False)` fails);
- `report_path must be cited in notes when detail_state is <state>`.

The SDD report raises `invalid SDD report: <_detail_fault reason>`.

- [ ] **Step 1: Write the failing tests**

Add both methods to `ArtifactBudgetCliTest` in `home/common/agent-skills/tests/test_artifact_budget.py`, directly after `test_every_legacy_boundary_names_its_members_and_notes_bound`:

```python
    def test_ship_summary_refusals_name_the_member_and_rule(self):
        """Issue 559 AC2, D6, D7: every ship-summary rule names its member and rule, on v1 and v2."""
        self.addCleanup(lambda: [sys.modules.pop(key, None) for key in tuple(sys.modules)
                                 if key == "_artifact_budget_delivery_model"
                                 or key.startswith("_artifact_budget_delivery_model.")])
        bound = json.loads(POLICY.read_text(encoding="utf-8"))["phase_reports"]["notes_max_characters"]
        model = artifact_budget._delivery_model()
        contract, _ = contract_and_delivery(model)
        digest = model.canonical_digest(contract)
        durable = ".superpowers/issue-delivery/151/run-1/ship-review.json"
        retained = ".superpowers/ship-review/151/retained-detail.json"
        stopped = {"issue": 151, "state": "stopped", "pr_url": None, "merge_sha": None,
                   "issue_closed": False, "discussion_items": [], "detail_state": "none",
                   "report_path": None, "notes": "stopped"}
        merged = {**stopped, "state": "merged", "pr_url": "https://github.com/fagenorn/nix-config/pull/187",
                  "merge_sha": "c" * 40, "issue_closed": True, "notes": "merged"}

        def wrapped(result):
            return {"interface_version": 2, "issue": 151, "state": "terminal_failed",
                    "custody": custody(), "historical_owner_result": result,
                    "delivery_contract_digest": digest, "delivery_observations": [],
                    "authority_observations": [], "reevaluation_evidence": [],
                    "detail_state": "none", "report_path": None, "notes": "failed"}

        summary, state = "invalid ship summary: ", "invalid ship summary state: "
        rows = (
            (stopped, {"issue": 0}, summary + "issue", "positive integer"),
            (stopped, {"discussion_items": ["lost"]}, summary + "discussion_items", "empty list"),
            (stopped, {"issue_closed": 0}, summary + "issue_closed", "boolean"),
            (stopped, {"detail_state": "partial"}, summary + "detail_state", "none, present or unpublished"),
            (stopped, {"report_path": durable}, summary + "report_path", "null when detail_state is none"),
            (stopped, {"detail_state": "present", "report_path": retained, "notes": retained},
             summary + "report_path", "issue-delivery/ when detail_state is present"),
            (stopped, {"detail_state": "unpublished", "report_path": durable, "notes": durable},
             summary + "report_path", "outside issue-delivery/ when detail_state is unpublished"),
            (stopped, {"detail_state": "present", "report_path": durable},
             summary + "report_path", "cited in notes when detail_state is present"),
            (stopped, {"pr_url": ""}, summary + "pr_url", "null or a non-empty string"),
            (merged, {"pr_url": None}, state + "pr_url", "non-empty string when state is merged"),
            (merged, {"merge_sha": "c" * 7}, state + "merge_sha", "40-hex commit when state is merged"),
            (merged, {"detail_state": "unpublished", "report_path": retained, "notes": retained},
             state + "detail_state", "none or present when state is merged"),
            (stopped, {"merge_sha": "c" * 40}, state + "merge_sha", "null when state is stopped"),
            ({**stopped, "state": "failed"}, {"issue_closed": True}, state + "issue_closed",
             "false when state is failed"),
            (stopped, {"state": "closed"}, state + "state", "merged, stopped or failed"),
            (stopped, {"notes": "n" * (bound + 1)}, "notes", str(bound)),
        )
        for accepted in (stopped, merged, wrapped(stopped), wrapped(merged)):
            self.assertEqual(self.run_validate("ship-summary", accepted, True).returncode, 0)
        for base, change, member, rule in rows:
            for version, value in ((1, {**base, **change}), (2, wrapped({**base, **change}))):
                with self.subTest(member=member, rule=rule, version=version):
                    reason = self.assert_refusal(self.run_validate("ship-summary", value, version == 1),
                                                 "invalid report")
                    if version == 2:
                        self.assertTrue(reason.startswith("ship-summary: "), reason)
                    self.assertIn(member, reason)
                    self.assertIn(rule, reason)
                    self.assertNotIn("closed", reason.replace("issue_closed", ""))

    def test_an_sdd_detail_refusal_names_report_path(self):
        """Issue 559 D6: the shared detail check names its rule for the SDD report too."""
        value = self.make_sdd("complete", "clean", "clean", "clean", "passed", "a" * 40, "b" * 40,
                              "present", ".superpowers/issue-delivery/49/run-1/sdd-a.json")
        self.assertEqual(self.run_validate("sdd", value, True).returncode, 0)
        reason = self.assert_refusal(self.run_validate("sdd", {**value, "notes": "no durable detail"}, True),
                                     "invalid report")
        self.assertEqual(reason, "invalid SDD report: report_path must be cited in notes when detail_state is present")
```

The `"closed"` check holds the "no echo" rule for the unknown-state row, the only row whose input value would show up in a reason.

- [ ] **Step 2: Run the tests and watch them fail**

Run (timeout 600 s): `launch-scope exec --repo-root <ledger root> --run-id <run-id> --worker-id <worker-id> -- bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_artifact_budget.py -k test_ship_summary_refusals_name_the_member_and_rule -k test_an_sdd_detail_refusal_names_report_path 2>&1 | tail -6'`
Expected: FAIL, `Ran 2 tests` and `FAILED`. The reasons are still the bare `invalid ship summary`, `invalid PR URL`, `invalid ship summary state` and `invalid SDD report`, so `assertIn(member, …)` fails for every row except the `notes` row, which issue 472 already names (D7).

- [ ] **Step 3: Write the minimal implementation**

In `home/common/agent-skills/scripts/artifact_budget.py`:
- Replace `_detail_fields` with `_detail_fault`. It checks in this order: `none`, which needs `report_path` null; `present`, which needs `_relative_path(path, durable=True)`; `unpublished` when `allow_unpublished`, which needs `_relative_path(path, durable=False)`; anything else, which is the closed-set reason. For `present` and `unpublished` it finally requires `path in notes`. Keep the docstring sentence that callers run `_require_notes` first.
- `validate_sdd_report`: `if (fault := _detail_fault(value, allow_unpublished=True)) is not None: raise ArtifactBudgetError(f"invalid SDD report: {fault}")`. The `acceptance_state` check after it stays the bare `invalid SDD report`.
- `validate_ship_summary_report`: after `_require_members` and `_require_notes`, run the field rules and then the state rules of the table, each raising its full reason. The old `or` chain becomes sequential checks in the same order, with `pr_url` last among the field rules, as before. The `merged` checks run in the order `pr_url`, `merge_sha`, `detail_state`, and the `stopped`/`failed` checks in the order `merge_sha`, `issue_closed`. The `detail_state` membership test is safe, because `_detail_fault` has already confined it to the closed set.

- [ ] **Step 4: Verify**

1. Focused tests, green (timeout 600 s): the Step 2 command.
   Expected: `Ran 2 tests` and `OK`.
2. The whole module, for the matrix and v2 tests that drive the same validators (timeout 1800 s): `launch-scope exec --repo-root <ledger root> --run-id <run-id> --worker-id <worker-id> -- bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_artifact_budget.py 2>&1 | tail -4'`
   Expected: `OK`. A failure in `test_every_sdd_report_matrix_row`, `test_a_held_merge_row_is_an_owner_report` or `test_only_response_result_slots_accept_the_reconciliation_record` means the change altered which inputs are accepted.
3. Static scope (instant): `if grep -nE '"invalid PR URL"|_detail_fields|raise ArtifactBudgetError\("invalid ship summary( state)?"\)' home/common/agent-skills/scripts/artifact_budget.py; then exit 1; fi`
   Expected: exit 0 with no output. Exit 1 lists a bare composite that is still raised.

No `just build` is needed: the build copies `artifact_budget.py` and never imports it.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/scripts/artifact_budget.py home/common/agent-skills/tests/test_artifact_budget.py
launch-commit --repo-root <ledger root> --run-id <run-id> --worker-id <worker-id> -- -m "fix(issue-559): name the failing ship-summary member and rule" -m "<the session's Co-Authored-By trailer>"
```

Then check the scope (instant): `test "$(git show --name-only --format= HEAD | sort | tr '\n' ' ')" = "home/common/agent-skills/scripts/artifact_budget.py home/common/agent-skills/tests/test_artifact_budget.py "`
Expected: exit 0. A non-zero exit means the commit touched another file or missed one.

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[],"commit_subject_bytes":[64,64,64],"id":3,"records":[{"bounds":[{"added_lines":60,"boundary":"all","deleted_lines":25,"record_bytes":12288,"support":{"covers":["r3-1"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r3-1","last_task":3,"owner":3,"path":"home/common/agent-skills/scripts/artifact_budget.py"},{"bounds":[{"added_lines":80,"boundary":"all","deleted_lines":0,"record_bytes":12288,"support":{"covers":["r3-2"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r3-2","last_task":3,"owner":3,"path":"home/common/agent-skills/tests/test_artifact_budget.py"}]}}
```
