---
name: ship-issue
description: Deliver a finished feature-branch worktree — sync integration branch, PR, review, CI, merge, close issue, clean up. Phase 7 of from-issue. Use for "ship #X", "land it".
---

# Ship Issue

Counterpart to `to-issues` and `from-issue`. Take a worktree branch with the implementation committed and deliver it: merged on the integration branch, issue closed, workspace gone.

## Project bindings (resolve first)

Run `resolve-project resolve --repo-root <checkout>` once at phase entry and retain the full `ResolvedProject` in memory. Resolve once at phase entry, retain the returned `ResolvedProject` in memory, and treat every resolver error as fatal before mutation or external effects. On refusal, preserve and report the resolver's `error.code`, `repair_id`, and ordered `violations` exactly; never translate it into a partial snapshot or fallback. The only sanctioned exception is `workflow-state build-delivery`, which performs its own sealed, read-only resolution when it builds a delivery object; this skill still never resolves again itself. Use `bindings.tracker`, `bindings.vcs`, `bindings.commands`, `bindings.workflow.review.code`, and `bindings.workflow.verification`; dereference verification IDs through `bindings.commands`.

For code review, select `bindings.workflow.review.code` and route retained
`capabilities.review.code` first. `blocked` stops; authored `unsupported` takes
only its documented route. Only `available` dereferences
`bindings.commands[review_id].argv` before execution.

A blocked required capability stops. An authored unsupported tracker takes the existing tracker-free route; the sync/verify/consolidate/merge machinery still applies.

Retained `capabilities.review.code` governs the full review route.

**Invocation paths.** From `from-issue`, treat the handoff as received stdin
bytes: pass them through `artifact-budget validate-report --boundary
ship-handoff --input -` before decoding any field. With lifecycle identity it is a
`ship-handoff/v2` carrying `custody`, the installed delivery contract, its initial
intent and the ledger's pending stages; ledger-free it is the legacy handoff with
a null lifecycle group. Either carries the fixed lifecycle
scalars, `spec_artifact`, `plan_artifact`, `head_sha`, `review_state`, `auto`, one
optional durable `report_path`, and notes. On entry, independently run
`artifact-budget check` for the design-spec and implementation-plan roots,
compare all four metrics, and recheck a non-null SDD detail root as a
review-package. Exit 2/3, stale metrics, a mismatch, or over-budget input stops
before Phase 0. After any later writer changes either artifact, repeat the same
checks before continuing. Standalone (`/ship-issue <num>`): `review_state` is
`unknown` unless the user supplies validated evidence of a completed sdd
two-axis review; derive the issue number and artifacts, then establish the same
checker-valid root/metric objects. The worktree state — not the handoff — is
ground truth.

Only after the plan's successful artifact-budget check, discover the plan members
locally from its validated index for `diff-scope` exclusion. Supply one argument for the plan root and each discovered member.
Keep that private
list inside ship-issue: do not put the member list in the handoff, report, or
review prompt.

## The flow

```
0. Pre-flight              → worktree clean, branch pattern ok, no PR yet
1. Sync integration branch → fetch + merge origin/<integration>, hybrid conflict policy
2. Verify locally          → lint + tests inside the worktree
3. Consolidate learnings   → see CONSOLIDATE.md; drop most candidates
4. Open PR                 → push -u; gh pr create with "Closes #<num>"
5. Review the PR           → merge-delta check or full two-axis review
6. Wait for CI             → gh pr checks --watch (one blocking call)
   Selection gate          → lifecycle identity only: select the CI-green head (## Delivery loop)
7. Merge                   → gh pr merge <pr-num> --repo <resolved-repository> --merge [--subject "<rendered subject>"] --delete-branch (true merge commit)
8. Cleanup                 → issue closed; worktree + branches removed
                             (lifecycle identity: each 7–8 effect is one ## Delivery loop cycle)
```

## Standing authorization

Standing authorization exists where repository policy or an explicit user grant
covers the concrete action, target, and external effect. Carry that grant across
phase and session boundaries; do not demand that Codex receive the same literal
command text again. A harmless quoting or spelling change and a transient command
failure do not erase scoped authorization. The launch guard, required CI,
reviewed-tip check, protected-branch rules, and the host's actual automatic
approval decision still bind.

