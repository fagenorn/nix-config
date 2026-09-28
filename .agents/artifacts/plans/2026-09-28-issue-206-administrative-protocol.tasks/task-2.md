# Task 2: Schema v3, declared/inspected events, `Transaction.actions` and `inspect_action`

**Files:**
- Modify: `python/agent_tools/transaction_invocation.py`
- Modify: `python/agent_tools/transaction_history.py`
- Modify: `python/agent_tools/transaction_core.py`
- Modify: `tests/test_transaction_invocation.py` (fixtures and tests appended before the
  `if __name__` block; merge imports into the header)
- Modify: `tests/test_transaction_core.py` (two schema strings)

**Interfaces:**
- Consumes (Task 1): `action_violation`, `action_id`, `OUTCOMES`, `MAX_ATTEMPTS`,
  `RETRY_WINDOW_MS`, `RETRY_SAFE_CLASSES`, `EffectResultInvalid`, storage `format_at`,
  `parse_at`; core `_fenced(custody, operation, *, writes) -> (prior, now)`,
  `_validate_state`, `atomic_write`, `snapshot`; history `_check_envelope`.
- Produces (`transaction_invocation`; Tasks 3–5 extend these exact names):
  - `ACTION_EVENT_KEYS: Mapping[str, frozenset[str]]` — `action_declared`: envelope ∪
    {`action_id`, `name`, `parameters`}; `action_inspected`: envelope ∪ {`action_id`,
    `outcome`, `reference`, `fence`} (envelope = {`seq`, `type`, `at`}).
  - `@dataclasses.dataclass class ActionFold` with fields `action_id: str`, `name: str`,
    `attempts: int = 0`, `open: bool = False`, `intent_fence: dict | None = None`,
    `returned: dict | None = None` (the latest attempt's `invocation_returned`),
    `inspection: dict | None = None` (the latest `action_inspected`),
    `first_failure_ms: int | None = None`.
  - `inspect_result_violation(result: Any) -> str | None` — None only for a `dict` whose
    key set is exactly {`outcome`, `reference`}, outcome in `OUTCOMES`, reference a
    non-empty `str` (per D11).
  - `action_event_violation(event: dict, actions: dict[str, ActionFold], *, transaction_id:
    str, keys: list[str], open_fence: dict | None, state: str) -> str | None` — the rule
    one envelope-checked action event breaks, or None.
  - `apply_action_event(event: dict, actions: dict[str, ActionFold]) -> None` — folds one
    valid event; never raises on a valid history.
  - `fold_actions(events: Sequence[Mapping]) -> dict[str, ActionFold]` — declaration-ordered.
  - `retry_safe(entry: ActionFold) -> bool` — for now: the latest attempt has a return that
    is not `accepted` and whose class is in `RETRY_SAFE_CLASSES` (Task 4 widens it).
  - `status(entry: ActionFold) -> str` — `open` if `entry.open`; else the latest
    inspection's outcome; else `declared`.
  - `action_views(events) -> list[dict]` — one dict per action with exactly the keys
    `action_id`, `name`, `attempts`, `status`, `last_error_class` (the latest return's
    `error_class`, else None), `retry_eligible` (`status == "absent"` and `attempts <
    MAX_ATTEMPTS` and (`attempts == 0` or `retry_safe(entry)`), per D17) and
    `retry_deadline_at` (`format_at(first_failure_ms + RETRY_WINDOW_MS)` or None).
  - `effect_request(document: dict, identity: str, name: str, parameters: dict, attempt: int)
    -> Mapping[str, Any]` — `MappingProxyType` of `transaction_id`, `action_id`, `name`,
    deep-copied `parameters`, deep-copied held `fence`, `attempt`.
- Produces (history): `SCHEMA = "transaction-state/v3"`; `Transaction.actions:
  tuple[Mapping[str, Any], ...]` (last field, `MappingProxyType` per `action_views` entry).
- Produces (core): `TransactionStore.inspect_action(custody: Custody, *, name: str,
  parameters: dict, effect: Any) -> Transaction`; private `_action_arguments(custody,
  operation, name, parameters, effect) -> str` (the action id) and `_append(prior: dict,
  now: int, events: list[dict]) -> Transaction` (numbers each fields dict with `seq` and
  `at = format_at(now)`, sets `revision`, validates, writes, returns the snapshot). Task 3
  reuses both.

**Invariants:**
- Validator rules this task adds, each message containing the quoted fragment:
  a non-string `action_id` → `"action_id is not a string"`; a declared id already declared
  → `"is declared twice"`; a declared name/parameters with an `action_violation` → that
  rule; a declared id ≠ `action_id(transaction_id, name, parameters)` → `"does not re-derive
  from its name and parameters"`; any other action event whose id is undeclared → `"has no
  earlier action_declared"`; a fenced action event with a malformed fence →
  `fence_violation`'s rule; with no open span → `"sits outside an open custody span"`;
  with a fence ≠ the open span's → `"fence does not equal the open span's fence"`;
  outcome → `"outcome is not absent, in_progress, satisfied, diverged or unknown"`;
  reference → `"reference is not a non-empty string"`. Envelope violations keep history's
  `_check_envelope` messages.
- `apply_action_event` on `action_inspected`: sets `inspection` to `{outcome, fence, at}`,
  clears `open`, and sets `first_failure_ms = parse_at(at)` when the outcome is `absent`,
  `attempts >= 1` and it is still None (per D6).
- `inspect_action` (per D3, D5, D8): shape refusals (`StateInvalid`) come first, before any
  lock — a malformed credential, `action_violation`, or an effect without callable
  `inspect` and `invoke`. Under `_fenced(..., writes=True)` (terminal → `TransitionRefused`,
  then the fenced check) it builds the request with `attempt` = the entry's `attempts`, or
  0, and leaves the lock. It calls `effect.inspect(request)`; an `inspect_result_violation`
  is `EffectResultInvalid` with nothing written. Under a second `_fenced` it appends
  `action_declared` (only when the re-folded history has no entry) and `action_inspected`
  stamped with the held fence, in one write. The effect's exceptions propagate.
- Any state but a terminal may inspect, parkings included (per D8).

- [ ] **Step 1: Write the failing tests** — header imports become:

```python
import copy
import fcntl
import unittest

from agent_tools import transaction_history, transaction_storage
from agent_tools.canonical import telemetry_digest
from agent_tools.transaction_core import (
    MAX_ATTEMPTS, RETRY_WINDOW_MS, EffectResultInvalid, InvocationRefused, StaleCustody,
    StateInvalid, TransactionError, TransactionStore, TransitionRefused, action_id)

from .test_transaction_custody import TTL, CustodyCase, T0, plain, serialize
```

  Append:

```python
OTHER_FENCE = {key: {"epoch": 9, "instance": "lin_" + "0" * 32}
               for key in ("project:alpha", "target:alpha")}


class Crash(Exception):
    """A runner dying inside an effect."""


class FakeWorld:
    """The external side: which attempt applied each idempotency key, and invoke counts."""

    def __init__(self):
        self.applied = {}
        self.invokes = {}


class FakeEffect:
    """An effect over a FakeWorld. `inspect_outcome` forces the observation; `results`
    scripts each invoke's (result, error_class), default accepted; `crash` is "before"
    (raise before touching the world) or "after" (apply, then raise); `during` runs at
    the start of every call. References encode what the request carried."""

    def __init__(self, world, *, inspect_outcome=None, results=(), crash=None, during=None):
        self.world, self.inspect_outcome = world, inspect_outcome
        self.results, self.crash, self.during = list(results), crash, during

    def inspect(self, request):
        if self.during:
            self.during()
        outcome = self.inspect_outcome or (
            "satisfied" if request["action_id"] in self.world.applied else "absent")
        epoch = min(entry["epoch"] for entry in request["fence"].values())
        return {"outcome": outcome, "reference": f"seen:{request['attempt']}:{epoch}"}

    def invoke(self, request):
        if self.during:
            self.during()
        key = request["action_id"]
        if self.crash == "before":
            raise Crash(key)
        self.world.invokes[key] = self.world.invokes.get(key, 0) + 1
        result, error_class = self.results.pop(0) if self.results else ("accepted", None)
        if result == "accepted":
            self.world.applied[key] = request["attempt"]
        if self.crash == "after":
            raise Crash(key)
        return {"result": result, "error_class": error_class,
                "reference": f"call:{request['attempt']}"}


def renumbered(document):
    for seq, event in enumerate(document["events"], start=1):
        event["seq"] = seq
    document["revision"] = len(document["events"])
    return document


class ProtocolCase(CustodyCase):
    NAME = "build"
    PARAMETERS = {"mode": "materialize", "subject": {"digest": "sha256:abc"}}

    def setUp(self):
        super().setUp()
        self.world = FakeWorld()
        self.transaction_id = self.new()
        self.custody = self.acquire(self.transaction_id)

    def effect(self, **options):
        return FakeEffect(self.world, **options)

    def to(self, *targets, custody=None):
        for target in targets:
            after = self.store.advance(self.transaction_id, target, reason="r",
                                       external_state="known",
                                       custody=custody or self.custody)
        return after

    def publishing(self):
        return self.to("awaiting_verification", "ready", "publishing")

    def inspect(self, effect=None, *, custody=None, name=None):
        return self.store.inspect_action(
            custody or self.custody, name=name or self.NAME, parameters=self.PARAMETERS,
            effect=effect or self.effect())

    def act(self, name=None):
        return action_id(self.transaction_id, name or self.NAME, self.PARAMETERS)

    def view(self):
        [entry] = self.store.load(self.transaction_id).actions
        return dict(entry)

    def action_types(self):
        return [e["type"] for e in self.store.load(self.transaction_id).events
                if e["type"].startswith(("action_", "invocation_"))]


class SchemaTest(ProtocolCase):
    def test_new_state_is_v3_and_a_v2_document_fails_closed_naming_its_version(self):
        document = self.state_doc(self.transaction_id)
        self.assertEqual(document["schema"], "transaction-state/v3")
        self.assertRuleRefuses(self.transaction_id,
                               {**document, "schema": "transaction-state/v2"},
                               "transaction-state/v2")


class InspectActionTest(ProtocolCase):
    def test_a_first_inspection_declares_the_action_and_records_the_outcome(self):
        after = self.inspect()
        at = "2027-01-15T08:00:00.000Z"
        self.assertEqual([dict(e) for e in after.events[2:]], [
            {"seq": 3, "type": "action_declared", "at": at, "action_id": self.act(),
             "name": "build", "parameters": self.PARAMETERS},
            {"seq": 4, "type": "action_inspected", "at": at, "action_id": self.act(),
             "outcome": "absent", "reference": "seen:0:1",
             "fence": plain(self.custody.fence)}])
        self.assertEqual(self.view(), {
            "action_id": self.act(), "name": "build", "attempts": 0, "status": "absent",
            "last_error_class": None, "retry_eligible": True, "retry_deadline_at": None})
        self.assertEqual(self.world.invokes, {})
        self.assertEqual(TransactionStore(self.root).load(self.transaction_id).actions,
                         after.actions)

    def test_a_later_inspection_appends_only_its_outcome(self):
        self.inspect()
        self.world.applied[self.act()] = 0
        self.assertEqual(self.inspect().events[-1]["outcome"], "satisfied")
        self.assertEqual(self.action_types(),
                         ["action_declared", "action_inspected", "action_inspected"])
        self.assertEqual(self.view()["status"], "satisfied")

    def test_every_outcome_is_recorded_and_a_parking_may_inspect(self):
        self.to("attention_required")
        for outcome in ("in_progress", "diverged", "unknown", "absent", "satisfied"):
            self.inspect(self.effect(inspect_outcome=outcome))
            self.assertEqual(self.view()["status"], outcome)
            self.assertEqual(self.view()["retry_eligible"], outcome == "absent")

    def test_actions_are_listed_in_declaration_order(self):
        for name in ("stage", "build", "stage"):
            self.inspect(name=name)
        self.assertEqual([e["name"] for e in self.store.load(self.transaction_id).actions],
                         ["stage", "build"])

    def test_malformed_arguments_are_refused_before_any_lock(self):
        effect = self.effect(during=self.fail)
        cases = ({"name": "", "parameters": {}, "effect": effect},
                 {"name": "b", "parameters": [], "effect": effect},
                 {"name": "b", "parameters": {"x": float("nan")}, "effect": effect},
                 {"name": "b", "parameters": {}, "effect": object()})
        with open(self.root / self.transaction_id / "lock", "r+") as holder:
            fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
            for kwargs in cases:
                with self.subTest(kwargs=kwargs):
                    self.assertRefusedUnchanged(StateInvalid, lambda: self.store.inspect_action(
                        self.custody, **kwargs))
            self.assertRefusedUnchanged(StateInvalid, lambda: self.store.inspect_action(
                "not custody", name="b", parameters={}, effect=effect))

    def test_a_malformed_inspect_result_is_refused_with_nothing_recorded(self):
        class Returning(FakeEffect):
            def inspect(self, request):
                return self.inspect_outcome

        for result in (None, {"outcome": "absent"}, {"outcome": "gone", "reference": "r"},
                       {"outcome": "absent", "reference": ""},
                       {"outcome": "absent", "reference": "r", "extra": 1}):
            with self.subTest(result=result):
                self.assertRefusedUnchanged(EffectResultInvalid, lambda: self.inspect(
                    Returning(self.world, inspect_outcome=result)))

    def test_stale_or_terminal_holders_are_refused_before_the_effect_runs(self):
        self.clock.advance(TTL)
        self.assertRefusedUnchanged(StaleCustody,
                                    lambda: self.inspect(self.effect(during=self.fail)))
        self.clock.advance(-TTL)
        self.to("abandoned")
        self.assertRefusedUnchanged(TransitionRefused,
                                    lambda: self.inspect(self.effect(during=self.fail)))

    def test_a_lease_lapse_during_the_call_records_nothing(self):
        self.assertRefusedUnchanged(StaleCustody, lambda: self.inspect(
            self.effect(during=lambda: self.clock.advance(TTL))))

    def test_hand_edited_action_histories_fail_the_named_rule(self):
        self.inspect()
        good = self.state_doc(self.transaction_id)
        released = {"type": "lease_released", "at": good["events"][2]["at"],
                    "fence": plain(self.custody.fence), "reason": "released"}

        def edit(change):
            document = copy.deepcopy(good)
            change(document["events"])
            return renumbered(document)

        cases = {
            "does not re-derive from its name and parameters":
                lambda ev: ev[2].update(name="stage"),
            "is declared twice": lambda ev: ev.append(copy.deepcopy(ev[2])),
            "has no earlier action_declared": lambda ev: ev.pop(2),
            "action_id is not a string": lambda ev: ev[3].update(action_id=["x"]),
            "outcome is not absent, in_progress, satisfied, diverged or unknown":
                lambda ev: ev[3].update(outcome="gone"),
            "reference is not a non-empty string": lambda ev: ev[3].update(reference=""),
            "fence does not equal the open span's fence":
                lambda ev: ev[3].update(fence=OTHER_FENCE),
            "sits outside an open custody span": lambda ev: ev.insert(2, dict(released)),
            "is not the closed action_inspected event": lambda ev: ev[3].update(extra=1),
        }
        for fragment, change in cases.items():
            with self.subTest(fragment=fragment):
                self.assertRuleRefuses(self.transaction_id, edit(change), fragment)
```

  In `tests/test_transaction_core.py`: the created-document assertion's
  `"transaction-state/v2"` becomes `"transaction-state/v3"`, and the `"wrong schema"` case's
  `"transaction-state/v3"` becomes `"transaction-state/v2"`.

- [ ] **Step 2: Run the tests and watch them fail**

Run: `PYTHONPATH=python python3 -m unittest tests/test_transaction_invocation.py 2>&1 | tail -3`
Expected: FAIL — `AttributeError: 'TransactionStore' object has no attribute 'inspect_action'`
and the v3 schema assertion.

- [ ] **Step 3: Implement**

  1. Invocation: add the names under **Produces** with the rules under **Invariants**.
     `action_event_violation` checks, in order: `action_id` is a `str`; for
     `action_declared` the three declared rules; otherwise the id is declared; for events
     carrying `fence`, `fence_violation(fence, keys)`, then open span, then equality; then
     the per-type field rules. `fold_actions` is `apply_action_event` over every event whose
     type is in `ACTION_EVENT_KEYS`.
  2. History: `SCHEMA = "transaction-state/v3"`; before the event loop `actions: dict = {}`;
     a `match` arm `case str() if event_type in ACTION_EVENT_KEYS:` runs
     `_check_envelope(event, seq, ACTION_EVENT_KEYS[event_type], refuse)`, then
     `action_event_violation(... open_fence=None if fold.custody is None else
     fold.custody["fence"], state=state)` (refuse as `f"event {seq} {violation}"`), then
     `apply_action_event`. `snapshot` sets `actions`. Update the module, `Transaction` and
     `validate_state` docstrings from v2 to v3 and name the derived `actions` view.
  3. Core: `inspect_action` per the invariants, using `_action_arguments` and `_append`;
     `_require_creatable`'s docstring says v3. Docstring of `inspect_action`: describe the
     two lock holds, the unlocked call and what is appended, from the implemented code.

- [ ] **Step 4: Verify**

Run: `PYTHONPATH=python python3 -m unittest tests/test_transaction_invocation.py tests/test_transaction_core.py tests/test_transaction_custody.py tests/test_transaction_core_sweep.py 2>&1 | tail -3`
Expected: `OK`.

Run: `wc -c < python/agent_tools/transaction_core.py` — Expected: ≤ 55000.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/transaction_invocation.py python/agent_tools/transaction_history.py \
  python/agent_tools/transaction_core.py tests/test_transaction_invocation.py \
  tests/test_transaction_core.py
git commit -m "feat(transaction-core): record action inspections under schema v3 (#206)"
```

Decisions: per D2, D3, D5, D8, D11, D13, D17.
