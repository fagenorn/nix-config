# Phase-5 rollover (direct autonomous controller)

For every module-owned direct autonomous run, Phase 5 is the controller's last phase; one fresh owner takes implementation and delivery.

## Mandatory transfer gate

Finish Phase 5 and disposition every Blocking and accepted Should-fix finding. Apply accepted review edits and ledger writes, then commit the reviewed plan and ledger. After the last mutation, run fresh `artifact-budget check --kind design-spec` and `artifact-budget check --kind implementation-plan`, retain each checker's four metrics, and require both `within_budget`. If a commit hook changes either artifact, repeat check and commit until the roots and retained measurements agree. Require a clean worktree, then resolve the full 40-hex lowercase current commit as `reviewed_head_sha`.

Once no conversational dependency remains, call `workflow-state progress` for completed Phase 5 with truthful available usage and the exact gate values `next_needs_context=false`, `artifacts_sufficient=true` and `remainder_self_contained=true`. Require the persisted action `delegate`, then dispatch exactly one fresh issue owner at the existing `from-issue-phase-delegate` tier. This includes mechanical-only direct autonomous runs.

The continuation is one closed JSON object. Its `owner` is the validated interface-2 owner object this controller acquired, unchanged, with all 19 members; angle-bracketed strings stand for the helper's own values:

```json
{
  "owner": {
    "interface_version": 2,
    "kind": "owner",
    "ledger_repo_root": "/absolute/primary-checkout",
    "run_id": "direct-74-000001",
    "issue": 74,
    "attempt": 1,
    "owner": "74:1",
    "action_id": "74:1:1",
    "launch_kind": "spawn",
    "worktree": "/absolute/.worktrees/worktree-issue-74-cache",
    "handoff_path": null,
    "deadline_at": "2026-08-20T12:00:00Z",
    "custody": {"kind": "implementation", "attempt": 1, "launch": 1, "action_id": "74:1:1"},
    "contract": "<the installed delivery-contract/v1 object>",
    "contract_digest": "<sha256 digest of that contract>",
    "pending_stage_ids": ["select_reviewed_output", "publish_branch", "open_pr", "merge_pr", "close_tracker", "delete_remote_branch", "remove_worktree", "delete_local_branch"],
    "requirements": [{"kind": "scope_tuple", "subject_id": "select_reviewed_output", "reason_code": "scope_tuple_required", "detail_pointer": null}],
    "authority_evaluation": null,
    "requested_scope": null
  },
  "reviewed_head_sha": "0123456789abcdef0123456789abcdef01234567",
  "spec_artifact": {"kind": "design-spec", "path": "<passed-spec-artifact>",
    "metrics": {"root_bytes": 1000, "total_bytes": 1000, "file_count": 1, "largest_member_bytes": 1000},
    "budget_status": "within_budget"},
  "plan_artifact": {"kind": "implementation-plan", "path": "<passed-plan-artifact>",
    "metrics": {"root_bytes": 2000, "total_bytes": 6000, "file_count": 3, "largest_member_bytes": 2000},
    "budget_status": "within_budget"}
}
```

Pass the unchanged owner object, `reviewed_head_sha` and the two measured artifact blocks only: no artifact contents, task-member paths, review transcript, conversation summary, alternate worktree, reconstructed lifecycle field or authorization flag.

Beside the continuation, never inside it, pass a resume pack: after `progress` persists `delegate`, run `workflow-state resume-pack --repo-root <ledger_repo_root> --run-id <run-id> --action-id <action_id>` with this controller's own `action_id`, and on exit 0 put its stdout in the prompt as a `Resume pack` paragraph. A refusal sends none and does not stop the transfer.

## Earlier controller stop

After delegation the controller's action set is exactly validate, relay, and stop. Two closed lines are matched byte for byte first: a return that is only the canonical re-entry line `/from-issue <num> --auto`, and a return that is only a canonical `Suspended (blocked_on=<value>). Resume: /from-issue <num> --auto` line. Each is relayed unchanged with no validation; the controller writes nothing and stops. Neither is a dispatch failure. Otherwise the received bytes are the delegated owner's durable `finish` reply, a workflow response: run `artifact-budget validate-report --boundary workflow-response` over them; on success, relay the canonical bytes unchanged and stop.

The earlier controller does not invoke `sdd`, edit implementation files, reacquire or call `direct-owner`, start or create a new attempt, dispatch a second owner, call `workflow-state finish` after delegation, or continue after the delegated report. A dispatch failure is the only terminal result it persists, and it is never permission to implement locally.
