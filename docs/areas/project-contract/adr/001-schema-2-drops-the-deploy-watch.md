# ADR-project-contract-001 — Project schema 2 is schema 1 without the deploy watch

- **Status:** accepted
- **Decided in:** issue 579 (P11)

## Context

A deploy watch was authored as `bindings.deploy` and `capabilities.deploy` beside the release, and ADR-release-007 moved it into the release profile's activation units. The contract schema had to stop admitting the old members, and a project that still authors them had to be told how to leave.

## Decision

Platform 2.0.0 accepts project schema 2 only (`project_schema_versions` is `[2]`) and declares the migration `bindings-deploy.retire` from schema 1 to 2. Schema 2 is schema 1 without `bindings.deploy` and `capabilities.deploy`. A schema-1 contract is refused `unsupported_schema` with reason `project_schema_unsupported`, never read as a degraded schema 2, and `adopt-project plan` routes it as `migration_required` with the `bindings-deploy.retire` step.

## Consequences

- A project on schema 1 cannot resolve until its operator has run the migration; the steps are in [Retire the deploy watch](../../../guides/retire-the-deploy-watch.md).
- The resolver and adoption tests read a pinned schema-2 contract.
