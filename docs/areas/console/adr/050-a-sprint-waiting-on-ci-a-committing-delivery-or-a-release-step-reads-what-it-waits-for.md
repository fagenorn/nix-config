# ADR-console-050 — A sprint waiting on CI, a committing delivery or a release step reads what it waits for

- **Status:** accepted; amended by ADR-console-060
- **Decided in:** #1110

## Context

ADR-console-042 gave the state line, the ball, the "last seen" prefix and the digest one movement reading, built from a listed session working, the goal, the approval, the report and the sprint's runs. A sprint waiting on CI for its pull request, on a commit its delivery was making, or on a release moves none of those, so after fifteen minutes it read "may be stuck" while it was waiting on something the console could see. This decision lets those three waits move the sprint and say which one it is.

## Decision

**D1. The signals count at the time they were last seen.** CI on a pull request counts at the time it was last seen running, a commit at the head commit's `committedDate` or the branch's last reflog entry, and a release at the time it was last seen in progress, each under the same fifteen-minute window as the rest of the reading (ADR-console-005, ADR-console-042 D2). A signal that disappears, because its pull request merged or closed, its branch was deleted or its release finished, keeps the time it was last seen and is never refreshed, as movement outlives its run (ADR-console-042 D3). A reading is dropped only with its project, once no sprint of it runs.

**D2. A signal is the sprint's.** A pull request belongs to a sprint when its head branch carries, under the project's branch pattern, or its body names as `#<n>`, an issue of the report's `issues` or `inbox`, the same set ADR-console-042 D3 uses for runs. A local branch belongs the same way, by its branch pattern.

**D3. The wait is named only when it is what moves the sprint.** The now-sentence names the wait only when the movement reading without the three signals reads quiet and with them reads moving. The order is CI, then a committing delivery, then a release step: `waiting for CI on its pull request`, `a delivery is committing`, `waiting for a release step`. It comes after the owner and quota rules and before the starting rule and the stage phrase, except that a merge refusal the sprint shows (ADR-console-048) is read first: a refusal is what the owner needs to see, and a check or commit still inside the window must not hide it for up to fifteen minutes. A sprint with a shown refusal and a wait signal reads `merge refused: <reason>`. The state line, the ball and the "last seen" prefix follow the one reading, so none of them reads quiet while a sentence names a wait. The word "stalled" is still never written.

**D4. A release is in progress while its transaction is neither finished nor held for a person.** The state of a transaction under the release store is read from its `state.json`. It is in progress when it is a state of the release core's vocabulary that is neither terminal nor `attention_required`; a release parked in `attention_required` waits on a person and should let the sprint read may be stuck. A state outside that closed vocabulary, or a `state.json` that does not read, is an invalid reading: it never counts as in progress, refreshes no movement and is reported once on stderr as `console: movement_release_invalid <project_id> <transaction id>` until a good read discards the report.

**D5. One forge read per project with a running sprint every two minutes.** The service reads, on its own thread, one GraphQL call per project with a running sprint every two minutes, for at most fifty open pull requests, newest updated first, through the retries of ADR-console-032 D2 and D3, never inside the ingest lock. Closing the console cancels the read in flight: the `gh` process group is killed and the read raises `cancelled`, not after the transport timeout. A pull request's commit time never moves back: a rewritten head keeps the newest commit time seen, as the branch reading keeps the larger time. A failed or timed-out read keeps the last reading, whose signals age out after the window. Readings live in memory, not in the event log; a restart loses them and reads at once.

**D6. CI counts only while a check is queued or in progress.** The forge read counts the head commit's contexts by state (`checkRunCountsByState`, `statusContextCountsByState`), so a pull request with more than a page of checks is still read whole. A check run counts as CI running in `QUEUED`, `IN_PROGRESS` or `PENDING`, a status in `PENDING`. A check in `WAITING` is held on a person, such as a deployment environment waiting for a reviewer, and like `attention_required` in D4 it lets the sprint read may be stuck.

## Consequences

- A sprint whose only movement is CI on its pull request, a commit on its branch or a release in progress reads moving, and its line says which: `waiting for CI on its pull request`, `a delivery is committing` or `waiting for a release step`.
- A check held for a reviewer's approval moves nothing, so the sprint reads may be stuck once the window passes.
- A release left nonterminal keeps the sprint reading "waiting for a release step"; a parked release (`attention_required`) lets it read may be stuck.
- A release state outside the release core's vocabulary moves nothing and is reported once as `movement_release_invalid`.
- A merged pull request or a deleted branch keeps moving the sprint for the window after it was last seen, then stops.
- The forge costs one GraphQL point per project with a running sprint every two minutes.
- A restart loses the kept reading and reads at once; until that read answers, a sprint reads on the other signals alone.
- ADR-console-042 stays in force; its status line names this decision, and its D2 is read with D1 above.
- Related: ADR-console-003, ADR-console-005, ADR-console-032, ADR-console-042, ADR-console-048.
