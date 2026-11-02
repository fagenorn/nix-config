# Task 2: End the turn on a blocker another session owns

This task covers spec § The end-the-turn rule, per D3. from-issue's Suspension procedure names a blocker another session owns as its external wait, ends the turn on it and never polls it. The dropped "(never a child's interim result)" keeps its rule in the **Interim child results** paragraph, which this task leaves byte-identical.

**Files:**
- Modify: `home/common/agent-skills/skills/from-issue/SKILL.md` (the first paragraph of `## Suspension procedure` only)
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py` (extend `ClaudeCompatibleWaitContractsTest`)

**Interfaces:**
- Consumes, from Task 1: the class `ClaudeCompatibleWaitContractsTest` in `test_workflow_skill_contracts.py`, its docstring, and its last method `test_each_former_site_names_both_claude_compatible_waits`. From the module as it is at the base: `FROM_ISSUE` (the path of `home/common/agent-skills/skills/from-issue/SKILL.md`) and `normalized(text)`.
- Produces: the class attribute `END_THE_TURN` and the test `test_from_issue_ends_the_turn_on_another_sessions_blocker`.

**Invariants:**
- The `## Suspension procedure` section of from-issue's `SKILL.md`, whitespace-normalized, holds `a blocker another session owns: end the turn, never poll`.
- `never a child's interim result` occurs nowhere in the three skill trees.
- The `**Interim child results.**` paragraph, the suspend call, its `--blocked-on` values and the `Suspended (…)` line are unchanged; `InterimChildResultContractsTest` stays green.
- Task 1's clause, carriers and constant are unchanged.

- [ ] **Step 1: Write the failing test**

In `home/common/agent-skills/tests/test_workflow_skill_contracts.py`, in `ClaudeCompatibleWaitContractsTest`:

1. Replace the class docstring with:

```python
    """#474: no skill document chains a check onto a foreground `sleep`, each
    former no-wait-loops site names both Claude-compatible waits, and from-issue
    ends the turn on a blocker another session owns."""
```

2. Right after the line `WAIT_FORMS = ("Monitor with an until-condition", "bare `sleep N` call")`, add:

```python
    END_THE_TURN = "a blocker another session owns: end the turn, never poll"
```

3. After `test_each_former_site_names_both_claude_compatible_waits`, as the class's last method, add:

```python
    def test_from_issue_ends_the_turn_on_another_sessions_blocker(self):
        text = FROM_ISSUE.read_text(encoding="utf-8")
        start = text.index("\n## Suspension procedure\n")
        end = text.index("\n## ", start + 1)
        self.assertIn(self.END_THE_TURN, normalized(text[start:end]))
```

- [ ] **Step 2: Run the test and watch it fail**

Run the Wait-class tests command (timeout 600 s).
Expected: `Ran 4 tests`, `FAILED (failures=1)`; the one failure is `test_from_issue_ends_the_turn_on_another_sessions_blocker`, an `AssertionError` that the phrase is not in the section.

- [ ] **Step 3: Write the minimal implementation**

In `home/common/agent-skills/skills/from-issue/SKILL.md`, in the first paragraph under `## Suspension procedure`, replace the substring (it occurs once)

```text
an external wait (never a child's interim result)
```

with

```text
an external wait (a blocker another session owns: end the turn, never poll)
```

The paragraph then reads, as one line:

```text
Suspend — do not finish — when an environmental interruption pauses the work: an imminent quota or session limit, a repeated transport failure, a permission prompt only a human can approve, an external wait (a blocker another session owns: end the turn, never poll), or a context that cannot launch the agents a phase needs. A suspension consumes no attempt and needs no authorization phrase.
```

- [ ] **Step 4: Verify**

Run the Wait-class tests command (timeout 600 s). Expected: `Ran 4 tests`, `OK`.

Run the Skill contract tests command (timeout 900 s). Expected: `Ran 236 tests`, `OK (skipped=3)`.

Run (timeout 60 s):

```bash
set -euo pipefail
if git grep -n -F "never a child's interim result" -- home/common/agent-skills/skills home/common/claude-code/skills home/common/codex/skills; then exit 1; fi
test "$(git grep -c -F 'an external wait (a blocker another session owns: end the turn, never poll)' -- home/common/agent-skills/skills/from-issue/SKILL.md | cut -d: -f2)" -eq 1
echo end-the-turn-ok
```

Expected: `end-the-turn-ok`. At the starting commit the first `git grep` prints from-issue's Suspension line and the script exits 1.

Run the Budget command (timeout 600 s). Expected: last line `check: pass`. The prototype measured from-issue-controller hot at +23 B against the base with 22 B left, and implementation-owner hot at +5 B with 13 B left (D5).

Run the Installed tier command (timeout 3600 s). Expected: `OK (skipped=1)` or `OK`.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/skills/from-issue/SKILL.md home/common/agent-skills/tests/test_workflow_skill_contracts.py
launch-commit --repo-root <R> --run-id <I> --worker-id <W> -- -m "feat(from-issue): end the turn on a blocker another session owns (issue 474)"
```

The message ends with the session's attribution trailer. Report DONE with the two test counts and the Budget line.
