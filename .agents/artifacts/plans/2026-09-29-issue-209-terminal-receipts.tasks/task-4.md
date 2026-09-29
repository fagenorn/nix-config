# Task 4: `dispose_failed` — the closed disposition and every refusal

**Files:**
- Modify: `python/agent_tools/transaction_disposition.py` (vocabularies, admission,
  events, validator rules, `terminal_blocker`, `action_effects`)
- Modify: `python/agent_tools/transaction_recovery.py` (extract `unreconciled`, used by
  `begin_refusal` and the disposition)
- Modify: `python/agent_tools/transaction_storage.py` (`DispositionRefused`)
- Modify: `python/agent_tools/transaction_receipt.py` (the `failed` outcome proof and
  qualifier; `abandoned` reuses `action_effects`)
- Modify: `python/agent_tools/transaction_history.py` (dispatch `failure_disposed`;
  `terminal_blocker` replaces `unresolved` at a terminal)
- Modify: `python/agent_tools/transaction_core.py` (`dispose_failed`, re-exports)
- Modify: `tests/test_transaction_disposition.py`

**Interfaces:**
- Consumes (Tasks 1–3): `FAILURE_REASON`, the two `failed` rules, `ACTOR_KINDS`, the
  grant fields, `authority_class` on `created`, the seal in `_append`, `Sealed`
  (`tests/test_transaction_receipt.py`). Also `RecoveryCase`, `RECOVERY`
  (`tests/test_transaction_recovery.py`, `tests/test_transaction_recovery_plan.py`) and
  `AUTHORITY`, `T0`, `TTL`, `plain`, `SUBJECT`, `KEYS`, `EMPTY_PROOF`, `EMPTY_RECOVERY`
  (`tests/test_transaction_custody.py`). From `transaction_recovery`: `effect_class`,
  `fresh_grant`, `no_effect`, `recovery_view`. From `transaction_invocation`:
  `fold_actions`, `status`, `unresolved`.
- Produces:
  - The Global Constraints' constants, plus `DISPOSITION_EVENT_KEYS =
    {"failure_disposed": envelope | {"grant_id", "ground", "reference", "occurred_at",
    "successor", "successor_receipt", "qualifier", "effect_snapshot", "units",
    "fence"}}`. All are re-exported by the core except the event keys.
  - `disposition_refused(transaction_id, reason, detail) -> DispositionRefused`, the one
    construction path, whose message is `"<transaction_id>: disposition refused: <reason>:
    <detail>"` (as `recovery_refused` words its own); `transaction_storage.DispositionRefused(TransactionError)` with
    `.reason`, re-exported.
  - `action_effects(events) -> dict[str, str]`: every `fold_actions` entry's
    `effect_class`, in declaration order (per D20).
  - `failure_refusal(document, grant_id, disposition, *, now_ms: int | None, successor:
    Mapping | None, writer: bool) -> tuple[str, str] | None`.
  - `failure_record(document, grant_id, disposition, successor_receipt) -> dict`, the
    `failure_disposed` fields without `seq`/`at`.
  - `failure_events(document, now_ms, grant_id, disposition, successor) -> list[dict]`.
  - `failure_event_violation(event, events_before, document, *, open_fence, state) -> str
    | None`.
  - `terminal_blocker(actions, previous) -> ActionFold | None`.
  - `transaction_recovery.unreconciled(actions, held) -> ActionFold | None`.
  - `TransactionStore.dispose_failed(custody, *, grant_id: str, disposition: Any) ->
    Transaction`.
  - Tests: `DisposeCase` with `disposition`, `dispose`, `human`, `unobservable`,
    `declined` and `succeeded`, and the helpers `destroyed(unit)` and `live(unit,
    bound)`. Task 5 reuses them.

