# Task 5: Late-result intake: recording, adoption, retention

An owner's `finish` now reaches the core: recorded against its launch's span, adopted over a reaper's stop, or retained when it is refused. Read the root's Global Constraints first. Decisions: D5, D6, D10, D17, D18, D20, D21.

**Files:**
- Modify: `home/common/agent-skills/scripts/workflow-state.py`, `python/agent_tools/attempt_store.py`
- Modify: `home/common/agent-skills/tests/test_attempt_custody.py` (add)

**Interfaces:**
- Consumes: Task 3's `settle_custody(…, report: OwnerReport | None)` (it already records a `record_result` operation), `OwnerReport`, `custody_of`, `store_lock`, `commit_state(…, report=None)`; Task 4's `OwnerCall`, `admit_owner_call`, `transact(…, owner_call=…)`; Task 2's `reaped`, `launch_fence`, `result_recorded`, `launch_id`, `at_ms`; the delivery runtime's public `record_for_custody(issue_state, custody)`, which raises `ValueError` unless the custody is the record's last launch and the record is `active`.
- Produces:
  - `attempt_store.retain_result(store: Path, run: str, *, issue: int, attempt: int, launch: int, report: dict, now_ms: int) -> bool`: records `report` with `record_owner_result` on the attempt's custody transaction, against the fence of `launch`'s latest span, under `store_lock`, with the clock `now_ms`. It returns `False` and writes nothing when the attempt has no custody transaction, the transaction is terminal, the core issued no span for that launch, or that span already holds a result with the same `telemetry_digest`.
  - `workflow-state.py`: `class CustodyRefusal(WorkflowError)`, an engine refusal of a finish for custody; `adopt_late_finish(issue_state, record, call) -> None`.

**Behaviour:**

