# Task 5: The sdd skill dispatches by rendered brief

**Files:**
- Modify: `home/common/agent-skills/skills/sdd/SKILL.md`
- Modify: `home/common/agent-skills/skills/sdd/task-reviewer-prompt.md` (the `**Placeholders:**` line only)
- Modify: `home/common/agent-skills/skills/sdd/evals/evals.json` (three `expected_output` strings)
- Modify: `home/common/agent-skills/tests/test_workflow_skill_contracts.py` (`SDD_MACHINE_TEXT`)
- Modify: `home/common/agent-skills/tests/test_shell_example_contracts.py` (`COMMAND_VOCABULARY`)
- Create: `.agents/artifacts/plans/2026-10-10-issue-353-sdd-gate-rendered-briefs.acceptance.md` (rows AC1 and AC2 only)
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`, `home/common/agent-skills/tests/test_shell_example_contracts.py`, `home/common/agent-skills/tests/test_eval_cases.py`, `just agent-instruction-budget`

**Interfaces:**
- Consumes, from Tasks 3–4, the installed command's contract, which the skill text below states: `sdd-gate next PLAN_FILE --skill-dir DIR [--completed N [--parked K]] [--task M [--context-file PATH]] [--delivery-base SHA] [--standards PATH]... [--repo-root R --run-id I --action-id A]` and `sdd-gate review PLAN_FILE --skill-dir DIR --task N [--standards PATH]... [--repo-root R --run-id I --action-id A --worker-id W]`; one JSON object on stdout with `outcome` `ready` or `refused`; a ready object carries `brief_path`, `worker_id` (`next`) and `manifest_root` and `metrics` (`review`); a refused object carries `step` and `gate` (`decompose_required`, `failed` or `null`).
- Consumes, from Task 1: the reviewer template's line `**Placeholders:** every bracketed capital token above is filled before dispatch.`
- Produces: skill text in which steps 1–3 and 5 of the task loop instruct the two `sdd-gate` calls and a one-sentence dispatch prompt; two `sdd-gate` argv pins in `SDD_MACHINE_TEXT`; `sdd-gate` in the shell-example vocabulary; the acceptance record's two evidence rows.

**Invariants (spec "The skill's dispatch contract"; D7, D11, D13):**
- The headings `### Lifecycle workers`, `### 1. Dispatch the implementer`, `### Review-package gate` and `### Cumulative delivery gate` keep their exact text: tests and `final-review.md` anchor on them.
- Every other string `SDD_MACHINE_TEXT` pins for `SKILL.md` stays present: the `register-worker`, `release-worker`, `check-launch` and `mark-progress` argv, the `Lifecycle worker:` line, both `launch-scope` argv, `launch fence refused:` and `artifact-budget validate-report --boundary producer --input -`.
- Every dispatch marker line, every `Agent(...)` line, the leaf-agent clauses paragraph and both `Template:` links are unchanged.
- No living example in the skill feeds `sdd-gate` through a heredoc, pipe or redirect: the context goes in a file (D11).
- `fix-loop.md`, `re-review-prompt.md`, `final-review.md`, the two final-review prompts and `implementer-prompt.md` are not edited in this task.
- `home/common/agent-skills/instruction-load.json` and the gate files are not edited.
- No test asserts an English phrase: the two new pins are argv (rule 6).

- [ ] **Step 1: Change the pins first**

In `home/common/agent-skills/tests/test_workflow_skill_contracts.py`, inside `SDD_MACHINE_TEXT`'s entry for `SDD`, replace

```python
        "scripts/task-brief PLAN_FILE N", PRODUCER_VALIDATION,
```

with

```python
        "sdd-gate next PLAN_FILE --skill-dir <skill-dir> --task N",
        "sdd-gate review PLAN_FILE --skill-dir <skill-dir> --task N", PRODUCER_VALIDATION,
```

In `home/common/agent-skills/tests/test_shell_example_contracts.py`, add `"sdd-gate"` to `COMMAND_VOCABULARY` directly before `"sdd-workspace"`. From then on every inline code span that starts with `sdd-gate` is a living example and is checked for refused shell forms.

