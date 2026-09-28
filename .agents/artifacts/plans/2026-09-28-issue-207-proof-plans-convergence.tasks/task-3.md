# Task 3: `collect_obligation`, evaluation and the proof view

**Files:**
- Create: `python/agent_tools/transaction_proof.py`
- Modify: `python/agent_tools/transaction_history.py` (dispatch, the evidence-id fold,
  `Transaction.proof`)
- Modify: `python/agent_tools/transaction_custody.py` (`admissibility` reads observations)
- Modify: `python/agent_tools/transaction_storage.py` (one error class)
- Modify: `python/agent_tools/transaction_core.py` (`collect_obligation`, re-exports)
- Create: `tests/test_transaction_proof.py`
- Modify: `tests/test_transaction_core_sweep.py` (`NEUTRAL_MODULES`), `justfile`

**Interfaces:**
- Consumes (Tasks 1–2): the plan module's names (`DERIVED_REASONS`, `PHASE_CLASS`), the
  stored `document["proof_plan"]`, `created.proof_plan_digest`, `transaction_custody.
  admissibility(events) -> (evidence, grants)`, `transaction_storage.parse_at`,
  `EffectResultInvalid`, and the core's `_fenced`/`_append`, `require_texts`.
- Produces (`agent_tools.transaction_storage`): `class ProofRefused(TransactionError)`, with
  `__init__(self, message: str, *, reason: str)` storing `self.reason`. Its docstring:
  `"""A proof operation the core refuses; `reason` names the closed rule. An admission
  refusal precedes any write or observer call; one at `collect_obligation`'s second hold
  follows the call and records nothing from it (#207 D18, D33)."""`.
- Produces (`agent_tools.transaction_proof`; Tasks 4–5 extend these exact names):
  - `OUTCOMES = ("satisfied", "unsatisfied", "unknown")`;
    `EVALUATIONS = ("accepted", "rejected", "indeterminate", "not_applicable",
    "unsupported")`;
    `PROOF_REFUSAL_REASONS = ("state_not_proving", "unknown_obligation",
    "unsupported_obligation", "dependency_not_accepted", "already_accepted",
    "not_cohort_member", "clock_regressed", "proof_incomplete", "cohort_open",
    "convergence_exhausted", "no_open_cohort")`, the whole vocabulary, fixed now;
    `PROOF_EVENT_KEYS: Mapping[str, frozenset[str]]`, which in this task holds only
    `"obligation_observed": {seq, type, at, obligation_id, evidence_id, form, outcome,
    reason, reference, fence, cohort, latency_ms}`.
  - `proof_refused(transaction_id: str, reason: str, detail: str) -> ProofRefused`: the one
    construction path. Its message is `f"{transaction_id}: proof refused: {reason}:
    {detail}"`, and an unknown reason is `ValueError`.
  - `obligation(plan: Mapping, obligation_id: str) -> dict | None`.
  - `next_evidence_id(events: Sequence[Mapping], obligation_id: str) -> str` (per D25).
  - `open_cohort(events: Sequence[Mapping], fence: Mapping) -> int | None`, which returns
    None in this task (no cohort event exists yet); Task 4 fills it.
  - `observation_request(document: dict, entry: dict, cohort: int | None) ->
    Mapping[str, Any]`, a `MappingProxyType` of `transaction_id`, `obligation_id`,
    `predicate`, `collector`, `parameters` (a deep copy), `fence` (a deep copy of the held
    fence) and `cohort`.
  - `observation_violation(result: Any, entry: Mapping) -> str | None`.
  - `evaluate(plan: Mapping, events: Sequence[Mapping], cutoff_ms: int) ->
    dict[str, tuple[str, str]]`: obligation id → (evaluation, reason), in plan order.
  - `collection_refusal(document: dict, obligation_id: Any, now_ms: int) -> str | None`.
  - `@dataclasses.dataclass class ProofFold` (whatever state the event rules need; Task 4
    adds cohort state), `proof_event_violation(event: dict, events_before:
    Sequence[Mapping], fold: ProofFold, *, plan: Mapping, keys: list[str], open_fence: dict
    | None, state: str) -> str | None`, and `apply_proof_event(event: dict, fold:
    ProofFold) -> None`.
  - `proof_view(document: dict) -> dict`: `{"plan_digest", "obligations", "cohorts",
    "proof_cutoff_at"}`. Here `cohorts` is `[]` and `proof_cutoff_at` is None; Task 4
    fills both.
