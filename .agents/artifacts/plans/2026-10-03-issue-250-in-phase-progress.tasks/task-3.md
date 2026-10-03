# Task 3: Owner instructions, skill contract, architecture document and completion gates

Lane: full (instructions that drive lifecycle owners). Decisions: per D1, D7
and D11 of the spec's ledger; the spec's "Skill prose" section owns what the
instructions must say.

**Files:**
- Modify: `home/common/agent-skills/skills/sdd/SKILL.md`
- Modify: `home/common/agent-skills/skills/from-issue/SKILL.md`
- Modify: `home/common/claude-code/skills/orchestrate-issues/SKILL.md`
- Modify: `home/common/agent-skills/instruction-load.json`
- Modify: `CLAUDE.md`
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes (from Task 2, already merged on this branch): the verb
  `workflow-state mark-progress --repo-root <ledger_repo_root> --run-id <run-id> --now <utc> --action-id <action_id>`,
  its four zero-exit outcomes `baseline`, `unchanged`, `advanced`, `diverged`,
  its exit-2 refusals, and the schema-6 attempt field `progress_marker`.
- Produces: nothing later tasks consume. This is the last task; its final
  step is the issue's completion gate.

**Invariants:**
- The exact command line above appears in sdd's `### Lifecycle workers`
  section, again in sdd's `### 5. Complete the task` after the `complete`
  sentence, and in from-issue's Phase 6 before the Phase 7 heading.
- Neither skill presents a `mark-progress` refusal as a reason to suspend or
  to stop the task loop (per D7).
- The pre-existing anchors of `LaunchFencedWorkerContractsTest` keep their
  order; that class stays green unedited.
- No instruction-load profile exceeds its ceiling.
- Every sentence written here describes what the code merged in Tasks 1–2
  does. Before committing, check each dictated clause against
  `record_progress_marker`, `probe_progress_head` and `command_mark_progress`;
  where the code differs, the code wins: correct the sentence and say so in
  your report.

## Steps

- [ ] **Step 1: Write the failing contract test**

Append to `home/common/agent-skills/tests/test_workflow_skill_contracts.py`,
directly after `LaunchFencedWorkerContractsTest` (before
`class CodebaseDesignSkillContractsTest`):

```python
class ProgressMarkerContractsTest(unittest.TestCase):
    """#250: the Phase 6 owner records a progress marker after each completed task."""

    MARK = ("workflow-state mark-progress --repo-root <ledger_repo_root> "
            "--run-id <run-id> --now <utc> --action-id <action_id>")
    BOUND = "without a phase advance or a newly recorded progress marker"

    def assert_ordered(self, text, *anchors):
        position = -1
        for anchor in anchors:
            next_position = text.find(anchor, position + 1)
            self.assertGreaterEqual(next_position, 0, anchor)
            position = next_position

    @staticmethod
    def read(path):
        return normalized(path.read_text(encoding="utf-8"))

    def test_sdd_records_a_marker_before_the_first_task_and_after_each_one(self):
        self.assert_ordered(
            self.read(SDD), "### Lifecycle workers", self.MARK,
            "once before dispatching the first task this session will execute",
            "after each task completes (step 5)",
            "### 1. Dispatch the implementer", "### 5. Complete the task",
            "appends `Task <N>: complete", self.MARK, "## Final review")

    def test_a_refused_marker_is_no_suspension_cause_in_sdd(self):
        self.assert_ordered(
            self.read(SDD), "### Lifecycle workers", self.MARK,
            "The reply's `outcome` is informational.",
            "A refusal changes nothing, is not a suspension cause and never stops "
            "the task loop", "### 1. Dispatch the implementer")

    def test_from_issue_phase_6_names_the_marker_on_both_routes(self):
        self.assert_ordered(
            self.read(FROM_ISSUE), "## Phase 6 — Execute",
            "`ledger_repo_root`, `run_id` and `action_id`",
            "records a progress marker after each completed task", self.MARK,
            "once before dispatching the mechanic and once after its change is "
            "committed", "is not a suspension cause", "## Phase 7 — Ship")

    def test_the_bound_is_described_as_progress_not_phase(self):
        for path, retired in ((FROM_ISSUE, "at the same recorded phase too many times"),
                              (ORCHESTRATE, "at the same phase too many times")):
            with self.subTest(path=path.name):
                text = self.read(path)
                self.assertIn(self.BOUND, text)
                self.assertNotIn(retired, text)

    def test_claude_md_describes_the_marker(self):
        self.assert_ordered(
            self.read(REPO_ROOT / "CLAUDE.md"),
            "The anti-zombie bound counts progress, not phase changes", self.MARK,
            "`progress_marker`", "`baseline`", "`advanced`", "`unchanged`",
            "`diverged`")
