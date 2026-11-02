# Context Map & Area Glossary Format

Domain knowledge lives as a **map plus area glossaries**. The map is an index, never a store: it names the areas, the paths each governs, and the area that owns each term; definitions live in the area files. Readers load the map every time and open only the areas whose `governs:` globs intersect the paths they touch. Use only the caller-selected map from `bindings.paths.context`; never read configuration or discover a location.

## Contents

- Illustrative layout (below)
- The map
- Area glossary
- Repos without a map yet
- Linting

**Illustrative layout**, for a selected map in `docs/`: the docs root holds only `README.md` (the routing index) and `CONTEXT-MAP.md`; everything else sits in a reserved directory.

```
docs/
├── README.md            ← routing index: every entry + where new knowledge goes
├── CONTEXT-MAP.md       ← the map (≤150 lines); links ./areas/<slug>/CONTEXT.md
├── areas/
│   ├── system/          ← reserved pseudo-area: decisions no single area owns
│   │   ├── CONTEXT.md   ←   a stub; its map row carries governs `*`
│   │   └── adr/
│   └── <slug>/
│       ├── CONTEXT.md   ← budgeted glossary for this area only
│       └── adr/
│           └── NNN-kebab-title.md
├── standards/           ← Layer-2 project deltas + ≤40-line README index
├── operations/          ← runbooks
├── guides/              ← architecture.md and the rest of the how-to prose
└── archive/             ← dormant or superseded material
```

The reserved directories are created only when needed. Every directory under `areas/` is an area with a row in the map's Areas table, and every row points into `areas/`. An extra docs-root directory needs a row in `docs/README.md`'s routing table. `areas/system/` holds decisions spanning areas: its map row has gist "decisions spanning areas" and glob `*`, and its `CONTEXT.md` stays a stub because every grounding pass loads it. There is no central `docs/adr/`. Specs, plans, handoffs and notes are not documentation: they go to their retained `bindings.paths.artifacts` locations.

The Order / Invoice / Customer names below are illustrative.

## The map: `<selected-context-map>`

**Hard budget: 150 lines.** Three tables and nothing else.

```md
# Context Map

## Areas

| Area | Context file | Gist | governs |
|---|---|---|---|
| Ordering | [CONTEXT](./areas/ordering/CONTEXT.md) | Receives and tracks customer orders | `src/ordering/**` |
| Billing | [CONTEXT](./areas/billing/CONTEXT.md) | Raises invoices and settles payments | `src/billing/**`, `src/api/invoices/**` |
| System | [CONTEXT](./areas/system/CONTEXT.md) | Decisions spanning areas | `*` |

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

- A gist is one line of twelve words or fewer.
- `governs:` globs are the load trigger: each matches at least one real path from the repo root, and they live only here, never restated in the area file.
- Context-file links are map-relative: `./areas/<area-slug>/CONTEXT.md`.
- Every term an area defines appears exactly once in Terms, sorted, with its owning area and no definition. A term with two homes is a modelling bug to resolve.
- `## Relationships` carries cross-area edges only.

## Area glossary: `CONTEXT.md`

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

- Glossary only: nothing that goes stale when the code changes (no implementation, spec, notes or decision log).
- Each definition is one or two sentences on what the term *is*.
- `_Avoid_:` is mandatory whenever rival names circulate.
- Only concepts unique to this domain; general programming concepts (timeouts, retries, error types) stay out.
- Group under `###` subheadings when clusters emerge.
- At most one example dialogue per area, at most ten lines, only when two terms resist definition.

Mark an open ambiguity inline on the disputed term and delete the marker in the commit that settles it; there is no "flagged ambiguities" log:

```md
**Account**:
_Ambiguous_: used for both **Customer** and **User**. Unresolved.
```

A writer that pushes the map or an area past its budget consolidates or splits in the same commit; the split procedure is in [SKILL.md](./SKILL.md).

## Repos without a map yet

Start with a single `docs/CONTEXT.md` (or a legacy root `CONTEXT.md`) in the area format, created when the first term resolves; the first split creates the map. Readers without a map read that whole file.

## Linting

`~/.agents/bin/context-map-lint --repo-root <absolute checkout root> --context-map <selected map path>` checks term resolution, budgets, globs, links and, once `docs/areas/` exists, the layout and ADR ids above. Fix what it reports, and wire it into CI.
