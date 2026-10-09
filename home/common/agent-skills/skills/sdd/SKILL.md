---
name: sdd
description: Executes an implementation plan with a fresh subagent per task, reviewed between tasks. Use when a written plan of independent tasks is ready to build.
---

# Subagent-Driven Development

The owning phase passes its retained project here; do not perform another policy
read. For correctness review select `bindings.workflow.review.code` and route
retained `capabilities.review.code` first: `blocked` stops and authored
`unsupported` takes only its documented route. Only `available` dereferences
`bindings.commands[review_id].argv` before launching it.

Execute a plan with a fresh implementer per task, a lane-scoped task review after each, and one two-axis whole-branch review (conformance ∥ correctness) at the end.

**Continuous execution:** don't pause between tasks. Stop only for BLOCKED you cannot resolve, ambiguity that genuinely prevents progress, all-tasks-complete, or the deadline headroom rule. Narrate at most one short line between tool calls.

## Setup

Work in an isolated workspace: invoke the `worktrees` skill to create or verify one. Never implement on a main/master branch without explicit consent.

Before initial plan validation or brief extraction, run `artifact-budget check
--kind implementation-plan --root PLAN_FILE --format json`. Exit 2 or 3 stops. On
exit 0, require `status: within_budget` and the four non-boolean integer metrics
`root_bytes`, `total_bytes`, `file_count`, and `largest_member_bytes`; any other
shape stops as a contract error. Retain the root path and all four for dispatches.

Track progress in a ledger file:

- `scripts/sdd-workspace PLAN_FILE` prints the plan's git-ignored workspace — `<primary-checkout>/.superpowers/sdd/<checkout-bucket>/<plan-basename>/`, where `<checkout-bucket>` is `primary` or `wt-<worktree-name>` for a linked worktree. Ledger, briefs, reports and review packages for THIS plan live there; another plan's directory or checkout's bucket is never yours.
- Check `<workspace>/progress.md`. If its first line names your plan file, tasks with a `Task <N>: complete` line are DONE — resume at the first task without one; a task whose last line is a fix round resumes mid-loop. A ledger naming a different plan is not yours: leave it, start fresh.
- Create the ledger with its identity as the first line: `# SDD ledger — plan: <plan file path>`.
- After compaction, or if the workspace is gone, trust the ledger and `git log` over recollection.

**Initial validation is the only whole-package read.** After the checker passes,
read the root and every indexed member once, in discovery order, and scan for
conflicts — tasks that contradict each other or the constraints, or anything the
package mandates that the review rubric treats as a defect. Present findings as
one batched question, each beside the plan text mandating it and asking which
governs, before execution begins; a clean scan proceeds without comment. A
missing or unreadable member is a contract error. Afterwards hold only the plan root **header** (summary, Global
Constraints, Test seams, Delivery estimate and boundaries, and the `## Task index`
with ID, title, files touched, risk lane and member link per task), its checker
metrics, and the current task's brief from `scripts/task-brief`. Build the todo
list from the Task index.

### Cumulative delivery gate

Resolve the integration branch from the project bindings, then pin
`DELIVERY_BASE` once to the full SHA printed by `git merge-base HEAD
origin/<integration-branch>`. Never derive it from an independently advanced
local integration branch. Before the first implementer, and after each completed
task before any next dispatch, pin `DELIVERY_HEAD` to the full `git rev-parse
HEAD` SHA and run `review-package PLAN_FILE DELIVERY_BASE DELIVERY_HEAD`, then
apply the review-package gate.

A validated existing package satisfies a gate only when its manifest's full
`range.base` and `range.head` equal the intended full SHAs, its retained producer
report still validates, and a fresh independent artifact check agrees with all
four metrics. Seven-character path prefixes never establish range identity.
Record both full SHAs and the four checked metrics in the ledger. A non-passing
gate cannot advance: preserve completed work and identify an independently
deliverable split for the caller instead of dispatching more work.

### Review-package gate

Every `review-package` range, whether task, cumulative, fix-round or
final-review, passes this gate before any reviewer dispatch:

1. Record the full base and head SHAs before invoking the producer.
2. Run `review-package PLAN_FILE <base> <head>`, capture its stdout unchanged and
   pipe those bytes through `artifact-budget validate-report --boundary producer --input -`.
3. Independently run `artifact-budget check --kind review-package` on the
   report's root and compare all four metrics (`root_bytes`, `total_bytes`,
   `file_count`, `largest_member_bytes`) with the report's.

Then take one of three exits:

- Generator exit 0, validator exit 0, a strict `complete` report and agreement
  permit dispatch.
- Generator exit 3 must validate as `decompose_required`: record and return it,
  with no reviewer dispatched.
