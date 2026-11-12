---
name: deliver-batch
description: Delivers a batch of one repository's tracker issues through its Workflow program. Use for "deliver issues X, Y, Z".
---

# deliver-batch

Claude-only. The request opts in to this run; one issue goes to `deliver-standard`.

Run `program-copies --repo-root <checkout> --from <sibling deliver-standard skill dir>`, then the Workflow tool with `scriptPath` its `deliver-batch.js` copy and `args` `{repo_root, issues|label, batch_id, child_script, decisions?}`: `issues` the numbers, or `label` for every open issue with it; `batch_id` `<host>-<yyyymmdd-hhmm>` (short host, local time); `child_script` its `deliver-standard.js` copy.

Render what it returns by `stage`:
- `args`: report `error` and stop.
- `setup`: report `result` (the refusal, or null) with any `missing`, `invalid`, `holder`, and stop.
- `done` or `breaker`: on `breaker`, report it first. Render `table` as one Markdown table (issue, outcome, PR, reason), then `questions` by issue and `owner_actions`.

Run a non-null `relaunch` as a new run, adding the user's answers as `decisions` `{"<issue>": answer}`, unless its args, `reasons` aside, equal the previous run's: then stop, reporting the open rows as awaiting the owner. Only a run cut off before returning resumes with `resumeFromRunId` and its original `args`.
