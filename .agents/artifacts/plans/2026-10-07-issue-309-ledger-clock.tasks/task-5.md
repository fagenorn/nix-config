# Task 5: The `no-wait-loops` dispatch clause

**Files:**
- Test: `home/common/agent-skills/tests/test_dispatch_contracts.py`
- Modify (fence carriers): `home/common/agent-skills/skills/sdd/implementer-prompt.md`, `home/common/agent-skills/skills/sdd/task-reviewer-prompt.md`, `home/common/agent-skills/skills/sdd/re-review-prompt.md`, `home/common/agent-skills/skills/sdd/correctness-reviewer-prompt.md`, `home/common/agent-skills/skills/sdd/conformance-reviewer-prompt.md`, `home/common/agent-skills/skills/from-issue/ship-handoff.md`
- Modify (section and blockquote carriers): `home/common/agent-skills/skills/from-issue/SKILL.md`, `home/common/agent-skills/skills/sdd/SKILL.md`, `home/common/claude-code/skills/orchestrate-issues/SKILL.md`
- Modify (clause count): `home/common/agent-skills/skills/from-issue/AUTO.md`
- Modify: `home/common/agent-skills/instruction-load.json`, only if the gate asks for it (Step 4)

**Interfaces:**
- Consumes: Task 4's `HandBuiltTimeContractsTest`, which must stay green (no `--now` and no `"now":` in the new text).
- Produces: `CONTRACTS["no-wait-loops"]`, and `test_no_wait_loops` in `SourceTreeContractsTest` and `InstalledTreeContractsTest`.

**Invariants:**
- `CONTRACTS` gains exactly one entry, with the id `no-wait-loops` and this text:
  `Never write an \`until\` or \`while\` loop around \`sleep\` to wait for something: if a wait is truly needed, run one bounded foreground \`sleep N\`, then check once.`
  It is the one authoritative copy (D10).
- Each of the nine skill carriers holds that clause exactly once inside its rendered region, through the default `contracts` tuple. `AGENT_CLAUSES` stays `("own-commands",)`, so the four agent definitions do not gain it (D10).
- The clause occurs nowhere outside an enrolled region. `StrayCopyGuardTest` enforces this, and it also covers `home/common/agent-guidance/AGENTS.md`, so the guidance gets no copy.
- Every statement of the clause count says four: `REMAINDER_PLACEHOLDER`, ship-handoff's placeholder line and its explanation, from-issue's and sdd's "Leaf-agent clauses" rules, and AUTO.md's planning-owner list.

- [ ] **Step 1: Write the failing test**

In `test_dispatch_contracts.py`, add to `CONTRACTS` after `"own-commands"`:

```python
    "no-wait-loops": (
        "Never write an `until` or `while` loop around `sleep` to wait for "
        "something: if a wait is truly needed, run one bounded foreground "
        "`sleep N`, then check once."
    ),
```

Change `REMAINDER_PLACEHOLDER` to `"<the four leaf-agent clauses of the ship-owner prompt above, verbatim>"`. Add `def test_no_wait_loops(self): self.assert_contract_held("no-wait-loops")` to `SourceTreeContractsTest`, and `def test_no_wait_loops(self): self.assert_contract_installed("no-wait-loops")` to `InstalledTreeContractsTest`.

- [ ] **Step 2: Run the test and watch it fail**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_dispatch_contracts.py 2>&1 | tail -15`
Expected: FAIL. `test_no_wait_loops` reports each of the nine skill carriers as missing `no-wait-loops`, and the ship-handoff placeholder check reports the stale "three".

- [ ] **Step 3: Add the clause to each carrier**

Put the clause directly after that carrier's copy of the `own-commands` clause, in the same style:
- In the five sdd prompt templates and the ship-owner prompt in `ship-handoff.md`, use the same indentation and wrapping as the `own-commands` lines, as a sentence after "…still running.".
- In `from-issue/SKILL.md` (the `> ` line under **Leaf-agent clauses** in `## Dispatch, phase-budget and attempt-budget rules`) and `sdd/SKILL.md` (the `> ` line in `## Agent tiers`), append it to the end of the single quoted line.
- In `orchestrate-issues/SKILL.md`, add it inside the owner-prompt blockquote with a `> ` prefix on each wrapped line.

Then make the count four:
- `ship-handoff.md`: `<the three leaf-agent clauses …>` becomes `<the four leaf-agent clauses of the ship-owner prompt above, verbatim>`, and "those three clauses" becomes "those four clauses".
- `from-issue/SKILL.md` and `sdd/SKILL.md`: "carries these three clauses verbatim" becomes "carries these four clauses verbatim".
- `from-issue/AUTO.md`: "the three clauses of `SKILL.md`'s **Leaf-agent clauses** rule" becomes "the four clauses of …".

Run: `grep -rn -i "three leaf-agent\|these three clauses\|those three clauses\|the three clauses of" home/common/agent-skills/skills home/common/claude-code/skills || true`
Expected: no output.

- [ ] **Step 4: Verify**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_dispatch_contracts.py home/common/agent-skills/tests/test_workflow_skill_contracts.py home/common/agent-skills/tests/test_shell_example_contracts.py home/common/agent-skills/tests/test_skill_lint.py 2>&1 | tail -5` (timeout 900 s)
Expected: `OK`. `CheckerMutationTest` and `StrayCopyGuardTest` cover the new clause automatically, because they iterate `CONTRACTS`.

Run: `just agent-instruction-budget 2>&1 | tail -15` (timeout 600 s)
Expected: `check: pass`. If the gate reports a profile over its ceiling (`exceed ceiling`), the clause copies have outgrown what Task 4 cut. Raise each reported ceiling in `home/common/agent-skills/instruction-load.json` to the exact measured bytes the gate prints, then confirm with `just agent-instruction-budget --raise-label` (expected `check: pass`). Put `instruction-budget-raise needed` in the commit body, so that ship applies the label (spec, Skill and prompt text). If it prints a `tightness:` line instead, run `PYTHONPATH="$PWD/python" python3 -m agent_tools.instruction_load tighten` and re-run the gate. Then run `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_instruction_load.py 2>&1 | tail -3` and expect `OK`.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/tests/test_dispatch_contracts.py home/common/agent-skills/skills/sdd/implementer-prompt.md home/common/agent-skills/skills/sdd/task-reviewer-prompt.md home/common/agent-skills/skills/sdd/re-review-prompt.md home/common/agent-skills/skills/sdd/correctness-reviewer-prompt.md home/common/agent-skills/skills/sdd/conformance-reviewer-prompt.md home/common/agent-skills/skills/sdd/SKILL.md home/common/agent-skills/skills/from-issue/ship-handoff.md home/common/agent-skills/skills/from-issue/SKILL.md home/common/agent-skills/skills/from-issue/AUTO.md home/common/claude-code/skills/orchestrate-issues/SKILL.md
git add home/common/agent-skills/instruction-load.json  # only if Step 4 changed it
git commit -m "docs(skills): add the no-wait-loops dispatch clause (#309)"
```
