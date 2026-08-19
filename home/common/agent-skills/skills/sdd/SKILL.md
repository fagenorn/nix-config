---
name: sdd
description: Execute an implementation plan with a fresh subagent per task, reviewed between tasks. Use when a written plan with independent tasks is ready to build.
---

# Subagent-Driven Development

Execute a plan by dispatching a fresh implementer per task, a lane-scoped task review after each, and one two-axis whole-branch review (conformance ∥ correctness) at the end. Subagents never inherit your session's history — you construct exactly what each needs, which also keeps your own context flat for coordination.

**Continuous execution:** don't pause between tasks. Stop only for BLOCKED you cannot resolve, ambiguity that genuinely prevents progress, or all-tasks-complete. Narrate at most one short line between tool calls — the ledger and tool results carry the record.

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

- Each plan owns a workspace: `scripts/sdd-workspace PLAN_FILE` prints the plan's git-ignored directory (`<repo-root>/.superpowers/sdd/<plan-basename>/`) — home to every artifact for THIS plan: ledger, briefs, reports, review packages. Another plan's directory is never yours to read or write.
- Check `<workspace>/progress.md`. If its first line names your plan file, tasks with a `Task <N>: complete` line are DONE — resume at the first task without one; a task whose last line is a fix round resumes mid-loop. A ledger naming a different plan is not yours: leave it, start fresh.
- Create the ledger with its identity as the first line: `# SDD ledger — plan: <plan file path>`.
- After compaction, trust the ledger and `git log` over recollection. (`git clean -fdx` destroys the workspace; recover from `git log`.)

**Initial validation is the only whole-package read.** After the successful
checker result, read the root and every indexed member once in discovery order
and scan them for conflicts — tasks that contradict each other or the constraints,
or anything the package mandates that the review rubric treats as a defect — and
present findings as one batched question (each beside the plan text mandating it,
asking which governs) before execution begins. A missing or unreadable member is a contract error, never a fallback to monolithic parsing. Clean scan → proceed
without comment. After that, the controller holds only the plan root **header** —
summary, Global Constraints, Test seams, and the `## Task index` (ID, title,
files touched, risk lane, member link per task) — its compact checker metrics,
plus the current task's brief from `scripts/task-brief`; never re-read the whole
package or retain other task bodies. Build the todo list from the Task index.

## Agent tiers

Dispatch by agent type — the definitions carry the model and effort tier; never leave the tier to inheritance:

- **`mechanic`** — transcription plus testing: the plan text contains the complete code, or the change is single-file mechanical. Also inventories and bulk sweeps.
- **`implementer`** — every other implementation task: prose-specified work, multi-file integration, judgment inside a fixed scope.
- **`reviewer`** — full-lane first-pass task review and every first-pass whole-branch review.
- **`reviewer-lite`** — only a scoped re-review (named prior findings + bounded fix diff) or a mechanical/low-risk lane verification (declared lane + bounded task diff). Ambiguous adjudication or branch-wide review escalates to `reviewer` on Opus/high, recorded in the SDD ledger.
- The **final review's two axes** dispatch per [final-review.md](final-review.md) — the conformance axis as `reviewer` on Sonnet/high, the correctness axis via `codex-collaboration`'s `diff-review` when that skill is available, else as `reviewer` on Opus/high.
- **Stuck tasks escalate across models, not just tiers** — see the fix loop's round 4.

Turn count beats token price: a too-cheap agent takes 2–3× the turns on multi-step work and costs more overall. Unsure between mechanic and implementer → pick implementer.

## The task loop

Everything you paste into a dispatch — and everything a subagent prints back — stays resident in your context for the session. Hand artifacts over as file paths; subagents write detail to files.

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

- **DONE** → run `scripts/review-package PLAN_FILE BASE HEAD` (BASE from step 1 — never `HEAD~1`, which silently drops all but the last commit), then the step-3 gate.
- **DONE_WITH_CONCERNS** → correctness/scope concerns get addressed before review; observations get noted, review proceeds.
- **NEEDS_CONTEXT** → provide it, re-dispatch.
- **BLOCKED** → context problem: add context, re-dispatch same tier. Reasoning problem: re-dispatch `implementer` (or bump the model). Too large: split it. Plan wrong: escalate to the human. Never force an unchanged retry — if the implementer said it's stuck, something must change.

