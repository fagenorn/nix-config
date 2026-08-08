---
name: ship-issue
description: Deliver a finished feature-branch worktree — sync integration branch, PR, review, CI, merge, close issue, clean up. Phase 7 of from-issue. Use for "ship #X", "land it".
argument-hint: "[issue number — optional; inferred from branch name]"
---

# Ship Issue

Counterpart to `to-issues` and `from-issue`. Take a worktree branch that has the implementation committed and deliver it: merged on the integration branch, issue closed, workspace gone.

## Project bindings (resolve first)

This skill is project-agnostic. Before acting, resolve project-specific values:

1. If `.claude/skills.config.json` exists at the project root (cwd), read it for the bindings below.
2. For any absent key (or no config file), auto-detect: issue tracker = `gh` if the git remote is github.com (else `glab`/none); verify commands from the manifest (`package.json` scripts, `*.slnx`/`*.sln` → `dotnet test`, `Cargo.toml` → `cargo test`, `go.mod` → `go test`, `Makefile` → `make test`); branches from the repo default.
3. Defaults when neither config nor detection yields a value: `integrationBranch=main`, `defaultBranch=main`, `commit.coAuthoredBy=true`, `unsetGithubToken=false`, `specDir=.claude/specs`, `planDir=.claude/plans`.
4. Degrade gracefully: any configured-but-absent doc path, sibling skill, or hints file is skipped silently — never read a file that does not exist, never hard-fail on a missing optional binding.

Keys this skill uses: `integrationBranch`, `defaultBranch`, `issueTracker{kind,cli}`, `repoSlug`, `unsetGithubToken`, `verify{lint,lintFix,test}`, `commit.coAuthoredBy`, `mergeSubjectTemplate`, `branchNaming{pattern,worktreePrefix}`, `docPaths.*`, `specDir`, `planDir`, `projectHints`.

