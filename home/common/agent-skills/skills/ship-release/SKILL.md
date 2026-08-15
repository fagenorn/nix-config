---
name: ship-release
description: Release the integration branch to the default branch — changelog, release PR, CI, merge, semver tag + GitHub Release, deploy watch. Use for "release", "ship to prod", "deploy".
argument-hint: "[scope hint — optional one-line summary phrase to seed the merge subject]"
---

# Ship Release

Counterpart to `ship-issue`: where that lands one feature on the integration branch, this lands the accumulated integration branch on the default branch, tags + publishes a GitHub Release, and (when a deploy adapter is configured) watches the platform pick it up. The unit of work is **all merges on the integration branch since the last default-branch merge**, not a single issue.

## Ownership

When a controller delegates the release, it must launch one owner for the entire
existing phase sequence with this explicit selection:

<!-- agent-dispatch: id=ship-release-owner role=ship-owner model=opus effort=high -->
Agent(subagent_type="general-purpose", model="opus", effort="high") owns the release through final reporting.

A direct interactive invocation keeps the current session as owner. Do not split
release ownership across cheaper transport or mechanic agents.

## Project bindings (resolve first)

Read `.claude/skills.config.json` at the project root. Auto-detect absent keys: tracker = `gh` for a github.com remote (else `glab`/none); branches from the repo default. Remaining defaults: `integrationBranch=main`, `defaultBranch=main`, `commit.coAuthoredBy=true`, `unsetGithubToken=false`, `deploy.adapter=none`. Degrade gracefully — never read a configured doc/hints path that doesn't exist, never hard-fail on a missing optional binding.

`<integration>` means the resolved `integrationBranch`, `<default>` the resolved `defaultBranch`. When they're identical (the common single-branch repo) there is no PR to open: run Phases 0 **and** 1 — the pre-flight and the changelog body / bump evidence are still required — then skip Phases 2–4 and continue at Phase 4.5. The release ref is the confirmed tip of `<default>`. The two-branch flow below is the general case.

Derive `repoSlug` once from `git remote get-url origin` when config doesn't set it (strip the `git@github.com:` / `https://github.com/` prefix and trailing `.git`), and reuse it for every PR/commit/release URL. **Never hardcode an owner/name.**

When `issueTracker.kind == "none"` there is no forge: run Phases 0–1, then replace Phases 2–4 with a local true merge (`git checkout <default> && git merge --no-ff <integration>`), tag the **local merge result** — `git rev-parse <default>` *after* the merge, never `origin/<default>`, which is still the stale pre-merge tip — skip the PR / CI-wait / GitHub-Release steps, and report the merge SHA + tag.

## Durable release state

A release must survive a crash between any two phases — after Phase 4 the merge exists whether or not this session lives to tag it. Keep a skill-owned state file at `.superpowers/workflows/ship-release/state.json` (ensure `.superpowers/workflows/.gitignore` exists and contains `*`; create both if missing):

```json
{"headSha": "<origin/<integration> tip being released>", "pr": null, "prUrl": null,
 "mergeSha": null, "tag": null, "releaseUrl": null, "deployState": "pending"}
```

Write it atomically (temp file in the same dir, then `mv`) at every transition: Phase 0 (`headSha`), Phase 2 (`pr`, `prUrl`), Phase 4 or the local merge (`mergeSha`), Phase 4.5 (`tag`, then `releaseUrl`), Phase 5 (`deployState`: `watching` → `done`; `none` when no adapter). Phase 0 reads it **first** and re-enters at the first null field. Phase 6 deletes it after the report — a present file always means an unfinished release.

## The flow

