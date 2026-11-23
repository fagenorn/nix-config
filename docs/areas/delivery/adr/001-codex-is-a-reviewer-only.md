# ADR-delivery-001 — Codex is a reviewer only

Codex reviews the delivery programs' plans and diffs and authors nothing, so Nix writes nothing under `~/.codex/` and nothing under `~/.agents/skills/`: the global guidance reaches Claude alone, as `~/.claude/CLAUDE.md` through `programs.claude-code.memory`, and the skills reach Claude through `skillsDir`, written once with no second projection to keep in step. Giving Codex its own guidance file, skill view or config splice was rejected because Nix would then own, populate and prune Codex's runtime state (decided in #687 D1).
