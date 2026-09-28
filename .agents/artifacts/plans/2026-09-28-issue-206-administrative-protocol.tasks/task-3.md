# Task 3: `invoke_action` — intent, return, post-inspection and the retry budget

**Files:**
- Modify: `python/agent_tools/transaction_invocation.py`
- Modify: `python/agent_tools/transaction_core.py`
- Modify: `tests/test_transaction_invocation.py` (append before the `if __name__` block)

**Interfaces:**
- Consumes (Tasks 1–2): `ActionFold`, `ACTION_EVENT_KEYS`, `action_event_violation`,
  `apply_action_event`, `fold_actions`, `retry_safe`, `effect_request`, the constants;
  core `_action_arguments`, `_append`, `_fenced`; test fixtures `ProtocolCase`,
  `FakeEffect`, `FakeWorld`, `renumbered`, `OTHER_FENCE`.
- Produces (`transaction_invocation`):
  - `ACTION_EVENT_KEYS` gains `invocation_intended`: envelope ∪ {`action_id`, `attempt`,
    `fence`} and `invocation_returned`: envelope ∪ {`action_id`, `attempt`, `result`,
    `error_class`, `reference`, `fence`}.
  - `invoke_result_violation(result: Any) -> str | None` — None only for a `dict` with key
    set exactly {`result`, `error_class`, `reference`}, result in `RESULTS`, `error_class`
    None exactly when `accepted` and otherwise in `ERROR_CLASSES`, reference a non-empty
    `str` (per D11).
  - `satisfied(entry: ActionFold | None) -> bool` — entry exists, is not open, and its
    latest inspection's outcome is `satisfied`.
  - `refusal(entry: ActionFold | None, *, held_fence: dict, now_ms: int) -> str | None` —
    rules 1–4 of the spec in order (per D5, D6): `inspection_required` when the entry is
    None, open, has no inspection, or its latest inspection's fence ≠ `held_fence`;
    `not_absent` when that outcome is not `absent`; with `n = attempts + 1`:
    `not_retryable` when `n > 1` and not `retry_safe(entry)`; `budget_exhausted` when
    `n > MAX_ATTEMPTS`; `window_closed` when `n > 1` and `now_ms - first_failure_ms >
    RETRY_WINDOW_MS` (inclusive bound).
- Produces (core): `TransactionStore.invoke_action(custody: Custody, *, name: str,
  parameters: dict, effect: Any) -> Transaction`; core re-imports `EFFECT_STATES`.

**Invariants:**
- `apply_action_event`: `invocation_intended` sets `attempts = attempt`, `open = True`,
  `intent_fence = fence`, `returned = None`; `invocation_returned` sets `returned` to
  `{result, error_class, reference}`.