```
0. Pre-flight    → resume check (durable state, then latest MERGED base→head PR), default checkout
                   (not a worktree), tree clean, <integration> ahead of <default>, no open release PR,
                   <integration> CI green, local/origin <integration> in sync
1. Changelog     → mine merges since last release; assemble the categorised PR body per CHANGELOG.md
2. Open PR       → nothing to push; gh pr create --base <default> --head <integration>
3. Wait for CI   → one blocking gh pr checks --watch call (no wakeup loop, no improvised polling)
4. Merge         → gh pr merge --merge (NO --delete-branch — the integration branch is permanent)
4.5. Tag+Release → resolve MERGE_SHA, skip-check for an existing release, THEN semver bump from the
                   CHANGELOG.md categories; tag the merge commit; gh release create
5. Watch deploy  → only when deploy.adapter != none: poll per service until the running commit is the
                   merge SHA at a terminal SUCCESS status
6. Report        → PR URL, merge SHA, version tag + release URL, per-service deployment IDs + statuses
```

## Standing authorization

"Release" / "ship to prod" / "do the release" authorises the whole chain: opening the PR, waiting for CI, merging with `--merge`, tagging + publishing the Release, and polling the platform until each affected service is on the merge SHA. Don't re-prompt at each step. Pause only on:

- Pre-flight failures (Phase 0).
- A CI check finishing `FAILURE` / `CANCELLED` / `TIMED_OUT` (Phase 3).
- A deployment finishing `FAILED` (Phase 5) — *especially* the silent-rollback case.
- Genuinely new risks not covered above.

## Doc-grounded escalations

Before forming any user-facing question, invoke `doc-grounded-questions` (if unavailable, read the configured doc directly when it exists). Deploy/platform questions → `docPaths.deploy` and `deploy.watchDoc`; git ops → `docPaths.gitWorktrees`; the bar → `docPaths.standards`. The silent-rollback gotcha, the latest-deployment-commit vs actually-built-commit distinction, and the stale-`FAILED` trap are platform specifics — read the configured deploy doc rather than answering from memory.

## gh hygiene

`GH_PREFIX` below means `unset GITHUB_TOKEN && ` when `unsetGithubToken` is true, else nothing — some harnesses inject a token scoped to the wrong org, which surfaces as an opaque `Resource not accessible by integration` that reads like a transient error. Default is OFF; do not strip the token unconditionally. When `issueTracker.cli == "glab"`, translate to `glab mr create/merge/view`, `glab ci status`, `glab release create` — the methodology is identical, only the verbs differ.

## Phase 0 — Pre-flight

0. **Resume check — before any "nothing to release" verdict.** `git fetch origin --prune --tags`, then:
   - **Durable state.** Read `.superpowers/workflows/ship-release/state.json` if present. `mergeSha` set but no `tag` → set `MERGE_SHA` from it and jump to Phase 4.5. `tag` set but no `releaseUrl` (forge case) → resume at 4.5f. Released but `deployState` not terminal and `deploy.adapter != none` → jump to Phase 5. A record whose `headSha` matches neither `origin/<integration>` nor a resumable `mergeSha` is stale → surface it, then continue fresh.
   - **Merged-PR lookup.** No usable state: `${GH_PREFIX}gh pr list --base <default> --head <integration> --state merged --limit 1 --json number,url,mergeCommit,mergedAt`. If the newest merged release PR's `mergeCommit.oid` carries no `v*` tag (`git tag --points-at <oid> 'v[0-9]*'` empty) and its head was the current `origin/<integration>` tip, a prior session crashed after Phase 4: set `MERGE_SHA=<oid>` and resume at Phase 4.5. (kind == none: the same check is `git tag --points-at $(git rev-parse <default>) 'v[0-9]*'` on the local merge result.)

   This step is first because a merged-but-untagged release makes step 3 read "zero merges → nothing to release", silently losing the tag + Release. When neither resume path applies, record `headSha` in a fresh state file and continue.