**Invariants:**
- `failure_refusal` returns the first `(reason, detail)` in the spec's order (per D8,
  D9, D21):
  1. `state_not_attention`: `document["state"]` is not `attention_required`.
  2. `grant_required`: `fresh_grant(events, grant_id, held_fence)` is false.
  3. `malformed`: `disposition` is not a strict JSON object (`json_object_violation`) with
     exactly `ground`, `reference`, `occurred_at`, `successor` and `units`. `ground` is in
     `GROUNDS`, `reference` is a non-empty string, `occurred_at` is None or a non-bool int
     ≥ 0, and `successor` is None or `is_id`. `units` is a list of objects with exactly
     `unit` (non-empty string, no duplicate), `consequence` (in `CONSEQUENCES`),
     `residue_bound` and `recheck`. A destroyed unit has `residue_bound` and `recheck`
     None. A possibly-live unit has `residue_bound` in `RESIDUE_BOUNDS` and `recheck` a
     non-empty string. A known-state ground needs `occurred_at` None and `units` empty.
     `successor_succeeded` needs a `successor`, and `no_recovery_path` needs it None. An
     observability ground needs an int `occurred_at` (and, when `writer`, `occurred_at <=
     now_ms`) and `successor` None.
  4. `no_effect`: `no_effect(events)`.
  5. `reconciliation_required`: `unreconciled(actions, held_fence)` names an action,
     meaning one with an attempt that is open or whose latest inspection fence is not the
     held one. `begin_refusal` now calls this helper, and its behavior is unchanged.
  6. `effect_uncertain`: under a known-state ground, some action's `status` is
     `in_progress` or `unknown`; under an observability ground, some action is
     `in_progress` (per D21). Then, for `successor_succeeded`, `successor_not_succeeded`
     when the successor is not in `recovery_view(document)["children"]`, or, when
     `writer`, when `successor` is None, its `state` is not `succeeded`, or its
     `receipt_digest` is None.
  7. For an observability ground: `human_required` when the fresh grant (the latest
     `grant_issued` named `grant_id` under the held fence) has `actor_kind` other than
     `human`, then `authority_class_mismatch` when its `authority_class` differs from the
     `created` event's (per D11).
  8. `units_mismatch`: the `unit` list differs from the ids of the actions whose
     `effect_class` is not `no_effect`, in declaration order.
  9. `inspection_not_exhausted`: a possibly-live unit's fold has an inspection whose
     outcome is not `unknown`, whose fence is not the held one, or whose `at` (via
     `parse_at`) is not greater than `occurred_at`.
  Each detail names the unit or action it concerns.
- `failure_record` returns `grant_id` and the disposition's five fields, deep-copied,
  plus the following. `successor_receipt` is as passed. `qualifier` is
  `effects_unobservable` when some unit is possibly live, else `final_state_known`.
  `effect_snapshot` is `action_effects(events)`, so an `unknown` stays `unknown` (per
  D10). `fence` is the held fence. `failure_events` refuses through
  `disposition_refused`, else returns `[{"type": "failure_disposed", **record}, {"type":
  "transitioned", "from": "attention_required", "to": "failed", "reason":
  "failure_disposed", "external_state": "known"}]`, with `successor_receipt =
  successor["receipt_digest"]` for `successor_succeeded`, else None.
- `dispose_failed` runs `require_texts(custody, "dispose_failed", grant_id=grant_id)`
  before any lock. With no lock held, when `disposition` is a dict whose `successor`
  passes `is_id`, it loads that transaction. `successor` becomes `{"state",
  "receipt_digest"}` from its snapshot and `terminal`, or None on `UnknownTransaction`.
  It then calls `self._decide(custody, "dispose_failed", lambda prior, now:
  failure_events(prior, now, grant_id, disposition, successor))`, so the seal follows in
  the same write (per D2, D21). Its docstring points to `failure_refusal`'s.
- The validator dispatches `failure_disposed` through `_check_envelope` with
  `DISPOSITION_EVENT_KEYS`. Then `failure_event_violation` runs over a view `{**document,
  "events": events_before, "state": state, "custody": {"fence": open_fence}}`. With no
  open span it returns `failure_disposed sits outside an open custody span`. A refusal
  from `failure_refusal(view, …, now_ms=None, successor=None, writer=False)` reads
  `failure_disposed <reason>: <detail>`. `successor_receipt` must be None for every
  ground but `successor_succeeded`, and a `sha256:` + 64-hex string for it, else
  `failure_disposed successor_receipt is not null or a receipt digest as its ground
  requires`. Then every other field must equal `failure_record(view, …)`'s, else
  `failure_disposed does not match its re-derivation: <first differing key in sorted
  order>` (per D21; #208 D10).
- At a terminal transition the history uses `terminal_blocker(actions, events[seq - 2])`
  in place of `unresolved(actions)`. When the previous event is a `failure_disposed` with
  an observability ground, the blocker is the first action whose status is `open`,
  `in_progress` or `unknown`, skipping an `unknown` action named in its `units`.
  Otherwise it is `unresolved(actions)`. The refusal text is unchanged (per D21).
- The receipt's `failed` outcome proof is `{disposition_seq, ground, ground_reference,
  ground_occurred_at, successor, successor_receipt, effect_snapshot, units}` from the
  `failure_disposed`, and `terminal_qualifier` is its `qualifier`. `terminal_view`
  returns the same qualifier. The `abandoned` snapshot now calls `action_effects`.
- The disposition module docstring, the core's one-line sibling clause and the
  `transaction_history` docstrings are updated from the code.

- [ ] **Step 1: Write the failing tests.** Extend the imports of
  `tests/test_transaction_disposition.py`:

```python
from agent_tools import transaction_disposition, transaction_storage
from agent_tools.transaction_core import (
    CONSEQUENCES, DISPOSITION_REFUSAL_REASONS, GROUNDS, KNOWN_STATE_GROUNDS,
    OBSERVABILITY_GROUNDS, QUALIFIERS, RESIDUE_BOUNDS, DispositionRefused)

