# Task 4: `begin_recovery`, effect classes and the `abandoned` gate

**Files:**
- Modify: `python/agent_tools/transaction_recovery.py`
- Modify: `python/agent_tools/transaction_history.py` (the recovery pairing)
- Modify: `python/agent_tools/transaction_core.py` (`begin_recovery`)
- Modify: `tests/test_transaction_recovery.py` (append, and two helpers on `RecoveryCase`)
- Modify: `tests/test_transaction_core.py` (the `recovering` source and `rolled_back` path)
- Modify: `tests/test_transaction_custody.py` (one test moves out)

**Interfaces:**
- Consumes (Tasks 1–3): `_observed`, `check_requests`, `unit_label`, `recovery_refused`,
  `RECOVERY_EVENT_KEYS`, `recovery_event_violation`, `recovery_transition_violation`,
  `recovery_advance_violation`; `transaction_invocation.fold_actions`, `status`,
  `ActionFold`; `RecoveryCase`, `Checker`, `Boom`.
- Produces (`agent_tools.transaction_recovery`; `EFFECT_CLASSES` is re-exported):
  - `EFFECT_CLASSES` (Global Constraints), and
    `RESERVED_RECOVERY_REASONS = ("recovery_started", "recovery_settled",
    "recovery_incomplete")`.
  - `effect_class(entry: ActionFold | None) -> str`.
  - `effect_snapshot(plan, actions) -> dict[str, str]` maps every plan unit's action id to
    its class.
  - `selection(plan, actions) -> list[str]` lists the edge action ids of every affected
    unit, in plan order and then declaration order.
  - `effecting_action(events) -> ActionFold | None` returns the first action, in
    declaration order, whose class is not `no_effect`. `no_effect(events) -> bool` is
    `effecting_action(events) is None`.
  - `fresh_grant(events, grant_id, fence) -> bool`.
  - `begin_refusal(document, grant_id) -> tuple[str, str] | None` returns `(reason, detail)`.
  - `begin_requests(document, grant_id) -> list[Mapping]` and
    `begin_events(document, grant_id, requests, results) -> list[dict]`.
  - `recovery_pairing_violation(previous: Mapping | None, event: Mapping | None) -> str | None`.
- Produces (`TransactionStore`): `begin_recovery(custody, *, grant_id: str, observer) ->
  Transaction`.
- Produces (`RecoveryCase`): `grant(grant_id="g-1")`, which calls `issue_grant(custody,
  grant_id=..., actor="operator")`, and `begin(grant_id="g-1", checker=None)`, which calls
  `begin_recovery(custody, grant_id=..., observer=checker or Checker())`.

**Invariants:**
- `effect_class` (per D8, D19): `no_effect` for None or `attempts == 0`, whatever the
  inspection says. Then `in_progress` while `open`. Then, by the latest inspection outcome,
  `absent` → `no_effect`, `satisfied` → `target_satisfied`, `diverged` → `diverged`,
  `in_progress` → `in_progress` and `unknown` → `unknown`. A unit is affected unless it is
  `no_effect`.
- `fresh_grant` holds when a `grant_issued` with `grant_id` and `fence == fence` has a
  `seq` greater than the latest `transitioned` event into `attention_required` (per D19).
- `begin_refusal` returns the first matching reason, in this order (per D8):
  1. `state_not_attention`;
  2. `grant_required`, when `not fresh_grant(events, grant_id, held fence)`;
  3. `reconciliation_required`, for the first action with `attempts > 0` that is `open` or
     whose latest inspection fence is not the held fence;
  4. `undeclared_effect`, for an action that is neither a plan unit nor a plan edge and is
     not `no_effect`;
  5. `effect_uncertain`, for an affected unit that is `in_progress` or `unknown`;
  6. `no_effect`, when no unit is affected;
  7. `unit_not_restorable`, for the first affected unit that is `supersedable_only` or
     `manual_only`.

  A detail naming a unit uses `unit_label`, and one naming an undeclared action uses its id.
- `begin_requests` raises `begin_refusal`'s reason (`recovery_refused`). Otherwise it
  returns `check_requests(document, "compatibility", <affected restorable units>)`.
  `begin_events` raises `restore_incompatible`, naming the first unit whose result is not
  `satisfied`. Otherwise it returns `[{"type": "recovery_started", "grant_id",
  "effect_snapshot", "selected", "checks": [{"unit", "reference"}...], "fence"},
  {"type": "transitioned", "from": "attention_required", "to": "recovering", "reason":
  "recovery_started", "external_state": "known"}]`. An admission with only compensatable
  affected units therefore writes in the first hold, with no call.