In a qualifying repository, the lifecycle guard covers pushing a non-default
branch, opening a PR to the default branch, the guarded merge, branch deletion,
and worktree removal. Execute that authorized chain without a phase-boundary
re-prompt while every check above passes.

On a host whose permission layer adjudicates intent by review, use an existing
user grant when it covers the same chain. When authority is absent, take the
consolidated operator gate of [`HUMAN-GATE.md`](./HUMAN-GATE.md). An actual
denial stops the denied action; never route around it.

## Launch guard

The lifecycle ledger reserves one worktree per issue and hands a retry the
predecessor's worktree and branch on purpose, so a superseded attempt can still
push, open a PR and merge. Before **every write to the forge or to `origin` this
skill makes up to and including the merge**, re-validate that the handoff's
launch identity is still the launch the ledger entitles. The rule binds
regardless of tracker capability, so an unsupported-tracker invocation — which skips
Phase 4's PR but still pushes the branch — guards that bare `origin` push too:

```
~/.agents/bin/workflow-state check-launch --repo-root <ledger_repo_root> --run-id <run-id> --action-id <issue:attempt:launch>
```

`<issue:attempt:launch>` is the `action_id` the handoff carried, passed through
verbatim — never recomputed, never derived from `attempt`; the launch ordinal is
exactly the part this owner cannot know. The verb is read-only: it takes no
clock, holds no lock and creates nothing.

Proceed only on `current: true`. Refuse the write on `current: false`, a
non-zero exit, a missing helper, or output that does not parse into the exact
four keys `action_id`, `current`, `current_action_id` and `reason`. **This one
call does not follow this skill's degrade-gracefully rule for absent optional
helpers** — that rule is written for optional bindings, not for a safety check,
and following it here would turn the guard into a no-op precisely when the
environment is broken.

