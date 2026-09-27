# Design: Reviewer reviews run as detached workers; the bridge makes only bounded foreground calls

Issue: https://github.com/fagenorn/nix-config/issues/3 · Base: codex-plugin-cc pinned at `db52e28f`, patch p4 (includes issue #2's truthful-terminal-states work) · Worktree branch: `worktree-issue-3-detached-reviewer-bridge`

## Problem

Codex plan-reviews die because their lifetime is chained to the Claude bridge agent's conversation lifetime. The `codex:codex-reviewer` bridge launches `codex-companion task --fresh --reviewer --timeout-ms 840000` as a harness background Bash task and then completes its turn; the harness kills a completed subagent's background process tree, so every compliant review is killed ~40 s in and the pipeline silently degrades to the native Claude fallback reviewer.

Falsifying evidence at base (2026-08-10, session `581dbb6b`): job `reviewer-msn70svo-bgjxnw` killed 42 s after launch, `CODEX_REVIEW_FAILURE: process terminated without producing reviewer output`. This is the second failure of the same shape: the previous round (commit `e4d9bf3`) replaced a foreground launch — killed at the harness's 600 s foreground Bash cap — with the background launch that now dies at subagent completion. Both rounds raced the harness; neither decoupled the review's lifetime from the agent's.

The runtime already owns everything needed to decouple them: a detached-worker background path (`enqueueBackgroundTask` → `spawnDetachedTaskWorker`, `detached: true`, `stdio: "ignore"`, `unref`), durable job records that store the result, `status <id> --wait --timeout-ms`, and `result <id> --json`. Issue #2 (merged, p4) made that machinery trustworthy: a status read probes the recorded worker pid, persists the dead-worker→`failed` flip, terminates `--wait` on it, and cleans the reviewer runtime on every terminal path. The only thing blocking the reviewer from using it is one guard: `Reviewer jobs must be fresh, foreground, and read-only.`

## Intent

Run every reviewer review as the runtime's own detached background worker, and reduce the bridge agent to a pure sequence of bounded foreground calls: enqueue (sub-second) → at most two bounded waits (each under the 600 s harness cap) → collect the recorded result verbatim. Killing the bridge — or the harness reaping its process tree at turn end — at any point after enqueue must leave the review running to completion with its result durable in the job record. Timeout layering stays defense-in-depth: the worker's internal 840 s budget is the correctness bound; the bridge's bounded waits exist for experience and surface a timely `CODEX_REVIEW_FAILURE:` carrying the job's recorded error. Launch mechanics get exactly one home (the bridge agent definition); the codex-collaboration skill states only the contract.

## Requirements (bound to acceptance criteria)