- Generator or validator exit 2, malformed or unknown output, or any
  report/checker disagreement (including `complete` with `over_budget`) is
  `failed`: record and return it before dispatch through the failed SDD
  candidate (`detail_state: "none"`, `report_path: null`), validated by
  `artifact-budget validate-report --boundary sdd`, returning only canonical stdout.

## Agent tiers

Dispatch by agent type, with the model and effort its dispatch site declares; never leave the tier to inheritance:

- **`mechanic`** — transcription plus testing (the plan text has the complete code, or the change is single-file mechanical), inventories and bulk sweeps.
- **`implementer`** — every other implementation task. A planned task and its fix rounds 1–3 run on Sonnet/high (the `task-implementer` role); fix rounds 4–5, a reasoning-problem BLOCKED and the final-review fixer run on Opus/high (the `implementer` role).
- **`reviewer`** — full-lane first-pass task review and every first-pass whole-branch review.
- **`reviewer-lite`** — only a scoped re-review (named prior findings + bounded fix diff) or a mechanical/low-risk lane verification (declared lane + bounded task diff). Ambiguity or branch-wide review escalates to `reviewer` on Opus/high, recorded in the ledger.
- The **final review's two axes** dispatch per [final-review.md](final-review.md): conformance as `reviewer` on Opus/high; correctness via `codex-collaboration`'s `diff-review` when `capabilities.review.code` is `available` and that skill is installed, else as `reviewer` on Opus/high (`blocked` stops).

Unsure between mechanic and implementer → pick implementer.

**Re-evaluating Sonnet task implementers.** Metric: first-pass approval of full-lane task reviews of `task-implementer` tasks (spec ✅, no Critical or Important finding, no fix round). Baseline: 84% over 153 reviews on Opus/high. Judge after about 10 delivered issues and at least 30 reviews; below 74% reverts the `sdd-nonmechanical-implementation` and `sdd-task-fix-redispatch` sites to the `implementer` role, otherwise keep Sonnet.

**Leaf-agent clauses.** Every prompt this skill composes for an `Agent` dispatch — here, in [fix-loop.md](fix-loop.md) or in [final-review.md](final-review.md) — carries these four clauses verbatim, as a paragraph of their own; a prompt built from one of the `*-prompt.md` templates already carries them:

> Launch any subagent by type only, never by name: a subagent cannot spawn a named teammate, and a named launch returns an error instead of work. Read an existing file before writing to it: overwriting content you have not read destroys work you cannot see. Run each long command, every verification command included, in the foreground with an explicit timeout above its expected duration. If the host moves one to the background anyway, wait for it in the same turn: never end your turn while a command or agent you started still runs. Never write an `until` or `while` loop around `sleep` to wait for something: if a wait is truly needed, run one bounded foreground `sleep N`, then check once.

## The task loop

Hand artifacts over as file paths; subagents write detail to files.

### Lifecycle workers

When the caller runs this skill under a lifecycle identity — its
`ledger_repo_root`, `run_id` and `action_id` — every agent this skill
dispatches or resumes that can write (the implementer, the mechanic and each
fix-round implementer) is a registered worker of that launch. Immediately
before the dispatch or resume, run
`workflow-state register-worker --repo-root <ledger_repo_root> --run-id <run-id> --action-id <action_id>`
and put its printed `worker_id` into the prompt as the single line
`Lifecycle worker: --repo-root <ledger_repo_root> --run-id <run-id> --worker-id <worker_id>`,
followed by the sentences "Run each long command, every verification command included, as
`launch-scope exec --repo-root <ledger_repo_root> --run-id <run-id> --worker-id <worker_id> -- <argv>`,
still in the foreground." and "Create every scratch directory or scratch worktree under the path that
`launch-scope scratch --repo-root <ledger_repo_root> --run-id <run-id> --worker-id <worker_id>` prints."
When that agent returns, run
`workflow-state release-worker --repo-root <ledger_repo_root> --run-id <run-id> --worker-id <worker_id> --event returned`.
A resumed agent is registered again and gets a fresh `worker_id`.
Read-only reviewers are not registered.

A report of `BLOCKED` with `launch fence refused: <reason>` means that
worker's launch fence refused its commit. Release that worker, retry and
re-dispatch nothing, then run
`workflow-state check-launch --repo-root <ledger_repo_root> --run-id <run-id> --action-id <action_id>`
on this launch:

- `current: false` or any helper failure: follow from-issue's superseded route.
  After that release nothing more is written; print `/from-issue <num> --auto`
  on its own line and stop.
- `current: true`: the refusal was no supersession; follow from-issue's
  suspension procedure with `blocked_on=transport`.

