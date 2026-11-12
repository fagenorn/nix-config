---
name: ship-release
description: Releases the integration branch's verified tip through the release core — notes, version, one preview, then tag and GitHub Release. Use for "release", "ship to prod".
argument-hint: "[scope hint — seeds the release title]"
---

# Ship Release

The release core publishes `origin/<integration>`'s verified tip and holds all state; this skill prepares notes and version, shows one preview, then runs the core on the user's yes.

## Ownership

A delegating controller launches one owner for Phases 0–3:

<!-- agent-dispatch: id=ship-release-owner role=ship-owner model=opus effort=high -->
Agent(subagent_type="general-purpose", model="opus", effort="high") owns the release through the preview.

A direct invocation keeps the current session as owner; never split release ownership.

A delegated owner ends at the runnable preview, returning its arguments and confirmations. No agent message is the user's approval, so the controller, which holds it, runs Phase 4 itself (one run, then the background resume wait), which is no split.

## Project bindings (resolve first)

Run `resolve-project resolve --repo-root <checkout>`. Resolve once at phase entry, retain the returned `ResolvedProject` in memory, and treat every resolver error as fatal before mutation or external effects. On refusal, preserve and report the resolver's `error.code`, `repair_id`, and ordered `violations` exactly; never translate it into a partial snapshot or fallback.

`<integration>` and `<default>` are `bindings.vcs.integration_branch` and `bindings.vcs.default_branch`. Any `gh` call unsets the names in `bindings.tracker.credential_env.unset_before_invocation` first. The release command resolves the project itself; a resolver refusal from it is reported the same way (exit 2), and a driver refusal (`{"error":{"code","repair_id","detail"}}`, exit 3) as printed. Never work around either.

## Authorization

Invocation authorizes the reversible, predeclared steps: reading, notes, version proposal, land lock, preview. Each irreversible action needs its own confirmation token; the preview is the one stop for all. Only an explicit yes to all lets the run pass them, and only ones the user saw in that turn: tokens rotate on every resume, so a confirmation is never carried across one; silence or any other reply passes none. A standing release authorization the user gave in this session's own conversation (never relayed by an agent or inferred from a go-ahead for other work) replaces seeing them in that turn; the run still passes exactly its runnable preview's tokens. A changed version is a new target: preview again.

## Doc-grounded escalations

Before any user-facing question, invoke `doc-grounded-questions`, using only the retained snapshot's declared context, standards, architecture, and hint paths.

## Phase 0 — Pre-flight

1. Main checkout, not a worktree: `git rev-parse --git-common-dir` ends in `.git`; otherwise switch to it or surface.
2. Clean tree: `git status --porcelain` is empty. Surface changes; never stash.
3. `git fetch origin --prune --tags`, then local `<integration>` in sync with `origin/<integration>`: equal or absent continues; behind offers `git checkout <integration>` and, only if that succeeded, `git merge --ff-only origin/<integration>`; ahead or diverged is surfaced, never resolved.
4. Read the core's state:

```text
release transaction status --repo-root <main-checkout>
```

A nonterminal `release` (any state outside `succeeded`, `failed`, `rolled_back`, `abandoned`) goes straight to Phase 3 in resume form. A `legacy` class of `in_flight` or `unreadable`, or a `shape` refusal, is reported with its code and detail, not worked around; a legacy file is the user's call, and the driver never removes one.

5. Only with no nonterminal release: `git describe --tags --abbrev=0 origin/<default>` prints `<prev-tag>`, the previous tag; non-zero is the first release. Write the tag in (none: drop `<prev-tag>..`): `git log <prev-tag>..origin/<integration> --oneline` empty means nothing to release; report and stop. A shell variable does not survive between calls; never expand one.

## Phase 1 — Changelog

**Read [`CHANGELOG.md`](./CHANGELOG.md) first**: it owns the rubric and template. Assemble the body, the release notes, for the range `<prev-tag>..<commit>` (no tag: all of `<commit>`), where `<commit>` is `git rev-parse origin/<integration>`. Write it with the file-writing tool to `<notes-path>`, a path outside both working trees, and pass it by path (`worktrees/SKILL.md`, `## Shell forms the isolation checker refuses`). The title: one line under 70 characters synthesising the body. Create no tracked `CHANGELOG.md` unless asked.