- [ ] **Step 2: Run the test and watch it fail**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py -k test_sdd_documents_carry_their_machine_text`
Expected: FAIL in two subtests of `SKILL.md`, each `'sdd-gate … --task N' not found`.

- [ ] **Step 3: Edit the skill text**

Apply these twelve edits exactly. Each "replace" text is the file's text after Task 1; the text was measured, so do not reword it (see Step 6 if the budget gate disagrees).

**Edit 1** — in `home/common/agent-skills/skills/sdd/task-reviewer-prompt.md`, replace this text, which occurs exactly once:

````text
**Placeholders:** every bracketed capital token above is filled before dispatch.
````

with:

````text
**Placeholders:** `sdd-gate review` fills every bracketed capital token above.
````

**Edit 2** — in `home/common/agent-skills/skills/sdd/SKILL.md`, replace this text, which occurs exactly once:

````text
metrics, and the current task's brief from `scripts/task-brief`. Build the todo
list from the Task index.
````

with:

````text
metrics, and the current task's `sdd-gate` output. Build the todo list from the
Task index.
````

**Edit 3** — in `home/common/agent-skills/skills/sdd/SKILL.md`, replace this text, which occurs exactly once:

````text
local integration branch. Before the first implementer, and after each completed
task before any next dispatch, pin `DELIVERY_HEAD` to the full `git rev-parse
HEAD` SHA and run `review-package PLAN_FILE DELIVERY_BASE DELIVERY_HEAD`, then
apply the review-package gate.
````

with:

````text
local integration branch. Before the first implementer, and after each completed
task before any next dispatch, `sdd-gate next` pins `DELIVERY_HEAD` to the full
`git rev-parse HEAD` SHA, runs `review-package PLAN_FILE DELIVERY_BASE
DELIVERY_HEAD` and applies the review-package gate.
````

**Edit 4** — in `home/common/agent-skills/skills/sdd/SKILL.md`, replace this text, which occurs exactly once:

````text
four metrics. Seven-character path prefixes never establish range identity.
Record both full SHAs and the four checked metrics in the ledger. A non-passing
gate cannot advance:
````

with:

````text
four metrics. Seven-character path prefixes never establish range identity.
The helper records both full SHAs and the four checked metrics in the ledger. A non-passing
gate cannot advance:
````

**Edit 5** — in `home/common/agent-skills/skills/sdd/SKILL.md`, replace this text, which occurs exactly once:

````text
A resumed agent is registered again and gets a fresh `worker_id`.
Read-only reviewers are not registered.
````

with:

````text
A resumed agent is registered again and gets a fresh `worker_id`.
Read-only reviewers are not registered. `sdd-gate` makes the register, release
and progress calls for the two dispatches it renders.
````

**Edit 6** — in `home/common/agent-skills/skills/sdd/SKILL.md`, replace this text, which occurs exactly once:

````text
Under a lifecycle identity, run
`workflow-state mark-progress --repo-root <ledger_repo_root> --run-id <run-id> --action-id <action_id>`
before dispatching the first task this session executes and after each task's `complete` line (step 5).
A refusal changes nothing and never stops the task loop.
````

with nothing (delete it, together with the one empty line that follows it).

**Edit 7** — in `home/common/agent-skills/skills/sdd/SKILL.md`, replace this text, which occurs exactly once:

````text
Record BASE (`git rev-parse HEAD`) first.

- `scripts/task-brief PLAN_FILE N` revalidates the package, copies exactly one
  convention-linked member byte-for-byte and prints the brief path. Checker exit
  2/3 or a missing, unreadable, duplicate or nonconventional member link stops
  before replacing an existing brief. The brief is the single source of
  task-specific requirements; never make a subagent read the whole plan package.
- The dispatch contains: one line on where the task fits; the plan root path and
  all four metrics; the brief path ("read this first — it is your requirements,
  with the exact values to use verbatim"); interfaces and decisions from earlier
  tasks the brief cannot know; your resolution of any ambiguity you noticed; the
  report-file path (brief `…/task-N-brief.md` → `…/task-N-report.md`) and report
  contract. Never member lists, task contents or prior-task history.
- If an earlier task parked a finding in this task's area, carry a pointer to that ledger entry.
- Record the implementer's agent identity — fix rounds 1–3 resume it.
- Never dispatch multiple implementers in parallel (conflicts).
````

with:

````text
Run `sdd-gate next PLAN_FILE --skill-dir <skill-dir> --task N`
(`<skill-dir>` is this file's directory), adding:

- `--completed <previous-task>` after that task's review, with `--parked <K>`
  for parked findings (step 5);
- `--delivery-base <DELIVERY_BASE>` on the run's first call;
- one `--standards <path>` per retained `bindings.paths.standards` entry;
- `--context-file <file>`, written with the file-writing tool: where the task
  fits, interfaces and decisions from earlier tasks the brief cannot know, your
  resolution of any ambiguity, a pointer to the ledger entry of a finding parked
  in this area. Never member lists, task contents or prior-task history;
- `--repo-root <ledger_repo_root> --run-id <run-id> --action-id <action_id>`
  under a lifecycle identity.

It records the task's base, marks progress, runs the cumulative delivery gate,
writes the task brief, registers the worker and prints one JSON object. On `outcome: ready` the whole prompt is
`Read the dispatch brief at <brief_path> and follow it exactly.`; agent type,
model and effort come from the template's marker lines.

On `outcome: refused` dispatch nothing: `gate: decompose_required` and
`gate: failed` are the review-package gate's second and third exits; step
`release-worker` or `register-worker` is a lifecycle failure under
`### Lifecycle workers`; any other `step` is a contract error: stop. Once the
cause is fixed, re-run the same call.

