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
- `tests/worker-postmortem.test.mjs` — new behaviour-named file; created in Task 1 and appended to in Tasks 2–4 (13 tests total).
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

## Standards review provenance

- **Reviewer:** Claude fallback (fresh `reviewer` agent, no inherited context, read-only toolset).
- **Codex attempt:** dispatched first, per policy — job `reviewer-msq7jtdg-rnq1tj`, isolated read-only runtime, 14-minute budget. It **failed**: the bridge returned `CODEX_REVIEW_FAILURE` with no `errorMessage`, so it fell back to reporting the job's `summary`, a mid-run progress line. The recorded state is `status: "failed"`, `phase: "failed"`, `pid: null`, 14:51:58Z → 15:01:22Z (~9.5 min). Failure class: **worker died without recording a result**. Not a retry candidate and not a concurrency fallback, so the one-time native fallback was taken.
- **Note the irony, and the corroboration:** that failure is a live instance of the pathology this issue fixes — a dead worker whose only forensic trace is a stale progress line, with no captured stderr to say why. The evidence the plan asks for is exactly what was missing while diagnosing it.
- **Base SHA reviewed:** `165a3b000c4945c1b79ddca69e25b88b388acf27` (branch point); plan reviewed at `a91147c`.
- **Focus:** none configured (`codex.planReview.focus` unset; no `.claude/skills.config.json` in this repo).
- **Findings:** 10 raised — 4 Blocking, 3 Should-fix, 3 Discussion. **All 10 verified against the live tree** (the pinned upstream at `db52e28f` plus the committed p5 patch); none rejected as stale.
- **Dispositions:** 8 applied (B1, B2, B3, B4, S1, S2, S3, D3 — one `Auto-resolved decisions` entry each). 2 deferred to the human reviewer, both `low` confidence and both explicitly "conscious accept" requests rather than defects:
  - **D1** — exactly at the deadline `formatElapsedDuration` returns `"0s"`, so the cell reads `(overdue by 0s)` for one second. Truthful; kept unbranched.
  - **D2** — "active" now has a shared predicate plus the ~8 pre-existing open-coded copies in `job-control.mjs` and `render.mjs` that this plan deliberately does not churn.
- **Consequence for the spec:** S1 falsified one sentence of the spec's retention-safety rationale. Corrected in place at `.claude/specs/2026-08-12-worker-post-mortem-design.md` rather than by re-running Phase 2 — no requirement, option or scope changed, only a wrong justification and the guard it failed to justify.
- No reviewer transcript is stored in this repo, per the review contract.

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
- **Choice:** 13 tests in the new `tests/worker-postmortem.test.mjs` (3 in Task 1, 5 in Task 2, 4 in Task 3, 1 in Task 4), 1 test appended to `tests/commands.test.mjs` (Task 4), and 1 existing `runtime.test.mjs` test rewritten in place (count unchanged). Expected gates: after Task 1 `# tests 110 / # pass 106 / # fail 0 / # skipped 4`; after Task 2 `115 / 111 / 0 / 4`; after Task 3 `119 / 115 / 0 / 4`; after Task 4 `121 / 117 / 0 / 4`.
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
- **Grounding:** The design: "after the per-job loop, apply `MAX_JOBS` retention to each state dir the hook touched" — the hook touches every state dir (it migrates each one). Retention is state-dir-scoped today (`pruneJobRecords` → `listJobs` → `pruneJobs`), not session-scoped, so scoping the trigger by session would be a new policy.
- **Alternative considered:** Pruning only state dirs that yielded a matching job (leaves a worktree whose owning session never ends unpruned, for no gain); pruning once after the state-dir loop (needs a collected set for no behavioural difference).
- **Amended at Phase 5 (finding S1):** the prune is called with `retain: (job) => isActiveJobStatus(job.status)`. An active record is exempt from the cap entirely. Two facts force this: `pruneJobs` (`state.mjs:190-194`) ranks purely by `updatedAt` and is status-blind, and `createJobProgressUpdater` (`tracked-jobs.mjs:77-105`) only writes when `phase`/`threadId`/`turnId` change, so a wedged worker's `updatedAt` goes stale and it sorts *oldest*. Since this hook iterates **every** state dir while retaining terminal records makes 50-record dirs the steady state, a status-blind cap would make one session's end delete a live record and log owned by a concurrent session. `MAX_JOBS` still bounds the dir; it now bounds the evictable (terminal) records, so a dir holds at most 50 terminal records plus its live ones.

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

