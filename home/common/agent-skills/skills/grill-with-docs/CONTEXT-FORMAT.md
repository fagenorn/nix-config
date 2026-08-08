# Context Map & Area Glossary Format

Domain knowledge lives as a **map plus area glossaries**. The map is an index, never a store: it names the areas, the paths each one governs, and which area owns each term. The definitions live in the area files. Readers load the map every time (cheap) and open only the area files whose `governs:` globs intersect the paths they are touching.

**Location: contained in `docs/`.** The docs root holds exactly two loose files — `README.md`, the routing index, and `CONTEXT-MAP.md`, the map. Everything else lives in a reserved directory:

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

`areas/`, `standards/`, `operations/`, `guides/` and `archive/` are **reserved, not required** — create one when you have something to put in it. A directory under `areas/` *is* an area, so every area directory needs a row in the map's Areas table and every Areas row must point into `areas/`. A project-specific extra directory at the docs root is allowed only when `docs/README.md`'s routing table carries a row for it.

`docs/areas/system/` is the reserved pseudo-area for decisions that belong to no single area. Its map row is real — gist "decisions spanning areas", `governs:` glob `*` — and its `CONTEXT.md` is a stub of a few lines, because every grounding pass loads it. **There is no central `docs/adr/`**: every ADR lives in exactly one `docs/areas/<slug>/adr/`, so tooling has one shape and no special cases.

Prefer `.claude/skills.config.json`'s `docPaths.contextMap` / `docPaths.context` when set. (Two legacy layouts survive where a repo still uses them — a root `CONTEXT-MAP.md` with code-colocated area files, and flat `docs/<slug>/` areas beside a central `docs/adr/`. Follow what a repo actually has rather than imposing this tree on it mid-migration.)

Skill output is not documentation and does not live here: specs, plans, handoffs and notes go to `.claude/specs/`, `.claude/plans/`, `.claude/handoffs/`, `.claude/notes/`.

> The Order / Invoice / Customer names below are illustrative DDD samples — substitute the project's real terms.

## `docs/CONTEXT-MAP.md` — the index

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

Rules for the map:

- **The gist is one line, twelve words or fewer.** It exists so a reader can decide whether to open the file, not so they can skip opening it.
- **`governs:` globs are the load trigger.** Every glob must match at least one real path, resolved from the repo root (the map lives in `docs/`, but the globs point at code). They live here and only here — an area file does not restate its own globs.
- **Context-file links are map-relative**: `./areas/<area-slug>/CONTEXT.md`.
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

Every ADR lives in exactly one `docs/areas/<slug>/adr/` — the area it concerns, or `system` when it spans areas or belongs to none. Numbering is **per directory**: `NNN-kebab-title.md`, three digits, each directory running its own sequence from `001`. A new record takes the next free number in its directory at merge time.

The id is `ADR-<area-slug>-NNN`: the slug of the containing directory plus the filename's number, and the header line restates it. **The full id is the only citation form, everywhere** — no bare short forms, not even inside the record's own area. It is a single grep token, and it is lexically disjoint from the old four-digit `ADR-NNNN` form, so ids left behind by a migration stay mechanically detectable. There is no global sequence and no cross-directory uniqueness to maintain.

When an accepted record moves to another area, it takes the destination directory's next free number and gains a `- **Formerly:** ADR-<old-slug>-NNN` line; the move goes through the VCS's own move, and every *living* reference is re-pointed in the same commit. Historical citations inside other accepted records are part of those records and stay as written — the `Formerly` line is what carries identity across the move.

Nobody hand-maintains an ADR index: a sorted `ls` of an `adr/` directory indexes itself, and the map's Areas table is the directory of directories. Record mechanics — the shape of a record, the admission gate, the parallel-session collision rule — live in [ADR-FORMAT.md](./ADR-FORMAT.md).

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

`~/.agents/bin/context-map-lint <repo-root>` checks that every term resolves to an area file that defines it, every file is within budget, every `governs:` glob matches something, and every relative link in the map resolves.

Once `docs/areas/` exists it also enforces the layout above:

- every directory under `docs/areas/` is the target of an Areas row, and every Areas row resolves under `docs/areas/`;
- ADR filenames are `NNN-kebab-title.md`, the number is unique within its directory, and the header is `# ADR-<slug>-NNN — Title` with the slug and number matching the file's home;
- every `ADR-<slug>-NNN` cited anywhere under `docs/` resolves to a record that exists;
- no four-digit `ADR-NNNN` survives under `docs/`, except on a `- **Formerly:**` line or inside `docs/archive/`;
- the docs root carries nothing but `README.md`, `CONTEXT-MAP.md`, the reserved directories, and whatever `docs/README.md` routes.

A repo still on a legacy layout keeps passing exactly as before — these checks activate only where `docs/areas/` is present. Wire it into CI — a citation linter is the only anti-drift measure that has been observed to hold.
