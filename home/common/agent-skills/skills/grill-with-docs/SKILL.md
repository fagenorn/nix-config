---
name: grill-with-docs
description: Stress-test a plan against the project's domain docs — challenges terminology and decisions, updates the glossary and ADRs inline as decisions crystallise.
---

<what-to-do>

Interview me relentlessly about every aspect of this plan until we reach a shared understanding. Walk down each branch of the design tree, resolving dependencies between decisions one-by-one. For each question, provide your recommended answer.

Ask the questions one at a time, waiting for feedback on each question before continuing.

If a question can be answered by exploring the codebase, explore the codebase instead.

</what-to-do>

<supporting-info>

## Domain awareness

During codebase exploration, also look for existing documentation.

**Doc locations are adaptive.** Don't impose `docs/adr/` or `CONTEXT.md` on a repo that already has its own conventions. Detect what the project already uses and follow it:

- **Glossary / context file** — look for `CONTEXT.md` first, then common alternatives at the repo root (`GLOSSARY.md`, `DOMAIN.md`, `docs/CONTEXT.md`, `docs/glossary.md`). Use whatever exists.
- **Decision records** — look for `docs/adr/`, then `docs/decisions/`, `doc/adr/`, `adr/`, or an `RFCs/` directory. Use whatever exists. If a project keeps decisions in some other documented place, follow that.

If `.claude/skills.config.json` exists at the project root, it may name these explicitly under `docPaths` (e.g. `docPaths.context`, `docPaths.adrDir`) — prefer those when present. Only fall back to the default layout below when neither config nor detection yields a location.

### File structure

Most repos have a single context:

```
/
├── CONTEXT.md
├── docs/
│   └── adr/
│       ├── 0001-event-sourced-orders.md
│       └── 0002-postgres-for-write-model.md
└── src/
```

If a `CONTEXT-MAP.md` exists at the root, the repo has multiple contexts. The map points to where each one lives:

```
/
├── CONTEXT-MAP.md
├── docs/
│   └── adr/                          ← system-wide decisions
├── src/
│   ├── ordering/
│   │   ├── CONTEXT.md
│   │   └── docs/adr/                 ← context-specific decisions
│   └── billing/
│       ├── CONTEXT.md
│       └── docs/adr/
```

Create files lazily — only when you have something to write. If no glossary/context file exists, create one when the first term is resolved (named to match the project's convention, or `CONTEXT.md` by default). If no decision-record directory exists, create it when the first ADR is needed (matching the project's convention, or `docs/adr/` by default).

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

### Update the glossary inline

When a term is resolved, update the glossary/context file right there. Don't batch these up — capture them as they happen. Use the format in [CONTEXT-FORMAT.md](./CONTEXT-FORMAT.md).

Don't couple the glossary to implementation details. Only include terms that are meaningful to domain experts.

### Offer ADRs sparingly

Only offer to create an ADR when all three are true:

1. **Hard to reverse** — the cost of changing your mind later is meaningful
2. **Surprising without context** — a future reader will wonder "why did they do it this way?"
3. **The result of a real trade-off** — there were genuine alternatives and you picked one for specific reasons

If any of the three is missing, skip the ADR. Use the format in [ADR-FORMAT.md](./ADR-FORMAT.md).

</supporting-info>
