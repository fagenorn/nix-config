---
name: ship-issue
description: Deliver a finished feature-branch worktree — sync integration branch, PR, review, CI, merge, close issue, clean up. Phase 7 of from-issue. Use for "ship #X", "land it".
argument-hint: "[issue number — optional; inferred from branch name]"
---

# Ship Issue

Counterpart to `to-issues` and `from-issue`. Take a worktree branch with the implementation committed and deliver it: merged on the integration branch, issue closed, workspace gone.

## Project bindings (resolve first)

Read `.claude/skills.config.json` at the project root. Auto-detect absent keys: tracker = `gh` for a github.com remote (else `glab`/none); verify commands from the manifest (`package.json` scripts, `*.slnx`/`*.sln` → `dotnet test`, `Cargo.toml` → `cargo test`, `go.mod` → `go test`, `Makefile` → `make test`); branches from the repo default. Remaining defaults: `integrationBranch=main`, `defaultBranch=main`, `commit.coAuthoredBy=true`, `unsetGithubToken=false`, `specDir=.claude/specs`, `planDir=.claude/plans`.

Degrade gracefully: never read a configured doc/hints path that doesn't exist, never hard-fail on a missing optional binding. `issueTracker.kind=none` skips every issue/PR/CI step; the sync/verify/consolidate/merge machinery still applies. `defaultBranch` matters because it controls GitHub auto-close-on-merge (Phase 4).

**Invocation paths.** From `from-issue` (dispatched as an `Agent` subagent), the bootstrapping prompt carries `issue_number`, `branch`, `worktree_path`, `spec_path`, `plan_path`, `head_sha`, `auto`, `summary` — use those instead of re-deriving. Standalone (`/ship-issue <num>`), derive them: issue number from the branch name, spec/plan from `ls <specDir>/ | grep "issue-<num>"` and the same in `<planDir>` (filenames `YYYY-MM-DD-issue-<num>-<topic>-design.md` and `…-<topic>.md`; latest date prefix wins). Either way, the worktree state — not the handoff — is ground truth.

## The flow

```
0. Pre-flight              → worktree clean, branch matches the configured pattern, no PR yet
1. Sync integration branch → fetch + merge origin/<integrationBranch> with hybrid conflict policy
2. Verify locally          → lint + tests inside the worktree
3. Consolidate learnings   → see CONSOLIDATE.md; drop most candidates
4. Open PR                 → push -u origin <branch>; gh pr create with "Closes #<num>"
5. Review the PR           → dispatch reviewer subagent; apply Blocking items inline
6. Wait for CI             → gh pr checks --watch (one blocking call, no wakeup loop)
7. Merge                   → gh pr merge --merge with proper subject (true merge commit)
8. Cleanup                 → verify issue closed; remove worktree; delete branches
```

## Standing authorization

This skill IS the chain that "PR-handoff authorization" describes. Don't re-prompt for `git push`, `gh pr create`, `gh pr merge --merge`, branch delete, or worktree remove. Pause only where a phase says to.

## Doc-grounded escalations

Before forming *any* user-facing question this skill raises mid-flow, invoke the `doc-grounded-questions` skill (if unavailable, read whichever declared `docPaths` exist). Lead with what the relevant doc says; ask only the genuinely open part.

## gh hygiene

When `unsetGithubToken` is true, prefix every `gh` call with `unset GITHUB_TOKEN &&` — for harnesses that export a token lacking access to the target org. Default is false: use `gh` normally, unprefixed. When `issueTracker.cli` is `glab`, substitute the equivalent `glab` verbs.

## Phase 0 — Pre-flight

Verify the workspace is shippable before doing anything destructive:

1. `git rev-parse --git-common-dir` ≠ `git rev-parse --git-dir` — a linked worktree, not the main checkout.
2. `git branch --show-current` matches the regex built from `branchNaming.pattern` (default `issue-<num>-<slug>`) with an optional `branchNaming.worktreePrefix` (default `worktree-`) — for the defaults, `^(worktree-)?issue-<num>-<slug>$`. Both forms are valid: the prefix comes from `EnterWorktree`, the bare form from manual `git worktree add`. Extract `<num>`. An argument or handoff `issue_number` wins, but verify it matches the branch.
3. `git status --porcelain` returns nothing.
4. `gh pr list --head <branch> --json number,url` returns `[]` — no open PR for this branch.

Any failure: pause, ground, surface. Don't auto-fix the branch name or stash changes.

## Phase 1 — Sync from the integration branch

```
git fetch origin
git log origin/<integrationBranch>..<integrationBranch> --oneline
```

Non-empty AND those commits aren't on the feature branch (`git cherry <integrationBranch> <feature>`) → the local integration branch has diverged. **Whether to stop depends on what you're about to do:**

