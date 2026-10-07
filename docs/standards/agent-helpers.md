# Agent helpers

Deltas for agent-workflow Python in this repository. They bind new code now;
a legacy flat script meets them when its cluster moves into the package.

1. **Helpers live in the package.** Agent-workflow Python is a module of `agent_tools` under `python/`, and a command is that module plus one row in the command table in `lib/agent-tools.nix`, never a new top-level script. Each legacy script moves in with its cluster's PR. ([design](../../.agents/artifacts/specs/2026-09-24-agent-tools-package-design.md))

2. **A command module is a thin shell.** It parses argv with a parser whose `prog` is the command name, reads input, calls importable functions, writes output and maps errors to exit codes; policy lives in functions that other modules and tests import. ([design](../../.agents/artifacts/specs/2026-09-24-agent-tools-package-design.md))

3. **No import machinery and no path-derived calls.** Nothing edits `sys.path`, loads a module through `importlib` or by file path, checks a module version handshake, or locates another module or command from `__file__`. A packaged sibling runs as `sys.executable`, with `-I` only when the caller itself runs isolated, then `-m agent_tools.<module>`, through one shared package helper, while an executable outside the package runs by its command name on `PATH`. ([design](../../.agents/artifacts/specs/2026-09-24-agent-tools-package-design.md))

4. **One canonical-JSON home.** A digest uses `agent_tools.canonical.telemetry_digest` (sorted, compact, ASCII-escaped JSON with a `sha256:` prefix) or the delivery model's own format, never a local copy. A strict JSON load composes the `reject_duplicate_keys` and `reject_nonfinite_literal` hooks from `agent_tools.canonical` that its command needs, never a local hook. ([design](../../.agents/artifacts/specs/2026-09-24-agent-tools-package-design.md))

5. **Tests drive commands from source.** A test runs a command as `python -m agent_tools.<module>` under the recipe's `PYTHONPATH` and imports modules normally. Only the installed-layout test, `tests/test_agent_tools_launchers.py`, touches the built launchers. ([design](../../.agents/artifacts/specs/2026-09-24-agent-tools-package-design.md))

6. **Skill-text tests pin only what a tool or subagent consumes.** A test under `home/common/agent-skills/tests/` may assert the dispatch marker lines and the `Agent(...)` call lines mirrored in `model-matrix.json`, the carrier clauses `test_dispatch_contracts` places in dispatch regions, shell examples vetted by `test_shell_example_contracts`, frontmatter, the JSON key sets of lifecycle contracts, and `workflow-state`/`resolve-project` argv. No new test pins an English phrase. Existing phrase pins are deleted in the slice that slims their skill, and a heading anchor that only tests read may be renamed with its test in the same commit. ([design](../../.agents/artifacts/specs/2026-10-07-issue-291-skill-best-practices-design.md))

The Claude Code lifecycle guard, `home/common/claude-code/lifecycle_guard.py`, stays a standalone, standard-library-only file that imports nothing from `agent_tools`, so of these rules only rule 3's ban on import machinery and `__file__` lookups binds it, and it runs `git`, `gh` and `jq` by the absolute store paths its policy names rather than by name on `PATH`. ([design](../../.agents/artifacts/specs/2026-09-24-issue-176-lifecycle-guard-extraction-design.md))
