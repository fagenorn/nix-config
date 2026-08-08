# Docs directory standard, per-directory ADR numbering, and the end of the central ADR dir

Interview date: 2026-08-08. All decisions user-confirmed in two AskUserQuestion rounds
(grounding: `.claude/specs/GROUNDING.md`). This supersedes `CONTEXT-FORMAT.md`'s current
§Location and §Decisions-ride-with-their-area clauses "one numbering sequence" and
"a record keeps its filename".

## Problem

Both migrated repos (nodo, argus) share a `docs/` layout where 13/11 area directories sit
directly beside `operations/`, `superpowers/`, `standards/`, `archive/`, and loose `.md`
files — "a bit of a mess": nothing distinguishes an area from a utility dir without
consulting the map. ADRs live in a special-cased central `docs/adr/` plus per-area `adr/`
dirs under one global numbering sequence whose serial collisions under parallel sessions
are documented, recurring pain (nodo: six collisions, one failed reservation scheme).
There is no written standard a third project could adopt.

## Solution

One standard tree, spec'd normatively in nix-config and applied to nodo, argus, and every
future project:

```
docs/
├── README.md          # routing index: table of every entry + "where new knowledge goes"
├── CONTEXT-MAP.md     # the map (≤150 lines); links ./areas/<slug>/CONTEXT.md
├── areas/
│   ├── system/        # reserved pseudo-area: decisions no single area owns
│   │   ├── CONTEXT.md #   minimal stub; map row carries governs `*`
│   │   └── adr/
│   └── <slug>/
│       ├── CONTEXT.md # budgeted glossary (unchanged format)
│       └── adr/
│           └── NNN-kebab-title.md
├── standards/         # Layer-2 deltas + ≤40-line README index (unchanged)
├── operations/        # runbooks (reserved, not required)
├── guides/            # architecture.md + all repo how-to prose
└── archive/           # dormant/superseded material; holds adr-id-map.md
```

Skill output (specs, plans, handoffs, notes) leaves `docs/` entirely:
`.claude/{specs,plans,handoffs,notes}/` — the tool defaults.

ADR ids become per-directory: `ADR-<area-slug>-NNN` (3-digit, per-dir sequence from 001).
Every existing record is renumbered, every reference in both repos rewritten, and GitHub
issue/PR bodies **and comments** are swept post-merge to fix both old ids and moved file
paths. Continuity: a `- **Formerly:** ADR-0042` line on every migrated record plus a
committed old→new table per repo.

## Decisions

### D1 — Areas are namespaced under `docs/areas/<slug>/`

A directory under `areas/` **is** an area; the linter flags orphans (dir without a map
row) in both directions. The map stays at `docs/CONTEXT-MAP.md` and links
`./areas/<slug>/CONTEXT.md`. Area-file format, budgets (map 150 / area 200 default),
terms, and `governs:` rules are unchanged.

### D2 — The docs root holds exactly two loose files

`README.md` (routing index) and `CONTEXT-MAP.md`. Everything else lives in a reserved
dir: `areas/`, `standards/`, `operations/`, `guides/`, `archive/` — reserved, not
required. `architecture.md` and other how-to prose (devenv, git-and-worktrees,
workflow-shapes) move to `guides/`, with `docPaths` keys repointed. A project-specific
extra dir is allowed only with a row in `docs/README.md`'s routing table.

### D3 — The central ADR dir dies; `system` is a uniform pseudo-area