Throughout this skill, references to "the integration branch" mean `integrationBranch` (the branch feature work merges into) and "the default branch" means `defaultBranch` (the repo's default/prod branch that controls GitHub auto-close-on-merge). When `issueTracker.kind=none`, skip every issue/PR linkage step and operate on the branch directly; the merge/sync/verify/consolidate machinery still applies.

**Two invocation paths.** When `from-issue` runs end-to-end, it dispatches this skill as a fresh `Agent` subagent — the prompt that starts the subagent contains a handoff block (`issue_number`, `branch`, `worktree_path`, `spec_path`, `plan_path`, `head_sha`, `auto`, `summary`). Use those fields directly; they save Phase 0 from re-deriving things `from-issue` already knew. When the user invokes `/ship-issue <num>` standalone (no parent subagent dispatch), there is no handoff — Phase 0 falls back to discovering everything from the worktree. Both paths run the same phases below.

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

This skill IS the chain that "PR-handoff authorization" describes. Don't re-prompt for `git push`, `gh pr create`, `gh pr merge --merge`, branch delete, or worktree remove. Pause only on the specific points called out under each phase below.

## Doc-grounded escalations

Every user-facing question this skill raises mid-flow — pre-flight failures, conflict resolutions, lint/test failures, CI failures, review-blocker decisions, cleanup oddities — invoke the `doc-grounded-questions` skill before forming the prompt (if it is unavailable, fall back to reading whatever `docPaths` the project config declares that exist). Lead with what the relevant doc says; ask only the genuinely open part.

## gh hygiene

If `unsetGithubToken` is true (config), `unset GITHUB_TOKEN` (or `env -u GITHUB_TOKEN`) before every `gh` call. This is for projects whose harness exports a token without access to the target org — when `unsetGithubToken` is false (the default), use `gh` normally without stripping the token. The `gh` invocations below are written with the `unset GITHUB_TOKEN &&` prefix as the config-gated form; drop the prefix when `unsetGithubToken` is false. When `issueTracker.cli` is `glab`, substitute the equivalent `glab` commands; when `issueTracker.kind=none`, skip these calls entirely.

## Phase 0 — Pre-flight

**Handoff awareness.** When `from-issue` dispatches this skill as a subagent (the normal autonomous path), the prompt that bootstrapped the subagent already contains the handoff payload — issue number, branch, worktree path, spec path, plan path, head SHA, execute summary, `auto` flag. Use those fields directly instead of re-deriving anything `from-issue` already knew. The pre-flight checks below still run regardless, because the worktree state is the ground truth and the prompt is only a hint.

Verify the workspace is shippable before doing anything destructive:

1. `git rev-parse --git-common-dir` ≠ `git rev-parse --git-dir` — confirms a linked worktree, not the main checkout.
2. `git branch --show-current` matches the configured branch pattern. Build the regex from `branchNaming.pattern` (default `issue-<num>-<slug>`), allowing an optional `branchNaming.worktreePrefix` (default `worktree-`). For the defaults this is `^(worktree-)?issue-<num>-<slug>$`. (The prefix comes from `EnterWorktree`; the bare form comes from manual `git worktree add`. Both are valid.) Extract `<num>` for use throughout. If the user passed an argument or the handoff supplied `issue_number`, prefer that and verify it matches the branch.
3. `git status --porcelain` returns nothing — no uncommitted or staged changes.
4. `gh pr list --head <branch> --json number,url` returns `[]` — no open PR for this branch. (Skip when `issueTracker.kind=none`.)

Any failure: pause, ground the prompt per `doc-grounded-questions`, surface the situation. Don't auto-fix the branch name or stash changes — surface and let the user resolve.

## Phase 1 — Sync from the integration branch

```
git fetch origin
```

Before merging, check for a diverged local integration branch:

```
git log origin/<integrationBranch>..<integrationBranch> --oneline
```

Non-empty AND those commits aren't on the feature branch (`git cherry <integrationBranch> <feature>` to confirm) → the divergence exists. **Whether to stop depends on what you're about to do**:

- **Standard worktree-driven flow (this skill's normal case).** You're operating on the feature branch in an isolated worktree; the next operation is `git merge origin/<integrationBranch>` *into the feature branch*. That merge does not touch the local integration branch — its diverged state is irrelevant to the merge's safety. Note the divergence in your reasoning so you don't forget those parallel commits exist (and so you don't later try to push the local integration branch), then continue. Common case under multi-agent runs (e.g. `from-issue --auto` on parallel issues) — divergence is the *expected* steady state, not a bug.
- **Anything that would touch the local integration branch directly** — `git reset --hard origin/<integrationBranch>` + cherry-pick to "clean up", `git rebase`, `git push origin <integrationBranch>`, etc. → **stop**. Those operations may discard another in-flight session's spec/plan commits. Invoke `doc-grounded-questions` (against `docPaths.gitWorktrees` if it exists) and surface to the user. Do not silently recover, even in `--auto` — `git reset --hard` is a destructive op and auto-resolution doesn't extend to it.

Auto-mode rule: in `--auto`, the worktree-driven flow case does not pause; it proceeds with the merge after logging the divergence. The destructive-ops case still pauses. Audit reality: across three `/from-issue --auto` sessions that hit integration-branch divergence, only one correctly paused at the destructive-ops case — the other two silently cherry-picked / rebased the local integration branch. Don't be those two. If you're about to run anything that rewrites the integration branch's history, pause regardless of `--auto`.

**Cross-cutting foreign-commit hazard.** When `from-issue --auto` runs in parallel, an earlier version of the flow let spec/plan/grill commits land on the local integration branch *before* the worktree was created — those commits then rode along into whichever worktree was created next. The current `from-issue` creates the worktree at Phase 1 based on `origin/<integrationBranch>`, which fixes the source. But if `ship-issue` runs against an older worktree created under the previous flow, `git log <feature> ^origin/<integrationBranch> --oneline` may show commits that don't belong to this issue (spec files for unrelated issues, etc.). If you see them, surface — don't try to clean up silently.

**Wire-shape retirement scope creep.** When the branch retires a field / discriminant / endpoint, expect to find sibling branches that landed on `origin/<integrationBranch>` *during* this issue's execution to have consumed the retired surface in new code. The conflict shape is recognisable: (a) modify/delete on files the branch edited that `origin/<integrationBranch>` removed wholesale, AND/OR (b) clean-merged newly-added files that reference the field the branch retires. Resolve by extending scope — sweep the new files for the retired symbol and clean them in the same merge commit. Don't shrug at the merge and let typecheck fail downstream. Audit reality: an issue retired an `Origin` field end-to-end; mid-execution, a sibling issue landed a new `models-table.tsx` that branched on `origin.origin === 'seed'`, requiring a one-commit scope extension at merge time. The ship-issue verification gate would have caught it, but cleaning at merge-time is cheaper than a separate fix-up commit.

**Wire-shape addition scope creep (the symmetric case).** Same shape with the integration branch as the additive party. When the integration branch lands a *new* sibling axis on a surface the feature branch tests for idle/no-op behaviour, the merge is clean but the feature branch's "X is idle when X is unchanged" assertions can fire on the newly-added axis. Example: an issue added `AGENT_BROWSER_PROXY` env-rewrites on `kind=browser`; mid-execution, a sibling landed `NODO_AUTH_PROXY_LISTEN_HOST` env-rewrites on every `kind=mcp` row. The feature branch's `BrowserProxyToken_IdleWhenUnchanged` test seeded only the proxy var, leaving listen-host empty — after merge the listen-host write fired and the no-restart assertion broke. Fix: identify which sibling axes the test now triggers, seed those at their desired values in the test setup so the test isolates its target invariant. Phase 2's local verify catches this; the merge itself doesn't.

Otherwise, merge:

```
git merge origin/<integrationBranch>
```

Clean merge → continue.

Conflicts → apply the hybrid policy.

**Auto-resolve allowlist (silent):**

| Pattern | Action |
|---|---|
| `**/*.lock`, `**/package-lock.json`, `**/bun.lockb`, `**/Cargo.lock`, `**/go.sum`, `**/pnpm-lock.yaml` | Regenerate from source (`pnpm install` / `bun install` / `cargo update` / `go mod tidy`); stage |
| `**/Migrations/*.cs`, `**/migrations/*.sql` | Keep both sides; verify the merged set still applies clean |
| Files with `<auto-generated>` header or `// Code generated by` | Regenerate from source; stage |
| `.claude/settings.json` | `git restore --staged .claude/settings.json && git checkout HEAD -- .claude/settings.json` — never include in the merge |

**Everything else → escalate** with the prompt below, one conflict at a time. Before forming each prompt, invoke `doc-grounded-questions` and read the domain terms / ADRs / coding-standards rules touching the conflicted file (from whichever `docPaths` exist).

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

Skipped conflicts stay in the worktree with `<<<<` markers. If any skips happened, pause at end of phase: "N conflicts left for manual resolution; resume when ready."

Commit the merge with the default merge-commit message format. Don't squash.

## Phase 2 — Verify locally

Resolve the verify commands from config (`verify.lint`, `verify.test`, `verify.lintFix`); if a key is absent, auto-detect from the manifest (`package.json` scripts, `*.slnx`/`*.sln` → `dotnet test`, `Cargo.toml` → `cargo test`, `go.mod` → `go test`, `Makefile` → `make test`). If neither config nor detection yields a command for a given step, **skip that step and note the skip in the PR body** so reviewers know it wasn't run.

```
<verify.lint>
<verify.test>
```

Check `docPaths.devenvTooling` (if it exists) for the canonical command set — if the resolved commands have moved, that doc is the source of truth.

Lint failures: try `verify.lintFix` (if defined) then re-run `verify.lint`. Still failing → pause, ground, surface.

Test failures: distinguish *environmental* (Docker/Testcontainers connectivity, missing network, sandbox limits) from *real* before pausing. To baseline: spin up a scratch worktree on `origin/<integrationBranch>`, run the same project there. Same failures → environmental & pre-existing — continue, and note the baseline diff in the PR body so reviewers see what was waived. Different failures → real, pause, ground, surface.

## Phase 3 — Consolidate learnings

**Read [`CONSOLIDATE.md`](./CONSOLIDATE.md) first** — it sits next to this file. Don't paraphrase from memory: the mining commands, four-part rubric, destination table, and reporting format are encoded there and have evolved. Your prior about "what consolidation means" is not the procedure.

Then run CONSOLIDATE step 1's mining commands as actual tool calls (`git log <branch> ^origin/<integrationBranch>`, `gh run list --branch <branch>`, the spec/plan diff) *before* forming any empty-vs-non-empty conclusion. Empty is a finding, not a default — earn it by running the mining first.

If anything was promoted, commits land here as `docs(<scope>): <summary>`. Follow `commit.coAuthoredBy` for the `Co-Authored-By` trailer (default: include).

## Phase 4 — Open PR

Skip this phase entirely when `issueTracker.kind=none` (push the branch and stop, or merge locally per the user's request). Otherwise:

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

(Prefix the `gh` calls with `unset GITHUB_TOKEN &&` when `unsetGithubToken` is true.)

Title: use the issue title verbatim unless the implementation deviated meaningfully (then describe the actual delivery). Under 70 chars; details go in the body.

The `Closes #<num>` line provides the GitHub UI link between PR and issue. **Whether it auto-closes the issue on merge depends on the base branch**: GitHub auto-close fires only when the PR base equals the **default branch** (`defaultBranch`). So:
- If `integrationBranch == defaultBranch`, merging this PR *will* auto-close the issue — Phase 8 step 1 is just a verification.
- If `integrationBranch != defaultBranch` (e.g. a separate `dev` integration branch merging into `main`), auto-close does **not** fire on this merge. The real close mechanism is Phase 8's explicit `gh issue close <num>`. Keep the trailer for traceability; don't rely on it.

**Reference syntax: use full URLs, not bare `#N`.** In the PR body, in PR comments, in commit-message references, write `https://github.com/<repoSlug>/issues/<n>` or `.../pull/<n>` — not `#107`. (Derive `<repoSlug>` from config `repoSlug`, else `git remote get-url origin`.) GitHub resolves bare `#N` against the source repo context, which under cross-references (or when the agent's mental model of "this repo" is wrong) lands on unrelated refs. The `Closes #<num>` trailer is the one exception — it's a recognized GitHub keyword in PR bodies and resolves against the PR's base repo, which is correct here.

## Phase 5 — Review the PR

Get base/head first:

```
BASE_SHA=$(git merge-base HEAD origin/<integrationBranch>)
HEAD_SHA=$(git rev-parse HEAD)
```

Dispatch a fresh subagent via the `Agent` tool (`general-purpose`, no inherited context). Nested `Agent` dispatch is supported even when this skill is itself running inside an `Agent` subagent — but the schema is sometimes deferred. If the `Agent` tool isn't visible in your current tool surface, call `ToolSearch` with `query: "select:Agent"` first to load it; only then invoke it. Don't fall back to inlining the review when this happens — inline review is the deprecated path that re-loads the spec/plan into your already-large context.

The reviewer prompt has two layers. The **generic rubric is fixed** (use it verbatim). The **project-specific examples** come from `projectHints` (if that file exists) — read it and fold its review hints / domain vocab into the prompt; if it's absent, omit the project-specific paragraph silently.

> Review the diff from `<BASE_SHA>` to `<HEAD_SHA>` against the project's coding bar.
>
> First invoke the `doc-grounded-questions` skill **via the Skill tool** (not inline; the skill's body re-injects up-to-date pointers to the project's domain/ADR/standards/architecture docs). If that skill is unavailable, read whatever of `docPaths.context`, `docPaths.adrDir`, `docPaths.standards`, `docPaths.architecture` exist. Then read the linked issue body (`gh issue view <num>`), the spec at `<spec-path>`, and the plan at `<plan-path>` for what the diff was supposed to deliver.
>
> **When checking specific findings, Read the live file at HEAD** rather than relying on diff/snapshot views. Reviews have produced false-positive Should-fixes by quoting stale snapshots after the spec/plan were edited mid-flow.
>
> Evaluate the diff against the grounded constraints. Output:
>
> - **Blocking** — must fix before merge
> - **Should-fix** — strong recommendation; justify if you skip
> - **Discussion** — judgment calls worth raising with the user
>
> [PROJECT-SPECIFIC, only if `projectHints` exists] Pay particular attention to the recurring review hazards documented in the project hints (e.g. known refactor traps, nullability-lift equivalence in predicate-to-`Contains` translations over nullable surfaces, domain-specific invariants) — fold those concrete examples in here.
>
> Don't propose new features. Don't second-guess scope. Grade only against the bar and the delivered-vs-spec gap.
>
> Return findings ranked most-severe first, each anchored to a file:line, with a one-line verdict (approve | fix-first) at the top. Cap the whole report at ~400 words — your reply is re-read by the caller on every later turn; detail beyond the cap belongs in the finding's file:line anchor, not the report.

Apply Blocking fixes inline to the branch — but `apply` and `push` are separate steps, not one verb. The failure mode is "edited files, ran tests, forgot to commit, advanced to Phase 6 polling CI on the stale tip." Follow this order:

1. Edit the file(s).
2. Re-run `verify.lint` + `verify.test` against the modified surface.
3. `git add` the changed files; commit with `fix(issue-<num>): address PR review — <short blocker>` (follow `commit.coAuthoredBy`).
4. `git push`.
5. Verify the push landed: `gh pr view <pr-num> --json headRefOid` should equal `git rev-parse HEAD`. Diverged → push didn't take, retry before Phase 6.

In `--auto` mode (invoked from `from-issue --auto`), apply Should-fix items inline using the same five-step procedure and log each as a PR comment with a one-line rationale. Only Discussion items remain user-facing — surface those with a doc-grounded prompt. Then continue to Phase 6.

## Phase 6 — Wait for CI

(Skip when `issueTracker.kind=none`.)

Before blocking on CI, verify it's running on the right tip:

```
gh pr view <pr-num> --json headRefOid
```

Must equal `git rev-parse HEAD`. Diverged → the Phase 5 fix-and-push step didn't land; re-push before continuing, otherwise CI runs on the unfixed code.

Then block on CI completion with `gh`'s built-in watch — one Bash call with a **300s timeout**. The 5-minute ceiling matters: it forces you to emit an assistant turn every ~5 min, which keeps the subagent stream alive. Earlier versions used 540s and died mid-Phase-6 when CI took >9 min — the harness reaps a subagent that goes silent for ~9+ min on a blocking Bash:

```
timeout 300 gh pr checks <pr-num> --watch --fail-fast --interval 30
```

(Prefix with `unset GITHUB_TOKEN &&` when `unsetGithubToken` is true.)

**Foreground only — do NOT background this.** Run it as a normal blocking Bash. Do not pass `run_in_background: true` and do not use `Monitor` to wait on it. The harness yields a subagent indefinitely when it sees a long-running monitored background Bash, and the subagent never wakes up to issue the next turn. The foreground blocking shape is correct: `gh` polls the API at the network layer at ~30s cadence while Bash blocks, costing zero model turns until it returns.

`--fail-fast` exits on the first check that flips to a failing bucket, so failures surface immediately rather than waiting on parallel checks.

**No improvised polling — the blocking watch above is the only sanctioned wait shape.** Transcript mining found one session that ran a bare `gh pr checks <n> | grep <check>` 244 times, plus sessions burning dozens of `gh run view` re-runs and `true`/`:`/`date` no-op keep-alive turns — every such poll is a full model turn that re-reads the entire session prefix. Never run `gh pr checks` without `--watch` more than once per phase; never re-run `gh run view`/`tail` on a loop; never emit no-op commands to pass time. If you only care about one named check, still run the blocking watch, then read that check's row from its final output (or one `--json name,bucket` call after it returns).

Exit codes:

- **`0`** → all checks pass; continue to Phase 7.
- **`124`** (Bash `timeout` fired) → CI still running past ~5 min. **Emit one short narration turn** (e.g. `CI: still pending at 5m, retry 2/8`) before re-invoking — that turn is the keep-alive. Then re-run the same `timeout 300 gh pr checks ...` command. Repeat up to **8 times (~40 min cumulative)**. If still pending after 8 retries, surface a checkpoint per the doc-grounded escalation pattern. GitHub Actions webhooks can fail to fire silently and a PR can sit indefinitely with "expected — Waiting for status to be reported". The escalation prompt: "PR #<n> has been pending for ~40 min with no terminal CI state. Options: (a) wait another 10 min, (b) close+reopen to re-trigger checks, (c) merge without CI if the project allows admin-merge, (d) abort and investigate manually."
- **any other non-zero** → at least one check failed (or `gh` itself errored). Pull the failing run's logs (`gh run view <run-id> --log-failed`), invoke `doc-grounded-questions` against the failing surface (lint → the standards doc rule, test → area spec/plan), then surface to user.

**Why no wakeup loop.** Earlier versions of this phase polled with a scheduled-wakeup loop at a ~3-minute cadence — 10-12 wakeups × ~4 model turns each × ~300k cached context per turn = ~1-1.5M weighted tokens per run, just for "is CI green yet?". `gh --watch` does the same poll at the network layer for free; one blocking Bash call replaces the entire loop.

**JSON-field note.** Earlier versions of this phase used `gh pr checks --json state,name,conclusion,bucket`; `conclusion` is not a valid field on `gh pr checks` (`gh` rejects it). Valid fields: `bucket,completedAt,description,event,link,name,startedAt,state,workflow`. `bucket` (pass/fail/pending/skipping/cancel) is the cleanest decision field when you do need structured output.

## Phase 7 — Merge

(Skip when `issueTracker.kind=none`; for that case, fast-forward or merge the branch into the integration branch locally per the user's instruction.)

Build the merge subject from `mergeSubjectTemplate` (substituting `<feature>`/`<desc>`/`<num>`/`<integrationBranch>`); if it's null, omit `--subject` and let the forge default stand.

```
gh pr merge <pr-num> \
  --merge \
  --subject "<rendered mergeSubjectTemplate>" \
  --delete-branch
```

(Prefix with `unset GITHUB_TOKEN &&` when `unsetGithubToken` is true.)

`gh pr merge` on recent `gh` (≥ 2.83) does **not** accept `--no-ff` — the flag is rejected with `unknown flag: --no-ff`. `--merge` alone already creates a true merge commit (no fast-forward), so passing `--no-ff` is both redundant and broken. The intent (true merge commit, no squash, no rebase) is documented here in prose instead.

The `--subject` override is only needed when `mergeSubjectTemplate` is set and the forge default doesn't match the project convention. If `mergeSubjectTemplate` is null, skip `--subject`.

`--delete-branch` may report failure or silently no-op on the remote branch when the worktree is still checked out elsewhere (the local branch is "in use"). The remote merge itself still succeeds. After verifying the merge landed, if `gh pr view <pr-num> --json headRefName` still resolves the branch, delete the remote ref manually:

```
git push origin --delete <branch>
```

(Use the actual branch name, including the `branchNaming.worktreePrefix` if present.)

Then verify the merge:

```
gh pr view <pr-num> --json state,mergeCommit
```

`MERGED` + non-null `mergeCommit.oid` means it landed.

## Phase 8 — Cleanup

1. Verify the issue closed (skip when `issueTracker.kind=none`):
   ```
   gh issue view <num> --json state
   ```
   If `OPEN`, run `gh issue close <num>`. (When `integrationBranch == defaultBranch` the merge should have auto-closed it; when they differ, this explicit close is the real mechanism — see Phase 4.)

2. Remove the worktree from the main repo root (never from inside the worktree):
   ```
   MAIN_ROOT=$(git -C "$(git rev-parse --git-common-dir)/.." rev-parse --show-toplevel)
   cd "$MAIN_ROOT"
   git worktree remove <worktree-path>
   git worktree prune
   git branch -d <branch>
   ```

3. If `git worktree remove` refuses on the rebased-branch case (check `docPaths.gitWorktrees` if it exists): verify the PR landed via `gh pr view`, then retry with `ExitWorktree action: "remove", discard_changes: true`. The "discarded N commits" wording is misleading — the content is on the integration branch via the merge commit.

Report final state: PR URL, merge commit SHA, issue closed.

## Notes

- The `Co-Authored-By` trailer follows `commit.coAuthoredBy` (default: include). When the project config sets it false, omit the trailer on all commits in this skill.
- Commits made during this flow (merge commits, learning doc updates, blocker fixes) fall under standing local-commit authorization. Don't re-confirm each.
- If a phase reveals an earlier phase was wrong (e.g. review surfaces that the spec was misaligned), back up to the appropriate `from-issue` phase. Don't paper over.
- If `ship-issue` is invoked standalone (the user types `/ship-issue <num>` in a fresh session, not via `from-issue`'s subagent dispatch): the worktree state is the source of truth. Branch name gives the issue number; spec/plan paths come from `ls <specDir>/ | grep "issue-<num>"` and `ls <planDir>/ | grep "issue-<num>"` (filenames follow `YYYY-MM-DD-issue-<num>-<topic>-design.md` and `YYYY-MM-DD-issue-<num>-<topic>.md` respectively). If multiple matches, take the latest by date prefix. If `from-issue` / `superpowers:*` sibling skills are absent, this skill still runs — the sibling references degrade to no-ops.
