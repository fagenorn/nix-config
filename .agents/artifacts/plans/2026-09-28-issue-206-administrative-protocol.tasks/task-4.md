# Task 4: Crash seam — interrupted attempts, `attempt_in_flight` and the second-write re-check

**Files:**
- Modify: `python/agent_tools/transaction_invocation.py`
- Modify: `python/agent_tools/transaction_core.py`
- Modify: `tests/test_transaction_invocation.py` (append before the `if __name__` block)

**Interfaces:**
- Consumes (Tasks 1–3): `ActionFold`, `retry_safe`, `action_event_violation`,
  `fold_actions`, `TransactionStore.inspect_action`, `invoke_action`; test fixtures
  `InvokeCase`, `FakeEffect(crash=...)`, `Crash`, `renumbered`.
- Produces: no new public name. `retry_safe(entry)` becomes: the latest attempt has no
  return (it was **interrupted**), or its return is not `accepted` and its class is in
  `RETRY_SAFE_CLASSES` (per D6). `inspect_action` gains the `attempt_in_flight` refusal at
  both lock holds (per D14, D16).

**Invariants:**
- First lock hold of `inspect_action`: when the action's latest attempt is open and its
  `intent_fence` equals the held fence, raise `InvocationRefused` reason
  `attempt_in_flight` before any effect call (per D14), raised through `refused_error`
  (its message names the transaction id and the action id).
- Second lock hold of `inspect_action` (per D16): re-fold; when the entry's attempt count
  (0 without an entry) differs from the count read at the first hold, or the entry is open
  under the held fence, raise `InvocationRefused` reason `attempt_in_flight` with nothing
  written. An inspection made before another attempt began is never recorded. This is a
  post-call refusal: the effect's `inspect` has already run (per D19).
- Validator rule (per D14): an `action_inspected` that closes an open attempt with no
  recorded return and carries the intent's fence is refused with a message containing
  `"closes a return-less attempt under its intent's fence"`. A return-less attempt closed
  under a newer fence loads, and its `absent` closing inspection admits the retry.
- Attempt numbers keep increasing across a crash and a reacquisition (per D4).

- [ ] **Step 1: Write the failing tests**

```python
class CrashSeamTest(InvokeCase):
    def crash(self, where):
        self.inspect()
        with self.assertRaises(Crash):
            self.invoke(self.effect(crash=where))

    def reacquire(self):
        self.store.release(self.custody)
        self.custody = self.acquire(self.transaction_id)

    def test_a_crash_before_the_call_leaves_an_open_intent_and_resumes_as_attempt_2(self):
        self.crash("before")
        self.assertEqual(self.state_doc(self.transaction_id)["events"][-1]["type"],
                         "invocation_intended")
        self.assertEqual((self.world.invokes, self.world.applied), ({}, {}))
        self.assertEqual(self.view()["status"], "open")
        self.refused("inspection_required", lambda: self.invoke(self.effect(during=self.fail)))
        self.refused("attempt_in_flight", lambda: self.inspect(self.effect(during=self.fail)))
        self.reacquire()
        self.assertEqual(self.inspect().events[-1]["outcome"], "absent")
        self.assertTrue(self.view()["retry_eligible"])
        self.invoke()
        self.assertEqual((self.attempts(), self.world.invokes), ([1, 2], {self.act(): 1}))
        self.assertEqual(self.view()["status"], "satisfied")

    def test_an_effect_that_applied_then_raised_is_settled_without_a_second_call(self):
        self.crash("after")
        self.refused("attempt_in_flight", lambda: self.inspect(self.effect(during=self.fail)))
        self.reacquire()
        self.assertEqual(self.inspect().events[-1]["outcome"], "satisfied")
        self.invoke(self.effect(during=self.fail))
        self.assertEqual((self.attempts(), self.world.invokes), ([1], {self.act(): 1}))

    def test_an_observation_made_before_a_newer_attempt_is_not_recorded(self):
        self.inspect()
        with self.assertRaises(InvocationRefused) as caught:
            self.inspect(self.effect(inspect_outcome="absent", during=lambda: self.invoke()))
        self.assertEqual(caught.exception.reason, "attempt_in_flight")
        self.assertEqual(self.store.load(self.transaction_id).events[-1]["outcome"],
                         "satisfied")
        self.assertEqual((self.view()["status"], self.world.invokes),
                         ("satisfied", {self.act(): 1}))

    def test_a_return_less_attempt_closed_under_its_own_fence_is_refused(self):
        self.crash("before")
        document = self.state_doc(self.transaction_id)
        intent = document["events"][-1]
        document["events"].append({
            "type": "action_inspected", "at": intent["at"], "action_id": self.act(),
            "outcome": "absent", "reference": "r", "fence": intent["fence"]})
        self.assertRuleRefuses(self.transaction_id, renumbered(document),
                               "closes a return-less attempt under its intent's fence")
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `PYTHONPATH=python python3 -m unittest tests/test_transaction_invocation.py 2>&1 | tail -3`
Expected: FAIL — the `attempt_in_flight` refusals are not raised, the resumed retry is
refused `not_retryable`, and the stale observation is recorded.

- [ ] **Step 3: Implement** the three invariants in `transaction_invocation` (the
  `retry_safe` widening and the validator rule) and `transaction_core` (the two
  `inspect_action` checks, reading the attempt count at the first hold). Rewrite
  `inspect_action`'s docstring from the implemented code to name both refusals and say
  the second follows the read-only `inspect` call and records nothing.

- [ ] **Step 4: Verify**

Run: `PYTHONPATH=python python3 -m unittest tests/test_transaction_invocation.py tests/test_transaction_core.py tests/test_transaction_custody.py tests/test_transaction_core_sweep.py 2>&1 | tail -3`
Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/transaction_invocation.py python/agent_tools/transaction_core.py \
  tests/test_transaction_invocation.py
git commit -m "feat(transaction-core): close interrupted attempts only under a new custody span (#206)"
```

- [ ] **Step 6: Check the review budget** (after the commit)

```bash
base=ce33847bd60d4dc40a8a241d9f35b2bbdc9aaae1; fail=0
for f in python/agent_tools/transaction_*.py tests/test_transaction_invocation.py; do
  n=$(git diff -U10 "$base" HEAD -- "$f" | wc -c); printf '%s %s\n' "$n" "$f"
  [ "$n" -lt 65536 ] || fail=1
done
[ "$(wc -c < python/agent_tools/transaction_core.py)" -le 55000 ] || fail=1
test "$fail" = 0
```

Expected: exit 0. A miss means the task is not done.

Decisions: per D3, D4, D6, D14, D16, D19.
