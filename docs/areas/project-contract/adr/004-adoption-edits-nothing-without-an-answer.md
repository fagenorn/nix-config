# ADR-project-contract-004 — Adoption edits a path literal only on an explicit answer

- **Status:** accepted
- **Decided in:** issues 350, 372, 376, 380

## Context

A relocation leaves path literals in tracked tooling files pointing at the old place. Whether a literal should follow the move depends on what the file means by it, which a scan of the text cannot tell, and an edit committed in the adoption commit is hard to take back.

## Decision

`adopt-project plan` asks about every occurrence of such a literal and offers `extend`, `rewrite` and `retain`, each only where it applies. A policy for a file class may be answered once, and its table value is a recommendation that is printed and never applied: nothing is edited without an answer. Every answer enters `decisions.answered` and so `plan_id`, and `apply` re-applies them from the stored plan, so the plan id authenticates them.

## Consequences

- An unanswered occurrence keeps the plan `draft` through `no-open-decisions`.
- A policy answer decides only the occurrences that have no answer of their own.
- The `git grep` prefilter scans a file only when it holds the first path segment of a move source as written, so a regular-expression spelling that escapes an interior dot of that segment (`foo\.bar` for `foo.bar`) is not found.
