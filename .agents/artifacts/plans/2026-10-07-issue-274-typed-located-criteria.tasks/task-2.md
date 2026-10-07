# Task 2: Acceptance map in writing-plans and its blocking review check

Per D2, D3, D4, D5. Measures issue #274 AC2.

**Files:**
- Modify: `home/common/agent-skills/skills/writing-plans/SKILL.md`
- Modify: `home/common/agent-skills/skills/from-issue/REVIEW-CONTRACT.md`
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py` (append one new class)

**Interfaces:**
- Consumes: the test module's existing `REPO_ROOT` and `normalized(text)`.
- Produces: the plan-root section `## Acceptance map`, a pipe table headed `| AC | Kind | Task | Check |` with rows `AC1`…`AC<n>`, or the single line `None — no acceptance criteria.`; Task 3's `acceptance_map_covers` grades exactly this shape.

**Invariants:**
- In `writing-plans/SKILL.md` the `## ` heading that follows `## Task index` is `## Acceptance map`; `## Task index` and `## Acceptance map` each occur exactly once as a line.
- Self-review keeps `**Final remeasurement**` as the last numbered item.
- In `REVIEW-CONTRACT.md`, `## Acceptance map check` sits after `## Reviewer instructions` and before `## Common-miss checklist`; no other section changes.
- `artifact-budget` and `task-brief` are not edited: both end the Task index at the next `## ` line, and map rows start with `|`, never `Task `.

- [ ] **Step 1: Write the failing test**

Append immediately before `if __name__ == "__main__":` in `test_workflow_skill_contracts.py` (after any class an earlier task appended):

```python
class AcceptanceMapContractsTest(unittest.TestCase):
    """#274 AC2: plans carry an Acceptance map and plan review blocks a gap (D2-D5)."""

    WRITING_PLANS = REPO_ROOT / "home/common/agent-skills/skills/writing-plans/SKILL.md"
    REVIEW_CONTRACT = (
        REPO_ROOT / "home/common/agent-skills/skills/from-issue/REVIEW-CONTRACT.md")

    @classmethod
    def setUpClass(cls):
        cls.plans = cls.WRITING_PLANS.read_text(encoding="utf-8")
        cls.review = cls.REVIEW_CONTRACT.read_text(encoding="utf-8")

    @staticmethod
    def section(text, heading):
        start = text.index("\n" + heading + "\n") + 1
        end = text.find("\n## ", start + len(heading))
        return text[start:] if end < 0 else text[start:end]

    def assert_ordered(self, text, *anchors):
        position = -1
        for anchor in anchors:
            position = text.find(anchor, position + 1)
            self.assertGreaterEqual(position, 0, anchor)

    def test_the_plan_template_places_the_map_directly_after_the_task_index(self):
        headings = [line for line in self.plans.splitlines() if line.startswith("## ")]
        self.assertEqual(headings.count("## Task index"), 1)
        self.assertEqual(headings.count("## Acceptance map"), 1)
        self.assertEqual(headings[headings.index("## Task index") + 1], "## Acceptance map")
        self.assertIn("Task index, Acceptance map, and decision-ID", normalized(self.plans))

    def test_the_map_section_fixes_its_columns_kinds_owner_and_checks(self):
        mapping = normalized(self.section(self.plans, "## Acceptance map"))
        for phrase in (
            "| AC | Kind | Task | Check |",
            "`None — no acceptance criteria.`",
            "a tagged criterion is never reclassified",
            "`<kind> (classified)`",
            "exactly one owning `Task N` from the index",
            "the task that adds or runs the check",
            "the acceptance-record row `AC<n>` the owning task's implementer fills in",
            "The map is the plan's only acceptance surface",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, mapping)

    def test_self_review_checks_the_map_before_final_remeasurement(self):
        self.assert_ordered(
            normalized(self.plans), "## Self-review",
            "8. **Acceptance map** — one row per issue criterion",
            "9. **Final remeasurement**")

    def test_review_contract_blocks_a_missing_or_duplicated_row(self):
        self.assert_ordered(
            self.review, "## Reviewer instructions\n", "## Acceptance map check\n",
            "## Common-miss checklist\n")
        check = normalized(self.section(self.review, "## Acceptance map check"))
        for phrase in (
            "Each of these is **Blocking**:",
            "the `## Acceptance map` section is missing;",
            "a criterion has no row, or more than one;",
            "rows are out of issue order (`AC1` to `AC<n>`);",
            "a kind is outside `code`, `evidence`, `human`, or contradicts the issue's tag;",
            "an owning task is not a `Task N` in the Task index;",
            "an `evidence` row lacks its command, its conditions or its literal threshold.",
            "A `(classified)` kind you disagree with is **Should-fix**",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, check)
