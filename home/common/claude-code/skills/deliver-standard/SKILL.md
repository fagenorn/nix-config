---
name: deliver-standard
description: Runs the standard-lane Workflow program for one issue. Use for deliver-standard.
---

# deliver-standard

Claude-only; settled criteria (fuzzy: `design`, `grill-with-docs` first).

Run `program-copies --repo-root <checkout> --from <this skill dir>`, then the Workflow tool with `scriptPath` its `deliver-standard.js` copy and `args` `{repo_root, issue, session_id: ${CLAUDE_SESSION_ID}, batch_id?, mode?, lane?, decisions?, spec?}` (`spec`: approved spec path). `mode`: `plan` stops after plan review, `ready` after verify (no PR), `ship` (default) merges; `lane: direct`: one implementer and reviewer, no plan.

Returns `{stage, ...}`. `done`, `planned`, `ready` succeed; keep `cont` for a later `mode`. No `cont`: report it. Else fix the cause (`needs_user`: ask, set `decisions`), rerun with `args.cont`.

Batch of issues: the `deliver-batch` skill.