```

- [ ] **Step 2: Run it and watch it fail**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py -k ProgressMarkerContractsTest 2>&1 | tail -8`

Expected: 5 tests, 5 failures (the `MARK` anchor, the `BOUND` phrase and the
architecture bullet do not exist yet).

- [ ] **Step 3: Edit the skill sources**

Hard-wrap to the surrounding paragraph's width; the contract test collapses
whitespace, so only the words are pinned.

**sdd, `### Lifecycle workers`.** After the section's last paragraph (the
one ending `workers commit with plain \`git\`.`) and before
`### 1. Dispatch the implementer`, add this paragraph:

> Under a lifecycle identity, also record this launch's progress marker. Run
> `workflow-state mark-progress --repo-root <ledger_repo_root> --run-id <run-id> --now <utc> --action-id <action_id>`
> once before dispatching the first task this session will execute, and again
> after each task completes (step 5). The helper reads the commit checked out
> in the attempt's worktree itself; a commit that strictly descends from the
> last recorded one starts a fresh anti-zombie stall count, so a long run that
> suspends between tasks is not stopped as stalled. The reply's `outcome` is
> informational. A refusal changes nothing, is not a suspension cause and
> never stops the task loop: the next `workflow-state progress` or
> `check-launch` remains the authority on the attempt's state.

**sdd, `### 5. Complete the task`.** Append one sentence to the end of the
section's existing paragraph (after `…that are neither fixed nor parked.`):

> Under a lifecycle identity, run
> `workflow-state mark-progress --repo-root <ledger_repo_root> --run-id <run-id> --now <utc> --action-id <action_id>`
> immediately after appending that `complete` line, as `### Lifecycle workers`
> describes.

**from-issue, `## Phase 6 — Execute`.** Replace the paragraph that begins
`With lifecycle identity, invoke \`sdd\`` with:

> With lifecycle identity, invoke `sdd` with this owner's
> `ledger_repo_root`, `run_id` and `action_id` as its lifecycle identity, so
> sdd's `### Lifecycle workers` registers each writing agent under this
> launch and records a progress marker after each completed task. The
> mechanical route's mechanic is registered the same way: run
> `workflow-state register-worker` before dispatching it, put the
> `Lifecycle worker:` line in its prompt, and release it when it returns. On
> that route this owner records the marker itself: run
> `workflow-state mark-progress --repo-root <ledger_repo_root> --run-id <run-id> --now <utc> --action-id <action_id>`
> once before dispatching the mechanic and once after its change is
> committed. A refusal changes nothing and is not a suspension cause.

**from-issue, the expiry paragraph.** In the sentence
`At the anti-zombie bound — an attempt parked at the same recorded phase too many times in a row — the reaper ends the work`,
replace the parenthetical so it reads:

> At the anti-zombie bound — an attempt parked too many times in a row
> without a phase advance or a newly recorded progress marker — the reaper
> ends the work

**orchestrate-issues.** In
`home/common/claude-code/skills/orchestrate-issues/SKILL.md`, the clause
`where the attempt has already been parked at the same phase too many times in a row,`
becomes:

> where the attempt has already been parked too many times in a row without a
> phase advance or a newly recorded progress marker,

Change nothing else in these files.

- [ ] **Step 4: Raise the instruction-load ceilings**

The skill prose grew, and the hot-path ceilings in
`home/common/agent-skills/instruction-load.json` have no headroom. Measure:

```bash
PYTHONPATH="$PWD/python" python3 - <<'PY'
from pathlib import Path
from agent_tools import instruction_load as il
root = Path(".").resolve()
model = il.load_model((root / il.MODEL_PATH).read_bytes())
measured = il.measure(model, il.tree_reader(root))
for profile in model["profiles"]:
    for host in profile["hosts"]:
        used = measured["profiles"][profile["id"]][host]["hot"]["bytes"]
        if used > profile["ceiling_bytes"][host]:
            print(profile["id"], host, profile["ceiling_bytes"][host], "->", used)
PY
```

