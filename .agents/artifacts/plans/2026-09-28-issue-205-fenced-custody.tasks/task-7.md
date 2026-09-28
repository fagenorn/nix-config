# Task 7: Reap, synthesized stop and late owner-result intake

**Files:**
- Modify: `python/agent_tools/transaction_core.py` (the two store methods)
- Modify: `python/agent_tools/transaction_history.py` (the event keys, validator rules
  and three pure history queries, per D33)
- Modify: `tests/test_transaction_custody.py` (append classes before `if __name__`)

**Interfaces:**
- Consumes (Tasks 3–6): `LeaseAuthority.span_lapsed(fence, now)`,
  `self._check_custody`, `self._transaction_locked`, `self._now()`, `self._leases`,
  `_validate_state`; from `transaction_history` (Task 6): `format_at`, `snapshot`,
  `bound_path`, `is_subject_path`, `require_custody_shape` (its fence-shape part),
  `validate_state`'s per-type dispatch, `_check_envelope` (history-internal),
  `EVENT_KEYS`; `record_evidence`, `advance(..., custody=)`, `StaleCustody`,
  `CustodyMisbound`, `TransitionRefused`, `StateInvalid`; slice 1's strict-JSON
  round-trip rule used by `_require_creatable` for `subject`; test helpers
  `CustodyCase` (with `assertRuleRefuses`), `span`, `history`, `plain`, `TTL`, `KEYS`,
  `PATH`, `serialize`.
- Produces: `TransactionStore.reap(self, transaction_id: str, *, reason: str) -> Transaction`
  and `TransactionStore.record_owner_result(self, transaction_id: str, *, executor_id: str, subject_path: str, fence: Mapping[str, Mapping[str, Any]], result: dict) -> Transaction`.
  Task 8's reaper step calls `reap` exactly so.
- Produces (`agent_tools.transaction_history`, pure, no I/O):
  `reaped(document: dict, at: str, reason: str) -> dict` — a deep-copied candidate with
  the lapse, the stop and (outside a parking) the park appended, `parked_from`, `state`,
  `custody` and `revision` updated; `span_issued(events, executor_id: str, fence) -> bool`;
  `superseded_stop(events, fence) -> int | None`.

**Invariants:**
- `reap` takes no custody and never refuses a held, absent or terminal custody: with no
  open span, a terminal, or a live span (per `span_lapsed` at one `now`) it writes nothing
  and returns the unchanged snapshot (D17).
- On a lapsed open span one write appends `lease_lapse_detected {fence, executor_id}`,
  `stop_synthesized {fence, executor_id, reason}` and — only when the state is not a
  parking — `transitioned` to `attention_required` with the given `reason` and
  `external_state: "unknown"`; `custody` becomes `None`. Lease records are not touched
  (an expired or re-held record is already inert, D24).
- `record_owner_result` is authentic iff some `lease_acquired`/`lease_reacquired` event
  carries that `executor_id` and an equal fence, else `StaleCustody`; then the path must
  equal the bound one, else `CustodyMisbound`; a terminal refuses with
  `TransitionRefused` first (D18, D27). It appends one `owner_result {executor_id, fence,
  custody, supersedes, result}` where `custody` is `"current"` iff the projection holds
  that executor and fence and `span_lapsed` is false, else `"stale"`; `supersedes` is
  the `seq` of the latest `stop_synthesized` with an equal fence, else `None`. It never
  changes `state`, `parked_from` or `custody`, and never touches lease records.
- Validator: `stop_synthesized` directly follows a `lease_lapse_detected` of the same
  fence and executor, with a non-empty `reason`; `owner_result` names a span's executor
  and fence, `custody` is `current`/`stale`, `supersedes` is `None` or the `seq` of an
  earlier `stop_synthesized` with an equal fence, and `result` is a JSON object (D30).
