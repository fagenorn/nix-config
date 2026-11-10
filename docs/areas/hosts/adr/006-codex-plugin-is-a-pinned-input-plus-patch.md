# ADR-hosts-006 — The Codex plugin is a pinned upstream plus one repo-owned zero-context patch

- **Status:** accepted
- **Decided in:** `lib/agent-plugins.nix`; #790 for the `turnStatus` and `error` payload

## Context

`codex-plugin-cc` is the reviewer path to Codex, and the repo needs behaviour the upstream does not have: a reviewer that refuses a stdin or stdout another live reviewer holds (#693), and a `task --json` payload that says why a review failed, a usage limit included, and not only the job log (#790). The plugin is installed from a store path, so any change must be reproducible from the flake.

## Decision

The plugin comes from a pinned flake input, and one patch, `patches/agent-plugins/codex-plugin-cc.patch`, is applied to a copy of it in a store path that serves as the `nix-codex` marketplace. The patch is zero-context and is applied with `git apply --unidiff-zero`. When two branches edit it, they are reconciled by merging the patched source trees and regenerating the patch, never by merging the patch text.

## Consequences

- A flake update of the input can make the patch stop applying, and the build then fails until the patch is regenerated against the new pin.
- Every patch change bumps `patchRevision` in `lib/agent-plugins.nix`, which is part of the plugin version.
