# ADR-system-002 — Agent-workflow Python is one standard-library package with one install route

- **Status:** accepted
- **Decided in:** [the agent-tools package design](../../../../.agents/artifacts/specs/2026-09-24-agent-tools-package-design.md)

## Context

The agent-workflow helpers were some two dozen loose Python files that Nix linked one by one into `~/.agents/bin`. Because they were not a package they could not import each other, so each spec invented its own loader and copied knowledge between modules.

## Decision

Every helper is a module of the one standard-library package `agent_tools` under `python/`. Each command is that module plus exactly one row in the command table of `lib/agent-tools.nix`, which is the only install route. A row becomes a `~/.agents/bin/<command>` launcher that unsets the `NIX_PYTHON*` variables and runs `python3 -I -m agent_tools.<module>` from one Nix-built environment, so nothing on `PYTHONPATH` or in the working directory can shadow the store copy.

## Consequences

- The builder import-checks every module, so a broken import fails `just build`.
- The installed-layout check pins the system closure to one `agent_tools` build and every launcher to one environment; a helper added outside the table is not installed.
- The package is standard-library only, so a module that needs a third-party dependency cannot join it without revisiting this decision.
