# ADR-console-044 — A manager posts, lists and withdraws short notices for its project

- **Status:** accepted; amended by ADR-console-051
- **Decided in:** #1117

## Context

The console runs several sprints of one project at once, each with a manager of its own. They touch the same files and contracts, and nothing tells one manager what another is doing: the owner relays claims ("I am reworking this page"), heads-ups ("this command is changing") and hand-offs ("this is yours now") by hand today. A manager needs a short, bounded way to say it to the project's other managers and to the owner, and to read what they said, without a new place to keep it and without anything that could block work.

## Decision

**D1. Two kept kinds and schema 10.** A notice is one `notice.posted` row and its withdrawal one `notice.withdrawn` row. Both are kept kinds (ADR-console-009), because a notice dropped by the retention pass would change what a sprint folds to. Adding a kept kind is a schema step: the event log is at schema 10, and a store at schema 2 to 9 is migrated in place, keeping every event. An older build refuses a store migrated to schema 10, the same one-way step ADR-console-009 took before.

**D2. Three kinds and their bounds.** A notice is an object of a `kind` and a `text`: `claim` adds `what` and `until`, `heads-up` adds nothing, `hand-off` adds `to`. `text` is at most 280 characters, `what` at most 200 and `until` at most 140, each one line; a sprint has at most 5 open notices. Every bound is checked in one place, `sprints.checked_notice` for the notice and `postable_notice` for the sprint, and a bad notice is refused with the first bad member named, in a fixed refusal text that never echoes a key or a value the manager sent (ADR-console-019).

**D3. The routes.** `POST /api/notice` posts a notice, `POST /api/notices` lists the project's open notices and `POST /api/withdraw-notice` withdraws one of the sprint's own. All three are manager writes under the sprint's secret (ADR-console-013), listed in ADR-console-008 beside `POST /api/ask`; any `Origin` is refused, as for every manager write (ADR-console-008). Their bodies are at most 16384, 4096 and 4096 bytes.

**D4. A hand-off's addressee.** The `to` of a hand-off is `owner` or the id of another open sprint of the same project, never the sprint itself.

**D5. Who enforces what.** The service enforces the limit of open notices and the addressee under its lock, so two posts cannot both take the last place. The fold applies every well-formed row it reads and does not repeat those checks, so a log written by an earlier decision folds the same.

**D6. When a notice ends.** A notice ends when it is withdrawn, or when its sprint closes, is stopped (from the stop request) or is dropped, and no row says so: the fold marks it ended at the row that ended its sprint. An ended notice is no longer listed, and it stays ended if the sprint reopens (a newer brief or report after a done report). Withdrawing another sprint's notice, or one that has ended, is refused with the reason.

**D7. Information, never approval.** A notice informs; it never grants or denies. The console never refuses or blocks work because of a claim, and two overlapping claims are both accepted. A manager that reads a claim decides for itself.

**D8. Where a notice lives.** A notice is kept only in the console's log, never in the tracker, a commit or a pull request. This slice adds no digest moment, no page card and no recap member.

**D9. Who may post.** Posting needs an open sprint that has not ended or begun stopping. It does not need an approved brief: a manager announces a claim while its brief is still waiting.

**D10. No Instruction Budget raise.** The manager's contract says how to post, list and withdraw a notice. The contract is outside the instruction corpus (ADR-console-015), so the change needs no Instruction Budget raise.

## Consequences

- A store at schema 10 is not readable by an older build, so a rollback of the console needs the store of the older schema.
- A notice stays in the log for good, so a claim a sprint made is never lost to retention; what the manager lists is only the open ones.
- A claim is advice. Two managers can claim the same path, and the owner reads that from the list, not from a refusal.
- Related: ADR-console-008, ADR-console-009, ADR-console-013, ADR-console-015, ADR-console-019.
