---
name: sdd
description: Executes an implementation plan with a fresh subagent per task, reviewed between tasks. Use when a written plan of independent tasks is ready to build.
---

# Subagent-Driven Development

The owning phase passes its retained project here; read no policy again. For
correctness review select `bindings.workflow.review.code` and route retained
`capabilities.review.code` first: `blocked` stops and authored `unsupported`
takes only its documented route. Only `available` dereferences
`bindings.commands[review_id].argv` before launching it.

Execute a plan with a fresh implementer per task, a lane-scoped review after each, and a final two-axis branch review (conformance ∥ correctness).

**Continuous execution:** don't pause between tasks. Stop only for BLOCKED you cannot resolve, ambiguity that prevents progress, all tasks complete, a decomposition stop, or the deadline headroom rule. Narrate at most one short line between tool calls.

## Setup

Work in an isolated workspace: invoke the `worktrees` skill to create or verify one. Never implement on main/master without consent.

Before initial plan validation or brief extraction, run `artifact-budget check
--kind implementation-plan --root PLAN_FILE --format json`. Exit 2 or 3 stops. On
exit 0 require `status: within_budget` and the four non-boolean integer metrics
`root_bytes`, `total_bytes`, `file_count`, and `largest_member_bytes`; any other
shape is a contract error that stops. Retain the root path and all four.

Track progress in a ledger:

- `scripts/sdd-workspace PLAN_FILE` prints the plan's git-ignored workspace — `<primary-checkout>/.superpowers/sdd/<checkout-bucket>/<plan-basename>/`, where `<checkout-bucket>` is `primary` or `wt-<worktree-name>` for a linked worktree. Ledger, briefs, reports and review packages for THIS plan live there; no other plan's directory or checkout's bucket is yours.
- Check `<workspace>/progress.md`. If its first line names your plan file, tasks with a `Task <N>: complete` line are DONE — resume at the first without one; a task whose last line is a fix round resumes mid-loop. A ledger naming another plan is not yours: leave it, start fresh.
- Create the ledger with its identity first: `# SDD ledger — plan: <plan file path>`.
- After compaction, or if the workspace is gone, trust the ledger and `git log` over memory.

**Initial validation, the only whole-package read, runs only on an unreviewed first
entry** (no literal `--reviewed` token, no ledger line `Initial validation: done` for
this plan): read the root and every indexed member once, in discovery order, scanning
for conflicts — tasks that contradict each other or the constraints, or anything the
package mandates that the review rubric treats as a defect. Present findings before
execution as one batched question, each beside the plan text mandating it, asking
which governs; a clean or answered scan writes that line. A missing or
unreadable member is a contract error. Afterwards hold only the root header to its
`## Task index`, its checker metrics and the current task's `sdd-gate` output,
reading only `<plan stem>.tasks/task-<N>.md` before each dispatch. Build the todo
list from the Task index.

### Cumulative delivery gate

