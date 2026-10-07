---
name: ship-issue
description: 'Delivers a finished feature-branch worktree: integration-branch sync, PR, review, CI, merge, issue close or hold, cleanup. Phase 7 of from-issue. Use for "ship #X", "land it".'
---

# Ship Issue

Merges a committed worktree branch into the integration branch, closes or holds the issue, cleans up.

## Project bindings (resolve first)

Run `resolve-project resolve --repo-root <checkout>`. Resolve once at phase entry, retain the returned `ResolvedProject` in memory, and treat every resolver error as fatal before mutation or external effects. On refusal, preserve and report the resolver's `error.code`, `repair_id`, and ordered `violations` exactly; never translate it into a partial snapshot or fallback. The only sanctioned exception is `workflow-state build-delivery`, which performs its own sealed, read-only resolution when it builds a delivery object; this skill still never resolves again itself. Use `bindings.tracker`, `bindings.vcs`, `bindings.commands`, `bindings.workflow.review.code`, and `bindings.workflow.verification`; dereference verification IDs through `bindings.commands`.

For code review, select `bindings.workflow.review.code` and route retained `capabilities.review.code` first: `blocked` stops, authored `unsupported` takes only its documented route, and only `available` dereferences `bindings.commands[review_id].argv` before execution. A blocked required capability stops. An authored unsupported tracker takes the tracker-free route; sync, verify, consolidate and merge still apply.

**Invocation paths.** Pass a `from-issue` handoff's received bytes through `artifact-budget validate-report --boundary ship-handoff --input -` before decoding any field. On entry, and again after any later writer changes either artifact, independently run `artifact-budget check` on the design-spec and implementation-plan roots, compare all four metrics, and recheck a non-null SDD detail root as a review-package; exit 2/3, stale metrics, a mismatch or over-budget input stops (on entry, before Phase 0). Standalone (`/ship-issue <num>`), `review_state` is `unknown`, and so `acceptance_state` is `not_applicable`, unless the user supplies validated evidence of a completed sdd two-axis review; derive the issue number and artifacts, then establish the same checker-valid root/metric objects. The worktree state, not the handoff, is ground truth. Only after the plan's successful check, discover its members locally from its validated index for `review-range` exclusion; keep that list private to ship-issue, never in the handoff, report or review prompt.

## Files beside this one

- `SYNC.md` — Phase 1: divergence, foreign commits, scope creep, the allowlist, escalation.
- `CONSOLIDATE.md` — Phase 3: the bar, the rubric, destinations and the procedure.
- `REVIEW.md` — Phase 5: Codex failures, templates, delta brief, range record, severity, fix, detail.
- `CI-MERGE.md` — Phases 6–7: 40-minute escalation, failing checks, advisory overflow, merge exit.
- `POST-SELECTION-SYNC.md` — a stale or conflicting PR after selection; read with SYNC.md, REVIEW.md.
- `HUMAN-GATE.md` — the operator gates, entered only if `## Standing authorization` finds no grant.
- `DELIVERY-LOOP.md` — lifecycle identity: read it for every `ship-handoff/v2` and every remainder.
- `REMAINDER.md` — a `delivery_remainder` owner's entry, start points, close or hold, `finish`.

## The flow

```
0. Pre-flight              → dispatch probe, worktree clean, branch pattern ok, no PR yet
1. Sync integration branch → fetch + merge origin/<integration>, hybrid conflict policy
2. Verify locally          → verified-tree check; run + record unless verified
3. Consolidate learnings   → see CONSOLIDATE.md; drop most candidates
4. Open PR                 → push -u; gh pr create with "Closes #<num>" unless held
5. Review the PR           → review-range picks delta, empty or full; two-axis review over it
6. Wait for CI             → gh pr checks --required --watch (one blocking call; all checks when none is required)
   Selection gate          → lifecycle identity only: select the CI-green head (## Delivery loop)
7. Merge                   → gh pr merge <pr-num> --repo <resolved-repository> --merge [--subject "<rendered subject>"] --delete-branch (true merge commit)
8. Cleanup                 → issue closed or held; worktree + branches removed
                             (lifecycle identity: each 7–8 effect is one ## Delivery loop cycle)
```

## Standing authorization