Guarded: the Phase-4 push, the Phase-4 PR create, every push in REVIEW.md's
five-step apply/push flow, and the Phase-7 merge. There is no post-merge
exemption: under lifecycle identity each post-merge effect is a `## Delivery loop`
cycle — the remote branch delete, and Phase 8's issue close, `git worktree
remove` and `git branch -d` — fenced by `current-launch` before and after the
effect exactly like the merge. Phase 1's merge from the integration branch and
Phase 3's local commits are not forge writes and are not guarded.

**A refusal is a stop that writes nothing anywhere.** Do not execute the write.
Make no further forge write, **no ledger write**, and run no cleanup: leave the
worktree, the branch and any PR exactly as they are, because the successor is
working in that same worktree on that same branch. Print the canonical re-entry
line `/from-issue <num> --auto` on its own line, then return a truthful
`stopped` ship summary (under lifecycle identity, the `historical_owner_result`
of a `terminal_failed` `ship-summary/v2`) whose notes name the refusal, the reported `reason`, this
`action_id` and the reported `current_action_id`. Its fields are `merge_sha:
null`, `issue_closed: false`, `discussion_items: []`, `pr_url` the PR when one
was already opened and null otherwise, and `detail_state: "none"` with
`report_path: null` — or the failure-only `unpublished` shape when Phase 5
retained readable Minor/Discussion findings, naming that retained source and its
root in notes and keeping the worktree. An `unpublished` `report_path` is
worktree-relative, not main-root-relative (REVIEW.md §"Durable
Minor/Discussion detail"). Phase 8 does not run and no delivery detail is
published: the successor owns that worktree and will produce its own.

Without lifecycle identity — a standalone `/ship-issue <num>`, or a handoff
whose lifecycle group is all-null — skip the guard silently: a ledger-free
invocation has no attempts and no supersession mechanism, and the handoff
validator's all-or-nothing group means it is never partially present. That is
the only skip, and it is a statement about the invocation, not about the
environment.

## Doc-grounded escalations

Before forming *any* user-facing question this skill raises mid-flow, invoke the `doc-grounded-questions` skill and read only the retained declared paths. Lead with what the relevant document says; ask only the genuinely open part.

## gh hygiene

Prefix a forge invocation only with the names in `bindings.tracker.credential_env.unset_before_invocation`; for example, an exhaustive list containing `GITHUB_TOKEN` yields `unset GITHUB_TOKEN && gh ...` when a harness token lacks access to the target org. When `bindings.tracker.cli` is `glab`, substitute the equivalent `glab` verbs.

Throughout, follow `writing-plans`' Payload discipline: targeted `rg` over whole-file reads, bounded reads, summarized command output, logs on disk, artifacts handed over as paths.

## Phase 0 — Pre-flight

Verify the workspace is shippable before doing anything destructive:

1. `git rev-parse --git-common-dir` ≠ `git rev-parse --git-dir` — a linked worktree, not the main checkout.
2. `git branch --show-current` matches the regex built from retained `bindings.vcs.branch_pattern` and `bindings.vcs.worktree.prefix`; both configured forms are valid. Extract `<num>`. An argument or handoff `issue_number` wins, but verify it matches the branch.
3. `git status --porcelain` returns nothing.
4. `gh pr list --head <branch> --json number,url` returns `[]` — no open PR for this branch.

Any failure: pause, ground, surface. Don't auto-fix the branch name or stash changes.

## Phase 1 — Sync from the integration branch

**Read [`SYNC.md`](./SYNC.md) first** — it owns divergence handling, foreign-commit checks, scope-creep sweeps (retirement/addition), the auto-resolve allowlist, and the conflict escalation format.

```
git fetch origin
git log origin/<integration>..<integration> --oneline
```

The load-bearing rules, in brief:

- Merging `origin/<integration>` into the feature branch is safe even when the local integration branch has diverged (expected under parallel `--auto` runs). **Anything that rewrites the local integration branch — reset, rebase, push — stops and surfaces; `--auto` never auto-resolves history rewrites.**
- Foreign commits on the branch (another issue's work) → surface, never clean up silently.
- Conflicts: the allowlist auto-resolves lockfiles, migrations and generated files, and always keeps `.claude/settings.json` out of the merge. **Everything else escalates one conflict at a time**; skipped conflicts pause the phase.

Otherwise `git merge origin/<integration>`; commit the merge with the configured merge-commit message. Don't squash.

## Phase 2 — Verify locally

```
<each bindings.workflow.verification command, dereferenced through bindings.commands>
```

Run every command id in retained `bindings.workflow.verification` through its
`bindings.commands` argv and cwd. A blocked verification capability stops and
reports its `reason_code` and `repair_id`; authored unsupported follows only its
documented no-verification route.

On a failing verification command, pause, ground, and surface; do not invent a
fix command outside retained `bindings.commands`.

Test failures: separate *environmental* (container connectivity, missing network, sandbox limits) from *real* by baselining the same project in a scratch worktree on `origin/<integration>`. Same failures → pre-existing; continue and note the baseline diff in the PR body. Different failures → real; pause, ground, surface.

## Phase 3 — Consolidate learnings

**Read [`CONSOLIDATE.md`](./CONSOLIDATE.md) first** — it owns the mining commands, rubric, destination table, and reporting format. Run its step-1 mining commands as actual tool calls *before* concluding anything: empty is a finding, not a default — earn it by mining. Promoted candidates commit as `docs(<scope>): <summary>`, following retained `bindings.vcs.commit.co_authored_by`.

## Phase 4 — Open PR

Skip entirely when the tracker capability is unsupported (push the branch and stop, or merge locally per the user's request).

When `## Standing authorization` finds no existing grant for these concrete
actions, enter Gate 1 of [`HUMAN-GATE.md`](./HUMAN-GATE.md) before running
anything below. Never use the gate to retry an actual denial.

Run `check-launch` (see `## Launch guard`); on anything but `current: true`,
stop without pushing. Then:

```
git push -u origin <branch>
```

Run `check-launch` again, then:

```
gh pr create --repo <resolved-repository> --base <integration> --head <branch> --title "<title>" --body "## Summary
<2-4 bullets of what shipped>

## Spec
<spec-path>

## Plan
<plan-path>

Closes #<num>"
```