1. **Default checkout, not a worktree.** `git rev-parse --git-common-dir` should be `.git` (or end in `.git`); a path like `<repo>/.git/worktrees/<name>` means the user is in a feature worktree. A release is repo-wide — switch to the main checkout (`cd $(git -C "$(git rev-parse --git-common-dir)/.." rev-parse --show-toplevel)`) or surface.
2. **Working tree clean.** `git status --porcelain` empty. Uncommitted changes are not part of the release — surface, don't auto-stash.
3. **`<integration>` is ahead of `<default>`.** `git log origin/<default>..origin/<integration> --first-parent --merges --pretty=oneline | wc -l` non-zero. Zero → nothing to release; report and stop, don't open an empty PR. (Single-branch case: `PREV=$(git describe --tags --abbrev=0 origin/<default> 2>/dev/null)` — note the explicit ref; bare `git describe` reads whatever HEAD the user parked on — then check `git log ${PREV:+$PREV..}origin/<default> --oneline` is non-empty.)
4. **No existing open release PR.** `${GH_PREFIX}gh pr list --base <default> --head <integration> --state open --json number,url,headRefOid`. If one exists and its `headRefOid` matches `origin/<integration>`, a prior session crashed mid-flow — skip Phases 1–2 and resume at Phase 3 or 4 depending on CI state. If its head is stale, surface; don't silently force-update a PR another session/operator opened.
5. **CI on `origin/<integration>` is green.** `${GH_PREFIX}gh run list --branch <integration> --limit 5 --json conclusion,status,name,databaseId,headSha`; every run whose `headSha` equals `origin/<integration>` should be `conclusion: success`. Anything `cancelled`, `failure`, or still pending → surface. Common cause: a `ship-issue` merge whose post-merge CI hasn't settled or got cancelled. Either wait it out (`gh run rerun --failed`) or hold the release — don't cut from a tip whose own CI didn't pass.
6. **Local `<integration>` in sync with origin.** Compare `git rev-parse <integration>` against `git rev-parse origin/<integration>`:
   - Equal, or no local branch at all → continue (this skill reads `origin/<integration>`).
   - **Local ahead** → unpushed commits on the integration line. Almost always wrong: commits get there via PR merges. Surface with `git log --oneline --left-right LOCAL...REMOTE | head -20` and ask whether they belong in this release. Don't auto-resolve — push and reset are destructive in opposite directions.
   - **Local behind** → stale local branch. Offer `git checkout <integration> && git merge --ff-only origin/<integration>` and proceed; the skill doesn't need it but the user will for follow-up work.
   - **Diverged** → surface the full divergence and let the user decide. Don't auto-rebase or reset.

Any failure: ground, then surface. Don't paper over.

## Phase 1 — Changelog

**Read [`CHANGELOG.md`](./CHANGELOG.md) first** — it sits next to this file and owns the *content* of the PR body: the categorisation rubric, the output template, the version-bump signals. Don't paraphrase from memory; your prior about "what a changelog looks like" is probably the flat merge-list shape this skill moved away from.

Two outputs are required from this phase:

1. **The PR body** — assembled per `CHANGELOG.md`'s template (top synthesis → Highlights → Features → Improvements → Fixes → Deploy notes → Internal → collapsible raw-PR list → Verification). Operator-facing prose, not a SHA dump.
2. **The PR title / merge-subject seed** — one line under 70 chars from the top-of-body synthesis. It becomes `gh pr create --title` and, with `(<integration> → <default>)` appended, `gh pr merge --subject`.

Also surface for the user's glance: the number of first-parent merges in the range (so they can sanity-check scope), and — only when `deploy.adapter != none` — the **deploy expectations**: match `git diff --name-only origin/<default>..origin/<integration>` against the redeploy watch-patterns in `deploy.watchDoc` / `docPaths.deploy` to say which services will actually redeploy. That feeds the **Deploy notes** section and pre-empts "I merged but nothing happened".

Don't create a tracked `CHANGELOG.md` in the repo root unless the user explicitly asks — the PR body *is* the per-release changelog, and the Releases tab is the cumulative one. The `CHANGELOG.md` above is this skill's side-file, not a repo artefact.

## Phase 2 — Open PR

```bash
${GH_PREFIX}gh pr create \
  --base <default> \
  --head <integration> \
  --title "<merge subject seed from Phase 1>" \
  --body "$(cat <<'EOF'
<the body from Phase 1>
EOF
)"
```

