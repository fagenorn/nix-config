---
name: sdd
description: Execute an implementation plan with a fresh subagent per task, reviewed between tasks. Use when a written plan with independent tasks is ready to build.
---

# Subagent-Driven Development

The owning phase passes its retained project here; do not perform another policy
read. For correctness review select `bindings.workflow.review.code` and route
retained `capabilities.review.code` first: `blocked` stops and authored
`unsupported` takes only its documented route. Only `available` dereferences
`bindings.commands[review_id].argv` before launching it.

Execute a plan by dispatching a fresh implementer per task, a lane-scoped task review after each, and one two-axis whole-branch review (conformance ∥ correctness) at the end. Subagents never inherit your session's history — you construct exactly what each needs, which also keeps your own context flat for coordination.

**Continuous execution:** don't pause between tasks. Stop only for BLOCKED you cannot resolve, ambiguity that genuinely prevents progress, all-tasks-complete, or the deadline headroom rule. Narrate at most one short line between tool calls — the ledger and tool results carry the record.

## Setup

Work happens in an isolated workspace: invoke the `worktrees` skill to create or verify one. Never implement on a main/master branch without explicit consent.

Before initial plan validation or brief extraction, run `artifact-budget check
--kind implementation-plan --root PLAN_FILE --format json`. Exit 2 is a package
contract failure and exit 3 is an over-budget stop; neither may advance. On exit
0, require `status: within_budget` and exactly the four non-boolean integer
metrics `root_bytes`, `total_bytes`, `file_count`, and `largest_member_bytes`.
Retain the root path and all four metrics for dispatches. Missing metrics or any
other result shape is a contract error (D5, D6, D8).

Conversation memory does not survive compaction; controllers that lost their place have re-dispatched entire completed task sequences. Track progress in a ledger file:

- Each plan owns a workspace: `scripts/sdd-workspace PLAN_FILE` prints the plan's git-ignored directory beneath the **primary checkout** — `<primary-checkout>/.superpowers/sdd/<checkout-bucket>/<plan-basename>/`, where `<checkout-bucket>` is `primary` for the primary checkout itself and `wt-<worktree-name>` for a linked worktree — home to every artifact for THIS plan: ledger, briefs, reports, review packages. It is never rooted at your cwd, so running from a linked worktree leaves no nested ledger inside it. Another plan's directory, and another checkout's bucket, is never yours to read or write.
- Check `<workspace>/progress.md`. If its first line names your plan file, tasks with a `Task <N>: complete` line are DONE — resume at the first task without one; a task whose last line is a fix round resumes mid-loop. A ledger naming a different plan is not yours: leave it, start fresh.
- Create the ledger with its identity as the first line: `# SDD ledger — plan: <plan file path>`.
- After compaction, trust the ledger and `git log` over recollection. (`git clean -fdx` in the primary checkout destroys the workspace; recover from `git log`.)

**Initial validation is the only whole-package read.** After the successful
checker result, read the root and every indexed member once in discovery order
and scan them for conflicts — tasks that contradict each other or the constraints,
or anything the package mandates that the review rubric treats as a defect — and
present findings as one batched question (each beside the plan text mandating it,
asking which governs) before execution begins. A missing or unreadable member is a contract error, never a fallback to monolithic parsing. Clean scan → proceed
without comment. After that, the controller holds only the plan root **header** —
summary, Global Constraints, Test seams, Delivery estimate and boundaries, and the `## Task index` (ID, title,
files touched, risk lane, member link per task) — its compact checker metrics,
plus the current task's brief from `scripts/task-brief`; never re-read the whole
package or retain other task bodies. Build the todo list from the Task index.

### Cumulative delivery gate

Resolve the integration branch from the project bindings, then pin
`DELIVERY_BASE` once to the full SHA printed by `git merge-base HEAD
origin/<integration-branch>`. Never derive it from an independently advanced
local integration branch. Before the first implementer, and after each completed
task before any next dispatch, pin `DELIVERY_HEAD` to the full `git rev-parse
HEAD` SHA and run `review-package PLAN_FILE DELIVERY_BASE DELIVERY_HEAD`.
Apply the producer-boundary validation and independent `artifact-budget check
--kind review-package` metric comparison defined in the task loop. This
cumulative gate supplements the task-scoped package and review; it does not
replace either.