- Shape errors (`StateInvalid`, before any lock): empty `reason`/`executor_id`; bad
  `subject_path` per Task 3; malformed fence; `result` not a `dict` that survives the
  strict JSON round trip slice 1 applies to `subject`.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_transaction_custody.py`:

```python
class ReapTest(CustodyCase):
    def proving(self):
        transaction_id = self.new()
        custody = self.acquire(transaction_id)
        for target in ("awaiting_verification", "ready", "publishing", "published",
                       "proving"):
            self.store.advance(transaction_id, target, reason="r", external_state="known",
                               custody=custody)
        return transaction_id, custody

    def test_reap_writes_nothing_without_a_lapse(self):
        bare = self.new("bare", keys=("project:bare",))
        transaction_id, _ = self.proving()
        before = self.files()
        for candidate in (bare, transaction_id):
            self.assertEqual(self.store.reap(candidate, reason="sweep"),
                             self.store.load(candidate))
        self.assertEqual(self.files(), before)

    def test_reaping_a_lapse_parks_with_a_synthesized_stop_once(self):
        transaction_id, custody = self.proving()
        self.clock.advance(TTL)
        reaped = self.store.reap(transaction_id, reason="lease expired")
        tail = [dict(e) for e in reaped.events[-3:]]
        self.assertEqual([e["type"] for e in tail],
                         ["lease_lapse_detected", "stop_synthesized", "transitioned"])
        self.assertEqual((tail[1]["fence"], tail[1]["executor_id"], tail[1]["reason"]),
                         (plain(custody.fence), "exec-a", "lease expired"))
        self.assertEqual((tail[2]["to"], tail[2]["external_state"], tail[2]["reason"]),
                         ("attention_required", "unknown", "lease expired"))
        self.assertEqual((reaped.state, reaped.parked_from, reaped.custody),
                         ("attention_required", "proving", None))
        before = self.files()
        self.assertEqual(self.store.reap(transaction_id, reason="again"), reaped)
        self.assertEqual(self.files(), before)
        for call in (
                lambda: self.store.advance(transaction_id, "proving", reason="r",
                                           custody=custody),
                lambda: self.store.record_evidence(custody, evidence_id="x",
                                                   form="snapshot", reference="r")):
            self.assertRefusedUnchanged(StaleCustody, call)
        fresh = self.acquire(transaction_id, executor="exec-b")
        for call in (
                lambda: self.store.advance(transaction_id, "proving", reason="r",
                                           custody=custody),
                lambda: self.store.record_evidence(custody, evidence_id="x",
                                                   form="snapshot", reference="r"),
                lambda: self.store.renew(custody),
                lambda: self.store.release(custody)):
            self.assertRefusedUnchanged(StaleCustody, call)  # epoch 1 after epoch 2
        self.assertEqual(self.store.advance(transaction_id, "proving", reason="r",
                                            custody=fresh).state, "proving")

    def test_reaping_a_parked_lapse_adds_no_transition(self):
        transaction_id = self.new()
        custody = self.acquire(transaction_id)
        self.store.advance(transaction_id, "attention_required", reason="r", custody=custody)
        self.clock.advance(TTL)
        reaped = self.store.reap(transaction_id, reason="lease expired")
        self.assertEqual([e["type"] for e in reaped.events[-2:]],
                         ["lease_lapse_detected", "stop_synthesized"])
        self.assertEqual(reaped.state, "attention_required")


class OwnerResultTest(ReapTest):
    def late(self, transaction_id, custody, **overrides):
        arguments = {"executor_id": custody.executor_id,
                     "subject_path": custody.subject_path, "fence": plain(custody.fence),
                     "result": {"status": "done", "items": [1, 2]}, **overrides}
        return self.store.record_owner_result(transaction_id, **arguments)

    def test_a_late_authentic_result_is_kept_beside_the_synthesized_stop(self):
        transaction_id, custody = self.proving()
        self.clock.advance(TTL)
        reaped = self.store.reap(transaction_id, reason="lease expired")
        stop = next(e for e in reaped.events if e["type"] == "stop_synthesized")
        after = self.late(transaction_id, custody)
        event = dict(after.events[-1])
        self.assertEqual(event, {
            "seq": reaped.revision + 1, "type": "owner_result", "at": event["at"],
            "executor_id": "exec-a", "fence": plain(custody.fence), "custody": "stale",
            "supersedes": stop["seq"], "result": {"status": "done", "items": [1, 2]}})
        self.assertEqual((after.state, after.parked_from, after.custody),
                         (reaped.state, reaped.parked_from, None))
        self.assertIn("stop_synthesized", [e["type"] for e in after.events])
        self.assertRefusedUnchanged(StaleCustody, lambda: self.store.advance(
            transaction_id, "proving", reason="r", custody=custody))

    def test_a_result_under_live_custody_is_current(self):
        transaction_id, custody = self.proving()
        event = self.late(transaction_id, custody).events[-1]
        self.assertEqual((event["custody"], event["supersedes"]), ("current", None))
        self.assertEqual(self.store.load(transaction_id).custody, custody)

    def test_unissued_misbound_or_malformed_results_are_refused_before_any_write(self):
        transaction_id, custody = self.proving()
        bumped = {k: {**v, "epoch": v["epoch"] + 1} for k, v in plain(custody.fence).items()}
        for overrides in ({"fence": bumped}, {"executor_id": "exec-z"}):
            with self.subTest(overrides=overrides):
                self.assertRefusedUnchanged(
                    StaleCustody, lambda: self.late(transaction_id, custody, **overrides))
        self.assertRefusedUnchanged(CustodyMisbound, lambda: self.late(
            transaction_id, custody, subject_path="/work/beta"))
        for result in (["not", "an", "object"], {"x": float("nan")}, {1: "int key"},
                       {"t": (1, 2)}):
            with self.subTest(result=result):
                self.assertRefusedUnchanged(
                    StateInvalid, lambda: self.late(transaction_id, custody, result=result))

    def test_a_terminal_transaction_refuses_late_results(self):
        transaction_id, custody = self.proving()
        self.store.advance(transaction_id, "succeeded", reason="r", external_state="known",
                           custody=custody)
        self.assertRefusedUnchanged(TransitionRefused,
                                    lambda: self.late(transaction_id, custody))

    def test_hand_edited_stop_and_result_histories_fail_the_named_rule(self):
        transaction_id, custody = self.proving()
        self.clock.advance(TTL)
        self.store.reap(transaction_id, reason="lease expired")
        self.late(transaction_id, custody)
        base = self.state_doc(transaction_id)
        _, acquired, *middle, lapse, stop, park, result = base["events"]
        early = [acquired, *middle]
        unlapsed = history(base, *early, stop, park, result, custody=span(acquired))
        unlapsed["events"][-1]["supersedes"] = unlapsed["events"][-3]["seq"]
        cases = {
            "stop without lapse": (unlapsed, "does not follow a lease_lapse_detected"),
            "result names no span": (
                history(base, *early, lapse, stop, park,
                        {**result, "executor_id": "exec-z"}, custody=None),
                "names no custody span"),
            "supersedes no stop": (
                history(base, *early, lapse, stop, park,
                        {**result, "supersedes": park["seq"]}, custody=None),
                "supersedes names no earlier stop_synthesized"),
            "unknown custody word": (
                history(base, *early, lapse, stop, park, {**result, "custody": "maybe"},
                        custody=None), "custody is not current or stale"),
        }
        for name, (document, fragment) in cases.items():
            with self.subTest(case=name):
                self.assertRuleRefuses(transaction_id, copy.deepcopy(document), fragment)
