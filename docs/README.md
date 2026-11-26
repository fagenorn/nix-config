# nix-config docs

| Entry | What lives there |
|---|---|
| [CONTEXT-MAP.md](./CONTEXT-MAP.md) | The map: the areas, the paths each governs, and which area owns each term |
| [areas/](./areas/) | One directory per area: a budgeted glossary plus that area's decision records |
| [standards/](./standards/) | The coding bar for this repo |
| [guides/](./guides/) | Procedures (how to do one task, one file each) and the architecture description |
| [guides/write-for-the-owner.md](./guides/write-for-the-owner.md) | The plain-words rule for everything the console shows the owner, including what managers write |
| [guides/owner-words.md](./guides/owner-words.md) | The glossary of internal words, each with a one-line everyday gloss |
| [guides/console-page-audit-2026-11-25.md](./guides/console-page-audit-2026-11-25.md) | The audit of the live console page of 25 November 2026, the starting point later changes measure against |

**Where new knowledge goes**

| Knowledge | Home |
|---|---|
| A term | The owning area's `CONTEXT.md` |
| A decision | That area's `adr/` (`areas/system/adr/` when it spans areas). A decision record is written only in design and grilling, never by a delivery agent, and only when it is hard to reverse, surprising without context, a real trade-off and names its rejected alternative. Else how it works goes to the code, its tests and module docstring; a rule for every change to a standard with an id; a word's meaning to the glossary; a one-off choice or a bug's story to the issue and commit message. |
| A command's contract | Its module docstring in `python/agent_tools/<area>/<module>.py`, or `python/agent_tools/<module>.py` for a top-level module (the lifecycle guard's in `home/common/claude-code/lifecycle_guard.py`) |
| A rule for the words the console shows the owner, and its glossary | [`guides/write-for-the-owner.md`](./guides/write-for-the-owner.md) and [`guides/owner-words.md`](./guides/owner-words.md) |
| A procedure (how-to) | `guides/`, one file per task, named for what it does |
| The architecture description (flake layout, module layering, helpers, the agent helper package) | [`guides/architecture.md`](./guides/architecture.md) |
| The behaviour of a Nix module with no Python home | That module's README (`home/common/claude-code/README.md`, `home/common/agent-skills/README.md`, `home/linux/claude-local/README.md`) |
| A measurement, spike or other evidence | A comment or attachment on the pull request or issue it proves, never `docs/` |
| A Layer-2 coding rule | `standards/` |
| The package overview (layout, running, testing) | `python/README.md` |
| A spec | The body of its parent issue, never the tree |
| A plan and its task files | The worktree's git directory, never the tree |
