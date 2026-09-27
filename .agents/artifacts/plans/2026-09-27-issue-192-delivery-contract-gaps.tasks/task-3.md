# Task 3: AUTO.md's delegated owner takes `expected_branch` from the contract

Spec §3 and T6, per D5, D23, D27. A resumed legacy owner's worktree is slugless,
so its final path component is not its branch. The delegated owner's
continuation check must read the branch the builder sealed, which is the
contract's reviewed-slot branch, and not re-derive it from the path. Its path
check compares `owner.worktree` with the contract's `remove_worktree` literal,
so "a pattern, path, or current-branch mismatch" keeps a real path check (D27).
No other prose changes for gap 1 (D5). orchestrate-issues' "a candidate's final path
component is the branch its contract will carry" stays, because a candidate is
absent and builds by rule 1.

**Files:**
- Modify: `home/common/agent-skills/skills/from-issue/AUTO.md`
- Modify: `home/common/agent-skills/instruction-load.json`
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes: the interface-2 owner object's `contract` member. Every validated
  `owner` carries a model-valid contract, and each of its slot stages carries
  `target_ref.constraints.branch` (the reviewed slot). Its `remove_worktree`
  stage's literal `target_ref.value` is the path control and direct-owner bind
  custody to ("custody worktree does not match the delivery contract").
- Produces: nothing later tasks read.

**Invariants:**
- `expected_branch` is still matched against the binding-derived accepted
  branch regex, and `git -C owner.worktree branch --show-current` must still
  equal it. Only the source of the value changes.
- Normalized `owner.worktree` must equal the contract's `remove_worktree`
  literal, before the branch probe.
- `#### Fresh delegated owner` no longer says "final path component".
- Only the ceilings AUTO.md's growth breaches move, each to its measured hot
  bytes, with #192 named in the profile note (D23).

- [ ] **Step 1: Update the pin so it fails**

In `test_workflow_skill_contracts.py`, in
`test_direct_auto_phase_five_rolls_to_one_fresh_implementation_owner`, the first
`self.assert_ordered(delegated, ...)` call lists `"final path component",`.
Replace that one anchor with:

```python
            "`owner.contract`'s reviewed-slot `constraints.branch`",
```

In the same call, directly after its `"`expected_branch`",` anchor, add:

```python
            "normalized `owner.worktree` to",
            "`remove_worktree` stage",
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
is the deterministic `expected_branch`. Require normalized `owner.worktree` to
equal the literal target of `owner.contract`'s `remove_worktree` stage. Require
```

Change nothing else in AUTO.md.

- [ ] **Step 4: Re-measure the ceilings**

Run: `PYTHONPATH=python python3 -c 'from pathlib import Path; from agent_tools import instruction_load as il; r = il.tree_reader(Path(".")); m = il.load_model(r(il.MODEL_PATH)); print("\n".join(il.over_ceiling(m, il.measure(m, r))) or "no breach")'`
Expected: five lines, `profile <id> on <host>: hot <N> bytes exceed ceiling <C> (...)`,
for `from-issue-controller` on `claude` and `codex` (ceiling 87439),
`implementation-owner` on `claude` and `codex` (138951), and
`orchestrated-issue-owner` on `claude` (147826). The planning probe measured
`<N>` as 87550, 139062 and 147937, 111 bytes over each.

In `instruction-load.json`, set each breached profile's `ceiling_bytes` for the
breached hosts to its measured `<N>`, and append to its `note`:
` Ceiling raised for #192: AUTO.md's fresh delegated owner checks its worktree against the contract's remove_worktree target (#155 D10).`.
Raise no other profile.

Run the same command again.
Expected: `no breach`.

- [ ] **Step 5: Verify**

Run: `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py home/common/agent-skills/tests/test_instruction_load.py home/common/agent-skills/tests/test_shell_example_contracts.py home/common/agent-skills/tests/test_dispatch_contracts.py`
Expected: `OK` (the existing skips stay skips), with no `FAIL:`/`ERROR:`.
`LiveModelTest.test_the_live_tree_breaches_no_ceiling` passes.

Run: `if grep -q "final path component" home/common/agent-skills/skills/from-issue/AUTO.md; then exit 1; else echo path-rule-gone; fi`
Expected: `path-rule-gone`.

- [ ] **Step 6: Commit**

```bash
git add home/common/agent-skills/skills/from-issue/AUTO.md home/common/agent-skills/instruction-load.json home/common/agent-skills/tests/test_workflow_skill_contracts.py
git commit -m "fix(from-issue): take the delegated owner's expected branch from its contract (#192)" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```
