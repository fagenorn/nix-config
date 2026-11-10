# Package layout

Deltas for the `agent_tools` package layout. They bind every module under `python/agent_tools/`; the rule and its reasons are in [ADR-system-003](../areas/system/adr/003-agent-tools-subpackages-are-the-areas.md).

1. **A module lives in its area.** It sits in `agent_tools.<area>`, the area whose `docs/CONTEXT-MAP.md` row governs its concern, one level deep, and the subpackage's `__init__.py` holds only a docstring. ([ADR-system-003](../areas/system/adr/003-agent-tools-subpackages-are-the-areas.md))

2. **Unowned code goes in `system`.** Code no area owns lives in `agent_tools.system`, which imports only itself and top-level modules. ([ADR-system-003](../areas/system/adr/003-agent-tools-subpackages-are-the-areas.md))

3. **The top level is the gate closure.** It holds only `__init__` and the Instruction Budget gate modules with their import closure, which move only with a raise-labelled change. ([ADR-system-003](../areas/system/adr/003-agent-tools-subpackages-are-the-areas.md))

4. **Imports are absolute and follow one table.** A module imports another area's module only when `ALLOWED_IMPORTS` in `tests/test_agent_tools_layout.py` lists that edge; adding an edge is a reviewed change to that table, never a relative import or a subprocess workaround. ([ADR-system-003](../areas/system/adr/003-agent-tools-subpackages-are-the-areas.md))

5. **A module serving two areas is split.** It is cut at that seam into the owning area and `system`. ([ADR-system-003](../areas/system/adr/003-agent-tools-subpackages-are-the-areas.md))
