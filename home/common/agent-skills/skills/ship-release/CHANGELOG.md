# Generating the release changelog

Loaded by Phase 1 of [`SKILL.md`](./SKILL.md). This file owns the *content* of a release's PR body — the categorisation rubric, the output template, and the version-bump signals. SKILL.md owns the workflow around it.

`<integration>`, `<default>`, and `<repoSlug>` resolve as in SKILL.md. Build every PR/commit/ADR URL from `<repoSlug>`; never hardcode an owner/name.

The audience is the operator debugging something three months from now — usually you. They don't care about the SHA of every cherry-pick; they care about *what landed and what they need to know to operate it*.

## Step 1 — Mine the merges

```bash
${GH_PREFIX}git fetch origin --prune
git log origin/<default>..origin/<integration> --first-parent --merges \
  --pretty=format:'%h%x1f%s%x1f%cI%x1f%b%x1e'
```

Field separator `%x1f` (US), record separator `%x1e` (RS) — neither collides with anything in commit messages. Parse into `{sha, subject, committed_at, body}`.

For each merge, resolve the PR (skip when `issueTracker.kind == "none"`):

```bash
${GH_PREFIX}gh pr list --search "<merge-sha>" --state merged \
  --json number,title,url,labels,body -q '.[0]'
```

An empty result means the merge was done locally without a PR (rare — usually a resync or hotfix). Note it, use a commit URL instead of a PR URL, don't drop it. Read the PR body where it exists: it carries the *intent*, which beats the merge subject for writing operator-facing prose.

## Step 2 — Categorise each merge

Walk the decision tree in order; stop at the first match.

