# Task 1: Own every external result before validation and recording

**Files:**
- Modify: `python/agent_tools/transaction_core.py`
- Modify/Test: `tests/test_transaction_custody.py`
- Modify/Test: `tests/test_transaction_invocation.py`
- Modify/Test: `tests/test_transaction_proof.py`
- Modify/Test: `tests/test_transaction_recovery.py`

Read the [plan root](../2026-09-29-issue-229-result-ownership.md) for Global
Constraints and the [spec](../../specs/2026-09-29-issue-229-result-ownership-design.md)
for D1–D3 before editing. Work in the issue checkout. Keep tool output bounded:
targeted searches and reads, quiet tests, long logs in the platform temp directory,
and only failure lines or final summaries in reports.

**Interfaces:**
- Consumes `TransactionStore.inspect_action(custody, *, name, parameters, effect) -> Transaction`, `invoke_action` with the same signature, `collect_obligation(custody, *, obligation_id, observer) -> Transaction`, `verify_anchors(custody, *, observer) -> Transaction`, and `begin_recovery(custody, *, grant_id, observer) -> Transaction`.
- Consumes existing `inspect_result_violation(result: Any) -> str | None`, `invoke_result_violation(result: Any) -> str | None`, `observation_violation(result: Any, entry: Mapping) -> str | None`, and `check_result_violation(result: Any) -> str | None` without moving/changing them.
- Produces a private module function `_capture_result(result: Any, validator: Callable[[Any], str | None], *, where: str) -> dict`; it returns the owned validated dictionary or raises `EffectResultInvalid(f"{where}: {violation}")`.
- Extends the existing test-only `FakeClock` with `on_next_read(callback)`; callback runs once before its next returned clock value, leaving `advance(ms)` and normal readings unchanged.

**Invariants:**
- Per D1, each external return is copied before validation; all later reads use that same captured value.
- Per D2, invocation's capture/validation finishes before inspection begins; an invalid invocation prevents inspection. Post-invoke inspection is captured independently.
- Standalone inspection preserves `_refuse_in_flight` and its latest-event comparison; invoke preserves durable intent and history validation; proof preserves obligation-sensitive validation, clock/admission/cohort checks and interval opening; recovery preserves revision comparison and its no-request fast path.
- Per D3, returned and freshly loaded snapshots retain each original field and derived action status; a successful attempt has a matching returned event and closing inspection.

- [ ] **Step 1: Add the two baseline-failing invocation regressions.**

Append this complete class beside `InvokeActionTest` in
`tests/test_transaction_invocation.py`, using its existing imports and fixtures:

```python
class InvocationOwnershipTest(InvokeCase):
    def retained_invocation(self, mutate):
        class Retaining(FakeEffect):
            def invoke(self, request):
                self.reply = super().invoke(request)
                self.reply["reference"] = "invoke:original"
                return self.reply

            def inspect(self, request):
                mutate(self.reply)
                result = super().inspect(request)
                result["reference"] = "inspect:own"
                return result

        self.inspect()
        after = self.invoke(Retaining(self.world))
        loaded = TransactionStore(self.root).load(self.transaction_id)
        for transaction in (after, loaded):
            with self.subTest(snapshot=transaction.revision):
                events = [e for e in transaction.events
                          if e.get("action_id") == self.act()]
                self.assertEqual([e["type"] for e in events[-3:]],
                                 ["invocation_intended", "invocation_returned",
                                  "action_inspected"])
                intended, returned, inspected = events[-3:]
                self.assertEqual((intended["attempt"], returned["attempt"]), (1, 1))
                self.assertEqual(
                    {key: returned[key] for key in ("result", "error_class", "reference")},
                    {"result": "accepted", "error_class": None,
                     "reference": "invoke:original"})
                self.assertEqual((inspected["outcome"], inspected["reference"]),
                                 ("satisfied", "inspect:own"))
                [action] = transaction.actions
                self.assertEqual((action["status"], action["attempts"],
                                  action["last_error_class"]), ("satisfied", 1, None))

    def test_inspect_cannot_rewrite_the_invocation_return(self):
        self.retained_invocation(lambda reply: reply.update(
            result="rejected", error_class="provider_throttled", reference="inspect:changed"))

    def test_inspect_cannot_clear_the_invocation_return(self):
        self.retained_invocation(lambda reply: reply.clear())
```

- [ ] **Step 2: Demonstrate both regressions against the unchanged core.**

Run from this checkout:

```sh
PYTHONPATH=python python3 -m unittest -q tests.test_transaction_invocation.InvocationOwnershipTest
```

Required observation at implementation base `3bf2936`: the rewrite case fails
because recorded invocation fields are rejected/provider_throttled/inspect:changed;
the clear case errors with `KeyError` while recording. This command must be
nonzero. Save its failure summary before editing core. A missing test/import
error does not count. Both failures arise inside the operation, not from mutation
after it returned.

- [ ] **Step 3: Add the deterministic single-return regression fixture.**

