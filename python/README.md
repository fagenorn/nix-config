# agent_tools — the agent helper package

Every agent-workflow helper is a module of one standard-library Python package, `agent_tools`; this file is its overview. A command's contract is its module docstring, so read the code's own head, not a copy of it.

## Layout

- `python/agent_tools/` holds the modules in one subpackage per docs area (`claims`, `console`, `delivery`, `guard`, `hosts`, `project_contract`, `release`, `verification`, and `system` for code no area owns) beside the gate-pinned top level (`instruction_load`, `skill_lint`, `agent_model_matrix`, `canonical`), and `python/pyproject.toml` declares the package. The layout rule is [`docs/standards/package-layout.md`](../docs/standards/package-layout.md).
- `lib/agent-tools.nix` builds the package into one Python environment, import-checks every module so that a broken import fails `just build`, and holds the command table. Each command is a module plus one row of that table, and the row is its only install route (ADR-system-002).
- `home/common/agent-tools/default.nix` applies that builder once per home configuration as the `agentTools` module argument, which agent-skills and claude-code consume.
- Each row becomes a `~/.agents/bin/<command>` launcher. It unsets the `NIX_PYTHON*` variables and runs `python3 -I -m agent_tools.<area>.<module>` (`agent_tools.<module>` for a top-level module) from the built environment, so nothing on `PYTHONPATH` or in the working directory can shadow the store copy.
- The installed-layout check pins the built system closure to one `agent_tools` package build, every launcher to one Python environment, and that environment's imports to the closure's package build. `just agent-installed-skill-tests` passes `AGENT_TOOLS_SYSTEM_RESULT` to the check.

## Running a command

- Installed: call the launcher by its command name, for example `forge-issue` or `resolve-project`.
- From source: `PYTHONPATH=python python3 -m agent_tools.<area>.<module>`, or `-m agent_tools.<module>` for a top-level module, from the repository root.
- The `just` recipes that run package code (`agent-workflow-tests`, `agent-run-profile`, `verify`, `agent-instruction-budget` and the others) set `PYTHONPATH` to `python/` themselves.
- A command's contract (arguments, output, exit codes) is its module docstring. Read it with `python3 -m pydoc agent_tools.<area>.<module>` (`agent_tools.<module>` for a top-level module) or from the head of the file.

## Testing

- `just agent-workflow-tests` runs the whole curated suite, one process per member and `min(8, CPUs - 2)` at a time. `SUITE_RUNNER_JOBS` or `--jobs N` sets the cap, and `--jobs 1` runs serially with live output.
- One member: `PYTHONPATH=python python3 -m unittest -v <test file>`, for example `tests/test_docs_tree.py`.
- `just agent-installed-skill-tests` checks the skill contracts, the launchers, the generated Claude settings and the Claude launchers against what the Nix build installs.
- `just build` is the import check for the package and the Nix side.

## Where docs live

- A command's contract is its module docstring.
- A decision is an ADR under `docs/areas/<area>/adr/`, and each area's terms are in its `CONTEXT.md`. [`docs/CONTEXT-MAP.md`](../docs/CONTEXT-MAP.md) is the one place that says which area governs a module.
- A measurement is kept under `docs/archive/`, and a procedure is a guide under `docs/guides/`.
- [`docs/README.md`](../docs/README.md) routes new knowledge, procedures included.