### Resuming a second time, after the reset between Phase 4 and Phase 5
- **Question:** A second `--auto` run was reset, this time with the plan committed (`a91147c`) and Phase 5 never started. Resume again, or restart?
- **Choice:** Resume at Phase 5. No plan content was re-derived; the standards review below is the first review of these artifacts.
- **Grounding:** Same pre-flight evidence as the entry above, re-verified: the worktree is clean (`git status --porcelain` empty), it holds exactly the two doc commits above `origin/main` at `165a3b0`, and `gh pr list --state all --search "issue-10"` returns no PR for this issue (only the merged #4, #8, #5 for issues 2, 1 and 3). The plan ends with its complete `## Spec coverage` section, so it was not truncated mid-write.
- **Alternative considered:** Discarding and restarting — rejected for the same reason as before, now with more to lose.

### Resuming a third time, mid-Phase-6, after Task 2
- **Question:** A third `--auto` run was reset during execution, with Tasks 1 and 2 committed (`9a3af56`, `cbc4376`) and Tasks 3 and 4 unstarted. Resume at Task 3, or re-run the whole flow?
- **Choice:** Resume at Task 3. Phases 0–5 stand as recorded above; Phase 6 continues from the Task 2 commit, and Tasks 1 and 2 are not re-executed or re-reviewed.
- **Grounding:** Re-verified the same pre-flight evidence: `git status --porcelain` is empty, the branch holds exactly the six commits above `origin/main` at `165a3b0` with nothing pushed, and `gh pr list --state all --search "issue-10"` still returns no PR for this issue. Both implementation commits landed complete — Task 1's plan-text corrections were themselves committed (`b84207d`, entry E1 above), and `lib/agent-plugins.nix` already reads `patchRevision = 6`, which the plan assigns to Task 1 alone. Each task's own gates (green suite at the stated count, green `just build`) had to pass before its commit, so the tree at `cbc4376` is a valid Task 3 starting point by construction. The plan's per-task independence makes this cheap: every task rebuilds the scratch clone from the *committed* patch, so no in-flight implementer state was lost with the reset.
- **Alternative considered:** Re-running Tasks 1 and 2 to confirm their gates — rejected: it re-derives nothing, and a second implementer pass over an already-reviewed commit risks churning accepted code. Discarding the branch — rejected for the same reason as the two entries above, now with two implementation commits to lose.

### B1: the Task 1 patch gate expected a count that a correct implementation cannot produce
- **Question:** The reviewer says `grep -c 'stdio: ["ignore", logFd, logFd]'` on the regenerated patch yields `1`, not the `2` the gate expects, because the broker's identical line is pristine upstream rather than patch-added.
- **Choice:** Expected count `2` → `1`, the failure interpretation inverted to "if the count is 0", and the false claim that the broker line is "already patch-added at p5" removed.
- **Grounding:** Verified directly: `git show db52e28f…:plugins/codex/scripts/lib/broker-lifecycle.mjs` carries `stdio: ["ignore", logFd, logFd]` at line 120 *at the pin* (the `:65` this entry first recorded was itself wrong — corrected during Task 1; the fd-lifecycle precedent this task copies is `broker-lifecycle.mjs:115-123`), and `grep -c` on the committed p5 patch returns `0`. The p5 patch does touch `broker-lifecycle.mjs`, which is what made the original claim plausible, but not that line. As written the gate failed on a correct implementation and passed on a broken one.
- **Alternative considered:** Grepping the built store path instead — rejected: Step 8 already does exactly that, and the patch-level grep is the cheaper pre-build check.

### B2: the hard-kill test's last-line assertion could never pass
- **Question:** The reviewer says `` `${logLines.at(-1).slice(0, 27)} ${DEAD_WORKER_MESSAGE(pid)}` `` reconstructs the line with two spaces, so the assertion fails at both p5 and p6.
- **Choice:** Replaced with `assert.ok(logLines.at(-1).endsWith(DEAD_WORKER_MESSAGE(workerPid)), logLines.join("\n"))`.
- **Grounding:** `appendLogLine` writes `` `[${nowIso()}] ${normalized}\n` `` (`tracked-jobs.mjs:43`) and `nowIso()` is `toISOString()`, so the prefix is `[` + 24 chars + `]` = 26 characters and index 26 is the separating space. `slice(0, 27)` therefore already ends with that space and the template adds a second. This also repaired Step 3's gate: the test is declared green at p5, so the double space would have made it fail there and turned "2 of 3 fail" into 3. `endsWith` beats `slice(0, 26)` because it encodes no prefix width at all, and the existing `ISO_PREFIXED` filter assertion at the end of the test is what pins the prefix shape.
- **Alternative considered:** `slice(0, 26)` — the reviewer's other suggestion, rejected: it still hard-codes a magic width that a change to the timestamp format would silently break.

### B3: Task 3 adds four tests, so the Task 3 and Task 4 suite gates were off by one
- **Question:** The reviewer says the test-count budget says "3 in Task 3" while Task 3's Step 2 appends four tests, making the `118` and `120` full-suite gates wrong.
- **Choice:** Budget → "13 tests … (3 in Task 1, 5 in Task 2, 4 in Task 3, 1 in Task 4)"; Task 3's gate `118 / 114` → `119 / 115`; Task 4's gate `120 / 116` → `121 / 117`.
- **Grounding:** Counted the `test(` declarations in the plan: Task 1 at 3, Task 2 at 5, Task 3 at 4 (`deadlineAt` stamping, alive-past-deadline, future-plus-missing deadline, dead-worker-past-deadline), Task 4 at 1 in `worker-postmortem` plus 1 in `commands`. From the verified 107 baseline: 110, 115, 119, 121, with `skipped` fixed at 4 so `pass` is always `tests - 4`. The per-file expectations ("12 tests" after Task 3, "13 tests" after Task 4) were already right and are unchanged — only the whole-suite arithmetic was wrong.
- **Alternative considered:** Dropping one Task 3 test to match the budget — rejected: all four assert distinct behaviour, and the budget exists to catch a lost test, not to cap them.

### B4: the Task 2 `removeJobFromStateDir` gate miscounted the surviving occurrences
- **Question:** The reviewer says the gate expects `2` where a correct implementation leaves `3`.
- **Choice:** Expected `2` → `3`, with all three enumerated, and the failure interpretation redirected to the store-path grep that scopes the check to the hook file.
- **Grounding:** Verified: the committed p5 patch holds 4 occurrences (patch lines 1071, 1074, 1189, 1247). Task 2 deletes the hook's import and call and adds one use inside `pruneJobRecordsInStateDir`, leaving the definition, the `cwd`-variant delegation, and the prune use. The original text overlooked the delegation. A patch-wide grep also cannot tell which file an occurrence sits in, so the meaningful assertion is the existing `grep -c … session-lifecycle-hook.mjs # 0` against the built store path.
- **Alternative considered:** Deleting the patch-level grep as redundant — rejected: it fails faster than a build, which is the point of a pre-build gate.

### S1: the SessionEnd prune exempts active records from the cap
- **Question:** The reviewer says the status-blind `MAX_JOBS` prune can delete a live record and log belonging to a *concurrent* session, and that the spec's safety rationale for this is false.
- **Choice:** `pruneJobRecordsInStateDir(stateDir, { retain })` takes a caller-supplied predicate; the hook passes `(job) => isActiveJobStatus(job.status)`, so an active record is never an eviction candidate. `MAX_JOBS` still bounds the dir, now over the evictable (terminal) records. The spec's falsified sentence is corrected in place, and the existing retention test gains a falsifying assertion.
- **Grounding:** Verified all three legs. `pruneJobs` (`state.mjs:190-194`) ranks purely by `updatedAt` and knows nothing about status. `createJobProgressUpdater` (`tracked-jobs.mjs:77-105`) returns early unless `phase`/`threadId`/`turnId` changed, so a wedged worker's `updatedAt` goes stale and it sorts *oldest* — the spec's claim that "its worker stamps `updatedAt` on every progress event, so it sorts newest" is simply wrong. And the hook walks **every** state dir, while retaining terminal records makes 50-record dirs the steady state, so the cap starts biting every session. Deleting a live record contradicts R3 and AC2 outright. The predicate lives with the caller because `tracked-jobs.mjs` already imports from `state.mjs`, so importing the status predicate back would create a cycle; `state.mjs` holds no status knowledge today and keeps none. `pruneJobRecords(cwd)` passes no predicate, so cwd-scoped pruning is bit-for-bit unchanged and `saveState prunes dropped job artifacts when indexed jobs exceed the cap` still passes — verified that it seeds all 51 records `status: "completed"`, so no active-record exemption applies to it.
- **Alternative considered:** Hard-coding the active check inside `state.mjs` (duplicates the predicate the plan deliberately unified, and gives the state layer status semantics it has never had); importing `isActiveJobStatus` into `state.mjs` (circular import, load-order fragile even though ESM hoisting would mask it); leaving it and documenting the risk (rejected: the failure it invites is the exact data loss this issue exists to stop).

### S2: terminal records keep the reviewer-runtime cleanup retry
- **Question:** The reviewer says moving `cleanupReviewerRuntime` inside `terminalizeLiveSessionJob` silently drops the retry for already-terminal `plan-review` records.
- **Choice:** The terminal branch calls `cleanupReviewerRuntime(current.workspaceRoot, current.id)` before `continue` when `current.kind === "plan-review" && current.workspaceRoot`. The live path keeps its existing terminate → cleanup → terminal-write order. The terminal-guard test gains a leaked-runtime-dir assertion.
- **Grounding:** Verified at p5 (`session-lifecycle-hook.mjs:65-67`): the call sits in the per-job loop after the conditional terminate, so it runs for every job of the ending session regardless of status. The plan's rewrite reached it only for still-active jobs. `cleanupReviewerRuntime` is idempotent (it `rm -rf`s a path), so the retry is free, and it matters more now: a terminal record whose own cleanup never completed — `withAppServer`'s `finally` can throw — used to have its runtime dir collected as the record was deleted. Placing the retry in the terminal branch rather than before the reconcile preserves issue #2's ordering for live jobs, where cleanup must follow the terminate and precede the terminal write.
- **Alternative considered:** Hoisting the cleanup above the reconcile for all jobs (would delete a live worker's runtime home out from under it — the reason p5 terminates first); recording the drop as deliberate (the reviewer's other option, rejected: it trades a leak that nothing revisits for nothing).

### S3: reconcile only when the record's own state dir is the one being walked
- **Question:** The reviewer says `reconcileWorkerLiveness(job.workspaceRoot, …)` can write to a different state dir than the loop is reading, leaving the real record active forever.
- **Choice:** `const reconcilable = Boolean(job.workspaceRoot) && resolveStateDir(job.workspaceRoot) === stateDir;` gates the reconcile; when it is false the record takes the state-dir-only path that a record without a `workspaceRoot` already takes.
- **Grounding:** Verified `resolveStateDir` (`state.mjs:72-84`) hashes `fs.realpathSync.native(workspaceRoot)` and falls back to the literal path when the realpath fails. For a worktree since moved or deleted the two hashes diverge, so reconcile would terminalize a phantom record in the other dir, this loop would read the untouched record, see "terminal" and `continue` — and now that SessionEnd deletes nothing, the stuck `running` record would never be cleaned up either. The gate reuses the escape hatch the plan already has, so it adds a condition rather than a code path.
- **Alternative considered:** Passing `stateDir` into `reconcileWorkerLiveness` (a signature change to a function this plan deliberately leaves untouched, and issue #2's tests pin its behaviour); leaving it (rejected: it converts a rare-but-real condition into a permanently wrong record). No test accompanies this one: the reviewer notes the seams cannot reach it, because every test's seed workspace resolves to its own state dir. Recorded here rather than papered over with a test that would prove nothing.

### D3: the store-path lookup tolerates more than one closure match
- **Question:** The reviewer notes `STORE=$(nix-store -qR ./result | grep codex-plugin-cc)` assumes a single match.
- **Choice:** All four sites become `grep 'codex-plugin-cc-1\.0\.6' | head -n1`.
- **Grounding:** The closure contains the marketplace `runCommand` derivations alongside the plugin output, and any second match makes `$STORE` multi-line, breaking the `grep -c` that follows with a confusing error rather than a clear gate failure. Pinning the version narrows it to the p6 output and `head -n1` makes the command total. Applied rather than deferred because it is a two-token change that removes a spurious-failure mode from a gate every task runs.
- **Alternative considered:** Leaving it and letting an implementer debug the multi-line expansion — rejected as false economy.

### E1: Task 1's hard-kill test raced its own kill, so Step 3's "passes at p5" was false

- **Question:** Executing Task 1 found that `a hard-killed worker's trail is its progress lines plus the heal-on-read line` failed 3/3 at p5, on `logLines.some((line) => line.includes("Starting Codex task thread."))` — not 2/3 as Step 3 predicted, and not for a reason any later step would fix. Is the test wrong, the code wrong, or the gate wrong?
- **Choice:** The plan's test was wrong, in its synchronisation only. Step 2's `waitFor` predicate gains a third conjunct requiring the log to already contain `Starting Codex task thread.` before the SIGKILL; every assertion in the test stays byte-identical, and Step 3 now records that its "passes at p5" claim holds only with that conjunct. Step 7's `grep -A3` also becomes `-A6`, and B1's `broker-lifecycle.mjs:65` becomes `:120`.
- **Grounding:** `runTrackedJob` (`tracked-jobs.mjs:134-146`) writes the `running` record with `pid: process.pid` *synchronously, before* `await runner()`, while `Starting Codex task thread.` is emitted from *inside* the runner (`codex.mjs:1111`) — measured ~370 ms later. So the record-only predicate was satisfied strictly before the worker had logged anything of its own, and with a 25 ms poll the kill landed in that window deterministically. The test's own stated intent is that the worker is "provably mid-run when it is killed"; the fake turn lasts 5000 ms (`tests/fake-codex-fixture.mjs`), so waiting for the line kills at ~430 ms into a 5 s turn — still provably mid-turn, and a strictly stronger precondition than "flagged running". Verified independently by the controller in the pinned source and again by the task reviewer before acceptance. The `-A3` correction has the same character: git emits `index`, `--- /dev/null`, `+++ b/…` between the mode line and the hunk header, so a 3-line window could not show the adjacency the gate asserts.
- **Consequence:** `tests/worker-postmortem.test.mjs` is 224 lines after Task 1 (the `N` in Step 7's whole-file hunk header), and the assertion the predicate now guarantees is tautological — recorded as a deferred minor rather than removed, because the same test's `endsWith` and no-unprefixed-lines assertions are what carry its falsifiable content.
- **Alternative considered:** Deleting or skipping the test to keep the plan text verbatim — rejected: it is the only pin on the honest kill -9 limit, and dropping it would have moved the suite gate to 109/105/0/4. Widening `waitFor`'s timeout — rejected: the failure is program order, not slowness, so no timeout fixes it.

### E2: the prune gate counted call sites but grepped lines, so a correct Task 2 printed 2

- **Question:** Executing Task 2 found `grep -c "pruneJobRecordsInStateDir" <hook file>` returning `2` where Task 2 Step 9 and Task 4 Step 8 both expect `1`. Is the hook calling the prune twice, or is the gate wrong?
- **Choice:** The gate was wrong; the code stands unchanged. Task 2's gate now expects `2` and gains a second, anchored grep (`pruneJobRecordsInStateDir(stateDir`) expecting `1`; Task 4's gate switches to the anchored form outright.
- **Grounding:** `grep -c` counts matching *lines*, and Step 7's prescribed `./lib/state.mjs` import block puts `pruneJobRecordsInStateDir,` on a line of its own — so any implementation that follows the plan verbatim produces two matching lines (the import at hook line 12, the call at line 146). Verified in the committed patch: the symbol appears at patch lines 1144 (definition in `state.mjs`), 1179 (the `cwd` delegation), 1276 (the hook's import) and 1404 (the hook's call) — one call site in the hook, exactly as the gate intended. The neighbouring `removeJobFromStateDir` gate, which must print `0`, is the authoritative "the hook deletes nothing" check and passed as written.
- **Alternative considered:** Collapsing the hook's import to one line so the bare grep returns `1` — rejected: it churns transcribed-verbatim plan code to satisfy a counting mistake, and the multi-line import matches the file's existing style. Deleting the gate as redundant — rejected: anchored on `(stateDir` it still pins "pruned exactly once per state dir", which is the S1 decision's whole point.

### E3: Task 4's whole-issue file-list gate omitted the spec correction Phase 5 made

- **Question:** Executing Task 4 found Step 7's `git diff --name-only 98d5377` gate enumerating three paths where the real list has four — it also carries `.claude/specs/2026-08-12-worker-post-mortem-design.md`. Did a task touch a file it should not have?
- **Choice:** No — the gate text was stale; the fourth path is expected and the enumeration now names it. No code or commit changed.
- **Grounding:** Verified: the spec edit is docs-only (10 insertions, 2 deletions) and landed in `bbc775d`, the standards-review commit, which is exactly where this plan's own *Standards review provenance* section says finding S1 corrected the spec's falsified retention-safety sentence in place. The gate was written in Task 4's text before Phase 5 ran, so it could not have anticipated a fourth path. Its substance — that no *unexpected* repo file changed across the issue — holds: the four paths are the plan, the spec, the `patchRevision` bump and the patch.
- **Alternative considered:** Reverting the spec edit to make the gate literally true — rejected outright: the edit is a Phase-5 correction of a false statement, and the plan records it as deliberate. Loosening the gate to a path *prefix* check — rejected: enumerating the exact list is what makes it catch a stray file, which is the whole point.

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

  // The log line, not just the record, is the mid-run signal: runTrackedJob
  // writes `status: "running"` with its pid *before* it calls the runner, and
  // "Starting Codex task thread." is emitted from inside the runner, so a
  // record-only predicate is satisfied ~370 ms before the worker has logged
  // anything of its own — and the SIGKILL below would then land in that window,
  // leaving no progress line for the trail assertion to find.
  await waitFor(() => {
    const record = JSON.parse(fs.readFileSync(jobFile, "utf8"));
    return (
      record.status === "running" &&
      Number.isFinite(record.pid) &&
      fs.readFileSync(logFile, "utf8").includes("Starting Codex task thread.")
    );
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
  // endsWith, not a slice-based reconstruction of the prefix: appendLogLine
  // writes `[${nowIso()}] ${message}`, and `[` + a 24-char ISO instant + `]`
  // is 26 characters, so any slice wide enough to include the separating space
  // makes the template add a second one. The ISO_PREFIXED assertion below is
  // what pins the prefix shape.
  assert.ok(logLines.at(-1).endsWith(DEAD_WORKER_MESSAGE(workerPid)), logLines.join("\n"));
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
- `a hard-killed worker's trail is its progress lines plus the heal-on-read line` **passes** at p5 — it pins the honest limit (kill -9 writes nothing) and issue #2's existing flip, so it is a regression pin rather than a falsifying gate. It must stay green after the change too. **This holds only with the log-line conjunct in the Step 2 `waitFor` predicate** (see the E1 entry under `Auto-resolved decisions`); with a record-only predicate it fails at p5 too, making the count 3 of 3.

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
Expected: `1` — the single `+` line in `plugins/codex/scripts/codex-companion.mjs` added by this task. The broker's identical line is **pristine upstream** (`plugins/codex/scripts/lib/broker-lifecycle.mjs:120` at the pin), not patch-added, so the committed p5 patch matches this grep `0` times and p6 matches it once. If the count is 0, the worker's spawn shape did not reach the patch.

Run: `grep -c 'LOG_LINE_PREFIX_PATTERN' "$WORKTREE/patches/agent-plugins/codex-plugin-cc.patch"`
Expected: `2` — the definition and its single use.

Run: `grep -A6 '^diff --git a/tests/worker-postmortem\.test\.mjs' "$WORKTREE/patches/agent-plugins/codex-plugin-cc.patch"`
Expected: one match showing `new file mode 100644` and, below it, the whole-file hunk header `@@ -0,0 +1,N @@` where `N` is the exact line count of the file created in Step 2. A context window rather than two independent greps because the claim is that these lines belong to the *same* file, which only adjacency shows. `-A6`, not `-A3`: git emits `index`, `--- /dev/null` and `+++ b/…` between the mode line and the hunk header, so a 3-line window stops one line short of the thing being asserted.

- [ ] **Step 8: `just build`**

Run (from `$WORKTREE`): `just build`
Expected: exits 0. Then:

```bash
STORE=$(nix-store -qR ./result | grep 'codex-plugin-cc-1\.0\.6' | head -n1)
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
  - `pruneJobRecordsInStateDir(stateDir, { retain } = {})` exported from `state.mjs`, where `retain` is an optional predicate marking records that are exempt from the `MAX_JOBS` cap; the private `pruneJobRecords(cwd)` delegates to it and passes none.
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

Add `import { spawn } from "node:child_process";` and `import { resolveReviewerRuntimeHome } from "../plugins/codex/scripts/lib/runtime-home.mjs";` to the file's import block (neither is there after Task 1; `tests/liveness.test.mjs` and `tests/reviewer-detach.test.mjs` import the resolver the same way).

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

  // A terminal plan-review record whose reviewer runtime dir outlived its own
  // cleanup (withAppServer's `finally` can throw). Retaining the record must not
  // also drop the hook's idempotent cleanup retry, which p5 ran for every job of
  // the ending session regardless of status.
  const reviewerRuntime = resolveReviewerRuntimeHome(workspace, "reviewer-terminal-leak");
  fs.mkdirSync(reviewerRuntime, { recursive: true });
  fs.writeFileSync(path.join(reviewerRuntime, "config.toml"), "", "utf8");
  const { jobFile: reviewerJobFile } = seedJob(
    workspace,
    activeRecord(workspace, "reviewer-terminal-leak", null, sessionId, {
      kind: "plan-review",
      status: "failed",
      phase: "failed",
      pid: null,
      completedAt: "2026-08-01T10:00:09.000Z",
      errorMessage: DEAD_WORKER_MESSAGE(4242)
    })
  );

  const result = runSessionEndHook(workspace, sessionId);

  assert.equal(result.status, 0, result.stderr);
  const stored = JSON.parse(fs.readFileSync(jobFile, "utf8"));
  assert.equal(stored.status, "completed");
  assert.equal(stored.pid, sleeper.pid);
  assert.equal(stored.errorMessage, undefined);
  assert.equal(isPidGone(sleeper.pid), false);
  // Retained, unrelabelled — and its leaked runtime dir collected.
  assert.equal(fs.existsSync(reviewerJobFile), true, reviewerJobFile);
  assert.equal(JSON.parse(fs.readFileSync(reviewerJobFile, "utf8")).status, "failed");
  assert.equal(fs.existsSync(reviewerRuntime), false, reviewerRuntime);
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

  // A *live* record owned by a different session, carrying the oldest updatedAt
  // in the dir. The per-job loop skips it on the session check, so only the
  // prune can touch it — and a status-blind cap would evict it, because
  // createJobProgressUpdater stamps updatedAt only when a phase, thread or turn
  // changes, so a wedged worker sorts oldest. Deleting it would destroy a
  // concurrent session's live record and log.
  const foreignLive = seedJob(
    workspace,
    activeRecord(workspace, "task-foreign-live", null, "sess-other-live", {
      status: "running",
      phase: "running",
      updatedAt: "2026-08-01T09:00:00.000Z"
    })
  );

  const result = runSessionEndHook(workspace, sessionId);

  assert.equal(result.status, 0, result.stderr);
  // The active record is exempt from the cap, so it survives untouched.
  assert.equal(fs.existsSync(foreignLive.jobFile), true, foreignLive.jobFile);
  assert.equal(fs.existsSync(foreignLive.logFile), true, foreignLive.logFile);
  assert.equal(JSON.parse(fs.readFileSync(foreignLive.jobFile, "utf8")).status, "running");
  // MAX_JOBS is 50 over the evictable (terminal) records, newest-first by
  // updatedAt: the five oldest lose both artifacts, the newest fifty keep theirs.
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
export function pruneJobRecordsInStateDir(stateDir, { retain = null } = {}) {
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
  // MAX_JOBS bounds the records the caller is willing to evict, and `retain`
  // says which are not evictable at all. It exists because pruneJobs ranks by
  // updatedAt while a job's updatedAt only advances when its phase, thread or
  // turn changes (createJobProgressUpdater in tracked-jobs.mjs returns early
  // when nothing changed) — so a long-wedged worker sorts *oldest*, which is
  // precisely the record this feature exists to preserve. state.mjs stays
  // status-agnostic: the predicate comes from the caller, and pruneJobRecords
  // passes none, so cwd-scoped pruning keeps its current semantics exactly.
  const exempt = retain ? records.filter((job) => retain(job)) : [];
  const evictable = retain ? records.filter((job) => !retain(job)) : records;
  const retainedIds = new Set([...exempt, ...pruneJobs(evictable)].map((job) => job.id));
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
  resolveStateDir,
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
      //
      // Reconciliation also has to be writing to the record this loop is
      // reading. reconcileWorkerLiveness resolves its own state dir by hashing
      // the *realpath* of workspaceRoot (`state.mjs:72-84`), so for a worktree
      // that has since been moved or deleted the hash diverges: it would
      // terminalize a phantom record elsewhere, this loop would read "terminal"
      // and skip, and the real record would stay active forever — and is now
      // never deleted either. When the two disagree, take the state-dir-only
      // path and let terminalizeLiveSessionJob write through `stateDir`.
      const reconcilable = Boolean(job.workspaceRoot) && resolveStateDir(job.workspaceRoot) === stateDir;
      const current =
        isActiveJobStatus(job.status) && reconcilable ? reconcileWorkerLiveness(job.workspaceRoot, job) : job;
      if (!isActiveJobStatus(current.status)) {
        // Already terminal, or never active: retained with its log, never
        // relabelled, never killed. The reviewer-runtime cleanup still runs:
        // it is idempotent, the p5 hook retried it for every job of the ending
        // session regardless of status, and a terminal record whose own cleanup
        // never completed (`withAppServer`'s `finally` can throw) would
        // otherwise keep its runtime dir forever now that the record survives.
        if (current.kind === "plan-review" && current.workspaceRoot) {
          cleanupReviewerRuntime(current.workspaceRoot, current.id);
        }
        continue;
      }
      terminalizeLiveSessionJob(stateDir, current);
    }
    // SessionEnd used to delete this session's records, which made it the de
    // facto garbage collector of job artifacts. Retaining them means the state
    // layer's existing MAX_JOBS retention has to run at the same lifecycle
    // event, or .json/.log files — each carrying a full review payload —
    // accumulate without bound. No new policy: the existing one, triggered —
    // except that an *active* record is never an eviction candidate. This hook
    // walks every state dir, not just this session's, so a status-blind cap
    // would let one session's end delete a live record and log belonging to a
    // concurrent session, which is the opposite of what the issue asks for.
    pruneJobRecordsInStateDir(stateDir, { retain: (job) => isActiveJobStatus(job.status) });
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
Expected: `3` — the three occurrences inside `state.mjs`: the exported definition, the `cwd`-variant delegation (`return removeJobFromStateDir(resolveStateDir(cwd), jobId);`), and the use inside `pruneJobRecordsInStateDir`. The committed p5 patch has `4` — those same three minus the prune use, plus the hook's import and call, both of which this task removes. Because this grep cannot say *which* file each occurrence sits in, the authoritative check that the hook deletes nothing is the store-path grep in the next step, which must print `0` for `session-lifecycle-hook.mjs`.

Run: `grep -c "Session ended while the job was still" "$WORKTREE/patches/agent-plugins/codex-plugin-cc.patch"`
Expected: `4` — one in the hook, three in the tests (two in `tests/worker-postmortem.test.mjs`, one in the rewritten `tests/runtime.test.mjs` assertion).

Run (from `$WORKTREE`): `just build`
Expected: exits 0. Then:

```bash
STORE=$(nix-store -qR ./result | grep 'codex-plugin-cc-1\.0\.6' | head -n1)
grep -c "pruneJobRecordsInStateDir" "$STORE/plugins/codex/scripts/session-lifecycle-hook.mjs"   # 2
grep -c "pruneJobRecordsInStateDir(stateDir" "$STORE/plugins/codex/scripts/session-lifecycle-hook.mjs"  # 1
grep -c "removeJobFromStateDir" "$STORE/plugins/codex/scripts/session-lifecycle-hook.mjs" || true  # 0 (grep exits 1)
```

The first count is `2` because `grep -c` counts lines and Step 7's own import block gives `pruneJobRecordsInStateDir,` a line of its own; the second grep is the one that pins the gate's real intent — exactly one call site.

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
Expected: `# tests 119 / # pass 115 / # fail 0 / # skipped 4`. In particular `status shows phases, hints, and the latest finished job` must still pass with `Duration: 1m 5s` — the `isTerminalJobStatus` substitution in the `duration` branch is semantics-preserving.

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
STORE=$(nix-store -qR ./result | grep 'codex-plugin-cc-1\.0\.6' | head -n1)
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
Expected: `# tests 121 / # pass 117 / # fail 0 / # skipped 4`. In particular the existing table assertion in `status shows phases, hints, and the latest finished job` must still pass — it matches the `Elapsed` cell with `.*`, and that job has no `deadlineAt`, so the cell is a bare duration.

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
Expected: the `--name-only` list is exactly `.claude/plans/2026-08-12-worker-post-mortem.md`, `.claude/specs/2026-08-12-worker-post-mortem-design.md`, `lib/agent-plugins.nix`, `patches/agent-plugins/codex-plugin-cc.patch` — no other repo file changed across the whole issue. The spec appears because Phase 5's finding S1 corrected one falsified sentence in it in place (see *Standards review provenance* above); that edit landed in `bbc775d`, docs-only.

- [ ] **Step 8: `just build` and closure content checks**

Run (from `$WORKTREE`): `just build`
Expected: exits 0. Then:

```bash
STORE=$(nix-store -qR ./result | grep 'codex-plugin-cc-1\.0\.6' | head -n1)
echo "$STORE"                                                                                     # ...codex-plugin-cc-1.0.6-nix.db52e28f.p6
grep -c 'stdio: \["ignore", logFd, logFd\]' "$STORE/plugins/codex/scripts/codex-companion.mjs"     # 1
grep -c "pruneJobRecordsInStateDir(stateDir" "$STORE/plugins/codex/scripts/session-lifecycle-hook.mjs"  # 1
grep -c "overdue by" "$STORE/plugins/codex/scripts/lib/render.mjs"                                 # 1
grep -c "overdue by" "$STORE/plugins/codex/commands/status.md"                                     # 1
```
Expected: the `.p6` path and all four counts as annotated — proof the patch applies under nix's `patch -p1` and that the shipped closure carries all three acceptance criteria. (The prune grep is anchored on `(stateDir` because the bare symbol also matches the hook's import line; see Task 2 Step 9.)

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
- **R8 / AC4** (suite green env-scrubbed; `patchRevision` 5→6 with `just build` green): every task's suite gate (110 → 115 → 119 → 121 tests, `# fail 0`, `# skipped 4` throughout), Task 1 Steps 7-8 (bump + build), Task 4 Steps 7-8 (determinism, `patchRevision = 6`, `.p6` closure content checks).
