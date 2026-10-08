# Generating the release changelog

Loaded by Phase 1 of [`SKILL.md`](./SKILL.md). This file owns the PR body's content; `SKILL.md` owns the workflow.

`<integration>` and `<default>` come from `bindings.vcs`; the repository slug comes from `bindings.tracker.repo_slug`. Build every PR/commit/ADR URL from it; never hardcode an owner/name.

## Contents

- Step 1 — Mine the merges
- Step 2 — Categorise each merge
- Step 3 — Write each entry
- Step 4 — Top-of-body synthesis
- Step 5 — Assemble the PR body
- Quality check before opening the PR
- Version bump signals

## Step 1 — Mine the merges

```bash
${GH_PREFIX}git fetch origin --prune
git log origin/<default>..origin/<integration> --first-parent --merges \
  --pretty=format:'%h%x1f%s%x1f%cI%x1f%b%x1e'
```

Split fields on `%x1f`, records on `%x1e`.

Single-branch (`<integration> == <default>`): the range is `<prev-tag>..origin/<default>` and `--merges` is dropped, since direct commits are the release units. Write the tag that `git describe --tags --abbrev=0 origin/<default>` prints into the command; a shell variable does not survive to a later call. With no tag yet that command exits non-zero and prints nothing, and the range is `origin/<default>`.

For each merge, resolve the PR only when `capabilities.tracker` permits it:

```bash
${GH_PREFIX}gh pr list --search "<merge-sha>" --state merged \
  --json number,title,url,labels,body -q '.[0]'
```

An empty result means no PR: note it, keep the merge and use a commit URL. Read the PR body: it carries the intent.

## Step 2 — Categorise each merge

Walk the table in order; stop at the first match.

