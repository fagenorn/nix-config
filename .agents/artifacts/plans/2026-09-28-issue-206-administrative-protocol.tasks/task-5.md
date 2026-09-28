# Task 5: Quiesce exception, terminal refusal and refusal precedence

**Files:**
- Modify: `python/agent_tools/transaction_invocation.py`
- Modify: `python/agent_tools/transaction_history.py` (terminal-transition validator rule)
- Modify: `python/agent_tools/transaction_core.py` (`renew`, `_advance_locked`, docstrings)
- Modify: `tests/test_transaction_invocation.py` (append before the `if __name__` block;
  add `import dataclasses`, `PARKED_CUSTODY_WINDOW_MS` and `REFUSAL_REASONS` to the header
  imports)

**Interfaces:**
- Consumes (Tasks 2–4): `fold_actions`, `status`, `InvokeCase` (with `wait`, `refused`,
  `to`, `inspect`, `invoke`, `publishing`), `FakeEffect`, `Crash`, `renumbered`,
  `refused_error`; core `PARKED_CUSTODY_WINDOW_MS`, `parked_since`, `REFUSAL_REASONS`.
- Produces (`transaction_invocation`):
  - `observed(actions: dict[str, ActionFold]) -> bool` — some action's `status` is `open`
    or `in_progress` (per D9).
  - `unresolved(actions: dict[str, ActionFold]) -> ActionFold | None` — the first action,
    in declaration order, whose `status` is `open`, `in_progress` or `unknown`.

**Invariants:**
- `renew` quiesces a parked transaction past `PARKED_CUSTODY_WINDOW_MS` only when
  `observed(fold_actions(events))` is false; otherwise it takes the ordinary renewal path
  (extend inside the margin, no event, no `state.json` write). `unknown` and `diverged`
  do not hold custody (per D9).
- `advance` into a terminal is `TransitionRefused` while `unresolved(...)` names an action,
  checked after every existing lifecycle refusal and before any write; the message names
  the transaction id, the action id and its status. `external_state="known"` does not
  override it (per D9).
- The history validator enforces the same rule on stored history (per D20): in the
  `transitioned` arm, after `_fold_transitioned`, a transition into a terminal while
  `unresolved(actions)` names an action is `StateInvalid` with a message containing
  `"over unresolved action"`, the action id and its status. `advance` and the validator
  share the one `unresolved` predicate.
