# ADR-release-007 — A deploy watch is a watch-only activation unit of a release profile

- **Status:** accepted
- **Decided in:** issue 465 D2, issue 555 D3, D6, issue 582

## Context

A deploy that the publication triggers on its own (a GitHub Actions run, a Railway deployment) was watched by a separate `bindings.deploy` and `capabilities.deploy`. That path sat beside the release and could not be tied to the commit the release published.

## Decision

Project schema 2 has no `bindings.deploy`. A deploy watch is a `publication_triggered` activation unit of a release profile, served by the `github-actions-health` and `railway-deploy` adapters. Both refuse every `invoke` with `unsupported_operation` and answer the `running_subject_identity` predicate, so the driver inspects the unit and never invokes it. The unit watches what publication released: the candidate's `merge` binds into it, so the released commit is the merge commit of the release pull request.

## Consequences

- A deploy that is absent or still running is waited on within the unit's observation deadline and parks `attention_required` past it, so an absent deployment is never a success.
- A watch's health is read through the adapter's own provider tool, and the caller applies the credential binding.
