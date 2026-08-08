# Agent skills — project adapter contract

The skills in `skills/` are project-agnostic: they carry zero project residue and read everything
project-specific through the adapter surfaces below. A new project onboards by writing a config file
and a map skeleton; nothing in this tree changes.

| Surface | Lives at (per repo) | Carries |
|---|---|---|
| **Values** | `.claude/skills.config.json` | Tracker, branches, verify commands, doc paths, naming, deploy adapter — every binding the skills resolve. See the per-skill "Keys used" lines. |
| **Prose hints** | `.claude/hints/` (via the `projectHints` binding) | Project-specific prose the generic skills defer to: `review.md` (Phase-5 reviewers), `merge.md` (ship-issue merge phase), `deploy.md` + `changelog.md` (ship-release). |
| **Domain language** | `docs/CONTEXT-MAP.md` + `docs/areas/<area>/CONTEXT.md` | The map is an index (≤150 lines): areas, term → area table, `governs:` globs (root-relative). Area files are budgeted glossaries. Format: `skills/grill-with-docs/CONTEXT-FORMAT.md`; linter: `~/.agents/bin/context-map-lint`. |
| **Decisions** | `docs/areas/<slug>/adr/` — every area's own, including the reserved `system` area for decisions no single area owns | 1–3 sentence records, gated on hard-to-reverse AND surprising AND real-trade-off. Ids are `ADR-<slug>-NNN`, numbered per directory from `001`; no global sequence. Format: `skills/grill-with-docs/ADR-FORMAT.md`. |
| **Standards, Layer 2** | `docs/standards/` + ≤40-line README index with `governs:` globs | Project deltas only. Layers 0–1 are machine-global: `~/.agents/standards/the-bar.md` (universal) and `~/.agents/standards/stacks/*.md` (per-stack trap libraries) — a new project inherits both for free. Precedence: direct instruction > project > stack > bar > convention. |
| **Rejection KB** | `.out-of-scope/*.md` | One file per consciously-rejected direction; `to-issues` checks it before proposing slices. |
| **Decision maps** (optional) | tracker issues labelled `wayfinder:*` | Big fuzzy efforts charted by the `wayfind` skill; `from-issue --auto`'s fog gate emits decision tickets into them. |

## The `projectHints` binding

`projectHints` in `.claude/skills.config.json` names the prose-hints location:

- **Directory** (e.g. `".claude/hints/"`) — the contract: each consuming skill reads the file for its
  moment (`review.md`, `merge.md`, `deploy.md`, `changelog.md`) and silently skips absent ones.
- **Single file** (legacy) — treated as review hints only.

Hints are read **only by the consuming agent at the moment of use** — never loaded into an
orchestrator context.

## Onboarding a new project

1. `cp` a sibling project's `.claude/skills.config.json` and edit the values.
2. Write the map skeleton: `docs/CONTEXT-MAP.md` with one area (or run a `grill-with-docs` session
   and let the first terms create it).
3. Optionally seed `docs/standards/README.md` (empty index) and `.claude/hints/`.
4. Everything else is machine-global via nix (`home/common/agent-skills/`): the skills, the
   standards layers 0–1, and the linter arrive with the home-manager generation.