from .test_transaction_custody import T0, TTL, plain
from .test_transaction_receipt import Sealed
from .test_transaction_recovery import RecoveryCase
from .test_transaction_recovery_plan import RECOVERY

OTHER = "rel_01890a5d-ac96-7abc-8def-0123456789ab"
```

  Then append:

```python
def destroyed(unit):
    return {"unit": unit, "consequence": "effects_destroyed_with_authority",
            "residue_bound": None, "recheck": None}


def live(unit, bound="unbounded"):
    return {"unit": unit, "consequence": "effects_possibly_live_unobservable",
            "residue_bound": bound, "recheck": "re-read the target once authority returns"}


class DisposeCase(Sealed, RecoveryCase):
    def disposition(self, ground="no_recovery_path", **fields):
        return {"ground": ground, "reference": f"ops://{ground}", "occurred_at": None,
                "successor": None, "units": [], **fields}

    def unobservable(self, units=None, occurred_at=T0 - 1, **fields):
        build, start = self.act("build", n=1), self.act("start", n=2)
        return self.disposition("authority_retired", occurred_at=occurred_at,
                                units=[destroyed(build), live(start)] if units is None
                                else units, **fields)

    def dispose(self, grant_id="g-1", disposition=None, **fields):
        return self.store.dispose_failed(
            self.custody, grant_id=grant_id,
            disposition=self.disposition(**fields) if disposition is None else disposition)

    def human(self, grant_id="h-1", authority_class=AUTHORITY):
        return self.store.issue_grant(self.custody, grant_id=grant_id, actor="operator",
                                      actor_kind="human", authority_class=authority_class)

    def declined(self, reason, call):
        error = self.assertRefusedUnchanged(DispositionRefused, call)
        self.assertEqual(error.reason, reason)
        self.assertIn(self.transaction_id, str(error))
        return error

    def succeeded(self, transaction_id):
        custody = self.acquire(transaction_id)
        for target in ("awaiting_verification", "ready", "publishing", "published", "proving"):
            self.store.advance(transaction_id, target, reason="r", external_state="known",
                               custody=custody)
        self.store.start_cohort(custody)
        return self.store.settle_proof(custody)


# Every reason some `declined(...)` call in this file asserts; pinned to the vocabulary.
OBSERVED_REASONS = {"state_not_attention", "grant_required", "malformed", "no_effect",
                    "reconciliation_required", "effect_uncertain", "successor_not_succeeded",
                    "human_required", "authority_class_mismatch", "units_mismatch",
                    "inspection_not_exhausted"}


