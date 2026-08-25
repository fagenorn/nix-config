---
name: ship-issue
description: Deliver a finished feature-branch worktree — sync integration branch, PR, review, CI, merge, close issue, clean up. Phase 7 of from-issue. Use for "ship #X", "land it".
argument-hint: "[issue number — optional; inferred from branch name]"
---

# Ship Issue

Counterpart to `to-issues` and `from-issue`. Take a worktree branch with the implementation committed and deliver it: merged on the integration branch, issue closed, workspace gone.

## Project bindings (resolve first)

Run `~/.agents/bin/resolve-bindings` from the worktree — it prints the standard binding set (`specDir`, `planDir`, branches, tracker kind/CLI, branch naming, commit flags) from `.claude/skills.config.json` plus auto-detection and the shared defaults. Helper missing → read the config and apply the defaults it documents. Verify commands: config, else the manifest (`package.json` scripts, `*.slnx`/`*.sln` → `dotnet test`, `Cargo.toml` → `cargo test`, `go.mod` → `go test`, `Makefile` → `make test`).

Degrade gracefully: never read a configured doc/hints path that doesn't exist, never hard-fail on a missing optional binding. `issueTracker.kind=none` skips every issue/PR/CI step; the sync/verify/consolidate/merge machinery still applies.

Optional `review.criticalPaths` globs: diffs intersecting any always get Phase 5's full two-axis review; absent = the `risky` label is the only always-full trigger.

