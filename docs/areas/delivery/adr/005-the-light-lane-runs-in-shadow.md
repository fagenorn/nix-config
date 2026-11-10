# ADR-delivery-005 — The light-lane verdict is recorded while every attempt still runs full

- **Status:** accepted
- **Decided in:** #279

## Context

`lane-triage` can say that an issue qualifies for the project's light lane. Acting on that verdict before it has been judged against real deliveries would skip steps on the strength of an unproven rule.

## Decision

`lane-triage` only reads the owner's triage record and `bindings.workflow.light_lane` and prints `{hits, lane, mode}`; it writes nothing. The owner's Phase 0 records the verdict, and every attempt still runs the full route.

## Consequences

- The verdict costs nothing and changes nothing, so the rule can be judged against real deliveries before it is trusted.
- A project that declares no light lane, or `null`, gets exit 2 with `light_lane_unsupported` and stays on the standard route.
