# ADR-console-083 — A reconcile plan proposes the commit environment a stranded hook needs

- **Status:** accepted
- **Decided in:** #1333

## Context

ADR-console-082 proposes the commit environment only for a checkout with no contract. A checkout that is already adopted, and whose installed commit hook calls a runner that only the development shell provides, planned `reconcile` with no environment and failed at the adoption commit with `exec: prek: not found`. ADR-project-contract-009 gives the adopter `--commit-environment`, which adds the command to an existing contract.

## Decision

**D1. When the proposal is made.** A fresh registration run of a checkout that has a contract proposes the commit environment when `HEAD` holds a root `devenv.nix` and an installed commit hook is stranded (D2). Otherwise the run plans as today.

**D2. What stranded means.** A hook is stranded when it execs a runner that no candidate path resolves, judged against the console process's own `PATH`, because Apply's commit inherits that environment. Reading runs no hook. A hook the parser cannot judge is not stranded.

**D3. The row carries a one-field draft.** The row holds the `commit-environment` record as its draft, the Apply card states its line first, and `Not now` and Change work as in ADR-console-082 D3. The answer `none` plans as today, and a changed command is planned again through the adopter, never through a draft file.

**D4. The adopter decides whether the contract already names one.** A contract that already names a commit environment is kept (ADR-project-contract-009 D2), and the console then drops the proposal, because the plan carries no `commit_environment` member.

**D5. The drafted path keeps ADR-console-082 D1.** A checkout with no contract is proposed its command exactly as before.

## Consequences

- This amends ADR-console-082's consequence that an existing contract is never changed: a reconcile plan can add the binding and the command.
- The command must be on the console service's `PATH`.
- The behaviour is pinned in `tests/test_console_approve_service.py` and `tests/test_console_commit_failure.py`.