Without a lifecycle identity none of this applies and workers commit with plain `git`.

Under a lifecycle identity, run
`workflow-state mark-progress --repo-root <ledger_repo_root> --run-id <run-id> --action-id <action_id>`
before dispatching the first task this session executes and after each task's `complete` line (step 5).
A refusal changes nothing and never stops the task loop.

With the attempt's `deadline_at` also handed over, check headroom at each
task boundary: before dispatching a task, and after the last `complete` line,
before the final review. `remaining` is `deadline_at` minus `date -u`;
`longest` is the largest dispatch-to-`complete` wall time of a task completed
this session (0 before the first). When `remaining` is under the larger of
15 minutes and `longest`, stop any still-live worker and run
`workflow-state release-worker --repo-root <ledger_repo_root> --run-id <run-id> --worker-id <worker_id> --event stopped`,
then
`workflow-state mark-progress --repo-root <ledger_repo_root> --run-id <run-id> --action-id <action_id>`
(a refusal does not stop you), then
`workflow-state check-launch --repo-root <ledger_repo_root> --run-id <run-id> --action-id <action_id>`.
On `current: false` or any helper failure, write nothing more, print
`/from-issue <num> --auto` on its own line and stop. On `current: true`,
follow from-issue's suspension procedure with `blocked_on=deadline`; a suspend
refused because the attempt is no longer active means the reaper expired it:
follow from-issue's expired-deadline route, with no retry.

### 1. Dispatch the implementer

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

Template: [implementer-prompt.md](implementer-prompt.md)

### 2. Handle the report

- **DONE** → run `review-package PLAN_FILE BASE HEAD` (BASE from step 1 — never `HEAD~1`) and apply the review-package gate before step 3.
- **DONE_WITH_CONCERNS** → correctness/scope concerns get addressed before review; observations get noted, review proceeds.
- **NEEDS_CONTEXT** → provide it, re-dispatch.
- **BLOCKED** → a `launch fence refused` report follows `### Lifecycle workers` and is never re-dispatched. Otherwise: context problem: add context, re-dispatch at the same tier. Reasoning problem: escalate to a fresh Opus/high implementer carrying the brief path, the report path and the blocker:

<!-- agent-dispatch: id=sdd-blocked-reasoning-escalation role=implementer model=opus effort=high -->
Agent(subagent_type="implementer", model="opus", effort="high") takes over a task whose implementer reported BLOCKED on a reasoning problem.

  Too large: split it. Plan wrong: escalate to the human. Never force an unchanged retry.

**Interim child results.** A child's return that the host marks interim — it stopped with background work of its own still running, or its result may be interim — is not a completion: the child is still running. Re-engage that same child by its recorded agent identity: message it to wait for its own job inside its turn and then return its final report, and wait for that report within your turn. Never answer an interim result with a text-only reply, never suspend for it (it is not an `external` wait), and never dispatch a replacement or stop the child. A registered lifecycle worker stays registered under its existing worker id: an interim result is not its `returned` event, and re-engagement is not a resume, so it registers nothing new. If the message cannot be delivered or its reply cannot be awaited in your turn, the child is one you cannot wait for: follow from-issue's **Writing workers** route (task-stop, then release `--event stopped`), then this skill's ordinary handling of a lost child; that is the one case that may lead to a fresh dispatch. Only the child's final hand-back counts as its result.

If the implementer asks questions — before or during — answer completely.

### 3. Review the task

Per-task review is never skipped, and a report missing either verdict (spec compliance AND quality) is not accepted; implementer self-review never substitutes. Its **form** follows the task's risk lane from the plan's task index:

- **full lane** — the full first-pass reviewer below, always.
- **mechanical / low-risk lane** — scoped verification: dispatch reviewer-lite with the declared lane and the bounded task diff. For a mechanical microtask whose verify commands are deterministic, the controller may instead verify inline (run the commands, inspect the diff) and ledger `Task <N>: verified inline (mechanical)`.
- **Batching** — adjacent same-lane microtasks in the same file neighborhood may share one verification context when isolation adds nothing; ledger the batch.
- A lane verification that surfaces ambiguity, semantic doubt, or anything beyond its lane escalates to the full reviewer; never adjudicate inside the cheap gate or route a lane the plan didn't declare.

<!-- agent-dispatch: id=sdd-lane-task-verification role=reviewer-lite model=sonnet effort=medium -->
Agent(subagent_type="reviewer-lite", model="sonnet", effort="medium") verifies the bounded mechanical/low-risk lane task diff against its brief.

For the full-lane review:

- The reviewer gets the plan root path and all four metrics, then the brief and
  report paths plus the review-package manifest root path and all four metrics.
  It never gets a member list, shard list, artifact contents, diff contents, or
  another task body.