| # | Requirement | Acceptance criterion |
|---|---|---|
| R1 | `codex-companion task --fresh --reviewer --background --json` enqueues a detached worker and prints the queued JSON payload (with `jobId`) without waiting for the review — at base this combination throws. | AC1 |
| R2 | Reviewer invariants survive the guard change: reviewer + `--write` and reviewer + `--resume`/`--resume-last` are still refused; each reviewer job still runs fresh (no thread persistence, isolated per-job `CODEX_HOME`) and read-only (sandbox `read-only`, touched-files check). | AC2 |
| R3 | The bridge agent definition prescribes only foreground Bash calls, each with an explicit bound ≤ 600 000 ms, in the fixed sequence enqueue → bounded wait(s) → collect; it contains no `run_in_background`, no sleeps, no shell polling loops, and no completion-notification wait. | AC3 |
| R4 | Terminating the launcher (the enqueue CLI process, and with it the bridge's Bash process tree) after enqueue does not stop the review: the detached worker runs to a terminal state and the result remains collectable from the job record afterwards. | AC4 |
| R5 | A failed, cancelled, or timed-out job yields a single `CODEX_REVIEW_FAILURE:` line carrying the job's recorded error (`errorMessage`, else its `summary`), within the bridge's bounded wait budget (≤ 2 × 540 s of waits plus constant-time calls). | AC5 |
| R6 | The codex-collaboration skill's launch guidance states the contract only — fresh, isolated, read-only, ~15 min ceiling, `CODEX_REVIEW_FAILURE` semantics, capability fallback unchanged — and no longer mentions harness background tasks, completion notifications, or the launch command. | AC6 |
| R7 | The patched plugin's suite passes env-scrubbed (baseline at p4: `# tests 102 / # pass 98 / # fail 0 / # skipped 4`); reviewer-background coverage flips from refused-at-source to a tested enqueue path (see Test strategy note: p4 has no test asserting the old throw, so the flip lands as new tests that would have failed at p4). | AC7 |
| R8 | `patchRevision` bumps 4→5, `just build` succeeds, and one live plan-review through the skill is evidenced end-to-end (what ran, what it printed). | AC8 |

## Design options considered

**A — Reuse the runtime's detached background path; bridge waits in bounded `status --wait` chunks (chosen).** Lift `--background` from the reviewer guard so `enqueueBackgroundTask`/`spawnDetachedTaskWorker` own the review process; the bridge enqueues, waits with at most two foreground `status <id> --wait --timeout-ms 540000` calls, and collects via `result <id> --json`. The worker is `detached: true` + `unref` with `stdio: "ignore"` — its own process session, unreachable by the harness's turn-end tree kill — and records `pid: child.pid`, exactly the pid issue #2's liveness probe watches, so a crashed worker surfaces as a truthful `failed` through the same wait call. Framework-first: every piece already exists and is tested; the change to the runtime is one predicate.

**B — Keep the harness background task but forbid the bridge from completing its turn.** Rejected: correctness by prompt admonition. The issue's own decision log rules it out ("do not race it with poll loops or 'never end your turn' prompt admonitions") — a model that ends its turn anyway (or is killed) still destroys the review. This is the failure mode observed twice.

**C — Bridge-side daemonization (`setsid`/`nohup` around a foreground reviewer run).** Rejected: it duplicates the runtime's job bookkeeping outside the job record — no queued payload, no pid for the liveness probe, no durable result without inventing a second result channel, and cancel/status/session-cleanup would not know the process. "Framework-first": the runtime already has detached workers; a custom shell daemon is the custom X the framework has.

**D — A new dedicated `reviewer-worker` subcommand.** Rejected (YAGNI/DRY): `task-worker` already replays a stored request through `executeTaskRun`, which already handles `reviewer: true` (isolated runtime, read-only, touched-files check, cleanup). A parallel subcommand would be a second home for the same lifecycle.

Sub-choices within A — wait shape (2 × 540 s vs 540 + 420 vs 3 × 300), expiry behavior (report vs cancel), result channel (JSON extraction vs rendered stdout), timeout flag (omit vs explicit) — are settled in Auto-resolved decisions.

## Decisions

### Runtime: the guard is the only behavior change

`handleTask`'s reviewer guard drops the `options.background` arm:

```js
if (reviewer && (write || resumeLast)) {
  throw new Error("Reviewer jobs must be fresh and read-only.");
}
```

- Reviewer + `--background` now flows into the existing `options.background` branch: `buildTaskJob` (already reviewer-aware: `reviewer-` id prefix, `kind: "plan-review"`, `jobClass: "review"`) → `buildTaskRequest` (already carries `reviewer` and `timeoutMs`) → `enqueueBackgroundTask` → `spawnDetachedTaskWorker`. No changes to any of those functions.
- Foreground reviewer runs remain allowed — "only the foreground requirement is lifted" (issue) — so the p4 tests "reviewer tasks run foreground in a fresh read-only runtime and clean it up" and "parallel reviewers in one worktree receive distinct mutable runtimes" stay green unchanged, and interactive use keeps working.
- Reviewer + `--write` and reviewer + `--resume`/`--resume-last` still refuse with the reworded message. The usage string in `printUsage` needs no change (it already shows `[--background]` and `[--reviewer]` as independent flags).

Verified plumbing, requiring no edits (this is why the change is one predicate):

- **Timeout**: `timeoutMs` defaults to `840000` when `reviewer` is set and no `--timeout-ms` is given; it is computed before the background branch, stored in the job's `request` by `buildTaskRequest`, replayed by `handleTaskWorker` (`executeTaskRun({...request})`), and enforced by `runAppServerTurn`'s `Promise.race` hard timeout, whose rejection (`Codex job timed out after 840000ms.`) lands in the job record as `status: "failed"` + `errorMessage` via `runTrackedJob`'s catch path.
- **Isolation and cleanup in the worker**: `executeTaskRun` passes `reviewerJobId`, so `withAppServer` creates the per-job reviewer runtime and removes it in its `finally` — on success, failure, and the internal timeout. A hard-killed worker is covered by issue #2's flip path, which also removes the runtime.
- **Liveness**: `enqueueBackgroundTask` records `pid: child.pid`; the worker's own `running` write records the same pid (`runTrackedJob`: `pid: process.pid`). That is the pid `reconcileWorkerLiveness` probes, so a dead worker flips the job to `failed` on the bridge's next wait poll and `status --wait` returns promptly — the bridge's fast-fail on a dead worker is inherited, not built.
- **Result durability**: `runTrackedJob` persists `result: execution.payload` and `rendered` into the job file on completion. For a reviewer run the payload is `{status, threadId, rawOutput, touchedFiles, reasoningSummary}` — `rawOutput` is the reviewer's final message, byte-for-byte. `result <id> --json` returns `{job, storedJob}` with that payload intact.
- **Enqueue ordering**: `enqueueBackgroundTask` spawns the worker before writing the queued record. If the worker ever boots faster than the synchronous writes that follow spawn, it throws "No stored job found", exits, and the queued record's dead pid is flipped to `failed` by the first status read — the pre-existing race issue #2 already made truthful. Reused unchanged; not widened.

### Bridge agent definition (the single home for launch mechanics)

Full replacement body for the `codex:codex-reviewer` agent definition (frontmatter unchanged: `model: sonnet`, `tools: Bash, Read`). This text is binding on the plan; incidental wording may be polished, the prescribed calls and bounds may not.

```markdown
Act only as a transport for one Codex plan-review job.

- The dispatch message's first line is `WORKTREE_ROOT: <absolute path>`; everything
  after that line is the delegation prompt. If the line is absent, use the
  invocation directory as the root. Every Bash call below is foreground and
  bounded — the two wait calls set the Bash tool's `timeout` to 600000
  explicitly; every other call is sub-second and stays under the tool's default
  bound. Never pass `run_in_background`, never sleep, never write a polling loop.
- Pre-flight with one fast foreground Bash call: `command -v codex-companion`. If
  the command is missing, immediately return
  `CODEX_REVIEW_FAILURE: codex-companion not on PATH` without running anything else.
- Write the delegation prompt, unchanged, to a temporary file outside the repository.
- Enqueue exactly one review with one sub-second foreground call:
  `cd "<worktree-root>" && codex-companion task --fresh --reviewer --background --json < "<tmpfile>"`.
  The `cd` keys the runtime's job state to the reviewed worktree. Note the `jobId`
  from the printed JSON. From this moment a detached worker owns the review with
  its own 840 s budget; nothing that happens to you can stop it, and its result
  is durable in the job record.
- Wait with at most two foreground calls, run one after the other only while the
  job is still `queued` or `running`:
  `cd "<worktree-root>" && codex-companion status <jobId> --wait --timeout-ms 540000 --json`
  — each with the Bash tool's `timeout` parameter set to 600000. Read
  `job.status` from the printed JSON (the command exits 0 either way). Two
  540 s waits cover the worker's 840 s budget plus startup with margin.
- If `job.status` is `completed`, collect the result with one foreground call
  (temp paths beside the prompt file):
  `cd "<worktree-root>" && codex-companion result <jobId> --json > "<tmpdir>/result.json" && node -e 'const fs=require("node:fs");const o=JSON.parse(fs.readFileSync(process.argv[1],"utf8"))?.storedJob?.result?.rawOutput;if(typeof o!=="string"||!o)process.exit(3);fs.writeFileSync(process.argv[2],o)' "<tmpdir>/result.json" "<tmpdir>/review.md"`,
  then Read `<tmpdir>/review.md` and return its contents exactly. If the
  extraction exits non-zero, return
  `CODEX_REVIEW_FAILURE: job <jobId> completed without recorded reviewer output`.
- If `job.status` is `failed` or `cancelled`, return one line:
  `CODEX_REVIEW_FAILURE: ` followed by the job's `errorMessage`, else its
  `summary`, else `job <jobId> ended <status>`.
- If the job is still `queued` or `running` after the second wait, return one line:
  `CODEX_REVIEW_FAILURE: job <jobId> still <status> after 1080s of bounded waits
  (worker budget is 840s); check codex-companion status <jobId>`. Do not cancel
  the job — the worker's own timeout is the correctness bound.
- If any prescribed command itself fails, return a single line beginning
  `CODEX_REVIEW_FAILURE:` followed by its stderr or exit status.
- Run the whole sequence in this one turn without pausing; stopping early only
  delays the caller — it cannot harm the review, which is already detached with
  a durable result.
- Do not inspect the repository, interpret the request, edit files, run Git, retry,
  fall back to Claude analysis, or add commentary.
```

Why these numbers: each wait's CLI timeout (540 000 ms) returns within 540 s + one 2 s poll + process startup ≈ 543 s, leaving ~57 s slack under the 600 000 ms Bash tool bound (which must be set explicitly — the tool's default is 120 000 ms and would kill the wait). Worst-case wall clock from enqueue to a worker-written terminal state is ≤ ~865 s (worker spawn + runtime seed + app-server connect ≤ ~25 s, then the 840 s turn budget, then cleanup); two chunks give 1080 s of wait, a ≥ 200 s margin. A job still active after both chunks therefore means the worker's own timeout failed to fire — a wedged worker — which the bridge reports without killing, because a second kill mechanism racing the first is exactly the pattern that caused both prior rounds, and the result may still land and remain collectable.

