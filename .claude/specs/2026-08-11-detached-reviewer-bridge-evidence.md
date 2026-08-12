# Detached reviewer bridge — AC8 live-demo evidence

Recorded 2026-08-11, after `just switch` activated the p5 plugin
(`/nix/store/b4p6s8fmnk1sb074wjly85z3v2cbd2ga-codex-plugin-cc-1.0.6-nix.db52e28f.p5`,
confirmed as `installed_plugins.json` installPath; active `codex-reviewer.md`
contains the `--background --json` enqueue and no `run_in_background: true`).
One real `plan-review` ran end-to-end through the rebuilt transport sequence —
the exact three calls the bridge agent definition prescribes, against the live
Codex API, reviewing the real implementation plan
`.claude/plans/2026-08-11-detached-reviewer-bridge.md`.

Demo note: the transport sequence was driven directly at the CLI. The plugin
*agent definition* is process-snapshotted per Claude Code session (see
`docs`-recorded snapshot rule, commit 9a4c53a), and the recording session
predated the switch — dispatching `codex:codex-reviewer` from it would have
exercised the stale pre-fix definition. The active p5 definition prescribes
byte-for-byte the commands run below (verified by grep against the installed
file), so this is the contract the next fresh session's bridge executes.

## 1. Enqueue (sub-second, returns the job id)

```
$ codex-companion task --fresh --reviewer --background --json < <packet>
{
  "jobId": "reviewer-msos3kyn-oatetg",
  "status": "queued",
  "title": "Codex Plan Reviewer",
  "summary": "Operation: plan-review Invocation directory: /Users/anis/tmp/nix-config Worktree root: /Users...",
  "logFile": ".../state/nix-config-3d36e85cba3c8b06/jobs/reviewer-msos3kyn-oatetg.log"
}
```

## 2. Bounded wait (first 540 s chunk sufficed)

```
$ codex-companion status reviewer-msos3kyn-oatetg --wait --timeout-ms 540000 --json
{ "status": "completed", "phase": "done", "waitTimedOut": false, "errorMessage": null }
```

## 3. Result collection (the definition's extraction, verbatim)

```
$ codex-companion result reviewer-msos3kyn-oatetg --json > result.json
$ node -e '…storedJob.result.rawOutput…' result.json review.md   # exit 0
storedJob: { "status": "completed", "completedAt": "2026-08-11T14:58:27.626Z" }
```

Reviewer runtime directory `reviewer-runtimes/reviewer-msos3kyn-oatetg`:
absent after completion (cleaned by the worker).

## 4. The returned review (rawOutput, verbatim shape)

Three top-level sections came back well-formed — `Blocking: None.`, three
`Should fix` findings (S1–S3, each with affected section, live `path:line`
evidence, confidence, correction, unknowns), `Discussion` reporting all six
packet artifacts readable. No `CODEX_REVIEW_FAILURE`, no Claude fallback, no
truncation.

Findings disposition (the reviewed plan is executed and shipped; findings
grade the plan document post-hoc): S1 re-detects the known Task-1 snippet
drift already recorded in the plan's own D1 disposition and triaged defer at
final review. S2/S3 suggest stronger written gates than the plan's `--stat`
and grep set; the stronger checks were in fact performed during execution by
the sdd task reviewers (byte-for-byte body diff; whole-file stale-prose
sweeps). No action on the shipped artifacts.

## 5. Bonus: issue #2's healing observed live on the original incident

The job the 2026-08-10 forensics started from — `reviewer-msn70svo-bgjxnw`,
hard-killed mid-turn, frozen ~30 h at `status: "running", pid: 1818` with its
runtime directory leaked — was healed by the *first* p5 status read:

```
$ codex-companion status reviewer-msn70svo-bgjxnw --json
{ "status": "failed", "phase": "failed", "pid": null,
  "errorMessage": "Worker process 1818 exited without recording a result.",
  "completedAt": "2026-08-11T14:50:59.421Z" }
```

Persisted on disk identically; `reviewer-runtimes/reviewer-msn70svo-bgjxnw`
removed in the same read.

## Verdict

AC8 satisfied: enqueue payload with job id, wait snapshot `running →
completed` with `waitTimedOut: false`, a well-formed three-section review
returned verbatim from the durable job record, terminal `completed` record,
and no `CODEX_REVIEW_FAILURE` or fallback anywhere in the run.