- No open-ended directives ("check all uses") without a concrete task-specific reason, no asking it to re-run tests the implementer ran, and never pre-judge: a prompt containing "do not flag" or "at most Minor" is wrong; adjudication happens in the loop.
- **⚠️ Cannot-verify items** (requirements in unchanged code or spanning tasks) don't block the review, but you resolve each yourself before marking the task complete. A confirmed gap enters the fix loop as a failed spec review.

Template: [task-reviewer-prompt.md](task-reviewer-prompt.md)

### 4. The fix loop

Triggers on spec ❌, any Critical/Important finding, or a confirmed ⚠️ gap — read [fix-loop.md](fix-loop.md) beside this file and follow it: five capped rounds, scoped re-reviews, and the at-the-cap breaker that parks or blocks every residual with a ledger ruling.

Two routes exit before the loop starts:

- **Minor findings** go to the ledger as they arrive (`Task <N>: minor (deferred): <one-liner>`); the final review triages them. They never enter the loop.
- **Plan-mandated findings** — anything conflicting with the plan's own text — are the human's call: present finding and plan text, ask which governs.

Never fix findings yourself in the controller session.

### 5. Complete the task

Clean review — or everything parked-with-ruling at the cap — appends `Task <N>: complete (commits <base7>..<head7>, review clean | <K> parked)`; mark the todo, run the cumulative delivery gate, then move on only when it passes. Never advance past open Critical/Important findings that are neither fixed nor parked.

## Final review — two axes

Mandatory for **every** risk lane — lanes narrow per-task review, never this gate. When all tasks are complete, read [final-review.md](final-review.md) beside this file and follow it, through its **Final verification** step.

## Finish

Before any workspace can disappear, collect every parked or residual finding as
the strict non-empty detail input and write the retained candidate to
`<workspace>/retained-detail.json`. Invoke review-package in `delivery-detail`
mode with issue/branch/run/head identity; the producer alone derives the
destination beneath the primary checkout's `.superpowers/issue-delivery/` home.
Independently run `artifact-budget check --kind
review-package` on the published root and compare its metrics with the producer
report.

Build one exact SDD JSON object with only `state`, `review_state`,
`conformance_verdict`, `correctness_verdict`, `verification_state`, `base_sha`,
`head_sha`, `acceptance_state`, `detail_state`, `report_path`, and `notes`,
then run `artifact-budget validate-report --boundary sdd` and transport only
canonical stdout.

- `base_sha` and `head_sha` are the `DELIVERY_BASE` and `DELIVERY_HEAD` the final
  review's first pass covered, never the branch tip; ship-issue reviews the fix
  wave's later commits as its delta.
- `verification_state` is `passed` only when final-review.md's **Final
  verification** step recorded a pass on the branch tip it ran on or took its
  none-declared route with the per-task focused tests passing; `failed` when that
  step's repair round did not pass.
- `acceptance_state` derives from the final verdicts: `not_applicable` when there
  was no criterion source or the run failed before the conformance axis graded;
  otherwise `unmet` when any verdict is `unmet` or `unverified`; otherwise
  `human_pending` when any is `human_pending`; otherwise `met`.
- A non-empty detail set is `present` with one main-root-relative durable path.
  With genuinely no findings it is `none` with a null path. Transient review
  evidence is never inlined.

If publication fails, run `artifact-budget validate-detail-input` against the
no-follow retained file and consume canonical stdout, requiring non-empty findings
and comparison with the candidate before setting `detail_state: "unpublished"`.
That `report_path` is the `<workspace>/retained-detail.json` written above,
**main-root-relative** like the durable path; name the root in notes. Validate the
failed candidate through `artifact-budget validate-report --boundary sdd`, keep
the workspace and the worktree, and remove neither. Missing, unreadable, empty,
malformed, wrong-schema, or empty-findings input remains failed without an
unpublished claim.

Terminal states:

- **Clean** — both axes clean (or clean after the fix wave), or every remaining
  finding parked-with-ruling (an acceptance finding never is), and the **Final
  verification** step recorded a pass on the branch tip or took its
  none-declared route: delete this plan's workspace (`rm -rf <workspace>`;
  sibling directories belong to other plans) and report `review_state: clean`.
- **Residuals** — the breaker surfaced a load-bearing residual the caller must
  decide on: keep the workspace and ledger and report `review_state: residuals`;
  the retained or durable review package named by the single `report_path` is the
  only findings transport.

Report to the calling workflow only the validated SDD JSON above. `review_state`
is `clean | residuals`; sdd never reports `unknown`. Do not ship, merge, or open
PRs — the caller owns delivery.