`docs/areas/system/` holds decisions no single area owns (nodo 16, argus 19 — membership
carried over unchanged from the previous migration's classification; no re-homing now).
Its map row is real: gist "decisions spanning areas", `governs:` glob `*` (system-wide
decisions apply everywhere; the stub CONTEXT.md this loads on every grounding pass is a
few lines). Rule after this change: **every ADR lives in exactly one
`docs/areas/<slug>/adr/`** — tooling has one shape, no special cases.

### D4 — Id grammar: `ADR-<area-slug>-NNN`

- Filename `NNN-kebab-title.md`; NNN is 3 digits, zero-padded, per-directory sequence
  starting 001 (largest dir today holds 49 records).
- Header line: `# ADR-<slug>-NNN — Title`; slug must equal the containing dir's slug,
  NNN must equal the filename number (linted).
- The full id is the only citation form, everywhere — no bare short forms even within
  the record's own area. It is a single grep token and lexically disjoint from the old
  `ADR-\d{4}` form, so stale old-style ids stay mechanically detectable forever.
- Renumber assignment: within each destination dir, old records are ordered by old
  serial ascending and assigned 001, 002, … — chronology preserved per dir.
- New-record procedure: next free NNN in that dir at merge time. Parallel-session
  collisions (now possible only within one area) keep nodo's proven rule: first branch
  to the integration branch keeps the number; the later branch renumbers itself and its
  own citations before merge.
- Cross-dir moves later: the record takes the destination dir's next number and gains a
  `- **Formerly:** ADR-<old-slug>-NNN` line; living references are re-pointed in the
  same commit. (This replaces "a record keeps its filename".)

### D5 — Continuity: Formerly lines + committed id-map + GitHub sweep

- Every migrated record gets `- **Formerly:** ADR-0042` immediately after its
  `- **Status:**` line — a repo grep for any old id (e.g. from the 303 nodo + 470 argus
  immutable commit subjects) lands on the successor.
- One committed table per repo at `docs/archive/adr-id-map.md`: old id → new id
  (linked to the new file). It drives the sweep and audits the migration.
- **Full GitHub sweep, post-merge, per repo**: issue + PR bodies AND all comments, open
  and closed (625 nodo items, 4 argus items mention ADR ids). Rewrites (a) old ADR ids →
  new ids via the id-map, (b) moved file paths → new paths (`docs/<area>/…` →
  `docs/areas/<area>/…`, `docs/adr/<old>.md` → the record's new path from the id-map,
  `docs/superpowers/…` → `.claude/…`). Throttled `gh api` script committed under each
  repo's `scripts/`; **dry-run diff reviewed by the user before apply**. nodo: prefix
  `unset GITHUB_TOKEN`; argus PAT's missing checks scope is irrelevant to issues API.

### D6 — Citation rewrite: everything, once

Every ADR citation in both repos — markdown links and bare prose serials, inside
accepted records included — becomes the new id in the migration commit (~2,100 nodo +
~3,700 argus source-comment lines; ~1,300 + ~4,900 doc lines; nodo's
`dotnet-tests.yml` ADR-0020 job name/comment/error strings). **Exception — historical
records keep their original text**: repo-root `LAYOUT-NOTES.md`/`MIGRATION-NOTES.md`
and `docs/archive/**` are records of what happened, not living references (they are
also outside the linter's stale-id guard). Afterwards the old convention resumes:
historical citations inside accepted records stay as written; Formerly lines carry
identity through future moves.

### D7 — No hand-maintained ADR indexes; no template files

`docs/adr/README.md` (both repos) is deleted, not relocated: sorted `ls` of each `adr/`
dir self-indexes; the map's Areas table is the directory of directories. The collision
procedure moves into `CONTEXT-FORMAT.md`. `0000-template.md` is deleted in both repos —
the record shape (header + Status/Date/Deciders bullets, `Formerly` only on migrated or
moved records, 1–3 sentence body, admission gate unchanged: hard-to-reverse AND
surprising AND real-trade-off) is documented in `CONTEXT-FORMAT.md`, which every agent
has deployed globally.

### D8 — Skill output moves to `.claude/`

`docs/superpowers/` → `.claude/specs/`, `.claude/plans/`, `.claude/handoffs/`,
`.claude/notes/` (nodo: 1,213 files; argus: ~100 — moved wholesale, tracked in git).
nodo's `specDir`/`planDir` config keys are removed (defaults take over). Old GitHub
links into `docs/superpowers/` are fixed by the D5 sweep. nodo's `.gitignore` ignores
`.claude/*` with a `hints/` whitelist — the migration adds `!.claude/specs/`,
`!.claude/plans/`, `!.claude/handoffs/`, `!.claude/notes/` so the moved files stay
versioned (argus tracks `.claude/` already). nodo's `skills.config.json` stays
untracked as today — flagged to the user, not changed here.

### D9 — Normative spec + tooling changes (nix-config)

- `skills/grill-with-docs/CONTEXT-FORMAT.md`: rewrite §Location (D1/D2/D3 tree),
  rewrite §Decisions-ride-with-their-area (D3/D4/D5 mechanics: id grammar, Formerly,
  collision rule, move rule, no indexes, record shape), update the map example's links
  to `./areas/…`, update §Linting for the new checks.
- `home/common/agent-skills/README.md` adapter table: Domain-language row
  (`docs/areas/<area>/CONTEXT.md`), Decisions row (per-area `adr/` incl. `system`; id
  grammar `ADR-<slug>-NNN`; per-dir numbering).
- `scripts/context-map-lint.py` gains: (1) bidirectional area↔map-row agreement for
  `docs/areas/*`; (2) per-dir ADR checks — filename `^\d{3}-[a-z0-9-]+\.md$`, number
  unique per dir, header slug == dir slug and header NNN == filename NNN; (3) citation
  resolution — every `ADR-[a-z0-9-]+-\d{3}` token anywhere under `docs/` resolves to an
  existing record; (4) stale-id guard — any bare `ADR-\d{4}` under `docs/` is an error
  except in `- **Formerly:**` lines and `docs/archive/**`; (5) root hygiene — loose
  files at docs root other than README.md/CONTEXT-MAP.md, or top-level dirs outside the
  reserved set that lack a README routing row, are errors. Legacy layouts (no map, or
  no `docs/areas/`) keep passing untouched — the new checks activate only when
  `docs/areas/` exists.
- Skills and eval fixtures referencing `docs/<area>/`, `docs/adr/`, or
  `docPaths.adrDir`: grep-driven update at execution (known: `doc-grounded-questions`
  ADR-dir fallback list; `from-issue`/`grill-with-docs` path mentions; B1 fixture
  repos). `docPaths.adrDir` is deprecated: ADR homes are derived from the map.
- nodo `.claude/skills.config.json`: `docPaths.adrDir`, `specDir`, `planDir` removed;
  `architecture`, `gitWorktrees`, `devenvTooling` repointed into `docs/guides/`.

### D10 — Migration shape: one atomic PR per repo

Structure moves + renumber + every reference rewrite + config/linter/test/CI updates
land together; the GitHub sweep runs after merge. nodo's PR touches source and CI
config, so it waits for CI normally (the docs-only fast-path does not apply); argus CI
is broken pre-existing and never gates. argus's `tests/docs/context-budget.test.ts` is
updated in the same PR: `docs/adr` hardcode replaced by map-derived
`docs/areas/*/adr/`, cross-dir uniqueness flipped to per-dir uniqueness, citation regex
moved to the new grammar plus the stale-id guard.

## Test seams

- **`scripts/context-map-lint.py` CLI** (exit code + findings text) — run against both
  migrated repos and against the eval fixture repos; prior art: it already gates both
  repos and stays the single docs-conformance authority.
- **argus `tests/docs/context-budget.test.ts`** — argus's in-repo enforcement of the
  same contract, updated not bypassed.
- **B1 eval runner** (`just evals <skill> <id>`) for skills whose text changes
  (deployed-skill behavior seam; commit → user runs `just switch` → evals).
- **GitHub sweep dry-run diff** — the reviewed artifact before any remote mutation.

No new seams are invented; implementers may not add others.

## Out of scope

- Re-homing ADRs between areas (membership stays as the previous migration classified
  it; the D4 move mechanic covers future re-homing).
- Rewriting immutable history (commit messages) — Formerly lines + id-map are the
  resolution path.
- A CI guard for stale ADR ids in *source* comments (docs-scoped guard only; a source
  sweep can be a later, separate decision).
- ship-issue's docs-only CI fast-path (separate task, same session, different commit).
- wayfind re-derivation and evals (job 4, separate design pass).
- nix-config's own repo layout (it has no `docs/`; it hosts the spec).
- argus's 57 deliberately-dangling relative links and nodo's 381 pre-existing broken
  links outside lint scope — unchanged policy: left alone.

## Auto-resolved decisions

- argus `docs/prototypes/` → `docs/archive/prototypes/` — the prototype skill works in
  throwaway worktrees; the dir is residue. Alternative (reserved `prototypes/` dir)
  rejected: nothing writes there anymore.
- nodo `docs/agents/` (domain.md, issue-tracker.md, triage-labels.md) and
  `docs/agent-framework/overview.md`: migration agent folds still-true content into
  `guides/` (or `.claude/hints/` where it is hint-shaped), deletes what the map
  superseded (domain.md's reading list), archives the rest. Alternative (blessing
  `agents/` as reserved) rejected: two repos, one occurrence.
- `docs/coding-standards.md` pointer file deleted in both repos; its pointer content
  folds into `docs/standards/README.md`; README routing covers discovery. Alternative
  (moving it to guides/) rejected: it duplicates the standards README's first line.
- Sweep scripts committed under each repo's `scripts/` (audit + re-runnability), not
  deleted after use.
- Renumber ordering is chronological per dir (by old serial) — keeps `ls` order
  meaning "oldest first", matching the old global sequence's property within a dir.
- `.claude/` output dir names follow the tool defaults exactly
  (`specs`, `plans`, `handoffs`, `notes`).
- Linter stays docs-scoped and backward-compatible with legacy layouts (checks activate
  on `docs/areas/` presence) so un-migrated repos and fixtures don't break.
