# ADR-guard-005 — The raise-label refusal catches mistakes; the required check enforces

- **Status:** accepted
- **Decided in:** #294; `.agents/knowledge/rejections/ungated-agent-merges.md`

## Context

The `instruction-budget-raise` label lets a change exceed the instruction budget, and only the owner may apply it. An agent can add a label with `gh pr edit --add-label`, with `gh api`, with a GraphQL mutation or with `curl`, and Codex has no hook at all.

## Decision

The guard refuses an agent adding the label through the one door it can read, a `gh` invocation whose `--add-label` value contains it, in every repository and before any other verb is judged. This catches the mistakes of a cooperating session and is not enforcement. The protection that holds is the required `Instruction Budget` check plus the owner seeing the label on the pull request.

## Consequences

- `gh api`, GraphQL and `curl` are outside the guard, so an agent that means to add the label can.
- Other labels, `--remove-label` and quoted mentions pass, so the guard stays quiet outside the one case it exists for.
