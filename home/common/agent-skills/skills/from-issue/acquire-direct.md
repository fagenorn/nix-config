# Direct autonomous acquisition

With literal `--auto` and no dispatcher envelope, resolve the immutable absolute `ledger_repo_root`, the positive issue and the configured positive attempt budget. Every call sends exactly this interface_version 2 shape, with `issue` and `attempt_budget_minutes` filled from them. Populate every observation kind the helper has requested at least once during this acquisition; keep an observation kind `null` until the helper requests it, keep `authorization_intents` `[]` until a contract is sent, keep every other slot as shown, and add no keys.

```json
{
  "interface_version": 2,
  "issue": 73,
  "attempt_budget_minutes": 180,
  "new_run": false,
  "owner_unavailable": false,
  "tracker": null,
  "worktree": null,
  "forge": null,
  "delivery_contract": null,
  "authorization_intents": [],
  "authority_observations": [],
  "reevaluation_evidence": [],
  "delivery_observations": [],
  "requested_scope": null,
  "recovery": null
}
```

Invoke only:

```text
workflow-state direct-owner --repo-root <ledger_repo_root> --request-file - <<'EOF' | artifact-budget validate-report --boundary workflow-response --input -
<request JSON>
EOF
```

Set `owner_unavailable` true only when the current user instruction explicitly authorizes takeover of the currently discovered unexpired active attempt. Set `new_run` true only when that instruction explicitly authorizes a new run after terminal replay. Never infer either from a restart, missing process handle, silence, an active ledger, terminal replay, a reopened tracker, or a desire to continue; the self-answer pattern cannot grant either. A resume is not a takeover: resuming a `suspended` attempt requires neither flag.

Validate the response as exactly one closed discriminator:

1. **`kind: observe`**: require exactly `interface_version`, `kind`, `issue`, nullable `run_id`, and `requirements`, then accept only the five exact requirement shapes, in the returned order: `{"kind":"tracker"}`; `{"kind":"recorded_worktree", "path":"<absolute-path>"}`; `{"kind":"candidate_worktree"}`; `{"kind":"forge_pr", "path":"<issue-branch-prefix>"}`; or `{"kind":"delivery_contract", "subject_id":"<issue>", "reason_code":"delivery_contract_required", "detail_pointer":null}`.
   Observe only what each asks: `tracker` through the tracker adapter; `recorded_worktree` by inspecting exactly the returned path; `candidate_worktree` by reserving and verifying one absent issue-branch candidate; `forge_pr` by observing the issue branch's pull request at the returned prefix, into `forge`. Build `delivery_contract` with one command.

   ```text
   workflow-state build-delivery --repo-root <ledger_repo_root> --kind contract --input - <<'EOF'
   {"issue": <num>, "worktree": "<absolute-worktree>", "source_kind": "explicit_user", "source_reference": "invocation:/from-issue <num> --auto"}
   EOF
   ```

   `worktree` is the recorded worktree when the helper named one, else the reserved candidate. Put the printed `contract` in `delivery_contract` and its `initial_intent` as the only member of `authorization_intents`. A builder refusal (exit 2, empty stdout) fails loudly; report its stderr line verbatim.

   Retain every fact requested during this acquisition, refresh a value whose external state may have changed, and resend them all by calling `direct-owner` again; never send a fact kind before the helper requests it. Unknown, duplicate, or malformed requirements fail loudly.
2. **`kind: owner`**: validate the exact closed response shape, then adopt its `ledger_repo_root`, `run_id`, `issue`, `attempt`, `owner`, `action_id`, `launch_kind`, `worktree`, `handoff_path`, and `deadline_at` as this invocation's complete persisted lifecycle identity, and keep its `custody`, installed `contract`, `contract_digest`, `pending_stage_ids`, `requirements`, `authority_evaluation` and `requested_scope` for the Phase-7 handoff. Continue the Phase 0–7 owner flow; spawn or reserve no other owner or worktree. When its `launch_kind` is `resume`, run `workflow-state resume-pack --repo-root <ledger_repo_root> --run-id <run-id> --action-id <action_id>` and, on exit 0, use its stdout as this relaunch's resume pack (the resume pack's checks).
3. **`kind: delivery_remainder`**: no implementation owner. Skip Phases 0–6 and launch ship-issue remainder mode through the `from-issue-ship-owner` site with the `## Remainder owner prompt` that `SKILL.md`'s index names for Phase 7, carrying the object verbatim. Validate the remainder owner's returned bytes at the `workflow-response` boundary (a `finish` response or a `delivery_stalled` checkpoint reply) and relay them unchanged; a return of only the re-entry line `/from-issue <num> --auto` (a checkpointed denial) is relayed as that line without validation. This invocation writes no `finish` of its own.
4. **`kind: terminal`**: require exactly `interface_version`, `kind`, `issue`, nullable `run_id`, `source`, `reason`, `blockers`, nullable `result`, and `reentry`; return the compact response unchanged to the caller, stop before Phase 1, and install no waiter.

Clear the retained observation set on `owner`, `delivery_remainder`, `terminal`, or any failure. An unknown response kind, invalid shape, or loud helper error fails loudly and ends acquisition; it never falls back to another lifecycle or ledger-free route.
