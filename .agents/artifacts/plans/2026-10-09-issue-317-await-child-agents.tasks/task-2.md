# Task 2: `own-commands` names agents, plus the stale-wording guard

**Files:**
- Modify: `home/common/agent-skills/tests/test_dispatch_contracts.py` (`CONTRACTS["own-commands"]`, new `STALE_TURN_END_WORDING` and `StaleTurnEndWordingTest`)
- Modify (the clause's second sentence, inside each carrier's rendered region only):
  - `home/common/agent-skills/skills/sdd/implementer-prompt.md`
  - `home/common/agent-skills/skills/sdd/task-reviewer-prompt.md`
  - `home/common/agent-skills/skills/sdd/re-review-prompt.md`
  - `home/common/agent-skills/skills/sdd/correctness-reviewer-prompt.md`
  - `home/common/agent-skills/skills/sdd/conformance-reviewer-prompt.md`
  - `home/common/agent-skills/skills/from-issue/ship-handoff.md`
  - `home/common/claude-code/skills/orchestrate-issues/SKILL.md` (owner-prompt blockquote only)
  - `home/common/agent-skills/skills/from-issue/SKILL.md` (`## Dispatch, phase-budget and attempt-budget rules` blockquote)
  - `home/common/agent-skills/skills/sdd/SKILL.md` (`## Agent tiers` blockquote)
  - `home/common/claude-code/agents/implementer.md`, `mechanic.md`, `reviewer.md`, `reviewer-lite.md`
- Modify: the plan's acceptance record (row AC2), at the path sdd assigns.

**Interfaces:**
- Consumes: Task 1's result — no guarded document contains "host wakes you".
- Produces: `STALE_TURN_END_WORDING: tuple[str, ...]` and `StaleTurnEndWordingTest` in `test_dispatch_contracts.py`.

**Invariants:**
- The clause's first sentence is unchanged; its second sentence is exactly `If the host moves one to the background anyway, wait for it in the same turn: never end your turn while a command or agent you started still runs.` (D1).
- Each carrier holds the full clause exactly once inside its rendered region, whitespace-normalized; no copy appears outside a region (existing tests).
- `REMAINDER_PLACEHOLDER`, `AGENT_CLAUSES`, `CARRIERS` and the carrier counts are unchanged (D1, D3).
- No guarded document, whitespace-normalized, contains `never end your turn while a command you started` or `host wakes you` (D6).
- Every edited document is no larger than at `ef7eab96` (D4). The replacement text is one byte shorter but one word longer than the text it replaces, so a line break that adds indent bytes can grow a file; rewrap only within the paragraph and only so the file does not grow.

- [ ] **Step 1: Write the failing tests**

In `CONTRACTS`, replace the `"own-commands"` value with:

```python
    "own-commands": (
        "Run each long command, every verification command included, in the "
        "foreground with an explicit timeout above its expected duration. If "
        "the host moves one to the background anyway, wait for it in the "
        "same turn: never end your turn while a command or agent you started "
        "still runs."
    ),
```

After `STALE_REMAINDER_WORDING`, add:

```python
# Wording #317 retired: the commands-only turn-end tail and the false premise
# that the host wakes a dispatched owner (per D1, D2, D6).
STALE_TURN_END_WORDING = (
    "never end your turn while a command you started",
    "host wakes you",
)
```

After `StrayCopyGuardTest`, add:

```python
class StaleTurnEndWordingTest(unittest.TestCase):
    def test_no_document_keeps_the_commands_only_or_host_wakes_wording(self):
        found = [
            f"{label}: {phrase}"
            for label, text in sorted(guarded_documents().items())
            for phrase in STALE_TURN_END_WORDING
            if _clause_pattern(phrase).search(text)
        ]
        self.assertEqual(found, [])
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_dispatch_contracts.py`
Expected: FAIL — `test_own_commands` reports every carrier missing the clause, `test_no_document_keeps_the_commands_only_or_host_wakes_wording` lists the 13 carriers with `never end your turn while a command you started`. Installed-tree tests skip while their installed-home variable is unset.

- [ ] **Step 3: Reword every carrier (per D1, D4)**

In each file listed above, inside its existing clause, replace the words `wait for it within the same turn: never end your turn while a command you started is still running.` with `wait for it in the same turn: never end your turn while a command or agent you started still runs.` Keep each carrier's existing line prefix (`> ` in blockquotes, four-space indent in the sdd prompt fences, none in the agent bodies and ship-handoff fence). Line breaks may move only within that paragraph; never join it with the following `Never write an \`until\`` line where it is a separate line today.

- [ ] **Step 4: Verify**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_dispatch_contracts.py home/common/agent-skills/tests/test_workflow_skill_contracts.py`
Expected: PASS, no failures.

Run the byte-neutrality gate from the plan root's Global Constraints.
Expected: no output, exit 0; a `GREW` line names a carrier to rewrap.

Run: `PYTHONPATH="$PWD/python" python3 -m agent_tools.instruction_load check --base origin/main`
Expected: `check: pass` (it is the unlabelled Instruction Budget gate; a failure here means a document grew).

- [ ] **Step 5: Record AC2 and commit**

Write acceptance-record row AC2 with Check `hand-back texts of the run's owner launches`, Conditions `post-merge orchestrated run, ≥2 issues reaching Phase 7`, threshold `zero matches of waiting for`, Observed `not measured — post-merge`, Verdict `unverified` (D5).

```bash
git add home/common/agent-skills/tests/test_dispatch_contracts.py home/common/agent-skills/skills home/common/claude-code/skills/orchestrate-issues/SKILL.md home/common/claude-code/agents
launch-commit … -- -m "fix(skills): the own-commands clause names agents (#317)" -m "<trailers>"
```
