# Task 4: The implementer agent type is shared in cost telemetry

Per D5. `agent_costs._declaration` must stop inferring the `implementer` role from
the `implementer` subagent type alone, because that type now serves two roles.

**Files:**
- Modify: `python/agent_tools/agent_costs.py` (`_declaration`, around line 1268)
- Test: `tests/test_agent_costs.py` (class `ExecutionTelemetryRoutingTest`)

**Interfaces:**
- Consumes: nothing from other tasks (the cost tool deliberately does not read the matrix).
- Produces: `_declaration(value: dict, reasons: Counter) -> dict` with the same return shape `{"dispatch_id": str | None, "role": str | None, "authority": "structured-dispatch" | "runtime-agent-type" | "unknown"}`.

**Invariants:**
- A declared `role` that is canonical is accepted exactly as today; `task-implementer` is now canonical.
- Type-only inference never yields a role for a shared type: `reviewer`, `mechanic` and `implementer`. Such an observation is `role: None`, `authority: "unknown"`, counts one `role_ambiguous`, and also one `dispatch_missing` when it has no `dispatch_id`.
- Type-only inference for every other canonical type (e.g. `reviewer-lite`) is unchanged.

- [ ] **Step 1: Write the failing tests**

Add to `ExecutionTelemetryRoutingTest` in `tests/test_agent_costs.py`, directly after `test_unbounded_direct_projection_and_shared_transport_are_inconclusive`:

```python
    def test_the_shared_implementer_type_is_ambiguous_without_a_declared_role(self):
        reasons = agent_costs.Counter()
        self.assertEqual(agent_costs._declaration({"subagent_type": "implementer"}, reasons),
                         {"dispatch_id": None, "role": None, "authority": "unknown"})
        self.assertEqual(reasons["role_ambiguous"], 1)
        self.assertEqual(reasons["dispatch_missing"], 1)
        reasons = agent_costs.Counter()
        self.assertEqual(agent_costs._declaration({"subagent_type": "reviewer-lite"}, reasons),
                         {"dispatch_id": None, "role": "reviewer-lite",
                          "authority": "runtime-agent-type"})
        self.assertEqual(reasons["role_ambiguous"], 0)

    def test_a_declared_implementer_role_is_accepted_on_either_tier(self):
        for role in ("task-implementer", "implementer"):
            with self.subTest(role=role):
                reasons = agent_costs.Counter()
                self.assertEqual(
                    agent_costs._declaration({"subagent_type": "implementer", "role": role,
                                              "dispatch_id": "sdd-nonmechanical-implementation"},
                                             reasons),
                    {"dispatch_id": "sdd-nonmechanical-implementation", "role": role,
                     "authority": "structured-dispatch"})
                self.assertEqual(reasons["role_ambiguous"], 0)
                reasons = agent_costs.Counter()
                self.assertEqual(
                    agent_costs._declaration({"role": role}, reasons),
                    {"dispatch_id": None, "role": role, "authority": "runtime-agent-type"})
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `PYTHONPATH=python python3 -m unittest tests/test_agent_costs.py -k implementer 2>&1 | tail -5`
Expected: FAIL — `{"subagent_type": "implementer"}` is inferred as role `implementer`, and role `task-implementer` is not canonical.

- [ ] **Step 3: Implement**

In `_declaration`:
1. Add `"task-implementer"` to the `canonical` set literal.
2. Replace the type-only inference set `canonical - {"reviewer", "mechanic"}` with `canonical - {"implementer", "mechanic", "reviewer"}`.
3. Replace the comment's second sentence with: `These are the source's known canonical role spellings; an agent type that serves several roles (implementer, mechanic, reviewer) stays ambiguous without a declared role.`

Nothing else in the module changes.

- [ ] **Step 4: Verify**

Run: `PYTHONPATH=python python3 -m unittest tests/test_agent_costs.py tests/test_agent_model_drift_routing.py tests/test_agent_model_drift_producer_integration.py tests/test_agent_model_drift_scheduling.py 2>&1 | tail -3`
Expected: `OK`.

Run (the module is built into the Nix Python environment): `just build` with an explicit timeout of 3000000 ms.
Expected: success.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/agent_costs.py tests/test_agent_costs.py
git commit -m "fix(agent-costs): treat the implementer agent type as shared between two roles (#270)"
```