```

- [ ] **Step 2: Run the test and watch it fail**

Run: `PYTHONPATH=python timeout 300 python3 -m unittest -v home/common/agent-skills/tests/test_workflow_skill_contracts.py -k AcceptanceMapContracts 2>&1 | tail -5`
Expected: FAILED — all 4 tests fail or error (`## Decisions` follows `## Task index`; no `## Acceptance map` section; no `## Acceptance map check`).

- [ ] **Step 3: Write the minimal implementation**

In `home/common/agent-skills/skills/writing-plans/SKILL.md`:

1. In the `## Plan header` prose, change `Task index, and decision-ID` to `Task index, Acceptance map, and decision-ID` (keep the surrounding sentence; re-wrap if needed).

2. Inside the plan-header template fence, between the Task index block's closing line (``Example: `Task 3 — … [task-3.md](2026-08-19-feature.tasks/task-3.md)`>``) plus its blank line and `## Decisions`, insert exactly:

```markdown
## Acceptance map

<One row per acceptance criterion of the issue this plan serves, in issue order —
or, with no issue, of the requirements document. With no criteria, this section
holds the single line `None — no acceptance criteria.` Otherwise it is this table:

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code | Task 3 | `tests/test_config.py::test_loader_rejects_unknown_key` |

- `AC` — `AC1` to `AC<n>`, numbering the criteria in issue order, each exactly once.
- `Kind` — the issue's `[code|evidence|human]` tag, copied: a tagged criterion is
  never reclassified. An untagged criterion gets the kind you judge and is written
  `<kind> (classified)`.
- `Task` — exactly one owning `Task N` from the index: when several tasks
  contribute, the task that adds or runs the check.
- `Check` — for `code`, the test, check or CI job; for `evidence`, the command,
  the conditions, the literal threshold and the acceptance-record row `AC<n>` the
  owning task's implementer fills in; for `human`, the judgment that attests it
  and who makes it.

The map is the plan's only acceptance surface; task verification lines stay as
they are.>

```

3. In `## Self-review`, insert a new item 8 before the current `8. **Final remeasurement**` and renumber that item to 9:

```markdown
8. **Acceptance map** — one row per issue criterion in issue order, each kind
   copied from the issue's tag or written `<kind> (classified)`, each owner a
   `Task N` in the index, and every `evidence` row naming its command, its
   conditions and its literal threshold.
```

In `home/common/agent-skills/skills/from-issue/REVIEW-CONTRACT.md`, insert directly before `## Common-miss checklist` (after the hints paragraph that ends `fold those into this pass.` and its blank line):

```markdown
## Acceptance map check

Read the issue's acceptance criteria (or, with no issue, the requirements
document's) and the plan root's `## Acceptance map`. Each of these is **Blocking**:

- the `## Acceptance map` section is missing;
- a criterion has no row, or more than one;
- rows are out of issue order (`AC1` to `AC<n>`);
- a kind is outside `code`, `evidence`, `human`, or contradicts the issue's tag;
- an owning task is not a `Task N` in the Task index;
- an `evidence` row lacks its command, its conditions or its literal threshold.

A `(classified)` kind you disagree with is **Should-fix**: give the kind you would
assign and why.

```

- [ ] **Step 4: Verify**

Run: `PYTHONPATH=python timeout 300 python3 -m unittest -v home/common/agent-skills/tests/test_workflow_skill_contracts.py -k AcceptanceMapContracts 2>&1 | tail -3`
Expected: `Ran 4 tests` … `OK`

Run: `PYTHONPATH=python timeout 600 python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py 2>&1 | tail -3`
Expected: `OK` — existing writing-plans and REVIEW-CONTRACT pins (package contract, `## Accepted-edit remeasurement` order) still hold.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/skills/writing-plans/SKILL.md home/common/agent-skills/skills/from-issue/REVIEW-CONTRACT.md home/common/agent-skills/tests/test_workflow_skill_contracts.py
git commit -m "feat(writing-plans): require an Acceptance map and block a missing row in plan review (#274)"
```
