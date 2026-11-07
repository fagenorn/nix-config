---
name: deliver-batch
description: Delivers a batch of one repository's tracker issues through the deliver-batch Workflow program. Use for "deliver issues X, Y, Z".
---

# deliver-batch

Claude-only. The user's request is the opt-in to run this Workflow; one issue goes to `deliver-standard`.

Run the Workflow tool with `scriptPath` `deliver-batch.js` in the sibling `deliver-standard` skill directory and `args` `{repo_root, issues|label, batch_id, child_script, decisions?}`: `issues` the numbers, or `label` for every open issue carrying it; `batch_id` `<host>-<yyyymmdd-hhmm>` (short host name, local time now); `child_script` the absolute path of `deliver-standard.js` beside it.

Render what it returns by `stage`:
- `args`: report `error` and stop.
- `setup`: report `result` (the contract refusal, or null when setup returned nothing) with any `missing`, `invalid` and `holder`, and stop.
- `done` or `breaker`: on `breaker`, report it first. Render `table` as one Markdown table (issue, outcome, PR, detail), then the deferred `questions` by issue and the `owner_actions`.

Continue on a non-null `relaunch` as a new run, adding the user's answers as `decisions` `{"<issue>": answer}`; never `resumeFromRunId` for it. Only a run cut off before it returned resumes with `resumeFromRunId` and its original `args`.
