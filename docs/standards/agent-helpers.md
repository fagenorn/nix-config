# Agent helpers

Deltas for agent-workflow Python in this repository. They bind new code now;
a legacy flat script meets them when its cluster moves into the package.

1. **Helpers live in the package.** Agent-workflow Python is a module of `agent_tools` under `python/`, and a command is that module plus one row in the command table in `lib/agent-tools.nix`, never a new top-level script. Each legacy script moves in with its cluster's PR. ([design](../../.agents/artifacts/specs/2026-09-24-agent-tools-package-design.md))

2. **A command module is a thin shell.** It parses argv with a parser whose `prog` is the command name, reads input, calls importable functions, writes output and maps errors to exit codes; policy lives in functions that other modules and tests import. ([design](../../.agents/artifacts/specs/2026-09-24-agent-tools-package-design.md))

3. **No import machinery and no path-derived calls.** Nothing edits `sys.path`, loads a module through `importlib` or by file path, checks a module version handshake, or locates another module or command from `__file__`. A packaged sibling runs as `sys.executable`, with `-I` only when the caller itself runs isolated, then `-m agent_tools.<module>`, through one shared package helper, while an executable outside the package runs by its command name on `PATH`. ([design](../../.agents/artifacts/specs/2026-09-24-agent-tools-package-design.md))

4. **One canonical-JSON home.** A digest uses `agent_tools.canonical.telemetry_digest` (sorted, compact, ASCII-escaped JSON with a `sha256:` prefix) or the delivery model's own format, never a local copy. A strict JSON load composes the `reject_duplicate_keys` and `reject_nonfinite_literal` hooks from `agent_tools.canonical` that its command needs, never a local hook. ([design](../../.agents/artifacts/specs/2026-09-24-agent-tools-package-design.md))

5. **Tests drive commands from source.** A test runs a command as `python -m agent_tools.<module>` under the recipe's `PYTHONPATH` and imports modules normally. Only the installed-layout test, `tests/test_agent_tools_launchers.py`, touches the built launchers. ([design](../../.agents/artifacts/specs/2026-09-24-agent-tools-package-design.md))
