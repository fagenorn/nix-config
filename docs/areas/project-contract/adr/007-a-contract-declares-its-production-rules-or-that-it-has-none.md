# ADR-project-contract-007 — A contract declares its production rules, or that it has none

- **Status:** accepted; amended by ADR-system-004
- **Decided in:** issue 1148

## Context

No fixed rule can refuse a change to a project's production without a declaration of what that production is: which commands, key files and MCP tools change it, which only read it, and through which release profile a change is allowed. The guard (#1149, #1150) and the console (#1151) will read that declaration, and each project must be able to say that it has no production at all, so that a project which has not answered is told apart from one that has.

## Decision

The contract gains one optional top-level member, `production`, in one of two forms. `{"none": true}` declares that the project has no production, and no rule member may stand beside it (`contract.production.none_with_rules`). `{"none": false, "changes": {...}, "read_only": {...}, "release_profile": "<id>"}` declares the rules. `none` is always required, so neither form is implied.

With `none: false`, every member and list is required. A list may be empty, but `changes` must name at least one command, key file or MCP tool (`no_change_route`). Command ids must name `bindings.commands` entries. `release_profile` must name a key of `release.profiles`, so a contract whose `release` is `unsupported` cannot carry rules. A command or MCP tool listed both as changing and as read-only is refused (`route_both_ways`). Key files follow the contract glob rule (safe, canonical, matched with `fnmatchcase`), and MCP tool names match `mcp__<server>__<tool>`, the per-tool name Claude Code reports; a server-level name is not a tool.

Every snapshot carries a derived `production` member: `{"status": "not_declared"}` when the section is absent, `{"status": "none"}` for the no-production form, and `{"status": "declared", "changes", "read_only", "release_profile"}` with the authored values copied verbatim. Key-file globs stay repository-relative, because they are not bindings and are not made absolute.

## Consequences

- An existing contract resolves unchanged, with `production` reported as `not_declared`, which is not the same as `none`.
- A host's installed resolver predates the section and refuses a contract that carries it until that host switches.
- The guard and console issues consume the snapshot member and never read the contract file.
