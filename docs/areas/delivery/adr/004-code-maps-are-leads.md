# ADR-delivery-004 — A code map is a navigation lead, never an authority

- **Status:** accepted
- **Decided in:** #354, #743

## Context

The design skill and the deliver-standard planner each leave a code map so the next agent need not rediscover the modules a change touches. A map is written from what one agent had read at one moment, so it goes stale, and a committed or cited map would read as a decision.

## Decision

A code map is a navigation lead. It is kept in the git directory of the worktree it was written in, so it is never staged, committed, pushed or reviewed, and no artifact-budget kind measures it. A plan never cites, links or copies it, and every mapped path and symbol that a plan writes into a task is checked against the current tree. Readers open the code to check a claim the map makes or where it is silent.

## Consequences

- A map is lost when its linked worktree is removed, and a rerun of `design` on the same spec overwrites it.
- A stale entry costs a lookup, not a wrong plan, because nothing is taken on its word.