| Question | Bucket |
|---|---|
| Does it break or change operator-visible config (env vars, schema, endpoint shape, retired surface)? | **Deploy notes** (always — and pick a second bucket below) |
| Is it a marquee change anyone reading these notes should know about? | **Highlights** (1–3 max; promote, don't dilute) |
| Does it add a new operator-visible capability that didn't exist before? | **Features** |
| Does it make an existing capability faster, safer, more observable, easier to operate? | **Improvements** |
| Does it fix a defect or restore expected behaviour? | **Fixes** |
| Is it operator-invisible — pure refactor, test hardening, internal docs, dependency bump? | **Internal** |

Judgment notes:

- **Highlights is a quality bar, not a quantity.** Five highlights means you're padding; demote to Features/Improvements.
- A merge appears in two buckets only when one of them is Deploy notes. Otherwise pick the primary operator impact.
- "Decommission X" / "retire Y" / "remove Z" is usually Deploy notes even when the user-visible message is just "fewer endpoints".
- ADR commits and spec/plan docs are Internal, unless they encode a behaviour change operators need — then categorise by the behaviour, not the doc.
- **Don't synthesise from the merge subject alone.** Subjects look like `merge: <slug> — <terse desc> (issue-N → <integration>)`; the operator-facing meaning lives in the PR body and the diff.

## Step 3 — Write each entry

**One short sentence, imperative voice, operator-facing meaning, PR link.** The project's worked
examples (entry rewrites, synthesis, bump calls) live in the project hints (`projectHints` directory
→ its `changelog.md`); read them now if present.

| Bad | Good |
|---|---|
| `c7d3002a merge: <slug> — <terse desc> (issue-N → <integration>)` | `<What changed, in the words an operator would search for> — <the consequence they'd notice> ([#N](https://github.com/<repoSlug>/pull/N))` |
| `Various fixes and improvements` | (delete; if you're tempted to write this, you haven't read enough merges yet) |

- Lead with the *change*, not the issue number.
- Use the words an operator would search for — feature names, endpoint paths, env var names, table names. Not internal class names unless they're the user-facing surface.
- Link the PR inline with the **full URL**, never a bare `#N` — many forges auto-link a bare `#N` against the wrong repo under cross-references.
- Link ADRs when relevant: `[ADR-<slug>-NNN](docs/areas/<slug>/adr/NNN-<kebab>.md)`, cited by full id. In a legacy repo with a central ADR directory, use `docPaths.adrDir` and that repo's own id form instead. Skip when the repo keeps no ADRs.
- Don't include the SHA; the PR link is enough.
- One PR that shipped two distinct operator-visible changes gets two entries linking the same PR.

## Step 4 — Top-of-body synthesis

Open with a 2–4 sentence prose summary themed around the 2–3 threads that organise most of the release — the executive summary an operator reads before drilling into the categorised list. Shape:

> This release lands `<theme 1: the marquee capability, with its sub-parts named>`, retires `<theme 2: the concept removed, and how far it went>`, and tightens `<theme 3: the surface hardened>`. Plus the usual hardening across `<area>`.

Tone: factual, not promotional. No "exciting new", no "we're thrilled" — operators want signal, not enthusiasm. `Merged 57 PRs from <integration> — see list below` is not a synthesis.

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

- [#N](https://github.com/<repoSlug>/pull/N) — <merge subject verbatim>
- ...
</details>

## Verification (post-merge)
- <when deploy.adapter != none: per-service running-commit check — the latest deployment's status is the platform's SUCCESS value AND its commit starts with the merge SHA. See deploy.watchDoc for the exact command.>
- A health probe returning 200 is *not* proof — verify the running commit equals the merge SHA at a SUCCESS status (SKILL.md Phase 5).
```

Skip an empty section rather than writing "## Fixes\n*none*" — absence reads fine. When `deploy.adapter == none`, drop the Verification section's deploy lines and keep only the merged+tagged record. The collapsible raw list preserves the exhaustive record for future debugging without cluttering the operator-facing read.

## Quality check before opening the PR

Re-read the assembled body and ask: could a teammate tell what landed in 90 seconds (top synthesis + Highlights)? Could an on-call engineer tell which PR to suspect for a given regression (category-by-impact structure)? Is everything in Deploy notes already reflected in the deploy env / schema state — and if not, fix that *before* merging? Is Highlights down to the things that deserve it? Any `Various` / `Misc` phrasing left, which means you haven't finished reading the merges?

Any "no" or "not sure" → iterate before opening. The body becomes the merge commit's permanent record; cheaper to fix now than in `git log --grep`.

## Anti-patterns

- **The flat SHA dump.** Subject lines copied verbatim with their `issue-N → <integration>` suffix. The raw collapsible is the only place that format belongs.
- **Headlining everything.** Ten highlights means none of them are highlighted.
- **Confusing process with content.** "ADR-NNNN implemented" is not an entry; what the ADR *made the system do* is. The ADR is the why, not the what.
- **Padding with internal churn.** A dependency bump in Highlights signals you're filling space.

## Version bump signals

Feeds [`SKILL.md` Phase 4.5b](./SKILL.md#45b-decide-major--minor--patch): the same buckets that produced the changelog drive the semver bump. Walk top-down, **stop at the first matching rule**.

| Bucket evidence | Bump |
|---|---|
| `## Deploy notes` has at least one entry requiring *operator action to upgrade* that is *not backward-compatible*: an env var the app rejects on missing; a migration dropping a column/table with no shim; an endpoint/contract change with no compat path; an ADR marked breaking. | **MAJOR** |
| `## Highlights` or `## Features` has at least one new operator-visible capability. | **MINOR** |
| Only `## Improvements`, `## Fixes`, `## Internal`, or non-breaking `## Deploy notes` (additive env vars *with defaults*, additive migrations, telemetry-only changes). | **PATCH** |

**Pre-1.0 caveat.** While `PREV_TAG` is `0.x.y`, the table shifts down one slot: MAJOR-class evidence yields a MINOR bump (`0.MINOR.0` → `0.MINOR+1.0`); MINOR and PATCH map to themselves. Per the [semver §4 unstable-release convention](https://semver.org/#spec-item-4) — pre-1.0 explicitly disclaims API stability. The 0.x → 1.0 promotion is a separate operator decision, not driven by this rubric.

Worked example (MAJOR on the 1.0+ track; the other buckets follow the same reading):

```
## Deploy notes
- New required env var `<Key>` — the app refuses to start without it. Set it before deploying.
- Migration drops `<table>.<column>` — no shim; downstream consumers must read `<replacement>`.
```
→ A required env var with no default plus a schema drop with no shim: two entries needing operator action to upgrade, neither backward-compatible. Bump = **MAJOR**. On a `v0.x` predecessor the same evidence yields **MINOR**.

When the rubric is ambiguous:

- **Both breaking-deploy and feature** → MAJOR wins. Operators needing to coordinate before the upgrade dominates "we also added a thing".
- **A flipped feature-flag default** → the test is operator-visibility. Anyone on default config seeing a different shape after the upgrade = MAJOR. Behaviour that requires opting in = MINOR plus a Deploy notes mention.
- **A NOT NULL column added with a backfill default** → MINOR, with the backfill timeline in Deploy notes. Compatible from the application's side, but downstream consumers querying the column directly see nothing pre-migration.
- **In genuine doubt, propose the higher bump** and show the reasoning. Over-bumping costs one tag; under-bumping ships a break the operator wasn't warned about. The cost is asymmetric.

Whether release notes carry an AI-assistance trailer follows `commit.coAuthoredBy` (default: include).
