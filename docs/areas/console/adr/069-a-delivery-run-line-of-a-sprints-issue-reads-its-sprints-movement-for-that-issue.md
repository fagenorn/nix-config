# ADR-console-069 — A delivery run line of a sprint's issue reads its sprint's movement for that issue

- **Status:** accepted
- **Decided in:** #1212

## Context

A delivery run line read only the run journal, so a run of a sprint's issue read "quiet for 45 min" while its sprint line read "waiting its turn to merge" for the same issue: the sprint line counted CI, commits, the land lock and session output (ADR-console-042, ADR-console-050, ADR-console-057, ADR-console-061), and the run line counted none of them (ADR-console-005). The two lines contradicted each other about one issue.

## Decision

**D1. Which run lines.** A run line reads its sprint's movement when the run belongs to a running sprint: the run carries an issue of the sprint's report or of its inbox, or the run is in the sprint's manager session (ADR-console-042 D3). A run belongs to the first such sprint, the sprint stated newest first. A run of an ended sprint, and a run of no sprint, keep the journal reading of ADR-console-005.

**D2. The reading.** The run's movement is the latest of its journal, the sprint's wait signals of the run's own issues (CI on its pull request, a commit on it or on its branch, a land lock wait or hold, a release step), and the output and a running check of its own session, the run's. A reply to the manager's idle nudge is left out, as ADR-console-057 D6. The line reads quiet when that latest time is fifteen minutes old. A signal of another issue or of another session does not count, so quiet means that nothing of the issue has moved.

**D3. The sentence.** When the waits alone move the line, that is, the journal and its own session are fifteen minutes old and a wait is not, the line ends with the wait's sentence instead of an age: the first of waiting for CI on its pull request, a delivery is committing, waiting for a release step, and waiting its turn to merge, in the order of ADR-console-050 D3 and ADR-console-061 D3. The page shows that sentence without an age. A merge refusal stays on the sprint line (ADR-console-048). The word "stalled" is never written.

**D4. The wire.** A delivery entry carries `wait_text`, the sentence or null, and null for a run outside a sprint. `reading_at` is the time of the reading of D2, which the page ages. `moved_at` keeps its earlier meaning, the run journal's own last movement, and `journal_at` repeats it, so a host check pinned to an earlier commit (the #1185 verification reads `moved_at`) still judges the journal alone. The check of this change (`movement_check`) reads `journal_at`, so a run moved only by the output of its session does not count as other movement of the sprint.

## Consequences

- This amends ADR-console-005 and ADR-console-042 D1: a run line no longer reads the journal alone, and the state line, the ball and a sprint's run lines now read one movement.
- A sprint waiting its turn to merge for 45 minutes shows no "quiet" on its run line: it ends with "waiting its turn to merge".
- A run whose session ended moves only by its journal and its issues' waits.
- Related: ADR-console-005, ADR-console-042, ADR-console-048, ADR-console-050, ADR-console-057, ADR-console-061.
