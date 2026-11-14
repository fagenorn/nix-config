# ADR-hosts-005 — Account profiles share configuration by links to `~/.claude/<entry>`

- **Status:** accepted
- **Decided in:** #373

## Context

Several Claude accounts run side by side on one host, each with its own login. Everything but the login should be the same in every account: settings, `CLAUDE.md`, skills, agents, plugins and transcripts come from the Nix-generated `~/.claude`, which changes with every generation. Claude Code reads one directory, `CLAUDE_CONFIG_DIR`, so each account needs a directory of its own.

## Decision

A profile directory under `~/.claude-accounts/profiles/` is the account's `CLAUDE_CONFIG_DIR`, and its shared entries are links to the `~/.claude/<entry>` paths, never to their store targets, so they follow generations. `~/.claude.json` is the exception: a new profile gets a one-time copy without the login, because the file holds the login. Everything under the profiles and the bindings table is runtime-owned, and Nix owns only the code that creates and uses it.

## Consequences

- An MCP server merged into `~/.claude.json` after a profile exists does not reach that profile until it is merged into the profile's own `.claude.json` too.
- A switch that regenerates `~/.claude` reaches every profile at once, with no per-account step.
- Transcripts are shared through the links, so a conversation carries over when a session switches accounts.
- The console creates a profile only by running `claude-account add`, so a profile added from the page is the same as one added in a terminal (ADR-console-025).
