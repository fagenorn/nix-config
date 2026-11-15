# ADR-project-contract-006 — A drafted contract enters the adoption plan as a file it writes

- **Status:** accepted
- **Decided in:** issue 1067

## Context

`adopt-project plan` can only reach `ready` for a checkout whose contract exists, because the amendment it plans edits that file (ADR-project-contract-004). Issue #1067 asks for a way to adopt a repository that has no contract. Such a repository could therefore never be planned to `ready`, and a contract written into the checkout first would change the checkout the plan is meant to leave alone.

## Decision

`adopt-project plan --contract-draft FILE` takes one JSON object from a file outside the checkout and plans it as the file the adoption writes: the first operation is a `write-file` of `.agents/project.json`, with no `before`, whose content is the draft with the running platform's interval added when it declares none, keys in canonical sorted order because a stored plan keeps no other. The draft, exactly as given, is the plan's `contract_draft` member and an eleventh input of `plan_id`, so two drafts differing in one value give two ids. `apply` re-derives with the stored draft, and a draft changed after planning refuses `plan_stale` as `adopt.plan.inputs_changed`.

Every resolver check runs on the bytes the plan would write, in a scratch export of the base revision that holds them, so the checkout is never written by `plan` and a draft the resolver refuses is refused by the plan. The refusals are `adopt.draft.contract_present` (the checkout already has a contract file), `adopt.draft.unreadable`, `adopt.draft.inside_checkout`, `adopt.draft.invalid` (carrying the resolver's own violations) and `adopt.draft.id_taken` (the drafted project id is registered for another checkout, a check `derive_identity` skips for a contract id). The outcome is routed as for a checkout with no contract of its own.

## Consequences

- A plan without the flag is unchanged: it has no `contract_draft` member and its `plan_id` is the ten-input formula.
- The checkout is never written before `apply`, which writes the draft in its own worktree.
- Registration still reads the remote (ADR-project-contract-005), so the drafted contract registers only after the adoption reaches the remote.
