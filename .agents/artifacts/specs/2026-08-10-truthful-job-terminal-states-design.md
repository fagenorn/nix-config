# Design: Companion jobs report truthful terminal states; reviewer runtimes never leak

Issue: https://github.com/fagenorn/nix-config/issues/2 · Base: codex-plugin-cc pinned at `db52e28f`, patch p3 · Worktree branch: `worktree-issue-2-truthful-job-states`

## Problem

When the process driving a codex-companion job dies without reaching a terminal transition — hard kill, crash, machine reboot — the job record freezes at `running`/`queued` forever. `codex-companion status <id> --wait` then blocks until its own timeout on a job that can never finish, and a reviewer job's isolated runtime directory (`reviewer-runtimes/<jobId>/`) leaks on disk.

Falsifying evidence at base (2026-08-10, session `581dbb6b`): job `reviewer-msn70svo-bgjxnw` was hard-killed mid-turn; its record still reads `status: "running", phase: "starting", pid: 1818` with pid 1818 long dead, and its runtime directory still exists. This violates the-bar "Truthful terminal states": a run that did no work must report Failed, never eternally Running.

This fix is a prerequisite for issue #3 (trusting `status --wait` as the bridge's only wait primitive for detached reviewers).

## Intent

Make the job-state surface truthful at read time: a status read probes the recorded driver pid of active jobs, persists the `failed` transition when the driver is gone, terminates `status --wait` on that transition, and guarantees that every terminal path — including the new dead-worker one — leaves no reviewer runtime directory behind. Entirely runtime-side, inside the repo's `codex-plugin-cc` patch; no change to how jobs are launched.

## Requirements (bound to acceptance criteria)

| # | Requirement | Acceptance criterion |
|---|---|---|
| R1 | A `running`/`queued` job whose recorded worker pid no longer exists is reported `failed` by a single `codex-companion status` read (and by any status listing), with an error naming the dead worker pid, and the transition is persisted to the job record. | AC1 |
| R2 | `status <id> --wait` on such a job returns the failed state on its next poll instead of sleeping until `--timeout-ms`. | AC2 |
| R3 | After any terminal state — success, failure, internal timeout, cancel, or the new dead-worker transition — the job's reviewer runtime directory no longer exists on disk. | AC3 |
| R4 | `node --test tests/` passes in a patched checkout of the pinned revision, including new tests asserting the dead-pid→failed transition through observable job state (no call-count assertions). | AC4 |
| R5 | `patches/agent-plugins/codex-plugin-cc.patch` is regenerated, `patchRevision` in `lib/agent-plugins.nix` is bumped 3→4, and `just build` succeeds. | AC5 |

## Design options considered

**A — Persistent read-time reconciliation at the status surface (chosen).** Status snapshot builders probe each active record's pid; on ESRCH they take the record's own metadata lock, re-check, remove the reviewer runtime, and persist the `failed` transition. One authoritative home for job state (the record), every consumer sees the same truth after any status read, `--wait` terminates naturally because it polls the same builder.

**B — Report-only derivation.** The snapshot shows `failed` but the record stays `running`. Rejected: consumers disagree (`result` still refuses "still running" jobs, `cancel` and resume-candidate still see an active job), every reader must re-derive the probe, and the record — the authoritative state home — keeps lying. Violates "Truthful terminal states" and DRY (job state would have two homes: the record and the derivation rule).

**C — Background sweeper/GC daemon.** Rejected: explicitly out of the issue's scope, YAGNI, and a process with no live caller contradicts the Node standard's "background work with no off switch" rule. The read path is the only place that needs the truth, exactly when it needs it.

**D — Reconcile inside `listJobs` so every consumer heals.** Rejected for blast radius: `listJobs` also runs on write paths (`saveState`, pruning), which would turn every read into a potential write mid-write; it would also silently change `cancel` semantics (a dead job would flip to `failed` before `resolveCancelableJob` sees it). The issue scopes the probe to status reads; persistence makes every other consumer consistent one status read later without touching them.

