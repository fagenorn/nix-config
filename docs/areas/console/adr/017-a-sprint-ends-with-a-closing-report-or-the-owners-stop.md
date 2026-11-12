# ADR-console-017 — A sprint ends with a closing report or the owner's stop

- **Status:** accepted
- **Decided in:** #834, #928, #892

## Context

ADR-console-014 left a done sprint on the page until its goal was withdrawn, and ADR-console-016 left the manager's background session running after a withdrawal. A finished sprint therefore never folded away, the owner had no way to end one that was going wrong other than withdrawing it, and each withdrawal left an idle session spending quota. #834 decided that the owner can always end a sprint; #928 gave the console's checks one shared way to stop a manager's session. #892 makes a sprint end in one of two ways, the manager's closing report or the owner's stop, and makes both visible.

## Decision

**The closing rule.** A manager ends a sprint with `POST /api/close`, a manager write like `POST /api/report` (ADR-console-013): the sprint's secret replaces the token and any `Origin` is refused. The closing report is `{"summary", "issues": [{"issue", "stage"}], "differently"}`. It is refused with `an issue of this sprint is neither landed nor dropped` unless every issue named in the sprint's latest report is listed with a stage of `landed`, `held` or `dropped`. A held issue is merged and held for verification, so `held` counts as landed; an issue is dropped only by being listed as `dropped` in the closing report. The summary's first line is one plain sentence with no issue number: it is the sprint's line and the digest's.

**The stop is one stored message.** `POST /api/stop` is a page write under ADR-console-008. It stores `sprint.stop_requested`, which makes exactly one message of kind `stop` with a fixed text (a second stop of the same sprint is refused). The message is read through `sprint inbox` and nudged like every message of ADR-console-016, so the owner's words still travel only through the inbox. A manager that gets it finishes what is mid-merge, starts nothing new and sends a closing report that lists every unfinished issue as `dropped`; that closing report is accepted without the coverage rule and without an approved brief. The sprint reads "stopping" until it ends.

**The ten-minute timeout.** A stop ends the manager's session when its closing report arrives, or after ten minutes (`STOP_WAIT_MS`) without one, whichever comes first. The session poll finishes it; the owner is never left waiting on a manager that cannot answer.

**One session stop, shared.** The stop of the session is the shared stop of #928 (`manager.stop_listed`, `claude-account run stop <short id>`), run off the lock. The completion is `manager.stopped`; a failed attempt is `manager.stop_failed`, retried by the session poll once a minute has passed. A host without a stopper (not Linux) runs no managers: an open sprint's due stop is recorded without a call and a withdrawal stops nothing.

**Launch, nudge and stop never overlap.** One sprint's launch, nudge and stop each hold a reservation that excludes the other two, as launches and nudges already excluded each other. A stop waits for a launch or wake in flight and the poll takes it after. A stopped manager is never woken, nudged or relaunched: its message box and its retry are gone. A stopping manager is still nudged, so its stop message reaches it, never while its stop runs.

**Withdrawal stops the session.** Every `goal.withdrawn` row without a later `manager.stopped` is a pending stop, so withdrawals made before this decision have their leftover sessions stopped on the first start after it. A stop that finds no listed session within thirty seconds of the sprint's last launch or wake is retried rather than recorded, because a just-started background session may not be listed yet; after that window an empty listing means there is nothing to stop.

**Kept kinds, schema 7.** The store moves to schema 7 (ADR-console-009). `sprint.closed`, `sprint.stop_requested` and `manager.stopped` are kept kinds: retention deletes other rows older than 90 days before the fold at construction, and `manager.stopped` alone sets the stopped time and ends a withdrawal's pending stop, so an unkept one would reopen a finished stop on a restart. It is bounded to one per stop. `manager.stop_failed` is not kept, like the manager rows of ADR-console-015: it is an observation, a failing retry may append one a minute, and losing one only drops a shown reason and makes the next retry due at once.

**Every route to done ends a sprint the same way.** A report of phase `done` stays a route to "done" (ADR-console-014); stored reports carry it. It ends the sprint at the report's time and folds like a closing, which moves the end to its own time when one is sent later. A stop overrides both.

**The fold.** An ended sprint, done or stopped by you, folds into its project's "Finished sprints" a day (24 h) after it ended, and a finished sprint does not make its project active. With no clock nothing folds. A plain closing report does not stop the manager's session: only the owner's stop and a withdrawal do, so a done sprint's idle manager stays until it is withdrawn.

The digest says one new sentence, that the sprint for a project is done with the summary's first line; a stop makes no sentence. The page confirms a stop with a second in-page button, never `window.confirm` (ADR-console-002).

## Consequences

- ADR-console-014's "A done sprint stays shown until its goal is withdrawn" no longer holds: an ended sprint folds into Finished sprints a day after it ends, and is shown until then.
- ADR-console-016's "a withdrawal ... does not end the session" no longer holds: a withdrawal stops the manager's session. Its other statements stand, among them that a verification check must stop its test manager first, which now leaves the withdrawal's own stop with nothing listed to stop.
- The manager's contract gains an `Ending` section; it is not in the instruction corpus (ADR-console-015), so there is no Instruction Budget raise.
- A sprint stopped by the owner cannot be resumed: the owner states a new goal.
- A closing report cannot be amended once sent: the sprint has ended.
