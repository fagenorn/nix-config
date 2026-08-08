# Context Map

## Areas

| Area | Context file | Gist | governs |
|---|---|---|---|
| Backlog | [CONTEXT](./areas/backlog/CONTEXT.md) | Tasks, their states, and the file they live in | `tinytask/**`, `tests/**` |
| System | [CONTEXT](./areas/system/CONTEXT.md) | Decisions spanning areas | `*` |

## Terms

| Term | Area |
|---|---|
| Backlog | Backlog |
| State | Backlog |
| Store | Backlog |
| Task | Backlog |
| Task file | Backlog |

## Relationships

- **Backlog → System**: Backlog is the only domain area; System carries the repo-wide
  decisions it works under (dependencies, tooling).
