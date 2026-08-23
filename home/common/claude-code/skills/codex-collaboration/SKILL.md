---
name: codex-collaboration
description: Run a private, isolated Codex pass — plan-review (from-issue Phase 5) or diff-review (the diff review's correctness axis) — and disposition its findings.
user-invocable: false
---

# Codex Collaboration

Support two operations; each owns a reference file read when that operation runs:

- **`plan-review`** (from-issue Phase 5) — reviews the implementation plan for
  conformance to the issue, spec, docs, and coding bar. Packet, reviewer
  contract, and finding disposition in [PLAN-REVIEW.md](./PLAN-REVIEW.md).
- **`diff-review`** — the correctness axis of the two-axis diff review. The sdd
  skill defines the axes and dispatches the parallel native conformance axis
  itself; that axis never comes through this skill, and the correctness axis is
  never skipped. Packet, output contract, and disposition in
  [DIFF-REVIEW.md](./DIFF-REVIEW.md).

Both operations share this file's runtime contract — resolve policy, read-only
rules, pre-flight, one foreground transport dispatch, validation, and the
one-time native fallback. Keep Codex review-only and keep the parent Claude
agent responsible for every plan edit and disposition.

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

## Read-only rules (both operations)

Include these verbatim in substance in every packet:

- Remain read-only. Do not edit files; mutate Git; create commits, branches, or
  worktrees; change issues or PRs; install dependencies; or perform shipping
  actions.
- Use read-only repository and Git inspection only. Do not transfer a Claude
  transcript, and do not review outside the assigned scope.
- Inspect the live files at HEAD. Paths and summaries are routing context,
  never substitutes for reading the worktree.
- A limitation of your own execution environment is never a finding. The sandbox
  is `read-only` and denies every write, `TMPDIR` included, so test runners,
  mutation checks and anything else needing scratch space cannot run here and are
  not expected to. Report what you could not verify where you already report what
  you could not read, and in each finding's unresolved unknowns field — never as
  a `Blocking` / `Should fix` / `Critical` / `Important` / `Minor` item. A defect
  in the artifact under review is still reportable when a failed command is what
  exposed it; anchor it in the artifact with evidence, not in the transcript of
  the denial.

## Launch

Capability pre-flight first, one sub-second call: `command -v codex-companion`. If
the command is missing, take the capability fallback above — use the native
reviewer flow immediately and record it as such. Never convert a missing
runtime into a timed-out Codex attempt.
An operation may define an additional pre-flight of its own in its reference file —
`diff-review` defines a size pre-flight in DIFF-REVIEW.md — and that one always runs
after this capability check.

Every invocation of an operation pre-flights fresh and gets its own attempt.
"Codex already failed earlier in this run" is not a reason to
skip the capability pre-flight or go straight to native: the no-retry rule
scopes to a single operation invocation, not to the pipeline or the session.
An operator or dispatcher advisory does not narrow this contract — if skipping
is right, the caller records the deviation as such rather than treating the
advisory as the rule.

Build the operation's packet per its reference file, then dispatch the plugin
agent once with the complete packet using this transport selection:

<!-- agent-dispatch: id=codex-review-transport role=codex-transport model=sonnet effort=medium -->
Agent(subagent_type="codex:codex-reviewer", model="sonnet", effort="medium") transports the complete review packet to the isolated Codex runtime.

Run it in the foreground, with the first two lines of the dispatch exactly, in
this order:

`WORKTREE_ROOT: <absolute worktree root>`
`REVIEW_OPERATION: <plan-review|diff-review>`

Here `<operation>` is the operation currently being invoked. The first line lets
the bridge key runtime job state to the reviewed worktree, and the second
preserves the operation across the detached transport. Launch mechanics live
solely in that agent's definition. This selection changes only the Claude
transport tier; it does not select or change the external Codex runtime model.
The contract: the review runs
fresh in an isolated read-only Codex runtime (fresh `CODEX_HOME`, approval
policy `never`, sandbox `read-only`), survives the bridge's own lifetime, and is
bounded by a per-operation runtime budget — expect up to
roughly 28 minutes of wall clock for `plan-review` and
roughly 14 minutes for `diff-review`.
The bridge returns the reviewer's output verbatim, or a single
`CODEX_REVIEW_FAILURE:` line carrying the review job's recorded error.

Parallel reviews are valid. A queued or active review is never a reason to use a
Claude fallback. Wait for the requested job. The patched reviewer runtime does
not share a broker with interactive commands or with another reviewer.

Live bridge certification evidence — needed only when certifying that deployed
bridge definitions are current — lives in [CERTIFICATION.md](./CERTIFICATION.md);
it changes none of the contracts in this file.

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

Give it the read-only toolset matching from-issue Phase 5 step 3, the same
packet, and the same read-only/output contract. Do not ask that fallback
reviewer to imitate Codex. Record the concrete failure class and that Claude
fallback was used. Do not retry Codex and do not fall back because of
concurrency.

## Disposition

`plan-review`: the parent Claude agent verifies and dispositions every finding
per PLAN-REVIEW.md before returning control. `diff-review`: return the validated
result unmodified to the calling controller per DIFF-REVIEW.md.
