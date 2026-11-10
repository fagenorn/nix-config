# ADR-release-003 — A release profile is judged by grammar inside resolve and by admissibility apart

- **Status:** accepted
- **Decided in:** #124 D1, D3, D7, D23

## Context

The project contract is resolved by every workflow, but whether a release profile can run depends on the transaction core's compilers and on which adapter executables a host has. Judging both inside resolve would make every resolve depend on the host and on the core.

## Decision

Two tiers judge a profile. The grammar (`release_profile.grammar_violations`) runs inside `resolve-project resolve` and reads only the authored document and the registered descriptors: every violation is `invalid_contract` with a `contract.release.*` repair. A profile that names an adapter outside the closed registry, or an operation the adapter does not support, is a grammar violation and never a lookup fallback. Admissibility (`release_profile.admissibility_findings`) runs over a grammar-valid profile only, and the same function feeds `capabilities.release`, so the capability and the inspection report agree by construction.

## Consequences

- A profile can be grammar-valid and still blocked: `capabilities.release` then reports `release_profile_inadmissible`, or `release_adapter_unavailable` when a bound adapter's executable is not on `PATH`.
- The core compilers, not the grammar, own the vocabularies and deadlines they judge, so a missing deadline is a compile rejection and never `invalid_contract`.
