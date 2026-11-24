# ADR-console-048 — A merge refused by the guard shows once in the sprint's line, never as a question

Context: managers raised the guard's merge refusals as questions the owner could not act on (#1115). Decision: a report whose status line starts `merge refused: <reason>` marks it. The now-sentence shows it, and the ball and the inbox do not. Only a later report without the marker clears it, and the digest speaks once per reason. Rejected: a question card, and clearing it on a run observation.
