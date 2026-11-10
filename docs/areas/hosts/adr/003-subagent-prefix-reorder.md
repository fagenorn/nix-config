# ADR-hosts-003 — A subagent's first user message is reordered so siblings share a cached prefix

- **Status:** accepted
- **Decided in:** #429; `docs/spikes/cache-proxy-prefix-retest.md` § Attempt 2

## Context

Two subagents of one type start with the same system prompt and the same attachments, but each first user message carries its own delegation prompt ahead of the `<system-reminder>` attachments. The prompt therefore ends the shared start-up prefix where it begins, ahead of attachments the siblings have in common. The proxy is the one place that can change the order without a change to Claude Code.

## Decision

With `--reorder` the proxy moves the delegation prompt behind the attachments that follow it and, below four cache breakpoints, marks the block before the prompt. It acts only on a subagent's first request, registers that agent id, and reorders a later request only for a registered id, so a forked subagent keeps its parent's prefix. The `x-anthropic-billing-header` line is never changed. Every request that is not of the exact accepted shape, and every failure of the transform, forwards the client's original bytes and headers.

## Consequences

- The re-test that admitted the reorder found the billing suffix equal and a gain of 6803 tokens, verdict go (`docs/spikes/cache-proxy-prefix-retest.md` § Attempt 2).
- A reordered body is re-encoded as compact UTF-8 JSON in its key order, so a reordered request is not byte-identical to the client's even where its content is.
- The registry of first requests is in memory, holds at most 4,096 ids and is forgotten on restart, so a restart turns the reorder off for the subagents already running.
- The reorder accepts only the attachment and budget-line shapes it knows, and passes any other body unchanged as `shape`.