This is the one form the lifecycle guard accepts: one command, those five flags in that order, `<resolved-repository>` the retained `bindings.tracker.repo_slug`, and the body a single double-quoted argument that may span lines but contains no `"`, `$`, backtick or backslash. A body written to a file, a heredoc or a command substitution is refused, so render the body in place.

Title: the issue title verbatim unless the implementation deviated meaningfully. Under 70 chars; details go in the body.

GitHub auto-close on merge fires only when the PR base equals the **default branch**; when retained integration and default branches differ, the real close mechanism is Phase 8's explicit `gh issue close <num>` — keep the `Closes #<num>` trailer for traceability, don't rely on it.

**Use full URLs, not bare `#N`**, in PR bodies, comments, and commit-message references (`https://github.com/<resolved-repository>/issues/<n>`) — GitHub resolves bare `#N` against the source repo context, which under cross-references lands on unrelated refs. The `Closes #<num>` trailer is the one exception.

## Phase 5 — Review the PR

```
BASE_SHA=$(git merge-base HEAD origin/<integration>)
HEAD_SHA=$(git rev-parse HEAD)
```

The branch normally arrives already reviewed on two axes by sdd's final review (conformance ∥ correctness); this phase reviews only what that review could not have seen — unless a risk signal calls for the full ladder. **Read [`REVIEW.md`](./REVIEW.md) before dispatching or applying anything.**

**Pick the path first.** Degrade to the merge-delta check when ALL of these hold; otherwise run the full two-axis review:

- `review_state` is `clean` (handoff / sdd report: both axis verdicts clean, or every residual parked-with-ruling). `unknown` never degrades.
- The Phase-1 sync needed no manual conflict escalation (allowlist auto-resolves count as clean).
- The branch diff is small: **≤1,000 product lines AND ≤20 product files**. Measure, never hand-count: start with `~/.agents/bin/diff-scope $BASE_SHA..$HEAD_SHA --format text --artifact-path <spec_path> --artifact-path <plan_path>`, then append one argument for each plan member and any other process artifact this run wrote. Each exclusion is an individual `--artifact-path <path>` argument. Its first line reads `product: <lines> lines, <files> files`, after the helper drops lockfiles, generated-header files, and those exact artifacts. The gate measures PRODUCT changes, not process artifacts; never exclude the resolved artifact directories themselves, which hold every artifact this repo has ever accepted, and a historical artifact that is itself the requested product still counts. No measurement, invalid plan discovery, or non-zero exit is not a small diff: run the full two-axis review.
- The issue does NOT carry the `risky` label (`<tracker-cli> issue view <num> --json labels`; with an unsupported tracker capability the condition passes), and the retained `capabilities.review.code` state permits the documented review route.

**Merge-delta check (degraded path).** Scope and checklist per REVIEW.md; over exactly the non-empty merge delta, dispatch:

<!-- agent-dispatch: id=ship-issue-merge-delta-review role=reviewer model=opus effort=high -->
Agent(subagent_type="reviewer", model="opus", effort="high") reviews exactly the non-empty merge delta.

An empty delta is recorded in the PR body ("merge-delta empty, nothing to review") and skips to Phase 6.

**Full two-axis review.** Templates and fallback rubrics per REVIEW.md, over the post-sync range `$BASE_SHA..$HEAD_SHA`. Launch the native conformance axis with:

<!-- agent-dispatch: id=ship-issue-full-conformance-review role=reviewer model=opus effort=high -->
Agent(subagent_type="reviewer", model="opus", effort="high") performs the full conformance review.

Run it in parallel with the correctness axis via `codex-collaboration`'s `diff-review`; when that capability is unavailable, use this native first-pass dispatch instead:

<!-- agent-dispatch: id=ship-issue-full-correctness-fallback role=reviewer model=opus effort=high -->
Agent(subagent_type="reviewer", model="opus", effort="high") performs the full correctness fallback review.

Axis reports are never merged, and when the correctness axis came through `diff-review`, its scope is recorded in the PR body per REVIEW.md. Apply findings through REVIEW.md's severity mapping and five-step apply/push flow. After the fix lands, re-review only a named finding and the bounded fix diff — never as a first-pass, merge-delta, or whole-branch review:

