---
name: ship-release
description: Releases the integration branch to the default branch — changelog, release PR, CI, merge, semver tag + GitHub Release, deploy watch. Use for "release", "ship to prod", "deploy".
argument-hint: "[scope hint — optional one-line summary phrase to seed the merge subject]"
---

# Ship Release

The unit of work is **all merges on the integration branch since the last default-branch merge**: land them on the default branch, tag + publish a GitHub Release, and (when a deploy adapter is configured) watch the platform pick it up.

## Ownership

When a controller delegates the release, it must launch one owner for the entire
existing phase sequence with this explicit selection:

<!-- agent-dispatch: id=ship-release-owner role=ship-owner model=opus effort=high -->
Agent(subagent_type="general-purpose", model="opus", effort="high") owns the release through final reporting.

A direct invocation keeps the current session as owner; never split release ownership.

## Project bindings (resolve first)

Run `resolve-project resolve --repo-root <checkout>`. Resolve once at phase entry, retain the returned `ResolvedProject` in memory, and treat every resolver error as fatal before mutation or external effects. On refusal, preserve and report the resolver's `error.code`, `repair_id`, and ordered `violations` exactly; never translate it into a partial snapshot or fallback. Use `bindings.tracker`, `bindings.vcs`, `bindings.commands`, `bindings.workflow.release`, and `bindings.deploy`. A blocked required capability stops; authored unsupported takes only the existing no-capability route.

`<integration>` and `<default>` come from `bindings.vcs.integration_branch` and `bindings.vcs.default_branch`; repository identity comes only from `bindings.tracker.repo_slug`. When identical there is no PR: run Phases 0 **and** 1, skip Phases 2–4, continue at Phase 4.5; the release ref is the confirmed tip of `<default>`.

Use `bindings.tracker.{kind,cli,repo_slug,credential_env.unset_before_invocation}` for forge actions. Never derive a repository value from Git or configuration. An authored unsupported tracker takes the tracker-free route; a blocked one stops the dependent forge operation.

Tracker-free route: Phases 0–1, then a local true merge (check out `<default>` and, only if that succeeded, `git merge --no-ff <integration>`) in place of Phases 2–4, tag the local merge result, skip forge steps, report the merge SHA and tag.

## Durable release state

Keep a skill-owned state file at `.superpowers/workflows/ship-release/state.json` (ensure `.superpowers/workflows/.gitignore` exists and contains `*`; create both if missing):

```json
{"headSha": "<origin/<integration> tip being released>", "pr": null, "prUrl": null,
 "mergeSha": null, "tag": null, "releaseUrl": null, "deployState": "pending"}
```

Write it atomically (temp file in the same dir, then `mv`) at every transition: Phase 0 (`headSha`), Phase 2 (`pr`, `prUrl`), Phase 4 or the local merge (`mergeSha`), Phase 4.5 (`tag`, then `releaseUrl`), Phase 5 (`deployState`: `watching` → `done`; `none` when no adapter). Phase 0 reads it **first** and re-enters at the first null field. Phase 6 deletes it after the report — a present file always means an unfinished release.

## Standing authorization

"Release" / "ship to prod" / "do the release" authorises the whole chain: opening the PR, waiting for CI, merging with `--merge`, tagging + publishing the Release (`git tag -a`, `git push origin v*`, `gh release create`), and polling the platform until each affected service is on the merge SHA. 4.5d's bump proposal is the one confirmation round; it does not extend to pushing `<default>` or `<integration>`. The `Co-Authored-By` trailer follows `bindings.vcs.commit.co_authored_by`. Pause only on Phase 0 failures, a CI check finishing `FAILURE` / `CANCELLED` / `TIMED_OUT` (Phase 3), a deployment finishing `FAILED` (Phase 5, *especially* a silent rollback), and genuinely new risks.

## Doc-grounded escalations

Before forming any user-facing question, invoke `doc-grounded-questions`, using only the retained snapshot's declared context, standards, architecture, and hint paths. Platform specifics (silent rollback, latest vs built commit, stale `FAILED`) come from the declared documents.

## gh hygiene

