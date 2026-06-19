---
name: ship-release
description: Drive an integration-branch → default-branch release end-to-end — generate a changelog from the merges that have accumulated on the integration branch, open the release PR, wait for CI, merge with a true merge commit, decide the next semver version (MAJOR / MINOR / PATCH) from the change categorisation, tag the merge commit and publish a GitHub Release, then (when a deploy adapter is configured) watch the platform until every affected service has the merge SHA running at a SUCCESS status. Use whenever the user says "release", "cut a release", "ship to prod", "push to main", "dev to main", "roll out", "deploy", "go to prod", "bump the version", or otherwise indicates that the work accumulated on the integration branch should land on the default branch and reach production. Covers the silent-rollback trap so a failed deploy can't masquerade as a successful one, and the version bookkeeping so each release has a stable named anchor.
argument-hint: "[scope hint — optional one-line summary phrase to seed the merge subject]"
---

# Ship Release

Counterpart to `ship-issue` (if available): where `ship-issue` lands one feature on the integration branch, `ship-release` lands the accumulated integration branch on the default branch, tags + publishes a GitHub Release, and (when a deploy adapter is configured) watches the platform pick it up. The unit of work here is **all merges on the integration branch since the last default-branch merge**, not a single issue.

## Project bindings (resolve first)

This skill is project-agnostic. Before acting, resolve project-specific values:

1. If `.claude/skills.config.json` exists at the project root, read it for the bindings below.
2. For any absent key (or no config file), auto-detect: issue tracker = `gh` if the git remote is github.com (else `glab`/none); verify commands from the manifest (package.json scripts, `*.slnx`/`*.sln` → dotnet test, Cargo.toml → cargo test, go.mod → go test, Makefile → make test); branches from the repo default.
3. Defaults when neither config nor detection yields a value: `integrationBranch=main`, `defaultBranch=main`, `commit.coAuthoredBy=true`, `unsetGithubToken=false`, `deploy.adapter=none`, `specDir=.claude/specs`, `planDir=.claude/plans`.
4. Degrade gracefully: any configured-but-absent doc path, sibling skill, or hints file is skipped silently — never read a file that does not exist, never hard-fail on a missing optional binding.

Keys this skill reads: `integrationBranch`, `defaultBranch`, `issueTracker{kind,cli}`, `repoSlug`, `unsetGithubToken`, `commit.coAuthoredBy`, `deploy{adapter,project,env,services,watchDoc}`, `docPaths{deploy,gitWorktrees,standards,adrDir}`, `projectHints`.

Throughout this document, `<integration>` means the resolved `integrationBranch` (default `main`) and `<default>` means the resolved `defaultBranch` (default `main`). Where they're identical (the common single-branch repo), the "integration → default" flow collapses to "tag-and-release HEAD of the default branch" — there is no separate PR to open; skip straight to Phase 4.5 after confirming the working tree is at the tip you intend to release. The two-branch flow below is the general case.

When `repoSlug` is absent, derive it once from `git remote get-url origin` (strip the `git@github.com:` / `https://github.com/` prefix and the trailing `.git`) and reuse it for every PR/commit/release URL. **Never hardcode an owner/name.**

When `issueTracker.kind == "none"`, there is no forge for PRs/CI/releases. Degrade to: merge the integration branch into the default branch locally with a true merge commit (`git merge --no-ff`), tag it, and skip the PR, CI-wait, GitHub-Release, and any forge-specific steps. Report the merge SHA + tag.

## The flow

```
0. Pre-flight             → default checkout (not a worktree), working tree clean, <integration> ahead of <default>, no open release PR, <integration> CI green, local/origin <integration> in sync
1. Changelog              → mine merges since last release; assemble the categorised PR body per CHANGELOG.md
2. Open PR                → push nothing (<integration> is already on origin); gh pr create --base <default> --head <integration>
3. Wait for CI            → wake/poll loop, ~3 min cadence, against the PR head
4. Merge                  → gh pr merge --merge (NO --delete-branch when <integration> != <default> — the integration branch is permanent)
4.5. Tag + Release        → decide semver bump from CHANGELOG.md categories; tag merge commit; gh release create with PR body as notes
5. Watch deploy           → only when deploy.adapter != none: poll the platform per affected service until commit matches merge SHA and status is SUCCESS
6. Report                 → PR URL, merge SHA, version tag + release URL, per-service deployment IDs + statuses (or "no deploy adapter configured")
```