<!-- agent-dispatch: id=ship-issue-scoped-fix-rereview role=reviewer-lite model=sonnet effort=medium -->
Agent(subagent_type="reviewer-lite", model="sonnet", effort="medium") re-reviews named prior findings against the bounded fix diff.

If the fix changes unrelated behavior or the finding cannot be checked in that bounded diff, stop the cheap re-review and return to the appropriate full Opus/high axis above.

## Phase 6 — Wait for CI

**Docs-only changes never wait for CI.** `git diff --name-only <base>..HEAD` — every path ends in `.md` → skip straight to Phase 7 (a markdown-only diff cannot break a build); anything else → the phase runs normally.

Before blocking, verify the tip: `gh pr view <pr-num> --json headRefOid` must
equal the reviewed `HEAD_SHA` — the value fixed in Phase 5 and re-fixed by
REVIEW.md's step 5 after each applied fix lands — never `git rev-parse HEAD`
read afresh. Two attempts of one issue share this checkout, so live local HEAD
is not evidence about what was reviewed.

Diverged → the PR head carries **unreviewed commits** on the branch. Never
resolve it by re-pushing, resetting, re-reviewing or merging. In `--auto` this
is the genuinely-blocked stop: stop before the CI wait and before the merge,
make no further forge write, run no cleanup, keep the worktree and the branch,
and return a truthful `stopped` ship summary naming both SHAs — the reviewed
`HEAD_SHA` and the observed `headRefOid`. In interactive mode, surface and wait
at the same point. Divergence here is also evidence of a superseded launch,
which is why `## Launch guard` runs before the merge regardless of how this
check came out.

Then block with `gh`'s built-in watch — one Bash call, **300s timeout**:

```
timeout 300 gh pr checks <pr-num> --watch --fail-fast --interval 30
```

**Foreground only — never backgrounded, and the blocking watch is the only sanctioned wait shape: no bare re-polls, no no-op keep-alive commands.** Exit `0` → Phase 7. Exit `124` → one short narration turn, re-run the identical command, up to 8 times (~40 min), then escalate. Other non-zero → a check failed; pull `gh run view <run-id> --log-failed`, ground, surface. Rationale, escalation script, and JSON-field notes: [`CI-MERGE.md`](./CI-MERGE.md).

## Phase 7 — Merge

(When the tracker capability is unsupported, merge the branch into the integration branch locally per the user's instruction instead.)

When `## Standing authorization` finds no existing grant for the merge and
cleanup chain, enter Gate 2 of [`HUMAN-GATE.md`](./HUMAN-GATE.md) before
anything below. The gate comes first because it waits for the operator's own
message; `check-launch` is then re-validated after the grant arrives,
immediately before the merge. Never use the gate to retry an actual denial.

Run `check-launch` (see `## Launch guard`) immediately before the merge, and
run it regardless of how Phase 6's tip check came out. On anything but
`current: true`, refuse the merge and take the no-write stop. Under lifecycle
identity the merge is the `merge_pr` cycle of `## Delivery loop`: its scope was
checkpointed at the pre-merge selection gate, the fence is that cycle's
`current-launch` call, and `current-launch` runs again after the merge.

Use retained `bindings.tracker.repo_slug` and `bindings.vcs` values to build the subject. Emit the subject form only when the rendered result is nonempty and representable by D18's quoted-subject grammar: it contains none of double quote, dollar, backtick, backslash, NUL, LF, or CR; otherwise omit `--subject` and its value and let the forge choose its normal subject. Never pass `--no-ff` (rejected by recent `gh`; `--merge` already produces a true merge commit).

```
gh pr merge <pr-num> --repo <resolved-repository> --merge --subject "<rendered subject>" --delete-branch
```

**Judge success by the verify below, never by the exit code** — in a worktree checkout the merge can land on the remote while local post-merge steps fail (details: CI-MERGE.md).

Verify: `gh pr view <pr-num> --json state,mergeCommit` → `MERGED` plus a non-null `mergeCommit.oid` means it landed.

After verifying the merge, ask the REMOTE whether the branch still exists — `git ls-remote --heads origin <branch>` (the actual configured branch name); PR metadata like `headRefName` is retained after deletion and proves nothing. Non-empty output → `git push origin --delete <branch>`. Under lifecycle
identity, when the contract has a `delete_remote_branch` stage, empty output is
that stage's `remote_branch_absent` observation (observation-only, made true by
`--delete-branch`), and a non-empty one makes the delete that stage's loop cycle.