`GH_PREFIX` below is assembled only from the exhaustive names in `bindings.tracker.credential_env.unset_before_invocation`; for example, the list containing `GITHUB_TOKEN` yields `unset GITHUB_TOKEN && `. An empty list yields no prefix. When `bindings.tracker.cli == "glab"`, translate to `glab mr create/merge/view`, `glab ci status`, `glab release create` — only the verbs differ.

## Phase 0 — Pre-flight

0. **Resume check — before any "nothing to release" verdict.** `git fetch origin --prune --tags`, then:
   - **Durable state.** Read `.superpowers/workflows/ship-release/state.json` if present. `mergeSha` set but no `tag` → set `MERGE_SHA` from it, jump to Phase 4.5. `tag` set but no `releaseUrl` (forge case) → 4.5f. Released but `deployState` not terminal and `deploy.adapter != none` → Phase 5. A `headSha` matching neither `origin/<integration>` nor a resumable `mergeSha` is stale → surface it, continue fresh.
   - **Merged-PR lookup.** No usable state: `${GH_PREFIX}gh pr list --base <default> --head <integration> --state merged --limit 1 --json number,url,mergeCommit,mergedAt`. If the newest merged release PR's `mergeCommit.oid` carries no `v*` tag (`git tag --points-at <oid> 'v[0-9]*'` empty) and its head was the current `origin/<integration>` tip, a prior session crashed after Phase 4: set `MERGE_SHA=<oid>`, resume at Phase 4.5. (kind == none: `git tag --points-at $(git rev-parse <default>) 'v[0-9]*'` on the local merge result.)

   When neither resume path applies, record `headSha` in a fresh state file and continue.
1. **Default checkout, not a worktree.** `git rev-parse --git-common-dir` should be `.git` (or end in `.git`); `<repo>/.git/worktrees/<name>` means a feature worktree. Switch to the main checkout (`cd $(git -C "$(git rev-parse --git-common-dir)/.." rev-parse --show-toplevel)`) or surface.
2. **Working tree clean.** `git status --porcelain` empty. Surface uncommitted changes; don't auto-stash.
3. **`<integration>` is ahead of `<default>`.** `git log origin/<default>..origin/<integration> --first-parent --merges --pretty=oneline` output non-empty; each line is one merge. No output → nothing to release; report and stop. (Single-branch case: `git describe --tags --abbrev=0 origin/<default>` prints the previous tag, `<prev-tag>`; a non-zero exit means no tag yet — the first release — not a failed pre-flight. Use that explicit ref, never bare `git describe`. Check `git log <prev-tag>..origin/<default> --oneline` is non-empty with the printed tag written in, or `git log origin/<default> --oneline` for a first release; a shell variable does not survive between calls, so never expand one.)
4. **No existing open release PR.** `${GH_PREFIX}gh pr list --base <default> --head <integration> --state open --json number,url,headRefOid`. If one exists and its `headRefOid` matches `origin/<integration>`, a prior session crashed mid-flow — skip Phases 1–2, resume at Phase 3 or 4 by CI state. If its head is stale, surface; don't force-update another session's PR.
5. **CI on `origin/<integration>` is green.** `${GH_PREFIX}gh run list --branch <integration> --limit 5 --json conclusion,status,name,databaseId,headSha`; every run whose `headSha` equals `origin/<integration>` should be `conclusion: success`. Anything `cancelled`, `failure`, or pending → surface; wait it out (`gh run rerun --failed`) or hold.
6. **Local `<integration>` in sync with origin.** Compare `git rev-parse <integration>` with `git rev-parse origin/<integration>`:
   - Equal, or no local branch → continue.
   - **Local ahead** → unpushed commits on the integration line. Surface with `git log --oneline --left-right LOCAL...REMOTE`, quoting its first 20 lines, and ask whether they belong. Don't auto-resolve.
   - **Local behind** → stale local branch. Offer `git checkout <integration>` and, only if that succeeded, `git merge --ff-only origin/<integration>`.
   - **Diverged** → surface the divergence; the user decides. Don't auto-rebase or reset.

Any failure: ground, then surface.

## Phase 1 — Changelog

