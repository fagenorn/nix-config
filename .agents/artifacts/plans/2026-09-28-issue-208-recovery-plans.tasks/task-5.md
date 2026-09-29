# Task 5: Recovery edges through the administrative protocol

**Files:**
- Modify: `python/agent_tools/transaction_invocation.py` (`EFFECT_STATES`, `REFUSAL_REASONS`,
  one message)
- Modify: `python/agent_tools/transaction_recovery.py` (`selection_refusal`)
- Modify: `python/agent_tools/transaction_history.py` (the validator applies it)
- Modify: `python/agent_tools/transaction_core.py` (`invoke_action`)
- Modify: `tests/test_transaction_recovery.py` (append)
- Modify: `tests/test_transaction_invocation.py` (the pinned vocabulary, one message key
  and one test name)

**Interfaces:**
- Consumes (Tasks 1–4): `begin_recovery`, the latest `recovery_started`'s `selected`, the
  plan's edge `action_id`s, `RecoveryCase` with `grant`, `begin` and `run`.
- Produces:
  - `transaction_invocation.EFFECT_STATES = ("publishing", "activating", "recovering")`, and
    `REFUSAL_REASONS` gains `"not_selected"` as its last member.
  - `transaction_recovery.selection_refusal(recovery_plan, events, state, identity) ->
    str | None`, which returns `"not_selected"` or None.

**Invariants:**
- `selection_refusal` returns `not_selected` in two cases (per D15). In `recovering`, it
  refuses an `identity` absent from the latest `recovery_started`'s `selected`. In any other
  state, it refuses an `identity` that is one of the plan's edge action ids. Otherwise it
  returns None, so undeclared actions stay invocable in `publishing` and `activating`.
- `invoke_action`'s first hold checks, in order: the terminal refusal and fenced check,
  `state_not_effectful`, then `not_selected`, then the satisfied no-op, then the #206 rules
  (per D22). Each refusal comes before any write or call. The docstring is updated from the
  resulting code.
- The validator applies `selection_refusal` to every `invocation_intended`, after
  `action_event_violation`, with the plan, the events before it and the folded state. Its
  rule is `f"invocation_intended of {action_id} is not_selected in {state}"`.
- `action_event_violation`'s state rule now reads `"invocation_intended sits outside
  publishing, activating and recovering"`.
- Recovery edges otherwise inherit #206's intent, inspection and retry budget unchanged.

- [ ] **Step 1: Write the failing tests.** Append to `tests/test_transaction_recovery.py`
  above `RecoveryVocabularyTest` (import `InvocationRefused` from `transaction_core`):

```python
class EdgeTest(RecoveryCase):
    def recovering(self):
        self.parked()
        self.grant()
        return self.begin()

    def invoke(self, name, parameters):
        return self.store.invoke_action(self.custody, name=name, parameters=parameters,
                                        effect=FakeEffect(self.world))

    def not_selected(self, call):
        error = self.assertRefusedUnchanged(InvocationRefused, call)
        self.assertEqual(error.reason, "not_selected")

    def test_a_selected_edge_runs_through_intent_and_inspection(self):
        self.recovering()
        after = self.run("restore", {"unit": "start"})
        view = next(v for v in after.actions if v["action_id"] == self.act("restore", unit="start"))
        self.assertEqual((view["status"], view["attempts"]), ("satisfied", 1))
        again = self.invoke("restore", {"unit": "start"})
        self.assertEqual(again.revision, after.revision)

    def test_forward_or_unselected_actions_are_refused_in_recovering(self):
        self.recovering()
        for name, parameters in (("build", {"n": 1}), ("pin", {"n": 3}),
                                 ("extra", {"n": 9})):
            with self.subTest(name=name):
                self.store.inspect_action(self.custody, name=name, parameters=parameters,
                                          effect=FakeEffect(self.world))
                self.not_selected(lambda: self.invoke(name, parameters))

    def test_a_plan_edge_is_refused_outside_recovering(self):
        self.published()
        self.store.inspect_action(self.custody, name="compensate",
                                  parameters={"unit": "build"}, effect=FakeEffect(self.world))
        self.not_selected(lambda: self.invoke("compensate", {"unit": "build"}))
        self.store.inspect_action(self.custody, name="extra", parameters={"n": 9},
                                  effect=FakeEffect(self.world))
        self.assertEqual(self.invoke("extra", {"n": 9}).state, "publishing")

    def test_a_hand_built_intent_of_an_unselected_edge_is_state_invalid(self):
        self.published()
        self.store.inspect_action(self.custody, name="compensate",
                                  parameters={"unit": "build"}, effect=FakeEffect(self.world))
        document = self.state_doc(self.transaction_id)
        document["events"].append({
            "seq": 0, "type": "invocation_intended", "at": document["events"][-1]["at"],
            "action_id": self.act("compensate", unit="build"), "attempt": 1,
            "fence": plain(self.custody.fence)})
        self.assertRuleRefuses(self.transaction_id, renumbered(document), "not_selected")

    def test_a_hand_built_intent_of_an_unselected_action_in_recovering_is_state_invalid(self):
        self.recovering()
        self.store.inspect_action(self.custody, name="pin", parameters={"n": 3},
                                  effect=FakeEffect(self.world))
        document = self.state_doc(self.transaction_id)
        document["events"].append({
            "seq": 0, "type": "invocation_intended", "at": document["events"][-1]["at"],
            "action_id": self.act("pin", n=3), "attempt": 1,
            "fence": plain(self.custody.fence)})
        self.assertRuleRefuses(self.transaction_id, renumbered(document),
                               "is not_selected in recovering")
```

  In `tests/test_transaction_invocation.py`, add `"not_selected"` to `OBSERVED_REASONS`
  with a trailing comment `# asserted in test_transaction_recovery.py`. Rename the case key
  `"invocation_intended sits outside publishing and activating"` to the new message, and
  rename `test_only_publishing_and_activating_may_invoke` to
  `test_only_effect_states_may_invoke`, since `recovering` now invokes too.

- [ ] **Step 2: Run the tests and watch them fail.**
  Run: `PYTHONPATH=python python3 -m unittest tests/test_transaction_recovery.py 2>&1 | tail -3`.
  Expected: FAIL in `EdgeTest` (`state_not_effectful` in `recovering`, and no
  `not_selected` in `publishing`).

- [ ] **Step 3: Implement** the invariants.

- [ ] **Step 4: Verify.**
  Run the slice unit command with both recovery test files. Expected: `OK`.

```bash
grep -q '"not_selected"' python/agent_tools/transaction_invocation.py || exit 1
grep -q 'EFFECT_STATES = ("publishing", "activating", "recovering")' python/agent_tools/transaction_invocation.py || exit 1
```

  Run: `just build 2>&1 | tail -3`. Expected: success.

- [ ] **Step 5: Commit.** Stage exactly this task's **Files**, then:

```bash
git commit -m "feat(transaction-core): drive only selected recovery edges in recovering (#208)"
```

- [ ] **Step 6: Check the review budget** with `FILES="python/agent_tools/transaction_invocation.py python/agent_tools/transaction_recovery.py python/agent_tools/transaction_history.py python/agent_tools/transaction_core.py tests/test_transaction_recovery.py"`.
  Expected: exit 0.

Decisions: per D15, D22, D25.
