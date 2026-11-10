# ADR-claims-007 — Blocking edges are filed and confirmed by database id

- **Status:** accepted
- **Decided in:** issue 697 D1, D3, D6, D7, D10

## Context

Blocking edges between issues were prose that no tool could read. The forge's dependencies endpoints record them natively, but they take a database id, not an issue number; GitHub also redirects a transferred issue's number to its new home, where the same number may be another issue. A filing call can fail after the issue exists, and a link call can answer success without the edge being recorded.

## Decision

Every link posts the database id read from `repos/<slug>/issues/<n>` (`.id`), and identity is the database id everywhere: an existing edge and the read-back match requested issues by `id`, never by `number`. Nothing is filed on a bad number: `create` and `link` resolve every requested number to an issue of `--repo` before any POST. After posting, both lists of the issue are read back, and `create` succeeds only when each id set equals the requested one, `link` when it contains it. An exit 1 with `issue` set means that issue exists and `link` repairs it; a filing call that failed or lost its response is `create_unconfirmed`, and the title is looked up on the forge before filing again.

## Consequences

- Each filing costs a lookup per requested number plus two read-back calls.
- A caller must tell the exit-1 outcomes apart; refiling after `create_unconfirmed` without a lookup would duplicate the issue.
- An issue of another repository that shares a requested number is reported as `unexpected_*` and never counts as the edge.
