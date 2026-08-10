# Autonomous mode (`--auto`)

Read this file once, when you detect `--auto` in the invocation. It replaces the checkpoint
behavior in `SKILL.md`; everything else in `SKILL.md` still applies.

The shift is *what you do at a decision point*, not *what work gets done*. Every phase still
produces the same artifact at the same quality bar. Brainstorm still happens. Grill still happens.
Standards review still happens. You don't get to skip thinking — you only stop waiting for the user.

## The self-answer pattern

Wherever a phase or sub-skill would ask the user a clarifying question, present option sets, or pause
at a `**CHECKPOINT**`:

1. **Ground first.** Use this phase's `GROUNDING.md` cache (see `SKILL.md` → Doc grounding). If the
   decision reaches into an area the cache doesn't cover, load that area and append it.
2. **Pick the most defensible default** — the choice that aligns with documented invariants and ADRs,
   matches existing precedent in the codebase, honors the issue author's stated intent, and keeps
   scope tight. When two options are both defensible, prefer the smaller, more reversible, more
   idiomatic one.
3. **Log it** in the artifact's `## Auto-resolved decisions` section, one entry per decision, using
   the template in `SKILL.md`. This is the audit trail: a human reviewing the PR can challenge any
   choice without re-deriving it.
4. **Continue.** Don't post the question. Don't wait.

Sub-skills (`design`, `grill-with-docs`, `writing-plans`, `sdd`,
`ship-issue`) don't know about `--auto`. *You* carry the autonomous-mode context — when one tells you
to ask or wait, run the self-answer pattern instead.

## When *not* to auto-resolve

There are no checkpoint gates, but two content-level stops still apply, because they are judgments
about the work itself rather than user-approval gates:

- **Phase 0 wrong-issue-type stop.** If the issue is several issues bundled, a duplicate, a pure
  question, or otherwise not implementable, surface that and stop. Auto-mode means "decide without
  asking", not "implement something incoherent". The same holds for the Phase-0 pre-flight stops
  (open/merged PR, dirty or multiple matching worktrees).
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
  it, and log the loop in `Auto-resolved decisions`.

Should-fix findings: apply inline and log with the reviewer's rationale. Exception: a should-fix that
implies a scope change ("the plan covers A but the spec promised A+B") — back up rather than
scope-creep the plan. Everything else — option choices, scope boundary calls, ADR phrasing, plan task
granularity — you decide and log.

## Phases 2–4 run as subagents

Interactive mode runs these phases inline and conversationally. **In `--auto` they are dispatched**,
because brainstorm and grill transcripts are the single largest context sink in the flow and none of
it is needed downstream — the artifacts are.

**The orchestrator (this session) holds only three things: the Phase-0 issue summary, the resolved
config bindings, and each phase's returned report.** Brainstorm and grill conversation must never
enter this context. Don't ask a subagent to "show its reasoning"; the reasoning belongs in the
committed artifact.

Both dispatches: `Agent` tool, `subagent_type: general-purpose`, model inherited — design quality is
worth paying for here. Purely mechanical dispatches elsewhere in the flow use `mechanic`;
reviewer-shaped dispatches use `reviewer`.

Both prompts must carry, inline (the subagent starts with no context and loads no skills of its own
beyond the exceptions named below):

- the Phase-0 issue summary and scope boundary,
- the resolved bindings it needs (`specDir`, `planDir`, `docPaths.*`, `projectHints`,
  `commit.coAuthoredBy`, `<tracker-cli>`, `unsetGithubToken`),
- the absolute worktree path, and an instruction to `cd` there and commit its artifacts there,
- the self-answer pattern above and the `## Auto-resolved decisions` template, pasted verbatim,
- the fixed return schema, with "details live in the committed files, not in your report".

**Skill exception.** Each subagent *should* invoke, through its own `Skill` tool, the globally
installed skills its phase names — `grill-with-docs` and `doc-grounded-questions` for the design
subagent, `writing-plans` and `doc-grounded-questions` for the plan subagent, plus
`design` if present. Those load in the subagent's context, not yours. If one isn't
installed, it uses the inline fallback named in the corresponding `SKILL.md` phase.

### Design subagent — Phases 2 + 3

One dispatch covering brainstorm and grill. It produces the design doc under `specDir`, applies the
grill's refinements to it, and writes any context-doc updates and ADRs — all committed in the
worktree. Splitting these into two dispatches would mean re-establishing the whole design in a second
prompt for no gain.

Return schema:

```
spec_path:  <path relative to repo root>
adr_paths:  [<path>, …]   ([] if none)
decisions:  [<one-line title per auto-resolved decision>]
notes:      <≤500 chars: unresolved tension, scope surprise, or anything the plan phase must know>
```

### Plan subagent — Phase 4 (+ mechanical Phase 5)

Writes the implementation plan under `planDir`, committed in the worktree, including its own
`## Auto-resolved decisions` section. Give it the spec path and the design subagent's `decisions` and
`notes` — not its transcript. `SKILL.md`'s plan-prose ≠ code-prose rule goes in the prompt.

When Phase 0 declared the issue `mechanical-only`, this dispatch also performs the Phase-5 self-grade
(read issue, spec, plan, live files, standards; grade against Blocking / Should-fix / Discussion) and
applies its own blocking fixes before returning.

Return schema:

```
plan_path:   <path relative to repo root>
open_items:  [<blocking or should-fix item it could not resolve>]   ([] if none)
notes:       <≤500 chars>
```

### Phases 5, 6, 7

Already out-of-context and unchanged by autonomous mode: Phase 5 dispatches the reviewer (or
`codex-collaboration`) with `REVIEW-CONTRACT.md`'s path, Phase 6 runs subagent-driven development, and
Phase 7 dispatches `ship-issue` with `auto: true` in its handoff. Verifying findings and dispositioning
them stays with you.
