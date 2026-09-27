# Task 1: The ledger-result rule for workflow-response result slots

Per D2, D3, D4, D7, D9, D10. Abbreviations: `S` = `home/common/agent-skills/scripts`,
`T` = `home/common/agent-skills/tests`.

**Files:**
- Modify: `S/artifact_budget.py`
- Modify: `S/workflow-state.py` (the `reconciled_result` docstring only)
- Test: `T/test_artifact_budget.py`, `T/test_workflow_state.py`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces:
  - `artifact_budget.validate_ledger_result(value: Mapping[str, object], notes_max_characters: int) -> None`,
    which raises `ArtifactBudgetError` on refusal.
  - `artifact_budget._validate_legacy_result_slot(value, issue, notes_max_characters, *, rule)`,
    where `rule: Callable[[Mapping[str, object], int], None]`.
  - `LifecycleHarness.validated_response(self, stdout: str) -> dict` in
    `T/test_workflow_state.py`. It pipes `stdout` through the real
    `artifact-budget validate-report --boundary workflow-response --input -`,
    asserts exit 0, empty stderr and canonical stdout byte-equal to `stdout`, and
    returns `json.loads(stdout)`. Tasks 2 and 3 call it from `progress()` and
    `suspend()`.

**Invariants:**
- `validate_ledger_result` accepts `v` iff `validate_ship_summary_report(v)`
  accepts it, or `v` is the lifecycle reconciliation record the spec's
  "Ledger-result rule" section defines.
- The rule dispatches on the reconciliation signature (`state == "merged"` and
  `issue_closed is False`), which the owner rule never accepts. There is no
  try/except around the owner rule (D10).
- The workflow-response boundary applies the ledger-result rule to `kind:
  terminal` → `result` and to every control `summaries[].result`. The
  ship-summary v2 `historical_owner_result` slot and the v1 ship summary stay on
  `validate_ship_summary_report`. No `--boundary` value is added.
- `reconciled_result` and `reconcile_merged_attempt` keep their code byte for
  byte. Only one docstring sentence changes.

- [ ] **Step 1: Write the failing tests**

(a) In `T/test_artifact_budget.py`, class `ArtifactBudgetCliTest`, insert this
method immediately before `def test_workflow_response_uses_source_and_lexical_installed_package`:

