# ADR-release-004 — A profile may declare no publication

- **Status:** accepted
- **Decided in:** #368 D1-D8, D11

## Context

A project may want its release targets, requirements and bindings declared and inspected without anything the driver would publish. Requiring one publication action would force a placeholder action that could never run.

## Decision

A profile with `"publication": "none"` is a publication-free profile. It declares its target and bindings like any other, passes the same same-repository rule, must author `activation` as `"none"` and `proof.obligations` as `[]`, and can name no recovery unit. It compiles to empty graphs and never reaches `TransactionStore.create`: `bind_candidate` refuses it with a `ValueError` naming the profile, and `release_adapter.core_binding` over it has no compiled node and refuses every request. Its targets are still listed in the derived `release.targets` member of the resolved snapshot, with empty `operations`, and `release profile inspect` reports it with exit 0.

## Consequences

- `capabilities.release` is `unsupported` when no profile declares a publication, before any admissibility or executable check.
- The grammar, the capability and the inspection treat the profile as a first-class member, so every later reader of a phase's nodes goes through `release_profile.phase_nodes`.