Replace only the existing `FakeClock` class in
`tests/test_transaction_custody.py` with this complete test fixture; all existing
callers retain their behavior unless they explicitly arm it:

```python
class FakeClock:
    def __init__(self, now=T0):
        self.now = now
        self.next_read = None

    def on_next_read(self, callback):
        self.next_read = callback

    def __call__(self):
        callback, self.next_read = self.next_read, None
        if callback is not None:
            callback()
        return self.now

    def advance(self, ms):
        self.now += ms
```

- [ ] **Step 4: Add both inspection ownership tests.**

Append these complete classes in `tests/test_transaction_invocation.py`:

```python
class InspectionOwnershipTest(ProtocolCase):
    def test_standalone_inspection_keeps_its_returned_fields(self):
        clock = self.clock

        class Retaining(FakeEffect):
            def inspect(self, request):
                reply = super().inspect(request)
                reply["reference"] = "inspect:original"
                clock.on_next_read(lambda: reply.update(
                    outcome="satisfied", reference="inspect:changed"))
                return reply

        before = clock.now
        after = self.inspect(Retaining(self.world))
        self.assertEqual(clock.now, before)
        for transaction in (after, TransactionStore(self.root).load(self.transaction_id)):
            event = transaction.events[-1]
            self.assertEqual((event["type"], event["outcome"], event["reference"]),
                             ("action_inspected", "absent", "inspect:original"))
            [action] = transaction.actions
            self.assertEqual((action["status"], action["attempts"]), ("absent", 0))


class PostInvokeInspectionOwnershipTest(InvokeCase):
    def test_post_invoke_inspection_keeps_its_returned_fields(self):
        clock = self.clock

        class Retaining(FakeEffect):
            def inspect(self, request):
                reply = super().inspect(request)
                reply["reference"] = "inspect:original"
                clock.on_next_read(lambda: reply.update(
                    outcome="absent", reference="inspect:changed"))
                return reply

        self.inspect()
        before = clock.now
        after = self.invoke(Retaining(self.world))
        self.assertEqual(clock.now, before)
        for transaction in (after, TransactionStore(self.root).load(self.transaction_id)):
            returned, inspected = transaction.events[-2:]
            self.assertEqual((returned["type"], returned["result"], returned["error_class"],
                              returned["reference"]),
                             ("invocation_returned", "accepted", None, "call:1"))
            self.assertEqual((inspected["type"], inspected["outcome"], inspected["reference"]),
                             ("action_inspected", "satisfied", "inspect:original"))
            [action] = transaction.actions
            self.assertEqual((action["status"], action["attempts"]), ("satisfied", 1))
```

- [ ] **Step 5: Add proof ownership coverage.**

Add `TransactionStore` to the existing core imports in
`tests/test_transaction_proof.py`, then append:

```python
class ProofOwnershipTest(ProofCase):
    def test_collection_keeps_the_observers_returned_fields(self):
        class Retaining(Observer):
            def observe(self, request):
                reply = super().observe(request)
                reply["reference"] = "proof:original"
                self.clock.on_next_read(lambda: reply.update(
                    outcome="unsatisfied", reason="subject_mismatch", reference="proof:changed"))
                return reply

        self.proving()
        before = self.clock.now
        after = self.collect(self.pub, Retaining(self.clock))
        self.assertEqual(self.clock.now, before)
        for transaction in (after, TransactionStore(self.root).load(self.transaction_id)):
            event = transaction.events[-1]
            self.assertEqual((event["type"], event["obligation_id"], event["outcome"],
                              event["reason"], event["reference"], event["latency_ms"]),
                             ("obligation_observed", self.pub, "satisfied", "ok",
                              "proof:original", 0))
            [entry] = [e for e in transaction.proof["obligations"]
                       if e["obligation_id"] == self.pub]
            self.assertEqual((entry["observations"], entry["latest_outcome"],
                              entry["latest_admissible"]), (1, "satisfied", True))
```

- [ ] **Step 6: Preserve successful multi-result recovery ownership.**

Add `TransactionStore` to the existing core imports in
`tests/test_transaction_recovery.py`, then append this class, reusing the existing
`Reusing` observer and two-restorable-unit declaration:

```python
class RecoveryOwnershipTest(RecoveryCase):
    def test_anchor_reuse_retains_each_units_reference(self):
        self.start_with(TWO_RESTORABLE, key="two", keys=("key:two",))
        self.to("awaiting_verification", "ready")
        after = self.verify(Reusing("satisfied", "satisfied"))
        expected = [{"unit": self.act("start", n=2), "reference": "ref-1"},
                    {"unit": self.act("pin", n=3), "reference": "ref-2"}]
        for transaction in (after, TransactionStore(self.root).load(self.transaction_id)):
            self.assertEqual(transaction.state, "ready")
            event = transaction.events[-1]
            self.assertEqual((event["type"], event["anchors"]),
                             ("anchors_verified", expected))
        self.assertEqual(self.to("publishing").state, "publishing")

    def test_compatibility_reuse_retains_each_units_reference(self):
        self.start_with(TWO_RESTORABLE, key="two", keys=("key:two",))
        self.parked(pin="diverged")
        self.grant()
        after = self.begin(checker=Reusing("satisfied", "satisfied"))
        expected = [{"unit": self.act("start", n=2), "reference": "ref-1"},
                    {"unit": self.act("pin", n=3), "reference": "ref-2"}]
        for transaction in (after, TransactionStore(self.root).load(self.transaction_id)):
            self.assertEqual(transaction.state, "recovering")
            event = transaction.events[-2]
            self.assertEqual((event["type"], event["checks"]),
                             ("recovery_started", expected))
```