Standing authorization exists where repository policy or an explicit user grant covers the concrete action, target and external effect. It carries across phase and session boundaries, need not be re-sent as the same literal command, and survives a harmless quoting or spelling change or a transient command failure. In a qualifying repository the lifecycle guard covers pushing a non-default branch, opening a PR to the default branch, the guarded merge, branch deletion and worktree removal: run that chain without a phase-boundary re-prompt. The launch guard, required CI, the reviewed-tip check, protected-branch rules and the host's actual automatic approval decision still bind. On a host whose permission layer adjudicates intent by review, use an existing user grant covering the same chain; without one, take `HUMAN-GATE.md`'s consolidated operator gate. An actual denial stops the denied action; never route around it.

## Launch guard

Before **every write to the forge or to `origin` this skill makes up to and including the merge**, an unsupported-tracker run's bare branch push included, re-validate that the handoff's launch identity is still the launch the ledger entitles:

```
~/.agents/bin/workflow-state check-launch --repo-root <ledger_repo_root> --run-id <run-id> --action-id <issue:attempt:launch>
```

`<issue:attempt:launch>` is the `action_id` the handoff carried, passed through verbatim — never recomputed, never derived from `attempt`. Proceed only on `current: true`. Anything else — `current: false`, a non-zero exit, a missing helper, or output that does not parse into the exact four keys `action_id`, `current`, `current_action_id` and `reason` — refuses the write; this check never degrades gracefully. Skip it silently only without lifecycle identity (a standalone `/ship-issue <num>`, or an all-null lifecycle group).

Guarded: the Phase-4 push and PR create, every push in REVIEW.md's five-step flow, and the Phase-7 merge. There is no post-merge exemption: under lifecycle identity each post-merge effect is a `## Delivery loop` cycle fenced by `current-launch` before and after. Local commits are fenced separately (### Local commits).

