# Task 5: from-issue's pre-`finish` guard

Closes the other side of the trust boundary and its share of AC6. Rests on spec
rows D8 and D9.

**Files:**
- Modify: `home/common/agent-skills/skills/from-issue/SKILL.md`
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes (Task 1): the verb
  `~/.agents/bin/workflow-state check-launch --repo-root <ledger_repo_root> --run-id <run-id> --action-id <issue:attempt:launch>`.
- Consumes (Task 2): from-issue's own adopted `action_id`, threaded through the
  lifecycle identity.
- Consumes (Task 3): the refusal shape — write nothing, print the canonical
  re-entry line, stop.
- Produces: nothing later tasks depend on.

**Invariants:**
- The guard runs immediately before the terminal `workflow-state finish` that
  from-issue's Phase 7 performs for a ship report, and uses **this owner's own**
  `action_id` — the ship owner and its parent share one launch identity, so a
  ship report from a superseded launch means this parent is superseded too.
- On `current: false` or any helper failure: write nothing, print the canonical
  re-entry line, stop. No `finish`, no `suspend`.
- Phase 7's existing anchor order is preserved: `ledger_repo_root` → "receiving
  the ship report" → `workflow-state finish` → "send the exact JSON".
- Scope stays at this one call. Do not guard from-issue's other
  `workflow-state` writes — that is #125's, and it would add a failure mode at
  all eight phase gates (per D9).

---

- [ ] **Step 1: Write the failing test**

Add to `WorkflowSkillContractsTest` in
`home/common/agent-skills/tests/test_workflow_skill_contracts.py`, immediately
after `test_owner_lifecycle_is_optional_for_direct_use_and_covers_all_stops`:

```python
    def test_from_issue_revalidates_its_launch_before_the_terminal_finish(self):
        # Without this the design refuses the forge write and then performs the
        # ledger write from the very launch it just proved stale, because the
        # ship owner and this parent share one identity (per D9).
        phase_seven = self.section(self.from_issue, "## Phase 7", "## Notes")
        self.assert_ordered(
            phase_seven,
            "receiving the ship report",
            "check-launch",
            "workflow-state finish",
        )
        collapsed = normalized(phase_seven)
        self.assertIn(
            "~/.agents/bin/workflow-state check-launch --repo-root "
            "<ledger_repo_root> --run-id <run-id> --action-id "
            "<issue:attempt:launch>",
            collapsed,
        )
        self.assertIn("this owner's own `action_id`", collapsed)
        self.assertIn("write nothing", collapsed)
        # The refusal is a stop, never a suspension: in the resume shape a
        # suspend would park the successor's live attempt (per D8).
        self.assertNotIn("workflow-state suspend", phase_seven)
```

- [ ] **Step 2: Run the test and watch it fail**

```sh
python3 home/common/agent-skills/tests/test_workflow_skill_contracts.py -v \
  -k revalidates_its_launch_before_the_terminal_finish
```
Expected: FAIL — `assert_ordered` reports `missing anchor: 'check-launch'`;
from-issue's Phase 7 has no ledger contact between receiving the ship report and
the terminal write.

- [ ] **Step 3: Insert the guard sentence**

In `home/common/agent-skills/skills/from-issue/SKILL.md`, `## Phase 7 — Ship`,
inside the paragraph that begins "After receiving the ship report, from-issue
owns the terminal durable write.", insert immediately **before** the existing
sentence "Then call `workflow-state finish` and send the exact JSON printed on
stdout unchanged." (hard-wrap at ~80 columns):

> Before that terminal write, run
> `~/.agents/bin/workflow-state check-launch --repo-root <ledger_repo_root> --run-id <run-id> --action-id <issue:attempt:launch>`
> with this owner's own `action_id`: the ship owner and this parent share one
> launch identity, so a ship report from a superseded launch means this launch
> is superseded too. On `current: false` or any helper failure, write nothing,
> print the canonical re-entry line, and stop.

Keep the command on one line so the contract's collapsed-whitespace anchor
matches it. Change nothing else in Phase 7: the ship-summary validation, the
`unpublished` re-read, the "A fresh ship agent never writes the owner's final
ledger result" sentence and the `ship-Phase-N` narration rule all stay as they
are.

- [ ] **Step 4: Verify**

```sh
python3 home/common/agent-skills/tests/test_workflow_skill_contracts.py -v
```
Expected: OK, zero failures and zero errors. In particular
`test_owner_lifecycle_is_optional_for_direct_use_and_covers_all_stops` must
still pass — it pins the Phase-7 anchor order `ledger_repo_root` → "receiving
the ship report" → `workflow-state finish` → "send the exact JSON", and the new
sentence sits between the second and third anchors without displacing any.

Then confirm the retired verb name did not sneak in with the new one:
```sh
if grep -q 'workflow-state launch' home/common/agent-skills/skills/from-issue/SKILL.md; then
  echo "the retired verb name appears"; exit 1
fi
if ! grep -q 'workflow-state check-launch' home/common/agent-skills/skills/from-issue/SKILL.md; then
  echo "from-issue does not invoke check-launch"; exit 1
fi
```
Expected: no output, exit 0. At the commit this task starts from the second gate
exits 1.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/skills/from-issue/SKILL.md \
        home/common/agent-skills/tests/test_workflow_skill_contracts.py
git commit -m "feat(issue-132): re-validate the launch before from-issue's terminal finish"
```
Include the `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>` trailer.
Never disable commit signing.
