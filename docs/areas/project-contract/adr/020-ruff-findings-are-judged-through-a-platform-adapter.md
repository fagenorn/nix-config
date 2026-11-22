# ADR-project-contract-020 — Ruff findings are judged through a platform adapter

- **Status:** accepted
- **Decided in:** #1460 (per #1414, #1415, #1420)

## Context

The never-rise check (ADR-project-contract-017) takes any enforcer that prints one line per violation, but no enforcer judged Python: unused imports, commented-out code and unreasoned suppressions could rise unseen. The platform package already carries the helper commands every adopting project runs, so it carries the Python adapter too, and the Python stack shard names the rules it prints.

## Decision

**D1. Pinned Ruff, run by its command name.** The package builds a tools directory holding the pinned Ruff and every launcher exports it as `AGENT_PLATFORM_TOOLS`. The adapter runs `ruff` by its command name on a `PATH` that is that directory alone, which is how standard P3 of `docs/standards/agent-helpers.md` (an external executable runs by its command name on `PATH`) applies to a pinned tool. It never searches the inherited `PATH`. A tools directory that is unset, relative or without an executable `ruff` is `ruff_unavailable`.

**D2. Selection.** Ruff runs with `--isolated`, `--no-cache`, `--exit-zero`, target `py313` and the rules `E4`, `E7`, `E9`, `F` and `ERA001`. No Ruff configuration of the project is read, so a branch cannot deselect a rule it breaks, and `py313` is the newest syntax the pinned interpreter runs, so newer syntax is never a parse violation.

**D3. Mapping.** One table maps a Ruff code prefix to a rule id of the Python stack shard, the longest prefix winning; a parse error (`invalid-syntax`) is a syntax rule violation. A code the table does not map is `unmapped_code`, never a pass and never a guessed id.

**D4. Coverage.** A file is judged when it is a tracked regular text blob with suffix `.py` or `.pyi` at or below a directory holding a tracked regular text `pyproject.toml`, an empty one included. Each revision declares its own coverage, so base and branch are each read as committed.

**D5. Suppression.** Ruff's native `noqa` stays. A `# noqa`, `# ruff: noqa` or `# flake8: noqa` comment without a code and a reason is a `PY13` violation at its line. Comments are read only from tokens, so text in a string is no comment, and after a tokenize error only the comments read before it count.

**D6. Scratch materialization.** The covered blobs are written into a fresh scratch directory whose parent is outside the repository (`scratch_inside_repository`, checked before anything is created) and removed on every exit. A path that is absolute or holds an empty, `.` or `..` segment is `unsafe_path`. Two paths equal after Unicode normalization and case folding are `path_collision` on every host, and each file is created exclusively, so no blob overwrites another. A failure creating, writing or removing the scratch tree is `scratch_unwritable`. Ruff runs over batches of 200 paths, and one revision's pass is shared by every Ruff enforcer.

**D7. Count rules.** Each Python rule is its own count enforcer, so a rename or a move keeps the count and each rule is judged on its own.

**D8. A failing enforcer fails the check.** An enforcer that cannot judge raises `EnforcerFailed` with an enforcer and a reason, and the check reports `enforcer_failed` with the repair `violations.enforcer.repair`. A failed or malformed history read inside an enforcer is not an enforcer failure: it stays `history_unavailable` with `violations.history.fetch` (ADR-project-contract-017 D1).

**D9. Bounded command.** The `ruff-lint` command passes a finite timeout to every git and Ruff child, and in the conformance run the check's own child timeout applies.

## Consequences

- Existing findings are carried and none is fixed by this decision; only a rise fails.
- Other projects get the adapter through a lock bump of the platform package.
- A project with no `pyproject.toml` judges no Python.
- A branch that deletes its `pyproject.toml` lowers its own count; a reviewer sees the deletion.
- A repository whose covered paths differ only by case or Unicode normalization fails the check on every host.
- Rejected: honouring the project's Ruff configuration, because a branch could deselect a rule it breaks.
- Rejected: searching the inherited `PATH` for `ruff`, because a `doctor` run and the CI run could then judge with different Ruff builds.
- Rejected: an environment variable naming the Ruff binary itself, because P3 runs an external executable by its command name.
