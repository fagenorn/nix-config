# Autonomous mode (`--auto`)

Read this file once, when you detect `--auto` in the invocation. It replaces the checkpoint
behavior in `SKILL.md`; everything else in `SKILL.md` still applies.

You don't get to skip thinking — you only stop waiting for the user.

## Contents

- The self-answer pattern
- When *not* to auto-resolve
- Phases 2–4 run as subagents
- Interface_version 2 delivery relay
- Other Phase 5–7 routes

## The self-answer pattern

Wherever a phase or sub-skill would ask the user a clarifying question, present option sets, or pause
at a `**CHECKPOINT**`:

1. **Ground first.** Use this phase's `GROUNDING.md` cache. If the decision reaches into an area
   the cache doesn't cover, load that area and append it.
2. **Pick the most defensible default** — the choice that aligns with documented invariants and ADRs,
   matches existing precedent in the codebase, honors the issue author's stated intent, and keeps
   scope tight. When two options are both defensible, prefer the smaller, more reversible, more
   idiomatic one.
3. **Log it** as a row in the spec's `## Decision ledger` (the C1 decision-ledger format; its file is
   in `SKILL.md`'s index), applying the non-obvious-only filter — routine splits, commit boundaries,
   and obvious verification commands are not rows. Plans and ADRs cite the ID.
4. **Continue.** Don't post the question. Don't wait.

Auto-resolving a checkpoint never skips `workflow-state progress`: persist the gate decision at
every phase checkpoint and obey its returned action before the next phase starts. If it returns a
durable handoff, invoke `handoff` at the per-run destination, finalize it through
`workflow-state progress`, and stop. For every ordinarily owned terminal result, call
`workflow-state finish` successfully before any notification to the dispatcher; persistence always
precedes notification. A delegated-owner dispatch failure is such a result and must be persisted
before notification.

Sub-skills (`design`, `grill-with-docs`, `writing-plans`, `sdd`, `ship-issue`) don't know about
`--auto`. *You* carry the autonomous-mode context: when one tells you to ask or wait, run the
self-answer pattern instead. Never self-answer a request for new authorization. First apply any
existing explicit user grant whose scope covers the concrete action and target; a phase or session
boundary does not erase it, and silence never creates or expands a grant. When authority is absent,
present the gate's concrete block and follow `SKILL.md`'s suspension procedure, suspending
`blocked_on: human_gate` and printing the canonical re-entry line. An actual permission denial
stops that action and is never routed around.

## When *not* to auto-resolve

There are no checkpoint gates, but two content-level stops still apply:

- **Phase 0 wrong-issue-type stop.** If the issue is several issues bundled, a duplicate, a pure
  question, or otherwise not implementable, surface that and stop. Phase 0 reconciles an exact
  open or merged PR per Phase 0's PR pre-flight; it remains a stop only when ownership,
  target, scope, acceptance evidence, or authority is unknown. The same stop
  rule applies to dirty or multiple matching worktrees and a matching worktree
  whose disposability cannot be proven — prefer an authorized resume; never delete on ambiguity.
  When lifecycle identity exists, finalize this terminal result through the
  SKILL.md terminal return procedure before stopping.
- **Phase 0 fog gate.** Before any worktree exists, test the grounded issue: can every open question
  be *phrased precisely* and answered from the docs, codebase precedent, or the issue itself with a
  defensible default? Vague-but-phraseable questions are normal `--auto` work — self-answer them.
  **Fog** is different: a question you cannot state sharply, a load-bearing term the docs mark
  undefined or out-of-scope, no acceptance criterion that would make any answer falsifiable. Fog is
  an abort — stop before creating anything, name each foggy question in the stop report, and emit a
  `wayfind` decision ticket per question (when that skill and a tracker are available; otherwise the
  stop report carries the list). Abort conservatively: fog is the exception, autonomy stays the
  default posture.
- **Phase 5 blocking findings.** Apply blocking fixes to the plan inline. If a blocker can't be fixed
  by editing the plan — it means the spec or the issue scope is wrong — back up to that phase, redo
  it, and log the loop in the decision ledger.

Should-fix findings: apply inline and log with the reviewer's rationale. Exception: a should-fix that
implies a scope change ("the plan covers A but the spec promised A+B") — back up rather than
scope-creep the plan. Everything else — option choices, scope boundary calls, ADR phrasing, plan task
granularity — you decide and log.

## Phases 2–4 run as subagents

**In `--auto` these phases are dispatched.**

**The orchestrator (this session) holds only three things: the Phase-0 issue summary, the resolved
config bindings, and each phase's returned report.** Brainstorm and grill conversation must never
enter this context.

Both prompts must carry, inline (the subagent starts with no context and loads no skills of its own
beyond the exceptions named below):

- the Phase-0 issue summary and scope boundary, with the note's **Lane triage** record and verdict verbatim,
- the retained fields it needs (`bindings.paths.artifacts`, `bindings.paths.context`,
  `bindings.paths.hints`, `bindings.tracker`, `bindings.vcs`, and `bindings.workflow`),
- the absolute worktree path, and an instruction to `cd` there and commit its artifacts there,
- with lifecycle identity, the `Lifecycle worker:` line from `SKILL.md`'s **Writing workers** rule, the
  `launch-scope exec` and `scratch` sentences that follow it there, and the instruction to create every
  commit through `launch-commit` with its three values,
