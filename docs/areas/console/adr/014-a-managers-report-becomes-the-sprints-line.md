# ADR-console-014 — A manager's report becomes the sprint's line

- **Status:** accepted
- **Decided in:** #833, #835, #837, #838, #890

## Context

ADR-console-013 carried a manager's brief to the page and the owner's approval back, and then the sprint read "starting" and said nothing more. #835 decided that the manager reports in a fixed shape after each batch and on any change of state, and that the run journal fills in the stage between reports. #833 and #837 decided that the owner reads one plain line per sprint, with issue numbers, branches and session names kept out of it, and that a sprint is quiet, never stalled, without a positive signal. #838 item 8 keeps reports indefinitely. This slice carries a manager's report to the page and folds it, with the runs that follow it, into the sprint's line.

## Decision

A manager uses `sprint report` to send its report. `POST /api/report` takes the sprint id, the sprint's secret and the report. Like `POST /api/brief` it is a manager write, not a page write: it carries no token, the sprint's secret takes the token's place, and any `Origin` is refused (ADR-console-008, ADR-console-013). It refuses in this order: the sprint is not open, then `secret refused`, then the brief not approved, then the first of the seven members that is missing or invalid, then a status line that names an issue number. A refusal records nothing, and the answer to a wrong secret is the one text `secret refused`.

A report has seven members: the status line, the phase (`running`, `closing` or `done`), the milestone, the tracker link, the issues with their stages, the inbox items it raised (issue numbers) and the next step. A newer report replaces the one before it. Report rows (`sprint.reported`) are kept indefinitely and the store moves to schema 5 to protect them (ADR-console-009, #838 item 8).

A sprint has one state, the first that holds: no approved brief reads "drafting the brief"; a report whose phase is `done` reads "done"; something waiting on the owner reads "waiting on you (n)"; no movement for fifteen minutes reads "quiet for N min — may be stuck"; a report whose phase is `closing` reads "closing"; an approved brief with no report reads "starting"; anything else reads "on track". Movement is the latest of the approval, the report and a run that carries one of the report's issues. A sprint is quiet after fifteen minutes of that and is never "stalled": a slow step and a dead one cannot be told apart, and #837 item 3 keeps "stalled" for a positive signal (ADR-console-005).

Between reports an issue follows the run. The console folds the `delivery.seen` rows that came after the report into the newest observation of each reported issue, because a run leaves the live list as soon as its final record exists (ADR-console-005); the last stage is kept after the run leaves, until the next report clears it. A reported outcome (`landed` or `held`) is kept against any run. A run's close-out reads "closed out" until the manager reports landed or held, because a close-out held for verification looks the same as one that landed. The progress counts follow these effective stages. Waiting counts the open inbox items on the report's issues or its inbox list; held counts the issues the manager reports held, which is how a held verification shows in a sprint's progress (#837 item 6).

The digest says one sentence only when the reported phase changes. Issue numbers, branches and session names appear only behind the "Detail" fold on the sprint's line, with the tracker link last (#833, #837 item 2).

## Consequences

- A done sprint stays shown until its goal is withdrawn.
- A quiet sprint is not pinged yet: #837 item 3's ping is later work, and the line only says so.
- A change to quiet or to waiting makes no digest sentence; only a change of the reported phase does.
- A close-out reads "closed out" until the manager's next report says landed or held.
- A restart after 90 days without a report loses the older run observations (ADR-console-009, the `delivery.seen` rows are not kept), and the sprint shows the report's own stages.
- A manager that holds the secret can report any stage it likes: loopback trust is the boundary (ADR-console-008).
