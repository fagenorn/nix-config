---
name: sdd
description: Execute an implementation plan with a fresh subagent per task, reviewed between tasks. Use when a written plan with independent tasks is ready to build.
---

# Subagent-Driven Development

Execute a plan by dispatching a fresh implementer per task, a task review (spec compliance + code quality) after each, and one two-axis whole-branch review (conformance ∥ correctness) at the end. Subagents never inherit your session's history — you construct exactly what each needs, which is also what keeps your own context flat for coordination.

**Continuous execution:** don't pause to check in between tasks. Stop only for BLOCKED you cannot resolve, ambiguity that genuinely prevents progress, or all-tasks-complete. Narrate at most one short line between tool calls — the ledger and tool results carry the record.

## Setup

Work happens in an isolated workspace: invoke the `worktrees` skill to create or verify one. Never implement on a main/master branch without explicit consent.

Conversation memory does not survive compaction; controllers that lost their place have re-dispatched entire completed task sequences. Track progress in a ledger file:

- Each plan owns a workspace: run this skill's `scripts/sdd-workspace PLAN_FILE` — it prints the plan's git-ignored directory (`<repo-root>/.superpowers/sdd/<plan-basename>/`), home to every artifact for THIS plan: ledger, briefs, reports, review packages. Another plan's directory is never yours to read or write.
- Check `<workspace>/progress.md`. If its first line names your plan file, tasks with a `Task <N>: complete` line are DONE — resume at the first task without one; a task whose last line is a fix round resumes mid-loop. A ledger naming a different plan is not yours: leave it, start fresh.
- Create the ledger with its identity as the first line: `# SDD ledger — plan: <plan file path>`.
- After compaction, trust the ledger and `git log` over your own recollection. (`git clean -fdx` destroys the workspace; recover from `git log`.)

**Initial validation is the only whole-plan read.** Read the plan once now and scan for conflicts — tasks that contradict each other or the constraints, or anything the plan mandates that the review rubric treats as a defect — and present findings as one batched question (each beside the plan text mandating it, asking which governs) before execution begins. Clean scan → proceed without comment. After that, the controller holds only the plan **header** — summary, Global Constraints, Test seams, and the `## Task index` (ID, title, files touched, risk lane per task) — plus the current task's brief from `scripts/task-brief`; never re-read the whole plan. Build the todo list from the task index.

## Agent tiers

Dispatch by agent type — the definitions carry the model and effort tier; never leave the tier to inheritance:

- **`mechanic`** — implementation that is transcription plus testing: the plan text contains the complete code, or the change is single-file mechanical. Also inventories and bulk sweeps.
- **`implementer`** — every other implementation task: prose-specified work, multi-file integration, anything needing judgment inside a fixed scope.
- **`reviewer`** — first-pass task review and every first-pass whole-branch review.
- **`reviewer-lite`** — only a scoped re-review supplied with named prior findings and a bounded fix diff. Ambiguous adjudication or branch-wide review escalates to `reviewer` on Opus/high and is recorded in the SDD ledger.
- The **final review's two axes** dispatch per §Final review — the conformance axis as `reviewer` on Sonnet/high (delivered-vs-promised grading is checklist-shaped work against written promises; the top tier stays on correctness), the correctness axis via `codex-collaboration`'s `diff-review` when that skill is available, else as `reviewer` on Opus/high.
- **Stuck tasks escalate across models, not just tiers** — see the fix loop's round 4.

Turn count beats token price: a too-cheap agent takes 2–3× the turns on multi-step work and costs more overall. When unsure between mechanic and implementer, pick implementer.

## The task loop

Everything you paste into a dispatch — and everything a subagent prints back — stays resident in your context for the rest of the session. Hand artifacts over as file paths, and have subagents write detail to files.

### 1. Dispatch the implementer

Record BASE (`git rev-parse HEAD`) first — the review package and fix-round diffs need it.

- Run `scripts/task-brief PLAN_FILE N` — it extracts the task's full text to a file and prints the path. The brief is the single source of requirements; exact values (numbers, magic strings, signatures, test cases) appear only there. Never make a subagent read the whole plan.
- The dispatch contains: one line on where the task fits; the brief path ("read this first — it is your requirements, with the exact values to use verbatim"); interfaces and decisions from earlier tasks the brief cannot know; your resolution of any ambiguity you noticed; the report-file path (brief `…/task-N-brief.md` → report `…/task-N-report.md`) and report contract. No accumulated prior-task history — a fresh subagent needs its task, the interfaces it touches, and the global constraints, nothing else.
- If an earlier task parked a finding in the area this task touches, carry a pointer to that ledger entry.
- Record the implementer's agent identity — fix rounds 1–3 resume it.
- Never dispatch multiple implementers in parallel (conflicts).

Template: [implementer-prompt.md](implementer-prompt.md)

### 2. Handle the report

