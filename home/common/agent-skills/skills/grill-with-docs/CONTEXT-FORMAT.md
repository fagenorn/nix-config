# Context Map & Area Glossary Format

Domain knowledge lives as a **map plus area glossaries**. The map is an index, never a store: it names the areas, the paths each one governs, and which area owns each term. The definitions live in the area files. Readers load the map every time (cheap) and open only the area files whose `governs:` globs intersect the paths they are touching.

**Location: contained in `docs/`.** Prefer `.claude/skills.config.json`'s `docPaths.contextMap` / `docPaths.context` when set; otherwise `docs/CONTEXT-MAP.md`, with one directory per area — `docs/<area-slug>/CONTEXT.md` for the glossary and `docs/<area-slug>/adr/` for that area's decisions. System-wide decisions stay in `docs/adr/`; all ADR directories share one numbering sequence, and a record keeps its filename if it ever moves. (A root `CONTEXT-MAP.md` with code-colocated area files is the legacy layout — follow it where a repo still uses it.)

> The Order / Invoice / Customer names below are illustrative DDD samples — substitute the project's real terms.

## `docs/CONTEXT-MAP.md` — the index

**Hard budget: 150 lines.** Three tables and nothing else.

```md
# Context Map

## Areas

| Area | Context file | Gist | governs |
|---|---|---|---|
| Ordering | [CONTEXT](./ordering/CONTEXT.md) | Receives and tracks customer orders | `src/ordering/**` |
| Billing | [CONTEXT](./billing/CONTEXT.md) | Raises invoices and settles payments | `src/billing/**`, `src/api/invoices/**` |

## Terms

| Term | Area |
|---|---|
| Customer | Ordering |
| Invoice | Billing |
| Order | Ordering |

## Relationships

- **Ordering → Billing**: Ordering emits `OrderPlaced`; Billing consumes it to raise an **Invoice**.
- **Ordering ↔ Billing**: shared `CustomerId` and `Money` types.
```

Rules for the map:

- **The gist is one line, twelve words or fewer.** It exists so a reader can decide whether to open the file, not so they can skip opening it.
- **`governs:` globs are the load trigger.** Every glob must match at least one real path, resolved from the repo root (the map lives in `docs/`, but the globs point at code). They live here and only here — an area file does not restate its own globs.
- **Context-file links are map-relative**: `./<area-slug>/CONTEXT.md`, a sibling directory of the map.
- **Every term defined in an area file appears exactly once in the Terms table**, sorted alphabetically. The table carries the term and its owning area, never a definition — a term with two homes is a modelling bug to resolve, not a row to duplicate.
- **`## Relationships` carries cross-area edges only.** Cardinality and event flow between areas; anything internal to one area belongs in that area's file.

## Per-area `CONTEXT.md` — glossary only

```md
---
area: Ordering
budget: 200 lines
---

# Ordering

One or two sentences on what this area is and why it exists.

## Language

**Order**:
A confirmed, priced request to buy, owned by exactly one Customer.
_Avoid_: Purchase, transaction

**Customer**:
A person or organisation that places Orders and is billed for them.
_Avoid_: Client, buyer, account
```

Rules for area files:

- **Glossary and nothing else.** No implementation details, no spec, no scratch notes, no decision log. If it would go stale when the code changes, it does not belong here.
- **Definitions are one to two sentences.** Define what the term *is*, not what it does.
- **`_Avoid_:` is mandatory whenever rival names circulate.** Picking the winner and naming the losers is what stops the vocabulary drifting; be opinionated.
- **Admission test:** is this concept unique to this project's domain, or a general programming concept? Only the former belongs — timeouts, retries, error types and utility patterns stay out however heavily the project uses them.
- **Group under `###` subheadings** when natural clusters emerge; a flat list is fine for a cohesive area.
- **Example dialogue is optional, at most one per area, at most ten lines.** Write one only when the boundary between two terms is genuinely hard to state as definitions.

## Decisions ride with their area

An ADR that concerns exactly one area lives in that area's `docs/<area-slug>/adr/`; a decision spanning areas (or the whole system) lives in `docs/adr/`. One numbering sequence covers every ADR directory, so an id is unambiguous without its path. When an accepted record moves, it keeps its filename, moves through the VCS's own move, and every *living* reference is re-pointed in the same commit — historical citations inside other accepted records are part of those records and stay as written.

## Delete on resolve

An ambiguity is flagged *while it is open* and removed the moment it closes — the resolution lives in the winning term's definition (and its `_Avoid_:` line) or in an ADR, never in a permanent log. There is no "Flagged ambiguities" section: a list that only grows is a second, worse copy of the glossary.

Mark an open ambiguity inline on the disputed term and delete the marker in the same commit that settles it:

```md
**Account**:
_Ambiguous_: used for both **Customer** and **User**. Unresolved.
```

## Net-neutral writes

Both files carry a hard budget (150 lines for the map, the front-matter `budget:` for each area). **A writer that pushes a file past its budget consolidates or splits in the same commit** — never "just this once", never a follow-up TODO. In practice a glossary at budget means either several entries have grown past two sentences and should be tightened, or the area covers two things and should become two areas. The split procedure lives in [SKILL.md](./SKILL.md).

This is what keeps grounding cost flat as the project ages: every issue adds terms, so every issue must also pay down.

## Repos without a map yet

A new repo may begin with a single `docs/CONTEXT.md` (or legacy root `CONTEXT.md`) in the area-file format above; create it lazily, when the first term resolves. The first split creates the map. Readers fall back to reading the whole file when no `CONTEXT-MAP.md` exists, so a repo mid-migration always works.

## Linting

`~/.agents/bin/context-map-lint <repo-root>` checks every term resolves to an area file that defines it, every file is within budget, every `governs:` glob matches something, and every relative link in the map resolves. Wire it into CI — a citation linter is the only anti-drift measure that has been observed to hold.