## Phase 8 — Cleanup

Before cleanup, take every non-empty Minor/Discussion finding retained per
REVIEW.md and invoke review-package (`~/.agents/bin/review-package`) in
`delivery-detail` mode. Independently run
`artifact-budget check --kind review-package` on the returned durable root and
compare metrics. Record the checked `detail_state` and single `report_path`, but
do not construct or validate a successful `merged` ship summary yet. With non-empty findings,
publication failure may return `unpublished` only after the no-follow retained
source passes `validate-detail-input`; keep the worktree and do not remove it.
Otherwise fail closed. Only `none` or a checker-valid `present` detail can proceed
to remove the worktree.

The steps below are the ledger-free order. Under lifecycle identity the same
effects run as `## Delivery loop` cycles in the contract's stage order — issue
close (`close_tracker`, observation-only when the merge already closed it),
`git worktree remove` (`remove_worktree`), then `git branch -d`
(`delete_local_branch`) — each fenced by `current-launch`, and the summary is
the loop's `ship-summary/v2`.

1. `gh issue view <num> --json state`; if `OPEN`, `gh issue close <num>` (the real close mechanism when retained integration and default branches differ — see Phase 4).

2. Remove the worktree from the main repo root, never from inside the worktree:
   ```
   MAIN_ROOT=$(git -C "$(git rev-parse --git-common-dir)/.." rev-parse --show-toplevel)
   BUCKET="$MAIN_ROOT/.superpowers/sdd/wt-$(basename "$(git -C <worktree-path> rev-parse --path-format=absolute --git-dir)")"
   cd "$MAIN_ROOT"
   git worktree remove <worktree-path>
   git worktree prune
   git branch -d <branch>
   ```

   After the worktree is gone, remove the `$BUCKET` directory recorded above —
   the shape `<primary-checkout>/.superpowers/sdd/wt-<worktree-name>/`,
   captured from the worktree's own git directory before removal rather than
   guessed from its path, because a stale registration under the same
   basename makes `git worktree add` register `<name>1` instead of `<name>`,
   and guessing would delete another worktree's bucket. Nothing else prunes
   it: the bucket lives in the primary checkout and outlives the worktree
   that named it, so a later worktree recreated under the same name would
   resolve to this attempt's ledger and read its `Task <N>: complete` lines
   as its own. Remove only that one worktree's bucket — never `primary/`,
   and never another worktree's.

3. If `git worktree remove` refuses on the rebased-branch case: confirm the PR landed via `gh pr view`, then retry with `ExitWorktree action: "remove", discard_changes: true` — the "discarded N commits" wording is misleading; the content is on the integration branch.

4. Only after issue closure and worktree cleanup both succeed, construct the
   successful `merged` ship summary with the observed full `merge_sha`,
   `issue_closed: true`, `discussion_items: []`, and the checked detail fields.
   Validate it through `artifact-budget validate-report --boundary ship-summary`
   and report only canonical stdout. Never predeclare closure or cleanup in a
   candidate. If an earlier phase fails before merge, validate and return the
   truthful `stopped` or `failed` row. If a post-merge cleanup action fails, keep
   ownership and recover or retry that action; do not forge either a pre-merge
   failure row or a successful summary for actions that have not happened.

The final validated ship-summary contains only `issue`, `state`, `pr_url`, full
`merge_sha`, `issue_closed`, `discussion_items: []`, `detail_state`,
`report_path`, and notes. `report_path` is relative, and which root it is
relative to follows `detail_state`: a `present` path resolves against the
primary checkout, an `unpublished` one against the feature worktree. Notes say
which, because the path alone does not. That 9-key row has two roles: it is the
ledger-free return, and under lifecycle identity it is the
`historical_owner_result` of the `ship-summary/v2` that `## Delivery loop`
returns. Under implementation custody a ship owner writes only
`checkpoint-delivery`, never `finish`; a remainder owner writes its own
`finish --summary-file -`.

