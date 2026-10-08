# Doc-Grounded Questions — reference

## Decision-log and standards homes

Each area in the map keeps its decisions in an `adr/` directory beside its `CONTEXT.md` (`docs/areas/<slug>/adr/`), and `docs/areas/system/adr/` holds decisions spanning areas. With no map, use only the relevant retained `bindings.paths.context` path; never infer a decision-log location.

Project standards deltas at `bindings.paths.standards` are a `docs/standards/` directory whose README index carries `governs:` globs, or in older repos a single `CONTRIBUTING.md` or `docs/coding-standards.md`. `~/.agents/standards/README.md` gives the precedence ladder.

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

## The question shape

> "`<CONTEXT-DOC>` defines '`<Domain Term>`' as `<the canonical definition>`.
> `<ADR-NNN>` settled that `<the relevant decision>` happens in `<component A>`,
> not `<component B>`. `<STANDARDS-DOC>` requires `<the applicable rule>` for all
> `<X>`-touching code. Given that, the open question is whether to extend
> `<the existing abstraction>` or add a sibling abstraction for the new
> `<edge case>` — what's your call?"

When the docs fully answer it: "Per `<ADR-NNN>`, `<the decision>`, so this goes there. Continuing."
