# Project standards: nix-config

Layer 2 of the three-layer standards contract (`~/.agents/standards/README.md`).
It holds deltas only, on top of the bar (Layer 0) and the stack shards
(Layer 1). A shard loads when a touched path matches one of its `governs` globs.

| Shard | governs | Gist |
|---|---|---|
| [agent-helpers.md](agent-helpers.md) | `python/**`, `scripts/**`, `home/common/agent-skills/skills/*/scripts/**`, `home/common/claude-code/lifecycle_guard.py`, `home/common/agent-skills/tests/**` | Agent-workflow Python lives in the `agent_tools` package, runs only through `-m`, and shares one canonical-JSON home. Skill-text tests pin only machine-consumed text. |
| [package-layout.md](package-layout.md) | `python/agent_tools/**`, `tests/test_agent_tools_layout.py` | Each agent_tools module or .NET project lives in its area, and dependencies follow one reviewed table: the layout test's imports for Python, the record's reference graph for .NET. |
| [testing.md](testing.md) | `tests/**`, `home/common/agent-skills/tests/**`, `home/common/agent-skills/evals/tests/**`, `justfile`, `.github/workflows/ci.yaml` | Every test has one tier, fast, integration or nightly; a new test file declares it and joins that tier's runner, and CI reports suite time growth over main; a stress probe grows in bounded steps from under 1 GiB. |
