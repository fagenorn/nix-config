# ADR-guard-012 — The guard refuses declared production MCP tools and key file writes

- **Status:** accepted
- **Decided in:** #1150

## Context

ADR-guard-009 named a `PreToolUse` matcher as the control for an MCP tool call and for a write to a key file through Edit or Write, and ADR-guard-011 enforced a project's production commands but left those two routes unenforced. A session in `bypassPermissions` could still call a declared production MCP tool or write a declared key file with no hook to object. The contract already declares both (ADR-project-contract-007), so the guard reads them from the project's derived row as it reads the commands.

## Decision

The guard refuses a call to a declared production MCP tool and a write to a declared key file, in every permission mode. The decisions below make that reading precise.

- **D1, the row member.** A row's `production` member carries the changing `key_files` and `mcp_tools` as authored, beside its commands. Read-only MCP tools are not carried. The loader takes both as optional, and the compiled policy's schema becomes 5.
- **D2, the registration.** The same guard command is registered on `Edit|Write|MultiEdit|NotebookEdit` and on `^mcp__`. MultiEdit is listed because the pinned Claude Code names it among its file-write tools.
- **D3, an MCP call.** An MCP call is refused by exact name wherever it is called, because an MCP server acts with its own credentials, not through a checkout. The refusal names the first declaring project by sorted slug.
- **D4, a key file.** A key file is judged in the written path's own checkout (the git toplevel of the nearest existing ancestor, and of each lexical ancestor holding a `.git` so a symlinked directory inside the checkout cannot hide it, with its `origin` slug) under three spellings, and any of them refuses: the path as named, its directories resolved with the final component kept, and its full realpath, so a symlink neither hides a declared key file nor reaches one unseen. The glob is matched with `fnmatchcase` on the strings unchanged, as the contract matches it (`*` crossing `/`, no casefolding). File system aliases are handled apart from the match: each existing component takes the file system's own spelling, so a case variant on darwin reads as the file it reaches, while on a case-sensitive file system it stays a different path.
- **D5, when git runs.** Git runs only when a declared glob matches a suffix of the path, the base policy is read only then, and a checkout lookup that fails for such a path refuses: a timeout, a git that cannot start, and any nonzero exit other than git's "not a git repository" (dubious ownership, a malformed config) are failures, so only a confirmed non-repository counts as outside a checkout.
- **D6, a bad policy.** A compiled policy that does not load refuses nothing, as for every production rule.
- **D7, the sentences.** A refused MCP call reads ``<tool> changes the production of <slug> (production MCP tool), so it runs only through the release profile <profile> with release transaction preview and release transaction run.`` with the tool in backquotes. A refused write reads ``<relative> is a key file of <slug> (key file glob <glob>), so it changes only through the release profile <profile> with release transaction preview and release transaction run.`` with the relative path in backquotes.

## Consequences

- An agent cannot edit a declared key file or call a declared production MCP tool in any permission mode.
- A key file written through a Bash command (redirection, `sed`, `git checkout`) or through a hard link under another name, and an MCP tool reached under another name, are not seen.
- Every edit and MCP call now starts the guard, which reads one compiled policy file.
- A session started before the switch that installs this guard reads a schema-5 row as malformed until it restarts.
- The policy-rewrite route of ADR-guard-011 stays open.
