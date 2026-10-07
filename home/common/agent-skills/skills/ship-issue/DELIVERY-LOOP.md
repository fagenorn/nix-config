# Delivery loop (lifecycle identity)

## Lifecycle calls and the checkpoint

Every lifecycle call is one command that reads its input from stdin through a
quoted heredoc, with the helper named bare or as `~/.agents/bin/workflow-state`,
optionally piped into or out of `artifact-budget validate-report --input -`. A
checkpoint is one such command:

```text
artifact-budget validate-report --boundary ship-checkpoint --input - <<'EOF' | workflow-state checkpoint-delivery --repo-root <ledger_repo_root> --run-id <run-id> --checkpoint-file - | artifact-budget validate-report --boundary workflow-response --input -
<ship-checkpoint/v2 JSON>
EOF
```

When this run holds a `Lifecycle worker:` line, append `--worker-id <worker_id>`
to every `checkpoint-delivery`: it excuses this run alone when its own
checkpoint suspends the launch.

A `ship-checkpoint/v2` has exactly `interface_version` (2), `issue`, `custody`,
`contract_digest`, `delivery_observations`, `authority_observations`,
`reevaluation_evidence` (each sorted by `id`), `requested_scope`,
`detail_state`, `report_path` and `notes`. Every scope, selection, observation
and authority observation comes from the builder named in `SKILL.md`'s
`## Delivery loop`, fed the installed contract and the kind's facts in a quoted
heredoc; never compose an id or digest. Treat each validated reply's
`pending_stage_ids`, `requirements` and `state` as current truth.

## Loop steps

1. **Synchronize.** The first ledger act is a null-scope checkpoint with empty arrays.
2. **Before selection.** Everything before the selection gate runs under the native guard and `check-launch`, with no checkpoint.
3. **The pre-merge selection gate.** Once Phase 6 (with its tip check) has passed, build the selection with `--kind selected-output` over the reviewed `HEAD_SHA`, its tree (`git rev-parse <HEAD_SHA>^{tree}`), and the fixed refs — the spec root for `acceptance_ref`, the durable review report path (else the literal review state) for `review_ref`, and `checks` for `test_ref` — so a relaunched owner re-derives the identical selection. Build the now-true `selected_output`, `branch_published` and `pr_opened` observations with `--kind observation` (the selection; the head; the PR number, URL and head), and checkpoint them through `checkpoint-delivery` with the `--kind scope` for `merge_pr`, the ready stage once they fold. Selection has no cycle of its own: its effect is that checkpoint write. Before the merge, run the trigger check of the post-selection sync route: a later sync of the integration branch extends this selection with a sync selection and never replaces it.
4. **Each post-selection effect is one cycle.** Checkpoint the stage's `--kind scope` as `requested_scope` (the merge's was checkpointed at the selection gate); require the validated echo to equal the scope you sent, and bind the actual invocation to it; run `~/.agents/bin/workflow-state current-launch --repo-root <ledger_repo_root> --run-id <run-id> --action-id <custody action_id>` and proceed only on `current: true`; run the effect; run `current-launch` again; then the next checkpoint carries the effect's observation, one `--kind authority-observation` for that scope and this launch (`launch_id` the custody `action_id`), and the next stage's scope. The stages, in the contract's order, are `merge_pr` → `pr_merged`; `close_tracker` → `tracker_closed`, or `tracker_held` on a hold; `delete_remote_branch` → `remote_branch_absent`; `remove_worktree` → `worktree_absent`; `delete_local_branch` → `local_branch_absent`.
   - With a `delete_remote_branch` stage in the contract, `git ls-remote --heads origin <branch>` after the merge decides it: empty output is its observation (step 5), non-empty output makes the delete its cycle.
   - On a hold the `close_tracker` cycle runs Phase 8 step 1's hold branch (reopen when closed, the `needs-verification` label, the hold comment) under that stage's own scope and fences. Its observation is `--kind observation` `tracker_held` with the facts `comment_url` (the hold comment's URL), `record_path` (exactly the PR body's repository-relative `Acceptance record:` value, never an absolute path), `acceptance_state` (the effective state) and `observation_identity` `github:issue:<num>:held`. A hold whose `Acceptance record:` is `none` stops with `terminal_failed` before any hold effect: no hold exists without a record. A hold records exactly one such observation, reusing an existing hold comment's URL rather than posting a second.
5. **Already-true stages are observation-only.** A stage the previous effect already made true is recorded by its observation alone, without a proposal: remote deletion by the merge's `--delete-branch` and, on the close branch only, closure by a merge that closes the issue; a hold always runs its cycle. Fold it into the next checkpoint.
6. **Denials.** A merge the provider refuses because the PR cannot merge into its base is not a denial: record no authority observation for it, and take the post-selection sync route. A guard, host or provider denial of an effect is checkpointed with the denied stage's scope as `requested_scope`, carrying the `authority-observation` with verdict `rejected` for that scope, plus the observation of any partial effect. It becomes the reducer's `human_gate` suspension: require the validated reply's `state: suspended` and `blocked_on: human_gate`, and fail loudly on anything else. Then print the canonical re-entry line `/from-issue <num> --auto` on its own line as your whole return and stop. The checkpoint already suspended the custody, so no summary or `finish` follows it. Never route around it. A checkpoint reply of kind `delivery_stalled` means the reducer already ended the custody: stop the loop, write nothing more, and return that validated reply as your whole result.
7. **Completion.** Do not checkpoint the last cycle: once delivery is complete `check-launch` reports the attempt inactive, which would make the parent's fence refuse. Build the last stage's absence, `implementation_delivered` (the current selection, merge SHA, integrated ref and the `pr_merged` observation id) and `cleanup_complete` (the three absence observation ids, the detail pointer and its read evidence), and return them with the last cycle's authority observation in a `ship-summary/v2` whose `state` is `delivery_complete` and whose `historical_owner_result` is the legacy `merged` row (`issue_closed: false` on a hold). A failure returns `terminal_failed` with the legacy `stopped`/`failed` row and the partial observations. Only after the last cycle, validate it with `artifact-budget validate-report --boundary ship-summary --input -` and return only canonical stdout.
