# Design: Dead workers leave a post-mortem trail; terminal job records survive session end

Issue: https://github.com/fagenorn/nix-config/issues/10 · Base: codex-plugin-cc pinned at `db52e28f`, patch p5 (includes issue #2's heal-on-read and issue #3's detached-reviewer work) · Worktree branch: `worktree-issue-10-worker-post-mortem`

## Problem

When a detached reviewer/task worker dies, nothing survives to say why.

The issue-6 plan-review worker (job `reviewer-msp00t2w-89raed`) died inside its 14-minute budget. Heal-on-read did its job — the record flipped to `failed` with `Worker process <pid> exited without recording a result.` — but that sentence is the *entire* forensic record, and it names a symptom, not a cause. Three gaps produce that outcome:

1. **The death trail is discarded at the source.** The worker is spawned `stdio: "ignore"`. A V8 fatal error, an `abort()` trace, or an unhandled-rejection stack goes to a closed fd. Two sibling detached node processes died of heap exhaustion the same evening; their `abort()` traces survived only in macOS crash reports, outside the plugin entirely.
2. **The post-mortem record is erased by the next session.** The SessionEnd hook walks every job of the ending session and calls `removeJobFromStateDir`, which deletes the `.json` *and* the `.log` beside it — `failed` and `completed` records included. The evidence that heal-on-read had just written was gone the moment the next session started.
3. **A hung-but-alive worker is invisible.** Heal-on-read can only reconcile a job whose recorded pid is *dead*. The in-process `Promise.race` timeout is the only thing enforcing the 840 s budget, and it dies with the process it lives in. A worker that is alive and wedged past its budget renders as `running` forever, with an ever-growing `Elapsed` and no signal that it has overrun anything.

The three gaps compound: (1) means there is nothing to read, (2) means there is nowhere to read it from, and (3) means a whole class of death never gets classified at all.

## Intent

Make a dead worker diagnosable after the fact, from disk, in a later session.

Concretely: the worker's own stderr lands in the job log it already owns; every job record of an ending session reaches a *truthful* terminal state and is *kept*, with its log, bounded by the retention policy the state layer already has; and a status read tells the user when a live worker has outrun its recorded budget, without pretending to be a second enforcement mechanism.

Nothing about the worker's shape changes. This is three narrow extensions of machinery issues #2 and #3 already built: one spawn option, one hook policy, one derived field.

## Requirements (bound to acceptance criteria)

