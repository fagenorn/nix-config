# Artifact-path validation for diff-scope

Issue: https://github.com/fagenorn/nix-config/issues/38

## Problem

`diff-scope --artifact-path .//x` is currently accepted and normalized to `/x`.
That output is no longer repository-relative, so the helper silently accepts malformed
input instead of reporting the same CLI error used for absolute paths.

## Solution

Reject every artifact path that is absolute after the documented leading `./` prefixes
are removed. Keep valid `./x` normalization unchanged. Add a CLI regression test that
proves `.//x` exits 1 and emits the helper diagnostic prefix.

## Decisions

The normalization order is part of the CLI contract: remove leading `./` components,
then reject an absolute result before trimming a trailing slash or checking escape
components. This makes `.//x` fail loudly without broadening the accepted path syntax.

## Test seams

The existing subprocess CLI seam in `test_diff_scope.py` exercises `--artifact-path`
against a temporary Git repository and asserts both the exit status and diagnostic.

## Out of scope

No new path syntax, artifact matching change, or generated-output change is included.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Strip leading `./` before rejecting absolute artifact paths, including `.//x`. | Issue #38 and the existing contract that permits leading `./` but requires repository-relative paths. | Check only the raw argument, which lets the normalized value become absolute. |