- [ ] **Step 7: Run all new tests before the fix.**

```sh
PYTHONPATH=python python3 -m unittest -q \
  tests.test_transaction_invocation.InvocationOwnershipTest \
  tests.test_transaction_invocation.InspectionOwnershipTest \
  tests.test_transaction_invocation.PostInvokeInspectionOwnershipTest \
  tests.test_transaction_proof.ProofOwnershipTest \
  tests.test_transaction_recovery.RecoveryOwnershipTest
```

Expect seven tests: five failing/error cases from aliasing and two passing
recovery cases. Check the reasons individually; fixture errors are not ownership
evidence. The already-passing recovery cases protect the existing behavior
during migration to the shared helper.

- [ ] **Step 8: Implement the private intake sequence and integrate each path.**

Implement the interface declared above using imports already available in
`transaction_core.py`. Per D1, its ordered operations are: deep-copy the raw
return; call the supplied validator with the copy; raise the unchanged
contextual `EffectResultInvalid` on a non-`None` violation; return that copy.
Do not retain the original result for later field reads. Do not add a registry,
schema conversion, wrapper, fallback, or exception catch.

Wrap the external expression directly at each intake site:

| Location | Validator supplied | `where` value |
|---|---|---|
| `inspect_action`, `effect.inspect(request)` | `inspect_result_violation` | `f"{custody.transaction_id}: inspect_action"` |
| `invoke_action`, `effect.invoke(request)` | `invoke_result_violation` | `f"{transaction_id}: invoke_action"` |
| `invoke_action`, following `effect.inspect(request)` | `inspect_result_violation` | `f"{transaction_id}: invoke_action"` |
| `collect_obligation`, `observer.observe(request)` | `lambda captured: observation_violation(captured, entry)` | `f"{transaction_id}: collect_obligation"` |
| `_observed`, each loop's `observer.observe(request)` | `check_result_violation` | `f"{transaction_id}: {operation}"` |

Remove only the replaced inline copy/validation/error blocks. Invocation's two
capture calls are sequential, so the first exception prevents the second call.
Recovery appends each captured result before observing the next request. Keep
the existing second fenced holds and all their checks; change no event
construction, pre-call writes, public signature, or pure validation policy.
Any edited comments/docstrings must describe the resulting live behavior;
derive wording from the code rather than copying plan narration into source.

- [ ] **Step 9: Verify the fix and compatibility.**

Repeat Step 7: all seven tests must pass, including both issue-mandated failures
from Step 2. Then run the focused existing suite:

```sh
PYTHONPATH=python python3 -m unittest -q \
  tests.test_transaction_custody tests.test_transaction_invocation \
  tests.test_transaction_proof tests.test_transaction_recovery \
  tests.test_transaction_core_sweep
```

It must pass malformed invoke/inspect/proof/recovery shapes, adapter exceptions,
stale custody, changed action/recovery history, proof intervals and cohorts,
recovery reused-object refusals, asserted scenario sweep, and neutrality checks.
Do not weaken these existing tests. Confirm the invalid invocation still skips
inspection and leaves only durable intent; malformed post-invoke inspection
still leaves an open attempt, with the same error contexts.

Run retained verification command ID `agent-workflow-tests` (`just
agent-workflow-tests`) and command ID `nix-build` (`just build`) from the owner
checkout. Capture long output outside the checkout and report exit status plus
the final summary; on failure read the targeted error before proceeding. A
passing test run before core changes is baseline evidence, not final validation.

Run the scoped whitespace gate:

```sh
git diff --check -- python/agent_tools/transaction_core.py tests/test_transaction_custody.py tests/test_transaction_invocation.py tests/test_transaction_proof.py tests/test_transaction_recovery.py
```

- [ ] **Step 10: Commit the implementation and evidence-bearing tests.**

```sh
git add python/agent_tools/transaction_core.py tests/test_transaction_custody.py tests/test_transaction_invocation.py tests/test_transaction_proof.py tests/test_transaction_recovery.py
git commit -S -m "fix(transaction): own external results at intake (#229)" -m "Co-Authored-By: Codex <noreply@openai.com>"
```

Keep signing enabled. Report baseline-failure evidence and final validation
summaries to the task owner. The owner retains lifecycle, review, and shipping.
