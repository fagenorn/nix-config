# ADR-console-042 — A sprint reads stuck only when nothing it reads has moved

- **Status:** accepted; amended by ADR-console-043
- **Decided in:** #1109

## Context

A running sprint's state line and its ball each read whether the sprint had moved, and they read it from different signals. The ball counted a working manager session; the state line did not. Only runs on issues the report named, and only those that moved after the report, counted as movement, and a new report cleared what had been seen before it. So a sprint read "nothing running, may be stuck" or "quiet for N min — may be stuck" while its manager was working, three times by 16 Nov. This decision gives the state line, the ball, the "last seen" prefix of the now-sentence and the digest one reading of movement.

## Decision

**D1. One reading.** The state line, the ball, the "last seen" prefix and the digest read one movement reading of a sprint: it is moving, or it has been quiet for so many milliseconds. The state line reads quiet, and the ball reads nobody, exactly when the sprint is not moving, and the prefix follows the ball. The precedence of the owner, drafting, waiting, quota, stopping and ended rules (#1086) is unchanged; only what counts as moving changes. The word "stalled" is still never written (ADR-console-005, ADR-console-014).

**D2. The signals.** A sprint is moving when a listed session of the sprint is working, or when the latest of the goal's stated time, the brief's approval, the report and the sprint's runs is less than fifteen minutes old, the window of ADR-console-005. A reading with no clock, which the digest takes, always reads moving: the digest reads no clock, so a change to quiet makes no digest sentence (ADR-console-014).

**D3. A run is the sprint's.** A run belongs to the sprint when it is its manager session's, or when it carries an issue of the sprint's report or of the report's inbox. It counts whenever it moved, before or after the report, and a new report keeps the movement already seen. Stage observations are unchanged: only reported issues, only runs that moved after the report, cleared by the next report.

**D4. A failed launch.** When the manager failed to start and no session of the sprint is listed, only the goal's stated time leaves the signals, because it stood in for a manager about to be listed and a failed launch says none will be. An approval, a report or a run inside the window keeps the sprint moving whatever its order against the failure. With none of them the sprint is not moving at once, and the ball reads nothing running, as #1086 decided: a failed launch beats the freshness of the goal. The state then reads drafting, since no brief was approved.

## Consequences

- ADR-console-014's sentence on movement, "Movement is the latest of the approval, the report and a run that carries one of the report's issues", is amended by D2 and D3; its status line names this decision.
- The state line never reads quiet under fifteen minutes, and the ball reads nothing running sooner only for a failed launch with no approval, report or run behind it.
- A run of the manager session on an issue it has not reported yet now counts as movement.
- Related: ADR-console-005, ADR-console-014.
