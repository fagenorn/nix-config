---
name: to-issues
description: Splits a plan, spec or PRD into independently grabbable tracker issues as tracer-bullet vertical slices. Use to turn a plan into implementation tickets.
---

# To Issues

## Project bindings (resolve first)

Run `resolve-project resolve --repo-root <checkout>`. Resolve once at phase entry, retain the returned `ResolvedProject` in memory, and treat every resolver error as fatal before mutation or external effects. On refusal, preserve and report the resolver's `error.code`, `repair_id`, and ordered `violations` exactly; never translate it into a partial snapshot or fallback. Use `bindings.tracker` and `bindings.paths`; required blocked capabilities stop, and authored unsupported takes its documented tracker-free route.

`bindings.tracker.{kind,cli,repo_slug,credential_env.unset_before_invocation}` say where and how issues are filed. An authored unsupported tracker, or `kind: none`, means no publishing: emit the slices as a Markdown list, one template block each, for the user to file. A blocked tracker stops the forge operation.

## Process

### 1. Gather context

Work from the conversation. Given an issue reference, fetch and read its full body; load the comment thread only when the body points to a discussion, shows review activity, or leaves a question open.

### 2. Explore the codebase

Explore if you haven't. Titles and descriptions use the terms of the retained `bindings.paths.context` and the knowledge capability's passed records (an authored unsupported knowledge capability takes its no-knowledge route). Look for prefactoring that makes the change easy; it is its own leading slice.

### 3. Draft vertical slices

First read the retained `bindings.paths.rejections` entries in authored order. Never propose a slice that re-litigates a rejected direction; cite the rejection path instead. Only the user revives one.

Each issue is a **tracer bullet**: a thin vertical slice through every integration layer, never a horizontal slice of one layer. Mark each slice human-required (needs a person's decision, review, credential or approval) or autonomous, preferring autonomous.

<vertical-slice-rules>
- Each slice delivers a narrow but COMPLETE path through every layer (schema, API, UI, tests)
- A completed slice is demoable or verifiable on its own
- Each slice fits one fresh context window
- Any prefactoring is its own slice, and comes first
- Prefer many thin slices over few thick ones
</vertical-slice-rules>

A wide refactor (one mechanical change with codebase-wide blast radius) cannot land green as a tracer bullet: sequence it per [WIDE-REFACTORS.md](./WIDE-REFACTORS.md) when such a candidate appears.

### 4. Quiz the user

Present the breakdown as a numbered list with each slice's **title**, **type** (human-required / autonomous), **blocked by**, and **user stories covered** when the source has them. Ask whether the granularity, dependencies, merges or splits, and human/autonomous marks are right. Iterate until the user approves.

When the user rules a direction out (not merely defers it), write one short file per rejection to an authored `bindings.paths.rejections` location (the idea in a line, why, the date, any link) and commit it with the breakdown. An empty or unsupported list has no write route.

### 5. Publish

Publish each approved slice with the template below, blockers first so "Blocked by" cites real identifiers. Apply a triage label only when a label taxonomy was given or configured; otherwise skip it and say so.

Record blocking edges natively where the tracker supports it:

- **GitHub**: `gh api --method POST repos/<owner>/<repo>/issues/<child>/dependencies/blocked_by -F issue_id=<blocker-db-id>`. **`issue_id` is the blocker's numeric database id** (`gh api repos/<owner>/<repo>/issues/<n> --jq .id`), not its `#number` or `node_id`: a number silently links the wrong issue or fails. Read open blockers back from `issue_dependencies_summary.blocked_by`.
- **GitLab**: `glab issue note <child> --message "/blocked_by #<blocker>"`; the free tier lacks native links, so the body section is the record.

Without a native relationship the template's "Blocked by" section is the record. A slice is unblocked when all its blockers are closed.

<issue-template>
## Parent

A reference to the parent issue (omit when the source was not an issue).

## What to build

The slice's end-to-end behavior, not layer-by-layer steps. No file paths or code, except a prototype snippet that pins a decision better than prose (state machine, reducer, schema), trimmed to its decision and marked as from a prototype.

**Demo:** one line: what a reviewer can run, see, or click when this slice lands.

## Decisions

One line per decision this slice depends on (ADR, wayfind ticket, spec section) with the answer's gist. Omit when none apply.

## Acceptance criteria

- [ ] [code] <observable outcome> — measured: <the test, check or CI job that observes it>
- [ ] [evidence] <observable outcome> — measured: <command>, <conditions it runs under>, <literal threshold>
- [ ] [human] <observable outcome> — measured: <who judges, in what environment>

## Blocked by

- A reference to the blocking ticket (if any)

Or "None - can start immediately" if no blockers.

</issue-template>

Write each criterion as `- [ ] [code|evidence|human] <observable outcome> — measured: <where>`:

- `code`: a test, the build or a CI job any reviewer reruns at the head.
- `evidence`: a measurement outside the gating suite: the command, its conditions and a literal threshold, such as `≤ 90 s per module, serial, idle mbp`, never "faster".
- `human`: who judges, in what environment; only when no agent can observe it.

Prefer `code`, then `evidence`. The `measured:` clause is the only place the body names a test, file or command.

The body is the contract, read weeks later in a fresh context: behavior and outcomes, no file paths outside `measured:`, no line numbers, no "as discussed above"; what an implementer needs lives in the body or a linked artifact, never only in a comment.

Every criterion must be falsifiable: name the `measured:` observation that would show it false, and confirm by hand that it fails at the commit the implementer starts from; a criterion already true there lets the issue be "completed" as a no-op. Also reject a criterion only another slice's work can satisfy, and one that restates the request instead of deriving from the artifact.

Do NOT close or modify any parent issue.