```python
    def test_only_response_result_slots_accept_the_reconciliation_record(self):
        """#191 D2-D4: the ledger-result rule widens the workflow-response slots only."""
        self.addCleanup(lambda: [sys.modules.pop(key, None) for key in tuple(sys.modules)
                                 if key == "_artifact_budget_delivery_model"
                                 or key.startswith("_artifact_budget_delivery_model.")])
        model = artifact_budget._delivery_model()
        contract, _ = contract_and_delivery(model)
        digest = model.canonical_digest(contract)
        durable = ".superpowers/issue-delivery/151/run-1/ship-review.json"
        retained = ".superpowers/ship-review/151/retained-detail.json"
        superseded = "reconciled from forge observation; superseded owner failed verdict"
        bare = {"issue": 151, "state": "merged",
                "pr_url": "https://github.com/fagenorn/nix-config/pull/187",
                "merge_sha": "bad94161012db5d285176762e4f4a9247d2f4d48",
                "issue_closed": False, "discussion_items": [],
                "detail_state": "none", "report_path": None,
                "notes": "reconciled from forge observation"}
        records = {
            "bare": bare,
            "present": {**bare, "detail_state": "present", "report_path": durable,
                        "notes": superseded},
            "unpublished": {**bare, "detail_state": "unpublished",
                            "report_path": retained, "notes": superseded},
        }

        def terminal(result):
            value = deepcopy(workflow_responses(model)["terminal"])
            value["result"] = deepcopy(result)
            return value

        def control(result):
            value = deepcopy(workflow_responses(model)["control"])
            value["summaries"][0]["result"] = deepcopy(result)
            return value

        def summary(result):
            return {"interface_version": 2, "issue": 151, "state": "delivery_complete",
                    "custody": custody(), "historical_owner_result": deepcopy(result),
                    "delivery_contract_digest": digest, "delivery_observations": [],
                    "authority_observations": [], "reevaluation_evidence": [],
                    "detail_state": "none", "report_path": None, "notes": "merged"}

        owner_twin = {**bare, "issue_closed": True}
        for boundary, value in (("ship-summary", summary(owner_twin)),
                                ("ship-summary", owner_twin)):
            accepted = self.run_validate(boundary, value, use_stdin=True)
            self.assertEqual((accepted.returncode, accepted.stderr), (0, b""))
        for name, record in records.items():
            for slot, wrap in (("terminal", terminal), ("control", control)):
                with self.subTest(record=name, slot=slot):
                    accepted = self.run_validate("workflow-response", wrap(record),
                                                 use_stdin=True)
                    self.assertEqual((accepted.returncode, accepted.stderr), (0, b""))
            for version, value in ((2, summary(record)), (1, record)):
                with self.subTest(record=name, ship_summary=version):
                    refused = self.run_validate("ship-summary", value, use_stdin=True)
                    self.assertEqual((refused.returncode, refused.stdout), (2, b""))
        mutations = {
            "null PR URL": {"pr_url": None},
            "short merge SHA": {"merge_sha": "bad9416"},
            "discussion items": {"discussion_items": ["lost"]},
            "none with a path": {"report_path": durable},
            "present without a path": {"detail_state": "present"},
            "present with a retained path": {"detail_state": "present",
                                             "report_path": retained},
            "unpublished with a durable path": {"detail_state": "unpublished",
                                                "report_path": durable},
            "notes over the policy limit": {"notes": "n" * 501},
            "an extra member": {"result_source": "superseded"},
        }
        for name, change in mutations.items():
            for slot, wrap in (("terminal", terminal), ("control", control)):
                with self.subTest(mutation=name, slot=slot):
                    refused = self.run_validate("workflow-response",
                                                wrap({**bare, **change}), use_stdin=True)
                    self.assertEqual((refused.returncode, refused.stdout), (2, b""))
```

(b) In `T/test_workflow_state.py`, class `LifecycleHarness`, replace the body of
`control_validated` with a call to a new `validated_response` helper. The
helper goes directly above `control_validated`:

```python
    def validated_response(self, stdout):
        """Decode reply bytes the `workflow-response` boundary passes unchanged (#191 D7)."""
        validated = subprocess.run(
            [sys.executable, str(ARTIFACT_BUDGET), "validate-report", "--boundary",
             "workflow-response", "--input", "-", "--policy", str(BUDGET_POLICY)],
            input=stdout, capture_output=True, text=True, check=False,
            env=self.cli_env)
        self.assertEqual((validated.returncode, validated.stderr), (0, ""))
        self.assertEqual(validated.stdout, stdout)
        return json.loads(stdout)

    def control_validated(self, **request_fields):
        """Sweep, returning interface-3 bytes the `workflow-response` boundary passes (#194)."""
        completed = self.control_raw(legacy=False, ok=False, **request_fields)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return self.validated_response(completed.stdout)
```

(c) In `T/test_workflow_state.py`, insert this class immediately before
`class ResolverOutcomeTest(unittest.TestCase):`. The `none` direct case parks
the attempt with `suspend` and ignores its return value, so it does not depend
on Task 3's helper change.