**Invocation paths.** From `from-issue`, treat the handoff as received stdin
bytes: pass them through `artifact-budget validate-report --boundary
ship-handoff --input -` before decoding any field. It carries the fixed lifecycle
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
1. Sync integration branch → fetch + merge origin/<integrationBranch>, hybrid conflict policy
2. Verify locally          → lint + tests inside the worktree
3. Consolidate learnings   → see CONSOLIDATE.md; drop most candidates
4. Open PR                 → push -u; gh pr create with "Closes #<num>"
5. Review the PR           → merge-delta check or full two-axis review
6. Wait for CI             → gh pr checks --watch (one blocking call)
7. Merge                   → gh pr merge <pr-num> --repo <repoSlug> --merge [--subject "<rendered mergeSubjectTemplate>"] --delete-branch (true merge commit)
8. Cleanup                 → issue closed; worktree + branches removed
```

## Standing authorization

Standing authorization exists exactly where the lifecycle guard grants it: pushing a non-default branch, opening a PR to the default branch, and the guarded merge, in fagenorn-owned repositories; everywhere else these commands stay per-action gated — suspend with blocked_on=human_gate and print the re-entry line instead of dying at the prompt.

In a qualifying repository this skill IS that chain: `git push`, `gh pr create`, `gh pr merge <pr-num> --repo <repoSlug> --merge [--subject "<rendered mergeSubjectTemplate>"] --delete-branch`, branch delete, and worktree remove need no re-prompt; pause only where a phase says to.

## Launch guard

The lifecycle ledger reserves one worktree per issue and hands a retry the
predecessor's worktree and branch on purpose, so a superseded attempt can still
push, open a PR and merge. Before **every write to the forge or to `origin` this
skill makes up to and including the merge**, re-validate that the handoff's
launch identity is still the launch the ledger entitles. The rule binds
regardless of `issueTracker.kind`, so a `kind=none` invocation — which skips
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
five-step apply/push flow, and the Phase-7 merge. Everything **after the merge is
verified** is deliberately unguarded — the remote branch delete, and Phase 8's
issue close, `git branch -d` and `git worktree remove`. A refusal there could
only refuse cleanup for a merge that already landed, stranding a worktree and a
branch; deleting an already-merged branch is idempotent and harmless. Phase 1's
merge from the integration branch and Phase 3's local commits are not forge
writes and are not guarded.

**A refusal is a stop that writes nothing anywhere.** Do not execute the write.
Make no further forge write, **no ledger write**, and run no cleanup: leave the
worktree, the branch and any PR exactly as they are, because the successor is
working in that same worktree on that same branch. Print the canonical re-entry
line `/from-issue <num> --auto` on its own line, then return a truthful
`stopped` ship summary whose notes name the refusal, the reported `reason`, this
`action_id` and the reported `current_action_id`. Its fields are `merge_sha:
null`, `issue_closed: false`, `discussion_items: []`, `pr_url` the PR when one
was already opened and null otherwise, and `detail_state: "none"` with
`report_path: null` — or the failure-only `unpublished` shape when Phase 5
retained readable Minor/Discussion findings, naming that retained source in
notes and keeping the worktree. Phase 8 does not run and no delivery detail is
published: the successor owns that worktree and will produce its own.

Without lifecycle identity — a standalone `/ship-issue <num>`, or a handoff
whose lifecycle group is all-null — skip the guard silently: a ledger-free
invocation has no attempts and no supersession mechanism, and the handoff
validator's all-or-nothing group means it is never partially present. That is
the only skip, and it is a statement about the invocation, not about the
environment.

## Doc-grounded escalations

Before forming *any* user-facing question this skill raises mid-flow, invoke the `doc-grounded-questions` skill (if unavailable, read whichever declared `docPaths` exist). Lead with what the relevant doc says; ask only the genuinely open part.

## gh hygiene

When `unsetGithubToken` is true, prefix every `gh` call with `unset GITHUB_TOKEN &&` — for harnesses whose exported token lacks access to the target org (default false). When `issueTracker.cli` is `glab`, substitute the equivalent `glab` verbs.

Throughout, follow `writing-plans`' Payload discipline: targeted `rg` over whole-file reads, bounded reads, summarized command output, logs on disk, artifacts handed over as paths.

## Phase 0 — Pre-flight

Verify the workspace is shippable before doing anything destructive:

1. `git rev-parse --git-common-dir` ≠ `git rev-parse --git-dir` — a linked worktree, not the main checkout.
2. `git branch --show-current` matches the regex built from `branchNaming.pattern` plus optional `branchNaming.worktreePrefix` — for the defaults, `^(worktree-)?issue-<num>-<slug>$`; both forms are valid. Extract `<num>`. An argument or handoff `issue_number` wins, but verify it matches the branch.
3. `git status --porcelain` returns nothing.
4. `gh pr list --head <branch> --json number,url` returns `[]` — no open PR for this branch.

Any failure: pause, ground, surface. Don't auto-fix the branch name or stash changes.

## Phase 1 — Sync from the integration branch

**Read [`SYNC.md`](./SYNC.md) first** — it owns divergence handling, foreign-commit checks, scope-creep sweeps (retirement/addition), the auto-resolve allowlist, and the conflict escalation format.

```
git fetch origin
git log origin/<integrationBranch>..<integrationBranch> --oneline
```

The load-bearing rules, in brief:

- Merging `origin/<integrationBranch>` into the feature branch is safe even when the local integration branch has diverged (expected under parallel `--auto` runs). **Anything that rewrites the local integration branch — reset, rebase, push — stops and surfaces; `--auto` never auto-resolves history rewrites.**
- Foreign commits on the branch (another issue's work) → surface, never clean up silently.
- Conflicts: the allowlist auto-resolves lockfiles, migrations and generated files, and always keeps `.claude/settings.json` out of the merge. **Everything else escalates one conflict at a time**; skipped conflicts pause the phase.

Otherwise `git merge origin/<integrationBranch>`; commit the merge with the default merge-commit message. Don't squash.

## Phase 2 — Verify locally

```
<verify.lint>
<verify.test>
```

No command from config or manifest detection → **skip that step and note the skip in the PR body**. `docPaths.devenvTooling`, where it exists, is the source of truth if the commands have moved.

Lint failures: try `verify.lintFix`, re-run `verify.lint`. Still failing → pause, ground, surface.

Test failures: separate *environmental* (container connectivity, missing network, sandbox limits) from *real* by baselining the same project in a scratch worktree on `origin/<integrationBranch>`. Same failures → pre-existing; continue and note the baseline diff in the PR body. Different failures → real; pause, ground, surface.

## Phase 3 — Consolidate learnings

**Read [`CONSOLIDATE.md`](./CONSOLIDATE.md) first** — it owns the mining commands, rubric, destination table, and reporting format. Run its step-1 mining commands as actual tool calls *before* concluding anything: empty is a finding, not a default — earn it by mining. Promoted candidates commit as `docs(<scope>): <summary>`, following `commit.coAuthoredBy`.

## Phase 4 — Open PR

Skip entirely when `issueTracker.kind=none` (push the branch and stop, or merge locally per the user's request).

Run `check-launch` (see `## Launch guard`); on anything but `current: true`,
stop without pushing. Then:

```
git push -u origin <branch>
```

Run `check-launch` again, then:

```
gh pr create --base <integrationBranch> --title "<title>" --body "$(cat <<'EOF'
## Summary
<2-4 bullets of what shipped>

## Spec
<spec-path>

## Plan
<plan-path>

Closes #<num>
EOF
)"
```

Title: the issue title verbatim unless the implementation deviated meaningfully. Under 70 chars; details go in the body.

GitHub auto-close on merge fires only when the PR base equals the **default branch**; when `integrationBranch != defaultBranch` the real close mechanism is Phase 8's explicit `gh issue close <num>` — keep the `Closes #<num>` trailer for traceability, don't rely on it.

**Use full URLs, not bare `#N`**, in PR bodies, comments, and commit-message references (`https://github.com/<repoSlug>/issues/<n>`; `repoSlug` from config, else the origin URL) — GitHub resolves bare `#N` against the source repo context, which under cross-references lands on unrelated refs. The `Closes #<num>` trailer is the one exception.

