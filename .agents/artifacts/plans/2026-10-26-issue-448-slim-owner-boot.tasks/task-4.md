# Task 4: Cut 1 — one task file per dispatch (`--reviewed`)

Spec § Cut 1; per D5, D6, D16, D20. sdd's whole-package read and its conflict scan run only on a plan's unreviewed first entry. from-issue's Phase 6 passes sdd the literal token `--reviewed` on every route, because Phase 5's reviewer read the root and every member. A reviewed or resumed run keeps only the root and its checker metrics, and reads only `<plan stem>.tasks/task-<N>.md` before each dispatch. Every other caller passes no token and keeps today's validation. The resume pack and `workflow-state` are not touched.

**Files:**
- Modify: `home/common/agent-skills/skills/sdd/SKILL.md`: the `## Setup` paragraph that begins `**Initial validation is the only whole-package read.**`.
- Modify: `home/common/agent-skills/skills/from-issue/SKILL.md`: the first two sentences of `## Phase 6 — Execute`.
- Modify: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`: adds class `SlimBootContractsTest`.
- Modify: `.agents/artifacts/plans/2026-10-26-issue-448-slim-owner-boot.acceptance.md`: the Built cell of cut row 1.

**Interfaces:**
- Consumes: Task 3's cut row 1, `| 1 | … | <verdict> | <built> |`.
- Produces: class `SlimBootContractsTest` (docstring `Issue 448: the fresh-owner boot reads only what its phase needs.`), with the static helpers `read(path)` (`normalized` text) and `section(text, heading, next_heading)`. Tasks 5–6 add their tests to this class.

**Invariants:**
- `sdd/SKILL.md`'s `## Setup` (up to `### Cumulative delivery gate`) names the literal token `` `--reviewed` `` and the member path `` `<plan stem>.tasks/task-<N>.md` ``.
- `from-issue/SKILL.md`'s `## Phase 6 — Execute` (up to `## Phase 7 — Ship`) names `` `--reviewed` ``.
- Every rule of the old paragraph survives: the artifact-budget check first, the conflict scan's definition, one batched question, a missing member is a contract error, the held root and metrics, and the todo list from the Task index.
- The bytes of the two skill documents together fall (D5). No profile breaches its ceiling. The existing `LaunchFencedWorkerContractsTest.test_from_issue_phase_6_hands_sdd_its_lifecycle_identity` anchors (`## Phase 6 — Execute`, `### Lifecycle workers`, `` `deadline_at` ``, `workflow-state register-worker`, `## Phase 7 — Ship`) still appear in order.

- [ ] **Step 0: Read the verdict**

Run `bash -c 'grep -qE "^\| 1 \| .*\| keep \| " .agents/artifacts/plans/2026-10-26-issue-448-slim-owner-boot.acceptance.md'`. On a non-zero exit (the row says `reject`), change nothing, commit nothing, and report DONE with the note `cut 1 not built: Task 3 verdict` (D16).

- [ ] **Step 1: Write the failing test**

Add to `home/common/agent-skills/tests/test_workflow_skill_contracts.py`, after `class ResumePackContractsTest`:

```python
class SlimBootContractsTest(unittest.TestCase):
    """Issue 448: the fresh-owner boot reads only what its phase needs."""

    @staticmethod
    def read(path):
        return normalized(path.read_text(encoding="utf-8"))

    @staticmethod
    def section(text, heading, next_heading):
        start = text.index(heading)
        return text[start:text.index(next_heading, start + len(heading))]

    def test_phase_6_hands_sdd_the_reviewed_token_and_sdd_skips_the_package_read(self):
        phase_6 = self.section(self.read(FROM_ISSUE), "## Phase 6 — Execute", "## Phase 7 — Ship")
        self.assertIn("`--reviewed`", phase_6)
        setup = self.section(self.read(SDD), "## Setup", "### Cumulative delivery gate")
        self.assertIn("`--reviewed`", setup)
        self.assertIn("`<plan stem>.tasks/task-<N>.md`", setup)
```

- [ ] **Step 2: Run the test and watch it fail**

Run: `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py -k SlimBootContractsTest 2>&1 | tail -4'` (timeout 300 s).
Expected: FAIL, because `` `--reviewed` `` is not in `## Phase 6 — Execute`.

- [ ] **Step 3: Edit the two documents**

In `sdd/SKILL.md`, replace the paragraph from `**Initial validation is the only whole-package read.**` through `Build the todo list from the Task index.`. This draft measures 36 bytes shorter at `cf7232c1`; keep the file's ~90-column wrapping:

```markdown
**Initial validation is the only whole-package read, made only on an unreviewed first
entry** (no literal `--reviewed` token, no ledger naming this plan): read the root and
every indexed member once, in discovery order, and scan for conflicts — tasks that
contradict each other or the constraints, or anything the package mandates that the
review rubric treats as a defect. Before execution, present findings as one batched
question, each beside the plan text mandating it and asking which governs; a clean scan
proceeds silently. A missing or unreadable member is a contract error. Otherwise, and
afterwards, hold only the plan root, its checker metrics and the current task's
`sdd-gate` output, reading only `<plan stem>.tasks/task-<N>.md` before each dispatch.
Build the todo list from the Task index.
```

In `from-issue/SKILL.md`'s `## Phase 6 — Execute`, the first sentence becomes ``Invoke `sdd` with the literal token `--reviewed`: it dispatches an implementer per task and reviews each output by risk lane.``. In the second sentence, ``invoke it with this owner's`` becomes ``pass this owner's``. The draft measures 2 bytes longer, which is exactly the `from-issue-controller` hot headroom at `cf7232c1`. If the gate reports a breach, shorten the same paragraph further without dropping an anchor listed under Invariants.

- [ ] **Step 4: Verify**

Run: the Step 2 command. Expected: PASS, 1 test.
Run: **Skill contract tests**. Expected: PASS.
Run: **Budget**. Expected: `check: pass` (no `ceiling:` or `tightness:` line). On a `tightness:` line only, run `just agent-instruction-load tighten`, add `home/common/agent-skills/instruction-load.json` to the commit, and rerun.
Run the net-bytes check (fails unless the two documents together got shorter):

```bash
bash -c 'set -e; net=0; for f in home/common/agent-skills/skills/sdd/SKILL.md home/common/agent-skills/skills/from-issue/SKILL.md; do net=$((net + $(wc -c < "$f") - $(git show "HEAD:$f" | wc -c))); done; echo "net $net"; test "$net" -lt 0'
```

If the Budget or net-bytes check cannot pass without dropping a rule or an Invariants anchor, the cut fails D5's rule 2. Then revert the three files with `git checkout -- <file>`, set row 1's Verdict to `reject (instruction load)` and its Built to `not built`, and commit only the record.

- [ ] **Step 5: Record and commit**

Set cut row 1's Built cell to `built; net <n> bytes`, using the figure the check printed (for example `built; net -34 bytes`). Task 7 names the commit. Then:

```bash
git add home/common/agent-skills/skills/sdd/SKILL.md home/common/agent-skills/skills/from-issue/SKILL.md \
  home/common/agent-skills/tests/test_workflow_skill_contracts.py \
  .agents/artifacts/plans/2026-10-26-issue-448-slim-owner-boot.acceptance.md
git commit -m "feat(sdd): a reviewed or resumed plan reads one task file per dispatch (issue 448)"
```