| # | Requirement | AC |
|---|---|---|
| R1 | The detached worker's stderr (and stdout) is redirected to the job's existing log file at spawn, so anything the worker writes to fd 1/2 — including output no application code produced, like a V8 fatal error or an abort trace — is appended to a file the job record already points at via `logFile`. | AC1 |
| R2 | Captured raw output does not pollute the status surface: the progress preview continues to show only the runtime's own timestamped progress lines, and that exclusion is structural (a property of the filter) rather than incidental. | AC1 |
| R3 | SessionEnd deletes no job record. Records already terminal (`completed`/`failed`/`cancelled`) are retained with their logs. | AC2 |
| R4 | SessionEnd leaves every job of the ending session in a *truthful* terminal state: a job whose worker pid is already dead is reconciled by issue #2's heal-on-read (`failed`, dead-worker message); a job whose worker is still alive is terminated and then recorded `cancelled` with a session-ended reason. | AC2 |
| R5 | Retained records stay bounded on disk: the state layer's existing `MAX_JOBS` retention is applied at SessionEnd, the same lifecycle event that previously did the deleting. No new retention policy is introduced. | AC2 |
| R6 | A background enqueue with a timeout stamps the job record with `deadlineAt` (the record's creation instant plus its timeout). A job with no timeout gets no deadline. | AC3 |
| R7 | A status read derives, without writing, whether an active job is past its `deadlineAt`, and reports it on both the active-jobs table and the per-job detail block, alongside the already-present `/codex:cancel` action. An overdue job is not flipped to a terminal state. | AC3 |
| R8 | The patched plugin's suite passes env-scrubbed (baseline at p5: `# tests 107 / # pass 103 / # fail 0 / # skipped 4`), and `patchRevision` bumps 5→6 with `just build` succeeding. | AC4 |

## Design options considered

**A — Extend the three existing surfaces in place (chosen).** The spawn helper gains a log fd (the broker's exact shape); the SessionEnd hook's per-job branch swaps `remove` for `terminalize-and-retain` plus a prune call; the status read gains one derived field in the enrich step that already derives `elapsed`/`duration`/`phase`. No new files, no new record schema beyond a single `deadlineAt` timestamp, no new deletion or rendering paths. Every piece has in-repo precedent (see Decisions).

**B — A dedicated post-mortem artifact set.** A sibling `<jobId>.stderr.log` referenced by a new record field, plus an `archive/` directory that SessionEnd *moves* terminal records into instead of deleting them. Rejected: it multiplies surfaces for no diagnostic gain. The sibling log needs a new record field, new rendering to be discoverable, and new deletion/prune handling in `removeJobFromStateDir` and the prune path — three edits to make it as discoverable as `logFile` already is. The archive dir is worse: it invents a second retention policy alongside `MAX_JOBS`, and it moves records out from under `resolveJobFile`, so `status <jobId>` and `result <jobId>` would stop finding exactly the records the feature exists to preserve.

**C — An out-of-process watchdog that supervises worker pids and deadlines.** Rejected: explicitly out of scope in the issue, and it repeats the lesson issue #3 paid for twice — a second kill mechanism racing the first is the failure pattern, not the fix.

**D — Flip an overdue worker to a terminal state (with or without killing it).** Rejected: the worker is *by definition alive*, so a terminal record would be false at the moment it is written, which is precisely the class of lie issue #2 existed to remove. The issue asks that a read "reports an alive-but-overdue worker as such instead of showing it indefinitely running" — reporting, not reaping.

Sub-choices within A — which file receives the stderr, where overdue detection lives, what `cancelled` vs `failed` means at SessionEnd, whether the status listing crosses sessions — are settled in Auto-resolved decisions.

## Decisions

### AC1 — The worker's fds are redirected into the job log it already owns

`spawnDetachedTaskWorker` takes the job's log file and adopts `spawnBrokerProcess`'s shape verbatim:

```js
const logFd = fs.openSync(logFile, "a");
const child = spawn(process.execPath, [scriptPath, "task-worker", "--cwd", cwd, "--job-id", jobId], {
  cwd,
  env: process.env,
  detached: true,
  stdio: ["ignore", logFd, logFd],
  windowsHide: true
});
child.unref();
fs.closeSync(logFd);
```

Why this is safe and why it needs no new plumbing:

- **The log already exists at spawn time.** `enqueueBackgroundTask` calls `createTrackedProgress(job)` (which runs `createJobLogFile` → truncate + `Starting <title>.`) and appends `Queued for background execution.` *before* spawning. Opening in append mode after that cannot lose either line.
- **The worker never re-truncates it.** `handleTaskWorker` passes `logFile: storedJob.logFile ?? null` into `createTrackedProgress`, which takes the `options.logFile ?? createJobLogFile(...)` branch. The stored path is always set by the enqueue, so `createJobLogFile`'s truncating write is never reached on the worker side.
- **`logFile` is already the discoverable pointer.** It is a top-level record field, it is already surfaced as `Log: <path>` by `pushJobDetails`, and it is already what `removeJobFromStateDir` deletes alongside the `.json`. AC1's "discoverable from the job record" is satisfied by a field that exists, with no schema change and no new rendering.
- **The two writers do not fight.** Both the worker's own progress appends (`fs.appendFileSync`) and its inherited fd are `O_APPEND` on the same inode, from the same process. Interleaving is chronological, which is exactly what a post-mortem wants: the last progress line the worker managed to write, immediately followed by the trace that killed it.
- **The fd is not leaked.** `fs.closeSync(logFd)` after spawn releases the parent's copy; the child holds its own dup. Identical to the broker.
- **stdout is captured too**, matching the broker. The worker writes nothing to stdout in `task-worker` mode (`handleTaskWorker` never calls `outputResult`), so this costs nothing today and means a future stray write is evidence rather than a void.
- **The app-server's own stderr is unaffected.** `AppServerClient` spawns `codex app-server` with `stdio: ["pipe","pipe","pipe"]` and accumulates its stderr in memory for error messages. That path is untouched; only the worker process's own fds are redirected.

What this captures that nothing captured before: the worker's top-level `main().catch` already writes every escaping error to `process.stderr` — including the error `runTrackedJob` rethrows after recording it — plus node's own uncaught-exception and unhandled-rejection reports, and V8's `FATAL ERROR: Reached heap limit` / `abort()` output, which no `catch` can intercept because V8 writes it directly to fd 2. The redirection is fd-level, so it covers all of them with one mechanism and no per-error-class code.

One immediate dividend on a known race: issue #3 documented that `enqueueBackgroundTask` spawns the worker *before* writing the queued record, so a worker that boots faster than the following synchronous writes throws `No stored job found for <id>.` and exits, leaving heal-on-read to flip a record whose failure reason was unknowable. The log already exists when that happens (it is created before the spawn), so the redirection now captures that exact sentence — the race becomes self-documenting with no code written for it.

**Honest limit, to be stated in the plan:** `SIGKILL` is silent by construction — a `kill -9`'d process writes nothing. For that death the trail is the progress lines already in the log plus the heal-on-read line `reconcileWorkerLiveness` appends. The capture covers *diagnosable* deaths (fatal error, abort, uncaught exception, unhandled rejection), which is the class the issue actually observed in the sibling processes.

### AC1 — The progress preview excludes captured output structurally

`readJobProgressPreview` keeps only lines matching `line.startsWith("[")` and then strips a `^\[[^\]]+\]\s*` prefix. Raw V8 and node crash output does not start with `[` (stack frames start with spaces or `at`, V8's heap report starts with `<--- Last few GCs --->`), so the exclusion works today by accident.

Tighten the filter's bracket test from `^\[` to a full ISO-8601 timestamp prefix, so "captured raw output never reaches the progress preview" becomes a property of the filter rather than a property of what crashes happen to print. Every line the runtime writes goes through `appendLogLine`/`appendLogBlock`, which prefix `[${nowIso()}] `, so no legitimate progress line is lost; every log fixture in the suite that is *meant* to be previewed already uses a full ISO timestamp (`[2026-03-18T15:30:00.000Z] ...`), so the tightening is green against the existing suite.

**The tightening also closes a latent defect that predates this issue.** `runTrackedJob` appends `appendLogBlock(logFile, "Final output", execution.rendered)` on its completion path, and that path produces `failed` as well as `completed` (`completionStatus` is `failed` whenever `exitStatus !== 0`). `enrichJob` computes a progress preview for `failed` jobs. So the *body* of a rendered review — arbitrary markdown — is already preview-eligible today, and any body line beginning with `[` (a markdown link, a `[Blocking]`-style tag) passes the `startsWith("[")` test and then has its leading bracket group silently eaten by `stripLogPrefix`. A full-timestamp prefix excludes block bodies structurally.

Two further consequences, both favourable: `inferLegacyJobPhase` reads the preview, so neither captured output nor review prose can steer inferred phase; and the `[codex] <msg>` form `createProgressReporter` writes to stderr when `stderr: true` could never be mistaken for a progress line if a future worker path enabled it.

### AC2 — SessionEnd terminalizes and retains; it deletes nothing

`cleanupSessionJobs`'s per-job body changes from *terminate → cleanup → remove* to *reconcile → terminate → cleanup → terminalize → retain*:

1. **Reconcile first**, and branch on the *returned* record, not the one read off disk before the call. If the record is active and carries a `workspaceRoot` that still resolves to the state dir this loop is walking, run issue #2's `reconcileWorkerLiveness`. If the worker's pid is already dead, this is the existing dead-worker flip: the record becomes `failed` with `Worker process <pid> exited without recording a result.`, the reviewer runtime is cleaned before the terminal write, and the message is appended to the log. This makes SessionEnd the last heal-on-read opportunity before a session's records go quiet — which is exactly the issue-6 case, where no human ran a status read between the death and the session ending.
2. **If still active after reconciliation, the worker is alive.** Terminate its process tree (unchanged), clean the reviewer runtime for `plan-review` jobs (unchanged, idempotent), and only then write the terminal record.
3. **The terminal write mirrors `handleCancel`.** `status: "cancelled"`, `phase: "cancelled"`, `pid: null`, `completedAt`, `cancelledAt`, `errorMessage: "Session ended while the job was still <status>."`, and the same sentence appended to the log. Cancellation is the honest label: nothing failed, a lifecycle owner deliberately stopped a healthy worker — the same event `/codex:cancel` records.
4. **The write is guarded by the concurrent-writer bail-out.** It goes through `updateJobRecord`'s mutate-returns-`null` protocol: if the record is no longer active when the lock is held (the worker completed in the gap, another reader flipped it, a cancel landed), keep what the other writer wrote. Without this, a worker that finished microseconds before the hook fired would have its `completed` record overwritten with `cancelled` — a new lie in the place the previous lie was just removed.
5. **Nothing is deleted.** Every job of the ending session ends up terminal and retained. That is the whole rule, and it is what makes the record and its log available to a later session.

Two boundary cases fall out of the existing guards rather than needing new ones. An active record with no usable `pid` (a `queued` job whose launcher died before recording one) is not probe-eligible, so reconciliation leaves it active; `terminateProcessTree` already returns `{attempted: false}` for a non-finite pid, so it terminalizes as `cancelled` without a kill attempt. And a record that is *already* terminal is skipped entirely — the hook's terminate call is already inside the active-status guard, so a `completed` record that still carries a stale live pid is neither killed nor relabelled.

Ordering note: this preserves issue #2's documented invariant — *cleanup precedes the terminal write*. Reviewer-runtime cleanup and process termination both happen before the record goes terminal, so a hook that dies mid-way leaves an active record that the next status read heals, rather than a terminal record with a permanent leak no reader will revisit.

The hook iterates `listStateDirs()` and has no workspace root of its own, so the guarded write needs a state-dir-flavored mutator. `state.mjs` already establishes exactly this pairing convention (`removeJob(cwd)` / `removeJobFromStateDir(stateDir)`, `migrateLegacyJobIndex(cwd)` / `migrateLegacyJobIndexInStateDir(stateDir)`); follow it: add `updateJobRecordInStateDir(stateDir, jobId, mutate)` and make the existing `updateJobRecord(cwd, ...)` delegate to it. The delegation must keep creating the jobs directory — today `updateJobRecord` gets that for free because `resolveJobFile` calls `ensureStateDir`, so the state-dir variant needs the same `mkdirSync(jobsDir, { recursive: true })` that `removeJobFromStateDir` already does. Records without a `workspaceRoot` (legacy and synthetic fixtures) skip step 1 and take steps 2–5, which need only the state dir — and so do records whose `workspaceRoot` no longer resolves to the state dir holding them, since `resolveStateDir` hashes the *realpath* of the workspace root and falls back to the literal path when that fails, so a worktree moved or deleted since the record was written names a different dir.

### AC2 — Retention: the existing policy, triggered at the event that used to delete

`MAX_JOBS = 50` is the project's retention policy and it needs no replacement. But its *enforcement* has two halves, and only one of them runs often:

- `pruneJobs` caps what any read *sees* — `listJobs` applies it on every call, so no status output and no reader can be flooded regardless of how many files exist. This half is already sufficient for AC2's visible surface.
- `pruneJobRecords` is what actually *deletes* over-cap `.json`/`.log` artifacts, and it is reachable only from `saveState` ← `updateState` ← `setConfig`, whose sole production call site is the review-gate toggle. So on-disk deletion happens only when the review gate is flipped.

Today SessionEnd's unconditional removal is therefore the de-facto garbage collector of job artifacts. Removing it without a replacement trigger would let `.json` files — which carry the full `result`/`rendered` payload of every review, potentially hundreds of KB each — accumulate indefinitely. That is a leak this change would introduce, so it is in scope to prevent, and the fix is to trigger the policy that already exists rather than invent one: after the per-job loop, apply `MAX_JOBS` retention to each state dir the hook touched.

Add `pruneJobRecordsInStateDir(stateDir, { retain })` beside the existing pair convention (readdir → parse → sort newest-first by `updatedAt` → keep `MAX_JOBS` → `removeJobFromStateDir` the rest), and make `pruneJobRecords(cwd)` delegate to it — passing no `retain` — so `MAX_JOBS` keeps one home and cwd-scoped pruning is unchanged.

**An active record must be exempt from the cap** (corrected at Phase 5; the first draft of this section claimed the opposite was safe). The hook walks *every* state dir, not only the ending session's, so this prune is the one place where one session's shutdown can reach another session's live job. Two facts make a status-blind cap genuinely dangerous rather than theoretical: `pruneJobs` ranks purely by `updatedAt` and knows nothing about status, and `createJobProgressUpdater` writes only when `phase`, `threadId` or `turnId` *changes* — so a long-running or wedged worker's `updatedAt` goes stale and it sorts **oldest**, making it the first thing evicted. That is precisely the record this feature exists to preserve, and deleting it would violate R3 directly. So SessionEnd passes `retain: (job) => isActiveJobStatus(job.status)`. This is not a new policy: `MAX_JOBS` remains the only bound, applied to the records that are eligible for eviction at all.

The resulting steady-state ceiling is 50 terminal records plus their logs per state dir (one state dir per worktree), plus however many jobs are currently live there — where the large records are completed reviews carrying a `result`/`rendered` payload, order-of-magnitude single-digit MB per worktree, against a previous steady state of "whatever the current session has produced so far". That is the cost of the feature, it is bounded by a policy that already exists, and it is the reason the trigger is non-optional.

### AC3 — The record carries `deadlineAt`; the status read derives `overdue`

**The field.** `enqueueBackgroundTask` stamps the queued record with

```
deadlineAt = new Date(Date.parse(job.createdAt) + request.timeoutMs).toISOString()
```

when `request.timeoutMs` is a positive finite number, and omits it otherwise. `timeoutMs` already reaches the enqueue — `handleTask` computes it (defaulting to `840000` for reviewers) before the background branch, and `buildTaskRequest` carries it into the stored request — so no new plumbing is needed. Basing it on the record's own `createdAt` rather than a fresh `Date.now()` makes the field verifiable from the record alone and lets the suite assert an exact delta instead of a fuzzy one. `deadlineAt` survives the worker's `running` and terminal writes for free, because `runTrackedJob` spreads the stored record into both.

Naming follows the record's existing `<verb>At` ISO-string convention (`createdAt`, `startedAt`, `completedAt`, `cancelledAt`).

**The derivation.** `enrichJob` gains two derived, non-persisted fields beside `elapsed`/`duration`/`phase`:

```js
const overdueBy = isActiveJobStatus(job.status) ? formatElapsedDuration(job.deadlineAt, null) : null;
// -> overdue: Boolean(overdueBy), overdueBy
```

`formatElapsedDuration` already returns `null` for an unparseable start *and* for an end earlier than the start, so a missing `deadlineAt` and a deadline still in the future both fall out as "not overdue" with no extra branching. It is the same end-minus-start computation the function exists for — measured from the deadline rather than from the start — so the reuse is arithmetic, not a coincidence; only the name reads slightly off at the call site, which a comment covers.

**Why `enrichJob` and not `reconcileWorkerLiveness`.** Overdue detection must not write, and `reconcileWorkerLiveness` is a guarded mutation whose ordering and bail-out comments are load-bearing for issue #2; adding a second concern to it would put a read-only signal inside a locked write path. `enrichJob` is pure, is already the home of every derived status field, and reaches the listing (`buildStatusSnapshot`), the single-job read (`buildSingleJobSnapshot`), and the `--json` output (no projection step exists between `enrichJob` and `JSON.stringify`) in one place.

The composition also delivers "*alive*-but-overdue" for free: both snapshot builders run `reconcileWorkerLiveness` *before* `enrichJob`, so a job that is still active by the time `enrichJob` sees it has just passed a liveness probe. A dead worker flips to `failed` and is never reported overdue; only a worker that answered the probe can be.

**Advisory only.** No state changes, no process is signalled, `--wait` behaviour is untouched (it still waits for a terminal status until its own bound). The remedy is the action the row already offers: `/codex:cancel <id>`, which is present in the `Actions` cell for every queued/running job and remains the only user-facing kill path.

This is the human-facing counterpart to a machine-facing signal that already exists: the `codex:codex-reviewer` bridge reports `job <id> still <status> after 1080s of bounded waits (worker budget is 840s)` when a wedged worker outlives its bounded waits. AC3 gives the same fact to a person reading `/codex:status`, who otherwise sees only a growing `Elapsed`. Neither surface kills anything, and the two do not need to agree on a threshold — the bridge's is a transport bound, the record's is the job's own budget.

**Known, bounded skew.** `deadlineAt` measures from record creation, while the worker's internal `Promise.race` budget starts at turn start — after worker spawn, runtime seeding, and app-server connect (≤ ~25 s per issue #3's measurements). A healthy worker can therefore read as overdue for that margin before its own timeout fires. This is acceptable and self-correcting: the field is defined as *the deadline recorded in the job record*, the label reports exactly that, the signal is advisory, and within seconds the internal timeout writes a truthful `failed`.

### AC3 — Where overdue surfaces

Both status surfaces, because `plugins/codex/commands/status.md` constrains the choice: for a bare `/codex:status` it instructs the model to re-render the CLI output as a compact table and to "not include progress blocks or extra prose outside the table", preserving an enumerated field list (job ID, kind, status, phase, elapsed or duration, summary, follow-up commands). A signal that lived only in the `Live details:` block would be dropped from the user-visible surface for exactly the read where a wedged worker is discovered.

- **Active-jobs table** — the `Elapsed` cell becomes `<elapsed> (overdue by <overdueBy>)` when overdue, plain `<elapsed>` otherwise. `Elapsed` is in `status.md`'s preserved list, it is the correct semantic axis, and the existing table assertion matches the cell with `.*`, so the suffix keeps it green.
- **Per-job detail block** (`pushJobDetails`, used by both the `Live details:` list and the single-job `/codex:status <id>` report, which `status.md` tells the model to present in full) — one added line when overdue, stating the overrun, the recorded deadline, that the worker is still alive, and the cancel command.
- **`--json`** — `overdue` and `overdueBy` ride along verbatim, which is what the `codex:codex-reviewer` bridge and any other machine consumer read.
- **`plugins/codex/commands/status.md`** — add overdue to the preserved-fields sentence, so the model keeps it when it re-renders the table.

### Shared active/terminal predicate

`status === "queued" || status === "running"` is currently open-coded in a private `isActiveJobStatus` in `codex-companion.mjs`, in `isWorkerProbeEligible`, in the SessionEnd hook, and at several points in `job-control.mjs`. This change needs the predicate (and its negation, "terminal") in the hook and in `enrichJob`, so define it once: export `isActiveJobStatus` and `isTerminalJobStatus` from `tracked-jobs.mjs` (the job-lifecycle-semantics module, whose dependencies the hook already imports), use them in the new code, and delete `codex-companion.mjs`'s private copy in favour of the import. The inline comparisons inside `job-control.mjs`'s filters are left alone — converging them is pure churn with no behaviour change, and touched lines are review surface.

### Terminal, defined

**Terminal** = `completed` | `failed` | `cancelled`. **Active** = `queued` | `running`. There is no fourth state. Terminal records are retained by SessionEnd and eligible for `result <id>`; active records are what heal-on-read and the SessionEnd terminalization act on.

## Test seams

The agreed seams — all pre-existing; the plan and every implementer inherit these and may not invent others:

1. **The companion CLI subprocess surface** — `node scripts/codex-companion.mjs task|status|result … --json` run as child processes against a temp workspace with the fake codex on PATH. Prior art: `tests/reviewer-detach.test.mjs`, the background-task tests in `tests/runtime.test.mjs`.
2. **The on-disk state contract** — job record JSON, the job `.log`, and reviewer runtime directories located via the exported resolvers (`resolveStateDir`, `resolveJobFile`, `resolveJobLogFile`). Prior art: `tests/state.test.mjs`, `tests/liveness.test.mjs`, `tests/isolation.test.mjs`.
3. **The SessionEnd hook as a subprocess** — `node scripts/session-lifecycle-hook.mjs SessionEnd` with the hook JSON on stdin and `CODEX_COMPANION_SESSION_ID` in env. Prior art: the existing session-end tests in `tests/runtime.test.mjs`.

Plus one narrow rendered-text seam already used by the suite: assertions over the markdown `status` output (prior art: the active-jobs table assertions in `tests/runtime.test.mjs`) and over `plugins/codex/commands/status.md`'s text (prior art: the docs assertions in `tests/commands.test.mjs`).

No new seam is required. In particular, `spawnDetachedTaskWorker` stays module-private — AC1 is observable at seams 1 and 2 (run a background job through the CLI, read its log off disk), so exporting it to test the redirection directly would be inventing a seam for a property the public surface already shows.

## Test strategy

New behaviour-named file `tests/worker-postmortem.test.mjs` (precedent: `liveness.test.mjs`, `isolation.test.mjs`, `reviewer-detach.test.mjs` — never grow the 2400-line `runtime.test.mjs`), plus a rewrite of one existing session-end test.

**AC1 — capture**

1. *A failing background worker's stderr lands in the job log.* Enqueue a background task with a fake-codex behaviour that makes the run fail. The worker's top-level `main().catch` writes the rethrown error message to fd 2, so the log must contain that message as a line with **no** `[iso]` prefix — provably from the redirected fd, since no code path appends the error text to the log. Assert the log also still contains the `[iso]`-prefixed progress lines, and that `status <id> --json`'s `progressPreview` contains no fragment of the unprefixed text (R2). This is the deterministic, real-path proof that the fd redirection works for *anything* the worker writes to stderr, which is the whole mechanism.
2. *A hard-killed worker's trail is its progress plus the heal-on-read line.* `SIGKILL` the worker mid-run, then read status: the record is `failed` with the dead-worker message and the log ends with that message. Documents the honest limit rather than pretending `kill -9` produces output.

**AC2 — survival and truthfulness at SessionEnd**

3. *Terminal records and logs survive.* Seed a session with `completed` and `failed` records (each with a log) plus a record belonging to another session, run the hook, and assert all records and logs still exist and the other session's are untouched.
4. *A live worker is terminated and recorded `cancelled`.* Seed an active record whose pid is a live sleeper, run the hook, assert the pid is gone, the record is `cancelled` with the session-ended `errorMessage`, `pid: null`, a `completedAt`, and its log retained with the reason appended.
5. *An already-dead worker is recorded `failed`, not `cancelled`.* Same shape with a pid that is already dead: the record must carry issue #2's dead-worker message. This is the labelling distinction R4 exists for and the issue-6 case.
6. *A terminal record is never relabelled.* Seed a `completed` record that still carries a live pid and the ending session's id: the hook must leave its status `completed` and must not kill the pid — the concurrent-writer/terminal guard, asserted without racing anything.
7. *Retention still bounds disk.* Seed more than `MAX_JOBS` records for the ending session, run the hook, and assert the over-cap `.json` and `.log` artifacts are gone while the newest `MAX_JOBS` remain (prior art: `tests/state.test.mjs`'s "saveState prunes dropped job artifacts when indexed jobs exceed the cap").
8. *Rewrite of the existing test.* `session end fully cleans up jobs for the ending session` (in `tests/runtime.test.mjs`) asserts the ending session's `completed` and `running` artifacts are deleted and that the jobs dir contains only the other session's two files. That assertion **is** the behaviour AC2 changes, so the test is intentionally rewritten and renamed (e.g. *session end terminates live workers and retains terminal records*), keeping its still-valid halves: the other session is untouched and the live pid is killed. The plan must carry this as a deliberate rewrite, not a regression.

**AC3 — deadline and overdue**

9. *A reviewer background enqueue stamps the deadline.* `task --fresh --reviewer --background --json`, then read the record: `Date.parse(deadlineAt) - Date.parse(createdAt) === 840000` exactly. A non-reviewer background task with no `--timeout-ms` has no `deadlineAt`.
10. *An alive-but-overdue job reports overdue.* Seed an active record with a live sleeper pid and a `deadlineAt` in the past; `status --json` reports `overdue: true` with a non-empty `overdueBy`, and the rendered markdown's active-jobs table row carries `(overdue by ` in its `Elapsed` cell while the detail block carries the overdue line and the `/codex:cancel` action. Assert the record's `status` is still `running` afterwards — advisory, not a flip.
11. *Not-overdue cases.* A future `deadlineAt`, and an active record with no `deadlineAt` at all, both report `overdue: false`.
12. *A dead worker is failed, never overdue.* Seed a past `deadlineAt` with a dead pid: the read flips it to `failed` (issue #2's path) and reports `overdue: false`, proving the alive-but-overdue composition rather than asserting it in prose.

**Docs**

13. `plugins/codex/commands/status.md` mentions overdue in its preserved-fields guidance (prior art: the docs-text assertions in `tests/commands.test.mjs`).

Every assertion is a printed payload, an on-disk record, a file's existence, or rendered text. No call-count assertions, no wall-clock measurements. Suite expectation after the change: `# fail 0`, `# skipped 4` (unchanged upstream skips), `# tests` = 107 + the new tests, exact count recorded in the plan's verification output.

**Fixture note for the plan:** `tests/helpers.mjs` exports only `makeTempDir`, `writeExecutable`, `run`, and `initGitRepo`. The sleeper / dead-pid / `waitFor` helpers these tests need are defined *locally* in `tests/liveness.test.mjs`, which is the file-local convention; the new file defines its own rather than importing across test files or promoting them to the shared helper module. Each test file also pins `CLAUDE_PLUGIN_DATA` to a fresh temp dir and deletes the two `CODEX_COMPANION_*` env vars at module scope, which is what keeps the suite hermetic inside a live Claude session — the new file must do the same.

## Verification loop (for the plan to turn into tasks)

Per the repo `CLAUDE.md`'s mandatory patch-editing workflow — the nix-store plugin copy is read-only, so edits happen in a scratch clone and land only as the regenerated patch:

```sh
WORKTREE=<absolute path to this repo worktree>
scratch=$(mktemp -d)
gh repo clone openai/codex-plugin-cc "$scratch"
git -C "$scratch" checkout db52e28f4d9ded852ab3942cea316258ae4ef346
git -C "$scratch" apply --unidiff-zero "$WORKTREE/patches/agent-plugins/codex-plugin-cc.patch"   # zero-context patch; plain apply rejects it
git -C "$scratch" add -N .        # intent-to-add so patch-created files appear in git diff

# edit loop (env scrub is mandatory: 4 upstream tests fail spuriously under a live
# Claude session env, and unscrubbed runs leak codex-plugin-test-* state dirs):
(cd "$scratch" && env -u CLAUDE_PLUGIN_DATA -u CODEX_COMPANION_SESSION_ID -u CODEX_COMPANION_TRANSCRIPT_PATH node --test tests/*.test.mjs)

# regenerate (re-run `git add -N .` first — tests/worker-postmortem.test.mjs is a new file):
git -C "$scratch" diff -U0 db52e28f4d9ded852ab3942cea316258ae4ef346 > "$WORKTREE/patches/agent-plugins/codex-plugin-cc.patch"

# bump patchRevision 5 -> 6 in lib/agent-plugins.nix, then:
just build
```

Both the patch regeneration and the `patchRevision` 5→6 bump are required deliverables of the execution phase — the change does not reach the machine without them.

**Demo (the issue's own):** `kill -9` a running worker mid-review, then show (a) the job log ending with the worker's captured output and the heal-on-read line, (b) the healed `failed` record and its log still present after the owning session's SessionEnd, and (c) a status read flagging a still-alive worker that has passed its recorded deadline. Record it following the `2026-08-11-detached-reviewer-bridge-evidence.md` precedent in `.claude/specs/` (the plan phase fixes the exact home).

## Out of scope

- Changing the detached-worker architecture, the bounded-foreground-transport shape, or the reviewer's `840000` ms default (issues #2 and #3 settled these).
- Replacing heal-on-read, or altering `reconcileWorkerLiveness`'s flip semantics, ordering rule, or concurrent-writer bail-out. AC3 attaches beside it; it does not modify it.
- Any out-of-process watchdog, supervisor daemon, or second enforcement of the worker budget. Overdue is a report.
- Killing, signalling, or otherwise reaping an overdue worker.
- macOS crash-report integration.
- Making `/codex:status` list *other sessions'* retained records. `buildStatusSnapshot` filters to the current session, and that filter stays; cross-session post-mortem access is via `codex-companion status <jobId>` / `result <jobId>` (neither session-filters when given an explicit id) and the log file's stable path. Redefining `--all` to cross sessions is a separate, unrequested behaviour change.
- A new retention policy, an archive directory, or any change to `MAX_JOBS`'s value.
- Structured parsing, classification, or truncation of captured stderr. The log is raw evidence.
- Capturing stderr on the *foreground* task path, or stamping `deadlineAt` on foreground jobs. A foreground run's stderr already reaches the invoking terminal, so nothing is discarded there, and AC3's invisibility problem is specific to the detached worker whose in-process timeout dies with it.
- Broker lifecycle, `review`/`adversarial-review` commands, the `superpowers` patch, and every other plugin feature.
- Contributing the change upstream.

## Decision records

No separate ADR files. This repo has no `docs/` tree, no context map, and no ADR directory — `CLAUDE.md` is the authoritative project doc — so inventing an ADR convention for one issue would create a second, competing home for decisions that the `.claude/specs/` series already records. The three decisions that would otherwise qualify (SessionEnd retains rather than deletes; overdue is advisory and never enforced; the deadline is recorded at enqueue and never restamped) are captured below with their grounding and rejected alternatives, which is the content an ADR would carry. The one durable cross-issue invariant worth restating for whoever reads this next: **issues #2, #3 and #10 all rest on there being exactly one mechanism that ends a worker's life. #2 made its outcome truthful, #3 kept it inside the worker, and #10 declines to add a second one.**

## Auto-resolved decisions

### Captured stderr lands in the existing job log, not a sibling file
- **Question:** Does the worker's captured stderr go to the existing `job.logFile`, or to a sibling `<jobId>.stderr.log` referenced by a new record field?
- **Choice:** The existing `job.logFile`.
- **Grounding:** AC1 requires a file "discoverable from the job record"; `logFile` already is one — a top-level field, already rendered as `Log: <path>` by `pushJobDetails`, already deleted alongside the `.json` by `removeJobFromStateDir`, and already covered by this change's own SessionEnd survival work. A sibling file would need a new record field, new rendering, and new deletion/prune handling to reach the same discoverability. The interleaving objection inverts on inspection: one chronological file shows the last progress line the worker wrote immediately before the trace that killed it, which is what diagnosis needs, and both writers are `O_APPEND` from the same process.
- **Alternative considered:** A dedicated `<jobId>.stderr.log`, following `spawnBrokerProcess`'s use of a dedicated file — rejected because the broker's file is dedicated only in the sense that the broker has no other log; the transferable part of that precedent is the `openSync`/`stdio: [ignore, fd, fd]`/`unref`/`closeSync` shape, which is adopted verbatim.

### Both stdout and stderr are redirected
- **Question:** Redirect only fd 2, or fd 1 and fd 2 like the broker?
- **Choice:** Both, `stdio: ["ignore", logFd, logFd]`.
- **Grounding:** Byte-identical to `spawnBrokerProcess`, the in-repo precedent. `handleTaskWorker` never calls `outputResult`, so the worker's stdout is silent today and the extra redirection costs nothing; if a future path does print, that output is evidence rather than a void.
- **Alternative considered:** `["ignore", "ignore", logFd]` — marginally narrower, gratuitously divergent from the precedent, and it would silently discard a future diagnostic.

### The progress-preview filter is tightened to a full ISO prefix
- **Question:** Leave `readJobProgressPreview`'s `line.startsWith("[")` filter alone (captured crash output happens not to start with `[`), or make the exclusion structural?
- **Choice:** Tighten the bracket test to a full ISO-8601 timestamp prefix.
- **Grounding:** AC1 must not corrupt the status surface, and after this change the log holds arbitrary third-party bytes. Every runtime-written line goes through `appendLogLine`/`appendLogBlock`, which always prefix `[${nowIso()}] `, so nothing legitimate is lost; every previewed log fixture in the suite already uses a full ISO timestamp, so the tightening is green at p5. It also protects `inferLegacyJobPhase`, which reads the preview, from being steered by captured output.
- **Alternative considered:** Leaving the filter as-is and relying on crash output never starting with `[` — rejected: it makes a correctness property of the status surface depend on the formatting habits of code we do not control.

### Retention needs no new policy, but does need a trigger
- **Question:** Do records surviving SessionEnd require new pruning?
- **Choice:** No new policy — `MAX_JOBS = 50` stays exactly as it is — but its existing deleting half must be triggered at SessionEnd, via a `pruneJobRecordsInStateDir(stateDir)` sibling that `pruneJobRecords(cwd)` delegates to.
- **Grounding:** This refines the Phase-0 reading. `pruneJobs` caps every read (`listJobs` applies it unconditionally), so the *visible* surface is already bounded and no reader can be flooded. But `pruneJobRecords` — the half that deletes `.json`/`.log` artifacts — is reachable only from `saveState` ← `updateState` ← `setConfig`, whose only production call site is the review-gate toggle. SessionEnd's unconditional removal is therefore today's de-facto garbage collector; removing it with no replacement trigger would let records that each carry a full `result`/`rendered` review payload accumulate indefinitely. Triggering the existing policy at the same lifecycle event that previously did the deleting is the minimal correct completion of AC2, not new policy.
- **Alternative considered:** Triggering the prune from `listJobs` (every status read would delete files — a read with a destructive side effect, and a much larger behavioural change), or inventing a time-based/archive retention (a second policy alongside `MAX_JOBS`).

### An overdue worker is reported, never flipped or killed
- **Question:** Should an alive-but-overdue worker be flipped to a terminal state (and/or killed), or reported as overdue while left running?
- **Choice:** Reported only. No state change, no signal. The user's remedy is `/codex:cancel <id>`, already present in the row's `Actions` cell for every active job.
- **Grounding:** The issue asks that a read "reports an alive-but-overdue worker as such instead of showing it indefinitely running" — reporting, and it notes the worker is by definition alive, so killing is not asked for. A terminal record written about a live process would be false at the instant of writing, which is the exact class of lie issue #2 removed. Issue #3 rejected bridge-side killing for the same reason: a second kill mechanism racing the first is the twice-observed failure pattern, and a result that may still land stays collectable if nothing kills the worker.
- **Alternative considered:** Flipping to `failed`/`cancelled` after the deadline (fabricates a terminal state for a running process, and destroys a result that may still arrive), or `SIGTERM`ing the worker (an out-of-process enforcement mechanism, explicitly out of scope).

### Overdue is derived in `enrichJob`, not inside `reconcileWorkerLiveness`
- **Question:** Where does overdue detection live — inside issue #2's `reconcileWorkerLiveness`, or beside it?
- **Choice:** As two derived fields (`overdue`, `overdueBy`) in `enrichJob`.
- **Grounding:** Overdue must not write, and `reconcileWorkerLiveness` is a guarded mutation whose ordering rule and concurrent-writer bail-out are load-bearing and must be preserved; adding a read-only signal inside a locked write path would put two concerns in one critical section. `enrichJob` is pure and already derives `elapsed`, `duration`, and `phase`, and it reaches the listing, the single-job read, and `--json` (no projection step exists before `JSON.stringify`) in one edit. The composition also yields "*alive*-but-overdue" for free, because both snapshot builders run `reconcileWorkerLiveness` before `enrichJob` — so only a job that just passed a liveness probe can ever be reported overdue.
- **Alternative considered:** Extending `reconcileWorkerLiveness` to also detect overdue (couples a read-only signal to #2's write path and its ordering comments) or adding a third pass over the job list (a redundant traversal for a field the existing enrich pass can compute).

### `deadlineAt` = record creation + timeout, stamped once at enqueue
- **Question:** What exactly is the recorded deadline, given that the worker's internal budget starts at turn start rather than at enqueue?
- **Choice:** `deadlineAt = createdAt + request.timeoutMs`, stamped once by `enqueueBackgroundTask`, absent when there is no timeout. Background path only.
- **Grounding:** The issue specifies "enqueue time + timeout" and notes that "a deadline only exists when a timeout does". Basing it on the record's own `createdAt` (rather than a fresh `Date.now()`) makes the field verifiable from the record alone and lets the suite assert an exact 840000 ms delta instead of a fuzzy window. The known skew — the internal `Promise.race` starts after spawn, runtime seeding, and app-server connect (≤ ~25 s per issue #3) — is bounded, self-correcting (the internal timeout writes a truthful `failed` within that margin), and harmless because the signal is advisory; the field is defined as *the deadline recorded in the record* and the label reports exactly that, so it is truthful by construction.
- **Alternative considered:** Restamping `deadlineAt` from `startedAt` in the worker's `running` write (tighter, but it gives the constant two homes and still does not match the true turn-start instant), or adding a grace margin (invented policy the issue did not ask for).

### Terminal = `completed` | `failed` | `cancelled`, via one shared predicate
- **Question:** What exactly does "terminal" mean for the SessionEnd filter, and where does the predicate live?
- **Choice:** Terminal is `completed`/`failed`/`cancelled`; active is `queued`/`running`. Export `isActiveJobStatus` and `isTerminalJobStatus` from `tracked-jobs.mjs`, use them in the new code, and delete `codex-companion.mjs`'s private `isActiveJobStatus` in favour of the import.
- **Grounding:** Those five are the only statuses any writer produces (`runTrackedJob`, `handleCancel`, `reconcileWorkerLiveness`, `enqueueBackgroundTask`), and the active pair is already the codebase's own de-facto predicate — open-coded in `codex-companion.mjs`, `isWorkerProbeEligible`, the SessionEnd hook, and `job-control.mjs`. This change needs it in two more places, so it gets one home. `tracked-jobs.mjs` is the job-lifecycle-semantics module and the hook already imports its whole dependency set, so no new package-level edge is created.
- **Alternative considered:** Open-coding the comparison a fifth and sixth time (a sixth home for a closed-set rule), or converging every existing inline comparison too (churn on untouched lines, no behaviour change, more review surface).

### A SessionEnd-terminated live worker is recorded `cancelled`
- **Question:** A job that SessionEnd itself kills was `running` and becomes non-terminal-but-dead. Does the hook write a terminal record for it, and with what status?
- **Choice:** Yes — after terminating the process tree and cleaning the reviewer runtime, write `cancelled` / `phase: "cancelled"` / `pid: null` / `completedAt` / `cancelledAt` / `errorMessage: "Session ended while the job was still <status>."`, and append the same sentence to the log. The write goes through `updateJobRecord`'s mutate-returns-`null` guard.
- **Grounding:** Under "retain terminal, and nothing else needs deleting", a killed job must be terminalized or it would be the one record class that still vanishes — losing exactly the evidence AC2 preserves. `cancelled` is the honest label and has direct precedent: `handleCancel` records deliberate termination by an actor as `cancelled` with an `errorMessage` and a log line, and SessionEnd killing a healthy worker is the same kind of event. `failed` would assert a fault that did not occur. Placing the write after termination and runtime cleanup preserves issue #2's "cleanup precedes the terminal write" ordering, so a hook that dies mid-way leaves an active record the next status read heals. The guard is required because a worker that completed microseconds earlier would otherwise have its `completed` record overwritten with `cancelled`.
- **Alternative considered:** Leaving the record `running` and relying on a later heal-on-read (it would never happen — `buildStatusSnapshot` filters to the current session, so the record would sit as a permanently lying `running` forever), or deleting non-terminal records (the evidence loss the issue reports, in the case where no status read preceded session end).

### SessionEnd reconciles liveness before deciding the label
- **Question:** Should the hook run heal-on-read before terminalizing, or just record `cancelled` for anything still active?
- **Choice:** Reconcile first via `reconcileWorkerLiveness` when the record carries a `workspaceRoot` *and* `resolveStateDir(workspaceRoot)` is the state dir the hook is walking; only a job that survives that as still-active gets terminated and recorded `cancelled`.
- **Grounding:** This is the issue-6 case exactly: the worker died hard and no human ran a status read before the session ended. Without reconciliation the hook would label a crash as a session-end cancellation — a lie, in the same place issue #2 removed one. With it, the hook becomes the last heal-on-read opportunity before a session's records go quiet, and the record keeps the truthful `Worker process <pid> exited without recording a result.` message. The issue's Decisions require extending issue #2's heal-on-read rather than replacing it; this is that extension. Records lacking a `workspaceRoot` (legacy and synthetic fixtures) skip reconciliation and take the state-dir-only path, since `reconcileWorkerLiveness` needs a workspace root to resolve the reviewer runtime and the job file — and so do records whose `workspaceRoot` resolves to a *different* state dir than the one holding them, because reconciliation would then terminalize a phantom record elsewhere while this loop read "terminal" and skipped the real one.
- **Alternative considered:** Recording `cancelled` for everything still active (simpler by one branch, mislabels every unread crash), or duplicating #2's pid probe and message inside the hook (a second home for the dead-worker semantics).

### SessionEnd still terminates the live workers of the ending session
- **Question:** Does the hook keep killing live workers, or does record survival imply worker survival?
- **Choice:** Unchanged — `terminateProcessTree` still runs for every still-active job of the ending session, and the reviewer runtime is still cleaned.
- **Grounding:** AC2 is about record survival only; nothing in the issue asks for worker survival. Issue #3's spec documented SessionEnd reaping as a deliberate lifecycle boundary — a plan-review whose requesting session is gone has no consumer, and exempting it would leak orphan workers and runtime directories, reintroducing the leak class issue #2 closed. The termination call is already independent of the removal call in the hook, so retaining records requires no change to it.
- **Alternative considered:** Letting workers outlive their session (orphan processes and runtime dirs with no consumer, contradicting issue #3's recorded boundary).

### The status listing's session filter stays; cross-session access is by job id
- **Question:** Retained records are invisible to a later session's `/codex:status`, because `buildStatusSnapshot` filters to the current session. Does AC2 require lifting that filter?
- **Choice:** No. The filter is untouched. Post-mortem access from a later session is `codex-companion status <jobId>` / `result <jobId>` — neither session-filters when given an explicit id — plus the log file at its stable path.
- **Grounding:** AC2 asks that records and logs *survive*, which is what makes any later read possible at all; it does not ask for a new discovery surface. The user diagnosing a specific failure has the job id from the failing session, and `buildSingleJobSnapshot`/`resolveResultJob` both bypass the session filter for an explicit reference. Within the owning session — where a failure is normally first noticed — the listing already shows the record.
- **Alternative considered:** Redefining `--all` to cross sessions (today it only widens the `recent` slice; changing its meaning is an unrequested behaviour change with its own test surface) or dropping the session filter entirely (would surface every parallel worktree session's jobs in one listing).

### Overdue must appear in the table cell, not only the detail block
- **Question:** Which status surface carries the overdue signal?
- **Choice:** Both — a suffix on the active-jobs table's `Elapsed` cell (`<elapsed> (overdue by <overdueBy>)`) and a dedicated line in the per-job detail block — plus `overdue`/`overdueBy` in `--json`, and an update to `plugins/codex/commands/status.md`'s preserved-fields guidance.
- **Grounding:** `plugins/codex/commands/status.md` instructs the model, for a bare `/codex:status`, to re-render the CLI output as a compact table, to "not include progress blocks or extra prose outside the table", and to preserve an enumerated field list that includes elapsed. A signal living only in `Live details:` would be dropped from the user-visible surface on precisely the read where a wedged worker is found. `Elapsed` is in that enumerated list and is the correct semantic axis, and the existing table assertion matches the cell with `.*`, so a suffix stays green. The detail block covers `/codex:status <id>`, which `status.md` tells the model to present in full. The `status.md` edit is required so the model preserves the new signal.
- **Alternative considered:** A new `Overdue` column (not in `status.md`'s enumerated list, so the model may drop it, and it widens an eight-column table for a rare case), or overriding the `Phase` cell (destroys the workflow phase — `reviewing` — that the same cell exists to report, and breaks existing phase assertions).

### The existing session-end cleanup test is rewritten, not preserved
- **Question:** `session end fully cleans up jobs for the ending session` asserts the ending session's `completed` and `running` artifacts are deleted and that only the other session's files remain. Is that a test to keep green?
- **Choice:** No — it is rewritten and renamed (e.g. *session end terminates live workers and retains terminal records*), keeping its still-valid assertions (the other session untouched, the live pid killed) and replacing the deletion assertions with retention and terminal-label assertions.
- **Grounding:** That assertion *is* the behaviour AC2 changes; a test encoding the old policy cannot survive a change to the policy. Issue #3's spec treated the same test as a pinned boundary precisely because it did not change SessionEnd; this issue does. Flagging it explicitly keeps the plan from reading the failure as a regression and "fixing" it by restoring the deletion.
- **Alternative considered:** Adding new tests while leaving the old one green (impossible — the assertions are mutually exclusive), or deleting the test outright (loses the two assertions that are still correct and still worth pinning).

### AC1 is proven through the worker's own top-level catch, not a simulated V8 abort
- **Question:** How does the suite prove stderr capture without manufacturing a heap exhaustion or an `abort()`?
- **Choice:** Enqueue a background task that fails, and assert the job log contains the worker's rethrown error message as an **unprefixed** line. Separately, assert the `SIGKILL` case's trail (progress lines plus the heal-on-read line) and document that `kill -9` is silent by construction.
- **Grounding:** `handleTaskWorker` does not catch, `runTrackedJob` rethrows after recording, and `codex-companion.mjs`'s `main().catch` writes the message to `process.stderr` — so every failing background job already writes to fd 2 today, and that output currently goes nowhere. No code path appends the error text to the log, so an unprefixed copy appearing there can only have come through the redirected fd. Because the mechanism is fd-level, proving it for one stderr writer proves it for all of them, including the V8 output no `catch` can intercept; a fixture that fakes a heap abort would test node's crash formatting, not the plugin. `tests/liveness.test.mjs`'s `spawnSleeper`/`deadPid` helpers already establish the kill-and-probe pattern for the `SIGKILL` half.
- **Alternative considered:** A fake-codex behaviour that writes junk to its own stderr — rejected: `AppServerClient` spawns the codex child with `stdio: ["pipe","pipe","pipe"]` and buffers its stderr in memory, so it never reaches the worker's fd 2 and the test would assert nothing about the redirection. Exporting `spawnDetachedTaskWorker` to test it directly — rejected: inventing a seam for a property the CLI surface already exposes.

### Phase 5 (finding S1): an active record is exempt from the SessionEnd cap
- **Question:** The standards review falsified this design's claim that a concurrent session's live job is safe from the SessionEnd prune. Does the retention decision above survive?
- **Choice:** The decision survives — no new policy, the existing `MAX_JOBS` triggered at SessionEnd — with one correction: the prune takes a caller-supplied `retain` predicate and the hook passes `(job) => isActiveJobStatus(job.status)`, so an active record is never an eviction candidate. `MAX_JOBS` now bounds the evictable (terminal) records. The falsified sentence in "AC2 — Retention" is corrected in place; this entry records why.
- **Grounding:** The original claim was that a live worker "stamps `updatedAt` on every progress event, so it sorts newest". `createJobProgressUpdater` (`tracked-jobs.mjs:77-105`) returns early unless `phase`, `threadId` or `turnId` changed, so a long-running or wedged worker's `updatedAt` goes *stale* and it sorts oldest under `pruneJobs`'s status-blind `updatedAt` ranking (`state.mjs:190-194`). Because the hook walks every state dir and retaining terminal records makes 50-record dirs the steady state, a status-blind cap would let one session's end delete a concurrent session's live record and log — a direct violation of R3, and the loss of exactly the evidence R1 exists to capture. The predicate is supplied by the caller because `tracked-jobs.mjs` already imports from `state.mjs`; importing the status predicate back would be a cycle, and the state layer carries no status semantics today.
- **Alternative considered:** Re-running the design phase over this section — rejected as disproportionate: no requirement, option, or scope boundary changed, only a false justification and the guard it failed to justify. Hard-coding the status check inside `state.mjs`, or importing `isActiveJobStatus` there — both rejected (duplicated predicate; circular import).
