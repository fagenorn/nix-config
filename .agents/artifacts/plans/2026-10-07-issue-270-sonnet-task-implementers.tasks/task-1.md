# Task 1: Sonnet task-implementer role and the per-task dispatch

Per D1 and D6. Adds the role and re-points the existing per-task site; the two new
fix-loop/BLOCKED sites belong to Task 2.

**Files:**
- Modify: `python/agent_tools/agent_model_matrix.py`
- Modify: `home/common/agent-skills/model-matrix.json`
- Modify: `home/common/agent-skills/skills/sdd/implementer-prompt.md` (lines 14–15)
- Modify: `home/common/agent-skills/instruction-load.json` (ceilings only, via the Global Constraints ceiling procedure)
- Test: `home/common/agent-skills/tests/test_agent_model_matrix.py`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: matrix role `task-implementer` = `{"model": "sonnet", "effort": "high", "eligible": ["planned task implementation", "task fix rounds 1–3"], "prohibited": ["deterministic mechanical work", "stuck-task escalation"]}`; validator constants `EXPECTED_ROLE_TIERS["task-implementer"] == ("sonnet", "high")` and `ALLOWED_SUBAGENT_TYPES["task-implementer"] == {"implementer"}`; test helpers `EXPECTED_TIERS`, `EXPECTED_SUBAGENT_TYPES`, `EXPECTED_SDD_SITES` and the new test method `test_task_implementer_is_a_sonnet_role_on_the_opus_implementer_type`, which Task 2 extends.

**Invariants:**
- `CUSTOM_AGENT_ROLES` stays exactly `{"implementer", "reviewer", "reviewer-lite", "mechanic"}`; no agent file is added or edited.
- `implementer` stays `("opus", "high")`; its matrix `eligible` list becomes `["non-mechanical implementation", "stuck-task escalation"]` (per D6); its `prohibited` list is unchanged.
- Site `sdd-nonmechanical-implementation` keeps its id and path; its role/model/effort become `task-implementer`/`sonnet`/`high`, and the same selection appears in its `sdd` and `representative` scenario events.
- Every other dispatch site and scenario event is byte-unchanged.

- [ ] **Step 1: Write the failing tests**

In `test_agent_model_matrix.py`:

1. Add `"task-implementer": ("sonnet", "high"),` to `EXPECTED_TIERS` directly after the `"implementer"` entry.
2. Add `"task-implementer": {"implementer"},` to `EXPECTED_SUBAGENT_TYPES` directly after the `"implementer"` entry.
3. Change the `EXPECTED_SDD_SITES["sdd-nonmechanical-implementation"]` tuple to:

```python
    "sdd-nonmechanical-implementation": (
        "home/common/agent-skills/skills/sdd/implementer-prompt.md",
        "task-implementer",
        "sonnet",
        "high",
        [],
    ),
```

4. Add this method to `AgentModelMatrixTest`, directly after `test_sdd_dispatches_select_exact_tiers`:

```python
    def test_task_implementer_is_a_sonnet_role_on_the_opus_implementer_type(self):
        data = json.loads(MATRIX.read_text(encoding="utf-8"))
        roles = data["roles"]
        self.assertEqual(
            roles["task-implementer"]["eligible"],
            ["planned task implementation", "task fix rounds 1–3"],
        )
        self.assertEqual(
            roles["task-implementer"]["prohibited"],
            ["deterministic mechanical work", "stuck-task escalation"],
        )
        self.assertEqual(
            roles["implementer"]["eligible"],
            ["non-mechanical implementation", "stuck-task escalation"],
        )
        # No new agent file: an implementer dispatch that omitted its model
        # still runs on the definition's Opus/high.
        self.assertEqual(
            agent_model_matrix.CUSTOM_AGENT_ROLES,
            {"implementer", "reviewer", "reviewer-lite", "mechanic"},
        )
        definition = frontmatter(AGENTS / "implementer.md")
        self.assertEqual((definition["model"], definition["effort"]), ("opus", "high"))

        by_role = {}
        for site in data["dispatch_sites"]:
            by_role.setdefault(site["role"], set()).add(site["id"])
            if site["role"] in ("task-implementer", "implementer"):
                model = "sonnet" if site["role"] == "task-implementer" else "opus"
                self.assertTrue(
                    site["call"].startswith(
                        f'Agent(subagent_type="implementer", model="{model}", '
                        'effort="high")'
                    ),
                    site["id"],
                )
        self.assertEqual(
            by_role["task-implementer"], {"sdd-nonmechanical-implementation"}
        )
        self.assertEqual(
            by_role["implementer"],
            {
                "sdd-post-rescue-implementation",
                "sdd-rescue-fallback-implementation",
                "sdd-round-five-implementation",
                "sdd-final-review-fixer",
            },
        )
        for scenario in ("sdd", "representative"):
            events = [
                event
                for event in agent_model_matrix.trace(REPO_ROOT, scenario)
                if event["dispatch"] == "sdd-nonmechanical-implementation"
            ]
            self.assertEqual(len(events), 1, scenario)
            self.assertEqual(
                (events[0]["role"], events[0]["model"], events[0]["effort"]),
                ("task-implementer", "sonnet", "high"),
                scenario,
            )
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_agent_model_matrix.py 2>&1 | tail -5`
Expected: FAIL — `test_executable_subagent_type_mapping_is_exhaustive`, `test_matrix_declares_the_exact_closed_role_tiers`, `test_sdd_dispatches_select_exact_tiers` and the new test fail (no `task-implementer` role yet).

