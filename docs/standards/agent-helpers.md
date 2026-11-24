# Agent helpers

Deltas for agent-workflow Python in this repository. They bind all agent-workflow Python.

### P1. Helpers live in the package

Agent-workflow Python is a module of `agent_tools` under `python/`, and a command is that module plus one row in the command table in `lib/agent-tools.nix`, never a new top-level script. ([design](https://github.com/fagenorn/nix-config/blob/6b06a4e277ab8885d02cca9cec38e85a6de5dc55/.agents/artifacts/specs/2026-09-24-agent-tools-package-design.md))

### P2. A command module is a thin shell

It parses argv with a parser whose `prog` is the command name, reads input, calls importable functions, writes output and maps errors to exit codes; policy lives in functions that other modules and tests import. ([design](https://github.com/fagenorn/nix-config/blob/6b06a4e277ab8885d02cca9cec38e85a6de5dc55/.agents/artifacts/specs/2026-09-24-agent-tools-package-design.md))

### P3. No import machinery and no path-derived calls

Nothing edits `sys.path`, loads a module through `importlib` or by file path, checks a module version handshake, or locates another module or command from `__file__`. A packaged sibling runs as `sys.executable`, with `-I` only when the caller itself runs isolated, then `-m agent_tools.<area>.<module>`, or `-m agent_tools.<module>` for a module the layout rule keeps at the top level, through one shared package helper, while an executable outside the package runs by its command name on `PATH`. ([design](https://github.com/fagenorn/nix-config/blob/6b06a4e277ab8885d02cca9cec38e85a6de5dc55/.agents/artifacts/specs/2026-09-24-agent-tools-package-design.md))

### P4. One canonical-JSON home

A digest uses `agent_tools.canonical.telemetry_digest` (sorted, compact, ASCII-escaped JSON with a `sha256:` prefix) or the delivery model's own format, never a local copy. A strict JSON load composes the `reject_duplicate_keys` and `reject_nonfinite_literal` hooks from `agent_tools.canonical` that its command needs, never a local hook. ([design](https://github.com/fagenorn/nix-config/blob/6b06a4e277ab8885d02cca9cec38e85a6de5dc55/.agents/artifacts/specs/2026-09-24-agent-tools-package-design.md))

### P5. Tests drive commands from source

A test runs a command as `python -m agent_tools.<area>.<module>`, or `python -m agent_tools.<module>` for a module the layout rule keeps at the top level, under the recipe's `PYTHONPATH` and imports modules normally. Only the installed-layout test, `tests/test_agent_tools_launchers.py`, touches the built launchers. ([design](https://github.com/fagenorn/nix-config/blob/6b06a4e277ab8885d02cca9cec38e85a6de5dc55/.agents/artifacts/specs/2026-09-24-agent-tools-package-design.md))

### P6. Skill-text tests pin only what a tool or subagent consumes

A test under `home/common/agent-skills/tests/` may assert the dispatch marker lines and the `Agent(...)` call lines mirrored in `model-matrix.json`, the carrier clauses `test_dispatch_contracts` places in dispatch regions, shell examples vetted by `test_shell_example_contracts`, frontmatter, the JSON key sets of lifecycle contracts, and `resolve-project` argv. No new test pins an English phrase. Existing phrase pins are deleted in the slice that slims their skill, and a heading anchor that only tests read may be renamed with its test in the same commit. ([design](https://github.com/fagenorn/nix-config/blob/6b06a4e277ab8885d02cca9cec38e85a6de5dc55/.agents/artifacts/specs/2026-10-07-issue-291-skill-best-practices-design.md))

### P8. The lifecycle guard stays standalone

The Claude Code lifecycle guard, `home/common/claude-code/lifecycle_guard.py`, stays a standalone, standard-library-only file that imports nothing from `agent_tools`, so of these rules only P3's ban on import machinery and `__file__` lookups binds it, and it runs `git`, `gh` and `jq` by the absolute store paths its **base policy** names, and its row check and look check by the store paths its wrapper passes as `--derive-bin` and `--look-bin`, rather than by name on `PATH`; it never runs a program named by the user-writable compiled policy. ([design](https://github.com/fagenorn/nix-config/blob/6b06a4e277ab8885d02cca9cec38e85a6de5dc55/.agents/artifacts/specs/2026-09-24-issue-176-lifecycle-guard-extraction-design.md))

### P14. A wording pin is a finding, and two scans enforce it for records and docstrings

A test that pins a decision record's or a module docstring's wording is two cases of the bar's wording-pin finding, and this rule is their source. No test asserts that text read from a record under `docs/areas/*/adr/`, or a module docstring, contains, equals, starts or ends with given words (for a docstring, or omits them), directly or through a saved or normalised copy. A check that a docstring exists, and a check of a command's `--help` usage output, are allowed. `tests/test_decision_record_wording.py` and `tests/test_module_docstring_wording.py` enforce it over every member of the `agent-workflow-tests` recipe plus `tests/*.py` and `home/common/agent-skills/tests/*.py`, never the two lifecycle guard test files; a suite member of a kind neither scan reads fails it, and a shell member may not name a record at all. Each scan keeps, by name, the wording tests on main when it landed whose source names a token, credential, secret, password or keychain (or, for records, calls `logins_in`); adding a test to a kept list is a new decision with its own record. Each scanner's module docstring states what it reads and what it does not see. (issues 1309 and 1311)
