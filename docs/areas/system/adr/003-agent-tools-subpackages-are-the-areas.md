# ADR-system-003 — agent_tools subpackages are the docs areas, and cross-area imports follow one table

- **Status:** accepted
- **Decided in:** issue 695

## Context

`agent_tools` was one flat package of some eighty modules, so nothing in the tree showed which area a module belonged to and any module could import any other. ADR-system-001 said the docs areas become the subpackages; this decision carries that out.

## Decision

Each docs area is a subpackage of `agent_tools`, one level deep, named by its area with hyphens replaced by underscores, and its `__init__.py` holds only a docstring. A module lives in the area whose `docs/CONTEXT-MAP.md` row governs its concern; code no area owns lives in `agent_tools.system`, which imports only itself and top-level modules. A module that serves two areas is split at that seam into the owning area and `system`.

The top level keeps only `__init__` and the Instruction Budget gate modules with their import closure. Imports inside the package are absolute. A module imports another area's module only when a table in `tests/test_agent_tools_layout.py` lists that edge, so adding an edge is a reviewed change to that table.

## Consequences

- The gate closure stays flat until a raise-labelled change moves it.
- The layout test refuses an unlisted edge, a relative import, a stray flat module and a non-area subpackage.
- Launchers keep their names; the command table maps each to its dotted module.
- Accepted ADRs keep their citations as written, so a flat `agent_tools.<module>` in an older record names the module now at `agent_tools.<area>.<module>`, its area being the `docs/CONTEXT-MAP.md` row that governs it.