Title pattern: `merge: <integration> — <two or three comma-separated themes>`, under 70 chars, same shape as the eventual merge subject *minus* the `(<integration> → <default>)` suffix (added back at merge time via `--subject`). A user-supplied scope-hint argument seeds it — refine after reading the merges, but keep the user's intent.

Capture the PR number and URL; you need them through Phase 5. Persist `pr` + `prUrl` to the durable state file now.

## Phase 3 — Wait for CI

First verify CI is watching the right tip:

```bash
${GH_PREFIX}gh pr view <pr-num> --json headRefOid
```

It must equal `git rev-parse origin/<integration>` after a fetch. Drift means new commits landed on the integration branch since the PR opened. Prefer letting the in-flight PR finish on the older tip and shipping another release right after — releases are atomic units — but surface the drift either way.

Then block on CI with one Bash call, **300s timeout**, foreground:

```bash
${GH_PREFIX}timeout 300 gh pr checks <pr-num> --watch --fail-fast --interval 30
```

The 5-minute ceiling forces an assistant turn every ~5 min, which keeps a subagent stream alive; a harness reaps an agent that goes silent for ~9+ min on a blocking Bash. **Do not background it** (`run_in_background`, `Monitor`) — the harness yields indefinitely on a long-running monitored background Bash and never wakes to issue the next turn. Blocking foreground is correct: `gh` polls at the network layer every ~30s, costing zero model turns until it returns.

**No improvised polling.** Never run `gh pr checks` without `--watch` more than once per phase, never loop `gh run view`/`tail`, never emit `true`/`:`/`date` no-op turns to pass time. Each such poll is a full model turn that re-reads the entire session prefix.

Exit codes:

- **`0`** → all checks pass; continue to Phase 4.
- **`124`** → still running. Emit one short narration turn (`CI: still pending at 5m, retry 2/8`) as the keep-alive, then re-run the identical command, up to **8 times (~40 min)**. Still pending after that → escalate: webhooks can fail to fire silently, leaving a PR on "expected — Waiting for status to be reported" forever. Prompt: "PR #<n> has been pending ~40 min with no terminal CI state. Options: (a) wait another 10 min, (b) close+reopen to re-trigger checks, (c) merge admin-only if allowed, (d) abort and investigate."
- **any other non-zero** → a check failed. Pull `gh run view <run-id> --log-failed`, ground (lint → `docPaths.standards`, test → area spec/plan), surface. A CI failure on a release is a real blocker — the fix usually lands on the integration branch via a follow-up `ship-issue`, after which this release rebases its PR head onto the new `origin/<integration>` (close+reopen or push-update; trust whichever the user picks).

## Phase 4 — Merge

```bash
${GH_PREFIX}gh pr merge <pr-num> --merge \
  --subject "merge: <integration> — <scope summary> (<integration> → <default>)"
```

**Do NOT pass `--delete-branch` when `<integration> != <default>`.** The integration branch is permanent; deleting it breaks every in-flight `ship-issue` worktree.

**Do NOT pass `--no-ff`.** Recent `gh` (≥ 2.83) rejects it (`unknown flag: --no-ff`); `--merge` alone already creates a true merge commit. Same footgun as `ship-issue`.

`--subject` is mandatory whenever the forge default ("Merge pull request #N from owner/<integration>") doesn't match the repo convention. Mirror the PR title with `(<integration> → <default>)` appended.

Verify: `${GH_PREFIX}gh pr view <pr-num> --json state,mergeCommit` → `MERGED` plus a non-null `mergeCommit.oid`. Capture that oid as `MERGE_SHA` and persist `mergeSha` to the durable state file **before doing anything else** — a crash here otherwise strands a merged, untagged release.

Then `git fetch origin` to refresh local refs. Don't `git push origin <default>` or `git checkout <default> && git merge` — the remote is the source of truth, and local-default divergence has bitten parallel sessions.

## Phase 4.5 — Tag + GitHub Release

Every release gets a semver tag and a GitHub Release. No flag, no opt-out: the tag is the stable anchor an operator references ("we shipped v1.4.0 last Tuesday"), the Release is the discoverable artefact with the PR body as notes. (When `issueTracker.kind == "none"`, create the local annotated tag only and skip 4.5f–4.5g.)