- Produces (history): `Transaction.proof: Mapping[str, Any]`, the last field, a
  `MappingProxyType` over `proof_view(document)`. It is derived on every load and never
  stored.
- Produces (core): `TransactionStore.collect_obligation(custody: Custody, *, obligation_id:
  str, observer: Any) -> Transaction`, and the re-exports `PROOF_REFUSAL_REASONS` and
  `ProofRefused`.

**Invariants:**
- Import direction: `transaction_proof` imports only the standard library,
  `agent_tools.canonical`, `transaction_plan`, `transaction_invocation`,
  `transaction_custody` and `transaction_storage`. History imports proof, and proof never
  imports history or core. It reads no file, lock or clock.
- `next_evidence_id` returns `f"{obligation_id}@{n}"`, where n is 1 + the largest decimal
  suffix `k` over every `interval_opened`, `evidence_recorded` and `obligation_observed`
  whose `evidence_id` is exactly `f"{obligation_id}@{k}"` (so `k` is all decimal digits),
  and 1 when there is none.
- `collection_refusal` checks in order, with the first rule that applies winning (per D7):
  1. `state_not_proving` unless `document["state"] == "proving"`.
  2. `unknown_obligation` when there is no plan obligation of that id.
  3. `unsupported_obligation` when the collector's `predicates` lacks the predicate.
  4. `dependency_not_accepted` unless every dep evaluates `accepted` at `now_ms`.
  5. `already_accepted` for an `event` or `interval` obligation that evaluates `accepted`
     at `now_ms`.
- `observation_violation` requires the closed `{outcome, reason, reference}` dict, with
  `outcome` in `OUTCOMES` and `reason`/`reference` non-empty strings. For a
  `core_derived` entry, a non-`satisfied` outcome's reason must be in
  `DERIVED_REASONS[entry["derived_class"]]` (per D8).
- `evaluate` walks the plan in order (per D8, D28):
  1. Any dep evaluated `rejected` or `indeterminate` gives (`indeterminate`,
     `dependency_suppressed`).
  2. An advisory obligation whose collector lacks its predicate gives (`unsupported`,
     `predicate_unsupported`).
  3. Otherwise it takes the obligation's latest `obligation_observed`:
     - none gives (`indeterminate`, `evidence_missing`);
     - one whose `admissibility` entry is not admissible gives (`indeterminate`,
       `fence_lost`);
     - a `snapshot` with `cutoff_ms > parse_at(at) + freshness_ms` gives (`indeterminate`,
       `evidence_stale`);
     - `satisfied` gives (`accepted`, its reason), `unsatisfied` gives (`rejected`, its
       reason), and `unknown` gives (`indeterminate`, `unreachable`).
- `admissibility` treats `obligation_observed` exactly like `evidence_recorded` (same entry
  keys and void rules). History's evidence-id fold (`_id_violation`, `_note_id`,
  `fenced_id_violation`) does too, so an interval observation must close an opened,
  unclosed id, and any other observation id must be unused (per D25).
- The `obligation_observed` validator rules, each a `StateInvalid` naming the event seq:
  - the folded state is `proving`;
  - the fence is inside the open span and equals it;
  - `obligation_id` names a plan obligation, and `form` equals its form;
  - `evidence_id` is `f"{obligation_id}@<decimal>"`, and for a non-interval form it equals
    `next_evidence_id(events_before, obligation_id)`;
  - `outcome`, `reason` and `reference` pass the `observation_violation` rules;
  - `latency_ms` is an int ≥ 0 and not a bool;
  - `cohort` equals `open_cohort(events_before, fence)`.
- `collect_obligation` (per D6, D22, D27, D33, D34):
  - It refuses `StateInvalid` before any lock for a malformed credential or id, or an
    observer without a callable `observe`.
  - **First hold** (`_fenced`, `writes=True`), with `now` read once: `collection_refusal`
    raises `proof_refused` (nothing written, observer not called). `cohort` is
    `open_cohort(events, held fence)`. For an `interval` obligation the core appends
    `interval_opened` under `next_evidence_id` and keeps that id. It then builds the
    request with `started = now`.
  - **Call**: `observer.observe(request)` runs with no lock held. Whatever the observer
    raises propagates. A result failing `observation_violation` is `EffectResultInvalid`,
    and nothing from the call is written.
  - **Second hold** (`_fenced` again: a terminal is `TransitionRefused` and a lapse is
    `StaleCustody`, with nothing written). A `now` earlier than `started` is refused
    `clock_regressed` (per D34). Then `collection_refusal` is re-run at the new `now`, and
    `not_cohort_member` is refused when `open_cohort` now differs from the request's
    `cohort`. None of these records anything from the call. The core then appends
    `obligation_observed`, whose evidence id is the opened interval id or a fresh
    `next_evidence_id`, whose `fence` is the held one and whose `latency_ms` is
    `now - started`.
  - Any other exit after the first hold leaves an interval's `interval_opened` unclosed,
    and the next collection mints a new id (per D33); `collect_obligation`'s docstring
    says so.