```python
class ReconciledReplyBoundaryTest(LifecycleHarness, unittest.TestCase):
    """#191: every reply that projects a reconciled merge passes the boundary."""

    MERGED_PR = {"state": "merged",
                 "url": "https://github.com/fagenorn/nix-config/pull/187",
                 "merge_sha": "bad94161012db5d285176762e4f4a9247d2f4d48"}
    # The record run-20260923-147-153-154-150-148-149-126-155 persisted for #154.
    RECONCILED_154 = {
        "issue": 154, "state": "merged",
        "pr_url": "https://github.com/fagenorn/nix-config/pull/187",
        "merge_sha": "bad94161012db5d285176762e4f4a9247d2f4d48",
        "issue_closed": False, "discussion_items": [],
        "detail_state": "none", "report_path": None,
        "notes": "reconciled from forge observation",
    }

    def contractless_sweep(self, issue, *, now, tracker_state="open"):
        """A validated sweep of a ledger with no delivery contract, the forge merged."""
        worktree = self.read_state()["issues"][str(issue)]["attempts"][-1]["worktree"]
        request = self.control_request(
            now=now, issues=[issue],
            tracker=[self.tracker_fact(issue, state=tracker_state)],
            worktrees=[self.worktree_fact(issue, recorded={
                "path": worktree, "state": "matching_issue_branch"})],
            max_parallel=1)
        request["delivery_contracts"][str(issue)] = None
        request["authorization_intents"][str(issue)] = []
        request["forge"][str(issue)] = copy.deepcopy(self.MERGED_PR)
        return self.control_validated(request=request)

    def test_control_relays_a_reconciled_merge_on_every_sweep(self):
        """Acceptance 1 (D2): reconciled, the result keeps `issue_closed` false and validates."""
        for tracker_state in ("closed", "open"):
            with self.subTest(tracker=tracker_state):
                self.run_id = f"reconcile-{tracker_state}"
                self.init_run()
                self.spawn(issue=47, worktree=self.root / f"wt-47-{tracker_state}")
                self.suspend(issue=47, attempt=1, blocked_on="usage_limit",
                             now="2026-08-13T20:02:00Z")
                state = self.read_state()
                state["issues"]["47"]["delivery"] = self.empty_delivery()
                self.write_state(state)
                for now in ("2026-08-13T20:03:00Z", "2026-08-13T20:04:00Z"):
                    summary = self.contractless_sweep(
                        47, now=now, tracker_state=tracker_state)["summaries"][0]
                    self.assertEqual(
                        (summary["state"], summary["result"]["state"],
                         summary["result"]["issue_closed"]), ("merged", "merged", False))
                attempt = self.read_state()["issues"]["47"]["attempts"][-1]
                self.assertEqual((attempt["state"], attempt["result_source"]),
                                 ("merged", "superseded"))

    def test_control_relays_the_persisted_154_record(self):
        """Acceptance 2 (D4): the shape run-…-155 holds for #154 validates, unmigrated."""
        self.run_id = "run-20260923-147-153-154-150-148-149-126-155"
        self.init_run()
        self.spawn(issue=154, worktree=self.root / "worktree-issue-154")
        self.suspend(issue=154, attempt=1, blocked_on="usage_limit",
                     now="2026-08-13T20:02:00Z")
        state = self.read_state()
        issue = state["issues"]["154"]
        attempt = issue["attempts"][-1]
        attempt.update({"state": "merged", "blocked_on": None,
                        "result": copy.deepcopy(self.RECONCILED_154),
                        "finished_at": "2026-08-13T20:05:00Z",
                        "result_source": "superseded"})
        issue["outcome"] = copy.deepcopy(self.RECONCILED_154)
        issue["delivery"] = self.empty_delivery()
        self.write_state(state)
        before = self.state_path.read_bytes()
        response = self.contractless_sweep(154, now="2026-08-13T20:06:00Z")
        self.assertEqual(response["summaries"][0]["result"], self.RECONCILED_154)
        self.assertEqual(
            json.loads(self.state_path.read_bytes())["issues"]["154"]["attempts"],
            json.loads(before)["issues"]["154"]["attempts"])

    def test_direct_replays_of_a_reconciled_merge_validate(self):
        """Acceptance 2 (D4): raw direct replays validate, bare or carrying a superseded pointer."""
        durable = ".superpowers/issue-delivery/154/run-1/ship-review.json"
        retained = ".superpowers/ship-review/154/retained-detail.json"
        for detail_state, report_path in (("none", None), ("present", durable),
                                          ("unpublished", retained)):
            with self.subTest(detail_state=detail_state):
                root = self.root / f"direct-{detail_state}"
                root.mkdir()
                root = root.resolve()
                self.root = root
                owner = self.acquire_direct(issue=154)
                if report_path is not None:
                    verdict = {**self.RECONCILED_154, "state": "failed", "pr_url": None,
                               "merge_sha": None, "detail_state": detail_state,
                               "report_path": report_path,
                               "notes": f"owner verdict; details: {report_path}"}
                    path = self.direct_state_path(owner["run_id"])
                    state = json.loads(path.read_text())
                    attempt = state["issues"]["154"]["attempts"][-1]
                    attempt.update({"state": "failed", "blocked_on": None,
                                    "result": copy.deepcopy(verdict),
                                    "finished_at": "2026-08-20T10:30:00Z",
                                    "result_source": "owner"})
                    state["issues"]["154"]["outcome"] = copy.deepcopy(verdict)
                    path.write_text(json.dumps(state), encoding="utf-8")
                else:
                    self.run_id = owner["run_id"]
                    self.suspend(issue=154, attempt=1, blocked_on="human_gate",
                                 now="2026-08-20T10:30:00Z")
                replies = []
                for now, forge in (("2026-08-20T11:00:00Z", self.MERGED_PR),
                                   ("2026-08-20T11:05:00Z", self.no_pull_request())):
                    request = self.direct_request(
                        issue=154, now=now, forge=copy.deepcopy(forge),
                        worktree=self.worktree_fact(154, recorded={
                            "path": owner["worktree"], "state": "matching_issue_branch"}))
                    completed = self.direct_owner_at_root(root, request)
                    replies.append(self.validated_response(completed.stdout))
                reconciled, replayed = replies
                self.assertEqual((replayed["kind"], replayed["reason"]), ("terminal", "merged"))
                self.assertEqual(replayed, reconciled)
                result = replayed["result"]
                self.assertEqual((result["issue_closed"], result["detail_state"],
                                  result["report_path"]), (False, detail_state, report_path))
                if report_path is None:
                    self.assertEqual(result, self.RECONCILED_154)
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_artifact_budget.py -k reconciliation_record 2>&1 | grep -E '^(FAIL|ERROR):|^Ran |^OK|^FAILED'`
Expected: `FAILED (failures=6)`. The six are the `record`×`slot` acceptance subtests.
The mutation and ship-summary subtests already pass, because the owner rule refuses them today.

