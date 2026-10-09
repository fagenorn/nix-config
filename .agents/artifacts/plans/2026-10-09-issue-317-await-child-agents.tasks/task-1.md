# Task 1: Interim child results waits within the turn

**Files:**
- Modify: `home/common/agent-skills/skills/from-issue/SKILL.md` (the `**Interim child results.**` paragraph only)
- Modify: `home/common/agent-skills/skills/sdd/SKILL.md` (the `**Interim child results.**` paragraph only)
- Modify: `home/common/agent-skills/skills/ship-issue/SKILL.md` (the `**Interim child results.**` paragraph only)
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py` (`InterimChildResultContractsTest`)

**Interfaces:**
- Consumes: nothing from other tasks. Module constants `SDD`, `FROM_ISSUE`, `SHIP_ISSUE` and the helper `normalized` already exist in the test module.
- Produces: no copy of the paragraph contains "host wakes you" or an end-your-turn allowance; Task 2's stale-wording test relies on that.

**Invariants:**
- The from-issue and sdd paragraphs stay byte-identical after whitespace normalization (`test_the_paragraph_copies_stay_identical`).
- Each of the three files holds `**Interim child results.**` exactly once; the paragraph stays one physical line.
- No copy contains "may end your" or "host wakes you" (D2).
- Every edited file is no larger than at `ef7eab96` (D4, D7).
- No other paragraph of these files changes.

- [ ] **Step 1: Write the failing tests**

In `InterimChildResultContractsTest`, replace `test_the_paragraph_states_the_rule_in_order` with the version below and add the new method after it:

```python
    def test_the_paragraph_states_the_rule_in_order(self):
        self.assert_ordered(
            self.paragraph(SDD), self.HEAD,
            "is not a completion: the child is still running.",
            "Re-engage that same child by its recorded agent identity",
            "and wait for that report within your turn.",
            "Never answer an interim result with a text-only reply",
            "never suspend for it (it is not an `external` wait)",
            "never dispatch a replacement or stop the child.",
            "stays registered under its existing worker id",
            "so it registers nothing new.",
            "If the message cannot be delivered or its reply cannot be awaited "
            "in your turn, the child is one you cannot wait for",
            "release `--event stopped`",
            "the one case that may lead to a fresh dispatch.",
            "Only the child's final hand-back counts as its result.")

    def test_no_copy_permits_ending_the_turn_on_a_live_child(self):
        for path in (SDD, FROM_ISSUE, SHIP_ISSUE):
            with self.subTest(path=path.parent.name):
                paragraph = self.paragraph(path)
                self.assertIn("and wait for that report within your turn.", paragraph)
                self.assertIn(
                    "If the message cannot be delivered or its reply cannot be "
                    "awaited in your turn,", paragraph)
                self.assertNotIn("may end your", paragraph)
                self.assertNotIn("host wakes you", paragraph)
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py -k InterimChildResultContractsTest`
Expected: FAIL — `test_the_paragraph_states_the_rule_in_order` misses `and wait for that report within your turn.`; `test_no_copy_permits_ending_the_turn_on_a_live_child` fails for all three subtests.

- [ ] **Step 3: Edit the three paragraphs (per D2, D7)**

In both `from-issue/SKILL.md` and `sdd/SKILL.md`, apply exactly these two replacements inside the paragraph (the copies must stay identical):

1. Replace `and wait for that report. You may end your own turn while the re-engaged child is live, because the host wakes you with its next notification; that is a child's work, not a command you started. Never answer` with `and wait for that report within your turn. Never answer`.
2. Replace `If the message cannot be delivered, the child is one you cannot wait for:` with `If the message cannot be delivered or its reply cannot be awaited in your turn, the child is one you cannot wait for:`.

In `ship-issue/SKILL.md`, inside the paragraph:

1. Replace `and wait for that report. You may end your turn while it is live; the host wakes you with its next notification. Never answer` with `and wait for that report within your turn. Never answer`.
2. Replace `If the message cannot be delivered, follow` with `If the message cannot be delivered or its reply cannot be awaited in your turn, follow` (D7: no "the child is one you cannot wait for" gloss here).

Expected sizes (estimate, for self-check): from-issue 30254 → 30147, sdd 22102 → 21995, ship-issue 30864 → 30838 bytes.

- [ ] **Step 4: Verify**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py`
Expected: PASS, no failures (the whole file, so the identity and AUTO-pointer tests still hold).

Run the byte-neutrality gate from the plan root's Global Constraints.
Expected: no output, exit 0. Before Step 3 it is vacuous; a `GREW` line means a file grew and the task is incomplete.

Run: `if grep -rn "host wakes you" home/common/agent-skills/skills/from-issue/SKILL.md home/common/agent-skills/skills/sdd/SKILL.md home/common/agent-skills/skills/ship-issue/SKILL.md; then exit 1; fi`
Expected: exit 0 (it exits 1 at the starting commit).

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/skills/from-issue/SKILL.md home/common/agent-skills/skills/sdd/SKILL.md home/common/agent-skills/skills/ship-issue/SKILL.md home/common/agent-skills/tests/test_workflow_skill_contracts.py
launch-commit … -- -m "fix(skills): interim child results wait within the turn (#317)" -m "<trailers>"
```