| Question | Bucket |
|---|---|
| Does it break or change operator-visible config (env vars, schema, endpoint shape, retired surface)? | **Deploy notes** (always — and pick a second bucket below) |
| Is it a marquee change anyone reading these notes should know about? | **Highlights** (1–3 max; promote, don't dilute) |
| Does it add a new operator-visible capability that didn't exist before? | **Features** |
| Does it make an existing capability faster, safer, more observable, easier to operate? | **Improvements** |
| Does it fix a defect or restore expected behaviour? | **Fixes** |
| Is it operator-invisible — pure refactor, test hardening, internal docs, dependency bump? | **Internal** |

- Five highlights means you're padding; demote to Features/Improvements.
- A merge appears in two buckets only when one of them is Deploy notes. Otherwise pick the primary operator impact.
- "Decommission X" / "retire Y" / "remove Z" is usually Deploy notes, even when the user-visible message is just "fewer endpoints".
- ADR commits and spec/plan docs are Internal, unless they encode a behaviour change operators need; then categorise by the behaviour.
- **Don't synthesise from the merge subject alone.** Subjects look like `merge: <slug> — <terse desc> (issue-N → <integration>)`; the operator-facing meaning lives in the PR body and the diff.

## Step 3 — Write each entry

**One short sentence, imperative voice, operator-facing meaning, PR link.** The project's worked examples arrive through passed `bindings.paths.hints` paths; read them if present.

| Bad | Good |
|---|---|
| `c7d3002a merge: <slug> — <terse desc> (issue-N → <integration>)` | `<What changed, in the words an operator would search for> — <the consequence they'd notice> ([#N](https://github.com/<passed-repo-slug>/pull/N))` |
| `Various fixes and improvements` | (delete; if you're tempted to write this, you haven't read enough merges yet) |

- Link the PR inline with the **full URL**, never a bare `#N`.
- Link ADRs only from the caller-passed context paths, cited by their full id. Skip when none were passed.
- One PR that shipped two distinct operator-visible changes gets two entries linking the same PR.

## Step 4 — Top-of-body synthesis

Open with a 2–4 sentence summary of the release's 2–3 main threads. Shape:

> This release lands `<theme 1: the marquee capability, with its sub-parts named>`, retires `<theme 2: the concept removed, and how far it went>`, and tightens `<theme 3: the surface hardened>`. Plus the usual hardening across `<area>`.

Tone: factual, not promotional; `Merged 57 PRs from <integration> — see list below` is not a synthesis.

## Step 5 — Assemble the PR body

```markdown
<2–4 sentence prose synthesis from Step 4>

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
- <endpoint `/api/...` is now admin-only>

## Internal
<single paragraph or short list — refactors, test hardening, doc updates, dep bumps. Group, don't enumerate.>

## Included PRs (raw)
<details>
<summary>All <N> merged PRs, in commit order</summary>

- [#N](https://github.com/<passed-repo-slug>/pull/N) — <merge subject verbatim>
- ...
</details>

## Verification (post-merge)
- <when bindings.deploy.adapter != none: per-service running-commit check — the latest deployment's status is the platform's SUCCESS value AND its commit starts with the merge SHA. Use retained bindings.deploy command/config values.>
- A health probe returning 200 is *not* proof — verify the running commit equals the merge SHA at a SUCCESS status (SKILL.md Phase 5).
```

Skip an empty section. When `deploy.adapter == none`, drop the Verification section's deploy lines and keep only the merged+tagged record.

## Quality check before opening the PR

Re-read the body:

- Could a teammate tell what landed in 90 seconds (synthesis + Highlights)?
- Could an on-call engineer tell which PR to suspect for a regression?
- Is everything in Deploy notes already reflected in the deploy env / schema state? If not, fix that *before* merging.
- Does Highlights hold only what deserves it, with no internal churn such as a dependency bump?
- Is any `Various` / `Misc` left, or a flat SHA dump? Only the raw list holds verbatim subjects.
- Is any entry process rather than content? "ADR-NNNN implemented" is not one; what the ADR made the system do is.

Any "no" or "not sure" means iterate before opening.

## Version bump signals

Feeds [`SKILL.md` Phase 4.5d](./SKILL.md#45d-decide-major--minor--patch). **This table is the only copy of the rubric**. Walk top-down, **stop at the first matching rule**.

| Bucket evidence | Bump |
|---|---|
| `## Deploy notes` has at least one entry requiring *operator action to upgrade* that is *not backward-compatible*: an env var the app rejects on missing; a migration dropping a column/table with no shim; an endpoint/contract change with no compat path; an ADR marked breaking. | **MAJOR** |
| `## Highlights` or `## Features` has at least one new operator-visible capability. | **MINOR** |
| Only `## Improvements`, `## Fixes`, `## Internal`, or non-breaking `## Deploy notes` (additive env vars *with defaults*, additive migrations, telemetry-only changes). | **PATCH** |

**Pre-1.0 caveat.** While `PREV_TAG` is `0.x.y`, the table shifts down one slot: MAJOR-class evidence yields a MINOR bump; MINOR and PATCH map to themselves. The 0.x → 1.0 promotion is a separate operator decision.

Worked example (MAJOR on the 1.0+ track):

```
## Deploy notes
- New required env var `<Key>` — the app refuses to start without it. Set it before deploying.
- Migration drops `<table>.<column>` — no shim; downstream consumers must read `<replacement>`.
```
→ Two entries needing operator action, neither backward-compatible: **MAJOR**. On a `v0.x` predecessor, **MINOR**.

When the rubric is ambiguous:

- **Both breaking-deploy and feature** → MAJOR wins.
- **A flipped feature-flag default** → the test is operator-visibility. Anyone on default config seeing a different shape after the upgrade = MAJOR. Behaviour that requires opting in = MINOR plus a Deploy notes mention.
- **A NOT NULL column added with a backfill default** → MINOR, with the backfill timeline in Deploy notes.
- **In genuine doubt, propose the higher bump** and show the reasoning.

Whether release notes carry an AI-assistance trailer follows `bindings.vcs`.
