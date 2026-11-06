---
name: deliver-standard
description: Runs the standard-lane Workflow program for one issue. Use for deliver-standard.
---

# deliver-standard

Claude-only. For one issue with settled criteria, too big for `deliver-direct`; a fuzzy issue goes through `design` and `grill-with-docs` first.

Run the Workflow tool with `scriptPath` `deliver-standard.js` in this skill's base directory and `args` `{repo_root, issue, decisions?, spec?}` (`spec`: an approved spec's path). It plans outside the tree, implements, reviews, verifies, opens the PR, waits for required checks and merges.

It returns `{stage, ...}`; `done` means merged. On `setup`, report the reason. On any other stop, fix the cause (for `needs_user`, ask and set `decisions`), then rerun with the returned `cont` as `args.cont`: it re-adopts the worktree and skips the plan and finished tasks.