A validated existing package satisfies a gate only when its manifest's full
`range.base` and `range.head` equal the intended full SHAs, its retained producer
report still validates, and a fresh independent artifact check agrees with all
four metrics. Seven-character path prefixes never establish range identity.
Record both full SHAs and the four checked metrics in the ledger. Exit 2 or 3,
malformed output, stale range identity, or metric disagreement cannot advance:
preserve completed work and identify an independently deliverable split for the
caller instead of dispatching more work.

## Agent tiers

Dispatch by agent type, with the model and effort its dispatch site declares; never leave the tier to inheritance — an `implementer` dispatch that omitted its model would run on its definition's Opus/high:

- **`mechanic`** — transcription plus testing: the plan text contains the complete code, or the change is single-file mechanical. Also inventories and bulk sweeps.
- **`implementer`** — every other implementation task: prose-specified work, multi-file integration, judgment inside a fixed scope. A planned task and its fix rounds 1–3 run on Sonnet/high (the `task-implementer` role); a stuck task's escalations — fix rounds 4–5 and a reasoning-problem BLOCKED — and the final-review fixer run on Opus/high (the `implementer` role).
- **`reviewer`** — full-lane first-pass task review and every first-pass whole-branch review.
- **`reviewer-lite`** — only a scoped re-review (named prior findings + bounded fix diff) or a mechanical/low-risk lane verification (declared lane + bounded task diff). Ambiguous adjudication or branch-wide review escalates to `reviewer` on Opus/high, recorded in the SDD ledger.
- The **final review's two axes** dispatch per [final-review.md](final-review.md) — the conformance axis as `reviewer` on Opus/high; the correctness axis via `codex-collaboration`'s `diff-review` when `capabilities.review.code` is `available` and that skill is installed, and as `reviewer` on Opus/high when the capability is `unsupported` or the skill is not installed (`blocked` stops).
- **Stuck tasks escalate across models, not just tiers** — Sonnet → Opus: see the fix loop's rounds 4–5 and the BLOCKED handling under the task loop.

Turn count beats token price: a too-cheap agent takes 2–3× the turns on multi-step work and costs more overall. Unsure between mechanic and implementer → pick implementer.

**Re-evaluating Sonnet task implementers.** Sonnet/high task implementers replaced Opus/high on 2026-10-07. Judge that choice by this rule alone:

- *Metric:* the first-pass approval rate of full-lane task reviews of tasks a `task-implementer` implemented — the share whose first-pass review needed no fix round (spec ✅ and no Critical or Important finding).
- *Baseline:* Opus/high implementers, about 84% first-pass approval across 153 full-lane first-pass reviews, measured before 2026-10-07.
- *When:* after about 10 delivered issues under this routing, and only once the sample holds at least 30 full-lane first-pass reviews; below that floor, keep going.
- *Decision:* below 74% (ten points under the baseline) is clearly worse — revert by pointing the `sdd-nonmechanical-implementation` and `sdd-task-fix-redispatch` sites back at the `implementer` role and retiring the `task-implementer` role. At or above 74%, keep Sonnet; a rate between 74% and 84% is reported but is not a revert trigger.

**Leaf-agent clauses.** Every prompt this skill composes for an `Agent` dispatch — here, in [fix-loop.md](fix-loop.md) or in [final-review.md](final-review.md) — carries these four clauses verbatim, as a paragraph of their own; a prompt built from one of the `*-prompt.md` templates already carries them:

> Launch any subagent by type only, never by name: a subagent cannot spawn a named teammate, and a named launch returns an error instead of work. Read an existing file before writing to it: overwriting content you have not read destroys work you cannot see. Run each long command, every verification command included, in the foreground with an explicit timeout above its expected duration. If the host moves one to the background anyway, wait for it within the same turn: never end your turn while a command you started is still running. Never write an `until` or `while` loop around `sleep` to wait for something: if a wait is truly needed, run one bounded foreground `sleep N`, then check once.

## The task loop

Everything you paste into a dispatch — and everything a subagent prints back — stays resident in your context for the session. Hand artifacts over as file paths; subagents write detail to files.

