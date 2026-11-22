# nix-config docs

| Entry | What lives there |
|---|---|
| [CONTEXT-MAP.md](./CONTEXT-MAP.md) | The map: the areas, the paths each governs, and which area owns each term |
| [areas/](./areas/) | One directory per area: a budgeted glossary plus that area's decision records |
| [standards/](./standards/) | The coding bar for this repo |
| [guides/](./guides/) | Procedures (how to do one task, one file each) and the architecture description |

**Where new knowledge goes**

| Knowledge | Home |
|---|---|
| A term | The owning area's `CONTEXT.md` |
| A decision | That area's `adr/` (`areas/system/adr/` when it spans areas). A decision record is written only in design and grilling, never by a delivery agent, and only when it is hard to reverse, surprising without context, a real trade-off and names its rejected alternative. Else how it works goes to the code, its tests and module docstring; a rule for every change to a standard with an id; a word's meaning to the glossary; a one-off choice or a bug's story to the issue and commit message. |
| A command's contract | Its module docstring in `python/agent_tools/<area>/<module>.py`, or `python/agent_tools/<module>.py` for a top-level module (the lifecycle guard's in `home/common/claude-code/lifecycle_guard.py`) |
| A procedure (how-to) | `guides/`, one file per task, named for what it does |
| The architecture description (flake layout, module layering, helpers, the agent helper package) | [`guides/architecture.md`](./guides/architecture.md) |
| The behaviour of a Nix module with no Python home | That module's README (`home/common/claude-code/README.md`, `home/common/agent-skills/README.md`, `home/linux/claude-local/README.md`) |
| A measurement, spike or other evidence | A comment or attachment on the pull request or issue it proves, never `docs/` |
| A Layer-2 coding rule | `standards/` |
| The package overview (layout, running, testing) | `python/README.md` |
| A spec | The body of its parent issue, never the tree |
| A plan and its task files | The worktree's git directory, never the tree |