## Standing authorization

When the user says "release", "ship to prod", "do the release", or similar, that authorises the full chain: opening the PR, waiting for CI, merging with `--merge`, tagging + publishing the Release, and (when a deploy adapter is configured) polling the platform until each affected service is on the merge SHA. Don't re-prompt at each step. Pause only on:

- Pre-flight failures (Phase 0).
- A CI check finishing as `FAILURE` / `CANCELLED` / `TIMED_OUT` (Phase 3).
- A deployment finishing as `FAILED` (Phase 5) — *especially* the silent-rollback case where the platform shows `FAILED` but a health probe still returns 200 against the previous build.
- Genuinely new risks not covered above.

This matches the common "PR-handoff authorization is one round, not many" convention.

## Doc-grounded escalations

Every user-facing question this skill raises mid-flow — pre-flight oddities, conflict resolutions, CI failures, deploy anomalies — invoke `doc-grounded-questions` (if available) before forming the prompt. Lead with what the relevant doc says, then ask only the genuinely open part:

- Deploy / platform questions → `docPaths.deploy` (and `deploy.watchDoc` if set).
- Git ops → `docPaths.gitWorktrees`.
- The bar → `docPaths.standards`.

If `doc-grounded-questions` is not installed, still read the configured doc (when the path exists) before forming the question, and skip silently if it's absent. The silent-rollback gotcha, the "latest-deployment-commit vs actually-built-commit" distinction, and the stale-`FAILED`-notification trap are deploy-platform concerns — read the configured deploy doc before forming a deploy question, not from memory.

## gh hygiene

If `unsetGithubToken` is `true` (config), run `unset GITHUB_TOKEN` (or `env -u GITHUB_TOKEN`) before every `gh` call — some harnesses inject a token scoped to the wrong org, which surfaces as opaque `Resource not accessible by integration` errors that are easy to misdiagnose as transient. Default is OFF: do **not** strip the token unconditionally. Throughout the commands below, `GH_PREFIX` means `unset GITHUB_TOKEN && ` when `unsetGithubToken` is true, else nothing.

When `issueTracker.cli == "glab"`, translate the `gh` invocations to their `glab` equivalents (`glab mr create/merge/view`, `glab ci status`, `glab release create`). The methodology is identical; only the CLI verbs differ.

## Phase 0 — Pre-flight

Verify the working environment is ready before touching anything publishable:

1. **Default checkout, not a worktree.** `git rev-parse --git-common-dir` should equal `.git` (or end in `.git`); if it returns a path like `<repo>/.git/worktrees/<name>`, the user is in a feature worktree. A release is a repo-wide operation, not a feature-branch one — switch to the main checkout (`cd $(git -C "$(git rev-parse --git-common-dir)/.." rev-parse --show-toplevel)`) or surface and let the user move.
2. **Working tree clean.** `git status --porcelain` returns nothing. Local uncommitted changes are not part of the release — surface, don't auto-stash.
3. **Fetch origin.** `${GH_PREFIX}git fetch origin --prune`.
4. **`<integration>` is ahead of `<default>`.** `git log origin/<default>..origin/<integration> --first-parent --merges --pretty=oneline | wc -l` is non-zero. Zero merges → there's nothing to release; report that and stop. Don't open an empty PR. (When `<integration> == <default>`, instead check `git log $(git describe --tags --abbrev=0 2>/dev/null || echo origin/<default>)..origin/<default>` is non-empty — i.e. there are commits since the last tag.)
5. **No existing open release PR.** `${GH_PREFIX}gh pr list --base <default> --head <integration> --state open --json number,url,headRefOid`. If a PR exists:
   - Verify its `headRefOid` matches `origin/<integration>`. If yes, skip Phases 1–2 and resume at Phase 3 (Wait for CI) or Phase 4 (Merge) depending on CI state — the prior session probably crashed mid-flow.
   - If the existing PR's head is stale (`origin/<integration>` has advanced since the PR was opened), surface to the user. Don't silently force-update — the existing PR may have been opened by another session/operator with intent we can't read.
