# Task 4: Pin the dispatch-marker total

Per D8. Measures issue #274 AC4.

**Files:**
- Test: `home/common/agent-skills/tests/test_dispatch_contracts.py` (one new module constant and one new class, appended)

**Interfaces:**
- Consumes: `SOURCE_TREES` (already imported from `skill_tree_support`: `{"shared": home/common/agent-skills/skills, "claude-only": home/common/claude-code/skills}`).
- Produces: `DISPATCH_MARKER_TOTAL = 39` and `DispatchMarkerInventoryTest`.

**Invariants:**
- The count is every occurrence of `<!-- agent-dispatch:` across all `*.md` files under both source trees (recursive); at this plan's base (81210221) it is 39.
- No skill file changes in this task; the literal changes only in a commit that adds or removes a dispatch marker.

- [ ] **Step 1: Write the failing test**

Append immediately before `if __name__ == "__main__":` in `test_dispatch_contracts.py`:

```python
# Every `<!-- agent-dispatch:` marker across the source skill trees, pinned at
# #274's base. A change that adds or removes a dispatch site updates this literal
# in the same commit, which is the point of the pin (#274 D8).
DISPATCH_MARKER_TOTAL = 39


class DispatchMarkerInventoryTest(unittest.TestCase):
    def test_the_source_trees_hold_the_pinned_number_of_dispatch_markers(self):
        total = sum(
            path.read_text(encoding="utf-8").count("<!-- agent-dispatch:")
            for root in SOURCE_TREES.values()
            for path in sorted(root.rglob("*.md"))
        )
        self.assertEqual(total, DISPATCH_MARKER_TOTAL)
```

- [ ] **Step 2: Run the test and watch it fail**

First add only the class (without the `DISPATCH_MARKER_TOTAL` line) and run:
`PYTHONPATH=python timeout 300 python3 -m unittest -v home/common/agent-skills/tests/test_dispatch_contracts.py -k DispatchMarkerInventory 2>&1 | tail -5`
Expected: ERROR — `NameError: name 'DISPATCH_MARKER_TOTAL' is not defined`.

- [ ] **Step 3: Write the minimal implementation**

Add the `DISPATCH_MARKER_TOTAL = 39` constant with its comment, exactly as in Step 1, directly above the class.

- [ ] **Step 4: Verify**

Run: `PYTHONPATH=python timeout 300 python3 -m unittest -v home/common/agent-skills/tests/test_dispatch_contracts.py -k DispatchMarkerInventory 2>&1 | tail -3`
Expected: `Ran 1 test` … `OK`

Mutation check (proves the pin can fail; restores the file afterwards):
`printf '\n<!-- agent-dispatch: id=probe role=explorer model=sonnet effort=medium -->\n' >> home/common/agent-skills/skills/worktrees/SKILL.md; PYTHONPATH=python timeout 300 python3 -m unittest home/common/agent-skills/tests/test_dispatch_contracts.py -k DispatchMarkerInventory 2>&1 | grep -c "AssertionError: 40 != 39"; git checkout -- home/common/agent-skills/skills/worktrees/SKILL.md`
Expected: `1`; afterwards `git status --short home/common/agent-skills/skills` prints nothing.

Run: `PYTHONPATH=python timeout 300 python3 -m unittest home/common/agent-skills/tests/test_dispatch_contracts.py 2>&1 | tail -3`
Expected: `OK` (installed-tree tests may skip).

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/tests/test_dispatch_contracts.py
git commit -m "test(dispatch): pin the agent-dispatch marker total (#274)"
```
