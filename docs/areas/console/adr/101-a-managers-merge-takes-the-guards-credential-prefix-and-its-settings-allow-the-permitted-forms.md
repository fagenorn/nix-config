# ADR-console-101 — A manager's merge takes the guard's credential prefix and its settings allow the permitted forms

- **Status:** accepted
- **Decided in:** #1592

## Context

The guidance of a project such as jarbird prefixes `gh` with `env -u GITHUB_TOKEN -u GH_TOKEN`. The lifecycle guard admitted that spelling, but the permit read `env` as a wrapper and refused with `ALONE`, which names no form. The auto-mode classifier then refused the exact form (the second part of this record).

## Decision

**D1. The permit takes the guard's prefix set.** A merge or rerun may follow one credential-scrub prefix, exactly a spelling the lifecycle guard accepts, stripped once. The release run takes none (PD2, PD3).

**D2. A spelling refusal names the cure.** `ALONE` and `NOT_GRANTED` for a merge or rerun carry the missing flags whenever the words are readable, the accepted form filled with the project's slug and strategy, and the prefix clause the guard prints. State refusals name only their problem (PD4).

**D3. A leading release run the permit cannot read is denied.** The release allow rule (D4) matches any text after `release transaction run `, so a spelling that got no decision would run unjudged by both the permit and the classifier. A command whose text begins with `release transaction run` and that is neither the plain run nor an abandon or dispose is denied with `RELEASE_SPELLING` (PD9).

## Consequences

- The permit and the guard agree on the prefix, and a test holds them equal.
- `permit.landed` records a prefixed merge too.
- The spellings ADR-console-098 let fall to the classifier now get `RELEASE_SPELLING`, while those that do not begin with the run (a wrapper, `xargs`, a shell variable) still fall to it.
- Related: ADR-console-094, ADR-console-098.
