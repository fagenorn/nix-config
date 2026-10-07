# Task 2: State the `sdd` headroom rule and wire from-issue

**Files:**
- Modify: `home/common/agent-skills/skills/sdd/SKILL.md` (end of `### Lifecycle workers`, just before `### 1. Dispatch the implementer`)
- Modify: `home/common/agent-skills/skills/from-issue/SKILL.md` (`## Suspension procedure`, `## Phase 6 — Execute`)
- Modify: `home/common/agent-skills/instruction-load.json` (only the ceilings the gate reports as breached, and those profiles' `note`)
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes: Task 1's `workflow-state suspend --blocked-on deadline`; the existing argv spellings `workflow-state release-worker --repo-root <ledger_repo_root> --run-id <run-id> --worker-id <worker_id>` and `workflow-state mark-progress --repo-root <ledger_repo_root> --run-id <run-id> --action-id <action_id>`; test helpers `WorkflowSkillContractsTest.section`, `.assert_ordered`, `normalized`, `LaunchFencedWorkerContractsTest.assert_ordered` / `.read`.
- Produces: the skill contract the AC2 test pins; no code interface.

**Invariants:**
- Exactly one blank-line-delimited paragraph of sdd's `### Lifecycle workers` contains `` `blocked_on=deadline` ``, and in it `` `deadline_at` ``, the `release-worker` argv, the `mark-progress` argv and `` `blocked_on=deadline` `` appear in that order (D9). Never hard-wrap inside `` `blocked_on=deadline` ``.
- No new test asserts an English phrase; the 15-minute and longest-task wording is unpinned (D5).
- The existing anchors stay byte-identical: `(the reaper alone owns `unknown`)`, `` `ledger_repo_root`, `run_id` and `action_id` ``, `### Lifecycle workers`.
- from-issue's expired-deadline paragraph in `## Dispatch, phase-budget and attempt-budget rules` is not changed (spec, "from-issue suspension procedure").
- The instruction gate passes with the raise label; each raised ceiling equals its measured bytes exactly (D8).

- [ ] **Step 1: Write the failing tests**

In `WorkflowSkillContractsTest`, directly after `test_suspension_procedure_admits_agent_dispatch`, add:

```python
    def test_sdd_states_the_deadline_suspension_order(self):
        # #281 D5, D9: the one paragraph of `### Lifecycle workers` naming
        # `blocked_on=deadline` releases workers, records progress, then
        # suspends with that value, pinned by argv and value, not prose.
        workers = self.section(self.sdd, "### Lifecycle workers",
                               "### 1. Dispatch the implementer")
        paragraphs = [normalized(p) for p in re.split(r"\n\s*\n", workers)
                      if "`blocked_on=deadline`" in p]
        self.assertEqual(len(paragraphs), 1, paragraphs)
        self.assert_ordered(
            paragraphs[0],
            "`deadline_at`",
            "workflow-state release-worker --repo-root <ledger_repo_root> "
            "--run-id <run-id> --worker-id <worker_id>",
            "workflow-state mark-progress --repo-root <ledger_repo_root> "
            "--run-id <run-id> --action-id <action_id>",
            "`blocked_on=deadline`",
        )
```

In `test_suspension_procedure_admits_agent_dispatch`, add `` "`deadline`", `` between `` "`agent_dispatch`", `` and `` "(the reaper alone owns `unknown`)", `` in the `assert_ordered` call.

In `LaunchFencedWorkerContractsTest.test_from_issue_phase_6_hands_sdd_its_lifecycle_identity`, add `` "`deadline_at`", `` between `"### Lifecycle workers"` and `"register-worker"`.

- [ ] **Step 2: Run the tests and watch them fail**

Run: `PYTHONPATH=python python3 -m unittest -k deadline_suspension_order -k admits_agent_dispatch -k phase_6_hands_sdd home/common/agent-skills/tests/test_workflow_skill_contracts.py 2>&1 | tail -5`
Expected: FAILED (failures=3) — no paragraph carries `` `blocked_on=deadline` ``; `` `deadline` `` is missing after `` `agent_dispatch` ``; `` `deadline_at` `` is missing from Phase 6.

- [ ] **Step 3: Write the skill text**

`sdd/SKILL.md`: insert these two paragraphs at the end of `### Lifecycle workers` (after the paragraph ending "remains the authority on the attempt's state."). The numbered list must follow its lead-in line with no blank line, so the lead-in and list form one paragraph:

```markdown
When the caller also hands over the attempt's `deadline_at`, stop cleanly at
a task boundary instead of letting the reaper expire the attempt mid-task. A
task boundary is the moment before you dispatch a plan task, and the moment
after the last task's `complete` line, before the final review. Note each
task's dispatch instant with `date -u`; at its `complete` line, its wall time
is the elapsed difference. `longest` is the largest wall time of a task
completed this session (0 before the first), and `remaining` is `deadline_at`
minus `date -u`. At each boundary, when `remaining` is less than the larger of
15 minutes and `longest`:
1. release every worker this launch still has registered — normally none,
   because each is released when it returns; stop a still-live one and run
   `workflow-state release-worker --repo-root <ledger_repo_root> --run-id <run-id> --worker-id <worker_id> --event stopped`,
   as from-issue's **Writing workers** route says;
2. run
   `workflow-state mark-progress --repo-root <ledger_repo_root> --run-id <run-id> --action-id <action_id>`;
3. follow from-issue's suspension procedure with `blocked_on=deadline`.

A refused `mark-progress` does not stop these steps. If the suspend is
refused because the attempt is no longer active, the reaper expired it
first: follow from-issue's expired-deadline route — print
`/from-issue <num> --auto` on its own line and stop, with no retry. Without
a `deadline_at`, this rule does not apply.
```

`from-issue/SKILL.md`, `## Suspension procedure` (the quoted source text is hard-wrapped in the file; match it whitespace-insensitively and re-wrap near 80 columns):
- In the first paragraph, change "or a context that cannot launch the agents a phase needs." to "a context that cannot launch the agents a phase needs, or too little attempt budget left for the next `sdd` task."
- Change "with `<value>` one of `usage_limit`, `transport`, `human_gate`, `external`, or `agent_dispatch` (the reaper alone owns `unknown`)." to "with `<value>` one of `usage_limit`, `transport`, `human_gate`, `external`, `agent_dispatch`, or `deadline` (the reaper alone owns `unknown`). Only sdd's deadline headroom rule writes `deadline`."

`from-issue/SKILL.md`, `## Phase 6 — Execute`: directly after the sentence ending "and records a progress marker after each completed task.", insert: "Also hand `sdd` the `deadline_at` this owner adopted at acquisition, so sdd's deadline headroom rule can suspend cleanly at a task boundary."

- [ ] **Step 4: Run the focused tests**

Run: `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py home/common/agent-skills/tests/test_dispatch_contracts.py home/common/agent-skills/tests/test_shell_example_contracts.py home/common/agent-skills/tests/test_skill_lint.py 2>&1 | tail -3`
Expected: `OK`.

- [ ] **Step 5: Raise the breached instruction ceilings (D8)**

Run: `PYTHONPATH=python python3 -m agent_tools.instruction_load check --base origin/main 2>&1 | grep '^ceiling:'`
Expected before the raise: one or more `ceiling: <label> measures <N> bytes, above its ceiling <C>` lines (base headroom is 81 B for from-issue-controller and 0 B for orchestrated-issue-owner and implementation-owner). If none print, skip the rest of this step.

For each breached line, set that profile's `ceiling_bytes.<host>` (or the top-level `corpus_ceiling_bytes`) in `instruction-load.json` to exactly `<N>`, preserving the file's formatting (edit with a short `json`-module script that writes `indent=2` plus a trailing newline only if that reproduces the file byte-for-byte for unchanged members; otherwise edit the numbers in place). Append to each raised profile's `note` the sentence ` Ceiling raised for #281: sdd's deadline headroom rule and from-issue's \`deadline\` suspension value (#155 D10).` Touch no other ceiling or note.

Run: `just agent-instruction-budget --raise-label 2>&1 | tail -3`
Expected: `check: pass`.

Run: `just agent-instruction-budget 2>&1 | grep -c '^raise:'`
Expected: a count of at least 1 when Step 5 raised anything (the raise needs the human-applied `instruction-budget-raise` label), and no `ceiling:`, `tightness:` or `lint:` lines in the same output.

Run: `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_instruction_load.py 2>&1 | tail -3`
Expected: `OK`.

- [ ] **Step 6: Build**

Run: `just build` (foreground, timeout 3600000 ms) — skills are installed by the build.
Expected: exits 0.

- [ ] **Step 7: Commit**

When Step 5 raised a ceiling, the commit body carries the line `instruction-budget-raise needed: sdd's deadline headroom rule and from-issue's deadline value grew <profiles> past their ceilings; each is raised to its exact measured bytes.` (naming the raised profiles), per D8. The label itself is applied by a human on the PR; never apply it yourself.

```bash
git add home/common/agent-skills/skills/sdd/SKILL.md home/common/agent-skills/skills/from-issue/SKILL.md home/common/agent-skills/instruction-load.json home/common/agent-skills/tests/test_workflow_skill_contracts.py
launch-commit --repo-root <ledger_repo_root> --run-id <run-id> --worker-id <worker_id> -- -m "docs(skills): sdd suspends at a task boundary before its deadline (#281)" -m "<instruction-budget-raise line, if any>" -m "<attribution lines>"
```