- `RECOVERY_EVENT_KEYS["recovery_started"]` is the envelope plus `{grant_id,
  effect_snapshot, selected, checks, fence}`. `recovery_event_violation` re-derives it from
  the document as of `events_before` (the same `state`, and custody fence `open_fence`)
  through the writer's functions (per D10):
  - `begin_refusal` must be None, else a rule naming its reason;
  - `effect_snapshot` must equal `effect_snapshot(...)` and `selected` must equal
    `selection(...)`, else rules containing those words;
  - `checks` units must be the affected restorable units in plan order, with non-empty
    references, else a rule containing `checks`.
- `recovery_pairing_violation` (per D10): `recovery_started` is immediately followed by
  `attention_required → recovering` with reason `recovery_started` and external state
  `known`. Every transition into `recovering` immediately follows `recovery_started`, and
  every transition whose reason is in `RESERVED_RECOVERY_REASONS` immediately follows its
  event. Each failure string contains `recovery_started` (for this task's rules). The
  history calls it beside `pairing_violation`, at every event and once past the end.
- `recovery_advance_violation` gains, before the gate: target `recovering` (a rule
  containing `begin_recovery`), any reason in `RESERVED_RECOVERY_REASONS`, and target
  `abandoned` while `effecting_action` names an action (through
  `recovery_transition_violation`, a rule containing `abandoned` and that action's id). The
  validator's transition rule gains the same `abandoned` check. Both run after the
  `unresolved` check (per D22).

- [ ] **Step 1: Write the failing tests.** Add `grant` and `begin` to `RecoveryCase` as
  **Produces** says, import `Crash` from `.test_transaction_invocation` and `serialize` from
  `.test_transaction_custody`, and append above
  `RecoveryVocabularyTest`:

```python
class BeginTest(RecoveryCase):
    def test_begin_freezes_the_snapshot_selects_every_edge_and_enters_recovering(self):
        self.parked()
        self.grant()
        after = self.begin()
        started, moved = (dict(e) for e in after.events[-2:])
        build, start, pin = self.act("build", n=1), self.act("start", n=2), self.act("pin", n=3)
        self.assertEqual(started["effect_snapshot"], {
            build: "target_satisfied", start: "diverged", pin: "no_effect"})
        self.assertEqual(started["selected"], [
            self.act("compensate", unit="build"), self.act("restore", unit="start"),
            self.act("compensate", unit="start")])
        self.assertEqual([check["unit"] for check in started["checks"]], [start])
        self.assertEqual((started["grant_id"], started["fence"]),
                         ("g-1", plain(self.custody.fence)))
        self.assertEqual((moved["from"], moved["to"], moved["reason"], moved["external_state"]),
                         ("attention_required", "recovering", "recovery_started", "known"))
        self.assertEqual(after.state, "recovering")
        self.assertEqual((dict(after.recovery["effect_snapshot"]), list(after.recovery["selected"])),
                         (started["effect_snapshot"], started["selected"]))

    def test_an_affected_compensatable_unit_alone_needs_no_check(self):
        self.published()
        self.to("attention_required")
        self.grant()
        after = self.begin(checker=Checker(fail=Boom()))
        self.assertEqual(list(after.recovery["selected"]), [self.act("compensate", unit="build")])
        self.assertEqual(after.events[-2]["checks"], [])

    def test_begin_outside_attention_or_without_a_fresh_grant_is_refused(self):
        self.to("awaiting_verification")
        self.grant("early")
        self.refused("state_not_attention", lambda: self.begin("early"))
        self.to("attention_required")
        self.refused("grant_required", lambda: self.begin("early"))
        self.refused("grant_required", lambda: self.begin("never-issued"))

    def test_an_action_inspected_under_an_older_fence_needs_reconciliation(self):
        self.parked()
        self.clock.advance(TTL)
        self.store.reap(self.transaction_id, reason="executor lost")
        self.custody = self.acquire(self.transaction_id)
        self.grant()
        self.refused("reconciliation_required", lambda: self.begin(checker=Checker(fail=Boom())))
        for name, parameters in (("build", {"n": 1}), ("start", {"n": 2})):
            self.store.inspect_action(self.custody, name=name, parameters=parameters,
                                      effect=FakeEffect(self.world))
        self.assertEqual(self.begin().state, "recovering")

    def test_an_open_attempt_needs_reconciliation(self):
        self.published()
        self.to("published", "activating")
        self.store.inspect_action(self.custody, name="start", parameters={"n": 2},
                                  effect=FakeEffect(self.world))
        with self.assertRaises(Crash):
            self.store.invoke_action(self.custody, name="start", parameters={"n": 2},
                                     effect=FakeEffect(self.world, crash="before"))
        self.to("attention_required")
        self.grant()
        self.refused("reconciliation_required", lambda: self.begin(checker=Checker(fail=Boom())))

    def test_an_undeclared_effect_or_an_uncertain_unit_is_refused(self):
        self.published()
        self.run("extra", {"n": 9})
        self.to("attention_required")
        self.grant()
        self.refused("undeclared_effect", lambda: self.begin(checker=Checker(fail=Boom())))
        for outcome in ("unknown", "in_progress"):
            with self.subTest(outcome=outcome):
                self.start_with(RECOVERY, key=outcome, keys=(f"key:{outcome}",))
                self.parked(start=outcome)
                self.grant()
                error = self.refused("effect_uncertain",
                                     lambda: self.begin(checker=Checker(fail=Boom())))
                self.assertIn(self.act("start", n=2), str(error))

    def test_no_affected_unit_is_refused_no_effect(self):
        self.to("awaiting_verification", "ready")
        self.verify()
        self.to("attention_required")
        self.grant()
        self.refused("no_effect", lambda: self.begin(checker=Checker(fail=Boom())))

    def test_an_affected_non_restorable_unit_is_refused_before_any_check(self):
        self.parked(pin="diverged")
        self.grant()
        error = self.refused("unit_not_restorable",
                             lambda: self.begin(checker=Checker(fail=Boom())))
        self.assertIn(f"pin ({self.act('pin', n=3)})", str(error))
        self.start_with(with_unit(1, posture="supersedable_only", anchor=None,
                                  compatibility=None, edges=[]),
                        key="forward-only", keys=("key:forward-only",))
        self.parked()
        self.grant()
        error = self.refused("unit_not_restorable",
                             lambda: self.begin(checker=Checker(fail=Boom())))
        self.assertIn("start (", str(error))

    def test_an_incompatible_restore_is_refused_after_the_check(self):
        self.parked()
        self.grant()
        for outcome in ("unsatisfied", "unknown"):
            with self.subTest(outcome=outcome):
                error = self.refused("restore_incompatible", lambda: self.begin(
                    checker=Checker({"compatibility": outcome})))
                self.assertIn("start (", str(error))

    def test_a_history_grown_during_the_check_is_refused(self):
        self.parked()
        self.grant()
        grow = lambda: self.store.issue_grant(self.custody, grant_id="during", actor="op")
        with self.assertRaises(RecoveryRefused) as caught:
            self.begin(checker=Checker(during=grow))
        self.assertEqual(caught.exception.reason, "history_changed")
        self.assertEqual(self.store.load(self.transaction_id).state, "attention_required")

    def test_moving_into_recovering_does_not_restart_the_quiescence_window(self):
        self.parked()
        self.grant()
        self.clock.advance(400_000)
        self.store.renew(self.custody)
        self.begin()
        self.clock.advance(400_000)
        self.store.renew(self.custody)
        self.clock.advance(100_001)
        self.assertIsNone(self.store.renew(self.custody).custody)


class AbandonAndReservedTest(RecoveryCase):
    def test_abandoned_needs_every_action_without_effect(self):
        self.parked()
        error = self.assertRefusedUnchanged(TransitionRefused, lambda: self.to("abandoned"))
        self.assertIn(self.act("build", n=1), str(error))

    def test_an_inspected_but_never_invoked_action_has_no_effect(self):
        self.to("awaiting_verification", "ready")
        self.verify()
        self.to("publishing")
        self.store.inspect_action(self.custody, name="build", parameters={"n": 1},
                                  effect=FakeEffect(self.world, inspect_outcome="satisfied"))
        self.to("attention_required")
        self.assertEqual(self.to("abandoned").state, "abandoned")

    def test_advance_never_enters_recovering_nor_writes_recovery_started(self):
        self.parked()
        error = self.assertRefusedUnchanged(TransitionRefused, lambda: self.to("recovering"))
        self.assertIn("begin_recovery", str(error))
        self.assertRefusedUnchanged(TransitionRefused,
                                    lambda: self.to("activating", reason="recovery_started"))

    def test_hand_built_recovery_breaches_are_state_invalid(self):
        self.parked()
        parked = self.state_doc(self.transaction_id)
        at = parked["events"][-1]["at"]

        def moved(document, target):
            document = copy.deepcopy(document)
            document["events"].append({"seq": 0, "type": "transitioned", "at": at,
                                       "from": "attention_required", "to": target,
                                       "reason": "r", "external_state": "known"})
            document.update(state=target, parked_from=None)
            return renumbered(document)

        self.assertRuleRefuses(self.transaction_id, moved(parked, "abandoned"),
                               self.act("build", n=1))
        self.assertRuleRefuses(self.transaction_id, moved(parked, "recovering"),
                               "recovery_started")
        (self.root / self.transaction_id / "state.json").write_text(serialize(parked))
        self.grant()
        self.begin()
        begun = self.state_doc(self.transaction_id)
        pin = self.act("pin", n=3)
        for field, value, fragment in (
                ("effect_snapshot", {**begun["events"][-2]["effect_snapshot"], pin: "diverged"},
                 "effect_snapshot"),
                ("selected", begun["events"][-2]["selected"][:1], "selected"),
                ("checks", [], "checks"),
                ("grant_id", "never-issued", "grant_required")):
            with self.subTest(field=field):
                edited = copy.deepcopy(begun)
                edited["events"][-2][field] = value
                self.assertRuleRefuses(self.transaction_id, edited, fragment)
```

  The `write_text(serialize(parked))` line restores the parked document that the two
  rejected edits left behind.

  Existing tests (per D24):
  - `tests/test_transaction_core.py`: remove `"recovering"` from `PATHS_TO` and
    `"rolled_back"` from `PATHS_TO_TERMINAL`. In
    `test_every_allowed_edge_is_accepted_and_every_other_target_refused`, the
    `attention_required` allowed set becomes `{"created", "abandoned", "failed"}`. In
    `test_a_valid_hand_built_history_loads`, keep only the `abandoned` path, and add a check
    that `with_history(base, "attention_required", "recovering", "rolled_back")` raises
    `StateInvalid` mentioning `recovery_started`.
  - `tests/test_transaction_custody.py`: delete
    `test_moving_between_parkings_does_not_restart_the_window`, which moves here as
    `test_moving_into_recovering_does_not_restart_the_quiescence_window`.

- [ ] **Step 2: Run the tests and watch them fail.**
  Run: `PYTHONPATH=python python3 -m unittest tests/test_transaction_recovery.py 2>&1 | tail -3`.
  Expected: ERRORs, because `TransactionStore` has no `begin_recovery`.

- [ ] **Step 3: Implement** the invariants. `begin_recovery` refuses a malformed credential
  or a `grant_id` that is not a non-empty string (`require_texts`) before any lock, then it
  is `_observed(custody, "begin_recovery", observer, <begin_requests bound to grant_id>,
  <begin_events bound to grant_id>)`. Write its docstring, and update the `advance` and
  module docstrings, from the resulting code.

- [ ] **Step 4: Verify.**
  Run the slice unit command with both recovery test files. Expected: `OK`.

```bash
if grep -n '"recovering": ("attention_required", "recovering")' tests/test_transaction_core.py; then exit 1; fi
if grep -n "test_moving_between_parkings_does_not_restart_the_window" tests/test_transaction_custody.py; then exit 1; fi
grep -q "def begin_recovery" python/agent_tools/transaction_core.py || exit 1
```

  Run: `git add -A python tests && just build 2>&1 | tail -3`. Expected: success.

- [ ] **Step 5: Commit.** Stage exactly this task's **Files**, then:

```bash
git commit -m "feat(transaction-core): enter recovery through begin_recovery alone (#208)"
```

- [ ] **Step 6: Check the review budget** with `FILES="python/agent_tools/transaction_recovery.py python/agent_tools/transaction_history.py python/agent_tools/transaction_core.py tests/test_transaction_recovery.py tests/test_transaction_core.py tests/test_transaction_custody.py"`.
  Expected: exit 0.

Decisions: per D8, D10, D16, D19, D20, D22, D23, D24.
