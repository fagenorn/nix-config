---
name: grill-with-docs
description: Stress-test a plan against the project's domain docs — challenges terminology and decisions, updates the glossary and ADRs inline as decisions crystallise.
---

<what-to-do>

Interview me relentlessly about every aspect of this plan until we reach a shared understanding. Model the design as a tree of decisions; the **frontier** is every question whose prerequisites are already settled.

Ask the whole frontier as one numbered round of `❓ question / ➡️ recommended answer` pairs. A question whose answer depends on another question still open in this round belongs to a later round. The round's answers reshape the tree — recompute the frontier and ask the next round; done when it's empty.

When every question in a round carries a ➡️ recommendation, say so once, at the first round: they may
reply with only the numbers they'd change, and anything they don't name adopts its recommendation and
is recorded as a decision exactly as if they had typed it. A well-defaulted round then costs one short
reply instead of a line of assent per question. The decisions stay theirs — the offer is made in the
open, and any number they name overrides.

Three kinds of question never ride on silence: anything that redraws the destination or the scope,
anything hard to reverse, and anything that spends money or hands out a credential. Mark those in the
round and wait for an answer in words, however many rounds it costs.

If a question can be answered by exploring the codebase or docs, explore instead of asking — dispatch the lookup without blocking the round (only the questions downstream of it wait). The decisions are mine; the facts are yours.

</what-to-do>

<supporting-info>

## Domain awareness

During codebase exploration, also look for existing documentation. Read a long one by section, not whole: past ~400 lines, grep its headings first and open only the sections that govern what you're grilling — `doc-grounded-questions` step 4 owns this rule.

**Detect the layout before writing anything**, in this order:

1. **The standard** — `docs/CONTEXT-MAP.md` plus `docs/areas/`. Areas and their decisions live under `docs/areas/<slug>/`; that is the tree below and the one to create in a repo that has nothing yet.
2. **Legacy conventions** — a root `CONTEXT-MAP.md` with area files beside the code, or flat `docs/<slug>/` areas beside a central `docs/adr/`. For a glossary: `CONTEXT.md`, `GLOSSARY.md`, `DOMAIN.md`, `docs/CONTEXT.md`, `docs/glossary.md`. For decisions: `docs/adr/`, `docs/decisions/`, `doc/adr/`, `adr/`, `RFCs/`. Follow what the repo has; don't impose the standard tree on it mid-flight.
3. **`.claude/skills.config.json`** may name paths explicitly under `docPaths` (e.g. `docPaths.context`, `docPaths.contextMap`) — prefer those when present. `docPaths.adrDir` is a legacy override: where the map has areas, each area owns its own `adr/`.

### File structure

The steady state is contained in `docs/`: a map plus one directory per area under `areas/`:

```
/
└── docs/
    ├── README.md                     ← routing index for everything in docs/
    ├── CONTEXT-MAP.md                ← index: areas, governs globs, term → area
    └── areas/
        ├── system/                   ← decisions no single area owns
        │   ├── CONTEXT.md            ←   a stub; its map row governs `*`
        │   └── adr/
        ├── ordering/
        │   ├── CONTEXT.md            ← glossary for this area only
        │   └── adr/                  ← this area's decisions, NNN-kebab.md
        └── billing/
            ├── CONTEXT.md
            └── adr/
```

`standards/`, `operations/`, `guides/` and `archive/` are the other reserved directories — see [CONTEXT-FORMAT.md](./CONTEXT-FORMAT.md) for the full tree. ADR numbering is **per directory** (`ADR-<slug>-NNN`), so an area's records never collide with another's.

A young repo may still be a single `docs/CONTEXT.md` (or legacy root `CONTEXT.md`) with no map; that is fine, and the first split creates the map.

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