6. **CI on `origin/<integration>` is green.** `${GH_PREFIX}gh run list --branch <integration> --limit 5 --json conclusion,status,name,databaseId,headSha`. The runs whose `headSha` equals `origin/<integration>` should all be `conclusion: success`. If the latest is `cancelled`, `failure`, or `null` (still pending), surface — you do not want to open a release PR off a tip whose own integration CI didn't pass. Common case: a `ship-issue` flow merged to the integration branch but the post-merge CI hasn't finished or got cancelled mid-run. Either wait for it to settle (re-run cancelled jobs via `gh run rerun --failed`) or hold the release.
7. **Local `<integration>` is in sync with `origin/<integration>`.** Compute `LOCAL=$(git rev-parse <integration> 2>/dev/null)` and `REMOTE=$(git rev-parse origin/<integration>)`. Three outcomes:
   - `LOCAL == REMOTE` → in sync, continue silently.
   - `LOCAL` doesn't resolve (no local `<integration>` branch) → fine, this skill operates on `origin/<integration>` and doesn't require local `<integration>` to exist. Continue.
   - `LOCAL != REMOTE` → surface the divergence with the specifics. Use `git log --oneline --left-right LOCAL...REMOTE | head -20` to show what's on each side. Three sub-cases for the user to decide:
     - **Local ahead** (`git rev-list REMOTE..LOCAL` non-empty, reverse empty): there are unpushed commits on local `<integration>`. Almost always wrong — the integration branch is supposed to be the integration line, all commits get there via PR merges, not local pushes. Surface and ask: are these meant to go out in this release? If yes, the user needs to `git push origin <integration>` first; if not (e.g. accidental local commits), they need to reset local to match origin. Don't auto-resolve either direction — both are destructive in opposite ways.
     - **Local behind** (`git rev-list LOCAL..REMOTE` non-empty, reverse empty): local `<integration>` is stale, easy fix. Run `git checkout <integration> && git merge --ff-only origin/<integration>` to fast-forward; the skill itself doesn't need this (it reads `origin/<integration>`) but the user almost certainly does for any local work afterwards. Offer to do this fast-forward and proceed.
     - **Diverged** (both sides have commits the other doesn't): something went wrong — typically a local commit on `<integration>` that conflicts with what landed via PR. Surface with full divergence and let the user decide; don't auto-rebase or reset.

Any failure: ground via `doc-grounded-questions` (if available), then surface. Don't paper over.

## Phase 1 — Changelog

**Read [`CHANGELOG.md`](./CHANGELOG.md) first** — it sits next to this file and owns the *content* of the PR body (categorisation rubric, output template, examples of good vs bad entries). Don't paraphrase from memory: the rubric and category list have evolved with operator feedback. Your prior about "what a changelog looks like" is probably the flat-merge-list shape this skill explicitly moved away from.

What this skill needs from Phase 1 is just two outputs:

1. **The PR body** — assembled per `CHANGELOG.md`'s template (top synthesis → Highlights → Features → Improvements → Fixes → Deploy notes → Internal → collapsible raw-PR list → Verification). Operator-facing prose, not a flat SHA dump.
2. **The PR title / merge subject seed** — one line, under 70 chars, captured from the top-of-body synthesis. This becomes the `gh pr create --title` value and (with `(<integration> → <default>)` appended) the `gh pr merge --subject` value.

Also during this phase, compute and surface for the user's pre-flight glance:

- Number of first-parent merges in the range (so they can sanity-check the scope).
- **Deploy expectations** (only when `deploy.adapter != none`): whether the configured services will auto-redeploy — match `git diff --name-only origin/<default>..origin/<integration>` against the redeploy watch-patterns documented in the configured deploy doc (`deploy.watchDoc` or `docPaths.deploy`). This feeds the **Deploy notes** section and pre-empts the "I merged but nothing happened" confusion. If `deploy.adapter == none`, skip this analysis entirely.

There is no `CHANGELOG.md` *file* in most repos — that's intentional; the PR body **is** the per-release changelog and the git log of the default branch is the cumulative history. Don't create a tracked `CHANGELOG.md` in the repo root unless the user explicitly asks. The `CHANGELOG.md` referenced above is *this skill's side-file*, not a repo artefact.

## Phase 2 — Open PR

```bash
${GH_PREFIX}gh pr create \
  --base <default> \
  --head <integration> \
  --title "<merge subject — see below>" \
  --body "$(cat <<'EOF'
<the body from Phase 1>
EOF
)"
```

**Title format**: derive from the top-of-body synthesis you wrote in Phase 1. Same shape as the eventual merge subject, *minus* the `(<integration> → <default>)` suffix (the forge adds the `#N` ref under the hood, and the suffix is added back at merge time via `--subject`). Examples of the shape:

- `merge: <integration> — workflow triggers MVP, model library, egress hardening`
- `merge: <integration> — admin-lease-heartbeat: server-side heartbeat + idle timeout`

Pattern: `merge: <integration> — <two or three comma-separated themes>`. Under 70 chars when possible; details belong in the body, not the title. If a user-provided scope-hint argument is present, prefer it as the seed; refine after reading the merges, but keep the user's intent.

Capture the PR number and URL — you'll need them through Phase 5.

## Phase 3 — Wait for CI

Before the first wake-up, verify CI is polling the right tip:

```bash
${GH_PREFIX}gh pr view <pr-num> --json headRefOid
```

It must equal `git rev-parse origin/<integration>` (after a `git fetch`). If it diverged because new commits landed on the integration branch between PR open and now, you have a choice: either let the in-flight PR finish on the older tip (and immediately ship another release after) or update the PR head. The simpler path is the former — releases are atomic units. Surface to the user if you see drift.

Schedule a wake-up every ~180 seconds using your harness's wake/poll primitive (e.g. `ScheduleWakeup`) with `prompt: "/ship-release <pr-num>"` (or whatever the user originally invoked). 180s keeps a typical prompt cache warm (many providers use a ~5 min TTL); 300s is the worst-of-both (cache miss without amortisation). If CI is known to take longer than 10 min for this repo, drop to 240s rather than padding to 300s+. If your harness has no wake primitive, fall back to a manual poll loop and surface progress on each pass.

On each wake-up:

```bash
${GH_PREFIX}gh pr checks <pr-num> --json state,name,conclusion,bucket
```

Decode:
- Any `IN_PROGRESS` / `PENDING` → report one short progress line ("CI: 4/6 green at 8m, waiting on tests"), schedule next wake-up.
- All `SUCCESS` → continue to Phase 4.
- Any `FAILURE` / `CANCELLED` / `TIMED_OUT` → pause. Pull the failing check's logs (`gh run view <run-id> --log-failed`), ground via `doc-grounded-questions` (if available) against the relevant docs (lint → `docPaths.standards`, test → area spec/plan), surface to the user. A CI failure on a release is a real blocker — the right fix usually lands on the integration branch via a follow-up `ship-issue`, then this release flow rebases its PR head onto the new `origin/<integration>` (close + reopen, or push-update; trust whichever path the user chooses).

**Max-wait escalation.** Track the wake-up count. After 10 wake-ups (~30 min) with no terminal state, surface a checkpoint even in `--auto` mode. CI webhooks can fail to fire silently and a PR can sit indefinitely on "expected — Waiting for status to be reported". The escalation prompt: "PR #<n> has been pending for ~30 min with no terminal CI state. {state summary}. Options: (a) wait another 10 min, (b) close+reopen to re-trigger checks, (c) merge admin-only if allowed, (d) abort and investigate." Don't loop forever silently.

## Phase 4 — Merge

```bash
${GH_PREFIX}gh pr merge <pr-num> --merge \
  --subject "merge: <integration> — <scope summary> (<integration> → <default>)"
```

**Do NOT pass `--delete-branch` when `<integration> != <default>`.** The integration branch is permanent. Passing it would delete the integration branch and break every in-flight `ship-issue` worktree. (When `<integration> == <default>`, this whole PR/merge phase doesn't apply — there's nothing to delete.)

**Do NOT pass `--no-ff`.** Recent `gh` (≥ 2.83) rejects it (`unknown flag: --no-ff`). `--merge` alone already creates a true merge commit. This is a real footgun — see `ship-issue` SKILL.md (if available) for the same note.

The `--subject` override is mandatory when the forge default doesn't match the repo convention — `gh`'s default ("Merge pull request #N from owner/<integration>") usually doesn't. The subject should mirror the PR title, with `(<integration> → <default>)` appended. If `commit.coAuthoredBy` is `true` (the default), the merge commit may carry a `Co-Authored-By` trailer per the project convention; if `false`, do not add one. (The merge commit is the forge's, not yours, so this rarely comes up here.)