```

`OwnerResultTest` subclasses `ReapTest` only to reuse `proving`; it therefore also
re-runs `ReapTest`'s three tests, which is intended and harmless.

- [ ] **Step 2: Run the tests and watch them fail**

Run: `PYTHONPATH=python python3 -m unittest tests/test_transaction_custody.py 2>&1 | tail -3`
Expected: FAIL — `AttributeError: 'TransactionStore' object has no attribute 'reap'`.

- [ ] **Step 3: Write the minimal implementation**

1. In `transaction_history`: add `stop_synthesized {seq, type, at, fence, executor_id,
   reason}` and `owner_result {seq, type, at, executor_id, fence, custody, supersedes,
   result}` to `EVENT_KEYS`, dispatch both in `validate_state` (envelope via
   `_check_envelope`) with the validator rules above; neither opens or closes a span.
   Add `reaped`, `span_issued` and `superseded_stop` per the Interfaces.
2. `reap` (core): `reason` shape → `_transaction_locked` → `prior` → return
   `snapshot(prior)` when terminal or `prior["custody"] is None` → `now` → return
   unchanged unless `span_lapsed(fence, now)` → `reaped(prior, format_at(now), reason)`
   (every event stamped with that `at`; the park updates `parked_from` exactly as
   `advance` does) → `_validate_state` → `atomic_write`. No lease lock.
3. `record_owner_result` (core): shapes → lock → `prior` → terminal refusal →
   `span_issued` → `bound_path` → `now` → `custody` word and `superseded_stop` → append
   → `_validate_state` → write. The `result` stored is a deep copy.
4. Validator messages contain the fragments the tests assert: `does not follow a
   lease_lapse_detected`, `names no custody span`, `supersedes names no earlier
   stop_synthesized`, `custody is not current or stale`.
5. Docstrings of both methods describe these rules as implemented. Extend
   `transaction_history`'s module docstring with one clause for the reap composition and
   owner-result queries — TODO: word it from the implemented functions.

- [ ] **Step 4: Verify**

Run: `PYTHONPATH=python python3 -m unittest tests/test_transaction_custody.py 2>&1 | tail -3`
Expected: `OK` (Task 5's custody-file count + 11 test runs: 3 in `ReapTest`, 3 inherited
plus 5 in `OwnerResultTest`).

Run: `just agent-workflow-tests 2>&1 | tail -3` — Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/transaction_core.py python/agent_tools/transaction_history.py \
  tests/test_transaction_custody.py
git commit -m "feat(transaction-core): reap lapsed custody and take late owner results (#205)"
```

- [ ] **Step 6: Check the review budget** (after the commit)

Run:

```bash
for f in python/agent_tools/transaction_core.py python/agent_tools/transaction_history.py \
    tests/test_transaction_custody.py; do
  printf '%s %s\n' "$(git diff -U10 66ccba5844eab2af9c68962c54a28f874585ee80 HEAD -- "$f" | wc -c)" "$f"
done
```

Expected (estimates: core ~54000, history ~29000, custody tests ~43000): every file
≤ 55000. A miss means the task is not done: move more of the pure composition into
`transaction_history` (never a `TransactionStore` method) and re-run this step.