For every `(profile, host)` line it prints, set that profile's
`ceiling_bytes.<host>` to the printed measured value — no extra slack — and
append one sentence to the profile's `note`, following the existing notes'
form. Use
`Ceiling raised for #250: sdd and from-issue Phase 6 record a progress marker after each task, and the stall bound's description names it (#155 D10).`
for a profile that loads `from-issue/SKILL.md` or `sdd/SKILL.md`, and
`Ceiling raised for #250: the anti-zombie sentence names the progress marker (#155 D10).`
for one that loads only `orchestrate-issues/SKILL.md`. Expect
`from-issue-controller`, `orchestration-dispatcher`,
`orchestrated-issue-owner` and `implementation-owner`; raise exactly what the
script prints and nothing else. Keep the file's existing formatting. Re-run
the script: it must print nothing.

- [ ] **Step 5: Update the architecture document**

In `CLAUDE.md`, under "Key conventions & gotchas", insert this bullet directly
after the bullet that begins `Orchestration admission is declared, not measured`
(same two-space indentation as its neighbours, one physical line):

> - The anti-zombie bound counts progress, not phase changes: an attempt is stopped as `stopped(stalled)` on its fourth consecutive suspension with neither a phase advance nor a newly recorded progress marker. `workflow-state mark-progress --repo-root <ledger_repo_root> --run-id <run-id> --now <utc> --action-id <action_id>` records the marker for the current launch of an active attempt: the helper itself reads the commit checked out in the attempt's recorded worktree and stores it as the attempt's `progress_marker` (ledger schema 6; `null` until first recorded). The first recording is a `baseline` and resets nothing; a commit that strictly descends from the stored marker is `advanced` and starts a fresh stall count; the same commit (`unchanged`) and a commit that does not descend from it (`diverged`) write nothing; a launch that is not current, a remainder launch, and a worktree git cannot read are refused. `sdd` records a marker before its first task of a session and after each completed task, so a long Phase 6 that suspends between tasks is not discarded.

In the same file, the launch-fence sentence says writers are registered "in
the ledger's schema-5 `workers` list". The ledger is now schema 6, so reword
that phrase to "in the ledger's `workers` list (added in schema 5)"; the
existing `test_claude_md_describes_the_launch_fence` anchors still match.

Do not touch the `@.agents/instructions/bootstrap.md` import line or
`AGENTS.md`; those are generated.

- [ ] **Step 6: Verify**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py -k ProgressMarkerContractsTest -k LaunchFencedWorkerContractsTest 2>&1 | tail -4`
Expected: `OK` — the 5 new tests and every pre-existing launch-fence contract.

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_instruction_load.py 2>&1 | tail -4`
Expected: `OK` (`test_the_live_tree_breaches_no_ceiling` included).

Run:
```bash
if grep -q 'schema-5 `workers` list' CLAUDE.md; then exit 1; fi
```
Expected: exit 0 (the stale schema claim is gone).

- [ ] **Step 7: Commit**

```bash
git add home/common/agent-skills/skills/sdd/SKILL.md \
  home/common/agent-skills/skills/from-issue/SKILL.md \
  home/common/claude-code/skills/orchestrate-issues/SKILL.md \
  home/common/agent-skills/instruction-load.json \
  home/common/agent-skills/tests/test_workflow_skill_contracts.py \
  CLAUDE.md
git commit -m "docs(sdd,from-issue): record a progress marker after each Phase 6 task (#250)"
```

The message ends with the co-author trailer from the plan's Global Constraints.

- [ ] **Step 8: Completion gates for the issue**

Run both from the worktree root, after the commit, and report what each
printed:

Run: `just agent-workflow-tests 2>&1 | tail -6`
Expected: `OK`, zero failures and errors.

Run: `just build 2>&1 | tail -15`
Expected: the build completes with exit status 0. Nix evaluates only tracked
files, which is why this runs after the commit. A failure here is fixed at its
cause and committed as a follow-up; it is never waived.