## Notes

- Merge commits, learning-doc updates, and blocker fixes fall under standing local-commit authorization. Don't re-confirm each. The `Co-Authored-By` trailer follows retained `bindings.vcs.commit.co_authored_by`.
- If a phase reveals an earlier one was wrong (review surfaces a misaligned spec, say), back up to the appropriate `from-issue` phase. Don't paper over.
- Absent sibling skills (`from-issue`, `sdd`, `worktrees`) degrade to no-ops; this skill still runs.

## Delivery loop

Under lifecycle identity — a validated `ship-handoff/v2`, or the
`delivery_remainder` object of remainder mode below — every delivery effect from
the pre-merge selection gate on runs through this loop. Ledger-free, Phases 7–8
run as written and no ledger call is made.

Every lifecycle call is one command that reads its input from stdin through a
quoted heredoc, with the helper named bare or as `~/.agents/bin/workflow-state`,
optionally piped into or out of `artifact-budget validate-report --input -`. A
checkpoint is one such command:

```text
artifact-budget validate-report --boundary ship-checkpoint --input - <<'EOF' | workflow-state checkpoint-delivery --repo-root <ledger_repo_root> --run-id <run-id> --now <utc> --checkpoint-file - | artifact-budget validate-report --boundary workflow-response --input -
<ship-checkpoint/v2 JSON>
EOF
```

A `ship-checkpoint/v2` has exactly `interface_version` (2), `issue`, `custody`,
`contract_digest`, `delivery_observations`, `authority_observations`,
`reevaluation_evidence` (each sorted by `id`), `requested_scope`,
`detail_state`, `report_path` and `notes`. Every scope, selection, observation
and authority observation comes from `workflow-state build-delivery --repo-root
<ledger_repo_root> --kind <kind> --input -`, fed the installed contract and the
kind's facts in a quoted heredoc: the builder seals every id and digest, so
never compose one. Validate each reply before decoding and treat its
`pending_stage_ids`, `requirements` and `state` as current truth.

1. **Synchronize.** The first ledger act is a null-scope checkpoint with empty
   arrays; the ledger, not the handoff, says which stages are pending.
2. **Pre-selection publication stays as it is.** The Phase-1 sync, the Phase-4
   push and PR, REVIEW.md's fix pushes and the Phase-6 CI wait precede
   selection, so no stage is ready for them: they run under the native guard,
   repository policy and the `check-launch` fence of `## Launch guard`, with no
   checkpoint.
3. **The pre-merge selection gate.** Selection is immutable, so it waits for the
   final CI-green head: once Phase 6 (with its tip check) has passed, build the
   selection with `--kind selected-output` over the reviewed `HEAD_SHA`, its
   tree (`git rev-parse <HEAD_SHA>^{tree}`), and the fixed refs — the spec root for `acceptance_ref`, the durable
   review report path (else the literal review state) for `review_ref`, and
   `checks` for `test_ref` — so a relaunched owner re-derives the identical
   selection. Build the now-true `selected_output`, `branch_published` and
   `pr_opened` observations with `--kind observation` (the selection; the head;
   the PR number, URL and head), and checkpoint them through
   `checkpoint-delivery` with the `--kind scope` for `merge_pr`, the ready stage
   once they fold. Selection has no cycle of its own: its effect is that
   checkpoint write.
4. **Each post-selection effect is one cycle.** Checkpoint the stage's
   `--kind scope` as `requested_scope` (for the merge, the selection checkpoint
   already did); require the validated echo to equal the scope you sent, and
   bind the actual invocation to it; run
   `~/.agents/bin/workflow-state current-launch --repo-root <ledger_repo_root> --run-id <run-id> --action-id <custody action_id>`
   and proceed only on `current: true`; run the effect; run `current-launch`
   again; then the next checkpoint carries the effect's observation, one
   `--kind authority-observation` for that scope and this launch (`launch_id`
   the custody `action_id`), and the next stage's scope. The cycles are the
   merge (`merge_pr` → `pr_merged`), the issue close (`close_tracker` →
   `tracker_closed`), the remote delete (`delete_remote_branch` →
   `remote_branch_absent`), `git worktree remove` (`remove_worktree` →
   `worktree_absent`) and `git branch -d` (`delete_local_branch` →
   `local_branch_absent`), in the contract's stage order.