The `node -e` extraction exists because no rendered output channel is verbatim: non-JSON `result` output appends `Codex session ID:`/`Resume in Codex:` trailer lines whenever the job has a `threadId` (reviewer jobs do), and asking the model to re-type a multi-hundred-line review from JSON risks silent corruption. `node` is on PATH (the repo ships `pkgs.nodejs`; `codex-companion` itself is a node wrapper). The short `jobId` (`reviewer-xxxxxxxx-xxxxxx`) is copied by the model from the small enqueue payload — a short stable handle, per the-bar's token-economy rule.

### Skill text: contract only, mechanics gone

`home/common/claude-code/skills/codex-collaboration/SKILL.md` changes in exactly three places; everything else (packet building, reviewer contract, verify-and-disposition, resolve policy) is untouched, and the caller-facing contract — three-section output, single `CODEX_REVIEW_FAILURE:` line on failure, capability fallback, one-time native fallback — is stable for from-issue Phase 5 and sdd's diff-review consumer.

1. **`## Launch`, second paragraph** — replace the plumbing narration (background Bash task, 840 s vs 600 s cap rationale, the launch command) with the contract:

   > Dispatch the plugin agent `codex:codex-reviewer` once with the complete packet.
   > Run it in the foreground, with the first line of the dispatch exactly
   > `WORKTREE_ROOT: <absolute worktree root>` so the bridge keys runtime job state
   > to the reviewed worktree. Launch mechanics live solely in that agent's
   > definition. The contract: the review runs fresh in an isolated read-only
   > Codex runtime (fresh `CODEX_HOME`, approval policy `never`, sandbox
   > `read-only`), survives the bridge's own lifetime, and is bounded by the
   > runtime's internal ~14 min budget — expect up to ~15 minutes wall clock. The
   > bridge returns the reviewer's output verbatim, or a single
   > `CODEX_REVIEW_FAILURE:` line carrying the review job's recorded error.