Run: `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_workflow_state.py -k ReconciledReplyBoundaryTest 2>&1 | grep -E '^(FAIL|ERROR):|AssertionError|^Ran |^OK|^FAILED'`
Expected: every subtest fails with `Tuples differ: (2, 'artifact-budget: invalid report\n') != (0, '')`.

- [ ] **Step 3: Implement the rule and compose it**

In `S/artifact_budget.py`:

1. Change the typing import to `from typing import Callable, Mapping, Sequence`.
2. Insert the rule directly after `validate_ship_summary_report`. It is written
   out in full because it pins the D10 dispatch and the exact record:

```python
def validate_ledger_result(value: Mapping[str, object], notes_max_characters: int) -> None:
    """Check a result the lifecycle ledger projects onto a workflow response.

    The ledger holds owner reports, which the owner-report rule
    (``validate_ship_summary_report``) already accepts, and one record no owner
    writes: reconciliation's ``merged`` row with ``issue_closed`` false, which
    asserts only the merge the forge observed. That record may carry a
    superseded owner's detail pointer without citing it in its notes.
    """
    if not (isinstance(value, dict) and value.get("state") == "merged"
            and value.get("issue_closed") is False):
        validate_ship_summary_report(value, notes_max_characters)
        return
    keys = {"issue", "state", "pr_url", "merge_sha", "issue_closed", "discussion_items",
            "detail_state", "report_path", "notes"}
    if not _exact_keys(value, keys):
        raise ArtifactBudgetError("invalid ledger result")
    detail, path = value["detail_state"], value["report_path"]
    valid = (_integer(value["issue"], minimum=1) and _string(value["pr_url"])
             and _sha(value["merge_sha"]) and value["discussion_items"] == []
             and _notes(value["notes"], notes_max_characters)
             and ((detail == "none" and path is None)
                  or (detail == "present" and _relative_path(path, durable=True))
                  or (detail == "unpublished" and _relative_path(path, durable=False))))
    if not valid:
        raise ArtifactBudgetError("invalid ledger result")
```