The bump is grounded in the categorisation `CHANGELOG.md` already produced — the semver rubric lives **only** in [its "Version bump signals"](./CHANGELOG.md#version-bump-signals); read it before computing, don't re-derive it here, and don't re-litigate the categorisation.

### 4.5a. Resolve the merge SHA

```bash
MERGE_SHA=$(${GH_PREFIX}gh pr view <pr-num> --json mergeCommit -q .mergeCommit.oid)
# no-PR paths (single-branch and/or kind == none), AFTER any local merge:
MERGE_SHA=$(git rev-parse <default>)
```

On the no-PR paths the target is the **local** `<default>` — `origin/<default>` is the stale pre-merge tip whenever Phase 2–4 was a local merge that nothing pushed, and tagging it silently releases the wrong commit.

### 4.5b. Skip condition — before creating anything

The only legitimate skip: this merge commit was already tagged + released (a prior crashed session, or a manual recovery). Check **before** 4.5e/4.5f so a re-entry can't double-tag:

```bash
EXISTING=$(${GH_PREFIX}gh release list --limit 5 --json tagName,targetCommitish -q \
  ".[] | select(.targetCommitish == \"$MERGE_SHA\") | .tagName")
# kind == none (no forge): EXISTING=$(git tag --points-at "$MERGE_SHA" 'v[0-9]*')
```

Non-empty → ask "Release `$EXISTING` already exists for merge $MERGE_SHA. Skip tag + create?" Default: skip — record `tag`/`releaseUrl` in the state file and go to Phase 5. Don't double-tag. A tag that exists without its Release → resume at 4.5f only.

### 4.5c. Find the previous release tag

```bash
PREV_TAG=$(git tag --list 'v[0-9]*' --merged "$MERGE_SHA" --sort=-v:refname | head -1)
```

`--merged "$MERGE_SHA"` restricts the search to tags reachable from the commit being released — a repo-wide `--sort` happily returns a higher tag from an unmerged experiment branch, which yields a wrong `PREV_TAG` and a wrong next version. Non-empty → regular case, bump per 4.5d. No `v*` tags (or only non-semver checkpoint tags) → bootstrap: surface the existing tags and propose **v0.1.0** ("pre-1.0; the MAJOR-bump decision is deferred until the platform is declared 1.0-stable. Override?"). Never silently jump to `v1.0.0` — 0.x → 1.0 is a product statement, not a mechanical one.

### 4.5d. Decide MAJOR / MINOR / PATCH

Apply the "Version bump signals" table in `CHANGELOG.md` (including its pre-1.0 caveat and ambiguity calls) to the buckets Phase 1 produced, top-down, stopping at the first match.

Surface the proposal *with its evidence*, not just the verdict:

```
Proposed next version: v1.4.0  (from v1.3.2, MINOR bump)

Evidence:
- ## Features has 2 entries → MINOR triggered
- ## Deploy notes has 1 entry, additive with a default → not MAJOR
- No breaking ADRs or schema drops in the range

Override? (M/m/p — uppercase for major, lowercase for minor/patch; or a literal version like 'v2.0.0')
```

One round only: if the user confirms or doesn't respond, proceed. In `--auto`, proceed without prompting — the categorisation is deterministic and a wrong tag is one re-tag away.

### 4.5e. Tag the merge commit

```bash
NEXT_VERSION=v1.4.0   # from 4.5d

git tag -a "$NEXT_VERSION" "$MERGE_SHA" -m "release: $NEXT_VERSION — <one-line scope from PR title>"
${GH_PREFIX}git push origin "$NEXT_VERSION"   # skip the push when kind == none
```

Annotated (`-a`), not lightweight — `git describe` and `gh release` expect the message/author/date. Pass `MERGE_SHA` explicitly rather than relying on `HEAD`: Phase 4 deliberately left the local checkout alone, so `HEAD` is whatever branch the user was on. Persist `tag` to the state file as soon as `git tag` succeeds.

### 4.5f. Create the GitHub Release

```bash
PR_BODY=$(${GH_PREFIX}gh pr view <pr-num> --json body -q .body)
echo "$PR_BODY" > /tmp/release-notes-$NEXT_VERSION.md

${GH_PREFIX}gh release create "$NEXT_VERSION" \
  --target <default> \
  --title "$NEXT_VERSION — <one-line scope from PR title>" \
  --notes-file /tmp/release-notes-$NEXT_VERSION.md

rm /tmp/release-notes-$NEXT_VERSION.md
```

`--notes-file`, never inline `--notes`: the body carries code fences, backticks, and quoted JSON that shells mangle. (In the single-branch case with no PR, write the Phase 1 body straight to the file.) Skip `--prerelease` — `v0.x.y` is pre-1.0 by the spec but not a GitHub prerelease (alpha/beta/rc). Skip `--draft` — this skill ships.

### 4.5g. Verify

```bash
${GH_PREFIX}gh release view "$NEXT_VERSION" --json url,tagName,createdAt,isLatest -q .
```

`tagName == "$NEXT_VERSION"` and `isLatest == true`. Capture `.url` for Phase 6 and persist `releaseUrl` to the state file.

If `gh release create` fails, the usual causes are a rejected tag push (branch/tag protection) or a token without `contents: write`. Surface the actual error; don't silently continue to Phase 5. It's recoverable — but only if the user knows it happened.

## Phase 5 — Watch deploy

**Skip this entire phase when `deploy.adapter == none`** (the default): Phase 4.5 already tagged and published, so set `deployState: none` in the state file, go to Phase 6 and report "merged + tagged; no deploy adapter configured". Do not invent a deploy step the project doesn't have.

Otherwise set `deployState: watching` on entry (`done` when every watched service verifies) — this phase enforces the load-bearing invariant of the whole skill:

> **Verify the production service is actually running the merge SHA at a SUCCESS status. A health-200 is never proof.** A platform can report a deploy `FAILED` and silently keep serving an older build; a health probe against that older build still returns 200. Match the *running commit* to `MERGE_SHA` **and** require a terminal SUCCESS status before declaring the release live.

Read `deploy.watchDoc` (or `docPaths.deploy`) for the platform's commands and gotchas before polling; the project hints (`projectHints` directory → its `deploy.md`) carry the concrete verbs when present. The adapter contract below is the generic shape; the docs have the specifics.

### 5a. Enumerate services

Enumerate dynamically rather than hardcoding, so a new service is picked up without a skill edit. Start from `deploy.services` as the expected set and cross-check it against what the platform actually reports.

### 5b. Decide which to watch

If Phase 1's deploy-expectations analysis flagged a service as "no watch-pattern match", drop it from active polling — but still verify in the final report that its latest deployment is unchanged *and was successful* (a stale FAILED deploy on an untouched service is still a production fire). Otherwise, watch it. No Phase 1 analysis → watch all services and rely on the timeout logic below.

### 5c. Poll each watched service

Poll at ~180s cadence via your harness's wake/poll primitive. Cadence matters because every wake is a full model turn — don't tighten it below ~180s and don't emit no-op commands between wakes. The **wait conditions are platform-agnostic**:

**Success** — all three: the running deployment's commit *starts with* `MERGE_SHA` (platforms often store the short SHA, so `startswith`/substring, **never** strict `==`); its source branch is `<default>`; its status is the platform's terminal-success value (e.g. `SUCCESS`).

**Intermediate** — a deployment for `MERGE_SHA` exists at a build/deploy-in-progress status (`BUILDING` / `DEPLOYING` / `INITIALIZING` / `QUEUED`) → log one progress line and wake again. Or the latest deployment predates the merge commit → the platform hasn't picked up the push; usually clears within ~60s but can take minutes on a cold service, so wait at least 3 cycles before treating it as "no redeploy will happen".

**Failure paths — pause, ground via the deploy doc, surface:**

- **Silent rollback** (the case this skill exists for). A deployment for `MERGE_SHA` sits at `FAILED` while the currently-serving deployment is an older `SUCCESS` build. That old build can execute days-old code against a freshly-migrated schema, producing confusing errors like `relation "X" does not exist`. Pull build logs and surface. The health-200 is the trap — it's the *old* build answering.
- **No redeploy after ~10 min**, though Phase 1 said there should be one. Causes: wrong watch-pattern analysis, a forge webhook that didn't fire, a backed-up build queue. Check `${GH_PREFIX}gh api repos/<repoSlug>/commits/$MERGE_SHA/check-runs` for a platform check-run, then either force a deploy (a modify-shared-infra action — **confirm with the user first**) or surface.
- **Stale FAILED notification.** A dashboard can show a `FAILED` deploy prominently *after* a newer `SUCCESS` has landed. Before calling anything a silent rollback, check the chronology of the last few deployments — if the latest is `SUCCESS` at `MERGE_SHA`, the notification is stale; don't surface it as a failure.

### 5d. Adapter commands

Each adapter supplies three things against the contract above: a service-enumeration command, a per-service **deployment-list** command returning at least `{id, status, commit, branch, createdAt}` for the most recent deployments (list, not a status summary — the chronology is what distinguishes a silent rollback from a stale notification), and a build-log command. For the bundled `railway` adapter:

```bash
railway deployment list --service <name> --json \
  | jq '.[0:5] | .[] | {id, status, commit: .meta.commitHash, branch: .meta.branch, at: .createdAt}'
# success: .meta.commitHash startswith MERGE_SHA, .meta.branch == "<default>", .status == "SUCCESS"
```

For any other adapter, follow the same 5a–5c shape using the verbs in `deploy.watchDoc`. If the adapter is unrecognised and no `watchDoc` is set, say so and skip active polling rather than guessing platform verbs.

### 5e. Wakeup prompt

Wake with `prompt: "/ship-release <pr-num>"` (or whatever the user originally invoked) — nothing longer. Re-entering at the top hits the Phase 0 resume check, which reads the durable state ("released, `deployState: watching`") and jumps straight back here.

## Phase 6 — Report

When every watched service is on `MERGE_SHA` at a terminal SUCCESS status (or the user acked an anomaly, or `deploy.adapter == none`):

```
release: <NEXT_VERSION> — <PR title>

Version: <NEXT_VERSION>  (previous: <PREV_TAG or "bootstrap">, bump: <MAJOR|MINOR|PATCH>)
Release: <gh release URL>
PR:      <PR URL>
Merge:   <MERGE_SHA>

Deploy (adapter: <adapter>, env: <env>):
  <service> → <deployment-id>  SUCCESS  commit <short SHA>  at <ISO timestamp>
  -- or --
  no deploy adapter configured — merged + tagged only

Next: monitor the service health probe and the platform dashboards for the next ~15 min.
```

That last line is a reminder, not a phase. Don't keep polling after the report unless asked. Delete `.superpowers/workflows/ship-release/state.json` after the report — a present file always means an unfinished release.

## Notes

- **Standing release-publishing authorization.** Invoking this skill authorises `git tag -a`, `git push origin v*`, and `gh release create`. The proposed bump in 4.5d is the one confirmation round. Standing *local-commit* authorization does not extend to pushing `<default>`, `<integration>`, or any tag — those are the explicit Phase 4 / 4.5 operations covered here.
- **The `Co-Authored-By` trailer follows `commit.coAuthoredBy`** (default: include). Rarely relevant — the only artefacts this skill produces are the forge's merge commit and the annotated tag.
- **A failed release's tag stays.** If Phase 5 surfaces that the merge shipped something broken, the fix is a hotfix `ship-issue` on the integration branch then a new PATCH release — not a force-redeploy of old code. The tag is a permanent record that v1.4.0 was attempted; v1.4.1 supersedes it. Don't delete tags.
- **Invoked standalone with no argument**: infer scope from the merges in Phase 1 — the synthesised summary *is* the scope hint.
