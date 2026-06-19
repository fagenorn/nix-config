# Generating the release changelog

This file is loaded by Phase 1 of [`SKILL.md`](./SKILL.md). It owns the *content* of a release's PR body: the categorisation rubric, the output template, the examples of what good vs bad entries look like. SKILL.md owns the workflow around it (when to generate, where it goes, what happens next).

Throughout this file, `<integration>` is the resolved `integrationBranch` (default `main`), `<default>` is the resolved `defaultBranch` (default `main`), and `<repoSlug>` is `repoSlug` from `.claude/skills.config.json` — or, when absent, derived once from `git remote get-url origin`. Build every PR/commit/ADR URL from `<repoSlug>`; never hardcode an owner/name.

The audience for a release PR body is the operator who has to debug something three months later — usually you, sometimes a teammate, occasionally someone reconstructing a regression from the merge log. Write for that reader. They don't care about the SHA of every cherry-pick; they care about *what landed and what they need to know to operate it*.

## Step 1 — Mine the merges

```bash
${GH_PREFIX}git fetch origin --prune
git log origin/<default>..origin/<integration> --first-parent --merges \
  --pretty=format:'%h%x1f%s%x1f%cI%x1f%b%x1e'
```

(`${GH_PREFIX}` = `unset GITHUB_TOKEN && ` only when `unsetGithubToken` is true; otherwise nothing.)

Field separator is `%x1f` (US), record separator is `%x1e` (RS) — chosen because they don't collide with anything in commit messages. Parse into records of `{sha, subject, committed_at, body}`.

For each merge, also resolve the PR (when `issueTracker.kind != "none"`):

```bash
${GH_PREFIX}gh pr list --search "<merge-sha>" --state merged \
  --json number,title,url,labels,body \
  -q '.[0]'
```

Empty result means the merge was done locally without a PR (rare — usually an integration-branch resync or a hotfix). Note it but don't drop it from the list; use a commit URL instead of a PR URL.

Read the PR body when it's available — it has the *intent* of the change, which is more useful than the merge subject when you're writing operator-facing prose.

## Step 2 — Categorise each merge

Walk the merges through this decision tree, in order. Stop at the first match.

