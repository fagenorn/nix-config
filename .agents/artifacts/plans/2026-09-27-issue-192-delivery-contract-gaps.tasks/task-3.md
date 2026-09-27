# Task 3: AUTO.md's delegated owner takes `expected_branch` from the contract

Spec §3 and T6, per D5, D12, D23. A resumed legacy owner's worktree is slugless,
so its final path component is not its branch. The delegated owner's
continuation check must read the branch the builder sealed, which is the
contract's reviewed-slot branch, and not re-derive it from the path. No other
prose changes for gap 1 (D5). orchestrate-issues' "a candidate's final path
component is the branch its contract will carry" stays, because a candidate is
absent and builds by rule 1.

**Files:**
- Modify: `home/common/agent-skills/skills/from-issue/AUTO.md`
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes: the interface-2 owner object's `contract` member. Every validated
  `owner` carries a model-valid contract, and each of its slot stages carries
  `target_ref.constraints.branch` (the reviewed slot).
- Produces: nothing later tasks read.

**Invariants:**
- `expected_branch` is still matched against the binding-derived accepted
  branch regex, and `git -C owner.worktree branch --show-current` must still
  equal it. Only the source of the value changes.
- AUTO.md's byte size does not change. The replacement is 178 bytes, like the
  sentence it replaces, so no instruction-load ceiling moves (D23).
- `#### Fresh delegated owner` no longer says "final path component".

- [ ] **Step 1: Update the pin so it fails**

In `test_workflow_skill_contracts.py`, in
`test_direct_auto_phase_five_rolls_to_one_fresh_implementation_owner`, the first
`self.assert_ordered(delegated, ...)` call lists `"final path component",`.
Replace that one anchor with:

```python
            "`owner.contract`'s reviewed-slot `constraints.branch`",
```

Directly after that `assert_ordered` call, add:

```python
        self.assertNotIn("final path component", delegated)
```

- [ ] **Step 2: Run the pin and watch it fail**

Run: `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py -k test_direct_auto_phase_five_rolls_to_one_fresh_implementation_owner`
Expected: `FAILED (failures=1)`, with
`missing anchor: "`owner.contract`'s reviewed-slot `constraints.branch`"`.

- [ ] **Step 3: Edit AUTO.md**

In `#### Fresh delegated owner`, replace exactly these three lines:

```text
either the resolved prefix or no prefix. Take normalized `owner.worktree`'s final path component
and require it to match that binding-derived accepted branch regex; that component
is the deterministic `expected_branch`. Require
```

with:

```text
either the resolved prefix or no prefix. Take `owner.contract`'s reviewed-slot `constraints.branch`
and require it to match that binding-derived accepted branch regex; that branch
is the deterministic `expected_branch`. Require
```

Change nothing else in AUTO.md.

- [ ] **Step 4: Verify**

Run: `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py home/common/agent-skills/tests/test_instruction_load.py home/common/agent-skills/tests/test_shell_example_contracts.py home/common/agent-skills/tests/test_dispatch_contracts.py`
Expected: `OK` (the existing skips stay skips), with no `FAIL:`/`ERROR:`.
`LiveModelTest.test_the_live_tree_breaches_no_ceiling` passes with no ceiling
edit.

Run: `test "$(git show HEAD:home/common/agent-skills/skills/from-issue/AUTO.md | wc -c)" -eq "$(wc -c < home/common/agent-skills/skills/from-issue/AUTO.md)" && echo same-size`
Expected: `same-size`, before the commit.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/skills/from-issue/AUTO.md home/common/agent-skills/tests/test_workflow_skill_contracts.py
git commit -m "fix(from-issue): take the delegated owner's expected branch from its contract (#192)" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```