All removable cleanup is downstream of the D15 `delivery-detail` publication
contract. Its destination is derived by the producer beneath the primary
checkout's `.superpowers/issue-delivery/` home; callers supply issue, branch,
run, and head identity only, never an authoritative destination.

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
worker's launch fence refused its commit. Release that worker and make no
retry and no re-dispatch; then run
`workflow-state check-launch --repo-root <ledger_repo_root> --run-id <run-id> --action-id <action_id>`
on this launch. On `current: false` or any helper failure, follow from-issue's
superseded route: after that release nothing more is written; print
`/from-issue <num> --auto` on its own line and stop. On `current: true` the
refusal was no supersession: follow from-issue's suspension procedure with
`blocked_on=transport`. Without a lifecycle identity none of this applies and
workers commit with plain `git`.

Under a lifecycle identity, also record this launch's progress marker. Run
`workflow-state mark-progress --repo-root <ledger_repo_root> --run-id <run-id> --action-id <action_id>`
once before dispatching the first task this session will execute, and again
after each task completes (step 5). A commit that strictly descends from the
last recorded one starts a fresh anti-zombie stall count. A refusal changes
nothing, is not a suspension cause and never stops the task loop.

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

Record BASE (`git rev-parse HEAD`) first — the review package and fix-round diffs need it.

- `scripts/task-brief PLAN_FILE N` revalidates the package, resolves exactly one
  convention-linked member, copies it byte-for-byte, and prints the brief path.
  Checker exit 2/3 or a missing, unreadable, duplicate, or nonconventional member
  link stops before replacing an existing brief. The brief is the single source
  of task-specific requirements; exact values (numbers, magic strings,
  signatures, test cases) appear only there. Never make a subagent read the whole
  plan package.