Pin `DELIVERY_BASE` once to the full SHA printed by `git merge-base HEAD origin/<integration-branch>` (integration branch from the project bindings), never an advanced local branch. `sdd-gate next` gates every dispatch on the cumulative package, then the projection of the remaining tasks (steps and ledger lines: nix-config's `python/README.md` § `sdd-gate`). A refusal cannot advance: preserve completed work and name an independently deliverable split.

### Review-package gate

`sdd-gate review` and `next` run this for task and cumulative ranges; fix-round and final-review ranges pass it by hand before any reviewer dispatch: record the full base and head SHAs, run `review-package PLAN_FILE <base> <head>`, pipe its stdout unchanged through `artifact-budget validate-report --boundary producer --input -`, and run `artifact-budget check --kind review-package` on the report's root, agreeing on all four metrics. A reused package must carry the same full `range.base` and `range.head`. Take one of three exits:

- Generator exit 0, validator exit 0, a strict `complete` report and agreement permit dispatch.
- Generator exit 3 must validate as `decompose_required`: record it, dispatch no reviewer, and report it as `actual_overage` per **Finish**.
- Generator or validator exit 2, malformed or unknown output, or any report/checker disagreement (including `complete` with `over_budget`) is `failed`: record and return it before dispatch as the failed SDD candidate (`detail_state: "none"`, `report_path: null`), validated by `artifact-budget validate-report --boundary sdd`, returning only canonical stdout.

## Agent tiers

Dispatch by agent type, with the model and effort its dispatch site declares:

- **`mechanic`** — transcription plus testing (complete code in the plan, or a single-file mechanical change), inventories and bulk sweeps.
- **`implementer`** — every other implementation task. A planned task and fix rounds 1–3 run on Sonnet/high (the `task-implementer` role); fix rounds 4–5, a reasoning-problem BLOCKED and the final-review fixer on Opus/high (the `implementer` role).
- **`reviewer`** — full-lane first-pass task review and every first-pass branch review.
- **`reviewer-lite`** — only a scoped re-review (named prior findings + bounded fix diff) or a mechanical/low-risk lane verification (declared lane + bounded task diff). Ambiguity or branch-wide review escalates to `reviewer` on Opus/high, ledgered.
- The **final review's two axes** dispatch per [final-review.md](final-review.md): conformance as `reviewer` on Opus/high; correctness via `codex-collaboration`'s `diff-review` when `capabilities.review.code` is `available` and that skill is installed, else `reviewer` on Opus/high (`blocked` stops).

Unsure: implementer.

**Re-evaluating Sonnet task implementers.** Metric: first-pass approval of full-lane `task-implementer` reviews (spec ✅, no Critical/Important finding, no fix round); baseline 84% over 153 Opus/high reviews. At about 10 delivered issues and 30 reviews, below 74% reverts the `sdd-nonmechanical-implementation` and `sdd-task-fix-redispatch` sites to `implementer`.

**Leaf-agent clauses.** Every prompt this skill composes for an `Agent` dispatch — here, in [fix-loop.md](fix-loop.md) or in [final-review.md](final-review.md) — carries these four clauses verbatim, as a paragraph of their own; a `*-prompt.md` template already carries them:

> Launch any subagent by type only, never by name: a subagent cannot spawn a named teammate, and a named launch returns an error instead of work. Read an existing file before writing to it: overwriting content you have not read destroys work you cannot see. Run each long command, every verification command included, in the foreground with an explicit timeout above its expected duration. If the host moves one to the background anyway, wait for it in the same turn: never end your turn while a command or agent you started still runs. Never loop `sleep` in the foreground or chain a check onto it: use Monitor with an until-condition, or one short bare `sleep N` call and check in the next.

## The task loop

### Lifecycle workers

Under a lifecycle identity — the caller's `ledger_repo_root`, `run_id` and
`action_id` — every agent this skill dispatches or resumes that can write (the
implementer, the mechanic and each fix-round implementer) is a registered worker
of that launch. Immediately before the dispatch or resume, run
`workflow-state register-worker --repo-root <ledger_repo_root> --run-id <run-id> --action-id <action_id>`
and put its printed `worker_id` into the prompt as the line
`Lifecycle worker: --repo-root <ledger_repo_root> --run-id <run-id> --worker-id <worker_id>`,
followed by the sentences "Run each long command, every verification command included, as
`launch-scope exec --repo-root <ledger_repo_root> --run-id <run-id> --worker-id <worker_id> -- <argv>`,
still in the foreground." and "Create every scratch directory or scratch worktree under the path that
`launch-scope scratch --repo-root <ledger_repo_root> --run-id <run-id> --worker-id <worker_id>` prints."
When that agent returns, run
`workflow-state release-worker --repo-root <ledger_repo_root> --run-id <run-id> --worker-id <worker_id> --event returned`.
A resumed agent is registered again with a fresh `worker_id`. Read-only
reviewers are not registered. `sdd-gate` makes the register, release and
progress calls for the two dispatches it renders.

A `BLOCKED` report with `launch fence refused: <reason>` means that worker's
launch fence refused its commit. Release that worker, retry and re-dispatch
nothing, and run
`workflow-state check-launch --repo-root <ledger_repo_root> --run-id <run-id> --action-id <action_id>`
on this launch:

- `current: false` or any helper failure: follow from-issue's superseded route,
  then write nothing more; print `/from-issue <num> --auto` on its own line and stop.
- `current: true`: no supersession; follow from-issue's suspension procedure
  with `blocked_on=transport`.

Without one, none of this applies and workers commit with plain `git`.

With the attempt's `deadline_at` also handed over, check headroom at each
task boundary: before dispatching a task, and after the last `complete` line,
before the final review. `remaining` is `deadline_at` minus `date -u`;
`longest` is the largest dispatch-to-`complete` wall time of a task completed
this session (0 before the first). When `remaining` is under the larger of
15 minutes and `longest`, stop any live worker and run
`workflow-state release-worker --repo-root <ledger_repo_root> --run-id <run-id> --worker-id <worker_id> --event stopped`,
then
`workflow-state mark-progress --repo-root <ledger_repo_root> --run-id <run-id> --action-id <action_id>`
(a refusal does not stop you), then
`workflow-state check-launch --repo-root <ledger_repo_root> --run-id <run-id> --action-id <action_id>`.
On `current: false` or any helper failure, write nothing more, print
`/from-issue <num> --auto` on its own line and stop. On `current: true`,
follow from-issue's suspension procedure with `blocked_on=deadline`; a suspend
refused because the attempt is no longer active means the reaper expired it:
follow from-issue's expired-deadline route, no retry.

### 1. Dispatch the implementer

Run `sdd-gate next PLAN_FILE --skill-dir <skill-dir> --task N`
(`<skill-dir>`: this file's directory), adding:

- `--completed <previous-task>` after that task's review, with `--parked <K>`
  for parked findings (step 5);
- `--delivery-base <DELIVERY_BASE>` on the run's first call;
- one `--standards <path>` per retained `bindings.paths.standards` entry;
- `--context-file <file>`, written with the file-writing tool: where the task
  fits, earlier interfaces and decisions the brief cannot know, your resolution
  of any ambiguity, a pointer to the ledger entry of a finding parked here. Never
  member lists, task contents or prior-task history;
- `--repo-root <ledger_repo_root> --run-id <run-id> --action-id <action_id>`
  under a lifecycle identity.

It prints one JSON object. On `outcome: ready` the whole prompt is
`Read the dispatch brief at <brief_path> and follow it exactly.`

On `outcome: refused` dispatch nothing and route by `step` and `gate`:

- step `projection`, `gate: decompose_required` → `review-feasibility confirm --plan PLAN_FILE --base DELIVERY_BASE --input -` over the refusal's `report` must exit 3 → SDD `decompose_required`, `stop: {"kind":"projected_overflow","projection":<confirm stdout>}`;
- step `validate-report`, `gate: decompose_required` → `artifact-budget check --kind review-package --root <report artifact path>` must agree with the report on all four metrics and the violations → SDD `decompose_required`, `stop: {"kind":"actual_overage","artifact":<report artifact>}`;
- `gate: failed`, a confirm exit other than 3 or any disagreement → SDD `failed`;
- step `release-worker` or `register-worker` is a lifecycle failure under `### Lifecycle workers`; any other `step` is a contract error: stop.

A stop dispatches nothing more and keeps the workspace, ledger and worktree. A plan without forecast blocks fails at the first projection.

- Record the implementer's agent identity and `worker_id`; fix rounds 1–3 resume it.
- Never dispatch implementers in parallel.

Template: [implementer-prompt.md](implementer-prompt.md)

### 2. Handle the report

- **DONE** → run `sdd-gate review PLAN_FILE --skill-dir <skill-dir> --task N` with step 1's `--standards` and lifecycle flags plus `--worker-id <worker_id>`. A refusal routes as in step 1.
- **DONE_WITH_CONCERNS** → address correctness/scope concerns before review; note observations and review.
- **NEEDS_CONTEXT** → release the worker, then repeat step 1's call with the context added.
- **BLOCKED** → a `launch fence refused` report follows `### Lifecycle workers` and is never re-dispatched. Otherwise a context problem re-dispatches as for NEEDS_CONTEXT, at the same tier; a reasoning problem does the same to a fresh Opus/high implementer, with the blocker and report path in the context:

<!-- agent-dispatch: id=sdd-blocked-reasoning-escalation role=implementer model=opus effort=high -->
Agent(subagent_type="implementer", model="opus", effort="high") takes over a task whose implementer reported BLOCKED on a reasoning problem.

  Too large: split it. Plan wrong: escalate to the human. Never retry unchanged.

**Interim child results.** A child's return that the host marks interim (its own background work still running, or a result that may be interim) is not a completion. Re-engage that same child by its recorded agent identity: tell it to wait for its job inside its turn and then return its final report, and wait for that report within your turn. Never answer an interim result with a text-only reply, never suspend for it (it is not an `external` wait), and never dispatch a replacement or stop the child. A registered lifecycle worker stays registered under its existing worker id and registers nothing new: an interim result is not its `returned` event. If the message cannot be delivered or its reply cannot be awaited in your turn, follow from-issue's **Writing workers** route (task-stop, then release `--event stopped`), then this skill's handling of a lost child, the one case that may lead to a fresh dispatch. Only the child's final hand-back counts as its result.

Answer implementer questions completely.

### 3. Review the task

Per-task review is never skipped; a report missing either verdict (spec compliance AND quality) is refused, and self-review never substitutes. Its **form** follows the risk lane in the plan's task index:

- **full lane** — the full first-pass reviewer below.
- **mechanical / low-risk lane** — scoped verification: dispatch reviewer-lite with the declared lane and the `manifest_root` and `metrics` `sdd-gate review` printed. A mechanical microtask with deterministic verify commands may instead be verified inline and ledgered `Task <N>: verified inline (mechanical)`.
- **Batching** — adjacent same-lane microtasks in one file neighborhood may share a verification context; ledger the batch.
- A lane verification that surfaces ambiguity, semantic doubt, or anything beyond its lane escalates to the full reviewer; never adjudicate in the cheap gate or route an undeclared lane.

<!-- agent-dispatch: id=sdd-lane-task-verification role=reviewer-lite model=sonnet effort=medium -->
Agent(subagent_type="reviewer-lite", model="sonnet", effort="medium") verifies the bounded mechanical/low-risk lane task diff against its brief.

For the full-lane review:

- The whole prompt is step 1's sentence with `sdd-gate review`'s `brief_path`.
- **⚠️ Cannot-verify items** (requirements in unchanged code or spanning tasks) don't block the review, but you resolve each before marking the task complete. A confirmed gap enters the fix loop as a failed spec review.

Template: [task-reviewer-prompt.md](task-reviewer-prompt.md)

### 4. The fix loop

Triggers on spec ❌, any Critical/Important finding, or a confirmed ⚠️ gap — read [fix-loop.md](fix-loop.md) and follow it: five capped rounds, scoped re-reviews, and the at-the-cap breaker that parks or blocks every residual with a ledger ruling.

Two routes exit before the loop starts:

- **Minor findings** go to the ledger as they arrive (`Task <N>: minor (deferred): <one-liner>`) for the final review to triage; they never enter the loop.
- **Plan-mandated findings** — conflicting with the plan's own text — are the human's call: present finding and plan text, ask which governs.

Never fix findings yourself in the controller session.

### 5. Complete the task

Clean review — or everything parked-with-ruling at the cap — runs `sdd-gate record PLAN_FILE --task N`, which writes task N's ownership evidence into the plan's forecast blocks (they change only through `record` after SDD entry). Commit exactly its `paths` as one process-only commit with subject `plan: record task <N> evidence`: under a lifecycle identity register yourself and commit through `launch-commit` as final-review.md's acceptance record does, else plain `git commit`. Then run `sdd-gate next --completed N` (step 1's call, with `--task N+1` when one remains, without it after the last task or before a headroom stop): it ledgers the task `complete` and runs the cumulative delivery gate. Move on only on `outcome: ready`; a refusal routes as in step 1. Never advance past open Critical/Important findings neither fixed nor parked.

## Final review — two axes

Mandatory for **every** risk lane; lanes narrow per-task review, never this gate. When all tasks are complete, read [final-review.md](final-review.md) and follow it, through its **Final verification** step.

## Finish

Before any workspace can disappear (a `decompose_required` stop skips this), collect every parked or residual finding as
the strict non-empty detail input and write the retained candidate to
`<workspace>/retained-detail.json`. Invoke review-package in `delivery-detail`
mode with issue/branch/run/head identity; the producer alone derives the
destination under the primary checkout's `.superpowers/issue-delivery/`.
Independently run `artifact-budget check --kind review-package` on the published
root and compare its metrics with the producer report.

Build one exact SDD JSON object with only `state`, `review_state`,
`conformance_verdict`, `correctness_verdict`, `verification_state`, `base_sha`,
`head_sha`, `acceptance_state`, `detail_state`, `report_path`, and `notes`
(plus `stop` for `decompose_required` only), then run
`artifact-budget validate-report --boundary sdd` and transport only canonical stdout.

- `base_sha` and `head_sha` are the `DELIVERY_BASE` and `DELIVERY_HEAD` the final
  review's first pass covered, never the branch tip; ship-issue reviews the fix
  wave's later commits as its delta.
- `verification_state` is `passed` only when final-review.md's **Final
  verification** step recorded a pass on the branch tip it ran on or took its
  none-declared route with the per-task focused tests passing; `failed` when its repair round did not pass.
- `acceptance_state` derives from the final verdicts: `not_applicable` when there
  was no criterion source or the run failed before the conformance axis graded;
  otherwise `unmet` when any verdict is `unmet` or `unverified`; otherwise
  `human_pending` when any is `human_pending`; otherwise `met`.
- `decompose_required` (a stop, no final review): `review_state: unknown`, both verdicts and `verification_state` `not_run`, `acceptance_state: not_applicable`, `detail_state: none`, `report_path: null`, and `base_sha`/`head_sha` the refused gate's range (the summary's for a projected overflow; `DELIVERY_BASE` and the gate head for an actual overage). Keep the workspace and worktree.
- A non-empty detail set is `present` with one main-root-relative durable path;
  with no findings it is `none` with a null path. Never inline transient review
  evidence.

