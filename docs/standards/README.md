# Project standards: nix-config

Layer 2 of the three-layer standards contract (`~/.agents/standards/README.md`).
It holds deltas only, on top of the bar (Layer 0) and the stack shards
(Layer 1). A shard loads when a touched path matches one of its `governs` globs.

| Shard | governs | Gist |
|---|---|---|
| [agent-helpers.md](agent-helpers.md) | `python/**`, `scripts/**`, `home/common/agent-skills/scripts/**`, `home/common/agent-skills/skills/*/scripts/**`, `home/common/claude-code/lifecycle_guard.py` | Agent-workflow Python lives in the `agent_tools` package, runs only through `-m`, and shares one canonical-JSON home. |
