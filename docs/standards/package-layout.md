# Package layout

Deltas for the `agent_tools` layout in both runtimes. Python rules bind each module left under `python/agent_tools/` ([ADR-system-003](../areas/system/adr/003-agent-tools-subpackages-are-the-areas.md)); .NET rules bind each project under `dotnet/` ([ADR-system-007](../areas/system/adr/007-agent-tools-moves-to-dotnet-under-one-reference-graph.md)).

### P9. A module lives in its area

Python: it sits in `agent_tools.<area>`, the area whose `docs/CONTEXT-MAP.md` row governs its concern, one level deep, and `__init__.py` holds only a docstring. .NET: each area is one project under `dotnet/` named for it, its test project beside it. ([ADR-system-007](../areas/system/adr/007-agent-tools-moves-to-dotnet-under-one-reference-graph.md))

### P10. The system layer holds only what no area may own

Python: code no area owns lives in `agent_tools.system`, which imports only itself and top-level modules. .NET: the System project holds only the forge transport (the `gh` calls) and references no other project. ([ADR-system-007](../areas/system/adr/007-agent-tools-moves-to-dotnet-under-one-reference-graph.md))

### P11. The top level is the gate closure, the composition root is Hosts

Python: the top level holds only `__init__`, `instruction_load`, `skill_lint` and their import closure. .NET: Hosts is the composition root and owns the command table. ([ADR-system-007](../areas/system/adr/007-agent-tools-moves-to-dotnet-under-one-reference-graph.md))

### P12. Dependencies follow one reviewed table

Python: a module imports another area's module only when `ALLOWED_IMPORTS` in `tests/test_agent_tools_layout.py` lists that edge; adding an edge is a reviewed change to that table, never a relative import or a subprocess workaround. .NET: a project references another only along an edge of the record's reference graph, every project sets `DisableTransitiveProjectReferences`, and one architecture test holds the table; adding an edge changes the record and that test, never a `Process.Start` of the tool's own binary. ([ADR-system-007](../areas/system/adr/007-agent-tools-moves-to-dotnet-under-one-reference-graph.md))

### P13. A module serving two areas is split

Python: it is cut at that seam into the owning area and `system`. .NET: a type serving two areas is cut at that seam into the owning area's project and the lower layer both may reference. ([ADR-system-007](../areas/system/adr/007-agent-tools-moves-to-dotnet-under-one-reference-graph.md))