class DisposeTest(DisposeCase):
    def test_the_vocabularies_are_exactly_the_specified_ones(self):
        self.assertEqual(GROUNDS, KNOWN_STATE_GROUNDS + OBSERVABILITY_GROUNDS)
        self.assertEqual(KNOWN_STATE_GROUNDS, ("successor_succeeded", "no_recovery_path"))
        self.assertEqual(OBSERVABILITY_GROUNDS, (
            "authority_retired", "tenancy_destroyed", "host_decommissioned",
            "credential_class_revoked_without_successor", "subject_scope_erased"))
        self.assertEqual(CONSEQUENCES, ("effects_destroyed_with_authority",
                                        "effects_possibly_live_unobservable"))
        self.assertEqual(QUALIFIERS, ("final_state_known", "effects_unobservable"))
        self.assertEqual(RESIDUE_BOUNDS, ("bounded", "unbounded"))
        self.assertEqual(DISPOSITION_REFUSAL_REASONS, (
            "state_not_attention", "grant_required", "malformed", "no_effect",
            "reconciliation_required", "effect_uncertain", "successor_not_succeeded",
            "human_required", "authority_class_mismatch", "units_mismatch",
            "inspection_not_exhausted"))
        self.assertEqual(OBSERVED_REASONS, set(DISPOSITION_REFUSAL_REASONS))
        self.assertIs(DispositionRefused, transaction_storage.DispositionRefused)
        self.assertIs(GROUNDS, transaction_disposition.GROUNDS)
        with self.assertRaises(ValueError):
            transaction_disposition.disposition_refused("rel_x", "vibes", "d")

    def test_no_recovery_path_fails_with_a_sealed_known_state_receipt(self):
        self.parked()
        self.grant()
        after = self.dispose()
        self.assertEqual([e["type"] for e in after.events[-4:]],
                         ["failure_disposed", "transitioned", "lease_released", "receipt_sealed"])
        disposed, moved = dict(after.events[-4]), dict(after.events[-3])
        self.assertEqual((moved["from"], moved["to"], moved["reason"], moved["external_state"]),
                         ("attention_required", "failed", "failure_disposed", "known"))
        snapshot = {self.act("build", n=1): "target_satisfied",
                    self.act("start", n=2): "diverged"}
        self.assertEqual({k: v for k, v in disposed.items() if k not in ("seq", "type", "at")}, {
            "grant_id": "g-1", "ground": "no_recovery_path",
            "reference": "ops://no_recovery_path", "occurred_at": None, "successor": None,
            "successor_receipt": None, "qualifier": "final_state_known",
            "effect_snapshot": snapshot, "units": [], "fence": plain(self.custody.fence)})
        receipt = self.assertSealed(after, "failed", qualifier="final_state_known")
        self.assertEqual(receipt["outcome_proof"], {
            "disposition_seq": disposed["seq"], "ground": "no_recovery_path",
            "ground_reference": "ops://no_recovery_path", "ground_occurred_at": None,
            "successor": None, "successor_receipt": None, "effect_snapshot": snapshot,
            "units": []})
        self.assertFalse((self.root / "hazards").exists())

    def test_state_grant_shape_and_effect_refusals_come_first(self):
        self.published()
        self.grant()
        self.declined("state_not_attention", self.dispose)
        self.to("attention_required")
        self.declined("grant_required", self.dispose)
        self.grant("g-2")
        build = self.act("build", n=1)
        for shape in (["not", "an", "object"], {**self.disposition(), "extra": 1},
                      self.disposition("vibes"), self.disposition(reference=""),
                      self.disposition(occurred_at=T0 - 1), self.disposition(successor=OTHER),
                      self.disposition(units=[destroyed(build)]),
                      self.disposition("successor_succeeded"),
                      self.disposition("authority_retired", units=[destroyed(build)]),
                      self.unobservable(occurred_at=T0 + 1), self.unobservable(occurred_at=True),
                      self.unobservable(successor=OTHER),
                      self.unobservable(units=[{**destroyed(build), "consequence": "gone"}]),
                      self.unobservable(units=[{**destroyed(build), "residue_bound": "bounded"}]),
                      self.unobservable(units=[live(build, bound="some")]),
                      self.unobservable(units=[{**live(build), "recheck": ""}]),
                      self.unobservable(units=[destroyed(build), destroyed(build)])):
            with self.subTest(shape=shape):
                self.declined("malformed", lambda: self.dispose("g-2", disposition=shape))
        self.start_with(RECOVERY, key="bare", keys=("key:bare",))
        self.to("attention_required")
        self.grant()
        self.declined("no_effect", self.dispose)

    def test_an_inspection_under_an_older_fence_needs_reconciliation(self):
        self.parked()
        self.clock.advance(TTL)
        self.store.reap(self.transaction_id, reason="executor lost")
        self.custody = self.acquire(self.transaction_id, executor="exec-b")
        self.grant()
        self.declined("reconciliation_required", self.dispose)

    def test_an_uncertain_effect_never_becomes_a_known_state_failure(self):
        self.parked(start="unknown")
        self.grant()
        self.declined("effect_uncertain", self.dispose)
        self.start_with(RECOVERY, key="flight", keys=("key:flight",))
        self.parked(start="in_progress")
        self.human()
        self.declined("effect_uncertain", lambda: self.dispose(
            "h-1", disposition=self.unobservable()))

    def test_an_observability_ground_needs_a_human_at_the_class_and_exhausted_units(self):
        self.parked(start="unknown")
        self.grant()
        start = self.act("start", n=2)
        self.declined("human_required", lambda: self.dispose(disposition=self.unobservable()))
        self.human("h-beta", authority_class="release:beta")
        self.declined("authority_class_mismatch", lambda: self.dispose(
            "h-beta", disposition=self.unobservable()))
        self.human()
        self.declined("units_mismatch", lambda: self.dispose(
            "h-1", disposition=self.unobservable(units=[live(start)])))
        self.declined("inspection_not_exhausted", lambda: self.dispose(
            "h-1", disposition=self.unobservable(occurred_at=T0)))
        self.start_with(RECOVERY, key="seen", keys=("key:seen",))
        self.parked()
        self.human()
        self.declined("inspection_not_exhausted", lambda: self.dispose(
            "h-1", disposition=self.unobservable()))

    def test_successor_succeeded_needs_a_linked_child_that_succeeded(self):
        self.parked()
        self.grant()
        child = self.store.roll_forward(
            self.custody, grant_id="g-1", reason="unit_not_restorable", creation_key="forward",
            subject={**SUBJECT, "candidate": "sha256:def"}, concurrency_keys=("target:beta",),
            proof=EMPTY_PROOF, recovery=EMPTY_RECOVERY, authority_class=AUTHORITY)
        stranger = self.store.create(
            "stranger", SUBJECT, concurrency_keys=("target:gamma",), proof=EMPTY_PROOF,
            recovery=EMPTY_RECOVERY, authority_class=AUTHORITY).transaction_id
        self.succeeded(stranger)
        for successor in (child.transaction_id, stranger, OTHER):
            with self.subTest(successor=successor):
                self.declined("successor_not_succeeded", lambda: self.dispose(
                    ground="successor_succeeded", successor=successor))
        finished = self.succeeded(child.transaction_id)
        after = self.dispose(ground="successor_succeeded", successor=child.transaction_id)
        disposed = next(dict(e) for e in after.events if e["type"] == "failure_disposed")
        self.assertEqual((disposed["successor"], disposed["successor_receipt"]),
                         (child.transaction_id, finished.terminal["receipt_digest"]))
        receipt = self.assertSealed(after, "failed", qualifier="final_state_known")
        self.assertEqual(receipt["outcome_proof"]["successor_receipt"],
                         finished.terminal["receipt_digest"])

    def test_hand_edited_dispositions_are_state_invalid(self):
        self.parked()
        self.grant()
        self.dispose()
        document = self.state_doc(self.transaction_id)
        index = next(i for i, e in enumerate(document["events"])
                     if e["type"] == "failure_disposed")
        start = self.act("start", n=2)
        cases = (
            (lambda e: e.update(qualifier="effects_unobservable"),
             "failure_disposed does not match its re-derivation: qualifier"),
            (lambda e: e["effect_snapshot"].update({start: "no_effect"}),
             "failure_disposed does not match its re-derivation: effect_snapshot"),
            (lambda e: e.update(grant_id="g-9"), "failure_disposed grant_required"),
            (lambda e: e.update(ground="vibes"), "failure_disposed malformed"),
            (lambda e: e.update(successor_receipt="sha256:" + "0" * 64),
             "failure_disposed successor_receipt is not null or a receipt digest"),
            (lambda e: e.pop("units"), "closed failure_disposed event"))
        for edit, fragment in cases:
            with self.subTest(fragment=fragment):
                edited = copy.deepcopy(document)
                edit(edited["events"][index])
                self.assertRuleRefuses(self.transaction_id, edited, fragment)