**Read [`CHANGELOG.md`](./CHANGELOG.md) first** — it owns the PR body's content: categorisation rubric, output template, version-bump signals.

Two outputs:

1. **The PR body** — assembled per `CHANGELOG.md`'s template.
2. **The PR title / merge-subject seed** — one line under 70 chars from the body's synthesis; it becomes `gh pr create --title` and, with `(<integration> → <default>)` appended, `gh pr merge --subject`.

Also surface the number of first-parent merges in the range and — only when `deploy.adapter != none` — the **deploy expectations** from retained deploy-related documentation (they feed **Deploy notes**).

Do not create a tracked `CHANGELOG.md` in the repo root unless the user explicitly asks.

## Phase 2 — Open PR

Write the Phase 1 body to `<release-body-path>`, outside the working tree, with the file-writing tool and pass it by path (`worktrees/SKILL.md`, `## Shell forms the isolation checker refuses`).

```bash
${GH_PREFIX}gh pr create \
  --base <default> \
  --head <integration> \
  --title "<merge subject seed from Phase 1>" \
  --body-file <release-body-path>
```

Title pattern: `merge: <integration> — <two or three comma-separated themes>`, under 70 chars (the merge subject minus its `(<integration> → <default>)` suffix). A user-supplied scope-hint argument seeds it — keep the user's intent. With no argument, the Phase 1 synthesis is the scope hint.

Persist `pr` + `prUrl` to the durable state file now.

## Phase 3 — Wait for CI

Verify CI is watching the right tip:

```bash
${GH_PREFIX}gh pr view <pr-num> --json headRefOid
```

It must equal `git rev-parse origin/<integration>` after a fetch. Drift (new commits since the PR opened): surface it; prefer finishing on the older tip and releasing again after.

Then block on CI with one Bash call, **300s timeout**, foreground:

```bash
${GH_PREFIX}timeout 300 gh pr checks <pr-num> --watch --fail-fast --interval 30
```

**Do not background it** (`run_in_background`, `Monitor`).

**No improvised polling:** no `gh pr checks` without `--watch` more than once per phase, no `gh run view`/`tail` loops, no no-op turns.

Exit codes:

