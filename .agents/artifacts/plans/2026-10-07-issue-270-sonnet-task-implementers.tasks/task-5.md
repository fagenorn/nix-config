# Task 5: Living tier docs

Per D1 and D2. Two living documents still say every implementer dispatch runs on
Opus; point-in-time plans and specs are not edited.

**Files:**
- Modify: `home/common/claude-code/default.nix` (the comment above `home.file.".claude/agents"`, lines 250–254)
- Modify: `home/common/agent-skills/skills/sdd/evals/evals.json` (`expected_output` of the eval named `task-loop-and-fix-loop-discipline`)

**Interfaces:**
- Consumes: the routing Tasks 1–2 shipped (Sonnet/high task implementer for planned tasks and fix rounds 1–3; Opus/high for rounds 4–5, a reasoning-problem BLOCKED and the final-review fixer).
- Produces: nothing.

**Invariants:**
- Only comment text changes in `default.nix`; the Nix expression is unchanged.
- `evals.json` stays valid JSON, and only the one `expected_output` string changes.

- [ ] **Step 1: Confirm the stale text is present (the gate that must flip)**

Run: `grep -q 'implementer/reviewer (opus/high)' home/common/claude-code/default.nix && grep -q 'Three failed same-context rounds trigger the round-4 stuck-breaker:' home/common/agent-skills/skills/sdd/evals/evals.json && echo stale`
Expected: `stale`.

- [ ] **Step 2: Implement**

1. In `default.nix`, the comment lines

```nix
  # ~/.claude/agents/<name>.md — tiered pipeline agent definitions. Global
  # effortLevel stays xhigh for interactive/orchestrator sessions; pipeline
  # subagents dispatch explicitly as implementer/reviewer (opus/high),
  # mechanic (sonnet/high) or reviewer-lite (sonnet/medium). Skills reference
  # them by name; home/common/agent-skills/model-matrix.json owns every tier.
```

   become exactly

```nix
  # ~/.claude/agents/<name>.md — tiered pipeline agent definitions. Global
  # effortLevel stays xhigh for interactive/orchestrator sessions; pipeline
  # subagents dispatch explicitly as reviewer (opus/high), implementer
  # (sonnet/high for a planned sdd task and its first fix rounds, opus/high
  # for stuck-task escalation and the final-review fixer), mechanic
  # (sonnet/high) or reviewer-lite (sonnet/medium). Skills reference them by
  # name; home/common/agent-skills/model-matrix.json owns every tier.
```

2. In `evals.json`, inside that eval's `expected_output`, replace `(3) Three failed same-context rounds trigger the round-4 stuck-breaker:` with `(3) Rounds 1-3 stay on the Sonnet/high task implementer; three failed same-context rounds trigger the round-4 stuck-breaker, which escalates to Opus/high:`. The rest of the string, including both later `Opus/high implementer` mentions, is unchanged.

- [ ] **Step 3: Verify**

Run (fails before Step 2): `if grep -q 'implementer/reviewer (opus/high)' home/common/claude-code/default.nix; then exit 1; fi; grep -q 'Rounds 1-3 stay on the Sonnet/high task implementer' home/common/agent-skills/skills/sdd/evals/evals.json || exit 1`
Expected: exit 0.

Run: `python3 -m json.tool home/common/agent-skills/skills/sdd/evals/evals.json > /dev/null`
Expected: exit 0.

Run (a `.nix` file changed): `just build` with an explicit timeout of 3000000 ms.
Expected: success.

- [ ] **Step 4: Commit**

```bash
git add home/common/claude-code/default.nix home/common/agent-skills/skills/sdd/evals/evals.json
git commit -m "docs: name Sonnet task implementers in the living tier docs (#270)"
```