## Phase 5 — Review the PR

```
BASE_SHA=$(git merge-base HEAD origin/<integrationBranch>)
HEAD_SHA=$(git rev-parse HEAD)
```

The branch normally arrives already reviewed on two axes by sdd's final review (conformance ∥ correctness); this phase reviews only what that review could not have seen — unless a risk signal calls for the full ladder. **Read [`REVIEW.md`](./REVIEW.md) before dispatching or applying anything.**

**Pick the path first.** Degrade to the merge-delta check when ALL of these hold; otherwise run the full two-axis review:

- `review_state` is `clean` (handoff / sdd report: both axis verdicts clean, or every residual parked-with-ruling). `unknown` never degrades.
- The Phase-1 sync needed no manual conflict escalation (allowlist auto-resolves count as clean).
- The branch diff is small: **≤1,000 product lines AND ≤20 product files**. Measure, never hand-count: start with `diff-scope $BASE_SHA..$HEAD_SHA --format text --artifact-path <spec_path> --artifact-path <plan_path>`, then append one argument for each discovered plan member and any other process artifact this run wrote. Each exclusion is an individual `--artifact-path <path>` argument (executable `~/.agents/bin/diff-scope`; use the full path if the bare name does not resolve). Its first line reads `product: <lines> lines, <files> files`, after the helper drops lockfiles, generated-header files, and those exact artifacts. The gate measures PRODUCT changes, not process artifacts; never exclude `<specDir>`/`<planDir>` themselves, which hold every artifact this repo has ever accepted, and a historical artifact that is itself the requested product still counts. No measurement — helper missing, invalid plan discovery, or non-zero exit — is not a small diff: run the full two-axis review.
- The issue does NOT carry the `risky` label (`<tracker-cli> issue view <num> --json labels`; with `issueTracker.kind=none` the condition passes), and no path from `git diff --name-only $BASE_SHA..$HEAD_SHA` matches a `review.criticalPaths` glob.

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

**Docs-only changes never wait for CI.** `git diff --name-only <base>..HEAD | sed 's/.*\.//' | sort -u` — every line `md` → skip straight to Phase 7 (a markdown-only diff cannot break a build); anything else → the phase runs normally.

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

(When `issueTracker.kind=none`, merge the branch into the integration branch locally per the user's instruction instead.)

Run `check-launch` (see `## Launch guard`) immediately before the merge, and
run it regardless of how Phase 6's tip check came out. On anything but
`current: true`, refuse the merge and take the no-write stop.

Use the `repoSlug` binding resolved in Phase 0. Build the subject from `mergeSubjectTemplate` (substituting `<feature>`/`<desc>`/`<num>`/`<integrationBranch>`). Emit the subject form only when the rendered result is nonempty and representable by D18's quoted-subject grammar: it contains none of double quote, dollar, backtick, backslash, NUL, LF, or CR; otherwise omit `--subject` and its value and let the forge default stand. Never pass `--no-ff` (rejected by recent `gh`; `--merge` already produces a true merge commit).

```
gh pr merge <pr-num> --repo <repoSlug> --merge --subject "<rendered mergeSubjectTemplate>" --delete-branch
```

**Judge success by the verify below, never by the exit code** — in a worktree checkout the merge can land on the remote while local post-merge steps fail (details: CI-MERGE.md).

Verify: `gh pr view <pr-num> --json state,mergeCommit` → `MERGED` plus a non-null `mergeCommit.oid` means it landed.

After verifying the merge, ask the REMOTE whether the branch still exists — `git ls-remote --heads origin <branch>` (actual branch name, including `branchNaming.worktreePrefix` if present); PR metadata like `headRefName` is retained after deletion and proves nothing. Non-empty output → `git push origin --delete <branch>`.

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

1. `gh issue view <num> --json state`; if `OPEN`, `gh issue close <num>` (the real close mechanism when `integrationBranch != defaultBranch` — see Phase 4).

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

3. If `git worktree remove` refuses on the rebased-branch case (see `docPaths.gitWorktrees`): confirm the PR landed via `gh pr view`, then retry with `ExitWorktree action: "remove", discard_changes: true` — the "discarded N commits" wording is misleading; the content is on the integration branch.

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
`report_path`, and notes. A fresh ship owner never writes workflow-state
itself; the read-only `check-launch` query of `## Launch guard` is the one
ledger call it makes.

## Notes

- Merge commits, learning-doc updates, and blocker fixes fall under standing local-commit authorization. Don't re-confirm each. The `Co-Authored-By` trailer follows `commit.coAuthoredBy`.
- If a phase reveals an earlier one was wrong (review surfaces a misaligned spec, say), back up to the appropriate `from-issue` phase. Don't paper over.
- Absent sibling skills (`from-issue`, `sdd`, `worktrees`) degrade to no-ops; this skill still runs.
