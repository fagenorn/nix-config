# Phases 6–7 — CI escalation and merge quirks

Read this when Phase 6's CI wait escalates or fails, or when Phase 7's merge
exits non-zero. Exit-code handling lives in SKILL.md's Phase 6.

## Escalation after 40 minutes

After the eighth `124`, GitHub Actions webhooks may have failed to fire;
escalate with:

"PR #<n> has been pending for ~40 min with no terminal CI state. Options:
(a) wait another 10 min, (b) close+reopen to re-trigger checks, (c) merge
without CI if the project allows admin-merge, (d) abort and investigate
manually."

## Failing checks

Pull `gh run view <run-id> --log-failed`, ground against the failing surface
(lint → standards doc, test → area spec/plan), surface.

## Advisory overflow

When the advisory list does not fit the shared notes bound, end it with
`+<n> more`, and keep a non-null `report_path` named first. Under lifecycle
identity the line goes in the legacy row's `notes`, which `ship-summary/v2`
carries as `historical_owner_result`.

## Merge exit code in a worktree

`gh pr merge` runs local post-merge steps (check out the default branch, delete
the local branch) that fail with `failed to run git: fatal: '<branch>' is already
used by worktree at '<main-root>'` — a non-zero exit **after the merge already
landed on the remote**. Retrying the merge or reporting failure on that exit
code is wrong; run Phase 7's verify first, and treat the exit code as
meaningless until it disagrees with `gh pr view`.