- Validator rules this task adds, checked after the shared id and fence rules, each
  message containing the quoted fragment (`n` the event's attempt, `m` the folded one):
  intent — a non-int or bool attempt, or `n != m + 1` → `"attempt {n!r} does not follow
  attempt {m}"`; `n > MAX_ATTEMPTS` → `"attempt {n} exceeds 3"`; state not in
  `EFFECT_STATES` → `"invocation_intended sits outside publishing and activating"` (per
  D17); open, no inspection, or latest inspection not `absent` or under another fence →
  `"does not follow an absent inspection under its fence"`; `n > 1` and not
  `retry_safe` → `"retry follows an attempt that is not retry-safe"`. Return — not open →
  `"invocation_returned follows no open attempt"`; `n != m` → `"attempt does not name the
  open attempt"`; `returned` already set → `"attempt {m} already returned"`; fence ≠
  `intent_fence` → `"fence does not equal its intent's"`; result → `"result is not accepted,
  rejected or unknown"`; class → `"error_class does not match the result"`; reference →
  `"reference is not a non-empty string"`.
- `invoke_action` (per D3, D5–D8), after `_action_arguments`: under `_fenced(...,
  writes=True)` — state not in `EFFECT_STATES` → `InvocationRefused` reason
  `state_not_effectful`; `satisfied(entry)` → return `snapshot(prior)` with no write and
  no call; `refusal(...)` → `InvocationRefused` with that reason; else `_append` one
  `invocation_intended` (attempt `n`, held fence) and build the request with `attempt = n`.
  Out of the lock: `effect.invoke(request)` then `effect.inspect(request)`, each result
  shape-checked (`EffectResultInvalid`, the intent stays open). Under a second `_fenced`:
  one `_append` of `invocation_returned` (the result's three fields, held fence) and the
  closing `action_inspected`. Every refusal message names the transaction id, the action id
  and the reason; nothing is caught.
- Interim gap (closed by Task 4): an attempt with no return is not retry-safe, and
  `inspect_action` may still close an attempt open under the held fence.

- [ ] **Step 1: Write the failing tests**

```python
THROTTLED = ("rejected", "provider_throttled")


class InvokeCase(ProtocolCase):
    def setUp(self):
        super().setUp()
        self.publishing()

    def invoke(self, effect=None, *, custody=None, name=None):
        return self.store.invoke_action(
            custody or self.custody, name=name or self.NAME, parameters=self.PARAMETERS,
            effect=effect or self.effect())

    def refused(self, reason, call):
        error = self.assertRefusedUnchanged(InvocationRefused, call)
        self.assertEqual(error.reason, reason)
        self.assertIn(self.transaction_id, str(error))
        return error

    def views(self):
        return {e["name"]: dict(e) for e in self.store.load(self.transaction_id).actions}

    def attempts(self, name=None):
        identity = self.act(name)
        return [e["attempt"] for e in self.store.load(self.transaction_id).events
                if e["type"] == "invocation_intended" and e["action_id"] == identity]

    def wait(self, ms):
        while ms:
            step = min(ms, 400_000)
            self.clock.advance(step)
            ms -= step
            self.store.renew(self.custody)


class InvokeActionTest(InvokeCase):
    def test_an_absent_action_is_invoked_once_then_inspected(self):
        self.inspect()
        after = self.invoke()
        fence, at = plain(self.custody.fence), "2027-01-15T08:00:00.000Z"
        self.assertEqual([dict(e) for e in after.events[7:]], [
            {"seq": 8, "type": "invocation_intended", "at": at, "action_id": self.act(),
             "attempt": 1, "fence": fence},
            {"seq": 9, "type": "invocation_returned", "at": at, "action_id": self.act(),
             "attempt": 1, "result": "accepted", "error_class": None,
             "reference": "call:1", "fence": fence},
            {"seq": 10, "type": "action_inspected", "at": at, "action_id": self.act(),
             "outcome": "satisfied", "reference": "seen:1:1", "fence": fence}])
        self.assertEqual((self.world.invokes, self.world.applied),
                         ({self.act(): 1}, {self.act(): 1}))
        self.assertEqual((self.view()["status"], self.view()["attempts"]), ("satisfied", 1))

    def test_a_satisfied_action_is_never_invoked_again(self):
        self.inspect()
        self.invoke()
        before = self.files()
        self.assertEqual(self.invoke(self.effect(during=self.fail)).revision, 10)
        self.assertEqual(self.files(), before)
        self.assertEqual(self.world.invokes, {self.act(): 1})

    def test_an_inspection_reading_satisfied_settles_the_action_without_a_call(self):
        self.world.applied[self.act()] = 0
        self.inspect()
        self.invoke(self.effect(during=self.fail))
        self.assertEqual(self.world.invokes, {})
        self.assertEqual(self.action_types(), ["action_declared", "action_inspected"])

    def test_a_blind_invoke_is_refused_before_any_call(self):
        self.refused("inspection_required", lambda: self.invoke(self.effect(during=self.fail)))
        self.assertEqual(self.world.invokes, {})

    def test_an_inspection_that_is_not_absent_refuses_the_call(self):
        for outcome in ("in_progress", "diverged", "unknown"):
            with self.subTest(outcome=outcome):
                self.inspect(self.effect(inspect_outcome=outcome))
                self.refused("not_absent", lambda: self.invoke(self.effect(during=self.fail)))

    def test_only_publishing_and_activating_may_invoke(self):
        self.inspect()
        self.to("attention_required")
        self.refused("state_not_effectful", lambda: self.invoke(self.effect(during=self.fail)))
        self.to("publishing", "published")
        self.refused("state_not_effectful", lambda: self.invoke(self.effect(during=self.fail)))
        self.to("activating")
        self.invoke()
        self.assertEqual(self.world.invokes, {self.act(): 1})

    def test_a_throttled_attempt_is_retried_once(self):
        self.inspect()
        self.invoke(self.effect(results=[THROTTLED]))
        self.assertEqual(self.view(), {
            "action_id": self.act(), "name": "build", "attempts": 1, "status": "absent",
            "last_error_class": "provider_throttled", "retry_eligible": True,
            "retry_deadline_at": "2027-01-15T08:15:00.000Z"})
        self.clock.advance(30_000)
        self.invoke()
        self.assertEqual(self.view(), {
            "action_id": self.act(), "name": "build", "attempts": 2, "status": "satisfied",
            "last_error_class": None, "retry_eligible": False,
            "retry_deadline_at": "2027-01-15T08:15:00.000Z"})
        self.assertEqual((self.attempts(), self.world.invokes), ([1, 2], {self.act(): 2}))

    def test_a_fourth_try_is_refused_budget_exhausted(self):
        self.inspect()
        throttled = self.effect(results=[THROTTLED] * 3)
        for _ in range(MAX_ATTEMPTS):
            self.invoke(throttled)
        self.assertFalse(self.view()["retry_eligible"])
        self.refused("budget_exhausted", lambda: self.invoke(self.effect(during=self.fail)))
        self.assertEqual(self.world.invokes, {self.act(): 3})

    def test_the_window_admits_exactly_900_000_ms_and_refuses_one_more(self):
        for name in ("late", "exact"):
            self.inspect(name=name)
            self.invoke(self.effect(results=[THROTTLED]), name=name)
            self.clock.advance(1)
        self.wait(RETRY_WINDOW_MS - 1)
        self.refused("window_closed",
                     lambda: self.invoke(self.effect(during=self.fail), name="late"))
        self.invoke(name="exact")
        self.assertEqual(self.views()["exact"]["status"], "satisfied")

    def test_a_non_retry_safe_class_or_an_accepted_absent_attempt_is_not_retryable(self):
        for name, result in (("denied", ("rejected", "invalid_input")),
                             ("vanished", ("accepted", None))):
            with self.subTest(name=name):
                self.inspect(name=name)
                self.invoke(self.effect(results=[result], inspect_outcome="absent"), name=name)
                self.assertFalse(self.views()[name]["retry_eligible"])
                self.refused("not_retryable",
                             lambda: self.invoke(self.effect(during=self.fail), name=name))

    def test_an_inspection_from_an_earlier_custody_span_licenses_no_call(self):
        self.inspect()
        self.invoke(self.effect(results=[THROTTLED]))
        self.store.release(self.custody)
        self.custody = self.acquire(self.transaction_id)
        self.refused("inspection_required", lambda: self.invoke(self.effect(during=self.fail)))
        self.assertEqual(self.inspect().events[-1]["reference"], "seen:1:2")
        self.invoke()
        self.assertEqual((self.attempts(), self.world.invokes), ([1, 2], {self.act(): 2}))

    def test_a_malformed_invoke_result_leaves_the_intent_open(self):
        class Returning(FakeEffect):
            def invoke(self, request):
                return self.results[0]

        for index, result in enumerate((
                None, {"result": "accepted", "error_class": None},
                {"result": "done", "error_class": None, "reference": "r"},
                {"result": "accepted", "error_class": "invalid_input", "reference": "r"},
                {"result": "rejected", "error_class": None, "reference": "r"},
                {"result": "rejected", "error_class": "flaky", "reference": "r"},
                {"result": "accepted", "error_class": None, "reference": ""})):
            with self.subTest(result=result):
                name = f"bad-{index}"
                self.inspect(name=name)
                with self.assertRaises(EffectResultInvalid):
                    self.invoke(Returning(self.world, results=[result]), name=name)
                self.assertEqual(self.views()[name]["status"], "open")
                self.assertEqual(self.store.load(self.transaction_id).events[-1]["type"],
                                 "invocation_intended")

    def test_a_lease_lapse_during_the_call_leaves_the_intent_open(self):
        self.inspect()
        with self.assertRaises(StaleCustody):
            self.invoke(self.effect(during=lambda: self.clock.advance(TTL)))
        self.assertEqual(self.action_types()[-1], "invocation_intended")
        self.assertEqual(self.world.invokes, {self.act(): 1})

    def test_hand_edited_attempt_histories_fail_the_named_rule(self):
        self.inspect()
        self.invoke(self.effect(results=[THROTTLED]))
        self.invoke()
        good = self.state_doc(self.transaction_id)
        parked = {"type": "transitioned", "at": good["events"][7]["at"],
                  "from": "publishing", "to": "attention_required", "reason": "r",
                  "external_state": None}

        def edit(change):
            document = copy.deepcopy(good)
            change(document["events"])
            return renumbered(document)

        cases = {
            "attempt 3 does not follow attempt 1": lambda ev: ev[10].update(attempt=3),
            "does not follow an absent inspection under its fence": lambda ev: ev.pop(9),
            "invocation_intended sits outside publishing and activating":
                lambda ev: ev.insert(7, dict(parked)),
            "retry follows an attempt that is not retry-safe":
                lambda ev: ev[8].update(error_class="invalid_input"),
            "invocation_returned follows no open attempt":
                lambda ev: ev.insert(10, copy.deepcopy(ev[8])),
            "attempt 1 already returned": lambda ev: ev.insert(9, copy.deepcopy(ev[8])),
            "attempt does not name the open attempt": lambda ev: ev[8].update(attempt=2),
            "result is not accepted, rejected or unknown":
                lambda ev: ev[8].update(result="done"),
            "error_class does not match the result":
                lambda ev: ev[11].update(error_class="provider_throttled"),
            "is not the closed invocation_intended event": lambda ev: ev[7].update(extra=1),
        }
        for fragment, change in cases.items():
            with self.subTest(fragment=fragment):
                self.assertRuleRefuses(self.transaction_id, edit(change), fragment)

    def test_a_fourth_attempt_in_history_is_refused(self):
        self.inspect()
        throttled = self.effect(results=[THROTTLED] * 3)
        for _ in range(MAX_ATTEMPTS):
            self.invoke(throttled)
        document = self.state_doc(self.transaction_id)
        document["events"].append({**document["events"][-3], "attempt": 4})
        self.assertRuleRefuses(self.transaction_id, renumbered(document),
                               "attempt 4 exceeds 3")
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `PYTHONPATH=python python3 -m unittest tests/test_transaction_invocation.py 2>&1 | tail -3`
Expected: FAIL — `AttributeError: ... no attribute 'invoke_action'`.

- [ ] **Step 3: Implement** the names under **Produces** with the rules under
  **Invariants**. `refusal` is the one home of rules 1–4; the validator reuses
  `retry_safe` and does not re-implement rule 4. Write `invoke_action`'s docstring from the
  implemented code: the refusal order, the satisfied no-op, the two writes around the
  unlocked calls, and that effect exceptions propagate with the intent open. Extend the
  core module docstring with one sentence naming the two protocol operations.

- [ ] **Step 4: Verify**

Run: `PYTHONPATH=python python3 -m unittest tests/test_transaction_invocation.py tests/test_transaction_core.py tests/test_transaction_custody.py tests/test_transaction_core_sweep.py 2>&1 | tail -3`
Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/transaction_invocation.py python/agent_tools/transaction_core.py \
  tests/test_transaction_invocation.py
git commit -m "feat(transaction-core): invoke actions behind a durable intent and retry budget (#206)"
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

Expected: exit 0 (estimates: core ~42000 bytes, test file diff ~35000). A miss means the
task is not done: move pure logic from the core into `transaction_invocation`.

Decisions: per D3, D5, D6, D7, D8, D10, D11, D17.
