# ADR-console-029 — The owner answers the adoption's questions on the page

Context: plan questions were answered only with `adopt-project plan --answer` in a terminal (#1053, #1066). Decision: each open question is a counted inbox card. An answer reruns the plan with every answer that plan returned plus the new one, and the plan, not the console, judges it. A refusal is held in memory and logged to stderr, never appended. Rejected: the console judging or storing answers itself.