- **DONE** → run `scripts/review-package PLAN_FILE BASE HEAD` (BASE from step 1 — never `HEAD~1`, which silently drops all but the last commit) and dispatch the task reviewer with the printed path.
- **DONE_WITH_CONCERNS** → read the concerns; correctness/scope concerns get addressed before review, observations get noted and review proceeds.
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

- The reviewer gets three paths — brief, report, review package — plus the global constraints copied **verbatim** from the plan (exact values, formats, stated relationships). The template carries the process rules; the constraints block is what THIS project's spec demands.
- Don't add open-ended directives ("check all uses") without a concrete task-specific reason; don't ask it to re-run tests the implementer already ran; and never pre-judge — if your prompt contains "do not flag" or "at most Minor", stop: adjudication happens in the loop, not the dispatch.
- **⚠️ Cannot-verify items** (requirements living in unchanged code or spanning tasks) don't block the review, but you resolve each yourself before marking the task complete — you hold the cross-task context. A confirmed gap enters the fix loop as a failed spec review.

Template: [task-reviewer-prompt.md](task-reviewer-prompt.md)

### 4. The fix loop

Triggers on spec ❌, any Critical/Important finding, or a confirmed ⚠️ gap. Two routes exit before it starts:

- **Minor findings** go to the ledger as they arrive (`Task <N>: minor (deferred): <one-liner>`); the final review triages them. They never enter the loop.
- **Plan-mandated findings** — anything conflicting with the plan's own text — are the human's call: present finding and plan text, ask which governs.

A round is one fix dispatch plus one scoped re-review. Five rounds maximum:

