# Task 3: sdd agent tiers and the re-evaluation rule

Per D1, D2 and D4. Rewords sdd's `## Agent tiers` section for the two-tier
implementer type and records the rule a later reviewer applies to keep or revert
Sonnet task implementers.

**Files:**
- Modify: `home/common/agent-skills/skills/sdd/SKILL.md` (`## Agent tiers` section only)
- Modify: `home/common/agent-skills/instruction-load.json` (ceilings only, via the Global Constraints ceiling procedure)
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes (Task 2): class `SonnetTaskImplementerContractsTest` with its `assert_ordered` and `read` helpers; site ids `sdd-nonmechanical-implementation` and `sdd-task-fix-redispatch` (the two `task-implementer` sites the revert names).
- Produces: nothing later tasks consume.

**Invariants:**
- The section still opens with `## Agent tiers`, keeps the `mechanic`, `reviewer`, `reviewer-lite` and final-review bullets byte-unchanged, and keeps the `**Leaf-agent clauses.**` paragraph and its quoted clauses byte-unchanged (`test_dispatch_contracts.py` reads that section as a carrier).
- The re-evaluation rule's values are exactly D4's: 84% baseline over 153 full-lane first-pass reviews, about 10 delivered issues, a 30-review sample floor, revert below 74%.
- No new `Agent(` line is added.

- [ ] **Step 1: Write the failing test**

Add this method to `SonnetTaskImplementerContractsTest` in `test_workflow_skill_contracts.py`:

```python
    def test_sdd_agent_tiers_carry_the_re_evaluation_rule(self):
        tiers = self.read(SDD).split("## Agent tiers", 1)[1].split("## The task loop", 1)[0]
        self.assert_ordered(
            tiers,
            "with the model and effort its dispatch site declares",
            "an `implementer` dispatch that omitted its model would run on its "
            "definition's Opus/high",
            "A planned task and its fix rounds 1–3 run on Sonnet/high (the "
            "`task-implementer` role)",
            "fix rounds 4–5 and a reasoning-problem BLOCKED — and the final-review "
            "fixer run on Opus/high (the `implementer` role)",
            "**Stuck tasks escalate across models, not just tiers** — Sonnet → Opus",
            "**Re-evaluating Sonnet task implementers.**",
            "*Metric:* the first-pass approval rate of full-lane task reviews",
            "spec ✅ and no Critical or Important finding",
            "*Baseline:* Opus/high implementers, about 84% first-pass approval "
            "across 153 full-lane first-pass reviews",
            "*When:* after about 10 delivered issues",
            "at least 30 full-lane first-pass reviews",
            "*Decision:* below 74%",
            "`sdd-nonmechanical-implementation` and `sdd-task-fix-redispatch`",
            "retiring the `task-implementer` role",
            "between 74% and 84% is reported but is not a revert trigger",
            "**Leaf-agent clauses.**")
        self.assertNotIn("the definitions carry the model and effort tier", tiers)
```

- [ ] **Step 2: Run the test and watch it fail**

Run: `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py -k re_evaluation 2>&1 | tail -5`
Expected: FAIL — the first anchor is absent.

- [ ] **Step 3: Implement**

In `sdd/SKILL.md` `## Agent tiers`:

1. Replace the opening line `Dispatch by agent type — the definitions carry the model and effort tier; never leave the tier to inheritance:` with exactly:

```markdown
Dispatch by agent type, with the model and effort its dispatch site declares; never leave the tier to inheritance — an `implementer` dispatch that omitted its model would run on its definition's Opus/high:
```

2. Replace the `implementer` bullet with exactly:

```markdown
- **`implementer`** — every other implementation task: prose-specified work, multi-file integration, judgment inside a fixed scope. A planned task and its fix rounds 1–3 run on Sonnet/high (the `task-implementer` role); a stuck task's escalations — fix rounds 4–5 and a reasoning-problem BLOCKED — and the final-review fixer run on Opus/high (the `implementer` role).
```

3. Replace the `Stuck tasks` bullet with exactly:

```markdown
- **Stuck tasks escalate across models, not just tiers** — Sonnet → Opus: see the fix loop's rounds 4–5 and the BLOCKED handling under the task loop.
```

4. Directly after the line beginning `Turn count beats token price:` and before `**Leaf-agent clauses.**`, insert this paragraph and list (blank line before and after):

```markdown
**Re-evaluating Sonnet task implementers.** Sonnet/high task implementers replaced Opus/high on 2026-10-07. Judge that choice by this rule alone:

- *Metric:* the first-pass approval rate of full-lane task reviews of tasks a `task-implementer` implemented — the share whose first-pass review needed no fix round (spec ✅ and no Critical or Important finding).
- *Baseline:* Opus/high implementers, about 84% first-pass approval across 153 full-lane first-pass reviews, measured before 2026-10-07.
- *When:* after about 10 delivered issues under this routing, and only once the sample holds at least 30 full-lane first-pass reviews; below that floor, keep going.
- *Decision:* below 74% (ten points under the baseline) is clearly worse — revert by pointing the `sdd-nonmechanical-implementation` and `sdd-task-fix-redispatch` sites back at the `implementer` role and retiring the `task-implementer` role. At or above 74%, keep Sonnet; a rate between 74% and 84% is reported but is not a revert trigger.
```

5. Run the Global Constraints ceiling procedure; the note sentence is `Ceiling raised for #270: sdd's agent tiers name the Sonnet task implementer and carry its re-evaluation rule (#155 D10).`

- [ ] **Step 4: Verify**

Run: `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py home/common/agent-skills/tests/test_dispatch_contracts.py home/common/agent-skills/tests/test_instruction_load.py home/common/agent-skills/tests/test_agent_model_matrix.py 2>&1 | tail -3`
Expected: `OK`.

Run (fails at the base commit, where the rule is absent): `grep -q '^\*\*Re-evaluating Sonnet task implementers.\*\*' home/common/agent-skills/skills/sdd/SKILL.md || exit 1`
Expected: exit 0.

Run (skill files are part of the built home-manager tree): `just build` with an explicit timeout of 3000000 ms.
Expected: success.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/skills/sdd/SKILL.md home/common/agent-skills/instruction-load.json \
  home/common/agent-skills/tests/test_workflow_skill_contracts.py
git commit -m "docs(sdd): name Sonnet task implementers and record the re-evaluation rule (#270)"
```
