# Worker Post-Mortem Trail Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** A dead detached worker becomes diagnosable after the fact, from disk, in a later session — its own stdout/stderr is captured into the job log it already owns, every job record of an ending session reaches a truthful terminal state and is *kept* (bounded by the existing `MAX_JOBS` retention), and a status read reports an alive-but-overdue worker against a `deadlineAt` stamped at enqueue — delivered as a regenerated `patches/agent-plugins/codex-plugin-cc.patch` at `patchRevision = 6`.

**Architecture:** Three narrow extensions of machinery issues #2 and #3 already built. (1) `spawnDetachedTaskWorker` adopts `spawnBrokerProcess`'s exact stdio shape (`fs.openSync(logFile, "a")` → `stdio: ["ignore", logFd, logFd]` → `child.unref()` → `fs.closeSync(logFd)`), and `readJobProgressPreview`'s line filter tightens from "starts with `[`" to "starts with a full ISO-8601 timestamp" so captured bytes cannot reach the status surface. (2) The SessionEnd hook's per-job body changes from *terminate → cleanup → remove* to *reconcile → terminate → cleanup → terminalize → retain*, and calls the state layer's existing `MAX_JOBS` prune once per state dir afterwards. (3) `enqueueBackgroundTask` stamps `deadlineAt = createdAt + timeoutMs`, and `enrichJob` derives non-persisted `overdue`/`overdueBy` beside `elapsed`/`duration`/`phase`. All plugin edits happen in a scratch clone of `openai/codex-plugin-cc` at pinned rev `db52e28f4d9ded852ab3942cea316258ae4ef346` and land in this repo only as the regenerated zero-context patch. Design authority: `.claude/specs/2026-08-12-worker-post-mortem-design.md` — this plan implements it, it does not redesign it.

**Tech stack:** Node.js ≥ 22 ESM (`.mjs`, stdlib only), `node --test` runner, git-generated unified diff patch, Nix (`just build` applies the patch via `patch -p1` inside `lib/agent-plugins.nix`).

## Global Constraints

- Pinned upstream revision: `db52e28f4d9ded852ab3942cea316258ae4ef346` (`openai/codex-plugin-cc`); the flake input never changes.
- The patch file `patches/agent-plugins/codex-plugin-cc.patch` is the only plugin-code artifact. Never commit the scratch clone; never edit anything under `/nix/store` (read-only). The only files that change in the worktree across this whole plan are `patches/agent-plugins/codex-plugin-cc.patch`, `lib/agent-plugins.nix`, and this plan document.
- `patchRevision` in `lib/agent-plugins.nix` goes `5` → `6` exactly once (Task 1), never higher. `codexVersion` embeds it, so the built closure path becomes `codex-plugin-cc-1.0.6-nix.db52e28f.p6`.
- The committed patch is zero-context: regenerate with `git diff -U0 <pinned-rev>`, apply with `git apply --unidiff-zero` (plain `git apply` rejects zero-context hunks; nix's `patch -p1` handles them by line number).
- **Terminal** = `completed` | `failed` | `cancelled`. **Active** = `queued` | `running`. There is no sixth status — these five are the only values `runTrackedJob`, `handleCancel`, `reconcileWorkerLiveness`, `enqueueBackgroundTask` and the SessionEnd hook write.
- Issue #2's invariants are extended, never modified: `reconcileWorkerLiveness`'s flip semantics, its *cleanup-precedes-the-terminal-write* ordering rule, and its concurrent-writer bail-out (`updateJobRecord`'s mutate-returns-`null` protocol) stay byte-stable. Overdue detection is read-only and lives in `enrichJob`, not in `reconcileWorkerLiveness`.
- Issue #3's shape is untouched: the worker stays detached, SessionEnd still terminates the live workers of the ending session, and the reviewer's `840000` ms default is not changed.
- An overdue worker is **reported, never flipped and never killed**. No new kill path, no watchdog, no supervisor.
- Exact strings, copied verbatim into code:
  - session-end terminal reason: `Session ended while the job was still ${current.status}.`
  - dead-worker message (pre-existing, unchanged): `Worker process ${pid} exited without recording a result.`
  - overdue detail line: `  Overdue: ${job.overdueBy} past the recorded deadline ${job.deadlineAt}; the job is still ${job.status}. Cancel: /codex:cancel ${job.id}`
  - overdue table-cell suffix: `(overdue by ${job.overdueBy})`
- Canonical test command, run from the scratch clone root (the `env -u` scrub is mandatory per `CLAUDE.md`: without it 4 upstream tests fail spuriously under a live Claude-session env, and every run leaks `codex-plugin-test-*` state dirs into `~/.claude/plugins/data/codex-nix-codex/state/`):
  `env -u CLAUDE_PLUGIN_DATA -u CODEX_COMPANION_SESSION_ID -u CODEX_COMPANION_TRANSCRIPT_PATH node --test tests/*.test.mjs`
  Baseline at patch p5 (verified before any change): `# tests 107 / # pass 103 / # fail 0 / # skipped 4`.
- `just build` (run in the worktree) is the repo verification step; it must end green in every task. It may be slow on the first run of a task chain; treat it as the final repo-level gate of each task.
- Worktree: `/Users/anis/tmp/nix-config/.claude/worktrees/issue-10-worker-post-mortem` (branch `worktree-issue-10-worker-post-mortem`, base `165a3b0`, design commit `98d5377`). Every commit message ends with exactly:
  ```
  Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_018ND9WQgzw7ccKYruN3pRaF
  ```
  Never disable signing (no `-c commit.gpgsign=false`, no `--no-gpg-sign`). A `%G?` verification warning is a known local `allowedSignersFile` gap, not a signing failure — ignore it.
- Do not push and do not open a PR; that is the ship phase's job.

## Scratch clone workflow (used by every task)

The scratch clone lives at a fixed path outside the repo and is rebuilt deterministically at the start of every task from the currently committed patch, so tasks are independent and a half-edited tree can never leak between implementers. **Do not reuse any pre-existing clone under a session scratchpad — those are read-only references and may already carry edits.**

```bash
WORKTREE=/Users/anis/tmp/nix-config/.claude/worktrees/issue-10-worker-post-mortem
SCRATCH=/tmp/codex-plugin-cc-issue-10-scratch
PIN=db52e28f4d9ded852ab3942cea316258ae4ef346

if [ ! -d "$SCRATCH/.git" ]; then
  gh repo clone openai/codex-plugin-cc "$SCRATCH"
fi
git -C "$SCRATCH" reset --hard
git -C "$SCRATCH" checkout --force --detach "$PIN"
git -C "$SCRATCH" clean -ffd
test -z "$(git -C "$SCRATCH" status --porcelain)"   # must print nothing / exit 0
git -C "$SCRATCH" apply --unidiff-zero "$WORKTREE/patches/agent-plugins/codex-plugin-cc.patch"
git -C "$SCRATCH" add -N .    # intent-to-add, so patch-created files appear in git diff
```

Regeneration (end of every task, after the suite is green — re-run `add -N .` first, because `tests/worker-postmortem.test.mjs` is a new file):

```bash
git -C "$SCRATCH" add -N .
git -C "$SCRATCH" diff -U0 "$PIN" > "$WORKTREE/patches/agent-plugins/codex-plugin-cc.patch"
```

## File structure

Scratch clone (all paths relative to `$SCRATCH`):

- `plugins/codex/scripts/codex-companion.mjs` — `spawnDetachedTaskWorker` gains a log fd (Task 1); `enqueueBackgroundTask` stamps `deadlineAt` (Task 3); the private `isActiveJobStatus` is deleted in favour of the shared export (Task 2).
- `plugins/codex/scripts/lib/job-control.mjs` — `readJobProgressPreview`'s filter tightens to a full ISO prefix (Task 1); `enrichJob` derives `overdue`/`overdueBy` and uses `isTerminalJobStatus` for `duration` (Task 3).
- `plugins/codex/scripts/lib/state.mjs` — two stateDir-paired helpers added, with the `cwd` variants delegating to them: `updateJobRecordInStateDir`, `pruneJobRecordsInStateDir` (Task 2).
- `plugins/codex/scripts/lib/tracked-jobs.mjs` — `isActiveJobStatus` exported and reused by `isWorkerProbeEligible` (Task 2); `isTerminalJobStatus` exported (Task 3). `reconcileWorkerLiveness` itself is not modified in any task.
- `plugins/codex/scripts/session-lifecycle-hook.mjs` — `cleanupSessionJobs` terminalizes and retains instead of deleting, and prunes per state dir (Task 2).
- `plugins/codex/scripts/lib/render.mjs` — the active-jobs table's `Elapsed` cell gains an overdue suffix; `pushJobDetails` gains one overdue line (Task 4).
- `plugins/codex/commands/status.md` — the preserved-fields sentence keeps the overdue marker (Task 4).
- `tests/worker-postmortem.test.mjs` — new behaviour-named file; created in Task 1 and appended to in Tasks 2–4 (12 tests total).
- `tests/runtime.test.mjs` — the existing `session end fully cleans up jobs for the ending session` test is deliberately rewritten and renamed (Task 2). This is an expected, designed change, not a regression.
- `tests/commands.test.mjs` — one docs-contract test appended (Task 4).

Repo worktree:

- `patches/agent-plugins/codex-plugin-cc.patch` — regenerated in all four tasks.
- `lib/agent-plugins.nix` — `patchRevision = 5` → `6` (Task 1 only).

## Test seams

Inherited from the design — implementers test at these and nowhere else. A task needing a new seam is a plan bug, not an implementer's call.

1. **The companion CLI subprocess surface** — `node <SCRIPT> task|status|result … --json` run as child processes against a temp workspace with the fake codex on PATH (`installFakeCodex(binDir, behavior)` / `buildEnv(binDir)` from `tests/fake-codex-fixture.mjs`). Prior art: `tests/reviewer-detach.test.mjs`, the background-task tests in `tests/runtime.test.mjs`.
2. **The on-disk state contract** — job record JSON, the job `.log`, and reviewer runtime dirs located via the exported resolvers (`resolveStateDir`, `resolveJobFile`, `resolveJobLogFile`). Prior art: `tests/state.test.mjs`, `tests/liveness.test.mjs`, `tests/isolation.test.mjs`.
3. **The SessionEnd hook as a subprocess** — `node scripts/session-lifecycle-hook.mjs SessionEnd` with the hook JSON on stdin and `CODEX_COMPANION_SESSION_ID` in env. Prior art: the session-end test in `tests/runtime.test.mjs`.
4. **A narrow rendered-text seam** — assertions over the markdown `status` output (prior art: the active-jobs table assertions in `tests/runtime.test.mjs`) and over `plugins/codex/commands/status.md`'s text (prior art: the docs assertions in `tests/commands.test.mjs`).

`spawnDetachedTaskWorker` stays module-private: AC1 is observable at seams 1 and 2 (run a background job through the CLI, read its log off disk). No call-count assertions, no wall-clock measurements, no process-tree/`ppid` assertions — every assertion is a printed payload, an on-disk record, a file's existence, or rendered text.

## Auto-resolved decisions

### Task granularity: four tasks along acceptance-criterion / artifact boundaries
- **Question:** One task for the whole change, or several — and along which boundary?
- **Choice:** Four: (1) AC1 capture + preview filter + `patchRevision` bump, (2) AC2 SessionEnd terminalize/retain/prune + the two state helpers + the shared active predicate + the deliberate `runtime.test.mjs` rewrite, (3) AC3 record and derive (`deadlineAt`, `overdue`/`overdueBy`, `--json`), (4) AC3 render (table cell, detail line, `status.md`) + the whole-issue verification. Each task ends in a green suite, a green `just build`, and one worktree commit.
- **Grounding:** writing-plans right-sizing — a reviewer can reject the overdue rendering wording while approving the derivation, or reject the SessionEnd policy while approving the fd capture; the slices map one-to-one onto AC1 / AC2 / AC3-record / AC3-render. Precedent: `.claude/plans/2026-08-11-detached-reviewer-bridge.md` and `.claude/plans/2026-08-11-truthful-job-terminal-states.md` used the same per-artifact slicing against the same patch workflow.
- **Alternative considered:** Three tasks with AC3 whole — rejected: the rendering change is prose the reviewer must read against `status.md`'s constraints, and it would ride in the same reviewable unit as the arithmetic. A fifth task for final verification alone — rejected: it would change no file, so it could not carry a falsifiable deliverable, and its checks fold naturally into Task 4.

### Scratch clone at a fixed /tmp path, rebuilt per task, never a pre-existing one
- **Question:** Where does the scratch upstream clone live, does it persist between tasks, and may the implementer reuse an already-patched clone left by an earlier phase?
- **Choice:** Fixed path `/tmp/codex-plugin-cc-issue-10-scratch`; every task starts with `reset --hard` + `checkout --force --detach <pin>` + `clean -ffd` + a clean-tree assertion + apply the currently committed patch. Clone reuse is a network optimisation only; correctness never depends on prior task state. Any clone under a session scratchpad is treated as read-only reference material and is never used for regeneration.
- **Grounding:** `CLAUDE.md`'s binding patch-editing workflow ("work in a scratch clone of the pinned upstream rev … regenerate with `git diff -U0 <pin>`"); the design's Verification-loop block; the issue-3 plan proved this exact loop across three tasks. The clean-tree assertion is what makes `git diff -U0 $PIN` a function of the committed patch alone.
- **Alternative considered:** `mktemp -d` fresh clone per task (a network round-trip every task, no correctness gain); a git-ignored directory inside the worktree (risks an accidental commit of the whole upstream tree).

### `patchRevision` bumps in Task 1, not in the last patch-touching task
- **Question:** When does `patchRevision` go 5→6, given four patch-touching commits?
- **Choice:** Task 1, together with the first regenerated patch. Tasks 2–4 leave it at 6 and Task 4 re-verifies it.
- **Grounding:** `codexVersion = "${upstream}-nix.${shortRev}.p${patchRevision}"`, so bumping at the first content change keeps every intermediate commit's version string truthful — the same "truthful state" discipline this issue applies to job records, applied to version metadata. AC4 requires one bump total, which this satisfies. Same decision and grounding as the issue-2 and issue-3 plans.
- **Alternative considered:** Bumping in the final task — rejected: Tasks 1–3 would ship p5-labelled builds containing p6 content.

### `isActiveJobStatus` is exported in Task 2, `isTerminalJobStatus` in Task 3
- **Question:** The design says export both predicates from `tracked-jobs.mjs`. In which task does each land?
- **Choice:** `isActiveJobStatus` in Task 2 (its consumers — the hook, `isWorkerProbeEligible`, and `codex-companion.mjs`'s deleted private copy — all land there); `isTerminalJobStatus` in Task 3 (its consumer, `enrichJob`'s `duration`, lands there).
- **Grounding:** writing-plans: every task ends in an independently testable deliverable, and no commit should contain an export with no consumer. The design fixes *where* the predicates live (`tracked-jobs.mjs`) and *that* there is one home each, not which commit introduces them.
- **Alternative considered:** Both in Task 2 — rejected: `isTerminalJobStatus` would sit unused for one commit, which a reviewer would rightly flag as dead code.

### `isTerminalJobStatus`'s consumer is `enrichJob`'s `duration`, not the SessionEnd hook
- **Question:** The hook needs "not active"; should it read `isTerminalJobStatus(status)` (the design's terminal predicate) or `!isActiveJobStatus(status)`?
- **Choice:** The hook uses `!isActiveJobStatus(...)`; `isTerminalJobStatus` is consumed by `enrichJob`'s `duration` computation, which today open-codes the exact same three-way comparison on a line Task 3 already edits.
- **Grounding:** The two are not equivalent for a record with a missing or unknown `status` (a legacy or truncated record): `isTerminalJobStatus(undefined)` is `false`, so a `isTerminalJobStatus` gate would fall through to *terminate and relabel* such a record, inventing a kill and a `cancelled` write for something that was never active. `!isActiveJobStatus` retains it untouched, which is the conservative reading of "SessionEnd deletes no job record". `enrichJob`'s `duration` line is exactly `completed || failed || cancelled` today, so the substitution there is semantics-preserving and lands on a line the task touches anyway.
- **Alternative considered:** Leaving `isTerminalJobStatus` unused (dead export), or converging every inline comparison in `job-control.mjs` (the design explicitly rules that out as churn on untouched lines).

### A dedicated falsifiable test for the preview-filter tightening
- **Question:** The design's test list has no test that fails if the `readJobProgressPreview` filter is *not* tightened (captured crash output happens not to start with `[`, so R2's assertion passes either way). Does the tightening ship untested?
- **Choice:** No — Task 1 adds one seeded-state test that pins the latent pre-existing defect the design identified: a `failed` job whose log carries an `appendLogBlock` "Final output" block whose body line starts with `[` (a `[Blocking]`-style tag) must not appear in `progressPreview`. It fails at p5 (the body line passes `startsWith("[")` and has its bracket group eaten by `stripLogPrefix`) and passes after the tightening.
- **Grounding:** The design's R2 requires the exclusion to be "structural (a property of the filter) rather than incidental", and its AC1 preview decision documents the block-body leak as a latent defect the tightening closes. writing-plans: "every task carries at least one verification line that could fail" — without this test the filter change has none.
- **Alternative considered:** Relying on the AC1 capture test's `progressPreview` assertion — rejected: it passes at p5 and after the change with or without the tightening, so it cannot gate the filter edit. Manufacturing a V8 heap abort — rejected by the design (it would test node's crash formatting, not the plugin).

