# nix-config docs

| Entry | What lives there |
|---|---|
| [CONTEXT-MAP.md](./CONTEXT-MAP.md) | The map: the areas, the paths each governs, and which area owns each term |
| [areas/](./areas/) | One directory per area: a budgeted glossary plus that area's decision records |
| [standards/](./standards/) | The coding bar for this repo |
| [archive/](./archive/) | Retained evidence and point-in-time records, kept at their paths |
| [spikes/](./spikes/) | Point-in-time spike reports, kept at their paths |

**Where new knowledge goes**

| Knowledge | Home |
|---|---|
| A term | The owning area's `CONTEXT.md` |
| A decision | That area's `adr/` (`areas/system/adr/` when it spans areas), under the ADR-FORMAT gate |
| A command's contract | Its module docstring in `python/agent_tools/<module>.py` (the lifecycle guard's in `home/common/claude-code/lifecycle_guard.py`) |
| A procedure (how-to) | `guides/`, one file per task, named for what it does |
| The behaviour of a Nix module with no Python home | That module's README (`home/common/claude-code/README.md`, `home/common/agent-skills/README.md`, `home/linux/claude-local/README.md`) |
| A measurement or other retained evidence | `archive/` |
| A Layer-2 coding rule | `standards/` |
| The package overview (layout, running, testing) | `python/README.md` |
| Specs and plans | `.agents/artifacts/`, never `docs/` |