3. `_validate_legacy_result_slot` gains a keyword-only
   `rule: Callable[[Mapping[str, object], int], None]` and calls
   `rule(value, notes_max_characters)` where it called
   `validate_ship_summary_report`. It keeps its `None` early return, its issue
   type check and its `legacy result issue mismatch` check. Its docstring
   becomes `"""Apply ``rule`` to one nullable v2 result slot and match its issue."""`.
4. In `validate_workflow_response_report`, pass `rule=validate_ledger_result` at
   both calls, the terminal `result` and each `summaries[].result`. In
   `validate_delivery_model_report`, pass `rule=validate_ship_summary_report`
   for `historical_owner_result`.

In `S/workflow-state.py`, in the `reconciled_result` docstring, replace the
sentence that runs from "That is also why this record is checked against the
ledger's own result schema" to "and cleaned up." Its "That is" ends the line
`closed, because reconciliation saw a merge, not a report (per D3). That is`,
so after the edit that line ends at `(per D3).`. The replacement, on the lines
that follow it, is exactly:

```text
    That is also why every workflow response that relays this record checks it
    with artifact-budget's ledger-result rule (``validate_ledger_result``), not
    the owner-report rule: a ``merged`` owner report means the owner also closed
    the issue and cleaned up.
```

- [ ] **Step 4: Verify**

Run each of these. Summarize the unittest output with the Step 2 `grep -E` filter.

1. `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_artifact_budget.py` → `OK`, one test more than at the start.
2. `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_workflow_state.py -k ReconciledReplyBoundaryTest -k unresumable` → `OK`. The `-k unresumable` tests are #194's `control_validated` users.
3. `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_workflow_state.py home/common/agent-skills/tests/test_delivery_workflow.py` → `OK`. This takes several minutes, so run it once.
4. Docstring gate (it fails before Step 3):
   `(set -e; f=home/common/agent-skills/scripts/workflow-state.py; grep -q 'ledger-result rule (``validate_ledger_result``)' "$f"; if grep -q "ledger's own result schema" "$f"; then exit 1; fi)`
5. Behaviour-freeze gate. No `workflow-state.py` function body changes; only
   docstrings may. It exits non-zero and names the function if a body changed:

```bash
python3 - <<'EOF'
import ast, subprocess
path = "home/common/agent-skills/scripts/workflow-state.py"
def bodies(source):
    return {node.name: ast.dump(ast.Module(
                body=node.body[1:] if ast.get_docstring(node) else node.body,
                type_ignores=[]))
            for node in ast.parse(source).body if isinstance(node, ast.FunctionDef)}
base = bodies(subprocess.run(
    ["git", "show", f"6ab576eb655ad0fed75028c658c4b8c0c756cdd7:{path}"],
    capture_output=True, text=True, check=True).stdout)
head = bodies(open(path, encoding="utf-8").read())
changed = sorted(name for name in base.keys() | head.keys() if base.get(name) != head.get(name))
raise SystemExit(f"function bodies changed: {changed}" if changed else 0)
EOF
```

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/scripts/artifact_budget.py \
  home/common/agent-skills/scripts/workflow-state.py \
  home/common/agent-skills/tests/test_artifact_budget.py \
  home/common/agent-skills/tests/test_workflow_state.py
git commit -m "fix(agent-skills): validate reconciled merges with a ledger-result rule (#191)"
```