- Refusal precedence for both operations (per D7, #205 D27): argument shape
  (`StateInvalid`) before any lock, even when the lock is held elsewhere; a terminal →
  `TransitionRefused` before the fenced check; the fenced check before any
  `InvocationRefused`.

- [ ] **Step 1: Write the failing tests**

```python
class LifecycleTest(InvokeCase):
    def fresh(self, key):
        self.transaction_id = self.new(key, keys=(f"key:{key}",))
        self.custody = self.acquire(self.transaction_id)
        self.to("attention_required")

    def test_an_open_attempt_holds_parked_custody_past_the_window(self):
        self.inspect()
        with self.assertRaises(Crash):
            self.invoke(self.effect(crash="before"))
        self.to("attention_required")
        self.wait(PARKED_CUSTODY_WINDOW_MS + 1)
        after = self.store.renew(self.custody)
        self.assertEqual(after.custody, self.custody)
        self.assertNotIn("lease_released", [e["type"] for e in after.events])

    def test_only_an_in_progress_inspection_holds_parked_custody(self):
        for outcome, held in (("in_progress", True), ("unknown", False),
                              ("diverged", False)):
            with self.subTest(outcome=outcome):
                self.fresh(outcome)
                self.inspect(self.effect(inspect_outcome=outcome))
                self.wait(PARKED_CUSTODY_WINDOW_MS)
                self.clock.advance(1)
                after = self.store.renew(self.custody)
                self.assertEqual(after.custody is not None, held)

    def test_a_terminal_is_refused_over_unresolved_external_state(self):
        for outcome, allowed in (("in_progress", False), ("unknown", False),
                                 ("diverged", True), ("absent", True), ("satisfied", True)):
            with self.subTest(outcome=outcome):
                self.fresh(outcome)
                self.inspect(self.effect(inspect_outcome=outcome))
                if allowed:
                    self.assertEqual(self.to("abandoned").state, "abandoned")
                else:
                    error = self.assertRefusedUnchanged(TransitionRefused,
                                                        lambda: self.to("abandoned"))
                    self.assertIn(self.act(), str(error))
                    self.assertIn(outcome, str(error))

    def test_an_open_attempt_blocks_a_terminal(self):
        self.inspect()
        with self.assertRaises(Crash):
            self.invoke(self.effect(crash="before"))
        self.to("attention_required")
        error = self.assertRefusedUnchanged(TransitionRefused, lambda: self.to("failed"))
        self.assertIn("open", str(error))

    def test_refusals_keep_their_precedence(self):
        self.inspect()
        with open(self.root / self.transaction_id / "lock", "r+") as holder:
            fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertRefusedUnchanged(StateInvalid, lambda: self.store.invoke_action(
                self.custody, name="", parameters={}, effect=self.effect()))
        self.to("attention_required")
        forged = dataclasses.replace(self.custody, executor_id="someone-else")
        self.assertRefusedUnchanged(StaleCustody, lambda: self.invoke(
            self.effect(during=self.fail), custody=forged))
        self.refused("state_not_effectful", lambda: self.invoke(self.effect(during=self.fail)))
        self.to("abandoned")
        for call in (lambda: self.invoke(self.effect(during=self.fail), custody=forged),
                     lambda: self.inspect(self.effect(during=self.fail), custody=forged)):
            self.assertRefusedUnchanged(TransitionRefused, call)

    def test_a_hand_edited_terminal_over_an_unresolved_action_is_refused(self):
        for status in ("open", "in_progress", "unknown"):
            with self.subTest(status=status):
                if status == "open":
                    self.transaction_id = self.new(status, keys=(f"key:{status}",))
                    self.custody = self.acquire(self.transaction_id)
                    self.publishing()
                    self.inspect()
                    with self.assertRaises(Crash):
                        self.invoke(self.effect(crash="before"))
                    self.to("attention_required")
                else:
                    self.fresh(status)
                    self.inspect(self.effect(inspect_outcome=status))
                document = self.state_doc(self.transaction_id)
                document["events"].append({
                    "type": "transitioned", "at": document["events"][-1]["at"],
                    "from": "attention_required", "to": "abandoned", "reason": "r",
                    "external_state": "known"})
                self.assertRuleRefuses(self.transaction_id, renumbered(document),
                                       "over unresolved action")


# Every reason some `refused(...)` call in this file asserts; pinned to the vocabulary.
OBSERVED_REASONS = {"inspection_required", "not_absent", "not_retryable", "budget_exhausted",
                    "window_closed", "state_not_effectful", "attempt_in_flight"}


class RefusalVocabularyTest(unittest.TestCase):
    def test_the_refusal_reasons_are_exactly_the_observed_ones(self):
        self.assertEqual(set(REFUSAL_REASONS), OBSERVED_REASONS)
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `PYTHONPATH=python python3 -m unittest tests/test_transaction_invocation.py 2>&1 | tail -3`
Expected: FAIL — the parked open attempt quiesces inside `wait` (the next `renew` is
`StaleCustody`), and the unresolved terminals are admitted.

- [ ] **Step 3: Implement** `observed` and `unresolved`, the `renew` condition, the
  `_advance_locked` refusal and the history validator rule. Rewrite `renew`'s and
  `advance`'s docstrings from the implemented code so they name the quiesce exception and
  the terminal refusal, name the terminal rule in `validate_state`'s docstring, finish the
  core module docstring's slice-3 sentence, and update `transaction_invocation`'s module
  docstring (custody and lifecycle predicates) — all from the implemented code.

- [ ] **Step 4: Verify**

Run: `PYTHONPATH=python python3 -m unittest tests/test_transaction_invocation.py tests/test_transaction_core.py tests/test_transaction_custody.py tests/test_transaction_core_sweep.py 2>&1 | tail -3`
Expected: `OK` (the #205 quiesce tests still pass: a history with no action is not
observed).

Run (each pinned reason is really asserted somewhere; exits 1 otherwise):

```bash
for r in inspection_required not_absent not_retryable budget_exhausted window_closed \
    state_not_effectful attempt_in_flight; do
  grep -q "refused(\"$r\"" tests/test_transaction_invocation.py || exit 1
done
```

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/transaction_invocation.py python/agent_tools/transaction_core.py \
  python/agent_tools/transaction_history.py tests/test_transaction_invocation.py
git commit -m "feat(transaction-core): hold custody over observed calls and refuse unresolved terminals (#206)"
```

Decisions: per D7, D9, D20, D21.
