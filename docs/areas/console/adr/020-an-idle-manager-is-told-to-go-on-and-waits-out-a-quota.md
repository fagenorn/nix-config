# ADR-console-020 — A manager idle while its sprint has work is told to go on, and waits out a quota

- **Status:** accepted
- **Decided in:** #837, #839, #891, #893, #929

## Context

ADR-console-017's Consequences leave "a manager that is listed but idle while work remains" to a separate slice: a listed manager is not gone, so the bring-back never touches it, and a sprint whose manager has stopped working but is still listed stops moving until the owner notices. #837 decided that a sprint reads stalled only on a positive signal, because a quiet sprint cannot tell a slow manager from a dead one. #839 decided that a limit stop is acted on only when the reset is more than 15 minutes away; a manager's session lives on one account, so it waits for that account's reset, and moving it to another account is out of scope here. ADR-console-016 gave the console one fixed sentence to send, never carrying the owner's words, and a stored message nudges at once. This slice tells an idle manager to go on, stops after a bound, and holds every send while the manager's account is out of allowance.

## Decision

**Idle.** A manager is idle when its manager row is `started`, the session carrying the sprint's manager name is listed in state `idle` or `limit`, and both the time of that session's last change and the time of its last activity are at least five minutes old. The last activity is the latest of the last movement of any delivery run of that session and the console's last launch, nudge or wake of the sprint. A run's movement outlives the run, so a run that moved and then ended still holds the nudge.

**Work.** The rule applies to a sprint with work in the sense of ADR-console-017 read without the clock: starting or on track, with a quiet closing sprint reading closing (#893). A sprint waiting on the owner, drafting, closing, done, stopping, stopped or withdrawn is never nudged, and neither is a stalled sprint or one whose no-progress item is open.

**Bounded.** Every idle nudge, delivered or failed, counts, and an accepted report or the owner's continue resets the count. A nudge is due ten minutes after the last one. When a nudge is due and three are already counted without a report, the console writes one `manager.no_progress` row instead and sends nothing more. The row raises one inbox item, `the manager has stopped making progress on <goal>`, carrying the report's status line when there is one, with two actions: continue and withdraw.

**Continue.** Continue is a page write, `POST /api/continue`, with the body `{"project_id", "sprint_id"}` under ADR-console-008 (the token and the origin). It is refused when the sprint is not open or when no no-progress item is open. It appends `sprint.continued`, which clears the item and resets the count, and sends one idle nudge at once: the five-minute idle time and the ten-minute spacing are skipped, every other rule holds. Withdraw is the existing withdraw.

**Quota.** A manager's account is out when the capacity reading of the profile its manager row names is out, that is, a refusal or a window that is out with its reset still ahead (ADR-console-006). While it is out nothing is sent to the manager: no idle nudge, no message nudge, the stop message included, and no wake of a stopped manager; a takeover is unchanged. This amends ADR-console-016's "A stored message nudges at once" and ADR-console-017's wake: a stored message waits and is sent by the re-nudge once the account is back, and a wake is not sent while the account is out. Every send reads the quota again under the lock after its listings and before the nudger runs, so a reading that arrives while the listings are read still holds the send. A sprint with work whose account is out reads `waiting on quota until <reset>`, in place of starting or on track and of quiet.

**Resume.** The first successful send after such a wait, whichever it is (a held message, an idle nudge or a wake), carries `resumed`, and the digest says `<goal> resumed after the quota reset` once, in place of the restart sentence for a wake. The idle nudge waits five minutes after any send, so a held message is the one send that resumes the sprint. A manager seen working while its account is not out, or a manager row that is no longer `started`, clears the wait without a sentence.

**Rows not kept.** `manager.nudged`, `manager.no_progress` and `sprint.continued` are observations like the manager rows of ADR-console-015: they are not kept kinds, the store stays at schema 8, and the `resumed` member rides on the existing `sprint.nudged` and `manager.woken` rows.

**The sentence.** The idle nudge is always a relay, on its own `continue` route: the manager is listed, and when a fresh listing no longer shows it nothing is sent or written, because the bring-back owns a gone manager. The sentence is fixed, as ADR-console-016 requires: `The console found you idle while your sprint has work. Run "sprint recap", then "sprint inbox", and go on with the next step.`

## Consequences

- An idle nudge costs one short print-mode relay on the manager's profile; three unanswered nudges cost at most three relays per report, and then the sprint is the owner's.
- A manager that cannot make progress shows as one inbox item with a way to push it on or end the sprint, instead of a sprint that sits quiet.
- A restart of the console forgets that a sprint was held for the quota, so the resume sentence is not said for a wait that began before the restart; the sends themselves resume as soon as the account reads available.
- A takeover during a quota wait is unchanged: it starts a new session on the best profile.
- A stored message left during a quota wait is delivered after the reset, not at once; the owner sees the sprint waiting on quota until the reset meanwhile.
