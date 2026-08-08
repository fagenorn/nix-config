---
name: grill-with-docs
description: Stress-test a plan against the project's domain docs — challenges terminology and decisions, updates the glossary and ADRs inline as decisions crystallise.
---

<what-to-do>

Interview me relentlessly about every aspect of this plan until we reach a shared understanding. Model the design as a tree of decisions; the **frontier** is every question whose prerequisites are already settled.

Ask the whole frontier as one numbered round of `❓ question / ➡️ recommended answer` pairs. A question whose answer depends on another question still open in this round belongs to a later round. The round's answers reshape the tree — recompute the frontier and ask the next round; done when it's empty.

If a question can be answered by exploring the codebase or docs, explore instead of asking — dispatch the lookup without blocking the round (only the questions downstream of it wait). The decisions are mine; the facts are yours.

</what-to-do>

<supporting-info>

## Domain awareness

During codebase exploration, also look for existing documentation.

**Doc locations are adaptive.** Don't impose `docs/adr/` or `CONTEXT.md` on a repo that already has its own conventions. Detect what the project already uses and follow it:

- **Glossary / context file** — look for `CONTEXT.md` first, then common alternatives at the repo root (`GLOSSARY.md`, `DOMAIN.md`, `docs/CONTEXT.md`, `docs/glossary.md`). Use whatever exists.
- **Decision records** — look for `docs/adr/`, then `docs/decisions/`, `doc/adr/`, `adr/`, or an `RFCs/` directory. Use whatever exists. If a project keeps decisions in some other documented place, follow that.

If `.claude/skills.config.json` exists at the project root, it may name these explicitly under `docPaths` (e.g. `docPaths.context`, `docPaths.adrDir`) — prefer those when present. Only fall back to the default layout below when neither config nor detection yields a location.

### File structure

The steady state is a root map plus one glossary per area:

```
/
├── CONTEXT-MAP.md                    ← index: areas, governs globs, term → area
├── docs/adr/                         ← system-wide decisions
└── src/
    ├── ordering/CONTEXT.md           ← glossary for this area only
    └── billing/CONTEXT.md
```

A young repo may still be a single root `CONTEXT.md` with no map; that is fine, and the first split creates the map. Some repos also keep area-scoped `src/<area>/docs/adr/` — follow that if it exists, otherwise keep ADRs central.

Create files lazily — only when you have something to write. If no glossary exists, create one when the first term resolves (named to match the project's convention, `CONTEXT.md` by default). If no decision-record directory exists, create it when the first ADR is needed.

> The Order / Invoice / Customer / Fulfillment names used throughout these docs are illustrative DDD samples — substitute your project's actual domain terms.

## During the session

### Challenge against the glossary

When the user uses a term that conflicts with the existing language in the glossary, call it out immediately. "Your glossary defines 'cancellation' as X, but you seem to mean Y — which is it?"

### Sharpen fuzzy language

When the user uses vague or overloaded terms, propose a precise canonical term. "You're saying 'account' — do you mean the Customer or the User? Those are different things."

### Discuss concrete scenarios

When domain relationships are being discussed, stress-test them with specific scenarios. Invent scenarios that probe edge cases and force the user to be precise about the boundaries between concepts.

### Cross-reference with code

When the user states how something works, check whether the code agrees. If you find a contradiction, surface it: "Your code cancels entire Orders, but you just said partial cancellation is possible — which is right?"

### Update the glossary inline, net-neutral

When a term resolves, write it into the owning area's glossary right there, and add its row to the map's term table. Use the format in [CONTEXT-FORMAT.md](./CONTEXT-FORMAT.md). Only terms meaningful to a domain expert; never implementation details.

Two disciplines make this sustainable — both are same-commit obligations, never follow-ups:

**Delete on resolve.** An ambiguity marker is removed the moment the ambiguity closes; the resolution lives in the winning term's definition and its `_Avoid_:` line, or in an ADR. Never leave a growing log of settled questions.

**Net-neutral writes.** If your addition pushes a file past its budget (150 lines for the map, the front-matter `budget:` for an area file), consolidate or split before you finish. Consolidate first: entries that grew past two sentences, near-duplicate terms that should be one term with aliases, an example dialogue the definitions have made redundant. Split only when the area genuinely covers two things.

**Splitting an area** — four edits, one commit:

1. Create the new area file with front-matter (`area:`, `budget: 200 lines`), its one-or-two-sentence purpose, and the terms moving out — moved verbatim, not rewritten, so nothing is silently lost.
2. Delete those terms from the old file.
3. Add a row to the map's `## Areas` table: name, link, one-line gist, and `governs:` globs. Narrow the old area's globs to match what it still owns.
4. Repoint the moved terms' rows in the map's `## Terms` table, and add any new cross-area edge to `## Relationships`.

Then run `~/.agents/bin/context-map-lint .` — it catches a term left pointing at the old area, a glob matching nothing, and a file still over budget.

### Offer ADRs sparingly

Only offer to create an ADR when all three are true:

1. **Hard to reverse** — the cost of changing your mind later is meaningful
2. **Surprising without context** — a future reader will wonder "why did they do it this way?"
3. **The result of a real trade-off** — there were genuine alternatives and you picked one for specific reasons

If any of the three is missing, skip the ADR. Use the format in [ADR-FORMAT.md](./ADR-FORMAT.md).

</supporting-info>