- the self-answer pattern above and the `## Decision ledger` table format with its non-obvious-only
  filter, pasted verbatim from the C1 decision-ledger format (its file is in `SKILL.md`'s index),
- the four clauses of `SKILL.md`'s **Leaf-agent clauses** rule, verbatim, as a paragraph of their own,
- the fixed return schema, with "details live in the committed files, not in your report".

**Skill exception.** Each subagent *should* invoke, through its own `Skill` tool, the globally
installed skills its phase names — `grill-with-docs` and `doc-grounded-questions` for the design
subagent, `writing-plans` and `doc-grounded-questions` for the plan subagent, plus
`design` if present. If one isn't
installed, it uses the inline fallback named in the corresponding `SKILL.md` phase.

A Phase 2–4 subagent's interim result follows `SKILL.md`'s **Interim child results** rule.

### Design subagent — Phases 2 + 3

<!-- agent-dispatch: id=from-issue-design-grill role=auto-owner model=opus effort=xhigh -->
Agent(subagent_type="general-purpose", model="opus", effort="xhigh") launches the autonomous design-and-grill owner.

One dispatch covering brainstorm and grill. It produces the design doc under `bindings.paths.artifacts.specs`, applies the
grill's refinements to it, and writes any context-doc updates and ADRs — all committed in the
worktree.

After the final mutation, write a candidate producer report, run
`artifact-budget validate-report --boundary producer`, and return only validated stdout bytes.
never inline artifact contents or member paths. The exact `complete` report is:

```
{"state":"complete","artifact":{"kind":"design-spec","path":"<root relative to repo>","metrics":{"root_bytes":<int>,"total_bytes":<int>,"file_count":<int>,"largest_member_bytes":<int>},"budget_status":"within_budget"},"notes":"<bounded note>"}
```

The exact over-budget report includes the checker's ordered, non-empty
`violations` array:

```
{"state":"decompose_required","artifact":{"kind":"design-spec","path":"<root relative to repo>","metrics":{"root_bytes":<int>,"total_bytes":<int>,"file_count":<int>,"largest_member_bytes":<int>},"budget_status":"over_budget","violations":["root_bytes"]},"notes":"<bounded note>"}
```

For `failed`, `artifact` is exactly `null` before a root exists or exactly
`{"kind":"design-spec","path":"<root relative to repo>"}` after one exists;
metrics, budget status, and violations are forbidden in both failed rows.

### Plan subagent — Phase 4 (+ mechanical Phase 5)

<!-- agent-dispatch: id=from-issue-planning role=auto-owner model=opus effort=xhigh -->
Agent(subagent_type="general-purpose", model="opus", effort="xhigh") launches the autonomous planning owner.

Writes the implementation plan package under `bindings.paths.artifacts.plans`, committed in the worktree, with a `## Task index`
carrying each task's risk lane; it cites decision-ledger rows by ID and appends new non-obvious
plan-level decisions to the spec's ledger. Give it the validated spec artifact
root and metrics plus notes — not a transcript. `SKILL.md`'s plan-prose ≠
code-prose rule goes in the prompt.

When Phase 0 declared the issue `mechanical-only`, this dispatch also performs the Phase-5 self-grade
(read issue, spec, plan, live files, standards; grade against Blocking / Should-fix / Discussion) and
applies its own blocking fixes before returning.

After the final mutation, write a candidate producer report, run
`artifact-budget validate-report --boundary producer`, and return only validated stdout bytes.
never inline artifact contents or task member paths. The exact `complete` report is:

```
{"state":"complete","artifact":{"kind":"implementation-plan","path":"<root relative to repo>","metrics":{"root_bytes":<int>,"total_bytes":<int>,"file_count":<int>,"largest_member_bytes":<int>},"budget_status":"within_budget"},"notes":"<bounded note>"}
```

The exact over-budget report includes the checker's ordered, non-empty
`violations` array:

```
{"state":"decompose_required","artifact":{"kind":"implementation-plan","path":"<root relative to repo>","metrics":{"root_bytes":<int>,"total_bytes":<int>,"file_count":<int>,"largest_member_bytes":<int>},"budget_status":"over_budget","violations":["root_bytes"]},"notes":"<bounded note>"}
```

For `failed`, `artifact` is exactly `null` before a root exists or exactly
`{"kind":"implementation-plan","path":"<root relative to repo>"}` after one
exists; metrics, budget status, and violations are forbidden in both failed
rows. `complete` plus any status other than `within_budget` is a contract error.

## Interface_version 2 delivery relay

Every relay here carries a validated object unchanged: the interface-2 `owner`
object in the continuation, the ship report's `ship-summary/v2` into `finish`,
and each `workflow-state` reply after `artifact-budget validate-report
--boundary workflow-response`. Delivery effects, scopes and observations belong
to ship-issue's `## Delivery loop`; a returned `delivery_remainder` launches
ship-issue remainder mode per `SKILL.md`.

## Other Phase 5–7 routes

A direct autonomous controller hands Phases 6–7 to a fresh owner at the Phase-5 rollover, mechanical-only runs included. Elsewhere Phase 5's reviewer gets `REVIEW-CONTRACT.md`'s path.

At every Phase-6 or Phase-7 push, PR-open, or merge gate, first apply repository
policy or an explicit user grant covering the concrete action, target, and
effect. A host without standing repository authorization may continue under an
existing scoped user grant and its normal approval review. When neither source
grants the action, follow `SKILL.md`'s suspension procedure with
`blocked_on: human_gate` and the canonical re-entry line. This never bypasses
`check-launch`: `current: false`, helper failure, or an actual permission denial
stops the action and is never routed around.
