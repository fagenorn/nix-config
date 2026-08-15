# Doc-Grounded Questions — rationale, expanded guidance, examples

SKILL.md owns the pass itself; this file owns the why, the legacy fallbacks, and
the worked examples.

## Why this matters

The user's time is the bottleneck. The cost of asking a question that's already
answered in the project's context doc is not zero — it's:

- Time spent re-explaining
- Loss of trust that you've done the reading
- Risk that the user briefly forgets a decision and answers inconsistently with
  the existing doc

Worse: proposing options where one of them violates the coding bar is asking the
user to validate a wrong answer. Drop those options before asking.

## Step 1 expanded — the context map

Always read the map in full — it is capped at 150 lines and tells you what
exists. Opening every area file defeats the point; the map exists so you can
skip the ones that don't apply. If a term in your question is defined in an area
you opened, use the canonical term and don't ask the user to disambiguate it
again.

**No map?** Fall back to the legacy layout: read whichever of `docPaths.context`,
`CONTEXT.md`, `GLOSSARY.md`, `DOMAIN.md` or a top-of-`README` domain section
exists — whole when it is short, by governing section when it is not (see the
long-doc rule below). Read it once, not per question.

## Step 2 expanded — decision-log homes

Areas own their decisions: each area in the map has an `adr/` directory beside
its `CONTEXT.md` (`docs/areas/<slug>/adr/`), plus the reserved
`docs/areas/system/adr/` for decisions spanning areas. Legacy fallback, for
repos with no `docs/areas/`: `docPaths.adrDir` if configured, else whichever of
`docs/adr/`, `docs/adrs/`, `docs/decisions/`, `adr/` exists.

## Step 3 expanded — standards layers

Load a stack shard only when the change's file extensions match it. Project
deltas live at `docPaths.standards` (a `docs/standards/` directory with a README
index carrying `governs:` globs, or a single `CONTRIBUTING.md` /
`docs/coding-standards.md` in older repos). See `~/.agents/standards/README.md`
for the precedence ladder.

## Step 4 expanded — the long-doc rule

Past ~400 lines, read a doc by governing section rather than whole: grep its
headings first, then open only the sections covering the components in play. The
same cap governs any other long doc this pass sends you to; the context map is
the exception, and only because it is capped at 150 lines by design. A large
architecture doc read end-to-end can cost more than every other step of this
pass combined, and its two or three relevant sections answer the question just
as well.

## Cache example

```md
# Grounding — <phase>

## Areas loaded
- Billing (`src/billing/**`) — Invoice, Dunning, Settlement
- Ordering (`src/ordering/**`) — Order, Customer

## Constraints found
- ADR-system-007: Ordering and Billing communicate by domain event, never synchronous HTTP.
- the-bar.md: fail-loud at closed-set dispatch sites.
- docs/standards/testing.md: endpoint tests share the API factory fixture.

## Areas deliberately not loaded
- Fulfilment, Identity — no path or term overlap with this issue.
```

Never write the cache inside the working tree: a committed cache collides across
parallel runs (observed: two `--auto` branches add/add-conflicted on
`.claude/specs/GROUNDING.md` at merge).

## The question shape

Substitute your project's real terms and decisions for the placeholders:

> "`<CONTEXT-DOC>` defines '`<Domain Term>`' as `<the canonical definition>`.
> `<ADR-NNN>` settled that `<the relevant decision>` happens in `<component A>`,
> not `<component B>`. `<STANDARDS-DOC>` requires `<the applicable rule>` for all
> `<X>`-touching code. Given that, the open question is whether to extend
> `<the existing abstraction>` or add a sibling abstraction for the new
> `<edge case>` — what's your call?"

This does two things at once: shows the homework, and frames the question
precisely around what's actually unknown. When the docs fully answer it:
"Per `<ADR-NNN>`, `<the decision>`, so this goes there. Continuing."

## Cost note

A grounded pass is the map (≤150 lines) plus the one or two area files that
actually apply, plus a handful of greps — seconds, not minutes, and bounded no
matter how large the project's docs have grown. If you're tempted to skip it
because "it'll take too long," you're either about to ask a question that
doesn't deserve to be asked, or you're loading area files the `governs:` globs
told you to skip.
