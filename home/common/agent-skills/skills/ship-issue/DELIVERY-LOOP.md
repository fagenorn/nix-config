# Delivery loop (lifecycle identity)

## Construction and transport

Use `ship-delivery checkpoint --context <context.json> --input -` (mode `summary`
for terminal reports). Save the received handoff/remainder bytes unchanged in the primary
checkout's ignored `.agents/runtime/` first; keep this context through cleanup.
Read the complete recipe API at `~/.agents/share/ship-delivery.md`.
Recipes contain observed facts, never sealed objects, custody, digests or IDs.
`--output <new-runtime-file>` retains the validated payload for later `--prior`
references; files must be new. Supply prior payloads containing the merge and
absence observations when completion refers to them. The helper resolves
`$selection` from this call's selection chain or the ledger, and `$<observation_kind>`
from earlier recipe observations and prior payloads; ambiguity refuses.

A lifecycle call may now begin with this compiler, fed a quoted heredoc:

```text
ship-delivery checkpoint --context <context.json> --output <new-payload.json> --input - <<'EOF' | workflow-state checkpoint-delivery --repo-root <ledger_repo_root> --run-id <run-id> --checkpoint-file - | artifact-budget validate-report --boundary workflow-response --input -
{"observed_at":"<UTC probe time>","requested_stage":null}
EOF
```

Add `--worker-id <worker_id>` to `checkpoint-delivery` when this run holds a
`Lifecycle worker:` line. The helper performs canonical construction and report
validation; it runs no effect and changes no ledger. A compiler refusal stops
before submission. Treat each validated response's state, pending stages and
requirements as current truth. `delivery_stalled` ends custody: write nothing
more and return the validated reply alone.

## Loop steps

1. **Synchronize.** Submit the empty null-stage recipe above as the first ledger act.
   Before selection, use the native guard and `check-launch` without checkpoints.
2. **Select after Phase 6's tip check.** Give `selections` one `initial` recipe over
   the reviewed head/tree, `acceptance_ref` the spec root, `review_ref` the durable
   review path (else literal review state), and `test_ref` `checks`. It emits the
   selected-output observation. Add `branch_published` and `pr_opened` observations
   of that head/PR, and request `merge_pr`. Fixed refs make relaunch deterministic.
   Run the post-selection sync trigger check before merge; sync links extend this
   selection and never replace it.
3. **One cycle per effect.** Request its stage (`merge_pr` was requested above),
   require the response's scope echo to equal the compiled payload's scope, and
   bind the invocation to it. Run `workflow-state current-launch --repo-root <ledger_repo_root> --run-id <run-id> --action-id <custody action_id>`
   immediately before and after the effect; require current.
   The next recipe records the effect's observation and an `authority` recipe
   naming that stage and the actual verdict/evidence, then requests the next stage.
   Order: `merge_pr` → `pr_merged`; `close_tracker` → `tracker_closed` or
   `tracker_held`; `delete_remote_branch` → `remote_branch_absent`; `remove_worktree`
   → `worktree_absent`; `delete_local_branch` → `local_branch_absent`.
4. **Already true.** Record observations alone, without authority or proposal:
   remote deletion by merge's `--delete-branch` (confirmed by empty
   `git ls-remote --heads origin <branch>`), and closure by merge on the close
   branch only. A hold always executes its close_tracker cycle under Phase 8's
   fences. Record its actual comment URL, relative Acceptance record, effective
   state and `observation_identity` `github:issue:<num>:held`; reuse the existing
   comment. Record `none` stops with terminal failure before any hold effect.
5. **Denial.** A merge refused for base conflicts takes post-selection sync,
   with no authority observation. An actual guard/host/provider denial requests
   the denied stage again, records rejected authority and any partial observation,
   and must return `state: suspended`, `blocked_on: human_gate`; otherwise fail
   loudly. Return only `/from-issue <num> --auto`. No summary or finish follows.
6. **Complete.** Do not checkpoint the last cycle. Compile a `summary` with
   `state: delivery_complete`, `result.state: merged` and the last cycle's
   authority plus absence observation. Add `implementation_delivered` with
   `$selection` and `$pr_merged`, and `cleanup_complete` referencing the three
   absence kinds and the checked detail/read evidence. `result.issue_closed` is
   false on a hold. Return canonical stdout; remainder mode submits it to finish.
   A failure compiles `terminal_failed` with a truthful `stopped`/`failed` result
   and partial observations. The compiler permits a stale launch's failure report
   but never its checkpoint or successful summary; no report restores authority.
