# Task 3: Owner rule admits a held merge; finish cross-checks issue_closed

**Files:**
- Modify: `home/common/agent-skills/scripts/artifact_budget.py`
- Modify: `home/common/agent-skills/scripts/workflow_delivery.py`
- Test: `home/common/agent-skills/tests/test_artifact_budget.py`
- Test: `home/common/agent-skills/tests/test_delivery_workflow.py`

**Interfaces:**
- Consumes (Tasks 1–2): `build-delivery --kind observation` for `tracker_held`, with the facts `comment_url`, `record_path`, `acceptance_state` and `observation_identity`. Its subject satisfies `close_tracker` and the `tracker_closed` postcondition.
- Produces:
  - `artifact_budget.validate_ship_summary_report` accepts a `merged` row with `issue_closed` either `true` or `false`. Every other condition of that rule is unchanged (D6).
  - `DeliveryRuntime.finish_outcome` refuses, with `ValueError("delivery summary issue_closed does not match the tracker outcome")`, a `delivery_complete` summary that meets all three of these conditions (D17):
    - its `historical_owner_result` is non-null;
    - its reduced delivery's `tracker_closed` postcondition is `observed`;
    - `historical_owner_result["issue_closed"]` is not exactly `observation_kind == "tracker_closed"` of the observation that postcondition names.
  - Task 4's control harness calls `finish` with a held row (`issue_closed: false`) and needs both of these.
- Produces, in `test_delivery_workflow.py`:
  - `SOURCES["tracker_held"] == "tracker"`. `test_delivered_control.py` and `test_admission_replay.py` import `SOURCES`.
  - Module constants `HELD_COMMENT = "https://github.com/fagenorn/nix-config/issues/171#issuecomment-1"` and `HELD_RECORD = ".claude/plans/2026-09-21-issue-171.acceptance.md"`.

**Invariants:**
- A `merged` row still needs a non-empty `pr_url`, a full 40-hex `merge_sha` and `detail_state ∈ {none, present}`. `stopped` and `failed` rows are unchanged.
- `validate_ledger_result`'s reconciliation branch is unchanged. Its docstring is rewritten so that it no longer claims that `merged` with `issue_closed: false` is outside the owner-report rule.
- The cross-check runs before any ledger mutation in `finish_outcome`. A refused finish leaves `state.json` byte-identical, and `workflow-state finish` exits 2.
- The cross-check is skipped when `tracker_closed` is `not_applicable`, and when `historical_owner_result` is null (D17).

- [ ] **Step 1: Write the failing tests**

(a) In `home/common/agent-skills/tests/test_artifact_budget.py`, find `test_only_response_result_slots_accept_the_reconciliation_record`. Replace only its inner `for version, value in ((2, summary(record)), (1, record)):` block with this:

```python
            for version, value in ((2, summary(record)), (1, record)):
                with self.subTest(record=name, ship_summary=version):
                    checked = self.run_validate("ship-summary", value, use_stdin=True)
                    if name == "bare":
                        # #273 D6 amends #191 D3: a held merge's owner row is
                        # `merged` with `issue_closed` false.
                        self.assertEqual((checked.returncode, checked.stderr), (0, b""))
                    else:
                        self.assertEqual((checked.returncode, checked.stdout), (2, b""))
```

Change the docstring's first line to `"""#191 D2-D4, amended by #273 D6: response slots alone accept the uncited reconciliation record."""`. Then append this method to the same class, `ArtifactBudgetCliTest`:

```python
    def test_a_held_merge_row_is_an_owner_report(self):
        """#273 D6: `merged` admits `issue_closed` false; nothing else widens."""
        held = {"issue": 273, "state": "merged",
                "pr_url": "https://github.com/fagenorn/nix-config/pull/300",
                "merge_sha": "c" * 40, "issue_closed": False, "discussion_items": [],
                "detail_state": "none", "report_path": None,
                "notes": "held for verification: https://github.com/fagenorn/nix-config/issues/273#issuecomment-1"}
        accepted = self.run_validate("ship-summary", held, use_stdin=True)
        self.assertEqual((accepted.returncode, accepted.stderr), (0, b""))
        for label, change in (("null PR URL", {"pr_url": None}),
                              ("null merge SHA", {"merge_sha": None}),
                              ("short merge SHA", {"merge_sha": "c" * 7}),
                              ("unpublished detail", {"detail_state": "unpublished",
                                                      "report_path": ".superpowers/x.json"}),
                              ("non-boolean", {"issue_closed": 0})):
            with self.subTest(mutation=label):
                refused = self.run_validate("ship-summary", {**held, **change},
                                            use_stdin=True)
                self.assertEqual((refused.returncode, refused.stdout), (2, b""))
```