- **`0`** → all checks pass; continue to Phase 4.
- **`124`** → still running. Emit one short narration turn (`CI: still pending at 5m, retry 2/8`), re-run the identical command, up to **8 times (~40 min)**, then escalate. Prompt: "PR #<n> has been pending ~40 min with no terminal CI state. Options: (a) wait another 10 min, (b) close+reopen to re-trigger checks, (c) merge admin-only if allowed, (d) abort and investigate."
- **any other non-zero** → a check failed. Pull `gh run view <run-id> --log-failed`, ground (lint → retained standards, test → area spec/plan), surface. The fix usually lands via a follow-up `ship-issue`; then rebase this PR head onto the new `origin/<integration>` (close+reopen or push-update, the user's pick).

## Phase 4 — Merge

```bash
${GH_PREFIX}gh pr merge <pr-num> --repo <resolved-repository> --merge --subject "merge: <integration> — <scope summary> (<integration> → <default>)"
```

**Spell it exactly like that, on one line**, with `--subject` mirroring the PR title plus `(<integration> → <default>)`. The `PreToolUse` lifecycle guard adjudicates `gh pr merge` as its release arm; act on its refusal. The subject must contain none of `"`, `$`, backtick, backslash, or a newline.

**Do NOT pass `--delete-branch` when `<integration> != <default>`** (the integration branch is permanent). **Do NOT pass `--no-ff`**: `gh` ≥ 2.83 rejects it, and `--merge` alone makes a true merge commit.

Verify: `${GH_PREFIX}gh pr view <pr-num> --json state,mergeCommit` → `MERGED` plus a non-null `mergeCommit.oid`. Capture that oid as `MERGE_SHA` and persist `mergeSha` to the durable state file **before doing anything else**.

Then `git fetch origin` to refresh local refs. Don't `git push origin <default>`, and don't check out `<default>` to merge it locally.

## Phase 4.5 — Tag + GitHub Release

Every release gets a semver tag and a GitHub Release; no opt-out. (Unsupported tracker capability: local annotated tag only, skip 4.5f–4.5g.)

The semver rubric lives **only** in [`CHANGELOG.md`'s "Version bump signals"](./CHANGELOG.md#version-bump-signals); read it before computing, and don't re-litigate the categorisation.

### 4.5a. Resolve the merge SHA

Run exactly ONE of these — they are alternatives, not a sequence.

PR path (a release PR was merged):

```bash
MERGE_SHA=$(${GH_PREFIX}gh pr view <pr-num> --json mergeCommit -q .mergeCommit.oid)
```

The no-PR paths (single-branch and/or kind == none) resolve it AFTER any local merge:

```bash
MERGE_SHA=$(git rev-parse <default>)
```

On the no-PR paths the target is the **local** `<default>`, never `origin/<default>` (the stale pre-merge tip).

### 4.5b. Skip condition — before creating anything

The only skip: this merge commit was already tagged + released. Check **before** 4.5e/4.5f:

```bash
# a remote? fetch tags first, so a tag pushed by a crashed session is visible
git remote get-url origin
git fetch --tags --quiet origin
EXISTING=$(git tag --points-at "$MERGE_SHA" 'v[0-9]*')
```

The fetch is conditional: skip the fetch when the first command exits non-zero (no remote). The check is tag-based on both paths: `gh release list`'s `targetCommitish` holds a **branch name**, not the merge SHA.

Non-empty → ask "Release `$EXISTING` already exists for merge $MERGE_SHA. Skip tag + create?" Default: skip — record `tag`/`releaseUrl` and go to Phase 5. A tag with no Release (forge case: `${GH_PREFIX}gh release view "$EXISTING"` fails) → resume at 4.5f only.

### 4.5c. Find the previous release tag

```bash
git for-each-ref --count=1 --merged "$MERGE_SHA" --sort=-v:refname --format='%(refname:short)' 'refs/tags/v[0-9]*'
```

Its one output line is `PREV_TAG`; no output is the bootstrap case. `--merged "$MERGE_SHA"` excludes tags from unmerged branches. No `v*` tags (or only non-semver checkpoint tags) → bootstrap: surface the existing tags and propose **v0.1.0** ("pre-1.0; override?"). Never silently jump to `v1.0.0`.

### 4.5d. Decide MAJOR / MINOR / PATCH

Apply `CHANGELOG.md`'s "Version bump signals" table (pre-1.0 caveat and ambiguity calls included) to the Phase 1 buckets, top-down, first match wins.

Surface the proposal with its evidence:

```
Proposed next version: v1.4.0  (from v1.3.2, MINOR bump)

Evidence:
- ## Features has 2 entries → MINOR triggered
- ## Deploy notes has 1 entry, additive with a default → not MAJOR
- No breaking ADRs or schema drops in the range

Override? (M/m/p — uppercase for major, lowercase for minor/patch; or a literal version like 'v2.0.0')
```

One round only: if the user confirms or doesn't respond, proceed. In `--auto`, proceed without prompting.

### 4.5e. Tag the merge commit

```bash
NEXT_VERSION=v1.4.0   # from 4.5d

git tag -a "$NEXT_VERSION" "$MERGE_SHA" -m "release: $NEXT_VERSION — <one-line scope from PR title>"
${GH_PREFIX}git push origin "$NEXT_VERSION"   # skip the push when kind == none
```

Annotated (`-a`, as `git describe` and `gh release` expect), tagging `MERGE_SHA` explicitly (never `HEAD`). Persist `tag` to the state file as soon as `git tag` succeeds.

### 4.5f. Create the GitHub Release

```bash
${GH_PREFIX}gh pr view <pr-num> --json body -q .body

${GH_PREFIX}gh release create "$NEXT_VERSION" \
  --target <default> \
  --title "$NEXT_VERSION — <one-line scope from PR title>" \
  --notes-file <release-notes-path>

rm <release-notes-path>
```

Between the two: write the body the first command printed to `<release-notes-path>` (outside the working tree) with the file-writing tool, pass that path to the second, and remove it once the Release exists. No PR (single-branch): write the Phase 1 body there. Skip `--prerelease` and `--draft`.

### 4.5g. Verify

```bash
${GH_PREFIX}gh release view "$NEXT_VERSION" --json url,tagName,createdAt,isLatest -q .
```

`tagName == "$NEXT_VERSION"` and `isLatest == true`. Capture `.url` for Phase 6 and persist `releaseUrl` to the state file.

If `gh release create` fails (rejected tag push, token without `contents: write`), surface the actual error; do not continue to Phase 5.

## Phase 5 — Watch deploy

**Skip this entire phase when `deploy.adapter == none`** (the default): set `deployState: none` in the state file, go to Phase 6 and report "merged + tagged; no deploy adapter configured".

Otherwise set `deployState: watching` on entry (`done` when every watched service verifies). The invariant: the running commit starts with `MERGE_SHA`, on branch `<default>`, at a terminal SUCCESS status. A health 200 is not proof: a failed deploy keeps serving the older build.

Before polling, read the retained snapshot's deploy-related context and hint paths; the adapter contract below is generic, the declared documents carry the specifics.

### 5a. Enumerate services

Enumerate only the services declared in retained `bindings.deploy.config`, cross-checked against what the platform reports.

### 5b. Decide which to watch

A service Phase 1's deploy-expectations analysis flagged "no watch-pattern match" is dropped from polling, but the final report still verifies its latest deployment is unchanged *and was successful*. Otherwise watch it; with no Phase 1 analysis, watch all.

### 5c. Poll each watched service

Poll at ~180s via your harness's wake/poll primitive; no no-op commands between wakes.

**Success** — all three: the running deployment's commit *starts with* `MERGE_SHA` (platforms often store the short SHA: `startswith`/substring, **never** strict `==`); its source branch is `<default>`; its status is the platform's terminal-success value (e.g. `SUCCESS`).

**Intermediate** — a deployment for `MERGE_SHA` exists at a build/deploy-in-progress status (`BUILDING` / `DEPLOYING` / `INITIALIZING` / `QUEUED`) → log one progress line and wake again. Or the latest deployment predates the merge commit → not picked up yet; wait at least 3 cycles before treating it as "no redeploy".

**Failure paths — pause, ground via the deploy doc, surface:**

- **Silent rollback.** A deployment for `MERGE_SHA` sits at `FAILED` while the currently-serving deployment is an older `SUCCESS` build. Pull build logs and surface.
- **No redeploy after ~10 min**, though Phase 1 said there should be one. Check `${GH_PREFIX}gh api repos/<resolved-repository>/commits/$MERGE_SHA/check-runs` for a platform check-run, then either force a deploy (a modify-shared-infra action — **confirm with the user first**) or surface.
- **Stale FAILED notification.** A dashboard can show `FAILED` after a newer `SUCCESS` landed. Before calling a silent rollback, check the last few deployments' chronology; if the latest is `SUCCESS` at `MERGE_SHA`, the notification is stale.

### 5d. Adapter commands

An adapter supplies a service-enumeration command, a per-service **deployment-list** command returning at least `{id, status, commit, branch, createdAt}` for the most recent deployments (a list, not a status summary: the chronology tells a silent rollback from a stale notification), and a build-log command. For the bundled `railway` adapter:

```bash
railway deployment list --service <name> --json
# success: .meta.commitHash startswith MERGE_SHA, .meta.branch == "<default>", .status == "SUCCESS"
```

Read the five most recent entries of that JSON and, for each, the fields `id`, `status`, `.meta.commitHash`, `.meta.branch`, and `createdAt`.

Any other adapter follows 5a–5c using only retained `bindings.deploy` command/config values; an unrecognised adapter stops and surfaces its declared state.

### 5e. Wakeup prompt

Wake with `prompt: "/ship-release <pr-num>"` (or whatever the user originally invoked) — nothing longer.

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

Do not keep polling after the report unless asked. A failed release's tag stays: fix with a hotfix `ship-issue` and a new PATCH release; never delete tags. Delete `.superpowers/workflows/ship-release/state.json` after the report.
