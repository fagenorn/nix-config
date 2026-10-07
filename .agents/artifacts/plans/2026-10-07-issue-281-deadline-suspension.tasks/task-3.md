# Task 3: Sync with `main` and fit under the instruction ceilings with no raise

**Files:**
- Merge: `origin/main` into the branch (one signed merge commit)
- Modify: `home/common/agent-skills/instruction-load.json` (take main's file unchanged; lower a ceiling only through `tighten`)
- Modify: `home/common/agent-skills/skills/sdd/SKILL.md` (opening **Continuous execution**, `### Lifecycle workers`, `### 2. Handle the report`, `### 5. Complete the task`)
- Modify: `home/common/agent-skills/skills/from-issue/SKILL.md` (`## Suspension procedure`, `## Phase 6 — Execute`)
- Test (unchanged, kept green): `home/common/agent-skills/tests/test_workflow_skill_contracts.py`, `test_dispatch_contracts.py`, `test_agent_model_matrix.py`, `test_shell_example_contracts.py`, `test_skill_lint.py`, `test_instruction_load.py`, `test_eval_cases.py` (all under `home/common/agent-skills/tests/`)

**Interfaces:**
- Consumes: Tasks 1–2 as committed (the `deadline` value, sdd's headroom paragraph, from-issue's `deadline_at` handover); main's `instruction-load.json` after #295.
- Produces: no new interface. The skill contract keeps every pin Task 2 and earlier issues set (D14).

**Invariants:**
- No instruction-load ceiling rises, no note claims a raise, and no `--raise-label` is used anywhere in this task (D12; issue AC4). A ceiling may only be lowered, with `just agent-instruction-load tighten`, when the gate reports `tightness:` (D12).
- Every cut preserves meaning (D16): it drops only restated mechanism or text a sibling file of the same hot set already carries. No D4, D6 or D11 behavior leaves sdd's headroom paragraph; the merged step-2 gate keeps every exit route.
- No test is loosened, deleted or rewritten to free bytes (D14). The pins that bound the cuts:
  - sdd `### Lifecycle workers`: exactly one paragraph contains `` `blocked_on=deadline` `` and carries, in order, `` `deadline_at` ``, the `workflow-state release-worker --repo-root <ledger_repo_root> --run-id <run-id> --worker-id <worker_id>` prefix, `workflow-state mark-progress --repo-root <ledger_repo_root> --run-id <run-id> --action-id <action_id>`, `workflow-state check-launch --repo-root <ledger_repo_root> --run-id <run-id> --action-id <action_id>`, `` `current: false` ``, `` `/from-issue <num> --auto` ``, `` `current: true` ``, `` `blocked_on=deadline` `` (D9, D11). Never hard-wrap inside a backticked span.
  - `SDD_MACHINE_TEXT[SDD]`: `validate-report --boundary sdd`, `detail_state: "none"`, `report_path: null`, `validate-detail-input`, `detail_state: "unpublished"`, `scripts/task-brief PLAN_FILE N`, `artifact-budget validate-report --boundary producer --input -`, `stable-first-fit-whole-file`, `member_count`, `aggregate_bytes`, the register/release/check-launch/mark-progress argv, the `Lifecycle worker:` line, the `launch-scope exec`/`scratch` argv, `launch fence refused:`. sdd also keeps `complete`, `within_budget` and `contract error`, and the report field names.
  - Every `<!-- agent-dispatch: … -->` marker and its `Agent(…)` line, byte-identical; #261's **Interim child results** paragraphs, untouched.
  - from-issue `## Phase 6 — Execute`, in order: `` `ledger_repo_root`, `run_id` and `action_id` ``, `### Lifecycle workers`, `records a progress marker after each completed task`, `` `deadline_at` ``, `register-worker`, the mark-progress argv, `once before dispatching the mechanic and once after its change is committed`, `is not a suspension cause`.
  - from-issue `## Suspension procedure`: `` `agent_dispatch` ``, `` `deadline` ``, `(the reaper alone owns `unknown`)` in that order; `release every worker`, `live workers:`. The expired-deadline paragraph in `## Dispatch, phase-budget and attempt-budget rules` is untouched.

- [ ] **Step 1: Merge `origin/main` (D12)**

```bash
git fetch origin
git merge --no-ff --no-commit origin/main
git checkout origin/main -- home/common/agent-skills/instruction-load.json
git diff --name-only --diff-filter=U
```

Expected: the last command prints nothing. Planning observed `instruction-load.json` as the only conflict against `baac2897`; if main has advanced and another file conflicts, keep both sides' meaning and re-run every pin listed above. Conclude the merge:

`launch-commit --repo-root <ledger_repo_root> --run-id <run-id> --worker-id <worker_id> -- -m "Merge origin/main into the #281 branch" -m "instruction-load.json takes main's file unchanged; #281 no longer raises a ceiling (D12)." -m "<attribution lines>"`

Then confirm the model is main's: `git diff --quiet origin/main -- home/common/agent-skills/instruction-load.json` exits 0.

- [ ] **Step 2: Watch the gate fail**

Run: `just agent-instruction-budget 2>&1 | grep -E '^(ceiling|tightness|lint|raise):'`
Expected: `ceiling:` lines for from-issue-controller (claude, codex), orchestrated-issue-owner, implementation-owner (claude, codex) and the corpus. Against `baac2897` planning measured overages of 270 B, 2207 B, 2207 B and 2152 B (D13). Re-measure here: #279 or other merges may move them, and these numbers are estimates, not targets.

- [ ] **Step 3: Cut #281's own text (D13 cut 1)**

`sdd/SKILL.md`, `### Lifecycle workers`: replace the numbered headroom list and the paragraph after it with this single paragraph (re-wrap near 80 columns, never inside a backticked span):

```markdown
With the attempt's `deadline_at` also handed over, check headroom at each
task boundary: before dispatching a task, and after the last `complete` line,
before the final review. `remaining` is `deadline_at` minus `date -u`;
`longest` is the largest dispatch-to-`complete` wall time of a task completed
this session (0 before the first). When `remaining` is under the larger of
15 minutes and `longest`, stop any still-live worker and run `workflow-state release-worker --repo-root <ledger_repo_root> --run-id <run-id> --worker-id <worker_id> --event stopped`,
then `workflow-state mark-progress --repo-root <ledger_repo_root> --run-id <run-id> --action-id <action_id>`
(a refusal does not stop you), then `workflow-state check-launch --repo-root <ledger_repo_root> --run-id <run-id> --action-id <action_id>`.
On `current: false` or any helper failure, write nothing more, print
`/from-issue <num> --auto` on its own line and stop. On `current: true`,
follow from-issue's suspension procedure with `blocked_on=deadline`; a suspend
refused because the attempt is no longer active means the reaper expired it:
follow from-issue's expired-deadline route, with no retry.
```

`sdd/SKILL.md`, **Continuous execution**: "all-tasks-complete, or the deadline headroom rule in `### Lifecycle workers`." becomes "all-tasks-complete, or the deadline headroom rule."

`from-issue/SKILL.md`, `## Suspension procedure`: restore the first paragraph's trigger list to main's wording ("…an external wait (never a child's interim result; see **Interim child results**), or a context that cannot launch the agents a phase needs."); sdd defines the deadline trigger (D16). In the value list write "`agent_dispatch`, or sdd's `deadline` (the reaper alone owns `unknown`)." and delete the sentence "Only sdd's deadline headroom rule writes `deadline`."

`from-issue/SKILL.md`, `## Phase 6 — Execute`: replace "Also hand `sdd` the `deadline_at` … at a task boundary." with "Also hand it the `deadline_at` this owner currently holds (a later `declare-lane` reply's value supersedes the acquired one)." (D10 keeps its meaning.)

- [ ] **Step 4: Cut nearby restated mechanism (D13 cut 2)**

- sdd, the `launch fence refused:` paragraph: drop "Whatever the reason," and "not every reason means a supersession, so then"; keep release, no retry/re-dispatch, the check-launch argv, both outcomes (`current: false`/helper failure → superseded route, print and stop; `current: true` → suspension with `blocked_on=transport`) and the plain-`git` sentence.
- sdd, the mark-progress paragraph: keep the argv, both timings (before the first task this session executes; after each completed task, step 5), that an advancing commit resets the stall count, and that a refusal changes nothing, is not a suspension cause and never stops the task loop. Drop the restated helper mechanism ("reads the commit checked out…", "so a long run that suspends between tasks is not stopped as stalled", "the next `workflow-state progress` or `check-launch` remains the authority").
- sdd step 5: replace its trailing argv sentence with "Under a lifecycle identity, record the progress marker right after that `complete` line (`### Lifecycle workers`)."
- from-issue Phase 6, the mechanical-route sentences: condense to "On the mechanical route, register its mechanic the same way (`workflow-state register-worker` before dispatch, the `Lifecycle worker:` line in its prompt, release on return) and run <mark-progress argv> once before dispatching the mechanic and once after its change is committed. A refusal changes nothing and is not a suspension cause."

- [ ] **Step 5: Merge sdd step-2 duplicates (D13 cut 3)**

- Merge the two closed-gate paragraphs ("Every initial review-package call…" and "Record the exact `base_sha and head_sha`…") into one that states, in order: record `base_sha` and `head_sha` before the producer; validate with `artifact-budget validate-report --boundary producer --input -`, then `artifact-budget check --kind review-package` on its root and compare all four metrics; only generator exit 0, validator exit 0, a strict `complete` report and agreement permit dispatch; exit 3 must validate as `decompose_required`, recorded and returned with no reviewer dispatched; on generator or validator exit 2, the exact failed SDD candidate with `detail_state: "none"` and `report_path: null`, through `artifact-budget validate-report --boundary sdd`, returning only canonical stdout; malformed or unknown output and any report/checker disagreement are `failed` before dispatch; `complete` plus `over_budget` is a contract error.
- Interface versions 2 and 3: keep only the controller's guards — v2 only for a positively identified auto-generated EF Core migration designer replaced by bounded deterministic evidence; anything else that large exits 3; never classify by suffix, truncate a diff, or treat generated evidence as a review waiver; v3 only when a complete v1/v2 `-U10` package fails solely on `member_count` and/or `aggregate_bytes`, retrying contexts 7, 5, 3, 1, 0 with `stable-first-fit-whole-file`, never splitting a file diff or omitting a changed line; `member_bytes` and `root_bytes` never take it. Drop the reviewer duties only after confirming `rg -c 'EF Core|context_lines' home/common/agent-skills/skills/sdd/{task-reviewer-prompt,correctness-reviewer-prompt,final-review}.md` reports a nonzero count for each file (D13).

- [ ] **Step 6: Run the focused tests and the gate**

Run: `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py home/common/agent-skills/tests/test_dispatch_contracts.py home/common/agent-skills/tests/test_agent_model_matrix.py home/common/agent-skills/tests/test_shell_example_contracts.py home/common/agent-skills/tests/test_skill_lint.py home/common/agent-skills/tests/test_instruction_load.py home/common/agent-skills/tests/test_eval_cases.py 2>&1 | tail -3`
Expected: `OK`.

Run: `just agent-instruction-budget 2>&1 | tail -3`
Expected: `check: pass`, with no `ceiling:`, `raise:`, `tightness:` or `lint:` line. A remaining `ceiling:` line means cut more, in D13's order and within D16; never raise. A `tightness:` line means run `just agent-instruction-load tighten` and re-run the gate. Then `git diff --quiet origin/main -- home/common/agent-skills/instruction-load.json` exits 0, unless `tighten` lowered a ceiling, in which case `git diff -U0 origin/main -- home/common/agent-skills/instruction-load.json | grep '^+ *"'` shows only smaller numbers.

Record the observed headroom per profile in the acceptance record's AC4 row (Observed column), with the commit, leaving the verdict `pending`: the Instruction Budget CI check on the PR decides it.

- [ ] **Step 7: Build**

Run: `just build` (foreground, timeout 3600000 ms). Expected: exits 0.

- [ ] **Step 8: Commit**

```bash
git add home/common/agent-skills/skills/sdd/SKILL.md home/common/agent-skills/skills/from-issue/SKILL.md home/common/agent-skills/instruction-load.json .agents/artifacts/plans/2026-10-07-issue-281-deadline-suspension.acceptance.md
launch-commit --repo-root <ledger_repo_root> --run-id <run-id> --worker-id <worker_id> -- -m "docs(skills): fit #281 under the instruction ceilings without a raise" -m "<attribution lines>"
```

The commit body carries no `instruction-budget-raise needed:` line. The ship phase syncs with `main` again right before the PR, because #279 is in flight, and re-runs `just agent-instruction-budget`. Any new overage is cut in D13's order and never raised (D15).
