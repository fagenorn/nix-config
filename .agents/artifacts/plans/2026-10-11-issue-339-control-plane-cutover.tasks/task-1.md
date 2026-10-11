# Task 1: Pure rules: delivery subject, journal, remainder subject and the planner's new rows

The pure half of the cutover: a new module for the delivery transaction and remainder custody, and the settle planner's new inputs. No effect is added, and with the new inputs at their defaults every package-2 plan is unchanged. Decisions: D1–D5, D14, D15, D17, D19, D24.

**Files:**
- Create: `python/agent_tools/attempt_delivery.py`, `tests/test_attempt_delivery.py`
- Modify: `python/agent_tools/attempt_custody.py`, `tests/test_attempt_custody.py`
- Modify: `justfile` (`    tests/test_attempt_delivery.py \` after `    tests/test_attempt_custody.py \` in `agent-workflow-tests`)

**Interfaces:**
- Consumes: `attempt_custody` at the base.
- Produces `agent_tools.attempt_delivery`, which imports `attempt_custody` (never the reverse) and nothing from the skill scripts. Constants: `DELIVERY_SCHEMA = "attempt-delivery/v1"`, `DELIVERY_AUTHORITY_CLASS = "attempt-delivery"`, `REMAINDER_SCHEMA = "remainder-custody/v1"`, `POSTCONDITIONS` and `JOURNAL_KINDS` (the tuples the tests pin), `COLLECTOR = "delivery"`, `COLLECTION_LATENCY_MS = 30_000`, `OBSERVED = "observed"`, `RECEIPT_EVIDENCE = "delivery-receipt"`, `HELPER_TTL_MS = 60_000`. Functions:
  - `delivery_key(issue: int, contract_digest: str, ordinal: int) -> str`; `delivery_lease_key(run: str, issue: int) -> str`; `delivery_executor(issue: int) -> str`
  - `delivery_subject(*, run, issue, contract_digest, contract) -> dict`; `delivery_subject_violation(value) -> str | None`
  - `required_postconditions(contract) -> tuple[str, ...]`; `proof_declaration(contract) -> dict`; `delivery_creation_arguments(subject) -> dict`
  - `JournalEntry(evidence_id: str, reference: str)`; `journal_entries(delivery, canonical_text: Callable[[Any], str]) -> tuple[JournalEntry, ...]`; `journaled(transaction, supplements=()) -> frozenset[str]`; `collections(delivery) -> tuple[tuple[str, str], ...]`
  - `remainder_key(run, issue, remainder) -> str`; `remainder_launch_id(issue, remainder, launch) -> str`; `remainder_subject(*, run, issue, remainder, worktree, prior, bound_launch) -> dict`; `remainder_subject_violation(value) -> str | None`; `plan_remainder_migration(document) -> dict[tuple[int, int], int]`
- Produces in `agent_tools.attempt_custody`:
  - `REMAINDER_BLOCKED_ON_VALUES`, `SUSPENSION_CAUSES = BLOCKED_ON_VALUES | REMAINDER_BLOCKED_ON_VALUES`, `CAPACITY_RELEASED = "capacity_released"`, `DELIVERED = "delivered"`, `FORWARD_STATES = ("awaiting_verification", "ready", "publishing", "published", "proving")`; `OPERATIONS` gains `"claim"` and `"seal_succeeded"`; `Operation` gains `reference: str | None = None`
  - `claim_reference(roles: Mapping, route: str) -> str`; `claim_roles(reference: str) -> dict`; `claim_id(executor_id: str, epoch: int) -> str`; `span_epoch(custody) -> int`; `claimed(transaction, executor_id) -> str | None`; `held_claim(admission, holder) -> str | None`; `owner_gone(admission, holder) -> bool`; `gate_open(claims, holder) -> bool`; `seal_executor(launch: str) -> str`
  - `settle_plan(issue_state, attempt, transaction, *, lease, now_ms, latest, report_digest=None, bound=False, current=None, claim=None, owner_gone=False, gate_open=False, delivered=False) -> tuple[Operation, ...]`

**Invariants:**
- `BLOCKED_ON_VALUES`, `OWNER_BLOCKED_ON_VALUES` and `AUTO_RESUMABLE_BLOCKED_ON` keep their members. `owner_unavailable` is a remainder cause: it joins only `SUSPENSION_CAUSES`, which `suspension_reason`, `blocked_on_of` and the planner's suspension row accept (D24).
- `settle_plan` with the five new keywords at their defaults returns what it returns at the base: the 22 existing cases pass unedited.
- Both subjects are closed. A delivery subject's contract names the subject's issue. A remainder subject follows the attempt subject's worktree rule and is created with `attempt_custody.creation_arguments(subject)`.
- `proof_declaration`: one deterministic collector `delivery` with `max_collection_latency_ms` 30000 and, per postcondition the contract marks `required`, in `POSTCONDITIONS` order, one required `event` obligation whose id and predicate are that name and whose semantic is `readiness`. A contract that requires none gets `{"units": [], "obligations": [], "collectors": {}}`.
- `journal_entries`: kind by kind in `JOURNAL_KINDS` order, each list in stored order, `JournalEntry(f"{kind}:{item['id']}", canonical_text(item))`. `stage_facts` and `postconditions` yield nothing.
- `collections`: `(name, observation_id)` per required postcondition; `ValueError` when one is not `observed`.
- A claim reference is `json.dumps({"roles": dict(roles), "route": route}, sort_keys=True, separators=(",", ":"))`. `claimed` answers only for an entry recorded under the fence of that launch's latest span.
- `gate_open` is the base's `refusal_gated` comparison: the block holds a `launch_refused` claim naming `holder`, and some claim released by any other event has a greater `release_seq`.

**Planner rows** (`current` defaults to the attempt form of the launch id):
- `active` with `owner_gone`: close the span (`release`, or `reap("expiry")` when lapsed), then unpark. Never acquire or claim.
- `active` otherwise: the base's `_plan_active`; then, when `claim` is given and the plan ends with `current` holding an unlapsed span that this plan acquired or that carries no claim, a last `Operation("claim", executor_id=current, reference=claim)`.
- `suspended` on `host_capacity` with `gate_open`: when a span is held, the base's `park_with(reason, reason)`; then, when parked, `Operation("unpark", reason="capacity_released")`. No other cause reads `gate_open`.
- `delivered`, transaction terminal: `()`. `delivered`, transaction in `FORWARD_STATES`: exactly `(Operation("seal_succeeded", executor_id=seal_executor(current), reason="delivered"),)`. Without `delivered` both keep the base's answers, `ProjectionMismatch` included.
- `delivered` otherwise: unless the open span's executor is `seal_executor(current)`, reap a lapsed launch span, record an owner verdict this write submits as `_plan_verdict` does and release a live launch span; then `seal_succeeded`. Nothing is acquired, parked or claimed.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_attempt_delivery.py`:

```python
"""Delivery custody's pure rules (#339): the delivery transaction and remainder custody.

Run: just agent-workflow-tests
"""

import json
import unittest
from types import SimpleNamespace

from agent_tools import attempt_custody as ac
from agent_tools import attempt_delivery as ad
from agent_tools.transaction_plan import compile_proof

RUN = "rel_01890a5d-ac96-774b-bcce-b302099a8057"
DIGEST = "sha256:" + "c" * 64


def text(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"


def contract(**obligations):
    marks = {**dict.fromkeys(ad.POSTCONDITIONS, "required"), **obligations}
    return {"issue": 41, "deliverable": {"id": "d", "summary": "é", "obligations": marks}}


def delivery(**obligations):
    post = {name: {"state": "observed", "observation_id": f"sha256:{name}"}
            for name in ad.POSTCONDITIONS}
    for name, mark in obligations.items():
        post[name] = {"state": mark, "observation_id": None}
    return {"contract": contract(**obligations), "contract_digest": DIGEST,
            "postconditions": post, **{kind: [] for kind in ad.JOURNAL_KINDS},
            "delivery_observations": [{"id": "sha256:o2", "n": "é"}, {"id": "sha256:o1"}],
            "authorization_intents": [{"id": "sha256:i1"}], "stage_facts": [{"id": "x"}]}


class DeliveryTransactionTest(unittest.TestCase):
    def test_keys_and_the_closed_subject(self):
        self.assertEqual(ad.delivery_key(41, DIGEST, 2), f"attempt-delivery/v1:41:{DIGEST}:2")
        self.assertEqual(ad.delivery_lease_key(RUN, 41), f"attempt-delivery:{RUN}:41")
        self.assertEqual(ad.delivery_executor(41), "delivery:41")
        subject = ad.delivery_subject(run=RUN, issue=41, contract_digest=DIGEST,
                                      contract=contract())
        self.assertEqual(subject, {"schema": "attempt-delivery/v1", "run": RUN, "issue": 41,
                                   "contract_digest": DIGEST, "contract": contract()})
        for changes in ({"schema": "attempt-custody/v1"}, {"run": "orchestrate-41"},
                        {"issue": 0}, {"contract_digest": ""}, {"contract": {"issue": 42}},
                        {"extra": 1}):
            with self.subTest(changes=changes):
                self.assertIsNotNone(ad.delivery_subject_violation({**subject, **changes}))
        with self.assertRaises(ValueError):
            ad.delivery_subject(run=RUN, issue=42, contract_digest=DIGEST, contract=contract())

    def test_the_proof_plan_is_the_contracts_required_postconditions(self):
        subject = ad.delivery_subject(run=RUN, issue=41, contract_digest=DIGEST,
                                      contract=contract(tracker_closed="not_applicable"))
        arguments = ad.delivery_creation_arguments(subject)
        self.assertEqual((arguments["concurrency_keys"], arguments["authority_class"],
                          arguments["recovery"]),
                         ([f"attempt-delivery:{RUN}:41"], "attempt-delivery",
                          {"effects": {}, "units": []}))
        declared = arguments["proof"]
        self.assertEqual(
            [(o["id"], o["predicate"], o["form"], o["required"], o["semantic"])
             for o in declared["obligations"]],
            [(name, name, "event", True, "readiness")
             for name in ("implementation_delivered", "pr_merged", "cleanup_complete")])
        self.assertEqual(declared["collectors"], {"delivery": {
            "basis": "deterministic", "max_collection_latency_ms": 30_000,
            "predicates": ["implementation_delivered", "pr_merged", "cleanup_complete"]}})
        compile_proof(declared)  # the core accepts it
        none = contract(**dict.fromkeys(ad.POSTCONDITIONS, "not_applicable"))
        self.assertEqual(ad.proof_declaration(none),
                         {"units": [], "obligations": [], "collectors": {}})

    def test_a_complete_delivery_is_collected_from_its_postconditions(self):
        value = delivery(tracker_closed="not_applicable")
        self.assertEqual(ad.collections(value), tuple(
            (name, f"sha256:{name}")
            for name in ("implementation_delivered", "pr_merged", "cleanup_complete")))
        value["postconditions"]["pr_merged"] = {"state": "pending", "observation_id": None}
        with self.assertRaises(ValueError):
            ad.collections(value)

    def test_the_journal_is_every_object_in_kind_then_stored_order(self):
        value = delivery()
        entries = ad.journal_entries(value, text)
        self.assertEqual(entries, (
            ad.JournalEntry("authorization_intents:sha256:i1", '{"id":"sha256:i1"}\n'),
            ad.JournalEntry("delivery_observations:sha256:o2", '{"id":"sha256:o2","n":"é"}\n'),
            ad.JournalEntry("delivery_observations:sha256:o1", '{"id":"sha256:o1"}\n')))
        self.assertEqual(ad.JOURNAL_KINDS, (
            "authorization_intents", "authority_observations", "reevaluation_evidence",
            "authority_evaluation_consumptions", "delivery_observations", "selected_outputs"))
        held = SimpleNamespace(evidence=[{"evidence_id": entries[0].evidence_id}])
        self.assertEqual(ad.journaled(held), {"authorization_intents:sha256:i1"})
        self.assertEqual(ad.journaled(held, [{"reason": entries[2].evidence_id}]),
                         {"authorization_intents:sha256:i1", "delivery_observations:sha256:o1"})


class RemainderSubjectTest(unittest.TestCase):
    def test_key_launch_and_closed_subject(self):
        self.assertEqual(ad.remainder_key(RUN, 41, 2), f"attempt-custody/v1:{RUN}:41:r2")
        self.assertEqual(ad.remainder_launch_id(41, 2, 3), "41:r2:3")
        subject = ad.remainder_subject(run=RUN, issue=41, remainder=2, worktree="/work/wt",
                                       prior=RUN, bound_launch=None)
        self.assertEqual(subject, {
            "schema": "remainder-custody/v1", "run": RUN, "issue": 41, "remainder": 2,
            "worktree": "/work/wt", "prior": RUN, "bound_launch": None})
        self.assertEqual(ac.creation_arguments(subject)["concurrency_keys"],
                         ["attempt-worktree:/work/wt"])
        for changes in ({"schema": "attempt-custody/v1"}, {"run": "x"}, {"remainder": 0},
                        {"worktree": "wt"}, {"prior": "x"}, {"bound_launch": 0},
                        {"attempt": 1}):
            with self.subTest(changes=changes):
                self.assertIsNotNone(ad.remainder_subject_violation({**subject, **changes}))
        with self.assertRaises(ValueError):
            ad.remainder_subject(run=RUN, issue=41, remainder=1, worktree="wt", prior=None,
                                 bound_launch=None)

    def test_the_bind_plans_each_live_remainder_at_its_launch_count(self):
        def remainder(ordinal, state, launches):
            return {"remainder": ordinal, "state": state, "launches": [{}] * launches}

        document = {"issues": {
            "41": {"delivery_remainders": [remainder(1, "failed", 2),
                                           remainder(2, "suspended", 3)]},
            "42": {"delivery_remainders": [remainder(1, "active", 1)]},
            "43": {"delivery_remainders": []}}}
        self.assertEqual(ad.plan_remainder_migration(document), {(41, 2): 3, (42, 1): 1})
```

In `tests/test_attempt_custody.py`, add to `VocabularyTest`:

```python
    def test_the_cutover_vocabulary(self):
        self.assertEqual(ac.SUSPENSION_CAUSES - ac.BLOCKED_ON_VALUES, {"owner_unavailable"})
        self.assertNotIn("owner_unavailable", ac.OWNER_BLOCKED_ON_VALUES)
        self.assertEqual(ac.blocked_on_of(ac.suspension_reason("owner_unavailable")),
                         "owner_unavailable")
        roles = {"worker": 1, "owner": 1}
        reference = ac.claim_reference(roles, "claude-code")
        self.assertEqual(reference, '{"roles":{"owner":1,"worker":1},"route":"claude-code"}')
        self.assertEqual((ac.claim_roles(reference), ac.claim_id("14:r1:2", 3),
                          ac.seal_executor("14:1:3"), ac.seal_executor("14:r2:1")),
                         (roles, "admission-claim:14:r1:2:3", "14:1:seal", "14:r2:seal"))
        with self.assertRaises(ValueError):
            ac.claim_roles('{"roles":{"owner":"1"},"route":"x"}')

        def claim(holder, event=None, seq=None):
            return {"holder": holder, "roles": roles, "release_event": event,
                    "release_seq": seq, "released_at": None if event is None else "t"}

        claims = [claim("12:1:1"), claim("14:1:1", "launch_refused", 2),
                  claim("16:1:1", "owner_unavailable", 1), claim("18:1:1", "launch_refused", 3)]
        block = {"route": "claude-code", "claims": claims}
        self.assertEqual((ac.held_claim(block, "12:1:1"), ac.held_claim(block, "14:1:1"),
                          ac.held_claim(None, "12:1:1")), (reference, None, None))
        self.assertEqual((ac.owner_gone(block, "16:1:1"), ac.owner_gone(block, "12:1:1"),
                          ac.owner_gone(None, "16:1:1")), (True, False, False))
        # Only a later release that is not itself a refusal opens the gate.
        self.assertEqual((ac.gate_open(claims, "14:1:1"), ac.gate_open(claims, "12:1:1")),
                         (False, False))
        claims.append(claim("20:1:1", "finished", 4))
        self.assertEqual((ac.gate_open(claims, "14:1:1"), ac.gate_open(claims, "18:1:1")),
                         (True, True))
```

In `SettlePlanTest`, replace `plan`, add the `claim` branch to `apply` before its `park`/`unpark` branch, and add the seven tests:

```python
    def plan(self, attempt_, *, issue_=None, latest=True, digest=None, bare=False,
             bound=False, **facts):
        transaction = None if bare else self.store.load(self.id)
        lease = None if bare else self.store.inspect_lease(ac.worktree_key(WORKTREE))
        return ac.settle_plan(issue_ or issue(), attempt_, transaction, lease=lease,
                              now_ms=self.now, latest=latest, report_digest=digest,
                              bound=bound, **facts)

            # in `apply`:
            elif op.kind == "claim":
                self.store.record_evidence(
                    held, evidence_id=ac.claim_id(op.executor_id, ac.span_epoch(held)),
                    form="snapshot", reference=op.reference)

    def test_a_claimed_launch_records_its_claim_once_per_span(self):
        claim = ac.claim_reference({"owner": 1}, "claude-code")
        entry = Op("claim", executor_id="14:1:1", reference=claim)
        self.assertEqual(self.plan(attempt("active"), bare=True, claim=claim), (
            Op("create"), Op("acquire", executor_id="14:1:1", ttl_ms=30 * MINUTE), entry))
        custody = self.acquire()
        # An open span the store holds without a claim gets one (the route's first sweep).
        self.assertEqual(self.plan(attempt("active"), claim=claim), (entry,))
        self.store.record_evidence(
            custody, evidence_id=ac.claim_id("14:1:1", ac.span_epoch(custody)),
            form="snapshot", reference=claim)
        self.assertEqual(ac.claimed(self.store.load(self.id), "14:1:1"), claim)
        self.assertEqual(self.plan(attempt("active"), claim=claim), ())
        self.now = T0 + 31 * MINUTE
        resumed = attempt("active", launches=2, deadline="2026-08-13T21:01:00Z")
        # A resume claims its new span, as the plan's last operation.
        self.assertEqual([op.kind for op in self.plan(resumed, claim=claim)],
                         ["reap", "acquire", "unpark", "claim"])
        self.assertEqual(self.plan(resumed, claim=claim)[-1],
                         Op("claim", executor_id="14:1:2", reference=claim))
        # An expired launch that is not reacquired claims nothing.
        self.assertEqual(self.plan(attempt("active"), claim=claim), ())
        self.assertIsNone(ac.claimed(self.store.load(self.id), "14:1:2"))

    def test_an_unavailable_owner_gives_the_span_up(self):
        self.assertEqual(self.plan(attempt("active"), bare=True, owner_gone=True),
                         (Op("create"),))
        self.acquire()
        self.assertEqual(self.plan(attempt("active"), owner_gone=True, claim="c"),
                         (Op("release"),))
        self.now = T0 + 31 * MINUTE
        self.assertEqual(self.plan(attempt("active"), owner_gone=True),
                         (Op("reap", reason="expiry"), Op("unpark", reason="resumed")))

    def test_the_capacity_gate_parks_and_a_release_wakes(self):
        refused = attempt("suspended", blocked_on="host_capacity")
        park, wake = (Op("park", reason="suspended:host_capacity"),
                      Op("unpark", reason="capacity_released"))
        self.acquire()
        # A refusal and a later release in one write keep their order.
        self.assertEqual(self.plan(refused, gate_open=True), (park, Op("release"), wake))
        self.assertEqual(self.plan(refused), (park, Op("release")))
        self.apply(self.plan(refused), None)
        self.assertEqual(self.plan(refused), ())
        self.assertEqual(self.plan(refused, gate_open=True), (wake,))
        self.apply(self.plan(refused, gate_open=True), None)
        self.assertEqual((self.held()[0], self.plan(refused, gate_open=True)), ("created", ()))
        # The gate is read from the block: closed again, the transaction parks again.
        self.assertEqual(self.plan(refused), (park,))
        # No other suspension is woken by an open gate.
        self.assertEqual(self.plan(attempt("suspended", blocked_on="transport"),
                                   gate_open=True), (Op("park", reason="suspended:transport"),))

    def test_a_remainder_record_is_planned_by_the_same_rows(self):
        remainder = {"remainder": 1, "state": "active", "worktree": WORKTREE,
                     "launches": [{"kind": "fresh"}], "deadline_at": DEADLINE,
                     "blocked_on": None, "result_source": None, "result": None}
        self.assertEqual(self.plan(remainder, bare=True, current="14:r1:1", claim="c"), (
            Op("create"), Op("acquire", executor_id="14:r1:1", ttl_ms=30 * MINUTE),
            Op("claim", executor_id="14:r1:1", reference="c")))
        gone = {**remainder, "state": "suspended", "blocked_on": "owner_unavailable"}
        self.assertEqual(self.plan(gone, bare=True, current="14:r1:1"), (
            Op("create"), Op("park", reason="suspended:owner_unavailable")))
        failed = {**remainder, "state": "failed", "result_source": "owner",
                  "result": result("failed")}
        self.assertEqual(self.plan(failed, bare=True, bound=True, current="14:r1:1"),
                         (Op("create"), Op("seal", reason="owner:failed")))

    def test_a_delivered_issue_gives_up_launch_spans_and_plans_the_succeeded_seal(self):
        seal = Op("seal_succeeded", executor_id="14:1:seal", reason="delivered")
        merged = attempt("merged", source="owner", result=result("merged", "b" * 40))
        self.assertEqual(self.plan(attempt("active"), bare=True, delivered=True),
                         (Op("create"), seal))
        self.assertEqual(self.plan(merged, bare=True, delivered=True, latest=False), ())
        self.acquire()
        self.assertEqual(self.plan(attempt("active"), delivered=True, claim="c"),
                         (Op("release"), seal))
        self.assertEqual(self.plan(merged, delivered=True, digest="sha256:" + "1" * 64),
                         (Op("record_result", executor_id="14:1:1"), Op("release"), seal))
        self.now = T0 + 31 * MINUTE
        self.assertEqual(self.plan(attempt("active"), delivered=True),
                         (Op("reap", reason="expiry"), seal))
        self.assertEqual(self.plan(
            {"remainder": 2, "state": "active", "launches": [{}], "deadline_at": DEADLINE,
             "blocked_on": None, "result_source": None, "result": None},
            delivered=True, current="14:r2:1")[-1],
            Op("seal_succeeded", executor_id="14:r2:seal", reason="delivered"))

    def test_only_a_delivered_record_may_be_in_the_seals_forward_states(self):
        seal = Op("seal_succeeded", executor_id="14:1:seal", reason="delivered")
        held = self.store.acquire(self.id, executor_id="14:1:seal", subject_path=WORKTREE,
                                  ttl_ms=MINUTE).custody
        # The seal's own span is left open, at every state the seal passes.
        self.assertEqual(self.plan(attempt("active"), delivered=True), (seal,))
        for target in ac.FORWARD_STATES:
            self.store.advance(self.id, target, reason="delivered", custody=held)
            self.assertEqual(self.plan(attempt("active"), delivered=True), (seal,), target)
            with self.assertRaises(ac.ProjectionMismatch):
                self.plan(attempt("active"))
        self.store.settle_proof(self.store.start_cohort(held).custody)
        self.assertEqual(self.store.load(self.id).state, "succeeded")
        self.assertEqual(self.plan(attempt("active"), delivered=True), ())
        with self.assertRaises(ac.ProjectionMismatch):
            self.plan(attempt("active"))

    def test_a_cutover_plan_interrupted_after_any_operation_converges(self):
        resumed = attempt("active", launches=2, deadline="2026-08-13T21:01:00Z")
        refused = attempt("suspended", blocked_on="host_capacity")
        for lapsed, attempt_, facts, length in (
                (True, resumed, {"claim": "c"}, 4), (False, refused, {"gate_open": True}, 3),
                (True, attempt("active"), {"owner_gone": True}, 2)):
            def start():
                self.fresh()
                self.acquire()
                self.now = T0 + (31 * MINUTE if lapsed else 0)

            start()
            whole = self.plan(attempt_, **facts)
            self.assertEqual(len(whole), length, facts)
            self.apply(whole, None)
            reached = self.held()
            self.assertEqual(self.plan(attempt_, **facts), (), facts)
            for cut in range(1, length):
                with self.subTest(facts=facts, applied=cut):
                    start()
                    self.apply(self.plan(attempt_, **facts)[:cut], None)
                    self.apply(self.plan(attempt_, **facts), None)
                    self.assertEqual((self.held(), self.plan(attempt_, **facts)),
                                     (reached, ()))
```

- [ ] **Step 2: Run them and watch them fail**

Run: `PYTEST tests/test_attempt_delivery.py tests/test_attempt_custody.py`
Expected: FAIL — `agent_tools.attempt_delivery` cannot be imported, and the eight new custody cases fail on `ac.SUSPENSION_CAUSES` or an unexpected keyword of `settle_plan`. The 22 pre-existing cases pass.

- [ ] **Step 3: Implement**

Write the module and extend the planner to the interfaces, invariants and rows above. `_Settling` learns whether this plan acquired, and `unpark` takes its reason (default `"resumed"`). Violation functions return the first violation as text, as `subject_violation` does. Docstrings state each contract as built; the new module's says it is pure and that the caller passes the delivery model's canonical-text function in (D14).

- [ ] **Step 4: Verify**

Run: `PYTEST tests/test_attempt_delivery.py tests/test_attempt_custody.py tests/test_transaction_core_sweep.py T/test_attempt_custody.py`
Expected: `OK`; `tests/test_attempt_delivery.py` runs 6 tests and `tests/test_attempt_custody.py` 30. Package 2's CLI suite passes unedited: the store still calls the planner with the defaults.

Run: `if git diff --stat BASE -- 'python/agent_tools/transaction_*.py' | grep -q .; then exit 1; fi`
Expected: exit 0.

- [ ] **Step 5: Commit**

```bash
git add python tests justfile
launch-commit … -- -m "feat(attempt-delivery): pure delivery rules and the planner's cutover rows (#339)"
```