(b) In `home/common/agent-skills/tests/test_delivery_workflow.py`:
1. Add `"tracker_held": "tracker"` to `SOURCES`.
2. Add the two `HELD_*` constants from Interfaces directly below `URL = ...`.
3. Give `DeliveryLoopTest.deliver` two keyword arguments, `tracker="tracker_closed"` and `issue_closed=None`, and make these changes inside it:
   - The `close_tracker` facts entry becomes this:
     ```python
     "close_tracker": [self.observed(tracker, **({
         "close_reason": "completed",
         "observation_identity": "github:issue:171:closed"}
         if tracker == "tracker_closed" else {
         "comment_url": HELD_COMMENT, "record_path": HELD_RECORD,
         "acceptance_state": "unmet",
         "observation_identity": "github:issue:171:held"}))],
     ```
   - Set `closed = (tracker == "tracker_closed") if issue_closed is None else issue_closed`. The historical row then uses `"issue_closed": closed`, and its `notes` are `"delivered"` on close and `f"held for verification: {HELD_COMMENT}"` on hold.
   - Immediately after `validated = self.validated("ship-summary", summary)` and the existing wire-size assertion, insert the mismatch branch:
     ```python
     if closed is not (tracker == "tracker_closed"):
         before = state.read_bytes()
         refused = self.cli("finish", *self.run_args, "--now", LATER,
                            "--summary-file", "-", stdin=validated, ok=False)
         self.assertEqual((refused.returncode, state.read_bytes()), (2, before))
         self.assertIn(b"issue_closed does not match the tracker outcome",
                       refused.stderr)
         return
     ```
   - After the existing `stored["attempts"][-1]["state"]` assertion, add:
     ```python
     self.assertIs(stored["attempts"][-1]["result"]["issue_closed"], closed)
     held_id = stored["delivery"]["postconditions"]["tracker_closed"]["observation_id"]
     self.assertEqual(next(item["observation_kind"]
                           for item in stored["delivery"]["delivery_observations"]
                           if item["id"] == held_id), tracker)
     ```
4. Add these two tests to `DeliveryLoopTest`:

```python
    def test_a_held_delivery_completes_with_issue_closed_false(self):
        """#273: tracker_held satisfies close_tracker; the owner row says not closed."""
        self.deliver({"merge_pr", "close_tracker", "remove_worktree", "delete_local_branch"},
                     tracker="tracker_held")

    def test_finish_refuses_an_issue_closed_that_disagrees_with_the_tracker(self):
        """#273 D6, D17: the historical row agrees with the observed tracker outcome."""
        for tracker, closed in (("tracker_held", True), ("tracker_closed", False)):
            with self.subTest(tracker=tracker, issue_closed=closed):
                self.deliver({"merge_pr", "close_tracker", "remove_worktree",
                              "delete_local_branch"}, tracker=tracker, issue_closed=closed)
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `PYTHONPATH=python timeout 900 python3 -m unittest home/common/agent-skills/tests/test_artifact_budget.py -k reconciliation_record -k held_merge 2>&1 | tail -8`
Expected: FAIL. The `bare` record and the held row exit 2 at `ship-summary` (`invalid ship summary state`).

Run: `PYTHONPATH=python timeout 900 python3 -m unittest home/common/agent-skills/tests/test_delivery_workflow.py -k held_delivery -k disagrees_with_the_tracker 2>&1 | tail -8`
Expected: FAIL. Either the held summary is refused at `ship-summary`, or the `("tracker_held", True)` finish exits 0 because there is no cross-check yet.

- [ ] **Step 3: Write the minimal implementation**

1. In `artifact_budget.py` `validate_ship_summary_report`, the `merged` arm becomes `valid = _string(pr) and _sha(value["merge_sha"]) and value["detail_state"] in {"none", "present"}`. `issue_closed` is already checked to be a bool above. Rewrite the docstring of `validate_ledger_result` to say this: "Every row the ledger holds meets the owner-report rule, except reconciliation's `merged` row with `issue_closed` false. That row asserts only the merge the forge observed, and it may carry a superseded owner's detail pointer without citing it in its notes. An owner's held `merged` row (#273) has the same two cells but meets the owner rule."
2. In `workflow_delivery.py` `finish_outcome`, inside `if report["state"] == "delivery_complete":` and after the `completion_state` check, add `self._check_tracker_outcome(reduction["next_delivery"], report["historical_owner_result"])` before any `record.update`. Define this:
   ```python
   @staticmethod
   def _check_tracker_outcome(delivery: dict[str, Any], historical: dict[str, Any] | None) -> None:
       """A historical row's issue_closed names the observed tracker outcome (#273 D6, D17)."""
       post = delivery["postconditions"]["tracker_closed"]
       if historical is None or post["state"] != "observed":
           return
       kind = next(item["observation_kind"] for item in delivery["delivery_observations"]
                   if item["id"] == post["observation_id"])
       if historical["issue_closed"] is not (kind == "tracker_closed"):
           raise ValueError("delivery summary issue_closed does not match the tracker outcome")
   ```

- [ ] **Step 4: Verify**

Run: `PYTHONPATH=python timeout 900 python3 -m unittest home/common/agent-skills/tests/test_artifact_budget.py home/common/agent-skills/tests/test_delivery_workflow.py home/common/agent-skills/tests/test_delivered_control.py home/common/agent-skills/tests/test_admission_replay.py 2>&1 | tail -4`
Expected: `OK`.

Run: `PYTHONPATH=python timeout 1800 python3 -m unittest home/common/agent-skills/tests/test_workflow_state.py 2>&1 | tail -4`
Expected: `OK`. Ledger-result and reconciliation tests stay green.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/scripts/artifact_budget.py home/common/agent-skills/scripts/workflow_delivery.py home/common/agent-skills/tests/test_artifact_budget.py home/common/agent-skills/tests/test_delivery_workflow.py
launch-commit --repo-root <ledger_repo_root> --run-id <run-id> --worker-id <worker_id> -- -m "feat(ship-summary): admit a held merge row; finish checks issue_closed against the tracker outcome (#273)" -m "<trailers>"
```
