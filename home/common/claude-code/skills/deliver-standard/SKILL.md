---
name: deliver-standard
description: Runs the standard-lane Workflow program for one issue. Use for deliver-standard.
---

# deliver-standard

Claude-only; settled criteria (fuzzy: `design`, `grill-with-docs` first).

Run the Workflow tool with `scriptPath` `deliver-standard.js` (this skill's directory) and `args` `{repo_root, issue, session_id: ${CLAUDE_SESSION_ID}, batch_id?, mode?, lane?, decisions?, spec?}` (`spec`: approved spec path). `mode`: `plan` stops after plan review, `ready` after verify (no PR), `ship` (default) merges; `lane: direct`: one implementer and reviewer, no plan.

Returns `{stage, ...}`. `done`, `planned`, `ready` succeed; keep `cont` for a later `mode`. No `cont`: report it. Else fix the cause (`needs_user`: ask, set `decisions`), rerun with `args.cont`.

Batch: `deliver-batch.js` there, `args` `{repo_root, issues|label, batch_id: <host>-<yyyymmdd-hhmm>, child_script: deliver-standard.js path, decisions?}`. Report its table; continue as a new run on `relaunch` (`resumeFromRunId` only if it was cut off).