Verify the merge:

```bash
${GH_PREFIX}gh pr view <pr-num> --json state,mergeCommit
```

`state == MERGED` plus non-null `mergeCommit.oid` means it landed. Capture `mergeCommit.oid` as `MERGE_SHA` for Phase 5.

Update local default branch to reflect the merged state (optional but kind to the next session):

```bash
${GH_PREFIX}git fetch origin
```

Don't `git push origin <default>` or `git checkout <default> && git merge` — the remote is the source of truth and local-default divergence has bitten parallel sessions before.

## Phase 4.5 — Tag + GitHub Release

Every release gets a semver tag and a GitHub Release. The tag is the stable named anchor an operator can reference ("we shipped v1.4.0 last Tuesday"); the Release is the discoverable artefact in the repo's Releases tab with the full PR body as notes. No flag, no opt-out — if Phase 4 succeeds (or, in the single-branch / `kind=none` case, the working tree is at the tip you intend to release), Phase 4.5 runs. (When `issueTracker.kind == "none"`, skip the GitHub-Release sub-step 4.5d/4.5e and just create the local annotated tag; report it.)

The version-bump decision is grounded in the categorisation [`CHANGELOG.md`](./CHANGELOG.md) already produced. Don't second-guess it here — the rubric there is the source of truth for what counts as a feature vs a fix vs a breaking change. Read [`CHANGELOG.md`'s "Version bump signals"](./CHANGELOG.md#version-bump-signals) section before computing the bump.

### 4.5a. Find the previous release tag

```bash
PREV_TAG=$(git tag --list 'v[0-9]*' --sort=-v:refname | head -1)
```

Three cases:

- **`PREV_TAG` is non-empty** (e.g. `v1.3.2`): regular case. Compute the next version by bumping MAJOR / MINOR / PATCH per Step 4.5b.
- **No `v*` tags exist** (bootstrap): this is the *first* release using this skill. Surface to the user with a doc-grounded prompt: "No prior semver tag found. Proposing **v0.1.0** as the bootstrap version (pre-1.0; future MAJOR-bump decision deferred until the platform is declared 1.0-stable). Override?" Default to `v0.1.0` if the user confirms. Do not silently jump to `v1.0.0` — the `0.x → 1.0` decision is a product/maturity statement, not a mechanical one.
- **Tags exist but none look like semver** (only checkpoint tags like `phase-a-foo`): treat as bootstrap. Surface the existing tags so the user knows what's there, then proceed as the bootstrap case.

### 4.5b. Decide MAJOR / MINOR / PATCH

Read the PR body you assembled in Phase 1 and apply this decision tree, in order:

1. **MAJOR** — at least one entry in `## Deploy notes` requires *operator action to upgrade* and is *not backward-compatible*. Concretely: an env var added that the app refuses to start without; a schema migration that drops a column or table not yet shimmed by client code; an endpoint shape or auth requirement change without a compat path; an ADR explicitly flagged as breaking.
2. **MINOR** — at least one entry in `## Highlights` or `## Features` (a new operator-visible capability that didn't exist before).
3. **PATCH** — only `## Improvements`, `## Fixes`, `## Internal`, or non-breaking `## Deploy notes` (additive env vars with defaults, additive migrations, telemetry-only changes).

**Pre-1.0 caveat (`0.x.y`):** while `PREV_TAG` is on `0.x.y`, what would be MAJOR on a 1.0+ release is a MINOR bump (`0.MINOR.0` becomes `0.MINOR+1.0`), and MINOR/PATCH map to MINOR/PATCH on the `0.x` track. This is the [semver convention for unstable releases](https://semver.org/#spec-item-4) — explicit operator pre-commitment to API-stability arrives at 1.0.

Surface the proposed bump *with reasoning* before tagging:

```
Proposed next version: v1.4.0  (from v1.3.2, MINOR bump)

Reasoning:
- 2 entries in ## Features → MINOR bump triggered
- 0 entries in ## Deploy notes flagged as breaking → not MAJOR
- Operator action needed: review the new `Scheduler:DefaultTimezone` env var added in #168 (additive, has default — not MAJOR-class)

Override the bump? (M/m/p — uppercase for major, lowercase for minor/patch; or type a literal version like 'v2.0.0')
```

If the user confirms or doesn't respond after a single round, proceed with the proposed bump. In `--auto` (if invoked from a chained flow), proceed without prompting — the categorisation is deterministic and the operator can always re-tag if wrong.

### 4.5c. Tag the merge commit

```bash
NEXT_VERSION=v1.4.0   # from Step 4.5b
MERGE_SHA=$(${GH_PREFIX}gh pr view <pr-num> --json mergeCommit -q .mergeCommit.oid)
# single-branch / kind=none case: MERGE_SHA=$(git rev-parse origin/<default>)

git tag -a "$NEXT_VERSION" "$MERGE_SHA" -m "release: $NEXT_VERSION — <one-line scope from PR title>"
${GH_PREFIX}git push origin "$NEXT_VERSION"
```

Use `git tag -a` (annotated, not lightweight) — annotated tags carry the message, author, and date and are what `git describe` and `gh release` expect. The tag *message* should be a one-line scope matching the PR title; the full release notes go in the GitHub Release, not the tag.

The tag points at `MERGE_SHA` explicitly, not implicit `HEAD`. Phase 4 left local checkout state alone (we don't `git checkout <default>`), so implicit HEAD is whatever branch the user was on — which is wrong. Always pass the SHA.

### 4.5d. Create the GitHub Release

```bash
PR_BODY=$(${GH_PREFIX}gh pr view <pr-num> --json body -q .body)
echo "$PR_BODY" > /tmp/release-notes-$NEXT_VERSION.md

${GH_PREFIX}gh release create "$NEXT_VERSION" \
  --target <default> \
  --title "$NEXT_VERSION — <one-line scope from PR title>" \
  --notes-file /tmp/release-notes-$NEXT_VERSION.md

rm /tmp/release-notes-$NEXT_VERSION.md
```

Use `--notes-file`, not inline `--notes` — the PR body has heredoc-unfriendly content (code fences, backticks, quoted JSON examples) and shells mangle it. Write to a temp file then delete after. (In the single-branch case where there's no PR, write the changelog body assembled in Phase 1 directly to the file.)

`--target <default>` is explicit-and-safe: the tag already points at `MERGE_SHA` which is on the default branch, so this is redundant in the happy path, but it makes the intent unambiguous and protects against a future flow where this step might run from a different branch.

Don't pass `--prerelease` for normal releases — the bootstrap `v0.x.y` releases are pre-1.0 by the semver spec, but they're not *prereleases* in GitHub's UI sense (which means alpha/beta/rc). Drop `--prerelease` flag entirely; reserve it for explicit rc/beta tags if you ever cut them.

Don't pass `--draft` — this skill is for shipping, not staging. If you want a draft, you're in the wrong workflow.

### 4.5e. Verify the release landed

```bash
${GH_PREFIX}gh release view "$NEXT_VERSION" --json url,tagName,createdAt,isLatest -q .
```

Two checks:
- `tagName == "$NEXT_VERSION"` confirms the tag was found.
- `isLatest == true` confirms GitHub flagged this as the latest release (so it appears in the repo's release notification feed and in `gh release view --web`).

Capture `.url` for the Phase 6 report.

If `gh release create` fails: most common cause is the tag-push from 4.5c was rejected (write protection on the remote) or the GH token lacks `contents: write`. Surface with the actual error; don't silently proceed to Phase 5. A failed Release-create after a successful merge is recoverable (re-tag locally and re-run `gh release create`), but only if the user knows it happened.

### 4.5f. Skip conditions

The only legitimate skip is: **the user has already manually tagged + released this merge commit before re-running the skill** (rare, but happens during recovery). Detect via:

```bash
EXISTING=$(${GH_PREFIX}gh release list --limit 5 --json tagName,targetCommitish -q \
  ".[] | select(.targetCommitish == \"$MERGE_SHA\") | .tagName")
```

If non-empty, surface: "Release `$EXISTING` already exists for merge $MERGE_SHA. Skip tag + create?" Default: skip. Don't double-tag.

## Phase 5 — Watch deploy

**Skip this entire phase when `deploy.adapter == none`** (the default). In that case there is no deploy to watch — Phase 4.5 already tagged and published; go straight to Phase 6 and report "merged + tagged; no deploy adapter configured". Do not invent a deploy step the project doesn't have.

When `deploy.adapter != none`, this phase enforces the load-bearing invariant of the whole skill:

> **Verify the production service is actually running the merge SHA at a SUCCESS status. A health-200 is never proof.** A platform can report a deploy `FAILED` and silently keep serving an older build; a health probe against that older build still returns 200. Match the *running commit* to `MERGE_SHA` *and* require a terminal SUCCESS status before declaring the release live.

Capture inputs:

```bash
MERGE_SHA=$(${GH_PREFIX}gh pr view <pr-num> --json mergeCommit -q .mergeCommit.oid)
```

Read `deploy.watchDoc` (or `docPaths.deploy`) for the platform-specific commands and gotchas before polling — the adapter below is the generic shape; the doc has the project's specifics.

### 5a. Enumerate services

Enumerate the services dynamically rather than hardcoding — future services should be picked up without a skill edit. Start from `deploy.services` (config) as the expected set, but cross-check against what the platform actually reports so a newly-added service isn't missed.

### 5b. Determine which services to watch

For each service, decide whether the release SHOULD have triggered a deploy:

- If Phase 1's deploy-expectations analysis flagged a service as "no watch-pattern match" → skip it from active polling; just verify in the final report that its latest deployment is unchanged and *was successful* (a stale FAILED deploy on an unchanged service is still a production fire — surface it).
- Otherwise, watch.

If you didn't run the watch-pattern analysis in Phase 1, watch *all* services and rely on the timeout logic below.

### 5c. Poll each watched service

Poll with your harness's wake/poll primitive at ~180s cadence. The **wait conditions** are platform-agnostic:

**Success:**
- The running deployment's commit *starts with* `MERGE_SHA` (platforms sometimes store the short SHA, so prefer `startswith` / substring match — never strict `==` on length).
- Its source branch is `<default>`.
- Its status is the platform's terminal-success value (e.g. `SUCCESS`).

**Intermediate:**
- A deployment with the merge SHA exists but its status is a build/deploy-in-progress value (`BUILDING` / `DEPLOYING` / `INITIALIZING` / `QUEUED`) → log one progress line, schedule next wake-up.
- The latest deployment is older than the merge commit → the platform hasn't picked up the push yet. This usually clears within ~60s of merge but can take several minutes on a cold service. Wait through at least 3 cycles before treating as "no redeploy will happen".

**Failure paths — pause, ground via the deploy doc, surface:**

- **Silent rollback** (the case the entire skill exists for). A deployment for `MERGE_SHA` exists with status `FAILED`, AND the currently-serving deployment is now an older `SUCCESS` build. The running service can execute code from days ago against a freshly-migrated schema, producing confusing errors like `relation "X" does not exist`. Pull build logs and surface. A health-200 here is the trap — it's the *old* build answering.
- **No redeploy after ~10 min.** No deployment with `MERGE_SHA` appears, even though Phase 1 said one should. Possible causes: watch-pattern analysis was wrong; the platform webhook from the forge didn't fire; build queue backed up. Verify via `${GH_PREFIX}gh api repos/<repoSlug>/commits/$MERGE_SHA/check-runs` (does the platform report a check-run?), then either force a deploy (a "modify shared infra" action — **confirm with the user first**) or surface.
- **Stale FAILED notification.** A platform dashboard can show a `FAILED` deploy prominently *even after* a newer `SUCCESS` has landed. Before treating any FAILED status as the silent-rollback case, check the chronology of the last few deployments. If the latest is `SUCCESS` and its commit matches `MERGE_SHA`, the notification is stale — don't surface it as a failure.

### 5d. Railway adapter (`deploy.adapter == "railway"`)

Concrete commands for the bundled Railway adapter. `deploy.project`, `deploy.env`, and `deploy.services` come from config.

```bash
# 5a — enumerate services
railway status --json | jq -r '.environments[].services[].node.serviceName' | sort -u

# 5c — poll one service
railway deployment list --service <name> --json \
  | jq '.[0] | {id, status, commit: .meta.commitHash, branch: .meta.branch, at: .createdAt}'
# success: .meta.commitHash startswith MERGE_SHA, .meta.branch == "<default>", .status == "SUCCESS"

# silent-rollback / stale-FAILED chronology check
railway deployment list --service <name> --json \
  | jq '.[0:5] | .[] | {id, status, at: .createdAt, commit: .meta.commitHash[0:8]}'

# build logs on failure
railway logs --service <name> --deployment <id> --build

# force a redeploy (modify-shared-infra — confirm with user first)
railway up --service <name> --detach
```

For any other `deploy.adapter` value, follow the same generic 5a–5c shape and read `deploy.watchDoc` for the platform's equivalent commands; if the adapter is unrecognised and no `watchDoc` is set, surface that and skip active polling rather than guessing platform verbs.

### 5e. Wakeup prompt

Use your harness's wake/poll primitive with `prompt: "/ship-release <pr-num>"` (or whatever invocation the user used). Don't reuse a longer prompt — re-entering the skill at the top replays Phases 0–4 idempotently and just wastes the prompt cache. The wake-up handler should detect "PR is merged, services are still pending" and jump straight to Phase 5 polling.

## Phase 6 — Report

When all watched services are on `MERGE_SHA` with a terminal SUCCESS status (or the user has acked any anomaly, or `deploy.adapter == none`), emit a final report:

```
release: <NEXT_VERSION> — <PR title>

Version: <NEXT_VERSION>  (previous: <PREV_TAG or "bootstrap">, bump: <MAJOR|MINOR|PATCH>)
Release: <gh release URL>
PR:      <PR URL>
Merge:   <MERGE_SHA>

Deploy (adapter: <adapter>, env: <env>):
  <service> → <deployment-id>  SUCCESS  commit <short SHA>  at <ISO timestamp>
  <others as applicable>
  -- or, when deploy.adapter == none --
  no deploy adapter configured — merged + tagged only

Next: monitor the service health probe and the platform dashboards for the next ~15 min for anything weird.
```

The "monitor for ~15 min" line is not a separate phase — it's just a reminder. Don't keep polling after the report unless the user asks.

## Notes

- **`Co-Authored-By` trailer follows `commit.coAuthoredBy`** (default: include). This rarely comes up since the only commit this skill produces is the merge commit (which is the forge's, not yours) and the annotated tag. If the project sets `commit.coAuthoredBy: false`, omit the trailer; otherwise include it per the project convention.
- **Semver tags are mandatory** (Phase 4.5). Every release produces a `vMAJOR.MINOR.PATCH` tag on the merge commit plus a GitHub Release (or just a local tag when `issueTracker.kind == "none"`). The bump is computed from the categorised PR body per `CHANGELOG.md`'s "Version bump signals" rubric; the user can override per-release but cannot opt out of tagging. Bootstrap (first release with this skill, no prior `v*` tag): default to `v0.1.0` and treat the 0.x→1.0 promotion as a separate operator decision.
- **Standing release-publishing authorization.** When the user invokes this skill, that authorises `git tag -a`, `git push origin v*`, and `gh release create`. Don't re-prompt at each step. The user does see and confirm the *proposed bump* in Phase 4.5b — that's the one round, not many.
- **No `CHANGELOG.md` file** in the repo unless the user explicitly asks. The merge commit subject + PR body + GitHub Release page *are* the per-release changelog; the cumulative changelog is the Releases tab itself. The `CHANGELOG.md` referenced in Phase 1 is *this skill's side-file*, not a repo artefact.
- **Local integration-branch divergence** is surfaced in Phase 0 (step 7) but only blocks if it's a real ahead/diverged case. The skill itself reads `origin/<integration>` for the release; local `<integration>` matters because the user almost always wants to fast-forward it for follow-up work.
- **Standing local-commit authorization** (where the project has one) covers any prep commits you might land on the integration branch mid-flow. It does NOT cover pushing to `<default>`, `<integration>`, or any version tag (those are explicit Phase 4 / 4.5 operations under the standing release-publishing authorization above).
- **If a Phase reveals an earlier Phase was wrong** (e.g. Phase 5 surfaces that the merge included a broken migration → the platform rolled back → the right fix is a hotfix `ship-issue` on the integration branch, *then* a new release with a PATCH bump), back up. Don't paper over by force-redeploying old code. The tag from the failed release stays — it's a permanent record that v1.4.0 was attempted and rolled back; v1.4.1 supersedes it. Don't delete tags.
- **If `release` is invoked standalone** (no argument): infer scope by reading the merges in Phase 1; the synthesised summary IS the scope hint. If the user gave a hint as an argument, use it as the seed and refine after reading.
