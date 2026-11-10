# ADR-system-001 — Decisions live in area ADRs and contracts in docstrings, not in READMEs

- **Status:** accepted
- **Decided in:** issue 694 (owner decision 2026-11-08)

## Context

`python/README.md` had grown to 234 KB because `CLAUDE.md` and two READMEs sent every new detail into one file, mixing contracts, decisions, evidence and how-to in a single place that no reader could scan and no test could keep honest.

## Decision

Adopt the docs standard: `docs/README.md` routes knowledge, `docs/CONTEXT-MAP.md` maps the areas, each area holds a glossary and an `adr/`, and `guides/` holds procedures. A command's contract lives in its module docstring, a decision is an area ADR, a measurement goes to `docs/archive/`, and a README is an overview of at most 150 lines.

## Consequences

- `tests/test_docs_tree.py` runs the context-map linter and checks the section map in the suite, so the tree and the record of where each README section went cannot drift unseen.
- `paths.context` is not yet declared, so the skills do not select the map until #797 wires it.
- How-to already in the kept sections of the Nix-module READMEs stays there instead of moving to `guides/`, because it describes the module that README documents.
- The map's areas are also the subpackages #695 will create.