If publication fails, run `artifact-budget validate-detail-input` against the
no-follow retained file and consume canonical stdout, requiring non-empty findings
and comparison with the candidate before setting `detail_state: "unpublished"`.
That `report_path` is the `<workspace>/retained-detail.json` written above,
**main-root-relative** like the durable path; name the root in notes. Validate the
failed candidate through `artifact-budget validate-report --boundary sdd` and keep
the workspace and worktree. Missing, unreadable, empty, malformed, wrong-schema, or
empty-findings input remains failed without an unpublished claim.

Terminal states:

- **Clean** — both axes clean (or clean after the fix wave), or every remaining
  finding parked-with-ruling (an acceptance finding never is), and the **Final
  verification** step recorded a pass on the branch tip or took its
  none-declared route: delete this plan's workspace (`rm -rf <workspace>`;
  sibling directories belong to other plans) and report `review_state: clean`.
- **Residuals** — the breaker surfaced a load-bearing residual the caller must
  decide on: keep the workspace and ledger and report `review_state: residuals`;
  the review package named by the single `report_path` is the only findings
  transport.

Report only the validated SDD JSON above to the calling workflow; `review_state`
is `clean | residuals` (`unknown` only for a stop or `failed`). Do not ship, merge or open PRs: the caller owns delivery.