- The dispatch contains: one line on where the task fits; the plan root path and
  all four metrics; the brief path ("read this first — it is your requirements,
  with the exact values to use verbatim"); interfaces and decisions from earlier
  tasks the brief cannot know; your resolution of any ambiguity you noticed; the
  report-file path (brief `…/task-N-brief.md` → report `…/task-N-report.md`) and
  report contract. It never contains member lists, task contents, or accumulated
  prior-task history (D6).
- If an earlier task parked a finding in this task's area, carry a pointer to that ledger entry.
- Record the implementer's agent identity — fix rounds 1–3 resume it.
- Never dispatch multiple implementers in parallel (conflicts).

Template: [implementer-prompt.md](implementer-prompt.md)

### 2. Handle the report

- **DONE** → run `review-package PLAN_FILE BASE HEAD` (BASE from step 1 — never `HEAD~1`, which silently drops all but the last commit), capture its compact JSON stdout unchanged, and pass those bytes through `artifact-budget validate-report --boundary producer --input -` before the step-3 gate.
- **DONE_WITH_CONCERNS** → correctness/scope concerns get addressed before review; observations get noted, review proceeds.
- **NEEDS_CONTEXT** → provide it, re-dispatch.
- **BLOCKED** → a `launch fence refused` report follows `### Lifecycle workers` and is never re-dispatched. Otherwise: context problem: add context, re-dispatch at the same tier. Reasoning problem: escalate to a fresh Opus/high implementer carrying the brief path, the report path and the blocker:

<!-- agent-dispatch: id=sdd-blocked-reasoning-escalation role=implementer model=opus effort=high -->
Agent(subagent_type="implementer", model="opus", effort="high") takes over a task whose implementer reported BLOCKED on a reasoning problem.

  Too large: split it. Plan wrong: escalate to the human. Never force an unchanged retry — if the implementer said it's stuck, something must change.

**Interim child results.** A child's return that the host marks interim — it stopped with background work of its own still running, or its result may be interim — is not a completion: the child is still running. Re-engage that same child by its recorded agent identity: message it to wait for its own job inside its turn and then return its final report, and wait for that report. You may end your own turn while the re-engaged child is live, because the host wakes you with its next notification; that is a child's work, not a command you started. Never answer an interim result with a text-only reply, never suspend for it (it is not an `external` wait), and never dispatch a replacement or stop the child. A registered lifecycle worker stays registered under its existing worker id: an interim result is not its `returned` event, and re-engagement is not a resume, so it registers nothing new. If the message cannot be delivered, the child is one you cannot wait for: follow from-issue's **Writing workers** route (task-stop, then release `--event stopped`), then this skill's ordinary handling of a lost child; that is the one case that may lead to a fresh dispatch. Only the child's final hand-back counts as its result.

If the implementer asks questions — before or during — answer completely; don't rush it.

Every initial review-package call uses one closed gate before any review
dispatch. Record the exact `base_sha and head_sha` before invoking any
`review-package` producer. Parse every producer report only after the
producer-boundary validator, then independently run
`artifact-budget check --kind review-package` on its root and compare all four
metrics. Only generator exit 0, validator exit 0, a strict `complete` report
and report/checker agreement permit dispatch. Exit 3 must validate as
`decompose_required`; record and return it with no reviewer dispatched. On
generator or validator exit 2, construct the exact failed SDD candidate with
`detail_state: "none"` and `report_path: null`, pass it through
`artifact-budget validate-report --boundary sdd` and return only canonical
stdout. Malformed or unknown output and any report/checker disagreement are
`failed`, recorded and returned before dispatch. `complete` plus `over_budget`
is a contract error.

Interface version 2 is allowed only when an individually oversized file is a
positively identified auto-generated EF Core migration designer, replaced by
bounded deterministic evidence; anything else that large exits 3. Never
classify by suffix alone, truncate a diff, or treat generated evidence as a
review waiver.

Interface version 3 is allowed only when a complete version-1/2 `-U10` package
fails solely on `member_count` and/or `aggregate_bytes`. It retries contexts 7,
5, 3, 1, 0, packing whole file-diff records with `stable-first-fit-whole-file`;
it never splits a file diff or omits a changed line. `member_bytes` and
`root_bytes` never take it.

### 3. Review the task

Per-task review is a task-scoped gate; never skip it, and never accept a report missing either verdict (spec compliance AND quality). Implementer self-review never substitutes. The gate's **form** follows the task's risk lane from the plan's task index:

- **full lane** — the full first-pass reviewer below, always.
- **mechanical / low-risk lane** — scoped verification: dispatch reviewer-lite with the declared lane and the bounded task diff. For a mechanical microtask whose verify commands are deterministic, the controller may instead verify inline (run the commands, inspect the diff) and ledger `Task <N>: verified inline (mechanical)`.
- **Batching** — adjacent same-lane microtasks in the same file neighborhood may share one verification context when isolation adds nothing; ledger the batch.
- A lane verification that surfaces ambiguity, semantic doubt, or anything beyond its lane escalates to the full reviewer — never adjudicate inside the cheap gate, and never route a lane the plan didn't declare.

<!-- agent-dispatch: id=sdd-lane-task-verification role=reviewer-lite model=sonnet effort=medium -->
Agent(subagent_type="reviewer-lite", model="sonnet", effort="medium") verifies the bounded mechanical/low-risk lane task diff against its brief.

For the full-lane review:

- The reviewer gets the plan root path and all four metrics, then the brief and
  report paths plus the review-package manifest root path and all four metrics
  (`root_bytes`, `total_bytes`, `file_count`,
  `largest_member_bytes`). It never gets a member list, shard list, artifact
  contents, diff contents, or another task body. The reviewer reads Global
  Constraints from the bounded plan root, strictly checks the manifest, then
  reads every shard once in manifest order and explicitly reports an unreadable
  or mismatched shard. The template carries the process rules; the root carries
  what THIS project's spec demands.
- Don't add open-ended directives ("check all uses") without a concrete task-specific reason; don't ask it to re-run tests the implementer already ran; and never pre-judge — if your prompt contains "do not flag" or "at most Minor", stop: adjudication happens in the loop, not the dispatch.
- **⚠️ Cannot-verify items** (requirements living in unchanged code or spanning tasks) don't block the review, but you resolve each yourself before marking the task complete — you hold the cross-task context. A confirmed gap enters the fix loop as a failed spec review.

Template: [task-reviewer-prompt.md](task-reviewer-prompt.md)

### 4. The fix loop

Triggers on spec ❌, any Critical/Important finding, or a confirmed ⚠️ gap — read [fix-loop.md](fix-loop.md) beside this file and follow it: five capped rounds (rounds 1–3 resume the original implementer by its recorded identity, round 4 is the Codex-assisted stuck-breaker and round 5 the final fresh dispatch, both on Opus/high), scoped re-reviews, the explicit escalation dispatch, and the at-the-cap breaker that parks or blocks every residual with a ledger ruling.

Two routes exit before the loop starts:

- **Minor findings** go to the ledger as they arrive (`Task <N>: minor (deferred): <one-liner>`); the final review triages them. They never enter the loop.
- **Plan-mandated findings** — anything conflicting with the plan's own text — are the human's call: present finding and plan text, ask which governs.

Never fix findings yourself in the controller session — controller fixes skip review and pollute the coordination context.

### 5. Complete the task

Clean review — or everything parked-with-ruling at the cap — appends `Task <N>: complete (commits <base7>..<head7>, review clean | <K> parked)`; mark the todo, run the cumulative delivery gate, then move on only when it passes. Never advance past open Critical/Important findings that are neither fixed nor parked. Under a lifecycle identity, record the progress marker right after that `complete` line (`### Lifecycle workers`).

## Final review — two axes

Mandatory for **every** risk lane — lanes narrow per-task review, never this gate. When all tasks are complete, read [final-review.md](final-review.md) beside this file and follow it: it owns the two isolated axis dispatches, the single fix wave, the scoped per-axis re-reviews, the escalation rules, and the **Final verification** step.

## Finish

Before any workspace can disappear, collect every parked or residual finding as
the strict non-empty detail input and write the retained candidate to
`<workspace>/retained-detail.json`. Invoke review-package in `delivery-detail`
mode with issue/branch/run/head identity; it alone derives the primary-checkout
destination. Independently run `artifact-budget check --kind review-package` on
the published root and compare its metrics with the producer report.

Build one exact SDD JSON object with only `state`, `review_state`,
`conformance_verdict`, `correctness_verdict`, `verification_state`, `base_sha`,
`head_sha`, `acceptance_state`, `detail_state`, `report_path`, and `notes`,
then run `artifact-budget validate-report --boundary sdd` and transport only
canonical stdout. `base_sha` and `head_sha` are the `DELIVERY_BASE` and
`DELIVERY_HEAD` the final review's first pass covered, never the branch tip:
when the fix wave adds commits, the tip is past `head_sha`, and ship-issue
reviews those commits again as part of its delta since that final-review head.
`verification_state` is `passed` only when final-review.md's **Final
verification** step recorded a pass on the branch tip it ran on (the tip after
the fix wave, past `head_sha` when that wave added commits) or took its
none-declared route with the per-task focused tests passing, and `failed` when
that step's repair round did not pass. `acceptance_state` derives from the
final verdicts final-review.md recorded: `not_applicable` when there was no
criterion source or the run failed before the conformance axis graded;
otherwise `unmet` when any verdict is `unmet` or `unverified`; otherwise
`human_pending` when any verdict is `human_pending`; otherwise `met`.
`artifact-budget validate-report --boundary sdd` rejects `unmet` under `clean`.
A non-empty detail set is `present` with one main-root-relative durable path.
With genuinely no findings it is `none` with a null path; transient review
evidence is never inlined.

If publication fails, run `artifact-budget validate-detail-input` against the
no-follow retained file and consume canonical stdout, requiring non-empty findings
and comparison with the candidate before setting `detail_state: "unpublished"`.
That `report_path` is the `<workspace>/retained-detail.json` written above, and
is **main-root-relative** like the durable path: the workspace lives beneath
the primary checkout, never the process cwd, so both sdd detail states share
one root — unlike ship-issue, which roots its retained candidate in the feature
worktree instead. Name the root in notes.
Then validate the failed candidate through `artifact-budget
validate-report --boundary sdd`, keep the workspace and keep the worktree, and
do not remove either. Missing, unreadable, empty, malformed, wrong-schema, or
empty-findings input remains failed without an unpublished claim.

Terminal states:

- **Clean** — both axes clean (or clean after the fix wave), or every remaining
  finding parked-with-ruling (an acceptance finding never is), and the **Final
  verification** step recorded a pass on the branch tip or took its
  none-declared route:
  delete this plan's workspace (`rm -rf <workspace>`; sibling directories
  belong to other plans) and report `review_state: clean` — parked findings
  are already available through the one durable report.
- **Residuals** — the breaker surfaced a load-bearing residual the caller must
  decide on: keep the workspace and ledger for the caller's inspection and report
  `review_state: residuals`; the retained or durable review package named by the
  single `report_path` is the only findings transport.

Report to the calling workflow only the validated SDD JSON above. `review_state`
is `clean | residuals` — sdd never reports `unknown`; that third value exists for
downstream callers describing a branch with no evidence of a completed sdd
review. Do not ship, merge, or open PRs — the caller owns delivery.
