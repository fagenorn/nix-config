# ADR-delivery-001 — Codex is a reviewer only

- **Status:** accepted
- **Decided in:** #687 D1

## Context

Codex reviews plans and diffs for the delivery programs and does not author. Giving it a guidance file, a skill view or a config splice would make Nix own, populate and prune its runtime state.

## Decision

Nix writes nothing under `~/.codex/` and nothing under `~/.agents/skills/`. The global guidance reaches Claude alone, as `~/.claude/CLAUDE.md` through `programs.claude-code.memory`, and the skills reach Claude through `skillsDir`.

## Consequences

- Codex gets no guidance file, skill view or config splice, and its own runtime state is neither populated nor pruned.
- Guidance and skills are written once, for Claude, with no second projection to keep in step.