## Phase 2 — Version

The previous tag, reachable from the released commit. Set `COMMIT=<commit>` in the same call:

```text
git for-each-ref --count=1 --merged "$COMMIT" --sort=-v:refname --format='%(refname:short)' 'refs/tags/v[0-9]*'
```

Its output is `<prev-tag>`; no output is the bootstrap case: surface the existing tags and propose **v0.1.0**, never `v1.0.0`. Otherwise apply the semver rubric in [`CHANGELOG.md`'s "Version bump signals"](./CHANGELOG.md#version-bump-signals); do not re-litigate the categorisation.

## Phase 3 — Preview

New release, or the resume form:

```text
release transaction preview --repo-root <main-checkout> --commit <commit> --version <version> --title "<title>" --notes-file <notes-path>
release transaction preview --repo-root <main-checkout>
```

Two-branch project: before the first preview, and again after opening the release PR, run alone (60-minute timeout) `forge-claim land acquire --repo <slug> --branch <integration> --sha <commit> --release --wait --follow-head`, where `<slug>` is `bindings.tracker.repo_slug`; resume form drops `--follow-head` and `<commit>` is the release's `commit`. On `head_moved`, `git fetch origin`, then redo Phases 1–2 with its `lock_sha` as `<commit>`. `no_open_pr` goes on to the preview, or in resume form before the merge is reported with an `abandon` offer. The confirmation stop and a `release_busy` stop keep the lock, and the run releases it; every other stop, a declined confirmation or a timed-out or killed acquire too, first runs `forge-claim land release --repo <slug> --branch <integration> --sha <commit>`, and after such an acquire also at the head from `gh pr view <integration> --repo <slug> --json headRefOid`.

On `release_pr_missing` (exit 3 still prints the document), open the release PR once with `gh pr create --repo <slug> --base <default> --head <integration> --title "<title>" --body "<version>"`. On `verification_pending`, wait once for CI in one foreground call: under the lock `gh pr checks <integration> --repo <slug> --required --watch --fail-fast --interval 60` (30-minute timeout; it can return early, so the re-preview judges), else `gh run watch <id> --exit-status` from `gh run list --commit <commit>` (at most 5 minutes). After either, re-run the same preview. Still pending, or another refusal: report it and stop.

When `runnable`, present the version with its evidence (its triggering buckets), the title, the commit, each action and every confirmation, and ask for one explicit yes to all, then end the turn. Tokens then stay stable if CI and the `<default>` tip are unchanged; never edit the notes.

## Phase 4 — Run

Once confirmed, run the latest preview's arguments with one `--confirm` per token:

```text
release transaction run --repo-root <main-checkout> --commit <commit> --version <version> --title "<title>" --notes-file <notes-path> --confirm <token> --confirm <token>
release transaction run --repo-root <main-checkout> --confirm <token>
```

Run from inside the main checkout. The result's `next`:

- `done`, or `attention` (parked; do not retry): go to Phase 5.
- `wait` (after a pause) or `confirm`: `preview` in resume form. No confirmation listed: run the resume form with no `--confirm`. Any listed: present them as in Phase 3 and end the turn; tokens from an earlier yes are never reused.

A `confirmation_stale`, `confirmation_required` or, after acquiring again, `land_lock_*` refusal is likewise a re-preview. `release_busy`: another session holds the release; report it.

Abandon only on the user's explicit word and when every action is `absent` (none took effect):

```text
release transaction abandon --repo-root <main-checkout>
```

## Phase 5 — Report

Report only from `release transaction status` and the run's `sync` and `lock`, not memory: `release.state`, `version`, `commit`, each action's `phase`, `status` and `reference`, and `receipt`. Only `succeeded` is released: for a parked release (`attention_required`) give its `reason` and offer resume (Phase 3 resume form) or, with every action `absent`, `abandon`. Never delete a tag; fix forward with a new version.
