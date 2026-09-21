# Issue 39: CI contract minors

## Problem

The repository's CI and branch-protection contract has three small gaps. The
workflow inherits repository-default token permissions, the protection payload
uses the legacy context-only status-check shape, and the line-based job-name
extractor can return YAML quote characters as part of a check name. Together
these leave the workflow broader than necessary and make the offline guard less
exact than the GitHub API contract it protects.

The existing `Nix Eval` required check already reports successfully through the
GitHub Actions app. Its name, trigger behavior, evaluation command, and provider
must remain unchanged.

## Solution

Declare workflow-level `contents: read`, the only repository permission needed
by checkout and the referenced read-only Nix actions. Bind the required
`Nix Eval` check to the observed GitHub Actions provider app ID in the complete
branch-protection replacement payload. Extend the existing offline contract
tests so they reject broader workflow permissions, assert the full protection
payload, and prove quoted YAML job names are normalized to their unquoted
values.

Two approaches were considered. The selected approach extends the existing
small line-oriented workflow inspection and JSON fixture assertions. Replacing
that inspection with a YAML dependency would add an environment and parser
contract for three fixed fields without improving the API boundary under test.

## Decisions

- The workflow grants only read access to repository contents. All unspecified
  GitHub token permissions remain disabled by GitHub's workflow permission
  semantics.
- Required checks use the provider-bound `checks` API shape with the observed
  GitHub Actions app ID `15368`; the deprecated context-only form is absent.
- Job-name extraction supports the workflow's plain names and YAML's matching
  single- or double-quoted scalar forms, returning only the scalar contents.
- The protection test compares the complete replacement payload because the
  rollout command sends the whole document with `PUT`.

## Test seams

- The existing Python contract suite remains the public offline seam for both
  the workflow text and branch-protection JSON.
- A synthetic job-name fixture covers plain, single-quoted, and double-quoted
  names at the extractor boundary.
- Exact equality assertions cover the workflow permission map and the complete
  protection payload, so an added scope or omitted API field fails locally.
- Existing assertions continue to pin the `Nix Eval` name, pull-request
  trigger, ungated evaluation, and evaluated NixOS attribute.

## Out of scope

- Changing action versions, job names, triggers, concurrency, evaluation
  commands, or the protected branch.
- Applying branch protection remotely or changing repository billing and
  administrative settings.
- Adding required checks beyond `Nix Eval` or changing its provider.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Grant only workflow-level `contents: read`. | `actions/checkout@v4` recommends that scope; the referenced Nix actions only consume the token for read-only downloads and access tokens, and GitHub disables unspecified permissions when any are declared. | Granting broader scopes would violate the issue's least-privilege acceptance criterion. |
| D2 | Bind `Nix Eval` to GitHub Actions app ID `15368` and assert the complete replacement payload. | The successful live check run named in the audit contract reports that provider, and `just protect-main` sends the full JSON document with `PUT`. | Omitting `app_id` lets GitHub select a recent provider; `-1` accepts any provider and weakens the gate. |
| D3 | Keep the dependency-free line parser and normalize matching YAML quotes explicitly. | The suite intentionally runs without PyYAML and the workflow uses a fixed indentation convention. | Adding a YAML dependency expands the environment for a narrow scalar extraction fix. |
| D4 | Reject every job-level `permissions` override as well as any broader top-level grant. | Phase-5 Sol review identified that GitHub lets jobs replace workflow permissions, so checking only the top-level map would not prove the effective least-privilege contract. | Computing separate effective maps would add parser complexity when this workflow needs no per-job exception. |