| Question | Bucket |
|---|---|
| Does this break or change operator-visible config (env vars, schema, endpoint shape, retired surface)? | **Deploy notes** (always — and pick a second bucket below) |
| Is it a marquee change anyone reading these notes should know about? | **Highlights** (1–3 max per release; promote, don't dilute) |
| Does it add a new operator-visible capability that didn't exist before? | **Features** |
| Does it make an existing capability faster, safer, more observable, easier to operate? | **Improvements** |
| Does it fix a defect or restore expected behaviour? | **Fixes** |
| Is it operator-invisible — pure refactor, test hardening, internal docs, dependency bump? | **Internal** |

Notes on judgment:

- **Highlights is a quality bar, not a quantity.** If you find yourself listing five highlights, the release didn't have five marquee changes — it had one or two and you're padding. Demote the rest to Features/Improvements.
- **A merge can appear in two buckets only if one is Deploy notes.** Otherwise pick the *primary* operator impact and let the secondary be implicit in the prose.
- **"Decommission X" / "retire Y" / "remove Z" is usually Deploy notes**, even when the user-visible message is just "fewer endpoints." A migration that drops a column is a deploy-time concern.
- **ADR commits and spec/plan docs are Internal** unless they encode a behaviour change that operators need to know about (in which case categorise by the behaviour, not the doc).
- **Don't synthesise from the merge subject alone.** The subject is often `merge: <slug> — <terse desc> (issue-N → <integration>)`. The PR body and the diff are where the operator-facing meaning lives.

## Step 3 — Write each entry

**One short sentence per entry, imperative voice, operator-facing meaning, PR link.**

| Bad | Good |
|---|---|
| `c7d3002a merge: decommission unassigned device — move DELETE to admin tree (issue-182 → <integration>)` | `Move unassigned-device decommission DELETE to the admin tree — endpoint now requires admin auth ([#190](https://github.com/<repoSlug>/pull/190))` |
| `merge: ADR-0017 — provider-policy prevention guard (issue-176 → <integration>)` | `Reject provider policies that would conflict with platform contributions before they're persisted — eliminates a class of "policy applied silently dropped" bugs ([#188](https://github.com/<repoSlug>/pull/188), [ADR-0017](<adrDir>/0017-provider-policy-contribution-guard.md))` |
| `Various fixes and improvements` | (delete; if you're tempted to write this, you haven't read enough merges yet) |

Rules of thumb:

- Lead with the *change*, not the issue number.
- Use the words an operator would search for — feature names, endpoint paths, env var names, table names. Not internal class names unless they're the user-facing surface.
- Link the PR inline with the full URL: `[#N](https://github.com/<repoSlug>/pull/N)`. **Full URLs, never bare `#N`** — many forges auto-link a bare `#N` against the wrong repo context under cross-references.
- Link ADRs when relevant, using `docPaths.adrDir`: `[ADR-0017](<adrDir>/0017-...md)`. Skip if no ADR dir is configured.
- Don't include the SHA. The PR link is enough.
- If a single PR shipped two distinct operator-visible changes, write two entries linking the same PR.

## Step 4 — Write the top-of-body synthesis

The first thing in the PR body is a 2–4 sentence prose summary that themes the release. It's the executive summary an operator reads first; the categorised list is the detail they drill into.

Pick the 2–3 themes that organise most of the release. Examples:

| Bad | Good |
|---|---|
| `Merged 57 PRs from <integration> — see list below.` | `This release lands the workflow-triggers MVP (scheduler, manual run, webhooks), retires the seeded-models concept end-to-end (admin-authored models only), and tightens the device-admin surface (decommission moves to admin tree, audit-log targetType harmonised). Plus the usual hardening across the worker fleet.` |
| `Various improvements across the codebase.` | `Three themes: (a) operator-visible model-library overhaul — one-click add from discovery, new connector, iteration-cap policy switches; (b) admin-tree consolidation — decommission, console, spectator console, typed-confirmation preempt all moved or unified; (c) production-noise reduction in the browser fleet and reconciler.` |

Tone: factual, not promotional. No "exciting new", no "we're thrilled". Operators don't want enthusiasm; they want signal.

## Step 5 — Assemble the PR body

```markdown
<!-- top-of-body synthesis from Step 4 -->
<2–4 sentence prose summary>

## Highlights
- <1–3 marquee entries>

## Features
- <entries>

## Improvements
- <entries>

## Fixes
- <entries>

## Deploy notes
> **Required before merge:** verify the items below are reflected in the deploy env / schema state.
- <env var X added — `<value source>`>
- <schema migration: column `foo.bar` dropped (ADR-XYZ)>
- <endpoint `/api/admin/devices/{id}` is now admin-only>

## Internal
<single paragraph or short list — refactors, test hardening, doc updates, dep bumps. Don't enumerate; group them.>

## Included PRs (raw)
<details>
<summary>All <N> merged PRs, in commit order</summary>

- [#190](https://github.com/<repoSlug>/pull/190) — merge: decommission unassigned device — move DELETE to admin tree (issue-182 → <integration>)
- [#188](https://github.com/<repoSlug>/pull/188) — merge: ADR-0017 — provider-policy prevention guard (issue-176 → <integration>)
- ...
</details>

## Verification (post-merge)
- <when deploy.adapter != none: per-service running-commit check — the latest deployment's status is the platform's SUCCESS value AND its commit starts with the merge SHA. See deploy.watchDoc for the exact command.>
- A health probe returning 200 is *not* proof — verify the running commit equals the merge SHA at a SUCCESS status (see SKILL.md Phase 5 and the configured deploy doc).
```

Skip a section if it's empty — don't write "## Fixes\n*none*". A reader can tell from absence. When `deploy.adapter == none`, drop the "Verification (post-merge)" section's deploy lines and keep only the merged+tagged record.

The collapsible "Included PRs (raw)" at the bottom keeps the full list available for future debugging (the use case the user originally implied for an "exhaustive" changelog) without cluttering the operator-facing read.

## Quality check before opening the PR

Before you call `gh pr create`, re-read the assembled body and ask:

1. **If a teammate read this in 90 seconds, would they know what landed?** The top synthesis + Highlights should answer that.
2. **Would an on-call engineer responding to a regression know which PR to suspect?** The category-by-impact-area structure is what gets them there.
3. **Is anything in Deploy notes that's not also reflected in the deploy env / schema state right now?** If yes, fix that before merging — that's what Deploy notes is for.
4. **Have I demoted everything that doesn't deserve to be in Highlights?** If Highlights has 5+ items, demote.
5. **Are there `Various` / `Misc` / generic phrasings?** If yes, you're not done reading the merges.

If any answer is "no" or "I'm not sure", iterate on the body before opening the PR. The body becomes the merge commit's permanent record — it's cheaper to fix now than in `git log --grep`.

## Anti-patterns

- **The flat SHA dump.** Subject lines copied verbatim with their merge-subject prefix and `issue-N → <integration>` suffix. Unreadable. The "raw" collapsible at the bottom is the only place this format is acceptable.
- **Headlining everything.** Highlights with 10 items means none of them are highlighted.
- **Confusing process with content.** "ADR-0017 implemented" is not a changelog entry. "Reject provider policies that would conflict with platform contributions" is. The ADR is the *why*, not the *what*.
- **Padding with internal churn.** A dependency bump or test rename in Highlights signals you're filling space. Internal is fine for these — that's what it's for.

## Version bump signals

This section feeds [`SKILL.md` Phase 4.5b](./SKILL.md#45b-decide-major--minor--patch) — once the PR body is assembled per the categorisation above, the same buckets drive the semver bump. Same evidence, two outputs: the changelog *and* the version increment.

### The decision tree

Walk the categorised body top-down. **Stop at the first matching rule** — earlier rules dominate later ones.

| Bucket evidence | Bump |
|---|---|
| `## Deploy notes` contains at least one entry that requires *operator action to upgrade* AND is *not backward-compatible*: a new env var the app rejects on missing; a schema migration that drops a column/table without a shim; an endpoint/contract change without a compat path; an ADR explicitly marked as breaking. | **MAJOR** |
| `## Highlights` or `## Features` contains at least one new operator-visible capability. | **MINOR** |
| Only `## Improvements`, `## Fixes`, `## Internal`, or non-breaking `## Deploy notes` (additive env vars *with defaults*, additive migrations, telemetry-only changes). | **PATCH** |

### Pre-1.0 caveat

While `PREV_TAG` is on `0.x.y`, the table above shifts down one slot: what would be MAJOR on a 1.0+ release is a MINOR bump on `0.x` (`0.MINOR.0` → `0.MINOR+1.0`); MINOR maps to MINOR, PATCH maps to PATCH. This is the [semver §4 unstable-release convention](https://semver.org/#spec-item-4) — pre-1.0 explicitly disclaims API stability, so "breaking" doesn't mean what it means at 1.0+. The 0.x → 1.0 promotion is a separate operator decision, not driven by this rubric.

### Worked examples

**Example 1 — MAJOR (1.0+ track):**

```
## Deploy notes
- New required env var `Console:DownstreamTicketKey` — app refuses to start without it. Upsert it (generated by `openssl rand -base64 32`) before deploying.
- Migration drops `business_device.worker_version` — no shim, downstream consumers must read `business_device.worker_id` instead.
```
→ Two breaking entries: a required env var with no default that blocks startup + a schema drop without a shim. Bump = **MAJOR**.

**Example 2 — MINOR (1.0+ track):**

```
## Features
- Workflow triggers MVP — cron scheduler, schedule/workflow/business pickers, fires panel.
- Provider discovery endpoints — OpenAI + Anthropic /v1/models proxy.

## Improvements
- 30s retry budget on the publish-and-roll race window in CI.

## Deploy notes
- New optional env var `Scheduler:DefaultTimezone` — defaults to `UTC`; no action required.
```
→ Features present, no breaking deploy notes (the env var is additive with default). Bump = **MINOR**.

**Example 3 — PATCH (1.0+ track):**

```
## Fixes
- RecordingListener trace-scope flake — re-establishes scope inside the listener callback.
- Audit-log `targetType` harmonised to a single canonical enum name (no observable change).

## Internal
- Dependency bumps (test framework, ORM minor versions).
- Test collection split for parallel runs.
```
→ Only fixes + internal + non-breaking alignment. Bump = **PATCH**.

**Example 4 — MINOR (pre-1.0 track, `0.x` caveat):**

```
## Deploy notes
- Migration drops `business_device.worker_version` — no shim, downstream must read `worker_id`.
```
→ Would be MAJOR on a 1.0+ track, but the previous tag is `v0.3.2`, so the 0.x caveat applies. Bump = **MINOR** (`v0.3.2 → v0.4.0`).

### When the rubric is ambiguous

- **A merge looks both breaking-deploy and feature.** It's both — and MAJOR wins. The whole point of MAJOR is that operators need to coordinate before the upgrade lands; that signal dominates the "we also added a thing" signal.
- **A merge is "kind of breaking" — e.g. a feature flag default flipped.** The question is operator-visibility: if anyone running the platform with default config experiences a different shape *after the upgrade*, that's MAJOR. If they have to opt in via a flag to see the new behaviour, that's MINOR with a Deploy notes mention.
- **A schema migration adds a NOT NULL column with a backfill default.** Backward-compatible from the *application's* perspective (it can read both old and new shape if the code is written defensively), but if downstream consumers query the column directly they'd see no value pre-migration. Call it MINOR; surface in Deploy notes with the backfill timeline.
- **In genuine doubt, propose the higher bump and surface the reasoning.** Over-bumping is recoverable (the next release is just one tag away); under-bumping creates an incident where v1.4.0 actually broke something an operator wasn't warned about. The cost is asymmetric.

### Calling it out in the proposal

When Phase 4.5b proposes the bump to the user, include the *evidence*, not just the verdict:

```
Proposed: v1.4.0  (from v1.3.2 — MINOR bump)

Evidence:
- ## Features has 2 entries (workflow triggers, provider discovery) → MINOR triggered
- ## Deploy notes has 1 entry (Scheduler:DefaultTimezone) — additive with default → not MAJOR
- No breaking ADRs or schema drops in the range

Override? (M/m/p, or literal version)
```

That format lets the user veto with one keystroke if they disagree with the categorisation, and lets them see *why* if they want to learn the rubric.

- **Mentioning the agent.** Whether release notes carry an AI-assistance trailer follows `commit.coAuthoredBy` (default: include). If the project sets it to `false`, don't write "Claude implemented X" or include a `Co-Authored-By` trailer; otherwise follow the project's commit convention.
