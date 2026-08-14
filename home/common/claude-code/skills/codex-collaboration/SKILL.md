---
name: codex-collaboration
description: Run a private, isolated Codex pass — plan-review (from-issue Phase 5) or diff-review (the diff review's correctness axis) — and disposition its findings.
user-invocable: false
---

# Codex Collaboration

Support two operations: `plan-review` and `diff-review`. Keep Codex
review-only and keep the parent Claude agent responsible for every plan edit
and disposition.

## Resolve policy

Read `<repo-root>/.claude/skills.config.json` when present. Resolve
`codex.planReview` as follows:

- Missing `enabled` means `true`.
- `enabled: false` means the project has opted out of Codex review passes entirely:
  return control so the caller uses its native reviewer flow — for either operation.
  Do not launch Codex.
- A non-empty `focus` adds project-specific emphasis without replacing the
  standard review bar.
- Continue to apply the existing `projectHints` binding when its file exists.

If this skill or the `codex:codex-reviewer` plugin agent is unavailable, the
caller uses the native reviewer flow. This is capability fallback, not a Codex
runtime failure.

## Build the review packet

Start from the invocation directory and resolve the canonical Git
workspace/worktree root. Build one self-contained delegation prompt containing:

1. The operation name, invocation directory, worktree root, current branch, and
   base SHA.
2. The issue title/body/URL, acceptance criteria, Phase-0 investigation summary,
   open questions and their dispositions.
3. Absolute paths to the approved specification and implementation plan.
4. Every applicable `AGENTS.md` and `CLAUDE.md` from the invocation directory up
   through the worktree root.
5. `.claude/skills.config.json` and `projectHints` when present, plus domain
   docs selected map-first, all by path, skipping absent files: the context map
   (`docPaths.contextMap`, else `docs/CONTEXT-MAP.md`, else legacy root
   `CONTEXT-MAP.md`) and only the area
   `CONTEXT.md` files whose `governs:` globs intersect the plan's touched paths
   or whose terms appear in the issue; ADRs only when cited by the issue, spec,
   plan, or a selected area file; the standards layers that apply —
   `~/.agents/standards/the-bar.md`, its `stacks/` shards matching the diff's
   file types, and the project's `docs/standards/` shards whose globs
   intersect. A worktree `GROUNDING.md` is a routing hint for this selection,
   never a substitute for it. Only when the project has no map, fall back to
   the `docPaths.{context,standards,architecture}` whole-doc paths.
6. Relevant manifests and inferred verification commands.
7. The configured `codex.planReview.focus`, when non-empty.
8. The absolute path to the caller's review contract (`REVIEW-CONTRACT.md`) —
   the common-miss checklist and coding bar travel by path, with concrete
   values supplied for every placeholder the contract names.

Tell the reviewer to inspect the live files at HEAD. Paths and summaries are
routing context, never substitutes for reading the worktree.

## Reviewer contract

(These rules are the `plan-review` reviewer contract; `diff-review` defines its own
output contract in its operation section below — the read-only rules apply to both.)

Include these rules verbatim in substance:

- Remain read-only. Do not edit files; mutate Git; create commits, branches, or
  worktrees; change issues or PRs; install dependencies; or perform shipping
  actions.
- Use read-only repository and Git inspection only. Do not transfer a Claude
  transcript or review the whole branch as a substitute for reviewing the plan.
- Review only for conformance to the issue, acceptance criteria, approved spec,
  live implementation context, project docs, and supplied coding bar. Do not add
  features or relitigate accepted scope.
- Return exactly three top-level sections: `Blocking`, `Should fix`, and
  `Discussion`. Write `None.` under an empty section.
- For every finding include a stable ID, the affected plan task or section,
  evidence with live `path:line` references, confidence (`high`, `medium`, or
  `low`), the required or suggested correction, and unresolved unknowns
  (`none` when empty).
- Explicitly report which supplied artifacts could not be read.

## Launch

Pre-flight first, one sub-second call: `command -v codex-companion`. If the
command is missing, take the capability fallback above — use the native
reviewer flow immediately and record it as such. Never convert a missing
runtime into a timed-out Codex attempt.

Dispatch the plugin agent once with the complete packet using this transport
selection:

<!-- agent-dispatch: id=codex-review-transport role=codex-transport model=sonnet effort=medium -->
Agent(subagent_type="codex:codex-reviewer", model="sonnet", effort="medium") transports the complete review packet to the isolated Codex runtime.

Run it in the foreground, with the first line of the dispatch exactly
`WORKTREE_ROOT: <absolute worktree root>` so the bridge keys runtime job state
to the reviewed worktree. Launch mechanics live solely in that agent's
definition. This selection changes only the Claude transport tier; it does not
select or change the external Codex runtime model. The contract: the review runs fresh in an isolated read-only
Codex runtime (fresh `CODEX_HOME`, approval policy `never`, sandbox
`read-only`), survives the bridge's own lifetime, and is bounded by the
runtime's internal ~14 min budget — expect up to ~15 minutes wall clock. The
bridge returns the reviewer's output verbatim, or a single
`CODEX_REVIEW_FAILURE:` line carrying the review job's recorded error.

Parallel reviews are valid. A queued or active review is never a reason to use a
Claude fallback. Wait for the requested job. The patched reviewer runtime does
not share a broker with interactive commands or with another reviewer.

## Validate and fall back

A valid result has the operation's required headings — a one-line axis verdict then
`Critical` / `Important` / `Minor` for `diff-review`; `Blocking` / `Should fix` /
`Discussion` for `plan-review` — and either `None.` or findings with evidence,
confidence, and unknowns. Treat only these as Codex failures:

- the executable is missing or authentication is unavailable;
- the agent returns `CODEX_REVIEW_FAILURE:` — the review job ended failed,
  cancelled, or timed out (including the runtime's hard timeout and
  dead-worker detection), with the job's recorded error on the line;
- the result is empty or malformed after one completed fresh run.

On a real failure, dispatch exactly one fresh Claude standards reviewer with the
same packet using:

<!-- agent-dispatch: id=codex-failure-fallback-review role=reviewer model=opus effort=high -->
Agent(subagent_type="reviewer", model="opus", effort="high") performs the one-time native standards-review fallback.

Give it the read-only toolset matching from-issue Phase 5 step 3 and the same
packet and the same read-only/output contract. Do not ask
that fallback reviewer to imitate Codex. Record the concrete failure class and
that Claude fallback was used. Do not retry Codex and do not fall back because of
concurrency.

## Verify and disposition

(Applies to `plan-review`. For `diff-review`, verification and disposition live with
the calling controller — see that operation's section.)

The parent Claude agent owns the result:

1. Re-open every cited live file and verify each finding. Reject findings whose
   evidence is stale, absent, or does not support the claim.
2. Apply verified Blocking findings to the plan. Apply verified Should-fix items
   in `--auto`; otherwise present them to the user. Raise Discussion items at the
   normal checkpoint, or apply the documented autonomous decision rule.
3. Preserve one `Auto-resolved decisions` entry per applied finding using the
   caller's required template. Never collapse several findings into one entry.
4. Add or update a concise `## Standards review provenance` section in the plan:
   reviewer (`Codex` or `Claude fallback`), base SHA, isolated/read-only mode,
   optional focus, counts accepted/rejected/deferred, and fallback reason when
   applicable.
5. Do not store the raw reviewer transcript in the repository, plan, issue, PR,
   or commit message.

Return control only after all accepted findings have explicit dispositions and
the plan is clean enough for the caller's Phase-5 checkpoint.

## Operation: `diff-review`

The correctness axis of the two-axis diff review (the sdd skill defines the axes and
owns dispatching the parallel native conformance axis — that axis never comes through
this skill). Same runtime contract as `plan-review`: resolve policy, pre-flight,
packet by paths, `WORKTREE_ROOT:` first line, one foreground `codex:codex-reviewer`
dispatch, validation, one-time native
`reviewer` fallback on a real Codex failure, never a retry, concurrency never a
fallback reason. The axis is never skipped.

**The `diff-review` packet replaces `## Build the review packet`'s list wholesale** —
it is not that packet plus tweaks. It contains exactly:

1. The operation name, invocation directory, worktree root, current branch, and the
   base and head SHAs of the diff under review.
2. Scope line: review the diff `<base-sha>..<head-sha>` in the worktree for code
   correctness — bugs, boundary error handling, dead branches, assertions that fail
   to pin the documented contract, DRY against existing helpers, cross-task
   integration. Conformance to issue/spec/docs is the parallel axis's job; instruct
   the reviewer not to grade it.
3. The caller's correctness rubric by absolute path (sdd's
   `correctness-reviewer-prompt.md`), with concrete values supplied for every
   placeholder it names.
4. The diff-package path when the caller built one, and the plan path (routing
   context for what the tasks were).
5. Inferred verify commands and every applicable `AGENTS.md`/`CLAUDE.md`.
6. The standards layers matching the diff's file types
   (`~/.agents/standards/the-bar.md`, its `stacks/` shards, project
   `docs/standards/` shards whose globs intersect).

Nothing else rides along: no issue investigation, no spec, no domain docs, no
`codex.planReview.focus`, no `REVIEW-CONTRACT.md`. The light packet is what keeps
Codex inside its runtime budget; domain conformance belongs to the other axis.

Reviewer output contract: first line is the axis verdict (`**Correctness:** Clean |
Findings — 1–2 sentences`), then exactly three top-level sections `Critical` /
`Important` / `Minor` (must-fix-before-merge / should-fix / nice-to-have), ≤400
words total, every finding with a stable ID, live `path:line` evidence, confidence
(`high` / `medium` / `low`), and unknowns (`none` when empty); `None.` under an
empty section; unreadable artifacts reported explicitly.

Verify-and-disposition stays with the calling controller and its own fix-flow rules:
return the validated three-section result (or the fallback reviewer's) unmodified,
plus the reviewer identity (`Codex` | `Claude fallback` + failure class) for the
caller's ledger.