5. **Already-true stages are observation-only.** A stage the previous effect
   already made true is recorded by its observation alone, without a proposal:
   remote deletion by the merge's `--delete-branch`, and closure by a merge
   that closes the issue. Fold it into the next checkpoint.
6. **Denials.** A guard, host or provider denial of an effect is checkpointed
   with the denied stage's scope as `requested_scope` — the reducer weighs a
   rejection only against a proposed scope — carrying the
   `authority-observation` with verdict `rejected` for that scope, plus the
   observation of any partial effect. It becomes the reducer's `human_gate`
   suspension: require the validated reply's `state: suspended` and
   `blocked_on: human_gate`, and fail loudly on anything else. Then print the
   canonical re-entry line `/from-issue <num> --auto` on its own line as your
   whole return and stop. The checkpoint already suspended the custody, so no
   summary or `finish` follows it. Never route around it. A checkpoint reply of
   kind `delivery_stalled` means the reducer already ended the custody: stop
   the loop, write nothing more, and return that validated reply as your whole
   result.
7. **Completion.** Do not checkpoint the last cycle: once delivery is complete
   `check-launch` reports the attempt inactive, which would make the parent's
   fence refuse. Build the last stage's absence, `implementation_delivered`
   (the selection, merge SHA, integrated ref and the `pr_merged` observation
   id) and `cleanup_complete` (the three absence observation ids, the detail
   pointer and its read evidence), and return them with the last cycle's
   authority observation in a `ship-summary/v2` whose `state` is
   `delivery_complete` and whose `historical_owner_result` is the legacy
   `merged` row. A failure returns `terminal_failed` with the legacy
   `stopped`/`failed` row and the partial observations. Only after the last
   cycle, validate it with
   `artifact-budget validate-report --boundary ship-summary --input -` and
   return only canonical stdout.

## Remainder mode

Entered with a validated `delivery_remainder` object (from-issue's
`## Remainder owner prompt`) instead of a handoff: validate it at the
`workflow-response` boundary before decoding. Its `custody` (a remainder, whose
`action_id` is `<issue>:r<n>:<launch>`), `contract`, `contract_digest`,
`worktree` and `pending_stage_ids` are the whole identity; there is no spec,
plan or reviewed head to review, so skip Phases 0–5. Run `## Delivery loop`
from the ledger's ready stage, starting with its synchronizing null-scope
checkpoint. When selection is pending, build it from the PR head
(`gh pr view <pr-num> --json headRefOid`) and that head's tree with literal
refs — `acceptance_ref` the issue URL
(`https://github.com/<resolved-repository>/issues/<num>`), `review_ref` `unknown`,
`test_ref` `checks` — so a relaunched remainder owner re-derives the identical
selection; then build its observations. When the merge is pending, start at the merge gate: Phase 6's CI
wait and Phase 7's gate and fence still bind. Otherwise start at the first
pending cleanup cycle. `## Launch guard` fences with this custody's
`action_id`.

A denial or a `delivery_stalled` reply ends a remainder owner's loop exactly as
step 6 of `## Delivery loop` says: its whole return is the re-entry line or that
reply, and it writes no `finish`. Otherwise a remainder owner holds its custody,
so it writes its own `finish --summary-file -`. After the last cycle, validate the `ship-summary/v2` (its `historical_owner_result` is
the legacy row) and write it in one command, then return exactly the validated
reply and nothing else:

```text
workflow-state finish --repo-root <ledger_repo_root> --run-id <run-id> --now <utc> --summary-file - <<'EOF' | artifact-budget validate-report --boundary workflow-response --input -
<canonical ship-summary/v2>
EOF
```