```

- [ ] **Step 2: Run the tests and watch them fail.**
  Run: `PYTHONPATH=python python3 -m unittest tests/test_transaction_disposition.py 2>&1 | tail -3`.
  Expected: ERROR (`CONSEQUENCES` cannot be imported).

- [ ] **Step 3: Implement** the invariants. `failure_refusal` is one function whose steps
  are the numbered list. The writer and the validator both call it, and they differ only
  through `writer` and `now_ms` (per D21). Extract `unreconciled` without changing
  `begin_refusal`'s refusal text. If `transaction_core.py` passes 64000 bytes, apply the
  Global Constraints' docstring economy.

- [ ] **Step 4: Verify.**
  Run the slice unit command. Expected: `OK`.

```bash
grep -q "def dispose_failed" python/agent_tools/transaction_core.py || exit 1
grep -q "def unreconciled" python/agent_tools/transaction_recovery.py || exit 1
if grep -n "unresolved(actions)" python/agent_tools/transaction_history.py; then exit 1; fi
```

  Run: `git add -A python tests && just build 2>&1 | tail -3`. Expected: success.

- [ ] **Step 5: Commit.** Stage exactly this task's **Files**, then:

```bash
git commit -m "feat(transaction-core): enter failed only through a closed, grounded disposition (#209)"
```

- [ ] **Step 6: Check the review budget** with `FILES="python/agent_tools/transaction_disposition.py python/agent_tools/transaction_recovery.py python/agent_tools/transaction_receipt.py python/agent_tools/transaction_history.py python/agent_tools/transaction_core.py tests/test_transaction_disposition.py"`.
  Expected: exit 0.

Decisions: per D8, D9, D10, D11, D16, D20, D21.
