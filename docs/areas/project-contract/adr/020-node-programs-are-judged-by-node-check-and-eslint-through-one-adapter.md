# ADR-project-contract-020 — Node programs are judged by node --check and ESLint through one adapter

- **Status:** accepted
- **Decided in:** #1467 (per #1415, #1414, #1437)

## Context

The never-rise check (ADR-project-contract-017) holds every registered enforcer's violation count level with the merge base, and no enforcer judged a Workflow program, so a syntax error or an unused binding in one passed it. The programs parse neither as an ES module nor as a script as written: each opens with an `export` and uses a top-level `return` and `await`, because the runtime loads the text as the body of an async function. ESLint alone would report one fatal parse error and no finding, and `node --check` alone would reject the file. Their existing findings are many and the sprint forbids editing them, so the gate has to be a count that may not rise.

## Decision

**D1. The programs stay unedited.** No behaviour is added to a Workflow program and none is edited, not even to lower a count; the never-rise counts for them are measured from outside them.

**D2. Coverage is the Workflow program shape, not a path list, and it holds across the comparison.** A file is a program at a revision when it is a tracked file whose path ends in `.js` and whose text has a line starting `export const meta`, the test the runtime harness applies. The check judges, on each side, every `.js` path of that side that is a program on either side, so a branch that breaks the `export const meta` line is still judged and reports `NODE11`. The adapter holds no repository path, so another project gets the same rule through a lock bump.

**D3. A program is linted as the runtime loads it.** The adapter rewrites the first `export const meta` to `const meta` and wraps the text as the body of an anonymous async function whose parameters are the runtime's eight names: one prefix line before the text, a closing line after it. The function declares no binding, so no program carries a finding for its own wrapper; the eight names are parameters, so redeclaring one does not parse, as at run time; no statement precedes the text, so a directive prologue stays one; every line keeps its number. Findings on generated tokens are dropped by position. `node --check` and ESLint both read the wrapped copy.

**D4. Five Node rules and one mapping.** `NODE11` a program parses (`node --check` and ESLint's fatal parse message, one violation per distinct line, each mapped into the source first), `NODE12` no unused binding, `NODE13` every name declared once and used as its kind, `NODE14` the rest of ESLint's recommended set, `NODE15` a lint suppression names its rule and a reason. Every rule of the pinned ESLint's recommended set maps to `NODE12`, `NODE13` or `NODE14`, and no other ESLint rule is selected. All five are count rules over the project, never per file.

**D5. ESLint's native suppression is kept and judged by `NODE15`.** ESLint applies its own disable comments. A second run with inline configuration refused lists every inline configuration comment; each is a `NODE15` violation at its line unless it is `eslint-enable`, or an `eslint-disable`, `eslint-disable-line` or `eslint-disable-next-line` that names at least one rule and has a reason after ` -- ` holding a letter or a digit. `eslint`, `eslint-env`, `global`, `globals` and `exported` comments always count, because configuration lives outside the program. The platform's own `suppress-standard:` marker keeps working (ADR-project-contract-019).

**D6. Node and ESLint are pinned by the platform package and run by their store paths.** The platform package carries a record of the two tools' absolute store paths, read under the platform root, else under `$HOME/.agents/share`, as the manifest is, never from `PATH`. The adapter runs both by those paths, because the never-rise counts must come from the ESLint the platform pins, and the CI suite's shell holds no ESLint at all. That departs from rule P3 of `docs/standards/agent-helpers.md`, so P3 names the exception, as P8 does for the lifecycle guard. The tools run with the environment `HOME` (a temporary directory) and `LANG` only, so `NODE_OPTIONS` and `ESLINT_USE_FLAT_CONFIG` cannot reach them.

**D7. Lazy and fail closed, with stable failure facts.** The record is read only when a revision holds a program, so a project with none needs no tools. A record that cannot be read, a tool that cannot start, times out, exits outside its expected codes or prints unusable output fails the check with `enforcer_failed` and the repair `platform.enforcers.install`, never a pass. Its facts are the tool and a reason from a closed set; the detail, which can name a home or store path, goes only to the standalone command's stderr. A failed blob read is no tool failure: the check keeps `history_unavailable` and its fetch repair.

**D8. The tests use the packaged tools.** The suite reads the tools from the platform package it tests, built from this repository, so a green local run shows the tools the platform ships. No CI file changes; the `Conformance` job gets the tools through the platform package it already runs.

**D9. `node-lint` is a registered command, not the gate**, as `size-lint` is (ADR-project-contract-017 D9): the gate is the never-rise check, because the existing findings make a plain run exit 1.

**D10. Complete tool output or a failure.** Each ESLint run must return one result per requested file, each naming it, with messages carrying an integer line and column; a `node --check` exit 1 must carry node's file and line and its `SyntaxError: ` line. Anything less is an `unreadable_output` failure, so a tool that prints an empty list cannot pass the gate.

## Consequences

- The existing findings of the two programs are carried by the computed baseline; fixing them is optional and only lowers the counts.
- Another project gets the adapter by a lock bump and is judged only when it tracks a Workflow program.
- An ESLint upgrade that adds a recommended rule fails `test_the_mapping_is_the_recommended_set_of_the_pinned_eslint` until the rule is mapped.
- Rejected: an ESLint configuration file in the repository, because the programs and their tree stay unedited.
- Rejected: linting the programs as written, because they do not parse.
- Rejected: running the tools by name on `PATH`, because the CI suite's shell has no ESLint and a host's would not be the pinned one.
