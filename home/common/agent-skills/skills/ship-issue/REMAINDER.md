# Remainder mode

## Entry and start points

Entered with a validated `delivery_remainder` object (from-issue's remainder
owner prompt) instead of a handoff: validate it at the `workflow-response`
boundary before decoding. Its `custody` (a remainder, whose `action_id` is
`<issue>:r<n>:<launch>`), `contract`, `contract_digest`, `worktree` and
`pending_stage_ids` are the whole identity; there is no spec, plan or reviewed
head to review, so skip Phases 0–5. Run `## Delivery loop` from the ledger's
ready stage, starting with its synchronizing null-scope checkpoint. When
selection is pending, build it from the PR head
(`gh pr view <pr-num> --json headRefOid`) and that head's tree with literal
refs — `acceptance_ref` the issue URL
(`https://github.com/<resolved-repository>/issues/<num>`), `review_ref` `unknown`,
`test_ref` `checks` — so a relaunched remainder owner re-derives the identical
selection. When the merge is pending, start at the merge gate: Phase 6's CI wait and Phase 7's gate and fence still bind, and so
does the post-selection sync route, which also folds a merge that already landed
at a sync run. A selection this owner did not build, such as that route's first
`prior_selection` or the one `implementation_delivered` names, is the ledger's
current selection: read it with `--kind current-selection`, fed the installed
contract. Otherwise start at the first pending cleanup cycle. `## Launch guard`
fences with this custody's `action_id`.

## Close or hold from the PR body

A remainder has no handoff, so it takes the close-or-hold choice from its PR
body. On every remainder entry, whichever cycle it starts at (including a
cleanup cycle after `close_tracker` is already observed), run
`gh pr view <pr-num> --repo <resolved-repository> --json body` and take the
body's one `Acceptance state:` line, its one `Acceptance record:` line and its
acceptance table. `met` or `not_applicable` closes and `unmet` or
`human_pending` holds, exactly as in Phase 8 step 1. A missing or repeated line,
or a value outside those four, stops before its next effect with
`terminal_failed`, whose notes name the line; never default. When the stage is
already observed as a hold, recover the hold comment URL from
`gh issue view <num> --json comments` (the earliest comment whose first line is
`Held for verification: <PR URL>`) for the summary's notes instead of posting a
second comment.

## Exits and finish

A denial or a `delivery_stalled` reply ends a remainder owner's loop exactly as
step 6 of `## Delivery loop` says: its whole return is the re-entry line or that
reply, and it writes no `finish`. Otherwise a remainder owner holds its custody,
so it writes its own `finish --summary-file -`. A remainder owner whose prompt
carries a `Lifecycle worker:` line releases every worker it registered and
then itself with
`workflow-state release-worker --repo-root <ledger_repo_root> --run-id <run-id> --worker-id <worker_id> --event returned`
after its last commit and immediately before its own `finish`; after that
release it creates no commit. After the last cycle, validate the
`ship-summary/v2` (its `historical_owner_result` is the legacy row) and write it
in one command, then return exactly the validated reply and nothing else:

```text
workflow-state finish --repo-root <ledger_repo_root> --run-id <run-id> --summary-file - <<'EOF' | artifact-budget validate-report --boundary workflow-response --input -
<canonical ship-summary/v2>
EOF
```
