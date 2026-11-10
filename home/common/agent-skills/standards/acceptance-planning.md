# Acceptance planning rules

Read on demand when writing acceptance criteria (`to-issues`), mapping them in a plan (`writing-plans`) or holding an issue after merge (`deliver-direct`). A criterion is `code` (a test, the build or a CI job shows it), `evidence` (only a deploy, an activation or observation over time shows it), `human` (only a person can judge it) or `note` (a post-deploy reading the orchestrator records itself, R9). A held issue is open, labelled `needs-verification`, and carries one verify block in its hold comment; the system runs the block and closes the issue when its checks pass.

## Rules

- **R1. Pre-merge evidence is `code`.** Evidence that exists before merge (the pull request's CI, a local evaluation, a test tier, the merge commit's CI run) is a `code` criterion, graded after CI at ship, never a post-merge check.
- **R2. Approvals happen on the pull request.** Design, ADR, runbook and path-list approvals are given on the pull request before merge, never as a post-merge hold.
- **R3. `human` is narrow.** Use `human` only for senses, hands, credentials, money or taste, and write which one, and why, in the criterion.
- **R4. Every `evidence` criterion is a verify block.** It declares trigger, command, threshold and expiry, and is posted as a verify block that `verify-pending lint` accepts.
- **R5. Metrics are reported, never gates.** A cost, timing or rate threshold is a check with `mode: observe`: a miss files a follow-up issue instead of failing the hold.
- **R6. No hold over unmet code.** While a `code` criterion is unmet the issue is not held: finish it, or split the rest into a new issue filed by `forge-issue create --blocked-by <n>`.
- **R7. A human check blocks nothing.** A remaining human check goes into its own issue that blocks no other issue, so dependents wait only for the code.
- **R8. Do it, do not ask.** An action that stays within the owner's repositories, is reversible and needs no senses, hands, credentials, money or taste is done by the delivery itself and its evidence recorded at ship: creating and deleting refs, scratch branches or pull requests, a ready-mode run, pushing a branch. Ask only for an R3 reason, a change to a production system, or a genuine product or design decision. Evidence on infrastructure that exists for one run only is recorded when observed, never held as a recurring check.
- **R9. An orchestrator observation is a `note`.** When a decision says a post-deploy reading is the orchestrator's own observation, or not a hold, the criterion is a `note`, even when the reading is a cost, a time or a rate: it carries no verify block, no script and no metric, is never held and not graded at ship, and the close-out lists its text in a comment for the orchestrator to record.

## Verify block fields

`verify-pending` owns the block's grammar, and its refusals name each field. The four parts R4 requires map to:

| Part | Block field |
|---|---|
| trigger | `when`: `deployed_includes`, `released_includes`, `ci_run_includes`, `not_before` or `days_after` |
| command | `run`: a command id that is a member of `workflow.verification`, a committed executable script or a built-in probe |
| threshold | the run's exit (0 met, 1 not met, 75 not yet) and the optional `expect`; `mode: observe` for metrics (R5) |
| expiry | `expires_after_days` (default 21) and `on_expire` |

A `human` check uses an `ask` or `act` run and a `reason` (R3).

The unattended runner runs a command check only when its command id is in `workflow.verification`; any other declared command lints as valid but stays pending as `command_not_verification`, so a check that must complete without a person uses a member of that list, a script or a probe.

## Linting a hold

`verify-pending lint --input <hold comment> --repo-root <checkout>` checks the block before it is posted. Give it what only the caller knows: `--code-unmet <AC>` for each unmet `code` criterion (R6), `--pr-workflow <name>` with `--pr-head <sha>` for the pull request's required workflows (R1), and `--blocks <issue>` for each issue this one blocks (R7). It refuses an ask for a document approval (R2) and a `human` check without a reason (R3). After the merge, regrade each `code` criterion once required checks pass. If a `code` criterion is still unmet, do not hold: follow R6. If no criterion of any kind is left open (a `note` is never open), close the issue with the evidence; there is no hold and no verify block. Otherwise every `code` criterion is met and only `evidence` or `human` checks remain: post the hold comment for them, add the `needs-verification` label, and run `verify-pending run --host <host> --repo <slug> --issue <n>` once: it closes the issue when a check is already met. `--repo` matters: `--issue` alone matches that number in every project the run covers.