- **Rounds 1–3 — resume the original implementer** with the open findings verbatim; its context is intact. (Can't resume? Fresh dispatch carrying brief path, report path, findings — the report file is the persistent memory.)
- **Round 4 — the stuck-breaker.** Three same-context rounds failing usually means the implementer cannot see its own problem, and another same-model retry re-runs the blindness. Use the bounded Codex transport with the failing command or test, the diff so far (`BASE..HEAD`), the brief and report paths, and the open findings:

<!-- agent-dispatch: id=sdd-codex-rescue-transport role=codex-transport model=sonnet effort=medium -->
Agent(subagent_type="codex:rescue", model="sonnet", effort="medium") transports the bounded stuck-breaker diagnosis to the external Codex runtime without selecting that runtime's model.

  **Verify its diagnosis against the live worktree before acting on it**, then use a fresh judgment-bearing implementer:

<!-- agent-dispatch: id=sdd-post-rescue-implementation role=implementer model=opus effort=high -->
Agent(subagent_type="implementer", model="opus", effort="high") applies the verified rescue diagnosis plus the open findings.

  Codex unavailable → use the same Opus/high implementation tier with the packet and the framing "a prior implementer attempted this task 3 times; you own it now — read the report file for what was tried":

<!-- agent-dispatch: id=sdd-rescue-fallback-implementation role=implementer model=opus effort=high -->
Agent(subagent_type="implementer", model="opus", effort="high") owns the fresh-context rescue fallback.
- **Round 5 — last round**, same packet plus round 4's findings, owned by a fresh Opus/high implementer:

<!-- agent-dispatch: id=sdd-round-five-implementation role=implementer model=opus effort=high -->
Agent(subagent_type="implementer", model="opus", effort="high") owns the fifth and final fix round.

Every round: the implementer fixes, re-runs the covering tests, appends a fix report (what changed, covering tests, command, output) to the same report file, and returns the short contract. Confirm all three fix-report elements before dispatching the re-review — reviewers do not re-run tests.

The re-review is scoped: `scripts/review-package PLAN_FILE FIX_BASE HEAD` (FIX_BASE = the head the previous review saw), template [re-review-prompt.md](re-review-prompt.md), with the findings list, brief, and report paths. Its explicit `reviewer-lite` selection verdicts each finding ADDRESSED / NOT ADDRESSED and flags new breakage in the fix diff only; out-of-scope observations go to the ledger as deferred minors. A result that requires ambiguous adjudication or branch-wide review escapes reviewer-lite through this explicit full-review dispatch:

<!-- agent-dispatch: id=sdd-task-rereview-escalation role=reviewer model=opus effort=high -->
Agent(subagent_type="reviewer", model="opus", effort="high") adjudicates an ambiguous or branch-wide task re-review escape.

Record the escalation and selected full-review role in this plan's SDD ledger.

After each round, append: `Task <N>: fix round <R>/5 (<X> addressed, <Y> open — <one-liners>; commits <a7>..<b7>)`.

Never fix findings yourself in the controller session — controller fixes skip review and pollute the coordination context.

**The breaker.** When round 5's re-review still leaves findings open, stop dispatching and adjudicate each yourself:

- Reviewer wrong, or contestable → park it: `Task <N>: parked — <finding> — ruling: <why the code stands>`.
- Real but nothing downstream builds on it → park it, ruling says real-and-deferred.
- Real and load-bearing (a later task builds on it, or it reveals a plan defect) → STOP: `Task <N>: BLOCKED — <reason>`, report to the human with the finding, the colliding plan text, and the fix history.

Adjudicate only at the cap — earlier is pre-judging with a different name. Every adjudication is a ledger entry; silent discards are forbidden.

### 5. Complete the task

Clean review — or everything parked-with-ruling at the cap — appends `Task <N>: complete (commits <base7>..<head7>, review clean | <K> parked)`; mark the todo, move on. Never advance past open Critical/Important findings that are neither fixed nor parked.

## Final review — two axes

This gate runs for **every** risk lane — lanes narrow per-task review, never this one. Run `scripts/review-package PLAN_FILE MERGE_BASE HEAD` (MERGE_BASE = `git merge-base <integration-branch> HEAD`) once, then review the branch on two axes **in parallel, as isolated subagents** over that same package:

- **Conformance axis** — did the diff deliver what issue + spec + plan promised, honoring the project's ADRs, context docs, and standards. Native `reviewer`, model per Agent tiers, template [conformance-reviewer-prompt.md](conformance-reviewer-prompt.md).
- **Correctness axis** — is it built right: bugs, boundary error handling, dead branches, assertions that pin the documented contract, DRY, cross-task integration. When the `codex-collaboration` skill is available, invoke its `diff-review` operation for this axis; that skill solely owns the isolated Codex transport launch and one-time native fallback, while the external Codex reviewer keeps its independently configured model. Unavailable → use the Opus/high native reviewer selected in [correctness-reviewer-prompt.md](correctness-reviewer-prompt.md). Either way the axis is never skipped.

Point the conformance dispatch at the ledger's deferred-minor and parked lines so it triages what must be fixed before merge. Verdicts come back ≤400 words each, findings Critical/Important/Minor anchored to file:line. **Never merge the two reports** into one narrative — they are independent signals; disposition each on its own, and record both verdicts plus the correctness axis's reviewer identity (`Codex` | `native` | `fallback` + failure class) in the ledger.

Findings → verify each against the live worktree first (stale or unsupported ones are rejected by you, in the ledger), then use one Opus/high fixer with the complete list labeled by axis:

<!-- agent-dispatch: id=sdd-final-review-fixer role=implementer model=opus effort=high -->
Agent(subagent_type="implementer", model="opus", effort="high") fixes the verified whole-branch findings in one wave.

Where both axes flag the same lines, dedupe at dispatch and credit both axes in the ledger (per-finding fixers each rebuild context and re-run suites; a real session's per-finding fix wave cost more than all its tasks combined). Then run exactly one scoped re-review per axis that had findings, using that axis's unchanged rubric with the named findings and bounded fix-range package:

<!-- agent-dispatch: id=sdd-final-conformance-rereview role=reviewer-lite model=sonnet effort=medium -->
Agent(subagent_type="reviewer-lite", model="sonnet", effort="medium") re-verdicts the named conformance findings against the bounded fix diff.
<!-- agent-dispatch: id=sdd-final-correctness-rereview role=reviewer-lite model=sonnet effort=medium -->
Agent(subagent_type="reviewer-lite", model="sonnet", effort="medium") re-verdicts the named correctness findings against the bounded fix diff.

For either axis, supply (1) the axis's findings list verbatim, (2) a fix-range package from `scripts/review-package PLAN_FILE FIX_BASE HEAD` (FIX_BASE = the head that axis's first pass reviewed), and (3) the instruction to verdict each finding ADDRESSED / NOT ADDRESSED and flag new breakage in the fix diff only — out-of-scope observations go to the ledger as deferred minors; ≤400 words. Ambiguous or branch-wide judgment escapes reviewer-lite through this explicit full-review dispatch:

<!-- agent-dispatch: id=sdd-final-rereview-escalation role=reviewer model=opus effort=high -->
Agent(subagent_type="reviewer", model="opus", effort="high") adjudicates an ambiguous or branch-wide final-axis re-review escape.

Record the escalation and selected full-review role in the SDD ledger. Adjudicate residuals like the task-loop breaker. There is no second fix wave — residual load-bearing findings surface to the caller.

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

## Common rationalizations

| Excuse | Reality |
|--------|---------|
| "Close enough on spec compliance" | Spec gaps = not done. Fix or hit the cap and adjudicate — the only exits. |
| "I'll fix it myself, dispatching is overhead" | Controller fixes pollute context and skip review. Resume the implementer. |
| "One more round will converge" | Past the cap the failure is structural. Adjudicate and route. |
| "This finding is obviously wrong, I'll drop it" | Adjudicate only at the cap; every ruling is a ledger entry. |
| "The fix was small, skip the re-review" | Unreviewed fixes are how regressions land. |
| "Ledger bookkeeping is overhead" | The ledger is what survives compaction — without one, controllers have re-executed whole plans. |