- **Merging `origin/<integrationBranch>` into the feature branch** (this skill's normal case) doesn't touch the local integration branch, so its divergence is irrelevant to the merge's safety. Note it so you don't later try to push that branch, then continue. Under parallel `from-issue --auto` runs, divergence is the expected steady state.
- **Anything that rewrites the local integration branch** — `git reset --hard` + cherry-pick to "clean up", `git rebase`, `git push origin <integrationBranch>` → **stop and surface**, ground against `docPaths.gitWorktrees`. Those can discard another in-flight session's spec/plan commits.

Auto-mode rule: `--auto` proceeds on the first case and still pauses on the second — auto-resolution does not extend to history rewrites. Of three audited `--auto` sessions that hit this, two silently cherry-picked or rebased the local integration branch. Don't be those two.

**Foreign commits.** `git log <feature> ^origin/<integrationBranch> --oneline` should show only this issue's commits. Older flows let unrelated issues' spec/plan commits ride into a worktree. If you see any, surface — don't clean up silently.

**Scope creep at merge time.** When this branch retires or extends a wire shape (field, discriminant, endpoint, env-var axis), siblings that landed on `origin/<integrationBranch>` *during* execution may already consume that surface. Two shapes:

- **Retirement** — modify/delete conflicts on files the integration branch removed wholesale, and/or cleanly-merged *new* files still referencing the retired symbol. Extend scope: sweep those files and clean them in the same merge commit, rather than eating a downstream typecheck failure plus a fix-up commit.
- **Addition** (symmetric) — the merge is clean, but a newly-landed sibling axis on the same surface now fires inside tests asserting "X is idle when X is unchanged". Seed the sibling axes at their intended values in the test setup so the test isolates its own invariant. Phase 2 catches this; the merge doesn't.

Concrete instances of both live in the project hints (`projectHints`; a directory → its `merge.md`) when the project declares them.

Otherwise `git merge origin/<integrationBranch>`. Clean → continue. Conflicts → hybrid policy.

**Auto-resolve allowlist (silent):**

| Pattern | Action |
|---|---|
| `**/*.lock`, `**/package-lock.json`, `**/bun.lockb`, `**/Cargo.lock`, `**/go.sum`, `**/pnpm-lock.yaml` | Regenerate from source (`pnpm install` / `bun install` / `cargo update` / `go mod tidy`); stage |
| `**/Migrations/*.cs`, `**/migrations/*.sql` | Keep both sides; verify the merged set still applies clean |
| Files with `<auto-generated>` header or `// Code generated by` | Regenerate from source; stage |
| `.claude/settings.json` | `git restore --staged .claude/settings.json && git checkout HEAD -- .claude/settings.json` — never include in the merge |

**Everything else → escalate**, one conflict at a time, after grounding on the docs that touch the conflicted file:

```
Conflict in <path> (<i> of <total>)

Hunk: lines <start>-<end>
─── ours (this branch) ───
<ours>
─── theirs (origin/<integrationBranch>) ───
<theirs>
─── blame for theirs ───
<sha> <short-message> — <author>
─── recommendation ───
<paragraph citing the doc-grounded constraint or specific rule, with reasoning>

[A] take ours  [T] take theirs  [B] custom hunk  [S] skip
```

Skipped conflicts stay in the worktree with `<<<<` markers; if any, pause at end of phase: "N conflicts left for manual resolution; resume when ready."

Commit the merge with the default merge-commit message. Don't squash.

## Phase 2 — Verify locally

```
<verify.lint>
<verify.test>
```

If neither config nor manifest detection yields a command for a step, **skip it and note the skip in the PR body** so reviewers know it wasn't run. `docPaths.devenvTooling`, where it exists, is the source of truth if the commands have moved.

Lint failures: try `verify.lintFix`, re-run `verify.lint`. Still failing → pause, ground, surface.

Test failures: separate *environmental* (Docker/Testcontainers connectivity, missing network, sandbox limits) from *real* before pausing. Baseline by running the same project in a scratch worktree on `origin/<integrationBranch>`. Same failures → pre-existing; continue and note the baseline diff in the PR body so reviewers see what was waived. Different failures → real; pause, ground, surface.

## Phase 3 — Consolidate learnings

**Read [`CONSOLIDATE.md`](./CONSOLIDATE.md) first** — it owns the mining commands, the four-part rubric, the destination table, and the reporting format. Don't paraphrase consolidation from memory.

Run its step-1 mining commands as actual tool calls (`git log <branch> ^origin/<integrationBranch>`, `gh run list --branch <branch>`, the spec/plan diff) *before* concluding anything. Empty is a finding, not a default — earn it by mining first.

Promoted candidates commit as `docs(<scope>): <summary>`, following `commit.coAuthoredBy`.

## Phase 4 — Open PR

Skip entirely when `issueTracker.kind=none` (push the branch and stop, or merge locally per the user's request).

```
git push -u origin <branch>
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

`Closes #<num>` gives the GitHub UI link between PR and issue. **Whether it auto-closes on merge depends on the base branch** — GitHub auto-close fires only when the PR base equals the **default branch**:

- `integrationBranch == defaultBranch` → merging auto-closes; Phase 8 step 1 is just verification.
- `integrationBranch != defaultBranch` (e.g. `dev` merging to `main` only at release time) → auto-close does **not** fire. The real close mechanism is Phase 8's explicit `gh issue close <num>`. Keep the trailer for traceability; don't rely on it.

**Use full URLs, not bare `#N`**, in PR bodies, comments, and commit-message references: `https://github.com/<repoSlug>/issues/<n>` or `.../pull/<n>` (`repoSlug` from config, else `git remote get-url origin`). GitHub resolves bare `#N` against the source repo context, which under cross-references lands on unrelated refs. The `Closes #<num>` trailer is the one exception — a recognized keyword resolving against the PR's base repo.

## Phase 5 — Review the PR

```
BASE_SHA=$(git merge-base HEAD origin/<integrationBranch>)
HEAD_SHA=$(git rev-parse HEAD)
```

Dispatch a fresh subagent via the `Agent` tool (`general-purpose`, no inherited context). Nested dispatch works even when this skill is itself inside an `Agent` subagent, but the schema is sometimes deferred — if `Agent` isn't in your tool surface, call `ToolSearch` with `query: "select:Agent"` first. Don't fall back to inlining the review; that deprecated path re-loads the spec/plan into your already-large context.

The **generic rubric below is fixed — use it verbatim**. The project-specific paragraph comes from `projectHints` (a directory → its `review.md`; a file → itself); omit it silently when absent.

> Review the diff from `<BASE_SHA>` to `<HEAD_SHA>` against the project's coding bar.
>
> First invoke `doc-grounded-questions` **via the Skill tool** (not inline — its body re-injects current pointers to the project's domain/ADR/standards/architecture docs); if unavailable, read whichever of `docPaths.context`, `docPaths.adrDir`, `docPaths.standards`, `docPaths.architecture` exist. Then read the issue body (`gh issue view <num>`), the spec at `<spec-path>`, and the plan at `<plan-path>` for what the diff was supposed to deliver.
>
> **Read the live file at HEAD when checking a finding**, not a diff or snapshot view — reviews have produced false-positive Should-fixes by quoting stale snapshots after the spec/plan were edited mid-flow.
>
> Evaluate the diff against the grounded constraints. Output:
>
> - **Blocking** — must fix before merge
> - **Should-fix** — strong recommendation; justify if you skip
> - **Discussion** — judgment calls worth raising with the user
>
> [PROJECT-SPECIFIC, only when `projectHints` exists] Pay particular attention to the recurring review hazards documented in the project hints — the refactor traps and domain invariants reviews on this codebase keep missing. Fold those concrete examples in here.
>
> Don't propose new features. Don't second-guess scope. Grade only against the bar and the delivered-vs-spec gap.
>
> Return findings ranked most-severe first, each anchored to a file:line, with a one-line verdict (approve | fix-first) at the top. Cap the whole report at ~400 words — your reply is re-read by the caller on every later turn; detail beyond the cap belongs in the finding's file:line anchor, not the report.

Apply Blocking fixes inline — but `apply` and `push` are separate steps, not one verb. The failure mode is "edited files, ran tests, forgot to commit, advanced to Phase 6 polling CI on the stale tip." Follow this order:

1. Edit the file(s).
2. Re-run `verify.lint` + `verify.test` against the modified surface.
3. `git add` the changed files; commit `fix(issue-<num>): address PR review — <short blocker>` (follow `commit.coAuthoredBy`).
4. `git push`.
5. Verify the push landed: `gh pr view <pr-num> --json headRefOid` must equal `git rev-parse HEAD`. Diverged → the push didn't take; retry before Phase 6.

In `--auto`, apply Should-fix items inline through the same five steps and log each as a PR comment with a one-line rationale. Only Discussion items stay user-facing — surface those with a doc-grounded prompt. Then continue.

## Phase 6 — Wait for CI

Before blocking, verify CI is running on the right tip: `gh pr view <pr-num> --json headRefOid` must equal `git rev-parse HEAD`. Diverged → the Phase 5 push didn't land; re-push, otherwise CI runs on the unfixed code.

Then block with `gh`'s built-in watch — one Bash call, **300s timeout**:

```
timeout 300 gh pr checks <pr-num> --watch --fail-fast --interval 30
```

The 5-minute ceiling forces an assistant turn every ~5 min, which keeps the subagent stream alive; the harness reaps a subagent that goes silent for ~9+ min on a blocking Bash (which is what a 540s timeout produced). `--fail-fast` exits on the first check to flip into a failing bucket, so failures surface without waiting on parallel checks.

**Foreground only — do NOT background this.** No `run_in_background: true`, no `Monitor`. The harness yields a subagent indefinitely when it sees a long-running monitored background Bash and the subagent never wakes to issue the next turn. The blocking foreground shape is correct: `gh` polls the API at the network layer every ~30s while Bash blocks, costing zero model turns until it returns.

**No improvised polling — the blocking watch is the only sanctioned wait shape.** Transcript mining found one session that ran a bare `gh pr checks <n> | grep <check>` 244 times, plus sessions burning dozens of `gh run view` re-runs and `true`/`:`/`date` no-op keep-alive turns; every such poll is a full model turn that re-reads the entire session prefix. Never run `gh pr checks` without `--watch` more than once per phase, never re-run `gh run view`/`tail` on a loop, never emit no-op commands to pass time. For a single named check, still run the blocking watch and read that check's row from its final output (or one `--json name,bucket` call afterwards).

Exit codes:

- **`0`** → all checks pass; continue to Phase 7.
- **`124`** (`timeout` fired) → still running past ~5 min. **Emit one short narration turn** (`CI: still pending at 5m, retry 2/8`) as the keep-alive, then re-run the identical command. Up to **8 times (~40 min)**. Still pending after that → escalate: GitHub Actions webhooks can fail to fire silently, leaving a PR indefinitely on "expected — Waiting for status to be reported". Prompt: "PR #<n> has been pending for ~40 min with no terminal CI state. Options: (a) wait another 10 min, (b) close+reopen to re-trigger checks, (c) merge without CI if the project allows admin-merge, (d) abort and investigate manually."
- **any other non-zero** → a check failed (or `gh` errored). Pull `gh run view <run-id> --log-failed`, ground against the failing surface (lint → standards doc, test → area spec/plan), surface.

**JSON-field note.** `conclusion` is not a valid field on `gh pr checks` — `gh` rejects it (`--help` lists the real set). When you need structured output, `bucket` (pass/fail/pending/skipping/cancel) is the cleanest decision field.

## Phase 7 — Merge

(When `issueTracker.kind=none`, merge the branch into the integration branch locally per the user's instruction instead.)

Build the subject from `mergeSubjectTemplate` (substituting `<feature>`/`<desc>`/`<num>`/`<integrationBranch>`); if it's null, omit `--subject` and let the forge default stand.

```
gh pr merge <pr-num> --merge --subject "<rendered mergeSubjectTemplate>" --delete-branch
```

**Do not pass `--no-ff`** — recent `gh` (≥ 2.83) rejects it (`unknown flag: --no-ff`), and `--merge` alone already produces a true merge commit (no squash, no rebase, no fast-forward).

`--delete-branch` may fail or silently no-op on the remote branch while the worktree still has it checked out. The remote merge still succeeds. After verifying the merge, if `gh pr view <pr-num> --json headRefName` still resolves the branch, run `git push origin --delete <branch>` (actual branch name, including `branchNaming.worktreePrefix` if present).

Verify: `gh pr view <pr-num> --json state,mergeCommit` → `MERGED` plus a non-null `mergeCommit.oid` means it landed.

## Phase 8 — Cleanup

1. `gh issue view <num> --json state`; if `OPEN`, `gh issue close <num>`. (Auto-close should have fired when `integrationBranch == defaultBranch`; when they differ this explicit close is the real mechanism — see Phase 4.)

2. Remove the worktree from the main repo root, never from inside the worktree:
   ```
   MAIN_ROOT=$(git -C "$(git rev-parse --git-common-dir)/.." rev-parse --show-toplevel)
   cd "$MAIN_ROOT"
   git worktree remove <worktree-path>
   git worktree prune
   git branch -d <branch>
   ```

3. If `git worktree remove` refuses on the rebased-branch case (see `docPaths.gitWorktrees`): confirm the PR landed via `gh pr view`, then retry with `ExitWorktree action: "remove", discard_changes: true`. The "discarded N commits" wording is misleading — the content is on the integration branch via the merge commit.

Report final state: PR URL, merge commit SHA, issue closed.

## Notes

- Merge commits, learning-doc updates, and blocker fixes fall under standing local-commit authorization. Don't re-confirm each. The `Co-Authored-By` trailer follows `commit.coAuthoredBy`.
- If a phase reveals an earlier one was wrong (review surfaces a misaligned spec, say), back up to the appropriate `from-issue` phase. Don't paper over.
- Absent sibling skills (`from-issue`, `sdd`, `worktrees`) degrade to no-ops; this skill still runs.
