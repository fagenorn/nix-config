# Task 3: The receipt's truth — postconditions, stops, owner results, evaluations

**Files:**
- Modify: `python/agent_tools/transaction_receipt.py` (`terminal_receipt` gains four keys)
- Modify: `tests/test_transaction_receipt.py` (the key-set line of `assertSealed`, and
  the new tests)

**Interfaces:**
- Consumes (Task 2): `terminal_receipt`, `ReceiptStore`, `read_receipt`, the `Sealed`
  mixin and `ENVELOPE`. From `transaction_proof`: `evaluate(plan, events, cutoff_ms)`.
  From `transaction_invocation`: `fold_actions`, `status`. From `transaction_storage`:
  `parse_at`. Tests use `CustodyCase`, `AUTHORITY`, `PATH`, `TTL`, `plain`, `serialize`
  (custody tests), `FakeEffect`, `FakeWorld` (invocation tests), `Observer` and
  `CohortCase` (proof tests) and `inert_recovery` (recovery-plan tests).
- Produces: the receipt keys `postconditions`, `stops`, `owner_results` and `evaluations`,
  and the test constant `TRUTH`. Task 6 reads `postconditions` in the sweep.

**Invariants:**
- `postconditions` has one entry per `proof_plan["units"]` entry, in plan order:
  `{"unit": action_id, "name", "phase", "status", "observed", "effected"}`. `status` is
  `status(fold)` of that action, or None when the action has no event. `observed` is the
  latest `action_inspected` of that action whose outcome is `satisfied`, as `{"seq",
  "at", "reference", "fence"}`, or None. `effected` is `fold.attempts > 0`, false with no
  fold (per D4, D20; #208 D19).
- `stops` has one entry per `stop_synthesized`, in seq order: `{"seq", "executor_id",
  "fence", "reason", "superseded_by"}`. `superseded_by` is the seq of the first
  `owner_result` whose `supersedes` equals that stop's seq, else None (per D13).
- `owner_results` has one entry per `owner_result`, in seq order: `{"seq",
  "executor_id", "fence", "custody", "supersedes", "result_digest":
  telemetry_digest(result)}`. The result body never enters the receipt (per D3).
- `evaluations` has one entry per `proof_plan["obligations"]` entry, in plan order:
  `{"obligation_id", "evaluation", "reason", "evidence_id"}`. The pair comes from
  `evaluate(proof_plan, events, parse_at(sealed_at))`. `evidence_id` is that
  obligation's latest `obligation_observed` `evidence_id`, else None (per D20).
- Every value is deep-copied from the events, so a receipt never aliases the document.
- The receipt module docstring gains one sentence per new key, written from the code.

- [ ] **Step 1: Write the failing tests.** In `tests/test_transaction_receipt.py`, add
  `TRUTH = {"postconditions", "stops", "owner_results", "evaluations"}` below `ENVELOPE`.
  In `assertSealed`, change `self.assertEqual(set(receipt), ENVELOPE)` to
  `self.assertEqual(set(receipt), ENVELOPE | TRUTH)`. Extend the imports:

```python
from .test_transaction_custody import AUTHORITY, KEYS, PATH, SUBJECT, TTL, CustodyCase, plain, serialize
from .test_transaction_proof import CohortCase, Observer
from .test_transaction_recovery_plan import inert_recovery
```

  Then append:

```python
DC = {"basis": "deterministic", "max_collection_latency_ms": 30_000,
      "predicates": ["publication_visible", "running_subject_identity"]}
DELIVERY = {"collectors": {"c": DC}, "obligations": [], "units": [
    {"name": "deliver_implementation", "parameters": {"n": 1}, "phase": "publication",
     "collector": "c"},
    {"name": "merge_change", "parameters": {"n": 2}, "phase": "activation", "collector": "c"},
    {"name": "close_issue", "parameters": {"n": 3}, "phase": "activation", "collector": "c"},
    {"name": "clean_up", "parameters": {"n": 4}, "phase": "activation", "collector": "c"}]}


class SucceededTruthTest(Sealed, CohortCase):
    def test_success_records_the_final_evaluations_with_their_evidence(self):
        self.ready()
        self.start()
        self.members()
        after = self.settle()
        receipt = self.assertSealed(after, "succeeded")
        latest = {e["obligation_id"]: e["evidence_id"] for e in after.events
                  if e["type"] == "obligation_observed"}
        expected = [{"obligation_id": i, "evaluation": "accepted", "reason": "ok",
                     "evidence_id": latest[i]} for i in self.ids[:2] + ["migrated", "health",
                                                                        "smoke"]]
        expected += [{"obligation_id": "vibe", "evaluation": "indeterminate",
                      "reason": "evidence_missing", "evidence_id": None},
                     {"obligation_id": "uptime", "evaluation": "unsupported",
                      "reason": "predicate_unsupported", "evidence_id": None}]
        self.assertEqual(sorted(receipt["evaluations"], key=lambda e: e["obligation_id"]),
                         sorted(expected, key=lambda e: e["obligation_id"]))
        self.assertEqual([e["obligation_id"] for e in receipt["evaluations"]], self.ids)
        self.assertEqual((receipt["stops"], receipt["owner_results"]), ([], []))


class DeliveryCase(Sealed, CustodyCase):
    """A delivery-shaped declaration: one publication unit and three activation units."""

    def setUp(self):
        super().setUp()
        self.world = FakeWorld()
        self.transaction_id = self.store.create(
            "delivery", SUBJECT, concurrency_keys=KEYS, proof=DELIVERY,
            recovery=inert_recovery(DELIVERY), authority_class=AUTHORITY).transaction_id
        self.custody = self.acquire(self.transaction_id)
        self.plan = self.store.load(self.transaction_id).proof_plan

    def to(self, *targets):
        for target in targets:
            after = self.store.advance(self.transaction_id, target, reason="r",
                                       external_state="known", custody=self.custody)
        return after

    def unit(self, name, externally_satisfied=False):
        parameters = next(u["parameters"] for u in DELIVERY["units"] if u["name"] == name)
        if externally_satisfied:
            return self.store.inspect_action(
                self.custody, name=name, parameters=parameters,
                effect=FakeEffect(self.world, inspect_outcome="satisfied"))
        for operation in (self.store.inspect_action, self.store.invoke_action):
            after = operation(self.custody, name=name, parameters=parameters,
                              effect=FakeEffect(self.world))
        return after

    def observed(self, activation, externally=()):
        self.to("awaiting_verification", "ready", "publishing")
        self.unit("deliver_implementation")
        self.to("published", "activating")
        for name in activation:
            self.unit(name, name in externally)
        return self.to("proving")

    def collect_stale(self):
        for entry in self.store.load(self.transaction_id).proof["obligations"]:
            if entry["latest_admissible"] is not True:
                self.store.collect_obligation(self.custody, obligation_id=entry["obligation_id"],
                                              observer=Observer(self.clock))

    def sealed(self):
        """Collect, open one cohort, collect its members and settle into `succeeded`."""
        self.collect_stale()
        started = self.store.start_cohort(self.custody)
        for member in started.proof_plan["cohort"]["members"]:
            self.store.collect_obligation(self.custody, obligation_id=member,
                                          observer=Observer(self.clock))
        before = self.state_doc(self.transaction_id)["events"]
        after = self.store.settle_proof(self.custody)
        final = self.state_doc(self.transaction_id)["events"]
        self.assertEqual([serialize(e) for e in final[:len(before)]],
                         [serialize(e) for e in before])
        return self.assertSealed(after, "succeeded"), after

    def assertPostconditions(self, receipt, after, externally=()):
        units = self.plan["units"]
        self.assertEqual([p["unit"] for p in receipt["postconditions"]],
                         [u["action_id"] for u in units])
        for entry, unit in zip(receipt["postconditions"], units):
            seen = [dict(e) for e in after.events if e["type"] == "action_inspected"
                    and e["action_id"] == unit["action_id"] and e["outcome"] == "satisfied"][-1]
            self.assertEqual(entry, {
                "unit": unit["action_id"], "name": unit["name"], "phase": unit["phase"],
                "status": "satisfied",
                "observed": {"seq": seen["seq"], "at": seen["at"],
                             "reference": seen["reference"], "fence": seen["fence"]},
                "effected": unit["name"] not in externally})


class PostconditionTest(DeliveryCase):
    def test_merge_before_close_records_every_unit_observed_and_effected(self):
        self.observed(["merge_change", "close_issue", "clean_up"])
        receipt, after = self.sealed()
        self.assertPostconditions(receipt, after)
        self.assertEqual(len(self.receipt_files()), 1)

    def test_close_before_merge_records_the_closed_target_observed_but_not_effected(self):
        self.observed(["close_issue", "merge_change", "clean_up"], externally={"close_issue"})
        receipt, after = self.sealed()
        self.assertPostconditions(receipt, after, externally={"close_issue"})
        close = next(p for p in receipt["postconditions"] if p["name"] == "close_issue")
        merge = next(p for p in receipt["postconditions"] if p["name"] == "merge_change")
        self.assertLess(close["observed"]["seq"], merge["observed"]["seq"])
        self.assertEqual(len(self.receipt_files()), 1)

    def test_evidence_voided_by_a_lapse_is_recollected_and_cited(self):
        self.observed(["merge_change", "close_issue", "clean_up"])
        self.collect_stale()
        self.clock.advance(TTL)
        self.store.reap(self.transaction_id, reason="executor lost")
        lapse = self.store.load(self.transaction_id).revision
        self.custody = self.acquire(self.transaction_id, executor="exec-b")
        self.to("proving")
        receipt, after = self.sealed()
        self.assertPostconditions(receipt, after)
        observed = {e["evidence_id"]: e["seq"] for e in after.events
                    if e["type"] == "obligation_observed"}
        snapshots = [o["obligation_id"] for o in self.plan["obligations"]
                     if o["form"] == "snapshot"]
        self.assertTrue(snapshots)
        for entry in receipt["evaluations"]:
            self.assertEqual(entry["evaluation"], "accepted")
            if entry["obligation_id"] in snapshots:
                self.assertGreater(observed[entry["evidence_id"]], lapse)
        [stop] = receipt["stops"]
        self.assertEqual((stop["executor_id"], stop["superseded_by"]), ("exec-a", None))
        self.assertEqual(len(self.receipt_files()), 1)

    def test_a_late_owner_result_and_the_stop_it_supersedes_link_both_ways(self):
        self.observed(["merge_change", "close_issue", "clean_up"])
        self.collect_stale()
        lost = self.custody
        self.clock.advance(TTL)
        self.store.reap(self.transaction_id, reason="executor lost")
        self.custody = self.acquire(self.transaction_id, executor="exec-b")
        late = self.store.record_owner_result(
            self.transaction_id, executor_id="exec-a", subject_path=PATH,
            fence=plain(lost.fence), result={"done": True})
        self.to("proving")
        receipt, after = self.sealed()
        stop = next(dict(e) for e in after.events if e["type"] == "stop_synthesized")
        result = dict(late.events[-1])
        self.assertEqual(receipt["stops"], [{
            "seq": stop["seq"], "executor_id": "exec-a", "fence": stop["fence"],
            "reason": "executor lost", "superseded_by": result["seq"]}])
        self.assertEqual(receipt["owner_results"], [{
            "seq": result["seq"], "executor_id": "exec-a", "fence": result["fence"],
            "custody": "stale", "supersedes": stop["seq"],
            "result_digest": telemetry_digest({"done": True})}])
        self.assertNotIn('"done"', self.receipt_files()[0].read_text())

    def test_a_unit_with_no_event_records_nulls(self):
        after = self.store.advance(self.transaction_id, "abandoned", reason="r",
                                   external_state="known", custody=self.custody)
        receipt = self.assertSealed(after, "abandoned")
        self.assertEqual(receipt["postconditions"], [
            {"unit": u["action_id"], "name": u["name"], "phase": u["phase"], "status": None,
             "observed": None, "effected": False} for u in self.plan["units"]])
        self.assertEqual([e["evidence_id"] for e in receipt["evaluations"]],
                         [None] * len(self.plan["obligations"]))
```

- [ ] **Step 2: Run the tests and watch them fail.**
  Run: `PYTHONPATH=python python3 -m unittest tests/test_transaction_receipt.py 2>&1 | tail -3`.
  Expected: FAILED (the receipt lacks the four keys).

- [ ] **Step 3: Implement** the invariants in `terminal_receipt`, one private builder per
  key. Update the module docstring.

- [ ] **Step 4: Verify.**
  Run the slice unit command with both new test files. Expected: `OK`.

```bash
for key in postconditions stops owner_results evaluations; do
  grep -q "\"$key\"" python/agent_tools/transaction_receipt.py || exit 1
done
```

  Run: `git add -A python tests && just build 2>&1 | tail -3`. Expected: success.

- [ ] **Step 5: Commit.** Stage exactly this task's **Files**, then:

```bash
git commit -m "feat(transaction-core): record postconditions, stops and evaluations in the receipt (#209)"
```

- [ ] **Step 6: Check the review budget** with `FILES="python/agent_tools/transaction_receipt.py tests/test_transaction_receipt.py"`.
  Expected: exit 0.

Decisions: per D3, D4, D13, D16, D20.
