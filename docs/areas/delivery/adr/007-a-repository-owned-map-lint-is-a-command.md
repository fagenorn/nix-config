# ADR-delivery-007 — A repository-owned context-map lint is a `context-map-lint` command

- **Status:** accepted
- **Decided in:** issue 873

## Context

`context-map-lint` enforces one map budget and one default area budget for every repository. A repository that outgrew them took its own copy of the lint into its CI with its own budgets, and the machine-global tool and the grill-with-docs skill kept failing a map that repository's lint accepts, so each grill session folded glossary terms to satisfy a budget the repository had already replaced.

## Decision

A repository that owns its context-map lint declares it in its project contract as the `commands` entry with the id `context-map-lint`. The caller that resolved the contract passes that entry's argv to the global tool after `--repo-lint`; the tool then runs none of its own checks, runs that command in the repository root and exits with its status. The skill names the default budget only as a default. A repository without the entry is linted exactly as before.

## Considered options

- **Budgets as a new contract member.** Rejected: it grows the schema for two numbers, and a repository that owns its lint may differ in rules as well as budgets, so the tool would still disagree with it.
- **The tool resolves the contract itself.** Rejected: the tool takes the root and the selected map as arguments and reads no project policy, which is what lets another project's CI call it at a stable path; the caller already holds the resolved contract.

## Consequences

- The id `context-map-lint` is an agreed name, not a schema member: the resolver validates the entry as it does any command and gives the id no meaning of its own.
- The command runs in the repository root, whatever `cwd` its entry declares, and receives no map argument: it selects its own map.
