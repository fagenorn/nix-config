# ADR-release-008 — Preview creates nothing and run re-derives the previewed plan

- **Status:** accepted
- **Decided in:** #128 D6, D17, D18; #69

## Context

An operator confirms irreversible actions from a preview. If the preview wrote state, or if `run` trusted the preview rather than the world, a confirmation could outlive the plan it was given for.

## Decision

`preview` is diagnosis and never mutates: it creates no directory, transaction or lock and calls no adapter, and it reports an unrunnable plan in its own document. `run` re-derives the plan exactly as `preview` does and writes nothing until it passes. Each confirmation token binds the plan digest, the action, its next attempt and the next acquisition ordinal, so a retry, a re-acquisition or a changed input yields a new token. A token outside the recomputed set refuses `confirmation_stale` and a missing one `confirmation_required`, all-or-nothing.

## Consequences

- A confirmation is valid for one plan only; an operator re-previews after anything changes.
- `run` repeats the verification reads that `preview` made, so a red or unfinished CI reserves no version.