1. **The report as submitted.** The legacy `finish` keeps a deep copy of the validated result object taken right after `load_result_file`, before the worktree note is added; `finish --summary-file` keeps the validated summary. That object is `OwnerCall.report`. The legacy call stays `keyed=True`; the summary call is `OwnerCall(issue=report["issue"], attempt=custody["attempt"], action_id=custody["action_id"], keyed=False, report=report, supplied=…, summary=True)` and is passed only for `custody["kind"] == "implementation"` (D10: remainders are untouched).
2. **Recording.** When the mutation changed the ledger and the call carries a report, `transact` passes `report=OwnerReport(call.issue, call.attempt, call.report)` to `commit_state`. The settle step records it against the last launch's span before any seal or release.
3. **Adoption** (D21), in `admit_owner_call` after the fence: when the call carries a report, the caller's launch is the attempt's last, the attempt is its issue's latest, it has a custody transaction and `reaped(transaction, <launch id>)` is true, call `adopt_late_finish` on the locked copy of the state. It presents the record as `active` again in two cases and does nothing in any other: the record is `suspended` with `blocked_on` `unknown` and no result (set `state` `active`, `blocked_on` `None`); or the call is a summary and the record is a `stalled` stop whose result is the issue's outcome (also clear `result`, `finished_at`, `result_source` and the issue's `outcome`). A summary whose `historical_owner_result` is null is never adopted. The engine then judges the finish as an on-time one; when it refuses, nothing is written.
4. **Custody refusals.** In the legacy `finish`, `finish requires an active attempt` and `conflicting terminal result for issue … attempt …` are raised as `CustodyRefusal` with the same text. In `finish --summary-file`, the mutation first calls `runtime.record_for_custody(issue_state, report["custody"])` for a known issue; its `ValueError` becomes `CustodyRefusal("delivery finish refused")`, the text the runtime's own refusal prints today.
5. **Retention** (D6, D20). A report is retained through `retain_result`, with `now_ms = at_ms` of the transport's ledger time (`ledger_time(supplied)`), in two places: before `superseded_launch` is raised for a call that carries one, and when the mutation raises `CustodyRefusal` for a call whose launch `admit_owner_call` resolved. The refusal is then raised unchanged; the ledger's bytes do not change.

**Invariants:**
- After a reaper's stop, a `finish` from the attempt's last launch succeeds, the ledger shows the owner's result with source `owner`, and the custody history holds `stop_synthesized` and an `owner_result` with `custody` `stale` whose `supersedes` is the stop's `seq`.
- A non-`merged` verdict with no merge recorded seals `abandoned`; the receipt read back by its digest lists the stop with `superseded_by` and the result with `supersedes`. A `merged` verdict, or any verdict over a recorded merge, leaves the transaction non-terminal with no custody and no receipt (D5).
- An on-time `finish` is recorded with `custody` `current` and `supersedes` null.
- A refused finish changes no ledger byte; it adds at most one `owner_result` per distinct report to the launch's span, and none after a seal.
- `workflow_delivery*.py` is not edited; a later control sweep that observes a delivery postcondition writes no core file.

- [ ] **Step 1: Write the failing tests**

In `home/common/agent-skills/tests/test_attempt_custody.py`, add this method to `LaunchFenceTest`:

```python
    def test_ac5_attempt_keyed_finish_is_refused_and_its_result_retained(self):
        self.legacy_owner_resumed_to_launch_2()
        ledger = self.state_path.read_bytes()
        launch_1 = ac.launch_fence(self.custody(14), "14:1:1")
        refused = self.finish(1, self.stopped(), now=T(33), action_id=False, ok=False)
        self.assertEqual(refused.returncode, 2)
        self.assertTrue(refused.stderr.startswith(PREFIX + "superseded_launch: "),
                        refused.stderr)
        self.assertEqual(self.state_path.read_bytes(), ledger)
        results = self.events(14, "owner_result")
        self.assertEqual(len(results), 1)
        self.assertEqual((results[0]["executor_id"], results[0]["custody"],
                          results[0]["fence"], results[0]["result"]),
                         ("14:1:1", "stale", launch_1, self.stopped()))
        self.assertEqual(self.custody(14).custody.executor_id, "14:1:2")
        self.finish(1, self.stopped(), now=T(33), action_id=False, ok=False)
        self.assertEqual(len(self.events(14, "owner_result")), 1)
```

Add these methods to `DeliveredCustody`:

```python
    def reap(self, issue):
        """Minute 31: the launch has expired and its worktree no longer matches, so the
        sweep reaps without resuming."""
        self.control(31, recorded={issue: "mismatch"})
        attempt = self.records(issue)[0][0]
        self.assertEqual((attempt["state"], attempt["blocked_on"], len(attempt["launches"])),
                         ("suspended", "unknown", 1))

    def finish(self, summary, minute, **options):
        return self.cli("finish", *self.run_args, "--now", at(minute), "--summary-file", "-",
                        stdin=summary, **options)

    def merge_checkpoint(self, custody, minute):
        """Select, publish, open and reach the merge stage at `minute`; returns the
        observations and authority the finishing summary still has to carry."""
        issue, when = DELIVERED, at(minute)
        contract = self.built[issue]["contract"]
        url, head = f"https://github.com/fagenorn/nix-config/pull/{issue}", "a" * 40
        selection = self.build("selected-output", {
            "contract": contract, "head": head, "tree": "c" * 40,
            "acceptance_ref": f".claude/specs/issue-{issue}.md", "review_ref": "clean",
            "test_ref": "checks"})
        pending = [self.observed(contract, when, "selected_output", selection=selection),
                   self.observed(contract, when, "branch_published", head=head),
                   self.observed(contract, when, "pr_opened", pr_number=issue, pr_url=url,
                                 head=head)]
        scope = self.build("scope", {"contract": contract, "stage_id": "merge_pr"})
        self.cli("checkpoint-delivery", *self.run_args, "--now", when, "--checkpoint-file",
                 "-", stdin=self.validated("ship-checkpoint", {
                     "interface_version": 2, "issue": issue, "custody": custody,
                     "contract_digest": self.model.canonical_digest(contract),
                     "delivery_observations": sorted(pending, key=lambda item: item["id"]),
                     "authority_observations": [], "reevaluation_evidence": [],
                     "requested_scope": scope, "detail_state": "none", "report_path": None,
                     "notes": ""}))
        authority = self.build("authority-observation", {
            "contract": contract, "scope_id": scope["id"], "launch_id": custody["action_id"],
            "authority_kind": "native_guard", "verdict": "allowed",
            "reason_code": "guard_allowed", "observed_at": when, "evidence": "merge_pr"})
        merged = self.observed(contract, when, "pr_merged", pr_number=issue, pr_url=url,
                               head=head, merge_sha="b" * 40)
        return [merged], [authority], {"pr_url": url, "merge_sha": "b" * 40}

    def postconditions(self, issue):
        delivery = self.ledger_document()["issues"][str(issue)]["delivery"]
        return {name: item["state"] for name, item in delivery["postconditions"].items()}

    def core_files(self):
        return {path: content for path, content in self.tree().items()
                if path.startswith(".superpowers/attempt-transactions/")}
```

Add these classes before the `__main__` guard:

```python
class LateLegacyResultTest(LifecycleCustody, unittest.TestCase):
    def reaped(self):
        self.spawn_14()
        self.expire(issue=14, worktree=self.worktree, now=T(31))
        attempt = self.read_state()["issues"]["14"]["attempts"][0]
        self.assertEqual((attempt["state"], attempt["blocked_on"]), ("suspended", "unknown"))

    def test_ac2_a_late_finish_supersedes_the_reapers_stop_in_the_receipt(self):
        self.reaped()
        self.assertEqual(self.finish(1, self.stopped(), now=T(32))["state"], "stopped")
        attempt = self.read_state()["issues"]["14"]["attempts"][0]
        self.assertEqual((attempt["state"], attempt["result_source"]), ("stopped", "owner"))
        sealed = self.custody(14)
        self.assertEqual((sealed.state, sealed.terminal["outcome"]), ("abandoned", "abandoned"))
        receipt = self.core().read_receipt(sealed.terminal["receipt_digest"])
        (stop,), (result,) = receipt["stops"], receipt["owner_results"]
        self.assertEqual((receipt["outcome"], stop["reason"], stop["executor_id"]),
                         ("abandoned", "expiry", "14:1:1"))
        self.assertEqual((stop["superseded_by"], result["supersedes"], result["custody"]),
                         (result["seq"], stop["seq"], "stale"))

    def test_ac2_a_late_merged_finish_is_recorded_and_left_unsealed(self):
        self.reaped()
        self.finish(1, self.merged_result(), now=T(32))
        attempt = self.read_state()["issues"]["14"]["attempts"][0]
        self.assertEqual((attempt["state"], attempt["result_source"]), ("merged", "owner"))
        open_ = self.custody(14)
        (stop,) = self.events(14, "stop_synthesized")
        (result,) = self.events(14, "owner_result")
        self.assertEqual((result["supersedes"], result["custody"]), (stop["seq"], "stale"))
        self.assertEqual((open_.state, open_.terminal, open_.custody),
                         ("attention_required", None, None))

    def test_an_on_time_finish_is_recorded_current_and_sealed(self):
        self.spawn_14()
        self.finish(1, self.stopped("on time"), now=T(5))
        sealed = self.custody(14)
        receipt = self.core().read_receipt(sealed.terminal["receipt_digest"])
        (result,) = receipt["owner_results"]
        self.assertEqual((receipt["outcome"], receipt["stops"], result["custody"],
                          result["supersedes"]), ("abandoned", [], "current", None))
        self.assertEqual(sealed.events[-3]["reason"], "owner:stopped")

    def test_a_finish_refused_for_custody_is_retained_without_touching_the_ledger(self):
        self.spawn_14()
        self.progress(turn_count=118, context_tokens=20000, now=T(1),
                      handoff_path=self.write_handoff(14))
        ledger = self.state_path.read_bytes()
        refused = self.finish(1, self.stopped(), now=T(2), ok=False)
        self.assertEqual(refused.returncode, 2)
        self.assertIn("finish requires an active attempt", refused.stderr)
        self.assertEqual(self.state_path.read_bytes(), ledger)
        (result,) = self.events(14, "owner_result")
        self.assertEqual((result["custody"], result["supersedes"]), ("stale", None))


class LateSummaryTest(DeliveredCustody, unittest.TestCase):
    def test_ac2_a_late_summary_supersedes_the_reapers_stop_in_the_receipt(self):
        custody = self.spawn(DELIVERED)[DELIVERED]
        self.reap(DELIVERED)
        finished = json.loads(self.finish(self.summary(custody, "stopped"), 32).stdout)
        self.assertEqual(finished["kind"], "terminal_failed")
        attempt = self.records(DELIVERED)[0][0]
        self.assertEqual((attempt["state"], attempt["result_source"]), ("stopped", "owner"))
        sealed = self.custody(DELIVERED)
        receipt = self.core().read_receipt(sealed.terminal["receipt_digest"])
        (stop,), (result,) = receipt["stops"], receipt["owner_results"]
        self.assertEqual((receipt["outcome"], stop["reason"], result["custody"]),
                         ("abandoned", "expiry", "stale"))
        self.assertEqual((stop["superseded_by"], result["supersedes"]),
                         (result["seq"], stop["seq"]))

    def test_a_late_summary_without_a_reap_or_from_an_earlier_launch_is_not_adopted(self):
        custody = self.spawn(DELIVERED)[DELIVERED]
        self.control(31, recorded={DELIVERED: "matching_issue_branch"})  # reap and resume
        ledger = self.ledger.read_bytes()
        refused = self.finish(self.summary(custody, "stopped"), 32, ok=False)
        self.assertEqual((refused.returncode, refused.stderr),
                         (2, b"workflow-state: delivery finish refused\n"))
        self.assertEqual(self.ledger.read_bytes(), ledger)
        (result,) = self.events(DELIVERED, "owner_result")
        self.assertEqual((result["executor_id"], result["custody"]),
                         (f"{DELIVERED}:1:1", "stale"))

    def test_ac4_merged_and_closed_are_observed_apart_from_custody(self):
        custody = self.spawn(DELIVERED)[DELIVERED]
        observations, authority, merged = self.merge_checkpoint(custody, 5)
        self.reap(DELIVERED)
        self.finish(self.summary(custody, "merged", observations, authority, **merged), 32)
        attempt = self.records(DELIVERED)[0][0]
        self.assertEqual((attempt["state"], attempt["result_source"]), ("merged", "owner"))
        held = self.custody(DELIVERED)
        (stop,) = self.events(DELIVERED, "stop_synthesized")
        (result,) = self.events(DELIVERED, "owner_result")
        self.assertEqual((held.terminal, held.custody, result["supersedes"]),
                         (None, None, stop["seq"]))
        before = self.postconditions(DELIVERED)
        self.assertEqual((before["pr_merged"], before["tracker_closed"]),
                         ("observed", "pending"))
        core = self.core_files()
        contract = self.built[DELIVERED]["contract"]
        request = json.loads(self.request(40, recorded={DELIVERED: "matching_issue_branch"},
                                          contracts=True))
        request["delivery_observations"][str(DELIVERED)] = [self.observed(
            contract, at(40), "tracker_closed", close_reason="completed",
            observation_identity=f"github:issue:{DELIVERED}:closed")]
        self.cli("control", *self.run_args, "--request-file", "-",
                 stdin=json.dumps(request).encode())
        self.assertEqual(self.postconditions(DELIVERED),
                         {**before, "tracker_closed": "observed"})
        self.assertEqual(self.core_files(), core)
```

- [ ] **Step 2: Run them and watch them fail**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_attempt_custody.py -k LateLegacyResultTest -k LateSummaryTest -k finish_is_refused_and_its_result_retained`
Expected: 8 fail: a late `finish` is refused (`finish requires an active attempt`, `delivery finish refused`), and no `owner_result` event exists.

- [ ] **Step 3: Implement**

Implement the interfaces and the five behaviours above. Docstrings are written from the implemented code; `command_finish`'s docstring gains what a finish after a reap now does.

- [ ] **Step 4: Verify**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_attempt_custody.py`
Expected: `OK`, 19 tests.

Run, one command each, timeout 1800 s: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/<file>` for `test_workflow_state.py`, `test_delivery_workflow.py`, `test_delivered_control.py`, `test_host_admission.py`, `test_attempt_migration.py`.
Expected: `OK` for each, with no edit to a pre-existing test in this task.

Run: `git diff --stat 5bd914e199f3e57217780596beefe69838f4efd4..HEAD -- home/common/agent-skills/scripts/workflow_delivery.py home/common/agent-skills/scripts/workflow_delivery_build.py home/common/agent-skills/scripts/workflow_delivery_wire.py home/common/agent-skills/scripts/delivery_model`
Expected: empty output.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/scripts/workflow-state.py python/agent_tools/attempt_store.py home/common/agent-skills/tests/test_attempt_custody.py
launch-commit … -- -m "feat(workflow-state): record, adopt and retain late owner results (#338)"
```