### AC1's capture proof uses the `auth-run-fails` fixture, verified against the live tree
- **Question:** Which deterministic failure makes the worker write to fd 2, and what exactly does it write?
- **Choice:** `installFakeCodex(binDir, "auth-run-fails")` on a plain `task --background` run. Probed against the patched tree at p5: the record lands `status: "failed"`, `errorMessage: "authentication expired; run codex login"` (exactly), and the job log currently holds only three `[iso]`-prefixed lines — `Starting Codex Task.`, `Queued for background execution.`, `Starting Codex task thread.` — with the error text absent. So the test's "an unprefixed line containing the error text exists in the log" assertion fails at p5 and can only pass through the redirected fd.
- **Grounding:** The fixture throws inside its `thread/start` handler; `AppServerClient` turns the JSON-RPC error into `createProtocolError(message.error.message)`, so `error.message` is that string verbatim; `runTrackedJob` records and rethrows; `handleTaskWorker` does not catch; `main().catch` writes `${error.message}\n` to `process.stderr`. No code path appends that text to the log. The existing foreground test `task reports the actual Codex auth error when the run is rejected` pins the same string on the foreground path.
- **Alternative considered:** The `--timeout-ms 1000` + `interruptible-slow-task` failure (the issue-3 plan's shape) — works identically but costs ~1 s of wall clock per run for no extra evidence. A fake codex that writes junk to its own stderr — rejected by the design: the codex child is spawned with piped stdio and its stderr is buffered in memory, so it never reaches the worker's fd 2.

### Test-count budget and per-task suite expectations
- **Question:** How do the design's 13 test-strategy items map onto test cases and files, and what count does each task's gate expect?
- **Choice:** 12 tests in the new `tests/worker-postmortem.test.mjs` (3 in Task 1, 5 in Task 2, 3 in Task 3, 1 in Task 4), 1 test appended to `tests/commands.test.mjs` (Task 4), and 1 existing `runtime.test.mjs` test rewritten in place (count unchanged). Expected gates: after Task 1 `# tests 110 / # pass 106 / # fail 0 / # skipped 4`; after Task 2 `115 / 111 / 0 / 4`; after Task 3 `118 / 114 / 0 / 4`; after Task 4 `120 / 116 / 0 / 4`.
- **Grounding:** Baseline 107/103/0/4 verified at p5 before any change; the 4 skips are unchanged upstream skips (`test.skip("upstream-only: …")`). The arithmetic is stated per task so an implementer that silently loses a test is caught by its own gate.
- **Alternative considered:** Leaving counts to the implementer — rejected: a test that never registers (a typo'd `test(` name, an early `return`) is invisible without an expected total.

### "Not overdue" is one test with two seeded records
- **Question:** The design's item 11 covers two negative cases (a future `deadlineAt`, and no `deadlineAt` at all). One test or two?
- **Choice:** One test, two seeded records, two `status <id> --json` reads.
- **Grounding:** Both cases exercise the identical code path — `formatElapsedDuration` returning `null` for an end earlier than the start and for an unparseable start — so a failure in either names the same defect. The issue-3 plan split its two guard refusals precisely because they were *different* predicates; that reasoning does not transfer here.
- **Alternative considered:** Two tests — rejected: duplicate scaffolding for one assertion, with no extra diagnostic resolution.

### The deadline-stamping test also covers an explicit `--timeout-ms` non-reviewer job
- **Question:** The design's item 9 covers the reviewer default (840 000 ms) and a plain background task (no deadline). Is a non-reviewer job with an explicit timeout worth a third assertion?
- **Choice:** Yes — the same test adds `task --background --timeout-ms 60000` and asserts an exact 60 000 ms delta.
- **Grounding:** It is the assertion that proves `deadlineAt` is driven by `request.timeoutMs` and not by `reviewer`, which is exactly the design's rule ("a deadline only exists when a timeout does"). It costs one CLI call in a test that already has the fixture set up. Probe-verified at p5: a reviewer background enqueue stores `request.timeoutMs: 840000` and a plain one stores `null`.
- **Alternative considered:** Reviewer-only coverage — rejected: it would leave the reviewer default and the deadline arithmetic indistinguishable if someone hard-coded 840 000.

### The overdue detail line's exact wording
- **Question:** The design requires the per-job detail line to state the overrun, the recorded deadline, that the worker is still alive, and the cancel command. What is the exact string, given that plan-prose copied into code must describe what the code actually does?
- **Choice:** `  Overdue: ${job.overdueBy} past the recorded deadline ${job.deadlineAt}; the job is still ${job.status}. Cancel: /codex:cancel ${job.id}` — "still `${job.status}`" rather than any claim about a liveness probe, and the cancel command inline.
- **Grounding:** Aliveness is expressed as the record's own status because that is the only thing the renderer can assert truthfully: `enrichJob` only marks an active job overdue, and both snapshot builders run `reconcileWorkerLiveness` before `enrichJob` — but a `queued` record with no usable `pid` is *not probe-eligible*, so it never "answered a probe". Saying "the worker answered its liveness probe" would be false for exactly that record. The inline cancel command is the design's requirement (R7: reported "alongside the already-present `/codex:cancel` action"); it duplicates the separate `Cancel:` hint that `renderJobStatusReport` already emits, which is accepted because `commands/status.md` tells the model to drop prose outside the table for a bare `/codex:status`, so the line must be self-contained.
- **Alternative considered:** Asserting the probe result in the text (false for pid-less queued records); omitting the cancel command and relying on the table's `Actions` cell (leaves the `Live details:` block without a remedy and contradicts the design); adding `showCancelHint: true` to the listing's detail options (changes output for every active job, beyond scope).

### The overdue marker rides the `Elapsed` cell through a `formatElapsedCell` helper
- **Question:** How is the table cell composed, given `job.elapsed` can in principle be `null`?
- **Choice:** A module-private `formatElapsedCell(job)` in `render.mjs` that returns `job.elapsed ?? ""` when not overdue and `[job.elapsed, "(overdue by …)"].filter(Boolean).join(" ")` when overdue.
- **Grounding:** The design fixes the cell (`<elapsed> (overdue by <overdueBy>)`) and the reason (`commands/status.md`'s preserved-field list names elapsed, so a new column could be dropped on re-render). The `filter(Boolean)` join avoids emitting a leading space for a record whose `createdAt` is unparseable but whose `deadlineAt` is set — cheap, and it keeps the row well-formed rather than inventing a placeholder token.
- **Alternative considered:** Inlining the ternary in the already-long row template literal (harder to read and to review); a `"unknown"` placeholder for a missing elapsed (invents a token no other cell uses).

### The SessionEnd hook keeps exactly one `try/catch`, around the existing terminate call
- **Question:** Should the new reconcile call and the new guarded terminal write be wrapped in `try/catch` so one bad record cannot abort the rest of the teardown?
- **Choice:** No. The only `catch` stays the pre-existing one around `terminateProcessTree` ("Ignore teardown failures during session shutdown"). Reconciliation and the terminal write propagate, and the hook's existing `main().catch` reports to stderr and exits 1.
- **Grounding:** Parity with today's behaviour: `removeJobFromStateDir` is currently uncaught, so a lock-timeout already aborts the hook. Swallowing a failed terminal write would leave a permanently lying `running` record with no visible signal — the exact class of lie issue #2 removed — whereas an aborted hook is loud and the next status read still heals the record. Verified non-throwing on the paths that worried me: `resolveWorkspaceRoot` catches (falls back to `cwd`), `resolveStateDir` catches its `realpathSync`, `ensureStateDir` is `mkdirSync(recursive)`, and `isProcessAlive` catches.
- **Alternative considered:** Per-job `try/catch` around everything — rejected: it converts a broken lock into silent data loss and adds a policy the design never asked for.

### A record with a missing or unknown status is retained untouched
- **Question:** The hook's branch is "still active after reconciliation". What happens to a record whose `status` is absent or unrecognised (a legacy or truncated record)?
- **Choice:** It is skipped: not killed, not relabelled, retained with its log. This follows from gating on `!isActiveJobStatus(current.status)`.
- **Grounding:** AC2 is "SessionEnd deletes no job record", and the design's boundary-case paragraph resolves the neighbouring cases (a pid-less active record, an already-terminal record with a stale live pid) by *leaning on the existing guards rather than adding new ones*. Same reasoning: an unknown status was never active, so there is nothing to terminalize, and writing `cancelled` over it would assert a lifecycle event that never happened.
- **Alternative considered:** Treating unknown as active and terminalizing it — rejected: it fabricates a `cancelled` record (and a kill attempt) for a record the hook cannot classify.

### The retention prune runs once per state dir, unconditionally, after the per-job loop
- **Question:** Where exactly does `pruneJobRecordsInStateDir` get called, and is it conditional on that state dir having contained jobs of the ending session?
- **Choice:** Once per state dir, immediately after the per-job loop inside `cleanupSessionJobs`'s `for (const stateDir of listStateDirs())`, unconditionally. `cleanupSessionJobs` already returns early when there is no session id, so no prune happens outside a SessionEnd with a session.
- **Grounding:** The design: "after the per-job loop, apply `MAX_JOBS` retention to each state dir the hook touched" — the hook touches every state dir (it migrates each one). Retention is state-dir-scoped today (`pruneJobRecords` → `listJobs` → `pruneJobs`), not session-scoped, so scoping the trigger by session would be a new policy. The pre-existing property that a long-idle *active* record could fall outside a 50-record cap is unchanged, not widened.
- **Alternative considered:** Pruning only state dirs that yielded a matching job (leaves a worktree whose owning session never ends unpruned, for no gain); pruning once after the state-dir loop (needs a collected set for no behavioural difference).

### Test isolation: hermetic module-scope env, distinct session id per SessionEnd test, file-local helpers
- **Question:** How do the new tests stay correct inside a live Claude Code session and independent of each other, given the SessionEnd hook iterates *every* state dir under the plugin data root?
- **Choice:** Module-scope `process.env.CLAUDE_PLUGIN_DATA = makeTempDir(...)` plus `delete` of both `CODEX_COMPANION_*` vars; each SessionEnd test uses its own session id (`sess-retain-terminal`, `sess-cancel-live`, …); sleeper / dead-pid / `waitFor` helpers are defined locally in the new file rather than imported across test files or promoted into `tests/helpers.mjs`.
- **Grounding:** `tests/liveness.test.mjs` and `tests/reviewer-detach.test.mjs` establish all three conventions (`tests/helpers.mjs` exports only `makeTempDir`, `writeExecutable`, `run`, `initGitRepo`), and the design's fixture note makes them binding. Distinct session ids matter because the hook walks all state dirs: with a shared id, a later test's hook run would re-process earlier tests' records. Records left by earlier tests are already terminal, so they are skipped, and every earlier state dir holds far fewer than `MAX_JOBS` records, so no cross-test prune can delete anything a test asserts on.
- **Alternative considered:** One shared session id (couples the tests through the hook's state-dir walk); promoting the sleeper helpers into `tests/helpers.mjs` (touches a shared fixture module for two callers, against the file-local convention).

### `just build` gates every task
- **Question:** Is a green `just build` required per task or once at the end?
- **Choice:** Every task ends with a green `just build` from the worktree.
- **Grounding:** `CLAUDE.md`: "After editing any `.nix`, run `just build` before claiming success" — the patch is materially a nix input, and a patch that nix's `patch -p1` cannot apply is only discoverable this way. Same decision as the issue-2 and issue-3 plans. After the first build the marginal cost is seconds (only the cheap `runCommand` marketplace derivations rebuild).
- **Alternative considered:** Final-task-only — rejected: an intermediate commit carrying a nix-unappliable patch would be discovered three tasks late.

### Commit boundaries: one worktree commit per task
- **Question:** What lands in each worktree commit?
- **Choice:** Task 1: `patches/agent-plugins/codex-plugin-cc.patch` + `lib/agent-plugins.nix`. Tasks 2, 3, 4: the patch file only. Nothing from `$SCRATCH` is ever committed; `result` (the `just build` symlink) stays untracked.
- **Grounding:** `CLAUDE.md`'s recorded workflow (the patch is the only plugin artifact); writing-plans "frequent commits" with one reviewable deliverable each; issue-2 and issue-3 precedent.
- **Alternative considered:** One squashed commit — rejected: loses the per-task review gates `sdd` depends on.

### The live demo is a ship-phase note, with its evidence home fixed here
- **Question:** The issue asks for a `kill -9` demo. Is that a task in this plan?
- **Choice:** No — it is recorded as a ship-phase note, with the evidence home fixed at `.claude/specs/2026-08-12-worker-post-mortem-evidence.md`. Tasks 1, 2 and 4 pin the same three facts mechanically (captured trail + heal-on-read line, terminal survival across SessionEnd, an overdue live worker in the rendered status).
- **Grounding:** The design's Verification loop defers the demo's exact home to the plan and names the `2026-08-11-detached-reviewer-bridge-evidence.md` precedent (sibling `<date>-<slug>-evidence.md` beside the design doc). The demo needs an activated build (`just switch`), which this plan's gates deliberately stop short of, exactly as the issue-3 plan did for its AC8 demo.
- **Alternative considered:** A task that runs the demo (requires `just switch`, i.e. mutating the machine, outside a plan task's remit); appending evidence to the design spec (it is approved and frozen; the sibling-file precedent exists).

### Resuming this worktree instead of restarting the flow
- **Question:** The first `--auto` run on this issue died between Phase 4 and Phase 5, leaving the design doc committed as `98d5377` and this plan written but uncommitted. Restart from a clean worktree, or resume?
- **Choice:** Resume. This commit is the plan's first commit; Phase 5 (standards review) runs against it next.
- **Grounding:** from-issue's pre-flight treats a matching worktree with uncommitted work as a stop, but the state here is a dead agent's artifact rather than a human's in-progress edit — no process holds the worktree (`lsof -a -d cwd` finds none), no PR exists for the issue, the branch is based on `origin/main` at `165a3b0` as Phase 1 requires, and both artifacts are structurally complete (the plan ends with its full `## Spec coverage` section, so it was not truncated mid-write). Discarding would re-derive an approved 352-line design at no gain.
- **Alternative considered:** `git worktree remove` + a fresh Phase 0–4 run — rejected: it throws away a complete design and plan whose quality Phase 5 is about to test anyway, and a second design pass could reach different decisions than the ones the spec commit already records.

---

### Task 1: AC1 — the worker's fds land in the job log, and the progress preview excludes them structurally

**Files:**
- Modify (scratch): `plugins/codex/scripts/codex-companion.mjs`
- Modify (scratch): `plugins/codex/scripts/lib/job-control.mjs`
- Create (scratch): `tests/worker-postmortem.test.mjs`
- Modify (worktree): `patches/agent-plugins/codex-plugin-cc.patch` (regenerated)
- Modify (worktree): `lib/agent-plugins.nix` (`patchRevision` 5→6)

**Interfaces:**
- Consumes: `spawnBrokerProcess`'s stdio shape (`plugins/codex/scripts/lib/broker-lifecycle.mjs:113-125`) as the precedent to copy; `enqueueBackgroundTask`'s existing `createTrackedProgress(job)` → `appendLogLine(logFile, "Queued for background execution.")` sequence, which guarantees the log file exists before the spawn; `appendLogLine`/`appendLogBlock`'s invariant that every runtime-written line starts with `[${nowIso()}] `. Test infrastructure: `installFakeCodex(binDir, behavior)` / `buildEnv(binDir)` (`tests/fake-codex-fixture.mjs`), `makeTempDir` / `initGitRepo` / `run` (`tests/helpers.mjs`), `resolveStateDir` (`plugins/codex/scripts/lib/state.mjs`).
- Produces (later tasks rely on these):
  - `spawnDetachedTaskWorker(cwd, jobId, logFile)` — third parameter is required; the worker's fd 1 and fd 2 are the job log, opened `"a"`.
  - `tests/worker-postmortem.test.mjs` with module-scope hermetic env and these file-local helpers, which Tasks 2–4 extend and reuse:
    - `const SCRIPT` — absolute path to `plugins/codex/scripts/codex-companion.mjs`
    - `const AUTH_ERROR = "authentication expired; run codex login"`
    - `const DEAD_WORKER_MESSAGE = (pid) => \`Worker process ${pid} exited without recording a result.\``
    - `const ISO_PREFIXED = /^\[\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z\]\s/`
    - `makeRepo(): string` — temp dir, `git init`, one commit
    - `seedJob(workspace, record, logContents?): { jobFile, logFile }` — writes `<jobsDir>/<id>.json` (with `logFile` injected) and `<jobsDir>/<id>.log`
    - `isPidGone(pid): boolean`
    - `waitFor(predicate, { timeoutMs = 5000, intervalMs = 25 }): Promise<void>`
  - A progress preview that admits only lines matching `ISO_PREFIXED`.

- [ ] **Step 1: Rebuild the scratch clone**

Run the *Scratch clone workflow* setup block from the plan header verbatim.

Run: `git -C /tmp/codex-plugin-cc-issue-10-scratch rev-parse HEAD`
Expected: `db52e28f4d9ded852ab3942cea316258ae4ef346`

Run (from `$SCRATCH`): `env -u CLAUDE_PLUGIN_DATA -u CODEX_COMPANION_SESSION_ID -u CODEX_COMPANION_TRANSCRIPT_PATH node --test tests/*.test.mjs`
Expected: `# tests 107 / # pass 103 / # fail 0 / # skipped 4` — the p5 baseline, confirming the patch applied cleanly before anything changes.

- [ ] **Step 2: Write the failing tests**

Create `$SCRATCH/tests/worker-postmortem.test.mjs`:

```js
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";

import { buildEnv, installFakeCodex } from "./fake-codex-fixture.mjs";
import { initGitRepo, makeTempDir, run } from "./helpers.mjs";
import { resolveStateDir } from "../plugins/codex/scripts/lib/state.mjs";

// State resolvers read these variables at call time, and spawned CLI children
// inherit process.env (via buildEnv), so pinning them here keeps every test in
// this file hermetic even when the suite runs inside a live Claude Code session.
// node --test runs each file in its own process; nothing leaks across files.
process.env.CLAUDE_PLUGIN_DATA = makeTempDir("codex-plugin-postmortem-data-");
delete process.env.CODEX_COMPANION_SESSION_ID;
delete process.env.CODEX_COMPANION_TRANSCRIPT_PATH;

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const SCRIPT = path.join(ROOT, "plugins", "codex", "scripts", "codex-companion.mjs");
const AUTH_ERROR = "authentication expired; run codex login";
const DEAD_WORKER_MESSAGE = (pid) => `Worker process ${pid} exited without recording a result.`;
// The prefix appendLogLine/appendLogBlock put on every line the runtime writes.
// A log line without it is either the worker's captured stdout/stderr or the
// body of an appended block, and neither may reach the progress preview.
const ISO_PREFIXED = /^\[\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z\]\s/;

function makeRepo() {
  const repo = makeTempDir("codex-plugin-postmortem-repo-");
  initGitRepo(repo);
  fs.writeFileSync(path.join(repo, "README.md"), "hello\n");
  run("git", ["add", "README.md"], { cwd: repo });
  run("git", ["commit", "-m", "init"], { cwd: repo });
  return repo;
}

function seedJob(workspace, record, logContents = null) {
  const jobsDir = path.join(resolveStateDir(workspace), "jobs");
  fs.mkdirSync(jobsDir, { recursive: true });
  const logFile = path.join(jobsDir, `${record.id}.log`);
  fs.writeFileSync(logFile, logContents ?? `[2026-08-01T10:00:00.000Z] Starting ${record.title}.\n`, "utf8");
  const jobFile = path.join(jobsDir, `${record.id}.json`);
  fs.writeFileSync(jobFile, `${JSON.stringify({ ...record, logFile }, null, 2)}\n`, "utf8");
  return { jobFile, logFile };
}

function isPidGone(pid) {
  try {
    process.kill(pid, 0);
    return false;
  } catch (error) {
    return error?.code === "ESRCH";
  }
}

async function waitFor(predicate, { timeoutMs = 5000, intervalMs = 25 } = {}) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    if (await predicate()) {
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
  throw new Error("Timed out waiting for condition.");
}

function readLogLines(logFile) {
  return fs.readFileSync(logFile, "utf8").split(/\r?\n/).filter(Boolean);
}

test("a failing background worker's stderr is captured in the job log", async () => {
  const repo = makeRepo();
  const binDir = makeTempDir();
  // The fake codex rejects thread/start, so executeTaskRun throws, runTrackedJob
  // records the failure and rethrows, handleTaskWorker does not catch, and the
  // worker's own main().catch writes the message to fd 2. No code path appends
  // that text to the log, so an unprefixed copy there can only have arrived
  // through the redirected fd — which is the whole mechanism under test.
  installFakeCodex(binDir, "auth-run-fails");
  const env = buildEnv(binDir);

  const launched = run("node", [SCRIPT, "task", "--background", "--json", "investigate the failing test"], {
    cwd: repo,
    env
  });
  assert.equal(launched.status, 0, launched.stderr);
  const launchPayload = JSON.parse(launched.stdout);

  const waited = run("node", [SCRIPT, "status", launchPayload.jobId, "--wait", "--timeout-ms", "15000", "--json"], {
    cwd: repo,
    env
  });
  assert.equal(waited.status, 0, waited.stderr);
  const job = JSON.parse(waited.stdout).job;
  assert.equal(job.status, "failed");
  assert.equal(job.errorMessage, AUTH_ERROR);

  const logLines = readLogLines(launchPayload.logFile);
  const captured = logLines.filter((line) => !ISO_PREFIXED.test(line));
  assert.ok(
    captured.some((line) => line.includes(AUTH_ERROR)),
    `no captured stderr line in the job log:\n${logLines.join("\n")}`
  );
  // The runtime's own progress lines survive alongside it, chronologically: the
  // last thing the worker managed to report, then the trail that ended it.
  assert.ok(logLines.some((line) => ISO_PREFIXED.test(line) && line.includes("Starting Codex task thread.")));

  // R2: captured output never reaches the status surface.
  assert.ok(job.progressPreview.includes("Starting Codex task thread."), JSON.stringify(job.progressPreview));
  for (const line of job.progressPreview) {
    assert.equal(line.includes("authentication expired"), false, line);
  }
});

test("the progress preview admits only timestamped runtime lines, not appended block bodies", () => {
  const workspace = makeTempDir();
  // A failed job's log as runTrackedJob actually leaves it: progress lines, then
  // an appendLogBlock "Final output" block whose body is arbitrary review
  // markdown, plus a line of captured worker output. Only the two progress
  // lines are progress.
  const { logFile } = seedJob(
    workspace,
    {
      id: "task-preview",
      kind: "task",
      kindLabel: "rescue",
      title: "Codex Task",
      workspaceRoot: workspace,
      jobClass: "task",
      summary: "Investigate flaky test",
      status: "failed",
      phase: "failed",
      createdAt: "2026-08-01T10:00:00.000Z",
      startedAt: "2026-08-01T10:00:01.000Z",
      completedAt: "2026-08-01T10:00:09.000Z",
      updatedAt: "2026-08-01T10:00:09.000Z"
    },
    [
      "[2026-08-01T10:00:00.000Z] Starting Codex Task.",
      "[2026-08-01T10:00:01.000Z] Turn started (turn_1).",
      "",
      "[2026-08-01T10:00:08.000Z] Final output",
      "[Blocking] The retry loop never terminates.",
      "Fix the loop bound.",
      "FATAL ERROR: Reached heap limit Allocation failed",
      ""
    ].join("\n")
  );
  assert.ok(fs.existsSync(logFile));

  const result = run("node", [SCRIPT, "status", "task-preview", "--json"], { cwd: workspace });

  assert.equal(result.status, 0, result.stderr);
  assert.deepEqual(JSON.parse(result.stdout).job.progressPreview, [
    "Starting Codex Task.",
    "Turn started (turn_1)."
  ]);
});

test("a hard-killed worker's trail is its progress lines plus the heal-on-read line", async (t) => {
  const repo = makeRepo();
  const binDir = makeTempDir();
  // 5 s turn, so the worker is provably mid-run when it is killed.
  installFakeCodex(binDir, "interruptible-slow-task");
  const env = buildEnv(binDir);

  const launched = run("node", [SCRIPT, "task", "--background", "--json", "investigate the failing test"], {
    cwd: repo,
    env
  });
  assert.equal(launched.status, 0, launched.stderr);
  const { jobId, logFile } = JSON.parse(launched.stdout);
  const jobFile = path.join(resolveStateDir(repo), "jobs", `${jobId}.json`);

  await waitFor(() => {
    const record = JSON.parse(fs.readFileSync(jobFile, "utf8"));
    return record.status === "running" && Number.isFinite(record.pid);
  });
  const workerPid = JSON.parse(fs.readFileSync(jobFile, "utf8")).pid;
  t.after(() => {
    try {
      process.kill(-workerPid, "SIGKILL");
    } catch {
      // Already gone.
    }
  });

  // SIGKILL the worker's whole process group (the worker plus the codex child it
  // spawned). kill -9 is silent by construction: the process writes nothing.
  try {
    process.kill(-workerPid, "SIGKILL");
  } catch {
    process.kill(workerPid, "SIGKILL");
  }
  await waitFor(() => isPidGone(workerPid));

  const read = run("node", [SCRIPT, "status", jobId, "--json"], { cwd: repo, env });
  assert.equal(read.status, 0, read.stderr);
  const job = JSON.parse(read.stdout).job;
  assert.equal(job.status, "failed");
  assert.equal(job.errorMessage, DEAD_WORKER_MESSAGE(workerPid));

  const logLines = readLogLines(logFile);
  assert.equal(logLines.at(-1), `${logLines.at(-1).slice(0, 27)} ${DEAD_WORKER_MESSAGE(workerPid)}`);
  assert.ok(logLines.some((line) => line.includes("Starting Codex task thread.")), logLines.join("\n"));
  // The honest limit, pinned rather than papered over: a SIGKILLed process
  // contributes no captured output, so the trail is progress plus heal-on-read.
  assert.deepEqual(logLines.filter((line) => !ISO_PREFIXED.test(line)), []);
});
```

- [ ] **Step 3: Run the tests and watch two of three fail**

Run (from `$SCRATCH`): `env -u CLAUDE_PLUGIN_DATA -u CODEX_COMPANION_SESSION_ID -u CODEX_COMPANION_TRANSCRIPT_PATH node --test tests/worker-postmortem.test.mjs`
Expected: FAIL — 3 tests, 2 fail.
- `a failing background worker's stderr is captured in the job log` fails on `no captured stderr line in the job log:` — at p5 the worker is spawned `stdio: "ignore"`, so the log holds only the three `[iso]`-prefixed lines and the error text is nowhere.
- `the progress preview admits only timestamped runtime lines, not appended block bodies` fails on the `deepEqual`: at p5 the filter is `line.startsWith("[")`, so `[Blocking] The retry loop never terminates.` passes it and `stripLogPrefix` eats its bracket group, producing a third preview entry `The retry loop never terminates.`
- `a hard-killed worker's trail is its progress lines plus the heal-on-read line` **passes** at p5 — it pins the honest limit (kill -9 writes nothing) and issue #2's existing flip, so it is a regression pin rather than a falsifying gate. It must stay green after the change too.

- [ ] **Step 4: Redirect the worker's fds into the job log**

In `$SCRATCH/plugins/codex/scripts/codex-companion.mjs`, replace `spawnDetachedTaskWorker` (currently lines 683-694):

```js
function spawnDetachedTaskWorker(cwd, jobId) {
  const scriptPath = path.join(ROOT_DIR, "scripts", "codex-companion.mjs");
  const child = spawn(process.execPath, [scriptPath, "task-worker", "--cwd", cwd, "--job-id", jobId], {
    cwd,
    env: process.env,
    detached: true,
    stdio: "ignore",
    windowsHide: true
  });
  child.unref();
  return child;
}
```

with:

```js
function spawnDetachedTaskWorker(cwd, jobId, logFile) {
  const scriptPath = path.join(ROOT_DIR, "scripts", "codex-companion.mjs");
  // Same shape as spawnBrokerProcess. The child inherits an O_APPEND fd on the
  // job log, so everything it writes to fd 1/2 is appended to the file the job
  // record already points at via logFile — including output no application code
  // produced (node's uncaught-exception and unhandled-rejection reports, V8's
  // "FATAL ERROR: Reached heap limit", an abort trace), which no catch can
  // intercept. The parent's fd is closed straight after the spawn; the child
  // keeps its own dup. The worker's own appendFileSync progress writes are
  // O_APPEND on the same inode from the same process, so the two interleave
  // chronologically: the last progress line, then the trail that ended it.
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
  return child;
}
```

In the same file, `enqueueBackgroundTask` (currently line 700), pass the log file through — it is already created and written to two lines above, so opening it in append mode here cannot lose either line:

```js
  const child = spawnDetachedTaskWorker(cwd, job.id, logFile);
```

- [ ] **Step 5: Tighten the progress-preview filter to a full ISO prefix**

In `$SCRATCH/plugins/codex/scripts/lib/job-control.mjs`, add the pattern above `stripLogPrefix` (currently line 49):

```js
// Only the runtime's own progress lines may reach the status surface. Every line
// appendLogLine/appendLogBlock writes starts with `[${nowIso()}] `, so a full
// ISO-8601 timestamp prefix admits all of them and nothing else: the worker's
// captured stdout/stderr (redirected into this same log) and the bodies of
// appended blocks are excluded structurally, not by what a crash happens to
// print. This also keeps inferLegacyJobPhase, which reads the preview, from
// being steered by text the runtime did not write.
const LOG_LINE_PREFIX_PATTERN = /^\[\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z\]\s/;
```

Then in `readJobProgressPreview` (currently line 71), replace:

```js
    .filter((line) => line.startsWith("["))
```

with:

```js
    .filter((line) => LOG_LINE_PREFIX_PATTERN.test(line))
```

Leave `stripLogPrefix` unchanged: its `^\[[^\]]+\]\s*` still strips exactly the prefix that just passed the test.

- [ ] **Step 6: Verify — new tests pass, full suite green**

Run (from `$SCRATCH`): `env -u CLAUDE_PLUGIN_DATA -u CODEX_COMPANION_SESSION_ID -u CODEX_COMPANION_TRANSCRIPT_PATH node --test tests/worker-postmortem.test.mjs`
Expected: PASS — 3 tests, 0 fail.

Run (from `$SCRATCH`): `env -u CLAUDE_PLUGIN_DATA -u CODEX_COMPANION_SESSION_ID -u CODEX_COMPANION_TRANSCRIPT_PATH node --test tests/*.test.mjs`
Expected: `# tests 110 / # pass 106 / # fail 0 / # skipped 4`. In particular `status shows phases, hints, and the latest finished job` (`tests/runtime.test.mjs`) must still pass: its previewed fixture lines all carry full ISO timestamps, so the tightened filter admits them unchanged.

- [ ] **Step 7: Regenerate the patch and bump `patchRevision`**

Run the *Regeneration* block from the plan header. Then in the worktree edit `lib/agent-plugins.nix`: `patchRevision = 5;` → `patchRevision = 6;`.

Run: `git -C "$WORKTREE" status --porcelain`
Expected: exactly two modified paths — ` M lib/agent-plugins.nix` and ` M patches/agent-plugins/codex-plugin-cc.patch` (plus possibly `?? result`, untracked). Anything else means a stray edit landed.

Run: `grep -c 'stdio: \["ignore", logFd, logFd\]' "$WORKTREE/patches/agent-plugins/codex-plugin-cc.patch"`
Expected: `2` — one `+` line in `plugins/codex/scripts/codex-companion.mjs` (added by this task) and one context-free `+` line in `plugins/codex/scripts/lib/broker-lifecycle.mjs` (the pre-existing broker spawn, already patch-added at p5). If the count is 1, the worker's spawn shape did not reach the patch.

Run: `grep -c 'LOG_LINE_PREFIX_PATTERN' "$WORKTREE/patches/agent-plugins/codex-plugin-cc.patch"`
Expected: `2` — the definition and its single use.

Run: `grep -A3 '^diff --git a/tests/worker-postmortem\.test\.mjs' "$WORKTREE/patches/agent-plugins/codex-plugin-cc.patch"`
Expected: one match showing `new file mode 100644` and, immediately below, the whole-file hunk header `@@ -0,0 +1,N @@` where `N` is the exact line count of the file created in Step 2. `-A3` rather than two independent greps because the claim is that these lines belong to the *same* file, which only adjacency shows.

- [ ] **Step 8: `just build`**

Run (from `$WORKTREE`): `just build`
Expected: exits 0. Then:

```bash
STORE=$(nix-store -qR ./result | grep codex-plugin-cc)
echo "$STORE"                                                                     # ...codex-plugin-cc-1.0.6-nix.db52e28f.p6
grep -c 'stdio: \["ignore", logFd, logFd\]' "$STORE/plugins/codex/scripts/codex-companion.mjs"   # 1
```
Expected: the `.p6` path, and the shipped script carries the redirected stdio — proof the patch applies under nix's `patch -p1` and ships the feature.

- [ ] **Step 9: Commit**

```bash
cd "$WORKTREE"
git add patches/agent-plugins/codex-plugin-cc.patch lib/agent-plugins.nix
git commit -m "feat(agent-plugins): capture the detached worker's stdio in its job log

spawnDetachedTaskWorker now adopts spawnBrokerProcess's shape verbatim —
fs.openSync(logFile, \"a\") -> stdio: [ignore, logFd, logFd] -> unref ->
closeSync — so everything the worker writes to fd 1/2 is appended to the log
the job record already points at via logFile, including node's uncaught
exception reports and V8 output no catch can intercept. readJobProgressPreview
now admits only lines carrying a full ISO-8601 timestamp prefix, which is what
every appendLogLine/appendLogBlock write produces, so captured bytes and
appended block bodies are excluded structurally; that also closes a latent
defect where rendered review lines starting with [ leaked into a failed job's
progress preview. New tests/worker-postmortem.test.mjs pins the captured
stderr line, the preview exclusion, and the honest kill -9 limit. Patch p6
against codex-plugin-cc db52e28f.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_018ND9WQgzw7ccKYruN3pRaF"
```

---

### Task 2: AC2 — SessionEnd terminalizes and retains; the existing retention runs at the event that used to delete

**Files:**
- Modify (scratch): `plugins/codex/scripts/lib/state.mjs`
- Modify (scratch): `plugins/codex/scripts/lib/tracked-jobs.mjs`
- Modify (scratch): `plugins/codex/scripts/codex-companion.mjs`
- Modify (scratch): `plugins/codex/scripts/session-lifecycle-hook.mjs`
- Modify (scratch): `tests/worker-postmortem.test.mjs`
- Modify (scratch): `tests/runtime.test.mjs` (one test deliberately rewritten and renamed)
- Modify (worktree): `patches/agent-plugins/codex-plugin-cc.patch` (regenerated)

**Interfaces:**
- Consumes: Task 1's `tests/worker-postmortem.test.mjs` module-scope env block and its helpers `makeRepo()`, `seedJob(workspace, record, logContents?)`, `isPidGone(pid)`, `waitFor(predicate, opts)`, `DEAD_WORKER_MESSAGE(pid)`, `ISO_PREFIXED`. Existing runtime: `reconcileWorkerLiveness(workspaceRoot, job)` (unmodified), `terminateProcessTree(pid)` (returns `{attempted:false}` for a non-finite pid), `cleanupReviewerRuntime(workspaceRoot, jobId)` (idempotent), `removeJobFromStateDir(stateDir, jobId)`, `MAX_JOBS = 50`, `withMetadataLock`, `atomicWriteFile`, `readJobFile`, `pruneJobs`.
- Produces (later tasks rely on these):
  - `isActiveJobStatus(status): boolean` exported from `plugins/codex/scripts/lib/tracked-jobs.mjs` — `true` for `"queued"` and `"running"` only. Task 3 imports it into `job-control.mjs`.
  - `updateJobRecordInStateDir(stateDir, jobId, mutate)` exported from `state.mjs`; `updateJobRecord(cwd, jobId, mutate)` delegates to it with identical semantics (mutate returning `null` keeps the on-disk record and returns it).
  - `pruneJobRecordsInStateDir(stateDir)` exported from `state.mjs`; the private `pruneJobRecords(cwd)` delegates to it.
  - `tests/worker-postmortem.test.mjs` additionally exports-by-convention the file-local helpers `spawnSleeper(t, cwd)`, `deadPid(t, cwd)`, `runSessionEndHook(repo, sessionId)` and the constant `SESSION_HOOK`, which Task 4 reuses (`spawnSleeper` only).

- [ ] **Step 1: Rebuild the scratch clone**

Run the *Scratch clone workflow* setup block from the plan header verbatim (it applies the Task 1 patch, so the redirected spawn, the tightened filter and `tests/worker-postmortem.test.mjs` are present).

Run (from `$SCRATCH`): `env -u CLAUDE_PLUGIN_DATA -u CODEX_COMPANION_SESSION_ID -u CODEX_COMPANION_TRANSCRIPT_PATH node --test tests/worker-postmortem.test.mjs`
Expected: PASS — 3 tests, 0 fail.

- [ ] **Step 2: Write the failing tests**

Append to `$SCRATCH/tests/worker-postmortem.test.mjs`. First the three new helpers and the hook path constant (put `SESSION_HOOK` beside the existing `SCRIPT` constant, and the helpers beside `waitFor`):

```js
const SESSION_HOOK = path.join(ROOT, "plugins", "codex", "scripts", "session-lifecycle-hook.mjs");
```

```js
function spawnSleeper(t, cwd) {
  const sleeper = spawn(process.execPath, ["-e", "setInterval(() => {}, 1000)"], {
    cwd,
    detached: true,
    stdio: "ignore"
  });
  sleeper.unref();
  t.after(() => {
    try {
      process.kill(-sleeper.pid, "SIGKILL");
    } catch {
      try {
        process.kill(sleeper.pid, "SIGKILL");
      } catch {
        // Already gone.
      }
    }
  });
  return sleeper;
}

async function deadPid(t, cwd) {
  const sleeper = spawnSleeper(t, cwd);
  process.kill(sleeper.pid, "SIGKILL");
  await waitFor(() => isPidGone(sleeper.pid));
  return sleeper.pid;
}

function runSessionEndHook(repo, sessionId) {
  return run("node", [SESSION_HOOK, "SessionEnd"], {
    cwd: repo,
    env: { ...process.env, CODEX_COMPANION_SESSION_ID: sessionId },
    input: JSON.stringify({ hook_event_name: "SessionEnd", session_id: sessionId, cwd: repo })
  });
}

function activeRecord(workspace, id, pid, sessionId, overrides = {}) {
  return {
    id,
    kind: "task",
    kindLabel: "rescue",
    title: "Codex Task",
    workspaceRoot: workspace,
    jobClass: "task",
    summary: "Investigate flaky test",
    write: false,
    sessionId,
    status: "running",
    phase: "starting",
    pid,
    createdAt: "2026-08-01T10:00:00.000Z",
    startedAt: "2026-08-01T10:00:01.000Z",
    updatedAt: "2026-08-01T10:00:02.000Z",
    ...overrides
  };
}
```

Add `import { spawn } from "node:child_process";` to the file's import block (it is not there after Task 1).

Then the five tests:

```js
test("session end retains this session's terminal records and their logs", () => {
  const workspace = makeTempDir();
  const sessionId = "sess-retain-terminal";
  const completed = seedJob(
    workspace,
    activeRecord(workspace, "task-completed", null, sessionId, {
      status: "completed",
      phase: "done",
      pid: null,
      completedAt: "2026-08-01T10:00:08.000Z"
    })
  );
  const failed = seedJob(
    workspace,
    activeRecord(workspace, "task-failed", null, sessionId, {
      status: "failed",
      phase: "failed",
      pid: null,
      errorMessage: "Worker process 4242 exited without recording a result.",
      completedAt: "2026-08-01T10:00:09.000Z"
    })
  );
  const other = seedJob(
    workspace,
    activeRecord(workspace, "task-other-session", null, "sess-someone-else", {
      status: "completed",
      phase: "done",
      pid: null,
      completedAt: "2026-08-01T10:00:07.000Z"
    })
  );

  const result = runSessionEndHook(workspace, sessionId);

  assert.equal(result.status, 0, result.stderr);
  for (const { jobFile, logFile } of [completed, failed, other]) {
    assert.equal(fs.existsSync(jobFile), true, jobFile);
    assert.equal(fs.existsSync(logFile), true, logFile);
  }
  assert.equal(JSON.parse(fs.readFileSync(completed.jobFile, "utf8")).status, "completed");
  assert.equal(JSON.parse(fs.readFileSync(failed.jobFile, "utf8")).status, "failed");
  assert.equal(
    JSON.parse(fs.readFileSync(failed.jobFile, "utf8")).errorMessage,
    "Worker process 4242 exited without recording a result."
  );
});

test("session end terminates a live worker and records it cancelled", async (t) => {
  const workspace = makeTempDir();
  const sessionId = "sess-cancel-live";
  const sleeper = spawnSleeper(t, workspace);
  const { jobFile, logFile } = seedJob(workspace, activeRecord(workspace, "task-live", sleeper.pid, sessionId));

  const result = runSessionEndHook(workspace, sessionId);

  assert.equal(result.status, 0, result.stderr);
  await waitFor(() => isPidGone(sleeper.pid));

  assert.equal(fs.existsSync(jobFile), true);
  const stored = JSON.parse(fs.readFileSync(jobFile, "utf8"));
  assert.equal(stored.status, "cancelled");
  assert.equal(stored.phase, "cancelled");
  assert.equal(stored.pid, null);
  assert.equal(stored.errorMessage, "Session ended while the job was still running.");
  assert.ok(stored.completedAt);
  assert.equal(stored.cancelledAt, stored.completedAt);
  assert.equal(fs.existsSync(logFile), true);
  assert.ok(fs.readFileSync(logFile, "utf8").includes("Session ended while the job was still running."));
});

test("session end records an already-dead worker as failed, not cancelled", async (t) => {
  const workspace = makeTempDir();
  const sessionId = "sess-heal-dead";
  const pid = await deadPid(t, workspace);
  const { jobFile, logFile } = seedJob(workspace, activeRecord(workspace, "task-dead", pid, sessionId));

  const result = runSessionEndHook(workspace, sessionId);

  assert.equal(result.status, 0, result.stderr);
  const stored = JSON.parse(fs.readFileSync(jobFile, "utf8"));
  // The issue-6 case: the worker died hard and no human ran a status read before
  // the session ended. SessionEnd is the last heal-on-read chance, so the record
  // keeps issue #2's truthful dead-worker message instead of being relabelled a
  // session-end cancellation.
  assert.equal(stored.status, "failed");
  assert.equal(stored.phase, "failed");
  assert.equal(stored.pid, null);
  assert.equal(stored.errorMessage, DEAD_WORKER_MESSAGE(pid));
  assert.ok(fs.readFileSync(logFile, "utf8").includes(DEAD_WORKER_MESSAGE(pid)));
});

test("session end never relabels or kills an already-terminal record", (t) => {
  const workspace = makeTempDir();
  const sessionId = "sess-terminal-guard";
  const sleeper = spawnSleeper(t, workspace);
  // A completed record that still carries a live pid: the terminal guard must
  // skip it entirely — no kill, no relabel — with nothing racing.
  const { jobFile } = seedJob(
    workspace,
    activeRecord(workspace, "task-terminal-live-pid", sleeper.pid, sessionId, {
      status: "completed",
      phase: "done",
      completedAt: "2026-08-01T10:00:08.000Z"
    })
  );

  const result = runSessionEndHook(workspace, sessionId);

  assert.equal(result.status, 0, result.stderr);
  const stored = JSON.parse(fs.readFileSync(jobFile, "utf8"));
  assert.equal(stored.status, "completed");
  assert.equal(stored.pid, sleeper.pid);
  assert.equal(stored.errorMessage, undefined);
  assert.equal(isPidGone(sleeper.pid), false);
});

test("session end applies the MAX_JOBS retention it used to get from deleting", () => {
  const workspace = makeTempDir();
  const sessionId = "sess-retention";
  const seeded = [];
  for (let index = 0; index < 55; index += 1) {
    const minute = String(index).padStart(2, "0");
    seeded.push(
      seedJob(
        workspace,
        activeRecord(workspace, `task-${minute}`, null, sessionId, {
          status: "completed",
          phase: "done",
          pid: null,
          completedAt: `2026-08-01T10:${minute}:05.000Z`,
          updatedAt: `2026-08-01T10:${minute}:06.000Z`
        })
      )
    );
  }

  const result = runSessionEndHook(workspace, sessionId);

  assert.equal(result.status, 0, result.stderr);
  // MAX_JOBS is 50, newest-first by updatedAt: the five oldest lose both
  // artifacts, the newest fifty keep theirs.
  for (const { jobFile, logFile } of seeded.slice(0, 5)) {
    assert.equal(fs.existsSync(jobFile), false, jobFile);
    assert.equal(fs.existsSync(logFile), false, logFile);
  }
  for (const { jobFile, logFile } of seeded.slice(5)) {
    assert.equal(fs.existsSync(jobFile), true, jobFile);
    assert.equal(fs.existsSync(logFile), true, logFile);
  }
});
```

- [ ] **Step 3: Rewrite the existing session-end test in `tests/runtime.test.mjs`**

This is a deliberate rewrite, not a regression to fix by restoring the old behaviour: `session end fully cleans up jobs for the ending session` (currently line 1899) asserts the ending session's `completed` and `running` artifacts are **deleted**, which is exactly the policy AC2 changes. Keep the fixture and the two still-valid assertions (the other session is untouched; the live pid is killed) and replace the deletion assertions.

Rename the test and replace its assertion block (currently lines 1998-2017) with:

```js
  assert.equal(result.status, 0, result.stderr);
  assert.equal(fs.existsSync(otherSessionLog), true);
  assert.equal(fs.existsSync(otherJobFile), true);
  // SessionEnd deletes nothing now: every record of the ending session is left
  // terminal and retained, with its log, beside the other session's untouched
  // pair.
  assert.deepEqual(
    fs.readdirSync(jobsDir).sort(),
    [
      "review-completed.json",
      "review-other.json",
      "review-running.json",
      path.basename(completedLog),
      path.basename(otherSessionLog),
      path.basename(runningLog)
    ].sort()
  );

  await waitFor(() => {
    try {
      process.kill(sleeper.pid, 0);
      return false;
    } catch (error) {
      return error?.code === "ESRCH";
    }
  });

  const storedCompleted = JSON.parse(fs.readFileSync(completedJobFile, "utf8"));
  assert.equal(storedCompleted.status, "completed");

  const storedRunning = JSON.parse(fs.readFileSync(runningJobFile, "utf8"));
  assert.equal(storedRunning.status, "cancelled");
  assert.equal(storedRunning.phase, "cancelled");
  assert.equal(storedRunning.pid, null);
  assert.equal(storedRunning.errorMessage, "Session ended while the job was still running.");

  const jobIds = listJobs(repo).map((job) => job.id);
  // The cancelled write stamps a fresh updatedAt, so the terminalized job sorts
  // newest; the seeded pair keeps its 15:35 / 15:31 order behind it.
  assert.deepEqual(jobIds, ["review-running", "review-other", "review-completed"]);
  assert.equal(listJobs(repo).find((job) => job.id === "review-other").logFile, otherSessionLog);
```

Also change the test's name on line 1899 from `"session end fully cleans up jobs for the ending session"` to `"session end terminates live workers and retains terminal records"`, and add `const jobsDir = path.join(stateDir, "jobs");` usage where the fixture already computes it (line 1907) — it is already in scope.

- [ ] **Step 4: Run the tests and watch six fail**

Run (from `$SCRATCH`): `env -u CLAUDE_PLUGIN_DATA -u CODEX_COMPANION_SESSION_ID -u CODEX_COMPANION_TRANSCRIPT_PATH node --test tests/worker-postmortem.test.mjs`
Expected: FAIL — 8 tests, 5 fail (Task 1's three still pass). Every new test fails because `cleanupSessionJobs` still calls `removeJobFromStateDir` for every job of the ending session: the retention test sees no surviving artifacts at all, and the other four see their record file gone (`fs.existsSync(...)` false / `readFileSync` throwing `ENOENT`).

Run (from `$SCRATCH`): `env -u CLAUDE_PLUGIN_DATA -u CODEX_COMPANION_SESSION_ID -u CODEX_COMPANION_TRANSCRIPT_PATH node --test tests/runtime.test.mjs`
Expected: FAIL — `session end terminates live workers and retains terminal records` fails on the `readdirSync` deepEqual (only the other session's two files exist at the starting commit).

- [ ] **Step 5: Add the two stateDir-paired state helpers**

In `$SCRATCH/plugins/codex/scripts/lib/state.mjs`, replace `updateJobRecord` (currently lines 260-282) with the pair — the state-dir variant carries the body, the `cwd` variant delegates, following the file's existing `removeJob`/`removeJobFromStateDir` convention:

```js
export function updateJobRecordInStateDir(stateDir, jobId, mutate) {
  const jobsDir = path.join(stateDir, JOBS_DIR_NAME);
  // resolveJobFile used to create this directory as a side effect of
  // ensureStateDir; the state-dir variant has no cwd, so it does it explicitly
  // and callers keep the same guarantee.
  fs.mkdirSync(jobsDir, { recursive: true });
  const jobFile = path.join(jobsDir, `${jobId}.json`);
  return withMetadataLock(`${jobFile}.lock`, () => {
    let current = null;
    if (fs.existsSync(jobFile)) {
      try {
        // Null on parse failure is safe: listJobs already drops unparseable
        // records before selection, so null here only means a benign delete
        // race, where returning the in-memory job is correct.
        current = readJobFile(jobFile);
      } catch {
        current = null;
      }
    }
    const next = mutate(current);
    if (next == null) {
      return current;
    }
    const written = { ...next, updatedAt: nowIso() };
    atomicWriteFile(jobFile, `${JSON.stringify(written, null, 2)}\n`);
    return written;
  });
}

export function updateJobRecord(cwd, jobId, mutate) {
  return updateJobRecordInStateDir(resolveStateDir(cwd), jobId, mutate);
}
```

And replace `pruneJobRecords` (currently lines 355-367) with:

```js
export function pruneJobRecordsInStateDir(stateDir) {
  const jobsDir = path.join(stateDir, JOBS_DIR_NAME);
  if (!fs.existsSync(jobsDir)) {
    return;
  }
  const names = fs.readdirSync(jobsDir).filter((name) => name.endsWith(".json"));
  const records = [];
  for (const name of names) {
    try {
      records.push(readJobFile(path.join(jobsDir, name)));
    } catch {
      // An unparseable record is not retainable, so it prunes out — the same
      // outcome listJobs + the old pruneJobRecords produced together.
    }
  }
  const retainedIds = new Set(pruneJobs(records).map((job) => job.id));
  for (const name of names) {
    const jobId = name.slice(0, -".json".length);
    if (!retainedIds.has(jobId)) {
      removeJobFromStateDir(stateDir, jobId);
    }
  }
}

function pruneJobRecords(cwd) {
  pruneJobRecordsInStateDir(resolveStateDir(cwd));
}
```

`MAX_JOBS` keeps exactly one home: both paths reach it through `pruneJobs`. `saveState` still calls `pruneJobRecords(cwd)` and its behaviour is unchanged — it already runs `ensureStateDir(cwd)` before the prune, and `loadState` has already migrated any legacy index by the time `saveState` runs.

- [ ] **Step 6: Export the shared active predicate and drop the private copy**

In `$SCRATCH/plugins/codex/scripts/lib/tracked-jobs.mjs`, replace `isWorkerProbeEligible` (currently lines 197-199) with:

```js
// Active = queued | running. The only other statuses any writer produces are the
// terminal three (completed | failed | cancelled), so "not active" and "terminal"
// coincide for every record the runtime writes — but not for a legacy record with
// no status at all, which is why callers that must not act pick the predicate
// that says so.
export function isActiveJobStatus(status) {
  return status === "queued" || status === "running";
}

function isWorkerProbeEligible(job) {
  return isActiveJobStatus(job?.status) && Number.isFinite(job?.pid);
}
```

In `$SCRATCH/plugins/codex/scripts/codex-companion.mjs`, delete the private copy (currently lines 287-289):

```js
function isActiveJobStatus(status) {
  return status === "queued" || status === "running";
}
```

and add `isActiveJobStatus,` to the existing `./lib/tracked-jobs.mjs` import block, after `createProgressReporter,`. Its two existing call sites in `waitForSingleJobSnapshot` are unchanged.

- [ ] **Step 7: Terminalize and retain in the SessionEnd hook**

In `$SCRATCH/plugins/codex/scripts/session-lifecycle-hook.mjs`, replace the state import (currently line 9) and add the tracked-jobs import:

```js
import {
  listStateDirs,
  migrateLegacyJobIndexInStateDir,
  pruneJobRecordsInStateDir,
  updateJobRecordInStateDir
} from "./lib/state.mjs";
import { appendLogLine, isActiveJobStatus, nowIso, reconcileWorkerLiveness } from "./lib/tracked-jobs.mjs";
```

`removeJobFromStateDir` is no longer imported — the hook deletes nothing.

Then replace `cleanupSessionJobs` (currently lines 35-71) with:

```js
function terminalizeLiveSessionJob(stateDir, job) {
  try {
    terminateProcessTree(job.pid ?? Number.NaN);
  } catch {
    // Ignore teardown failures during session shutdown.
  }
  if (job.kind === "plan-review" && job.workspaceRoot) {
    cleanupReviewerRuntime(job.workspaceRoot, job.id);
  }

  // Cleanup precedes the terminal write (issue #2's ordering rule): if this
  // process dies between them the record is still active, so the next status
  // read heals it and retries both. The reverse order would leave a terminal
  // record with a permanent leak no reader revisits.
  let reason = null;
  const written = updateJobRecordInStateDir(stateDir, job.id, (current) => {
    if (!current || !isActiveJobStatus(current.status)) {
      // A concurrent writer (the worker completing, a cancel, a reader's
      // dead-worker flip) reached the record first; keep what it wrote.
      return null;
    }
    reason = `Session ended while the job was still ${current.status}.`;
    const completedAt = nowIso();
    return {
      ...current,
      status: "cancelled",
      phase: "cancelled",
      pid: null,
      completedAt,
      cancelledAt: completedAt,
      errorMessage: reason
    };
  });

  if (reason) {
    appendLogLine(written?.logFile ?? job.logFile ?? null, reason);
  }
}

function cleanupSessionJobs(sessionId) {
  if (!sessionId) {
    return;
  }
  for (const stateDir of listStateDirs()) {
    migrateLegacyJobIndexInStateDir(stateDir);
    const jobsDir = path.join(stateDir, "jobs");
    if (!fs.existsSync(jobsDir)) {
      continue;
    }
    for (const name of fs.readdirSync(jobsDir)) {
      if (!name.endsWith(".json")) {
        continue;
      }
      let job;
      try {
        job = JSON.parse(fs.readFileSync(path.join(jobsDir, name), "utf8"));
      } catch {
        continue;
      }
      if (job.sessionId !== sessionId) {
        continue;
      }
      // Heal first, and branch on what reconciliation returned rather than on
      // what was read off disk: a worker that already died is recorded failed
      // with issue #2's dead-worker message instead of being mislabelled a
      // session-end cancellation. This makes SessionEnd the last heal-on-read
      // opportunity before a session's records go quiet. A record without a
      // workspaceRoot cannot be reconciled (that is what resolves both the job
      // file and the reviewer runtime), so it takes the state-dir-only path.
      const current =
        isActiveJobStatus(job.status) && job.workspaceRoot ? reconcileWorkerLiveness(job.workspaceRoot, job) : job;
      if (!isActiveJobStatus(current.status)) {
        // Already terminal, or never active: retained with its log, never
        // relabelled, never killed.
        continue;
      }
      terminalizeLiveSessionJob(stateDir, current);
    }
    // SessionEnd used to delete this session's records, which made it the de
    // facto garbage collector of job artifacts. Retaining them means the state
    // layer's existing MAX_JOBS retention has to run at the same lifecycle
    // event, or .json/.log files — each carrying a full review payload —
    // accumulate without bound. No new policy: the existing one, triggered.
    pruneJobRecordsInStateDir(stateDir);
  }
}
```

- [ ] **Step 8: Verify — new tests pass, rewritten test passes, full suite green**

Run (from `$SCRATCH`): `env -u CLAUDE_PLUGIN_DATA -u CODEX_COMPANION_SESSION_ID -u CODEX_COMPANION_TRANSCRIPT_PATH node --test tests/worker-postmortem.test.mjs`
Expected: PASS — 8 tests, 0 fail.

Run (from `$SCRATCH`): `env -u CLAUDE_PLUGIN_DATA -u CODEX_COMPANION_SESSION_ID -u CODEX_COMPANION_TRANSCRIPT_PATH node --test tests/runtime.test.mjs tests/liveness.test.mjs tests/state.test.mjs`
Expected: PASS — 0 fail. `session end terminates live workers and retains terminal records` now passes; `saveState prunes dropped job artifacts when indexed jobs exceed the cap` (`tests/state.test.mjs`) still passes, which is what pins the `pruneJobRecords` delegation as semantics-preserving; every `tests/liveness.test.mjs` test still passes, which pins `reconcileWorkerLiveness` and `isWorkerProbeEligible` as unchanged in behaviour.

Run (from `$SCRATCH`): `env -u CLAUDE_PLUGIN_DATA -u CODEX_COMPANION_SESSION_ID -u CODEX_COMPANION_TRANSCRIPT_PATH node --test tests/*.test.mjs`
Expected: `# tests 115 / # pass 111 / # fail 0 / # skipped 4`.

- [ ] **Step 9: Regenerate the patch, verify, `just build`**

Run the *Regeneration* block from the plan header (`patchRevision` stays 6 — do not touch `lib/agent-plugins.nix`).

Run: `git -C "$WORKTREE" status --porcelain`
Expected: exactly one modified tracked path — ` M patches/agent-plugins/codex-plugin-cc.patch` (plus possibly `?? result`).

Run: `grep -c "removeJobFromStateDir" "$WORKTREE/patches/agent-plugins/codex-plugin-cc.patch"`
Expected: `2` — the two occurrences inside `state.mjs` (the exported definition and its use in `pruneJobRecordsInStateDir`). The hook's call and import are gone, so if this prints 3 or more the hook still deletes records.

Run: `grep -c "Session ended while the job was still" "$WORKTREE/patches/agent-plugins/codex-plugin-cc.patch"`
Expected: `4` — one in the hook, three in the tests (two in `tests/worker-postmortem.test.mjs`, one in the rewritten `tests/runtime.test.mjs` assertion).

Run (from `$WORKTREE`): `just build`
Expected: exits 0. Then:

```bash
STORE=$(nix-store -qR ./result | grep codex-plugin-cc)
grep -c "pruneJobRecordsInStateDir" "$STORE/plugins/codex/scripts/session-lifecycle-hook.mjs"   # 1
grep -c "removeJobFromStateDir" "$STORE/plugins/codex/scripts/session-lifecycle-hook.mjs" || true  # 0 (grep exits 1)
```

- [ ] **Step 10: Commit**

```bash
cd "$WORKTREE"
git add patches/agent-plugins/codex-plugin-cc.patch
git commit -m "feat(agent-plugins): SessionEnd terminalizes and retains job records

The SessionEnd hook's per-job body goes from terminate -> cleanup -> remove to
reconcile -> terminate -> cleanup -> terminalize -> retain. It deletes nothing:
a job whose worker already died is healed by issue #2's reconcileWorkerLiveness
and keeps the truthful dead-worker message, a job whose worker is still alive is
terminated, has its reviewer runtime cleaned, and is then recorded cancelled
with 'Session ended while the job was still <status>.' through a
concurrent-writer-guarded write, and an already-terminal record is skipped
entirely — no kill, no relabel. Because SessionEnd's unconditional removal was
the de facto garbage collector, the state layer's existing MAX_JOBS retention is
now triggered per state dir at the same lifecycle event, via a new
pruneJobRecordsInStateDir that pruneJobRecords delegates to; updateJobRecord
gains the same stateDir-paired sibling so the hook can write under the lock
without a workspace root. isActiveJobStatus becomes a single exported predicate
in tracked-jobs.mjs. tests/runtime.test.mjs's session-end test is deliberately
rewritten: its deletion assertions were the policy this change replaces.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_018ND9WQgzw7ccKYruN3pRaF"
```

---

### Task 3: AC3 (record and derive) — `deadlineAt` at enqueue, `overdue`/`overdueBy` in every read

**Files:**
- Modify (scratch): `plugins/codex/scripts/codex-companion.mjs`
- Modify (scratch): `plugins/codex/scripts/lib/tracked-jobs.mjs`
- Modify (scratch): `plugins/codex/scripts/lib/job-control.mjs`
- Modify (scratch): `tests/worker-postmortem.test.mjs`
- Modify (worktree): `patches/agent-plugins/codex-plugin-cc.patch` (regenerated)

**Interfaces:**
- Consumes: Task 2's `isActiveJobStatus(status)` export from `plugins/codex/scripts/lib/tracked-jobs.mjs`; Task 1's and Task 2's test helpers `makeRepo()`, `seedJob(workspace, record, logContents?)`, `spawnSleeper(t, cwd)`, `deadPid(t, cwd)`, `waitFor(...)`, `activeRecord(workspace, id, pid, sessionId, overrides)`, `DEAD_WORKER_MESSAGE(pid)`. Existing runtime: `formatElapsedDuration(startValue, endValue = null)` in `job-control.mjs` — returns `null` for an unparseable start *and* for an end earlier than the start; `handleTask`'s `timeoutMs` (reviewer default `840000`, `null` otherwise) already carried into the stored `request` by `buildTaskRequest`; `createCompanionJob` → `createJobRecord`, which stamps `createdAt: nowIso()` on every job.
- Produces (Task 4 relies on these):
  - Record field `deadlineAt` — an ISO string on the queued record when and only when the request carries a positive finite `timeoutMs`; absent otherwise. It survives the worker's `running` and terminal writes because `runTrackedJob` spreads the stored record into both.
  - Derived, non-persisted fields on every `enrichJob` result, and therefore on `status --json`, `status <id> --json`, the listing and the single-job report: `overdue: boolean` and `overdueBy: string | null` (a `formatElapsedDuration`-formatted span such as `"5m 0s"`, non-null exactly when `overdue` is true).
  - `isTerminalJobStatus(status): boolean` exported from `tracked-jobs.mjs` — `true` for `"completed"`, `"failed"`, `"cancelled"` only.

- [ ] **Step 1: Rebuild the scratch clone**

Run the *Scratch clone workflow* setup block from the plan header verbatim.

Run (from `$SCRATCH`): `env -u CLAUDE_PLUGIN_DATA -u CODEX_COMPANION_SESSION_ID -u CODEX_COMPANION_TRANSCRIPT_PATH node --test tests/worker-postmortem.test.mjs`
Expected: PASS — 8 tests, 0 fail.

- [ ] **Step 2: Write the failing tests**

Append to `$SCRATCH/tests/worker-postmortem.test.mjs`:

```js
test("a background enqueue stamps deadlineAt from the record's own createdAt", () => {
  const repo = makeRepo();
  const binDir = makeTempDir();
  installFakeCodex(binDir, "slow-task");
  const env = buildEnv(binDir);
  const jobsDir = path.join(resolveStateDir(repo), "jobs");
  const readRecord = (jobId) => JSON.parse(fs.readFileSync(path.join(jobsDir, `${jobId}.json`), "utf8"));

  const reviewer = run("node", [SCRIPT, "task", "--fresh", "--reviewer", "--background", "--json"], {
    cwd: repo,
    env,
    input: "review the plan"
  });
  assert.equal(reviewer.status, 0, reviewer.stderr);
  const reviewerRecord = readRecord(JSON.parse(reviewer.stdout).jobId);
  // The reviewer default budget, exactly: enqueue time + 840000 ms. Basing the
  // deadline on the record's own createdAt is what makes this an exact delta
  // rather than a fuzzy window.
  assert.equal(Date.parse(reviewerRecord.deadlineAt) - Date.parse(reviewerRecord.createdAt), 840000);

  const explicit = run(
    "node",
    [SCRIPT, "task", "--background", "--timeout-ms", "60000", "--json", "investigate the failing test"],
    { cwd: repo, env }
  );
  assert.equal(explicit.status, 0, explicit.stderr);
  const explicitRecord = readRecord(JSON.parse(explicit.stdout).jobId);
  // Driven by the request's timeoutMs, not by --reviewer.
  assert.equal(Date.parse(explicitRecord.deadlineAt) - Date.parse(explicitRecord.createdAt), 60000);

  const untimed = run("node", [SCRIPT, "task", "--background", "--json", "investigate the failing test"], {
    cwd: repo,
    env
  });
  assert.equal(untimed.status, 0, untimed.stderr);
  const untimedRecord = readRecord(JSON.parse(untimed.stdout).jobId);
  // A deadline exists only when a timeout does.
  assert.equal(untimedRecord.request.timeoutMs, null);
  assert.equal(untimedRecord.deadlineAt, undefined);
});

test("an alive job past its recorded deadline reports overdue without being flipped", (t) => {
  const workspace = makeTempDir();
  const sleeper = spawnSleeper(t, workspace);
  const { jobFile } = seedJob(
    workspace,
    activeRecord(workspace, "task-overdue", sleeper.pid, null, {
      createdAt: new Date(Date.now() - 600000).toISOString(),
      startedAt: new Date(Date.now() - 600000).toISOString(),
      deadlineAt: new Date(Date.now() - 300000).toISOString(),
      updatedAt: new Date(Date.now() - 60000).toISOString()
    })
  );

  const result = run("node", [SCRIPT, "status", "task-overdue", "--json"], { cwd: workspace });

  assert.equal(result.status, 0, result.stderr);
  const job = JSON.parse(result.stdout).job;
  // Alive-but-overdue falls out of the composition: buildSingleJobSnapshot runs
  // reconcileWorkerLiveness before enrichJob, so a job still active here has
  // just been probed (or was never probe-eligible) — it was not flipped.
  assert.equal(job.status, "running");
  assert.equal(job.overdue, true);
  assert.match(job.overdueBy, /^\d+m \d+s$/);
  // Advisory only: no state change, no signal.
  assert.equal(JSON.parse(fs.readFileSync(jobFile, "utf8")).status, "running");
  assert.equal(isPidGone(sleeper.pid), false);
});

test("a future deadline and a missing deadline both report not overdue", (t) => {
  const workspace = makeTempDir();
  const sleeper = spawnSleeper(t, workspace);
  seedJob(
    workspace,
    activeRecord(workspace, "task-future", sleeper.pid, null, {
      deadlineAt: new Date(Date.now() + 600000).toISOString()
    })
  );
  seedJob(workspace, activeRecord(workspace, "task-no-deadline", sleeper.pid, null));

  for (const jobId of ["task-future", "task-no-deadline"]) {
    const result = run("node", [SCRIPT, "status", jobId, "--json"], { cwd: workspace });
    assert.equal(result.status, 0, result.stderr);
    const job = JSON.parse(result.stdout).job;
    assert.equal(job.status, "running", jobId);
    assert.equal(job.overdue, false, jobId);
    assert.equal(job.overdueBy, null, jobId);
  }
});

test("a dead worker past its deadline is failed, never overdue", async (t) => {
  const workspace = makeTempDir();
  const pid = await deadPid(t, workspace);
  seedJob(
    workspace,
    activeRecord(workspace, "task-dead-overdue", pid, null, {
      deadlineAt: new Date(Date.now() - 300000).toISOString()
    })
  );

  const result = run("node", [SCRIPT, "status", "task-dead-overdue", "--json"], { cwd: workspace });

  assert.equal(result.status, 0, result.stderr);
  const job = JSON.parse(result.stdout).job;
  assert.equal(job.status, "failed");
  assert.equal(job.errorMessage, DEAD_WORKER_MESSAGE(pid));
  // Only an active job can be overdue, so the flip wins: a crash is reported as
  // a crash, not as an overrun.
  assert.equal(job.overdue, false);
  assert.equal(job.overdueBy, null);
});
```

- [ ] **Step 3: Run the tests and watch four fail**

Run (from `$SCRATCH`): `env -u CLAUDE_PLUGIN_DATA -u CODEX_COMPANION_SESSION_ID -u CODEX_COMPANION_TRANSCRIPT_PATH node --test tests/worker-postmortem.test.mjs`
Expected: FAIL — 12 tests, 4 fail. `a background enqueue stamps deadlineAt from the record's own createdAt` fails on the first delta (`Date.parse(undefined)` is `NaN`); the other three fail on `job.overdue` being `undefined` rather than `true`/`false`, because `enrichJob` derives no such field at the starting commit.

- [ ] **Step 4: Stamp `deadlineAt` at enqueue**

In `$SCRATCH/plugins/codex/scripts/codex-companion.mjs`, add above `enqueueBackgroundTask` (currently line 696):

```js
function resolveJobDeadline(createdAt, timeoutMs) {
  // The issue's definition: enqueue time + timeout, and a deadline exists only
  // when a timeout does. Measured from the record's own createdAt rather than a
  // fresh Date.now(), so the field is verifiable from the record alone. The
  // worker's internal Promise.race budget starts later (after spawn, runtime
  // seeding and app-server connect), so a healthy job can read as overdue for
  // that margin — bounded, self-correcting, and harmless because the signal is
  // advisory and is defined as the deadline recorded in the record.
  const createdMs = Date.parse(createdAt ?? "");
  if (!Number.isFinite(createdMs) || !Number.isFinite(timeoutMs) || timeoutMs <= 0) {
    return null;
  }
  return new Date(createdMs + timeoutMs).toISOString();
}
```

and inside `enqueueBackgroundTask`, build the queued record with it (currently lines 701-708):

```js
  const deadlineAt = resolveJobDeadline(job.createdAt, request.timeoutMs);
  const queuedRecord = {
    ...job,
    status: "queued",
    phase: "queued",
    pid: child.pid ?? null,
    logFile,
    ...(deadlineAt ? { deadlineAt } : {}),
    request
  };
```

- [ ] **Step 5: Export the terminal predicate and derive overdue in `enrichJob`**

In `$SCRATCH/plugins/codex/scripts/lib/tracked-jobs.mjs`, add beside `isActiveJobStatus`:

```js
export function isTerminalJobStatus(status) {
  return status === "completed" || status === "failed" || status === "cancelled";
}
```

In `$SCRATCH/plugins/codex/scripts/lib/job-control.mjs`, extend the tracked-jobs import (currently line 5):

```js
import { isActiveJobStatus, isTerminalJobStatus, reconcileWorkerLiveness, SESSION_ID_ENV } from "./tracked-jobs.mjs";
```

and replace `enrichJob` (currently lines 161-181):

```js
export function enrichJob(job, options = {}) {
  const maxProgressLines = options.maxProgressLines ?? DEFAULT_MAX_PROGRESS_LINES;
  // Read as deadline-to-now rather than start-to-now: the same end-minus-start
  // computation, measured from the deadline. formatElapsedDuration returns null
  // for an unparseable start and for an end earlier than the start, so a record
  // with no deadlineAt and a deadline still in the future both fall out as "not
  // overdue" with no extra branching. Only an active job can be overdue, and
  // both snapshot builders reconcile liveness before enriching, so a dead
  // worker is reported failed rather than overdue.
  const overdueBy = isActiveJobStatus(job.status) ? formatElapsedDuration(job.deadlineAt, null) : null;
  const enriched = {
    ...job,
    kindLabel: getJobTypeLabel(job),
    progressPreview:
      job.status === "queued" || job.status === "running" || job.status === "failed"
        ? readJobProgressPreview(job.logFile, maxProgressLines)
        : [],
    elapsed: formatElapsedDuration(job.startedAt ?? job.createdAt, job.completedAt ?? null),
    duration: isTerminalJobStatus(job.status)
      ? formatElapsedDuration(job.startedAt ?? job.createdAt, job.completedAt ?? job.updatedAt)
      : null,
    overdue: overdueBy != null,
    overdueBy
  };

  return {
    ...enriched,
    phase: enriched.phase ?? inferLegacyJobPhase(enriched, enriched.progressPreview)
  };
}
```

Nothing else in `job-control.mjs` changes: the filters in `buildStatusSnapshot`, `resolveResultJob` and `resolveCancelableJob` keep their inline comparisons, and the session filter stays — cross-session post-mortem access is by explicit job id.

- [ ] **Step 6: Verify — new tests pass, full suite green**

Run (from `$SCRATCH`): `env -u CLAUDE_PLUGIN_DATA -u CODEX_COMPANION_SESSION_ID -u CODEX_COMPANION_TRANSCRIPT_PATH node --test tests/worker-postmortem.test.mjs`
Expected: PASS — 12 tests, 0 fail.

Run (from `$SCRATCH`): `env -u CLAUDE_PLUGIN_DATA -u CODEX_COMPANION_SESSION_ID -u CODEX_COMPANION_TRANSCRIPT_PATH node --test tests/*.test.mjs`
Expected: `# tests 118 / # pass 114 / # fail 0 / # skipped 4`. In particular `status shows phases, hints, and the latest finished job` must still pass with `Duration: 1m 5s` — the `isTerminalJobStatus` substitution in the `duration` branch is semantics-preserving.

- [ ] **Step 7: Regenerate the patch, verify, `just build`**

Run the *Regeneration* block from the plan header (`patchRevision` stays 6).

Run: `git -C "$WORKTREE" status --porcelain`
Expected: exactly one modified tracked path — ` M patches/agent-plugins/codex-plugin-cc.patch`.

Run: `grep -c "deadlineAt" "$WORKTREE/patches/agent-plugins/codex-plugin-cc.patch"`
Expected: at least `9` — the two lines in `enqueueBackgroundTask`, the one in `enrichJob`, and six in the new tests. The exact number depends on test formatting, so treat a count below 9 as "the field did not reach both the runtime and the tests".

Run: `grep -c "overdueBy" "$WORKTREE/patches/agent-plugins/codex-plugin-cc.patch"`
Expected: at least `5` — three in `enrichJob`, and the test assertions.

Run (from `$WORKTREE`): `just build`
Expected: exits 0. Then:

```bash
STORE=$(nix-store -qR ./result | grep codex-plugin-cc)
grep -c "resolveJobDeadline" "$STORE/plugins/codex/scripts/codex-companion.mjs"   # 2
grep -c "overdueBy" "$STORE/plugins/codex/scripts/lib/job-control.mjs"            # 3
```

- [ ] **Step 8: Commit**

```bash
cd "$WORKTREE"
git add patches/agent-plugins/codex-plugin-cc.patch
git commit -m "feat(agent-plugins): record a job deadline and derive overdue on every read

enqueueBackgroundTask stamps deadlineAt = createdAt + request.timeoutMs on the
queued record when and only when the request carries a positive finite timeout,
so a reviewer job records its 840 s budget and an untimed task records no
deadline. enrichJob derives two non-persisted fields beside elapsed/duration —
overdue and overdueBy — from formatElapsedDuration(deadlineAt, null), which
already returns null for a missing deadline and for one still in the future.
Only active jobs are eligible and both snapshot builders reconcile liveness
before enriching, so alive-but-overdue falls out of the composition and a dead
worker is reported failed instead. The signal is advisory: no state change, no
signal sent, /codex:cancel remains the only kill path. isTerminalJobStatus is
exported from tracked-jobs.mjs and replaces enrichJob's open-coded terminal
comparison.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_018ND9WQgzw7ccKYruN3pRaF"
```

---

### Task 4: AC3 (render) — overdue on the table cell, in the detail block, and preserved by `status.md`; whole-issue verification

**Files:**
- Modify (scratch): `plugins/codex/scripts/lib/render.mjs`
- Modify (scratch): `plugins/codex/commands/status.md`
- Modify (scratch): `tests/worker-postmortem.test.mjs`
- Modify (scratch): `tests/commands.test.mjs`
- Modify (worktree): `patches/agent-plugins/codex-plugin-cc.patch` (regenerated)

**Interfaces:**
- Consumes: Task 3's derived fields `job.overdue` (boolean) and `job.overdueBy` (`string | null`), plus the persisted `job.deadlineAt`, on every `enrichJob` result reaching `renderStatusReport` (via `buildStatusSnapshot`) and `renderJobStatusReport` (via `buildSingleJobSnapshot`). Task 1's/Task 2's test helpers `seedJob`, `spawnSleeper`, `activeRecord`. The `read(relativePath)` helper already defined at the top of `tests/commands.test.mjs` (resolves against `plugins/codex/`).
- Produces: the user-visible overdue surface — table cell suffix `(overdue by <overdueBy>)` on `Elapsed`, one `Overdue:` line in the per-job detail block, and the `commands/status.md` guidance that keeps the marker when the model re-renders the table.

- [ ] **Step 1: Rebuild the scratch clone**

Run the *Scratch clone workflow* setup block from the plan header verbatim.

Run (from `$SCRATCH`): `env -u CLAUDE_PLUGIN_DATA -u CODEX_COMPANION_SESSION_ID -u CODEX_COMPANION_TRANSCRIPT_PATH node --test tests/worker-postmortem.test.mjs`
Expected: PASS — 12 tests, 0 fail.

- [ ] **Step 2: Write the failing tests**

Append to `$SCRATCH/tests/worker-postmortem.test.mjs`:

```js
test("the status report marks an overdue job in the active-jobs table and its detail block", (t) => {
  const workspace = makeTempDir();
  const sleeper = spawnSleeper(t, workspace);
  const deadlineAt = new Date(Date.now() - 300000).toISOString();
  seedJob(
    workspace,
    activeRecord(workspace, "task-overdue-render", sleeper.pid, null, {
      createdAt: new Date(Date.now() - 600000).toISOString(),
      startedAt: new Date(Date.now() - 600000).toISOString(),
      deadlineAt,
      updatedAt: new Date(Date.now() - 60000).toISOString()
    })
  );

  const result = run("node", [SCRIPT, "status"], { cwd: workspace });

  assert.equal(result.status, 0, result.stderr);
  // The marker rides the Elapsed cell, which commands/status.md's preserved
  // field list names — a new column could be dropped when the model re-renders.
  assert.match(
    result.stdout,
    /\| task-overdue-render \| rescue \| running \| starting \| \d+m \d+s \(overdue by \d+m \d+s\) \|/
  );
  assert.match(
    result.stdout,
    new RegExp(
      `Overdue: \\d+m \\d+s past the recorded deadline ${deadlineAt}; the job is still running\\. Cancel: /codex:cancel task-overdue-render`
    )
  );
  assert.match(result.stdout, /`\/codex:status task-overdue-render`<br>`\/codex:cancel task-overdue-render`/);
});
```

And append to `$SCRATCH/tests/commands.test.mjs`, after `internal docs use task terminology for rescue runs`:

```js
test("the status command preserves the overdue marker when it re-renders the table", () => {
  const source = read("commands/status.md");
  // A bare /codex:status is re-rendered as a compact table from an enumerated
  // field list, so the overdue marker has to be named there or the slash command
  // drops it on exactly the read where a wedged worker is found.
  assert.match(source, /overdue by/);
  assert.match(source, /elapsed or duration/);
});
```

- [ ] **Step 3: Run the tests and watch two fail**

Run (from `$SCRATCH`): `env -u CLAUDE_PLUGIN_DATA -u CODEX_COMPANION_SESSION_ID -u CODEX_COMPANION_TRANSCRIPT_PATH node --test tests/worker-postmortem.test.mjs tests/commands.test.mjs`
Expected: FAIL — 2 fail. `the status report marks an overdue job…` fails on the table-row regex (the `Elapsed` cell is a bare duration at the starting commit, and there is no `Overdue:` line at all). `the status command preserves the overdue marker…` fails on `/overdue by/` (`commands/status.md` has no such text).

- [ ] **Step 4: Render the marker in the table cell and the detail block**

In `$SCRATCH/plugins/codex/scripts/lib/render.mjs`, add above `appendActiveJobsTable` (currently line 109):

```js
function formatElapsedCell(job) {
  if (!job.overdue) {
    return job.elapsed ?? "";
  }
  // The overdue marker rides the Elapsed cell rather than a column of its own:
  // commands/status.md tells the model to re-render a bare /codex:status as a
  // compact table preserving an enumerated field list that names elapsed, so a
  // separate column could be dropped on precisely the read where a wedged
  // worker is discovered.
  return [job.elapsed, `(overdue by ${job.overdueBy})`].filter(Boolean).join(" ");
}
```

In the same function's row template (currently line 119), replace `${escapeMarkdownCell(job.elapsed ?? "")}` with `${escapeMarkdownCell(formatElapsedCell(job))}`. The rest of the row is unchanged, including the `Actions` cell that already offers `/codex:cancel` for every active job.

In `pushJobDetails`, immediately after the `showDuration` block (currently lines 135-137) and before the `threadId` block, add:

```js
  if (job.overdue) {
    // Advisory only — nothing is signalled and no state changes. The status is
    // reported rather than a probe result, because a queued record with no
    // usable pid is never probe-eligible and so never "answered" anything.
    lines.push(
      `  Overdue: ${job.overdueBy} past the recorded deadline ${job.deadlineAt}; the job is still ${job.status}. Cancel: /codex:cancel ${job.id}`
    );
  }
```

- [ ] **Step 5: Keep the marker in `commands/status.md`**

In `$SCRATCH/plugins/codex/commands/status.md`, replace line 13 exactly:

Old text:

```
- Preserve the actionable fields from the command output, including job ID, kind, status, phase, elapsed or duration, summary, and follow-up commands.
```

New text:

```
- Preserve the actionable fields from the command output, including job ID, kind, status, phase, elapsed or duration (keep any `(overdue by ...)` marker attached to the elapsed value), summary, and follow-up commands.
```

Change nothing else in the file: the `!`-prefixed command line, the compact-table instruction, and the pass-through rule for a job-id argument all stay byte-stable.

- [ ] **Step 6: Verify — new tests pass, full suite green**

Run (from `$SCRATCH`): `env -u CLAUDE_PLUGIN_DATA -u CODEX_COMPANION_SESSION_ID -u CODEX_COMPANION_TRANSCRIPT_PATH node --test tests/worker-postmortem.test.mjs tests/commands.test.mjs`
Expected: PASS — 0 fail (13 tests in `worker-postmortem`, the full `commands` file including the new test).

Run (from `$SCRATCH`): `env -u CLAUDE_PLUGIN_DATA -u CODEX_COMPANION_SESSION_ID -u CODEX_COMPANION_TRANSCRIPT_PATH node --test tests/*.test.mjs`
Expected: `# tests 120 / # pass 116 / # fail 0 / # skipped 4`. In particular the existing table assertion in `status shows phases, hints, and the latest finished job` must still pass — it matches the `Elapsed` cell with `.*`, and that job has no `deadlineAt`, so the cell is a bare duration.

- [ ] **Step 7: Regenerate the patch and run the whole-issue verification**

Run the *Regeneration* block from the plan header (`patchRevision` stays 6).

Run: `git -C "$WORKTREE" status --porcelain`
Expected: exactly one modified tracked path — ` M patches/agent-plugins/codex-plugin-cc.patch`.

Determinism — a pristine re-apply of the committed patch reproduces it byte-for-byte:

```bash
WORKTREE=/Users/anis/tmp/nix-config/.claude/worktrees/issue-10-worker-post-mortem
SCRATCH=/tmp/codex-plugin-cc-issue-10-scratch
PIN=db52e28f4d9ded852ab3942cea316258ae4ef346
git -C "$SCRATCH" reset --hard && git -C "$SCRATCH" checkout --force --detach "$PIN" && git -C "$SCRATCH" clean -ffd
git -C "$SCRATCH" apply --unidiff-zero "$WORKTREE/patches/agent-plugins/codex-plugin-cc.patch"
git -C "$SCRATCH" add -N .
git -C "$SCRATCH" diff -U0 "$PIN" | diff - "$WORKTREE/patches/agent-plugins/codex-plugin-cc.patch"
```
Expected: `diff` prints nothing (exit 0).

Run: `grep -n 'patchRevision = ' "$WORKTREE/lib/agent-plugins.nix"`
Expected: `patchRevision = 6;` — bumped in Task 1, untouched since.

Run: `git -C "$WORKTREE" diff --stat 98d5377 -- lib/agent-plugins.nix patches/agent-plugins/codex-plugin-cc.patch && git -C "$WORKTREE" diff --name-only 98d5377`
Expected: the `--name-only` list is exactly `.claude/plans/2026-08-12-worker-post-mortem.md`, `lib/agent-plugins.nix`, `patches/agent-plugins/codex-plugin-cc.patch` — no other repo file changed across the whole issue.

- [ ] **Step 8: `just build` and closure content checks**

Run (from `$WORKTREE`): `just build`
Expected: exits 0. Then:

```bash
STORE=$(nix-store -qR ./result | grep codex-plugin-cc)
echo "$STORE"                                                                                     # ...codex-plugin-cc-1.0.6-nix.db52e28f.p6
grep -c 'stdio: \["ignore", logFd, logFd\]' "$STORE/plugins/codex/scripts/codex-companion.mjs"     # 1
grep -c "pruneJobRecordsInStateDir" "$STORE/plugins/codex/scripts/session-lifecycle-hook.mjs"      # 1
grep -c "overdue by" "$STORE/plugins/codex/scripts/lib/render.mjs"                                 # 1
grep -c "overdue by" "$STORE/plugins/codex/commands/status.md"                                     # 1
```
Expected: the `.p6` path and all four counts as annotated — proof the patch applies under nix's `patch -p1` and that the shipped closure carries all three acceptance criteria.

- [ ] **Step 9: Commit**

```bash
cd "$WORKTREE"
git add patches/agent-plugins/codex-plugin-cc.patch
git commit -m "feat(agent-plugins): surface overdue jobs in the status table, details, and status.md

The active-jobs table's Elapsed cell becomes '<elapsed> (overdue by <span>)'
for an overdue job via a formatElapsedCell helper, and pushJobDetails gains one
line naming the overrun, the recorded deadline, the job's current status, and
the /codex:cancel remedy — so the signal reaches both the compact listing and
the full /codex:status <id> report. commands/status.md's preserved-fields
sentence now names the marker, without which the slash command would drop it
when it re-renders the table. A docs test in tests/commands.test.mjs pins that
sentence. Nothing is killed or flipped: overdue stays advisory.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_018ND9WQgzw7ccKYruN3pRaF"
```

---

## Ship-phase note (the issue's demo — not a task in this plan)

Activation (`just switch`) and the live demo are the ship phase's call. After the merged change is active, reproduce the issue's own demo against a real reviewer job and record it in `.claude/specs/2026-08-12-worker-post-mortem-evidence.md` (following the `2026-08-11-detached-reviewer-bridge-evidence.md` precedent — what ran, what it printed):

1. `kill -9` a running worker mid-review, then show the job log ending with the worker's captured trail (if any) plus the heal-on-read line `Worker process <pid> exited without recording a result.` — and state plainly that a SIGKILLed process contributes no captured output, so for *that* death the trail is progress plus heal-on-read. A diagnosable death (fatal error, abort, uncaught exception, unhandled rejection) is what the fd capture adds.
2. End the owning session and show the healed `failed` record and its `.log` still present afterwards, readable from a later session via `codex-companion status <jobId>` / `result <jobId>`.
3. Show a status read flagging a still-alive worker that has passed its recorded deadline, with its `deadlineAt` in the record and `(overdue by …)` in the rendered table.

## Spec coverage

- **R1 / AC1** (worker stderr and stdout captured to the log the record already points at): Task 1 Step 4, pinned by `a failing background worker's stderr is captured in the job log`.
- **R2 / AC1** (captured output structurally excluded from the progress preview): Task 1 Step 5, pinned by `the progress preview admits only timestamped runtime lines, not appended block bodies` (which also closes the pre-existing block-body leak) and by the preview assertions in the capture test.
- **R3 / AC2** (SessionEnd deletes no record; terminal records retained with logs): Task 2 Step 7, pinned by `session end retains this session's terminal records and their logs` and the rewritten `session end terminates live workers and retains terminal records`.
- **R4 / AC2** (every record of the ending session left truthfully terminal — dead → `failed` via heal-on-read, alive → terminated then `cancelled`, already-terminal untouched): Task 2 Step 7, pinned by `session end records an already-dead worker as failed, not cancelled`, `session end terminates a live worker and records it cancelled`, and `session end never relabels or kills an already-terminal record`.
- **R5 / AC2** (retained records stay bounded by the existing `MAX_JOBS`, triggered at SessionEnd): Task 2 Steps 5 and 7, pinned by `session end applies the MAX_JOBS retention it used to get from deleting`; the delegation's semantics are pinned by the untouched `tests/state.test.mjs` prune test.
- **R6 / AC3** (`deadlineAt` = creation + timeout, stamped once at enqueue, absent without a timeout): Task 3 Step 4, pinned by `a background enqueue stamps deadlineAt from the record's own createdAt`.
- **R7 / AC3** (a read derives overdue without writing, reports it on the table and the detail block beside `/codex:cancel`, never flips): Task 3 Step 5 and Task 4 Steps 4-5, pinned by `an alive job past its recorded deadline reports overdue without being flipped`, `a future deadline and a missing deadline both report not overdue`, `a dead worker past its deadline is failed, never overdue`, `the status report marks an overdue job in the active-jobs table and its detail block`, and `the status command preserves the overdue marker when it re-renders the table`.
- **R8 / AC4** (suite green env-scrubbed; `patchRevision` 5→6 with `just build` green): every task's suite gate (110 → 115 → 118 → 120 tests, `# fail 0`, `# skipped 4` throughout), Task 1 Steps 7-8 (bump + build), Task 4 Steps 7-8 (determinism, `patchRevision = 6`, `.p6` closure content checks).
