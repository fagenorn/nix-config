# Ship delivery recipes

`ship-delivery checkpoint|summary --context CONTEXT [--prior PAYLOAD ...]
[--input RECIPE|-] [--output NEW_PAYLOAD]` compiles observed facts into a canonical
`ship-checkpoint/v2` or `ship-summary/v2`. `CONTEXT` is the unchanged, tool-produced
`ship-handoff/v2` or `delivery_remainder`, stored under the primary checkout's
ignored `.agents/runtime/` so cleanup cannot delete it. Every context and prior
payload crosses `artifact-budget` validation before use. Prior payloads must
match this contract and custody. The compiler delegates all sealing to
`workflow-state build-delivery` and validates its final report. It executes no
forge effect and performs no ledger write. Checkpoints and successful summaries
also require `current-launch`; a stale launch can still describe its failure.

Exit 0 prints only canonical JSON. `--output` additionally retains those bytes
in a new file, refusing to overwrite an existing file. Exit 2 prints a diagnostic
on stderr and no stdout. A dependency refusal retains the command, exit code and
stderr. Input JSON rejects duplicate keys and non-finite literals. Unknown keys,
missing facts, invalid seals, stale custody and unresolved references refuse.
The engine still adjudicates the resulting checkpoint/finish, and effect fences
and scope echo checks still apply; compilation grants no permission.

Both recipe modes require `observed_at` (the UTC probe time). Optional common
keys are `selections`, `observations`, `authority` (default empty arrays),
`detail_state` (default `none`), `report_path` (default null), and `notes` (default
empty). Checkpoint additionally requires `requested_stage` (a contract stage ID,
or null). Summary instead requires `state` (`delivery_complete` or
`terminal_failed`) and `result` with exactly `state`, `pr_url`, `merge_sha`,
`issue_closed`. Result state is `merged` for completion, `stopped` or `failed`
for failure. The compiler supplies issue, custody, contract digests, sorted
sealed arrays, an empty reevaluation array and the legacy result envelope.

Each `selections` entry requires `kind`, `head`, `tree`, `review_ref`, `test_ref`,
`source_kind`, `source_reference`, `evidence`. `initial` also requires
`acceptance_ref` and forbids `parents`; `sync` instead requires the ordered two
`parents` and forbids `acceptance_ref`. Entries run in order, each emitting a
`selected_output` observation. The first sync extends the ledger's current
selection; later entries extend the preceding entry. Actual sync eligibility,
review and CI remain the shipping owner's duties.

Each `observations` entry has exactly `kind`, `source_kind`, `source_reference`,
`evidence`, `facts`. Source/evidence are actual probe provenance, never a generic
success claim. `facts` has the canonical builder's exact members:

| Kind | Facts |
|------|-------|
| `selected_output` | `selection` |
| `branch_published` | `head` |
| `pr_opened` | `pr_number`, `pr_url`, `head` |
| `pr_merged` | `pr_number`, `pr_url`, `head`, `merge_sha` |
| `tracker_closed` | `close_reason` (string or null), `observation_identity` |
| `tracker_held` | `comment_url`, `record_path` (relative), `acceptance_state` (`unmet` or `human_pending`), `observation_identity` |
| `remote_branch_absent`, `local_branch_absent`, `worktree_absent` | empty object |
| `implementation_delivered` | `selection`, `merge_sha`, `integrated_ref`, `merge_observation_id` |
| `cleanup_complete` | `remote_branch_observation_ids`, `local_branch_observation_ids`, `worktree_observation_ids`, `detail_pointer`, `read_evidence` |

`selection` must be `$selection`: the last selection built in this invocation,
or the ledger's current selection. An observation ID field instead takes
`$<observation_kind>`; ID arrays contain these references. References resolve
against earlier observations in this recipe and all `--prior` payloads.
Exactly one distinct observation must match; repeated copies of an identical
sealed observation are harmless. Missing/ambiguous matches refuse. Thus cleanup
can refer to prior absence observations without copying their sealed IDs.

Each `authority` entry has exactly `stage_id`, `authority_kind` (`native_guard`,
`host`, `provider`), `verdict` (`allowed`, `rejected`, `unknown`), `reason_code`,
`evidence`. Scope and launch are derived from the validated context. Use only an
actual authority response, including rejection and partial effect evidence.
An already-true stage takes an observation alone, never invented authority.

For example, after a merge was observed, request its next stage with this recipe
(real invocations substitute the actual probe values):

```json
{"observed_at":"2026-10-22T15:00:00Z","requested_stage":"close_tracker",
 "observations":[{"kind":"pr_merged","source_kind":"provider",
  "source_reference":"gh:pr:5","evidence":"state=MERGED; mergeCommit observed",
  "facts":{"pr_number":5,"pr_url":"https://github.com/example/project/pull/5",
   "head":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
   "merge_sha":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}}],
 "authority":[{"stage_id":"merge_pr","authority_kind":"native_guard",
  "verdict":"allowed","reason_code":"guard_allowed","evidence":"native guard allowed merge"}]}
```

Pass the compiler's stdout directly to `workflow-state checkpoint-delivery`,
then validate the response at `workflow-response`. Retain the merge payload for
completion's `$pr_merged` reference. After the final effect, compile a summary
with the last authority/absence plus `implementation_delivered` and
`cleanup_complete`; reference the prior merge and absence payloads with
`--prior`. Submit summaries only where the caller owns `finish` (a remainder
owner does; implementation shipping returns it to its parent). No last-cycle
checkpoint precedes that summary. Denial checkpoints must suspend at human_gate;
they have no subsequent summary or finish. Full close, hold, sync, denial and
completion examples run against the real engine in `test_ship_delivery.py`.
