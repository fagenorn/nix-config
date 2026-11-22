# ADR-project-contract-019 — Adoption moves hints and turns hand-written entry files into the bootstrap source

- **Status:** accepted
- **Decided in:** #1468 (per #1413)

## Context

Adoption left `.claude/hints/` where it was, so the delivery phases, which read `.agents/knowledge/hints/`, never saw an adopted project's hints. It rewrote every inbound relative link, including those in accepted records that must keep their citations, and it overwrote hand-written entry files with generated ones. This decision makes adoption move the hints, keep point-in-time records as they are, and report a hint no phase reads.

## Decision

**D1. Hints are a canonical move.** The `.claude/hints` classification row is `move-canonical` into `.agents/knowledge/hints`, the directory `agent_tools.delivery.hint_phases.HINT_DIR` names, so every tracked hint is a `git-mv` that keeps its history. A hint that is ignored by git stays recorded and retained, because `git mv` cannot move an untracked file.

**D2. A `paths.hints` binding follows the move, file or directory.** `amended_contract` maps each `paths.hints` string through the plan's relocations by prefix: a value equal to a relocated group, or under it, takes the group's target in place of that prefix. `.claude/hints` becomes `.agents/knowledge/hints` and `.claude/hints/planning.md` becomes `.agents/knowledge/hints/planning.md`, so a declared `knowledge.hints` capability stays `available` after apply.

**D3. An unread hint is an open item, never a gate.** `plan.open_items` is present only when non-empty: one `{"id": "hint-without-reader", "path": <new path>}` per moved hint whose path under the hint directory is not a name in `hint_phases.HINT_FILES` (a file in a subdirectory always qualifies), sorted by path. It is outside the plan id, because it is a pure function of the evidence and moves the plan id already covers, and it is not a ready gate, because a gate would change the `checks` of every evidence record and block a plan on something adoption cannot repair. The human view prints `open item hint-without-reader: <path>`.

**D4. Point-in-time records keep their citations (bar B9).** A path with an `adr` component, or under `.agents/knowledge/archive/` or `.agents/artifacts/`, is a point-in-time record. It is never an inbound link-rewrite source: the planner skips it before counting, so it adds no rewrite, no `unrewritable` row and no `already_broken` count, and `no-new-broken-link` does not judge it unless a `git-mv` moved it. A moved record keeps its outbound rewrite, because its links would otherwise break where it now sits.