If the implementer asks questions — before or during — answer completely; don't rush it.

### 3. Review the task

Per-task review is a task-scoped gate; never skip it, and never accept a report missing either verdict (spec compliance AND quality). Implementer self-review never substitutes. The gate's **form** follows the task's risk lane from the plan's task index:

- **full lane** — the full first-pass reviewer below, always.
- **mechanical / low-risk lane** — scoped verification: dispatch reviewer-lite with the declared lane and the bounded task diff. For a mechanical microtask whose verify commands are deterministic, the controller may instead verify inline (run the commands, inspect the diff) and ledger `Task <N>: verified inline (mechanical)`.
- **Batching** — adjacent same-lane microtasks in the same file neighborhood may share one verification context when isolation adds nothing; ledger the batch.
- A lane verification that surfaces ambiguity, semantic doubt, or anything beyond its lane escalates to the full reviewer — never adjudicate inside the cheap gate, and never route a lane the plan didn't declare.

<!-- agent-dispatch: id=sdd-lane-task-verification role=reviewer-lite model=sonnet effort=medium -->
Agent(subagent_type="reviewer-lite", model="sonnet", effort="medium") verifies the bounded mechanical/low-risk lane task diff against its brief.

For the full-lane review:

- The reviewer gets the plan root path and all four metrics, then three task
  paths — brief, report, review package — plus the global constraints copied
  **verbatim** from the root. It never gets a member list or another task body.
  The template carries the process rules; the constraints block is what THIS
  project's spec demands.
- Don't add open-ended directives ("check all uses") without a concrete task-specific reason; don't ask it to re-run tests the implementer already ran; and never pre-judge — if your prompt contains "do not flag" or "at most Minor", stop: adjudication happens in the loop, not the dispatch.
- **⚠️ Cannot-verify items** (requirements living in unchanged code or spanning tasks) don't block the review, but you resolve each yourself before marking the task complete — you hold the cross-task context. A confirmed gap enters the fix loop as a failed spec review.

Template: [task-reviewer-prompt.md](task-reviewer-prompt.md)

### 4. The fix loop

Triggers on spec ❌, any Critical/Important finding, or a confirmed ⚠️ gap — read [fix-loop.md](fix-loop.md) beside this file and follow it: five capped rounds (rounds 1–3 resume the original implementer by its recorded identity, round 4 is the Codex-assisted stuck-breaker, round 5 the final fresh dispatch), scoped re-reviews, the explicit escalation dispatch, and the at-the-cap breaker that parks or blocks every residual with a ledger ruling.

Two routes exit before the loop starts:

- **Minor findings** go to the ledger as they arrive (`Task <N>: minor (deferred): <one-liner>`); the final review triages them. They never enter the loop.
- **Plan-mandated findings** — anything conflicting with the plan's own text — are the human's call: present finding and plan text, ask which governs.

Never fix findings yourself in the controller session — controller fixes skip review and pollute the coordination context.

### 5. Complete the task

Clean review — or everything parked-with-ruling at the cap — appends `Task <N>: complete (commits <base7>..<head7>, review clean | <K> parked)`; mark the todo, move on. Never advance past open Critical/Important findings that are neither fixed nor parked.

## Final review — two axes

Mandatory for **every** risk lane — lanes narrow per-task review, never this gate. When all tasks are complete, read [final-review.md](final-review.md) beside this file and follow it: it owns the two isolated axis dispatches, the single fix wave, the scoped per-axis re-reviews, and the escalation rules.

## Finish

Terminal states:

- **Clean** — both axes clean (or clean after the fix wave), or every remaining
  finding parked-with-ruling: delete this plan's workspace (`rm -rf <workspace>`;
  sibling directories belong to other plans) and report `review_state: clean` —
  parked findings still travel in the report's parked-findings field.
- **Residuals** — the breaker surfaced a load-bearing residual the caller must
  decide on: keep the workspace and ledger for the caller's inspection and report
  `review_state: residuals` with the surfaced list.

Report to the calling workflow: `review_state` (`clean | residuals` — sdd never reports `unknown`; that third value exists for downstream callers describing a branch with no evidence of a completed sdd review), per-axis final-review verdicts, commit range `<base7>..<head7>`, parked findings with rulings, verification status, ≤500 characters of notes. Do not ship, merge, or open PRs — the caller owns delivery.
