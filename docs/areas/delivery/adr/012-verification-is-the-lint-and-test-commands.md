# ADR-delivery-012 — Verification is the lint and test commands, run from one member table

- **Status:** accepted
- **Decided in:** issue 1446 (owner decision issue 1430)

## Context

Verification of this repository was the single command `nix-build` (`just build`), which proves the Nix side evaluates and builds but runs none of the lints that pull-request CI runs and none of the suite. A change could pass verification and fail CI on a lint.

## Decision

- D1. The members of each command live in one module, `agent_tools.delivery.verification_command`, run by two argument-free recipes, `just lint` and `just test`. They are not recipe dependencies.
- D2. Every member of a command runs, in order, even after one fails. The run names each member that failed and exits 1, or names all members and exits 0.
- D3. `lint` runs `agnostic-lint`, `context-map-lint` and `instruction-budget` (`instruction_load check` with no base, so raise control against a base stays with CI). `test` runs `nix-build` (`just build`) then `agent-workflow-tests` (`just agent-workflow-tests`), with the same argv as the contract commands of those ids.
- D4. The pull-request CI steps that are not lints stay outside `lint`: runner setup, the flake checker, the host evaluation, the oMLX adapter check and the suite. `tests/test_verification_command.py` classifies every pull-request CI step and checks that each CI lint is a `lint` member.
- D5. The module reads no project policy. Its root is the current directory, which `just` sets to the justfile's directory, and it has no command-table row, after the suite runner.

## Considered options

- **Recipe dependencies.** Rejected for D1's reason: `just` stops at the first failing dependency, and a test cannot read a dependency list as data.
- **Folding the oMLX adapter check and the `anis-desktop` evaluation into `test`.** Rejected because the issue fixes `test` to the build and the suite; folding more is a later decision.
- **Classifying CI steps by name.** Rejected because a lint appended to a named step would go unseen.

## Consequences

- A new or edited pull-request CI step fails `tests/test_verification_command.py` until someone classifies it.
- `nix-build` stays a read-only route outside verification.
- A held `command` check naming `nix-build` would wait as `command_not_verification`; none was open on 2026-11-21.