- The `proof_view` obligations follow plan order, each keyed exactly `obligation_id,
  obligation_kind, semantic, derived_class, form, required, observations` (the count of
  `obligation_observed`), `latest_outcome` (None when unobserved) and `latest_admissible`
  (the admissibility entry's `admissible`, or None when unobserved). `plan_digest` is
  `created.proof_plan_digest`.
- `transaction_core.py` stays at most 55000 bytes: keep every rule in `transaction_proof`.

- [ ] **Step 1: Write the failing tests.** Create `tests/test_transaction_proof.py`:

```python
"""Transaction core slice 4: obligations, the convergence cohort and settlement (#207).

Run: just agent-workflow-tests
"""

import copy
import json
import unittest

from agent_tools import transaction_storage
from agent_tools.transaction_core import (
    PROOF_REFUSAL_REASONS, EffectResultInvalid, ProofRefused, StaleCustody, StateInvalid,
    TransactionError, TransitionRefused, action_id)

from .test_transaction_custody import KEYS, SUBJECT, TTL, CustodyCase, plain, serialize
from .test_transaction_invocation import FakeEffect, FakeWorld, renumbered

PUB, ACT = "published_artifact_identity", "running_subject_identity"
C = {"basis": "deterministic", "max_collection_latency_ms": 30_000,
     "predicates": ["publication_visible", "running_subject_identity", "migrated", "health",
                    "smoke"]}
M = {"basis": "model", "predicates": ["vibe"], "max_collection_latency_ms": 30_000}
UNITS = [{"name": "build", "parameters": {"n": 1}, "phase": "publication", "collector": "c"},
         {"name": "start", "parameters": {"n": 2}, "phase": "activation", "collector": "c"}]


def ob(identity, form, predicate, *, deps=(), required=True, collector="c",
       semantic="readiness"):
    entry = {"id": identity, "semantic": semantic, "form": form, "predicate": predicate,
             "collector": collector, "required": required, "deps": list(deps),
             "parameters": {"of": identity}}
    if form == "snapshot":
        entry["freshness_ms"] = 600_000
    return entry


DECLARATION = {"units": UNITS, "collectors": {"c": C, "m": M}, "obligations": [
    ob("migrated", "event", "migrated"),
    ob("health", "snapshot", "health", deps=["migrated"], semantic="liveness"),
    ob("smoke", "interval", "smoke", deps=[f"derived:{ACT}:start"], semantic="product_smoke"),
    ob("vibe", "snapshot", "vibe", required=False, collector="m", semantic="observability"),
    ob("uptime", "snapshot", "uptime", required=False, semantic="observability")]}


class Boom(Exception):
    """An observer dying mid-call."""


class Observer:
    """An in-memory observer. `outcomes` maps obligation ids to outcomes (default
    `satisfied`); `step_ms` advances the store clock inside every call; `result`
    replaces the reply; `fail` is raised. The reference encodes the request."""

    def __init__(self, clock, outcomes=None, *, reasons=None, step_ms=0, result=None,
                 fail=None):
        self.clock, self.outcomes, self.reasons = clock, outcomes or {}, reasons or {}
        self.step_ms, self.result, self.fail = step_ms, result, fail

    def observe(self, request):
        self.clock.advance(self.step_ms)
        if self.fail is not None:
            raise self.fail
        if self.result is not None:
            return self.result
        outcome = self.outcomes.get(request["obligation_id"], "satisfied")
        reason = self.reasons.get(request["obligation_id"],
                                  "ok" if outcome == "satisfied" else "subject_mismatch")
        epoch = min(entry["epoch"] for entry in request["fence"].values())
        return {"outcome": outcome, "reason": reason,
                "reference": f"obs:{request['cohort']}:{epoch}:{request['predicate']}"}


class ProofCase(CustodyCase):
    def setUp(self):
        super().setUp()
        self.world = FakeWorld()
        self.transaction_id = self.store.create(
            "proof", SUBJECT, concurrency_keys=KEYS, proof=DECLARATION).transaction_id
        self.custody = self.acquire(self.transaction_id)
        self.plan = self.store.load(self.transaction_id).proof_plan
        self.ids = [entry["obligation_id"] for entry in self.plan["obligations"]]
        self.pub, self.act = self.ids[:2]

    def to(self, *targets, custody=None):
        for target in targets:
            after = self.store.advance(self.transaction_id, target, reason="r",
                                       external_state="known",
                                       custody=custody or self.custody)
        return after

    def satisfy(self, name, parameters):
        for operation in (self.store.inspect_action, self.store.invoke_action):
            operation(self.custody, name=name, parameters=parameters,
                      effect=FakeEffect(self.world))

    def proving(self):
        self.to("awaiting_verification", "ready", "publishing")
        self.satisfy("build", {"n": 1})
        self.to("published", "activating")
        self.satisfy("start", {"n": 2})
        return self.to("proving")

    def observer(self, *args, **options):
        return Observer(self.clock, *args, **options)

    def collect(self, obligation_id, observer=None, custody=None):
        return self.store.collect_obligation(custody or self.custody,
                                             obligation_id=obligation_id,
                                             observer=observer or self.observer())

    def collect_required(self, observer=None):
        for obligation_id in (self.pub, self.act, "migrated", "health", "smoke"):
            after = self.collect(obligation_id, observer)
        return after

    def refused(self, reason, call):
        now = self.clock.now
        error = self.assertRefusedUnchanged(ProofRefused, call)
        self.assertEqual((error.reason, self.clock.now), (reason, now))
        self.assertIn(self.transaction_id, str(error))
        return error

    def observed(self):
        return [dict(e) for e in self.store.load(self.transaction_id).events
                if e["type"] == "obligation_observed"]

    def entry(self, obligation_id):
        return next(dict(e) for e in self.store.load(self.transaction_id).proof["obligations"]
                    if e["obligation_id"] == obligation_id)

    def reacquired(self):
        self.clock.advance(TTL)
        self.store.reap(self.transaction_id, reason="executor lost")
        self.custody = self.acquire(self.transaction_id)
        return self.to("proving")


class CollectTest(ProofCase):
    def test_an_observation_is_recorded_with_its_core_measured_latency(self):
        self.proving()
        after = self.collect(self.pub, self.observer(step_ms=1_234))
        recorded = {k: v for k, v in after.events[-1].items() if k not in ("seq", "at")}
        self.assertEqual(recorded, {
            "type": "obligation_observed", "obligation_id": self.pub,
            "evidence_id": f"{self.pub}@1", "form": "event", "outcome": "satisfied",
            "reason": "ok", "reference": "obs:None:1:publication_visible",
            "fence": plain(self.custody.fence), "cohort": None, "latency_ms": 1_234})
        [evidence] = [e for e in after.evidence if e["evidence_id"] == f"{self.pub}@1"]
        self.assertEqual((evidence["form"], evidence["admissible"]), ("event", True))

    def test_the_request_is_read_only(self):
        class Mutating(Observer):
            def observe(self, request):
                request["cohort"] = 1

        self.proving()
        self.assertRefusedUnchanged(TypeError, lambda: self.collect(
            self.pub, Mutating(self.clock)))

    def test_evidence_ids_step_past_every_earlier_id_of_the_obligation(self):
        self.proving()
        self.collect(self.act)
        self.collect(self.act)
        self.store.record_evidence(self.custody, evidence_id=f"{self.act}@7",
                                   form="snapshot", reference="by hand")
        self.collect(self.act)
        self.assertEqual([e["evidence_id"] for e in self.observed()],
                         [f"{self.act}@1", f"{self.act}@2", f"{self.act}@8"])
        self.assertRefusedUnchanged(StateInvalid, lambda: self.store.record_evidence(
            self.custody, evidence_id=f"{self.act}@8", form="snapshot", reference="again"))

    def test_the_core_opens_an_interval_before_its_call(self):
        self.proving()
        self.collect(self.act)
        with self.assertRaises(Boom):
            self.collect("smoke", self.observer(fail=Boom()))
        after = self.collect("smoke")
        trail = [(e["type"], e.get("evidence_id")) for e in after.events
                 if e.get("evidence_id", "").startswith("smoke@")]
        self.assertEqual(trail, [("interval_opened", "smoke@1"), ("interval_opened", "smoke@2"),
                                 ("obligation_observed", "smoke@2")])
        self.assertEqual(self.entry("smoke")["latest_admissible"], True)

    def test_an_invalid_interval_result_keeps_its_opened_marker(self):
        self.proving()
        self.collect(self.act)
        with self.assertRaises(EffectResultInvalid):
            self.collect("smoke", self.observer(result={"outcome": "maybe", "reason": "ok",
                                                        "reference": "r"}))
        self.assertEqual([(e["type"], e.get("evidence_id")) for e in self.store.load(
            self.transaction_id).events][-1], ("interval_opened", "smoke@1"))
        self.assertEqual(self.entry("smoke")["observations"], 0)
        self.assertEqual(self.collect("smoke").events[-1]["evidence_id"], "smoke@2")

    def test_a_clock_that_runs_backwards_during_the_call_records_nothing(self):
        self.proving()
        error = self.assertRefusedUnchanged(ProofRefused, lambda: self.collect(
            self.pub, self.observer(step_ms=-5_000)))
        self.assertEqual(error.reason, "clock_regressed")

    def test_admission_refusals_come_before_any_write_or_call(self):
        slow = self.observer(step_ms=1)
        self.refused("state_not_proving", lambda: self.collect(self.pub, slow))
        self.proving()
        self.refused("unknown_obligation", lambda: self.collect("ghost", slow))
        self.refused("unsupported_obligation", lambda: self.collect("uptime", slow))
        self.refused("dependency_not_accepted", lambda: self.collect("health", slow))
        self.refused("dependency_not_accepted", lambda: self.collect("smoke", slow))
        self.collect("migrated")
        self.refused("already_accepted", lambda: self.collect("migrated", slow))
        self.collect(self.act)
        self.collect("smoke")
        self.refused("already_accepted", lambda: self.collect("smoke", slow))

    def test_a_rejected_prerequisite_suppresses_collection(self):
        self.proving()
        self.collect("migrated", self.observer({"migrated": "unsatisfied"}))
        self.refused("dependency_not_accepted", lambda: self.collect("health"))

    def test_out_of_shape_observations_record_nothing(self):
        self.proving()
        for obligation_id, result in (
                (self.pub, ["not", "a", "result"]),
                (self.pub, {"outcome": "satisfied", "reference": "r"}),
                (self.pub, {"outcome": "satisfied", "reason": "ok", "reference": "r", "x": 1}),
                (self.pub, {"outcome": "maybe", "reason": "ok", "reference": "r"}),
                (self.pub, {"outcome": "satisfied", "reason": "", "reference": "r"}),
                (self.pub, {"outcome": "satisfied", "reason": "ok", "reference": 7}),
                (self.act, {"outcome": "unsatisfied", "reason": "flaky", "reference": "r"}),
                (self.pub, {"outcome": "unknown", "reason": "subject_absent",
                            "reference": "r"})):
            with self.subTest(obligation=obligation_id, result=result):
                self.assertRefusedUnchanged(EffectResultInvalid, lambda: self.collect(
                    obligation_id, self.observer(result=result)))
        self.collect(self.pub, self.observer(result={
            "outcome": "unknown", "reason": "store_unreachable", "reference": "r"}))
        self.collect("migrated", self.observer(result={
            "outcome": "unsatisfied", "reason": "anything stable", "reference": "r"}))

    def test_a_lapse_during_the_call_records_nothing(self):
        self.proving()
        self.assertRefusedUnchanged(StaleCustody, lambda: self.collect(
            self.act, self.observer(step_ms=TTL)))

    def test_the_view_keeps_events_and_voids_snapshots_across_a_fence_change(self):
        self.proving()
        self.collect(self.pub)
        self.collect(self.act)
        view = self.reacquired().proof
        self.assertEqual(view["plan_digest"],
                         self.store.load(self.transaction_id).events[0]["proof_plan_digest"])
        self.assertEqual((view["cohorts"], view["proof_cutoff_at"]), ([], None))
        entries = {e["obligation_id"]: dict(e) for e in view["obligations"]}
        self.assertEqual(list(entries), self.ids)
        self.assertEqual(entries[self.pub], {
            "obligation_id": self.pub, "obligation_kind": "core_derived", "semantic": None,
            "derived_class": PUB, "form": "event", "required": True, "observations": 1,
            "latest_outcome": "satisfied", "latest_admissible": True})
        self.assertEqual((entries[self.act]["latest_admissible"],
                          entries["health"]["observations"],
                          entries["health"]["latest_outcome"],
                          entries["health"]["latest_admissible"]), (False, 0, None, None))

    def test_hand_edited_observations_are_state_invalid(self):
        self.proving()
        pristine = json.loads(serialize(self.state_doc(self.collect(self.pub).transaction_id)))
        last = len(pristine["events"])
        for field, value in (("obligation_id", "ghost"), ("form", "snapshot"),
                             ("evidence_id", f"{self.pub}@2"), ("outcome", "maybe"),
                             ("reason", ""), ("latency_ms", -1), ("latency_ms", True),
                             ("cohort", 1)):
            with self.subTest(field=field, value=value):
                document = copy.deepcopy(pristine)
                document["events"][-1][field] = value
                if field == "obligation_id":
                    document["events"][-1]["evidence_id"] = "ghost@1"
                self.assertRuleRefuses(self.transaction_id, document, f"event {last}")
        document = copy.deepcopy(pristine)
        document["events"][-1].update(outcome="unsatisfied", reason="flaky")
        self.assertRuleRefuses(self.transaction_id, document, f"event {last}")
        document = copy.deepcopy(pristine)
        proving = next(i for i, e in enumerate(document["events"])
                       if e["type"] == "transitioned" and e["to"] == "proving")
        document["events"].insert(proving, copy.deepcopy(document["events"][-1]))
        self.assertRuleRefuses(self.transaction_id, renumbered(document), f"event {proving + 1}")


class ProofVocabularyTest(unittest.TestCase):
    def test_the_error_is_a_transaction_error_homed_in_storage(self):
        self.assertIs(ProofRefused, transaction_storage.ProofRefused)
        self.assertTrue(issubclass(ProofRefused, TransactionError))

    def test_the_refusal_reasons_are_fixed(self):
        self.assertEqual(len(set(PROOF_REFUSAL_REASONS)), 11)


if __name__ == "__main__":
    unittest.main()
```

  In `tests/test_transaction_core_sweep.py`, add `transaction_proof` to the late import and
  to `NEUTRAL_MODULES`, directly after `transaction_history`. In `justfile`, add
  `    tests/test_transaction_proof.py \` directly after `tests/test_transaction_plan.py \`.

- [ ] **Step 2: Run the tests and watch them fail.**
  Run: `PYTHONPATH=python python3 -m unittest tests/test_transaction_proof.py 2>&1 | tail -3`.
  Expected: FAIL, `ImportError: cannot import name 'PROOF_REFUSAL_REASONS'`.

- [ ] **Step 3: Implement** the module, the history dispatch and the core operation, as
  set out under **Interfaces** and **Invariants**.
  - In `validate_state`, a `case str() if event_type in PROOF_EVENT_KEYS:` arm runs, in
    order: `_check_envelope`, then `proof_event_violation(event, events[:seq - 1], fold, ...)`,
    then (for `obligation_observed`) the evidence-id rule `_id_violation`/`_note_id`, then
    `apply_proof_event`.
  - Add `obligation_observed` to the types `fenced_id_violation` folds.
  - Write docstrings from the finished code: the new module's (what it holds; no file,
    lock or clock); history's and `validate_state`'s, which now hand proof events to
    `transaction_proof`; `Transaction`'s, which adds `proof`, derived on every load and
    never stored; and `collect_obligation`'s, which describes the two holds as built.
  - Core: re-export `PROOF_REFUSAL_REASONS` and `ProofRefused`.

- [ ] **Step 4: Verify.**
  Run the root's slice unit command. Expected: `OK`.

```bash
if grep -nE "^(from|import) .*transaction_(core|history)" python/agent_tools/transaction_proof.py; then exit 1; fi
[ "$(grep -c 'tests/test_transaction_proof.py' justfile)" = 1 ] || exit 1
```

  Run: `git add -A python tests justfile && just build 2>&1 | tail -3`. Expected: success.

- [ ] **Step 5: Commit.** Stage exactly this task's **Files**, then:

```bash
git commit -m "feat(transaction-core): collect obligations through the core (#207)"
```

- [ ] **Step 6: Check the review budget** (after the commit): run the root's review-budget block with `FILES="python/agent_tools/transaction_*.py tests/test_transaction_proof.py tests/test_transaction_plan.py tests/test_transaction_core.py"`.
  Expected: exit 0.

Decisions: per D5–D8, D13, D18, D20, D22, D25, D27, D33, D34.
