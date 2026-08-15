# Phases 6–7 — CI wait and merge mechanics

Read this when Phase 6 starts. It owns the rationale, retry/escalation scripts,
and merge quirks behind SKILL.md's Phase 6/7 rules.

## Why the blocking watch is shaped that way

```
timeout 300 gh pr checks <pr-num> --watch --fail-fast --interval 30
```

The 5-minute ceiling forces an assistant turn every ~5 min, which keeps the
subagent stream alive; the harness reaps a subagent that goes silent for ~9+ min
on a blocking Bash (which is what a 540s timeout produced). `--fail-fast` exits
on the first check to flip into a failing bucket, so failures surface without
waiting on parallel checks.

**Foreground only — do NOT background this.** No `run_in_background: true`, no
`Monitor`. The harness yields a subagent indefinitely when it sees a
long-running monitored background Bash and the subagent never wakes to issue the
next turn. The blocking foreground shape is correct: `gh` polls the API at the
network layer every ~30s while Bash blocks, costing zero model turns until it
returns.

**Why improvised polling is banned.** Transcript mining found one session that
ran a bare `gh pr checks <n> | grep <check>` 244 times, plus sessions burning
dozens of `gh run view` re-runs and `true`/`:`/`date` no-op keep-alive turns;
every such poll is a full model turn that re-reads the entire session prefix.
Never run `gh pr checks` without `--watch` more than once per phase, never
re-run `gh run view`/`tail` on a loop, never emit no-op commands to pass time.
For a single named check, still run the blocking watch and read that check's row
from its final output (or one `--json name,bucket` call afterwards).

## Exit codes

- **`0`** → all checks pass; continue to Phase 7.
- **`124`** (`timeout` fired) → still running past ~5 min. **Emit one short
  narration turn** (`CI: still pending at 5m, retry 2/8`) as the keep-alive, then
  re-run the identical command. Up to **8 times (~40 min)**. Still pending after
  that → escalate: GitHub Actions webhooks can fail to fire silently, leaving a
  PR indefinitely on "expected — Waiting for status to be reported". Prompt:
  "PR #<n> has been pending for ~40 min with no terminal CI state. Options:
  (a) wait another 10 min, (b) close+reopen to re-trigger checks, (c) merge
  without CI if the project allows admin-merge, (d) abort and investigate
  manually."
- **any other non-zero** → a check failed (or `gh` errored). Pull
  `gh run view <run-id> --log-failed`, ground against the failing surface
  (lint → standards doc, test → area spec/plan), surface.

**JSON-field note.** `conclusion` is not a valid field on `gh pr checks` — `gh`
rejects it (`--help` lists the real set). When you need structured output,
`bucket` (pass/fail/pending/skipping/cancel) is the cleanest decision field.

## Merge quirks (Phase 7)

**Do not pass `--no-ff`** — recent `gh` (≥ 2.83) rejects it
(`unknown flag: --no-ff`), and `--merge` alone already produces a true merge
commit (no squash, no rebase, no fast-forward).

**Why the exit code lies in a worktree checkout.** `gh pr merge` runs local
post-merge steps (check out the default branch, delete the local branch) that
fail with `failed to run git: fatal: '<branch>' is already used by worktree at
'<main-root>'` — a non-zero exit **after the merge already landed on the
remote**. Retrying the merge or reporting failure on that exit code is wrong;
run SKILL.md's verify first, and treat the exit code as meaningless until it
disagrees with `gh pr view`.

`--delete-branch` may fail or silently no-op on the remote branch while the
worktree still has it checked out; the remote merge still succeeds — hence
SKILL.md's `git ls-remote --heads` check (PR metadata like `headRefName` is
retained after deletion and proves nothing).

(`merged` is not a valid `gh pr view --json` field — use
`state`/`mergeCommit`/`mergedAt`.)
