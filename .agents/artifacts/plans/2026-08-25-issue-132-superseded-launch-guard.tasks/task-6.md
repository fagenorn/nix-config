# Task 6: Shared-bucket and wall-clock-expiry documentation, then the whole-change gate

Discharges AC7 and AC8. Rests on spec rows D11 and D15, and on the new D18.

**Files:**
- Modify: `CLAUDE.md`
- Modify: `home/common/agent-skills/skills/from-issue/SKILL.md`
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes (Tasks 1–5): the shipped verb name `workflow-state check-launch` and
  the rule that a still-running predecessor re-validates before any forge write.
- Produces: nothing later tasks depend on. This is the last content task and it
  carries the whole-change gate.

**Invariants:**
- The `CLAUDE.md` claim goes **inside the existing per-checkout-bucket
  parenthesis**, so the two halves of one fact stay together: two *checkouts*
  never share a task ledger, and two *attempts* on one issue do share a checkout.
- The expiry statement is appended to from-issue's deadline-rejected-`progress`
  paragraph, after "Persistence precedes notification: the reaper's suspension
  is already durable before you print." Appending preserves the anchor order
  that paragraph's existing contract test pins.
- `last_progress_at` is described as playing **no** part in expiry, and it must
  not become an expiry input anywhere — that is issue #133's slice.
- No new contract-test seam for `CLAUDE.md` (per D18); its criterion is gated by
  `grep` here.

---

- [ ] **Step 1: Write the failing test**

Add to `WorkflowSkillContractsTest` in
`home/common/agent-skills/tests/test_workflow_skill_contracts.py`, immediately
after `test_from_issue_revalidates_its_launch_before_the_terminal_finish`:

```python
    def test_expiry_prose_describes_the_wall_clock_the_reaper_actually_reads(self):
        # The only skill-prose home that explains expiry to an owner. Prose that
        # frames expiry as detecting a silent agent is wrong: the reaper compares
        # instants and never looks at progress (per D11).
        rules = self.section(
            self.from_issue,
            "## Dispatch, phase-budget and attempt-budget rules",
            "## Terminal return procedure",
        )
        collapsed = normalized(rules)
        self.assert_ordered(
            collapsed,
            "Persistence precedes notification",
            "wall-clock only",
            "never consults `last_progress_at`",
        )
        self.assertIn("blocked on a CI watch", collapsed)
        self.assertIn(
            "bounds how long an owner may hold the issue", collapsed
        )
```

- [ ] **Step 2: Run the test and watch it fail**

```sh
python3 home/common/agent-skills/tests/test_workflow_skill_contracts.py -v \
  -k expiry_prose_describes_the_wall_clock
```
Expected: FAIL — `assert_ordered` reports `missing anchor: 'wall-clock only'`.

- [ ] **Step 3: Say what the reaper actually does**

In `home/common/agent-skills/skills/from-issue/SKILL.md`, in the paragraph that
ends "Persistence precedes notification: the reaper's suspension is already
durable before you print." (inside `## Dispatch, phase-budget and attempt-budget
rules`), append, in the same paragraph, hard-wrapped at ~80 columns:

> Expiry is wall-clock only: the reaper compares the current instant against the
> attempt's `deadline_at` and never consults `last_progress_at`, so an attempt
> that is actively working — blocked on a CI watch, say — expires exactly like
> one whose owner is gone. A deadline bounds how long an owner may hold the
> issue; it says nothing about whether that owner is still running.

Append only. Do not reorder or rewrite the sentences before it, and do not touch
`workflow-state.py`'s docstrings — they are not the prose this criterion names.

- [ ] **Step 4: State the shared bucket beside the sentence it completes**

In `CLAUDE.md`, find the parenthesis inside the `.superpowers/` bullet reading

> (`primary/` or `wt-<worktree-name>/`, so two checkouts executing the same plan
> can never share a ledger)

and extend it **inside the same parenthesis**, leaving the rest of the sentence
and the surrounding bullet untouched:

> (`primary/` or `wt-<worktree-name>/`, so two checkouts executing the same plan
> can never share a ledger — though two *attempts* on one issue do share a
> checkout, because the lifecycle hands a retry the predecessor's worktree and
> branch on purpose: that sharing is what lets a successor resume the task ledger
> seamlessly, and it is why a still-running predecessor must re-validate its
> launch identity with `workflow-state check-launch` before any forge write)

`CLAUDE.md` is a single long line per bullet; keep it that way — do not re-wrap
the bullet.

- [ ] **Step 5: Verify the documentation**

```sh
python3 home/common/agent-skills/tests/test_workflow_skill_contracts.py -v
```
Expected: OK, zero failures and zero errors.

`CLAUDE.md` has no contract seam and gets none (per D18); gate it here:
```sh
if ! grep -q 'two \*attempts\* on one issue do share a checkout' CLAUDE.md; then
  echo "CLAUDE.md does not state the shared bucket"; exit 1
fi
if ! grep -q 'can never share a ledger — though two \*attempts\*' CLAUDE.md; then
  echo "the claim is not inside the existing parenthesis"; exit 1
fi
```
Expected: no output, exit 0. At the commit this task starts from both gates
exit 1.

- [ ] **Step 6: Run the whole-change gate**

This is AC8 and the plan's `## Verification` section, run from the worktree root
over the complete change:

```sh
just build
just agent-workflow-tests
just show-claude-settings > "$TMPDIR/claude-settings.json" \
  && CLAUDE_SETTINGS_PATH="$TMPDIR/claude-settings.json" \
     python3 tests/test_claude_permission_guard.py -v
```

Expected:
- `just build` completes and writes `./result` with no evaluation error.
- `just agent-workflow-tests` ends `OK` across all thirteen suites, zero
  failures and zero errors.
- `just show-claude-settings` prints exactly one settings artifact (it fails
  unless discovery finds exactly one), and the permission-guard suite ends `OK`
  — **untouched**: its adversarial table is a gate here, never a target. If it
  is red, the change reached the guard's command grammar, which is out of scope;
  revert that reach rather than editing the suite.

Confirm nothing in this change touched the out-of-scope surfaces:
```sh
changed=$(git diff --name-only origin/main..HEAD -- \
  tests/test_claude_permission_guard.py home/common/claude-code/default.nix)
if [ -n "$changed" ]; then
  echo "the permission guard surface was modified: $changed"; exit 1
fi
if git diff origin/main..HEAD -- home/common/agent-skills/scripts/workflow-state.py \
   | grep -E '^[+-]' | grep -q 'CONTROL_DISPATCH_KINDS'; then
  echo "CONTROL_DISPATCH_KINDS was touched"; exit 1
fi
```
Expected: no output, exit 0. Scope the pathspec exactly as written — never grade
the raw commit range, which also holds this run's spec and plan artifacts and
anything a sync merge pulled in.

- [ ] **Step 7: Commit**

```bash
git add CLAUDE.md \
        home/common/agent-skills/skills/from-issue/SKILL.md \
        home/common/agent-skills/tests/test_workflow_skill_contracts.py
git commit -m "docs(issue-132): state the shared sdd bucket and wall-clock expiry"
```
Include the `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>` trailer.
Never disable commit signing.
