# ADR-console-071 — A failed adoption commit shows its hook and last lines, and Cancel waits until it was shown

- **Status:** accepted
- **Decided in:** #1236

## Context

On 17 Nov an adoption commit failed inside a project's pre-commit hook. The adoption tool kept only the exit code, so the card said the adoption commit could not be made, with no hook and no reason, and Cancel registration removed the kept worktree before the owner could learn why. The hook needed the project's development environment, whose configuration was generated and untracked, so a second attempt could not be reproduced from the removed copy.

## Decision

**D1. The tool keeps the output and names the hook.** A failed commit keeps git's merged output (its last bytes, of those the last 40 non-blank lines) and the failing hook, read from git's own trace2 events and not by running a hook again, as `commit_output` `{hook, exit, lines}` on the error object and in the failure record.

**D2. The card words the hook and shows its last lines.** The headline names the hook and why it could not run, worded from its exit code (a missing command, a command that could not be executed, a hook that could not be started, or its exit status). The note is `HOOK_NOTE`. When the contract signs and the signing probe fails after a hook failed, the card keeps the signing reason, so `Turn signed commits off` stays offered, and its note names the hook and why (`hook_signing_note`). The card shows the last 8 lines after sanitizing: escapes and control characters removed, the worktree's own path made relative, any other absolute path cut to its last segment (after any non-word delimiter, URLs kept), long hex runs cut and a line that still matches the page pattern dropped. The lines are git's words, so they are held to ADR-console-035's page pattern and not to its plain-words rule.

**D3. No development environment in this slice.** The commit runs as before: the same arguments, no development environment entered, no hook skipped, never retried unsigned. A contract binding for running hooks in the project's development environment is follow-up #1249.

**D4. Cancel waits until the card was shown.** While the view carries a failed commit's evidence card (the one `register_apply` card of an `apply_failed` adoption with evidence, identified by its key) that no `/api/stream` client has been sent, Cancel registration is refused with `register.CANCEL_UNSEEN`, after the three existing refusals. A refused cancel appends nothing, runs no discard and keeps the worktree, its branch and its failure record. `GET /api/state` does not count as shown, and a new failure is a new card that needs its own showing. With no evidence card in the view (after Not now, or a failure with no evidence) Cancel is unchanged. The mark (`ConsoleService.delivered`, called by the stream after the frame was written) is in memory: after a restart the page receives the card again when it reconnects.

**D5. `adoption.step` gains `evidence`.** The member is `null` or `{hook, why, lines}`. A stored row without it reads as `null` and no row is rewritten.

## Consequences

- Amends ADR-console-035: a failure card may carry git's own lines, held to the page pattern.
- Amends ADR-console-037 D7: Cancel has one more refusal, `register.CANCEL_UNSEEN`.
- The owner always has a view of why the commit failed before the kept copy can be removed.
- The behaviour is pinned in `tests/test_console_commit_failure.py`.
