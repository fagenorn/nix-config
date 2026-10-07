# Dispatcher-owned acquisition

A dispatcher supplies a lifecycle envelope: `ledger_repo_root`, `run_id`, `attempt`, `owner`, `action_id` and the normalized `worktree`, plus the canonical-JSON owner object. A generic `delegate` owner receives this same envelope. Require all six fields and the object.

Pipe the object through `artifact-budget validate-report --boundary workflow-response --input -` before decoding it, and require its identity to equal the six fields (for a `delivery_remainder`, `attempt` is its `source_attempt` and `action_id` its custody's `action_id`).

- `kind: owner`: this invocation's lifecycle identity and delivery envelope. Adopt it unchanged, with its `custody`, `contract`, `contract_digest`, `pending_stage_ids`, `requirements`, `authority_evaluation` and `requested_scope`.
- `kind: delivery_remainder`: no implementation owner. Skip Phases 0–6 and hand it verbatim to the Phase-7 remainder launch (the `## Remainder owner prompt` that `SKILL.md`'s index names for Phase 7), then relay that owner's validated reply unchanged: its `finish` response or a `delivery_stalled` checkpoint reply. A return of only the re-entry line `/from-issue <num> --auto` (a checkpointed denial, which already suspended the remainder) is relayed as that line without validation. This invocation writes no `finish` of its own.

A partial envelope, a missing or invalid object, or an identity mismatch fails loudly; this route performs no other acquisition.
