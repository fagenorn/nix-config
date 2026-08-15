---
name: design
description: Turn an idea or issue into an approved design doc by grilling the open questions in batched rounds. Use to brainstorm, design, or spec before planning.
---

# Design

Turn an idea into a design doc the plan phase can execute from. You own the interview and the spec; the caller owns planning, review, and execution.

## The interview — round-batched frontier

Model the design as a tree: every decision branches into the decisions hanging off it. The **frontier** is every question whose prerequisites are already settled — the ones you can ask *now* without guessing at an answer you haven't heard yet.

Ask the whole frontier in one numbered round:

```
❓ **Q1** — **<short title>**: <the question, with the choices when there are choices>

➡️ <your recommended answer>
```

- One round carries every askable question. A question whose answer depends on another question still open in this round belongs to a *later* round.
- Every question carries a `➡️` recommendation. Committing to a defensible default before you hear the user's lean is the discipline, not decoration.
- The round's answers reshape the tree — settled decisions push the frontier outward. Recompute it and ask the next round.
- Done when the frontier is empty: every branch visited, nothing silently assumed.

**Facts are your job, never the user's.** When a frontier question needs a sharply bounded fact from the environment — filesystem, tooling, library behavior, prior art in the codebase — resolve it yourself. Keep a small direct grep or file check inline: a trivial repository fact (does the file exist, what is the symbol's signature) is answered locally, not delegated. Only when the result set needs a sharply bounded read-only exploration pass, use the explorer below. When the answer needs cited primary sources, invoke `research`; that skill owns its own marked background launch.

<!-- agent-dispatch: id=design-bounded-fact-lookup role=explorer model=haiku effort=medium -->
Agent(subagent_type="Explore", model="haiku", effort="medium") performs one sharply bounded read-only fact lookup without making the design decision.

Don't block on it: an in-flight lookup is an unsettled prerequisite, so only the questions downstream of it wait; ask the rest of the frontier now. The *decisions* are the user's. If the lookup becomes open-ended, ambiguous, or judgment-bearing, stop the cheap-tier run and re-dispatch the `issue-owner` on Opus/high; record that escalation and selected role in the phase's existing fixed-schema report.

**Ground before round 1.** Invoke `doc-grounded-questions`, or read this phase's `GROUNDING.md` cache when the caller already built one. A question the project's docs already answer is not a question — state the answer, cite it, move on.

## Autonomous mode

When the caller runs autonomously (`from-issue --auto`), **the `➡️` recommendation is the answer.** Don't post the round and don't wait: resolve each question with its recommendation and record it in the spec's `## Decision ledger` (see Output). Log only non-obvious decisions — scope, interface, behavioral, test-seam, irreversible, user-preference; skip routine task splits, commit boundaries, obvious verification commands, and mechanical pattern-following. Consolidation is permitted and encouraged: related decisions merge into one row. Rounds still run in order; the frontier is what keeps dependent decisions from being settled out of sequence.

## Guards

- **Synthesize, never re-interview.** Everything the rounds and the caller's earlier phases settled goes into the spec as a decision. Re-asking a settled question is the failure this skill exists to prevent.
- **Agree the test seams before the spec is written.** Name the public boundaries this work will be tested at. Prefer existing seams, prefer the highest seam, keep them few. The plan and every implementer inherit these seams and may not invent others.
- **YAGNI.** Strip from every option the configuration, abstraction and future-proofing nobody asked for.
- **Scope check first.** If the request is several independent subsystems, say so before spending questions on detail: decompose it, design the first piece, hand the rest to `to-issues`.

## Output

Write the design to `<specDir>/<YYYY-MM-DD>-<topic>-design.md` (`specDir` from `.claude/skills.config.json`, default `.claude/specs`) and commit it in the worktree you were called in — never on the integration branch.

Sections: **Problem** (from the user's perspective) · **Solution** · **Decisions** (modules and interfaces touched, schema and API contracts, behavior — no file paths or line numbers; they rot) · **Test seams** (the agreed seams and the prior art they follow) · **Out of scope** (mandatory, and real) · **Decision ledger** — the issue's single decision store, a table later phases cite by row ID instead of restating rationale:

```markdown
| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | <what was decided, one line> | <doc/standard/user statement it rests on> | <the alternative and why not, one line> |
```

Only non-obvious decisions earn a row (scope, interface, behavioral, test-seam, irreversible, user-preference — self-answered or user-answered); plans and task briefs cite "per D3" rather than duplicating the row.

Then read the file once with fresh eyes and fix inline: placeholders (`TBD`, "handle edge cases"), sections that contradict each other, requirements that can be read two ways, scope that needs decomposing. No reviewer dispatch — this is your own pass.

## Return control

Report to the caller: the spec path, any ADR paths, one line per auto-resolved decision, and ≤500 characters of notes for anything the plan phase must know. Details stay in the committed file. Do not invoke `writing-plans`, do not start implementing, and do not offer to — the caller owns the next phase.
