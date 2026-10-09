# Task 4: One canonical Interim child results paragraph

**Files:**
- Modify: `home/common/agent-skills/skills/sdd/SKILL.md` (the `**Interim child results.**` paragraph only)
- Modify: `home/common/agent-skills/skills/from-issue/SKILL.md` (the `**Interim child results.**` paragraph only)
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py` (`InterimChildResultContractsTest`)
- Modify only if Step 4's budget gate reports a tightness violation: `home/common/agent-skills/instruction-load.json`

**Interfaces:**
- Consumes: nothing from other tasks. Module constants `SDD`, `FROM_ISSUE`, `SHIP_ISSUE` and the helper `normalized` already exist in the test module.
- Produces: the three copies are one text; nothing later depends on it.

**Invariants:**
- The canonical text is ship-issue's current paragraph, byte for byte; `ship-issue/SKILL.md` is not edited (D4).
- sdd, from-issue and ship-issue each hold `**Interim child results.**` exactly once, as one physical line, and the three paragraphs are equal after `normalized` (D5, AC2).
- No other line of `sdd/SKILL.md` or `from-issue/SKILL.md` changes; each file shrinks by exactly 150 bytes (sdd 21994 → 21844, from-issue 30146 → 29996).
- `just agent-instruction-budget` without `--raise-label` prints `check: pass`; no ceiling rises (D4).

- [ ] **Step 1: Write the failing tests**

In `InterimChildResultContractsTest` (D5: extend, add no test):

- set `OWNERS = (SDD, FROM_ISSUE, SHIP_ISSUE)`;
- in `test_the_paragraph_copies_stay_identical`, loop `for path in (FROM_ISSUE, SHIP_ISSUE):`;
- replace `test_the_paragraph_states_the_rule_in_order` with:

```python
    def test_the_paragraph_states_the_rule_in_order(self):
        self.assert_ordered(
            self.paragraph(SDD), self.HEAD,
            "(its own background work still running, or a result that may be interim) "
            "is not a completion.",
            "Re-engage that same child by its recorded agent identity",
            "and wait for that report within your turn.",
            "Never answer an interim result with a text-only reply",
            "never suspend for it (it is not an `external` wait)",
            "never dispatch a replacement or stop the child.",
            "stays registered under its existing worker id and registers nothing new",
            "an interim result is not its `returned` event.",
            "If the message cannot be delivered or its reply cannot be awaited "
            "in your turn, follow from-issue's **Writing workers** route",
            "release `--event stopped`",
            "the one case that may lead to a fresh dispatch.",
            "Only the child's final hand-back counts as its result.")
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py -k InterimChildResultContractsTest 2>&1 | grep -E '^FAIL|^FAILED'`
Expected: FAIL — `test_the_paragraph_copies_stay_identical` for `ship-issue`, and `test_the_paragraph_states_the_rule_in_order` misses `… is not a completion.`.

- [ ] **Step 3: Copy the canonical paragraph (per D4)**

In `sdd/SKILL.md` and `from-issue/SKILL.md`, replace the whole line that starts with `**Interim child results.**` with the line from `ship-issue/SKILL.md` that starts with `**Interim child results.**`, verbatim. Every clause survives the shorter wording (#296 D8, #317 D2).

- [ ] **Step 4: Verify**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py 2>&1 | tail -n 1`
Expected: `OK` (the whole module, so the AUTO-pointer test still holds).

Run: `test "$(wc -c < home/common/agent-skills/skills/sdd/SKILL.md)" -eq 21844 && test "$(wc -c < home/common/agent-skills/skills/from-issue/SKILL.md)" -eq 29996`
Expected: exit 0 (exits 1 at the starting commit).

Run: `just agent-instruction-budget` (timeout 600 s)
Expected: `check: pass` (measured at planning with this edit applied). If it instead names a ceiling more than 5% above its measure, run `PYTHONPATH="$PWD/python" python3 -m agent_tools.instruction_load tighten`, rerun the gate until it prints `check: pass`, and commit `instruction-load.json` with this task. Never pass `--raise-label`, never raise a ceiling.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/skills/sdd/SKILL.md home/common/agent-skills/skills/from-issue/SKILL.md home/common/agent-skills/tests/test_workflow_skill_contracts.py
# only when Step 4 ran tighten:
git add home/common/agent-skills/instruction-load.json
launch-commit … -- -m "docs(skills): one canonical interim child results paragraph (#331)" -m "<trailers>"
```