**A refusal is a stop that writes nothing anywhere**: no further forge write, **no ledger write**, no cleanup; leave the worktree, the branch and any PR as they are. Print the re-entry line `/from-issue <num> --auto` on its own line, then return a truthful `stopped` ship summary (under lifecycle identity, a `terminal_failed` `ship-summary/v2`'s `historical_owner_result`): notes name the refusal, its `reason`, this `action_id` and the reported `current_action_id`; `merge_sha: null`, `issue_closed: false`, `discussion_items: []`, `pr_url` the opened PR or null, `detail_state: "none"` and `report_path: null`, or the failure-only `unpublished` shape when Phase 5 retained readable Minor/Discussion findings (notes name that source and its root; keep the worktree). Phase 8 does not run; no detail is published.

### Local commits

When the prompt carries a `Lifecycle worker:` line, this run is a
registered worker, and it creates every local commit as
`launch-commit --repo-root <ledger_repo_root> --run-id <run-id> --worker-id <worker_id> -- <git commit arguments>`.
That includes Phase 1's sync, run as
`git merge --no-commit --no-ff origin/<integration>` followed by
`launch-commit`, and Phase 3's commits. Exit 3 is a refusal like
`check-launch`'s: stop with the same no-write rule. An agent this run
dispatches that can write is registered with
`--parent <worker_id>` added to `workflow-state register-worker` (this
handoff's `action_id` as `--action-id`), gets its own `Lifecycle worker:`
line followed by the sentences "Run each long command, every verification command included, as
`launch-scope exec --repo-root <ledger_repo_root> --run-id <run-id> --worker-id <worker_id> -- <argv>`,
still in the foreground." and "Create every scratch directory or scratch worktree under the path that
`launch-scope scratch --repo-root <ledger_repo_root> --run-id <run-id> --worker-id <worker_id>` prints.", and is released when it returns. Without the line, commit with plain
`git`.

## Doc-grounded escalations

Before any user-facing question mid-flow, invoke `doc-grounded-questions`, read only the retained declared paths, lead with what the document says, and ask only the open part.

## gh hygiene

Prefix a forge invocation only with the names in `bindings.tracker.credential_env.unset_before_invocation`; for example, an exhaustive list containing `GITHUB_TOKEN` yields `unset GITHUB_TOKEN && gh ...` when a harness token lacks access to the target org. When `bindings.tracker.cli` is `glab`, substitute the equivalent `glab` verbs. Follow `writing-plans`' Payload discipline.

## Phase 0 — Pre-flight

**Reviewer-dispatch probe — first, before any write.** After entry validation and before the checks below (so before `## Delivery loop`'s synchronizing null-scope checkpoint, the Phase-1 sync and every forge, ledger or git write), confirm that this context can launch the subagents this skill's reviewer dispatch sites name: the subagent-launch tool is in your tool surface or, on a host that defers tool schemas, its tool search returns that tool's schema (Claude Code: `ToolSearch` `select:Agent`). Test the capability, never a host by name; launch nothing, write nothing, make no trial dispatch. It runs in every review-bearing invocation, either handoff or standalone, even when the review range may be empty. On failure, stop with nothing launched or written; from a handoff your whole return is exactly this closed line, with no ship summary and no validation:

```text
capability_gap: agent_dispatch
```

Standalone, tell the user the probe found no subagent-launch tool, end with that same line, and stop, keeping the worktree. Then check:

1. `git rev-parse --git-common-dir` ≠ `git rev-parse --git-dir`: a linked worktree, not the main checkout.
2. `git branch --show-current` matches the regex built from retained `bindings.vcs.branch_pattern` and `bindings.vcs.worktree.prefix` (either configured form); extract `<num>`. An argument or handoff `issue_number` wins, but must match the branch.
3. `git status --porcelain` returns nothing.
4. `gh pr list --head <branch> --json number,url` returns `[]`.

Any failure: pause, ground, surface; don't auto-fix the branch name or stash changes.

**Effective acceptance state.** Start from the handoff's `acceptance_state`. The record is `<plan stem>.acceptance.md` beside the plan root, named by its repository-relative path, or `none` when absent. With `human_pending` and `auto: false`, ask the user in one grounded question to attest each `human_pending` row; if every row is attested, rewrite those Verdict cells to `met (attested)`, commit the record (### Local commits) and continue with `met`, else keep `human_pending`. `--auto` never asks and never self-attests. The value is then fixed for the run and ship grades nothing: `met` or `not_applicable` **closes** the issue, `unmet` or `human_pending` **holds** it open as `needs-verification` (Phase 8). A hold whose record is `none` stops with `terminal_failed` before any hold effect.

## Phase 1 — Sync from the integration branch

**Read `SYNC.md` first**, then:

```
git fetch origin
git log origin/<integration>..<integration> --oneline
```

Run `git merge --no-commit --no-ff origin/<integration>`; unless it reports `Already up to date`, commit the merge with the configured merge-commit message (### Local commits). Don't squash.

## Phase 2 — Verify locally

A blocked verification capability stops and reports its `reason_code` and `repair_id`; authored unsupported follows only its documented no-verification route.

1. **Check.** Run `verified-tree check --verification <id>` in the worktree, repeating `--verification` for every id in retained `bindings.workflow.verification`, in order; keep the `tree` it prints.
2. **Skip only on `verified`** (exit 0). On Phase 2's own run, note `verification reused: tree <id>` in the PR body's Summary.
3. **Otherwise run and record.** Run every id's `bindings.commands` argv and cwd; when all pass, run `verified-tree record --tree <the checked tree>` with the same `--verification` ids. `record` exit 3 `tree_changed` is a failing verification; `check` exit 2 means run anyway and leave the pass unrecorded; `record` exit 2 leaves it unrecorded.

On a failing verification command, pause, ground and surface; never invent a fix command outside retained `bindings.commands`. Tell *environmental* test failures (container connectivity, missing network, sandbox limits) from *real* ones with a baseline of the same project in a scratch worktree on `origin/<integration>`: the same failures are pre-existing (continue; note the baseline diff in the PR body), different ones are real (pause, ground, surface).

## Phase 3 — Consolidate learnings

**Read `CONSOLIDATE.md` first**; run its step-1 mining commands as actual tool calls *before* concluding anything. When Phase 3 commits anything, rerun Phase 2's verification step before Phase 4.

## Phase 4 — Open PR

Skip it when the tracker capability is unsupported (push the branch and stop, or merge locally per the user's request). Without a standing grant for these actions, enter `HUMAN-GATE.md`'s Gate 1 before anything below; never use a gate to retry an actual denial. Run `check-launch`; on anything but `current: true`, stop without pushing. Then:

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

## Acceptance
Acceptance state: <effective acceptance state>

Acceptance record: <record-path or none>

<acceptance table>

Closes #<num>"
```

- The lifecycle guard accepts only this form (`<resolved-repository>` is retained `bindings.tracker.repo_slug`); render the body in place, with no `"`, `$`, backtick or backslash, never through a file, heredoc or substitution.
- `## Acceptance` always appears, with Phase 0's effective state and the record's repository-relative path or `none`. With a record, `<acceptance table>` is a Markdown table (`AC`, `Kind`, `Verdict`), one row per record row copying its closed tokens; without one, drop that line. A **hold** drops the `Closes #<num>` line too and carries no closing keyword (close, closes, closed, fix, fixes, fixed, resolve, resolves or resolved before an issue reference).
- Title: the issue title verbatim unless the implementation deviated meaningfully; under 70 chars.
- GitHub auto-closes on merge only for a **default-branch** base; otherwise Phase 8's `gh issue close <num>` is the real close. On the close branch keep the trailer for traceability; don't rely on it.
- **Use full URLs, not bare `#N`**, in PR bodies, comments and commit messages (`https://github.com/<resolved-repository>/issues/<n>`): GitHub resolves `#N` against the source repo. The `Closes #<num>` trailer is the one exception.

## Phase 5 — Review the PR

```
BASE_SHA=$(git merge-base HEAD origin/<integration>)
HEAD_SHA=$(git rev-parse HEAD)
```

Review only what sdd's final two-axis review could not have seen, unless a risk signal calls for the full review. **Read `REVIEW.md` before dispatching or applying anything.**

**Pick the range first.** The *final-review head* is the handoff's `head_sha` when `review_state` is `clean`, not the reviewed `HEAD_SHA` this phase fixes. If the first, second or fourth condition fails, the range is full and `review-range` does not run. Select it with `review-range` when ALL hold:

- `review_state` is `clean` (both axes clean, or every residual parked-with-ruling); `unknown` never degrades.
- The Phase-1 sync needed no manual conflict escalation (allowlist auto-resolves count as clean).
- The delta since the final-review head is small: **≤1,000 product lines AND ≤20 product files**. Measure, never hand-count: `~/.agents/bin/review-range --integration-ref origin/<integration> --head $HEAD_SHA --final-review-head <final-review head> --max-lines 1000 --max-files 20 --artifact-path <spec_path> --artifact-path <plan_path>`, plus one individual `--artifact-path <path>` per plan member and other process artifact this run wrote, never the resolved artifact directories; a historical artifact that is itself the requested product still counts. Its one JSON object's `route` is `delta`, `empty` or `full`, with a closed `reason`. No measurement (exit 1, unparseable stdout, invalid plan discovery) is not a small diff: the range is full, recorded as `review-range unavailable`.
- The issue does NOT carry the `risky` label (`<tracker-cli> issue view <num> --json labels`; with an unsupported tracker capability the condition passes), and the retained `capabilities.review.code` state permits the documented review route.

**Route the review.** `delta` → the two-axis review over `<review_base>..$HEAD_SHA`, with REVIEW.md's delta-route conformance brief. `empty` → nothing to review: record it and skip to Phase 6. `full`, a failed prerequisite, or an unavailable helper → the two-axis review over `$BASE_SHA..$HEAD_SHA`. Record the route in the PR body per REVIEW.md.

**Merge-delta reviewer**, dispatched only by POST-SELECTION-SYNC.md, never by Phase 5:

<!-- agent-dispatch: id=ship-issue-merge-delta-review role=reviewer model=opus effort=high -->
Agent(subagent_type="reviewer", model="opus", effort="high") reviews exactly the non-empty merge delta.

**Full two-axis review** over the selected range, templates and rubrics per REVIEW.md. Conformance:

<!-- agent-dispatch: id=ship-issue-full-conformance-review role=reviewer model=opus effort=high -->
Agent(subagent_type="reviewer", model="opus", effort="high") performs the full conformance review.

In parallel, the correctness axis, routed by the retained `capabilities.review.code` state before either axis is dispatched, never by how a Codex call failed:

1. `blocked` stops with its capability reason and repair ID; neither axis is dispatched.
2. `available` with `codex-collaboration` installed → its `diff-review`, the only rung reaching Codex.
3. `unsupported`, or `available` without `codex-collaboration` → this native first-pass dispatch:

<!-- agent-dispatch: id=ship-issue-full-correctness-fallback role=reviewer model=opus effort=high -->
Agent(subagent_type="reviewer", model="opus", effort="high") performs the full correctness fallback review.

A Codex call made under `unsupported` anyway is a routing error: discard its outcome (verdict, refusal or failure), record the routing error in the PR body beside the correctness verdict, and run the rung-3 dispatch, with no retry, stop or suspension.

Apply findings through REVIEW.md's severity mapping and five-step flow. After the fix lands, re-review only a named finding and the bounded fix diff, never first-pass, merge-delta or whole-branch:

<!-- agent-dispatch: id=ship-issue-scoped-fix-rereview role=reviewer-lite model=sonnet effort=medium -->
Agent(subagent_type="reviewer-lite", model="sonnet", effort="medium") re-reviews named prior findings against the bounded fix diff.

If the fix changes unrelated behavior or the finding cannot be checked in that bounded diff, stop the cheap re-review and return to the appropriate full Opus/high axis.

**Interim child results.** A child's return that the host marks interim (its own background work still running, or a result that may be interim) is not a completion. Re-engage that same child by its recorded agent identity: tell it to wait for its job inside its turn and then return its final report, and wait for that report. You may end your turn while it is live; the host wakes you with its next notification. Never answer an interim result with a text-only reply, never suspend for it (it is not an `external` wait), and never dispatch a replacement or stop the child. A registered lifecycle worker stays registered under its existing worker id and registers nothing new: an interim result is not its `returned` event. If the message cannot be delivered, follow from-issue's **Writing workers** route (task-stop, then release `--event stopped`), then this skill's handling of a lost child, the one case that may lead to a fresh dispatch. Only the child's final hand-back counts as its result.

## Phase 6 — Wait for CI

**Docs-only changes never wait for CI.** `git diff --name-only <base>..HEAD` — every path ends in `.md` → skip straight to Phase 7 (a markdown-only diff cannot break a build); anything else → the phase runs normally.

Before blocking, `gh pr view <pr-num> --json headRefOid` must equal the reviewed `HEAD_SHA` (fixed in Phase 5, re-fixed by REVIEW.md's step 5 after each applied fix), never `git rev-parse HEAD` read afresh: two attempts of one issue share this checkout, so live local HEAD is not evidence. Diverged → the PR head carries **unreviewed commits**: never resolve it by re-pushing, resetting, re-reviewing or merging, except for a head POST-SELECTION-SYNC.md admits. In `--auto` this is the genuinely-blocked stop: before the CI wait and the merge, make no further forge write, run no cleanup, keep the worktree and the branch, and return a truthful `stopped` ship summary naming the reviewed `HEAD_SHA` and the observed `headRefOid`. Interactive, surface and wait at the same point.

Then block on the required checks — one foreground Bash call, **300s timeout**, the only sanctioned wait shape (no re-polls, no keep-alive commands):

```
timeout 300 gh pr checks <pr-num> --required --watch --fail-fast --interval 30
```

Exit `0` → list advisory states, then Phase 7. `124` → one short narration turn, re-run the identical command, up to 8 times (~40 min), then escalate. `1` with gh's `no required checks reported` error → run `timeout 300 gh pr checks <pr-num> --watch --fail-fast --interval 30` for the rest of the phase under the same exit codes and retry budget, list no advisory states, and note `CI: no required checks reported; waited on all`. Other non-zero → a gating check failed. After the required watch exits `0`, run `gh pr checks <pr-num> --json name,bucket` once and append each non-`pass` row to the ship summary's notes as `advisory CI: <name>=<bucket>, …`; an advisory failure does not block the merge. Escalation, failing checks and advisory overflow: `CI-MERGE.md`.

## Phase 7 — Merge

With an unsupported tracker capability, merge into the integration branch locally per the user. Without a standing grant for the merge and cleanup chain, enter `HUMAN-GATE.md`'s Gate 2 before anything below; never use a gate to retry an actual denial. Then, immediately before the merge and whatever Phase 6's tip check showed, run `check-launch`; on anything but `current: true`, refuse the merge and take the no-write stop. Under lifecycle identity this effect is a `## Delivery loop` cycle.

Build the subject from retained `bindings.tracker.repo_slug` and `bindings.vcs` values. Pass `--subject` only when the rendered subject is non-empty and contains none of `"`, `$`, backtick, backslash, NUL, LF or CR; otherwise omit it. Never pass `--no-ff`.

```
gh pr merge <pr-num> --repo <resolved-repository> --merge --subject "<rendered subject>" --delete-branch
```

**Judge success by the verify, never by the exit code** (CI-MERGE.md): `gh pr view <pr-num> --json state,mergeCommit` → `MERGED` plus a non-null `mergeCommit.oid`. Then ask the REMOTE whether the branch still exists, `git ls-remote --heads origin <branch>`; PR metadata like `headRefName` proves nothing. Non-empty output → `git push origin --delete <branch>`.

## Phase 8 — Cleanup

Before cleanup, invoke review-package (`~/.agents/bin/review-package`) in `delivery-detail` mode over every non-empty Minor/Discussion finding retained per REVIEW.md, independently run `artifact-budget check --kind review-package` on the returned durable root and compare metrics, and record the checked `detail_state` and single `report_path`, constructing no `merged` summary yet. A publication failure may return `unpublished` only as REVIEW.md's durable detail allows, keeping the worktree; otherwise fail closed. Only `none` or a checker-valid `present` detail proceeds to remove the worktree. Under lifecycle identity this effect is a `## Delivery loop` cycle.

1. Close or hold, per Phase 0's effective acceptance state.
   - **Close** (`met` or `not_applicable`): `gh issue view <num> --json state`; if `OPEN`, `gh issue close <num>` (see Phase 4).
   - **Hold** (`unmet` or `human_pending`), in this order: `gh issue view <num> --json state,comments`; if `CLOSED`, `gh issue reopen <num>`. When `gh label list --repo <resolved-repository> --search needs-verification --json name` shows no name exactly `needs-verification`, run `gh label create needs-verification --repo <resolved-repository> --description "Merged, acceptance criteria await verification"`, never with `--force`. Then `gh issue edit <num> --add-label needs-verification`. The hold comment's first line is `Held for verification: <PR URL>`; the rest gives the effective acceptance state, the PR body's three-column table and the record's link at the merge SHA (`https://github.com/<resolved-repository>/blob/<merge-sha>/<record-path>`). When the earlier view already shows comments with that first line, reuse the earliest one's URL; otherwise post it with `gh issue comment <num> --body "<hold comment>"`, whose stdout is the comment URL. Finally `gh issue view <num> --json state,labels` must show `OPEN` with `needs-verification`; anything else keeps ownership and retries, as for any failed post-merge action.
2. Remove the worktree from the main repo root, never from inside the worktree:
   ```
   MAIN_ROOT=$(git -C "$(git rev-parse --git-common-dir)/.." rev-parse --show-toplevel)
   BUCKET="$MAIN_ROOT/.superpowers/sdd/wt-$(basename "$(git -C <worktree-path> rev-parse --path-format=absolute --git-dir)")"
   cd "$MAIN_ROOT"
   git worktree remove <worktree-path>
   git worktree prune
   git branch -d <branch>
   ```
   After the worktree is gone, remove only `$BUCKET` — the shape `<primary-checkout>/.superpowers/sdd/wt-<worktree-name>/` — captured from the worktree's own git directory before removal, never `primary/` or another worktree's.
3. If `git worktree remove` refuses on the rebased-branch case, confirm the PR landed via `gh pr view`, then retry with `ExitWorktree action: "remove", discard_changes: true`; despite its "discarded N commits" wording, the content is on the integration branch.
4. Only after issue closure (on a hold, the confirmed hold) and worktree cleanup both succeed, construct the successful `merged` ship summary: the observed full `merge_sha`, `issue_closed: true` on close or `issue_closed: false` on hold (notes name the hold and the comment URL), `discussion_items: []` and the checked detail fields. Validate it through `artifact-budget validate-report --boundary ship-summary` and report only canonical stdout. Never predeclare closure or cleanup in a candidate. A failure before merge validates and returns the truthful `stopped` or `failed` row. A failed post-merge cleanup action keeps ownership and is recovered or retried; never forge a pre-merge failure row or a successful summary for actions that have not happened.

The final ship-summary contains only `issue`, `state`, `pr_url`, full `merge_sha`, `issue_closed`, `discussion_items: []`, `detail_state`, `report_path` and notes. `report_path` is relative: a `present` path to the primary checkout, an `unpublished` one to the feature worktree, and notes say which. Under implementation custody a ship owner writes only `checkpoint-delivery`, never `finish`; a remainder owner writes its own `finish --summary-file -`.

## Notes

- Merge commits, learning-doc updates and blocker fixes fall under standing local-commit authorization; don't re-confirm each. Trailers follow retained `bindings.vcs.commit.co_authored_by`.
- If a phase reveals an earlier one was wrong, back up to that `from-issue` phase; don't paper over.
- Absent sibling skills (`from-issue`, `sdd`, `worktrees`) degrade to no-ops.

## Delivery loop

Under lifecycle identity (a validated `ship-handoff/v2`, or `## Remainder mode`'s `delivery_remainder`), every delivery effect from the pre-merge selection gate on runs through this loop, per `DELIVERY-LOOP.md`; ledger-free, Phases 7–8 run as written with no ledger call. The builder is `workflow-state build-delivery --repo-root <ledger_repo_root> --kind <kind> --input -`.

## Remainder mode

Entered with a validated `delivery_remainder` object instead of a handoff. It skips Phases 0–5 and runs `## Delivery loop` from the ledger's ready stage, as `REMAINDER.md` says.