- [ ] **Step 3: Implement**

1. `agent_model_matrix.py`: add `"task-implementer": ("sonnet", "high"),` to `EXPECTED_ROLE_TIERS` and `"task-implementer": {"implementer"},` to `ALLOWED_SUBAGENT_TYPES`, each directly after its `"implementer"` entry. Nothing else in the module changes.
2. `model-matrix.json` `roles`: insert the `task-implementer` object from **Produces** directly after `implementer`, and append `"stuck-task escalation"` to `implementer.eligible`.
3. `model-matrix.json` `dispatch_sites`, row `sdd-nonmechanical-implementation`: set `"role": "task-implementer"`, `"model": "sonnet"`, and
   - `"marker": "<!-- agent-dispatch: id=sdd-nonmechanical-implementation role=task-implementer model=sonnet effort=high -->"`
   - `"call": "Agent(subagent_type=\"implementer\", model=\"sonnet\", effort=\"high\") executes the task from this prompt."`
4. `model-matrix.json` `scenarios.sdd` and `scenarios.representative`: in each event whose `dispatch` is `sdd-nonmechanical-implementation`, set `"role": "task-implementer"` and `"model": "sonnet"`.
5. `sdd/implementer-prompt.md` lines 14–15 become exactly the marker and call from item 3 (the call line unescaped: `Agent(subagent_type="implementer", model="sonnet", effort="high") executes the task from this prompt.`).
6. Run the Global Constraints ceiling procedure; the note sentence is `Ceiling raised for #270: sdd's per-task implementer dispatch selects the Sonnet task-implementer role (#155 D10).`

- [ ] **Step 4: Verify**

Run: `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_agent_model_matrix.py home/common/agent-skills/tests/test_instruction_load.py tests/test_agent_model_drift_routing.py tests/test_agent_model_drift_schema.py 2>&1 | tail -3`
Expected: `OK`.

Run: `PYTHONPATH=python python3 -m agent_tools.agent_model_matrix validate --root .`
Expected: `agent model matrix: valid`.

Run (fails at the base commit, where the marker says `role=implementer model=opus`): `grep -qx '<!-- agent-dispatch: id=sdd-nonmechanical-implementation role=task-implementer model=sonnet effort=high -->' home/common/agent-skills/skills/sdd/implementer-prompt.md || exit 1`
Expected: exit 0.

Run: `git diff --quiet <BASE> -- home/common/claude-code/agents || exit 1` (BASE = the commit this task started from)
Expected: exit 0 — no agent definition changed.

Run (the module is built into the Nix Python environment): `just build` with an explicit timeout of 3000000 ms.
Expected: success.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/agent_model_matrix.py home/common/agent-skills/model-matrix.json \
  home/common/agent-skills/skills/sdd/implementer-prompt.md \
  home/common/agent-skills/instruction-load.json \
  home/common/agent-skills/tests/test_agent_model_matrix.py
git commit -m "feat(matrix): route sdd per-task implementation to a Sonnet task-implementer role (#270)"
```