- Record the implementer's agent identity and `worker_id`: fix rounds 1–3 resume it.
- Never dispatch multiple implementers in parallel (conflicts).
````

**Edit 8** — in `home/common/agent-skills/skills/sdd/SKILL.md`, replace this text, which occurs exactly once:

````text
- **DONE** → run `review-package PLAN_FILE BASE HEAD` (BASE from step 1 — never `HEAD~1`) and apply the review-package gate before step 3.
````

with:

````text
- **DONE** → run `sdd-gate review PLAN_FILE --skill-dir <skill-dir> --task N` with step 1's `--standards` and lifecycle flags plus `--worker-id <worker_id>`. It releases the worker, gates the task's review package and renders the reviewer brief; a refusal routes as in step 1.
````

**Edit 9** — in `home/common/agent-skills/skills/sdd/SKILL.md`, replace this text, which occurs exactly once:

````text
- **NEEDS_CONTEXT** → provide it, re-dispatch.
- **BLOCKED** → a `launch fence refused` report follows `### Lifecycle workers` and is never re-dispatched. Otherwise: context problem: add context, re-dispatch at the same tier. Reasoning problem: escalate to a fresh Opus/high implementer carrying the brief path, the report path and the blocker:
````

with:

````text
- **NEEDS_CONTEXT** → release the worker, then repeat step 1's call with the context added: the task base is kept and a fresh worker registered.
- **BLOCKED** → a `launch fence refused` report follows `### Lifecycle workers` and is never re-dispatched. Otherwise: context problem: re-dispatch as for NEEDS_CONTEXT, at the same tier. Reasoning problem: the same, with the blocker and the report path in the context, to a fresh Opus/high implementer:
````

**Edit 10** — in `home/common/agent-skills/skills/sdd/SKILL.md`, replace this text, which occurs exactly once:

````text
- **mechanical / low-risk lane** — scoped verification: dispatch reviewer-lite with the declared lane and the bounded task diff.
````

with:

````text
- **mechanical / low-risk lane** — scoped verification: dispatch reviewer-lite with the declared lane and the `manifest_root` and `metrics` `sdd-gate review` printed; its rendered brief is not dispatched.
````

**Edit 11** — in `home/common/agent-skills/skills/sdd/SKILL.md`, replace this text, which occurs exactly once:

````text
- The reviewer gets the plan root path and all four metrics, then the brief and
  report paths plus the review-package manifest root path and all four metrics.
  It never gets a member list, shard list, artifact contents, diff contents, or
  another task body.
- No open-ended directives ("check all uses") without a concrete task-specific reason, no asking it to re-run tests the implementer ran, and never pre-judge: a prompt containing "do not flag" or "at most Minor" is wrong; adjudication happens in the loop.
````

with:

````text
- The whole prompt is step 1's sentence with `sdd-gate review`'s `brief_path`:
  adjudication happens in the loop.
````

**Edit 12** — in `home/common/agent-skills/skills/sdd/SKILL.md`, replace this text, which occurs exactly once:

