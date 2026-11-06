---
name: deliver-standard
description: Runs the standard-lane Workflow program for one issue. Use for deliver-standard.
---

# deliver-standard

Claude-only. For one issue with settled criteria; a fuzzy issue goes through `design` and `grill-with-docs` first.

Run the Workflow tool with `scriptPath` `deliver-standard.js` in this skill's base directory and `args` `{repo_root, issue, session_id: ${CLAUDE_SESSION_ID}, batch_id?, mode?, lane?, decisions?, spec?}` (`spec`: an approved spec's path). It claims the issue, plans outside the tree, implements, reviews, verifies, opens the PR, waits for required checks and merges. `mode`: `plan` stops after plan review, `ready` after verify (no PR), `ship` (default) merges; `lane: direct` runs one implementer and one fresh reviewer, no plan.

It returns `{stage, ...}`. `done` (merged), `planned` and `ready` succeed: report them; keep `cont` for a later `mode`. A stop without `cont`: report the reason. Else fix the cause (for `needs_user`, ask and set `decisions`) and rerun with `cont` as `args.cont`.