2. **`## Validate and fall back` failure classes** — the process-level class becomes a job-record class; four bullets become three:

   > - the executable is missing or authentication is unavailable;
   > - the agent returns `CODEX_REVIEW_FAILURE:` — the review job ended failed,
   >   cancelled, or timed out (including the runtime's hard timeout and
   >   dead-worker detection), with the job's recorded error on the line;
   > - the result is empty or malformed after one completed fresh run.

   (A crashed bridge agent shows up as the third class — empty or malformed output.)

3. **`## Operation: diff-review`, first paragraph** — "one foreground `codex:codex-reviewer` dispatch with background launch inside the bridge" loses the trailing mechanics clause: "one foreground `codex:codex-reviewer` dispatch".

The "Parallel reviews are valid" paragraph stays as is: it states contract (queued/active jobs are never a fallback reason; isolated runtimes don't share a broker), not mechanics — and parallel reviews now simply mean parallel detached workers with distinct job ids and runtimes, which p4's isolation tests already pin.

### Session-end boundary (documented, unchanged)

The plugin's SessionEnd hook still terminates and removes this session's `queued`/`running` jobs (and their reviewer runtimes). AC4's survival guarantee is about the failure actually observed — the harness reaping a completed subagent's process tree, and the death of the launcher/bridge — not about outliving the whole Claude session: a plan-review's only consumer is the session that requested it, so a worker outliving the session would be an orphan by definition, and upstream's session hygiene (pinned by the "session end fully cleans up jobs for the ending session" test) is intentional. The detached worker is unreachable by the turn-end tree kill (own process session via `detached: true`); it remains reachable by explicit `cancel` and by SessionEnd cleanup — both deliberate, human-or-lifecycle-owned kill paths.

## Test seams

Agreed seams — the plan and implementers inherit these and may not invent others (both are issue #2's seams, unchanged):

1. **The companion CLI subprocess surface**: `node scripts/codex-companion.mjs task|status|result … --json` run as child processes against a temp workspace with the fake codex on PATH. Prior art: upstream "task --background enqueues a detached worker and exposes per-job status" (the exact enqueue → wait → result shape this design gives the reviewer, including the `installFakeCodex(binDir, "slow-task")` fixture behavior that keeps the job active past enqueue-return) and the p4 foreground reviewer tests.
2. **The on-disk state contract**: job record JSON files, job logs, and reviewer runtime directories located via the exported resolvers (`resolveStateDir`/`resolveJobFile`, `resolveReviewerRuntimeHome`). Prior art: `tests/isolation.test.mjs`, `tests/liveness.test.mjs`.

Plus one narrow docs seam with `tests/commands.test.mjs` precedent ("internal docs use task terminology…"): text assertions over `plugins/codex/agents/codex-reviewer.md`, because AC3 is a claim about that file's contents.

## Test strategy

New behavior-named file `tests/reviewer-detach.test.mjs` (precedent: `isolation.test.mjs`, `liveness.test.mjs` — never grow the 2400-line `runtime.test.mjs`):

1. **Reviewer background run survives its launcher and lands a verbatim durable result** (R1, R4, and the AC1 sub-second claim asserted behaviorally): with `installFakeCodex(binDir, "slow-task")`, run `task --fresh --reviewer --background --json` via the synchronous `run` helper — when it returns, the launcher process has already exited. Assert the printed payload has `status: "queued"` and a `reviewer-`-prefixed `jobId` (the enqueue returned before the review ran — the behavioral form of "prints a job id in under a second", no stopwatch flakiness). Then `status <jobId> --wait --timeout-ms 15000 --json` → `completed`; then `result <jobId> --json` → `storedJob.result.rawOutput` equals the fake codex's exact final message (verbatim, lossless), `storedJob.kind === "plan-review"`; the reviewer runtime directory no longer exists; the canonical `CODEX_HOME`'s `config.toml` is untouched (isolation held on the background path).
2. **Guard boundaries that remain** (R2): `task --reviewer --write --background` exits non-zero with `Reviewer jobs must be fresh and read-only.`; same for `task --reviewer --resume-last --background`. These give the guard the failing tests it never had (see note below).
3. **The worker's internal timeout is enforced on the background path** (R5's error source, defense-in-depth): with `installFakeCodex(binDir, "interruptible-slow-task")` (5 s turn) and `--timeout-ms 1000`, enqueue in background; `status <jobId> --wait --timeout-ms 15000 --json` returns `failed` with `errorMessage` matching `Codex job timed out after 1000ms.`; the reviewer runtime directory is gone.
4. **Agent-definition contract** (R3, in `tests/commands.test.mjs` beside the existing docs tests): the agent file does not match `run_in_background` or `completion notification`; it matches the `--background --json` enqueue, `--wait --timeout-ms 540000`, and `CODEX_REVIEW_FAILURE:`.

No call-count assertions anywhere; every assertion is a printed payload, an on-disk record, or a directory's existence. Dead-worker fast-fail, `--wait` prompt termination, and flip-path runtime cleanup are already pinned by `tests/liveness.test.mjs` and are not re-tested.

**Baseline note (AC7's "flipped" test):** p4 has no test asserting that reviewer + `--background` throws — the guard's background arm was untested (verified by grep over the patch's tests; the-bar "Tests that can fail" flags exactly this). The flip therefore lands as: source guard rewritten, plus tests 1–3 above, each of which fails at p4 (test 1 and 3 throw at enqueue; test 2 asserts the new message). Suite expectation after the change: `# fail 0`, `# skipped 4` (unchanged upstream skips), test count = 102 + the new tests, exact count recorded in the plan's verification output.

## Verification loop (for the plan to turn into tasks)

Per the worktree CLAUDE.md's recorded workflow — the nix-store plugin copy is read-only; edits happen in a scratch clone and land only as the regenerated patch:

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

# regenerate (re-run `git add -N .` first if new files were created, e.g. tests/reviewer-detach.test.mjs):
git -C "$scratch" diff -U0 db52e28f4d9ded852ab3942cea316258ae4ef346 > "$WORKTREE/patches/agent-plugins/codex-plugin-cc.patch"

# bump patchRevision 4 -> 5 in lib/agent-plugins.nix, edit SKILL.md in the repo, then:
just build
```

**Live demo (AC8):** after the change is merged and activated (`just switch` — activation is the ship phase's call, not the implementer's), run one real `plan-review` through the codex-collaboration skill against a real plan. Evidence to capture — what ran and what it printed: the enqueue payload (jobId), the wait snapshot(s) showing `running` → `completed`, the returned review with `Blocking` / `Should fix` / `Discussion` sections, the job's terminal `completed` record, and the absence of any `CODEX_REVIEW_FAILURE` or Claude fallback. Record it following the `c4g2-evidence.md` precedent in `.claude/specs/` (the plan phase fixes the exact home).

## Out of scope

- Any change to `enqueueBackgroundTask`, `spawnDetachedTaskWorker`, `task-worker`, `status`, `result`, `cancel`, or the state/liveness machinery — the runtime change is the guard predicate only.
- SessionEnd cleanup policy (documented above as a deliberate boundary of AC4).
- The foreground reviewer path and its tests (stays allowed, stays green).
- Broker lifecycle, non-reviewer task flows, `review`/`adversarial-review` commands.
- Adding a Write tool (or any tool change) to the bridge agent — the temp-file-via-Bash pattern is proven in production runs.
- Retry logic in bridge or skill (the skill's one-time native fallback policy is unchanged).
- Contributing the change upstream.

## Auto-resolved decisions

### Launch mechanism: the runtime's own detached background path
- **Question:** Which mechanism decouples the review from the bridge's lifetime — the runtime's `--background` path, harness backgrounding with prompt admonitions, bridge-side `setsid`/`nohup`, or a new worker subcommand?
- **Choice:** Lift `--background` from the reviewer guard and reuse `enqueueBackgroundTask`/`spawnDetachedTaskWorker`/`task-worker` unchanged.
- **Grounding:** Issue Decisions ("Framework-first: the runtime already has detached workers, durable job records, `status --wait`, and `result` — use them"); upstream test "task --background enqueues a detached worker and exposes per-job status" proves the exact end-to-end shape; issue #2 made the path's failure modes truthful (`pid: child.pid` is precisely what `reconcileWorkerLiveness` probes).
- **Alternative considered:** Options B–D above — all rejected: B is correctness-by-admonition (the observed failure, twice), C/D duplicate job bookkeeping the runtime already owns.

### Guard predicate and message
- **Question:** Exact new reviewer guard — is foreground still allowed, and what does the error say?
- **Choice:** `if (reviewer && (write || resumeLast))` → `"Reviewer jobs must be fresh and read-only."`. Foreground reviewer runs remain allowed.
- **Grounding:** Issue: "The *fresh* and *read-only* reviewer invariants remain enforced …; only the foreground requirement is lifted." Keeping foreground preserves the two p4 foreground-reviewer tests unchanged and the interactive path. The message states exactly the invariants that remain — a message naming an unenforced property would lie.
- **Alternative considered:** Requiring `--background` for reviewers (foreground refused) — rejected: lifts one requirement by imposing its opposite, breaks two green tests, and no acceptance criterion asks for it.

### Bridge wait shape: two 540 s chunks
- **Question:** How does the bridge chunk its wait under the 600 s foreground Bash cap, given the worker's 840 s internal budget?
- **Choice:** At most two sequential `status <jobId> --wait --timeout-ms 540000 --json` calls, each with the Bash tool's `timeout` set explicitly to 600 000 ms (the tool default of 120 000 ms would kill the wait).
- **Grounding:** Arithmetic in the bridge section: each call returns ≈ 543 s worst case (57 s slack under the cap); two chunks = 1080 s ≥ 865 s worst-case wall clock with ≥ 200 s margin. Two identical calls are the simplest prescription a model executes reliably (token economy); the second runs only if the first reports the job still active — most reviews end inside the first.
- **Alternative considered:** 540 + 420 (asymmetric, same coverage, more prompt surface for no gain); 3 × 300 (a third call and two status parses for the same bound); one 590 s call (insufficient: 590 < 865, would misreport legitimate 10–14 min reviews as timeouts).

### Bridge budget expiry: report, never cancel
- **Question:** When both waits expire with the job still active, does the bridge cancel the job or report and leave it?
- **Choice:** Report `CODEX_REVIEW_FAILURE: job <id> still <status> after 1080s …` and leave the worker to its own 840 s timeout.
- **Grounding:** Issue Decisions ("Defense in depth: inner worker timeout for correctness, outer bounded waits for experience"). After 1080 s an active job means the inner timeout failed — a wedged worker; a bridge-side kill would be a second kill mechanism racing the first, the exact pattern behind both prior failure rounds, and would destroy a result that may still land and stay collectable. `cancel` remains available to a human via `/codex:status`/`/codex:cancel`.
- **Alternative considered:** `cancel <jobId>` on expiry — rejected as above; also turns an experience bound into a correctness actor.

### Result collection: `result --json` + mechanical extraction of `storedJob.result.rawOutput`
- **Question:** Which stored field carries the reviewer's output, and how does the bridge return it verbatim?
- **Choice:** `storedJob.result.rawOutput` (persisted by `runTrackedJob` from `executeTaskRun`'s payload; `result <id> --json` exposes it losslessly). The bridge extracts it with a `node -e` one-liner into a file, Reads the file, and returns its contents exactly.
- **Grounding:** Verified in source: worker stdio is `"ignore"`, so the job record is the only output channel; `rawOutput` is `result.finalMessage` byte-for-byte. Non-JSON `result` output is *not* verbatim — `renderStoredJobResult` appends `Codex session ID:`/`Resume in Codex:` trailer lines whenever `threadId` is set (reviewer jobs record one). Model re-typing from JSON risks silent corruption of a multi-hundred-line review; a file written by `node` (guaranteed on PATH — the repo ships `pkgs.nodejs`, and `codex-companion` is itself a node wrapper) plus the agent's existing Read tool is deterministic.
- **Alternative considered:** Return the rendered `result` stdout (carries the trailer — not verbatim); parse the job log's "Final output" block (log lines carry timestamps/prefixes); `jq` (not a guaranteed dependency of the plugin's environment; `node` is).

### Timeout plumbing: the bridge passes no `--timeout-ms`
- **Question:** Does the bridge pass `--timeout-ms 840000` explicitly, and does the enqueue path deliver it to the worker?
- **Choice:** Omit the flag. The runtime's reviewer default (`timeoutMs = 840000` when `--reviewer` and no flag) is computed in `handleTask` before the background branch, stored in the job's `request`, and enforced by the worker.
- **Grounding:** Verified: `buildTaskRequest` carries `timeoutMs`; `handleTaskWorker` replays the stored request; `runAppServerTurn` races the hard timeout; the rejection lands as the job's `errorMessage`. DRY: the 840 000 constant has exactly one authoritative home — the runtime default; repeating it in the agent prompt creates a second home that can drift. Token economy: defaults absorb the common case.
- **Alternative considered:** Explicit `--timeout-ms 840000` in the enqueue command (current agent-def practice) — rejected: duplicates the constant; legibility is preserved by the agent def *naming* the 840 s budget in prose without re-plumbing it.

### WORKTREE_ROOT first-line contract: unchanged
- **Question:** Does the bridge dispatch keep the `WORKTREE_ROOT: <absolute path>` first line?
- **Choice:** Yes, byte-for-byte, including the fallback to the invocation directory.
- **Grounding:** Job state is keyed by `resolveWorkspaceRoot(cwd)`; the `cd "<worktree-root>"` prefix on every companion call is what lands the job record, runtime dir, and result in the reviewed worktree's state dir — and both skill operations already mandate the line. Nothing about detaching changes the keying.
- **Alternative considered:** Passing `--cwd` instead of `cd` — equivalent behavior, needless churn against a proven convention.

### Detached-survival test: behavioral, at the CLI seam, no stopwatch
- **Question:** How does the suite prove "terminating the launcher does not stop the review" and sub-second enqueue without flaky timing or call-count assertions?
- **Choice:** Test 1 in Test strategy: synchronous `run` of the enqueue (launcher provably exited when it returns) with the `slow-task` fixture (job still active at that moment, pinned by asserting the payload's `status: "queued"`), then wait → `completed`, then `result --json` equality on `rawOutput`, runtime-dir absence, canonical-home untouched. "Sub-second" is asserted structurally — the enqueue prints the queued payload, not the review — never with a wall-clock measurement.
- **Grounding:** Upstream precedent "task --background enqueues a detached worker and exposes per-job status" (same helper, same fixture behavior, same three-call shape); the-bar "Tests that can fail" (observable behavior; a timing assertion fails for reasons other than the defect). The launcher's process group is empty by the time the job completes, so survival is proven by completion itself, not by asserting process-tree internals.
- **Alternative considered:** Spawning the launcher detached and SIGKILLing its process group mid-run — closer theater to the harness kill, but the group is already empty after `spawnSync` returns (ESRCH), so it asserts nothing test 1 doesn't; platform-dependent `ppid`/reparenting assertions rejected for the same reason.

### Skill-text scope: three precise edits
- **Question:** Exactly which SKILL.md sections change?
- **Choice:** (1) `## Launch` second paragraph → contract text (quoted in Decisions); (2) `## Validate and fall back` failure classes 4→3, the process class becoming a job-record class; (3) the diff-review operation paragraph drops "with background launch inside the bridge". Nothing else — packet lists, reviewer contract, disposition flow, "Parallel reviews are valid" paragraph, and both operations' output contracts stay byte-stable.
- **Grounding:** AC6 names the launch section and the mechanics/one-home rule (DRY: mechanics live only in the agent def); the failure-class edit is required for truthfulness because "the process crashes or reaches its hard timeout" is no longer an event the skill can observe — it reaches the skill as the bridge's `CODEX_REVIEW_FAILURE:` line carrying the job record's error. Callers (from-issue Phase 5, sdd diff-review) consume the output shape and the fallback policy, both unchanged.
- **Alternative considered:** Also rewriting the "Parallel reviews" paragraph — nothing in it narrates plumbing; touched text is review surface, so minimal diff wins.

### Session-end reap stays; AC4 is a launcher/turn-end guarantee
- **Question:** The SessionEnd hook kills and removes this session's queued/running jobs — does AC4 ("terminating the bridge (or its session) … does not stop the review") require exempting reviewer jobs?
- **Choice:** No exemption; document the boundary in the spec (Decisions section). Survival is guaranteed across the observed failure surface: bridge/subagent termination and the harness's turn-end process-tree kill.
- **Grounding:** The forensic failure is the turn-end tree kill of a *subagent's* background tasks; SessionEnd is a different, deliberate lifecycle (pinned by upstream's "session end fully cleans up jobs for the ending session" test, which p4 keeps green). A plan-review whose requesting session is gone has no consumer — an exemption would leak orphan workers and runtimes against upstream's hygiene policy for a case with no acceptance criterion.
- **Alternative considered:** Skipping `kind: "plan-review"` jobs in SessionEnd cleanup — rejected: YAGNI, breaks a green upstream-shape test, and reintroduces the leak class issue #2 closed.

### Enqueue prompt delivery and jobId extraction
- **Question:** How does the prompt reach the enqueue call, and how does the bridge capture the job id?
- **Choice:** Keep stdin redirection from the temp prompt file (`< "<tmpfile>"`); the model copies `jobId` from the small enqueue JSON payload.
- **Grounding:** The stdin path (`readStdinIfPiped`) is the current agent-def mechanism and is production-proven (the forensic run's job was created through it); the enqueue payload is 6 short fields and the id is a short stable handle (`reviewer-…`), the form the-bar's token-economy rule says models emit reliably — no shell capture plumbing needed.
- **Alternative considered:** `--prompt-file` (equivalent, churn); capturing the id into a shell variable across calls (Bash state does not persist between tool calls — each call re-`cd`s anyway).

### Agent-def text test (grill round)
- **Question:** Is a text assertion over the agent definition a legitimate test, given the-bar's dislike of assertions that don't observe behavior?
- **Choice:** Yes, one narrow docs test: no `run_in_background` / completion-notification language; the enqueue, `--wait --timeout-ms 540000`, and `CODEX_REVIEW_FAILURE:` markers present.
- **Grounding:** AC3 is itself a claim about the file's text — the prescribed calls and bounds — so text is the observable here, and `tests/commands.test.mjs` already pins doc contracts this way ("internal docs use task terminology…", hooks-text assertions). The test fails for exactly one reason: the agent def regressing toward harness backgrounding — the twice-observed failure mode.
- **Alternative considered:** No doc test (leave AC3 to review) — rejected: this is the one regression with two prior occurrences; cheap to pin.

### Explicit bounds cover every prescribed call (grill round)
- **Question:** AC3 requires "every Bash call it prescribes is foreground with an explicit bound ≤ 600 s" — do the sub-second calls (pre-flight, prompt write, enqueue, collect) each need an explicit `timeout` parameter too?
- **Choice:** No per-call flags; the agent definition states the bound rule once: the two wait calls set the tool `timeout` to 600 000 ms explicitly (mandatory — the 120 000 ms default would kill a 540 s wait), and every other call runs under the tool's default 120 000 ms bound, which is itself ≤ 600 s.
- **Grounding:** The harness bounds every foreground Bash call at its default unless raised — there is no unbounded foreground call to prevent; AC3's target is the absence of `run_in_background` and unbounded waiting, and the definition now says so in its opening bullet. Token economy: one standing rule beats a repeated parameter on five sub-second calls.
- **Alternative considered:** `timeout: 600000` on every call — rejected: noise that invites the model to treat slow non-wait calls as acceptable; a sub-second call that needs 10 minutes is itself a failure the default bound correctly surfaces.

### Wait-call resilience (grill round)
- **Question:** What if a wait call is cut off (user interrupt, harness kill) before printing JSON — does the bridge need a retry clause?
- **Choice:** No dedicated retry. The prescribed sequence is naturally resilient: `status --wait` is a stateless idempotent read, so a cut-off first wait simply means the second wait (or the failure line) acts on the next observed state; the catch-all `CODEX_REVIEW_FAILURE:` line covers a command that errors outright. Correctness never depends on the bridge at all — the job record keeps the result for the skill's caller regardless.
- **Grounding:** YAGNI (the interrupt case is outside the contract and non-fatal by construction); the-bar "Root causes" — retry loops in the bridge would re-race the harness instead of relying on the detachment that makes racing irrelevant.
- **Alternative considered:** "Re-run a cut-off wait once" clause — rejected: adds an unbounded-in-principle branch to a definition whose whole point (AC3) is a fixed bounded sequence.