````text
Clean review — or everything parked-with-ruling at the cap — appends `Task <N>: complete (commits <base7>..<head7>, review clean | <K> parked)`; mark the todo, run the cumulative delivery gate, then move on only when it passes.
````

with:

````text
Clean review — or everything parked-with-ruling at the cap — is recorded by the next `sdd-gate next --completed N` (step 1's call, without `--task` after the last task): it appends `Task <N>: complete (commits <base7>..<head7>, review clean | <K> parked)` and runs the cumulative delivery gate. Mark the todo and move on only on `outcome: ready`.
````

What the edits remove is text the helper makes dead (D13): the `task-brief` and dispatch-contents bullets of step 1, the standalone `mark-progress` paragraph (`sdd-gate next` runs it on every call; its argv stays pinned in the deadline paragraph), and the two step-3 bullets about composing a reviewer prompt, which is now one fixed sentence.

- [ ] **Step 4: Reword the three evals**

In `home/common/agent-skills/skills/sdd/evals/evals.json` change only `expected_output` strings, each substring occurring exactly once. Keep the JSON valid and every other byte as it is.

Eval 1 (`task-loop-and-fix-loop-discipline`), replace

```text
(1) The dispatch carries a task brief extracted to a file (the brief path is the single source of requirements — contract: briefs are per-task files produced by the skill's task-brief script, matching the thin-index-plus-briefs plan shape), one line of where the task fits, interfaces/decisions from earlier tasks the brief cannot know, the report-file path and contract — and explicitly NOT the whole plan or accumulated prior-task history. BASE is recorded before dispatch for the review package.
```

with

```text
(1) The controller runs `sdd-gate next` for the task and dispatches with a one-sentence prompt that names the rendered dispatch brief and says to follow it (contract: the prompt is the `brief_path` the helper prints; the helper fills the implementer template, and the task brief stays a per-task file the dispatch brief points at). The controller's own words reach the brief only through `--context-file`: where the task fits and interfaces/decisions from earlier tasks the brief cannot know — explicitly NOT the whole plan, template text typed into the prompt, or accumulated prior-task history. The helper records the task's base in the ledger for the review package.
```

and replace

```text
or pastes whole-plan text into dispatches is a failure.
```

with

```text
or pastes whole-plan or template text into dispatches is a failure.
```

Eval 3 (`cumulative-package-gate-stops-next-dispatch`), replace

```text
before any next dispatch, run the existing review-package producer over the cumulative DELIVERY_BASE..HEAD range, validate its producer report, then independently check the artifact and compare all four metrics. Record full base/head SHAs and metrics in the ledger.
```

with

```text
before any next dispatch, `sdd-gate next` runs the existing review-package producer over the cumulative DELIVERY_BASE..HEAD range, validates its producer report, then independently checks the artifact and compares all four metrics, and records the full base/head SHAs and metrics in the ledger.
```

and replace

```text
Task 2's scoped pass does not override cumulative exit 3:
```

with

```text
Task 2's scoped pass does not override the cumulative exit 3 (`outcome: refused`, `gate: decompose_required`):
```

Eval 4 (`planned-worktree-executes-and-stops-before-final-review`), replace

```text
) and dispatches one implementer for Task 1. The implementer commits the flag rename on the worktree branch, and its task review passes. The ledger then records `Task 1: complete`
```

with

```text
), runs `sdd-gate next` and dispatches one implementer for Task 1 with a prompt naming the rendered dispatch brief. The implementer commits the flag rename on the worktree branch, and its task review, dispatched the same way after `sdd-gate review`, passes. A final `sdd-gate next --completed 1` then records `Task 1: complete` in the ledger
```

The eval's `asserts` are unchanged: its ledger assert still greps `Task 1: complete`.

- [ ] **Step 5: Write the two evidence rows of the acceptance record**

Create `.agents/artifacts/plans/2026-10-10-issue-353-sdd-gate-rendered-briefs.acceptance.md` with exactly this content (D9: both criteria are post-merge evidence; nothing in this change measures them, and the controller adds rows AC3–AC5 and every verdict at the final review):

```markdown
# Acceptance record — issue #353

| AC | Criterion | Kind | Check or command | Observed | Commit | Conditions | Verdict |
|----|-----------|------|------------------|----------|--------|------------|---------|
| AC1 | [evidence] Owner turns per task in the task loop are ≤ 6 — measured: owner transcript of the next orchestrated nodocom issue with ≥ 4 tasks, counting requests between consecutive implementer dispatches; baseline 7.5–13.7. | evidence | Count the owner's requests between consecutive implementer dispatches in the owner transcript; threshold: ≤ 6 per task (baseline 7.5–13.7). | not measured — post-merge | — | the next orchestrated nodocom issue with at least 4 tasks, run with the merged `sdd-gate` installed on the orchestrating host | unverified |
| AC2 | [evidence] Median implementer and task-review dispatch prompt is ≤ 1,000 characters — measured: `prompt` length of the owner's Agent calls in that transcript; baseline 8.0k and 7.8k. | evidence | Median `prompt` length of the owner's implementer and task-review `Agent` calls in that transcript; threshold: ≤ 1,000 characters (baseline 8.0k and 7.8k). | not measured — post-merge | — | the same transcript as AC1 | unverified |
```

Before writing, read the issue's two lines with `gh issue view 353 --repo fagenorn/nix-config --json body` and correct the `Criterion` cells if the issue text differs from the above; they are the issue's lines verbatim, without the checkbox.

- [ ] **Step 6: Verify**

Run: `wc -c home/common/agent-skills/skills/sdd/SKILL.md home/common/agent-skills/skills/sdd/implementer-prompt.md home/common/agent-skills/skills/sdd/task-reviewer-prompt.md`
Expected: `22120`, `6837`, `7450`, total `36407`.

Run: `just agent-instruction-budget`
Expected: exactly `check: pass`, with no `ceiling:`, `tightness:`, `lint:` or `raise:` line (its `lint:` lines are `skill-lint`'s). If it prints a `ceiling:` line, follow the plan root's "Instruction budget" section: shorten only sentences these edits introduced, keep every pinned argv and heading, re-run; if it still fails, stop and report BLOCKED with the gate's lines. Never edit `instruction-load.json` or a gate file, and never ask for the raise label.

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py home/common/agent-skills/tests/test_shell_example_contracts.py home/common/agent-skills/tests/test_dispatch_contracts.py home/common/agent-skills/tests/test_eval_cases.py home/common/agent-skills/tests/test_skill_lint.py home/common/agent-skills/tests/test_instruction_load.py home/common/agent-skills/tests/test_agent_model_matrix.py` (timeout 900 s)
Expected: `OK` (skips allowed).

Run: `if grep -nE "scripts/task-brief|Record BASE" home/common/agent-skills/skills/sdd/SKILL.md; then exit 1; fi`
Expected: no output, exit 0 (the skill no longer tells the owner to run `task-brief` or record the base by hand).

Run: `if grep -n "sdd-gate[^\`]*<<" home/common/agent-skills/skills/sdd/SKILL.md; then exit 1; fi`
Expected: no output, exit 0 (no heredoc is fed to `sdd-gate`).

Run: `python3 -c "import json,sys; json.load(open('home/common/agent-skills/skills/sdd/evals/evals.json', encoding='utf-8'))"`
Expected: exit 0.

Run: `git diff --stat cd4b1746e5a844a17f806ccf791e6840e26d4cb2 -- home/common/agent-skills/skills home/common/agent-skills/instruction-load.json .github python/agent_tools/skill_lint.py python/agent_tools/instruction_load.py`
Expected: exactly four files, all under `home/common/agent-skills/skills/sdd/`: `SKILL.md`, `implementer-prompt.md`, `task-reviewer-prompt.md`, `evals/evals.json`.

- [ ] **Step 7: Commit**

```bash
git add home/common/agent-skills/skills/sdd/SKILL.md home/common/agent-skills/skills/sdd/task-reviewer-prompt.md home/common/agent-skills/skills/sdd/evals/evals.json home/common/agent-skills/tests/test_workflow_skill_contracts.py home/common/agent-skills/tests/test_shell_example_contracts.py .agents/artifacts/plans/2026-10-10-issue-353-sdd-gate-rendered-briefs.acceptance.md
git commit -m "feat(issue-353): the sdd skill dispatches by rendered brief through sdd-gate"
```