## Decisions

### Status-read state machine

**Probe eligibility.** A record is probed iff `status ∈ {queued, running}` **and** its `pid` is a finite number. Terminal records (`completed`, `failed`, `cancelled`) are never probed (their writers already set `pid: null`). Active records without a finite pid are left untouched — they are unprobeable, and the upstream suite enshrines this ("status --wait times out cleanly" seeds a pid-less `running` record and asserts it stays running).

**Probe.** `process.kill(pid, 0)`. Only `ESRCH` means dead. Success or `EPERM` (process exists but isn't ours) or any other errno counts as alive — the read path never flips a record on uncertain evidence; a wrong "alive" degrades to today's behavior, a wrong "dead" would fabricate a failure.

**Transition (probe says dead).** Under the same per-job metadata lock the record's writers use:

1. Re-read the record. If it is no longer `queued`/`running`, or its pid is no longer the probed pid, abort — a concurrent writer (worker completion, cancel, another reader's flip) won the race; return the re-read record.
2. If the job is a reviewer job (`kind === "plan-review"`): remove its reviewer runtime directory (`cleanupReviewerRuntime` — already idempotent and path-guarded). Cleanup precedes the terminal write deliberately: a crash between the two steps leaves the record active, so the next status read retries both; the reverse order would leave a terminal record with a permanent leak that no reader would ever revisit.
3. Write the failed record:
   - `status: "failed"`, `phase: "failed"` (the shape every existing failure writer produces)
   - `errorMessage: "Worker process <pid> exited without recording a result."` — the error text naming the dead worker
   - `pid: null` (terminal records never carry a pid)
   - `completedAt: <now>` — detection time, the earliest truthful bound the reader has (matches every existing terminal writer; no new `failedAt` field — no consumer needs it, no precedent carries it)
   - `updatedAt` stamped by the guarded write, as `upsertJob` does today

A metadata-lock timeout during the flip propagates to the caller — no catch-and-mute (the-bar "Root causes"); a status read that cannot take a per-job lock held for milliseconds is evidence of a real fault and must say so.

After the lock is released, append the same error message to the job's log file (`appendLogLine` precedent from `cancel`): the log stream must show why the job failed. This line is also what surfaces the error in the *human-rendered* status report — verified in `render.mjs`: `renderJobStatusReport` prints a failed job's log-derived progress preview but not `errorMessage` (only `result` prints that) — so the issue's demo output names the dead worker through the log line while the `--json` surface carries `errorMessage`.

**Where it runs.** Both single-job snapshots (`status <id>`, and each poll of `status <id> --wait`) and the status listing (`status`, `status --all`) reconcile active records before enriching/partitioning them, so a flipped job leaves the "running" section and appears as the latest finished job in the same read. The listing reconciles exactly the active records it surfaces — i.e. after its existing session filter; a dead job belonging to another Claude session is healed by that session's listing or by any single-job read (`buildSingleJobSnapshot` applies no session filter). `waitForSingleJobSnapshot` needs no change of its own: it loops on `isActiveJobStatus`, and the reconciled snapshot exits that loop on the first poll after death — that is the prompt `--wait` termination.

### Driver-pid invariant (verified, no writer changes)

The recorded `pid` is always the pid of the process driving the job to its terminal transition:

- **Foreground jobs** (`review`, `task`, reviewer `task --reviewer`): `runTrackedJob` records `pid: process.pid` — the CLI client *is* the driver (evidence record pid 1818 was the foreground client).
- **Detached background jobs**: `enqueueBackgroundTask` records `pid: child.pid` where the child *is* the `task-worker` process; the worker's own `running` write records `process.pid` — the same pid. There is no separate supervisor whose pid could diverge.
- Every terminal writer (`completed`/`failed`/`cancelled`) sets `pid: null`.

So the invariant already holds on every path and `handleTaskWorker`/`runTrackedJob` need no pid changes. The known races are all handled correctly by the probe: a worker that crashes before its first record write (including the enqueue race where the worker reads its `request` before the queued record exists and dies) leaves a queued record with a dead pid → flipped to `failed`, which is the truth. The only unreachable case is a queued record with `pid: null` (synchronous spawn failure of the node binary itself) — unprobeable, left untouched, out of scope.

### Pid-reuse false negatives

A recycled pid can make a dead worker look alive; the record then stays `running` — exactly today's behavior, not a new lie. No staleness heuristic (e.g. "running + `updatedAt` older than N minutes ⇒ failed"): a wall-clock threshold is an unfalsifiable magic number that would fabricate failures for legitimately long jobs, and the-bar's Root-causes rule warns against building a mechanism around symptom-shaped evidence. The pid probe is the falsifiable criterion; pid reuse is a documented limitation of this design (this section is that documentation).

### Cleanup semantics — every terminal path

Inventory of terminal paths and their reviewer-runtime cleanup after this change:

| Terminal path | Cleanup mechanism |
|---|---|
| Success / failure / internal timeout (driver alive) | `withAppServer`'s `finally` (exists at base; the runtime is created inside it, so no throw can skip it) |
| `cancel` | `handleCancel` calls `cleanupReviewerRuntime` (exists at base) |
| Dead-worker flip (**new**) | The status reader that persists the flip removes the runtime inside the same lock scope, before the terminal write |

The flip owner is the cleanup owner: whoever writes the terminal state guarantees the invariant "terminal record ⇒ no runtime directory". No sweeper, no separate GC pass (YAGNI); `cleanupReviewerRuntime` stays idempotent so double-cleanup on races is harmless.

### Module surface

- **`lib/process.mjs`** gains the liveness probe (`isProcessAlive`-shaped: `kill(pid, 0)`, ESRCH ⇒ false, anything else ⇒ true). This module already owns the ESRCH-aware kill handling (`terminateProcessTree`).
- **`lib/state.mjs`** exports a lock-guarded read-modify-write over a single job record — the same per-job `withMetadataLock` + atomic-rename + `updatedAt` stamping its writers already use, exposed so a caller can re-check-then-transition atomically. No new locking scheme.
- **`lib/tracked-jobs.mjs`** owns the dead-worker transition (probe → guarded re-check → reviewer cleanup → failed write → log line): job lifecycle transitions live here, beside the running/completed/failed writers. Imports `runtime-home.mjs` for cleanup (no import cycle: runtime-home depends only on state).
- **`lib/job-control.mjs`** (the read side) invokes the reconciliation from `buildSingleJobSnapshot` and `buildStatusSnapshot` for probe-eligible records and consumes the returned (possibly flipped) records.

Names above are indicative; the plan may adjust identifiers, not responsibilities.

### Blast radius deliberately not taken

`result`, `cancel`, `task-resume-candidate`, and enqueue's active-task check read `listJobs` directly and are unchanged: they see the truth after any status read (the flip is persisted), and changing their own read paths is not needed to meet the acceptance criteria. In particular `cancel` keeps its current semantics for a dead-pid job until a status read flips it. A `cancel` racing a concurrent flip is the pre-existing last-writer-wins race `cancel` already has with every terminal writer (it reads the record outside the lock before overwriting); both outcomes are terminal, both trigger idempotent reviewer cleanup, and this design does not widen that race.

## Test seams

Agreed seams — the plan and implementers inherit these and may not invent others:

1. **The companion CLI subprocess surface**: `node scripts/codex-companion.mjs status|result … --json` run against a temp workspace, asserting the JSON payload. Prior art: the `status --wait times out cleanly` and `task --background` tests in `tests/runtime.test.mjs`.
2. **The on-disk state contract**: job record JSON files and job logs under the workspace's jobs dir, and the reviewer runtime directory, located via the exported resolvers (`resolveStateDir`/`resolveJobFile`, `resolveReviewerRuntimeHome`). Prior art: the cancel test (asserts the persisted record) and `tests/isolation.test.mjs` (asserts runtime directories).

Fixtures follow existing conventions: `makeTempDir` workspaces with seeded job records shaped like production records (full field set, ISO timestamps — not minimal parses), real short-lived detached `node -e "setInterval(() => {}, 1000)"` sleeper processes for live/dead pids with `t.after` teardown (cancel-test precedent), `installFakeCodex` only where a real turn is needed. No call-count assertions, no mocking of internal modules.

## Test strategy

New behavior-named file `tests/liveness.test.mjs` (precedent: the patch already adds behavior-named `tests/isolation.test.mjs` rather than growing the 2400-line `runtime.test.mjs`):

1. **Dead-pid running job, single read**: seed a `running` record with the pid of a spawned-then-killed sleeper; `status <id> --json` reports `failed` with `errorMessage` matching `Worker process <pid> exited without recording a result`; the job file on disk is now `failed` with `pid: null` and a `completedAt`; the job log contains the same message. (R1)
2. **Dead-pid queued job**: same flip for a `queued` record (covers the worker-dead-on-arrival/enqueue race). (R1)
3. **Live-pid running job**: seed with a live sleeper's pid; `status <id>` still reports `running` and the record is unchanged — the probe cannot false-positive. (R1 guard)
4. **Status listing flips too**: with a dead-pid job seeded, plain `status --json` shows it out of `running` and as the failed latest-finished job. (R1)
5. **`--wait` terminates promptly**: seed a running record with a live sleeper pid, start `status <id> --wait --timeout-ms 15000 --poll-interval-ms 100 --json` as a child process, kill the sleeper; the wait returns `failed` with `waitTimedOut: false`. Promptness is asserted through `waitTimedOut === false` against a generous timeout, not wall-clock measurement (no flaky timing assertions); the tight poll interval keeps the test fast. (R2)
6. **Reviewer runtime removed on the dead-worker path**: seed a `kind: "plan-review"` dead-pid record plus an existing directory at `resolveReviewerRuntimeHome(workspace, jobId)`; after `status <id>`, the record is `failed` and the directory no longer exists. (R3)

Existing coverage retained, not duplicated: the upstream `status --wait times out cleanly` test (pid-less running record stays running — the probe-eligibility boundary) and the existing `withAppServer`-finally and cancel cleanup tests must stay green; the full suite (`node --test tests/`) is the regression gate. (R4)

## Verification loop (for the plan to turn into tasks)

The nix store copy is read-only; all edits happen in a scratch checkout of the pinned upstream, and land in the repo only as a regenerated patch.

```sh
WORKTREE=<absolute path to this repo worktree>
scratch=$(mktemp -d)
gh repo clone openai/codex-plugin-cc "$scratch"
git -C "$scratch" checkout db52e28f4d9ded852ab3942cea316258ae4ef346
git -C "$scratch" apply "$WORKTREE/patches/agent-plugins/codex-plugin-cc.patch"
git -C "$scratch" add -N .        # intent-to-add so patch-created files appear in git diff

# edit loop:
(cd "$scratch" && node --test tests/)
# node v22.22.2 is on PATH (repo ships pkgs.nodejs) — adequate; fallback per user convention:
#   devenv -O languages.javascript.enable:bool true shell -- node --test tests/

# regenerate the patch (run `git -C "$scratch" add -N .` again if new files were created, e.g. tests/liveness.test.mjs):
git -C "$scratch" diff db52e28f4d9ded852ab3942cea316258ae4ef346 > "$WORKTREE/patches/agent-plugins/codex-plugin-cc.patch"

# bump patchRevision 3 -> 4 in lib/agent-plugins.nix, then:
just build
```

`just build` is the repo's verification step (successful Nix eval + build, which re-applies the regenerated patch with `patch -p1`). The issue's manual demo (start a reviewer, `kill -9` its worker, observe `failed` + runtime gone) is optional corroboration; the committed proof is the test suite plus `just build`.

## Out of scope

- Lifting the reviewer `--background` guard and any bridge/skill rewrite — issue #3, blocked on this one.
- Any GC daemon, sweeper, or periodic reconciliation process.
- Broker lifecycle changes (`broker-lifecycle.mjs`, app-server broker).
- Healing readers other than the status surface (`result`, `cancel`, resume-candidate keep their current read paths; they benefit via persistence).
- A staleness/`updatedAt` heuristic for pid-reuse false negatives (documented limitation instead).
- Handling active records without a finite pid (unreachable from real launch paths; enshrined by the upstream wait-timeout test).
- Contributing the change upstream.

## Auto-resolved decisions

### Persist the dead-pid→failed transition vs report-only
- **Question:** Should the status read persist the `failed` transition into the job record (write-on-read under the metadata lock), or only report `failed` in the returned snapshot while the record stays `running`?
- **Choice:** Persist, under the per-job metadata lock, with a re-check inside the lock.
- **Grounding:** the-bar "Truthful terminal states" (status surfaces are truth — the record *is* the status surface; a lying record with a truthful projection still lies to `result`/`cancel`/resume-candidate) and DRY (job state has exactly one authoritative home). Issue AC2 needs `--wait` to terminate on the transition, which falls out of the persisted flip with zero changes to the wait loop.
- **Alternative considered:** Report-only derivation — rejected; every reader re-derives the probe, consumers disagree about whether the job is active, and the authoritative record keeps lying.

### Reconciliation point: status snapshot builders, not `listJobs`
- **Question:** Should the probe run in `listJobs` (healing every consumer) or only in the status snapshot builders (`buildSingleJobSnapshot`, `buildStatusSnapshot`)?
- **Choice:** The status snapshot builders.
- **Grounding:** Issue text scopes the probe to "a single `codex-companion status` read, or any status listing". `listJobs` also runs on write paths (`saveState`, pruning), where triggering flips would turn reads into writes mid-write; it would also silently change `cancel`'s view of active jobs. Persistence makes all other consumers consistent one status read later.
- **Alternative considered:** Probe in `listJobs` — rejected for blast radius and out-of-scope behavior changes to `cancel`/enqueue guards.

### Probe eligibility: only active records carrying a finite pid
- **Question:** Exactly which records are probed, given the enqueue race (queued record written after the worker spawn) and spawn failure leaving `pid: null`?
- **Choice:** Probe iff `status ∈ {queued, running}` and `pid` is a finite number. Pid-carrying queued records are safe to probe: the recorded pid *is* the worker pid (the spawned child runs `task-worker` directly), so a dead pid on a queued record always means the worker died without a terminal write. Active records without a finite pid are left untouched.
- **Grounding:** Verified from `enqueueBackgroundTask`/`spawnDetachedTaskWorker` (child pid == worker pid, no intermediary) and `runTrackedJob` (worker overwrites with the same `process.pid`). The upstream test "status --wait times out cleanly" seeds a pid-less `running` record and asserts it stays running — the pid-less rule is enshrined behavior.
- **Alternative considered:** "null-pid queued records older than a threshold ⇒ failed" — rejected: the only path to that state is a synchronous spawn failure of the node binary itself (effectively unreachable), and an age threshold is an unfalsifiable magic number (YAGNI).

### Probe semantics: only ESRCH means dead
- **Question:** How does the probe classify `kill(pid, 0)` outcomes?
- **Choice:** ESRCH ⇒ dead; success, EPERM, or any other errno ⇒ alive.
- **Grounding:** the-bar "Root causes"/"Truthful terminal states" cut both ways: fabricating a failure for a live job is worse than leaving a dead one running for another read. EPERM proves a process exists. `terminateProcessTree` in `process.mjs` already treats ESRCH as the only "missing process" signal on POSIX.
- **Alternative considered:** Treating EPERM/unknown errnos as dead — rejected; it would flip records on uncertain evidence.

### Driver-pid semantics: already uniform, no writer changes
- **Question:** Do `handleTaskWorker`/`runTrackedJob`/`enqueueBackgroundTask` need pid-field updates so the probe always sees the driving process?
- **Choice:** No writer changes. Invariant (documented in this spec): `pid` is the pid of the process driving the job (foreground client, or the detached `task-worker` child — which the enqueue-recorded `child.pid` already equals); terminal writers set it to null.
- **Grounding:** Verified in code: `runTrackedJob` writes `pid: process.pid`; `spawnDetachedTaskWorker` spawns the worker directly so `child.pid` is the worker pid; the worker's running write records the same pid. Evidence record pid 1818 was the foreground client — the process whose death froze the job — confirming the foreground client is the right probe target.
- **Alternative considered:** Adding a separate `workerPid`/`driverPid` field — rejected; the existing field already carries exactly the right value on every path (YAGNI, DRY).

### Pid-reuse false negatives: no staleness mitigation
- **Question:** Should a `running` record with an implausibly stale `updatedAt` also be flipped, to mitigate a recycled pid masking a dead worker?
- **Choice:** No. The pid probe is the sole criterion; pid reuse degrades to today's behavior (record stays running) and is documented as a known limitation in this spec.
- **Grounding:** YAGNI and the-bar "Root causes" (a wall-clock threshold is a mechanism built around symptom-shaped evidence, and would fabricate failures for legitimately long jobs — reviewer timeout is already 840s, and long tasks have no bound). "Tests that can fail": a threshold has no falsifiable boundary to test. The conservative failure direction (wrongly-alive, never wrongly-dead) preserves truthfulness.
- **Alternative considered:** `updatedAt`-staleness flip — rejected as an unfalsifiable heuristic that can lie in the dangerous direction.

### Cleanup ownership and ordering on the dead-worker path
- **Question:** Who removes the leaked reviewer runtime when the dead-worker flip fires, and in what order relative to the record write?
- **Choice:** The status reader that persists the flip removes the runtime for `kind === "plan-review"` jobs, inside the same lock scope, *before* writing the terminal record.
- **Grounding:** Issue AC3 ("after any terminal state … the directory no longer exists") makes the terminal-state writer the natural owner of the invariant. Ordering: cleanup-then-write self-heals on a crash between the steps (record still active ⇒ next read retries both); write-then-cleanup would leave a permanent leak behind a terminal record no reader revisits. `cleanupReviewerRuntime` is already idempotent and path-guarded, so racing double-cleanup is harmless. No sweeper (issue OUT scope, YAGNI).
- **Alternative considered:** Cleanup outside the lock after the write (smaller lock hold) — rejected; the lock holds for one small `rmSync` longer, versus an unhealable leak window.

### Failed-record shape and error text
- **Question:** Exactly what does the flipped record carry?
- **Choice:** `status: "failed"`, `phase: "failed"`, `errorMessage: "Worker process <pid> exited without recording a result."`, `pid: null`, `completedAt` = detection time, `updatedAt` stamped by the write; the same message appended to the job log. No new `failedAt` field.
- **Grounding:** Matches the failure shape `runTrackedJob`'s catch path and `handleCancel` already write (`errorMessage` + `phase: "failed"`/terminal + `pid: null` + `completedAt`), so every renderer and consumer handles it without changes. The message names the dead worker pid (issue AC1); "worker" is the issue's own term and, per the driver-pid invariant, denotes whichever process the record's `pid` names — the foreground client or the detached `task-worker` — so the wording is truthful on both paths. Log line: the-bar "The log stream is the debugger", with `appendLogLine` precedent from cancel — and it is the channel through which the human-rendered status report surfaces the error (verified: `renderJobStatusReport` prints the log preview, not `errorMessage`). `failedAt` has no precedent and no consumer (YAGNI).
- **Alternative considered:** A distinct status value like `"lost"`/`"orphaned"` — rejected; it would fork the closed status set every consumer switches on, for no consumer that needs the distinction. The truth the issue demands is "failed, and here is why".

### Module placement of probe, guard, and transition
- **Question:** Which modules gain which responsibilities?
- **Choice:** Liveness probe in `lib/process.mjs`; lock-guarded single-record read-modify-write exported from `lib/state.mjs`; the dead-worker transition (probe + re-check + cleanup + write + log) in `lib/tracked-jobs.mjs`; invocation from `lib/job-control.mjs`'s two snapshot builders.
- **Grounding:** Single responsibility along existing boundaries: `process.mjs` already owns ESRCH-aware process handling, `state.mjs` owns the per-job lock and atomic writes, `tracked-jobs.mjs` owns every existing lifecycle transition, `job-control.mjs` owns the read surface. No import cycles (runtime-home → state only).
- **Alternative considered:** Everything inline in `job-control.mjs` with `withMetadataLock` exported raw — rejected; it would put a lifecycle write in the read module and leak the raw lock primitive to a second home.

### Test seam and test file
- **Question:** Where and how is the new behavior tested?
- **Choice:** New behavior-named `tests/liveness.test.mjs`; seams are the CLI subprocess (`--json` payloads) and the on-disk state contract (job files, job log, reviewer runtime dir via exported resolvers); real detached sleeper processes provide live/dead pids.
- **Grounding:** the-bar "Tests that can fail" (observable behavior, production-shaped fixtures); node stack standard "one test file per behaviour, named for the behaviour"; direct prior art in the suite — the cancel test (real sleeper + persisted-record assertions), the wait-timeout test (seeded records through `resolveStateDir`), and the patch's own `tests/isolation.test.mjs` (new behavior-named file, runtime-dir assertions).
- **Alternative considered:** Growing `tests/runtime.test.mjs` — rejected; 2400+ lines already, and a failing file should name the broken behavior by itself.

### Listing reconciles only the records it surfaces (grill round)
- **Question:** Should the status listing probe every active record in the workspace, or only the ones its existing session filter surfaces?
- **Choice:** Only the surfaced (post-session-filter) active records.
- **Grounding:** Scope tightness — the listing's job is the view it renders; probing hidden records would make a read in session A silently rewrite session B's records. Cross-session healing still exists: `buildSingleJobSnapshot` applies no session filter, so `status <id>` heals any job, and each session's own listing heals its jobs. The issue's demo and ACs all read the affected job directly.
- **Alternative considered:** Probe all active records workspace-wide on every listing — rejected as hidden write amplification with no acceptance criterion needing it.

### Lock-timeout during the flip propagates (grill round)
- **Question:** If acquiring the per-job metadata lock for the flip times out (5s), should the status read swallow the error and return the stale record?
- **Choice:** Propagate the error; the status read fails loudly.
- **Grounding:** the-bar "Root causes" (no catch to mute an error) and "Fail loud". The per-job lock is held for milliseconds; a 5s acquisition timeout means something is genuinely broken, and returning a stale `running` record would be exactly the lie this issue removes. `upsertJob` already propagates the same error on every write path.
- **Alternative considered:** Degrade to report-only on lock timeout — rejected; it reintroduces the two-homes-of-truth problem in the rare case where truth matters most.

### Verification-loop tooling
- **Question:** Scratch-checkout mechanics and node runtime for the dev loop?
- **Choice:** `gh repo clone openai/codex-plugin-cc` + `git checkout db52e28f…` + `git apply` the repo patch + `git add -N .`; system node v22.22.2 runs `node --test tests/` directly; regenerate with `git diff <pinned-rev>` into the patch file; bump `patchRevision` 3→4; `just build`.
- **Grounding:** `flake.lock` pins `openai/codex-plugin-cc` at `db52e28f4d…`; CLAUDE.md mandates patch-file ownership and `just build` as verification; node on PATH is v22.22.2 (≥22 requirement met), so the devenv ad-hoc shell is only the fallback per the user's global convention. `git add -N` is required so patch-created files (and the new test file) appear in `git diff` against the pinned base.
- **Alternative considered:** Editing the nix-store copy — impossible/forbidden (read-only, CLAUDE.md); a devenv-first loop — unnecessary since the system node already satisfies the version bound.
