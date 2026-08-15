# Operation: `diff-review`

Read this when running `diff-review` — the correctness axis of the two-axis diff
review (the sdd skill defines the axes and owns dispatching the parallel native
conformance axis — that axis never comes through this skill). SKILL.md owns the
shared runtime contract: resolve policy, pre-flight, packet by paths,
`WORKTREE_ROOT:` first line, one foreground `codex:codex-reviewer` dispatch,
validation, one-time native `reviewer` fallback on a real Codex failure, never a
retry, concurrency never a fallback reason. The axis is never skipped.

## Packet

**The `diff-review` packet replaces PLAN-REVIEW.md's packet wholesale** — it is
not that packet plus tweaks. It contains exactly:

1. The operation name, invocation directory, worktree root, current branch, and
   the base and head SHAs of the diff under review.
2. Scope line: review the diff `<base-sha>..<head-sha>` in the worktree for code
   correctness — bugs, boundary error handling, dead branches, assertions that
   fail to pin the documented contract, DRY against existing helpers, cross-task
   integration. Conformance to issue/spec/docs is the parallel axis's job;
   instruct the reviewer not to grade it.
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

## Reviewer output contract

First line is the axis verdict (`**Correctness:** Clean | Findings — 1–2
sentences`), then exactly three top-level sections `Critical` / `Important` /
`Minor` (must-fix-before-merge / should-fix / nice-to-have), ≤400 words total,
every finding with a stable ID, live `path:line` evidence, confidence (`high` /
`medium` / `low`), and unknowns (`none` when empty); `None.` under an empty
section; unreadable artifacts reported explicitly.

## Disposition

Verify-and-disposition stays with the calling controller and its own fix-flow
rules: return the validated three-section result (or the fallback reviewer's)
unmodified, plus the reviewer identity (`Codex` | `Claude fallback` + failure
class) for the caller's ledger.
